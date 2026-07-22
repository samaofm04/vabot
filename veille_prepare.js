/* ============================================================================
   Veille — « Préparer la veille » (v3 anti-course)
   Layout 2 colonnes : lecteur vidéo immédiat (route /veille/reelinfo) + panneau
   d'analyse. OCR rapide / toute la vidéo / jusqu'au curseur (précision 1/100s) /
   à la seconde. Caption + description éditables, chips modèles, aperçu Telegram.

   v3 : jeton de génération S.gen — CHAQUE réponse asynchrone (reelinfo, analyze,
   send, models) vérifie que le modal n'a pas été fermé/réouvert entre-temps,
   sinon elle est jetée (fini le texte du reel A injecté dans le reel B).
   close() aborte l'analyse en vol. Envoyer/Marquer prêt verrouillés pendant la
   lecture. Le texte tapé par l'utilisateur n'est plus écrasé par l'OCR auto.
   ========================================================================== */
(function () {
  'use strict';

  var S = { rid: null, models: [], selected: {}, raf: 0, gen: 0, busyN: 0,
            capDirty: false, descDirty: false, analyzed: false,
            inflight: null, prepModels: [] };

  function esc(x) {
    return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function el(id) { return document.getElementById(id); }
  function toast(m, t) { if (typeof showToast === 'function') showToast(m, t || 'success'); }
  function fmtT(sec) {
    // en centisecondes pour éviter « 0:60.00 » autour des minutes pleines
    var cs = Math.round((sec || 0) * 100);
    var m = Math.floor(cs / 6000);
    var s = (cs - m * 6000) / 100;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
  }

  var INP = 'width:100%;padding:10px 12px;background:#0b0e16;border:1px solid #262b3a;color:#e8eaf2;border-radius:10px;font-size:13px;font-family:inherit;box-sizing:border-box;outline:none;transition:border-color .15s';
  var SECTION = 'font-size:10px;color:#8a91a8;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px';
  var BTN_GHOST = 'padding:9px 14px;background:#161a26;border:1px solid #262b3a;color:#c9cede;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer;transition:all .15s';

  function close() {
    S.gen++;                                    // invalide toutes les réponses en vol
    if (S.inflight) { try { S.inflight.abort(); } catch (e) { } S.inflight = null; }
    S.busyN = 0;
    if (S.raf) { cancelAnimationFrame(S.raf); S.raf = 0; }
    var m = el('vprep-modal');
    if (m) m.remove();
  }

  /* Envoyer / Marquer prêt : verrouillés tant qu'une lecture (reelinfo ou OCR)
     est en vol — sinon un clic trop rapide envoyait des champs encore vides. */
  function updateActions() {
    var busy = S.busyN > 0;
    ['vprep-send', 'vprep-ready'].forEach(function (id) {
      var b = el(id); if (!b) return;
      if (b.dataset.t0 == null) b.dataset.t0 = b.title || '';
      b.disabled = busy;
      b.style.opacity = busy ? '.55' : '1';
      b.title = busy ? 'Attends la fin de la lecture de la vidéo…' : b.dataset.t0;
    });
  }
  function beginBusy() { S.busyN++; updateActions(); }
  function endBusy(g) { if (g !== S.gen) return; S.busyN = Math.max(0, S.busyN - 1); updateActions(); }

  /* Message dans le cadre vidéo quand il n'y a pas (encore) de lecteur —
     avant, « ⏳ chargement du lecteur… » restait affiché pour l'éternité. */
  function playerMsg(msg) {
    if (el('vprep-player')) return;
    var vw = el('vprep-video-wrap');
    if (vw) vw.innerHTML = '<div style="height:170px;border:1px dashed #262b3a;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#8a91a8;font-size:11px;text-align:center;padding:0 12px;line-height:1.5">' + esc(msg) + '</div>';
  }

  function open(rid) {
    close();
    S.rid = rid; S.selected = {}; S.capDirty = false; S.descDirty = false;
    S.analyzed = false; S.prepModels = [];
    var card = document.querySelector('.veille-card[data-rid="' + rid + '"]');
    var knownDesc = '';
    if (card && card.dataset.caption && card.dataset.caption.indexOf('Pas de caption') < 0) knownDesc = card.dataset.caption;

    var ov = document.createElement('div');
    ov.id = 'vprep-modal';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(2,4,10,.78);z-index:10000;display:flex;align-items:center;justify-content:center;padding:18px;backdrop-filter:blur(6px)';
    ov.innerHTML =
      '<div class="vp-card" style="background:#0f1117;border:1px solid #232838;border-radius:18px;width:100%;max-width:900px;max-height:94vh;display:flex;flex-direction:column;box-shadow:0 40px 100px rgba(0,0,0,.7);overflow:hidden;animation:vprepIn .25s cubic-bezier(.16,1,.3,1)">' +
      '<style>@keyframes vprepIn{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}' +
      '.vp-chip{transition:all .12s}.vp-chip:hover{border-color:#3b82f6!important}' +
      '#vprep-modal textarea:focus,#vprep-modal input:focus{border-color:#3b82f6}' +
      '.vp-abtn:hover{filter:brightness(1.12)}.vp-abtn:disabled{opacity:.5;cursor:wait}' +
      '@media(max-width:820px){#vprep-modal{padding:0!important}' +
      '.vp-card{max-width:100%!important;width:100%!important;height:100%;max-height:100%!important;border-radius:0!important}' +
      '.vp-body{flex-direction:column!important;overflow-y:auto!important}' +
      '.vp-colL{width:100%!important;border-right:0!important;border-bottom:1px solid #1d2230}}</style>' +

      // ── Header ──
      '<div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid #1d2230;flex-shrink:0">' +
      '<div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:17px">🎯</div>' +
      '<div style="flex:1"><div style="font-size:15.5px;font-weight:800;color:#fff">Préparer la veille</div>' +
      '<div style="font-size:11.5px;color:#8a91a8">Lis le texte incrusté, valide, puis envoie aux modèles</div></div>' +
      '<button id="vprep-x" style="background:#161a26;border:1px solid #262b3a;color:#8a91a8;width:32px;height:32px;border-radius:9px;cursor:pointer;font-size:13px">✕</button>' +
      '</div>' +

      // ── Corps 2 colonnes ──
      '<div class="vp-body" style="display:flex;gap:0;flex:1;min-height:0;overflow:hidden">' +

      // Colonne gauche : vidéo
      '<div class="vp-colL" style="width:300px;flex-shrink:0;padding:16px;border-right:1px solid #1d2230;overflow-y:auto;background:#0c0e15">' +
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
      '<textarea id="vprep-desc" placeholder="La description qui accompagne la vidéo — laisse VIDE pour que la vidéo parte sans description." style="' + INP + ';min-height:64px;resize:vertical;margin-bottom:18px;line-height:1.5">' + esc(knownDesc) + '</textarea>' +

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
    ov.addEventListener('click', function (e) {
      if (e.target !== ov) return;
      // clic accidentel sur le fond : si du texte a été tapé/corrigé, on demande
      // avant de tout jeter (une ré-analyse coûte 20-40 s)
      if (S.capDirty && (el('vprep-cap') || {}).value && !window.confirm('Fermer ? Le texte corrigé ne sera pas enregistré.')) return;
      close();
    });
    document.body.appendChild(ov);

    el('vprep-x').addEventListener('click', close);
    el('vprep-cancel').addEventListener('click', close);
    el('vprep-ocr').addEventListener('click', function () { analyze(''); });
    el('vprep-ocr-full').addEventListener('click', function () { analyze('', true); });
    el('vprep-ocr-sec').addEventListener('click', function () { analyze(el('vprep-sec').value); });
    // capDirty : le texte tapé/corrigé par l'utilisateur ne sera PAS écrasé par l'OCR auto
    el('vprep-cap').addEventListener('input', function () { S.capDirty = true; preview(); });
    // input couvre aussi le passage à vide : effacer la description pose le flag
    el('vprep-desc').addEventListener('input', function () { S.descDirty = true; preview(); });
    el('vprep-send').addEventListener('click', send);
    el('vprep-ready').addEventListener('click', savePrep);
    el('vprep-upto').addEventListener('click', function () {
      var pl = el('vprep-player');
      var ct = (pl && pl.currentTime) || 0;
      if (ct < 0.5) { toast('Place d\'abord le curseur de la vidéo au moment voulu', 'error'); return; }
      if (pl && !pl.paused) pl.pause();
      analyze('', true, ct.toFixed(2));
    });

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
    var g = S.gen;
    beginBusy();
    fetch('/veille/reelinfo?reel_id=' + encodeURIComponent(S.rid))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (g !== S.gen) return;              // modal fermé/changé de reel entre-temps
        endBusy(g);
        if (!j.ok) { if (!S.inflight && !S.analyzed) analyze('', false, null, true); return; }
        if (j.video_url) setPlayer(j.video_url);
        // parité serveur (web_upload.py /veille/send) : un brouillon « prêt » fait
        // foi même entièrement vide (desc volontairement vidée) -> pas d'OCR auto
        var draft = !!j.prepared;
        if (draft) {
          // brouillon « PRÊT » : on recharge tel quel — PAS d'OCR auto, sinon on
          // écraserait la caption déjà validée.
          if ((j.prep_overlay || '').trim()) el('vprep-cap').value = j.prep_overlay;
          if ((j.prep_desc || '').trim()) el('vprep-desc').value = j.prep_desc;
          else if (j.prepared) el('vprep-desc').value = '';   // desc vidée volontairement dans le brouillon
          S.prepModels = j.prep_models || [];
          applyPrepModels();
          var st = el('vprep-ocr-status');
          if (st) { st.innerHTML = '💾 brouillon « prêt » chargé — modifie si besoin, puis envoie'; st.style.color = '#8b9dff'; }
          if (!j.video_url) playerMsg('🚫 Pas de vidéo en cache pour ce reel — lance 🔍 Analyser pour la récupérer.');
          preview();
        } else {
          if ((j.caption || '').trim() && !S.descDirty && !el('vprep-desc').value.trim()) { el('vprep-desc').value = j.caption; preview(); }
          // OCR auto uniquement s'il n'y a pas de brouillon ET si aucune analyse
          // n'a déjà été lancée depuis l'ouverture (en vol OU déjà terminée)
          if (!S.inflight && !S.analyzed) analyze('', false, null, true);
        }
      }).catch(function () { if (g !== S.gen) return; endBusy(g); if (!S.inflight && !S.analyzed) analyze('', false, null, true); });
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
    var cb = card.querySelector('.vl-rdy-cb'); if (cb) cb.checked = true;
    // réutilise le helper de la page (toggle vert + contour vert + badge)
    if (typeof window.veilleReadyVisual === 'function') { window.veilleReadyVisual(card, true); return; }
    card.setAttribute('data-prepared', '1');
    var media = card.querySelector('.reel-media');
    if (media && !media.querySelector('.vl-ready-badge')) {
      var b = document.createElement('div');
      b.className = 'vl-ready-badge';
      b.style.cssText = 'position:absolute;top:11px;left:46px;background:#22c55e;color:#fff;font-size:10px;font-weight:800;padding:4px 10px;border-radius:6px;z-index:6;letter-spacing:.3px;box-shadow:0 2px 10px rgba(34,197,94,.5)';
      b.textContent = '✓ PRÊT';
      media.appendChild(b);
    }
  }
  function savePrep() {
    var g = S.gen, rid = S.rid;
    var b = el('vprep-ready'); if (!b || b.disabled) return;
    if (S.busyN > 0) { toast('Attends la fin de la lecture de la vidéo…', 'error'); return; }
    var orig = '💾 Marquer prêt';
    b.innerHTML = '⏳…'; beginBusy();   // busyN verrouille aussi Envoyer pendant la sauvegarde
    var fd = new FormData();
    fd.set('reel_id', rid);
    fd.set('overlay', (el('vprep-cap').value || '').trim());
    fd.set('caption', (el('vprep-desc').value || '').trim());
    fd.set('to_models', Object.keys(S.selected).join(','));
    fetch('/veille/prepare_save', { method: 'POST', body: fd }).then(function (r) { return r.json(); })
      .then(function (j) {
        endBusy(g); if (g === S.gen && el('vprep-ready')) el('vprep-ready').innerHTML = orig;
        if (!j.ok) { toast('Erreur : ' + (j.error || '?'), 'error'); return; }
        toast('✓ Marqué prêt — brouillon enregistré');
        markCardReady(rid);
        if (g === S.gen) close();
        // compteurs « prêts » du header re-rendus depuis l'état serveur
        if (typeof window.refreshVeilleSection === 'function') window.refreshVeilleSection();
      })
      .catch(function (e) { endBusy(g); if (g === S.gen && el('vprep-ready')) el('vprep-ready').innerHTML = orig; toast('Erreur : ' + e, 'error'); });
  }

  /* ── Analyse OCR ── */
  function analyze(second, full, end, auto) {
    var g = S.gen, rid = S.rid;
    // UNE seule analyse à la fois : la nouvelle annule la précédente (avant, la
    // dernière à répondre écrasait le résultat de l'autre + statut incohérent)
    if (S.inflight) { try { S.inflight.abort(); } catch (e) { } S.inflight = null; }
    var st = el('vprep-ocr-status');
    if (!st) return;
    S.analyzed = true;   // une analyse a été lancée pour ce modal -> bloque l'OCR auto tardif de loadInfo
    var btns = [el('vprep-ocr'), el('vprep-ocr-sec'), el('vprep-ocr-full'), el('vprep-upto')];
    function lock(v) {
      if (g !== S.gen) return;
      btns.forEach(function (b) { if (b) b.disabled = v; });
      if (!v) { var b3 = el('vprep-upto'); if (b3 && !el('vprep-player')) b3.disabled = true; }
    }
    st.textContent = full
      ? (end ? ('🧠 analyse du début jusqu\'à ' + fmtT(parseFloat(end)) + '…') : '🧠 analyse de toute la vidéo (8 images)… ~20-40 s')
      : '⏳ lecture de la vidéo…';
    st.style.color = '#8a91a8';
    playerMsg('⏳ récupération de la vidéo…');
    lock(true); beginBusy();
    var fd = new FormData(); fd.set('reel_id', rid);
    if (full) fd.set('full', '1');
    if (end) fd.set('end', end);
    if (second !== '' && second != null) fd.set('second', second);
    var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    S.inflight = ctrl;
    var killed = false;
    var settled = false;
    function settle() {
      if (settled) return; settled = true;
      // seule l'analyse COURANTE déverrouille les boutons — une analyse supersédée
      // (abortée par une plus récente) ne doit pas dégeler ce que #2 a verrouillé
      if (S.inflight === ctrl) { S.inflight = null; lock(false); }
      endBusy(g);   // toujours : équilibre le beginBusy de CETTE analyse
    }
    var to = setTimeout(function () {
      killed = true; if (ctrl) ctrl.abort();
      settle();
      if (g !== S.gen) return;
      var s2 = el('vprep-ocr-status');
      if (s2) {
        s2.textContent = '⚠️ trop long — réessaie, ou tape le texte à la main';
        s2.style.color = '#f87171';
      }
    }, full ? 160000 : 75000);
    fetch('/veille/analyze', { method: 'POST', body: fd, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        clearTimeout(to); if (killed) return;
        var mine = (S.inflight === ctrl);     // suis-je encore l'analyse courante ?
        settle();
        if (g !== S.gen || !mine) return;     // modal fermé OU supersédée par une analyse plus récente -> jetée
        var s2 = el('vprep-ocr-status'); if (!s2) return;
        if (!j.ok) {
          s2.textContent = '⚠️ ' + (j.error || 'échec'); s2.style.color = '#f87171';
          playerMsg('🚫 Vidéo indisponible — tape le texte à la main (« Analyser jusqu\'ici » désactivé).');
          return;
        }
        if (j.text) {
          var capEl = el('vprep-cap');
          // texte tapé/corrigé par l'utilisateur : l'OCR AUTO ne l'écrase pas.
          // Un clic explicite sur Analyser remplace toujours.
          var keepUser = !!(auto && S.capDirty && capEl && capEl.value.trim());
          if (!keepUser && capEl) { capEl.value = j.text; S.capDirty = false; }
          var eng = j.engine === 'gemini' ? 'Gemini ✨' : (j.engine === 'ia' ? 'Claude ✨' : 'gratuit/Tesseract');
          if (keepUser) {
            s2.innerHTML = '✅ lu (' + eng + ') — ton texte tapé est conservé (clique 🔍 Analyser pour le remplacer)';
            s2.style.color = '#4ade80';
          } else if (j.engine === 'tesseract' && j.gemini_err) {
            s2.innerHTML = '⚠️ IA indisponible (' + esc(String(j.gemini_err).slice(0, 50)) + '…) — lu en secours, corrige';
            s2.style.color = '#facc15';
          } else {
            s2.innerHTML = '✅ lu (' + eng + (j.full ? (end ? ' · jusqu\'à ' + fmtT(parseFloat(end)) : ' · toute la vidéo 🧠') : '') + ') — vérifie/corrige';
            s2.style.color = '#4ade80';
          }
        } else if (j.gemini_key && j.gemini_err) {
          s2.innerHTML = '⚠️ IA a échoué : ' + esc(j.gemini_err);
          s2.style.color = '#f87171';
        } else {
          s2.textContent = 'ℹ️ aucun texte détecté — regarde la vidéo et réanalyse (autre moment)';
          s2.style.color = '#facc15';
        }
        // lecteur : on ne REMPLACE pas une vidéo qui joue déjà (ça remettait le
        // curseur à zéro pendant qu'on calait « Analyser jusqu'ici ») — swap
        // uniquement si pas de lecteur ou si sa source est morte.
        if (j.video_url) {
          var pl0 = el('vprep-player');
          if (!pl0 || pl0.error) setPlayer(j.video_url);
        } else {
          playerMsg('🚫 Vidéo non récupérable — tape le texte à la main.');
        }
        var fw = el('vprep-frame-wrap');
        if (fw && j.frame) {
          fw.innerHTML = '<div style="' + SECTION + '">Image analysée</div>' +
            '<img src="data:image/jpeg;base64,' + j.frame + '" style="width:100%;border-radius:10px;border:1px solid #262b3a">';
        }
        // description : ne PAS re-remplir un champ que l'utilisateur a touché/vidé
        if (j.description && !S.descDirty && !el('vprep-desc').value.trim()) el('vprep-desc').value = j.description;
        preview();
      })
      .catch(function (e) {
        clearTimeout(to); if (killed) return;
        var mine = (S.inflight === ctrl);
        settle();
        if (g !== S.gen || !mine) return;     // abort par l'analyse suivante -> silencieux (pas de rouge)
        var s2 = el('vprep-ocr-status');
        if (s2) { s2.textContent = '⚠️ ' + e; s2.style.color = '#f87171'; }
      });
  }

  /* ── Modèles ── */
  function loadModels() {
    var g = S.gen;
    fetch('/veille/models').then(function (r) { return r.json(); }).then(function (j) {
      if (g !== S.gen) return;
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
    }).catch(function () { if (g !== S.gen) return; var b = el('vprep-models'); if (b) b.textContent = 'Erreur chargement modèles'; });
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
    var h = bubble('🎬 [la vidéo] — le lien Instagram part en légende dessous', true);
    if (cap) h += bubble(cap);
    if (desc) h += bubble(desc);
    if (!cap && !desc) h += bubble('(aucun autre texte — vidéo + lien seulement)', true);
    // Telegram coupe à 4000 caractères par message : on prévient AVANT l'envoi
    if (cap.length > 4000 || desc.length > 4000) {
      h += '<div style="font-size:11px;color:#facc15;padding:2px 4px">⚠️ texte &gt; 4000 caractères — Telegram le coupera</div>';
    }
    p.innerHTML = h;
  }

  /* ── Envoi ── */
  function send() {
    var models = Object.keys(S.selected).filter(function (m) { return !S.models.length || S.models.indexOf(m) !== -1; });
    // 0 modèle = autorisé (envoi dans le canal Veille seulement), mais on confirme
    if (!models.length && !window.confirm('Aucune modèle cochée — envoyer uniquement dans le canal Veille ?')) return;
    if (S.busyN > 0) { toast('Attends la fin de la lecture de la vidéo…', 'error'); return; }
    var g = S.gen, rid = S.rid;
    var b = el('vprep-send'); if (!b || b.disabled) return;
    // état retry porté par la CARTE (survit à la fermeture du modal), pas juste le bouton
    var card0 = document.querySelector('.veille-card[data-rid="' + rid + '"]');
    var isRetry = b.dataset.retry === '1' || (card0 && card0.dataset.retryModels === '1');
    var orig = '📤 Envoyer la veille';
    b.innerHTML = '⏳ envoi…'; beginBusy();   // busyN : une analyse qui finit ne pourra pas réactiver Envoyer
    var fd = new FormData();
    fd.set('reel_id', rid);
    fd.set('overlay', (el('vprep-cap').value || '').trim());
    fd.set('caption', (el('vprep-desc').value || '').trim());
    fd.set('desc_set', '1');                   // champ EXPLICITE : vide = pas de description
    fd.set('to_models', models.join(','));
    fd.set('models_set', '1');                 // champ EXPLICITE : vide = aucun modèle (pas de fallback draft)
    if (isRetry) fd.set('forward_only', '1');  // la vidéo est déjà dans la Veille -> pas de re-post
    var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var to = ctrl ? setTimeout(function () { ctrl.abort(); }, 150000) : 0;
    fetch('/veille/send', { method: 'POST', body: fd, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        clearTimeout(to); endBusy(g);
        var b2 = (g === S.gen) ? el('vprep-send') : null;
        if (b2) b2.innerHTML = orig;
        if (!j.ok) { toast('Erreur : ' + (j.error || '?'), 'error'); return; }
        var sent = (j.models_sent || []).length;
        var errs = (j.models_err || []);
        if (j.mode && j.mode !== 'video') toast('⚠️ Parti en LIEN (vidéo introuvable) — pas en vidéo native', 'error');
        if (sent) toast('✓ Veille envoyée à ' + sent + ' modèle(s)');
        else if (!models.length) toast('✓ Envoyé dans le canal Veille');
        if (errs.length) toast('⚠️ ' + errs.join(' · '), 'error');
        // succès = au moins 1 modèle servie, OU envoi « canal seulement » voulu
        if (sent || !models.length) {
          // succès réel : marque la carte, ferme, et resynchronise les compteurs
          var card = document.querySelector('.veille-card[data-rid="' + rid + '"]');
          if (card) {
            var wasSent = card.getAttribute('data-sent') === '1';
            var cb = card.querySelector('.vl-rdy-cb'); if (cb) cb.checked = false;
            if (typeof window.veilleReadyVisual === 'function') window.veilleReadyVisual(card, false);
            var lbl = card.querySelector('.vl-rdy'); if (lbl) lbl.style.display = 'none';
            var media = card.querySelector('.reel-media');
            if (media && !wasSent) {
              var r2 = document.createElement('div'); r2.style.cssText = 'position:absolute;top:11px;left:46px;background:#22c55e;color:#fff;font-size:10px;font-weight:800;padding:4px 10px;border-radius:6px;z-index:6'; r2.textContent = '✓ ENVOYÉ'; media.appendChild(r2);
            }
            card.setAttribute('data-prepared', '0');
            card.setAttribute('data-sent', '1');
            delete card.dataset.retryModels;   // succès -> plus de retry en attente
          }
          if (g === S.gen) close();
          // tuiles Envoyés / A envoyer + compteurs par jour : re-render AJAX
          if (typeof window.refreshVeilleSection === 'function') window.refreshVeilleSection();
        } else {
          // vidéo postée dans la Veille mais 0 modèle servi : PAS de faux « ✓ ENVOYÉ ».
          // Retry proposé UNIQUEMENT si une vidéo Telegram existe (mode video) —
          // en mode lien il n'y a rien à re-forwarder, le re-clic re-posterait.
          if (j.mode === 'video' && j.tg_file_id) {
            var cardR = document.querySelector('.veille-card[data-rid="' + rid + '"]');
            if (cardR) cardR.dataset.retryModels = '1';   // survit à la fermeture du modal
            if (b2) { b2.dataset.retry = '1'; b2.innerHTML = '🔁 Réessayer les modèles'; }
          }
        }
      })
      .catch(function (e) {
        clearTimeout(to); endBusy(g);
        var b2 = (g === S.gen) ? el('vprep-send') : null;
        if (b2) b2.innerHTML = orig;
        var msg = (e && e.name === 'AbortError')
          ? '⚠️ trop long — vérifie sur Telegram si c\'est parti AVANT de re-cliquer'
          : ('Erreur : ' + e);
        toast(msg, 'error');
      });
  }

  window.veillePrepare = open;
})();
