/* ============================================================================
   Veille — « Préparer la veille » (v2 pro)
   Layout 2 colonnes : lecteur vidéo immédiat (route /veille/reelinfo) + panneau
   d'analyse. OCR rapide / toute la vidéo / jusqu'au curseur (précision 1/100s) /
   à la seconde. Caption + description éditables, chips modèles, aperçu Telegram.
   Fichier séparé (pas d'échappement dans UPLOAD_HTML).
   ========================================================================== */
(function () {
  'use strict';

  var S = { rid: null, models: [], selected: {}, raf: 0 };

  function esc(x) {
    return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function el(id) { return document.getElementById(id); }
  function toast(m, t) { if (typeof showToast === 'function') showToast(m, t || 'success'); }
  function fmtT(sec) {
    var m = Math.floor(sec / 60);
    var s = sec - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
  }

  var INP = 'width:100%;padding:10px 12px;background:#0b0e16;border:1px solid #262b3a;color:#e8eaf2;border-radius:10px;font-size:13px;font-family:inherit;box-sizing:border-box;outline:none;transition:border-color .15s';
  var SECTION = 'font-size:10px;color:#8a91a8;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px';
  var BTN_GHOST = 'padding:9px 14px;background:#161a26;border:1px solid #262b3a;color:#c9cede;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer;transition:all .15s';

  function close() {
    if (S.raf) { cancelAnimationFrame(S.raf); S.raf = 0; }
    var m = el('vprep-modal');
    if (m) m.remove();
  }

  function open(rid) {
    S.rid = rid; S.selected = {};
    close();
    var card = document.querySelector('.veille-card[data-rid="' + rid + '"]');
    var knownDesc = '';
    if (card && card.dataset.caption && card.dataset.caption.indexOf('Pas de caption') < 0) knownDesc = card.dataset.caption;

    var ov = document.createElement('div');
    ov.id = 'vprep-modal';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(2,4,10,.78);z-index:10000;display:flex;align-items:center;justify-content:center;padding:18px;backdrop-filter:blur(6px)';
    ov.innerHTML =
      '<div style="background:#0f1117;border:1px solid #232838;border-radius:18px;width:100%;max-width:900px;max-height:94vh;display:flex;flex-direction:column;box-shadow:0 40px 100px rgba(0,0,0,.7);overflow:hidden;animation:vprepIn .25s cubic-bezier(.16,1,.3,1)">' +
      '<style>@keyframes vprepIn{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}' +
      '.vp-chip{transition:all .12s}.vp-chip:hover{border-color:#3b82f6!important}' +
      '#vprep-modal textarea:focus,#vprep-modal input:focus{border-color:#3b82f6}' +
      '.vp-abtn:hover{filter:brightness(1.12)}.vp-abtn:disabled{opacity:.5;cursor:wait}</style>' +

      // ── Header ──
      '<div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid #1d2230;flex-shrink:0">' +
      '<div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:17px">🎯</div>' +
      '<div style="flex:1"><div style="font-size:15.5px;font-weight:800;color:#fff">Préparer la veille</div>' +
      '<div style="font-size:11.5px;color:#8a91a8">Lis le texte incrusté, valide, puis envoie aux modèles</div></div>' +
      '<button id="vprep-x" style="background:#161a26;border:1px solid #262b3a;color:#8a91a8;width:32px;height:32px;border-radius:9px;cursor:pointer;font-size:13px">✕</button>' +
      '</div>' +

      // ── Corps 2 colonnes ──
      '<div style="display:flex;gap:0;flex:1;min-height:0;overflow:hidden">' +

      // Colonne gauche : vidéo
      '<div style="width:300px;flex-shrink:0;padding:16px;border-right:1px solid #1d2230;overflow-y:auto;background:#0c0e15">' +
      '<div style="' + SECTION + '">Vidéo</div>' +
      '<div id="vprep-video-wrap"><div style="height:170px;border:1px dashed #262b3a;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#5a6178;font-size:11.5px">⏳ chargement du lecteur…</div></div>' +
      '<button id="vprep-upto" class="vp-abtn" disabled style="width:100%;margin-top:10px;padding:10px 12px;background:linear-gradient(135deg,#8b5cf6,#6d28d9);border:0;color:#fff;border-radius:10px;font-size:12px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px">' +
      '🧠 Analyser jusqu&#39;ici <span id="vprep-upto-t" style="font-family:ui-monospace,Consolas,monospace;font-size:11.5px;background:rgba(0,0,0,.28);padding:2px 7px;border-radius:6px">0:00.00</span></button>' +
      '<div style="font-size:10.5px;color:#5a6178;margin-top:7px;line-height:1.5">Place le curseur là où le texte s&#39;arrête (précis au 1/100s), puis clique — l&#39;analyse couvre du début jusqu&#39;à ce point.</div>' +
      '<div id="vprep-frame-wrap" style="margin-top:14px"></div>' +
      '</div>' +

      // Colonne droite : contrôles
      '<div style="flex:1;min-width:0;padding:16px 20px;overflow-y:auto">' +

      '<div style="' + SECTION + '">1 · Texte incrusté</div>' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">' +
      '<button id="vprep-ocr" class="vp-abtn" style="padding:9px 15px;background:linear-gradient(135deg,#3b82f6,#2563eb);border:0;color:#fff;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer">🔍 Analyser</button>' +
      '<button id="vprep-ocr-full" class="vp-abtn" title="8 images réparties sur toute la vidéo : capte les textes qui changent au fil du montage, sans répéter ce qui reste affiché" style="padding:9px 15px;background:linear-gradient(135deg,#8b5cf6,#6d28d9);border:0;color:#fff;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer">🧠 Toute la vidéo</button>' +
      '<div style="display:flex;align-items:center;gap:6px;margin-left:auto">' +
      '<input id="vprep-sec" type="number" min="0" step="0.1" placeholder="sec" style="' + INP + ';width:74px;padding:8px 9px;font-size:12px">' +
      '<button id="vprep-ocr-sec" class="vp-abtn" style="' + BTN_GHOST + '">à la seconde</button>' +
      '</div></div>' +
      '<div id="vprep-ocr-status" style="font-size:11.5px;color:#8a91a8;min-height:16px;margin-bottom:8px"></div>' +
      '<textarea id="vprep-cap" placeholder="Le texte lu sur la vidéo apparaîtra ici — corrige-le si besoin (retours à la ligne conservés)." style="' + INP + ';min-height:76px;resize:vertical;margin-bottom:18px;line-height:1.5"></textarea>' +

      '<div style="' + SECTION + '">2 · Description postée sous la vidéo</div>' +
      '<textarea id="vprep-desc" placeholder="La description qui accompagne la vidéo." style="' + INP + ';min-height:64px;resize:vertical;margin-bottom:18px;line-height:1.5">' + esc(knownDesc) + '</textarea>' +

      '<div style="' + SECTION + '">3 · Envoyer aux modèles</div>' +
      '<div id="vprep-models" style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:18px;min-height:30px;color:#5a6178;font-size:12px">Chargement…</div>' +

      '<div style="' + SECTION + '">Aperçu Telegram <span style="text-transform:none;letter-spacing:0;font-weight:600;color:#5a6178">(messages séparés)</span></div>' +
      '<div id="vprep-preview" style="display:flex;flex-direction:column;gap:7px;margin-bottom:6px"></div>' +

      '</div></div>' +

      // ── Footer ──
      '<div style="display:flex;gap:10px;justify-content:flex-end;align-items:center;padding:14px 20px;border-top:1px solid #1d2230;flex-shrink:0;background:#0c0e15">' +
      '<button id="vprep-cancel" style="' + BTN_GHOST + ';padding:10px 18px">Annuler</button>' +
      '<button id="vprep-ready" class="vp-abtn" title="Enregistrer la caption + la description sans envoyer — la carte passe « PRÊT »" style="padding:10px 18px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border:0;color:#fff;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;box-shadow:0 6px 18px rgba(59,130,246,.22)">💾 Marquer prêt</button>' +
      '<button id="vprep-send" class="vp-abtn" style="padding:10px 24px;background:linear-gradient(135deg,#22c55e,#15803d);border:0;color:#fff;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;box-shadow:0 6px 18px rgba(34,197,94,.25)">📤 Envoyer la veille</button>' +
      '</div></div>';
    ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
    document.body.appendChild(ov);

    el('vprep-x').addEventListener('click', close);
    el('vprep-cancel').addEventListener('click', close);
    el('vprep-ocr').addEventListener('click', function () { analyze(''); });
    el('vprep-ocr-full').addEventListener('click', function () { analyze('', true); });
    el('vprep-ocr-sec').addEventListener('click', function () { analyze(el('vprep-sec').value); });
    el('vprep-cap').addEventListener('input', preview);
    el('vprep-desc').addEventListener('input', preview);
    el('vprep-send').addEventListener('click', send);
    el('vprep-ready').addEventListener('click', savePrep);
    el('vprep-upto').addEventListener('click', function () {
      var pl = el('vprep-player');
      var ct = (pl && pl.currentTime) || 0;
      if (ct < 0.5) { toast('Place d\'abord le curseur de la vidéo au moment voulu', 'error'); return; }
      if (pl && !pl.paused) pl.pause();
      analyze('', true, ct.toFixed(2));
    });

    S.prepModels = [];
    loadModels();
    preview();
    loadInfo();       // lecteur + brouillon éventuel, puis décide l'OCR auto
  }

  /* ── Lecteur vidéo (immédiat) + compteur 1/100s ── */
  function setPlayer(url) {
    var vw = el('vprep-video-wrap');
    if (!vw || !url) return;
    var existing = el('vprep-player');
    if (existing) {
      if (existing.getAttribute('src') !== url) existing.setAttribute('src', url);
      return;
    }
    vw.innerHTML = '<video id="vprep-player" src="' + esc(url) + '" controls preload="metadata" playsinline style="width:100%;max-height:300px;border-radius:12px;background:#000;display:block"></video>';
    var pl = el('vprep-player');
    var btn = el('vprep-upto');
    var lbl = el('vprep-upto-t');
    if (btn) btn.disabled = false;
    // compteur haute précision (requestAnimationFrame, pas timeupdate ~4Hz)
    function tick() {
      if (!document.getElementById('vprep-player')) { S.raf = 0; return; }
      if (lbl && pl) lbl.textContent = fmtT(pl.currentTime || 0);
      S.raf = requestAnimationFrame(tick);
    }
    if (S.raf) cancelAnimationFrame(S.raf);
    S.raf = requestAnimationFrame(tick);
  }

  function loadInfo() {
    fetch('/veille/reelinfo?reel_id=' + encodeURIComponent(S.rid))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) { analyze(''); return; }
        if (j.video_url) setPlayer(j.video_url);
        var draft = j.prepared && ((j.prep_overlay || '').trim() || (j.prep_desc || '').trim() || (j.prep_models || []).length);
        if (draft) {
          // brouillon « PRÊT » : on recharge tel quel — PAS d'OCR auto, sinon on
          // écraserait la caption déjà validée.
          if ((j.prep_overlay || '').trim()) el('vprep-cap').value = j.prep_overlay;
          if ((j.prep_desc || '').trim()) el('vprep-desc').value = j.prep_desc;
          else if ((j.caption || '').trim() && !el('vprep-desc').value.trim()) el('vprep-desc').value = j.caption;
          S.prepModels = j.prep_models || [];
          applyPrepModels();
          var st = el('vprep-ocr-status');
          if (st) { st.innerHTML = '💾 brouillon « prêt » chargé — modifie si besoin, puis envoie'; st.style.color = '#8b9dff'; }
          preview();
        } else {
          if ((j.caption || '').trim() && !el('vprep-desc').value.trim()) { el('vprep-desc').value = j.caption; preview(); }
          analyze('');   // OCR auto uniquement s'il n'y a pas de brouillon
        }
      }).catch(function () { analyze(''); });
  }

  /* ── Marquer « prêt » : enregistre le brouillon SANS envoyer ── */
  function applyPrepModels() {
    var box = el('vprep-models'); if (!box) return;
    (S.prepModels || []).forEach(function (m) {
      S.selected[m] = true;
      var c = box.querySelector('.vprep-chip[data-m="' + m + '"]');
      if (c) { c.style.borderColor = '#22c55e'; c.style.background = 'rgba(34,197,94,.14)'; c.style.color = '#fff'; }
    });
  }
  function markCardReady(rid) {
    var card = document.querySelector('.veille-card[data-rid="' + rid + '"]');
    if (!card || card.getAttribute('data-sent') === '1') return;
    card.setAttribute('data-prepared', '1');
    var media = card.querySelector('.reel-media');
    if (media && !media.querySelector('.vl-ready-badge')) {
      var b = document.createElement('div');
      b.className = 'vl-ready-badge';
      b.style.cssText = 'position:absolute;top:11px;left:46px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;font-size:10px;font-weight:800;padding:4px 10px;border-radius:6px;z-index:6;letter-spacing:.3px;box-shadow:0 2px 10px rgba(59,130,246,.5)';
      b.textContent = '✓ PRÊT';
      media.appendChild(b);
    }
  }
  function savePrep() {
    var b = el('vprep-ready'); var orig = b.innerHTML;
    b.disabled = true; b.innerHTML = '⏳…';
    var fd = new FormData();
    fd.set('reel_id', S.rid);
    fd.set('overlay', (el('vprep-cap').value || '').trim());
    fd.set('caption', (el('vprep-desc').value || '').trim());
    fd.set('to_models', Object.keys(S.selected).join(','));
    fetch('/veille/prepare_save', { method: 'POST', body: fd }).then(function (r) { return r.json(); })
      .then(function (j) {
        b.disabled = false; b.innerHTML = orig;
        if (!j.ok) { toast('Erreur : ' + (j.error || '?'), 'error'); return; }
        toast('✓ Marqué prêt — brouillon enregistré');
        markCardReady(S.rid);
        close();
      })
      .catch(function (e) { b.disabled = false; b.innerHTML = orig; toast('Erreur : ' + e, 'error'); });
  }

  /* ── Analyse OCR ── */
  function analyze(second, full, end) {
    var st = el('vprep-ocr-status');
    var btns = [el('vprep-ocr'), el('vprep-ocr-sec'), el('vprep-ocr-full'), el('vprep-upto')];
    function lock(v) { btns.forEach(function (b) { if (b) b.disabled = v; }); if (!v) { var b3 = el('vprep-upto'); if (b3 && !el('vprep-player')) b3.disabled = true; } }
    st.textContent = full
      ? (end ? ('🧠 analyse du début jusqu\'à ' + fmtT(parseFloat(end)) + '…') : '🧠 analyse de toute la vidéo (8 images)… ~20-40 s')
      : '⏳ lecture de la vidéo…';
    st.style.color = '#8a91a8';
    lock(true);
    var fd = new FormData(); fd.set('reel_id', S.rid);
    if (full) fd.set('full', '1');
    if (end) fd.set('end', end);
    if (second !== '' && second != null) fd.set('second', second);
    var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var killed = false;
    var to = setTimeout(function () {
      killed = true; if (ctrl) ctrl.abort();
      lock(false);
      st.textContent = '⚠️ trop long (lien Instagram expiré ?) — réessaie, ou tape le texte à la main';
      st.style.color = '#f87171';
    }, full ? 160000 : 75000);
    fetch('/veille/analyze', { method: 'POST', body: fd, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        clearTimeout(to); if (killed) return;
        lock(false);
        if (!j.ok) { st.textContent = '⚠️ ' + (j.error || 'échec'); st.style.color = '#f87171'; return; }
        if (j.text) {
          el('vprep-cap').value = j.text;
          var eng = j.engine === 'gemini' ? 'Gemini ✨' : (j.engine === 'ia' ? 'Claude ✨' : 'gratuit/Tesseract');
          if (j.engine === 'tesseract' && j.gemini_err) {
            st.innerHTML = '⚠️ IA indisponible (' + esc(String(j.gemini_err).slice(0, 50)) + '…) — lu en secours, corrige';
            st.style.color = '#facc15';
          } else {
            st.innerHTML = '✅ lu (' + eng + (j.full ? (end ? ' · jusqu\'à ' + fmtT(parseFloat(end)) : ' · toute la vidéo 🧠') : '') + ') — vérifie/corrige';
            st.style.color = '#4ade80';
          }
        } else if (j.gemini_key && j.gemini_err) {
          st.innerHTML = '⚠️ IA a échoué : ' + esc(j.gemini_err);
          st.style.color = '#f87171';
        } else {
          st.textContent = 'ℹ️ aucun texte détecté — regarde la vidéo et réanalyse (autre moment)';
          st.style.color = '#facc15';
        }
        if (j.video_url) setPlayer(j.video_url);
        var fw = el('vprep-frame-wrap');
        if (fw && j.frame) {
          fw.innerHTML = '<div style="' + SECTION + '">Image analysée</div>' +
            '<img src="data:image/jpeg;base64,' + j.frame + '" style="width:100%;border-radius:10px;border:1px solid #262b3a">';
        }
        if (j.description && !el('vprep-desc').value.trim()) el('vprep-desc').value = j.description;
        preview();
      })
      .catch(function (e) {
        clearTimeout(to); if (killed) return;
        lock(false);
        st.textContent = '⚠️ ' + e; st.style.color = '#f87171';
      });
  }

  /* ── Modèles ── */
  function loadModels() {
    fetch('/veille/models').then(function (r) { return r.json(); }).then(function (j) {
      var box = el('vprep-models'); if (!box) return;
      if (!j.ok || !(j.models || []).length) {
        box.innerHTML = '<span style="color:#5a6178">Aucune modèle branchée au routeur Telegram (/setmodel dans son groupe).</span>';
        return;
      }
      S.models = j.models;
      var pre = (typeof veilleModelsSelected === 'function') ? veilleModelsSelected() : [];
      var prep = S.prepModels || [];   // modèles du brouillon « prêt »
      box.innerHTML = j.models.map(function (m) {
        var on = pre.indexOf(m) !== -1 || prep.indexOf(m) !== -1; if (on) S.selected[m] = true;
        return '<button class="vp-chip vprep-chip" data-m="' + esc(m) + '" style="padding:7px 14px;border-radius:999px;border:1px solid ' +
          (on ? '#22c55e' : '#262b3a') + ';background:' + (on ? 'rgba(34,197,94,.14)' : '#12151f') +
          ';color:' + (on ? '#fff' : '#9aa0b4') + ';font-size:12px;font-weight:700;cursor:pointer">' + esc(m) + '</button>';
      }).join('');
      Array.prototype.forEach.call(box.querySelectorAll('.vprep-chip'), function (c) {
        c.addEventListener('click', function () {
          var m = c.dataset.m;
          if (S.selected[m]) { delete S.selected[m]; c.style.borderColor = '#262b3a'; c.style.background = '#12151f'; c.style.color = '#9aa0b4'; }
          else { S.selected[m] = true; c.style.borderColor = '#22c55e'; c.style.background = 'rgba(34,197,94,.14)'; c.style.color = '#fff'; }
        });
      });
    }).catch(function () { var b = el('vprep-models'); if (b) b.textContent = 'Erreur chargement modèles'; });
  }

  /* ── Aperçu : une bulle par message (vidéo, caption, description) ── */
  var BUBBLE = 'background:linear-gradient(135deg,#182533,#141d29);border:1px solid #24384d;border-radius:14px 14px 14px 4px;padding:10px 14px;font-size:12.5px;color:#dbe4ee;white-space:pre-wrap;line-height:1.55;max-width:95%';
  function bubble(txt, dim) {
    return '<div style="' + BUBBLE + (dim ? ';color:#7d8aa0;font-style:italic' : '') + '">' + esc(txt) + '</div>';
  }
  function preview() {
    var cap = ((el('vprep-cap') || {}).value || '').trim();
    var desc = ((el('vprep-desc') || {}).value || '').trim();
    var p = el('vprep-preview');
    if (!p) return;
    var h = bubble('🎬 [la vidéo]', true);
    if (cap) h += bubble(cap);
    if (desc) h += bubble(desc);
    if (!cap && !desc) h += bubble('(aucun texte — la vidéo partira seule)', true);
    p.innerHTML = h;
  }

  /* ── Envoi ── */
  function send() {
    var models = Object.keys(S.selected);
    if (!models.length) { toast('Coche au moins une modèle', 'error'); return; }
    var b = el('vprep-send'); var orig = b.innerHTML;
    b.disabled = true; b.innerHTML = '⏳ envoi…';
    var fd = new FormData();
    fd.set('reel_id', S.rid);
    fd.set('overlay', (el('vprep-cap').value || '').trim());
    fd.set('caption', (el('vprep-desc').value || '').trim());
    fd.set('to_models', models.join(','));
    fetch('/veille/send', { method: 'POST', body: fd }).then(function (r) { return r.json(); })
      .then(function (j) {
        b.disabled = false; b.innerHTML = orig;
        if (!j.ok) { toast('Erreur : ' + (j.error || '?'), 'error'); return; }
        var sent = (j.models_sent || []).length;
        var errs = (j.models_err || []);
        if (sent) toast('✓ Veille préparée envoyée à ' + sent + ' modèle(s)');
        if (errs.length) toast('⚠️ ' + errs.join(' · '), 'error');
        var card = document.querySelector('.veille-card[data-rid="' + S.rid + '"]');
        if (card) {
          var media = card.querySelector('.reel-media');
          if (media) {
            var rb = media.querySelector('.vl-ready-badge'); if (rb) rb.remove();  // PRÊT -> ENVOYÉ
            if (card.getAttribute('data-sent') !== '1') {
              var r2 = document.createElement('div'); r2.style.cssText = 'position:absolute;top:11px;left:46px;background:#22c55e;color:#fff;font-size:10px;font-weight:800;padding:4px 10px;border-radius:6px;z-index:6'; r2.textContent = '✓ ENVOYÉ'; media.appendChild(r2);
            }
          }
          card.setAttribute('data-prepared', '0');
          card.setAttribute('data-sent', '1');
        }
        if (sent) close();
      })
      .catch(function (e) { b.disabled = false; b.innerHTML = orig; toast('Erreur : ' + e, 'error'); });
  }

  window.veillePrepare = open;
})();
