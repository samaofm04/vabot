#!/usr/bin/env python3
"""Écrire dans un salon Discord depuis le Mac, sous l'identité du bot SEVEN.

    python3 discord_ecrire.py

Ouvre une petite page sur http://127.0.0.1:8787 : on choisit le serveur et le
salon, on écrit, SEVEN poste. On peut aussi REPRENDRE un message déjà posté
par le bot pour le corriger — Discord ne laisse modifier que ses propres
messages, et ceux du bot en sont.

LOCAL, ET SEULEMENT LOCAL. Rien n'est déployé, rien ne touche youl4b.com. Le
serveur n'écoute que 127.0.0.1 : la page n'est pas joignable depuis le
réseau, et le jeton ne quitte pas la machine. Fermer la fenêtre du terminal
arrête tout.

Le jeton est lu dans ~/.config/seven_bot_token (ou data/seven_bot_token, ou
la variable SEVEN_BOT_TOKEN) et n'est jamais envoyé à la page.

Rien d'autre que la bibliothèque standard : pas d'installation.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API = "https://discord.com/api/v10"
PORT = 8787
MAX_TEXTE = 2000            # limite Discord d'un message
MAX_EMBED = 4096            # limite Discord d'une description d'encadré
COULEUR_DEFAUT = 0x5865F2

# Les serveurs de l'agence. Repris de verif_discord.py ; on les met en dur
# pour que cet outil marche même lancé hors du dépôt.
try:
    # meme definition que le bot deploye : deux copies finiraient par diverger
    from copie_discord import bouton as BOUTON_COPIE
except Exception:
    BOUTON_COPIE = None

SERVEURS = ["1445108485090971710",       # YouLab TWITTER / THREADS
            "1552152470464110703"]       # YouLab - Entretien


def jeton() -> str:
    t = (os.environ.get("SEVEN_BOT_TOKEN") or "").strip()
    if t:
        return t
    for p in (Path.home() / ".config" / "seven_bot_token",
              Path(__file__).resolve().parent / "data" / "seven_bot_token"):
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


TOKEN = jeton()


def api(methode: str, chemin: str, corps=None, params=None):
    """(code, données). Ne lève jamais : la page affiche l'erreur."""
    url = API + chemin
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(corps).encode() if corps is not None else None
    req = urllib.request.Request(url, data=data, method=methode, headers={
        "Authorization": "Bot " + TOKEN, "Content-Type": "application/json",
        "User-Agent": "DiscordBot (youl4b-local, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            brut = r.read()
            return r.status, (json.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


def _multipart(payload: dict, fichiers):
    """Encode un envoi avec pièces jointes pour Discord.

    Discord veut du multipart : un champ `payload_json` avec le message, puis
    `files[0]`, `files[1]`… Et dans le message, une liste `attachments` où
    chaque entrée porte l'indice du fichier correspondant — sans elle, les
    images partent mais ne s'affichent pas.
    """
    limite = "----youl4b" + os.urandom(12).hex()
    morceaux = []

    def champ(entete: bytes, contenu: bytes):
        morceaux.append(b"--" + limite.encode() + b"\r\n" + entete + b"\r\n\r\n"
                        + contenu + b"\r\n")

    champ(b'Content-Disposition: form-data; name="payload_json"\r\n'
          b"Content-Type: application/json",
          json.dumps(payload, ensure_ascii=False).encode())
    for i, (nom, octets) in enumerate(fichiers):
        sur = nom.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
        champ(f'Content-Disposition: form-data; name="files[{i}]"; filename="{sur}"'
              .encode() + b"\r\nContent-Type: application/octet-stream", octets)
    morceaux.append(b"--" + limite.encode() + b"--\r\n")
    return b"".join(morceaux), f"multipart/form-data; boundary={limite}"


def api_fichiers(methode: str, chemin: str, payload: dict, fichiers):
    """Comme api(), mais avec des pièces jointes."""
    corps, type_contenu = _multipart(payload, fichiers)
    req = urllib.request.Request(API + chemin, data=corps, method=methode, headers={
        "Authorization": "Bot " + TOKEN, "Content-Type": type_contenu,
        "User-Agent": "DiscordBot (youl4b-local, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            brut = r.read()
            return r.status, (json.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


def salons(gid: str):
    """Les salons texte, groupés par catégorie — « name » ou « bio » seuls ne
    disent rien, il y en a dans plusieurs catégories."""
    code, rep = api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return []
    cats = {c["id"]: c.get("name") or "" for c in rep if c.get("type") == 4}
    textes = [c for c in rep if c.get("type") in (0, 5)]
    textes.sort(key=lambda c: (cats.get(c.get("parent_id"), "~"), c.get("position", 0)))
    return [{"id": str(c["id"]), "nom": c.get("name") or "",
             "categorie": cats.get(c.get("parent_id"), "(sans catégorie)")} for c in textes]


def corps_message(texte: str, titre: str, couleur: str, encadre: bool):
    texte = (texte or "").strip()
    mentions = {"parse": ["everyone", "roles", "users"]}
    if not encadre and not titre:
        return {"content": texte[:MAX_TEXTE], "allowed_mentions": mentions}
    try:
        c = int(str(couleur).lstrip("#"), 16) if couleur else COULEUR_DEFAUT
    except ValueError:
        c = COULEUR_DEFAUT
    e = {"description": texte[:MAX_EMBED], "color": c}
    if titre:
        e["title"] = titre[:256]
    return {"embeds": [e], "allowed_mentions": mentions}


def derniers(salon: str, combien: int = 15):
    """Les derniers messages DU BOT : ceux qu'on peut réécrire."""
    code, rep = api("GET", f"/channels/{salon}/messages", params={"limit": 50})
    if code != 200 or not isinstance(rep, list):
        return []
    out = []
    for m in rep:
        if not ((m.get("author") or {}).get("bot")):
            continue
        e = (m.get("embeds") or [{}])[0] if m.get("embeds") else {}
        out.append({"id": str(m.get("id")),
                    "date": str(m.get("timestamp") or "")[:16].replace("T", " "),
                    "encadre": bool(m.get("embeds")),
                    "titre": e.get("title") or "",
                    "couleur": f'{int(e.get("color") or 0):06X}' if e.get("color") else "",
                    "texte": e.get("description") or m.get("content") or "",
                    # les images déjà attachées : on les montre pour pouvoir en
                    # retirer une sans reposter tout le message
                    "images": [{"id": str(a.get("id")), "nom": a.get("filename") or "",
                                "url": a.get("url") or ""}
                               for a in (m.get("attachments") or [])]})
        if len(out) >= combien:
            break
    return out


PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Écrire dans un salon Discord</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--fond:#0b0b10;--carte:#161620;--bord:#2a2a3a;--texte:#e8e8f0;--faible:#8b8ba0;--bleu:#5865F2;--vert:#22c55e;--rouge:#ef4444}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px}
h1{font-size:19px;margin:0 0 4px}
.sous{color:var(--faible);font-size:13px;margin:0 0 20px}
.grille{display:grid;grid-template-columns:1fr 340px;gap:20px;max-width:1180px}
@media(max-width:900px){.grille{grid-template-columns:1fr}}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:14px;padding:16px}
label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--faible);font-weight:700;margin:12px 0 5px}
select,input,textarea{width:100%;padding:10px 12px;background:#0f0f18;border:1px solid var(--bord);color:var(--texte);border-radius:9px;font:inherit}
textarea{min-height:190px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px}
.ligne{display:flex;gap:10px;align-items:end;flex-wrap:wrap}
.ligne>*{flex:1;min-width:120px}
button{padding:11px 18px;border:0;border-radius:9px;font-weight:700;cursor:pointer;font-size:14px}
.envoyer{background:var(--bleu);color:#fff}
.gris{background:#26263a;color:var(--texte)}
.rouge{background:var(--rouge);color:#fff}
button:disabled{opacity:.5;cursor:default}
.etat{margin-top:12px;font-size:13.5px;min-height:20px}
.ok{color:var(--vert)}.ko{color:var(--rouge)}
.msg{background:#0f0f18;border:1px solid var(--bord);border-left:3px solid var(--bleu);border-radius:9px;padding:9px 11px;margin-bottom:8px;cursor:pointer}
.msg:hover{background:#151522}
.msg .q{font-size:11px;color:var(--faible)}
.msg .t{font-size:13px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.compte{font-size:11.5px;color:var(--faible);text-align:right;margin-top:4px}
.apercu{background:#0f0f18;border:1px solid var(--bord);border-radius:9px;padding:12px;margin-top:10px;white-space:pre-wrap;font-size:14px;min-height:40px}
.apercu.encadre{border-left:4px solid var(--bleu)}
.apercu .titre{font-weight:700;margin-bottom:6px}
.depot{margin-top:12px;border:2px dashed var(--bord);border-radius:11px;padding:16px;text-align:center;color:var(--faible);font-size:13px;cursor:pointer}
.depot:hover,.depot.survol{border-color:var(--bleu);color:var(--texte);background:rgba(88,101,242,.07)}
.vignettes{display:flex;gap:9px;flex-wrap:wrap;margin-top:10px}
.vignette{position:relative;width:78px;height:78px;border-radius:9px;overflow:hidden;border:1px solid var(--bord)}
.vignette img{width:100%;height:100%;object-fit:cover;display:block}
.vignette .x{position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.72);color:#fff;border:0;font-size:13px;line-height:20px;padding:0;cursor:pointer}
.vignette .v{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.6);color:#9fd3ff;font-size:9px;text-align:center}
.onglets{display:flex;gap:6px;margin-bottom:14px}
.onglets button{background:#0f0f18;color:var(--faible);border:1px solid var(--bord);font-size:13px;padding:8px 14px}
.onglets button.actif{background:var(--bleu);color:#fff;border-color:var(--bleu)}
.bout{background:#0f0f18;border:1px solid var(--bord);border-left:3px solid var(--bleu);border-radius:8px;padding:8px 11px;margin-bottom:7px;display:flex;gap:9px;align-items:start}
.bout .n{color:var(--faible);font-size:11px;font-weight:700;min-width:22px;padding-top:2px}
.bout .c{flex:1;font-size:13px;white-space:pre-wrap;word-break:break-word}
.bout .x{background:transparent;border:0;color:var(--faible);cursor:pointer;font-size:14px;padding:0 4px}
.bout .x:hover{color:var(--rouge)}
.bout.trop{border-left-color:var(--rouge)}
.liste-bouts{max-height:420px;overflow:auto;margin-top:10px}
.case{display:flex;align-items:center;gap:8px;margin-top:11px;color:var(--faible);
      font-size:12px;text-transform:none;letter-spacing:0;cursor:pointer}
.case input{width:auto;margin:0}
.case b{color:var(--texte)}
</style></head><body>
<h1>Écrire dans un salon Discord</h1>
<p class="sous">Le message est posté par <b>SEVEN</b>. Tout se passe sur ta machine — rien n'est déployé.</p>
<div class="grille">
  <div class="carte">
    <div class="onglets">
      <button id="onglet-un" class="actif">Un message</button>
      <button id="onglet-lot">Coller en masse</button>
    </div>
    <div class="ligne">
      <div><label>Serveur</label><select id="serveur"></select></div>
      <div><label>Salon</label><select id="salon"></select></div>
    </div>
    <div class="ligne" id="zone-titre">
      <div style="flex:2"><label>Titre <span style="text-transform:none">(vide = message simple, sans encadré)</span></label>
        <input id="titre" placeholder="ex : Infos modèle — Lola"></div>
      <div style="max-width:130px"><label>Couleur</label><input id="couleur" placeholder="5865F2"></div>
    </div>
    <div id="zone-un">
    <label>Message <span style="text-transform:none">— gras **texte**, lien &lt;#salon&gt;, saut de ligne accepté</span></label>
    <textarea id="texte" placeholder="Écris ici…"></textarea>
    <div class="compte" id="compte"></div>
    <div class="depot" id="depot">Glisse tes photos ici, ou clique pour les choisir · 10 max, 9 Mo chacune</div>
    <input type="file" id="fichiers" accept="image/*,video/*" multiple style="display:none">
    <div class="vignettes" id="vignettes"></div>
    <div class="apercu" id="apercu"></div>
    </div>

    <div id="zone-lot" style="display:none">
      <div class="ligne">
        <div><label>Separation</label><select id="sep">
          <option value="auto">Automatique (devine)</option>
          <option value="vide">Ligne vide entre chaque</option>
          <option value="ligne">Un par ligne</option>
          <option value="lien">Une URL par message (le reste est ignore)</option>
          <option value="num">Numerotation (1. 2. 3.)</option>
          <option value="point">Un point suivi d'un espace</option>
          <option value="perso">Separateur a moi</option>
        </select></div>
        <div style="max-width:170px"><label>Lequel</label>
          <input id="sepperso" placeholder="ex : ---" disabled></div>
      </div>
      <label>Colle tout ici <span style="text-transform:none">&mdash; un message par morceau, poste dans l'ordre</span></label>
      <textarea id="brut" placeholder="Colle tes captions, tes liens, tes bios&hellip;"></textarea>
      <div class="compte" id="comptelot"></div>
      <label class="case"><input type="checkbox" id="copier" checked>
        Poser un bouton <b>Copier</b> sous chaque message</label>
      <div class="liste-bouts" id="bouts"></div>
    </div>

    <div class="ligne" style="margin-top:14px">
      <button class="envoyer" id="envoyer">Poster</button>
      <button class="gris" id="annuler" style="display:none">Nouveau message</button>
      <button class="rouge" id="supprimer" style="display:none">Supprimer</button>
    </div>
    <div class="etat" id="etat"></div>
  </div>
  <div class="carte">
    <label style="margin-top:0">Derniers messages du bot dans ce salon</label>
    <p class="sous" style="margin:0 0 10px">Clique pour le reprendre et le corriger.</p>
    <div id="liste"></div>
  </div>
</div>
<script>
var E = function(i){ return document.getElementById(i); };
var enCours = null;   // l'id du message qu'on est en train de corriger
var neuves = [];      // images ajoutées maintenant : {nom, b64, url}
var gardees = [];     // images déjà attachées qu'on garde : {id, nom, url}

function vignettes(){
  var z = E('vignettes'); z.innerHTML = '';
  function carte(src, legende, retirer){
    var d = document.createElement('div'); d.className = 'vignette';
    var i = document.createElement('img'); i.src = src; d.appendChild(i);
    if(legende){ var v = document.createElement('div'); v.className = 'v'; v.textContent = legende; d.appendChild(v); }
    var b = document.createElement('button'); b.className = 'x'; b.textContent = '✕';
    b.title = 'Retirer'; b.onclick = retirer; d.appendChild(b);
    z.appendChild(d);
  }
  gardees.forEach(function(g, i){
    carte(g.url, 'déjà là', function(){ gardees.splice(i, 1); vignettes(); });
  });
  neuves.forEach(function(n, i){
    carte(n.url, '', function(){ neuves.splice(i, 1); vignettes(); });
  });
}

function ajouter(liste){
  var restant = 10 - (neuves.length + gardees.length);
  Array.prototype.slice.call(liste, 0, Math.max(0, restant)).forEach(function(f){
    var lect = new FileReader();
    lect.onload = function(){
      var s = String(lect.result);
      neuves.push({nom: f.name, b64: s.slice(s.indexOf(',') + 1), url: s});
      vignettes();
    };
    lect.readAsDataURL(f);
  });
  if(restant <= 0) etat('10 fichiers au maximum par message.', 'ko');
}

E('depot').onclick = function(){ E('fichiers').click(); };
E('fichiers').onchange = function(){ ajouter(this.files); this.value = ''; };
['dragenter','dragover'].forEach(function(e){
  E('depot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.add('survol'); });
});
['dragleave','drop'].forEach(function(e){
  E('depot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.remove('survol'); });
});
E('depot').addEventListener('drop', function(ev){ ajouter(ev.dataTransfer.files); });
// déposer n'importe où dans la page marche aussi, sans ouvrir le fichier
document.addEventListener('dragover', function(e){ e.preventDefault(); });
document.addEventListener('drop', function(e){
  e.preventDefault();
  if(e.target.closest && e.target.closest('#depot')) return;
  if(e.dataTransfer && e.dataTransfer.files.length) ajouter(e.dataTransfer.files);
});

function etat(txt, classe){ var e = E('etat'); e.textContent = txt; e.className = 'etat ' + (classe || ''); }

function apercu(){
  var t = E('texte').value, ti = E('titre').value.trim(), c = E('couleur').value.trim();
  var a = E('apercu');
  a.className = 'apercu' + (ti ? ' encadre' : '');
  a.style.borderLeftColor = ti ? ('#' + (c || '5865F2')) : '';
  a.textContent = '';
  if(ti){ var d = document.createElement('div'); d.className = 'titre'; d.textContent = ti; a.appendChild(d); }
  a.appendChild(document.createTextNode(t));
  var max = ti ? 4096 : 2000;
  E('compte').textContent = t.length + ' / ' + max + (t.length > max ? ' — le surplus sera coupé' : '');
  E('compte').style.color = t.length > max ? '#ef4444' : '';
}

var modeLot = false;
var lot = [];   // les morceaux du collage, dans l'ordre ou ils partiront

var NOMS = {num:'numerotation', vide:'ligne vide', ligne:'une par ligne',
            lien:'une URL par message', point:'point suivi d un espace',
            perso:'ton separateur'};

// Discord n'interprete PAS [texte](url) dans un message simple : il l'affiche
// tel quel, et le lien n'est pas cliquable. Une URL nue l'est. On ramene donc
// tout lien masque a son URL — le libelle reste devant quand il dit autre chose.
var RE_MASQUE = /\[([^\]\n]*)\]\((<?)(https?:\/\/[^)\s]+?)>?\)/g;
var remisAPlat = 0;

function nettoyerLiens(m){
  return m.replace(RE_MASQUE, function(_, t, __, u){
    remisAPlat++;
    t = t.trim().replace(/\/+$/, '');
    return (!t || t === u.replace(/\/+$/, '')) ? u : (t + ' ' + u);
  });
}

// Un collage venu d'un tableur, d'une note ou d'un doc traine toujours des
// restes : une puce, un numero, des guillemets autour de tout, deux espaces,
// des caracteres invisibles. Ils partiraient tels quels dans le message.
var nettoyes = 0;
var PAIRES = [['"','"'], ['“','”'], ['«','»'], ["'","'"]];

function nettoyerBrut(m){
  var avant = m;
  m = m.replace(/[​-‏⁠﻿]/g, '');
  // une puce ou un numero EN TETE seulement, et suivi d'une espace : une
  // caption qui commence par un tiret volontaire n'est pas touchee
  m = m.replace(/^\s*(?:[-–—*•·>]|\d{1,3}[.)])[ \t]+/, '');
  m = m.trim();
  // des guillemets qui enferment TOUT le morceau : ceux du texte restent
  for(var i = 0; i < PAIRES.length; i++){
    if(m.length > 1 && m.charAt(0) === PAIRES[i][0] && m.charAt(m.length - 1) === PAIRES[i][1]){
      m = m.slice(1, -1).trim(); break;
    }
  }
  m = m.replace(/[ \t]{2,}/g, ' ');
  if(m !== avant) nettoyes++;
  return m;
}

function detecter(t){
  // la numerotation passe avant la ligne vide : une liste numerotee dont les
  // items sont espaces garderait sinon son "1." colle au debut du message
  if((t.match(/(?:^|\n)[ \t]*\d{1,3}[ \t]*[.)\-][ \t]+/g) || []).length >= 2) return 'num';
  if(/\n[ \t]*\n/.test(t)) return 'vide';
  if(/\n/.test(t)) return 'ligne';
  if((t.match(/https?:\/\//g) || []).length >= 2) return 'lien';
  return 'point';
}

function decouper(t, mode, perso){
  t = String(t || '');
  if(!t.trim()) return [];
  if(mode === 'auto') mode = detecter(t);
  var b;
  if(mode === 'num')        b = t.split(/(?:^|\n)[ \t]*\d{1,3}[ \t]*[.)\-][ \t]+/);
  else if(mode === 'vide')  b = t.split(/\n[ \t]*\n+/);
  else if(mode === 'ligne') b = t.split(/\n+/);
  // une liste de liens collee d'un bloc : on prend les URL une par une
  else if(mode === 'lien')  b = (nettoyerLiens(t).match(/https?:\/\/\S+/g) || []);
  // un point colle a un chiffre ("daddy-19.9") n'est pas une fin de phrase :
  // on ne coupe que sur un point suivi d'une espace
  else if(mode === 'point') b = t.replace(/([.!?…])[ \t]+/g, '$1\u0000').split('\u0000');
  else if(mode === 'perso') b = perso ? t.split(perso) : [t];
  else b = [t];
  remisAPlat = 0; nettoyes = 0;
  return b.map(function(x){ return nettoyerBrut(nettoyerLiens(x.trim())); })
          .filter(function(x){ return x.length; });
}

function rendreLot(recalculer){
  if(recalculer !== false)
    lot = decouper(E('brut').value, E('sep').value, E('sepperso').value);
  var z = E('bouts'); z.innerHTML = '';
  lot.forEach(function(m, i){
    var d = document.createElement('div');
    d.className = 'bout' + (m.length > 2000 ? ' trop' : '');
    var n = document.createElement('div'); n.className = 'n'; n.textContent = (i + 1) + '.';
    var c = document.createElement('div'); c.className = 'c'; c.textContent = m;
    var x = document.createElement('button'); x.className = 'x'; x.textContent = '✕';
    x.title = 'Ne pas envoyer celui-la';
    x.onclick = function(){ lot.splice(i, 1); rendreLot(false); };
    d.appendChild(n); d.appendChild(c); d.appendChild(x);
    z.appendChild(d);
  });
  var e = E('comptelot');
  if(!lot.length){ e.textContent = E('brut').value.trim() ? 'Rien a decouper.' : ''; e.style.color = ''; return; }
  var m = E('sep').value === 'auto' ? detecter(E('brut').value) : E('sep').value;
  var trop = lot.filter(function(x){ return x.length > 2000; }).length;
  var txt = lot.length + ' message' + (lot.length > 1 ? 's' : '') + ' · coupe sur : ' + (NOMS[m] || m)
          + ' · environ ' + Math.ceil(lot.length * 1.1) + ' s d envoi';
  if(remisAPlat) txt += ' · ' + remisAPlat + ' lien(s) [..](..) remis a plat pour rester cliquables';
  if(nettoyes) txt += ' · ' + nettoyes + ' morceau(x) nettoye(s) : puce, numero, guillemets, espaces en trop';
  if(m === 'lien') txt += ' · seules les URL sont gardees';
  if(trop) txt += ' · ' + trop + ' depasse(nt) 2000 caracteres, le surplus sera coupe';
  if(lot.length > 300) txt += ' · trop d un coup : 300 au maximum';
  e.textContent = txt;
  e.style.color = (trop || lot.length > 300) ? '#ef4444' : '';
}

function basculer(versLot){
  modeLot = versLot;
  nouveau();
  E('onglet-lot').className = versLot ? 'actif' : '';
  E('onglet-un').className  = versLot ? '' : 'actif';
  E('zone-lot').style.display   = versLot ? '' : 'none';
  E('zone-un').style.display    = versLot ? 'none' : '';
  E('zone-titre').style.display = versLot ? 'none' : '';
  E('envoyer').textContent = versLot ? 'Poster les messages' : 'Poster';
  if(versLot) rendreLot();
}

async function demander(chemin, corps){
  var r = await fetch(chemin, corps ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(corps)} : undefined);
  return await r.json();
}

async function chargerSalons(){
  E('salon').innerHTML = '<option>…</option>';
  var j = await demander('/salons?g=' + encodeURIComponent(E('serveur').value));
  E('salon').innerHTML = '';
  var cat = null;
  (j.salons || []).forEach(function(s){
    if(s.categorie !== cat){ cat = s.categorie;
      var g = document.createElement('optgroup'); g.label = cat; g.id = 'g-' + cat; E('salon').appendChild(g); }
    var o = document.createElement('option'); o.value = s.id; o.textContent = s.nom;
    E('salon').lastChild.appendChild(o);
  });
  if(!(j.salons || []).length) etat('Aucun salon lisible sur ce serveur.', 'ko');
  chargerMessages();
}

async function chargerMessages(){
  E('liste').innerHTML = '<p class="sous">…</p>';
  var j = await demander('/messages?c=' + encodeURIComponent(E('salon').value));
  E('liste').innerHTML = '';
  if(!(j.messages || []).length){ E('liste').innerHTML = '<p class="sous">Le bot n\'a rien posté ici.</p>'; return; }
  j.messages.forEach(function(m){
    var d = document.createElement('div'); d.className = 'msg';
    var q = document.createElement('div'); q.className = 'q';
    q.textContent = m.date + (m.encadre ? ' · encadré' : '');
    var t = document.createElement('div'); t.className = 't';
    t.textContent = m.titre || m.texte.split('\n')[0] || '(vide)';
    d.appendChild(q); d.appendChild(t);
    d.onclick = function(){
      // reprendre un message en mode collage n'aurait pas de sens : on revient
      if(modeLot) basculer(false);
      enCours = m.id;
      E('titre').value = m.titre || ''; E('couleur').value = m.couleur || '';
      E('texte').value = m.texte;
      neuves = []; gardees = (m.images || []).slice();
      E('envoyer').textContent = 'Enregistrer la correction';
      E('annuler').style.display = ''; E('supprimer').style.display = '';
      etat('Tu corriges un message déjà posté.', '');
      apercu(); vignettes(); window.scrollTo(0, 0);
    };
    E('liste').appendChild(d);
  });
}

function nouveau(){
  enCours = null;
  E('titre').value = ''; E('couleur').value = ''; E('texte').value = '';
  neuves = []; gardees = [];
  E('envoyer').textContent = 'Poster';
  E('annuler').style.display = 'none'; E('supprimer').style.display = 'none';
  etat(''); apercu(); vignettes();
}

async function envoyerLot(bouton){
  if(!lot.length){ etat('Rien a envoyer : colle ton texte au-dessus.', 'ko'); return; }
  if(lot.length > 300){ etat(lot.length + ' messages : trop d un coup (300 au maximum).', 'ko'); return; }
  if(!confirm('Poster ' + lot.length + ' messages, un par un, dans ce salon ?')) return;
  bouton.disabled = true;
  etat('Envoi de ' + lot.length + ' messages… laisse la page ouverte (~'
       + Math.ceil(lot.length * 1.1) + ' s).');
  var j = await demander('/poster_lot', {salon: E('salon').value, messages: lot,
                                        copier: E('copier').checked});
  bouton.disabled = false;
  if(j.error && !j.envoyes){ etat('✕ ' + j.error, 'ko'); return; }
  if((j.echecs || []).length){
    // on nomme les rates : le reste est parti, il ne faut surtout pas tout reposter
    etat('⚠ ' + j.envoyes + ' / ' + j.total + ' postes. Rates : '
         + j.echecs.map(function(x){ return '#' + x.n + ' (' + x.erreur + ')'; }).join(' · '), 'ko');
  } else {
    etat('✓ ' + j.envoyes + ' messages postes.', 'ok');
    E('brut').value = ''; rendreLot();
  }
  chargerMessages();
}

E('envoyer').onclick = async function(){
  if(modeLot) return envoyerLot(this);
  // une photo seule est un message valable : on n'exige du texte que s'il
  // n'y a rien d'autre à envoyer
  if(!E('texte').value.trim() && !neuves.length && !gardees.length){
    etat('Rien à envoyer : écris un message ou dépose une photo.', 'ko'); return;
  }
  this.disabled = true;
  etat(neuves.length ? ('Envoi de ' + neuves.length + ' fichier(s)…') : 'Envoi…');
  var j = await demander('/poster', {salon: E('salon').value, message: enCours,
    texte: E('texte').value, titre: E('titre').value.trim(), couleur: E('couleur').value.trim(),
    images: neuves.map(function(n){ return {nom: n.nom, b64: n.b64}; }),
    garder: gardees.map(function(g){ return g.id; })});
  this.disabled = false;
  if(!j.ok){ etat('✕ ' + (j.error || 'Erreur'), 'ko'); return; }
  etat(enCours ? '✓ Message corrigé.' : '✓ Message posté.' + (j.coupe ? ' (' + j.coupe + ' caractères coupés)' : ''), 'ok');
  nouveau(); chargerMessages();
};

E('supprimer').onclick = async function(){
  if(!enCours || !confirm('Supprimer ce message du salon ?')) return;
  var j = await demander('/supprimer', {salon: E('salon').value, message: enCours});
  if(!j.ok){ etat('✕ ' + (j.error || 'Erreur'), 'ko'); return; }
  etat('✓ Message supprimé.', 'ok'); nouveau(); chargerMessages();
};

E('onglet-un').onclick  = function(){ basculer(false); };
E('onglet-lot').onclick = function(){ basculer(true); };
E('brut').oninput = function(){ rendreLot(); };
E('sepperso').oninput = function(){ rendreLot(); };
E('sep').onchange = function(){
  E('sepperso').disabled = this.value !== 'perso';
  rendreLot();
};
E('annuler').onclick = nouveau;
E('serveur').onchange = chargerSalons;
E('salon').onchange = chargerMessages;
['texte','titre','couleur'].forEach(function(i){ E(i).oninput = apercu; });

(async function(){
  var j = await demander('/serveurs');
  (j.serveurs || []).forEach(function(s){
    var o = document.createElement('option'); o.value = s.id; o.textContent = s.nom;
    E('serveur').appendChild(o);
  });
  if(!(j.serveurs || []).length){ etat('Aucun serveur joignable — le jeton du bot est-il en place ?', 'ko'); return; }
  chargerSalons(); apercu();
})();
</script></body></html>"""


class Poste(BaseHTTPRequestHandler):
    def _envoyer(self, data, code=200):
        brut = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def _lire(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        chemin, _, requete = self.path.partition("?")
        q = urllib.parse.parse_qs(requete)
        if chemin == "/":
            brut = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(brut)))
            self.end_headers()
            self.wfile.write(brut)
            return
        if chemin == "/serveurs":
            out = []
            for gid in SERVEURS:
                code, rep = api("GET", f"/guilds/{gid}")
                if code == 200:
                    out.append({"id": gid, "nom": rep.get("name") or gid})
            return self._envoyer({"serveurs": out})
        if chemin == "/salons":
            return self._envoyer({"salons": salons((q.get("g") or [""])[0])})
        if chemin == "/messages":
            return self._envoyer({"messages": derniers((q.get("c") or [""])[0])})
        self._envoyer({"error": "inconnu"}, 404)

    def do_POST(self):
        d = self._lire()
        salon = str(d.get("salon") or "")
        if self.path == "/supprimer":
            code, rep = api("DELETE", f'/channels/{salon}/messages/{d.get("message")}')
            return self._envoyer({"ok": code in (200, 204),
                                  "error": "" if code in (200, 204) else f"HTTP {code}"})
        if self.path == "/poster_lot":
            return self._lot(d)
        if self.path != "/poster":
            return self._envoyer({"error": "inconnu"}, 404)
        texte = str(d.get("texte") or "")
        titre = str(d.get("titre") or "")
        corps = corps_message(texte, titre, str(d.get("couleur") or ""), bool(titre))
        msg = d.get("message")

        # Images : celles qu'on ajoute maintenant, et celles déjà attachées
        # qu'on garde. Discord EFFACE toute pièce jointe absente de la liste
        # `attachments` d'un PATCH — d'où le renvoi explicite des gardées.
        neuves = []
        for im in (d.get("images") or [])[:10]:
            try:
                octets = base64.b64decode(str(im.get("b64") or ""), validate=True)
            except Exception:
                continue
            if octets:
                neuves.append((str(im.get("nom") or "image.png"), octets))
        gardees = [str(x) for x in (d.get("garder") or [])]

        trop = [n for n, o in neuves if len(o) > 9 * 1024 * 1024]
        if trop:
            return self._envoyer({"ok": False,
                                  "error": "Trop lourd pour Discord (9 Mo max) : "
                                           + ", ".join(trop)})
        if neuves or (msg and gardees is not None):
            jointes = [{"id": i} for i in gardees]
            jointes += [{"id": i, "filename": n}
                        for i, (n, _) in enumerate(neuves, start=len(gardees))]
            if msg or neuves:
                corps["attachments"] = jointes

        if msg and neuves:
            code, rep = api_fichiers("PATCH", f"/channels/{salon}/messages/{msg}",
                                     corps, neuves)
        elif msg:
            code, rep = api("PATCH", f"/channels/{salon}/messages/{msg}", corps)
        elif neuves:
            code, rep = api_fichiers("POST", f"/channels/{salon}/messages",
                                     corps, neuves)
        else:
            code, rep = api("POST", f"/channels/{salon}/messages", corps)
        if code != 200:
            return self._envoyer({"ok": False,
                                  "error": f'Discord a refusé (HTTP {code}) : '
                                           f'{str(rep.get("message") or rep)[:160]}'})
        limite = MAX_EMBED if titre else MAX_TEXTE
        return self._envoyer({"ok": True, "id": str(rep.get("id") or ""),
                              "coupe": max(0, len(texte.strip()) - limite)})

    def _lot(self, d):
        """Poste une liste de messages, un par un, dans l'ordre.

        Discord accepte environ 5 messages par 5 secondes dans un salon : on
        laisse une seconde entre chaque et on respecte le délai qu'il demande
        quand il dit stop (429). Un envoi raté n'arrête pas les suivants — le
        compte rendu dit lesquels sont passés, pour reprendre la main dessus
        sans tout reposter.
        """
        salon = str(d.get("salon") or "")
        titre = str(d.get("titre") or "")
        couleur = str(d.get("couleur") or "")
        messages = [str(x or "").strip() for x in (d.get("messages") or [])]
        messages = [m for m in messages if m]
        if not salon or not messages:
            return self._envoyer({"ok": False, "error": "Salon vide ou aucun message"})
        if len(messages) > 300:
            return self._envoyer({"ok": False,
                                  "error": f"{len(messages)} messages : trop d'un coup "
                                           "(300 au maximum). Coupe le collage en deux."})
        copier = bool(d.get("copier")) and BOUTON_COPIE is not None
        if d.get("copier") and BOUTON_COPIE is None:
            return self._envoyer({"ok": False,
                                  "error": "copie_discord.py est introuvable : "
                                           "pas de bouton Copier possible."})
        envoyes, echecs = 0, []
        for i, texte in enumerate(messages):
            corps = corps_message(texte, titre, couleur, bool(titre))
            if copier:
                corps["components"] = BOUTON_COPIE()
            for essai in range(3):
                code, rep = api("POST", f"/channels/{salon}/messages", corps)
                if code == 429:
                    time.sleep(float(rep.get("retry_after") or 1) + 0.3)
                    continue
                break
            if code == 200:
                envoyes += 1
            else:
                echecs.append({"n": i + 1,
                               "apercu": texte[:60],
                               "erreur": str(rep.get("message") or f"HTTP {code}")[:120]})
            time.sleep(1.0)
        return self._envoyer({"ok": not echecs, "envoyes": envoyes,
                              "total": len(messages), "echecs": echecs})

    def log_message(self, *a):
        pass          # le terminal reste lisible


def main():
    if not TOKEN:
        print("Jeton du bot introuvable.\n"
              "Attendu dans ~/.config/seven_bot_token, data/seven_bot_token, "
              "ou la variable SEVEN_BOT_TOKEN.", file=sys.stderr)
        return 1
    # 127.0.0.1 et pas 0.0.0.0 : la page n'est pas joignable depuis le réseau.
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Poste)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Écrire dans un salon Discord : {url}\nCtrl+C pour arrêter.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
