# -*- coding: utf-8 -*-
"""tests_page_emy_jessye.py — la page /infloww/liens?c=emy additionne Emy et
Jessye.

Propriétaire, 28/10/2026 : « pour Jessye faut que ça additionne les subs de
Emy et de Jessye » (mêmes personnes, mêmes liens GetMySocial).

Ce qui est vérifié (infloww_liens, profil « emy », PARTENAIRE) :
  - un lien passé sur Jessye compte son lien de suivi Jessye (Infloww) ET le
    lien de suivi Emy qu'il a quitté (registre du podium), chacun une fois ;
  - la règle du registre : le nom du lien, ou son id + le numéro unique du
    lien de suivi actuel ; un id seul (faux candidat) ne suffit pas ; un lien
    de suivi encore visé par un autre lien reste à cet autre lien ; un lien de
    suivi quitté avant la période n'y compte pas (mais compte depuis toujours) ;
  - Infloww muet : la part Emy reste, la page le dit, aucune prime ;
  - gains Jessye non datés : le $ / sub est celui d'Emy seule, et c'est dit ;
  - clics et gains Jessye connus seulement sur une période qui couvre toute
    la vie du lien et finit aujourd'hui ;
  - un lien de suivi quitté ne compte que jusqu'à son dernier jour visé
    (lecture MyPuls [du, vu], comme le podium) ; sans elle, il est compté sur
    toute la période, la page le dit, la paie attend ;
  - un lien Jessye créé après la période y vaut 0, connu, sans lecture
    (créations d'Infloww gardées, sinon « premier » du registre hors amorce) ;
  - la lecture Infloww part dans un fil, attendue au plus
    PARTENAIRE_ATTENTE_S, depuis toujours (tableau) comme sur une période ;
    depuis toujours, abonnés comptés un par un (subs_infloww, pause=False) ;
  - la part Jessye d'une quinzaine close est gardée (QUINZ_FICHIER) et
    resservie sans Infloww ; pas d'une lecture trop tôt ni d'une panne ;
  - subs_infloww(pause=False) ne met pas Jessye au repos du podium ;
  - « tracking partagé avec » sous chacune des lignes qui visent le même lien ;
  - la page Jessye (sans c) ne change pas ; la vue des VA ne montre ni
    paiement ni gain ; aucun JavaScript.

Faux registre, fausses lectures : aucun appel réseau. Lancement :
python tests_page_emy_jessye.py
"""
from __future__ import annotations

import datetime as dt
import html
import io
import json
import pathlib
import shutil
import sys
import tempfile
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from zoneinfo import ZoneInfo          # noqa: E402

# GetMySocial bouché : aucun appel, même par mégarde (tableau() demande sa pause)
_GMS = types.ModuleType("gms")
_GMS.pause_restante = lambda: 0
_GMS.etat_quota = lambda: {}
_GMS_AVANT = sys.modules.get("gms")
sys.modules["gms"] = _GMS

import infloww_liens as il             # noqa: E402
import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


em = il.profil("emy")
J = "https://onlyfans.com/jessyewdiference/c"
E = "https://onlyfans.com/emy.brw/c"
DU, AU = "2026-10-16", "2026-10-28"


def lien(lid, nom, url):
    return {"id": lid, "display_name": nom, "url": None, "url_boutons": [url], "status": "active"}


GMS = [lien("lnk_a1", "VA 2 - Abdoul  ( normal )", J + "144"),
       lien("lnk_a2", "VA 2 - Abdoul  ( spam )", E + "41"),
       lien("lnk_d", "DONLAD ( normal )", J + "138"),          # renommé de DOLAD
       lien("lnk_m", "VA 4 - ( Mihkim )", J + "136"),
       lien("lnk_t", "VA 3 - ( Tsiry )", J + "145"),
       lien("lnk_j", "JERRY N", E + "69"),
       lien("lnk_jj", "VA 7 - ( Jerry )", J + "134")]


def entree(numero, liens, ids, premier, vu, actif):
    return {"numero": numero, "liens": liens, "ids": ids, "premier": premier, "vu": vu, "actif": actif}


REG = {"trackings": {
    "emy.brw/c40": entree(10, ["VA 2 - Abdoul  ( normal )"], ["lnk_a1"], "2026-10-06", "2026-10-27", False),
    # quitté avant la période : compte depuis toujours, pas du 16 au 28
    "emy.brw/c10": entree(10, ["VA 2 - Abdoul  ( normal )"], ["lnk_a1"], "2026-09-01", "2026-10-05", False),
    "emy.brw/c41": entree(15, ["VA 2 - Abdoul  ( spam )"], ["lnk_a2"], "2026-10-06", "2026-10-28", True),
    "emy.brw/c55": entree(16, ["DOLAD ( normal )"], ["lnk_d", "lnk_j"], "2026-10-06", "2026-10-27", False),
    # c37 : Tsiry, mais l'id de Mihkim y traîne (faux candidat du 28/10)
    "emy.brw/c37": entree(43, ["VA 3 - ( Tsiry )"], ["lnk_t", "lnk_m"], "2026-10-06", "2026-10-27", False),
    "emy.brw/c62": entree(58, ["VA 4 - ( Mihkim )"], ["lnk_m"], "2026-10-06", "2026-10-27", False),
    # encore visé par JERRY N : à lui, pas à « VA 7 - ( Jerry ) »
    "emy.brw/c69": entree(64, ["JERRY N", "VA 7 - ( Jerry )"], ["lnk_j", "lnk_jj"], "2026-10-06", "2026-10-28",
                          True),
    # un vieux lien de suivi Jessye (avant le 06/10) : pas un lien Emy quitté
    "jessyewdiference/c91": entree(10, ["VA 2 - Abdoul  ( normal )"], [], "2026-10-06", "2026-10-06", False),
    # vu dès l'amorce du registre : son « premier » n'est pas une date de création
    "jessyewdiference/c86": entree(11, ["Kylmich"], [], "2026-09-01", "2026-10-28", True)},
    "attente": {"jessyewdiference/c144": {"numeros": [10], "premier": "2026-10-27"},
                "jessyewdiference/c138": {"numeros": [16], "premier": "2026-10-27"},
                "jessyewdiference/c136": {"numeros": [43, 58], "premier": "2026-10-27"},
                "jessyewdiference/c145": {"numeros": [43], "premier": "2026-10-27"},
                "jessyewdiference/c134": {"numeros": [64], "premier": "2026-10-27"}}}


def mp(code, subs, clics, net):
    return {"id": f"mypuls:{code}", "nom": f"Emy c{code}", "code": str(code), "clics": clics,
            "abonnes": subs, "net": net}


MP = [mp(40, 312, 2211, 26947), mp(10, 5, 50, 0), mp(41, 3, 18, 720), mp(55, 11, 168, 0),
      mp(37, 269, 2535, 18319), mp(62, 200, 1800, 51400), mp(69, 8, 127, 0), mp(99, 7, 70, 100)]
# MyPuls du 16 au 27 (dernier jour où c40, c55, c37, c62 étaient visés) : le
# 28/10, MyPuls avait encore rangé des abonnés sur des liens quittés la veille
MP27 = [mp(40, 311, 2200, 26000), mp(10, 5, 50, 0), mp(41, 3, 18, 720), mp(55, 11, 168, 0),
        mp(37, 269, 2530, 18000), mp(62, 199, 1790, 51000), mp(69, 8, 120, 0), mp(99, 7, 70, 100)]
FINS = {"2026-10-27": {"liens": MP27}}
PARIS = ZoneInfo("Europe/Paris")
CREE = int(dt.datetime(2026, 10, 27, 16, 13, tzinfo=PARIS).timestamp() * 1000)


def ifw(code, abonnes, clics, net):
    return {"id": f"ifw{code}", "nom": f"Jessye c{code}", "code": str(code), "clics": clics, "abonnes": abonnes,
            "net": net, "cree": "2026-10-27", "cree_ms": CREE, "devise": "USD", "termine": False}


IFW = [ifw(144, 28, 238, 0), ifw(138, 0, 40, 0), ifw(136, 5, 300, 500), ifw(145, 3, 90, 0), ifw(134, 0, 12, 0)]
SUBS_JESSYE = {144: 27, 138: 0, 136: 5, 145: 3, 134: 0}     # sur la période, créations retirées


def part(entier=True):
    return {"liens": [em._entree_partenaire(x, x["code"], SUBS_JESSYE[int(x["code"])], entier) for x in IFW]}


_SAUVE = {"_lire_registre": pd._lire_registre, "subs_infloww": pd.subs_infloww}
_SAUVE_EM = {k: getattr(em, k) for k in ("_aujourdhui", "_infloww", "liens_gms", "PARTENAIRE_ATTENTE_S",
                                         "QUINZ_FICHIER", "PAIE_FICHIER", "LIGNES_FICHIER", "_us_pour_la_page")}
# infloww n'est importé que par ses importeurs voulus (tests_site le vérifie) :
# le module que subs_infloww importe est remplacé dans sys.modules, le temps
# d'un essai
_SAUVE_IW = sys.modules.get("infloww")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="tests_page_emy_"))


def vider_caches():
    """Les caches de la part Jessye du module de la page Emy, à zéro."""
    for d in (em._PARTENAIRE_CACHE, em._PARTENAIRE_ECHECS, em._PARTENAIRE_FILS, em._PARTENAIRE_CREES):
        d.clear()
try:
    pd._lire_registre = lambda: REG

    # ── les liens de suivi quittés (registre du podium) ────────────────────
    anc, panne = em._anciens_trackings(GMS, (DU, AU))
    codes = {k: [a["code"] for a in v] for k, v in anc.items()}
    check("registre : Abdoul retrouve c40 (par le nom), pas c10 quitté avant la période",
          codes.get("lnk_a1") == ["40"] and not panne, (codes, panne))
    check("registre : DONLAD (renommé) retrouve c55 par l'id et le numéro unique de c138",
          codes.get("lnk_d") == ["55"], codes)
    check("registre : Mihkim retrouve c62, pas c37 (son id y traîne, numéro c136 pas unique)",
          codes.get("lnk_m") == ["62"], codes)
    check("registre : Tsiry retrouve c37 (le nom)", codes.get("lnk_t") == ["37"], codes)
    check("registre : JERRY N ne prend pas c55 (id présent, mais numéro 64 ≠ 16)", "lnk_j" not in codes, codes)
    check("registre : c69 encore visé par JERRY N n'est le lien quitté de personne", "lnk_jj" not in codes, codes)
    check("registre : un vieux lien de suivi Jessye n'est jamais un lien Emy quitté",
          all(not c.startswith("j") for v in codes.values() for c in v), codes)
    tous, _p = em._anciens_trackings(GMS, None)
    check("registre : depuis toujours, c10 compte aussi",
          sorted(a["code"] for a in tous.get("lnk_a1") or []) == ["10", "40"], tous.get("lnk_a1"))
    check("registre : la page Jessye ne lit pas le registre", il._anciens_trackings(GMS, (DU, AU)) == ({}, ""))

    # ── le tableau d'une période : Emy (MyPuls) + Jessye (Infloww) ────────
    t = em.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": AU}, partenaire=part(), bornes=(DU, AU),
                      fins=FINS)
    L = {x["cle"]: x for x in t["lignes"]}
    ab = L.get("VA 2 - Abdoul") or {}
    check("additionne : Abdoul = c40 jusqu'au 27/10 (Emy, MyPuls) + c144 (Jessye, Infloww) = 311 + 27",
          ab.get("subs") == 338 and (ab.get("part_p") or {}).get("subs") == 27, ab)
    check("additionne : c40 dit « visé jusqu'au 27/10 », c144 dit sa créatrice",
          any(r.get("code") == "40" and r.get("quitte") == "2026-10-27" for r in ab.get("infloww") or [])
          and any(r.get("code") == "144" and r.get("creatrice") == "jessyewdiference" for r in ab.get("infloww") or []),
          ab.get("infloww"))
    check("additionne : DONLAD 11, Mihkim 199 + 5, Tsiry 269 + 3, JERRY N 8 (c69 encore visé), Jerry 0",
          [(L.get(k) or {}).get("subs") for k in ("DONLAD", "Mihkim", "Tsiry", "JERRY N", "Jerry")]
          == [11, 204, 272, 8, 0], {k: (v.get("subs"), v.get("infloww")) for k, v in L.items()})
    T = t["totaux"]
    check("additionne : chaque lien de suivi une fois au total (836), c10 et c99 hors GetMySocial",
          T.get("subs") == 311 + 27 + 3 + 11 + 0 + 199 + 5 + 269 + 3 + 8 + 0
          and sorted(x["code"] for x in t["hors_gms"]) == ["10", "99"], (T, t["hors_gms"]))
    check("additionne : clics jusqu'au 27/10 + Infloww, CVR sur les mêmes liens, $ / sub = gains de la période",
          ab.get("clics") == 2200 + 238 and abs(ab["par_sub"] - 269.47 / 338) < 1e-9
          and abs(ab["cvr"] - 338 * 100 / (2200 + 238)) < 1e-9, ab)
    check("quitté : c40 compté jusqu'au 27/10 (« fin »), sans marque de manque",
          any(r.get("code") == "40" and r.get("fin") == "2026-10-27" and not r.get("fin_manque")
              for r in ab.get("infloww") or []), ab.get("infloww"))

    # ── un lien quitté sans sa lecture jusqu'au dernier jour ───────────────
    t_sf = em.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": AU}, partenaire=part(),
                         bornes=(DU, AU), fins={"2026-10-27": {"erreur": "réponse vide", "en_cours": True}})
    ab_sf = {x["cle"]: x for x in t_sf["lignes"]}["VA 2 - Abdoul"]
    h_sf = em.page_html(t_sf, "nom", "asc", "CLE")
    check("quitté sans lecture [du, vu] : compté sur toute la période (339), marqué, dit en tête",
          ab_sf["subs"] == 339 and any(r.get("fin_manque") for r in ab_sf["infloww"])
          and "compté sur toute la période" in h_sf and "en cours" in h_sf
          and t_sf["partenaire"]["n_fins_manque"] == 4, (ab_sf, t_sf["partenaire"]))
    s_sf, tr_sf = em._subs_par_personne(MP, GMS, bornes=(DU, AU), partenaire=part(),
                                        fins={"2026-10-27": {"a_lire": True}})
    check("quitté sans lecture [du, vu] : pas de prime (trou « c40 jusqu'au 27/10 »)",
          s_sf.get("VA 2 - Abdoul") is None and tr_sf.get("VA 2 - Abdoul") == ["40@2026-10-27"]
          and em._lib_code("40@2026-10-27") == "c40 jusqu'au 27/10", (s_sf, tr_sf))
    fq = em._fins_quittes(GMS, DU, AU)
    check("quitté : une lecture de plus par dernier jour distinct (16 → 27 : c37, c40, c55, c62)",
          fq == {"2026-10-27": ["37", "40", "55", "62"]} and em._fins_quittes(GMS, DU, "2026-10-27") == {}
          and il._fins_quittes(GMS, DU, AU) == {}, fq)
    h = em.page_html(t, "nom", "asc", "CLE")
    check("page : sous les subs « dont 27 Jessye », sous le nom « visé jusqu'au 27/10 »",
          "dont 27 Jessye" in h and "visé jusqu'au 27/10" in h)
    check("page : colonne « Clics OF », titre « MyPuls + Infloww », @emy.brw + @jessyewdiference",
          "Clics OF" in h and "· MyPuls + Infloww" in h and "@emy.brw + @jessyewdiference" in h)
    check("page : « liens de suivi d'Emy » (et non « de Jessye ») hors GetMySocial",
          "liens de suivi d'Emy qu'aucun lien" in html.unescape(h) and "de suivi de Jessye qu" not in h)
    check("page des VA : ni paiement ni gain, aucun JavaScript",
          "Paiement" not in h and "Gain" not in h and "<script" not in h.lower())

    # ── gains et clics Jessye pas datés sur la période ─────────────────────
    t2 = em.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": "2026-10-27"},
                       partenaire=part(entier=False), bornes=(DU, "2026-10-27"))
    ab2 = {x["cle"]: x for x in t2["lignes"]}["VA 2 - Abdoul"]
    h2 = em.page_html(t2, "nom", "asc", "CLE")
    check("hors vie entière : subs Jessye comptés, clics et gains Jessye hors du CVR et du $ / sub",
          ab2["subs"] == 339 and ab2["clics"] == 2211 and abs(ab2["par_sub"] - 269.47 / 312) < 1e-9
          and abs(ab2["cvr"] - 312 * 100 / 2211) < 1e-9, ab2)
    check("hors vie entière : la page le dit (« hors Jessye », « Emy seule »)",
          "hors Jessye" in h2 and "Emy seule" in h2)
    rv = em._revenu(ab2, t2["_paie_liens"], "USD")
    check("hors vie entière : pas de revenu inventé pour la paie (gains Jessye inconnus)",
          rv[0] is None and "inconnus sur cette période" in rv[1], rv)

    # ── Infloww muet ───────────────────────────────────────────────────────
    t3 = em.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": AU},
                       partenaire={"erreur": "réseau : timed out"}, bornes=(DU, AU), fins=FINS)
    ab3 = {x["cle"]: x for x in t3["lignes"]}["VA 2 - Abdoul"]
    h3 = em.page_html(t3, "nom", "asc", "CLE")
    check("Infloww muet : la part Emy reste (311), la part Jessye est dite manquante",
          ab3["subs"] == 311 and ab3["part_p"]["manque"] == 1 and "sans Jessye" in h3
          and "Part Jessye manquante" in h3 and "pas lu chez Infloww" in h3, (ab3, h3[:0]))
    s_ok, tr_ok = em._subs_par_personne(MP, GMS, bornes=(DU, AU), partenaire=part(), fins=FINS)
    s_ko, tr_ko = em._subs_par_personne(MP, GMS, bornes=(DU, AU), partenaire={"erreur": "réseau : timed out"},
                                        fins=FINS)
    check("paie : les primes se calculent sur les subs additionnés (338)",
          s_ok.get("VA 2 - Abdoul") == 338 and tr_ok.get("VA 2 - Abdoul") == [], (s_ok, tr_ok))
    check("paie : Infloww muet -> subs inconnus (pas de prime), trou « Jessye c144 » dit",
          s_ko.get("VA 2 - Abdoul") is None and tr_ko.get("VA 2 - Abdoul") == ["jessyewdiference/c144"]
          and em._lib_code("jessyewdiference/c144") == "Jessye c144" and em._lib_code("83") == "c83",
          (s_ko.get("VA 2 - Abdoul"), tr_ko.get("VA 2 - Abdoul")))
    check("paie : les tranches MyPuls n'attendent jamais un code Jessye",
          em._codes_personne(ab) == {"40"}, em._codes_personne(ab))

    # ── registre illisible ─────────────────────────────────────────────────
    pd._lire_registre = lambda: {"trackings": {}, "attente": {}}
    t4 = em.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": AU}, partenaire=part(), bornes=(DU, AU),
                       fins=FINS)
    check("registre vide ou illisible : dit sur la page, la part Jessye reste",
          "Registre des liens de suivi du podium illisible" in em.page_html(t4, "nom", "asc", "CLE")
          and {x["cle"]: x for x in t4["lignes"]}["VA 2 - Abdoul"]["subs"] == 27)
    pd._lire_registre = lambda: REG

    # ── les compteurs Jessye ne valent la période que sur toute la vie du lien
    em._aujourdhui = lambda: "2026-10-28"
    em._infloww = lambda creatrice="": {"erreur": "", "liens": [dict(x) for x in IFW], "lu_a": 1.0}
    pd.subs_infloww = lambda jour, ts, au=None, creatrice="", pause=True: {t_: 1 for t_ in ts}
    vies = {}
    for du_, au_ in ((DU, AU), ("2026-10-28", AU), (DU, "2026-10-27")):
        v, raison = em._lire_partenaire(du_, au_, ("144",))
        vies[(du_, au_)] = (v["liens"][0]["clics"], v["liens"][0]["net_absent"], raison)
    check("Infloww : clics et gains Jessye comptés du 16 au 28 (création le 27, fin aujourd'hui)",
          vies[(DU, AU)] == (238, False, ""), vies)
    check("Infloww : pas le 28 seul (créé la veille), ni du 16 au 27 (ne finit pas aujourd'hui)",
          vies[("2026-10-28", AU)][:2] == (None, True) and vies[(DU, "2026-10-27")][:2] == (None, True), vies)
    pd.subs_infloww = lambda jour, ts, au=None, creatrice="", pause=True: None
    v, raison = em._lire_partenaire(DU, AU, ("144",))
    check("Infloww : linkfans muet -> erreur dite, rien d'inventé", v == {} and "linkfans" in raison, raison)

    # ── depuis toujours : abonnés un par un, pas le compteur cumulé ────────
    vider_caches()
    vus_args = []

    def subs_trace(jour, ts, au=None, creatrice="", pause=True):
        vus_args.append((jour, au, creatrice, pause))
        return {t_: 20 for t_ in ts}

    pd.subs_infloww = subs_trace
    v, raison = em._lire_partenaire("", "", ("144",))
    check("depuis toujours : subs_infloww de PLANCHER à aujourd'hui, pause=False, pas subCount (28)",
          not raison and v["liens"][0]["abonnes"] == 20 and v["liens"][0]["clics"] == 238
          and vus_args == [(em.PLANCHER.isoformat(), "2026-10-28", "jessyewdiference", False)], (v, vus_args))
    check("lecture Infloww : les jours de création des liens Jessye sont gardés (Paris)",
          em._PARTENAIRE_CREES.get("144") == "2026-10-27", em._PARTENAIRE_CREES)

    # ── lecteur lent : la page attend au plus son délai ────────────────────
    vider_caches()
    pd.subs_infloww = lambda jour, ts, au=None, creatrice="", pause=True: {t_: 4 for t_ in ts}

    def infloww_lent(s):
        def f(creatrice=""):
            time.sleep(s)
            return {"erreur": "", "liens": [dict(x) for x in IFW], "lu_a": time.time()}
        return f

    em._infloww = infloww_lent(0.3)
    t0 = time.time()
    r_l = em._partenaire_periode(DU, AU, ["144"], attente=3.0)
    d_l = time.time() - t0
    check("lecteur lent (0,3 s) dans l'attente (3 s) : la lecture est rendue, sans attendre plus",
          [x["abonnes"] for x in r_l.get("liens") or []] == [4] and not r_l.get("erreur") and d_l < 2.0,
          (r_l, d_l))
    em._infloww = infloww_lent(2.0)
    t0 = time.time()
    r_t = em._partenaire_periode("2026-10-20", AU, ["144"], attente=0.3)
    d_t = time.time() - t0
    fil = (em._PARTENAIRE_FILS.get(("2026-10-20", AU)) or {}).get("fil")
    check("lecteur trop lent (2 s) : rendu en 0,3 s, « en cours », la lecture continue dans son fil",
          d_t < 1.5 and r_t.get("en_cours") and "ne répond pas encore" in r_t.get("erreur", "")
          and fil is not None and fil.is_alive(), (r_t, d_t))
    if fil is not None:
        fil.join(5)
    r_t2 = em._partenaire_periode("2026-10-20", AU, ["144"], attente=0.3)
    check("lecteur trop lent : rechargée après, la page a sa lecture (cache)",
          [x["abonnes"] for x in r_t2.get("liens") or []] == [4], r_t2)
    # lecture périmée (plus de PARTENAIRE_TTL_S) et relecture lente : la
    # dernière valeur connue, avec son heure, plutôt qu'un trou
    em._PARTENAIRE_CACHE[("2026-10-20", AU)]["t"] -= em.PARTENAIRE_TTL_S + 5
    t0 = time.time()
    r_t3 = em._partenaire_periode("2026-10-20", AU, ["144"], attente=0.3)
    d_t3 = time.time() - t0
    check("lecture périmée + Infloww lent : dernière valeur (4) et « chiffres lus le … », en 0,3 s",
          [x["abonnes"] for x in r_t3.get("liens") or []] == [4] and "chiffres lus le" in r_t3.get("perime", "")
          and d_t3 < 1.5, (r_t3.get("perime"), d_t3))
    fil3 = (em._PARTENAIRE_FILS.get(("2026-10-20", AU)) or {}).get("fil")
    if fil3 is not None:
        fil3.join(5)

    # ── tableau() (depuis toujours) borné lui aussi ─────────────────────────
    vider_caches()
    EMY_IFW = [{"id": f"emy{c}", "nom": f"Emy c{c}", "code": str(c), "clics": 100, "abonnes": 10, "net": 1000,
                "cree": "2026-10-06", "devise": "USD", "termine": False} for c in (40, 41, 55, 37, 62, 69, 10)]

    def infloww_deux(creatrice=""):
        if creatrice == "jessyewdiference":
            time.sleep(2.0)
            return {"erreur": "", "liens": [dict(x) for x in IFW], "lu_a": time.time()}
        return {"erreur": "", "liens": [dict(x) for x in EMY_IFW], "lu_a": time.time()}

    em._infloww = infloww_deux
    em.liens_gms = lambda maintenant=None: {"liens": [dict(l) for l in GMS], "repli": "", "desactives": 0}
    em._us_pour_la_page = lambda ents: None
    em.PARTENAIRE_ATTENTE_S = 0.3
    t0 = time.time()
    tt = em.tableau(us="cache")
    d_tt = time.time() - t0
    h_tt = em.page_html(tt, "nom", "asc", "CLE")
    ab_tt = {x["cle"]: x for x in tt["lignes"]}.get("VA 2 - Abdoul") or {}
    check("tableau() : Infloww lent pour Jessye -> rendu en moins de 1,5 s, part Emy affichée",
          d_tt < 1.5 and ab_tt.get("subs") == 20 and tt["partenaire"].get("en_cours"), (d_tt, ab_tt))
    check("tableau() : la page dit « Part Jessye en cours de lecture »",
          "Part Jessye en cours de lecture" in h_tt)
    f_tt = (em._PARTENAIRE_FILS.get(("", "")) or {}).get("fil")
    if f_tt is not None:
        f_tt.join(5)
    tt2 = em.tableau(us="cache")
    ab_tt2 = {x["cle"]: x for x in tt2["lignes"]}.get("VA 2 - Abdoul") or {}
    check("tableau() : rechargé, la part Jessye y est (20 + 4)",
          ab_tt2.get("subs") == 24 and (ab_tt2.get("part_p") or {}).get("subs") == 4, ab_tt2)
    em.PARTENAIRE_ATTENTE_S = _SAUVE_EM["PARTENAIRE_ATTENTE_S"]

    # ── une période avant la création des liens Jessye : rien à lire ───────
    vider_caches()
    appels_ifw = []
    em._infloww = lambda creatrice="": appels_ifw.append(creatrice) or {"erreur": "réseau : timed out"}
    P1, P2 = "2026-10-01", "2026-10-15"
    MP01 = [mp(40, 150, 1000, 9000), mp(55, 9, 90, 0), mp(37, 120, 1100, 5000), mp(62, 80, 700, 20000),
            mp(41, 2, 10, 0), mp(69, 4, 50, 0), mp(10, 5, 40, 300)]
    # c10, quitté le 05/10 : compté du 01 au 05 seulement
    FINS01 = {"2026-10-05": {"liens": [mp(10, 3, 30, 200)]}}
    p_av = em._partenaire_periode(P1, P2, em._codes_partenaire(GMS))
    check("avant la création (registre, cache vide) : 0 pour chaque lien Jessye, Infloww jamais appelé",
          appels_ifw == [] and not p_av.get("erreur") and p_av.get("sans_lecture")
          and sorted((x["code"], x["abonnes"], x["apres"]) for x in p_av["liens"])
          == sorted((c, 0, "2026-10-27") for c in ("134", "136", "138", "144", "145")), p_av)
    t_av = em.construire(MP01, GMS, source="MyPuls", periode={"du": P1, "au": P2, "devise": "USD"},
                         partenaire=p_av, bornes=(P1, P2), fins=FINS01)
    L_av = {x["cle"]: x for x in t_av["lignes"]}
    h_av = em.page_html(t_av, "nom", "asc", "CLE")
    s_av, tr_av = em._subs_par_personne(MP01, GMS, bornes=(P1, P2), partenaire=p_av, fins=FINS01)
    check("avant la création : Abdoul 150 + 3 (c10 jusqu'au 05/10), Mihkim 80, aucun « — » ni part Jessye",
          L_av["VA 2 - Abdoul"]["subs"] == 153 and L_av["Mihkim"]["subs"] == 80
          and "part_p" not in L_av["VA 2 - Abdoul"] and "Part Jessye" not in h_av
          and "créé le 27/10, après la période : 0" in h_av, (L_av["VA 2 - Abdoul"], h_av[:0]))
    check("avant la création : primes calculables (aucun trou) et revenu connu",
          s_av.get("VA 2 - Abdoul") == 153 and tr_av.get("VA 2 - Abdoul") == []
          and em._revenu(L_av["VA 2 - Abdoul"], t_av["_paie_liens"], "USD")[0] == 93.0, (s_av, tr_av))
    em._PARTENAIRE_CREES["144"] = "2026-10-27"
    check("création connue par Infloww (cache) ; « premier » à l'amorce du registre jamais cru",
          em._crees_partenaire(["144", "86"]) == {"144": "2026-10-27"}, em._crees_partenaire(["144", "86"]))
    vider_caches()

    # ── quinzaine close : la part Jessye gardée, resservie sans Infloww ────
    em.QUINZ_FICHIER = TMP / "quinzaines_emy.json"
    Q1, Q2 = "2026-10-16", "2026-10-31"
    paris = ZoneInfo("Europe/Paris")
    tot = dt.datetime(2026, 11, 1, 2, 0, tzinfo=paris).timestamp()       # 2 h après minuit : trop tôt
    tard = dt.datetime(2026, 11, 1, 5, 0, tzinfo=paris).timestamp()
    lu_q = {"liens": [em._entree_partenaire(x, x["code"], SUBS_JESSYE[int(x["code"])], False) for x in IFW]}
    check("gel : pas d'une lecture faite moins de 4 h après la fin de la quinzaine (retard OnlyFans)",
          em._garder_partenaire(Q1, Q2, dict(lu_q, lu_a=tot)) is False and not em.QUINZ_FICHIER.exists())
    check("gel : pas d'une panne ni d'une lecture « en cours »",
          em._garder_partenaire(Q1, Q2, {"erreur": "réseau", "en_cours": True, "lu_a": tard}) is False
          and not em.QUINZ_FICHIER.exists())
    check("gel : une lecture assez tard est gardée", em._garder_partenaire(Q1, Q2, dict(lu_q, lu_a=tard)))
    lu_q2 = {"liens": [em._entree_partenaire(x, x["code"], 99, False) for x in IFW], "lu_a": tard + 3600}
    em._garder_partenaire(Q1, Q2, lu_q2)
    gele = (json.loads(em.QUINZ_FICHIER.read_text()).get("tranches") or {}).get(f"{Q1}|{Q2}") or {}
    check("gel : une valeur gardée ne change plus (27 reste 27)",
          (gele.get("partenaire") or {}).get("subs", {}).get("144") == 27, gele)
    # la part MyPuls gardée à côté, puis la paie de la quinzaine, Infloww muet
    em._garder_tranche(Q1, Q2, {"liens": MP, "lu_jour": "2026-11-01", "lu_a": tard,
                                "periode_mypuls": {"from": Q1 + "T00:00:00+01:00", "to": Q2 + "T23:59:59+01:00"}})
    em._garder_tranche(Q1, "2026-10-27", {"liens": MP27, "lu_jour": "2026-11-01", "lu_a": tard,
                                          "periode_mypuls": {"from": Q1, "to": "2026-10-27"}})
    gele2 = (json.loads(em.QUINZ_FICHIER.read_text()).get("tranches") or {}).get(f"{Q1}|{Q2}") or {}
    check("gel : la part MyPuls gardée ensuite ne retire pas la part Jessye",
          (gele2.get("partenaire") or {}).get("subs", {}).get("144") == 27 and gele2.get("subs", {}).get("40") == 312,
          gele2)
    em.PAIE_FICHIER = TMP / "paie.json"
    em.PAIE_FICHIER.write_text(json.dumps({"personnes": {"VA 2 - Abdoul": {
        "type": "fixe_primes", "montant": 75.0, "devise": "USD", "frequence": "quinzaine",
        "depuis": Q1, "telephones": 1}}}))
    em.LIGNES_FICHIER = TMP / "lignes.json"
    em._aujourdhui = lambda: "2026-11-02"
    appels_ifw.clear()
    em._infloww = lambda creatrice="": appels_ifw.append(creatrice) or {"erreur": "réseau : timed out"}
    pd.subs_infloww = lambda jour, ts, au=None, creatrice="", pause=True: appels_ifw.append("fans") or None
    t_q = em.construire(MP, GMS, source="MyPuls", periode={"du": Q1, "au": Q2, "devise": "USD"},
                        partenaire={"erreur": "réseau : timed out"}, bornes=(Q1, Q2), fins={"2026-10-27": {"liens": MP27}})
    tq = em.avec_paie(t_q, attente=0.5)
    pq = {x["cle"]: x for x in tq["lignes"]}["VA 2 - Abdoul"]["paie"]
    dq = [(q["du"], q["au"], q["subs"], q.get("prime")) for q in pq.get("detail_q") or []]
    check("quinzaine close gardée : primes sur 311 (Emy jusqu'au 27/10) + 27 (Jessye gardé), Infloww jamais lu",
          dq == [(Q1, Q2, 338, 90.0)] and appels_ifw == [], (dq, appels_ifw, pq.get("raison")))
    # un lien Jessye neuf (c160, date de création inconnue) : lu, Infloww muet ;
    # les liens gardés servent quand même, lien par lien
    GMS3 = GMS + [lien("lnk_z", "VA 9 - ( Zed )", J + "160")]
    t_q3 = em.construire(MP, GMS3, source="MyPuls", periode={"du": Q1, "au": Q2, "devise": "USD"},
                         partenaire={"erreur": "réseau : timed out"}, bornes=(Q1, Q2),
                         fins={"2026-10-27": {"liens": MP27}})
    tq3 = em.avec_paie(t_q3, attente=0.5)
    pq3 = {x["cle"]: x for x in tq3["lignes"]}["VA 2 - Abdoul"]["paie"]
    check("quinzaine close gardée + un lien Jessye neuf pas lu : Abdoul garde ses primes (338)",
          [(q["subs"], q.get("prime")) for q in pq3.get("detail_q") or []] == [(338, 90.0)]
          and appels_ifw == ["jessyewdiference"], (pq3.get("detail_q"), appels_ifw))
    # le tableau de la MÊME période a lu Infloww pour tous les codes : c144 y
    # vaut 99 ; la paie doit rester sur la valeur gardée (27), pas la vive
    vive = {"liens": [em._entree_partenaire({"id": "i144", "nom": "", "code": "144", "clics": 1,
                                             "abonnes": 99, "net": 0, "cree": "2026-10-27"}, "144", 99, False),
                      em._entree_partenaire({"nom": "", "code": "160"}, "160", 0, False)],
            "lu_a": time.time(), "codes": ["144", "160"]}
    em._PARTENAIRE_CACHE[(Q1, Q2)] = {"t": time.time(), "v": vive}
    tq4 = em.avec_paie(t_q3, attente=0.5)
    pq4 = {x["cle"]: x for x in tq4["lignes"]}["VA 2 - Abdoul"]["paie"]
    check("quinzaine close gardée + cache vif de la période (c144 = 99) : la paie garde 27 (338)",
          [(q["subs"], q.get("prime")) for q in pq4.get("detail_q") or []] == [(338, 90.0)],
          pq4.get("detail_q"))
    em._PARTENAIRE_CACHE.pop((Q1, Q2), None)
    em._aujourdhui = lambda: "2026-10-28"

    # ── subs_infloww(pause=False) ne met pas Jessye au repos du podium ─────
    pd.subs_infloww = _SAUVE["subs_infloww"]

    def creatrice_ko(pseudo):
        raise RuntimeError("réseau : timed out")

    faux_iw = types.ModuleType("infloww")
    faux_iw.creatrice = creatrice_ko
    sys.modules["infloww"] = faux_iw
    pd._INFLOWW_MUET.pop("jessyewdiference", None)
    r_np = pd.subs_infloww("2026-10-16", {"jessyewdiference/c144"}, au=AU, creatrice="jessyewdiference",
                           pause=False)
    check("subs_infloww(pause=False) : None, et _INFLOWW_MUET reste vide",
          r_np is None and "jessyewdiference" not in pd._INFLOWW_MUET, dict(pd._INFLOWW_MUET))
    r_p = pd.subs_infloww("2026-10-16", {"jessyewdiference/c144"}, au=AU, creatrice="jessyewdiference")
    check("subs_infloww() du podium : inchangé, 10 min de repos après un échec",
          r_p is None and pd._INFLOWW_MUET.get("jessyewdiference", 0) > time.time() + 500, dict(pd._INFLOWW_MUET))
    pd._INFLOWW_MUET.pop("jessyewdiference", None)
    sys.modules["infloww"] = _SAUVE_IW

    # ── tracking partagé entre la ligne normale et la ligne SPAM ───────────
    GMS2 = GMS + [lien("lnk_g1", "VA 5 - Gerome ( normal )", J + "141"),
                  lien("lnk_g2", "VA 5 - Gerome ( spam )", J + "141")]
    p141 = {"liens": part()["liens"] + [em._entree_partenaire(ifw(141, 2, 30, 0), "141", 2, True)]}
    t_g = em.construire(MP, GMS2, source="MyPuls", periode={"du": DU, "au": AU}, partenaire=p141,
                        bornes=(DU, AU), fins=FINS)
    L_g = {x["cle"]: x for x in t_g["lignes"]}
    h_g = em.page_html(t_g, "nom", "asc", "CLE")
    check("partagé : chaque ligne dit « tracking partagé avec » l'autre, montants inchangés (2 et 2, 2 au total)",
          [r.get("partage_avec") for r in L_g["VA 5 - Gerome"]["infloww"]] == [["VA 5 - Gerome SPAM"]]
          and [r.get("partage_avec") for r in L_g["VA 5 - Gerome SPAM"]["infloww"]] == [["VA 5 - Gerome"]]
          and L_g["VA 5 - Gerome"]["subs"] == 2 and L_g["VA 5 - Gerome SPAM"]["subs"] == 2
          and t_g["totaux"]["subs"] == t["totaux"]["subs"] + 2
          and h_g.count("tracking partagé avec VA 5 - Gerome") == 2,
          (t_g["totaux"]["subs"], t["totaux"]["subs"], h_g.count("tracking partagé avec VA 5 - Gerome")))
    tj_g = il.construire(MP, GMS2, source="MyPuls", periode={"du": DU, "au": AU})
    check("partagé : rien de neuf sur la page Jessye", "tracking partagé" not in il.page_html(tj_g, "nom", "asc", "CLE"))

    # ── la page Jessye (sans c) ne change pas ──────────────────────────────
    check("page Jessye : pas d'autre créatrice, pas de code Jessye « partenaire »",
          il.PARTENAIRE == "" and il.code_partenaire(J + "144") == "" and em.code_partenaire(J + "144") == "144"
          and em.code_partenaire(E + "40") == "" and il._codes_partenaire(GMS) == [])
    tj = il.construire(MP, GMS, source="MyPuls", periode={"du": DU, "au": AU})
    check("page Jessye : ni part Jessye ni liens quittés, titre « · MyPuls » seul",
          tj["partenaire"] == {} and all("part_p" not in x for x in tj["lignes"])
          and "· MyPuls + Infloww" not in il.page_html(tj, "nom", "asc", "CLE"))
finally:
    for k, val in _SAUVE.items():
        setattr(pd, k, val)
    for k, val in _SAUVE_EM.items():
        setattr(em, k, val)
    if _SAUVE_IW is None:
        sys.modules.pop("infloww", None)
    else:
        sys.modules["infloww"] = _SAUVE_IW
    if _GMS_AVANT is None:
        sys.modules.pop("gms", None)
    else:
        sys.modules["gms"] = _GMS_AVANT
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
