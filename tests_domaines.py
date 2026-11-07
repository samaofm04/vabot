"""tests_domaines.py — trust-ofm.com pour les VA de TRUST, youl4b.com pour le reste.

Propriétaire, 07/11/2026 : les pages que voient les VA de TRUST TWITTER,
INSTAGRAM et THREADS (stats, affiliation, vérification) passent sur
trust-ofm.com. Vérifie :
  1. la table : quel serveur reçoit quel domaine ;
  2. les liens du bot : page perso, vérification ; /trust/liens reste ;
  3. la garde de trust-ofm.com, par le client de test Flask : les pages des
     VA y répondent, le reste rend une page neutre ; youl4b.com ne change pas.

    python tests_domaines.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import domaines as dm  # noqa: E402

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  ✅ " if cond else "  ❌ ") + nom + ("" if cond else f"  → {str(detail)[:300]}"))


TW, IG, TH = "1445108485090971710", "1488331963575177247", "1498948161039896586"
VA_IG, AUTRE = "1505418484052394004", "1234567890123456789"

print("1. La table")
check("les trois serveurs TRUST", dm.SERVEURS_TRUST == {TW, IG, TH}, dm.SERVEURS_TRUST)
check("TRUST TWITTER, INSTAGRAM, THREADS → trust-ofm.com",
      all(dm.site(g) == "https://trust-ofm.com" for g in (TW, IG, TH)))
check("un id en nombre vaut le même id en texte", dm.site(int(TW)) == "https://trust-ofm.com")
check("Va IG, un autre serveur, aucun (l'Entretien) → youl4b.com",
      all(dm.site(g) == "https://youl4b.com" for g in (VA_IG, AUTRE, "", None)))
check("hôte trust-ofm.com reconnu (www, port, casse)",
      dm.hote_trust("trust-ofm.com") and dm.hote_trust("WWW.Trust-OFM.com:443")
      and not dm.hote_trust("youl4b.com") and not dm.hote_trust("trust-ofm.com.evil.io")
      and not dm.hote_trust(""))
check("chemins des VA servis, le reste non",
      all(dm.chemin_trust(c) for c in ("/mes-stats", "/verif/abc", "/affiliation/mon-espace",
                                       "/affiliation/affiche.png", "/static/x/y.png", "/favicon.svg"))
      and not any(dm.chemin_trust(c) for c in ("/", "/login", "/trust/liens", "/affiliations",
                                               "/subs", "/mes-statsX", "/verif", "/settings/role/add",
                                               "/interactions", "/version", "/affiliation/mon-espaceX")))

print("2. Les liens du bot")
_tmp = Path(tempfile.mkdtemp())
import stats_va as sv  # noqa: E402
import stats_trust as st  # noqa: E402
sv.CLES_FICHIER = _tmp / "stats_va_cles.json"
st.CLE_FICHIER = _tmp / "stats_trust_cle.json"
U = "111111111111111111"
for g in (TW, IG, TH):
    check(f"page perso {g[-4:]} sur trust-ofm.com",
          sv.lien(g, U) == f"https://trust-ofm.com/mes-stats?t={sv.jeton(g, U)}", sv.lien(g, U))
check("hors TRUST, pas de page perso (inchangé)", sv.lien(VA_IG, U) == "")
check("/trust/liens (direction) reste sur youl4b.com",
      st.lien().startswith("https://youl4b.com/trust/liens?k="), st.lien())

import verif_discord as vd  # noqa: E402
check("images des embeds : verif_discord.SITE reste youl4b.com", vd.SITE == "https://youl4b.com")
_src = Path(vd.__file__).read_text(encoding="utf-8")
check("la vérification reste sur youl4b.com (identifiant d'appareil propre au domaine)",
      '"url": f"{SITE}/verif/{jeton}"' in _src and "domaines.site(gid)}/verif/" not in _src)

print("2 bis. Les pages au nom TRUST")
# le texte dessiné pour l'empreinte : le changer rendrait les empreintes
# d'avant incomparables à celles d'après
_canvas = "g.fillText('YouLab verif \\u2728 123'"
for g, marque in ((TW, "TRUST"), (TH, "TRUST"), (vd.GUILD_ID, "TRUST Agency"), (VA_IG, "YouLab")):
    h = vd.page_html(g)
    check(f"vérification {g[-4:]} : « Vérification {marque} », rien d'autre ne change",
          f"<title>Vérification {marque}</title>" in h and f"<h1>🔐 Vérification {marque}</h1>" in h
          and f"l'équipe {marque} seulement" in h and "__" not in h.split("<script>")[0]
          and h.count(_canvas) == 2 and (("data:image/svg+xml" in h) == (marque != "YouLab")), marque)
check("réponse de la vérification au nom TRUST (serveur TRUST), YouLab ailleurs",
      vd.en_trust({"message": "Tu n'es plus sur le serveur YouLab."}, vd.table_marque(TW))["message"]
      == "Tu n'es plus sur le serveur TRUST." and vd.table_marque(VA_IG) is None)
check("page « Tes stats » : icône TRUST dans l'onglet", dm.ICONE_LIEN in sv.page_introuvable())

import habillage_trust as ht  # noqa: E402
_AFF = ('<!doctype html><html lang="fr"><meta charset="utf-8"><title>Mon affiliation · YouL4b</title>'
        '<style>:root{color-scheme:dark}/* Thème Mario : décor */body{background:#69ceff}</style>'
        '<main><small>YOUL4B · VA AGENCY</small><h1>Mon espace affiliation</h1><p>Ton lien.</p>'
        '<figure class="aff-poster"><img src="/affiliation/affiche.png"></figure>'
        '<section><h2>🔗 Ton lien personnel · Agency</h2><p><a href="https://discord.gg/abc">x</a></p>'
        '<button type="button" class="copier-lien" data-lien="https://discord.gg/abc">📋 Copier le lien</button></section>'
        '<section><h2>🤝 Ton parrain</h2><p>Aucun parrain enregistré pour Agency.</p></section>'
        '<style>.copier-lien{cursor:pointer}</style><script>document.addEventListener("click",function(){})</script>'
        '<footer>Cette page est personnelle.</footer></main></html>')
_h = ht.affiliation(_AFF, "agency")
check("affiliation TRUST INSTAGRAM : titre, bandeau, thème « Tes stats »",
      "<title>Mon affiliation · TRUST</title>" in _h and '<div class="marque">TRUST INSTAGRAM</div>' in _h
      and "--acc:#f97341" in _h and "Mario" not in _h and "#69ceff" not in _h, _h[:300])
check("affiliation : plus de YouL4b, l'affiche Mario retirée, « Agency » → « Instagram »",
      not re.search(r"(?i)youl[a4]b", _h) and "aff-poster" not in _h and " Agency" not in _h
      and "Ton lien personnel · Instagram" in _h and "pour Instagram." in _h)
check("affiliation : le bouton « Copier » et son script restent",
      'class="copier-lien"' in _h and "addEventListener" in _h and ".copier-lien{cursor:pointer}" in _h)
check("bouton « Copier » plus spécifique que la règle de la page", "section .copier-lien{" in ht.STYLE)
for p, b in (("threads", "TRUST THREADS"), ("twitter", "TRUST TWITTER")):
    check(f"affiliation {p} : bandeau {b}",
          f'<div class="marque">{b}</div>' in ht.affiliation(_AFF.replace("VA AGENCY", "VA " + p.upper()), p))

print("3. La garde, par le client de test Flask")
from flask import Flask  # noqa: E402

app = Flask(__name__, static_folder=None)   # /static/ est une vue du test
dm.installer(app)
for chemin in ("/", "/mes-stats", "/verif/<j>", "/affiliation/mon-espace", "/trust/liens", "/static/<path:p>"):
    app.add_url_rule(chemin, chemin, (lambda **kw: "VUE"), methods=["GET", "POST"])
c = app.test_client()


def get(chemin, hote, **kw):
    r = c.open(chemin, headers={"Host": hote}, **kw)
    return r.status_code, r.get_data(as_text=True)


for hote in ("trust-ofm.com", "www.trust-ofm.com"):
    check(f"{hote}/ : page neutre en 404, pas la connexion",
          get("/", hote) == (404, dm.PAGE_NEUTRE), get("/", hote)[0])
    check(f"{hote}/trust/liens : neutre (direction sur youl4b.com seulement)",
          get("/trust/liens?k=x", hote)[0] == 404)
    check(f"{hote}/mes-stats?t= : la vue répond", get("/mes-stats?t=abc", hote) == (200, "VUE"))
    check(f"{hote}/verif/<j> en GET et en POST", get("/verif/j", hote) == (200, "VUE")
          and get("/verif/j", hote, method="POST", json={}) == (200, "VUE"))
    check(f"{hote}/affiliation/mon-espace", get("/affiliation/mon-espace?t=a", hote) == (200, "VUE"))
    check(f"{hote}/static/…", get("/static/a.png", hote) == (200, "VUE"))
r = c.get("/", headers={"Host": "trust-ofm.com"})
check("page neutre : ni cache ni moteur de recherche",
      r.headers.get("Cache-Control") == "no-store" and "noindex" in r.headers.get("X-Robots-Tag", ""))
for hote in ("youl4b.com", "127.0.0.1:5000", "localhost"):
    check(f"{hote} : rien ne change ('/', /trust/liens, /mes-stats)",
          get("/", hote) == (200, "VUE") and get("/trust/liens", hote) == (200, "VUE")
          and get("/mes-stats?t=a", hote) == (200, "VUE"))

r = c.get("/favicon.svg", headers={"Host": "trust-ofm.com"})
check("trust-ofm.com/favicon.svg : l'icône TRUST", r.status_code == 200 and r.mimetype == "image/svg+xml"
      and b"TRUST" in r.data and c.get("/favicon.ico", headers={"Host": "trust-ofm.com"}).data == r.data)
check("youl4b.com/favicon.svg : pas touché (la vue du site)",
      c.get("/favicon.svg", headers={"Host": "youl4b.com"}).status_code == 404)

app2 = Flask(__name__ + "2", static_folder=None)
app2.add_url_rule("/affiliation/mon-espace", "aff", lambda: _AFF)
app2.add_url_rule("/autre", "autre", lambda: _AFF)
ht.installer(app2)
_vrai = ht.plateforme_affiliation
ht.plateforme_affiliation = lambda t: {"a": "agency", "i": "instagram"}.get(t)
c2 = app2.test_client()
check("espace d'affiliation d'un VA TRUST INSTAGRAM : habillé à la sortie",
      "TRUST INSTAGRAM" in c2.get("/affiliation/mon-espace?t=a").get_data(as_text=True))
check("Va IG (instagram), lien inconnu, autre page : inchangés",
      c2.get("/affiliation/mon-espace?t=i").get_data(as_text=True) == _AFF
      and c2.get("/affiliation/mon-espace?t=zz").get_data(as_text=True) == _AFF
      and c2.get("/autre?t=a").get_data(as_text=True) == _AFF)
ht.plateforme_affiliation = _vrai
check("lien d'affiliation inconnu : aucune plateforme, rien d'habillé",
      ht.plateforme_affiliation("x") is None)

_wu = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
check("web_upload installe la garde et l'habillage",
      "domaines.installer(app)" in _wu and "habillage_trust.installer(app)" in _wu)
check("web_upload : la page de vérification au nom du serveur du lien",
      '_vd.page_html(_info.get("guild_id"))' in _wu and "_vd.PAGE_HTML" not in _wu)

print()
print(f"{len(OK)} OK, {len(KO)} échec(s)")
for n in KO:
    print("  ❌", n)
sys.exit(1 if KO else 0)
