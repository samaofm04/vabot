"""tests_photos_profil.py — banc d'essai de la page « Photos de profil » (/pfp).

Lancer :  python tests_photos_profil.py

Hors réseau : Yandex, Bing et les téléchargements sont remplacés par des
doublures, et tout s'écrit dans un dossier TEMPORAIRE (data/ n'est pas touché).
Le rendu de la page passe par le vrai create_app() et son script par
`node --check` : le JavaScript vit dans une chaîne Python.
"""
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

os.environ["VABOT_BANC_ESSAI"] = "1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np

import photos_profil as pp

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  — {detail}"))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_pfp_"))
pp.RACINE = TMP
pp.STYLES_FILE = TMP / "styles.json"


def _png(couleur=(200, 30, 90), taille=(300, 300), fmt="PNG"):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", taille, couleur).save(b, fmt)
    return b.getvalue()


print("1) Clés et adresses")
a = "https://i.pinimg.com/originals/ca/de/65/cade65ebcf7df92efe6d7ea9067da84d.jpg"
b = "https://i.pinimg.com/236x/ca/de/65/cade65ebcf7df92efe6d7ea9067da84d.jpg?nii=t"
check("même épingle, tailles différentes : même clé", pp.cle_image([a]) == pp.cle_image([b]),
      f"{pp.cle_image([a])} / {pp.cle_image([b])}")
check("clé hors Pinterest : stable et valide",
      pp.cle_image(["https://x.com/a.jpg"]) == pp.cle_image(["https://x.com/a.jpg"])
      and pp._CLE.match(pp.cle_image(["https://x.com/a.jpg"])) is not None)
urls = pp._trier_urls([("https://i.pinimg.com/736x/ca/de/65/cade65ebcf7df92efe6d7ea9067da84d.jpg", 736, 736),
                       ("https://avatars.akamai.steamstatic.com/x_medium.jpg", 64, 64),
                       (a, 1024, 1024)])
check("originals en premier, avatar 64 px écarté", urls[0] == a and len(urls) == 2, f"{urls}")
check("adresse interne refusée (127.0.0.1)", not pp._url_publique("http://127.0.0.1:5000/settings"))
check("adresse interne refusée (10.x)", not pp._url_publique("http://10.0.0.5/x.jpg"))
check("schéma file:// refusé", not pp._url_publique("file:///etc/passwd"))
check("adresse publique littérale acceptée", pp._url_publique("https://1.1.1.1/x.jpg"))

print("2) Lecture des résultats Yandex et Bing")
ent = {"origUrl": "https://i.pinimg.com/736x/ca/de/65/cade65ebcf7df92efe6d7ea9067da84d.jpg",
       "origWidth": 736, "origHeight": 736, "image": "//avatars.mds.yandex.net/i?id=1&n=13",
       "snippet": {"title": "<b>Anime</b> pfp", "url": "https://www.pinterest.com/pin/123/"},
       "viewerData": {"thumb": {"url": "//avatars.mds.yandex.net/i?id=1&n=13"},
                      "dups": [{"url": a, "w": 1024, "h": 1024}]}}
c = pp.depuis_yandex(ent)
check("Yandex : original Pinterest choisi", c and c["img"] == a, f"{c}")
check("Yandex : vignette en https, titre sans balise",
      c and c["vign"].startswith("https://") and c["titre"] == "Anime pfp", f"{c}")
cb = pp.depuis_bing({"murl": "https://i.pinimg.com/originals/aa/bb/cc/aabbcc00000000000000000000000000.png",
                     "turl": "https://ts1.mm.bing.net/th?id=OIP.x", "purl": "https://pinterest.com/pin/1", "t": "t"})
check("Bing : candidate lue", cb and cb["cle"] == "paabbcc00000000000000000000000000", f"{cb}")
etat = pp._etat_yandex('<div data-state="' + '{&quot;initialState&quot;:{&quot;serpList&quot;:{}}}' + '"></div>', "")
check("Yandex : état de page décodé", etat == {"serpList": {}}, f"{etat}")
try:
    pp._etat_yandex("<html>captcha</html>", "https://yandex.com/showcaptcha?x")
    check("Yandex : captcha signalé", False, "aucune erreur levée")
except pp.ErreurSource as e:
    check("Yandex : captcha signalé", "anti-robot" in str(e), str(e))

check("banque d'images (filigrane) reconnue", pp._banque({"img": "https://cdn.vectorstock.com/i/x.jpg"})
      and pp._banque({"page": "https://www.alamy.com/stock-photo-x.html"})
      and not pp._banque({"img": a, "page": "https://www.pinterest.com/pin/1/"}))

print("3) Avis, téléchargement, corbeille")
pp._TELECHARGEMENTS = type("Sync", (), {"submit": staticmethod(lambda f, *a: f(*a))})()
sid = pp.styles()[0]["id"]
img = _png()
orig_dl = pp._telecharger
pp._telecharger = lambda u, *a, **k: img if "bon" in u else None
r = pp.juger(sid, "pbon1", "ok", {"img": "https://exemple.org/bon.jpg", "vign": "https://exemple.org/v.jpg",
                                  "alt": [], "page": "", "titre": "x", "src": "yandex"})
g = pp.gardees(sid)
check("OK : original téléchargé dans garde/", r["ok"] and g and g[0]["fichier"] == "pbon1.png"
      and (TMP / sid / "garde" / "pbon1.png").is_file(), f"{r} {g}")
r = pp.juger(sid, "pmauvais", "ok", {"img": "https://exemple.org/mort.jpg", "vign": "https://exemple.org/mort2.jpg"})
g = {x["cle"]: x for x in pp.gardees(sid)}
check("OK sans original joignable : échec dit, pas caché", g["pmauvais"]["echec"] != "", f"{g['pmauvais']}")
pp.juger(sid, "pbon1", "annuler", {})
check("annuler : le fichier part à la corbeille, jamais effacé",
      not (TMP / sid / "garde" / "pbon1.png").exists()
      and any((TMP / sid / "corbeille").glob("*_pbon1.png")))
r = pp.juger(sid, "pbon2", "non", {"img": "https://exemple.org/bon.jpg"})
check("Non enregistré sans téléchargement", r["ok"] and not (TMP / sid / "garde" / "pbon2.png").exists())
check("verdict inconnu refusé", not pp.juger(sid, "pbon3", "peut-etre", {"img": "https://e.org/bon.jpg"})["ok"])
check("clé invalide refusée", not pp.juger(sid, "../x", "ok", {"img": "https://e.org/bon.jpg"})["ok"])
check("style inconnu refusé", not pp.juger("deadbeef", "pbon4", "ok", {"img": "https://e.org/bon.jpg"})["ok"])
check("fichier hors garde/ refusé", pp.chemin_fichier(sid, "../styles.json") is None)
r = pp.ajouter_exemples(sid, [("moi.webp", _png(fmt="WEBP")), ("pas-une-image.txt", b"bonjour")])
check("exemples : image acceptée (WebP -> PNG), texte refusé et nommé",
      r["ok"] and r["ajoutes"] == 1 and r["refuses"] == ["pas-une-image.txt"], f"{r}")
pp._telecharger = orig_dl

print("4) Classement")
rng = np.random.default_rng(1)


def _unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


base_ok, base_non = _unit(rng.normal(size=512)), _unit(rng.normal(size=512))
sid2 = pp.creer_style("Classement")["id"]
avis = {}
for i in range(3):
    avis[f"pok{i}"] = {"v": "ok", "t": i, "vec": pp._vec_vers_txt(_unit(base_ok + 0.3 * rng.normal(size=512) / 22))}
    avis[f"pnon{i}"] = {"v": "non", "t": i, "vec": pp._vec_vers_txt(_unit(base_non + 0.3 * rng.normal(size=512) / 22))}
pp._enregistrer_avis(sid2, avis)
cands = [{"cle": "cproche_non", "vign": "v"}, {"cle": "cmilieu", "vign": "v"}, {"cle": "cproche_ok", "vign": "v"},
         {"cle": "cdoublon", "vign": "v"}, {"cle": "pok0", "vign": "v"}]
vecs = {"cproche_non": _unit(base_non + rng.normal(size=512) / 90),
        "cmilieu": _unit(base_ok + base_non),
        "cproche_ok": _unit(base_ok + rng.normal(size=512) / 90),
        "cdoublon": pp._txt_vers_vec(avis["pok1"]["vec"])}
orig_vc, orig_pret = pp._vecteurs_candidates, pp._pret
pp._vecteurs_candidates = lambda cs: {c["cle"]: vecs[c["cle"]] for c in cs if c["cle"] in vecs}
pp._pret = lambda: True
r = pp._classer(sid2, cands, [], False, "t")
ordre = [c["cle"] for c in r["images"]]
check("le plus proche des OK passe en premier", ordre and ordre[0] == "cproche_ok", f"{ordre}")
check("proche des Non : mis de côté, pas supprimé", [c["cle"] for c in r["ecartees"]] == ["cproche_non"], f"{r['ecartees']}")
check("déjà jugée : masquée et comptée", r["deja_jugees"] == 1, f"{r['deja_jugees']}")
check("même image qu'un OK : doublon compté", r["doublons"] == 1, f"{r['doublons']}")
check("★ proche sur la candidate proche des OK",
      next(c for c in r["images"] if c["cle"] == "cproche_ok")["proche"])
avis2 = {k: v for k, v in avis.items() if not k.startswith("pnon")}
avis2["pnon0"] = avis["pnon0"]
pp._enregistrer_avis(sid2, avis2)
r = pp._classer(sid2, cands, [], False, "t")
check("moins de 3 Non : rien n'est mis de côté", not r["ecartees"], f"{r['ecartees']}")
pp._vecteurs_candidates, pp._pret = orig_vc, orig_pret

print("5) Pousser pour OF / MYM")
IDS = TMP / "identities"
appels = []
pp._PP.clear()
pp._PP.update({"identites": lambda: ["usA", "usB", "frC"],
               "marche": lambda i: "fr" if i == "frC" else "us",
               "dossier": lambda i: IDS / str(i).lower() / "profile_pics",
               "apres": lambda: appels.append(1)})
pp._telecharger = lambda u, *a, **k: img
pp.juger(sid, "ppush", "ok", {"img": "https://exemple.org/p.jpg", "vign": "https://exemple.org/v.jpg"})
pp._telecharger = orig_dl
garde = TMP / sid / "garde" / "ppush.png"
(IDS / "usa" / "profile_pics").mkdir(parents=True)
(IDS / "usa" / "profile_pics" / "pp_1.jpg").write_bytes(_png((1, 2, 3), fmt="JPEG"))
(IDS / "usb" / "profile_pics").mkdir(parents=True)
(IDS / "usb" / "profile_pics" / "pp_7.png").write_bytes(garde.read_bytes())
cs = pp.cibles("us")
check("cibles : seules les models du marché, avec leur nombre de PP",
      [(c["id"], c["n"]) for c in cs] == [("usA", 1), ("usB", 1)], f"{cs}")
r = pp.pousser(sid, ["ppush"], "us", ["usA", "usB", "frC", "inconnue"])
check("pousser OF : copiée là où elle manque, pas en double ailleurs",
      r["ok"] and r["copiees"] == 1 and r["deja"] == 1, f"{r}")
check("pousser OF : nommage pp_N du site, sans écraser",
      (IDS / "usa" / "profile_pics" / "pp_2.png").read_bytes() == garde.read_bytes()
      and (IDS / "usa" / "profile_pics" / "pp_1.jpg").exists())
check("pousser OF : model MYM et inconnue refusées, et dites", sorted(r["refusees"]) == ["frc", "inconnue"], f"{r}")
check("pousser OF : aucun fichier temporaire laissé",
      not list(IDS.rglob("*.tmp")), f"{list(IDS.rglob('*.tmp'))}")
check("pousser OF : l'image garde la trace des models servies",
      pp._avis(sid)["ppush"]["pousse"]["ids"] == ["usA", "usB"], f"{pp._avis(sid)['ppush']}")
check("pousser OF : compteurs du site rafraîchis", len(appels) == 1, f"{appels}")
r = pp.pousser(sid, ["ppush"], "us", ["usA", "usB"])
check("pousser deux fois : rien de recopié", r["ok"] and r["copiees"] == 0 and r["deja"] == 2
      and len(list((IDS / "usa" / "profile_pics").iterdir())) == 2, f"{r}")
check("pousser MYM sans model MYM cochée : refusé", not pp.pousser(sid, ["ppush"], "fr", ["usA"])["ok"])
check("marché inconnu : refusé", not pp.pousser(sid, ["ppush"], "xx", ["usA"])["ok"])
check("image non gardée : rien de poussé", not pp.pousser(sid, ["pzz", "pbon2"], "us", ["usA"])["ok"])
r = pp.pousser(sid, ["ppush"], "tout", ["usA", "frC"])
check("bouton unique (« tout ») : les deux marchés dans le même envoi",
      r["ok"] and r["copiees"] == 1 and r["deja"] == 1 and (IDS / "frc" / "profile_pics").is_dir(), f"{r}")
check("page : la carte dit Poussée ✓ (3 models)", next(g for g in pp.gardees(sid) if g["cle"] == "ppush")["pousse_n"] == 3,
      f"{pp.gardees(sid)}")
check("cibles « tout » : chaque ligne porte son drapeau",
      {c["id"]: c["marche"] for c in pp.cibles("tout", "pp")} == {"usA": "us", "usB": "us", "frC": "fr"})
ex_f = next(TMP.glob(f"{sid}/garde/x*.png"))
(IDS / "usa" / "profile_pics" / "pp_9.png").write_bytes(ex_f.read_bytes())
cl = {c["id"]: c for c in pp.cibles("us", "pp", sid)}
check("style amorcé : coche les models qui ont déjà ses PP, et elles seules",
      cl["usA"]["coche"] and cl["usA"]["look"] == 1 and not cl["usB"]["coche"], f"{cl}")
check("sans style : la règle d'avant (des PP = cochée)", all(c["coche"] for c in pp.cibles("us", "pp")))

print("5b) Catégories : PP, Story me, life, travel, night")
import types_story
types_story.FICHIER = TMP / "story_types.json"      # jamais le vrai registre
st = pp.styles()
check("une catégorie par usage, PP en premier (un style perso suit sa catégorie)",
      [s["usage"] for s in st if s["nom"] != "Classement"] == ["pp", "me", "life", "travel", "night"]
      and [s["nom"] for s in st][:2] == ["PP", "Classement"] and st[0]["id"] == sid, f"{st}")
vieux = TMP / "vieux_styles.json"
import safe_json
safe_json.write(vieux, {"styles": [{"id": "abcdef12", "nom": "Mon style", "cree": 1, "recherches": []}]})
orig_sf = pp.STYLES_FILE
pp.STYLES_FILE = vieux
st2 = pp.styles()
check("« Mon style » du premier jour devient la catégorie PP",
      st2[0]["id"] == "abcdef12" and st2[0]["usage"] == "pp" and st2[0]["nom"] == "PP" and len(st2) == 5, f"{st2}")
pp.STYLES_FILE = orig_sf
ids_st = {s["usage"]: s["id"] for s in st}
natures = {"usA": "identite", "usR": "reserve", "frM": "modele", "frR": "reserve"}
pp._PP.clear()
pp._PP.update({"identites": lambda: list(natures), "marche": lambda i: "fr" if i.startswith("fr") else "us",
               "nature": lambda i: natures[i], "dossier": lambda i: IDS / str(i).lower() / "profile_pics"})
check("Story life : seules les réserves, cochées d'office",
      [(c["id"], c["coche"]) for c in pp.cibles("us", "life")] == [("usR", True)], f"{pp.cibles('us', 'life')}")
check("Story me : pas de réserve", [c["id"] for c in pp.cibles("fr", "me")] == ["frM"], f"{pp.cibles('fr', 'me')}")
check("PP : toutes les identités du marché", [c["id"] for c in pp.cibles("us", "pp")] == ["usA", "usR"])
pp._telecharger = lambda u, *a, **k: img
pp.juger(ids_st["life"], "plife", "ok", {"img": "https://exemple.org/l.jpg"})
pp.juger(ids_st["night"], "pnight", "ok", {"img": "https://exemple.org/n.jpg"})
pp.juger(ids_st["me"], "pme", "ok", {"img": "https://exemple.org/m.jpg"})
pp._telecharger = orig_dl
r = pp.pousser(ids_st["life"], ["plife"], "us", ["usR", "usA"])
story = IDS / "usr" / "stories" / "pfp_plife.png"
check("Story life : copiée dans stories/ de la réserve", r["ok"] and r["copiees"] == 1 and story.is_file(), f"{r}")
check("Story life : type life posé (sinon aucun bouton ne la sert)",
      types_story.type_de("usR", "pfp_plife.png") == "life", f"{types_story.lire()}")
check("Story life : une identité qui n'est pas une réserve est refusée", r["refusees"] == ["usa"], f"{r}")
check("Story life : rien dans les PP", not (IDS / "usr" / "profile_pics").exists()
      or not list((IDS / "usr" / "profile_pics").glob("pfp_*")))
r = pp.pousser(ids_st["life"], ["plife"], "us", ["usR"])
check("Story life : deux fois, pas de doublon", r["ok"] and r["copiees"] == 0 and r["deja"] == 1
      and len(list((IDS / "usr" / "stories").iterdir())) == 1, f"{r}")
r = pp.pousser(ids_st["night"], ["pnight"], "us", ["usR"])
check("Story night : refusée tant que le type n'existe pas (aucun bouton ne la servirait)",
      not r["ok"] and "night" in r["erreur"].lower() and not (IDS / "usr" / "stories" / "pfp_pnight.png").exists(),
      f"{r}")
check("Story night : la page le sait d'avance", pp.etat(ids_st["night"])["usages"]["night"]["possible"] is False)
r = pp.pousser(ids_st["me"], ["pme"], "fr", ["frM", "frR"])
check("Story me : stories/ de la model, sans type, réserve refusée",
      r["ok"] and (IDS / "frm" / "stories" / "pfp_pme.png").is_file()
      and types_story.type_de("frM", "pfp_pme.png") == "" and r["refusees"] == ["frr"], f"{r}")
s_bl = pp.creer_style("PP blonde", "pp", ["blonde cartoon girl pfp", "  "])
check("style à idées propres : la page les montre à la place de celles de la catégorie",
      pp.etat(s_bl["id"])["idees"] == ["blonde cartoon girl pfp"] and pp.etat(sid)["idees"] == pp.USAGES["pp"]["idees"])
check("format : PP carré, stories verticales", pp.etat(ids_st["life"])["usages"]["life"]["format"] == "vertical"
      and pp._format(None, "carre") == "carre" and pp._format(True) == "carre" and pp._format("xx", "vertical") == "vertical")

print("6) Page et routes (vrai create_app)")
try:
    import web_upload as w
    app = w.create_app()
    app.config["TESTING"] = True
    orig_users = w._load_web_users

    def _client(nom, role):
        w._load_web_users = lambda: {nom: {"role": role, "password": "x"}}
        cl = app.test_client()
        with cl.session_transaction() as s:
            s["auth"] = True
            s["username"] = nom
            s["role"] = role
        return cl

    pp.renommer_style(sid, "Nom </script><b>")
    adm = _client("boss", "owner")
    r = adm.get("/pfp?style=" + sid)
    h = r.get_data(as_text=True)
    check("admin : la page s'affiche", r.status_code == 200 and "Photos de profil" in h, f"HTTP {r.status_code}")
    check("un nom de style ne ferme pas le script", "Nom </script>" not in h and h.count("</script>") == 2)
    scripts = re.findall(r"<script>(.*?)</script>", h, re.S)
    f = TMP / "page.js"
    f.write_text(scripts[0] if scripts else "", encoding="utf-8")
    nc = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    check("script de la page : node --check", bool(scripts) and nc.returncode == 0, nc.stderr[:200])
    r = adm.post("/pfp/avis", json={"style": sid, "cle": "pzz", "v": "non",
                                    "meta": {"img": "https://exemple.org/a.jpg"}})
    check("admin : un avis s'enregistre", r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True)[:120])
    r = adm.post("/pfp/avis", json={"style": sid, "cle": "pzz", "v": "ok"},
                 headers={"Sec-Fetch-Site": "cross-site"})
    check("envoi venu d'un autre site : refusé", r.status_code == 403, f"HTTP {r.status_code}")
    r = adm.get(f"/pfp/zip/{sid}")
    check("zip des gardées", r.status_code == 200 and r.data[:2] == b"PK", f"HTTP {r.status_code}")
    r = adm.get(f"/pfp/cibles?marche=us&style={sid}")
    check("admin : liste des cibles", r.status_code == 200 and r.get_json()["usage"] == "pp", r.get_data(as_text=True)[:120])
    ch = _client("chatteur1", "chatter")
    check("rôle restreint : page refusée", ch.get("/pfp").status_code == 403)
    check("rôle restreint : écriture refusée",
          ch.post("/pfp/avis", json={"style": sid, "cle": "pzz", "v": "ok"}).status_code == 403)
    check("rôle restreint : fichier refusé", ch.get(f"/pfp/zip/{sid}").status_code == 403)
    check("rôle restreint : pousser refusé",
          ch.post("/pfp/pousser", json={"style": sid, "cles": ["ppush"], "marche": "us",
                                        "identites": ["usA"]}).status_code == 403)
    anon = app.test_client()
    check("anonyme : renvoyé à la connexion", anon.get("/pfp").status_code in (301, 302))
    w._load_web_users = orig_users
except Exception as e:
    check("routes : testables", False, repr(e)[:200])

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{len(OKS)} OK, {len(FAILS)} échec(s)")
sys.exit(1 if FAILS else 0)
