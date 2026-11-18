// L'extension Chrome extension_cookies/, jouee dans un FAUX Chrome : faux
// cookies, faux youl4b.com, aucun reseau. Elle ne peut pas etre lancee dans
// un vrai Chrome par les tests ; ce fichier prouve ses DECISIONS : quoi part,
// vers ou, quand, et ce qui ne part jamais.
//
// Lance par tests_cookies_extension.py, ou seul : node tests_cookies_extension.js
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "extension_cookies", "background.js"), "utf8");
const OKS = [];
const KOS = [];

function check(libelle, cond, detail) {
  (cond ? OKS : KOS).push(libelle);
  console.log((cond ? "OK   " : "FAIL ") + libelle + (cond || detail === undefined ? "" : "  [" + String(detail).slice(0, 300) + "]"));
}

// Des valeurs de cookie FABRIQUEES pour ce test : aucune n'a jamais existe.
function jeton(compte, exp) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return b64({ alg: "HS256" }) + "." + b64({ id: compte, sessionId: "s-" + compte, iat: exp - 2592000, exp }) + ".SIGNATUREFABRIQUEE" + compte;
}
const DEMAIN = Math.floor(Date.now() / 1000) + 86400 * 20;
const GMS_A = jeton("compteA", DEMAIN);
const GMS_B = jeton("compteB", DEMAIN + 50);
const GMS_ECHU = jeton("compteA", Math.floor(Date.now() / 1000) - 60);
const REM_A = "App.Entity.User%3AY29tcHRlQQ~~%3A" + DEMAIN + "%3ASIGNATUREFABRIQUEEREMA";
const SECRETS = [GMS_A, GMS_B, GMS_ECHU, REM_A, "SIGNATUREFABRIQUEE"];

const BON = { cle: "x", nom: "X", niveau: "ok", texte: "Valide.", aide: "", jours: 19 };
function etatSite(gms, mypuls) {
  return { ok: true, services: [Object.assign({}, BON, { cle: "gms", nom: "GetMySocial" }, gms || {}),
    Object.assign({}, BON, { cle: "mypuls", nom: "MyPuls", jours: 6 }, mypuls || {})] };
}

function reponse(status, corps, type) {
  return { status, ok: status >= 200 && status < 300, type: type || "basic",
    json: async () => { if (corps === undefined) throw new Error("pas du JSON"); return corps; } };
}

// Un monde : des cookies dans « Chrome », et un « site » qui repond.
function monde(cookies, site) {
  const m = { stockage: {}, requetes: [], badge: { texte: "", couleur: null }, alarmes: [], ecoutes: {}, console: [] };
  const espion = (...a) => m.console.push(a.map(String).join(" "));
  const chrome = {
    cookies: {
      getAll: async ({ domain, name }) => cookies.filter((c) => {
        const d = c.domain.replace(/^\./, "");
        return c.name === name && (d === domain || d.endsWith("." + domain));
      }),
      onChanged: { addListener: (f) => { m.ecoutes.cookie = f; } },
    },
    storage: { local: {
      get: async (k) => ({ [k]: m.stockage[k] === undefined ? undefined : JSON.parse(JSON.stringify(m.stockage[k])) }),
      set: async (o) => { Object.assign(m.stockage, JSON.parse(JSON.stringify(o))); },
    } },
    action: {
      setBadgeText: (o) => { m.badge.texte = o.text; },
      setBadgeBackgroundColor: (o) => { m.badge.couleur = o.color; },
    },
    alarms: {
      get: (_n, cb) => cb(null),
      create: (n, o) => m.alarmes.push([n, o]),
      onAlarm: { addListener: (f) => { m.ecoutes.alarme = f; } },
    },
    runtime: {
      onInstalled: { addListener: (f) => { m.ecoutes.installe = f; } },
      onStartup: { addListener: (f) => { m.ecoutes.demarre = f; } },
      onMessage: { addListener: (f) => { m.ecoutes.message = f; } },
    },
  };
  const faux_fetch = async (url, opt) => {
    const champs = opt && opt.body ? Object.fromEntries(opt.body.entries()) : null;
    m.requetes.push({ url, methode: (opt && opt.method) || "GET", champs, credentials: opt && opt.credentials, redirect: opt && opt.redirect });
    return site(url, champs, m);
  };
  const contexte = vm.createContext({
    chrome, fetch: faux_fetch, FormData, crypto: globalThis.crypto, TextEncoder, atob, AbortController,
    setTimeout, clearTimeout, console: { log: espion, warn: espion, error: espion, info: espion, debug: espion },
  });
  vm.runInContext(SOURCE, contexte, { filename: "background.js" });
  m.dire = (message) => new Promise((res) => { if (!m.ecoutes.message(message, null, res)) res("non-traite"); });
  // la file interne de l'extension : un message « memoire » ne passe pas par
  // elle, « etat » si ; attendre « etat » = attendre que tout soit fini
  m.attendre = () => m.dire({ type: "etat" });
  m.posts = () => m.requetes.filter((r) => r.methode === "POST");
  return m;
}

const CK_GMS = (v) => ({ name: "authToken", domain: "getmysocial.com", value: v });
const CK_REM = (v) => ({ name: "REMEMBERME", domain: ".mypuls.app", value: v, expirationDate: DEMAIN });

function siteQuiVaBien(etat, reponses) {
  return (url, champs) => {
    if (url.endsWith("/settings/cookies_etat")) return reponse(200, typeof etat === "function" ? etat() : etat);
    const r = (reponses || {})[url.replace("https://youl4b.com", "")];
    return r ? (typeof r === "function" ? r(champs) : r) : reponse(200, { ok: true });
  };
}

// Le parcours du popup : étape 1 (aperçu), étape 2 (valider ce qui a été vu).
async function deuxEtapes(m) {
  m.apercu = await m.dire({ type: "apercu" });
  return m.dire({ type: "envoyer", empreintes: m.apercu.empreintes });
}

async function jouer() {
  // ---------------------------------------------------------------- 1
  console.log("1. A l'installation, le site allant bien");
  let m = monde([CK_GMS(GMS_A), CK_REM(REM_A)], siteQuiVaBien(etatSite()));
  m.ecoutes.installe();
  await m.attendre();
  let p = m.posts();
  check("le cookie GetMySocial, jamais envoye, part une fois", p.length === 1 && p[0].url === "https://youl4b.com/gms/set_session_cookie", p.map((x) => x.url));
  check("il part dans le champ « cookie », marque source=extension, sans forcer",
    p[0] && p[0].champs.cookie === GMS_A && p[0].champs.source === "extension" && !("forcer" in p[0].champs), p[0] && Object.keys(p[0].champs));
  check("MyPuls va bien sur le site : son cookie ne part PAS tout seul", !p.some((x) => x.url.includes("/mypuls/")));
  check("pastille vide quand tout va bien", m.badge.texte === "", m.badge.texte);
  check("l'alarme des 6 heures est armee", m.alarmes.some((a) => a[0] === "verif" && a[1].periodInMinutes === 360), JSON.stringify(m.alarmes));
  const avant = m.posts().length;
  m.ecoutes.alarme({ name: "verif" });
  await m.attendre();
  check("au controle suivant, le meme cookie GetMySocial n'est pas renvoye", m.posts().length === avant, m.posts().length);

  // ---------------------------------------------------------------- 2
  console.log("2. Les deux boutons : prendre, puis valider");
  m = monde([CK_GMS(GMS_A), CK_REM(REM_A)], siteQuiVaBien(etatSite()));
  let rep = await deuxEtapes(m);
  p = m.posts();
  check("deux envois : GetMySocial puis MyPuls", p.length === 2 && p[0].url.endsWith("/gms/set_session_cookie") && p[1].url.endsWith("/mypuls/save_cookies"), p.map((x) => x.url));
  check("MyPuls : le REMEMBERME seul (pas de PHPSESSID), marque source=extension",
    p[1] && p[1].champs.rememberme === REM_A && p[1].champs.source === "extension" && Object.keys(p[1].champs).sort().join() === "rememberme,source", p[1] && Object.keys(p[1].champs));
  check("le bouton ne force pas : le controle de compte du site reste", p.every((x) => !("forcer" in x.champs)));
  check("tout part vers https://youl4b.com et nulle part ailleurs", m.requetes.length > 0 && m.requetes.every((r) => r.url.startsWith("https://youl4b.com/")), m.requetes.map((r) => r.url));
  check("chaque appel joint la session du site et ne suit aucune redirection", m.requetes.every((r) => r.credentials === "include" && r.redirect === "manual"));
  check("la reponse au popup : l'etat du site et les deux envois reussis",
    rep && rep.site && rep.site.connecte && rep.envois.gms.ok && rep.envois.mypuls.ok && rep.site.services.length === 2, JSON.stringify(rep).slice(0, 200));

  // ---------------------------------------------------------------- 3
  console.log("3. Aucune valeur ne traine");
  const partout = JSON.stringify(m.stockage) + m.console.join("\n") + JSON.stringify(rep) + JSON.stringify(m.apercu) + m.requetes.map((r) => r.url).join("\n");
  check("ni la memoire de l'extension, ni la console, ni l'apercu, ni la reponse au popup, ni une adresse ne portent une valeur de cookie",
    SECRETS.every((s) => !partout.includes(s)), SECRETS.filter((s) => partout.includes(s)).length + " valeur(s) trouvee(s)");
  check("la memoire garde une empreinte de 16 caracteres", /^[0-9a-f]{16}$/.test(m.stockage.memoire.envois.gms.empreinte || ""), m.stockage.memoire.envois.gms.empreinte);
  check("rien n'est ecrit dans la console", m.console.length === 0, m.console.length);

  // ---------------------------------------------------------------- 4
  console.log("4. MyPuls mort sur le site : remis tout seul, une fois");
  let mort = true;
  m = monde([CK_REM(REM_A)], siteQuiVaBien(() => etatSite(null, mort ? { niveau: "ko", texte: "MyPuls refuse le cookie du site depuis le 20/11/2026.", jours: null } : null),
    { "/mypuls/save_cookies": () => { mort = false; return reponse(200, { ok: true }); } }));
  m.ecoutes.alarme({ name: "verif" });
  await m.attendre();
  p = m.posts();
  check("le REMEMBERME du navigateur part sans clic", p.length === 1 && p[0].url.endsWith("/mypuls/save_cookies") && p[0].champs.rememberme === REM_A, p.map((x) => x.url));
  check("la pastille redevient vide une fois le site repare", m.badge.texte === "", m.badge.texte);
  mort = true;
  m.ecoutes.alarme({ name: "verif" });
  await m.attendre();
  check("le meme cookie, refuse ou non, n'est pas renvoye deux fois dans la journee", m.posts().length === 1, m.posts().length);
  check("pastille rouge « ! » tant qu'un cookie du site est mort", m.badge.texte === "!" && m.badge.couleur === "#dc2626", JSON.stringify(m.badge));

  // ---------------------------------------------------------------- 5
  console.log("5. Un autre compte dans ce Chrome");
  m = monde([CK_GMS(GMS_B), CK_REM(REM_A)], siteQuiVaBien(etatSite(), {
    "/gms/set_session_cookie": (c) => (c.forcer === "1" ? reponse(200, { ok: true }) : reponse(200, { ok: false, error: "autre compte", autre_compte: true })),
  }));
  m.ecoutes.installe();
  await m.attendre();
  let e = m.stockage.memoire.envois.gms;
  check("le refus du site est note « autre compte », rien n'est force", e && !e.ok && e.autre_compte === true && m.posts().every((x) => !("forcer" in x.champs)), JSON.stringify(e).slice(0, 200));
  check("un autre compte n'allume pas la pastille (le site, lui, va bien)", m.badge.texte === "", m.badge.texte);
  rep = await m.dire({ type: "forcer", cle: "gms" });
  p = m.posts();
  check("« Remplacer le compte du site » : un envoi marque forcer=1, pour ce service seul",
    p[p.length - 1].champs.forcer === "1" && p[p.length - 1].url.endsWith("/gms/set_session_cookie") && rep.envois.gms.ok && p.filter((x) => x.champs.forcer === "1").length === 1, p.map((x) => x.url + " " + (x.champs.forcer || "")));
  rep = await m.dire({ type: "forcer", cle: "inconnu" });
  check("un service inconnu ne declenche aucun envoi", m.posts().length === p.length, m.posts().length);

  // ---------------------------------------------------------------- 6
  console.log("6. Pas connecte a youl4b.com");
  m = monde([CK_GMS(GMS_A), CK_REM(REM_A)], () => reponse(401, { ok: false, error: "unauth" }));
  m.ecoutes.demarre();
  await m.attendre();
  check("sans session sur le site, le controle automatique n'envoie aucun cookie", m.posts().length === 0, m.posts().length);
  check("pastille grise « ? » et message clair", m.badge.texte === "?" && /Pas connecté à youl4b\.com/.test(m.stockage.memoire.site.message), JSON.stringify(m.badge) + m.stockage.memoire.site.message);
  rep = await deuxEtapes(m);
  check("au bouton, le 401 est dit pour chaque service", !rep.envois.gms.ok && /Pas connecté à youl4b\.com/.test(rep.envois.gms.message) && !rep.envois.mypuls.ok, rep.envois.gms.message);
  m = monde([CK_GMS(GMS_A)], () => reponse(0, undefined, "opaqueredirect"));
  rep = await deuxEtapes(m);
  check("une redirection (Cloudflare, page de connexion) est dite telle quelle", /redirection/.test(rep.site.message) && /redirection/.test(rep.envois.gms.message), rep.site.message);
  m = monde([CK_GMS(GMS_A)], () => reponse(403, { ok: false, error: "Action réservée aux administrateurs" }));
  rep = await deuxEtapes(m);
  check("un compte sans droit (403) : « il faut un compte admin »", /compte admin/.test(rep.envois.gms.message) && !rep.site.connecte, rep.envois.gms.message);
  m = monde([CK_GMS(GMS_A)], () => { throw new Error("reseau coupe"); });
  rep = await deuxEtapes(m);
  check("site injoignable : dit, rien ne plante", rep && !rep.site.connecte && /injoignable/.test(rep.site.message) && /injoignable/.test(rep.envois.gms.message), JSON.stringify(rep).slice(0, 200));

  // ---------------------------------------------------------------- 7
  console.log("7. Rien a envoyer");
  m = monde([], siteQuiVaBien(etatSite(null, { niveau: "ko", texte: "Aucun cookie sur le site.", jours: null })));
  rep = await deuxEtapes(m);
  check("pas connecte a GetMySocial ni a MyPuls dans Chrome : l'apercu donne deux consignes, rien a valider, aucun envoi", m.posts().length === 0
    && /getmysocial\.com/.test(m.apercu.services.gms.message) && /Se souvenir de moi/.test(m.apercu.services.mypuls.message)
    && !m.apercu.services.gms.trouve && Object.keys(m.apercu.empreintes).length === 0, JSON.stringify(m.apercu));
  m.ecoutes.alarme({ name: "verif" });
  await m.attendre();
  check("le controle automatique non plus", m.posts().length === 0, m.posts().length);
  m = monde([CK_GMS(GMS_ECHU)], siteQuiVaBien(etatSite({ niveau: "ko", texte: "Échu.", jours: null })));
  rep = await deuxEtapes(m);
  check("un jeton GetMySocial echu dans Chrome : dit a l'apercu, pas envoyable, pas envoye", m.posts().length === 0
    && m.apercu.services.gms.trouve && !m.apercu.services.gms.envoyable && /échu/.test(m.apercu.services.gms.message)
    && !("gms" in m.apercu.empreintes), JSON.stringify(m.apercu));
  m = monde([CK_GMS(GMS_ECHU), { name: "authToken", domain: "app.getmysocial.com", value: GMS_A }], siteQuiVaBien(etatSite()));
  await deuxEtapes(m);
  check("deux cookies authToken (domaine et sous-domaine) : celui qui expire le plus tard", m.posts()[0].champs.cookie === GMS_A);

  // ---------------------------------------------------------------- 8
  console.log("8. GetMySocial bientot echu, reconnexion");
  m = monde([CK_GMS(GMS_A)], siteQuiVaBien(etatSite({ niveau: "alerte", jours: 2 })));
  m.ecoutes.installe();
  await m.attendre();
  check("pastille orange « 2j » a deux jours de l'echeance", m.badge.texte === "2j" && m.badge.couleur === "#f59e0b", JSON.stringify(m.badge));
  m.alarmes.length = 0;
  m.ecoutes.cookie({ removed: false, cookie: { name: "authToken", domain: ".getmysocial.com" } });
  m.ecoutes.cookie({ removed: false, cookie: { name: "REMEMBERME", domain: "mypuls.app" } });
  check("un cookie authToken ou REMEMBERME qui change arme une relecture", m.alarmes.filter((a) => a[0] === "relire").length === 2, JSON.stringify(m.alarmes));
  m.alarmes.length = 0;
  m.ecoutes.cookie({ removed: true, cookie: { name: "authToken", domain: "getmysocial.com" } });
  m.ecoutes.cookie({ removed: false, cookie: { name: "authToken", domain: "evilgetmysocial.com" } });
  m.ecoutes.cookie({ removed: false, cookie: { name: "PHPSESSID", domain: "mypuls.app" } });
  m.ecoutes.cookie({ removed: false, cookie: { name: "REMEMBERME", domain: "autre-site.com" } });
  check("ni une suppression, ni un autre cookie, ni un autre domaine", m.alarmes.length === 0, JSON.stringify(m.alarmes));

  // ---------------------------------------------------------------- 9
  console.log("9. Le site refuse ou repond n'importe quoi");
  m = monde([CK_REM(REM_A)], siteQuiVaBien(etatSite(), { "/mypuls/save_cookies": reponse(200, { ok: false, error: "MyPuls refuse ce cookie" }) }));
  rep = await deuxEtapes(m);
  check("le refus du site est repris mot pour mot, et « rien change »", /MyPuls refuse ce cookie/.test(rep.envois.mypuls.message) && /Rien changé/.test(rep.envois.mypuls.message) && !rep.envois.mypuls.autre_compte, rep.envois.mypuls.message);
  m = monde([CK_REM(REM_A)], siteQuiVaBien(etatSite(), { "/mypuls/save_cookies": reponse(500, undefined) }));
  rep = await deuxEtapes(m);
  check("une reponse qui n'est pas du JSON : « HTTP 500 », pas un succes", !rep.envois.mypuls.ok && /HTTP 500/.test(rep.envois.mypuls.message), rep.envois.mypuls.message);
  m = monde([CK_REM(REM_A)], (url) => (url.endsWith("/settings/cookies_etat") ? reponse(200, { ok: true }) : reponse(200, { ok: true })));
  rep = await m.dire({ type: "etat" });
  check("un etat sans la liste des services n'est pas pris pour « tout va bien »", !rep.site.connecte && m.badge.texte === "?", JSON.stringify(rep.site));
  rep = await m.dire({ type: "memoire" });
  check("« memoire » rend ce qu'on savait sans rien demander au site", rep && rep.site && m.requetes.length === 1, m.requetes.length);

  // --------------------------------------------------------------- 10
  console.log("10. Deux etapes : rien ne part sans avoir ete vu");
  m = monde([CK_GMS(GMS_A), CK_REM(REM_A)], siteQuiVaBien(etatSite()));
  let a = await m.dire({ type: "apercu" });
  check("l'apercu ne fait AUCUNE requete, ni au site ni ailleurs", m.requetes.length === 0, m.requetes.length);
  check("il dit pour chaque service : trouve, envoyable, echeance, pas encore envoye",
    a.services.gms.trouve && a.services.gms.envoyable && a.services.gms.exp === DEMAIN && a.services.gms.deja === null
    && a.services.mypuls.trouve && a.services.mypuls.envoyable && a.services.mypuls.exp === DEMAIN && a.services.mypuls.deja === null, JSON.stringify(a.services));
  check("il rend une empreinte de 16 caracteres par cookie, jamais une valeur",
    /^[0-9a-f]{16}$/.test(a.empreintes.gms) && /^[0-9a-f]{16}$/.test(a.empreintes.mypuls) && SECRETS.every((x) => !JSON.stringify(a).includes(x)), JSON.stringify(a.empreintes));
  check("l'apercu n'ecrit rien dans la memoire de l'extension", m.stockage.memoire === undefined, JSON.stringify(m.stockage).slice(0, 120));
  rep = await m.dire({ type: "envoyer" });
  check("« envoyer » sans apercu : rien ne part", m.posts().length === 0, m.posts().length);
  rep = await m.dire({ type: "envoyer", empreintes: { gms: a.empreintes.gms } });
  check("valider un seul des deux : lui seul part", m.posts().length === 1 && m.posts()[0].url.endsWith("/gms/set_session_cookie") && rep.envois.gms.ok && !rep.envois.mypuls, m.posts().map((x) => x.url));
  a = await m.dire({ type: "apercu" });
  check("apres l'envoi, l'apercu dit « deja envoye » pour celui-la seulement",
    typeof a.services.gms.deja === "number" && a.services.gms.deja > 0 && a.services.mypuls.deja === null, JSON.stringify(a.services));

  let cookies = [CK_GMS(GMS_A)];
  m = monde(cookies, siteQuiVaBien(etatSite()));
  a = await m.dire({ type: "apercu" });
  cookies[0] = CK_GMS(GMS_B);          // un autre compte ouvert entre l'apercu et la validation
  cookies.push(CK_REM(REM_A));         // et un cookie MyPuls apparu entre-temps
  rep = await m.dire({ type: "envoyer", empreintes: a.empreintes });
  check("le cookie a change entre l'apercu et la validation : il ne part pas, et c'est dit",
    m.posts().length === 0 && !rep.envois.gms.ok && /a changé depuis l’aperçu/.test(rep.envois.gms.message), rep.envois.gms.message);
  check("un cookie apparu apres l'apercu ne part pas non plus (il n'a pas ete vu)", !rep.envois.mypuls && m.posts().length === 0);
  rep = await m.dire({ type: "envoyer", empreintes: { gms: "0000000000000000", mypuls: 12, inconnu: "abc" } });
  check("des empreintes fausses ou mal formees n'envoient rien", m.posts().length === 0, m.posts().length);

  m = monde([], siteQuiVaBien(etatSite()));
  const version = await m.dire({ type: "version" });
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "extension_cookies", "manifest.json"), "utf8"));
  check("le fond dit sa version, celle du manifest (le popup recharge l'extension si elle differe)", version === manifest.version && /^\d+\.\d+$/.test(version), version);

  console.log("=".repeat(70));
  console.log("RESULTAT : " + OKS.length + " OK / " + KOS.length + " ECHEC(S)");
  for (const k of KOS) console.log("  - " + k);
  process.exit(KOS.length ? 1 : 0);
}

jouer().catch((e) => { console.log("FAIL le simulateur a plante : " + (e && e.stack || e)); process.exit(1); });
