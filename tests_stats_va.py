"""La page perso d'un VA de TRUST INSTAGRAM (stats_va) et son lien dans « 📈 Mes stats ».

Propriétaire, 03/11/2026 : « un petit lien perso pour chaque VA où il voit
uniquement son tracking link ... depuis toujours, aujourd'hui, cette quinzaine,
quinzaine précédente ... les clics GetMySocial, les clics globaux, les clics
Infloww et les subs », pour le serveur Instagram, donné dans le ticket ; puis
« le truc de base, quinzaine et tout, comme d'hab », et en bas seulement les
sources : « API officielle d'Infloww utilisée, avec la doc, et aussi pour
GetMySocial, c'est tout ».

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/.
Seules les RÉPONSES des sources sont simulées (MyPuls tracking-links, Infloww,
GetMySocial) ; les calculs sont les vrais (subs_va._subs_of,
subs_depuis_toujours, _communs, la copie « lia » d'infloww_liens et ses
relevés).
  1. La clé : une par VA, stable, fichier 0600, retrouvée en temps constant ;
     fausse, vide ou courte : rien. Hors TRUST INSTAGRAM : pas de lien.
  2. Les chiffres d'une période : clics GMS de clics_du_va, subs de
     MyPuls « à son nom », clics Infloww des liens Lia (+ Emy depuis toujours),
     CVR (subs ÷ visites MyPuls), $ / sub (net ÷ subs), Gagné selon la grille
     quinzaine par quinzaine (palier de la quinzaine entière), « — » jamais 0
     pour l'illisible.
  3. La page : choix de la période (raccourcis de la page Lia, clé gardée),
     la ligne de la page Lia (@ du VA, CVR et $ / sub colorés, Gagné), pas la
     liste de ses trackings, en bas les trois API officielles liées à leur doc
     et rien d'autre, aucun autre VA, ni revenu total ni paiement ni gain /
     perte, tout échappé.
  4. La route /mes-stats : 404 sans clé, clé fausse, VA parti ou sans fiche ;
     en-têtes no-store, noindex, no-referrer.
  5. « 📈 Mes stats » : le lien sous les chiffres sur TRUST INSTAGRAM, pas
     ailleurs ; une clé non écrite ne fait pas tomber le message. L'accueil
     épinglé du ticket : la page sous « 🔗 Ton lien » (« mets-le ici, en bas de
     son lien »), refaite avec lui, pas ailleurs.
  6. Rien d'écrit dans le vrai data/.

Lancer depuis la racine du dépôt : python tests_stats_va.py
"""
from __future__ import annotations

import datetime as dt
import html
import io
import json
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


VRAIS = [BOT / "data" / n for n in ("stats_va_cles.json", "infloww_liens_clics_infloww_lia.json")]
AVANT = {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS}

import stats_va as sv           # noqa: E402
import subs_va                  # noqa: E402
import liens_va                 # noqa: E402
import podium_discord as pod    # noqa: E402
import infloww_liens as il      # noqa: E402
import tickets_discord          # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="stats_va_"))
sv.CLES_FICHIER = TMP / "stats_va_cles.json"
# TW : Threads (le nom est resté) -- TRUST TWITTER et THREADS ont leur page
# depuis le 04/11 (vérifié plus bas), « ailleurs » est Va IG
GID, TW = sv.AGENCY_IG_ID, subs_va.THREADS_ID
U108, U63 = "111111111111111108", "111111111111111063"
JOUR = dt.date(2026, 11, 3)
BASCULE = int(dt.datetime(2026, 10, 28, 15, 0).timestamp())
LIA, SEREN, EMY = ("https://onlyfans.com/liasxcret/c104", "https://onlyfans.com/seren.vale/c236",
                   "https://onlyfans.com/emy.brw/c117")
FICHES = {
    (GID, U108): {"numero": 108, "pseudo": "duc_duchesse", "link_id": "lnk_a", "public_url": "getmysocial.com/ducx",
                  "quand": int(dt.datetime(2026, 10, 20, 12, 0).timestamp()),
                  "tracking": LIA, "variante": {"modele": "Seren", "tracking": SEREN},
                  "anciens_trackings": [EMY],
                  "bascule": {"vers": 3992, "de": EMY, "quand": BASCULE}},
    (GID, U63): {"numero": 63, "pseudo": "autre_va_secret", "link_id": "lnk_b",
                 "tracking": "https://onlyfans.com/liasxcret/c98",
                 "variante": {"modele": "Seren", "tracking": "https://onlyfans.com/seren.vale/c230"}},
}
PARTIS = set()
APPELS = {"clics": 0}
liens_va.lien_de = lambda g, u: dict(FICHES.get((str(g), str(u))) or {})
tickets_discord.partis = lambda g: {u: 1.0 for (gg, u) in PARTIS if gg == g}
pod._aujourdhui = lambda: JOUR

# ─── MyPuls : ses réponses, période par période (visites, subs) ──────────
P = {"toujours": ("", ""), "aujourdhui": ("2026-11-03", "2026-11-03"), "periode": ("2026-11-01", "2026-11-03"),
     "precedente": ("2026-10-16", "2026-10-31"), "libre": ("2026-10-20", "2026-10-22")}
NOM = "Instagram VA 108 @duc_duchesse"
#            (visites, subs, net en centimes) par tracking : Lia, Seren, Emy
MP = {P["aujourdhui"]: {"liasxcret/c104": (12, 1, 300), "seren.vale/c236": (3, 0, 0), "emy.brw/c117": (0, 0, 0)},
      P["periode"]: {"liasxcret/c104": (107, 3, 900), "seren.vale/c236": (20, 1, 200), "emy.brw/c117": (0, 0, 0)},
      P["precedente"]: {"liasxcret/c104": (798, 10, 2000), "seren.vale/c236": (50, 5, 1500),
                        "emy.brw/c117": (30, 2, 500)},
      P["libre"]: {"liasxcret/c104": (0, 0, 0), "seren.vale/c236": (5, 0, 0), "emy.brw/c117": (10, 6, 600)},
      # le revenu depuis toujours (lecture du 01/01/2024 à aujourd'hui)
      ("2024-01-01", "2026-11-03"): {"liasxcret/c104": (905, 15, 3000), "seren.vale/c236": (78, 8, 1700),
                                     "emy.brw/c117": (40, 2, 500)}}
TOTAUX = {"liasxcret/c104": (905, 15), "seren.vale/c236": (78, 8), "emy.brw/c117": (40, 2),
          "liasxcret/c98": (0, 0), "seren.vale/c230": (0, 0)}
NOMS = {"liasxcret/c104": NOM, "seren.vale/c236": NOM, "emy.brw/c117": NOM,
        "liasxcret/c98": "Instagram VA 63 @autre_va_secret", "seren.vale/c230": "Instagram VA 63 @autre_va_secret"}
MYPULS = {"muet": False}


def _lire_mypuls(du, au, forcer=False):
    if MYPULS["muet"]:
        return None, "HTTP 503"
    per = MP.get((du, au), {})
    out = {}
    for t, (vt, st) in TOTAUX.items():
        v, s_, net = per.get(t, (0, 0, 0))
        out[t] = {"visites": v, "total": vt, "subs": s_, "subs_total": st, "nom": NOMS[t], "net": net}
    return out, ""


pod._lire_mypuls = _lire_mypuls

# ─── GetMySocial : (US, tous pays) ───────────────────────────────────────
GMS = {"2024-01-01": {"US": 500, "FR": 400, "DE": 100}, "2026-11-03": {"US": 10, "FR": 10},
       "2026-11-01": {"US": 80, "FR": 70}, "2026-10-16": {"US": 300, "GB": 300, "FR": 300},
       "2026-10-20": {"US": 40, "CA": 30}}
GMS_MUET = set()


def _clics_du_va(g, u, periodes):
    APPELS["clics"] += 1
    out = []
    for a, _b in periodes:
        pays = GMS.get(a.isoformat())
        out.append(None if pays is None or a.isoformat() in GMS_MUET else (pays.get("US", 0), sum(pays.values())))
    return out


pod.clics_du_va = _clics_du_va

# ─── Infloww : la vraie copie « lia », ses relevés dans un dossier à part ─
lia = il.profil("lia")
lia.RELEVES_CVR_FICHIER = TMP / "releves_lia.json"
lia._aujourdhui = lambda: JOUR.isoformat()
# cumuls relevés chaque jour (le dernier vu) ; c104 créé le 27/10 chez Infloww
(TMP / "releves_lia.json").write_text(json.dumps({"jours": {
    "2026-10-31": {"104": 798, "98": 0}, "2026-11-02": {"104": 893, "98": 0}},
    "crees": {"104": "2026-10-27", "98": "2026-10-27"}}))
INFLOWW = {"lia": 905, "muet": False}
lia._infloww = lambda createrice="": ({"erreur": "Infloww : 503"} if INFLOWW["muet"] else
                                      {"erreur": "", "liens": [{"code": "104", "clics": INFLOWW["lia"], "cree": "2026-10-27"},
                                                               {"code": "98", "clics": 0, "cree": "2026-10-27"}]})
il._infloww = lambda createrice="": ({"erreur": "", "liens": [{"code": "117", "clics": 40}]}
                                     if createrice == "emy.brw" else {"erreur": "pas lu"})

print("1. La clé")
t108 = sv.jeton(GID, U108)
check("une clé par VA, stable d'un clic à l'autre",
      len(t108) >= 20 and sv.jeton(GID, U108) == t108 and sv.jeton(GID, U63) != t108)
check("fichier des clés en 0600", stat.S_IMODE(sv.CLES_FICHIER.stat().st_mode) == 0o600)
check("la clé retrouve son VA", sv.qui(t108) == (GID, U108), sv.qui(t108))
check("clé fausse, vide ou courte : rien",
      sv.qui("x" * 32) is None and sv.qui("") is None and sv.qui(None) is None
      and sv.qui(t108[:10]) is None and sv.qui(t108 + "a") is None)
check("le lien : https://youl4b.com/mes-stats?t=<sa clé>",
      sv.lien(GID, U108) == f"https://youl4b.com/mes-stats?t={t108}", sv.lien(GID, U108))
check("hors des TRUST (Va IG), pas de lien (ni clé créée)",
      sv.lien(subs_va.VA_IG_ID, U108) == "" and f"{subs_va.VA_IG_ID}:{U108}" not in sv._cles())
# 04/11/2026, devant le menu de Threads : « il manque les trucs pour mes stats
# et tout [...] un peu comme sur Twitter »
check("TRUST THREADS : sa page aussi, une clé à lui",
      sv.lien(TW, U108).startswith("https://youl4b.com/mes-stats?t=") and sv.lien(TW, U108) != sv.lien(GID, U108))

print("2. Les chiffres")
sv._CACHE.clear()
D = {k: sv.chiffres(GID, U108, *v) for k, v in P.items()}
check("clics GMS US et globaux, sur la période demandée",
      [(D[k]["us"], D[k]["glob"]) for k in P] == [(500, 1000), (10, 20), (80, 150), (300, 900), (40, 70)],
      [(D[k]["us"], D[k]["glob"]) for k in P])
check("subs : depuis toujours = compteurs MyPuls (15 + 8 + 2), puis la période",
      [D[k]["subs"] for k in P] == [25, 1, 4, 17, 6], [D[k]["subs"] for k in P])
check("mêmes subs que « Mes stats » (subs_du_va) sur ses trois périodes",
      [D[k]["subs"] for k in ("aujourdhui", "periode", "precedente")]
      == [subs_va.subs_du_va(GID, U108, JOUR)[k]["n"] for k in ("aujourdhui", "periode", "precedente")])
check("clics Infloww depuis toujours : Lia + ancien Emy (905 + 40)", D["toujours"]["infloww"] == 945,
      D["toujours"])
check("clics Infloww d'une période : Lia, par différence de relevés",
      [D[k]["infloww"] for k in ("aujourdhui", "periode", "precedente", "libre")] == [12, 107, 798, 0],
      [D[k]["infloww"] for k in ("aujourdhui", "periode", "precedente", "libre")])
check("la grille : 0,70 $ jusqu'à 499, 0,80 dès 500, 0,90 dès 800, 1 dès 1000, 1,20 dès 1250",
      [sv.prix_du_sub(n) for n in (0, 499, 500, 799, 800, 999, 1000, 1249, 1250, 5000)]
      == [0.70, 0.70, 0.80, 0.80, 0.90, 0.90, 1.00, 1.00, 1.20, 1.20])
check("Gagné d'une quinzaine : ses subs × le prix de son palier (17 × 0,70)", D["precedente"]["gagne"] == 11.9,
      D["precedente"]["gagne"])
check("Gagné depuis toujours : quinzaine par quinzaine, dès la quinzaine de ses liens, entière (17 × 0,70 + 4 × 0,70)",
      D["toujours"]["gagne"] == 14.7, D["toujours"]["gagne"])
check("Gagné d'une période dans une quinzaine : ses subs au palier de la quinzaine entière (6 × 0,70)",
      D["libre"]["gagne"] == 4.2, D["libre"]["gagne"])
_sauve_mp = dict(MP)
MP[P["precedente"]] = {"liasxcret/c104": (798, 500, 2000), "seren.vale/c236": (50, 5, 1500), "emy.brw/c117": (30, 5, 500)}
dpal = sv.chiffres(GID, U108, *P["precedente"])
dpal_l = sv.chiffres(GID, U108, *P["libre"])
MP.clear()
MP.update(_sauve_mp)
check("palier atteint : 510 subs sur la quinzaine → les 510 à 0,80 $ (408 $)", dpal["gagne"] == 408.0, dpal["gagne"])
check("une période dans cette quinzaine paie au palier de la quinzaine entière (6 × 0,80)", dpal_l["gagne"] == 4.8,
      dpal_l["gagne"])
check("CVR = subs ÷ visites MyPuls de ses liens (17 ÷ 878)", abs(D["precedente"]["cvr"] - 1700 / 878) < 1e-9,
      D["precedente"]["cvr"])
check("CVR depuis toujours : compteurs depuis la création (25 ÷ 1023)", abs(D["toujours"]["cvr"] - 2500 / 1023) < 1e-9,
      D["toujours"]["cvr"])
check("$ / sub = revenu net MyPuls de ses liens ÷ subs (40 $ ÷ 17)", abs(D["precedente"]["par_sub"] - 40 / 17) < 1e-9,
      D["precedente"]["par_sub"])
check("$ / sub depuis toujours (52 $ ÷ 25)", abs(D["toujours"]["par_sub"] - 52 / 25) < 1e-9, D["toujours"]["par_sub"])
check("une période sans sub : $ / sub « — », pas une division par zéro",
      sv.chiffres(GID, U108, "2026-10-25", "2026-10-25")["par_sub"] is None)
check("une période : « du/au » gardés ; depuis toujours : vides",
      (D["libre"]["du"], D["libre"]["au"]) == P["libre"] and (D["toujours"]["du"], D["toujours"]["au"]) == ("", ""))
NOMS["seren.vale/c236"] = "LIEN COMMUN AGENCE"
dc = sv.chiffres(GID, U108, *P["periode"])
NOMS["seren.vale/c236"] = NOM
check("un tracking pas à son nom n'est pas compté, et c'est dit",
      dc["subs"] == 3 and dc["communs"] == [SEREN], (dc["subs"], dc["communs"]))
NOMS["liasxcret/c104"] = "LIEN COMMUN AGENCE"
dl = sv.chiffres(GID, U108)
dlp = sv.chiffres(GID, U108, *P["periode"])
NOMS["liasxcret/c104"] = NOM
check("un lien Lia commun : ni ses subs, ni ses clics Infloww (ceux de tout le monde)",
      (dl["subs"], dl["infloww"]) == (10, 40) and dlp["infloww"] == 0 and dlp["subs"] == 1,
      (dl["subs"], dl["infloww"], dlp["infloww"], dlp["subs"]))
GMS_MUET.add("2026-11-01")
d3 = sv.chiffres(GID, U108, *P["periode"])
GMS_MUET.clear()
check("GetMySocial muet : None, le reste de la page reste", (d3["us"], d3["glob"]) == (None, None)
      and d3["subs"] == 4)
MYPULS["muet"] = True
dmu = sv.chiffres(GID, U108, *P["periode"])
MYPULS["muet"] = False
check("MyPuls muet : subs, CVR, $ / sub et Gagné « — », jamais 0",
      all(dmu[k] is None for k in ("subs", "cvr", "par_sub", "gagne")), dmu)
sv._CACHE.clear()
n0 = APPELS["clics"]
for _ in range(2):
    sv.chiffres_caches(GID, U108, *P["periode"])
sv.chiffres_caches(GID, U108, *P["precedente"])
check("relu au plus toutes les 10 min, par période", APPELS["clics"] - n0 == 2, APPELS["clics"] - n0)
_max = sv.PERIODES_JOUR_MAX
sv.PERIODES_JOUR_MAX = 2
sv._CACHE.clear()
sv._LECTURES.clear()
sv.chiffres_caches(GID, U108, "2026-10-20", "2026-10-22")
sv.chiffres_caches(GID, U108, "2026-10-21", "2026-10-22")
try:
    sv.chiffres_caches(GID, U108, "2026-10-22", "2026-10-22")
    trop = False
except sv.TropDePeriodes:
    trop = True
raccourcis_ok = all(sv.chiffres_caches(GID, U108, *P[k]) for k in ("toujours", "aujourdhui", "periode", "precedente"))
deja_lue = sv.chiffres_caches(GID, U108, "2026-10-20", "2026-10-22")
autre_va = sv.chiffres_caches(GID, U63, "2026-10-22", "2026-10-22")
check("quota : au-delà du plafond de périodes à la main par jour, refus ; raccourcis, période déjà lue et "
      "autre VA restent libres", trop and raccourcis_ok and deja_lue and autre_va)
sv._CACHE.clear()
check("période de l'adresse : celle de la page Lia (bornes, inversion, illisible = toujours)",
      sv.periode({"du": "2026-11-01", "au": "2026-11-03"}) == ("2026-11-01", "2026-11-03")
      and sv.periode({"du": "2026-11-03", "au": "2026-11-01"}) == ("2026-11-01", "2026-11-03")
      and sv.periode({"tout": "1"}) == ("", ""))
check("sans période : cette quinzaine par défaut (« pas depuis toujours mais cette quinzaine »)",
      sv.periode({}) == ("2026-11-01", "2026-11-03") and sv.periode(None) == ("2026-11-01", "2026-11-03")
      and sv.periode({"du": "zzz"}) == ("2026-11-01", "2026-11-03"))

print("3. La page")
h = sv.page_html(D["precedente"], t108, JOUR)
vue = h
check("titre, période et pseudo du VA",
      "Instagram VA 108" in h and "@duc_duchesse" in h and "Quinzaine précédente (du 16/10 au 31/10)" in h)
check("ses chiffres de la période", all(f">{v}<" in vue for v in ("300", "900", "17")) and ">798" in vue)
nav = re.findall(r'<nav class="raccourcis"[^>]*>(.*?)</nav>', h)
check("les raccourcis de la page Lia, dans l'ordre",
      nav and [html.unescape(re.sub("<[^>]+>", "", x)) for x in re.findall(r"<a [^>]*>.*?</a>", nav[0])]
      == ["Depuis toujours", "Aujourd'hui", "Cette quinzaine", "Quinzaine précédente", "7 derniers jours",
          "30 derniers jours"])
check("« Quinzaine précédente » allumé, un seul raccourci allumé",
      h.count('class="on"') == 1 and re.search(r'<a href="[^"]*du=2026-10-16&amp;au=2026-10-31" class="on"', h))
check("chaque raccourci et le formulaire gardent la clé",
      all(f"t={t108}" in x for x in re.findall(r'<a href="(\?[^"]*)"', h))
      and f'<input type="hidden" name="t" value="{t108}">' in h)
check("pas la liste de ses trackings (« ça je veux pas »)",
      not any(x in h for x in ("c104", "c236", "c117", "avant le passage")))
pied = h.split("</table></div>", 1)[1]
check("en bas : les trois API officielles, chacune liée à sa doc",
      all(f'href="{u}"' in pied and f">{n}</a>" in pied for n, u in sv.SOURCES)
      and pied.count("API officielle") == 3
      and 'href="https://infloww-openapi.stoplight.io"' in pied and 'href="https://mypuls.app/api/doc"' in pied)
check("en bas, rien d'autre : ni bloc de preuves, ni longues explications",
      "Preuves" not in h and "<details" not in h and "<ul" not in pied and pied.count('<p class="pied">') <= 3)
check("aucun autre VA", "autre_va_secret" not in h and "VA 63" not in h)
check("la ligne de la page Lia : @ du VA, son numéro dessous",
      re.search(r'<td class="nom">@duc_duchesse<span class="det">Instagram VA 108</span></td>', h))
check("les colonnes de la page Lia, sans Paiement ni Gain / perte",
      re.findall(r"<th[^>]*>([^<]*)</th>", h) == ["Personne", "Clics US GMS", "Clics globaux GMS", "Clics Infloww",
                                                  "Subs", "CVR", "$ / sub", "Gagné"]
      and "Paiement" not in h and "Gain" not in h, re.findall(r"<th[^>]*>([^<]*)</th>", h))
check("CVR et $ / sub colorés comme la page Lia (rouge sous la moitié du seuil)",
      '<span class="nv r">1,94 %</span>' in h and '<span class="nv v1">2,35 $</span>' in h,
      re.findall(r'<span class="nv[^"]*">[^<]*</span>', h))
check("Gagné : 11,90 $", ">11,90 $<" in h)
check("jamais le revenu total (40 $) ni l'euro", "40,00" not in h and "€" not in h)
check("ni astérisque ni note sur les anciens liens Emy (« retire ça »)",
      "*" not in re.sub(r"<style>.*?</style>", "", h, flags=re.S) and "Emy" not in h)
check("en bas, deux lignes quand tout est lisible : les sources, l'heure",
      (ha := sv.page_html(D["aujourdhui"], t108, JOUR)).count('<p class="pied">') == 2
      and "pas encore lisible" not in ha)
check("aucun JavaScript", "<script" not in h.lower())
check("« — » quand ce n'est pas lisible, et dit en bas",
      "—" in (h3 := sv.page_html(d3, t108, JOUR)) and "pas encore lisible" in h3)
check("une période libre : « Du 20/10 au 22/10 », aucun raccourci allumé",
      "Du 20/10 au 22/10" in (hl := sv.page_html(D["libre"], t108, JOUR)) and 'class="on"' not in hl)
d4 = dict(D["periode"], pseudo='<img src=x onerror=alert(1)>')
check("un pseudo ne peut rien casser (échappé)", "<img src=x" not in sv.page_html(d4, t108, JOUR))

print("4. La route")
import web_upload as wu         # noqa: E402
app = wu.create_app()
app.config["TESTING"] = True
c = app.test_client()
sv._CACHE.clear()
r = c.get(f"/mes-stats?t={t108}")
corps = r.get_data(as_text=True)
check("sa clé seule : 200, sa page, CETTE QUINZAINE allumée", r.status_code == 200 and "Instagram VA 108" in corps
      and "<b>Cette quinzaine (du 01/11 au 03/11)</b>" in corps and ">80<" in corps
      and re.search(r'du=2026-11-01&amp;au=2026-11-03" class="on"', corps), r.status_code)
rt = c.get(f"/mes-stats?t={t108}&tout=1").get_data(as_text=True)
check("le raccourci « Depuis toujours » (?tout=1) : depuis toujours",
      "<b>Depuis toujours</b>" in rt and ">500<" in rt and re.search(r'tout=1" class="on"', rt)
      and f'href="?t={t108}&amp;tout=1"' in corps)
check("en-têtes : no-store, noindex, no-referrer",
      "no-store" in r.headers.get("Cache-Control", "") and "noindex" in r.headers.get("X-Robots-Tag", "")
      and r.headers.get("Referrer-Policy") == "no-referrer", dict(r.headers))
rp = c.get(f"/mes-stats?t={t108}&du=2026-10-16&au=2026-10-31").get_data(as_text=True)
check("?du=&au= : la période demandée", "Quinzaine précédente (du 16/10 au 31/10)" in rp and ">300<" in rp)
for lib, url in (("sans clé", "/mes-stats"), ("clé fausse", "/mes-stats?t=" + "y" * 32),
                 ("clé coupée", f"/mes-stats?t={t108[:-1]}")):
    rr = c.get(url)
    check(f"{lib} : 404, rien de lui", rr.status_code == 404 and "duc_duchesse" not in rr.get_data(as_text=True),
          rr.status_code)
PARTIS.add((GID, U108))
rr = c.get(f"/mes-stats?t={t108}")
PARTIS.clear()
check("VA parti : 404", rr.status_code == 404 and "duc_duchesse" not in rr.get_data(as_text=True), rr.status_code)
_f = FICHES.pop((GID, U108))
sv._CACHE.clear()
rr = c.get(f"/mes-stats?t={t108}")
FICHES[(GID, U108)] = _f
check("VA sans fiche : 404", rr.status_code == 404, rr.status_code)
sv._LECTURES.clear()
sv.PERIODES_JOUR_MAX = 1
c.get(f"/mes-stats?t={t108}&du=2026-10-05&au=2026-10-06")
rq = c.get(f"/mes-stats?t={t108}&du=2026-10-07&au=2026-10-08")
tq = rq.get_data(as_text=True)
sv.PERIODES_JOUR_MAX = _max
check("quota : 429, le message et les raccourcis, la clé gardée",
      rq.status_code == 429 and "beaucoup de périodes" in tq and f"t={t108}" in tq and "Quinzaine précédente" in tq,
      rq.status_code)
r63 = c.get(f"/mes-stats?t={sv.jeton(GID, U63)}").get_data(as_text=True)
check("la clé d'un autre VA n'ouvre que la sienne", "Instagram VA 63" in r63 and "duc_duchesse" not in r63)
print("5. « 📈 Mes stats »")
r_ = subs_va.subs_du_va(GID, U108, JOUR)
_cv = pod.clics_du_va
pod.clics_du_va = lambda g, u, p: [(1, 2) for _x in p]
txt = subs_va._texte_stats(GID, U108, r_)
check("TRUST INSTAGRAM : le lien sous les chiffres, entre < > (pas d'aperçu)",
      f"<https://youl4b.com/mes-stats?t={t108}>" in txt and txt.index("Clics de ton lien") < txt.index("mes-stats"),
      txt[-300:])
check("TRUST INSTAGRAM : aucun montant dans le message", "$" not in txt)
txt_tw = subs_va._texte_stats(TW, U108, r_)
check("Threads (04/11) : le lien sous les chiffres aussi",
      "mes-stats" in txt_tw and "Clics de ton lien" in txt_tw)
# 04/11/2026 : « un peu comme sur Instagram » pour TRUST TWITTER
check("TRUST TWITTER : son lien, une clé à lui, distincte d'Instagram",
      sv.lien(sv.TWITTER_ID, U108).startswith("https://youl4b.com/mes-stats?t=")
      and sv.lien(sv.TWITTER_ID, U108) != sv.lien(GID, U108))
_dtw = dict(D["precedente"], gid=sv.TWITTER_ID)
_htw = sv.page_html(_dtw, sv.jeton(sv.TWITTER_ID, U108), JOUR)
check("TRUST TWITTER : bandeau « TRUST TWITTER », lien « Twitter VA 108 »",
      "TRUST TWITTER" in _htw and "TRUST INSTAGRAM" not in _htw and "Twitter VA 108" in _htw)
_j = sv.jeton


def _panne(g, u):
    raise OSError("disque plein")


sv.jeton = _panne
txt_p = subs_va._texte_stats(GID, U108, r_)
sv.jeton = _j
pod.clics_du_va = _cv
check("clé non écrite : le message part quand même, sans lien",
      "mes-stats" not in txt_p and "Clics de ton lien" in txt_p)

print("5b. L'accueil épinglé")
ACC = {"description": "Bonjour.\n\n🔗 **Ton lien** — celui que tu postes sur Instagram :\nhttps://getmysocial.com/vieux"}
APPELS_API = []


def _faux_api(methode, chemin, **kw):
    APPELS_API.append((methode, chemin, kw))
    if methode == "GET":
        return 200, {"embeds": [dict(ACC)]}
    return 200, {}


_api_sauve, _etat_sauve = tickets_discord._api, tickets_discord._etat
tickets_discord._api = _faux_api
tickets_discord._etat = lambda: {"tickets": {f"{GID}:{U108}": {"accueil": "m1"}, f"{TW}:{U108}": {"accueil": "m2"}}}
try:
    tickets_discord._poser_lien_dans_accueil(GID, U108, "sal", {"public_url": "https://getmysocial.com/neuf",
                                                               "plateforme": "Instagram"})
    d_ig = [kw for m, c, kw in APPELS_API if m == "PATCH"][-1]["json"]["embeds"][0]["description"]
    APPELS_API.clear()
    tickets_discord._poser_lien_dans_accueil(TW, U108, "sal", {"public_url": "https://getmysocial.com/neuf",
                                                              "plateforme": "Twitter"})
    d_tw = [kw for m, c, kw in APPELS_API if m == "PATCH"][-1]["json"]["embeds"][0]["description"]
    ACC["description"] = d_ig
    APPELS_API.clear()
    tickets_discord._poser_lien_dans_accueil(GID, U108, "sal", {"public_url": "https://getmysocial.com/autre",
                                                               "plateforme": "Instagram"})
    d_re = [kw for m, c, kw in APPELS_API if m == "PATCH"][-1]["json"]["embeds"][0]["description"]
finally:
    tickets_discord._api, tickets_discord._etat = _api_sauve, _etat_sauve
check("TRUST INSTAGRAM : la page de stats juste sous « 🔗 Ton lien »",
      d_ig.endswith(f"https://getmysocial.com/neuf\n\n📊 **Ta page de stats** — rien que pour toi :\n"
                    f"https://youl4b.com/mes-stats?t={t108}") and "vieux" not in d_ig, d_ig[-200:])
check("Threads : pas de page de stats dans l'accueil (elle est dans le menu)", "mes-stats" not in d_tw, d_tw[-160:])
check("lien refait : la page de stats une seule fois, sous le nouveau lien",
      d_re.count("mes-stats") == 1 and d_re.index("autre") < d_re.index("mes-stats") and "neuf" not in d_re, d_re[-200:])
check("ligne_page_perso : rien pour Threads (dans le menu)", tickets_discord.ligne_page_perso(TW, U108) == "")
# 04/11 : « pas Bienvenue, mets en mode voilà ton menu » -- Twitter : dans le menu, pas l'accueil
check("TRUST TWITTER : rien dans l'accueil", tickets_discord.ligne_page_perso(sv.TWITTER_ID, U108) == "")
_lv_lien = __import__("liens_va").lien_de
__import__("liens_va").lien_de = lambda g, u: {"public_url": "https://getmysocial.com/neuf", "actif": True}
try:
    _menu_tw = tickets_discord._texte_menu(sv.TWITTER_ID, U108)
    _menu_ig = tickets_discord._texte_menu(GID, U108)
finally:
    __import__("liens_va").lien_de = _lv_lien
check("TRUST TWITTER : le menu porte le lien puis la page de stats",
      _menu_tw.startswith("📋 **Menu**\n🔗 <https://getmysocial.com/neuf>\n📊 Tes stats : <https://youl4b.com/mes-stats?t=")
      and _menu_tw.endswith(">"), _menu_tw)
check("TRUST INSTAGRAM : le menu ne change pas (sa page reste dans l'accueil)",
      _menu_ig == "📋 **Menu**\n🔗 <https://getmysocial.com/neuf>", _menu_ig)

print("6. Isolation")
check("rien écrit dans le vrai data/ (clés, relevés Infloww de Lia)",
      {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS} == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
