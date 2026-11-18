/* Revenue chart: one-day bars, daily curves, existing model/shift filters. */
(function () {
  'use strict';
  window.mpRevenueChartSeries = function (source, txs, sh, now) {
    var hourly = source.days.length === 1;
    var labels = hourly ? Array.from({length:24}, function (_, h) { return String(h).padStart(2,'0') + 'h'; }) : source.labels.slice();
    var buckets = {};
    if (hourly || sh) txs.forEach(function (t) {
      var h = t.t;
      if (!t.day || h < 0 || (sh && !(sh[0] <= sh[1] ? h >= sh[0] && h < sh[1] : h >= sh[0] || h < sh[1]))) return;
      if (hourly && t.day !== source.days[0]) return;
      var key = JSON.stringify([t.c, hourly ? h : t.day]);
      buckets[key] = (buckets[key] || 0) + Math.round(Number(t.a || 0) * 100);
    });
    var parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(now || new Date());
    var clock = {}; parts.forEach(function (p) { clock[p.type] = p.value; });
    var today = clock.year + '-' + clock.month + '-' + clock.day;
    return {labels:labels, hourly:hourly, values:source.datasets.map(function (ds) {
      if (!hourly && !sh) return ds.data.slice();
      return (hourly ? labels : source.days).map(function (day, h) {
        if (hourly && source.days[0] === today && h > Number(clock.hour)) return null;
        return (buckets[JSON.stringify([ds.label, hourly ? h : day])] || 0) / 100;
      });
    })};
  };
  window.mpInitRevenueChart = function (source) {
    var canvas = document.getElementById('mypuls-chart');
    if (!canvas) return;
    var card = canvas.closest('.mp-revenue-chart'), chart = null, attempts = 0;
    var singleDay = source.days.length === 1;
    // MyM vend en euros, OnlyFans en dollars : chaque courbe est ramenee en
    // dollars au taux de la paie, sinon tout s'affichait suivi d'un « € ».
    var usd = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:2});
    function enUsd(ds, v) {
      if (v == null) return null;
      // Net / Brut et $ / € : les memes regles que la liste des chatteurs
      // (revenus_ui.js). Sans elles, la bascule changeait les chiffres de la
      // liste et laissait les courbes sur l'ancienne base.
      if (typeof window.mpRevenueBase === 'function') return window.mpRevenueBase(Number(v), ds.devise !== 'EUR');
      return Number(v) * (ds.devise === 'EUR' ? (window.__mpEurToUsd || 1) : 1);
    }
    function ecrire(v) { return typeof window.mpRevenueFormat === 'function' ? window.mpRevenueFormat(v) : usd.format(v); }
    var status = card.querySelector('.mp-revenue-chart-status');
    var note = card.querySelector('.mp-revenue-chart-note');
    var buttons = Array.from(card.querySelectorAll('[data-mp-legend]'));
    var headerAvatars = card.querySelector('.mp-revenue-chart-avatars');
    var avatarMap = window.__mpCreatorAvatars || {};
    var tooltip = document.createElement('div');
    tooltip.className = 'mp-revenue-chart-tooltip'; tooltip.hidden = true;
    canvas.parentElement.appendChild(tooltip);

    function modelPhoto(name) {
      var image = document.createElement('img'); image.alt = name;
      image.src = avatarMap[name] || '';
      image.onerror = function () { image.hidden = true; };
      return image;
    }
    function externalTooltip(context) {
      var tip = context.tooltip;
      if (!tip.opacity || !tip.dataPoints || !tip.dataPoints.length) { tooltip.hidden = true; return; }
      tooltip.replaceChildren();
      var title = document.createElement('small'); title.textContent = (tip.title || []).join(' · '); tooltip.appendChild(title);
      tip.dataPoints.forEach(function (point) {
        var line = document.createElement('div'); line.className = 'mp-revenue-chart-tooltip-model';
        if (avatarMap[point.dataset.label]) { var photo = modelPhoto(point.dataset.label); photo.style.border = '2px solid ' + point.dataset.borderColor; line.appendChild(photo); }
        var name = document.createElement('span'); name.textContent = point.dataset.label; line.appendChild(name);
        var amount = document.createElement('strong'); amount.textContent = ecrire(point.parsed.y); line.appendChild(amount);
        tooltip.appendChild(line);
      });
      tooltip.hidden = false;
      tooltip.style.left = Math.max(4, Math.min(tip.caretX + 12, canvas.clientWidth - tooltip.offsetWidth - 4)) + 'px';
      tooltip.style.top = Math.max(4, tip.caretY - tooltip.offsetHeight - 12) + 'px';
    }

    /* LE THEME DE LA COURBE DE L'ACCUEIL (« Revenus par jour »), demande du
       18/11/2026 : trait epais et arrondi, points blancs cercles de la couleur
       de la courbe, grille en pointilles, leger fondu dessous. Seule la
       couleur change d'une model a l'autre.
       L'ancienne courbe etait « monotone » : entre deux jours a zero elle
       filait a plat puis montait a pic -- « des trucs tres horizontaux,
       verticaux », ses mots. La tension simple arrondit comme a l'accueil ;
       Chart.js garde les points de controle dans la zone du graphique, la
       courbe ne passe donc pas sous zero. */
    var nbPoints = singleDay ? 24 : source.days.length;
    // Sur une longue periode, des centaines de points blancs feraient une
    // bouillie : le trait s'affine et les points s'effacent.
    var trait = nbPoints <= 16 ? {w:3.6, r:4.6} : nbPoints <= 35 ? {w:3.2, r:3.8}
      : nbPoints <= 70 ? {w:2.6, r:2.6} : nbPoints <= 140 ? {w:2.2, r:0} : {w:1.7, r:0};
    function voile(hex, a) {
      var n = parseInt(String(hex || '').replace('#', ''), 16);
      if (isNaN(n)) return 'transparent';
      return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
    }
    function fondu(couleur) {
      return function (ctx) {
        var zone = ctx.chart.chartArea;
        if (!zone) return 'transparent';
        var g = ctx.chart.ctx.createLinearGradient(0, zone.top, 0, zone.bottom);
        g.addColorStop(0, voile(couleur, .16)); g.addColorStop(1, voile(couleur, .02));
        return g;
      };
    }
    function theme() {
      var css = getComputedStyle(card);
      return {text:css.getPropertyValue('--mpr-text').trim(), muted:css.getPropertyValue('--mpr-muted').trim(),
        surface:css.getPropertyValue('--mpr-surface').trim(), border:css.getPropertyValue('--mpr-border').trim()};
    }
    function refresh() {
      if (!chart) return;
      var sh = window.__mpShift, excluded = window.__mpExcluded || new Set();
      var series = window.mpRevenueChartSeries(source, window.__mpTransactions || [], sh);
      chart.data.labels = series.labels;
      var total = 0, active = 0;
      if (headerAvatars) headerAvatars.replaceChildren();
      chart.data.datasets.forEach(function (ds, i) {
        ds.data = series.values[i].map(function (v) { return enUsd(ds, v); });
        var visible = !excluded.has(ds.label);
        chart.setDatasetVisibility(i, visible);
        var amount = ds.data.reduce(function (sum, n) { return sum + Number(n || 0); }, 0);
        if (visible) {
          total += amount; active++;
        }
        var inSegment = typeof window.mpRevenueInSegment !== 'function' || window.mpRevenueInSegment(ds.label);
        if (headerAvatars && avatarMap[ds.label] && inSegment) {
          var avatar = document.createElement('button'); avatar.type = 'button';
          avatar.setAttribute('aria-label', (visible ? 'Masquer ' : 'Afficher ') + ds.label);
          avatar.setAttribute('aria-pressed', String(visible)); avatar.title = ds.label;
          avatar.style.setProperty('--mp-series-color',ds.borderColor);
          var photo = modelPhoto(ds.label);
          // Une photo qui ne vient pas : la pastille entiere se retire, au
          // lieu de laisser un rond vide dans la rangee.
          photo.addEventListener('error', function () { avatar.hidden = true; });
          avatar.appendChild(photo);
          // La plateforme, en petit sous la photo, comme sur MyPuls.
          var seg = (window.__mpCreatorSegments || {})[ds.label];
          if (seg) {
            var plateforme = document.createElement('i');
            plateforme.className = 'mp-revenue-plat mp-revenue-plat-' + (seg === 'mym' ? 'mym' : 'of');
            plateforme.textContent = seg === 'mym' ? 'mym' : 'OF';
            plateforme.setAttribute('aria-hidden', 'true');
            avatar.appendChild(plateforme);
          }
          avatar.onclick = function () { window.mpToggleCreator(ds.label); };
          headerAvatars.appendChild(avatar);
        }
        var button = buttons.find(function (b) { return b.dataset.mpLegend === ds.label; });
        if (button) {
          button.hidden = typeof window.mpRevenueInSegment === 'function' && !window.mpRevenueInSegment(ds.label);
          button.setAttribute('aria-pressed', String(visible));
          button.classList.toggle('mp-creator-excluded', !visible);
          button.querySelector('.mp-revenue-model-total').textContent = ecrire(amount);
        }
      });
      // Beaucoup de courbes a la fois : le trait s'affine un peu, sinon dix
      // traits epais se recouvrent. Une ou deux models : le trait de l'accueil.
      var epaisseur = trait.w * (active > 6 ? .78 : 1);
      chart.data.datasets.forEach(function (ds) { ds.borderWidth = epaisseur; });
      status.textContent = active + ' modèle' + (active > 1 ? 's' : '') + ' affiché' + (active > 1 ? 's' : '');
      note.textContent = !active ? 'Aucun modèle sélectionné. Clique sur un modèle pour afficher ses revenus.'
        : total === 0 ? 'Aucune vente sur ce créneau pour les modèles sélectionnés.'
        : (singleDay ? 'Revenus heure par heure' : 'Revenus par jour') + ' · heure de Paris' + (sh ? ' · shift ' + sh[0] + 'h–' + sh[1] + 'h' : '');
      card.dataset.chartTotal = total.toFixed(2);
      card.dataset.chartKind = 'line';
      card.dataset.chartGranularity = singleDay ? 'hour' : 'day';
      canvas.setAttribute('aria-label', note.textContent + '. Total affiché : ' + ecrire(total) + '.');
      var colors = theme(), opt = chart.options;
      opt.scales.y.ticks.color = opt.scales.x.ticks.color = colors.muted;
      opt.plugins.tooltip.backgroundColor = colors.surface;
      opt.plugins.tooltip.titleColor = colors.text;
      opt.plugins.tooltip.bodyColor = colors.muted;
      opt.plugins.tooltip.borderColor = colors.border;
      chart.update('none');
      tooltip.hidden = true;
    }
    window.mpRefreshRevenueChart = refresh;
    function init() {
      if (typeof Chart === 'undefined') {
        if (++attempts < 100) { setTimeout(init, 100); return; }
        note.textContent = 'Le graphique n’a pas pu se charger. Les montants par modèle restent disponibles ci-dessus.';
        return;
      }
      if (window.__mypulsChart) window.__mypulsChart.destroy();
      chart = window.__mypulsChart = new Chart(canvas, {
        type:'line',
        data:{labels:source.labels.slice(), datasets:source.datasets.map(function (ds) {
          return {label:ds.label, devise:ds.devise, data:ds.data.map(function (v) { return enUsd(ds, v); }), borderColor:ds.borderColor,
            backgroundColor:fondu(ds.borderColor),
            borderWidth:trait.w, borderCapStyle:'round', borderJoinStyle:'round', fill:'origin',
            tension:.35, clip:8,
            // Pas de point sur un jour a zero : avec dix models, la ligne du
            // bas devenait un chapelet de points blancs qui ne disaient rien.
            pointRadius:function (ctx) { return ctx.parsed && ctx.parsed.y ? trait.r : 0; },
            pointHoverRadius:trait.r ? trait.r + 1.6 : 5,
            pointBackgroundColor:'#fff', pointHoverBackgroundColor:'#fff',
            pointBorderColor:ds.borderColor, pointBorderWidth:1.8, pointHoverBorderWidth:2.5};
        })},
        options:{responsive:true, maintainAspectRatio:false, animation:false,
          layout:{padding:{top:6,right:8}},
          interaction:{mode:'index',intersect:false},
          plugins:{legend:{display:false}, tooltip:{enabled:false,external:externalTooltip,borderWidth:1,padding:12,
            callbacks:{label:function (ctx) { return ctx.dataset.label + ' : ' + ecrire(ctx.parsed.y); }}}},
          scales:{y:{beginAtZero:true,border:{display:false,dash:[4,3]},grid:{color:'rgba(136,136,136,.32)',lineWidth:.9},
              ticks:{maxTicksLimit:5,padding:10,font:{size:12.5},callback:function (v) { return ecrire(v); }}},
            x:{grid:{display:false},border:{display:false},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:10,padding:8,font:{size:12.5}}}}
        }
      });
      refresh();
      new MutationObserver(refresh).observe(document.body, {attributes:true,attributeFilter:['class','data-theme']});
    }
    init();
  };
})();
