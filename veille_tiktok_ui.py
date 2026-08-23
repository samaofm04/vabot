"""veille_tiktok_ui.py — L'onglet « TikTok Trends » du tableau de bord.

Le rendu et les routes sont ici plutôt que dans `web_upload.py` : ce dernier
fait déjà 49 000 lignes, et cette fonctionnalité est indépendante. Le câblage
côté `web_upload.py` se réduit à cinq lignes (bouton de nav, panneau,
remplacement du gabarit, table de rendu paresseux, permission) plus l'appel à
`register(app, is_auth)` — le même motif que `facture_web` et `parc_web`.

La logique métier, elle, est dans `veille_tiktok.py`. Ici il n'y a que de
l'affichage et du HTTP.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List

import veille_tiktok as vtk

#: Tarif Apify au résultat, pour l'estimation affichée avant de cliquer.
#: Annoncé plutôt que caché : c'est de l'argent réel, et le bouton en dépense.
PRIX_RESULTAT = 0.005

TRIS = [("vues", "Vues"), ("taux", "Engagement"),
        ("surperf", "Surperformance"), ("recent", "Vitesse")]

_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _gros(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _comptes_saisis(brut: str) -> List[str]:
    """« @a, b\nhttps://tiktok.com/@c » -> ['a', 'b', 'c'] sans doublon."""
    morceaux = re.split(r"[\s,;]+", str(brut or ""))
    vus, out = set(), []
    for m in morceaux:
        m = m.strip()
        if not m:
            continue
        trouve = re.search(r"@([\w.\-]+)", m)
        nom = (trouve.group(1) if trouve else m).lstrip("@").strip("/")
        nom = nom.split("/")[0].split("?")[0]
        if nom and nom.lower() not in vus:
            vus.add(nom.lower())
            out.append(nom)
    return out


# ------------------------------------------------------------------ rendu --

def _carte(g: Dict[str, Any]) -> str:
    e = html.escape
    s = g.get("scores") or {}
    vid = str(g.get("id") or "")
    a_video = bool(g.get("video_fichier")) and vtk.a_le_fichier(vid)

    if a_video:
        media = (f"<video controls preload='none' playsinline "
                 f"src='/tiktok/video/{e(vid)}' "
                 f"style='width:100%;aspect-ratio:9/16;object-fit:cover;"
                 f"background:#000;display:block'></video>")
    else:
        couv = e(g.get("couverture") or "")
        fond = (f"background-image:url('{couv}');background-size:cover;"
                f"background-position:center;" if couv else "background:#000;")
        media = (f"<a href='{e(g.get('url') or '#')}' target='_blank' "
                 f"rel='noopener' style='display:block;width:100%;"
                 f"aspect-ratio:9/16;{fond}position:relative'>"
                 f"<span style='position:absolute;left:8px;bottom:8px;"
                 f"background:rgba(0,0,0,.7);color:#ddd;font-size:10px;"
                 f"padding:3px 7px;border-radius:5px'>voir sur TikTok</span></a>")

    lignes = [f"<span><b style='color:#fff'>{_gros(g.get('vues'))}</b> vues</span>"]
    if s.get("taux"):
        lignes.append(f"<span><b style='color:#fff'>{s['taux'] * 100:.1f}%</b> eng.</span>")
    if s.get("surperf"):
        lignes.append(f"<span style='color:#43b581;font-weight:700'>"
                      f"x{s['surperf']:.1f}</span>")

    return (
        "<div style='background:#161616;border:1px solid #2a2a2a;"
        "border-radius:12px;overflow:hidden;display:flex;flex-direction:column'>"
        + media +
        "<div style='padding:10px 12px 12px'>"
        f"<div style='color:#3b82f6;font-weight:600;font-size:12px'>"
        f"@{e(g.get('compte') or '')}</div>"
        "<div style='display:flex;gap:10px;flex-wrap:wrap;margin:6px 0;"
        "font-size:11px;color:#888'>" + "".join(lignes) + "</div>"
        f"<div style='font-size:11.5px;color:#aaa;max-height:48px;"
        f"overflow:hidden'>{e(g.get('titre') or '')}</div>"
        f"<div style='margin-top:8px;font-size:11px;color:#666'>"
        f"{e(g.get('date') or '')}</div>"
        "</div></div>")


def rendu_html(tri: str = "vues") -> str:
    """Le contenu de l'onglet. Aucune requête réseau : tout vient du magasin."""
    if tri not in dict(TRIS):
        tri = "vues"
    e = html.escape
    configure = vtk.configured()
    comptes = vtk.comptes_suivis()
    lignes = vtk.classer(tri=tri, n=60)

    boutons = "".join(
        f"<button onclick=\"tkTri('{cle}')\" style=\"padding:8px 16px;"
        f"background:{'#3b82f6' if cle == tri else '#1f1f1f'};color:"
        f"{'#fff' if cle == tri else '#999'};border:1px solid "
        f"{'#3b82f6' if cle == tri else '#2a2a2a'};border-radius:8px;"
        f"cursor:pointer;font-size:12px;font-weight:600\">{lib}</button>"
        for cle, lib in TRIS)

    puces = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"background:#1f1f1f;border:1px solid #2a2a2a;border-radius:20px;"
        f"padding:5px 12px;font-size:12px;color:#ddd'>@{e(c['compte'])}"
        f"<span style='color:#666'>{c['videos']}</span>"
        f"<b onclick=\"tkOublier('{e(c['compte'])}')\" style='cursor:pointer;"
        f"color:#e0576b'>&times;</b></span>"
        for c in comptes) or "<span style='color:#666;font-size:12px'>Aucun compte suivi pour l'instant.</span>"

    alerte = "" if configure else (
        "<div style='background:#3a2a1a;border:1px solid #6a4a20;color:#f0c070;"
        "border-radius:10px;padding:12px 14px;margin-bottom:16px;font-size:13px'>"
        "Aucun token Apify. Réglages &rarr; <b>Token API Apify</b> — le même "
        "que la veille Instagram, il n'y en a qu'un à renseigner.</div>")

    grille = ("".join(_carte(g) for g in lignes) if lignes else
              "<div style='grid-column:1/-1;background:#1a1a1a;border:1px solid "
              "#2a2a2a;border-radius:12px;padding:50px 20px;text-align:center;"
              "color:#666'>Rien encore. Ajoute un compte concurrent ci-dessus "
              "et lance la collecte.</div>")

    return f"""
<h2 style="margin:0 0 6px;font-size:26px">TikTok Trends</h2>
<div style="color:#888;font-size:13px;margin-bottom:20px">
  Les meilleures vidéos des comptes suivis, classées par performance.
  Passe par Apify — aucun cookie, aucun compte de l'agence exposé.
</div>
{alerte}

<div style="background:#161616;border:1px solid #2a2a2a;border-radius:12px;
            padding:16px;margin-bottom:20px">
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
    <div style="flex:1;min-width:260px">
      <label style="display:block;font-size:11px;color:#888;font-weight:600;
                    text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
        Comptes TikTok</label>
      <input id="tk-comptes" placeholder="@concurrent1, @concurrent2, ou une URL"
             style="width:100%;background:#0f0f0f;border:1px solid #2a2a2a;
                    color:#fff;border-radius:8px;padding:9px 12px;font-size:13px">
    </div>
    <div style="width:130px">
      <label style="display:block;font-size:11px;color:#888;font-weight:600;
                    text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
        Top par compte</label>
      <input id="tk-nb" type="number" min="1" max="200" value="30"
             oninput="tkPrix()"
             style="width:100%;background:#0f0f0f;border:1px solid #2a2a2a;
                    color:#fff;border-radius:8px;padding:9px 12px;font-size:13px">
    </div>
    <button id="tk-go" onclick="tkCollecter()"
            style="padding:10px 20px;background:#3b82f6;color:#fff;border:0;
                   border-radius:8px;cursor:pointer;font-size:13px;font-weight:700">
      Collecter</button>
  </div>
  <label style="display:flex;align-items:center;gap:8px;margin-top:12px;
                font-size:12px;color:#aaa;cursor:pointer">
    <input type="checkbox" id="tk-video" onchange="tkPrix()">
    Télécharger les vidéos, pour que l'équipe les regarde depuis le site
    <span style="color:#666">(option Apify facturée en plus)</span>
  </label>
  <div id="tk-prix" style="margin-top:10px;font-size:12px;color:#888"></div>
  <div id="tk-etat" style="margin-top:8px;font-size:12px"></div>
</div>

<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">{boutons}</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">{puces}</div>

<div style="display:grid;gap:14px;
            grid-template-columns:repeat(auto-fill,minmax(210px,1fr))">{grille}</div>

<script>
function tkPrix(){{
  var n = parseInt(document.getElementById('tk-nb').value || '0', 10) || 0;
  var c = (document.getElementById('tk-comptes').value || '')
            .split(/[\\s,;]+/).filter(function(x){{return x.trim();}}).length;
  var d = document.getElementById('tk-prix');
  if(!c || !n){{ d.textContent = ''; return; }}
  var usd = (c * n * {PRIX_RESULTAT}).toFixed(2);
  d.innerHTML = 'Environ <b style="color:#ddd">' + (c*n) + ' résultats</b>, soit '
              + '<b style="color:#ddd">~' + usd + ' $</b> de crédit Apify'
              + (document.getElementById('tk-video').checked
                 ? ', plus l\\'option téléchargement.' : '.');
}}
document.getElementById('tk-comptes').addEventListener('input', tkPrix);

function tkCollecter(){{
  var btn = document.getElementById('tk-go');
  var etat = document.getElementById('tk-etat');
  var comptes = document.getElementById('tk-comptes').value || '';
  if(!comptes.trim()){{ etat.innerHTML = '<span style="color:#e0576b">Indique au moins un compte.</span>'; return; }}
  btn.disabled = true; btn.textContent = 'Collecte...';
  etat.innerHTML = '<span style="color:#888">Apify travaille — compte une minute par compte.</span>';
  fetch('/tiktok/collect', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      comptes: comptes,
      par_compte: parseInt(document.getElementById('tk-nb').value || '30', 10),
      avec_video: document.getElementById('tk-video').checked
    }})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    btn.disabled = false; btn.textContent = 'Collecter';
    if(!d.ok){{ etat.innerHTML = '<span style="color:#e0576b">' + (d.error||'echec') + '</span>'; return; }}
    etat.innerHTML = '<span style="color:#43b581">' + d.message + '</span>';
    tkRafraichir();
  }}).catch(function(err){{
    btn.disabled = false; btn.textContent = 'Collecter';
    etat.innerHTML = '<span style="color:#e0576b">' + err + '</span>';
  }});
}}

function tkTri(t){{ tkRafraichir(t); }}

function tkRafraichir(t){{
  var url = '/tiktok/render' + (t ? ('?tri=' + encodeURIComponent(t)) : '');
  fetch(url).then(function(r){{ return r.text(); }}).then(function(h){{
    var c = document.getElementById('form-tktrends');
    if(c) c.innerHTML = h;
  }});
}}

function tkOublier(compte){{
  if(!confirm('Retirer @' + compte + ' et toutes ses vidéos du classement ?')) return;
  fetch('/tiktok/forget', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{compte: compte}})
  }}).then(function(){{ tkRafraichir(); }});
}}

tkPrix();
</script>
"""


# ----------------------------------------------------------------- routes --

def register(app, is_auth):
    from flask import jsonify, request, send_file

    @app.route("/tiktok/render", methods=["GET"])
    def tiktok_render():
        if not is_auth():
            return "", 401
        try:
            return rendu_html(request.args.get("tri") or "vues")
        except Exception as e:
            return (f"<div style='color:#f99;padding:14px'>Erreur rendu TikTok : "
                    f"{type(e).__name__}: {e}</div>"), 500

    @app.route("/tiktok/collect", methods=["POST"])
    def tiktok_collect():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        d = request.get_json(silent=True) or {}
        comptes = _comptes_saisis(d.get("comptes"))
        if not comptes:
            return jsonify({"ok": False, "error": "Aucun compte lisible"}), 400
        try:
            par_compte = max(1, min(200, int(d.get("par_compte") or 30)))
        except (TypeError, ValueError):
            par_compte = 30
        avec_video = bool(d.get("avec_video"))

        diag: Dict[str, Any] = {}
        fiches, err = vtk.collecter(comptes, par_compte=par_compte,
                                    tri="popular", avec_video=avec_video,
                                    diag=diag)
        if err and not fiches:
            return jsonify({"ok": False, "error": err, "diag": diag}), 502

        neuf, maj = vtk.enregistrer(fiches)
        msg = f"{len(fiches)} vidéos ({neuf} nouvelles, {maj} mises à jour)"
        if avec_video:
            ok, rate = vtk.rapatrier(fiches)
            msg += f", {ok} vidéos téléchargées"
            if rate:
                msg += f", {rate} échecs"
        return jsonify({"ok": True, "message": msg, "diag": diag})

    @app.route("/tiktok/forget", methods=["POST"])
    def tiktok_forget():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        d = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "retirees": vtk.oublier_compte(d.get("compte"))})

    @app.route("/tiktok/video/<vid>", methods=["GET"])
    def tiktok_video(vid):
        if not is_auth():
            return "", 401
        # L'identifiant vient de l'URL : sans ce filtre, un « ../../ » sortirait
        # du dossier des vidéos et servirait n'importe quel fichier du disque.
        if not _ID_OK.match(str(vid or "")):
            return "", 404
        p = vtk.chemin_video(vid)
        if not p.exists():
            return "", 404
        return send_file(str(p), mimetype="video/mp4", conditional=True)
