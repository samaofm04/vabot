# -*- coding: utf-8 -*-
"""tests_podium_va_ig_subs.py — le podium de la semaine de Va IG aux vrais abonnés.

Propriétaire, 27/10/2026, devant « 208 subs » pour un lien d'environ 200
clics : « c'est impossible ». Puis : « Oui, vrais subs », et pour le minimum,
« 100 comme les autres ».

Ce qui est vérifié (podium_discord, suivi_va) :
  - Va IG compte sa semaine (et la paie) aux abonnés OF + MYM de subs_va,
    comme sa quinzaine, chaque heure ;
  - primes_semaine : 100 subs au moins, jamais à 0 ; un seul prix par
    personne (une ligne par model) : le prix suivant passe à la personne
    suivante ;
  - le message : « Abonnés OF + MYM via Instagram », plus « clics FR » ; 💰
    seulement aux lignes payées, « pas de prime (min. 100) », « déjà primé »,
    la ligne du minimum sous le bloc des primes ;
  - l'avis privé (_annoncer_primes_fr) suit exactement le podium : rang du
    prix, montant, personne déjà primée sautée, rien sous le minimum.

Aucun appel réseau, rien dans data/. Lancement :
python tests_podium_va_ig_subs.py
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_fr                        # noqa: E402
import podium_discord as pd            # noqa: E402
import requests                        # noqa: E402
import safe_json                       # noqa: E402
import subs_va                         # noqa: E402
import suivi_va as sv                  # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


IG = pd.VA_IG_ID
LUN, DIM = dt.date(2026, 10, 26), dt.date(2026, 11, 1)


def ligne(model, n, subs):
    nom = {"amelia": "Amelia", "alicia": "Alicia", "emma": "Emma"}[model]
    return {"va": f"{nom} VA {n}", "numero": n, "clics": subs, "liens": 1, "spam": False,
            "model": model}


# fahnih tient Amelia VA 44 et Alicia VA 21 ; priscah Emma VA 34 ; Lumière Amelia VA 46
NUMEROS = {"amelia": {"fahnih": 44, "lumiere": 46, "autre": 7}, "alicia": {"fahnih": 21},
           "emma": {"priscah": 34}}
HAUT = [ligne("amelia", 44, 156), ligne("alicia", 21, 134), ligne("emma", 34, 130),
        ligne("amelia", 46, 115), ligne("amelia", 7, 90)]
VRAI = [ligne("amelia", 44, 56), ligne("alicia", 21, 34), ligne("emma", 34, 30),
        ligne("amelia", 46, 15)]

TMP = pathlib.Path(tempfile.mkdtemp(prefix="va_ig_subs_"))
pf = pd.SERVEURS[IG]
_SAUVE_PF = dict(pf)
_SAUVE = (liens_fr.NUMEROS, safe_json.load, requests.post, sv.ETAT_FICHIER,
          os.environ.get("DISCORD_TOKEN"), subs_va.classement_va_ig)
try:
    (TMP / "numeros_va_fr.json").write_text(json.dumps(NUMEROS), encoding="utf-8")
    liens_fr.NUMEROS = TMP / "numeros_va_fr.json"
    # les noms tels quels (« Amelia VA 44 ») : la marque a ses tests (tests_podium_marque.py)
    pf.pop("marque", None)

    check("Va IG : la semaine aux vrais abonnés, chaque heure, minimum 100, un prix par personne",
          pd._mesure_podium(IG) == "abonnes" and pd._minutes_podium(IG) == 60
          and pd.MINIMUM_SEMAINE.get(IG) == 100 and pf.get("un_prix_par_personne") is True)
    vus = []
    subs_va.classement_va_ig = lambda d, f: (vus.append((d, f)) or
                                             {"lignes": list(VRAI), "illisibles": [], "frais": True})
    _part = pd._partis
    pd._partis = lambda gid: {}
    try:
        cl = pd.classement(LUN, DIM, gid=IG, mesure=pd._mesure_podium(IG))
    finally:
        pd._partis = _part
    check("… la semaine lit subs_va.classement_va_ig (la quinzaine aussi), plus GetMySocial",
          vus == [(LUN, DIM)] and [x["clics"] for x in cl["lignes"]] == [56, 34, 30, 15], vus)

    p = pd.primes_semaine(IG, HAUT)
    check("un seul prix par personne : fahnih 10 $, sa 2e ligne rien, priscah 5 $, Lumière 3 $, "
          "puis plus rien (et 90 subs : sous le minimum)",
          [x["prime"] for x in p] == [10.0, None, 5.0, 3.0, None]
          and [x["raison"] for x in p] == ["", "un_seul_prix", "", "", ""]
          and [x["rang"] for x in p] == [0, None, 1, 2, None], p)
    p2 = pd.primes_semaine(IG, [ligne("amelia", 44, 120), ligne("amelia", 7, 90)])
    check("sous 100 subs : pas de prime, « minimum »",
          [(x["prime"], x["raison"]) for x in p2] == [(10.0, ""), (None, "minimum")], p2)
    check("les chiffres de la semaine (56, 34, 30, 15) : aucune prime",
          all(x["prime"] is None and x["raison"] == "minimum" for x in pd.primes_semaine(IG, VRAI)))
    check("jamais à 0, même sans minimum",
          not pd.prime_semaine_due("autre", {"clics": 0}) and pd.prime_semaine_due("autre", {"clics": 1}))

    e = pd.embed_podium({"lignes": HAUT, "illisibles": [], "frais": True}, LUN, DIM,
                        en_cours=True, gid=IG)
    d = e["description"]
    check("en-tête : « Abonnés OF + MYM via Instagram », plus « clics FR »",
          "Abonnés **OF + MYM** via Instagram" in d and "clics **FR**" not in d, d[:300])
    check("💰 aux lignes payées, « déjà primé » sur la 2e ligne de fahnih, 3 $ à la 4e ligne",
          "🥇 **Amelia VA 44** — **156** subs · 💰 **10$**" in d
          and "🥈 **Alicia VA 21** — **134** subs · déjà primé (un seul prix par personne)" in d
          and "🥉 **Emma VA 34** — **130** subs · 💰 **5$**" in d
          and "4. Amelia VA 46 — **115** subs · 💰 **3$**" in d
          and "5. Amelia VA 7 — **90** subs\n" in d, d)
    check("… le minimum dit sous le bloc des primes",
          "🥉 3e → **3$**\nMinimum 100 subs dans la semaine pour toucher la prime." in d, d)
    ev = pd.embed_podium({"lignes": VRAI, "illisibles": [], "frais": True}, LUN, DIM,
                         en_cours=True, gid=IG)["description"]
    check("les chiffres de la semaine : ni 💰 dans les lignes, « pas de prime (min. 100) » au top 3",
          "🥇 **Amelia VA 44** — **56** subs · pas de prime (min. 100)" in ev
          and "🥉 **Emma VA 34** — **30** subs · pas de prime (min. 100)" in ev
          and "4. Amelia VA 46 — **15** subs\n" in ev
          and not [l for l in ev.splitlines() if l.startswith(("🥇", "🥈", "🥉", "4.")) and "💰" in l], ev)

    # l'avis privé suit le podium
    users = {u: {"channel_id": f"salon-{u}"} for u in ("fahnih", "lumiere", "priscah", "autre")}
    annonces = []
    vrai_load = _SAUVE[1]
    sv.ETAT_FICHIER = TMP / "suivi_va.json"
    safe_json.load = lambda chemin, default=None: (
        users if pathlib.Path(chemin).name == "users.json" else vrai_load(chemin, default=default))
    requests.post = lambda url, timeout=None, headers=None, json=None: (
        annonces.append((url, json)) or types.SimpleNamespace(status_code=200))
    os.environ["DISCORD_TOKEN"] = "faux-jeton"
    b = sv._annoncer_primes_fr(IG, {"lignes": HAUT}, LUN, DIM)
    titres = [(u.split("/channels/")[1].split("/")[0], j["embeds"][0]["title"]) for u, j in annonces]
    check("avis privés : fahnih 1er 10 $, priscah 2e 5 $, Lumière 3e 3 $ — comme le podium",
          titres == [("salon-fahnih", "🥇 1e de la semaine — 10.00$"),
                     ("salon-priscah", "🥈 2e de la semaine — 5.00$"),
                     ("salon-lumiere", "🥉 3e de la semaine — 3.00$")], titres)
    check("… la 2e ligne de fahnih : « un seul prix », personne d'autre prévenu",
          b["un_seul_prix"] == ["Alicia VA 21"] and len(annonces) == 3, b)
    annonces.clear()
    sv.ETAT_FICHIER = TMP / "suivi_va_2.json"
    b2 = sv._annoncer_primes_fr(IG, {"lignes": VRAI}, LUN, DIM)
    check("les chiffres de la semaine : aucun avis, les trois premiers sous le minimum",
          not annonces and b2.get("sous_minimum") == ["Amelia VA 44 (56)", "Alicia VA 21 (34)",
                                                       "Emma VA 34 (30)"], b2)
finally:
    (liens_fr.NUMEROS, safe_json.load, requests.post, sv.ETAT_FICHIER) = _SAUVE[:4]
    if _SAUVE[4] is None:
        os.environ.pop("DISCORD_TOKEN", None)
    else:
        os.environ["DISCORD_TOKEN"] = _SAUVE[4]
    subs_va.classement_va_ig = _SAUVE[5]
    pf.clear()
    pf.update(_SAUVE_PF)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
