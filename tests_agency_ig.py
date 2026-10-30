# -*- coding: utf-8 -*-
"""tests_agency_ig.py — Agency VA INSTAGRAM monté « comme Twitter » (22/10/2026).

Propriétaire : liens dans EMY IG (« MIG »), « pour le moment mets juste le
lien direct » vers le tracking Emy du VA, « Instagram VA n », pas d'Outlook.

Ce qui est vérifié :
  - liens_va.espace : EMY IG, lien direct, plateforme Instagram, tracking Emy,
    jamais de variante (pause Seren levée ou pas) ; manque() sans gabarit ;
  - creer_pour : un tracking au nom « Instagram VA n @pseudo », puis un
    directlink DANS EMY IG vers ce tracking, sans copie de gabarit ;
  - un gabarit posé un jour (clé agency_ig de la config) : la copie revient ;
  - tickets_discord.boutons_va : Créer son lien, Mon adresse USDC, Mes stats ;
  - subs_va : les trackings et le pseudo du VA viennent de sa fiche ;
  - podium_discord.clics_du_va : SON lien (celui de la fiche), au marché US.

Faux GetMySocial, faux MyPuls : aucun appel réseau, rien dans data/.
Lancement : python tests_agency_ig.py
"""
from __future__ import annotations

import datetime as dt
import inspect
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

import liens_va as lv                  # noqa: E402
import podium_discord as pod           # noqa: E402
# le calcul VA par VA : le registre de ces tests n'a pas de fiche liens_va,
# tout y serait « compte interne » réuni en VA 41 (tests_va_interne.py)
pod.INTERNES_REUNIS = False
import subs_va as sv                   # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


AG = lv.AGENCY_IG_ID
EMY_IG = "tm_6ada83b07218da6450e65862"
CONFIG = {"gabarit": "lnk_gabarit_twitter", "equipe": lv.EQUIPE_VA, "mypuls_actif": True,
          "creator_id": 3352, "modele": "Emy"}


class FauxGMS(types.ModuleType):
    PUBLIC_LINK_DOMAIN = "https://getmysocial.com"

    def __init__(self):
        super().__init__("gms")
        self.appels = []

    def de(self, genre):
        return [a for a in self.appels if a[0] == genre]

    def create_directlink(self, sc, url, nom="", team_id=None, deeplink_mode=""):
        self.appels.append(("direct", sc, url, nom, team_id))
        self.deeplink = deeplink_mode
        self.liens = getattr(self, "liens", {})
        self.liens[f"lnk_{sc}"] = {"type": "directlink", "url": url}
        return {"ok": True, "link": {"id": f"lnk_{sc}", "url": url}}

    refus_maj = False

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        # la copie d'une landing de JESSY LE RETOUR : la page Emy, son bouton
        # vers le tracking d'un AUTRE VA (celui du gabarit)
        self.liens = getattr(self, "liens", {})
        self.liens[f"lnk_{sc}"] = {"type": "landing", "buttons": [
            {"label": "“exclusive” stuff lol ", "url": "https://onlyfans.com/emy.brw/c27",
             "button_effect": "2", "container_color": "#d99be3"}]}
        return {"ok": True, "link": {"id": f"lnk_{sc}", "url": url}}

    # la règle des pays (liens_va.poser_pays) passe par gms.get_link / update_link
    def get_link(self, lid, team_id=None):
        l = getattr(self, "liens", {}).get(lid)
        return {"ok": l is not None, "link": json.loads(json.dumps(l)) if l else None,
                "error": "" if l else "link_not_found"}

    def update_link(self, lid, champs, team_id=None):
        self.appels.append(("pays", lid))
        self.liens[lid].update(json.loads(json.dumps(champs)))
        return {"ok": True, "link": self.liens[lid]}

    def disable_link(self, lid):
        self.appels.append(("disable", lid))
        return {"ok": True}

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "list_groups":
            return {"ok": True, "data": {"data": [{"name": "GONE", "id": "grp_g"}]}}
        if outil == "get_link":
            return {"ok": True, "data": json.loads(json.dumps(
                getattr(self, "liens", {}).get(args["link_id"]) or {}))}
        if outil == "update_link" and "buttons" in args:
            if self.refus_maj:
                return {"ok": False, "error": "429"}
            self.liens[args["link_id"]]["buttons"] = args["buttons"]
        return {"ok": True, "data": {}}

    def assign_link_to_group(self, link_id, gid, team_id=None):
        self.appels.append(("assign", link_id, gid, team_id))
        return {"ok": True}

    def lire_ab_testing(self, lid, equipe=""):
        return {"ok": True, "config": {"enabled": False, "variants": []}}

    def list_links_team(self, equipe, force_refresh=False):
        return {"links": []}


TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "ETAT_FICHIER", "COUPES_FICHIER",
                                         "numero_de", "creer_tracking", "SEREN_EN_PAUSE")}
_SAUVE_GMS = sys.modules.get("gms")
_SAUVE_POD = {k: getattr(pod, k) for k in ("liens_bruts", "_releve_liens")}


def monde(config=None, etat=None):
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    lv.COUPES_FICHIER = TMP / "liens_seren_coupes.json"
    for p in TMP.iterdir():
        p.unlink()
    lv.CONFIG_FICHIER.write_text(json.dumps(CONFIG if config is None else config))
    lv.ETAT_FICHIER.write_text(json.dumps(etat or {}))
    g = FauxGMS()
    sys.modules["gms"] = g
    lv.numero_de = lambda pseudo: 27
    suivis = []

    def faux_tracking(nom, creator_id=None):
        suivis.append((nom, creator_id))
        return {"ok": True, "url": "https://onlyfans.com/emy.brw/c300", "code": "c300"}
    lv.creer_tracking = faux_tracking
    return g, suivis


try:
    # ── l'espace ─────────────────────────────────────────────────────────
    monde()
    for pause in (True, False):
        lv.SEREN_EN_PAUSE = pause
        e = lv.espace(AG)
        # 24/10/2026 : « Instagram aussi sur Seren » — le 50/50, sauf en pause
        check(f"espace Agency (pause Seren {pause}) : EMY IG, landing de JESSY LE RETOUR, Instagram, "
              "tracking, " + ("sans variante" if pause else "variante Seren 50 % depuis un lien direct"),
              e["equipe"] == EMY_IG and e["landing"] and e["gabarit"] == "lnk_6ada9ed9cf84f313d19d14ae"
              and e["plateforme"] == "Instagram" and e["tracking"] is True
              and (e["variante"] is None if pause else
                   (e["variante"] == lv.VARIANTE_TWITTER
                    and e["source_variante"] == "lnk_6adc91b2c2f08bda9012135f")), e)
    _src = lv.ESPACE_AGENCY_IG.pop("source_variante")
    check("… sans lien direct source : Emy seule (une copie de landing finirait chez Emy)",
          lv.espace(AG)["variante"] is None)
    lv.ESPACE_AGENCY_IG["source_variante"] = _src
    import inspect as _insp
    _patche = 'e["plateforme"]} VA' in _insp.getsource(lv._poser_variante_sans_garde)
    rv = lv.poser_variante(AG, "u_inconnu")
    check("poser_variante (Agency) : sans le nommage par plateforme (patch du VPS), rien créé",
          _patche or ("Twitter VA" in rv.get("erreur", "") and rv["ok"] is False), rv)
    lv.SEREN_EN_PAUSE = True
    check("Agency fait partie des serveurs à liens", AG in lv.SERVEURS)
    check("manque() : rien ne manque (gabarit landing)", lv.manque(AG) == "", lv.manque(AG))
    _sauve_esp = dict(lv.ESPACE_AGENCY_IG)
    lv.ESPACE_AGENCY_IG["gabarit"] = ""
    check("sans gabarit : lien direct, rien ne manque", lv.manque(AG) == "", lv.manque(AG))
    monde(config=dict(CONFIG, mypuls_actif=False))
    check("… mais MyPuls fermé : refusé (un lien direct sans tracking ne serait à personne)",
          "MyPuls" in lv.manque(AG), lv.manque(AG))
    lv.ESPACE_AGENCY_IG.clear(); lv.ESPACE_AGENCY_IG.update(_sauve_esp)
    monde()
    check("Twitter et Threads ne bougent pas (leurs équipes)",
          lv.espace(lv.TWITTER_ID)["equipe"] == lv.EQUIPE_VA
          and lv.espace(lv.THREADS_ID)["equipe"] == lv.ESPACE_THREADS["equipe"])

    # ── créer : la landing de base ───────────────────────────────────────
    g, suivis = monde()
    r = lv.creer_pour(AG, "u1", "zaid014787", manager="GONE")
    dup = g.de("duplicate")
    check("landing : copie de la page de JESSY LE RETOUR dans EMY IG, SANS adresse (une landing n'en a pas)",
          r.get("ok") and len(dup) == 1 and dup[0][1] == "lnk_6ada9ed9cf84f313d19d14ae"
          and dup[0][4] == "" and dup[0][5] == EMY_IG and not g.de("direct"), g.appels)
    b0 = g.liens[f'lnk_{r["shortcode"]}']["buttons"][0]
    check("… son bouton OnlyFans mène au tracking DU VA, le reste du bouton intact",
          b0["url"] == "https://onlyfans.com/emy.brw/c300" and b0["container_color"] == "#d99be3"
          and b0["label"].startswith("“exclusive”"), b0)
    check("… un tracking chez Emy, au nom « Instagram VA 27 @zaid014787 » (landing)",
          suivis == [("Instagram VA 27 @zaid014787", None)], suivis)
    page = g.liens[f'lnk_{r["shortcode"]}']
    check("… pays (29/10/2026) : hors US/CA/AU/GB/NZ/IE, le bouton OnlyFans mène au compte de base, "
          "rien sur la page",
          len(b0.get("geofilters") or []) == 250 and "geofilters" not in page
          and {x["destination_url"] for x in b0["geofilters"]} == {"https://onlyfans.com/emy.brw"}
          and lv.lien_de(AG, "u1").get("pays") is True, (len(b0.get("geofilters") or []), page.keys()))
    g, suivis = monde()
    g.refus_maj = True
    r = lv.creer_pour(AG, "u3", "refus")
    check("bouton non posé : la copie (tracking d'un autre VA) est COUPÉE, jamais donnée",
          not r.get("ok") and g.de("disable") and not lv.lien_de(AG, "u3").get("public_url"), r)

    # ── créer : le lien direct (sans gabarit) ───────────────────────────
    lv.ESPACE_AGENCY_IG["gabarit"] = ""
    g, suivis = monde()
    r = lv.creer_pour(AG, "u1", "zaid014787", manager="GONE")
    check("lien créé", r.get("ok") and r.get("plateforme") == "Instagram", r)
    check("… un tracking chez Emy, au nom « Instagram VA 27 @zaid014787 »",
          suivis == [("Instagram VA 27 @zaid014787", None)], suivis)
    d = g.de("direct")
    check("… un lien DIRECT dans EMY IG vers ce tracking, sans copie de gabarit",
          len(d) == 1 and d[0][2] == "https://onlyfans.com/emy.brw/c300"
          and d[0][3] == "Instagram VA 27 @zaid014787" and d[0][4] == EMY_IG
          and not g.de("duplicate"), g.appels)
    check("… avec le deeplink « pageload » (sortir du navigateur d'Instagram)",
          getattr(g, "deeplink", "") == "pageload")
    geo = g.liens[f'lnk_{r["shortcode"]}'].get("geofilters") or []
    check("… et la liste des pays sur le lien direct, vers le compte de base",
          len(geo) == 250 and {x["destination_url"] for x in geo} == {"https://onlyfans.com/emy.brw"},
          len(geo))
    f = lv.lien_de(AG, "u1")
    check("… la fiche : numéro, tracking, lien", f.get("numero") == 27
          and f.get("tracking", "").endswith("/c300") and f.get("link_id", "").startswith("lnk_"), f)
    check("… et aucun 50/50 : pas de variante au résultat", r.get("variante") is None, r)
    lv.ESPACE_AGENCY_IG.clear(); lv.ESPACE_AGENCY_IG.update(_sauve_esp)

    g, suivis = monde(config=dict(CONFIG, agency_ig={"gabarit": "lnk_tpl_ig"}))
    r = lv.creer_pour(AG, "u2", "mike047639")
    check("un gabarit posé un jour (agency_ig.gabarit) : la copie revient, dans EMY IG",
          r.get("ok") and g.de("duplicate") and g.de("duplicate")[0][1] == "lnk_tpl_ig"
          and g.de("duplicate")[0][5] == EMY_IG and not g.de("direct"), g.appels)

    # ── les boutons du ticket ────────────────────────────────────────────
    b = [c for rg in tk.boutons_va("u1", confirme=True, gid=AG) for c in rg["components"]]
    ids = [c["custom_id"].split(":")[0] + ":" + c["custom_id"].split(":")[1] for c in b]
    check("accueil Agency : Créer son lien, Mon adresse USDC, Mes stats",
          "lien:new" in ids and "usdc:set" in ids and "subs:total" in ids
          and [c["label"] for c in b if c["custom_id"].startswith("subs:total")] == ["Mes stats"], b)
    b2 = [c for rg in tk.boutons_va("u1", confirme=True, gid=AG) for c in rg["components"]]
    check("… un seul « Mes stats »", sum(1 for c in b2 if c["custom_id"].startswith("subs:total")) == 1)

    # ── subs et clics ────────────────────────────────────────────────────
    monde(etat={"liens": {f"{AG}:u1": {"pseudo": "zaid014787", "numero": 27, "link_id": "lnk_abc",
                                       "tracking": "https://onlyfans.com/emy.brw/c300"}}})
    check("subs_va : Agency disponible, trackings et pseudo de la fiche",
          sv.disponible(AG) and sv.trackings_du_va(AG, "u1") == [("of", "https://onlyfans.com/emy.brw/c300")]
          and sv.pseudo_du_va(AG, "u1") == "zaid014787")
    vus = []
    pod.liens_bruts = lambda gid, etiq="podium": ([{"id": "lnk_abc", "type": "directlink"}], True)

    def faux_releve(gid, ids_, d0, d1, mesure, etiq, directs):
        vus.append((gid, list(ids_), mesure, sorted(directs)))
        return 9, {"US": 4, "FR": 5}
    pod._releve_liens = faux_releve
    c = pod.clics_du_va(AG, "u1", [(dt.date(2026, 10, 16), dt.date(2026, 10, 22))])
    check("clics_du_va : SON lien seulement, direct, US · GBL",
          c == [(4, 9)] and vus == [(AG, ["lnk_abc"], "gms_bouton", ["lnk_abc"])], (c, vus))
    check("profil Agency : subs, Wario, Mes stats, USDC",
          pod._profil(AG)["unite"] == "subs" and pod._profil(AG)["bot"] == "Wario"
          and pod._profil(AG)["mes_stats"] and pod._profil(AG)["bouton_usdc"])

    # ── adopter un salon fait à la main ──────────────────────────────────
    _sauve_tk = {k: getattr(tk, k) for k in ("_api", "ETAT_FICHIER", "managers")}
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.ETAT_FICHIER.write_text("{}")
    monde()
    appels = []
    SALONS = {
        "c1": {"id": "c1", "name": "zaid", "type": 0, "parent_id": "cat",
               "permission_overwrites": [{"type": 0, "id": "rm", "allow": "1024", "deny": "0"},
                                         {"type": 1, "id": "v1", "allow": "1024", "deny": "0"}]},
        "c2": {"id": "c2", "name": "gone", "type": 0, "parent_id": "cat",
               "permission_overwrites": [{"type": 1, "id": "m1", "allow": "1024", "deny": "0"}]},
        "c3": {"id": "c3", "name": "general", "type": 0, "parent_id": "autre",
               "permission_overwrites": [{"type": 1, "id": "v1", "allow": "1024", "deny": "0"}]},
        "cat": {"id": "cat", "name": "🔵┤ Manager GONE ├🔵", "type": 4},
        "autre": {"id": "autre", "name": "💬 DISCUSSION", "type": 4}}
    MEMBRES = {"v1": {"user": {"id": "v1", "username": "zaid014787"}, "roles": ["r_deb"]},
               "m1": {"user": {"id": "m1", "username": "jrm_12."}, "roles": ["rm"]}}

    def faux_api(methode, chemin, **kw):
        appels.append((methode, chemin, kw.get("json")))
        if methode == "GET" and chemin.startswith("/channels/"):
            c_ = SALONS.get(chemin.split("/")[2])
            return (200, c_) if c_ else (404, {})
        if methode == "GET" and chemin.endswith("/roles"):
            return 200, [{"id": "rm", "name": "MANAGER VA"}, {"id": "r_deb", "name": "VA débutant"}]
        if methode == "GET" and "/members/" in chemin:
            m_ = MEMBRES.get(chemin.rsplit("/", 1)[1])
            return (200, m_) if m_ else (404, {})
        if methode == "POST" and chemin.endswith("/messages"):
            return 200, {"id": "msg1"}
        if methode == "PUT" and "/pins/" in chemin:
            return 204, {}
        return 200, {}
    tk._api = faux_api
    tk.managers = lambda gid, force=False: [{"user": {"id": "m1", "username": "jrm_12."},
                                             "nick": "MANAGER | Gone"}]
    r = tk.adopter_salon(AG, "c1")
    check("adopter à blanc : le VA du salon, son manager (catégorie GONE), en essai (VA débutant)",
          r["ok"] and r["uid"] == "v1" and r["manager"] == "m1" and r["essai"]
          and not [a for a in appels if a[0] != "GET"], r)
    labels = [b["label"] for rg in r["corps"]["components"] for b in rg["components"]]
    # 30/10/2026 : 📤 Spoofer et ⬇️ Download avant le Numéro (outils_tickets,
    # « vas-y ajoute dans trust agency »)
    check("… l'accueil : USDC, Mes stats, Spoofer, Download, Numéro, puis 🌱 Passer Débutant "
          "(en essai), Créer son lien, et aucune mention",
          labels == ["Mon adresse USDC", "Mes stats", "Spoofer", "Download", "Numéro",
                     "Passer Débutant", "Créer son lien"]
          and r["corps"]["allowed_mentions"] == {"parse": []}, labels)
    check("salon d'un manager : refusé", not tk.adopter_salon(AG, "c2")["ok"])
    check("salon hors des catégories de managers : refusé", not tk.adopter_salon(AG, "c3")["ok"])
    appels.clear()
    r = tk.adopter_salon(AG, "c1", poster=True)
    fiche = json.loads(tk.ETAT_FICHIER.read_text())["tickets"][f"{AG}:v1"]
    check("adopter pour de vrai : accueil posté et épinglé, fiche écrite, rien d'autre",
          r["ok"] and fiche["salon"] == "c1" and fiche["accueil"] == "msg1"
          and fiche["manager"] == "m1" and fiche["adopte"]
          and [(a[0], a[1]) for a in appels if a[0] != "GET"]
          == [("POST", "/channels/c1/messages"), ("PUT", "/channels/c1/pins/msg1")], appels)
    SALONS["c4"] = {"id": "c4", "name": "israel", "type": 0, "parent_id": "cat",
                    "permission_overwrites": [{"type": 1, "id": "v2"}, {"type": 1, "id": "lead"}]}
    MEMBRES["v2"] = {"user": {"id": "v2", "username": "israelfdn"}, "roles": ["r_att"]}
    MEMBRES["lead"] = {"user": {"id": "lead", "username": "aboubakar6260"}, "roles": []}
    check("deux membres sans rôle de manager : refusé sans VA désigné",
          not tk.adopter_salon(AG, "c4")["ok"])
    r4 = tk.adopter_salon(AG, "c4", uid_va="v2")
    check("… le VA désigné (en attente) : adopté, en essai, le leader laissé tel quel",
          r4["ok"] and r4["uid"] == "v2" and r4["essai"], r4)
    check("… un VA désigné qui n'est pas membre du salon : refusé",
          not tk.adopter_salon(AG, "c4", uid_va="v1")["ok"])
    appels.clear()
    r = tk.adopter_salon(AG, "c1", poster=True, renommer=True)
    check("déjà adopté + renommer : PAS de second accueil, le nom d'un ticket avec le numéro du VA",
          r["ok"] and r.get("deja") and r["nom"] == "─│🔵┤-27-va-＠zaid014787"
          and [(a[0], a[1], a[2]) for a in appels if a[0] != "GET"]
          == [("PATCH", "/channels/c1", {"name": "─│🔵┤-27-va-＠zaid014787"})], appels)
    for k, v in _sauve_tk.items():
        setattr(tk, k, v)

    # ── classements aux abonnés ──────────────────────────────────────────
    _sauve_sv = {k: getattr(sv, k) for k in ("_subs_entite", "subs_depuis_toujours")}
    _sauve_pd = {k: getattr(pod, k) for k in ("_classement_avec_partis", "_noms_registre")}
    monde(etat={"liens": {
        f"{AG}:u1": {"pseudo": "zaid014787", "numero": 12, "link_id": "lnk_a",
                     "tracking": "https://onlyfans.com/emy.brw/c300"},
        f"{AG}:u2": {"pseudo": "mike047639", "numero": 7, "link_id": "lnk_b",
                     "tracking": "https://onlyfans.com/emy.brw/c301"},
        f"{AG}:u3": {"pseudo": "parti", "numero": 9, "link_id": "lnk_c", "actif": False,
                     "tracking": "https://onlyfans.com/emy.brw/c302"},
        f"{AG}:u4": {"pseudo": "sanslien", "numero": 5}}})
    SUBS = {"https://onlyfans.com/emy.brw/c300": 56, "https://onlyfans.com/emy.brw/c301": None}
    sv._subs_entite = lambda e, d0, d1: SUBS.get(e["trackings"][0][1])
    _vrai_cap = _sauve_pd["_classement_avec_partis"]
    tw_appels = []

    def faux_cap(debut, fin, pause=0.3, gid=None, mesure=None, etiquette="podium"):
        if str(gid) == pod.TWITTER_ID:
            tw_appels.append(mesure)
            return {"lignes": [{"va": "VA 12", "numero": 12, "clics": 4, "liens": 2}],
                    "illisibles": ["VA 40"], "frais": True}
        return _vrai_cap(debut, fin, pause=pause, gid=gid, mesure=mesure, etiquette=etiquette)
    pod._classement_avec_partis = faux_cap
    pod._noms_registre = lambda: {12: "Roucham", 40: "tsiry"}
    J1, J2 = dt.date(2026, 10, 19), dt.date(2026, 10, 25)
    cl = pod.classement(J1, J2, gid=AG)
    check("semaine Agency : ses VA en « Instagram VA n », aux abonnés ; lien coupé et sans lien absents",
          [(x["va"], x["clics"]) for x in cl["lignes"]] == [("Instagram VA 12", 56)]
          and cl["illisibles"] == ["Instagram VA 7"], cl)
    clq = pod.classement(J1, J2, gid=AG, mesure=pod._profil(AG)["mesure_subs"])
    check("quinzaine Agency : + les abonnés des VA de Youl4b (Twitter) en trois lignes "
          "« Instagram VA 001/002/003 », 44 % / 32 % / le reste ; leurs sans relevé en une ligne",
          [(x["va"], x["clics"]) for x in clq["lignes"]]
          == [("Instagram VA 12", 56), ("Instagram VA 001", 2), ("Instagram VA 002", 1),
              ("Instagram VA 003", 1)]
          and all(x.get("youl4b") for x in clq["lignes"][1:]) and tw_appels == ["tracking_abonnes"]
          and clq["illisibles"] == ["Instagram VA 7", "YouLab Twitter (1 VA sans relevé)"], clq)
    check("partage 44 / 32 / reste : la somme ne bouge pas",
          sv._parts_youlab(100) == [44, 32, 24] and sv._parts_youlab(1) == [0, 0, 1]
          and sum(sv._parts_youlab(1469)) == 1469 and sv._parts_youlab(0) == [0, 0, 0])
    pages = pod.pages_subs(clq, J1, J2, {"Instagram VA 12": 70}, gid=AG)
    desc = pages[0]["description"]
    check("quinzaine : « Instagram VA 12 — 56 subs · 🌐 70 all-time » ; Youl4b sans all-time "
          "(faux depuis le passage sur Emy, comme à Twitter)",
          "**Instagram VA 12** — **56** subs · 🌐 70 all-time" in desc
          and "**Instagram VA 001** — **2** subs\n" in desc + "\n"
          and "Abonnés **tracking OF**" in desc and "$" not in desc, desc[:600])
    emb = pod.embed_podium(cl, J1, J2, gid=AG, en_cours=True)
    # au format du bonus du jour depuis le 25/10/2026 : plus d'en-tête
    check("podium de la semaine : en subs, « Instagram VA n », le top 3 et sa prime",
          "**Instagram VA 12** — **56 subs** → pas de prime (min. 100)" in emb["description"]
          and "clics" not in emb["description"],
          emb["description"][:500])
    bon = pod.embed_bonus(cl, J2, AG)
    check("bonus du jour : « Instagram VA n — N subs → 5.00$ » (format du 25/10/2026)",
          "**Instagram VA 12** — **56 subs** → **5.00$**" in bon["description"], bon["description"][:300])
    noms = pod._noms_libelles(AG)
    check("👀 Pseudos : les VA d'Agency au pseudo, les trois lignes de YouLab à leur part",
          noms.get("Instagram VA 12") == "zaid014787"
          and noms.get("Instagram VA 001") == "YouLab Twitter · 44 % de leurs abonnés"
          and noms.get("Instagram VA 003") == "YouLab Twitter · le reste de leurs abonnés"
          and "Instagram VA 012" not in noms, noms)
    check("la semaine (qui paie) n'a pas les VA de Youl4b", tw_appels == ["tracking_abonnes"])
    _sauve_partis = tk.partis
    tk.partis = lambda g: {"u1": 1792000000} if str(g) == AG else {}
    check("un VA d'Agency parti sort du classement (clé « Instagram VA 12 »)",
          "Instagram VA 12" in pod._partis(AG)
          and [x["va"] for x in pod.classement(J1, J2, gid=AG)["lignes"]] == [], pod._partis(AG))
    tk.partis = _sauve_partis
    check("les salons d'Agency : les siens, pas ceux de Twitter",
          pod._profil(AG)["salon_podium"] == "🏆・classement" and pod._nom_salon_subs(AG) == "📈・subs"
          and pod._profil(AG)["salon_bonus"] == "💰・bonus-journalier")
    import verif_discord as vd
    cfg = vd.serveur(AG)
    check("Agency dans la boucle (SERVEURS_EXTRA) : ses rôles, sans quête",
          cfg and cfg["role_verifie"] == "1562953421508837426" and cfg["quetes"] is False, cfg)
    for k, v in _sauve_sv.items():
        setattr(sv, k, v)
    for k, v in _sauve_pd.items():
        setattr(pod, k, v)

    # ── arrivées, départs, panneau (agency_accueil) ──────────────────────
    import agency_accueil as aa
    import verif_discord as vd2
    _sauve_aa = (aa.FICHIER, aa._api, vd2.assurer_message_verif)
    aa.FICHIER = TMP / "agency_accueil.json"
    LISTE = {"ok": True, "m": [{"user": {"id": "1"}, "joined_at": "a", "roles": []},
                               {"user": {"id": "2"}, "joined_at": "b", "roles": []},
                               {"user": {"id": "9", "bot": True}, "roles": []}]}
    INVITES = {"ok": True, "usages": {"vanity": 4}}
    postes, panneaux, appels_aa = [], [], []

    edits = []

    def faux_api_aa(methode, chemin, **kw):
        appels_aa.append((methode, chemin, kw.get("json")))
        if methode == "GET" and "/members/" in chemin:
            uid_ = chemin.rsplit("/", 1)[1]
            m_ = next((x for x in LISTE["m"] if x["user"]["id"] == uid_), None)
            return (200, m_) if m_ else (404, {})
        if methode == "GET" and "/members" in chemin:
            return (200, list(LISTE["m"])) if LISTE["ok"] else (403, {"message": "Missing Access"})
        if methode == "GET" and chemin.endswith("/invites"):
            if not INVITES["ok"]:
                return 403, {"message": "Missing Permissions"}
            return 200, [{"code": c, "uses": n} for c, n in INVITES["usages"].items()]
        if methode == "POST" and chemin.endswith("/invites"):
            code = f"inv{len(INVITES['usages'])}"
            INVITES["usages"][code] = 0
            return 200, {"code": code}
        if methode == "POST":
            postes.append((chemin, kw["json"]["embeds"][0]["title"], kw["json"]["allowed_mentions"],
                           kw["json"]["embeds"][0]))
            return 200, {"id": f"m{len(postes)}"}
        if methode == "PATCH":
            edits.append((chemin, kw["json"]["embeds"][0]))
            return 200, {}
        return 200, {}
    aa._api = faux_api_aa
    vd2.assurer_message_verif = lambda gid: panneaux.append(gid) or "pose"
    b1 = aa.surveiller()
    check("premier passage : les membres déjà là sont notés SANS annonce, le panneau est posé",
          b1.get("initialise") == 2 and not postes and panneaux == [AG], (b1, postes))
    # l'historique (« remets les mecs ici ») : une ligne par membre déjà là, dans
    # l'ordre d'arrivée, et la bienvenue des vérifiés ; par paquets, une seule fois
    LISTE["m"][1]["roles"] = [vd2.serveur(AG)["role_verifie"]]
    _paquet = aa.RATTRAPAGE_PAR_TOUR
    aa.RATTRAPAGE_PAR_TOUR = 2
    bh = aa.surveiller()
    check("historique, 1er paquet (2 messages) : arrivée de 1 puis de 2, dans l'ordre d'arrivée, en carte",
          bh.get("rattrapage") == 2 and [p_[1] for p_ in postes] == ["🚪 Arrivée sur Agency VA INSTAGRAM"] * 2
          and all(p_[3].get("author") and p_[3].get("thumbnail") for p_ in postes)
          and not json.loads(aa.FICHIER.read_text()).get("rattrape"), postes)
    bh2 = aa.surveiller()
    check("… 2e paquet : la carte de bienvenue du vérifié dans ✅ membres-vérifiés, puis c'est fini",
          bh2.get("rattrapage") == 1 and postes[2][0].endswith(f"/{aa.SALON_VERIFIES}/messages")
          and postes[2][3]["title"].startswith("✨ Bienvenue") and len(postes[2][3]["fields"]) == 2
          and json.loads(aa.FICHIER.read_text()).get("rattrape"), postes)
    # l'historique posté AVANT les cartes : réécrit sur place, une fois
    etat_aa = json.loads(aa.FICHIER.read_text())
    etat_aa["membres"]["1"].pop("carte", None)
    etat_aa.pop("habille", None)
    aa.FICHIER.write_text(json.dumps(etat_aa))
    aa.surveiller()
    check("historique sans carte : réécrit sur place (édition, aucune notification), une fois",
          [e_[0] for e_ in edits] == [f"/channels/{aa.SALON_ARRIVEES}/messages/m1"]
          and edits[0][1].get("thumbnail") and json.loads(aa.FICHIER.read_text()).get("habille"), edits)
    aa.RATTRAPAGE_PAR_TOUR = _paquet
    postes.clear()
    LISTE["m"][1]["roles"] = []
    aa.surveiller()
    check("… ensuite plus rien n'est reposté", not postes, postes)
    LISTE["m"] = [x for x in LISTE["m"] if x["user"]["id"] != "2"] + [
        {"user": {"id": "3"}, "joined_at": "c", "roles": []}]
    b2 = aa.surveiller()
    check("un arrivé dans 🚪 arrivées, un parti dans 👋 départs, sans mention ni bot",
          b2["arrivees"] == 1 and b2["departs"] == 1
          and postes[0][0].endswith(f"/{aa.SALON_ARRIVEES}/messages")
          and postes[1][0].endswith(f"/{aa.SALON_DEPARTS}/messages")
          and all(x[2].get("parse") == [] and not x[2].get("users") for x in postes), postes)
    check("… le panneau n'est pas revérifié à chaque tour (une fois l'heure)", panneaux == [AG])
    n = len(postes)
    b3 = aa.surveiller()
    check("tour suivant sans changement : rien de reposté", b3["arrivees"] == b3["departs"] == 0
          and len(postes) == n)
    LISTE["ok"] = False
    b4 = aa.surveiller()
    check("liste illisible (403) : rien d'annoncé ni d'oublié",
          b4["arrivees"] == b4["departs"] == 0 and len(postes) == n
          and "3" in json.loads(aa.FICHIER.read_text())["membres"])
    LISTE["ok"] = True

    # ── parrainage (23/10 : « il manque parrainage ») ────────────────────
    def etat_aa():
        return json.loads(aa.FICHIER.read_text())

    def invites_creees():
        return [a for a in appels_aa if a[0] == "POST" and a[1].endswith("/invites")]
    lien1 = aa.lien_pour("1")
    check("lien personnel : une invitation permanente et unique sur 🔐・vérification",
          lien1.startswith("https://discord.gg/inv") and len(invites_creees()) == 1
          and invites_creees()[0][1] == f"/channels/{aa.SALON_VERIF}/invites"
          and invites_creees()[0][2] == {"max_age": 0, "max_uses": 0, "unique": True}, appels_aa[-3:])
    check("… créée une seule fois (le même lien au clic suivant)",
          aa.lien_pour("1") == lien1 and len(invites_creees()) == 1)
    code1 = lien1.rsplit("/", 1)[1]
    INVITES["usages"][code1] += 1
    LISTE["m"] = LISTE["m"] + [{"user": {"id": "4", "username": "nouveau4"}, "joined_at": "d", "roles": []}]
    n = len(postes)
    b5 = aa.surveiller()
    f4 = etat_aa()["filleuls"].get("4") or {}
    check("arrivé par le lien de 1 : 1 est son parrain, et l'annonce le dit (sans mention)",
          b5["arrivees"] == 1 and b5["parraines"] == 1 and f4.get("parrain") == "1"
          and f4.get("source") == "invitation_unique" and len(postes) == n + 1
          and "Invité par <@1>." in postes[n][3]["description"] and postes[n][3].get("thumbnail")
          and postes[n][2] == {"parse": []}, (b5, f4, postes[n:]))
    check("… parrain_de le rend (le « Merci » de la bienvenue)",
          aa.parrain_de("4") == "1" and aa.parrain_de("3") == "")
    check("… et la bienvenue des vérifiés d'Agency remercie le parrain, pas celle de Twitter",
          "Merci <@1>" in vd2._merci_parrain("4", vd2.serveur(AG))
          and vd2._merci_parrain("4", {"id": "1445108485090971710"}) == ""
          and vd2._merci_parrain("3", vd2.serveur(AG)) == "")
    code3 = aa.lien_pour("3").rsplit("/", 1)[1]
    INVITES["usages"][code1] += 1
    INVITES["usages"][code3] += 1
    LISTE["m"] = LISTE["m"] + [{"user": {"id": "5"}, "joined_at": "e", "roles": []},
                               {"user": {"id": "6"}, "joined_at": "f", "roles": []}]
    b6 = aa.surveiller()
    e6 = etat_aa()["filleuls"]
    check("deux arrivés par deux liens dans le même relevé : origine à confirmer, rien deviné",
          b6["arrivees"] == 2 and b6["parraines"] == 0
          and e6["5"]["parrain"] is None and e6["6"]["source"] == "a_confirmer", (b6, e6))
    INVITES["usages"]["vanity"] += 1
    LISTE["m"] = LISTE["m"] + [{"user": {"id": "7"}, "joined_at": "g", "roles": []}]
    aa.surveiller()
    check("arrivé par une invitation qui n'est à personne : sans parrain",
          etat_aa()["filleuls"]["7"]["parrain"] is None)
    LISTE["m"] = [x for x in LISTE["m"] if x["user"]["id"] != "4"]
    b7 = aa.surveiller()
    INVITES["usages"][code3] += 1
    LISTE["m"] = LISTE["m"] + [{"user": {"id": "4", "username": "nouveau4"}, "joined_at": "h", "roles": []}]
    b8 = aa.surveiller()
    check("parti puis revenu par un autre lien : départ et retour annoncés, premier parrain gardé",
          b7["departs"] == 1 and b8["arrivees"] == 1 and aa.parrain_de("4") == "1", (b7, b8))
    INVITES["ok"] = False
    LISTE["m"] = LISTE["m"] + [{"user": {"id": "8"}, "joined_at": "i", "roles": []}]
    n = len(postes)
    b9 = aa.surveiller()
    check("invitations illisibles : le tour attend, rien d'annoncé ni d'attribué",
          b9["arrivees"] == 0 and len(postes) == n and "8" not in etat_aa()["membres"])
    INVITES["ok"] = True
    check("… et le tour suivant reprend l'arrivée", aa.surveiller()["arrivees"] == 1)
    _vrai_etat = aa.FICHIER.read_text()
    aa._ecrire({"initialise": 1, "membres": {"50": {"joined_at": "2026-01-01"},
                                             "51": {"joined_at": "2026-02-01", "neuf": True, "arrivee": "m"},
                                             "52": {"joined_at": "2026-03-01", "a_annoncer": True, "neuf": True}}})
    n = len(postes)
    nr = aa.rattraper({u: {"user": {"id": u}, "joined_at": j, "roles": []}
                       for u, j in (("50", "2026-01-01"), ("51", "2026-02-01"), ("52", "2026-03-01"))}, "")
    check("historique : les arrivés du relevé (annoncés ou en attente) n'y repassent pas",
          nr == 1 and len(postes) == n + 1 and "<@50>" in postes[-1][3]["description"]
          and "01/01/2026" in postes[-1][3]["description"]
          and etat_aa().get("rattrape"), postes[n:])
    aa.FICHIER.write_text(_vrai_etat)
    LISTE["m"] = LISTE["m"] + [{"user": {"id": str(100 + i)}, "joined_at": "x", "roles": []} for i in range(30)]
    n = len(postes)
    b10 = aa.surveiller()
    check("état perdu (la moitié du serveur « arrivée » d'un coup) : nouvelle référence, rien d'annoncé",
          b10.get("reference") == 30 and b10["arrivees"] == 0 and len(postes) == n
          and "130" not in etat_aa().get("filleuls", {}), b10)
    aa.FICHIER.write_text(_vrai_etat)
    LISTE["m"] = LISTE["m"][:-30]

    # ── l'espace personnel, le bouton, le panneau ─────────────────────────
    _sauve_mods = {k: sys.modules.get(k) for k in ("affiliation_privee", "affiliation_site")}
    _sauve_lien_de = lv.lien_de
    try:
        sys.modules["affiliation_privee"] = types.SimpleNamespace(
            compteurs=lambda: {"https://onlyfans.com/emy.brw/c1": 12})
        sys.modules["affiliation_site"] = types.SimpleNamespace(
            lien_personnel=lambda uid, p: f"https://youl4b.com/affiliation/mon-espace?t={p}-{uid}")
        lv.lien_de = lambda gid, uid: ({"tracking": "https://onlyfans.com/emy.brw/c1/"}
                                       if (gid, uid) == (AG, "4") else {})
        p1 = aa.panneau("1")
        t1 = json.dumps(p1, ensure_ascii=False)
        check("espace de 1 : son lien, pas de parrain, son filleul et ses subs aux deux paliers",
              p1["fields"][0]["value"] == lien1 and "lien personnel" in p1["fields"][0]["name"]
              and "Aucun parrain" in p1["fields"][1]["value"] and "1 filleul(s)" in p1["fields"][2]["value"]
              and "@nouveau4" in t1 and "12 vrais subs" in t1 and "Objectif 10 : 100 %" in t1
              and "Objectif 200 : 6 %" in t1 and "0,50 $ à 10 subs" in t1, t1)
        p4 = aa.panneau("4")
        check("espace de 4 : son parrain est 1, son propre lien créé à l'ouverture",
              p4["fields"][1]["value"] == "@1" and p4["fields"][0]["value"].startswith("https://discord.gg/")
              and p4["fields"][0]["value"] != lien1, p4)
        check("subs d'une fiche : son tracking ; sans tracking ni compteurs, inconnu",
              aa.subs_fiche({"tracking": "https://onlyfans.com/emy.brw/c1"}, {"https://onlyfans.com/emy.brw/c1": 3}) == 3
              and aa.subs_fiche({}, {"x": 1}) is None
              and aa.subs_fiche({"tracking": "https://onlyfans.com/emy.brw/c1"}, None) is None
              and aa.subs_fiche({"tracking": "https://onlyfans.com/emy.brw/c9"}, {"x": 1}) is None)
        charge = {"type": 3, "guild_id": AG, "application_id": str(vd2.bot_du_serveur(AG).get("app_id")),
                  "member": {"user": {"id": "4"}}, "data": {"custom_id": "agency-aff:mes"}}
        r = aa.traiter(charge)
        check("bouton « Mon espace personnel » : l'adresse de SON espace Agency, en privé",
              r["type"] == 4 and r["data"]["flags"] == 64 and "t=agency-4" in r["data"]["content"], r)
        check("… d'un autre serveur ou d'une autre application : refusé",
              "ne correspond pas" in aa.traiter(dict(charge, guild_id="1"))["data"]["content"]
              and "ne correspond pas" in aa.traiter(dict(charge, application_id="1"))["data"]["content"])
        check("… un autre bouton ne le concerne pas",
              aa.traiter({"data": {"custom_id": "twitter-aff:mes"}}) is None)
        sys.modules["affiliation_site"] = types.SimpleNamespace(
            lien_personnel=lambda uid, p: (_ for _ in ()).throw(ValueError("Plateforme inconnue")))
        check("… espace indisponible (site pas prêt) : il le dit, en privé",
              "indisponible" in aa.traiter(charge)["data"]["content"])
    finally:
        lv.lien_de = _sauve_lien_de
        for k, v in _sauve_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    r1 = aa.poser_panneau_parrainage()
    posts_p = [a for a in appels_aa if a[0] == "POST" and a[1] == f"/channels/{aa.SALON_PARRAINAGE}/messages"]
    pins = [a for a in appels_aa if a[0] == "PUT" and a[1].startswith(f"/channels/{aa.SALON_PARRAINAGE}/pins/")]
    corps = posts_p[-1][2] if posts_p else {}
    check("panneau du parrainage : posé dans 🤝・parrainage, épinglé, bouton agency-aff, paliers",
          r1 == "pose" and len(posts_p) == 1 and len(pins) == 1
          and corps["components"][0]["components"][0]["custom_id"] == "agency-aff:mes"
          and "0,50 $ à 10 subs" in corps["embeds"][0]["description"]
          and corps["allowed_mentions"] == {"parse": []}, (r1, corps))
    r2 = aa.poser_panneau_parrainage()
    check("… reposé : remis au texte du jour sur place, pas de doublon",
          r2 == "mis a jour" and len([a for a in appels_aa if a[0] == "POST"
                                      and a[1] == f"/channels/{aa.SALON_PARRAINAGE}/messages"]) == 1)
    # la validation (verif_discord.poster_bienvenue) : la carte d'Agency, une fois
    postes.clear()
    LISTE["m"].append({"user": {"id": "60", "username": "neuf"}, "joined_at": "j", "roles": []})
    aa.surveiller()
    postes.clear()
    r_b = vd2.poster_bienvenue("60", vd2.serveur(AG))
    check("validation : carte de bienvenue d'Agency, le membre mentionné",
          r_b and postes[0][0].endswith(f"/{aa.SALON_VERIFIES}/messages")
          and postes[0][2] == {"parse": [], "users": ["60"]} and postes[0][3]["title"].startswith("✨"), postes)
    check("… et pas deux fois", vd2.poster_bienvenue("60", vd2.serveur(AG)) == "" and len(postes) == 1)
    # ✅ Vérifié posé à la main : sa carte au tour suivant
    postes.clear()
    LISTE["m"].append({"user": {"id": "61", "username": "main"}, "joined_at": "k", "roles": []})
    aa.surveiller()
    postes.clear()
    LISTE["m"][-1]["roles"] = [vd2.serveur(AG)["role_verifie"]]
    b61 = aa.surveiller()
    check("✅ Vérifié posé à la main : sa carte de bienvenue au tour suivant",
          b61.get("bienvenues") == 1 and postes and postes[-1][3]["title"].startswith("✨"), (b61, postes))
    # validé dans la minute de son arrivée, avant que le relevé ne l'ait vu :
    # sa note d'arrivée garde la bienvenue, rien de reposté
    postes.clear()
    LISTE["m"].append({"user": {"id": "62", "username": "rapide"}, "joined_at": "l",
                       "roles": [vd2.serveur(AG)["role_verifie"]]})
    r62 = vd2.poster_bienvenue("62", vd2.serveur(AG))
    b62 = aa.surveiller()
    check("validé avant le relevé : son arrivée annoncée, sa bienvenue pas reposée",
          r62 and b62["arrivees"] == 1 and not b62.get("bienvenues")
          and [p_[0].rsplit("/", 2)[1] for p_ in postes] == [aa.SALON_VERIFIES, aa.SALON_ARRIVEES]
          and etat_aa()["membres"]["62"].get("bienvenue") == r62, (b62, postes))
    e4 = aa.embed_bienvenue("4", {"user": {"id": "4"}}, aa.parrain_de("4"))
    check("la bienvenue d'un filleul remercie son parrain (comme Twitter)",
          "🙏 Merci <@1>" in e4["description"] and "Merci" not in aa.embed_bienvenue("3", {})["description"])
    aa.FICHIER, aa._api, vd2.assurer_message_verif = _sauve_aa
    src_wu = (BOT / "web_upload.py").read_text(encoding="utf-8")
    check("un seul relevé des membres : plus dans le tour des tickets, le fil d'agency_accueil",
          ".surveiller()" not in inspect.getsource(tk.suivre_partout)
          and '"agency_accueil": ("agency-accueil"' in src_wu and "_ag_boot.demarrer()" in src_wu
          and 'not os.environ.get("VABOT_BANC_ESSAI") and _machine_proprietaire("agency-accueil")' in src_wu)
    check("route Discord : le bouton agency-aff va à agency_accueil.traiter",
          "_rep_ag = _ag.traiter(charge)" in src_wu)
    check("Agency dans le périmètre des tickets, managers fixes Gone et Yoshiki",
          AG in tk.SERVEURS_TICKETS
          and tk.MANAGERS_POSES[AG] == ["1392192812073615391", "1502081637591289877"])
    cfg2 = vd2.serveur(AG)
    check("vérification d'Agency : panneau, entrées, suspicions, bienvenue, parcours",
          cfg2["salon_verification"] == "1562974555423776848"
          and cfg2["salon_entrees"] == "1562974587585699960" and cfg2["salon_suspicions"]
          and cfg2["salon_bienvenue"] and len(cfg2["parcours"]) == 4 and cfg2["auto"] is False, cfg2)
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    for k, v in _SAUVE_POD.items():
        setattr(pod, k, v)
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
