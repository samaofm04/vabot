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
from pathlib import Path

BOT_DIR = Path(__file__).parent.resolve()
NOCTUS_SRC = BOT_DIR / "noctus"                 # pipeline-core.js + runner + fonts
NOCTUS_DATA = BOT_DIR / "data" / "noctus"       # données user (models/, captions.json, temp/)
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
V_FOLDERS = [f"V{i}" for i in range(1, 11)]

_PROCS = {}  # model_id -> subprocess.Popen


# ---------- helpers système ----------
def node_available() -> bool:
    return shutil.which("node") is not None


def deps_installed() -> bool:
    return (NOCTUS_SRC / "node_modules" / "@napi-rs" / "canvas").exists()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def setup_ok() -> bool:
    return node_available() and deps_installed() and ffmpeg_available()


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
    f = _models_dir() / _safe(model_id) / "_status.json"
    try:
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    proc = _PROCS.get(_safe(model_id))
    if proc and proc.poll() is None:
        return {"state": "running"}
    return {"state": "idle"}


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
        (NOCTUS_DATA / "captions.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


# ---------- run / stop ----------
def run(model_id: str, folders=None, captions=None, targets=None):
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
    }
    old = _PROCS.get(mid)
    if old and old.poll() is None:
        stop(mid)
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True  # groupe de process -> kill propre
    proc = subprocess.Popen(
        ["node", "noctus_runner.js", json.dumps(payload)],
        cwd=str(NOCTUS_SRC),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    _PROCS[mid] = proc
    return proc


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
        setup_banner = (
            "<div style='background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.4);"
            "border-radius:12px;padding:16px 18px;margin-bottom:18px;color:#fca5a5;font-size:13px;line-height:1.6'>"
            "⚠️ <b>Setup incomplet sur ce serveur</b> — manque : <b>" + esc(", ".join(miss)) + "</b>.<br>"
            "Lance une fois sur le VPS :<br>"
            "<code style='display:block;background:#0a0a0a;border:1px solid #2a2a2a;border-radius:8px;"
            "padding:10px 12px;margin-top:8px;color:#8ef;white-space:pre-wrap'>"
            "sudo apt update &amp;&amp; sudo apt install -y nodejs npm ffmpeg\n"
            "cd /opt/va-bot/noctus &amp;&amp; npm install</code>"
            "</div>"
        )

    # Options modèles
    model_opts = "".join(
        f"<option value='{esc(m['id'])}'>{esc(m['id'])} — {m['inputs']} source(s), {m['outputs']} généré(s)</option>"
        for m in models
    )
    if not model_opts:
        model_opts = "<option value=''>(aucun modèle — crée-en un)</option>"

    cap_checks = "".join(
        f"<label style='display:inline-flex;align-items:center;gap:6px;background:#1a1a1a;border:1px solid #2a2a2a;"
        f"padding:6px 11px;border-radius:8px;font-size:12px;cursor:pointer'>"
        f"<input type='checkbox' class='nx-cap' value='{esc(l)}' checked style='accent-color:#a855f7'> {esc(l)}</label>"
        for l in cap_labels
    ) or "<span style='color:#666;font-size:12px'>aucune version de caption — édite-les ci-dessous</span>"

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
    <div style="font-size:12px;color:#888;margin:14px 0 6px">Versions de captions :</div>
    <div id="nx-caps" style="display:flex;flex-wrap:wrap;gap:8px">{cap_checks}</div>
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
    <p style="color:#888;font-size:12px;margin:10px 0">Format : liste de versions {{label, font, captions:[{{start,end,text}}]}}. Fonts : Inter, Poppins, Montserrat, BebasNeue, Anton, TikTokSans.</p>
    <textarea id="nx-capsjson" spellcheck="false" style="width:100%;min-height:200px;background:#0a0a0a;border:1px solid #2a2a2a;color:#8ef;border-radius:10px;padding:12px;font-family:monospace;font-size:12px">{caps_json}</textarea>
    <button onclick="nxSaveCaptions()" style="margin-top:10px;padding:9px 16px;background:#1a1a1a;border:1px solid #3a3a3a;color:#ddd;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px">💾 Sauver les captions</button>
    <span id="nx-capsmsg" style="margin-left:10px;font-size:12px"></span>
  </details>
</div>

<script>
function nxModel(){{ const s=document.getElementById('nx-model'); return s? s.value : ''; }}
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
      html+='<div style="width:120px"><video src="'+url+'" muted playsinline preload=metadata onloadeddata="try{{this.currentTime=0.1}}catch(e){{}}" style="width:120px;aspect-ratio:9/16;object-fit:cover;border-radius:8px;background:#000"></video><a href="'+url+'" download style="display:block;text-align:center;color:#8ef;font-size:11px;margin-top:3px;text-decoration:none">⬇ télécharger</a></div>';
    }});
    html+='</div></div>';
  }});
  wrap.innerHTML=html;
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
        captions = [c for c in (request.form.get("captions") or "").split(",") if c.strip()]
        proc = run(mid, folders or None, captions or None)
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
        p = _models_dir() / mid / "output" / vf / name
        if not p.exists() or not p.is_file():
            return "Not found", 404
        return send_file(str(p))

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
