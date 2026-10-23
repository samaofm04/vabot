# -*- coding: utf-8 -*-
"""tests_menu_numero.py — « 📱 Numéro » dans le menu épinglé des tickets.

Propriétaire, 23/10/2026, sur le menu épinglé d'un ticket d'Agency : « je veux
que ça soit une option dans le menu pin ». Le bouton (custom_id « numx:menu »)
ramène la carte numéro du VA en bas de son ticket ; le clic est à
numeros_x_discord._menu.

Ce qui est vérifié (tickets_discord.boutons_va, traiter, BOUTONS_VERSION) :
  - Twitter, Threads, Agency : « 📱 Numéro » en dernier, une seule fois ;
  - Twitter seulement : « 📧 Outlook » juste après (« mailx:menu »), sur une
    2e rangée quand la 1re est pleine ;
  - menu le plus long (Confirmer, Désactiver, USDC, Mes stats) : Numéro en
    5e place de la même rangée ; une rangée déjà pleine : une 2e rangée,
    jamais un 6e bouton (Discord refuserait tout le menu) ;
  - un autre serveur : pas de bouton ;
  - traiter rend None pour « numx: » et « mailx: » (la route passe alors le
    clic aux numéros, à Outlook) ;
  - BOUTONS_VERSION monte : les menus déjà postés sont redessinés.

Aucun appel réseau. Lancement : python tests_menu_numero.py
"""
from __future__ import annotations

import io
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


def ids(rangs):
    return [[b.get("custom_id") for b in r.get("components") or []] for r in rangs]


TW, TH, AG = "1445108485090971710", "1498948161039896586", tk.AGENCY_IG_ID
for gid, nom in ((TW, "Twitter"), (TH, "Threads"), (AG, "Agency")):
    r = tk.boutons_va("7", confirme=False, a_un_lien=True, gid=gid)
    # sur Twitter, « 📧 Outlook » vient encore après (vérifié plus bas)
    tous = [c for rang in ids(r) for c in rang if c != "mailx:menu"]
    num = [b for rang in r for b in rang["components"] if b.get("custom_id") == "numx:menu"]
    check(f"{nom} : « 📱 Numéro » en dernier, une fois, dans la même rangée",
          tous[-1] == "numx:menu" and tous.count("numx:menu") == 1 and "numx:menu" in ids(r)[0]
          and all(len(rang) <= 5 for rang in ids(r))
          and num[0]["label"] == "Numéro" and num[0]["emoji"] == {"name": "📱"} and num[0]["style"] == 2,
          ids(r))
    r2 = tk.boutons_va("7", confirme=True, a_un_lien=False, gid=gid)
    check(f"{nom} : aussi sous un VA confirmé sans lien",
          [c for rang in ids(r2) for c in rang if c != "mailx:menu"][-1] == "numx:menu", ids(r2))
ag = tk.boutons_va("7", confirme=False, a_un_lien=True, gid=AG)
check("Agency, menu le plus long : Confirmer · Désactiver · USDC · Mes stats · Numéro",
      ids(ag) == [["essai:ok:7", "lien:off:7", "usdc:set:7", "subs:total:7", "numx:menu"]], ids(ag))
_vrai = tk._boutons_va_avant_stats
try:
    tk._boutons_va_avant_stats = lambda uid, **kw: [{"type": 1, "components": [
        {"type": 2, "custom_id": f"x{i}"} for i in range(5)]}]
    plein = tk.boutons_va("7", gid=TH)
    check("rangée déjà pleine : Numéro sur une 2e rangée, jamais un 6e bouton",
          ids(plein) == [[f"x{i}" for i in range(5)], ["numx:menu"]], ids(plein))
finally:
    tk._boutons_va_avant_stats = _vrai
autre = tk.boutons_va("7", a_un_lien=True, gid="1")
check("un autre serveur : pas de bouton Numéro",
      "numx:menu" not in [c for rang in ids(autre) for c in rang], ids(autre))
check("traiter rend None pour « numx:menu » (le clic va aux numéros)",
      tk.traiter({"type": 3, "guild_id": TW, "data": {"custom_id": "numx:menu"},
                  "member": {"user": {"id": "7"}}}) is None)
check("BOUTONS_VERSION à 7 : les menus postés sont redessinés", tk.BOUTONS_VERSION >= 7)
# « 📧 Outlook » : Twitter seulement, juste après Numéro
tw = tk.boutons_va("7", confirme=False, a_un_lien=True, gid=TW)
tous = [c for rang in ids(tw) for c in rang]
out = [b for r in tw for b in r["components"] if b.get("custom_id") == "mailx:menu"]
check("Twitter : « 📧 Outlook » juste après Numéro, une fois, aucune rangée de plus de 5",
      tous[-2:] == ["numx:menu", "mailx:menu"] and tous.count("mailx:menu") == 1
      and all(len(r) <= 5 for r in ids(tw))
      and out[0]["label"] == "Outlook" and out[0]["emoji"] == {"name": "📧"} and out[0]["style"] == 2, ids(tw))
for gid, nom in ((TH, "Threads"), (AG, "Agency"), ("1", "un autre serveur")):
    check(f"{nom} : pas d'Outlook",
          "mailx:menu" not in [c for rang in ids(tk.boutons_va("7", a_un_lien=True, gid=gid)) for c in rang])
check("traiter rend None pour « mailx:menu » (le clic va à Outlook)",
      tk.traiter({"type": 3, "guild_id": TW, "data": {"custom_id": "mailx:menu"},
                  "member": {"user": {"id": "7"}}}) is None)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
