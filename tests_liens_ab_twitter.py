# -*- coding: utf-8 -*-
"""tests_liens_ab_twitter.py — le 50/50 Emy / Seren des liens de VA Twitter.

Propriétaire, 14/10/2026 : « exactement le même lien [que emythreads] juste
pour Twitter, quand je génère un lien le mec il a son tracking link », puis
« avec 2 tracking links, un pour Emy et un pour Seren », « dans EMY TWITTER ».

Ce qui est vérifié :
  - espace() : la variante Seren (3867, 50 %) sur Twitter seulement, et
    seulement MyPuls ouvert ; la config peut l'éteindre ;
  - creer_pour : tracking Emy, lien GetMySocial, PUIS tracking Seren au même
    nom, copie temporaire du gabarit vers le tracking Seren dans EMY TWITTER,
    A/B posé sur le lien du VA, copie supprimée ;
  - un cookie refusé : le lien est créé quand même (tout sur Emy), le
    tracking Seren est noté, la copie temporaire supprimée ;
  - reprendre_variantes : réutilise le tracking noté (MyPuls ne supprime
    rien), s'arrête au premier refus de cookie, ne touche pas aux liens
    d'avant le 50/50 ;
  - une copie temporaire dont l'adresse n'a pas pris : pas d'A/B ;
  - MyPuls muet pour Seren : lien créé, échec noté, repris ensuite ;
  - le podium voit le tracking de la variante, sur ce lien seulement ;
  - gms.poser_ab_testing : le corps envoyé, et un cookie périmé reconnu ;
  - le cookie : valeur d'authToken seule acceptée, échéance lue ;
  - le message au manager.

Faux GetMySocial, faux MyPuls, faux Discord : aucun appel réseau, rien dans data/.
Lancement : python tests_liens_ab_twitter.py
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import shutil
import sys
import tempfile
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms as vrai_gms                 # noqa: E402
import liens_va as lv                  # noqa: E402
import podium_discord as pod           # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH = lv.TWITTER_ID, lv.THREADS_ID
EMY_TWITTER = lv.EQUIPE_VA
GABARIT_TW = "lnk_gabarit_twitter"
CONFIG = {"gabarit": GABARIT_TW, "equipe": EMY_TWITTER, "mypuls_actif": True, "creator_id": 3352}


class FauxGMS(types.ModuleType):
    PUBLIC_LINK_DOMAIN = "https://getmysocial.com"

    def __init__(self):
        super().__init__("gms")
        self.appels = []
        self.ab = {"ok": True, "config": {}}
        self.adresse_prise = True

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        return {"ok": True, "link": {"id": f"lnk_{sc}",
                                     "url": url if (url and self.adresse_prise) else "https://onlyfans.com/emy.brw"}}

    def poser_ab_testing(self, lid, source, equipe, poids, nom):
        self.appels.append(("ab", lid, source, equipe, poids, nom))
        return dict(self.ab)

    cookie = "authToken=a.b.c"
    echeance = None

    def get_session_cookie(self):
        return self.cookie

    def cookie_expiration(self, ck=None):
        return self.echeance

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "list_groups":
            return {"ok": True, "data": {"data": [{"name": "YAZID", "id": "grp_y"}]}}
        return {"ok": True, "data": {}}

    def assign_link_to_group(self, link_id, gid, team_id=None):
        self.appels.append(("assign", link_id, gid, team_id))
        return {"ok": True}

    def delete_link(self, lid):
        self.appels.append(("delete", lid))
        return {"ok": True}

    def list_links_team(self, equipe, force_refresh=False):
        return {"links": []}

    def de(self, genre):
        return [a for a in self.appels if a[0] == genre]


TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "numero_de",
                                         "creer_tracking")}
_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "_api", "_EN_FOND",
                                         "_suite", "identifiant", "nom_manager")}
_SAUVE_GMS = sys.modules.get("gms")
_SAUVE_REQ_POST = vrai_gms.requests.post
_SAUVE_COOKIE = vrai_gms.get_session_cookie
SEQ = []      # l'ordre des créations, MyPuls et GetMySocial mêlés


def monde(config=None, etat=None, mypuls_ok=True):
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.CONFIG_FICHIER = TMP / "tickets_config.json"
    for p in TMP.iterdir():
        p.unlink()
    lv.CONFIG_FICHIER.write_text(json.dumps(CONFIG if config is None else config))
    if etat is not None:
        lv.ETAT_FICHIER.write_text(json.dumps(etat))
    g = FauxGMS()
    sys.modules["gms"] = g
    lv.numero_de = lambda pseudo: 27
    suivis = []
    SEQ.clear()

    def faux_tracking(nom, creator_id=None):
        suivis.append((nom, creator_id))
        SEQ.append(("mypuls", creator_id))
        if creator_id == 3867 and not mypuls_ok:
            return {"ok": False, "erreur": "session MyPuls indisponible (cookies)"}
        code = "c201" if creator_id == 3867 else "c55"
        modele = "seren.vale" if creator_id == 3867 else "emy.brw"
        return {"ok": True, "url": f"https://onlyfans.com/{modele}/{code}", "code": code}
    lv.creer_tracking = faux_tracking
    _dup = g.duplicate_link

    def dup_trace(*a):
        SEQ.append(("gms", a[1]))
        return _dup(*a)
    g.duplicate_link = dup_trace
    tk._CACHE_HELPER.clear()
    return g, suivis


SEREN = "https://onlyfans.com/seren.vale/c201"
# l'adresse du premier lien : sans prénom (« pour les noms des liens GMS ca
# doit pas avoir de nom », 14/10/2026)
SC1 = lv.mots_sans_prenom("Twitter VA 27 @yazid", 0)

try:
    # ── espace ───────────────────────────────────────────────────────────
    monde()
    v = lv.espace(TW).get("variante")
    check("Twitter, MyPuls ouvert : variante Seren (3867) à 50 %",
          v == {"modele": "Seren", "creator_id": 3867, "poids": 50}, v)
    monde(config=dict(CONFIG, mypuls_actif=False))
    check("… MyPuls fermé : pas de variante (une moitié rattachée à personne)",
          lv.espace(TW).get("variante") is None)
    monde(config=dict(CONFIG, variante={}))
    check("… la config l'éteint (« variante » : {})", lv.espace(TW).get("variante") is None)
    monde(config=dict(CONFIG, variante={"poids": 30}))
    check("… ou change le poids, le reste par défaut",
          lv.espace(TW)["variante"] == {"modele": "Seren", "creator_id": 3867, "poids": 30})
    monde()
    check("Threads : jamais de variante (son 50/50 vient de emythreads)",
          lv.espace(TH).get("variante") is None)

    # ── créer : tout se passe bien ───────────────────────────────────────
    g, suivis = monde()
    r = lv.creer_pour(TW, "u1", "yazid", manager="YAZID")
    check("lien créé, 50/50 posé", r.get("ok") and (r.get("variante") or {}).get("ok"), r)
    check("… à une adresse SANS prénom (« angelyy », pas « emycute »)",
          r.get("shortcode") == SC1 and "emy" not in SC1, r.get("shortcode"))
    check("deux trackings au même nom : Emy (créatrice de la config) puis Seren (3867)",
          suivis == [("Twitter VA 27 @yazid", None), ("Twitter VA 27 @yazid", 3867)], suivis)
    check("… dans cet ordre : tracking Emy, lien du VA, PUIS tracking Seren",
          [s[0] for s in SEQ[:3]] == ["mypuls", "gms", "mypuls"] and SEQ[2][1] == 3867, SEQ)
    dup = g.de("duplicate")
    check("copie temporaire : le gabarit Twitter, vers le tracking Seren, dans EMY TWITTER",
          len(dup) == 2 and dup[1][1] == GABARIT_TW and dup[1][4] == SEREN
          and dup[1][5] == EMY_TWITTER and dup[1][2].startswith("abtmp"), dup)
    ab = g.de("ab")
    check("A/B posé sur le lien du VA, source = la copie, 50 %, « Seren »",
          ab == [("ab", f"lnk_{SC1}", f"lnk_{dup[1][2]}", EMY_TWITTER, 50, "Seren")], ab)
    check("… et la copie temporaire supprimée", g.de("delete") == [("delete", f"lnk_{dup[1][2]}")],
          g.de("delete"))
    fv = lv.lien_de(TW, "u1").get("variante") or {}
    check("fiche : variante posée, tracking Seren et son code notés",
          fv.get("posee") is True and fv.get("tracking") == SEREN and fv.get("code") == "c201"
          and fv.get("creator_id") == 3867, fv)
    check("le tracking principal reste celui d'Emy",
          lv.lien_de(TW, "u1").get("tracking") == "https://onlyfans.com/emy.brw/c55")
    r2 = lv.poser_variante(TW, "u1")
    check("reposer un 50/50 déjà posé : rien de refait", r2.get("deja") and len(g.de("ab")) == 1, r2)

    # ── le podium voit la moitié Seren ───────────────────────────────────
    tv = lv.trackings_variantes()
    check("trackings des variantes : par identifiant SANS « lnk_ »", tv == {SC1: [SEREN]}, tv)
    ts = pod.trackings_du_lien({"id": f"lnk_{SC1}", "url": "https://onlyfans.com/emy.brw/c55"})
    check("podium : le lien porte ses deux trackings, Emy et Seren",
          ts == ["emy.brw/c55", "seren.vale/c201"], ts)
    ts2 = pod.trackings_du_lien({"id": "lnk_autre", "url": "https://onlyfans.com/emy.brw/c9"})
    check("… un autre lien, le sien seulement", ts2 == ["emy.brw/c9"], ts2)

    # ── cookie refusé ────────────────────────────────────────────────────
    g, suivis = monde()
    g.ab = {"ok": False, "cookie": True, "error": "cookie de session GetMySocial refusé : à recoller"}
    r = lv.creer_pour(TW, "u2", "bryan", manager="YAZID")
    var = r.get("variante") or {}
    check("cookie refusé : le lien est créé quand même", r.get("ok") and r.get("public_url"), r)
    check("… le 50/50 est dit non posé, à cause du cookie",
          var.get("ok") is False and var.get("cookie") is True and "cookie" in var.get("erreur", ""), var)
    check("… la copie temporaire est supprimée malgré l'échec", len(g.de("delete")) == 1, g.de("delete"))
    fv = lv.lien_de(TW, "u2").get("variante") or {}
    check("… le tracking Seren est noté (MyPuls ne le supprimera jamais)",
          fv.get("tracking") == SEREN and fv.get("posee") is False and fv.get("erreur"), fv)
    check("… et rien au podium tant qu'il n'est pas posé", lv.trackings_variantes() == {})

    # ── reprise, anciens liens compris ───────────────────────────────────
    lv.PAUSE_VARIANTE_S = 0
    etat = json.loads(lv.ETAT_FICHIER.read_text())
    etat["liens"][f"{TW}:u0"] = {"pseudo": "ancien", "numero": 3, "shortcode": "emyold",
                                 "link_id": "lnk_emyold", "tracking": "https://onlyfans.com/emy.brw/c3"}
    etat["liens"][f"{TW}:u8"] = {"pseudo": "sanstracking", "numero": 8, "shortcode": "emyprov",
                                 "link_id": "lnk_emyprov", "tracking": ""}
    etat["liens"][f"{TW}:u9"] = {"pseudo": "coupe", "numero": 9, "shortcode": "emycoupe",
                                 "link_id": "lnk_emycoupe", "tracking": "https://onlyfans.com/emy.brw/c4",
                                 "actif": False}
    etat["liens"][f"{TH}:t1"] = {"pseudo": "threads", "numero": 61, "shortcode": "angelyy",
                                 "link_id": "lnk_angelyy", "tracking": ""}
    lv.ETAT_FICHIER.write_text(json.dumps(etat))
    check("en attente : le 50/50 en plan ET les anciens liens, pas le lien coupé ni Threads",
          lv.en_attente() == [f"{TW}:u0", f"{TW}:u2", f"{TW}:u8"], lv.en_attente())
    suivis.clear()
    g.appels.clear()
    g.ab = {"ok": True, "config": {}}
    b = lv.reprendre_variantes()
    check("reprise : les trois posés", sorted(b["poses"]) == ["ancien", "bryan", "sanstracking"]
          and not b["rates"], b)
    check("… le 50/50 en plan reprend SON tracking Seren noté (aucun nouveau pour lui)",
          ("Twitter VA 27 @bryan", 3867) not in suivis, suivis)
    check("… l'ancien lien reçoit son tracking Seren, à son nom",
          ("Twitter VA 3 @ancien", 3867) in suivis
          and (lv.lien_de(TW, "u0").get("variante") or {}).get("posee") is True, suivis)
    upd = [a for a in g.appels if a[0] == "update_link"]
    check("… le lien sans tracking reçoit d'abord son tracking Emy (rebranché), puis Seren",
          suivis.count(("Twitter VA 8 @sanstracking", None)) == 1
          and ("Twitter VA 8 @sanstracking", 3867) in suivis
          and upd and upd[0][1]["link_id"] == "lnk_emyprov"
          and lv.lien_de(TW, "u8").get("tracking") == "https://onlyfans.com/emy.brw/c55", (suivis, upd))
    check("… le lien coupé n'est pas touché", "variante" not in lv.lien_de(TW, "u9"))
    check("… posé, noté, et plus rien en attente",
          (lv.lien_de(TW, "u2").get("variante") or {}).get("posee") is True and lv.en_attente() == [],
          lv.en_attente())

    g, _s = monde(etat={"liens": {
        f"{TW}:a": {"pseudo": "a", "numero": 1, "shortcode": "x1", "link_id": "lnk_x1",
                    "tracking": "https://onlyfans.com/emy.brw/c1",
                    "variante": {"tracking": SEREN, "posee": False}},
        f"{TW}:b": {"pseudo": "b", "numero": 2, "shortcode": "x2", "link_id": "lnk_x2",
                    "tracking": "https://onlyfans.com/emy.brw/c2",
                    "variante": {"tracking": SEREN, "posee": False}}}})
    g.ab = {"ok": False, "cookie": True, "error": "cookie refusé"}
    b = lv.reprendre_variantes()
    check("reprise : arrêt au premier refus de cookie (le suivant échouerait pareil)",
          len(g.de("ab")) == 1 and b.get("cookie") and len(b["rates"]) == 1, (g.de("ab"), b))
    b = lv.reprendre_variantes()
    check("… et ce cookie-là n'est plus essayé (rien d'envoyé au passage suivant)",
          len(g.de("ab")) == 1 and b.get("cookie"), (g.de("ab"), b))
    g.cookie = "authToken=d.e.f"
    g.ab = {"ok": True, "config": {}}
    b = lv.reprendre_variantes()
    check("… un nouveau cookie collé relance tout", sorted(b["poses"]) == ["a", "b"], b)
    g, _s = monde(etat={"liens": {f"{TW}:a": {"pseudo": "a", "numero": 1, "shortcode": "x1",
                                               "link_id": "lnk_x1", "tracking": "https://onlyfans.com/emy.brw/c1"}}})
    g.echeance = time.time() - 60
    b = lv.reprendre_variantes()
    check("cookie échu : rien n'est tenté", b.get("cookie") and not g.appels and not _s, (b, g.appels))
    g.cookie = ""
    g.echeance = None
    b = lv.reprendre_variantes()
    check("pas de cookie : rien non plus", b.get("cookie") and not g.appels, b)

    # ── garde-fous MyPuls ────────────────────────────────────────────────
    g, suivis = monde(etat={"liens": {f"{TW}:a": {"pseudo": "a", "numero": 1, "shortcode": "x1",
                                                   "link_id": "lnk_x1",
                                                   "tracking": "https://onlyfans.com/emy.brw/c1"}}})
    lv.creer_tracking = lambda nom, creator_id=None: (suivis.append((nom, creator_id)) or
                                                      {"ok": False, "erreur": "créé, mais introuvable à la relecture"})
    b = lv.reprendre_variantes()
    fv = lv.lien_de(TW, "a").get("variante") or {}
    check("MyPuls ambigu (peut-être créé) : à vérifier à la main",
          fv.get("a_verifier") is True and b["a_verifier"] and not b["poses"], (fv, b))
    lv.reprendre_variantes()
    check("… et jamais réessayé (un second tracking resterait à vie)", len(suivis) == 1, suivis)
    g, suivis = monde(etat={"liens": {f"{TW}:a": {"pseudo": "a", "numero": 1, "shortcode": "x1",
                                                   "link_id": "lnk_x1",
                                                   "tracking": "https://onlyfans.com/emy.brw/c1"}}})
    lv.creer_tracking = lambda nom, creator_id=None: (suivis.append(nom) or
                                                      {"ok": False, "refuse": True, "erreur": "MyPuls a refusé (HTTP 422)"})
    lv.reprendre_variantes()
    lv.reprendre_variantes()
    check("MyPuls refuse net : rien de créé, réessayé ensuite",
          len(suivis) == 2 and not (lv.lien_de(TW, "a").get("variante") or {}).get("a_verifier"), suivis)
    g, _s = monde(etat={"liens": {f"{TW}:a": {"pseudo": "a", "numero": 1, "shortcode": "x1",
                                               "link_id": "lnk_x1", "tracking": "https://onlyfans.com/emy.brw/c1",
                                               "variante": {"tracking": SEREN, "posee": False}}}})
    g.ab = {"ok": False, "error": "HTTP 404 : link not found"}
    for _ in range(4):
        lv.reprendre_variantes()
    check("un échec qui n'est pas le cookie : trois essais, puis la main",
          len(g.de("ab")) == lv.ESSAIS_VARIANTE
          and (lv.lien_de(TW, "a").get("variante") or {}).get("a_verifier") is True, g.de("ab"))

    # ── copie temporaire mal adressée ────────────────────────────────────
    g, _s = monde()
    g.adresse_prise = False
    r = lv.creer_pour(TW, "u3", "carl")
    var = r.get("variante") or {}
    check("adresse de la copie pas prise : AUCUN A/B (il enverrait chez Emy)",
          r.get("ok") and var.get("ok") is False and not g.de("ab")
          and "pointe sur" in var.get("erreur", ""), (r, g.de("ab")))
    check("… copie supprimée quand même", len(g.de("delete")) == 1, g.de("delete"))

    # ── MyPuls muet pour Seren ───────────────────────────────────────────
    g, suivis = monde(mypuls_ok=False)
    r = lv.creer_pour(TW, "u4", "dino")
    var = r.get("variante") or {}
    check("MyPuls refuse le tracking Seren : lien créé, 50/50 non posé, la raison dite",
          r.get("ok") and var.get("ok") is False and "MyPuls (Seren)" in var.get("erreur", "")
          and len(g.de("duplicate")) == 1 and not g.de("ab"), (r, g.appels))
    fv = lv.lien_de(TW, "u4").get("variante") or {}
    check("… noté sans tracking, en attente", fv.get("posee") is False and not fv.get("tracking"), fv)

    # ── sans variante : comme avant ──────────────────────────────────────
    g, suivis = monde(config=dict(CONFIG, variante={}))
    r = lv.creer_pour(TW, "u5", "emma")
    check("variante éteinte : un seul tracking, aucun A/B, pas de clé « variante »",
          r.get("ok") and r.get("variante") is None and len(suivis) == 1 and not g.de("ab")
          and "variante" not in lv.lien_de(TW, "u5"), (r, suivis))

    # ── gms.poser_ab_testing ─────────────────────────────────────────────
    envois = []

    class Rep:
        def __init__(self, code, corps, json_ok=True):
            self.status_code, self._c, self._j = code, corps, json_ok

        def json(self):
            if not self._j:
                raise ValueError("pas du JSON")
            return self._c

    reponse = {"r": None}

    def faux_post(url, **kw):
        envois.append((url, kw))
        return reponse["r"]
    vrai_gms.requests.post = faux_post
    vrai_gms.get_session_cookie = lambda: "authToken=a.b.c"
    reponse["r"] = Rep(200, {"success": True, "config": {
        "enabled": True, "controlWeight": 50, "variants": [{"variantId": "v1", "weight": 50}]}})
    rr = vrai_gms.poser_ab_testing("lnk_6acf00", "lnk_6acf01", "tm_6ab46e", 50, "Seren")
    url, kw = envois[-1]
    corps = kw.get("json") or {}
    check("API privée : POST /api/links/ab-testing/<id>/save, identifiants sans préfixe",
          rr.get("ok") and url.endswith("/api/links/ab-testing/6acf00/save")
          and corps.get("teamId") == "6ab46e" and corps["variants"][0]["sourceLinkId"] == "6acf01"
          and corps["variants"][0]["variantId"] is None, (rr, url, corps))
    check("… 50 / 50, A/B activé, cookie envoyé, sans suivre de redirection",
          corps.get("controlWeight") == 50 and corps["variants"][0]["weight"] == 50
          and corps.get("enabled") is True and kw["headers"].get("Cookie") == "authToken=a.b.c"
          and kw.get("allow_redirects") is False, kw)
    reponse["r"] = Rep(302, {}, json_ok=False)
    rr = vrai_gms.poser_ab_testing("lnk_a", "lnk_b", "tm_c")
    check("redirection vers la connexion : cookie à recoller", not rr.get("ok") and rr.get("cookie"), rr)
    reponse["r"] = Rep(200, "<html>", json_ok=False)
    rr = vrai_gms.poser_ab_testing("lnk_a", "lnk_b", "tm_c")
    check("une page HTML au lieu du JSON : cookie aussi", not rr.get("ok") and rr.get("cookie"), rr)
    reponse["r"] = Rep(200, {"success": True, "config": {"enabled": False, "variants": []}})
    rr = vrai_gms.poser_ab_testing("lnk_a", "lnk_b", "tm_c")
    check("« enregistré » mais relu sans variante : échec, pas un faux 50/50",
          not rr.get("ok") and not rr.get("cookie"), rr)
    vrai_gms.get_session_cookie = lambda: ""
    n = len(envois)
    rr = vrai_gms.poser_ab_testing("lnk_a", "lnk_b", "tm_c")
    check("sans cookie : rien n'est envoyé", not rr.get("ok") and rr.get("cookie") and len(envois) == n, rr)

    # ── le cookie ────────────────────────────────────────────────────────
    def jeton(exp):
        seg = base64.urlsafe_b64encode(json.dumps({"id": "u", "exp": exp}).encode()).decode().rstrip("=")
        return f"eyJhbGciOiJIUzI1NiJ9.{seg}.signature"
    j = jeton(int(time.time()) + 10 * 86400)
    check("la valeur d'authToken seule devient « authToken=… »",
          vrai_gms.normaliser_cookie("  " + j + " ") == f"authToken={j}")
    check("l'en-tête entier reste tel quel (sans « Cookie: »)",
          vrai_gms.normaliser_cookie(f"Cookie: _ga=1; authToken={j}; x=2") == f"_ga=1; authToken={j}; x=2")
    exp = vrai_gms.cookie_expiration(f"_ga=1; authToken={j}; x=2")
    check("échéance lue dans le jeton", exp and abs(exp - (time.time() + 10 * 86400)) < 5, exp)
    check("… illisible : None, pas d'exception", vrai_gms.cookie_expiration("authToken=pasunjwt") is None)

    # ── le message au manager ────────────────────────────────────────────
    postes, suites = [], []
    tk._EN_FOND = lambda f: f()
    tk._suite = lambda jeton_, texte, p=None: suites.append(texte)
    tk.identifiant = lambda gid, uid: "pseudo_va"
    tk.nom_manager = lambda gid, uid: "YAZID"

    def faux_api(methode, chemin, **kw):
        postes.append((methode, chemin, kw.get("json")))
        return 200, {}
    tk._api = faux_api
    g, _s = monde()
    tk._creer_lien(TW, "u6", "m1", {"token": "t", "channel_id": "s6"})
    check("manager : « 50/50 avec Seren ✓ »", suites and "50/50 avec Seren ✓" in suites[0], suites)
    suites.clear()
    g, _s = monde()
    g.ab = {"ok": False, "cookie": True, "error": "cookie de session GetMySocial refusé"}
    tk._creer_lien(TW, "u7", "m1", {"token": "t", "channel_id": "s7"})
    check("cookie refusé : le manager sait que tout part sur Emy, et quoi faire",
          suites and "Seren pas encore branché" in suites[0] and "Recolle le cookie" in suites[0]
          and "getmysocial.com/" in suites[0], suites)
finally:
    for _k, _v in _SAUVE_LV.items():
        setattr(lv, _k, _v)
    for _k, _v in _SAUVE_TK.items():
        setattr(tk, _k, _v)
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS
    else:
        sys.modules.pop("gms", None)
    vrai_gms.requests.post = _SAUVE_REQ_POST
    vrai_gms.get_session_cookie = _SAUVE_COOKIE
    lv._VARIANTES_LUES.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
