"""Lia seule partout (03/11/2026) : TRUST THREADS et TRUST INSTAGRAM comme Twitter.

Propriétaire : « Lia seule partout ». Les liens de VA des trois TRUST n'ont
plus que deux branches : le tracking du VA (70 %) et la page de Lia sans
tracking (« Base Lia », 30 %). Ce fichier prouve, sans réseau :
  1. espace() de Threads (tel que le patch du VPS le rend, variante Seren
     comprise) et d'Agency : plus de variante, la page de Lia à 70 / 30 ;
     « lia_seule » : false les rend à Seren.
  2. poser_base_seule sur un lien à quatre branches (Agency en page, Threads
     en direct) : « Base Lia » gardée sous son variantId, Seren et « Base
     Seren » retirées, relu à 70 / 30 ; le tracking Seren reste dans la fiche
     (ses subs comptent toujours) ; un second passage ne réécrit rien.
  3. la synchro ne remet pas Seren : reprendre_pays ne recopie pas sa
     variante, reprendre_variantes ne pose rien, reprendre_bases passe par la
     page de base seule.

Lancer depuis la racine du dépôt : python tests_lia_seule_partout.py
"""
from __future__ import annotations

import io
import json
import os
import pathlib
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


import liens_va as lv     # noqa: E402
import gms                # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp())
lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
lv.ETAT_FICHIER = TMP / "liens_va.json"
CONFIG = {"gabarit": "lnk_gabarit", "equipe": lv.EQUIPE_VA, "mypuls_actif": True,
          "creator_id": 3992, "modele": "Lia"}
TH, AG = lv.THREADS_ID, lv.AGENCY_IG_ID


def config(**kw):
    lv.CONFIG_FICHIER.write_text(json.dumps(dict(CONFIG, **kw)))


config()
_orig = lv._espace_avec_seren


def _comme_le_vps(gid=""):
    # le patch 99-threads-mypuls du VPS : Threads a ses trackings et sa
    # variante Seren ; l'enveloppe espace() doit la retirer quand même
    e = _orig(gid)
    if str(gid) == TH:
        e = dict(e, tracking=True, variante=dict(lv.VARIANTE_TWITTER))
    return e


lv._espace_avec_seren = _comme_le_vps

print("1. espace() de Threads et d'Agency")
for gid, nom in ((TH, "Threads"), (AG, "Agency")):
    e = lv.espace(gid)
    check(f"{nom} : plus de variante Seren, la page de Lia à 70 / 30",
          e.get("variante") is None and e.get("base_seule") == lv.LIA_SEULE, e)
check("lia_seule() : les 3 TRUST", all(lv.lia_seule(g) == lv.LIA_SEULE for g in (lv.TWITTER_ID, TH, AG)))
check("Va IG (pas un TRUST) : pas touché", lv.lia_seule("1505418484052394004") is None)
config(lia_seule=False)
check("« lia_seule » : false rend Seren à Threads",
      lv.espace(TH).get("variante") is not None and lv.espace(TH).get("base_seule") is None, lv.espace(TH))
check("… et retire la page seule d'Agency", lv.espace(AG).get("base_seule") is None)
config()

print("2. poser_base_seule sur les liens à quatre branches")


def quatre():
    return {"enabled": True, "controlWeight": 46.7, "variants": [
        {"variantId": "v_seren", "name": "Seren", "weight": 23.3, "description": "Seren"},
        {"variantId": "v_base_lia", "name": "Base Lia", "weight": 20,
         "description": "Variant based on another link"},
        {"variantId": "v_base_seren", "name": "Base Seren", "weight": 10, "description": "x"}]}


AB = {"lnk_ag": quatre(), "lnk_th": quatre()}
POSTS, DUPS = [], []
LIENS = {"lnk_ag": {"type": "landing", "buttons": [{"label": "“exclusive” stuff lol",
                                                     "url": "https://onlyfans.com/liasxcret/c98"}]},
         "lnk_th": {"type": "direct", "url": "https://onlyfans.com/liasxcret/c87"}}


def _ab(methode, lid, equipe, corps):
    POSTS.append((lid, json.loads(json.dumps(corps))))
    AB[lid] = {"enabled": corps["enabled"], "controlWeight": corps["controlWeight"],
               "variants": [dict(v, variantId=v.get("variantId") or "v_neuf") for v in corps["variants"]]}
    return {"ok": True}


gms.lire_ab_testing = lambda lid, equipe=None: {"ok": True, "config": json.loads(json.dumps(AB[lid]))}
gms._ab_prive = _ab
gms.get_link = lambda lid, equipe=None: {"ok": True, "link": LIENS[lid]}
gms.duplicate_link = lambda *a, **k: DUPS.append(a) or {"ok": False, "error": "pas de copie attendue"}
lv.nom_de_page = lambda p: "Lia" if "liasxcret" in str(p) else ""
SEREN_AG, SEREN_TH = "https://onlyfans.com/seren.vale/c230", "https://onlyfans.com/seren.vale/c204"
lv._ecrire({"liens": {
    f"{AG}:u1": {"link_id": "lnk_ag", "shortcode": "dollvelvetyy", "numero": 63,
                 "tracking": "https://onlyfans.com/liasxcret/c98",
                 "variante": {"tracking": SEREN_AG, "posee": True, "bases": True}},
    f"{TH}:u2": {"link_id": "lnk_th", "shortcode": "dreamyy", "numero": 31,
                 "tracking": "https://onlyfans.com/liasxcret/c87",
                 "variante": {"tracking": SEREN_TH, "posee": True, "bases": True, "pays": False}}}})

for gid, uid, lid, nom, seren in ((AG, "u1", "lnk_ag", "Agency (page)", SEREN_AG),
                                  (TH, "u2", "lnk_th", "Threads (direct)", SEREN_TH)):
    n = len(POSTS)
    r = lv.poser_base_seule(gid, uid)
    corps = POSTS[-1][1] if len(POSTS) > n else {}
    vs = corps.get("variants") or []
    check(f"{nom} : posé et relu à 70 / 30", r.get("ok") and r.get("pose"), r)
    check(f"{nom} : « Base Lia » seule, gardée sous son variantId, à 30",
          corps.get("controlWeight") == 70 and len(vs) == 1 and vs[0].get("name") == "Base Lia"
          and vs[0].get("variantId") == "v_base_lia" and vs[0].get("weight") == 30
          and vs[0].get("sourceLinkId") is None, corps)
    f = lv.lien_de(gid, uid)
    check(f"{nom} : noté fait pour la page de Lia",
          (f.get("base_seule") or {}).get("ok") is True
          and (f.get("base_seule") or {}).get("pour") == "https://onlyfans.com/liasxcret", f.get("base_seule"))
    check(f"{nom} : le tracking Seren reste dans la fiche (ses subs comptent)",
          (f.get("variante") or {}).get("tracking") == seren and seren in lv.trackings_de_fiche(f))
    n = len(POSTS)
    r2 = lv.poser_base_seule(gid, uid)
    check(f"{nom} : un second passage reconnaît et ne réécrit rien", r2.get("deja") and len(POSTS) == n, r2)
check("aucune copie temporaire (« Base Lia » existait)", not DUPS, DUPS)

print("3. la synchro ne remet pas Seren")
REFILTRES, COOKIES, SEULES = [], [], []
lv.refiltrer_variante = lambda gid, uid: REFILTRES.append((gid, uid)) or {"ok": True}
gms.get_session_cookie = lambda: COOKIES.append(1) or ""
_rbs = lv.reprendre_base_seule
lv.reprendre_base_seule = lambda gid: SEULES.append(gid) or {}
for gid, nom in ((TH, "Threads"), (AG, "Agency")):
    lv.reprendre_pays(gid)
    lv.reprendre_variantes(gid)
    lv.reprendre_bases(gid)
check("reprendre_pays : la variante Seren n'est pas recopiée (« pays » : false sur Threads)", not REFILTRES, REFILTRES)
check("reprendre_variantes : rien posé, pas même le cookie lu", not COOKIES, COOKIES)
check("reprendre_bases : la page de base seule, sur les deux", SEULES == [TH, AG], SEULES)
lv.reprendre_base_seule = _rbs

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
