/* ============================================================================
   Veille — « Préparer la veille » : lire le texte incrusté (OCR gratuit),
   choisir la seconde, valider la caption + la description, aperçu Telegram,
   puis envoyer aux modèles. Fichier séparé (pas d'échappement dans UPLOAD_HTML).
   ========================================================================== */
(function () {
  'use strict';

  var S = { rid: null, models: [], selected: {} };

  function esc(x) {
    return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function el(id) { return document.getElementById(id); }
  function toast(m, t) { if (typeof showToast === 'function') showToast(m, t || 'success'); }

  var INP = 'width:100%;padding:10px 12px;background:#0d0d16;border:1px solid #2c2c3d;color:#fff;border-radius:9px;font-size:13px;font-family:inherit;box-sizing:border-box';

  function close() { var m = el('vprep-modal'); if (m) m.remove(); }

  function open(rid) {
    S.rid = rid; S.selected = {};
    close();
    // description déjà connue côté carte (data-caption) -> pré-remplissage instantané
    var card = document.querySelector('.veille-card[data-rid="' + rid + '"]');
    var knownDesc = '';
    if (card && card.dataset.caption && card.dataset.caption.indexOf('Pas de caption') < 0) knownDesc = card.dataset.caption;

    var ov = document.createElement('div');
    ov.id = 'vprep-modal';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.74);z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px)';
    ov.innerHTML =
      '<div style="background:#12121c;border:1px solid #2c2c3d;border-radius:16px;padding:22px;width:100%;max-width:560px;max-height:94vh;overflow-y:auto;box-shadow:0 30px 80px rgba(0,0,0,.6)">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">' +
      '<div style="font-size:17px;font-weight:800">🎯 Préparer la veille</div>' +
      '<button id="vprep-x" style="background:#1d1d28;border:0;color:#999;width:30px;height:30px;border-radius:8px;cursor:pointer">✕</button></div>' +

      // --- OCR ---
      '<div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px">1 · Texte incrusté sur la vidéo</div>' +
      '<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">' +
      '<button id="vprep-ocr" style="padding:9px 15px;background:linear-gradient(135deg,#3b82f6,#2563eb);border:0;color:#fff;border-radius:9px;font-size:12.5px;font-weight:700;cursor:pointer">🔍 Analyser le texte</button>' +
      '<span style="color:#77778a;font-size:12px">ou à la seconde</span>' +
      '<input id="vprep-sec" type="number" min="0" step="0.5" placeholder="ex: 1.5" style="' + INP + ';width:90px;padding:8px 10px">' +
      '<button id="vprep-ocr-sec" style="padding:8px 12px;background:#1d1d28;border:1px solid #2c2c3d;color:#ddd;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer">Analyser à cette seconde</button>' +
      '<span id="vprep-ocr-status" style="color:#77778a;font-size:11.5px"></span>' +
      '</div>' +
      '<textarea id="vprep-cap" placeholder="Le texte lu sur la vidéo apparaîtra ici — corrige-le si besoin." style="' + INP + ';min-height:60px;resize:vertical;margin-bottom:16px"></textarea>' +

      // --- Description ---
      '<div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px">2 · Description (postée sous la vidéo)</div>' +
      '<textarea id="vprep-desc" placeholder="La description qui accompagne la vidéo." style="' + INP + ';min-height:70px;resize:vertical;margin-bottom:16px">' + esc(knownDesc) + '</textarea>' +

      // --- Modèles ---
      '<div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px">3 · Envoyer aux modèles</div>' +
      '<div id="vprep-models" style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:16px;min-height:34px;color:#66667a;font-size:12px">Chargement…</div>' +

      // --- Aperçu ---
      '<div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px">Aperçu Telegram</div>' +
      '<div id="vprep-preview" style="background:#0e0e16;border:1px solid #26263a;border-radius:10px;padding:12px 14px;font-size:12.5px;color:#c8c8d8;white-space:pre-wrap;line-height:1.5;margin-bottom:18px;min-height:40px"></div>' +

      '<div style="display:flex;gap:10px;justify-content:flex-end">' +
      '<button id="vprep-cancel" style="padding:10px 18px;background:#1d1d28;border:1px solid #2c2c3d;color:#ddd;border-radius:10px;font-size:12.5px;font-weight:700;cursor:pointer">Annuler</button>' +
      '<button id="vprep-send" style="padding:10px 22px;background:linear-gradient(135deg,#22c55e,#16a34a);border:0;color:#fff;border-radius:10px;font-weight:800;cursor:pointer">📤 Envoyer la veille</button>' +
      '</div></div>';
    ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
    document.body.appendChild(ov);

    el('vprep-x').addEventListener('click', close);
    el('vprep-cancel').addEventListener('click', close);
    el('vprep-ocr').addEventListener('click', function () { analyze(''); });
    el('vprep-ocr-sec').addEventListener('click', function () { analyze(el('vprep-sec').value); });
    el('vprep-cap').addEventListener('input', preview);
    el('vprep-desc').addEventListener('input', preview);
    el('vprep-send').addEventListener('click', send);

    loadModels();
    preview();
    analyze('');   // OCR auto au démarrage (4 frames, meilleur résultat)
  }

  function analyze(second) {
    var st = el('vprep-ocr-status'); var b1 = el('vprep-ocr'); var b2 = el('vprep-ocr-sec');
    st.textContent = '⏳ téléchargement + lecture de la vidéo… (jusqu\'à ~30 s la 1re fois)';
    st.style.color = '#77778a';
    b1.disabled = b2.disabled = true;
    var fd = new FormData(); fd.set('reel_id', S.rid);
    if (second !== '' && second != null) fd.set('second', second);
    // timeout dur : si le serveur rame (lien IG à re-résoudre), on ne reste pas bloqué
    var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var killed = false;
    var to = setTimeout(function () {
      killed = true; if (ctrl) ctrl.abort();
      b1.disabled = b2.disabled = false;
      st.textContent = '⚠️ trop long (lien Instagram expiré ?) — réessaie, ou tape le texte à la main';
      st.style.color = '#f87171';
    }, 75000);
    fetch('/veille/analyze', { method: 'POST', body: fd, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        clearTimeout(to); if (killed) return;
        b1.disabled = b2.disabled = false;
        if (!j.ok) { st.textContent = '⚠️ ' + (j.error || 'échec'); st.style.color = '#f87171'; return; }
        if (j.text) {
          el('vprep-cap').value = j.text;
          st.innerHTML = '✅ lu (' + (j.engine === 'ia' ? 'IA' : 'gratuit') + ') — vérifie/corrige';
          st.style.color = '#4ade80';
        } else {
          st.textContent = 'ℹ️ aucun texte net détecté — tape-le à la main ou change de seconde';
          st.style.color = '#facc15';
        }
        if (j.description && !el('vprep-desc').value.trim()) el('vprep-desc').value = j.description;
        preview();
      })
      .catch(function (e) {
        clearTimeout(to); if (killed) return;
        b1.disabled = b2.disabled = false;
        st.textContent = '⚠️ ' + e; st.style.color = '#f87171';
      });
  }

  function loadModels() {
    fetch('/veille/models').then(function (r) { return r.json(); }).then(function (j) {
      var box = el('vprep-models'); if (!box) return;
      if (!j.ok || !(j.models || []).length) {
        box.innerHTML = '<span style="color:#77778a">Aucune modèle branchée au routeur Telegram (/setmodel dans son groupe).</span>';
        return;
      }
      S.models = j.models;
      // reprend la sélection globale des chips si elle existe
      var pre = (typeof veilleModelsSelected === 'function') ? veilleModelsSelected() : [];
      box.innerHTML = j.models.map(function (m) {
        var on = pre.indexOf(m) !== -1; if (on) S.selected[m] = true;
        return '<button class="vprep-chip" data-m="' + esc(m) + '" style="padding:7px 13px;border-radius:999px;border:1px solid ' +
          (on ? '#22c55e' : '#2a2a35') + ';background:' + (on ? 'rgba(34,197,94,.16)' : 'transparent') +
          ';color:' + (on ? '#fff' : '#9a9aa8') + ';font-size:12px;font-weight:700;cursor:pointer">' + esc(m) + '</button>';
      }).join('');
      Array.prototype.forEach.call(box.querySelectorAll('.vprep-chip'), function (c) {
        c.addEventListener('click', function () {
          var m = c.dataset.m;
          if (S.selected[m]) { delete S.selected[m]; c.style.borderColor = '#2a2a35'; c.style.background = 'transparent'; c.style.color = '#9a9aa8'; }
          else { S.selected[m] = true; c.style.borderColor = '#22c55e'; c.style.background = 'rgba(34,197,94,.16)'; c.style.color = '#fff'; }
        });
      });
    }).catch(function () { var b = el('vprep-models'); if (b) b.textContent = 'Erreur chargement modèles'; });
  }

  function preview() {
    var cap = (el('vprep-cap') || {}).value || '';
    var desc = (el('vprep-desc') || {}).value || '';
    var parts = [];
    if (cap.trim()) parts.push('✍️ « ' + cap.trim() + ' »');
    if (desc.trim()) parts.push(desc.trim());
    var p = el('vprep-preview');
    if (p) p.textContent = parts.length ? parts.join('\n\n') : '(vide — la vidéo partira sans texte)';
  }

  function selectedModels() { return Object.keys(S.selected); }

  function send() {
    var models = selectedModels();
    if (!models.length) { toast('Coche au moins une modèle', 'error'); return; }
    var b = el('vprep-send'); var orig = b.innerHTML;
    b.disabled = true; b.innerHTML = '⏳ envoi…';
    var fd = new FormData();
    fd.set('reel_id', S.rid);
    fd.set('overlay', (el('vprep-cap').value || '').trim());   // caption incrustée VALIDÉE
    fd.set('caption', (el('vprep-desc').value || '').trim());  // description
    fd.set('to_models', models.join(','));
    fetch('/veille/send', { method: 'POST', body: fd }).then(function (r) { return r.json(); })
      .then(function (j) {
        b.disabled = false; b.innerHTML = orig;
        if (!j.ok) { toast('Erreur : ' + (j.error || '?'), 'error'); return; }
        var sent = (j.models_sent || []).length;
        var errs = (j.models_err || []);
        if (sent) toast('✓ Veille préparée envoyée à ' + sent + ' modèle(s)');
        if (errs.length) toast('⚠️ ' + errs.join(' · '), 'error');
        // marque la carte envoyée
        var card = document.querySelector('.veille-card[data-rid="' + S.rid + '"]');
        if (card && card.getAttribute('data-sent') !== '1') {
          var media = card.querySelector('.reel-media');
          if (media) { var r2 = document.createElement('div'); r2.style.cssText = 'position:absolute;top:11px;left:46px;background:#22c55e;color:#fff;font-size:10px;font-weight:800;padding:4px 10px;border-radius:6px;z-index:6'; r2.textContent = '✓ ENVOYÉ'; media.appendChild(r2); }
          card.setAttribute('data-sent', '1');
        }
        if (sent) close();
      })
      .catch(function (e) { b.disabled = false; b.innerHTML = orig; toast('Erreur : ' + e, 'error'); });
  }

  window.veillePrepare = open;
})();
