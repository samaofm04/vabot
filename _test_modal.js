
var _vlmCurrentUid = null;
var _vlmCurrentIdent = '';
var _vlmActiveModel = '__all__';
function vaLinksOpen(uid, username, identity){
  _vlmCurrentUid = uid;
  _vlmCurrentIdent = (identity || '').toLowerCase().trim();
  document.getElementById('vlm-subtitle').textContent = '@' + username;
  document.getElementById('vlm-search').value = '';
  // Construire les pills par identite/folder
  var allLinks = window.__gmsAllLinks || [];
  var counts = {};
  allLinks.forEach(function(l){
    var m = (l.model || '(sans dossier)');
    counts[m] = (counts[m] || 0) + 1;
  });
  var models = Object.keys(counts).sort(function(a,b){ return a.localeCompare(b); });
  // Auto-select : si l identite du VA matche un folder, on filtre dessus
  var matchModel = null;
  models.forEach(function(m){
    if(m.toLowerCase() === _vlmCurrentIdent) matchModel = m;
  });
  _vlmActiveModel = matchModel || '__all__';
  var pillsHtml = '<button type="button" class="vlm-pill ' + (_vlmActiveModel === '__all__' ? 'active' : '') + '" data-pill-model="__all__" onclick="vaLinksSetModel(this)">Tous <span class="vlm-pill-count">' + allLinks.length + '</span></button>';
  models.forEach(function(m){
    var active = (m === _vlmActiveModel) ? 'active' : '';
    var safeAttr = m.replace(/"/g, '&quot;');
    pillsHtml += '<button type="button" class="vlm-pill ' + active + '" data-pill-model="' + safeAttr + '" onclick="vaLinksSetModel(this)">' + m + ' <span class="vlm-pill-count">' + counts[m] + '</span></button>';
  });
  document.getElementById('vlm-pills').innerHTML = pillsHtml;
  // Render la liste
  vaLinksRender();
  document.getElementById('va-links-modal').classList.add('show');
}
function vaLinksRender(){
  var current = (window.__vaLinksData || {})[_vlmCurrentUid] || [];
  var allLinks = window.__gmsAllLinks || [];
  var listEl = document.getElementById('vlm-list');
  var html = '';
  var groupedByModel = {};
  allLinks.forEach(function(l){
    var m = (l.model || '(sans dossier)');
    if(_vlmActiveModel !== '__all__' && m !== _vlmActiveModel) return;
    (groupedByModel[m] = groupedByModel[m] || []).push(l);
  });
  Object.keys(groupedByModel).sort().forEach(function(model){
    html += '<div style="font-size:10px;color:#888;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin:14px 8px 6px">' + model + '</div>';
    groupedByModel[model].forEach(function(l){
      var checked = current.indexOf(l.id) !== -1;
      html += '<div class="vlm-item ' + (checked ? 'checked' : '') + '" data-link-id="' + l.id + '" data-search="' + (l.name + ' ' + l.shortcode + ' ' + l.model).toLowerCase() + '" onclick="vaLinksToggle(this, event)">'
        + '<div class="vlm-cb"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>'
        + '<div class="vlm-info">'
        + '<div class="vlm-name">' + l.name + '</div>'
        + '<div class="vlm-meta">/' + l.shortcode + '</div>'
        + '</div>'
        + '<button type="button" class="vlm-row-dup" data-dup-id="' + l.id + '" title="Dupliquer ce lien dans le meme dossier" onclick="vaLinksDuplicateOne(event, this)">⎘</button>'
        + '</div>';
    });
  });
  if(!html){
    html = '<p style="color:#888;text-align:center;padding:30px">Aucun lien dans ce dossier.</p>';
  }
  listEl.innerHTML = html;
}
function vaLinksSetModel(btn){
  var m = btn.getAttribute('data-pill-model') || '__all__';
  _vlmActiveModel = m;
  document.querySelectorAll('.vlm-pill').forEach(function(p){
    p.classList.toggle('active', p.getAttribute('data-pill-model') === m);
  });
  vaLinksRender();
  // Re-apply search filter
  var q = (document.getElementById('vlm-search').value || '').toLowerCase().trim();
  if(q) vaLinksFilter(q);
}
function vaLinksToggle(el, e){
  if(e && e.target && e.target.classList && e.target.classList.contains('vlm-row-dup')) return;
  el.classList.toggle('checked');
}
function vaLinksFilter(q){
  q = (q||'').toLowerCase().trim();
  document.querySelectorAll('.vlm-item').forEach(function(el){
    var s = el.getAttribute('data-search') || '';
    el.style.display = (!q || s.indexOf(q) !== -1) ? '' : 'none';
  });
}
function vaLinksDuplicateOne(e, btn){
  if(e){ e.stopPropagation(); e.preventDefault(); }
  var linkId = btn ? btn.getAttribute('data-dup-id') : '';
  if(!linkId) return;
  if(typeof showToast === 'function') showToast('Duplication en cours…', 'info');
  var fd = new FormData();
  fd.append('link_id', linkId);
  fetch('/linkscale/duplicate', {method:'POST', body:fd})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Lien dupliqué ✓ Recharge…', 'success');
        setTimeout(function(){ window.location.reload(); }, 600);
      } else {
        if(typeof showToast === 'function') showToast('Erreur dup: ' + (d && d.error || '?'), 'error');
      }
    })
    .catch(function(err){
      if(typeof showToast === 'function') showToast('Erreur: ' + err, 'error');
    });
}
function vaLinksDuplicateSelected(){
  var ids = [];
  document.querySelectorAll('.vlm-item.checked').forEach(function(el){
    var id = el.getAttribute('data-link-id');
    if(id) ids.push(id);
  });
  if(!ids.length){
    if(typeof showToast === 'function') showToast('Sélectionne au moins 1 lien à dupliquer', 'error');
    return;
  }
  if(!confirm('Dupliquer ' + ids.length + ' lien(s) dans le même dossier ?')) return;
  if(typeof showToast === 'function') showToast('Duplication de ' + ids.length + ' lien(s)…', 'info');
  var done = 0, fail = 0;
  function next(){
    if(!ids.length){
      if(typeof showToast === 'function') showToast('Terminé : ' + done + ' OK, ' + fail + ' échec(s). Recharge…', 'success');
      setTimeout(function(){ window.location.reload(); }, 700);
      return;
    }
    var id = ids.shift();
    var fd = new FormData();
    fd.append('link_id', id);
    fetch('/linkscale/duplicate', {method:'POST', body:fd})
      .then(function(r){ return r.json(); })
      .then(function(d){ if(d && d.ok) done++; else fail++; next(); })
      .catch(function(){ fail++; next(); });
  }
  next();
}
function vaLinksGenerate(){
  // Determine le folder actif (la pill selectionnee)
  var folder = _vlmActiveModel;
  if(folder === '__all__'){
    if(typeof showToast === 'function') showToast('Sélectionne d'abord un dossier (clique une pill)', 'error');
    return;
  }
  // Demande le prefix au user (default = nom du folder)
  var defaultPrefix = folder.toLowerCase().replace(/[^a-z0-9_]/g, '');
  var prefix = prompt('Préfixe du nouveau lien (4 lettres random seront ajoutées) :', defaultPrefix);
  if(prefix === null) return;
  prefix = (prefix || '').trim();
  if(!prefix){
    if(typeof showToast === 'function') showToast('Préfixe vide', 'error');
    return;
  }
  if(typeof showToast === 'function') showToast('Génération en cours…', 'info');
  var fd = new FormData();
  fd.append('folder_name', folder);
  fd.append('prefix', prefix);
  fetch('/linkscale/generate', {method:'POST', body:fd})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){
        if(typeof showToast === 'function') showToast('Lien généré ✓ Recharge…', 'success');
        setTimeout(function(){ window.location.reload(); }, 700);
      } else {
        if(typeof showToast === 'function') showToast('Erreur: ' + (d && d.error || '?'), 'error');
      }
    })
    .catch(function(err){
      if(typeof showToast === 'function') showToast('Erreur: ' + err, 'error');
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
