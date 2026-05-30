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


def _resolve_user_obj(user_id):
    """Retourne l'objet User Discord depuis l'ID, ou None si pas trouvé."""
    if _BOT_REF is None:
        return None
    try:
        uid_int = int(user_id)
    except Exception:
        return None
    try:
        u = _BOT_REF.get_user(uid_int)
        if u:
            return u
    except Exception:
        pass
    try:
        for g in _BOT_REF.guilds:
            m = g.get_member(uid_int)
            if m:
                return m
    except Exception:
        pass
    return None


def _resolve_avatar_url(user_id) -> str:
    """Retourne l'URL de la PP Discord d'un user, ou empty string si introuvable."""
    u = _resolve_user_obj(user_id)
    if not u:
        return ""
    try:
        return str(u.display_avatar.url)
    except Exception:
        try:
            return str(u.avatar.url) if u.avatar else ""
        except Exception:
            return ""


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
<html lang="fr"><head><title>VA Bot — Connexion</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#fafafa;color:#0a0a0a;min-height:100vh;display:flex;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;letter-spacing:-.01em}
.layout{display:flex;width:100%;min-height:100vh}
/* Panneau gauche : formulaire */
.left{flex:1;display:flex;align-items:center;justify-content:center;padding:48px 32px;background:#fff;
  min-width:0}
.card{width:100%;max-width:380px}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:48px;font-weight:800;font-size:22px;letter-spacing:-.03em}
.logo-mark{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#3b82f6,#a855f7);
  display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:18px;
  box-shadow:0 4px 14px rgba(59,130,246,.3)}
h1{font-size:30px;font-weight:800;letter-spacing:-.03em;margin-bottom:6px;color:#0a0a0a}
.subtitle{color:#6b7280;font-size:14px;margin-bottom:32px}
.field{margin-bottom:18px}
label{display:block;font-size:13px;font-weight:600;color:#374151;margin-bottom:6px}
label .req{color:#ef4444;font-weight:700;margin-left:2px}
input{width:100%;padding:11px 14px;background:#f9fafb;border:1px solid #e5e7eb;
  color:#0a0a0a;border-radius:9px;font-size:14px;font-family:inherit;
  transition:all .15s;outline:none}
input:focus{border-color:#3b82f6;background:#fff;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
input::placeholder{color:#9ca3af}
.row-links{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;font-size:13px}
.row-links a{color:#3b82f6;text-decoration:none;font-weight:500}
.row-links a:hover{text-decoration:underline}
.row-links .muted{color:#6b7280;font-weight:500}
.remember-row{display:flex;align-items:center;gap:10px;margin-bottom:22px;cursor:pointer;font-size:13px;color:#374151;user-select:none}
.remember-row input[type=checkbox]{position:absolute;opacity:0;pointer-events:none}
.remember-check{width:18px;height:18px;border:1.5px solid #d1d5db;border-radius:5px;display:flex;align-items:center;justify-content:center;background:#fff;transition:all .15s;flex-shrink:0}
.remember-check svg{width:12px;height:12px;display:none}
.remember-row input[type=checkbox]:checked + .remember-check{background:#3b82f6;border-color:#3b82f6}
.remember-row input[type=checkbox]:checked + .remember-check svg{display:block}
.remember-row:hover .remember-check{border-color:#3b82f6}
.remember-hint{color:#9ca3af;font-size:11px;margin-left:auto;font-weight:400}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:13px;background:#3b82f6;color:#fff;border:0;border-radius:9px;
  font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .15s;
  box-shadow:0 1px 2px rgba(59,130,246,.15);min-height:46px}
.btn:hover{background:#2563eb;box-shadow:0 4px 14px rgba(59,130,246,.35);transform:translateY(-1px)}
.btn:active{transform:translateY(0)}
.btn:disabled{cursor:wait;opacity:.85;transform:none}
.btn:disabled:hover{transform:none;box-shadow:0 1px 2px rgba(59,130,246,.15)}
/* Spinner Insta-style pour le bouton de login */
.spinner{width:18px;height:18px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;display:inline-block;animation:spin .7s linear infinite;flex-shrink:0}
.btn .spinner{display:none}
.btn.loading .spinner{display:inline-block}
.btn.loading .label{display:none}
@keyframes spin{to{transform:rotate(360deg)}}
.footer-note{margin-top:28px;text-align:center;color:#6b7280;font-size:13px}
.footer-note a{color:#3b82f6;text-decoration:none;font-weight:500}
.footer-note a:hover{text-decoration:underline}
.err{background:#fee2e2;border:1px solid #fecaca;color:#dc2626;padding:11px 14px;
  border-radius:9px;font-size:13px;margin-bottom:20px;font-weight:500;
  display:flex;align-items:center;gap:8px}
/* Panneau droit : visuel */
.right{flex:1;background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#3b0764 100%);
  display:flex;align-items:center;justify-content:center;padding:48px;
  position:relative;overflow:hidden}
.right::before{content:'';position:absolute;inset:-50%;
  background:radial-gradient(circle at 30% 50%,rgba(59,130,246,.15),transparent 60%),
             radial-gradient(circle at 70% 20%,rgba(168,85,247,.12),transparent 50%);
  animation:drift 20s ease-in-out infinite}
@keyframes drift{0%,100%{transform:translate(0,0)}50%{transform:translate(20px,-20px)}}
.brand{position:relative;text-align:center;color:#fff;max-width:420px}
.brand h2{font-size:32px;font-weight:800;letter-spacing:-.03em;margin-bottom:14px;line-height:1.2}
.brand p{font-size:15px;color:rgba(255,255,255,.7);line-height:1.6}
.stats{display:flex;gap:28px;justify-content:center;margin-top:36px;padding-top:28px;
  border-top:1px solid rgba(255,255,255,.1)}
.stat-item{text-align:center}
.stat-v{font-size:22px;font-weight:800;letter-spacing:-.02em}
.stat-l{font-size:11px;color:rgba(255,255,255,.6);text-transform:uppercase;letter-spacing:.08em;
  font-weight:600;margin-top:4px}
@media (max-width:900px){
  .right{display:none}
  .layout{justify-content:center}
}
/* Page loader global - même style que dashboard */
#page-loader{position:fixed;inset:0;background:rgba(15,15,15,.92);z-index:99999;display:none;align-items:center;justify-content:center;backdrop-filter:blur(6px)}
#page-loader.show{display:flex}
#page-loader .pl-ring{width:54px;height:54px;border:4px solid rgba(59,130,246,.15);border-top-color:#3b82f6;border-radius:50%;animation:plSpin .8s linear infinite}
@keyframes plSpin{to{transform:rotate(360deg)}}
</style></head><body>
<div id="page-loader"><div class="pl-ring"></div></div>
<div class="layout">
  <div class="left">
    <div class="card">
      <div class="logo">
        <div class="logo-mark">VA</div>
        <span>VA Bot</span>
      </div>
      <h1>Connexion</h1>
      <p class="subtitle">Content de te revoir</p>
      {err}
      <form method="POST" autocomplete="on">
        <div class="field">
          <label>Username<span class="req">*</span></label>
          <input type="text" name="username" id="login-username" placeholder="samaali" value="samaali" autocomplete="username" autofocus>
        </div>
        <div class="field">
          <label>Mot de passe<span class="req">*</span></label>
          <input type="password" name="password" placeholder="••••••••" autocomplete="current-password" required>
        </div>
        <label class="remember-row">
          <input type="checkbox" name="remember" id="login-remember" value="1">
          <span class="remember-check"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></span>
          <span>Se souvenir de moi</span>
          <span class="remember-hint">(30 jours)</span>
        </label>
        <button type="submit" class="btn" id="login-btn"><span class="label">Se connecter →</span><span class="spinner"></span></button>
      </form>
      <script>
        // Pré-remplir username depuis localStorage si l'user s'était souvenu
        try{
          var savedUser = localStorage.getItem('vabot_remembered_user');
          if(savedUser){
            document.getElementById('login-username').value = savedUser;
            document.getElementById('login-remember').checked = true;
          }
        }catch(e){}
        document.querySelector('form').addEventListener('submit', function(){
          // Sauver / oublier le username selon la checkbox
          try{
            var remember = document.getElementById('login-remember').checked;
            var u = document.getElementById('login-username').value.trim();
            if(remember && u){
              localStorage.setItem('vabot_remembered_user', u);
            } else {
              localStorage.removeItem('vabot_remembered_user');
            }
          }catch(e){}
          var b = document.getElementById('login-btn');
          if(b){ b.classList.add('loading'); b.disabled = true; }
          var pl = document.getElementById('page-loader');
          if(pl) setTimeout(function(){ pl.classList.add('show'); }, 300);
        });
        window.addEventListener('pageshow', function(){
          var pl = document.getElementById('page-loader');
          if(pl) pl.classList.remove('show');
        });
      </script>
      <div class="footer-note">Privé · accès réservé</div>
    </div>
  </div>
  <div class="right">
    <div class="brand">
      <h2>Pilote ton agence depuis une seule interface</h2>
      <p>Upload contenu, planification SFS, suivi des ventes MyPuls en temps réel, paiements chatteurs, et bien plus.</p>
      <div class="stats">
        <div class="stat-item"><div class="stat-v">5</div><div class="stat-l">Modèles</div></div>
        <div class="stat-item"><div class="stat-v">160+</div><div class="stat-l">Chatteurs</div></div>
        <div class="stat-item"><div class="stat-v">24/7</div><div class="stat-l">Sync auto</div></div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""

UPLOAD_HTML = """
<!DOCTYPE html>
<html><head><title>VA Bot Dashboard</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;background:#0f0f0f;color:#eee;margin:0;padding:0;min-height:100vh;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;letter-spacing:-.01em}

/* ============ PAGE LOADER GLOBAL (entre 2 navigations) ============ */
#page-loader{position:fixed;inset:0;background:rgba(15,15,15,.92);z-index:99999;display:none;align-items:center;justify-content:center;backdrop-filter:blur(6px);animation:fadeIn .2s}
#page-loader.show{display:flex}
#page-loader .pl-ring{width:54px;height:54px;border:4px solid rgba(59,130,246,.15);border-top-color:#3b82f6;border-radius:50%;animation:plSpin .8s linear infinite}
@keyframes plSpin{to{transform:rotate(360deg)}}
body.light #page-loader,html.light-pre #page-loader{background:rgba(249,250,251,.92)}
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
/* Cercle de sélection rond — frosted white pour rester lisible sur n'importe quelle image */
.sel-circle{display:block;width:24px;height:24px;border-radius:50%;
  background:rgba(255,255,255,.85);border:2px solid #fff;
  backdrop-filter:blur(8px);transition:all .15s;position:relative;
  box-shadow:0 2px 6px rgba(0,0,0,.2)}
.sel-circle-wrap:hover .sel-circle{background:#fff;transform:scale(1.08);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.sel-cb:checked + .sel-circle{background:#3b82f6;border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.25),0 4px 12px rgba(59,130,246,.3)}
.sel-cb:checked + .sel-circle::after{content:'';position:absolute;left:50%;top:50%;width:11px;height:7px;border-left:2.5px solid #fff;border-bottom:2.5px solid #fff;transform:translate(-55%,-65%) rotate(-45deg)}
/* Bouton edit crayon sur les cards — frosted white aussi */
.card-edit-btn{background:rgba(255,255,255,.85);border:0;color:#1a1a1a;width:28px;height:28px;
  border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;
  padding:0;backdrop-filter:blur(8px);transition:all .15s;
  box-shadow:0 2px 6px rgba(0,0,0,.2)}
.card-edit-btn:hover{background:#3b82f6;color:#fff;transform:scale(1.08);box-shadow:0 4px 12px rgba(59,130,246,.4)}

/* Items de la sidebar - smooth hover */
.sidebar .item,.sidebar .group-head,.sidebar .subgroup-head,.sidebar .logout-btn{transition:background .15s,color .15s,padding-left .15s}
.sidebar .item:hover{padding-left:14px}

/* Sub-tabs */
.subtab{transition:color .15s,border-color .15s}

/* Boutons - hover lift */
button[type=submit],.btn,.danger-btn{transition:transform .12s ease,background .15s,box-shadow .15s}
button[type=submit]:hover,.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(59,130,246,.3)}
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
input:focus,select:focus,textarea:focus{outline:0;border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.15);transition:border-color .15s,box-shadow .15s}

/* Sort options hover */
.ig-sort-opt{transition:background .12s,color .12s,padding-left .12s}
.ig-sort-opt:hover{padding-left:18px}

/* Loading skeleton effect (utile plus tard) */
.skeleton{background:linear-gradient(90deg,#1a1a1a 0%,#2a2a2a 50%,#1a1a1a 100%);background-size:200% 100%;animation:shimmer 1.5s infinite}

/* ============ TOAST NOTIFICATIONS ============ */
.toast-container{position:fixed;top:24px;right:24px;display:flex;flex-direction:column;gap:10px;z-index:9999;pointer-events:none;max-width:420px}
.toast{background:#1a1a1a;border:1px solid #2a2a2a;border-left:4px solid #3b82f6;border-radius:10px;padding:14px 18px;color:#fff;font-size:14px;box-shadow:0 12px 32px rgba(0,0,0,.6);display:flex;align-items:flex-start;gap:12px;pointer-events:auto;animation:toastIn .4s cubic-bezier(.16,1,.3,1);min-width:280px;backdrop-filter:blur(10px)}
.toast.success{border-left-color:#00d68f;background:#0f1f17}
.toast.error{border-left-color:#ff4757;background:#1f0f0f}
.toast.info{border-left-color:#3b82f6}
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
/* Item standalone (Dashboard tout en haut) */
.sidebar .solo-group{padding:0 12px 8px;margin-bottom:4px;border-bottom:1px solid #1a1a1a}
.sidebar .solo-item{display:flex;align-items:center;gap:12px;width:100%;padding:11px 14px;background:transparent;border:0;color:#aaa;font-size:14px;font-weight:600;cursor:pointer;border-radius:8px;font-family:inherit;text-align:left;letter-spacing:-.01em;margin-bottom:4px}
.sidebar .solo-item svg{width:18px;height:18px;flex-shrink:0}
.sidebar .solo-item:hover{background:rgba(255,255,255,.05);color:#fff}
.sidebar .solo-item.active{background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(168,85,247,.1));color:#3b82f6;box-shadow:0 0 0 1px rgba(59,130,246,.2) inset}
body.light .sidebar .solo-item{color:#4b5563}
body.light .sidebar .solo-item:hover{background:#f3f4f6;color:#111827}
body.light .sidebar .solo-item.active{background:linear-gradient(135deg,#dbeafe,#ede9fe);color:#3b82f6;box-shadow:0 0 0 1px rgba(59,130,246,.25) inset}
body.light .sidebar .solo-group{border-bottom-color:#e5e7eb}
/* SFS responsive : stack sur petits écrans */
@media(max-width:1300px){.sfs-layout{grid-template-columns:200px 1fr!important}.sfs-layout > div:last-child{grid-column:1/-1}}
@media(max-width:900px){.sfs-layout{grid-template-columns:1fr!important}}

/* =============== LIGHT MODE (DEFAULT) =============== */
body.light{background:#f9fafb!important;color:#111827!important}
body.light .sidebar{background:#fff!important;border-right-color:#e5e7eb!important}
body.light .sidebar .group-head{color:#4b5563}
body.light .sidebar .item{color:#6b7280}
body.light .sidebar .group-head:hover,body.light .sidebar .item:hover{background:#f3f4f6!important;color:#111827}
body.light .sidebar .item.active{background:#dbeafe!important;color:#3b82f6!important}
body.light .sidebar .item.active svg{color:#3b82f6}
body.light .sidebar .group-head.active{background:#f3f4f6!important;color:#111827}
body.light .sidebar .group-head.active svg.lead{color:#3b82f6}
body.light .sidebar .group .items{border-left-color:#e5e7eb}
body.light .sidebar .section-label{color:#9ca3af}
body.light .sidebar .sep{background:#e5e7eb}
body.light .sidebar .logout-btn{color:#6b7280}
body.light .sidebar .logout-btn:hover{background:#fef2f2;color:#dc2626}
body.light .main{color:#111827}
body.light .main h1,body.light .main h2,body.light .main h3,body.light .main h4{color:#111827}
body.light .box{background:#fff!important;border-color:#e5e7eb!important;color:#111827;box-shadow:0 1px 2px rgba(0,0,0,.04)}
body.light label{color:#374151}
body.light small{color:#6b7280}
body.light input[type=text],body.light input[type=password],body.light input[type=number],body.light input[type=date],body.light input[type=time],body.light input[type=file],body.light select,body.light textarea{background:#fff!important;border-color:#d1d5db!important;color:#111827!important}
body.light input:focus,body.light select:focus,body.light textarea:focus{border-color:#3b82f6!important;box-shadow:0 0 0 3px rgba(59,130,246,.1)}
body.light table th{background:#f9fafb!important;color:#374151!important;border-color:#e5e7eb}
body.light table td{border-color:#e5e7eb!important;color:#374151}
body.light .stat{background:#fff!important;border-color:#e5e7eb!important;box-shadow:0 1px 2px rgba(0,0,0,.04)}
body.light .stat .l{color:#6b7280}
body.light code{background:#f3f4f6!important;color:#111827}
body.light .subtab{color:#6b7280}
body.light .subtab.active{color:#3b82f6}
body.light .reel-card,body.light .cloud-card{background:#fff!important;border-color:#e5e7eb!important;color:#111827}
body.light .toast{background:#fff!important;border-color:#e5e7eb!important;color:#111827;box-shadow:0 8px 24px rgba(0,0,0,.1)}
body.light .toast.success{background:#f0fdf4!important;border-left-color:#10b981!important;color:#065f46}
body.light .toast.error{background:#fef2f2!important;border-left-color:#ef4444!important;color:#991b1b}
body.light .toast.warning{background:#fffbeb!important;border-left-color:#f59e0b!important;color:#92400e}
body.light .confirm-box{background:#fff!important;border-color:#e5e7eb!important;color:#111827}
body.light .confirm-box h3{color:#111827}
body.light .confirm-box p{color:#6b7280}
body.light .confirm-box .btn-cancel{background:#f3f4f6!important;color:#374151!important}
/* Inputs/selects backgrounds qui utilisent #0f0f0f en inline */
body.light [style*="background:#0f0f0f"]{background:#f9fafb!important}
body.light [style*="background:#1a1a1a"]{background:#fff!important}
body.light [style*="background:#0a0a0a"]{background:#fff!important}
body.light [style*="background:#000"]{background:#fff!important}
body.light [style*="border:1px solid #2a2a2a"]{border-color:#e5e7eb!important}
body.light [style*="border:1px solid #1a1a1a"]{border-color:#e5e7eb!important}
body.light [style*="border:1px solid #333"]{border-color:#d1d5db!important}
body.light [style*="color:#fff"]:not(.toast):not(button){color:#111827!important}
body.light [style*="color:#aaa"]{color:#6b7280!important}
body.light [style*="color:#888"]{color:#9ca3af!important}
body.light [style*="color:#666"]{color:#9ca3af!important}
body.light [style*="color:#ccc"]{color:#374151!important}
body.light [style*="background:rgba(0,0,0,.6)"]{background:rgba(255,255,255,.85)!important}
body.light [style*="background:rgba(0,0,0,.5)"]{background:rgba(255,255,255,.85)!important}
body.light .sidebar .ico .tip{background:#111827;color:#fff}
body.light .danger-btn{background:#ef4444!important;color:#fff!important}
body.light a{color:#3b82f6}
body.light .subtabs{border-bottom-color:#e5e7eb}
/* Calendrier SFS en light mode */
body.light .sfs-day{border-color:#e5e7eb!important;background:#fff!important;color:#111827!important}
body.light .sfs-day:hover{background:#f3f4f6!important}
body.light .sfs-day > div:first-child{color:#111827!important}
body.light .sfs-day[style*="background:#0f1a2e"]{background:#eff6ff!important}
body.light .sfs-day[style*="background:#1f1410"]{background:#eff6ff!important}
body.light .sfs-day[style*="background:#15100d"]{background:#f3f4f6!important}
body.light .sfs-ident-row.active{background:rgba(59,130,246,.1)!important;color:#3b82f6!important}

/* === Selected day (les 2 modes) === */
.sfs-day.selected{box-shadow:inset 0 0 0 2px #3b82f6}
body:not(.light) .sfs-day.selected{background:#0f1a2e!important}
body.light .sfs-day.selected{background:#eff6ff!important}

/* === Today (les 2 modes) === */
body:not(.light) .sfs-day[style*="background:#0f1a2e"]{background:#0f1a2e!important}
body.light .sfs-day[style*="background:#0f1a2e"]{background:#eff6ff!important}
.sidebar .group{display:flex;flex-direction:column;margin:0 10px}
.sidebar .group-head{display:flex;align-items:center;gap:12px;padding:10px 12px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;width:100%;text-align:left;margin:0;border-radius:8px;transition:all .15s}
.sidebar .group-head:hover{background:#181818;color:#fff}
.sidebar .group-head.active{background:#181818;color:#fff}
.sidebar .group-head svg.lead{width:18px;height:18px;flex-shrink:0;color:#888}
.sidebar .group-head.active svg.lead{color:#3b82f6}
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
.sidebar .group .item.active{color:#3b82f6;background:#181818}
.sidebar .group .item.active svg{color:#3b82f6}
.sidebar .group .item.soon{cursor:not-allowed;opacity:.6}
.sidebar .group .item .badge{padding:2px 6px;font-size:9px;background:#3b82f6;color:#fff;border-radius:4px;font-weight:700;letter-spacing:.5px}
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
/* ============ Styled file inputs (no more ugly "Choose File") ============ */
input[type="file"]{padding:0;background:transparent;border:0;color:#aaa;font-size:13px;cursor:pointer;line-height:1.4}
input[type="file"]::file-selector-button,
input[type="file"]::-webkit-file-upload-button{
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#fff;border:0;padding:11px 18px;border-radius:8px;font-size:13px;
  font-weight:600;cursor:pointer;font-family:inherit;margin-right:14px;
  transition:all .15s;letter-spacing:.01em;
  box-shadow:0 1px 3px rgba(59,130,246,.25)
}
input[type="file"]::file-selector-button:hover,
input[type="file"]::-webkit-file-upload-button:hover{
  background:linear-gradient(135deg,#2563eb,#1d4ed8);
  box-shadow:0 4px 12px rgba(59,130,246,.35);transform:translateY(-1px)
}
/* Light mode override */
body.light input[type="file"]{color:#666}
body.light input[type="file"]::file-selector-button,
body.light input[type="file"]::-webkit-file-upload-button{
  background:linear-gradient(135deg,#3b82f6,#2563eb)!important;color:#fff!important
}
button[type=submit],.btn{padding:12px 24px;background:#3b82f6;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;margin-top:16px;transition:all .15s}
button[type=submit]:hover,.btn:hover{background:#2563eb;box-shadow:0 4px 14px rgba(59,130,246,.3);transform:translateY(-1px)}
button[type=submit]:active,.btn:active{transform:translateY(0)}
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
.stat .v{font-size:28px;font-weight:700;color:#3b82f6}
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
// === THEME (light/dark) ===
function setTheme(theme){
  if(theme === 'light'){
    document.body.classList.add('light');
  } else {
    document.body.classList.remove('light');
  }
  try{ localStorage.setItem('vabot_theme', theme); }catch(e){}
  // Mettre à jour la sélection visuelle des cards
  document.querySelectorAll('.theme-card').forEach(function(c){
    if(c.dataset.theme === theme){
      c.style.outline = '3px solid #3b82f6';
      c.style.outlineOffset = '2px';
    } else {
      c.style.outline = '';
    }
  });
  if(typeof showToast === 'function'){
    showToast('🎨 Thème ' + (theme === 'light' ? 'clair' : 'sombre') + ' activé', 'success', 2000);
  }
}
// Appliquer le thème au plus tôt (avant render) - défaut : clair
(function(){
  try{
    var saved = localStorage.getItem('vabot_theme') || 'light';
    if(saved === 'light'){
      document.documentElement.classList.add('pre-light');
      document.addEventListener('DOMContentLoaded', function(){
        document.body.classList.add('light');
        document.querySelectorAll('.theme-card[data-theme="light"]').forEach(function(c){
          c.style.outline = '3px solid #3b82f6';
          c.style.outlineOffset = '2px';
        });
      });
    } else {
      document.addEventListener('DOMContentLoaded', function(){
        document.querySelectorAll('.theme-card[data-theme="dark"]').forEach(function(c){
          c.style.outline = '3px solid #3b82f6';
          c.style.outlineOffset = '2px';
        });
      });
    }
  }catch(e){}
})();
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
// === PAGE LOADER GLOBAL ===
var _pageLoaderTimeout = null;
function showPageLoader(){
  var pl = document.getElementById('page-loader');
  if(pl) pl.classList.add('show');
  // Safety : auto-hide après 20s si la navigation se bloque
  if(_pageLoaderTimeout) clearTimeout(_pageLoaderTimeout);
  _pageLoaderTimeout = setTimeout(hidePageLoader, 20000);
}
function hidePageLoader(){
  var pl = document.getElementById('page-loader');
  if(pl) pl.classList.remove('show');
  if(_pageLoaderTimeout){ clearTimeout(_pageLoaderTimeout); _pageLoaderTimeout = null; }
}
// Cacher au load de la page (si visible depuis navigation précédente)
window.addEventListener('pageshow', hidePageLoader);
window.addEventListener('load', hidePageLoader);
// Escape clavier = cacher le loader (filet de sécurité)
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape'){ hidePageLoader(); }
});
// Clic sur le loader lui-même = le cacher
document.addEventListener('click', function(e){
  var pl = document.getElementById('page-loader');
  if(pl && pl.classList.contains('show') && (e.target === pl || pl.contains(e.target))){
    hidePageLoader();
  }
}, true);
// Afficher pendant la navigation (clic sur lien interne, submit form)
document.addEventListener('click', function(e){
  var a = e.target.closest('a[href]');
  if(!a) return;
  // Skip si data-no-loader (genre tabs internes, nav rapide)
  if(a.dataset.noLoader || a.closest('[data-no-loader]')) return;
  var href = a.getAttribute('href') || '';
  if(!href || href.startsWith('#') || href.startsWith('javascript:') || a.target === '_blank') return;
  if(e.ctrlKey || e.metaKey || e.shiftKey) return;
  try{
    var url = new URL(href, window.location.origin);
    if(url.origin !== window.location.origin) return;
  }catch(_){}
  showPageLoader();
}, true);
document.addEventListener('submit', function(e){
  var form = e.target;
  if(!form || form.dataset.noLoader) return;
  // Ignorer les forms qui submit-en-ajax (ex: change handlers)
  if(form.action && form.action.indexOf('javascript:') === 0) return;
  // Skip si le form a un bouton avec data-confirm — ces forms passent par un modal
  // de confirmation, le loader doit attendre que l'user confirme (sinon il s'affiche
  // pendant le modal et reste bloqué si l'user annule).
  if(form.querySelector && form.querySelector('[data-confirm]') && !form.dataset.confirmed) return;
  setTimeout(showPageLoader, 150);
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
    if(btn) btn.click();  // Synchrone (pas de setTimeout pour éviter flicker)
  }
});
// === Reel hover play + expand panel ===
window.igHoverPlay = function(media){
  if(!media) return;
  var v = media.querySelector('.reel-video');
  if(!v) return;
  try{ v.muted = true; v.currentTime = 0; }catch(e){}
  v.style.opacity = '1';
  var p = v.play();
  if(p && p.catch) p.catch(function(){});
};
window.igHoverStop = function(media){
  if(!media) return;
  var v = media.querySelector('.reel-video');
  if(!v) return;
  try{ v.pause(); }catch(e){}
  v.style.opacity = '0';
};
window.toggleReelExpand = function(card){
  if(!card) return;
  var panel = card.querySelector('.reel-expand');
  var chev = card.querySelector('.reel-chevron');
  if(!panel) return;
  var isOpen = panel.style.display !== 'none' && panel.style.display !== '';
  if(isOpen){
    panel.style.display = 'none';
    if(chev) chev.style.transform = 'rotate(0deg)';
  } else {
    panel.style.display = '';
    if(chev) chev.style.transform = 'rotate(180deg)';
    // Charge la duree depuis le video element
    var v = card.querySelector('.reel-video');
    var label = panel.querySelector('.reel-dur-label');
    if(v && label){
      if(v.duration && !isNaN(v.duration)){
        var d = Math.round(v.duration);
        label.textContent = Math.floor(d/60) + ':' + ('0' + (d%60)).slice(-2);
      } else {
        // Pas encore chargee : ecoute l'event loadedmetadata
        v.addEventListener('loadedmetadata', function(){
          if(v.duration && !isNaN(v.duration)){
            var d = Math.round(v.duration);
            label.textContent = Math.floor(d/60) + ':' + ('0' + (d%60)).slice(-2);
          }
        }, {once:true});
        // Force le chargement si preload='none'
        if(v.preload === 'none') v.preload = 'metadata';
        try{ v.load(); }catch(e){}
      }
    }
  }
};

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
  bar.style.display = n === 0 ? 'none' : 'block';
  var lbl = document.getElementById('sel-count');
  if(lbl) lbl.textContent = n;
}
function clearSelection(){
  selectedFiles.clear();
  document.querySelectorAll('.sel-cb').forEach(function(cb){ cb.checked = false; });
  updateActionBar();
}
// Lightbox style Infloww : navigation prev/next + compteur + édition caption/desc
var lbGallery = [];   // {url, isVideo, name, fileId}
var lbIndex = 0;
var lbEditMode = false;
function lbCollectGallery(){
  lbGallery = [];
  // IMPORTANT : ne collecter QUE les cartes de l'onglet (form-section) actuellement
  // visible — sinon on navigue à travers tous les Reels + Posts + Stories de toutes
  // les identités à la fois (167 fichiers !).
  var visibleSection = null;
  document.querySelectorAll('.form-section').forEach(function(sec){
    if(sec.offsetParent !== null) visibleSection = sec;  // visible (pas display:none)
  });
  var scope = visibleSection || document;
  scope.querySelectorAll('.cloud-card').forEach(function(card){
    var wrap = card.querySelector('[onclick*="openLightbox"]');
    if(!wrap) return;
    var oc = wrap.getAttribute('onclick') || '';
    var m = oc.match(/openLightbox\("([^"]+)",(true|false),"([^"]*)",?"?([^"]*)"?,?"?([^"]*)"?\)/);
    if(m) lbGallery.push({
      url: m[1], isVideo: m[2]==='true', name: m[3],
      fileId: m[4] || '', exampleUrl: m[5] || ''
    });
  });
}
function lbRender(){
  if(lbIndex < 0) lbIndex = 0;
  if(lbIndex >= lbGallery.length) lbIndex = lbGallery.length - 1;
  var it = lbGallery[lbIndex];
  if(!it) return;
  var content = document.getElementById('lightbox-content');
  if(it.isVideo){
    var mainVideo = '<video controls autoplay playsinline preload="metadata" src="'+it.url+'" '
      + 'style="max-width:100%;max-height:calc(100vh - 120px);height:auto;width:auto"></video>';
    if(it.exampleUrl){
      // Affichage côte-à-côte : vidéo principale + exemple (muet, autoplay loop pour preview)
      content.innerHTML =
        '<div class="lb-dual-video">' +
          '<div class="lb-dual-item">' +
            '<div class="lb-dual-label">Avec captions</div>' +
            mainVideo +
          '</div>' +
          '<div class="lb-dual-item">' +
            '<div class="lb-dual-label">Original (clean)</div>' +
            '<video controls muted loop playsinline preload="metadata" src="'+it.exampleUrl+'" '
              + 'style="max-width:100%;max-height:calc(100vh - 120px);height:auto;width:auto"></video>' +
          '</div>' +
        '</div>';
    } else {
      content.innerHTML = mainVideo;
    }
  } else {
    content.innerHTML = '<img src="'+it.url+'" alt="'+(it.name||'').replace(/"/g,'')+'">';
  }
  var pos = document.getElementById('lb-pos');
  var tot = document.getElementById('lb-total');
  if(pos) pos.textContent = (lbIndex + 1);
  if(tot) tot.textContent = lbGallery.length;
  var prev = document.querySelector('.lb-prev');
  var next = document.querySelector('.lb-next');
  if(prev) prev.disabled = (lbIndex === 0);
  if(next) next.disabled = (lbIndex >= lbGallery.length - 1);
  // Le bouton edit (crayon dans le header) n'apparaît que pour les Reels
  // (file_id contient |videos|). Pour Posts / Stories / Story CTA / PPs : caché.
  var editBtn = document.querySelector('.lb-edit-btn');
  var canEdit = (it.fileId || '').indexOf('|videos|') !== -1;
  if(editBtn){
    editBtn.style.display = canEdit ? '' : 'none';
  }
  // Si on est sur un media non-éditable et que le panel est ouvert -> fermer
  if(!canEdit && lbEditMode){
    lbToggleEdit();
  }
  // Si panneau ouvert et item editable, recharger les meta
  if(lbEditMode && canEdit) lbLoadMeta();
}
function lbPrev(){ if(lbIndex > 0){ lbIndex--; lbRender(); } }
function lbNext(){ if(lbIndex < lbGallery.length - 1){ lbIndex++; lbRender(); } }
function openLightbox(url, isVideo, filename, fileId, exampleUrl){
  lbCollectGallery();
  lbIndex = 0;
  for(var i = 0; i < lbGallery.length; i++){
    if(lbGallery[i].url === url){ lbIndex = i; break; }
  }
  if(lbGallery.length === 0){
    lbGallery = [{url:url, isVideo:isVideo, name:filename, fileId:fileId||'', exampleUrl:exampleUrl||''}];
    lbIndex = 0;
  }
  var modal = document.getElementById('lightbox');
  modal.classList.add('show');
  lbRender();
  document.addEventListener('keydown', lbKeyboard);
}
function lbToggleEdit(){
  var stage = document.querySelector('.lb-stage');
  var btn = document.querySelector('.lb-edit-btn');
  lbEditMode = !lbEditMode;
  if(lbEditMode){
    stage.classList.add('with-panel');
    if(btn) btn.classList.add('active');
    lbLoadMeta();
  } else {
    stage.classList.remove('with-panel');
    if(btn) btn.classList.remove('active');
  }
}
function lbLoadMeta(){
  var it = lbGallery[lbIndex];
  if(!it || !it.fileId) return;
  var capInput = document.getElementById('lb-caption');
  var descInput = document.getElementById('lb-description');
  capInput.value = ''; descInput.value = '';
  fetch('/cloud/meta/get?file_id=' + encodeURIComponent(it.fileId))
    .then(function(r){ return r.json(); })
    .then(function(data){
      capInput.value = data.caption || '';
      descInput.value = data.description || '';
      document.getElementById('lb-caption-count').textContent = capInput.value.length;
      document.getElementById('lb-desc-count').textContent = descInput.value.length;
    }).catch(function(){});
}
function lbSaveMeta(){
  var it = lbGallery[lbIndex];
  if(!it || !it.fileId) return;
  var btn = document.getElementById('lb-save-btn');
  btn.classList.add('loading');
  btn.disabled = true;
  var form = new FormData();
  form.append('file_id', it.fileId);
  form.append('caption', document.getElementById('lb-caption').value);
  form.append('description', document.getElementById('lb-description').value);
  fetch('/cloud/meta/save', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(data){
      btn.classList.remove('loading');
      btn.disabled = false;
      if(typeof showToast === 'function') showToast(data.ok ? 'Métadonnées sauvegardées' : ('Erreur : ' + (data.error || '?')), data.ok ? 'success' : 'error');
    }).catch(function(e){
      btn.classList.remove('loading');
      btn.disabled = false;
      if(typeof showToast === 'function') showToast('Erreur réseau', 'error');
    });
}
// Compteur live
document.addEventListener('input', function(e){
  if(e.target && e.target.id === 'lb-caption'){
    document.getElementById('lb-caption-count').textContent = e.target.value.length;
  }
  if(e.target && e.target.id === 'lb-description'){
    document.getElementById('lb-desc-count').textContent = e.target.value.length;
  }
});
function openCaptionEditor(fileId){
  // Trouver l'item dans la galerie courante par son fileId
  lbCollectGallery();
  lbIndex = 0;
  for(var i = 0; i < lbGallery.length; i++){
    if(lbGallery[i].fileId === fileId){ lbIndex = i; break; }
  }
  var it = lbGallery[lbIndex];
  if(!it) return;
  var modal = document.getElementById('lightbox');
  modal.classList.add('show');
  lbRender();
  // Ouvrir direct le panneau
  if(!lbEditMode) lbToggleEdit();
  document.addEventListener('keydown', lbKeyboard);
}
function closeLightbox(){
  var modal = document.getElementById('lightbox');
  var content = document.getElementById('lightbox-content');
  if(modal) modal.classList.remove('show');
  if(content) content.innerHTML = ''; // stoppe la vidéo et libère la mémoire
  document.removeEventListener('keydown', lbKeyboard);
}
function lbKeyboard(e){
  if(e.key === 'Escape'){ closeLightbox(); return; }
  if(e.key === 'ArrowLeft'){ lbPrev(); e.preventDefault(); return; }
  if(e.key === 'ArrowRight'){ lbNext(); e.preventDefault(); return; }
}
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
  // Retirer le style initial injecté en HEAD (pour le pre-paint)
  var initStyle = document.getElementById('__initial-tab-css');
  if(initStyle) initStyle.remove();
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

// === Add to Veille (bookmark) ===
window.addToVeille = async function(btn, payload){
  if(!payload || !payload.url) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '⏳';
  try {
    const r = await fetch('/veille/add', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
      credentials:'same-origin'
    });
    const j = await r.json();
    if(j.ok){
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="#22c55e" stroke="#22c55e" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
      btn.style.background = 'rgba(34,197,94,.3)';
      if(typeof showToast === 'function') showToast('🔖 Ajouté à la Veille', 'success');
      // Reste filled
      btn.disabled = false;
    } else if(j.error === 'already_exists'){
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="#3b82f6" stroke="#3b82f6" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
      btn.style.background = 'rgba(59,130,246,.3)';
      if(typeof showToast === 'function') showToast('🔖 Déjà dans la Veille', 'success');
      btn.disabled = false;
    } else {
      btn.innerHTML = orig;
      btn.disabled = false;
      if(typeof showToast === 'function') showToast('❌ ' + (j.error || 'Erreur'), 'error');
    }
  } catch(e){
    btn.innerHTML = orig;
    btn.disabled = false;
    if(typeof showToast === 'function') showToast('❌ Erreur réseau', 'error');
  }
};

// === GLOBAL : Pre-fill identite + cache la card + badge "Pour @xxx" ===
window.upPrefillIdentity = function(utab, ident){
  setTimeout(function(){
    var form = document.getElementById('form-' + utab);
    if(!form) return;
    var sel = form.querySelector('select[name=identity]');
    if(sel){ sel.value = ident; }
    // Cache la card identite (.up-card) OU le label/select classique
    var cards = form.querySelectorAll('.up-card');
    cards.forEach(function(c){
      if(c.querySelector('select[name=identity]')){ c.style.display = 'none'; }
    });
    if(cards.length === 0){
      form.querySelectorAll('label').forEach(function(l){
        if(l.textContent.trim() === 'Identité' && l.nextElementSibling){
          l.style.display = 'none';
          l.nextElementSibling.style.display = 'none';
        }
      });
    }
    // Badge "Pour @ident" - construit avec DOM API (pas d innerHTML pour eviter escape hell)
    var badge = form.querySelector('.up-identity-badge');
    if(!badge){
      badge = document.createElement('div');
      badge.className = 'up-identity-badge';
      badge.style.cssText = 'display:flex;align-items:center;gap:8px;padding:10px 16px;background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(168,85,247,.1));border:1px solid rgba(59,130,246,.35);border-radius:12px;color:#3b82f6;font-size:13px;font-weight:700;margin-bottom:14px;letter-spacing:-.01em;width:fit-content';
      // Icone user
      var icon = document.createElementNS('http://www.w3.org/2000/svg','svg');
      icon.setAttribute('viewBox','0 0 24 24');
      icon.setAttribute('width','14');
      icon.setAttribute('height','14');
      icon.setAttribute('fill','none');
      icon.setAttribute('stroke','currentColor');
      icon.setAttribute('stroke-width','2.5');
      var p1 = document.createElementNS('http://www.w3.org/2000/svg','circle');
      p1.setAttribute('cx','12'); p1.setAttribute('cy','7'); p1.setAttribute('r','4');
      var p2 = document.createElementNS('http://www.w3.org/2000/svg','path');
      p2.setAttribute('d','M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2');
      icon.appendChild(p1); icon.appendChild(p2);
      badge.appendChild(icon);
      // Texte
      var txt = document.createElement('span');
      var nameSpan = document.createElement('span');
      nameSpan.className = 'up-badge-name';
      nameSpan.textContent = ident;
      txt.append('Pour @', nameSpan);
      badge.appendChild(txt);
      // Bouton X
      var x = document.createElement('button');
      x.type = 'button';
      x.textContent = '×';
      x.title = 'Changer d identite';
      x.style.cssText = 'background:transparent;border:0;color:#888;font-size:14px;cursor:pointer;padding:2px 8px;margin-left:4px;border-radius:4px';
      x.onclick = function(){ window.upClearPrefill(utab); };
      badge.appendChild(x);
      form.insertBefore(badge, form.firstChild);
    } else {
      var nm = badge.querySelector('.up-badge-name');
      if(nm) nm.textContent = ident;
    }
  }, 50);
};
window.upClearPrefill = function(utab){
  var form = document.getElementById('form-' + utab);
  if(!form) return;
  form.querySelectorAll('.up-card').forEach(function(c){
    if(c.querySelector('select[name=identity]')) c.style.display = '';
  });
  form.querySelectorAll('label').forEach(function(l){
    if(l.textContent.trim() === 'Identité'){
      l.style.display = '';
      if(l.nextElementSibling) l.nextElementSibling.style.display = '';
    }
  });
  var badge = form.querySelector('.up-identity-badge');
  if(badge) badge.remove();
};
</script>
<script>
// === Theme sync (AVANT le premier paint pour éviter le flash sombre) ===
(function(){
  try{
    var theme = localStorage.getItem('vabot_theme') || 'light';
    if(theme === 'light'){
      // Ajouter la classe sur <html> tout de suite + CSS critique
      document.documentElement.classList.add('light-pre');
      var s = document.createElement('style');
      s.textContent = 'html.light-pre,html.light-pre body{background:#f9fafb !important;color:#111827 !important}';
      document.head.appendChild(s);
    }
    // SFW pre-apply : floute les images avant qu'elles s'affichent si actif
    // (exclus la lightbox, sera unblurred au clic)
    if(localStorage.getItem('vault_sfw') === '1'){
      var ss = document.createElement('style');
      ss.id = '__sfw-pre';
      ss.textContent = '.vault-gallery img,.vault-thumb img,.file-thumb img,.preview-card img{filter:blur(22px) saturate(.5)}#lightbox img,#lightbox video,.lightbox-content img,.lightbox-content video{filter:none!important}';
      document.head.appendChild(ss);
    }
  }catch(e){}
})();
// Run AVANT le premier rendu : cache form-home et affiche le bon form-<tab>
(function(){
  try{
    var params = new URLSearchParams(window.location.search);
    var t = params.get('tab');
    if(t && t !== 'home' && /^[a-zA-Z0-9_]{1,30}$/.test(t)){
      var s = document.createElement('style');
      s.id = '__initial-tab-css';
      s.textContent = '#form-home{display:none !important}#form-' + t + '{display:block !important}';
      document.head.appendChild(s);
    }
  }catch(e){}
})();
</script>
</head><body>
<!-- Page loader global (affiché pendant la navigation) -->
<div id="page-loader"><div class="pl-ring"></div></div>
<div class="layout">
<!-- SIDEBAR : groupes pliables avec flèches -->
<div class="sidebar">

<!-- DASHBOARD STANDALONE (top) -->
<div class="solo-group">
  <button class="item solo-item active" id="tab-home" onclick="showTab('solo','home','Dashboard','Tous tes revenus en un coup d oeil')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
    Dashboard
  </button>
</div>

<div class="section-label">Contenu</div>

<div class="group" id="grp-cloud">
  <button class="group-head" onclick="toggleGroup('cloud')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
    <span class="label">Bibliothèque</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" onclick="showTab('cloud','cloudoverview','Vue d ensemble','Tout ton stockage par type de contenu')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
      Vue d'ensemble
    </button>
    <button class="item" onclick="showTab('cloud','cloudreels','Reels','Tous les reels stockés par identité')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
      Reels
    </button>
    <button class="item" onclick="showTab('cloud','cloudposts','Posts','Tous les posts stockés')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
      Posts
    </button>
    <button class="item" onclick="showTab('cloud','cloudstories','Stories','Toutes les stories stockées')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
      Stories
    </button>
    <button class="item" onclick="showTab('cloud','cloudstoryctas','Story CTA','Toutes les stories CTA stockées')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
      Story CTA
    </button>
    <button class="item" onclick="showTab('cloud','cloudpps','Photos de profil','Pool partagé des PPs')">
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

<div class="group" id="grp-chatting">
  <button class="group-head" onclick="toggleGroup('chatting')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span class="label">Chatting</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" id="tab-chatplanning" onclick="showTab('chatting','chatplanning','Emploi du temps chatteurs','Planning hebdomadaire des shifts de chatting')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
      Emploi du temps
    </button>
  </div>
</div>

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
    <button class="item" id="tab-biolinks" onclick="showTab('business','biolinks','Bio Links','Pages publiques style Linktree par identite')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
      Bio Links
    </button>
    <button class="item" id="tab-gms" onclick="showTab('business','gms','GetMySocial','Gere tes liens GMS depuis le site')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      GetMySocial
    </button>
    <button class="item" id="tab-schedule" onclick="showTab('business','schedule','Schedule — Auto-post','Genere un fichier Excel template d import de posts planifies')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><path d="M8 14h.01"/><path d="M12 14h.01"/><path d="M16 14h.01"/><path d="M8 18h.01"/><path d="M12 18h.01"/><path d="M16 18h.01"/></svg>
      Schedule
    </button>
    <button class="item" id="tab-mypulslive" onclick="showTab('business','mypulslive','MyPuls Live — Push direct','Pousse stories/posts directement dans le scheduler MyPuls via cookies')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
      MyPuls Live
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
    <button class="item" id="tab-saccount" onclick="showTab('settings','saccount','Mon compte','Profil et identifiants')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
      Mon compte
    </button>
    <button class="item" id="tab-sprefs" onclick="showTab('settings','sprefs','Préférences','Thème, langue, affichage')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
      Préférences
    </button>
    <button class="item" id="tab-ssecurity" onclick="showTab('settings','ssecurity','Sécurité','Sessions actives et accès')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      Sécurité
    </button>
    <button class="item" id="tab-srole" onclick="showTab('settings','srole','Rôles & permissions','Gérer les utilisateurs et leurs accès')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      Rôles & permissions
    </button>
    <button class="item" id="tab-stoken" onclick="showTab('settings','stoken','Token bot admin','Token du 2e bot Discord')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg>
      Token bot admin
    </button>
    <button class="item" id="tab-sinsta" onclick="showTab('settings','sinsta','Cookies Instagram','Auth scraper Instagram')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="20" x="2" y="2" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor"/></svg>
      Cookies Instagram
    </button>
    <button class="item" id="tab-vtg" onclick="showTab('settings','vtg','Veille Telegram','Bot Telegram pour la veille reels')">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>
      Veille Telegram
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
<!-- SFW global toggle (style Inflow) -->
<div id="sfw-floating" style="position:fixed;top:18px;right:24px;z-index:90;display:flex;align-items:center;gap:6px;padding:6px 12px 6px 8px;background:#fff;border:1px solid #e5e7eb;border-radius:20px;box-shadow:0 4px 16px rgba(0,0,0,.08);cursor:pointer;user-select:none;transition:all .15s" onclick="toggleSFW()" title="Safe For Work — floute les images">
  <span class="sfw-switch" style="position:relative;width:36px;height:20px;background:#e5e7eb;border-radius:11px;transition:background .2s;flex-shrink:0">
    <span class="sfw-thumb" style="position:absolute;top:2px;left:2px;width:16px;height:16px;background:#fff;border-radius:50%;box-shadow:0 1px 3px rgba(0,0,0,.2);transition:transform .2s"></span>
  </span>
  <span style="font-size:11px;font-weight:800;color:#9ca3af;letter-spacing:.8px">SFW</span>
</div>
<h1 id="page-title">Dashboard</h1>
<div class="subtitle" id="page-subtitle">Tous tes revenus en un coup d'œil</div>
{msg_html}

<div class="form-section" id="form-reel" style="display:none">
<form method="POST" action="/upload/reel" enctype="multipart/form-data" class="up-form" data-utype="reel" data-accept="video/*">
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Identité</h3></div>
<select name="identity" required class="up-input">{ident_opts}</select>
</div>

<!-- Conteneur des slots de reel (1 slot = 1 reel complet) -->
<div id="reel-slots-container">
<!-- Le 1er slot est cree au load par initReelSlots() -->
</div>

<button type="button" id="add-reel-slot" class="up-add-slot">+ Ajouter un autre reel</button>

<button type="submit" class="up-submit">⬆ Uploader tous les reels</button>
</form>
</div>

<!-- Template HTML pour 1 reel slot (clone par initReelSlots) -->
<template id="reel-slot-template">
<div class="reel-slot" data-slot-idx="0">
<div class="reel-slot-header">
<div class="reel-slot-num">#1</div>
<button type="button" class="reel-slot-remove" onclick="removeReelSlot(this)" title="Retirer ce reel">×</button>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Vidéo CLEAN <span class="up-req">(obligatoire)</span></h3></div>
<label class="up-drop">
<input type="file" data-name="video" accept="video/*" required class="up-file-main">
<div class="up-drop-inner"><div class="up-plus">+</div><div class="up-plus-lbl">Add media</div></div>
<div class="up-drop-hint">Drag and drop the clean video here</div>
<div class="up-drop-limits"><span>Video size limit: 14GB</span></div>
</label>
<div class="up-edit-table" style="display:none">
<div class="up-edit-head"><div>Media</div><div>Action</div></div>
</div>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Vidéo EXEMPLE <span class="up-opt">(optionnel)</span></h3></div>
<label class="up-drop up-drop-small">
<input type="file" data-name="example" accept="video/*" class="up-file-example">
<div class="up-drop-inner-small"><div class="up-plus">+</div><div class="up-plus-lbl">Ajouter exemple</div></div>
</label>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Textes</h3></div>
<label class="up-mini-label">Caption (overlay sur la vidéo)</label>
<textarea data-name="caption" placeholder="Pov : j'ai fait la maline..." class="up-input"></textarea>
<label class="up-mini-label" style="margin-top:14px">Description (texte du post)</label>
<textarea data-name="description" placeholder="Ouais bon on va espérer hein 💀" class="up-input"></textarea>
</div>
<div class="reel-slot-status"></div>
</div>
</template>

<div class="form-section" id="form-post" style="display:none">
<form method="POST" action="/upload/post" enctype="multipart/form-data" class="up-form" data-utype="post" data-accept="image/*">
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Identité</h3></div>
<select name="identity" required class="up-input">{ident_opts}</select>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Select media</h3></div>
<label class="up-drop">
<input type="file" name="photo" accept="image/*" required class="up-file-main" multiple>
<div class="up-drop-inner"><div class="up-plus">+</div><div class="up-plus-lbl">Add media</div></div>
<div class="up-drop-hint">Drag and drop media file(s) — tu peux selectionner plusieurs photos d un coup</div>
<div class="up-drop-limits"><span>Image size limit: 100MB</span><span>·</span><span>Dimensions: 16px to 10000px</span></div>
</label>
<div class="up-edit-table" style="display:none">
<div class="up-edit-head"><div>Media</div><div>Action</div></div>
<div class="up-edit-row" data-file="main"><div class="up-edit-name">—</div><div><button type="button" class="up-rm" onclick="upClearMain(this)">🗑</button></div></div>
</div>
</div>
<button type="submit" class="up-submit">⬆ Uploader le post</button>
</form>
</div>

<div class="form-section" id="form-story" style="display:none">
<form method="POST" action="/upload/story" enctype="multipart/form-data" class="up-form" data-utype="story" data-accept="image/*">
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Identité</h3></div>
<select name="identity" required class="up-input">{ident_opts}</select>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Select media</h3></div>
<label class="up-drop">
<input type="file" name="photo" accept="image/*" required class="up-file-main" multiple>
<div class="up-drop-inner"><div class="up-plus">+</div><div class="up-plus-lbl">Add media</div></div>
<div class="up-drop-hint">Drag and drop media file(s) — tu peux selectionner plusieurs photos d un coup</div>
<div class="up-drop-limits"><span>Image size limit: 100MB</span><span>·</span><span>Dimensions: 16px to 10000px</span></div>
</label>
<div class="up-edit-table" style="display:none">
<div class="up-edit-head"><div>Media</div><div>Action</div></div>
<div class="up-edit-row" data-file="main"><div class="up-edit-name">—</div><div><button type="button" class="up-rm" onclick="upClearMain(this)">🗑</button></div></div>
</div>
</div>
<button type="submit" class="up-submit">⬆ Uploader la story</button>
</form>
</div>

<div class="form-section" id="form-storycta" style="display:none">
<form method="POST" action="/upload/storycta" enctype="multipart/form-data" class="up-form" data-utype="storycta" data-accept="image/*">
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Identité</h3></div>
<select name="identity" required class="up-input">{ident_opts}</select>
</div>
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Select media</h3></div>
<label class="up-drop">
<input type="file" name="photo" accept="image/*" required class="up-file-main" multiple>
<div class="up-drop-inner"><div class="up-plus">+</div><div class="up-plus-lbl">Add media</div></div>
<div class="up-drop-hint">Drag and drop 1080x1920 image(s) — multi OK</div>
<div class="up-drop-limits"><span>Story CTA · captions partagées via /addstoryctacaptions</span></div>
</label>
<div class="up-edit-table" style="display:none">
<div class="up-edit-head"><div>Media</div><div>Action</div></div>
<div class="up-edit-row" data-file="main"><div class="up-edit-name">—</div><div><button type="button" class="up-rm" onclick="upClearMain(this)">🗑</button></div></div>
</div>
</div>
<button type="submit" class="up-submit">⬆ Uploader story CTA</button>
</form>
</div>

<div class="form-section" id="form-pp" style="display:none">
<form method="POST" action="/upload/pp" enctype="multipart/form-data" class="up-form" data-utype="pp" data-accept="image/*">
<div class="up-card">
<div class="up-step"><span class="up-dot"></span><h3>Photo de profil</h3></div>
<small style="color:#888;margin-bottom:10px;display:block">Pool partagé entre toutes les identités</small>
<label class="up-drop">
<input type="file" name="photo" accept="image/*" required class="up-file-main" multiple>
<div class="up-drop-inner"><div class="up-plus">+</div><div class="up-plus-lbl">Add media</div></div>
<div class="up-drop-hint">Drag and drop your profile picture(s) — multi OK</div>
</label>
<div class="up-edit-table" style="display:none">
<div class="up-edit-head"><div>Media</div><div>Action</div></div>
<div class="up-edit-row" data-file="main"><div class="up-edit-name">—</div><div><button type="button" class="up-rm" onclick="upClearMain(this)">🗑</button></div></div>
</div>
</div>
<button type="submit" class="up-submit">⬆ Uploader la PP</button>
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
{cloud_reels_html}
</div>

<!-- CLOUD : posts -->
<div class="form-section" id="form-cloudposts" style="display:none">
{cloud_posts_html}
</div>

<!-- CLOUD : stories -->
<div class="form-section" id="form-cloudstories" style="display:none">
{cloud_stories_html}
</div>

<!-- CLOUD : Story CTAs -->
<div class="form-section" id="form-cloudstoryctas" style="display:none">
{cloud_storyctas_html}
</div>

<!-- CLOUD : PPs -->
<div class="form-section" id="form-cloudpps" style="display:none">
<div class="box">{cloud_pps_html}</div>
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
    <div style="width:40px;height:40px;border:2px solid #06b6d4;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#06b6d4;cursor:pointer">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/></svg>
    </div>
  </div>
</div>

<h2 style="margin:0 0 18px;font-size:26px">Trends</h2>

<!-- Sub-tabs style Insta : Mes suivies / Explorer / Veille -->
<div style="display:flex;gap:4px;border-bottom:1px solid #2a2a2a;margin-bottom:20px">
  <button class="ig-feed-tab active" onclick="showFeed(this,'suivies')" style="padding:12px 24px;background:none;border:0;color:#fff;cursor:pointer;font-size:14px;font-weight:600;border-bottom:2px solid #3b82f6;margin:0">👥 Mes suivies</button>
  <button class="ig-feed-tab" onclick="showFeed(this,'explore')" style="padding:12px 24px;background:none;border:0;color:#888;cursor:pointer;font-size:14px;font-weight:600;border-bottom:2px solid transparent;margin:0">🔍 Explorer</button>
  <button class="ig-feed-tab" onclick="showFeed(this,'veille')" style="padding:12px 24px;background:none;border:0;color:#888;cursor:pointer;font-size:14px;font-weight:600;border-bottom:2px solid transparent;margin:0">🔖 Veille <span id="veille-count-badge" style="background:#3b82f6;color:#fff;font-size:10px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:4px;display:none"></span></button>
</div>
<script>
function showFeed(btn,name){
  document.querySelectorAll('.ig-feed-tab').forEach(function(b){
    b.style.color='#888';
    b.style.borderBottomColor='transparent';
  });
  btn.style.color='#fff';
  btn.style.borderBottomColor='#3b82f6';
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
      <button onclick="igSelectSort(this,'Trending')" class="ig-sort-opt selected" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#fff;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Trending<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Newest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Newest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Oldest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Oldest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
    </div>
  </div>

  <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:4px;display:flex;gap:2px">
    <button onclick="igPeriod(this,'day')" class="ig-period" style="padding:8px 18px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0" title="Reels des dernieres 24h">24h</button>
    <button onclick="igPeriod(this,'week')" class="ig-period active" style="padding:8px 18px;background:#2a2a2a;border:0;color:#fff;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0" title="Reels des 7 derniers jours">7j</button>
    <button onclick="igPeriod(this,'month')" class="ig-period" style="padding:8px 18px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0" title="Reels des 30 derniers jours">30j</button>
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

<div id="feed-veille" class="ig-feed-content" style="display:none">
{veille_feed_html}
</div>

<!-- Modal details reel (sound, caption, duration) -->
<div id="reel-details-modal" onclick="if(event.target===this)closeReelDetails()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);backdrop-filter:blur(8px);z-index:9999;align-items:center;justify-content:center;padding:20px">
  <div style="background:#161616;border:1px solid #2a2a2a;border-radius:16px;max-width:520px;width:100%;max-height:90vh;overflow-y:auto;color:#fff">
    <div style="position:relative">
      <video id="reel-details-video" controls muted loop style="width:100%;max-height:60vh;background:#000;display:block;border-radius:16px 16px 0 0"></video>
      <button onclick="closeReelDetails()" style="position:absolute;top:12px;right:12px;width:32px;height:32px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border:0;color:#fff;border-radius:50%;cursor:pointer;font-size:18px;line-height:1">×</button>
    </div>
    <div style="padding:18px 20px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <img id="reel-details-pp" style="width:36px;height:36px;border-radius:50%;object-fit:cover">
        <div style="flex:1">
          <div id="reel-details-owner" style="font-weight:700;font-size:15px">@?</div>
          <div id="reel-details-time" style="color:#888;font-size:11px"></div>
        </div>
        <a id="reel-details-igbtn" href="#" target="_blank" style="background:#3b82f6;color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-size:12px;font-weight:700">Voir sur Instagram</a>
      </div>
      <div style="display:flex;gap:14px;color:#aaa;font-size:13px;margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid #232323">
        <span id="reel-details-views" style="display:flex;align-items:center;gap:5px"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><polygon points="5 3 19 12 5 21"/></svg> <span></span></span>
        <span id="reel-details-likes" style="display:flex;align-items:center;gap:5px"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg> <span></span></span>
        <span id="reel-details-comments" style="display:flex;align-items:center;gap:5px"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg> <span></span></span>
        <span id="reel-details-duration" style="margin-left:auto;display:flex;align-items:center;gap:5px;color:#3b82f6;font-weight:700"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> <span>...</span></span>
      </div>
      <div style="font-size:11px;color:#666;letter-spacing:1px;text-transform:uppercase;font-weight:700;margin-bottom:6px">Caption</div>
      <div id="reel-details-caption" style="color:#ddd;font-size:13.5px;line-height:1.55;white-space:pre-wrap;word-wrap:break-word;max-height:160px;overflow-y:auto;margin-bottom:14px"></div>
      <div style="font-size:11px;color:#666;letter-spacing:1px;text-transform:uppercase;font-weight:700;margin-bottom:6px">🎵 Sound</div>
      <div id="reel-details-sound" style="color:#aaa;font-size:13px;font-style:italic">Info son pas disponible via le scraper</div>
    </div>
  </div>
</div>

<script>
function openReelDetails(card){
  if(!card) return;
  const modal = document.getElementById('reel-details-modal');
  if(!modal) return;
  // Charge la video
  const videoEl = document.getElementById('reel-details-video');
  const videoUrl = card.dataset.videoUrl;
  const thumb = card.dataset.thumb;
  if(videoUrl){
    videoEl.src = videoUrl;
    videoEl.poster = thumb || '';
    videoEl.play().catch(()=>{});
    // Recupere la duree quand la video est chargee
    videoEl.onloadedmetadata = function(){
      const d = Math.round(videoEl.duration || 0);
      const min = Math.floor(d/60), sec = (d%60).toString().padStart(2,'0');
      const durEl = document.querySelector('#reel-details-duration span');
      if(durEl) durEl.textContent = min + ':' + sec;
    };
  }
  document.getElementById('reel-details-owner').textContent = '@' + (card.dataset.owner||'?');
  document.getElementById('reel-details-time').textContent = card.dataset.timeAgo || '';
  const pp = document.getElementById('reel-details-pp');
  if(card.dataset.ownerPp){ pp.src = card.dataset.ownerPp; pp.style.display=''; } else { pp.style.display = 'none'; }
  document.getElementById('reel-details-caption').textContent = card.dataset.caption || '(aucune caption)';
  document.querySelector('#reel-details-views span').textContent = card.dataset.views || '0';
  document.querySelector('#reel-details-likes span').textContent = card.dataset.likes || '0';
  document.querySelector('#reel-details-comments span').textContent = card.dataset.comments || '0';
  const igBtn = document.getElementById('reel-details-igbtn');
  if(igBtn && card.dataset.url) igBtn.href = card.dataset.url;
  modal.style.display = 'flex';
}
function closeReelDetails(){
  const modal = document.getElementById('reel-details-modal');
  const videoEl = document.getElementById('reel-details-video');
  if(videoEl){ videoEl.pause(); videoEl.src = ''; }
  if(modal) modal.style.display = 'none';
}
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape') closeReelDetails();
});
</script>

</div><!-- /form-igtrends -->

<!-- HOME (clic sur "VA Bot") -->
<div class="form-section" id="form-home">
{home_dashboard_html}
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
<button type="submit" style="background:#d9534f">Sauver et redémarrer</button>
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

<!-- BUSINESS - BIO LINKS -->
<div class="form-section" id="form-biolinks" style="display:none">
{biolinks_html}
</div>

<!-- BUSINESS - GETMYSOCIAL -->
<div class="form-section" id="form-gms" style="display:none">
{gms_html}
</div>

<!-- BUSINESS - SCHEDULE (AUTO-POST XLSX) -->
<div class="form-section" id="form-schedule" style="display:none">
{schedule_html}
</div>

<!-- BUSINESS - MYPULS LIVE PUSH -->
<div class="form-section" id="form-mypulslive" style="display:none">
{mypulslive_html}
</div>

<!-- CHATTING - EMPLOI DU TEMPS -->
<div class="form-section" id="form-chatplanning" style="display:none">
{chatplanning_html}
</div>

<!-- SETTINGS - INSTAGRAM COOKIES -->
<div class="form-section" id="form-vtg" style="display:none">
{vtg_html}
</div>

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
<button type="submit">Sauver la clé RapidAPI</button>
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
<form method="POST" action="/settings/insta_auth_file" enctype="multipart/form-data" class="box" style="border:2px dashed #3b82f6">
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
<button type="submit">Sauver les cookies</button>
</form>
</div>

<!-- SETTINGS - MON COMPTE -->
<div class="form-section" id="form-saccount" style="display:none">
<form method="POST" action="/settings/account" enctype="multipart/form-data" class="box">
<h3 style="margin-top:0">👤 Informations personnelles</h3>
<small>Profil et identifiants de connexion</small>
<label style="margin-top:16px">Photo de profil</label>
<div style="display:flex;align-items:center;gap:14px;margin-bottom:14px">
  {profile_pic_html}
  <input type="file" name="profile_pic" accept="image/*" style="flex:1">
</div>
<label>Nom affiché</label>
<input type="text" name="display_name" value="{account_display_name}" placeholder="Ton nom">
<label>Email</label>
<input type="email" name="email" value="{account_email}" placeholder="email@exemple.com">
<button type="submit">Sauvegarder le profil</button>
</form>

<form method="POST" action="/settings/account_password" class="box">
<h3 style="margin-top:0">🔐 Changer le mot de passe</h3>
<small>Mot de passe d'accès au site</small>
<label style="margin-top:14px">Nouveau mot de passe</label>
<input type="password" name="new_password" placeholder="Min 6 caractères" required minlength="6">
<label>Confirmer le mot de passe</label>
<input type="password" name="confirm_password" placeholder="Re-tape pour confirmer" required minlength="6">
<button type="submit">Changer le mot de passe</button>
</form>
</div>

<!-- SETTINGS - PRÉFÉRENCES -->
<div class="form-section" id="form-sprefs" style="display:none">
<div class="box">
<h3 style="margin-top:0">🎨 Affichage</h3>
<small>Choisis entre le mode clair et sombre</small>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px">
  <div onclick="setTheme('light')" class="theme-card" data-theme="light" style="background:#fff;border:2px solid #e5e7eb;border-radius:12px;padding:20px;cursor:pointer;text-align:center;color:#111827">
    <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-start;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:8px;width:100%"><div style="width:14px;height:14px;border-radius:50%;background:#e5e7eb"></div><div style="flex:1;height:8px;background:#e5e7eb;border-radius:4px"></div></div>
      <div style="display:flex;align-items:center;gap:8px;width:60%"><div style="width:14px;height:14px;border-radius:50%;background:#e5e7eb"></div><div style="flex:1;height:8px;background:#3b82f6;border-radius:4px"></div></div>
    </div>
    <div style="display:flex;align-items:center;gap:8px"><input type="radio" name="theme-radio" style="margin:0" id="theme-radio-light"><label for="theme-radio-light" style="font-size:14px;font-weight:600;cursor:pointer;color:#111827;margin:0">Light mode</label></div>
  </div>
  <div onclick="setTheme('dark')" class="theme-card" data-theme="dark" style="background:#0a0a0a;border:2px solid #2a2a2a;border-radius:12px;padding:20px;cursor:pointer;text-align:center;color:#fff">
    <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-start;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:8px;width:100%"><div style="width:14px;height:14px;border-radius:50%;background:#2a2a2a"></div><div style="flex:1;height:8px;background:#2a2a2a;border-radius:4px"></div></div>
      <div style="display:flex;align-items:center;gap:8px;width:60%"><div style="width:14px;height:14px;border-radius:50%;background:#2a2a2a"></div><div style="flex:1;height:8px;background:#3b82f6;border-radius:4px"></div></div>
    </div>
    <div style="display:flex;align-items:center;gap:8px"><input type="radio" name="theme-radio" style="margin:0" id="theme-radio-dark" checked><label for="theme-radio-dark" style="font-size:14px;font-weight:600;cursor:pointer;color:#fff;margin:0">Dark mode</label></div>
  </div>
</div>
</div>
<div class="box">
<h3 style="margin-top:0">🌐 Langue</h3>
<small>Langue de l'interface</small>
<label style="margin-top:14px">Langue</label>
<select disabled>
  <option>Français (par défaut)</option>
  <option>English (coming soon)</option>
</select>
<small style="margin-top:8px">L'anglais sera disponible bientôt.</small>
</div>
</div>

<!-- SETTINGS - SÉCURITÉ -->
<div class="form-section" id="form-ssecurity" style="display:none">
<div class="box">
<h3 style="margin-top:0">🛡️ Sessions actives</h3>
<small>Personnes actuellement connectées à ton site</small>
{security_sessions_html}
</div>
</div>

<!-- SETTINGS - RÔLES -->
<div class="form-section" id="form-srole" style="display:none">
<div class="box">
<h3 style="margin-top:0">👥 Rôles & permissions</h3>
<small>Gère qui peut accéder à quelles fonctions du site</small>
{role_settings_html}
</div>
<form method="POST" action="/settings/role/add" class="box">
<h3 style="margin-top:0">➕ Ajouter un utilisateur</h3>
<small>Crée un compte d'accès avec un rôle spécifique</small>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px">
<div><label>Nom</label><input type="text" name="username" placeholder="Nom de l'utilisateur" required></div>
<div><label>Rôle</label><select name="role" required>
<option value="admin">Admin (tout)</option>
<option value="creator">Creator (upload + cloud)</option>
<option value="chatter">Chatter (revenus + sfs)</option>
<option value="va">VA (lecture seule)</option>
<option value="custom">Custom (à définir)</option>
</select></div>
</div>
<label>Mot de passe initial</label>
<input type="password" name="password" placeholder="Min 6 caractères" required minlength="6">
<button type="submit">Ajouter l'utilisateur</button>
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
<button type="submit" style="background:#d9534f">Sauver et redémarrer</button>
</form>
</div>

</div>

<!-- Barre flottante d'actions style Infloww (apparaît quand items sélectionnés) -->
<div id="action-bar" style="display:none">
  <div class="action-bar-inner">
    <button class="action-close" onclick="clearSelection()" title="Annuler la sélection">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
    <div class="action-count"><span id="sel-count">0</span> Sélectionné</div>
    <div style="flex:1"></div>
    <button class="action-icon" onclick="deleteSelected()" title="Supprimer">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>
    </button>
  </div>
</div>
<style>
#action-bar{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:200;animation:slideUp .3s ease}
@keyframes slideUp{from{transform:translate(-50%,40px);opacity:0}to{transform:translateX(-50%);opacity:1}}
.action-bar-inner{display:flex;align-items:center;gap:14px;background:#0a0a0a;border:1px solid #222;border-radius:14px;padding:10px 16px 10px 12px;box-shadow:0 12px 36px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.04) inset;min-width:300px}
.action-close{background:transparent;border:0;color:#888;width:32px;height:32px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0;transition:all .15s}
.action-close:hover{background:rgba(255,255,255,.06);color:#fff}
.action-count{color:#fff;font-weight:600;font-size:14px;letter-spacing:-.01em}
.action-icon{background:transparent;border:0;color:#aaa;width:36px;height:36px;border-radius:9px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0;transition:all .15s}
.action-icon:hover{background:rgba(239,68,68,.12);color:#ef4444}
body.light .action-bar-inner{background:#fff;border-color:#e5e7eb;box-shadow:0 12px 36px rgba(0,0,0,.15)}
body.light .action-close{color:#666}
body.light .action-close:hover{background:#f3f4f6;color:#111}
body.light .action-count{color:#111}
body.light .action-icon{color:#666}
</style>

<!-- Lightbox plein écran -->
<!-- Lightbox style Infloww : backdrop semi-transparent + nav + panneau caption -->
<div id="lightbox" onclick="closeLightbox()">
  <div class="lb-header" onclick="event.stopPropagation()">
    <div class="lb-counter"><span id="lb-pos">1</span> / <span id="lb-total">1</span></div>
    <button class="lb-edit-btn" onclick="lbToggleEdit()" title="Modifier caption / description">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
    </button>
    <button class="lb-close-btn" onclick="closeLightbox()" title="Fermer (Esc)">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  </div>
  <button class="lb-nav lb-prev" onclick="event.stopPropagation();lbPrev()" title="Précédent (←)">
    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
  </button>
  <div class="lb-stage" onclick="event.stopPropagation()">
    <div class="lb-content-wrap">
      <div id="lightbox-content"></div>
    </div>
    <!-- Panneau caption/description à droite, caché par défaut -->
    <div class="lb-side-panel" id="lb-side-panel">
      <div class="lb-side-header">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#3b82f6" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        Métadonnées média
      </div>
      <div class="lb-side-body">
        <label class="lb-side-label">Caption</label>
        <textarea id="lb-caption" maxlength="2200" placeholder="Pov : ..."></textarea>
        <div class="lb-side-count"><span id="lb-caption-count">0</span> / 2200</div>

        <label class="lb-side-label" style="margin-top:14px">Description</label>
        <textarea id="lb-description" maxlength="500" placeholder="Decris le contexte du media..."></textarea>
        <div class="lb-side-count"><span id="lb-desc-count">0</span> / 500</div>

        <div style="display:flex;gap:8px;margin-top:16px">
          <button class="lb-btn-secondary" onclick="lbToggleEdit()">Annuler</button>
          <button class="lb-btn-primary" id="lb-save-btn" onclick="lbSaveMeta()">
            <span class="lb-save-label">Enregistrer</span>
            <span class="lb-save-spinner"></span>
          </button>
        </div>
      </div>
    </div>
  </div>
  <button class="lb-nav lb-next" onclick="event.stopPropagation();lbNext()" title="Suivant (→)">
    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
  </button>
</div>
<style>
#lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);backdrop-filter:blur(8px);z-index:300;align-items:center;justify-content:center;padding:60px 80px;animation:lbFade .2s}
#lightbox.show{display:flex}
@keyframes lbFade{from{opacity:0}to{opacity:1}}
.lb-header{position:absolute;top:18px;right:20px;display:flex;align-items:center;gap:14px;z-index:5}
.lb-counter{background:rgba(0,0,0,.5);color:#fff;font-size:14px;font-weight:600;padding:7px 14px;border-radius:8px;letter-spacing:.01em;backdrop-filter:blur(6px)}
.lb-close-btn{background:rgba(0,0,0,.5);border:0;color:#fff;width:40px;height:40px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;backdrop-filter:blur(6px);transition:all .15s}
.lb-close-btn:hover{background:rgba(255,255,255,.15);transform:scale(1.08)}
.lb-nav{position:absolute;top:50%;transform:translateY(-50%);background:rgba(0,0,0,.5);border:0;color:#fff;width:48px;height:48px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;backdrop-filter:blur(6px);transition:all .15s;z-index:5}
.lb-prev{left:18px}
.lb-next{right:18px}
.lb-nav:hover{background:rgba(255,255,255,.15);transform:translateY(-50%) scale(1.08)}
.lb-nav:disabled{opacity:.25;cursor:not-allowed;pointer-events:none}
.lb-stage{display:flex;align-items:center;justify-content:center;gap:18px;max-width:calc(100vw - 220px);width:100%;height:100%}
.lb-stage.with-panel .lb-content-wrap{max-width:calc(100% - 380px)}
.lb-content-wrap{display:flex;align-items:center;justify-content:center;flex:1;max-height:calc(100vh - 120px);height:100%;transition:max-width .25s;min-width:0}
#lightbox-content{max-width:100%;max-height:100%;display:flex;align-items:center;justify-content:center;width:100%;height:100%}
#lightbox-content img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;display:block;border-radius:12px;background:#000;box-shadow:0 24px 60px rgba(0,0,0,.5)}
/* Lecteur vidéo plus élégant : ratio 9:16 (vertical) par défaut, controls plus solides */
#lightbox-content video{outline:none;display:block;background:#000;border-radius:14px;
  box-shadow:0 24px 60px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.04);
  max-width:100%;max-height:calc(100vh - 120px);width:auto;height:auto}
#lightbox-content video::-webkit-media-controls-panel{background:linear-gradient(to top,rgba(0,0,0,.85),transparent);border-radius:0 0 14px 14px}
/* Dual video : Original + Exemple côte à côte */
.lb-dual-video{display:flex;gap:16px;align-items:center;justify-content:center;flex-wrap:wrap;max-width:100%;max-height:100%}
.lb-dual-item{display:flex;flex-direction:column;align-items:center;gap:8px;max-width:48%;flex:1;min-width:0}
.lb-dual-label{font-size:11px;font-weight:700;color:#aaa;text-transform:uppercase;letter-spacing:.08em;background:rgba(0,0,0,.5);padding:5px 12px;border-radius:6px;backdrop-filter:blur(4px)}
.lb-dual-item video{max-width:100% !important;max-height:calc(100vh - 160px) !important}
@media(max-width:900px){.lb-dual-video{flex-direction:column}.lb-dual-item{max-width:100%}}
/* Bouton edit crayon dans header */
.lb-edit-btn{background:rgba(0,0,0,.5);border:0;color:#fff;width:40px;height:40px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;backdrop-filter:blur(6px);transition:all .15s}
.lb-edit-btn:hover,.lb-edit-btn.active{background:#3b82f6;transform:scale(1.08)}
/* Panneau latéral droite (Caption / Description) */
.lb-side-panel{width:0;background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;overflow:hidden;opacity:0;transition:all .25s;display:flex;flex-direction:column;max-height:calc(100vh - 120px)}
.lb-stage.with-panel .lb-side-panel{width:360px;opacity:1}
.lb-side-header{padding:16px 20px;border-bottom:1px solid #2a2a2a;font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px;color:#fff;flex-shrink:0}
.lb-side-body{padding:18px 20px;overflow-y:auto;flex:1}
.lb-side-label{display:block;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.lb-side-body textarea{width:100%;min-height:90px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:8px;padding:10px 12px;font-size:13px;font-family:inherit;resize:vertical;line-height:1.4}
.lb-side-body textarea:focus{border-color:#3b82f6;outline:none;box-shadow:0 0 0 3px rgba(59,130,246,.15)}
.lb-side-count{text-align:right;font-size:11px;color:#666;margin-top:4px;font-weight:500}
.lb-btn-primary{flex:1;background:#3b82f6;color:#fff;border:0;padding:11px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;gap:8px;min-height:42px;font-family:inherit}
.lb-btn-primary:hover{background:#2563eb}
.lb-btn-primary:disabled{cursor:wait;opacity:.85}
.lb-save-spinner{display:none;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}
.lb-btn-primary.loading .lb-save-label{display:none}
.lb-btn-primary.loading .lb-save-spinner{display:inline-block}
.lb-btn-secondary{background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:11px 16px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;font-family:inherit}
.lb-btn-secondary:hover{background:rgba(255,255,255,.05);color:#fff}
body.light .lb-side-panel{background:#fff;border-color:#e5e7eb}
body.light .lb-side-header{border-color:#e5e7eb;color:#111}
body.light .lb-side-body textarea{background:#fff;border-color:#e5e7eb;color:#111}
body.light .lb-side-label{color:#6b7280}
body.light .lb-btn-secondary{color:#6b7280;border-color:#e5e7eb}
body.light .lb-btn-secondary:hover{background:#f3f4f6;color:#111}
@media(max-width:768px){
  #lightbox{padding:50px 60px}
  .lb-stage{max-width:calc(100vw - 130px)}
  .lb-stage.with-panel .lb-side-panel{width:280px}
  .lb-stage.with-panel .lb-content-wrap{max-width:calc(100% - 300px)}
  .lb-nav{width:38px;height:38px}
  #lightbox-content video{min-width:auto}
}
</style>

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


# ============ Utilisateurs web (login user/password) ============

WEB_USERS_FILE = DATA_DIR / "web_admin_users.json"


def _hash_password(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _load_web_users() -> dict:
    if not WEB_USERS_FILE.exists():
        return {}
    try:
        return json.loads(WEB_USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_web_users(users: dict):
    WEB_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEB_USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _bootstrap_web_users():
    """Crée le user 'samaali' avec le WEB_PASSWORD courant si pas déjà présent."""
    users = _load_web_users()
    if "samaali" not in users:
        users["samaali"] = {
            "password_hash": _hash_password(WEB_PASSWORD),
            "created_at": int(time.time()),
            "role": "admin",
        }
        _save_web_users(users)


def _check_web_login(username: str, password: str) -> bool:
    """Accepte 2 façons :
    1. username + password matchant un user enregistré dans web_admin_users.json
    2. password seul matchant WEB_PASSWORD (legacy, pour compat)
    """
    if not password:
        return False
    # Bootstrap au premier login
    _bootstrap_web_users()
    if username:
        users = _load_web_users()
        u = users.get(username.lower().strip())
        if u and u.get("password_hash") == _hash_password(password):
            return True
    # Fallback : password seul matchant WEB_PASSWORD
    if password == WEB_PASSWORD:
        return True
    return False


def _render_login(err=""):
    err_html = (
        f'<div class="err"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>{err}</div>'
        if err else ""
    )
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


# ============ VA -> Paiement (crypto ou taptap) ============
VA_PAYMENTS_FILE = DATA_DIR / "va_payments.json"

# Réseaux crypto par type (réutilise la convention MyPuls)
VA_CRYPTO_NETWORKS = {
    "USDC": ["Ethereum", "Tron", "Solana", "BSC", "Polygon", "Arbitrum", "Optimism", "Base"],
    "ETH": ["Ethereum", "Arbitrum", "Optimism", "Base", "BSC", "Polygon", "Solana"],
    "SOL": ["Solana", "Ethereum", "BSC"],
    "TRX": ["Tron"],
}
VA_CRYPTO_TYPES = list(VA_CRYPTO_NETWORKS.keys())

# Opérateurs TapTap (mobile money)
TAPTAP_NETWORKS = ["Orange Money", "MTN Mobile Money", "Moov Money",
                   "Wave", "Free Money", "Airtel Money", "Autre"]


def _load_va_payments() -> dict:
    if not VA_PAYMENTS_FILE.exists():
        return {}
    try:
        return json.loads(VA_PAYMENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_va_payments(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VA_PAYMENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_va_payment(user_id) -> dict:
    """Retourne {kind, crypto_type, crypto_network, crypto_address,
    taptap_number, taptap_network} ou dict vide."""
    return _load_va_payments().get(str(user_id), {})


def _set_va_payment(user_id, payload: dict):
    data = _load_va_payments()
    key = str(user_id)
    # Nettoyer : ne garder que les champs reconnus
    clean = {}
    kind = (payload.get("kind") or "").strip().lower()
    if kind not in ("crypto", "taptap"):
        # Vide = effacer
        if key in data:
            data.pop(key)
            _save_va_payments(data)
        return
    clean["kind"] = kind
    if kind == "crypto":
        ct = (payload.get("crypto_type") or "").strip().upper()
        if ct in VA_CRYPTO_TYPES:
            clean["crypto_type"] = ct
        clean["crypto_network"] = (payload.get("crypto_network") or "").strip()
        clean["crypto_address"] = (payload.get("crypto_address") or "").strip()[:200]
    else:  # taptap
        clean["taptap_number"] = (payload.get("taptap_number") or "").strip()[:30]
        clean["taptap_network"] = (payload.get("taptap_network") or "").strip()
    data[key] = clean
    _save_va_payments(data)


# ============ VA -> Instagram (handle + last stats) ============
VA_INSTA_FILE = DATA_DIR / "va_instagram.json"


def _load_va_insta() -> dict:
    if not VA_INSTA_FILE.exists():
        return {}
    try:
        return json.loads(VA_INSTA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_va_insta(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VA_INSTA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_va_insta(user_id) -> dict:
    """Retourne {handle, followers, posts, last_post_at, last_scraped_at} ou {}."""
    return _load_va_insta().get(str(user_id), {})


def _set_va_insta(user_id, handle: str):
    data = _load_va_insta()
    key = str(user_id)
    h = (handle or "").strip().lstrip("@")[:50]
    if not h:
        data.pop(key, None)
    else:
        existing = data.get(key, {})
        existing["handle"] = h
        data[key] = existing
    _save_va_insta(data)


def _update_va_insta_stats(user_id, handle: str, followers: int = 0,
                            posts: int = 0, last_post_at: str = ""):
    """Mise à jour des stats après scrape."""
    data = _load_va_insta()
    key = str(user_id)
    import time as _t
    data[key] = {
        "handle": handle,
        "followers": followers,
        "posts": posts,
        "last_post_at": last_post_at,
        "last_scraped_at": int(_t.time()),
    }
    _save_va_insta(data)


# ============ VA -> GMS links mapping ============
VA_LINKS_FILE = DATA_DIR / "va_links.json"


def _load_va_links() -> dict:
    """Retourne {user_id_str: [link_id_1, link_id_2, ...]}."""
    if not VA_LINKS_FILE.exists():
        return {}
    try:
        return json.loads(VA_LINKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_va_links(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VA_LINKS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_links_for_va(user_id) -> list:
    return _load_va_links().get(str(user_id), [])


def _set_links_for_va(user_id, link_ids: list):
    data = _load_va_links()
    key = str(user_id)
    if link_ids:
        data[key] = link_ids
    else:
        data.pop(key, None)
    _save_va_links(data)


# Cache simple pour les données quotidiennes GMS (TTL 5 min, module-level)
_VA_DAILY_CACHE: dict = {}
_VA_DAILY_TTL = 300  # 5 minutes


def _get_links_clicks_period(link_ids: list, days: int = 7) -> dict:
    """Retourne {total, daily: [...]} pour des liens GMS sur N jours.

    Daily est calculé à partir de list_recent_visitors (timestamps par visite).
    Cache 5 min.
    """
    import time as _t
    now = _t.time()
    key = "|".join(sorted(link_ids)) + f"|days={days}"
    cached = _VA_DAILY_CACHE.get(key)
    if cached and (now - cached[0]) < _VA_DAILY_TTL:
        return cached[1]
    result = {"total": 0, "daily": [0] * days}
    try:
        import gms
        import datetime as _dt3
        if not gms.is_configured() or not link_ids:
            _VA_DAILY_CACHE[key] = (now, result)
            return result
        # list_recent_visitors avec limit 100 (les param dates ne marchent pas
        # fiablement sur cette API, on filtre côté client).
        today = _dt3.date.today()
        start_date = today - _dt3.timedelta(days=days - 1)
        res = gms._call_tool("list_recent_visitors", {
            "link_ids": link_ids,
            "limit": 100,
        })
        if res.get("ok"):
            data = res.get("data") or {}
            visitors = data.get("data", []) if isinstance(data, dict) else []
            # Bucketer par jour
            buckets = {}  # iso_date -> count
            for v in visitors:
                ts = v.get("timestamp", "") if isinstance(v, dict) else ""
                if not ts:
                    continue
                try:
                    # Format "2026-05-29T09:00:47.000Z"
                    day = ts[:10]  # "2026-05-29"
                    if start_date.isoformat() <= day <= today.isoformat():
                        buckets[day] = buckets.get(day, 0) + 1
                except Exception:
                    pass
            # Construire le tableau dans l'ordre chronologique
            daily = []
            for i in range(days - 1, -1, -1):
                d = (today - _dt3.timedelta(days=i)).isoformat()
                daily.append(buckets.get(d, 0))
            result = {"total": sum(daily), "daily": daily}
        _VA_DAILY_CACHE[key] = (now, result)
        return result
    except Exception:
        return result


def _sparkline_svg(values: list, width: int = 90, height: int = 28, color: str = "#a855f7") -> str:
    """Mini sparkline avec area fill."""
    if not values:
        return ""
    n = len(values)
    if n < 2:
        return ""
    max_v = max(values) or 1
    pts = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * (width - 4) + 2
        y = height - 4 - (v / max_v) * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    pts_str = " ".join(pts)
    area_pts = f"2,{height} {pts_str} {width-2},{height}"
    grad_id = f"spk-{id(values) % 100000}"
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' style='overflow:visible;display:block'>"
        f"<defs><linearGradient id='{grad_id}' x1='0' x2='0' y1='0' y2='1'>"
        f"<stop offset='0%' stop-color='{color}' stop-opacity='.35'/>"
        f"<stop offset='100%' stop-color='{color}' stop-opacity='0'/>"
        f"</linearGradient></defs>"
        f"<polygon points='{area_pts}' fill='url(#{grad_id})'/>"
        f"<polyline points='{pts_str}' fill='none' stroke='{color}' stroke-width='1.8' stroke-linejoin='round' stroke-linecap='round'/>"
        f"</svg>"
    )


def _get_model_clicks_period(model_name: str, days: int = 7) -> dict:
    """Retourne {total, daily: [...]} pour un modèle sur N derniers jours.

    Réutilise _get_links_clicks_period en récupérant d'abord les links du modèle.
    """
    try:
        import gms
        if not gms.is_configured():
            return {"total": 0, "daily": [0] * days}
        grouped = gms.get_links_grouped_by_model()
        link_ids = grouped.get(model_name, [])
        if not link_ids:
            return {"total": 0, "daily": [0] * days}
        return _get_links_clicks_period(link_ids, days=days)
    except Exception:
        return {"total": 0, "daily": [0] * days}


def _render_gms_clicks_widget() -> str:
    """Widget clicks GMS par modèle — style Infloww : cartes compactes par identité."""
    try:
        import gms
        if not gms.is_configured():
            return ""
    except Exception:
        return ""

    from flask import request as _req
    import datetime as _dt

    today = _dt.date.today()

    # Période : current_h1 (1-15) ou current_h2 (16-end), avec switches prev_*
    period = "current_h2" if today.day > 15 else "current_h1"
    try:
        period = _req.args.get("va_clicks_period", period) or period
    except Exception:
        pass

    def _range_for(p):
        first_of_month = today.replace(day=1)
        if p == "current_h1":
            s = first_of_month
            e = min(first_of_month + _dt.timedelta(days=14), today)
        elif p == "current_h2":
            s = first_of_month + _dt.timedelta(days=15)
            if first_of_month.month == 12:
                nm = first_of_month.replace(year=first_of_month.year + 1, month=1)
            else:
                nm = first_of_month.replace(month=first_of_month.month + 1)
            e = min(nm - _dt.timedelta(days=1), today)
        elif p == "prev_h2":
            if first_of_month.month == 1:
                pf = first_of_month.replace(year=first_of_month.year - 1, month=12)
            else:
                pf = first_of_month.replace(month=first_of_month.month - 1)
            s = pf + _dt.timedelta(days=15)
            e = first_of_month - _dt.timedelta(days=1)
        else:
            if first_of_month.month == 1:
                pf = first_of_month.replace(year=first_of_month.year - 1, month=12)
            else:
                pf = first_of_month.replace(month=first_of_month.month - 1)
            s = pf
            e = pf + _dt.timedelta(days=14)
        return s, e

    start_dt, end_dt = _range_for(period)
    days_count = (end_dt - start_dt).days + 1

    # Limiter aux modèles principaux (qui correspondent aux identités du bot)
    identities = _list_identities()
    ident_to_model = {ident: ident.capitalize() for ident in identities}
    sorted_models = [ident_to_model[i] for i in sorted(identities)]

    # Fetch en parallèle pour les 5 modèles (3-5x plus rapide que séquentiel)
    from concurrent.futures import ThreadPoolExecutor
    sorted_idents = sorted(identities)

    def _fetch_one(ident):
        try:
            return ident, _get_model_clicks_period(ident_to_model[ident], days=days_count)
        except Exception:
            return ident, {"total": 0, "daily": [0] * days_count}

    results = {}
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(sorted_idents) or 1)) as pool:
            for ident, data in pool.map(_fetch_one, sorted_idents):
                results[ident] = data
    except Exception:
        for ident in sorted_idents:
            results[ident] = {"total": 0, "daily": [0] * days_count}

    cards_html = []
    total_clicks = 0
    total_visitors = 0
    # Pré-calculer le grouping une fois (cache déjà au niveau gms)
    grouped_links = gms.get_links_grouped_by_model()
    for ident in sorted_idents:
        model = ident_to_model[ident]
        data = results.get(ident) or {"total": 0, "daily": [0] * days_count}
        clicks = int(data.get("total", 0))
        daily = data.get("daily", []) or [0] * days_count
        total_clicks += clicks

        # Avatar identité
        avatar_url = _identity_avatar_url(ident)
        avatar_html = (
            f"<img src='{avatar_url}' class='vac-card-avatar' alt='{ident}' loading='lazy'>"
            if avatar_url else
            f"<div class='vac-card-avatar vac-card-avatar-fallback'>{ident[:1].upper()}</div>"
        )

        # Trend
        if clicks > 0 and len(daily) >= 2:
            trend_up = daily[-1] >= daily[-2]
            trend_color = "#22c55e" if trend_up else "#ef4444"
            trend_arrow = "↑" if trend_up else "↓"
        else:
            trend_color = "#6b7280"
            trend_arrow = "—"

        # Sparkline
        spark_color = "#3b82f6" if clicks > 0 else "#6b7280"
        spark = _sparkline_svg(daily, width=140, height=32, color=spark_color)

        n_links = len(grouped_links.get(model, []))
        cards_html.append(
            f"<div class='vac-card'>"
            f"<div class='vac-card-head'>"
            f"{avatar_html}"
            f"<div class='vac-card-info'>"
            f"<div class='vac-card-name'>@{ident}</div>"
            f"<div class='vac-card-sub'>{n_links} lien{'s' if n_links > 1 else ''}</div>"
            f"</div>"
            f"<div class='vac-card-trend' style='color:{trend_color}'>{trend_arrow}</div>"
            f"</div>"
            f"<div class='vac-card-value'>{clicks:,}</div>"
            f"<div class='vac-card-label'>clicks</div>"
            f"<div class='vac-card-spark'>{spark}</div>"
            f"</div>"
        )

    if not cards_html:
        return ""

    def _btn(p, txt):
        active = "vac-btn-active" if p == period else ""
        return f"<a href='?tab=valist&va_clicks_period={p}' class='vac-btn {active}'>{txt}</a>"

    mois_fr = ["janv", "févr", "mars", "avr", "mai", "juin",
               "juil", "août", "sept", "oct", "nov", "déc"]
    period_label_short = f"{start_dt.day} → {end_dt.day} {mois_fr[start_dt.month - 1]}"

    css = """
<style>
.vac-widget{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px;margin-bottom:20px}
.vac-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px;flex-wrap:wrap}
.vac-title{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;letter-spacing:-.01em}
.vac-title svg{color:#3b82f6}
.vac-subtitle{font-size:11px;color:#888;font-weight:400;margin-left:6px}
.vac-period-row{display:flex;gap:5px;flex-wrap:wrap}
.vac-btn{padding:6px 12px;background:transparent;border:1px solid #2a2a2a;color:#aaa;border-radius:7px;font-size:12px;font-weight:600;text-decoration:none;transition:all .15s}
.vac-btn:hover{background:rgba(255,255,255,.05);color:#fff}
.vac-btn-active{background:#3b82f6 !important;border-color:#3b82f6 !important;color:#fff !important}
/* Grid de cartes par modèle */
.vac-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.vac-card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:6px;transition:all .15s;position:relative;overflow:hidden}
.vac-card:hover{border-color:rgba(59,130,246,.4);transform:translateY(-2px)}
.vac-card-head{display:flex;align-items:center;gap:10px}
.vac-card-avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a;flex-shrink:0}
.vac-card-avatar-fallback{background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:15px;border:0}
.vac-card-info{flex:1;min-width:0}
.vac-card-name{font-weight:700;font-size:13px;letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vac-card-sub{font-size:10px;color:#888;margin-top:2px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.vac-card-trend{font-size:16px;font-weight:800;line-height:1}
.vac-card-value{font-size:28px;font-weight:800;letter-spacing:-.03em;line-height:1;margin-top:4px}
.vac-card-label{font-size:11px;color:#888;font-weight:600;letter-spacing:.02em}
.vac-card-spark{margin-top:auto;display:flex;align-items:center;justify-content:center;opacity:.9}
body.light .vac-widget{background:#fff;border-color:#e5e7eb}
body.light .vac-btn{color:#666;border-color:#e5e7eb}
body.light .vac-btn:hover{background:#f3f4f6;color:#111}
body.light .vac-card{background:#f9fafb;border-color:#e5e7eb}
body.light .vac-card-name{color:#111}
</style>
"""

    return (
        css
        + "<div class='vac-widget'>"
        + "<div class='vac-head'>"
        + "<div class='vac-title'>"
        + "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2.2'><path d='M22 12h-4l-3 9L9 3l-3 9H2'/></svg>"
        + f"Performance des modèles<span class='vac-subtitle'>{period_label_short} · {total_clicks} clicks</span>"
        + "</div>"
        + "<div class='vac-period-row'>"
        + _btn("prev_h1", "M-1 · 1-15")
        + _btn("prev_h2", "M-1 · 16-fin")
        + _btn("current_h1", "Ce mois · 1-15")
        + _btn("current_h2", "Ce mois · 16-fin")
        + "</div>"
        + "</div>"
        + "<div class='vac-grid'>"
        + "".join(cards_html)
        + "</div>"
        + "</div>"
    )


def _render_va_list_html() -> str:
    try:
        clicks_widget = _render_gms_clicks_widget()
    except Exception:
        clicks_widget = ""
    try:
        return clicks_widget + _render_va_list_html_inner()
    except Exception as e:
        return clicks_widget + (
            f"<div style='padding:18px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);"
            f"border-radius:10px;color:#ef4444;font-size:13px'>❌ Erreur rendu liste VAs : {type(e).__name__}: {e}</div>"
        )


def _render_va_list_html_inner() -> str:
    users = _load_users()
    if not users:
        return (
            "<div style='padding:60px 20px;text-align:center;color:#888;background:#0f1116;border:1px solid #2a2a2a;border-radius:14px'>"
            "<svg viewBox='0 0 24 24' width='44' height='44' fill='none' stroke='currentColor' stroke-width='1.5' style='margin-bottom:12px;opacity:.5'><path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M23 21v-2a4 4 0 0 0-3-3.87'/><path d='M16 3.13a4 4 0 0 1 0 7.75'/></svg>"
            "<p style='margin:0;font-size:14px;font-weight:600'>Aucun VA assigné pour l'instant.</p>"
            "<p style='margin:6px 0 0;font-size:12px;color:#666'>Les VAs apparaitront ici dès qu'ils utiliseront /assignme sur Discord.</p>"
            "</div>"
        )

    # Regrouper par identité
    by_identity = {}
    for uid, data in users.items():
        if isinstance(data, dict):
            identity = data.get("identity", "?")
        else:
            identity = str(data)
        by_identity.setdefault(identity, []).append((uid, data))

    all_identities = _list_identities()

    css = """
<style>
/* === Layout Vault 2 panneaux : sidebar liste + détail === */
.va-vault-layout{display:grid;grid-template-columns:320px 1fr;gap:18px;align-items:start}
@media(max-width:1000px){.va-vault-layout{grid-template-columns:1fr}}
.va-vault-sidebar{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:12px;max-height:calc(100vh - 200px);overflow:hidden;position:sticky;top:18px}
.va-vault-detail{min-width:0}
/* Sidebar toolbar */
.va-vault-toolbar{display:flex;flex-direction:column;gap:8px;flex-shrink:0}
.va-vault-search{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:9px;padding:8px 12px;display:flex;align-items:center;gap:8px;transition:all .15s}
.va-vault-search:focus-within{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
.va-vault-search input{flex:1;background:transparent;border:0;color:#fff;outline:none;font-size:13px;font-family:inherit;padding:0;margin:0}
.va-vault-search input::placeholder{color:#666}
.va-vault-filter{background:#1a1a1a;border:1px solid #2a2a2a;color:#aaa;border-radius:9px;padding:8px 12px;font-size:12px;font-family:inherit;cursor:pointer;outline:none}
.va-vault-filter:focus{border-color:#3b82f6}
/* Liste sidebar scrollable */
.va-vault-list{display:flex;flex-direction:column;gap:6px;overflow-y:auto;flex:1;margin:0 -6px;padding:0 6px}
.va-vlist-section{display:flex;flex-direction:column;gap:3px;margin-bottom:6px}
.va-vlist-section-head{display:flex;align-items:center;gap:4px;font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;padding:6px 4px 4px 8px;border-radius:8px;transition:background .12s}
.va-vlist-section-head:hover{background:rgba(255,255,255,.04)}
.va-vlist-section-head-main{display:flex;align-items:center;gap:8px;flex:1;cursor:pointer;min-width:0;padding:2px 0}
.va-vlist-section-head-main > span:nth-child(2){flex:1;color:#aaa;font-size:12px;letter-spacing:-.01em;text-transform:none;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.va-vlist-section-active .va-vlist-section-head{background:linear-gradient(90deg,rgba(59,130,246,.18),rgba(168,85,247,.08));color:#60a5fa}
/* Toggle chevron pour collapse/expand */
.va-vlist-toggle{background:rgba(255,255,255,.04);border:0;color:#888;width:26px;height:26px;border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;padding:0;transition:all .15s}
.va-vlist-toggle:hover{background:rgba(255,255,255,.1);color:#fff}
.va-vlist-toggle svg{transition:transform .2s}
.va-vlist-section.collapsed .va-vlist-toggle svg{transform:rotate(-90deg)}
/* Body collapsible */
.va-vlist-section-body{display:flex;flex-direction:column;gap:3px;overflow:hidden;transition:max-height .25s ease,opacity .15s,margin-top .15s;max-height:1000px;opacity:1;margin-top:2px}
.va-vlist-section.collapsed .va-vlist-section-body{max-height:0;opacity:0;margin-top:0;pointer-events:none}
body.light .va-vlist-section-head:hover{background:#f3f4f6}
body.light .va-vlist-section-active .va-vlist-section-head{background:linear-gradient(90deg,#dbeafe,#ede9fe);color:#3b82f6}
body.light .va-vlist-toggle{background:#f3f4f6}
body.light .va-vlist-toggle:hover{background:#e5e7eb;color:#111}
.va-vlist-ident-av{width:22px;height:22px;border-radius:50%;object-fit:cover;flex-shrink:0}
.va-vlist-section-head > span:nth-child(2){flex:1;color:#aaa;font-size:12px;letter-spacing:-.01em;text-transform:none;font-weight:600}
.va-vlist-count{background:rgba(59,130,246,.15);color:#60a5fa;padding:2px 7px;border-radius:9px;font-size:10px;font-weight:700}
.va-vlist-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:10px;cursor:pointer;border:1px solid transparent;transition:all .12s}
.va-vlist-item:hover{background:rgba(255,255,255,.04)}
.va-vlist-item.va-vlist-selected{background:linear-gradient(90deg,rgba(59,130,246,.2),rgba(168,85,247,.1));border-color:rgba(59,130,246,.4)}
.va-vlist-pp-wrap{position:relative;width:36px;height:36px;flex-shrink:0}
.va-vlist-pp{width:36px;height:36px;border-radius:50%;object-fit:cover;display:block}
.va-vlist-pp-fallback{display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;font-weight:800;font-size:13px}
.va-vlist-dot{position:absolute;bottom:0;right:0;width:10px;height:10px;border-radius:50%;border:2px solid #0f1116}
.va-vlist-dot-on{background:#22c55e}
.va-vlist-dot-off{background:#6b7280}
.va-vlist-info{flex:1;min-width:0}
.va-vlist-name{font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:-.01em}
.va-vlist-sub{font-size:11px;color:#888;margin-top:2px;display:flex;gap:4px;align-items:center}
.va-vlist-mini-badge{font-size:12px;line-height:1}
/* Détail panel : header guidé */
.va-detail-hint{padding:60px 20px;text-align:center;color:#666;font-size:13px}
body.light .va-vault-sidebar{background:#fff;border-color:#e5e7eb}
body.light .va-vault-search,body.light .va-vault-filter{background:#f9fafb;border-color:#e5e7eb;color:#111}
body.light .va-vault-search input{color:#111}
body.light .va-vlist-item:hover{background:#f3f4f6}
body.light .va-vlist-item.va-vlist-selected{background:linear-gradient(90deg,#dbeafe,#ede9fe);border-color:rgba(59,130,246,.3)}
body.light .va-vlist-dot{border-color:#fff}
/* Animation fade quand un VA est masqué/affiché */
.va-card{opacity:1;transition:opacity .15s}
.va-card.va-hidden{display:none}
.va-section.va-empty{display:none}
.va-section{margin-bottom:24px;background:#0f1116;border:1px solid #2a2a2a;border-radius:16px;padding:20px 22px}
.va-section-head{display:flex;align-items:center;gap:14px;margin-bottom:18px;padding-bottom:16px;border-bottom:1px solid #2a2a2a}
.va-section-avatar{width:48px;height:48px;border-radius:50%;object-fit:cover;border:2px solid rgba(59,130,246,.4);flex-shrink:0}
.va-section-name{font-weight:800;font-size:18px;letter-spacing:-.02em}
.va-section-count{background:rgba(59,130,246,.12);color:#60a5fa;font-size:11px;font-weight:700;padding:4px 11px;border-radius:20px;letter-spacing:.02em;text-transform:uppercase}
.va-list{display:flex;flex-direction:column;gap:8px}
/* Vault-style : pastille verte sur avatar, badge rose à droite, row clickable */
.va-card{display:grid;grid-template-columns:52px minmax(180px,1fr) auto auto;gap:16px;align-items:center;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px;padding:14px 18px;transition:all .15s}
.va-card:hover{background:#1f1f1f;border-color:#3a3a3a}
/* Wrapper avatar pour positionner la pastille verte */
.va-pp-wrap{position:relative;width:44px;height:44px;flex-shrink:0}
.va-pp,.va-pp-fallback{width:44px;height:44px;display:block}
.va-status-dot-on-avatar{position:absolute;bottom:0;right:0;width:13px;height:13px;border-radius:50%;background:#22c55e;border:2.5px solid #1a1a1a}
.va-status-dot-off-avatar{position:absolute;bottom:0;right:0;width:13px;height:13px;border-radius:50%;background:#6b7280;border:2.5px solid #1a1a1a}
/* Badge rose à droite avec icône (clicks ou salon) */
.va-pink-badge{display:inline-flex;align-items:center;gap:5px;background:rgba(244,114,182,.12);color:#f472b6;font-size:12px;font-weight:700;padding:5px 11px;border-radius:14px;letter-spacing:-.01em;cursor:default;border:1px solid rgba(244,114,182,.2)}
.va-pink-badge svg{flex-shrink:0}
.va-actions{display:flex;align-items:center;gap:10px;justify-content:flex-end}
body.light .va-status-dot-on-avatar,body.light .va-status-dot-off-avatar{border-color:#f9fafb}
.va-ig-btn{background:transparent;border:1px solid currentColor;padding:6px 11px;border-radius:7px;font-size:11px;cursor:pointer;font-weight:700;margin:0;font-family:inherit;display:inline-flex;align-items:center;gap:5px;width:135px;white-space:nowrap;justify-content:flex-start;height:34px;box-sizing:border-box;transition:all .15s}
.va-ig-btn:hover{background:currentColor;color:#fff !important}
.va-ig-btn:hover .va-ig-label{color:#fff}
.va-ig-label{overflow:hidden;text-overflow:ellipsis;font-size:11px;flex:1;text-align:left;font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace}
.va-pay-btn{background:transparent;border:1px solid currentColor;padding:6px 11px;border-radius:7px;font-size:11px;cursor:pointer;font-weight:700;margin:0;font-family:inherit;display:inline-flex;align-items:center;gap:5px;width:110px;white-space:nowrap;justify-content:flex-start;height:34px;box-sizing:border-box;transition:all .15s}
.va-pay-btn:hover{background:currentColor;color:#fff !important}
.va-pay-btn:hover .va-pay-label{color:#fff}
.va-pay-label{overflow:hidden;text-overflow:ellipsis;font-size:11px;flex:1;text-align:left}
.va-links-btn{background:rgba(168,85,247,.1);border:1px solid rgba(168,85,247,.3);color:#a855f7;padding:7px 11px;border-radius:7px;font-size:11px;cursor:pointer;font-weight:700;margin:0;font-family:inherit;display:inline-flex;align-items:center;gap:5px;width:140px;white-space:nowrap;justify-content:flex-start;height:34px;box-sizing:border-box}
.va-links-btn:hover{background:rgba(168,85,247,.2)}
.va-links-btn-label{font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace;font-size:11px;letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;flex:1;display:inline-block;line-height:1;text-align:left}
.va-mini-stat{width:170px;height:48px;box-sizing:border-box}
.va-change-form{width:130px}
.va-change-form select{flex:1;min-width:0}
.va-reset-btn{width:80px;text-align:center}
@media(max-width:1100px){
  .va-card{grid-template-columns:46px minmax(0,1fr) auto;gap:10px}
  .va-col-auto,.va-col-salon{grid-column:2/-2;justify-self:start}
  .va-actions{grid-column:1/-1;justify-content:flex-start;flex-wrap:wrap;padding-top:8px;border-top:1px dashed #2a2a2a;margin-top:4px}
}
.va-card:hover{border-color:rgba(59,130,246,.3);background:#202020}
.va-pp{width:46px;height:46px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a;background:#222;flex-shrink:0}
.va-pp-fallback{width:46px;height:46px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:18px;flex-shrink:0}
.va-info{min-width:0;overflow:hidden;display:flex;flex-direction:column;gap:2px}
.va-username{font-weight:700;font-size:14px;letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;color:#fff}
.va-id{font-family:monospace;font-size:11px;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.va-salon{font-size:11px;color:#888;display:inline-flex;align-items:center;gap:5px;text-decoration:none;background:rgba(255,255,255,.04);padding:5px 10px;border-radius:7px;font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace;letter-spacing:-.01em;white-space:nowrap;transition:all .15s}
.va-salon:hover{background:rgba(59,130,246,.15);color:#3b82f6}
.va-auto-pill{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:6px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.va-auto-on{background:rgba(34,197,94,.15);color:#22c55e}
.va-auto-off{background:rgba(107,114,128,.15);color:#9ca3af}
.va-change-form{display:flex;gap:6px;align-items:center;margin:0}
.va-change-form select{padding:7px 10px;background:#0f1116;border:1px solid #2a2a2a;color:#fff;border-radius:7px;font-size:12px;width:auto;font-family:inherit;cursor:pointer}
.va-change-form button{padding:7px 12px;background:#3b82f6;color:#fff;border:0;border-radius:7px;font-size:12px;cursor:pointer;font-weight:600;margin:0;font-family:inherit}
.va-change-form button:hover{background:#2563eb}
.va-reset-btn{background:transparent;border:1px solid rgba(239,68,68,.3);color:#ef4444;padding:7px 14px;border-radius:7px;font-size:12px;cursor:pointer;font-weight:600;margin:0;font-family:inherit}
.va-reset-btn:hover{background:rgba(239,68,68,.1)}
/* Mini stat clicks avec sparkline (à côté du username) */
.va-mini-stat{display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(168,85,247,.07);border:1px solid rgba(168,85,247,.18);border-radius:10px;min-width:140px}
.va-mini-num{font-size:15px;font-weight:800;letter-spacing:-.02em;line-height:1}
.va-mini-label{font-size:10px;color:#888;margin-top:3px;font-weight:600;letter-spacing:.03em;text-align:right}
body.light .va-mini-stat{background:rgba(168,85,247,.06);border-color:rgba(168,85,247,.2)}
@media(max-width:900px){.va-card{grid-template-columns:auto 1fr;grid-auto-rows:auto}.va-card > *{grid-column:span 2}.va-pp,.va-pp-fallback{grid-column:1;grid-row:1}.va-info{grid-column:2;grid-row:1}}
body.light .va-section{background:#fff;border-color:#e5e7eb}
body.light .va-section-head{border-color:#e5e7eb}
body.light .va-card{background:#f9fafb;border-color:#e5e7eb}
body.light .va-card:hover{background:#fff}
body.light .va-change-form select{background:#fff;border-color:#e5e7eb;color:#111}
body.light .va-id{color:#9ca3af}
</style>
"""

    # Pré-calculer une map link_id -> {shortcode, name} pour afficher dans les cartes
    _links_info_map = {}
    try:
        import gms as _gms_pre
        if _gms_pre.is_configured():
            _grp = _gms_pre.get_links_grouped_by_model()
            _res_pre = _gms_pre.list_all_links()
            if _res_pre.get("ok"):
                for _l in _res_pre.get("links", []):
                    _lid = _l.get("id")
                    if _lid:
                        _links_info_map[_lid] = {
                            "shortcode": _l.get("shortcode", ""),
                            "name": _l.get("display_name") or _l.get("shortcode", ""),
                        }
    except Exception:
        pass

    # ===== Pré-calcul parallèle des clicks pour TOUS les VAs (1 round-trip) =====
    # Sinon : chaque carte fait son appel série -> 4 VAs = 4×~200ms = 800ms+
    import datetime as _dt_pre
    _today_pre = _dt_pre.date.today()
    if _today_pre.day <= 15:
        _pre_days = _today_pre.day
    else:
        _pre_days = _today_pre.day - 15

    _va_clicks_cache = {}  # uid -> {total, daily, source: 'links'|'model'}
    try:
        from concurrent.futures import ThreadPoolExecutor as _TPE
        # Collecter tous les fetch à faire (déduplication)
        fetch_tasks = []  # [(uid, kind, key)] où key = "lnk_..." tuple ou model name
        for uid, data in users.items():
            assigned = _get_links_for_va(uid)
            if assigned:
                fetch_tasks.append((uid, "links", tuple(sorted(assigned))))
            else:
                ident = data.get("identity", "?") if isinstance(data, dict) else str(data)
                model = (ident or "").strip().capitalize()
                fetch_tasks.append((uid, "model", model))

        def _fetch_va(task):
            uid, kind, key = task
            try:
                if kind == "links":
                    d = _get_links_clicks_period(list(key), days=_pre_days)
                else:
                    d = _get_model_clicks_period(key, days=_pre_days)
                return uid, kind, d
            except Exception:
                return uid, kind, {"total": 0, "daily": [0] * _pre_days}

        if fetch_tasks:
            with _TPE(max_workers=min(8, len(fetch_tasks))) as pool:
                for uid, kind, d in pool.map(_fetch_va, fetch_tasks):
                    _va_clicks_cache[uid] = {"data": d, "source": kind}
    except Exception:
        pass

    # ===== Sidebar Vault style : liste compacte des VAs par identité =====
    identities_for_filter = sorted(by_identity.keys())
    ident_opts = "".join(
        f"<option value='{i}'>{i.capitalize()}</option>" for i in identities_for_filter
    )

    # Construire la liste sidebar
    sidebar_rows = []
    first_uid = ""
    for identity in identities_for_filter:
        members = by_identity[identity]
        ident_avatar = _identity_avatar_url(identity)
        # Header identité
        ident_av_html = (
            f"<img src='{ident_avatar}' class='va-vlist-ident-av' alt='{identity}'>"
            if ident_avatar else
            f"<div class='va-vlist-ident-av' style='background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:13px'>{identity[:1].upper()}</div>"
        )
        sidebar_rows.append(
            f"<div class='va-vlist-section' data-vlist-identity='{identity}'>"
            f"<div class='va-vlist-section-head'>"
            f"<div class='va-vlist-section-head-main' onclick=\"vaShowIdentity('{identity}')\">"
            f"{ident_av_html}<span>@{identity}</span>"
            f"<span class='va-vlist-count'>{len(members)}</span>"
            f"</div>"
            f"<button class='va-vlist-toggle' onclick=\"vaToggleSection(this)\" title='Réduire / déplier'>"
            f"<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2.5'><polyline points='6 9 12 15 18 9'/></svg>"
            f"</button>"
            f"</div>"
            f"<div class='va-vlist-section-body'>"
        )
        for uid, data in members:
            try:
                uname = _resolve_username(uid)
                if not isinstance(uname, str):
                    uname = str(uname)
                avatar_url = _resolve_avatar_url(uid)
                if not isinstance(avatar_url, str):
                    avatar_url = ""
                if isinstance(data, dict):
                    is_a = data.get("auto_post", True)
                else:
                    is_a = True
                insta_va_side = _get_va_insta(uid)
                ig_h_side = insta_va_side.get("handle", "")
                pay_side = _get_va_payment(uid)
                pay_has = bool(pay_side.get("kind"))
                assigned_side = _get_links_for_va(uid)

                pp_side = (
                    f"<img src='{avatar_url}' class='va-vlist-pp' alt=''>"
                    if avatar_url else
                    f"<div class='va-vlist-pp va-vlist-pp-fallback'>{(uname[:1] if uname else '?').upper()}</div>"
                )
                status_dot_side = (
                    "<div class='va-vlist-dot va-vlist-dot-on'></div>"
                    if is_a else
                    "<div class='va-vlist-dot va-vlist-dot-off'></div>"
                )
                # Mini badges pour les features configurées
                badges = []
                if assigned_side:
                    badges.append(f"<span class='va-vlist-mini-badge' style='color:#a855f7' title='{len(assigned_side)} lien(s) GMS'>🔗</span>")
                if pay_has:
                    badges.append("<span class='va-vlist-mini-badge' style='color:#22c55e' title='Paiement configuré'>💳</span>")
                if ig_h_side:
                    badges.append("<span class='va-vlist-mini-badge' style='color:#ec4899' title='Instagram lié'>📷</span>")
                badges_html = "".join(badges) or "<span class='va-vlist-mini-badge' style='color:#444'>—</span>"

                disp_name = uname if uname and uname != str(uid) else "—"
                search_b = (uname + " " + uid + " " + identity).lower()
                if not first_uid:
                    first_uid = str(uid)
                sidebar_rows.append(
                    f"<div class='va-vlist-item' data-vlist-uid='{uid}' "
                    f"data-vlist-search='{search_b}' data-vlist-identity='{identity}' "
                    f"onclick=\"vaSelectVa('{uid}')\">"
                    f"<div class='va-vlist-pp-wrap'>{pp_side}{status_dot_side}</div>"
                    f"<div class='va-vlist-info'>"
                    f"<div class='va-vlist-name'>{disp_name}</div>"
                    f"<div class='va-vlist-sub'>{''.join(badges_html if isinstance(badges_html, str) else badges_html)}</div>"
                    f"</div>"
                    f"</div>"
                )
            except Exception:
                continue
        sidebar_rows.append("</div></div>")  # close section-body + section

    vault_sidebar = (
        "<div class='va-vault-sidebar'>"
        "<div class='va-vault-toolbar'>"
        "<div class='va-vault-search'>"
        "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='#888' stroke-width='2'>"
        "<circle cx='11' cy='11' r='8'/><path d='m21 21-4.35-4.35'/></svg>"
        "<input type='text' id='va-search' placeholder='Rechercher…' oninput='vaSearch(this.value)'>"
        "</div>"
        "<select id='va-filter-identity' onchange='vaSearch(null)' class='va-vault-filter'>"
        "<option value=''>Toutes les identités</option>"
        + ident_opts +
        "</select>"
        "</div>"
        "<div class='va-vault-list' id='va-vault-list'>"
        + "".join(sidebar_rows)
        + "</div>"
        "</div>"
    )

    sections = []
    for identity in sorted(by_identity.keys()):
        members = by_identity[identity]
        ident_avatar = _identity_avatar_url(identity)
        avatar_html = (
            f"<img src='{ident_avatar}' class='va-section-avatar' alt='{identity}'>"
            if ident_avatar else
            f"<div class='va-section-avatar' style='display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;font-weight:800;border:0'>{identity[:1].upper()}</div>"
        )

        cards = []
        for uid, data in members:
            try:
                if isinstance(data, dict):
                    channel_id = data.get("channel_id", "")
                    is_auto = data.get("auto_post", True)
                    cur_identity = data.get("identity", identity)
                else:
                    channel_id = ""
                    is_auto = True
                    cur_identity = identity

                # Normaliser channel_id en string (parfois stocké en int Discord)
                channel_id = str(channel_id) if channel_id else ""
                username = _resolve_username(uid)
                # Sécurité : forcer string
                if not isinstance(username, str):
                    username = str(username)
                avatar_url = _resolve_avatar_url(uid)
                if not isinstance(avatar_url, str):
                    avatar_url = ""
            except Exception:
                # Si une entrée VA est corrompue, on skip plutôt que de crasher
                continue
            avatar_inner = (
                f"<img src='{avatar_url}' class='va-pp' loading='lazy' alt='@{username}'>"
                if avatar_url else
                f"<div class='va-pp-fallback'>{(username[:1] if username else '?').upper()}</div>"
            )
            status_class = "va-status-dot-on-avatar" if is_auto else "va-status-dot-off-avatar"
            status_title = "Auto-post actif" if is_auto else "Manuel"
            pp_html = (
                f"<div class='va-pp-wrap' title='{status_title}'>"
                f"{avatar_inner}"
                f"<div class='{status_class}'></div>"
                f"</div>"
            )

            if username == str(uid):
                name_display = f"<span class='va-username' style='color:#888'>—</span>"
            else:
                # Tooltip = nom complet pour si le truncate cache une partie
                name_display = f"<span class='va-username' title='@{username}'>@{username}</span>"

            # Pas de pill séparée — statut auto-post est sur l'avatar (dot vert)
            # Badge rose Vault-style avec icône Discord (lien direct vers le salon)
            if channel_id:
                pink_badge = (
                    f"<a class='va-pink-badge' href='https://discord.com/channels/@me/{channel_id}' "
                    f"target='_blank' title='Ouvrir le salon Discord (#{channel_id})' "
                    f"style='text-decoration:none'>"
                    f"<svg viewBox='0 0 24 24' width='11' height='11' fill='currentColor'><path d='M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm-1 14H5V8l7 5 7-5v10zM12 11L5 6h14l-7 5z'/></svg>"
                    f"<span>{channel_id[-4:]}</span></a>"
                )
            else:
                pink_badge = ""

            opts = "".join(
                f"<option value='{i}'{' selected' if i == cur_identity else ''}>{i}</option>"
                for i in all_identities
            )
            change_form = (
                f"<form method='POST' action='/va/change_identity' class='va-change-form'>"
                f"<input type='hidden' name='user_id' value='{uid}'>"
                f"<select name='identity'>{opts}</select>"
                f"<button type='submit'>OK</button>"
                f"</form>"
            )

            reset_form = (
                f"<form method='POST' action='/va/reset' style='margin:0'>"
                f"<input type='hidden' name='user_id' value='{uid}'>"
                f"<button type='submit' class='va-reset-btn' "
                f"data-confirm=\"Reset @{username} ? Le VA gardera son salon Discord mais perdra son identité assignée.\">Reset</button>"
                f"</form>"
            )

            # Bouton "Liens" pour attribuer des liens GMS à ce VA
            assigned_links = _get_links_for_va(uid)
            # Construire le label/tooltip basé sur les liens assignés
            if assigned_links:
                first_link = _links_info_map.get(assigned_links[0], {})
                first_short = first_link.get("shortcode", "") or "?"
                if len(assigned_links) == 1:
                    btn_label = f"/{first_short}"
                else:
                    btn_label = f"/{first_short} +{len(assigned_links) - 1}"
                # Tooltip : liste complète
                tip_lines = []
                for lid in assigned_links[:8]:  # max 8 pour pas overflow
                    info = _links_info_map.get(lid, {})
                    name = info.get("name", "?")
                    sc = info.get("shortcode", "?")
                    tip_lines.append(f"/{sc} — {name}")
                if len(assigned_links) > 8:
                    tip_lines.append(f"… +{len(assigned_links) - 8} autres")
                tooltip = "\n".join(tip_lines).replace("\"", "&quot;")
            else:
                btn_label = "Aucun"
                tooltip = "Aucun lien assigné. Clic pour attribuer."

            links_btn_html = (
                f"<button type='button' onclick=\"vaLinksOpen('{uid}', '{username.replace(chr(39), chr(92)+chr(39))}')\" "
                f"class='va-links-btn' title=\"{tooltip}\">"
                f"<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2'><path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71'/><path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'/></svg>"
                f"<span class='va-links-btn-label'>{btn_label}</span>"
                f"</button>"
            )

            # Mini stat clicks AVEC sparkline (à côté du username)
            # Période = quinzaine en cours (1-15 ou 16-fin du mois, auto)
            import datetime as _dt_va
            _today_va = _dt_va.date.today()
            if _today_va.day <= 15:
                # 1ère quinzaine en cours
                _period_days = _today_va.day
                _period_label = f"1-15 {_today_va.strftime('%b').lower()}"
            else:
                # 2nde quinzaine en cours
                _period_days = _today_va.day - 15
                _period_label = f"16-fin {_today_va.strftime('%b').lower()}"
            mini_clicks_html = ""
            try:
                # Utiliser le cache pré-calculé (parallèle) au lieu de refaire l'appel
                pre = _va_clicks_cache.get(uid)
                if pre:
                    clicks_data = pre["data"]
                    is_fallback = (pre["source"] == "model")
                else:
                    # Fallback : pas dans le pre-cache, fetch direct
                    if assigned_links:
                        clicks_data = _get_links_clicks_period(assigned_links, days=_period_days)
                        is_fallback = False
                    else:
                        model_name = (identity or "").strip().capitalize()
                        clicks_data = _get_model_clicks_period(model_name, days=_period_days)
                        is_fallback = True
                label = f"{_period_label}" + (" · modèle" if is_fallback else "")

                total = clicks_data.get("total", 0)
                daily = clicks_data.get("daily", []) or [0] * 7
                # Toujours afficher le chip — même avec 0 — pour confirmer la connexion GMS
                if total > 0:
                    color = "#a855f7" if not is_fallback else "#3b82f6"
                    trend_up = daily[-1] >= daily[-2] if len(daily) >= 2 else True
                    arrow = "↑" if trend_up else "↓"
                    arrow_color = "#22c55e" if trend_up else "#ef4444"
                else:
                    # Etat muted pour 0 clicks
                    color = "#6b7280"
                    arrow = ""
                    arrow_color = "#444"
                spark = _sparkline_svg(daily, width=70, height=22, color=color)
                mini_clicks_html = (
                    f"<div class='va-mini-stat' style='border-color:{color}30;background:{color}10'>"
                    f"<div style='display:flex;flex-direction:column;align-items:flex-end;gap:0'>"
                    f"<div style='display:flex;align-items:center;gap:5px;line-height:1'>"
                    + (f"<span style='color:{arrow_color};font-weight:800;font-size:11px'>{arrow}</span>" if arrow else "")
                    + f"<span class='va-mini-num' style='color:{color}'>{total:,}</span>"
                    f"</div>"
                    f"<div class='va-mini-label'>{label}</div>"
                    f"</div>"
                    f"<div style='display:flex;align-items:center'>{spark}</div>"
                    f"</div>"
                )
            except Exception:
                pass

            # Bouton paiement (crypto ou taptap)
            payment = _get_va_payment(uid)
            if payment.get("kind") == "crypto":
                ct = payment.get("crypto_type", "?")
                net = payment.get("crypto_network", "")
                pay_label = f"{ct}" + (f" · {net.split(' ')[0]}" if net else "")
                pay_color = {"USDC": "#2775ca", "ETH": "#627eea",
                             "SOL": "#9945ff", "TRX": "#ef4444"}.get(ct, "#3b82f6")
                pay_icon = "💵" if ct == "USDC" else "₿"
            elif payment.get("kind") == "taptap":
                num = payment.get("taptap_number", "")
                net = payment.get("taptap_network", "")
                # afficher les 4 derniers chiffres
                short_num = ("…" + num[-4:]) if len(num) > 4 else num
                pay_label = f"{short_num}" if num else "TapTap"
                pay_color = "#f59e0b"
                pay_icon = "📱"
            else:
                pay_label = "Paiement"
                pay_color = "#444"
                pay_icon = "💳"

            pay_btn = (
                f"<button type='button' onclick=\"vaPayOpen('{uid}', '{username.replace(chr(39), chr(92)+chr(39))}')\" "
                f"class='va-pay-btn' style='border-color:{pay_color}40;color:{pay_color}' "
                f"title='Configurer le paiement'>"
                f"<span>{pay_icon}</span>"
                f"<span class='va-pay-label'>{pay_label}</span>"
                f"</button>"
            )

            # Bouton Instagram + indicateur santé
            insta = _get_va_insta(uid)
            ig_handle = insta.get("handle", "")
            if ig_handle:
                # Calcul du status santé d'après dernier post / scrape
                import time as _t_ig
                last_scraped = int(insta.get("last_scraped_at", 0))
                age_h = (_t_ig.time() - last_scraped) / 3600 if last_scraped else 999
                last_post = insta.get("last_post_at", "")
                post_age_days = 0
                try:
                    if last_post:
                        import datetime as _dt_ig
                        d_post = _dt_ig.date.fromisoformat(last_post[:10])
                        post_age_days = (_dt_ig.date.today() - d_post).days
                except Exception:
                    post_age_days = 999

                if not last_post or post_age_days > 14:
                    ig_color = "#ef4444"  # rouge : inactif
                    ig_dot = "🔴"
                elif post_age_days > 7:
                    ig_color = "#f59e0b"  # amber : ralenti
                    ig_dot = "🟡"
                else:
                    ig_color = "#22c55e"  # vert : actif
                    ig_dot = "🟢"
                ig_label = f"@{ig_handle[:14]}{'…' if len(ig_handle) > 14 else ''}"
            else:
                ig_color = "#444"
                ig_dot = ""
                ig_label = "Instagram"

            ig_btn = (
                f"<button type='button' onclick=\"vaInstaOpen('{uid}', '{username.replace(chr(39), chr(92)+chr(39))}')\" "
                f"class='va-ig-btn' style='border-color:{ig_color}40;color:{ig_color}' "
                f"title='Compte Instagram'>"
                f"<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2'><rect x='2' y='2' width='20' height='20' rx='5'/><path d='M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z'/><line x1='17.5' y1='6.5' x2='17.51' y2='6.5'/></svg>"
                f"<span class='va-ig-label'>{ig_label}</span>"
                + (f"<span style='font-size:8px'>{ig_dot}</span>" if ig_dot else "")
                + "</button>"
            )

            search_blob = (username + " " + uid + " " + identity).lower()
            cards.append(
                f"<div class='va-card' data-va-uid='{uid}' data-va-search='{search_blob}' data-va-identity='{identity}'>"
                f"{pp_html}"
                f"<div class='va-info'>"
                f"{name_display}"
                f"<div class='va-id'>{uid}</div>"
                f"</div>"
                f"{pink_badge}"
                f"<div class='va-actions'>"
                f"{ig_btn}"
                f"{links_btn_html}"
                f"{pay_btn}"
                f"{mini_clicks_html}"
                f"{change_form}"
                f"{reset_form}"
                f"</div>"
                f"</div>"
            )

        sections.append(
            f"<div class='va-section' data-va-section-identity='{identity}'>"
            f"<div class='va-section-head'>"
            f"{avatar_html}"
            f"<div class='va-section-name'>@{identity}</div>"
            f"<div class='va-section-count'>{len(members)} VA{'s' if len(members) > 1 else ''}</div>"
            f"</div>"
            f"<div class='va-list'>{''.join(cards)}</div>"
            f"</div>"
        )

    footer = (
        f"<div style='margin-top:18px;padding:12px 16px;background:rgba(59,130,246,.05);border:1px solid rgba(59,130,246,.2);border-radius:10px;color:#888;font-size:13px'>"
        f"💡 <b style='color:#3b82f6'>{len(users)}</b> VA{'s' if len(users) > 1 else ''} actif{'s' if len(users) > 1 else ''} réparti{'s' if len(users) > 1 else ''} sur <b style='color:#3b82f6'>{len(by_identity)}</b> identité{'s' if len(by_identity) > 1 else ''}"
        f"</div>"
    )

    # ====== Modal Instagram (handle + stats + scraper) ======
    all_va_insta = _load_va_insta()
    import json as _json_ig
    insta_data_json = _json_ig.dumps(all_va_insta, ensure_ascii=False)

    insta_modal_html = (
        "<div id='va-ig-modal' onclick='vaInstaClose(event)'>"
        "<div class='vim-box' onclick='event.stopPropagation()'>"
        "<div class='vim-head'>"
        "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#ec4899' stroke-width='2'><rect x='2' y='2' width='20' height='20' rx='5'/><path d='M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z'/><line x1='17.5' y1='6.5' x2='17.51' y2='6.5'/></svg>"
        "<div>Compte Instagram</div>"
        "<div id='vim-subtitle'></div>"
        "<button onclick='vaInstaClose()' class='vim-close'>×</button>"
        "</div>"
        "<div class='vim-body'>"
        "<label>Handle Instagram (sans @)</label>"
        "<div style='display:flex;gap:8px;align-items:stretch'>"
        "<input type='text' id='vim-handle' placeholder='amelia.xoxoo' maxlength='50' style='flex:1'>"
        "<a id='vim-open-link' href='#' target='_blank' class='vim-open-btn' title='Ouvrir sur Instagram'>"
        "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2'><path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/><polyline points='15 3 21 3 21 9'/><line x1='10' y1='14' x2='21' y2='3'/></svg>"
        "</a>"
        "</div>"
        # Stats si disponibles
        "<div id='vim-stats-block' style='display:none;margin-top:18px'>"
        "<div class='vim-stats-grid'>"
        "<div class='vim-stat'><div class='vim-stat-v' id='vim-followers'>—</div><div class='vim-stat-l'>Followers</div></div>"
        "<div class='vim-stat'><div class='vim-stat-v' id='vim-posts'>—</div><div class='vim-stat-l'>Posts</div></div>"
        "<div class='vim-stat'><div class='vim-stat-v' id='vim-last-post'>—</div><div class='vim-stat-l'>Dernier post</div></div>"
        "</div>"
        "<div id='vim-health' style='margin-top:12px;font-size:12px;padding:10px 14px;border-radius:8px;text-align:center'></div>"
        "<div id='vim-scraped-at' style='margin-top:8px;font-size:10px;color:#666;text-align:center'></div>"
        "</div>"
        "</div>"
        "<div class='vim-foot'>"
        "<button onclick='vaInstaClear()' class='vim-clear'>Effacer</button>"
        "<button onclick='vaInstaScrape()' class='vim-scrape' id='vim-scrape-btn'>"
        "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2.5' style='margin-right:4px'><polyline points='1 4 1 10 7 10'/><polyline points='23 20 23 14 17 14'/><path d='M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15'/></svg>"
        "<span class='vim-scrape-label'>Scraper</span>"
        "<span class='vim-scrape-spinner'></span>"
        "</button>"
        "<button onclick='vaInstaClose()' class='vim-cancel'>Annuler</button>"
        "<button onclick='vaInstaSave()' class='vim-save'>Enregistrer</button>"
        "</div>"
        "</div>"
        "</div>"
        + f"<script>window.__vaInstaData={insta_data_json};</script>"
    )

    insta_css_js = """
<style>
#va-ig-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);backdrop-filter:blur(6px);z-index:9999;align-items:center;justify-content:center;padding:30px}
#va-ig-modal.show{display:flex}
.vim-box{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;width:100%;max-width:480px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.6)}
.vim-head{padding:18px 22px;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px}
.vim-head > div:first-of-type{flex:1}
#vim-subtitle{font-size:11px;color:#888;font-weight:400}
.vim-close{background:transparent;border:0;color:#888;font-size:22px;cursor:pointer;padding:0 6px;line-height:1}
.vim-body{padding:18px 22px;display:flex;flex-direction:column;gap:4px}
.vim-body label{font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.vim-body input{background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;font-family:'JetBrains Mono',ui-monospace,monospace;width:100%;box-sizing:border-box}
.vim-body input:focus{border-color:#ec4899;outline:none;box-shadow:0 0 0 3px rgba(236,72,153,.15)}
.vim-open-btn{background:#1a1a1a;border:1px solid #2a2a2a;color:#aaa;padding:0 12px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none;flex-shrink:0;transition:all .15s}
.vim-open-btn:hover{background:#ec4899;color:#fff;border-color:#ec4899}
.vim-stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.vim-stat{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:10px 12px;text-align:center}
.vim-stat-v{font-size:18px;font-weight:800;letter-spacing:-.02em;color:#ec4899}
.vim-stat-l{font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;font-weight:600;margin-top:3px}
.vim-foot{padding:14px 18px;border-top:1px solid #2a2a2a;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
.vim-clear{background:transparent;border:1px solid rgba(239,68,68,.3);color:#ef4444;padding:9px 14px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit;margin-right:auto}
.vim-clear:hover{background:rgba(239,68,68,.1)}
.vim-cancel{background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:9px 16px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit}
.vim-scrape{background:transparent;border:1px solid #ec4899;color:#ec4899;padding:9px 14px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit;display:inline-flex;align-items:center;justify-content:center;min-width:100px}
.vim-scrape:hover{background:#ec4899;color:#fff}
.vim-scrape.loading{opacity:.85;cursor:wait}
.vim-scrape.loading .vim-scrape-label{display:none}
.vim-scrape.loading .vim-scrape-spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}
.vim-scrape-spinner{display:none}
.vim-save{background:#ec4899;color:#fff;border:0;padding:9px 18px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit}
.vim-save:hover{background:#db2777}
body.light .vim-box{background:#fff;border-color:#e5e7eb}
body.light .vim-head,body.light .vim-foot{border-color:#e5e7eb}
body.light .vim-body input{background:#fff;border-color:#e5e7eb;color:#111}
body.light .vim-stat{background:#f9fafb;border-color:#e5e7eb}
</style>
<script>
var _vimCurrentUid = null;
function vaInstaOpen(uid, username){
  _vimCurrentUid = uid;
  document.getElementById('vim-subtitle').textContent = '@' + username;
  var data = (window.__vaInstaData || {})[uid] || {};
  var handle = data.handle || '';
  document.getElementById('vim-handle').value = handle;
  vaInstaUpdateOpenLink();
  // Stats
  var hasStats = data.followers !== undefined && data.last_scraped_at;
  document.getElementById('vim-stats-block').style.display = hasStats ? 'block' : 'none';
  if(hasStats){
    document.getElementById('vim-followers').textContent = (data.followers || 0).toLocaleString();
    document.getElementById('vim-posts').textContent = (data.posts || 0).toLocaleString();
    var lp = data.last_post_at || '';
    document.getElementById('vim-last-post').textContent = lp ? lp.substring(0, 10) : '—';
    // Health
    var hEl = document.getElementById('vim-health');
    var ageDays = 999;
    if(lp){ try { ageDays = Math.floor((Date.now() - new Date(lp).getTime()) / 86400000); } catch(e){} }
    if(ageDays <= 7){ hEl.innerHTML = '🟢 Actif (post il y a ' + ageDays + 'j)'; hEl.style.cssText = 'background:rgba(34,197,94,.1);color:#22c55e;margin-top:12px;font-size:12px;padding:10px 14px;border-radius:8px;text-align:center;font-weight:600'; }
    else if(ageDays <= 14){ hEl.innerHTML = '🟡 Ralenti (' + ageDays + 'j sans poster)'; hEl.style.cssText = 'background:rgba(245,158,11,.1);color:#f59e0b;margin-top:12px;font-size:12px;padding:10px 14px;border-radius:8px;text-align:center;font-weight:600'; }
    else { hEl.innerHTML = '🔴 Inactif (' + ageDays + 'j sans poster)'; hEl.style.cssText = 'background:rgba(239,68,68,.1);color:#ef4444;margin-top:12px;font-size:12px;padding:10px 14px;border-radius:8px;text-align:center;font-weight:600'; }
    // Scraped at
    var scrapeAge = Math.floor((Date.now() / 1000 - (data.last_scraped_at || 0)) / 3600);
    document.getElementById('vim-scraped-at').textContent = 'Dernière vérif il y a ' + (scrapeAge < 24 ? scrapeAge + 'h' : Math.floor(scrapeAge / 24) + 'j');
  }
  document.getElementById('va-ig-modal').classList.add('show');
}
function vaInstaUpdateOpenLink(){
  var h = document.getElementById('vim-handle').value.trim().replace(/^@/, '');
  document.getElementById('vim-open-link').href = h ? ('https://instagram.com/' + h) : '#';
}
document.addEventListener('input', function(e){
  if(e.target && e.target.id === 'vim-handle') vaInstaUpdateOpenLink();
});
function vaInstaClose(e){
  if(e && e.target && e.target.id !== 'va-ig-modal' && e.target !== this) return;
  document.getElementById('va-ig-modal').classList.remove('show');
}
function vaInstaClear(){
  var form = new FormData();
  form.append('user_id', _vimCurrentUid);
  form.append('handle', '');
  fetch('/va/set_insta', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Compte Instagram effacé', 'success');
        setTimeout(function(){ window.location.reload(); }, 300);
      }
    });
}
function vaInstaSave(){
  var form = new FormData();
  form.append('user_id', _vimCurrentUid);
  form.append('handle', document.getElementById('vim-handle').value);
  fetch('/va/set_insta', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Compte Instagram enregistré', 'success');
        setTimeout(function(){ window.location.reload(); }, 300);
      }
    });
}
function vaInstaScrape(){
  var btn = document.getElementById('vim-scrape-btn');
  btn.classList.add('loading');
  btn.disabled = true;
  var form = new FormData();
  form.append('user_id', _vimCurrentUid);
  form.append('handle', document.getElementById('vim-handle').value);
  fetch('/va/scrape_insta', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      btn.classList.remove('loading'); btn.disabled = false;
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Profil scrapé : ' + d.followers.toLocaleString() + ' followers', 'success');
        setTimeout(function(){ window.location.reload(); }, 500);
      } else {
        if(typeof showToast === 'function') showToast('Erreur scrape : ' + (d.error || '?'), 'error');
      }
    });
}
</script>
"""

    # ====== Modal Paiement (crypto ou taptap) ======
    import json as _json_pay
    all_va_payments = _load_va_payments()
    pay_data_json = _json_pay.dumps(all_va_payments, ensure_ascii=False)
    pay_networks_json = _json_pay.dumps(VA_CRYPTO_NETWORKS, ensure_ascii=False)
    pay_taptap_json = _json_pay.dumps(TAPTAP_NETWORKS, ensure_ascii=False)

    pay_modal_html = (
        "<div id='va-pay-modal' onclick='vaPayClose(event)'>"
        "<div class='vpm-box' onclick='event.stopPropagation()'>"
        "<div class='vpm-head'>"
        "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#3b82f6' stroke-width='2'><rect x='2' y='5' width='20' height='14' rx='2'/><line x1='2' y1='10' x2='22' y2='10'/></svg>"
        "<div>Configurer le paiement</div>"
        "<div id='vpm-subtitle'></div>"
        "<button onclick='vaPayClose()' class='vpm-close'>×</button>"
        "</div>"
        # Toggle Crypto / TapTap
        "<div class='vpm-toggle'>"
        "<button class='vpm-kind-btn' data-kind='crypto' onclick='vaPaySetKind(\"crypto\")'>💵 Crypto</button>"
        "<button class='vpm-kind-btn' data-kind='taptap' onclick='vaPaySetKind(\"taptap\")'>📱 TapTap</button>"
        "</div>"
        # Form Crypto (caché par défaut)
        "<div id='vpm-form-crypto' class='vpm-form'>"
        "<label>Type</label>"
        "<select id='vpm-crypto-type' onchange='vaPayUpdateCryptoNetworks()'>"
        "<option value=''>—</option>"
        "<option value='USDC'>USDC</option>"
        "<option value='ETH'>ETH</option>"
        "<option value='SOL'>SOL</option>"
        "<option value='TRX'>TRX</option>"
        "</select>"
        "<label>Blockchain</label>"
        "<select id='vpm-crypto-network'><option value=''>Choisis d\\'abord le type</option></select>"
        "<label>Adresse</label>"
        "<input type='text' id='vpm-crypto-address' placeholder='0x… / T… / …' maxlength='200'>"
        "</div>"
        # Form TapTap (caché par défaut)
        "<div id='vpm-form-taptap' class='vpm-form' style='display:none'>"
        "<label>Numéro</label>"
        "<input type='tel' id='vpm-taptap-number' placeholder='+225 07 12 34 56 78' maxlength='30'>"
        "<label>Opérateur / Réseau</label>"
        "<select id='vpm-taptap-network'><option value=''>—</option></select>"
        "</div>"
        "<div class='vpm-foot'>"
        "<button onclick='vaPayClear()' class='vpm-clear'>Effacer</button>"
        "<button onclick='vaPayClose()' class='vpm-cancel'>Annuler</button>"
        "<button onclick='vaPaySave()' class='vpm-save'>Enregistrer</button>"
        "</div>"
        "</div>"
        "</div>"
        + f"<script>window.__vaPayData={pay_data_json};window.__vaPayCryptoNetworks={pay_networks_json};window.__vaPayTaptap={pay_taptap_json};</script>"
    )

    pay_css_js = """
<style>
#va-pay-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);backdrop-filter:blur(6px);z-index:9999;align-items:center;justify-content:center;padding:30px}
#va-pay-modal.show{display:flex}
.vpm-box{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;width:100%;max-width:480px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.6)}
.vpm-head{padding:18px 22px;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px}
.vpm-head > div:first-of-type{flex:1}
#vpm-subtitle{font-size:11px;color:#888;font-weight:400}
.vpm-close{background:transparent;border:0;color:#888;font-size:22px;cursor:pointer;padding:0 6px;line-height:1}
.vpm-toggle{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:14px 18px 6px}
.vpm-kind-btn{background:#1a1a1a;border:1px solid #2a2a2a;color:#aaa;padding:10px 14px;border-radius:9px;font-weight:700;cursor:pointer;font-family:inherit;font-size:13px;transition:all .15s}
.vpm-kind-btn:hover{background:#222;color:#fff}
.vpm-kind-btn.active{background:#3b82f6;border-color:#3b82f6;color:#fff}
.vpm-form{padding:14px 18px;display:flex;flex-direction:column;gap:4px}
.vpm-form label{font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-top:10px}
.vpm-form input,.vpm-form select{background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;font-family:inherit;width:100%;box-sizing:border-box;margin-top:4px}
.vpm-form input:focus,.vpm-form select:focus{border-color:#3b82f6;outline:none}
.vpm-foot{padding:14px 18px;border-top:1px solid #2a2a2a;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
.vpm-clear{background:transparent;border:1px solid rgba(239,68,68,.3);color:#ef4444;padding:9px 14px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit;margin-right:auto}
.vpm-clear:hover{background:rgba(239,68,68,.1)}
.vpm-cancel{background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:9px 16px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit}
.vpm-save{background:#3b82f6;color:#fff;border:0;padding:9px 18px;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px;font-family:inherit}
.vpm-save:hover{background:#2563eb}
body.light .vpm-box{background:#fff;border-color:#e5e7eb}
body.light .vpm-head,body.light .vpm-foot{border-color:#e5e7eb}
body.light .vpm-kind-btn{background:#f9fafb;border-color:#e5e7eb;color:#666}
body.light .vpm-form input,body.light .vpm-form select{background:#fff;border-color:#e5e7eb;color:#111}
body.light .vpm-cancel{color:#666;border-color:#e5e7eb}
</style>
<script>
var _vpmCurrentUid = null;
var _vpmCurrentKind = '';
function vaPayOpen(uid, username){
  _vpmCurrentUid = uid;
  document.getElementById('vpm-subtitle').textContent = '@' + username;
  // Populate taptap networks
  var tt = document.getElementById('vpm-taptap-network');
  tt.innerHTML = '<option value="">—</option>';
  (window.__vaPayTaptap || []).forEach(function(n){
    var o = document.createElement('option'); o.value = n; o.textContent = n; tt.appendChild(o);
  });
  // Charger les données existantes
  var data = (window.__vaPayData || {})[uid] || {};
  var kind = data.kind || 'crypto';
  vaPaySetKind(kind);
  if(kind === 'crypto'){
    document.getElementById('vpm-crypto-type').value = data.crypto_type || '';
    vaPayUpdateCryptoNetworks();
    document.getElementById('vpm-crypto-network').value = data.crypto_network || '';
    document.getElementById('vpm-crypto-address').value = data.crypto_address || '';
  } else {
    document.getElementById('vpm-taptap-number').value = data.taptap_number || '';
    document.getElementById('vpm-taptap-network').value = data.taptap_network || '';
  }
  document.getElementById('va-pay-modal').classList.add('show');
}
function vaPaySetKind(kind){
  _vpmCurrentKind = kind;
  document.querySelectorAll('.vpm-kind-btn').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-kind') === kind);
  });
  document.getElementById('vpm-form-crypto').style.display = (kind === 'crypto' ? '' : 'none');
  document.getElementById('vpm-form-taptap').style.display = (kind === 'taptap' ? '' : 'none');
}
function vaPayUpdateCryptoNetworks(){
  var t = document.getElementById('vpm-crypto-type').value;
  var sel = document.getElementById('vpm-crypto-network');
  sel.innerHTML = '';
  if(!t){
    sel.innerHTML = '<option value="">Choisis d\\'abord le type</option>'; return;
  }
  var nets = (window.__vaPayCryptoNetworks || {})[t] || [];
  nets.forEach(function(n){
    var o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o);
  });
}
function vaPayClose(e){
  if(e && e.target && e.target.id !== 'va-pay-modal' && e.target !== this) return;
  document.getElementById('va-pay-modal').classList.remove('show');
}
function vaPayClear(){
  var form = new FormData();
  form.append('user_id', _vpmCurrentUid);
  form.append('kind', '');
  fetch('/va/set_payment', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Paiement effacé', 'success');
        setTimeout(function(){ window.location.reload(); }, 300);
      }
    });
}
function vaPaySave(){
  var form = new FormData();
  form.append('user_id', _vpmCurrentUid);
  form.append('kind', _vpmCurrentKind);
  if(_vpmCurrentKind === 'crypto'){
    form.append('crypto_type', document.getElementById('vpm-crypto-type').value);
    form.append('crypto_network', document.getElementById('vpm-crypto-network').value);
    form.append('crypto_address', document.getElementById('vpm-crypto-address').value);
  } else {
    form.append('taptap_number', document.getElementById('vpm-taptap-number').value);
    form.append('taptap_network', document.getElementById('vpm-taptap-network').value);
  }
  fetch('/va/set_payment', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Paiement enregistré', 'success');
        setTimeout(function(){ window.location.reload(); }, 300);
      }
    });
}
</script>
"""

    # ====== Modal d'attribution de liens GMS (récupération de la liste à l'ouverture) ======
    all_va_links = _load_va_links()
    import json as _json_va
    va_links_json = _json_va.dumps(all_va_links, ensure_ascii=False)

    # Récupérer la liste de tous les liens GMS (par modèle)
    grouped_for_modal = {}
    try:
        import gms
        if gms.is_configured():
            grouped_for_modal = gms.get_links_grouped_by_model() or {}
    except Exception:
        pass

    # Construire un dict {link_id: {shortcode, display_name, model, url}}
    all_links_info = []
    try:
        import gms
        if gms.is_configured():
            res_all = gms.list_all_links()
            if res_all.get("ok"):
                for link in res_all["links"]:
                    model = gms.categorize_link(link)
                    all_links_info.append({
                        "id": link.get("id"),
                        "shortcode": link.get("shortcode", ""),
                        "name": link.get("display_name") or "—",
                        "model": model,
                        "url": link.get("url") or "(landing)",
                        "status": link.get("status", "active"),
                    })
            all_links_info.sort(key=lambda l: (l["model"], l["name"]))
    except Exception:
        pass

    links_json = _json_va.dumps(all_links_info, ensure_ascii=False)

    modal_html = (
        "<div id='va-links-modal' onclick='vaLinksClose(event)'>"
        "<div class='vlm-box' onclick='event.stopPropagation()'>"
        "<div class='vlm-head'>"
        "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#a855f7' stroke-width='2'><path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71'/><path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'/></svg>"
        "<div>Attribuer des liens GMS</div>"
        "<div id='vlm-subtitle'></div>"
        "<button onclick='vaLinksClose()' class='vlm-close'>×</button>"
        "</div>"
        "<input type='text' id='vlm-search' placeholder='Rechercher un lien…' oninput='vaLinksFilter(this.value)'>"
        "<div id='vlm-list'></div>"
        "<div class='vlm-foot'>"
        "<button onclick='vaLinksClose()' class='vlm-cancel'>Annuler</button>"
        "<button onclick='vaLinksSave()' class='vlm-save'>Enregistrer</button>"
        "</div>"
        "</div>"
        "</div>"
        + f"<script>window.__vaLinksData={va_links_json};window.__gmsAllLinks={links_json};</script>"
    )

    css_modal = """
<style>
#va-links-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);backdrop-filter:blur(6px);z-index:9999;align-items:center;justify-content:center;padding:30px}
#va-links-modal.show{display:flex}
.vlm-box{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;width:100%;max-width:560px;max-height:84vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.6)}
.vlm-head{padding:18px 22px;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px}
.vlm-head > div:first-of-type{flex:1}
#vlm-subtitle{font-size:11px;color:#888;font-weight:400}
.vlm-close{background:transparent;border:0;color:#888;font-size:22px;cursor:pointer;padding:0 6px;line-height:1}
.vlm-close:hover{color:#fff}
#vlm-search{margin:14px 18px;padding:9px 14px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:8px;font-size:13px;width:calc(100% - 36px)}
#vlm-search:focus{border-color:#a855f7;outline:none}
#vlm-list{flex:1;overflow-y:auto;padding:6px 14px 14px}
.vlm-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;cursor:pointer;transition:background .12s;border:1px solid transparent}
.vlm-item:hover{background:rgba(255,255,255,.04)}
.vlm-item.checked{background:rgba(168,85,247,.1);border-color:rgba(168,85,247,.3)}
.vlm-cb{width:16px;height:16px;border-radius:4px;border:1.5px solid #444;background:transparent;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.vlm-item.checked .vlm-cb{background:#a855f7;border-color:#a855f7}
.vlm-item.checked .vlm-cb svg{display:block}
.vlm-cb svg{display:none;width:12px;height:12px}
.vlm-info{flex:1;min-width:0}
.vlm-name{font-weight:600;font-size:13px;letter-spacing:-.01em}
.vlm-meta{font-size:11px;color:#888;font-family:monospace;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vlm-badge{background:rgba(168,85,247,.15);color:#a855f7;font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px}
.vlm-foot{padding:14px 18px;border-top:1px solid #2a2a2a;display:flex;gap:10px;justify-content:flex-end}
.vlm-cancel{background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:9px 16px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;font-family:inherit}
.vlm-save{background:#a855f7;color:#fff;border:0;padding:9px 18px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;font-family:inherit}
.vlm-save:hover{background:#9333ea}
body.light .vlm-box{background:#fff;border-color:#e5e7eb}
body.light .vlm-head,body.light .vlm-foot{border-color:#e5e7eb}
body.light #vlm-search{background:#f9fafb;border-color:#e5e7eb;color:#111}
body.light .vlm-item:hover{background:#f3f4f6}
body.light .vlm-cancel{color:#666;border-color:#e5e7eb}
</style>
<script>
var _vlmCurrentUid = null;
function vaLinksOpen(uid, username){
  _vlmCurrentUid = uid;
  document.getElementById('vlm-subtitle').textContent = '@' + username;
  document.getElementById('vlm-search').value = '';
  var current = (window.__vaLinksData || {})[uid] || [];
  // Construire la liste
  var listEl = document.getElementById('vlm-list');
  var html = '';
  var groupedByModel = {};
  (window.__gmsAllLinks || []).forEach(function(l){
    (groupedByModel[l.model] = groupedByModel[l.model] || []).push(l);
  });
  Object.keys(groupedByModel).sort().forEach(function(model){
    html += '<div style="font-size:10px;color:#888;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin:14px 8px 6px">' + model + '</div>';
    groupedByModel[model].forEach(function(l){
      var checked = current.indexOf(l.id) !== -1;
      html += '<div class="vlm-item ' + (checked ? 'checked' : '') + '" data-link-id="' + l.id + '" data-search="' + (l.name + ' ' + l.shortcode + ' ' + l.model).toLowerCase() + '" onclick="vaLinksToggle(this)">'
        + '<div class="vlm-cb"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>'
        + '<div class="vlm-info">'
        + '<div class="vlm-name">' + l.name + '</div>'
        + '<div class="vlm-meta">/' + l.shortcode + '</div>'
        + '</div>'
        + '</div>';
    });
  });
  listEl.innerHTML = html || '<p style="color:#888;text-align:center;padding:30px">Aucun lien GMS disponible.</p>';
  document.getElementById('va-links-modal').classList.add('show');
}
function vaLinksToggle(el){
  el.classList.toggle('checked');
}
function vaLinksFilter(q){
  q = (q||'').toLowerCase().trim();
  document.querySelectorAll('.vlm-item').forEach(function(el){
    var s = el.getAttribute('data-search') || '';
    el.style.display = (!q || s.indexOf(q) !== -1) ? '' : 'none';
  });
}
function vaLinksClose(e){
  if(e && e.target && e.target.id !== 'va-links-modal' && e.target !== this) return;
  document.getElementById('va-links-modal').classList.remove('show');
}
function vaLinksSave(){
  var selected = [];
  document.querySelectorAll('.vlm-item.checked').forEach(function(el){
    var id = el.getAttribute('data-link-id');
    if(id) selected.push(id);
  });
  var form = new FormData();
  form.append('user_id', _vlmCurrentUid);
  selected.forEach(function(id){ form.append('link_ids', id); });
  fetch('/va/set_links', {method:'POST', body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Liens mis à jour', 'success');
        // Reload pour rafraîchir le mini-stat
        setTimeout(function(){ window.location.reload(); }, 300);
      } else {
        if(typeof showToast === 'function') showToast('Erreur : ' + (d.error || '?'), 'error');
      }
    });
}
</script>
"""

    vault_search_js = (
        "<script>"
        "var _firstVaUid = " + _json_pay.dumps(first_uid) + ";"
        + """
function vaSearch(q){
  if(q === null) q = document.getElementById('va-search').value;
  q = (q || '').toLowerCase().trim();
  var identFilter = (document.getElementById('va-filter-identity').value || '').toLowerCase().trim();
  // Sidebar items
  document.querySelectorAll('.va-vlist-section').forEach(function(sec){
    var secIdent = (sec.getAttribute('data-vlist-identity') || '').toLowerCase();
    if(identFilter && secIdent !== identFilter){
      sec.style.display = 'none';
      return;
    }
    var anyVisible = false;
    sec.querySelectorAll('.va-vlist-item').forEach(function(item){
      var blob = (item.getAttribute('data-vlist-search') || '').toLowerCase();
      var match = !q || blob.indexOf(q) !== -1;
      item.style.display = match ? '' : 'none';
      if(match) anyVisible = true;
    });
    sec.style.display = anyVisible ? '' : 'none';
  });
  // Si le dropdown a une identité sélectionnée → afficher tous ses VAs en détail
  if(identFilter) vaShowIdentity(identFilter);
  else if(!q) vaShowAll();
}
function vaSelectVa(uid){
  // Désélectionner les sections highlight
  document.querySelectorAll('.va-vlist-section').forEach(function(sec){
    sec.classList.remove('va-vlist-section-active');
  });
  // Highlight sidebar item
  document.querySelectorAll('.va-vlist-item').forEach(function(it){
    it.classList.toggle('va-vlist-selected', it.getAttribute('data-vlist-uid') === uid);
  });
  // Show only the selected VA card, hide others
  document.querySelectorAll('.va-card').forEach(function(card){
    card.style.display = card.getAttribute('data-va-uid') === uid ? '' : 'none';
  });
  document.querySelectorAll('.va-section').forEach(function(sec){
    var hasVisible = sec.querySelector('.va-card:not([style*="display: none"])');
    sec.style.display = hasVisible ? '' : 'none';
  });
  var detail = document.querySelector('.va-vault-detail');
  if(detail) detail.scrollTop = 0;
}
function vaShowIdentity(identity){
  identity = (identity || '').toLowerCase();
  // Désélectionner les items individuels
  document.querySelectorAll('.va-vlist-item').forEach(function(it){
    it.classList.remove('va-vlist-selected');
  });
  // Highlight la section entière dans la sidebar
  document.querySelectorAll('.va-vlist-section').forEach(function(sec){
    var secId = (sec.getAttribute('data-vlist-identity') || '').toLowerCase();
    sec.classList.toggle('va-vlist-section-active', secId === identity);
  });
  // Afficher TOUS les VAs de cette identité dans le panel détail
  document.querySelectorAll('.va-card').forEach(function(card){
    var cardId = (card.getAttribute('data-va-identity') || '').toLowerCase();
    card.style.display = cardId === identity ? '' : 'none';
  });
  // Afficher uniquement la section qui correspond
  document.querySelectorAll('.va-section').forEach(function(sec){
    var secId = (sec.getAttribute('data-va-section-identity') || '').toLowerCase();
    sec.style.display = secId === identity ? '' : 'none';
  });
  var detail = document.querySelector('.va-vault-detail');
  if(detail) detail.scrollTop = 0;
}
function vaShowAll(){
  document.querySelectorAll('.va-vlist-item').forEach(function(it){
    it.classList.remove('va-vlist-selected');
  });
  document.querySelectorAll('.va-vlist-section').forEach(function(sec){
    sec.classList.remove('va-vlist-section-active');
  });
  document.querySelectorAll('.va-card').forEach(function(card){ card.style.display = ''; });
  document.querySelectorAll('.va-section').forEach(function(sec){ sec.style.display = ''; });
}
// Toggle collapse d'une section (chevron)
function vaToggleSection(btn){
  event.stopPropagation();
  var sec = btn.closest('.va-vlist-section');
  if(!sec) return;
  sec.classList.toggle('collapsed');
  // Persist dans localStorage
  try{
    var ident = sec.getAttribute('data-vlist-identity') || '';
    var collapsed = JSON.parse(localStorage.getItem('vabot_va_collapsed') || '[]');
    if(sec.classList.contains('collapsed')){
      if(collapsed.indexOf(ident) === -1) collapsed.push(ident);
    } else {
      collapsed = collapsed.filter(function(i){ return i !== ident; });
    }
    localStorage.setItem('vabot_va_collapsed', JSON.stringify(collapsed));
  }catch(e){}
}
// Auto-select le premier VA au chargement + restaurer collapsed
document.addEventListener('DOMContentLoaded', function(){
  if(_firstVaUid) vaSelectVa(_firstVaUid);
  // Restaurer l'état collapsed depuis localStorage
  try{
    var collapsed = JSON.parse(localStorage.getItem('vabot_va_collapsed') || '[]');
    collapsed.forEach(function(ident){
      document.querySelectorAll('.va-vlist-section').forEach(function(sec){
        if(sec.getAttribute('data-vlist-identity') === ident){
          sec.classList.add('collapsed');
        }
      });
    });
  }catch(e){}
});
</script>
"""
    )
    detail_content = "".join(sections) + footer
    return (
        css + css_modal + pay_css_js + insta_css_js
        + "<div class='va-vault-layout'>"
        + vault_sidebar
        + "<div class='va-vault-detail'>" + detail_content + "</div>"
        + "</div>"
        + modal_html + pay_modal_html + insta_modal_html
        + vault_search_js
    )


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


def _preview_card(media_url: str, thumb_url: str, file_path, is_video: bool, file_id: str = "", example_url: str = "", deferred: bool = False) -> str:
    """Carte preview style propre : juste un badge date en haut à gauche + thumbnail
    en grand. Plus de nom de fichier ni de taille en dessous (visible au hover via title).

    Si deferred=True, l img a data-src (pas src) et l IntersectionObserver
    se charge de la swap au moment ou la card devient visible.
    """
    name = file_path.name
    # Date upload courte format français (ex. "27 mai")
    try:
        import datetime as _dt_pc
        mtime = file_path.stat().st_mtime
        d = _dt_pc.date.fromtimestamp(mtime)
        fr_months = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                     "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        date_short = f"{d.day} {fr_months[d.month - 1]}"
    except Exception:
        date_short = ""

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

    # Badge date en haut à GAUCHE — fond blanc frosted, texte foncé (lisible partout)
    date_badge = ""
    if date_short:
        date_badge = (
            f"<div class='card-date-badge' style='position:absolute;top:8px;left:8px;"
            f"background:rgba(255,255,255,.92);color:#1a1a1a;font-size:11px;font-weight:700;"
            f"padding:4px 10px;border-radius:6px;backdrop-filter:blur(8px);"
            f"letter-spacing:.01em;pointer-events:none;z-index:4;"
            f"box-shadow:0 2px 8px rgba(0,0,0,.2),0 0 0 1px rgba(255,255,255,.4) inset'>{date_short}</div>"
        )

    is_video_js = "true" if is_video else "false"
    fid_safe = file_id.replace("'", "\\'") if file_id else ""
    example_safe = example_url.replace("'", "\\'") if example_url else ""
    # Skeleton placeholder + lazy image fade-in
    if deferred:
        img_tag = (
            f"<img data-src='{thumb_url}' class='vault-defer-img vault-img-load' loading='lazy' "
            f"src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiPjwvc3ZnPg==' "
            f"style='width:100%;height:100%;object-fit:cover;display:block;opacity:0;transition:opacity .25s'>"
        )
    else:
        img_tag = (
            f"<img src='{thumb_url}' loading='lazy' class='vault-img-load' onload='this.style.opacity=1' "
            f"style='width:100%;height:100%;object-fit:cover;display:block;opacity:0;transition:opacity .25s'>"
        )
    media_html = (
        f"<div onclick='openLightbox(\"{media_url}\",{is_video_js},\"{name}\",\"{fid_safe}\",\"{example_safe}\")' "
        f"title='{name}' class='vault-card-bg' "
        f"style='cursor:pointer;position:relative;width:100%;aspect-ratio:1;border-radius:10px;overflow:hidden'>"
        f"{img_tag}"
        f"{play_badge}"
        f"{date_badge}"
        f"</div>"
    )

    # Crayon (Edit) UNIQUEMENT pour les Reels (file_id contient |videos|).
    # Posts / Stories / Story CTA / PPs n'ont pas de caption/description à éditer.
    show_edit = "|videos|" in (file_id or "")
    actions_html = ""
    if file_id:
        edit_btn = ""
        if show_edit:
            edit_btn = (
                f"<button class='card-edit-btn' onclick='event.stopPropagation();openCaptionEditor(\"{fid_safe}\")' "
                f"title='Modifier caption / description'>"
                f"<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='2.2'><path d='M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7'/><path d='M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z'/></svg>"
                f"</button>"
            )
        actions_html = (
            f"<div class='card-actions' style='position:absolute;top:8px;right:8px;display:flex;gap:6px;align-items:center;z-index:5'>"
            f"{edit_btn}"
            f"<label class='sel-circle-wrap' onclick='event.stopPropagation()' style='cursor:pointer;display:block'>"
            f"<input type='checkbox' class='sel-cb' "
            f"onchange='toggleSelect(\"{file_id}\", this.checked)' "
            f"style='position:absolute;opacity:0;pointer-events:none'>"
            f"<span class='sel-circle'></span>"
            f"</label>"
            f"</div>"
        )

    return (
        f"<div class='cloud-card' style='background:transparent;border:0;border-radius:10px;position:relative'>"
        f"{actions_html}"
        f"{media_html}"
        f"</div>"
    )


def _render_cloud_content_html(subdir: str, exts) -> str:
    """Vue "Vault" style Infloww : sidebar à gauche avec liste des identités
    (avatars + counts + search), galerie à droite pour l'identité sélectionnée.
    Pas de navigation back/forward, tout dans la même page.
    """
    from flask import request as _req
    identities = _list_identities()
    if not identities:
        return "<p style='color:#888'>Aucune identité créée.</p>"
    is_video = subdir == "videos"

    # Calculer stats par identité (counts + size)
    ident_stats = {}
    for ident in identities:
        folder = IDENTITIES_DIR / ident / subdir
        n_files = 0
        n_videos = 0
        n_images = 0
        size_mb = 0.0
        if folder.exists():
            for p in folder.iterdir():
                if not p.is_file():
                    continue
                if p.suffix.lower() not in exts or ".example" in p.name:
                    continue
                n_files += 1
                if p.suffix.lower() in VIDEO_EXTS:
                    n_videos += 1
                else:
                    n_images += 1
                try:
                    size_mb += p.stat().st_size / (1024 * 1024)
                except Exception:
                    pass
        ident_stats[ident] = {
            "n_files": n_files, "n_videos": n_videos,
            "n_images": n_images, "size_mb": size_mb,
        }

    # Identité sélectionnée (par défaut : la première qui a des fichiers, sinon la 1re)
    selected = ""
    try:
        selected = (_req.args.get(f"cloud_{subdir}_ident", "") or "").lower().strip()
    except Exception:
        pass
    if not selected or selected not in identities:
        # Auto-select : la 1re identité avec des fichiers
        for ident in identities:
            if ident_stats[ident]["n_files"] > 0:
                selected = ident
                break
        if not selected:
            selected = identities[0]

    tab_name = {"videos": "cloudreels", "posts": "cloudposts",
                "stories": "cloudstories", "storyctas": "cloudstoryctas"}.get(subdir, "cloudoverview")
    subdir_key = f"cloud_{subdir}_ident"

    # ============ Sidebar Vault (gauche) ============
    vault_items = []
    for ident in identities:
        stats = ident_stats[ident]
        avatar_url = _identity_avatar_url(ident)
        avatar_html = (
            f"<img src='{avatar_url}' style='width:42px;height:42px;border-radius:50%;object-fit:cover;flex-shrink:0'>"
            if avatar_url else
            f"<div style='width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:16px;flex-shrink:0'>{ident[:1].upper()}</div>"
        )
        # Dot statut (en ligne) à droite de l'avatar
        status_dot = "<div style='position:absolute;bottom:0;right:0;width:12px;height:12px;background:#22c55e;border:2px solid #0a0a0a;border-radius:50%'></div>"
        # Badge count (à droite du nom)
        count_badge = ""
        if stats["n_files"] > 0:
            count_badge = (
                f"<span class='vault-count' style='background:rgba(251,113,133,.15);color:#fb7185;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;display:inline-flex;align-items:center;gap:3px'>"
                f"<svg viewBox='0 0 24 24' width='10' height='10' fill='currentColor'><path d='M12 2C6.48 2 2 5.94 2 10.8c0 2.43 1.09 4.64 2.85 6.21L4 22l4.8-2.4c.96.25 1.96.4 3 .4c5.52 0 10-3.94 10-8.8S17.52 2 12 2z'/></svg>"
                f"{stats['n_files']}</span>"
            )
        active_class = "vault-item-active" if ident == selected else ""
        vault_items.append(
            f"<a href='?tab={tab_name}&{subdir_key}={ident}' "
            f"onclick='return vaultGoTo(event,this.href)' "
            f"onmouseenter='vaultPrefetch(this.href)' "
            f"data-no-loader='1' class='vault-item {active_class}' data-ident='{ident}'>"
            f"<div style='position:relative;display:inline-block'>{avatar_html}{status_dot}</div>"
            f"<div style='flex:1;min-width:0'>"
            f"<div style='font-weight:700;font-size:14px;letter-spacing:-.01em'>{ident.title()}</div>"
            f"<div style='font-size:11px;color:#888;margin-top:2px'>{stats['n_files']} fichier{'s' if stats['n_files'] != 1 else ''}</div>"
            f"</div>"
            f"{count_badge}"
            f"</a>"
        )

    vault_sidebar = (
        "<div class='vault-sidebar'>"
        f"<div class='vault-search'>"
        f"<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2.5' style='color:#666'><circle cx='11' cy='11' r='8'/><path d='m21 21-4.35-4.35'/></svg>"
        f"<input type='text' placeholder='Rechercher…' oninput='vaultFilter(this.value)' id='vault-search-{subdir}'>"
        f"</div>"
        f"<div class='vault-filter-row'>"
        f"<div style='color:#3b82f6;font-weight:600;font-size:13px;letter-spacing:-.01em;display:flex;align-items:center;gap:6px'>Toutes les identités"
        f"<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2.5'><polyline points='6 9 12 15 18 9'/></svg>"
        f"</div>"
        f"</div>"
        f"<div class='vault-list' id='vault-list-{subdir}'>"
        + "".join(vault_items)
        + "</div>"
        "</div>"
    )

    # ============ Galerie (droite) ============
    sel_stats = ident_stats.get(selected, {"n_files": 0, "size_mb": 0})
    sel_avatar_url = _identity_avatar_url(selected)
    sel_avatar_html = (
        f"<img src='{sel_avatar_url}' style='width:42px;height:42px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a'>"
        if sel_avatar_url else
        f"<div style='width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:16px'>{selected[:1].upper()}</div>"
    )

    # Récupérer les options de tri/filtre depuis l'URL
    sort_mode = ""
    filter_date = ""
    type_filter = "all"
    try:
        sort_mode = (_req.args.get(f"cloud_{subdir}_sort", "recent") or "recent").lower().strip()
        filter_date = (_req.args.get(f"cloud_{subdir}_date", "") or "").strip()
        type_filter = (_req.args.get(f"cloud_{subdir}_type", "all") or "all").lower().strip()
    except Exception:
        sort_mode = "recent"

    folder = IDENTITIES_DIR / selected / subdir
    files = []
    if folder.exists():
        files = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in exts and ".example" not in p.name
        ]

    # Filtre type (photo/vidéo) — appliqué après chargement, avant tri
    if type_filter == "photo":
        files = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    elif type_filter == "video":
        files = [p for p in files if p.suffix.lower() in VIDEO_EXTS]

    # Filtre "Aller à la date" : ne garder que les fichiers de cette date
    if filter_date:
        try:
            import datetime as _dt_fc
            target = _dt_fc.date.fromisoformat(filter_date)
            files = [
                p for p in files
                if _dt_fc.date.fromtimestamp(p.stat().st_mtime) == target
            ]
        except Exception:
            pass

    # Tri
    if sort_mode == "asc":
        files.sort(key=lambda p: p.stat().st_mtime)  # plus ancien d'abord
    elif sort_mode == "desc" or sort_mode == "recent":
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)  # plus récent d'abord
    else:  # "all" ou inconnu : tri alphabétique
        files.sort(key=lambda p: p.name.lower())

    # Construire les URLs de tri (préservant la sélection d'identité courante)
    def _sort_url(value):
        params = [f"tab={tab_name}", f"{subdir_key}={selected}"]
        if value != "recent":
            params.append(f"cloud_{subdir}_sort={value}")
        return "?" + "&".join(params)

    # Compteur fichiers affichés (après filtre)
    n_shown = len(files)
    filter_label = ""
    if filter_date:
        filter_label = f" · filtré au {filter_date}"

    sort_btn_html = (
        "<div class='vault-sort'>"
        "<button type='button' class='vault-sort-btn' onclick='vaultSortToggle(event,this)'>"
        "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2'><line x1='4' y1='6' x2='20' y2='6'/><line x1='8' y1='12' x2='16' y2='12'/><line x1='10' y1='18' x2='14' y2='18'/></svg>"
        f"<span>{('Tout' if sort_mode == 'all' else 'Récemment' if sort_mode == 'recent' else 'Croissant' if sort_mode == 'asc' else 'Décroissant' if sort_mode == 'desc' else 'Trier')}</span>"
        "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2.5'><polyline points='6 9 12 15 18 9'/></svg>"
        "</button>"
        "<div class='vault-sort-menu' onclick='event.stopPropagation()'>"
        f"<a href='{_sort_url('all')}' data-no-loader='1' class='vault-sort-item {('vault-sort-active' if sort_mode == 'all' else '')}'>"
        "<span class='vault-radio'></span>Tout</a>"
        f"<form method='GET' class='vault-sort-form'>"
        f"<input type='hidden' name='tab' value='{tab_name}'>"
        f"<input type='hidden' name='{subdir_key}' value='{selected}'>"
        "<label class='vault-sort-item' style='cursor:default'>"
        "<span class='vault-radio'></span>Aller à la date :</label>"
        f"<input type='date' name='cloud_{subdir}_date' value='{filter_date}' onchange='this.form.submit()' "
        "style='margin:6px 36px 8px;padding:5px 8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;font-size:12px;width:calc(100% - 72px)'>"
        "</form>"
        "<div class='vault-sort-sep'></div>"
        f"<a href='{_sort_url('recent')}' data-no-loader='1' class='vault-sort-item {('vault-sort-active' if sort_mode == 'recent' else '')}'>"
        "<span class='vault-radio'></span>Récemment</a>"
        "<div class='vault-sort-sep'></div>"
        f"<a href='{_sort_url('asc')}' data-no-loader='1' class='vault-sort-item {('vault-sort-active' if sort_mode == 'asc' else '')}'>"
        "<span class='vault-radio'></span>Croissant</a>"
        f"<a href='{_sort_url('desc')}' data-no-loader='1' class='vault-sort-item {('vault-sort-active' if sort_mode == 'desc' else '')}'>"
        "<span class='vault-radio'></span>Décroissant</a>"
        "</div>"
        "</div>"
    )

    # Filtre type (Tout / Photo / Vidéo) — uniquement pour les pages qui mixent vraiment.
    # Reels = vidéos only, Posts = photos only → pas de filtre.
    # Stories + Story CTA → peuvent contenir les deux, on affiche le filtre.
    type_filter_html = ""
    if subdir in ("stories", "storyctas"):
        def _type_url(value):
            params = [f"tab={tab_name}", f"{subdir_key}={selected}"]
            if sort_mode and sort_mode != "recent":
                params.append(f"cloud_{subdir}_sort={sort_mode}")
            if filter_date:
                params.append(f"cloud_{subdir}_date={filter_date}")
            if value != "all":
                params.append(f"cloud_{subdir}_type={value}")
            return "?" + "&".join(params)

        type_filter_html = (
            "<div class='media-type-pills'>"
            + f"<a href='{_type_url('all')}' data-no-loader='1' class='media-pill {('media-pill-active' if type_filter == 'all' else '')}'>Tout</a>"
            + f"<a href='{_type_url('photo')}' data-no-loader='1' class='media-pill {('media-pill-active' if type_filter == 'photo' else '')}'>Photo</a>"
            + f"<a href='{_type_url('video')}' data-no-loader='1' class='media-pill {('media-pill-active' if type_filter == 'video' else '')}'>Vidéo</a>"
            + "</div>"
        )

    # Mapping subdir -> upload tab name (pour le bouton + Add media)
    upload_tab_map = {
        "videos": ("reel", "Upload Reel", "Vidéo clean + caption + description"),
        "posts": ("post", "Upload Post", "Photo simple pour le feed"),
        "stories": ("story", "Upload Story", "Photo simple pour story"),
        "storyctas": ("storycta", "Story CTA", "Photo 1080x1920 pour CTA + lien"),
    }
    add_media_btn = ""
    if subdir in upload_tab_map:
        utab, utitle, usub = upload_tab_map[subdir]
        # On cache la card identite + on l auto-remplit + on affiche un badge "Pour @<identity>"
        add_media_btn = (
            f"<button type='button' onclick=\"showTab('upload','{utab}','{utitle}','{usub}');"
            f"upPrefillIdentity('{utab}', '{selected}');\" "
            f"style='display:inline-flex;align-items:center;gap:8px;padding:9px 18px;"
            f"background:linear-gradient(135deg,#3b82f6,#a855f7);border:0;color:#fff;"
            f"border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;"
            f"box-shadow:0 4px 12px rgba(59,130,246,.25);letter-spacing:.01em'>"
            f"<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>"
            f"Add media</button>"
        )

    gallery_header = (
        # === Row 1 : identite a gauche + Add media a droite ===
        f"<div class='vault-gallery-header' style='justify-content:space-between'>"
        f"<div style='display:flex;align-items:center;gap:12px;flex:1;min-width:0'>"
        f"{sel_avatar_html}"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='font-weight:700;font-size:18px;letter-spacing:-.01em'>@{selected}</div>"
        f"<div style='font-size:12px;color:#888;margin-top:2px'>{n_shown} fichier{'s' if n_shown != 1 else ''} · {sel_stats['size_mb']:.1f} MB{filter_label}</div>"
        f"</div></div>"
        f"<div style='display:flex;align-items:center;gap:10px;flex-shrink:0'>"
        f"{add_media_btn}"
        f"</div>"
        f"</div>"
        # === Row 2 : tri + filtres ===
        f"<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px;padding:10px 0 0;border-top:1px solid #232323'>"
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
        + type_filter_html.replace("<div class='media-type-pills'>", "<div class='media-type-pills' style='margin:0'>")
        + f"</div>"
        f"<div>{sort_btn_html}</div>"
        f"</div>"
    )

    if not files:
        gallery = (
            gallery_header +
            "<div style='padding:60px 20px;text-align:center;color:#666'>"
            "<svg viewBox='0 0 24 24' width='44' height='44' fill='none' stroke='currentColor' stroke-width='1.5' style='margin-bottom:12px;opacity:.4'><path d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/></svg>"
            f"<p style='margin:0;font-size:13px'>Aucun fichier pour @{selected}</p>"
            "</div>"
        )
    else:
        # === PAGINATION : ne render que les N premiers, le reste = lazy via Intersection Observer ===
        INITIAL_BATCH = 24  # cards visibles direct (rapide a charger)
        cards_html = []
        # Pré-indexer les fichiers exemple par stem (pour swap clean -> example)
        example_by_stem = {}
        if folder.exists():
            for pe in folder.iterdir():
                if pe.is_file() and ".example" in pe.name:
                    base_stem = pe.stem.replace(".example", "")
                    example_by_stem[base_stem] = pe.name

        total_files = len(files)
        for idx, p in enumerate(files):
            file_id = f"{selected}|{subdir}|{p.name}"
            clean_url = f"/cloud/file/{selected}/{subdir}/{p.name}"
            ex_name = example_by_stem.get(p.stem)
            if ex_name:
                url = f"/cloud/file/{selected}/{subdir}/{ex_name}"
                thumb_url = f"/cloud/thumb/{selected}/{subdir}/{ex_name}"
                second_url = clean_url
            else:
                url = clean_url
                thumb_url = f"/cloud/thumb/{selected}/{subdir}/{p.name}"
                second_url = ""
            # Apres INITIAL_BATCH : on render avec data-src vide, l image se charge a l intersection
            deferred = idx >= INITIAL_BATCH
            cards_html.append(_preview_card(url, thumb_url, p, is_video, file_id, second_url, deferred=deferred))
        gallery = (
            gallery_header
            + "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px' id='vault-grid'>"
            + "".join(cards_html)
            + "</div>"
        )
        # Compteur en bas + auto-scroll trigger
        if total_files > INITIAL_BATCH:
            gallery += (
                f"<div id='vault-load-status' style='text-align:center;padding:14px;color:#666;font-size:12px;margin-top:10px'>"
                f"{INITIAL_BATCH} / {total_files} affiches — scroll pour charger plus"
                f"</div>"
            )

    css = """
<style>
.vault-layout{display:grid;grid-template-columns:280px 1fr;gap:18px;align-items:start}
@media(max-width:900px){.vault-layout{grid-template-columns:1fr}}
.vault-sidebar{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px;max-height:calc(100vh - 160px);overflow:hidden}
.vault-search{display:flex;align-items:center;gap:8px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px 12px}
.vault-search input{flex:1;background:transparent;border:0;color:#fff;outline:none;font-size:13px;font-family:inherit;padding:0;margin:0;width:100%}
.vault-filter-row{padding:4px 6px;cursor:pointer}
.vault-list{display:flex;flex-direction:column;gap:4px;overflow-y:auto;flex:1;margin:0 -6px;padding:0 6px}
.vault-item{display:flex;align-items:center;gap:12px;padding:10px 12px;background:transparent;border:1px solid transparent;border-radius:10px;text-decoration:none;color:inherit;transition:all .15s}
.vault-item:hover{background:rgba(255,255,255,.04)}
.vault-item-active{background:linear-gradient(90deg,rgba(59,130,246,.18),rgba(168,85,247,.08)) !important;border-color:rgba(59,130,246,.4) !important}
.vault-gallery{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:20px}
.vault-gallery-header{display:flex;align-items:center;gap:12px;margin-bottom:14px;padding-bottom:16px;border-bottom:1px solid #2a2a2a}
/* === Pills filtre Photo/Vidéo === */
.media-type-pills{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}
.media-pill{padding:7px 18px;background:transparent;border:1px solid #2a2a2a;color:#aaa;border-radius:18px;font-size:13px;font-weight:600;text-decoration:none;cursor:pointer;transition:all .15s;letter-spacing:-.01em}
.media-pill:hover{background:rgba(255,255,255,.05);color:#fff;border-color:#3a3a3a}
.media-pill-active{background:rgba(59,130,246,.15) !important;color:#3b82f6 !important;border-color:rgba(59,130,246,.4) !important}
body.light .media-pill{color:#666;border-color:#e5e7eb}
body.light .media-pill:hover{background:#f3f4f6;color:#111;border-color:#d1d5db}
body.light .media-pill-active{background:#dbeafe !important;color:#3b82f6 !important;border-color:rgba(59,130,246,.3) !important}
/* === Sort/filter dropdown === */
.vault-sort{position:relative}
.vault-sort-btn{background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:8px 14px;border-radius:9px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:8px;font-family:inherit;transition:all .15s}
.vault-sort-btn:hover{background:#252525;border-color:#3a3a3a}
.vault-sort-menu{position:absolute;top:calc(100% + 6px);right:0;min-width:240px;background:#0a0a0a;border:1px solid #2a2a2a;border-radius:12px;padding:6px;display:none;z-index:1000;box-shadow:0 12px 32px rgba(0,0,0,.5);max-height:80vh;overflow-y:auto}
.vault-sort.open .vault-sort-menu{display:block;animation:vaultMenuFade .14s ease}
@keyframes vaultMenuFade{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.vault-sort-item{display:flex;align-items:center;gap:10px;padding:10px 14px;color:#ddd;font-size:13px;font-weight:500;text-decoration:none;border-radius:8px;cursor:pointer;transition:background .12s}
.vault-sort-item:hover{background:rgba(255,255,255,.06)}
.vault-sort-active{color:#3b82f6}
.vault-sort-sep{height:1px;background:#222;margin:4px 8px}
.vault-radio{width:16px;height:16px;border-radius:50%;border:2px solid #444;flex-shrink:0;position:relative}
.vault-sort-active .vault-radio{border-color:#3b82f6}
.vault-sort-active .vault-radio::after{content:'';position:absolute;inset:2px;background:#3b82f6;border-radius:50%}
.vault-sort-form{margin:0;padding:0}
body.light .vault-sidebar{background:#fff;border-color:#e5e7eb}
body.light .vault-search{background:#f9fafb;border-color:#e5e7eb}
body.light .vault-search input{color:#111}
body.light .vault-item:hover{background:#f3f4f6}
body.light .vault-item-active{background:linear-gradient(90deg,#dbeafe,#ede9fe) !important;border-color:rgba(59,130,246,.3) !important}
body.light .vault-gallery{background:#fff;border-color:#e5e7eb}
body.light .vault-sort-btn{background:#fff;border-color:#e5e7eb;color:#111}
body.light .vault-sort-btn:hover{background:#f9fafb}
body.light .vault-sort-menu{background:#fff;border-color:#e5e7eb}
body.light .vault-sort-item{color:#111}
body.light .vault-sort-item:hover{background:#f3f4f6}
body.light .vault-sort-sep{background:#e5e7eb}

/* === UPLOAD STYLE INFLOW === */
.up-form{max-width:880px}
.up-card{position:relative;background:#161616;border:1px solid #232323;border-radius:14px;padding:22px 24px;margin-bottom:14px}
body.light .up-card{background:#fff;border-color:#e5e7eb}
.up-step{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.up-step .up-dot{width:11px;height:11px;border-radius:50%;background:#3b82f6;flex-shrink:0;box-shadow:0 0 0 4px rgba(59,130,246,.15)}
.up-step h3{margin:0;font-size:15px;font-weight:700;color:#fff;letter-spacing:-.01em}
body.light .up-step h3{color:#111}
.up-step .up-req{color:#888;font-weight:500;font-size:13px;margin-left:4px}
.up-step .up-opt{color:#666;font-weight:500;font-size:13px;margin-left:4px;font-style:italic}
.up-input{background:#0f0f0f;border:1px solid #2a2a2a;color:#fff;padding:11px 14px;border-radius:10px;font-family:inherit;font-size:14px;width:100%;outline:none;transition:.15s}
.up-input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
body.light .up-input{background:#f9fafb;border-color:#e5e7eb;color:#111}
.up-mini-label{display:block;font-size:11px;color:#888;letter-spacing:.5px;text-transform:uppercase;font-weight:700;margin-bottom:6px}
textarea.up-input{min-height:72px;resize:vertical}

/* === DROP zone === */
.up-drop{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:rgba(59,130,246,.04);border:2px dashed rgba(59,130,246,.3);border-radius:12px;padding:36px 16px;cursor:pointer;transition:.15s;position:relative}
.up-drop input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer}
.up-drop:hover{background:rgba(59,130,246,.07);border-color:rgba(59,130,246,.55)}
.up-drop.dragover{background:rgba(59,130,246,.12);border-color:#3b82f6;transform:scale(1.005)}
.up-drop.has-file{background:rgba(34,197,94,.05);border-color:rgba(34,197,94,.3);border-style:solid;padding:18px 14px}
body.light .up-drop{background:rgba(59,130,246,.05)}
.up-drop-inner{display:flex;flex-direction:column;align-items:center;gap:4px;background:#fff;border:1px dashed rgba(59,130,246,.4);border-radius:12px;padding:14px 22px;color:#3b82f6;font-weight:700;font-size:13px;letter-spacing:-.01em;pointer-events:none;box-shadow:0 4px 12px rgba(59,130,246,.08)}
.up-drop-inner-small{display:flex;align-items:center;gap:8px;background:#fff;border:1px dashed rgba(59,130,246,.4);border-radius:10px;padding:10px 16px;color:#3b82f6;font-weight:700;font-size:13px;pointer-events:none}
.up-drop-small{padding:14px 16px}
.up-plus{font-size:22px;line-height:1;color:#3b82f6}
.up-plus-lbl{font-size:13px}
.up-drop-hint{color:#666;font-size:13px;text-align:center;pointer-events:none}
.up-drop-limits{display:flex;gap:8px;color:#888;font-size:11px;flex-wrap:wrap;justify-content:center;pointer-events:none}
.up-drop-limits span{padding:0 4px}

/* === Edit table (apres drop) === */
.up-edit-table{margin-top:14px;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;overflow:hidden}
body.light .up-edit-table{background:#fff;border-color:#e5e7eb}
.up-edit-head{display:grid;grid-template-columns:1fr 60px;padding:10px 16px;background:#1a1a1a;border-bottom:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:.5px;text-transform:uppercase;font-weight:700}
body.light .up-edit-head{background:#f9fafb;border-bottom-color:#e5e7eb}
.up-edit-row{display:grid;grid-template-columns:1fr 60px;align-items:center;padding:12px 16px;border-bottom:1px solid #1a1a1a}
.up-edit-row:last-child{border-bottom:0}
.up-edit-name{font-size:13px;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.light .up-edit-name{color:#111}
.up-edit-thumb{display:inline-block;width:42px;height:42px;border-radius:8px;background:#262626;margin-right:10px;vertical-align:middle;object-fit:cover}
.up-rm{background:transparent;border:0;color:#ef4444;font-size:18px;cursor:pointer;padding:4px 8px;border-radius:6px;transition:.15s}
.up-rm:hover{background:rgba(239,68,68,.15)}

.up-submit{margin-top:6px;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;border:0;padding:14px 26px;border-radius:12px;font-weight:800;font-size:15px;cursor:pointer;box-shadow:0 6px 18px rgba(59,130,246,.3);letter-spacing:.01em;width:100%;font-family:inherit}
.up-submit:hover{transform:translateY(-1px);box-shadow:0 8px 22px rgba(59,130,246,.4)}

/* === Reel slots (multi-reel upload) === */
.reel-slot{position:relative;background:#121212;border:1px solid #232323;border-radius:14px;padding:16px;margin-bottom:14px}
body.light .reel-slot{background:#f9fafb;border-color:#e5e7eb}
.reel-slot .up-card{background:#1a1a1a;margin-bottom:10px}
body.light .reel-slot .up-card{background:#fff}
.reel-slot-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding:4px 4px 0}
.reel-slot-num{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;border-radius:10px;font-size:12px;font-weight:800;letter-spacing:.5px}
.reel-slot-remove{background:transparent;border:1px solid #333;color:#ef4444;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:18px;line-height:1;display:flex;align-items:center;justify-content:center;transition:.15s}
.reel-slot-remove:hover{background:rgba(239,68,68,.15);transform:scale(1.1)}
.up-add-slot{display:flex;align-items:center;justify-content:center;width:100%;padding:14px;background:transparent;border:2px dashed rgba(59,130,246,.4);color:#3b82f6;border-radius:12px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:.15s;margin-bottom:14px}
.up-add-slot:hover{background:rgba(59,130,246,.06);border-color:rgba(59,130,246,.7)}
.reel-slot-status{padding:8px 4px 0;font-size:12px;color:#888;text-align:center}
.reel-slot-status.ok{color:#22c55e;font-weight:700}
.reel-slot-status.err{color:#ef4444;font-weight:700}
.reel-slot-status.uploading{color:#3b82f6;font-weight:700}

/* === Skeleton placeholder (gradient gris anime) avant chargement thumb === */
.vault-card-bg{background:linear-gradient(110deg,#1a1a1a 8%,#262626 18%,#1a1a1a 33%);background-size:200% 100%;animation:vaultSkel 1.4s linear infinite}
body.light .vault-card-bg{background:linear-gradient(110deg,#eceff1 8%,#f5f5f5 18%,#eceff1 33%);background-size:200% 100%}
@keyframes vaultSkel{0%{background-position:200% 0}100%{background-position:-200% 0}}
/* L image apparait en fade quand elle a chargee */
.vault-img-load{opacity:0}
.vault-img-load.loaded{opacity:1}

/* === SFW blur mode === */
/* Tout flou par defaut quand SFW est ON */
body.sfw-on .vault-gallery img,body.sfw-on .vault-thumb img,body.sfw-on .file-thumb img,body.sfw-on .preview-card img{filter:blur(22px) saturate(.5);transition:filter .25s}
/* Pas d unblur au hover. Seul la lightbox (clic) affiche net. */
body.sfw-on #lightbox img,body.sfw-on #lightbox video,body.sfw-on .lightbox-content img,body.sfw-on .lightbox-content video{filter:none!important}

/* SFW floating toggle (style iOS, dark theme adapte) */
#sfw-floating{}
body.dark #sfw-floating,body:not(.light) #sfw-floating{background:#161616!important;border-color:#2a2a2a!important}
body.dark #sfw-floating .sfw-switch,body:not(.light) #sfw-floating .sfw-switch{background:#2a2a2a!important}
#sfw-floating:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,0,0,.15)}
/* Etat ON : orange (matche le screenshot Inflow) */
body.sfw-on #sfw-floating .sfw-switch{background:#fb923c!important;box-shadow:0 0 0 1px #fb923c,0 0 12px rgba(251,146,60,.45) inset}
body.sfw-on #sfw-floating .sfw-thumb{transform:translateX(16px)!important}
body.sfw-on #sfw-floating span:last-child{color:#fb923c!important}
@media(max-width:768px){#sfw-floating{top:12px;right:12px;padding:5px 10px 5px 6px}}
</style>
<script>
// === Upload drag&drop + preview MULTI-FILE ===
function _upHumanSize(b){
  if(b<1024) return b+' B';
  if(b<1024*1024) return (b/1024).toFixed(1)+' KB';
  if(b<1024*1024*1024) return (b/(1024*1024)).toFixed(1)+' MB';
  return (b/(1024*1024*1024)).toFixed(2)+' GB';
}
function _upRowThumb(file){
  if(file.type && file.type.startsWith('image/')){
    const url = URL.createObjectURL(file);
    return '<img class=up-edit-thumb src="'+url+'">';
  } else if(file.type && file.type.startsWith('video/')){
    return '<span class=up-edit-thumb style="display:inline-flex;align-items:center;justify-content:center;color:#aaa;font-size:18px">🎬</span>';
  }
  return '<span class=up-edit-thumb></span>';
}
function _upRefreshTable(input){
  const dropZone = input.closest('.up-drop');
  const card = dropZone.closest('.up-card');
  const table = card.querySelector('.up-edit-table');
  if(!table) return;
  const files = input.files && input.files.length ? Array.from(input.files) : [];
  // Vide la table sauf le head
  Array.from(table.querySelectorAll('.up-edit-row')).forEach(r=>r.remove());
  if(!files.length){
    table.style.display = 'none';
    dropZone.classList.remove('has-file');
    const inner = dropZone.querySelector('.up-drop-inner, .up-drop-inner-small');
    if(inner) inner.style.display = '';
    const hint = dropZone.querySelector('.up-drop-hint');
    if(hint && hint.dataset.origText){ hint.textContent = hint.dataset.origText; }
    const limits = dropZone.querySelector('.up-drop-limits');
    if(limits) limits.style.display = '';
    return;
  }
  dropZone.classList.add('has-file');
  const inner = dropZone.querySelector('.up-drop-inner, .up-drop-inner-small');
  if(inner) inner.style.display = 'none';
  const hint = dropZone.querySelector('.up-drop-hint');
  if(hint){
    if(!hint.dataset.origText) hint.dataset.origText = hint.textContent;
    hint.textContent = '✓ ' + files.length + ' fichier' + (files.length>1?'s':'') + ' prêt' + (files.length>1?'s':'') + ' — clique pour changer';
  }
  const limits = dropZone.querySelector('.up-drop-limits');
  if(limits) limits.style.display = 'none';
  table.style.display = '';
  // 1 row par file
  files.forEach((file, idx)=>{
    const row = document.createElement('div');
    row.className = 'up-edit-row';
    row.dataset.file = 'main-' + idx;
    row.innerHTML = '<div class=up-edit-name>' + _upRowThumb(file) + '<span>' + file.name + ' <span style="color:#888">· ' + _upHumanSize(file.size) + '</span></span></div><div><span class="up-progress" data-idx="' + idx + '" style="color:#666;font-size:12px;margin-right:8px"></span></div>';
    table.appendChild(row);
  });
}
function upClearMain(btn){
  const card = btn.closest('.up-card');
  const input = card.querySelector('.up-file-main, .up-file-example');
  if(input) input.value = '';
  _upRefreshTable(input);
}
document.addEventListener('change', function(e){
  const input = e.target;
  if(input.matches('.up-file-main, .up-file-example')){
    _upRefreshTable(input);
  }
});

// === REEL SLOTS : multi-reel preparation + bulk push ===
function _reelRenumberSlots(){
  const slots = document.querySelectorAll('#reel-slots-container .reel-slot');
  slots.forEach((s, i)=>{
    s.dataset.slotIdx = String(i);
    const num = s.querySelector('.reel-slot-num');
    if(num) num.textContent = '#' + (i+1);
    // Cache le bouton X si c'est le seul slot
    const rm = s.querySelector('.reel-slot-remove');
    if(rm) rm.style.visibility = slots.length === 1 ? 'hidden' : 'visible';
  });
}
function addReelSlot(){
  const tpl = document.getElementById('reel-slot-template');
  const container = document.getElementById('reel-slots-container');
  if(!tpl || !container) return;
  const clone = tpl.content.cloneNode(true);
  container.appendChild(clone);
  _reelRenumberSlots();
}
function removeReelSlot(btn){
  const slot = btn.closest('.reel-slot');
  if(slot){ slot.remove(); _reelRenumberSlots(); }
}
function initReelSlots(){
  const container = document.getElementById('reel-slots-container');
  if(!container) return;
  // Si le conteneur est vide, on ajoute le premier slot
  if(container.querySelectorAll('.reel-slot').length === 0){
    addReelSlot();
  }
  const addBtn = document.getElementById('add-reel-slot');
  if(addBtn && !addBtn.dataset.bound){
    addBtn.dataset.bound = '1';
    addBtn.addEventListener('click', addReelSlot);
  }
}
// Lance l init au load et apres chaque switch de tab
document.addEventListener('DOMContentLoaded', initReelSlots);
window.initReelSlots = initReelSlots;

// === BULK REEL UPLOAD ===
async function pushAllReels(form){
  const slots = Array.from(form.querySelectorAll('#reel-slots-container .reel-slot'));
  if(!slots.length) return;
  const identity = form.querySelector('select[name=identity]')?.value;
  if(!identity){ alert('Selectionne une identite'); return; }
  // Verifier que chaque slot a au moins une video clean
  for(const s of slots){
    const v = s.querySelector('input.up-file-main');
    if(!v || !v.files || !v.files.length){
      alert('Le reel #' + (parseInt(s.dataset.slotIdx)+1) + ' n a pas de vidéo CLEAN. Ajoute-en une ou supprime ce slot.');
      return;
    }
  }
  const submitBtn = form.querySelector('.up-submit');
  let done = 0, errs = 0;
  if(submitBtn){ submitBtn.disabled = true; submitBtn.textContent = '⬆ Upload 0 / ' + slots.length + '...'; }
  async function pushOne(slot, idx){
    const fd = new FormData();
    fd.append('identity', identity);
    const cleanInput = slot.querySelector('input[data-name=video]');
    const exampleInput = slot.querySelector('input[data-name=example]');
    const captionT = slot.querySelector('textarea[data-name=caption]');
    const descT = slot.querySelector('textarea[data-name=description]');
    if(cleanInput && cleanInput.files[0]) fd.append('video', cleanInput.files[0], cleanInput.files[0].name);
    if(exampleInput && exampleInput.files[0]) fd.append('example', exampleInput.files[0], exampleInput.files[0].name);
    if(captionT) fd.append('caption', captionT.value || '');
    if(descT) fd.append('description', descT.value || '');
    const status = slot.querySelector('.reel-slot-status');
    if(status){ status.className = 'reel-slot-status uploading'; status.textContent = '⏳ Upload en cours...'; }
    try {
      const r = await fetch(form.action, {method:'POST', body:fd, credentials:'same-origin'});
      if(r.ok){
        done++;
        if(status){ status.className = 'reel-slot-status ok'; status.textContent = '✓ Upload OK'; }
      } else {
        errs++;
        if(status){ status.className = 'reel-slot-status err'; status.textContent = '✗ Erreur ' + r.status; }
      }
    } catch(e){
      errs++;
      if(status){ status.className = 'reel-slot-status err'; status.textContent = '✗ Erreur réseau'; }
    }
    if(submitBtn) submitBtn.textContent = '⬆ Upload ' + (done+errs) + ' / ' + slots.length + '...';
  }
  // Push 2 reels en parallele max (videos lourdes)
  const CONCURRENCY = 2;
  for(let i = 0; i < slots.length; i += CONCURRENCY){
    await Promise.all(slots.slice(i, i + CONCURRENCY).map((s, j)=>pushOne(s, i+j)));
  }
  if(submitBtn){
    submitBtn.disabled = false;
    submitBtn.textContent = '✅ ' + done + ' reel(s) OK' + (errs?' · '+errs+' erreur(s)':'');
    submitBtn.style.background = errs ? 'linear-gradient(135deg,#22c55e,#ef4444)' : 'linear-gradient(135deg,#22c55e,#16a34a)';
  }
  setTimeout(()=>{
    if(submitBtn){
      submitBtn.textContent = '⬆ Uploader tous les reels';
      submitBtn.style.background = '';
    }
  }, 3500);
}

// === BULK UPLOAD : intercepte submit, envoie chaque file separement ===
document.addEventListener('submit', function(e){
  const form = e.target;
  if(!form.classList || !form.classList.contains('up-form')) return;
  // Reel form : utilise les slots de reel (bulk reel push)
  if(form.dataset.utype === 'reel' && form.querySelector('#reel-slots-container')){
    e.preventDefault();
    pushAllReels(form);
    return;
  }
  const mainInput = form.querySelector('.up-file-main');
  if(!mainInput || !mainInput.files || mainInput.files.length <= 1) return; // <=1 file : laisse le submit natif
  e.preventDefault();
  const files = Array.from(mainInput.files);
  const exampleInput = form.querySelector('.up-file-example');
  const exampleFile = exampleInput && exampleInput.files.length ? exampleInput.files[0] : null;
  const submitBtn = form.querySelector('.up-submit');
  const baseData = new FormData(form);
  // Conserve les champs non-fichier
  const nonFileFields = {};
  baseData.forEach((v, k)=>{
    if(!(v instanceof File)) nonFileFields[k] = v;
  });
  let done = 0, errs = 0;
  if(submitBtn){ submitBtn.disabled = true; submitBtn.textContent = '⬆ Upload 0 / ' + files.length + '...'; }
  const fileFieldName = mainInput.getAttribute('name');
  async function pushOne(file, idx){
    const fd = new FormData();
    Object.entries(nonFileFields).forEach(([k,v])=>fd.append(k, v));
    fd.append(fileFieldName, file, file.name);
    // Pour reel : ajoute la video example sur le PREMIER push uniquement
    if(idx === 0 && exampleFile){
      fd.append('example', exampleFile, exampleFile.name);
    }
    const pgEl = form.querySelector('.up-progress[data-idx="' + idx + '"]');
    if(pgEl){ pgEl.textContent = '⏳'; pgEl.style.color = '#3b82f6'; }
    try {
      const r = await fetch(form.action, {method:'POST', body:fd, credentials:'same-origin'});
      if(r.ok){
        done++;
        if(pgEl){ pgEl.textContent = '✓'; pgEl.style.color = '#22c55e'; }
      } else {
        errs++;
        if(pgEl){ pgEl.textContent = '✗ ' + r.status; pgEl.style.color = '#ef4444'; }
      }
    } catch(e){
      errs++;
      if(pgEl){ pgEl.textContent = '✗'; pgEl.style.color = '#ef4444'; }
    }
    if(submitBtn) submitBtn.textContent = '⬆ Upload ' + (done+errs) + ' / ' + files.length + '...';
  }
  // Push 3 en parallele max
  (async function(){
    const CONCURRENCY = 3;
    for(let i = 0; i < files.length; i += CONCURRENCY){
      await Promise.all(files.slice(i, i + CONCURRENCY).map((f, j)=>pushOne(f, i+j)));
    }
    if(submitBtn){
      submitBtn.disabled = false;
      submitBtn.textContent = '✅ ' + done + ' upload(s) OK' + (errs?' · '+errs+' erreur(s)':'');
      submitBtn.style.background = errs ? 'linear-gradient(135deg,#22c55e,#ef4444)' : 'linear-gradient(135deg,#22c55e,#16a34a)';
    }
    setTimeout(function(){
      if(submitBtn){
        submitBtn.textContent = '⬆ Uploader';
        submitBtn.style.background = '';
      }
      mainInput.value = '';
      _upRefreshTable(mainInput);
    }, 2500);
  })();
}, true);
document.addEventListener('dragover', function(e){
  const drop = e.target.closest('.up-drop');
  if(drop){ e.preventDefault(); drop.classList.add('dragover'); }
});
document.addEventListener('dragleave', function(e){
  const drop = e.target.closest('.up-drop');
  if(drop){ drop.classList.remove('dragover'); }
});

// === SFW toggle global (floute toutes les images de la dashboard) ===
function toggleSFW(){
  document.body.classList.toggle('sfw-on');
  localStorage.setItem('vault_sfw', document.body.classList.contains('sfw-on') ? '1' : '0');
}
// Init : si SFW etait actif a la derniere visite, ré-applique direct
(function(){
  if(localStorage.getItem('vault_sfw') === '1'){
    document.body.classList.add('sfw-on');
  }
})();

function vaultFilter(q){
  q = (q || '').toLowerCase().trim();
  var list = document.querySelectorAll('.vault-item');
  list.forEach(function(el){
    var ident = (el.getAttribute('data-ident') || '').toLowerCase();
    el.style.display = (!q || ident.indexOf(q) !== -1) ? '' : 'none';
  });
}
function vaultSortToggle(e, btn){
  e.stopPropagation();
  var wrap = btn.closest('.vault-sort');
  if(!wrap) return;
  // Fermer les autres
  document.querySelectorAll('.vault-sort.open').forEach(function(w){ if(w !== wrap) w.classList.remove('open'); });
  wrap.classList.toggle('open');
}
document.addEventListener('click', function(e){
  document.querySelectorAll('.vault-sort.open').forEach(function(w){
    if(!w.contains(e.target)) w.classList.remove('open');
  });
});

// === Vault : AJAX switch instantane + prefetch on hover ===
window.__vaultPrefetchCache = window.__vaultPrefetchCache || {};
window.__vaultPrefetchInflight = window.__vaultPrefetchInflight || {};

window.vaultPrefetch = function(url){
  if(!url || window.__vaultPrefetchCache[url] || window.__vaultPrefetchInflight[url]) return;
  window.__vaultPrefetchInflight[url] = true;
  fetch(url, {credentials:'same-origin'})
    .then(r=>r.text())
    .then(html=>{
      window.__vaultPrefetchCache[url] = html;
      delete window.__vaultPrefetchInflight[url];
    })
    .catch(()=>{ delete window.__vaultPrefetchInflight[url]; });
};

window.vaultGoTo = function(ev, url){
  if(ev && (ev.ctrlKey || ev.metaKey || ev.shiftKey)) return true;
  ev.preventDefault();
  // Active item sidebar (UI feedback instant)
  const allItems = document.querySelectorAll('.vault-item');
  allItems.forEach(i=>{
    const same = i.getAttribute('href') === url || (i.href === url);
    i.classList.toggle('vault-item-active', same);
  });
  // Met a jour l URL
  try{ history.pushState({}, '', url); }catch(e){}
  // Trouve la section ciblee (form-cloud<...>)
  let sec = document.querySelector('.form-section[id^="form-cloud"]');
  // Choisis la section visible (style block), sinon premiere matchant
  document.querySelectorAll('.form-section[id^="form-cloud"]').forEach(s=>{
    if(s.style.display && s.style.display !== 'none') sec = s;
  });
  if(!sec) { window.location.href = url; return false; }
  // Skeleton instant : remplace les images existantes par placeholder
  sec.querySelectorAll('.vault-card-bg img').forEach(img=>{
    img.style.opacity = '0';
  });
  sec.querySelectorAll('.vault-card-bg').forEach(c=>{
    c.style.animation = '';
  });
  // Charge le nouveau HTML
  const apply = (html)=>{
    try{
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const newSec = doc.getElementById(sec.id);
      if(!newSec){ window.location.href = url; return; }
      sec.innerHTML = newSec.innerHTML;
      // Re-execute les scripts inline
      sec.querySelectorAll('script').forEach(oldS=>{
        const newS = document.createElement('script');
        newS.textContent = oldS.textContent;
        oldS.parentNode.replaceChild(newS, oldS);
      });
    } catch(e){ window.location.href = url; }
  };
  if(window.__vaultPrefetchCache[url]){
    apply(window.__vaultPrefetchCache[url]);
  } else {
    fetch(url, {credentials:'same-origin'}).then(r=>r.text()).then(apply).catch(()=>{ window.location.href = url; });
  }
  return false;
};
window.addEventListener('popstate', function(){
  // Re-render la section actuelle en fonction de l URL
  window.vaultGoTo({preventDefault:()=>{}, ctrlKey:false}, window.location.href);
});

// === Lazy loading des thumbnails differees (IntersectionObserver) ===
(function(){
  const imgs = document.querySelectorAll('img.vault-defer-img');
  if(!imgs.length || !('IntersectionObserver' in window)) {
    // Fallback : charge tout direct
    imgs.forEach(i=>{ if(i.dataset.src){ i.src = i.dataset.src; }});
    return;
  }
  const status = document.getElementById('vault-load-status');
  let loaded = 24; // INITIAL_BATCH
  const total = 24 + imgs.length;
  const io = new IntersectionObserver((entries)=>{
    entries.forEach(entry=>{
      if(entry.isIntersecting){
        const img = entry.target;
        if(img.dataset.src){
          img.src = img.dataset.src;
          delete img.dataset.src;
          img.addEventListener('load', function(){
            img.style.opacity = '1';
            // Arret du skeleton apres chargement
            const card = img.closest('.vault-card-bg');
            if(card) card.style.animation = 'none';
          }, {once:true});
          io.unobserve(img);
          loaded++;
          if(status) status.textContent = loaded + ' / ' + total + ' charges';
          if(loaded >= total && status) status.style.display = 'none';
        }
      }
    });
  }, {rootMargin: '300px'});  // pre-charge avant que l img n entre dans le viewport
  imgs.forEach(img=>io.observe(img));
})();

// Pour les imgs eager (premiers 24) : aussi stop le skeleton apres load
document.querySelectorAll('img.vault-img-load:not(.vault-defer-img)').forEach(function(img){
  if(img.complete && img.naturalHeight !== 0){
    img.style.opacity = '1';
    const card = img.closest('.vault-card-bg');
    if(card) card.style.animation = 'none';
  } else {
    img.addEventListener('load', function(){
      img.style.opacity = '1';
      const card = img.closest('.vault-card-bg');
      if(card) card.style.animation = 'none';
    }, {once:true});
  }
});
</script>
"""

    return (
        css
        + "<div class='vault-layout'>"
        + vault_sidebar
        + f"<div class='vault-gallery'>{gallery}</div>"
        + "</div>"
    )


def _render_cloud_pps_html() -> str:
    """PPs partagées avec preview en grille + bouton + Add media."""
    add_btn = (
        "<button type='button' onclick=\"showTab('upload','pp','Photo de profil','Pool partagé entre toutes les identités')\" "
        "style='display:inline-flex;align-items:center;gap:8px;padding:9px 16px;"
        "background:linear-gradient(135deg,#3b82f6,#a855f7);border:0;color:#fff;"
        "border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;"
        "box-shadow:0 4px 12px rgba(59,130,246,.25);margin-bottom:14px'>"
        "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>"
        "Add media (PP)</button>"
    )
    if not PROFILE_PICS_DIR.exists():
        return add_btn + "<p style='color:#888'>Aucune PP uploadée.</p>"
    files = sorted([p for p in PROFILE_PICS_DIR.iterdir() if p.is_file()])
    if not files:
        return add_btn + "<p style='color:#888'>Aucune PP uploadée.</p>"
    rows = [add_btn, "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px'>"]
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
        "<button type='submit' style='padding:10px 18px;background:#3b82f6;color:#fff;border:0;border-radius:6px;cursor:pointer;font-weight:600'>+ Ajouter</button>"
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
                verified_badge = "<span style='color:#3b82f6;font-size:13px' title='Vérifié'>✓</span>"
            # Avatar : image ou initiale colorée
            if pic:
                avatar_html = (
                    f"<img src='{pic}' loading='lazy' "
                    f"style='width:48px;height:48px;border-radius:50%;object-fit:cover;background:#0f0f0f' "
                    f"onerror=\"this.style.display='none';this.nextElementSibling.style.display='flex'\">"
                    f"<div style='display:none;width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#06b6d4);"
                    f"align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:18px'>{u[0].upper()}</div>"
                )
            else:
                avatar_html = (
                    f"<div style='width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#06b6d4);"
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
                f"<button type='submit' style='width:100%;padding:8px;background:#3b82f6;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin:0'>🔄 Scrape</button>"
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
            f"<button type='submit' style='padding:12px 24px;background:#3b82f6;color:#fff;border:0;border-radius:8px;cursor:pointer;font-weight:600' "
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
            "<button type='submit' style='padding:14px 28px;background:#3b82f6;color:#fff;border:0;border-radius:10px;cursor:pointer;font-weight:700;font-size:15px;margin:0' "
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
            # Badge plus clean : pill avec icone trending + valeur
            trending_html = (
                '<div style="display:inline-flex;align-items:center;gap:5px;color:#22c55e;font-weight:800;font-size:12px;margin-bottom:6px;'
                'background:rgba(34,197,94,.15);padding:3px 9px;border-radius:8px;letter-spacing:.2px;'
                'border:1px solid rgba(34,197,94,.35);text-shadow:0 0 4px rgba(0,0,0,.6)">'
                '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="#22c55e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
                '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>'
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
                f"<video class='reel-video' src='{video_url}' muted loop playsinline preload='metadata' "
                f"style='position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .25s'></video>"
            )
        cards.append(f"""
<div class="reel-card cloud-card" data-ts="{taken_at}" data-views="{d_views}" data-likes="{d_likes}" data-comments="{d_comments}" data-trending="{int((d_views/max(avg,1))*100) if avg > 0 else 0}" data-url="{url}" data-video-url="{video_url}" data-thumb="{thumb}" data-owner="{owner}" data-owner-pp="{owner_pic}" data-caption="{caption}" data-time-ago="{time_ago}" style="background:#0f0f0f;border:1px solid #2a2a2a;border-radius:14px;overflow:hidden;display:flex;flex-direction:column">
  <div class="reel-media" style="position:relative;width:100%;aspect-ratio:9/16;background:#000;cursor:pointer;overflow:hidden"
       onmouseenter='igHoverPlay(this)'
       onmouseleave='igHoverStop(this)'
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
      <button onclick='addToVeille(this, {{"url":"{url}","video_url":"{video_url}","thumb":"{thumb}","owner":"{owner}","owner_pp":"{owner_pic}","caption":"{caption}","views":{d_views},"likes":{d_likes},"comments":{d_comments}}})' title="Ajouter à la Veille" style="width:28px;height:28px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border:0;border-radius:50%;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
      </button>
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
    <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(to top,rgba(0,0,0,.9),transparent);padding:8px 10px;z-index:2">
      {trending_html}
      <button onclick='event.stopPropagation();toggleReelExpand(this.closest(".reel-card"))' title="Voir caption, son, durée" class="reel-username-btn" style="display:flex;align-items:center;gap:7px;color:#fff;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);cursor:pointer;font-size:12px;font-weight:700;width:100%;padding:6px 10px;border-radius:8px;text-align:left;font-family:inherit;backdrop-filter:blur(4px);transition:.15s" onmouseover="this.style.background='rgba(255,255,255,.14)'" onmouseout="this.style.background='rgba(255,255,255,.06)'">
        {avatar}<span style="flex:1">@{owner}</span>
        <svg class="reel-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="transition:transform .2s"><polyline points="6 15 12 9 18 15"/></svg>
      </button>
    </div>
  </div>
  <!-- Expand panel : caption + sound (cachee par defaut) -->
  <div class="reel-expand" style="display:none;padding:12px;background:#0f0f0f;border-top:1px solid #232323;font-size:12.5px;color:#ddd;line-height:1.5">
    <div style="color:#fff;white-space:pre-wrap;word-wrap:break-word;max-height:140px;overflow-y:auto">{caption_short if caption_short else '<span style=color:#666>Aucune caption</span>'}</div>
    <div style="display:flex;align-items:center;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid #1a1a1a;color:#888;font-size:11.5px">
      <span style="color:#3b82f6">🎵</span> <span>Sound:</span>
      <span style="color:#ccc">Original audio</span>
      <span style="margin-left:auto;color:#3b82f6;font-weight:700" class="reel-dur-label">--:--</span>
    </div>
  </div>
</div>""")
    cards.append("</div>")
    cards.append(f"<div style='margin-top:18px;display:flex;justify-content:space-between;align-items:center'>"
                 f"<small id='ig-period-info'>{len(reels)} reel(s) au total</small>"
                 f"<form method='POST' action='/insta/scrape_all' style='margin:0'>"
                 f"<button type='submit' style='padding:8px 18px;background:#3b82f6;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;margin:0' "
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
        f"background:linear-gradient(135deg,#3b82f6,#06b6d4);display:flex;"
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
            f"<button type='submit' style='width:100%;padding:8px;background:#3b82f6;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin-top:8px'>Upload</button>"
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
        "style='flex:1;padding:14px;background:none;border:0;color:#fff;cursor:pointer;font-size:16px;font-weight:700;border-bottom:3px solid #3b82f6;margin:0'>"
        "OnlyFans (OF)</button>"
        "<button class='sfs-platform-tab' data-platform='MYM' onclick='switchSfsPlatform(this,\"MYM\")' "
        "style='flex:1;padding:14px;background:none;border:0;color:#888;cursor:pointer;font-size:16px;font-weight:700;border-bottom:3px solid transparent;margin:0'>"
        "MYM</button>"
        "</div>"
    )

    # === LAYOUT 3 COLONNES : identités | calendrier | détail jour ===
    rows.append("<div style='display:grid;grid-template-columns:220px 1fr 300px;gap:16px;align-items:start' class='sfs-layout'>")

    # --- COLONNE 1 : LISTE DES IDENTITÉS ---
    rows.append("<div class='box' style='padding:14px'>")
    # Filtre "All creators"
    rows.append(
        "<div onclick='filterSfsByIdentity(null,this)' "
        "class='sfs-ident-row sfs-ident-all active' "
        "style='display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;cursor:pointer;color:#3b82f6;font-weight:600;font-size:13px;background:rgba(59,130,246,.1)'>"
        "<span>All creators</span>"
        "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='margin-left:auto'><polyline points='6 9 12 15 18 9'/></svg>"
        "</div>"
    )
    # Liste des identités avec compteur de SFS
    sfs_count_by_ident = {}
    for it in items:
        ident = it.get("identity", "")
        if ident:
            sfs_count_by_ident[ident] = sfs_count_by_ident.get(ident, 0) + 1
    for ident in sorted(_list_identities()):
        avatar = _identity_avatar_html(ident, size=36)
        count = sfs_count_by_ident.get(ident, 0)
        # Plateformes auxquelles cette identité appartient
        ident_platforms = platforms_map.get(ident, [])
        platforms_attr = ",".join(ident_platforms)
        badge = ""
        if count > 0:
            badge = (
                f"<span style='background:#ef4444;color:#fff;font-size:10px;padding:2px 6px;"
                f"border-radius:8px;font-weight:700;margin-left:auto;display:flex;align-items:center;gap:3px'>"
                f"<svg viewBox='0 0 24 24' width='9' height='9' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9'/><path d='M10.3 21a1.94 1.94 0 0 0 3.4 0'/></svg>{count}</span>"
            )
        rows.append(
            f"<div onclick='filterSfsByIdentity(\"{ident}\",this)' "
            f"class='sfs-ident-row' data-ident='{ident}' data-platforms='{platforms_attr}' "
            f"style='display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;cursor:pointer;margin-top:4px;transition:background .15s' "
            f"onmouseover='if(!this.classList.contains(\"active\"))this.style.background=\"#1a1a1a\"' "
            f"onmouseout='if(!this.classList.contains(\"active\"))this.style.background=\"transparent\"'>"
            f"<div style='position:relative'>{avatar}"
            f"<div style='position:absolute;bottom:0;right:0;width:9px;height:9px;background:#10b981;border:2px solid #0a0a0a;border-radius:50%'></div>"
            f"</div>"
            f"<span style='font-weight:600;font-size:13px;color:#fff'>{ident}</span>"
            f"{badge}"
            f"</div>"
        )
    rows.append("</div>")

    # --- COLONNE 2 : CALENDRIER ---
    rows.append("<div class='box'>")
    # Header du calendrier avec navigation
    today_link = f"?tab=sfs&sfs_month={today.year:04d}-{today.month:02d}"
    prev_link = f"?tab=sfs&sfs_month={prev_year:04d}-{prev_month:02d}"
    next_link = f"?tab=sfs&sfs_month={next_year:04d}-{next_month:02d}"
    is_current_month = (year == today.year and month == today.month)
    today_btn_html = ""
    if not is_current_month:
        today_btn_html = (
            f"<a href='{today_link}' style='padding:6px 12px;background:#3b82f6;color:#fff;"
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
            f"<a href='{today_link}' style='padding:6px 14px;background:#3b82f6;color:#fff;"
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
        cell_bg = "#0f1a2e" if is_today else "transparent"
        weight = 700 if is_today else 500
        # Si c'est le 1er du mois, afficher aussi le nom du mois (style référence "mai 1")
        day_label_html = f"<span style='color:#888;font-size:12px;margin-right:4px'>{fr_months[month-1][:3].lower()}</span>{d}" if d == 1 else str(d)
        rows.append(
            f"<div class='sfs-day' data-date='{date_iso}' data-of='{nb_of}' data-mym='{nb_mym}' "
            f"onclick='selectSfsDay(\"{date_iso}\")' ondblclick='openSfsModal(\"{date_iso}\")' "
            f"style='min-height:120px;background:{cell_bg};border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:10px 12px;cursor:pointer;transition:background .15s;display:flex;flex-direction:column;position:relative' "
            f"onmouseover='this.style.background=\"#15100d\"' onmouseout='if(window.__selectedSfsDate !== this.dataset.date) this.style.background=\"{cell_bg}\"'>"
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
    rows.append("</div></div>")  # ferme la grille + box du calendrier

    # === PANEL DROITE : DÉTAIL DU JOUR SÉLECTIONNÉ ===
    rows.append("<div class='box' id='sfs-day-panel' style='position:sticky;top:20px'>")
    rows.append("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px'>")
    rows.append("<div style='display:flex;align-items:center;gap:4px'>")
    rows.append("<button onclick='shiftDayPanel(-1)' style='width:28px;height:28px;background:transparent;color:#aaa;border:0;border-radius:6px;cursor:pointer;font-size:16px;padding:0;margin:0'>‹</button>")
    rows.append("<button onclick='shiftDayPanel(1)' style='width:28px;height:28px;background:transparent;color:#aaa;border:0;border-radius:6px;cursor:pointer;font-size:16px;padding:0;margin:0'>›</button>")
    rows.append("</div>")
    rows.append("<div id='sfs-day-panel-title' style='font-weight:600;font-size:14px;color:#fff'>mai 28, 2026</div>")
    rows.append("<button onclick='openSfsModalFromPanel()' title='Ajouter SFS' style='width:32px;height:32px;background:#3b82f6;border:0;border-radius:8px;color:#fff;cursor:pointer;font-size:18px;font-weight:700;padding:0;margin:0;line-height:1'>+</button>")
    rows.append("</div>")
    rows.append("<div id='sfs-day-panel-content' style='min-height:240px'></div>")
    rows.append("</div>")

    rows.append("</div>")  # ferme le grid 2 cols

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
  return '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#06b6d4);display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:' + Math.round(size*0.45) + 'px;flex-shrink:0">' + init + '</div>';
}}

function switchSfsPlatform(btn, platform){{
  window.__currentSfsPlatform = platform;
  document.querySelectorAll('.sfs-platform-tab').forEach(function(b){{
    b.style.color = '#888';
    b.style.borderBottomColor = 'transparent';
  }});
  btn.style.color = '#fff';
  btn.style.borderBottomColor = (platform === 'OF') ? '#3b82f6' : '#06b6d4';
  // Filtrer la liste des identités selon la plateforme
  var currentIdent = window.__currentSfsIdent;
  var stillVisible = false;
  document.querySelectorAll('.sfs-ident-row[data-platforms]').forEach(function(row){{
    var rowPlatforms = (row.dataset.platforms || '').split(',').filter(Boolean);
    var matches = rowPlatforms.indexOf(platform) !== -1;
    row.style.display = matches ? '' : 'none';
    if(matches && row.dataset.ident === currentIdent) stillVisible = true;
  }});
  // Si l'identité sélectionnée n'est pas sur cette plateforme, repasser à "All creators"
  if(currentIdent && !stillVisible){{
    var allRow = document.querySelector('.sfs-ident-all');
    if(allRow) filterSfsByIdentity(null, allRow);
  }} else {{
    refreshSfsCalendar();
    refreshSfsDayPanel();
  }}
}}

function filterSfsByIdentity(ident, btnEl){{
  window.__currentSfsIdent = ident; // null = all
  // Highlight visuel
  document.querySelectorAll('.sfs-ident-row').forEach(function(r){{
    r.classList.remove('active');
    r.style.background = 'transparent';
    r.style.color = '#fff';
  }});
  if(btnEl){{
    btnEl.classList.add('active');
    btnEl.style.background = 'rgba(59,130,246,.15)';
    btnEl.style.color = '#3b82f6';
  }}
  refreshSfsCalendar();
  refreshSfsDayPanel();
}}
function refreshSfsCalendar(){{
  var platform = window.__currentSfsPlatform;
  var ident = window.__currentSfsIdent;
  document.querySelectorAll('.sfs-day').forEach(function(day){{
    var barsEl = day.querySelector('.sfs-day-bars') || day.querySelector('.sfs-day-badges');
    if(barsEl) barsEl.innerHTML = '';
    var date = day.dataset.date;
    var allDay = window.__sfsData[date] || [];
    var filtered = allDay.filter(function(x){{ return x.platform === platform && (!ident || x.identity === ident); }});
    if(filtered.length === 0 || !barsEl) return;
    var nb_sched = filtered.filter(function(x){{ return x.status === 'scheduled'; }}).length;
    var nb_prog = filtered.filter(function(x){{ return x.status === 'to_program'; }}).length;
    // Barre orange #f59e0b pour scheduled (style référence)
    if(nb_sched){{
      var b = document.createElement('div');
      b.style.cssText = 'background:#f59e0b;color:#fff;font-size:10px;padding:3px 8px;border-radius:4px;font-weight:700;text-align:center;width:100%;box-sizing:border-box';
      b.textContent = nb_sched;
      barsEl.appendChild(b);
    }}
    // Barre grise #6b7280 pour to_program (différencier du orange)
    if(nb_prog){{
      var b = document.createElement('div');
      b.style.cssText = 'background:#6b7280;color:#fff;font-size:10px;padding:3px 8px;border-radius:4px;font-weight:700;text-align:center;width:100%;box-sizing:border-box';
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

function selectSfsDay(date){{
  window.__selectedSfsDate = date;
  refreshSfsDayPanel();
  // Toggle la classe "selected" sur la bonne cellule
  document.querySelectorAll('.sfs-day').forEach(function(c){{
    c.classList.toggle('selected', c.dataset.date === date);
  }});
}}
function refreshSfsDayPanel(){{
  var date = window.__selectedSfsDate;
  if(!date) return;
  var platform = window.__currentSfsPlatform;
  // Format date en français lisible
  var d = new Date(date);
  var months = ['janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc'];
  var formatted = months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
  document.getElementById('sfs-day-panel-title').textContent = formatted;
  var ident = window.__currentSfsIdent;
  var items = (window.__sfsData[date] || []).filter(function(x){{ return x.platform === platform && (!ident || x.identity === ident); }});
  var content = document.getElementById('sfs-day-panel-content');
  if(items.length === 0){{
    content.innerHTML = '<div style="text-align:center;color:#666;padding:40px 20px"><svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:12px"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg><div style="font-size:14px">Aucun SFS prévu</div><div style="font-size:12px;margin-top:8px;color:#555">Pour le ' + platform + ' ce jour-là</div></div>';
    return;
  }}
  var html = '<div style="display:flex;flex-direction:column;gap:8px">';
  items.forEach(function(x){{
    var statusBadge = x.status === 'scheduled'
      ? '<span style="background:#3b82f6;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">SCHEDULED</span>'
      : '<span style="background:#6b7280;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">TO PROGRAM</span>';
    html += '<div style="background:#0f0f0f;border:1px solid #2a2a2a;border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:8px">'
      + '<div style="display:flex;align-items:center;gap:8px">' + identityAvatarHtml(x.identity, 28)
      + '<div style="flex:1"><div style="font-weight:700;font-size:13px">' + x.identity + '</div><div style="font-size:11px;color:#888">@' + x.partner + '</div></div></div>'
      + '<div style="display:flex;justify-content:space-between;align-items:center"><span style="color:#aaa;font-size:12px">à ' + x.time + '</span>' + statusBadge + '</div>'
      + (x.notes ? '<div style="font-size:12px;color:#888;border-top:1px solid #2a2a2a;padding-top:6px">' + x.notes + '</div>' : '')
      + '</div>';
  }});
  html += '</div>';
  content.innerHTML = html;
}}
function shiftDayPanel(delta){{
  if(!window.__selectedSfsDate) return;
  var d = new Date(window.__selectedSfsDate);
  d.setDate(d.getDate() + delta);
  var iso = d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  selectSfsDay(iso);
}}
function openSfsModalFromPanel(){{
  if(window.__selectedSfsDate) openSfsModal(window.__selectedSfsDate);
}}
function openSfsModal(date){{
  selectSfsDay(date);
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
        ? '<span style="background:#3b82f6;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">SCHEDULED</span>'
        : '<span style="background:#6b7280;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">TO PROGRAM</span>';
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
  setTimeout(function(){{
    // Filtrer la liste d'identités pour OF (par défaut)
    var initialPlatform = window.__currentSfsPlatform || 'OF';
    document.querySelectorAll('.sfs-ident-row[data-platforms]').forEach(function(row){{
      var rowPlatforms = (row.dataset.platforms || '').split(',').filter(Boolean);
      row.style.display = rowPlatforms.indexOf(initialPlatform) !== -1 ? '' : 'none';
    }});
    refreshSfsCalendar();
    // Sélectionner aujourd'hui par défaut
    var today = new Date();
    var todayIso = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
    selectSfsDay(todayIso);
  }}, 50);
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
        <button type='submit' style='padding:10px 22px;background:#3b82f6;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:0'>Ajouter</button>
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
                "<span style='background:#3b82f6;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>SCHEDULED</span>"
                if status == "scheduled" else
                "<span style='background:#6b7280;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>TO PROGRAM</span>"
            )
            platform = it.get("platform", "OF")
            platform_color = "#3b82f6" if platform == "OF" else "#06b6d4"
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
                f"<input type='checkbox' name='platform_{ident}' value='{p}' {checked} style='width:18px;height:18px;accent-color:#3b82f6'>"
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


def _render_home_dashboard_html() -> str:
    """Dashboard global affiché à la racine — synthèse de TOUS les revenus.

    Combine :
    - MyPuls (ventes chatteurs live) — cache 5min
    - Revenus manuels (module Business → Revenus)
    Avec sélecteur de période (Aujourd'hui / Hier / Cette semaine / Ce mois).
    """
    import datetime as _dt
    from flask import request as flask_request

    period = flask_request.args.get("home_period", "week") if hasattr(flask_request, "args") else "week"
    today = _dt.date.today()

    # Calculer la période
    if period == "today":
        start = today
        end = today
        period_label = "Aujourd'hui"
    elif period == "yesterday":
        start = end = today - _dt.timedelta(days=1)
        period_label = "Hier"
    elif period == "month":
        start = today.replace(day=1)
        end = today
        period_label = "Ce mois"
    else:  # week
        start = today - _dt.timedelta(days=today.weekday())
        end = today
        period_label = "Cette semaine"

    # Fetch MyPuls (cached)
    mp_configured = False
    mp_data = {"totals": {}, "chatters": [], "transactions": [], "chart": {}}
    try:
        import mypuls
        mp_configured = mypuls.is_configured()
        if mp_configured:
            res = mypuls.fetch_team_stats(start.isoformat(), end.isoformat(), use_cache=True)
            if res.get("ok"):
                mp_data = res
    except Exception:
        pass

    # Fetch revenus manuels (module Business)
    manual_total = 0.0
    try:
        from business import list_revenues
        revs = list_revenues()
        for r in revs:
            try:
                d = _dt.date.fromisoformat(r.get("date", ""))
                if start <= d <= end:
                    manual_total += float(r.get("amount", 0))
            except Exception:
                pass
    except Exception:
        pass

    totals = mp_data.get("totals", {}) or {}
    chatters = mp_data.get("chatters", []) or []
    chart_data = mp_data.get("chart", {}) or {}

    ca_total = float(totals.get("ca_total", 0))
    ca_ppv = float(totals.get("ca_ppv", 0))
    ca_tips = float(totals.get("ca_tips", 0))
    nb_tx = int(totals.get("nb_transactions", 0))
    active_chatters = int(totals.get("active_chatters", 0))
    grand_total = ca_total + manual_total

    def _btn(p, label):
        active = "home-period-active" if p == period else ""
        return f"<a href='?tab=home&home_period={p}' class='home-period-btn {active}'>{label}</a>"

    period_switcher = (
        "<div class='home-period-row'>"
        + _btn("today", "Aujourd'hui")
        + _btn("yesterday", "Hier")
        + _btn("week", "Cette semaine")
        + _btn("month", "Ce mois")
        + "</div>"
    )

    # Top créateurs (depuis le chart datasets)
    top_creators_html = ""
    if chart_data.get("datasets"):
        creators_map = {}
        try:
            cr_res = mypuls.list_creators()
            if cr_res.get("ok"):
                creators_map = cr_res.get("creators") or {}
        except Exception:
            pass
        items = []
        for i, ds in enumerate(chart_data["datasets"][:5]):
            cid = creators_map.get(ds["label"])
            avatar = (
                f"<img src='/mypuls/avatar/{cid}' style='width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a'>"
                if cid else
                f"<div style='width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700'>{ds['label'][:1].upper()}</div>"
            )
            pct = (ds["total"] / chart_data.get("all_creators_total", 1) * 100) if chart_data.get("all_creators_total") else 0
            items.append(
                f"<div style='display:flex;align-items:center;gap:12px;padding:10px 14px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px'>"
                f"{avatar}"
                f"<div style='flex:1;min-width:0'>"
                f"<div style='font-weight:600;font-size:14px'>{ds['label']}</div>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-top:4px'>"
                f"<div style='flex:1;background:#0f0f0f;height:5px;border-radius:3px;overflow:hidden'><div style='width:{pct:.1f}%;height:100%;background:linear-gradient(90deg,#22c55e,#3b82f6)'></div></div>"
                f"<div style='font-size:11px;color:#888;font-weight:600;min-width:60px;text-align:right'>{ds['total']:.0f}€</div>"
                f"</div>"
                f"</div>"
                f"</div>"
            )
        top_creators_html = (
            "<div class='home-card'>"
            "<div class='home-card-header'>Top modèles</div>"
            "<div style='display:flex;flex-direction:column;gap:8px'>"
            + "".join(items)
            + "</div></div>"
        )

    # Top chatteurs (top 5)
    top_chatters_html = ""
    if chatters:
        items = []
        max_ca = chatters[0].get("ca_total", 1) or 1
        for c in chatters[:5]:
            pct = (c.get("ca_total", 0) / max_ca * 100) if max_ca else 0
            items.append(
                f"<div style='display:flex;align-items:center;gap:12px;padding:10px 14px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px'>"
                f"<div style='width:32px;height:32px;border-radius:50%;background:#3b82f6;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px'>{c['name'][:2].upper()}</div>"
                f"<div style='flex:1;min-width:0'>"
                f"<div style='font-weight:600;font-size:14px'>{c['name']}</div>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-top:4px'>"
                f"<div style='flex:1;background:#0f0f0f;height:5px;border-radius:3px;overflow:hidden'><div style='width:{pct:.1f}%;height:100%;background:linear-gradient(90deg,#a855f7,#ec4899)'></div></div>"
                f"<div style='font-size:11px;color:#888;font-weight:600;min-width:60px;text-align:right'>{c['ca_total']:.0f}€</div>"
                f"</div>"
                f"</div>"
                f"</div>"
            )
        top_chatters_html = (
            "<div class='home-card'>"
            "<div class='home-card-header'>Top chatteurs</div>"
            "<div style='display:flex;flex-direction:column;gap:8px'>"
            + "".join(items)
            + "</div></div>"
        )

    if not mp_configured:
        warning = (
            "<div style='padding:14px 16px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.3);border-radius:10px;margin-bottom:18px;font-size:13px;color:#fbbf24'>"
            "💡 Configure MyPuls (Business → Revenus) pour voir tes ventes en temps réel."
            "</div>"
        )
    else:
        warning = ""

    # Breakdown par type de revenu (matching Infloww layout)
    type_totals = {"Subscriptions": 0.0, "Posts": 0.0, "Messages": 0.0,
                   "Tips": 0.0, "Referrals": 0.0, "Streams": 0.0}
    for tx in mp_data.get("transactions", []) or []:
        ty = (tx.get("type", "") or "").lower()
        amt = tx.get("amount", 0)
        if "média privé" in ty or "media prive" in ty or "ppv" in ty or "message" in ty:
            type_totals["Messages"] += amt
        elif "pourboire" in ty or "tip" in ty:
            type_totals["Tips"] += amt
        elif "abonnement" in ty or "subscription" in ty:
            type_totals["Subscriptions"] += amt
        elif "post" in ty:
            type_totals["Posts"] += amt
        elif "stream" in ty:
            type_totals["Streams"] += amt
        elif "referral" in ty or "parrain" in ty:
            type_totals["Referrals"] += amt

    css = """
<style>
.home-period-row{display:flex;gap:0;background:rgba(255,255,255,.04);border:1px solid #2a2a2a;border-radius:10px;padding:4px;font-size:13px}
.home-period-btn{background:transparent;border:0;color:#888;padding:8px 18px;border-radius:7px;font-weight:600;cursor:pointer;text-decoration:none;transition:all .15s;flex:1;text-align:center}
.home-period-btn:hover{color:#fff}
.home-period-active{background:#3b82f6 !important;color:#fff !important;box-shadow:0 2px 8px rgba(59,130,246,.25)}
.home-overview{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:24px;margin-bottom:18px}
.home-overview-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px;gap:14px;flex-wrap:wrap}
.home-overview-title{font-size:16px;font-weight:700;letter-spacing:-.01em;display:flex;align-items:center;gap:8px}
.home-overview-title small{font-size:11px;font-weight:400;color:#888;background:rgba(59,130,246,.1);padding:3px 8px;border-radius:5px}
.home-grid{display:grid;grid-template-columns:280px 1fr 1fr 1fr;gap:14px}
@media(max-width:1100px){.home-grid{grid-template-columns:1fr 1fr 1fr}}
@media(max-width:760px){.home-grid{grid-template-columns:1fr 1fr}}
.home-hero-card{background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.25);border-radius:14px;padding:22px;grid-row:span 2;display:flex;flex-direction:column;justify-content:space-between;min-height:180px;position:relative;overflow:hidden}
.home-hero-card::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at 80% 20%,rgba(59,130,246,.15),transparent 60%);pointer-events:none}
.home-hero-icon{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#3b82f6,#2563eb);display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 6px 20px rgba(59,130,246,.4);position:relative}
.home-hero-label{font-size:13px;color:#3b82f6;font-weight:600;margin-top:32px;position:relative}
.home-hero-value{font-size:36px;font-weight:800;letter-spacing:-.03em;margin-top:6px;position:relative}
.home-stat{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px;position:relative;display:flex;flex-direction:column;justify-content:space-between;min-height:88px}
.home-stat-icon{position:absolute;top:18px;right:18px;width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center}
.home-stat-value{font-size:22px;font-weight:800;letter-spacing:-.02em;line-height:1.1}
.home-stat-label{font-size:12px;color:#888;margin-top:5px;font-weight:500}
.home-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}
@media(max-width:768px){.home-row{grid-template-columns:1fr}}
.home-card{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px}
.home-card-header{font-size:14px;font-weight:700;margin-bottom:14px;letter-spacing:-.01em}
body.light .home-period-row{background:#f3f4f6;border-color:#e5e7eb}
body.light .home-period-btn{color:#666}
body.light .home-overview{background:#fff;border-color:#e5e7eb}
body.light .home-stat{background:#f9fafb;border-color:#e5e7eb}
body.light .home-card{background:#fff;border-color:#e5e7eb}
</style>
"""

    def _stat(label, value, color, bg_color, icon_svg):
        return (
            f"<div class='home-stat'>"
            f"<div class='home-stat-icon' style='background:{bg_color};color:{color}'>{icon_svg}</div>"
            f"<div>"
            f"<div class='home-stat-value' style='color:{color}'>{value:,.2f}€</div>"
            f"<div class='home-stat-label'>{label}</div>"
            f"</div>"
            f"</div>"
        )

    # 6 stat cards comme Infloww
    overview_html = (
        "<div class='home-overview'>"
        "<div class='home-overview-head'>"
        f"<div class='home-overview-title'>Aperçu des revenus créateur "
        f"<small>UTC{_dt.datetime.now().astimezone().strftime('%z')[:3]}:{_dt.datetime.now().astimezone().strftime('%z')[3:]}</small>"
        "</div>"
        + period_switcher
        + "</div>"
        "<div class='home-grid'>"
        # Big hero card (Total earnings)
        "<div class='home-hero-card'>"
        "<div class='home-hero-icon'>"
        "<svg viewBox='0 0 24 24' width='26' height='26' fill='none' stroke='currentColor' stroke-width='2.5'><path d='M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6'/></svg>"
        "</div>"
        f"<div><div class='home-hero-label'>Total revenus</div>"
        f"<div class='home-hero-value'>{ca_total + manual_total:,.2f}€</div></div>"
        "</div>"
        # 6 small stat cards
        + _stat("Abonnements", type_totals["Subscriptions"], "#22c55e", "rgba(34,197,94,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><path d='M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z'/></svg>")
        + _stat("Posts", type_totals["Posts"], "#10b981", "rgba(16,185,129,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><polyline points='14 2 14 8 20 8'/></svg>")
        + _stat("Messages (PPV)", type_totals["Messages"], "#a855f7", "rgba(168,85,247,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/></svg>")
        + _stat("Pourboires", type_totals["Tips"], "#f59e0b", "rgba(245,158,11,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><path d='M9 18h6M10 22h4M15 14c0-3 4-3 4-7a7 7 0 0 0-14 0c0 4 4 4 4 7'/></svg>")
        + _stat("Parrainage", type_totals["Referrals"], "#ec4899", "rgba(236,72,153,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M23 21v-2a4 4 0 0 0-3-3.87'/><path d='M16 3.13a4 4 0 0 1 0 7.75'/></svg>")
        + _stat("Streams", type_totals["Streams"], "#3b82f6", "rgba(59,130,246,.15)",
                "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' stroke-width='2'><line x1='8' y1='6' x2='21' y2='6'/><line x1='8' y1='12' x2='21' y2='12'/><line x1='8' y1='18' x2='21' y2='18'/><line x1='3' y1='6' x2='3.01' y2='6'/><line x1='3' y1='12' x2='3.01' y2='12'/><line x1='3' y1='18' x2='3.01' y2='18'/></svg>")
        + "</div>"
        + "</div>"
    )

    return (
        css
        + warning
        + overview_html
        + (
            f"<div class='home-row'>{top_creators_html}{top_chatters_html}</div>"
            if top_creators_html or top_chatters_html else ""
        )
    )


def _render_mypuls_section_html() -> str:
    """Section MyPuls en haut de la page Revenus.

    Scrape le dashboard MyPuls via cookies de session (PHPSESSID + REMEMBERME).
    Affiche : stats globales, top chatteurs, transactions récentes, filtre période.
    """
    try:
        import mypuls
    except Exception as e:
        return f"<div class='box' style='border:1px solid rgba(239,68,68,.3)'><p style='color:#ef4444;margin:0;font-size:13px'>❌ Module mypuls indispo : {e}</p></div>"

    from flask import request as flask_request
    import datetime as _dt

    configured = mypuls.is_configured()

    # CSS commun
    css = """
<style>
/* Spinner Insta-style */
.mp-spinner{width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;display:inline-block;animation:mpSpin .7s linear infinite;flex-shrink:0}
@keyframes mpSpin{to{transform:rotate(360deg)}}
.mp-save-btn.loading{cursor:wait;opacity:.85}
.mp-save-btn.loading .mp-save-label{display:none}
.mp-save-btn.loading .mp-spinner{display:inline-block !important}
/* Etat excluded sur avatars + pills */
img.mp-creator-excluded{filter:grayscale(1);opacity:.35}
button.mp-creator-excluded{filter:grayscale(1);opacity:.4;text-decoration:line-through;text-decoration-color:#888}
/* Loading overlay quand on change de période */
.mp-loading-overlay{position:absolute;inset:0;background:rgba(15,17,22,.85);display:none;align-items:center;justify-content:center;border-radius:14px;z-index:10;backdrop-filter:blur(2px)}
.mp-loading-overlay.show{display:flex}
.mp-loading-overlay .mp-big-spinner{width:36px;height:36px;border:3px solid rgba(255,255,255,.15);border-top-color:#3b82f6;border-radius:50%;animation:mpSpin .7s linear infinite}
body.light .mp-loading-overlay{background:rgba(249,250,251,.9)}
.mypuls-section{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px;margin-bottom:20px;position:relative}
.mypuls-section h3{margin:0 0 12px;font-size:15px;display:flex;align-items:center;gap:8px}
.mypuls-stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.mypuls-stat{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:14px 16px}
.mypuls-stat .v{font-size:22px;font-weight:800;letter-spacing:-.02em;line-height:1.1}
.mypuls-stat .l{font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-top:4px;font-weight:600}
.mypuls-tabs{display:flex;gap:6px;border-bottom:1px solid #2a2a2a;margin-bottom:14px}
.mypuls-tab{background:transparent;border:0;color:#888;padding:8px 14px;font-size:13px;font-weight:600;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.mypuls-tab:hover{color:#fff}
.mypuls-tab-active{color:#3b82f6;border-bottom-color:#3b82f6}
.mypuls-table{width:100%;border-collapse:collapse;font-size:12px}
.mypuls-table th{background:#1a1a1a;color:#888;padding:8px 10px;text-align:left;border-bottom:1px solid #2a2a2a;font-size:10px;text-transform:uppercase;letter-spacing:.05em;font-weight:700}
.mypuls-table td{padding:8px 10px;border-bottom:1px solid #1a1a1a;color:#fff;vertical-align:middle}
.mypuls-table tr:hover td{background:rgba(59,130,246,.04)}
.mypuls-bar{position:relative;background:#1a1a1a;height:6px;border-radius:3px;overflow:hidden;margin-top:4px}
.mypuls-bar-fill{position:absolute;top:0;left:0;height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e);border-radius:3px}
.mypuls-pill{display:inline-block;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.mypuls-period{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.mypuls-period-btn{background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.mypuls-period-btn:hover{background:rgba(255,255,255,.05);color:#fff}
.mypuls-period-btn-active{background:#3b82f6;border-color:#3b82f6;color:#fff}
body.light .mypuls-section{background:#fff;border-color:#e5e7eb}
body.light .mypuls-stat{background:#f9fafb;border-color:#e5e7eb}
body.light .mypuls-stat .v{color:#111}
body.light .mypuls-table th{background:#f9fafb;color:#666;border-color:#e5e7eb}
body.light .mypuls-table td{color:#111;border-color:#f3f4f6}
body.light .mypuls-period-btn{color:#666;border-color:#e5e7eb}
body.light .mypuls-period-btn:hover{background:#f3f4f6;color:#111}
body.light .mypuls-tabs{border-color:#e5e7eb}
body.light .mypuls-tab{color:#888}
body.light .mypuls-tab:hover{color:#111}
body.light .mypuls-bar{background:#e5e7eb}
</style>
"""

    if not configured:
        # Pas de cookies : afficher uniquement le form de config
        config_html = (
            "<div class='mypuls-section'>"
            "<h3>"
            "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#3b82f6' stroke-width='2'><circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/></svg>"
            "Sync MyPuls"
            "<span style='font-size:11px;color:#888;font-weight:400;margin-left:6px'>scrape direct du dashboard mypuls.app via tes cookies</span>"
            "</h3>"
            "<div style='padding:14px 16px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.3);border-radius:8px;margin-bottom:14px;font-size:13px;color:#fbbf24'>"
            "⚠ Cookies non configurés. Loggue-toi sur <a href='https://mypuls.app/' target='_blank' style='color:#fbbf24;text-decoration:underline'>mypuls.app</a> et colle tes cookies ci-dessous."
            "</div>"
            "<form method='POST' action='/mypuls/save_cookies' style='display:flex;flex-direction:column;gap:8px;margin-bottom:14px'>"
            "<label style='font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Cookie PHPSESSID (obligatoire)</label>"
            "<input type='password' name='phpsessid' placeholder='9c1f82750ae5104c5d326e57150fe0c9' required minlength='16' style='font-family:monospace;font-size:12px'>"
            "<label style='font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-top:6px'>Cookie REMEMBERME (optionnel, garde la session plus longtemps)</label>"
            "<input type='password' name='rememberme' placeholder='App.Entity.User%3A...' style='font-family:monospace;font-size:11px'>"
            "<button type='submit' style='width:100%;margin-top:8px'>Enregistrer les cookies</button>"
            "</form>"
            "<details style='font-size:12px;color:#888'>"
            "<summary style='cursor:pointer;color:#3b82f6;font-weight:600'>Comment récupérer mes cookies ?</summary>"
            "<ol style='margin:8px 0 0 18px;line-height:1.7'>"
            "<li>Loggue-toi sur <code>mypuls.app</code></li>"
            "<li>Appuie sur <b>F12</b> → onglet <b>Application</b> (Storage)</li>"
            "<li>Côté gauche : <b>Cookies → https://mypuls.app</b></li>"
            "<li>Copie la valeur de <code>PHPSESSID</code> (et <code>REMEMBERME</code> si dispo)</li>"
            "</ol>"
            "</details>"
            "</div>"
        )
        return css + config_html

    # ============ Cookies configurés : afficher les données ============
    # Période : défaut 30j
    today = _dt.date.today()
    default_start = (today - _dt.timedelta(days=29)).isoformat()
    default_end = today.isoformat()
    start_str = flask_request.args.get("mp_start", default_start) if hasattr(flask_request, "args") else default_start
    end_str = flask_request.args.get("mp_end", default_end) if hasattr(flask_request, "args") else default_end

    res = mypuls.fetch_team_stats(start_str, end_str)
    if not res.get("ok"):
        err_html = (
            "<div class='mypuls-section'>"
            "<h3>"
            "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#ef4444' stroke-width='2'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/></svg>"
            "Sync MyPuls — Erreur"
            "</h3>"
            f"<div style='padding:14px 16px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:8px;color:#ef4444;font-size:13px;margin-bottom:14px'>❌ {res.get('error', '?')}</div>"
            "<form method='POST' action='/mypuls/clear_cookies' style='margin:0'>"
            "<button type='submit' style='background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer'>Reset cookies</button>"
            "</form>"
            "</div>"
        )
        return css + err_html

    totals = res["totals"]
    chatters = res["chatters"]
    transactions = res["transactions"]
    max_ca = chatters[0]["ca_total"] if chatters else 1

    # Boutons période (presets + custom) avec loader au clic
    def _preset_url(days):
        s = (today - _dt.timedelta(days=days - 1)).isoformat()
        e = today.isoformat()
        active = "mypuls-period-btn-active" if start_str == s and end_str == e else ""
        return f"<a href='?tab=revenus&mp_start={s}&mp_end={e}' onclick='mpShowPeriodLoader()' class='mypuls-period-btn {active}'>{days}j</a>"

    period_html = (
        "<div class='mypuls-period'>"
        "<span style='font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-right:6px'>Période :</span>"
        + _preset_url(1) + _preset_url(7) + _preset_url(30) + _preset_url(90)
        + "<form method='GET' style='display:inline-flex;gap:6px;align-items:center;margin-left:6px' onsubmit='mpShowPeriodLoader()'>"
        + "<input type='hidden' name='tab' value='revenus'>"
        + f"<input type='date' name='mp_start' value='{start_str}' style='font-size:12px;padding:4px 8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:5px;width:auto'>"
        + "<span style='color:#666;font-size:12px'>→</span>"
        + f"<input type='date' name='mp_end' value='{end_str}' style='font-size:12px;padding:4px 8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:5px;width:auto'>"
        + "<button type='submit' class='mypuls-period-btn'>Filtrer</button>"
        + "</form>"
        + "</div>"
    )

    # Stats grid (avec data-attributes pour update JS)
    stats_html = (
        "<div class='mypuls-stats-grid'>"
        f"<div class='mypuls-stat'><div class='v' data-mp-stat='ca_total' style='color:#22c55e'>+{totals['ca_total']:.0f}€</div><div class='l'>CA Total</div></div>"
        f"<div class='mypuls-stat'><div class='v' data-mp-stat='ca_ppv' style='color:#3b82f6'>{totals['ca_ppv']:.0f}€</div><div class='l'>CA PPV</div></div>"
        f"<div class='mypuls-stat'><div class='v' data-mp-stat='ca_tips' style='color:#a855f7'>{totals['ca_tips']:.0f}€</div><div class='l'>CA Tips</div></div>"
        f"<div class='mypuls-stat'><div class='v' data-mp-stat='nb_tx'>{totals['nb_transactions']}</div><div class='l'>Transactions</div></div>"
        f"<div class='mypuls-stat'><div class='v' data-mp-stat='active_chatters'>{totals['active_chatters']}<span style='font-size:14px;color:#666'>/{totals['nb_chatters']}</span></div><div class='l'>Chatteurs actifs</div></div>"
        "</div>"
    )

    # ============ Graphique évolution revenus par créateur ============
    chart_data = res.get("chart", {"days": [], "datasets": []})
    chart_days = chart_data["days"]
    chart_datasets = chart_data["datasets"]

    # Palette de couleurs distinctes pour les créateurs
    palette = ["#22c55e", "#3b82f6", "#a855f7", "#f59e0b", "#ec4899",
               "#06b6d4", "#ef4444", "#84cc16", "#f97316", "#8b5cf6"]

    # Format date pour l'axe X : "30 avr"
    import datetime as _dt2
    def _fmt_day(iso):
        try:
            d = _dt2.date.fromisoformat(iso)
            fr_months = ["janv","févr","mars","avr","mai","juin","juil","août","sept","oct","nov","déc"]
            return f"{d.day} {fr_months[d.month-1]}"
        except Exception:
            return iso
    chart_labels = [_fmt_day(d) for d in chart_days]

    # Récupérer le mapping name -> id pour les avatars
    creators_map: dict = {}
    try:
        cr_res = mypuls.list_creators()
        if cr_res.get("ok"):
            creators_map = cr_res.get("creators") or {}
    except Exception:
        pass

    # Construire les datasets pour Chart.js
    import json as _json
    chartjs_datasets = []
    legend_items = []
    avatars_header = []
    for i, ds in enumerate(chart_datasets):
        color = palette[i % len(palette)]
        chartjs_datasets.append({
            "label": ds["label"],
            "data": ds["data"],
            "borderColor": color,
            "backgroundColor": color + "20",
            "fill": True,
            "tension": 0.4,
            "borderWidth": 2,
            "pointRadius": 0,
            "pointHoverRadius": 4,
        })
        creator_id = creators_map.get(ds["label"])
        ds_label = ds["label"]
        ds_total = ds["total"]
        if creator_id:
            avatar_img = (
                f"<img src='/mypuls/avatar/{creator_id}' alt='{ds_label}' "
                f"title='Clic pour activer / désactiver {ds_label}' "
                f"onclick=\"mpToggleCreator('{ds_label.replace(chr(39), chr(92)+chr(39))}')\" "
                f"data-mp-avatar='{ds_label}' "
                f"style='width:32px;height:32px;border-radius:50%;object-fit:cover;border:2px solid {color};margin-left:-8px;cursor:pointer;transition:filter .2s,opacity .2s' loading='lazy'>"
            )
            avatars_header.append(avatar_img)
            avatar_legend = (
                f"<img src='/mypuls/avatar/{creator_id}' style='width:18px;height:18px;border-radius:50%;object-fit:cover;border:1px solid {color}'>"
            )
        else:
            avatar_legend = f"<span style='width:8px;height:8px;background:{color};border-radius:50%;display:inline-block'></span>"
        ds_label_safe = ds_label.replace("'", "\\'")
        legend_items.append(
            f"<button type='button' onclick=\"mpToggleCreator('{ds_label_safe}')\" "
            f"data-mp-legend='{ds_label}' "
            f"style='display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 4px;background:{color}15;border:1px solid {color}40;border-radius:20px;font-size:11px;font-weight:600;color:inherit;cursor:pointer;font-family:inherit;transition:all .2s'>"
            f"{avatar_legend}"
            f"{ds['label']} <span style='color:#888;font-weight:400'>{ds['total']:.0f}€</span>"
            f"</button>"
        )

    avatars_header_html = (
        f"<div style='display:flex;align-items:center;margin-left:14px'>{''.join(avatars_header)}</div>"
        if avatars_header else ""
    )

    chart_json = _json.dumps({"labels": chart_labels, "datasets": chartjs_datasets}, ensure_ascii=False)

    if chart_datasets:
        plural_s = "s" if len(chart_datasets) > 1 else ""
        chart_html = (
            "<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:16px;margin-bottom:14px'>"
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:10px'>"
            "<div style='display:flex;align-items:center;gap:8px;font-weight:700;font-size:14px'>"
            "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='#22c55e' stroke-width='2.5'><polyline points='22 12 18 12 15 21 9 3 6 12 2 12'/></svg>"
            "Évolution des revenus par modèle"
            + avatars_header_html +
            "</div>"
            f"<div style='font-size:11px;color:#888'>{len(chart_datasets)} modèle{plural_s} actif{plural_s}</div>"
            "</div>"
            "<div style='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px'>"
            + "".join(legend_items) +
            "</div>"
            "<div style='position:relative;height:340px'>"
            "<canvas id='mypuls-chart'></canvas>"
            "</div>"
            "</div>"
        )
        # JS d'initialisation du chart (déclenché après le DOM)
        chart_init_js = f"""
<script>
(function(){{
  var data = {chart_json};
  function initChart(){{
    var canvas = document.getElementById('mypuls-chart');
    if(!canvas || typeof Chart === 'undefined'){{ setTimeout(initChart, 100); return; }}
    if(window.__mypulsChart){{ try{{ window.__mypulsChart.destroy(); }}catch(e){{}} }}
    var isDark = !document.body.classList.contains('light');
    var gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
    var textColor = isDark ? '#888' : '#666';
    window.__mypulsChart = new Chart(canvas, {{
      type: 'line',
      data: data,
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: isDark ? '#0f1116' : '#fff',
            titleColor: isDark ? '#fff' : '#111',
            bodyColor: isDark ? '#aaa' : '#555',
            borderColor: '#2a2a2a',
            borderWidth: 1,
            padding: 12,
            callbacks: {{
              label: function(ctx){{
                return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '€';
              }}
            }}
          }}
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            grid: {{ color: gridColor }},
            ticks: {{ color: textColor, callback: function(v){{ return v.toFixed(0)+'€'; }} }}
          }},
          x: {{
            grid: {{ display: false }},
            ticks: {{ color: textColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }}
          }}
        }}
      }}
    }});
  }}
  initChart();
}})();
</script>
"""
    else:
        chart_html = ""
        chart_init_js = ""

    # Helper pour insérer un nom comme arg JS dans un onclick="..." HTML.
    # On utilise &quot; pour les guillemets pour pas casser le parsing HTML.
    def _json_escape(s: str) -> str:
        import json as _js
        return _js.dumps(s).replace('"', "&quot;")

    # Récupérer le taux EUR -> USD (cache 24h)
    rate_info = mypuls.get_eur_usd_rate()
    eur_to_usd = rate_info["rate"]

    # Table chatteurs (top 30) — avec % commission, à payer en USD, screenshot crypto
    chatters_rows = []
    for i, c in enumerate(chatters[:30]):
        bar_pct = (c["ca_total"] / max_ca * 100) if max_ca else 0
        name_esc = c["name"].replace("<", "&lt;").replace(">", "&gt;")
        meta = mypuls.get_chatter_meta(c["name"])
        commission = meta["commission_pct"]
        to_pay_eur = round(c["ca_total"] * commission / 100, 2)
        to_pay = round(to_pay_eur * eur_to_usd, 2)
        has_crypto = bool(meta["crypto_file"]) or bool(meta["crypto_address"])
        has_screenshot = bool(meta.get("crypto_file"))
        crypto_type = meta.get("crypto_type") or ""
        crypto_network = meta.get("crypto_network") or ""
        crypto_address = meta.get("crypto_address") or ""
        addr_short = (crypto_address[:6] + "…" + crypto_address[-4:]) if len(crypto_address) > 14 else crypto_address

        # Couleur du badge selon la crypto
        type_color = {
            "USDC": "#2775ca",
            "ETH": "#627eea",
            "SOL": "#9945ff",
            "TRX": "#ef4444",
        }.get(crypto_type, "#888")

        name_url_safe = c["name"].replace(" ", "%20")

        # Thumbnail screenshot (preview direct dans la cellule + hover = enlarge)
        if has_screenshot:
            thumb_html = (
                f"<div class='mp-crypto-thumb' style='position:relative;display:inline-block'>"
                f"<img src='/mypuls/chatter/crypto/{name_url_safe}' "
                f"style='width:38px;height:38px;border-radius:6px;object-fit:cover;border:1px solid #2a2a2a;cursor:zoom-in;display:block' "
                f"onclick=\"event.stopPropagation();mpEnlargeImg(this.src)\">"
                f"</div>"
            )
        else:
            thumb_html = (
                "<div style='width:38px;height:38px;border-radius:6px;border:1px dashed #2a2a2a;display:flex;align-items:center;justify-content:center;color:#444'>"
                "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.5'><rect x='3' y='3' width='18' height='18' rx='2'/><circle cx='9' cy='9' r='2'/><polyline points='21 15 16 10 5 21'/></svg>"
                "</div>"
            )

        # Info crypto (badge type + reseau + adresse + copier) ou bouton configurer
        if crypto_type:
            addr_full_safe = crypto_address.replace("'", "\\'").replace('"', '\\"')
            copy_btn = (
                f"<button type='button' onclick=\"mpCopyAddr('{addr_full_safe}', this);event.stopPropagation()\" "
                f"title='Copier l\\'adresse complète' "
                f"style='background:transparent;border:0;color:#888;cursor:pointer;padding:2px 4px;font-size:10px;display:inline-flex;align-items:center;gap:3px'>"
                f"<svg viewBox='0 0 24 24' width='11' height='11' fill='none' stroke='currentColor' stroke-width='2'><rect x='9' y='9' width='13' height='13' rx='2'/><path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/></svg>"
                f"</button>"
            ) if crypto_address else ""
            info_html = (
                f"<div style='display:flex;flex-direction:column;gap:2px;align-items:flex-start;min-width:0;flex:1'>"
                f"<div style='display:flex;align-items:center;gap:6px;flex-wrap:wrap'>"
                f"<span style='background:{type_color};color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:.04em'>{crypto_type}</span>"
                + (f"<span style='font-size:10px;color:#888'>{crypto_network.split('(')[0].strip()}</span>" if crypto_network else "")
                + "</div>"
                + (
                    f"<div style='display:flex;align-items:center;gap:2px;max-width:140px'>"
                    f"<span style='font-family:monospace;font-size:10px;color:#aaa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{addr_short}</span>"
                    f"{copy_btn}"
                    f"</div>"
                    if addr_short else ""
                )
                + "</div>"
            )
        else:
            info_html = (
                "<div style='flex:1;font-size:11px;color:#666'>Pas configuré</div>"
            )

        # Tout dans un row cliquable qui toggle l'edit inline
        crypto_cell = (
            f"<div style='display:flex;align-items:center;gap:8px'>"
            f"{thumb_html}"
            f"{info_html}"
            f"<button onclick=\"mpToggleEdit({_json_escape(c['name'])})\" "
            f"style='background:transparent;border:1px solid #2a2a2a;color:#888;padding:4px 8px;border-radius:6px;font-size:11px;cursor:pointer'>"
            f"✏️</button>"
            f"</div>"
        )
        # Construire le bloc edit inline (caché par défaut)
        chatter_name_safe = c["name"].replace("'", "&#39;")
        edit_inline = (
            f"<tr id='mp-edit-row-{i}' class='mp-edit-row' data-chatter='{chatter_name_safe}' style='display:none'>"
            f"<td colspan='9' style='background:#0f1116;border-top:0;padding:18px 20px'>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:760px'>"
            # Colonne gauche : type + reseau + adresse
            f"<form method='POST' action='/mypuls/chatter/set_crypto' style='display:flex;flex-direction:column;gap:10px'>"
            f"<input type='hidden' name='name' value='{name_esc}'>"
            f"<div><label style='font-size:10px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Réseau</label>"
            f"<select name='crypto_type' class='mp-edit-type' data-row='{i}' onchange='mpUpdateInlineNetworks({i})' style='margin-top:4px;width:100%'>"
            f"<option value=''>—</option>"
            + "".join(
                f"<option value='{t}'{' selected' if crypto_type==t else ''}>{t}</option>"
                for t in ["USDC", "ETH", "SOL", "TRX"]
            )
            + f"</select></div>"
            f"<div><label style='font-size:10px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Blockchain</label>"
            f"<select name='crypto_network' class='mp-edit-network' data-row='{i}' data-saved=\"{crypto_network.replace(chr(34), '&quot;')}\" style='margin-top:4px;width:100%'>"
            f"<option value=''>Choisis d'abord un réseau</option>"
            f"</select></div>"
            f"<div><label style='font-size:10px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Adresse</label>"
            f"<div style='display:flex;gap:6px;margin-top:4px;align-items:stretch'>"
            f"<input type='text' name='crypto_address' value='{crypto_address.replace(chr(39), '&#39;')}' placeholder='0x… / T… / …' style='flex:1;font-family:monospace;font-size:12px'>"
            + (
                f"<button type='button' onclick=\"mpCopyAddr('{crypto_address.replace(chr(39), chr(92)+chr(39))}', this)\" "
                f"style='background:transparent;border:1px solid #2a2a2a;color:#888;padding:0 10px;border-radius:6px;font-size:11px;cursor:pointer;display:inline-flex;align-items:center;gap:4px' title='Copier'>"
                f"<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2'><rect x='9' y='9' width='13' height='13' rx='2'/><path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/></svg>"
                f"</button>"
                if crypto_address else ""
            )
            + "</div></div>"
            f"<button type='submit' class='mp-save-btn' style='background:#3b82f6;color:#fff;border:0;padding:10px;border-radius:6px;font-weight:600;cursor:pointer;font-size:12px;margin-top:4px;display:flex;align-items:center;justify-content:center;gap:8px;min-height:38px'>"
            f"<span class='mp-save-label'>Enregistrer</span>"
            f"<span class='mp-spinner' style='display:none'></span>"
            f"</button>"
            f"</form>"
            # Colonne droite : screenshot + actions
            f"<div style='display:flex;flex-direction:column;gap:10px'>"
            + (
                f"<div style='position:relative'><img src='/mypuls/chatter/crypto/{name_url_safe}?t=now' style='width:100%;max-height:200px;object-fit:contain;border-radius:8px;border:1px solid #2a2a2a;background:#000'></div>"
                if has_screenshot else
                "<div style='border:2px dashed #2a2a2a;border-radius:8px;padding:40px 20px;text-align:center;color:#666;font-size:12px'>Pas de screenshot</div>"
            )
            + f"<form method='POST' action='/mypuls/chatter/upload_crypto' enctype='multipart/form-data' style='margin:0'>"
            f"<input type='hidden' name='name' value='{name_esc}'>"
            f"<label style='display:block;background:transparent;border:1px dashed #2a2a2a;color:#888;padding:8px;border-radius:6px;cursor:pointer;text-align:center;font-size:12px'>📷 "
            + ("Changer le screenshot" if has_screenshot else "Upload un screenshot")
            + f"<input type='file' name='file' accept='image/*' onchange='this.form.submit()' style='display:none'></label>"
            f"</form>"
            + (
                f"<form method='POST' action='/mypuls/chatter/delete_crypto' style='margin:0'>"
                f"<input type='hidden' name='name' value='{name_esc}'>"
                f"<button type='submit' data-confirm='Cette action est irréversible.' data-confirm-title='Supprimer le screenshot ?' style='width:100%;background:transparent;border:1px solid rgba(239,68,68,.3);color:#ef4444;padding:7px;border-radius:6px;font-size:11px;cursor:pointer'>🗑 Supprimer le screenshot</button>"
                f"</form>"
                if has_screenshot else ""
            )
            + "</div>"
            f"</div></td></tr>"
        )

        chatters_rows.append(
            f"<tr data-chatter-row='{i}' data-chatter='{name_esc}' class='mp-chatter-row'>"
            f"<td><div style='font-weight:600'>{name_esc}</div>"
            f"<div class='mypuls-bar' style='width:140px'><div class='mp-bar-fill mypuls-bar-fill' data-max='{max_ca}' style='width:{bar_pct:.1f}%'></div></div></td>"
            f"<td class='mp-cell-ca-total' style='font-weight:700;color:#22c55e'>{c['ca_total']:.2f}€</td>"
            f"<td class='mp-cell-ca-ppv' style='color:#3b82f6'>{c['ca_ppv']:.2f}€</td>"
            f"<td class='mp-cell-ca-tips' style='color:#a855f7'>{c['ca_tips']:.2f}€</td>"
            f"<td><span class='mypuls-pill' style='background:rgba(255,255,255,.05);color:#aaa'>{c['conv_rate']}</span></td>"
            f"<td>"
            f"<form method='POST' action='/mypuls/chatter/set_pct' style='display:inline-flex;align-items:center;gap:4px;margin:0' onchange='this.submit()'>"
            f"<input type='hidden' name='name' value='{name_esc}'>"
            f"<input type='number' name='pct' value='{commission:g}' min='0' max='100' step='1' style='width:60px;padding:4px 6px;background:#0f1116;border:1px solid #2a2a2a;color:#fff;border-radius:5px;font-size:12px;text-align:right'>"
            f"<span style='color:#888;font-size:11px'>%</span>"
            f"</form>"
            f"</td>"
            f"<td class='mp-cell-pay' style='font-weight:700;color:{'#22c55e' if to_pay > 0 else '#444'};font-size:13px' title='≈ {to_pay_eur:.2f}€ × {eur_to_usd:.4f}'>${to_pay:.2f}</td>"
            f"<td>{crypto_cell}</td>"
            f"<td style='color:#888;font-size:11px'>{c['presence']}</td>"
            f"</tr>"
            + edit_inline
        )
    chatters_empty = "<tr><td colspan='9' style='text-align:center;padding:30px;color:#888'>Aucun chatteur actif sur la période</td></tr>"
    chatters_body = "".join(chatters_rows) or chatters_empty

    # Total à payer (somme des "à payer" sur les 30 affichés)
    total_to_pay_eur = sum(
        round(c["ca_total"] * mypuls.get_chatter_meta(c["name"])["commission_pct"] / 100, 2)
        for c in chatters[:30]
    )
    total_to_pay_usd = round(total_to_pay_eur * eur_to_usd, 2)

    # Indicateur de fraîcheur du taux
    rate_age = rate_info.get("cached_age_h", 0)
    if rate_info.get("source") == "fallback":
        rate_color = "#ef4444"
        rate_label = "fallback (API down)"
    elif rate_info.get("source") == "stale_cache":
        rate_color = "#fbbf24"
        rate_label = f"cache vieux de {rate_age:.0f}h"
    else:
        rate_color = "#888"
        rate_label = f"BCE {rate_info.get('date', '?')}"

    payout_summary = (
        "<div style='padding:12px 14px;background:rgba(34,197,94,.05);border:1px solid rgba(34,197,94,.2);border-radius:8px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>"
        "<div style='display:flex;flex-direction:column;gap:2px'>"
        "<div style='font-size:13px;color:#888'>💰 Total à payer aux chatteurs sur cette période</div>"
        f"<div style='font-size:10px;color:{rate_color};font-weight:600'>Taux EUR→USD : 1€ = {eur_to_usd:.4f}$ <span style='color:#666'>({rate_label})</span> "
        "<form method='POST' action='/mypuls/refresh_rate' style='display:inline;margin-left:6px'>"
        "<button type='submit' style='background:transparent;border:0;color:#3b82f6;font-size:10px;cursor:pointer;padding:0;text-decoration:underline'>↻ MAJ taux</button>"
        "</form>"
        "</div>"
        "</div>"
        "<div style='text-align:right'>"
        f"<div data-mp-stat='total_pay_usd' style='font-weight:800;font-size:22px;color:#22c55e'>${total_to_pay_usd:.2f}</div>"
        f"<div data-mp-stat='total_pay_eur' style='font-size:11px;color:#666'>≈ {total_to_pay_eur:.2f}€</div>"
        "</div>"
        "</div>"
    )

    # Construire la map JSON {chatter: {type, network, address, has_screenshot, commission}}
    import json as _json_mod
    crypto_data_js = {}
    for c in chatters[:30]:
        m = mypuls.get_chatter_meta(c["name"])
        crypto_data_js[c["name"]] = {
            "type": m.get("crypto_type", "") or "",
            "network": m.get("crypto_network", "") or "",
            "address": m.get("crypto_address", "") or "",
            "has_screenshot": bool(m.get("crypto_file")),
            "commission_pct": float(m.get("commission_pct", 0)),
        }
    networks_js = _json_mod.dumps(mypuls.CRYPTO_NETWORKS, ensure_ascii=False)
    crypto_data_json = _json_mod.dumps(crypto_data_js, ensure_ascii=False)

    # Exposer les transactions à JS pour le filtre client-side par modèle
    transactions_js = _json_mod.dumps(
        [{"c": t["creator"], "h": t["chatter"], "a": t["amount"], "y": t["type"]} for t in transactions],
        ensure_ascii=False,
    )
    # Liste des chatteurs avec leur présence/réactivité (stats non-recalculables côté client)
    chatters_base_js = _json_mod.dumps(
        [{"name": c["name"], "presence": c["presence"], "conv_rate": c["conv_rate"]} for c in chatters[:50]],
        ensure_ascii=False,
    )

    chatters_table = (
        "<div id='mp-tab-chatters' style='display:block'>"
        + payout_summary +
        "<table class='mypuls-table'>"
        "<thead><tr><th>Chatteur</th><th>CA Total</th><th>PPV</th><th>Tips</th><th>Conv.</th><th>%</th><th>À payer ($)</th><th>Crypto</th><th>Présence</th></tr></thead>"
        f"<tbody>{chatters_body}</tbody>"
        "</table>"
        f"<script>window.__mpCryptoData = {crypto_data_json};</script>"
        f"<script>window.__mpNetworks = {networks_js};</script>"
        f"<script>window.__mpTransactions = {transactions_js};</script>"
        f"<script>window.__mpChattersBase = {chatters_base_js};</script>"
        f"<script>window.__mpEurToUsd = {eur_to_usd};</script>"
        "</div>"
    )

    # Table transactions (recent 50)
    tx_rows = []
    for t in transactions[:50]:
        type_color = {
            "Média privé": "#3b82f6",
            "Pourboires": "#a855f7",
            "Abonnement": "#22c55e",
        }.get(t["type"], "#888")
        tx_rows.append(
            f"<tr>"
            f"<td style='color:#888;font-size:11px;white-space:nowrap'>{t['date']}</td>"
            f"<td style='font-weight:600'>{t['creator']}</td>"
            f"<td style='color:#3b82f6'>{t['chatter']}</td>"
            f"<td style='color:#888'>{t['fan']}</td>"
            f"<td style='font-weight:700;color:#22c55e'>+{t['amount']:.2f}€</td>"
            f"<td><span class='mypuls-pill' style='background:rgba({251 if t['type']=='Pourboires' else 59},{191 if t['type']=='Pourboires' else 130},{36 if t['type']=='Pourboires' else 246},.15);color:{type_color}'>{t['type']}</span></td>"
            f"</tr>"
        )
    tx_empty = "<tr><td colspan='6' style='text-align:center;padding:30px;color:#888'>Aucune transaction</td></tr>"
    tx_body = "".join(tx_rows) or tx_empty
    tx_table = (
        "<div id='mp-tab-tx' style='display:none'>"
        "<table class='mypuls-table'>"
        "<thead><tr><th>Date</th><th>Créateur</th><th>Chatteur</th><th>Fan</th><th>Montant</th><th>Type</th></tr></thead>"
        f"<tbody>{tx_body}</tbody>"
        "</table>"
        "</div>"
    )

    tabs_html = (
        "<div class='mypuls-tabs'>"
        f"<button class='mypuls-tab mypuls-tab-active' onclick='mpTab(this,\"chatters\")'>Top chatteurs ({totals['active_chatters']})</button>"
        f"<button class='mypuls-tab' onclick='mpTab(this,\"tx\")'>Transactions ({totals['nb_transactions']})</button>"
        "<div style='flex:1'></div>"
        "<form method='POST' action='/mypuls/clear_cookies' style='margin:0;align-self:center' onsubmit='return confirm(\"Supprimer les cookies MyPuls ?\")'>"
        "<button type='submit' style='background:transparent;border:0;color:#888;font-size:11px;cursor:pointer;padding:4px 8px'>Reset cookies</button>"
        "</form>"
        "</div>"
    )

    js = """
<script>
function mpTab(btn, name){
  document.querySelectorAll('.mypuls-tab').forEach(function(t){t.classList.remove('mypuls-tab-active');});
  btn.classList.add('mypuls-tab-active');
  document.getElementById('mp-tab-chatters').style.display = (name === 'chatters') ? 'block' : 'none';
  document.getElementById('mp-tab-tx').style.display = (name === 'tx') ? 'block' : 'none';
}
function mpUpdateInlineNetworks(rowIdx){
  var typeSel = document.querySelector('.mp-edit-type[data-row="'+rowIdx+'"]');
  var netSel = document.querySelector('.mp-edit-network[data-row="'+rowIdx+'"]');
  if(!typeSel || !netSel) return;
  var t = typeSel.value;
  var nets = (window.__mpNetworks || {})[t] || [];
  var savedNet = netSel.getAttribute('data-saved') || netSel.value || '';
  netSel.innerHTML = '';
  if(!t){
    netSel.innerHTML = '<option value="">Choisis d\\'abord un réseau</option>';
    return;
  }
  nets.forEach(function(n){
    var opt = document.createElement('option');
    opt.value = n;
    opt.textContent = n;
    if(n === savedNet) opt.selected = true;
    netSel.appendChild(opt);
  });
}
function mpToggleEdit(chatterName){
  // Cherche la row d'edit qui matche ce chatter
  var rows = document.querySelectorAll('.mp-edit-row');
  rows.forEach(function(r){
    if(r.getAttribute('data-chatter') === chatterName){
      r.style.display = (r.style.display === 'none' || !r.style.display) ? 'table-row' : 'none';
      if(r.style.display === 'table-row'){
        // Init networks pour cette row
        var typeSel = r.querySelector('.mp-edit-type');
        if(typeSel) mpUpdateInlineNetworks(typeSel.getAttribute('data-row'));
      }
    } else {
      r.style.display = 'none';
    }
  });
}
window.__mpExcluded = window.__mpExcluded || new Set();

function mpToggleCreator(name){
  if(window.__mpExcluded.has(name)) window.__mpExcluded.delete(name);
  else window.__mpExcluded.add(name);
  mpUpdateVisualState();
  mpRecompute();
}
function mpUpdateVisualState(){
  // Avatars dans le header
  document.querySelectorAll('[data-mp-avatar]').forEach(function(el){
    var n = el.getAttribute('data-mp-avatar');
    if(window.__mpExcluded.has(n)) el.classList.add('mp-creator-excluded');
    else el.classList.remove('mp-creator-excluded');
  });
  // Pills légende
  document.querySelectorAll('[data-mp-legend]').forEach(function(el){
    var n = el.getAttribute('data-mp-legend');
    if(window.__mpExcluded.has(n)) el.classList.add('mp-creator-excluded');
    else el.classList.remove('mp-creator-excluded');
  });
}
function mpRecompute(){
  var excluded = window.__mpExcluded;
  var txs = window.__mpTransactions || [];
  var rate = window.__mpEurToUsd || 1;
  // Filtrer les transactions
  var filtered = txs.filter(function(t){ return !excluded.has(t.c); });
  // Agréger par chatteur
  var byChat = {};
  var totals = {ca_total: 0, ca_ppv: 0, ca_tips: 0, nb_tx: filtered.length};
  filtered.forEach(function(t){
    totals.ca_total += t.a;
    if(t.y === 'Média privé' || (t.y && t.y.indexOf('PPV') >= 0)) totals.ca_ppv += t.a;
    else if(t.y === 'Pourboires' || (t.y && t.y.indexOf('Tip') >= 0)) totals.ca_tips += t.a;
    var n = t.h || '?';
    if(!byChat[n]) byChat[n] = {ca_total:0, ca_ppv:0, ca_tips:0};
    byChat[n].ca_total += t.a;
    if(t.y === 'Média privé') byChat[n].ca_ppv += t.a;
    else if(t.y === 'Pourboires') byChat[n].ca_tips += t.a;
  });
  // Update stat cards
  var setStat = function(key, val){
    var el = document.querySelector('[data-mp-stat="'+key+'"]');
    if(el) el.firstChild ? el.firstChild.nodeValue = val : el.textContent = val;
  };
  var statCa = document.querySelector('[data-mp-stat="ca_total"]');
  if(statCa) statCa.textContent = '+' + Math.round(totals.ca_total) + '€';
  var statPpv = document.querySelector('[data-mp-stat="ca_ppv"]');
  if(statPpv) statPpv.textContent = Math.round(totals.ca_ppv) + '€';
  var statTips = document.querySelector('[data-mp-stat="ca_tips"]');
  if(statTips) statTips.textContent = Math.round(totals.ca_tips) + '€';
  var statTx = document.querySelector('[data-mp-stat="nb_tx"]');
  if(statTx) statTx.textContent = totals.nb_tx;

  // Update chart - cacher les datasets exclus
  if(window.__mypulsChart){
    window.__mypulsChart.data.datasets.forEach(function(ds){
      var meta = window.__mypulsChart.getDatasetMeta(window.__mypulsChart.data.datasets.indexOf(ds));
      meta.hidden = excluded.has(ds.label);
    });
    window.__mypulsChart.update('none');
  }

  // Update table chatteurs
  var rows = document.querySelectorAll('.mp-chatter-row');
  var activeCount = 0;
  // Calculer le nouveau max pour les barres
  var newMax = 0;
  Object.keys(byChat).forEach(function(n){ if(byChat[n].ca_total > newMax) newMax = byChat[n].ca_total; });
  if(newMax === 0) newMax = 1;
  // Trier les chatteurs par ca_total desc - on doit re-ordonner les rows
  var sortedChatters = Object.keys(byChat).filter(function(n){ return byChat[n].ca_total > 0; })
    .sort(function(a,b){ return byChat[b].ca_total - byChat[a].ca_total; });
  var sortedSet = {};
  sortedChatters.forEach(function(n, idx){ sortedSet[n] = idx; });

  var totalPayUsd = 0;
  rows.forEach(function(row){
    var name = row.getAttribute('data-chatter');
    var data = byChat[name];
    if(!data || data.ca_total <= 0){
      row.style.display = 'none';
      var nextRow = row.nextElementSibling;
      if(nextRow && nextRow.classList.contains('mp-edit-row')) nextRow.style.display = 'none';
      return;
    }
    activeCount++;
    row.style.display = '';
    var cellTotal = row.querySelector('.mp-cell-ca-total');
    if(cellTotal) cellTotal.textContent = data.ca_total.toFixed(2) + '€';
    var cellPpv = row.querySelector('.mp-cell-ca-ppv');
    if(cellPpv) cellPpv.textContent = data.ca_ppv.toFixed(2) + '€';
    var cellTips = row.querySelector('.mp-cell-ca-tips');
    if(cellTips) cellTips.textContent = data.ca_tips.toFixed(2) + '€';
    // Bar
    var bar = row.querySelector('.mp-bar-fill');
    if(bar) bar.style.width = (data.ca_total / newMax * 100).toFixed(1) + '%';
    // Commission + à payer
    var pct = (window.__mpCryptoData[name] && window.__mpCryptoData[name].commission_pct) || 0;
    var payEur = data.ca_total * pct / 100;
    var payUsd = payEur * rate;
    totalPayUsd += payUsd;
    var cellPay = row.querySelector('.mp-cell-pay');
    if(cellPay){
      cellPay.textContent = '$' + payUsd.toFixed(2);
      cellPay.style.color = payUsd > 0 ? '#22c55e' : '#444';
    }
  });
  // Update active chatters stat
  var statActive = document.querySelector('[data-mp-stat="active_chatters"]');
  if(statActive){
    statActive.innerHTML = activeCount + '<span style="font-size:14px;color:#666">/' + (window.__mpChattersBase || []).length + '</span>';
  }
  // Update total à payer
  var totalUsdEl = document.querySelector('[data-mp-stat="total_pay_usd"]');
  if(totalUsdEl) totalUsdEl.textContent = '$' + totalPayUsd.toFixed(2);
  var totalEurEl = document.querySelector('[data-mp-stat="total_pay_eur"]');
  if(totalEurEl) totalEurEl.textContent = '≈ ' + (totalPayUsd / rate).toFixed(2) + '€';
}
function mpShowPeriodLoader(){
  var ov = document.getElementById('mp-loading');
  if(ov) ov.classList.add('show');
}
function mpCopyAddr(addr, btn){
  if(!navigator.clipboard){
    // Fallback
    var ta = document.createElement('textarea');
    ta.value = addr;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch(e){}
    document.body.removeChild(ta);
  } else {
    navigator.clipboard.writeText(addr);
  }
  // Feedback visuel
  var orig = btn.innerHTML;
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="#22c55e" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
  btn.style.color = '#22c55e';
  setTimeout(function(){
    btn.innerHTML = orig;
    btn.style.color = '';
  }, 1200);
  if(typeof showToast === 'function') showToast('Adresse copiée', 'success');
}
function mpEnlargeImg(src){
  // Overlay plein écran avec l'image agrandie
  var ov = document.createElement('div');
  ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:99999;display:flex;align-items:center;justify-content:center;padding:30px;cursor:zoom-out';
  ov.innerHTML = '<img src="' + src + '" style="max-width:100%;max-height:100%;border-radius:8px;box-shadow:0 0 60px rgba(0,0,0,.8)">';
  ov.onclick = function(){ document.body.removeChild(ov); };
  document.body.appendChild(ov);
}
// Init des dropdowns réseaux pour chaque row au load
document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('.mp-edit-network').forEach(function(sel){
    var rowIdx = sel.getAttribute('data-row');
    var typeSel = document.querySelector('.mp-edit-type[data-row="'+rowIdx+'"]');
    if(!typeSel || !typeSel.value) return;
    sel.setAttribute('data-saved', (window.__mpCryptoData_byRow || {})[rowIdx] || '');
    mpUpdateInlineNetworks(rowIdx);
  });
  // Spinner sur tous les boutons Save MyPuls quand le form est submit
  document.querySelectorAll('.mp-save-btn').forEach(function(btn){
    var form = btn.closest('form');
    if(form){
      form.addEventListener('submit', function(){
        btn.classList.add('loading');
        btn.disabled = true;
      });
    }
  });
});
</script>
"""

    # Indicateur cookies auto-refresh
    age_h = mypuls.last_refresh_age_hours()
    if age_h is None:
        refresh_status = "<span style='color:#888'>Cookies frais (pas encore rafraîchis)</span>"
    elif age_h < 1:
        refresh_status = f"<span style='color:#22c55e'>● Cookies auto-renouvelés il y a {int(age_h*60)} min</span>"
    elif age_h < 24:
        refresh_status = f"<span style='color:#22c55e'>● Cookies auto-renouvelés il y a {age_h:.1f}h</span>"
    elif age_h < 24 * 7:
        refresh_status = f"<span style='color:#fbbf24'>● Cookies pas renouvelés depuis {age_h/24:.1f}j</span>"
    else:
        refresh_status = f"<span style='color:#ef4444'>● Cookies pas renouvelés depuis {age_h/24:.0f}j</span>"

    keepalive_info = (
        f"<div style='font-size:11px;color:#666;margin-top:10px;padding:8px 12px;background:rgba(34,197,94,.05);border:1px solid rgba(34,197,94,.15);border-radius:6px'>"
        f"🔄 <strong>Auto-refresh actif</strong> : le bot ping MyPuls toutes les 12h pour prolonger ton cookie REMEMBERME automatiquement — tant que tu changes pas ton mot de passe MyPuls, ça reste connecté pour toujours. {refresh_status}"
        f"</div>"
    )

    section = (
        "<div class='mypuls-section'>"
        "<div class='mp-loading-overlay' id='mp-loading'><div class='mp-big-spinner'></div></div>"
        "<h3>"
        "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#3b82f6' stroke-width='2'><path d='M3 3v18h18'/><path d='M7 14l4-4 4 4 5-5'/></svg>"
        "MyPuls — Ventes chatteurs"
        f"<span style='font-size:11px;color:#888;font-weight:400;margin-left:6px'>scrape direct mypuls.app · {start_str} → {end_str}</span>"
        "</h3>"
        + period_html + stats_html + chart_html + tabs_html + chatters_table + tx_table + keepalive_info
        + "</div>"
    )
    return css + section + js + chart_init_js


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
    # ============ MyPuls sync en haut ============
    rows.append(_render_mypuls_section_html())
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


def _render_biolinks_html() -> str:
    """Page de gestion des bio links pour toutes les identités."""
    try:
        from bio_links import get_bio, stats
    except Exception as e:
        return f"<p style='color:#f99'>Module bio_links indispo : {e}</p>"
    identities = _list_identities()
    s = stats()
    rows = []
    rows.append(
        "<div class='stat-grid' style='margin-bottom:18px'>"
        f"<div class='stat'><div class='v'>{s['nb_idents_with_bio']}</div><div class='l'>Identités avec bio</div></div>"
        f"<div class='stat'><div class='v'>{s['nb_total_links']}</div><div class='l'>Liens totaux</div></div>"
        f"<div class='stat'><div class='v'>{len(identities)}</div><div class='l'>Identités disponibles</div></div>"
        "</div>"
    )
    if not identities:
        rows.append("<p style='color:#888'>Aucune identité créée. Crée-en sur Discord.</p>")
        return "".join(rows)
    rows.append(
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px'>"
    )
    for ident in identities:
        bio = get_bio(ident)
        nb_links = len(bio.get("links", []))
        avatar = _identity_avatar_html(ident, size=48)
        display_name = bio.get("display_name") or ident
        bio_text = bio.get("bio") or ""
        public_url = f"/bio/{ident}"
        rows.append(
            f"<div class='cloud-card' style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;padding:16px'>"
            f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:12px'>"
            f"{avatar}"
            f"<div style='flex:1;min-width:0'>"
            f"<div style='font-weight:700;font-size:15px;color:#fff'>{display_name}</div>"
            f"<div style='font-size:12px;color:#888'>@{ident}</div>"
            f"</div>"
            f"</div>"
            f"<div style='font-size:13px;color:#aaa;height:36px;overflow:hidden;margin-bottom:12px'>{bio_text or '<span style=color:#666>(Pas de bio)</span>'}</div>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#aaa;padding:8px 0;border-top:1px solid #2a2a2a;border-bottom:1px solid #2a2a2a;margin-bottom:12px'>"
            f"<span>🔗 <b>{nb_links}</b> lien(s)</span>"
            f"<a href='{public_url}' target='_blank' style='color:#3b82f6;text-decoration:none;font-weight:600'>Voir la page →</a>"
            f"</div>"
            f"<button onclick='openBioEditor(\"{ident}\")' style='width:100%;padding:10px;background:#3b82f6;color:#fff;border:0;border-radius:8px;cursor:pointer;font-weight:600;margin:0'>Éditer la page</button>"
            f"</div>"
        )
    rows.append("</div>")

    # Modal d'édition
    rows.append("""
<div id='bio-overlay' class='confirm-overlay' onclick='closeBioEditor()'>
  <div class='confirm-box' style='max-width:600px;width:95%;max-height:90vh;overflow-y:auto' onclick='event.stopPropagation()'>
    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px'>
      <h3 style='margin:0' id='bio-modal-title'>Éditer la bio</h3>
      <button onclick='closeBioEditor()' style='background:none;border:0;color:#888;font-size:20px;cursor:pointer;padding:0;margin:0'>×</button>
    </div>
    <form method='POST' action='/biolinks/save_meta' id='bio-meta-form'>
      <input type='hidden' name='identity' id='bio-identity'>
      <label>Nom affiché</label>
      <input type='text' name='display_name' id='bio-display-name' maxlength='60' placeholder='Amelia ✨'>
      <label>Bio (description)</label>
      <textarea name='bio' id='bio-text' maxlength='300' rows='3' placeholder='Modèle OnlyFans · Paris · DM ouvert'></textarea>
      <label>Thème de la page publique</label>
      <select name='theme' id='bio-theme'>
        <option value='dark'>Sombre (défaut)</option>
        <option value='light'>Clair</option>
        <option value='gradient'>Dégradé violet/rose</option>
      </select>
      <button type='submit' style='margin-top:14px;width:100%'>Sauvegarder le profil</button>
    </form>
    <h4 style='margin:24px 0 10px;font-size:14px'>Liens (drag pour réorganiser à venir)</h4>
    <div id='bio-links-list' style='display:flex;flex-direction:column;gap:8px;margin-bottom:14px'></div>
    <form method='POST' action='/biolinks/add_link' id='bio-add-form'>
      <input type='hidden' name='identity' id='bio-add-identity'>
      <h4 style='margin:0 0 8px;font-size:14px'>➕ Ajouter un lien</h4>
      <div style='display:grid;grid-template-columns:60px 1fr;gap:8px'>
        <div><label>Icône</label><input type='text' name='icon' id='bio-link-icon' maxlength='5' placeholder='🔗' value='🔗'></div>
        <div><label>Titre</label><input type='text' name='title' id='bio-link-title' maxlength='100' placeholder='OnlyFans' required></div>
      </div>
      <label>URL</label>
      <input type='url' name='url' id='bio-link-url' maxlength='500' placeholder='https://onlyfans.com/...' required>
      <button type='submit' style='margin-top:10px;width:100%'>Ajouter le lien</button>
    </form>
  </div>
</div>
<script>
window.__bioData = {};
function openBioEditor(ident){
  fetch('/biolinks/get?identity=' + encodeURIComponent(ident))
    .then(function(r){ return r.json(); })
    .then(function(data){
      window.__bioData = data;
      document.getElementById('bio-modal-title').textContent = 'Éditer la bio de @' + ident;
      document.getElementById('bio-identity').value = ident;
      document.getElementById('bio-add-identity').value = ident;
      document.getElementById('bio-display-name').value = data.display_name || '';
      document.getElementById('bio-text').value = data.bio || '';
      document.getElementById('bio-theme').value = data.theme || 'dark';
      renderBioLinks(data.links || []);
      document.getElementById('bio-overlay').classList.add('show');
    });
}
function renderBioLinks(links){
  var ident = document.getElementById('bio-identity').value;
  var container = document.getElementById('bio-links-list');
  if(!links || links.length === 0){
    container.innerHTML = '<p style="color:#888;text-align:center;font-size:13px;margin:0">Aucun lien ajouté pour l\\'instant</p>';
    return;
  }
  var html = '';
  links.forEach(function(l){
    html += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:10px;display:flex;align-items:center;gap:10px">'
      + '<div style="font-size:18px">' + (l.icon || '🔗') + '</div>'
      + '<div style="flex:1;min-width:0">'
      + '<div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + l.title + '</div>'
      + '<div style="font-size:11px;color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + l.url + '</div>'
      + '</div>'
      + '<button onclick="removeBioLink(\\''  + ident + '\\','+l.id+')" style="background:transparent;border:0;color:#aaa;cursor:pointer;padding:4px 8px;font-size:14px" onmouseover="this.style.color=\\'#ef4444\\'" onmouseout="this.style.color=\\'#aaa\\'">✕</button>'
      + '</div>';
  });
  container.innerHTML = html;
}
function removeBioLink(ident, linkId){
  showConfirm('Supprimer le lien ?', 'Cette action est irréversible.', function(){
    var form = new FormData();
    form.append('identity', ident);
    form.append('link_id', linkId);
    fetch('/biolinks/remove_link', {method: 'POST', body: form})
      .then(function(r){ return r.json(); })
      .then(function(data){
        if(data.success){
          showToast('✅ Lien supprimé', 'success');
          window.__bioData.links = (window.__bioData.links || []).filter(function(l){ return l.id !== linkId; });
          renderBioLinks(window.__bioData.links);
        }
      });
  });
}
function closeBioEditor(){
  document.getElementById('bio-overlay').classList.remove('show');
}
</script>
""")
    return "".join(rows)


def _render_bio_public_page(identity: str) -> str:
    """Page publique style Linktree pour une identité."""
    try:
        from bio_links import get_bio
    except Exception:
        return "<h1>Erreur module</h1>"
    bio = get_bio(identity)
    display_name = bio.get("display_name") or identity
    bio_text = bio.get("bio") or ""
    theme = bio.get("theme", "dark")
    links = bio.get("links", [])
    avatar_url = _identity_avatar_url(identity)

    if theme == "light":
        bg = "#f9fafb"
        card_bg = "#fff"
        text = "#111827"
        text_secondary = "#6b7280"
        link_bg = "#fff"
        link_hover = "#f3f4f6"
        link_border = "#e5e7eb"
    elif theme == "gradient":
        bg = "linear-gradient(135deg,#667eea,#764ba2)"
        card_bg = "rgba(255,255,255,.1)"
        text = "#fff"
        text_secondary = "rgba(255,255,255,.7)"
        link_bg = "rgba(255,255,255,.15)"
        link_hover = "rgba(255,255,255,.25)"
        link_border = "rgba(255,255,255,.2)"
    else:  # dark
        bg = "#0a0a0a"
        card_bg = "#1a1a1a"
        text = "#fff"
        text_secondary = "#888"
        link_bg = "#1a1a1a"
        link_hover = "#2a2a2a"
        link_border = "#2a2a2a"

    if avatar_url:
        avatar = f"<img src='{avatar_url}' style='width:96px;height:96px;border-radius:50%;object-fit:cover;border:3px solid {text};box-shadow:0 4px 20px rgba(0,0,0,.3)'>"
    else:
        init = (display_name[0] if display_name else "?").upper()
        avatar = f"<div style='width:96px;height:96px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:42px'>{init}</div>"

    links_html = ""
    for l in links:
        url = l.get("url", "#")
        title = l.get("title", "")
        icon = l.get("icon", "🔗")
        links_html += (
            f"<a href='{url}' target='_blank' rel='noopener' style='display:flex;align-items:center;gap:14px;padding:16px 20px;background:{link_bg};border:1px solid {link_border};border-radius:14px;color:{text};text-decoration:none;font-weight:600;transition:all .15s;font-size:15px' "
            f"onmouseover='this.style.background=\"{link_hover}\";this.style.transform=\"translateY(-2px)\"' "
            f"onmouseout='this.style.background=\"{link_bg}\";this.style.transform=\"\"'>"
            f"<span style='font-size:22px'>{icon}</span>"
            f"<span>{title}</span>"
            f"</a>"
        )
    if not links_html:
        links_html = f"<p style='color:{text_secondary};text-align:center;padding:30px 20px'>Aucun lien pour l'instant</p>"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>@{identity} — {display_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',-apple-system,sans-serif;background:{bg};min-height:100vh;display:flex;align-items:flex-start;justify-content:center;padding:40px 20px;color:{text};-webkit-font-smoothing:antialiased}}
.container{{max-width:480px;width:100%}}
.header{{text-align:center;margin-bottom:30px}}
.name{{font-size:24px;font-weight:800;margin-top:18px;letter-spacing:-.02em}}
.handle{{font-size:14px;color:{text_secondary};margin-top:4px}}
.bio{{font-size:15px;color:{text_secondary};margin-top:14px;line-height:1.5;padding:0 12px}}
.links{{display:flex;flex-direction:column;gap:12px}}
.footer{{text-align:center;margin-top:40px;font-size:11px;color:{text_secondary};opacity:.5}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    {avatar}
    <div class="name">{display_name}</div>
    <div class="handle">@{identity}</div>
    {f'<div class="bio">{bio_text}</div>' if bio_text else ''}
  </div>
  <div class="links">{links_html}</div>
  <div class="footer">Powered by VA Bot</div>
</div>
</body>
</html>"""


def _render_gms_html() -> str:
    """Page GetMySocial : gestion clé API + liste/création/suppression liens."""
    try:
        import gms
    except Exception as e:
        return f"<p style='color:#f99'>Module gms indispo : {e}</p>"

    configured = gms.is_configured()
    key = gms.get_api_key()
    key_masked = (key[:9] + "…" + key[-6:]) if key and len(key) > 18 else (key or "")

    # Header / config key
    if configured:
        key_status_html = (
            f"<div style='display:flex;align-items:center;gap:10px;padding:12px 16px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);border-radius:10px;margin-bottom:18px'>"
            f"<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#22c55e' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M20 6L9 17l-5-5'/></svg>"
            f"<div style='flex:1'><div style='font-weight:600;color:#22c55e;font-size:13px'>Clé API GetMySocial configurée</div>"
            f"<div style='font-size:12px;color:#888;font-family:monospace'>{key_masked}</div></div>"
            f"<form method='POST' action='/gms/test' style='margin:0'><button type='submit' style='background:#22c55e;border:0;color:#000;padding:8px 14px;border-radius:8px;font-weight:600;font-size:12px;cursor:pointer'>▶ Tester</button></form>"
            f"</div>"
        )
    else:
        key_status_html = (
            "<div style='display:flex;align-items:center;gap:10px;padding:12px 16px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:10px;margin-bottom:18px'>"
            "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#ef4444' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/></svg>"
            "<div style='flex:1;font-weight:600;color:#ef4444;font-size:13px'>Aucune clé API configurée — entre ta clé ci-dessous pour activer l'intégration</div>"
            "</div>"
        )

    key_form = (
        "<div class='box' style='margin-bottom:24px'>"
        "<h3 style='margin:0 0 4px;font-size:15px'>Clé API GetMySocial</h3>"
        "<p style='color:#888;font-size:12px;margin:0 0 12px'>Récupère-la sur ton dashboard GetMySocial → Settings → API Keys (commence par <code>gms_live_</code>).</p>"
        "<form method='POST' action='/gms/save_key' style='display:flex;gap:8px'>"
        "<input type='password' name='api_key' placeholder='gms_live_…' required minlength='20' style='flex:1'>"
        "<button type='submit'>Enregistrer</button>"
        "</form>"
        "</div>"
    )

    # Liste des liens (uniquement si configuré)
    links_section = ""
    if configured:
        res = gms.list_all_links()
        if not res.get("ok"):
            links_html = (
                f"<div style='padding:18px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:10px;color:#ef4444;font-size:13px'>"
                f"❌ Erreur API : {res.get('error', '?')}</div>"
            )
            tabs_html = ""
        else:
            links = res["links"]
            # Catégoriser chaque lien
            from collections import Counter
            cat_counter: Counter = Counter()
            link_cats = []  # parallel array
            for l in links:
                c = gms.categorize_link(l)
                cat_counter[c] += 1
                link_cats.append(c)

            # Préparer la liste des catégories triées : modèles principaux d'abord, puis par count
            PRIORITY = ["Amelia", "Lola", "Julia", "Sarah", "Emma"]
            sorted_cats = []
            # 1) Ajouter prioritaires s'ils existent
            for p in PRIORITY:
                if p in cat_counter:
                    sorted_cats.append((p, cat_counter[p]))
            # 2) Ajouter le reste par count décroissant
            for c, n in cat_counter.most_common():
                if c not in PRIORITY:
                    sorted_cats.append((c, n))

            # Tabs HTML
            if sorted_cats:
                tab_buttons = (
                    f"<button class='gms-tab gms-tab-active' data-cat='__all__' onclick='gmsFilter(this,\"__all__\")'>"
                    f"Tous <span class='gms-tab-count'>{len(links)}</span></button>"
                )
                for cat, n in sorted_cats:
                    cat_safe = cat.replace("'", "&#39;").replace('"', "&quot;")
                    tab_buttons += (
                        f"<button class='gms-tab' data-cat='{cat_safe}' onclick='gmsFilter(this,\"{cat_safe}\")'>"
                        f"{cat} <span class='gms-tab-count'>{n}</span></button>"
                    )
                tabs_html = (
                    "<div class='gms-tabs' style='display:flex;gap:6px;flex-wrap:wrap;margin:20px 0 14px;padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;overflow-x:auto'>"
                    + tab_buttons
                    + "</div>"
                )
            else:
                tabs_html = ""

            if not links:
                links_html = (
                    "<div style='padding:40px;text-align:center;color:#888;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px'>"
                    "Aucun lien pour l'instant. Crée ton premier ci-dessus.</div>"
                )
            else:
                rows = []
                for l, cat in zip(links, link_cats):
                    lid = l.get("id", "")
                    short = l.get("shortcode", "")
                    name = l.get("display_name", "") or "—"
                    url = l.get("url") or "(landing page)"
                    status = l.get("status", "active")
                    ltype = l.get("type", "directlink")
                    is_active = status == "active"
                    status_color = "#22c55e" if is_active else "#6b7280"
                    status_bg = "rgba(34,197,94,.12)" if is_active else "rgba(107,114,128,.15)"
                    status_label = "Actif" if is_active else "Inactif"
                    toggle_label = "Désactiver" if is_active else "Activer"
                    toggle_action = "disable" if is_active else "enable"
                    type_badge = "Landing" if ltype == "landing" else "Redirect"
                    type_color = "#a855f7" if ltype == "landing" else "#3b82f6"
                    cat_safe = cat.replace("'", "&#39;").replace('"', "&quot;")
                    rows.append(
                        f"<div class='gms-link-card' data-cat='{cat_safe}' style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:14px 16px;display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center'>"
                        f"<div style='min-width:0'>"
                        f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap'>"
                        f"<strong style='font-size:14px'>{name}</strong>"
                        f"<span style='background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.3);color:#3b82f6;font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px'>{cat}</span>"
                        f"<span style='background:rgba(255,255,255,.05);border:1px solid #2a2a2a;color:{type_color};font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:.04em'>{type_badge}</span>"
                        f"<span style='background:{status_bg};color:{status_color};font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:.04em'>{status_label}</span>"
                        f"</div>"
                        f"<div style='font-size:12px;color:#888;font-family:monospace;margin-bottom:3px'>/{short}</div>"
                        f"<div style='font-size:11px;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>→ {url}</div>"
                        f"</div>"
                        f"<div style='display:flex;gap:6px;align-items:center'>"
                        f"<button onclick=\"copyToClipboard('/{short}', this)\" style='background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer' title='Copier le shortcode'>📋</button>"
                        f"<form method='POST' action='/gms/toggle' style='margin:0;display:inline'>"
                        f"<input type='hidden' name='link_id' value='{lid}'>"
                        f"<input type='hidden' name='action' value='{toggle_action}'>"
                        f"<button type='submit' style='background:transparent;border:1px solid #2a2a2a;color:#aaa;padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer'>{toggle_label}</button>"
                        f"</form>"
                        f"<form method='POST' action='/gms/delete' style='margin:0;display:inline' onsubmit='return confirmGmsDelete(this)'>"
                        f"<input type='hidden' name='link_id' value='{lid}'>"
                        f"<input type='hidden' name='shortcode' value='{short}'>"
                        f"<button type='submit' style='background:transparent;border:1px solid rgba(239,68,68,.3);color:#ef4444;padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer'>Supprimer</button>"
                        f"</form>"
                        f"</div>"
                        f"</div>"
                    )
                links_html = "<div id='gms-links-list' style='display:flex;flex-direction:column;gap:10px'>" + "".join(rows) + "</div>"

        # Formulaire de création
        create_form = (
            "<div class='box' style='margin-bottom:18px;border:2px solid #3b82f6'>"
            "<h3 style='margin:0 0 4px;font-size:15px;color:#3b82f6'>➕ Créer un nouveau lien</h3>"
            "<p style='color:#888;font-size:12px;margin:0 0 14px'>Redirect simple (directlink) : shortcode → URL de destination.</p>"
            "<form method='POST' action='/gms/create' style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>"
            "<div><label>Shortcode (3-24 car.)</label><input type='text' name='shortcode' pattern='[a-zA-Z0-9_-]{3,24}' minlength='3' maxlength='24' placeholder='amelia-of' required></div>"
            "<div><label>Nom affiché (optionnel)</label><input type='text' name='display_name' maxlength='60' placeholder='Amelia OnlyFans'></div>"
            "<div style='grid-column:1 / -1'><label>URL de destination</label><input type='url' name='url' placeholder='https://onlyfans.com/...' required></div>"
            "<div style='grid-column:1 / -1'><button type='submit' style='width:100%'>Créer le lien</button></div>"
            "</form>"
            "</div>"
        )

        # Section : templates par modèle + boutons Génération rapide
        templates = gms.load_templates()
        identities = _list_identities()
        # Réutiliser le même `source_options` plus bas via fonction helper
        def _build_source_select(selected=""):
            html = []
            for model in sorted(links_by_model.keys()):
                html.append(f"<optgroup label='{model}'>")
                for l in sorted(links_by_model[model], key=lambda x: (x.get("display_name") or "").lower()):
                    lid = l.get("id", "")
                    sc = l.get("shortcode", "")
                    nm = l.get("display_name") or "—"
                    lbl = f"/{sc} — {nm}"[:80]
                    sel = " selected" if lid == selected else ""
                    html.append(f"<option value='{lid}'{sel}>{lbl}</option>")
                html.append("</optgroup>")
            return "".join(html) if html else "<option value=''>Aucun lien</option>"

        from collections import defaultdict as _dd_t
        links_by_model_t = _dd_t(list)
        for l in res.get("links", []):
            model = gms.categorize_link(l)
            links_by_model_t[model].append(l)
        links_by_model = links_by_model_t  # réutilisé plus bas pour duplicate_form

        template_rows = []
        for ident in sorted(identities):
            cur_tpl = templates.get(ident.lower(), "")
            tpl_select = _build_source_select(cur_tpl)
            avatar = _identity_avatar_url(ident)
            avatar_html = (
                f"<img src='{avatar}' style='width:30px;height:30px;border-radius:50%;object-fit:cover;flex-shrink:0'>"
                if avatar else
                f"<div style='width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a855f7);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:13px;flex-shrink:0'>{ident[:1].upper()}</div>"
            )
            # Bouton Generate quick si template défini
            if cur_tpl:
                quick_btn = (
                    f"<form method='POST' action='/gms/quick_generate' style='margin:0'>"
                    f"<input type='hidden' name='identity' value='{ident}'>"
                    f"<button type='submit' style='background:#22c55e;color:#000;border:0;padding:8px 14px;border-radius:7px;font-weight:700;cursor:pointer;font-size:12px;white-space:nowrap'>"
                    f"🎲 Générer</button></form>"
                )
            else:
                quick_btn = "<span style='color:#666;font-size:11px'>Définis un template d'abord</span>"

            template_rows.append(
                f"<div style='display:grid;grid-template-columns:30px 90px 1fr auto auto;gap:10px;align-items:center;padding:10px 12px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px'>"
                f"{avatar_html}"
                f"<div style='font-weight:700;font-size:13px'>@{ident}</div>"
                f"<form method='POST' action='/gms/set_template' style='margin:0;display:flex;gap:6px;align-items:center'>"
                f"<input type='hidden' name='identity' value='{ident}'>"
                f"<select name='link_id' style='flex:1;font-size:12px;padding:6px 8px'>"
                f"<option value=''>—</option>{tpl_select}</select>"
                f"<button type='submit' style='background:#3b82f6;color:#fff;border:0;padding:7px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer'>Save</button>"
                f"</form>"
                f"<div>{quick_btn}</div>"
                f"</div>"
            )

        templates_section = (
            "<div class='box' style='margin-bottom:18px;border:2px solid #22c55e'>"
            "<h3 style='margin:0 0 4px;font-size:15px;color:#22c55e'>🎲 Templates par modèle</h3>"
            "<p style='color:#888;font-size:12px;margin:0 0 14px'>"
            "Définis un lien template par modèle. Click sur <b>🎲 Générer</b> → crée auto un nouveau lien "
            "avec préfixe aléatoire (ex: <code>jfsiamelia</code>) en clonant tout du template.</p>"
            "<div style='display:flex;flex-direction:column;gap:6px'>"
            + "".join(template_rows)
            + "</div>"
            "</div>"
        )

        # Formulaire de duplication depuis un template
        # On groupe les liens dispos par modèle pour le select
        from collections import defaultdict as _dd
        links_by_model = _dd(list)
        for l in res.get("links", []):
            model = gms.categorize_link(l)
            links_by_model[model].append(l)
        source_options = []
        for model in sorted(links_by_model.keys()):
            source_options.append(f"<optgroup label='{model}'>")
            for l in sorted(links_by_model[model], key=lambda x: (x.get("display_name") or "").lower()):
                lid = l.get("id", "")
                sc = l.get("shortcode", "")
                nm = l.get("display_name") or "—"
                lbl = f"/{sc} — {nm}"[:80]
                source_options.append(f"<option value='{lid}'>{lbl}</option>")
            source_options.append("</optgroup>")
        source_select = "".join(source_options) if source_options else "<option value=''>Aucun lien existant à dupliquer</option>"

        duplicate_form = (
            "<div class='box' style='margin-bottom:18px;border:2px solid #a855f7'>"
            "<h3 style='margin:0 0 4px;font-size:15px;color:#a855f7'>🪄 Dupliquer depuis un template</h3>"
            "<p style='color:#888;font-size:12px;margin:0 0 14px'>"
            "Reprend TOUTE la config d'un lien existant (boutons, profile pic, pixels, anti-bot, design, "
            "smart redirect, A/B testing, etc.) — tu changes juste le shortcode et l'URL.</p>"
            "<form method='POST' action='/gms/duplicate' style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>"
            "<div style='grid-column:1 / -1'>"
            "<label>Lien source (template)</label>"
            f"<select name='source_link_id' required>{source_select}</select>"
            "</div>"
            "<div><label>Nouveau shortcode</label>"
            "<input type='text' name='shortcode' pattern='[a-zA-Z0-9_-]{3,24}' minlength='3' maxlength='24' placeholder='amelia-newva' required></div>"
            "<div><label>Nom affiché</label>"
            "<input type='text' name='display_name' maxlength='60' placeholder='Amelia New VA' required></div>"
            "<div style='grid-column:1 / -1'><label>Nouvelle URL (optionnel — sinon garde celle du template)</label>"
            "<input type='url' name='url' placeholder='https://onlyfans.com/<nouveau-username>'></div>"
            "<div style='grid-column:1 / -1'>"
            "<button type='submit' style='width:100%;background:#a855f7'>🪄 Dupliquer + créer</button></div>"
            "</form>"
            "</div>"
        )

        total_count = len(res.get("links", []))
        links_section = (
            templates_section
            + create_form
            + duplicate_form
            + f"<h3 style='margin:24px 0 0;font-size:15px;display:flex;align-items:center;gap:10px'>Tes liens"
            + f"<span style='background:#1a1a1a;border:1px solid #2a2a2a;color:#888;font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px'>{total_count}</span>"
            + "</h3>"
            + tabs_html
            + links_html
        )

    js = """
<style>
.gms-tab{background:transparent;border:1px solid transparent;color:#aaa;padding:7px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;white-space:nowrap;transition:all .12s}
.gms-tab:hover{background:rgba(255,255,255,.05);color:#fff}
.gms-tab-active{background:#3b82f6 !important;color:#fff !important;border-color:#3b82f6 !important}
.gms-tab-active .gms-tab-count{background:rgba(255,255,255,.2);color:#fff}
.gms-tab-count{background:#2a2a2a;color:#888;font-size:10px;font-weight:700;padding:1px 7px;border-radius:5px;line-height:1.5}
body.light .gms-tab{color:#666}
body.light .gms-tab:hover{background:rgba(0,0,0,.05);color:#111}
body.light .gms-tab-count{background:#e5e7eb;color:#666}
</style>
<script>
function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(function(){
    var orig = btn.textContent;
    btn.textContent = '✓';
    setTimeout(function(){ btn.textContent = orig; }, 1200);
  });
}
function confirmGmsDelete(form) {
  var sc = form.querySelector('input[name=shortcode]').value;
  return confirm('Supprimer définitivement le lien /' + sc + ' ?\\n\\nCette action est irréversible — l\\'historique de redirections est perdu et le shortcode peut être réservé un moment contre le squatting.');
}
function gmsFilter(btn, cat){
  // update active tab
  document.querySelectorAll('.gms-tab').forEach(function(t){ t.classList.remove('gms-tab-active'); });
  btn.classList.add('gms-tab-active');
  // filter cards
  document.querySelectorAll('.gms-link-card').forEach(function(c){
    if(cat === '__all__' || c.getAttribute('data-cat') === cat){
      c.style.display = '';
    } else {
      c.style.display = 'none';
    }
  });
}
</script>
"""

    return (
        "<h2 style='margin:0 0 6px;font-size:20px'>GetMySocial</h2>"
        "<p style='margin:0 0 18px;color:#888;font-size:13px'>Gère tes liens GetMySocial (redirects) directement depuis le site — synchronisé avec ton compte GMS via l'API officielle.</p>"
        + key_status_html
        + (key_form if not configured else "")
        + links_section
        + js
    )


def _render_veille_feed_html() -> str:
    """Liste des reels veille, groupes par jour. Bouton 'Send to Telegram' par reel."""
    try:
        import veille
        import veille_telegram
    except Exception as e:
        return f"<p style='color:#f99'>Module veille indispo : {e}</p>"

    by_day = veille.reels_by_day()
    s = veille.stats()
    tg_configured = veille_telegram.is_configured()

    if not by_day:
        return (
            "<div style='background:#161616;border:1px solid #2a2a2a;border-radius:12px;padding:60px 20px;text-align:center;color:#666'>"
            "<div style='font-size:48px;margin-bottom:12px'>🔖</div>"
            "<h3 style='margin:0 0 8px;color:#fff'>Pas de reels en veille</h3>"
            "<p style='margin:0;font-size:14px'>Va dans <b>Mes suivies</b> et clique sur le bouton 🔖 d'un reel pour l'ajouter ici.</p>"
            "</div>"
        )

    # Header stats + actions globales
    tg_warn = ""
    if not tg_configured:
        tg_warn = (
            "<div style='background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:10px;padding:12px 16px;margin-bottom:18px;color:#f59e0b;font-size:13px'>"
            "⚠️ Bot Telegram pas configuré — va dans <a href='?tab=vtg' style='color:#f59e0b;text-decoration:underline'>Settings → Veille Telegram</a> pour l envoyer aux reels."
            "</div>"
        )

    stats_html = (
        "<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px'>"
        f"<div style='background:#161616;border:1px solid #232323;border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:22px;font-weight:800;color:#fff'>{s['total']}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase'>Reels</div></div>"
        f"<div style='background:#161616;border:1px solid #232323;border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:22px;font-weight:800;color:#22c55e'>{s['sent_count']}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase'>Envoyés</div></div>"
        f"<div style='background:#161616;border:1px solid #232323;border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:22px;font-weight:800;color:#3b82f6'>{s['unsent_count']}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase'>A envoyer</div></div>"
        f"<div style='background:#161616;border:1px solid #232323;border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:22px;font-weight:800;color:#a855f7'>{s['days_count']}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase'>Jours</div></div>"
        "</div>"
    )

    # Render par jour
    import datetime as _dt_v
    fr_months = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                 "juill.", "août", "sept.", "oct.", "nov.", "déc."]

    sections = []
    for day in sorted(by_day.keys(), reverse=True):
        reels = by_day[day]
        # Format date
        try:
            d = _dt_v.date.fromisoformat(day)
            today = _dt_v.date.today()
            if d == today:
                day_label = "Aujourd'hui"
            elif d == today - _dt_v.timedelta(days=1):
                day_label = "Hier"
            else:
                day_label = f"{d.day} {fr_months[d.month - 1]} {d.year}"
        except Exception:
            day_label = day

        unsent_count = sum(1 for r in reels if not r.get('sent_to_telegram'))

        # Header du jour
        section_html = (
            "<div style='margin-bottom:30px'>"
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #2a2a2a'>"
            f"<div><h3 style='margin:0;font-size:17px;color:#fff;letter-spacing:-.01em'>📅 {day_label}</h3>"
            f"<div style='font-size:12px;color:#666;margin-top:2px'>{len(reels)} reels · {unsent_count} non envoyés</div></div>"
        )
        if unsent_count > 0 and tg_configured:
            section_html += (
                f"<button onclick=\"sendAllVeilleDay('{day}')\" "
                f"style='background:#0088cc;color:#fff;border:0;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:700;display:inline-flex;align-items:center;gap:6px'>"
                f"📤 Envoyer tout ({unsent_count})</button>"
            )
        section_html += "</div>"

        # Grille des reels
        section_html += "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px'>"
        for r in reels:
            sent = r.get("sent_to_telegram", False)
            ribbon = ""
            if sent:
                ribbon = ("<div style='position:absolute;top:8px;left:8px;background:#22c55e;color:#fff;font-size:10px;font-weight:800;"
                          "padding:3px 8px;border-radius:6px;z-index:3;letter-spacing:.3px'>✓ ENVOYÉ</div>")
            send_btn = ""
            if not sent and tg_configured:
                send_btn = (
                    f"<button onclick=\"sendVeilleReel('{r['id']}', this)\" "
                    f"style='flex:1;background:#0088cc;color:#fff;border:0;padding:8px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:700'>"
                    f"📤 Telegram</button>"
                )
            else:
                send_btn = (
                    f"<button disabled style='flex:1;background:#1a1a1a;color:#22c55e;border:1px solid #22c55e;padding:7px;border-radius:6px;font-size:12px;font-weight:700;cursor:default'>"
                    f"✓ Envoyé</button>"
                )
            section_html += (
                f"<div style='background:#0f0f0f;border:1px solid #232323;border-radius:12px;overflow:hidden;display:flex;flex-direction:column'>"
                f"<div style='position:relative;width:100%;aspect-ratio:9/16;background:#000;cursor:pointer' onclick=\"window.open('{r['url']}','_blank')\">"
                f"{ribbon}"
                f"<img src='{r.get('thumb', '')}' loading='lazy' style='width:100%;height:100%;object-fit:cover'>"
                f"<div style='position:absolute;bottom:0;left:0;right:0;background:linear-gradient(to top,rgba(0,0,0,.85),transparent);padding:10px;color:#fff;font-size:11px'>"
                f"<div style='font-weight:700'>@{r.get('owner', '?')}</div>"
                f"<div style='display:flex;gap:8px;color:#ddd;margin-top:3px;font-size:11px'>▶ {_format_count(r.get('views', 0))} · ♥ {_format_count(r.get('likes', 0))}</div>"
                f"</div></div>"
                f"<div style='padding:10px;display:flex;gap:6px'>"
                + send_btn +
                f"<button onclick=\"removeVeilleReel('{r['id']}', this)\" "
                f"style='background:transparent;border:1px solid #5a2020;color:#ef4444;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:12px' title='Retirer de la veille'>🗑</button>"
                f"</div>"
                f"</div>"
            )
        section_html += "</div></div>"
        sections.append(section_html)

    js = """
<script>
async function sendVeilleReel(rid, btn){
  if(!confirm('Envoyer ce reel sur Telegram ?')) return;
  const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '⏳ Envoi...';
  const fd = new FormData(); fd.set('reel_id', rid);
  const r = await fetch('/veille/send', {method:'POST', body:fd});
  const j = await r.json();
  if(j.ok){
    btn.innerHTML = '✓ Envoyé'; btn.style.background = '#22c55e';
    setTimeout(()=>location.reload(), 800);
  } else {
    btn.innerHTML = '✗ ' + (j.error||'Erreur');
    btn.style.background = '#ef4444';
    setTimeout(()=>{ btn.innerHTML = orig; btn.style.background = '#0088cc'; btn.disabled = false; }, 3000);
  }
}
async function sendAllVeilleDay(day){
  if(!confirm('Envoyer TOUS les reels non envoyés du ' + day + ' sur Telegram ?')) return;
  const fd = new FormData(); fd.set('day', day);
  const r = await fetch('/veille/send_day', {method:'POST', body:fd});
  const j = await r.json();
  if(j.ok){
    showToast('✅ ' + j.sent + ' reels envoyés' + (j.failed?' · ' + j.failed + ' fail':''), j.failed?'error':'success');
    setTimeout(()=>location.reload(), 800);
  } else {
    alert('Erreur: ' + (j.error || '?'));
  }
}
async function removeVeilleReel(rid, btn){
  if(!confirm('Retirer ce reel de la veille ?')) return;
  const fd = new FormData(); fd.set('reel_id', rid);
  const r = await fetch('/veille/remove', {method:'POST', body:fd});
  const card = btn.closest('div[style*="aspect-ratio"]')?.parentNode;
  if(card) card.style.opacity = '0.3';
  setTimeout(()=>location.reload(), 400);
}
</script>
"""

    return tg_warn + stats_html + "".join(sections) + js


def _render_vtg_html() -> str:
    """Settings : Veille Telegram (bot token + chat ID)."""
    try:
        import veille_telegram
    except Exception as e:
        return f"<p style='color:#f99'>Module veille_telegram indispo : {e}</p>"

    cfg = veille_telegram.load_config()
    configured = veille_telegram.is_configured()
    masked_token = ""
    if cfg.get("bot_token"):
        t = cfg["bot_token"]
        masked_token = t[:10] + "..." + t[-4:] if len(t) > 16 else t[:4] + "..."

    status_html = ""
    if configured:
        status_html = (
            "<div style='display:flex;align-items:center;gap:10px;padding:12px 16px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);border-radius:10px;margin-bottom:18px'>"
            "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#22c55e' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M20 6L9 17l-5-5'/></svg>"
            f"<div style='flex:1'><div style='font-weight:600;color:#22c55e;font-size:13px'>Bot Telegram configuré</div>"
            f"<div style='font-size:12px;color:#888;font-family:monospace'>{masked_token} · chat_id: <code>{cfg.get('chat_id', '?')}</code></div></div>"
            "<form method='POST' action='/settings/veille_telegram/test' style='margin:0'>"
            "<button type='submit' style='background:#22c55e;border:0;color:#000;padding:8px 14px;border-radius:8px;font-weight:600;font-size:12px;cursor:pointer'>▶ Tester</button></form>"
            "</div>"
        )
    else:
        status_html = (
            "<div style='display:flex;align-items:center;gap:10px;padding:12px 16px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:10px;margin-bottom:18px'>"
            "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#ef4444' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/></svg>"
            "<div style='font-weight:600;color:#ef4444;font-size:13px'>Bot Telegram pas encore configuré</div>"
            "</div>"
        )

    return (
        "<div style='max-width:680px'>"
        "<h2 style='margin:0 0 6px;font-size:20px'>📤 Veille Telegram</h2>"
        "<p style='margin:0 0 18px;color:#888;font-size:13px'>"
        "Configure ton bot Telegram pour envoyer les reels intéressants au groupe de veille en 1 clic. "
        "Tu utilises un <b>bot downloader</b> (style @downloaderbot ou ton propre bot) qui se charge ensuite de télécharger la vidéo."
        "</p>"
        + status_html +
        "<form method='POST' action='/settings/veille_telegram' class='box'>"
        "<h3 style='margin:0 0 10px;font-size:14px'>🔑 Configuration</h3>"
        "<label>Bot token <span style='color:#f99'>*</span></label>"
        "<input type='password' name='bot_token' placeholder='123456789:ABCDEF...' "
        f"value='{cfg.get('bot_token', '')}' required>"
        "<small style='color:#888'>Crée un bot via <code>@BotFather</code> sur Telegram, il te donne un token.</small>"
        "<label style='margin-top:14px'>Chat ID du groupe Veille <span style='color:#f99'>*</span></label>"
        "<input type='text' name='chat_id' placeholder='-100123456789' "
        f"value='{cfg.get('chat_id', '')}' required>"
        "<small style='color:#888'>ID du groupe Telegram où poster les liens. Ajoute le bot au groupe puis va sur <code>https://api.telegram.org/bot[TOKEN]/getUpdates</code> pour voir le chat_id.</small>"
        "<button type='submit' style='margin-top:14px;background:#0088cc;color:#fff;border:0;padding:11px 22px;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px'>💾 Sauvegarder</button>"
        "</form>"
        "<div style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;padding:14px;margin-top:18px;font-size:13px;color:#aaa;line-height:1.7'>"
        "<h4 style='margin:0 0 8px;color:#fff'>📖 Comment ça marche</h4>"
        "1. <b>Crée un bot</b> via @BotFather sur Telegram, copie le token<br>"
        "2. <b>Ajoute ton bot au groupe</b> Veille (et donne-lui les droits d'écrire)<br>"
        "3. <b>Récupère le chat_id</b> : envoie un message dans le groupe puis va sur <code>https://api.telegram.org/bot[TOKEN]/getUpdates</code><br>"
        "4. <b>Sauve les 2 valeurs</b> ici → clique <b>Tester</b> pour vérifier<br>"
        "5. Sur n'importe quel reel des Trends, clique le bouton 📤 → le lien part au bot downloader"
        "</div>"
        "</div>"
    )


def _render_schedule_html() -> str:
    """Page Schedule : formulaire pour generer un fichier Excel d'import de posts planifies."""
    import datetime as _dt

    # Liste des modeles depuis les identites
    try:
        identities = sorted(_list_identities())
    except Exception:
        identities = []

    # Captions par defaut
    try:
        from schedule_xlsx import DEFAULT_CAPTIONS
        captions_default = "\n".join(DEFAULT_CAPTIONS)
    except Exception:
        captions_default = (
            "Ton abonnement 100% GRATUIT + un CADEAU aujourd'hui seulement \U0001F609❤️\n"
            "Abonnement gratuit sans code, si tu likes mes derniers posts = \U0001F381\n"
            "Abonnement gratuit sans code et si tu likes mes 5 derniers posts = cadeau\n"
            "Abonnement gratuit sans code + surprise si tu likes mes posts \U0001F48B\n"
            "Abonnement gratuit 0€ + des surprises si tu likes mes derniers post\n"
            "Abonnement 100% gratuit sans code + des surprises en prive"
        )

    # Dates par defaut : aujourd hui -> +7 jours
    today = _dt.date.today()
    week_later = today + _dt.timedelta(days=6)
    d_start = today.isoformat()
    d_end = week_later.isoformat()

    # Datalist des modeles existants
    datalist_opts = "".join(f"<option value='{i}'></option>" for i in identities)

    return (
        "<div style='max-width:980px'>"
        "<h2 style='margin:0 0 6px;font-size:20px'>Schedule — Auto-post</h2>"
        "<p style='margin:0 0 18px;color:#888;font-size:13px'>"
        "Genere un fichier <b>Excel template d'import</b> de posts planifies. "
        "Tu definis le modele, la periode, le nombre de posts par jour et les heures. "
        "Tu colles tes <b>media_id</b> (un par ligne) et tes <b>captions</b> (les 6 captions par defaut sont pre-remplies). "
        "Les minutes sont randomisees entre <b>:03</b> et <b>:25</b> pour faire humain. "
        "Chaque post sera supprime automatiquement <b>48h</b> apres publication (post_action=delete, delay=172800)."
        "</p>"

        "<form method='POST' action='/schedule/generate' class='box' style='border:1px solid #2a2a2a'>"

        "<datalist id='schedule-models'>" + datalist_opts + "</datalist>"

        "<div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>"
        "<div>"
        "<label>Modele / prenom <span style='color:#f99'>*</span></label>"
        "<input type='text' name='model_name' list='schedule-models' placeholder='ex: amelia' required>"
        "<small>Sert pour le nom du fichier <code>template_import_[PRENOM]_[PERIODE].xlsx</code></small>"
        "</div>"
        "<div></div>"
        "</div>"

        "<div style='display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px'>"
        "<div>"
        "<label>Date de debut <span style='color:#f99'>*</span></label>"
        f"<input type='date' name='date_start' value='{d_start}' required>"
        "</div>"
        "<div>"
        "<label>Date de fin <span style='color:#f99'>*</span></label>"
        f"<input type='date' name='date_end' value='{d_end}' required>"
        "</div>"
        "</div>"

        "<div style='display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px'>"
        "<div style='background:rgba(34,197,94,.05);border:1px solid rgba(34,197,94,.2);border-radius:10px;padding:14px'>"
        "<h4 style='margin:0 0 8px;color:#22c55e;font-size:14px'>\U0001F30D Posts PUBLICS</h4>"
        "<label>Heures (separer par virgules)</label>"
        "<input type='text' name='public_hours' placeholder='ex: 9, 14, 20' value='9, 14, 20'>"
        "<small>1 post public sera planifie a chaque heure indiquee, chaque jour de la periode. Minutes aleatoires :03 a :25.</small>"
        "</div>"
        "<div style='background:rgba(168,85,247,.05);border:1px solid rgba(168,85,247,.2);border-radius:10px;padding:14px'>"
        "<h4 style='margin:0 0 8px;color:#a855f7;font-size:14px'>\U0001F512 Posts PRIVES</h4>"
        "<label>Heures (separer par virgules)</label>"
        "<input type='text' name='private_hours' placeholder='ex: 11, 17, 23' value='11, 17, 23'>"
        "<small>1 post prive sera planifie a chaque heure indiquee, chaque jour. Minutes aleatoires :03 a :25.</small>"
        "</div>"
        "</div>"

        "<label style='margin-top:14px'>media_id <span style='color:#f99'>*</span> "
        "<span style='color:#888;font-weight:400'>(un par ligne, recycles en ordre si pas assez)</span></label>"
        "<textarea name='media_ids' rows='8' placeholder='media_id_1&#10;media_id_2&#10;media_id_3&#10;...' required style='font-family:monospace;font-size:13px'></textarea>"

        "<label style='margin-top:8px'>Captions "
        "<span style='color:#888;font-weight:400'>(une par ligne — tirees au hasard pour chaque post)</span></label>"
        f"<textarea name='captions' rows='8' style='font-family:inherit;font-size:13px'>{captions_default}</textarea>"

        "<button type='submit' style='margin-top:14px;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;border:0;padding:12px 22px;border-radius:10px;font-weight:700;font-size:14px;cursor:pointer'>"
        "⬇ Generer le fichier Excel"
        "</button>"
        "</form>"

        "<div style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;padding:14px;margin-top:18px;font-size:13px;color:#aaa;line-height:1.7'>"
        "<h4 style='margin:0 0 8px;color:#fff'>ℹ Structure du fichier genere</h4>"
        "Colonnes : <code>media_id</code> | <code>date_schedule</code> | <code>feed_visibility</code> | <code>post_action</code> | <code>post_action_delay_seconds</code> | <code>caption</code><br>"
        "Sheet : <b>Posts</b> — Date format : <code>yyyy-mm-dd hh:mm:ss</code><br>"
        "Tous les posts : <code>post_action=delete</code>, <code>post_action_delay_seconds=172800</code> (48h)<br>"
        "Trie par date croissante."
        "</div>"

        "</div>"
    )


def _render_chatplanning_html() -> str:
    """Emploi du temps chatteurs - tableau Excel-style multi-EDT multi-semaines."""
    try:
        import chatting
    except Exception as e:
        return f"<p style='color:#f99'>Module chatting indispo : {e}</p>"

    from flask import request as _req
    edts = chatting.list_edts()

    # Week navigation : ?week_start=YYYY-MM-DD
    ws_param = (_req.args.get("week_start") or "").strip()
    if ws_param:
        active_week = chatting.parse_week_start(ws_param)
    else:
        active_week = chatting.current_week_start()
    prev_week = chatting.shift_week(active_week, -1)
    next_week = chatting.shift_week(active_week, +1)
    today_week = chatting.current_week_start()
    week_dates = chatting.week_dates(active_week)
    week_lbl = chatting.week_label(active_week)
    iso_w = chatting.iso_week_number(active_week)

    # Si pas d EDT, propose les 2 presets + custom
    if not edts:
        return (
            "<div style='max-width:680px;text-align:center;padding:50px 20px'>"
            "<div style='font-size:48px;margin-bottom:12px'>💬</div>"
            "<h2 style='margin:0 0 6px;font-size:22px'>Emploi du temps chatteurs</h2>"
            "<p style='margin:0 0 28px;color:#888;font-size:14px'>Cree tes plannings — un par plateforme.</p>"
            "<div style='display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:520px;margin:0 auto 20px'>"
            # OF preset
            "<form method='POST' action='/chatting/create_preset' style='margin:0'>"
            "<input type='hidden' name='preset' value='of'>"
            "<button type='submit' style='width:100%;display:flex;flex-direction:column;align-items:center;gap:8px;padding:24px 14px;background:linear-gradient(135deg,#0099ff,#0066cc);border:0;color:#fff;border-radius:14px;cursor:pointer;font-family:inherit;box-shadow:0 6px 18px rgba(0,153,255,.25)'>"
            "<span style='font-size:30px'>💌</span>"
            "<span style='font-weight:800;font-size:15px;letter-spacing:.3px'>EDT OnlyFans</span>"
            "<span style='font-size:11px;opacity:.85;font-weight:500'>Planning OF</span>"
            "</button>"
            "</form>"
            # MYM preset
            "<form method='POST' action='/chatting/create_preset' style='margin:0'>"
            "<input type='hidden' name='preset' value='mym'>"
            "<button type='submit' style='width:100%;display:flex;flex-direction:column;align-items:center;gap:8px;padding:24px 14px;background:linear-gradient(135deg,#ff4d8d,#a855f7);border:0;color:#fff;border-radius:14px;cursor:pointer;font-family:inherit;box-shadow:0 6px 18px rgba(255,77,141,.25)'>"
            "<span style='font-size:30px'>📱</span>"
            "<span style='font-weight:800;font-size:15px;letter-spacing:.3px'>EDT MYM</span>"
            "<span style='font-size:11px;opacity:.85;font-weight:500'>Planning MYM</span>"
            "</button>"
            "</form>"
            "</div>"
            "<div style='color:#444;font-size:12px;margin:14px 0'>— OU —</div>"
            "<form method='POST' action='/chatting/create_edt' style='display:flex;gap:10px;align-items:stretch;max-width:380px;margin:0 auto'>"
            "<input type='text' name='name' placeholder='Nom custom' "
            "style='flex:1;padding:11px 14px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:10px;font-size:13px'>"
            "<button type='submit' style='background:#1a1a1a;border:1px solid #2a2a2a;color:#aaa;padding:11px 20px;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px;white-space:nowrap'>+ Custom</button>"
            "</form>"
            "<div style='font-size:11px;color:#666;margin-top:8px'>Tu pourras toujours en ajouter d'autres apres</div>"
            "</div>"
        )

    # Determiner l EDT actif
    active_id = (_req.args.get("edt_id") or "").strip()
    active_edt = None
    for e in edts:
        if e["id"] == active_id:
            active_edt = e
            break
    if not active_edt:
        active_edt = edts[0]

    # Couleurs statuts (matche le xlsx)
    statut_colors = {
        "Ancien":  {"bg": "#84e8c1", "fg": "#0a3d2c"},   # vert clair
        "Nouveau": {"bg": "#a3e0f0", "fg": "#062f47"},   # bleu clair
        "Support": {"bg": "#1f3a5f", "fg": "#cfe5ff"},   # bleu marine
    }
    pres_colors = {
        "Present": {"bg": "#86efac", "fg": "#14532d"},
        "Absent":  {"bg": "#fca5a5", "fg": "#7f1d1d"},
        "Retard":  {"bg": "#fed7aa", "fg": "#7c2d12"},
        "Coupure": {"bg": "#fef08a", "fg": "#713f12"},
        "OFF":     {"bg": "#525252", "fg": "#e5e5e5"},
    }
    creneau_colors = {
        "02h-08h": "#1d4ed8",
        "08h-14h": "#0e7490",
        "14h-20h": "#c2410c",
        "20h-02h": "#7e22ce",
    }

    # Tabs des EDTs : JS-only switch (no page reload)
    tabs_html = "".join(
        f"<a href='?tab=chatplanning&edt_id={e['id']}' "
        f"onclick='return chatSwitchTo(this.href)' data-no-loader='1' "
        f"class='chat-tab {'active' if e['id'] == active_edt['id'] else ''}' "
        f"style='padding:9px 18px;background:{'#1a1a1a' if e['id'] == active_edt['id'] else 'transparent'};"
        f"border:1px solid {'#3b82f6' if e['id'] == active_edt['id'] else '#262626'};"
        f"color:{'#fff' if e['id'] == active_edt['id'] else '#888'};"
        f"text-decoration:none;border-radius:10px;font-size:13px;font-weight:600'>{e['name']}</a>"
        for e in edts
    )
    # Detecte les presets deja crees (par nom contient OF / MYM)
    has_of = any("of" in (e.get("name","").lower()) for e in edts)
    has_mym = any("mym" in (e.get("name","").lower()) for e in edts)
    quick_btns = ""
    if not has_of:
        quick_btns += (
            "<form method='POST' action='/chatting/create_preset' style='margin:0;display:inline'>"
            "<input type='hidden' name='preset' value='of'>"
            "<button type='submit' style='padding:9px 14px;background:linear-gradient(135deg,#0099ff,#0066cc);border:0;color:#fff;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px'>💌 + EDT OF</button>"
            "</form>"
        )
    if not has_mym:
        quick_btns += (
            "<form method='POST' action='/chatting/create_preset' style='margin:0;display:inline'>"
            "<input type='hidden' name='preset' value='mym'>"
            "<button type='submit' style='padding:9px 14px;background:linear-gradient(135deg,#ff4d8d,#a855f7);border:0;color:#fff;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px'>📱 + EDT MYM</button>"
            "</form>"
        )
    add_tab = quick_btns + (
        "<button type='button' onclick=\"const n=prompt('Nom du nouveau planning ?'); if(n){const f=document.createElement('form');f.method='POST';f.action='/chatting/create_edt';f.innerHTML='<input name=name value=\\''+n+'\\'>';document.body.appendChild(f);f.submit();}\" "
        "style='padding:9px 14px;background:transparent;border:1px dashed #3b82f6;color:#3b82f6;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer'>+ Custom</button>"
    )
    # Renommer/Supprimer EDT actif
    edt_actions = (
        f"<form method='POST' action='/chatting/rename_edt' style='display:inline;margin:0' "
        f"onsubmit=\"const n=prompt('Nouveau nom ?', '{active_edt['name']}'); if(!n) return false; this.querySelector('[name=new_name]').value=n;\">"
        f"<input type='hidden' name='edt_id' value='{active_edt['id']}'>"
        f"<input type='hidden' name='new_name' value=''>"
        f"<button type='submit' style='background:transparent;border:0;color:#888;font-size:13px;cursor:pointer;padding:4px 8px'>✏ renommer</button>"
        f"</form>"
        f"<form method='POST' action='/chatting/delete_edt' style='display:inline;margin:0' "
        f"onsubmit=\"return confirm('Supprimer ce planning et toutes ses lignes ?')\">"
        f"<input type='hidden' name='edt_id' value='{active_edt['id']}'>"
        f"<button type='submit' style='background:transparent;border:0;color:#ef4444;font-size:13px;cursor:pointer;padding:4px 8px'>🗑 supprimer</button>"
        f"</form>"
    )

    # === Construction du tableau ===
    # Group rows by creneau (et conserve l ordre des creneaux)
    rows_by_cre = {c: [] for c in chatting.CRENEAUX}
    for r in active_edt.get("rows", []):
        c = r.get("creneau", "02h-08h")
        if c not in rows_by_cre:
            c = "02h-08h"
        rows_by_cre[c].append(r)

    # Genere les options pour les selects
    statut_opts = lambda v: "".join(
        f"<option value='{s}' {'selected' if s == v else ''}>{s}</option>" for s in chatting.STATUTS
    )
    off_opts = lambda v: "<option value=''></option>" + "".join(
        f"<option value='{s}' {'selected' if s == v else ''}>{s}</option>" for s in chatting.OFF_OPTIONS
    )
    # Liste des modeles disponibles pour cet EDT (Of ou MyM)
    available_modeles = chatting.models_for_edt(active_edt.get("name", ""))
    pres_opts = lambda v: "".join(
        f"<option value='{p}' {'selected' if p == v else ''}>{p}</option>"
        for p in chatting.PRESENCE_VALUES
    )

    def _select_cell(row_id, field, value, opts_html, bg, fg, width=None):
        wstyle = f"width:{width}px;" if width else ""
        return (
            f"<select class='chat-cell' data-row='{row_id}' data-field='{field}' "
            f"onchange='saveCell(this)' "
            f"style='{wstyle}background:{bg};color:{fg};border:0;padding:6px 4px;"
            f"border-radius:6px;font-weight:600;font-size:11.5px;cursor:pointer;font-family:inherit;text-align:center'>"
            f"{opts_html}</select>"
        )

    def _input_cell(row_id, field, value, placeholder=""):
        return (
            f"<input type='text' class='chat-cell' data-row='{row_id}' data-field='{field}' "
            f"value='{(value or '').replace(chr(39), chr(39)+chr(39))}' placeholder='{placeholder}' "
            f"onchange='saveCell(this)' "
            f"style='background:#1a1a1a;color:#fff;border:1px solid #2a2a2a;padding:6px 8px;"
            f"border-radius:6px;font-size:12px;width:120px'>"
        )

    body_rows = []
    for creneau in chatting.CRENEAUX:
        rows_in = rows_by_cre.get(creneau, [])
        cre_color = creneau_colors[creneau]
        # Si pas de lignes, ajoute une ligne placeholder avec le creneau cell
        if not rows_in:
            cre_only_cell = (
                f"<td class='chat-cre-cell' data-creneau='{creneau}' rowspan='1' "
                f"style='background:{cre_color};color:#fff;font-weight:700;text-align:center;"
                f"font-size:13px;padding:8px;border-right:2px solid #0a0a0a'>"
                f"{creneau.replace('h-', 'h - ').replace('-', ' - ')}h"
                f"</td>"
            )
            body_rows.append(
                f"<tr class='chat-empty-placeholder' data-creneau='{creneau}'>"
                f"{cre_only_cell}"
                f"<td colspan='13' style='padding:14px;color:#444;text-align:center;font-size:12px;font-style:italic'>aucune ligne — clique ci-dessous</td>"
                f"</tr>"
            )
        first = True
        for r in rows_in:
            counts = chatting.row_counts(r, active_week)
            pres_for_row = chatting.row_presence(r, active_week)
            cre_cell = ""
            if first:
                cre_cell = (
                    f"<td class='chat-cre-cell' data-creneau='{creneau}' rowspan='{len(rows_in)}' "
                    f"style='background:{cre_color};color:#fff;font-weight:700;text-align:center;"
                    f"font-size:13px;padding:8px;writing-mode:initial;border-right:2px solid #0a0a0a'>"
                    f"{creneau.replace('h-', 'h - ').replace('-', ' - ')}h"
                    f"</td>"
                )
                first = False
            # Pseudo
            pseudo_cell = f"<td style='padding:4px 6px'>{_input_cell(r['id'], 'pseudo', r.get('pseudo', ''), 'Pseudo')}</td>"
            # Statut
            sc = statut_colors.get(r.get("statut", "Nouveau"), statut_colors["Nouveau"])
            statut_cell = f"<td style='padding:4px 6px'>{_select_cell(r['id'], 'statut', r.get('statut', 'Nouveau'), statut_opts(r.get('statut', 'Nouveau')), sc['bg'], sc['fg'], 90)}</td>"
            # Modele : multi-select (genere "Amelia+Lola" alpha auto)
            current_mod = r.get('modele', '')
            current_set = set([m.strip() for m in current_mod.split('+') if m.strip()])
            chips_html = ""
            for m in available_modeles:
                checked = m in current_set
                chips_html += (
                    f"<label style='display:flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;border-radius:5px;font-size:12px;color:#ccc' onmouseover=\"this.style.background='#222'\" onmouseout=\"this.style.background='transparent'\">"
                    f"<input type='checkbox' value='{m}' {'checked' if checked else ''} onchange='modelToggle(this, \"{r['id']}\")' style='accent-color:#3b82f6'>"
                    f"<span>{m}</span></label>"
                )
            display = current_mod if current_mod else "—"
            modele_cell = (
                f"<td style='padding:4px 6px;position:relative'>"
                f"<button type='button' class='mod-trigger' data-row='{r['id']}' onclick='modelOpen(this)' "
                f"style='width:150px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;padding:6px 10px;border-radius:6px;font-size:11.5px;font-weight:600;cursor:pointer;font-family:inherit;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                f"{display} ▾</button>"
                f"<div class='mod-pop' style='display:none;position:absolute;top:100%;left:6px;z-index:60;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:8px;padding:4px;min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,.5);margin-top:4px'>"
                f"{chips_html}"
                f"</div>"
                f"</td>"
            )
            # OFF
            off_cell = f"<td style='padding:4px 6px'>{_select_cell(r['id'], 'off', r.get('off', ''), off_opts(r.get('off', '')), '#1a1a1a', '#aaa', 110)}</td>"
            # Days - presence pour la semaine active
            day_cells = ""
            for dk in chatting.DAYS:
                pv = pres_for_row.get(dk, "Present")
                pc = pres_colors.get(pv, pres_colors["Present"])
                day_cells += f"<td style='padding:4px 4px'>{_select_cell(r['id'], dk, pv, pres_opts(pv), pc['bg'], pc['fg'], 85)}</td>"
            # Retards/absences
            retards_cell = f"<td id='retards-{r['id']}' style='text-align:center;color:{'#fb923c' if counts['retards'] else '#666'};font-weight:700;padding:6px'>{counts['retards']}</td>"
            absences_cell = f"<td id='absences-{r['id']}' style='text-align:center;color:{'#ef4444' if counts['absences'] else '#666'};font-weight:700;padding:6px'>{counts['absences']}</td>"
            # Delete
            del_btn = f"<td style='text-align:center'><button type='button' onclick='deleteRow(\"{r['id']}\")' style='background:transparent;border:0;color:#666;font-size:16px;cursor:pointer;padding:0 8px'>×</button></td>"
            body_rows.append(
                f"<tr data-rowid='{r['id']}'>{cre_cell}{pseudo_cell}{statut_cell}{modele_cell}{off_cell}{day_cells}{retards_cell}{absences_cell}{del_btn}</tr>"
            )
        # Bouton "+ ajouter ligne" sous chaque creneau (AJAX, no reload)
        body_rows.append(
            f"<tr id='addrow-{creneau}'><td colspan='14' style='padding:6px;background:#0d0d0d;border-top:1px solid #1a1a1a'>"
            f"<button type='button' onclick='addChatRow(\"{creneau}\")' "
            f"style='background:transparent;border:1px dashed #2a2a2a;color:#666;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;width:100%;font-family:inherit'>"
            f"+ ajouter une ligne sur {creneau}</button>"
            f"</td></tr>"
        )

    # Header tableau - jours avec dates de la semaine
    today_iso = chatting.current_week_start()  # used only as a marker
    today_real = chatting.date.today().isoformat()
    day_headers = "".join(
        f"<th style='background:#1a1a1a;color:#3b82f6;font-weight:700;padding:10px 8px;font-size:12px;{'border-bottom:2px solid #3b82f6' if d.isoformat() == today_real else ''}'>"
        f"{name}<div style='font-size:10px;color:#888;font-weight:500;margin-top:2px'>{d.day:02d}/{d.month:02d}</div>"
        f"</th>"
        for d, name in zip(week_dates, chatting.DAYS_FULL)
    )
    header = (
        "<thead><tr>"
        "<th style='background:#0a0a0a;color:#3b82f6;font-weight:700;padding:10px 6px;font-size:12px;border-right:2px solid #0a0a0a;width:80px'>Creneau</th>"
        "<th style='background:#1a1a1a;color:#3b82f6;font-weight:700;padding:10px 6px;font-size:12px'>Pseudo</th>"
        "<th style='background:#1a1a1a;color:#3b82f6;font-weight:700;padding:10px 6px;font-size:12px'>Statut</th>"
        "<th style='background:#1a1a1a;color:#3b82f6;font-weight:700;padding:10px 6px;font-size:12px'>Modele</th>"
        "<th style='background:#1a1a1a;color:#3b82f6;font-weight:700;padding:10px 6px;font-size:12px'>OFF</th>"
        + day_headers +
        "<th style='background:#1a1a1a;color:#fb923c;font-weight:700;padding:10px 6px;font-size:12px'>Retards</th>"
        "<th style='background:#1a1a1a;color:#ef4444;font-weight:700;padding:10px 6px;font-size:12px'>Absences</th>"
        "<th style='background:#1a1a1a'></th>"
        "</tr></thead>"
    )
    table = (
        f"<div style='overflow-x:auto;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px'>"
        f"<table style='width:100%;border-collapse:separate;border-spacing:0;font-size:12px'>"
        f"{header}<tbody>{''.join(body_rows)}</tbody></table></div>"
    )

    # Footer legend
    legend = (
        "<div style='margin-top:14px;padding:12px 16px;background:#161616;border:1px solid #232323;border-radius:10px;display:flex;flex-wrap:wrap;gap:18px;font-size:12px'>"
        "<span style='color:#666;letter-spacing:.5px;font-weight:600'>PRESENCE :</span>"
        + "".join(
            f"<span style='display:flex;align-items:center;gap:5px'><span style='width:14px;height:14px;background:{pres_colors[p]['bg']};border-radius:3px'></span>{p}</span>"
            for p in chatting.PRESENCE_VALUES
        )
        + "<span style='color:#666;letter-spacing:.5px;font-weight:600;margin-left:16px'>STATUT :</span>"
        + "".join(
            f"<span style='display:flex;align-items:center;gap:5px'><span style='width:14px;height:14px;background:{statut_colors[s]['bg']};border-radius:3px'></span>{s}</span>"
            for s in chatting.STATUTS
        )
        + "</div>"
    )

    js = """
<script>
// AJAX switch entre EDTs et semaines : remplace juste le contenu de #form-chatplanning
window.chatSwitchTo = async function(url){
  const sec = document.getElementById('form-chatplanning');
  if(!sec) return true;
  // Visual feedback : leger fade
  sec.style.opacity = '0.5';
  sec.style.pointerEvents = 'none';
  try {
    const r = await fetch(url, {headers:{'X-Chat-Ajax':'1'}});
    const html = await r.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newSec = doc.getElementById('form-chatplanning');
    if(newSec){
      sec.innerHTML = newSec.innerHTML;
      // Update URL sans reload
      history.pushState({}, '', url);
      // Re-execute les scripts inline (sinon les fonctions saveCell/addChatRow etc disparaissent)
      sec.querySelectorAll('script').forEach(oldScript=>{
        const newScript = document.createElement('script');
        newScript.textContent = oldScript.textContent;
        oldScript.parentNode.replaceChild(newScript, oldScript);
      });
    }
  } catch(e){
    console.error('chatSwitchTo:', e);
    window.location.href = url;
    return false;
  }
  sec.style.opacity = '';
  sec.style.pointerEvents = '';
  return false;
};

// Restaure le scroll vers le tableau apres un switch
window.addEventListener('popstate', ()=>{ window.chatSwitchTo(window.location.href); });

async function saveCell(el){
  const fd = new FormData();
  fd.set('edt_id', '""" + active_edt['id'] + """');
  fd.set('row_id', el.dataset.row);
  fd.set('field', el.dataset.field);
  fd.set('value', el.value);
  fd.set('week_start', '""" + active_week + """');
  // Si c'est un select de presence, mettre a jour la couleur immediatement
  const PRES_COL = {Present:['#86efac','#14532d'], Absent:['#fca5a5','#7f1d1d'], Retard:['#fed7aa','#7c2d12'], Coupure:['#fef08a','#713f12'], OFF:['#525252','#e5e5e5']};
  const STA_COL = {Ancien:['#84e8c1','#0a3d2c'], Nouveau:['#a3e0f0','#062f47'], Support:['#1f3a5f','#cfe5ff']};
  if(PRES_COL[el.value] && ['lun','mar','mer','jeu','ven','sam','dim'].includes(el.dataset.field)){
    el.style.background = PRES_COL[el.value][0];
    el.style.color = PRES_COL[el.value][1];
  }
  if(STA_COL[el.value] && el.dataset.field === 'statut'){
    el.style.background = STA_COL[el.value][0];
    el.style.color = STA_COL[el.value][1];
  }
  await fetch('/chatting/update_cell', {method:'POST', body:fd});
  // Update counts si on a touche un jour
  if(['lun','mar','mer','jeu','ven','sam','dim'].includes(el.dataset.field)){
    const row = el.dataset.row;
    const cells = document.querySelectorAll('select[data-row=\"'+row+'\"]');
    let ret=0, abs=0;
    cells.forEach(c=>{
      if(['lun','mar','mer','jeu','ven','sam','dim'].includes(c.dataset.field)){
        if(c.value==='Retard') ret++;
        else if(c.value==='Absent') abs++;
      }
    });
    document.getElementById('retards-'+row).textContent = ret;
    document.getElementById('absences-'+row).textContent = abs;
    document.getElementById('retards-'+row).style.color = ret ? '#fb923c' : '#666';
    document.getElementById('absences-'+row).style.color = abs ? '#ef4444' : '#666';
  }
}
async function deleteRow(rid){
  if(!confirm('Supprimer cette ligne ?')) return;
  const fd = new FormData();
  fd.set('edt_id', '""" + active_edt['id'] + """');
  fd.set('row_id', rid);
  await fetch('/chatting/delete_row', {method:'POST', body:fd});
  const tr = document.querySelector('tr[data-rowid=\"'+rid+'\"]');
  if(!tr) return;
  // Si cette tr contient la cellule creneau rowspan, il faut la transferer a la suivante
  const creCell = tr.querySelector('td.chat-cre-cell');
  if(creCell){
    const creneau = creCell.dataset.creneau;
    const curSpan = parseInt(creCell.getAttribute('rowspan')||'1');
    if(curSpan > 1){
      // Trouve la TR suivante dans le meme groupe et lui pose la cellule en debut
      const nextTr = tr.nextElementSibling;
      if(nextTr && nextTr.dataset.rowid){
        const clone = creCell.cloneNode(true);
        clone.setAttribute('rowspan', String(curSpan - 1));
        nextTr.insertBefore(clone, nextTr.firstChild);
      }
    }
  } else {
    // Decremente le rowspan du creneau cell trouve dans une autre tr
    const trAnyInGroup = tr.previousElementSibling || tr.nextElementSibling;
    let groupCell = document.querySelector('td.chat-cre-cell');
    // Cherche la cellule chat-cre-cell du meme groupe (parcours les soeurs)
    let cur = tr;
    while(cur){
      const cc = cur.querySelector?.('td.chat-cre-cell');
      if(cc){ groupCell = cc; break; }
      cur = cur.previousElementSibling;
    }
    if(groupCell){
      const cur2 = parseInt(groupCell.getAttribute('rowspan')||'1');
      if(cur2 > 1) groupCell.setAttribute('rowspan', String(cur2 - 1));
    }
  }
  tr.remove();
}

// Liste des options par select
const PRES_OPTS = ['Present','Absent','Retard','Coupure','OFF'];
const STA_OPTS = ['Ancien','Nouveau','Support'];
const OFF_OPTS = ['', 'FULLTIME','Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche','PAS DE REPONSE'];
const MODELE_OPTS = ['','Julia','Amelia','Lola','Sarah','Emma','Amelia+Lola','Lola+Emma','Julia+Sarah','Les 3 (Julia+Amelia+Lola)','Toutes (Julia+Amelia+Lola+Sarah+Emma)'];

// Pas de label '(vide)' - on laisse l option vide
function _opt(v, sel){ return '<option value=\"'+v+'\"'+(v===sel?' selected':'')+'>'+v+'</option>'; }

// === Multi-select Modele ===
window.AVAILABLE_MODELES = """ + json.dumps(available_modeles) + """;

function modelOpen(btn){
  document.querySelectorAll('.mod-pop').forEach(p=>{ if(p !== btn.nextElementSibling) p.style.display='none'; });
  const pop = btn.nextElementSibling;
  pop.style.display = (pop.style.display === 'block') ? 'none' : 'block';
}
document.addEventListener('click', function(e){
  if(!e.target.closest('.mod-trigger') && !e.target.closest('.mod-pop')){
    document.querySelectorAll('.mod-pop').forEach(p=>p.style.display='none');
  }
});

function modelToggle(checkbox, rowId){
  const pop = checkbox.closest('.mod-pop');
  const checked = Array.from(pop.querySelectorAll('input[type=checkbox]:checked')).map(c=>c.value);
  checked.sort();
  const value = checked.join('+');
  const trigger = pop.previousElementSibling;
  if(trigger) trigger.innerHTML = (value || '—') + ' ▾';
  const fake = {dataset:{row:rowId, field:'modele'}, value:value};
  saveCell(fake);
}

async function addChatRow(creneau){
  const fd = new FormData();
  fd.set('edt_id', '""" + active_edt['id'] + """');
  fd.set('creneau', creneau);
  const r = await fetch('/chatting/add_row', {method:'POST', body:fd});
  const j = await r.json();
  if(!j.ok){ alert('Erreur: '+(j.error||'?')); return; }
  const rid = j.row_id;
  // Si une row placeholder 'aucune ligne' existait, on la vire
  const placeholder = document.querySelector('tr.chat-empty-placeholder[data-creneau=\"'+creneau+'\"]');
  if(placeholder) placeholder.remove();
  const STA_COL = {Ancien:['#84e8c1','#0a3d2c'], Nouveau:['#a3e0f0','#062f47'], Support:['#1f3a5f','#cfe5ff']};
  const sta = 'Nouveau';
  const stCol = STA_COL[sta];
  const statutSel = '<select class=chat-cell data-row='+rid+' data-field=statut onchange=saveCell(this) style=\"width:90px;background:'+stCol[0]+';color:'+stCol[1]+';border:0;padding:6px 4px;border-radius:6px;font-weight:600;font-size:11.5px;cursor:pointer;font-family:inherit;text-align:center\">' + STA_OPTS.map(o=>_opt(o,sta)).join('') + '</select>';
  // Modele : multi-select wrapper
  let chipsHtml = '';
  (window.AVAILABLE_MODELES || []).forEach(m=>{
    chipsHtml += '<label style=\"display:flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;border-radius:5px;font-size:12px;color:#ccc\" onmouseover=\"this.style.background=\\'#222\\'\" onmouseout=\"this.style.background=\\'transparent\\'\"><input type=checkbox value=\"'+m+'\" onchange=\"modelToggle(this,\\''+rid+'\\')\" style=accent-color:#3b82f6><span>'+m+'</span></label>';
  });
  const modeleSel = '<div style=position:relative><button type=button class=mod-trigger data-row='+rid+' onclick=modelOpen(this) style=\"width:150px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;padding:6px 10px;border-radius:6px;font-size:11.5px;font-weight:600;cursor:pointer;font-family:inherit;text-align:center\">— ▾</button><div class=mod-pop style=\"display:none;position:absolute;top:100%;left:0;z-index:60;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:8px;padding:4px;min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,.5);margin-top:4px\">'+chipsHtml+'</div></div>';
  const offSel = '<select class=chat-cell data-row='+rid+' data-field=off onchange=saveCell(this) style=\"width:110px;background:#1a1a1a;color:#aaa;border:0;padding:6px 4px;border-radius:6px;font-weight:600;font-size:11.5px;cursor:pointer;font-family:inherit;text-align:center\">' + OFF_OPTS.map(o=>_opt(o,'')).join('') + '</select>';
  const days = ['lun','mar','mer','jeu','ven','sam','dim'];
  let dayCells = '';
  days.forEach(dk=>{
    const opts = PRES_OPTS.map(o=>_opt(o,'Present')).join('');
    dayCells += '<td style=padding:4px><select class=chat-cell data-row='+rid+' data-field='+dk+' onchange=saveCell(this) style=\"width:85px;background:#86efac;color:#14532d;border:0;padding:6px 4px;border-radius:6px;font-weight:600;font-size:11.5px;cursor:pointer;font-family:inherit;text-align:center\">'+opts+'</select></td>';
  });
  // Chercher si une cellule rowspan existe deja pour ce creneau
  const existingCreCell = document.querySelector('td.chat-cre-cell[data-creneau=\"'+creneau+'\"]');
  let creCellHtml = '';
  if(existingCreCell){
    // Extend le rowspan
    const cur = parseInt(existingCreCell.getAttribute('rowspan')||'1');
    existingCreCell.setAttribute('rowspan', String(cur+1));
  } else {
    // Premier element du groupe : creer la creneau cell
    const CRE_COLORS = {'02h-08h':'#1d4ed8','08h-14h':'#0e7490','14h-20h':'#c2410c','20h-02h':'#7e22ce'};
    creCellHtml = '<td class=chat-cre-cell data-creneau=\"'+creneau+'\" rowspan=1 style=\"background:'+CRE_COLORS[creneau]+';color:#fff;font-weight:700;text-align:center;font-size:13px;padding:8px;border-right:2px solid #0a0a0a\">'+creneau.replace('h-','h - ').replace('-',' - ')+'h</td>';
  }
  const tr = document.createElement('tr');
  tr.dataset.rowid = rid;
  tr.innerHTML = creCellHtml
    + '<td style=padding:4px><input type=text class=chat-cell data-row='+rid+' data-field=pseudo value=\"\" placeholder=Pseudo onchange=saveCell(this) style=\"background:#1a1a1a;color:#fff;border:1px solid #2a2a2a;padding:6px 8px;border-radius:6px;font-size:12px;width:120px\"></td>'
    + '<td style=padding:4px>'+statutSel+'</td>'
    + '<td style=padding:4px>'+modeleSel+'</td>'
    + '<td style=padding:4px>'+offSel+'</td>'
    + dayCells
    + '<td id=retards-'+rid+' style=\"text-align:center;color:#666;font-weight:700;padding:6px\">0</td>'
    + '<td id=absences-'+rid+' style=\"text-align:center;color:#666;font-weight:700;padding:6px\">0</td>'
    + '<td style=text-align:center><button type=button onclick=deleteRow(\"'+rid+'\") style=\"background:transparent;border:0;color:#666;font-size:16px;cursor:pointer;padding:0 8px\">×</button></td>';
  const anchor = document.getElementById('addrow-'+creneau);
  anchor.parentNode.insertBefore(tr, anchor);
}
</script>
"""

    # === Navigation semaine ===
    is_current = (active_week == today_week)
    week_nav = (
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"padding:14px 18px;background:linear-gradient(135deg,#161616,#0f0f0f);"
        f"border:1px solid #2a2a2a;border-radius:14px;margin-bottom:14px;flex-wrap:wrap;gap:10px'>"
        # Prev arrow
        f"<a href='?tab=chatplanning&edt_id={active_edt['id']}&week_start={prev_week}' onclick='return chatSwitchTo(this.href)' data-no-loader='1' "
        f"style='display:flex;align-items:center;gap:8px;color:#fff;text-decoration:none;"
        f"padding:8px 14px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;"
        f"font-size:13px;font-weight:600;transition:.12s' "
        f"onmouseover='this.style.background=\"#222\"' onmouseout='this.style.background=\"#1a1a1a\"'>"
        f"<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' "
        f"stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='15 18 9 12 15 6'/></svg>"
        f"Semaine precedente</a>"
        # Middle (current week info)
        f"<div style='display:flex;flex-direction:column;align-items:center;gap:2px;text-align:center;flex:1;min-width:200px'>"
        f"<div style='display:flex;align-items:center;gap:10px'>"
        f"<span style='font-size:11px;color:#888;letter-spacing:1.5px;text-transform:uppercase'>Semaine {iso_w}</span>"
        + (f"<span style='background:#3b82f6;color:#fff;font-size:10px;padding:2px 8px;border-radius:6px;font-weight:700;letter-spacing:.5px'>EN COURS</span>" if is_current else f"<a href='?tab=chatplanning&edt_id={active_edt['id']}&week_start={today_week}' onclick='return chatSwitchTo(this.href)' data-no-loader='1' style='background:#3b82f6;color:#fff;font-size:10px;padding:3px 10px;border-radius:6px;font-weight:700;letter-spacing:.5px;text-decoration:none;cursor:pointer'>Revenir a aujourd hui</a>")
        + f"</div>"
        f"<div style='color:#fff;font-size:17px;font-weight:700;letter-spacing:-.01em'>{week_lbl}</div>"
        f"</div>"
        # Next arrow
        f"<a href='?tab=chatplanning&edt_id={active_edt['id']}&week_start={next_week}' onclick='return chatSwitchTo(this.href)' data-no-loader='1' "
        f"style='display:flex;align-items:center;gap:8px;color:#fff;text-decoration:none;"
        f"padding:8px 14px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;"
        f"font-size:13px;font-weight:600;transition:.12s' "
        f"onmouseover='this.style.background=\"#222\"' onmouseout='this.style.background=\"#1a1a1a\"'>"
        f"Semaine suivante"
        f"<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' "
        f"stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='9 18 15 12 9 6'/></svg>"
        f"</a>"
        f"</div>"
    )

    return (
        "<div style='max-width:1500px'>"
        "<h2 style='margin:0 0 6px;font-size:20px'>💬 Emploi du temps chatteurs</h2>"
        "<p style='margin:0 0 16px;color:#888;font-size:13px'>"
        f"Planning <b>{active_edt['name']}</b> — clique sur n importe quelle cellule pour la modifier. "
        f"Les pseudos / statuts / modeles restent fixes, la <b>presence change par semaine</b>."
        "</p>"
        # Tabs EDTs
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;align-items:center'>"
        + tabs_html + add_tab +
        "</div>"
        f"<div style='margin:0 0 14px;color:#666;font-size:11px'>{edt_actions}</div>"
        + week_nav
        + table
        + legend
        + js
        + "</div>"
    )


def _render_mypulslive_html() -> str:

    # Identites pour le dropdown "Model"
    try:
        identities = sorted(_list_identities())
    except Exception:
        identities = []

    # Couleur deterministe par chatteur
    def _color_for(name: str) -> str:
        h = int(_hash.md5((name or "?").lower().encode()).hexdigest()[:8], 16)
        return f"hsl({h % 360},70%,55%)"

    DAYS = chatting.DAYS
    DAYS_FULL = chatting.DAYS_FULL

    # Heures affichees (5h-3h+1 = 22 heures pour couvrir une journee de chat)
    hours_range = list(range(5, 24)) + list(range(0, 4))  # 5h matin -> 3h nuit
    hour_height_px = 32

    # Helpers pour position des shifts
    def _hour_to_offset(h: int, m: int) -> int:
        """Position en px depuis le haut de la grille."""
        if h in hours_range:
            idx = hours_range.index(h)
        elif h < 5:
            idx = len(hours_range) - 1 + (h - 3)  # rare : avant 5h matin
        else:
            idx = 0
        return idx * hour_height_px + (m * hour_height_px // 60)

    def _shift_block(s):
        sh, sm = map(int, s["start"].split(":"))
        eh, em = map(int, s["end"].split(":"))
        top = _hour_to_offset(sh, sm)
        bot = _hour_to_offset(eh, em)
        height = max(20, bot - top)
        color = _color_for(s["chatter"])
        model = s.get("model", "")
        model_tag = f"<div style='font-size:9.5px;color:rgba(255,255,255,.85);overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>🎯 {model}</div>" if model else ""
        return (
            f"<div onclick='editShift(\"{s['id']}\")' "
            f"style='position:absolute;top:{top}px;left:4px;right:4px;height:{height}px;"
            f"background:linear-gradient(135deg,{color},hsla(0,0%,0%,.2));"
            f"border-left:3px solid {color};border-radius:8px;padding:4px 6px;"
            f"overflow:hidden;cursor:pointer;color:#fff;box-shadow:0 2px 6px rgba(0,0,0,.3);"
            f"transition:transform .12s' onmouseover='this.style.transform=\"translateX(2px)\"' "
            f"onmouseout='this.style.transform=\"none\"'>"
            f"<div style='font-size:11px;font-weight:700;letter-spacing:.2px'>{s['chatter']}</div>"
            f"<div style='font-size:10px;color:rgba(255,255,255,.8);font-family:monospace'>{s['start']} → {s['end']}</div>"
            f"{model_tag}"
            f"</div>"
        )

    # === Header: stats + form add ===
    stats_html = (
        "<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px'>"
        f"<div class='box' style='text-align:center;padding:14px'>"
        f"<div style='font-size:24px;font-weight:800;color:#fff'>{stats['shifts_count']}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-top:4px'>Shifts</div></div>"
        f"<div class='box' style='text-align:center;padding:14px'>"
        f"<div style='font-size:24px;font-weight:800;color:#22c55e'>{len(chatters)}</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-top:4px'>Chatteurs</div></div>"
        f"<div class='box' style='text-align:center;padding:14px'>"
        f"<div style='font-size:24px;font-weight:800;color:#3b82f6'>{stats['total_hours']}h</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-top:4px'>Heures/semaine</div></div>"
        f"<div class='box' style='text-align:center;padding:14px'>"
        f"<div style='font-size:24px;font-weight:800;color:#a855f7'>{round(stats['total_hours']/7, 1)}h</div>"
        f"<div style='font-size:10px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-top:4px'>Moyenne/jour</div></div>"
        "</div>"
    )

    # === Add shift form ===
    day_opts = "".join(f"<option value='{d}'>{DAYS_FULL[d]}</option>" for d in DAYS)
    chatter_opts = "".join(f"<option value='{c}'>{c}</option>" for c in chatters)
    ident_opts = "<option value=''>(aucun modele)</option>" + "".join(f"<option value='{i}'>{i}</option>" for i in identities)

    add_form = (
        "<form method='POST' action='/chatting/add_shift' class='box' style='margin-bottom:18px;border:1px solid #2a2a2a'>"
        "<h3 style='margin:0 0 14px;font-size:15px'>➕ Ajouter un shift</h3>"
        "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:10px;align-items:end'>"
        "<div>"
        "<label style='font-size:11px'>Chatteur</label>"
        f"<input type='text' name='chatter' list='chat-existing' placeholder='ex: Lola' required>"
        f"<datalist id='chat-existing'>{chatter_opts}</datalist>"
        "</div>"
        "<div>"
        "<label style='font-size:11px'>Jour</label>"
        f"<select name='day' required>{day_opts}</select>"
        "</div>"
        "<div>"
        "<label style='font-size:11px'>Debut</label>"
        "<input type='time' name='start' value='09:00' required>"
        "</div>"
        "<div>"
        "<label style='font-size:11px'>Fin</label>"
        "<input type='time' name='end' value='17:00' required>"
        "</div>"
        "<div>"
        "<label style='font-size:11px'>Modele (optionnel)</label>"
        f"<select name='model'>{ident_opts}</select>"
        "</div>"
        "</div>"
        "<button type='submit' style='margin-top:14px;background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;border:0;padding:11px 22px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer'>+ Ajouter au planning</button>"
        "</form>"
    )

    # === Grille hebdo ===
    # Header colonnes (jours)
    day_headers = "".join(
        f"<div style='text-align:center;padding:10px 8px;color:#fff;font-weight:700;font-size:13px;letter-spacing:.5px;border-right:1px solid #1a1a1a;background:#161616'>"
        f"{DAYS_FULL[d]}"
        f"<div style='font-size:10px;color:#666;font-weight:500;margin-top:2px'>{stats['by_day'].get(d, 0):.1f}h</div>"
        f"</div>"
        for d in DAYS
    )

    # Colonne heures (gauche)
    hour_labels = "".join(
        f"<div style='height:{hour_height_px}px;font-size:10px;color:#666;padding:0 8px;text-align:right;line-height:{hour_height_px}px;font-family:monospace'>{h:02d}:00</div>"
        for h in hours_range
    )

    # Colonnes jours avec shifts
    day_cols = []
    total_height = len(hours_range) * hour_height_px
    for d in DAYS:
        shifts_today = shifts_by_day.get(d, [])
        blocks = "".join(_shift_block(s) for s in shifts_today)
        # Hour-grid lines
        lines = "".join(
            f"<div style='position:absolute;top:{i*hour_height_px}px;left:0;right:0;height:1px;background:#1a1a1a'></div>"
            for i in range(len(hours_range)+1)
        )
        day_cols.append(
            f"<div style='position:relative;border-right:1px solid #1a1a1a;height:{total_height}px;background:#0f0f0f'>"
            f"{lines}{blocks}"
            f"</div>"
        )
    day_cols_html = "".join(day_cols)

    grid = (
        f"<div style='background:#0a0a0a;border:1px solid #1a1a1a;border-radius:14px;overflow:hidden'>"
        # Header
        f"<div style='display:grid;grid-template-columns:60px repeat(7,1fr);border-bottom:1px solid #232323'>"
        f"<div style='background:#161616;border-right:1px solid #1a1a1a'></div>"
        f"{day_headers}"
        f"</div>"
        # Body
        f"<div style='display:grid;grid-template-columns:60px repeat(7,1fr)'>"
        f"<div style='background:#0d0d0d;border-right:1px solid #1a1a1a'>{hour_labels}</div>"
        f"{day_cols_html}"
        f"</div>"
        f"</div>"
    )

    # Legend chatteurs
    legend_items = "".join(
        f"<div style='display:flex;align-items:center;gap:6px;font-size:12px;color:#ccc'>"
        f"<span style='width:12px;height:12px;background:{_color_for(c)};border-radius:3px'></span>"
        f"{c}"
        f"</div>"
        for c in chatters
    )
    legend = (
        f"<div style='display:flex;flex-wrap:wrap;gap:14px;margin-top:14px;padding:12px 16px;background:#161616;border:1px solid #232323;border-radius:10px'>"
        f"<span style='color:#666;font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:600'>Equipe :</span>"
        f"{legend_items or '<span style=color:#666>Aucun chatteur encore</span>'}"
        f"</div>"
    )

    # Edit modal (cache par defaut, ouvert par JS)
    js = """
<script>
function editShift(sid){
  if(confirm('Supprimer ce shift ? Pour modifier, supprime + recree pour l instant.')){
    const fd = new FormData();
    fd.set('shift_id', sid);
    fetch('/chatting/delete_shift', {method:'POST', body:fd}).then(()=>location.reload());
  }
}
</script>
"""

    return (
        "<div style='max-width:1280px'>"
        "<h2 style='margin:0 0 6px;font-size:20px'>💬 Emploi du temps chatteurs</h2>"
        "<p style='margin:0 0 18px;color:#888;font-size:13px'>"
        "Planning hebdomadaire des shifts. Clique sur un shift pour le supprimer. "
        "<b>Recurrence hebdo</b> — c est ton modele de base, repete chaque semaine."
        "</p>"
        + stats_html
        + add_form
        + grid
        + legend
        + js
        + "</div>"
    )


def _render_mypulslive_html() -> str:
    """MyPuls Live - UI 'campagne' avec slots dynamiques (style MyPuls)."""
    import datetime as _dt
    try:
        import mypuls
        import mypuls_scheduler
    except Exception as e:
        return f"<p style='color:#f99'>Module mypuls indispo : {e}</p>"

    if not mypuls.is_configured():
        return (
            "<div style='max-width:680px'>"
            "<h2 style='margin:0 0 6px;font-size:20px'>MyPuls Live</h2>"
            "<div style='background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);"
            "border-radius:10px;padding:18px;color:#f99;margin-top:14px'>"
            "<b>Cookies MyPuls non configures.</b><br>"
            "Va dans <a href='?tab=mypuls' style='color:#3b82f6'>Settings → MyPuls</a> "
            "et colle tes cookies avant d utiliser le scheduler live."
            "</div></div>"
        )

    # Createurs
    res = mypuls.list_creators()
    creators_map = res.get("creators", {}) if res.get("ok") else {}

    # Captions defaut
    try:
        from schedule_xlsx import DEFAULT_CAPTIONS
        captions_default = "\n".join(DEFAULT_CAPTIONS)
        captions_count = len(DEFAULT_CAPTIONS)
    except Exception:
        captions_default = ""
        captions_count = 0

    today = _dt.date.today()
    week_later = today + _dt.timedelta(days=6)
    d_start = today.isoformat()
    d_end = week_later.isoformat()

    first_creator_name = ""
    first_creator_id = 0
    if creators_map:
        first_creator_name = sorted(creators_map.keys(), key=str.lower)[0]
        first_creator_id = creators_map[first_creator_name]

    # Couleur deterministe par createur (HSL, hue depend du nom)
    import hashlib as _hash
    def _color_for(name: str) -> tuple:
        h = int(_hash.md5((name or "?").lower().encode()).hexdigest()[:8], 16)
        hue = h % 360
        return (hue, f"hsl({hue},70%,60%)", f"hsla({hue},70%,60%,0.18)", f"hsla({hue},70%,60%,0.40)")

    first_hue, first_color, first_color_bg, first_color_border = _color_for(first_creator_name)

    # Campagnes actives
    try:
        import mypuls_campaigns
        active_campaigns = mypuls_campaigns.list_campaigns(active_only=False)
    except Exception:
        active_campaigns = []

    def _campaign_row(c):
        cid = c.get("id", "")
        cname = c.get("creator_name", "?")
        ctype = c.get("type", "?")
        active = c.get("active", False)
        sched_until = c.get("scheduled_until", "?")
        planned = c.get("total_planned", 0)
        slots_count = len(c.get("slots", []))
        active_color = "#22c55e" if active else "#666"
        active_label = "ACTIF" if active else "PAUSE"
        type_color = "#22c55e" if ctype == "post" else "#3b82f6"
        # Couleur deterministe du createur
        _hue, cr_color, cr_bg, cr_border = _color_for(cname)
        # Action buttons
        toggle_action = "pause" if active else "resume"
        toggle_label = "⏸" if active else "▶"
        return (
            f"<div style='display:flex;align-items:center;gap:10px;padding:11px 14px;"
            f"background:#0f0f0f;border:1px solid #232323;border-left:3px solid {cr_color};border-radius:10px;margin-bottom:6px'>"
            f"<img src='/mypuls/avatar/{c.get('creator_id')}' style='width:30px;height:30px;border-radius:50%;object-fit:cover;flex-shrink:0;border:1.5px solid {cr_color}' onerror=\"this.style.display='none'\">"
            f"<div style='flex:1;min-width:0'>"
            f"<div style='color:{cr_color};font-weight:700;font-size:13px'>{cname} <span style='color:{type_color};font-size:10px;letter-spacing:.5px;padding:2px 6px;background:rgba({34 if ctype=='post' else 59},{197 if ctype=='post' else 130},{94 if ctype=='post' else 246},.15);border-radius:5px;margin-left:6px'>{ctype.upper()}</span></div>"
            f"<div style='color:#888;font-size:11px;font-family:monospace;margin-top:2px'>{slots_count}/jour · planifie jusqu au {sched_until} · {planned} total</div>"
            f"</div>"
            f"<span style='color:{active_color};font-size:10px;font-weight:700;letter-spacing:.5px;padding:3px 8px;background:rgba({34 if active else 100},{197 if active else 100},{94 if active else 100},.12);border-radius:5px;flex-shrink:0'>{active_label}</span>"
            f"<form method='POST' action='/mypulslive/campaign/{toggle_action}' style='margin:0;display:inline'><input type='hidden' name='campaign_id' value='{cid}'><button type='submit' style='background:transparent;border:1px solid #444;color:#aaa;padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px'>{toggle_label}</button></form>"
            f"<form method='POST' action='/mypulslive/campaign/delete' style='margin:0;display:inline' onsubmit=\"return confirm('Supprimer cette campagne ? Les posts deja planifies restent sur MyPuls.')\"><input type='hidden' name='campaign_id' value='{cid}'><button type='submit' style='background:transparent;border:1px solid #5a2020;color:#ef4444;padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px'>×</button></form>"
            f"</div>"
        )

    campaigns_html = ""
    if active_campaigns:
        campaigns_html = (
            "<div style='background:#161616;border:1px solid #232323;border-radius:14px;padding:18px;margin-bottom:18px'>"
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:12px'>"
            "<span style='color:#888;font-size:11px;letter-spacing:1.2px;text-transform:uppercase'>♾️ Campagnes</span>"
            f"<span style='color:#666;font-size:11px'>{sum(1 for c in active_campaigns if c.get('active'))} actives / {len(active_campaigns)} total</span>"
            "</div>"
            + "".join(_campaign_row(c) for c in active_campaigns) +
            "</div>"
        )

    # Cards de createurs avec avatars + couleur unique + drag&drop
    def _creator_card(name, cid, active=False):
        hue, color, color_bg, color_border = _color_for(name)
        active_cls = " active" if active else ""
        return (
            f"<div class='mpl-cr-card{active_cls}' draggable='true' "
            f"data-id='{cid}' data-name='{name}' data-color='{color}' data-hue='{hue}' "
            f"style='--cr-color:{color};--cr-bg:{color_bg};--cr-border:{color_border}' "
            f"onclick='if(!this.__dragging) selectCreator({cid}, \"{name}\", \"{color}\", {hue})' "
            f"ondragstart='crDragStart(event)' ondragover='crDragOver(event)' "
            f"ondragleave='crDragLeave(event)' ondrop='crDrop(event)' ondragend='crDragEnd(event)'>"
            f"<div class='mpl-cr-grip'><svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='9' cy='5' r='1'/><circle cx='9' cy='12' r='1'/><circle cx='9' cy='19' r='1'/><circle cx='15' cy='5' r='1'/><circle cx='15' cy='12' r='1'/><circle cx='15' cy='19' r='1'/></svg></div>"
            f"<img src='/mypuls/avatar/{cid}' alt='{name}' loading='lazy' onerror=\"this.style.display='none'\">"
            f"<div class='mpl-cr-info'>"
            f"<div class='mpl-cr-name'>{name}</div>"
            f"<div class='mpl-cr-id'>#{cid}</div>"
            f"</div>"
            f"</div>"
        )
    # Appliquer l ordre custom de l user si dispo
    saved_order = mypuls.load_creator_order()
    name_by_id = {cid: name for name, cid in creators_map.items()}
    ordered_pairs = []
    seen = set()
    for cid in saved_order:
        if cid in name_by_id and cid not in seen:
            ordered_pairs.append((name_by_id[cid], cid))
            seen.add(cid)
    # Ajoute les nouveaux createurs (pas encore dans l ordre custom) a la fin, alphabetique
    for name, cid in sorted(creators_map.items(), key=lambda x: x[0].lower()):
        if cid not in seen:
            ordered_pairs.append((name, cid))
    creators_cards = "".join(
        _creator_card(name, cid, active=(cid == first_creator_id))
        for name, cid in ordered_pairs
    ) or "<div style='color:#666;padding:20px;text-align:center;font-size:13px'>Aucun createur. Verifie tes cookies MyPuls.</div>"

    style = """
<style>
.mpl-shell{max-width:920px;margin:0 auto}
.mpl-card{background:#161616;border:1px solid #232323;border-radius:18px;padding:28px;margin-bottom:22px}
.mpl-card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.mpl-name{font-size:24px;font-weight:700;color:#fff;display:flex;align-items:center;gap:10px;margin:6px 0}
.mpl-badge{background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;padding:3px 12px;border-radius:14px;font-size:11px;font-weight:700;letter-spacing:.5px}
.mpl-handle{color:#888;font-size:14px;margin-bottom:18px}
.mpl-banner{display:flex;align-items:center;gap:12px;padding:14px 18px;background:rgba(245,158,11,.05);border:1px solid rgba(245,158,11,.25);border-radius:14px;margin-bottom:18px}
.mpl-banner-dot{width:10px;height:10px;border-radius:50%;background:#f59e0b}
.mpl-banner-title{color:#fff;font-weight:600;font-size:14px;margin:0}
.mpl-banner-sub{color:#888;font-size:12.5px;margin:2px 0 0}
.mpl-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
.mpl-stat{background:#1a1a1a;border:1px solid #262626;border-radius:14px;padding:18px;text-align:center}
.mpl-stat-num{font-size:30px;font-weight:800;color:#fff;line-height:1}
.mpl-stat-lbl{font-size:11px;color:#888;letter-spacing:1px;margin-top:6px;text-transform:uppercase}
.mpl-section-label{font-size:11px;color:#666;letter-spacing:1.5px;text-transform:uppercase;margin:14px 0 8px;padding-left:4px}
.mpl-row{background:#1a1a1a;border:1px solid #262626;border-radius:14px;margin-bottom:8px;transition:background .15s}
.mpl-row:hover{background:#1e1e1e}
.mpl-row-head{display:flex;align-items:center;gap:14px;padding:16px 18px;cursor:pointer;user-select:none}
.mpl-row-icon{width:38px;height:38px;border-radius:10px;background:#222;display:flex;align-items:center;justify-content:center;color:#aaa;flex-shrink:0}
.mpl-row-icon svg{width:20px;height:20px}
.mpl-row-text{flex:1;min-width:0}
.mpl-row-title{color:#fff;font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px}
.mpl-row-sub{color:#888;font-size:12.5px;margin-top:2px}
.mpl-row-arrow{color:#888;transition:transform .15s}
.mpl-row.open .mpl-row-arrow{transform:rotate(180deg)}
.mpl-row-body{display:none;padding:0 18px 18px;border-top:1px solid #232323;margin-top:0}
.mpl-row.open .mpl-row-body{display:block;padding-top:14px}
.mpl-mini-badge{padding:2px 8px;font-size:10px;background:#262626;color:#888;border-radius:6px;letter-spacing:.5px;font-weight:700}
.mpl-mini-badge.green{background:rgba(34,197,94,.15);color:#22c55e}
.mpl-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px}

/* SLOTS */
.mpl-count-input{width:90px;text-align:center;font-size:18px;font-weight:700;padding:8px 10px;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;color:#fff}
.mpl-slots{display:flex;flex-direction:column;gap:8px;margin-top:14px}
.mpl-slot{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#0f0f0f;border:1px solid #232323;border-radius:12px}
.mpl-slot-badge{flex-shrink:0;width:42px;height:28px;border-radius:14px;background:rgba(59,130,246,.12);color:#3b82f6;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;letter-spacing:.5px}
.mpl-slot-time{flex:1;padding:8px 12px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;color:#fff;font-size:14px;font-family:inherit}
.mpl-slot-vis{flex-shrink:0;padding:7px 16px;border-radius:18px;font-size:12.5px;font-weight:600;cursor:pointer;border:1px solid #333;background:#1a1a1a;color:#aaa;display:flex;align-items:center;gap:6px;transition:.15s}
.mpl-slot-vis.public{background:#3b82f6;color:#fff;border-color:#3b82f6;box-shadow:0 0 0 1px #3b82f6 inset}
.mpl-slot-vis.private{background:#1a1a1a;color:#aaa}
.mpl-slot-vis svg{width:13px;height:13px}
.mpl-slot-rm{flex-shrink:0;width:28px;height:28px;border-radius:8px;background:transparent;border:0;color:#666;cursor:pointer;font-size:20px;line-height:1}
.mpl-slot-rm:hover{color:#ef4444;background:rgba(239,68,68,.1)}

/* TOGGLES (options) */
.mpl-opt{display:flex;align-items:center;gap:14px;padding:14px 16px;background:#0f0f0f;border:1px solid #232323;border-radius:12px;margin-bottom:8px;cursor:pointer;transition:.15s}
.mpl-opt:hover{background:#141414}
.mpl-opt.active{background:linear-gradient(135deg,rgba(59,130,246,.12),rgba(168,85,247,.08));border-color:rgba(59,130,246,.35)}
.mpl-opt-icon{width:36px;height:36px;border-radius:10px;background:rgba(59,130,246,.15);color:#3b82f6;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.mpl-opt-icon svg{width:18px;height:18px}
.mpl-opt-text{flex:1}
.mpl-opt-title{color:#fff;font-weight:600;font-size:14px;margin:0}
.mpl-opt-sub{color:#888;font-size:12.5px;margin:2px 0 0}
.mpl-opt-toggle{flex-shrink:0;width:44px;height:24px;background:#2a2a2a;border-radius:14px;position:relative;transition:.2s}
.mpl-opt-toggle::after{content:'';position:absolute;top:3px;left:3px;width:18px;height:18px;background:#888;border-radius:50%;transition:.2s}
.mpl-opt.active .mpl-opt-toggle{background:#3b82f6}
.mpl-opt.active .mpl-opt-toggle::after{transform:translateX(20px);background:#fff}

.mpl-push-btn{background:linear-gradient(135deg,#3b82f6,#a855f7);color:#fff;border:0;padding:14px 28px;border-radius:12px;font-weight:800;font-size:15px;cursor:pointer;box-shadow:0 6px 18px rgba(59,130,246,.35);display:inline-flex;align-items:center;gap:8px;letter-spacing:.3px}
.mpl-push-btn:hover{transform:translateY(-1px);box-shadow:0 8px 22px rgba(59,130,246,.45)}
.mpl-fetch-btn{background:#1a1a1a;border:1px solid #3b82f6;color:#3b82f6;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer}
.mpl-fetch-btn:hover{background:rgba(59,130,246,.1)}

/* Distinct visual identity per type */
.mpl-card-posts{border-left:3px solid rgba(34,197,94,.5)}
.mpl-card-stories{border-left:3px solid rgba(59,130,246,.5)}

/* === Creator cards (avatar + name + id) === */
.mpl-cr-bar{display:flex;gap:10px;overflow-x:auto;padding:4px 4px 8px;margin-bottom:20px;scrollbar-width:thin;scrollbar-color:#3b82f6 #1a1a1a}
.mpl-cr-bar::-webkit-scrollbar{height:6px}
.mpl-cr-bar::-webkit-scrollbar-track{background:#0f0f0f;border-radius:3px}
.mpl-cr-bar::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
.mpl-cr-bar::-webkit-scrollbar-thumb:hover{background:#3b82f6}
.mpl-cr-card{flex-shrink:0;display:flex;align-items:center;gap:10px;background:#0f0f0f;border:1px solid #232323;padding:8px 14px 8px 8px;border-radius:14px;cursor:pointer;transition:.15s;font-family:inherit;color:#ccc;min-width:160px;--cr-color:#3b82f6;--cr-bg:rgba(59,130,246,.18);--cr-border:rgba(59,130,246,.55)}
.mpl-cr-card:hover{background:#1a1a1a;border-color:var(--cr-border);transform:translateY(-1px)}
.mpl-cr-card.active{background:linear-gradient(135deg,var(--cr-bg),rgba(0,0,0,0.05));border-color:var(--cr-border);box-shadow:0 4px 14px var(--cr-bg);color:#fff}
.mpl-cr-card img{width:42px;height:42px;border-radius:50%;object-fit:cover;background:#222;flex-shrink:0;border:1.5px solid rgba(255,255,255,.06)}
.mpl-cr-card.active img{border-color:var(--cr-color)}
.mpl-cr-card.active .mpl-cr-name{color:var(--cr-color)}
.mpl-cr-grip{color:#444;opacity:0;transition:.15s;cursor:grab;flex-shrink:0;display:flex;align-items:center}
.mpl-cr-card:hover .mpl-cr-grip{opacity:1;color:#666}
.mpl-cr-card:active .mpl-cr-grip{cursor:grabbing}
.mpl-cr-card.dragging{opacity:.4;transform:scale(.95)}
.mpl-cr-card.drop-target{border-color:var(--cr-color);box-shadow:0 0 0 2px var(--cr-color) inset;transform:translateY(-2px)}
.mpl-cr-saved-hint{display:inline-block;font-size:10px;color:#22c55e;margin-left:6px;opacity:0;transition:opacity .2s}
.mpl-cr-saved-hint.show{opacity:1}
.mpl-cr-info{display:flex;flex-direction:column;align-items:flex-start;line-height:1.2;text-align:left}
.mpl-cr-name{font-size:14px;font-weight:700;letter-spacing:-.01em}
.mpl-cr-id{font-size:11px;color:#666;font-family:monospace;margin-top:2px}
.mpl-cr-card.active .mpl-cr-id{color:#aaa}
body.light .mpl-cr-card{background:#f9fafb;border-color:#e5e7eb;color:#374151}
body.light .mpl-cr-card:hover{background:#fff;border-color:#9ca3af}
body.light .mpl-cr-card.active{background:linear-gradient(135deg,#dbeafe,#ede9fe);color:#111;border-color:#3b82f6}

/* === PILL NAV (Auto-Post / Auto-Story / Auto-Delete) === */
.mpl-pillnav{display:flex;gap:6px;padding:6px;background:#0f0f0f;border:1px solid #232323;border-radius:14px;margin-bottom:20px}
.mpl-pillnav button{flex:1;display:flex;align-items:center;justify-content:center;gap:10px;background:transparent;border:0;color:#888;padding:11px 14px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;transition:.15s;font-family:inherit}
.mpl-pillnav button svg{width:18px;height:18px;flex-shrink:0}
.mpl-pillnav button:hover{background:#1a1a1a;color:#fff}
.mpl-pillnav button.active{background:#1f1f1f;color:#fff;box-shadow:0 0 0 1px #333 inset}
.mpl-pillnav button.active[data-tab=post]{background:linear-gradient(135deg,rgba(34,197,94,.15),rgba(34,197,94,.08));color:#22c55e;box-shadow:0 0 0 1px rgba(34,197,94,.4) inset}
.mpl-pillnav button.active[data-tab=story]{background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(59,130,246,.08));color:#3b82f6;box-shadow:0 0 0 1px rgba(59,130,246,.4) inset}
.mpl-pillnav button.active[data-tab=delete]{background:linear-gradient(135deg,rgba(168,85,247,.15),rgba(168,85,247,.08));color:#a855f7;box-shadow:0 0 0 1px rgba(168,85,247,.4) inset}
body.light .mpl-pillnav{background:#f3f4f6;border-color:#e5e7eb}
body.light .mpl-pillnav button{color:#6b7280}
body.light .mpl-pillnav button:hover{background:#fff;color:#111}

/* === Delete panel === */
.mpl-events{display:flex;flex-direction:column;gap:6px;margin-top:14px;max-height:480px;overflow-y:auto;padding-right:4px}
.mpl-event{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#0f0f0f;border:1px solid #222;border-radius:10px;font-size:13px;color:#ccc}
.mpl-event.selected{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.4)}
.mpl-event-cb{flex-shrink:0;width:18px;height:18px;accent-color:#ef4444}
.mpl-event-type{flex-shrink:0;padding:3px 8px;font-size:10px;border-radius:5px;font-weight:700;letter-spacing:.5px}
.mpl-event-type.feed{background:rgba(34,197,94,.15);color:#22c55e}
.mpl-event-type.story{background:rgba(59,130,246,.15);color:#3b82f6}
.mpl-event-date{flex-shrink:0;color:#888;font-family:monospace;font-size:12px}
.mpl-event-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

body.light .mpl-card{background:#fff;border-color:#e5e7eb}
body.light .mpl-stat,body.light .mpl-row,body.light .mpl-slot,body.light .mpl-opt{background:#f9fafb;border-color:#e5e7eb}
body.light .mpl-stat-num,body.light .mpl-row-title,body.light .mpl-name,body.light .mpl-opt-title,body.light .mpl-slot-time{color:#111;background:#fff}

/* === Custom WHEEL time picker (style iOS) === */
.mpl-wheel-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:9999;backdrop-filter:blur(4px);opacity:0;pointer-events:none;transition:opacity .15s}
.mpl-wheel-overlay.show{opacity:1;pointer-events:auto}
.mpl-wheel-modal{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:16px;width:330px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.6);transform:translateY(20px);transition:transform .2s}
.mpl-wheel-overlay.show .mpl-wheel-modal{transform:translateY(0)}
.mpl-wheel-head{padding:18px 22px 14px;border-bottom:1px solid #232323}
.mpl-wheel-head-title{font-size:11px;color:#888;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;margin-bottom:4px}
.mpl-wheel-head-sub{color:#fff;font-size:16px;font-weight:600;border-bottom:2px solid #3b82f6;padding-bottom:6px;display:inline-block}
.mpl-wheel-body{display:flex;justify-content:center;align-items:center;gap:24px;padding:18px 0;position:relative}
.mpl-wheel-body::before{content:'';position:absolute;left:30px;right:30px;top:50%;height:46px;transform:translateY(-50%);background:rgba(59,130,246,.06);border-top:1px solid rgba(59,130,246,.18);border-bottom:1px solid rgba(59,130,246,.18);pointer-events:none;border-radius:6px}
.mpl-wheel-col{height:240px;overflow-y:scroll;width:80px;scroll-snap-type:y mandatory;scrollbar-width:none;text-align:center;-webkit-mask-image:linear-gradient(180deg,transparent 0%,#000 25%,#000 75%,transparent 100%);mask-image:linear-gradient(180deg,transparent 0%,#000 25%,#000 75%,transparent 100%)}
.mpl-wheel-col::-webkit-scrollbar{display:none}
.mpl-wheel-item{height:46px;line-height:46px;font-size:22px;color:#666;scroll-snap-align:center;font-weight:500;transition:color .15s,font-size .15s,font-weight .15s}
.mpl-wheel-item.center{color:#3b82f6;font-weight:700;font-size:24px}
.mpl-wheel-sep{font-size:24px;color:#444;font-weight:300}
.mpl-wheel-foot{display:flex;border-top:1px solid #232323}
.mpl-wheel-btn{flex:1;background:transparent;border:0;color:#3b82f6;padding:14px;font-size:13px;font-weight:700;letter-spacing:1px;cursor:pointer;font-family:inherit;text-transform:uppercase}
.mpl-wheel-btn:hover{background:#222}
.mpl-wheel-btn.cancel{color:#888}

/* === Flatpickr custom dark theme (matches dashboard) === */
.flatpickr-calendar{background:#1a1a1a!important;border:1px solid #2a2a2a!important;border-radius:14px!important;box-shadow:0 12px 40px rgba(0,0,0,.5)!important;color:#fff!important;font-family:inherit!important}
.flatpickr-calendar::before,.flatpickr-calendar::after{display:none!important}
.flatpickr-months{background:transparent;color:#fff;padding:14px 12px 6px;border-bottom:1px solid #2a2a2a}
.flatpickr-months .flatpickr-month{background:transparent;color:#fff;height:auto}
.flatpickr-current-month{padding:0;font-size:14px;font-weight:600}
.flatpickr-current-month input.cur-year,.flatpickr-current-month .cur-month{color:#fff!important;font-weight:600!important;background:transparent!important}
.flatpickr-current-month .cur-month:hover{background:transparent!important}
.flatpickr-monthDropdown-months{background:#1a1a1a!important;color:#fff!important;border:0!important}
.flatpickr-monthDropdown-month{background:#1a1a1a!important;color:#fff!important}
.flatpickr-prev-month,.flatpickr-next-month{color:#888!important;fill:#888!important;padding:8px!important}
.flatpickr-prev-month:hover,.flatpickr-next-month:hover{color:#fff!important;fill:#fff!important;background:#262626!important;border-radius:6px!important}
.flatpickr-weekdays{background:transparent;padding:8px 0 4px}
span.flatpickr-weekday{color:#888!important;font-weight:600!important;background:transparent!important;font-size:11px!important;letter-spacing:.5px;text-transform:uppercase}
.flatpickr-day{color:#ccc!important;border-radius:50%!important;height:36px!important;line-height:36px!important;font-size:13.5px!important;border:0!important}
.flatpickr-day:hover{background:#262626!important;color:#fff!important;border-color:#262626!important}
.flatpickr-day.today{background:transparent!important;border:1px solid #3b82f6!important;color:#3b82f6!important;font-weight:700}
.flatpickr-day.selected,.flatpickr-day.selected:hover{background:#3b82f6!important;color:#fff!important;border-color:#3b82f6!important;font-weight:700;box-shadow:0 0 0 4px rgba(59,130,246,.18)!important}
.flatpickr-day.flatpickr-disabled,.flatpickr-day.prevMonthDay,.flatpickr-day.nextMonthDay{color:#444!important;opacity:.5}
.flatpickr-day.flatpickr-disabled:hover,.flatpickr-day.prevMonthDay:hover{background:transparent!important}

/* Time picker */
.flatpickr-time{border-top:1px solid #2a2a2a!important;background:transparent!important;padding:8px 0}
.flatpickr-time input{color:#fff!important;background:transparent!important;font-size:20px!important;font-weight:700;font-family:inherit!important}
.flatpickr-time input:hover,.flatpickr-time input:focus{background:#262626!important}
.flatpickr-time .flatpickr-time-separator{color:#666!important;font-size:20px}
.flatpickr-time .numInputWrapper:hover{background:#262626!important}
.flatpickr-time .arrowUp:after{border-bottom-color:#888!important}
.flatpickr-time .arrowDown:after{border-top-color:#888!important}
</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css">
<script src="https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/l10n/fr.js"></script>
"""

    form = f"""
<form method='POST' action='/mypulslive/push' id='mpl-form' onsubmit='return submitMyPulsForm(event)'>
  <input type='hidden' name='creator_id' id='mpl-creator-id' value='{first_creator_id}'>
  <input type='hidden' name='post_slots_json' id='mpl-post-slots-json' value='[]'>
  <input type='hidden' name='story_slots_json' id='mpl-story-slots-json' value='[]'>
  <input type='hidden' name='shuffle_media' id='mpl-shuffle-media' value='0'>
  <input type='hidden' name='infinite_recycle' id='mpl-recycle' value='1'>
  <input type='hidden' name='randomize_minutes' id='mpl-random-min' value='1'>

  <!-- PILL NAV : Auto-Post / Auto-Story / Auto-Delete -->
  <div class='mpl-pillnav'>
    <button type='button' data-tab='post' class='active' onclick='switchTab("post")'>
      <svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='3' rx='2'/><path d='M3 9h18'/><path d='M3 15h18'/><path d='M9 3v18'/><path d='M15 3v18'/></svg>
      Auto-Post
    </button>
    <button type='button' data-tab='story' onclick='switchTab("story")'>
      <svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><circle cx='12' cy='10' r='3'/><path d='M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662'/></svg>
      Auto-Story
    </button>
    <button type='button' data-tab='delete' onclick='switchTab("delete")'>
      <svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='4' rx='2' ry='2'/><line x1='16' x2='16' y1='2' y2='6'/><line x1='8' x2='8' y1='2' y2='6'/><line x1='3' x2='21' y1='10' y2='10'/><path d='M8 14h.01'/><path d='M12 14h.01'/><path d='M16 14h.01'/><path d='M8 18h.01'/><path d='M12 18h.01'/><path d='M16 18h.01'/></svg>
      Emploi du temps
    </button>
  </div>

  <input type='hidden' name='content_type' id='mpl-content-type' value='post'>

  <!-- Bloc dates (commun a post / story, masque pour delete) -->
  <div class='mpl-row open' id='mpl-dates-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='4' rx='2' ry='2'/><line x1='16' x2='16' y1='2' y2='6'/><line x1='8' x2='8' y1='2' y2='6'/><line x1='3' x2='21' y1='10' y2='10'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>Periode</div>
        <div class='mpl-row-sub'>Plage de dates a planifier</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <!-- Toggle Mode infini -->
      <label class='mpl-opt' style='margin:0 0 14px 0' id='mpl-infinite-toggle' onclick='toggleInfinite()'>
        <div class='mpl-opt-icon' style='background:rgba(168,85,247,.15);color:#a855f7'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M18.178 8c5.096 0 5.096 8 0 8-5.095 0-7.133-8-12.739-8-4.585 0-4.585 8 0 8 5.606 0 7.644-8 12.739-8z'/></svg></div>
        <div class='mpl-opt-text'>
          <p class='mpl-opt-title'>♾️ Mode infini (campagne continue)</p>
          <p class='mpl-opt-sub'>Schedule 2 jours a la fois. Le cron etend automatiquement tant que c est actif. Evite les rate-limits MyPuls.</p>
        </div>
        <div class='mpl-opt-toggle'></div>
      </label>
      <input type='hidden' name='infinite_mode' id='mpl-infinite' value='0'>

      <div class='mpl-2col'>
        <div>
          <label id='mpl-lbl-start'>Date debut</label>
          <input type='date' name='date_start' value='{d_start}' required>
        </div>
        <div id='mpl-end-wrap'>
          <label>Date fin</label>
          <input type='date' name='date_end' value='{d_end}'>
        </div>
      </div>
    </div>
  </div>

  <div class='mpl-section-label' id='mpl-planif-label'>Planification</div>

  <!-- POSTS card -->
  <div class='mpl-row open mpl-card-posts' id='mpl-posts-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon' style='background:rgba(34,197,94,.12);color:#22c55e'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='3' rx='2' ry='2'/><circle cx='9' cy='9' r='2'/><path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>📰 Posts (feed)<span class='mpl-mini-badge green' id='mpl-posts-tag'>9 / jour</span></div>
        <div class='mpl-row-sub'>Publications dans le feed (public ou prive) avec captions</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap'>
        <div>
          <div style='font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px'>Posts par jour</div>
          <input type='number' class='mpl-count-input' id='mpl-posts-count' value='9' min='0' max='24' oninput='renderPostSlots()'>
        </div>
        <div style='flex:1;min-width:200px;color:#888;font-size:13px'>
          Pour chaque post : 1 creneau = 1 publication par jour de la periode.<br>
          Clique sur le bouton bleu/gris pour basculer <b>Public ↔ Prive</b>.
        </div>
      </div>
      <div style='font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;margin:18px 0 6px'>Horaires de publication</div>
      <div class='mpl-slots' id='mpl-post-slots'></div>
      <button type='button' onclick='addPostSlot()' style='margin-top:10px;background:transparent;border:1px dashed #2e6f4e;color:#22c55e;padding:8px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600'>+ Ajouter un creneau post</button>
    </div>
  </div>

  <!-- STORIES card -->
  <div class='mpl-row open mpl-card-stories' id='mpl-stories-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon' style='background:rgba(59,130,246,.12);color:#3b82f6'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='14' height='20' x='5' y='2' rx='2' ry='2'/><line x1='12' x2='12' y1='18' y2='18'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>📱 Stories <span class='mpl-mini-badge' style='background:rgba(59,130,246,.15);color:#3b82f6' id='mpl-stories-tag'>4 / jour</span></div>
        <div class='mpl-row-sub'>Stories ephemères MyM (auto-supprimees au bout de 24h)</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap'>
        <div>
          <div style='font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px'>Stories par jour</div>
          <input type='number' class='mpl-count-input' id='mpl-stories-count' value='4' min='0' max='24' oninput='renderStorySlots()'>
        </div>
        <div style='flex:1;min-width:200px;color:#888;font-size:13px'>
          Audience par defaut : <code>everyone</code>. Pas de caption sur les stories.
        </div>
      </div>
      <div style='font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;margin:18px 0 6px'>Horaires des stories</div>
      <div class='mpl-slots' id='mpl-story-slots'></div>
      <button type='button' onclick='addStorySlot()' style='margin-top:10px;background:transparent;border:1px dashed #2e4f80;color:#3b82f6;padding:8px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600'>+ Ajouter une story</button>
    </div>
  </div>

  <!-- Auto-delete posts -->
  <div class='mpl-row' id='mpl-autodelete-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 6h18'/><path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6'/><path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>Auto-delete posts publics <span class='mpl-mini-badge green'>NATIF MYPULS</span></div>
        <div class='mpl-row-sub'>Supprime les posts publics apres delai. Les stories se suppriment seules au bout de 24h.</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <div class='mpl-2col'>
        <div>
          <label>Activer auto-delete</label>
          <select name='post_action' id='mpl-post-action' onchange='updatePostAction()'>
            <option value='delete' selected>Oui, supprimer apres delai</option>
            <option value='none'>Non, garder</option>
          </select>
        </div>
        <div id='mpl-post-delay-wrap'>
          <label>Apres combien de jours</label>
          <input type='number' name='post_delete_days' value='2' min='1' max='30' step='1'>
          <small>Defaut 2 jours = 48h. MyPuls le gere nativement.</small>
        </div>
      </div>
    </div>
  </div>

  <!-- Auto-Delete panel : Emploi du temps + Clean rapide -->
  <div class='mpl-row open' id='mpl-delete-block' style='display:none;border-left:3px solid rgba(239,68,68,.5)'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon' style='background:rgba(239,68,68,.12);color:#ef4444'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='4' rx='2' ry='2'/><line x1='16' x2='16' y1='2' y2='6'/><line x1='8' x2='8' y1='2' y2='6'/><line x1='3' x2='21' y1='10' y2='10'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title' style='font-size:15px'>Emploi du temps <span class='mpl-mini-badge' style='background:rgba(239,68,68,.15);color:#ef4444' id='mpl-del-count'>0</span></div>
        <div class='mpl-row-sub'>Calendrier des posts/stories planifies — clique un jour pour voir et supprimer</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body' id='mpl-calendar-block'>
      <!-- CALENDRIER (header + grille + detail) -->
      <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px'>
        <div style='display:flex;align-items:center;gap:4px'>
          <button type='button' onclick='calNav(-1)' style='width:32px;height:32px;background:#1a1a1a;color:#aaa;border:0;border-radius:8px;cursor:pointer;font-size:16px'>‹</button>
          <button type='button' onclick='calNav(1)' style='width:32px;height:32px;background:#1a1a1a;color:#aaa;border:0;border-radius:8px;cursor:pointer;font-size:16px'>›</button>
          <h4 id='mpl-cal-month-name' style='margin:0 0 0 10px;font-size:15px;font-weight:600;color:#fff;text-transform:capitalize'>mois</h4>
          <span class='mpl-mini-badge' id='mpl-cal-month-badge' style='background:rgba(168,85,247,.15);color:#a855f7;margin-left:8px'>...</span>
        </div>
        <div style='display:flex;align-items:center;gap:12px;font-size:11px;color:#888;flex-wrap:wrap'>
          <span style='display:flex;align-items:center;gap:5px'><span style='width:10px;height:10px;background:#3b82f6;border-radius:3px'></span>Public</span>
          <span style='display:flex;align-items:center;gap:5px'><span style='width:10px;height:10px;background:#737373;border-radius:3px'></span>Prive</span>
          <span style='display:flex;align-items:center;gap:5px'><span style='width:10px;height:10px;background:#a855f7;border-radius:3px'></span>Story</span>
          <button type='button' onclick='calToday()' style='padding:5px 11px;background:#3b82f6;color:#fff;border:0;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer'>Aujourd hui</button>
        </div>
      </div>

      <!-- Header jours de la semaine -->
      <div style='display:grid;grid-template-columns:repeat(7,1fr);margin-bottom:4px'>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Lun</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Mar</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Mer</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Jeu</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Ven</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Sam</div>
        <div style='font-size:10.5px;color:#666;font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.5px'>Dim</div>
      </div>

      <!-- Grille du mois (rempli en JS) -->
      <div id='mpl-cal-grid' style='display:grid;grid-template-columns:repeat(7,1fr);border-top:1px solid #1a1a1a;border-left:1px solid #1a1a1a;border-radius:8px;overflow:hidden;min-height:240px'>
        <div style='grid-column:1/-1;padding:60px;text-align:center;color:#666;font-size:13px'>Chargement...</div>
      </div>

      <!-- Detail jour selectionne (avec bouton delete) -->
      <div id='mpl-cal-day-detail' style='display:none;margin-top:14px;padding:14px;background:#0f0f0f;border:1px solid #232323;border-radius:10px'></div>

      <!-- Quick clean depuis date X -->
      <div style='background:linear-gradient(135deg,rgba(239,68,68,.06),rgba(239,68,68,.03));border:1px solid rgba(239,68,68,.25);border-radius:12px;padding:14px;margin-top:14px'>
        <div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>
          <svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#ef4444' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 6h18'/><path d='M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6'/><path d='M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2'/></svg>
          <span style='color:#ef4444;font-weight:700;font-size:13px;letter-spacing:.3px'>🧹 Clean rapide</span>
        </div>
        <p style='color:#aaa;font-size:12.5px;margin:0 0 10px;line-height:1.5'>
          Supprime <b>TOUS</b> les events a partir d une date (utile pour repartir de zero).
        </p>
        <div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap'>
          <input type='date' id='mpl-clean-from' value='{d_start}' style='flex:0 0 auto;max-width:180px'>
          <button type='button' onclick='quickClean()' style='background:#ef4444;border:0;color:#fff;padding:9px 16px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer'>
            🧹 Tout supprimer a partir de cette date
          </button>
          <small id='mpl-clean-status' style='color:#888'></small>
        </div>
      </div>

      <input type='hidden' name='delete_ids' id='mpl-delete-ids' value=''>
    </div>
  </div>

  <!-- Options -->
  <div class='mpl-section-label' id='mpl-options-label'>Options</div>

  <div class='mpl-opt active' id='opt-recycle' onclick='toggleOpt("opt-recycle","mpl-recycle")'>
    <div class='mpl-opt-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 12a9 9 0 1 1-6.219-8.56'/></svg></div>
    <div class='mpl-opt-text'>
      <p class='mpl-opt-title'>♾️ Recyclage infini</p>
      <p class='mpl-opt-sub'>Tes medias sont recycles dans l'ordre quand on arrive au bout de la liste</p>
    </div>
    <div class='mpl-opt-toggle'></div>
  </div>

  <div class='mpl-opt' id='opt-shuffle' onclick='toggleOpt("opt-shuffle","mpl-shuffle-media")'>
    <div class='mpl-opt-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='16 3 21 3 21 8'/><line x1='4' y1='20' x2='21' y2='3'/><polyline points='21 16 21 21 16 21'/><line x1='15' y1='15' x2='21' y2='21'/><line x1='4' y1='4' x2='9' y2='9'/></svg></div>
    <div class='mpl-opt-text'>
      <p class='mpl-opt-title'>🔀 Ordre aleatoire des medias</p>
      <p class='mpl-opt-sub'>Shuffle la liste avant de planifier (au lieu de l'ordre fourni)</p>
    </div>
    <div class='mpl-opt-toggle'></div>
  </div>

  <div class='mpl-opt active' id='opt-randmin' onclick='toggleOpt("opt-randmin","mpl-random-min")'>
    <div class='mpl-opt-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='1 4 1 10 7 10'/><polyline points='23 20 23 14 17 14'/><path d='M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15'/></svg></div>
    <div class='mpl-opt-text'>
      <p class='mpl-opt-title'>🎲 Randomiser les minutes</p>
      <p class='mpl-opt-sub'>Les minutes varient (3 a 25) chaque jour pour eviter les patterns detectables</p>
    </div>
    <div class='mpl-opt-toggle'></div>
  </div>

  <div class='mpl-section-label'>Contenu</div>

  <!-- Bibliotheque Medias -->
  <div class='mpl-row' id='mpl-media-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect width='18' height='18' x='3' y='3' rx='2' ry='2'/><circle cx='9' cy='9' r='2'/><path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>Bibliotheque Medias <span class='mpl-mini-badge' id='mpl-media-count'>0</span></div>
        <div class='mpl-row-sub'>Tes media_id MyPuls qui seront planifies</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:8px'>
        <small style='color:#888' id='mpl-media-status'>Aucun media. Clique pour fetch.</small>
        <button type='button' class='mpl-fetch-btn' onclick='fetchMyPulsMedia()'>↓ Recuperer depuis MyPuls</button>
      </div>
      <textarea name='media_ids' id='mpl-media-ids' rows='8' required
                placeholder='75784227&#10;75784226&#10;...'
                style='font-family:monospace;font-size:13px' oninput='updateMediaCount()'></textarea>
    </div>
  </div>

  <!-- Captions -->
  <div class='mpl-row' id='mpl-captions-block'>
    <div class='mpl-row-head' onclick='mplToggle(this.parentElement)'>
      <div class='mpl-row-icon'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><polyline points='14 2 14 8 20 8'/></svg></div>
      <div class='mpl-row-text'>
        <div class='mpl-row-title'>Captions <span class='mpl-mini-badge' id='mpl-cap-count'>{captions_count}</span></div>
        <div class='mpl-row-sub'>Textes des posts (tirees au hasard) — non utilise pour les stories</div>
      </div>
      <svg class='mpl-row-arrow' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' width='18' height='18'><polyline points='6 9 12 15 18 9'/></svg>
    </div>
    <div class='mpl-row-body'>
      <textarea name='captions' id='mpl-captions' rows='8' style='font-family:inherit;font-size:13px' oninput='updateCapCount()'>{captions_default}</textarea>
    </div>
  </div>

  <div style='text-align:center;margin-top:24px'>
    <button type='submit' class='mpl-push-btn'>⚡ Pousser dans MyPuls (LIVE)</button>
  </div>
</form>
"""

    return (style + f"""
<div class='mpl-shell'>
  <div class='mpl-card'>
    <div class='mpl-card-header'>
      <span style='color:#888;font-size:12px;letter-spacing:1px;text-transform:uppercase'>MyPuls Live ⚡</span>
      <a href='?tab=mypuls' style='color:#888;text-decoration:none;font-size:12px'>⚙ Cookies</a>
    </div>

    <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:8px'>
      <span style='color:#888;font-size:11px;letter-spacing:1.2px;text-transform:uppercase'>Createur <span style='color:#444;font-size:10px;margin-left:6px'>(drag pour reorganiser)</span></span>
      <span style='color:#666;font-size:11px'><span id='mpl-cr-count'>{len(creators_map)} createurs</span><span class='mpl-cr-saved-hint' id='mpl-cr-saved'></span></span>
    </div>
    <div class='mpl-cr-bar'>
      {creators_cards}
    </div>

    <div class='mpl-name' id='mpl-name'>
      <img id='mpl-name-avatar' src='/mypuls/avatar/{first_creator_id}' alt='' style='width:48px;height:48px;border-radius:50%;object-fit:cover;border:2.5px solid {first_color};margin-right:6px;box-shadow:0 0 0 4px {first_color_bg}' onerror="this.style.display='none'">
      <span id='mpl-name-text' style='color:{first_color}'>{first_creator_name or '—'}</span>
    </div>
    <div class='mpl-handle' id='mpl-handle'>id #{first_creator_id}</div>

    <div class='mpl-banner'>
      <div class='mpl-banner-dot'></div>
      <div>
        <p class='mpl-banner-title'>Push manuel (one-shot)</p>
        <p class='mpl-banner-sub'>Tu definis tes slots → ⚡ Pousser → MyPuls execute aux dates/heures prevues.</p>
      </div>
    </div>

    {campaigns_html}

    <div class='mpl-stats'>
      <div class='mpl-stat'><div class='mpl-stat-num' id='mpl-stat-media'>0</div><div class='mpl-stat-lbl'>MEDIAS</div></div>
      <div class='mpl-stat'><div class='mpl-stat-num' id='mpl-stat-cap'>{captions_count}</div><div class='mpl-stat-lbl'>CAPTIONS</div></div>
      <div class='mpl-stat'><div class='mpl-stat-num' id='mpl-stat-perday'>9</div><div class='mpl-stat-lbl mpl-stat-lbl-perday'>POSTS / JOUR</div></div>
    </div>

    {form}
  </div>
</div>

<script>
// ============= Slot management =============
const DEFAULT_POST_SLOTS = [
  {{time:'01:00', visibility:'public'}}, {{time:'02:00', visibility:'private'}},
  {{time:'04:00', visibility:'public'}}, {{time:'08:00', visibility:'private'}},
  {{time:'13:00', visibility:'public'}}, {{time:'15:00', visibility:'private'}},
  {{time:'18:00', visibility:'public'}}, {{time:'19:00', visibility:'private'}},
  {{time:'20:00', visibility:'public'}},
];
// Story slots : {{time, audience}} - audience values doivent matcher l API MyPuls
const STORY_AUDIENCES = [
  {{value:'everyone', label:'Tous MYM'}},
  {{value:'subscribers', label:'Abonnes'}},
  {{value:'former_subscribers', label:'Ex-abonnes'}},
  {{value:'interested', label:'Interesses'}},
];
const DEFAULT_STORY_SLOTS = [
  {{time:'08:00', audience:'everyone'}},
  {{time:'12:00', audience:'everyone'}},
  {{time:'16:00', audience:'subscribers'}},
  {{time:'20:00', audience:'everyone'}},
];

let postSlots = DEFAULT_POST_SLOTS.slice();
let storySlots = DEFAULT_STORY_SLOTS.slice();

function renderPostSlots(){{
  const cnt = parseInt(document.getElementById('mpl-posts-count').value)||0;
  // resize
  while(postSlots.length < cnt){{
    // Auto-add: alternate vis, time = next free hour
    const lastH = postSlots.length?parseInt(postSlots[postSlots.length-1].time.split(':')[0]):0;
    const nextH = Math.min(23,(lastH+2));
    const v = (postSlots.length%2===0)?'public':'private';
    postSlots.push({{time:String(nextH).padStart(2,'0')+':00', visibility:v}});
  }}
  while(postSlots.length > cnt) postSlots.pop();
  const c = document.getElementById('mpl-post-slots');
  c.innerHTML = postSlots.map((s,i)=>`
    <div class='mpl-slot' data-idx='${{i}}'>
      <div class='mpl-slot-badge'>#${{i+1}}</div>
      <input type='time' class='mpl-slot-time' value='${{s.time}}' onchange='postSlots[${{i}}].time=this.value;syncSlots()'>
      <button type='button' class='mpl-slot-vis ${{s.visibility}}' onclick='togglePostVis(${{i}})'>
        ${{s.visibility==='public'?'<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M2 12h20\"/><path d=\"M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z\"/></svg> Public':'<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/></svg> Prive'}}
      </button>
      <button type='button' class='mpl-slot-rm' onclick='removePostSlot(${{i}})' title='Retirer'>×</button>
    </div>
  `).join('');
  syncSlots();
}}
function togglePostVis(i){{
  postSlots[i].visibility = postSlots[i].visibility==='public'?'private':'public';
  renderPostSlots();
}}
function removePostSlot(i){{
  postSlots.splice(i,1);
  document.getElementById('mpl-posts-count').value = postSlots.length;
  renderPostSlots();
}}
function addPostSlot(){{
  postSlots.push({{time:'12:00', visibility:'public'}});
  document.getElementById('mpl-posts-count').value = postSlots.length;
  renderPostSlots();
}}

function renderStorySlots(){{
  const cnt = parseInt(document.getElementById('mpl-stories-count').value)||0;
  // Migration : si on a une ancienne string, la convertir en objet
  storySlots = storySlots.map(s=> typeof s === 'string' ? {{time:s, audience:'everyone'}} : s);
  while(storySlots.length < cnt){{
    const lastSlot = storySlots[storySlots.length-1];
    const lastH = lastSlot ? parseInt(lastSlot.time.split(':')[0]) : 0;
    const nextH = Math.min(23,(lastH+4));
    storySlots.push({{time:String(nextH).padStart(2,'0')+':00', audience:'everyone'}});
  }}
  while(storySlots.length > cnt) storySlots.pop();
  // Options HTML pour audience
  const audOpts = STORY_AUDIENCES.map(a=>'<option value=\"'+a.value+'\">'+a.label+'</option>').join('');
  const c = document.getElementById('mpl-story-slots');
  c.innerHTML = storySlots.map((s,i)=>`
    <div class='mpl-slot' data-idx='${{i}}'>
      <div class='mpl-slot-badge' style='background:rgba(59,130,246,.15);color:#3b82f6'>#${{i+1}}</div>
      <input type='time' class='mpl-slot-time' value='${{s.time}}' onchange='storySlots[${{i}}].time=this.value;syncSlots()'>
      <select class='mpl-slot-aud' onchange='storySlots[${{i}}].audience=this.value;syncSlots()' style='flex-shrink:0;background:#1a1a1a;border:1px solid #2a2a2a;color:#aaa;padding:6px 10px;border-radius:8px;font-size:13px;cursor:pointer'>
        ${{audOpts.replace('value=\"'+s.audience+'\"','value=\"'+s.audience+'\" selected')}}
      </select>
      <button type='button' class='mpl-slot-rm' onclick='removeStorySlot(${{i}})' title='Retirer'>×</button>
    </div>
  `).join('');
  syncSlots();
}}
function removeStorySlot(i){{
  storySlots.splice(i,1);
  document.getElementById('mpl-stories-count').value = storySlots.length;
  renderStorySlots();
}}
function addStorySlot(){{
  storySlots.push({{time:'12:00', audience:'everyone'}});
  document.getElementById('mpl-stories-count').value = storySlots.length;
  renderStorySlots();
}}

function syncSlots(){{
  document.getElementById('mpl-post-slots-json').value = JSON.stringify(postSlots);
  document.getElementById('mpl-story-slots-json').value = JSON.stringify(storySlots);
  // Stat /jour : reflete le type courant
  var t = document.getElementById('mpl-content-type').value;
  document.getElementById('mpl-stat-perday').textContent = (t==='story')?storySlots.length:postSlots.length;
  var pt = document.getElementById('mpl-posts-tag');
  if(pt) pt.textContent = postSlots.length + ' / jour';
  var st = document.getElementById('mpl-stories-tag');
  if(st) st.textContent = storySlots.length + ' / jour';
}}

function switchTab(tab){{
  // Mise a jour du bouton actif
  document.querySelectorAll('.mpl-pillnav button').forEach(b=>{{
    b.classList.toggle('active', b.dataset.tab===tab);
  }});
  // Set hidden content_type
  document.getElementById('mpl-content-type').value = tab;
  // Show/hide blocs selon le tab
  const showPosts = (tab==='post');
  const showStories = (tab==='story');
  const showDelete = (tab==='delete');
  // Posts card
  const pb = document.getElementById('mpl-posts-block');
  if(pb) pb.style.display = showPosts?'':'none';
  // Stories card
  const sb = document.getElementById('mpl-stories-block');
  if(sb) sb.style.display = showStories?'':'none';
  // Auto-delete posts settings (lie aux posts)
  const ad = document.getElementById('mpl-autodelete-block');
  if(ad) ad.style.display = showPosts?'':'none';
  // Captions (lie aux posts)
  const cap = document.getElementById('mpl-captions-block');
  if(cap) cap.style.display = showPosts?'':'none';
  // Delete panel
  const del = document.getElementById('mpl-delete-block');
  if(del) del.style.display = showDelete?'':'none';
  // Options + section labels : cachees en mode delete
  const opts = document.querySelectorAll('.mpl-opt');
  opts.forEach(o=>{{ o.style.display = showDelete?'none':''; }});
  const oLbl = document.getElementById('mpl-options-label');
  if(oLbl) oLbl.style.display = showDelete?'none':'';
  const pLbl = document.getElementById('mpl-planif-label');
  if(pLbl) pLbl.style.display = showDelete?'none':'';
  // Bibliotheque medias : cachee en delete
  const med = document.getElementById('mpl-media-block');
  if(med) med.style.display = showDelete?'none':'';
  // Stats : adapter le label /jour
  const lbl = document.querySelector('.mpl-stat-lbl-perday');
  if(lbl){{
    if(showStories) lbl.textContent = 'STORIES / JOUR';
    else if(showDelete) lbl.textContent = 'EVENTS PLANIFIES';
    else lbl.textContent = 'POSTS / JOUR';
  }}
  const v = document.getElementById('mpl-stat-perday');
  if(v){{
    if(showStories) v.textContent = storySlots.length;
    else if(showDelete) v.textContent = document.getElementById('mpl-cal-month-badge') ? document.getElementById('mpl-cal-month-badge').textContent.replace(' events','') : '0';
    else v.textContent = postSlots.length;
  }}
  // Bouton push : adapter le texte
  const btn = document.querySelector('.mpl-push-btn');
  if(btn){{
    if(showDelete){{ btn.style.display = 'none'; }}
    else {{
      btn.style.display = '';
      if(showStories) btn.innerHTML = '⚡ Pousser les stories';
      else btn.innerHTML = '⚡ Pousser les posts';
    }}
  }}
  // Cache aussi le bloc dates en mode delete (le calendrier a sa propre nav)
  const datesBlk = document.getElementById('mpl-dates-block');
  if(datesBlk) datesBlk.style.display = showDelete?'none':'';
  // Auto-charge le calendrier en mode delete
  if(showDelete) setTimeout(()=>loadCalendar(), 100);
}}
function updatePostAction(){{
  const a = document.getElementById('mpl-post-action');
  const w = document.getElementById('mpl-post-delay-wrap');
  if(a && w) w.style.display = (a.value==='delete')?'':'none';
}}

function toggleInfinite(){{
  const t = document.getElementById('mpl-infinite-toggle');
  if(!t) return;
  t.classList.toggle('active');
  const on = t.classList.contains('active');
  document.getElementById('mpl-infinite').value = on?'1':'0';
  // Cache la date de fin si infini
  const ew = document.getElementById('mpl-end-wrap');
  if(ew) ew.style.display = on?'none':'';
  // Change le label de "Date debut" en "Demarrer le"
  const lbl = document.getElementById('mpl-lbl-start');
  if(lbl) lbl.textContent = on?'Demarrer le':'Date debut';
  // Adapter le bouton push
  const btn = document.querySelector('.mpl-push-btn');
  if(btn){{
    const ct = document.getElementById('mpl-content-type').value;
    if(ct==='delete') return;
    if(on){{
      btn.innerHTML = '♾️ Lancer la campagne infinie';
    }} else {{
      btn.innerHTML = (ct==='story')?'⚡ Pousser les stories':'⚡ Pousser les posts';
    }}
  }}
}}

// === Auto-Delete : fetch events + select + delete ===
async function fetchEvents(){{
  const cid = document.getElementById('mpl-creator-id').value;
  if(!cid){{ alert('Pas de createur'); return; }}
  const ds = document.querySelector('input[name=date_start]').value;
  const de = document.querySelector('input[name=date_end]').value;
  const status = document.getElementById('mpl-events-status');
  status.textContent = 'Chargement...';
  status.style.color = '#3b82f6';
  try {{
    const r = await fetch('/mypulslive/list_events?creator='+cid+'&start='+ds+'&end='+de);
    const j = await r.json();
    if(!j.ok){{
      status.textContent = 'Erreur: ' + (j.error || '?');
      status.style.color = '#f99';
      return;
    }}
    const list = document.getElementById('mpl-events-list');
    if(!j.events || !j.events.length){{
      list.innerHTML = '<div style=\"color:#666;padding:20px;text-align:center;font-size:13px\">Aucun event planifie sur cette periode</div>';
      status.textContent = '0 event';
      status.style.color = '#888';
      document.getElementById('mpl-del-count').textContent = '0';
      return;
    }}
    list.innerHTML = j.events.map(e=>{{
      const ep = e.extendedProps || {{}};
      const typ = ep.type || 'feed';
      const d = (e.start || '').substring(0, 16).replace('T', ' ');
      const title = (e.title || '').substring(0, 70);
      const vis = ep.visibility ? ' • '+ep.visibility : '';
      return '<label class=\"mpl-event\" data-id=\"'+e.id+'\"><input type=\"checkbox\" class=\"mpl-event-cb\" onchange=\"updateDeleteSel()\"><span class=\"mpl-event-type '+typ+'\">'+typ.toUpperCase()+'</span><span class=\"mpl-event-date\">'+d+'</span><span class=\"mpl-event-title\">'+title+vis+'</span></label>';
    }}).join('');
    status.textContent = j.events.length + ' events trouves';
    status.style.color = '#22c55e';
    document.getElementById('mpl-del-count').textContent = j.events.length;
    updateDeleteSel();
  }} catch(e){{
    status.textContent = 'Erreur reseau: '+e;
    status.style.color = '#f99';
  }}
}}
function parseSelectedIds(){{
  const ids = [];
  document.querySelectorAll('.mpl-event').forEach(el=>{{
    const cb = el.querySelector('.mpl-event-cb');
    if(cb && cb.checked){{
      ids.push(el.dataset.id);
      el.classList.add('selected');
    }} else {{
      el.classList.remove('selected');
    }}
  }});
  return ids;
}}
function updateDeleteSel(){{
  const ids = parseSelectedIds();
  document.getElementById('mpl-delete-ids').value = ids.join(',');
  const v = document.getElementById('mpl-stat-perday');
  if(v && document.getElementById('mpl-content-type').value==='delete'){{
    v.textContent = ids.length;
  }}
}}
function toggleSelectAll(){{
  document.querySelectorAll('.mpl-event-cb').forEach(cb=>cb.checked=true);
  updateDeleteSel();
}}
function unselectAll(){{
  document.querySelectorAll('.mpl-event-cb').forEach(cb=>cb.checked=false);
  updateDeleteSel();
}}
// === CALENDRIER MENSUEL ===
let __calYear, __calMonth;
const FR_MONTHS = ['janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre'];

function calToday(){{
  const d = new Date();
  __calYear = d.getFullYear();
  __calMonth = d.getMonth();
  loadCalendar();
}}
function calNav(delta){{
  if(__calYear===undefined){{ calToday(); return; }}
  __calMonth += delta;
  if(__calMonth < 0){{ __calMonth = 11; __calYear--; }}
  if(__calMonth > 11){{ __calMonth = 0; __calYear++; }}
  loadCalendar();
}}
async function loadCalendar(){{
  if(__calYear===undefined){{
    const d = new Date();
    __calYear = d.getFullYear();
    __calMonth = d.getMonth();
  }}
  const cid = document.getElementById('mpl-creator-id').value;
  if(!cid){{ return; }}
  // Update header
  document.getElementById('mpl-cal-month-name').textContent = FR_MONTHS[__calMonth] + ' ' + __calYear;
  document.getElementById('mpl-cal-month-badge').textContent = '...';

  // Range : 1er du mois -> dernier du mois
  const d1 = new Date(__calYear, __calMonth, 1);
  const dLast = new Date(__calYear, __calMonth+1, 0);
  const pad = n=>String(n).padStart(2,'0');
  const startStr = __calYear+'-'+pad(__calMonth+1)+'-01';
  const endStr = __calYear+'-'+pad(__calMonth+1)+'-'+pad(dLast.getDate());

  try {{
    const r = await fetch('/mypulslive/list_events?creator='+cid+'&start='+startStr+'&end='+endStr);
    const j = await r.json();
    if(!j.ok){{
      document.getElementById('mpl-cal-grid').innerHTML = '<div style=\"grid-column:1/-1;padding:30px;text-align:center;color:#f99;font-size:13px\">Erreur: '+(j.error||'?')+'</div>';
      document.getElementById('mpl-cal-month-badge').textContent = '0';
      return;
    }}
    renderCalendar(j.events || []);
  }} catch(e){{
    document.getElementById('mpl-cal-grid').innerHTML = '<div style=\"grid-column:1/-1;padding:30px;text-align:center;color:#f99;font-size:13px\">Erreur reseau: '+e+'</div>';
  }}
}}
function renderCalendar(events){{
  // Index events par date YYYY-MM-DD avec split public/prive/story
  const byDate = {{}};
  events.forEach(e=>{{
    const d = (e.start || '').substring(0, 10);
    if(!byDate[d]) byDate[d] = {{pub:[], priv:[], story:[]}};
    const ep = e.extendedProps||{{}};
    const t = ep.type || 'feed';
    if(t === 'story') byDate[d].story.push(e);
    else if((ep.visibility||'public')==='private') byDate[d].priv.push(e);
    else byDate[d].pub.push(e);
  }});
  document.getElementById('mpl-cal-month-badge').textContent = events.length + ' events';

  // Build grid
  const d1 = new Date(__calYear, __calMonth, 1);
  const dLast = new Date(__calYear, __calMonth+1, 0);
  let firstWd = d1.getDay() - 1;
  if(firstWd < 0) firstWd = 6;
  const daysInMonth = dLast.getDate();
  const todayStr = new Date().toISOString().substring(0,10);

  let html = '';
  // Previous month padding
  const prevLast = new Date(__calYear, __calMonth, 0).getDate();
  for(let i = firstWd; i > 0; i--){{
    const d = prevLast - i + 1;
    html += '<div style=\"min-height:74px;background:transparent;border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:8px 10px;color:#444;font-size:13px\">'+d+'</div>';
  }}
  // Current month
  const pad = n=>String(n).padStart(2,'0');
  for(let d = 1; d <= daysInMonth; d++){{
    const iso = __calYear+'-'+pad(__calMonth+1)+'-'+pad(d);
    const data = byDate[iso] || {{pub:[], priv:[], story:[]}};
    const nPub = data.pub.length;
    const nPriv = data.priv.length;
    const nStory = data.story.length;
    const isToday = (iso === todayStr);
    const bg = isToday ? '#0f1a2e' : 'transparent';
    const weight = isToday ? 700 : 500;
    html += '<div onclick=\"calDayDetail(\\''+iso+'\\')\" style=\"min-height:74px;background:'+bg+';border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:8px 10px;cursor:pointer;display:flex;flex-direction:column;gap:4px;transition:background .12s\" onmouseover=\"this.style.background=\\'#15100d\\'\" onmouseout=\"this.style.background=\\''+bg+'\\'\">'
      + '<div style=\"font-size:13px;font-weight:'+weight+';color:#fff\">'+d+'</div>'
      + '<div style=\"display:flex;flex-direction:column;gap:2px;margin-top:auto\">';
    if(nPub > 0) html += '<div style=\"background:rgba(59,130,246,.18);color:#3b82f6;font-size:10px;padding:2px 5px;border-radius:4px;font-weight:600\">'+nPub+' pub</div>';
    if(nPriv > 0) html += '<div style=\"background:rgba(115,115,115,.20);color:#a3a3a3;font-size:10px;padding:2px 5px;border-radius:4px;font-weight:600\">'+nPriv+' priv</div>';
    if(nStory > 0) html += '<div style=\"background:rgba(168,85,247,.18);color:#a855f7;font-size:10px;padding:2px 5px;border-radius:4px;font-weight:600\">'+nStory+' story</div>';
    html += '</div></div>';
  }}
  // Next month padding
  const totalCells = firstWd + daysInMonth;
  const padding = (Math.ceil(totalCells / 7) * 7) - totalCells;
  for(let i = 1; i <= padding; i++){{
    html += '<div style=\"min-height:74px;background:transparent;border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:8px 10px;color:#444;font-size:13px\">'+i+'</div>';
  }}
  document.getElementById('mpl-cal-grid').innerHTML = html;
  window.__calEvents = byDate;
  document.getElementById('mpl-cal-day-detail').style.display = 'none';
}}
function calDayDetail(iso){{
  const byDate = window.__calEvents || {{}};
  const data = byDate[iso] || {{pub:[], priv:[], story:[]}};
  const det = document.getElementById('mpl-cal-day-detail');
  const all = [...data.pub, ...data.priv, ...data.story].sort((a,b)=>a.start.localeCompare(b.start));
  if(!all.length){{
    det.innerHTML = '<div style=\"color:#666;text-align:center;padding:14px;font-size:13px\">Aucun event sur le <b>'+iso+'</b></div>';
    det.style.display = '';
    return;
  }}
  const allIds = all.map(e=>e.id).join(',');
  let html = '<div style=\"display:flex;align-items:center;justify-content:space-between;margin-bottom:12px\"><strong style=\"color:#fff;font-size:14px\">'+iso+'</strong><div style=\"display:flex;align-items:center;gap:10px\"><span style=\"color:#888;font-size:12px\">'+all.length+' event(s)</span><button type=\"button\" onclick=\"deleteAllDay(\\''+iso+'\\',\\''+allIds+'\\')\" style=\"background:#ef4444;border:0;color:#fff;padding:6px 12px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer\">🗑 Tout supprimer ce jour</button></div></div>';
  // SVG icones par type
  const SVG = {{
    pub: '<svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M2 12h20\"/><path d=\"M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z\"/></svg>',
    priv: '<svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/></svg>',
    story: '<svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><polygon points=\"10 8 16 12 10 16 10 8\"/></svg>'
  }};
  html += all.map(e=>{{
    const ep = e.extendedProps||{{}};
    const t = ep.type || 'feed';
    let kind, label, color, bg, tint, icon;
    if(t === 'story'){{
      kind='story'; label='STORY'; color='#a855f7';
      bg='rgba(168,85,247,.10)'; tint='rgba(168,85,247,.85)'; icon=SVG.story;
    }} else if((ep.visibility||'public')==='private'){{
      kind='priv'; label='PRIVE'; color='#a3a3a3';
      bg='rgba(115,115,115,.10)'; tint='rgba(115,115,115,.85)'; icon=SVG.priv;
    }} else {{
      kind='pub'; label='PUBLIC'; color='#3b82f6';
      bg='rgba(59,130,246,.10)'; tint='rgba(59,130,246,.85)'; icon=SVG.pub;
    }}
    const time = (e.start||'').substring(11,16);
    const title = (e.title||'').substring(0,55);
    return '<div style=\"display:flex;align-items:center;gap:10px;padding:9px 12px;background:'+bg+';border-radius:8px;margin-bottom:5px;font-size:12.5px;border:1px solid '+bg.replace('.10','.20')+'\">'
      + '<span style=\"color:#ccc;font-weight:700;font-family:monospace;font-size:12px;flex-shrink:0;min-width:42px\">'+time+'</span>'
      + '<span style=\"font-size:10px;padding:3px 10px;background:'+tint+';color:#fff;border-radius:14px;font-weight:700;letter-spacing:.5px;display:inline-flex;align-items:center;gap:5px;flex-shrink:0\">'+icon+' '+label+'</span>'
      + '<span style=\"flex:1;color:#bbb;overflow:hidden;text-overflow:ellipsis;white-space:nowrap\">'+title+'</span>'
      + '<button type=\"button\" onclick=\"deleteOneEvent('+e.id+')\" title=\"Supprimer\" style=\"background:transparent;border:1px solid #5a2020;color:#ef4444;padding:3px 9px;border-radius:5px;font-size:11px;cursor:pointer;flex-shrink:0\">×</button>'
      + '</div>';
  }}).join('');
  det.innerHTML = html;
  det.style.display = '';
}}

async function deleteOneEvent(eventId){{
  if(!confirm('Supprimer cet event ?')) return;
  const fd = new FormData();
  fd.set('delete_ids', String(eventId));
  const r = await fetch('/mypulslive/delete_events', {{method:'POST', body:fd}});
  if(r.redirected) window.location.href = r.url; else window.location.reload();
}}

async function deleteAllDay(iso, ids){{
  const idArr = ids.split(',').filter(Boolean);
  if(!idArr.length) return;
  if(!confirm('Supprimer les '+idArr.length+' events du '+iso+' ?\\n\\nAction IRREVERSIBLE.')) return;
  const fd = new FormData();
  fd.set('delete_ids', ids);
  const r = await fetch('/mypulslive/delete_events', {{method:'POST', body:fd}});
  if(r.redirected) window.location.href = r.url; else window.location.reload();
}}

async function quickClean(){{
  const cid = document.getElementById('mpl-creator-id').value;
  if(!cid){{ alert('Pas de createur'); return; }}
  const from = document.getElementById('mpl-clean-from').value;
  if(!from){{ alert('Choisis une date'); return; }}
  const status = document.getElementById('mpl-clean-status');
  status.textContent = 'Comptage...';
  status.style.color = '#3b82f6';
  // Range : from -> +1 an
  const fromD = new Date(from);
  const toD = new Date(fromD); toD.setFullYear(toD.getFullYear()+1);
  const toStr = toD.toISOString().slice(0,10);
  try {{
    const r = await fetch('/mypulslive/list_events?creator='+cid+'&start='+from+'&end='+toStr);
    const j = await r.json();
    if(!j.ok){{
      status.textContent = 'Erreur: '+(j.error||'?');
      status.style.color = '#f99';
      return;
    }}
    const ids = (j.events||[]).map(e=>e.id);
    if(!ids.length){{
      status.textContent = 'Aucun event a supprimer';
      status.style.color = '#888';
      return;
    }}
    if(!confirm('Supprimer '+ids.length+' event(s) planifie(s) a partir du '+from+' ?\\n\\nCette action est IRREVERSIBLE.')){{
      status.textContent = 'Annule';
      status.style.color = '#888';
      return;
    }}
    status.textContent = 'Suppression en cours...';
    status.style.color = '#3b82f6';
    // POST direct au endpoint de bulk delete
    const fd = new FormData();
    fd.set('delete_ids', ids.join(','));
    const dr = await fetch('/mypulslive/delete_events', {{method:'POST', body:fd}});
    // Le endpoint redirige avec flash, on suit le redirect
    if(dr.redirected){{
      window.location.href = dr.url;
    }} else {{
      window.location.reload();
    }}
  }} catch(e){{
    status.textContent = 'Erreur reseau: '+e;
    status.style.color = '#f99';
  }}
}}

function toggleOpt(elId, hiddenId){{
  const el = document.getElementById(elId);
  el.classList.toggle('active');
  document.getElementById(hiddenId).value = el.classList.contains('active')?'1':'0';
}}

function mplToggle(el){{ el.classList.toggle('open'); }}

// === Drag & drop des cards createurs ===
let __crDragSrc = null;
function crDragStart(ev){{
  __crDragSrc = ev.currentTarget;
  __crDragSrc.classList.add('dragging');
  __crDragSrc.__dragging = true;
  ev.dataTransfer.effectAllowed = 'move';
  // Astuce safari/chrome : il faut setData
  try{{ ev.dataTransfer.setData('text/plain', __crDragSrc.dataset.id || ''); }}catch(e){{}}
}}
function crDragOver(ev){{
  if(!__crDragSrc) return;
  ev.preventDefault();
  const t = ev.currentTarget;
  if(t === __crDragSrc) return;
  // Supprimer drop-target des autres
  document.querySelectorAll('.mpl-cr-card.drop-target').forEach(c=>{{ if(c!==t) c.classList.remove('drop-target'); }});
  t.classList.add('drop-target');
}}
function crDragLeave(ev){{
  ev.currentTarget.classList.remove('drop-target');
}}
function crDrop(ev){{
  ev.preventDefault();
  const target = ev.currentTarget;
  target.classList.remove('drop-target');
  if(!__crDragSrc || target === __crDragSrc) return;
  // Determiner si on insere avant ou apres target
  const bar = target.parentElement;
  const cards = Array.from(bar.children).filter(c=>c.classList.contains('mpl-cr-card'));
  const srcIdx = cards.indexOf(__crDragSrc);
  const dstIdx = cards.indexOf(target);
  if(srcIdx < dstIdx) bar.insertBefore(__crDragSrc, target.nextSibling);
  else bar.insertBefore(__crDragSrc, target);
  // Sauve le nouvel ordre
  saveCreatorOrder();
}}
function crDragEnd(ev){{
  if(__crDragSrc){{
    __crDragSrc.classList.remove('dragging');
    setTimeout(()=>{{ if(__crDragSrc) __crDragSrc.__dragging = false; __crDragSrc = null; }}, 50);
  }}
  document.querySelectorAll('.mpl-cr-card.drop-target').forEach(c=>c.classList.remove('drop-target'));
}}
async function saveCreatorOrder(){{
  const ids = Array.from(document.querySelectorAll('.mpl-cr-card')).map(c=>c.dataset.id);
  const fd = new FormData();
  fd.set('order', ids.join(','));
  const r = await fetch('/mypulslive/reorder_creators', {{method:'POST', body:fd}});
  const hint = document.getElementById('mpl-cr-saved');
  if(hint){{
    hint.textContent = '✓ ordre sauvegarde';
    hint.classList.add('show');
    setTimeout(()=>hint.classList.remove('show'), 1500);
  }}
}}

function selectCreator(cid, name, color, hue){{
  document.querySelectorAll('.mpl-cr-card').forEach(c=>{{
    c.classList.toggle('active', String(c.dataset.id)===String(cid));
  }});
  document.getElementById('mpl-creator-id').value = cid;
  // Color glow par createur
  if(!color){{
    // Fallback : recalcule depuis le nom
    let h=0; for(let i=0;i<name.length;i++) h=name.charCodeAt(i)+((h<<5)-h);
    hue=Math.abs(h)%360;
    color='hsl('+hue+',70%,60%)';
  }}
  var colorBg = 'hsla('+hue+',70%,60%,0.18)';
  var nt = document.getElementById('mpl-name-text');
  if(nt){{ nt.textContent = name; nt.style.color = color; }}
  var av = document.getElementById('mpl-name-avatar');
  if(av){{
    av.src = '/mypuls/avatar/'+cid;
    av.style.display='';
    av.style.borderColor = color;
    av.style.boxShadow = '0 0 0 4px '+colorBg;
  }}
  document.getElementById('mpl-handle').textContent = 'id #' + cid;
  // Reset media + events
  var ta = document.getElementById('mpl-media-ids');
  if(ta){{ ta.value = ''; updateMediaCount(); }}
  var s = document.getElementById('mpl-media-status');
  if(s){{ s.textContent = 'Aucun media charge. Clique pour fetch.'; s.style.color = '#888'; }}
  var el = document.getElementById('mpl-events-list');
  if(el) el.innerHTML = '';
  var es = document.getElementById('mpl-events-status');
  if(es){{ es.textContent = 'Choisis une periode + clique "Charger events"'; es.style.color='#888'; }}
  // Reload calendrier si visible
  var cal = document.getElementById('mpl-calendar-block');
  if(cal && cal.classList.contains('open')) loadCalendar();
}}
function updateMediaCount(){{
  const ta = document.getElementById('mpl-media-ids');
  const n = ta.value.split('\\n').filter(x=>x.trim()).length;
  document.getElementById('mpl-stat-media').textContent = n;
  document.getElementById('mpl-media-count').textContent = n;
}}
function updateCapCount(){{
  const ta = document.getElementById('mpl-captions');
  const n = ta.value.split('\\n').filter(x=>x.trim()).length;
  document.getElementById('mpl-stat-cap').textContent = n;
  document.getElementById('mpl-cap-count').textContent = n;
}}
async function fetchMyPulsMedia(){{
  const cid = document.getElementById('mpl-creator-id').value;
  if(!cid){{ alert('Pas de createur'); return; }}
  const status = document.getElementById('mpl-media-status');
  status.textContent = 'Fetching media library...';
  status.style.color = '#3b82f6';
  try{{
    const r = await fetch('/mypulslive/fetch_media?creator='+cid);
    const j = await r.json();
    if(j.ok){{
      document.getElementById('mpl-media-ids').value = j.ids.join('\\n');
      status.textContent = '✓ '+j.ids.length+' medias recuperes';
      status.style.color = '#22c55e';
      updateMediaCount();
    }} else {{ status.textContent='Erreur: '+(j.error||'?'); status.style.color='#f99'; }}
  }} catch(e) {{ status.textContent='Erreur reseau: '+e; status.style.color='#f99'; }}
}}
function submitMyPulsForm(ev){{
  ev.preventDefault();
  syncSlots();
  const ct = document.getElementById('mpl-content-type').value;
  const ds = document.querySelector('input[name=date_start]').value;
  const de = document.querySelector('input[name=date_end]').value;
  if(ct==='delete'){{
    const ids = parseSelectedIds();
    if(!ids.length){{ alert('Aucun event selectionne.'); return false; }}
    if(confirm('Supprimer '+ids.length+' event(s) planifie(s) sur MyPuls ? Action IRREVERSIBLE.')){{
      // Set form action to delete endpoint
      ev.target.action = '/mypulslive/delete_events';
      ev.target.submit();
    }}
    return false;
  }}
  const label = (ct==='story')?'stories':'posts';
  if(confirm('Pousser les '+label+' dans MyPuls du '+ds+' au '+de+' ?\\n\\nCette action est IRREVERSIBLE.')){{
    ev.target.action = '/mypulslive/push';
    ev.target.submit();
  }}
  return false;
}}

// === Flatpickr DATE only (time inputs sont gérés par notre wheel custom) ===
function applyFlatpickr(){{
  if(typeof flatpickr === 'undefined') return;
  try{{ flatpickr.localize(flatpickr.l10ns.fr); }}catch(e){{}}
  document.querySelectorAll('#form-mypulslive input[type=date]:not([data-fp])').forEach(el=>{{
    el.dataset.fp = '1';
    flatpickr(el, {{
      dateFormat: 'Y-m-d',
      altInput: true,
      altFormat: 'j F Y',
      monthSelectorType: 'static',
      disableMobile: true,
    }});
  }});
  // Time inputs : wheel picker custom (interceptes au click)
  document.querySelectorAll('#form-mypulslive input[type=time]:not([data-tp])').forEach(el=>{{
    el.dataset.tp = '1';
    el.setAttribute('readonly', 'readonly');
    el.style.cursor = 'pointer';
    el.addEventListener('focus', e=>{{ e.target.blur(); openTimeWheel(e.target); }});
    el.addEventListener('click', e=>{{ openTimeWheel(e.target); }});
  }});
}}

// === Wheel time picker (style iOS) ===
let __twTarget = null;
let __twHour = 0;
let __twMinute = 0;

function openTimeWheel(input){{
  __twTarget = input;
  const val = (input.value || '00:00').split(':');
  __twHour = parseInt(val[0])||0;
  __twMinute = parseInt(val[1])||0;
  buildTimeWheelIfNeeded();
  // Headers
  const sub = document.getElementById('mpl-tw-sub');
  if(sub) sub.textContent = 'Heure';
  // Scroll vers les valeurs initiales
  const colH = document.getElementById('mpl-tw-hour');
  const colM = document.getElementById('mpl-tw-min');
  // Hauteur d'un item = 46px, top padding fait que item 0 est centré
  colH.scrollTop = __twHour * 46;
  colM.scrollTop = __twMinute * 46;
  // Mettre a jour les classes 'center'
  setTimeout(()=>{{ updateWheelCenter(colH); updateWheelCenter(colM); }}, 30);
  document.getElementById('mpl-tw-overlay').classList.add('show');
}}
function closeTimeWheel(save){{
  const ov = document.getElementById('mpl-tw-overlay');
  if(ov) ov.classList.remove('show');
  if(save && __twTarget){{
    const hh = String(__twHour).padStart(2,'0');
    const mm = String(__twMinute).padStart(2,'0');
    __twTarget.value = hh+':'+mm;
    // Trigger change pour que les slot listeners reagissent
    __twTarget.dispatchEvent(new Event('change', {{bubbles:true}}));
  }}
}}
function updateWheelCenter(col){{
  if(!col) return;
  const items = col.querySelectorAll('.mpl-wheel-item');
  const colRect = col.getBoundingClientRect();
  const colMid = colRect.top + colRect.height/2;
  let bestEl = null, bestDist = Infinity;
  items.forEach(it=>{{
    const r = it.getBoundingClientRect();
    const mid = r.top + r.height/2;
    const d = Math.abs(mid - colMid);
    if(d < bestDist){{ bestDist = d; bestEl = it; }}
  }});
  items.forEach(it=>it.classList.toggle('center', it===bestEl));
  if(bestEl){{
    const val = parseInt(bestEl.dataset.val);
    if(col.id === 'mpl-tw-hour') __twHour = val;
    else __twMinute = val;
  }}
}}
function buildTimeWheelIfNeeded(){{
  if(document.getElementById('mpl-tw-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'mpl-tw-overlay';
  overlay.className = 'mpl-wheel-overlay';
  overlay.addEventListener('click', e=>{{ if(e.target===overlay) closeTimeWheel(false); }});
  let hours = '';
  for(let i=0;i<24;i++){{
    hours += '<div class="mpl-wheel-item" data-val="'+i+'">'+String(i).padStart(2,'0')+'</div>';
  }}
  let mins = '';
  for(let i=0;i<60;i++){{
    mins += '<div class="mpl-wheel-item" data-val="'+i+'">'+String(i).padStart(2,'0')+'</div>';
  }}
  overlay.innerHTML = '<div class="mpl-wheel-modal">'
    + '<div class="mpl-wheel-head">'
    + '<div class="mpl-wheel-head-title">Programmer</div>'
    + '<div class="mpl-wheel-head-sub" id="mpl-tw-sub">Heure</div>'
    + '</div>'
    + '<div class="mpl-wheel-body">'
    + '<div class="mpl-wheel-col" id="mpl-tw-hour"><div style="height:97px"></div>'+hours+'<div style="height:97px"></div></div>'
    + '<div class="mpl-wheel-sep">:</div>'
    + '<div class="mpl-wheel-col" id="mpl-tw-min"><div style="height:97px"></div>'+mins+'<div style="height:97px"></div></div>'
    + '</div>'
    + '<div class="mpl-wheel-foot">'
    + '<button type="button" class="mpl-wheel-btn cancel" onclick="closeTimeWheel(false)">Annuler</button>'
    + '<button type="button" class="mpl-wheel-btn" onclick="closeTimeWheel(true)">Valider</button>'
    + '</div>'
    + '</div>';
  document.body.appendChild(overlay);
  // Scroll listeners pour mettre a jour la valeur centrale
  let scrollTimer1, scrollTimer2;
  const colH = document.getElementById('mpl-tw-hour');
  const colM = document.getElementById('mpl-tw-min');
  colH.addEventListener('scroll', ()=>{{ updateWheelCenter(colH); clearTimeout(scrollTimer1); scrollTimer1=setTimeout(()=>snapWheel(colH), 90); }});
  colM.addEventListener('scroll', ()=>{{ updateWheelCenter(colM); clearTimeout(scrollTimer2); scrollTimer2=setTimeout(()=>snapWheel(colM), 90); }});
  // Click sur un item -> scroll dessus
  [colH, colM].forEach(col=>{{
    col.addEventListener('click', e=>{{
      const it = e.target.closest('.mpl-wheel-item');
      if(it){{
        const itTop = it.offsetTop - col.clientHeight/2 + it.clientHeight/2;
        col.scrollTo({{top: itTop, behavior:'smooth'}});
      }}
    }});
  }});
}}
function snapWheel(col){{
  // Snap au centre l'item le plus proche
  const items = col.querySelectorAll('.mpl-wheel-item');
  const colRect = col.getBoundingClientRect();
  const colMid = colRect.top + colRect.height/2;
  let bestEl = null, bestDist = Infinity;
  items.forEach(it=>{{
    const r = it.getBoundingClientRect();
    const mid = r.top + r.height/2;
    const d = Math.abs(mid - colMid);
    if(d < bestDist){{ bestDist = d; bestEl = it; }}
  }});
  if(bestEl && bestDist > 1){{
    const itTop = bestEl.offsetTop - col.clientHeight/2 + bestEl.clientHeight/2;
    col.scrollTo({{top: itTop, behavior:'smooth'}});
  }}
}}
// Re-init quand on re-render les slots
const __oldRenderPost = renderPostSlots;
renderPostSlots = function(){{ __oldRenderPost.apply(this, arguments); setTimeout(applyFlatpickr, 0); }};
const __oldRenderStory = renderStorySlots;
renderStorySlots = function(){{ __oldRenderStory.apply(this, arguments); setTimeout(applyFlatpickr, 0); }};

// Init
document.getElementById('mpl-posts-count').value = postSlots.length;
document.getElementById('mpl-stories-count').value = storySlots.length;
renderPostSlots();
renderStorySlots();
switchTab('post');
updatePostAction();
updateMediaCount();
updateCapCount();
// Charge flatpickr apres l init des slots
setTimeout(applyFlatpickr, 100);
// Re-essai si CDN charge tard (max 3s)
setTimeout(applyFlatpickr, 500);
setTimeout(applyFlatpickr, 1500);
setTimeout(applyFlatpickr, 3000);
// Init calendrier au mois courant + auto-load (le block est open par defaut)
const __initD = new Date();
__calYear = __initD.getFullYear();
__calMonth = __initD.getMonth();
document.getElementById('mpl-cal-month-name').textContent = FR_MONTHS[__calMonth] + ' ' + __calYear;
// Auto-fetch les events pour le createur par defaut (delai pour eviter de bloquer l init)
setTimeout(()=>loadCalendar(), 300);
</script>
""")

def _render_bilan_html() -> str:
    try:
        from business import expense_stats, sfs_stats, list_expenses, revenue_stats, va_payment_stats, list_revenues, list_expenses
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    import datetime
    import json as _json
    from flask import request as flask_request

    # Lire la période depuis l'URL
    today = datetime.date.today()
    default_from = today - datetime.timedelta(days=6)
    default_to = today
    from_str = flask_request.args.get("bilan_from", default_from.isoformat())
    to_str = flask_request.args.get("bilan_to", default_to.isoformat())
    try:
        date_from = datetime.date.fromisoformat(from_str)
        date_to = datetime.date.fromisoformat(to_str)
        if date_from > date_to:
            date_from, date_to = date_to, date_from
    except Exception:
        date_from = default_from
        date_to = default_to

    all_revenues = list_revenues()
    all_expenses = list_expenses()
    # Filtrer par période
    revenues = [r for r in all_revenues if date_from.isoformat() <= r.get("date", "") <= date_to.isoformat()]
    expenses = [e for e in all_expenses if date_from.isoformat() <= e.get("date", "") <= date_to.isoformat()]
    pay = va_payment_stats()
    nb_ident = len(_list_identities())

    # Calculer les totaux pour la période
    total_rev_period = sum(r.get("amount", 0) for r in revenues)
    total_exp_period = sum(e.get("amount", 0) for e in expenses)

    # Revenus par source (sur la période)
    by_source = {}
    for r in revenues:
        src = r.get("source", "Autre")
        by_source[src] = by_source.get(src, 0) + r.get("amount", 0)

    # Revenus par identité (sur la période)
    by_ident_period = {}
    for r in revenues:
        ident = r.get("identity", "?")
        by_ident_period[ident] = by_ident_period.get(ident, 0) + r.get("amount", 0)

    # Dépenses par catégorie (sur la période)
    by_cat_period = {}
    for e in expenses:
        cat = e.get("category", "Autre")
        by_cat_period[cat] = by_cat_period.get(cat, 0) + e.get("amount", 0)

    # Données quotidiennes (toutes les dates entre from et to)
    nb_days = (date_to - date_from).days + 1
    daily_revenue = {}
    daily_expense = {}
    for i in range(nb_days):
        d = (date_from + datetime.timedelta(days=i)).isoformat()
        daily_revenue[d] = 0
        daily_expense[d] = 0
    for r in revenues:
        d = r.get("date", "")
        if d in daily_revenue:
            daily_revenue[d] += r.get("amount", 0)
    for e in expenses:
        d = e.get("date", "")
        if d in daily_expense:
            daily_expense[d] += e.get("amount", 0)

    profit_period = total_rev_period - total_exp_period
    profit_color = "#10b981" if profit_period >= 0 else "#ef4444"
    profit_sign = "+" if profit_period >= 0 else ""
    daily_data_json = _json.dumps([{"date": k, "amount": v} for k, v in daily_revenue.items()])
    by_ident_json = _json.dumps(by_ident_period)
    by_cat_json = _json.dumps(by_cat_period)
    start_label = date_from.strftime("%d %b")
    end_label = date_to.strftime("%d %b, %Y")

    # Globaux (hors période) pour affichage de référence
    rev = revenue_stats()
    exp = expense_stats()
    sub_amt = by_source.get("OnlyFans", 0)
    fansly_amt = by_source.get("Fansly", 0)
    snap_amt = by_source.get("Snap", 0)

    rows = []
    # Top : date range picker interactif + filtres
    rows.append(f"""
<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;margin-bottom:20px;position:relative'>
  <div onclick='toggleBilanDatePicker(event)' id='bilan-date-btn' style='display:flex;align-items:center;gap:10px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px 14px;cursor:pointer;user-select:none'>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#888" stroke-width="2"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
    <span style='font-size:13px;font-weight:500'>{start_label} → {end_label}</span>
    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
  </div>
  <div style='display:flex;gap:8px'>
    <div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px 14px;display:flex;align-items:center;gap:8px;font-size:13px'>Vue: par jour</div>
    <div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px 14px;display:flex;align-items:center;gap:8px;font-size:13px'>Filtres</div>
  </div>
  <!-- Date range picker popover -->
  <div id='bilan-date-picker' style='display:none;position:absolute;top:48px;left:0;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;padding:16px;z-index:100;box-shadow:0 12px 40px rgba(0,0,0,.5);min-width:340px' onclick='event.stopPropagation()'>
    <div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px'>
      <div>
        <div style='font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;font-weight:600;margin-bottom:6px'>Du</div>
        <input type='date' id='bilan-from-input' value='{date_from.isoformat()}' style='width:100%;padding:8px 10px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;font-size:13px'>
      </div>
      <div>
        <div style='font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;font-weight:600;margin-bottom:6px'>Au</div>
        <input type='date' id='bilan-to-input' value='{date_to.isoformat()}' style='width:100%;padding:8px 10px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;font-size:13px'>
      </div>
    </div>
    <div style='display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:14px'>
      <button onclick='applyBilanPreset("today")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>Aujourd'hui</button>
      <button onclick='applyBilanPreset("yesterday")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>Hier</button>
      <button onclick='applyBilanPreset("last7")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>7 derniers jours</button>
      <button onclick='applyBilanPreset("last30")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>30 derniers jours</button>
      <button onclick='applyBilanPreset("thisMonth")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>Ce mois</button>
      <button onclick='applyBilanPreset("lastMonth")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>Mois dernier</button>
      <button onclick='applyBilanPreset("last90")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>90 derniers jours</button>
      <button onclick='applyBilanPreset("ytd")' class='date-preset' style='padding:8px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600'>Cette année</button>
    </div>
    <div style='display:flex;justify-content:flex-end;gap:8px;padding-top:12px;border-top:1px solid #2a2a2a'>
      <button onclick='toggleBilanDatePicker()' style='padding:8px 16px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600'>Annuler</button>
      <button onclick='applyBilanDateRange()' style='padding:8px 18px;background:#3b82f6;border:0;color:#fff;border-radius:6px;cursor:pointer;font-size:13px;font-weight:700'>Appliquer</button>
    </div>
  </div>
</div>
<script>
function toggleBilanDatePicker(e){{
  if(e) e.stopPropagation();
  var p = document.getElementById('bilan-date-picker');
  if(p) p.style.display = (p.style.display === 'none' ? 'block' : 'none');
}}
function applyBilanPreset(preset){{
  var today = new Date();
  var from, to;
  function iso(d){{ return d.toISOString().split('T')[0]; }}
  switch(preset){{
    case 'today':
      from = to = today; break;
    case 'yesterday':
      from = to = new Date(today.getTime() - 86400000); break;
    case 'last7':
      to = today; from = new Date(today.getTime() - 6*86400000); break;
    case 'last30':
      to = today; from = new Date(today.getTime() - 29*86400000); break;
    case 'thisMonth':
      from = new Date(today.getFullYear(), today.getMonth(), 1); to = today; break;
    case 'lastMonth':
      from = new Date(today.getFullYear(), today.getMonth()-1, 1);
      to = new Date(today.getFullYear(), today.getMonth(), 0); break;
    case 'last90':
      to = today; from = new Date(today.getTime() - 89*86400000); break;
    case 'ytd':
      from = new Date(today.getFullYear(), 0, 1); to = today; break;
  }}
  document.getElementById('bilan-from-input').value = iso(from);
  document.getElementById('bilan-to-input').value = iso(to);
  applyBilanDateRange();
}}
function applyBilanDateRange(){{
  var from = document.getElementById('bilan-from-input').value;
  var to = document.getElementById('bilan-to-input').value;
  if(!from || !to) return;
  // Conserver l'onglet bilan dans l'URL
  window.location.search = '?tab=bilan&bilan_from=' + from + '&bilan_to=' + to;
}}
// Fermer le picker au clic extérieur
document.addEventListener('click', function(e){{
  var p = document.getElementById('bilan-date-picker');
  var btn = document.getElementById('bilan-date-btn');
  if(p && p.style.display === 'block' && !p.contains(e.target) && !btn.contains(e.target)){{
    p.style.display = 'none';
  }}
}});
</script>
<h3 style='margin:0 0 14px;font-size:20px;font-weight:700'>Récap des revenus <span style='font-size:13px;font-weight:400;color:#888'>({start_label} → {end_label})</span></h3>
<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:20px'>
  <div class='box' style='display:flex;flex-direction:column;justify-content:space-between'>
    <div style='display:flex;align-items:center;gap:12px;margin-bottom:14px'>
      <div style='width:48px;height:48px;background:#3b82f6;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700'>$</div>
      <div style='font-size:13px;color:#888;font-weight:500'>Revenus de la période</div>
    </div>
    <div style='font-size:32px;font-weight:700;color:#3b82f6;letter-spacing:-.02em'>{total_rev_period:.2f}€</div>
    <div style='font-size:11px;color:#888;margin-top:4px'>Total all-time : {rev['total_all_time']:.0f}€</div>
  </div>
  <div class='box'>
    <div style='display:flex;justify-content:space-between;align-items:flex-start'>
      <div>
        <div style='font-size:22px;font-weight:700;margin-bottom:4px'>{sub_amt:.2f}€</div>
        <div style='font-size:12px;color:#888'>OnlyFans</div>
      </div>
      <div style='width:40px;height:40px;background:rgba(59,130,246,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#3b82f6;font-weight:700'>OF</div>
    </div>
  </div>
  <div class='box'>
    <div style='display:flex;justify-content:space-between;align-items:flex-start'>
      <div>
        <div style='font-size:22px;font-weight:700;margin-bottom:4px'>{fansly_amt:.2f}€</div>
        <div style='font-size:12px;color:#888'>Fansly</div>
      </div>
      <div style='width:40px;height:40px;background:rgba(16,185,129,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#10b981;font-weight:700;font-size:11px'>FS</div>
    </div>
  </div>
  <div class='box'>
    <div style='display:flex;justify-content:space-between;align-items:flex-start'>
      <div>
        <div style='font-size:22px;font-weight:700;margin-bottom:4px'>{snap_amt:.2f}€</div>
        <div style='font-size:12px;color:#888'>Snap</div>
      </div>
      <div style='width:40px;height:40px;background:rgba(251,191,36,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fbbf24;font-weight:700'>SC</div>
    </div>
  </div>
  <div class='box'>
    <div style='display:flex;justify-content:space-between;align-items:flex-start'>
      <div>
        <div style='font-size:22px;font-weight:700;margin-bottom:4px;color:#fbbf24'>{pay['total_unpaid']:.2f}€</div>
        <div style='font-size:12px;color:#888'>À payer VAs</div>
      </div>
      <div style='width:40px;height:40px;background:rgba(251,191,36,.15);border-radius:10px;color:#fbbf24;display:flex;align-items:center;justify-content:center;font-weight:700'>€</div>
    </div>
  </div>
  <div class='box'>
    <div style='display:flex;justify-content:space-between;align-items:flex-start'>
      <div>
        <div style='font-size:22px;font-weight:700;margin-bottom:4px;color:#ef4444'>-{total_exp_period:.2f}€</div>
        <div style='font-size:12px;color:#888'>Dépenses de la période</div>
      </div>
      <div style='width:40px;height:40px;background:rgba(239,68,68,.15);border-radius:10px;color:#ef4444;display:flex;align-items:center;justify-content:center;font-weight:700'>−</div>
    </div>
  </div>
</div>

<div class='box' style='display:flex;justify-content:space-between;align-items:center;background:linear-gradient(135deg,rgba(59,130,246,.1),rgba(6,182,212,.05));border-color:#3b82f6;margin-bottom:24px'>
  <div>
    <div style='font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;font-weight:600;margin-bottom:6px'>Profit net sur la période</div>
    <div style='font-size:36px;font-weight:800;color:{profit_color};letter-spacing:-.02em'>{profit_sign}{profit_period:.2f}€</div>
  </div>
  <div style='display:flex;gap:30px;text-align:right'>
    <div>
      <div style='font-size:11px;color:#888;text-transform:uppercase'>Revenus</div>
      <div style='font-size:18px;font-weight:700;color:#10b981;margin-top:2px'>+{total_rev_period:.0f}€</div>
    </div>
    <div>
      <div style='font-size:11px;color:#888;text-transform:uppercase'>Dépenses</div>
      <div style='font-size:18px;font-weight:700;color:#ef4444;margin-top:2px'>-{total_exp_period:.0f}€</div>
    </div>
  </div>
</div>

<div class='box'>
  <h4 style='margin:0 0 14px;font-size:16px;font-weight:700'>Tendance des revenus <span style='font-size:12px;font-weight:400;color:#888'>({nb_days} jour{"s" if nb_days > 1 else ""})</span></h4>
  <div style='height:280px;position:relative'><canvas id='bilan-bar-chart'></canvas></div>
</div>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px' class='bilan-charts'>
  <div class='box'>
    <h4 style='margin:0 0 14px;font-size:16px;font-weight:700'>Revenus par identité</h4>
    <div style='height:240px;position:relative'><canvas id='bilan-identity-chart'></canvas></div>
  </div>
  <div class='box'>
    <h4 style='margin:0 0 14px;font-size:16px;font-weight:700'>Dépenses par catégorie</h4>
    <div style='height:240px;position:relative'><canvas id='bilan-expense-chart'></canvas></div>
  </div>
</div>

<script>
(function(){{
  if(typeof Chart === 'undefined'){{
    setTimeout(arguments.callee, 200);
    return;
  }}
  var isLight = document.body.classList.contains('light');
  var textColor = isLight ? '#374151' : '#aaa';
  var gridColor = isLight ? '#e5e7eb' : '#2a2a2a';
  Chart.defaults.color = textColor;
  Chart.defaults.borderColor = gridColor;
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  var daily = {daily_data_json};
  var byIdent = {by_ident_json};
  var byCat = {by_cat_json};
  var bc = document.getElementById('bilan-bar-chart');
  if(bc){{
    new Chart(bc, {{
      type: 'bar',
      data: {{
        labels: daily.map(function(d){{ var dt = new Date(d.date); return dt.toLocaleDateString('fr-FR', {{day:'numeric',month:'short'}}); }}),
        datasets: [{{ label: 'Revenus', data: daily.map(function(d){{ return d.amount; }}), backgroundColor: '#3b82f6', borderRadius: 6, maxBarThickness: 60 }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins:{{legend:{{display:false}}}}, scales: {{ y: {{ beginAtZero: true }}, x: {{ grid: {{display: false}} }} }} }}
    }});
  }}
  var ic = document.getElementById('bilan-identity-chart');
  if(ic){{
    var idents = Object.keys(byIdent);
    if(idents.length){{
      new Chart(ic, {{
        type: 'doughnut',
        data: {{ labels: idents, datasets: [{{ data: idents.map(function(k){{ return byIdent[k]; }}), backgroundColor: ['#3b82f6','#06b6d4','#10b981','#f59e0b','#a855f7','#ec4899'], borderWidth: 0 }}] }},
        options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{padding: 12, boxWidth: 12}} }} }} }}
      }});
    }} else {{
      ic.parentElement.innerHTML = '<p style="color:#888;text-align:center;padding:80px 0">Aucune donnée</p>';
    }}
  }}
  var ec = document.getElementById('bilan-expense-chart');
  if(ec){{
    var cats = Object.keys(byCat);
    if(cats.length){{
      new Chart(ec, {{
        type: 'bar',
        data: {{ labels: cats, datasets: [{{ label: 'Dépenses', data: cats.map(function(k){{ return byCat[k]; }}), backgroundColor: '#ef4444', borderRadius: 6, maxBarThickness: 28 }}] }},
        options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins:{{legend:{{display:false}}}}, scales: {{ x: {{beginAtZero: true}}, y: {{grid:{{display:false}}}} }} }}
      }});
    }} else {{
      ec.parentElement.innerHTML = '<p style="color:#888;text-align:center;padding:80px 0">Aucune dépense</p>';
    }}
  }}
}})();
</script>
""")
    return "".join(rows)


def _render_bilan_html_OLD() -> str:
    """Ancienne version (gardée temporairement, à supprimer)."""
    rows = []
    # Stats GROSSES en haut : profit net
    rows.append(
        "<div class='box' style='background:linear-gradient(135deg,#1a1a2e,#16213e);text-align:center;border:1px solid #3b82f6;margin-bottom:16px'>"
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
                f"<div style='width:{pct:.1f}%;background:linear-gradient(90deg,#f87171,#3b82f6);height:100%'></div>"
                f"</div></div>"
            )
    rows.append("</div>")
    return "".join(rows)


def _load_account_settings() -> dict:
    """Charge les settings du compte propriétaire."""
    f = DATA_DIR / "account_settings.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_account_settings(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / "account_settings.json"
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _render_profile_pic_html() -> str:
    """Render the profile pic preview (with fallback initial)."""
    settings = _load_account_settings()
    name = settings.get("display_name", "Admin")
    pic_path = DATA_DIR / "profile_pic.png"
    pic_jpg = DATA_DIR / "profile_pic.jpg"
    if pic_path.exists():
        return f"<img src='/account/profile_pic?v={int(time.time())}' style='width:80px;height:80px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a'>"
    if pic_jpg.exists():
        return f"<img src='/account/profile_pic?v={int(time.time())}' style='width:80px;height:80px;border-radius:50%;object-fit:cover;border:2px solid #2a2a2a'>"
    init = (name[0] if name else "?").upper()
    return (
        f"<div style='width:80px;height:80px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#06b6d4);"
        f"display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:28px'>{init}</div>"
    )


def _load_active_sessions() -> list:
    """Charge la liste des sessions actives."""
    f = DATA_DIR / "active_sessions.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _render_security_sessions_html() -> str:
    """Liste des sessions actives."""
    sessions = _load_active_sessions()
    try:
        from flask import session as flask_session
        current_sid = flask_session.get("session_id")
        for s in sessions:
            if s.get("id") == current_sid:
                s["current"] = True
    except Exception:
        pass
    if not sessions:
        return (
            "<p style='color:#888'>Aucune session active trackée pour l'instant.</p>"
            "<small>Les sessions seront enregistrées au prochain login.</small>"
        )
    rows = ["<div style='display:flex;flex-direction:column;gap:10px;margin-top:14px'>"]
    import datetime
    for s in sessions[:20]:
        ts = s.get("last_seen", 0)
        try:
            last_seen = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        except Exception:
            last_seen = "?"
        is_current = s.get("current", False)
        badge = "<span style='background:#10b981;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>ACTUELLE</span>" if is_current else ""
        rows.append(
            f"<div style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;padding:14px;display:flex;justify-content:space-between;align-items:center'>"
            f"<div>"
            f"<div style='font-weight:600;font-size:14px;margin-bottom:4px'>{s.get('user_agent_short', 'Unknown browser')} {badge}</div>"
            f"<div style='font-size:12px;color:#888'>IP : {s.get('ip', '?')} · Dernière activité : {last_seen}</div>"
            f"</div>"
            f"<form method='POST' action='/security/revoke_session' style='margin:0'>"
            f"<input type='hidden' name='session_id' value='{s.get('id', '')}'>"
            f"<button type='submit' class='danger-btn' data-confirm='Déconnecter cette session ?'>Déconnecter</button>"
            f"</form>"
            f"</div>"
        )
    rows.append("</div>")
    return "".join(rows)


def _load_role_users() -> list:
    """Liste des utilisateurs additionnels avec rôles."""
    f = DATA_DIR / "role_users.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_role_users(users: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / "role_users.json"
    f.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_role_definitions() -> dict:
    """Charge les définitions des rôles personnalisés (nom, description, permissions)."""
    f = DATA_DIR / "role_definitions.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_role_definitions(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "role_definitions.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# Structure des menus avec permissions disponibles
ROLE_MENU_STRUCTURE = [
    {"section": "Contenu", "items": [
        {"key": "upload", "name": "Upload (Reel/Post/Story/StoryCTA/PP)", "perms": ["view", "create"]},
        {"key": "cloud", "name": "Cloud (vue & gestion stockage)", "perms": ["view", "delete"]},
    ]},
    {"section": "Management", "items": [
        {"key": "vas_list", "name": "Liste VAs", "perms": ["view", "edit"]},
        {"key": "vas_stats", "name": "Stats par identité", "perms": ["view"]},
    ]},
    {"section": "Outils", "items": [
        {"key": "trends_ig", "name": "Trends Instagram", "perms": ["view", "scrape"]},
        {"key": "trends_tt", "name": "Trends TikTok", "perms": ["view"]},
        {"key": "business_sfs", "name": "Business — SFS Planning", "perms": ["view", "create", "edit"]},
        {"key": "business_revenus", "name": "Business — Revenus", "perms": ["view", "create", "edit"]},
        {"key": "business_depenses", "name": "Business — Dépenses", "perms": ["view", "create"]},
        {"key": "business_paievas", "name": "Business — Paie VAs", "perms": ["view", "create"]},
        {"key": "business_bilan", "name": "Business — Bilan", "perms": ["view"]},
    ]},
    {"section": "Settings", "items": [
        {"key": "settings_account", "name": "Mon compte", "perms": ["view", "edit"]},
        {"key": "settings_security", "name": "Sécurité (sessions)", "perms": ["view", "revoke"]},
        {"key": "settings_roles", "name": "Rôles & permissions", "perms": ["view", "edit"]},
    ]},
]


def _render_role_settings_html() -> str:
    """Tableau des rôles et permissions + utilisateurs."""
    users = _load_role_users()
    role_defs = _load_role_definitions()
    # Rôles par défaut
    default_roles = [
        ("owner", "Owner", "Toutes permissions", "#3b82f6"),
        ("admin", "Admin", "Accès complet (toutes pages, gestion VAs)", "#3b82f6"),
        ("creator", "Creator", "Upload + Cloud + visualisation revenus de son identité", "#10b981"),
        ("chatter", "Chatter", "Voir revenus + SFS + planning, pas d'upload", "#fbbf24"),
        ("va", "VA", "Lecture seule + accès à son propre contenu", "#a855f7"),
    ]
    # Construire la liste finale en mergeant avec les overrides custom
    roles_info = []
    for key, name, desc, color in default_roles:
        custom = role_defs.get(key, {})
        roles_info.append({
            "key": key,
            "name": custom.get("name", name),
            "desc": custom.get("description", desc),
            "color": color,
            "enabled": custom.get("enabled", True),
        })

    users_by_role = {}
    for u in users:
        r = u.get("role", "?")
        users_by_role.setdefault(r, []).append(u.get("username", "?"))

    rows = ["<table style='width:100%;border-collapse:collapse;margin-top:14px'>"]
    rows.append(
        "<tr style='background:#1a1a1a'>"
        "<th style='padding:10px 8px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Rôle</th>"
        "<th style='padding:10px 8px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Description</th>"
        "<th style='padding:10px 8px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Utilisateurs</th>"
        "<th style='padding:10px 8px;text-align:center;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Statut</th>"
        "<th style='padding:10px 8px;text-align:right;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px'>Actions</th>"
        "</tr>"
    )
    for r in roles_info:
        key = r["key"]
        members_list = users_by_role.get(key, [])
        if key == "owner" and not members_list:
            members_list = ["Toi"]
        members_str = ", ".join(members_list) if members_list else "<span style='color:#666'>—</span>"
        toggle_color = "#3b82f6" if r["enabled"] else "#444"
        toggle_pos = "right:2px" if r["enabled"] else "left:2px"
        # Échapper les guillemets pour les onclick JS
        r_name_safe = r["name"].replace('"', '\\"')
        r_desc_safe = r["desc"].replace('"', '\\"')
        r_color = r["color"]
        # Bouton trash seulement pour les rôles custom (pas Owner)
        trash_btn = ""
        if key != "owner":
            trash_btn = (
                f"<button onclick='deleteRole(\"{key}\",\"{r_name_safe}\")' "
                f"title='Supprimer le rôle' "
                f"style='background:transparent;border:0;color:#aaa;cursor:pointer;padding:4px 8px;margin-left:10px;font-size:14px' "
                f"onmouseover='this.style.color=\"#ef4444\"' onmouseout='this.style.color=\"#aaa\"'>"
                f"<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6'/><path d='M10 11v6M14 11v6'/><path d='M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2'/></svg>"
                f"</button>"
            )
        rows.append(
            f"<tr style='border-bottom:1px solid #2a2a2a'>"
            f"<td style='padding:12px 8px'><b style='color:{r_color}'>{r['name']}</b></td>"
            f"<td style='padding:12px 8px;font-size:13px;color:#aaa'>{r['desc']}</td>"
            f"<td style='padding:12px 8px;font-size:13px'>{members_str}</td>"
            f"<td style='padding:12px 8px;text-align:center'>"
            f"<div style='display:inline-block;width:36px;height:20px;background:{toggle_color};border-radius:10px;position:relative'>"
            f"<div style='position:absolute;{toggle_pos};top:2px;width:16px;height:16px;background:#fff;border-radius:50%'></div>"
            f"</div></td>"
            f"<td style='padding:12px 8px;text-align:right;white-space:nowrap'>"
            f"<a onclick='openPermissions(\"{key}\",\"{r_name_safe}\")' "
            f"style='color:#aaa;cursor:pointer;font-size:13px;font-weight:500;margin-right:18px;text-decoration:none' "
            f"onmouseover='this.style.color=\"#3b82f6\"' onmouseout='this.style.color=\"#aaa\"'>Set permissions</a>"
            f"<a onclick='openEditRole(\"{key}\",\"{r_name_safe}\",\"{r_desc_safe}\")' "
            f"style='color:#aaa;cursor:pointer;font-size:13px;font-weight:500;text-decoration:none' "
            f"onmouseover='this.style.color=\"#3b82f6\"' onmouseout='this.style.color=\"#aaa\"'>Edit</a>"
            f"{trash_btn}"
            f"</td></tr>"
        )
    rows.append("</table>")

    # Modal Edit role
    rows.append("""
<div id='edit-role-overlay' class='confirm-overlay' onclick='closeEditRole()'>
  <div class='confirm-box' style='max-width:480px' onclick='event.stopPropagation()'>
    <h3 style='margin-top:0'>Edit role</h3>
    <form method='POST' action='/settings/role/edit_def'>
      <input type='hidden' name='role_key' id='edit-role-key'>
      <label>Nom du rôle</label>
      <input type='text' name='name' id='edit-role-name' maxlength='50' required>
      <div style='font-size:11px;color:#666;text-align:right;margin-top:-8px'><span id='edit-role-name-count'>0</span> / 50</div>
      <label style='margin-top:12px'>Description</label>
      <textarea name='description' id='edit-role-desc' maxlength='300' rows='3' required></textarea>
      <div style='font-size:11px;color:#666;text-align:right;margin-top:-8px'><span id='edit-role-desc-count'>0</span> / 300</div>
      <div style='display:flex;gap:8px;justify-content:flex-end;margin-top:14px'>
        <button type='button' onclick='closeEditRole()' style='padding:10px 22px;background:#2a2a2a;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:0'>Cancel</button>
        <button type='submit' style='padding:10px 22px;background:#3b82f6;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:0'>Save</button>
      </div>
    </form>
  </div>
</div>

<div id='perm-overlay' class='confirm-overlay' onclick='closePermissions()'>
  <div class='confirm-box' style='max-width:900px;width:95%;max-height:85vh;overflow-y:auto' onclick='event.stopPropagation()'>
    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;position:sticky;top:0;background:#1a1a1a;padding-bottom:10px'>
      <h3 style='margin:0' id='perm-title'>‹ Set permissions for [role]</h3>
      <button onclick='savePermissions()' style='padding:8px 22px;background:#3b82f6;color:#fff;border:0;border-radius:8px;font-weight:700;cursor:pointer;margin:0'>Save</button>
    </div>
    <div id='perm-content'></div>
  </div>
</div>

<script>
window.__roleMenuStructure = """ + json.dumps(ROLE_MENU_STRUCTURE, ensure_ascii=False) + """;
window.__currentEditRoleKey = null;
function openEditRole(key, name, desc){
  document.getElementById('edit-role-key').value = key;
  document.getElementById('edit-role-name').value = name;
  document.getElementById('edit-role-desc').value = desc;
  document.getElementById('edit-role-name-count').textContent = name.length;
  document.getElementById('edit-role-desc-count').textContent = desc.length;
  document.getElementById('edit-role-overlay').classList.add('show');
}
function closeEditRole(){
  document.getElementById('edit-role-overlay').classList.remove('show');
}
document.addEventListener('input', function(e){
  if(e.target.id === 'edit-role-name') document.getElementById('edit-role-name-count').textContent = e.target.value.length;
  if(e.target.id === 'edit-role-desc') document.getElementById('edit-role-desc-count').textContent = e.target.value.length;
});
function openPermissions(key, name){
  window.__currentEditRoleKey = key;
  document.getElementById('perm-title').innerHTML = '‹ Set permissions for <b>' + name + '</b>';
  // Charger les permissions existantes via fetch
  fetch('/settings/role/permissions?key=' + encodeURIComponent(key))
    .then(function(r){ return r.json(); })
    .then(function(data){
      var perms = data.permissions || {};
      var content = document.getElementById('perm-content');
      var html = '';
      window.__roleMenuStructure.forEach(function(section){
        html += '<h4 style="margin:18px 0 8px;font-size:14px;font-weight:700">' + section.section + '</h4>';
        html += '<table style="width:100%;border-collapse:collapse;background:#0f0f0f;border-radius:8px;overflow:hidden;margin-bottom:14px">';
        html += '<tr style="background:#1a1a1a"><th style="padding:8px 10px;text-align:left;font-size:11px;color:#888;text-transform:uppercase">Menus</th><th style="padding:8px 10px;text-align:left;font-size:11px;color:#888;text-transform:uppercase">Permissions</th><th style="padding:8px 10px;text-align:left;font-size:11px;color:#888;text-transform:uppercase">Data scope</th></tr>';
        section.items.forEach(function(item){
          var menuPerms = perms[item.key] || {};
          var enabled = menuPerms.enabled !== false;
          var scope = menuPerms.scope || 'self';
          html += '<tr style="border-top:1px solid #1a1a1a">';
          html += '<td style="padding:10px"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" data-menu="' + item.key + '" data-field="enabled" ' + (enabled ? 'checked' : '') + ' style="accent-color:#3b82f6;width:18px;height:18px"> ' + item.name + '</label></td>';
          // Function perms
          var fnHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px">';
          (item.perms || []).forEach(function(p){
            var checked = (menuPerms.perms || []).indexOf(p) !== -1 || enabled;
            fnHtml += '<label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer"><input type="checkbox" data-menu="' + item.key + '" data-field="perm" data-perm="' + p + '" ' + (checked ? 'checked' : '') + ' style="accent-color:#3b82f6"> ' + p + '</label>';
          });
          fnHtml += '</div>';
          html += '<td style="padding:10px">' + fnHtml + '</td>';
          // Data scope
          var scopeHtml = '<div style="display:flex;gap:10px">'
            + '<label style="display:flex;align-items:center;gap:4px;font-size:12px"><input type="radio" name="scope_' + item.key + '" data-menu="' + item.key + '" data-field="scope" value="all" ' + (scope === 'all' ? 'checked' : '') + '> All data</label>'
            + '<label style="display:flex;align-items:center;gap:4px;font-size:12px"><input type="radio" name="scope_' + item.key + '" data-menu="' + item.key + '" data-field="scope" value="sub" ' + (scope === 'sub' ? 'checked' : '') + '> Self+subordinates</label>'
            + '<label style="display:flex;align-items:center;gap:4px;font-size:12px"><input type="radio" name="scope_' + item.key + '" data-menu="' + item.key + '" data-field="scope" value="self" ' + (scope === 'self' ? 'checked' : '') + '> Self only</label>'
            + '</div>';
          html += '<td style="padding:10px">' + scopeHtml + '</td>';
          html += '</tr>';
        });
        html += '</table>';
      });
      content.innerHTML = html;
      document.getElementById('perm-overlay').classList.add('show');
    });
}
function closePermissions(){
  document.getElementById('perm-overlay').classList.remove('show');
}
function deleteRole(key, name){
  showConfirm('Supprimer le rôle ?', 'Supprimer le rôle "' + name + '" ? Les utilisateurs ayant ce rôle ne perdent pas leur compte mais perdent leurs permissions.', function(){
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/settings/role/delete';
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'role_key';
    input.value = key;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
  });
}
function savePermissions(){
  // Construire l'objet permissions à partir des checkboxes
  var perms = {};
  document.querySelectorAll('#perm-content [data-menu]').forEach(function(input){
    var menu = input.dataset.menu;
    var field = input.dataset.field;
    if(!perms[menu]) perms[menu] = {enabled: true, perms: [], scope: 'self'};
    if(field === 'enabled') perms[menu].enabled = input.checked;
    else if(field === 'perm' && input.checked) perms[menu].perms.push(input.dataset.perm);
    else if(field === 'scope' && input.checked) perms[menu].scope = input.value;
  });
  var form = new FormData();
  form.append('role_key', window.__currentEditRoleKey);
  form.append('permissions', JSON.stringify(perms));
  fetch('/settings/role/permissions', {method: 'POST', body: form})
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(data.success){
        showToast('✅ Permissions sauvées', 'success');
        closePermissions();
      } else {
        showToast('❌ ' + (data.error || 'Erreur'), 'error');
      }
    });
}
</script>
""")
    # Tableau des utilisateurs ajoutés (avec suppression)
    if users:
        rows.append("<h4 style='margin:20px 0 10px'>Utilisateurs ajoutés</h4>")
        rows.append("<table style='width:100%;border-collapse:collapse'>")
        rows.append("<tr style='background:#1a1a1a'><th style='padding:8px;text-align:left'>Username</th><th style='padding:8px;text-align:left'>Rôle</th><th style='padding:8px;text-align:left'>Créé</th><th style='padding:8px;text-align:right'></th></tr>")
        import datetime
        for u in users:
            ts = u.get("created_at", 0)
            try:
                created = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y")
            except Exception:
                created = "?"
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:8px'><b>{u.get('username','?')}</b></td>"
                f"<td style='padding:8px;color:#aaa'>{u.get('role','?')}</td>"
                f"<td style='padding:8px;color:#888;font-size:12px'>{created}</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/settings/role/remove' style='display:inline;margin:0'>"
                f"<input type='hidden' name='username' value='{u.get('username','')}'>"
                f"<button type='submit' class='danger-btn' data-confirm=\"Supprimer {u.get('username','')} ?\">×</button>"
                f"</form></td></tr>"
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


def _render_upload(msg=None, error=None):
    try:
        return _render_upload_inner(msg=msg, error=error)
    except Exception as e:
        import traceback as _tb
        tb_text = _tb.format_exc()
        # Log côté serveur pour qu'on retrouve la trace
        try:
            import logging
            logging.getLogger("vabot").error(f"_render_upload CRASH: {e}\n{tb_text}")
        except Exception:
            pass
        # Page d'erreur stylée plutôt qu'un 500 brut Flask
        err_safe = (str(e) or type(e).__name__).replace("<", "&lt;").replace(">", "&gt;")
        tb_safe = tb_text.replace("<", "&lt;").replace(">", "&gt;")
        return f"""<!DOCTYPE html>
<html><head><title>VA Bot — Erreur</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap">
<style>
*{{box-sizing:border-box;margin:0;padding:0;font-family:'Inter',sans-serif}}
body{{background:#0a0a0a;color:#eee;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:40px}}
.card{{max-width:760px;width:100%;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px;padding:32px;box-shadow:0 12px 40px rgba(0,0,0,.4)}}
h1{{font-size:22px;font-weight:700;color:#ef4444;margin-bottom:6px;letter-spacing:-.02em}}
.sub{{color:#888;font-size:14px;margin-bottom:24px}}
pre{{background:#0a0a0a;border:1px solid #2a2a2a;border-radius:10px;padding:16px;font-size:12px;font-family:'JetBrains Mono',monospace;color:#aaa;max-height:300px;overflow:auto;white-space:pre-wrap;word-break:break-word}}
.actions{{display:flex;gap:10px;margin-top:20px}}
a,button{{padding:11px 18px;border-radius:8px;font-weight:600;cursor:pointer;text-decoration:none;font-size:13px;border:0;font-family:inherit}}
.primary{{background:#3b82f6;color:#fff}}
.secondary{{background:transparent;border:1px solid #2a2a2a;color:#aaa}}
</style></head><body>
<div class="card">
<h1>⚠ Erreur de rendu</h1>
<div class="sub">{err_safe}</div>
<pre>{tb_safe}</pre>
<div class="actions">
<a href="/" class="primary">Recharger</a>
<a href="/logout" class="secondary">Se déconnecter</a>
</div>
</div></body></html>"""


def _render_upload_inner(msg=None, error=None):
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
        .replace("{home_dashboard_html}", _render_home_dashboard_html())
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
        .replace("{cloud_storyctas_html}", _render_cloud_content_html("storyctas", IMAGE_EXTS))
        .replace("{cloud_pps_html}", _render_cloud_pps_html())
        .replace("{sfs_html}", _render_sfs_html())
        .replace("{revenus_html}", _render_revenus_html())
        .replace("{depenses_html}", _render_depenses_html())
        .replace("{paievas_html}", _render_paievas_html())
        .replace("{biolinks_html}", _render_biolinks_html())
        .replace("{gms_html}", _render_gms_html())
        .replace("{schedule_html}", _render_schedule_html())
        .replace("{vtg_html}", _render_vtg_html())
        .replace("{veille_feed_html}", _render_veille_feed_html())
        .replace("{mypulslive_html}", _render_mypulslive_html())
        .replace("{chatplanning_html}", _render_chatplanning_html())
        .replace("{bilan_html}", _render_bilan_html())
        .replace("{profile_pic_html}", _render_profile_pic_html())
        .replace("{account_display_name}", _load_account_settings().get("display_name", ""))
        .replace("{account_email}", _load_account_settings().get("email", ""))
        .replace("{security_sessions_html}", _render_security_sessions_html())
        .replace("{role_settings_html}", _render_role_settings_html())
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

    def _redirect_back(tab=None):
        """Retourne l'URL où rediriger : tab explicite > Referer > /."""
        if tab:
            return f"/?tab={tab}"
        # Use Referer pour rester sur l'onglet actuel
        ref = request.headers.get("Referer", "")
        if ref:
            # Garder uniquement le path+query relatifs (sécurité : pas de redirection externe)
            try:
                from urllib.parse import urlparse
                parsed = urlparse(ref)
                # Vérifier que c'est bien notre host (ou un path relatif)
                if parsed.netloc and request.host and parsed.netloc != request.host:
                    return "/"
                relative = parsed.path or "/"
                if parsed.query:
                    relative += "?" + parsed.query
                return relative
            except Exception:
                return "/"
        return "/"

    def _success(msg, tab=None):
        """Pattern POST-Redirect-GET : flash le message + redirige sur GET."""
        session["flash_msg"] = msg
        session["flash_error"] = False
        return redirect(_redirect_back(tab))

    def _error(msg, tab=None):
        session["flash_msg"] = msg
        session["flash_error"] = True
        return redirect(_redirect_back(tab))

    def _track_session():
        """Met à jour la session courante dans active_sessions.json."""
        try:
            sid = session.get("session_id")
            if not sid:
                import uuid
                sid = uuid.uuid4().hex[:16]
                session["session_id"] = sid
            ua = request.headers.get("User-Agent", "")
            # User-agent simplifié
            ua_short = "Unknown"
            for tag, label in [
                ("Chrome", "Chrome"), ("Firefox", "Firefox"), ("Safari", "Safari"),
                ("Edge", "Edge"), ("Opera", "Opera"),
            ]:
                if tag in ua:
                    ua_short = label
                    break
            os_name = "Unknown"
            for tag, label in [
                ("Windows", "Windows"), ("Mac", "macOS"), ("Linux", "Linux"),
                ("Android", "Android"), ("iPhone", "iOS"),
            ]:
                if tag in ua:
                    os_name = label
                    break
            ua_label = f"{ua_short} sur {os_name}"
            sessions = _load_active_sessions()
            now = int(time.time())
            updated = False
            for s in sessions:
                if s.get("id") == sid:
                    s["last_seen"] = now
                    s["ip"] = request.remote_addr or "?"
                    s["user_agent_short"] = ua_label
                    updated = True
                    break
            if not updated:
                sessions.append({
                    "id": sid,
                    "ip": request.remote_addr or "?",
                    "user_agent_short": ua_label,
                    "first_seen": now,
                    "last_seen": now,
                })
            # Garder seulement les 50 plus récentes
            sessions = sorted(sessions, key=lambda s: s.get("last_seen", 0), reverse=True)[:50]
            (DATA_DIR / "active_sessions.json").write_text(
                json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST" and not is_auth():
            username = (request.form.get("username") or "").strip().lower()
            password = request.form.get("password") or ""
            remember = (request.form.get("remember") or "") == "1"
            if _check_web_login(username, password):
                session["auth"] = True
                session["username"] = username or "admin"
                # "Se souvenir de moi" : session de 30 jours au lieu de session navigateur
                if remember:
                    session.permanent = True
                    import datetime as _dt_login
                    app.permanent_session_lifetime = _dt_login.timedelta(days=30)
                else:
                    session.permanent = False
                _track_session()
                return redirect("/")
            return _render_login("Nom d'utilisateur ou mot de passe incorrect")
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

    def _parse_file_id(file_id: str):
        """Parse 'identity|subdir|name' avec validation anti-path-traversal."""
        if not file_id or "|" not in file_id:
            return None
        parts = file_id.split("|", 2)
        if len(parts) != 3:
            return None
        ident, subdir, name = parts
        if ".." in name or "/" in name or "\\" in name:
            return None
        if subdir not in ("videos", "posts", "stories", "storyctas"):
            return None
        target_dir = IDENTITIES_DIR / ident / subdir
        target = target_dir / name
        if not target.exists() or not target.is_file():
            return None
        return target_dir, target

    @app.route("/cloud/meta/get")
    def cloud_meta_get():
        if not is_auth():
            return redirect("/")
        from flask import jsonify, request as r
        parsed = _parse_file_id(r.args.get("file_id", ""))
        if not parsed:
            return jsonify({"ok": False, "error": "bad file_id"}), 400
        target_dir, target = parsed
        stem = target.stem
        caption_file = target_dir / f"{stem}.txt"
        desc_file = target_dir / f"{stem}.desc.txt"
        caption = caption_file.read_text(encoding="utf-8") if caption_file.exists() else ""
        description = desc_file.read_text(encoding="utf-8") if desc_file.exists() else ""
        return jsonify({"ok": True, "caption": caption, "description": description})

    @app.route("/cloud/meta/save", methods=["POST"])
    def cloud_meta_save():
        if not is_auth():
            return redirect("/")
        from flask import jsonify, request as r
        parsed = _parse_file_id(r.form.get("file_id", ""))
        if not parsed:
            return jsonify({"ok": False, "error": "bad file_id"}), 400
        target_dir, target = parsed
        stem = target.stem
        caption = (r.form.get("caption") or "").strip()[:2200]
        description = (r.form.get("description") or "").strip()[:500]
        caption_file = target_dir / f"{stem}.txt"
        desc_file = target_dir / f"{stem}.desc.txt"
        try:
            if caption:
                caption_file.write_text(caption, encoding="utf-8")
            elif caption_file.exists():
                caption_file.unlink()
            if description:
                desc_file.write_text(description, encoding="utf-8")
            elif desc_file.exists():
                desc_file.unlink()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
        return jsonify({"ok": True})

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

    # ============ BIO LINKS ============

    @app.route("/biolinks/get")
    def biolinks_get():
        from flask import jsonify
        if not is_auth():
            return jsonify({"error": "unauth"}), 401
        try:
            from bio_links import get_bio
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        ident = (request.args.get("identity", "") or "").lower().strip()
        if not ident:
            return jsonify({"error": "no identity"}), 400
        return jsonify(get_bio(ident))

    @app.route("/biolinks/save_meta", methods=["POST"])
    def biolinks_save_meta():
        if not is_auth():
            return redirect("/")
        try:
            from bio_links import set_bio_meta
        except Exception as e:
            return _error(f"Module indispo: {e}")
        ident = (request.form.get("identity", "") or "").lower().strip()
        if not ident:
            return _error("❌ Identité manquante")
        display_name = request.form.get("display_name", "") or ""
        bio_text = request.form.get("bio", "") or ""
        theme = request.form.get("theme", "dark") or "dark"
        set_bio_meta(ident, display_name, bio_text, theme)
        return _success(f"✅ Profil bio de @{ident} mis à jour")

    @app.route("/biolinks/add_link", methods=["POST"])
    def biolinks_add_link():
        if not is_auth():
            return redirect("/")
        try:
            from bio_links import add_link
        except Exception as e:
            return _error(f"Module indispo: {e}")
        ident = (request.form.get("identity", "") or "").lower().strip()
        title = (request.form.get("title", "") or "").strip()
        url = (request.form.get("url", "") or "").strip()
        icon = (request.form.get("icon", "🔗") or "🔗").strip() or "🔗"
        if not ident or not title or not url:
            return _error("❌ Identité, titre et URL requis")
        add_link(ident, title, url, icon)
        return _success(f"✅ Lien ajouté à @{ident}")

    @app.route("/biolinks/remove_link", methods=["POST"])
    def biolinks_remove_link():
        from flask import jsonify
        if not is_auth():
            return jsonify({"error": "unauth"}), 401
        try:
            from bio_links import remove_link
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        ident = (request.form.get("identity", "") or "").lower().strip()
        try:
            link_id = int(request.form.get("link_id", "0"))
        except Exception:
            return jsonify({"success": False, "error": "bad id"}), 400
        ok = remove_link(ident, link_id)
        return jsonify({"success": ok})

    @app.route("/bio/<identity>")
    def bio_public(identity):
        """Page publique style Linktree (pas d'auth requise)."""
        ident = (identity or "").lower().strip()
        if not ident:
            return "Not Found", 404
        return _render_bio_public_page(ident)

    # ============ GETMYSOCIAL ============

    @app.route("/gms/save_key", methods=["POST"])
    def gms_save_key():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        key = (request.form.get("api_key") or "").strip()
        if not key or len(key) < 20 or not key.startswith("gms_"):
            return _error("❌ Clé invalide (doit commencer par <code>gms_</code> et faire 20+ caractères)")
        gms.save_api_key(key)
        # Test immédiat
        res = gms.ping()
        if res.get("ok"):
            return _success(f"✅ Clé enregistrée et validée (user <code>{res.get('user_id', '?')[:18]}…</code>)")
        return _error(f"⚠ Clé enregistrée mais le test a échoué : {res.get('error', '?')}")

    @app.route("/gms/test", methods=["POST"])
    def gms_test():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        res = gms.ping()
        if res.get("ok"):
            return _success(f"✅ Connexion OK (user <code>{res.get('user_id', '?')[:18]}…</code>)")
        return _error(f"❌ Test échoué : {res.get('error', '?')}")

    @app.route("/gms/set_template", methods=["POST"])
    def gms_set_template():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        ident = (request.form.get("identity") or "").strip().lower()
        link_id = (request.form.get("link_id") or "").strip()
        if not ident:
            return _error("❌ Identité manquante")
        gms.set_template_for_model(ident, link_id)
        if link_id:
            return _success(f"✅ Template défini pour <code>@{ident}</code>")
        return _success(f"✅ Template retiré pour <code>@{ident}</code>")

    @app.route("/gms/quick_generate", methods=["POST"])
    def gms_quick_generate():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        ident = (request.form.get("identity") or "").strip().lower()
        if not ident:
            return _error("❌ Identité manquante")
        templates = gms.load_templates()
        tpl_id = templates.get(ident)
        if not tpl_id:
            return _error(f"❌ Aucun template défini pour <code>@{ident}</code>. Configure-le d'abord ↑")

        # Génère shortcode = <random 4 lettres> + identity
        new_shortcode = gms.generate_random_prefix(4) + ident
        # Display name lisible
        new_name = f"@{ident} — {new_shortcode}"
        # Pas de nouvelle URL : on garde celle du template
        res = gms.duplicate_link(tpl_id, new_shortcode, new_name, new_url="")
        if not res.get("ok"):
            return _error(f"❌ {res.get('error', 'Génération échouée')}")
        link = res.get("link") or {}
        url_dest = link.get("url") or "(landing page)"
        return _success(
            f"✅ Nouveau lien généré : <code>/{new_shortcode}</code> "
            f"(clone de <code>{tpl_id[:18]}…</code>) → {url_dest}"
        )

    @app.route("/gms/duplicate", methods=["POST"])
    def gms_duplicate():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        source = (request.form.get("source_link_id") or "").strip()
        short = (request.form.get("shortcode") or "").strip()
        name = (request.form.get("display_name") or "").strip()
        url = (request.form.get("url") or "").strip()
        if not source or not source.startswith("lnk_"):
            return _error("❌ Lien source invalide")
        if not short or len(short) < 3 or len(short) > 24:
            return _error("❌ Shortcode doit faire 3-24 caractères")
        if not name:
            return _error("❌ Nom affiché requis")
        res = gms.duplicate_link(source, short, name, url)
        if res.get("ok"):
            link = res.get("link") or {}
            lid = link.get("id", "?")
            url_part = f" → {url}" if url else " (URL conservée du template)"
            return _success(f"✅ Lien <code>/{short}</code> dupliqué depuis le template{url_part}")
        return _error(f"❌ {res.get('error', 'Duplication échouée')}")

    @app.route("/gms/create", methods=["POST"])
    def gms_create():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        short = (request.form.get("shortcode") or "").strip()
        url = (request.form.get("url") or "").strip()
        name = (request.form.get("display_name") or "").strip()
        if not short or not url:
            return _error("❌ Shortcode et URL requis")
        if len(short) < 3 or len(short) > 24:
            return _error("❌ Shortcode doit faire 3-24 caractères")
        res = gms.create_directlink(short, url, name)
        if res.get("ok"):
            link = res.get("link") or {}
            lid = link.get("id", "?")
            return _success(f"✅ Lien <code>/{short}</code> créé ({lid[:18]}…)")
        return _error(f"❌ {res.get('error', 'Création échouée')}")

    @app.route("/gms/toggle", methods=["POST"])
    def gms_toggle():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        lid = (request.form.get("link_id") or "").strip()
        action = (request.form.get("action") or "").strip()
        if not lid or action not in ("enable", "disable"):
            return _error("❌ Paramètres invalides")
        res = gms.enable_link(lid) if action == "enable" else gms.disable_link(lid)
        if res.get("ok"):
            verb = "activé" if action == "enable" else "désactivé"
            return _success(f"✅ Lien {verb}")
        return _error(f"❌ {res.get('error', 'Action échouée')}")

    # ============ MYPULS ============

    @app.route("/mypuls/save_cookies", methods=["POST"])
    def mypuls_save_cookies():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        phpsessid = (request.form.get("phpsessid") or "").strip()
        rememberme = (request.form.get("rememberme") or "").strip()
        if not phpsessid or len(phpsessid) < 16:
            return _error("❌ PHPSESSID invalide (au moins 16 caractères)")
        mypuls.save_cookies(phpsessid, rememberme)
        # Test immédiat
        res = mypuls.ping()
        if res.get("ok"):
            return _success(f"✅ Cookies MyPuls enregistrés. Connecté en tant que <code>{res.get('email', '?')}</code>")
        return _error(f"⚠ Cookies enregistrés mais ping échoué : {res.get('error', '?')}")

    @app.route("/mypuls/clear_cookies", methods=["POST"])
    def mypuls_clear_cookies():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        cfg = mypuls.load_config()
        cfg.pop("PHPSESSID", None)
        cfg.pop("REMEMBERME", None)
        mypuls.save_config(cfg)
        return _success("✅ Cookies MyPuls supprimés")

    @app.route("/mypuls/refresh_rate", methods=["POST"])
    def mypuls_refresh_rate():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        res = mypuls.get_eur_usd_rate(force_refresh=True)
        return _success(f"✅ Taux EUR→USD mis à jour : 1€ = {res['rate']:.4f}$ ({res.get('date', '?')})")

    @app.route("/mypuls/chatter/set_pct", methods=["POST"])
    def mypuls_chatter_set_pct():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        name = (request.form.get("name") or "").strip()
        try:
            pct = float(request.form.get("pct") or "0")
        except Exception:
            return _error("❌ % invalide")
        if not name:
            return _error("❌ Nom manquant")
        mypuls.set_commission_pct(name, pct)
        return _success(f"✅ {name} → {pct:g}%")

    @app.route("/mypuls/chatter/set_crypto", methods=["POST"])
    def mypuls_chatter_set_crypto():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        name = (request.form.get("name") or "").strip()
        crypto_type = (request.form.get("crypto_type") or "").strip().upper()
        network = (request.form.get("crypto_network") or "").strip()
        address = (request.form.get("crypto_address") or "").strip()
        if not name:
            return _error("❌ Nom du chatteur manquant")
        if crypto_type and crypto_type not in mypuls.CRYPTO_TYPES:
            return _error(f"❌ Crypto inconnue ({crypto_type})")
        mypuls.set_crypto_address(name, crypto_type, network, address)
        if crypto_type:
            return _success(f"✅ {name} → {crypto_type} ({network or 'pas de réseau'})")
        return _success(f"✅ Infos crypto effacées pour {name}")

    @app.route("/mypuls/chatter/upload_crypto", methods=["POST"])
    def mypuls_chatter_upload_crypto():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        name = (request.form.get("name") or "").strip()
        if not name:
            return _error("❌ Nom du chatteur manquant")
        f = request.files.get("file")
        if not f or not f.filename:
            return _error("❌ Fichier manquant")
        # Limiter à 5MB
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        if size > 5 * 1024 * 1024:
            return _error("❌ Fichier trop gros (max 5MB)")
        try:
            data = f.read()
            mypuls.save_crypto_screenshot(name, data, f.filename)
        except Exception as e:
            return _error(f"❌ Erreur upload : {e}")
        return _success(f"✅ Screenshot crypto enregistré pour <code>{name}</code>")

    @app.route("/mypuls/chatter/crypto/<path:name>")
    def mypuls_chatter_crypto(name):
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception:
            return "", 404
        from urllib.parse import unquote
        name_dec = unquote(name)
        p = mypuls.crypto_path_for(name_dec)
        if not p or not p.exists():
            return "", 404
        from flask import send_file
        return send_file(str(p))

    @app.route("/mypuls/chatter/delete_crypto", methods=["POST"])
    def mypuls_chatter_delete_crypto():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        name = (request.form.get("name") or "").strip()
        if not name:
            return _error("❌ Nom manquant")
        ok = mypuls.delete_crypto_file(name)
        return _success(f"✅ Screenshot supprimé pour <code>{name}</code>") if ok else _error("❌ Pas de screenshot à supprimer")

    @app.route("/mypuls/avatar/<int:creator_id>")
    def mypuls_avatar(creator_id):
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception:
            return "", 404
        res = mypuls.get_avatar_bytes(creator_id)
        if not res.get("ok"):
            return "", 404
        from flask import Response
        resp = Response(res["content"], mimetype=res.get("content_type", "image/jpeg"))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/mypuls/test", methods=["POST"])
    def mypuls_test():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls
        except Exception as e:
            return _error(f"❌ Module mypuls indispo : {e}")
        res = mypuls.ping()
        if res.get("ok"):
            return _success(f"✅ MyPuls OK — connecté en tant que <code>{res.get('email', '?')}</code>")
        return _error(f"❌ {res.get('error', 'Test échoué')}")

    @app.route("/veille/add", methods=["POST"])
    def veille_add():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify, request as _r
        try:
            import veille
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        try:
            payload = _r.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}
        res = veille.add_reel(payload)
        return jsonify(res)

    @app.route("/veille/remove", methods=["POST"])
    def veille_remove():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import veille
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        rid = (request.form.get("reel_id") or "").strip()
        if not rid:
            return jsonify({"ok": False, "error": "reel_id manquant"})
        ok = veille.remove_reel(rid)
        return jsonify({"ok": ok})

    @app.route("/veille/send", methods=["POST"])
    def veille_send():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import veille
            import veille_telegram
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        rid = (request.form.get("reel_id") or "").strip()
        if not rid:
            return jsonify({"ok": False, "error": "reel_id manquant"})
        reel = veille.get_reel(rid)
        if not reel:
            return jsonify({"ok": False, "error": "Reel introuvable"})
        if not veille_telegram.is_configured():
            return jsonify({"ok": False, "error": "Bot Telegram non configuré"})
        res = veille_telegram.send_url(reel.get("url", ""), caption=f"📌 @{reel.get('owner', '?')}")
        if res.get("ok"):
            veille.mark_sent(rid)
        return jsonify(res)

    @app.route("/veille/send_day", methods=["POST"])
    def veille_send_day():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import veille
            import veille_telegram
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        day = (request.form.get("day") or "").strip()
        if not day:
            return jsonify({"ok": False, "error": "day manquant"})
        if not veille_telegram.is_configured():
            return jsonify({"ok": False, "error": "Bot Telegram non configuré"})
        by_day = veille.reels_by_day()
        reels = by_day.get(day, [])
        sent, failed = 0, 0
        for r in reels:
            if r.get("sent_to_telegram"):
                continue
            res = veille_telegram.send_url(r.get("url", ""), caption=f"📌 @{r.get('owner', '?')}")
            if res.get("ok"):
                veille.mark_sent(r["id"])
                sent += 1
            else:
                failed += 1
        return jsonify({"ok": True, "sent": sent, "failed": failed})

    @app.route("/settings/veille_telegram", methods=["POST"])
    def settings_veille_telegram():
        if not is_auth():
            return redirect("/")
        try:
            import veille_telegram
        except Exception as e:
            return _error(f"❌ Module veille_telegram indispo : {e}", tab="vtg")
        bot_token = (request.form.get("bot_token") or "").strip()
        chat_id = (request.form.get("chat_id") or "").strip()
        if not bot_token or not chat_id:
            return _error("❌ Bot token + chat ID requis", tab="vtg")
        veille_telegram.set_credentials(bot_token, chat_id)
        return _success("✅ Config Veille Telegram sauvegardée", tab="vtg")

    @app.route("/settings/veille_telegram/test", methods=["POST"])
    def settings_veille_telegram_test():
        if not is_auth():
            return redirect("/")
        try:
            import veille_telegram
        except Exception as e:
            return _error(f"❌ Module indispo : {e}", tab="vtg")
        res = veille_telegram.test_connection()
        if res.get("ok"):
            return _success("✅ Connexion OK — message test envoyé sur le chat", tab="vtg")
        return _error(f"❌ {res.get('error', 'Erreur inconnue')}", tab="vtg")

    @app.route("/chatting/create_edt", methods=["POST"])
    def chatting_create_edt():
        if not is_auth():
            return redirect("/")
        import chatting
        name = (request.form.get("name") or "").strip()
        if not name:
            return _error("❌ Nom manquant", tab="chatplanning")
        edt = chatting.create_edt(name)
        for cre in chatting.CRENEAUX:
            chatting.add_row(edt["id"], cre)
        return redirect(f"/?tab=chatplanning&edt_id={edt['id']}")

    @app.route("/chatting/create_preset", methods=["POST"])
    def chatting_create_preset():
        if not is_auth():
            return redirect("/")
        import chatting
        preset = (request.form.get("preset") or "").strip().lower()
        if preset == "of":
            name = "EDT OnlyFans"
        elif preset == "mym":
            name = "EDT MYM"
        else:
            return _error("❌ Preset invalide", tab="chatplanning")
        # Verifier qu il n existe pas deja
        for e in chatting.list_edts():
            if e.get("name", "").lower() == name.lower():
                return redirect(f"/?tab=chatplanning&edt_id={e['id']}")
        edt = chatting.create_edt(name)
        for cre in chatting.CRENEAUX:
            chatting.add_row(edt["id"], cre)
        return redirect(f"/?tab=chatplanning&edt_id={edt['id']}")

    @app.route("/chatting/rename_edt", methods=["POST"])
    def chatting_rename_edt():
        if not is_auth():
            return redirect("/")
        import chatting
        chatting.rename_edt(
            (request.form.get("edt_id") or "").strip(),
            (request.form.get("new_name") or "").strip(),
        )
        return redirect(f"/?tab=chatplanning&edt_id={request.form.get('edt_id') or ''}")

    @app.route("/chatting/delete_edt", methods=["POST"])
    def chatting_delete_edt():
        if not is_auth():
            return redirect("/")
        import chatting
        chatting.delete_edt((request.form.get("edt_id") or "").strip())
        return redirect("/?tab=chatplanning")

    @app.route("/chatting/add_row", methods=["POST"])
    def chatting_add_row():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        import chatting
        from flask import jsonify
        edt_id = (request.form.get("edt_id") or "").strip()
        cre = (request.form.get("creneau") or "02h-08h").strip()
        row = chatting.add_row(edt_id, cre)
        if not row:
            return jsonify({"ok": False, "error": "EDT introuvable"})
        return jsonify({"ok": True, "row_id": row["id"], "creneau": cre})

    @app.route("/chatting/delete_row", methods=["POST"])
    def chatting_delete_row():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False}), 401
        import chatting
        from flask import jsonify
        ok = chatting.delete_row(
            (request.form.get("edt_id") or "").strip(),
            (request.form.get("row_id") or "").strip(),
        )
        return jsonify({"ok": ok})

    @app.route("/chatting/update_cell", methods=["POST"])
    def chatting_update_cell():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False}), 401
        import chatting
        from flask import jsonify
        ok = chatting.update_cell(
            (request.form.get("edt_id") or "").strip(),
            (request.form.get("row_id") or "").strip(),
            (request.form.get("field") or "").strip(),
            (request.form.get("value") or "").strip(),
            week_start=(request.form.get("week_start") or "").strip(),
        )
        return jsonify({"ok": ok})

    @app.route("/mypulslive/reorder_creators", methods=["POST"])
    def mypulslive_reorder_creators():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import mypuls
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        raw = (request.form.get("order") or "").strip()
        if not raw:
            return jsonify({"ok": False, "error": "order vide"})
        try:
            ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except Exception:
            return jsonify({"ok": False, "error": "ids invalides"})
        mypuls.save_creator_order(ids)
        return jsonify({"ok": True, "saved": len(ids)})

    @app.route("/mypulslive/campaign/pause", methods=["POST"])
    def mypulslive_campaign_pause():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls_campaigns
        except Exception as e:
            return _error(f"❌ Module campagnes indispo : {e}", tab="mypulslive")
        cid = (request.form.get("campaign_id") or "").strip()
        if not cid:
            return _error("❌ Campaign ID manquant", tab="mypulslive")
        if mypuls_campaigns.set_campaign_active(cid, False):
            return _success(f"⏸ Campagne {cid[:14]} mise en pause", tab="mypulslive")
        return _error("❌ Campagne introuvable", tab="mypulslive")

    @app.route("/mypulslive/campaign/resume", methods=["POST"])
    def mypulslive_campaign_resume():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls_campaigns
        except Exception as e:
            return _error(f"❌ Module campagnes indispo : {e}", tab="mypulslive")
        cid = (request.form.get("campaign_id") or "").strip()
        if not cid:
            return _error("❌ Campaign ID manquant", tab="mypulslive")
        if mypuls_campaigns.set_campaign_active(cid, True):
            return _success(f"▶ Campagne {cid[:14]} reactivee", tab="mypulslive")
        return _error("❌ Campagne introuvable", tab="mypulslive")

    @app.route("/mypulslive/campaign/delete", methods=["POST"])
    def mypulslive_campaign_delete():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls_campaigns
        except Exception as e:
            return _error(f"❌ Module campagnes indispo : {e}", tab="mypulslive")
        cid = (request.form.get("campaign_id") or "").strip()
        if not cid:
            return _error("❌ Campaign ID manquant", tab="mypulslive")
        if mypuls_campaigns.delete_campaign(cid):
            return _success(f"🗑 Campagne {cid[:14]} supprimee", tab="mypulslive")
        return _error("❌ Campagne introuvable", tab="mypulslive")

    @app.route("/mypulslive/list_events", methods=["GET"])
    def mypulslive_list_events():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import mypuls_scheduler
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        try:
            cid = int(request.args.get("creator") or 0)
        except Exception:
            return jsonify({"ok": False, "error": "creator invalide"})
        start = (request.args.get("start") or "").strip()
        end = (request.args.get("end") or "").strip()
        if not cid or not start or not end:
            return jsonify({"ok": False, "error": "creator/start/end requis"})
        # Format ISO sans tz
        start_iso = start + "T00:00:00"
        end_iso = end + "T23:59:59"
        res = mypuls_scheduler.list_calendar_events([cid], start_iso, end_iso)
        if not res.get("ok"):
            return jsonify({"ok": False, "error": res.get("error", "fetch echoue")})
        events = res.get("events", [])
        # Garde uniquement les events futurs (status=schedule)
        filtered = []
        for e in events:
            ep = e.get("extendedProps", {}) or {}
            if ep.get("status") == "schedule":
                filtered.append(e)
        return jsonify({"ok": True, "events": filtered})

    @app.route("/mypulslive/delete_events", methods=["POST"])
    def mypulslive_delete_events():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls_scheduler
        except Exception as e:
            return _error(f"❌ Module indispo : {e}", tab="mypulslive")
        ids_raw = (request.form.get("delete_ids") or "").strip()
        if not ids_raw:
            return _error("❌ Aucun event selectionne", tab="mypulslive")
        try:
            ids = [int(x.strip()) for x in ids_raw.split(",") if x.strip()]
        except Exception:
            return _error("❌ IDs invalides", tab="mypulslive")
        deleted, failed = 0, 0
        first_errors = []
        for i in ids:
            res = mypuls_scheduler.delete_story(i)
            if res.get("ok"):
                deleted += 1
            else:
                failed += 1
                if len(first_errors) < 3:
                    first_errors.append(f"{i}: {res.get('error','?')[:60]}")
        msg = f"✅ Suppression : {deleted} OK / {failed} fail"
        if first_errors:
            msg += " | " + " ; ".join(first_errors)
        return _success(msg, tab="mypulslive")

    @app.route("/mypulslive/fetch_media", methods=["GET"])
    def mypulslive_fetch_media():
        if not is_auth():
            from flask import jsonify
            return jsonify({"ok": False, "error": "unauth"}), 401
        from flask import jsonify
        try:
            import mypuls_scheduler
        except Exception as e:
            return jsonify({"ok": False, "error": f"module indispo: {e}"})
        try:
            cid = int(request.args.get("creator") or 0)
        except Exception:
            return jsonify({"ok": False, "error": "creator id invalide"})
        if not cid:
            return jsonify({"ok": False, "error": "creator manquant"})
        res = mypuls_scheduler.list_all_media(cid, hard_limit=500)
        if not res.get("ok"):
            return jsonify({"ok": False, "error": res.get("error", "fetch echoue")})
        ids = [int(m["id"]) for m in res.get("items", []) if m.get("id")]
        return jsonify({"ok": True, "ids": ids, "total": len(ids)})

    @app.route("/mypulslive/push", methods=["POST"])
    def mypulslive_push():
        if not is_auth():
            return redirect("/")
        try:
            import mypuls_scheduler
        except Exception as e:
            return _error(f"❌ Module mypuls_scheduler indispo : {e}", tab="mypulslive")

        try:
            creator_id = int(request.form.get("creator_id") or 0)
        except Exception:
            return _error("❌ Createur invalide", tab="mypulslive")
        if not creator_id:
            return _error("❌ Createur manquant", tab="mypulslive")

        content_type = (request.form.get("content_type") or "both").strip()
        date_start = (request.form.get("date_start") or "").strip()
        date_end = (request.form.get("date_end") or "").strip()
        infinite_mode = (request.form.get("infinite_mode") or "0") == "1"
        post_slots_raw = request.form.get("post_slots_json") or "[]"
        story_slots_raw = request.form.get("story_slots_json") or "[]"
        media_ids_raw = request.form.get("media_ids") or ""
        captions_raw = request.form.get("captions") or ""
        post_action = (request.form.get("post_action") or "delete").strip()
        try:
            post_delete_days = int(request.form.get("post_delete_days") or 2)
        except Exception:
            post_delete_days = 2
        delay_sec = max(1, post_delete_days) * 86400
        # Options toggles
        shuffle_media = (request.form.get("shuffle_media") or "0") == "1"
        randomize_minutes = (request.form.get("randomize_minutes") or "1") == "1"
        # infinite_recycle est l'algorithme par defaut (cycle via modulo) - le flag
        # est pour info, le code recycle de toute facon
        import json as _json
        try:
            post_slots = _json.loads(post_slots_raw)
            if not isinstance(post_slots, list):
                post_slots = []
        except Exception:
            post_slots = []
        try:
            story_slots = _json.loads(story_slots_raw)
            if not isinstance(story_slots, list):
                story_slots = []
        except Exception:
            story_slots = []

        if not date_start:
            return _error("❌ Date de debut manquante", tab="mypulslive")
        if not infinite_mode and not date_end:
            return _error("❌ Date de fin manquante (sinon active Mode infini)", tab="mypulslive")

        def _parse_lines(raw):
            return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]

        media_ids_str = _parse_lines(media_ids_raw)
        try:
            media_ids = [int(m) for m in media_ids_str]
        except Exception:
            return _error("❌ media_ids doivent etre des entiers", tab="mypulslive")
        if not media_ids:
            return _error("❌ Aucun media_id", tab="mypulslive")

        captions = _parse_lines(captions_raw) or [""]

        # === Mode INFINI : creer une campagne au lieu d'un push one-shot ===
        if infinite_mode and content_type in ("story", "post"):
            try:
                import mypuls_campaigns
                import mypuls
            except Exception as e:
                return _error(f"❌ Module campagnes indispo : {e}", tab="mypulslive")
            # Recup nom du createur
            creators = mypuls.list_creators().get("creators", {})
            cname = ""
            for n, cid in creators.items():
                if int(cid) == creator_id:
                    cname = n
                    break
            slots = story_slots if content_type == "story" else post_slots
            if not slots:
                return _error("❌ Aucun slot configure pour ce type", tab="mypulslive")
            res = mypuls_campaigns.create_campaign(
                creator_id=creator_id,
                creator_name=cname,
                campaign_type=content_type,
                slots=slots,
                media_ids=media_ids,
                captions=captions,
                options={"shuffle_media": shuffle_media, "randomize_minutes": randomize_minutes},
                post_action=post_action,
                delay_sec=delay_sec,
                start_date=date_start,
            )
            if not res.get("ok"):
                return _error(f"❌ Creation campagne : {res.get('error', '?')}", tab="mypulslive")
            return _success(
                f"♾️ Campagne {content_type} lancee — premiers 2 jours planifies : "
                f"{res.get('planned', 0)} {content_type}(s). Le cron etend de 2 jours toutes les heures.",
                tab="mypulslive",
            )

        summary_parts = []
        all_errors = []

        # Story push
        if content_type in ("story", "both") and story_slots:
            # story_slots est une liste de "HH:MM" strings
            res = mypuls_scheduler.bulk_schedule_stories(
                creator_id=creator_id,
                media_ids=media_ids,
                date_start=date_start,
                date_end=date_end,
                story_slots=story_slots,
                shuffle_media=shuffle_media,
                randomize_minutes=randomize_minutes,
            )
            summary_parts.append(
                f"📱 Stories : {res.get('planned', 0)} OK / {res.get('failed', 0)} fail"
            )
            if res.get("errors"):
                all_errors.extend(res["errors"][:3])

        # Post push
        if content_type in ("post", "both") and post_slots:
            # post_slots est [{time:"HH:MM", visibility:"public"|"private"}, ...]
            res = mypuls_scheduler.bulk_schedule_posts(
                creator_id=creator_id,
                media_ids=media_ids,
                captions=captions,
                date_start=date_start,
                date_end=date_end,
                post_slots=post_slots,
                action=post_action,
                delay_sec=delay_sec,
                shuffle_media=shuffle_media,
                randomize_minutes=randomize_minutes,
            )
            summary_parts.append(
                f"📰 Posts : {res.get('planned', 0)} OK / {res.get('failed', 0)} fail"
            )
            if res.get("errors"):
                all_errors.extend(res["errors"][:3])

        if not summary_parts:
            return _error("❌ Aucun slot configure pour le type choisi", tab="mypulslive")

        msg = "✅ Push live termine — " + " | ".join(summary_parts)
        if all_errors:
            msg += " | Premieres erreurs : " + "; ".join(all_errors[:3])
        return _success(msg, tab="mypulslive")

    @app.route("/schedule/generate", methods=["POST"])
    def schedule_generate():
        if not is_auth():
            return redirect("/")
        try:
            import schedule_xlsx
        except Exception as e:
            return _error(f"❌ Module schedule_xlsx indispo (pip install openpyxl ?) : {e}", tab="schedule")

        model_name = (request.form.get("model_name") or "").strip()
        date_start = (request.form.get("date_start") or "").strip()
        date_end = (request.form.get("date_end") or "").strip()
        public_hours = (request.form.get("public_hours") or "").strip()
        private_hours = (request.form.get("private_hours") or "").strip()
        media_ids = request.form.get("media_ids") or ""
        captions = request.form.get("captions") or ""

        if not model_name:
            return _error("❌ Nom du modele manquant", tab="schedule")
        if not date_start or not date_end:
            return _error("❌ Dates manquantes", tab="schedule")
        if not media_ids.strip():
            return _error("❌ Aucun media_id fourni", tab="schedule")
        if not public_hours and not private_hours:
            return _error("❌ Au moins une heure (publique ou privee) doit etre indiquee", tab="schedule")

        try:
            xlsx_bytes, filename = schedule_xlsx.generate_xlsx(
                model_name=model_name,
                date_start=date_start,
                date_end=date_end,
                public_hours_raw=public_hours,
                private_hours_raw=private_hours,
                media_ids_raw=media_ids,
                captions_raw=captions,
            )
        except ValueError as e:
            return _error(f"❌ {e}", tab="schedule")
        except Exception as e:
            return _error(f"❌ Generation echouee : {type(e).__name__}: {e}", tab="schedule")

        from flask import Response
        resp = Response(
            xlsx_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        # ASCII-safe disposition (RFC 5987 for unicode filename)
        try:
            ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "template_import.xlsx"
        except Exception:
            ascii_name = "template_import.xlsx"
        from urllib.parse import quote
        resp.headers["Content-Disposition"] = (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''" + quote(filename)
        )
        return resp

    @app.route("/gms/delete", methods=["POST"])
    def gms_delete():
        if not is_auth():
            return redirect("/")
        try:
            import gms
        except Exception as e:
            return _error(f"❌ Module gms indispo : {e}")
        lid = (request.form.get("link_id") or "").strip()
        short = (request.form.get("shortcode") or "").strip() or lid[:12]
        if not lid:
            return _error("❌ ID manquant")
        res = gms.delete_link(lid)
        if res.get("ok"):
            return _success(f"✅ Lien <code>/{short}</code> supprimé")
        return _error(f"❌ {res.get('error', 'Suppression échouée')}")

    @app.route("/account/profile_pic")
    def account_profile_pic():
        if not is_auth():
            return redirect("/")
        for ext in ("png", "jpg", "jpeg", "webp"):
            p = DATA_DIR / f"profile_pic.{ext}"
            if p.exists():
                from flask import send_file
                return send_file(str(p))
        return "Not found", 404

    @app.route("/settings/account", methods=["POST"])
    def settings_account():
        if not is_auth():
            return redirect("/")
        settings = _load_account_settings()
        display_name = (request.form.get("display_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        if display_name:
            settings["display_name"] = display_name[:60]
        if email:
            settings["email"] = email[:120]
        f = request.files.get("profile_pic")
        if f and f.filename:
            ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
            if ext in ("png", "jpg", "jpeg", "webp"):
                # Supprimer les anciennes
                for old_ext in ("png", "jpg", "jpeg", "webp"):
                    old = DATA_DIR / f"profile_pic.{old_ext}"
                    if old.exists():
                        try:
                            old.unlink()
                        except Exception:
                            pass
                f.save(str(DATA_DIR / f"profile_pic.{ext}"))
        _save_account_settings(settings)
        return _success("✅ Profil sauvegardé")

    @app.route("/settings/account_password", methods=["POST"])
    def settings_account_password():
        if not is_auth():
            return redirect("/")
        new_pwd = (request.form.get("new_password") or "").strip()
        confirm = (request.form.get("confirm_password") or "").strip()
        if not new_pwd or len(new_pwd) < 6:
            return _error("❌ Mot de passe trop court (min 6 caractères)")
        if new_pwd != confirm:
            return _error("❌ Les mots de passe ne correspondent pas")
        ok = _write_env_var("WEB_UPLOAD_PASSWORD", new_pwd)
        if not ok:
            return _error("❌ Erreur écriture .env")
        _schedule_restart(2.0)
        return _success("✅ Mot de passe changé. Redémarrage dans 2 sec — reconnecte-toi.")

    @app.route("/security/revoke_session", methods=["POST"])
    def security_revoke():
        if not is_auth():
            return redirect("/")
        sid = (request.form.get("session_id") or "").strip()
        sessions = _load_active_sessions()
        sessions = [s for s in sessions if s.get("id") != sid]
        try:
            (DATA_DIR / "active_sessions.json").write_text(
                json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            return _error(f"❌ Erreur : {e}")
        return _success("✅ Session révoquée")

    @app.route("/settings/role/add", methods=["POST"])
    def settings_role_add():
        if not is_auth():
            return redirect("/")
        username = (request.form.get("username") or "").strip()
        role = (request.form.get("role") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        if not username or not role or len(password) < 6:
            return _error("❌ Champs requis manquants ou password trop court")
        users = _load_role_users()
        if any(u.get("username") == username for u in users):
            return _error(f"❌ {username} existe déjà")
        users.append({
            "username": username,
            "role": role,
            "password_hash": password,  # TODO: bcrypt hash in real prod
            "created_at": int(time.time()),
        })
        _save_role_users(users)
        return _success(f"✅ Utilisateur <b>{username}</b> ajouté (rôle : {role})")

    @app.route("/settings/role/remove", methods=["POST"])
    def settings_role_remove():
        if not is_auth():
            return redirect("/")
        username = (request.form.get("username") or "").strip()
        users = _load_role_users()
        users = [u for u in users if u.get("username") != username]
        _save_role_users(users)
        return _success(f"✅ {username} supprimé")

    @app.route("/settings/role/delete", methods=["POST"])
    def settings_role_delete():
        if not is_auth():
            return redirect("/")
        key = (request.form.get("role_key") or "").strip()
        if not key or key == "owner":
            return _error("❌ Impossible de supprimer ce rôle")
        defs = _load_role_definitions()
        if key in defs:
            del defs[key]
            _save_role_definitions(defs)
        # Réinitialiser les users qui avaient ce rôle
        users = _load_role_users()
        for u in users:
            if u.get("role") == key:
                u["role"] = "va"  # downgrade en VA par défaut
        _save_role_users(users)
        return _success(f"✅ Rôle <b>{key}</b> supprimé")

    @app.route("/settings/role/edit_def", methods=["POST"])
    def settings_role_edit_def():
        if not is_auth():
            return redirect("/")
        key = (request.form.get("role_key") or "").strip()
        name = (request.form.get("name") or "").strip()[:50]
        desc = (request.form.get("description") or "").strip()[:300]
        if not key or not name:
            return _error("❌ Champs requis manquants")
        defs = _load_role_definitions()
        if key not in defs:
            defs[key] = {}
        defs[key]["name"] = name
        defs[key]["description"] = desc
        _save_role_definitions(defs)
        return _success(f"✅ Rôle <b>{name}</b> mis à jour")

    @app.route("/settings/role/permissions", methods=["GET", "POST"])
    def settings_role_permissions():
        if not is_auth():
            from flask import jsonify
            return jsonify({"error": "auth required"}), 401
        from flask import jsonify
        if request.method == "GET":
            key = (request.args.get("key") or "").strip()
            if not key:
                return jsonify({"error": "key required"}), 400
            defs = _load_role_definitions()
            perms = defs.get(key, {}).get("permissions", {})
            return jsonify({"key": key, "permissions": perms})
        # POST
        key = (request.form.get("role_key") or "").strip()
        perms_json = request.form.get("permissions") or "{}"
        try:
            perms = json.loads(perms_json)
        except Exception:
            return jsonify({"error": "invalid permissions JSON"}), 400
        defs = _load_role_definitions()
        if key not in defs:
            defs[key] = {}
        defs[key]["permissions"] = perms
        _save_role_definitions(defs)
        return jsonify({"success": True})

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

    @app.route("/va/set_insta", methods=["POST"])
    def va_set_insta():
        from flask import jsonify
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        uid = (request.form.get("user_id") or "").strip()
        handle = (request.form.get("handle") or "").strip()
        if not uid:
            return jsonify({"ok": False, "error": "user_id manquant"}), 400
        try:
            _set_va_insta(uid, handle)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
        return jsonify({"ok": True})

    @app.route("/va/scrape_insta", methods=["POST"])
    def va_scrape_insta():
        from flask import jsonify
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        uid = (request.form.get("user_id") or "").strip()
        handle = (request.form.get("handle") or "").strip().lstrip("@")
        if not uid or not handle:
            return jsonify({"ok": False, "error": "user_id et handle requis"}), 400
        try:
            from insta_scraper import scrape_profile
            data = scrape_profile(handle, limit=3)
            if not data or "error" in data:
                err = data.get("error", "scrape échoué") if data else "scrape échoué"
                return jsonify({"ok": False, "error": err})
            # Extraire les champs utiles
            followers = int(data.get("followers", 0) or 0)
            posts_count = int(data.get("posts_count", 0) or data.get("posts", 0) or 0)
            # Dernier post timestamp
            last_post_at = ""
            posts_list = data.get("posts") if isinstance(data.get("posts"), list) else []
            if posts_list:
                # Trouver le timestamp le plus récent
                import datetime as _dt_sc
                latest_ts = 0
                for p in posts_list:
                    ts = p.get("taken_at", 0) if isinstance(p, dict) else 0
                    if ts and ts > latest_ts:
                        latest_ts = int(ts)
                if latest_ts:
                    last_post_at = _dt_sc.datetime.fromtimestamp(latest_ts).isoformat()
            _update_va_insta_stats(uid, handle, followers, posts_count, last_post_at)
            return jsonify({"ok": True, "followers": followers, "posts": posts_count,
                            "last_post_at": last_post_at})
        except ImportError:
            _set_va_insta(uid, handle)
            return jsonify({"ok": False, "error": "insta_scraper indispo, handle sauvegardé seulement"})
        except Exception as e:
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})

    @app.route("/va/set_payment", methods=["POST"])
    def va_set_payment():
        from flask import jsonify
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        uid = (request.form.get("user_id") or "").strip()
        if not uid:
            return jsonify({"ok": False, "error": "user_id manquant"}), 400
        try:
            _set_va_payment(uid, {
                "kind": request.form.get("kind", ""),
                "crypto_type": request.form.get("crypto_type", ""),
                "crypto_network": request.form.get("crypto_network", ""),
                "crypto_address": request.form.get("crypto_address", ""),
                "taptap_number": request.form.get("taptap_number", ""),
                "taptap_network": request.form.get("taptap_network", ""),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
        return jsonify({"ok": True})

    @app.route("/va/set_links", methods=["POST"])
    def va_set_links():
        from flask import jsonify
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        uid = (request.form.get("user_id") or "").strip()
        link_ids = request.form.getlist("link_ids")
        if not uid:
            return jsonify({"ok": False, "error": "user_id manquant"}), 400
        # Validation basique des link_ids (commence par lnk_)
        clean = [l for l in link_ids if isinstance(l, str) and l.startswith("lnk_")]
        try:
            _set_links_for_va(uid, clean)
            # Invalider le cache pour ce VA
            _VA_DAILY_CACHE.pop("|".join(sorted(clean)), None)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
        return jsonify({"ok": True, "count": len(clean)})

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
