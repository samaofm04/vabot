"""Le tableau staff (tableau_staff.py) : l'état de chaque VA, pour les managers.

Propriétaire, 13/10/2026 : « montre-moi le tableau pour le staff », « fais ça
aussi pour les autres groupes, IG, Twitter » ; Twitter « par numéro de VA »,
Va IG « par model, tous ses liens ».

Vérifié ici, sans réseau ni vrai data/ (Discord et GetMySocial sont faux ;
DATA_DIR est un dossier temporaire) :
  1. Threads : un VA par ticket, son lien Threads, ses visites, sa pastille
     (🟢 🟠 🔵 🔴), son manager, son salon ;
  2. Twitter : une ligne par numéro du registre (pages JESSY), sans ticket ;
     un VA sans lien en service n'y est pas ;
  3. Va IG : une section par model, chaque VA avec son lien de CETTE model ;
     un VA de deux models paraît dans les deux ; les comptes sans limite non ;
  4. la publication : salon créé fermé (staff et bot seulement), message
     réédité sur place, pages, GetMySocial muet = rien de touché ;
  5. la boucle du site l'appelle pour chaque serveur, avec son bot.

Lancer depuis la racine du dépôt : python tests_tableau_staff.py
"""
from __future__ import annotations

import ast
import copy
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# ------------------------------------------------------- faux GetMySocial --
GMS = {"visites": {}, "panne": False, "appels": []}


def _call_tool(outil, args):
    GMS["appels"].append((outil, dict(args)))
    if outil != "get_link_metrics":
        return {"ok": True, "data": {}}
    if GMS["panne"]:
        return {"ok": False, "error": "503"}
    v = GMS["visites"].get(args["team_id"], {})
    return {"ok": True, "data": {"object": "list", "has_more": False,
                                 "data": [{"key": k, "pageviews": n} for k, n in v.items()]}}


_faux_gms = types.ModuleType("gms")
_faux_gms._call_tool = _call_tool
_faux_gms.api_tag = None
sys.modules["gms"] = _faux_gms

import safe_json                       # noqa: E402
import tableau_staff as ts             # noqa: E402
import tickets_discord as tk           # noqa: E402
import liens_va as lv                  # noqa: E402
import liens_fr                        # noqa: E402
import podium_discord as pd            # noqa: E402
import clics_personnes as cp           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH, IG = ts.TWITTER_ID, ts.THREADS_ID, ts.VA_IG_ID
A = tk.AROBASE
EMY_THREADS, JESSY, EMY_TW = "tm_6ab51e03b299b7e3ba6ff7bf", ts.EQUIPES_TWITTER[0], ts.EQUIPES_TWITTER[1]
VIEUX = time.time() - 5 * 86400

SALONS = {
    TH: [{"id": "k1", "type": 4, "name": "🔵┤ Manager ABDOUL ├🔵"},
         {"id": "s1", "type": 0, "parent_id": "k1", "name": f"─│🟢┤-61-va-{A}momobtn"},
         {"id": "s2", "type": 0, "parent_id": "k1", "name": f"─│🟠┤-62-va-{A}steave0454"},
         {"id": "s3", "type": 0, "parent_id": "k1", "name": f"─│🔵┤-63-va-{A}absent"},
         {"id": "s4", "type": 0, "parent_id": "k1", "name": f"─│🔵┤-va-{A}neuf"},
         {"id": "s5", "type": 0, "parent_id": "k1", "name": f"─│🟠┤-64-va-{A}coupe"}],
    TW: [{"id": "t1", "type": 0, "name": "général"}],
    IG: [{"id": "c_am", "type": 4, "name": "Amelia"}, {"id": "c_em", "type": 4, "name": "Emma"},
         {"id": "g1", "type": 0, "parent_id": "c_am", "name": "🟢🔗-3-va-paul"},
         {"id": "g2", "type": 0, "parent_id": "c_em", "name": "🔴-7-va-marc"},
         {"id": "g9", "type": 0, "parent_id": "c_am", "name": "🟢-va-mario"},
         {"id": "g3", "type": 0, "parent_id": "c_em", "name": "🟠-2-va-lea"}],
}


class FauxDiscord:
    def __init__(self):
        self.appels, self.n, self.messages = [], 0, {}
        self.panne = 0                     # un code HTTP : Discord en panne

    def __call__(self, m, chemin, **kw):
        self.appels.append((m, chemin, copy.deepcopy(kw.get("json"))))
        b = chemin.strip("/").split("/")
        if chemin == "/users/@me":
            return 200, {"id": "bot1"}
        if b[0] == "guilds" and b[2:] == ["channels"]:
            if m == "GET":
                return 200, copy.deepcopy(SALONS.get(b[1], []))
            self.n += 1
            c = dict(kw["json"], id=f"neuf{self.n}")
            SALONS[b[1]].append(c)
            return 201, {"id": c["id"]}
        if b[0] == "channels" and b[2:] == ["messages"] and m == "POST":
            if self.panne:
                return self.panne, {}
            self.n += 1
            self.messages[str(1000 + self.n)] = kw["json"]
            return 200, {"id": str(1000 + self.n)}
        if b[0] == "channels" and len(b) == 4 and m == "PATCH":
            if self.panne:
                return self.panne, {}
            if b[3] not in self.messages:
                return 404, {}
            self.messages[b[3]] = kw["json"]
            return 200, {"id": b[3]}
        return 404, {}

    def ecritures(self, k=0):
        return [a for a in self.appels[k:] if a[0] != "GET"]


TMP = pathlib.Path(tempfile.mkdtemp(prefix="tableau_staff_"))
_SAUVE = {
    "ts": {k: getattr(ts, k) for k in ("DATA_DIR", "_api")},
    "tk": {k: getattr(tk, k) for k in ("ETAT_FICHIER", "role_helper")},
    "lv": {k: getattr(lv, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER")},
    "lf": {k: getattr(liens_fr, k) for k in ("ETAT",)},
    "pd": {k: getattr(pd, k) for k in ("DATA_DIR", "NUMEROS_FICHIER", "liens_bruts")},
    "cp": {"rattachements_identite": cp.rattachements_identite},
}
D = FauxDiscord()


def installer():
    global D
    D = FauxDiscord()
    for f in TMP.glob("*.json"):
        f.unlink()
    ts.DATA_DIR = TMP
    ts._api = D
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.role_helper = lambda gid: "role_helper"
    tk._ACTIVITE.clear()
    tk._ACTIVITE_LUE[0] = False
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    liens_fr.ETAT = TMP / "liens_va_fr.json"
    pd.DATA_DIR = TMP
    pd.NUMEROS_FICHIER = TMP / "podium_numeros.json"
    GMS["panne"] = False
    GMS["appels"].clear()
    # Threads
    safe_json.write(tk.ETAT_FICHIER, {"tickets": {
        f"{TH}:u1": {"salon": "s1", "ouvert": VIEUX}, f"{TH}:u2": {"salon": "s2", "ouvert": VIEUX},
        f"{TH}:u3": {"salon": "s3", "ouvert": VIEUX},
        f"{TH}:u4": {"salon": "s4", "ouvert": time.time() - 3600},
        f"{TH}:u5": {"salon": "s5", "ouvert": VIEUX},
        f"{TW}:x": {"salon": "t9"}}})
    safe_json.write(lv.ETAT_FICHIER, {"liens": {
        f"{TH}:u1": {"link_id": "lnk_a", "shortcode": "velvetyy", "numero": 61, "quand": VIEUX},
        f"{TH}:u2": {"link_id": "lnk_b", "shortcode": "cutieyy", "numero": 62, "quand": VIEUX},
        f"{TH}:u5": {"link_id": "lnk_c", "shortcode": "oldyy", "numero": 64, "quand": VIEUX,
                     "actif": False}}})
    # Twitter : le registre des trackings et deux pages
    safe_json.write(TMP / "podium_trackings.json", {"trackings": {
        "emy.brw/c42": {"numero": 12, "spam": False, "premier": "2026-10-06", "vu": "2026-10-13",
                        "actif": True, "ids": []},
        "emy.brw/c37": {"numero": 43, "spam": False, "premier": "2026-10-06", "vu": "2026-10-13",
                        "actif": True, "ids": []}}, "attente": {}})
    safe_json.write_text(pd.NUMEROS_FICHIER, json.dumps({}))
    of = "https://onlyfans.com/"
    pd.liens_bruts = lambda gid=None, etiquette="podium": ([
        {"id": "p1", "display_name": "VA 3 - Roucham 1 ( normal )", "shortcode": "knstjessye",
         "status": "active", "buttons": [{"url": of + "emy.brw/c42"}]},
        {"id": "p2", "display_name": "tsiry 1", "shortcode": "lovejessye", "status": "active",
         "buttons": [{"url": of + "emy.brw/c37"}]},
        {"id": "p3", "display_name": "ancien", "shortcode": "vieux", "status": "inactive",
         "buttons": [{"url": of + "emy.brw/c99"}]},
        # un tracking neuf, pas encore dans le registre : pas de numéro
        {"id": "p4", "display_name": "eddy 1", "shortcode": "eddyjessye", "status": "active",
         "buttons": [{"url": of + "emy.brw/c77"}]},
        # l'ancienne page du VA 12, coupée hier, et ses visites de la veille
        {"id": "p5", "display_name": "VA 3 - Roucham 2 ( normal )", "shortcode": "ancienne",
         "status": "inactive", "buttons": [{"url": of + "emy.brw/c42"}]}], True)
    cp.rattachements_identite = lambda: {}
    # Va IG
    safe_json.write(liens_fr.ETAT, {"liens": {
        "100:amelia": {"pseudo": "paul", "numero": 3, "link_id": "lnk_x", "shortcode": "amelialovee"},
        "100:lola": {"pseudo": "paul", "numero": 5, "link_id": "lnk_y", "shortcode": "lolababy"},
        # rôle Emma retiré : lien coupé par liens_fr.aligner, pas supprimé
        "100:emma": {"pseudo": "paul", "numero": 4, "link_id": "lnk_z", "shortcode": "emmacut",
                     "actif": False},
        "400:emma": {"pseudo": "lea", "numero": 2, "link_id": "lnk_w", "shortcode": "emmaold",
                     "actif": False},
        "402069419393679370:amelia": {"pseudo": "seven", "numero": 9, "link_id": "lnk_s",
                                      "shortcode": "test"}}})
    safe_json.write(TMP / "users.json", {"100": {"channel_id": "g1"}, "200": {"channel_id": "g2"},
                                         "402069419393679370": {"channel_id": "g9"},
                                         "400": {"channel_id": "g3"},
                                         "300": {"channel_id": "ailleurs"}})
    safe_json.write(TMP / "numeros_va_fr.json", {"emma": {"200": 7}})
    safe_json.write(TMP / "va_activity.json", {"200": {"_last": "2026-10-01T10:00:00"}})
    GMS["visites"] = {EMY_THREADS: {"lnk_a": 5, "lnk_b": 0, "lnk_c": 6},
                      JESSY: {"p1": 7, "p2": 0, "p3": 0, "p4": 3, "p5": 40},
                      EMY_TW: {}, liens_fr.EQUIPE: {"lnk_x": 9, "lnk_y": 0, "lnk_s": 50,
                                                    "lnk_z": 4, "lnk_w": 2}}


try:
    # ------------------------------------------------------------------ 1
    print("\n— 1. Threads")
    installer()
    l_th = ts._lignes_threads(SALONS[TH])
    par = {x["texte"].split(" · ")[1]: x for x in l_th}
    check("un VA par ticket du serveur (pas ceux de Twitter)",
          sorted(par) == ["absent", "coupe", "momobtn", "neuf", "steave0454"], sorted(par))
    check("🟢 lien avec visites, 🟠 lien sans visite, 🔴 sans lien et rien depuis 2 j, 🔵 neuf",
          [par[k]["rond"] for k in ("momobtn", "steave0454", "absent", "neuf")]
          == ["🟢", "🟠", "🔴", "🔵"], {k: v["rond"] for k, v in par.items()})
    check("la ligne : numéro, pseudo, lien, visites, manager, salon",
          par["momobtn"]["texte"] == "`VA 61` · momobtn · `velvetyy` · **5** visites · ABDOUL · <#s1>",
          par["momobtn"]["texte"])
    check("un lien coupé : 🟠 comme son salon, « lien coupé », ses visites d'avant ne comptent pas",
          par["coupe"]["rond"] == "🟠" and par["coupe"]["visites"] == 0
          and "`oldyy` · lien coupé" in par["coupe"]["texte"]
          and "visite" not in par["coupe"]["texte"], par["coupe"])

    # ------------------------------------------------------------------ 2
    print("\n— 2. Twitter : par numéro de VA")
    l_tw = ts._lignes_twitter(SALONS[TW])
    txt = [x["texte"] for x in l_tw if x["rond"] != ts.SANS_NUMERO]
    check("une ligne par numéro du registre, ses pages et leurs visites, sans ticket",
          sorted(txt) == ["`VA 12` · `knstjessye` · **7** visites",
                          "`VA 43` · `lovejessye` · **0** visite"], txt)
    check("🟢 / 🟠 selon les visites ; un lien plus en service n'apparaît pas",
          {x["n"]: x["rond"] for x in l_tw if x["rond"] != ts.SANS_NUMERO} == {12: "🟢", 43: "🟠"}
          and "vieux" not in " ".join(txt))
    check("les visites d'une page coupée ne comptent pas (VA 12 : 7, pas 47)",
          [x["visites"] for x in l_tw if x["n"] == 12] == [7] and "ancienne" not in " ".join(txt))
    sn = [x for x in l_tw if x["rond"] == ts.SANS_NUMERO]
    check("un tracking neuf, sans numéro : pas sauté, dans la section ❔ avec sa page et ses visites",
          len(sn) == 1 and "`eddyjessye`" in sn[0]["texte"] and "**3** visites" in sn[0]["texte"], sn)
    pg_tw = ts.pages(TW, l_tw)[0]["description"]
    check("… la section porte son titre ; une section vide ne paraît pas",
          "❔ **Sans numéro de VA" in pg_tw and "🔴" not in pg_tw.split("👥")[0], pg_tw)
    _pt = pd._par_tracking
    try:
        pd._par_tracking = lambda *a, **k: (lambda r: (r[0], r[1], {43}, r[3]))(_pt(*a, **k))
        l_d = ts._lignes_twitter(SALONS[TW])
    finally:
        pd._par_tracking = _pt
    check("un numéro que le registre met en doute est signalé",
          any(x["n"] == 43 and "⚠️ numéro en doute" in x["texte"] for x in l_d)
          and not any(x["n"] == 12 and "doute" in x["texte"] for x in l_d))
    check("aucun numéro attribué (la table au nom des liens reste vide)",
          json.loads(pd.NUMEROS_FICHIER.read_text()) == {})

    # ------------------------------------------------------------------ 3
    print("\n— 3. Va IG : par model, tous ses liens")
    l_ig = ts._lignes_ig(SALONS[IG])
    vu = {(x["section"], x["texte"].split("`")[1]): x for x in l_ig}
    check("un VA de deux models paraît dans les deux, chaque fois avec le lien de CETTE model",
          ("Amelia", "Amelia VA 3") in vu and ("Lola", "Lola VA 5") in vu
          and "amelialovee" in vu[("Amelia", "Amelia VA 3")]["texte"]
          and "lolababy" in vu[("Lola", "Lola VA 5")]["texte"], list(vu))
    check("🟢 9 visites (Amelia), 🟠 0 (Lola), 🔴 sans lien et inactif depuis 2 j (Emma VA 7)",
          vu[("Amelia", "Amelia VA 3")]["rond"] == "🟢" and vu[("Lola", "Lola VA 5")]["rond"] == "🟠"
          and vu[("Emma", "Emma VA 7")]["rond"] == "🔴", {k: v["rond"] for k, v in vu.items()})
    check("ni le compte sans limite du propriétaire, ni un VA hors du serveur",
          not any("seven" in x["texte"] or "mario" in x["texte"] for x in l_ig)
          and len(l_ig) == 4, [x["texte"] for x in l_ig])
    check("un lien coupé (rôle retiré) ne fait plus de lui un VA de cette model",
          not any(x["section"] == "Emma" and "paul" in x["texte"] for x in l_ig)
          and "emmacut" not in " ".join(x["texte"] for x in l_ig))
    lea = [x for x in l_ig if "lea" in x["texte"]]
    check("le lien coupé de la model de son salon : 🟠 « lien coupé », pas « sans lien »",
          len(lea) == 1 and lea[0]["rond"] == "🟠" and "`emmaold` · lien coupé" in lea[0]["texte"]
          and lea[0]["visites"] == 0, lea)

    # ------------------------------------------------------------------ 4
    print("\n— 4. la publication")
    k0 = len(D.appels)
    b = ts.publier(TH)
    cree = [a for a in D.appels[k0:] if a[0] == "POST" and a[1].endswith("/channels")]
    check("salon « ─│📊┤-suivi-va » créé, fermé à @everyone, ouvert au staff et au bot",
          len(cree) == 1 and cree[0][2]["name"] == "─│📊┤-suivi-va"
          and {"id": TH, "type": 0, "allow": "0", "deny": str(ts.VOIR)} in cree[0][2]["permission_overwrites"]
          and any(o["id"] == "bot1" for o in cree[0][2]["permission_overwrites"])
          and any(o["id"] == "role_helper" for o in cree[0][2]["permission_overwrites"]), cree)
    page = D.messages[b["messages"][0]]["embeds"][0]
    check("le message : titre, sections par pastille, total",
          page["title"] == "📊 Suivi des VA — Threads"
          and "🟢 **Leur lien fait des visites — 1**" in page["description"]
          and "🔴 **Sans lien, plus rien depuis 2 jours — 1**" in page["description"]
          and "👥 5 lignes · 5 visites depuis le " in page["description"]
          and "aujourd'hui compris" in page["description"], page["description"])
    k1 = len(D.appels)
    GMS["visites"][EMY_THREADS]["lnk_b"] = 4
    b2 = ts.publier(TH)
    check("passage suivant : le même message réédité, rien de créé",
          b2["messages"] == b["messages"]
          and not [a for a in D.ecritures(k1) if a[0] == "POST"]
          and "**4** visites" in D.messages[b["messages"][0]]["embeds"][0]["description"])
    check("une fois l'heure", not ts.a_publier(TH) and ts.a_publier(TH, time.time() + 3601))
    nom_salon = next(c for c in SALONS[TH] if c.get("name") == "─│📊┤-suivi-va")
    nom_salon["name"] = "─│📋┤-suivi-va"
    k_r = len(D.appels)
    b_r = ts.publier(TH)
    check("salon renommé à la main : retrouvé à son identifiant, pas recréé",
          b_r["messages"] == b["messages"]
          and not [a for a in D.appels[k_r:] if a[0] == "POST" and a[1].endswith("/channels")], b_r)
    D.panne = 503
    k_p = len(D.appels)
    b_p = ts.publier(TH)
    check("Discord en panne pendant l'édition : rien reposté, la page garde son message, "
          "nouvel essai dans 10 min",
          "503" in b_p["erreur"] and b_p["messages"] == b["messages"]
          and not [a for a in D.appels[k_p:] if a[0] == "POST"]
          and safe_json.load(TMP / "tableau_staff.json")[TH]["messages"] == b["messages"]
          and not ts.a_publier(TH, time.time() + 9 * 60)
          and ts.a_publier(TH, time.time() + 11 * 60), b_p)
    D.panne = 0
    _t = ts.TAILLE_PAGE
    ts.TAILLE_PAGE = 150
    try:
        b_m = ts.publier(TH)
        nb = len(b_m["messages"])
        del D.messages[b_m["messages"][0]]          # le staff supprime la page 1
        b_s = ts.publier(TH)
    finally:
        ts.TAILLE_PAGE = _t
    ordre = sorted(b_s["messages"], key=int)
    check("page supprimée à la main : une neuve, et les pages restent dans l'ordre du salon",
          nb > 2 and len(b_s["messages"]) == nb and b_m["messages"][0] not in b_s["messages"]
          and b_s["messages"] == ordre
          and D.messages[ordre[0]]["embeds"][0]["title"].endswith(f"(1/{nb})")
          and D.messages[ordre[-1]]["embeds"][0]["title"].endswith(f"({nb}/{nb})"),
          (nb, b_s, [D.messages[i]["embeds"][0]["title"] for i in ordre]))
    GMS["panne"] = True
    k2 = len(D.appels)
    b3 = ts.publier(TH)
    check("GetMySocial muet : le tableau garde ses chiffres, nouvel essai dans 10 min",
          b3["erreur"] == "visites illisibles" and not D.ecritures(k2)
          and not ts.a_publier(TH, time.time() + 9 * 60)
          and ts.a_publier(TH, time.time() + 11 * 60), b3)
    GMS["panne"] = False
    ts.TAILLE_PAGE, _taille = 120, ts.TAILLE_PAGE
    try:
        pg = ts.pages(TH, l_th)
    finally:
        ts.TAILLE_PAGE = _taille
    check("un tableau trop long : plusieurs pages, numérotées, le total sur la dernière",
          len(pg) > 1 and pg[0]["title"].endswith(f"(1/{len(pg)})")
          and "👥" in pg[-1]["description"] and "👥" not in pg[0]["description"], len(pg))
    ts.publier(IG)
    cree_ig = [a for a in D.appels if a[0] == "POST" and a[1] == f"/guilds/{IG}/channels"]
    check("Va IG : son salon « 📊・suivi-va », une section par model",
          cree_ig and cree_ig[0][2]["name"] == "📊・suivi-va"
          and any("**Amelia — 1**" in m["embeds"][0]["description"] for m in D.messages.values()))
    ts.publier(TW)
    check("Twitter : son salon, sa page",
          any(a[0] == "POST" and a[1] == f"/guilds/{TW}/channels" for a in D.appels)
          and any("Suivi des VA — Twitter" in m["embeds"][0]["title"] for m in D.messages.values()))

    # ------------------------------------------------------------------ 5
    print("\n— 5. la boucle du site")
    src = (BOT / "web_upload.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    aide = next(n for n in ast.walk(arbre)
                if isinstance(n, ast.FunctionDef) and n.name == "_tableau_staff")
    boucle = next(n for n in ast.walk(arbre)
                  if isinstance(n, ast.For) and isinstance(n.iter, ast.Attribute)
                  and n.iter.attr == "SERVEURS_EXTRA"
                  and "a_rafraichir_subs" in (ast.get_source_segment(src, n) or ""))
    check("la boucle appelle le tableau pour CHAQUE serveur, avant le filtre du podium",
          "_tableau_staff(gid)" in ast.get_source_segment(src, boucle).split("if gid not in _p.SERVEURS")[0])
    ns = {}
    exec(compile(ast.get_source_segment(src, aide), "aide", "exec"), ns)
    import verif_discord as vd
    vus = []
    _pub, _ap = ts.publier, ts.a_publier
    try:
        ts.a_publier = lambda g: True
        ts.publier = lambda g: vus.append((g, vd.serveur_courant())) or {}
        for g in (TW, TH, IG):
            ns["_tableau_staff"](g)
        ts.publier = lambda g: (_ for _ in ()).throw(RuntimeError("panne"))
        ns["_tableau_staff"](TW)
        avale = True
    except Exception:
        avale = False
    finally:
        ts.publier, ts.a_publier = _pub, _ap
    check("… chacun avec son bot (sur_serveur), et une panne n'arrête pas la boucle",
          vus == [(TW, TW), (TH, TH), (IG, IG)] and avale, vus)
finally:
    for mod, sv in ((ts, _SAUVE["ts"]), (tk, _SAUVE["tk"]), (lv, _SAUVE["lv"]),
                    (liens_fr, _SAUVE["lf"]), (pd, _SAUVE["pd"]), (cp, _SAUVE["cp"])):
        for k, v in sv.items():
            setattr(mod, k, v)
    tk._ACTIVITE.clear()
    tk._ACTIVITE_LUE[0] = False
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
