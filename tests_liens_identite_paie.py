# -*- coding: utf-8 -*-
"""tests_liens_identite_paie.py — les liens d'identite US ne faussent ni le
podium, ni la page Infloww, ni la paie, ni les clics.

La demande (proprietaire, 06/10) : chaque VA US cree lui-meme une page
GetMySocial par identite (liens_identite_us), copiee d'une page de base
« TEMPLATE <identite> » faite a la main dans l'espace JESSY LE RETOUR, et qui
vise LE MEME lien de suivi OnlyFans (c<N>) que son lien « global ».

Ce qui est verifie, sur les 46 vrais liens de l'espace (lus le 06/10), deux
pages de base et des pages d'identite d'EUD, de tsiry 1 et de LaBoule :
  1. UNE regle des gabarits (clics_personnes.est_gabarit) : une page de base
     n'est ni une personne du podium (pas de numero de VA grave a vie dans
     podium_numeros.json, pas d'appel GetMySocial), ni une ligne de la page
     Infloww, ni une ligne des clics ; elle est nommee, pas avalee. Rien ne
     change pour les liens d'aujourd'hui ni pour les autres espaces (EMY
     TWITTER, Va IG) : compare au code d'origine/main (64378fe, lu dans git).
  2. La paie : une page d'identite n'est pas une ligne ; la ligne de son
     global est active sur une tranche si le global OU une de ses pages y a
     fait un clic. Les pages ne sont relevees que si le global a un zero
     confirme (budget LIGNES_APPELS_JOUR), jamais avant leur creation ; une
     tranche figee n'est pas recalculee ; le « qui » d'un releve reste celui
     d'une ligne. Les clics US « depuis toujours » additionnent les pages
     (un appel par personne) ; les subs comptent les codes Infloww DISTINCTS.
  3. Les clics (clics_personnes.grouper) : une page d'identite rejoint la
     personne de son global par l'identifiant, meme quand les regles de nom
     du podium et des clics divergent (« tsiry 1 », « LaBoule ( Phone ) ») ;
     le report des clics de JESSY LE RETOUR ecarte ses gabarits avant tout
     releve, et l'image du report les nomme encore.
  4. Le contrat avec liens_identite_us, s'il est deja ecrit : est_base est
     inclus dans est_gabarit, et nom_lien donne au podium la cle du global.

Doublures : gms (aucun appel reseau), le registre liens_identite_us
(rattachements). Dossier temporaire : rien n'est ecrit dans data/.
Lancement : venv/bin/python tests_liens_identite_paie.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import types

ICI = pathlib.Path(__file__).resolve().parent
os.chdir(ICI)
sys.path.insert(0, str(ICI))

REF = "64378fe"                       # origin/main avant ce travail
NB = {"ok": 0, "ko": 0}


def check(nom: str, cond, detail="") -> None:
    if cond:
        NB["ok"] += 1
        print(f"  ok   {nom}")
    else:
        NB["ko"] += 1
        print(f"  KO   {nom}" + (f"\n         {str(detail)[:600]}" if detail != "" else ""))


# ─── les doublures, AVANT tout import du code ─────────────────────────────
# Le registre des liens d'identite : un faux module, pilote par REG.
REG = {"ratt": {}, "panne": None}
_LIU_AVANT = sys.modules.get("liens_identite_us")
faux_liu = types.ModuleType("liens_identite_us")


def _rattachements():
    if REG["panne"] is not None:
        raise REG["panne"]
    return dict(REG["ratt"])


faux_liu.rattachements = _rattachements
sys.modules["liens_identite_us"] = faux_liu

# GetMySocial : listes par espace, clics par (lien, tranche), appels notes.
GMS = {"listes": {}, "clics": {}, "us": {}, "appels": [], "lots": []}
_GMS_AVANT = sys.modules.get("gms")
faux_gms = types.ModuleType("gms")


def _clics_de(lid, d0, d1):
    v = GMS["clics"].get(lid, 0)
    if isinstance(v, dict):
        return int(v.get((d0, d1), 0))
    return int(v)


def _list_links_team(team, force_refresh=False):
    return {"ok": True, "links": [dict(l) for l in GMS["listes"].get(team, [])]}


def _analytics_for_link(lid, d0, d1):
    GMS["appels"].append((lid, d0, d1))
    n = _clics_de(lid, d0, d1)
    return n, ({"US": n} if n else {})


def _analytics_for_links(ids, d0, d1):
    GMS["lots"].append((tuple(sorted(ids)), d0, d1))
    us = sum(int(GMS["us"].get(i, 0)) for i in ids)
    return us + 1, {"US": us, "FR": 1}


def _get_analytics_overview(du, au, link_ids=None):
    GMS["appels"].append(("verif", tuple(link_ids or ()), du, au))
    n = sum(_clics_de(i, du, au) for i in (link_ids or ()))
    return {"ok": True, "data": {"total_clicks": n, "top_countries": []}}


def _lire_analytics(res):
    return int(res["data"]["total_clicks"]), {}


faux_gms.list_links_team = _list_links_team
faux_gms.analytics_for_link = _analytics_for_link
faux_gms.analytics_for_links = _analytics_for_links
faux_gms.get_analytics_overview = _get_analytics_overview
faux_gms._lire_analytics = _lire_analytics
faux_gms.pause_restante = lambda: 0
faux_gms.etat_quota = lambda: {"pause_s": 0, "reprise": "", "restant_jour": None, "raison": ""}
sys.modules["gms"] = faux_gms

import clics_personnes as cp            # noqa: E402
import podium_discord as pd             # noqa: E402
# Cette suite verifie la mecanique du podium sur les clics GetMySocial (Va IG,
# et Twitter jusqu au 06/10/2026) : Twitter y repasse, sans quoi il lirait le
# vrai MyPuls. Le comptage par tracking a ses tests : tests_podium_tracking.py.
pd.SERVEURS[pd.TWITTER_ID].pop("mesure", None)
import infloww_liens as il              # noqa: E402

# ─── le bac a sable : data/ jamais touche ────────────────────────────────
TMP = pathlib.Path(tempfile.mkdtemp(prefix="liens_identite_paie_"))
pd.DATA_DIR = TMP
pd.ETAT_FICHIER = TMP / "podium.json"
pd.CONFIG_FICHIER = TMP / "podium_config.json"
pd.NUMEROS_FICHIER = TMP / "podium_numeros.json"
pd.LIENS_CACHE = TMP / "gmsdash_links.json"
pd.ALLTIME_FICHIER = TMP / "podium_alltime.json"
for _n in ("ETAT_FICHIER", "CONFIG_FICHIER", "US_FICHIER", "US_PERIODES_FICHIER", "GMS_COPIE",
           "PAIE_FICHIER", "QUINZ_FICHIER", "BCE_FICHIER", "LIGNES_FICHIER", "CLE_FICHIER",
           "CLE_PAIE_FICHIER"):
    setattr(il, _n, TMP / f"il_{_n.lower()}.json")
il.GMS_CACHE = TMP / "gmsdash_links.json"
il.US_EN_FOND = il.LIGNES_EN_FOND = il.QUINZ_EN_FOND = False
il._dormir_us = lambda s: None
il._dormir_q = lambda s: None
il._bce_http = lambda: (_ for _ in ()).throw(RuntimeError("BCE non bouchonnee"))
JOUR = {"j": "2026-10-06"}
il._aujourdhui = lambda: JOUR["j"]

# ─── les 46 vrais liens de JESSY LE RETOUR (liste GetMySocial du 06/10) ──
# (id, shortcode, nom, code de suivi) — tous des liens directs vers
# onlyfans.com/jessyewdiference/c<N>.
REELS = [
    ("lnk_6ac140ba0b1140e50ba7a009", "prstjessye", "Printsyyy X1", 131),
    ("lnk_6abe1b34555277271dc49169", "secretjessye", "Micky", 126),
    ("lnk_6abe1b0337937d95663530cb", "loveejessye", "tsiry 2", 126),
    ("lnk_6abe1ae51eecdf1691b98b6f", "lovejessye", "tsiry 1", 126),
    ("lnk_6abe1ac4e1117ecf395c0e60", "cutxjessye", "eddy 2", 126),
    ("lnk_6abe1a9d37937d9566352b6c", "cutejessye", "eddy 1", 126),
    ("lnk_6aba05a9607a9585322e9f31", "crerjessye", "( Carter ) 3", 129),
    ("lnk_6aba0592607a9585322e9b81", "crtrjessye", "( Carter ) 2", 129),
    ("lnk_6aba051b55a5908a47f76592", "crtsjessye", "( Carter ) SPAM", 130),
    ("lnk_6aba04fad38dbae582b4333e", "crtejessye", "( Carter ) 1", 129),
    ("lnk_6ab965b21173088818a73b17", "moanjessye", "( Moan ) 1", 127),
    ("lnk_6ab9657b74b7baff6c586cff", "yzdjessye", "( Yazid ) 1", 128),
    ("lnk_6ab818fa74b7baff6c457f35", "cutyjessye", "(Roucham) 2", 88),
    ("lnk_6aada17d2ca1f12d16b779a2", "cutyxjessye", "(Gerome) SPAM", 124),
    ("lnk_6aaa4862f8e7bb1c51a679ec", "sweetjessye", "(VA 6 Noum) 1", 123),
    ("lnk_6aaa47f4695aae833dc64429", "dreamjessye", "(VA 5 Noum) 1", 122),
    ("lnk_6a9fd1728f00207299ec040b", "trsvjessye", "(TRAVIS) 1", 120),
    ("lnk_6a9c107102cce46ce2dcc64c", "bnsejessye", "(ANDRY) 2", 87),
    ("lnk_6a9c1052e92a6bdb5e732c7a", "bnesjessye", "(ANDRY) 1", 87),
    ("lnk_6a9b830982ff27ad6a5b13e3", "jnrjessye", "(DOLAD) 1", 118),
    ("lnk_6a9acbd7e00c8d4e750c3643", "rmvxjessy", "(Abdoul) SPAM", 115),
    ("lnk_6a9acb765c52dca77615e975", "hsvtjessy", "(Kylmich) SPAM", 114),
    ("lnk_6a9aca525c52dca77615c52d", "dhysjessye", "(Ricardo) 1 SPAM", 113),
    ("lnk_6a9ac8ea67c379119396139b", "kntsjessye", "(Roucham) 1SPAM", 110),
    ("lnk_6a977b9c3896661191c1ea25", "jesssvme", "TWITTER", 121),
    ("lnk_6a976ef53cb716046f6c88fe", "smljessye", "(PAMPAM) 1 SPAM", 116),
    ("lnk_6a8f792a7aa5923360cccbc4", "msgejessye", "EUD", 117),
    ("lnk_6a8d37fde5a41e3872409c50", "cipsjessy", "(VA 4 Noum)", 97),
    ("lnk_6a8b4b8714b37dc8996e1042", "hstujessye", "( Jaurel ) 2", 83),
    ("lnk_6a87332c855ddc45b1ec7c36", "hzysjessye", "(PAMPAM) 1", 96),
    ("lnk_6a8732e82a99dd49a091c423", "dhsyjessye", "(Ricardo) 1", 92),
    ("lnk_6a87320c2e2c19bece077bdf", "bsytjessye", "LaBoule ( Phone )", 125),
    ("lnk_6a8717c5ad7d51ec19dcf647", "ghezjessye", "Laboule ( X )", 126),
    ("lnk_6a8717b72e2c19bece065f17", "nsyejessye", "( BO7 ) 2", 85),
    ("lnk_6a6224c47e0f5e0625458acd", "bertjessye", "(Gerome) 1", 94),
    ("lnk_6a5167c3661861fd7a0eaa59", "knstjessye", "(Roucham) 1", 88),
    ("lnk_6a5167a9124b8220a218f2de", "hstvjessy", "(Kylmich) 1", 86),
    ("lnk_6a0e5415a5835045d4a1a4d2", "rmxvjessy", "(Abdoul) 1", 91),
    ("lnk_6a0e54087917759f8b67d6b5", "ldkpjessy", "(VA 3 Noum) 1", 52),
    ("lnk_6a0e540151a8673d099b79e3", "wzyfjessy", "(VA 2 Noum) 1", 51),
    ("lnk_6a0e53f9bfa0c238f20b46b8", "tbhcjessy", "(Miranto) 1", 90),
    ("lnk_6a0e53e19a5ce8394b308002", "nqrjjessy", "(Mykey) 1", 95),
    ("lnk_6a0e5362fea0a6e3ed3390d9", "pvxajessy", "( Jaurel ) 1", 83),
    ("lnk_6a0e5346fba948185cdbdfaf", "kfwojessy", "( VA 1 Noum ) 1", 47),
    ("lnk_6a0e533ba5835045d4a19815", "ztrkjessy", "( Safidy ) 1", 84),
    ("lnk_6a0e5332c08c737549671aa5", "xqvnjessy", "( BO7 ) 1", 85),
]
OF = "https://onlyfans.com/jessyewdiference/c%d"
JESSY = "tm_6a0e4739bfa0c238f20a8bf5"
EMY = "tm_6ab46ebb11a0232c11211b1a"


def _direct(lid, sc, nom, code):
    return {"id": lid, "object": "link", "type": "directlink", "shortcode": sc, "display_name": nom,
            "status": "active", "url": OF % code, "buttons": None}


def _oid(jour: str, suite: str) -> str:
    """Un identifiant GetMySocial dont l'horodatage est `jour` à midi : c'est
    lui qui date la création d'une page (infloww_liens.cree_gms)."""
    ts = int(dt.datetime.fromisoformat(jour + "T12:00:00").timestamp())
    return "lnk_%08x%s" % (ts, (suite * 16)[:16])


def _landing(lid, sc, nom):
    # une page (landing) : pas d'adresse a elle, ses boutons visent le suivi
    return {"id": lid, "object": "link", "type": "landing", "shortcode": sc, "display_name": nom,
            "status": "active", "url": None,
            "buttons": [{"label": "OnlyFans", "url": "(celle du global)"}]}


ID = {nom: lid for lid, _sc, nom, _c in REELS}
EUD = ID["EUD"]
BASE_IBEN = _landing(_oid("2026-09-19", "b1"), "tplibenhaastrup", "TEMPLATE ibenhaastrup")
BASE_JULIA = _landing(_oid("2026-09-19", "b2"), "tpljulia", "TEMPLATE julia")
I1 = _landing(_oid("2026-09-20", "a1"), "eudiben", "(EUD) ibenhaastrup")
I2 = _landing(_oid("2026-10-02", "a2"), "eudjulia", "(EUD) julia")
I3 = _landing(_oid("2026-10-02", "a3"), "tsiryiben", "(tsiry 1) ibenhaastrup")
I4 = _landing(_oid("2026-10-02", "a4"), "labouleiben", "(Phone) ibenhaastrup")
RATT = {I1["id"]: EUD, I2["id"]: EUD, I3["id"]: ID["tsiry 1"], I4["id"]: ID["LaBoule ( Phone )"]}
REELS_L = [_direct(*r) for r in REELS]
LIENS = REELS_L + [BASE_IBEN, BASE_JULIA, I1, I2, I3, I4]
REG["ratt"] = dict(RATT)


def _ancien(module: str):
    """Le module tel qu'il est sur origin/main (REF), lu dans git, importe
    sous un autre nom. None si git ne le rend pas."""
    try:
        src = subprocess.run(["git", "-C", str(ICI), "show", f"{REF}:{module}.py"],
                             capture_output=True, text=True, timeout=30, check=True).stdout
    except Exception as e:                                   # noqa: BLE001
        print(f"  (git show {REF}:{module}.py impossible : {e})")
        return None
    f = TMP / f"ancien_{module}.py"
    f.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"ancien_{module}", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


OLD_PD = _ancien("podium_discord")
OLD_CP = _ancien("clics_personnes")


# ═════════════════════════════════════════════════════════════════════════
print("1) Une seule regle des gabarits")
check("« TEMPLATE ibenhaastrup », « template julia », « TEMPLATE  X » sont des gabarits",
      all(cp.est_gabarit(n) for n in ("TEMPLATE ibenhaastrup", "template julia", " TEMPLATE  X ")))
check("aucun des 46 vrais liens n'est un gabarit",
      not [n for _i, _s, n, _c in REELS if cp.est_gabarit(n)])
check("ni podium_discord ni infloww_liens n'ont leur propre liste de gabarits",
      all("GABARITS" not in pathlib.Path(f).read_text(encoding="utf-8")
          and "templ\"" not in pathlib.Path(f).read_text(encoding="utf-8").lower()
          for f in ("podium_discord.py", "infloww_liens.py")))


# ═════════════════════════════════════════════════════════════════════════
print("2) Podium")
ents = pd.entites(LIENS)
check("une page de base n'est pas une personne du podium",
      not [k for k in ents if "template" in k.lower()], sorted(ents))
check("les pages de base sont nommees (pd.gabarits), pas avalees",
      pd.gabarits(LIENS) == ["TEMPLATE ibenhaastrup", "TEMPLATE julia"], pd.gabarits(LIENS))
check("EUD : son global et ses deux pages, une seule personne",
      sorted(ents["EUD"]["ids"]) == sorted([EUD, I1["id"], I2["id"]]), ents.get("EUD"))
check("tsiry 1 et LaBoule ( Phone ) : la page rejoint la cle du podium de son global",
      I3["id"] in ents["tsiry 1"]["ids"] and I4["id"] in ents["Phone"]["ids"])
if OLD_PD:
    anciens = OLD_PD.entites(REELS_L)
    check("les 46 liens d'aujourd'hui : memes personnes, memes liens qu'avant",
          {k: sorted(v["ids"]) for k, v in pd.entites(REELS_L).items()}
          == {k: sorted(v["ids"]) for k, v in anciens.items()})
    check("et les memes personnes une fois pages de base et pages d'identite ajoutees",
          set(ents) == set(anciens), sorted(set(ents) ^ set(anciens)))
    check("(le code d'avant en faisait des personnes : « TEMPLATE ibenhaastrup » numerotable)",
          "TEMPLATE ibenhaastrup" in OLD_PD.entites(LIENS))
# le rattachement est un fait du registre, pas du nom
renomme = dict(I1, display_name="Bidule ibenhaastrup")
check("une page renommee reste a la personne de son global",
      renomme["id"] in pd.entites(REELS_L + [renomme])["EUD"]["ids"])
piege = dict(I2, display_name="(EUD) templeton")
check("une page rattachee n'est jamais prise pour un gabarit (identite « templeton »)",
      piege["id"] in pd.entites(REELS_L + [piege])["EUD"]["ids"]
      and pd.gabarits(REELS_L + [piege]) == [])
seul = [l for l in LIENS if l["id"] != EUD]
check("sans son global dans la liste, une page garde la personne de son nom",
      sorted(pd.entites(seul)["EUD"]["ids"]) == sorted([I1["id"], I2["id"]]))
REG["ratt"] = {}
check("registre vide : le nom suffit (EUD, Carter SPAM...) et les gabarits restent dehors",
      sorted(pd.entites(LIENS)["EUD"]["ids"]) == sorted([EUD, I1["id"], I2["id"]])
      and not [k for k in pd.entites(LIENS) if "template" in k.lower()])
REG["ratt"] = dict(RATT)

# la regle ETROITE : seul un nom qui COMMENCE par le mot du gabarit sort
TEAM = [{"id": "lnk_tw5", "display_name": "Twitter VA 5 @teamplayer"},
        {"id": "lnk_tw6", "display_name": "Twitter VA 6 @abdoul"},
        {"id": "lnk_tp1", "display_name": "(Teamplayer) 1"},
        {"id": "lnk_tpl", "display_name": "TEMPLATE ibenhaastrup"},
        {"id": "lnk_tpl2", "display_name": "Tempalte julia"}]
_e_team = pd.entites(TEAM, {})
check("podium : « Twitter VA 5 @teamplayer » et « (Teamplayer) 1 » restent des personnes",
      "teamplayer" in _e_team and "Teamplayer" in _e_team and "abdoul" in _e_team, sorted(_e_team))
check("podium : seules les pages qui COMMENCENT par TEMPLATE sont des gabarits",
      pd.gabarits(TEAM, {}) == ["TEMPLATE ibenhaastrup", "Tempalte julia"], pd.gabarits(TEAM, {}))
check("commence_par_gabarit : contenue dans est_gabarit, « Temple 1 » / « Templeton » non",
      all(cp.est_gabarit(n) for n in ("TEMPLATE x", "Tempalte x", "Teamplte x", "TEMPLATES"))
      and all(cp.commence_par_gabarit(n) for n in ("TEMPLATE x", "Tempalte x", "Teamplte x", "TEMPLATES"))
      and not any(cp.commence_par_gabarit(n) for n in ("Temple 1", "Templeton", "(Teamplayer) 1",
                                                       "Twitter VA 5 @teamplayer", "va_template")))
if OLD_PD:
    check("EMY / Twitter : avec un pseudo « teamplayer », exactement les personnes d'avant",
          {k: v["ids"] for k, v in pd.entites(TEAM[:3], {}).items()}
          == {k: v["ids"] for k, v in OLD_PD.entites(TEAM[:3]).items()})

# numeros : rien de grave a vie pour une page de base
pd.NUMEROS_FICHIER.unlink(missing_ok=True)
table = pd.numeros(list(ents.keys()), attribuer=True)
disque = json.loads(pd.NUMEROS_FICHIER.read_text(encoding="utf-8"))
check("podium_numeros.json : aucune page de base, aucune page d'identite numerotee",
      not [k for k in disque if "template" in k.lower() or "ibenhaastrup" in k.lower()
           or "julia" in k.lower()], sorted(disque))
check("podium_numeros.json : un numero par personne, pas un de plus",
      set(disque) == set(ents) | set(pd.NUMEROS_HISTORIQUES), sorted(set(disque) - set(ents)))

# le classement entier, faux GetMySocial : les deux espaces du podium Twitter
EMY_L = [_direct("lnk_6ab46eabea8f46bb2cae2026", "emytest", "test emy", 3),
         {"id": "lnk_6ab46f000000000000000001", "shortcode": "emycute", "display_name":
          "Twitter VA 1 @abdoul", "url": "https://onlyfans.com/emywdiff/c4", "status": "active"}]
GMS["listes"] = {JESSY: LIENS, EMY: EMY_L}
GMS["us"] = {EUD: 10, I1["id"]: 5, I2["id"]: 2, BASE_IBEN["id"]: 99, BASE_JULIA["id"]: 99}
GMS["lots"].clear()
pd.NUMEROS_FICHIER.unlink(missing_ok=True)
cl = pd.classement(dt.date(2026, 9, 28), dt.date(2026, 10, 4), pause=0)
lots = [ids for ids, _d0, _d1 in GMS["lots"]]
check("classement : aucun appel GetMySocial pour une page de base",
      not [ids for ids in lots if BASE_IBEN["id"] in ids or BASE_JULIA["id"] in ids], lots)
check("classement : EUD releve en UN appel, ses pages comprises",
      tuple(sorted([EUD, I1["id"], I2["id"]])) in lots)
num_eud = pd.numeros([], attribuer=False).get("EUD")
ligne_eud = [x for x in cl["lignes"] if x["va"] == f"VA {num_eud}"]
check("classement : la ligne d'EUD compte les clics US de ses pages (10 + 5 + 2)",
      len(ligne_eud) == 1 and ligne_eud[0]["clics"] == 17 and ligne_eud[0]["liens"] == 3, ligne_eud)
check("classement : les gabarits ecartes sont dits (cl['gabarits'])",
      cl.get("gabarits") == ["TEMPLATE ibenhaastrup", "TEMPLATE julia"], cl.get("gabarits"))
check("classement : autant de lignes que de personnes (46 liens -> memes personnes, + EMY)",
      cl["entites"] == len(ents) + len(pd.entites(EMY_L)), (cl["entites"], len(ents)))
if OLD_PD:
    check("EMY TWITTER inchange (« test emy », « Twitter VA 1 @abdoul »)",
          {k: v["ids"] for k, v in pd.entites(EMY_L).items()}
          == {k: v["ids"] for k, v in OLD_PD.entites(EMY_L).items()})
    VAIG = [{"id": "l1", "display_name": "Amelia VA 3 @bob"}, {"id": "l2", "display_name": "TEMPLATE OF AMELIA"},
            {"id": "l3", "display_name": "Amelia 1"}, {"id": "l4", "display_name": "Amelia VA 3-2 @bob"}]
    check("Va IG (entites_fr) inchange",
          pd.entites_fr(VAIG) == OLD_PD.entites_fr(VAIG), pd.entites_fr(VAIG))


# ═════════════════════════════════════════════════════════════════════════
print("3) Page Infloww")


def _inf(code, subs, net=1000, clics=100, cree="2026-08-01"):
    return {"id": f"inf{code}", "nom": f"suivi c{code}", "code": str(code), "clics": clics,
            "abonnes": subs, "net": net, "brut": net, "termine": False, "maj": 1790382831491,
            "cree": cree, "devise": "USD"}


CODES = sorted({c for *_x, c in REELS})
INF = [_inf(c, 7 if c == 117 else 3) for c in CODES]
t = il.construire(INF, LIENS, lu_a=1790380000)
lignes = {x["cle"]: x for x in t["lignes"]}
check("aucune ligne de la page pour une page de base",
      not [k for k in lignes if "template" in k.lower()], sorted(lignes))
check("les pages de base sont nommees sous la page (t['gabarits'])",
      t["gabarits"] == ["TEMPLATE ibenhaastrup", "TEMPLATE julia"], t["gabarits"])
check("EUD : trois liens GMS, UN lien de suivi (c117), ses 7 subs une fois",
      lignes["EUD"]["nb_gms"] == 3 and [r["code"] for r in lignes["EUD"]["infloww"]] == ["117"]
      and lignes["EUD"]["subs"] == 7, lignes["EUD"])
check("une page d'identite (landing, sans adresse) n'est pas « sans lien de suivi »",
      t["introuvables"] == 0 and not lignes["EUD"]["introuvables"],
      [(k, x["introuvables"]) for k, x in lignes.items() if x["introuvables"]])
t46 = il.construire(INF, REELS_L, lu_a=1790380000)
check("totaux identiques a ceux des 46 liens seuls (subs, liens de suivi, personnes)",
      (t["totaux"]["subs"], t["totaux"]["liens_infloww"], t["totaux"]["personnes"])
      == (t46["totaux"]["subs"], t46["totaux"]["liens_infloww"], t46["totaux"]["personnes"]),
      (t["totaux"], t46["totaux"]))
check("subs : codes Infloww DISTINCTS (BO7 : deux liens GMS sur c85, 3 subs)",
      lignes["BO7"]["subs"] == 3 and len(lignes["BO7"]["infloww"]) == 1)
check("aucun code partage cree par une page d'identite",
      [p for p in t["partages"] if p["code"] == "117"] == [])
check("le compte des pages d'identite est dit (t['identites'] = 4)", t["identites"] == 4)
txt = json.dumps(il.messages_discord(t), ensure_ascii=False)
check("message Discord des VA : pas d'alerte « sans lien Infloww en face », pas de TEMPLATE",
      "sans lien Infloww" not in txt and "TEMPLATE" not in txt)
REG["ratt"] = {}
t0 = il.construire(INF, LIENS, lu_a=1790380000)
check("(sans registre, les 4 pages sortaient « sans lien de suivi » : ce que le rattachement evite)",
      t0["introuvables"] == 4, t0["introuvables"])
REG["ratt"] = dict(RATT)
REG["panne"] = RuntimeError("registre corrompu")
tp = il.construire(INF, LIENS, lu_a=1790380000)
html_p = il.page_html(tp)
check("registre en panne : dit sur la page, pas avale",
      "corrompu" in tp["identites_panne"] and "Registre des pages d" in html_p, tp["identites_panne"])
REG["panne"] = None
html_t = il.page_html(t)
check("page : les gabarits et les pages d'identite sont nommes dans les notes",
      "TEMPLATE ibenhaastrup" in html_t and "identité US comptées chez la personne" in html_t
      and "<td>TEMPLATE" not in html_t)

# clics US depuis toujours : un appel par personne, pages comprises
GMS["lots"].clear()
ents_il, _ = il.entites(LIENS)
r = il.releve_us(ents_il, forcer=True)
lot_eud = [ids for ids, d0, _d1 in GMS["lots"] if EUD in ids]
check("clics US depuis toujours : EUD en UN appel, ses deux pages comprises",
      lot_eud == [tuple(sorted([EUD, I1["id"], I2["id"]]))], lot_eud)
us = json.loads(il.US_FICHIER.read_text(encoding="utf-8"))["personnes"]
check("clics US depuis toujours : EUD = 10 + 5 + 2", us["EUD"]["us"] == 17, us.get("EUD"))
check("clics US : aucun appel pour une page de base",
      not [ids for ids, *_r in GMS["lots"] if BASE_IBEN["id"] in ids or BASE_JULIA["id"] in ids])


# ═════════════════════════════════════════════════════════════════════════
print("4) Paie : lignes actives")
T1, T2, T3 = ("2026-09-01", "2026-09-15"), ("2026-09-16", "2026-09-30"), ("2026-10-01", "2026-10-06")


def _regler(**pers):
    il.PAIE_FICHIER.write_text(json.dumps({"personnes": pers}), encoding="utf-8")


def _fixe(depuis="2026-09-01", **kw):
    return dict({"type": "fixe", "montant": 75, "devise": "USD", "frequence": "quinzaine",
                 "depuis": depuis}, **kw)


def _paie(liens=None):
    tt = il.construire(INF, LIENS if liens is None else liens, lu_a=1790380000)
    return tt, il.avec_paie(tt, attente=0)


def _x(tp_, cle="EUD"):
    return [x for x in tp_["lignes"] if x["cle"] == cle][0]["paie"]


def _appels(*ids):
    return [a for a in GMS["appels"] if a[0] in ids or (a[0] == "verif" and set(a[1]) & set(ids))]


def _raz_lignes():
    for f in (il.LIGNES_FICHIER, il.LIGNES_FICHIER.with_suffix(".json.prev")):
        f.unlink(missing_ok=True)
    GMS["appels"].clear()


_regler(EUD=_fixe())
il.LIGNES_APPELS_JOUR = 120

# 4a. le global a des clics partout : une ligne, et ses pages jamais relevees
_raz_lignes()
GMS["clics"] = {EUD: 4, I1["id"]: 9, I2["id"]: 9}
_tt, P = _paie()
p = _x(P)
check("EUD : une seule ligne (son global), ses pages n'en sont pas",
      [l["id"] for l in p["liens_gms"]] == [EUD]
      and sorted(p["pages_identite"]) == ["(EUD) ibenhaastrup", "(EUD) julia"], p.get("liens_gms"))
check("global actif sur les trois tranches : 1 ligne chacune",
      [f["lignes"] for f in p["detail_f"]] == [1, 1, 1] and [f["total"] for f in p["detail_f"]] == [1, 1, 1],
      [(f["du"], f["lignes"], f["total"]) for f in p["detail_f"]])
check("global actif : aucune page d'identite relevee (le quota ne paie pas pour rien)",
      _appels(I1["id"], I2["id"]) == [], _appels(I1["id"], I2["id"]))
check("fixe : 3 tranches x 1 ligne (75 $, la derniere au prorata)",
      p["fixe"] == round(75 + 75 + 75 * 6 / 15, 2), p.get("fixe"))

# 4b. le global a zero sur la 2e quinzaine, sa page ibenhaastrup y a cliqué
_raz_lignes()
GMS["clics"] = {EUD: {T1: 3, T2: 0, T3: 0}, I1["id"]: {T2: 6, T3: 0}, I2["id"]: {T3: 0}}
_tt, P = _paie()
premier = list(GMS["appels"])
check("1er passage : le global d'abord, aucune page relevee avant son zero",
      _appels(I1["id"], I2["id"]) == [] and {a[0] for a in premier if a[0] != "verif"} == {EUD}, premier)
_tt, P = _paie()
p = _x(P)
ap_i1 = [(a[1], a[2]) for a in _appels(I1["id"]) if a[0] == I1["id"]]
ap_i2 = [(a[1], a[2]) for a in _appels(I2["id"]) if a[0] == I2["id"]]
check("2e passage : la page relevee seulement la ou le global a un zero confirme, apres sa creation",
      sorted(ap_i1) == [T2, T3] and ap_i2 == [T3], (ap_i1, ap_i2))
check("la ligne d'EUD est ACTIVE sur la 2e quinzaine grace a sa page, toujours UNE ligne",
      [f["lignes"] for f in p["detail_f"]] == [1, 1, 0] and p["detail_f"][1]["total"] == 1,
      [(f["du"], f["lignes"], f["total"], f["inconnus"]) for f in p["detail_f"]])
check("le detail dit que la ligne est active par sa page",
      p["detail_f"][1]["par_pages"] == ["EUD ((EUD) ibenhaastrup)"], p["detail_f"][1].get("par_pages"))
etapes = il.etapes_calcul(p)
check("le detail du gain l'ecrit (« Active par ses pages d'identité »)",
      any("Active par ses pages" in n for n in etapes["notes"]), etapes["notes"])
lg = json.loads(il.LIGNES_FICHIER.read_text(encoding="utf-8"))
rel_t2 = lg["tranches"]["%s|%s" % T2]["liens"]
check("« qui » : le releve du global note EUD, celui de la page ne note personne",
      rel_t2[EUD].get("qui") == "EUD" and not rel_t2[I1["id"]].get("qui"),
      (rel_t2[EUD], rel_t2[I1["id"]]))
fige = lg["tranches"]["%s|%s" % T2].get("fige") or {}
check("tranche close entierement tranchee : figee, la ligne active avec sa page gardee a cote",
      fige.get("EUD", {}).get("liens", {}).get(EUD) == {"nom": "EUD", "actif": True, "pages": [I1["id"]]},
      fige)
check("la quinzaine en cours n'est pas figee",
      not (lg["tranches"].get("%s|%s" % T3) or {}).get("fige"))
html_paie = il.page_html(P)
check("page du proprietaire rendue, gain d'EUD calcule (3 lignes payees en tout)",
      p.get("gain") is not None and "EUD" in html_paie and p["fixe"] == 150.0, (p.get("gain"), p.get("fixe")))

# 4c. une tranche FIGEE ne se recalcule pas
GMS["appels"].clear()
GMS["clics"] = {EUD: 50, I1["id"]: 50, I2["id"]: 50}
_tt, P = _paie()
p = _x(P)
check("tranches figees relues telles quelles : aucun appel sur les quinzaines closes",
      not [a for a in GMS["appels"] if a[0] != "verif" and (a[1], a[2]) in (T1, T2)]
      and [f["fige"] for f in p["detail_f"]] == [True, True, False], GMS["appels"])

# 4d. une quinzaine figee AVANT les pages (inactive) reste inactive
_raz_lignes()
il.LIGNES_FICHIER.write_text(json.dumps({"tranches": {"%s|%s" % T2: {"liens": {}, "vu": 1.0, "fige": {
    "EUD": {"quand": 1.0, "liens": {EUD: {"nom": "EUD", "actif": False}}}}}}}), encoding="utf-8")
GMS["clics"] = {EUD: {T1: 1, T2: 0, T3: 1}, I1["id"]: {T2: 8}}
_tt, P = _paie()
_tt, P = _paie()
p = _x(P)
check("quinzaine deja figee : 0 ligne, sa page n'est pas relevee, rien n'est refait",
      p["detail_f"][1]["lignes"] == 0 and p["detail_f"][1]["fige"]
      and not [a for a in GMS["appels"] if (a[1:3] if a[0] != "verif" else a[2:4]) == T2],
      (p["detail_f"][1], GMS["appels"]))

# 4e. budget du jour
_raz_lignes()
il.LIGNES_APPELS_JOUR = 2
GMS["clics"] = {EUD: 0, I1["id"]: 3, I2["id"]: 0}
for _i in range(4):
    _tt, P = _paie()
p = _x(P)
check("budget LIGNES_APPELS_JOUR respecte, verifications des zeros comprises",
      len(GMS["appels"]) == 2, GMS["appels"])
check("budget atteint : les lignes attendent (« — »), aucun nombre de telephones invente",
      p.get("fixe") is None and (P["paie"].get("lignes") or {}).get("info", {}).get("budget") == 2,
      (p.get("fixe"), P["paie"].get("lignes")))
il.LIGNES_APPELS_JOUR = 120

# 4f. un releve de page note a la personne (panne du registre) ne devient pas une ligne
_raz_lignes()
# horodate maintenant : un morceau de quinzaine (01 -> 06/10) plus servi
# depuis 45 jours est elague a la premiere ecriture (_elaguer_lignes)
il.LIGNES_FICHIER.write_text(json.dumps({"tranches": {"%s|%s" % T3: {"liens": {
    I2["id"]: {"clics": 4, "quand": time.time(), "jour": JOUR["j"], "qui": "EUD", "nom": "(EUD) julia"}},
    "vu": time.time()}}}), encoding="utf-8")
GMS["clics"] = {EUD: {T1: 1, T2: 1, T3: 0}}
_tt, P = _paie()
_tt, P = _paie()
p = _x(P)
check("page relevee a son nom pendant une panne : pas une ligne (« partis » vide), elle active le global",
      p["detail_f"][2]["total"] == 1 and p["detail_f"][2]["lignes"] == 1 and not p["detail_f"][2]["partis"],
      p["detail_f"][2])

# 4g. une page dont le global n'est plus a la personne : dite, pas comptee
_raz_lignes()
orpheline = _landing(_oid("2026-09-20", "a5"), "eudzoe", "(EUD) zoe")
REG["ratt"] = dict(RATT, **{orpheline["id"]: "lnk_6a0000000000000000000000"})
GMS["clics"] = {EUD: 1, orpheline["id"]: 5}
_tt, P = _paie(LIENS + [orpheline])
_tt, P = _paie(LIENS + [orpheline])
p = _x(P)
check("page sans son global : ni ligne ni appel, et dite sous le gain",
      [l["id"] for l in p["liens_gms"]] == [EUD] and p["pages_sans_global"] == ["(EUD) zoe"]
      and not _appels(orpheline["id"])
      and any("sans leur lien global" in n for n in il.etapes_calcul(p)["notes"]),
      (p["liens_gms"], p.get("pages_sans_global")))
REG["ratt"] = dict(RATT)

# 4g bis. registre des pages illisible : rien n'est fige
_raz_lignes()
GMS["clics"] = {EUD: {T1: 3, T2: 0, T3: 0}, I1["id"]: {T2: 6, T3: 0}, I2["id"]: {T3: 0}}
REG["panne"] = RuntimeError("registre corrompu")
for _i in range(3):
    _tt, P = _paie()
lg = json.loads(il.LIGNES_FICHIER.read_text(encoding="utf-8")) if il.LIGNES_FICHIER.exists() else {}
check("registre en panne : aucune tranche close figee (les pages y seraient des lignes pour toujours)",
      not [k for k, v in (lg.get("tranches") or {}).items() if (v or {}).get("fige")],
      {k: list((v or {}).get("fige") or {}) for k, v in (lg.get("tranches") or {}).items()})
REG["panne"] = None
_tt, P = _paie()
_tt, P = _paie()
lg = json.loads(il.LIGNES_FICHIER.read_text(encoding="utf-8"))
fige = (lg["tranches"].get("%s|%s" % T2) or {}).get("fige") or {}
check("registre revenu : la tranche close se fige, page comptee avec sa ligne (une ligne)",
      list((fige.get("EUD") or {}).get("liens") or {}) == [EUD], fige)

# 4h. les autres personnes payees ne changent pas
_raz_lignes()
_regler(EUD=_fixe(), BO7=_fixe())
GMS["clics"] = {ID["( BO7 ) 1"]: 1, ID["( BO7 ) 2"]: 0, EUD: 1}
_tt, P = _paie()
_tt, P = _paie()
p_bo7 = _x(P, "BO7")
check("BO7 (deux liens directs) : deux lignes, une active, comme avant",
      [f["total"] for f in p_bo7["detail_f"]] == [2, 2, 2] and [f["lignes"] for f in p_bo7["detail_f"]] == [1, 1, 1],
      [(f["du"], f["lignes"], f["total"]) for f in p_bo7["detail_f"]])


# ═════════════════════════════════════════════════════════════════════════
print("5) Clics (classement par personne)")
ENT = [{"nom": l["display_name"], "clics": 1, "abonnes": None, "depuis": "", "id": l["id"]} for l in LIENS]
gens = {g["pseudo"]: g for g in cp.grouper(ENT)}
check("aucune page de base dans le classement", not [k for k in gens if "template" in k], sorted(gens))
check("EUD : trois liens, une personne, 3 clics", gens["eud"]["clics"] == 3 and len(gens["eud"]["liens"]) == 3)
check("la page de « tsiry 1 » rejoint tsiry (et pas une personne « tsiry 1 »)",
      "(tsiry 1) ibenhaastrup" in gens["tsiry"]["liens"] and "tsiry 1" not in gens, sorted(gens))
check("la page de « LaBoule ( Phone ) » rejoint LaBoule (et pas une personne « phone »)",
      "(Phone) ibenhaastrup" in gens["laboule"]["liens"] and "phone" not in gens)
SANS_ID = [{k: v for k, v in e.items() if k != "id"} for e in ENT]
if OLD_CP:
    def _resume(gs):
        return sorted((g["pseudo"], g["titre"], tuple(g["liens"]), g["clics"]) for g in gs)
    check("sans identifiant, le classement est exactement celui d'avant (git %s)" % REF,
          _resume(cp.grouper(SANS_ID)) == _resume(OLD_CP.grouper(SANS_ID)))
    check("les 46 liens avec identifiant : exactement le classement d'avant",
          _resume(cp.grouper(ENT[:46])) == _resume(OLD_CP.grouper(SANS_ID[:46])))
    check("(le code d'avant faisait de la page de tsiry 1 une personne « tsiry 1 »)",
          "tsiry 1" in {g["pseudo"] for g in OLD_CP.grouper(SANS_ID)})
rep = {"par_lien": [{"lien": e["nom"], "id": e["id"], "depuis": "",
                     "periodes": [{}, {}, {"marche": 1, "total": 2}]} for e in ENT],
       "abonnes": []}
gens_r = {g["pseudo"]: g for g in cp.grouper(cp.depuis_report(rep, "quinz"))}
check("report Discord : l'identifiant voyage du report au classement (depuis_report)",
      "(tsiry 1) ibenhaastrup" in gens_r["tsiry"]["liens"] and len(gens_r["eud"]["liens"]) == 3)
_src_cr = pathlib.Path("cogs/clickrecap.py").read_text(encoding="utf-8")
check("report Discord : le cog met l'identifiant sur chaque ligne du tableau",
      '"id": _id_de(p)' in _src_cr)
check("report Discord : JESSY LE RETOUR ecarte ses gabarits avant tout releve, regle etroite",
      "_cp_g.commence_par_gabarit(_nm)" in _src_cr and "_cp_g.ESPACE_RANKING" in _src_cr
      and _src_cr.index("_gabarits_ecartes = []") < _src_cr.index('ids = [m["id"] for m in metas'))
try:
    import clics_image as _ci
    _d_ci = {"par_lien": [r_ for r_ in rep["par_lien"] if "TEMPLATE" not in r_["lien"]], "abonnes": [],
             "gabarits_ecartes": ["TEMPLATE ibenhaastrup", "TEMPLATE julia"]}
    check("image du report : les gabarits ecartes avant releve restent nommes dans le pied",
          _ci._gabarits(_d_ci) == ["TEMPLATE ibenhaastrup", "TEMPLATE julia"], _ci._gabarits(_d_ci))
except ImportError as e:
    print(f"  (clics_image non importable ici : {e})")

# Le report de JESSY LE RETOUR en vrai (faux GetMySocial, faux MyPuls) : 46
# liens, 2 pages de base et 18 pages d'identite -- 66 liens, au-dela des 60
# du detail par lien si chaque page avait sa ligne.
import asyncio as _aio
import cogs.clickrecap as _cr
import clics_arrivees as _ca
PAGES_R = [_landing(_oid("2026-10-02", "r%02d" % i), "pg%02d" % i, "(EUD) id%02d" % i) for i in range(16)]
METAS = ([dict(l, destination=l["url"]) for l in REELS_L] + [BASE_IBEN, BASE_JULIA, I1, I2]
         + PAGES_R)
REG["ratt"] = dict(RATT, **{pg["id"]: EUD for pg in PAGES_R})
_PAGES_EUD = [I1["id"], I2["id"]] + [pg["id"] for pg in PAGES_R]
faux_gms.report_links_meta = lambda *a: [dict(m) for m in METAS]
faux_gms.clicks_for_ids = lambda ids, a, b: 100
faux_gms.sante_cles = lambda: []
_fm = types.ModuleType("mypuls")
_fm.api_tracking_links = lambda _f, d, f: []
_sauve_mp = sys.modules.get("mypuls")
sys.modules["mypuls"] = _fm
_sauve_cr = (_cr._PREC_FILE, _cr._paris_now, _ca.toutes, _ca.enregistrer_liens)
_cr._PREC_FILE = TMP / "prec.json"
_cr._paris_now = lambda: dt.datetime(2026, 10, 6, 14, 30)
_ca.toutes = lambda: {}
_ca.enregistrer_liens = lambda *a, **k: None
GMS["appels"].clear()
GMS["lots"].clear()
GMS["clics"] = {}
GMS["us"] = {EUD: 10, I1["id"]: 5, I2["id"]: 2}
_prep = {}
_tok = _cr._PREP_IMAGE.set(_prep)
try:
    _emb = _aio.run(_cr.ClickRecap._build_group_report(
        types.SimpleNamespace(), {"channel_id": 1, "team_id": JESSY, "group_name": "J", "marche": "us",
                                  "tout": True}, sortie={}))
finally:
    _cr._PREP_IMAGE.reset(_tok)
    _cr._PREC_FILE, _cr._paris_now, _ca.toutes, _ca.enregistrer_liens = _sauve_cr
    if _sauve_mp is None:
        sys.modules.pop("mypuls", None)
    else:
        sys.modules["mypuls"] = _sauve_mp
_don = (_prep.get("donnees") or {})
_pl = _don.get("par_lien") or []
_champs = " ".join(f"{f.name} {f.value}" for f in getattr(_emb, "fields", []))
check("report JESSY, 66 liens dont 18 pages : le detail par lien reste (46 lignes, pas « too many »)",
      len(_pl) == 46 and "too many" not in _champs and {r_["id"] for r_ in _pl} == {i for i, *_x in REELS},
      (len(_pl), _champs[:200]))
_l_eud = [r_ for r_ in _pl if r_["id"] == EUD]
check("la ligne d'EUD porte ses 18 pages, nommees",
      len(_l_eud) == 1 and len(_l_eud[0].get("pages") or []) == 18
      and "(EUD) ibenhaastrup" in _l_eud[0]["pages"] and _don.get("pages_identite") == 18, _l_eud)
_seuls = {a_[0] for a_ in GMS["appels"] if a_[0] != "verif"}
check("aucun releve a part pour une page d'identite ni une page de base",
      not (_seuls & set(_PAGES_EUD + [BASE_IBEN["id"], BASE_JULIA["id"]])), sorted(_seuls & set(_PAGES_EUD)))
_lots_eud = [ids for ids, _d0, _d1 in GMS["lots"] if EUD in ids]
check("EUD releve AVEC ses pages, un appel par periode (3, plus la quinzaine precedente)",
      len([x for x in _lots_eud if x == tuple(sorted([EUD] + _PAGES_EUD))]) == 4,
      [len(x) for x in _lots_eud])
check("le chiffre d'EUD compte ses pages (10 + 5 + 2 US)",
      _l_eud and _l_eud[0]["periodes"][0] == {"marche": 17, "total": 18}, _l_eud and _l_eud[0]["periodes"])
_g_eud = {g["pseudo"]: g for g in cp.grouper(cp.depuis_report(_don, "quinz"))}.get("eud") or {}
check("classement des clics : EUD une seule personne, une seule ligne de lien",
      _g_eud.get("liens") == ["EUD"], _g_eud.get("liens"))
REG["ratt"] = dict(RATT)
GMS["us"] = {}

REG["ratt"] = {"a": "a", "b": "", "": "c", "d": "e"}
check("registre : un lien rattache a lui-meme ou a rien est ignore",
      cp.rattachements_identite() == {"d": "e"}, cp.rattachements_identite())
REG["ratt"] = dict(RATT)
REG["panne"] = OSError("disque")
check("registre en panne : vide, et la panne est rendue",
      cp.rattachements_identite_ou_panne()[0] == {} and "disque" in cp.rattachements_identite_ou_panne()[1])
REG["panne"] = None
sys.modules.pop("liens_identite_us")
_sauve_path = list(sys.path)
sys.path[:] = [p_ for p_ in sys.path if pathlib.Path(p_ or ".").resolve() != ICI]
_absent = not (ICI / "liens_identite_us.py").exists()
if _absent:
    check("module absent : aucun rattachement, pas de panne",
          cp.rattachements_identite_ou_panne() == ({}, ""))
sys.path[:] = _sauve_path
sys.modules["liens_identite_us"] = faux_liu


# ═════════════════════════════════════════════════════════════════════════
print("6) Le contrat avec liens_identite_us")
_vrai = ICI / "liens_identite_us.py"
if not _vrai.exists():
    print("  (liens_identite_us.py pas encore ecrit : section sautee)")
else:
    try:
        spec = importlib.util.spec_from_file_location("liens_identite_us_reel", _vrai)
        liu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(liu)
    except Exception as e:                                   # noqa: BLE001
        liu = None
        check("liens_identite_us.py s'importe", False, f"{type(e).__name__}: {e}")
    if liu is not None:
        bases = ("TEMPLATE ibenhaastrup", "template ibenhaastrup", " TEMPLATE  julia ")
        if hasattr(liu, "est_base"):
            check("est_base -> est_gabarit (une seule regle)",
                  all(liu.est_base(n) and cp.est_gabarit(n) for n in bases)
                  and not any(liu.est_base(n) for _i, _s, n, _c in REELS))
        if hasattr(liu, "identite_de_base"):
            check("identite_de_base(« TEMPLATE ibenhaastrup ») == « ibenhaastrup »",
                  liu.identite_de_base("TEMPLATE ibenhaastrup") == "ibenhaastrup"
                  and liu.identite_de_base("EUD") is None)
        if hasattr(liu, "nom_lien"):
            ecarts_pd, ecarts_cp = [], []
            for lid, sc, nom, code in REELS:
                pers, spam = pd.personne(nom)
                g = {"link_id": lid, "shortcode": sc, "nom": nom, "personne": pers, "spam": spam,
                     "url": OF % code}
                try:
                    n2 = liu.nom_lien(g, "ibenhaastrup")
                except Exception as e:                       # noqa: BLE001
                    ecarts_pd.append((nom, f"{type(e).__name__}: {e}"))
                    continue
                if pd.cle_entite(*pd.personne(n2)) != pd.cle_entite(pers, spam) or cp.est_gabarit(n2):
                    ecarts_pd.append((nom, n2))
                if cp.pseudo(n2) != cp.pseudo(nom):
                    ecarts_cp.append((nom, n2))
            check("nom_lien : sur les 46 vrais globaux, la page a la cle de podium de son global",
                  not ecarts_pd, ecarts_pd)
            print(f"  info : regle de nom des clics differente sur {len(ecarts_cp)} global(aux) "
                  f"(rattrape par l'identifiant, section 5) : {[n for n, _ in ecarts_cp]}")


# ─── fin ─────────────────────────────────────────────────────────────────
if _GMS_AVANT is not None:
    sys.modules["gms"] = _GMS_AVANT
if _LIU_AVANT is not None:
    sys.modules["liens_identite_us"] = _LIU_AVANT
print(f"\n{NB['ok']} ok, {NB['ko']} KO")
sys.exit(1 if NB["ko"] else 0)
