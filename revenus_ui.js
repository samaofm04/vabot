/* UI only: keep existing totals, payment handlers and stored crypto files. */
(function () {
  'use strict';
  var host = document.getElementById('mp-tab-chatters');
  if (!host) return;
  var table = host.querySelector('table.mypuls-table');
  if (!table || table.dataset.revenueUi) return;
  var section = host.closest('.mypuls-section');
  if (section) section.classList.add('mp-revenue-section');
  var payoutSummary = host.firstElementChild;
  if (payoutSummary && payoutSummary !== table) payoutSummary.classList.add('mp-revenue-payout');
  table.dataset.revenueUi = '1';
  table.classList.add('mp-revenue-table');
  var entries = [], openEntry = null;
  // Returning to "Tous" must restore the server's performance figures,
  // including chatters outside the visible top 30 and per-chatter rounding.
  // Commission edits submit the existing form and reload this baseline.
  var initialStats = Array.from((section || host).querySelectorAll('[data-mp-stat]')).map(function (node) {
    return {node:node, children:Array.from(node.childNodes).map(function (child) { return child.cloneNode(true); })};
  });
  var avatarMap = window.__mpCreatorAvatars || {};
  function chatterLabel(name) {
    var raw = String(name || ''), saved = (window.__mpChatterNames || {})[raw.trim().toLowerCase()];
    return saved && saved.indexOf('@') < 0 ? saved : raw.indexOf('@') >= 0 ? raw.split('@')[0] : raw;
  }
  var normalize = function (value) { return String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase(); };
  var avatars = {};
  Object.keys(avatarMap).forEach(function (name) { avatars[normalize(name)] = avatarMap[name]; });
  var segments = {}, segmentButtons = [], transactionLimit = 50;
  Object.keys(window.__mpCreatorSegments || {}).forEach(function (name) {
    segments[normalize(name)] = window.__mpCreatorSegments[name];
  });
  var groups = [['all','Toutes',''], ['mym','MYM','M'], ['of_us','OF US','OF'], ['of_fr','OF FR','OF']];
  var segment = new URLSearchParams(location.search).get('mp_group') || 'mym';
  if (!groups.some(function (g) { return g[0] === segment; })) segment = 'mym';
  window.mpRevenueInSegment = function (name) { return segment === 'all' || segments[normalize(name)] === segment; };
  var groupBar = el('div', 'mp-revenue-segments');
  groupBar.setAttribute('role', 'group'); groupBar.setAttribute('aria-label', 'Plateforme des revenus');
  groups.forEach(function (g) {
    var button = el('button', 'mp-revenue-segment'); button.type = 'button'; button.dataset.segment = g[0];
    if (g[2]) { var icon = el('span', 'mp-revenue-platform-icon ' + (g[0] === 'mym' ? 'mp-platform-mym' : 'mp-platform-of'), g[2]); icon.setAttribute('aria-hidden','true'); button.appendChild(icon); }
    button.appendChild(el('span', '', g[1]));
    button.onclick = function () { segment = g[0]; transactionLimit = 50; applySegment(true); };
    groupBar.appendChild(button); segmentButtons.push(button);
  });
  var period = section && section.querySelector('.mypuls-period');
  if (period) period.before(groupBar);

  function applySegment(updateUrl) {
    var names = new Set(Object.keys(avatarMap).concat((window.__mpTransactions || []).map(function (t) { return t.c; })));
    window.__mpExcluded = new Set(Array.from(names).filter(function (name) { return !window.mpRevenueInSegment(name); }));
    segmentButtons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.segment === segment)); });
    groupBar.dataset.activeSegment = segment;
    if (period) {
      period.querySelectorAll('a.mypuls-period-btn').forEach(function (a) { var u = new URL(a.href); u.searchParams.set('mp_group', segment); a.href = u.href; });
      var form = period.querySelector('form');
      if (form) { var input = form.querySelector('input[name=mp_group]'); if (!input) { input = document.createElement('input'); input.type = 'hidden'; input.name = 'mp_group'; form.appendChild(input); } input.value = segment; }
    }
    if (updateUrl && new URLSearchParams(location.search).get('tab') === 'revenus') {
      var url = new URL(location.href); url.searchParams.set('mp_group', segment); history.replaceState(null, '', url.href);
    }
    if (typeof window.mpUpdateVisualState === 'function') window.mpUpdateVisualState();
    if (typeof window.mpRecompute === 'function') window.mpRecompute();
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function avatar(name) {
    var box = el('span', 'mp-revenue-avatar');
    box.setAttribute('aria-label', name || 'Modèle');
    box.setAttribute('role', 'img');
    var initials = String(name || '?').slice(0, 2).toUpperCase();
    box.textContent = initials;
    var src = avatars[normalize(name)];
    if (src) {
      var img = document.createElement('img');
      img.src = src; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      img.onerror = function () { box.textContent = initials; };
      box.replaceChildren(img);
    }
    return box;
  }
  function transactions(name) {
    var excluded = window.__mpExcluded || new Set(), sh = window.__mpShift;
    return (window.__mpTransactions || []).filter(function (t) {
      if ((name !== null && t.h !== name) || excluded.has(t.c)) return false;
      if (!sh) return true;
      var hour = typeof t.t === 'number' ? t.t : -1;
      return hour >= 0 && (sh[0] <= sh[1] ? hour >= sh[0] && hour < sh[1] : hour >= sh[0] || hour < sh[1]);
    });
  }
  function dateLabel(value) {
    var s = String(value || '');
    if (!s) return 'Date non indiquée';
    if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s)) {
      if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)) {
        var date = new Date(s);
        if (!isNaN(date.getTime())) return new Intl.DateTimeFormat('fr-FR', {timeZone:'Europe/Paris', day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).format(date);
      } else {
        return s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) + ' ' + s.slice(11, 16);
      }
    }
    return s;
  }
  function timestamp(t) {
    var s = dateLabel(t.d), m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/);
    if (m) return Date.UTC(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0));
    return /^\d{4}-\d{2}-\d{2}/.test(s) ? (Date.parse(s) || 0) : 0;
  }
  function currency(t) { return /USD|\$/.test(String(t.currency || '')) || t.u ? 'USD' : 'EUR'; }
  function money(value, code) { return new Intl.NumberFormat('fr-FR', {style:'currency', currency:code || 'EUR'}).format(value); }
  function sums(txs) {
    var result = {};
    txs.forEach(function (t) { var code = currency(t); result[code] = (result[code] || 0) + Math.round(Number(t.a || 0) * 100); });
    return result;
  }
  function moneyLines(target, amounts) {
    var keys = Object.keys(amounts);
    if (!keys.length) { target.textContent = '—'; return; }
    keys.sort().forEach(function (code) { target.appendChild(el('span', 'mp-revenue-currency', money(amounts[code] / 100, code))); });
  }
  function nameCell(name, subtitle) {
    var cell = el('td'), person = el('div', 'mp-revenue-sale-person'), label = el('span');
    person.appendChild(avatar(name));
    label.appendChild(el('span', 'mp-revenue-sale-label', name || 'Modèle non indiqué'));
    if (subtitle) label.appendChild(el('span', 'mp-revenue-sale-type', subtitle));
    person.appendChild(label); cell.appendChild(person); return cell;
  }
  function updateAvatars(entry, txs) {
    var names = Array.from(new Set(txs.map(function (t) { return t.c; }).filter(Boolean)));
    entry.models.replaceChildren();
    names.slice(0, 4).forEach(function (name) { entry.models.appendChild(avatar(name)); });
    if (names.length > 4) entry.models.appendChild(el('span', 'mp-revenue-more', '+' + (names.length - 4)));
    if (!names.length) entry.models.appendChild(el('span', 'mp-revenue-more', '—'));
    entry.count.textContent = txs.length;
  }
  function closeEntry(entry) {
    entry.detail.hidden = true;
    entry.row.classList.remove('mp-row-open');
    entry.button.setAttribute('aria-expanded', 'false');
    if (entry.edit) entry.edit.style.display = 'none';
    if (openEntry === entry) openEntry = null;
  }
  function renderDetail(entry) {
    var txs = transactions(entry.name).slice().sort(function (a, b) { return timestamp(b) - timestamp(a); });
    var names = Array.from(new Set(txs.map(function (t) { return t.c || ''; })));
    entry.salesTab.textContent = 'Ventes · ' + txs.length;
    entry.modelsTab.textContent = 'Par modèle · ' + names.length;
    entry.salesTab.setAttribute('aria-selected', String(entry.mode === 'sales'));
    entry.modelsTab.setAttribute('aria-selected', String(entry.mode === 'models'));
    entry.panel.setAttribute('aria-labelledby', entry.mode === 'sales' ? entry.salesTab.id : entry.modelsTab.id);
    entry.panel.replaceChildren();
    if (!txs.length) { entry.panel.appendChild(el('p', 'mp-revenue-note', 'Aucune vente disponible dans le journal pour ce filtre.')); return; }
    var ledger = el('table', 'mp-revenue-ledger' + (entry.mode === 'models' ? ' mp-revenue-by-model' : ''));
    ledger.setAttribute('aria-label', entry.mode === 'sales' ? 'Chaque vente de ' + entry.label : 'Ventes par modèle de ' + entry.label);
    var head = ledger.createTHead().insertRow(), body = ledger.createTBody();
    (entry.mode === 'sales' ? ['Modèle et vente', 'Date / heure de Paris', 'Fan', 'Montant'] : ['Modèle', 'Ventes', 'Total du journal']).forEach(function (label) { head.appendChild(el('th', '', label)); });
    if (entry.mode === 'sales') {
      txs.slice(0, entry.limit).forEach(function (t) {
        var row = body.insertRow(); row.appendChild(nameCell(t.c, t.y));
        row.appendChild(el('td', '', dateLabel(t.d)));
        row.appendChild(el('td', '', t.f || '—'));
        row.appendChild(el('td', 'mp-revenue-money', money(Number(t.a || 0), currency(t))));
      });
    } else {
      names.forEach(function (name) {
        var sales = txs.filter(function (t) { return (t.c || '') === name; }), row = body.insertRow();
        row.appendChild(nameCell(name)); row.appendChild(el('td', '', sales.length));
        var amount = el('td', 'mp-revenue-money'); moneyLines(amount, sums(sales)); row.appendChild(amount);
      });
    }
    entry.panel.appendChild(ledger);
    if (entry.mode === 'sales' && txs.length > entry.limit) {
      var more = el('button', 'mp-revenue-load-more', 'Afficher les ' + Math.min(50, txs.length - entry.limit) + ' ventes suivantes (' + entry.limit + ' / ' + txs.length + ')');
      more.type = 'button'; more.onclick = function () { entry.limit += 50; renderDetail(entry); };
      entry.panel.appendChild(more);
    }
    var footer = el('p', 'mp-revenue-note', txs.length + ' ventes dans le journal · ');
    var total = el('span', 'mp-revenue-money'); moneyLines(total, sums(txs)); footer.appendChild(total); entry.panel.appendChild(footer);
    var observed = txs.reduce(function (sum, t) { return sum + Number(t.a || 0); }, 0);
    var reference = (window.__mpPerfCa || {})[entry.name];
    if (!(window.__mpExcluded && window.__mpExcluded.size) && !window.__mpShift && typeof reference === 'number' && Math.abs(reference - observed) > Math.max(1, reference * .05)) {
      entry.panel.appendChild(el('p', 'mp-revenue-note', 'Le journal disponible ne recoupe pas le CA total. Le CA et le calcul de paie restent ceux du tableau de performance. Le détail affiche les ventes effectivement reçues.'));
    }
  }
  function metaItem(label, cell) {
    var item = el('span', 'mp-revenue-meta-item');
    item.appendChild(el('span', '', label));
    var value = el('span', cell.className);
    while (cell.firstChild) value.appendChild(cell.firstChild);
    if (cell.title) value.title = cell.title;
    item.appendChild(value); return item;
  }
  var header = table.tHead && table.tHead.rows[0];
  if (header) { header.replaceChildren(); ['Chatteur', 'Modèles', 'CA total', 'PPV', 'Tips', 'Ventes'].forEach(function (label) { header.appendChild(el('th', '', label)); }); }
  Array.from(table.querySelectorAll('.mp-chatter-row')).forEach(function (row, index) {
    var cells = Array.from(row.cells), name = row.dataset.chatter || '';
    if (cells.length < 5) return;
    var orphan = row.classList.contains('mp-row-orphelin');
    var edit = row.nextElementSibling;
    if (!edit || !edit.classList.contains('mp-edit-row')) edit = null;
    var entry = {row:row, name:name, label:chatterLabel(name), edit:edit, mode:'sales', limit:50};
    entry.initialDisplay = row.style.display;
    entry.initialAmounts = Array.from(row.querySelectorAll('.mp-cell-ca-total,.mp-cell-ca-ppv,.mp-cell-ca-tips,.mp-cell-pay')).map(function (node) {
      return {node:node, text:node.textContent, color:node.style.color};
    });
    var button = el('button', 'mp-revenue-toggle'); button.type = 'button';
    button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-label', 'Détail de ' + entry.label);
    var chevron = el('span', 'mp-revenue-chevron'); chevron.setAttribute('aria-hidden', 'true');
    button.appendChild(chevron); button.appendChild(el('span', 'mp-revenue-name', entry.label));
    cells[0].replaceChildren(button); entry.button = button;
    var modelCell = el('td'); entry.models = el('div', 'mp-revenue-models'); modelCell.appendChild(entry.models);
    entry.count = el('td', 'mp-revenue-count');
    var meta = el('td', 'mp-revenue-meta'); meta.colSpan = 6;
    var line = el('div', 'mp-revenue-meta-line'); meta.appendChild(line);
    var crypto = el('div', 'mp-revenue-crypto'); crypto.appendChild(el('span', 'mp-revenue-crypto-label', 'Crypto'));
    if (!orphan && cells.length >= 10) {
      line.appendChild(metaItem('Conv.', cells[4])); line.appendChild(metaItem('Commission', cells[5]));
      line.appendChild(metaItem('À payer', cells[6])); line.appendChild(metaItem('Présence', cells[8]));
      line.appendChild(metaItem('Payé', cells[9]));
      var content = el('div'); while (cells[7].firstChild) content.appendChild(cells[7].firstChild); crypto.appendChild(content);
      var editButton = content.querySelector('button[onclick*="mpToggleEdit"]');
      if (editButton) { editButton.textContent = 'Modifier'; editButton.setAttribute('aria-label', 'Modifier la crypto de ' + entry.label); }
      var photo = content.querySelector('.mp-crypto-thumb img');
      if (photo) {
        photo.alt = 'Capture crypto de ' + entry.label;
        var photoButton = el('button', 'mp-revenue-photo-button');
        photoButton.type = 'button'; photoButton.setAttribute('aria-label', 'Agrandir la capture crypto de ' + entry.label);
        photo.removeAttribute('onclick');
        photoButton.onclick = function () { window.mpEnlargeImg(photo.src); };
        photo.parentNode.insertBefore(photoButton, photo); photoButton.appendChild(photo);
      }
    } else {
      line.textContent = 'Ventes non attribuées · aucun paiement';
      crypto.hidden = true;
    }
    row.replaceChildren(cells[0], modelCell, cells[1], cells[2], cells[3], entry.count, meta);
    // The existing pay cell was moved into a span with the same class.
    entry.initialAmounts.forEach(function (saved) {
      if (saved.node.classList.contains('mp-cell-pay')) saved.node = row.querySelector('.mp-cell-pay');
    });
    var detail = el('tr', 'mp-revenue-details-row'); detail.hidden = true; detail.id = 'mp-revenue-detail-' + index;
    button.setAttribute('aria-controls', detail.id); entry.detail = detail;
    var detailCell = detail.insertCell(); detailCell.colSpan = 6; detailCell.appendChild(crypto);
    var detailHead = el('div', 'mp-revenue-detail-head'), tabs = el('div', 'mp-revenue-detail-tabs');
    tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Détail des revenus de ' + entry.label);
    ['sales', 'models'].forEach(function (mode) {
      var tab = el('button', 'mp-revenue-detail-tab'); tab.type = 'button'; tab.setAttribute('role', 'tab');
      tab.id = 'mp-revenue-' + mode + '-' + index; tab.setAttribute('aria-controls', 'mp-revenue-panel-' + index);
      tab.onclick = function () { entry.mode = mode; renderDetail(entry); tab.focus(); };
      tab.onkeydown = function (event) { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); (mode === 'sales' ? entry.modelsTab : entry.salesTab).click(); } };
      tabs.appendChild(tab); if (mode === 'sales') entry.salesTab = tab; else entry.modelsTab = tab;
    });
    detailHead.appendChild(tabs); detailHead.appendChild(el('span', 'mp-revenue-note', 'Ventes de la période sélectionnée'));
    detailCell.appendChild(detailHead); entry.panel = el('div'); entry.panel.id = 'mp-revenue-panel-' + index; entry.panel.setAttribute('role', 'tabpanel'); detailCell.appendChild(entry.panel);
    row.after(detail);
    button.onclick = function () {
      if (openEntry === entry) { closeEntry(entry); return; }
      if (openEntry) closeEntry(openEntry);
      openEntry = entry; detail.hidden = false; row.classList.add('mp-row-open'); button.setAttribute('aria-expanded', 'true'); renderDetail(entry);
    };
    updateAvatars(entry, transactions(name)); entries.push(entry);
  });
  function refresh() {
    entries.forEach(function (entry) {
      updateAvatars(entry, transactions(entry.name));
      if (entry.row.style.display === 'none') closeEntry(entry);
      else if (openEntry === entry) renderDetail(entry);
    });
    refreshTransactions();
  }
  function refreshTransactions() {
    var target = document.querySelector('#mp-tab-tx table tbody');
    if (!target) return;
    var txs = transactions(null).slice().sort(function (a,b) { return timestamp(b) - timestamp(a); });
    var orphan = section.querySelector('[data-mp-stat="non_attribue"]');
    if (orphan) {
      if (!(window.__mpExcluded && window.__mpExcluded.size) && !window.__mpShift) orphan.hidden = false;
      else {
        var amount = txs.reduce(function (sum,t) { return sum + ((window.__mpCryptoData[t.h] || {}).non_attribue ? Number(t.a || 0) : 0); },0);
        orphan.textContent = 'dont ' + amount.toFixed(2) + '€ non attribué — non payé';
        orphan.hidden = amount <= 0;
      }
    }
    target.replaceChildren();
    txs.slice(0, transactionLimit).forEach(function (t) {
      var row = target.insertRow();
      [dateLabel(t.d), t.c || '—', chatterLabel(t.h) || '—', t.f || '—', money(Number(t.a || 0), currency(t)), t.y || '—'].forEach(function (value) { row.appendChild(el('td','',value)); });
    });
    if (!txs.length) { var empty = target.insertRow().insertCell(); empty.colSpan = 6; empty.textContent = 'Aucune vente pour ces filtres.'; }
    var more = document.getElementById('mp-revenue-tx-more');
    if (!more) { more = el('button','mp-revenue-load-more'); more.id = 'mp-revenue-tx-more'; more.type = 'button'; target.closest('table').after(more); more.onclick = function () { transactionLimit += 50; refreshTransactions(); }; }
    more.hidden = txs.length <= transactionLimit;
    more.textContent = 'Afficher les ventes suivantes (' + Math.min(transactionLimit, txs.length) + ' / ' + txs.length + ')';
    var txTab = section.querySelector('.mypuls-tab[onclick*="tx"]');
    if (txTab) txTab.textContent = 'Transactions (' + txs.length + ')';
    var chatterTab = section.querySelector('.mypuls-tab[onclick*="chatters"]');
    var count = section.querySelector('[data-mp-stat="active_chatters"]');
    if (chatterTab && count) chatterTab.textContent = 'Chatteurs (' + count.textContent.split('/')[0] + ')';
  }
  var originalRecompute = window.mpRecompute;
  if (typeof originalRecompute === 'function') window.mpRecompute = function () {
    var result = originalRecompute.apply(this, arguments);
    if (!(window.__mpExcluded && window.__mpExcluded.size) && !window.__mpShift) {
      initialStats.forEach(function (saved) { saved.node.replaceChildren.apply(saved.node, saved.children.map(function (child) { return child.cloneNode(true); })); });
      entries.forEach(function (entry) {
        entry.row.style.display = entry.initialDisplay;
        entry.initialAmounts.forEach(function (saved) { if (saved.node) { saved.node.textContent = saved.text; saved.node.style.color = saved.color; } });
      });
    }
    refresh();
    if (typeof window.mpRefreshRevenueChart === 'function') window.mpRefreshRevenueChart();
    return result;
  };
  var originalToggleEdit = window.mpToggleEdit;
  if (typeof originalToggleEdit === 'function') window.mpToggleEdit = function () {
    var result = originalToggleEdit.apply(this, arguments);
    entries.forEach(function (entry) { if (entry.edit && entry.edit.style.display === 'table-row') entry.edit.style.display = 'block'; });
    return result;
  };
  // Existing image upload and editing keep their original routes and data.
  var originalUpload = window.mpUploadCryptoShot;
  if (typeof originalUpload === 'function') window.mpUploadCryptoShot = async function (input, rowIdx) {
    await originalUpload.apply(this, arguments);
    var source = document.querySelector('#mp-shot-' + rowIdx + ' img');
    var entry = entries.find(function (item) { return item.edit && item.edit.id === 'mp-edit-row-' + rowIdx; });
    if (!source || !entry) return;
    var thumb = entry.detail.querySelector('.mp-crypto-thumb img');
    if (thumb) thumb.src = source.src;
  };
  applySegment(false);
})();
