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
    var money = new Intl.NumberFormat('fr-FR', {maximumFractionDigits:2});
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
        var amount = document.createElement('strong'); amount.textContent = money.format(point.parsed.y) + ' €'; line.appendChild(amount);
        tooltip.appendChild(line);
      });
      tooltip.hidden = false;
      tooltip.style.left = Math.max(4, Math.min(tip.caretX + 12, canvas.clientWidth - tooltip.offsetWidth - 4)) + 'px';
      tooltip.style.top = Math.max(4, tip.caretY - tooltip.offsetHeight - 12) + 'px';
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
        ds.data = series.values[i];
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
          avatar.appendChild(modelPhoto(ds.label)); avatar.onclick = function () { window.mpToggleCreator(ds.label); };
          headerAvatars.appendChild(avatar);
        }
        var button = buttons.find(function (b) { return b.dataset.mpLegend === ds.label; });
        if (button) {
          button.hidden = typeof window.mpRevenueInSegment === 'function' && !window.mpRevenueInSegment(ds.label);
          button.setAttribute('aria-pressed', String(visible));
          button.classList.toggle('mp-creator-excluded', !visible);
          button.querySelector('.mp-revenue-model-total').textContent = money.format(amount) + ' €';
        }
      });
      status.textContent = active + ' modèle' + (active > 1 ? 's' : '') + ' affiché' + (active > 1 ? 's' : '');
      note.textContent = !active ? 'Aucun modèle sélectionné. Clique sur un modèle pour afficher ses revenus.'
        : total === 0 ? 'Aucune vente sur ce créneau pour les modèles sélectionnés.'
        : (singleDay ? 'Revenus heure par heure' : 'Revenus par jour') + ' · heure de Paris' + (sh ? ' · shift ' + sh[0] + 'h–' + sh[1] + 'h' : '');
      card.dataset.chartTotal = total.toFixed(2);
      card.dataset.chartKind = 'line';
      card.dataset.chartGranularity = singleDay ? 'hour' : 'day';
      canvas.setAttribute('aria-label', note.textContent + '. Total affiché : ' + money.format(total) + ' euros.');
      var colors = theme(), opt = chart.options;
      opt.scales.y.grid.color = colors.border;
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
          return {label:ds.label, data:ds.data.slice(), borderColor:ds.borderColor,
            backgroundColor:ds.backgroundColor,
            borderWidth:2, borderCapStyle:'round', borderJoinStyle:'round', fill:false,
            tension:.4, cubicInterpolationMode:'monotone', pointRadius:2.5, pointHoverRadius:5};
        })},
        options:{responsive:true, maintainAspectRatio:false, animation:false,
          interaction:{mode:'index',intersect:false},
          plugins:{legend:{display:false}, tooltip:{enabled:false,external:externalTooltip,borderWidth:1,padding:12,
            callbacks:{label:function (ctx) { return ctx.dataset.label + ' : ' + money.format(ctx.parsed.y) + ' €'; }}}},
          scales:{y:{beginAtZero:true,border:{display:false},ticks:{maxTicksLimit:5,callback:function (v) { return money.format(v) + ' €'; }}},
            x:{grid:{display:false},border:{display:false},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:8}}}
        }
      });
      refresh();
      new MutationObserver(refresh).observe(document.body, {attributes:true,attributeFilter:['class','data-theme']});
    }
    init();
  };
})();
