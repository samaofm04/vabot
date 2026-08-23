# -*- coding: utf-8 -*-
"""tests_facture_pct_base.py — bases « % d'un revenu » : ce que l'écran PROMET
doit être ce que le montant rendu VAUT.

Trois régressions relues à la main sur le module Facture, toutes du même genre :
un message d'interface écrit d'après le NOMBRE d'ids de base, alors que seuls
comptent (a) les bases qui répondent encore dans le mois et (b) les dollars
qu'elles valent. Chaque test échoue sur le code d'avant le correctif.

  1. supprimer une base multiple dont l'autre id est MORT : le serveur
     promettait « montant simplement recalculé », posait un toast VERT et
     n'écrivait aucune note — la ligne tombait à 0 $ (badge rouge) au
     rechargement ;
  2. « base supprimée » annoncé pour une base RETROUVÉE dans le fichier (freq
     « once », date de fin repoussée) — et le badge la nommait juste après ;
  3. « elles ne tombent PAS à 0 $ » (bandeau orange) pour une ligne dont la
     base restante vaut 0 $ ce mois-ci : la ligne était bien rendue à 0 $.

Aucune écriture dans data/ : FACTURE_FILE est déporté dans un dossier temporaire
avant le premier appel. Lancement : python tests_facture_pct_base.py
"""
from __future__ import annotations

import copy
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

FAILS = []
OK = 0


def check(name, cond, detail=""):
    global OK
    if cond:
        OK += 1
        print(f"  ok   {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} : {detail}")


# --------------------------------------------------------------------- fixture
import facture_web as F                                    # noqa: E402
from flask import Flask                                    # noqa: E402

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="facture_pctbase_"))
F.FACTURE_FILE = _TMP / "facture.json"
F._MYPULS_CACHE_FILE = _TMP / "mypuls_cache.json"
assert "data" not in str(F.FACTURE_FILE).replace("\\", "/").split("/"), F.FACTURE_FILE

M_JUIL, M_AOUT = "2026-07", "2026-08"


def _settings():
    # taux figés + override : aucun appel réseau, aucun gel de taux à écrire.
    return {"eur_usd": 1.08, "cutoff": 15, "associates": [],
            "month_rates": {m: 1.08 for m in ("2026-06", M_JUIL, M_AOUT,
                                              "2026-09", "2026-10")},
            # empêche les graines one-shot de peupler le mois courant
            "seeds_20260709_retired": True}


def install(months: dict):
    """Écrit la fixture dans le fichier temporaire et rend un client Flask."""
    F._save({"settings": _settings(), "months": copy.deepcopy(months)})
    app = Flask(__name__)
    F.register(app, lambda: True)
    return app.test_client()


def line_of(state, lid):
    for l in state["lines"]:
        if l.get("id") == lid:
            return l
    return {}


# ---------------------------------------------------------------- harnais node
_PCT_SRC = None


def _pct_base_info_js(cases):
    """Exécute pctBaseInfo() de facture_app.js sur des états de base donnés.

    La fonction vit dans une IIFE (aucun export) : on en extrait la source et on
    la rejoue dans node avec les deux seules aides dont elle se sert. Sans ça
    les phrases du badge — le cœur des régressions 2 et 3 — ne seraient
    vérifiées nulle part.
    """
    global _PCT_SRC
    if _PCT_SRC is None:
        js = (BOT / "facture_app.js").read_text(encoding="utf-8")
        i = js.index("function pctBaseInfo(pb) {")
        j = js.index("\n  }\n", i)
        _PCT_SRC = js[i:j + 4]
    harness = (
        "function esc(x){return String(x==null?'':x).replace(/&/g,'&amp;')"
        ".replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}\n"
        "function frDate(iso){return iso ? String(iso).slice(8,10)+'/'+String(iso).slice(5,7) : '';}\n"
        + _PCT_SRC +
        "\nconst cas = JSON.parse(process.argv[2]);\n"
        "console.log(JSON.stringify(cas.map(pctBaseInfo)));\n"
    )
    p = _TMP / "pctbaseinfo_harness.js"
    p.write_text(harness, encoding="utf-8")
    out = subprocess.run(["node", str(p), json.dumps(cases)],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(_TMP))
    if out.returncode != 0:
        raise RuntimeError(out.stderr[:400])
    return json.loads(out.stdout)


def _node_ok():
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=20)
        return True
    except Exception:
        return False


HAS_NODE = _node_ok()


# =============================================================================
print("1. suppression d'une base multiple dont l'AUTRE id est mort")
# Juillet : revenu A (fin le 31/07) + revenu B, paye P = 30 % de « lines:A,B ».
# Août reporté : A n'est plus reporté (fin passée) -> P vaut « lines:A(mort),B2 ».
# Supprimer B2 ne laisse AUCUNE base vivante : le classer en « réduites »
# promettait un simple recalcul et laissait la ligne à 0 $ sans note.
cli = install({
    M_JUIL: {"lines": [
        {"id": "A", "type": "rev", "cat": "rev_of", "form": "fixed", "label": "OF Lola",
         "amount": 1000, "currency": "USD", "end": "2026-07-31", "freq": "month"},
        {"id": "B", "type": "rev", "cat": "rev_mym", "form": "fixed", "label": "MyM Lola",
         "amount": 500, "currency": "USD", "freq": "month"},
    ]},
    M_AOUT: {"lines": [
        {"id": "B2", "type": "rev", "cat": "rev_mym", "form": "fixed", "label": "MyM Lola",
         "amount": 500, "currency": "USD", "freq": "month"},
        {"id": "P2", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Lola",
         "pct": 30, "pct_of": "lines:A,B2", "freq": "month"},
    ]},
})
j = cli.post("/facture/line/delete", data={"month": M_AOUT, "id": "B2"}).get_json()
check("1a confirmation : la paye est annoncée SANS base, pas « réduite »",
      j.get("sans_base") == ["Paye Lola"] and j.get("reduites") == [],
      f"sans_base={j.get('sans_base')} reduites={j.get('reduites')}")
check("1b confirmation : le texte annonce 0 $, pas un simple recalcul",
      "AUCUNE base" in (j.get("error") or "") and "recalculé sans celle-ci" not in (j.get("error") or ""),
      repr(j.get("error"))[:200])
j2 = cli.post("/facture/line/delete", data={"month": M_AOUT, "id": "B2", "confirm": "1"}).get_json()
check("1c retour : sans_base renseigné -> le toast client est en erreur (rouge)",
      j2.get("sans_base") == ["Paye Lola"] and not j2.get("reduites"), str(j2))
st = F.compute_state(M_AOUT)
p2 = line_of(st, "P2")
check("1d la note ⚠ est bien posée sur la paye privée de base",
      "base supprimée" in (p2.get("notes") or ""), repr(p2.get("notes")))
check("1e la ligne vaut 0 $ et est comptée avec les rouges",
      p2.get("usd") == 0.0 and st["totals"]["pct_orphans"] == 1
      and st["totals"]["pct_partielles"] == 0,
      f"usd={p2.get('usd')} totals={st['totals']['pct_orphans']}/{st['totals']['pct_partielles']}")

# =============================================================================
print("2. « base supprimée » ne doit jamais être dit d'une base retrouvée")
# (a) base ponctuelle (freq « once ») restée en juillet : rien n'a été supprimé.
cli = install({
    M_JUIL: {"lines": [
        {"id": "A", "type": "rev", "cat": "rev_of", "form": "fixed", "label": "OF Lola",
         "amount": 1000, "currency": "USD", "freq": "once"},
    ]},
    M_AOUT: {"lines": [
        {"id": "P2", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Lola",
         "pct": 30, "pct_of": "line:A", "freq": "month"},
    ]},
})
pb = line_of(F.compute_state(M_AOUT), "P2").get("pct_base") or {}
check("2a base freq « once » : classée ABSENTE, ni supprimée ni expirée",
      pb.get("absentes") == 1 and pb.get("supprimees") == 0 and pb.get("expirees") == 0,
      str(pb))
check("2a bis : l'état est porté par le détail, avec le libellé retrouvé",
      (pb.get("details") or [{}])[0].get("etat") == "absente"
      and (pb.get("details") or [{}])[0].get("label") == "OF Lola",
      str(pb.get("details")))

# (b) date de fin repoussée après coup : le badge repassait à « supprimée ».
cli = install({
    M_JUIL: {"lines": [
        {"id": "A", "type": "rev", "cat": "rev_of", "form": "fixed", "label": "OF Lola",
         "amount": 1000, "currency": "USD", "end": "2026-07-31", "freq": "month"},
    ]},
    M_AOUT: {"lines": [
        {"id": "P2", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Lola",
         "pct": 30, "pct_of": "line:A", "freq": "month"},
    ]},
})
pb0 = line_of(F.compute_state(M_AOUT), "P2").get("pct_base") or {}
check("2b avant : fin passée -> base TERMINÉE (nommée avec sa date)",
      pb0.get("expirees") == 1 and (pb0.get("details") or [{}])[0].get("etat") == "terminee",
      str(pb0))
cli.post("/facture/line/save", data={"month": M_JUIL, "line": json.dumps(
    {"id": "A", "type": "rev", "cat": "rev_of", "form": "fixed", "label": "OF Lola",
     "amount": 1000, "currency": "USD", "end": "2026-12-31", "freq": "month"})})
pb1 = line_of(F.compute_state(M_AOUT), "P2").get("pct_base") or {}
check("2b après : fin repoussée -> ABSENTE de ce mois, surtout pas « supprimée »",
      pb1.get("absentes") == 1 and pb1.get("supprimees") == 0 and pb1.get("expirees") == 0,
      str(pb1))

# (c) base VRAIMENT supprimée : introuvable dans tout le fichier -> « supprimée »
cli = install({
    M_AOUT: {"lines": [
        {"id": "A", "type": "rev", "cat": "rev_of", "form": "fixed", "label": "OF Lola",
         "amount": 1000, "currency": "USD", "freq": "month"},
        {"id": "P2", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Lola",
         "pct": 30, "pct_of": "line:A", "freq": "month"},
    ]},
})
cli.post("/facture/line/delete", data={"month": M_AOUT, "id": "A", "confirm": "1"})
pb2 = line_of(F.compute_state(M_AOUT), "P2").get("pct_base") or {}
check("2c une base réellement supprimée reste comptée « supprimée »",
      pb2.get("supprimees") == 1 and pb2.get("absentes") == 0
      and F.compute_state(M_AOUT)["totals"].get("pct_orphans_supprimees") == 1,
      str(pb2))

# =============================================================================
print("3. base restante à 0 $ : rouge (0 $), pas orange (« montant réduit »)")
cli = install({
    M_AOUT: {"lines": [
        # base vivante mais PAS ENCORE COMMENCÉE -> 0 $ ce mois-ci
        {"id": "C", "type": "rev", "cat": "rev_mym", "form": "fixed", "label": "MyM Nina",
         "amount": 800, "currency": "USD", "start": "2026-10-01", "freq": "month"},
        {"id": "Q", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Nina",
         "pct": 20, "pct_of": "lines:A,C", "freq": "month"},
    ]},
})
st3 = F.compute_state(M_AOUT)
q = line_of(st3, "Q")
check("3a la ligne rendue à 0 $ n'est PAS comptée dans les partielles (orange)",
      st3["totals"]["pct_partielles"] == 0 and st3["totals"]["pct_orphans"] == 1,
      f"partielles={st3['totals']['pct_partielles']} orphans={st3['totals']['pct_orphans']}")
check("3b le montant restant est remonté en dollars, pas en nombre d'ids",
      q.get("usd") == 0.0 and (q.get("pct_base") or {}).get("reste_nul") is True
      and (q.get("pct_base") or {}).get("reste_usd") == 0.0, str(q.get("pct_base")))

# base restante qui vaut ENCORE quelque chose -> orange, et le montant le prouve
cli = install({
    M_AOUT: {"lines": [
        {"id": "C", "type": "rev", "cat": "rev_mym", "form": "fixed", "label": "MyM Nina",
         "amount": 800, "currency": "USD", "freq": "month"},
        {"id": "Q", "type": "exp", "cat": "model", "form": "pct", "label": "Paye Nina",
         "pct": 20, "pct_of": "lines:A,C", "freq": "month"},
    ]},
})
st4 = F.compute_state(M_AOUT)
q4 = line_of(st4, "Q")
check("3c contre-épreuve : base restante à 800 $ -> partielle (orange), 160 $",
      st4["totals"]["pct_partielles"] == 1 and st4["totals"]["pct_orphans"] == 0
      and q4.get("usd") == 160.0,
      f"partielles={st4['totals']['pct_partielles']} usd={q4.get('usd')}")

# =============================================================================
print("4. les phrases du badge (facture_app.js) disent la même chose")
if not HAS_NODE:
    print("  (node absent : badges non vérifiés)")
else:
    # Les états passés au client sont ceux que le SERVEUR vient de produire
    # ci-dessus, pas des dictionnaires écrits à la main : c'est la jointure
    # serveur/client qui mentait, elle doit être testée bout en bout.
    cas = [pb, (q.get("pct_base") or {}), (q4.get("pct_base") or {}), pb2]
    try:
        r = _pct_base_info_js(cas)
    except Exception as e:
        r = None
        check("4 harnais node", False, repr(e)[:200])
    if r:
        absente, reste0, partielle, supprimee = r
        check("4a badge d'une base absente : le mot « supprimé » n'y figure pas du tout",
              "supprim" not in absente["badge"] and "OF Lola" in absente["badge"]
              and absente["tout"] is True,
              absente["badge"])
        check("4b badge d'une base absente : la cause exacte est nommée",
              "absente de ce mois" in absente["badge"], absente["badge"])
        check("4c reste à 0 $ : badge ROUGE et « la ligne compte encore » retiré",
              reste0["tout"] is True and "compte encore" not in reste0["badge"]
              and "0 $" in reste0["badge"], reste0["badge"])
        check("4d vraie partielle : badge ORANGE et promesse « seulement plus petit »",
              partielle["tout"] is False and "seulement plus petit" in partielle["badge"],
              partielle["badge"])
        check("4e base réellement supprimée : le mot reste employé",
              supprimee["tout"] is True and "base supprimée" in supprimee["badge"],
              supprimee["badge"])

    # le bandeau orange promet « PAS à 0 $ » : il doit se lire sur pct_partielles,
    # que le serveur ne remplit plus qu'avec des lignes à reste non nul.
    js = (BOT / "facture_app.js").read_text(encoding="utf-8")
    check("4f le bandeau rouge n'affirme « supprimé » que si le serveur l'a compté",
          "pct_orphans_supprimees" in js, "clé absente du client")

# =============================================================================
print()
print(f"{OK} ok, {len(FAILS)} échec(s)" + ("" if not FAILS else " : " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
