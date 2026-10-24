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
    classement le dit.

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
check("bonus du jour : posé et complété avec la rangée",
      "**_rangee_yeux_message(gid)" in inspect.getsource(pd.rafraichir_bonus)
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
    va = dict(p, member={"user": {"id": "va"}})
    check("clic d'un VA : refusé, aucun pseudo", "Réservé au staff" in pd.traiter(va)["data"]["content"])
    vide = dict(p, message={"embeds": [{"title": "x", "description": "rien"}]})
    check("message sans classement : dit", "Personne" in pd.traiter(vide)["data"]["content"])
    check("le 👀 de la quinzaine garde son chemin",
          pd.BOUTON_PSEUDOS != pd.BOUTON_PSEUDOS_MSG)
finally:
    pd._staff, pd._noms_libelles = _sauve

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
