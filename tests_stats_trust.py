"""La page de tous les VA TRUST (stats_trust) : /trust/liens.

Propriétaire, 07/11/2026 : « un lien exprès pour le Trust. Pour Trust Twitter,
Trust Instagram et même Trust Thread », trié « par nombre de subs, ascendant,
descendant, nombre de clics ascendant, descendant, la meilleure LTV, la pire
LTV, le coût par sub » ; pour lui et les managers seulement.

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/.
Les chiffres d'un VA (stats_va.chiffres, testés par tests_stats_va.py) sont
simulés ; tout le reste est le vrai code.
  1. La clé : créée une fois, stable, fichier 0600 ; fausse, vide ou courte :
     rien. Une clé par serveur (08/11) : distinctes, n'ouvrent que leur
     serveur, ne changent pas la clé de la page.
  2. Qui est sur la page : les fiches des trois serveurs TRUST, pas les autres
     serveurs, pas les VA partis ; une fiche illisible garde sa ligne.
  3. Les lignes : coût / sub = Gagné ÷ subs, marge = LTV − coût ; les tris
     demandés, l'illisible toujours en bas ; le total pondéré.
  4. La lecture en fond : la page répond tout de suite, se recharge seule
     pendant la lecture, plus quand elle est finie.
  5. La page : onglets par serveur, raccourcis de tri, clé gardée dans chaque
     lien, tout échappé.
  6. La route : sans compte ni clé, renvoi à l'accueil ; clé fausse 403 ; bonne
     clé : la page, sans le lien des managers ; admin connecté : la page et le
     lien ; en-têtes no-store, noindex, no-referrer.
  7. Rien d'écrit dans le vrai data/.

Lancer depuis la racine du dépôt : python tests_stats_trust.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import pathlib
import re
import stat
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


VRAI = BOT / "data" / "stats_trust_cle.json"
AVANT = VRAI.stat().st_mtime if VRAI.exists() else None

import stats_trust as st        # noqa: E402
import stats_va as sv           # noqa: E402
import liens_va                 # noqa: E402
import podium_discord as pod    # noqa: E402
import tickets_discord          # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="stats_trust_"))
st.CLE_FICHIER = TMP / "stats_trust_cle.json"
JOUR = dt.date(2026, 11, 7)
pod._aujourdhui = lambda: JOUR
TW, IG, TH = sv.TWITTER_ID, sv.AGENCY_IG_ID, sv.THREADS_ID
AUTRE = "1535758943324999711"   # Youl4b (Spam) : pas sur la page

FICHES = {
    f"{TW}:1": {"numero": 12, "pseudo": "alpha"},
    f"{TW}:2": {"numero": 13, "pseudo": "<b>beta</b>"},
    f"{TW}:3": {"numero": 14, "pseudo": "parti_tw"},
    f"{IG}:4": {"numero": 108, "pseudo": "gamma"},
    f"{IG}:5": {"numero": 109, "pseudo": "sans_fiche"},
    f"{TH}:6": {"numero": 141, "pseudo": "delta"},
    f"{TH}:7": {"numero": 142, "pseudo": "panne"},
    f"{AUTRE}:8": {"numero": 1, "pseudo": "spam_va"},
}
liens_va._etat = lambda: {"liens": FICHES}
tickets_discord.partis = lambda g: {"3": 1.0} if g == TW else {}

#  subs, gagné, LTV ($ / sub), clics US, clics globaux, Infloww, CVR
CH = {
    "1": dict(subs=100, gagne=70.0, par_sub=3.0, revenu=300.0, us=900, glob=2000, infloww=950, cvr=10.5),
    "2": dict(subs=10, gagne=7.0, par_sub=1.0, revenu=10.0, us=100, glob=300, infloww=120, cvr=8.0),
    "4": dict(subs=50, gagne=35.0, par_sub=None, revenu=None, us=400, glob=600, infloww=None, cvr=None),
    "6": dict(subs=20, gagne=60.0, par_sub=2.5, revenu=50.0, us=3000, glob=5000, infloww=2900, cvr=0.7),
}
APPELS = []


def _chiffres(g, u, du="", au=""):
    APPELS.append((g, u, du, au))
    if u == "5":
        raise LookupError("pas de fiche")
    if u == "7":
        raise RuntimeError("GetMySocial 429")
    d = dict(CH[u])
    d.update(numero=FICHES[f"{g}:{u}"]["numero"], pseudo=FICHES[f"{g}:{u}"]["pseudo"], gid=g, du=du, au=au)
    return d


sv.chiffres = _chiffres

print("1. La clé")
k = st.cle()
check("créée : longue, la même au second appel", len(k) >= 20 and st.cle() == k)
check("fichier 0600", stat.S_IMODE(st.CLE_FICHIER.stat().st_mode) == 0o600, oct(st.CLE_FICHIER.stat().st_mode))
check("bonne clé : oui ; fausse, coupée, vide : non",
      st.cle_ok(k) and not st.cle_ok("x" * 32) and not st.cle_ok(k[:-1]) and not st.cle_ok("") and not st.cle_ok(None))
check("le lien des managers porte la clé, sur trust-ofm.com",
      st.lien() == f"https://trust-ofm.com/trust/liens?k={k}", st.lien())
# 08/11, propriétaire : « un lien exprès pour que Twitter, un pour que
# Instagram et un pour que Threads »
k_tw, k_ig, k_th = st.cle("tw"), st.cle("ig"), st.cle("th")
check("une clé par serveur : longues, toutes différentes",
      all(len(x) >= 20 for x in (k_tw, k_ig, k_th)) and len({k, k_tw, k_ig, k_th}) == 4)
check("créer les clés des serveurs ne change pas celle déjà donnée", st.cle() == k)
check("chaque clé de serveur stable au second appel",
      (st.cle("tw"), st.cle("ig"), st.cle("th")) == (k_tw, k_ig, k_th))
check("portée : page → tous, chaque serveur → le sien, fausse ou coupée → rien",
      st.portee(k) == "tous" and st.portee(k_tw) == "tw" and st.portee(k_ig) == "ig"
      and st.portee(k_th) == "th" and st.portee(k_tw[:-1]) is None and st.portee("x" * 32) is None
      and st.portee("") is None and st.portee(None) is None)
check("cle_ok accepte aussi les clés des serveurs", st.cle_ok(k_ig) and not st.cle_ok(k_ig + "x"))
try:
    st.cle("spam")
    _leve = False
except ValueError:
    _leve = True
check("serveur inconnu : refusé, rien créé", _leve and "spam" not in str(st.CLE_FICHIER.read_text()))
check("fichier toujours 0600", stat.S_IMODE(st.CLE_FICHIER.stat().st_mode) == 0o600)
lm = st.liens_managers()
check("liens des managers : la page entière puis Twitter, Instagram, Threads, sur trust-ofm.com",
      [lib for lib, _u in lm] == ["Tous", "TRUST TWITTER seul", "TRUST INSTAGRAM seul", "TRUST THREADS seul"]
      and [u for _l, u in lm] == [f"https://trust-ofm.com/trust/liens?k={x}" for x in (k, k_tw, k_ig, k_th)], lm)
_vrai_fichier = st.CLE_FICHIER
st.CLE_FICHIER = TMP / "ancien_format.json"
import safe_json as _sj  # noqa: E402
_sj.write(st.CLE_FICHIER, {"cle": "A" * 32, "cree": 1})
_k_ancien = st.cle("th")
check("fichier de l'ancien format : la clé de la page est gardée, celle de Threads ajoutée",
      st.cle() == "A" * 32 and st.portee("A" * 32) == "tous" and st.portee(_k_ancien) == "th")
st.CLE_FICHIER = _vrai_fichier

print("2. Qui est sur la page")
gens, rem = st.personnes()
uids = sorted(p["uid"] for p in gens)
check("les trois serveurs TRUST, sans Youl4b (Spam) ni le VA parti", uids == ["1", "2", "4", "5", "6", "7"], uids)
check("rien à signaler quand tout se lit", rem == [], rem)

print("3. La lecture d'une période")
lot = st._calculer("2026-11-01", "2026-11-07")
check("chaque VA lu une fois, sur la période demandée",
      sorted(a[1] for a in APPELS) == ["1", "2", "4", "5", "6", "7"]
      and all(a[2:] == ("2026-11-01", "2026-11-07") for a in APPELS), APPELS)
check("deux illisibles : remontés avec leur raison, pas écartés",
      lot["pannes"] == {f"{IG}:5": "pas de fiche", f"{TH}:7": "RuntimeError : GetMySocial 429"}, lot["pannes"])
L = {x["uid"] if "uid" in x else None: x for x in []}
lignes = [st._ligne(p, lot["lignes"].get(f"{p['gid']}:{p['uid']}")) for p in lot["gens"]]
par_nom = {x["nom"]: x for x in lignes}
a = par_nom["Twitter VA 12"]
check("coût / sub = Gagné ÷ subs ; marge = LTV − coût", abs(a["cout"] - 0.70) < 1e-9 and abs(a["marge"] - 2.30) < 1e-9, a)
t = par_nom["Threads VA 141"]
check("Threads payé aux clics : coût / sub 3 $, marge négative", abs(t["cout"] - 3.0) < 1e-9 and t["marge"] < 0, t)
check("LTV illisible : pas de marge, le coût reste", par_nom["Instagram VA 108"]["marge"] is None
      and abs(par_nom["Instagram VA 108"]["cout"] - 0.70) < 1e-9)
check("VA illisible : sa ligne, vide", par_nom["Threads VA 142"]["lu"] is False and par_nom["Threads VA 142"]["subs"] is None)


def ordre(tri, sens, s="tous"):
    xs = [x for x in lignes if s == "tous" or x["code"] == s]
    return [x["numero"] for x in st.trier(xs, tri, sens)]


check("plus de subs : 12, 108, 141, 13 puis les illisibles", ordre("subs", "desc")[:4] == [12, 108, 141, 13]
      and set(ordre("subs", "desc")[4:]) == {109, 142}, ordre("subs", "desc"))
check("moins de subs : 13 d'abord, les illisibles TOUJOURS en bas",
      ordre("subs", "asc")[:4] == [13, 141, 108, 12] and set(ordre("subs", "asc")[4:]) == {109, 142},
      ordre("subs", "asc"))
check("plus de clics (globaux) : Threads 141 en tête", ordre("glob", "desc")[0] == 141)
check("meilleure LTV : 12 (3 $) ; pire LTV : 13 (1 $)", ordre("ltv", "desc")[0] == 12 and ordre("ltv", "asc")[0] == 13)
check("coût / sub le plus bas puis le plus haut", ordre("cout", "asc")[0] in (12, 13, 108) and ordre("cout", "desc")[0] == 141)
check("plus rentables : 12 (marge 2,30 $) ; moins rentables : 141",
      ordre("marge", "desc")[0] == 12 and ordre("marge", "asc")[0] == 141)
check("onglet Twitter : ses deux VA seulement", sorted(ordre("subs", "desc", "tw")) == [12, 13])
check("gain / perte = revenu net − Gagné : +230 $, +3 $, −10 $ ; revenu illisible : « — »",
      par_nom["Twitter VA 12"]["gain"] == 230.0 and par_nom["Twitter VA 13"]["gain"] == 3.0
      and par_nom["Threads VA 141"]["gain"] == -10.0 and par_nom["Instagram VA 108"]["gain"] is None)
check("plus gros gains : 12, 13, 141 puis les illisibles", ordre("gain", "desc")[:3] == [12, 13, 141]
      and set(ordre("gain", "desc")[3:]) == {108, 109, 142}, ordre("gain", "desc"))
check("plus grosses pertes : 141 d'abord, les illisibles toujours en bas", ordre("gain", "asc")[:3] == [141, 13, 12])
zp = st._ligne({"gid": TW, "code": "tw", "plateforme": "Twitter", "numero": 30, "pseudo": "emy"},
               {"subs": 65, "gagne": 45.5, "par_sub": 0.31, "revenu": None, "revenu_partiel": True})
check("ancien tracking Emy (revenu partiel) : LTV, marge et gain « — », pas une perte inventée",
      zp["ltv"] is None and zp["marge"] is None and zp["gain"] is None and abs(zp["cout"] - 0.7) < 1e-9, zp)
tg = st.totaux(lignes)
check("total gain / perte : 230 + 3 − 10 = 223 $, sur 3 VA", tg["gain"] == 223.0 and tg["n_gain"] == 3, tg)
tot = st.totaux([x for x in lignes if x["code"] == "tw"])
check("total Twitter : sommes, LTV pondérée par les subs ((3×100 + 1×10) / 110)",
      tot["subs"] == 110 and tot["glob"] == 2300 and abs(tot["gagne"] - 77) < 1e-9
      and abs(tot["ltv"] - 310 / 110) < 1e-9 and abs(tot["cout"] - 0.7) < 1e-9, tot)

print("4. La page")
h = st.page_html(lot, None, cle_=k, s="tous", du="2026-11-01", au="2026-11-07", tri="subs", sens="desc", jour=JOUR)
check("un pseudo ne peut rien casser (échappé)", "<b>beta</b>" not in h and "&lt;b&gt;beta&lt;/b&gt;" in h)
check("les tris demandés, en raccourcis",
      all(x in h for x in ("Plus de subs", "Moins de subs", "Plus de clics", "Moins de clics", "Meilleure LTV",
                           "Pire LTV", "Coût / sub le plus bas", "Plus rentables", "Plus gros gains",
                           "Plus grosses pertes")))
check("colonne Gain / perte : en-tête, perte en rouge avec son signe, gain en vert",
      ">Gain / perte</a></th>" in h and re.search(r'<td class="neg" title="[^"]*">−10,00', h)
      and '<td class="pos">230,00' in h)
check("Total : le gain / perte partiel est dit", "gain / perte : 3 VA" in h)
check("Threads : astérisque et explication au survol sur son gain / perte",
      re.search(r'<td class="neg" title="revenu des visiteurs envoyés sans tracking non compté">−10,00[^<]*\*</td>', h))
check("… et pas d'astérisque sur Twitter", re.search(r'<td class="pos">230,00[^<*]*</td>', h))
check("la note Threads au pied de la page", "perte affichés sont des maximums" in h)
check("Threads : astérisque aussi sur coût / sub et marge",
      re.search(r'<td title="subs des visiteurs envoyés sans tracking non comptés">3,00[^<]*\*</td>', h)
      and re.search(r'<td class="neg" title="subs des visiteurs envoyés sans tracking non comptés">−0,50[^<]*\*</td>', h),
      h[h.find("Threads VA 141"):h.find("Threads VA 141") + 900])
hp = st.page_html({"gens": [{"gid": TW, "uid": "30", "code": "tw", "plateforme": "Twitter", "numero": 30, "pseudo": "emy"}],
                   "lignes": {f"{TW}:30": {"subs": 65, "gagne": 45.5, "par_sub": 0.31, "revenu": None,
                                            "revenu_partiel": True}}, "pannes": {}, "fin": 1.0},
                  None, cle_=k, s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR)
check("revenu partiel : dit au pied (« 1 VA avec un ancien tracking Emy ou une variante Seren »)",
      "1 VA avec un ancien tracking Emy ou une variante Seren" in hp)
check("la clé gardée dans les liens (onglets, tris, périodes, formulaire)",
      h.count(f"k={k}") >= 15 and f'name="k" value="{k}"' in h)
check("onglets Tous 6, Twitter 2, Instagram 2, Threads 2",
      "Tous <span>6</span>" in h and "Twitter <span>2</span>" in h and "Threads <span>2</span>" in h)
check("lecture finie : pas de rechargement", 'http-equiv="refresh"' not in h)
check("les non lus nommés au pied de la page", "Instagram VA 109 (pas de fiche)" in h and "Threads VA 142" in h)
check("clé : le lien des managers n'est pas recopié sur la page", "Lien à donner" not in h)
check("aucune source d'autre serveur", "spam_va" not in h)
ha = st.page_html(lot, None, cle_="", s="tw", du="2026-11-01", au="2026-11-07", tri="ltv", sens="asc", jour=JOUR,
                  lien_mgr=st.lien())
check("admin : le lien des managers en haut", "Lien à donner aux managers" in ha and st.lien() in ha)
check("onglet Twitter : pas de Threads ni d'Instagram dans le tableau", "delta" not in ha and "gamma" not in ha)
check("pire LTV : 13 (beta) avant 12 (alpha)", ha.index("beta") < ha.index("alpha"))
he = st.page_html(None, {"gens": lot["gens"], "lignes": {}, "pannes": {}, "debut": 0}, cle_=k, s="tous",
                  du="", au="", tri="subs", sens="desc", jour=JOUR)
check("lecture en cours : bandeau 0 / 6 et rechargement seul",
      "Lecture en cours : 0 / 6" in he and 'http-equiv="refresh"' in he)
hv = st.page_html(lot, None, cle_=k_tw, s="th", du="", au="", tri="subs", sens="desc", jour=JOUR, verrou="tw")
check("lien Twitter : ses VA seulement, même si ?s=th est demandé",
      "alpha" in hv and "beta" in hv and "delta" not in hv and "gamma" not in hv and "spam_va" not in hv)
check("lien Twitter : un seul onglet, ni Tous ni les autres serveurs",
      "Twitter <span>2</span>" in hv and "Tous <span>" not in hv and "Instagram <span>" not in hv
      and "Threads <span>" not in hv)
check("lien Twitter : titre et marque TRUST TWITTER",
      "<h1>📊 VA TRUST TWITTER · clics et subs</h1>" in hv and '<div class="marque">TRUST · Twitter</div>' in hv
      and "<title>VA TRUST TWITTER · clics et subs</title>" in hv)
check("lien Twitter : ni les non-lus ni les notes Threads des autres serveurs",
      "Threads VA 142" not in hv and "Instagram VA 109" not in hv and "perte affichés sont des maximums" not in hv)
check("lien Twitter : la clé Twitter gardée dans les liens", hv.count(f"k={k_tw}") >= 10 and f"k={k}&" not in hv)
hth = st.page_html(lot, None, cle_=k_th, s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR, verrou="th")
check("lien Threads : ses VA, ses non-lus et sa note Threads",
      "delta" in hth and "alpha" not in hth and "Threads VA 142" in hth and "perte affichés sont des maximums" in hth)
hve = st.page_html(None, {"gens": lot["gens"], "lignes": {f"{TW}:1": {}}, "pannes": {}, "debut": 0}, cle_=k_ig,
                   s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR, verrou="ig")
check("lien Instagram, lecture en cours : le bandeau ne compte que ses VA (0 / 2)",
      "Lecture en cours : 0 / 2" in hve, re.findall(r"Lecture en cours : [^.]*", hve))
check("pages Twitter et Instagram : le mot Threads n'y paraît nulle part",
      "Threads" not in hv and "Threads" not in hve, [m.start() for m in re.finditer("Threads", hv)][:5])
check("page Threads : sa note de paie seule, pas celle des autres serveurs",
      "Threads : clics US·UK·CA, payé aux clics" in hth and "Twitter et Instagram" not in hth)
# lecture arrêtée (source muette) : le nombre du texte compte les trois serveurs
_arret = ("Lecture arrêtée après 3 VA de plus de 60 s chacun (MyPuls, Infloww ou GetMySocial ne répond "
          "plus) : 6 VA pas lus")
_lot_arr = dict(lot, remarques=[_arret], incomplet=True,
                pannes={f"{IG}:4": "pas lu : une source ne répond plus", f"{TH}:6": "pas lu : une source ne répond plus"})
hva = st.page_html(_lot_arr, None, cle_=k_tw, s="tw", du="", au="", tri="subs", sens="desc", jour=JOUR,
                   verrou="tw", essai_apres=__import__("time").time() + 300, echec=_arret)
check("lien Twitter, lecture arrêtée : ni le total des trois serveurs ni leurs non-lus",
      "6 VA pas lus" not in hva and "Lecture interrompue" in hva and "Instagram VA" not in hva
      and "Threads VA" not in hva, re.findall(r'class="encours">[^<]*', hva))
hta = st.page_html(_lot_arr, None, cle_=k_th, s="th", du="", au="", tri="subs", sens="desc", jour=JOUR,
                   verrou="th", essai_apres=__import__("time").time() + 300, echec=_arret)
check("lien Threads, lecture arrêtée : ses non-lus nommés au pied",
      "Non lus : Threads VA 141" in hta and "6 VA pas lus" not in hta)
hpa = st.page_html(_lot_arr, None, cle_=k, s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR,
                   essai_apres=__import__("time").time() + 300, echec=_arret)
check("page entière, lecture arrêtée : le texte d'origine (inchangé)", hpa.count("6 VA pas lus") == 2)
_vrai_jour = pod._aujourdhui
pod._aujourdhui = lambda: (_ for _ in ()).throw(RuntimeError("panne"))
_c, herr = st.page({}, cle_=k_ig, verrou="ig")
_c2, herr2 = st.page({}, cle_=k_ig, verrou="zz")
pod._aujourdhui = _vrai_jour
check("page d'erreur d'un lien Instagram : marque TRUST · Instagram ; verrou inconnu : ne lève pas",
      '<div class="marque">TRUST · Instagram</div>' in herr and "Lecture impossible" in herr2
      and '<div class="marque">TRUST · Twitter · Instagram · Threads</div>' in herr2)
_vrai_lien = st.lien
st.lien = lambda code="": (_ for _ in ()).throw(OSError("lecture seule")) if code == "ig" else _vrai_lien(code)
_lm = st.liens_managers()
st.lien = _vrai_lien
check("une clé non écrite n'emporte pas les autres liens",
      len(_lm) == 4 and _lm[0][1] == st.lien() and "non écrite" in _lm[2][1] and _lm[3][1] == st.lien("th"), _lm)
ha2 = st.page_html(lot, None, cle_="", s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR,
                   lien_mgr=st.liens_managers())
check("admin : les quatre liens à donner, chacun nommé",
      "Liens à donner aux managers" in ha2 and all(u in ha2 for _l, u in st.liens_managers())
      and "TRUST INSTAGRAM seul" in ha2)

print("5. La lecture en fond")
st._LOTS.clear()
APPELS.clear()
code, h1 = st.page({"du": "2026-10-16", "au": "2026-10-31"}, cle_=k)
check("la page répond tout de suite (200)", code == 200)
if st._FIL:
    st._FIL.join(10)
code, h2 = st.page({"du": "2026-10-16", "au": "2026-10-31"}, cle_=k)
check("puis complète, sans rechargement, chaque VA lu une fois",
      code == 200 and "alpha" in h2 and 'http-equiv="refresh"' not in h2 and len(APPELS) == 6, len(APPELS))
st.page({"du": "2026-10-16", "au": "2026-10-31"}, cle_=k)
check("relue dans les 10 min : aucun nouvel appel", len(APPELS) == 6, len(APPELS))
_max = st.PERIODES_JOUR_MAX
st.PERIODES_JOUR_MAX = 0
st._LECTURES.clear()
cq, hq = st.page({"du": "2026-09-01", "au": "2026-09-02"}, cle_=k)
cr, _hr = st.page({}, cle_=k)
st.PERIODES_JOUR_MAX = _max
if st._FIL:
    st._FIL.join(10)
check("quota de périodes à la main : 429, les raccourcis marchent encore", cq == 429 and cr == 200, (cq, cr))


print("5b. Relecture du 07/11 : file, quota, coût, sources muettes")
import threading, time as _time   # noqa: E402,E401
BLOQUE = threading.Event()
_vrai_chiffres = sv.chiffres


def _chiffres_bloque(g, u, du="", au=""):
    if du == "2026-08-01":
        BLOQUE.wait(20)
    return _vrai_chiffres(g, u, du, au)


sv.chiffres = _chiffres_bloque
st._LOTS.clear(); st._FILE.clear(); st._LECTURES.clear(); st._VUS.clear(); APPELS.clear()
BLOQUE.clear()
st.page({"du": "2026-08-01", "au": "2026-08-02"}, cle_=k)           # occupe le fil
codes = [st.page({"du": "2026-08-03", "au": "2026-08-04"}, cle_=k) for _i in range(35)]
check("une période en file rechargée 35 fois : toujours 200, comptée UNE fois",
      all(c_ == 200 for c_, _h in codes) and st._LECTURES.get(JOUR.isoformat()) == 2,
      (sorted({c_ for c_, _h in codes}), st._LECTURES))
check("… et sa page dit « Lecture en attente » et se recharge",
      "Lecture en attente" in codes[-1][1] and 'http-equiv="refresh"' in codes[-1][1])
# une période lue il y a une heure, remise en file derrière la lecture bloquée
st._LOTS[("2026-07-01", "2026-07-02")] = {"fait": dict(lot, fin=_time.time() - 3600), "encours": None}
cs, hs = st.page({"du": "2026-07-01", "au": "2026-07-02"}, cle_=k)
check("lecture périmée remise en file : bandeau « Mise à jour en attente » et rechargement",
      "Mise à jour en attente" in hs and 'http-equiv="refresh"' in hs and ("2026-07-01", "2026-07-02") in st._FILE)
# plus personne ne regarde 08/03 -> 08/04 : sortie de la file sans être lue
st._VUS[("2026-08-03", "2026-08-04")] = _time.time() - 3600
st._VUS[("2026-07-01", "2026-07-02")] = _time.time() - 3600
BLOQUE.set()
if st._FIL:
    st._FIL.join(20)
check("une période que plus personne ne regarde n'est pas lue",
      not any(a[2] in ("2026-08-03", "2026-07-01") for a in APPELS) and not st._FILE,
      sorted({a[2] for a in APPELS}))
check("la lecture qui occupait le fil, elle, va au bout",
      (st._LOTS.get(("2026-08-01", "2026-08-02")) or {}).get("fait") is not None)
sv.chiffres = _vrai_chiffres

# deux requêtes pendant personnes() : la période n'est lue qu'une fois
_vraies_personnes = st.personnes


def _personnes_lentes():
    _time.sleep(0.3)
    return _vraies_personnes()


st.personnes = _personnes_lentes
st._LOTS.clear(); st._FILE.clear(); st._VUS.clear(); APPELS.clear()
st.page({}, cle_=k)
_time.sleep(0.1)
st.page({}, cle_=k)
if st._FIL:
    st._FIL.join(20)
st.personnes = _vraies_personnes
check("une 2e requête pendant la lecture ne la relance pas (6 VA lus, pas 12)", len(APPELS) == 6, len(APPELS))

# Threads payé aux clics sans un sub
X = [st._ligne({"gid": TH, "code": "th", "plateforme": "Threads", "numero": 150, "pseudo": "zero"},
               {"subs": 0, "gagne": 130.0, "par_sub": None, "us": 2000, "glob": 2600}),
     st._ligne({"gid": TH, "code": "th", "plateforme": "Threads", "numero": 151, "pseudo": "vingt"},
               {"subs": 20, "gagne": 60.0, "par_sub": 10.0, "us": 1500, "glob": 1800}),
     st._ligne({"gid": TH, "code": "th", "plateforme": "Threads", "numero": 152, "pseudo": "muet"}, None)]
o_cd = [x["numero"] for x in st.trier(X, "cout", "desc")]
o_ma = [x["numero"] for x in st.trier(X, "marge", "asc")]
o_ca = [x["numero"] for x in st.trier(X, "cout", "asc")]
check("payé sans sub : EN TÊTE de « coût le plus haut » et de « moins rentables »",
      o_cd == [150, 151, 152] and o_ma == [150, 151, 152], (o_cd, o_ma))
check("payé sans sub : jamais mêlé aux illisibles (coût le plus bas : avant-dernier)", o_ca == [151, 150, 152], o_ca)
tx = st.totaux(X)
check("total : la paie du VA à 0 sub compte (190 $ / 20 subs = 9,50 $), marge sur les mêmes VA",
      abs(tx["cout"] - 9.5) < 1e-9 and abs(tx["marge"] - (200 - 190) / 20) < 1e-9, tx)
hx = st.page_html({"gens": [{"gid": TH, "uid": "9", "code": "th", "plateforme": "Threads", "numero": 150,
                             "pseudo": "zero"}],
                   "lignes": {f"{TH}:9": {"subs": 0, "gagne": 130.0, "par_sub": None, "us": 2000, "glob": 2600}},
                   "pannes": {}, "fin": 1.0}, None, cle_=k, s="tous", du="", au="", tri="cout", sens="desc",
                  jour=JOUR)
check("payé sans sub : écrit « payé, 0 sub », pas « — » (sa ligne et le Total)", hx.count("payé, 0 sub</td>") == 4)
check("Total : « payé, 0 sub » seulement quand le groupe n'a aucun sub",
      st.totaux([X[0]])["paye_sans_sub"] and not tx["paye_sans_sub"])
# LTV, coût, marge du Total sur le même groupe : un VA MYM (LTV —) n'y entre pas, et c'est dit
Y = [st._ligne({"gid": TW, "code": "tw", "plateforme": "Twitter", "numero": 20, "pseudo": "mym"},
               {"subs": 100, "gagne": 120.0, "par_sub": None}),
     st._ligne({"gid": TW, "code": "tw", "plateforme": "Twitter", "numero": 21, "pseudo": "of"},
               {"subs": 10, "gagne": 7.0, "par_sub": 1.0})]
ty = st.totaux(Y)
check("Total : marge = LTV − coût, sur les mêmes VA", abs(ty["ltv"] - 1.0) < 1e-9 and abs(ty["cout"] - 0.7) < 1e-9
      and abs(ty["marge"] - 0.3) < 1e-9 and ty["n_groupe"] == 1 and ty["subs"] == 110 and ty["gagne"] == 127, ty)
hy = st.page_html({"gens": [{"gid": TW, "uid": str(n), "code": "tw", "plateforme": "Twitter", "numero": n,
                             "pseudo": "p"} for n in (20, 21)],
                   "lignes": {f"{TW}:20": {"subs": 100, "gagne": 120.0, "par_sub": None},
                              f"{TW}:21": {"subs": 10, "gagne": 7.0, "par_sub": 1.0}},
                   "pannes": {}, "fin": 1.0}, None, cle_=k, s="tous", du="", au="", tri="subs", sens="desc", jour=JOUR)
check("Total : le groupe réduit est dit (« LTV, coût, marge : 1 VA »)", "LTV, coût, marge : 1 VA" in hy)

# trois VA lents d'affilée : la lecture s'arrête et le dit
_lent = st.LENT_S
st.LENT_S = 0.01


def _chiffres_lents(g, u, du="", au=""):
    _time.sleep(0.03)
    return _vrai_chiffres(g, u, du, au)


sv.chiffres = _chiffres_lents
lot_l = st._calculer("2026-06-01", "2026-06-02")
sv.chiffres = _vrai_chiffres
st.LENT_S = _lent
check("3 VA lents d'affilée (sans lecture d'avant) : arrêt, les 3 autres « pas lus », remarque au pied",
      len(lot_l["lignes"]) + len([v for v in lot_l["pannes"].values() if v != "pas de fiche"]) == 6
      and sum(1 for v in lot_l["pannes"].values() if v.startswith("pas lu")) == 3
      and any("Lecture arrêtée" in r for r in lot_l["remarques"]), (lot_l["pannes"], lot_l["remarques"]))


# arrêt « source muette » quand une lecture complète existe : elle reste, un essai suit
P_M = ("2026-05-01", "2026-05-02")
complet = dict(lot, fin=_time.time() - 700)
st._LOTS[P_M] = {"fait": complet, "encours": None}
st.LENT_S = 0.01
sv.chiffres = _chiffres_lents
st._calculer(*P_M)
sv.chiffres = _vrai_chiffres
st.LENT_S = _lent
e_m = st._LOTS[P_M]
check("source muette : la lecture complète d'avant reste affichée, un essai est daté",
      e_m["fait"] is complet and e_m.get("essai_apres", 0) > _time.time() and "Lecture arrêtée" in e_m.get("echec", ""),
      {k_: v_ for k_, v_ in e_m.items() if k_ != "fait"})
APPELS.clear(); st._FILE.clear()
cm, hm = st.page({"du": P_M[0], "au": P_M[1]}, cle_=k)
check("… pas de relance avant l'heure de l'essai ; bandeau et rechargement à cette heure-là",
      not st._FILE and not APPELS and "Nouvel essai à" in hm and "dernière lecture complète" in hm
      and re.search(r'http-equiv="refresh" content="(29\d|300)"', hm), (st._FILE, hm[:400]))
e_m["essai_apres"] = _time.time() - 1
st.page({"du": P_M[0], "au": P_M[1]}, cle_=k)
if st._FIL:
    st._FIL.join(20)
check("… l'heure passée, la période est relue et l'essai effacé",
      (st._LOTS[P_M]["fait"] is not complet) and "essai_apres" not in st._LOTS[P_M] and len(APPELS) == 6, len(APPELS))

# une lecture commencée va au bout même si plus personne ne regarde
P_C = ("2026-04-01", "2026-04-02")
st._VUS[P_C] = _time.time() - 3600
APPELS.clear()
st._calculer(*P_C)
check("une lecture commencée va au bout, même onglet fermé", len(APPELS) == 6
      and (st._LOTS[P_C]["fait"] or {}).get("lignes"), len(APPELS))

# quota : une période sortie de la file sans être lue ne se recompte pas au retour
st._LECTURES.clear(); st._COMPTEES.clear(); st._LOTS.clear(); st._FILE.clear(); st._VUS.clear()
st._compter_periode("2026-03-01", "2026-03-02", JOUR)
st._compter_periode("2026-03-01", "2026-03-02", JOUR)
check("quota : une période comptée une fois par jour, même revenue après sa sortie de file",
      st._LECTURES.get(JOUR.isoformat()) == 1, st._LECTURES)

# la liste d'un espace GetMySocial : une fois par lot, toujours relue hors lot
import gms                       # noqa: E402
_vraie_liste = gms.list_links_team
LISTES = []


def _fausse_liste(equipe, force_refresh=False):
    LISTES.append((equipe, force_refresh))
    return {"ok": True, "links": [{"id": "lnk_1"}]} if equipe != "tm_vide" else {"ok": True, "links": []}


gms.list_links_team = _fausse_liste
try:
    pod._liste_equipe("tm_a"); pod._liste_equipe("tm_a")
    hors = len(LISTES)
    LISTES.clear()
    with pod.listes_du_lot():
        for _i in range(5):
            pod._liste_equipe("tm_a"); pod._liste_equipe("tm_b"); pod._liste_equipe("tm_vide")
    dans = list(LISTES)
    LISTES.clear()
    pod._liste_equipe("tm_a")
    apres = len(LISTES)
finally:
    gms.list_links_team = _vraie_liste
check("hors lot : chaque appel relit l'espace (force_refresh), comme avant", hors == 2 and apres == 1, (hors, apres))
check("dans un lot : une lecture par espace ; une réponse vide n'est pas gardée",
      dans.count(("tm_a", True)) == 1 and dans.count(("tm_b", True)) == 1 and dans.count(("tm_vide", True)) == 5,
      dans)


print("6. La route")
import web_upload as wu         # noqa: E402
app = wu.create_app()
app.config["TESTING"] = True
c = app.test_client()
r = c.get("/trust/liens")
check("sans compte ni clé : renvoi à l'accueil", r.status_code in (301, 302) and r.headers.get("Location", "").endswith("/"),
      r.status_code)
r = c.get("/trust/liens?k=" + "z" * 32)
check("clé fausse : 403", r.status_code == 403, r.status_code)
r = c.get(f"/trust/liens?k={k}")
corps = r.get_data(as_text=True)
check("bonne clé : la page, sans le lien des managers", r.status_code == 200 and "VA TRUST" in corps
      and "Lien à donner" not in corps, r.status_code)
check("en-têtes : no-store, noindex, no-referrer",
      "no-store" in r.headers.get("Cache-Control", "") and "noindex" in r.headers.get("X-Robots-Tag", "")
      and r.headers.get("Referrer-Policy") == "no-referrer", dict(r.headers))
# 08/11 : le lien des managers est sur trust-ofm.com ; sans la garde de
# domaines qui laisse passer /trust/liens, il ouvrait la page neutre.
r = c.get(f"/trust/liens?k={k}", headers={"Host": "trust-ofm.com"})
check("trust-ofm.com, bonne clé : la page", r.status_code == 200 and "VA TRUST" in r.get_data(as_text=True),
      r.status_code)
r = c.get("/trust/liens?k=" + "z" * 32, headers={"Host": "trust-ofm.com"})
check("trust-ofm.com, clé fausse : 403", r.status_code == 403, r.status_code)
r = c.get(f"/trust/liens?k={k_tw}&s=th", headers={"Host": "trust-ofm.com"})
b = r.get_data(as_text=True)
check("clé Twitter avec ?s=th : la page Twitter seule",
      r.status_code == 200 and "VA TRUST TWITTER" in b and "Threads <span>" not in b
      and "Tous <span>" not in b and "Lien à donner" not in b and "Liens à donner" not in b, r.status_code)
r = c.get(f"/trust/liens?k={k_ig}", headers={"Host": "trust-ofm.com"})
check("clé Instagram : la page Instagram seule",
      r.status_code == 200 and "VA TRUST INSTAGRAM" in r.get_data(as_text=True), r.status_code)
r = c.get("/trust/liens", headers={"Host": "trust-ofm.com"})
r2 = c.get("/", headers={"Host": "trust-ofm.com"})
check("trust-ofm.com, sans clé : renvoi vers la page neutre, rien du dashboard",
      r.status_code in (301, 302) and r2.status_code == 404 and "Page introuvable" in r2.get_data(as_text=True),
      (r.status_code, r2.status_code))
with c.session_transaction() as s:
    s["auth"] = True
    s["username"] = "admin"
    s["role"] = "owner"
    s["legacy_owner"] = True
r = c.get("/trust/liens?s=th")
ca = r.get_data(as_text=True)
check("admin connecté, sans clé : la page et les liens des managers",
      r.status_code == 200 and "Liens à donner aux managers" in ca and k in ca and k_tw in ca
      and k_ig in ca and k_th in ca, r.status_code)
if st._FIL:
    st._FIL.join(10)

print("7. Isolation")
check("rien écrit dans le vrai data/", (VRAI.stat().st_mtime if VRAI.exists() else None) == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for x in KO:
        print("  - " + x)
print("=" * 70)
sys.exit(1 if KO else 0)
