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
          fiche.get("public_url", "").startswith("https://getmysocial.com/emy")
          and fiche.get("numero") == 27 and fiche.get("tracking") == ""
          and fiche.get("link_id", "").startswith("lnk_"), fiche)
    r2 = lv.creer_pour(TH, "u1", "abdoul_9684")
    check("un second clic ne double pas le lien", not r2.get("ok") and r2.get("deja"), r2)

    # ── Twitter inchangé ─────────────────────────────────────────────────
    g, suivis = monde(config={"gabarit": GABARIT_TW, "equipe": EMY_TWITTER,
                              "mypuls_actif": True, "creator_id": 3352})
    r = lv.creer_pour(TW, "u2", "yazid", manager="YAZID")
    dup = [a for a in g.appels if a[0] == "duplicate"]
    check("Twitter : gabarit et espace Twitter, tracking MyPuls d'abord",
          r.get("ok") and dup[0][1] == GABARIT_TW and dup[0][5] == EMY_TWITTER
          and dup[0][4] == "https://of/c9" and suivis == ["Twitter VA 27 @yazid"], (r, dup, suivis))
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
