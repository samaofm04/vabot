/* Onglets « Managers » et « Mini-boss » de la page Revenus chatteurs.

   Demande du proprietaire (18/11/2026), sur une maquette qu'il a validee :
   a cote de Chatteurs et Transactions, la paie de ses managers (un pourcentage
   sur les ventes des models qu'ils surveillent, shift par shift) et de ses
   mini-boss (un pourcentage sur tout un perimetre). Pour un manager, un CARRE :
   une ligne par model, une colonne par shift, on coche ce qu'il surveille.

   RIEN N'EST DANS LA PAGE : elle est gardee en memoire et servie a tous les
   roles. Tout arrive par /mypuls/managers.json, qui ne repond qu'aux acces
   complets. Refuse, ce script ne pose aucun onglet.

   LES CHIFFRES DES LIGNES VIENNENT DU SERVEUR (revenus_managers.du). Ici, on
   ne fait qu'additionner des cases deja calculees pour l'APERCU pendant
   qu'on coche ; apres « Enregistrer », la ligne reprend le chiffre du serveur. */
(function () {
  'use strict';
  var adresse = window.__mpManagersUrl;
  var barre = document.querySelector('.mypuls-tabs');
  var apres = document.getElementById('mp-tab-tx');
  if (!adresse || !barre || !apres) return;

  var ROLES = {
    manager: {onglet:'Managers', un:'un manager', pluriel:'managers', titre:'Manager', portee:'Surveille', ca:'CA surveillé',
      aide:'Même base que les chatteurs : MYM net, OnlyFans brut · suit la période choisie en haut'},
    miniboss: {onglet:'Mini-boss', un:'un mini-boss', pluriel:'mini-boss', titre:'Mini-boss', portee:'Périmètre', ca:'CA du périmètre',
      aide:'Un pourcentage sur tout le CA d’un périmètre, tous shifts confondus · même base que les chatteurs'}
  };
  var SEGMENTS = [['mym','MYM','mym'], ['of_fr','OF FR','of'], ['of_us','OF US','of'], ['','Autres','of']];
  var PORTEES = [['tout','Tout'], ['mym','MYM'], ['of','OnlyFans'], ['choix','Choisir…']];
  var COULEURS = ['#f97341','#3b82f6','#22c55e','#a855f7','#ec4899','#06b6d4','#eab308','#ef4444','#14b8a6','#8b5cf6'];

  var data = null;                       // la reponse de managers.json
  var ouvert = {manager:null, miniboss:null};   // l'id de la fiche ouverte, par onglet
  var brouillons = {};                   // les fiches en cours de reglage, par id
  var panneaux = {}, boutons = {};
  var periode = (function () {
    var q = new URLSearchParams(adresse.split('?')[1] || '');
    return {start:q.get('start') || '', end:q.get('end') || ''};
  })();

  /* ---------- petits outils ---------- */
  function el(tag, cls, texte) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }
  function usd(v, d) {
    var k = d === undefined ? 2 : d;
    return '$' + Number(v || 0).toLocaleString('en-US', {minimumFractionDigits:k, maximumFractionDigits:k});
  }
  function pct(v) { return String(Math.round(Number(v || 0) * 100) / 100).replace('.', ','); }
  function lirePct(texte) {
    var x = parseFloat(String(texte || '').replace(',', '.'));
    return isFinite(x) && x >= 0 && x <= 100 ? x : null;
  }
  function creneau(i) { var c = data.creneaux[i] || [0, 0]; return c[0] + 'h → ' + c[1] + 'h'; }
  function lignes() { return data.matrice.lignes; }
  function rond(nom, image, rang, taille) {
    var r = el('span', 'mpm-rond' + (taille ? ' mpm-rond-' + taille : ''));
    r.style.setProperty('--mpm-c', COULEURS[Math.abs(rang || 0) % COULEURS.length]);
    var lettres = String(nom || '?').replace(/[^0-9A-Za-zÀ-ÿ]/g, '').slice(0, 2).toUpperCase() || '?';
    r.appendChild(document.createTextNode(lettres));
    if (image) {
      var img = el('img'); img.alt = ''; img.loading = 'lazy'; img.src = image;
      // Une photo qui ne vient pas : les initiales restent, pas une icone cassee.
      img.onerror = function () { img.remove(); };
      r.appendChild(img);
    }
    return r;
  }
  function poster(chemin, corps) {
    return fetch(chemin, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(corps)})
      .then(function (r) { return r.json().catch(function () { return {ok:false, erreur:'Réponse illisible (HTTP ' + r.status + ')'}; }); });
  }
  function deRole(role) { return data.personnes.filter(function (p) { return p.role === role; }); }
  function modelsDuSegment(seg) {
    return data.matrice.ordre.filter(function (cle) { return (lignes()[cle].segment || '') === seg; });
  }

  /* ---------- le calcul de l'apercu (memes regles que revenus_managers.du) ---------- */
  function dansLaPortee(fiche, cle) {
    var seg = lignes()[cle].segment || '';
    if (fiche.portee === 'mym') return seg === 'mym';
    if (fiche.portee === 'of') return seg === 'of_fr' || seg === 'of_us';
    if (fiche.portee === 'choix') return (fiche.models || []).indexOf(cle) >= 0;
    return true;
  }
  function calcul(fiche) {
    var ca = 0, sans = 0, cases = 0, models = 0;
    if (fiche.role === 'miniboss') {
      data.matrice.ordre.forEach(function (cle) {
        if (!dansLaPortee(fiche, cle)) return;
        var l = lignes()[cle]; ca += l.total; models++;
        l.sans_chatteur.forEach(function (x) { sans += x; });
      });
    } else {
      Object.keys(fiche.cases || {}).forEach(function (cle) {
        var shifts = fiche.cases[cle] || [], l = lignes()[cle];
        cases += shifts.length; models++;
        if (l) shifts.forEach(function (s) { ca += l.shifts[s]; sans += l.sans_chatteur[s]; });
      });
    }
    return {ca:ca, a_payer:ca * Number(fiche.pct || 0) / 100, nb_cases:cases, nb_models:models, sans_chatteur:sans};
  }
  // Qui d'autre surveille cette case : dit dans le carre, avant de payer.
  function autresSur(fiche, cle, s) {
    return deRole('manager').filter(function (p) {
      return p.id !== fiche.id && ((p.cases || {})[cle] || []).indexOf(s) >= 0;
    }).map(function (p) { return p.nom; });
  }

  /* ---------- le resume d'une ligne ---------- */
  function shiftsEnClair(shifts) {
    if (shifts.length === data.creneaux.length) return '24 h';
    return shifts.map(creneau).join(' · ');
  }
  function resumeManager(fiche) {
    var boite = el('div', 'mpm-puces'), cases = fiche.cases || {}, reste = 0, posees = 0;
    function puce(titre, detail) {
      if (posees >= 4) { reste++; return; }
      var p = el('span', 'mpm-puce'); p.appendChild(el('b', '', titre)); p.appendChild(document.createTextNode(detail));
      boite.appendChild(p); posees++;
    }
    SEGMENTS.forEach(function (seg) {
      var tous = modelsDuSegment(seg[0]), coches = tous.filter(function (c) { return (cases[c] || []).length; });
      if (!coches.length) return;
      var premier = (cases[coches[0]] || []).join(',');
      var pareil = coches.length === tous.length && tous.length > 1
        && coches.every(function (c) { return (cases[c] || []).join(',') === premier; });
      if (pareil) { puce(seg[1], shiftsEnClair(cases[coches[0]])); return; }
      coches.forEach(function (c) { puce(lignes()[c].nom, shiftsEnClair(cases[c])); });
    });
    // Une model cochee que la periode ne connait plus (compte retire de MyPuls) : dite, pas tue.
    var perdues = Object.keys(cases).filter(function (c) { return !lignes()[c]; }).length;
    if (reste) boite.appendChild(el('span', 'mpm-puce mpm-puce-plus', '+ ' + reste));
    if (perdues) boite.appendChild(el('span', 'mpm-puce mpm-alerte', perdues + ' model' + (perdues > 1 ? 's' : '') + ' introuvable' + (perdues > 1 ? 's' : '')));
    if (!posees && !perdues) boite.appendChild(el('span', 'mpm-manque', 'rien de coché'));
    return boite;
  }
  function resumeMiniboss(fiche) {
    var boite = el('div', 'mpm-portee');
    PORTEES.forEach(function (p) { boite.appendChild(el('span', fiche.portee === p[0] ? 'mpm-on' : '', p[1])); });
    return boite;
  }
  function peindreAdresse(cible, fiche) {
    cible.replaceChildren();
    if (!fiche.crypto_address) { cible.appendChild(el('span', 'mpm-manque', 'à renseigner')); return; }
    if (fiche.crypto_type) {
      var t = el('span', 'mpm-crypto', fiche.crypto_type); t.dataset.type = fiche.crypto_type; cible.appendChild(t);
    }
    var a = String(fiche.crypto_address);
    var court = el('span', 'mpm-adr', a.length > 16 ? a.slice(0, 6) + '…' + a.slice(-4) : a);
    court.title = a + (fiche.crypto_network ? ' · ' + fiche.crypto_network : '');
    cible.appendChild(court);
  }

  /* ---------- le carre d'un manager ---------- */
  function carre(fiche, repeindre) {
    var g = el('div', 'mpm-carre');
    g.appendChild(el('div', 'mpm-coin'));
    data.creneaux.forEach(function (_c, s) {
      var total = 0; data.matrice.ordre.forEach(function (cle) { total += lignes()[cle].shifts[s]; });
      var t = el('button', 'mpm-tete-shift'); t.type = 'button'; t.title = 'Cocher ou décocher toute la colonne';
      t.appendChild(el('b', '', creneau(s))); t.appendChild(el('span', '', usd(total, 0)));
      t.onclick = function () {
        var cles = data.matrice.ordre, tout = cles.every(function (c) { return (fiche.cases[c] || []).indexOf(s) >= 0; });
        cles.forEach(function (c) { basculer(fiche, c, s, !tout); });
        repeindre();
      };
      g.appendChild(t);
    });
    SEGMENTS.forEach(function (seg) {
      var cles = modelsDuSegment(seg[0]);
      if (!cles.length) return;
      var nb = 0; cles.forEach(function (c) { nb += (fiche.cases[c] || []).length; });
      var tete = el('div', 'mpm-groupe');
      tete.appendChild(el('span', 'mpm-plat mpm-plat-' + seg[2], seg[1]));
      var tout = el('button', 'mpm-tout' + (nb ? ' mpm-on' : ''), nb ? 'tout décocher' : 'tout cocher'); tout.type = 'button';
      tout.onclick = function () {
        cles.forEach(function (c) { data.creneaux.forEach(function (_x, s) { basculer(fiche, c, s, !nb); }); });
        repeindre();
      };
      tete.appendChild(tout); g.appendChild(tete);
      cles.forEach(function (cle, i) {
        var l = lignes()[cle];
        var nom = el('button', 'mpm-model'); nom.type = 'button'; nom.title = 'Cocher ou décocher toute la ligne';
        nom.appendChild(rond(l.nom, (window.__mpCreatorAvatars || {})[l.nom], i + 3, 'petit'));
        nom.appendChild(el('b', '', l.nom));
        nom.onclick = function () {
          var plein = (fiche.cases[cle] || []).length === data.creneaux.length;
          data.creneaux.forEach(function (_x, s) { basculer(fiche, cle, s, !plein); });
          repeindre();
        };
        g.appendChild(nom);
        data.creneaux.forEach(function (_c, s) {
          var on = (fiche.cases[cle] || []).indexOf(s) >= 0, v = l.shifts[s];
          var c = el('button', 'mpm-case' + (on ? ' mpm-on' : '')); c.type = 'button';
          c.setAttribute('aria-pressed', String(on));
          c.setAttribute('aria-label', l.nom + ', ' + creneau(s));
          c.appendChild(el('b', '', usd(v, 0)));
          c.appendChild(el('span', '', on ? pct(fiche.pct) + ' % → ' + usd(v * Number(fiche.pct || 0) / 100) : '—'));
          var autres = autresSur(fiche, cle, s);
          if (autres.length) {
            var badge = el('em', '', '+ ' + (autres.length > 1 ? autres.length + ' autres' : autres[0]));
            badge.title = 'Aussi surveillé par ' + autres.join(', ');
            c.appendChild(badge);
          }
          if (on) c.appendChild(el('u', '', '✓'));
          c.onclick = function () { basculer(fiche, cle, s, !on); repeindre(); };
          g.appendChild(c);
        });
      });
    });
    return g;
  }
  function basculer(fiche, cle, s, coche) {
    var liste = (fiche.cases[cle] || []).filter(function (x) { return x !== s; });
    if (coche) liste.push(s);
    liste.sort(function (a, b) { return a - b; });
    if (liste.length) fiche.cases[cle] = liste; else delete fiche.cases[cle];
    fiche.modifie = true;
  }

  /* ---------- le perimetre d'un mini-boss ---------- */
  function perimetre(fiche, repeindre) {
    var boite = el('div', 'mpm-perimetre');
    var choix = el('div', 'mpm-portee mpm-portee-choix');
    PORTEES.forEach(function (p) {
      var b = el('button', fiche.portee === p[0] ? 'mpm-on' : '', p[1]); b.type = 'button';
      b.onclick = function () {
        // « Choisir… » part de ce qui etait dans le perimetre : on retire, on n'a pas tout a recocher.
        if (p[0] === 'choix' && fiche.portee !== 'choix') fiche.models = data.matrice.ordre.filter(function (c) { return dansLaPortee(fiche, c); });
        fiche.portee = p[0]; fiche.modifie = true; repeindre();
      };
      choix.appendChild(b);
    });
    boite.appendChild(choix);
    var liste = el('div', 'mpm-models');
    data.matrice.ordre.forEach(function (cle, i) {
      var l = lignes()[cle], dedans = dansLaPortee(fiche, cle);
      if (fiche.portee !== 'choix' && !dedans) return;
      var b = el('button', 'mpm-model-choix' + (dedans ? ' mpm-on' : '')); b.type = 'button';
      b.disabled = fiche.portee !== 'choix';
      b.appendChild(rond(l.nom, (window.__mpCreatorAvatars || {})[l.nom], i + 3, 'petit'));
      var t = el('span'); t.appendChild(el('b', '', l.nom)); t.appendChild(el('small', '', usd(l.total, 0)));
      b.appendChild(t);
      if (dedans) b.appendChild(el('u', '', '✓'));
      b.onclick = function () {
        var m = (fiche.models || []).filter(function (c) { return c !== cle; });
        if (!dedans) m.push(cle);
        fiche.models = m; fiche.modifie = true; repeindre();
      };
      liste.appendChild(b);
    });
    boite.appendChild(liste);
    return boite;
  }

  /* ---------- le panneau de reglage (a droite) ---------- */
  function champ(libelle, noeud) {
    var c = el('label', 'mpm-champ'); c.appendChild(el('small', '', libelle)); c.appendChild(noeud); return c;
  }
  function reglages(role, fiche, repeindre, peindreChiffres) {
    var boite = el('div', 'mpm-reglages');
    var nom = el('input'); nom.type = 'text'; nom.value = fiche.nom || ''; nom.placeholder = 'Son nom'; nom.maxLength = 60;
    nom.oninput = function () { fiche.nom = nom.value; fiche.modifie = true; };
    boite.appendChild(champ('Nom', nom));

    var dc = el('input'); dc.type = 'text'; dc.value = fiche.discord || ''; dc.placeholder = 'pseudo ou identifiant';
    dc.setAttribute('list', 'mp-discord-membres'); dc.autocomplete = 'off';
    dc.oninput = function () { fiche.discord = dc.value; fiche.modifie = true; };
    dc.onfocus = chargerMembres;
    var dcChamp = champ('Discord (pour sa photo)', dc);
    if (fiche.discord && fiche.discord_verifiable && !fiche.discord_trouve) dcChamp.appendChild(el('span', 'mpm-alerte mpm-mini', 'Introuvable sur le serveur de chatting'));
    boite.appendChild(dcChamp);

    var com = el('span', 'mpm-pct mpm-pct-grand');
    var comIn = el('input'); comIn.type = 'text'; comIn.inputMode = 'decimal'; comIn.value = pct(fiche.pct);
    comIn.setAttribute('aria-label', 'Commission en pourcentage');
    comIn.oninput = function () {
      var x = lirePct(comIn.value); com.classList.toggle('mpm-faux', x === null);
      if (x === null) return;
      fiche.pct = x; fiche.modifie = true; peindreChiffres(true);
    };
    com.appendChild(comIn); com.appendChild(el('i', '', '%'));
    boite.appendChild(champ('Commission', com));

    var chiffres = el('div', 'mpm-chiffres'); boite.appendChild(chiffres);
    boite.appendChild(el('hr'));

    var type = el('select'), reseau = el('select'), adr = el('input');
    [''].concat(Object.keys(data.cryptos || {})).forEach(function (t) {
      var o = el('option', '', t || '—'); o.value = t; if (t === (fiche.crypto_type || '')) o.selected = true; type.appendChild(o);
    });
    function reseaux() {
      reseau.replaceChildren();
      [''].concat((data.cryptos || {})[type.value] || []).forEach(function (r) {
        var o = el('option', '', r || '—'); o.value = r; if (r === (fiche.crypto_network || '')) o.selected = true; reseau.appendChild(o);
      });
    }
    reseaux();
    type.onchange = function () { fiche.crypto_type = type.value; fiche.crypto_network = ''; fiche.modifie = true; reseaux(); };
    reseau.onchange = function () { fiche.crypto_network = reseau.value; fiche.modifie = true; };
    adr.type = 'text'; adr.value = fiche.crypto_address || ''; adr.placeholder = 'Adresse de paiement'; adr.spellcheck = false;
    adr.oninput = function () { fiche.crypto_address = adr.value; fiche.modifie = true; };
    var deux = el('div', 'mpm-deux'); deux.appendChild(champ('Crypto', type)); deux.appendChild(champ('Réseau', reseau));
    boite.appendChild(deux); boite.appendChild(champ('Adresse', adr));

    var etat = el('div', 'mpm-etat'); etat.hidden = true; boite.appendChild(etat);
    var ok = el('button', 'mpm-btn mpm-btn-plein', 'Enregistrer'); ok.type = 'button';
    ok.onclick = function () {
      if (lirePct(comIn.value) === null) { etat.textContent = '✕ Pourcentage illisible (entre 0 et 100)'; etat.hidden = false; return; }
      ok.disabled = true; etat.hidden = true;
      var envoi = {role:role, nom:fiche.nom, pct:fiche.pct, discord:fiche.discord || '',
        crypto_type:fiche.crypto_type || '', crypto_network:fiche.crypto_network || '', crypto_address:fiche.crypto_address || ''};
      if (role === 'manager') envoi.cases = fiche.cases; else { envoi.portee = fiche.portee; envoi.models = fiche.models || []; }
      if (!fiche.nouveau) envoi.id = fiche.id;
      poster('/mypuls/managers/enregistrer', {fiche:envoi, start:periode.start, end:periode.end})
        .then(function (j) {
          if (!j.ok) { etat.textContent = '✕ ' + (j.erreur || 'Enregistrement refusé'); etat.hidden = false; return; }
          delete brouillons[fiche.id];
          var i = data.personnes.findIndex(function (p) { return p.id === j.personne.id; });
          if (i >= 0) data.personnes[i] = j.personne; else data.personnes.push(j.personne);
          ouvert[role] = j.personne.id;
          peindreTout();
        })
        .catch(function (e) { etat.textContent = '✕ ' + e; etat.hidden = false; })
        .then(function () { ok.disabled = false; });
    };
    boite.appendChild(ok);
    var bas = el('div', 'mpm-bas');
    var fermer = el('button', 'mpm-lien', fiche.nouveau ? 'Annuler' : 'Fermer'); fermer.type = 'button';
    fermer.onclick = function () { if (fiche.nouveau) delete brouillons[fiche.id]; ouvert[role] = null; peindre(role); };
    bas.appendChild(fermer);
    if (!fiche.nouveau) {
      var retirer = el('button', 'mpm-lien mpm-lien-rouge', 'Retirer de la liste'); retirer.type = 'button';
      retirer.onclick = function () {
        if (!window.confirm('Retirer ' + (fiche.nom || 'cette personne') + ' de la liste ? Sa fiche est gardée de côté, rien n’est effacé.')) return;
        poster('/mypuls/managers/retirer', {id:fiche.id}).then(function (j) {
          if (!j.ok) { etat.textContent = '✕ ' + (j.erreur || 'Refusé'); etat.hidden = false; return; }
          data.personnes = data.personnes.filter(function (p) { return p.id !== fiche.id; });
          delete brouillons[fiche.id]; ouvert[role] = null; peindreTout();
        });
      };
      bas.appendChild(retirer);
    }
    boite.appendChild(bas);
    return {boite:boite, chiffres:chiffres};
  }

  /* ---------- une fiche ouverte ---------- */
  function detail(role, fiche) {
    var boite = el('div', 'mpm-detail'), gauche = el('div', 'mpm-gauche');
    var zone = el('div');
    var r = reglages(role, fiche, repeindre, peindreChiffres);
    function peindreChiffres(avecZone) {
      var c = calcul(fiche);
      r.chiffres.replaceChildren();
      r.chiffres.appendChild(el('small', '', ROLES[role].ca)); r.chiffres.appendChild(el('div', 'mpm-gros', usd(c.ca)));
      r.chiffres.appendChild(el('small', '', 'À payer')); r.chiffres.appendChild(el('div', 'mpm-gros mpm-vert', usd(c.a_payer)));
      // Sur quoi il est paye : la part que MyPuls ne rattache a aucun chatteur est DITE.
      if (c.sans_chatteur > 0.005) r.chiffres.appendChild(el('p', 'mpm-note', 'dont ' + usd(c.sans_chatteur) + ' de ventes sans chatteur attribué'));
      if (role === 'manager') {
        var partagees = 0, avec = {};
        Object.keys(fiche.cases || {}).forEach(function (cle) {
          fiche.cases[cle].forEach(function (s) {
            var a = autresSur(fiche, cle, s); if (a.length) { partagees++; a.forEach(function (n) { avec[n] = 1; }); }
          });
        });
        if (partagees) r.chiffres.appendChild(el('p', 'mpm-note mpm-note-ambre', partagees + ' case' + (partagees > 1 ? 's' : '')
          + ' aussi surveillée' + (partagees > 1 ? 's' : '') + ' par ' + Object.keys(avec).join(', ') + '. Chacun est payé dessus.'));
      }
      if (avecZone) peindreZone();
    }
    function peindreZone() {
      zone.replaceChildren(role === 'manager' ? carre(fiche, repeindre) : perimetre(fiche, repeindre));
    }
    function repeindre() { peindreZone(); peindreChiffres(false); }
    gauche.appendChild(el('h4', '', role === 'manager'
      ? 'Ce que ' + (fiche.nom || 'ce manager') + ' surveille'
      : 'Le périmètre de ' + (fiche.nom || 'ce mini-boss')));
    gauche.appendChild(el('p', 'mpm-aide', role === 'manager'
      ? 'Clique une case pour la cocher. Une case = les ventes d’une model pendant un shift, sur la période affichée. Un clic sur un shift ou sur une model coche toute la colonne ou toute la ligne.'
      : 'Il touche son pourcentage sur toutes les ventes des models de son périmètre, sur 24 h.'));
    gauche.appendChild(zone);
    boite.appendChild(gauche); boite.appendChild(r.boite);
    repeindre();
    return boite;
  }

  /* ---------- un onglet ---------- */
  function fichePour(p) {
    // On regle une COPIE : fermer sans enregistrer ne change rien a la ligne.
    if (!brouillons[p.id]) {
      var copie = JSON.parse(JSON.stringify(p));
      copie.cases = copie.cases || {}; copie.models = copie.models || []; copie.portee = copie.portee || 'tout';
      brouillons[p.id] = copie;
    }
    return brouillons[p.id];
  }
  function peindre(role) {
    var panneau = panneaux[role], R = ROLES[role], gens = deRole(role);
    var nouveau = brouillons['nouveau-' + role];
    var total = 0, payes = 0, sansAdresse = 0;
    gens.forEach(function (p) {
      total += Number(p.a_payer || 0);
      if (data.paye.indexOf(p.id) >= 0) payes++;
      if (!p.crypto_address) sansAdresse++;
    });
    boutons[role].textContent = R.onglet + ' (' + gens.length + ')';

    var bande = el('div', 'mpm-bande'), gauche = el('div');
    gauche.appendChild(el('div', 'mpm-bande-titre', '💰 Total à payer aux ' + R.pluriel + ' sur cette période'));
    gauche.appendChild(el('div', 'mpm-bande-aide', R.aide));
    bande.appendChild(gauche); bande.appendChild(el('span', 'mpm-esp'));
    var ajouter = el('button', 'mpm-btn', '+ Ajouter ' + R.un); ajouter.type = 'button';
    ajouter.onclick = function () {
      brouillons['nouveau-' + role] = {id:'nouveau-' + role, nouveau:true, role:role, nom:'', discord:'', pct:0, cases:{}, portee:'tout', models:[]};
      ouvert[role] = 'nouveau-' + role; peindre(role);
      var champNom = panneau.querySelector('.mpm-reglages input'); if (champNom) champNom.focus();
    };
    bande.appendChild(ajouter);
    var droite = el('div', 'mpm-bande-total');
    droite.appendChild(el('div', 'mpm-bande-gros', usd(total)));
    droite.appendChild(el('div', 'mpm-bande-aide', gens.length
      ? payes + ' / ' + gens.length + ' payé' + (payes > 1 ? 's' : '') + (sansAdresse ? ' · ' + sansAdresse + ' adresse' + (sansAdresse > 1 ? 's' : '') + ' à renseigner' : '')
      : 'personne pour l’instant'));
    bande.appendChild(droite);

    var boite = el('div', 'mpm-boite mpm-' + role), tete = el('div', 'mpm-ligne mpm-tete');
    ['', R.titre, R.portee, R.ca, 'Commission', 'À payer', 'Payé', 'Adresse'].forEach(function (t, i) {
      tete.appendChild(el('span', i === 1 || i === 2 || i === 7 ? 'mpm-g' : i === 6 ? 'mpm-c' : '', t));
    });
    boite.appendChild(tete);
    if (!gens.length && !nouveau) {
      boite.appendChild(el('p', 'mpm-vide', role === 'manager'
        ? 'Aucun manager pour l’instant. Ajoute-en un, donne-lui un pourcentage et coche les shifts qu’il surveille.'
        : 'Aucun mini-boss pour l’instant. Ajoute-en un, donne-lui un pourcentage et choisis son périmètre.'));
    }
    gens.slice().sort(function (a, b) { return (b.a_payer || 0) - (a.a_payer || 0) || String(a.nom).localeCompare(String(b.nom)); })
      .forEach(function (p, i) {
        var estOuvert = ouvert[role] === p.id, modifie = !!(brouillons[p.id] && brouillons[p.id].modifie);
        var l = el('div', 'mpm-ligne mpm-personne' + (estOuvert ? ' mpm-ouverte' : ''));
        l.setAttribute('role', 'button'); l.tabIndex = 0; l.setAttribute('aria-expanded', String(estOuvert));
        l.appendChild(el('span', 'mpm-rang', String(i + 1)));
        var qui = el('span', 'mpm-g mpm-qui');
        qui.appendChild(rond(p.nom, p.photo, i));
        var noms = el('span'); noms.appendChild(el('b', '', p.nom));
        noms.appendChild(el('small', '', (p.discord ? '@' + p.discord : 'Discord à relier') + (modifie ? ' · modifié, pas enregistré' : '')));
        qui.appendChild(noms); qui.appendChild(el('i', 'mpm-chevron', estOuvert ? '▾' : '›'));
        l.appendChild(qui);
        var portee = el('span', 'mpm-g');
        portee.appendChild(role === 'manager' ? resumeManager(p) : resumeMiniboss(p));
        if (role === 'miniboss') portee.appendChild(el('small', '', p.nb_models + ' model' + (p.nb_models > 1 ? 's' : '') + ' · 24 h'));
        l.appendChild(portee);
        var ca = el('span'); ca.appendChild(el('b', '', usd(p.ca)));
        if (role === 'manager') ca.appendChild(el('small', '', p.nb_cases + ' case' + (p.nb_cases > 1 ? 's' : '') + ' · ' + p.nb_models + ' model' + (p.nb_models > 1 ? 's' : '')));
        l.appendChild(ca);
        var com = el('span'); var pastille = el('span', 'mpm-pct'); pastille.appendChild(document.createTextNode(pct(p.pct))); pastille.appendChild(el('i', '', '%'));
        com.appendChild(pastille); l.appendChild(com);
        l.appendChild(el('span', 'mpm-vert', usd(p.a_payer)));
        var paye = el('span', 'mpm-c'), coche = el('input'); coche.type = 'checkbox'; coche.className = 'mpm-paye';
        coche.checked = data.paye.indexOf(p.id) >= 0; coche.setAttribute('aria-label', 'Payé pour cette période : ' + p.nom);
        coche.onclick = function (e) { e.stopPropagation(); };
        coche.onchange = function () {
          coche.disabled = true;
          poster('/mypuls/managers/paye', {id:p.id, start:periode.start, end:periode.end, paye:coche.checked})
            .then(function (j) { if (j.ok) data.paye = j.paye; else { coche.checked = !coche.checked; window.alert(j.erreur || 'Refusé'); } })
            .catch(function () { coche.checked = !coche.checked; })
            .then(function () { coche.disabled = false; peindre(role); });
        };
        paye.appendChild(coche); l.appendChild(paye);
        var adr = el('span', 'mpm-g'); peindreAdresse(adr, p); l.appendChild(adr);
        if (coche.checked) l.classList.add('mpm-payee');
        var basculerLigne = function () { ouvert[role] = estOuvert ? null : p.id; peindre(role); };
        l.onclick = basculerLigne;
        l.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); basculerLigne(); } };
        boite.appendChild(l);
        if (estOuvert) boite.appendChild(detail(role, fichePour(p)));
      });
    if (nouveau && ouvert[role] === nouveau.id) boite.appendChild(detail(role, nouveau));
    panneau.replaceChildren(bande, boite);
    if (data.matrice.ecartees) panneau.appendChild(el('p', 'mpm-note', data.matrice.ecartees + ' vente(s) sans nom de model : comptée(s) nulle part ici.'));
  }
  function peindreTout() { Object.keys(ROLES).forEach(peindre); }

  /* ---------- la liste des membres Discord (pour choisir un pseudo) ---------- */
  var membresDemandes = false;
  function chargerMembres() {
    var liste = document.getElementById('mp-discord-membres');
    if (membresDemandes || !liste || liste.children.length) return;
    membresDemandes = true;
    fetch('/mypuls/chatters/membres_discord.json', {credentials:'same-origin'})
      .then(function (r) { return r.ok ? r.json() : null; })
      // `options` est du HTML deja echappe par le serveur (html_escape).
      .then(function (j) { if (j && j.ok && j.options && !liste.children.length) liste.innerHTML = j.options; })
      .catch(function () { membresDemandes = false; });
  }

  /* ---------- depart ---------- */
  fetch(adresse, {credentials:'same-origin'})
    .then(function (r) { return r.ok ? r.json() : null; })     // 401 / 403 : pas d'acces complet, aucun onglet
    .then(function (j) {
      if (!j || !j.ok) return;
      data = j;
      var repere = barre.querySelectorAll('.mypuls-tab'); repere = repere[repere.length - 1];
      var precedent = apres;
      Object.keys(ROLES).forEach(function (role) {
        var b = el('button', 'mypuls-tab'); b.type = 'button';
        b.setAttribute('onclick', 'mpTab(this,"' + (role === 'manager' ? 'managers' : 'miniboss') + '")');
        repere.after(b); repere = b; boutons[role] = b;
        var p = el('div', 'mpm'); p.id = 'mp-tab-' + (role === 'manager' ? 'managers' : 'miniboss'); p.style.display = 'none';
        precedent.after(p); precedent = p; panneaux[role] = p;
      });
      peindreTout();
    })
    .catch(function () {});
})();
