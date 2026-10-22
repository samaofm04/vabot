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

    def create_directlink(self, sc, url, nom="", team_id=None):
        self.appels.append(("direct", sc, url, nom, team_id))
        return {"ok": True, "link": {"id": f"lnk_{sc}", "url": url}}

    def duplicate_link(self, source, sc, nom, url, equipe):
        self.appels.append(("duplicate", source, sc, nom, url, equipe))
        return {"ok": True, "link": {"id": f"lnk_{sc}", "url": url}}

    def _call_tool(self, outil, args):
        self.appels.append((outil, args))
        if outil == "list_groups":
            return {"ok": True, "data": {"data": [{"name": "GONE", "id": "grp_g"}]}}
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
        check(f"espace Agency (pause Seren {pause}) : EMY IG, direct, Instagram, tracking, sans variante",
              e["equipe"] == EMY_IG and e["direct"] and not e["gabarit"]
              and e["plateforme"] == "Instagram" and e["tracking"] is True
              and e["variante"] is None, e)
    lv.SEREN_EN_PAUSE = True
    check("Agency fait partie des serveurs à liens", AG in lv.SERVEURS)
    check("manque() : rien ne manque sans gabarit (lien direct)", lv.manque(AG) == "", lv.manque(AG))
    monde(config=dict(CONFIG, mypuls_actif=False))
    check("… mais MyPuls fermé : refusé (un lien direct sans tracking ne serait à personne)",
          "MyPuls" in lv.manque(AG), lv.manque(AG))
    monde()
    check("Twitter et Threads ne bougent pas (leurs équipes)",
          lv.espace(lv.TWITTER_ID)["equipe"] == lv.EQUIPE_VA
          and lv.espace(lv.THREADS_ID)["equipe"] == lv.ESPACE_THREADS["equipe"])

    # ── créer ────────────────────────────────────────────────────────────
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
    f = lv.lien_de(AG, "u1")
    check("… la fiche : numéro, tracking, lien", f.get("numero") == 27
          and f.get("tracking", "").endswith("/c300") and f.get("link_id", "").startswith("lnk_"), f)
    check("… et aucun 50/50 : pas de variante au résultat", r.get("variante") is None, r)

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
    check("… l'accueil : Confirmer, Créer son lien, USDC, Mes stats, et aucune mention",
          labels == ["Confirmer le VA", "Créer son lien", "Mon adresse USDC", "Mes stats"]
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
    for k, v in _sauve_tk.items():
        setattr(tk, k, v)
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    for k, v in _SAUVE_POD.items():
        setattr(pod, k, v)
    if _SAUVE_GMS is not None:
        sys.modules["gms"] = _SAUVE_GMS

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
