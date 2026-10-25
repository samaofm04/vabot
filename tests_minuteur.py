# -*- coding: utf-8 -*-
"""tests_minuteur.py — les classements à heure fixe, leur minuteur, et le
podium de la semaine au format du bonus du jour.

Propriétaire, 25/10/2026 : « il faut que chaque heure les subs se mettent à
jour, avec un timer », « pour tous les classements subs », puis « prime pour
le classement sur la semaine, que les 3 premiers, comme bonus journalier,
pour les 3 serveurs ».

Ce qui est vérifié (podium_discord, web_upload) :
  - debut_creneau : calé sur l'horloge de Paris (hh:00 ; heures paires pour
    deux heures), heure d'été comme d'hiver ;
  - a_refaire : à refaire dès que le dernier passage est d'avant le créneau
    en cours, pas 60 min après lui ; HEURE_FIXE = False : l'ancien rythme ;
  - le podium, le bonus et la quinzaine suivent cette règle ;
  - ligne_minuteur : « 🔄 Prochaine mise à jour <t:…:R> · mis à jour à
    <t:…:t> », la prochaine heure pile, à l'heure du module ;
  - le minuteur sur les messages qui bougent (bonus du jour, podium en cours,
    quinzaine en cours, Va IG compris), jamais sur un message figé (bonus
    d'hier, semaine terminée, résultat final, quinzaine finie) ;
  - le podium court (Twitter, Threads, Agency) : titre, trois lignes et leur
    prime 10 / 5 / 3 $, le minuteur, la consigne « ton rang de la semaine »,
    « Un seul prix par personne » ; ni places 4 et plus, ni « … et N
    autres », ni bloc des primes, ni « 🔢 », ni avertissement (au journal) ;
    Threads en clics ; Va IG garde son podium ;
  - 👀 Pseudos lit les « sans relevé » dans l'état (le message ne les dit
    plus) ;
  - Threads et la quinzaine de Va IG chaque heure, le podium de Va IG
    (GetMySocial, un appel par VA) toutes les deux heures ;
  - la boucle du site se réveille aux dizaines de minutes de l'horloge.

Aucun appel réseau. Lancement : python tests_minuteur.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from zoneinfo import ZoneInfo          # noqa: E402

import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


PARIS = ZoneInfo("Europe/Paris")
TW, TH, AG, IG = pd.TWITTER_ID, pd.THREADS_ID, pd.AGENCY_IG_ID, pd.VA_IG_ID


def ts(*a):
    return dt.datetime(*a, tzinfo=PARIS).timestamp()


TMP = pathlib.Path(tempfile.mkdtemp(prefix="minuteur_"))
_SAUVE = {k: getattr(pd, k) for k in ("_maintenant", "_etat", "_staff", "_noms_libelles",
                                      "HEURE_FIXE", "MINUTEUR", "INTERNES_REUNIS")}
try:
    pd.INTERNES_REUNIS = False
    # ── les créneaux ──
    check("créneau d'une heure : 14h37 → 14h00 (heure d'été)",
          pd.debut_creneau(60, ts(2026, 7, 14, 14, 37)) == ts(2026, 7, 14, 14, 0))
    check("… et l'hiver (25/10/2026, jour du changement d'heure) : 14h37 → 14h00",
          pd.debut_creneau(60, ts(2026, 10, 25, 14, 37)) == ts(2026, 10, 25, 14, 0))
    check("créneau de deux heures : aux heures paires de Paris (15h10 → 14h00, 13h59 → 12h00)",
          pd.debut_creneau(120, ts(2026, 10, 25, 15, 10)) == ts(2026, 10, 25, 14, 0)
          and pd.debut_creneau(120, ts(2026, 10, 25, 13, 59)) == ts(2026, 10, 25, 12, 0))
    vu = ts(2026, 10, 25, 14, 2)
    check("passé à 14h02 : rien à refaire à 14h58, à refaire dès 15h00",
          not pd.a_refaire(vu, 60, ts(2026, 10, 25, 14, 58))
          and pd.a_refaire(vu, 60, ts(2026, 10, 25, 15, 0, 5)))
    vu2 = ts(2026, 10, 25, 14, 50)
    check("passé à 14h50 : à refaire à 15h00, pas une heure plus tard",
          pd.a_refaire(vu2, 60, ts(2026, 10, 25, 15, 0, 5)))
    pd.HEURE_FIXE = False
    check("HEURE_FIXE = False : l'ancien rythme (60 min après le passage)",
          not pd.a_refaire(vu2, 60, ts(2026, 10, 25, 15, 0, 5))
          and pd.a_refaire(vu2, 60, ts(2026, 10, 25, 15, 50, 1)))
    pd.HEURE_FIXE = True

    # ── podium, bonus, quinzaine : la même règle ──
    auj = dt.date(2026, 10, 25)
    lundi = dt.date(2026, 10, 19)
    ETAT = {"vivants": {TW: {"semaine": pd.semaine_en_cours(auj)[0].isoformat(), "message": "M",
                             "vu": vu2, "format": pd._format_affiche(TW)}},
            "bonus": {TW: {"jour": auj.isoformat(), "message": "B", "vu": vu2,
                           "sans_releve": ["VA 11"]}},
            "subs": {TW: {"saison": pd.saison_en_cours(auj)[0].isoformat(), "messages": ["Q"],
                          "vu": vu2, "format": pd._format_subs(TW)}}}
    pd._etat = lambda: json.loads(json.dumps(ETAT))
    pd._maintenant = lambda: dt.datetime(2026, 10, 25, 15, 0, 5)
    t15 = ts(2026, 10, 25, 15, 0, 5)
    t1459 = ts(2026, 10, 25, 14, 59)
    check("podium, bonus et quinzaine de Twitter : à refaire à 15h00 pile, pas à 14h59",
          pd.a_rafraichir(TW, t15) and pd.a_rafraichir_bonus(TW, t15) and pd._subs_du(TW, ETAT["subs"][TW], t15)
          and not pd.a_rafraichir(TW, t1459) and not pd.a_rafraichir_bonus(TW, t1459)
          and not pd._subs_du(TW, ETAT["subs"][TW], t1459))
    check("les rythmes : Threads chaque heure, la quinzaine de Va IG chaque heure, son podium "
          "(GetMySocial) toutes les deux heures",
          pd._minutes_podium(TH) == 60 and pd._minutes_subs(TH) == 60
          and pd._minutes_subs(IG) == 60 and pd._minutes_podium(IG) == 120
          and pd._minutes_podium(TW) == 60 and pd._minutes_bonus() == 60)

    # ── le minuteur ──
    pd._maintenant = lambda: dt.datetime(2026, 10, 25, 14, 18)
    m = pd.ligne_minuteur(60)
    check("minuteur : « 🔄 Prochaine mise à jour <t:15h00:R> · mis à jour à <t:14h18:t> »",
          m == f"🔄 Prochaine mise à jour <t:{int(ts(2026, 10, 25, 15, 0))}:R> · "
               f"mis à jour à <t:{int(ts(2026, 10, 25, 14, 18))}:t>", m)
    check("… deux heures (podium de Va IG) : la prochaine heure paire",
          f"<t:{int(ts(2026, 10, 25, 16, 0))}:R>" in pd.ligne_minuteur(120))
    MIN = "🔄 Prochaine mise à jour <t:"
    L3 = [{"va": "VA 41", "numero": 41, "clics": 120, "liens": 1, "spam": False, "model": ""},
          {"va": "VA 124", "numero": 124, "clics": 48, "liens": 1, "spam": False, "model": ""},
          {"va": "VA 74", "numero": 74, "clics": 18, "liens": 1, "spam": False, "model": ""},
          {"va": "VA 95", "numero": 95, "clics": 15, "liens": 1, "spam": False, "model": ""},
          {"va": "VA 96", "numero": 96, "clics": 8, "liens": 1, "spam": False, "model": ""}]
    cl = {"lignes": L3, "illisibles": ["VA 11"], "frais": True}
    b = pd.embed_bonus(cl, auj, TW)
    check("bonus du jour : le minuteur, sous le minimum",
          "Minimum 40 subs dans la journée pour toucher la prime.\n" + MIN in b["description"],
          b["description"])
    check("… le bonus d'hier (complété, réécrit) : pas de minuteur",
          MIN not in pd.embed_bonus(cl, dt.date(2026, 10, 24), TW)["description"])

    # ── le podium court ──
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        e = pd.embed_podium(dict(cl, sans_tracking=["test emy"]), lundi, auj, en_cours=True, gid=TW)
    d = e["description"]
    check("podium court de Twitter : « 🔴 Podium subs de la semaine · 19/10 → 25/10 »",
          e["title"] == "🔴 Podium subs de la semaine · 19/10 → 25/10", e["title"])
    # L3 : VA 41 120, VA 124 48, VA 74 18 — sous le minimum de la semaine (100)
    check("… trois lignes, rien au-delà ; sous 100 subs : « pas de prime (min. 100) »",
          "🥇 **VA 41** — **120 subs** → **10$**" in d
          and "🥈 **VA 124** — **48 subs** → pas de prime (min. 100)" in d
          and "🥉 **VA 74** — **18 subs** → pas de prime (min. 100)" in d and "VA 95" not in d
          and "4." not in d and "autres" not in d
          and "Minimum 100 subs dans la semaine pour toucher la prime.\n" + MIN in d, d)
    check("… le minuteur, le trait, la consigne « ton rang de la semaine »",
          MIN in d and "——————————" in d and "ton rang de la semaine" in d
          and d.index(MIN) < d.index("——————————"), d)
    check("… ni bloc des primes en double, ni « 🔢 ton numéro », ni avertissement",
          "Les 3 meilleurs" not in d and "🔢" not in d and "⚠️" not in d and "ℹ️" not in d
          and "Sans relevé" not in d, d)
    check("… les avertissements au journal (« VA 11 » sans relevé, le lien sans tracking)",
          "non affiché dans le podium" in sortie.getvalue() and "VA 11" in sortie.getvalue()
          and "sans tracking" in sortie.getvalue(), sortie.getvalue())
    check("… « Un seul prix par personne · payé à la main après vérification »",
          e["footer"]["text"] == "Un seul prix par personne · payé à la main après vérification")
    with contextlib.redirect_stdout(io.StringIO()):
        et = pd.embed_podium(cl, lundi, dt.date(2026, 10, 25), termine=True, gid=TW)
        ef = pd.embed_podium(cl, lundi, dt.date(2026, 10, 25), gid=TW)
    check("semaine terminée, résultat final : sans minuteur, le pied le dit",
          MIN not in et["description"] and MIN not in ef["description"]
          and et["title"] == "🏁 Podium subs · semaine du 19/10 → 25/10 terminée"
          and ef["title"] == "🏆 Podium subs de la semaine · 19/10 → 25/10"
          and ef["footer"]["text"].endswith(" · résultat final"), (et["title"], ef["title"]))
    with contextlib.redirect_stdout(io.StringIO()):
        e1 = pd.embed_podium({"lignes": L3[:1] + [dict(L3[1], clics=0)], "illisibles": [],
                              "frais": True}, lundi, auj, en_cours=True, gid=AG)
    check("Instagram : une place à 0 sans prime (min. 100) ; une place vide « — »",
          "🥈 **VA 124** — **0 subs** → pas de prime (min. 100)" in e1["description"]
          and "🥉 **—** → **3$**" in e1["description"], e1["description"])
    LTH = [dict(x, va=f"Threads {x['numero']}") for x in L3]
    with contextlib.redirect_stdout(io.StringIO()):
        eth = pd.embed_podium({"lignes": LTH, "illisibles": [], "frais": True}, lundi, auj,
                              en_cours=True, gid=TH)
    check("Threads : en clics, « Podium clics de la semaine », pas de minimum affiché",
          eth["title"].startswith("🔴 Podium clics de la semaine")
          and "🥇 **Threads 41** — **120 clics** → **10$**" in eth["description"]
          and "Minimum" not in eth["description"], eth["description"])
    with contextlib.redirect_stdout(io.StringIO()):
        eth0 = pd.embed_podium({"lignes": [dict(LTH[0], clics=0)], "illisibles": [], "frais": True},
                               lundi, auj, en_cours=True, gid=TH)
    check("… à 0 clic : pas de prime", "**0 clics** → pas de prime\n" in eth0["description"] + "\n",
          eth0["description"])
    check("le 👀 lit les lignes du podium court",
          [v for v, _n in pd._ligne_affichee("VA").findall(d)] == ["VA 41", "VA 124", "VA 74"])
    with contextlib.redirect_stdout(io.StringIO()):
        eig = pd.embed_podium({"lignes": [dict(L3[0], va="Amelia VA 3", model="amelia")],
                               "illisibles": [], "frais": True}, lundi, auj, en_cours=True, gid=IG)
    check("Va IG garde son podium, le minuteur à la place de « mis à jour plusieurs fois par jour »",
          IG not in pd.PODIUM_COURT and MIN in eig["description"]
          and "plusieurs fois par jour" not in eig["description"]
          and "Les 3 meilleurs" in eig["description"], eig["description"][:400])
    pd.MINUTEUR = False
    with contextlib.redirect_stdout(io.StringIO()):
        eig2 = pd.embed_podium({"lignes": [dict(L3[0], va="Amelia VA 3", model="amelia")],
                                "illisibles": [], "frais": True}, lundi, auj, en_cours=True, gid=IG)
    check("MINUTEUR = False : la ligne d'avant", "plusieurs fois par jour" in eig2["description"]
          and MIN not in eig2["description"])
    pd.MINUTEUR = True

    # ── la quinzaine ──
    pages = pd.pages_subs(cl, dt.date(2026, 10, 16), dt.date(2026, 10, 31), {}, gid=TW)
    finales = pd.pages_subs(cl, dt.date(2026, 10, 1), dt.date(2026, 10, 15), {}, gid=TW, final=True)
    check("quinzaine en cours : le minuteur sous l'en-tête ; finie : non",
          MIN in pages[0]["description"]
          and pages[0]["description"].index(MIN) < pages[0]["description"].index("🥇")
          and MIN not in finales[0]["description"], pages[0]["description"][:300])

    # ── 👀 : les sans relevé, lus dans l'état ──
    pd._staff = lambda p: True
    pd._noms_libelles = lambda gid: {41: "comptes internes", 124: "bigmaxm", 11: "Kylmich"}
    rep = pd._voir_pseudos_message({"guild_id": TW, "message": {"id": "B", "embeds": [b]}})
    check("👀 sous le bonus : « Sans relevé : VA 11 », lu dans l'état (le message ne le dit plus)",
          "**Sans relevé** : VA 11 Kylmich" in rep["data"]["content"] and "VA 11" not in b["description"],
          rep["data"]["content"])

    # ── la boucle du site ──
    src = (BOT / "web_upload.py").read_text(encoding="utf-8")
    check("la boucle du site se réveille aux dizaines de minutes de l'horloge",
          "_t_p.sleep(600 - _t_p.time() % 600 + 5)" in src)
finally:
    for k, v in _SAUVE.items():
        setattr(pd, k, v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
