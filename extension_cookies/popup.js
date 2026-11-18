// Le popup, en DEUX étapes (propriétaire, 18/11/2026 : « avec un bouton, je
// fais, et avec un bouton, je valide que ça envoie ») :
//   1. « Prendre les cookies de Chrome » : montre ce que ce Chrome a. Rien ne
//      part, aucune requête.
//   2. « Valider l'envoi à YouLab » : envoie ce qui vient d'être montré, rien
//      d'autre.
//
// Il n'écrit AUCUNE phrase d'état : il affiche celles que le site rend
// (/settings/cookies_etat, les mêmes que Réglages) et le résultat du dernier
// envoi, noté par background.js. Tout passe par textContent : rien de ce qui
// vient du réseau n'est interprété comme du HTML.

// La version de background.js que ce popup sait piloter (celle du manifest).
const ATTENDUE = "2.1";
const SERVICES = [["gms", "GetMySocial"], ["mypuls", "MyPuls"]];
const SIGNES = { ok: "✓", alerte: "⚠", ko: "✗" };

let memoire = null; // le dernier état rendu par le fond
let vu = null;      // l'aperçu de l'étape 1 ; tant qu'il existe, on est à l'étape 2

function date(s) {
  if (!s) return "";
  return new Date(s * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function jour(s) {
  return new Date(s * 1000).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}

function bloc(classe, texte) {
  const d = document.createElement("div");
  d.className = classe;
  d.textContent = texte;
  return d;
}

function aEnvoyer() {
  return vu && vu.empreintes ? Object.keys(vu.empreintes) : [];
}

// Ce que l'étape 1 a trouvé dans Chrome pour un service.
function ligneApercu(a) {
  if (!a.envoyable) return bloc("apercu non", "Ne sera pas envoyé. " + (a.message || ""));
  return bloc("apercu", "Dans ce Chrome : cookie trouvé"
    + (a.exp ? ", valable jusqu’au " + jour(a.exp) : "") + ". "
    + (a.deja ? "Déjà envoyé le " + date(a.deja) + "." : "Pas encore envoyé."));
}

function carte(cle, nom, srv, envoi, a) {
  const niveau = srv && SIGNES[srv.niveau] ? srv.niveau : "";
  const c = document.createElement("div");
  c.className = "service " + niveau;
  const titre = document.createElement("div");
  titre.className = "nom";
  const signe = document.createElement("span");
  signe.className = "signe";
  signe.textContent = (SIGNES[niveau] || "·") + " ";
  titre.appendChild(signe);
  titre.appendChild(document.createTextNode(nom));
  c.appendChild(titre);
  c.appendChild(bloc("texte", srv ? srv.texte || "" : "État inconnu."));
  if (a) {
    // étape 2 : l'état du site, et ce qui va partir. Rien d'autre à lire.
    c.appendChild(ligneApercu(a));
    return c;
  }
  // la consigne générale du site, sauf si le dernier envoi a une raison plus
  // précise à donner (« le cookie a changé »…) : pas deux consignes
  const raison = envoi && !envoi.ok && envoi.message && !envoi.autre_compte;
  if (srv && srv.niveau !== "ok" && srv.aide && !raison) c.appendChild(bloc("petit", srv.aide));
  if (envoi && envoi.ok) {
    c.appendChild(bloc("petit", "Dernier envoi : " + date(envoi.t)));
  } else if (envoi && envoi.message) {
    // un autre compte dans ce Chrome n'est pas une panne : dit sans rouge
    c.appendChild(bloc(envoi.autre_compte ? "petit" : "refus", envoi.message + " (" + date(envoi.t) + ")"));
    if (envoi.autre_compte) {
      const b = document.createElement("button");
      b.className = "lien";
      b.textContent = "Remplacer le compte du site par celui-ci";
      b.addEventListener("click", () => {
        b.disabled = true;
        b.textContent = "Envoi…";
        chrome.runtime.sendMessage({ type: "forcer", cle }, recevoir);
      });
      c.appendChild(b);
    }
    if (envoi.dernier_ok) c.appendChild(bloc("petit", "Dernier envoi réussi : " + date(envoi.dernier_ok)));
  }
  return c;
}

// Les boutons disent toujours où on en est : étape 1, ou étape 2 avec
// « Annuler ». Un aperçu sans rien d'envoyable reste à l'étape 1.
function majBoutons() {
  const b = document.getElementById("envoyer");
  const etape2 = aEnvoyer().length > 0;
  b.disabled = false;
  b.textContent = etape2 ? "2 · Valider l’envoi à YouLab" : "1 · Prendre les cookies de Chrome";
  b.className = etape2 ? "valider" : "";
  document.getElementById("annuler").hidden = !vu;
  document.getElementById("pied").textContent = !vu
    ? "Les cookies vont de ce Chrome à youl4b.com, nulle part ailleurs."
    : etape2 ? "Rien n’est encore parti. Valide pour envoyer à youl4b.com."
      : "Rien à envoyer pour l’instant.";
}

function afficher() {
  const boite = document.getElementById("services");
  const alerte = document.getElementById("site");
  if (!memoire) {
    alerte.hidden = true;
    boite.textContent = "L’extension n’a pas répondu : ferme ce panneau et rouvre-le.";
    majBoutons();
    return;
  }
  const site = memoire.site || null;
  const envois = memoire.envois || {};
  alerte.hidden = !site || site.connecte;
  alerte.textContent = site && !site.connecte ? "✗ " + (site.message || "youl4b.com n’a pas répondu.") : "";
  boite.textContent = "";
  for (const [cle, nom] of SERVICES) {
    const srv = site && site.connecte ? (site.services || []).find((x) => x.cle === cle) : null;
    const a = vu && vu.services ? vu.services[cle] || null : null;
    boite.appendChild(carte(cle, nom, srv || null, envois[cle] || null, a));
  }
  majBoutons();
}

// La réponse du fond à un envoi : l'état frais, et retour à l'étape 1.
function recevoir(m) {
  vu = null;
  memoire = chrome.runtime.lastError ? null : m || null;
  afficher();
}

document.getElementById("envoyer").addEventListener("click", (ev) => {
  const b = ev.currentTarget;
  const cles = aEnvoyer();
  b.disabled = true; // deux clics rapprochés n'envoient pas deux fois
  if (!cles.length) {
    b.textContent = "Lecture…";
    chrome.runtime.sendMessage({ type: "apercu" }, (a) => {
      vu = chrome.runtime.lastError ? null : a || null;
      afficher();
    });
    return;
  }
  b.textContent = "Envoi…";
  chrome.runtime.sendMessage({ type: "envoyer", empreintes: vu.empreintes }, recevoir);
});

document.getElementById("annuler").addEventListener("click", () => {
  vu = null;
  afficher();
});

// D'abord ce qu'on savait (immédiat), puis l'état frais lu sur le site.
function demarrer() {
  chrome.runtime.sendMessage({ type: "memoire" }, (m) => {
    if (!chrome.runtime.lastError && m && m.site) {
      memoire = m;
      afficher();
    }
    chrome.runtime.sendMessage({ type: "etat" }, (frais) => {
      memoire = chrome.runtime.lastError ? null : frais || null;
      afficher();
    });
  });
}

// Chrome relit ce fichier sur le disque à chaque ouverture, mais garde
// l'ancien background.js tant que l'extension n'est pas rechargée. Si le fond
// n'est pas à la version attendue, on recharge l'extension UNE fois (le
// panneau se ferme, il suffit de le rouvrir) ; si ça ne suffit pas, on le dit
// au lieu de recharger en boucle.
chrome.runtime.sendMessage({ type: "version" }, (v) => {
  if (!chrome.runtime.lastError && v === ATTENDUE) return demarrer();
  const boite = document.getElementById("services");
  document.getElementById("envoyer").disabled = true;
  chrome.storage.local.get("rechargee_pour", (o) => {
    if (o && o.rechargee_pour === ATTENDUE) {
      boite.textContent = "L’extension doit être rechargée à la main : ouvre chrome://extensions "
        + "et clique la flèche ronde sur « Cookies → youl4b ».";
      return;
    }
    boite.textContent = "Mise à jour de l’extension… rouvre ce panneau.";
    chrome.storage.local.set({ rechargee_pour: ATTENDUE }, () => chrome.runtime.reload());
  });
});
