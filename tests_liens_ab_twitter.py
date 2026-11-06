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
  - le message au manager ;
  - 30 % sans tracking (01/11/2026) : un lien neuf a quatre branches (46,7
    tracking / 23,3 Seren / 20 page de la model / 10 page Seren) ; les liens
    déjà passés à la main sont reconnus sans rien réécrire ; « Base Emy »
    remplacée après un changement de model ; « Variant … not found » remonté
    tel quel ; refiltrer_variante avec trois variantes ; « sans_tracking » :
    {} = comme avant ; un échec des pages ne fait pas échouer le lien ; Seren
    coupée puis remise retrouve ses quatre branches.

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
# Les liens Twitter sont des pages depuis le 03/11/2026 (GABARIT_PAGE_TWITTER) ;
# ce fichier garde les règles du lien direct (tracking d'abord, A/B, variantes),
# toujours celles des copies des branches. Le chemin en page : tests_twitter_pages.py.
lv.GABARIT_PAGE_TWITTER = ""
import podium_discord as pod           # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []

# Depuis le 21/10/2026, Seren est en pause (liens_va.SEREN_EN_PAUSE, voir
# tests_seren_en_pause.py) ; ce qui suit vérifie le 50/50 tel qu'il reviendra.
lv.SEREN_EN_PAUSE = False


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH = lv.TWITTER_ID, lv.THREADS_ID
EMY_TWITTER = lv.EQUIPE_VA
GABARIT_TW = "lnk_gabarit_twitter"
# Les vérifications d'avant le 01/11/2026 portent sur le 50/50 seul : la clé
# « sans_tracking » : {} coupe les pages de base (comportement d'avant). Les
# quatre branches (CONFIG_4, la config par défaut) sont vérifiées plus bas.
# « lia_seule » : false garde Seren sur Twitter (avant le 02/11/2026) ; Twitter
# sans Seren (la config par défaut) est vérifié à la fin.
CONFIG = {"gabarit": GABARIT_TW, "equipe": EMY_TWITTER, "mypuls_actif": True, "creator_id": 3352,
          "sans_tracking": {}, "lia_seule": False}
CONFIG_4 = {k: v for k, v in CONFIG.items() if k != "sans_tracking"}


class FauxGMS(types.ModuleType):
    PUBLIC_LINK_DOMAIN = "https://getmysocial.com"

    def __init__(self):
        super().__init__("gms")
        self.appels = []
        self.ab = {"ok": True, "config": {}}
        self.adresse_prise = True
        self.liens = {}         # ce que GetMySocial garde de chaque lien (get/update_link)
        self.refus_maj = set()  # débuts d'identifiants dont update_link est refusé

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        lien = {"id": f"lnk_{sc}", "type": "directlink",
                "url": url if (url and self.adresse_prise) else "https://onlyfans.com/emy.brw"}
        self.liens[lien["id"]] = dict(lien)
        return {"ok": True, "link": lien}

    def get_link(self, lid, equipe=None):
        return {"ok": True, "link": json.loads(json.dumps(
            self.liens.get(lid) or {"id": lid, "type": "directlink", "url": ""}))}

    def update_link(self, lid, champs, equipe=None):
        self.appels.append(("pays", lid))
        if any(lid.startswith(x) for x in self.refus_maj):
            return {"ok": False, "error": "HTTP 429"}
        self.liens.setdefault(lid, {"id": lid, "type": "directlink", "url": ""}).update(
            json.loads(json.dumps(champs)))
        return {"ok": True, "link": self.liens[lid]}

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


def _sans(lid):
    s = str(lid or "")
    return s[4:] if s.startswith("lnk_") else s


class FauxAB(FauxGMS):
    """FauxGMS avec l'écran A/B Testing tel qu'observé chez GetMySocial :
    une variante est une copie FIGÉE de sa source à l'enregistrement (gardée
    dans « copie ») ; l'enregistrement remplace la liste entière ; un
    variantId inconnu est refusé (« Variant … not found », bloomvelvetyy le
    01/11/2026) ; éteint, l'A/B perd ses variantes (21/10/2026)."""

    def __init__(self):
        super().__init__()
        self.abs = {}            # id sans lnk_ -> {enabled, controlWeight, variants}
        self.perdues = set()     # variantId que GetMySocial dit introuvables
        self.refus_post = None   # réponse de tout POST, si posée
        self.cookie_lire = False
        self.dans_liste = []     # liens rendus par list_links_team (couper_seren)
        self.n = 0

    def _copie(self, src):
        l = self.liens.get("lnk_" + _sans(src))
        return json.loads(json.dumps(l)) if l else None

    def _vid(self):
        self.n += 1
        return f"var{self.n}"

    @staticmethod
    def _public(cfg):
        cfg = json.loads(json.dumps(cfg))
        for v in cfg.get("variants") or []:
            v.pop("copie", None)
        return cfg

    def poser_ab_testing(self, lid, source, equipe, poids, nom):
        self.appels.append(("ab", lid, source, equipe, poids, nom))
        if not self.ab.get("ok"):
            return dict(self.ab)
        self.abs[_sans(lid)] = {"enabled": True, "controlWeight": round(100 - poids, 1), "variants": [
            {"variantId": self._vid(), "sourceLinkId": _sans(source), "name": nom, "weight": poids,
             "description": "Variant based on another link", "copie": self._copie(source)}]}
        return {"ok": True, "config": self._public(self.abs[_sans(lid)])}

    def lire_ab_testing(self, lid, equipe=None):
        self.appels.append(("lire", _sans(lid), equipe))
        if self.cookie_lire:
            return {"ok": False, "cookie": True, "error": "cookie de session GetMySocial refusé"}
        return {"ok": True, "config": self._public(
            self.abs.get(_sans(lid)) or {"enabled": False, "controlWeight": 50, "variants": []})}

    def _ab_prive(self, methode, lid, equipe=None, corps=None):
        if methode == "GET":
            return self.lire_ab_testing(lid, equipe)
        self.appels.append(("post", _sans(lid), json.loads(json.dumps(corps))))
        if self.refus_post:
            return dict(self.refus_post)
        avant = {v["variantId"]: v for v in (self.abs.get(_sans(lid)) or {}).get("variants") or []}
        neuves = []
        for v in corps.get("variants") or []:
            vid = v.get("variantId")
            if vid and (vid not in avant or vid in self.perdues):
                return {"ok": False, "error": f"HTTP 400 : Variant {vid} not found"}
            if v.get("sourceLinkId"):
                copie = self._copie(v["sourceLinkId"])
                if copie is None:
                    return {"ok": False, "error": "HTTP 404 : source introuvable"}
            elif vid:
                copie = avant[vid]["copie"]
            else:
                return {"ok": False, "error": "HTTP 400 : variante sans source"}
            neuves.append({"variantId": vid or self._vid(),
                           "sourceLinkId": v.get("sourceLinkId") or avant.get(vid, {}).get("sourceLinkId"),
                           "name": v.get("name"), "weight": v.get("weight"),
                           "description": v.get("description"), "copie": copie})
        self.abs[_sans(lid)] = {"enabled": bool(corps.get("enabled")),
                                "controlWeight": corps.get("controlWeight"),
                                "variants": neuves if corps.get("enabled") else []}
        return {"ok": True, "config": self._public(self.abs[_sans(lid)])}

    def allumer_ab_testing(self, lid, equipe="", actif=True, variantes=None):
        self.appels.append(("allumer", _sans(lid), actif))
        cfg = self.abs.get(_sans(lid)) or {"enabled": False, "controlWeight": 50, "variants": []}
        avant = self._public(cfg)
        self.abs[_sans(lid)] = dict(cfg, enabled=bool(actif), variants=cfg["variants"] if actif else [])
        return {"ok": True, "config": self._public(self.abs[_sans(lid)]), "avant": avant}

    def delete_link(self, lid):
        self.appels.append(("delete", lid))
        self.liens.pop(lid, None)     # la variante, copie figée, n'en dépend plus
        return {"ok": True}

    def list_links_team(self, equipe, force_refresh=False):
        out = []
        for lid in self.dans_liste:
            cfg = self.abs.get(_sans(lid)) or {"enabled": False, "variants": []}
            out.append(dict(self.liens.get(lid) or {}, id=lid, shortcode=_sans(lid),
                            ab_testing={"enabled": cfg["enabled"], "variants": cfg["variants"]}))
        return {"links": out}


TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "numero_de",
                                         "creer_tracking", "COUPES_FICHIER", "SEREN_EN_PAUSE",
                                         "_tracking_existant", "PAUSE_BASES_S",
                                         "BASES_PAR_PASSE", "RELIRE_ETEINT_S")}
_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "_api", "_EN_FOND",
                                         "_suite", "identifiant", "nom_manager")}
_SAUVE_GMS = sys.modules.get("gms")
_SAUVE_REQ_POST = vrai_gms.requests.post
_SAUVE_COOKIE = vrai_gms.get_session_cookie
SEQ = []      # l'ordre des créations, MyPuls et GetMySocial mêlés


def monde(config=None, etat=None, mypuls_ok=True, classe=None):
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.CONFIG_FICHIER = TMP / "tickets_config.json"
    lv.COUPES_FICHIER = TMP / "liens_seren_coupes.json"
    for p in TMP.iterdir():
        p.unlink()
    lv.CONFIG_FICHIER.write_text(json.dumps(CONFIG if config is None else config))
    if etat is not None:
        lv.ETAT_FICHIER.write_text(json.dumps(etat))
    g = (classe or FauxGMS)()
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
          v == {"modele": "Seren", "creator_id": 3867, "poids": 33.3}, v)
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
          ab == [("ab", f"lnk_{SC1}", f"lnk_{dup[1][2]}", EMY_TWITTER, 33.3, "Seren")], ab)
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
        b_tw = pod._boutons(TW, True, pseudos=True)
        check("bouton « 👀 Pseudos » sous la quinzaine de Va IG, à côté de « 🔄 » ; "
              "Twitter : « 👀 » seul (depuis le 19/10/2026)",
              [c["custom_id"] for c in b] == [pod.BOUTON_MAJ, pod.BOUTON_PSEUDOS]
              and [c["custom_id"] for c in pod._boutons(sv.VA_IG_ID, True)["components"][0]["components"]]
              == [pod.BOUTON_MAJ]
              and [c["custom_id"] for c in b_tw["components"][0]["components"]]
              == [pod.BOUTON_PSEUDOS], (b, b_tw))
        txt = pod.texte_pseudos(sv.VA_IG_ID, J)
        check("… réponse au staff : numéro Instagram, PSEUDO, model, abonnés",
              "**york** (Amelia VA 43) — 11 subs" in txt and "**adh040** (Lola VA 2) — 7 subs" in txt
              and "Instagram VA" in txt, txt)
        suites3 = []
        _sauve_pt = {k: getattr(pod, k) for k in ("_refus_pseudos", "_en_fond")}
        _sauve_tk3 = tk._suite
        try:
            pod._en_fond = lambda f: f()
            tk._suite = lambda jeton_, texte, p=None: suites3.append(texte)
            clic = {"type": 3, "guild_id": sv.VA_IG_ID, "token": "t",
                    "data": {"custom_id": pod.BOUTON_PSEUDOS}, "member": {"user": {"id": "1"}}}
            # 04/11/2026 : 👀 au rôle BOSS seulement (tests_pseudos_bonus)
            pod._refus_pseudos = lambda p_: pod.TEXTE_PSEUDOS_REFUS
            r = pod.traiter(clic)
            check("… un VA qui clique : refusé, rien calculé",
                  r.get("type") == 4 and "BOSS" in r["data"]["content"] and not suites3, r)
            pod._refus_pseudos = lambda p_: ""
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
        # Depuis le 21/10/2026 (« en privé les clics et subs ») : Twitter répond
        # « 📈 Mes stats », les abonnés puis les clics de son lien.
        _sauve_cdv = pod.clics_du_va
        pod.clics_du_va = lambda g_, u_, per: [(3, 5), (40, 71), (52, 90)]
        try:
            txt = cu._mes_subs_texte(types.SimpleNamespace(id=int(TW)), types.SimpleNamespace(id=42))
        finally:
            pod.clics_du_va = _sauve_cdv
        check("message du VA : trois totaux de subs avec les dates, puis ses clics, sans montant",
              txt.startswith("📈 **Tes stats**") and "**Subs**" in txt and "Aujourd'hui : **" in txt
              and "Cette période (du 01/10 au 15/10) : **15**" in txt
              and "Période précédente (du 16/09 au 30/09) : **20**" in txt
              and "**Clics de ton lien** (US · GBL = tous pays)" in txt
              and "Cette période (du 01/10 au 15/10) : US : **40** · GBL : **71**" in txt
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
    # (4 depuis le 21/10/2026 : « 📈 Mes stats » sur Threads ; Twitter, lui,
    # garde « Mes subs » et ses accueils sont seulement redessinés à l'identique)
    check("les accueils déjà postés sont redessinés une fois (BOUTONS_VERSION 3, puis 4)",
          tk.BOUTONS_VERSION >= 3)
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
    reponse["r"] = Rep(200, {"success": True, "config": {
        "enabled": True, "controlWeight": 66.7, "variants": [{"variantId": "v1", "weight": 33.3}]}})
    rr = vrai_gms.poser_ab_testing("lnk_6acf00", "lnk_6acf01", "tm_6ab46e", 33.3, "Seren")
    corps = (envois[-1][1].get("json") or {})
    check("2/3 Lia (29/10/2026) : 66.7 / 33.3 envoyés au dixième, relus sans arrondi",
          rr.get("ok") and corps.get("controlWeight") == 66.7
          and corps["variants"][0]["weight"] == 33.3, (rr, corps))
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

    # ── les pays qui comptent (29/10/2026) ───────────────────────────────
    # « dès que les mecs ne sont pas des USA, Australie, Canada […] renvoie-les
    # vers le lien qui n'a pas de tracking link, juste le compte de base »
    BASE = "https://onlyfans.com/emy.brw"       # le compte de la model du lien (tracking c55)
    # 8 cibles depuis le 03/11 (+ Bénin, Madagascar), plus l'Europe riche sur
    # Twitter depuis le 06/11 (liens_va.PAYS_EN_PLUS) : 23
    CIBLES_TW = lv.cibles_pays(lv.espace(TW)["equipe"])
    NB = len(lv.TOUS_LES_PAYS) - len(CIBLES_TW)
    g, _s = monde()
    r = lv.creer_pour(TW, "p1", "paysva", manager="YAZID")
    lid = f'lnk_{r.get("shortcode")}'
    geo = g.liens.get(lid, {}).get("geofilters") or []
    codes = {x["country_code"] for x in geo}
    check("lien neuf : tout pays hors US/CA/AU/GB/NZ/IE (et l'Europe riche) va au compte de base de SA model, sans tracking",
          r.get("ok") and len(geo) == NB == 233 and not codes & CIBLES_TW
          and {"ES", "IT", "MX"} <= codes and not {"FR", "DE"} & codes
          and all(x["destination_url"] == BASE for x in geo),
          (r, len(geo), {x["destination_url"] for x in geo}))
    check("… noté dans la fiche et dans le retour",
          lv.lien_de(TW, "p1").get("pays") is True and r.get("pays") is True)
    dup = g.de("duplicate")
    tmp = f"lnk_{dup[1][2]}" if len(dup) == 2 else "?"
    ordre = [a[:2] if a[0] == "pays" else a[0] for a in g.appels if a[0] in ("pays", "ab")]
    gtmp = g.liens.get(tmp, {}).get("geofilters") or []
    check("… la part Seren aussi : sa copie a la liste AVANT l'A/B (variante figée), vers le compte "
          "de la model du LIEN, pas de Seren",
          ordre == [("pays", lid), ("pays", tmp), "ab"] and len(gtmp) == NB
          and {x["destination_url"] for x in gtmp} == {BASE}, (ordre, len(gtmp)))

    g, _s = monde()
    g.refus_maj = {"lnk_abtmp"}
    r = lv.creer_pour(TW, "p1", "paysva", manager="YAZID")
    fv = lv.lien_de(TW, "p1").get("variante") or {}
    check("copie de la variante non filtrée : PAS d'A/B (il serait figé sans la règle), lien filtré quand même",
          r.get("ok") and r.get("pays") is True and not g.de("ab")
          and (r.get("variante") or {}).get("ok") is False and "pays" in (r.get("variante") or {}).get("erreur", ""),
          (r, g.de("ab")))
    check("… copie supprimée, variante en attente : reprendre_variantes la refera",
          len(g.de("delete")) == 1 and fv.get("posee") is False and f"{TW}:p1" in lv.en_attente(), (fv, g.de("delete")))
    g.refus_maj = set()
    b = lv.reprendre_variantes()
    check("… au passage suivant : posée, avec la liste sur sa copie",
          "paysva" in b["poses"] and len(g.de("ab")) == 1
          and len(g.liens.get(f'lnk_{g.de("duplicate")[-1][2]}', {}).get("geofilters") or []) == NB, b)

    g, _s = monde()
    g.refus_maj = {"lnk_"}
    r = lv.creer_pour(TW, "p1", "paysva", manager="YAZID")
    f = lv.lien_de(TW, "p1")
    check("règle ratée sur le lien : créé quand même, la fiche dit « pays » : false et pourquoi",
          r.get("ok") and r.get("pays") is False and f.get("pays") is False and "429" in f.get("pays_erreur", ""),
          (r, f))
    g.refus_maj = set()
    b = lv.reprendre_pays(TW)
    f = lv.lien_de(TW, "p1")
    check("reprendre_pays la repose : liste sur le lien, fiche « pays » : true",
          b["poses"] == [f["shortcode"]] and f.get("pays") is True
          and len(g.liens.get(f["link_id"], {}).get("geofilters") or []) == NB, (b, f))
    n = len(g.de("pays"))
    check("… et ne refait rien ensuite", lv.reprendre_pays(TW) == {"poses": [], "rates": []}
          and len(g.de("pays")) == n)
    etat = json.loads(lv.ETAT_FICHIER.read_text())
    etat["liens"][f"{TW}:p1"]["pays"] = False
    lv.ETAT_FICHIER.write_text(json.dumps(etat))
    g.refus_maj = {"lnk_"}
    for _ in range(lv.ESSAIS_PAYS + 2):
        lv.reprendre_pays(TW)
    f = lv.lien_de(TW, "p1")
    check(f"… raté {lv.ESSAIS_PAYS} fois : la main (« pays_a_verifier »), plus d'essai",
          f.get("pays_essais") == lv.ESSAIS_PAYS and f.get("pays_a_verifier") is True, f)
    etat = json.loads(lv.ETAT_FICHIER.read_text())
    etat["liens"][f"{TW}:p1"].update(pays=False, pays_essais=0, actif=False)
    lv.ETAT_FICHIER.write_text(json.dumps(etat))
    n = len(g.de("pays"))
    lv.reprendre_pays(TW)
    check("… un lien coupé n'est pas repris", len(g.de("pays")) == n)
    g.refus_maj = set()
    g.enable_link = lambda lid_: {"ok": True}
    bb = lv.basculer(TW, "p1", True)
    check("… mais rallumé, il reçoit la règle tout de suite",
          bb.get("ok") and lv.lien_de(TW, "p1").get("pays") is True and len(g.de("pays")) == n + 1, bb)

    # la variante Seren refiltrée (après un changement de model) : même variantId
    g, _s = monde(etat={"liens": {f"{TW}:v": {
        "pseudo": "v", "numero": 5, "shortcode": "vv", "link_id": "lnk_vv",
        "tracking": "https://onlyfans.com/liasxcret/c63", "pays_cibles": lv.signature_pays(TW),
        "variante": {"posee": True, "pays": False, "tracking": SEREN}}}})
    cfg = {"enabled": True, "controlWeight": 66.7,
           "variants": [{"variantId": "v1", "sourceLinkId": "vieux", "weight": 33.3, "name": "Seren"}]}
    g.lire_ab_testing = lambda lid_, eq=None: {"ok": True, "config": json.loads(json.dumps(cfg))}
    posts = []
    g._ab_prive = lambda m, lid_, eq=None, corps=None: (posts.append((lid_, corps)), {"ok": True, "config": cfg})[1]
    b = lv.reprendre_pays(TW)
    dup = g.de("duplicate")
    tmp = f"lnk_{dup[0][2]}" if dup else "?"
    gtmp = g.liens.get(tmp, {}).get("geofilters") or []
    check("variante « pays » : false : recopiée depuis une copie filtrée vers le compte de la model du lien",
          b["poses"] == ["vv (Seren)"] and dup and dup[0][4] == SEREN and len(gtmp) == NB
          and {x["destination_url"] for x in gtmp} == {"https://onlyfans.com/liasxcret"}, (b, dup))
    vv = (posts[0][1]["variants"][0] if posts else {})
    check("… au MÊME variantId et au même partage, copie supprimée",
          posts and posts[0][0] == "lnk_vv" and vv.get("variantId") == "v1" and vv.get("weight") == 33.3
          and posts[0][1]["controlWeight"] == 66.7 and vv.get("sourceLinkId") == tmp[4:]
          and g.de("delete") == [("delete", tmp)]
          and (lv.lien_de(TW, "v").get("variante") or {}).get("pays") is True, (posts, g.de("delete")))
    g.lire_ab_testing = lambda lid_, eq=None: {"ok": True, "config": {"enabled": False, "variants": []}}
    etat = json.loads(lv.ETAT_FICHIER.read_text())
    etat["liens"][f"{TW}:v"]["variante"]["pays"] = False
    lv.ETAT_FICHIER.write_text(json.dumps(etat))
    n = len(g.de("duplicate"))
    b = lv.reprendre_pays(TW)
    check("… A/B éteint ou inattendu : rien touché, et c'est dit",
          len(g.de("duplicate")) == n and b["rates"] and "inattendu" in b["rates"][0], b)

    # landing (Agency) et règles de la config
    g, _s = monde()
    g.liens["lnk_page"] = {"id": "lnk_page", "type": "landing", "buttons": [
        {"label": "Insta", "url": "https://instagram.com/x"},
        {"label": "OF", "url": "https://onlyfans.com/liasxcret/c98"}]}
    rp = lv.poser_pays("lnk_page", "tm_x")
    bts = g.liens["lnk_page"]["buttons"]
    check("landing (Agency) : la liste sur son bouton OnlyFans seulement (sur la page, GMS l'efface)",
          rp.get("ok") and len(bts[1].get("geofilters") or [])
          == len(lv.TOUS_LES_PAYS) - len(lv.cibles_pays("tm_x")) == 248     # équipe d'aucun serveur : liste d'avant
          and {x["destination_url"] for x in bts[1]["geofilters"]} == {"https://onlyfans.com/liasxcret"}
          and "geofilters" not in bts[0] and "geofilters" not in g.liens["lnk_page"], (rp, bts))
    g.liens["lnk_sans"] = {"id": "lnk_sans", "type": "landing", "buttons": [{"label": "a", "url": "https://x.com"}]}
    check("… sans bouton OnlyFans : refusé, rien envoyé",
          lv.poser_pays("lnk_sans", "tm_x").get("ok") is False and "geofilters" not in str(g.liens["lnk_sans"]))
    g.liens["lnk_d"] = {"id": "lnk_d", "type": "directlink", "url": "https://onlyfans.com/liasxcret/c1"}
    vrai_maj = g.update_link
    g.update_link = lambda lid_, champs, eq=None: {"ok": True, "link": {}}     # « 200 » sans rien garder
    check("relu sans la liste (GMS l'a avalée) : échec, pas un faux succès",
          "bonne liste" in lv.poser_pays("lnk_d", "tm_x").get("erreur", ""))
    g.update_link = vrai_maj
    lus = []
    vrai_get = g.get_link
    g.get_link = lambda lid_, eq=None: (lus.append(1), vrai_get(lid_) if len(lus) == 1 else {"ok": False, "error": "429"})[1]
    check("… relecture impossible : dit comme telle",
          "relecture impossible" in lv.poser_pays("lnk_d", "tm_x").get("erreur", ""))
    g.get_link = vrai_get
    monde(config=dict(CONFIG, pays={}))
    check("clé « pays » : {} coupe la règle (rien demandé à GetMySocial)",
          lv.regles_pays(BASE) == [] and lv.poser_pays("lnk_d", "tm_x").get("coupe") is True)
    monde(config=dict(CONFIG, pays={"cibles": ["us"]}))
    codes = {x["country_code"] for x in lv.regles_pays(BASE)}
    check("… {\"cibles\": [...]} change la liste", "US" not in codes and {"CA", "GB"} <= codes, codes)
    for mauvais, mot in (({"cibles": "US"}, "illisible"), ({"cibles": ["UK"]}, "GB"), (False, "illisible")):
        g, _s = monde(config=dict(CONFIG, pays=mauvais))
        g.liens["lnk_d"] = {"id": "lnk_d", "type": "directlink", "url": "https://onlyfans.com/liasxcret/c1"}
        rp = lv.poser_pays("lnk_d", "tm_x")
        check(f"… clé mal écrite ({mauvais!r}) : refusée en le disant, rien posé",
              rp.get("ok") is False and mot in rp.get("erreur", "") and not g.de("pays"), rp)
    check("compte de base : le tracking sans son code",
          lv.base_de("https://onlyfans.com/liasxcret/c63") == "https://onlyfans.com/liasxcret"
          and lv.base_de("https://onlyfans.com/seren.vale/c207?x=1") == "https://onlyfans.com/seren.vale"
          and lv.base_de("https://mym.fans/app/t/x") == "")

    # synchroniser repose la règle avant tout le reste (qui peut s'arrêter tôt)
    g, _s = monde()
    vus = []
    vrai_rp, vrai_groupes = lv.reprendre_pays, lv.groupes
    lv.reprendre_pays, lv.groupes = (lambda gid: vus.append(gid) or {}), (lambda eq, essais=3: None)
    try:
        lv.synchroniser(TW)
    finally:
        lv.reprendre_pays, lv.groupes = vrai_rp, vrai_groupes
    check("la synchro des liens (30 min) lance reprendre_pays", vus == [TW], vus)

    # ── 30 % sans tracking : les pages de base (01/11/2026) ──────────────
    # « 30 % des liens sans tracking, sur la page de base », « 2/3 et 1/3
    # comme d'hab » : 46,7 tracking de la model / 23,3 tracking Seren / 20
    # page de la model / 10 page Seren
    LIA_P, SEREN_P = "https://onlyfans.com/liasxcret", "https://onlyfans.com/seren.vale"
    lv._tracking_existant = lambda nom, cid: None     # aucun appel MyPuls
    lv.PAUSE_BASES_S = 0

    def monde4(etat=None, config=None):
        g_, suivis_ = monde(config=CONFIG_4 if config is None else config, etat=etat, classe=FauxAB)

        def faux_lia(nom, creator_id=None):
            suivis_.append((nom, creator_id))
            return ({"ok": True, "url": f"{SEREN_P}/c250", "code": "c250"} if creator_id == 3867
                    else {"ok": True, "url": f"{LIA_P}/c63", "code": "c63"})
        lv.creer_tracking = faux_lia
        return g_, suivis_

    def fiche4(n, sc, tracking=f"{LIA_P}/c60", seren=f"{SEREN_P}/c195", **kw):
        return {"pseudo": f"va{n}", "numero": n, "shortcode": sc, "link_id": f"lnk_{sc}",
                "tracking": tracking, "pays_cibles": lv.signature_pays(TW),
                "variante": dict({"posee": True, "modele": "Seren", "creator_id": 3867,
                                  "tracking": seren, "pays": True}, **kw)}

    def ab4(*variantes, controle=46.7):
        return {"enabled": True, "controlWeight": controle, "variants": [
            {"variantId": vid, "sourceLinkId": None, "name": nom, "weight": w, "description": "",
             "copie": {"url": url}} for vid, nom, w, url in variantes]}

    QUATRE = (("vS", "Seren", 23.3, f"{SEREN_P}/c195"), ("vL", "Base Lia", 20, LIA_P),
              ("vB", "Base Seren", 10, SEREN_P))

    def branches(g_, sc):
        cfg = g_.abs.get(sc) or {}
        return cfg, {v["name"]: v for v in cfg.get("variants") or []}

    check("les parts par défaut : 46,7 / 23,3 / 20 / 10, soit 66,7 Lia et 33,3 Seren, 30 % sans tracking",
          lv.SANS_TRACKING == {"controle": 46.7, "variante": 23.3, "base_modele": 20, "base_variante": 10}
          and round(lv.SANS_TRACKING["controle"] + lv.SANS_TRACKING["base_modele"], 1) == 66.7
          and round(lv.SANS_TRACKING["base_modele"] + lv.SANS_TRACKING["base_variante"], 1) == 30)
    check("noms des branches : la table des comptes du site (les 54 liens s'appellent « Base Lia », « Base Seren »)",
          (lv.nom_de_page(LIA_P), lv.nom_de_page(f"{SEREN_P}/c195"), lv.nom_de_page("https://onlyfans.com/emy.brw"),
           lv.nom_de_page("https://onlyfans.com/inconnue.x"), lv.nom_de_page("https://mym.fans/x"))
          == ("Lia", "Seren", "Emy", "inconnue.x", ""))

    # nouveau lien : quatre branches
    g, suivis = monde4()
    r = lv.creer_pour(TW, "n1", "nova", manager="YAZID")
    sc = r.get("shortcode") or "?"
    cfg, br = branches(g, sc)
    check("lien neuf : quatre branches, 46,7 tracking Lia / 23,3 Seren / 20 page Lia / 10 page Seren",
          r.get("ok") and (r.get("variante") or {}).get("ok") and cfg.get("enabled")
          and cfg.get("controlWeight") == 46.7
          and {n: v["weight"] for n, v in br.items()} == {"Seren": 23.3, "Base Lia": 20, "Base Seren": 10},
          (r, cfg))
    check("… la variante Seren reste celle posée juste avant (même variantId), vers SON tracking Seren",
          (br.get("Seren") or {}).get("variantId") == "var1"
          and ((br.get("Seren") or {}).get("copie") or {}).get("url") == f"{SEREN_P}/c250", br.get("Seren"))
    ok_pages = all(
        ((br.get(n) or {}).get("copie") or {}).get("url") == page
        and {x["destination_url"] for x in ((br.get(n) or {}).get("copie") or {}).get("geofilters") or []} == {LIA_P}
        and len(((br.get(n) or {}).get("copie") or {}).get("geofilters") or []) == NB
        for n, page in (("Base Lia", LIA_P), ("Base Seren", SEREN_P)))
    check("… les pages de base : copies figées des comptes SANS tracking, autres pays vers la page de la model du lien",
          ok_pages, {n: (v.get("copie") or {}).get("url") for n, v in br.items()})
    dup = g.de("duplicate")
    check("… copies temporaires depuis le gabarit, dans EMY TWITTER, toutes supprimées",
          len(dup) == 4 and all(d[1] == GABARIT_TW and d[5] == EMY_TWITTER for d in dup[1:])
          and sorted(x[1] for x in g.de("delete")) == sorted(f"lnk_{d[2]}" for d in dup[1:])
          and [d[4] for d in dup[2:]] == [LIA_P, SEREN_P], (dup, g.de("delete")))
    post = g.de("post")
    check("… un seul enregistrement : Seren gardée à son variantId sans source, deux pages neuves",
          len(post) == 1 and post[0][2]["controlWeight"] == 46.7
          and [(v["variantId"], v["sourceLinkId"] is None, v["weight"]) for v in post[0][2]["variants"]]
          == [("var1", True, 23.3), (None, False, 20), (None, False, 10)], post)
    fv = lv.lien_de(TW, "n1").get("variante") or {}
    check("… fiche : « bases » : true, pour la page de Lia ; un seul tracking Seren chez MyPuls",
          fv.get("bases") is True and fv.get("bases_pour") == LIA_P and fv.get("bases_essais") == 0
          and [c for _n, c in suivis] == [None, 3867], (fv, suivis))
    n = len(g.appels)
    b = lv.reprendre_bases(TW)
    check("… et la reprise n'y revient pas (rien lu)", not any(b[k] for k in ("poses", "deja", "rates"))
          and len(g.appels) == n, (b, g.appels[n:]))

    # les 54 liens passés à la main : reconnus, rien réécrit
    g, _s = monde4(etat={"liens": {f"{TW}:d": fiche4(32, "babeyy")}})
    g.liens["lnk_babeyy"] = {"id": "lnk_babeyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["babeyy"] = ab4(*QUATRE)
    avant = json.dumps(g.abs)
    b = lv.reprendre_bases(TW)
    check("lien déjà à quatre branches (« Base Lia », « Base Seren ») : reconnu, AUCUN enregistrement",
          b["deja"] == ["babeyy"] and not b["poses"] and not b["rates"] and not g.de("post")
          and not g.de("duplicate") and json.dumps(g.abs) == avant and len(g.de("lire")) == 1, (b, g.appels))
    fv = lv.lien_de(TW, "d").get("variante") or {}
    n = len(g.appels)
    lv.reprendre_bases(TW)
    check("… noté dans la fiche, plus relu ensuite",
          fv.get("bases") is True and fv.get("bases_pour") == LIA_P and len(g.appels) == n, fv)
    # par passage, BASES_PAR_PASSE liens au plus : synchroniser tourne dans la
    # boucle du podium, les 54 d'un coup la bloqueraient
    lv.BASES_PAR_PASSE = 2
    g, _s = monde4(etat={"liens": {f"{TW}:{u}": fiche4(40 + i, f"sc{u}") for i, u in enumerate("xyz")}})
    for u in "xyz":
        g.liens[f"lnk_sc{u}"] = {"id": f"lnk_sc{u}", "type": "directlink", "url": f"{LIA_P}/c60"}
        g.abs[f"sc{u}"] = ab4(*QUATRE)
    b1, b2 = lv.reprendre_bases(TW), lv.reprendre_bases(TW)
    lv.BASES_PAR_PASSE = _SAUVE_LV["BASES_PAR_PASSE"]
    check("… deux liens par passage (ici) : le reste au passage suivant, et c'est dit",
          (b1["deja"], b1["restent"], b2["deja"], b2["restent"]) == (["scx", "scy"], 1, ["scz"], 0)
          and len(g.de("lire")) == 3, (b1, b2))

    # Threads : la même reprise, dans EMY THREADS (sa variante vient du patch du VPS)
    g, _s = monde4(etat={"liens": {f"{TH}:t": fiche4(61, "angelyy")}})
    g.liens["lnk_angelyy"] = {"id": "lnk_angelyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["angelyy"] = ab4(QUATRE[0], controle=66.7)
    g.abs["angelyy"]["variants"][0]["weight"] = 33.3
    b = lv.reprendre_bases(TH)
    dup = g.de("duplicate")
    check("Threads : pages posées dans EMY THREADS, copies depuis emythreadsb (sans A/B)",
          b["poses"] == ["angelyy"] and len(dup) == 2
          and all(d[1] == lv.ESPACE_THREADS["source_variante"] and d[5] == lv.ESPACE_THREADS["equipe"] for d in dup)
          and g.de("lire")[0][2] == lv.ESPACE_THREADS["equipe"], (b, dup))

    # la model a changé (Emy → Lia) : la branche « Base Emy » est remplacée
    g, _s = monde4(etat={"liens": {f"{TW}:m": fiche4(5, "vv")}})
    g.liens["lnk_vv"] = {"id": "lnk_vv", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["vv"] = ab4(QUATRE[0], ("vE", "Base Emy", 20, "https://onlyfans.com/emy.brw"), QUATRE[2])
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "vv")
    post = g.de("post")
    check("branche « Base Emy » sur un lien passé chez Lia : remplacée par « Base Lia », le reste gardé",
          b["poses"] == ["vv"] and set(br) == {"Seren", "Base Lia", "Base Seren"}
          and br["Seren"]["variantId"] == "vS" and br["Base Seren"]["variantId"] == "vB"
          and br["Base Lia"]["copie"]["url"] == LIA_P and len(g.de("duplicate")) == 1
          and [v["variantId"] for v in post[0][2]["variants"]] == ["vS", None, "vB"], (b, cfg, post))

    # passer_sur (Emy → Lia) : « bases_pour » dit l'ancienne page, les deux sont refaites
    g, _s = monde4(etat={"liens": {f"{TW}:p": fiche4(6, "pp", bases=False,
                                                       bases_pour="https://onlyfans.com/emy.brw")}})
    g.liens["lnk_pp"] = {"id": "lnk_pp", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["pp"] = ab4(QUATRE[0], ("vE", "Base Emy", 20, "https://onlyfans.com/emy.brw"),
                      ("vB", "Base Seren", 10, SEREN_P))
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "pp")
    check("model changée (passer_sur) : « Base Seren » refaite aussi (ses autres pays partaient chez Emy)",
          b["poses"] == ["pp"] and br["Base Seren"]["variantId"] not in ("vB", None)
          and {x["destination_url"] for x in br["Base Seren"]["copie"].get("geofilters") or []} == {LIA_P}
          and len(g.de("duplicate")) == 2 and br["Seren"]["variantId"] == "vS"
          and (lv.lien_de(TW, "p").get("variante") or {}).get("bases_pour") == LIA_P, (b, br))

    # « Variant … not found » : l'erreur remonte, rien d'autre
    g, _s = monde4(etat={"liens": {f"{TW}:x": fiche4(7, "bloom")}})
    g.liens["lnk_bloom"] = {"id": "lnk_bloom", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["bloom"] = ab4(QUATRE[0], controle=66.7)
    g.abs["bloom"]["variants"][0]["weight"] = 33.3
    g.perdues = {"vS"}
    avant = json.dumps(g.abs)
    b = lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "x").get("variante") or {}
    check("« Variant … not found » : erreur remontée, un seul essai d'enregistrement, A/B intact",
          len(g.de("post")) == 1 and json.dumps(g.abs) == avant and b["a_verifier"]
          and "not found" in b["a_verifier"][0] and not b["poses"], (b, g.de("post")))
    check("… Seren pas refaite d'office, copies supprimées, la main tout de suite",
          [v.get("variantId") for v in g.de("post")[0][2]["variants"]][0] == "vS"
          and len(g.de("delete")) == len(g.de("duplicate")) == 2
          and fv.get("bases_a_verifier") is True and fv.get("bases") is False, fv)
    n = len(g.appels)
    lv.reprendre_bases(TW)
    check("… plus de reprise automatique", len(g.appels) == n, g.appels[n:])

    # « Variant <id> not found » quand l'enregistrement renvoie AUSSI une page
    # de base gardée par son variantId : l'id cité dit quelle branche est perdue
    # (avant, tout était mis sur Seren et le lien partait à la main)
    g, _s = monde4(etat={"liens": {f"{TW}:q": fiche4(18, "qq")}})
    g.liens["lnk_qq"] = {"id": "lnk_qq", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["qq"] = ab4(*QUATRE[:2])          # Seren + « Base Lia » gardée, « Base Seren » manque
    g.perdues = {"vL"}
    b = lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "q").get("variante") or {}
    post = g.de("post")
    check("« Variant vL not found » (page « Base Lia » gardée) : la bonne branche nommée, un essai normal",
          len(post) == 1 and [v["variantId"] for v in post[0][2]["variants"]] == ["vS", "vL", None]
          and b["rates"] and "Base Lia" in b["rates"][0] and "vL" in b["rates"][0]
          and "Seren introuvable" not in b["rates"][0] and not b["a_verifier"]
          and fv.get("bases_essais") == 1 and fv.get("bases_a_verifier") is False
          and fv.get("bases_perdues") == ["vL"], (b, fv))
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "qq")
    post = g.de("post")
    fv = lv.lien_de(TW, "q").get("variante") or {}
    check("… au passage suivant, « Base Lia » refaite en copie NEUVE (plus renvoyée par vL), Seren gardée",
          b["poses"] == ["qq"] and len(post) == 2
          and [(v["variantId"], v["sourceLinkId"] is None) for v in post[1][2]["variants"]]
          == [("vS", True), (None, False), (None, False)]
          and set(br) == {"Seren", "Base Lia", "Base Seren"} and br["Base Lia"]["variantId"] != "vL"
          and br["Base Lia"]["copie"]["url"] == LIA_P and br["Seren"]["variantId"] == "vS"
          and fv.get("bases") is True and "bases_perdues" not in fv, (b, post[-1:], fv))
    # … et quand c'est Seren qui est citée, pages gardées ou non : la main, comme avant
    g, _s = monde4(etat={"liens": {f"{TW}:q": fiche4(18, "qq")}})
    g.liens["lnk_qq"] = {"id": "lnk_qq", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["qq"] = ab4(*QUATRE[:2])
    g.perdues = {"vS"}
    b = lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "q").get("variante") or {}
    check("« Variant vS not found » avec une page gardée : Seren nommée, la main tout de suite",
          b["a_verifier"] and "variante Seren introuvable" in b["a_verifier"][0]
          and fv.get("bases_a_verifier") is True and "bases_perdues" not in fv, (b, fv))
    # un id que l'on ne reconnaît pas, des pages gardées : on ne devine pas
    g, _s = monde4(etat={"liens": {f"{TW}:q": fiche4(18, "qq")}})
    g.liens["lnk_qq"] = {"id": "lnk_qq", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["qq"] = ab4(*QUATRE[:2])
    g.refus_post = {"ok": False, "error": "HTTP 400 : Variant zz9 not found"}
    b = lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "q").get("variante") or {}
    check("… id non reconnu (ni Seren ni une page gardée) : la main, et c'est dit",
          b["a_verifier"] and "non reconnu" in b["a_verifier"][0] and fv.get("bases_a_verifier") is True
          and "bases_perdues" not in fv, (b, fv))

    # refiltrer_variante avec trois variantes (après un changement de model)
    g, _s = monde4(etat={"liens": {f"{TW}:r": fiche4(8, "rr", pays=False, bases=True)}})
    g.liens["lnk_rr"] = {"id": "lnk_rr", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["rr"] = ab4(*QUATRE)
    b = lv.reprendre_pays(TW)
    post = g.de("post")
    vs = post[0][2]["variants"] if post else []
    cfg, br = branches(g, "rr")
    check("refiltrer, quatre branches : Seren recopiée au MÊME variantId, les pages renvoyées telles quelles",
          b["poses"] == ["rr (Seren)"] and len(post) == 1 and post[0][2]["controlWeight"] == 46.7
          and [(v["variantId"], bool(v["sourceLinkId"]), v["weight"]) for v in vs]
          == [("vS", True, 23.3), ("vL", False, 20), ("vB", False, 10)], (b, post))
    check("… la copie Seren filtrée, les pages inchangées, fiche « pays » : true",
          len(br["Seren"]["copie"].get("geofilters") or []) == NB and br["Base Lia"]["copie"] == {"url": LIA_P}
          and br["Base Seren"]["copie"] == {"url": SEREN_P}
          and (lv.lien_de(TW, "r").get("variante") or {}).get("pays") is True, br)
    for forme, variantes in (("deux variantes", QUATRE[:2]),
                             ("une variante inconnue", (QUATRE[0], ("vE", "Emy", 20, LIA_P), QUATRE[2]))):
        g, _s = monde4(etat={"liens": {f"{TW}:r": fiche4(8, "rr", pays=False)}})
        g.abs["rr"] = ab4(*variantes)
        b = lv.reprendre_pays(TW)
        check(f"refiltrer, {forme} : rien touché, et c'est dit",
              not g.de("post") and not g.de("duplicate") and b["rates"] and "inattendu" in b["rates"][0], b)

    # sans_tracking : {} → comme avant
    g, suivis = monde4(config=CONFIG)
    r = lv.creer_pour(TW, "n2", "nova")
    cfg, br = branches(g, r.get("shortcode") or "?")
    fv = lv.lien_de(TW, "n2").get("variante") or {}
    n = len(g.appels)
    b = lv.reprendre_bases(TW)
    check("« sans_tracking » : {} : deux branches comme avant (66,7 / 33,3), aucune page, rien noté",
          r.get("ok") and cfg.get("controlWeight") == 66.7 and list(br) == ["Seren"]
          and len(g.de("duplicate")) == 2 and not g.de("post")
          and not any(k.startswith("bases") for k in fv) and len(g.appels) == n
          and not any(b[k] for k in ("poses", "deja", "rates")), (cfg, fv, b))
    g, _s = monde4(config=dict(CONFIG, sans_tracking=False), etat={"liens": {f"{TW}:d": fiche4(32, "babeyy")}})
    check("… false aussi : la reprise ne lit rien", lv.reprendre_bases(TW)["deja"] == [] and not g.appels)

    # un échec des pages ne fait pas échouer le lien
    g, _s = monde4()
    g.refus_post = {"ok": False, "error": "HTTP 500 : panne"}
    r = lv.creer_pour(TW, "n3", "nova")
    sc = r.get("shortcode") or "?"
    cfg, br = branches(g, sc)
    fv = lv.lien_de(TW, "n3").get("variante") or {}
    check("pages refusées : le lien et son 50/50 sont posés quand même (deux branches)",
          r.get("ok") and (r.get("variante") or {}).get("ok") and fv.get("posee") is True
          and list(br) == ["Seren"] and cfg.get("controlWeight") == 66.7, (r, cfg))
    check("… copies supprimées, l'échec noté (un essai), repris ensuite",
          len(g.de("delete")) == 3 and fv.get("bases") is False and fv.get("bases_essais") == 1
          and "panne" in fv.get("bases_erreur", ""), fv)
    g.refus_post = None
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, sc)
    check("… la reprise suivante les pose", b["poses"] == [sc] and set(br) == {"Seren", "Base Lia", "Base Seren"}
          and (lv.lien_de(TW, "n3").get("variante") or {}).get("bases") is True, (b, br))
    g, _s = monde4()
    _vrai_pb = lv.poser_bases
    lv.poser_bases = lambda gid_, uid_: 1 / 0
    try:
        r = lv.creer_pour(TW, "n4", "nova")
    finally:
        lv.poser_bases = _vrai_pb
    check("… même une exception dans poser_bases : le lien et le 50/50 restent ok",
          r.get("ok") and (r.get("variante") or {}).get("ok")
          and (lv.lien_de(TW, "n4").get("variante") or {}).get("posee") is True, r)

    # trois échecs : la main
    g, _s = monde4(etat={"liens": {f"{TW}:e": fiche4(9, "ee")}})
    g.liens["lnk_ee"] = {"id": "lnk_ee", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["ee"] = ab4(QUATRE[0], controle=66.7)
    g.refus_post = {"ok": False, "error": "HTTP 500 : panne"}
    for _ in range(lv.ESSAIS_BASES + 2):
        lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "e").get("variante") or {}
    check(f"échec répété : {lv.ESSAIS_BASES} essais, puis « bases_a_verifier » et plus rien",
          len(g.de("post")) == lv.ESSAIS_BASES and fv.get("bases_essais") == lv.ESSAIS_BASES
          and fv.get("bases_a_verifier") is True, (len(g.de("post")), fv))

    # cookie refusé : arrêt au premier, pas compté comme essai
    g, _s = monde4(etat={"liens": {f"{TW}:a": fiche4(10, "aa"), f"{TW}:b": fiche4(11, "bb")}})
    g.cookie_lire = True
    b = lv.reprendre_bases(TW)
    check("cookie refusé : arrêt au premier lien, pas un essai, ce cookie n'est plus essayé",
          b.get("cookie") and len(g.de("lire")) == 1
          and not (lv.lien_de(TW, "a").get("variante") or {}).get("bases_essais")
          and lv._etat().get("cookie_refuse") and lv.reprendre_bases(TW).get("cookie")
          and len(g.de("lire")) == 1, (b, g.de("lire")))

    # formes inattendues, fiche en retard, A/B éteint, config incohérente
    for forme, variantes in (("une variante inconnue (« Emy »)", (QUATRE[0], ("vE", "Emy", 20, LIA_P))),
                             ("deux Seren", (QUATRE[0], ("vS2", "Seren", 10, SEREN_P))),
                             ("pas de Seren", (QUATRE[1],))):
        g, _s = monde4(etat={"liens": {f"{TW}:i": fiche4(12, "ii")}})
        g.liens["lnk_ii"] = {"id": "lnk_ii", "type": "directlink", "url": f"{LIA_P}/c60"}
        g.abs["ii"] = ab4(*variantes)
        rb = lv.poser_bases(TW, "i")
        check(f"A/B avec {forme} : rien touché, et c'est dit",
              not rb.get("ok") and "inattendu" in rb.get("erreur", "") and not g.de("post")
              and not g.de("duplicate"), rb)
    g, _s = monde4(etat={"liens": {f"{TW}:s": fiche4(13, "ss", tracking="https://onlyfans.com/emy.brw/c5")}})
    g.liens["lnk_ss"] = {"id": "lnk_ss", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["ss"] = ab4(QUATRE[0], controle=66.7)
    rb = lv.poser_bases(TW, "s")
    check("fiche en retard sur le lien (Emy dans la fiche, Lia chez GetMySocial) : rien touché",
          not rb.get("ok") and "mène à" in rb.get("erreur", "") and not g.de("duplicate") and not g.de("post"), rb)
    g, _s = monde4(etat={"liens": {f"{TW}:o": fiche4(14, "oo")}})
    rb = lv.poser_bases(TW, "o")
    fv = lv.lien_de(TW, "o").get("variante") or {}
    check("A/B éteint : rien posé, noté (« bases » : false, l'erreur) mais PAS compté comme essai",
          not rb.get("ok") and rb.get("eteint") and not g.de("duplicate")
          and fv.get("bases") is False and "éteint" in fv.get("bases_erreur", "")
          and not fv.get("bases_essais") and fv.get("bases_a_verifier") is False, (rb, fv))
    # compté, il passait « à vérifier » au bout de ESSAIS_BASES passages et
    # n'était plus jamais repris une fois l'A/B rallumé
    g.liens["lnk_oo"] = {"id": "lnk_oo", "type": "directlink", "url": f"{LIA_P}/c60"}
    lv.RELIRE_ETEINT_S = 0          # chaque passage relit : rien ne doit compter d'essai
    for _ in range(lv.ESSAIS_BASES + 2):
        b = lv.reprendre_bases(TW)
    fv = lv.lien_de(TW, "o").get("variante") or {}
    check(f"… {lv.ESSAIS_BASES + 2} passages A/B éteint : jamais « à vérifier », listé à part (« eteints »)",
          b["eteints"] == ["oo"] and not b["rates"] and not b["a_verifier"] and not fv.get("bases_essais")
          and not fv.get("bases_a_verifier") and fv.get("bases_eteint") is True
          and not g.de("duplicate"), (b, fv))
    lv.RELIRE_ETEINT_S = _SAUVE_LV["RELIRE_ETEINT_S"]
    # relu à chaque passage, un lien éteint coûtait pour toujours une lecture,
    # une seconde de pause et une réécriture de liens_va.json toutes les 30 min
    n_lu, etat_avant = len(g.de("lire")), lv.ETAT_FICHIER.read_text()
    b = lv.reprendre_bases(TW)
    check("… dans le délai (6 h) : un lien éteint n'est ni relu ni réécrit",
          not b["eteints"] and b["restent"] == 0 and len(g.de("lire")) == n_lu
          and lv.ETAT_FICHIER.read_text() == etat_avant, b)
    d = lv._etat()
    d["liens"][f"{TW}:o"]["variante"]["bases_quand"] -= lv.RELIRE_ETEINT_S + 1
    lv._ecrire(d)
    b = lv.reprendre_bases(TW)
    check("… le délai passé : relu une fois", b["eteints"] == ["oo"] and len(g.de("lire")) == n_lu + 1, b)
    d = lv._etat()
    d["liens"][f"{TW}:o"]["variante"]["bases_quand"] -= lv.RELIRE_ETEINT_S + 1
    lv._ecrire(d)
    g.abs["oo"] = ab4(QUATRE[0], controle=66.7)
    g.abs["oo"]["variants"][0]["weight"] = 33.3
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "oo")
    check("… l'A/B rallumé : le lien est repris, ses deux pages posées",
          b["poses"] == ["oo"] and set(br) == {"Seren", "Base Lia", "Base Seren"}
          and (lv.lien_de(TW, "o").get("variante") or {}).get("bases") is True, (b, br))
    # un lien éteint ne garde pas sa place en tête de file : les autres passent
    lv.BASES_PAR_PASSE = 1
    g, _s = monde4(etat={"liens": {f"{TW}:a": fiche4(19, "aa"), f"{TW}:b": fiche4(20, "bb")}})
    g.liens["lnk_bb"] = {"id": "lnk_bb", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["bb"] = ab4(*QUATRE)
    b1, b2 = lv.reprendre_bases(TW), lv.reprendre_bases(TW)
    lv.BASES_PAR_PASSE = _SAUVE_LV["BASES_PAR_PASSE"]
    check("… un lien éteint passe en queue : au passage suivant, le lien d'après a son tour",
          b1["eteints"] == ["aa"] and b1["restent"] == 1 and b2["deja"] == ["bb"] and not b2["eteints"],
          (b1, b2))
    g, _s = monde4(config=dict(CONFIG_4, variante={"poids": 50}), etat={"liens": {f"{TW}:c": fiche4(15, "cc")}})
    rb = lv.poser_bases(TW, "c")
    check("poids de la variante changé (50) sans les parts : refusé sans rien lire ni noter",
          not rb.get("ok") and rb.get("config") and "incohérentes" in rb.get("erreur", "") and not g.appels
          and "bases_essais" not in (lv.lien_de(TW, "c").get("variante") or {}), rb)
    g, _s = monde4(config=dict(CONFIG_4, sans_tracking={"controle": 50}), etat={"liens": {f"{TW}:c": fiche4(15, "cc")}})
    b = lv.reprendre_bases(TW)
    check("clé « sans_tracking » qui ne fait pas 100 : refusée en le disant, rien lu",
          "100" in str(b.get("config")) and not g.appels, b)
    monde4(config=dict(CONFIG_4, sans_tracking={"controle": 40, "base_modele": 26.7}))
    check("… des parts qui font 100 : prises, le reste par défaut",
          lv.parts_sans_tracking() == {"controle": 40, "variante": 23.3, "base_modele": 26.7, "base_variante": 10})

    # Agency : une landing, copies depuis le lien direct emyigserenbase
    g, _s = monde4(etat={"liens": {f"{lv.AGENCY_IG_ID}:g": fiche4(16, "gg")}})
    g.liens["lnk_gg"] = {"id": "lnk_gg", "type": "landing", "buttons": [
        {"label": "insta", "url": "https://instagram.com/x"}, {"label": "OF", "url": f"{LIA_P}/c118"}]}
    g.abs["gg"] = ab4(QUATRE[0], controle=66.7)
    g.abs["gg"]["variants"][0]["weight"] = 33.3
    rb = lv.poser_bases(lv.AGENCY_IG_ID, "g")
    dup = g.de("duplicate")
    cfg, br = branches(g, "gg")
    check("Agency (landing) : la model lue sur le bouton OnlyFans, copies depuis emyigserenbase dans EMY IG",
          rb.get("ok") and len(dup) == 2 and all(d[1] == lv.ESPACE_AGENCY_IG["source_variante"]
                                                 and d[5] == lv.ESPACE_AGENCY_IG["equipe"] for d in dup)
          and set(br) == {"Seren", "Base Lia", "Base Seren"} and cfg.get("controlWeight") == 46.7, (rb, dup))

    # Seren en pause puis de retour : couper efface les trois variantes, le
    # retour refait Seren (même tracking) puis les pages
    g, suivis = monde4(etat={"liens": {f"{TW}:k": fiche4(17, "kk", bases=True, bases_pour=LIA_P)}})
    g.liens["lnk_kk"] = {"id": "lnk_kk", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["kk"] = ab4(*QUATRE)
    g.dans_liste = ["lnk_kk"]
    lv.SEREN_EN_PAUSE = True
    try:
        bc = lv.couper_seren(TW)
        notes = json.loads(lv.COUPES_FICHIER.read_text())["liens"]["kk"]
        check("couper : les quatre branches éteintes, la config d'avant notée avec ses TROIS variantes",
              bc["coupes"] == ["kk"] and not g.abs["kk"]["enabled"] and not g.abs["kk"]["variants"]
              and [v["name"] for v in notes["avant"]["variants"]] == ["Seren", "Base Lia", "Base Seren"]
              and notes["tracking_seren"] == f"{SEREN_P}/c195"
              and (lv.lien_de(TW, "k").get("variante") or {}).get("coupee"), (bc, notes))
        check("… la reprise des pages ne touche pas un lien coupé", lv.reprendre_bases(TW)["poses"] == []
              and not g.de("post"))
    finally:
        lv.SEREN_EN_PAUSE = False
    rm = lv.remettre_seren(TW)
    b = lv.reprendre_variantes(TW)
    cfg, br = branches(g, "kk")
    fv = lv.lien_de(TW, "k").get("variante") or {}
    check("retour de Seren : 50/50 refait vers le MÊME tracking Seren, puis les deux pages aussitôt",
          rm.get("a_reposer") == 1 and b["poses"] == ["va17"] and not suivis
          and set(br) == {"Seren", "Base Lia", "Base Seren"} and cfg.get("controlWeight") == 46.7
          and br["Seren"]["copie"]["url"] == f"{SEREN_P}/c195"
          and fv.get("bases") is True and fv.get("posee") is True and not fv.get("coupee"), (b, br, fv))

    # retour de Seren quand les pages sont coupées (« sans_tracking » : {}) ou
    # la clé mal écrite : l'A/B reposé n'a que Seren, la fiche oublie quand
    # même ses anciennes pages. Avant, « bases » : true d'avant la coupure
    # restait (_remettre_seren ne retire que « coupee ») et la reprise sautait
    # ce lien pour toujours une fois la règle revenue
    for quoi, regle in (("pages coupées (« sans_tracking » : {})", {}),
                        ("clé « sans_tracking » mal écrite", {"controle": 50})):
        g, _s = monde4(config=dict(CONFIG_4, sans_tracking=regle),
                       etat={"liens": {f"{TW}:k": fiche4(17, "kk", bases=True, bases_pour=LIA_P,
                                                          bases_quand=1, coupee=1)}})
        g.liens["lnk_kk"] = {"id": "lnk_kk", "type": "directlink", "url": f"{LIA_P}/c60"}
        rm = lv.remettre_seren(TW)
        b = lv.reprendre_variantes(TW)
        cfg, br = branches(g, "kk")
        fv = lv.lien_de(TW, "k").get("variante") or {}
        check(f"retour de Seren, {quoi} : A/B à deux branches, la fiche oublie ses anciennes pages",
              rm.get("a_reposer") == 1 and b["poses"] == ["va17"] and list(br) == ["Seren"]
              and fv.get("posee") is True and not any(k.startswith("bases") for k in fv), (b, fv))
        lv.CONFIG_FICHIER.write_text(json.dumps(CONFIG_4))
        b = lv.reprendre_bases(TW)
        cfg, br = branches(g, "kk")
        check(f"… la règle revenue, la reprise pose ses pages ({quoi})",
              b["poses"] == ["kk"] and set(br) == {"Seren", "Base Lia", "Base Seren"}
              and cfg.get("controlWeight") == 46.7
              and (lv.lien_de(TW, "k").get("variante") or {}).get("bases") is True, (b, br))

    # passer_sur pendant une pose : la fiche passe sur Lia pendant que les
    # pages d'Emy s'enregistrent. Avant, _noter_bases notait « bases » : true
    # avec l'ancienne page, et « Base Emy » restait à vie
    EMY_P = "https://onlyfans.com/emy.brw"
    g, _s = monde4(etat={"liens": {f"{TW}:w": fiche4(21, "ww", tracking=f"{EMY_P}/c5")}})
    g.liens["lnk_ww"] = {"id": "lnk_ww", "type": "directlink", "url": f"{EMY_P}/c5"}
    g.abs["ww"] = ab4(QUATRE[0], controle=66.7)
    g.abs["ww"]["variants"][0]["weight"] = 33.3
    _vrai_post = g._ab_prive

    def post_pendant_bascule(methode, lid, equipe=None, corps=None):
        if methode == "POST" and not g.de("post"):
            # ce que passer_sur écrit dans la fiche : tracking, bases false, bases_pour
            d = lv._etat()
            f = d["liens"][f"{TW}:w"]
            f["tracking"] = f"{LIA_P}/c64"
            f["variante"] = dict(f["variante"], bases=False, bases_essais=0, bases_a_verifier=False,
                                 bases_pour=EMY_P)
            lv._ecrire(d)
            g.liens["lnk_ww"]["url"] = f"{LIA_P}/c64"
        return _vrai_post(methode, lid, equipe, corps)
    g._ab_prive = post_pendant_bascule
    rb = lv.poser_bases(TW, "w")
    fv = lv.lien_de(TW, "w").get("variante") or {}
    cfg, br = branches(g, "ww")
    check("passer_sur pendant la pose : pages d'Emy enregistrées, la fiche ne dit PAS « bases » : true",
          rb.get("ok") and rb.get("base") == EMY_P and "Base Emy" in br and fv.get("bases") is False
          and fv.get("bases_pour") == EMY_P and not fv.get("bases_essais")
          and "entre-temps" in fv.get("bases_erreur", ""), (rb, fv))
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "ww")
    fv = lv.lien_de(TW, "w").get("variante") or {}
    check("… la reprise suivante refait les deux pour Lia (« Base Seren » : autres pays chez Lia)",
          b["poses"] == ["ww"] and set(br) == {"Seren", "Base Lia", "Base Seren"}
          and br["Seren"]["variantId"] == "vS"
          and {x["destination_url"] for x in br["Base Seren"]["copie"].get("geofilters") or []} == {LIA_P}
          and fv.get("bases") is True and fv.get("bases_pour") == LIA_P, (b, br, fv))

    # plafond des VRAIES poses (~16 appels GetMySocial chacune), à part des
    # lectures : synchroniser tourne dans la boucle du podium
    check("plafonds par passage : 15 liens lus, dont 3 vraiment posés",
          lv.BASES_PAR_PASSE == 15 and lv.BASES_POSEES_PAR_PASSE == 3)

    def a_poser(n, deja=0):
        etat_ = {f"{TW}:p{i}": fiche4(70 + i, f"pz{i}") for i in range(n)}
        etat_.update({f"{TW}:d{i}": fiche4(80 + i, f"dz{i}") for i in range(deja)})
        g_, _ = monde4(etat={"liens": etat_})
        for i in range(n):
            g_.liens[f"lnk_pz{i}"] = {"id": f"lnk_pz{i}", "type": "directlink", "url": f"{LIA_P}/c60"}
            g_.abs[f"pz{i}"] = ab4(QUATRE[0], controle=66.7)
            g_.abs[f"pz{i}"]["variants"][0]["weight"] = 33.3
        for i in range(deja):
            g_.abs[f"dz{i}"] = ab4(*QUATRE)
        return g_
    g = a_poser(5, deja=2)
    sortie = io.StringIO()
    _stdout, sys.stdout = sys.stdout, sortie
    try:
        b1 = lv.reprendre_bases(TW)
    finally:
        sys.stdout = _stdout
    f3 = lv.lien_de(TW, "p3").get("variante") or {}
    check("5 liens à poser + 2 déjà faits : 3 posés, 2 reportés (lus, pas posés), les 2 reconnus",
          b1["deja"] == ["dz0", "dz1"] and b1["poses"] == ["pz0", "pz1", "pz2"]
          and b1["reportes"] == ["pz3", "pz4"] and b1["restent"] == 2
          and len(g.de("post")) == 3 and len(g.de("duplicate")) == 6 and len(g.de("lire")) == 10, b1)
    check("… un reporté n'est pas noté (ni essai, ni erreur)",
          not any(k.startswith("bases") for k in f3), f3)
    check("… et c'est dit dans le journal", "restent 2 (dont 2 poses reportées" in sortie.getvalue()
          and "pz3" in sortie.getvalue(), sortie.getvalue())
    b2 = lv.reprendre_bases(TW)
    check("… le passage suivant pose les deux reportés",
          b2["poses"] == ["pz3", "pz4"] and not b2["reportes"] and b2["restent"] == 0
          and len(g.de("post")) == 5, b2)
    g = a_poser(5)
    g.refus_post = {"ok": False, "error": "HTTP 500 : panne"}
    b = lv.reprendre_bases(TW)
    check("… une pose ratée compte aussi dans le plafond (elle a coûté pareil)",
          len(g.de("post")) == 3 and len(b["rates"]) == 3 and b["reportes"] == ["pz3", "pz4"], b)

    # les gardes d'entrée : rien lu sans cookie utilisable, ni pendant une
    # autre reprise (le même écran A/B)
    def un_a_poser(**kw):
        g_, _ = monde4(etat=dict({"liens": {f"{TW}:g": fiche4(90, "gz")}}, **kw))
        g_.liens["lnk_gz"] = {"id": "lnk_gz", "type": "directlink", "url": f"{LIA_P}/c60"}
        g_.abs["gz"] = ab4(QUATRE[0], controle=66.7)
        g_.abs["gz"]["variants"][0]["weight"] = 33.3
        return g_
    g = un_a_poser()
    g.cookie = ""
    b = lv.reprendre_bases(TW)
    check("garde : pas de cookie GetMySocial → rien lu, « cookie » dit, le lien reste à faire",
          b.get("cookie") and not g.appels and b["restent"] == 1 and not b["poses"]
          and not any(k.startswith("bases") for k in lv.lien_de(TW, "g")["variante"]), b)
    g = un_a_poser()
    g.echeance = time.time() - 60
    b = lv.reprendre_bases(TW)
    check("garde : cookie échu → rien lu", b.get("cookie") and not g.appels, b)
    g = un_a_poser(cookie_refuse=lv._empreinte(FauxGMS.cookie))
    b = lv.reprendre_bases(TW)
    check("garde : cookie déjà refusé (même empreinte) → rien lu", b.get("cookie") and not g.appels, b)
    g.cookie = "authToken=x.y.z"
    b = lv.reprendre_bases(TW)
    check("… un cookie neuf collé : la reprise repart", b["poses"] == ["gz"] and not b.get("cookie"), b)
    g = un_a_poser()
    lv._REPRISE.acquire()
    try:
        b = lv.reprendre_bases(TW)
        tenu = lv._REPRISE.locked()
    finally:
        # relâché par reprendre_bases (le défaut) : ne pas planter la suite ici
        if lv._REPRISE.locked():
            lv._REPRISE.release()
    check("garde : une autre reprise tient le verrou → « occupe », rien lu, son verrou pas relâché",
          b.get("occupe") and not g.appels and tenu and b["restent"] == 1, b)
    b = lv.reprendre_bases(TW)
    check("… verrou rendu : la reprise suivante pose, puis relâche le verrou",
          b["poses"] == ["gz"] and not b.get("occupe") and not lv._REPRISE.locked(), b)

    # synchroniser : les pays, PUIS les pages de base
    g, _s = monde4()
    ordre = []
    vrai_rp, vrai_rb, vrai_groupes = lv.reprendre_pays, lv.reprendre_bases, lv.groupes
    lv.reprendre_pays = lambda gid: ordre.append(("pays", gid)) or {}
    lv.reprendre_bases = lambda gid: ordre.append(("bases", gid)) or {}
    lv.groupes = lambda eq, essais=3: None
    try:
        lv.synchroniser(TW)
    finally:
        lv.reprendre_pays, lv.reprendre_bases, lv.groupes = vrai_rp, vrai_rb, vrai_groupes
    check("la synchro (30 min) reprend les pays puis les pages de base", ordre == [("pays", TW), ("bases", TW)],
          ordre)

    # ── Twitter sans Seren : 70 tracking Lia / 30 page Lia (02/11/2026) ──
    # « pour Twitter uniquement, le trafic uniquement sur Lia », « 70 avec
    # tracking et 30 sans tracking »
    CONFIG_LIA = {k: v for k, v in CONFIG_4.items() if k != "lia_seule"}
    monde4(config=CONFIG_LIA)
    e = lv.espace(TW)
    check("Twitter par défaut : plus de variante Seren, la page de base seule à 70 / 30",
          e.get("variante") is None and e.get("base_seule") == {"controle": 70, "base_modele": 30}
          and lv.espace("").get("base_seule") == e.get("base_seule"), e)
    # 03/11/2026, « Lia seule partout » : Agency et Threads aussi
    check("… Agency et Threads aussi, depuis le 03/11 (même « base_seule »)",
          lv.espace(lv.AGENCY_IG_ID).get("base_seule") == e.get("base_seule")
          and lv.espace(lv.THREADS_ID).get("base_seule") == e.get("base_seule")
          and lv.espace(lv.AGENCY_IG_ID).get("variante") is None
          and lv.espace(lv.THREADS_ID).get("variante") is None)
    monde4(config=dict(CONFIG_LIA, lia_seule=False))
    check("« lia_seule » : false ramène Seren sur Twitter",
          lv.espace(TW).get("variante") is not None and lv.espace(TW).get("base_seule") is None)

    # nouveau lien : deux branches, aucun tracking Seren
    g, suivis = monde4(config=CONFIG_LIA)
    r = lv.creer_pour(TW, "n2", "nova2", manager="YAZID")
    sc = r.get("shortcode") or "?"
    cfg, br = branches(g, sc)
    check("lien neuf : 70 tracking Lia / 30 page Lia, rien d'autre",
          r.get("ok") and r.get("variante") is None and cfg.get("enabled") and cfg.get("controlWeight") == 70
          and {n: v["weight"] for n, v in br.items()} == {"Base Lia": 30}
          and ((br.get("Base Lia") or {}).get("copie") or {}).get("url") == LIA_P, (r, cfg))
    check("… aucun tracking Seren demandé à MyPuls (ils ne s'effacent pas)",
          [c for _n, c in suivis] == [None], suivis)
    check("… copie temporaire supprimée, fiche notée",
          len(g.de("delete")) == len(g.de("duplicate")) - 1
          and (lv.lien_de(TW, "n2").get("base_seule") or {}).get("ok") is True, (g.appels, lv.lien_de(TW, "n2")))

    # les liens à quatre branches : Seren et « Base Seren » retirées, « Base Lia » gardée
    g, _s = monde4(config=CONFIG_LIA, etat={"liens": {f"{TW}:d": fiche4(32, "babeyy")}})
    g.liens["lnk_babeyy"] = {"id": "lnk_babeyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["babeyy"] = ab4(*QUATRE)
    b = lv.reprendre_bases(TW)
    cfg, br = branches(g, "babeyy")
    post = g.de("post")
    check("lien à quatre branches : passé à 70 / 30, « Base Lia » gardée à son variantId, sans copie",
          b["poses"] == ["babeyy"] and cfg.get("controlWeight") == 70 and list(br) == ["Base Lia"]
          and br["Base Lia"]["variantId"] == "vL" and br["Base Lia"]["weight"] == 30
          and not g.de("duplicate") and len(post) == 1, (b, cfg, g.appels))
    n = len(g.appels)
    b = lv.reprendre_bases(TW)
    check("… noté : la reprise n'y revient pas", len(g.appels) == n and not b["poses"], (b, g.appels[n:]))

    # les 34 liens passés à la main le 02/11 : reconnus, rien réécrit
    g, _s = monde4(config=CONFIG_LIA, etat={"liens": {f"{TW}:d": fiche4(32, "babeyy")}})
    g.liens["lnk_babeyy"] = {"id": "lnk_babeyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["babeyy"] = ab4(("vL", "Base Lia", 30, LIA_P), controle=70)
    b = lv.reprendre_bases(TW)
    check("lien déjà à 70 / 30 : reconnu, AUCUN enregistrement",
          b["deja"] == ["babeyy"] and not g.de("post") and not g.de("duplicate"), (b, g.appels))

    # une variante inconnue : on ne devine pas
    g, _s = monde4(config=CONFIG_LIA, etat={"liens": {f"{TW}:d": fiche4(32, "babeyy")}})
    g.liens["lnk_babeyy"] = {"id": "lnk_babeyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["babeyy"] = ab4(("vX", "Autre", 30, "https://onlyfans.com/autre"), controle=70)
    b = lv.reprendre_bases(TW)
    check("variante inconnue : rien touché, et dit", not g.de("post") and b["rates"], (b, g.appels))

    # la règle des pays ne recopie plus la variante Seren sur Twitter
    g, _s = monde4(config=CONFIG_LIA, etat={"liens": {f"{TW}:d": fiche4(32, "babeyy", pays=False)}})
    g.liens["lnk_babeyy"] = {"id": "lnk_babeyy", "type": "directlink", "url": f"{LIA_P}/c60"}
    g.abs["babeyy"] = ab4(("vL", "Base Lia", 30, LIA_P), controle=70)
    lv.reprendre_pays(TW)
    check("reprendre_pays : la variante Seren n'est pas recopiée sur Twitter",
          not g.de("post") and not g.de("duplicate"), g.appels)
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
