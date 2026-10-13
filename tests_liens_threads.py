# -*- coding: utf-8 -*-
"""tests_liens_threads.py — « Créer son lien » sur YouLab THREADS.

Propriétaire, 13/10/2026 : « faire comme sur Twitter confirmer le VA et créer
un lien, sauf que pour Threads c'est pas avec un lien de tracking, faut juste
dupliquer le lien de VA Threads » — getmysocial.com/emythreads (A/B 50/50).

Ce qui est vérifié :
  - espace() : Threads dans EMY THREADS, gabarit emythreads, jamais de
    tracking ; Twitter inchangé (EMY TWITTER, gabarit de la config) ;
  - manque() : Threads n'exige pas de créatrice MyPuls, même interrupteur ouvert ;
  - creer_pour sur Threads : duplicata de emythreads dans EMY THREADS, SANS
    destination (l'A/B reste), aucun tracking MyPuls, nommé « Threads VA n
    @pseudo », rangé chez le manager dans EMY THREADS, rien de provisoire ;
  - creer_pour sur Twitter : toujours EMY TWITTER, « Twitter VA n @pseudo » ;
  - couper / supprimer un lien Threads : dans l'espace Threads ;
  - rebrancher (tracking) refusé sur Threads ;
  - le bouton « Créer son lien » apparaît sur Threads ;
  - le message au VA dit Threads, sans promettre les subs du podium ;
  - les accueils déjà ouverts sont redessinés une fois, pas à chaque tour ;
  - la synchro des groupes tourne pour Threads (et pas pour Twitter, déjà
    faite par la boucle du podium), au plus toutes les 30 minutes.

Faux GetMySocial et faux Discord : aucun appel réseau, rien dans data/.
Lancement : python tests_liens_threads.py
"""
from __future__ import annotations

import contextlib
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
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TH, TW = lv.THREADS_ID, lv.TWITTER_ID
EMY_THREADS, EMY_TWITTER = "tm_6ab51e03b299b7e3ba6ff7bf", lv.EQUIPE_VA
GABARIT_TW = "lnk_gabarit_twitter"


class FauxGMS(types.ModuleType):
    PUBLIC_LINK_DOMAIN = "https://getmysocial.com"

    def __init__(self):
        super().__init__("gms")
        self.appels = []
        self.pris = set()

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        if sc in self.pris:
            return {"ok": False, "error": "409 shortcode_taken"}
        self.pris.add(sc)
        return {"ok": True, "link": {"id": f"lnk_{sc}"}}

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "list_groups":
            return {"ok": True, "data": {"data": [{"name": "ROUCHAM", "id": "grp_r"}]}}
        if outil == "create_group":
            return {"ok": True, "data": {"id": "grp_" + args["name"].lower()}}
        return {"ok": True, "data": {}}

    def assign_link_to_group(self, link_id, gid, team_id=None):
        self.appels.append(("assign", link_id, gid, team_id))
        return {"ok": True}

    def disable_link(self, lid):
        self.appels.append(("disable", lid))
        return {"ok": True}

    def enable_link(self, lid):
        self.appels.append(("enable", lid))
        return {"ok": True}

    def delete_link(self, lid):
        self.appels.append(("delete", lid))
        return {"ok": True}

    def list_links_team(self, equipe, force_refresh=False):
        self.appels.append(("list_links_team", equipe))
        return {"links": []}


TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "numero_de",
                                         "creer_tracking")}
_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "_api", "_EN_FOND",
                                         "_suite", "identifiant", "nom_manager")}
_SAUVE_GMS = sys.modules.get("gms")


def monde(config=None, tickets=None):
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.CONFIG_FICHIER = TMP / "tickets_config.json"
    for p in (lv.ETAT_FICHIER, tk.ETAT_FICHIER, tk.CONFIG_FICHIER):
        if p.exists():
            p.unlink()
    lv.CONFIG_FICHIER.write_text(json.dumps(config if config is not None else
                                            {"gabarit": GABARIT_TW, "equipe": EMY_TWITTER}))
    if tickets is not None:
        tk.ETAT_FICHIER.write_text(json.dumps({"tickets": tickets}))
    g = FauxGMS()
    sys.modules["gms"] = g
    lv.numero_de = lambda pseudo: 27
    suivis = []
    lv.creer_tracking = lambda nom, creator_id=None: (suivis.append(nom)
                                                      or {"ok": True, "url": "https://of/c9", "code": "c9"})
    tk._CACHE_HELPER.clear()
    return g, suivis


try:
    # ── espace ───────────────────────────────────────────────────────────
    g, _ = monde()
    e = lv.espace(TH)
    check("Threads : espace EMY THREADS, gabarit emythreads, pas de tracking",
          e["equipe"] == EMY_THREADS and e["gabarit"] == "lnk_6acdd0a53fb996c565a47e90"
          and e["tracking"] is False and e["plateforme"] == "Threads", e)
    e = lv.espace(TW)
    check("Twitter : espace et gabarit de la config, inchangés",
          e["equipe"] == EMY_TWITTER and e["gabarit"] == GABARIT_TW and e["plateforme"] == "Twitter", e)
    check("les deux serveurs ont des liens", TH in lv.SERVEURS and TW in lv.SERVEURS)

    monde(config={"gabarit": GABARIT_TW, "mypuls_actif": True})
    check("interrupteur MyPuls ouvert sans créatrice : Twitter refuse",
          "créatrice" in lv.manque(TW), lv.manque(TW))
    check("… Threads, lui, n'en a pas besoin", lv.manque(TH) == "", lv.manque(TH))
    check("Threads : jamais de tracking, même interrupteur ouvert", lv.espace(TH)["tracking"] is False)
    monde(config={"gabarit": GABARIT_TW, "threads": {"gabarit": "lnk_autre"}})
    check("la clé « threads » de la config peut changer le gabarit",
          lv.espace(TH)["gabarit"] == "lnk_autre" and lv.espace(TH)["equipe"] == EMY_THREADS)

    # ── créer sur Threads ────────────────────────────────────────────────
    g, suivis = monde(config={"gabarit": GABARIT_TW, "mypuls_actif": True, "creator_id": 3352})
    r = lv.creer_pour(TH, "u1", "abdoul_9684", par="m1", manager="ROUCHAM")
    dup = [a for a in g.appels if a[0] == "duplicate"]
    check("Threads : lien créé", r.get("ok"), r)
    check("… copie de emythreads, dans EMY THREADS",
          dup and dup[0][1] == "lnk_6acdd0a53fb996c565a47e90" and dup[0][5] == EMY_THREADS, dup)
    check("… SANS destination : l'A/B seren/emy reste", dup and dup[0][4] == "", dup)
    check("… nommé « Threads VA 27 @abdoul_9684 »", dup and dup[0][3] == "Threads VA 27 @abdoul_9684", dup)
    check("… aucun tracking MyPuls, même interrupteur ouvert", suivis == [], suivis)
    assign = [a for a in g.appels if a[0] == "assign"]
    check("… rangé chez ROUCHAM dans EMY THREADS",
          assign and assign[0][2] == "grp_r" and assign[0][3] == EMY_THREADS
          and r.get("groupe") == "ROUCHAM", (assign, r))
    check("… rien de provisoire, plateforme Threads",
          r.get("provisoire") is False and r.get("plateforme") == "Threads", r)
    fiche = lv.lien_de(TH, "u1")
    check("… fiche gardée (lien, numéro, groupe, sans tracking)",
          fiche.get("public_url", "").startswith("https://getmysocial.com/")
          and fiche.get("numero") == 27 and fiche.get("tracking") == ""
          and fiche.get("link_id", "").startswith("lnk_"), fiche)
    r2 = lv.creer_pour(TH, "u1", "abdoul_9684")
    check("un second clic ne double pas le lien", not r2.get("ok") and r2.get("deja"), r2)
    # Propriétaire, 13/10/2026 : « pour Threads il ne doit pas y avoir de emy,
    # ça doit être sans nom », « genre angel, vraiment sans prénom », « mets
    # genre deux y à la fin »
    sc0 = dup[0][2] if dup else ""
    check("… adresse SANS prénom : un mot doux et deux y (« angelyy »), jamais « emy »",
          sc0 == lv.mots_sans_prenom("Threads VA 27 @abdoul_9684", 0)
          and sc0.endswith("yy") and "emy" not in sc0
          and any(sc0 in (m + "yy", m + "y") for m in lv.MOTS_THREADS)
          and fiche.get("public_url") == f"https://getmysocial.com/{sc0}", (sc0, fiche))
    g, _s = monde(config={"gabarit": GABARIT_TW})
    g.pris.update(lv.mots_sans_prenom("Threads VA 27 @abdoul_9684", i) for i in range(3))
    r3 = lv.creer_pour(TH, "u9", "abdoul_9684")
    scs = [a[2] for a in g.appels if a[0] == "duplicate"]
    check("déjà pris (adresses communes à tout GetMySocial) : un autre mot doux, toujours "
          "deux y, toujours sans prénom",
          r3.get("ok") and len(scs) == 4 and all("emy" not in x and x.endswith("yy") for x in scs)
          and scs == [lv.mots_sans_prenom("Threads VA 27 @abdoul_9684", i) for i in range(4)],
          (r3, scs))
    _n = len(lv.MOTS_THREADS)
    _tous = [lv.mots_sans_prenom("Threads VA 27 @abdoul_9684", i) for i in range(_n + 12)]
    check("chaque mot une fois, puis deux mots doux : jamais deux fois le même nom, et un "
          "autre VA commence ailleurs",
          len(set(_tous)) == len(_tous) and all(x.endswith("yy") for x in _tous)
          and lv.mots_sans_prenom("Threads VA 31 @x", 0) != _tous[0]
          and all(sum(x.startswith(m) for m in lv.MOTS_THREADS) >= 1 for x in _tous)
          and not any(m in x for x in _tous for m in ("lovee", "kisses", "princess", "sweetie")),
          _tous[:6])

    # ── Twitter inchangé ─────────────────────────────────────────────────
    g, suivis = monde(config={"gabarit": GABARIT_TW, "equipe": EMY_TWITTER,
                              "mypuls_actif": True, "creator_id": 3352})
    r = lv.creer_pour(TW, "u2", "yazid", manager="YAZID")
    dup = [a for a in g.appels if a[0] == "duplicate"]
    check("Twitter : gabarit et espace Twitter, tracking MyPuls d'abord",
          r.get("ok") and dup[0][1] == GABARIT_TW and dup[0][5] == EMY_TWITTER
          and dup[0][4] == "https://of/c9" and suivis == ["Twitter VA 27 @yazid"], (r, dup, suivis))
    check("… et son adresse garde « emy » (« emycute »), comme avant",
          dup and dup[0][2] == lv.mots_doux("emy", 0) == "emycute", dup)
    g, suivis = monde()
    r = lv.creer_pour(TW, "u3", "moan")
    check("Twitter interrupteur fermé : provisoire, comme avant",
          r.get("ok") and r.get("provisoire") is True and suivis == [], r)

    # ── couper / supprimer / rebrancher ──────────────────────────────────
    g, _ = monde()
    lv.ETAT_FICHIER.write_text(json.dumps({"liens": {f"{TH}:u1": {
        "shortcode": "emycute", "public_url": "https://getmysocial.com/emycute"}}}))
    lv.basculer(TH, "u1", False)
    check("couper un lien Threads : cherché dans EMY THREADS",
          ("list_links_team", EMY_THREADS) in g.appels, g.appels)
    r = lv.rebrancher(TH, "u1")
    check("rebrancher (tracking) refusé sur Threads",
          not r.get("ok") and "Threads" in r.get("erreur", ""), r)
    g.appels.clear()
    lv.supprimer(TH, "u1")
    check("supprimer un lien Threads : cherché dans EMY THREADS",
          ("list_links_team", EMY_THREADS) in g.appels, g.appels)

    # ── Discord : bouton, message ────────────────────────────────────────
    rang = tk.boutons_va("u9", gid=TH)
    ids = [b["custom_id"] for b in rang[0]["components"]]
    check("Threads : « Créer son lien » sous l'accueil", "lien:new:u9" in ids, ids)

    g, _ = monde(tickets={f"{TH}:u4": {"salon": "s4", "manager": "m1", "accueil": "a4"}})
    postes, suites = [], []
    tk._EN_FOND = lambda f: f()
    tk._suite = lambda jeton, texte, p=None: suites.append(texte)
    tk.identifiant = lambda gid, uid: "pseudo_va"
    tk.nom_manager = lambda gid, uid: "ROUCHAM"

    def faux_api(methode, chemin, **kw):
        postes.append((methode, chemin, kw.get("json")))
        if methode == "GET" and chemin.endswith("/messages/a4"):
            return 200, {"id": "a4", "embeds": [{"title": "👋 Bienvenue", "description": "Salut"}]}
        return 200, {}
    tk._api = faux_api
    tk._creer_lien(TH, "u4", "m1", {"token": "t", "channel_id": "s4"})
    msg = [j for (m, c, j) in postes if m == "POST" and c == "/channels/s4/messages"]
    check("message au VA : « tu mets sur Threads », sans promettre les subs",
          msg and "Threads" in msg[0]["content"] and "subs" not in msg[0]["content"], msg)
    acc = [j for (m, c, j) in postes if m == "PATCH" and c == "/channels/s4/messages/a4"]
    desc = acc[0]["embeds"][0]["description"] if acc else ""
    check("accueil épinglé : « celui que tu postes sur Threads », pas de mention MyPuls",
          "sur Threads" in desc and "MyPuls" not in desc and "subs" not in desc, desc)
    check("réponse au manager : lien donné, pas de « destination provisoire »",
          bool(suites) and "getmysocial.com/" in suites[0] and "provisoire" not in suites[0], suites)

    # ── accueils déjà ouverts ────────────────────────────────────────────
    g, _ = monde(tickets={f"{TH}:u5": {"salon": "s5", "accueil": "a5"},
                          f"{TH}:u6": {"salon": "s6", "accueil": "a6", "confirme": True},
                          f"{TH}:u7": {"salon": "s7"},
                          f"{TW}:u8": {"salon": "s8", "accueil": "a8"}})
    postes.clear()
    b = tk.redessiner_boutons(TH)
    patchs = {c: j for (m, c, j) in postes if m == "PATCH"}
    check("anciens accueils Threads redessinés avec « Créer son lien »",
          all("lien:new:" in json.dumps(patchs.get(f"/channels/s{i}/messages/a{i}", {}))
              for i in (5, 6)), patchs)
    check("… sans « Confirmer » pour un VA déjà confirmé",
          "essai:ok:u6" not in json.dumps(patchs.get("/channels/s6/messages/a6", {})))
    check("… un ticket sans accueil connu est compté, pas ignoré", b["sans_accueil"] == ["u7"], b)
    check("… les tickets de Twitter ne sont pas touchés", "/channels/s8/messages/a8" not in patchs)
    postes.clear()
    tk.redessiner_boutons(TH)
    check("… une seule fois : le tour suivant ne réécrit rien",
          not [p for p in postes if p[0] == "PATCH"], postes)

    # ── synchro des groupes ──────────────────────────────────────────────
    vus = []
    _sync = lv.synchroniser
    lv.synchroniser = lambda gid: (vus.append(gid) or {})
    tk._SYNCHRO_VUE.clear()
    tk._synchro_liens(TW, lambda gid: contextlib.nullcontext())
    tk._synchro_liens(TH, lambda gid: contextlib.nullcontext())
    tk._synchro_liens(TH, lambda gid: contextlib.nullcontext())
    check("synchro des groupes : Threads seulement, au plus toutes les 30 min",
          vus == [TH], vus)
    lv.synchroniser = _sync

    # ── EMY THREADS : les groupes des managers, et rien d'autre ──────────
    # Propriétaire, 13/10/2026 : « de base y avait 2 groupes et c'est tout,
    # pourquoi y a Roucham, pourquoi y a un truc MANAGER », « automatique ».
    class GMSGroupes(FauxGMS):
        def __init__(self):
            super().__init__()
            self.grp = {"ABDOUL": "grp_a", "MOMOBY": "grp_m", "ROUCHAM": "grp_r",
                        "MANAGER": "grp_x"}
            self.dedans = {"grp_a": ["lnk_angel", "lnk_main"], "grp_m": [], "grp_r": [],
                           "grp_x": ["lnk_v", "lnk_c", "lnk_starry"]}
            self.statut = {"lnk_angel": "inactive", "lnk_starry": "inactive"}

        def _ou(self, lid):
            return next((g_ for g_, ls in self.dedans.items() if lid in ls), None)

        def assign_link_to_group(self, link_id, gid_, team_id=None):
            self.appels.append(("assign", link_id, gid_, team_id))
            if self._ou(link_id):
                self.dedans[self._ou(link_id)].remove(link_id)
            self.dedans.setdefault(gid_, []).append(link_id)
            return {"ok": True}

        def _call_tool(self, outil, args):
            self.appels.append((outil, dict(args)))
            if outil == "list_groups":
                return {"ok": True, "data": {"data": [{"name": n, "id": i}
                                                      for n, i in self.grp.items()]}}
            if outil == "create_group":
                self.grp[args["name"]] = "grp_" + args["name"].lower()
                self.dedans.setdefault(self.grp[args["name"]], [])
                return {"ok": True, "data": {"id": self.grp[args["name"]]}}
            if outil == "list_links":
                return {"ok": True, "data": {"data": [
                    {"id": l, "status": self.statut.get(l, "active")}
                    for l in self.dedans.get(args["group_id"], [])], "has_more": False}}
            if outil == "remove_links_from_group":
                for l in args["link_ids"]:
                    self.dedans[args["group_id"]].remove(l)
                return {"ok": True, "data": {}}
            if outil == "delete_group":
                self.grp = {n: i for n, i in self.grp.items() if i != args["group_id"]}
                self.dedans.pop(args["group_id"], None)
                return {"ok": True, "data": {"deleted": True}}
            return {"ok": True, "data": {}}

    g, _ = monde(config={"gabarit": GABARIT_TW},
                 tickets={f"{TH}:u1": {"salon": "s1"}, f"{TH}:u2": {"salon": "s2"}})
    g = GMSGroupes()
    sys.modules["gms"] = g
    lv.ETAT_FICHIER.write_text(json.dumps({"liens": {
        f"{TH}:u1": {"pseudo": "momobtn", "shortcode": "velvetyy", "link_id": "lnk_v",
                     "groupe": "MANAGER"},
        f"{TH}:u2": {"pseudo": "steave0454", "shortcode": "cutieyy", "link_id": "lnk_c",
                     "groupe": "MANAGER"}}}))
    MGR = [{"user": {"id": "m1", "username": "abdoul_9684"}, "nick": "MANAGER | Abdoul"},
           {"user": {"id": "m2", "username": "momobtn"}, "nick": "MANAGER | Momoby"}]
    SAL = [{"id": "21", "type": 4, "name": "🔵┤ Manager ABDOUL ├🔵"},
           {"id": "22", "type": 4, "name": "🔵┤ Manager MOMOBY ├🔵"},
           {"id": "s1", "type": 0, "parent_id": "21"}, {"id": "s2", "type": 0, "parent_id": "21"}]
    _sauve_m = (tk.managers, tk._managers_surs)
    try:
        tk.managers = lambda gid, force=False: list(MGR)
        tk._managers_surs = lambda gid: (False, "rid", list(MGR))
        tk._api = lambda m, c, **k: (200, json.loads(json.dumps(SAL))) if c.endswith("/channels") \
            else (200, {})
        b = lv.synchroniser(TH)
        check("EMY THREADS rangé : deux groupes, ABDOUL et MOMOBY (ROUCHAM et MANAGER supprimés)",
              sorted(g.grp) == ["ABDOUL", "MOMOBY"]
              and sorted(b.get("groupes_supprimes", [])) == ["MANAGER", "ROUCHAM"], (g.grp, b))
        check("… les liens des VA suivent leur catégorie (ABDOUL), le lien posé à la main reste",
              sorted(g.dedans["grp_a"]) == ["lnk_c", "lnk_main", "lnk_v"]
              and json.loads(lv.ETAT_FICHIER.read_text())["liens"][f"{TH}:u1"]["groupe"] == "ABDOUL",
              g.dedans)
        check("… les liens coupés qu'aucune fiche ne tient sortent des groupes (sans être "
              "supprimés)", sorted(x.split()[0] for x in b.get("sortis", []))
              == ["lnk_angel", "lnk_starry"]
              and not [a for a in g.appels if a[0] in ("delete", "delete_links")], b)
        n = len(g.appels)
        b2 = lv.synchroniser(TH)
        check("… un second passage ne touche plus à rien",
              not b2.get("groupes_supprimes") and not b2.get("sortis") and not b2["deplaces"]
              and not [a for a in g.appels[n:] if a[0] in ("remove_links_from_group",
                                                           "delete_group", "assign")], b2)
        g.grp["ANCIEN"] = "grp_z"
        g.dedans["grp_z"] = []
        tk._managers_surs = lambda gid: (False, "rid", None)
        b3 = lv.synchroniser(TH)
        check("managers indéterminables : aucun groupe supprimé, et c'est dit",
              "ANCIEN" in g.grp and any("indéterminables" in r for r in b3["rates"]), b3)
        check("Twitter n'a pas ce rangement (son espace a d'autres groupes, TEMPLATES…)",
              not lv.espace(TW).get("groupes_managers_seuls")
              and lv.espace(TH).get("groupes_managers_seuls") is True)
    finally:
        tk.managers, tk._managers_surs = _sauve_m

    # ── le numéro du VA dans le nom du salon (Threads) ───────────────────
    # Propriétaire, 13/10/2026 : « faut mettre le numéro du VA », comme Va IG
    # (« 🔴-21-va-… »).
    g, _ = monde(config={"gabarit": GABARIT_TW},
                 tickets={f"{TH}:u1": {"salon": "s1"}, f"{TH}:u2": {"salon": "s2"},
                          f"{TH}:u9": {"salon": "s9"}, f"{TW}:u3": {"salon": "s3"}})
    lv.ETAT_FICHIER.write_text(json.dumps({"liens": {
        f"{TH}:u1": {"pseudo": "momobtn", "shortcode": "velvetyy", "numero": 61}}}))
    A = tk.AROBASE
    SALONS_N = {"s1": f"─│🔵┤-va-{A}momobtn", "s2": f"─│🔵┤-va-{A}steave0454",
                "s9": f"─│🔵┤-12-va-{A}deja", "s3": f"─│🔵┤-va-{A}yazid"}
    patchs_n = []

    def _api_n(m, c, **k):
        if m == "GET" and c.endswith("/channels"):
            gid_ = c.split("/")[2]
            return 200, [{"id": i, "type": 0, "name": n} for i, n in SALONS_N.items()
                         if (i == "s3") == (gid_ == TW)]
        if m == "PATCH":
            cid = c.split("/")[2]
            patchs_n.append((cid, k["json"]["name"]))
            SALONS_N[cid] = k["json"]["name"]
            return 200, {}
        return 200, {}
    tk._api = _api_n
    bn = tk.numeroter_salons(TH)
    check("Threads : chaque salon de VA prend son numéro (celui de son lien, sinon celui "
          "que la table lui réserve), devant « -va- »",
          sorted(patchs_n) == [("s1", f"─│🔵┤-61-va-{A}momobtn"),
                               ("s2", f"─│🔵┤-27-va-{A}steave0454")], (patchs_n, bn))
    check("… un salon déjà numéroté n'est pas touché", "s9" not in [c for c, _n in patchs_n])
    patchs_n.clear()
    tk.numeroter_salons(TH)
    check("… une fois : le passage suivant ne renomme plus rien", not patchs_n, patchs_n)
    check("Twitter garde ses noms (« ─│🔵┤-va-＠yazid »), sans numéro",
          not tk.numeroter_salons(TW)["renommes"] and SALONS_N["s3"] == f"─│🔵┤-va-{A}yazid"
          and tk.nom_salon_va(TW, "u3", "yazid") == f"─│🔵┤-va-{A}yazid")
    check("un ticket neuf sur Threads naît numéroté",
          tk.nom_salon_va(TH, "u1", "momobtn") == f"─│🔵┤-61-va-{A}momobtn")
finally:
    for _k, _v in _SAUVE_LV.items():
        setattr(lv, _k, _v)
    for _k, _v in _SAUVE_TK.items():
        setattr(tk, _k, _v)
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS
    else:
        sys.modules.pop("gms", None)
    tk._SYNCHRO_VUE.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
