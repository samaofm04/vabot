# -*- coding: utf-8 -*-
"""tests_va_interne.py — VA 41 : les comptes internes sur une seule ligne.

Propriétaire, 25/10/2026 : « mets tous les mecs de JESSY LE RETOUR pour le
VA 41, il prend tout », « tu prends un VA pour Twitter, idem pour Threads »,
« tous les comptes internes », « les subs pour Twitter et pour Instagram, et
pour Threads les clics ».

Ce qui est vérifié (podium_discord, section « VA 41 ») :
  - numeros_internes : tout numéro du registre qui n'est pas un VA Discord
    (tracking d'une fiche liens_va, variante comprise ; lien « Twitter VA n
    @pseudo » ; numéro d'une fiche de Twitter) ;
  - Twitter, en abonnés comme en clics : une ligne « VA 41 », la somme, à sa
    place ; les VA Discord sur la leur ; un compte interne sans relevé pas
    compté et dit, tous sans relevé : VA 41 sans relevé ; le relevé « gms »
    (Va IG) pas touché ; une panne du regroupement rend le classement
    d'avant ;
  - Agency, bonus et semaine : « Instagram VA 141 », les abonnés que Twitter
    vient de compter (sans relire), rien à la quinzaine (les lignes YouLab
    les ont déjà) ; Twitter muet : sans relevé ;
  - Threads, semaine : « Threads 142 », les clics US + UK des liens
    internes par lots de 20 (GetMySocial en refuse plus), sans les liens des
    VA Discord ; un lot muet : sans relevé, jamais un total partiel ; rien
    ajouté dans la quinzaine ;
  - Threads, quinzaine : les « Threads VA 1nn » internes réunis en « Threads
    VA 141 » (US, GBL, all-time additionnés) ; Va IG et Threads n intacts ;
  - le bonus affiche « 🥇 VA 41 — N subs → 5.00$ », aucun nom ; depuis le
    25/10, 40 subs au moins pour la prime (Twitter, Instagram), une place en
    dessous affichée « → pas de prime (min. 40) » ; un bonus d'avant garde
    7,50 / 5 / 3,50 $ sans minimum ;
  - Threads : « 💸 Bonus clics du jour », « US : n · GBL : n », rangé au US,
    400 clics US au moins ;
  - « Instagram VA 141 » et « Threads 142 » : jamais donnés à un VA ;
  - 👀 Pseudos : « comptes internes (N comptes) » et leurs noms, au staff ;
    les places payées seulement ;
  - suivi_va.annoncer_primes saute la ligne interne : personne n'est payé à
    son nom, le 2e garde la prime du 2e ;
  - INTERNES_REUNIS = False : tout comme avant.

Aucun appel réseau. Lancement : python tests_va_interne.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import pathlib
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import podium_discord as pd            # noqa: E402
import suivi_va                        # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


TW, TH, AG = pd.TWITTER_ID, pd.THREADS_ID, pd.AGENCY_IG_ID
J = dt.date(2026, 10, 24)
L = dt.date(2026, 10, 19)


def t(numero, cle, liens, actif=True):
    return {"numero": numero, "cle": cle, "nom": cle, "liens": liens, "actif": actif, "mp": True}


REG = {"trackings": {
    "emy.brw/c35": t(41, "Eddy", ["VA 2 - ( Eddy ) 1", "VA 2 - ( Eddy ) 2"]),
    "emy.brw/c42": t(12, "Roucham", ["VA 3 - Roucham 1 ( normal )"]),
    "emy.brw/c43": t(24, "Roucham SPAM", ["VA 3 - Roucham  ( spam )"]),
    "jessyewdiference/c86": t(11, "Kylmich", ["(Kylmich) 1 (Copy)"]),
    "emy.brw/c110": t(124, "bigmaxm", ["Twitter VA 124 @bigmaxm"]),
    "seren.vale/c228": t(124, "bigmaxm", ["Twitter VA 124 @bigmaxm"]),
    "emy.brw/c105": t(95, "rodolpheks", ["Twitter VA 95 @rodolpheks"]),
    # VA Discord par sa fiche seule : lien renommé, tracking d'avant
    "emy.brw/c6": t(31, "abdoul_9684", ["(ancien)"], actif=False),
    # … ou par la variante de sa fiche (Seren)
    "seren.vale/c300": t(77, "x77", ["sans nom"]),
    # un vieux compte interne sans tracking en service
    "jessyewdiference/c113": t(23, "Ricardo SPAM", ["(Ricardo) 1 SPAM"], actif=False),
}, "attente": {}, "frais": ""}
FICHES = {"liens": {
    f"{TW}:u31": {"numero": 31, "pseudo": "abdoul_9684", "tracking": "https://onlyfans.com/emy.brw/c6"},
    f"{TH}:u5": {"numero": 5, "pseudo": "th5", "tracking": "https://onlyfans.com/emy.brw/c999",
                 "variante": {"tracking": "https://onlyfans.com/seren.vale/c300"}},
    f"{TW}:u124": {"numero": 124, "pseudo": "bigmaxm", "tracking": "https://onlyfans.com/emy.brw/c110"},
}}
NOMS = {41: "Eddy", 12: "Roucham", 24: "Roucham SPAM", 11: "Kylmich", 23: "Ricardo SPAM",
        124: "bigmaxm", 95: "rodolpheks", 31: "abdoul_9684", 77: "x77"}


def ligne(va, n, clics, **kw):
    return dict({"va": va, "numero": n, "clics": clics, "liens": 1, "spam": False, "model": ""}, **kw)


SOURCES = {}          # (gid, source) -> classement rendu par le faux _classement_sans_internes
APPELS = []


def faux_classement(debut, fin, pause=0.3, gid=None, mesure=None, etiquette="podium"):
    src = pd._source(gid, mesure)
    APPELS.append((str(gid), src, debut, fin))
    cl = SOURCES.get((str(gid), src)) or {"lignes": [], "illisibles": [], "frais": True}
    return json.loads(json.dumps(cl))


TWITTER = {"lignes": [ligne("VA 41", 41, 194), ligne("VA 124", 124, 48), ligne("VA 12", 12, 37),
                      ligne("VA 24", 24, 30), ligne("VA 95", 95, 8), ligne("VA 31", 31, 0)],
           "illisibles": ["VA 11"], "frais": True, "erreur": ""}

TMP = pathlib.Path(tempfile.mkdtemp(prefix="va_interne_"))
_SAUVE = {k: getattr(pd, k) for k in ("_lire_registre", "_classement_sans_internes", "_noms_registre",
                                      "_entites_jessye_toutes", "VA_TWITTER_SUR_THREADS",
                                      "_liens_twitter", "_entites_jessye", "_releve_liens",
                                      "_quinzaine_sans_internes", "_noms_libelles_sans_internes",
                                      "_staff", "INTERNES_REUNIS")}
_SAUVE_LV = lv._etat
_SAUVE_SV = {k: getattr(suivi_va, k) for k in ("ETAT_FICHIER", "adresse_de")}
_SAUVE_TK = {k: getattr(tk, k) for k in ("_etat", "_api")}
try:
    pd._lire_registre = lambda: json.loads(json.dumps(REG))
    lv._etat = lambda: json.loads(json.dumps(FICHES))
    pd._noms_registre = lambda: dict(NOMS)
    pd._classement_sans_internes = faux_classement
    pd.INTERNES_REUNIS = True

    check("comptes internes : ni tracking de fiche (variante comprise), ni « Twitter VA n @ », "
          "ni numéro de fiche de Twitter",
          pd.numeros_internes() == {41, 12, 24, 11, 23}, sorted(pd.numeros_internes()))

    # ── Twitter ──
    SOURCES[(TW, "tracking_abonnes")] = TWITTER
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        cl = pd.classement(J, J, gid=TW, mesure="tracking_abonnes")
    va = [(x["va"], x["clics"]) for x in cl["lignes"]]
    v41 = cl["lignes"][0]
    check("Twitter : une seule ligne VA 41, la somme des comptes internes (194 + 37 + 30), en tête",
          va == [("VA 41", 261), ("VA 124", 48), ("VA 95", 8), ("VA 31", 0)], va)
    check("… marquée interne, avec ses comptes et ceux sans relevé (VA 11)",
          v41.get("interne") is True and v41["comptes"] == 4 and v41["sans_releve"] == ["VA 11"]
          and v41["numero"] == 41, v41)
    check("… le compte interne sans relevé n'est plus « sans relevé » au message, mais dit au journal",
          cl["illisibles"] == [] and "réuni(s) en VA 41" in sortie.getvalue()
          and "VA 11" in sortie.getvalue(), sortie.getvalue())
    SOURCES[(TW, "tracking")] = TWITTER
    with contextlib.redirect_stdout(io.StringIO()):
        clc = pd.classement(J, J, gid=TW, mesure="tracking")
    check("Twitter aux clics aussi", clc["lignes"][0]["va"] == "VA 41" and clc["lignes"][0]["clics"] == 261)
    SOURCES[(TW, "gms")] = TWITTER
    check("le relevé « gms » de Twitter (repris par Va IG) n'est pas touché",
          [x["va"] for x in pd.classement(J, J, gid=TW, mesure="gms")["lignes"]]
          == [x["va"] for x in TWITTER["lignes"]])
    SOURCES[(TW, "tracking_abonnes")] = {"lignes": [ligne("VA 124", 124, 48)],
                                         "illisibles": ["VA 41", "VA 12"], "frais": True}
    with contextlib.redirect_stdout(io.StringIO()):
        cs = pd.classement(J, J, gid=TW, mesure="tracking_abonnes")
    check("tous les comptes internes sans relevé : VA 41 sans relevé, une fois",
          cs["illisibles"] == ["VA 41"] and [x["va"] for x in cs["lignes"]] == ["VA 124"], cs)
    SOURCES[(TW, "tracking_abonnes")] = {"lignes": [ligne("VA 124", 124, 48), ligne("VA 95", 95, 8)],
                                         "illisibles": [], "frais": True}
    cd = pd.classement(J, J, gid=TW, mesure="tracking_abonnes")
    check("aucun compte interne : le classement tel quel",
          [x["va"] for x in cd["lignes"]] == ["VA 124", "VA 95"] and not cd["illisibles"])
    SOURCES[(TW, "tracking_abonnes")] = TWITTER
    _vrai = pd.numeros_internes
    pd.numeros_internes = lambda reg=None: 1 / 0
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        cp = pd.classement(J, J, gid=TW, mesure="tracking_abonnes")
    pd.numeros_internes = _vrai
    check("regroupement en panne : le classement d'avant, et c'est dit",
          [x["va"] for x in cp["lignes"]] == [x["va"] for x in TWITTER["lignes"]]
          and "comptes internes non réunis" in sortie.getvalue(), sortie.getvalue())

    J25 = dt.date(2026, 10, 25)
    with contextlib.redirect_stdout(io.StringIO()):
        b = pd.embed_bonus(pd.classement(J25, J25, gid=TW, mesure="tracking_abonnes"), J25, TW)
    check("le bonus du 25/10 : « 🥇 VA 41 — 261 subs → 5.00$ », 48 subs payés, 8 subs sous le minimum",
          "🥇 **VA 41** — **261 subs** → **5.00$**" in b["description"]
          and "🥈 **VA 124** — **48 subs** → **3.00$**" in b["description"]
          and "🥉 **VA 95** — **8 subs** → pas de prime (min. 40)" in b["description"]
          and "\nMinimum 40 subs dans la journée pour toucher la prime.\n" in b["description"],
          b["description"])
    with contextlib.redirect_stdout(io.StringIO()):
        b24 = pd.embed_bonus(pd.classement(J, J, gid=TW, mesure="tracking_abonnes"), J, TW)
    check("un bonus d'avant le 25/10 (réécrit) : le barème de son jour, 7.50 / 5 / 3.50, sans minimum",
          "🥇 **VA 41** — **261 subs** → **7.50$**" in b24["description"]
          and "🥉 **VA 95** — **8 subs** → **3.50$**" in b24["description"]
          and "Minimum" not in b24["description"], b24["description"])
    check("… aucun nom de compte interne en public",
          not any(n in b["description"] for n in ("Eddy", "Roucham", "Kylmich", "interne")))

    # ── Agency ──
    pd._TW_INTERNES.clear()
    SOURCES[(AG, "agency_abonnes")] = {"lignes": [ligne("Instagram VA 100", 100, 3),
                                                  ligne("Instagram VA 63", 63, 0)],
                                       "illisibles": [], "frais": True}
    SOURCES[(AG, "agency_quinzaine")] = {"lignes": [ligne("Instagram VA 001", 1, 500, youl4b=True)],
                                         "illisibles": [], "frais": True}
    APPELS.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        ca = pd.classement(J, J, gid=AG, mesure=pd._mesure_podium(AG))
        ca2 = pd.classement(J, J, gid=AG)
    va = [(x["va"], x["clics"]) for x in ca["lignes"]]
    check("Agency : « Instagram VA 141 » (un autre numéro), les abonnés des comptes internes, à sa place",
          va == [("Instagram VA 141", 261), ("Instagram VA 100", 3), ("Instagram VA 63", 0)]
          and ca["lignes"][0].get("interne") is True and ca["lignes"][0]["numero"] == 141, va)
    ba = pd.embed_bonus(ca, dt.date(2026, 10, 25), AG)
    check("… son bonus : le minimum de 40 subs aussi",
          "🥇 **Instagram VA 141** — **261 subs** → **5.00$**" in ba["description"]
          and "🥈 **Instagram VA 100** — **3 subs** → pas de prime (min. 40)" in ba["description"]
          and "Minimum 40 subs" in ba["description"], ba["description"])
    check("… Twitter relu une fois, puis repris (un quart d'heure)",
          [a for a in APPELS if a[0] == TW] == [(TW, "tracking_abonnes", J, J)]
          and ca2["lignes"][0]["va"] == "Instagram VA 141", APPELS)
    with contextlib.redirect_stdout(io.StringIO()):
        cq = pd.classement(J, J, gid=AG, mesure="agency_quinzaine")
    check("… pas à la quinzaine : ses lignes YouLab comptent déjà ces abonnés",
          [x["va"] for x in cq["lignes"]] == ["Instagram VA 001"], cq["lignes"])
    pd._TW_INTERNES.clear()
    SOURCES[(TW, "tracking_abonnes")] = {"lignes": [], "illisibles": [], "frais": False,
                                         "erreur": "MyPuls muet"}
    with contextlib.redirect_stdout(io.StringIO()):
        cm = pd.classement(J, J, gid=AG)
    check("… Twitter muet : Instagram VA 141 sans relevé, jamais zéro",
          "Instagram VA 141" in cm["illisibles"]
          and "Instagram VA 141" not in [x["va"] for x in cm["lignes"]], cm)
    SOURCES[(TW, "tracking_abonnes")] = TWITTER
    pd._TW_INTERNES.clear()

    # ── Threads, la semaine ──
    LIENS = [{"id": f"i{k}", "type": "page"} for k in range(30)] + [{"id": "d1", "type": "directlink"}]
    ENTS = {41: [f"i{k}" for k in range(25)] + ["d1"], 12: ["i25", "i26"], 124: ["i27", "i28"]}
    lots = []

    def faux_releve(gid, ids, d0, d1, mesure=None, etiquette="podium", directs=None):
        lots.append((list(ids), sorted(set(ids) & (directs or set()))))
        return 2 * len(ids), {"US": len(ids), "GB": 1, "CA": 1, "FR": 3}
    pd._liens_twitter = lambda etiq: (list(LIENS), True)
    pd._entites_jessye = lambda liens: {n: list(v) for n, v in ENTS.items()}
    pd._releve_liens = faux_releve
    SOURCES[(TH, "gms_bouton")] = {"lignes": [ligne("Threads 92", 92, 20), ligne("Threads 87", 87, 15)],
                                   "illisibles": [], "frais": True}
    with contextlib.redirect_stdout(io.StringIO()):
        ct = pd.classement(L, J, gid=TH, mesure=pd._mesure_podium(TH))
    v141 = ct["lignes"][0]
    check("Threads, la semaine : « Threads 142 », clics US + UK de tous les liens internes",
          [x["va"] for x in ct["lignes"]] == ["Threads 142", "Threads 92", "Threads 87"]
          and v141["clics"] == 28 + 2 and v141["gbl"] == 56 and v141.get("interne") is True
          and v141["comptes"] == 2 and v141["numero"] == 142, ct["lignes"])
    check("… par lots de 20 au plus, sans les liens des VA Discord (VA 124), le lien direct dit",
          all(len(ids) <= 20 for ids, _ in lots) and len(lots) == 2
          and sorted(i for ids, _ in lots for i in ids) == sorted(ENTS[41] + ENTS[12])
          and any(d == ["d1"] for _, d in lots), lots)
    lots.clear()
    pd._releve_liens = lambda gid, ids, *a, **k: ((None, None) if "i20" in ids else (1, {"US": 1}))
    with contextlib.redirect_stdout(io.StringIO()):
        cmt = pd.classement(L, J, gid=TH, mesure=pd._mesure_podium(TH))
    check("… un lot muet : Threads 142 sans relevé, jamais un total partiel",
          "Threads 142" in cmt["illisibles"]
          and "Threads 142" not in [x["va"] for x in cmt["lignes"]], cmt)
    pd._releve_liens = faux_releve
    jeton = pd._EN_QUINZAINE_THREADS.set(True)
    try:
        cin = pd.classement(L, J, gid=TH)
    finally:
        pd._EN_QUINZAINE_THREADS.reset(jeton)
    check("… pas dans le relevé des VA de Threads que fait la quinzaine (elle a les siens)",
          [x["va"] for x in cin["lignes"]] == ["Threads 92", "Threads 87"])

    # ── Threads, la quinzaine ──
    vus_ctx = []

    def fausse_quinzaine(debut, fin, gid, etiquette):
        vus_ctx.append(pd._EN_QUINZAINE_THREADS.get())
        return {"lignes": [
            ligne("Threads VA 141", 41, 100, gbl=300, at_clics=1000, jessye=41, ids=["a"]),
            ligne("Threads VA 1124", 124, 60, gbl=70, at_clics=70, jessye=124, ids=["c"]),
            ligne("Threads VA 112", 12, 50, gbl=100, at_clics=200, jessye=12, ids=["b"]),
            ligne("Threads VA 023", 23, 40, gbl=90, at_clics=95, cle_ig="amelia:44"),
            ligne("Threads 92", 92, 30, gbl=31, at_clics=40)],
            "illisibles": [], "frais": True}
    pd._quinzaine_sans_internes = fausse_quinzaine
    with contextlib.redirect_stdout(io.StringIO()):
        cq = pd._quinzaine_us_gbl(L, J, TH, "quinzaine")
    q = [(x["va"], x["clics"], x.get("gbl"), x.get("at_clics")) for x in cq["lignes"]]
    check("Threads, la quinzaine : les « Threads VA 1nn » internes en « Threads 142 » "
          "(US, GBL, all-time additionnés) ; Va IG et Threads n intacts",
          q[0] == ("Threads 142", 150, 400, 1200)
          and ("Threads VA 023", 40, 90, 95) in q and ("Threads 92", 30, 31, 40) in q
          and cq["lignes"][0]["ids"] == ["a", "b"] and vus_ctx == [True], q)
    # « sur Threads je vois les mecs de Twitter, ils ne doivent pas être là »
    check("… les VA Discord de Twitter (Threads VA 1124) n'y sont plus",
          "Threads VA 1124" not in [x[0] for x in q], q)
    ENTS_J = {41: ["a"], 12: ["b"], 124: ["c"]}
    pd._entites_jessye_toutes = lambda liens: {n: list(v) for n, v in ENTS_J.items()}
    jeton = pd._EN_QUINZAINE_THREADS.set(True)
    try:
        dans_q = _SAUVE["_entites_jessye"]([])
    finally:
        pd._EN_QUINZAINE_THREADS.reset(jeton)
    check("… ni relevés : dans la quinzaine, seuls les comptes internes sont lus (pas un appel "
          "GetMySocial pour un VA de Twitter) ; ailleurs, tous",
          sorted(dans_q) == [12, 41] and sorted(_SAUVE["_entites_jessye"]([])) == [12, 41, 124], dans_q)
    pd.VA_TWITTER_SUR_THREADS = True
    jeton = pd._EN_QUINZAINE_THREADS.set(True)
    try:
        remis = _SAUVE["_entites_jessye"]([])
    finally:
        pd._EN_QUINZAINE_THREADS.reset(jeton)
    with contextlib.redirect_stdout(io.StringIO()):
        cq3 = pd._quinzaine_us_gbl(L, J, TH, "quinzaine")
    pd.VA_TWITTER_SUR_THREADS = False
    check("… VA_TWITTER_SUR_THREADS = True : ils reviennent",
          sorted(remis) == [12, 41, 124]
          and "Threads VA 1124" in [x["va"] for x in cq3["lignes"]], cq3["lignes"])
    pd._quinzaine_sans_internes = lambda *a: {"lignes": [
        ligne("Threads VA 141", 41, 100, gbl=300, at_clics=None, jessye=41),
        ligne("Threads VA 112", 12, 50, gbl=100, at_clics=200, jessye=12)], "illisibles": []}
    with contextlib.redirect_stdout(io.StringIO()):
        cq2 = pd._quinzaine_us_gbl(L, J, TH, "quinzaine")
    check("… un all-time manquant : aucun all-time plutôt qu'un total trop petit",
          cq2["lignes"][0]["at_clics"] is None, cq2["lignes"])

    # ── le bonus du jour de Threads, en clics ──
    cb = {"lignes": [ligne("Threads 142", 142, 900, clics_subs=950, gbl=2000, interne=True),
                     ligne("Threads 92", 92, 300, clics_subs=420, gbl=500),
                     ligne("Threads 87", 87, 390, clics_subs=399, gbl=900)], "illisibles": []}
    bt = pd.embed_bonus(cb, dt.date(2026, 10, 25), TH)
    check("Threads : « 💸 Bonus clics du jour », « US : n · GBL : n », rangé au US (US + UK + CA)",
          bt["title"] == "💸 Bonus clics du jour"
          and "🥇 **Threads 142** — US : **950** · GBL : **2000** → **5.00$**" in bt["description"]
          and "🥈 **Threads 92** — US : **420** · GBL : **500** → **3.00$**" in bt["description"]
          and "🥉 **Threads 87** — US : **399** · GBL : **900** → pas de prime (min. 400 US)"
          in bt["description"]
          and "Minimum 400 clics US dans la journée pour toucher la prime." in bt["description"],
          bt["description"])
    check("… la consigne USDC et « Un seul prix par personne », comme Twitter",
          "💳 Mon adresse USDC" in bt["description"]
          and bt["footer"]["text"].startswith("Un seul prix par personne"))
    check("… et son 👀 lit ces lignes", [v for v, _n in pd._ligne_affichee("Threads").findall(
        bt["description"])] == ["Threads 142", "Threads 92", "Threads 87"])

    # ── les numéros réservés ──
    _vrai_nf = pd.NUMEROS_FICHIER
    try:
        pd.NUMEROS_FICHIER = TMP / "podium_numeros.json"
        pd.NUMEROS_FICHIER.write_text(json.dumps({f"k{n}": n for n in range(1, 141)}), encoding="utf-8")
        neufs = pd.numeros(["nouveau_a", "nouveau_b"])
        check("141 et 142 réservés : jamais donnés à un VA (les suivants : 143, 144)",
              (neufs["nouveau_a"], neufs["nouveau_b"]) == (143, 144)
              and {pd.VA_INTERNE_AGENCY, pd.VA_INTERNE_THREADS} == {141, 142} <= pd.NUMEROS_RESERVES,
              neufs)
    finally:
        pd.NUMEROS_FICHIER = _vrai_nf

    # ── 👀 Pseudos ──
    pd._noms_libelles_sans_internes = lambda gid: (
        {12: "Roucham", 41: "Eddy", 124: "bigmaxm"} if gid == TW
        else {"Threads 92": "drick"} if gid == TH else {"Instagram VA 100": "x"})
    texte = "comptes internes (4 comptes) : Kylmich, Roucham, Roucham SPAM, Eddy"
    check("👀 : « comptes internes (N comptes) » et leurs noms (tracking en service), pour VA 41 "
          "sur Twitter, Threads 142, Instagram VA 141",
          pd._noms_libelles(TW)[41] == texte and pd._noms_libelles(TH)["Threads 142"] == texte
          and pd._noms_libelles(AG)["Instagram VA 141"] == texte and pd._noms_libelles(TW)[124] == "bigmaxm",
          pd._noms_libelles(TW))
    pd._staff = lambda p: True
    rep = pd._voir_pseudos_message({"guild_id": TW, "message": {"embeds": [b]}})
    check("… sous le bonus, au staff, en privé : VA 41 → les comptes internes",
          rep["data"]["flags"] == 64 and f"🥇 VA 41 · **{texte}** · 261 subs" in rep["data"]["content"],
          rep["data"]["content"])
    check("… les places payées seulement : VA 95 (8 subs, sous le minimum) n'y est pas",
          "VA 124" in rep["data"]["content"] and "VA 95" not in rep["data"]["content"],
          rep["data"]["content"])

    # ── la prime : personne n'est payé au nom de VA 41 ──
    sv = TMP / "suivi_va.json"
    suivi_va.ETAT_FICHIER = sv
    suivi_va.adresse_de = lambda gid, uid: "ADR"
    tk._etat = lambda: {"tickets": {f"{TW}:u124": {"salon": "S124", "manager": "M"}}}
    posts = []
    tk._api = lambda m, chemin, **kw: (posts.append((m, chemin, kw.get("json"))) or (200, {"id": "1"}))
    paye = {"lignes": [dict(ligne("VA 41", 41, 1478), interne=True), ligne("VA 124", 124, 151),
                       ligne("VA 95", 95, 15)]}
    bilan = suivi_va.annoncer_primes(TW, paye, L, dt.date(2026, 10, 25))
    check("prime de la semaine : VA 41 sauté (« internes »), le 2e annoncé à 5$, personne d'autre",
          bilan.get("internes") == ["VA 41"] and len(posts) == 1 and posts[0][1] == "/channels/S124/messages"
          and "2e de la semaine — 5.00$" in posts[0][2]["embeds"][0]["title"], (bilan, posts))
    # « minimum 100 subs / semaine » (propriétaire, 25/10/2026)
    check("… le 3e sous 100 subs (VA 95, 15) : ni annonce, ni adresse demandée",
          bilan.get("sous_minimum") == ["VA 95 (15)"], bilan)
    check("prime_semaine_due : 100 subs sur Twitter et Instagram, 1000 clics sur Threads, jamais l'interne",
          pd.prime_semaine_due(TW, {"clics": 100}) and not pd.prime_semaine_due(TW, {"clics": 99})
          and not pd.prime_semaine_due(AG, {"clics": 51}) and pd.prime_semaine_due(TH, {"clics": 1000})
          and not pd.prime_semaine_due(TH, {"clics": 999}) and not pd.prime_semaine_due(TH, {"clics": 1})
          and not pd.prime_semaine_due(TH, {"clics": 0})
          and not pd.prime_semaine_due(TH, {"clics": 1478, "interne": True})
          and not pd.prime_semaine_due(TW, {"clics": 1478, "interne": True}))

    # ── l'interrupteur ──
    pd.INTERNES_REUNIS = False
    with contextlib.redirect_stdout(io.StringIO()):
        co = pd.classement(J, J, gid=TW, mesure="tracking_abonnes")
        cao = pd.classement(J, J, gid=AG)
    check("INTERNES_REUNIS = False : chaque compte sur sa ligne, rien ajouté à Agency, 👀 comme avant",
          [x["va"] for x in co["lignes"]] == [x["va"] for x in TWITTER["lignes"]]
          and [x["va"] for x in cao["lignes"]] == ["Instagram VA 100", "Instagram VA 63"]
          and pd._noms_libelles(TW).get(41) == "Eddy")
    check("le classement de tout le podium (bonus, semaine, quinzaine) passe par le regroupement",
          pd.classement.__doc__.startswith("Le classement du serveur, ses comptes internes")
          and pd._classement_sans_internes is not pd.classement)
finally:
    for k, v in _SAUVE.items():
        setattr(pd, k, v)
    lv._etat = _SAUVE_LV
    for k, v in _SAUVE_SV.items():
        setattr(suivi_va, k, v)
    for k, v in _SAUVE_TK.items():
        setattr(tk, k, v)
    pd._TW_INTERNES.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
