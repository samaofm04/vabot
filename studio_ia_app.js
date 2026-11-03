/* studio_ia_app.js — l'écran du Studio IA (onglet « studioia » du dashboard).
   Servi par /studio-ia/app.js ; `node --check` le vérifie tel qu'il est servi.
   Il lit window.SIA_CONF (textes, modèles, clé présente) posé par le fragment
   et se rebranche seul si l'onglet est réinjecté (chargement paresseux). */
(function () {
  'use strict';
  var C = window.SIA_CONF || {};
  var T = C.t || {};
  var root = document.getElementById('sia-root');
  if (!root) { return; }
  if (window.__sia) {
    if (window.__sia.timer) { clearInterval(window.__sia.timer); }
    if (window.__sia.chrono) { clearInterval(window.__sia.chrono); }
    if (window.__sia.collerHandler) { document.removeEventListener('paste', window.__sia.collerHandler); }
    if (window.__sia.toucheHandler) { document.removeEventListener('keydown', window.__sia.toucheHandler); }
  }
  var S = window.__sia = {
    type: 'video', modele: null, options: {}, refs: [], taches: [], credits: null,
    cle: !!C.cle, cleFin: C.cle_fin || '', admin: !!C.admin, cleOuvert: false,
    timer: null, chrono: null, vue: 'creer', envoi: false,
    estimTimer: null, estime: null, alerteErreur: false, collerHandler: null, toucheHandler: null
  };
  var MOD = C.modeles || [];
  var MAX_OUVERTES = C.max_ouvertes || 5;
  var DEFAUTS = { video: 'wan3', image: 'seedream5flash', motion: 'kling3motion' };
  var MIMES_IMAGE = ['image/jpeg', 'image/png', 'image/webp'];
  var MIMES_VIDEO = ['video/mp4', 'video/quicktime'];
  function estVideo(mime) { return (mime || '').indexOf('video/') === 0; }
  function accepteVideo(m) { return !!m && m.references.types.some(estVideo); }
  var SVG_DL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 21h16"/></svg>';
  var SVG_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  var SVG_REDO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>';
  var SVG_EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(s, o) {
    return String(s || '').replace(/\{(\w+)\}/g, function (_, k) {
      return o && o[k] !== undefined && o[k] !== null ? o[k] : '';
    });
  }
  function nb(x) {
    if (x === null || x === undefined || isNaN(x)) { return '?'; }
    var f = Number(x);
    return f === Math.round(f) ? String(f) : f.toFixed(1).replace(/\.0$/, '');
  }
  function toast(msg, type) {
    if (typeof window.showToast === 'function') {
      try { window.showToast(msg, type || 'info'); return; } catch (e) { /* repli */ }
    }
    window.alert(msg);
  }
  function confirmer(msg) {
    if (typeof window.showConfirmAsync === 'function') {
      try { return Promise.resolve(window.showConfirmAsync(T.masquer || '', msg)); } catch (e) { /* repli */ }
    }
    return Promise.resolve(window.confirm(msg));
  }
  function lireJson(r) {
    return r.text().then(function (txt) {
      var d = {};
      try { d = JSON.parse(txt); } catch (e) { d = { ok: false, erreur: T.erreur_reseau }; }
      if (r.status === 401) { d = { ok: false, erreur: 'unauth' }; }
      if (r.status === 403 && !d.erreur) { d = { ok: false, erreur: 'forbidden' }; }
      d.__http = r.status;
      return d;
    });
  }
  function get(url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } }).then(lireJson);
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(lireJson);
  }
  function maintenant() { return Math.floor(Date.now() / 1000); }
  function duree(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return (m ? m + ' min ' : '') + (s < 10 && m ? '0' : '') + s + ' ' + (T.secondes || 's');
  }
  function ilYA(ts) {
    var d = maintenant() - (ts || 0);
    var txt;
    if (d < 60) { txt = d + ' s'; }
    else if (d < 3600) { txt = Math.floor(d / 60) + ' min'; }
    else if (d < 86400) { txt = Math.floor(d / 3600) + ' h'; }
    else { txt = Math.floor(d / 86400) + ' j'; }
    return fmt(T.il_y_a, { d: txt });
  }
  function dateCourte(ts) {
    try {
      var d = new Date((ts || 0) * 1000);
      return d.toLocaleDateString(C.langue === 'en' ? 'en-GB' : 'fr-FR', { day: '2-digit', month: 'short' })
        + ' ' + d.toLocaleTimeString(C.langue === 'en' ? 'en-GB' : 'fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ''; }
  }
  function famille(cle) {
    if (cle.indexOf('kling') === 0) { return 'kling'; }
    if (cle.indexOf('seedance') === 0) { return 'seedance'; }
    if (cle.indexOf('wan') === 0) { return 'wan'; }
    return 'seedream';
  }

  // ------------------------------------------------------------ modèles --
  function modeleParCle(cle) {
    for (var i = 0; i < MOD.length; i++) { if (MOD[i].cle === cle) { return MOD[i]; } }
    return null;
  }
  function modelesDuType() {
    return MOD.filter(function (m) { return m.type === S.type; });
  }
  function rendreModeles() {
    var box = $('sia-modeles'), h = '';
    modelesDuType().forEach(function (m) {
      h += '<div class="sia-modele' + (S.modele && S.modele.cle === m.cle ? ' on' : '') + '" data-cle="' + esc(m.cle) + '" role="button" tabindex="0">'
        + '<div class="sia-logo l-' + famille(m.cle) + '">' + esc(m.nom.charAt(0)) + '</div>'
        + '<div class="sia-modele-txt"><div class="sia-modele-nom">' + esc(m.nom)
        + (m.badge ? '<span class="sia-badge">' + esc(m.badge) + '</span>' : '') + '</div>'
        + '<div class="sia-modele-sous" title="' + esc(m.editeur + ' · ' + m.resume) + '">' + esc(m.editeur) + ' · ' + esc(m.resume) + '</div></div>'
        + '<div class="sia-prix" title="' + esc(T.estime) + '">⚡ ' + (m.type === 'motion' ? nb(m.prix_seconde) + (T.par_seconde || '/s') : nb(m.estimation_defaut)) + '</div></div>';
    });
    box.innerHTML = h;
    Array.prototype.forEach.call(box.querySelectorAll('.sia-modele'), function (el) {
      el.addEventListener('click', function () { choisirModele(el.getAttribute('data-cle')); });
      el.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); choisirModele(el.getAttribute('data-cle')); }
      });
    });
  }
  function choisirModele(cle) {
    var m = modeleParCle(cle);
    if (!m) { return; }
    S.modele = m;
    S.options = {};
    m.options.forEach(function (o) { S.options[o.cle] = o.defaut; });
    if (S.refs.length > m.references.max) {
      S.refs = S.refs.slice(0, m.references.max);
      toast(fmt(T.refs_max, { n: m.references.max }), 'info');
    }
    var mauvaises = S.refs.filter(function (r) { return r.mime && m.references.types.indexOf(r.mime) < 0; });
    if (mauvaises.length) {
      S.refs = S.refs.filter(function (r) { return mauvaises.indexOf(r) < 0; });
      toast(T.ref_type_kling, 'info');
    }
    try { localStorage.setItem('sia_modele_' + S.type, cle); } catch (e) { /* navigation privée */ }
    // la zone de dépôt prend la vidéo quand le modèle la lit (motion, Seedance)
    $('sia-fichier').setAttribute('accept', (accepteVideo(m) ? MIMES_IMAGE.concat(MIMES_VIDEO) : MIMES_IMAGE).join(','));
    var ta = $('sia-prompt');
    ta.disabled = !!m.sans_prompt;
    if (m.sans_prompt) { ta.setAttribute('data-ph', ta.getAttribute('data-ph') || ta.getAttribute('placeholder') || ''); ta.setAttribute('placeholder', T.sans_prompt || ''); }
    else if (ta.getAttribute('data-ph')) { ta.setAttribute('placeholder', ta.getAttribute('data-ph')); ta.removeAttribute('data-ph'); }
    rendreModeles(); rendreOptions(); rendreRefs(); majPrompt(); majEstime();
  }
  function choisirType(type) {
    S.type = (type === 'image' || type === 'motion') ? type : 'video';
    Array.prototype.forEach.call(root.querySelectorAll('.sia-type'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-type') === S.type);
    });
    var souhaite = null;
    try { souhaite = localStorage.getItem('sia_modele_' + S.type); } catch (e) { souhaite = null; }
    var m = (souhaite && modeleParCle(souhaite)) || modeleParCle(DEFAUTS[S.type]) || modelesDuType()[0];
    var ph = S.type === 'image' ? T.prompt_ph_image : (S.type === 'motion' ? T.prompt_ph_motion : T.prompt_ph_video);
    $('sia-prompt').removeAttribute('data-ph');
    $('sia-prompt').setAttribute('placeholder', ph || '');
    $('sia-drop-t').textContent = S.type === 'motion' ? (T.deposer_motion || '') : (T.deposer || '');
    $('sia-drop-a').textContent = S.type === 'motion' ? (T.deposer_aide_motion || '') : (T.deposer_aide || '');
    if (m) { choisirModele(m.cle); } else { rendreModeles(); }
  }

  // ------------------------------------------------------------ options --
  function rendreOptions() {
    var box = $('sia-options'), m = S.modele, h = '';
    if (!m) { box.innerHTML = ''; return; }
    m.options.forEach(function (o) {
      if (o.si_refs && !S.refs.length) { return; }
      if (o.type === 'choix') {
        h += '<div class="sia-opt"><div class="sia-opt-tete"><span>' + esc(o.nom) + '</span></div><div class="sia-chips">';
        o.valeurs.forEach(function (v) {
          var lib = (o.libelles && o.libelles[v]) || v;
          h += '<button type="button" class="sia-chip' + (String(S.options[o.cle]) === String(v) ? ' on' : '') + '" data-opt="' + esc(o.cle) + '" data-val="' + esc(v) + '">' + esc(lib) + '</button>';
        });
        h += '</div>' + (o.aide ? '<p class="sia-aide">' + esc(o.aide) + '</p>' : '') + '</div>';
      } else if (o.type === 'nombre') {
        h += '<div class="sia-opt"><div class="sia-opt-tete"><span>' + esc(o.nom) + '</span><span class="sia-opt-val" id="sia-val-' + esc(o.cle) + '">' + esc(S.options[o.cle]) + ' ' + esc(o.unite || '') + '</span></div>'
          + '<input type="range" class="sia-range" data-opt="' + esc(o.cle) + '" min="' + esc(o.min) + '" max="' + esc(o.max) + '" step="1" value="' + esc(S.options[o.cle]) + '">'
          + '<div class="sia-range-bornes"><span>' + esc(o.min) + ' ' + esc(o.unite || '') + '</span><span>' + esc(o.max) + ' ' + esc(o.unite || '') + '</span></div>'
          + (o.aide ? '<p class="sia-aide">' + esc(o.aide) + '</p>' : '') + '</div>';
      } else if (o.type === 'bool') {
        h += '<div class="sia-opt"><label class="sia-switch"><span><span class="sia-switch-txt">' + esc(o.nom) + '</span>'
          + (o.aide ? '<span class="sia-switch-aide">' + esc(o.aide) + '</span>' : '') + '</span>'
          + '<input type="checkbox" data-opt="' + esc(o.cle) + '"' + (S.options[o.cle] ? ' checked' : '') + '><span class="sia-track"></span></label></div>';
      }
    });
    box.innerHTML = h;
    Array.prototype.forEach.call(box.querySelectorAll('.sia-chip'), function (b) {
      b.addEventListener('click', function () {
        S.options[b.getAttribute('data-opt')] = b.getAttribute('data-val');
        rendreOptions(); majEstime();
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll('input[type=range]'), function (r) {
      r.addEventListener('input', function () {
        var k = r.getAttribute('data-opt');
        S.options[k] = parseInt(r.value, 10);
        var v = $('sia-val-' + k);
        var o = null;
        m.options.forEach(function (x) { if (x.cle === k) { o = x; } });
        if (v) { v.textContent = r.value + ' ' + ((o && o.unite) || ''); }
        majEstime();
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll('input[type=checkbox]'), function (c) {
      c.addEventListener('change', function () {
        S.options[c.getAttribute('data-opt')] = c.checked;
        majEstime();
      });
    });
  }

  // --------------------------------------------------------- estimation --
  function majEstime() {
    if (!S.modele) { return; }
    if (S.estimTimer) { clearTimeout(S.estimTimer); }
    S.estimTimer = setTimeout(function () {
      var dureeVideo = 0;
      S.refs.forEach(function (r) { if (estVideo(r.mime) && r.duree) { dureeVideo = r.duree; } });
      var q = 'modele=' + encodeURIComponent(S.modele.cle) + '&nb_refs=' + S.refs.length + '&duree=' + encodeURIComponent(dureeVideo);
      Object.keys(S.options).forEach(function (k) {
        q += '&o_' + encodeURIComponent(k) + '=' + encodeURIComponent(S.options[k]);
      });
      get('/studio-ia/estimer?' + q).then(function (d) {
        if (d && d.ok) {
          S.estime = d.credits;
          $('sia-estime').textContent = nb(d.credits) + ' ' + (T.credits || '');
          verifierCredits();
        }
      }).catch(function () { /* l'estimation est un confort, pas un blocage */ });
    }, 120);
  }
  function montrerAlerte(msg, type) {
    var al = $('sia-alerte');
    al.className = 'sia-alerte on' + (type === 'att' ? ' att' : '');
    al.textContent = msg;
    S.alerteErreur = type !== 'att';
  }
  function effacerAlerte() {
    var al = $('sia-alerte');
    al.className = 'sia-alerte';
    al.textContent = '';
    S.alerteErreur = false;
  }
  function verifierCredits() {
    var btn = $('sia-generer');
    if (!S.cle) { effacerAlerte(); btn.disabled = true; return; }   // le bandeau du haut le dit deja
    if (S.credits !== null && S.credits !== undefined && S.estime !== null && S.estime !== undefined && S.estime > S.credits) {
      montrerAlerte(fmt(T.credits_insuffisants, { reste: nb(S.credits), besoin: nb(S.estime) }), 'att');
      btn.disabled = true;
      return;
    }
    if (!S.alerteErreur) { effacerAlerte(); }
    btn.disabled = S.envoi;
  }
  function majCredits(d) {
    var el = $('sia-credits'), tx = $('sia-credits-txt');
    if (d && d.credits !== undefined) { S.credits = d.credits; }
    if (!S.cle || S.credits === null || S.credits === undefined) {
      tx.textContent = T.credits_inconnus || '?';
      el.classList.add('ko');
    } else {
      tx.textContent = fmt(T.solde, { n: nb(S.credits) });
      el.classList.toggle('ko', S.credits <= 0);
    }
    verifierCredits();
  }

  // --------------------------------------------------------- références --
  function rendreRefs() {
    var box = $('sia-refs'), h = '', m = S.modele;
    S.refs.forEach(function (r, i) {
      var video = estVideo(r.mime);
      h += '<div class="sia-ref' + (r.envoi ? ' envoi' : '') + (video ? ' video' : '') + '" title="' + esc(r.nom) + (video && r.duree ? ' · ' + nb(r.duree) + ' s' : '') + '">'
        + (r.envoi ? '<div class="sia-rouet"></div>'
          : (video ? '<video src="' + esc(r.apercu) + '" muted playsinline preload="metadata"></video>' : '<img src="' + esc(r.apercu) + '" alt="">'))
        + '<span class="sia-ref-n">' + (video ? '🎬' + (r.duree ? ' ' + nb(r.duree) + ' s' : '') : (i + 1)) + '</span>'
        + '<button type="button" class="sia-ref-x" data-i="' + i + '" title="×">×</button></div>';
    });
    box.innerHTML = h;
    Array.prototype.forEach.call(box.querySelectorAll('.sia-ref-x'), function (b) {
      b.addEventListener('click', function () {
        S.refs.splice(parseInt(b.getAttribute('data-i'), 10), 1);
        rendreRefs(); rendreOptions(); majEstime();
      });
    });
    var aide = $('sia-refs-aide');
    aide.textContent = m ? (m.references.aide || '') : '';
    var drop = $('sia-drop');
    drop.style.display = (m && S.refs.length >= m.references.max) ? 'none' : '';
  }
  function ajouterFichiers(files) {
    var m = S.modele;
    if (!m || !files || !files.length) { return; }
    Array.prototype.slice.call(files).forEach(function (f) {
      var mime = (f.type || '').toLowerCase();
      if (mime === 'image/jpg') { mime = 'image/jpeg'; }
      var nom = (f.name || '').toLowerCase();
      if (!mime && /\.(mov|qt)$/.test(nom)) { mime = 'video/quicktime'; }
      if (!mime && /\.mp4$/.test(nom)) { mime = 'video/mp4'; }
      var video = estVideo(mime);
      if (S.type === 'motion') {
        // une photo et une vidéo : la nouvelle remplace celle du même genre
        S.refs = S.refs.filter(function (r) { return estVideo(r.mime) !== video; });
      }
      if (S.refs.length >= m.references.max) { toast(fmt(T.refs_max, { n: m.references.max }), 'info'); return; }
      if (video && !accepteVideo(m)) { toast(T.ref_type, 'error'); return; }
      if (video && S.type !== 'motion' && S.refs.filter(function (r) { return estVideo(r.mime); }).length >= (m.references.videos_max || 0)) {
        toast(fmt(T.refs_max, { n: m.references.videos_max || 0 }), 'info'); return;
      }
      if (!video && MIMES_IMAGE.indexOf(mime) < 0) { toast(T.ref_type, 'error'); return; }
      if (video && MIMES_VIDEO.indexOf(mime) < 0) { toast(T.video_type, 'error'); return; }
      // WebP : le serveur le convertit en PNG pour les modèles qui le refusent (Kling)
      if (!video && mime !== 'image/webp' && m.references.types.indexOf(mime) < 0) { toast(T.ref_type_kling, 'error'); return; }
      if (video && f.size > 100000000) { toast(fmt(T.video_trop_grosse, { mo: (f.size / 1e6).toFixed(1) }), 'error'); return; }
      if (!video && f.size > 30000000) { toast(fmt(T.ref_trop_grosse, { mo: (f.size / 1e6).toFixed(1) }), 'error'); return; }
      var tmp = { id: null, envoi: true, nom: f.name || (video ? 'video' : 'image'), mime: mime, duree: 0, apercu: URL.createObjectURL(f) };
      S.refs.push(tmp);
      rendreRefs();
      var fd = new FormData();
      fd.append('fichier', f, f.name || 'image');
      fetch('/studio-ia/reference', { method: 'POST', credentials: 'same-origin', body: fd, headers: { 'Accept': 'application/json' } })
        .then(lireJson)
        .then(function (d) {
          if (!d.ok) { throw new Error(d.erreur || T.erreur_reseau); }
          tmp.id = d.reference.id; tmp.envoi = false; tmp.apercu = d.reference.apercu; tmp.mime = d.reference.mime;
          tmp.duree = d.reference.duree || 0;
          if (d.reference.converti) { toast(T.webp_converti || '', 'info'); }
          if (estVideo(tmp.mime) && tmp.duree && S.type !== 'motion' && ('duration' in S.options)) {
            var oD = null;
            m.options.forEach(function (x) { if (x.cle === 'duration') { oD = x; } });
            if (oD) { S.options.duration = Math.max(oD.min, Math.min(oD.max, Math.ceil(tmp.duree))); }
          }
          rendreRefs(); rendreOptions(); majEstime();
        })
        .catch(function (e) {
          S.refs = S.refs.filter(function (x) { return x !== tmp; });
          rendreRefs(); rendreOptions(); majEstime();
          toast((e && e.message) || T.erreur_reseau, 'error');
        });
    });
  }

  // --------------------------------------------------------- génération --
  function generer() {
    if (!S.modele || S.envoi) { return; }
    if (S.refs.some(function (r) { return r.envoi; })) { toast(T.envoi_ref, 'info'); return; }
    var prompt = $('sia-prompt').value.trim();
    S.envoi = true;
    $('sia-generer').disabled = true;
    $('sia-generer-txt').textContent = T.generation || '…';
    effacerAlerte();
    post('/studio-ia/generer', {
      modele: S.modele.cle, prompt: prompt, options: S.options,
      references: S.refs.map(function (r) { return r.id; }).filter(Boolean)
    }).then(function (d) {
      if (!d.ok) {
        montrerAlerte(d.erreur || T.erreur_reseau);
        if (d.credits !== undefined && d.credits !== null) { majCredits({ credits: d.credits }); }
        return;
      }
      toast(fmt(T.lance, { n: nb(d.tache.credits_estimes) }), 'success');
      S.taches = [d.tache].concat(S.taches.filter(function (t) { return t.id !== d.tache.id; }));
      rendreTaches();
      assurerPoll();
    }).catch(function () {
      montrerAlerte(T.erreur_reseau);
    }).then(function () {
      S.envoi = false;
      $('sia-generer-txt').textContent = T.generer;
      verifierCredits();
    });
  }

  // ------------------------------------------------------------- tâches --
  function classeFormat(t) {
    var ar = (t.options && t.options.aspect_ratio) || '9:16';
    if (ar === '16:9' || ar === '21:9' || ar === '4:3' || ar === '3:2') { return ' paysage'; }
    if (ar === '1:1') { return ' carre'; }
    return '';
  }
  function carte(t) {
    var cls = 'sia-tache' + classeFormat(t);
    var credits = (t.credits !== null && t.credits !== undefined) ? ' · ⚡ ' + nb(t.credits)
      : ((t.credits_estimes !== null && t.credits_estimes !== undefined) ? ' · ≈ ⚡ ' + nb(t.credits_estimes) : '');
    var meta = '<b>' + esc(t.nom_modele) + '</b><span>' + esc(t.resume) + credits + '</span>';
    var actions = '<div class="sia-actions">';
    if (t.etat === 'fini' && t.fichiers.length) {
      var f = t.fichiers[0];
      var media = f.mime.indexOf('video') === 0
        ? (f.vignette ? '<img src="' + esc(f.vignette) + '" alt="" loading="lazy">' : '<video src="' + esc(f.url) + '" muted playsinline preload="metadata"></video>')
        : '<img src="' + esc(f.url) + '" alt="" loading="lazy">';
      actions += '<a href="' + esc(f.dl) + '" title="' + esc(T.telecharger) + '" data-stop="1">' + SVG_DL + '</a>'
        + '<button type="button" data-act="masquer" title="' + esc(T.masquer) + '">' + SVG_X + '</button></div>';
      return '<div class="' + cls + '" data-id="' + esc(t.id) + '">' + media + '<div class="sia-sur">' + meta + '</div>' + actions + '</div>';
    }
    actions += '<button type="button" data-act="reutiliser" title="' + esc(T.reutiliser) + '">' + SVG_REDO + '</button>'
      + '<button type="button" data-act="masquer" title="' + esc(T.masquer) + '">' + SVG_X + '</button></div>';
    if (t.etat === 'fini' && t.urls_kie && t.urls_kie.length) {
      return '<div class="' + cls + ' attente" data-id="' + esc(t.id) + '"><div class="sia-etat">' + esc(T.etat_fini) + '</div>'
        + '<div>' + esc(t.message) + '</div><a class="sia-btn" href="' + esc(t.urls_kie[0]) + '" target="_blank" rel="noopener" data-stop="1">' + esc(T.ouvrir_kie) + '</a>' + actions + '</div>';
    }
    if (t.etat === 'echec') {
      return '<div class="' + cls + ' attente echec" data-id="' + esc(t.id) + '"><div class="sia-etat">' + esc(T.etat_echec) + '</div>'
        + '<div>' + esc(t.message) + '</div><div class="sia-prompt-min">' + esc(t.prompt) + '</div><div>' + esc(t.nom_modele) + ' · ' + esc(t.resume) + '</div>' + actions + '</div>';
    }
    return '<div class="' + cls + ' attente" data-id="' + esc(t.id) + '"><div class="sia-rouet"></div>'
      + '<div class="sia-etat">' + esc(t.etat === 'en_cours' ? T.etat_en_cours : T.etat_en_attente) + '</div>'
      + '<div class="sia-chrono" data-depuis="' + esc(t.cree_le) + '">' + esc(duree(maintenant() - t.cree_le)) + '</div>'
      + '<div>' + esc(t.nom_modele) + ' · ' + esc(t.resume) + credits + '</div>'
      + (t.derniere_erreur ? '<div class="sia-prompt-min">' + esc(t.derniere_erreur) + '</div>' : '')
      + '<div class="sia-prompt-min">' + esc(t.prompt) + '</div>' + actions + '</div>';
  }
  function rendreGrille(id, liste, vide) {
    var box = $(id);
    if (!liste.length) { box.innerHTML = '<div class="sia-vide">' + esc(vide) + '</div>'; return; }
    box.innerHTML = liste.map(carte).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.sia-tache'), function (el) {
      el.addEventListener('click', function (ev) {
        var cible = ev.target.closest ? ev.target.closest('[data-act],[data-stop]') : null;
        if (cible) {
          if (cible.getAttribute('data-stop')) { ev.stopPropagation(); return; }
          ev.preventDefault(); ev.stopPropagation();
          action(cible.getAttribute('data-act'), el.getAttribute('data-id'));
          return;
        }
        ouvrirApercu(el.getAttribute('data-id'));
      });
    });
  }
  function rendreTaches() {
    var miennes = S.taches;
    rendreGrille('sia-recents', miennes.slice(0, 8), T.vide_recents);
    rendreGrille('sia-historique', miennes, T.vide_hist);
    var ouvertes = miennes.filter(function (t) { return t.etat === 'en_attente' || t.etat === 'en_cours'; }).length;
    var badge = $('sia-nb-ouvertes');
    badge.textContent = ouvertes;
    badge.hidden = !ouvertes;
  }
  function tacheParId(id) {
    for (var i = 0; i < S.taches.length; i++) { if (S.taches[i].id === id) { return S.taches[i]; } }
    return null;
  }
  function action(act, id) {
    var t = tacheParId(id);
    if (!t) { return; }
    if (act === 'masquer') {
      confirmer(T.masquer_confirm).then(function (ok) {
        if (!ok) { return; }
        post('/studio-ia/tache/' + encodeURIComponent(id) + '/masquer').then(function (d) {
          if (d.ok) { S.taches = S.taches.filter(function (x) { return x.id !== id; }); rendreTaches(); fermerApercu(); }
          else { toast(d.erreur || T.erreur_reseau, 'error'); }
        });
      });
    } else if (act === 'reutiliser') {
      reutiliser(t);
    }
  }
  function reutiliser(t) {
    fermerApercu();
    if (t.type && t.type !== S.type) { choisirType(t.type); }
    if (t.modele && modeleParCle(t.modele)) { choisirModele(t.modele); }
    if (t.options) {
      Object.keys(t.options).forEach(function (k) { if (k in S.options) { S.options[k] = t.options[k]; } });
      rendreOptions(); majEstime();
    }
    $('sia-prompt').value = t.prompt || '';
    majPrompt();
    choisirVue('creer');
    try { $('sia-prompt').focus(); } catch (e) { /* rien */ }
  }

  // ------------------------------------------------------------- aperçu --
  function ouvrirApercu(id) {
    var t = tacheParId(id);
    if (!t) { return; }
    var media = $('sia-modal-media'), cote = $('sia-modal-cote');
    var f = t.fichiers && t.fichiers[0];
    if (f) {
      media.innerHTML = f.mime.indexOf('video') === 0
        ? '<video src="' + esc(f.url) + '" controls autoplay playsinline loop></video>'
        : '<img src="' + esc(f.url) + '" alt="">';
    } else if (t.urls_kie && t.urls_kie.length) {
      media.innerHTML = t.type === 'video'
        ? '<video src="' + esc(t.urls_kie[0]) + '" controls autoplay playsinline loop></video>'
        : '<img src="' + esc(t.urls_kie[0]) + '" alt="">';
    } else {
      media.innerHTML = '<div class="sia-rouet"></div>';
    }
    var refs = (t.references || []).map(function (r) {
      return estVideo(r.mime) ? '<video src="' + esc(r.apercu) + '" muted playsinline preload="metadata" title="' + esc(r.nom) + '"></video>'
        : '<img src="' + esc(r.apercu) + '" alt="" title="' + esc(r.nom) + '">';
    }).join('');
    var credits = (t.credits !== null && t.credits !== undefined) ? nb(t.credits) : ('≈ ' + nb(t.credits_estimes));
    cote.innerHTML = '<h3>' + esc(t.nom_modele) + '</h3>'
      + '<div class="sia-meta">' + esc(dateCourte(t.cree_le)) + ' · ' + esc(ilYA(t.cree_le)) + '<br>' + esc(t.resume) + ' · ⚡ ' + esc(credits) + ' ' + esc(T.credits)
      + (t.utilisateur ? '<br>' + esc(T.par) + ' ' + esc(t.utilisateur) : '')
      + (t.message ? '<br>' + esc(t.message) : '') + '</div>'
      + '<div class="sia-prompt-plein">' + esc(t.prompt) + '</div>'
      + (refs ? '<div class="sia-refs-mini">' + refs + '</div>' : '')
      + '<div class="sia-btns">'
      + (f ? '<a class="sia-btn primaire" href="' + esc(f.dl) + '">' + SVG_DL + esc(T.telecharger) + '</a>' : '')
      + '<button type="button" class="sia-btn" data-act="reutiliser">' + SVG_REDO + esc(T.reutiliser) + '</button>'
      + '<button type="button" class="sia-btn danger" data-act="masquer">' + SVG_X + esc(T.masquer) + '</button>'
      + '</div>';
    Array.prototype.forEach.call(cote.querySelectorAll('[data-act]'), function (b) {
      b.addEventListener('click', function () { action(b.getAttribute('data-act'), t.id); });
    });
    $('sia-modal').classList.add('on');
  }
  function fermerApercu() {
    var m = $('sia-modal');
    if (!m.classList.contains('on')) { return; }
    m.classList.remove('on');
    $('sia-modal-media').innerHTML = '';
  }

  // -------------------------------------------------------------- suivi --
  function assurerPoll() {
    var ouvertes = S.taches.some(function (t) { return t.etat === 'en_attente' || t.etat === 'en_cours'; });
    if (ouvertes && !S.timer) { S.timer = setInterval(poll, 3500); }
    if (!ouvertes && S.timer) { clearInterval(S.timer); S.timer = null; }
  }
  function poll() {
    if (!document.body.contains(root)) { clearInterval(S.timer); S.timer = null; return; }
    get('/studio-ia/taches').then(function (d) {
      if (!d.ok) { return; }
      var avant = {};
      S.taches.forEach(function (t) { avant[t.id] = t.etat; });
      S.taches = d.taches || [];
      var fini = false;
      S.taches.forEach(function (t) {
        if (avant[t.id] && avant[t.id] !== t.etat && (t.etat === 'fini' || t.etat === 'echec')) {
          fini = true;
          toast(t.nom_modele + ' : ' + (t.etat === 'fini' ? T.etat_fini : (T.etat_echec + ' — ' + (t.message || ''))), t.etat === 'fini' ? 'success' : 'error');
        }
      });
      rendreTaches();
      assurerPoll();
      if (fini) { get('/studio-ia/etat?force=1').then(majCredits).catch(function () { /* rien */ }); }
    }).catch(function () { /* la prochaine passe réessaie */ });
  }
  function tictac() {
    Array.prototype.forEach.call(root.querySelectorAll('.sia-chrono'), function (el) {
      el.textContent = duree(maintenant() - parseInt(el.getAttribute('data-depuis') || '0', 10));
    });
  }

  // ----------------------------------------------------------------- clé --
  // Le panneau n'existe que pour l'admin (rendu serveur) : partout ailleurs
  // ces fonctions ne trouvent rien et ne font rien.
  function rendreCle() {
    var p = $('sia-cle');
    if (!p) { return; }
    var et = $('sia-cle-etat');
    et.textContent = S.cle ? fmt(T.cle_en_place, { fin: S.cleFin || '····' }) : T.cle_manquante_admin;
    et.classList.toggle('ko', !S.cle);
    p.hidden = S.cle && !S.cleOuvert;
    $('sia-cle-annuler').hidden = !S.cle;
  }
  function ouvrirCle() {
    S.cleOuvert = true;
    rendreCle();
    $('sia-cle-input').focus();
  }
  function enregistrerCle(ev) {
    ev.preventDefault();
    var inp = $('sia-cle-input'), btn = $('sia-cle-btn'), msg = $('sia-cle-msg');
    var v = (inp.value || '').trim();
    if (!v) { inp.focus(); return; }
    btn.disabled = true;
    msg.textContent = '…';
    msg.className = 'sia-cle-msg';
    post('/studio-ia/cle', { cle: v }).then(function (d) {
      btn.disabled = false;
      if (!d.ok) {
        msg.textContent = d.erreur === 'forbidden' ? 'forbidden' : (d.erreur || T.erreur_reseau);
        msg.className = 'sia-cle-msg ko';
        return;
      }
      inp.value = '';
      S.cle = true;
      S.cleFin = d.fin || '';
      S.cleOuvert = false;
      msg.textContent = fmt(T.cle_ok, { fin: S.cleFin, n: nb(d.credits) });
      msg.className = 'sia-cle-msg ok';
      toast(msg.textContent, 'success');
      majCredits({ credits: d.credits });
      verifierCredits();
      rendreCle();
    }).catch(function () {
      btn.disabled = false;
      msg.textContent = T.erreur_reseau;
      msg.className = 'sia-cle-msg ko';
    });
  }

  // --------------------------------------------------------------- vues --
  function choisirVue(vue) {
    S.vue = vue;
    Array.prototype.forEach.call($('sia-vues').querySelectorAll('button'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-vue') === vue);
    });
    $('sia-vue-creer').hidden = vue !== 'creer';
    $('sia-vue-historique').hidden = vue !== 'historique';
    $('sia-types').style.display = vue === 'creer' ? '' : 'none';
  }
  function majPrompt() {
    var ta = $('sia-prompt'), c = $('sia-compteur');
    var max = S.modele ? S.modele.prompt_max : 0;
    var n = ta.value.length;
    c.textContent = n.toLocaleString() + ' / ' + (max ? max.toLocaleString() : '—');
    c.classList.toggle('ko', !!max && n > max);
  }

  // ---------------------------------------------------------- branchement --
  Array.prototype.forEach.call(root.querySelectorAll('.sia-type'), function (b) {
    b.addEventListener('click', function () { choisirType(b.getAttribute('data-type')); });
  });
  Array.prototype.forEach.call($('sia-vues').querySelectorAll('button'), function (b) {
    b.addEventListener('click', function () { choisirVue(b.getAttribute('data-vue')); });
  });
  $('sia-generer').addEventListener('click', generer);
  $('sia-prompt').addEventListener('input', function () { majPrompt(); if (S.alerteErreur) { effacerAlerte(); verifierCredits(); } });
  $('sia-prompt').addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { ev.preventDefault(); generer(); }
  });
  $('sia-fichier').addEventListener('change', function () { ajouterFichiers(this.files); this.value = ''; });
  var drop = $('sia-drop');
  ['dragenter', 'dragover'].forEach(function (evn) {
    drop.addEventListener(evn, function (ev) { ev.preventDefault(); drop.classList.add('sur'); });
  });
  ['dragleave', 'drop'].forEach(function (evn) {
    drop.addEventListener(evn, function (ev) { ev.preventDefault(); drop.classList.remove('sur'); });
  });
  drop.addEventListener('drop', function (ev) { ajouterFichiers(ev.dataTransfer && ev.dataTransfer.files); });
  S.collerHandler = function (ev) {
    if (!document.body.contains(root) || root.offsetParent === null) { return; }
    if (ev.target === $('sia-prompt')) { return; }
    var items = ev.clipboardData && ev.clipboardData.files;
    if (items && items.length) { ev.preventDefault(); ajouterFichiers(items); }
  };
  document.addEventListener('paste', S.collerHandler);
  S.toucheHandler = function (ev) { if (ev.key === 'Escape') { fermerApercu(); } };
  document.addEventListener('keydown', S.toucheHandler);
  $('sia-modal-fermer').addEventListener('click', fermerApercu);
  $('sia-modal').addEventListener('click', function (ev) { if (ev.target === this) { fermerApercu(); } });
  $('sia-actualiser').addEventListener('click', function () { poll(); get('/studio-ia/etat?force=1').then(majCredits); });
  $('sia-actualiser2').addEventListener('click', function () { poll(); get('/studio-ia/etat?force=1').then(majCredits); });
  if ($('sia-cle')) {
    $('sia-cle-form').addEventListener('submit', enregistrerCle);
    $('sia-cle-ouvrir').addEventListener('click', ouvrirCle);
    $('sia-cle-annuler').addEventListener('click', function () { S.cleOuvert = false; rendreCle(); });
    rendreCle();
  }

  choisirType('video');
  choisirVue('creer');
  S.chrono = setInterval(tictac, 1000);
  get('/studio-ia/etat').then(function (d) {
    if (!d.ok) { if (d.erreur === 'forbidden') { montrerAlerte('forbidden'); } return; }
    S.cle = !!d.cle;
    S.cleFin = d.cle_fin || S.cleFin;
    S.taches = d.taches || [];
    rendreTaches();
    majCredits(d);
    verifierCredits();
    rendreCle();
    assurerPoll();
  }).catch(function () { majCredits({ credits: null }); });
})();
