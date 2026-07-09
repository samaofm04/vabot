/* ============================================================================
   Facture — compta mensuelle OFM (UI complète, consomme /facture/state)
   KPI, chips par catégorie, groupes pliables, marquer payé, % de revenus,
   phases de paiement, paramètres (taux EUR→USD, associés), mois suivant.
   ========================================================================== */
(function () {
  'use strict';

  var S = { month: null, data: null, filter: 'all', market: 'all', collapsed: {} };
  var MOIS = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
              'août', 'septembre', 'octobre', 'novembre', 'décembre'];

  function root() { return document.getElementById('facture-root'); }
  function esc(x) {
    return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function money(v) {
    return '$' + (Math.round(v * 100) / 100).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function moneyShort(v) { return '$' + Math.round(v).toLocaleString('en-US'); }
  function monthLabel(m) {
    if (!m) return '';
    var y = m.slice(0, 4), mm = parseInt(m.slice(5, 7), 10);
    var lbl = MOIS[mm].charAt(0).toUpperCase() + MOIS[mm].slice(1) + ' ' + y;
    if (S.data && m === S.data.cur_month) lbl += ' (en cours)';
    return lbl;
  }
  function frDate(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso + 'T12:00:00');
      return d.getDate() + ' ' + MOIS[d.getMonth() + 1];
    } catch (e) { return iso; }
  }
  function toast(msg, type) { if (typeof showToast === 'function') showToast(msg, type || 'success'); }

  function load(month) {
    fetch('/facture/state' + (month ? '?month=' + month : ''))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { root().innerHTML = '<div style="color:#f87171;padding:20px">Erreur : ' + esc(d.error) + '</div>'; return; }
        S.data = d; S.month = d.month;
        render();
      })
      .catch(function (e) { root().innerHTML = '<div style="color:#f87171;padding:20px">Erreur réseau : ' + esc(e) + '</div>'; });
  }

  /* ─────────────────────────── rendu principal ─────────────────────────── */
  function render() {
    var d = S.data, t = d.totals;
    // Filtre marché actif -> les KPI basculent sur les totaux de CE marché
    var mkTag = '';
    if (S.market !== 'all' && d.by_market && d.by_market[S.market]) {
      t = d.by_market[S.market];
      mkTag = S.market === 'us' ? ' 🇺🇸' : ' 🇫🇷';
    }
    var monthOpts = d.months.map(function (m) {
      return '<option value="' + m + '"' + (m === S.month ? ' selected' : '') + '>' + esc(monthLabel(m)) + '</option>';
    }).join('');

    var kpis =
      kpi('📨 Revenus / mois' + mkTag, moneyShort(t.rev), '#22c55e', t.rev_count + ' ligne(s)', 'linear-gradient(90deg,#22c55e,#3b82f6)') +
      kpi('📩 Dépenses / mois' + mkTag, moneyShort(t.exp), '#f87171', t.exp_count + ' ligne(s)', 'linear-gradient(90deg,#ef4444,#f59e0b)') +
      kpi('💰 Bénéfice net / mois' + mkTag, moneyShort(t.net), t.net >= 0 ? '#22c55e' : '#f87171', 'Revenus − Dépenses', 'linear-gradient(90deg,#22c55e,#a855f7)') +
      kpi('👑 Part lead (toi)' + mkTag, moneyShort(t.lead), '#facc15', (100 - d.totals.assoc_pct) + '% du net', 'linear-gradient(90deg,#facc15,#f97316)');

    var mktChips = [['all', '🌍 Tous'], ['fr', '🇫🇷 France'], ['us', '🇺🇸 US']]
      .map(function (c) {
        var on = S.market === c[0];
        return '<button class="fx-mkt" data-m="' + c[0] + '" style="padding:8px 15px;border-radius:999px;border:1px solid ' +
          (on ? '#22c55e' : '#2a2a35') + ';background:' + (on ? 'rgba(34,197,94,.15)' : 'transparent') +
          ';color:' + (on ? '#fff' : '#9a9aa8') + ';font-size:12.5px;font-weight:700;cursor:pointer;margin:0">' + c[1] + '</button>';
      }).join('');

    var chips = [['all', 'Tout'], ['rev', '📨 Revenus'], ['rev_mym', '💛 MYM'], ['model', '🧜‍♀️ Modèles'],
      ['chatter', '💬 Chatters'], ['va', '👤 VAs'], ['manager', '👔 Managers'], ['app', '📱 Apps'], ['other', '📁 Autres']]
      .map(function (c) {
        var on = S.filter === c[0];
        return '<button class="fx-chip" data-f="' + c[0] + '" style="padding:8px 15px;border-radius:999px;border:1px solid ' +
          (on ? '#6366f1' : '#2a2a35') + ';background:' + (on ? 'rgba(99,102,241,.18)' : 'transparent') +
          ';color:' + (on ? '#fff' : '#9a9aa8') + ';font-size:12.5px;font-weight:700;cursor:pointer;margin:0">' + c[1] + '</button>';
      }).join('');

    var html =
      '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">' +
      '<h2 style="margin:0;font-size:26px;display:flex;align-items:center;gap:10px">🧾 Facture <span style="font-size:13px;color:#888;font-weight:500">— YouLab (lead)</span></h2>' +
      '</div>' +
      '<p style="margin:0 0 16px;color:#888;font-size:13px">Gestion des revenus + dépenses de l&#39;agence (calculs en USD).</p>' +
      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px">' +
      '<select id="fx-month" style="width:auto;padding:10px 14px;background:#15151d;border:1px solid #2a2a35;color:#fff;border-radius:10px;font-size:13px;font-weight:700">📅 ' + monthOpts + '</select>' +
      '<div style="flex:1"></div>' +
      '<button id="fx-next" class="fx-btn2" style="padding:10px 16px">🧾 Démarrer mois suivant</button>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:16px">' + kpis + '</div>' +
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">' + mktChips +
      '<span style="width:1px;height:22px;background:#2a2a35;margin:0 4px"></span>' + chips +
      '<div style="flex:1"></div>' +
      '<button id="fx-settings" class="fx-btn2" style="padding:9px 15px">⚙️ Paramètres</button>' +
      '<button id="fx-add" style="padding:9px 17px;background:linear-gradient(135deg,#818cf8,#a78bfa);border:0;color:#0d0d18;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;margin:0">+ Ajouter une ligne</button>' +
      '</div>' +
      renderGroups() +
      '<style>.fx-btn2{background:#15151d;border:1px solid #2a2a35;color:#ddd;border-radius:10px;font-size:12.5px;font-weight:700;cursor:pointer;margin:0}.fx-btn2:hover{background:#1d1d28;color:#fff}</style>';

    root().innerHTML = html;

    document.getElementById('fx-month').addEventListener('change', function () { load(this.value); });
    document.getElementById('fx-next').addEventListener('click', nextMonth);
    document.getElementById('fx-add').addEventListener('click', function () { openLineModal(null); });
    document.getElementById('fx-settings').addEventListener('click', openSettingsModal);
    Array.prototype.forEach.call(root().querySelectorAll('.fx-chip'), function (c) {
      c.addEventListener('click', function () { S.filter = c.dataset.f; render(); });
    });
    Array.prototype.forEach.call(root().querySelectorAll('.fx-mkt'), function (c) {
      c.addEventListener('click', function () { S.market = c.dataset.m; render(); });
    });
    bindGroupEvents();
  }

  function kpi(label, value, color, sub, grad) {
    return '<div style="background:#12121a;border:1px solid #23232e;border-radius:14px;padding:16px 18px;position:relative;overflow:hidden">' +
      '<div style="position:absolute;top:0;left:0;right:0;height:2.5px;background:' + grad + '"></div>' +
      '<div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px">' + label + '</div>' +
      '<div style="font-size:28px;font-weight:800;color:' + color + ';letter-spacing:-.02em">' + value + '</div>' +
      '<div style="font-size:11.5px;color:#77778a;margin-top:6px">' + sub + '</div>' +
      '</div>';
  }

  function lineMatchesFilter(l) {
    if (S.market !== 'all' && (l.market || 'us') !== S.market) return false;
    if (S.filter === 'all') return true;
    if (S.filter === 'rev') return l.type === 'rev';
    if (S.filter === 'rev_mym') return l.cat === 'rev_mym';
    return l.cat === S.filter;
  }

  function renderGroups() {
    var d = S.data;
    var html = '';
    d.cat_order.forEach(function (cat) {
      var meta = d.cats[cat];
      var lines = d.lines.filter(function (l) { return l.cat === cat && lineMatchesFilter(l); });
      if (!lines.length) return;
      var isRev = meta.type === 'rev';
      var subtotal = lines.reduce(function (s, l) { return s + (l.usd || 0); }, 0);
      var paidN = lines.filter(function (l) { return l.paid; }).length;
      var collapsed = S.collapsed[cat];
      var paidBadge = !isRev && lines.length
        ? '<span style="background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.35);color:#4ade80;font-size:10.5px;font-weight:800;padding:3px 9px;border-radius:999px">' + paidN + '/' + lines.length + ' payées</span>'
        : '';
      html += '<div style="background:#10101a;border:1px solid #22222e;border-radius:14px;margin-bottom:14px;overflow:hidden">' +
        '<div class="fx-ghead" data-cat="' + cat + '" style="display:flex;align-items:center;gap:10px;padding:13px 16px;cursor:pointer;user-select:none">' +
        '<span style="color:#666;font-size:11px;transform:rotate(' + (collapsed ? '-90deg' : '0deg') + ');transition:transform .15s;display:inline-block">▼</span>' +
        '<span style="font-size:16px">' + meta.icon + '</span>' +
        '<span style="font-weight:800;font-size:14.5px">' + esc(meta.label) + '</span>' +
        '<span style="background:#23232e;color:#9a9aa8;font-size:10.5px;font-weight:800;padding:3px 8px;border-radius:999px">' + lines.length + '</span>' +
        paidBadge +
        '<div style="flex:1"></div>' +
        '<span style="font-weight:800;font-size:14.5px;color:' + (isRev ? '#22c55e' : '#f87171') + '">' +
        (isRev ? '+ ' : '− ') + money(subtotal) + ' <span style="font-size:10.5px;color:#77778a;font-weight:600">/ mois</span></span>' +
        '</div>' +
        (collapsed ? '' : '<div style="padding:0 12px 12px;display:flex;flex-direction:column;gap:8px">' + lines.map(renderLine).join('') + '</div>') +
        '</div>';
    });
    if (!html) {
      html = '<div style="border:1px dashed #2a2a35;border-radius:14px;padding:40px;text-align:center;color:#77778a;font-size:13.5px">' +
        'Aucune ligne pour ce mois' + (S.filter !== 'all' ? ' dans ce filtre' : '') + '.<br><br>Clique <b style="color:#a78bfa">+ Ajouter une ligne</b> pour créer tes revenus et dépenses.</div>';
    }
    return html;
  }

  function renderLine(l) {
    var d = S.data;
    var isRev = l.type === 'rev';
    var accent = isRev ? '#22c55e' : (l.paid ? '#22c55e' : '#2a2a35');
    // sous-titre montant d'origine
    var origin;
    if (l.form === 'pct') {
      var baseLbl = d.pct_bases[l.pct_of] || '';
      if (!baseLbl && l.pct_of && l.pct_of.indexOf('lines:') === 0) {
        var mids = l.pct_of.slice(6).split(',');
        var names = (d.rev_lines || []).filter(function (x) { return mids.indexOf(x.id) >= 0; })
          .map(function (x) { return x.label; });
        baseLbl = 'de ' + (names.length ? names.join(' + ') : mids.length + ' revenus');
      } else if (!baseLbl && l.pct_of && l.pct_of.indexOf('line:') === 0) {
        var rl = (d.rev_lines || []).filter(function (x) { return 'line:' + x.id === l.pct_of; })[0];
        baseLbl = rl ? 'de « ' + rl.label + ' »' : '';
      }
      origin = l.pct + '% ' + esc(baseLbl);
    } else if (l.form === 'mypuls') {
      origin = '🔄 CA MyPuls · ' + esc(l.mypuls_model || '?') + ' <span style="color:#4ade80">(auto)</span>';
    } else if (l.form === 'mypuls_crm') {
      origin = '🧾 Factures CRM MyPuls du mois <span style="color:#4ade80">(auto)</span>';
    } else {
      origin = (l.currency === 'EUR' ? '€' : '$') + (l.amount || 0).toFixed(2);
    }
    // badges
    var badges = '';
    var mb = monthBounds();
    badges += badge('📅', 'Période : ' + frDate(mb[0]) + ' → ' + frDate(mb[1]) + ' ' + S.month.slice(0, 4));
    if (isRev && l.next_pay) {
      var days = Math.ceil((new Date(l.next_pay + 'T12:00:00') - new Date()) / 86400000);
      badges += badge('🎯', 'Prochain paiement : ' + frDate(l.next_pay) + ' ' + l.next_pay.slice(0, 4) + (days >= 0 ? ' (dans ' + days + 'j)' : ''));
    }
    // phases
    var phasesHtml = '';
    if ((l.phases || []).length) {
      phasesHtml = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:7px">' + l.phases.map(function (p, i) {
        return '<button class="fx-phase" data-id="' + l.id + '" data-idx="' + i + '" style="padding:4px 11px;border-radius:999px;font-size:10.5px;font-weight:800;cursor:pointer;margin:0;border:1px solid ' +
          (p.paid ? 'rgba(34,197,94,.4)' : '#33333f') + ';background:' + (p.paid ? 'rgba(34,197,94,.12)' : 'transparent') +
          ';color:' + (p.paid ? '#4ade80' : '#9a9aa8') + '">' + (p.paid ? '✓ ' : '') + frDate(p.date) + '</button>';
      }).join('') + '</div>';
    }
    // bouton payé (dépenses sans phases)
    var payBtn = '';
    if (!isRev && !(l.phases || []).length) {
      payBtn = l.paid
        ? '<button class="fx-pay" data-id="' + l.id + '" title="Cliquer pour annuler" style="padding:5px 12px;border-radius:999px;border:1px solid rgba(34,197,94,.4);background:rgba(34,197,94,.12);color:#4ade80;font-size:11px;font-weight:800;cursor:pointer;margin:0">✓ Payé · ' + frDate(l.paid_at) + '</button>'
        : '<button class="fx-pay" data-id="' + l.id + '" style="padding:5px 12px;border-radius:999px;border:1px solid #33333f;background:transparent;color:#9a9aa8;font-size:11px;font-weight:700;cursor:pointer;margin:0">○ Marquer payé</button>';
    }
    var linkBtn = l.link
      ? '<a href="' + esc(l.link) + '" target="_blank" title="Ouvrir le lien de paiement" style="color:#818cf8;font-size:13px;text-decoration:none;padding:4px">🔗</a>'
      : '';
    return '<div style="background:#14141f;border:1px solid #23232e;border-left:3px solid ' + accent + ';border-radius:10px;padding:12px 14px">' +
      '<div style="display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap">' +
      '<div style="flex:1;min-width:200px">' +
      '<div style="font-weight:700;font-size:13.5px;color:#fff">' + ((l.market || 'us') === 'fr' ? '🇫🇷 ' : '🇺🇸 ') + esc(l.label) + '</div>' +
      '<div style="font-size:11.5px;color:#77778a;margin-top:3px">' + origin + ' <span style="color:#55556a">/ mois</span></div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">' + badges + '</div>' +
      phasesHtml +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:9px;margin-left:auto">' +
      linkBtn + payBtn +
      '<span style="font-weight:800;font-size:14px;color:' + (isRev ? '#22c55e' : '#f87171') + ';white-space:nowrap">' +
      (isRev ? '+ ' : '− ') + money(l.usd || 0) + ' <span style="font-size:10px;color:#77778a;font-weight:600">/ mois</span></span>' +
      '<button class="fx-edit" data-id="' + l.id + '" title="Modifier" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;padding:4px;margin:0">✎</button>' +
      '<button class="fx-del" data-id="' + l.id + '" title="Supprimer" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;padding:4px;margin:0">🗑</button>' +
      '</div></div></div>';
  }

  function badge(icon, txt) {
    return '<span style="background:#0e0e16;border:1px solid #26263a;color:#8f8fa8;font-size:10.5px;font-weight:600;padding:4px 10px;border-radius:8px">' + icon + ' ' + esc(txt) + '</span>';
  }

  function monthBounds() {
    var y = parseInt(S.month.slice(0, 4), 10), m = parseInt(S.month.slice(5, 7), 10);
    var last = new Date(y, m, 0).getDate();
    return [y + '-' + S.month.slice(5, 7) + '-01', y + '-' + S.month.slice(5, 7) + '-' + last];
  }

  function bindGroupEvents() {
    Array.prototype.forEach.call(root().querySelectorAll('.fx-ghead'), function (h) {
      h.addEventListener('click', function () {
        S.collapsed[h.dataset.cat] = !S.collapsed[h.dataset.cat];
        render();
      });
    });
    Array.prototype.forEach.call(root().querySelectorAll('.fx-pay'), function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); togglePay(b.dataset.id, null); });
    });
    Array.prototype.forEach.call(root().querySelectorAll('.fx-phase'), function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); togglePay(b.dataset.id, b.dataset.idx); });
    });
    Array.prototype.forEach.call(root().querySelectorAll('.fx-edit'), function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var l = S.data.lines.filter(function (x) { return x.id === b.dataset.id; })[0];
        if (l) openLineModal(l);
      });
    });
    Array.prototype.forEach.call(root().querySelectorAll('.fx-del'), function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!confirm('Supprimer cette ligne ?')) return;
        var fd = new FormData(); fd.set('month', S.month); fd.set('id', b.dataset.id);
        fetch('/facture/line/delete', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
          .then(function (j) { if (j.ok) { toast('Ligne supprimée'); load(S.month); } });
      });
    });
  }

  function togglePay(id, phaseIdx) {
    var fd = new FormData();
    fd.set('month', S.month); fd.set('id', id);
    if (phaseIdx !== null && phaseIdx !== undefined) fd.set('phase', phaseIdx);
    fetch('/facture/line/pay', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
      .then(function (j) { if (j.ok) load(S.month); else toast(j.error || 'Erreur', 'error'); });
  }

  function nextMonth() {
    if (!confirm('Démarrer le mois suivant ? Les lignes récurrentes seront reportées avec les paiements remis à zéro.')) return;
    var fd = new FormData(); fd.set('month', S.month);
    fetch('/facture/next_month', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) { toast('✓ ' + monthLabel(j.month) + ' créé (' + j.count + ' lignes reportées)'); load(j.month); }
        else toast(j.error || 'Erreur', 'error');
      });
  }

  /* ─────────────────────────── modals ─────────────────────────── */
  function modal(inner, wide) {
    closeModal();
    var ov = document.createElement('div');
    ov.id = 'fx-modal';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:9998;display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px)';
    ov.innerHTML = '<div style="background:#12121c;border:1px solid #2c2c3d;border-radius:16px;padding:24px;width:100%;max-width:' + (wide ? '620px' : '520px') + ';max-height:92vh;overflow-y:auto;box-shadow:0 30px 80px rgba(0,0,0,.6)">' + inner + '</div>';
    ov.addEventListener('click', function (e) { if (e.target === ov) closeModal(); });
    document.body.appendChild(ov);
    Array.prototype.forEach.call(ov.querySelectorAll('.fx-close'), function (b) {
      b.addEventListener('click', closeModal);
    });
  }
  function closeModal() {
    var m = document.getElementById('fx-modal');
    if (m) m.remove();
  }
  function fld(label, inner) {
    return '<div style="margin-bottom:13px"><div style="font-size:10.5px;color:#8a8a98;font-weight:800;letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px">' + label + '</div>' + inner + '</div>';
  }
  var INP = 'width:100%;padding:10px 12px;background:#0d0d16;border:1px solid #2c2c3d;color:#fff;border-radius:9px;font-size:13px;font-family:inherit;box-sizing:border-box';

  function openLineModal(line) {
    var d = S.data;
    var isEdit = !!line;
    line = line || {type: 'exp', cat: 'va', form: 'fixed', currency: 'USD', freq: 'monthly',
                    start: new Date().toISOString().slice(0, 10), phases: []};
    var catOpts = d.cat_order.map(function (c) {
      return '<option value="' + c + '"' + (line.cat === c ? ' selected' : '') + '>' + d.cats[c].icon + ' ' + d.cats[c].label + '</option>';
    }).join('');
    // Options du "% calculé sur" : catégories globales + CHAQUE ligne de revenu
    // (ex: la ligne "OF" de Revenue OF) -> le % suit ce revenu précis.
    var revLines = (d.rev_lines || []).filter(function (rl) { return rl.id !== line.id; });
    var isMulti = (line.pct_of || '').indexOf('lines:') === 0;
    var multiIds = isMulti ? line.pct_of.slice(6).split(',') : [];
    var pctBaseOpts = '<option value="multi"' + (isMulti ? ' selected' : '') + '>🧩 Plusieurs revenus (multi-sélection)</option>';
    pctBaseOpts += '<optgroup label="Global">';
    pctBaseOpts += Object.keys(d.pct_bases).map(function (k) {
      return '<option value="' + k + '"' + (line.pct_of === k ? ' selected' : '') + '>' + esc(d.pct_bases[k]) + '</option>';
    }).join('') + '</optgroup>';
    if (revLines.length) {
      pctBaseOpts += '<optgroup label="Une ligne de revenu précise">';
      pctBaseOpts += revLines.map(function (rl) {
        var key = 'line:' + rl.id;
        var tag = (d.cats[rl.cat] ? d.cats[rl.cat].label : '');
        return '<option value="' + key + '"' + (line.pct_of === key ? ' selected' : '') + '>💠 ' +
          esc(rl.label) + (tag ? ' (' + esc(tag) + ')' : '') + '</option>';
      }).join('') + '</optgroup>';
    }
    modal(
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px">' +
      '<div style="font-size:17px;font-weight:800">' + (isEdit ? 'Modifier la ligne' : 'Ajouter une ligne') + '</div>' +
      '<button class="fx-close" style="background:#1d1d28;border:0;color:#999;width:30px;height:30px;border-radius:8px;cursor:pointer;margin:0">✕</button></div>' +
      fld('📌 Libellé', '<input id="fxm-label" style="' + INP + '" placeholder="Ex: Revenue OF, VA Marc, Infloww…" value="' + esc(line.label || '') + '">') +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
      fld('💼 Type', '<select id="fxm-type" style="' + INP + '"><option value="exp"' + (line.type !== 'rev' ? ' selected' : '') + '>📩 Dépense (sortie)</option><option value="rev"' + (line.type === 'rev' ? ' selected' : '') + '>📨 Revenu (entrée)</option></select>') +
      fld('🗂 Catégorie', '<select id="fxm-cat" style="' + INP + '">' + catOpts + '</select>') +
      fld('💲 Forme', '<select id="fxm-form" style="' + INP + '"><option value="fixed"' + (line.form !== 'pct' && line.form !== 'mypuls' ? ' selected' : '') + '>💵 Montant fixe</option><option value="pct"' + (line.form === 'pct' ? ' selected' : '') + '>％ Pourcentage d&#39;un revenu</option><option value="mypuls"' + (line.form === 'mypuls' ? ' selected' : '') + '>🔄 CA MyPuls (auto)</option><option value="mypuls_crm"' + (line.form === 'mypuls_crm' ? ' selected' : '') + '>🧾 Frais CRM MyPuls (auto)</option></select>') +
      fld('🔁 Fréquence', '<select id="fxm-freq" style="' + INP + '"><option value="monthly"' + (line.freq === 'monthly' ? ' selected' : '') + '>Mensuel</option><option value="biweekly"' + (line.freq === 'biweekly' ? ' selected' : '') + '>Quinzaine (×2)</option><option value="weekly"' + (line.freq === 'weekly' ? ' selected' : '') + '>Hebdo (×4)</option><option value="once"' + (line.freq === 'once' ? ' selected' : '') + '>Une seule fois</option></select>') +
      fld('🌍 Marché', '<select id="fxm-market" style="' + INP + '"><option value="fr"' + (line.market === 'fr' ? ' selected' : '') + '>🇫🇷 France</option><option value="us"' + (line.market !== 'fr' ? ' selected' : '') + '>🇺🇸 US</option></select>') +
      '</div>' +
      '<div id="fxm-mypuls-wrap" style="display:' + (line.form === 'mypuls' ? 'block' : 'none') + '">' +
      fld('🔄 Créatrice MyPuls <span style="color:#55556a;text-transform:none">(CA du mois récupéré automatiquement, converti en $)</span>',
        '<select id="fxm-mypulsmodel" style="' + INP + '">' +
        (line.mypuls_model ? '<option value="' + esc(line.mypuls_model) + '" selected>' + esc(line.mypuls_model) + '</option>' : '<option value="">⏳ Chargement des créatrices…</option>') +
        '</select>') +
      '</div>' +
      '<div id="fxm-fixed-wrap" style="display:' + (line.form && line.form !== 'fixed' ? 'none' : 'grid') + ';grid-template-columns:1fr 130px;gap:12px">' +
      fld('💰 Montant', '<input id="fxm-amount" type="number" step="0.01" min="0" style="' + INP + '" value="' + (line.amount || '') + '" placeholder="0.00">') +
      fld('Devise', '<select id="fxm-currency" style="' + INP + '"><option value="USD"' + (line.currency !== 'EUR' ? ' selected' : '') + '>$ USD</option><option value="EUR"' + (line.currency === 'EUR' ? ' selected' : '') + '>€ EUR</option></select>') +
      '</div>' +
      '<div id="fxm-pct-wrap" style="display:' + (line.form === 'pct' ? 'grid' : 'none') + ';grid-template-columns:130px 1fr;gap:12px">' +
      fld('％ Pourcent', '<input id="fxm-pct" type="number" step="0.1" min="0" max="100" style="' + INP + '" value="' + (line.pct || '') + '" placeholder="25">') +
      fld('… calculé sur', '<select id="fxm-pctof" style="' + INP + '">' + pctBaseOpts + '</select>') +
      '</div>' +
      '<div id="fxm-multibox" style="display:' + (line.form === 'pct' && isMulti ? 'block' : 'none') + '">' +
      fld('🧩 Revenus inclus dans la base (le % s&#39;applique à leur SOMME)',
        '<div style="display:flex;flex-direction:column;gap:7px;max-height:190px;overflow-y:auto;border:1px dashed #2c2c3d;border-radius:9px;padding:11px">' +
        (revLines.length ? revLines.map(function (rl) {
          var ck = multiIds.indexOf(rl.id) >= 0;
          return '<label style="display:flex;align-items:center;gap:9px;font-size:12.5px;color:#c0c0d5;cursor:pointer;margin:0">' +
            '<input type="checkbox" class="fxm-mline" value="' + rl.id + '"' + (ck ? ' checked' : '') + ' style="width:auto;accent-color:#818cf8;cursor:pointer">' +
            esc(rl.label) + ' <span style="color:#55556a;font-size:11px">(' + money(rl.usd) + ')</span></label>';
        }).join('') : '<div style="color:#66667a;font-size:12px">Aucune ligne de revenu ce mois-ci.</div>') +
        '</div>') +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
      fld('📆 Date de début', '<input id="fxm-start" type="date" style="' + INP + '" value="' + esc(line.start || '') + '">') +
      fld('Date de fin <span style="color:#55556a;text-transform:none">(optionnel)</span>', '<input id="fxm-end" type="date" style="' + INP + '" value="' + esc(line.end || '') + '">') +
      '</div>' +
      '<div id="fxm-nextpay-wrap" style="display:' + (line.type === 'rev' ? 'block' : 'none') + '">' +
      fld('🎯 Prochain paiement (revenus)', '<input id="fxm-nextpay" type="date" style="' + INP + '" value="' + esc(line.next_pay || '') + '">') +
      '</div>' +
      fld('🔗 Lien de paiement (optionnel)', '<input id="fxm-link" style="' + INP + '" placeholder="https://infloww.com/billing — ouvert au moment de payer" value="' + esc(line.link || '') + '">') +
      fld('📆 Phases de paiement (optionnel) <button id="fxm-genphases" style="float:right;background:#1d1d28;border:1px solid #2c2c3d;color:#bbb;padding:4px 10px;border-radius:7px;font-size:11px;cursor:pointer;margin:0;text-transform:none;letter-spacing:0">📆 Générer auto</button>',
        '<div id="fxm-phases" style="display:flex;gap:6px;flex-wrap:wrap;min-height:34px;border:1px dashed #2c2c3d;border-radius:9px;padding:8px;font-size:11.5px;color:#66667a">' + renderPhaseChips(line.phases || []) + '</div>') +
      fld('📝 Notes (optionnel)', '<textarea id="fxm-notes" style="' + INP + ';min-height:60px;resize:vertical" placeholder="Ex: contrat 12 mois, paiement le 1er, etc.">' + esc(line.notes || '') + '</textarea>') +
      '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px">' +
      '<button class="fx-close" class="fx-btn2" style="padding:10px 18px">Annuler</button>' +
      '<button id="fxm-save" style="padding:10px 22px;background:linear-gradient(135deg,#818cf8,#a78bfa);border:0;color:#0d0d18;border-radius:10px;font-weight:800;cursor:pointer;margin:0">💾 Sauvegarder</button>' +
      '</div>', true);

    var phases = (line.phases || []).slice();
    document.getElementById('fxm-form').addEventListener('change', function () {
      document.getElementById('fxm-fixed-wrap').style.display = this.value === 'fixed' ? 'grid' : 'none';
      document.getElementById('fxm-pct-wrap').style.display = this.value === 'pct' ? 'grid' : 'none';
      document.getElementById('fxm-mypuls-wrap').style.display = this.value === 'mypuls' ? 'block' : 'none';
      document.getElementById('fxm-multibox').style.display =
        (this.value === 'pct' && document.getElementById('fxm-pctof').value === 'multi') ? 'block' : 'none';
      if (this.value === 'mypuls') document.getElementById('fxm-type').value = 'rev';
      if (this.value === 'mypuls_crm') document.getElementById('fxm-type').value = 'exp';
    });
    document.getElementById('fxm-pctof').addEventListener('change', function () {
      document.getElementById('fxm-multibox').style.display = this.value === 'multi' ? 'block' : 'none';
    });
    // Liste des créatrices MyPuls (pour la forme 'CA MyPuls auto')
    fetch('/facture/mypuls_models').then(function (r) { return r.json(); }).then(function (j) {
      var sel = document.getElementById('fxm-mypulsmodel');
      if (!sel) return;
      if (!j.ok) {
        if (!line.mypuls_model) sel.innerHTML = '<option value="">⚠️ ' + esc(j.error || 'MyPuls indisponible') + '</option>';
        return;
      }
      var curv = line.mypuls_model || '';
      sel.innerHTML = '<option value="">— choisir une créatrice —</option>' + (j.models || []).map(function (n) {
        return '<option value="' + esc(n) + '"' + (n === curv ? ' selected' : '') + '>' + esc(n) + '</option>';
      }).join('');
    }).catch(function () {});
    document.getElementById('fxm-type').addEventListener('change', function () {
      document.getElementById('fxm-nextpay-wrap').style.display = this.value === 'rev' ? 'block' : 'none';
    });
    document.getElementById('fxm-genphases').addEventListener('click', function (e) {
      e.preventDefault();
      var freq = document.getElementById('fxm-freq').value;
      var y = parseInt(S.month.slice(0, 4), 10), m = parseInt(S.month.slice(5, 7), 10);
      var last = new Date(y, m, 0).getDate();
      var mk = function (day) { return S.month + '-' + (day < 10 ? '0' : '') + day; };
      if (freq === 'weekly') phases = [mk(7), mk(14), mk(21), mk(last)].map(function (dt) { return {date: dt, paid: false}; });
      else if (freq === 'biweekly') phases = [mk(15), mk(last)].map(function (dt) { return {date: dt, paid: false}; });
      else phases = [{date: mk(last), paid: false}];
      document.getElementById('fxm-phases').innerHTML = renderPhaseChips(phases);
    });
    document.getElementById('fxm-save').addEventListener('click', function () {
      // Multi-sélection : la base % = 'lines:<id1>,<id2>,...' des revenus cochés
      var pctofVal = document.getElementById('fxm-pctof').value;
      if (pctofVal === 'multi') {
        var mids = Array.prototype.map.call(document.querySelectorAll('.fxm-mline:checked'), function (c) { return c.value; });
        if (document.getElementById('fxm-form').value === 'pct' && !mids.length) {
          toast('Coche au moins un revenu dans la multi-sélection', 'error');
          return;
        }
        pctofVal = 'lines:' + mids.join(',');
      }
      var payload = {
        id: line.id || '',
        label: document.getElementById('fxm-label').value,
        type: document.getElementById('fxm-type').value,
        cat: document.getElementById('fxm-cat').value,
        form: document.getElementById('fxm-form').value,
        market: document.getElementById('fxm-market').value,
        mypuls_model: (document.getElementById('fxm-mypulsmodel') || {value: ''}).value,
        amount: parseFloat(document.getElementById('fxm-amount').value) || 0,
        currency: document.getElementById('fxm-currency').value,
        pct: parseFloat(document.getElementById('fxm-pct').value) || 0,
        pct_of: pctofVal,
        freq: document.getElementById('fxm-freq').value,
        start: document.getElementById('fxm-start').value,
        end: document.getElementById('fxm-end').value,
        next_pay: document.getElementById('fxm-nextpay').value,
        link: document.getElementById('fxm-link').value,
        notes: document.getElementById('fxm-notes').value,
        phases: phases
      };
      if (!payload.label.trim()) { toast('Donne un libellé', 'error'); return; }
      var fd = new FormData();
      fd.set('month', S.month);
      fd.set('line', JSON.stringify(payload));
      fetch('/facture/line/save', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.ok) { closeModal(); toast(isEdit ? '✓ Ligne modifiée' : '✓ Ligne ajoutée'); load(S.month); }
          else toast(j.error || 'Erreur', 'error');
        });
    });
  }

  function renderPhaseChips(phases) {
    if (!phases.length) return 'Aucune phase. Clique 📆 Générer auto pour répartir le mois selon la fréquence.';
    return phases.map(function (p) {
      return '<span style="background:#1d1d2c;border:1px solid #33334a;color:#c0c0d5;padding:4px 11px;border-radius:999px;font-size:11px;font-weight:700">' + frDate(p.date) + '</span>';
    }).join('');
  }

  function openSettingsModal() {
    var st = S.data.settings;
    var assoc = (st.associates || []).slice();
    function assocRows() {
      if (!assoc.length) return '<div style="color:#66667a;font-size:12px;padding:10px 0">Aucun associé. Clique <b>+ Ajouter</b> pour en créer un.</div>';
      return assoc.map(function (a, i) {
        return '<div style="display:flex;gap:8px;align-items:center;margin-bottom:7px">' +
          '<input data-ai="' + i + '" data-k="name" style="' + INP + ';flex:1" value="' + esc(a.name) + '" placeholder="Nom">' +
          '<input data-ai="' + i + '" data-k="pct" type="number" min="0" max="100" step="0.5" style="' + INP + ';width:90px" value="' + a.pct + '">' +
          '<span style="color:#77778a;font-size:12px">%</span>' +
          '<button data-adel="' + i + '" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;margin:0">🗑</button></div>';
      }).join('');
    }
    modal(
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px">' +
      '<div style="font-size:17px;font-weight:800">⚙️ Paramètres de calcul</div>' +
      '<button class="fx-close" style="background:#1d1d28;border:0;color:#999;width:30px;height:30px;border-radius:8px;cursor:pointer;margin:0">✕</button></div>' +
      fld('💱 Taux EUR → USD', '<input id="fxs-rate" type="number" step="0.01" min="0.5" max="2" style="' + INP + '" value="' + st.eur_usd + '">') +
      fld('💸 Jour de coupure paie chatters', '<input id="fxs-cutoff" type="number" min="1" max="28" style="' + INP + '" value="' + st.cutoff + '">') +
      '<div style="background:#0d0d16;border:1px solid #26263a;border-radius:9px;padding:10px 13px;font-size:11.5px;color:#8f8fa8;margin-bottom:16px">Découpe le mois en 2 périodes de paie : <b style="color:#c0c0d5">1 → ce jour</b> et <b style="color:#c0c0d5">jour+1 → fin du mois</b>. Défaut : 15 (1-15 / 16-fin).</div>' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">' +
      '<div style="font-size:13.5px;font-weight:800">👥 Associés (% du net)</div>' +
      '<button id="fxs-addassoc" class="fx-btn2" style="padding:6px 13px">+ Ajouter associé</button></div>' +
      '<div id="fxs-assoc">' + assocRows() + '</div>' +
      '<div style="background:#0d0d16;border:1px solid #26263a;border-radius:9px;padding:10px 13px;font-size:11.5px;color:#8f8fa8;margin:10px 0 18px">Le <b style="color:#c0c0d5">lead</b> récupère automatiquement <b style="color:#c0c0d5">100% − total associés</b>.</div>' +
      '<div style="display:flex;gap:10px;justify-content:flex-end">' +
      '<button class="fx-close" class="fx-btn2" style="padding:10px 18px">Annuler</button>' +
      '<button id="fxs-save" style="padding:10px 22px;background:linear-gradient(135deg,#818cf8,#a78bfa);border:0;color:#0d0d18;border-radius:10px;font-weight:800;cursor:pointer;margin:0">💾 Sauvegarder</button>' +
      '</div>');
    function rebind() {
      document.getElementById('fxs-assoc').innerHTML = assocRows();
      Array.prototype.forEach.call(document.querySelectorAll('#fxs-assoc [data-ai]'), function (inp) {
        inp.addEventListener('input', function () {
          var a = assoc[parseInt(inp.dataset.ai, 10)];
          if (!a) return;
          if (inp.dataset.k === 'pct') a.pct = parseFloat(inp.value) || 0; else a.name = inp.value;
        });
      });
      Array.prototype.forEach.call(document.querySelectorAll('#fxs-assoc [data-adel]'), function (b) {
        b.addEventListener('click', function () { assoc.splice(parseInt(b.dataset.adel, 10), 1); rebind(); });
      });
    }
    rebind();
    document.getElementById('fxs-addassoc').addEventListener('click', function () {
      assoc.push({name: '', pct: 10}); rebind();
    });
    document.getElementById('fxs-save').addEventListener('click', function () {
      var fd = new FormData();
      fd.set('eur_usd', document.getElementById('fxs-rate').value);
      fd.set('cutoff', document.getElementById('fxs-cutoff').value);
      fd.set('associates', JSON.stringify(assoc.filter(function (a) { return (a.name || '').trim(); })));
      fetch('/facture/settings', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.ok) { closeModal(); toast('✓ Paramètres sauvegardés'); load(S.month); }
          else toast(j.error || 'Erreur', 'error');
        });
    });
  }

  /* boot */
  function boot() {
    if (!root()) { setTimeout(boot, 300); return; }
    load(null);
  }
  boot();
})();
