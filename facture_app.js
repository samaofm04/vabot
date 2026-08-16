/* Icones monochromes de la page Facture (jeu du menu dans web_upload.py) */
(function(){var st=document.createElement('style');st.textContent='.fic{vertical-align:-2px;margin-right:5px;flex-shrink:0;opacity:.7}';document.head.appendChild(st);})();
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
  /* Sous le montant NET : le BRUT (si des frais plateforme sont appliqués)
     puis l'équivalent en euros. Permet de recouper d'un coup d'œil avec
     OnlyFans/MyM et de repérer une erreur. */
  function eurHint(usd, feePct, isOf) {
    var parts = [];
    var f = parseFloat(feePct || 0);
    var gross = 0;
    if (f > 0 && f < 100 && usd) {
      gross = usd / (1 - f / 100);            // frais explicites sur la ligne
    } else if (isOf && usd) {
      gross = usd / 0.8;                      // OnlyFans retient 20 % (montant déjà net)
    }
    if (gross) parts.push('brut ' + money(gross));
    var r = parseFloat(((S.data || {}).settings || {}).eur_usd || 0);
    if (r && usd) {
      parts.push('≈ ' + (usd / r).toLocaleString('fr-FR', {maximumFractionDigits: 0}) + ' €');
    }
    if (!parts.length) return '';
    return '<div style="font-size:10.5px;color:#77778a;font-weight:600;margin-top:1px">'
      + parts.join(' · ') + '</div>';
  }
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
  // Sous-titre de la carte « Part lead » : % applicable (par marché si des
  // associés sont rattachés à un marché) + avances remboursées s'il y en a.
  // Nom du lead (réglable dans <svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 3.6v2.4M12 18v2.4M20.4 12H18M6 12H3.6M18 6l-1.7 1.7M7.7 16.3L6 18M18 18l-1.7-1.7M7.7 7.7L6 6"/></svg>️ Paramètres) — menu « Payée par » + badges.
  function leadName() {
    var s = (S.data && S.data.settings) || {};
    return s.lead_name || 'Sama';
  }

  // Options du menu « Payée par » : l'agence, le lead par son nom, puis chaque
  // associé des Paramètres (avance à LUI rembourser, suivie dans les totaux).
  function paidByOpts(line) {
    var st = (S.data && S.data.settings) || {};
    var cur = line.paid_by || 'agence';
    var o = '<option value="agence"' + (cur === 'agence' ? ' selected' : '') + '>▦ L&#39;agence</option>' +
      '<option value="lead"' + (cur === 'lead' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.6h16M4.4 7l4 3.4L12 5l3.6 5.4 4-3.4-1.6 8.2H6z"/></svg> ' + esc(leadName()) + ' (toi) — à me rembourser</option>';
    var seen = false, vals = [];
    (st.associates || []).forEach(function (a) {
      var nm = (a.name || '').trim();
      if (!nm) return;
      var v = 'assoc:' + nm;
      if (vals.indexOf(v) !== -1) return;   // même nom sur 2 marchés = 1 option
      vals.push(v);
      if (cur === v) seen = true;
      o += '<option value="' + esc(v) + '"' + (cur === v ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8.6" r="3.1"/><path d="M3.6 19.2a5.6 5.6 0 0 1 10.8 0"/><path d="M16 6.5a3.1 3.1 0 0 1 0 6M17.4 14.6a5.4 5.4 0 0 1 3 4.6"/></svg> ' + esc(nm) + ' — à lui rembourser</option>';
    });
    // associé supprimé des Paramètres depuis : on garde son option sélectionnée
    if (cur.indexOf('assoc:') === 0 && !seen) {
      o += '<option value="' + esc(cur) + '" selected><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8.6" r="3.1"/><path d="M3.6 19.2a5.6 5.6 0 0 1 10.8 0"/><path d="M16 6.5a3.1 3.1 0 0 1 0 6M17.4 14.6a5.4 5.4 0 0 1 3 4.6"/></svg> ' + esc(cur.slice(6)) + ' — à lui rembourser</option>';
    }
    return o;
  }

  function leadSub(t, d, isGlobal) {
    // Le calcul est en 2 étages ((1 − %marché) × (1 − %global)) : le % affiché
    // doit être le MULTIPLICATEUR réel, pas 100 − la somme des %.
    var g = (d.totals && d.totals.assoc_global) || 0;
    var byMk = (d.totals && d.totals.assoc_by_mk) || {};
    var hasMk = Object.keys(byMk).some(function (k) { return byMk[k] > 0; });
    var sub;
    if (isGlobal && hasMk) {
      // vue globale avec associés de marché : un % unique n'existe pas -> détail
      var order = d.market_order || Object.keys(byMk);
      sub = order.map(function (mk) {
        var eff = Math.round((100 - (byMk[mk] || 0)) * (100 - g)) / 100;
        return mk.toUpperCase() + ' ' + eff + '%';
      }).join(' · ') + ' du net';
    } else {
      var mkPct = isGlobal ? 0 : ((t.assoc_pct || 0) - g);
      var eff = Math.round((100 - mkPct) * (100 - g)) / 100;
      sub = eff + '% du net';
    }
    if (t.reimb) sub += ' + ' + moneyShort(t.reimb) + ' à te rembourser';
    return sub;
  }

  function render() {
    var d = S.data, t = d.totals;
    // Filtre marché actif -> les KPI basculent sur les totaux de CE marché
    var mkTag = '';
    if (S.market !== 'all' && d.by_market && d.by_market[S.market]) {
      t = d.by_market[S.market];
      mkTag = S.market === 'us' ? ' 🇺🇸' : ' 🇫🇷';
    }
    // Avances des ASSOCIÉS (dépenses payées par eux) : l'agence leur doit ça.
    // Les associés des Paramètres ont leur CARTE (part + avances) — la bannière
    // ne sert plus que pour un payeur retiré des Paramètres depuis.
    // clés préfixées : un payeur nommé « constructor »/« toString » remonterait
    // sinon Object.prototype et disparaîtrait de la bannière
    var apNames = {};
    (t.assoc_parts || []).forEach(function (a) { apNames['#' + a.name] = 1; });
    var ra = t.reimb_assoc || {};
    var raKeys = Object.keys(ra).filter(function (k) { return ra[k] > 0 && !apNames['#' + k]; });
    var raBar = raKeys.length
      ? '<div style="background:rgba(129,140,248,.06);border:1px solid rgba(129,140,248,.25);border-radius:12px;padding:10px 16px;margin-bottom:16px;font-size:12.5px;color:#c8c8da"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="5.4" width="18.8" height="13.2" rx="2.6"/><path d="M2.6 10h18.8"/></svg> Avances à rembourser : ' +
        raKeys.map(function (k) { return '<b style="color:#a5b4fc">' + esc(k) + '</b> ' + moneyShort(ra[k]); }).join(' <span style="color:#55556a">·</span> ') + '</div>'
      : '';
    var monthOpts = d.months.map(function (m) {
      return '<option value="' + m + '"' + (m === S.month ? ' selected' : '') + '>' + esc(monthLabel(m)) + '</option>';
    }).join('');

    var kpis =
      kpi('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.6v10.6"/><path d="M7.4 10.6L12 15.2l4.6-4.6"/><path d="M4.4 19.4h15.2"/></svg> Revenus / mois' + mkTag, moneyShort(t.rev), '#22c55e', t.rev_count + ' ligne(s)', 'linear-gradient(90deg,#22c55e,#3b82f6)') +
      kpi('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19.4V8.8"/><path d="M7.4 13.4L12 8.8l4.6 4.6"/><path d="M4.4 4.6h15.2"/></svg> Dépenses / mois' + mkTag, moneyShort(t.exp), '#f87171', t.exp_count + ' ligne(s)', 'linear-gradient(90deg,#ef4444,#f59e0b)') +
      kpi('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M12 6.8v10.4M14.7 9.4a2.7 2.7 0 0 0-2.7-1.4c-1.7 0-2.7 1-2.7 2.2 0 2.7 5.4 1.6 5.4 4.3 0 1.2-1 2.3-2.7 2.3a2.9 2.9 0 0 1-2.8-1.6"/></svg> Bénéfice net / mois' + mkTag, moneyShort(t.net), t.net >= 0 ? '#22c55e' : '#f87171', 'Revenus − Dépenses', 'linear-gradient(90deg,#22c55e,#a855f7)') +
      kpi('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.6h16M4.4 7l4 3.4L12 5l3.6 5.4 4-3.4-1.6 8.2H6z"/></svg> Part ' + esc(leadName()) + mkTag, moneyShort(t.lead_pay != null ? t.lead_pay : t.lead), '#facc15', leadSub(t, d, S.market === 'all'), 'linear-gradient(90deg,#facc15,#f97316)');

    // Associés regroupés par PERSONNE (un même nom peut avoir une entrée par
    // marché) : la carte KPI et la boîte du Règlement montrent le MÊME montant.
    var byMkA = (d.totals && d.totals.assoc_by_mk) || {};
    var hasMkA = Object.keys(byMkA).some(function (k) { return byMkA[k] > 0; });
    var seenA = {}, people = [];
    (t.assoc_parts || []).forEach(function (a) {
      var k = '#' + a.name;
      if (!seenA[k]) { seenA[k] = {name: a.name, entries: [], part: 0, reimb: 0, pay: 0}; people.push(seenA[k]); }
      var g = seenA[k];
      g.entries.push(a);
      g.part = Math.round((g.part + (a.part || 0)) * 100) / 100;
      g.reimb = Math.round((g.reimb + (a.reimb || 0)) * 100) / 100;
      g.pay = Math.round((g.pay + (a.pay != null ? a.pay : (a.part || 0))) * 100) / 100;
    });

    // une carte par personne : sa part du split + ses avances éventuelles.
    // Un « tous » est servi APRÈS les associés de marché -> « du net restant ».
    people.forEach(function (g) {
      if (S.market !== 'all' && !g.part && !g.reimb) return;   // hors de son marché
      var sub;
      if (g.entries.length === 1) {
        var a0 = g.entries[0];
        sub = a0.pct + '% du net' + (a0.market === 'us' ? ' 🇺🇸' : a0.market === 'fr' ? ' 🇫🇷' : (hasMkA ? ' restant' : ''));
      } else {
        sub = g.entries.map(function (a) {
          return a.pct + '%' + (a.market === 'us' ? ' 🇺🇸' : a.market === 'fr' ? ' 🇫🇷' : ' global');
        }).join(' + ') + ' du net';
      }
      if (g.reimb) sub += ' + ' + moneyShort(g.reimb) + ' à lui rembourser';
      kpis += kpi('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7.4 12.6l3-3 3.4 3.2 3.2-3.2"/><path d="M3.6 9.4l3.8-3.8 4.6 1.4 4.6-1.4 3.8 3.8-4 6.6-4.4 2.6-4.4-2.6z"/></svg> Part ' + esc(g.name) + mkTag, moneyShort(g.pay), '#a5b4fc', sub, 'linear-gradient(90deg,#818cf8,#a78bfa)');
    });

    // <svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Règlement du mois : pour chaque personne, la part du bénéf, chaque
    // dépense avancée LIGNE PAR LIGNE, le total des avances, et le « À verser ».
    var setLines = (d.lines || []).filter(function (l) {
      return l.type !== 'rev' && (S.market === 'all' || (l.market || 'us') === S.market);
    });
    // un payeur retiré des Paramètres garde sa boîte (part 0, avances dues)
    setLines.forEach(function (l) {
      var pb = String(l.paid_by || '');
      if (pb.indexOf('assoc:') !== 0) return;
      var nm = pb.slice(6), k = '#' + nm;
      if (seenA[k]) return;
      var owed = Object.prototype.hasOwnProperty.call(ra, nm) ? ra[nm] : 0;
      seenA[k] = {name: nm, entries: [], part: 0, reimb: Math.round(owed * 100) / 100, pay: Math.round(owed * 100) / 100};
      people.push(seenA[k]);
    });
    var settleHtml = '';
    var hasAdv = setLines.some(function (l) {
      return l.paid_by === 'lead' || String(l.paid_by || '').indexOf('assoc:') === 0;
    });
    if (people.length || hasAdv) {
      var leadAdv = setLines.filter(function (l) { return l.paid_by === 'lead'; });
      var boxes = settleBox('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.6h16M4.4 7l4 3.4L12 5l3.6 5.4 4-3.4-1.6 8.2H6z"/></svg> ' + esc(leadName()) + ' (toi)', t.lead || 0, leadAdv,
        t.reimb || 0, t.lead_pay != null ? t.lead_pay : (t.lead || 0), '#facc15');
      people.forEach(function (g) {
        if (S.market !== 'all' && !g.part && !g.reimb) return;   // hors de son marché
        var adv = setLines.filter(function (l) { return l.paid_by === 'assoc:' + g.name; });
        boxes += settleBox('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7.4 12.6l3-3 3.4 3.2 3.2-3.2"/><path d="M3.6 9.4l3.8-3.8 4.6 1.4 4.6-1.4 3.8 3.8-4 6.6-4.4 2.6-4.4-2.6z"/></svg> ' + esc(g.name), g.part, adv, g.reimb, g.pay, '#a5b4fc');
      });
      settleHtml =
        '<div style="background:#0f0f17;border:1px solid #23232e;border-radius:14px;padding:14px 16px;margin-bottom:16px">' +
        '<div style="font-size:13px;font-weight:800;margin-bottom:5px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Règlement du mois' + mkTag + '</div>' +
        '<div style="font-size:11.5px;color:#8f8fa8;margin-bottom:10px">' + money(t.rev || 0) + ' revenus − ' + money(t.exp || 0) +
        ' dépenses = <b style="color:' + (t.net >= 0 ? '#4ade80' : '#f87171') + '">' + money(t.net || 0) +
        '</b> de bénéf à splitter · chacun récupère EN PLUS ce qu&#39;il a avancé de sa poche</div>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px">' + boxes + '</div></div>';
    }

    var mktChips = [['all', '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4a13 13 0 0 1 0 17.2a13 13 0 0 1 0-17.2z"/></svg> Tous'], ['fr', '🇫🇷 France'], ['us', '🇺🇸 US']]
      .map(function (c) {
        var on = S.market === c[0];
        return '<button class="fx-mkt" data-m="' + c[0] + '" style="padding:8px 15px;border-radius:999px;border:1px solid ' +
          (on ? '#22c55e' : '#2a2a35') + ';background:' + (on ? 'rgba(34,197,94,.15)' : 'transparent') +
          ';color:' + (on ? '#fff' : '#9a9aa8') + ';font-size:12.5px;font-weight:700;cursor:pointer;margin:0">' + c[1] + '</button>';
      }).join('');

    var chips = [['all', 'Tout'], ['rev', '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.6v10.6"/><path d="M7.4 10.6L12 15.2l4.6-4.6"/><path d="M4.4 19.4h15.2"/></svg> Revenus'], ['rev_mym', '💛 MYM'], ['model', '🧜‍♀️ Modèles'],
      ['chatter', '💬 Chatters'], ['va', '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="3.4"/><path d="M5.4 19.4a6.8 6.8 0 0 1 13.2 0"/></svg> VAs'], ['manager', '👔 Managers'], ['app', '📱 Apps'], ['other', '▤ Autres']]
      .map(function (c) {
        var on = S.filter === c[0];
        return '<button class="fx-chip" data-f="' + c[0] + '" style="padding:8px 15px;border-radius:999px;border:1px solid ' +
          (on ? '#6366f1' : '#2a2a35') + ';background:' + (on ? 'rgba(99,102,241,.18)' : 'transparent') +
          ';color:' + (on ? '#fff' : '#9a9aa8') + ';font-size:12.5px;font-weight:700;cursor:pointer;margin:0">' + c[1] + '</button>';
      }).join('');

    var html =
      '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">' +
      '<h2 style="margin:0;font-size:26px;display:flex;align-items:center;gap:10px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Facture <span style="font-size:13px;color:#888;font-weight:500">— YouLab (lead)</span></h2>' +
      '</div>' +
      '<p style="margin:0 0 16px;color:#888;font-size:13px">Gestion des revenus + dépenses de l&#39;agence (calculs en USD).</p>' +
      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px">' +
      '<select id="fx-month" style="width:auto;padding:10px 14px;background:#15151d;border:1px solid #2a2a35;color:#fff;border-radius:10px;font-size:13px;font-weight:700"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg> ' + monthOpts + '</select>' +
      '<div style="flex:1"></div>' +
      '<button id="fx-next" class="fx-btn2" style="padding:10px 16px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Démarrer mois suivant</button>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:16px">' + kpis + '</div>' +
      settleHtml + raBar +
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">' + mktChips +
      '<span style="width:1px;height:22px;background:#2a2a35;margin:0 4px"></span>' + chips +
      '<div style="flex:1"></div>' +
      '<button id="fx-settings" class="fx-btn2" style="padding:9px 15px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 3.6v2.4M12 18v2.4M20.4 12H18M6 12H3.6M18 6l-1.7 1.7M7.7 16.3L6 18M18 18l-1.7-1.7M7.7 7.7L6 6"/></svg>️ Paramètres</button>' +
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

  // Boîte du Règlement : part du bénéf + avances ligne par ligne + « À verser ».
  // Montants en money() (2 décimales) : l'addition doit tomber juste à l'œil.
  function settleBox(title, part, advLines, advTotal, payTotal, color) {
    var rows = advLines.length ? advLines.map(function (l) {
      return '<div style="display:flex;justify-content:space-between;gap:10px;font-size:11.5px;color:#9a9aa8;padding:2px 0">' +
        '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">+ ' + esc(l.label || 'Sans nom') + '</span>' +
        '<span style="color:#c0c0d5;flex-shrink:0">' + money(l.usd || 0) + '</span></div>';
    }).join('') : '<div style="font-size:11.5px;color:#55556a;padding:2px 0">Aucune avance ce mois</div>';
    return '<div style="background:#12121a;border:1px solid #23232e;border-radius:12px;padding:13px 15px">' +
      '<div style="font-size:12.5px;font-weight:800;margin-bottom:8px">' + title + '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:12px;color:#c0c0d5;padding:2px 0"><span>Part du bénéf</span><b>' + money(part) + '</b></div>' +
      '<div style="font-size:10px;color:#8a8a98;font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin:8px 0 3px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="5.4" width="18.8" height="13.2" rx="2.6"/><path d="M2.6 10h18.8"/></svg> Avancé de sa poche</div>' +
      '<div style="max-height:150px;overflow:auto">' + rows + '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:12px;color:#c0c0d5;border-top:1px dashed #2a2a35;margin-top:6px;padding-top:6px"><span>Total avances</span><b>' + money(advTotal) + '</b></div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;border-top:1px solid #2a2a35;margin-top:8px;padding-top:8px"><span style="font-weight:800">= À verser</span><b style="color:' + color + ';font-size:16px">' + money(payTotal) + '</b></div>' +
      '</div>';
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
      origin = '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.6a8 8 0 1 1-2.4-5.4"/><path d="M20 4v4.6h-4.6"/></svg> CA MyPuls · ' + esc(l.mypuls_model || '?') + ' <span style="color:#4ade80">(auto)</span>';
      /* Provenance réelle du montant : API officielle (exact, posts inclus, net)
         ou repli scraping (incomplet). Si repli, on dit POURQUOI. */
      var src = l.mp_src;
      if (src && src.api) {
        origin += ' <span style="color:#22c55e">net · API</span>';
        /* comment la créatrice a été retrouvée : tout ce qui n'est pas
           « pseudo exact » mérite une relecture à l'œil, une fois. */
        if (src.resolution && src.resolution !== 'pseudo exact') {
          origin += ' <span style="color:#64748b;font-size:10px">(' + esc(src.resolution) + ')</span>';
        }
      } else if (src) {
        /* token API présent mais on sert du scraping = montant NON FIABLE
           (brut, sans les posts, supposé EUR) -> rouge, pas ambre. */
        var col = src.error ? '#ef4444' : '#fbbf24';
        var lbl = src.error ? '⛔ MONTANT NON FIABLE — repli scraping'
                            : '⚠ scraping (brut, sans les posts)';
        origin += ' <span style="color:' + col + '" title="' + esc(src.why || '') + '">' + lbl + '</span>';
        if (src.why) {
          origin += '<div style="color:' + col + ';font-size:10px;margin-top:2px">' + esc(src.why) + '</div>';
        }
      } else if (l.cat === 'rev_of') {
        origin += ' <span style="color:#22c55e">net</span>';
      }
    } else if (l.form === 'mypuls_crm') {
      origin = '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Factures CRM MyPuls du mois <span style="color:#4ade80">(auto)</span>';
    } else if (l.form === 'va_clicks') {
      origin = '<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11V6.4a1.8 1.8 0 1 1 3.6 0V13"/><path d="M12.6 9.6a1.7 1.7 0 0 1 3.4 0v1.2"/><path d="M16 10.6a1.7 1.7 0 0 1 3.4 0v3.6a5.6 5.6 0 0 1-5.6 5.6h-1.6a5 5 0 0 1-3.6-1.6L5 14.4a1.8 1.8 0 0 1 2.6-2.4L9 13.4"/></svg> ' + (l.va_clicks || 0).toLocaleString('en-US') + ' clics éligibles × $0.07 <span style="color:#4ade80">(auto)</span>';
    } else {
      origin = (l.currency === 'EUR' ? '€' : '$') + (l.amount || 0).toFixed(2);
    }
    // badges
    var badges = '';
    var mb = monthBounds();
    badges += badge('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg>', 'Période : ' + frDate(mb[0]) + ' → ' + frDate(mb[1]) + ' ' + S.month.slice(0, 4));
    if (!isRev && l.paid_by === 'lead') {
      badges += '<span style="background:rgba(250,204,21,.10);border:1px solid rgba(250,204,21,.4);color:#facc15;font-size:10.5px;font-weight:800;padding:4px 10px;border-radius:8px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="5.4" width="18.8" height="13.2" rx="2.6"/><path d="M2.6 10h18.8"/></svg> avancée par ' + esc(leadName()) + ' (toi) — à te rembourser</span>';
    } else if (!isRev && String(l.paid_by || '').indexOf('assoc:') === 0) {
      badges += '<span style="background:rgba(129,140,248,.10);border:1px solid rgba(129,140,248,.4);color:#a5b4fc;font-size:10.5px;font-weight:800;padding:4px 10px;border-radius:8px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="5.4" width="18.8" height="13.2" rx="2.6"/><path d="M2.6 10h18.8"/></svg> avancée par ' + esc(l.paid_by.slice(6)) + ' — à lui rembourser</span>';
    }
    if (isRev && l.next_pay) {
      var days = Math.ceil((new Date(l.next_pay + 'T12:00:00') - new Date()) / 86400000);
      badges += badge('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4.4"/><circle cx="12" cy="12" r="1"/></svg>', 'Prochain paiement : ' + frDate(l.next_pay) + ' ' + l.next_pay.slice(0, 4) + (days >= 0 ? ' (dans ' + days + 'j)' : ''));
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
      ? '<a href="' + esc(l.link) + '" target="_blank" title="Ouvrir le lien de paiement" style="color:#818cf8;font-size:13px;text-decoration:none;padding:4px"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.2 13.8a3.8 3.8 0 0 0 5.6.4l2.6-2.6a3.8 3.8 0 0 0-5.4-5.4l-1.4 1.4"/><path d="M13.8 10.2a3.8 3.8 0 0 0-5.6-.4l-2.6 2.6a3.8 3.8 0 0 0 5.4 5.4l1.4-1.4"/></svg></a>'
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
      (isRev ? '+ ' : '− ') + money(l.usd || 0) + ' <span style="font-size:10px;color:#77778a;font-weight:600">/ mois</span>' +
      /* le brut ne se déduit du net que si la source EST nette (API) ; un montant
         issu du scraping est déjà brut -> pas de division par 0.8 trompeuse */
      eurHint(l.usd || 0, l.fee_pct,
        l.cat === 'rev_of' && (!l.mp_src || l.mp_src.api)) + '</span>' +
      '<button class="fx-edit" data-id="' + l.id + '" title="Modifier" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;padding:4px;margin:0">✎</button>' +
      '<button class="fx-del" data-id="' + l.id + '" title="Supprimer" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;padding:4px;margin:0"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.6 6.6h14.8M9.4 6.6V4.8h5.2v1.8M6.6 6.6l1 12.6h8.8l1-12.6"/></svg></button>' +
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
        var send = function (confirmDeps) {
          if (confirmDeps) fd.set('confirm', '1');
          fetch('/facture/line/delete', {method: 'POST', body: fd}).then(function (r) { return r.json(); })
            .then(function (j) {
              if (j.ok) {
                toast(j.relinked && j.relinked.length
                  ? ('Ligne supprimée · ' + j.relinked.length + ' paye(s) rebasculée(s) sur le total des revenus')
                  : 'Ligne supprimée');
                load(S.month);
              } else if (j.needs_confirm) {
                // Des payes en % s'appuient sur cette ligne : on demande AVANT
                // de casser leur base (sinon elles tombaient à $0 en silence).
                var _q = j.error + String.fromCharCode(10) + String.fromCharCode(10)
                        + 'Supprimer quand meme ? Ces payes seront recalculees sur le TOTAL des revenus.';
                if (confirm(_q)) send(true);
              } else {
                toast(j.error || 'Échec de la suppression');
              }
            });
        };
        send(false);
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
    var pctBaseOpts = '<option value="multi"' + (isMulti ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9.4 4.6h5.2v3a1.8 1.8 0 1 0 0 3.6v5.2h-3a1.8 1.8 0 1 1-3.6 0h-3V4.6z"/></svg> Plusieurs revenus (multi-sélection)</option>';
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
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4.6h6l-1 5.4 3.4 3.2H6.6L10 10z"/><path d="M12 13.2V19.4"/></svg> Libellé', '<input id="fxm-label" style="' + INP + '" placeholder="Ex: Revenue OF, VA Marc, Infloww…" value="' + esc(line.label || '') + '">') +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7.4" width="18" height="12.4" rx="2.4"/><path d="M8.6 7.4V5.6a1.8 1.8 0 0 1 1.8-1.8h3.2a1.8 1.8 0 0 1 1.8 1.8v1.8"/></svg> Type', '<select id="fxm-type" style="' + INP + '"><option value="exp"' + (line.type !== 'rev' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19.4V8.8"/><path d="M7.4 13.4L12 8.8l4.6 4.6"/><path d="M4.4 4.6h15.2"/></svg> Dépense (sortie)</option><option value="rev"' + (line.type === 'rev' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.6v10.6"/><path d="M7.4 10.6L12 15.2l4.6-4.6"/><path d="M4.4 19.4h15.2"/></svg> Revenu (entrée)</option></select>') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.4 7.4a2.4 2.4 0 0 1 2.4-2.4h3.2l2 2.4h7.6a2.4 2.4 0 0 1 2.4 2.4v7a2.4 2.4 0 0 1-2.4 2.4H5.8a2.4 2.4 0 0 1-2.4-2.4z"/></svg> Catégorie', '<select id="fxm-cat" style="' + INP + '">' + catOpts + '</select>') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.6v14.8M15.4 8a3 3 0 0 0-3-1.6c-1.9 0-3 1.1-3 2.4 0 3 6 1.7 6 4.7 0 1.3-1.1 2.5-3 2.5a3.2 3.2 0 0 1-3.1-1.7"/></svg> Forme', '<select id="fxm-form" style="' + INP + '"><option value="fixed"' + (line.form !== 'pct' && line.form !== 'mypuls' ? ' selected' : '') + '>▤ Montant fixe</option><option value="pct"' + (line.form === 'pct' ? ' selected' : '') + '>％ Pourcentage d&#39;un revenu</option><option value="mypuls"' + (line.form === 'mypuls' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.6a8 8 0 1 1-2.4-5.4"/><path d="M20 4v4.6h-4.6"/></svg> CA MyPuls (auto)</option><option value="mypuls_crm"' + (line.form === 'mypuls_crm' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2.4"/><path d="M8.6 8h6.8M8.6 12h6.8M8.6 16h4"/></svg> Frais CRM MyPuls (auto)</option><option value="va_clicks"' + (line.form === 'va_clicks' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11V6.4a1.8 1.8 0 1 1 3.6 0V13"/><path d="M12.6 9.6a1.7 1.7 0 0 1 3.4 0v1.2"/><path d="M16 10.6a1.7 1.7 0 0 1 3.4 0v3.6a5.6 5.6 0 0 1-5.6 5.6h-1.6a5 5 0 0 1-3.6-1.6L5 14.4a1.8 1.8 0 0 1 2.6-2.4L9 13.4"/></svg> Clics VA × 0.07$ (auto)</option></select>') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11.6a8 8 0 0 1 13.6-5.6"/><path d="M17.6 2.6V7h-4.4"/><path d="M20 12.4a8 8 0 0 1-13.6 5.6"/><path d="M6.4 21.4V17h4.4"/></svg> Fréquence', '<select id="fxm-freq" style="' + INP + '"><option value="monthly"' + (line.freq === 'monthly' ? ' selected' : '') + '>Mensuel</option><option value="biweekly"' + (line.freq === 'biweekly' ? ' selected' : '') + '>Quinzaine (×2)</option><option value="weekly"' + (line.freq === 'weekly' ? ' selected' : '') + '>Hebdo (×4)</option><option value="once"' + (line.freq === 'once' ? ' selected' : '') + '>Une seule fois</option></select>') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4a13 13 0 0 1 0 17.2a13 13 0 0 1 0-17.2z"/></svg> Marché', '<select id="fxm-market" style="' + INP + '"><option value="fr"' + (line.market === 'fr' ? ' selected' : '') + '>🇫🇷 France</option><option value="us"' + (line.market !== 'fr' ? ' selected' : '') + '>🇺🇸 US</option></select>') +
      '<div id="fxm-paidby-wrap" style="display:' + (line.type === 'rev' ? 'none' : 'block') + '">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="5.4" width="18.8" height="13.2" rx="2.6"/><path d="M2.6 10h18.8"/></svg> Payée par', '<select id="fxm-paidby" style="' + INP + '">' + paidByOpts(line) + '</select>') +
      '</div>' +
      '</div>' +
      '<div id="fxm-mypuls-wrap" style="display:' + (line.form === 'mypuls' ? 'block' : 'none') + '">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.6a8 8 0 1 1-2.4-5.4"/><path d="M20 4v4.6h-4.6"/></svg> Créatrice MyPuls <span style="color:#55556a;text-transform:none">(CA du mois récupéré automatiquement, converti en $)</span>',
        '<select id="fxm-mypulsmodel" style="' + INP + '">' +
        (line.mypuls_model ? '<option value="' + esc(line.mypuls_model) + '" selected>' + esc(line.mypuls_model) + '</option>' : '<option value="">⏳ Chargement des créatrices…</option>') +
        '</select>') +
      '</div>' +
      '<div id="fxm-fixed-wrap" style="display:' + (line.form && line.form !== 'fixed' ? 'none' : 'grid') + ';grid-template-columns:1fr 130px;gap:12px">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M12 6.8v10.4M14.7 9.4a2.7 2.7 0 0 0-2.7-1.4c-1.7 0-2.7 1-2.7 2.2 0 2.7 5.4 1.6 5.4 4.3 0 1.2-1 2.3-2.7 2.3a2.9 2.9 0 0 1-2.8-1.6"/></svg> Montant', '<input id="fxm-amount" type="number" step="0.01" min="0" style="' + INP + '" value="' + (line.amount || '') + '" placeholder="0.00">') +
      fld('Devise', '<select id="fxm-currency" style="' + INP + '"><option value="USD"' + (line.currency !== 'EUR' ? ' selected' : '') + '>$ USD</option><option value="EUR"' + (line.currency === 'EUR' ? ' selected' : '') + '>€ EUR</option></select>') +
      '</div>' +
      '<div id="fxm-pct-wrap" style="display:' + (line.form === 'pct' ? 'grid' : 'none') + ';grid-template-columns:130px 1fr;gap:12px">' +
      fld('％ Pourcent', '<input id="fxm-pct" type="number" step="0.1" min="0" max="100" style="' + INP + '" value="' + (line.pct || '') + '" placeholder="25">') +
      fld('… calculé sur', '<select id="fxm-pctof" style="' + INP + '">' + pctBaseOpts + '</select>') +
      '</div>' +
      '<div id="fxm-multibox" style="display:' + (line.form === 'pct' && isMulti ? 'block' : 'none') + '">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9.4 4.6h5.2v3a1.8 1.8 0 1 0 0 3.6v5.2h-3a1.8 1.8 0 1 1-3.6 0h-3V4.6z"/></svg> Revenus inclus dans la base (le % s&#39;applique à leur SOMME)',
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
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg> Date de début', '<input id="fxm-start" type="date" style="' + INP + '" value="' + esc(line.start || '') + '">') +
      fld('Date de fin <span style="color:#55556a;text-transform:none">(optionnel)</span>', '<input id="fxm-end" type="date" style="' + INP + '" value="' + esc(line.end || '') + '">') +
      '</div>' +
      '<div id="fxm-nextpay-wrap" style="display:' + (line.type === 'rev' ? 'block' : 'none') + '">' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4.4"/><circle cx="12" cy="12" r="1"/></svg> Prochain paiement (revenus)', '<input id="fxm-nextpay" type="date" style="' + INP + '" value="' + esc(line.next_pay || '') + '">') +
      '</div>' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.2 13.8a3.8 3.8 0 0 0 5.6.4l2.6-2.6a3.8 3.8 0 0 0-5.4-5.4l-1.4 1.4"/><path d="M13.8 10.2a3.8 3.8 0 0 0-5.6-.4l-2.6 2.6a3.8 3.8 0 0 0 5.4 5.4l1.4-1.4"/></svg> Lien de paiement (optionnel)', '<input id="fxm-link" style="' + INP + '" placeholder="https://infloww.com/billing — ouvert au moment de payer" value="' + esc(line.link || '') + '">') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg> Phases de paiement (optionnel) <button id="fxm-genphases" style="float:right;background:#1d1d28;border:1px solid #2c2c3d;color:#bbb;padding:4px 10px;border-radius:7px;font-size:11px;cursor:pointer;margin:0;text-transform:none;letter-spacing:0"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg> Générer auto</button>',
        '<div id="fxm-phases" style="display:flex;gap:6px;flex-wrap:wrap;min-height:34px;border:1px dashed #2c2c3d;border-radius:9px;padding:8px;font-size:11.5px;color:#66667a">' + renderPhaseChips(line.phases || []) + '</div>') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.6 19.4l.9-3.6L15.2 6.1a2 2 0 0 1 2.8 2.8L8.2 18.5z"/><path d="M4.6 19.4h14.8"/></svg> Notes (optionnel)', '<textarea id="fxm-notes" style="' + INP + ';min-height:60px;resize:vertical" placeholder="Ex: contrat 12 mois, paiement le 1er, etc.">' + esc(line.notes || '') + '</textarea>') +
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
      if (this.value === 'mypuls_crm' || this.value === 'va_clicks') document.getElementById('fxm-type').value = 'exp';
    });
    document.getElementById('fxm-pctof').addEventListener('change', function () {
      document.getElementById('fxm-multibox').style.display = this.value === 'multi' ? 'block' : 'none';
    });
    // Liste des créatrices MyPuls (pour la forme 'CA MyPuls auto')
    function loadMypulsModels(force) {
      var sel = document.getElementById('fxm-mypulsmodel');
      if (!sel) return;
      var curv = (sel.value || line.mypuls_model || '');
      fetch('/facture/mypuls_models' + (force ? '?refresh=1' : '')).then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) {
          if (!curv) sel.innerHTML = '<option value="">⚠️ ' + esc(j.error || 'MyPuls indisponible') + '</option>';
          return;
        }
        /* Chaque option porte son ID MyPuls en data-cid : à la sauvegarde on
           l'épingle sur la ligne, et le montant n'est plus jamais retrouvé par
           correspondance de nom (source du montant faux de Jessye/Khloe). */
        var creators = j.creators || (j.models || []).map(function (n) { return {name: n, id: 0}; });
        var names = creators.map(function (c) { return c.name; });
        var html = '<option value="">— choisir une créatrice —</option>';
        // La valeur enregistrée n'existe plus/pas dans MyPuls ? On la GARDE quand
        // même (sinon elle serait silencieusement perdue à la sauvegarde).
        if (curv && names.indexOf(curv) === -1) {
          html += '<option value="' + esc(curv) + '" data-cid="' + (line.mypuls_creator_id || 0) +
            '" selected>' + esc(curv) + ' — ⚠️ introuvable dans MyPuls</option>';
        }
        html += creators.map(function (c) {
          var tag = c.platform ? ' (' + esc(c.platform) + ')' : '';
          return '<option value="' + esc(c.name) + '" data-cid="' + (c.id || 0) + '"' +
            (c.name === curv ? ' selected' : '') + '>' + esc(c.name) + tag + '</option>';
        }).join('');
        sel.innerHTML = html;
      }).catch(function () {});
    }
    loadMypulsModels(false);
    // petit bouton ↻ pour forcer la resynchro de la liste (cache MyPuls : 5 min)
    (function () {
      var sel = document.getElementById('fxm-mypulsmodel');
      if (!sel || document.getElementById('fxm-mypuls-refresh')) return;
      var b = document.createElement('button');
      b.id = 'fxm-mypuls-refresh';
      b.type = 'button';
      b.textContent = '↻ Actualiser la liste';
      b.style.cssText = 'margin-top:6px;padding:5px 10px;background:#161a26;border:1px solid #2a2a2a;color:#9aa0b4;border-radius:7px;font-size:11.5px;cursor:pointer';
      b.addEventListener('click', function () {
        b.disabled = true; b.textContent = '↻ …';
        loadMypulsModels(true);
        setTimeout(function () { b.disabled = false; b.textContent = '↻ Actualiser la liste'; }, 1200);
      });
      sel.insertAdjacentElement('afterend', b);
    })();
    document.getElementById('fxm-type').addEventListener('change', function () {
      document.getElementById('fxm-nextpay-wrap').style.display = this.value === 'rev' ? 'block' : 'none';
      var pw = document.getElementById('fxm-paidby-wrap');
      if (pw) pw.style.display = this.value === 'rev' ? 'none' : 'block';
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
        paid_by: (document.getElementById('fxm-paidby') || {value: 'agence'}).value,
        mypuls_model: (document.getElementById('fxm-mypulsmodel') || {value: ''}).value,
        mypuls_creator_id: (function () {
          var s = document.getElementById('fxm-mypulsmodel');
          var o = s && s.options[s.selectedIndex];
          return (o && o.getAttribute('data-cid')) || 0;   // ID épinglé
        })(),
        /* pas de champ dans le modal -> on RENVOIE la valeur existante, sinon le
           serveur la remet à 0 et les frais plateforme (OF 20 %) disparaissent
           silencieusement à chaque modification de la ligne */
        fee_pct: line.fee_pct || 0,
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
    if (!phases.length) return 'Aucune phase. Clique <svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="5.2" width="17.2" height="15.4" rx="2.6"/><path d="M3.4 10h17.2M8.4 3.4v3.6M15.6 3.4v3.6"/></svg> Générer auto pour répartir le mois selon la fréquence.';
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
        var mk = (a.market === 'fr' || a.market === 'us') ? a.market : 'tous';
        return '<div style="display:flex;gap:8px;align-items:center;margin-bottom:7px">' +
          '<input data-ai="' + i + '" data-k="name" style="' + INP + ';flex:1" value="' + esc(a.name) + '" placeholder="Nom">' +
          '<input data-ai="' + i + '" data-k="pct" type="number" min="0" max="100" step="0.5" style="' + INP + ';width:80px" value="' + a.pct + '">' +
          '<span style="color:#77778a;font-size:12px">%</span>' +
          '<select data-ai="' + i + '" data-k="market" style="' + INP + ';width:118px">' +
          '<option value="tous"' + (mk === 'tous' ? ' selected' : '') + '><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4a13 13 0 0 1 0 17.2a13 13 0 0 1 0-17.2z"/></svg> Tous</option>' +
          '<option value="fr"' + (mk === 'fr' ? ' selected' : '') + '>🇫🇷 FR</option>' +
          '<option value="us"' + (mk === 'us' ? ' selected' : '') + '>🇺🇸 US</option></select>' +
          '<button data-adel="' + i + '" style="background:transparent;border:0;color:#77778a;cursor:pointer;font-size:13px;margin:0"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.6 6.6h14.8M9.4 6.6V4.8h5.2v1.8M6.6 6.6l1 12.6h8.8l1-12.6"/></svg></button></div>';
      }).join('');
    }
    modal(
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px">' +
      '<div style="font-size:17px;font-weight:800"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 3.6v2.4M12 18v2.4M20.4 12H18M6 12H3.6M18 6l-1.7 1.7M7.7 16.3L6 18M18 18l-1.7-1.7M7.7 7.7L6 6"/></svg>️ Paramètres de calcul</div>' +
      '<button class="fx-close" style="background:#1d1d28;border:0;color:#999;width:30px;height:30px;border-radius:8px;cursor:pointer;margin:0">✕</button></div>' +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.6 8.4h11.8M12.4 4.6l4 3.8-4 3.8"/><path d="M19.4 15.6H7.6M11.6 11.8l-4 3.8 4 3.8"/></svg> Taux EUR → USD', '<input id="fxs-rate" type="number" step="0.01" min="0.5" max="2" style="' + INP + '" value="' + ((st.eur_usd_raw ? st.eur_usd_raw : '')) + '" placeholder="auto (' + (st.eur_usd || '') + ')">') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.6h16M4.4 7l4 3.4L12 5l3.6 5.4 4-3.4-1.6 8.2H6z"/></svg> Ton nom (lead)', '<input id="fxs-lead" style="' + INP + '" value="' + esc(st.lead_name || 'Sama') + '" placeholder="Sama">') +
      fld('<svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.6" y="6" width="18.8" height="12" rx="2.4"/><circle cx="12" cy="12" r="2.8"/></svg> Jour de coupure paie chatters', '<input id="fxs-cutoff" type="number" min="1" max="28" style="' + INP + '" value="' + st.cutoff + '">') +
      '<div style="background:#0d0d16;border:1px solid #26263a;border-radius:9px;padding:10px 13px;font-size:11.5px;color:#8f8fa8;margin-bottom:16px">Découpe le mois en 2 périodes de paie : <b style="color:#c0c0d5">1 → ce jour</b> et <b style="color:#c0c0d5">jour+1 → fin du mois</b>. Défaut : 15 (1-15 / 16-fin).</div>' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">' +
      '<div style="font-size:13.5px;font-weight:800"><svg class="fic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8.6" r="3.1"/><path d="M3.6 19.2a5.6 5.6 0 0 1 10.8 0"/><path d="M16 6.5a3.1 3.1 0 0 1 0 6M17.4 14.6a5.4 5.4 0 0 1 3 4.6"/></svg> Associés (% du net)</div>' +
      '<button id="fxs-addassoc" class="fx-btn2" style="padding:6px 13px">+ Ajouter associé</button></div>' +
      '<div id="fxs-assoc">' + assocRows() + '</div>' +
      '<div style="background:#0d0d16;border:1px solid #26263a;border-radius:9px;padding:10px 13px;font-size:11.5px;color:#8f8fa8;margin:10px 0 18px">Le <b style="color:#c0c0d5">lead</b> récupère <b style="color:#c0c0d5">100% − associés</b>. Un associé rattaché à <b style="color:#c0c0d5">🇺🇸 US</b> (ou 🇫🇷 FR) ne touche que le net de <b style="color:#c0c0d5">ce marché</b> ; « Tous » = % du net global.</div>' +
      '<div style="display:flex;gap:10px;justify-content:flex-end">' +
      '<button class="fx-close" class="fx-btn2" style="padding:10px 18px">Annuler</button>' +
      '<button id="fxs-save" style="padding:10px 22px;background:linear-gradient(135deg,#818cf8,#a78bfa);border:0;color:#0d0d18;border-radius:10px;font-weight:800;cursor:pointer;margin:0">💾 Sauvegarder</button>' +
      '</div>');
    function rebind() {
      document.getElementById('fxs-assoc').innerHTML = assocRows();
      Array.prototype.forEach.call(document.querySelectorAll('#fxs-assoc [data-ai]'), function (inp) {
        var upd = function () {
          var a = assoc[parseInt(inp.dataset.ai, 10)];
          if (!a) return;
          if (inp.dataset.k === 'pct') a.pct = parseFloat(inp.value) || 0;
          else if (inp.dataset.k === 'market') a.market = inp.value;
          else a.name = inp.value;
        };
        inp.addEventListener('input', upd);
        inp.addEventListener('change', upd);
      });
      Array.prototype.forEach.call(document.querySelectorAll('#fxs-assoc [data-adel]'), function (b) {
        b.addEventListener('click', function () { assoc.splice(parseInt(b.dataset.adel, 10), 1); rebind(); });
      });
    }
    rebind();
    document.getElementById('fxs-addassoc').addEventListener('click', function () {
      assoc.push({name: '', pct: 10, market: 'tous'}); rebind();
    });
    document.getElementById('fxs-save').addEventListener('click', function () {
      var fd = new FormData();
      fd.set('eur_usd', document.getElementById('fxs-rate').value);
      fd.set('cutoff', document.getElementById('fxs-cutoff').value);
      fd.set('lead_name', document.getElementById('fxs-lead').value);
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
