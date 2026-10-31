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
  - colonnes : Personne, Clics US, Subs, CVR, $ / sub — pas de clics du lien
    de suivi ; CVR = subs ÷ clics US, au total sur les seules lignes dont subs
    ET clics US sont connus ;
  - les autres liens de suivi de Lia (Twitter, Threads, Agency) sont comptés,
    pas listés : ni leur nom ni leurs chiffres sur la page ;
  - clics US relevés toutes les heures (liens neufs), un raté retenté après
    US_REESSAI_S ;
  - fichiers à elle (clics US, paie, copie GMS), la page Jessye et la page Emy
    ne changent pas ;
  - la route : clé des VA exigée, ni paiement ni gain, aucun JavaScript.

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
            "LIGNES_FICHIER", "ETAT_FICHIER", "CLE_FICHIER", "CLE_PAIE_FICHIER", "BCE_FICHIER")

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
check("le lien des VA porte c=lia (et la clé des VA)", m.url_page().endswith("&c=lia")
      if m.CLE_FICHIER.exists() else True)
for _k in FICHIERS:
    setattr(m, _k, TMP / (_k.lower() + ".json"))
m.US_EN_FOND = False
m._lire_mypuls_api = _mypuls

print("2. La page, depuis toujours")
h = m.page({}, cle="CLE", paie=False)
texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", h, flags=re.S))))
t = m.tableau()
lignes = {x["nom"]: x for x in t["lignes"]}
check("liste GMS : le groupe YouCham, aucune équipe", GROUPES_LUS and set(GROUPES_LUS) == {GROUPE}, GROUPES_LUS)
check("MyPuls lu depuis le premier jour jusqu'à aujourd'hui",
      MYPULS_LU and MYPULS_LU[0] == (il.PLANCHER.isoformat(), m._aujourdhui()), MYPULS_LU)
check("une personne par lien du groupe : VA 1..VA 4", sorted(lignes) == ["VA 1", "VA 2", "VA 3", "VA 4"],
      sorted(lignes))
entetes = re.findall(r"<th[^>]*>(?:<a[^>]*>)?([^<]+)", h)
check("colonnes : Personne, Clics US, Subs, CVR, $ / sub — rien d'autre",
      [e.replace(" ", " ").rstrip(" ▴▾") for e in entetes] == ["Personne", "Clics US", "Subs", "CVR", "$ / sub"],
      entetes)
check("aucune colonne « Clics MyPuls » ni « Clics Infloww »",
      "Clics MyPuls" not in texte.replace(" ", " ") and "Clics Infloww" not in texte.replace(" ", " "))
va1 = lignes["VA 1"]
check("VA 1 : 40 clics US, 3 subs, CVR 7,5 % (subs ÷ US), 4,17 $ / sub",
      va1["us"] == 40 and va1["subs"] == 3 and abs(va1["cvr"] - 7.5) < 1e-9
      and abs(va1["par_sub"] - 12.5 / 3) < 1e-9, va1)
check("VA 3 : 0 clic US, pas de CVR (et non 0 %)", lignes["VA 3"]["cvr"] is None, lignes["VA 3"])
check("VA 4 : lien de suivi introuvable chez MyPuls, dit, pas de zéro inventé",
      lignes["VA 4"]["subs"] is None and lignes["VA 4"]["introuvables"], lignes["VA 4"])
T = t["totaux"]
check("total : CVR sur les seules lignes dont subs ET US sont connus (4 ÷ 52, pas 4 ÷ 82)",
      T["us"] == 82 and abs(T["cvr"] - 4 * 100.0 / 52) < 1e-9, T)
check("le lien de suivi Twitter de Lia : compté hors YouCham, ni nom ni chiffres sur la page",
      "1 autre(s) lien(s) de suivi de Lia, hors « YouCham » : non comptés" in texte
      and "bid_a" not in h and "900" not in texte, texte[-600:])
check("autre créatrice : ignorée", "Emy VA" not in h)
check("en-tête : « Depuis toujours · MyPuls · @liasxcret · GetMySocial « YouCham » », marque MyPuls · YouCham",
      "Depuis toujours · MyPuls · @liasxcret · GetMySocial « YouCham »" in texte
      and "MyPuls · YouCham" in texte and "Infloww · YouL4b" not in texte, texte[:400])
check("note : CVR = subs ÷ clics US", "CVR = subs ÷ clics US" in texte)
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
      len(APPELS_US) == n0 + 4 and {x["nom"]: x for x in t2["lignes"]}["VA 1"]["us"] == 55, APPELS_US[n0:])
cache = m._us_cache()
p = dict(cache["personnes"])
p["VA 2"] = dict(p["VA 2"], rate="31/10 : panne", essai=time.time() - 120)
m.safe_json.write(m.US_FICHIER, dict(cache, personnes=p))
ents, _ = m.entites(LIENS)
check("relevé raté il y a 2 min : pas retenté avant US_REESSAI_S",
      "VA 2" not in m._a_mesurer(ents, m._us_cache(), m._aujourdhui(), time.time()))

print("4. Une période, la vue du propriétaire")
hp = m.page({"du": "2026-10-25", "au": "2026-10-31"}, cle="CLE", paie=False)
tp = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", hp, flags=re.S))))
check("période : mêmes colonnes, CVR sur les clics US, liens du groupe",
      "Clics MyPuls" not in tp.replace(" ", " ") and "CVR = subs ÷ clics US" in tp
      and "du groupe « YouCham »" in tp, tp[:600])
m.taux_eur_usd = lambda maintenant=None: {"taux": 1.08}
ho = m.page({}, cle="CLE", paie=True)
check("propriétaire : Paiement et Gain / perte, sans colonne de clics OF",
      ">Paiement<" in ho and "Clics MyPuls" not in ho and "Clics Infloww" not in ho)

print("5. La route")
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
finally:
    il.profil = _sauve

print("6. Isolation")
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
