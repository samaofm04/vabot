/* UI only: keep existing totals, payment handlers and stored crypto files.

   La liste des chatteurs est dessinee ICI, a partir du tableau que le serveur
   rend (ses cases de commission, de paie et de crypto sont DEPLACEES, jamais
   refaites : leurs formulaires et leurs routes restent ceux d'origine).
   Look des pages TRUST : rang, photo Discord, nom, puis les chiffres a droite
   avec un petit % de hausse ou de baisse par rapport a la periode d'avant. */
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
  table.classList.add('mp-revenue-table', 'mp-trust');
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
  var normalize = function (value) { return String(value || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').trim().toLowerCase(); };
  var cle = function (value) { return String(value || '').trim().toLowerCase(); };
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

  /* ---------- Net / Brut et $ / € : le reglage du tableau de bord ----------
     MyPuls rend le MYM en euros NETS et l'OnlyFans en dollars BRUTS. Avant,
     la page les affichait tels quels : un chatteur OnlyFans paraissait 25 %
     devant un chatteur MYM a vente egale. Ici chaque vente est ramenee a la
     base choisie (les memes frais que le tableau de bord), puis a la devise.
     LA PAIE N'EST PAS TOUCHEE : « A payer » garde son propre calcul. */
  var FRAIS = window.__mpFrais || {of:0.20, mym:0.26};
  function lire(nom) { try { return localStorage.getItem(nom); } catch (_e) { return null; } }
  function enBrut() { return lire('vabot_dash_mode') === 'gross'; }
  function enEuros() { return lire('vabot_dash_cur') === 'EUR'; }
  function taux() { return window.__mpEurToUsd || 1; }
  // Un montant dans la devise de la vente -> dollars, dans la base choisie.
  function base(montant, usd) {
    var a = Number(montant || 0);
    if (usd) return enBrut() ? a : a * (1 - FRAIS.of);
    return enBrut() ? a * taux() / (1 - FRAIS.mym) : a * taux();
  }
  function affiche(dollars) { return enEuros() ? dollars / taux() : dollars; }
  function ecrire(valeur, decimales) {
    var d = decimales === undefined ? 2 : decimales;
    return enEuros()
      ? valeur.toLocaleString('fr-FR', {minimumFractionDigits:d, maximumFractionDigits:d}) + ' €'
      : '$' + valeur.toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
  }
  function argent(dollars, decimales) { return ecrire(affiche(dollars), decimales); }
  // Pour le graphique « Revenus par modèle » (revenus_chart.js) : memes regles.
  window.mpRevenueBase = function (montant, usd) { return affiche(base(montant, usd)); };
  window.mpRevenueFormat = function (valeur) { return ecrire(Number(valeur || 0)); };
  function peindreBoutons() {
    document.querySelectorAll('.mp-fx-cur').forEach(function (b) { b.textContent = enEuros() ? '€ EUR' : '$ USD'; });
    document.querySelectorAll('.mp-fx-mode').forEach(function (b) {
      b.textContent = enBrut() ? 'Brut' : 'Net'; b.dataset.brut = enBrut() ? '1' : '0';
    });
    var explication = enBrut()
      ? 'Brut : ce que le fan a payé. OnlyFans : lu chez MyPuls. MYM : calculé (MyPuls ne donne que le net).'
      : 'Net : ce que la créatrice reçoit, frais de la plateforme retirés.';
    (section || host).querySelectorAll('.mypuls-stat[title]').forEach(function (s) { s.title = explication; });
  }
  window.mpFxToggle = function (quoi) {
    try {
      if (quoi === 'cur') localStorage.setItem('vabot_dash_cur', enEuros() ? 'USD' : 'EUR');
      else localStorage.setItem('vabot_dash_mode', enBrut() ? 'net' : 'gross');
    } catch (_e) {}
    // Le tableau de bord vit dans la meme page : il suit tout de suite.
    if (typeof window.fxApplyCur === 'function') { try { window.fxApplyCur(); } catch (_e2) {} }
    window.mpApplyMode();
  };
  window.mpApplyMode = function () {
    peindreBoutons();
    if (typeof window.mpRecompute === 'function') window.mpRecompute();
  };
  // Les boutons du tableau de bord changent le meme reglage : on suit.
  document.addEventListener('click', function (event) {
    if (event.target && event.target.closest && event.target.closest('#fx-cur-toggle,#fx-mode-toggle')) setTimeout(window.mpApplyMode, 0);
  });

  /* ---------- Les ventes, filtrees comme le reste de la page ---------- */
  function dansLeShift(heure, sh) {
    return heure >= 0 && (sh[0] <= sh[1] ? heure >= sh[0] && heure < sh[1] : heure >= sh[0] || heure < sh[1]);
  }
  function transactions(name) {
    var excluded = window.__mpExcluded || new Set(), sh = window.__mpShift;
    return (window.__mpTransactions || []).filter(function (t) {
      if ((name !== null && t.h !== name) || excluded.has(t.c)) return false;
      if (!sh) return true;
      return dansLeShift(typeof t.t === 'number' ? t.t : -1, sh);
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
  function nameCell(name, subtitle) {
    var cell = el('td'), person = el('div', 'mp-revenue-sale-person'), label = el('span');
    person.appendChild(avatar(name));
    label.appendChild(el('span', 'mp-revenue-sale-label', name || 'Modèle non indiqué'));
    if (subtitle) label.appendChild(el('span', 'mp-revenue-sale-type', subtitle));
    person.appendChild(label); cell.appendChild(person); return cell;
  }

  /* ---------- Les chiffres d'une ligne ---------- */
  // v ventes, p ventes PPV, t tips (dollars, base choisie) ; np PPV debloques.
  function sommer(txs) {
    var s = {v:0, p:0, t:0, np:0, n:txs.length};
    txs.forEach(function (x) {
      var b = base(x.a, !!x.u); s.v += b;
      if (x.k === 'p') { s.p += b; s.np++; } else if (x.k === 't') { s.t += b; }
    });
    return s;
  }
  // Le complement (periode d'avant, messages, presence) arrive apres la page.
  var complement = null, complementErreur = '';
  function shiftChoisi() {
    var sh = window.__mpShift;
    if (!sh || !complement || !complement.creneaux) return -1;
    for (var i = 0; i < complement.creneaux.length; i++) if (complement.creneaux[i][0] === sh[0] && complement.creneaux[i][1] === sh[1]) return i;
    return -2;   // un shift que la periode d'avant ne connait pas : pas de comparaison
  }
  // Ventes de la periode d'avant, sous les MEMES filtres. name null = tout le monde.
  function sommerAvant(name) {
    if (!complement || !complement.ventes_avant) return null;
    var excluded = window.__mpExcluded || new Set(), rang = shiftChoisi(), qui = name === null ? null : cle(name);
    if (rang === -2) return null;
    var s = {v:0, p:0, t:0, np:0, connu:false};
    complement.ventes_avant.forEach(function (l) {
      if (qui !== null && l[0] !== qui) return;
      s.connu = true;
      if (excluded.has(l[1]) || (window.__mpShift && l[2] !== rang)) return;
      s.v += base(l[4], !!l[3]); s.p += base(l[5], !!l[3]); s.t += base(l[6], !!l[3]); s.np += l[7];
    });
    return s;
  }
  // Messages et PPV envoyes. MyPuls ne les decoupe pas par heure : sous un
  // shift, on ne les affiche pas plutot que de montrer ceux de la journee.
  function sommerMessages(lignes, name) {
    if (!lignes || window.__mpShift) return null;
    var excluded = window.__mpExcluded || new Set(), qui = name === null ? null : cle(name), s = {m:0, e:0, connu:false};
    lignes.forEach(function (l) {
      if (qui !== null && l[0] !== qui) return;
      s.connu = true;
      if (l[1] !== '*' && excluded.has(l[1])) return;
      s.m += l[2]; s.e += l[3];
    });
    return s;
  }
  // Le petit % : hausse ou baisse par rapport a la periode d'avant.
  function evolution(maintenant, avant, nouveau) {
    var span = el('span', 'mp-ev');
    if (!complement) { span.textContent = complementErreur ? '—' : '…'; span.classList.add('mp-ev-plat'); return span; }
    if (avant === null || avant === undefined) { span.textContent = '—'; span.classList.add('mp-ev-plat'); return span; }
    if (nouveau) { span.textContent = 'nouveau'; span.classList.add('mp-ev-neuf'); return span; }
    if (!avant) {
      span.textContent = maintenant ? '0 avant' : '—';
      span.classList.add(maintenant ? 'mp-ev-neuf' : 'mp-ev-plat'); return span;
    }
    var e = 100 * (maintenant - avant) / avant;
    if (Math.abs(e) < 0.5) { span.textContent = '0 %'; span.classList.add('mp-ev-plat'); return span; }
    span.textContent = (e > 0 ? '+' : '−') + Math.abs(e).toFixed(0) + ' %';
    span.classList.add(e > 0 ? 'mp-ev-haut' : 'mp-ev-bas');
    return span;
  }
  function poser(cell, texte, maintenant, avant, nouveau) {
    cell.textContent = texte;
    if (arguments.length > 2) cell.appendChild(evolution(maintenant, avant, nouveau));
  }
  function nombre(n) { return Number(n || 0).toLocaleString('fr-FR'); }
  function pourcent(haut, bas, decimales) { return bas ? (100 * haut / bas).toFixed(decimales) + ' %' : '—'; }

  function updateAvatars(entry, txs) {
    var names = Array.from(new Set(txs.map(function (t) { return t.c; }).filter(Boolean)));
    entry.models.replaceChildren();
    names.slice(0, 4).forEach(function (name) { entry.models.appendChild(avatar(name)); });
    if (names.length > 4) entry.models.appendChild(el('span', 'mp-revenue-more', '+' + (names.length - 4)));
    if (!names.length) entry.models.appendChild(el('span', 'mp-revenue-more', '—'));
  }
  function closeEntry(entry) {
    entry.detail.hidden = true;
    entry.row.classList.remove('mp-row-open');
    entry.button.setAttribute('aria-expanded', 'false');
    if (entry.edit) entry.edit.style.display = 'none';
    if (openEntry === entry) openEntry = null;
  }
  function ouvrir(entry) {
    if (openEntry === entry) return;
    if (openEntry) closeEntry(openEntry);
    openEntry = entry; entry.detail.hidden = false; entry.row.classList.add('mp-row-open');
    entry.button.setAttribute('aria-expanded', 'true'); renderDetail(entry);
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
    (entry.mode === 'sales' ? ['Model et vente', 'Date / heure de Paris', 'Fan', 'Montant'] : ['Model', 'Ventes', 'Total']).forEach(function (label) { head.appendChild(el('th', '', label)); });
    if (entry.mode === 'sales') {
      txs.slice(0, entry.limit).forEach(function (t) {
        var row = body.insertRow(); row.appendChild(nameCell(t.c, t.y));
        row.appendChild(el('td', '', dateLabel(t.d)));
        row.appendChild(el('td', '', t.f || '—'));
        row.appendChild(el('td', 'mp-revenue-money', argent(base(t.a, !!t.u))));
      });
    } else {
      names.forEach(function (name) {
        var sales = txs.filter(function (t) { return (t.c || '') === name; }), row = body.insertRow();
        row.appendChild(nameCell(name)); row.appendChild(el('td', '', sales.length));
        row.appendChild(el('td', 'mp-revenue-money', argent(sommer(sales).v)));
      });
    }
    entry.panel.appendChild(ledger);
    if (entry.mode === 'sales' && txs.length > entry.limit) {
      var more = el('button', 'mp-revenue-load-more', 'Afficher les ' + Math.min(50, txs.length - entry.limit) + ' ventes suivantes (' + entry.limit + ' / ' + txs.length + ')');
      more.type = 'button'; more.onclick = function () { entry.limit += 50; renderDetail(entry); };
      entry.panel.appendChild(more);
    }
    var footer = el('p', 'mp-revenue-note', txs.length + ' ventes dans le journal · ');
    footer.appendChild(el('span', 'mp-revenue-money', argent(sommer(txs).v) + (enBrut() ? ' brut' : ' net'))); entry.panel.appendChild(footer);
    var observed = txs.reduce(function (sum, t) { return sum + Number(t.a || 0); }, 0);
    var reference = (window.__mpPerfCa || {})[entry.name];
    if (!(window.__mpExcluded && window.__mpExcluded.size) && !window.__mpShift && typeof reference === 'number' && Math.abs(reference - observed) > Math.max(1, reference * .05)) {
      entry.panel.appendChild(el('p', 'mp-revenue-note', 'Le journal disponible ne recoupe pas le CA total. Le CA et le calcul de paie restent ceux du tableau de performance. Le détail affiche les ventes effectivement reçues.'));
    }
  }

  /* ---------- La photo : le Discord relie au chatteur ---------- */
  var discord = window.__mpChatterExtra || {};
  function initiales(label) {
    var mots = String(label || '?').replace(/[^\p{L}\p{N} ]/gu, ' ').trim().split(/\s+/);
    var i = mots.length > 1 ? mots[0][0] + mots[1][0] : String(mots[0] || '?').slice(0, 2);
    return i.toUpperCase();
  }
  function teinte(label) {
    var h = 0, s = String(label || '');
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return h;
  }
  function peindrePhoto(entry) {
    var d = discord[entry.name] || {}, box = entry.photo, h = teinte(entry.label);
    box.replaceChildren(); box.className = 'mp-t-photo';
    box.style.setProperty('--mp-teinte', h);
    if (d.avatar) {
      var img = document.createElement('img');
      img.src = d.avatar; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      // Une photo qui ne charge pas retombe sur les initiales, jamais sur un trou.
      img.onerror = function () { box.replaceChildren(); box.classList.add('mp-t-initiales'); box.textContent = initiales(entry.label); box.appendChild(entry.point); };
      box.appendChild(img);
    } else {
      box.classList.add('mp-t-initiales'); box.textContent = initiales(entry.label);
    }
    box.appendChild(entry.point);
    if (entry.discordEtat) {
      entry.discordEtat.className = 'mp-t-discord-etat';
      if (!d.discord) entry.discordEtat.textContent = 'Aucun Discord relié : la ligne garde ses initiales.';
      else if (d.trouve) { entry.discordEtat.textContent = 'Relié à ' + (d.affiche || d.discord) + ' · photo à jour.'; entry.discordEtat.classList.add('mp-t-ok'); }
      else if (!d.verifiable) entry.discordEtat.textContent = d.par_id ? 'Identifiant enregistré : vérification chez Discord en cours.' : '@' + d.discord + ' enregistré. Bot Discord hors ligne : photo non vérifiable pour l’instant.';
      else if (d.par_id) { entry.discordEtat.textContent = 'Aucun compte Discord ne porte l’identifiant ' + d.discord + '. Vérifie les chiffres (clic droit sur son profil › Copier l’identifiant).'; entry.discordEtat.classList.add('mp-t-alerte'); }
      else {
        var ou = d.serveurs && d.serveurs.length ? ' Serveurs fouillés : ' + d.serveurs.join(', ') + '.' : '';
        entry.discordEtat.textContent = 'Aucun membre des serveurs que les bots voient ne porte « ' + d.discord + ' ».' + ou + ' Colle plutôt son identifiant Discord (clic droit sur son profil › Copier l’identifiant) : il marche sans serveur commun.';
        entry.discordEtat.classList.add('mp-t-alerte');
      }
    }
    if (entry.discordInput && document.activeElement !== entry.discordInput) entry.discordInput.value = d.discord || '';
    peindreSousLigne(entry);
  }
  function peindreSousLigne(entry) {
    var ligne = entry.sous; ligne.replaceChildren();
    var p = complement && complement.presence ? complement.presence[cle(entry.name)] : null;
    entry.point.hidden = !(p && p[0]);
    if (p && p[0]) ligne.appendChild(el('span', 'mp-t-enligne', 'en ligne'));
    else if (p && p[1]) ligne.appendChild(el('span', '', 'vu le ' + dateLabel(p[1]).replace(/\/\d{4}/, '')));
    var d = discord[entry.name] || {};
    // Pas de Discord : on propose de le relier. Un pseudo enregistre que le
    // bot ne trouve pas se VOIT aussi : sans ca la ligne restait en initiales
    // sans rien dire, et on croyait la photo en panne.
    if (!d.discord || (!d.trouve && d.verifiable)) {
      if (ligne.childNodes.length) ligne.appendChild(document.createTextNode(' · '));
      var plus = el('button', 'mp-t-plus' + (d.discord ? ' mp-t-plus-alerte' : ''), d.discord ? 'Discord introuvable' : '+ Discord'); plus.type = 'button';
      plus.setAttribute('aria-label', (d.discord ? 'Corriger le Discord de ' : 'Relier le Discord de ') + entry.label);
      plus.onclick = function () { ouvrir(entry); if (entry.discordInput) entry.discordInput.focus(); };
      ligne.appendChild(plus);
    }
  }
  // La liste des membres a choisir : lue une seule fois, au premier champ
  // ouvert. Refusee ou vide (bot hors ligne), la saisie reste libre.
  var membresDemandes = false;
  function chargerMembres() {
    if (membresDemandes) return;
    membresDemandes = true;
    fetch('/mypuls/chatters/membres_discord.json', {credentials:'same-origin'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        var liste = document.getElementById('mp-discord-membres');
        // `options` est du HTML deja echappe par le serveur (html_escape).
        if (liste && j && j.ok && j.options) liste.innerHTML = j.options;
        if (!j || !j.ok) return;
        // D'ou vient la liste, ou pourquoi elle est vide : dit sous le champ.
        var aide = j.serveur
          ? 'La liste propose les ' + j.nb + ' membres de « ' + j.serveur + ' ». Tu peux aussi coller un identifiant Discord.'
          : 'Aucun bot n\u2019est sur ton serveur de chatting : la liste est vide. Colle l\u2019identifiant Discord du chatteur (clic droit sur son profil › Copier l\u2019identifiant), ou invite le bot sur ce serveur depuis youl4b.com/version.';
        entries.forEach(function (entry) { if (entry.discordAide) entry.discordAide.textContent = aide; });
      })
      .catch(function () {});
  }
  function relierDiscord(entry) {
    var data = new FormData(); data.set('name', entry.name); data.set('discord', entry.discordInput.value || '');
    entry.discordBouton.disabled = true;
    fetch('/mypuls/chatter/set_discord', {method:'POST', body:data, credentials:'same-origin'})
      .then(function (r) { return r.json().catch(function () { return {ok:false, error:'Réponse illisible (HTTP ' + r.status + ')'}; }); })
      .then(function (j) {
        if (!j.ok) { entry.discordEtat.textContent = '✕ ' + (j.error || 'Enregistrement refusé'); entry.discordEtat.className = 'mp-t-discord-etat mp-t-alerte'; return; }
        if (j.discord) discord[entry.name] = j; else delete discord[entry.name];
        entry.discordInput.value = j.discord || '';     // tel qu'il est garde : sans arobase, en minuscules
        peindrePhoto(entry);
      })
      .catch(function (e) { entry.discordEtat.textContent = '✕ ' + e; entry.discordEtat.className = 'mp-t-discord-etat mp-t-alerte'; })
      .then(function () { entry.discordBouton.disabled = false; });
  }

  /* ---------- La commission : enregistree sans quitter la periode ----------
     Le formulaire d'origine s'envoyait seul au moindre changement et la page
     revenait sur la periode PAR DEFAUT, filtre perdu : on changeait le % d'un
     chatteur de la quinzaine, et on se retrouvait devant les 30 derniers
     jours, avec un « A payer » qui n'etait plus celui qu'on regardait.
     La route reste la meme ; seul le retour change : meme periode, meme filtre. */
  function memeEcran() {
    var bornes = String(window.__mpPeriodId || '').split('_'), u = new URL('/', location.href);
    u.searchParams.set('tab', 'revenus');
    if (bornes.length === 2) { u.searchParams.set('mp_start', bornes[0]); u.searchParams.set('mp_end', bornes[1]); }
    u.searchParams.set('mp_group', segment);
    var raccourci = new URLSearchParams(location.search).get('mp_period');
    if (raccourci) u.searchParams.set('mp_period', raccourci);
    return u.href;
  }
  function brancherCommission(cell) {
    var form = cell.querySelector('form[action*="set_pct"]'), champ = form && form.querySelector('input[name=pct]');
    if (!form || !champ) return;
    form.removeAttribute('onchange'); form.onchange = null;
    var enCours = false;
    function enregistrer() {
      if (enCours) return;
      enCours = true; cell.classList.add('mp-t-envoi');
      fetch(form.action, {method:'POST', body:new FormData(form), credentials:'same-origin'})
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); location.href = memeEcran(); })
        // Si l'envoi discret echoue, on retombe sur l'envoi d'origine : la
        // valeur est enregistree quand meme, au prix du retour par defaut.
        .catch(function () { enCours = false; cell.classList.remove('mp-t-envoi'); form.submit(); });
    }
    champ.addEventListener('change', enregistrer);
    form.addEventListener('submit', function (event) { event.preventDefault(); enregistrer(); });
  }

  /* ---------- L'adresse de paiement, en fin de ligne ---------- */
  function peindreAdresse(entry) {
    var c = (window.__mpCryptoData || {})[entry.name] || {}, cell = entry.adresse;
    cell.replaceChildren();
    var bouton = el('button', 'mp-t-adresse'); bouton.type = 'button';
    bouton.setAttribute('aria-label', 'Adresse de paiement de ' + entry.label);
    bouton.onclick = function () { ouvrir(entry); if (typeof window.mpToggleEdit === 'function' && (!entry.edit || entry.edit.style.display === 'none' || !entry.edit.style.display)) window.mpToggleEdit(entry.name); };
    if (c.type || c.address || c.has_screenshot) {
      if (c.type) bouton.appendChild(el('span', 'mp-t-crypto mp-t-crypto-' + String(c.type).toLowerCase(), c.type));
      var adr = String(c.address || '');
      bouton.appendChild(el('span', 'mp-t-adr', adr ? (adr.length > 14 ? adr.slice(0, 6) + '…' + adr.slice(-4) : adr) : 'capture enregistrée'));
      if (c.network) bouton.appendChild(el('span', 'mp-t-det', String(c.network).split('(')[0].trim()));
    } else {
      bouton.appendChild(el('span', 'mp-t-manque', 'à renseigner'));
    }
    cell.appendChild(bouton);
    entry.sansAdresse = !(c.type || c.address || c.has_screenshot);
  }

  /* ---------- Construction : une ligne par chatteur ---------- */
  var ENTETES = [['', ''], ['Chatteur', 'g'], ['Models', 'g'], ['Ventes', ''], ['Ventes PPV', ''], ['Tips', ''],
    ['Messages envoyés', ''], ['PPV envoyés', ''], ['Golden ratio', ''], ['PPV débloqués', ''], ['Taux de déblocage', ''],
    ['Commission', ''], ['À payer', ''], ['Payé', 'c'], ['Adresse', '']];
  var header = table.tHead && table.tHead.rows[0];
  if (header) {
    header.replaceChildren();
    ENTETES.forEach(function (h) { var th = el('th', h[1] ? 'mp-t-' + h[1] : '', h[0]); header.appendChild(th); });
    header.cells[8].title = 'PPV envoyés ÷ messages envoyés';
    header.cells[10].title = 'PPV débloqués ÷ PPV envoyés';
  }
  var corps = table.tBodies[0];
  Array.from(table.querySelectorAll('.mp-chatter-row')).forEach(function (row, index) {
    var cells = Array.from(row.cells), name = row.dataset.chatter || '';
    if (cells.length < 4) return;
    var orphan = row.classList.contains('mp-row-orphelin');
    var edit = row.nextElementSibling;
    if (!edit || !edit.classList.contains('mp-edit-row')) edit = null;
    var entry = {row:row, name:name, label:chatterLabel(name), edit:edit, mode:'sales', limit:50, orphan:orphan, ordre:index};
    entry.initialDisplay = row.style.display;
    entry.rang = el('td', 'mp-t-rang');
    // Colonne « Chatteur » : photo, nom (ouvre le detail), ligne grise dessous.
    var button = el('button', 'mp-revenue-toggle'); button.type = 'button';
    button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-label', 'Détail de ' + entry.label);
    button.appendChild(el('span', 'mp-revenue-name', orphan ? 'Ventes non attribuées' : entry.label));
    entry.button = button;
    entry.photo = el('span', 'mp-t-photo'); entry.point = el('i', 'mp-t-point'); entry.point.hidden = true;
    entry.sous = el('span', 'mp-t-det');
    var qui = el('div', 'mp-t-qui'), bloc = el('div');
    bloc.appendChild(button); bloc.appendChild(entry.sous);
    if (!orphan) qui.appendChild(entry.photo);
    qui.appendChild(bloc);
    cells[0].replaceChildren(qui); cells[0].className = 'mp-t-nom';
    var modelCell = el('td', 'mp-t-models'); entry.models = el('div', 'mp-revenue-models'); modelCell.appendChild(entry.models);
    // Les trois montants gardent leur classe : mpRecompute les reconnait.
    entry.cV = cells[1]; entry.cP = cells[2]; entry.cT = cells[3];
    [entry.cV, entry.cP, entry.cT].forEach(function (c) { c.removeAttribute('style'); });
    entry.cV.classList.add('mp-t-ventes');
    entry.cMsg = el('td'); entry.cEnv = el('td'); entry.cGold = el('td'); entry.cDeb = el('td'); entry.cTaux = el('td');
    entry.adresse = el('td', 'mp-t-fin');
    var crypto = el('div', 'mp-revenue-crypto'); crypto.appendChild(el('span', 'mp-revenue-crypto-label', 'Crypto'));
    var tdCom, tdPay, tdPaye;
    if (!orphan && cells.length >= 10) {
      tdCom = cells[5]; tdPay = cells[6]; tdPaye = cells[9];
      tdCom.classList.add('mp-t-com'); tdPay.classList.add('mp-t-payer'); tdPaye.classList.add('mp-t-c');
      brancherCommission(tdCom);
      tdPay.removeAttribute('style'); tdPaye.removeAttribute('style');
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
      // « Indetermine (Creatrice) » : des ventes, personne a payer.
      tdCom = el('td', '', '—'); tdPay = el('td', '', '—'); tdPaye = el('td', 'mp-t-c', '—');
      entry.sous.textContent = 'aucun chatteur associé · non payé';
      crypto.hidden = true; entry.adresse.textContent = '—';
    }
    entry.initialAmounts = [tdPay].filter(function (n) { return n.classList.contains('mp-cell-pay'); }).map(function (node) {
      return {node:node, text:node.textContent, color:node.style.color};
    });
    row.replaceChildren(entry.rang, cells[0], modelCell, entry.cV, entry.cP, entry.cT, entry.cMsg, entry.cEnv,
      entry.cGold, entry.cDeb, entry.cTaux, tdCom, tdPay, tdPaye, entry.adresse);
    var detail = el('tr', 'mp-revenue-details-row'); detail.hidden = true; detail.id = 'mp-revenue-detail-' + index;
    button.setAttribute('aria-controls', detail.id); entry.detail = detail;
    var detailCell = detail.insertCell(); detailCell.colSpan = ENTETES.length;
    if (!orphan) {
      // Le Discord du chatteur : on le choisit, sa photo s'affiche.
      var blocDiscord = el('form', 'mp-t-discord');
      blocDiscord.appendChild(el('span', 'mp-revenue-crypto-label', 'Discord'));
      entry.discordInput = el('input'); entry.discordInput.type = 'text'; entry.discordInput.maxLength = 40;
      entry.discordInput.placeholder = 'pseudo ou identifiant Discord'; entry.discordInput.setAttribute('list', 'mp-discord-membres');
      entry.discordInput.setAttribute('aria-label', 'Pseudo ou identifiant Discord de ' + entry.label); entry.discordInput.autocomplete = 'off';
      entry.discordInput.addEventListener('focus', chargerMembres);
      entry.discordBouton = el('button', 'mp-t-relier', 'Relier'); entry.discordBouton.type = 'submit';
      entry.discordEtat = el('span', 'mp-t-discord-etat');
      entry.discordAide = el('span', 'mp-t-discord-aide');
      blocDiscord.appendChild(entry.discordInput); blocDiscord.appendChild(entry.discordBouton); blocDiscord.appendChild(entry.discordEtat);
      blocDiscord.appendChild(entry.discordAide);
      blocDiscord.onsubmit = function (event) { event.preventDefault(); relierDiscord(entry); };
      detailCell.appendChild(blocDiscord);
    }
    detailCell.appendChild(crypto);
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
    button.onclick = function () { if (openEntry === entry) closeEntry(entry); else ouvrir(entry); };
    if (!orphan) { peindrePhoto(entry); peindreAdresse(entry); }
    entries.push(entry);
  });

  // La ligne « Total », en tete : la somme de ce qui est affiche.
  var total = null;
  if (corps && entries.length) {
    total = {row:el('tr', 'mp-t-total')};
    ['rang', 'nom', 'models', 'cV', 'cP', 'cT', 'cMsg', 'cEnv', 'cGold', 'cDeb', 'cTaux', 'com', 'pay', 'paye', 'adresse'].forEach(function (k) {
      total[k] = el('td'); total.row.appendChild(total[k]);
    });
    total.nom.className = 'mp-t-nom'; total.cV.className = 'mp-t-ventes'; total.pay.className = 'mp-t-payer';
    total.paye.className = 'mp-t-c'; total.adresse.className = 'mp-t-fin';
    corps.insertBefore(total.row, corps.firstChild);
  }

  /* ---------- Le tri ---------- */
  var TRIS = [['v', 'Ventes'], ['p', 'Ventes PPV'], ['t', 'Tips'], ['m', 'Messages'], ['g', 'Golden ratio'],
    ['d', 'Taux de déblocage'], ['pay', 'À payer'], ['nom', 'Nom']];
  var tri = 'v', barreTri = el('nav', 'mp-t-tris');
  barreTri.setAttribute('aria-label', 'Tri des chatteurs');
  barreTri.appendChild(el('span', 'mp-t-lib', 'Trier'));
  TRIS.forEach(function (t) {
    var b = el('button', '', t[1]); b.type = 'button'; b.dataset.tri = t[0];
    b.onclick = function () { tri = t[0]; ranger(); };
    barreTri.appendChild(b);
  });
  table.before(barreTri);
  var avis = el('p', 'mp-t-avis'); avis.hidden = true; table.after(avis);
  function valeurDeTri(entry) {
    var c = entry.chiffres || {};
    if (tri === 'nom') return entry.label.toLowerCase();
    if (tri === 'pay') return parseFloat(String((entry.row.querySelector('.mp-cell-pay') || {}).textContent || '').replace(/[^0-9.-]/g, '')) || 0;
    return Number(c[tri] || 0);
  }
  function ranger() {
    if (!corps) return;
    barreTri.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.tri === tri)); });
    var ordre = entries.slice().sort(function (a, b) {
      if (a.orphan !== b.orphan) return a.orphan ? 1 : -1;      // les ventes sans chatteur, toujours en bas
      var x = valeurDeTri(a), y = valeurDeTri(b);
      if (tri === 'nom') return x < y ? -1 : x > y ? 1 : 0;
      return (y - x) || (a.ordre - b.ordre);
    });
    // On ne deplace les lignes QUE si l'ordre change : re-poser une ligne
    // retire le curseur du champ qu'on est en train de remplir (commission,
    // Discord), et ce remplissage tombe pile quand le complement arrive.
    var enPlace = Array.from(corps.querySelectorAll('.mp-chatter-row'));
    var bouge = enPlace.length !== ordre.length || ordre.some(function (entry, i) { return enPlace[i] !== entry.row; });
    var rang = 0;
    ordre.forEach(function (entry) {
      if (bouge) {
        corps.appendChild(entry.row); corps.appendChild(entry.detail);
        if (entry.edit) corps.appendChild(entry.edit);
      }
      entry.rang.textContent = entry.orphan || entry.row.style.display === 'none' ? '' : String(++rang);
    });
  }

  /* ---------- Remplissage : apres chaque filtre, chaque bascule ---------- */
  function refresh() {
    var messagesOk = complement && complement.messages, sousShift = !!window.__mpShift;
    var tous = sommer(transactions(null)), tousAvant = sommerAvant(null), visibles = 0, payes = 0, sansAdresse = 0;
    var totMsg = {m:0, e:0}, totMsgAvant = {m:0, e:0}, aDesMessages = false;
    entries.forEach(function (entry) {
      var txs = transactions(entry.name), s = sommer(txs), avant = sommerAvant(entry.name);
      var msg = entry.orphan ? null : sommerMessages(complement && complement.messages, entry.name);
      var msgAvant = entry.orphan ? null : sommerMessages(complement && complement.messages_avant, entry.name);
      // « nouveau » : aucune trace de lui sur la periode d'avant, ni vente ni message.
      var nouveau = !!complement && !entry.orphan && avant !== null && !avant.connu && !(msgAvant && msgAvant.connu);
      updateAvatars(entry, txs);
      poser(entry.cV, argent(s.v), s.v, avant && avant.v, nouveau);
      poser(entry.cP, argent(s.p), s.p, avant && avant.p, nouveau);
      poser(entry.cT, argent(s.t), s.t, avant && avant.t, nouveau);
      entry.chiffres = {v:s.v, p:s.p, t:s.t, m:0, g:0, d:0};
      if (entry.orphan) {
        [entry.cMsg, entry.cEnv, entry.cGold, entry.cDeb, entry.cTaux].forEach(function (c) { c.textContent = '—'; });
      } else {
        if (msg) {
          poser(entry.cMsg, nombre(msg.m), msg.m, msgAvant && msgAvant.m, nouveau);
          poser(entry.cEnv, nombre(msg.e), msg.e, msgAvant && msgAvant.e, nouveau);
          entry.cGold.textContent = pourcent(msg.e, msg.m, 2);
          entry.cTaux.textContent = pourcent(s.np, msg.e, 1);
          entry.chiffres.m = msg.m; entry.chiffres.g = msg.m ? msg.e / msg.m : 0; entry.chiffres.d = msg.e ? s.np / msg.e : 0;
          if (entry.row.style.display !== 'none') {
            aDesMessages = true; totMsg.m += msg.m; totMsg.e += msg.e;
            if (msgAvant) { totMsgAvant.m += msgAvant.m; totMsgAvant.e += msgAvant.e; }
          }
        } else {
          var vide = !complement && !complementErreur ? '…' : '—';
          [entry.cMsg, entry.cEnv, entry.cGold, entry.cTaux].forEach(function (c) { c.textContent = vide; });
        }
        poser(entry.cDeb, nombre(s.np), s.np, avant && avant.np, nouveau);
        if (entry.row.style.display !== 'none') {
          visibles++;
          if ((entry.row.querySelector('.mp-paid-cb') || {}).checked) payes++;
          if (entry.sansAdresse) sansAdresse++;
        }
      }
      if (entry.row.style.display === 'none') closeEntry(entry);
      else if (openEntry === entry) renderDetail(entry);
    });
    if (total) {
      total.nom.replaceChildren(el('b', '', 'Total'), el('span', 'mp-t-det', visibles + ' chatteur' + (visibles > 1 ? 's' : '')));
      poser(total.cV, argent(tous.v), tous.v, tousAvant && tousAvant.v, false);
      poser(total.cP, argent(tous.p), tous.p, tousAvant && tousAvant.p, false);
      poser(total.cT, argent(tous.t), tous.t, tousAvant && tousAvant.t, false);
      if (aDesMessages) {
        poser(total.cMsg, nombre(totMsg.m), totMsg.m, totMsgAvant.m, false);
        poser(total.cEnv, nombre(totMsg.e), totMsg.e, totMsgAvant.e, false);
        total.cGold.textContent = pourcent(totMsg.e, totMsg.m, 2);
        total.cTaux.textContent = pourcent(tous.np, totMsg.e, 1);
      } else {
        [total.cMsg, total.cEnv, total.cGold, total.cTaux].forEach(function (c) { c.textContent = !complement && !complementErreur ? '…' : '—'; });
      }
      poser(total.cDeb, nombre(tous.np), tous.np, tousAvant && tousAvant.np, false);
      var aPayer = (section || host).querySelector('[data-mp-stat="total_pay_usd"]');
      total.pay.textContent = aPayer ? aPayer.textContent : '—';
      total.paye.textContent = payes + ' / ' + visibles;
      total.adresse.replaceChildren(sansAdresse ? el('span', 'mp-t-manque', sansAdresse + ' à renseigner') : document.createTextNode(''));
    }
    // Le bandeau du haut suit la meme base et la meme devise que la liste.
    [['ca_total', tous.v, '+'], ['ca_ppv', tous.p, ''], ['ca_tips', tous.t, '']].forEach(function (b) {
      var gros = (section || host).querySelector('[data-mp-stat="' + b[0] + '"]');
      if (gros) gros.textContent = b[2] + argent(b[1], 0);
      var petit = (section || host).querySelector('[data-mp-stat-eur="' + b[0] + '"]');
      if (petit) petit.textContent = '≈ ' + (enEuros() ? '$' + Math.round(b[1]).toLocaleString('en-US') : Math.round(b[1] / taux()).toLocaleString('fr-FR') + ' €');
    });
    // Ce qui manque est DIT, jamais tu.
    var notes = [];
    if (complementErreur) notes.push('Comparaison et messages indisponibles : ' + complementErreur);
    if (complement && complement.erreurs && complement.erreurs.length) notes.push(complement.erreurs.join(' · '));
    if (messagesOk && sousShift) notes.push('Sous un shift, les messages et PPV envoyés ne sont pas affichés : MyPuls ne les découpe pas par heure.');
    if (complement && complement.notes && complement.notes.length) notes.push(complement.notes.join(' · '));
    else if (messagesOk && !sousShift && complement.messages_par_compte === false) notes.push('Messages et PPV envoyés : tous comptes confondus.');
    if (complement && complement.avant && !complementErreur) notes.unshift('Le petit % compare au ' + dateLabel(complement.avant[0] + 'T00:00').slice(0, 10) + ' → ' + dateLabel(complement.avant[1] + 'T00:00').slice(0, 10) + '. Golden ratio = PPV envoyés ÷ messages envoyés. Taux de déblocage = PPV débloqués ÷ PPV envoyés.');
    avis.textContent = notes.join(' — '); avis.hidden = !notes.length;
    ranger();
    refreshTransactions();
  }
  function refreshTransactions() {
    var target = document.querySelector('#mp-tab-tx table tbody');
    if (!target) return;
    var txs = transactions(null).slice().sort(function (a,b) { return timestamp(b) - timestamp(a); });
    var orphan = section.querySelector('[data-mp-stat="non_attribue"]');
    if (orphan) {
      // Meme base et meme devise que le reste : avant, des euros MYM et des
      // dollars OnlyFans s'additionnaient ici sous un « € ».
      var amount = txs.reduce(function (sum,t) { return sum + (((window.__mpCryptoData || {})[t.h] || {}).non_attribue ? base(t.a, !!t.u) : 0); },0);
      orphan.textContent = 'dont ' + argent(amount) + ' non attribué — non payé';
      orphan.hidden = amount <= 0;
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
  // Cocher « Payé » met a jour le compte de la ligne Total.
  table.addEventListener('change', function (event) {
    if (event.target && event.target.classList && event.target.classList.contains('mp-paid-cb')) setTimeout(refresh, 0);
  });
  peindreBoutons();
  applySegment(false);

  // Le complement : lu apres la page. S'il echoue, les ventes et la paie
  // restent exactes ; seules les colonnes de comparaison affichent « — ».
  if (window.__mpComplementUrl) {
    fetch(window.__mpComplementUrl, {credentials:'same-origin'})
      .then(function (r) { return r.json().catch(function () { return {ok:false, erreurs:['Réponse illisible (HTTP ' + r.status + ')']}; }); })
      .then(function (j) {
        if (j && j.ok) complement = j; else complementErreur = ((j && j.erreurs) || ['réponse vide']).join(' · ');
        // Les photos Discord reverifiees pendant le complement : on repeint.
        if (j && j.discord) Object.keys(j.discord).forEach(function (nom) {
          discord[nom] = j.discord[nom];
          var e = entries.find(function (x) { return x.name === nom; });
          if (e && !e.orphan) peindrePhoto(e);
        });
      })
      .catch(function (e) { complementErreur = String(e); })
      .then(function () { entries.forEach(function (entry) { if (!entry.orphan) peindreSousLigne(entry); }); refresh(); });
  } else {
    complementErreur = 'adresse du complément absente';
  }
})();
