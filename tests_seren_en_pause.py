# -*- coding: utf-8 -*-
"""tests_seren_en_pause.py — tout chez Emy, plus de Seren (21/10/2026).

Propriétaire : « tout envoyé que sur Emy, plus de Seren pour le moment, pour
Threads et Twitter, et même pour les prochaines créations », puis « ok, tout
sur Emy ».

Ce qui est vérifié :
  - espace() : plus de variante, Twitter comme Threads (même celle qu'un patch
    du VPS ouvre sur Threads) ;
  - creer_pour : pas de tracking Seren, pas de copie temporaire, pas d'A/B ; le
    50/50 hérité du gabarit (emythreads) est éteint sur le lien neuf ;
  - couper_seren : éteint les A/B allumés de la liste (liens de VA comme liens
    de base), note chacun AVANT (config d'avant, tracking Seren de la fiche),
    marque la fiche, ne refait rien au passage suivant, s'arrête au premier
    refus de cookie ;
  - reprendre_variantes ne repose rien ;
  - remettre_seren : seulement Seren rallumé, fiches coupées « à poser » avec
    LEUR tracking Seren ;
  - gms.allumer_ab_testing : le corps envoyé (enabled false, variantes avec
    leur variantId), et la relecture.

Faux GetMySocial, faux MyPuls : aucun appel réseau, rien dans data/.
Lancement : python tests_seren_en_pause.py
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms as vrai_gms                 # noqa: E402
import liens_va as lv                  # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH = lv.TWITTER_ID, lv.THREADS_ID
EMY_TWITTER = lv.EQUIPE_VA
EMY_THREADS = lv.ESPACE_THREADS["equipe"]
CONFIG = {"gabarit": "lnk_gabarit_twitter", "equipe": EMY_TWITTER, "mypuls_actif": True,
          "creator_id": 3352, "threads": {"tracking": True}}
AB_SEREN = {"enabled": True, "controlWeight": 50,
            "variants": [{"variantId": "v1", "sourceLinkId": "s1", "weight": 50, "name": "Seren",
                          "description": "Variant based on another link"}]}


class FauxGMS(types.ModuleType):
    PUBLIC_LINK_DOMAIN = "https://getmysocial.com"

    def __init__(self):
        super().__init__("gms")
        self.appels = []
        self.ab = {}            # id sans lnk_ -> config A/B
        self.liste = {}         # équipe -> liens
        self.cookie_ok = True

    def de(self, genre):
        return [a for a in self.appels if a[0] == genre]

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        # la copie de emythreads garde son A/B (vérifié le 13/10/2026)
        self.ab[f"id_{sc}"] = json.loads(json.dumps(AB_SEREN))
        return {"ok": True, "link": {"id": f"lnk_id_{sc}", "url": url or "https://onlyfans.com/emy.brw"}}

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "update_link" and "shortcode" in args:
            return {"ok": True, "data": {"id": args["link_id"], "shortcode": args["shortcode"]}}
        if outil == "list_groups":
            return {"ok": True, "data": {"data": [{"name": "YAZID", "id": "grp_y"}]}}
        return {"ok": True, "data": {}}

    def assign_link_to_group(self, link_id, gid, team_id=None):
        return {"ok": True}

    def poser_ab_testing(self, *a):
        self.appels.append(("ab", a))
        return {"ok": True}

    def delete_link(self, lid):
        self.appels.append(("delete", lid))
        return {"ok": True}

    def get_session_cookie(self):
        return "authToken=a.b.c"

    def cookie_expiration(self, ck=None):
        return None

    def list_links_team(self, equipe, force_refresh=False):
        self.appels.append(("liste", equipe))
        out = []
        for l in self.liste.get(equipe, []):
            cfg = self.ab.get(l["id"][4:]) or {"enabled": False, "variants": []}
            out.append(dict(l, ab_testing={"enabled": cfg["enabled"],
                                           "variants": cfg.get("variants") or []}))
        return {"links": out}

    def lire_ab_testing(self, lid, equipe=""):
        self.appels.append(("lire", lid, equipe))
        if not self.cookie_ok:
            return {"ok": False, "cookie": True, "error": "cookie refusé"}
        return {"ok": True, "config": json.loads(json.dumps(
            self.ab.get(lid[4:] if lid.startswith("lnk_") else lid)
            or {"enabled": False, "controlWeight": 50, "variants": []}))}

    def allumer_ab_testing(self, lid, equipe="", actif=True, variantes=None):
        self.appels.append(("allumer", lid, equipe, actif))
        k = lid[4:] if lid.startswith("lnk_") else lid
        # comme GetMySocial : éteint, l'A/B perd sa variante
        self.ab[k] = {"enabled": bool(actif), "controlWeight": 50,
                      "variants": list(variantes or []) if actif else []}
        return {"ok": True, "config": self.ab[k]}


TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "COUPES_FICHIER",
                                         "numero_de", "creer_tracking", "SEREN_EN_PAUSE")}
_SAUVE_GMS = sys.modules.get("gms")
_SAUVE_REQ = (vrai_gms.requests.get, vrai_gms.requests.post, vrai_gms.get_session_cookie)


def monde(etat=None):
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    lv.COUPES_FICHIER = TMP / "liens_seren_coupes.json"
    lv.SEREN_EN_PAUSE = True
    for p in TMP.iterdir():
        p.unlink()
    lv.CONFIG_FICHIER.write_text(json.dumps(CONFIG))
    lv.ETAT_FICHIER.write_text(json.dumps(etat or {}))
    g = FauxGMS()
    sys.modules["gms"] = g
    lv.numero_de = lambda pseudo: 27
    suivis = []

    def faux_tracking(nom, creator_id=None):
        suivis.append((nom, creator_id))
        return {"ok": True, "url": "https://onlyfans.com/emy.brw/c55", "code": "c55"}
    lv.creer_tracking = faux_tracking
    return g, suivis


try:
    # ── les liens à venir ────────────────────────────────────────────────
    monde()
    check("espace() : plus de variante Seren sur Twitter", lv.espace(TW).get("variante") is None)
    # le patch du VPS (99-threads-mypuls) pose la variante dans le corps
    # d'origine : l'enveloppe la retire quand même
    _orig = lv._espace_avec_seren
    lv._espace_avec_seren = lambda gid="": dict(_orig(gid), variante=dict(lv.VARIANTE_TWITTER))
    check("… ni sur Threads, même ouverte par le patch du VPS",
          lv.espace(TH).get("variante") is None and lv.espace(TW).get("variante") is None)
    lv._espace_avec_seren = _orig
    lv.SEREN_EN_PAUSE = False
    check("… et revient quand la pause est levée (Twitter)",
          lv.espace(TW).get("variante") == lv.VARIANTE_TWITTER)
    lv.SEREN_EN_PAUSE = True

    g, suivis = monde()
    r = lv.creer_pour(TW, "u1", "yazid", manager="YAZID")
    check("Twitter : lien créé, sans variante", r.get("ok") and r.get("variante") is None, r)
    check("… un seul tracking (Emy), aucun chez Seren",
          [c for _n, c in suivis] == [None], suivis)
    check("… pas de copie temporaire ni d'A/B posé",
          len(g.de("duplicate")) == 1 and not g.de("ab") and not g.de("delete"), g.appels)
    check("… le 50/50 hérité du gabarit est éteint sur le lien neuf",
          g.de("allumer") and g.de("allumer")[0][3] is False
          and not g.ab[f'id_{r["shortcode"]}']["enabled"], g.appels)
    fiche = lv.lien_de(TW, "u1")
    check("… noté (config d'avant) et la fiche marquée « coupee »",
          (json.loads(lv.COUPES_FICHIER.read_text())["liens"][f'id_{r["shortcode"]}']["avant"]
           ["enabled"] is True) and (fiche.get("variante") or {}).get("coupee"), fiche)

    # ── les liens d'aujourd'hui ──────────────────────────────────────────
    etat = {"liens": {
        f"{TW}:u31": {"pseudo": "abdoul", "numero": 31, "shortcode": "bbyy", "link_id": "lnk_a31",
                      "variante": {"posee": True, "tracking": "https://onlyfans.com/seren.vale/c196",
                                   "modele": "Seren"}},
        f"{TH}:u89": {"pseudo": "michel", "numero": 89, "shortcode": "babystarryy",
                      "link_id": "lnk_t89",
                      "variante": {"posee": True, "tracking": "https://onlyfans.com/seren.vale/c221"}}}}
    g, _ = monde(etat)
    g.liste = {EMY_TWITTER: [{"id": "lnk_a31", "shortcode": "bbyy", "display_name": "Twitter VA 31 @abdoul"},
                             {"id": "lnk_tst", "shortcode": "testemy", "display_name": "test emy"}],
               EMY_THREADS: [{"id": "lnk_t89", "shortcode": "babystarryy"},
                             {"id": "lnk_t62", "shortcode": "starryy"},
                             {"id": "lnk_emt", "shortcode": "emythreads"}]}
    for k in ("a31", "t89", "t62", "emt"):
        g.ab[k] = json.loads(json.dumps(AB_SEREN))
    b_tw = lv.couper_seren(TW)
    b_th = lv.couper_seren(TH)
    check("Twitter : le 50/50 de chaque lien allumé est éteint, pas les autres",
          b_tw["coupes"] == ["bbyy"] and not b_tw["rates"]
          and [a[1] for a in g.de("allumer")] == ["a31", "t89", "t62", "emt"], (b_tw, g.appels))
    check("Threads : liens de VA ET liens de base (« tout sur Emy »), y compris sans fiche",
          b_th["coupes"] == ["babystarryy", "starryy", "emythreads"], b_th)
    check("… chez GetMySocial : tous éteints",
          not any(g.ab[k]["enabled"] for k in ("a31", "t89", "t62", "emt")), g.ab)
    notes = json.loads(lv.COUPES_FICHIER.read_text())["liens"]
    check("… chacun noté : config d'avant, tracking Seren de la fiche, fait",
          notes["a31"]["avant"]["variants"][0]["variantId"] == "v1"
          and notes["a31"]["tracking_seren"].endswith("/c196") and notes["a31"]["fait"]
          and notes["t62"]["fiche"] == "" and notes["t62"]["serveur"] == TH, notes)
    f31 = lv.lien_de(TW, "u31")["variante"]
    check("… la fiche garde « posee » (le podium lit encore ses clics Seren) et dit « coupee »",
          f31.get("posee") is True and f31.get("coupee"), f31)
    n_avant = len(g.appels)
    b2 = lv.couper_seren(TW)
    check("passage suivant : rien d'allumé, une liste et aucun autre appel",
          b2 == {"coupes": [], "rates": []} and [a[0] for a in g.appels[n_avant:]] == ["liste"],
          g.appels[n_avant:])
    check("reprendre_variantes ne repose rien tant que Seren est en pause",
          lv.reprendre_variantes(TW) == {"poses": [], "rates": [], "a_verifier": []}
          and not g.de("ab"))

    # bloomyy, éteint à la main (essai du 21/10) : sa fiche est marquée quand même
    g, _ = monde(etat)
    g.liste = {EMY_TWITTER: [{"id": "lnk_a31", "shortcode": "bbyy"}]}
    b4 = lv.couper_seren(TW)
    f31 = lv.lien_de(TW, "u31")["variante"]
    notes = json.loads(lv.COUPES_FICHIER.read_text())["liens"]
    check("A/B déjà éteint à la main : rien d'appelé, mais la fiche est marquée et notée",
          b4["coupes"] == [] and not g.de("allumer") and not g.de("lire")
          and f31.get("coupee") and notes["a31"]["deja_eteint"]
          and notes["a31"]["tracking_seren"].endswith("/c196"), (b4, f31, notes))

    g, _ = monde(etat)
    g.liste = {EMY_THREADS: [{"id": "lnk_t89", "shortcode": "babystarryy"},
                             {"id": "lnk_t62", "shortcode": "starryy"}]}
    g.ab["t89"] = json.loads(json.dumps(AB_SEREN))
    g.ab["t62"] = json.loads(json.dumps(AB_SEREN))
    g.cookie_ok = False
    b3 = lv.couper_seren(TH)
    check("cookie refusé : arrêt au premier lien, dit, rien d'éteint",
          b3.get("cookie") and len(b3["rates"]) == 1 and not b3["coupes"]
          and not g.de("allumer"), b3)

    # ── le retour au 50/50 ───────────────────────────────────────────────
    g, _ = monde(etat)
    g.liste = {EMY_TWITTER: [{"id": "lnk_a31", "shortcode": "bbyy"}]}
    g.ab["a31"] = json.loads(json.dumps(AB_SEREN))
    lv.couper_seren(TW)
    check("remettre_seren refuse tant que la pause tient",
          lv.remettre_seren(TW).get("ok") is False)
    lv.SEREN_EN_PAUSE = False
    rm = lv.remettre_seren(TW)
    f31 = lv.lien_de(TW, "u31")["variante"]
    check("remettre_seren : la fiche coupée repasse « à poser », avec SON tracking Seren",
          rm == {"ok": True, "a_reposer": 1} and f31.get("posee") is False
          and "coupee" not in f31 and f31["tracking"].endswith("/c196")
          and f"{TW}:u31" in lv.en_attente(TW), f31)
    check("… et seulement celles de ce serveur (Threads non touché)",
          lv.lien_de(TH, "u89")["variante"].get("posee") is True)
    lv.SEREN_EN_PAUSE = True

    # ── gms.allumer_ab_testing, l'appel réel (requests simulé) ───────────
    sys.modules["gms"] = vrai_gms
    envois = []
    etat_gms = {"cfg": json.loads(json.dumps(AB_SEREN))}

    class Rep:
        def __init__(self, cfg, code=200):
            self.status_code, self._cfg = code, cfg

        def json(self):
            return {"success": True, "config": self._cfg}

    def faux_get(url, params=None, headers=None, timeout=None, allow_redirects=None):
        envois.append(("GET", url, params))
        return Rep(json.loads(json.dumps(etat_gms["cfg"])))

    def faux_post(url, headers=None, json=None, timeout=None, allow_redirects=None):
        envois.append(("POST", url, json))
        etat_gms["cfg"] = {"enabled": json["enabled"], "controlWeight": json["controlWeight"],
                           "variants": json["variants"] if json["enabled"] else []}
        return Rep(etat_gms["cfg"])
    vrai_gms.requests.get, vrai_gms.requests.post = faux_get, faux_post
    vrai_gms.get_session_cookie = lambda: "authToken=a.b.c"
    r = vrai_gms.allumer_ab_testing("lnk_abc", "tm_def", actif=False)
    post = [e for e in envois if e[0] == "POST"]
    check("allumer_ab_testing(False) : enabled false, variantes renvoyées avec leur variantId",
          r.get("ok") and len(post) == 1 and post[0][1].endswith("/links/ab-testing/abc/save")
          and post[0][2]["enabled"] is False and post[0][2]["teamId"] == "def"
          and post[0][2]["variants"][0]["variantId"] == "v1", (r, post))
    check("… relu : éteint, et la variante perdue est dite (pas cachée)",
          r["config"]["enabled"] is False and r.get("variantes_perdues") == ["v1"], r)
    envois.clear()
    r = vrai_gms.allumer_ab_testing("lnk_abc", "tm_def", actif=False)
    check("… déjà éteint : aucun enregistrement", r.get("deja") and not [e for e in envois if e[0] == "POST"])
    r = vrai_gms.allumer_ab_testing("lnk_abc", "tm_def", actif=True)
    check("rallumer sans variante connue : refusé, rien envoyé",
          r.get("ok") is False and "aucune variante" in r.get("error", ""), r)
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS
    vrai_gms.requests.get, vrai_gms.requests.post, vrai_gms.get_session_cookie = _SAUVE_REQ

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
