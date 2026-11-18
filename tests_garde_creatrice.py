# -*- coding: utf-8 -*-
"""tests_garde_creatrice.py — un tracking neuf naît chez la bonne créatrice.

Depuis le 28/10/2026, les liens des VA partent sur Lia (MyPuls 3992). La garde
du patch local 99-z-tracking-creator-guard (VPS) ne vérifie qu'Emy et Seren :
une bascule MyPuls ratée aurait créé le tracking d'un VA chez la créatrice
d'avant, et MyPuls ne sait pas l'effacer.

Ce qui est vérifié (liens_va.creer_tracking, enveloppe _garde_creatrice ;
revenus_segments) :
  - page MyPuls de Lia seule : création, sous le verrou de bascule, cookies
    tournés enregistrés AVANT ;
  - page d'une autre créatrice, ou bascule renvoyée ailleurs : rien créé ;
  - tracking rendu hors du profil de Lia : arrêt dit (« arreter ») ;
  - créatrice que la table ne connaît pas (MYM) : rien ne change ;
  - sans creator_id : celle de la config ;
  - _creer_ou_reprendre passe par la garde pour créer, pas pour reprendre ;
  - Lia est comptée en OF US dans les revenus ;
  - le parrainage d'Agency garde les subs Emy d'un filleul basculé (cumul) ;
  - la page du code par e-mail de MyPuls (« Confirmez votre connexion ») est
    dite telle quelle, pas « page de personne » (capture du 18/11/2026) ;
  - l'API officielle passe devant (enveloppe _api_d_abord) : tracking créé
    sans session ; refus net : repli sur la session ; réponse douteuse :
    repris par son nom ou arrêt, jamais de second envoi ;
  - mypuls.api_post : change de clé sur 401 / 403 / 429, ne renvoie jamais
    après un délai dépassé, un 5xx ou une page web.

Faux MyPuls : aucun appel réseau, rien dans data/.
Lancement : python tests_garde_creatrice.py
"""
from __future__ import annotations

import io
import json
import pathlib
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import mypuls                          # noqa: E402
import revenus_segments as rs          # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


LIA = "https://onlyfans.com/liasxcret"


def page(*profils):
    return "".join(f'<tr id="row-link-{i}"><td>x</td><td>{p}/c{i}</td></tr>'
                   for i, p in enumerate(profils, 1))


class Rep:
    def __init__(self, texte="", code=200, url=""):
        self.text, self.status_code, self.url = texte, code, url


class Sess:
    """La session MyPuls : la page de tracking-stats montre la créatrice
    qu'on lui a dit de montrer (MONDE["page"])."""
    def get(self, url, **kw):
        JOURNAL.append(("get", url.split("mypuls.app")[-1], mypuls._OF_SWITCH_LOCK._is_owned()))
        if MONDE.get("code_demande"):
            # MyPuls renvoie tout vers sa page « Confirmez votre connexion »
            return Rep("<h1>Confirmez votre connexion</h1>", 200, "https://mypuls.app/securite/verifier")
        if "/switch-creator/" in url:
            return Rep(code=MONDE["code_bascule"])
        return Rep(MONDE["page"])


JOURNAL: list = []
MONDE = {"page": page(LIA, LIA), "code_bascule": 200, "rendu": f"{LIA}/c200"}


def faux_creer(nom, creator_id=None):
    JOURNAL.append(("creer", nom, creator_id, mypuls._OF_SWITCH_LOCK._is_owned()))
    return {"ok": True, "url": MONDE["rendu"], "code": MONDE["rendu"].rsplit("/", 1)[-1], "erreur": ""}


TMP = pathlib.Path(tempfile.mkdtemp(prefix="garde_creatrice_"))
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "_tracking_existant", "TRACKING_PAR_API")}
_SAUVE_MP = {k: getattr(mypuls, k) for k in ("_make_session", "_save_rotated_cookies", "api_post",
                                             "_cle_disponible", "_noter_cle", "_reprises_possibles")}


def _api_interdite(*a, **k):
    raise AssertionError("API MyPuls non bouchonnée : un test créerait un vrai tracking")
try:
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.CONFIG_FICHIER.write_text(json.dumps({"creator_id": 3992, "modele": "Lia", "mypuls_actif": True}))
    mypuls._make_session = lambda: Sess()
    mypuls._save_rotated_cookies = lambda s: JOURNAL.append(("cookies",))
    mypuls.api_post = _api_interdite      # jamais un vrai envoi depuis ces tests
    garde = lv._garde_creatrice(faux_creer)

    # ── la table, une seule ──
    check("Lia dans la table des comptes OF : profil liasxcret",
          lv.profil_of(3992) == LIA and rs.COMPTES_OF[3992] == ("Lia", "liasxcret"), lv.profil_of(3992))
    check("… Lia comptée en OF US dans les revenus (plus en OF FR)",
          rs.creator_segment(3992, "onlyfans") == "of_us" and 3992 in mypuls.OF_US_CREATOR_IDS)
    check("creer_tracking du module est gardé, son corps reste joignable (.brut)",
          lv.creer_tracking.__wrapped__ is not None and hasattr(lv.creer_tracking, "brut")
          and lv.creer_tracking.brut is lv.creer_tracking.__wrapped__.brut)

    # ── bascule réussie ──
    JOURNAL.clear()
    r = garde("Twitter VA 150 @neuf", 3992)
    etapes = [e[0] for e in JOURNAL]
    check("page de Lia seule : tracking créé chez Lia",
          r.get("ok") and r["url"] == f"{LIA}/c200" and ("creer", "Twitter VA 150 @neuf", 3992, True) in JOURNAL,
          (r, JOURNAL))
    check("… bascule vérifiée, cookies enregistrés, PUIS création — tout sous le verrou",
          etapes == ["get", "get", "cookies", "creer"]
          and JOURNAL[0][1].startswith("/switch-creator/3992") and JOURNAL[1][1] == "/tracking-stats/"
          and all(e[-1] is True for e in JOURNAL if e[0] in ("get", "creer")), JOURNAL)

    # ── sans creator_id : la config ──
    JOURNAL.clear()
    r = garde("Twitter VA 151 @cfg")
    check("sans creator_id : la créatrice de la config (Lia), vérifiée",
          r.get("ok") and JOURNAL[0][1].startswith("/switch-creator/3992")
          and ("creer", "Twitter VA 151 @cfg", None, True) in JOURNAL, JOURNAL)

    # ── bascule ratée : page d'une autre ──
    for label, pg, code in (("page de Seren (bascule restée sur elle)", page("https://onlyfans.com/seren.vale"), 200),
                            ("page de Lia ET d'Emy", page(LIA, "https://onlyfans.com/emy.brw"), 200),
                            ("page vide", "", 200),
                            ("bascule renvoyée ailleurs (HTTP 302 suivi en 404)", page(LIA), 404)):
        MONDE.update(page=pg, code_bascule=code)
        JOURNAL.clear()
        r = garde("Twitter VA 152 @rate", 3992)
        check(f"{label} : rien créé, dit",
              not r.get("ok") and r.get("refuse") and "rien créé" in r.get("erreur", "")
              and not [e for e in JOURNAL if e[0] == "creer"], (r, JOURNAL))
    MONDE.update(page=page(LIA), code_bascule=200)

    # ── créé quand même ailleurs ──
    MONDE["rendu"] = "https://onlyfans.com/emy.brw/c140"
    r = garde("Twitter VA 153 @ailleurs", 3992)
    check("tracking rendu chez Emy : arrêt dit, adresse donnée pour vérifier",
          not r.get("ok") and r.get("arreter") and r.get("tracking") == "https://onlyfans.com/emy.brw/c140", r)
    MONDE["rendu"] = f"{LIA}/c200"

    # ── créatrice inconnue de la table (MYM) ──
    JOURNAL.clear()
    r = garde("Amelia_VA_9", 769)
    check("créatrice hors table (MYM 769) : création directe, aucune bascule de plus",
          r.get("ok") and [e[0] for e in JOURNAL] == ["creer"], JOURNAL)

    # ── session absente ──
    mypuls._make_session = lambda: None
    JOURNAL.clear()
    r = garde("Twitter VA 154 @sans", 3992)
    check("sans session MyPuls : refusé, rien créé",
          not r.get("ok") and r.get("refuse") and not JOURNAL, (r, JOURNAL))
    mypuls._make_session = lambda: Sess()

    # ── _creer_ou_reprendre : créer passe par la garde, reprendre non ──
    _sauve_ct = lv.creer_tracking
    try:
        lv.creer_tracking = garde
        lv._tracking_existant = lambda nom, cid: ({"url": f"{LIA}/c60", "code": "c60"}
                                                  if nom == "Twitter VA 32 @bid_a" else None)
        JOURNAL.clear()
        r = lv._creer_ou_reprendre("Twitter VA 32 @bid_a", 3992)
        check("tracking déjà chez Lia : repris, aucune bascule",
              r.get("ok") and r.get("repris") and not JOURNAL, (r, JOURNAL))
        r = lv._creer_ou_reprendre("Twitter VA 155 @nouveau", 3992)
        check("tracking neuf : créé à travers la garde",
              r.get("ok") and [e[0] for e in JOURNAL] == ["get", "get", "cookies", "creer"], (r, JOURNAL))
    finally:
        lv.creer_tracking = _sauve_ct

    # ── la page du code par e-mail : dite, pas « page de personne » ──
    MONDE["code_demande"] = True
    JOURNAL.clear()
    r = garde("Twitter VA 250 @prego555", 3992)
    check("MyPuls demande son code par e-mail : rien créé, et c'est dit tel quel",
          not r.get("ok") and r.get("refuse") and r.get("code_demande")
          and mypuls.VERIFICATION_MYPULS in r.get("erreur", "") and "rien créé" in r["erreur"]
          and "personne" not in r["erreur"] and not [e for e in JOURNAL if e[0] == "creer"], (r, JOURNAL))
    MONDE["code_demande"] = False

    # ── l'API officielle d'abord (18/11/2026) ──
    APPELS: list = []
    CREE = {"ok": True, "statut": 201, "data": {"creator_id": 3992, "code": "c201", "name": "x",
                                                "url": f"{LIA}/c201", "group_ids": [], "created": True}}
    API = {"rep": CREE}
    EXISTE: dict = {}

    def faux_post(path, corps=None, _essai=0):
        APPELS.append((path, corps))
        return API["rep"]

    mypuls.api_post = faux_post
    lv._tracking_existant = lambda nom, cid: EXISTE.get(nom)
    api = lv._api_d_abord(garde)

    check("creer_tracking du module : l'API devant la garde, le corps toujours joignable (.brut)",
          lv.creer_tracking.__wrapped__.__wrapped__ is not None
          and lv.creer_tracking.brut is lv.creer_tracking.__wrapped__.brut and lv.TRACKING_PAR_API is True)

    def essai(nom="Twitter VA 250 @prego555", cid=3992):
        JOURNAL.clear()
        APPELS.clear()
        return api(nom, cid) if cid else api(nom)

    r = essai()
    check("API MyPuls : tracking créé chez Lia, sans ouvrir la session du site",
          r.get("ok") and r["url"] == f"{LIA}/c201" and r["code"] == "c201" and r.get("par_api")
          and APPELS == [("creators/3992/tracking-links", {"name": "Twitter VA 250 @prego555"})]
          and not JOURNAL, (r, APPELS, JOURNAL))
    r = essai(cid=None)
    check("… sans creator_id : la créatrice de la config, nommée dans l'adresse de l'API",
          r.get("ok") and APPELS[0][0] == "creators/3992/tracking-links" and not JOURNAL, (r, APPELS))
    r = essai(nom="  Twitter VA 251 @" + "x" * 80)
    check("… le nom envoyé est celui que la session aurait donné (60 caractères, sans bords)",
          r.get("ok") and len(APPELS[0][1]["name"]) == 60 and APPELS[0][1]["name"].startswith("Twitter VA 251 @x"),
          APPELS)
    API["rep"] = {"ok": True, "statut": 200, "data": {"data": {"code": "c202", "url": "https://www.onlyfans.com/liasxcret/c202/"}}}
    r = essai()
    check("… réponse emballée, « www. » et barre finale : la même adresse que les autres trackings",
          r.get("ok") and r["url"] == f"{LIA}/c202" and r["code"] == "c202", r)

    API["rep"] = {"ok": False, "statut": 403, "rien_cree": True, "error": "Token API refusé (HTTP 403)"}
    r = essai()
    check("API qui refuse net (403) : repli sur la session du site, à travers la garde",
          r.get("ok") and r["url"] == f"{LIA}/c200" and len(APPELS) == 1
          and [e[0] for e in JOURNAL] == ["get", "get", "cookies", "creer"], (r, JOURNAL))
    MONDE["code_demande"] = True
    r = essai()
    check("… et la session derrière le code par e-mail : rien créé, les deux raisons dites",
          not r.get("ok") and r.get("refuse") and mypuls.VERIFICATION_MYPULS in r["erreur"]
          and "Token API refusé (HTTP 403)" in r["erreur"] and not [e for e in JOURNAL if e[0] == "creer"],
          (r, JOURNAL))
    MONDE["code_demande"] = False

    API["rep"] = {"ok": False, "statut": 0, "rien_cree": False, "error": "l'API n'a pas répondu (ReadTimeout)"}
    r = essai()
    check("API douteuse (délai dépassé), tracking introuvable : arrêt, ni session ni second envoi",
          not r.get("ok") and r.get("refuse") and "reclique" in r["erreur"] and len(APPELS) == 1 and not JOURNAL,
          (r, APPELS, JOURNAL))
    EXISTE["Twitter VA 250 @prego555"] = {"url": f"{LIA}/c203", "code": "c203"}
    r = essai()
    check("API douteuse, mais le tracking est chez MyPuls sous ce nom : repris",
          r.get("ok") and r.get("repris") and r["url"] == f"{LIA}/c203" and len(APPELS) == 1 and not JOURNAL, r)
    API["rep"] = {"ok": True, "statut": 201, "data": {"created": True}}
    r = essai()
    check("API « créé » sans adresse : retrouvé par son nom",
          r.get("ok") and r.get("repris") and r["url"] == f"{LIA}/c203" and not JOURNAL, r)
    EXISTE.clear()
    r = essai()
    check("… introuvable : dit « à vérifier », aucune création de plus",
          not r.get("ok") and "à vérifier" in r["erreur"] and not r.get("repli") and not JOURNAL, (r, JOURNAL))

    API["rep"] = {"ok": True, "statut": 201, "data": {"code": "c141", "url": "https://onlyfans.com/emy.brw/c141"}}
    r = essai()
    check("API qui rend un tracking chez Emy : arrêt dit, adresse donnée pour vérifier",
          not r.get("ok") and r.get("arreter") and r.get("tracking") == "https://onlyfans.com/emy.brw/c141"
          and not JOURNAL, r)
    API["rep"] = CREE

    r = essai(nom="Amelia_VA_9", cid=769)
    check("créatrice hors table (MYM 769) : l'API OnlyFans n'est pas appelée",
          r.get("ok") and not APPELS and [e[0] for e in JOURNAL] == ["creer"], (APPELS, JOURNAL))
    lv.TRACKING_PAR_API = False
    r = essai()
    check("TRACKING_PAR_API éteint : la session seule, comme avant",
          r.get("ok") and not APPELS and [e[0] for e in JOURNAL] == ["get", "get", "cookies", "creer"],
          (APPELS, JOURNAL))
    lv.TRACKING_PAR_API = True

    def casse(path, corps=None, _essai=0):
        APPELS.append((path, corps))
        raise RuntimeError("boum")
    mypuls.api_post = casse
    r = essai()
    check("API qui plante en route : arrêt, pas de création par la session derrière",
          not r.get("ok") and r.get("refuse") and "à vérifier" in r["erreur"] and not JOURNAL, (r, JOURNAL))
    mypuls.api_post = faux_post

    _sauve_ct2 = lv.creer_tracking
    try:
        lv.creer_tracking = api
        EXISTE["Twitter VA 32 @bid_a"] = {"url": f"{LIA}/c60", "code": "c60"}
        JOURNAL.clear()
        APPELS.clear()
        r = lv._creer_ou_reprendre("Twitter VA 32 @bid_a", 3992)
        check("_creer_ou_reprendre, tracking déjà là : repris, ni API de création ni session",
              r.get("ok") and r.get("repris") and not APPELS and not JOURNAL, (r, APPELS, JOURNAL))
        r = lv._creer_ou_reprendre("Twitter VA 252 @neuf", 3992)
        check("_creer_ou_reprendre, tracking neuf : créé par l'API",
              r.get("ok") and r.get("par_api") and len(APPELS) == 1 and not JOURNAL, (r, APPELS, JOURNAL))
    finally:
        lv.creer_tracking = _sauve_ct2
        EXISTE.clear()

    # ── mypuls.api_post : ce qu'une réponse prouve ──
    import requests as _rq

    class RepHttp:
        def __init__(self, code, corps=None, texte="", entetes=None):
            self.status_code, self._corps, self.headers = code, corps, entetes or {}
            self.text = texte or (json.dumps(corps) if corps is not None else "")

        def json(self):
            if self._corps is None:
                raise ValueError("pas du JSON")
            return self._corps

    ENVOIS: list = []
    FILE: list = []
    NOTES: list = []

    def faux_requests_post(url, headers=None, json=None, timeout=None):
        ENVOIS.append((url, (headers or {}).get("X-API-TOKEN"), json))
        rep = FILE.pop(0)
        if isinstance(rep, Exception):
            raise rep
        return rep

    _sauve_rq = _rq.post
    try:
        _rq.post = faux_requests_post
        mypuls.api_post = _SAUVE_MP["api_post"]
        mypuls._cle_disponible = lambda: (f"k{len(ENVOIS)}", f"tok{len(ENVOIS)}")
        mypuls._noter_cle = lambda *a, **k: NOTES.append((a, k))
        mypuls._reprises_possibles = lambda: 2

        def envoi(*reps):
            ENVOIS.clear()
            NOTES.clear()
            FILE[:] = list(reps)
            return mypuls.api_post("creators/3992/tracking-links", {"name": "Twitter VA 250 @prego555"})

        r = envoi(RepHttp(201, {"code": "c201", "url": f"{LIA}/c201", "created": True}))
        check("api_post, 201 : créé, un seul envoi, à la bonne adresse, le nom dans le corps",
              r.get("ok") and r["statut"] == 201 and r["data"]["code"] == "c201"
              and ENVOIS == [("https://mypuls.app/api/v1/creators/3992/tracking-links", "tok0",
                              {"name": "Twitter VA 250 @prego555"})], (r, ENVOIS))
        r = envoi(RepHttp(403, {"message": "Creator hors de votre périmètre"}),
                  RepHttp(201, {"code": "c201", "url": f"{LIA}/c201"}))
        check("api_post, 403 puis 201 : la clé suivante du trousseau a le droit, créé",
              r.get("ok") and [e[1] for e in ENVOIS] == ["tok0", "tok1"], (r, ENVOIS))
        r = envoi(RepHttp(429, {}, entetes={"Retry-After": "7"}), RepHttp(201, {"url": f"{LIA}/c201"}))
        check("api_post, 429 puis 201 : clé mise au repos, la suivante crée",
              r.get("ok") and len(ENVOIS) == 2 and any(k.get("repos_s") == 7.0 for _a, k in NOTES), (r, NOTES))
        r = envoi(RepHttp(403, {}), RepHttp(403, {}), RepHttp(403, {}))
        check("api_post, 403 sur toutes les clés : refus net, rien créé",
              not r.get("ok") and r.get("rien_cree") is True and r["statut"] == 403 and len(ENVOIS) == 3, (r, ENVOIS))
        r = envoi(RepHttp(400, {"message": "creator non OnlyFans"}))
        check("api_post, 400 : refus net avec la raison de MyPuls, un seul envoi",
              not r.get("ok") and r.get("rien_cree") is True and "creator non OnlyFans" in r["error"]
              and len(ENVOIS) == 1, (r, ENVOIS))
        for label, rep in (("502", RepHttp(502, {"message": "Échec de la création côté OnlyFans"})),
                           ("délai dépassé", _rq.exceptions.ReadTimeout("trop long")),
                           ("page web à la place du JSON", RepHttp(200, None, "<html>connexion</html>"))):
            r = envoi(rep, RepHttp(201, {"url": f"{LIA}/c999"}))
            check(f"api_post, {label} : douteux, JAMAIS renvoyé",
                  not r.get("ok") and r.get("rien_cree") is False and len(ENVOIS) == 1, (r, ENVOIS))
        mypuls._cle_disponible = lambda: ("", "")
        r = envoi(RepHttp(201, {"url": f"{LIA}/c999"}))
        check("api_post, aucune clé : refus net, rien envoyé",
              not r.get("ok") and r.get("rien_cree") is True and not ENVOIS, (r, ENVOIS))
    finally:
        _rq.post = _sauve_rq
        mypuls.api_post = _api_interdite

    # ── parrainage Agency : le cumul garde les subs Emy d'avant la bascule ──
    import agency_accueil as aa
    fiche = {"tracking": f"{LIA}/c104", "anciens_trackings": ["https://onlyfans.com/emy.brw/c117/"],
             "variante": {"posee": True, "tracking": "https://onlyfans.com/seren.vale/c240"}}
    compte = {f"{LIA}/c104": 1, "https://onlyfans.com/emy.brw/c117": 7, "https://onlyfans.com/seren.vale/c240": 1}
    check("parrainage Agency : Lia + Seren + Emy d'avant la bascule (1 + 1 + 7)",
          aa.subs_fiche(fiche, compte) == 9, aa.subs_fiche(fiche, compte))
    check("… une adresse que MyPuls ne rend pas : inconnu, pas un cumul partiel",
          aa.subs_fiche(fiche, {f"{LIA}/c104": 1, "https://onlyfans.com/seren.vale/c240": 1}) is None)
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    for k, v in _SAUVE_MP.items():
        setattr(mypuls, k, v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
