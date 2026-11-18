// Remet à youl4b.com les cookies de session dont le site a besoin et qu'il
// ne peut prendre que dans le navigateur du propriétaire :
//
//   GetMySocial  authToken   30 jours. Sans lui, l'API privée (A/B des liens
//                            VA) ne répond plus. Échu le 07/11/2026, il
//                            fallait le recopier à la main dans Réglages.
//   MyPuls       REMEMBERME  Le site le renouvelle seul deux fois par jour ;
//                            il ne meurt que si le mot de passe MyPuls change.
//                            Il sert aux photos des models, aux pushs, aux
//                            factures. Le REMEMBERME seul suffit : le site
//                            s'ouvre sa propre session avec.
//
// Les cookies ne quittent le navigateur que vers https://youl4b.com, sur les
// routes qui existaient déjà pour ça (session admin du site). Ils ne sont
// jamais écrits dans la console ni gardés : seule une empreinte (8 octets de
// SHA-256) est notée, pour ne pas renvoyer dix fois le même.
//
// C'est le SITE qui dit l'état de ses cookies (/settings/cookies_etat) et qui
// refuse le cookie d'un autre compte. L'extension n'écrit aucune de ces
// phrases : deux rédactions auraient fini par se contredire.
//
// Ne PAS ajouter côté site un contrôle Origin == youl4b.com sur ces routes :
// la requête de l'extension porte une origine chrome-extension:// et serait
// refusée. Elles sont protégées par le cookie de session SameSite=Lax, que
// Chrome joint parce que youl4b.com est dans host_permissions.

const SITE = "https://youl4b.com";
// La version de CE fichier, égale à celle du manifest. Chrome relit popup.js
// sur le disque à chaque ouverture, mais garde l'ancien service worker tant
// que l'extension n'est pas rechargée : le popup compare, et recharge si le
// fond est resté en arrière (sinon il parlerait à un fond qui ne le comprend pas).
const VERSION = "2.1";
const RENVOI_S = 24 * 3600; // un même cookie : au plus un essai automatique par jour

const SERVICES = {
  gms: {
    nom: "GetMySocial",
    domaine: "getmysocial.com",
    cookie: "authToken",
    route: "/gms/set_session_cookie",
    champ: "cookie",
    absent: "Pas connecté à GetMySocial dans ce Chrome : ouvre getmysocial.com et connecte-toi.",
  },
  mypuls: {
    nom: "MyPuls",
    domaine: "mypuls.app",
    cookie: "REMEMBERME",
    route: "/mypuls/save_cookies",
    champ: "rememberme",
    absent: "Pas de cookie « Se souvenir de moi » MyPuls dans ce Chrome. Sur mypuls.app : "
      + "déconnecte-toi, puis reconnecte-toi en cochant « Se souvenir de moi ».",
  },
};

function maintenant() {
  return Math.floor(Date.now() / 1000);
}

// L'échéance écrite DANS le jeton GetMySocial (un JWT). Sert à choisir le
// bon cookie quand il y en a plusieurs, et à ne pas envoyer un jeton échu.
function expJeton(v) {
  try {
    const p = String(v).split(".")[1] || "";
    const b64 = p.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (p.length % 4)) % 4);
    const o = JSON.parse(atob(b64));
    return o && typeof o.exp === "number" ? o.exp : null;
  } catch (e) {
    return null;
  }
}

async function empreinte(v) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(v));
  return Array.from(new Uint8Array(b)).slice(0, 8).map((x) => x.toString(16).padStart(2, "0")).join("");
}

// Le cookie peut vivre sur le domaine, sur .domaine ou sur un sous-domaine
// (app.…) : chrome.cookies.get({url}) ne voit pas un cookie posé seulement
// sur un sous-domaine. On les prend tous et on garde celui qui expire le
// plus tard.
async function lireCookie(cle) {
  const s = SERVICES[cle];
  const tous = await chrome.cookies.getAll({ domain: s.domaine, name: s.cookie });
  let mieux = null;
  for (const c of tous) {
    if (!c || !c.value) continue;
    const exp = (cle === "gms" ? expJeton(c.value) : c.expirationDate) || 0;
    if (!mieux || exp > mieux.exp) mieux = { valeur: c.value, exp };
  }
  return mieux;
}

async function lireMemoire() {
  const m = (await chrome.storage.local.get("memoire")).memoire || {};
  return { site: m.site || null, envois: m.envois || {} };
}

async function ecrireMemoire(m) {
  await chrome.storage.local.set({ memoire: m });
}

// fetch vers le site, coupé au bout de `ms`. Chrome arrête le service worker
// d'une extension dont un fetch attend plus de 30 secondes : on coupe avant,
// pour dire « trop long » au lieu de disparaître sans rien noter.
async function appelSite(chemin, options, ms) {
  const coupe = new AbortController();
  const minuteur = setTimeout(() => coupe.abort(), ms);
  try {
    return await fetch(SITE + chemin, Object.assign({
      credentials: "include", redirect: "manual", cache: "no-store",
      headers: { Accept: "application/json" }, signal: coupe.signal,
    }, options || {}));
  } finally {
    clearTimeout(minuteur);
  }
}

// Ce que le site répond quand ce n'est pas du JSON utilisable, en clair.
function refusDuSite(r) {
  if (r.status === 401) return "Pas connecté à youl4b.com : ouvre le site et connecte-toi (compte admin).";
  if (r.type === "opaqueredirect" || r.status === 0 || (r.status >= 300 && r.status < 400)) {
    // redirection (Cloudflare, page de connexion…) : rien n'est renvoyé vers
    // la cible, on le dit tel quel au lieu de deviner
    return "youl4b.com a répondu par une redirection : ouvre le site, vérifie que tu es connecté, puis réessaie.";
  }
  if (r.status === 403) return "Ce compte youl4b.com n’a pas le droit : il faut un compte admin.";
  return null;
}

// L'état des cookies du site, lu sur le site. Jamais une valeur.
async function lireSite() {
  const site = { t: maintenant(), connecte: false, message: "", services: [] };
  let r;
  try {
    r = await appelSite("/settings/cookies_etat", { method: "GET" }, 15000);
  } catch (e) {
    site.message = "youl4b.com injoignable.";
    return site;
  }
  const refus = refusDuSite(r);
  if (refus) {
    site.message = refus;
    return site;
  }
  let j = null;
  try { j = await r.json(); } catch (e) { j = null; }
  if (!r.ok || !j || !j.ok || !Array.isArray(j.services)) {
    site.message = "youl4b.com n’a pas rendu l’état des cookies (HTTP " + r.status + ").";
    return site;
  }
  site.connecte = true;
  site.services = j.services;
  return site;
}

// Étape 1 du popup : ce que ce Chrome a, SANS rien envoyer et sans une seule
// requête. Le propriétaire, 18/11/2026 : « avec un bouton, je fais, et avec un
// bouton, je valide que ça envoie ». Jamais une valeur : l'échéance, si ce
// cookie est déjà parti, et l'empreinte que la validation devra retrouver.
async function apercu() {
  const m = await lireMemoire();
  const services = {};
  const empreintes = {};
  for (const cle of Object.keys(SERVICES)) {
    const s = SERVICES[cle];
    const c = await lireCookie(cle);
    if (!c) {
      services[cle] = { trouve: false, envoyable: false, exp: null, deja: null, message: s.absent };
      continue;
    }
    const h = await empreinte(c.valeur);
    const envoi = m.envois[cle] || {};
    const echu = cle === "gms" && c.exp && c.exp < maintenant();
    services[cle] = {
      trouve: true, envoyable: !echu, exp: c.exp || null,
      deja: envoi.empreinte_ok === h ? envoi.dernier_ok || null : null,
      message: echu ? "Le cookie GetMySocial de ce Chrome est échu : reconnecte-toi sur getmysocial.com." : "",
    };
    if (!echu) empreintes[cle] = h;
  }
  return { services, empreintes };
}

// Envoie UN cookie au site. `forcer` : remplacer le compte du site par celui
// de ce Chrome (le site refuse sinon le cookie d'un autre compte). `attendue` :
// l'empreinte montrée à l'étape 1 ; un cookie qui a changé depuis ne part pas.
async function envoyerService(cle, forcer, raison, attendue) {
  const s = SERVICES[cle];
  const memoire = await lireMemoire();
  const avant = memoire.envois[cle] || {};
  const essai = { t: maintenant(), ok: false, raison, message: "", autre_compte: false,
    empreinte: null, empreinte_ok: avant.empreinte_ok || null, dernier_ok: avant.dernier_ok || null };

  async function noter() {
    const m = await lireMemoire();
    m.envois[cle] = essai;
    await ecrireMemoire(m);
    return essai;
  }

  const c = await lireCookie(cle);
  if (!c) {
    essai.message = s.absent;
    return noter();
  }
  essai.empreinte = await empreinte(c.valeur);
  if (attendue && essai.empreinte !== attendue) {
    essai.message = "Le cookie " + s.nom + " de ce Chrome a changé depuis l’aperçu. Rien envoyé : recommence.";
    return noter();
  }
  if (cle === "gms" && c.exp && c.exp < essai.t) {
    essai.message = "Le cookie GetMySocial de ce Chrome est échu : reconnecte-toi sur getmysocial.com.";
    return noter();
  }
  const fd = new FormData();
  fd.append(s.champ, c.valeur);
  fd.append("source", "extension");
  if (forcer) fd.append("forcer", "1");
  let r;
  try {
    r = await appelSite(s.route, { method: "POST", body: fd }, 25000);
  } catch (e) {
    essai.message = "youl4b.com injoignable, ou trop long à répondre. Rien de sûr : regarde l’état ci-dessus.";
    return noter();
  }
  const refus = refusDuSite(r);
  if (refus) {
    essai.message = refus;
    return noter();
  }
  let j = null;
  try { j = await r.json(); } catch (e) { j = null; }
  if (!r.ok || !j || !j.ok) {
    essai.autre_compte = !!(j && j.autre_compte);
    const pourquoi = (j && j.error) || "HTTP " + r.status;
    essai.message = essai.autre_compte
      ? "Ce Chrome est connecté à un autre compte " + s.nom + " que celui du site. Rien changé sur le site."
      : s.nom + " : " + pourquoi + ". Rien changé sur le site.";
    return noter();
  }
  essai.ok = true;
  essai.empreinte_ok = essai.empreinte;
  essai.dernier_ok = essai.t;
  essai.message = "Cookie " + s.nom + " remis à youl4b.com.";
  return noter();
}

// Faut-il envoyer ce cookie SANS qu'on le demande ?
//   GetMySocial : quand le cookie du navigateur est neuf (reconnexion), ou
//                 quand le site n'a plus le sien.
//   MyPuls      : seulement quand le cookie du site ne va plus. Tant qu'il va,
//                 le site le renouvelle seul ; lui donner celui du navigateur
//                 ne ferait que lui changer de session pour rien.
// Et jamais deux fois le même cookie dans la journée, refusé ou non.
async function fautEnvoyer(cle, srv, envoi) {
  const c = await lireCookie(cle);
  if (!c) return false;
  const h = await empreinte(c.valeur);
  if (envoi && envoi.empreinte === h && maintenant() - (envoi.t || 0) < RENVOI_S) return false;
  const niveau = srv ? srv.niveau : null;
  if (cle === "gms") return !envoi || envoi.empreinte_ok !== h || niveau === "ko";
  return niveau !== null && niveau !== "ok";
}

function badge(texte, couleur) {
  chrome.action.setBadgeText({ text: texte });
  if (couleur) chrome.action.setBadgeBackgroundColor({ color: couleur });
}

// La pastille suit l'état du SITE : rouge si un cookie est mort, orange s'il
// va mourir (GetMySocial : le nombre de jours restants).
function majBadge(site) {
  if (!site || !site.connecte) return badge("?", "#6b7280");
  const s = site.services || [];
  if (s.some((x) => x.niveau === "ko")) return badge("!", "#dc2626");
  const alerte = s.find((x) => x.niveau === "alerte");
  if (alerte) return badge(typeof alerte.jours === "number" ? Math.max(0, alerte.jours) + "j" : "!", "#f59e0b");
  return badge("", null);
}

async function relireSite() {
  const site = await lireSite();
  const m = await lireMemoire();
  m.site = site;
  await ecrireMemoire(m);
  majBadge(site);
  return m;
}

// Le contrôle automatique : lire l'état du site, envoyer ce qui doit l'être.
async function verifier(raison) {
  let m = await relireSite();
  if (!m.site.connecte) return m;
  let envoye = false;
  for (const cle of Object.keys(SERVICES)) {
    const srv = m.site.services.find((x) => x.cle === cle) || null;
    if (await fautEnvoyer(cle, srv, m.envois[cle])) {
      await envoyerService(cle, false, raison);
      envoye = true;
    }
  }
  return envoye ? relireSite() : m;
}

// Étape 2 du popup : n'envoie QUE ce que l'étape 1 a montré (une empreinte
// par cookie). Sans aperçu, rien ne part. Le site garde son contrôle de
// compte : le cookie d'un autre compte est refusé, pas remplacé.
async function envoyerTout(empreintes) {
  const vus = empreintes && typeof empreintes === "object" ? empreintes : {};
  for (const cle of Object.keys(SERVICES)) {
    if (typeof vus[cle] === "string" && vus[cle]) await envoyerService(cle, false, "bouton", vus[cle]);
  }
  return relireSite();
}

async function forcerService(cle) {
  if (!SERVICES[cle]) return lireMemoire();
  await envoyerService(cle, true, "remplacement demandé");
  return relireSite();
}

let enCours = Promise.resolve();

// Une tâche à la fois, dans l'ordre : un clic pendant un contrôle automatique
// passe APRÈS lui, il n'est pas avalé par lui.
function enFile(tache) {
  const p = enCours.then(tache);
  enCours = p.catch(() => {});
  return p;
}

function armerAlarme() {
  chrome.alarms.get("verif", (a) => {
    if (!a) chrome.alarms.create("verif", { periodInMinutes: 360, delayInMinutes: 1 });
  });
}

// Un contrôle automatique n'a personne à qui rendre compte : ce qu'il a trouvé
// est dans la mémoire, et un plantage ne doit pas en laisser un deuxième.
function controler(raison) {
  enFile(() => verifier(raison)).catch(() => {});
}

chrome.runtime.onInstalled.addListener(() => { armerAlarme(); controler("installation"); });
chrome.runtime.onStartup.addListener(() => { armerAlarme(); controler("démarrage de Chrome"); });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "verif") controler("contrôle toutes les 6 h");
  if (a.name === "relire") controler("nouveau cookie dans Chrome");
});

// Un cookie change souvent deux fois de suite (suppression puis réécriture) :
// une alarme courte regroupe les changements, et survit à l'arrêt du service
// worker, contrairement à un setTimeout.
chrome.cookies.onChanged.addListener((ch) => {
  const ck = ch.cookie;
  if (ch.removed || !ck) return;
  const dom = String(ck.domain || "").replace(/^\./, "");
  for (const s of Object.values(SERVICES)) {
    if (ck.name === s.cookie && (dom === s.domaine || dom.endsWith("." + s.domaine))) {
      chrome.alarms.create("relire", { delayInMinutes: 0.5 });
      return;
    }
  }
});

chrome.runtime.onMessage.addListener((m, _expediteur, repondre) => {
  const type = m && m.type;
  const repondreOuErreur = (p) => p.then(repondre, () => repondre(null));
  if (type === "memoire") {
    // ce qu'on savait déjà, tout de suite : le popup ne reste pas vide
    // pendant qu'un contrôle automatique occupe la file
    repondreOuErreur(lireMemoire());
    return true;
  }
  if (type === "etat") {
    repondreOuErreur(enFile(relireSite));
    return true;
  }
  if (type === "version") {
    repondre(VERSION);
    return false;
  }
  if (type === "apercu") {
    repondreOuErreur(apercu());
    return true;
  }
  if (type === "envoyer") {
    repondreOuErreur(enFile(() => envoyerTout(m.empreintes)));
    return true;
  }
  if (type === "forcer") {
    repondreOuErreur(enFile(() => forcerService(m.cle)));
    return true;
  }
  return false;
});
