# -*- coding: utf-8 -*-
"""tests_bascule_lia.py — les liens des VA passent d'Emy à Lia, Seren gardée.

Propriétaire, 28/10/2026 : « touche jamais au compte JESSY LE RETOUR mais pour
Twitter tu peux basculer sur l'autre, Instagram aussi et sur Threads aussi en
50/50 avec Seren, crée les trackings et tout », « il faut additionner les subs
de Emy, Lia et Seren ».

Ce qui est vérifié (liens_va.passer_sur, trackings_de_fiche,
trackings_variantes ; subs_va) :
  - lien direct (Twitter, Threads) : tracking Lia au même nom que l'ancien,
    destination changée, A/B gardé, fiche à jour (tracking, code, ancien
    tracking gardé, bascule notée) ;
  - landing (Agency) : seul le bouton OnlyFans change ;
  - déjà chez Lia : rien ; lien coupé : refusé ;
  - tracking apparu hors du profil de Lia : arrêt, lien et fiche intacts ;
  - GetMySocial refuse : la fiche ne bouge pas ;
  - A/B perdu à la mise à jour : dit ;
  - le podium voit le tracking Lia (adresse du lien), Seren (variante) et
    Emy (ancien) sur le lien ;
  - « Mes subs » et le classement d'Agency additionnent les trois — Agency ne
    comptait pas la moitié Seren depuis le 24/10.

Faux GetMySocial, faux MyPuls : aucun appel réseau, rien dans data/.
Lancement : python tests_bascule_lia.py
"""
from __future__ import annotations

import copy
import io
import json
import pathlib
import shutil
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import podium_discord as pod           # noqa: E402
import subs_va                         # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


TW, TH, AG = lv.TWITTER_ID, lv.THREADS_ID, lv.AGENCY_IG_ID
LIA, PROFIL = 3992, "https://onlyfans.com/liasxcret"
AB = {"enabled": True, "variants": [{"variant_id": "v1", "weight": 50, "name": "Seren"}],
      "control_weight": 50}


class FauxGMS(types.ModuleType):
    def __init__(self, liens):
        super().__init__("gms")
        self.liens = liens
        self.appels = []
        self.refuser = False
        self.perdre_ab = False

    def _call_tool(self, outil, args):
        self.appels.append((outil, copy.deepcopy(args)))
        l = self.liens.get(args.get("link_id"))
        if l is None:
            return {"ok": False, "error": "link_not_found"}
        if outil == "get_link":
            return {"ok": True, "data": copy.deepcopy(l)}
        if outil == "update_link":
            if self.refuser:
                return {"ok": False, "error": "403 link_permission_denied"}
            for k in ("url", "buttons", "display_name"):
                if k in args:
                    l[k] = copy.deepcopy(args[k])
            if self.perdre_ab:
                l["ab_testing"] = {"enabled": False, "variants": []}
            return {"ok": True, "data": copy.deepcopy(l)}
        return {"ok": False, "error": f"outil {outil} inattendu"}

    # la règle des pays (liens_va.poser_pays) passe par gms.get_link / update_link
    def get_link(self, lid, team_id=None):
        r = self._call_tool("get_link", {"link_id": lid})
        return {"ok": r["ok"], "link": r.get("data"), "error": r.get("error")}

    def update_link(self, lid, champs, team_id=None):
        self.appels.append(("pays", lid))
        l = self.liens.get(lid)
        if l is None:
            return {"ok": False, "error": "link_not_found"}
        for k in ("geofilters", "buttons"):
            if k in champs:
                l[k] = copy.deepcopy(champs[k])
        return {"ok": True, "link": copy.deepcopy(l)}


def direct(lid, url):
    return {"id": lid, "type": "directlink", "url": url, "buttons": None,
            "display_name": "x", "ab_testing": copy.deepcopy(AB)}


def landing(lid, url):
    return {"id": lid, "type": "landing", "url": None, "display_name": "Instagram VA 63 @roucham",
            "ab_testing": copy.deepcopy(AB),
            "buttons": [{"label": "“exclusive” stuff lol ", "url": url, "button_effect": "2"},
                        {"label": "insta", "url": "https://instagram.com/x"}]}


def fiche(n, pseudo, lid, emy, seren, **kw):
    return dict({"pseudo": pseudo, "numero": n, "shortcode": f"sc{n}", "link_id": lid,
                 "tracking": emy, "code": emy.rsplit("/", 1)[1],
                 "variante": {"posee": True, "modele": "Seren", "creator_id": 3867,
                              "tracking": seren}}, **kw)


ETAT = {"liens": {
    f"{TW}:u32": fiche(32, "bid_a", "lnk_tw32", "https://onlyfans.com/emy.brw/c5",
                       "https://onlyfans.com/seren.vale/c195"),
    f"{TH}:u61": fiche(61, "momobtn", "lnk_th61", "https://onlyfans.com/emy.brw/c79",
                       "https://onlyfans.com/seren.vale/c202"),
    f"{AG}:u63": fiche(63, "roucham", "lnk_ag63", "https://onlyfans.com/emy.brw/c118",
                       "https://onlyfans.com/seren.vale/c230"),
    f"{TW}:u31": fiche(31, "abdoul", "lnk_tw31", "https://onlyfans.com/emy.brw/c6",
                       "https://onlyfans.com/seren.vale/c196", actif=False),
    f"{TW}:u69": fiche(69, "sieg", "lnk_tw69", "https://onlyfans.com/emy.brw/c74",
                       "https://onlyfans.com/seren.vale/c194"),
}}
LIENS = {"lnk_tw32": direct("lnk_tw32", "https://onlyfans.com/emy.brw/c5"),
         "lnk_th61": direct("lnk_th61", "https://onlyfans.com/emy.brw/c79"),
         "lnk_ag63": landing("lnk_ag63", "https://onlyfans.com/emy.brw/c118"),
         "lnk_tw31": direct("lnk_tw31", "https://onlyfans.com/emy.brw/c6"),
         "lnk_tw69": direct("lnk_tw69", "https://onlyfans.com/emy.brw/c74")}

TMP = pathlib.Path(tempfile.mkdtemp(prefix="bascule_lia_"))
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "_creer_ou_reprendre")}
_SAUVE_GMS = sys.modules.get("gms")
_SAUVE_POD = pod._lire_mypuls
crees = []
try:
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    lv.CONFIG_FICHIER.write_text(json.dumps({"creator_id": 3352, "mypuls_actif": True,
                                             "equipe": "tm_tw", "gabarit": "lnk_g",
                                             "threads": {"tracking": True}}))
    lv.ETAT_FICHIER.write_text(json.dumps(ETAT))
    g = FauxGMS(LIENS)
    sys.modules["gms"] = g
    codes = {"Twitter VA 32 @bid_a": "c60", "Threads VA 61 @momobtn": "c63",
             "Instagram VA 63 @roucham": "c64", "Twitter VA 69 @sieg": "c65"}

    def faux_creer(nom, creator_id=None):
        crees.append((nom, creator_id))
        if nom == "Twitter VA 69 @sieg":
            # la bascule de créatrice a raté : créé chez Emy
            return {"ok": True, "url": "https://onlyfans.com/emy.brw/c140", "code": "c140"}
        return {"ok": True, "url": f"{PROFIL}/{codes[nom]}", "code": codes[nom]}
    lv._creer_ou_reprendre = faux_creer

    # ── lien direct (Twitter) ──
    r = lv.passer_sur(TW, "u32", LIA, PROFIL)
    f = lv.lien_de(TW, "u32")
    check("Twitter : tracking Lia au même nom que l'ancien, chez Lia",
          r.get("ok") and crees[-1] == ("Twitter VA 32 @bid_a", LIA)
          and r["tracking"] == f"{PROFIL}/c60", (r, crees))
    check("… destination du lien changée, A/B gardé",
          LIENS["lnk_tw32"]["url"] == f"{PROFIL}/c60" and LIENS["lnk_tw32"]["ab_testing"]["enabled"])
    check("… fiche : tracking, code, ancien gardé, bascule notée",
          f["tracking"] == f"{PROFIL}/c60" and f["code"] == "c60"
          and f["anciens_trackings"] == ["https://onlyfans.com/emy.brw/c5"]
          and f["bascule"]["vers"] == LIA and f["bascule"]["de"].endswith("/c5")
          and f["variante"]["tracking"].endswith("/c195"), f)
    n = len(g.appels)
    r2 = lv.passer_sur(TW, "u32", LIA, PROFIL)
    check("déjà chez Lia : rien de refait", r2.get("ok") and r2.get("deja") and len(g.appels) == n
          and len(crees) == 1, r2)

    # ── Threads (direct aussi) ──
    r = lv.passer_sur(TH, "u61", LIA, PROFIL)
    check("Threads : « Threads VA 61 @momobtn » chez Lia, lien changé",
          r.get("ok") and crees[-1] == ("Threads VA 61 @momobtn", LIA)
          and LIENS["lnk_th61"]["url"] == f"{PROFIL}/c63", (r, crees))

    # ── landing (Agency) ──
    r = lv.passer_sur(AG, "u63", LIA, PROFIL)
    b = LIENS["lnk_ag63"]["buttons"]
    check("Agency (landing) : seul le bouton OnlyFans change, le nom de la page reste",
          r.get("ok") and b[0]["url"] == f"{PROFIL}/c64" and b[1]["url"] == "https://instagram.com/x"
          and LIENS["lnk_ag63"]["display_name"] == "Instagram VA 63 @roucham", (r, b))

    # ── la règle des pays suit la model (29/10/2026) ──
    geo = LIENS["lnk_tw32"].get("geofilters") or []
    f = lv.lien_de(TW, "u32")
    check("pays : les autres pays partent sur le compte de la NOUVELLE model, plus l'ancienne",
          len(geo) == 250 and {x["destination_url"] for x in geo} == {PROFIL}
          and f.get("pays") is True, ({x["destination_url"] for x in geo}, f.get("pays_erreur")))
    check("… sa variante Seren (copie figée) est notée à recopier : « variante.pays » : false",
          (f.get("variante") or {}).get("pays") is False and f["variante"].get("posee") is True, f)
    check("… landing : la liste sur le bouton OnlyFans, vers la nouvelle model",
          {x["destination_url"] for x in (b[0].get("geofilters") or [])} == {PROFIL}
          and len(b[0]["geofilters"]) == 250 and "geofilters" not in b[1], b)

    # ── lien coupé ──
    r = lv.passer_sur(TW, "u31", LIA, PROFIL)
    check("lien coupé : refusé, rien créé", not r.get("ok") and len(crees) == 3
          and LIENS["lnk_tw31"]["url"].endswith("/c6"), r)

    # ── tracking hors de Lia ──
    avant = json.loads(lv.ETAT_FICHIER.read_text())[ "liens"][f"{TW}:u69"]
    n = len(g.appels)
    r = lv.passer_sur(TW, "u69", LIA, PROFIL)
    check("tracking apparu chez Emy : arrêt, lien et fiche intacts",
          not r.get("ok") and r.get("arreter") and LIENS["lnk_tw69"]["url"].endswith("/c74")
          and lv.lien_de(TW, "u69") == avant
          and not [a for a in g.appels[n:] if a[0] == "update_link"], r)

    # ── GetMySocial refuse ──
    codes["Twitter VA 69 @sieg"] = "c65"
    lv._creer_ou_reprendre = lambda nom, creator_id=None: {"ok": True, "url": f"{PROFIL}/c65",
                                                           "code": "c65"}
    g.refuser = True
    r = lv.passer_sur(TW, "u69", LIA, PROFIL)
    check("GetMySocial refuse : dit, fiche intacte (le tracking existe, repris au prochain essai)",
          not r.get("ok") and r.get("tracking") == f"{PROFIL}/c65"
          and lv.lien_de(TW, "u69") == avant, r)
    g.refuser = False
    g.perdre_ab = True
    r = lv.passer_sur(TW, "u69", LIA, PROFIL)
    check("A/B perdu : la bascule est faite, la perte est dite",
          not r.get("ok") and "A/B perdu" in r.get("erreur", "")
          and lv.lien_de(TW, "u69")["tracking"] == f"{PROFIL}/c65", r)
    g.perdre_ab = False

    # ── ce que le podium et les subs voient ──
    f32 = lv.lien_de(TW, "u32")
    check("trackings_de_fiche : Lia, Seren, Emy, sans doublon",
          lv.trackings_de_fiche(f32) == [f"{PROFIL}/c60", "https://onlyfans.com/seren.vale/c195",
                                         "https://onlyfans.com/emy.brw/c5"],
          lv.trackings_de_fiche(f32))
    tl = pod.trackings_du_lien({"id": "lnk_tw32", "url": f"{PROFIL}/c60"})
    check("podium : le lien porte Lia, Seren et Emy",
          tl == ["liasxcret/c60", "seren.vale/c195", "emy.brw/c5"], tl)
    tl31 = pod.trackings_du_lien({"id": "lnk_tw31", "url": "https://onlyfans.com/emy.brw/c6"})
    check("… un lien pas basculé : inchangé (Emy + Seren)",
          tl31 == ["emy.brw/c6", "seren.vale/c196"], tl31)
    check("« Mes subs » : les trois trackings du VA",
          [u for _p, u in subs_va.trackings_du_va(TW, "u32")] == lv.trackings_de_fiche(f32))
    ents = subs_va.entites_agency()
    check("Agency : Lia, Seren ET Emy comptés (la moitié Seren ne l'était pas)",
          [u for _p, u in ents["u63"]["trackings"]]
          == [f"{PROFIL}/c64", "https://onlyfans.com/seren.vale/c230",
              "https://onlyfans.com/emy.brw/c118"], ents.get("u63"))
    pod._lire_mypuls = lambda d0, d1, forcer=False: ({
        "liasxcret/c64": {"subs": 4, "nom": "Instagram VA 63 @roucham"},
        "seren.vale/c230": {"subs": 3, "nom": "Instagram VA 63 @roucham"},
        "emy.brw/c118": {"subs": 5, "nom": "Instagram VA 63 @roucham"}}, "")
    cl = subs_va.classement_agency(pod._aujourdhui(), pod._aujourdhui())
    check("… le classement d'Agency additionne : 4 + 3 + 5 = 12",
          [(x["va"], x["clics"]) for x in cl["lignes"]] == [("Instagram VA 63", 12)], cl["lignes"])
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    pod._lire_mypuls = _SAUVE_POD
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS
    else:
        sys.modules.pop("gms", None)
    lv._VARIANTES_LUES.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
