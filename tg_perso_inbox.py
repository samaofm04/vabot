"""tg_perso_inbox.py — Page « Inbox » du bot Telegram perso (/tgperso/inbox).

Trois colonnes : fans (recherche, onglets), conversation (bulles, réponse,
interrupteur IA), fiche du fan. Tout est reconstruit en JS à partir de
/tgperso/inbox/liste et /tgperso/inbox/conv, relus toutes les 5 s.

Le HTML vit dans une chaîne BRUTE à part, sans formatage Python : dans
web_upload.py, une apostrophe mal échappée dans le JS d'une chaîne Python a
déjà tué un bouton sans la moindre erreur. Ici le JS est écrit tel quel, et
il ne pose jamais de texte venu d'un fan en innerHTML (textContent partout).
"""

INBOX_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inbox Telegram</title>
<style>
:root{--bg:#0b0d12;--panel:#11141b;--panel2:#161a23;--bord:#232836;--txt:#e7e9ee;--mut:#8b92a3;
--acc:#4f8cff;--moi:#3b2d6b;--moi-bord:#5b46a8;--fan:#1b202b;--ok:#2fbf71;--warn:#e0a526;--bad:#e5484d}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f4f5f8;--panel:#fff;--panel2:#f7f8fb;
--bord:#e3e6ec;--txt:#171a21;--mut:#646b7a;--acc:#2563eb;--moi:#ece7ff;--moi-bord:#c9bcff;--fan:#f0f2f6}}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--txt);font:14px/1.45 system-ui,-apple-system,sans-serif}
a{color:var(--acc)}
.app{display:grid;grid-template-columns:340px 1fr 320px;height:100vh}
.col{min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--bord);background:var(--panel)}
.col:last-child{border-right:0}
.tete{padding:14px 16px;border-bottom:1px solid var(--bord);display:flex;align-items:center;gap:10px}
.tete h1{font-size:17px;margin:0;flex:1}
.recherche{margin:12px 16px 8px;display:flex}
.recherche input{flex:1;background:var(--panel2);border:1px solid var(--bord);color:var(--txt);border-radius:10px;padding:9px 12px;font:inherit}
.onglets{display:flex;gap:6px;padding:0 16px 10px;flex-wrap:wrap}
.onglet{background:transparent;border:1px solid var(--bord);color:var(--mut);border-radius:999px;padding:5px 11px;font:inherit;font-size:13px;cursor:pointer}
.onglet.on{background:var(--acc);border-color:var(--acc);color:#fff}
.onglet b{font-weight:600;margin-left:4px}
.liste{overflow-y:auto;flex:1}
.item{display:flex;gap:10px;padding:11px 16px;border-bottom:1px solid var(--bord);cursor:pointer;align-items:flex-start}
.item:hover{background:var(--panel2)}
.item.sel{background:var(--panel2);box-shadow:inset 3px 0 0 var(--acc)}
.av{width:40px;height:40px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;position:relative}
.av.g{width:72px;height:72px;font-size:28px}
.pastille{position:absolute;right:-1px;bottom:-1px;width:12px;height:12px;border-radius:50%;border:2px solid var(--panel)}
.item .corps{flex:1;min-width:0}
.ligne1{display:flex;gap:6px;align-items:baseline}
.ligne1 .nom{font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ligne1 .quand{color:var(--mut);font-size:12px;flex:none}
.apercu{color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}
.etiquettes{display:flex;gap:6px;margin-top:5px;align-items:center;flex-wrap:wrap}
.tag{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--panel2);border:1px solid var(--bord);color:var(--mut)}
.tag.ia{color:var(--ok);border-color:#2fbf7155}
.tag.pause{color:var(--warn);border-color:#e0a52655}
.tag.off{color:var(--bad);border-color:#e5484d55}
.nonlus{margin-left:auto;background:var(--acc);color:#fff;border-radius:999px;font-size:11px;font-weight:700;min-width:20px;height:20px;display:flex;align-items:center;justify-content:center;padding:0 6px}
.vide{color:var(--mut);padding:30px 16px;text-align:center}
.conv-tete .qui{flex:1;min-width:0}
.conv-tete .qui b{display:block}
.conv-tete .qui span{color:var(--mut);font-size:12px}
.interrupteur{display:flex;align-items:center;gap:8px;border:1px solid var(--bord);border-radius:10px;padding:6px 10px;cursor:pointer;user-select:none;font-size:13px}
.interrupteur.on{border-color:#2fbf7166;color:var(--ok)}
.bascule{width:34px;height:20px;border-radius:999px;background:var(--bord);position:relative;transition:.15s}
.bascule::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.15s}
.interrupteur.on .bascule{background:var(--ok)}
.interrupteur.on .bascule::after{left:16px}
.retour{display:none;background:none;border:0;color:var(--txt);font-size:20px;cursor:pointer;padding:0 6px 0 0}
.fil{flex:1;overflow-y:auto;padding:18px 22px;display:flex;flex-direction:column;gap:10px;background:var(--bg)}
.jour{align-self:center;color:var(--mut);font-size:12px;border:1px solid var(--bord);border-radius:999px;padding:2px 10px;margin:6px 0}
.msg{max-width:72%;display:flex;flex-direction:column}
.msg.fan{align-self:flex-start}
.msg.moi{align-self:flex-end;align-items:flex-end}
.bulle{padding:9px 13px;border-radius:16px;white-space:pre-wrap;word-break:break-word}
.msg.fan .bulle{background:var(--fan);border:1px solid var(--bord);border-bottom-left-radius:5px}
.msg.moi .bulle{background:var(--moi);border:1px solid var(--moi-bord);border-bottom-right-radius:5px}
.meta{font-size:11px;color:var(--mut);margin-top:3px;display:flex;gap:6px}
.meta .ia{color:#a98bff}
.meta .toi{color:var(--acc)}
.saisie{border-top:1px solid var(--bord);padding:12px 16px;display:flex;gap:10px;align-items:flex-end;background:var(--panel)}
.saisie textarea{flex:1;resize:none;min-height:44px;max-height:160px;background:var(--panel2);border:1px solid var(--bord);color:var(--txt);border-radius:12px;padding:11px 12px;font:inherit}
.envoyer{background:var(--acc);color:#fff;border:0;border-radius:12px;width:46px;height:44px;font-size:18px;cursor:pointer}
.envoyer:disabled{opacity:.5;cursor:default}
.erreur{color:var(--bad);font-size:12px;padding:0 16px 8px}
.aide{color:var(--mut);font-size:12px;padding:6px 16px 0}
.fiche{overflow-y:auto;padding:22px 18px}
.fiche .haut{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;margin-bottom:16px}
.fiche .haut b{font-size:17px}
.fiche .haut span{color:var(--mut)}
.bloc{background:var(--panel2);border:1px solid var(--bord);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.bloc h3{margin:0 0 8px;font-size:12px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.kv{display:flex;justify-content:space-between;gap:10px;padding:3px 0}
.kv span:first-child{color:var(--mut)}
.kv span:last-child{text-align:right;word-break:break-word}
.fiche textarea{width:100%;min-height:90px;background:var(--panel);border:1px solid var(--bord);color:var(--txt);border-radius:10px;padding:9px;font:inherit;resize:vertical}
.statut{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.statut.abonne{background:#2fbf7122;color:var(--ok)}
.statut.clique{background:#e0a52622;color:var(--warn)}
.statut.froid{background:#e5484d22;color:var(--bad)}
.accueil{flex:1;display:flex;align-items:center;justify-content:center;color:var(--mut);flex-direction:column;gap:8px;background:var(--bg)}
@media (max-width:1100px){.app{grid-template-columns:300px 1fr}.col.fiche-col{display:none}}
@media (max-width:760px){
 .app{grid-template-columns:1fr}
 .app.ouvert .col.liste-col{display:none}
 .app:not(.ouvert) .col.conv-col{display:none}
 .retour{display:block}
 .msg{max-width:88%}
 .fil{padding:14px 16px}
}
</style></head>
<body>
<div class="app" id="app">
 <div class="col liste-col">
  <div class="tete"><h1>📥 Inbox</h1><a href="/tgperso/entrainement" title="Camp d'entraînement">🎯 Entraînement</a><a href="/tgperso" title="Réglages du bot">⚙️</a></div>
  <div class="recherche"><input id="recherche" placeholder="Rechercher un fan…" autocomplete="off"></div>
  <div class="onglets" id="onglets"></div>
  <div class="liste" id="liste"><div class="vide">Chargement…</div></div>
 </div>
 <div class="col conv-col" id="conv-col">
  <div class="accueil" id="accueil"><div style="font-size:34px">💬</div><div>Choisis une conversation à gauche.</div></div>
 </div>
 <div class="col fiche-col"><div class="fiche" id="fiche"></div></div>
</div>
<script>
(function () {
  "use strict";
  var ONGLETS = [["tous", "Tous"], ["nonlus", "Non lus"], ["clique", "Ont cliqué"], ["abonne", "Abonnés"]];
  var COULEURS = ["#4f8cff", "#2fbf71", "#e0a526", "#a98bff", "#e5484d", "#14b8a6", "#f472b6", "#64748b"];
  var etat = { fans: [], filtre: "tous", recherche: "", sel: null, conv: null, nbHisto: -1, maintenant: 0 };

  function el(tag, cls, texte) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texte !== undefined && texte !== null) e.textContent = texte;
    return e;
  }
  function couleur(id) {
    var h = 0, s = String(id);
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 997;
    return COULEURS[h % COULEURS.length];
  }
  function initiale(f) {
    var n = (f.nom || f.username || "?").trim();
    return n ? n.charAt(0).toUpperCase() : "?";
  }
  function nomDe(f) { return f.nom || (f.username ? "@" + f.username : "Fan " + f.id); }
  function heure(t) {
    var d = new Date(t * 1000);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function quand(t) {
    if (!t) return "";
    var maintenant = Date.now() / 1000, ecart = maintenant - t;
    if (ecart < 60) return "à l'instant";
    if (ecart < 3600) return Math.floor(ecart / 60) + " min";
    var d = new Date(t * 1000), auj = new Date();
    if (d.toDateString() === auj.toDateString()) return heure(t);
    var hier = new Date(auj.getTime() - 86400000);
    if (d.toDateString() === hier.toDateString()) return "hier";
    return String(d.getDate()).padStart(2, "0") + "/" + String(d.getMonth() + 1).padStart(2, "0");
  }
  function jourDe(t) {
    var d = new Date(t * 1000), auj = new Date();
    if (d.toDateString() === auj.toDateString()) return "Aujourd'hui";
    var hier = new Date(auj.getTime() - 86400000);
    if (d.toDateString() === hier.toDateString()) return "Hier";
    return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  }
  function avatar(f, grand) {
    var a = el("div", "av" + (grand ? " g" : ""), initiale(f));
    a.style.background = couleur(f.id);
    var p = el("span", "pastille");
    p.style.background = f.statut === "abonne" ? "var(--ok)" : f.statut === "clique" ? "var(--warn)" : "var(--mut)";
    p.title = f.statut === "abonne" ? "Abonné" : f.statut === "clique" ? "A cliqué" : "Rien cliqué";
    a.appendChild(p);
    return a;
  }
  function etiquetteIA(f) {
    if (f.mineur) return el("span", "tag off", "mineur : coupé");
    if (!f.ia) return el("span", "tag off", "IA coupée");
    if (f.pause_jusqua) return el("span", "tag pause", "IA en pause");
    return el("span", "tag ia", "● IA");
  }
  function api(url, corps) {
    var opts = corps ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) } : {};
    opts.credentials = "same-origin";
    return fetch(url, opts).then(function (r) {
      if (r.status === 403) { location.href = "/"; throw new Error("session"); }
      return r.json();
    });
  }

  // ---------------------------------------------------------- liste
  function filtres(f) {
    if (etat.filtre === "nonlus" && !f.non_lus) return false;
    if (etat.filtre === "clique" && f.statut !== "clique") return false;
    if (etat.filtre === "abonne" && f.statut !== "abonne") return false;
    if (etat.recherche) {
      var q = etat.recherche.toLowerCase();
      if ((f.nom + " " + f.username + " " + f.dernier.texte).toLowerCase().indexOf(q) < 0) return false;
    }
    return true;
  }
  function dessinerOnglets() {
    var compte = { tous: etat.fans.length, nonlus: 0, clique: 0, abonne: 0 };
    etat.fans.forEach(function (f) {
      if (f.non_lus) compte.nonlus++;
      if (f.statut === "clique") compte.clique++;
      if (f.statut === "abonne") compte.abonne++;
    });
    var box = document.getElementById("onglets");
    box.textContent = "";
    ONGLETS.forEach(function (o) {
      var b = el("button", "onglet" + (etat.filtre === o[0] ? " on" : ""), o[1]);
      b.appendChild(el("b", null, String(compte[o[0]])));
      b.onclick = function () { etat.filtre = o[0]; dessinerListe(); };
      box.appendChild(b);
    });
  }
  function dessinerListe() {
    dessinerOnglets();
    var box = document.getElementById("liste");
    box.textContent = "";
    var vus = etat.fans.filter(filtres);
    if (!vus.length) {
      box.appendChild(el("div", "vide", etat.fans.length ? "Aucun fan dans ce filtre." : "Aucun fan pour l'instant. Ils apparaîtront ici dès leur premier message."));
      return;
    }
    vus.forEach(function (f) {
      var ligne = el("div", "item" + (etat.sel === f.id ? " sel" : ""));
      ligne.appendChild(avatar(f));
      var corps = el("div", "corps");
      var l1 = el("div", "ligne1");
      l1.appendChild(el("span", "nom", nomDe(f)));
      l1.appendChild(el("span", "quand", quand(f.dernier.t || f.arrive)));
      corps.appendChild(l1);
      var prefixe = f.dernier.de === "fan" ? "" : (f.dernier.humain ? "Toi : " : "IA : ");
      corps.appendChild(el("div", "apercu", prefixe + (f.dernier.texte || "…")));
      var et = el("div", "etiquettes");
      et.appendChild(etiquetteIA(f));
      if (f.compte) et.appendChild(el("span", "tag", f.compte));
      if (f.non_lus) et.appendChild(el("span", "nonlus", String(f.non_lus)));
      corps.appendChild(et);
      ligne.appendChild(corps);
      ligne.onclick = function () { ouvrir(f.id); };
      box.appendChild(ligne);
    });
  }
  function chargerListe() {
    return api("/tgperso/inbox/liste").then(function (d) {
      etat.fans = d.fans || [];
      etat.maintenant = d.maintenant || 0;
      dessinerListe();
      if (etat.sel) {
        var f = etat.fans.filter(function (x) { return x.id === etat.sel; })[0];
        if (f) dessinerFiche(f);
      }
    }).catch(function () {});
  }

  // ---------------------------------------------------------- conversation
  function ouvrir(id) {
    etat.sel = id;
    etat.nbHisto = -1;
    document.getElementById("app").classList.add("ouvert");
    dessinerListe();
    chargerConv(true);
    api("/tgperso/inbox/action", { fan: id, quoi: "lu" }).then(chargerListe).catch(function () {});
  }
  function chargerConv(premier) {
    if (!etat.sel) return;
    var id = etat.sel;
    api("/tgperso/inbox/conv?fan=" + encodeURIComponent(id)).then(function (d) {
      if (etat.sel !== id || !d || !d.fan) return;
      var neuf = d.histo.length !== etat.nbHisto;
      etat.conv = d;
      if (premier) dessinerConv(d);
      else {
        dessinerTeteConv(d.fan);
        if (neuf) { dessinerFil(d); if (d.histo.length && d.histo[d.histo.length - 1].de === "fan") api("/tgperso/inbox/action", { fan: id, quoi: "lu" }).catch(function () {}); }
      }
      dessinerFiche(d.fan);
    }).catch(function () {});
  }
  function dessinerConv(d) {
    var col = document.getElementById("conv-col");
    col.textContent = "";
    var tete = el("div", "tete conv-tete");
    tete.id = "conv-tete";
    col.appendChild(tete);
    var fil = el("div", "fil");
    fil.id = "fil";
    col.appendChild(fil);
    var aide = el("div", "aide", "Écrire toi-même met l'IA en pause dans cette conversation (durée réglable dans ⚙️ Réglages).");
    col.appendChild(aide);
    var err = el("div", "erreur");
    err.id = "erreur";
    col.appendChild(err);
    var saisie = el("div", "saisie");
    var ta = el("textarea");
    ta.id = "texte";
    ta.rows = 1;
    ta.placeholder = "Répondre en tant que " + (d.fan.compte || "Lola") + "…";
    ta.addEventListener("input", function () { ta.style.height = "auto"; ta.style.height = Math.min(160, ta.scrollHeight) + "px"; });
    ta.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); envoyer(); } });
    var b = el("button", "envoyer", "➤");
    b.id = "btn-envoyer";
    b.title = "Envoyer";
    b.onclick = envoyer;
    saisie.appendChild(ta);
    saisie.appendChild(b);
    col.appendChild(saisie);
    dessinerTeteConv(d.fan);
    dessinerFil(d);
  }
  function dessinerTeteConv(f) {
    var tete = document.getElementById("conv-tete");
    if (!tete) return;
    tete.textContent = "";
    var retour = el("button", "retour", "‹");
    retour.onclick = function () { document.getElementById("app").classList.remove("ouvert"); };
    tete.appendChild(retour);
    tete.appendChild(avatar(f));
    var qui = el("div", "qui");
    qui.appendChild(el("b", null, nomDe(f)));
    var sous = (f.username ? "@" + f.username + " · " : "") + (f.compte || "");
    qui.appendChild(el("span", null, sous));
    tete.appendChild(qui);
    var inter = el("div", "interrupteur" + (f.ia && !f.pause_jusqua ? " on" : ""));
    var lib = f.mineur ? "Mineur : coupé" : !f.ia ? "IA coupée" : f.pause_jusqua ? "IA en pause jusqu'à " + heure(f.pause_jusqua) : "IA activée";
    inter.appendChild(el("span", null, lib));
    inter.appendChild(el("span", "bascule"));
    inter.title = f.pause_jusqua ? "Cliquer relance l'IA tout de suite" : "Allumer / couper l'IA pour ce fan";
    inter.onclick = function () {
      var allumer = !(f.ia && !f.pause_jusqua);
      api("/tgperso/inbox/action", { fan: f.id, quoi: "ia", actif: allumer }).then(function () { chargerConv(false); chargerListe(); });
    };
    if (!f.mineur) tete.appendChild(inter);
  }
  function dessinerFil(d) {
    var fil = document.getElementById("fil");
    if (!fil) return;
    var enBas = fil.scrollHeight - fil.scrollTop - fil.clientHeight < 80 || etat.nbHisto < 0;
    fil.textContent = "";
    var jourPrec = "";
    if (!d.histo.length) fil.appendChild(el("div", "vide", "Pas encore de message."));
    d.histo.forEach(function (h) {
      var j = jourDe(h.t);
      if (j !== jourPrec) { fil.appendChild(el("div", "jour", j)); jourPrec = j; }
      var moi = h.de !== "fan";
      var m = el("div", "msg " + (moi ? "moi" : "fan"));
      m.appendChild(el("div", "bulle", h.texte || ""));
      var meta = el("div", "meta");
      if (moi) meta.appendChild(el("span", h.humain ? "toi" : "ia", h.humain ? "Toi" : "✨ IA"));
      meta.appendChild(el("span", null, heure(h.t)));
      if (h.liens) meta.appendChild(el("span", null, "🔗 liens envoyés"));
      m.appendChild(meta);
      fil.appendChild(m);
    });
    etat.nbHisto = d.histo.length;
    if (enBas) fil.scrollTop = fil.scrollHeight;
  }
  function envoyer() {
    var ta = document.getElementById("texte"), b = document.getElementById("btn-envoyer"), err = document.getElementById("erreur");
    var texte = (ta.value || "").trim();
    if (!texte || !etat.sel) return;
    b.disabled = true;
    err.textContent = "";
    api("/tgperso/inbox/action", { fan: etat.sel, quoi: "envoyer", texte: texte }).then(function (r) {
      b.disabled = false;
      if (!r.ok) { err.textContent = r.erreur || "Envoi impossible."; return; }
      ta.value = "";
      ta.style.height = "auto";
      chargerConv(false);
      chargerListe();
    }).catch(function () { b.disabled = false; err.textContent = "Envoi impossible (réseau)."; });
  }

  // ---------------------------------------------------------- fiche
  var notesTimer = null;
  function kv(parent, cle, val) {
    if (val === undefined || val === null || val === "") return;
    var l = el("div", "kv");
    l.appendChild(el("span", null, cle));
    l.appendChild(el("span", null, String(val)));
    parent.appendChild(l);
  }
  function dessinerFiche(f) {
    var box = document.getElementById("fiche");
    var notesActif = document.activeElement && document.activeElement.id === "notes";
    if (notesActif) return;            // ne pas écraser une note en cours de frappe
    box.textContent = "";
    var haut = el("div", "haut");
    haut.appendChild(avatar(f, true));
    haut.appendChild(el("b", null, nomDe(f)));
    if (f.username) haut.appendChild(el("span", null, "@" + f.username));
    var st = el("span", "statut " + f.statut, f.statut === "abonne" ? "🟢 Abonné" : f.statut === "clique" ? "🟡 A cliqué" : "🔴 Rien cliqué");
    haut.appendChild(st);
    box.appendChild(haut);

    var b1 = el("div", "bloc");
    b1.appendChild(el("h3", null, "Telegram"));
    var LANG = { fr: "français", en: "anglais", es: "espagnol", de: "allemand", it: "italien", pt: "portugais", ar: "arabe" };
    kv(b1, "Langue de l'appli", f.langue ? (LANG[f.langue] || f.langue) : "");
    kv(b1, "Premium", f.premium ? "oui ⭐" : "non");
    kv(b1, "Âge", f.age !== null && f.age !== undefined ? f.age + " ans" : "");
    kv(b1, "Anniversaire", f.anniv);
    kv(b1, "Bio", f.bio);
    kv(b1, "Écrit sur", f.compte);
    box.appendChild(b1);

    var b2 = el("div", "bloc");
    b2.appendChild(el("h3", null, "Parcours"));
    kv(b2, "Arrivé", f.arrive ? jourDe(f.arrive).replace(/^./, function (c) { return c.toLowerCase(); }) + " à " + heure(f.arrive) : "");
    kv(b2, "Messages", f.nb_msg);
    kv(b2, "Abonné", f.abonne_t ? quand(f.abonne_t) : "pas encore");
    if (f.clics && f.clics.length) {
      f.clics.slice().reverse().forEach(function (c) { kv(b2, "🔗 " + c.lien, quand(c.t)); });
    } else kv(b2, "Clics", "aucun");
    box.appendChild(b2);

    var b3 = el("div", "bloc");
    b3.appendChild(el("h3", null, "Notes"));
    var ta = el("textarea");
    ta.id = "notes";
    ta.placeholder = "Ce qu'il aime, quand il est là, ce qu'il a dit…";
    ta.value = f.notes || "";
    ta.addEventListener("input", function () {
      clearTimeout(notesTimer);
      var id = f.id, v = ta.value;
      notesTimer = setTimeout(function () { api("/tgperso/inbox/action", { fan: id, quoi: "notes", notes: v }).catch(function () {}); }, 600);
    });
    b3.appendChild(ta);
    box.appendChild(b3);
  }

  document.getElementById("recherche").addEventListener("input", function (e) {
    etat.recherche = e.target.value.trim();
    dessinerListe();
  });
  chargerListe();
  setInterval(function () {
    if (document.hidden) return;
    chargerListe();
    chargerConv(false);
  }, 5000);
})();
</script>
</body></html>
"""


# Camp d'entraînement (/tgperso/entrainement). Même principe que l'Inbox :
# chaîne brute, aucun formatage Python, les données arrivent par __DONNEES__
# (JSON posé par la route) et tout texte passe par textContent.
ENTRAINEMENT_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entraînement IA</title>
<style>
:root{--bg:#0b0d12;--panel:#11141b;--panel2:#161a23;--bord:#232836;--txt:#e7e9ee;--mut:#8b92a3;
--acc:#4f8cff;--lola:#3b2d6b;--lola-bord:#5b46a8;--fan:#1d4ed8;--ok:#2fbf71;--warn:#e0a526;--bad:#e5484d}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f4f5f8;--panel:#fff;--panel2:#f7f8fb;
--bord:#e3e6ec;--txt:#171a21;--mut:#646b7a;--acc:#2563eb;--lola:#ece7ff;--lola-bord:#c9bcff;--fan:#2563eb}}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--txt);font:14px/1.45 system-ui,-apple-system,sans-serif}
a{color:var(--acc)}
.app{display:grid;grid-template-columns:320px 1fr;height:100vh}
.gauche{background:var(--panel);border-right:1px solid var(--bord);display:flex;flex-direction:column;min-width:0}
.tete{padding:14px 16px;border-bottom:1px solid var(--bord);display:flex;align-items:center;gap:10px}
.tete h1{font-size:17px;margin:0;flex:1}
.tete a{font-size:13px}
.sec{padding:12px 16px 4px;color:var(--mut);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.personas{overflow-y:auto;flex:1;padding:0 12px 12px}
.persona{border:1px solid var(--bord);background:var(--panel2);border-radius:12px;padding:10px 12px;margin-bottom:8px;cursor:pointer}
.persona:hover{border-color:var(--acc)}
.persona.on{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc) inset}
.persona b{display:block}
.persona span{color:var(--mut);font-size:12px;display:block;margin-top:2px}
.reglage{padding:10px 16px;border-top:1px solid var(--bord);display:flex;gap:8px;align-items:center;font-size:13px;color:var(--mut)}
.reglage input,.reglage select{background:var(--panel2);border:1px solid var(--bord);color:var(--txt);border-radius:8px;padding:5px 7px;font:inherit}
.reglage input[type=number]{width:60px}
.centre{display:flex;flex-direction:column;min-width:0}
.barre{padding:10px 16px;border-bottom:1px solid var(--bord);background:var(--panel);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.barre .qui{flex:1;min-width:160px}
.barre .qui b{display:block}
.barre .qui span{color:var(--mut);font-size:12px}
.btn{background:var(--panel2);border:1px solid var(--bord);color:var(--txt);border-radius:10px;padding:8px 12px;font:inherit;cursor:pointer}
.btn:hover{border-color:var(--acc)}
.btn.prim{background:var(--acc);border-color:var(--acc);color:#fff}
.btn:disabled{opacity:.5;cursor:default}
.fil{flex:1;overflow-y:auto;padding:18px 22px;display:flex;flex-direction:column;gap:10px;background:var(--bg)}
.vide{color:var(--mut);text-align:center;margin:auto;max-width:420px}
.msg{max-width:72%;display:flex;flex-direction:column}
.msg.fan{align-self:flex-end;align-items:flex-end}
.msg.lola{align-self:flex-start}
.bulle{padding:9px 13px;border-radius:16px;white-space:pre-wrap;word-break:break-word}
.msg.fan .bulle{background:var(--fan);color:#fff;border-bottom-right-radius:5px}
.msg.lola .bulle{background:var(--lola);border:1px solid var(--lola-bord);border-bottom-left-radius:5px}
.msg.lien .bulle{color:var(--acc);text-decoration:underline}
.meta{font-size:11px;color:var(--mut);margin-top:3px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.corriger{background:none;border:0;color:var(--acc);cursor:pointer;font:inherit;font-size:11px;padding:0}
.drapeau{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--bord)}
.drapeau.liens{color:var(--acc)}
.drapeau.mineur{color:var(--bad);border-color:#e5484d66}
.drapeau.abo{color:var(--ok);border-color:#2fbf7166}
.corrige{color:var(--ok)}
.edit{display:flex;flex-direction:column;gap:6px;width:min(520px,80vw)}
.edit textarea{min-height:70px;background:var(--panel2);border:1px solid var(--acc);color:var(--txt);border-radius:10px;padding:9px;font:inherit}
.edit div{display:flex;gap:6px}
.alerte{align-self:center;color:var(--bad);border:1px solid #e5484d66;border-radius:10px;padding:6px 12px;font-size:13px}
.info{align-self:center;color:var(--mut);font-size:12px}
.saisie{border-top:1px solid var(--bord);padding:12px 16px;display:flex;gap:10px;align-items:flex-end;background:var(--panel)}
.saisie textarea{flex:1;resize:none;min-height:44px;max-height:140px;background:var(--panel2);border:1px solid var(--bord);color:var(--txt);border-radius:12px;padding:11px 12px;font:inherit}
.erreur{color:var(--bad);font-size:12px;padding:0 16px 8px}
@media (max-width:820px){
 .app{grid-template-columns:1fr;grid-template-rows:auto 1fr;height:auto;min-height:100vh}
 .gauche{border-right:0;border-bottom:1px solid var(--bord)}
 .personas{display:flex;gap:8px;overflow-x:auto;padding-bottom:10px}
 .persona{min-width:160px;margin-bottom:0}
 .centre{min-height:80vh}
 .msg{max-width:88%}
}
</style></head>
<body>
<div class="app">
 <div class="gauche">
  <div class="tete"><h1>🎯 Entraînement</h1><a href="/tgperso/inbox">📥 Inbox</a><a href="/tgperso">⚙️</a></div>
  <div class="sec">Qui joue le fan ?</div>
  <div class="personas" id="personas"></div>
  <div class="reglage">Échanges par partie <input type="number" id="nb" min="1" max="20" value="6"></div>
 </div>
 <div class="centre">
  <div class="barre">
   <div class="qui"><b id="qui-titre">Toi</b><span id="qui-sous">Tu écris comme un fan. Rien ne part sur Telegram.</span></div>
   <button class="btn" id="btn-piege" title="Écrit une question difficile dans la zone de saisie">🎲 Question piège</button>
   <button class="btn prim" id="btn-lancer">▶️ Lancer</button>
   <button class="btn" id="btn-reset">🔄 Recommencer</button>
  </div>
  <div class="fil" id="fil"></div>
  <div class="erreur" id="erreur"></div>
  <div class="saisie">
   <textarea id="texte" rows="1" placeholder="Écris comme un fan… (Entrée pour envoyer)"></textarea>
   <button class="btn prim" id="btn-envoyer">➤</button>
  </div>
 </div>
</div>
<script>
(function () {
  "use strict";
  var D = __DONNEES__;
  var etat = { persona: "", histo: [], enCours: false, stop: false, coupe: false };

  function el(tag, cls, texte) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texte !== undefined && texte !== null) e.textContent = texte;
    return e;
  }
  function api(corps) {
    return fetch("/tgperso/entrainement/action", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps)
    }).then(function (r) {
      if (r.status === 403) { location.href = "/"; throw new Error("session"); }
      return r.json();
    });
  }
  function personaCourante() {
    for (var i = 0; i < D.personas.length; i++) if (D.personas[i].id === etat.persona) return D.personas[i];
    return null;
  }
  function erreur(t) { document.getElementById("erreur").textContent = t || ""; }

  function dessinerPersonas() {
    var box = document.getElementById("personas");
    box.textContent = "";
    var moi = el("div", "persona" + (etat.persona === "" ? " on" : ""));
    moi.appendChild(el("b", null, "🙋 Moi"));
    moi.appendChild(el("span", null, "Tu joues le fan toi-même."));
    moi.onclick = function () { choisir(""); };
    box.appendChild(moi);
    D.personas.forEach(function (p) {
      var c = el("div", "persona" + (etat.persona === p.id ? " on" : ""));
      c.appendChild(el("b", null, p.titre + " · " + p.nom));
      c.appendChild(el("span", null, p.role.length > 110 ? p.role.slice(0, 110) + "…" : p.role));
      c.onclick = function () { choisir(p.id); };
      box.appendChild(c);
    });
  }
  function choisir(id) {
    if (etat.enCours) return;
    etat.persona = id;
    var p = personaCourante();
    document.getElementById("qui-titre").textContent = p ? p.titre + " · " + p.nom : "Toi";
    document.getElementById("qui-sous").textContent = p
      ? "L'IA joue ce fan. ▶️ Lancer fait tourner la conversation toute seule."
      : "Tu écris comme un fan. Rien ne part sur Telegram.";
    document.getElementById("btn-lancer").style.display = p ? "" : "none";
    recommencer();
    dessinerPersonas();
  }
  function recommencer() {
    etat.histo = [];
    etat.coupe = false;
    erreur("");
    dessinerFil();
  }

  function dessinerFil() {
    var fil = document.getElementById("fil");
    fil.textContent = "";
    if (!etat.histo.length) {
      var v = el("div", "vide");
      v.appendChild(el("div", null, "Choisis un fan à gauche puis ▶️ Lancer, ou écris toi-même en bas."));
      v.appendChild(el("div", null, "Une réponse de " + D.prenom + " ne te plaît pas ? ✏️ Corriger : ta version devient un exemple qu'elle lira à chaque réponse."));
      fil.appendChild(v);
      return;
    }
    etat.histo.forEach(function (h, i) {
      if (h.de === "alerte") { fil.appendChild(el("div", "alerte", h.texte)); return; }
      if (h.de === "info") { fil.appendChild(el("div", "info", h.texte)); return; }
      var lola = h.de !== "fan";
      var m = el("div", "msg " + (lola ? "lola" : "fan") + (h.lien ? " lien" : ""));
      if (h.edition) {
        var ed = el("div", "edit");
        var ta = el("textarea");
        ta.value = h.texte;
        var bt = el("div");
        var ok = el("button", "btn prim", "Garder comme exemple");
        var non = el("button", "btn", "Annuler");
        ok.onclick = function () { sauverCorrection(i, ta.value); };
        non.onclick = function () { h.edition = false; dessinerFil(); };
        bt.appendChild(ok); bt.appendChild(non);
        ed.appendChild(ta); ed.appendChild(bt);
        m.appendChild(ed);
        fil.appendChild(m);
        setTimeout(function () { ta.focus(); }, 0);
        return;
      }
      m.appendChild(el("div", "bulle", h.texte));
      var meta = el("div", "meta");
      if (lola && !h.lien) {
        (h.drapeaux || []).forEach(function (d) { meta.appendChild(el("span", "drapeau " + d[0], d[1])); });
        if (h.corrige) meta.appendChild(el("span", "corrige", "✅ corrigé, gardé comme exemple"));
        else {
          var c = el("button", "corriger", "✏️ Corriger");
          c.onclick = function () { if (!etat.enCours) { h.edition = true; dessinerFil(); } };
          meta.appendChild(c);
        }
      }
      if (meta.childNodes.length) m.appendChild(meta);
      fil.appendChild(m);
    });
    fil.scrollTop = fil.scrollHeight;
  }

  function histoPourApi(jusqua) {
    return etat.histo.slice(0, jusqua === undefined ? etat.histo.length : jusqua)
      .filter(function (h) { return h.de === "fan" || h.de === "bot"; })
      .map(function (h) { return { de: h.de, texte: h.texte }; });
  }
  function sauverCorrection(i, texte) {
    texte = (texte || "").trim();
    if (!texte) return;
    api({ quoi: "corriger", histo: histoPourApi(i), correction: texte }).then(function (r) {
      if (!r.ok) { erreur(r.erreur || "Correction refusée."); return; }
      var h = etat.histo[i];
      h.texte = texte; h.edition = false; h.corrige = true;
      dessinerFil();
    }).catch(function () { erreur("Correction impossible (réseau)."); });
  }

  function reponseLola() {
    var p = personaCourante();
    return api({ quoi: "repondre", histo: histoPourApi(), nom: p ? p.nom : "", langue: p ? p.langue : "" }).then(function (r) {
      if (!r.ok) { erreur(r.erreur || "Pas de réponse."); return false; }
      var drap = [];
      if (r.liens && r.liens.length) drap.push(["liens", "🔗 lien envoyé"]);
      if (r.mineur) drap.push(["mineur", "⛔ mineur détecté"]);
      if (r.dit_abonne) drap.push(["abo", "🟢 dit abonné"]);
      r.messages.forEach(function (t, k) {
        etat.histo.push({ de: "bot", texte: t, drapeaux: k === r.messages.length - 1 ? drap : [] });
      });
      if (!r.messages.length && drap.length) etat.histo.push({ de: "info", texte: drap.map(function (d) { return d[1]; }).join(" · ") });
      (r.liens || []).forEach(function (u) { etat.histo.push({ de: "bot", texte: u, lien: true }); });
      if (r.mineur) {
        etat.coupe = true;
        etat.histo.push({ de: "alerte", texte: "⛔ Conversation coupée : sur Telegram, " + D.prenom + " ne répondrait plus à ce fan." });
      }
      dessinerFil();
      return true;
    });
  }
  function messageFan(texte) {
    etat.histo.push({ de: "fan", texte: texte });
    dessinerFil();
  }

  function envoyerMoi() {
    var ta = document.getElementById("texte");
    var t = (ta.value || "").trim();
    if (!t || etat.enCours) return;
    if (etat.coupe) { erreur("Conversation coupée (mineur). 🔄 Recommencer pour une nouvelle partie."); return; }
    ta.value = "";
    erreur("");
    messageFan(t);
    occuper(true);
    reponseLola().catch(function () { erreur("Erreur réseau."); }).then(function () { occuper(false); });
  }
  function occuper(oui) {
    etat.enCours = oui;
    document.getElementById("btn-envoyer").disabled = oui;
    document.getElementById("btn-reset").disabled = oui;
    var l = document.getElementById("btn-lancer");
    l.textContent = oui && etat.persona ? "⏸ Stop" : "▶️ Lancer";
    l.disabled = oui && !etat.persona;
  }
  function lancer() {
    if (etat.enCours) { etat.stop = true; return; }
    var p = personaCourante();
    if (!p) return;
    if (etat.coupe) recommencer();
    var n = Math.max(1, Math.min(20, parseInt(document.getElementById("nb").value, 10) || 6));
    etat.stop = false;
    erreur("");
    occuper(true);
    var i = 0;
    function tour() {
      if (etat.stop || etat.coupe || i >= n) { occuper(false); return; }
      i++;
      api({ quoi: "fan", persona: p.id, histo: histoPourApi() }).then(function (r) {
        if (!r.ok) { erreur(r.erreur || "Le fan simulé n'a pas répondu."); occuper(false); return; }
        messageFan(r.message);
        return reponseLola().then(function (ok) { if (ok) setTimeout(tour, 400); else occuper(false); });
      }).catch(function () { erreur("Erreur réseau."); occuper(false); });
    }
    tour();
  }

  document.getElementById("btn-envoyer").onclick = envoyerMoi;
  document.getElementById("texte").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); envoyerMoi(); }
  });
  document.getElementById("btn-piege").onclick = function () {
    var q = D.pieges[Math.floor(Math.random() * D.pieges.length)];
    var ta = document.getElementById("texte");
    ta.value = q;
    ta.focus();
  };
  document.getElementById("btn-lancer").onclick = lancer;
  document.getElementById("btn-reset").onclick = function () { if (!etat.enCours) recommencer(); };
  choisir("");
})();
</script>
</body></html>
"""
