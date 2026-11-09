"""Page JESSY LE RETOUR (?c=emy) après la bascule du 09/11/2026.

Les 31 liens de l'équipe sont passés de Jessye (jessyewdiference/c132…c160) à
la NOUVELLE Emy (emy.brw/c1…c27, Infloww 2639487016566802). Propriétaire,
09/11 : « use que Infloww comme avant » et « tu additionnes là pour cette fois
les subs de Jessye, sinon Emy » : la nouvelle Emy chez Infloww (épinglée par
son id, l'ancienne y porte le même pseudo), plus la part Jessye des liens
basculés (BASCULE_PARTENAIRE, par id de lien) pour la quinzaine du 01 au 15/11
seulement.

Page RENDUE, hors ligne : GetMySocial, MyPuls, Infloww, registre du podium et
rattachements bouchés ; tous les fichiers de la page dans un dossier
temporaire ; data/ du dépôt n'est pas touché (vérifié à la fin).
"""
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import types

ICI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
os.environ["VABOT_BANC_ESSAI"] = "1"


def _instantane():
    d = ICI / "data"
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*") if p.is_file()} if d.is_dir() else {}


AVANT_DATA = _instantane()
OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


_SAUVE = {k: sys.modules.get(k) for k in ("gms", "mypuls")}
g = types.ModuleType("gms")
g.pause_restante = lambda: 0
g.etat_quota = lambda: {"pause_s": 0, "reprise": "", "restant_jour": None, "raison": ""}
g.list_team_groups = lambda equipe: {"groups": [{"id": "grp_c", "name": "Manageur Carter"},
                                                {"id": "grp_n", "name": "Manageuse Noum"},
                                                {"id": "grp_s", "name": "Manageur Safidy"}]}


def _interdit(*a, **k):
    raise RuntimeError("GetMySocial non bouché")


g.list_links_team = g.list_links_group = g.analytics_for_link = g.analytics_for_links = _interdit
g.get_analytics_overview = _interdit
sys.modules["gms"] = g
APPELS_MP = []
mp = types.ModuleType("mypuls")


def api_get(chemin, params=None, **k):
    APPELS_MP.append((chemin, params.get("from"), params.get("to")))
    return {"ok": True, "data": {"data": [], "count": 0, "period": {}, "currency": "USD"}}


mp.api_get = api_get
sys.modules["mypuls"] = mp

import clics_personnes as cp          # noqa: E402
import infloww_liens as il            # noqa: E402
import podium_discord as pd           # noqa: E402

# le module Infloww, par la page (tests_site veut que seuls quelques modules
# l'importent ; un test passe par celui qui s'en sert)
infloww = il.infloww

NOUV, ANC = "2639487016566802", "2513465915080717"
print("1. Infloww : deux créatrices « emy.brw », l'appelant choisit par l'id")
nouv = {"id": NOUV, "userName": "emy.brw", "name": "Emy"}
anc = {"id": ANC, "userName": "emy.brw", "name": "Emy finito"}
check("avec l'id de la nouvelle : elle, quel que soit l'ordre (casse ignorée)",
      infloww._choisir("emy.brw", [anc, nouv], NOUV) is nouv and infloww._choisir("Emy.Brw", [nouv, anc], NOUV) is nouv)
check("jamais l'ancienne à sa place, même seule", infloww._choisir("emy.brw", [anc], NOUV) is None)
check("sans id : la première rendue, comme avant (le podium ne change pas)",
      infloww._choisir("emy.brw", [anc, nouv]) is anc and infloww._choisir("emy.brw", [nouv, anc]) is nouv)
_cr = infloww.creatrices
infloww.creatrices = lambda: [anc]
try:
    infloww._creatrice_ou_erreur("emy.brw", NOUV)
    dit = ""
except infloww.ErreurInfloww as e:
    dit = str(e)
finally:
    infloww.creatrices = _cr
check("son absence est dite, avec son numéro", NOUV in dit, dit)

TMP = pathlib.Path(tempfile.mkdtemp(prefix="tests_emy_bascule_"))
em = il.profil("emy")
_pd_si, _pd_reg, _cp_ratt = pd.subs_infloww, pd._lire_registre, cp.rattachements_identite_ou_panne
try:
    em.DATA_DIR = TMP
    for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "US_FICHIER", "CLE_FICHIER", "CLE_PAIE_FICHIER",
              "US_PERIODES_FICHIER", "GMS_COPIE", "RELEVES_CVR_FICHIER", "PAIE_FICHIER", "QUINZ_FICHIER",
              "BCE_FICHIER", "LIGNES_FICHIER"):
        setattr(em, k, TMP / getattr(em, k).name)
    em.JETON_FICHIERS = (TMP / "absent",)
    em.GMS_CACHE = TMP / "gmsdash_links.json"
    em.QUINZ_EN_FOND = em.LIGNES_EN_FOND = em.US_EN_FOND = False
    em._dormir_q = lambda s: None
    AUJ = {"j": "2026-11-09"}
    em._aujourdhui = lambda: AUJ["j"]
    em._us_periode_pour_la_page = lambda ents, du, au: {}
    em._us_pour_la_page = lambda ents: None

    print("2. Réglages de la page")
    b = em.BASCULE_PARTENAIRE
    check("nouvelle Emy chez Infloww (par son id) depuis le 01/11, depuis toujours chez Infloww",
          em.CREATRICE == "emy.brw" and em.PERIODE_INFLOWW_DEPUIS == "2026-11-01" and em.INFLOWW_CREATOR_ID == NOUV
          and em.SOURCE_TOUJOURS == "Infloww" and em.ANCIENS_DEPUIS == "2026-11-09")
    check("relevés Infloww de la nouvelle Emy dans un fichier neuf (l'ancien mêlait les deux comptes)",
          em._fichier_releves_principale().name == "infloww_liens_releves_principale_emy_2639487016566802.json")
    check("table de bascule : les 31 liens par leur id, 25 codes Jessye, les 7 liens Andry sur c150",
          len(b) == 31 and all(k.startswith("lnk_") for k in b) and len(set(b.values())) == 25
          and list(b.values()).count("150") == 7 and b["lnk_6aba04fad38dbae582b4333e"] == "147", b)
    check("Jessye pour la quinzaine du 01 au 15/11 seulement", em.BASCULE_JUSQU_AU == "2026-11-15"
          and em._bascule_compte("2026-11-01") and not em._bascule_compte("2026-11-16") and em._bascule_compte(""))
    check("les quinzaines figées de l'ancienne Emy ne sont plus servies (fichier à part)",
          em.QUINZ_FICHIER.name == "infloww_liens_quinzaines_emy_4126.json")
    check("la page Jessye (sans c) n'a ni bascule, ni fichier à part, ni id imposé",
          il.BASCULE_PARTENAIRE == {} and il.RELEVES_PRINCIPALE_NOM == "" and il.BASCULE_JUSQU_AU == ""
          and il.INFLOWW_CREATOR_ID == "")

    E = "https://onlyfans.com/emy.brw/c"
    MI, A3, A4, CA = ("lnk_6ac45440dae3fc7e8312b918", "lnk_6ad868d11f59a2659b845ddb",
                      "lnk_6ad868d91f59a2659b845e22", "lnk_6aba04fad38dbae582b4333e")

    def lien(lid, nom, url, grp):
        return {"id": lid, "display_name": nom, "url": None, "url_boutons": [url], "status": "active",
                "group_id": grp}

    GMS = [lien(MI, "VA 1 - ( Misandratra )", E + "15", "grp_n"),
           lien(A3, "VA 4 - ( Andry ) 3", E + "27", "grp_s"),
           lien(A4, "VA 4 - ( Andry ) 4", E + "27", "grp_s"),
           lien(CA, "VA 1 - ( Carter )", E + "1", "grp_c")]
    em.liens_gms = lambda maintenant=None: {"liens": [dict(l) for l in GMS], "repli": "", "desactives": 0}
    check("_codes_partenaire : les codes Jessye des liens basculés, une fois chacun ; rien après le 15/11",
          em._codes_partenaire(GMS) == ["147", "150", "153"] and em._codes_partenaire(GMS, "2026-11-16") == [])

    CREE_J = int(time.mktime((2026, 10, 27, 17, 0, 0, 0, 0, -1)) * 1000)
    CREE_E = int(time.mktime((2026, 11, 9, 1, 10, 0, 0, 0, -1)) * 1000)
    APPELS_IFW = []

    _ifw = em.infloww._creatrice_ou_erreur
    VUS_IFW = []
    em.infloww._creatrice_ou_erreur = lambda p, vise=None: (VUS_IFW.append((p, vise)), ({"id": vise or "x"}, []))[1]

    def faux_infloww(creatrice=""):
        cr = creatrice or em.CREATRICE
        APPELS_IFW.append(cr)
        if cr == "jessyewdiference":
            return {"erreur": "", "lu_a": time.time(), "liens": [
                {"id": f"i{c}", "code": f"c{c}", "nom": "x", "clics": 900, "abonnes": 41, "net": 0,
                 "cree_ms": CREE_J, "devise": "USD"} for c in (153, 150, 147)]}
        if cr == "emy.brw":
            return {"erreur": "", "lu_a": time.time(), "liens": [
                {"id": f"e{c}", "code": f"c{c}", "nom": n, "clics": 10, "abonnes": 0, "net": 0,
                 "cree_ms": CREE_E, "devise": "USD"} for c, n in ((15, "VA 1 - ( Misandratra )"),
                                                                 (27, "VA 4 - ( Andry )"), (1, "VA 1 - ( Carter )"))]}
        raise RuntimeError(f"Infloww lu pour {cr}")

    em._infloww = faux_infloww
    SUBS = {"jessyewdiference/c153": 40, "jessyewdiference/c150": 90, "jessyewdiference/c147": 70,
            "emy.brw/c15": 3, "emy.brw/c27": 2, "emy.brw/c1": 1}
    APPELS_SUBS = []

    def faux_subs(jour, ts, au=None, creatrice="", pause=True, infos=None, vise=""):
        APPELS_SUBS.append((creatrice, jour, au, vise))
        if creatrice not in ("jessyewdiference", "emy.brw"):
            raise RuntimeError(f"Infloww lu pour {creatrice}")
        return {t: SUBS.get(t, 0) for t in ts}

    pd.subs_infloww = faux_subs
    # l'ANCIENNE Emy au registre (c33, Carter, quitté le 04/11) : plus comptée ici
    REG = {"trackings": {
        "emy.brw/c33": {"numero": 38, "liens": ["VA 1 - ( Carter )"], "ids": [CA],
                        "premier": "2026-10-05", "vu": "2026-11-04", "actif": False}}, "attente": {}}
    pd._lire_registre = lambda: REG
    cp.rattachements_identite_ou_panne = lambda: ({}, "")

    print("3. Quinzaine du 01 au 15/11 : nouvelle Emy + Jessye, tout chez Infloww")
    t = em.tableau_periode("2026-11-01", "2026-11-15", us="cache")
    par = {x["cle"]: x for x in t.get("lignes") or []}
    check("source Infloww, aucune erreur, aucune lecture MyPuls",
          t.get("source") == "Infloww" and not t.get("erreur") and not APPELS_MP,
          (t.get("source"), t.get("erreur"), APPELS_MP))
    check("Misandratra = 3 (Emy c15) + 40 (Jessye c153) = 43, Gagné 17,20 $ (sous 70 : 0,40 $)",
          par.get("Misandratra", {}).get("subs") == 43 and par["Misandratra"].get("gagne") == 17.2,
          par.get("Misandratra"))
    check("Andry : 2 liens sur c27 comptés une fois, + Jessye c150 = 92, Gagné 71,00 $",
          par.get("Andry", {}).get("subs") == 92 and par["Andry"].get("gagne") == 71.0, par.get("Andry"))
    check("Carter = 1 + 70 = 71, sans l'ancien c33 de l'ancienne Emy, Gagné 60,50 $",
          par.get("Carter", {}).get("subs") == 71 and not par["Carter"].get("introuvables")
          and par["Carter"].get("gagne") == 60.5, par.get("Carter"))
    check("Total : 206 subs, Gagné 148,70 $",
          (t.get("totaux") or {}).get("subs") == 206 and (t.get("totaux") or {}).get("gagne") == 148.7,
          t.get("totaux"))
    check("Infloww lu pour la nouvelle Emy et pour Jessye, rien d'autre",
          set(APPELS_IFW) == {"emy.brw", "jessyewdiference"}
          and {c for c, *_ in APPELS_SUBS} <= {"emy.brw", "jessyewdiference"}, (APPELS_IFW, APPELS_SUBS))
    check("les abonnés de la nouvelle Emy lus par son id, ceux de Jessye sans",
          all(v == NOUV for c, _j, _a, v in APPELS_SUBS if c == "emy.brw")
          and all(v == "" for c, _j, _a, v in APPELS_SUBS if c == "jessyewdiference")
          and any(c == "emy.brw" for c, *_ in APPELS_SUBS), APPELS_SUBS)

    h = em.page({"du": "2026-11-01", "au": "2026-11-15", "c": "emy"}, cle="", paie=False, lien_perso=True)
    texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    check("la page rendue dit l'ancienne Emy hors compte et Jessye pour le 01→15/11 seulement",
          "ancienne Emy (emy.brww)" in texte and "01 au 15/11 seulement" in texte)
    check("la page rendue montre les trois VA, sans « introuvable », pas de <script> cassé",
          all(n in texte for n in ("Misandratra", "Andry", "Carter")) and "introuvable" not in texte
          and "<script" not in h)

    print("4. Un lien qui change plus tard de lien de suivi garde sa part Jessye")
    GMS[0] = lien(MI, "VA 1 - ( Misandratra )", E + "28", "grp_n")
    t3 = em.tableau_periode("2026-11-02", "2026-11-15", us="cache")
    m3 = {x["cle"]: x for x in t3.get("lignes") or []}.get("Misandratra", {})
    check("Misandratra passé sur c28 (inconnu d'Infloww) : part Jessye c153 toujours là (40), ligne à trou, "
          "Gagné « — »", (m3.get("part_p") or {}).get("subs") == 40 and m3.get("a_trou") and m3.get("gagne") is None,
          m3)
    check("… et le Total Gagné « — » (une ligne manque)", (t3.get("totaux") or {}).get("gagne") is None,
          t3.get("totaux"))
    GMS[0] = lien(MI, "VA 1 - ( Misandratra )", E + "15", "grp_n")

    print("5. La paie (tranches de quinzaine) lit la même source que le tableau")
    APPELS_MP.clear()
    for d in (il._MYPULS_CACHE, em._MYPULS_CACHE, em._MYPULS_ECHECS):
        d.clear()
    em._releve_mypuls("2026-11-01", "2026-11-15")
    tq = (em._MYPULS_CACHE.get(("2026-11-01", "2026-11-15")) or {}).get("v") or {}
    check("tranche 01→15/11 : lue chez Infloww (nouvelle Emy), aucune lecture MyPuls",
          not APPELS_MP and sorted((x["code"], x["abonnes"]) for x in tq.get("liens") or [])
          == [("1", 1), ("15", 3), ("27", 2)], (APPELS_MP, tq))
    sq, trous = em._subs_par_personne(tq["liens"], [dict(l) for l in GMS], bornes=("2026-11-01", "2026-11-15"),
                                      partenaire=em._partenaire_periode("2026-11-01", "2026-11-15",
                                                                        em._codes_partenaire(GMS, "2026-11-01")))
    check("… et ses subs par VA = le tableau (43 / 92 / 71)",
          [sq.get(k) for k in ("Misandratra", "Andry", "Carter")] == [43, 92, 71], (sq, trous))

    print("6. Période 10→20/11 : Jessye lue jusqu'au 15/11 seulement")
    APPELS_SUBS.clear()
    for d in (il._MYPULS_CACHE, em._MYPULS_CACHE, em._MYPULS_ECHECS):
        d.clear()
    em.tableau_periode("2026-11-10", "2026-11-20", us="cache")
    check("lecture Jessye bornée au 15/11", any(c == "jessyewdiference" and a == "2026-11-15"
                                                 for c, _j, a, _v in APPELS_SUBS)
          and not any(c == "jessyewdiference" and a == "2026-11-20" for c, _j, a, _v in APPELS_SUBS), APPELS_SUBS)

    print("7. Quinzaine du 16 au 30/11 : Emy seule")
    AUJ["j"] = "2026-11-20"
    APPELS_SUBS.clear()
    t4 = em.tableau_periode("2026-11-16", "2026-11-30", us="cache")
    p4 = {x["cle"]: x for x in t4.get("lignes") or []}
    check("plus de part Jessye : Misandratra 3, Andry 2, Carter 1",
          [p4.get(k, {}).get("subs") for k in ("Misandratra", "Andry", "Carter")] == [3, 2, 1]
          and not any(p4.get(k, {}).get("part_p") for k in ("Misandratra", "Andry", "Carter")), p4)
    check("… et Jessye n'est même pas lue", not any(c == "jessyewdiference" for c, *_ in APPELS_SUBS), APPELS_SUBS)
    em.infloww._creatrice_ou_erreur = _ifw
    AUJ["j"] = "2026-11-09"

    print("8. Relevés de lignes notés au nom d'avant le renommage (« ANDRY »)")
    k = em._cle_periode("2026-11-01", "2026-11-15")
    tr = {k: {"liens": {A3: {"qui": "ANDRY", "nom": "(ANDRY) 3"}, A4: {"qui": "ANDRY", "nom": "(ANDRY) 4"}}}}
    liens_andry = [{"id": A3, "nom": "VA 4 - ( Andry ) 3"}, {"id": A4, "nom": "VA 4 - ( Andry ) 4"}]
    proprio = {A3: "Andry", A4: "Andry", MI: "Misandratra"}
    r = em._lignes_tranche(tr, em._index_lg(tr), "Andry", liens_andry, "2026-11-01", "2026-11-15", "2026-11-09",
                           proprio, {}, {})
    check("« ANDRY » n'existe plus : ses 2 liens restent les lignes d'Andry, pas « exclus chez ANDRY »",
          not r["exclus"] and sorted(l["id"] for l, _s in r["sts"]) == sorted([A3, A4]), r)
    tr2 = {k: {"liens": {A3: {"qui": "Misandratra", "nom": "x"}}}}
    r2 = em._lignes_tranche(tr2, em._index_lg(tr2), "Andry", liens_andry[:1], "2026-11-01", "2026-11-15",
                            "2026-11-09", proprio, {}, {})
    check("… mais noté à une personne qui existe encore : toujours exclu chez elle",
          r2["exclus"] == [{"nom": "VA 4 - ( Andry ) 3", "chez": "Misandratra"}], r2)
finally:
    pd.subs_infloww, pd._lire_registre, cp.rattachements_identite_ou_panne = _pd_si, _pd_reg, _cp_ratt
    for k, v in _SAUVE.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    shutil.rmtree(TMP, ignore_errors=True)

check("data/ du dépôt inchangé", _instantane() == AVANT_DATA)
print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
