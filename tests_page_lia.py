# -*- coding: utf-8 -*-
"""tests_page_lia.py — la page /infloww/liens?c=lia, celle de YouCham.

Propriétaire, 31/10/2026 : « comme lui [la page Emy] mais pour Lia, et pour
les clics pas Infloww mais ceux de GMS, les US, après sub, CVR et LTV », puis
« même truc, la même exacte ». Un bouton « 📊 Statistiques » du salon
📊・click-et-sub de YouCham y mène (outils_communs, vérifié par
tests_youcham_outils.py).

Ce qui est vérifié (infloww_liens, profil « lia », REGLAGES) :
  - les personnes sont les liens du GROUPE « YouCham » de l'espace personnel
    (gms.list_links_group), jamais une équipe ;
  - depuis toujours, les chiffres viennent de MyPuls (Lia n'est pas chez
    Infloww), du premier jour à aujourd'hui ;
  - colonnes : Personne, Clics US, Clics globaux (tous pays, 31/10), Clics
    Infloww (ceux du CVR ; sur une période, cumul de fin − relevé de la
    veille du début, relevé gardé chaque jour), Subs,
    CVR, $ / sub — pas de clics du lien
    de suivi ; CVR = subs ÷ clics du lien de suivi OnlyFans, lus CHEZ
    INFLOWW au pseudo « aileney » (propriétaire, 31/10 : « prends juste les
    clics sur Infloww pour le CVR ») ; MyPuls en secours (Infloww muet,
    période qu'il ne sait pas dater), et la page le dit ;
  - les autres liens de suivi de Lia (Twitter, Threads, Agency) sont comptés,
    pas listés : ni leur nom ni leurs chiffres sur la page ;
  - clics US relevés toutes les heures (liens neufs), un raté retenté après
    US_REESSAI_S ;
  - fichiers à elle (clics US, paie, copie GMS), la page Jessye et la page Emy
    ne changent pas ;
  - le nom d'une personne : son lien de suivi (« @roucham_79944 »), « VA 1 »
    dessous (propriétaire, 31/10 : « tu mets leur truc d'Infloww, genre @ ») ;
  - la paie : 0,70 $ par sub pour tout VA sans réglage à lui (propriétaire,
    31/10 : « pour cette fiche les VA c'est 0,7 par sub tout le temps ») ; un
    réglage enregistré passe devant ; Jessye et Emy sans paie imposée ;
  - l'image de la quinzaine en cours (liens_image) : les chiffres de la page,
    triés par subs, sans net ni paie, la photo Discord de chaque VA ;
  - la route : accès libre (sans clé ni compte : vue des VA ; propriétaire,
    31/10 : « mets aussi un accès libre »), le lien posté sans clé, l'admin
    connecté garde le paiement ; Emy et Jessye restent fermées sans clé.

Fausses lectures : aucun appel réseau. Lancement : python tests_page_lia.py
"""
from __future__ import annotations

import html
import io
import pathlib
import re
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


def _instantane():
    """Les fichiers de la page dans le VRAI data/ : rien ne doit y bouger."""
    d = BOT / "data"
    if not d.is_dir():
        return {}
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
            for p in d.glob("infloww_liens*") if p.is_file()}


AVANT = _instantane()

import gms                             # noqa: E402
import infloww_liens as il             # noqa: E402

GROUPE = "grp_6ae626b131228574f13b70d2"


def _dt_auj():
    import datetime
    return datetime.date.fromisoformat(il._aujourdhui())


def _interdit(*a, **k):
    raise AssertionError("appel réseau inattendu")


for _n in ("list_links_team", "list_all_links", "clicks_for_link", "clicks_for_ids"):
    setattr(gms, _n, _interdit)
gms.pause_restante = lambda: 0
gms.etat_quota = lambda: {}


def lien(i, n, c, groupe=GROUPE, statut="active"):
    return {"id": f"lnk_{i}", "display_name": f"VA {n}", "shortcode": f"lia{i}", "status": statut,
            "group_id": groupe, "created": 1793468081,
            "buttons": [{"url": f"https://onlyfans.com/liasxcret/c{c}"}]}


GROUPES_LUS = []
LIENS = [lien("a", 1, 115), lien("b", 2, 113), lien("c", 3, 112), lien("d", 4, 999)]


def _groupe(g):
    GROUPES_LUS.append(g)
    return {"ok": True, "links": list(LIENS)}


gms.list_links_group = _groupe
US = {"lnk_a": 40, "lnk_b": 12, "lnk_c": 0, "lnk_d": 30}
APPELS_US = []


def _analytics(ids, du, au):
    APPELS_US.append(tuple(ids))
    n = sum(US[i] for i in ids)
    return n + 5, {"US": n, "FR": 5}


gms.analytics_for_links = _analytics
MYPULS_LU = []


def _mypuls(du, au):
    MYPULS_LU.append((du, au))
    items = [
        {"url": "https://onlyfans.com/liasxcret/c115", "name": "@roucham_79944", "visits_period": 24,
         "subscribers_period": 3, "revenue": {"total": 12.5}, "active": True},
        {"url": "https://onlyfans.com/liasxcret/c113", "name": "@bilal082598", "visits_period": 5,
         "subscribers_period": 1, "revenue": {"total": 0}, "active": True},
        {"url": "https://onlyfans.com/liasxcret/c112", "name": "@abdoul_9684", "visits_period": 0,
         "subscribers_period": 0, "revenue": {"total": 0}, "active": True},
        # un lien de suivi de Lia d'un autre serveur : compté, pas listé
        {"url": "https://onlyfans.com/liasxcret/c60", "name": "Twitter VA 32 @bid_a", "visits_period": 900,
         "subscribers_period": 80, "revenue": {"total": 300}, "active": True},
        # une autre créatrice : ignorée
        {"url": "https://onlyfans.com/emy.brw/c12", "name": "Emy VA", "visits_period": 9,
         "subscribers_period": 9, "revenue": {"total": 9}, "active": True}]
    return m._lire_mypuls({"data": items, "count": len(items), "currency": "USD",
                           "period": {"from": du + "T00:00:00+01:00", "to": au + "T23:59:59+01:00"}}), ""


TMP = pathlib.Path(tempfile.mkdtemp(prefix="page_lia_"))
m = il.profil("lia")
FICHIERS = ("GMS_COPIE", "US_FICHIER", "US_PERIODES_FICHIER", "PAIE_FICHIER", "QUINZ_FICHIER",
            "LIGNES_FICHIER", "ETAT_FICHIER", "CLE_FICHIER", "CLE_PAIE_FICHIER", "BCE_FICHIER",
            "RELEVES_CVR_FICHIER")

print("1. Le profil")
check("profil lia : Lia (liasxcret), groupe YouCham de l'espace personnel, MyPuls, sans clics OF",
      m is not il and m.CREATRICE == "liasxcret" and m.NOM_AFFICHE == "Lia" and m.GROUPE_GMS == GROUPE
      and not m.EQUIPE_GMS and m.NOM_EQUIPE == "YouCham" and m.SOURCE_TOUJOURS == "MyPuls"
      and m.CLICS_OF is False and m.HORS_DETAIL is False and m.US_FRAIS_S == 3600)
check("profil lia : clics US, paie et copie GMS dans des fichiers à elle",
      all(getattr(m, k) != getattr(il, k) for k in ("GMS_COPIE", "US_FICHIER", "US_PERIODES_FICHIER",
                                                     "PAIE_FICHIER", "QUINZ_FICHIER", "LIGNES_FICHIER")))
check("Jessye et Emy inchangées : équipe, Infloww, clics OF, liste hors détaillée",
      all(p.GROUPE_GMS == "" and p.EQUIPE_GMS == il.EQUIPE_GMS and p.SOURCE_TOUJOURS == "Infloww"
          and p.CLICS_OF is True and p.HORS_DETAIL is True and p.US_FRAIS_S is None
          for p in (il, il.profil("emy"))))
check("le lien posté : la page Lia SANS clé (accès libre, 31/10)",
      m.ACCES_LIBRE is True and m.url_page() == "https://youl4b.com/infloww/liens?c=lia", m.url_page())
check("Jessye et Emy : toujours une clé dans le lien, pas d'accès libre",
      il.ACCES_LIBRE is False and il.profil("emy").ACCES_LIBRE is False
      and "k=" in il.profil("emy").url_page() if il.CLE_FICHIER.exists() else True)
for _k in FICHIERS:
    setattr(m, _k, TMP / (_k.lower() + ".json"))
m.US_EN_FOND = False
m._lire_mypuls_api = _mypuls
# Infloww : Lia y est sous « aileney » ; ses clics font le CVR (31/10)
AUJ = m._aujourdhui()
INFLOWW_LU = []
INFLOWW = {"erreur": "", "liens": [{"code": "115", "clics": 49, "cree": AUJ},
                                   {"code": "113", "clics": 1, "cree": AUJ},
                                   {"code": "112", "clics": 8, "cree": AUJ}]}


def _infloww_faux(creatrice=""):
    INFLOWW_LU.append(creatrice)
    return dict(INFLOWW)


m._infloww = _infloww_faux

print("2. La page, depuis toujours")
h = m.page({}, cle="CLE", paie=False)
texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", h, flags=re.S))))
t = m.tableau()
lignes = {x["cle"]: x for x in t["lignes"]}
check("liste GMS : le groupe YouCham, aucune équipe", GROUPES_LUS and set(GROUPES_LUS) == {GROUPE}, GROUPES_LUS)
check("MyPuls lu depuis le premier jour jusqu'à aujourd'hui",
      MYPULS_LU and MYPULS_LU[0] == (il.PLANCHER.isoformat(), m._aujourdhui()), MYPULS_LU)
check("une personne par lien du groupe : VA 1..VA 4", sorted(lignes) == ["VA 1", "VA 2", "VA 3", "VA 4"],
      sorted(lignes))
entetes = re.findall(r"<th[^>]*>(?:<a[^>]*>)?([^<]+)", h)
check("colonnes : Personne, Clics US, Clics globaux, Clics Infloww, Subs, CVR, $ / sub — rien d'autre",
      [" ".join(e.split()).rstrip(" ▴▾") for e in entetes]
      == ["Personne", "Clics US", "Clics globaux", "Clics Infloww", "Subs", "CVR", "$ / sub"], entetes)
check("Clics Infloww : ceux qui font le CVR (VA 1 : 49), « — » sans lien de suivi (VA 4), total 58",
      lignes["VA 1"].get("clics_cvr") == 49 and lignes["VA 4"].get("cvr_infloww") is None
      and t["totaux"].get("clics_cvr") == 58, (lignes["VA 1"].get("clics_cvr"), t["totaux"].get("clics_cvr")))
_rel = m._lire_json(m.RELEVES_CVR_FICHIER)
check("relevé du jour gardé (cumul Infloww de chaque lien, et sa création), fichier à Lia",
      (_rel.get("jours") or {}).get(AUJ) == {"115": 49, "113": 1, "112": 8}
      and (_rel.get("crees") or {}).get("115") == AUJ
      and il.RELEVES_CVR_FICHIER.name == "infloww_liens_clics_infloww.json"
      and il.REGLAGES["lia"]["RELEVES_CVR_FICHIER"].name == "infloww_liens_clics_infloww_lia.json", _rel)
check("Jessye et Emy : pas de colonne Clics Infloww",
      il.COLONNE_CLICS_CVR is False and il.profil("emy").COLONNE_CLICS_CVR is False)
check("clics globaux : le total tous pays du même relevé GetMySocial (US 40 + 5 ailleurs)",
      lignes["VA 1"]["glob"] == 45 and lignes["VA 3"]["glob"] == 5 and t["totaux"]["glob"] == 45 + 17 + 5 + 35,
      (lignes["VA 1"].get("glob"), t["totaux"].get("glob")))
check("Jessye et Emy : pas de colonne des clics globaux",
      il.CLICS_GLOBAUX is False and il.profil("emy").CLICS_GLOBAUX is False)
check("aucune colonne « Clics MyPuls » (la colonne des clics est celle d'Infloww)",
      "Clics MyPuls" not in " ".join(texte.split()) and "Clics Infloww" in " ".join(texte.split()))
va1 = lignes["VA 1"]
check("VA 1 : 40 clics US, 3 subs (MyPuls), CVR = 3 ÷ 49 clics Infloww, 4,17 $ / sub",
      va1["us"] == 40 and va1["subs"] == 3 and abs(va1["cvr"] - 300.0 / 49) < 1e-9
      and va1.get("cvr_infloww") and abs(va1["par_sub"] - 12.5 / 3) < 1e-9, va1)
check("Infloww lu au pseudo « aileney » (Lia y est sous son ancien pseudo), pas liasxcret",
      INFLOWW_LU and set(INFLOWW_LU) == {"aileney"} and m.CREATRICE_CVR == "aileney", INFLOWW_LU)
check("Jessye et Emy : CVR sur les clics de leur source, aucune lecture à part",
      il.CREATRICE_CVR == "" and il.profil("emy").CREATRICE_CVR == "")
check("nom : le lien de suivi (« @roucham_79944 »), « VA 1 · c115 » dessous ; clé, paie et ancre : « VA 1 »",
      va1["nom"] == "@roucham_79944" and va1["cle"] == "VA 1"
      and "<b>@roucham_79944</b>" in h and "VA 1 · c115" in texte and 'id="' + m.ancre("VA 1") + '"' in h,
      (va1["nom"], texte[:900]))
check("sans lien de suivi trouvé : le nom GetMySocial reste (VA 4)", lignes["VA 4"]["nom"] == "VA 4",
      lignes["VA 4"]["nom"])
check("Jessye et Emy : le nom reste celui de GetMySocial",
      il.NOM_PAR_SUIVI is False and il.profil("emy").NOM_PAR_SUIVI is False)
check("VA 3 : 0 sub sur 8 clics Infloww : 0 % (0 clic MyPuls ne compte plus)",
      lignes["VA 3"]["cvr"] == 0.0, lignes["VA 3"])
check("VA 4 : lien de suivi introuvable chez MyPuls, dit, pas de zéro inventé",
      lignes["VA 4"]["subs"] is None and lignes["VA 4"]["introuvables"], lignes["VA 4"])
T = t["totaux"]
check("total : CVR = 4 subs ÷ 58 clics Infloww (sans VA 4, subs inconnus)",
      T["us"] == 82 and abs(T["cvr"] - 4 * 100.0 / 58) < 1e-9, T)
check("le lien de suivi Twitter de Lia : compté hors YouCham, ni nom ni chiffres sur la page",
      "1 autre(s) lien(s) de suivi de Lia, hors « YouCham » : non comptés" in texte
      and "bid_a" not in h and "900" not in texte, texte[-600:])
check("autre créatrice : ignorée", "Emy VA" not in h)
check("en-tête : « Depuis toujours · MyPuls · @liasxcret · GetMySocial « YouCham » », marque MyPuls · YouCham",
      "Depuis toujours · MyPuls · @liasxcret · GetMySocial « YouCham »" in texte
      and "MyPuls · YouCham" in texte and "Infloww · YouL4b" not in texte, texte[:400])
check("note : CVR = subs ÷ clics du lien de suivi OnlyFans, lus chez Infloww (compte aileney)",
      "CVR = subs ÷ clics du lien de suivi OnlyFans, lus chez Infloww (compte aileney)" in texte
      and "CVR = subs ÷ clics US" not in texte and "CVR sur les clics MyPuls" not in texte, texte[-700:])
INFLOWW["erreur"] = "Infloww en panne"
t_p = m.tableau()
h_p = m.page({}, cle="CLE")
INFLOWW["erreur"] = ""
check("Infloww muet : CVR sur les clics MyPuls (3 ÷ 24), et la page le dit",
      abs({x["cle"]: x for x in t_p["lignes"]}["VA 1"]["cvr"] - 12.5) < 1e-9
      and "Infloww n'a pas répondu" in html.unescape(h_p) and "Infloww en panne" in h_p,
      {x["cle"]: x.get("cvr") for x in t_p["lignes"]})
check("vue des VA : ni paiement ni gain, aucun JavaScript",
      "Paiement" not in texte and "Gain" not in texte and "<script" not in h.lower())
check("tri sur les clics du lien de suivi (absent) : ramené au nom", m._tri_valide("clics", "desc") == ("nom", "asc"))

print("3. Clics US : toutes les heures")
n0 = len(APPELS_US)
m.tableau()
check("relevé de moins d'une heure : pas d'appel GetMySocial", len(APPELS_US) == n0, APPELS_US[n0:])
cache = m._us_cache()
vieux = {k: dict(v, essai=time.time() - 3700) for k, v in (cache.get("personnes") or {}).items()}
m.safe_json.write(m.US_FICHIER, dict(cache, personnes=vieux))
US["lnk_a"] = 55
t2 = m.tableau()
check("relevé de plus d'une heure : refait, la valeur neuve s'affiche",
      len(APPELS_US) == n0 + 4 and {x["cle"]: x for x in t2["lignes"]}["VA 1"]["us"] == 55, APPELS_US[n0:])
cache = m._us_cache()
p = dict(cache["personnes"])
p["VA 2"] = dict(p["VA 2"], rate="31/10 : panne", essai=time.time() - 120)
m.safe_json.write(m.US_FICHIER, dict(cache, personnes=p))
ents, _ = m.entites(LIENS)
check("relevé raté il y a 2 min : pas retenté avant US_REESSAI_S",
      "VA 2" not in m._a_mesurer(ents, m._us_cache(), m._aujourdhui(), time.time()))
cache = m._us_cache()
p = {k: dict(v, essai=time.time(), rate="") for k, v in (cache.get("personnes") or {}).items()}
p["VA 1"].pop("glob", None)
m.safe_json.write(m.US_FICHIER, dict(cache, personnes=p))
check("relevé du jour d'avant les clics globaux (sans « glob ») : refait, lui seul",
      m._a_mesurer(ents, m._us_cache(), m._aujourdhui(), time.time()) == ["VA 1"],
      m._a_mesurer(ents, m._us_cache(), m._aujourdhui(), time.time()))

print("4. Une période, la vue du propriétaire")
hp = m.page({"du": "2026-10-25", "au": "2026-10-31"}, cle="CLE", paie=False)
tp = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", hp, flags=re.S))))
check("période : mêmes colonnes, CVR sur les clics OnlyFans, liens du groupe",
      "Clics MyPuls" not in tp.replace(" ", " ") and "CVR = subs ÷ clics OnlyFans du lien de suivi" in tp
      and "du groupe « YouCham »" in tp, tp[:600])
import datetime as _dtl                 # noqa: E402
_hier = (_dtl.date.fromisoformat(AUJ) - _dtl.timedelta(days=1)).isoformat()
_t_ouv = {x["cle"]: x for x in m.tableau_periode("2026-10-20", AUJ, us="cache")["lignes"]}
check("période, lien créé pendant : part de 0, jusqu'au cumul d'aujourd'hui (49 ; 3 ÷ 49)",
      _t_ouv["VA 1"].get("clics_cvr") == 49 and abs(_t_ouv["VA 1"]["cvr"] - 300.0 / 49) < 1e-9, _t_ouv["VA 1"])
# un lien créé AVANT la période : cumul de la fin moins celui de la veille du début
INFLOWW["liens"] = [dict(x, cree="2026-10-01") for x in INFLOWW["liens"]]
_r = m._lire_json(m.RELEVES_CVR_FICHIER)
_r["jours"]["2026-10-24"] = {"115": 30, "113": 1, "112": 2}
_r["jours"][_hier] = {"115": 45, "113": 1, "112": 7}
m.safe_json.write(m.RELEVES_CVR_FICHIER, _r)
_t_b = {x["cle"]: x for x in m.tableau_periode("2026-10-25", AUJ, us="cache")["lignes"]}
check("période, lien créé avant : 49 aujourd'hui − 30 la veille du début = 19 (CVR 3 ÷ 19)",
      _t_b["VA 1"].get("clics_cvr") == 19 and abs(_t_b["VA 1"]["cvr"] - 300.0 / 19) < 1e-9
      and _t_b["VA 3"].get("clics_cvr") == 6, (_t_b["VA 1"].get("clics_cvr"), _t_b["VA 3"].get("clics_cvr")))
_t_close = m.tableau_periode("2026-10-25", _hier, us="cache")
_t_cl = {x["cle"]: x for x in _t_close["lignes"]}
check("période close : le cumul vu le dernier jour (45) − la veille du début (30) = 15",
      _t_cl["VA 1"].get("clics_cvr") == 15 and abs(_t_cl["VA 1"]["cvr"] - 20.0) < 1e-9, _t_cl["VA 1"])
_t_sans = m.tableau_periode("2026-10-27", AUJ, us="cache")
_t_s = {x["cle"]: x for x in _t_sans["lignes"]}
check("sans relevé de la veille : « — », CVR sur les clics MyPuls de la période (3 ÷ 24), et c'est dit",
      not _t_s["VA 1"].get("cvr_infloww") and abs(_t_s["VA 1"]["cvr"] - 12.5) < 1e-9
      and _t_sans["totaux"].get("clics_cvr") is None
      and "CVR sur les clics MyPuls" in html.unescape(m.page_html(_t_sans)), _t_s["VA 1"])
_t_apres = {x["cle"]: x for x in m.tableau_periode("2026-09-01", "2026-09-30", us="cache")["lignes"]}
check("période d'avant la création du lien : 0 clic Infloww", _t_apres["VA 1"].get("clics_cvr") == 0,
      _t_apres["VA 1"].get("clics_cvr"))
INFLOWW["liens"] = [dict(x, cree=AUJ) for x in INFLOWW["liens"]]
m.taux_eur_usd = lambda maintenant=None: {"taux": 1.08}
ho = m.page({}, cle="CLE", paie=True)
check("propriétaire : Paiement et Gain / perte, colonne Clics Infloww, pas de Clics MyPuls",
      ">Paiement<" in ho and "Clics\u00a0MyPuls" not in ho and "Clics\u00a0Infloww" in ho)

print("5. La paie : 0,70 $ par sub, tout le temps")
check("paie de la page : au sub, 0,70 $ quel que soit le nombre, depuis le 31/10, un réglage valide",
      m.PAIE_PAGE == m.valider_paie(m.PAIE_PAGE)[0] and m.PAIE_PAGE["type"] == "au_sub"
      and m.cout_au_sub(m.PAIE_PAGE, 250)[0] == 175.0 and m.PAIE_PAGE["depuis"] == "2026-10-31")
check("Jessye et Emy : aucune paie imposée", il.PAIE_PAGE is None and il.profil("emy").PAIE_PAGE is None)
pa = {x["cle"]: x for x in m.avec_paie(m.tableau(), attente=10)["lignes"]}
check("VA sans réglage : « 0,70 $ / sub » (un seul prix, pas « jusqu'à 0 »)",
      all(pa[n]["paie"]["resume"] == "0,70\u00a0$ / sub" for n in ("VA 1", "VA 2", "VA 3")),
      [pa[n]["paie"]["resume"] for n in pa])
check("VA 1 : 3 subs × 0,70 = 2,10 $ payés, 12,50 $ rapportés, gain +10,40 $",
      pa["VA 1"]["paie"].get("cout") == 2.1 and pa["VA 1"]["paie"].get("revenu") == 12.5
      and abs((pa["VA 1"].get("gain") or 0) - 10.4) < 1e-9, pa["VA 1"]["paie"])
check("VA 2 : 1 sub, rien rapporté : -0,70 $", abs((pa["VA 2"].get("gain") or 0) + 0.7) < 1e-9, pa["VA 2"].get("gain"))
m.safe_json.write(m.PAIE_FICHIER, {"personnes": {"VA 2": {"type": "aucun", "montant": 0, "devise": "USD",
                                                       "frequence": "quinzaine"}}})
pa = {x["cle"]: x for x in m.avec_paie(m.tableau(), attente=10)["lignes"]}
check("un réglage enregistré passe devant (VA 2 « Aucun »), les autres gardent 0,70 $",
      pa["VA 2"]["paie"]["cfg"]["type"] == "aucun" and pa["VA 1"]["paie"]["cfg"]["type"] == "au_sub",
      pa["VA 2"]["paie"]["cfg"])

print("6. L'image de la quinzaine (📊・click-et-sub)")
import asyncio                          # noqa: E402
import io as _io                        # noqa: E402
import types as _types                  # noqa: E402

from PIL import Image as _Image         # noqa: E402

import liens_image as li                # noqa: E402
import outils_communs as oc             # noqa: E402
_tq = m.tableau_periode("2026-10-16", "2026-10-31", us="cache")
v = li.tableau(_tq, "2026-10-16", "2026-10-31", "19h00", nom="Lia")
rangs = {x["cle"]: x["rang"] for x in v["lignes"]}
check("image : triée par subs, rangs 1, 2 ; ni rang à zéro sub et zéro clic, ni sur des subs inconnus",
      [x["cle"] for x in v["lignes"]][:2] == ["VA 1", "VA 2"] and rangs["VA 1"] == 1 and rangs["VA 2"] == 2
      and rangs["VA 4"] == 0, rangs)
_p1 = {x["cle"]: x for x in _tq["lignes"]}["VA 1"]
_i1 = {x["cle"]: x for x in v["lignes"]}["VA 1"]
check("image : les chiffres de la page, pas recalculés (CVR, $ / sub, couleurs)",
      _i1["cvr"] == _p1["cvr"] and _i1["par_sub"] == _p1["par_sub"]
      and _i1["niv_cvr"] == m.niveau(_p1["cvr"], m.SEUIL_CVR) and _i1["nom"] == "@roucham_79944"
      and _i1["sous"] == "VA 1 · c115", _i1)
check("image : jamais le net ni la paie", not any(k in str(v) for k in ("'net'", "paie", "gain")))
png = li.dessiner(v)
_im = _Image.open(_io.BytesIO(png))
check("image : un PNG de 1400 px de large (six colonnes de chiffres)",
      png[:8] == b"\x89PNG\r\n\x1a\n" and _im.size[0] == li.LARGEUR == 1400, _im.size)
check("image : la colonne Clics Infloww (ceux de la page)",
      {x["cle"]: x for x in v["lignes"]}["VA 1"]["inf"] == {x["cle"]: x for x in _tq["lignes"]}["VA 1"].get("clics_cvr"))
check("image : vide, elle se dessine quand même (le message de la page)",
      li.dessiner(li.tableau({"lignes": [], "totaux": {}, "erreur": "MyPuls muet"}, "2026-10-16", "2026-10-31"))[:4]
      == b"\x89PNG")
import cogs.sessionsvoc as _svc        # noqa: E402
_photo = _io.BytesIO()
_Image.new("RGB", (64, 64), (200, 30, 30)).save(_photo, "PNG")
_vues_ph = []


async def _fausses_photos(bot, ids, **kw):
    _vues_ph.append(list(ids))
    return {i: _photo.getvalue() for i in ids}, {}
_svc_sauve, _svc.photos_avatars = _svc.photos_avatars, _fausses_photos
_il_sauve = il.profil
il.profil = lambda nom: m if str(nom or "").lower() == "lia" else _il_sauve(nom)
try:
    _g = _types.SimpleNamespace(id=1565640097146347533, members=[
        _types.SimpleNamespace(name="roucham_79944", id=111, bot=False),
        _types.SimpleNamespace(name="bilal082598", id=222, bot=False)])
    im = asyncio.run(oc.image_clics(_g, _types.SimpleNamespace()))
finally:
    il.profil, _svc.photos_avatars = _il_sauve, _svc_sauve
check("salon : image de la quinzaine EN COURS (du 1er ou du 16 à aujourd'hui), photos des VA par leur pseudo",
      im.get("png", b"")[:4] == b"\x89PNG" and _vues_ph == [["111", "222"]]
      and MYPULS_LU[-1] == (m.quinzaine_de(_dt_auj())[0].isoformat(), m._aujourdhui()),
      (im.get("erreur"), _vues_ph, MYPULS_LU[-2:]))

print("7. La route")
import web_upload as wu      # noqa: E402
app = wu.create_app()
app.config["TESTING"] = True
c = app.test_client()
_sauve = il.profil
il.profil = lambda nom: m if str(nom or "").lower() == "lia" else _sauve(nom)
try:
    bonne = m.cle_page()
    r = c.get(f"/infloww/liens?k={bonne}&c=lia")
    corps = r.get_data(as_text=True)
    check("route ?c=lia avec la clé des VA : 200, la page Lia",
          r.status_code == 200 and "Liens de suivi · Lia" in corps and "VA 1" in corps, r.status_code)
    check("route : sans paiement ni gain pour la clé des VA", ">Paiement<" not in corps)
    check("route : clé fausse refusée", c.get("/infloww/liens?k=FAUSSE&c=lia").status_code == 403)
    r = c.get("/infloww/liens?c=lia")
    libre = r.get_data(as_text=True)
    check("accès libre : sans clé ni compte, 200, la page Lia, ni paiement ni gain",
          r.status_code == 200 and "Liens de suivi · Lia" in libre and ">Paiement<" not in libre
          and "Gain" not in libre and "Votre lien personnel" not in libre, r.status_code)
    check("accès libre : les liens de tri et de période restent sans clé",
          "k=" not in "".join(re.findall(r'href="([^"]*)"', libre)), re.findall(r'href="([^"]*)"', libre)[:5])
    r_e = c.get("/infloww/liens?c=emy")
    check("page Emy sans clé ni compte : toujours fermée (renvoi à l'accueil)",
          r_e.status_code in (301, 302, 303) and "Liens de suivi" not in r_e.get_data(as_text=True), r_e.status_code)
    with c.session_transaction() as s_:
        s_["auth"], s_["username"], s_["role"] = True, "admin", "admin"
    r_a = c.get("/infloww/liens?c=lia").get_data(as_text=True)
    check("admin connecté, sans clé : sa vue, paiement compris", ">Paiement<" in r_a)
    # le patch du VPS (hors git) qui ajoute « 🤝 Affiliations » remplace la
    # balise <body> exacte de la vue du propriétaire
    nav = '<body><nav style="padding:16px"><a href="/affiliations">🤝 Affiliations · Vue globale</a></nav>'
    check("Lia : le lien « Affiliations » du patch VPS n'entre pas (31/10 : « rien à faire là »)",
          "<body>" not in r_a and "Affiliations" not in r_a.replace("<body>", nav, 1)
          and "<body" in r_a, r_a[:200])
    _e_ = il.profil("emy")
    check("Emy et Jessye : la balise <body> exacte reste, le lien du patch y entre",
          all("<body>" in p_.page_html(p_._vide("x")) for p_ in (il, _e_)))
finally:
    il.profil = _sauve

print("8. Isolation")
check("rien écrit ni modifié dans le vrai data/ (fichiers de la page)", _instantane() == AVANT,
      set(_instantane().items()) ^ set(AVANT.items()))

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
