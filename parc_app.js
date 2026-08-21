/* ==========================================================================
   REMOTE 2 — LE POSTE DE PILOTAGE DU PARC
   Interface de bot/parc_web.py. Servie par GET /parc/app.js.

   POURQUOI CE FICHIER EXISTE SEPAREMENT (et n'est pas une chaine Python) :
   dans ce projet le JS vivait dans des chaines """ de web_upload.py, ou une
   seule apostrophe mal echappee tuait le script de la page ENTIERE, en
   silence. Ici, « node --check parc_app.js » verifie le fichier tel qu'il
   est servi, et le piege disparait par construction.

   CONTRAT : le serveur calcule TOUT (verdicts, phrases, agregats, SVG). Ce
   fichier ne fait aucun calcul metier — il pose du HTML. C'est la condition
   pour que l'ecran reste juste a 5 machines et 250 comptes : la verite est
   calculee une fois, cote serveur.

   REGLE DE COMPOSITION tenue partout : aucun chiffre sans (a) son age,
   (b) sa provenance (● mesure / ◐ derive / ○ non declare), (c) la phrase
   qui dit quoi en faire. « 33 » nu est interdit.
   ========================================================================== */
(function () {
  'use strict';

  /* Garde d'idempotence : le fichier peut etre servi deux fois si la
     section est reconstruite par showTab (web_upload.py:6793 fabrique la
     section absente). Sans ce drapeau, deux sondages tourneraient. */
  /* Le chargeur paresseux du site (web_upload.py:6833) REJOUE les <script>
     du fragment apres avoir remplace le HTML de la section : le fichier
     peut donc s'executer deux fois, sur un #parc-root tout neuf. Le
     deuxieme passage ne rebranche pas tout — il rappelle simplement le
     depart, qui est idempotent par racine. */
  if (window.__r2Boot) { if (window.__r2Reveil) window.__r2Reveil(); return; }
  window.__r2Boot = 1;

  /* ---------------------------------------------------------------- etat */
  var S = {
    etat: null,            // la reponse de /parc/state, deja calculee
    err: '',
    charge: false,
    dernier: 0,            // horodatage du dernier /parc/state recu
    vueParc: 'agregee',
    parcDet: null,
    parcOpts: {tri: 'retard', sens: 'asc', page: 1, cat: '', statut: '',
               filtre: '', q: ''},
    ongletF: 'cloche',
    journal: null,
    jrnOpts: {evt: '', objet: '', code: '', machine: '', conteneur: '',
              depuis: 86400, page: 1, q: ''},
    jrnPreset: '24h',
    ecarts: null,
    ouvert: {prevol: false, pvOk: false, boite: false, det: ''},
    tiroir: '',            // '', 'reglages', 'provenance', 'correctifs', 'inventaire', 'machine'
    tiroirId: '',
    brouillon: null,       // les reglages en cours d'edition
    modifies: [],
    corriges: [],
    apercu: null,          // tuiles simulees, non enregistrees
    confirm: {cle: '', jusqu: 0},
    tempo: null,
    simTempo: null,
    qTempo: null
  };

  var MARQUES = {
    'mesure': ['●', 'mesure par le poste'],
    'derive': ['◐', 'derive par le site (observateur)'],
    'non_declare': ['○', 'non declare par le poste — ce n’est PAS un vert par defaut']
  };

  /* Libelles humains des valeurs de reglage. Le serveur envoie des cles
     techniques ; « refuser » seul ne dit pas ce qui sera refuse. */
  var LIB = {
    refuser: 'Refuser et compter dans Ecarts',
    classer: 'Classer d’office dans la categorie par defaut',
    retard: 'Le plus en retard d’abord',
    moins_passages: 'Le moins de passages d’abord',
    aleatoire: 'Aleatoire',
    registre: 'Ordre du registre',
    reporter: 'Reporter a l’ouverture suivante',
    abandonner: 'Abandonner (le passage disparait)',
    moins_chargee: 'A la machine la moins chargee',
    par_categorie: 'Une categorie par machine',
    manuel: 'Attribution manuelle',
    vault_poste: 'Vault PRO du poste',
    biblio_site: 'Bibliotheque du site',
    publier: 'Publier quand meme et compter l’ecart',
    annuler: 'Annuler le passage',
    moins_recent: 'Le moins recemment publie',
    tout: 'Tout, decisions de l’ordonnanceur comprises',
    evenements: 'Les evenements seulement',
    echecs: 'Les echecs seulement',
    ici: 'Ici seulement (bandeau rouge en haut)',
    ici_discord: 'Ici + Discord',
    agregee: 'Agregee (machine x categorie)',
    detaillee: 'Detaillee (une ligne par compte)',
    auto24h: 'Reessayer automatiquement apres 24 h',
    prudent: 'Prudent', croisiere: 'Croisiere', plein: 'Plein regime',
    surveillance: 'Surveillance seule', personnalise: 'Personnalise'
  };

  var GROUPES = [
    ['pilote', 'Le pilote', 'La commande elle-meme.'],
    ['parc', 'Le parc', 'Combien de comptes, et dans quelles categories.'],
    ['creation', 'Creation de comptes',
     '33 comptes declares pour 50 vises : le manque est l’etat normal du parc.'],
    ['publication', 'Rythme de publication',
     'Les mots du proprietaire : « toutes les dix douze heures, six reels a chaque fois ».'],
    ['fenetres', 'Fenetres horaires', 'Quand le parc a le droit de travailler.'],
    ['machines', 'Machines', 'Ce qu’un telephone peut physiquement absorber.'],
    ['gardefous', 'Garde-fous', 'Les seuils a partir desquels le pilote s’arrete tout seul.'],
    ['medias', 'Medias', 'Ou sont les videos, et a quelle frequence les rejouer.'],
    ['journal', 'Journal et alertes', 'Ce qui restera lisible dans six mois.'],
    ['affichage', 'Cet ecran', 'Rafraichissement et pagination.']
  ];

  var JOURS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

  /* ------------------------------------------------------------ outillage */
  function esc(x) {
    return String(x === null || x === undefined ? '' : x)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function racine() { return document.getElementById('parc-root'); }
  function zone(id) { return document.getElementById(id); }
  function num(n) {
    var v = Number(n || 0);
    return v.toLocaleString('fr-FR');
  }
  function hhmm(ts) {
    if (!ts) return '—';
    var d = new Date(Number(ts) * 1000);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  function jourheure(ts) {
    if (!ts) return '—';
    var d = new Date(Number(ts) * 1000);
    return ('0' + d.getDate()).slice(-2) + '/' + ('0' + (d.getMonth() + 1)).slice(-2)
      + ' ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  function toast(m, t) {
    if (typeof window.showToast === 'function') window.showToast(m, t || 'success');
  }
  /* La marque de provenance, avec son infobulle. Elle herite du tooltip
     global du site (.hsc-dot, web_upload.py:16827) : zero ligne de plus. */
  function marque(prov) {
    var m = MARQUES[prov] || MARQUES.non_declare;
    return '<span class="r2-mq r2-mq-' + esc(prov || 'non_declare')
      + ' hsc-dot" data-tip="' + esc(m[1]) + '">' + m[0] + '</span>';
  }
  function classeGravite(g) { return 'r2-g-' + (g || 'gris'); }

  /* Poste un formulaire et rend TOUJOURS un objet exploitable.

     Avant : on faisait r.json() sans jamais regarder le code HTTP, et 11 des
     12 appelants n'avaient pas de .catch(). Des que la reponse n'etait pas du
     JSON — 403 du garde RBAC, 302 vers /login, 500 avec une page d'erreur —
     r.json() rejetait et le clic ne faisait RIEN : pas de toast, pas de
     trace, juste un rejet de promesse non traite. Un veilleur de nuit avec
     le role « Remote 2 (lecture) » cliquait « Mettre en pause », ne voyait
     aucune reaction, et concluait que le site etait casse.

     Trois corrections, toutes ici pour que les 12 appelants en profitent :
       * ajax=1 — le garde RBAC (web_upload.py) repond en text/html sans lui ;
       * le code HTTP est lu AVANT de tenter r.json() ;
       * un .catch() unique traduit toute panne en toast et en objet
         {ok:false, error:...}, si bien qu'aucun appelant ne peut plus
         echouer en silence. */
  function poste(url, champs) {
    var fd = new FormData();
    for (var k in champs) {
      if (Object.prototype.hasOwnProperty.call(champs, k)) fd.append(k, champs[k]);
    }
    /* Sans ajax=1, le garde RBAC rend « Action reservee aux administrateurs »
       en text/html : du HTML dans r.json(), donc un rejet muet. */
    if (!Object.prototype.hasOwnProperty.call(champs || {}, 'ajax')) fd.append('ajax', '1');
    return fetch(url, {
      method: 'POST', body: fd, credentials: 'same-origin',
      headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
    }).then(function (r) {
      if (r.status === 401) throw new Error('session expiree — rechargez la page');
      if (r.status === 403) {
        throw new Error('403 : action reservee aux administrateurs '
          + '(le role « Remote 2 » donne la surveillance, pas la commande)');
      }
      if (r.status === 302 || r.redirected) throw new Error('session expiree — rechargez la page');
      return r.text().then(function (txt) {
        var j = null;
        try { j = JSON.parse(txt); } catch (e) { j = null; }
        if (!j) {
          throw new Error('reponse illisible du serveur (HTTP ' + r.status + ') : '
            + String(txt || '').replace(/<[^>]*>/g, ' ').trim().slice(0, 120));
        }
        if (!r.ok && j.error === undefined) {
          throw new Error('HTTP ' + r.status);
        }
        return j;
      });
    }).catch(function (e) {
      /* Ne jamais ecarter en silence : le toast est la seule chose qui
         distingue « le serveur a refuse » de « le bouton est mort ». */
      var msg = (e && e.message) ? e.message : String(e || 'echec reseau');
      toast(msg, 'error');
      return {ok: false, error: msg, _echec: true};
    });
  }
  function lit(url) {
    return fetch(url, {credentials: 'same-origin'}).then(function (r) {
      if (r.status === 401) throw new Error('session expiree — rechargez la page');
      if (r.status === 403) throw new Error('403 : le prefixe /parc/ n’est pas '
        + 'declare dans le RBAC de web_upload.py');
      return r.json();
    });
  }

  /* ------------------------------------------------------------ visibilite */
  /* Sonder un onglet masque a deja coute cher a ce projet : ZERO requete
     quand la section est cachee (patron remoteEtat, web_upload.py:9386). */
  function visible() {
    var sec = document.getElementById('form-remote2');
    if (sec) return sec.style.display !== 'none';
    var r = racine();
    return !!(r && r.offsetParent !== null);
  }

  function periode() {
    if (!visible() || document.hidden) return 0;
    var r = (S.etat && S.etat.regles) || {};
    var actif = (S.etat && S.etat.regles && S.etat.regles.pilote)
      || (S.etat && S.etat.machines && (S.etat.machines.lignes || []).some(
        function (m) { return m.etat === 'travail'; }));
    return (actif ? (r.rafraichissement_actif_s || 5) : (r.rafraichissement_repos_s || 20)) * 1000;
  }
  function planifierSondage() {
    if (S.tempo) clearTimeout(S.tempo);
    var d = periode();
    S.tempo = setTimeout(function () {
      if (periode() > 0) charger(true);
      else planifierSondage();
    }, d > 0 ? d : 4000);
  }
  window.__r2Reveil = function () { demarrer(); };

  /* ================================================================
     CHARGEMENT
     ================================================================ */
  function charger(auto) {
    if (S.charge) return;
    S.charge = true;
    lit('/parc/state').then(function (j) {
      S.charge = false;
      S.dernier = Date.now();
      if (j && j.ok === false) { S.err = j.error || 'erreur'; S.etat = S.etat || null; }
      else { S.err = ''; S.etat = j; }
      /* `vue_parc` etait un reglage que personne ne lisait : la vue de
         depart etait figee sur « agregee » en dur. On ne l'applique qu'au
         PREMIER chargement, sinon un rafraichissement automatique
         ramenerait l'utilisateur sur l'autre vue toutes les 5 s. */
      if (!S.vueParcPosee && S.etat && S.etat.regles && S.etat.regles.vue_parc) {
        S.vueParcPosee = true;
        S.vueParc = S.etat.regles.vue_parc === 'detaillee' ? 'detaillee' : 'agregee';
        if (S.vueParc === 'detaillee') chargerParcDet();
      }
      /* Un rafraichissement automatique ne doit pas voler le curseur ni
         fermer un tiroir en cours d'edition : dans ce cas seule la zone du
         haut est redessinee. Sans ce garde, taper dans le champ de
         recherche du parc etait impossible. */
      var focus = document.activeElement;
      var edite = focus && racine() && racine().contains(focus)
        && /^(INPUT|TEXTAREA|SELECT)$/.test(focus.tagName);
      if (auto && (S.tiroir || edite)) { rendreA(); rendreBandeaux(); }
      else rendre();
      planifierSondage();
    }).catch(function (e) {
      S.charge = false;
      S.err = String(e && e.message ? e.message : e);
      rendreBandeaux();
      if (!S.etat) rendre();
      planifierSondage();
    });
  }

  /* ================================================================
     RENDU — un appel par zone, jamais un innerHTML global : recomposer
     toute la page a chaque tick ferait sauter le defilement.
     ================================================================ */
  function rendre() {
    var r = racine();
    if (!r) return;
    var sec = r.querySelector('.r2-secours');
    if (sec) sec.remove();
    rendreBandeaux();
    rendreA();
    rendreB();
    rendreC();
    rendreD();
    rendreE();
    rendreF();
    rendreG();
    rendreTiroir();
  }

  /* ---------------------------------------------------- bandeaux d'alerte */
  function rendreBandeaux() {
    var z = zone('r2-bandeaux');
    if (!z) return;
    var h = '';
    if (S.err) {
      h += bandeau('rouge', 'L’ecran ne repond plus', esc(S.err)
        + ' — les chiffres affiches datent de '
        + (S.dernier ? Math.round((Date.now() - S.dernier) / 1000) + ' s' : 'jamais') + '.',
        '<button class="r2-b2" data-r2act="recharger">Reessayer</button>');
    }
    var e = S.etat || {};
    if (e.erreurs && e.erreurs.length) {
      h += bandeau('ambre', e.erreurs.length + ' bloc(s) de l’ecran n’ont pas pu etre calcules',
        'Le reste de l’ecran reste valable. ' + esc(e.erreurs.join(' · ')), '');
    }
    /* LES GARDE-FOUS S'AFFICHENT EN HAUT, VISIBLES, QUAND ILS SE
       DECLENCHENT. Le pre-vol complet est en zone C, mais un blocage ne
       doit pas attendre qu'on fasse defiler : la nuit du 21/08, une cause
       unique a produit 100 % d'echecs pendant des heures sans que rien ne
       le dise. */
    var pv = e.prevol || {};
    var bloq = (pv.controles || []).filter(function (c) { return c.bloque; });
    if (bloq.length) {
      h += bandeau('rouge', bloq.length + ' garde-fou(s) bloquent le demarrage',
        bloq.map(function (c) {
          return '<b>' + esc(c.nom) + '</b> : ' + esc(c.valeur) + ' — ' + esc(c.message);
        }).join('<br>'),
        '<button class="r2-b2" data-r2act="prevol-rouges">Ouvrir le pre-vol</button>');
    }
    var urg = (e.etat_pilote || {}).arret_urgence || {};
    if (urg && urg.ts) {
      h += bandeau('rouge', 'Arret d’urgence declenche ' + jourheure(urg.ts),
        esc(urg.motif || urg.code || '') + ' — les travaux en attente sont geles, '
        + 'pas annules. Le pre-vol est rejoue avant toute reprise.', '');
    }
    /* Piege ferme de notre cote : le garde de l'editeur de Remote 1 teste
       tab.indexOf('remote')!==0, donc partir vers « remote2 » avec des
       modifications non enregistrees ne demande AUCUNE confirmation. On ne
       touche pas Remote 1 ; on previent ici. */
    try {
      if (window.RMT_ED && window.RMT_ED.nom && !window.RMT_ED.propre) {
        h += bandeau('ambre', 'L’editeur de scenarios de Remote a des modifications non enregistrees',
          'Le scenario « ' + esc(window.RMT_ED.nom) + ' » a ete modifie et n’a pas ete envoye au poste. '
          + 'Quitter l’editeur vers Remote 2 ne demande pas de confirmation.',
          '<button class="r2-b2" data-r2act="remote1" data-r2id="editeur">Y retourner</button>');
      }
    } catch (x) { /* Remote 1 absent : ce n'est pas une erreur */ }
    z.innerHTML = h;
  }
  function bandeau(niv, titre, texte, boutons) {
    return '<div class="r2-bandeau r2-g-' + niv + '">'
      + '<div class="r2-bandeau-t">' + titre + '</div>'
      + '<div class="r2-bandeau-x">' + texte + '</div>'
      + (boutons ? '<div class="r2-bandeau-b">' + boutons + '</div>' : '')
      + '</div>';
  }

  /* ================================================================
     ZONE A — LE VERDICT, LE BOUTON, LES VOYANTS (etage 0)
     ================================================================ */
  function rendreA() {
    var z = zone('r2-a');
    if (!z) return;
    var e = S.etat;
    if (!e) {
      z.innerHTML = '<div class="r2-carte"><div class="r2-verdict r2-g-gris">'
        + 'Le poste de pilotage n’a pas encore repondu.</div>'
        + '<div class="r2-sous">' + esc(S.err || 'chargement…') + '</div></div>';
      return;
    }
    var v = e.verdict || {};
    var b = e.bouton || {};
    var f = e.fraicheur || {};
    var r = e.regles || {};
    var plan = (e.plan && e.plan.resume) || {};

    /* Le bouton : LE LIBELLE EST L'ETAT. Il ne se grise jamais sans dire
       pourquoi il refuse. */
    var actConf = S.confirm.cle && S.confirm.jusqu > Date.now();
    var lib = b.libelle || '…';
    var cls = 'r2-b1 r2-b1-' + (b.style || 'gris');
    var act = 'pilote';
    if (b.etat === 'pause') act = 'pilote-off';
    else if (b.etat === 'demarrer' || b.etat === 'reserves') act = 'pilote-on';
    else if (b.etat === 'nogo') act = 'prevol-rouges';
    else act = 'rien';
    if (actConf && S.confirm.cle === act) {
      lib = b.confirmation || 'CONFIRMER';
      cls += ' r2-b1-conf';
    }

    var voy = (e.voyants || []).map(function (o) {
      return '<button class="r2-voy" data-r2act="tiroir-provenance" data-r2id="' + esc(o.cle) + '">'
        + '<i class="r2-pt ' + classeGravite(o.gravite) + '"></i>'
        + '<span class="r2-voy-n">' + esc(o.nom) + '</span>'
        + '<span class="r2-voy-v">' + esc(o.valeur) + '</span>'
        + '<span class="r2-voy-a">' + marque(o.provenance) + ' ' + esc(o.age) + '</span>'
        + '</button>';
    }).join('');

    var depuis = (e.etat_pilote && e.etat_pilote.pilote_depuis) || 0;
    var pause = (e.etat_pilote && e.etat_pilote.pause_jusqu_a) || 0;
    var faits = 0;
    ((e.machines || {}).lignes || []).forEach(function (m) {
      faits += ((m.aujourdhui || {}).fini || 0);
    });
    var sous = [];
    sous.push(r.pilote
      ? 'Pilote actif' + (depuis ? ' depuis ' + hhmm(depuis) : '')
      : 'Pilote arrete');
    /* La fenetre : sans elle, « 0 travail du » se lit comme une panne alors
       que c'est simplement 3 h du matin et que la fenetre ouvre a 10 h. */
    sous.push((e.plan || {}).fenetre_ouverte
      ? 'fenetre ouverte'
      : 'hors fenetre, ouverture ' + jourheure((e.plan || {}).prochaine_ouverture));
    sous.push(num(plan.dus || 0) + ' du(s) · ' + num(plan.programmes || 0)
      + ' programme(s) · ' + num(plan.refuses || 0) + ' refuse(s)');
    sous.push(num(faits) + ' publication(s) journalisee(s) aujourd’hui');
    sous.push('lot de ' + num(plan.lot_par_tick || 0) + ' par tour');
    if (plan.bride_par_machines) sous.push('bride : aucune machine libre');
    if (pause > (e.maintenant || 0)) sous.push('en pause jusqu’a ' + jourheure(pause));

    z.innerHTML =
      '<div class="r2-barre">'
      + '<div class="r2-barre-h">'
      + '<button class="r2-verdict ' + classeGravite(v.niveau) + '" data-r2act="ancre" data-r2id="'
      + esc(v.ancre || 'prevol') + '">' + esc(v.phrase || '…') + '</button>'
      + '<span class="r2-frais ' + (f.perime ? 'r2-g-rouge' : 'r2-g-vert') + ' hsc-dot" '
      + 'data-tip="Age de la donnee la plus vieille affichee sur cet ecran. Au-dela de '
      + esc(r.age_donnees_min || 10) + ' min, on decide sur des chiffres perimes.">'
      + '⟳ donnees de ' + esc(f.age || '?') + '</span>'
      + '</div>'
      + '<div class="r2-cmd">'
      + '<button class="' + cls + '" data-r2act="' + act + '"'
      + (b.peut_cliquer ? '' : ' disabled')
      + ' title="' + esc(b.raison || '') + '">' + esc(lib) + '</button>'
      + '<div class="r2-cmd-x">'
      + '<div class="r2-sousligne">' + esc(sous.join(' · ')) + '</div>'
      + '<div class="r2-sous">' + esc(b.raison || '') + '</div>'
      + '</div>'
      + '<div class="r2-cmd-b">'
      + '<button class="r2-b2" data-r2act="tiroir-reglages">⚙ Reglages</button>'
      + '<span class="r2-pausebloc">'
      + '<select class="r2-champ r2-champ-s" data-r2sel="pause">'
      + '<option value="4">4 h</option>'
      + '<option value="12" selected>12 h</option>'
      + '<option value="24">24 h</option>'
      + '</select>'
      + '<button class="r2-b2" data-r2act="pause" title="Le geste « je pars, ne fais rien ce soir »">'
      + '⏸ Pause</button>'
      + '</span>'
      + '<button class="r2-b2" data-r2act="recharger" title="Redemande /parc/state">⟳</button>'
      + '</div>'
      + '</div>'
      + '<div class="r2-voyants">' + voy + '</div>'
      /* Dire exactement ce que fait le pilote : ni plus (on croirait que
         le parc tourne alors qu'il est a l'arret), ni moins (on croirait
         qu'il ne part jamais). */
      + '<div class="r2-note">' + (etatPiloteTexte()) + '</div>'
      + '</div>';
  }

  /* ================================================================
     ZONE B — CE QUE CA VA FAIRE : 4 tuiles + le ruban 24 h
     ================================================================ */
  function rendreB() {
    var z = zone('r2-b');
    if (!z || !S.etat) return;
    var src = S.apercu || (S.etat.tuiles || {});
    var tuiles = (src.tuiles || []).map(function (t, i) {
      var corr = (t.corrections || []).map(function (c, k) {
        if (!c.champ) return '';
        return '<button class="r2-b3" data-r2act="tuile-corr" data-r2id="' + i + ':' + k + '">'
          + esc(c.libelle) + '</button>';
      }).join('');
      return '<div class="r2-tuile r2-t-' + esc(t.verdict || 'ok') + '">'
        + '<div class="r2-tuile-t">' + esc(t.titre) + ' ' + marque(t.provenance) + '</div>'
        + '<div class="r2-tuile-v">' + esc(t.valeur) + '</div>'
        + '<div class="r2-tuile-d">' + esc(t.detail) + '</div>'
        + '<div class="r2-tuile-p">' + esc(t.phrase) + '</div>'
        + (corr ? '<div class="r2-tuile-c">' + corr + '</div>' : '')
        + '<div class="r2-tuile-verdict">' + esc((t.verdict || '').toUpperCase()) + '</div>'
        + '</div>';
    }).join('');

    var g = S.etat.graphiques || {};
    var legende = ''
      + '<span class="r2-leg"><i class="r2-pt r2-g-vert"></i>fini</span>'
      + '<span class="r2-leg"><i class="r2-pt r2-g-rouge"></i>echec</span>'
      + '<span class="r2-leg"><i class="r2-pt r2-g-bleu"></i>en cours</span>'
      + '<span class="r2-leg"><i class="r2-hach"></i>prevu par le plan</span>'
      + '<span class="r2-leg"><i class="r2-hach r2-hach-g"></i>machine muette</span>'
      + '<span class="r2-leg"><i class="r2-trait-a"></i>chute de WebDriverAgent</span>';

    z.innerHTML =
      (S.apercu ? '<div class="r2-apercu">Apercu : ces quatre tuiles montrent les reglages '
        + 'EN COURS D’EDITION, pas ceux qui sont enregistres. '
        + '<button class="r2-b3" data-r2act="apercu-annuler">Revenir aux reglages actifs</button></div>' : '')
      + '<div class="r2-tuiles">' + tuiles + '</div>'
      + '<div class="r2-carte" id="r2-ruban">'
      + '<div class="r2-tete"><div class="r2-h">Les 24 heures du parc</div>'
      + '<div class="r2-sous">18 h de passe mesure, 6 h de prevu. Une voie par machine : '
      + 'deux blocs superposes sur la meme voie, ce sont deux agents empiles.</div></div>'
      + '<div class="r2-scroll">' + (g.ruban || '') + '</div>'
      + '<div class="r2-legendes">' + legende + '</div>'
      + '</div>'
      + '<div class="r2-carte">'
      + '<button class="r2-plier" data-r2act="boite">'
      + (S.ouvert.boite ? '▾' : '▸') + ' La boite noire — debit horaire et couverture du parc'
      + '</button>'
      + (S.ouvert.boite
        ? '<div class="r2-plie">'
          + '<div class="r2-h2">Debit des 24 dernieres heures</div>'
          + '<div class="r2-scroll">' + (g.debit || '') + '</div>'
          + '<div class="r2-sous">' + esc(g.debit_phrase || '') + '</div>'
          + '<div class="r2-h2">Couverture du parc — 8 etapes du cycle</div>'
          + '<div class="r2-scroll">' + (g.couverture || '') + '</div>'
          + '<div class="r2-sous">Le seul graphique qui ne grossit pas avec le parc : '
          + '8 colonnes, que le parc fasse 33 ou 2 500 comptes.</div>'
          + '<div class="r2-h2">Reussite brute contre reussite verifiee</div>'
          + '<div class="r2-sous">' + esc(g.reussite_14j_note || '') + '</div>'
          + '</div>'
        : '')
      + '</div>';
  }

  /* ================================================================
     ZONE C — LE PRE-VOL (etage 0 -> 1)
     Il ne parle que quand il a quelque chose a dire : replie en une ligne
     si tout est vert, ouvert tout seul sinon.
     ================================================================ */
  function rendreC() {
    var z = zone('r2-c');
    if (!z || !S.etat) return;
    var pv = S.etat.prevol || {controles: []};
    var ctrls = pv.controles || [];
    var nonVerts = ctrls.filter(function (c) { return c.gravite !== 'vert'; });
    var verts = ctrls.filter(function (c) { return c.gravite === 'vert'; });
    var ouvert = S.ouvert.prevol || nonVerts.length > 0;

    var lignes = (ouvert ? nonVerts : []).map(ligneControle).join('');
    var lignesOk = (ouvert && S.ouvert.pvOk) ? verts.map(ligneControle).join('') : '';

    var resume = pv.total + ' controles · ' + pv.verts + ' OK · '
      + pv.ambres + ' reserve(s) · ' + pv.rouges + ' rouge(s) · '
      + pv.gris + ' non mesurable(s)';

    z.innerHTML = '<div class="r2-carte" id="r2-prevol">'
      + '<div class="r2-tete">'
      + '<button class="r2-plier" data-r2act="prevol">'
      + (ouvert ? '▾' : '▸') + ' Pre-vol — ' + esc(resume) + '</button>'
      + '<div class="r2-sous">Calcule il y a ' + Math.max(0, Math.round(
        ((S.etat.maintenant || 0) - (pv.calcule_le || 0)))) + ' s.</div>'
      + '</div>'
      + (ouvert
        ? '<div class="r2-plie">'
          + (nonVerts.length ? '<div class="r2-pv">' + lignes + '</div>'
            : '<div class="r2-sous">Les ' + pv.total + ' controles sont verts. Rien ne s’oppose au demarrage.</div>')
          + (verts.length
            ? '<button class="r2-b3" data-r2act="pv-ok">'
              + (S.ouvert.pvOk ? 'Masquer' : 'Voir') + ' les ' + verts.length + ' controles OK</button>'
            : '')
          + (lignesOk ? '<div class="r2-pv r2-pv-ok">' + lignesOk + '</div>' : '')
          + '<div class="r2-pied">'
          + pv.non_declares + ' indicateur(s) sont ○ non declares — '
          + (pv.correctifs_poste || []).length + ' correctif(s) cote poste les rendraient ● '
          + '<button class="r2-b3" data-r2act="tiroir-correctifs">voir la liste</button>'
          + (pv.erreurs_de_controle && pv.erreurs_de_controle.length
            ? ' · <b class="r2-g-rouge">' + pv.erreurs_de_controle.length
              + ' controle(s) en erreur : ' + esc(pv.erreurs_de_controle.join(', ')) + '</b>'
            : '')
          + '</div>'
          + '</div>'
        : '')
      + '</div>';
  }
  /* L'etiquette d'un controle, en toutes lettres.

     Avant, « bloquant » etait pose sur `bloquant_si_rouge` — or _diag()
     (parc_web.py) force `bloque = bloque_si_rouge ET gravite == ROUGE`. Dix
     controles portaient donc l'etiquette sans bloquer quoi que ce soit, et
     quatre la portaient en etat GRIS « non declare ». On lisait « ○ Un seul
     agent par machine · bloquant · non declare » et on comprenait
     « garde-fou arme, mesure indisponible », alors que la realite est
     « garde-fou desarme, il ne bloquera jamais ». Sur le garde-fou de la
     panne fondatrice, c'est la pire confusion possible. */
  function etiqueteControle(c) {
    if (c.bloque) return '<span class="r2-etiq r2-etiq-bloque">bloque le demarrage</span>';
    if (!c.bloquant_si_rouge) return '';
    if (c.gravite === 'gris') {
      return '<span class="r2-etiq r2-etiq-inerte" data-tip="Ce controle bloquerait '
        + 'le demarrage s’il passait au rouge, mais il n’est pas mesure : il ne '
        + 'bloquera pas.">ne bloque pas — non mesure</span>';
    }
    return '<span class="r2-etiq r2-etiq-inerte" data-tip="Ce controle ne bloque '
      + 'le demarrage que s’il passe au rouge.">bloquant si rouge</span>';
  }
  /* Ce que fait le pilote, EN CE MOMENT et en une phrase. Le bandeau
     annoncait en dur « l'execution n'est pas branchee » : c'etait vrai, ce
     ne l'est plus, et un bandeau qui ment sur l'etat du parc est pire que
     pas de bandeau du tout. */
  function etatPiloteTexte() {
    var r = (S.etat || {}).regles || {};
    var tick = Number(r.tick_s || 60);
    if (!r.pilote) {
      return 'Le pilote est A L’ARRET. L’horloge continue de jouer un tour toutes '
        + 'les ' + tick + ' s et journalise ce qui AURAIT ete lance — c’est ce qui '
        + 'permet de lire au matin ce que le parc aurait fait. Aucun travail n’est '
        + 'inscrit dans la file du poste tant que le parc n’est pas demarre.';
    }
    return 'Le pilote TOURNE. L’horloge joue un tour toutes les ' + tick + ' s : elle '
      + 'calcule le plan, verifie le pre-vol, puis inscrit les travaux dus dans la '
      + 'file du poste (au plus ' + Number(r.lot_par_tick || 3) + ' par tour, et '
      + 'seulement pour un telephone libre).';
  }

  function ligneControle(c) {
    var a = c.action || {};
    return '<div class="r2-pvl">'
      + '<i class="r2-pt ' + classeGravite(c.gravite) + '"></i>'
      + '<div class="r2-pvl-n">' + marque(c.provenance) + ' ' + esc(c.nom)
      + ' ' + etiqueteControle(c) + '</div>'
      + '<div class="r2-pvl-v">' + esc(c.valeur) + (c.age ? ' <span class="r2-faible">il y a '
        + esc(c.age) + '</span>' : '') + '</div>'
      + '<div class="r2-pvl-m">' + esc(c.message)
      + (c.source ? ' <span class="r2-faible">source : ' + esc(c.source) + '</span>' : '')
      + '</div>'
      + '<div class="r2-pvl-a">'
      + (a.quoi ? '<button class="r2-b3" data-r2act="pv-action" data-r2id="' + esc(a.quoi) + '">'
        + esc(a.libelle) + '</button>' : '')
      + '</div>'
      + '</div>';
  }

  /* ================================================================
     ZONE D — LES MACHINES (etage 1)
     La machine est une dimension de premier plan, pas une colonne ajoutee
     apres coup : une ligne par telephone, les MUETTES EN HAUT.
     ================================================================ */
  function rendreD() {
    var z = zone('r2-d');
    if (!z || !S.etat) return;
    var m = S.etat.machines || {lignes: []};
    var lignes = (m.lignes || []).map(function (x) {
      var etats = {travail: 'Au travail', attente: 'En attente', muette: 'Muette',
                   suspendue: 'Suspendue'};
      var verrouCls = x.verrou && x.verrou.pid ? '' : 'r2-g-rouge';
      return '<div class="r2-mrow r2-mgrid' + (x.etat === 'muette' ? ' r2-mrow-muette' : '') + '">'
        + '<i class="r2-pt ' + classeGravite(x.etat === 'travail' ? 'vert'
          : (x.etat === 'attente' ? 'bleu' : (x.etat === 'muette' ? 'rouge' : 'ambre'))) + '"></i>'
        + '<div><b>' + esc(x.nom) + '</b>'
        + (x.identifiee ? '' : ' <span class="r2-faible">(non identifie)</span>') + '</div>'
        + '<div>' + esc(etats[x.etat] || x.etat) + '</div>'
        + '<div class="' + verrouCls + '">' + marque((x.verrou || {}).provenance)
        + ' ' + esc(x.verrou_texte || '') + '</div>'
        + '<div>' + esc(x.fait_quoi || '—') + '</div>'
        + '<div>' + num((x.aujourdhui || {}).fini) + ' fini · '
        + num((x.aujourdhui || {}).echec) + ' echec</div>'
        + '<div class="' + ((x.aujourdhui || {}).echecs_1h ? 'r2-g-rouge' : '') + '">'
        + num((x.aujourdhui || {}).echecs_1h) + '</div>'
        + '<div>' + barre(x.charge_pct) + '</div>'
        + '<div><button class="r2-b3" data-r2act="tiroir-machine" data-r2id="'
        + esc(x.nom) + '">⋯</button></div>'
        + (x.phrase ? '<div class="r2-mrow-p">' + esc(x.phrase) + '</div>' : '')
        + '</div>';
    }).join('');

    z.innerHTML = '<div class="r2-carte" id="r2-machines">'
      + '<div class="r2-tete"><div class="r2-h">Machines</div>'
      + '<div class="r2-sous">Les muettes en haut : a l’echelle, ce qu’on cherche '
      + 'c’est le poste qui ne parle plus.</div></div>'
      + '<div class="r2-scroll"><div class="r2-mtbl">'
      + '<div class="r2-mhead r2-mgrid">'
      + '<span></span><span>Machine</span><span>Etat</span><span>Tient le telephone</span>'
      + '<span>Fait quoi</span><span>Aujourd’hui</span><span>Echecs 1 h</span>'
      + '<span>Charge prevue</span><span></span></div>'
      + (lignes || '<div class="r2-vide">Aucune machine connue.</div>')
      + '</div></div>'
      + (m.pied ? '<div class="r2-pied">' + esc(m.pied) + '</div>' : '')
      + (m.note_identite ? '<div class="r2-pied r2-g-ambre">' + esc(m.note_identite) + '</div>' : '')
      + '</div>';
  }
  function barre(pct) {
    var p = Math.max(0, Math.min(150, Number(pct || 0)));
    var cls = p > 100 ? 'r2-g-rouge' : (p > 70 ? 'r2-g-ambre' : 'r2-g-vert');
    return '<span class="r2-jauge"><i class="' + cls + '" style="width:'
      + Math.min(100, p) + '%"></i></span> <span class="r2-faible">' + p + ' %</span>';
  }

  /* ================================================================
     ZONE E — LE PARC (agrege d'abord, detail a la demande)
     ================================================================ */
  function rendreE() {
    var z = zone('r2-e');
    if (!z || !S.etat) return;
    var p = S.etat.parc || {lignes: []};
    var ag = (p.lignes || []).map(function (L) {
      var ouvert = S.ouvert.det === L.categorie;
      return '<div class="r2-arow r2-agrid' + (L.avertissement ? ' r2-arow-warn' : '') + '">'
        + '<button class="r2-b3" data-r2act="parc-deplier" data-r2id="' + esc(L.categorie) + '">'
        + (ouvert ? '▾' : '▸') + '</button>'
        /* La machine d'un conteneur n'est declaree NULLE PART : afficher
           « poste-1 » ici etait une attribution inventee dans la seule
           colonne censee porter cette dimension. ○ et le mot, comme
           partout ailleurs. */
        + '<div>' + marque(L.machine_provenance || 'non_declare') + ' '
        + '<span class="r2-faible">' + esc(L.machine_texte || L.machine || '—')
        + '</span></div>'
        + '<div><b>' + esc(L.categorie) + '</b></div>'
        + '<div>' + num(L.comptes) + '</div>'
        + '<div class="r2-g-vert">' + num(L.prets) + '</div>'
        + '<div class="' + (L.echec ? 'r2-g-rouge' : '') + '">' + num(L.echec) + '</div>'
        + '<div class="' + (L.sans_pseudo ? 'r2-g-ambre' : '') + '">' + num(L.sans_pseudo) + '</div>'
        + '<div>' + L.passages_moyens + ' ' + marque('derive') + '</div>'
        + '<div>' + esc(L.derniere_activite_texte) + ' ' + marque('derive') + '</div>'
        + '<div>' + (L.stock_medias === null || L.stock_medias === undefined
          ? '<span class="r2-faible">—</span>'
          : num(L.stock_medias) + ' ' + marque('derive')) + '</div>'
        + (L.avertissement
          ? '<div class="r2-arow-p">⚠ ' + esc(L.avertissement) + '</div>' : '')
        + '</div>';
    }).join('');

    z.innerHTML = '<div class="r2-carte" id="r2-parc">'
      + '<div class="r2-tete"><div class="r2-h">Parc — ' + num(p.total_comptes) + ' comptes</div>'
      + '<div class="r2-onglets r2-onglets-p">'
      + '<button class="r2-onglet' + (S.vueParc === 'agregee' ? ' on' : '') + '" '
      + 'data-r2act="parc-vue" data-r2id="agregee">Agrege (machine x categorie)</button>'
      + '<button class="r2-onglet' + (S.vueParc === 'detaillee' ? ' on' : '') + '" '
      + 'data-r2act="parc-vue" data-r2id="detaillee">Detaille</button>'
      + '</div></div>'
      + (S.vueParc === 'agregee'
        ? '<div class="r2-scroll"><div class="r2-atbl">'
          + '<div class="r2-ahead r2-agrid"><span></span><span>Machine</span><span>Categorie</span>'
          + '<span>Comptes</span><span>Prets</span><span>Echec</span><span>Sans pseudo</span>'
          + '<span>Passages moy.</span><span>Derniere activite</span><span>Stock reels</span></div>'
          + (ag || '<div class="r2-vide">Aucun conteneur declare par le poste.</div>')
          + '</div></div>'
          + '<div class="r2-pied">Une ligne par categorie. '
          + esc(p.note_machine || '') + '</div>'
        : '')
      + rendreRepartition()
      + (S.vueParc === 'detaillee' ? '<div id="r2-parcdet">' + rendreParcDet() + '</div>' : '')
      + '</div>';
  }

  /* L'ECART CIBLE <-> REALITE. Le reglage « repartition » existait, etait
     valide, et son unique consommateur (plan.creations) n'etait rendu nulle
     part : « manque » et « repartition » apparaissaient ZERO fois dans la
     page. Le proprietaire saisissait « 50 conteneurs, 20 beta, 30 test »,
     enregistrait, et ne voyait jamais l'ecart avec la realite. */
  function rendreRepartition() {
    var r = ((S.etat || {}).plan || {}).repartition;
    if (!r || !r.categories || !r.categories.length) return '';
    var lignes = r.categories.map(function (c) {
      var e = c.ecart;
      var cls = e === 0 ? 'r2-g-vert' : (e < 0 ? 'r2-g-ambre' : 'r2-g-bleu');
      var txt = e === 0 ? 'a la cible' : (e < 0 ? (-e) + ' manquant(s)' : '+' + e + ' en trop');
      return '<div class="r2-arow r2-rgrid">'
        + '<div><b>' + esc(c.categorie || '(sans categorie)') + '</b></div>'
        + '<div>' + num(c.actuel) + ' / ' + num(c.vise) + '</div>'
        + '<div class="' + cls + '">' + esc(txt) + '</div>'
        + '</div>';
    }).join('');
    var creations = ((S.etat || {}).plan || {}).creations || [];
    return '<div class="r2-carte r2-sous-carte" id="r2-repartition">'
      + '<div class="r2-h">Repartition — ' + num(r.total_actuel) + ' comptes pour '
      + num(r.objectif_total) + ' vises</div>'
      /* r2-rtbl et non r2-atbl : ce dernier impose min-width:1020px, fait
         pour un tableau a 10 colonnes. Trois colonnes n'ont pas a forcer un
         defilement horizontal. */
      + '<div class="r2-scroll"><div class="r2-rtbl">'
      + '<div class="r2-ahead r2-rgrid"><span>Categorie</span><span>Actuel / cible</span>'
      + '<span>Ecart</span></div>'
      + lignes
      + '</div></div>'
      + '<div class="r2-pied">'
      + (r.sans_categorie
        ? '<b>' + num(r.sans_categorie) + '</b> conteneur(s) sans categorie : '
          + '<b>' + num(r.a_reaffecter) + '</b> peuvent combler un manque en etant '
          + 'simplement CLASSES — les creer serait un compte Instagram pour rien. '
        : '')
      + '<b>' + num(r.a_creer) + '</b> compte(s) restent a creer'
      + (r.surplus ? ' · <b>' + num(r.surplus) + '</b> en trop sur d’autres categories' : '')
      + (r.depassement_evite
        ? ' · <span class="r2-g-ambre">' + num(r.depassement_evite) + ' creation(s) '
          + 'refusee(s) : elles auraient depasse l’objectif total</span>' : '')
      + (r.note_coherence ? ' · <span class="r2-g-ambre">' + esc(r.note_coherence)
        + '</span>' : '')
      + (creations.length
        ? '<div class="r2-sous">Le plan prevoit : '
          + creations.map(function (c) {
            return esc(c.categorie) + ' ' + num(c.a_creer)
              + ' (' + num(c.par_jour) + '/jour)';
          }).join(' · ') + '</div>'
        : '<div class="r2-sous">Aucune creation prevue (creation desactivee, ou '
          + 'rien a creer).</div>')
      + '</div></div>';
  }

  function rendreParcDet() {
    var d = S.parcDet;
    if (!d) return '<div class="r2-vide">Chargement du detail…</div>';
    if (d.ok === false) return '<div class="r2-vide r2-g-rouge">' + esc(d.error || 'erreur') + '</div>';
    var tris = (d.tris || []).map(function (t) {
      return '<option value="' + esc(t.cle) + '"' + (t.cle === d.tri ? ' selected' : '')
        + (t.actif ? '' : ' disabled') + ' title="' + esc(t.note || '') + '">'
        + esc(t.libelle) + (t.actif ? '' : ' — ' + esc(t.note)) + '</option>';
    }).join('');
    var f = d.filtres || {};
    function puce(cle, lib, n) {
      return '<button class="r2-puce' + (S.parcOpts.filtre === cle ? ' on' : '') + '" '
        + 'data-r2act="parc-filtre" data-r2id="' + cle + '">' + lib + ' <b>' + num(n) + '</b></button>';
    }
    var lignes = (d.lignes || []).map(function (L) {
      var traits = (L.etapes || []).map(function (e) {
        var c = e.etat === 'ok' ? 'ok' : (e.etat === 'echec' ? 'ko' : (e.etat ? 'now' : ''));
        return '<i class="' + c + ' hsc-dot" data-tip="' + esc(e.nom + ' : ' + (e.etat || 'pas encore')) + '"></i>';
      }).join('');
      var st = L.statut || '—';
      var stc = st === 'ok' ? 'r2-g-vert' : (st === 'echec' ? 'r2-g-rouge'
        : (st === 'bloque' ? 'r2-g-ambre' : ''));
      return '<tr>'
        + '<td><i class="r2-pt ' + classeGravite(L.quarantaine ? 'ambre'
          : (L.statut === 'echec' ? 'rouge' : (L.statut === 'ok' ? 'vert' : 'gris'))) + '"></i></td>'
        + '<td><b>' + esc(L.nom) + '</b>'
        + (L.refus ? '<div class="r2-faible">⚠ ' + esc(L.refus_detail || L.refus) + '</div>' : '')
        + '</td>'
        + '<td>' + esc(L.categorie || '—') + '</td>'
        + '<td>' + marque(L.machine_provenance || 'non_declare') + ' '
        + '<span class="r2-faible">' + esc(L.machine_texte || L.machine || '—')
        + '</span></td>'
        + '<td>' + (L.pseudo ? esc(L.pseudo) : '<span class="r2-g-ambre">aucun</span>') + '</td>'
        + '<td><span class="r2-tr">' + traits + '</span> <span class="r2-faible">'
        + L.franchies + '/8</span></td>'
        + '<td>' + num(L.passages) + '</td>'
        + '<td>' + esc(L.derniere_activite_texte) + ' ' + marque('derive') + '</td>'
        + '<td>' + (L.premiere_vue ? jourheure(L.premiere_vue) : '—')
        + (L.premiere_vue_approx
          ? ' <span class="r2-faible hsc-dot" data-tip="anterieur a la mise en service de Remote 2 '
            + '— le poste ne transmet pas cree_le">≈</span>' : '')
        + '</td>'
        + '<td class="' + stc + '">' + esc(st) + '</td>'
        + '<td>' + (L.fiabilite === 'reconstitue'
          ? '<span class="r2-g-ambre hsc-dot" data-tip="historique reconstruit par le poste, '
            + 'pas mesure">reconstitue</span>' : 'mesure') + '</td>'
        + '<td>' + num(L.echecs) + '</td>'
        + '<td>' + (L.prochain ? jourheure(L.prochain) : '—')
        + (L.retard ? ' <span class="r2-g-ambre">en retard</span>' : '')
        + '<div class="r2-faible">' + esc(L.raison || '') + '</div></td>'
        + '<td>' + (L.quarantaine
          ? '<button class="r2-b3" data-r2act="ct-rehab" data-r2id="' + esc(L.nom) + '">Rehabiliter</button>'
          : '<button class="r2-b3" data-r2act="ct-quar" data-r2id="' + esc(L.nom) + '">Quarantaine</button>')
        + '</td>'
        + '</tr>';
    }).join('');

    return '<div class="r2-filtres">'
      + '<label class="r2-lab">Trier par</label>'
      + '<select class="r2-champ" data-r2sel="tri">' + tris + '</select>'
      + '<button class="r2-b3" data-r2act="parc-sens">'
      + (S.parcOpts.sens === 'desc' ? '↑ inverse' : '↓ normal') + '</button>'
      + puce('', 'Tous', d.total_brut)
      + puce('sans_pseudo', 'Sans pseudo', f.sans_pseudo)
      + puce('reconstitue', 'Reconstitue', f.reconstitue)
      + puce('quarantaine', 'Quarantaine', f.quarantaine)
      + puce('refuses', 'Refuses au lancement', f.refuses)
      + '<input class="r2-champ" data-r2sel="q" placeholder="chercher un conteneur ou un pseudo" '
      + 'value="' + esc(S.parcOpts.q) + '">'
      + '</div>'
      + (d.note ? '<div class="r2-pied r2-g-ambre">' + esc(d.note) + '</div>' : '')
      + '<div class="r2-scroll"><table class="r2-tbl">'
      + '<thead><tr><th></th>' + th(d, 'Conteneur', 'alpha') + '<th>Categorie</th>'
      + '<th>Machine</th><th>Pseudo</th><th>Etapes</th>'
      + th(d, 'Passages', 'passages_desc', 'passages_asc')
      + th(d, 'Derniere activite', 'recent')
      + th(d, 'Premiere vue', 'cree', 'vieux')
      + '<th>Statut</th><th>Fiabilite</th>' + th(d, 'Echecs', 'echecs')
      + th(d, 'Prochain passage', 'retard') + '<th></th></tr></thead>'
      + '<tbody>' + (lignes || '<tr><td colspan="14" class="r2-vide">Aucune ligne pour ce filtre.</td></tr>')
      + '</tbody></table></div>'
      + '<div class="r2-pied">' + esc(d.pied || '')
      + (d.pages > 1
        ? ' · page ' + d.page + ' / ' + d.pages
          + ' <button class="r2-b3" data-r2act="parc-page" data-r2id="' + (d.page - 1) + '"'
          + (d.page <= 1 ? ' disabled' : '') + '>←</button>'
          + ' <button class="r2-b3" data-r2act="parc-page" data-r2id="' + (d.page + 1) + '"'
          + (d.page >= d.pages ? ' disabled' : '') + '>→</button>'
        : '')
      + '</div>';
  }

  /* En-tete de colonne cliquable. Le proprietaire a demande ces tris
     nommement (« plus recent, dernier cree, plus vieux ») : ils existent
     aussi dans le menu deroulant, mais personne ne va chercher un menu
     quand il a un titre de colonne sous la souris. Un tri indisponible
     reste VISIBLE et dit dans combien de temps il s'active. */
  function th(d, libelle, cle, cle2) {
    var t = (d.tris || []).filter(function (x) { return x.cle === cle; })[0] || {actif: true};
    var actif = d.tri === cle || (cle2 && d.tri === cle2);
    var fleche = actif ? (d.tri === cle ? ' ▼' : ' ▲') : '';
    return '<th class="r2-th' + (actif ? ' on' : '') + (t.actif ? '' : ' r2-th-off') + '" '
      + 'data-r2act="parc-tri" data-r2id="' + esc(cle) + (cle2 ? '|' + esc(cle2) : '') + '" '
      + 'title="' + esc(t.actif ? 'trier par ' + (t.libelle || libelle) : t.note) + '">'
      + esc(libelle) + fleche + '</th>';
  }

  function chargerParcDet() {
    var o = S.parcOpts;
    var u = '/parc/liste?vue=detaillee&tri=' + encodeURIComponent(o.tri)
      + '&sens=' + encodeURIComponent(o.sens) + '&page=' + o.page
      + '&cat=' + encodeURIComponent(o.cat) + '&statut=' + encodeURIComponent(o.statut)
      + '&filtre=' + encodeURIComponent(o.filtre) + '&q=' + encodeURIComponent(o.q);
    lit(u).then(function (j) {
      S.parcDet = j;
      var z = zone('r2-parcdet');
      if (z) z.innerHTML = rendreParcDet();
    }).catch(function (e) {
      S.parcDet = {ok: false, error: String(e.message || e)};
      var z = zone('r2-parcdet');
      if (z) z.innerHTML = rendreParcDet();
    });
  }

  /* ================================================================
     ZONE F — CE QUI CLOCHE / ECARTS / JOURNAL
     ================================================================ */
  function rendreF() {
    var z = zone('r2-f');
    if (!z || !S.etat) return;
    var c = S.etat.causes || {lignes: []};
    var e = S.etat.ecarts || [];
    var nC = (c.lignes || []).length + (c.reste_causes || 0);
    z.innerHTML = '<div class="r2-carte" id="r2-cloche">'
      + '<div class="r2-onglets">'
      + ong('cloche', 'Ce qui cloche' + (nC ? ' (' + nC + ')' : ''))
      + ong('ecarts', 'Ecarts' + (e.length ? ' (' + e.length + ')' : ''))
      + ong('journal', 'Journal')
      + '</div>'
      + '<div id="r2-fcorps">' + corpsF() + '</div>'
      + '</div>';
  }
  function ong(cle, lib) {
    return '<button class="r2-onglet' + (S.ongletF === cle ? ' on' : '') + '" '
      + 'data-r2act="f-onglet" data-r2id="' + cle + '">' + lib + '</button>';
  }
  function corpsF() {
    if (S.ongletF === 'cloche') return corpsCloche();
    if (S.ongletF === 'ecarts') return corpsEcarts();
    return corpsJournal();
  }
  function corpsCloche() {
    var c = (S.etat && S.etat.causes) || {lignes: []};
    if (!(c.lignes || []).length) {
      return '<div class="r2-vide">Aucune anomalie journalisee sur ' + esc(c.fenetre || '24 h')
        + '. Le journal ne commence qu’a l’installation du poste de pilotage : '
        + num((S.etat.journal || {}).lignes_total) + ' ligne(s) ecrite(s) a ce jour.</div>';
    }
    var l = c.lignes.map(function (x) {
      return '<div class="r2-crow">'
        + '<div class="r2-crow-n">' + num(x.n) + '×</div>'
        + '<div><b>' + esc(x.code) + '</b><div class="r2-faible">' + esc(x.exemple || '') + '</div></div>'
        + '<div>derniere il y a ' + esc(x.dernier_age) + '</div>'
        + '<div>' + num(x.machines) + ' machine(s) · ' + num(x.conteneurs) + ' compte(s)</div>'
        + '<div>' + esc(x.conduite || '') + '</div>'
        + '<div><button class="r2-b3" data-r2act="jrn-code" data-r2id="' + esc(x.code)
        + '">Au journal</button></div>'
        + '</div>';
    }).join('');
    return '<div class="r2-ctbl">' + l + '</div>'
      + (c.pied ? '<div class="r2-pied">' + esc(c.pied)
        + ' <button class="r2-b3" data-r2act="jrn-echecs">tout voir au journal</button></div>' : '')
      + (c.inconnu_en_tete
        ? '<div class="r2-pied r2-g-ambre">« inconnu » est la premiere cause : c’est la table '
          + 'des codes qui est a completer, pas le parc qui va bien.</div>' : '');
  }
  function corpsEcarts() {
    var e = (S.etat && S.etat.ecarts) || [];
    if (!e.length) {
      return '<div class="r2-vide">Aucun ecart compte pour l’instant. Cette table repond a '
        + '« qu’est-ce que le pilote n’a pas fait, combien de fois, et que dois-je '
        + 'changer pour que ca cesse ». Elle se remplira au premier tour d’ordonnanceur.'
        + '<div class="r2-pied">Le plan actuel refuserait '
        + num(((S.etat.plan || {}).resume || {}).refuses) + ' conteneur(s) : '
        + esc(motifs(((S.etat.plan || {}).resume || {}).par_motif)) + '.</div></div>';
    }
    var l = e.map(function (x) {
      return '<div class="r2-crow">'
        + '<div class="r2-crow-n">' + num(x.h24) + '</div>'
        + '<div><b>' + esc(x.motif) + '</b><div class="r2-faible">' + esc(x.libelle) + '</div></div>'
        + '<div>total ' + num(x.total) + '</div>'
        + '<div>dernier il y a ' + esc(x.dernier_age) + '<div class="r2-faible">'
        + esc(x.dernier_exemplaire) + '</div></div>'
        + '<div>' + esc(x.conduite) + '</div>'
        + '<div><button class="r2-b3" data-r2act="jrn-code" data-r2id="' + esc(x.motif)
        + '">Au journal</button></div>'
        + '</div>';
    }).join('');
    return '<div class="r2-ctbl">' + l + '</div>'
      + '<div class="r2-pied">24 h · total · dernier exemplaire · conduite a tenir. '
      + 'Ne jamais ecarter en silence : compter et remonter.</div>';
  }
  function motifs(par) {
    var out = [];
    for (var k in (par || {})) {
      if (Object.prototype.hasOwnProperty.call(par, k)) out.push(k + ' ' + par[k]);
    }
    return out.join(', ') || 'aucun';
  }
  function corpsJournal() {
    var j = S.journal;
    var presets = [['1h', 'Derniere heure'], ['24h', '24 heures'], ['7j', '7 jours'],
                   ['echecs', 'Echecs seulement'], ['plan', 'Decisions du pilote'],
                   ['tout', 'Tout']];
    var barre = presets.map(function (p) {
      return '<button class="r2-puce' + (S.jrnPreset === p[0] ? ' on' : '') + '" '
        + 'data-r2act="jrn-preset" data-r2id="' + p[0] + '">' + p[1] + '</button>';
    }).join('')
      + '<input class="r2-champ" data-r2sel="jq" placeholder="chercher dans le journal" value="'
      + esc(S.jrnOpts.q) + '">'
      + '<a class="r2-b3" href="/parc/journal?format=jsonl" '
      + 'title="Export par un vrai lien : un a.click() declenche en script est bloque ici">'
      + 'Exporter (.jsonl)</a>';
    if (!j) {
      return '<div class="r2-filtres">' + barre + '</div>'
        + '<div class="r2-vide">Chargement du journal…</div>';
    }
    if (j.ok === false) {
      return '<div class="r2-filtres">' + barre + '</div>'
        + '<div class="r2-vide r2-g-rouge">' + esc(j.error) + '</div>';
    }
    var l = (j.lignes || []).map(function (x) {
      return '<tr>'
        + '<td>' + jourheure(x.ts) + '</td>'
        + '<td>' + esc(x.machine || '—') + '</td>'
        + '<td>' + esc(x.objet || '') + '</td>'
        + '<td><b>' + esc(x.evt || '') + '</b></td>'
        + '<td>' + esc(x.conteneur || '') + '</td>'
        + '<td>' + (x.duree_s === null || x.duree_s === undefined ? '' : x.duree_s + ' s') + '</td>'
        + '<td>' + (x.code ? '<span class="r2-etiq">' + esc(x.code) + '</span>' : '') + '</td>'
        + '<td class="r2-jd">' + esc(x.detail || '')
        + (x.par ? ' <span class="r2-faible">par ' + esc(x.par) + '</span>' : '') + '</td>'
        + '</tr>';
    }).join('');
    return '<div class="r2-filtres">' + barre + '</div>'
      + '<div class="r2-scroll"><table class="r2-tbl">'
      + '<thead><tr><th>Heure</th><th>Machine</th><th>Objet</th><th>Evenement</th>'
      + '<th>Conteneur</th><th>Duree</th><th>Code</th><th>Detail</th></tr></thead>'
      + '<tbody>' + (l || '<tr><td colspan="8" class="r2-vide">Aucune ligne pour ce filtre. '
        + 'Le journal contient ' + num(j.balaye) + ' ligne(s) balayee(s).</td></tr>') + '</tbody>'
      + '</table></div>'
      + '<div class="r2-pied">' + num(j.total) + ' ligne(s) retenue(s) · '
      + num(j.masquees) + ' masquee(s) · ' + num(j.balaye) + ' balayee(s)'
      + (j.balayage_plafonne ? ' · <b class="r2-g-ambre">balayage plafonne : '
        + 'le journal est plus long que la fenetre de lecture</b>' : '')
      + (j.rotation_disponible ? ' · une rotation existe (parc_journal.1.jsonl)' : '')
      + (j.pages > 1
        ? ' · page ' + j.page + ' / ' + j.pages
          + ' <button class="r2-b3" data-r2act="jrn-page" data-r2id="' + (j.page - 1) + '"'
          + (j.page <= 1 ? ' disabled' : '') + '>←</button>'
          + ' <button class="r2-b3" data-r2act="jrn-page" data-r2id="' + (j.page + 1) + '"'
          + (j.page >= j.pages ? ' disabled' : '') + '>→</button>'
        : '')
      + '</div>';
  }
  function chargerJournal() {
    var o = S.jrnOpts;
    var u = '/parc/journal?page=' + o.page + '&depuis=' + o.depuis
      + '&evt=' + encodeURIComponent(o.evt) + '&objet=' + encodeURIComponent(o.objet)
      + '&code=' + encodeURIComponent(o.code) + '&machine=' + encodeURIComponent(o.machine)
      + '&conteneur=' + encodeURIComponent(o.conteneur) + '&q=' + encodeURIComponent(o.q)
      + '&par_page=' + (((S.etat || {}).regles || {}).lignes_journal || 100);
    lit(u).then(function (j) {
      S.journal = j;
      var z = zone('r2-fcorps');
      if (z && S.ongletF === 'journal') z.innerHTML = corpsJournal();
    }).catch(function (e) {
      S.journal = {ok: false, error: String(e.message || e)};
      var z = zone('r2-fcorps');
      if (z && S.ongletF === 'journal') z.innerHTML = corpsJournal();
    });
  }

  /* ================================================================
     ZONE G — LE PIED : ce qui reste dans Remote 1, et pourquoi
     ================================================================ */
  function rendreG() {
    var z = zone('r2-g');
    if (!z) return;
    z.innerHTML = '<div class="r2-carte">'
      + '<div class="r2-h">Ce qui reste dans Remote</div>'
      + '<div class="r2-renvois">'
      + renvoi('console', 'Voir l’ecran du telephone ↗',
        'Le flux de 1,5 s et la conversion pixel→point y sont deja justes. Et le garde-fou '
        + 'dit qu’on ne doit PAS regarder pendant un travail : l’integrer ici '
        + 'encouragerait la manoeuvre qui a fait tomber WebDriverAgent le 21/08.')
      + renvoi('editeur', 'Editer un scenario ↗',
        'Douze garde-fous d’edition y sont ecrits et verifies par tests_site.py. '
        + 'Les reimplementer serait les affaiblir. Remote 2 se contente de refuser un '
        + 'scenario incompatible et de renvoyer dessus.')
      + renvoi('cycle', 'Lancer un cycle a la main ↗',
        'Le travail hors plan doit rester visiblement hors plan — l’observateur '
        + 'le trace comme tel.')
      + '</div>'
      + '<div class="r2-pied-actions">'
      + '<button class="r2-b2" data-r2act="tick">Jouer un tour d’ordonnanceur maintenant</button>'
      + '<button class="r2-b2" data-r2act="tiroir-inventaire">Recenser le telephone</button>'
      + '<span class="r2-sous">Ce bouton joue le tour EN SIMULATION : il calcule '
      + 'le plan, le journalise et compte les ecarts, sans rien inscrire dans la '
      + 'file du poste. C’est l’horloge, et elle seule, qui inscrit.</span>'
      + '</div>'
      + '<div class="r2-partage">Remote 2 pilote et surveille. Remote ouvre le capot.</div>'
      + '</div>';
  }
  function renvoi(cle, lib, pourquoi) {
    return '<div class="r2-renvoi">'
      + '<button class="r2-lien" data-r2act="remote1" data-r2id="' + cle + '">' + lib + '</button>'
      + '<div class="r2-sous">' + pourquoi + '</div></div>';
  }

  /* ================================================================
     LES TIROIRS (etage 2) — reglages, provenance, correctifs, machine,
     inventaire. Jamais affiches en permanence : on ouvre Remote 2 et on
     voit un cockpit, pas un formulaire.
     ================================================================ */
  function rendreTiroir() {
    var t = zone('r2-tiroir');
    var v = zone('r2-voile');
    if (!t || !v) return;
    if (!S.tiroir) {
      t.classList.remove('ouvert');
      v.classList.remove('ouvert');
      t.setAttribute('aria-hidden', 'true');
      t.innerHTML = '';
      return;
    }
    t.classList.add('ouvert');
    v.classList.add('ouvert');
    t.setAttribute('aria-hidden', 'false');
    var h = '';
    if (S.tiroir === 'reglages') h = tiroirReglages();
    else if (S.tiroir === 'provenance') h = tiroirProvenance();
    else if (S.tiroir === 'correctifs') h = tiroirCorrectifs();
    else if (S.tiroir === 'machine') h = tiroirMachine();
    else if (S.tiroir === 'inventaire') h = tiroirInventaire();
    t.innerHTML = h;
  }

  /* ---------------------------------------------------- tiroir : reglages */
  function tiroirReglages() {
    var e = S.etat || {};
    var meta = e.regles_meta || [];
    var val = S.brouillon || {};
    var profils = e.profils || {};
    var pcourant = val.profil || 'croisiere';

    var boutonsProfil = Object.keys(profils).map(function (k) {
      var p = profils[k];
      return '<button class="r2-prof' + (pcourant === k ? ' on' : '') + '" '
        + 'data-r2act="profil" data-r2id="' + esc(k) + '">'
        + '<b>' + esc(p.titre) + '</b><span>' + esc(p.quand) + '</span></button>';
    }).join('');

    var corps = GROUPES.map(function (g) {
      var lignes = meta.filter(function (m) { return m.groupe === g[0]; })
        .map(function (m) { return ligneReglage(m, val); }).join('');
      if (!lignes) return '';
      return '<div class="r2-rgroupe"><div class="r2-h2">' + esc(g[1]) + '</div>'
        + '<div class="r2-sous">' + esc(g[2]) + '</div>' + lignes + '</div>';
    }).join('');

    var corrections = S.corriges.length
      ? '<div class="r2-corr">Le serveur a corrige ' + S.corriges.length + ' valeur(s) — '
        + 'affichees en clair plutot qu’appliquees en douce :<ul>'
        + S.corriges.map(function (c) {
          return '<li><b>' + esc(c.champ) + '</b> : demande ' + esc(JSON.stringify(c.demande))
            + ', retenu ' + esc(JSON.stringify(c.retenu)) + ' — ' + esc(c.motif) + '</li>';
        }).join('') + '</ul></div>'
      : '';

    return '<div class="r2-tiroir-t">'
      + '<div class="r2-h">Reglages du parc</div>'
      + '<button class="r2-b3" data-r2act="tiroir-fermer">Fermer</button></div>'
      + (S.modifies.length
        ? '<div class="r2-bandeau r2-g-ambre"><div class="r2-bandeau-t">'
          + S.modifies.length + ' reglage(s) modifie(s), non enregistres</div>'
          + '<div class="r2-bandeau-x">Le pilote tourne encore sur l’ancien plan : '
          + esc(S.modifies.join(', ')) + '</div></div>'
        : '')
      + corrections
      + '<div class="r2-profils">' + boutonsProfil + '</div>'
      + '<div class="r2-sous">Un profil pre-remplit tous les reglages qu’il nomme ; '
      + 'le reste revient aux valeurs d’usine. Modifier un champ bascule sur '
      + '« personnalise » — on ne laisse jamais croire qu’on tourne sur '
      + 'Croisiere alors que non.</div>'
      + corps
      + '<div class="r2-tiroir-p">'
      + '<button class="r2-b1 r2-b1-plein_vert r2-b1-petit" data-r2act="reg-enregistrer">Enregistrer</button>'
      + '<button class="r2-b2" data-r2act="reg-annuler">Annuler</button>'
      + '<button class="r2-b2" data-r2act="reg-usine">Valeurs d’usine</button>'
      + '</div>';
  }

  function ligneReglage(m, val) {
    var v = val[m.cle];
    var ctrl = '';
    var cle = esc(m.cle);
    if (m.type === 'bool') {
      ctrl = '<label class="r2-bascule"><input type="checkbox" data-r2reg="' + cle + '"'
        + (v ? ' checked' : '') + '><span></span></label>';
    } else if (m.type === 'int') {
      ctrl = '<input class="r2-champ r2-champ-n" type="number" data-r2reg="' + cle + '" '
        + 'value="' + esc(v) + '" min="' + esc(m.min === undefined ? 0 : m.min) + '" '
        + 'max="' + esc(m.max === undefined ? 999999 : m.max) + '"'
        + (m.verrou ? ' disabled' : '') + '>'
        + (m.unite ? '<span class="r2-unite">' + esc(m.unite) + '</span>' : '')
        + (m.verrou ? '<span class="r2-cadenas hsc-dot" data-tip="' + esc(m.pourquoi)
          + '">🔒 contrainte physique</span>' : '');
    } else if (m.type === 'choix') {
      ctrl = '<select class="r2-champ" data-r2reg="' + cle + '">'
        + (m.choix || []).map(function (c) {
          return '<option value="' + esc(c) + '"' + (c === v ? ' selected' : '') + '>'
            + esc(LIB[c] || c) + '</option>';
        }).join('') + '</select>';
    } else if (m.type === 'texte') {
      ctrl = '<input class="r2-champ" type="text" data-r2reg="' + cle + '" value="' + esc(v) + '"'
        + (m.cle === 'canal_webhook' ? ' placeholder="https://discord.com/api/webhooks/… '
          + '(vide = aucune alerte Discord)"' : '') + '>';
    } else if (m.type === 'lecture') {
      ctrl = '<input class="r2-champ" type="text" value="' + esc(v) + '" disabled>'
        + '<span class="r2-cadenas hsc-dot" data-tip="' + esc(m.pourquoi) + '">🔒</span>';
    } else if (m.type === 'jours') {
      ctrl = '<div class="r2-jours">' + JOURS.map(function (j, i) {
        return '<button class="r2-jour' + ((v || [])[i] ? ' on' : '') + '" '
          + 'data-r2act="jour" data-r2id="' + i + '">' + j + '</button>';
      }).join('') + '</div>';
    } else if (m.type === 'plage') {
      ctrl = '<input class="r2-champ r2-champ-h" type="time" data-r2reg="' + cle + ':0" value="'
        + esc((v || [])[0]) + '"> → '
        + '<input class="r2-champ r2-champ-h" type="time" data-r2reg="' + cle + ':1" value="'
        + esc((v || [])[1]) + '">';
    } else if (m.type === 'fenetres') {
      ctrl = '<div class="r2-fenetres">' + (v || []).map(function (f, i) {
        return '<div class="r2-fen">'
          + '<input class="r2-champ r2-champ-h" type="time" data-r2reg="fenetres:' + i + ':0" '
          + 'value="' + esc(f[0]) + '"> → '
          + '<input class="r2-champ r2-champ-h" type="time" data-r2reg="fenetres:' + i + ':1" '
          + 'value="' + esc(f[1]) + '">'
          + '<button class="r2-b3" data-r2act="fen-del" data-r2id="' + i + '">✕</button>'
          + '</div>';
      }).join('')
        + '<button class="r2-b3" data-r2act="fen-add">+ ajouter une fenetre</button></div>';
    } else if (m.type === 'repartition') {
      var somme = 0;
      var cats = Object.keys(v || {});
      cats.forEach(function (k) { somme += Number((v || {})[k] || 0); });
      var cible = Number(val.objectif_total || 0);
      ctrl = '<div class="r2-repart">' + cats.map(function (k) {
        return '<div class="r2-rep">'
          + '<span class="r2-rep-n">' + esc(k) + '</span>'
          + '<input class="r2-champ r2-champ-n" type="number" min="0" max="5000" '
          + 'data-r2reg="repartition:' + esc(k) + '" value="' + esc(v[k]) + '">'
          + '<button class="r2-b3" data-r2act="rep-del" data-r2id="' + esc(k) + '">✕</button>'
          + '</div>';
      }).join('')
        + '<div class="r2-rep"><input class="r2-champ" data-r2sel="repnom" '
        + 'placeholder="nouvelle categorie">'
        + '<button class="r2-b3" data-r2act="rep-add">+ ajouter</button></div>'
        + '<div class="' + (somme === cible ? 'r2-faible' : 'r2-g-ambre') + '">somme ' + somme
        + ' pour un objectif de ' + cible
        + (somme === cible ? '' : ' — l’ecart est affiche, rien n’est recale en douce')
        + '</div>'
        + '</div>';
    } else {
      ctrl = '<input class="r2-champ" type="text" data-r2reg="' + cle + '" value="'
        + esc(JSON.stringify(v)) + '">';
    }
    var usine = (m.type === 'jours' || m.type === 'fenetres' || m.type === 'repartition'
      || m.type === 'plage') ? JSON.stringify(m.defaut) : String(m.defaut);
    /* Un reglage qu'on saisit et qui ne fait RIEN doit le dire. Sans ca, on
       collait son webhook Discord, on choisissait « ici + Discord », on
       enregistrait — et on n'etait jamais prevenu de rien. Meme regle que
       « ne jamais ecarter en silence », appliquee aux reglages. */
    return '<div class="r2-rl' + (m.pas_branche ? ' r2-rl-inerte' : '') + '">'
      + '<div class="r2-rl-t">' + esc(m.libelle)
      + (m.pas_branche
        ? ' <span class="r2-etiq r2-etiq-inerte">sans effet pour l’instant</span>' : '')
      + '</div>'
      + '<div class="r2-rl-c">' + ctrl + '</div>'
      + '<div class="r2-rl-u">usine : ' + esc(usine) + '</div>'
      + '<div class="r2-rl-p">' + esc(m.pourquoi)
      + (m.pas_branche
        ? '<div class="r2-rl-inerte-p">⚠ Ce reglage est enregistre mais n’est lu '
          + 'par personne : ' + esc(m.pas_branche) + '</div>' : '')
      + (m.note_lecture
        ? '<div class="r2-sous">' + esc(m.note_lecture) + '</div>' : '')
      + '</div>'
      + '</div>';
  }

  /* -------------------------------------------------- tiroir : provenance */
  function tiroirProvenance() {
    var e = S.etat || {};
    var v = (e.voyants || []).filter(function (x) { return x.cle === S.tiroirId; })[0];
    var ctrls = (e.prevol || {}).controles || [];
    var l = ctrls.map(function (c) {
      return '<tr>'
        + '<td>' + marque(c.provenance) + ' ' + esc(c.nom) + '</td>'
        + '<td>' + esc(c.valeur) + '</td>'
        + '<td class="r2-jd">' + esc(c.source || '—') + '</td>'
        + '<td>' + (c.age ? 'il y a ' + esc(c.age) : '—') + '</td>'
        + '<td class="r2-jd">' + esc(c.message) + '</td>'
        + '</tr>';
    }).join('');
    return '<div class="r2-tiroir-t"><div class="r2-h">D’ou vient ce chiffre</div>'
      + '<button class="r2-b3" data-r2act="tiroir-fermer">Fermer</button></div>'
      + (v
        ? '<div class="r2-carte r2-carte-in">'
          + '<div class="r2-h2">' + marque(v.provenance) + ' ' + esc(v.nom) + '</div>'
          + '<div class="r2-tuile-v ' + classeGravite(v.gravite) + '">' + esc(v.valeur) + '</div>'
          + '<div class="r2-sous">Source : <b>' + esc(v.source) + '</b> · ecrit il y a '
          + esc(v.age) + '</div>'
          + '<div class="r2-tuile-p">' + esc(v.sens) + '</div></div>'
        : '')
      + '<div class="r2-h2">Les ' + ctrls.length + ' controles et leur provenance</div>'
      + '<div class="r2-scroll"><table class="r2-tbl">'
      + '<thead><tr><th>Indicateur</th><th>Valeur</th><th>Fichier source</th>'
      + '<th>Ecrit il y a</th><th>Ce que ca veut dire</th></tr></thead>'
      + '<tbody>' + l + '</tbody></table></div>'
      + '<div class="r2-pied">● mesure par le poste · ◐ derive par le site · '
      + '○ non declare. Un ○ n’est jamais un vert par defaut : un controle '
      + 'qu’on ne peut pas faire n’est pas un controle reussi.</div>';
  }

  /* -------------------------------------------------- tiroir : correctifs */
  function tiroirCorrectifs() {
    var pv = (S.etat || {}).prevol || {};
    var l = (pv.correctifs_poste || []).map(function (c) {
      return '<li>' + esc(c) + '</li>';
    }).join('');
    return '<div class="r2-tiroir-t"><div class="r2-h">Ce que le poste ne dit pas encore</div>'
      + '<button class="r2-b3" data-r2act="tiroir-fermer">Fermer</button></div>'
      + '<div class="r2-sous">' + (pv.non_declares || 0) + ' indicateur(s) restent ○ parce '
      + 'que l’agent ne les transmet pas. Chacun est un controle que Remote 2 ne peut PAS '
      + 'faire — affiche en gris, jamais en vert.</div>'
      + '<ul class="r2-liste">' + (l || '<li>aucun</li>') + '</ul>'
      + '<div class="r2-pied">Le jour ou ces champs arrivent dans le corps de '
      + '/api/rig/pull, les controles passent ● tout seuls : aucune ligne d’interface '
      + 'a changer.</div>';
  }

  /* ----------------------------------------------------- tiroir : machine */
  function tiroirMachine() {
    var m = (((S.etat || {}).machines || {}).lignes || []).filter(function (x) {
      return x.nom === S.tiroirId;
    })[0];
    if (!m) return '<div class="r2-vide">Machine inconnue.</div>';
    var occupe = m.jobs_en_cours > 0;
    return '<div class="r2-tiroir-t"><div class="r2-h">' + esc(m.nom) + '</div>'
      + '<button class="r2-b3" data-r2act="tiroir-fermer">Fermer</button></div>'
      + '<div class="r2-carte r2-carte-in">'
      + '<div>Etat : <b>' + esc(m.etat) + '</b> · silence ' + esc(m.silence) + '</div>'
      + '<div>' + marque((m.verrou || {}).provenance) + ' ' + esc(m.verrou_texte) + '</div>'
      + '<div>Battements observes : ' + num(m.battements) + ' · prises rapprochees : '
      + num(m.pulls_rapides)
      + ' <span class="r2-faible">(deux prises a moins de 8 s = signature de deux agents '
      + 'empiles)</span></div>'
      + (m.phrase ? '<div class="r2-g-ambre">' + esc(m.phrase) + '</div>' : '')
      + '</div>'
      + '<div class="r2-tiroir-p">'
      + (m.suspendue
        ? '<button class="r2-b2" data-r2act="mach-reprendre" data-r2id="' + esc(m.nom)
          + '">Reprendre cette machine</button>'
        : '<button class="r2-b2" data-r2act="mach-suspendre" data-r2id="' + esc(m.nom)
          + '">Suspendre cette machine</button>')
      + '<button class="r2-b2" data-r2act="remote1" data-r2id="console"'
      + (occupe ? ' disabled title="Un travail tourne : regarder l’ecran pendant un '
        + 'travail est ce qui a fait tomber WebDriverAgent le 21/08"' : '')
      + '>Voir son ecran (Remote) ↗</button>'
      + '<button class="r2-b2" data-r2act="jrn-machine" data-r2id="' + esc(m.nom)
      + '">Son journal</button>'
      + '</div>'
      + '<div class="r2-pied">Vider la file et degripper un travail ne sont pas proposes : '
      + 'Remote 2 n’ecrit pas encore dans rig_jobs.json. Un bouton qui ne fait rien serait '
      + 'pire que pas de bouton.</div>';
  }

  /* --------------------------------------------------- tiroir : inventaire */
  function tiroirInventaire() {
    var ex = '{\n "conteneurs": ["ig-445bt", "ig-7h079"],\n "releve_le": "21/08 02:24",\n'
      + ' "note": "recensement fait a la main sur le telephone"\n}';
    return '<div class="r2-tiroir-t"><div class="r2-h">Recenser le telephone</div>'
      + '<button class="r2-b3" data-r2act="tiroir-fermer">Fermer</button></div>'
      + '<div class="r2-sous">C’est la SEULE chose qui peut rendre vert le controle '
      + '« le registre correspond au telephone ». Personne n’a jamais confronte le registre '
      + 'a la realite : c’est ce qui a produit « 87 conteneurs pour 33 reels ».</div>'
      + '<textarea class="r2-champ r2-txt" data-r2sel="inv" rows="12">' + esc(ex) + '</textarea>'
      + '<div class="r2-tiroir-p">'
      + '<button class="r2-b1 r2-b1-plein_vert r2-b1-petit" data-r2act="inv-envoyer">'
      + 'Enregistrer le recensement</button>'
      + '</div>'
      + '<div class="r2-pied">Le poste pourrait le pousser tout seul : '
      + 'inventaire_telephone.json vers POST /parc/inventaire.</div>';
  }

  /* ================================================================
     ACTIONS — delegation unique, zero onclick inline.
     ================================================================ */
  function reglagesDeSecours() {
    /* Le brouillon part TOUJOURS des reglages effectifs renvoyes par le
       serveur : jamais d'un formulaire vide. « Aucun champ vide nulle
       part » est une regle du cahier des charges. */
    return JSON.parse(JSON.stringify((S.etat && S.etat.regles) || {}));
  }
  function ouvrirReglages() {
    if (!S.brouillon) S.brouillon = reglagesDeSecours();
    S.tiroir = 'reglages';
    rendreTiroir();
  }
  function marquerModifie(cle) {
    if (S.modifies.indexOf(cle) < 0) S.modifies.push(cle);
    armerQuitter();
    simulerBientot();
  }
  /* Le garde de sortie est pose UNE fois (voir brancher) et consulte
     S.modifies. On n'ecrit pas window.onbeforeunload : deux autres endroits
     du site posent deja un ecouteur beforeunload (web_upload.py:9107 et
     36922) et l'affectation directe les aurait laisses en place mais aurait
     ecrase tout futur handler pose de la meme facon. */
  function armerQuitter() { /* rien a faire : le garde lit S.modifies */ }
  function simulerBientot() {
    if (S.simTempo) clearTimeout(S.simTempo);
    S.simTempo = setTimeout(function () {
      poste('/parc/simuler', {regles: JSON.stringify(S.brouillon || {})})
        .then(function (j) {
          if (j && j.ok) {
            S.apercu = {tuiles: j.tuiles};
            S.corriges = j.corriges || [];
            rendreB();
            rendreTiroir();
          }
        }).catch(function () { /* la simulation n'ecrit rien : un echec est sans effet */ });
    }, 400);
  }

  function ancre(cle) {
    var m = {machines: 'r2-machines', prevol: 'r2-prevol', ruban: 'r2-ruban',
             bouton: 'r2-a', cloche: 'r2-cloche', parc: 'r2-parc'};
    var el = document.getElementById(m[cle] || 'r2-a');
    if (el && el.scrollIntoView) el.scrollIntoView({behavior: 'smooth', block: 'center'});
  }

  function confirmer(cle) {
    /* Deux clics de 4 s : le premier arme, le second agit. Un geste qui
       arrete ou demarre un parc entier ne part pas sur un clic. */
    if (S.confirm.cle === cle && S.confirm.jusqu > Date.now()) {
      S.confirm = {cle: '', jusqu: 0};
      return true;
    }
    S.confirm = {cle: cle, jusqu: Date.now() + 4000};
    rendreA();
    setTimeout(function () {
      if (S.confirm.cle === cle && S.confirm.jusqu <= Date.now()) {
        S.confirm = {cle: '', jusqu: 0};
        rendreA();
      }
    }, 4200);
    return false;
  }

  function agir(act, id, cible) {
    if (act === 'recharger') { charger(false); return; }
    if (act === 'ancre') { ancre(id); return; }
    if (act === 'rien') { return; }

    if (act === 'pilote-on') {
      if (!confirmer('pilote-on')) return;
      var b = (S.etat || {}).bouton || {};
      poste('/parc/pilote', {on: '1', force: b.etat === 'reserves' ? '1' : '0'})
        .then(function (j) {
          if (j._echec) return;          /* poste() a deja dit pourquoi */
          if (j.ok) toast('Le pilote demarre.');
          else if (j.confirmation) toast(j.error, 'error');
          else toast(j.error + (j.bloquants ? ' : ' + j.bloquants.join(', ') : ''), 'error');
          charger(false);
        });
      return;
    }
    if (act === 'pilote-off') {
      if (!confirmer('pilote-off')) return;
      poste('/parc/pilote', {on: '0'}).then(function (j) {
        if (j._echec) return;
        toast('Le parc est en pause. Les travaux en attente sont geles, pas annules.');
        charger(false);
      });
      return;
    }
    if (act === 'prevol-rouges') {
      S.ouvert.prevol = true;
      rendreC();
      ancre('prevol');
      return;
    }
    if (act === 'pause') {
      var sel = racine().querySelector('[data-r2sel="pause"]');
      var h = sel ? sel.value : '12';
      poste('/parc/pause', {heures: h}).then(function (j) {
        if (j._echec) return;
        if (j.ok) toast('Pause posee jusqu’a ' + jourheure(j.jusqu_a) + '.');
        else toast(j.error || 'refus', 'error');
        charger(false);
      });
      return;
    }
    if (act === 'tick') {
      poste('/parc/tick', {}).then(function (j) {
        if (j._echec) return;
        toast(j.deja_fait
          ? 'Un tour a deja ete joue cette minute (idempotence).'
          : 'Tour joue en simulation et journalise. Rien n’a ete inscrit : '
            + 'seule l’horloge inscrit dans la file du poste.');
        charger(false);
      });
      return;
    }
    if (act === 'boite') { S.ouvert.boite = !S.ouvert.boite; rendreB(); return; }
    if (act === 'prevol') { S.ouvert.prevol = !S.ouvert.prevol; rendreC(); return; }
    if (act === 'pv-ok') { S.ouvert.pvOk = !S.ouvert.pvOk; rendreC(); return; }
    if (act === 'pv-action') {
      if (id === 'journal') { S.ongletF = 'journal'; rendreF(); chargerJournal(); ancre('cloche'); }
      else if (id === 'ecarts') { S.ongletF = 'ecarts'; rendreF(); ancre('cloche'); }
      else if (id === 'recharger' || id === 'reessayer') {
        charger(false);
        if (id === 'reessayer') {
          toast('Etat redemande. Le site ne peut pas relancer WebDriverAgent a distance : '
            + 'c’est le poste qui le recree.', 'error');
        }
      } else if (id === 'reglages') ouvrirReglages();
      else if (id === 'recenser') { S.tiroir = 'inventaire'; rendreTiroir(); }
      else if (id === 'parc_sans_pseudo') {
        S.vueParc = 'detaillee';
        S.parcOpts.filtre = 'sans_pseudo';
        S.parcOpts.page = 1;
        rendreE();
        chargerParcDet();
        ancre('parc');
      }
      return;
    }
    if (act === 'tiroir-reglages') { ouvrirReglages(); return; }
    if (act === 'tiroir-provenance') { S.tiroir = 'provenance'; S.tiroirId = id; rendreTiroir(); return; }
    if (act === 'tiroir-correctifs') { S.tiroir = 'correctifs'; rendreTiroir(); return; }
    if (act === 'tiroir-machine') { S.tiroir = 'machine'; S.tiroirId = id; rendreTiroir(); return; }
    if (act === 'tiroir-inventaire') { S.tiroir = 'inventaire'; rendreTiroir(); return; }
    if (act === 'tiroir-fermer') { fermerTiroir(); return; }

    if (act === 'parc-vue') {
      S.vueParc = id;
      rendreE();
      if (id === 'detaillee' && !S.parcDet) chargerParcDet();
      return;
    }
    if (act === 'parc-deplier') {
      S.ouvert.det = (S.ouvert.det === id) ? '' : id;
      S.vueParc = 'detaillee';
      S.parcOpts.cat = S.ouvert.det;
      S.parcOpts.page = 1;
      rendreE();
      chargerParcDet();
      return;
    }
    if (act === 'parc-filtre') {
      S.parcOpts.filtre = id;
      S.parcOpts.page = 1;
      chargerParcDet();
      return;
    }
    if (act === 'parc-sens') {
      S.parcOpts.sens = S.parcOpts.sens === 'desc' ? 'asc' : 'desc';
      chargerParcDet();
      return;
    }
    if (act === 'parc-tri') {
      var duo = String(id).split('|');
      var d0 = S.parcDet || {};
      var t0 = (d0.tris || []).filter(function (x) { return x.cle === duo[0]; })[0];
      if (t0 && !t0.actif) { toast(t0.note, 'error'); return; }
      /* Recliquer sur la meme colonne bascule vers son jumeau (le plus de
         passages / le moins), sinon inverse le sens. */
      if (duo[1] && S.parcOpts.tri === duo[0]) S.parcOpts.tri = duo[1];
      else if (duo[1] && S.parcOpts.tri === duo[1]) S.parcOpts.tri = duo[0];
      else if (S.parcOpts.tri === duo[0]) S.parcOpts.sens = S.parcOpts.sens === 'desc' ? 'asc' : 'desc';
      else { S.parcOpts.tri = duo[0]; S.parcOpts.sens = 'asc'; }
      S.parcOpts.page = 1;
      chargerParcDet();
      return;
    }
    if (act === 'parc-page') { S.parcOpts.page = Math.max(1, Number(id)); chargerParcDet(); return; }
    if (act === 'ct-quar') {
      poste('/parc/conteneur/quarantaine', {conteneur: id, motif: 'manuel'}).then(function (j) {
        if (j._echec) return;
        toast(j.modifie ? id + ' est en quarantaine.' : (j.note || 'sans effet'), j.modifie ? 'success' : 'error');
        chargerParcDet();
        charger(false);
      });
      return;
    }
    if (act === 'ct-rehab') {
      poste('/parc/conteneur/rehabiliter', {conteneur: id}).then(function (j) {
        if (j._echec) return;
        toast(j.modifie ? id + ' est rehabilite.' : (j.note || 'sans effet'), j.modifie ? 'success' : 'error');
        chargerParcDet();
        charger(false);
      });
      return;
    }
    if (act === 'mach-suspendre' || act === 'mach-reprendre') {
      poste('/parc/machine/suspendre',
        {machine: id, on: act === 'mach-suspendre' ? '1' : '0'}).then(function (j) {
        if (j._echec) return;
        toast(act === 'mach-suspendre' ? id + ' est suspendue.' : id + ' reprend.');
        fermerTiroir();
        charger(false);
      });
      return;
    }

    if (act === 'f-onglet') {
      S.ongletF = id;
      rendreF();
      if (id === 'journal' && !S.journal) chargerJournal();
      return;
    }
    if (act === 'jrn-code') {
      S.ongletF = 'journal';
      S.jrnOpts.code = id;
      S.jrnOpts.evt = '';
      S.jrnOpts.depuis = 0;
      S.jrnPreset = '';
      S.jrnOpts.page = 1;
      rendreF();
      chargerJournal();
      return;
    }
    if (act === 'jrn-machine') {
      S.ongletF = 'journal';
      S.jrnOpts.machine = id;
      S.jrnOpts.page = 1;
      fermerTiroir();
      rendreF();
      chargerJournal();
      ancre('cloche');
      return;
    }
    if (act === 'jrn-echecs') {
      S.ongletF = 'journal';
      S.jrnPreset = 'echecs';
      S.jrnOpts.evt = 'echec';
      S.jrnOpts.page = 1;
      rendreF();
      chargerJournal();
      return;
    }
    if (act === 'jrn-preset') {
      S.jrnPreset = id;
      S.jrnOpts.page = 1;
      S.jrnOpts.evt = '';
      S.jrnOpts.objet = '';
      S.jrnOpts.code = '';
      if (id === '1h') S.jrnOpts.depuis = 3600;
      else if (id === '24h') S.jrnOpts.depuis = 86400;
      else if (id === '7j') S.jrnOpts.depuis = 604800;
      else if (id === 'echecs') { S.jrnOpts.depuis = 0; S.jrnOpts.evt = 'echec'; }
      else if (id === 'plan') { S.jrnOpts.depuis = 0; S.jrnOpts.evt = 'plan_decision'; }
      else S.jrnOpts.depuis = 0;
      chargerJournal();
      var z = zone('r2-fcorps');
      if (z) z.innerHTML = corpsJournal();
      return;
    }
    if (act === 'jrn-page') { S.jrnOpts.page = Math.max(1, Number(id)); chargerJournal(); return; }

    if (act === 'remote1') {
      /* Aucune reimplementation : on renvoie sur Remote 1, qui reste
         intact. Si l'onglet n'existe pas (deploiement partiel), on le dit
         au lieu de ne rien faire. */
      if (typeof window.showTab !== 'function') {
        toast('L’onglet Remote n’est pas disponible sur cette page.', 'error');
        return;
      }
      window.showTab('remote', 'remote', 'Remote', 'Pilotage de l’iPhone');
      if (typeof window.remoteVue === 'function') {
        window.remoteVue(id === 'console' ? 'console' : (id === 'editeur' ? 'editeur' : 'cycle'));
      }
      return;
    }

    if (act === 'tuile-corr') {
      var p = String(id).split(':');
      var src = S.apercu || (S.etat.tuiles || {});
      var t = (src.tuiles || [])[Number(p[0])];
      var c = t && (t.corrections || [])[Number(p[1])];
      if (!c || !c.champ) return;
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      S.brouillon[c.champ] = c.valeur;
      marquerModifie(c.champ);
      ouvrirReglages();
      toast('« ' + c.libelle + " » est pose dans les reglages, pas encore enregistre.");
      return;
    }
    if (act === 'apercu-annuler') {
      S.apercu = null;
      S.brouillon = null;
      S.modifies = [];
      S.corriges = [];
      armerQuitter();
      rendreB();
      rendreTiroir();
      return;
    }

    if (act === 'profil') {
      if (!window.confirm('Appliquer le profil « ' + id + ' » ? Tous les reglages qu’il '
        + 'nomme sont ecrases, le reste revient aux valeurs d’usine.')) return;
      poste('/parc/regles/profil', {profil: id}).then(function (j) {
        if (j._echec) return;
        if (!j.ok) { toast(j.error || 'refus', 'error'); return; }
        S.brouillon = j.regles;
        S.modifies = [];
        S.corriges = j.corriges || [];
        S.apercu = null;
        armerQuitter();
        toast('Profil ' + id + ' applique.');
        charger(false);
      });
      return;
    }
    if (act === 'reg-enregistrer') {
      poste('/parc/regles', {regles: JSON.stringify(S.brouillon || {})}).then(function (j) {
        if (j._echec) return;
        if (!j.ok) { toast(j.error || 'refus', 'error'); return; }
        S.brouillon = j.regles;
        S.corriges = j.corriges || [];
        S.modifies = [];
        S.apercu = null;
        armerQuitter();
        toast((j.modifies || []).length + ' reglage(s) enregistre(s).');
        if ((j.inconnues || []).length) {
          toast((j.inconnues || []).length + ' cle(s) inconnue(s) ignoree(s) : '
            + j.inconnues.join(', '), 'error');
        }
        charger(false);
      });
      return;
    }
    if (act === 'reg-annuler') {
      S.brouillon = reglagesDeSecours();
      S.modifies = [];
      S.corriges = [];
      S.apercu = null;
      armerQuitter();
      rendreB();
      rendreTiroir();
      return;
    }
    if (act === 'reg-usine') {
      if (!window.confirm('Remettre TOUS les reglages a leur valeur d’usine ?')) return;
      var usine = {};
      ((S.etat || {}).regles_meta || []).forEach(function (m) { usine[m.cle] = m.defaut; });
      usine.pilote = (S.etat.regles || {}).pilote;   // le pilote n'est pas un reglage : c'est une commande
      S.brouillon = usine;
      S.modifies = ['(valeurs d’usine)'];
      armerQuitter();
      simulerBientot();
      rendreTiroir();
      return;
    }
    if (act === 'jour') {
      var i = Number(id);
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      var j2 = (S.brouillon.jours || []).slice();
      j2[i] = !j2[i];
      S.brouillon.jours = j2;
      marquerModifie('jours');
      rendreTiroir();
      return;
    }
    if (act === 'fen-add') {
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      S.brouillon.fenetres = (S.brouillon.fenetres || []).concat([['21:00', '23:59']]);
      marquerModifie('fenetres');
      rendreTiroir();
      return;
    }
    if (act === 'fen-del') {
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      var f = (S.brouillon.fenetres || []).slice();
      f.splice(Number(id), 1);
      S.brouillon.fenetres = f;
      marquerModifie('fenetres');
      rendreTiroir();
      return;
    }
    if (act === 'rep-add') {
      var inp = racine().querySelector('[data-r2sel="repnom"]');
      var nom = inp && inp.value.trim();
      if (!nom) { toast('Donnez un nom de categorie.', 'error'); return; }
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      S.brouillon.repartition = S.brouillon.repartition || {};
      S.brouillon.repartition[nom] = 0;
      marquerModifie('repartition');
      rendreTiroir();
      return;
    }
    if (act === 'rep-del') {
      if (!S.brouillon) S.brouillon = reglagesDeSecours();
      delete (S.brouillon.repartition || {})[id];
      marquerModifie('repartition');
      rendreTiroir();
      return;
    }
    if (act === 'inv-envoyer') {
      var ta = racine().querySelector('[data-r2sel="inv"]');
      var txt = ta ? ta.value : '';
      try { JSON.parse(txt); } catch (x) {
        toast('JSON invalide : ' + x.message, 'error');
        return;
      }
      poste('/parc/inventaire', {inventaire: txt}).then(function (j) {
        if (j._echec) return;
        if (!j.ok) { toast(j.error || 'refus', 'error'); return; }
        toast(j.n + ' conteneur(s) reellement presents enregistres.');
        fermerTiroir();
        charger(false);
      });
      return;
    }
    if (cible) { /* action inconnue : on le dit plutot que de ne rien faire */
      toast('Action inconnue : ' + act, 'error');
    }
  }

  function fermerTiroir() {
    if (S.tiroir === 'reglages' && S.modifies.length) {
      if (!window.confirm(S.modifies.length + ' reglage(s) ne sont pas enregistres. Fermer quand meme ?')) return;
      S.brouillon = reglagesDeSecours();
      S.modifies = [];
      S.apercu = null;
      armerQuitter();
      rendreB();
    }
    S.tiroir = '';
    S.tiroirId = '';
    rendreTiroir();
  }

  /* ------------------------------------------------- ecouteurs (une fois) */
  function brancher() {
    var r = racine();
    if (!r || r.__r2Branche) return;
    r.__r2Branche = 1;

    r.addEventListener('click', function (ev) {
      var b = ev.target.closest ? ev.target.closest('[data-r2act]') : null;
      if (!b || !r.contains(b)) return;
      if (b.disabled) return;
      ev.preventDefault();
      agir(b.getAttribute('data-r2act'), b.getAttribute('data-r2id') || '', b);
    });

    r.addEventListener('change', function (ev) {
      var t = ev.target;
      if (!t) return;
      var reg = t.getAttribute && t.getAttribute('data-r2reg');
      if (reg) { poserReglage(reg, t); return; }
      var sel = t.getAttribute && t.getAttribute('data-r2sel');
      if (sel === 'tri') { S.parcOpts.tri = t.value; S.parcOpts.page = 1; chargerParcDet(); }
    });

    r.addEventListener('input', function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      var reg = t.getAttribute('data-r2reg');
      if (reg && t.type !== 'checkbox') { poserReglage(reg, t); return; }
      var sel = t.getAttribute('data-r2sel');
      if (sel === 'q' || sel === 'jq') {
        if (S.qTempo) clearTimeout(S.qTempo);
        var v = t.value;
        S.qTempo = setTimeout(function () {
          if (sel === 'q') { S.parcOpts.q = v; S.parcOpts.page = 1; chargerParcDet(); }
          else { S.jrnOpts.q = v; S.jrnOpts.page = 1; chargerJournal(); }
        }, 400);
      }
    });

    /* Echap ferme le tiroir : c'est le reflexe, et sans lui on cherche la
       croix. */
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && S.tiroir) fermerTiroir();
    });
    var v = zone('r2-voile');
    if (v) v.addEventListener('click', function () { fermerTiroir(); });

    /* Un onglet masque ne sonde pas ; en revenant, il se remet a jour tout
       de suite au lieu d'afficher des chiffres d'il y a une heure. */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && visible()) charger(false);
    });

    /* Quitter avec des reglages non enregistres : meme parade que
       l'editeur de Remote 1, mais posee ici et sans toucher a Remote 1.
       Deux sorties possibles — fermer l'onglet du navigateur, et changer
       d'ecran DANS le site (qui ne declenche pas beforeunload). */
    window.addEventListener('beforeunload', function (ev) {
      if (!S.modifies.length) return;
      ev.preventDefault();
      ev.returnValue = 'Des reglages du parc ne sont pas enregistres.';
    });
    if (typeof window.showTab === 'function' && !window.__r2Quitter) {
      window.__r2Quitter = 1;
      var avant = window.showTab;
      window.showTab = function (groupe, nom) {
        if (S.modifies.length && nom !== 'remote2') {
          if (!window.confirm(S.modifies.length + ' reglage(s) du parc ne sont pas '
            + 'enregistres. Quitter et les perdre ?')) return;
          S.brouillon = reglagesDeSecours();
          S.modifies = [];
          S.apercu = null;
        }
        return avant.apply(this, arguments);
      };
    }
  }

  function poserReglage(chemin, input) {
    if (!S.brouillon) S.brouillon = reglagesDeSecours();
    var p = chemin.split(':');
    var cle = p[0];
    var meta = ((S.etat || {}).regles_meta || []).filter(function (m) {
      return m.cle === cle;
    })[0] || {};
    var val;
    if (input.type === 'checkbox') val = input.checked;
    else if (input.type === 'number') val = input.value === '' ? 0 : Number(input.value);
    else val = input.value;
    if (p.length === 1) {
      S.brouillon[cle] = val;
    } else if (cle === 'repartition') {
      S.brouillon.repartition = S.brouillon.repartition || {};
      S.brouillon.repartition[p[1]] = Number(val) || 0;
    } else if (cle === 'fenetres') {
      var f = (S.brouillon.fenetres || []).map(function (x) { return x.slice(); });
      if (f[Number(p[1])]) f[Number(p[1])][Number(p[2])] = val;
      S.brouillon.fenetres = f;
    } else if (meta.type === 'plage') {
      var pl = (S.brouillon[cle] || []).slice();
      pl[Number(p[1])] = val;
      S.brouillon[cle] = pl;
    }
    marquerModifie(cle);
    /* Le bandeau « non enregistre » doit apparaitre a la premiere frappe,
       mais re-dessiner tout le tiroir volerait le curseur : on ne remet a
       jour que le bandeau. */
    var t = zone('r2-tiroir');
    var b = t && t.querySelector('.r2-bandeau-x');
    if (b) b.textContent = 'Le pilote tourne encore sur l’ancien plan : ' + S.modifies.join(', ');
    else rendreTiroir();
  }

  /* ================================================================
     DEPART
     ================================================================ */
  function demarrer() {
    brancher();
    charger(false);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', demarrer);
  } else {
    demarrer();
  }
})();
