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

    pris_sc = ()

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "update_link" and "shortcode" in args:
            if args["shortcode"] in self.pris_sc:
                return {"ok": False, "error": "409 shortcode_taken"}
            return {"ok": True, "data": {"id": args["link_id"], "shortcode": args["shortcode"]}}
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
    # Threads : ses trackings s'ouvrent par un patch local du VPS
    # (99-threads-mypuls-20261015) ; le dépôt, lui, n'en a pas
    check("Threads : pas de variante dans le dépôt (le patch du VPS l'ouvre)",
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

    # ── changer l'adresse des liens déjà donnés ──────────────────────────
    # « change le lien pour ceux qui sont déjà et remets le bon » (14/10/2026)
    g, _s = monde(etat={"liens": {f"{TW}:a": {"pseudo": "abdoul_9684", "numero": 31,
                                               "shortcode": "emycute", "link_id": "lnk_31",
                                               "public_url": "https://getmysocial.com/emycute"}}})
    nom31 = "Twitter VA 31 @abdoul_9684"
    g.pris_sc = (lv.mots_sans_prenom(nom31, 0),)
    r = lv.changer_adresse(TW, "a")
    neuf = lv.mots_sans_prenom(nom31, 1)
    upd = [x for x in g.appels if x[0] == "update_link"]
    check("adresse changée : le MÊME lien renommé, la suivante si la première est prise",
          r.get("ok") and r.get("public_url") == f"https://getmysocial.com/{neuf}"
          and len(upd) == 2 and all(x[1]["link_id"] == "lnk_31" and x[1]["team_id"] == EMY_TWITTER
                                    for x in upd) and "emy" not in neuf, (r, upd))
    f = lv.lien_de(TW, "a")
    check("… fiche à jour, l'ancienne adresse gardée",
          f.get("shortcode") == neuf and f.get("public_url").endswith("/" + neuf)
          and f.get("anciennes_adresses") == ["emycute"] and f.get("link_id") == "lnk_31", f)
    n = len(g.appels)
    r = lv.changer_adresse(TW, "a")
    check("… un second passage ne renomme plus rien", r.get("deja") and len(g.appels) == n, r)
    # 15/10/2026, VA 71 : les douze premiers mots seuls étaient TOUS pris
    g, _s = monde(etat={"liens": {f"{TW}:b": {"pseudo": "john088612", "numero": 71,
                                               "shortcode": "emycute", "link_id": "lnk_71"}}})
    nom71 = "Twitter VA 71 @john088612"
    g.pris_sc = tuple(lv.mots_sans_prenom(nom71, i) for i in range(len(lv.MOTS_THREADS) + 2))
    r = lv.changer_adresse(TW, "b")
    check("tous les mots seuls pris : une paire de mots (« angelpearlyy »), pas un abandon",
          r.get("ok") and r["public_url"].endswith("/" + lv.mots_sans_prenom(nom71, len(lv.MOTS_THREADS) + 2)),
          r)
    g, _s = monde()
    g.pris = set(lv.mots_sans_prenom("Twitter VA 27 @yazid", i) for i in range(20))
    _dup = g.duplicate_link

    def _dup_pris(source, sc, nom, url, equipe):
        if sc in g.pris:
            g.appels.append(("duplicate", source, sc, nom, url, equipe))
            return {"ok": False, "error": "409 shortcode_taken"}
        return _dup(source, sc, nom, url, equipe)
    g.duplicate_link = _dup_pris
    r = lv.creer_pour(TW, "u20", "yazid")
    check("… et pareil à la création : plus de douze essais",
          r.get("ok") and r.get("shortcode") == lv.mots_sans_prenom("Twitter VA 27 @yazid", 20), r)
    g, _s = monde(config=dict(CONFIG, sans_prenom=False),
                  etat={"liens": {f"{TW}:a": {"pseudo": "x", "numero": 1, "shortcode": "emycute",
                                               "link_id": "lnk_1"}}})
    r = lv.changer_adresse(TW, "a")
    check("règle éteinte (« sans_prenom » : false) : rien n'est renommé",
          not r.get("ok") and not g.appels, (r, g.appels))

    # ── le menu du VA donne l'adresse de SA fiche ────────────────────────
    # Le bouton « Demander un lien » avait son propre registre : après le
    # renommage du 14/10, il aurait redonné l'ancienne adresse, morte.
    import asyncio
    import cogs.user as cu
    g, _s = monde(etat={"liens": {f"{TW}:42": {"pseudo": "abdoul_9684", "numero": 31,
                                                "shortcode": "bbyy", "link_id": "lnk_31",
                                                "public_url": "https://getmysocial.com/bbyy"}}})
    envoyes = []

    class _Rep:
        async def defer(self, **k):
            pass

        async def send_message(self, *a, **k):
            envoyes.append(("rep", a, k))

    class _Suite:
        async def send(self, *a, **k):
            envoyes.append(("suite", a, k))

    class _Inter:
        guild = types.SimpleNamespace(id=int(TW), roles=[])
        user = types.SimpleNamespace(id=42, name="abdoul_9684")
        response = _Rep()
        followup = _Suite()
    _sauve_cu = {k: getattr(cu, k) for k in ("_menu_feature_check", "_link_identity",
                                             "_menu_outils_ici", "_lr_existing")}
    try:
        cu._menu_feature_check = lambda i, f: True
        cu._link_identity = lambda g_, u: "emy"
        cu._menu_outils_ici = lambda g_: False
        cu._lr_existing = lambda u: {"g": 1, "url": "https://getmysocial.com/emycute"}
        asyncio.run(cu.UserCog.request_link(None, _Inter()))
    finally:
        for _k, _v in _sauve_cu.items():
            setattr(cu, _k, _v)
    txt = " ".join(str(x[1]) for x in envoyes)
    check("menu VA : « Demander un lien » donne l'adresse de la fiche, pas l'ancienne du registre",
          "getmysocial.com/bbyy" in txt and "emycute" not in txt, envoyes)

    # ── « Mes subs » : aujourd'hui, la période, la précédente ────────────
    # « il check son nombre de subs : today, période et période précédente »,
    # « pour Twitter, IG et Threads ; pour IG MYM et OF ; pour Threads Emy et
    # Seren », « le VA reçoit direct le truc additionné » (15/10/2026)
    import datetime as _dt
    import subs_va as sv
    V = {("2026-10-15", "2026-10-15"): {"emy.brw/c6": 2, "seren.vale/c196": 1, "amelia/c3": 4},
         ("2026-10-01", "2026-10-15"): {"emy.brw/c6": 10, "seren.vale/c196": 5, "amelia/c3": 7},
         # MyPuls rend TOUS les trackings pour une période, même ceux créés
         # après (à 0) : Seren y est, à 0
         ("2026-09-16", "2026-09-30"): {"emy.brw/c6": 20, "seren.vale/c196": 0, "amelia/c3": 1}}
    panne = {"oui": False}

    def faux_mp(du, au, forcer=False):
        if panne["oui"]:
            return None, "MyPuls muet"
        # des visites dix fois plus nombreuses : on compte les ABONNÉS ; les
        # noms MyPuls portent le pseudo du VA (« uniquement son tracking avec
        # son nom »)
        NOMS = {"emy.brw/c6": "Twitter VA 31 @abdoul_9684",
                "seren.vale/c196": "Twitter VA 31 @abdoul_9684", "amelia/c3": "Lola_VA_2_adh040"}
        return {t: {"visites": n * 10, "total": n * 10, "subs": n, "nom": NOMS.get(t, "")}
                for t, n in V.get((du, au), {}).items()}, ""
    _sauve_pod = {k: getattr(pod, k) for k in ("_lire_mypuls", "_aujourdhui")}
    _sauve_sv = {k: getattr(sv, k) for k in ("MYM_FICHIER",)}
    import liens_fr as lf
    _sauve_lf = {k: getattr(lf, k) for k in ("ETAT",)}
    try:
        pod._lire_mypuls = faux_mp
        pod._aujourdhui = lambda: _dt.date(2026, 10, 15)
        sv.MYM_FICHIER = TMP / "mym_conversions.json"
        lf.ETAT = TMP / "liens_va_fr.json"
        J = _dt.date(2026, 10, 15)
        # Twitter (et Threads) : le tracking Emy du lien + celui de sa variante
        g, _s = monde(etat={"liens": {
            f"{TW}:42": {"pseudo": "abdoul_9684", "numero": 31, "shortcode": "bbyy",
                         "tracking": "https://onlyfans.com/emy.brw/c6",
                         "variante": {"tracking": "https://onlyfans.com/seren.vale/c196", "posee": True}},
            f"{TH}:43": {"pseudo": "abdoul_9684", "numero": 31, "shortcode": "angelyy",
                         "tracking": "https://onlyfans.com/emy.brw/c6"}}})
        check("trackings d'un VA Twitter : Emy et sa variante Seren",
              sv.trackings_du_va(TW, 42) == [("of", "https://onlyfans.com/emy.brw/c6"),
                                            ("of", "https://onlyfans.com/seren.vale/c196")],
              sv.trackings_du_va(TW, 42))
        r = sv.subs_du_va(TW, 42, J)
        check("Twitter : Emy + Seren ADDITIONNÉS, des abonnés pas des visites (3 · 15 · 20)",
              (r["aujourdhui"]["n"], r["periode"]["n"], r["precedente"]["n"]) == (3, 15, 20), r)
        check("… périodes : la quinzaine en cours, la précédente",
              (r["periode"]["du"], r["periode"]["au"], r["precedente"]["du"], r["precedente"]["au"])
              == ("2026-10-01", "2026-10-15", "2026-09-16", "2026-09-30"), r)
        check("Threads : le même compte, sur sa fiche à lui",
              sv.subs_du_va(TH, 43, J)["periode"]["n"] == 10 and sv.subs_du_va(TH, 42, J)["trackings"] == 0)
        # Va IG : OF à l'API, MYM au relevé de la page
        lf.ETAT.write_text(json.dumps({"liens": {
            "44:amelia": {"public_url": "https://getmysocial.com/ameliabby",
                          "trackings": {"of": "https://onlyfans.com/amelia/c3",
                                        "mym": "https://mym.fans/app/t/AAA"}},
            "45:amelia": {"trackings": {"mym": "https://mym.fans/app/t/BBB"}}}}))
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time(), "trackings": {
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1, "2026-10-03": 2, "2026-09-20": 5}}}}))
        r = sv.subs_du_va(sv.VA_IG_ID, 44, J)
        check("Va IG : OF + MYM additionnés (5 · 10 · 6)",
              (r["aujourdhui"]["n"], r["periode"]["n"], r["precedente"]["n"]) == (5, 10, 6), r)
        r = sv.subs_du_va(sv.VA_IG_ID, 45, J)
        check("… un tracking MYM pas encore relevé : « pas lisible », pas un zéro",
              r["periode"]["n"] is None, r)
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time() - 7 * 3600, "trackings": {
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1}}}}))
        check("… un relevé MYM de plus de six heures : « pas lisible » non plus",
              sv.subs_du_va(sv.VA_IG_ID, 44, J)["aujourdhui"]["n"] is None)
        # adh040 : son bouton MYM resté sur le tracking COMMUN « VA_MARKETING »
        # (« avant j'avais pas de tracking link, c'est juste un truc en
        # général ; faut juste prendre le tracking link actuel », 15/10/2026)
        lf.ETAT.write_text(json.dumps({"liens": {"46:lola": {
            "pseudo": "adh040", "trackings": {"of": "https://onlyfans.com/amelia/c3",
                                              "mym": "https://mym.fans/app/t/COMMUN"}}}}))
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time(), "trackings": {
            "https://mym.fans/app/t/COMMUN": {"nom": "VA_MARKETING",
                                              "jours": {"2026-10-03": 9, "2026-09-20": 45}},
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1}}}}))
        r = sv.subs_du_va(sv.VA_IG_ID, 46, J)
        check("tracking commun (nom sans le pseudo du VA) : pas compté, seul le sien l'est (7 · 1)",
              (r["periode"]["n"], r["precedente"]["n"]) == (7, 1)
              and r["communs"] == ["https://mym.fans/app/t/COMMUN"], r)
        check("… et le message le dit, en une ligne",
              "tracking commun" in sv.texte(sv.VA_IG_ID, 46, J))
        check("UNIQUEMENT son tracking avec son nom : « Lola_VA_2_adh040 » oui, « VA_MARKETING » ou sans nom non",
              sv._a_lui("Lola_VA_2_adh040", "adh040") and sv._a_lui("Twitter VA 31 @abdoul_9684", "abdoul_9684")
              and not sv._a_lui("VA_MARKETING", "adh040") and not sv._a_lui("", "adh040"))
        # la réparation d'un lien Va IG retrouve un tracking MYM déjà créé à
        # son nom (l'API ne rend pas MYM ; MYM refuse un 2e au même nom, HTTP 500)
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time(), "trackings": {
            "https://mym.fans/app/t/hmyayn": {"createur": 1116, "nom": "Lola_VA_2_adh040", "jours": {}},
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1}}}}))
        check("réparation Va IG : tracking MYM déjà créé au nom du VA, retrouvé dans le relevé",
              lf._releve_mym_au_nom("Lola_VA_2_adh040", 1116) == "https://mym.fans/app/t/hmyayn"
              and lf._releve_mym_au_nom("Lola_VA_2_adh040", 769) == ""
              and lf._releve_mym_au_nom("Lola_VA_3_autre", 1116) == "")
        # ── le classement de la quinzaine de Va IG, aux vrais abonnés ──────
        # « les vrais abonnés » ; « eux ils voient pas les pseudos, moi si »
        lf.ETAT.write_text(json.dumps({"liens": {
            "46:lola": {"pseudo": "adh040", "numero": 2,
                        "trackings": {"of": "https://onlyfans.com/amelia/c3",
                                      "mym": "https://mym.fans/app/t/COMMUN"}},
            "47:amelia": {"pseudo": "york", "numero": 43,
                          "trackings": {"mym": "https://mym.fans/app/t/YORK"}}}}))
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time(), "trackings": {
            "https://mym.fans/app/t/COMMUN": {"nom": "VA_MARKETING", "jours": {"2026-10-03": 9}},
            "https://mym.fans/app/t/YORK": {"nom": "Amelia_VA_43_york", "createur": 769,
                                            "jours": {"2026-10-02": 11, "2026-09-01": 4}},
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1}}}}))
        cl = pod.classement(_dt.date(2026, 10, 1), J, gid=sv.VA_IG_ID, mesure="abonnes")
        check("quinzaine Va IG : les ABONNÉS (MYM 11, OF 7), le tracking commun écarté, du plus fort",
              [(x["va"], x["clics"]) for x in cl["lignes"]] == [("Amelia VA 43", 11), ("Lola VA 2", 7)]
              and cl["source"] == "abonnes" and not cl["illisibles"], cl)
        check("… le profil de Va IG la demande pour sa quinzaine (le podium de la semaine non)",
              pod.SERVEURS[pod.VA_IG_ID].get("mesure_subs") == "abonnes"
              and pod.SERVEURS[pod.VA_IG_ID].get("mesure") != "abonnes")
        pages = pod.pages_subs(cl, _dt.date(2026, 10, 1), _dt.date(2026, 10, 15), {}, gid=sv.VA_IG_ID)
        desc = pages[0]["description"]
        check("… en-tête « Abonnés OF + MYM », numéros Instagram, aucun pseudo",
              "Abonnés **OF + MYM**" in desc and "Instagram VA" in desc
              and "adh040" not in desc and "york" not in desc and "Clics" not in desc, desc[:300])
        _vus_tot = {}
        _fa = lambda du, au, forcer=False: ({"amelia/c3": {"visites": 1, "total": 1, "subs": 1,
                                                          "subs_total": 40, "nom": "Lola_VA_2_adh040"}}, "")
        pod._lire_mypuls = _fa
        tot = sv.totaux_va_ig()
        pod._lire_mypuls = faux_mp
        check("… all-time : OF au compteur MyPuls (40), MYM tous les jours relevés (15), commun écarté",
              tot == {"Lola VA 2": 40, "Amelia VA 43": 15}, tot)
        b = pod._boutons(sv.VA_IG_ID, True, pseudos=True)["components"][0]["components"]
        check("bouton « 👀 Pseudos » sous la quinzaine de Va IG, à côté de « 🔄 »",
              [c["custom_id"] for c in b] == [pod.BOUTON_MAJ, pod.BOUTON_PSEUDOS]
              and [c["custom_id"] for c in pod._boutons(sv.VA_IG_ID, True)["components"][0]["components"]]
              == [pod.BOUTON_MAJ] and pod._boutons(TW, True, pseudos=True) == {}, b)
        txt = pod.texte_pseudos(sv.VA_IG_ID, J)
        check("… réponse au staff : numéro Instagram, PSEUDO, model, abonnés",
              "**york** (Amelia VA 43) — 11 subs" in txt and "**adh040** (Lola VA 2) — 7 subs" in txt
              and "Instagram VA" in txt, txt)
        suites3 = []
        _sauve_pt = {k: getattr(pod, k) for k in ("_staff", "_en_fond")}
        _sauve_tk3 = tk._suite
        try:
            pod._en_fond = lambda f: f()
            tk._suite = lambda jeton_, texte, p=None: suites3.append(texte)
            clic = {"type": 3, "guild_id": sv.VA_IG_ID, "token": "t",
                    "data": {"custom_id": pod.BOUTON_PSEUDOS}, "member": {"user": {"id": "1"}}}
            pod._staff = lambda p_: False
            r = pod.traiter(clic)
            check("… un VA qui clique : refusé, rien calculé",
                  r.get("type") == 4 and "staff" in r["data"]["content"] and not suites3, r)
            pod._staff = lambda p_: True
            r = pod.traiter(clic)
            check("… le staff : réponse privée différée, avec les pseudos",
                  r == {"type": 5, "data": {"flags": 64}} and suites3 and "york" in suites3[0], (r, suites3))
        finally:
            for _k, _v in _sauve_pt.items():
                setattr(pod, _k, _v)
            tk._suite = _sauve_tk3
        sv.MYM_FICHIER.write_text(json.dumps({"releve": time.time(), "trackings": {
            "https://mym.fans/app/t/AAA": {"jours": {"2026-10-15": 1}}}}))
        panne["oui"] = True
        check("MyPuls muet : « pas lisible », jamais un zéro inventé",
              sv.subs_du_va(TW, 42, J)["periode"]["n"] is None)
        panne["oui"] = False
        txt = cu._mes_subs_texte(types.SimpleNamespace(id=int(TW)), types.SimpleNamespace(id=42))
        check("message du VA : trois totaux avec les dates, sans détail ni montant",
              txt.startswith("📈 **Tes subs**") and "Aujourd'hui : **" in txt
              and "Cette période (du 01/10 au 15/10) : **15**" in txt
              and "Période précédente (du 16/09 au 30/09) : **20**" in txt
              and "Emy" not in txt and "Seren" not in txt and "$" not in txt and "€" not in txt, txt)
        check("les trois serveurs, et eux seuls",
              all(cu._subs_ici(types.SimpleNamespace(id=int(x))) for x in (TW, TH, sv.VA_IG_ID))
              and not cu._subs_ici(types.SimpleNamespace(id=123)))
        check("le bouton : menu complet, menu Threads, ligne épinglée de Va IG",
              any(b.cle == "subs" for _t, bs in cu._MENU_VA_DISPOSITION if isinstance(bs, tuple)
                  for b in bs if hasattr(b, "cle")) and "cmenu:subs" in cu._THREADS_MENU
              and "subs" in cu._LIGNE_SUIVI_CLES and hasattr(cu.ContentMenuView, "_clic_subs")
              and cu.LIGNE_DISPOSITION == "2026-10-15-mes-subs")

        # ── le relevé MYM : la page MyPuls, sous le verrou de bascule ───
        import mypuls as _mp
        verrou_tenu = []

        class _Rep:
            def __init__(self, texte="", js=None):
                self.text, self._js = texte, js

            def json(self):
                return self._js

        class _Sess:
            def get(self, url, **kw):
                verrou_tenu.append(_mp._OF_SWITCH_LOCK._is_owned())
                if "/tracking-stats/data" in url:
                    return _Rep(js={"labels": ["2026-10-14", "2026-10-15"], "daily": {
                        "0": {"label": "Amelia_VA_46_x", "linkId": 8924,
                              "data": [{"conversions": 2, "clicks": 9}, {"conversions": 1}]},
                        "1": {"label": "Instagram", "linkId": 137, "data": [None, {"conversions": 5}]}}})
                if "/tracking-stats/" in url:
                    return _Rep(texte='<tr id="row-link-8924"> <td>Amelia_VA_46_x</td> '
                                      '<button data-url="https://mym.fans/app/t/hn0d"></button></tr>')
                return _Rep()
        _sauve_mp = {k: getattr(_mp, k) for k in ("_make_session", "_save_rotated_cookies")}
        try:
            _mp._make_session = lambda: _Sess()
            _mp._save_rotated_cookies = lambda s: None
            b = sv.releve_mym([769])
        finally:
            for _k, _v in _sauve_mp.items():
                setattr(_mp, _k, _v)
        cache = json.loads(sv.MYM_FICHIER.read_text())
        check("relevé MYM : chaque tracking du tableau, ses conversions jour par jour",
              b.get("ok") and cache["trackings"]["https://mym.fans/app/t/hn0d"]["jours"]
              == {"2026-10-14": 2, "2026-10-15": 1}, (b, cache))
        check("… une série sans ligne au tableau (pas un tracking connu) est laissée",
              not any("Instagram" == v.get("nom") for v in cache["trackings"].values()), cache)
        check("… l'ancien relevé d'un tracking non relu cette fois est gardé",
              "https://mym.fans/app/t/AAA" in cache["trackings"], list(cache["trackings"]))
        check("… et TOUT se fait sous le verrou de bascule de MyPuls",
              verrou_tenu and all(verrou_tenu), verrou_tenu)
        # la création de tracking aussi, enveloppée sans toucher son corps
        # (les patchs du VPS le réécrivent)
        tenu = []
        _env = lv._sous_bascule(lambda *a, **k: tenu.append(_mp._OF_SWITCH_LOCK._is_owned()) or {"ok": True})
        _env("x", 1)
        check("création de tracking sous le même verrou (enveloppe _sous_bascule)",
              tenu == [True] and hasattr(_SAUVE_LV["creer_tracking"], "brut"), tenu)
    finally:
        for _k, _v in _sauve_pod.items():
            setattr(pod, _k, _v)
        for _k, _v in _sauve_sv.items():
            setattr(sv, _k, _v)
        for _k, _v in _sauve_lf.items():
            setattr(lf, _k, _v)

    # ── la relecture MyPuls lit le NOM de chaque tracking ────────────────
    # 15/10/2026 : la garde du VPS ne retient que le tracking au bon nom ; le
    # nom restait vide, et chaque création finissait « introuvable » (VA 75, 76)
    PAGE = ('<tr id="row-link-8924"> <td class="ps-4"> <div class="fw-bold">Twitter VA 76 @ghost_me0436</div>'
            '<div class="small text-muted">Créé le 15/10/2026</div> </td> <td> <span class="url-pill">'
            '<span class="text-truncate url-text">https://onlyfans.com/emy.brw/c84</span></span></td></tr>'
            '<tr id="row-link-9"> <td> <div class="fw-bold">Amelia_VA_46_x</div></td><td>'
            '<button data-url="https://mym.fans/app/t/hn0d"></button></td></tr>'
            '<p>https://onlyfans.com/emy.brw/c9</p>')
    lus = lv._tracking_de(None, PAGE)
    check("relecture : le nom de chaque tracking, OF comme MYM, depuis sa ligne du tableau",
          {"code": "c84", "nom": "Twitter VA 76 @ghost_me0436", "url": "https://onlyfans.com/emy.brw/c84"} in lus
          and any(x["nom"] == "Amelia_VA_46_x" and x["url"] == "https://mym.fans/app/t/hn0d" for x in lus)
          and any(x["code"] == "c9" and x["nom"] == "" for x in lus), lus)

    # ── un tracking déjà créé au nom du VA est repris, pas doublé ────────────
    g, suivis = monde()
    _sauve_ex = lv._tracking_existant
    try:
        lv._tracking_existant = lambda nom, cid: ({"url": "https://onlyfans.com/emy.brw/c84", "code": "c84"}
                                                  if (nom, cid) == ("Twitter VA 27 @yazid", 3352) else None)
        r = lv.creer_pour(TW, "u30", "yazid", manager="YAZID")
        check("création : le tracking Emy déjà chez MyPuls au nom du VA est repris (aucun doublon)",
              r.get("ok") and r.get("tracking") == "https://onlyfans.com/emy.brw/c84"
              and ("Twitter VA 27 @yazid", None) not in suivis and ("Twitter VA 27 @yazid", 3867) in suivis,
              (r, suivis))
    finally:
        lv._tracking_existant = _sauve_ex

    # ── l'accueil du ticket : redessiné pour montrer « 📈 Mes subs » ─────
    # (le bouton lui-même vient d'un patch local du VPS, 99-z-tickets-subs-total)
    check("les accueils déjà postés sont redessinés une fois (BOUTONS_VERSION 3)",
          tk.BOUTONS_VERSION == 3)
    _src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    _sync = _src_w[_src_w.index("def _sync_liens_va("):_src_w.index("_MODELES_VU = {")]
    check("… Twitter compris : la boucle du podium appelle redessiner_boutons",
          "redessiner_boutons(gid)" in _sync)

    # ── « Mes subs » dans le salon d'un VA : SES subs, pas ceux du cliqueur ─
    # « pk ça me dit 0 sub pour lui et pour lui aussi » (15/10/2026)
    vus_subs = []
    _sauve_cu = {k: getattr(cu, k) for k in ("_mes_subs_texte", "_va_du_salon")}

    class _RepS:
        async def defer(self, **k):
            pass

    class _SuiteS:
        async def send(self, txt, **k):
            vus_subs.append(txt)
    try:
        cu._mes_subs_texte = lambda g_, u_: f"subs de {u_.id}"
        cu._va_du_salon = lambda ch: 4242 if getattr(ch, "id", None) == 9 else None
        inter = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), user=types.SimpleNamespace(id=7),
                                      channel=types.SimpleNamespace(id=9), response=_RepS(), followup=_SuiteS())
        asyncio.run(cu.ContentMenuView._clic_subs(None, inter))
        inter.channel = types.SimpleNamespace(id=10)
        asyncio.run(cu.ContentMenuView._clic_subs(None, inter))
    finally:
        for _k, _v in _sauve_cu.items():
            setattr(cu, _k, _v)
    check("Mes subs dans le ticket d'un VA : les subs DE CE VA (pas du manager qui clique) ; ailleurs, les siens",
          vus_subs == ["subs de 4242", "subs de 7"], vus_subs)

    # le menu se construit vraiment : 5 boutons au plus par rangée (un 6e
    # fait tomber TOUT le menu), 40 composants au plus par message
    import discord as _discord

    def _compte(v):
        n, pire = 0, 0
        pile = list(getattr(v, "children", []) or [])
        while pile:
            c = pile.pop()
            n += 1
            if isinstance(c, _discord.ui.ActionRow):
                pire = max(pire, len(c.children))
            pile.extend(getattr(c, "children", []) or [])
        return n, pire

    async def _menus():
        out = {}
        v = cu.ContentMenuView(types.SimpleNamespace(bot=None), identite="emy", mention=42)
        out["tous"] = _compte(v)
        for nom, gid_ in (("twitter", int(TW)), ("threads", int(TH))):
            v.construire(types.SimpleNamespace(id=gid_, name=nom, roles=[], emojis=[]), filtrer=True)
            out[nom] = _compte(v) + ("cmenu:subs" in [getattr(c, "custom_id", "")
                                                      for c in v.walk_children()],)
        lg = cu.MenuLigneVA(types.SimpleNamespace(bot=None), identite="amelia", mention=42,
                            guild=types.SimpleNamespace(id=int(sv.VA_IG_ID), name="Va IG", roles=[],
                                                        emojis=[]), filtrer=True)
        # les boutons de la ligne portent « cmenu:l: » (_BoutonLigneVA)
        out["ligne"] = _compte(lg) + ("cmenu:l:subs" in [getattr(c, "custom_id", "")
                                                         for c in lg.walk_children()],)
        return out
    m = asyncio.run(_menus())
    check("menus VA : 5 boutons au plus par rangée, 40 composants au plus, « Mes subs » partout",
          all(m[k][1] <= 5 and m[k][0] <= 40 for k in m)
          and m["twitter"][2] and m["threads"][2] and m["ligne"][2], m)

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
    # « arrête de dire tracking pour elle et elle », « juste dire voilà ton
    # lien avec le tracking de sub » (15/10/2026)
    vu = " ".join(suites) + " " + json.dumps([x[2] for x in postes], ensure_ascii=False)
    check("manager : le lien, sans nom de modèle",
          suites and "getmysocial.com/" in suites[0] and "Seren" not in vu and "Emy" not in vu, suites)
    msg_va = [x[2]["content"] for x in postes if x[0] == "POST" and x[1] == "/channels/s6/messages"]
    check("VA : « voilà ton lien avec ton tracking de subs : … », rien d'autre",
          msg_va and msg_va[0].startswith("🔗 <@u6>, voilà ton lien avec ton tracking de subs : https://getmysocial.com/")
          and "\n" not in msg_va[0], msg_va)
    suites.clear()
    postes.clear()
    g, _s = monde()
    g.ab = {"ok": False, "cookie": True, "error": "cookie de session GetMySocial refusé"}
    tk._creer_lien(TW, "u7", "m1", {"token": "t", "channel_id": "s7"})
    check("cookie refusé : le manager sait que le partage attend, et quoi faire, sans nom de modèle",
          suites and "pas encore posé" in suites[0] and "Recolle le cookie" in suites[0]
          and "getmysocial.com/" in suites[0] and "Seren" not in suites[0] and "Emy" not in suites[0],
          suites)

    # ── nettoyer les vieux messages de lien dans les tickets ─────────────
    # « tu peux clean les liens dans les conv » (15/10/2026)
    g, _s = monde(etat={"liens": {f"{TW}:42": {"pseudo": "abdoul_9684", "numero": 31,
                                                "shortcode": "bbyy",
                                                "public_url": "https://getmysocial.com/bbyy"}}})
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {f"{TW}:42": {"salon": "s42"}}}))
    MSGS = [
        {"id": "m1", "author": {"id": "BOT"}, "content": "🔗 <@42>, voici **ton lien** : "
         "https://getmysocial.com/emycute\nC'est celui-là que tu postes sur Twitter — il compte tes subs pour le podium."},
        {"id": "m2", "author": {"id": "BOT"}, "content": "Bienvenue ! Lis les règles."},
        {"id": "m3", "author": {"id": "42"}, "content": "mon lien c'est getmysocial.com/emycute ?"},
        {"id": "m4", "author": {"id": "BOT"},
         "content": "🔗 <@42>, voilà ton lien avec ton tracking de subs : https://getmysocial.com/bbyy"},
    ]
    patchs = []

    def api_salon(methode, chemin, **kw):
        if chemin == "/users/@me":
            return 200, {"id": "BOT"}
        if methode == "GET" and chemin.startswith("/channels/s42/messages"):
            return 200, json.loads(json.dumps(MSGS))
        if methode == "PATCH":
            patchs.append((chemin, kw.get("json")))
            return 200, {}
        return 404, {}
    tk._api = api_salon
    b = tk.nettoyer_messages_lien(TW)
    check("nettoyage : le vieux message de lien du bot porte le BON lien",
          patchs == [("/channels/s42/messages/m1",
                      {"content": "🔗 <@42>, voilà ton lien avec ton tracking de subs : "
                                  "https://getmysocial.com/bbyy", "allowed_mentions": {"parse": []}})]
          and len(b["corriges"]) == 1 and b["a_jour"] == 1 and not b["rates"], (patchs, b))
    check("… ni les autres messages du bot, ni ceux du VA ne sont touchés",
          all("/m2" not in c and "/m3" not in c for c, _ in patchs), patchs)
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
