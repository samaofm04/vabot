/* ============================================================================
   Éditeur "mini CapCut" — Création de vidéos (Noctus)
   - Preview 9:16 avec textes draggables (position x/y sauvée en fraction)
   - Panneau propriétés : texte, police, taille, couleur, timing
   - Timeline : piste vidéo + blocs texte déplaçables/étirables, playhead
   - Sauvegarde = version de captions (POST /noctus/save_version) utilisable
     ensuite dans la génération V1→V10 (le pipeline lit x/y/size/color/font).
   Servi par /noctus/editor.js (fichier séparé -> zéro échappement Python).
   ========================================================================== */
(function () {
  'use strict';

  var FONTS = ['TikTokSans', 'TikTokSansRegular', 'Inter', 'InterMedium', 'InterRegular',
               'Poppins', 'Montserrat', 'BebasNeue', 'Anton'];
  var COLORS = ['#ffffff', '#fde047', '#f87171', '#4ade80', '#60a5fa', '#c084fc', '#fb923c', '#f472b6', '#000000'];
  var BASE_W = 1080, BASE_H = 1920; // référentiel du pipeline

  var S = {
    model: null, file: null, files: [],
    caps: [],            // [{id,text,start,end,x,y,size,color,font}]
    sel: null,           // id caption sélectionnée
    dur: 30,             // durée vidéo (s)
    pxPerSec: 40,        // zoom timeline
    playing: false,
    idSeq: 1,
    drag: null
  };

  function $(id) { return document.getElementById(id); }
  function video() { return $('nxed-video'); }
  function fmtT(t) {
    t = Math.max(0, t || 0);
    var m = Math.floor(t / 60), s = t - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(1);
  }
  function secToHms(t) {
    t = Math.max(0, t || 0);
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    function p2(n) { return (n < 10 ? '0' : '') + n; }
    var ss = s.toFixed(3);
    if (s < 10) ss = '0' + ss;
    return p2(h) + ':' + p2(m) + ':' + ss;
  }
  function hmsToSec(x) {
    if (typeof x === 'number') return x;
    var p = String(x || '0').split(':').map(parseFloat);
    if (p.length === 3) return (p[0] || 0) * 3600 + (p[1] || 0) * 60 + (p[2] || 0);
    if (p.length === 2) return (p[0] || 0) * 60 + (p[1] || 0);
    return p[0] || 0;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function selCap() {
    for (var i = 0; i < S.caps.length; i++) if (S.caps[i].id === S.sel) return S.caps[i];
    return null;
  }

  /* ───────────────────────── Construction du DOM ───────────────────────── */
  function buildUI() {
    if ($('nxed')) return;
    var root = document.createElement('div');
    root.id = 'nxed';
    root.innerHTML =
      '<style>' +
      '#nxed{position:fixed;inset:0;z-index:99990;background:#101014;color:#e8e8ee;display:none;flex-direction:column;font-family:Inter,-apple-system,sans-serif;user-select:none}' +
      '#nxed.open{display:flex}' +
      '#nxed *{box-sizing:border-box}' +
      '#nxed-top{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#17171c;border-bottom:1px solid #26262c;flex-shrink:0}' +
      '#nxed-top input,#nxed-top select{background:#232329;border:1px solid #33333b;color:#fff;border-radius:8px;padding:8px 10px;font-size:13px;width:auto}' +
      '.nxed-btn{background:#232329;border:1px solid #33333b;color:#ddd;border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;margin:0}' +
      '.nxed-btn:hover{background:#2b2b33;color:#fff}' +
      '.nxed-primary{background:linear-gradient(135deg,#6366f1,#a855f7)!important;border:0!important;color:#fff!important;font-weight:800}' +
      '#nxed-mid{display:flex;flex:1;min-height:0}' +
      '#nxed-left{width:240px;background:#141419;border-right:1px solid #26262c;padding:12px;overflow-y:auto;flex-shrink:0}' +
      '.nxed-h{font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#7a7a85;margin:0 0 10px}' +
      '.nxed-media{display:flex;align-items:center;gap:8px;padding:9px 10px;border-radius:8px;cursor:pointer;font-size:12.5px;color:#c9c9d2;border:1px solid transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.nxed-media:hover{background:#1d1d24}' +
      '.nxed-media.on{background:rgba(99,102,241,.14);border-color:rgba(99,102,241,.5);color:#fff}' +
      '#nxed-center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0;background:#0b0b0f;position:relative;padding:14px}' +
      '#nxed-stage{position:relative;height:100%;max-height:100%;aspect-ratio:9/16;background:#000;border-radius:10px;overflow:hidden;box-shadow:0 0 0 1px #26262c}' +
      '#nxed-video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}' +
      '.nxed-ov{position:absolute;transform:translate(-50%,-50%);cursor:grab;white-space:pre;text-align:center;line-height:1.45;font-weight:700;-webkit-text-stroke:0;text-shadow:0 0 4px rgba(0,0,0,.9),0 0 2px rgba(0,0,0,.9);padding:4px 8px;border:1.5px dashed transparent;border-radius:6px;max-width:92%}' +
      '.nxed-ov.on{border-color:#6aa8ff;background:rgba(99,102,241,.08)}' +
      '.nxed-ov:active{cursor:grabbing}' +
      '#nxed-right{width:280px;background:#141419;border-left:1px solid #26262c;padding:14px;overflow-y:auto;flex-shrink:0}' +
      '#nxed-right label{display:block;font-size:11px;color:#8a8a95;font-weight:700;margin:14px 0 6px;text-transform:uppercase;letter-spacing:.05em}' +
      '#nxed-right textarea,#nxed-right input,#nxed-right select{width:100%;background:#1e1e25;border:1px solid #33333b;color:#fff;border-radius:8px;padding:9px 11px;font-size:13px;font-family:inherit}' +
      '#nxed-right textarea{min-height:76px;resize:vertical}' +
      '.nxed-sw{width:26px;height:26px;border-radius:6px;cursor:pointer;border:2px solid transparent;display:inline-block}' +
      '.nxed-sw.on{border-color:#fff}' +
      '#nxed-bottom{height:190px;background:#141419;border-top:1px solid #26262c;flex-shrink:0;display:flex;flex-direction:column}' +
      '#nxed-transport{display:flex;align-items:center;gap:12px;padding:8px 16px;border-bottom:1px solid #222228}' +
      '#nxed-tlwrap{flex:1;overflow-x:auto;overflow-y:hidden;position:relative}' +
      '#nxed-tl{position:relative;height:100%;min-width:100%}' +
      '#nxed-ruler{position:relative;height:22px;border-bottom:1px solid #222228;cursor:pointer}' +
      '.nxed-tick{position:absolute;top:0;height:100%;border-left:1px solid #2c2c34;color:#6a6a75;font-size:9px;padding:3px 0 0 4px}' +
      '#nxed-vtrack{position:relative;height:34px;margin:8px 0 6px}' +
      '#nxed-vbar{position:absolute;top:0;height:100%;background:linear-gradient(135deg,#1f3a5f,#232355);border:1px solid #33518a;border-radius:6px;color:#9db7e8;font-size:11px;font-weight:600;display:flex;align-items:center;padding:0 10px;overflow:hidden;white-space:nowrap}' +
      '#nxed-ttracks{position:relative;flex:1;min-height:56px}' +
      '.nxed-blk{position:absolute;height:26px;background:linear-gradient(135deg,#7c3aed,#a855f7);border-radius:6px;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;padding:0 12px;cursor:grab;overflow:hidden;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.4)}' +
      '.nxed-blk.on{outline:2px solid #6aa8ff}' +
      '.nxed-hdl{position:absolute;top:0;width:9px;height:100%;cursor:ew-resize}' +
      '.nxed-hdl.l{left:0;border-radius:6px 0 0 6px}.nxed-hdl.r{right:0;border-radius:0 6px 6px 0}' +
      '.nxed-hdl:hover{background:rgba(255,255,255,.25)}' +
      '#nxed-ph{position:absolute;top:0;bottom:0;width:2px;background:#f43f5e;z-index:10;pointer-events:none}' +
      '#nxed-ph::before{content:"";position:absolute;top:0;left:-5px;border:6px solid transparent;border-top-color:#f43f5e}' +
      '</style>' +

      '<div id="nxed-top">' +
      '<button class="nxed-btn" onclick="nxEdClose()">&#8592; Retour</button>' +
      '<span style="font-weight:800;font-size:14px">&#127916; &Eacute;diteur</span>' +
      '<span style="color:#55555f">|</span>' +
      '<span style="font-size:12px;color:#8a8a95">Version :</span>' +
      '<input id="nxed-label" placeholder="nom de la version (ex: hook_v1)" style="width:200px">' +
      '<select id="nxed-loadsel" style="max-width:180px"><option value="">Charger une version&hellip;</option></select>' +
      '<div style="flex:1"></div>' +
      '<span id="nxed-msg" style="font-size:12px;color:#8a8a95"></span>' +
      '<button class="nxed-btn nxed-primary" onclick="nxEdSave()">&#128190; Enregistrer la version</button>' +
      '</div>' +

      '<div id="nxed-mid">' +
      '<div id="nxed-left"><div class="nxed-h">M&eacute;dias du mod&egrave;le</div><div id="nxed-medias"></div></div>' +
      '<div id="nxed-center"><div id="nxed-stage">' +
      '<video id="nxed-video" playsinline></video>' +
      '<div id="nxed-ovs" style="position:absolute;inset:0"></div>' +
      '</div></div>' +
      '<div id="nxed-right">' +
      '<div class="nxed-h">Texte s&eacute;lectionn&eacute;</div>' +
      '<div id="nxed-props" style="display:none">' +
      '<label>Contenu</label><textarea id="nxed-text"></textarea>' +
      '<label>Police</label><select id="nxed-font"></select>' +
      '<label>Taille <span id="nxed-sizeval" style="color:#fff"></span></label>' +
      '<input id="nxed-size" type="range" min="20" max="120" step="2" style="padding:0">' +
      '<label>Couleur</label><div id="nxed-colors" style="display:flex;gap:6px;flex-wrap:wrap"></div>' +
      '<input id="nxed-colorpick" type="color" value="#ffffff" style="margin-top:8px;height:34px;padding:2px">' +
      '<label>Timing (secondes)</label>' +
      '<div style="display:flex;gap:8px;align-items:center">' +
      '<input id="nxed-start" type="number" min="0" step="0.1" style="width:50%">' +
      '<span style="color:#666">&#8594;</span>' +
      '<input id="nxed-end" type="number" min="0" step="0.1" style="width:50%">' +
      '</div>' +
      '<button class="nxed-btn" style="width:100%;margin-top:16px;border-color:#7f1d1d;color:#f87171" onclick="nxEdDelCap()">&#128465; Supprimer ce texte</button>' +
      '</div>' +
      '<div id="nxed-noprops" style="color:#66666f;font-size:12.5px;line-height:1.6">Clique un texte sur la vid&eacute;o ou dans la timeline pour l&#39;&eacute;diter.<br><br>&#128161; Astuce : glisse le texte directement sur la vid&eacute;o pour le placer, et &eacute;tire ses bords dans la timeline pour r&eacute;gler quand il appara&icirc;t.</div>' +
      '</div>' +
      '</div>' +

      '<div id="nxed-bottom">' +
      '<div id="nxed-transport">' +
      '<button class="nxed-btn" id="nxed-play" onclick="nxEdPlay()" style="width:42px;text-align:center">&#9654;</button>' +
      '<span id="nxed-time" style="font-size:12px;color:#9a9aa5;font-variant-numeric:tabular-nums">0:00.0 / 0:00.0</span>' +
      '<button class="nxed-btn nxed-primary" onclick="nxEdAddCap()" style="padding:7px 14px">+ Texte</button>' +
      '<div style="flex:1"></div>' +
      '<span style="font-size:11px;color:#66666f">Zoom</span>' +
      '<input id="nxed-zoom" type="range" min="14" max="120" value="40" style="width:110px;padding:0" oninput="nxEdZoom(this.value)">' +
      '</div>' +
      '<div id="nxed-tlwrap"><div id="nxed-tl">' +
      '<div id="nxed-ruler"></div>' +
      '<div id="nxed-vtrack"><div id="nxed-vbar"></div></div>' +
      '<div id="nxed-ttracks"></div>' +
      '<div id="nxed-ph" style="left:0"></div>' +
      '</div></div>' +
      '</div>';
    document.body.appendChild(root);

    // Panneau propriétés : bindings
    var fsel = $('nxed-font');
    FONTS.forEach(function (f) {
      var o = document.createElement('option'); o.value = f; o.textContent = f; fsel.appendChild(o);
    });
    var cw = $('nxed-colors');
    COLORS.forEach(function (c) {
      var d = document.createElement('span');
      d.className = 'nxed-sw'; d.style.background = c; d.dataset.c = c;
      d.addEventListener('click', function () { nxEdSetColor(c); });
      cw.appendChild(d);
    });
    $('nxed-colorpick').addEventListener('input', function () { nxEdSetColor(this.value); });
    $('nxed-text').addEventListener('input', function () {
      var c = selCap(); if (!c) return; c.text = this.value; renderOverlays(); renderTimeline();
    });
    $('nxed-font').addEventListener('change', function () {
      var c = selCap(); if (!c) return; c.font = this.value; renderOverlays();
    });
    $('nxed-size').addEventListener('input', function () {
      var c = selCap(); if (!c) return; c.size = parseInt(this.value, 10);
      $('nxed-sizeval').textContent = c.size + 'px'; renderOverlays();
    });
    $('nxed-start').addEventListener('change', function () {
      var c = selCap(); if (!c) return;
      c.start = Math.max(0, Math.min(parseFloat(this.value) || 0, c.end - 0.1));
      renderTimeline(); renderOverlays();
    });
    $('nxed-end').addEventListener('change', function () {
      var c = selCap(); if (!c) return;
      c.end = Math.min(S.dur, Math.max(parseFloat(this.value) || 0, c.start + 0.1));
      renderTimeline(); renderOverlays();
    });
    $('nxed-loadsel').addEventListener('change', function () {
      if (this.value) nxEdLoadVersion(this.value);
    });

    // Vidéo : sync playhead
    var v = video();
    v.addEventListener('loadedmetadata', function () {
      S.dur = v.duration || 30; renderRuler(); renderTimeline(); updPlayhead();
    });
    v.addEventListener('timeupdate', function () { updPlayhead(); renderOverlays(); });
    v.addEventListener('play', function () { S.playing = true; $('nxed-play').innerHTML = '&#10074;&#10074;'; tick(); });
    v.addEventListener('pause', function () { S.playing = false; $('nxed-play').innerHTML = '&#9654;'; });

    // Ruler : seek au clic/drag
    $('nxed-ruler').addEventListener('pointerdown', function (e) {
      seekFromEvent(e); S.drag = { kind: 'seek' };
      this.setPointerCapture(e.pointerId);
    });
    $('nxed-ruler').addEventListener('pointermove', function (e) {
      if (S.drag && S.drag.kind === 'seek') seekFromEvent(e);
    });
    $('nxed-ruler').addEventListener('pointerup', function () { S.drag = null; });

    document.addEventListener('keydown', function (e) {
      if (!$('nxed').classList.contains('open')) return;
      if (e.key === ' ' && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'INPUT') {
        e.preventDefault(); nxEdPlay();
      }
      if (e.key === 'Escape') nxEdClose();
    });
  }

  function tick() {
    if (!S.playing) return;
    updPlayhead(); renderOverlays();
    requestAnimationFrame(tick);
  }
  function seekFromEvent(e) {
    var wrap = $('nxed-tlwrap');
    var x = e.clientX - $('nxed-tl').getBoundingClientRect().left;
    var t = Math.max(0, Math.min(S.dur, x / S.pxPerSec));
    video().currentTime = t;
    updPlayhead(); renderOverlays();
  }
  function updPlayhead() {
    var t = video().currentTime || 0;
    $('nxed-ph').style.left = (t * S.pxPerSec) + 'px';
    $('nxed-time').textContent = fmtT(t) + ' / ' + fmtT(S.dur);
  }

  /* ───────────────────────── Rendus ───────────────────────── */
  function renderMedias() {
    var w = $('nxed-medias');
    if (!S.files.length) {
      w.innerHTML = '<div style="color:#66666f;font-size:12px;line-height:1.5">Aucune vid&eacute;o source.<br>Uploade dans la section 1 puis rouvre.</div>';
      return;
    }
    w.innerHTML = S.files.map(function (f) {
      return '<div class="nxed-media' + (f === S.file ? ' on' : '') + '" data-f="' + esc(f) + '">&#127909; ' + esc(f) + '</div>';
    }).join('');
    Array.prototype.forEach.call(w.querySelectorAll('.nxed-media'), function (el) {
      el.addEventListener('click', function () { loadFile(el.dataset.f); });
    });
  }

  function loadFile(f) {
    S.file = f;
    var v = video();
    v.src = '/noctus/input_file/' + encodeURIComponent(S.model) + '/' + encodeURIComponent(f);
    v.load();
    renderMedias();
    $('nxed-vbar').textContent = '🎬 ' + f;
  }

  function stageFontFamily(f) {
    if (f === 'BebasNeue' || f === 'Anton' || f === 'Montserrat' || f === 'Poppins' || f === 'Inter') return f + ',Inter,sans-serif';
    return 'Inter,sans-serif';
  }

  function renderOverlays() {
    var wrap = $('nxed-ovs');
    var stH = $('nxed-stage').clientHeight || 1;
    var scale = stH / BASE_H;
    var t = video().currentTime || 0;
    var html = '';
    S.caps.forEach(function (c) {
      var visible = t >= c.start && t < c.end;
      if (!visible && c.id !== S.sel) return;
      html += '<div class="nxed-ov' + (c.id === S.sel ? ' on' : '') + '" data-id="' + c.id + '" style="' +
        'left:' + (c.x * 100) + '%;top:' + (c.y * 100) + '%;' +
        'font-size:' + Math.max(9, Math.round(c.size * scale)) + 'px;' +
        'color:' + c.color + ';font-family:' + stageFontFamily(c.font) + ';' +
        'opacity:' + (visible ? '1' : '.35') + '">' + esc(c.text) + '</div>';
    });
    wrap.innerHTML = html;
    Array.prototype.forEach.call(wrap.querySelectorAll('.nxed-ov'), function (el) {
      el.addEventListener('pointerdown', function (e) {
        e.preventDefault();
        var id = parseInt(el.dataset.id, 10);
        selectCap(id);
        var st = $('nxed-stage').getBoundingClientRect();
        S.drag = { kind: 'ov', id: id, stW: st.width, stH: st.height, stL: st.left, stT: st.top };
        el.setPointerCapture(e.pointerId);
      });
      el.addEventListener('pointermove', function (e) {
        if (!S.drag || S.drag.kind !== 'ov') return;
        var c = selCap(); if (!c) return;
        c.x = Math.max(0.03, Math.min(0.97, (e.clientX - S.drag.stL) / S.drag.stW));
        c.y = Math.max(0.03, Math.min(0.96, (e.clientY - S.drag.stT) / S.drag.stH));
        el.style.left = (c.x * 100) + '%';
        el.style.top = (c.y * 100) + '%';
      });
      el.addEventListener('pointerup', function () { S.drag = null; });
    });
  }

  function renderRuler() {
    var r = $('nxed-ruler');
    var tl = $('nxed-tl');
    tl.style.width = Math.max(S.dur * S.pxPerSec + 80, $('nxed-tlwrap').clientWidth) + 'px';
    var step = S.pxPerSec < 24 ? 5 : (S.pxPerSec < 60 ? 2 : 1);
    var html = '';
    for (var t = 0; t <= S.dur; t += step) {
      html += '<div class="nxed-tick" style="left:' + (t * S.pxPerSec) + 'px">' + t + 's</div>';
    }
    r.innerHTML = html;
    var vb = $('nxed-vbar');
    vb.style.left = '0px';
    vb.style.width = (S.dur * S.pxPerSec) + 'px';
  }

  function renderTimeline() {
    var w = $('nxed-ttracks');
    // lanes : évite le chevauchement visuel
    var lanes = [];
    var sorted = S.caps.slice().sort(function (a, b) { return a.start - b.start; });
    var html = '';
    sorted.forEach(function (c) {
      var lane = 0;
      while (lane < lanes.length && lanes[lane] > c.start + 0.001) lane++;
      lanes[lane] = c.end;
      var lbl = (c.text || '').split('\n')[0].slice(0, 30) || 'texte';
      html += '<div class="nxed-blk' + (c.id === S.sel ? ' on' : '') + '" data-id="' + c.id + '" style="' +
        'left:' + (c.start * S.pxPerSec) + 'px;width:' + Math.max(24, (c.end - c.start) * S.pxPerSec) + 'px;' +
        'top:' + (lane * 30) + 'px">' +
        '<div class="nxed-hdl l" data-h="l"></div><span style="pointer-events:none">T &nbsp;' + esc(lbl) + '</span><div class="nxed-hdl r" data-h="r"></div>' +
        '</div>';
    });
    w.innerHTML = html;
    Array.prototype.forEach.call(w.querySelectorAll('.nxed-blk'), function (el) {
      el.addEventListener('pointerdown', function (e) {
        var id = parseInt(el.dataset.id, 10);
        selectCap(id);
        var h = e.target.dataset ? e.target.dataset.h : null;
        var c = selCap();
        S.drag = { kind: h ? 'resize-' + h : 'move', id: id, x0: e.clientX, s0: c.start, e0: c.end };
        el.setPointerCapture(e.pointerId);
        e.preventDefault();
      });
      el.addEventListener('pointermove', function (e) {
        if (!S.drag || S.drag.id !== parseInt(el.dataset.id, 10)) return;
        var c = selCap(); if (!c) return;
        var dt = (e.clientX - S.drag.x0) / S.pxPerSec;
        if (S.drag.kind === 'move') {
          var len = S.drag.e0 - S.drag.s0;
          c.start = Math.max(0, Math.min(S.dur - len, S.drag.s0 + dt));
          c.end = c.start + len;
        } else if (S.drag.kind === 'resize-l') {
          c.start = Math.max(0, Math.min(S.drag.e0 - 0.2, S.drag.s0 + dt));
        } else if (S.drag.kind === 'resize-r') {
          c.end = Math.min(S.dur, Math.max(S.drag.s0 + 0.2, S.drag.e0 + dt));
        }
        el.style.left = (c.start * S.pxPerSec) + 'px';
        el.style.width = Math.max(24, (c.end - c.start) * S.pxPerSec) + 'px';
        syncProps();
      });
      el.addEventListener('pointerup', function () { S.drag = null; renderTimeline(); renderOverlays(); });
    });
  }

  function syncProps() {
    var c = selCap();
    if (!c) { $('nxed-props').style.display = 'none'; $('nxed-noprops').style.display = 'block'; return; }
    $('nxed-props').style.display = 'block';
    $('nxed-noprops').style.display = 'none';
    if (document.activeElement !== $('nxed-text')) $('nxed-text').value = c.text;
    $('nxed-font').value = c.font;
    $('nxed-size').value = c.size;
    $('nxed-sizeval').textContent = c.size + 'px';
    $('nxed-start').value = c.start.toFixed(1);
    $('nxed-end').value = c.end.toFixed(1);
    Array.prototype.forEach.call(document.querySelectorAll('.nxed-sw'), function (s) {
      s.classList.toggle('on', s.dataset.c.toLowerCase() === (c.color || '').toLowerCase());
    });
  }

  function selectCap(id) {
    S.sel = id;
    syncProps(); renderOverlays(); renderTimeline();
  }

  /* ───────────────────────── Actions globales ───────────────────────── */
  window.nxEdOpen = function () {
    var model = (typeof nxModel === 'function') ? nxModel() : '';
    if (!model) { alert('Choisis/crée un modèle d&#39;abord'); return; }
    buildUI();
    S.model = model;
    $('nxed').classList.add('open');
    $('nxed-msg').textContent = '';
    fetch('/noctus/inputs?model=' + encodeURIComponent(model))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        S.files = (j && j.files) || [];
        renderMedias();
        if (S.files.length && !S.file) loadFile(S.files[0]);
      });
    // versions existantes -> select "Charger"
    fetch('/noctus/captions').then(function (r) { return r.json(); }).then(function (j) {
      var sel = $('nxed-loadsel');
      sel.innerHTML = '<option value="">Charger une version&hellip;</option>';
      ((j && j.captions) || []).forEach(function (v) {
        if (!v || !v.label || v.label === 'sans_texte') return;
        var o = document.createElement('option');
        o.value = v.label; o.textContent = v.label + ' (' + ((v.captions || []).length) + ')';
        sel.appendChild(o);
      });
    });
    renderRuler(); renderTimeline(); renderOverlays(); syncProps();
  };

  window.nxEdClose = function () {
    var v = video(); if (v) v.pause();
    $('nxed').classList.remove('open');
    // rafraîchit la liste des versions de la page derrière (nouvelles versions sauvées)
    if (S.savedOnce) location.reload();
  };

  window.nxEdPlay = function () {
    var v = video();
    if (v.paused) v.play(); else v.pause();
  };

  window.nxEdZoom = function (val) {
    S.pxPerSec = parseInt(val, 10) || 40;
    renderRuler(); renderTimeline(); updPlayhead();
  };

  window.nxEdAddCap = function () {
    var t = video().currentTime || 0;
    var c = {
      id: S.idSeq++,
      text: 'Ton texte ici',
      start: Math.max(0, Math.min(t, Math.max(0, S.dur - 0.5))),
      end: Math.min(S.dur, t + 3),
      x: 0.5, y: 0.61, size: 44, color: '#ffffff', font: 'TikTokSans'
    };
    S.caps.push(c);
    selectCap(c.id);
    $('nxed-text').focus();
    $('nxed-text').select();
  };

  window.nxEdDelCap = function () {
    S.caps = S.caps.filter(function (c) { return c.id !== S.sel; });
    S.sel = null;
    syncProps(); renderOverlays(); renderTimeline();
  };

  window.nxEdSetColor = function (col) {
    var c = selCap(); if (!c) return;
    c.color = col;
    $('nxed-colorpick').value = col.length === 7 ? col : '#ffffff';
    syncProps(); renderOverlays();
  };

  window.nxEdLoadVersion = function (label) {
    fetch('/noctus/captions').then(function (r) { return r.json(); }).then(function (j) {
      var v = ((j && j.captions) || []).filter(function (x) { return x && x.label === label; })[0];
      if (!v) return;
      $('nxed-label').value = label;
      S.caps = (v.captions || []).map(function (s) {
        var end = hmsToSec(s.end);
        if (end > S.dur + 1) end = S.dur; // '99:99:99' = permanent
        return {
          id: S.idSeq++,
          text: s.text || '',
          start: Math.min(hmsToSec(s.start), Math.max(0, S.dur - 0.2)),
          end: Math.max(hmsToSec(s.start) + 0.2, Math.min(end, S.dur)),
          x: (s.x != null) ? parseFloat(s.x) : 0.5,
          y: (s.y != null) ? parseFloat(s.y) : 0.61,
          size: parseInt(s.size, 10) || 44,
          color: s.color || '#ffffff',
          font: s.font || v.font || 'TikTokSans'
        };
      });
      S.sel = null;
      syncProps(); renderOverlays(); renderTimeline();
    });
  };

  window.nxEdSave = function () {
    var label = ($('nxed-label').value || '').trim();
    var msg = $('nxed-msg');
    if (!label) { msg.style.color = '#f87171'; msg.textContent = 'Donne un nom de version'; $('nxed-label').focus(); return; }
    if (!S.caps.length) { msg.style.color = '#f87171'; msg.textContent = 'Ajoute au moins un texte (+ Texte)'; return; }
    var payload = S.caps.map(function (c) {
      // fin ~durée totale -> permanent (le texte reste jusqu'au bout, peu importe la source)
      var end = (c.end >= S.dur - 0.15) ? '99:99:99.000' : secToHms(c.end);
      return { start: secToHms(c.start), end: end, text: c.text,
               x: +c.x.toFixed(4), y: +c.y.toFixed(4), size: c.size, color: c.color, font: c.font };
    });
    var fd = new FormData();
    fd.set('label', label);
    fd.set('font', (S.caps[0] && S.caps[0].font) || 'TikTokSans');
    fd.set('json', JSON.stringify(payload));
    msg.style.color = '#8a8a95'; msg.textContent = 'Enregistrement…';
    fetch('/noctus/save_version', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) {
          S.savedOnce = true;
          msg.style.color = '#4ade80';
          msg.textContent = '✓ Version « ' + j.label + ' » enregistrée (' + j.count + ' texte(s)) — coche-la puis ▶ Générer';
        } else {
          msg.style.color = '#f87171'; msg.textContent = '❌ ' + (j.error || '?');
        }
      })
      .catch(function (e) { msg.style.color = '#f87171'; msg.textContent = 'Erreur réseau : ' + e; });
  };
})();
