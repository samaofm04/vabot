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
Le 10/11/2026 (« remove le truc erreur des 30 % ») la marge sans tracking est
retirée : 1 à 3 la vérifient telle qu'elle reviendrait (clé
« marge_sans_tracking » : true) ; par défaut, ni Seren ni « Base Lia », et la
synchro ne pose rien du tout.

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
config(marge_sans_tracking=True)
for gid, nom in ((TH, "Threads"), (AG, "Agency")):
    e = lv.espace(gid)
    check(f"marge remise, {nom} : plus de variante Seren, la page de Lia à 70 / 30",
          e.get("variante") is None and e.get("base_seule") == lv.LIA_SEULE, e)
check("marge remise : lia_seule() sur les 3 TRUST",
      all(lv.lia_seule(g) == lv.LIA_SEULE for g in (lv.TWITTER_ID, TH, AG)))
check("Va IG (pas un TRUST) : pas touché", lv.lia_seule("1505418484052394004") is None)
config(lia_seule=False, marge_sans_tracking=True)
check("« lia_seule » : false rend Seren à Threads",
      lv.espace(TH).get("variante") is not None and lv.espace(TH).get("base_seule") is None, lv.espace(TH))
check("… et retire la page seule d'Agency", lv.espace(AG).get("base_seule") is None)
config()
for gid, nom in ((TH, "Threads"), (AG, "Agency")):
    e = lv.espace(gid)
    check(f"sans marge (défaut), {nom} : ni Seren ni page de base",
          e.get("variante") is None and e.get("base_seule") is None, e)
check("sans marge : lia_seule() None sur les 3 TRUST, Seren toujours retirée",
      all(lv.lia_seule(g) is None and lv.sans_seren(g) for g in (lv.TWITTER_ID, TH, AG)))

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

config(marge_sans_tracking=True)
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
config()
n = len(POSTS)
r = lv.poser_base_seule(TH, "u2")
check("sans marge : poser_base_seule hors sujet, rien enregistré", r.get("hors_sujet") and len(POSTS) == n, r)

print("3. la synchro ne remet pas Seren")
REFILTRES, COOKIES, SEULES = [], [], []
lv.refiltrer_variante = lambda gid, uid: REFILTRES.append((gid, uid)) or {"ok": True}
gms.get_session_cookie = lambda: COOKIES.append(1) or ""
_rbs = lv.reprendre_base_seule
lv.reprendre_base_seule = lambda gid: SEULES.append(gid) or {}
for marge in (True, False):
    config(**({"marge_sans_tracking": True} if marge else {}))
    REFILTRES.clear(), COOKIES.clear(), SEULES.clear()
    n = len(POSTS)
    for gid, nom in ((TH, "Threads"), (AG, "Agency")):
        lv.reprendre_pays(gid)
        lv.reprendre_variantes(gid)
        lv.reprendre_bases(gid)
    quoi = "marge remise" if marge else "sans marge"
    check(f"{quoi} : reprendre_pays ne recopie pas la variante Seren (« pays » : false sur Threads)",
          not REFILTRES, REFILTRES)
    check(f"{quoi} : reprendre_variantes et reprendre_bases, pas même le cookie lu", not COOKIES, COOKIES)
    if marge:
        check("marge remise : reprendre_bases passe par la page de base seule, sur les deux",
              SEULES == [TH, AG], SEULES)
    else:
        # la garde contre les quatre branches (qui remettraient Seren) est
        # prouvée par tests_liens_ab_twitter : ici, le faux cookie vide les
        # arrêterait de toute façon
        check("sans marge : reprendre_bases ne pose rien, ni page seule ni quatre branches",
              not SEULES and len(POSTS) == n, (SEULES, POSTS[n:]))
lv.reprendre_base_seule = _rbs

print("4. Les pages de TRUST INSTAGRAM (10/11/2026 : plus de 70/30)")
import pages_va as pv     # noqa: E402
config(marge_sans_tracking=True)
check("marge remise : le 70/30 revient sur les pages d'Instagram seulement",
      pv.ab_voulu(AG) and not pv.ab_voulu(lv.TWITTER_ID))
config()
n, nd = len(POSTS), len(DUPS)
check("sans marge : aucune page ne reçoit de 70/30", not pv.ab_voulu(AG) and not pv.ab_voulu(lv.TWITTER_ID))
check("sans marge : la page des 30 % n'est plus fabriquée (lien et passage)",
      pv.poser_base_en_page(AG, "lnk_ag").get("hors_sujet")
      and pv.poser_bases_en_page(AG) == {"poses": [], "rates": []}
      and len(POSTS) == n and len(DUPS) == nd, (POSTS[n:], DUPS[nd:]))

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
