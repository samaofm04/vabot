"""tests_domaines.py — trust-ofm.com pour les VA de TRUST, youl4b.com pour le reste.

Propriétaire, 07/11/2026 : les pages que voient les VA de TRUST TWITTER,
INSTAGRAM et THREADS (stats, affiliation, vérification) passent sur
trust-ofm.com. Vérifie :
  1. la table : quel serveur reçoit quel domaine ;
  2. les liens du bot : page perso, vérification ; /trust/liens (lien des
     managers) sur trust-ofm.com depuis le 08/11, toujours ouvert sur youl4b.com ;
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
                                       "/affiliation/affiche.png", "/static/x/y.png", "/favicon.svg",
                                       "/trust/liens"))
      and not any(dm.chemin_trust(c) for c in ("/", "/login", "/trust/liensX", "/trust/liens/x",
                                               "/trust", "/trust/", "/affiliations",
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
check("/trust/liens : le lien des managers sur trust-ofm.com",
      st.lien().startswith("https://trust-ofm.com/trust/liens?k="), st.lien())

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
# les filleuls en carrés, aux trois formats des panneaux
def _prog(v):
    return f"<section><h2>📊 Progression du filleul</h2><p>{v}</p></section>"
_COMPTE = "<section><h2>👥 Tes filleuls</h2><p>3 filleul(s) enregistré(s).</p></section>"
_AG = _AFF.replace("</section><style>", "</section>" + _COMPTE
                   + _prog("@lea — ✅ Vérifié<br>0 vrais subs · Objectif 10 : 0 % · Objectif 200 : 0 %")
                   + _prog("@sam — ✅ Vérifié<br>60 vrais subs · Objectif 10 : 100 % · Objectif 200 : 30 %")
                   + _prog("@zoe — ⏳ Pas encore vérifié<br>Pas encore de lien de suivi : ses subs compteront dès sa création.")
                   + "<style>", 1)
_h = ht.affiliation(_AG, "agency")
check("filleuls TRUST INSTAGRAM : une carte « Tes filleuls · 3 », plus de rubrique par filleul",
      "👥 Tes filleuls · 3" in _h and "Progression du filleul" not in _h and _h.count('class="fil"') == 3
      and "filleul(s) enregistré(s)" not in _h)
check("60 subs : objectif 10 vert (100 % ✓), objectif 200 à 3 carrés sur 10 (30 %)",
      '<span class="nb">60 subs</span>' in _h and '<div class="pal ok"><span class="lib">Objectif 10</span>' in _h
      and "100 % ✓" in _h and ">30 %</span>" in _h)
_sam = _h.split("@sam")[1].split('class="fil"')[0]
check("… soit exactement 10 + 3 carrés pleins pour @sam", _sam.count('<i class="on">') == 13
      and _sam.count("<i") == 20, _sam.count('<i class="on">'))
check("un filleul sans subs lisibles garde son texte, sans carrés",
      "Pas encore de lien de suivi" in _h.split("@zoe")[1].split("</section>")[0]
      and "<i" not in _h.split("@zoe")[1].split("</section>")[0])
check("15 subs sur 200 : le premier carré se remplit aux trois quarts (7,5 %)",
      "var(--acc) 75%" in ht._cases(15, 200, "Objectif 200") and ">7,5 %<" in ht._cases(15, 200, "Objectif 200"))
_TW = _AFF.replace("VA AGENCY", "VA TWITTER").replace("</section><style>", "</section>"
      + _COMPTE.replace("3 filleul", "1 filleul")
      + _prog("@max<br>12 vrais subs · Objectif 10 : 100 % · Objectif 200 : 6 %") + "<style>", 1)
_h = ht.affiliation(_TW, "twitter")
check("filleuls TRUST TWITTER (sans état) : carte et carrés",
      "👥 Tes filleuls · 1" in _h and '<b>@max</b><span class="nb">12 subs</span>' in _h)
_TH = _AFF.replace("VA AGENCY", "VA THREADS").replace("</section><style>", "</section>"
      "<section><h2>👥 Tes filleuls · 2</h2><p>@ana — ✅ Vérifié<br>🎯 10 : 60/10 subs · 100 % ▰▰▰▰▰▰▰▰▰▰ ✅"
      "<br>🏆 200 : 60/200 subs · 30 % ▰▰▰▱▱▱▱▱▱▱<br><br>@bob — 👋 Arrivé, non vérifié<br>"
      "Subs et progression indisponibles : suivi MyPuls en attente.</p></section><style>", 1)
_h = ht.affiliation(_TH, "threads")
check("filleuls TRUST THREADS : les deux lus, ▰▱ remplacés par les carrés",
      "👥 Tes filleuls · 2" in _h and '<span class="nb">60 subs</span>' in _h and "▰" not in _h
      and "suivi MyPuls en attente" in _h and _h.count('class="fil"') == 2)
check("Threads sans filleul : la rubrique reste telle quelle",
      ht.filleuls("<section><h2>👥 Tes filleuls · 0</h2><p>Aucun filleul.</p></section>", "threads")
      == "<section><h2>👥 Tes filleuls · 0</h2><p>Aucun filleul.</p></section>")
# la carte des invitations du serveur de recrutement, sur un faux
# entretien_parrainage (hors git sur le VPS)
import datetime as _dt  # noqa: E402
import threading as _th  # noqa: E402
import types as _types  # noqa: E402
_ep = _types.ModuleType("entretien_parrainage")
_ep.LOCK, _ep.TZ, _ep.PRIX_CENTIMES = _th.RLock(), _dt.timezone.utc, 20
_ep.euros = lambda c: f"{c // 100},{c % 100:02d} $"
_ep.semaine = lambda now: (now.date() - _dt.timedelta(days=now.weekday())).isoformat()
_ep.lire = lambda: {"liens": {"77": {"code": "AbC123"}},
                    "declarations": {"a": {"parrain": "77", "semaine": "2026-11-02", "centimes": 20},
                                     "b": {"parrain": "77", "semaine": "2026-11-02", "centimes": 20},
                                     "c": {"parrain": "77", "semaine": "2026-10-26", "centimes": 15},
                                     "d": {"parrain": "88", "semaine": "2026-11-02", "centimes": 20}},
                    "en_attente": {"x": {"parrain": "77"}}}
sys.modules["entretien_parrainage"] = _ep
_d = ht.recrutement("77", _dt.datetime(2026, 11, 7, 22, 0, tzinfo=_dt.timezone.utc))
check("recrutement : semaine (2 · 0,40 $), total (3 · 0,55 $), 1 en attente, lien existant",
      _d["semaine"] == (2, "0,40 $") and _d["total"] == (3, "0,55 $") and _d["attente"] == 1
      and _d["lien"] == "https://discord.gg/AbC123" and (_d["du"], _d["au"]) == ("02/11", "08/11"), _d)
_c = ht.carte_recrutement(_d)
check("carte recrutement : 0,20 $ par personne, les deux tuiles, le bouton « Copier »",
      "🎙️ Recrutement · TRUST Agency" in _c and "<b>0,20 $</b>" in _c and "Cette semaine · du 02/11 au 08/11" in _c
      and 'class="copier-lien" data-lien="https://discord.gg/AbC123"' in _c and "0,55 $" in _c)
check("sans lien : la carte le dit, sans en créer (lecture seule)",
      "t'attend sur le serveur de recrutement" in ht.carte_recrutement(ht.recrutement("99"))
      and "data-lien" not in ht.carte_recrutement(ht.recrutement("99")))
check("la carte s'ajoute avant le pied de page de l'espace d'affiliation",
      ht.affiliation(_AFF, "agency", "77").index("Recrutement · TRUST Agency")
      < ht.affiliation(_AFF, "agency", "77").index("<footer>"))
del sys.modules["entretien_parrainage"]
check("pas de phrase « par plateforme » ni « une seule prime » (propriétaire : « ça fait trop »)",
      "par plateforme" not in ht.affiliation(_AFF, "agency") and not hasattr(ht, "NOTE_PRIMES"))
# la règle des primes (journal_primes) : un faux registre, de faux subs
import journal_primes as _jp  # noqa: E402
_sauve = {k: getattr(_jp, k) for k in ("registre", "compteurs", "subs", "pseudo")}
_REG = {"threads": {"filleuls": {"21": {"parrain": "7", "verified": True}, "22": {"parrain": "7"}}},
        "twitter": {"filleuls": {"21": {"parrain": "8", "verified": True}, "23": {"parrain": "7", "verified": True}}},
        "agency": {"filleuls": {}, "membres": {"23": {"nom": "zoe"}}}}
_SUBS = {("threads", "21"): 21, ("twitter", "21"): 300, ("twitter", "23"): 12}
_jp.registre = lambda p: _REG.get(p)
_jp.compteurs = lambda: {}
_jp.subs = lambda p, u, m: _SUBS.get((p, u))
_jp.pseudo = lambda u, noms: noms.setdefault(u, {"21": "fiable", "22": "sympa"}.get(u, ""))
_L = ht.lignes_filleuls("threads", "7")
check("règle des primes : la meilleure plateforme compte (300 subs · Twitter, pas 21 sur Threads)",
      len(_L) == 2 and "300 subs · Twitter" in _L[0] and "@fiable" in _L[0], _L)
check("prime chez un autre parrain : c'est dit", "Sa prime va à son parrain sur Twitter." in _L[0])
check("subs de Lia inconnus : aucun carré, la phrase", ht.INCONNU_LIA in _L[1] and "<i" not in _L[1] and "@sympa" in _L[1])
_L = ht.lignes_filleuls("twitter", "7")
check("filleul Twitter, nom lu au registre d'Agency, sa prime chez son parrain",
      len(_L) == 1 and "@zoe" in _L[0] and "12 subs · Twitter" in _L[0] and "Sa prime va" not in _L[0], _L)
check("sans filleul : la page garde le texte du panneau", ht.lignes_filleuls("agency", "7") == [])
_h = ht.affiliation(_AFF.replace("VA AGENCY", "VA THREADS").replace("</section><style>", "</section>"
     "<section><h2>🎯 Objectifs par filleul</h2><p>10 subs → 0,50 $<br>" + ht.ANCIENNE_REGLE_THREADS + "</p></section>"
     "<section><h2>👥 Tes filleuls · 0</h2><p>Aucun filleul pour le moment.</p></section><style>", 1), "threads", "7")
check("page Threads : la carte des filleuls vient de la règle, la phrase « tous les trackings » remplacée",
      "👥 Tes filleuls · 2" in _h and "300 subs · Twitter" in _h and ht.REGLE_PRIMES in _h
      and ht.ANCIENNE_REGLE_THREADS not in _h and "Aucun filleul pour le moment" not in _h)
for _k, _v in _sauve.items():
    setattr(_jp, _k, _v)
check("hors VPS : pas de carte recrutement", ht.carte_recrutement(ht.recrutement("77")) == ""
      and "Recrutement" not in ht.affiliation(_AFF, "agency", "77"))
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
    check(f"{hote}/trust/liens : la vue répond (elle vérifie la clé)",
          get("/trust/liens?k=x", hote) == (200, "VUE"))
    check(f"{hote}/trust/liens/… et /trust : neutres",
          get("/trust/liens/x", hote)[0] == 404 and get("/trust", hote)[0] == 404)
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
_vrai = ht.qui_affiliation
ht.qui_affiliation = lambda t: {"a": ("agency", "11"), "i": ("instagram", "12")}.get(t)
c2 = app2.test_client()
check("espace d'affiliation d'un VA TRUST INSTAGRAM : habillé à la sortie",
      "TRUST INSTAGRAM" in c2.get("/affiliation/mon-espace?t=a").get_data(as_text=True))
check("Va IG (instagram), lien inconnu, autre page : inchangés",
      c2.get("/affiliation/mon-espace?t=i").get_data(as_text=True) == _AFF
      and c2.get("/affiliation/mon-espace?t=zz").get_data(as_text=True) == _AFF
      and c2.get("/autre?t=a").get_data(as_text=True) == _AFF)
ht.qui_affiliation = _vrai
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
