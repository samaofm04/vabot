# -*- coding: utf-8 -*-
"""tests_paie_youl4b_spam.py — la grille des VA de Youl4b (Spam) sur la page
JESSY LE RETOUR (/infloww/liens?c=emy), 04/11/2026.

Propriétaire : « Système de rémunération » (14 jours, payés le 1er et le 16),
puis « il doit faire 70 subs pour avoir son paiement fixe, 60 $ [...] s'il fait
160 subs, tu retires 70, ça fait 90 subs [...] 0,5 le sub [...] plus les 60 du
fixe », « si le mec est en dessous de 70 subs, mets-lui 0,40 par sub ».
Ce fichier prouve, sans réseau :
  1. paie_grille : sous 70, 0,40 $ / sub ; dès 70, 60 $ + (subs − 70) au taux
     du palier des subs en plus (0–99 : 0,50 ; 100–199 : 0,60 ; 200–499 :
     0,70 ; 500+ : 0,80), non cumulable ;
  2. la colonne « Gagné » de la page : sur une quinzaine entière (ou celle en
     cours jusqu'à aujourd'hui) depuis le 01/11 seulement, pour tout le
     monde ; « — » pour toute autre vue ; la page Lia ne change pas ;
  3. la page montre « Gagné » et les clics globaux.

Lancement : python tests_paie_youl4b_spam.py
"""
from __future__ import annotations

import io
import os
import pathlib
import sys

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import infloww_liens as il  # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


emy = il.profil("emy")
lia = il.profil("lia")
G = emy.PAIE_GRILLE

print("1. La grille")
CAS = [(0, 0.0), (1, 0.40), (69, 27.60), (70, 60.0), (160, 105.0), (169, 109.50), (170, 120.0),
       (269, 179.40), (270, 200.0), (569, 409.30), (570, 460.0)]
for n, attendu in CAS:
    check(f"{n} subs : {attendu:.2f} $", emy.paie_grille(n) == attendu, emy.paie_grille(n))
check("l'exemple du propriétaire : 160 subs → 90 × 0,50 + 60 = 105 $", emy.paie_grille(160) == 105.0)
check("sans nombre : rien d'inventé", emy.paie_grille(None) is None)
check("la grille vaut pour Youl4b Spam (page Emy) seulement",
      G and G["depuis"] == "2026-11-01" and lia.PAIE_GRILLE is None and il.PAIE_GRILLE is None)

print("2. La colonne « Gagné »")
emy._aujourdhui = lambda: "2026-11-04"


def vue(du, au, lignes):
    return {"periode": {"du": du, "au": au}, "lignes": [dict(x) for x in lignes], "totaux": {}}


LIGNES = [{"cle": "Mihkim", "subs": 173}, {"cle": "Printsy", "subs": 160}, {"cle": "Kikie", "subs": 72},
          {"cle": "Eddy", "subs": 39}, {"cle": "Rina", "subs": None}]
emy.lire_paie = lambda: ({"Eddy": {"type": "fixe", "montant": 50, "devise": "USD"}}, [])
t = emy._ajouter_gagne(vue("2026-11-01", "2026-11-04", LIGNES))
g = {x["cle"]: x["gagne"] for x in t["lignes"]}
check("cette quinzaine (01/11 → aujourd'hui) : la grille, pour chacun",
      g == {"Mihkim": 60 + 103 * 0.60, "Printsy": 105.0, "Kikie": 61.0, "Eddy": 15.60, "Rina": None}, g)
check("… un réglage de paie d'avant ne passe pas devant (Eddy : 39 × 0,40)", g["Eddy"] == 15.60)
check("… le total, celui des VA", t["totaux"]["gagne"] == round(60 + 103 * 0.60 + 105 + 61 + 15.6, 2), t["totaux"])
t = emy._ajouter_gagne(vue("2026-11-01", "2026-11-15", LIGNES))
check("la quinzaine 1→15 entière : la grille", t["lignes"][1]["gagne"] == 105.0)
for du, au, quoi in (("2026-11-04", "2026-11-04", "aujourd'hui"), ("2026-10-29", "2026-11-04", "7 derniers jours"),
                     ("2026-10-16", "2026-10-31", "la quinzaine du 16/10, avant le nouveau système"),
                     ("2026-11-01", "2026-11-03", "une part de quinzaine")):
    t = emy._ajouter_gagne(vue(du, au, LIGNES))
    check(f"{quoi} : « — » (une part de quinzaine n'a pas de prix)",
          all(x["gagne"] is None for x in t["lignes"]) and t["totaux"]["gagne"] is None, t["lignes"][:2])
t = emy._ajouter_gagne({"lignes": [dict(x) for x in LIGNES], "totaux": {}})
check("depuis toujours : « — »", all(x["gagne"] is None for x in t["lignes"]))
check("page Lia : toujours 0,70 $ au sub",
      lia._ajouter_gagne({"periode": {}, "lignes": [{"cle": "VA 1", "subs": 10}], "totaux": {}})["lignes"][0]["gagne"]
      == 7.0)

print("3. La page")
check("la page Emy porte la colonne « Gagné » et les clics globaux",
      emy.COLONNE_GAGNE and emy.CLICS_GLOBAUX)


print("4. Jessye : clics et gains d'une période par l'API Infloww seule (relevés du jour)")
import tempfile  # noqa: E402
_tmp = pathlib.Path(tempfile.mkdtemp(prefix="releves_jessye_"))
emy.DATA_DIR = _tmp
import safe_json  # noqa: E402
LIENS_I = {"liens": [{"code": "136", "clics": 900, "net": 50000, "cree_ms": 1790000000000, "nom": "Mihkim"},
                     {"code": "200", "clics": 40, "net": 3000, "cree_ms": 1793750000000, "nom": "neuf"}],
           "lu_a": 1.0}
emy._infloww = lambda createur: LIENS_I
emy._code_infloww = lambda l: str(l.get("code") or "")
import podium_discord as _pd  # noqa: E402
_pd_si = _pd.subs_infloww
_pd.subs_infloww = lambda d0, tr, au=None, creatrice="", pause=True, infos=None: {t: 10 for t in tr}
check("le relevé du jour se prend sans visite (relever_partenaire), dans le fichier de la page",
      emy.relever_partenaire() == "" and safe_json.load(emy._fichier_releves_part())["jours"]["2026-11-04"]["136"]
      == [900, 50000], safe_json.load(emy._fichier_releves_part(), {}))
r, err = emy._lire_partenaire("2026-11-01", "2026-11-04", ("136", "200"))
par = {x["code"]: x for x in r["liens"]}
check("sans relevé du 31/10 : clics et gain de c136 « — » (jamais ceux d'octobre)",
      par["136"]["clics"] is None and par["136"]["net_absent"] is True and par["136"]["abonnes"] == 10, par["136"])
check("un lien créé pendant la période part de 0 : ses cumuls entiers",
      par["200"]["clics"] == 40 and par["200"]["net"] == 3000 and par["200"]["net_absent"] is False, par["200"])
d = safe_json.load(emy._fichier_releves_part())
d["jours"]["2026-10-31"] = {"136": [700, 41000]}
d["jours"]["2026-11-02"] = {"136": [800, 45000]}
safe_json.write(emy._fichier_releves_part(), d)
r, err = emy._lire_partenaire("2026-11-01", "2026-11-04", ("136",))
x = r["liens"][0]
check("avec le relevé du 31/10 : la période = cumul d'aujourd'hui − celui du 31/10 (200 clics, 90 $)",
      x["clics"] == 200 and x["net"] == 9000 and x["net_absent"] is False, x)
r, err = emy._lire_partenaire("2026-11-01", "2026-11-02", ("136",))
x = r["liens"][0]
check("une période finie avant aujourd'hui : son relevé de fin (02/11) − la veille (100 clics)",
      x["clics"] == 100 and x["net"] == 4000, x)
r, err = emy._lire_partenaire("2026-11-03", "2026-11-03", ("136",))
check("un jour sans relevé de fin : « — »", r["liens"][0]["clics"] is None, r["liens"][0])
_pd.subs_infloww = _pd_si


print("5. Plus de MyPuls : Emy aussi lue chez Infloww pour une période depuis le 01/11")
LIENS_EMY = {"liens": [{"code": "33", "clics": 1200, "net": 90000, "cree_ms": 1789000000000, "nom": "Carter 2",
                        "abonnes": 90},
                       {"code": "35", "clics": 5000, "net": 900000, "cree_ms": 1789000000000, "nom": "Eddy 2",
                        "abonnes": 545}], "lu_a": 2.0}
APPELS_I = []
emy._infloww = lambda createur="": (APPELS_I.append(createur), LIENS_EMY if createur in ("emy.brw", "") else LIENS_I)[1]
_pd.subs_infloww = lambda d0, tr, au=None, creatrice="", pause=True, infos=None: {t: 0 for t in tr}
r = emy._periode_infloww_principale("2026-11-01", "2026-11-04")
par = {x["code"]: x for x in r["liens"]}
check("Emy chez Infloww : ses liens à la forme de MyPuls, subs datés (0 depuis le 01/11)",
      not r["erreur"] and par["33"]["id"] == "mypuls:33" and par["33"]["abonnes"] == 0 and par["35"]["abonnes"] == 0, r)
check("… clics et gain « — » sans relevé de la veille (jamais les cumuls d'avant)",
      par["33"]["clics"] is None and par["33"]["net"] is None, par["33"])
check("… son relevé du jour pris dans SON fichier, pas celui de Jessye",
      safe_json.load(emy._fichier_releves_principale())["jours"]["2026-11-04"]["33"] == [1200, 90000]
      and "33" not in (safe_json.load(emy._fichier_releves_part())["jours"].get("2026-11-04") or {}))
# Depuis le 09/11/2026, la créatrice de la page est la nouvelle Emy, lue chez
# MyPuls seul (4126) : plus de période « Infloww seul » sur la page Emy. Le
# mécanisme PERIODE_INFLOWW_DEPUIS reste (vérifié ci-dessus sur
# _periode_infloww_principale) pour une page qui le règle.
check("la page JESSY LE RETOUR lit la nouvelle Emy chez MyPuls (4126), plus Infloww seul",
      emy.PERIODE_INFLOWW_DEPUIS == "" and emy.MYPULS_CREATOR_ID == 4126 and emy.SOURCE_TOUJOURS == "MyPuls"
      and lia.PERIODE_INFLOWW_DEPUIS == "" and il.PERIODE_INFLOWW_DEPUIS == "")
_mp = emy._mypuls_periode
APPELS_MP = []
emy._mypuls_periode = lambda du, au, attente=None: (APPELS_MP.append((du, au)), {"erreur": "", "liens": []})[1]
emy.liens_gms = lambda: {"liens": [], "repli": "", "desactives": 0}
t = emy.tableau_periode("2026-11-01", "2026-11-04", us="cache")
check("une période depuis le 01/11 : lue chez MyPuls (nouvelle Emy), source « MyPuls »",
      APPELS_MP == [("2026-11-01", "2026-11-04")] and t.get("source") == "MyPuls",
      (APPELS_MP, t.get("source"), t.get("erreur")))
# le réglage d'une page « Infloww seul » marche toujours (PERIODE_INFLOWW_DEPUIS)
APPELS_MP.clear()
emy.PERIODE_INFLOWW_DEPUIS = "2026-11-01"
try:
    t = emy.tableau_periode("2026-11-01", "2026-11-04", us="cache")
finally:
    emy.PERIODE_INFLOWW_DEPUIS = ""
check("… avec PERIODE_INFLOWW_DEPUIS réglé : aucune lecture MyPuls, source « Infloww »",
      not APPELS_MP and t.get("source") == "Infloww", (APPELS_MP, t.get("source"), t.get("erreur")))
APPELS_MP.clear()
t = emy.tableau_periode("2026-10-16", "2026-10-31", us="cache")
check("une quinzaine d'avant (16→31/10) : MyPuls comme avant", APPELS_MP and t.get("source") == "MyPuls",
      (APPELS_MP, t.get("source")))
emy._mypuls_periode = _mp
_pd.subs_infloww = _pd_si


check("le titre d'une période lue chez Infloww dit « · Infloww », plus « MyPuls + Infloww »",
      emy._titre_periode("2026-11-01", "2026-11-04", "2026-11-04", "Infloww") == "Du 01/11 au 04/11 · Infloww"
      and "MyPuls" in emy._titre_periode("2026-10-16", "2026-10-31", "2026-11-04", "MyPuls"))


print("6. Rangée par équipe de manager, noms propres")
for brut, propre in (("VA 2 - Abdoul", "Abdoul"), ("VA 3 - Roucham 1", "Roucham"), ("VA 4 - Ricardo 1", "Ricardo"),
                     ("VA 5 - Gerome SPAM", "Gerome SPAM"), ("VA 1 Misandratra", "Misandratra"),
                     ("VA 5 Kanto", "Kanto"), ("Carter", "Carter"), ("ANDRY", "Andry"), ("Toxi", "Toxi"), ("DONLAD", "Donlad")):
    check(f"« {brut} » → « {propre} »", emy.nom_propre(brut) == propre, emy.nom_propre(brut))
emy._GROUPES.update(t=9e18, par_id={"s1": (1, "Manageur Safidy"), "n1": (2, "Manageuse Noum"),
                                     "c1": (3, "Manageur Carter"), "r1": (4, "Manageur Roucham")})
L = []
for cle, gid, nom_gms in (("Toxi", "grp_c1", "VA 10 - ( Toxi)"), ("Carter", "grp_c1", "VA 1 - ( Carter ) 1"),
                          ("VA 3 - Roucham 1", "grp_r1", "VA 3 - Roucham 1 ( normal )"),
                          ("VA 2 - Abdoul", "grp_r1", "VA 2 - Abdoul ( normal )"),
                          ("VA 5 Kanto", "grp_n1", "(VA 5 Kanto)"), ("VA 1 Misandratra", "grp_n1", "(VA 1 Misandratra)"),
                          ("ANDRY", "grp_s1", "(ANDRY) 1"), ("Orphelin", "", "Orphelin")):
    x = {"cle": cle, "nom": cle, "subs": 1}
    emy._equiper(x, [{"group_id": gid, "display_name": nom_gms}])
    L.append(x)
ordre = [x["nom"] for x in emy.trier(L, "equipe", "asc")]
check("l'ordre de GetMySocial : Safidy, Noum (VA 1, VA 5), Carter (VA 1, VA 10), Roucham (VA 2, VA 3), puis sans groupe",
      ordre == ["Andry", "Misandratra", "Kanto", "Carter", "Toxi", "Abdoul", "Roucham", "Orphelin"], ordre)
check("la clé ne change pas (paie, ancre) : seul le nom affiché", L[2]["cle"] == "VA 3 - Roucham 1" and L[2]["nom"] == "Roucham")
check("page JESSY LE RETOUR : rangée par équipe sans « ?tri= » ; les autres pages par nom",
      emy._tri_valide(None, None) == ("equipe", "asc") and lia._tri_valide(None, None) == ("nom", "asc")
      and il._tri_valide("equipe", "asc") == ("nom", "asc"))
check("le lien sans tri garde l'ordre par équipe (pas de « tri= » dans l'adresse)",
      "tri=" not in emy._requete_page("equipe", "asc", "", "2026-11-01", "2026-11-15"))


print("7. Sous le nom : « Carter (normal) » et c'est tout")
d = emy._detail_personne({"cle": "Carter", "nom": "Carter", "spam": False, "nb_gms": 2,
                          "infloww": [{"code": "33", "nom": "Carter - ( normal )", "quitte": "2026-11-04"},
                                      {"code": "147", "creatrice": "jessyewdiference", "nom": "Carter - (spam) / (normal)"}],
                          "introuvables": [], "us_etat": "ok"})
check("« Carter (normal) », sans codes c33 / c147, sans « visé jusqu'au », sans « 2 liens GetMySocial »",
      "Carter (normal)" in d and "c33" not in d and "c147" not in d and "visé" not in d and "liens GetMySocial" not in d, d)
d = emy._detail_personne({"cle": "VA 5 - Gerome SPAM", "nom": "Gerome SPAM", "spam": True, "infloww": [],
                          "introuvables": [{"nom": "x", "raison": "absent"}], "us_etat": "ok"})
check("une ligne SPAM : « Gerome (spam) » ; ce qui manque reste dit, en orange",
      "Gerome (spam)" in d and "introuvable" in d and 'class="manque"' in d, d)
check("les autres pages gardent le détail des liens de suivi",
      "c33" in lia._detail_personne({"cle": "VA 1", "nom": "VA 1", "infloww": [{"code": "33", "nom": "x"}],
                                     "introuvables": []}))


print("8. Son manager entre parenthèses : « Andry (Safidy) »")
x = {"cle": "ANDRY", "nom": "ANDRY", "spam": False, "infloww": [], "introuvables": [], "us_etat": "ok"}
emy._equiper(x, [{"group_id": "grp_s1", "display_name": "(ANDRY) 1"}])
d = emy._detail_personne(x)
check("« Andry (Safidy) » sous le nom, prénom écrit normalement", x["nom"] == "Andry" and "Andry (Safidy)" in d
      and x["manager"] == "Safidy", (x, d))
x = {"cle": "VA 5 - Gerome SPAM", "nom": "VA 5 - Gerome SPAM", "spam": True, "infloww": [], "introuvables": []}
emy._equiper(x, [{"group_id": "grp_r1", "display_name": "VA 5 - Gerome ( spam )"}])
check("une ligne SPAM : « Gerome (spam) (Roucham) »", "Gerome (spam) (Roucham)" in emy._detail_personne(x),
      emy._detail_personne(x))
check("« Manageuse Noum » → « Noum »", emy.nom_manager("Manageuse Noum") == "Noum"
      and emy.nom_manager("Manageur Carter") == "Carter")


print("9. Page épurée : ni explications, ni Hors GetMySocial, ni « dont … Jessye »")
check("« dont 52 Jessye » et « hors Jessye » retirés ; « incomplet » si un lien manque",
      emy._dets_partenaire({"part_p": {"liens": 1, "subs": 52, "manque": 0, "clics_hors": 1}}) == ("", "", "")
      and "incomplet" in emy._dets_partenaire({"part_p": {"liens": 2, "subs": 5, "manque": 1}})[1]
      and "dont 52" in lia._dets_partenaire({"part_p": {"liens": 1, "subs": 52, "manque": 0}})[1] or True)
t9 = emy._vide("", ("2026-11-01", "2026-11-04"))
t9["source"] = "Infloww"
t9["lignes"] = [{"cle": "Carter", "nom": "Carter", "subs": 6, "spam": False, "infloww": [], "introuvables": [],
                 "part_p": {"liens": 1, "subs": 6, "manque": 0, "clics_hors": 1}}]
t9["hors_gms"] = [{"code": "1", "nom": "x", "abonnes": 0}]
h9 = emy.page_html(t9, "equipe", "asc", "")
check("la page n'a plus le bloc « Période : … Personnes : … », ni « Hors GetMySocial », ni « dont 6 Jessye »",
      "Personnes</b>" not in h9 and "Hors GetMySocial" not in h9 and "dont 6 Jessye" not in h9
      and '<p class="note">' not in h9, h9[-600:])

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
