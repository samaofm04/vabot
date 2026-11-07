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
check("le bouton « Ouvrir la vérification » prend le domaine du serveur",
      '"url": f"{domaines.site(gid)}/verif/{jeton}"' in _src and '"url": f"{SITE}/verif/' not in _src)

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

_wu = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
check("web_upload installe la garde", "domaines.installer(app)" in _wu)

print()
print(f"{len(OK)} OK, {len(KO)} échec(s)")
for n in KO:
    print("  ❌", n)
sys.exit(1 if KO else 0)
