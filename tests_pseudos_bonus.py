# -*- coding: utf-8 -*-
"""tests_pseudos_bonus.py — « 👀 Pseudos » sous le bonus du jour et le podium de la semaine.

Propriétaire, 24/10/2026, devant le bonus du jour de TRUST TWITTER : « tu
peux me mettre les yeux pour mettre les pseudos ». Twitter, Threads, Agency.

Ce qui est vérifié :
  - la rangée « 👀 Pseudos » (BOUTON_PSEUDOS_MSG) sous le bonus du jour (posé,
    complété le lendemain) et sous le podium, vivant ou figé ; rien ailleurs
    (Va IG garde son 🔄) ;
  - le clic : staff seulement, en privé, les VA DU MESSAGE cliqué (ses lignes,
    ses « sans relevé »), la personne devant chaque numéro ; un message sans
    classement le dit ;
  - depuis le 01/11/2026 (« dis-moi pourquoi là y a pas les yeux ») : la même
    rangée sur les pages d'une quinzaine finie, sur les 4 serveurs à yeux, Va
    IG compris ; Va IG y nomme « Instagram VA n » au pseudo et à la model.

Aucun appel réseau. Lancement : python tests_pseudos_bonus.py
"""
from __future__ import annotations

import inspect
import io
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


def cids(d):
    return [c.get("custom_id") for r in (d.get("components") or []) for c in r.get("components") or []]


VA_IG = "1505418484052394004"
for g, nom in ((pd.TWITTER_ID, "Twitter"), (pd.THREADS_ID, "Threads"), (pd.AGENCY_IG_ID, "Agency")):
    check(f"{nom} : « 👀 Pseudos » sous le podium, vivant et figé",
          cids(pd._boutons(g, True)) == [pd.BOUTON_PSEUDOS_MSG]
          and cids(pd._boutons(g, False)) == [pd.BOUTON_PSEUDOS_MSG], pd._boutons(g, True))
check("Va IG : son 🔄 seul, rien de neuf", pd.BOUTON_PSEUDOS_MSG not in cids(pd._boutons(VA_IG, True))
      and pd._rangee_yeux_message(VA_IG) == {})
for g, nom in ((pd.TWITTER_ID, "Twitter"), (pd.THREADS_ID, "Threads"), (pd.AGENCY_IG_ID, "Agency"),
               (VA_IG, "Va IG")):
    check(f"{nom} : quinzaine vivante, son 👀 de la quinzaine en cours ; finie, le 👀 qui lit la page",
          pd.BOUTON_PSEUDOS in cids(pd._boutons(g, True, pseudos=True))
          and cids(pd._boutons(g, False, pseudos=True)) == [pd.BOUTON_PSEUDOS_MSG],
          (pd._boutons(g, True, pseudos=True), pd._boutons(g, False, pseudos=True)))
check("Va IG : pas de 👀 sous sa semaine figée (pas demandé)", pd._boutons(VA_IG, False) == {"components": []})
check("bonus du jour : posé et complété avec la rangée",
      "**_rangee_yeux_message(gid)" in inspect.getsource(pd._rafraichir_bonus_mypuls)
      and "**_rangee_yeux_message(gid)" in inspect.getsource(pd._bonus_veille))

_sauve = (pd._staff, pd._noms_libelles)
try:
    pd._staff = lambda p: str(((p.get("member") or {}).get("user") or {}).get("id")) == "boss"
    pd._noms_libelles = lambda gid: {41: "Eddy", 43: "Tsiry", 12: "Roucham", 11: "Kylmich"}
    msg = {"embeds": [{"title": "💸 Bonus subs du jour — 24/10/2026", "description":
                       "📅 Journée du **24/10/2026** · abonnés **tracking OF**\n\n"
                       "🥇 **VA 41** — **12** subs → **3.00$**\n🥈 **VA 43** — **9** subs → **2.00$**\n"
                       "🥉 **VA 12** — **0** subs → **1.00$**\n\n"
                       "⚠️ Sans relevé aujourd'hui : VA 11 — à confirmer avant de payer."}]}
    p = {"type": 3, "guild_id": pd.TWITTER_ID, "member": {"user": {"id": "boss"}},
         "message": msg, "data": {"custom_id": pd.BOUTON_PSEUDOS_MSG}}
    r = pd.traiter(p)
    t = r["data"]["content"]
    check("clic du staff : en privé, les VA du message, la personne devant chaque numéro",
          r["type"] == 4 and r["data"]["flags"] == 64 and "Bonus subs du jour — 24/10/2026" in t
          and "🥇 VA 41 · **Eddy** · 12 subs" in t and "🥈 VA 43 · **Tsiry** · 9 subs" in t
          and "VA 12 Roucham" in t and "**Sans relevé** : VA 11 Kylmich" in t, t)
    neuf = dict(p, message={"embeds": [pd.embed_bonus(
        {"lignes": [{"va": "VA 41", "clics": 52}, {"va": "VA 43", "clics": 41},
                    {"va": "VA 12", "clics": 9}], "illisibles": [],
         "frais": True}, __import__("datetime").date(2026, 10, 25), pd.TWITTER_ID)]})
    t2 = pd.traiter(neuf)["data"]["content"]
    check("le bonus au format du 25/10/2026 se lit aussi (titre, « 52 subs » en gras)",
          "🥇 VA 41 · **Eddy** · 52 subs" in t2 and "🥈 VA 43 · **Tsiry** · 41 subs" in t2, t2)
    check("… les places payées seulement : sous le minimum (VA 12, 9 subs), pas à vérifier",
          "VA 12" not in t2 and "Roucham" not in t2, t2)
    va = dict(p, member={"user": {"id": "va"}})
    check("clic d'un VA : refusé, aucun pseudo", "Réservé au staff" in pd.traiter(va)["data"]["content"])
    vide = dict(p, message={"embeds": [{"title": "x", "description": "rien"}]})
    check("message sans classement : dit", "Personne" in pd.traiter(vide)["data"]["content"])
    check("le 👀 de la quinzaine garde son chemin",
          pd.BOUTON_PSEUDOS != pd.BOUTON_PSEUDOS_MSG)

    # Va IG, quinzaine figée du 16/10 au 31/10 : « Instagram VA n » → pseudo + model
    import subs_va
    pd._noms_libelles = _sauve[1]
    _sauve_ig = (pd.numeros_instagram, subs_va.entites_va_ig)
    pd.numeros_instagram = lambda *a, **k: {"lola:2": 11, "amelia:3": 4, "julia:9": 30}
    subs_va.entites_va_ig = lambda: {
        "lola:2": {"pseudo": "adh040", "nom": "Lola VA 2"},
        "amelia:3": {"pseudo": "seven", "nom": "Amelia VA 3"},
        "julia:9": {"pseudo": "", "nom": "Julia VA 9"},
        "sarah:7": {"pseudo": "sansnumero", "nom": "Sarah VA 7"}}
    try:
        page = {"embeds": [{"title": "🏆 Classement de la quinzaine — 16/10 → 31/10", "description":
                            "🗓️ Période **16/10 → 31/10/2026** · depuis le 16/10 à 00h00\n"
                            "Abonnés **OF + MYM** · **3** comptes classés\n\n"
                            "🥇 **Instagram VA 11** — **56** subs · 🌐 70 all-time\n"
                            "🥈 **Instagram VA 4** — **9** subs · 🌐 12 all-time\n"
                            "3. Instagram VA 30 — 0 subs\n\nTotal période **65** subs"}]}
        pi = {"type": 3, "guild_id": VA_IG, "member": {"user": {"id": "boss"}},
              "message": page, "data": {"custom_id": pd.BOUTON_PSEUDOS_MSG}}
        ti = pd.traiter(pi)["data"]["content"]
        check("Va IG, quinzaine figée : chaque « Instagram VA n » au pseudo et à la model",
              "🥇 Instagram VA 11 · **adh040 (Lola VA 2)** · 56 subs" in ti
              and "🥈 Instagram VA 4 · **seven (Amelia VA 3)** · 9 subs" in ti
              and "Instagram VA 30 ? (Julia VA 9)" in ti and "Total" not in ti, ti)
        check("… un VA sans numéro Instagram n'invente aucune ligne",
              "sansnumero" not in str(pd._noms_libelles(VA_IG)), pd._noms_libelles(VA_IG))
        check("… clic d'un VA : refusé", "Réservé au staff" in pd.traiter(
            dict(pi, member={"user": {"id": "va"}}))["data"]["content"])
    finally:
        pd.numeros_instagram, subs_va.entites_va_ig = _sauve_ig

    # « je dois tout pouvoir check » (01/11/2026) : le pseudo de LA période
    _sauve_p = (pd._noms_libelles, pd._noms_libelles_sans_internes, pd.numeros, pd._etat)
    pd._noms_libelles = lambda g: {41: "comptes internes (3 comptes)", 43: "Tsiry"}
    pd._noms_libelles_sans_internes = lambda g: {41: "Eddy", 43: "Tsiry"}
    pd.numeros = lambda cles, attribuer=True: {"Vieux": 7, "Tsiry": 43, "eddy 1": 41}
    ETAT = {}
    pd._etat = lambda: ETAT
    try:
        def page_tw(periode, mid="m1"):
            return {"type": 3, "guild_id": pd.TWITTER_ID, "member": {"user": {"id": "boss"}},
                    "data": {"custom_id": pd.BOUTON_PSEUDOS_MSG},
                    "message": {"id": mid, "embeds": [{"title": "📊 Classement subs (terminée)", "description":
                                f"🗓️ Période **{periode}** · depuis le 01/10 à 00h00\n\n"
                                "🥇 **VA 41** — **12** subs\n🥈 **VA 7** — **3** subs\n"
                                "🥉 **VA 43** — **2** subs\n4. VA 99 — 1 subs"}]}}
        t1 = pd.traiter(page_tw("01/10 → 15/10/2026"))["data"]["content"]
        check("quinzaine finie avant le 25/10 : VA 41 est Eddy, pas les comptes internes",
              "VA 41 · **Eddy** · 12 subs" in t1 and "internes" not in t1, t1)
        check("… un numéro sans tracking au registre : son nom de podium_numeros (donné pour toujours)",
              "VA 7 · **Vieux** · 3 subs" in t1 and "VA 43 · **Tsiry**" in t1, t1)
        check("… un numéro inconnu : « ? », et la réponse le dit (rien n'est deviné)",
              "VA 99 · **?**" in t1 and "Noms relus aujourd'hui" in t1 and "rien n'est deviné" in t1, t1)
        t2 = pd.traiter(page_tw("16/10 → 31/10/2026"))["data"]["content"]
        check("quinzaine finie après le 25/10 : VA 41 = la ligne des comptes internes",
              "VA 41 · **comptes internes (3 comptes)**" in t2, t2)
        ETAT["subs_figes"] = {pd.TWITTER_ID: {"2026-10-01": {"messages": ["m1"], "noms": {
            "VA 41": "Eddy (gardé au gel)", "VA 7": "Vieux", "VA 43": "Tsiry", "VA 99": "Zed"}}}}
        t3 = pd.traiter(page_tw("01/10 → 15/10/2026"))["data"]["content"]
        check("noms gardés au gel : ceux-là, tels quels, sans avertissement",
              "VA 41 · **Eddy (gardé au gel)**" in t3 and "VA 99 · **Zed**" in t3
              and "relus aujourd'hui" not in t3, t3)
        t4 = pd.traiter(page_tw("01/10 → 15/10/2026", mid="autre"))["data"]["content"]
        check("… ceux d'une autre page ne servent pas", "gardé au gel" not in t4, t4)
        longue = page_tw("01/10 → 15/10/2026", mid="long")
        longue["message"]["embeds"][0]["description"] += "".join(
            f"\n{i}. VA {i} — 1 subs" for i in range(100, 220))
        t5 = pd.traiter(longue)["data"]["content"]
        check("… une longue page : coupée avant la note, la note entière (2000 caractères)",
              len(t5) <= 2000 and t5.rstrip().endswith("rien n'est deviné._"), (len(t5), t5[-200:]))
        ETAT.clear()
        pages = [{"description": "🥇 **VA 41** — **12** subs\n2. VA 99 — 1 subs\n"
                                 "⚠️ Sans relevé : VA 7"}]
        check("au gel : les noms des VA de ses pages, sans « ? » (inconnu = rien de gardé)",
              pd._noms_des_pages(pd.TWITTER_ID, pages, __import__("datetime").date(2026, 10, 15))
              == {"VA 41": "Eddy", "VA 7": "Vieux"})
        src = inspect.getsource(pd._figer_quinzaine)
        check("… gardés avec la quinzaine figée",
              'rec["noms"] = _noms_des_pages(' in src and 'fige["noms"] = rec["noms"]' in src)
    finally:
        pd._noms_libelles, pd._noms_libelles_sans_internes, pd.numeros, pd._etat = _sauve_p
finally:
    pd._staff, pd._noms_libelles = _sauve

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
