# -*- coding: utf-8 -*-
"""tests_essai_clics.py — le message « Essai réussi » dit des clics US.

Le 10/11/2026, Dav (TRUST INSTAGRAM, Instagram VA 127) a lu « 53 subs sur la
période » alors que suivi_va.verifier compte les clics US de son lien
(clics_us) : 53 clics, 0 abonné. Propriétaire : « Écrire clics US ».

Ce qui est vérifié :
  - verifier : un VA en essai à 53 clics US (objectif 50) est confirmé ;
  - le message posté dit « 53 clics US » et « 50 clics US », jamais « subs ».

Aucun appel réseau, rien dans data/. Lancement : python tests_essai_clics.py
"""
from __future__ import annotations

import datetime as dt
import io
import pathlib
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import suivi_va as sv                  # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


AG = lv.AGENCY_IG_ID
UID = "1410778851335995403"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="essai_clics_"))
POSTES = []
CONFIRMES = []

_sauve = {"sv": {k: getattr(sv, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "clics_us")},
          "tk": {k: getattr(tk, k) for k in ("_etat", "_api", "confirmer")},
          "lv": {k: getattr(lv, k) for k in ("_etat", "est_actif")}}
try:
    sv.ETAT_FICHIER = TMP / "suivi_va.json"
    sv.CONFIG_FICHIER = TMP / "suivi_va_config.json"
    sv.clics_us = lambda lid, d0, d1: 53
    lv._etat = lambda: {"liens": {f"{AG}:{UID}": {"pseudo": "dav_chino", "numero": 127,
                                                   "link_id": "lnk_dav"}}}
    lv.est_actif = lambda gid, uid: True
    tk._etat = lambda: {"tickets": {f"{AG}:{UID}": {"salon": "c127", "essai": True}}}
    tk.confirmer = lambda gid, uid, par="": (CONFIRMES.append((gid, uid, par)), {"ok": True})[1]
    tk._api = lambda m, chemin, **k: (POSTES.append((m, chemin, k.get("json"))), {})[1]

    out = io.StringIO()
    bilan = sv.verifier(AG, dt.date(2026, 11, 9))
    check("53 clics US pour un objectif de 50 : confirmé par l'objectif",
          CONFIRMES == [(AG, UID, "objectif")] and bilan["confirmes"] == ["dav_chino (53 clics)"],
          (CONFIRMES, bilan))
    msg = next((j for m, c, j in POSTES if m == "POST" and c == "/channels/c127/messages"), None)
    desc = ((msg or {}).get("embeds") or [{}])[0].get("description", "")
    check("le message dit « 53 clics US » et l'objectif « 50 clics US »",
          "**53 clics US**" in desc and "**50 clics US**" in desc, desc)
    check("… et jamais « subs » (ce ne sont pas des abonnés)",
          "sub" not in desc.lower(), desc)
finally:
    for mod, sauve in ((sv, _sauve["sv"]), (tk, _sauve["tk"]), (lv, _sauve["lv"])):
        for k, v in sauve.items():
            setattr(mod, k, v)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
