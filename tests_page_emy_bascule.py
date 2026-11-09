"""Page JESSY LE RETOUR (?c=emy) après la bascule du 09/11/2026.

Les 31 liens de l'équipe sont passés de Jessye (jessyewdiference/c132…c160) à
la NOUVELLE Emy (emy.brw/c1…c27, MyPuls 4126). La page additionne, par VA, la
nouvelle Emy (MyPuls seul) et la part Jessye de ses liens basculés (Infloww),
retrouvée par BASCULE_PARTENAIRE : plus aucun bouton ne porte jessyewdiference.

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

ETAT = {"voit_4126": True}
APPELS_MP = []
mp = types.ModuleType("mypuls")


def api_get(chemin, params=None, **k):
    APPELS_MP.append((chemin, params.get("from"), params.get("to")))
    du, au = params["from"], params["to"]
    # un leurre : même pseudo, autre compte (l'ancienne Emy) — jamais compté
    items = [{"url": "https://onlyfans.com/emy.brw/c15", "name": "leurre", "creator_id": 3352,
              "visits_period": 999, "subscribers_period": 999, "revenue": {"total": 999}, "active": True}]
    if ETAT["voit_4126"]:
        items += [{"url": f"https://onlyfans.com/emy.brw/c{c}", "name": n, "creator_id": 4126,
                   "visits_period": v, "subscribers_period": s, "revenue": {"total": 0}, "active": True}
                  for c, n, v, s in ((15, "VA 1 - ( Misandratra )", 30, 3), (27, "VA 4 - ( Andry )", 20, 2),
                                     (1, "VA 1 - ( Carter )", 10, 1))]
    return {"ok": True, "data": {"data": items, "count": len(items),
                                 "period": {"from": du + "T00:00:00+01:00", "to": au + "T23:59:59+01:00"},
                                 "currency": "USD"}}


mp.api_get = api_get
sys.modules["mypuls"] = mp

import clics_personnes as cp          # noqa: E402
import infloww_liens as il            # noqa: E402
import podium_discord as pd           # noqa: E402

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
    em._aujourdhui = lambda: "2026-11-09"
    em._us_periode_pour_la_page = lambda ents, du, au: {}
    em._us_pour_la_page = lambda ents: None

    print("1. Réglages de la page")
    b = em.BASCULE_PARTENAIRE
    check("nouvelle Emy chez MyPuls 4126, plus de période Infloww seul",
          em.CREATRICE == "emy.brw" and em.MYPULS_CREATOR_ID == 4126 and em.PERIODE_INFLOWW_DEPUIS == ""
          and em.SOURCE_TOUJOURS == "MyPuls" and em.ANCIENS_DEPUIS == "2026-11-09")
    check("table de bascule : les 31 liens par leur id, 25 codes Jessye, les 7 liens Andry sur c150",
          len(b) == 31 and all(k.startswith("lnk_") for k in b) and len(set(b.values())) == 25
          and list(b.values()).count("150") == 7 and b["lnk_6aba04fad38dbae582b4333e"] == "147"
          and b["lnk_6ac45440dae3fc7e8312b918"] == "153", b)
    check("les quinzaines figées de l'ancienne Emy ne sont plus servies (fichier à part)",
          em.QUINZ_FICHIER.name == "infloww_liens_quinzaines_emy_4126.json")
    check("la page Jessye (sans c) n'a pas de bascule", il.BASCULE_PARTENAIRE == {} and il.MYPULS_CREATOR_ID is None)

    E = "https://onlyfans.com/emy.brw/c"

    def lien(lid, nom, url, grp):
        return {"id": lid, "display_name": nom, "url": None, "url_boutons": [url], "status": "active",
                "group_id": grp}

    MI, A3, A4, CA = ("lnk_6ac45440dae3fc7e8312b918", "lnk_6ad868d11f59a2659b845ddb",
                      "lnk_6ad868d91f59a2659b845e22", "lnk_6aba04fad38dbae582b4333e")
    GMS = [lien(MI, "VA 1 - ( Misandratra )", E + "15", "grp_n"),
           lien(A3, "VA 4 - ( Andry ) 3", E + "27", "grp_s"),
           lien(A4, "VA 4 - ( Andry ) 4", E + "27", "grp_s"),
           lien(CA, "VA 1 - ( Carter )", E + "1", "grp_c")]
    em.liens_gms = lambda maintenant=None: {"liens": [dict(l) for l in GMS], "repli": "", "desactives": 0}
    check("_codes_partenaire : les codes Jessye des liens basculés, une fois chacun",
          em._codes_partenaire(GMS) == ["147", "150", "153"], em._codes_partenaire(GMS))

    CREE_J = int(time.mktime((2026, 10, 27, 17, 0, 0, 0, 0, -1)) * 1000)
    APPELS_IFW = []

    def faux_infloww(creatrice=""):
        APPELS_IFW.append(creatrice or em.CREATRICE)
        if (creatrice or em.CREATRICE) != "jessyewdiference":
            raise RuntimeError("la nouvelle Emy ne se lit pas chez Infloww")
        return {"erreur": "", "lu_a": time.time(), "liens": [
            {"id": f"i{c}", "code": f"c{c}", "nom": "x", "clics": 900, "abonnes": 41, "net": 0,
             "cree_ms": CREE_J, "devise": "USD"} for c in (153, 150, 147)]}

    em._infloww = faux_infloww
    SUBS = {"jessyewdiference/c153": 40, "jessyewdiference/c150": 90, "jessyewdiference/c147": 70}

    def faux_subs(jour, ts, au=None, creatrice="", pause=True, infos=None):
        if creatrice != "jessyewdiference":
            raise RuntimeError(f"Infloww lu pour {creatrice}")
        return {t: SUBS.get(t, 0) for t in ts}

    pd.subs_infloww = faux_subs
    # l'ANCIENNE Emy au registre (c33, Carter, quitté le 04/11) : plus comptée ici
    REG = {"trackings": {
        "emy.brw/c33": {"numero": 38, "liens": ["VA 1 - ( Carter )"], "ids": [CA],
                        "premier": "2026-10-05", "vu": "2026-11-04", "actif": False}}, "attente": {}}
    pd._lire_registre = lambda: REG
    cp.rattachements_identite_ou_panne = lambda: ({}, "")

    print("2. Quinzaine du 01 au 15/11 : nouvelle Emy + Jessye")
    t = em.tableau_periode("2026-11-01", "2026-11-15", us="cache")
    par = {x["cle"]: x for x in t.get("lignes") or []}
    check("source MyPuls, aucune erreur", t.get("source") == "MyPuls" and not t.get("erreur"),
          (t.get("source"), t.get("erreur")))
    check("Misandratra = 3 (Emy c15) + 40 (Jessye c153) = 43, Gagné 17,20 $ (sous 70 : 0,40 $)",
          par.get("Misandratra", {}).get("subs") == 43 and par["Misandratra"].get("gagne") == 17.2,
          par.get("Misandratra"))
    check("Andry : 2 liens sur c27 comptés une fois, + Jessye c150 = 92, Gagné 71,00 $",
          par.get("Andry", {}).get("subs") == 92 and par["Andry"].get("gagne") == 71.0, par.get("Andry"))
    check("Carter = 1 + 70 = 71, sans l'ancien c33 de l'ancienne Emy, Gagné 60,50 $",
          par.get("Carter", {}).get("subs") == 71 and not par["Carter"].get("introuvables")
          and par["Carter"].get("gagne") == 60.5, par.get("Carter"))
    check("le leurre (même pseudo, compte 3352) n'est compté nulle part, et c'est dit",
          (t.get("totaux") or {}).get("subs") == 206 and (t.get("periode") or {}).get("autre_compte") == 1,
          (t.get("totaux"), (t.get("periode") or {}).get("autre_compte")))
    check("Total Gagné = la somme des trois (aucune ligne à trou)", (t.get("totaux") or {}).get("gagne") == 148.7,
          t.get("totaux"))
    check("Infloww n'est lu que pour Jessye", APPELS_IFW and set(APPELS_IFW) == {"jessyewdiference"}, APPELS_IFW)
    check("MyPuls lu pour la période", any(a[:2] == ("tracking-links", "2026-11-01") for a in APPELS_MP), APPELS_MP)

    h = em.page({"du": "2026-11-01", "au": "2026-11-15", "c": "emy"}, cle="", paie=False, lien_perso=True)
    texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    check("la page rendue dit que l'ancienne Emy n'est plus comptée", "ancienne Emy (emy.brww)" in texte)
    check("… et qu'un lien d'un autre compte MyPuls a été écarté", "autre compte MyPuls" in texte)
    check("la page rendue montre les trois VA et pas de <script> cassé",
          all(n in texte for n in ("Misandratra", "Andry", "Carter")) and "<script" not in h)

    print("3. Un lien qui change plus tard de lien de suivi garde sa part Jessye")
    for d in (il._MYPULS_CACHE, em._MYPULS_CACHE, em._MYPULS_ECHECS):
        d.clear()
    GMS[0] = lien(MI, "VA 1 - ( Misandratra )", E + "28", "grp_n")
    t3 = em.tableau_periode("2026-11-01", "2026-11-15", us="cache")
    m3 = {x["cle"]: x for x in t3.get("lignes") or []}.get("Misandratra", {})
    check("Misandratra passé sur c28 (absent de MyPuls) : part Jessye c153 toujours là (40), ligne à trou, Gagné « — »",
          (m3.get("part_p") or {}).get("subs") == 40 and m3.get("a_trou") and m3.get("gagne") is None, m3)
    check("… et le Total Gagné « — » (une ligne manque)", (t3.get("totaux") or {}).get("gagne") is None, t3.get("totaux"))
    GMS[0] = lien(MI, "VA 1 - ( Misandratra )", E + "15", "grp_n")

    print("4. Relevés de lignes notés au nom d'avant le renommage (« ANDRY »)")
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

    print("5. MyPuls ne voit pas la nouvelle Emy : la page le dit, aucune paie à trou")
    ETAT["voit_4126"] = False
    for d in (il._MYPULS_CACHE, em._MYPULS_CACHE, em._MYPULS_ECHECS):
        d.clear()
    t2 = em.tableau_periode("2026-11-01", "2026-11-15", us="cache")
    p2 = {x["cle"]: x for x in t2.get("lignes") or []}
    check("chaque VA : son lien de suivi Emy « introuvable », dit",
          all(p2.get(k, {}).get("introuvables") for k in ("Misandratra", "Andry", "Carter")), p2)
    check("… sa part Jessye reste lue (40 / 90 / 70)",
          [(p2.get(k, {}).get("part_p") or {}).get("subs") for k in ("Misandratra", "Andry", "Carter")] == [40, 90, 70],
          [(p2.get(k, {}).get("part_p")) for k in ("Misandratra", "Andry", "Carter")])
    check("… et Gagné « — » : pas de grille sur un compte à trou",
          all(p2.get(k, {}).get("gagne") is None for k in ("Misandratra", "Andry", "Carter")),
          [p2.get(k, {}).get("gagne") for k in ("Misandratra", "Andry", "Carter")])
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
