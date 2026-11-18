// Le popup n'écrit AUCUNE phrase d'état : il affiche celles que le site rend
// (/settings/cookies_etat, les mêmes que Réglages) et le résultat du dernier
// envoi, noté par background.js. Tout passe par textContent : rien de ce qui
// vient du réseau n'est interprété comme du HTML.

const SERVICES = [["gms", "GetMySocial"], ["mypuls", "MyPuls"]];
const SIGNES = { ok: "✓", alerte: "⚠", ko: "✗" };

function date(s) {
  if (!s) return "";
  return new Date(s * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function bloc(classe, texte) {
  const d = document.createElement("div");
  d.className = classe;
  d.textContent = texte;
  return d;
}

function carte(cle, nom, srv, envoi) {
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
  // la consigne générale du site, sauf si le dernier envoi a une raison plus
  // précise à donner (« pas de cookie dans ce Chrome »…) : pas deux consignes
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
      b.addEventListener("click", () => demander({ type: "forcer", cle }, b, "Envoi…"));
      c.appendChild(b);
    }
    if (envoi.dernier_ok) c.appendChild(bloc("petit", "Dernier envoi réussi : " + date(envoi.dernier_ok)));
  }
  return c;
}

function afficher(m) {
  const boite = document.getElementById("services");
  const alerte = document.getElementById("site");
  if (!m) {
    boite.textContent = "L’extension n’a pas répondu : ferme ce panneau et rouvre-le.";
    return;
  }
  const site = m.site || null;
  const envois = m.envois || {};
  alerte.hidden = !site || site.connecte;
  alerte.textContent = site && !site.connecte ? "✗ " + (site.message || "youl4b.com n’a pas répondu.") : "";
  boite.textContent = "";
  for (const [cle, nom] of SERVICES) {
    const srv = site && site.connecte ? (site.services || []).find((x) => x.cle === cle) : null;
    boite.appendChild(carte(cle, nom, srv || null, envois[cle] || null));
  }
}

// Un bouton occupé le dit, puis reprend son texte : deux clics rapprochés
// n'envoient pas deux fois.
function demander(message, bouton, occupe) {
  const texte = bouton.textContent;
  bouton.disabled = true;
  bouton.textContent = occupe;
  chrome.runtime.sendMessage(message, (m) => {
    afficher(chrome.runtime.lastError ? null : m);
    if (bouton.isConnected) {
      bouton.disabled = false;
      bouton.textContent = texte;
    }
  });
}

// D'abord ce qu'on savait (immédiat), puis l'état frais lu sur le site.
chrome.runtime.sendMessage({ type: "memoire" }, (m) => {
  if (!chrome.runtime.lastError && m && m.site) afficher(m);
  chrome.runtime.sendMessage({ type: "etat" }, (frais) => afficher(chrome.runtime.lastError ? null : frais));
});

document.getElementById("envoyer").addEventListener("click", (ev) => {
  demander({ type: "envoyer" }, ev.currentTarget, "Envoi…");
});
