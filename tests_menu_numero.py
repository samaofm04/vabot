# -*- coding: utf-8 -*-
"""tests_menu_numero.py — le menu épinglé des tickets (Twitter, Threads, Agency).

Propriétaire, 23/10/2026 : « 📱 Numéro » dans le menu épinglé (« je veux que
ça soit une option dans le menu pin »), « 📧 Outlook » sur Twitter (« mets ça
aussi dans leur ticket »), puis la maquette validée (« Oui, vas-y ») : la
rangée du VA, puis celle des managers.

Ce qui est vérifié (tickets_discord.boutons_va, traiter, BOUTONS_VERSION) :
  - rangée 1, le VA : 💳 USDC · 📈 Mes stats · 📱 Numéro (· 📧 Outlook sur
    Twitter) ; rangée 2, les managers : le niveau (🌱 / ⭐) · le lien ;
  - « 📱 Numéro » sur les trois serveurs, « 📧 Outlook » sur Twitter seulement,
    une fois chacun ;
  - jamais plus de 5 boutons par rangée (Discord refuserait tout le menu) ;
  - un autre serveur : ni Numéro, ni Outlook, rangée d'origine ;
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
import tempfile                        # noqa: E402

# un registre des tickets vide : le niveau du VA (🧪 / 🌱, tests_niveaux_va.py)
# se lit dans sa fiche, jamais dans le vrai data/
tk.ETAT_FICHIER = pathlib.Path(tempfile.mkdtemp(prefix="menu_numero_")) / "tickets.json"

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


def ids(rangs):
    return [[b.get("custom_id") for b in r.get("components") or []] for r in rangs]


TW, TH, AG = "1445108485090971710", "1498948161039896586", tk.AGENCY_IG_ID
for gid, nom, outlook in ((TW, "Twitter", ["mailx:menu"]), (TH, "Threads", []), (AG, "Agency", [])):
    r = ids(tk.boutons_va("7", confirme=False, a_un_lien=True, gid=gid))
    va, chefs = r[0], r[-1]
    check(f"{nom} : rangée du VA (USDC, stats, Numéro{', Outlook' if outlook else ''}), "
          "puis celle des managers (🌱 Passer Débutant pour un VA en essai, lien)",
          len(r) == 2 and va[0] == "usdc:set:7" and va[-1 - len(outlook)] == "numx:menu"
          and va[len(va) - len(outlook):] == outlook and chefs == ["essai:deb:7", "lien:off:7"]
          and all(len(x) <= 5 for x in r), r)
    r2 = ids(tk.boutons_va("7", confirme=True, a_un_lien=False, gid=gid))
    plats = [c for x in r2 for c in x]
    check(f"{nom} : VA confirmé sans lien — « Créer son lien » seul chez les managers",
          r2[-1] == ["lien:new:7"] and plats.count("numx:menu") == 1
          and plats.count("mailx:menu") == len(outlook), r2)
tw = tk.boutons_va("7", confirme=False, a_un_lien=True, gid=TW)
num = [b for r in tw for b in r["components"] if b.get("custom_id") == "numx:menu"][0]
out = [b for r in tw for b in r["components"] if b.get("custom_id") == "mailx:menu"][0]
check("les boutons : 📱 Numéro et 📧 Outlook, gris",
      (num["label"], num["emoji"], num["style"]) == ("Numéro", {"name": "📱"}, 2)
      and (out["label"], out["emoji"], out["style"]) == ("Outlook", {"name": "📧"}, 2), (num, out))
_vrai = tk._boutons_va_avant_stats
try:
    tk._boutons_va_avant_stats = lambda uid, **kw: [{"type": 1, "components": [
        {"type": 2, "custom_id": f"x{i}"} for i in range(5)]}]
    plein = ids(tk.boutons_va("7", gid=TW))
    check("trop de boutons pour une rangée : la suite passe dessous, jamais un 6e",
          all(len(x) <= 5 for x in plein) and [c for x in plein for c in x]
          == [f"x{i}" for i in range(5)] + ["numx:menu", "mailx:menu"], plein)
finally:
    tk._boutons_va_avant_stats = _vrai
autre = [c for x in ids(tk.boutons_va("7", confirme=False, a_un_lien=True, gid="1")) for c in x]
check("un autre serveur : ni Numéro ni Outlook, rangée d'origine",
      "numx:menu" not in autre and "mailx:menu" not in autre and autre[0] == "essai:ok:7", autre)
for cid in ("numx:menu", "mailx:menu"):
    check(f"traiter rend None pour « {cid} » (le clic va au module qui le sert)",
          tk.traiter({"type": 3, "guild_id": TW, "data": {"custom_id": cid},
                      "member": {"user": {"id": "7"}}}) is None)
check("BOUTONS_VERSION à 8 : les menus postés sont redessinés", tk.BOUTONS_VERSION >= 8)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
