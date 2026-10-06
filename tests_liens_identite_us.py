# -*- coding: utf-8 -*-
"""tests_liens_identite_us.py — les liens GetMySocial par identite des VA US.

Rien ne part vers GetMySocial : gms._call_tool et gms.list_links_team sont
remplaces par un espace « JESSY LE RETOUR » en memoire, peuple des 46 vrais
liens lus le 06/10/2026 (nom, shortcode, id, code c<N>). Le reseau est coupe
(requests leve), et toute ecriture hors du dossier temporaire est refusee et
comptee : le vrai data/ n'est jamais touche.

    python tests_liens_identite_us.py
"""
import copy
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:400]}]"))


# ─── isolation : ni reseau, ni ecriture hors du dossier temporaire ───────
TMP = Path(tempfile.mkdtemp(prefix="liens_identite_us_"))
HORS_TMP = []
VRAI_REGISTRE = Path(__file__).resolve().parent / "data" / "liens_identite_us.json"


def _etat_vrai():
    try:
        st = VRAI_REGISTRE.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


VRAI_AVANT = _etat_vrai()

import requests  # noqa: E402


def _reseau_interdit(*a, **k):
    raise RuntimeError("réseau interdit dans les tests")


requests.get = requests.post = _reseau_interdit
requests.Session.request = _reseau_interdit

import safe_json  # noqa: E402

_write_text_vrai = safe_json.write_text


def _write_text_garde(path, text, backup=None):
    p = Path(path).resolve()
    if TMP.resolve() not in p.parents:
        HORS_TMP.append(str(p))
        return False
    return _write_text_vrai(path, text, backup=backup)


safe_json.write_text = _write_text_garde

import gms  # noqa: E402
import clics_personnes as cp  # noqa: E402
import podium_discord as pd  # noqa: E402
import liens_identite_us as liu  # noqa: E402

gms._BUDGET_FICHIER = TMP / "gms_budget.json"
gms.CONFIG_FILE = TMP / "gms_config.json"
liu.REGISTRE = TMP / "liens_identite_us.json"
EQ = liu.EQUIPE

# ─── les 46 vrais liens de JESSY LE RETOUR (lus le 06/10/2026) ───────────
# (nom, shortcode, id, code du suivi c<N>, created). Tous des liens DIRECTS
# vers onlyfans.com/jessyewdiference/c<N>, tous actifs.
VRAIS = [
    ('Printsyyy X1', 'prstjessye', 'lnk_6ac140ba0b1140e50ba7a009', 131, 1791049914),
    ('Micky', 'secretjessye', 'lnk_6abe1b34555277271dc49169', 126, 1790843700),
    ('tsiry 2', 'loveejessye', 'lnk_6abe1b0337937d95663530cb', 126, 1790843651),
    ('tsiry 1', 'lovejessye', 'lnk_6abe1ae51eecdf1691b98b6f', 126, 1790843621),
    ('eddy 2', 'cutxjessye', 'lnk_6abe1ac4e1117ecf395c0e60', 126, 1790843588),
    ('eddy 1', 'cutejessye', 'lnk_6abe1a9d37937d9566352b6c', 126, 1790843549),
    ('( Carter ) 3', 'crerjessye', 'lnk_6aba05a9607a9585322e9f31', 129, 1790576041),
    ('( Carter ) 2', 'crtrjessye', 'lnk_6aba0592607a9585322e9b81', 129, 1790576018),
    ('( Carter ) SPAM', 'crtsjessye', 'lnk_6aba051b55a5908a47f76592', 130, 1790575899),
    ('( Carter ) 1', 'crtejessye', 'lnk_6aba04fad38dbae582b4333e', 129, 1790575866),
    ('( Moan ) 1', 'moanjessye', 'lnk_6ab965b21173088818a73b17', 127, 1790535090),
    ('( Yazid ) 1', 'yzdjessye', 'lnk_6ab9657b74b7baff6c586cff', 128, 1790535035),
    ('(Roucham) 2', 'cutyjessye', 'lnk_6ab818fa74b7baff6c457f35', 88, 1790449914),
    ('(Gerome) SPAM', 'cutyxjessye', 'lnk_6aada17d2ca1f12d16b779a2', 124, 1789763965),
    ('(VA 6 Noum) 1', 'sweetjessye', 'lnk_6aaa4862f8e7bb1c51a679ec', 123, 1789544546),
    ('(VA 5 Noum) 1', 'dreamjessye', 'lnk_6aaa47f4695aae833dc64429', 122, 1789544436),
    ('(TRAVIS) 1', 'trsvjessye', 'lnk_6a9fd1728f00207299ec040b', 120, 1788858738),
    ('(ANDRY) 2', 'bnsejessye', 'lnk_6a9c107102cce46ce2dcc64c', 87, 1788612721),
    ('(ANDRY) 1', 'bnesjessye', 'lnk_6a9c1052e92a6bdb5e732c7a', 87, 1788612690),
    ('(DOLAD) 1', 'jnrjessye', 'lnk_6a9b830982ff27ad6a5b13e3', 118, 1788576521),
    ('(Abdoul) SPAM', 'rmvxjessy', 'lnk_6a9acbd7e00c8d4e750c3643', 115, 1788529623),
    ('(Kylmich) SPAM', 'hsvtjessy', 'lnk_6a9acb765c52dca77615e975', 114, 1788529526),
    ('(Ricardo) 1 SPAM', 'dhysjessye', 'lnk_6a9aca525c52dca77615c52d', 113, 1788529234),
    ('(Roucham) 1SPAM', 'kntsjessye', 'lnk_6a9ac8ea67c379119396139b', 110, 1788528874),
    ('TWITTER', 'jesssvme', 'lnk_6a977b9c3896661191c1ea25', 121, 1788312476),
    ('(PAMPAM) 1 SPAM', 'smljessye', 'lnk_6a976ef53cb716046f6c88fe', 116, 1788309237),
    ('EUD', 'msgejessye', 'lnk_6a8f792a7aa5923360cccbc4', 117, 1787787562),
    ('(VA 4 Noum)', 'cipsjessy', 'lnk_6a8d37fde5a41e3872409c50', 97, 1787639805),
    ('( Jaurel ) 2', 'hstujessye', 'lnk_6a8b4b8714b37dc8996e1042', 83, 1787513735),
    ('(PAMPAM) 1', 'hzysjessye', 'lnk_6a87332c855ddc45b1ec7c36', 96, 1787245356),
    ('(Ricardo) 1', 'dhsyjessye', 'lnk_6a8732e82a99dd49a091c423', 92, 1787245288),
    ('LaBoule ( Phone )', 'bsytjessye', 'lnk_6a87320c2e2c19bece077bdf', 125, 1787245068),
    ('Laboule ( X )', 'ghezjessye', 'lnk_6a8717c5ad7d51ec19dcf647', 126, 1787238341),
    ('( BO7 ) 2', 'nsyejessye', 'lnk_6a8717b72e2c19bece065f17', 85, 1787238327),
    ('(Gerome) 1', 'bertjessye', 'lnk_6a6224c47e0f5e0625458acd', 94, 1784816836),
    ('(Roucham) 1', 'knstjessye', 'lnk_6a5167c3661861fd7a0eaa59', 88, 1783719875),
    ('(Kylmich) 1', 'hstvjessy', 'lnk_6a5167a9124b8220a218f2de', 86, 1783719849),
    ('(Abdoul) 1', 'rmxvjessy', 'lnk_6a0e5415a5835045d4a1a4d2', 91, 1779323925),
    ('(VA 3 Noum) 1', 'ldkpjessy', 'lnk_6a0e54087917759f8b67d6b5', 52, 1779323912),
    ('(VA 2 Noum) 1', 'wzyfjessy', 'lnk_6a0e540151a8673d099b79e3', 51, 1779323905),
    ('(Miranto) 1', 'tbhcjessy', 'lnk_6a0e53f9bfa0c238f20b46b8', 90, 1779323897),
    ('(Mykey) 1', 'nqrjjessy', 'lnk_6a0e53e19a5ce8394b308002', 95, 1779323873),
    ('( Jaurel ) 1', 'pvxajessy', 'lnk_6a0e5362fea0a6e3ed3390d9', 83, 1779323746),
    ('( VA 1 Noum ) 1', 'kfwojessy', 'lnk_6a0e5346fba948185cdbdfaf', 47, 1779323718),
    ('( Safidy ) 1', 'ztrkjessy', 'lnk_6a0e533ba5835045d4a19815', 84, 1779323707),
    ('( BO7 ) 1', 'xqvnjessy', 'lnk_6a0e5332c08c737549671aa5', 85, 1779323698),
]
NOMS = [v[0] for v in VRAIS]
ID = {v[0]: v[2] for v in VRAIS}
OF = "https://onlyfans.com/jessyewdiference/c%d"
#: Les ecarts ATTENDUS avec clics_personnes : sans parentheses, le podium
#: garde le chiffre (« tsiry 1 »), le report des clics le pele (« tsiry »).
#: Aucun nom ne peut satisfaire les deux regles a la fois.
ECARTS_CP = {"tsiry 1", "tsiry 2", "eddy 1", "eddy 2"}


def lien_direct(nom, sc, lid, code, created, status="active"):
    return {"id": lid, "object": "link", "type": "directlink", "shortcode": sc,
            "url": OF % code, "buttons": None, "display_name": nom, "status": status,
            "team_id": EQ, "created": created, "group_id": None,
            "profile_picture": "https://images.getmysocial.com/profil_default.webp"}


def page(nom, sc, lid, boutons, created, status="active", **plus):
    d = {"id": lid, "object": "link", "type": "landing", "shortcode": sc, "url": None,
         "buttons": boutons, "display_name": nom, "status": status, "team_id": EQ,
         "created": created, "group_id": None,
         "profile_picture": f"https://images.getmysocial.com/{sc}.webp",
         "background_image": f"https://images.getmysocial.com/{sc}-fond.webp"}
    d.update(plus)
    return d


BOUTONS_IBEN = [
    {"label": "My OF 🔥", "url": OF % 999, "button_effect": "5",
     "image_url": "https://s3.getmysocial.com/iben-bouton.png",
     "geofilters": [{"country_code": "FR", "country_name": "France",
                     "destination_url": OF % 998}]},
    {"label": "Instagram", "url": "https://instagram.com/ibenhaastrup", "button_effect": "2"},
    {"label": "onlyfans.com/jessyewdiference", "url": "https://onlyfans.com/jessyewdiference",
     "description": "le texte qui cite onlyfans.com reste du texte"},
]
BASES = [
    page("TEMPLATE ibenhaastrup", "tplibenh", "lnk_base_iben", BOUTONS_IBEN, 1791100000,
         smart_redirect={"enabled": True, "destination_url": OF % 999,
                         "trigger_after_visits": 3, "within_days": 7}),
    # doublon plus recent, a ne PAS prendre
    page("TEMPLATE ibenhaastrup", "tplibenh2", "lnk_base_iben_bis",
         [{"label": "OF", "url": OF % 777}], 1791200000),
    page("TEMPLATE e30princesss", "tple30", "lnk_base_e30",
         [{"label": "Instagram", "url": "https://instagram.com/e30princesss"}], 1791100001),
    lien_direct("TEMPLATE themikkiangel", "tplmikki", "lnk_base_mikki", 5, 1791100002),
    page("template  EllieAnn ", "tplellie", "lnk_base_ellie",
         [{"label": "OF", "url": OF % 555}], 1791100003, status="inactive"),
    page("TEMPALTE zezatwins", "tplzeza", "lnk_base_zeza",
         [{"label": "OF", "url": OF % 556}], 1791100004),
    page("TEMPLATE inconnue", "tplinconnue", "lnk_base_inc",
         [{"label": "OF", "url": OF % 557}], 1791100005),
    page("TEMPLATE ariiiann__", "tplarii", "lnk_base_arii",
         [{"label": "OF", "url": OF % 558}], 1791100006),
]
AUTRES = [
    {**lien_direct("(Other) 1", "otherone", "lnk_other", 5, 1791100100),
     "url": "https://onlyfans.com/autre/c5"},
    page("(Landing) 1", "landingone", "lnk_landing", [{"label": "OF", "url": OF % 117}], 1791100101),
    lien_direct("(Zed) 1", "zedone", "lnk_zed1", 140, 1791100102),
    lien_direct("(Zed) 1", "zedtwo", "lnk_zed2", 141, 1791100103),
]


class FauxGMS:
    """L'espace JESSY LE RETOUR en memoire, et les outils MCP qu'on appelle."""

    def __init__(self):
        self.liens = {}
        for v in VRAIS:
            self.liens[v[2]] = lien_direct(*v)
        for l in BASES + AUTRES:
            self.liens[l["id"]] = copy.deepcopy(l)
        self.appels = []
        self.tags = []
        self.pause = None
        self.ailleurs = set()          # shortcodes pris par d'autres comptes
        self.refus_update = 0
        self.update_sans_corps = 0
        self.update_ignore_boutons = 0
        self.perdre_reponse_dup = 0
        self.rejouer_dup = 0           # la copie est faite, la reponse perdue, gms rejoue : 409
        self.liste_leve = False
        self.fige = None               # une liste « en cache », perimee
        self.lent = 0.0
        self.n = 0

    def _tag(self):
        self.tags.append(getattr(gms._API_LOCAL, "tag", None))

    def outils(self, nom):
        return [a for a in self.appels if a[0] == nom]

    def list_links_team(self, team_id, force_refresh=False):
        self.appels.append(("list", team_id, force_refresh))
        self._tag()
        if self.liste_leve:
            raise RuntimeError("liste en panne")
        if self.pause:
            return {"ok": False, "error": self.pause}
        if self.fige is not None and not force_refresh:
            # le cache de 15 min de gms : ce qui a ete cree depuis n'y est pas
            return {"ok": True, "links": copy.deepcopy(self.fige)}
        return {"ok": True, "links": [copy.deepcopy(l) for l in self.liens.values()
                                      if l.get("team_id") == team_id]}

    def call_tool(self, nom, args=None, _retry=True, _429=0):
        args = copy.deepcopy(args or {})
        self.appels.append((nom, args))
        self._tag()
        if self.pause:
            return {"ok": False, "error": self.pause}
        if nom == "get_link":
            l = self.liens.get(args.get("link_id"))
            if not l:
                return {"ok": False, "error": "{'code': 'link_not_found'}"}
            return {"ok": True, "data": json.dumps(l, ensure_ascii=False)}   # texte, comme MCP
        if nom == "duplicate_link":
            if self.lent:
                time.sleep(self.lent)
            src = self.liens.get(args.get("link_id"))
            if not src:
                return {"ok": False, "error": "{'code': 'source_link_not_found'}"}
            if args.get("team_id") and src.get("team_id") != args["team_id"]:
                return {"ok": False, "error": "{'code': 'link_not_in_team'}"}
            sc = args["shortcode"]
            if sc in self.ailleurs or any(l["shortcode"] == sc for l in self.liens.values()):
                return {"ok": False, "error": "{'code': 'shortcode_taken', 'message': 'Shortcode already in use'}"}
            self.n += 1
            neuf = copy.deepcopy(src)
            neuf.update(id=f"lnk_copie{self.n:03d}", shortcode=sc, display_name=args["display_name"],
                        created=int(time.time()) + self.n, team_id=args.get("team_id") or src["team_id"])
            self.liens[neuf["id"]] = neuf
            if self.rejouer_dup:
                # ce que voit _call_tool_brut quand il rejoue l'appel apres un
                # ReadTimeout : la copie du premier envoi tient deja l'adresse
                self.rejouer_dup -= 1
                return {"ok": False, "error": "{'code': 'shortcode_taken', 'message': 'Shortcode already in use'}"}
            if self.perdre_reponse_dup:
                self.perdre_reponse_dup -= 1
                return {"ok": False, "error": "Erreur réseau : Read timed out"}
            return {"ok": True, "data": {k: neuf.get(k) for k in
                                         ("id", "object", "type", "shortcode", "url", "display_name",
                                          "status", "team_id", "created")}}
        if nom == "update_link":
            l = self.liens.get(args.get("link_id"))
            if not l:
                return {"ok": False, "error": "{'code': 'link_not_found'}"}
            if self.refus_update:
                self.refus_update -= 1
                return {"ok": False, "error": "HTTP 500 : erreur interne"}
            for k, v in args.items():
                if k in ("link_id", "team_id"):
                    continue
                if k == "buttons" and self.update_ignore_boutons:
                    continue
                if k in ("typeLink", "type"):
                    l["_type_demande"] = v
                    continue
                l[k] = copy.deepcopy(v)
            if self.update_ignore_boutons:
                self.update_ignore_boutons -= 1
            if self.update_sans_corps:
                self.update_sans_corps -= 1
                return {"ok": True, "data": {"id": l["id"], "updated": True}}
            return {"ok": True, "data": copy.deepcopy(l)}
        if nom == "enable_link":
            l = self.liens.get(args.get("link_id"))
            if not l:
                return {"ok": False, "error": "{'code': 'link_not_found'}"}
            l["status"] = "active"
            return {"ok": True, "data": {"id": l["id"], "status": "active"}}
        return {"ok": False, "error": f"Unknown tool: {nom}"}


F = FauxGMS()
SAV = (gms._call_tool, gms.list_links_team)


def neuf_gms():
    """Un espace neuf, le registre vide, la memoire du module oubliee."""
    global F
    F = FauxGMS()
    gms._call_tool = F.call_tool
    gms.list_links_team = F.list_links_team
    liu._DERNIERE.update(t=0.0, liens=[])
    liu._RELECTURES.clear()
    for p in TMP.glob("liens_identite_us.json*"):
        p.unlink()


def reg():
    return json.loads(liu.REGISTRE.read_text(encoding="utf-8"))


def urls_of(lien, cle="buttons"):
    return liu._urls_of(lien.get(cle) or [])


try:
    neuf_gms()

    # ═══ 1. Nommage sur les 46 vrais noms ═══════════════════════════════
    print("\n— nommage —")
    IDENTS = ["ibenhaastrup", "nanas__nyspam", "ariiiann__", "e30princesss", "ema_bb0",
              "templeton", "va_test", "zezatwins"]
    rate_pd, rate_cp, cp_ecarts, trop_long, gabarit = [], [], set(), [], []
    for ident in IDENTS:
        for nom_g in NOMS:
            n = liu.nom_lien({"nom": nom_g}, ident)
            if not n or pd.personne(n) != pd.personne(nom_g):
                rate_pd.append((nom_g, ident, n))
            if cp.pseudo(n) != cp.pseudo(nom_g):
                if nom_g in ECARTS_CP:
                    cp_ecarts.add(nom_g)
                else:
                    rate_cp.append((nom_g, ident, n, cp.pseudo(n), cp.pseudo(nom_g)))
            if len(n) > liu.NOM_MAX:
                trop_long.append(n)
            if liu.est_base(n) or cp.est_gabarit(n):
                gabarit.append(n)
    check("46 vrais noms × 8 identités : le podium lit TOUJOURS la personne (et le SPAM) du global",
          not rate_pd, rate_pd[:5])
    check("le report des clics lit la même personne, sauf les 4 écarts connus (tsiry/eddy n)",
          not rate_cp, rate_cp[:5])
    check("les 4 écarts connus sont bien des écarts (sinon la liste est périmée)",
          cp_ecarts == ECARTS_CP, cp_ecarts)
    check("aucun nom de lien d'identité au-delà de 60 caractères", not trop_long, trop_long[:3])
    check("aucun nom de lien d'identité pris pour une page de base ou un gabarit", not gabarit, gabarit[:3])
    attendus = {
        ("( Carter ) 1", "ibenhaastrup"): "(Carter) ibenhaastrup",
        ("( Carter ) SPAM", "ibenhaastrup"): "(Carter) ibenhaastrup SPAM",
        ("(Ricardo) 1 SPAM", "ibenhaastrup"): "(Ricardo) ibenhaastrup SPAM",
        ("EUD", "ibenhaastrup"): "(EUD) ibenhaastrup",
        ("tsiry 1", "ibenhaastrup"): "(tsiry 1) ibenhaastrup",
        ("Printsyyy X1", "ibenhaastrup"): "(Printsyyy X1) ibenhaastrup",
        ("(VA 4 Noum)", "ibenhaastrup"): "(VA 4 Noum) ibenhaastrup",
        ("LaBoule ( Phone )", "ibenhaastrup"): "LaBoule (Phone) ibenhaastrup",
        ("Laboule ( X )", "ibenhaastrup"): "Laboule (X) ibenhaastrup",
        ("( Carter ) 1", "nanas__nyspam"): "(Carter) nanas__nysp-am",
        ("( Carter ) 1", "templeton"): "(Carter) te-mpleton",
    }
    for (g, i), voulu in attendus.items():
        n = liu.nom_lien({"nom": g}, i)
        check(f"nom_lien(« {g} », {i}) = « {voulu} »", n == voulu, n)
    n = liu.nom_lien({"nom": "( Carter ) 1"}, "nanas__nyspam")
    check("une identité qui contient « spam » ne rend pas SPAM un global qui ne l'est pas",
          pd.personne(n) == ("Carter", False) and "spam" not in n.lower(), n)
    n = liu.nom_lien({"nom": "Twitter VA 1 @abdoul"}, "ibenhaastrup")
    check("global à « @pseudo » : le podium retrouve le pseudo",
          pd.personne(n) == ("abdoul", False), n)
    n = liu.nom_lien({"personne": "Gerome", "spam": True}, "ibenhaastrup")
    check("sans nom, la personne et le SPAM enregistrés suffisent",
          n == "(Gerome) ibenhaastrup SPAM", n)
    n = liu.nom_lien({"nom": "( Carter ) SPAM"}, "x" * 90)
    check("identité très longue : nom coupé à 60, SPAM gardé",
          len(n) <= 60 and n.endswith(" SPAM") and pd.personne(n) == ("Carter", True), n)
    check("identité vide : pas de nom", liu.nom_lien({"nom": "EUD"}, "  ") == "")
    # regroupement du podium (et donc de la page Infloww) : aucune personne de plus
    avant = pd.entites([{"id": f"v{i}", "display_name": nm} for i, nm in enumerate(NOMS)])
    plus = [{"id": f"i{i}", "display_name": liu.nom_lien({"nom": nm}, "ibenhaastrup")}
            for i, nm in enumerate(NOMS)]
    apres = pd.entites([{"id": f"v{i}", "display_name": nm} for i, nm in enumerate(NOMS)] + plus)
    check("podium_discord.entites : les 46 liens d'identité rejoignent les entités existantes",
          set(avant) == set(apres)
          and all(len(apres[k]["ids"]) == 2 * len(avant[k]["ids"]) for k in avant),
          sorted(set(apres) ^ set(avant)))

    # ═══ 2. Pages de base ═══════════════════════════════════════════════
    print("\n— pages de base —")
    cas = {"TEMPLATE ibenhaastrup": "ibenhaastrup", "template  IbenHaastrup ": "ibenhaastrup",
           "TEMPALTE ibenhaastrup": "ibenhaastrup", "TEAMPLTE ibenhaastrup": "ibenhaastrup",
           "TEMPLATE: ellieann": "ellieann", "TEMPLATE - zezatwins": "zezatwins",
           "TEMPLATE « ariiiann__ »": "ariiiann__", "Template iben haastrup": "ibenhaastrup",
           "TEMPLATE": None, "Templeton 1": None, "( Carter ) 1": None, "EUD": None,
           "TEMPLATEibenhaastrup": None, "(TEMPLATE) iben": None, "": None, None: None}
    for nom, voulu in cas.items():
        check(f"identite_de_base({nom!r}) = {voulu!r}", liu.identite_de_base(nom) == voulu,
              liu.identite_de_base(nom))
    check("aucun des 46 vrais liens n'est une page de base", not [n for n in NOMS if liu.est_base(n)])
    b = liu.bases()
    check("bases() : une par identité, la plus ancienne retenue en cas de doublon",
          b.get("ibenhaastrup", {}).get("id") == "lnk_base_iben"
          and {"ibenhaastrup", "e30princesss", "themikkiangel", "ellieann", "zezatwins",
               "inconnue", "ariiiann__"} == set(b), sorted(b))
    eb = liu.etat_bases(["ibenhaastrup", "EllieAnn", "sans_page", "zezatwins", "ibenhaastrup",
                         "e30princesss", "themikkiangel", "ariiiann__"])
    check("etat_bases : sans page, pages orphelines, doublons",
          eb["sans_base"] == ["sans_page"] and eb["orphelines"] == ["TEMPLATE inconnue"]
          and eb["doublons"] == {"ibenhaastrup": ["tplibenh", "tplibenh2"]}
          and "EllieAnn" in eb["avec_base"] and eb["raison"] == "", eb)

    # ═══ 3. shortcodes ══════════════════════════════════════════════════
    print("\n— shortcodes —")
    import re
    tous = [liu.shortcode_pour(i, e) for i in IDENTS + ["themikkiangel_tres_long_nom", "a", "É-è"]
            for e in range(0, 100)]
    check("shortcode : 3 à 24 caractères [a-z0-9_-]",
          all(re.fullmatch(r"[a-z0-9_-]{3,24}", s) for s in tous),
          [s for s in tous if not re.fullmatch(r"[a-z0-9_-]{3,24}", s)][:5])
    check("shortcode : « ibenhaastrupcute » puis « ibenhaastruplovee »",
          liu.shortcode_pour("ibenhaastrup", 0) == "ibenhaastrupcute"
          and liu.shortcode_pour("ibenhaastrup", 1) == "ibenhaastruplovee")
    check("shortcode : 100 essais, 100 adresses différentes",
          len({liu.shortcode_pour("ibenhaastrup", e) for e in range(100)}) == 100)

    # ═══ 4. liens_equipe ════════════════════════════════════════════════
    print("\n— liste de l'équipe —")
    liens, raison = liu.liens_equipe()
    check("liens_equipe : 46 vrais + pages + autres, raison vide",
          len(liens) == 46 + len(BASES) + len(AUTRES) and raison == "", (len(liens), raison))
    check("liens_equipe : appel étiqueté « liens-identite »", F.tags[-1] == liu.ETIQUETTE, F.tags[-1:])
    F.pause = "Quota GetMySocial epuise — reprise vers 14:00 (300 min)"
    liens, raison = liu.liens_equipe()
    check("GetMySocial en pause : la dernière liste connue, et la raison",
          len(liens) == 46 + len(BASES) + len(AUTRES) and "Quota" in raison, raison)
    F.pause = None
    F.liste_leve = True
    try:
        liens, raison = liu.liens_equipe()
        check("une exception dans gms ne remonte pas", "liste en panne" in raison, raison)
    except Exception as e:                                   # noqa: BLE001
        check("une exception dans gms ne remonte pas", False, e)
    F.liste_leve = False

    # ═══ 5. definir_global ══════════════════════════════════════════════
    print("\n— lien global —")
    neuf_gms()
    r = liu.definir_global(111, "msgejessye", "admin1")
    g = r.get("global") or {}
    check("par shortcode : « EUD » (c117)",
          r["ok"] and g.get("nom") == "EUD" and g.get("code") == "117"
          and g.get("url") == OF % 117 and g.get("personne") == "EUD" and g.get("spam") is False
          and g.get("par") == "admin1" and g.get("link_id") == ID["EUD"], r)
    check("global_de(111) relit le registre", (liu.global_de("111") or {}).get("shortcode") == "msgejessye")
    r = liu.definir_global("222", "https://getmysocial.com/crtejessye/", "admin1")
    check("par adresse getmysocial.com/<sc>/ : « ( Carter ) 1 »",
          r["ok"] and r["global"]["nom"] == "( Carter ) 1" and r["global"]["personne"] == "Carter", r)
    r = liu.definir_global("333", "(gerome)   SPAM", "admin1")
    check("par nom (casse et espaces indifférents) : « (Gerome) SPAM », spam vrai",
          r["ok"] and r["global"]["nom"] == "(Gerome) SPAM" and r["global"]["spam"] is True, r)
    r = liu.definir_global("444", ID["LaBoule ( Phone )"], "admin1")
    check("par id lnk_… : « LaBoule ( Phone ) »", r["ok"] and r["global"]["personne"] == "Phone", r)
    r = liu.definir_global("555", "( Carter ) 2", "admin1")
    check("même personne qu'un autre VA : accepté, et signalé",
          r["ok"] and r.get("meme_personne") == ["222"], r)
    r = liu.definir_global("555", "sweetjessye", "admin2")
    check("redéfinir : remplacé, l'ancien est rendu et gardé au registre",
          r["ok"] and r.get("remplace", {}).get("nom") == "( Carter ) 2"
          and reg().get("globaux_anciens", [{}])[-1].get("nom") == "( Carter ) 2", r)
    check("un global actif n'est pas signalé coupé", not r.get("inactif"), r)
    F.liens[ID["( Yazid ) 1"]]["status"] = "inactive"
    r = liu.definir_global("888", "yzdjessye", "admin1")
    check("un global coupé dans GetMySocial : accepté, et signalé", r["ok"] and r.get("inactif") is True, r)
    r = liu.definir_global("666", "tplibenh", "admin1")
    check("refus : une page de base", not r["ok"] and "page de base" in r["erreur"], r)
    r = liu.definir_global("666", "otherone", "admin1")
    check("refus : un suivi d'une autre créatrice",
          not r["ok"] and "@autre" in r["erreur"] and "jessyewdiference/c<N>" in r["erreur"], r)
    r = liu.definir_global("666", "landingone", "admin1")
    check("refus : une page sans adresse OnlyFans", not r["ok"] and "adresse OnlyFans" in r["erreur"], r)
    r = liu.definir_global("666", "msgejessye", "admin1")
    check("refus : déjà le global d'un autre VA (et lequel)",
          not r["ok"] and "111" in r["erreur"] and r.get("autre_uid") == "111", r)
    r = liu.definir_global("666", "(Zed) 1", "admin1")
    check("refus : nom ambigu, les shortcodes sont donnés",
          not r["ok"] and "zedone" in r["erreur"] and "zedtwo" in r["erreur"], r)
    F.appels.clear()
    r = liu.definir_global("666", "nexistepas", "admin1")
    check("refus : introuvable, après une relecture forcée",
          not r["ok"] and "introuvable" in r["erreur"]
          and ("list", EQ, True) in F.appels, (r, F.appels))
    check("refus : valeur vide", not liu.definir_global("666", "  ")["ok"])
    F.pause = "Quota GetMySocial epuise — reprise vers 14:00 (300 min)"
    r = liu.definir_global("666", "moanjessye", "admin1")
    check("refus : GetMySocial en pause, raison donnée", not r["ok"] and "Quota" in r["erreur"], r)
    F.pause = None
    check("les refus n'ont rien écrit", set(reg()["globaux"]) == {"111", "222", "333", "444", "555", "888"},
          sorted(reg()["globaux"]))

    # ═══ 6. creer_pour_identite ═════════════════════════════════════════
    print("\n— création —")
    F.appels.clear()
    r = liu.creer_pour_identite("999", "ibenhaastrup", "999")
    check("sans lien global : refus, aucun appel MCP",
          not r["ok"] and "lien global" in r["erreur"]
          and not [a for a in F.appels if a[0] != "list"], (r, F.appels))

    F.appels.clear(); F.tags.clear()
    F.ailleurs = {"ibenhaastrupcute"}
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    dups = F.outils("duplicate_link")
    check("création : ok, adresse rendue, ni « déjà » ni « réparé »",
          r["ok"] and r["url"] == "https://getmysocial.com/ibenhaastruplovee"
          and not r["deja"] and not r["repare"] and r["erreur"] == "", r)
    check("shortcode pris ailleurs puis libre : deux duplicate_link",
          [a[1]["shortcode"] for a in dups] == ["ibenhaastrupcute", "ibenhaastruplovee"], dups)
    check("duplicate_link : depuis la page de base retenue, dans JESSY LE RETOUR, au bon nom",
          all(a[1]["link_id"] == "lnk_base_iben" and a[1]["team_id"] == EQ
              and a[1]["display_name"] == "(EUD) ibenhaastrup" for a in dups), dups)
    check("jamais de typeLink directlink ni d'url passés à une page",
          not [a for a in F.outils("update_link") if "typeLink" in a[1] or "url" in a[1]],
          F.outils("update_link"))
    copie = F.liens[r["link_id"]]
    bout = copie["buttons"]
    check("bouton OF principal et règle pays visent c117",
          bout[0]["url"] == OF % 117 and bout[0]["geofilters"][0]["destination_url"] == OF % 117, bout[0])
    check("le reste du bouton est gardé (image, effet, libellé)",
          bout[0]["image_url"] == BOUTONS_IBEN[0]["image_url"] and bout[0]["button_effect"] == "5"
          and bout[0]["label"] == "My OF 🔥", bout[0])
    check("le bouton Instagram n'est pas touché", bout[1] == BOUTONS_IBEN[1], bout[1])
    check("un libellé qui cite onlyfans.com reste du texte ; son adresse OF est rebranchée",
          bout[2]["label"] == BOUTONS_IBEN[2]["label"] and bout[2]["url"] == OF % 117, bout[2])
    check("la redirection intelligente de la page vise aussi c117",
          copie["smart_redirect"]["destination_url"] == OF % 117
          and copie["smart_redirect"]["trigger_after_visits"] == 3, copie["smart_redirect"])
    check("photo et fond : ceux de la page de base (copiés par GetMySocial)",
          copie["profile_picture"].endswith("tplibenh.webp")
          and copie["background_image"].endswith("tplibenh-fond.webp"), copie)
    check("tous les appels étiquetés « liens-identite »",
          F.tags and all(t == liu.ETIQUETTE for t in F.tags), set(F.tags))
    e = reg()["liens"].get("111:ibenhaastrup") or {}
    check("registre : l'entrée du contrat",
          e.get("etat") == "ok" and e.get("link_id") == r["link_id"]
          and e.get("shortcode") == "ibenhaastruplovee"
          and e.get("public_url") == r["url"] and e.get("global_link_id") == ID["EUD"]
          and e.get("tracking") == OF % 117 and e.get("identite") == "ibenhaastrup"
          and e.get("nom") == "(EUD) ibenhaastrup" and e.get("par") == "111"
          and isinstance(e.get("quand"), int), e)
    check("registre : l'adresse prise ailleurs est retenue",
          "ibenhaastrupcute" in reg().get("pris_ailleurs", []), reg().get("pris_ailleurs"))

    F.appels.clear()
    r2 = liu.creer_pour_identite(111, "IbenHaastrup", "111")
    check("recliquer : le même lien, « déjà », aucun appel MCP",
          r2["ok"] and r2["deja"] and not r2["repare"] and r2["url"] == r["url"]
          and r2.get("actif") is True and not [a for a in F.appels if a[0] != "list"], (r2, F.appels))

    F.appels.clear()
    r = liu.creer_pour_identite(222, "ibenhaastrup", "222")
    check("un 2e VA, même identité : l'adresse prise ailleurs n'est pas réessayée",
          r["ok"] and [a[1]["shortcode"] for a in F.outils("duplicate_link")] == ["ibenhaastrupbaby"]
          and F.liens[r["link_id"]]["display_name"] == "(Carter) ibenhaastrup", (r, F.outils("duplicate_link")))
    check("… et son bouton vise SON suivi (c129), pas celui du 1er VA",
          F.liens[r["link_id"]]["buttons"][0]["url"] == OF % 129)

    r = liu.creer_pour_identite(333, "ibenhaastrup", "333")
    check("global SPAM : lien « (Gerome) ibenhaastrup SPAM » sur c124",
          r["ok"] and r["nom"] == "(Gerome) ibenhaastrup SPAM"
          and F.liens[r["link_id"]]["buttons"][0]["url"] == OF % 124, r)

    # échec de update_link : a_reparer, puis réparé au clic suivant
    F.appels.clear()
    F.refus_update = 1
    r = liu.creer_pour_identite(444, "ibenhaastrup", "444")
    e = reg()["liens"].get("444:ibenhaastrup") or {}
    check("update refusé : pas d'adresse donnée, erreur claire",
          not r["ok"] and r["url"] == "" and "pas encore branché" in r["erreur"], r)
    check("update refusé : entrée « a_reparer » avec la copie",
          e.get("etat") == "a_reparer" and e.get("link_id") in F.liens and e.get("erreur"), e)
    lid = e.get("link_id")
    check("la copie ratée n'est pas supprimée", lid in F.liens and not F.outils("delete_links"))
    F.appels.clear()
    r = liu.creer_pour_identite(444, "ibenhaastrup", "444")
    e2 = reg()["liens"].get("444:ibenhaastrup") or {}
    check("clic suivant : réparé sur place (même lien), aucune nouvelle copie",
          r["ok"] and r["deja"] and r["repare"] and r["link_id"] == lid
          and e2.get("etat") == "ok" and e2.get("shortcode") == e.get("shortcode")
          and not F.outils("duplicate_link"), (r, F.appels))
    check("réparé : le bouton vise c125 (LaBoule ( Phone )) et le nom garde LaBoule",
          F.liens[lid]["buttons"][0]["url"] == OF % 125
          and F.liens[lid]["display_name"] == "LaBoule (Phone) ibenhaastrup", F.liens[lid])

    # update_link « ok » mais boutons non appliqués : la vérification le voit
    F.update_ignore_boutons = 1
    r = liu.creer_pour_identite(111, "zezatwins", "111")
    check("update « ok » sans effet : vérification ratée, pas d'adresse donnée",
          not r["ok"] and "ne visent pas" in r["erreur"]
          and reg()["liens"]["111:zezatwins"]["etat"] == "a_reparer", r)
    r = liu.creer_pour_identite(111, "zezatwins", "111")
    check("… réparé au clic suivant", r["ok"] and r["repare"]
          and F.liens[r["link_id"]]["buttons"][0]["url"] == OF % 117, r)

    # update_link qui ne renvoie pas le lien : on relit pour vérifier
    F.appels.clear()
    F.update_sans_corps = 1
    r = liu.creer_pour_identite(222, "ariiiann__", "222")
    noms = [a[0] for a in F.appels if a[0] != "list"]
    check("réponse d'update sans boutons : relue par get_link avant de dire oui",
          r["ok"] and noms[-2:] == ["update_link", "get_link"], noms)

    # page de base désactivée : la copie est réactivée
    F.appels.clear()
    r = liu.creer_pour_identite(111, "EllieAnn", "111")
    check("copie d'une page de base désactivée : réactivée",
          r["ok"] and F.outils("enable_link") and F.liens[r["link_id"]]["status"] == "active"
          and any("réactivé" in s for s in r["soucis"]), r)

    F.appels.clear()
    r = liu.creer_pour_identite(111, "e30princesss", "111")
    check("page de base sans bouton OF : refus clair, aucune copie",
          not r["ok"] and "aucun bouton OnlyFans" in r["erreur"] and not F.outils("duplicate_link"), r)
    r = liu.creer_pour_identite(111, "themikkiangel", "111")
    check("page de base qui est un lien direct : refus qui le dit",
          not r["ok"] and "lien direct" in r["erreur"] and not F.outils("duplicate_link"), r)
    r = liu.creer_pour_identite(111, "sans_page", "111")
    check("pas de page de base : refus qui nomme la page attendue",
          not r["ok"] and "TEMPLATE sans_page" in r["erreur"], r)

    # page de base faite a l'instant : absente du cache, trouvee a la relecture
    F.fige = list(copy.deepcopy(F.liens).values())
    nouv = page("TEMPLATE mini_caryn", "tplmini", "lnk_base_mini", [{"label": "OF", "url": OF % 559}],
                int(time.time()))
    F.liens[nouv["id"]] = nouv
    F.appels.clear()
    r = liu.creer_pour_identite(111, "mini_caryn", "111")
    check("page de base créée après le cache : relue une fois, lien créé",
          r["ok"] and ("list", EQ, True) in F.appels
          and F.liens[r["link_id"]]["buttons"][0]["url"] == OF % 117, (r, F.appels[:3]))
    F.fige = None

    # GetMySocial en pause
    F.pause = "Quota GetMySocial epuise — reprise vers 14:00 (300 min)"
    F.appels.clear()
    r = liu.creer_pour_identite(222, "zezatwins", "222")
    check("GetMySocial en pause : refus avec la raison, aucune copie",
          not r["ok"] and "Quota" in r["erreur"] and not F.outils("duplicate_link"), r)
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    check("GetMySocial en pause : un lien déjà branché est redonné quand même",
          r["ok"] and r["deja"] and r["url"].endswith("ibenhaastruplovee")
          and any("Quota" in s for s in r["soucis"]), r)
    F.pause = None

    # réponse de duplicate perdue : la copie est retrouvée à son nom
    F.appels.clear()
    F.perdre_reponse_dup = 1
    avant = len(F.liens)
    r = liu.creer_pour_identite(222, "zezatwins", "222")
    check("réponse de duplicate perdue : copie retrouvée à son nom, une seule copie",
          r["ok"] and len(F.liens) == avant + 1 and len(F.outils("duplicate_link")) == 1
          and any("retrouvée" in s for s in r["soucis"]), r)

    # registre perdu : le lien présent à son nom est repris, pas recopié
    lid = reg()["liens"]["222:zezatwins"]["link_id"]

    def oublie(d):
        d["liens"].pop("222:zezatwins")
        return True, None
    liu._ecrire(oublie)
    F.appels.clear()
    r = liu.creer_pour_identite(222, "zezatwins", "222")
    check("absent du registre, présent à son nom : repris, aucune copie, aucune écriture inutile",
          r["ok"] and r["deja"] and r["link_id"] == lid and not F.outils("duplicate_link")
          and not F.outils("update_link")
          and reg()["liens"]["222:zezatwins"].get("repris"), (r, F.appels))

    # copie supprimée à la main : recréée, l'ancienne gardée en trace
    vieux = reg()["liens"]["222:zezatwins"]
    del F.liens[vieux["link_id"]]
    F.appels.clear()
    r = liu.creer_pour_identite(222, "zezatwins", "222")
    check("copie supprimée dans GetMySocial : une nouvelle, l'ancienne dans « perdus »",
          r["ok"] and not r["deja"] and r["link_id"] != vieux["link_id"]
          and reg()["perdus"][-1]["link_id"] == vieux["link_id"]
          and r["url"] != vieux["public_url"], r)

    # le global rebranché et renommé dans GetMySocial : le lien d'identité suit
    F.liens[ID["EUD"]]["url"] = OF % 200
    F.liens[ID["EUD"]]["display_name"] = "EUD 2"
    F.appels.clear()
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    l = F.liens[r["link_id"]]
    check("global changé : même lien, rebranché sur c200 et renommé, aucune copie",
          r["ok"] and r["deja"] and r["repare"] and l["buttons"][0]["url"] == OF % 200
          and l["display_name"] == "(EUD 2) ibenhaastrup"
          and pd.personne(l["display_name"]) == pd.personne("EUD 2")
          and not F.outils("duplicate_link"), (r, l["display_name"]))
    check("… et le registre du global suit",
          liu.global_de(111)["nom"] == "EUD 2" and liu.global_de(111)["code"] == "200")

    # global supprimé
    del F.liens[ID["(VA 6 Noum) 1"]]
    r = liu.creer_pour_identite(555, "ibenhaastrup", "555")
    check("global disparu de GetMySocial : refus clair", not r["ok"] and "n'est plus dans" in r["erreur"], r)

    # deux clics simultanés : une seule copie
    neuf_gms()
    liu.definir_global(111, "msgejessye", "admin1")
    F.lent = 0.15
    res = []
    fils = [threading.Thread(target=lambda: res.append(liu.creer_pour_identite(111, "ibenhaastrup", "111")))
            for _ in range(3)]
    for t in fils:
        t.start()
    for t in fils:
        t.join()
    F.lent = 0.0
    check("trois clics en même temps : une seule copie, trois fois la même adresse",
          len(F.outils("duplicate_link")) == 1 and len({x["url"] for x in res}) == 1
          and all(x["ok"] for x in res) and sum(1 for x in res if not x["deja"]) == 1, res)

    # registre illisible : rien n'est écrit, rien n'est créé
    sauve = liu.REGISTRE.read_text(encoding="utf-8")
    liu.REGISTRE.write_text("{tronqué", encoding="utf-8")
    prev = liu.REGISTRE.with_suffix(".json.prev")
    if prev.exists():
        prev.unlink()
    F.appels.clear()
    r = liu.creer_pour_identite(111, "zezatwins", "111")
    r2 = liu.definir_global("777", "moanjessye", "admin1")
    check("registre illisible : refus, aucune copie, fichier laissé tel quel",
          not r["ok"] and not r2["ok"] and "illisible" in r["erreur"] + r2["erreur"]
          and not F.outils("duplicate_link")
          and liu.REGISTRE.read_text(encoding="utf-8") == "{tronqué", (r, r2))
    try:
        liu.rattachements()
        check("registre illisible : rattachements() lève au lieu de rendre {} (lignes payées)", False)
    except RuntimeError as e:
        check("registre illisible : rattachements() lève au lieu de rendre {} (lignes payées)",
              "illisible" in str(e), e)
    if hasattr(cp, "rattachements_identite_ou_panne"):
        ratt, panne = cp.rattachements_identite_ou_panne()
        check("… et clics_personnes le dit comme une panne", ratt == {} and "illisible" in panne, panne)
    liu.REGISTRE.write_text(sauve, encoding="utf-8")

    # ═══ 7. liens du VA, actifs, rattachements, identités proposées ═════
    print("\n— compte des liens —")
    neuf_gms()
    liu.definir_global(222, "crtejessye", "admin1")
    liu.definir_global(333, "cutyxjessye", "admin1")
    a = liu.creer_pour_identite(222, "ibenhaastrup", "222")
    z = liu.creer_pour_identite(222, "zezatwins", "222")
    s = liu.creer_pour_identite(333, "ibenhaastrup", "333")
    F.liens[z["link_id"]]["status"] = "inactive"
    liens, _ = liu.liens_equipe(force=True)
    du = {l["display_name"] for l in liu.liens_du_va(222, liens)}
    check("liens_du_va : ses 4 liens Carter (SPAM compris) + ses 2 liens d'identité, hors pages de base",
          du == {"( Carter ) 1", "( Carter ) 2", "( Carter ) 3", "( Carter ) SPAM",
                 "(Carter) ibenhaastrup", "(Carter) zezatwins"}, du)
    check("liens_actifs : 5 (le lien coupé ne compte pas)", liu.liens_actifs(222, liens) == 5,
          liu.liens_actifs(222, liens))
    check("liens_actifs du VA SPAM : ses liens Gerome", liu.liens_actifs(333) == 3,
          [l["display_name"] for l in liu.liens_du_va(333)])
    check("liens_actifs sans global : 0", liu.liens_actifs(999) == 0)
    # renommé à la main, le lien d'identité reste à lui (par le registre)
    F.liens[a["link_id"]]["display_name"] = "nom tapé à la main"
    check("un lien d'identité renommé à la main reste compté",
          "nom tapé à la main" in {l["display_name"] for l in liu.liens_du_va(222, liu.liens_equipe(True)[0])})
    rt = liu.rattachements()
    check("rattachements : chaque lien d'identité vers son global",
          rt == {a["link_id"]: ID["( Carter ) 1"], z["link_id"]: ID["( Carter ) 1"],
                 s["link_id"]: ID["(Gerome) SPAM"]}, rt)
    F.appels.clear()
    e2 = liu.creer_pour_identite(333, "zezatwins", "333")
    rt2 = liu.rattachements()
    check("rattachements : relu après une écriture (pas de cache périmé)",
          rt2.get(e2["link_id"]) == ID["(Gerome) SPAM"] and len(rt2) == 4, rt2)
    if hasattr(cp, "rattachements_identite"):
        check("clics_personnes.rattachements_identite lit ce registre",
              cp.rattachements_identite() == rt2, cp.rattachements_identite())
    # le podium, avec les rattachements : chaque page va à la personne de son global
    ents = pd.entites(liu.liens_equipe(True)[0], rt2)
    check("podium_discord.entites : les pages d'identité dans l'entité de leur global",
          a["link_id"] in ents.get("Carter", {}).get("ids", [])
          and s["link_id"] in ents.get("Gerome SPAM", {}).get("ids", [])
          and e2["link_id"] in ents.get("Gerome SPAM", {}).get("ids", []),
          {k: v["ids"] for k, v in ents.items() if k in ("Carter", "Gerome SPAM")})
    ip = liu.identites_proposables(["ibenhaastrup", "sans_page", "zezatwins", "EllieAnn",
                                    "ibenhaastrup", "e30princesss"], uid=222)
    check("identites_proposables : celles qui ont une page, dans l'ordre, sans doublon",
          ip == [("ibenhaastrup", True), ("zezatwins", True), ("EllieAnn", False),
                 ("e30princesss", False)], ip)
    ip = liu.identites_proposables(["ibenhaastrup", "zezatwins"])
    check("identites_proposables sans uid : jamais « déjà »",
          ip == [("ibenhaastrup", False), ("zezatwins", False)], ip)
    check("liens_de : ses liens d'identité au registre",
          [e["identite"] for e in liu.liens_de(222)] == ["ibenhaastrup", "zezatwins"],
          liu.liens_de(222))

    # ═══ 7 bis. Relecture : les défauts corrigés ═════════════════════════
    print("\n— relecture : global remplacé —")
    neuf_gms()
    liu.definir_global(111, "( Carter ) 1", "admin1")
    a = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    page = a["link_id"]
    check("(base) page de 111 sur c129, au nom de Carter",
          a["ok"] and urls_of(F.liens[page])[0] == OF % 129
          and F.liens[page]["display_name"] == "(Carter) ibenhaastrup", (a, F.liens[page]["display_name"]))
    r = liu.definir_global(111, "( Carter ) SPAM", "admin1")
    check("global remplacé : les pages données sont à rebrancher (rendu à l'appelant)",
          r["ok"] and r.get("a_rebrancher") == ["ibenhaastrup"]
          and r.get("remplace", {}).get("nom") == "( Carter ) 1", r)
    check("global remplacé : la coche ✅ tombe tout de suite",
          liu.identites_proposables(["ibenhaastrup"], uid=111) == [("ibenhaastrup", False)])
    check("global remplacé : la page suit le global DU MOMENT dans rattachements()",
          liu.rattachements().get(page) == ID["( Carter ) SPAM"], liu.rattachements())
    check("global remplacé : a_rebrancher(111) la nomme", liu.a_rebrancher(111) == ["ibenhaastrup"],
          liu.a_rebrancher(111))
    r = liu.definir_global(222, "( Carter ) 1", "admin1")
    liens_ = liu.liens_equipe(force=True)[0]
    ids_222 = {l["id"] for l in liu.liens_du_va(222, liens_)}
    check("l'ancien global donné à 222 : la page de 111 (encore nommée Carter) n'est pas comptée chez 222",
          r["ok"] and page not in ids_222 and page in {l["id"] for l in liu.liens_du_va(111, liens_)},
          sorted(ids_222))
    F.pause = "Quota GetMySocial epuise — reprise vers 14:00 (300 min)"
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    F.pause = None
    check("GetMySocial muet : une page branchée sur l'ANCIEN global n'est pas redonnée",
          not r["ok"] and not r["url"], r)
    F.appels.clear()
    r = liu.creer_pour_identite(111, "ibenhaastrup", "admin1")
    check("rebrancher : même lien, même adresse, bouton sur c130, nom SPAM, sans copie",
          r["ok"] and r["repare"] and r["url"] == a["url"] and r["link_id"] == page
          and urls_of(F.liens[page]) and all(u == OF % 130 for u in urls_of(F.liens[page]))
          and F.liens[page]["display_name"] == "(Carter) ibenhaastrup SPAM"
          and not F.outils("duplicate_link"), (r, F.liens[page].get("display_name")))
    check("rebranchée : la coche revient, plus rien à rebrancher",
          liu.identites_proposables(["ibenhaastrup"], uid=111) == [("ibenhaastrup", True)]
          and liu.a_rebrancher(111) == [])

    print("\n— relecture : reprise du global d'un VA parti —")
    b = liu.creer_pour_identite(222, "zezatwins", "222")
    r = liu.definir_global(444, "crtejessye", "admin1")
    check("pris par 222, toujours membre : refus, et l'uid est rendu",
          not r["ok"] and r.get("autre_uid") == "222", r)
    r = liu.definir_global(444, "crtejessye", "admin1", partis=["222"])
    check("222 parti : le global passe à 444, l'ancienne fiche est archivée",
          r["ok"] and r.get("repris_de") == "222" and r.get("pages_du_parti") == 1
          and liu.global_de(222) is None and (liu.global_de(444) or {}).get("shortcode") == "crtejessye"
          and any(x.get("uid") == "222" and x.get("libere_pour") == "444"
                  for x in reg().get("globaux_anciens", [])), r)
    check("… et les pages du parti restent sur ce même lien (rattachements)",
          liu.rattachements().get(b["link_id"]) == ID["( Carter ) 1"], liu.rattachements())
    r = liu.definir_global(555, "crtejessye", "admin1", partis=["999"])
    check("partis ne libère que le VA nommé : 444 garde son global",
          not r["ok"] and r.get("autre_uid") == "444", r)

    print("\n— relecture : réponse de duplicate_link perdue puis rejouée (409) —")
    neuf_gms()
    liu.definir_global(111, "msgejessye", "admin1")
    F.rejouer_dup = 1
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    a_son_nom = [l for l in F.liens.values() if l["display_name"] == "(EUD) ibenhaastrup"]
    check("409 sur la copie de ce clic : reprise, pas de seconde copie",
          r["ok"] and len(a_son_nom) == 1 and len(F.outils("duplicate_link")) == 1
          and r["url"] == "https://getmysocial.com/ibenhaastrupcute"
          and reg()["liens"]["111:ibenhaastrup"]["link_id"] == a_son_nom[0]["id"], (r, len(a_son_nom)))
    check("… branchée sur le suivi du VA, adresse non retenue comme prise ailleurs",
          all(u == OF % 117 for u in urls_of(a_son_nom[0]))
          and "ibenhaastrupcute" not in reg().get("pris_ailleurs", []), reg().get("pris_ailleurs"))
    F.ailleurs = {"zezatwinscute"}
    r = liu.creer_pour_identite(111, "zezatwins", "111")
    check("un vrai 409 (adresse prise par un autre compte) : adresse suivante, retenue",
          r["ok"] and r["url"].endswith("zezatwinslovee")
          and "zezatwinscute" in reg().get("pris_ailleurs", []), r)

    print("\n— relecture : registre non écrit —")
    neuf_gms()
    liu.definir_global(111, "msgejessye", "admin1")
    _ecrire_vrai = liu.safe_json.write
    liu.safe_json.write = lambda *a_, **k_: False
    try:
        r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    finally:
        liu.safe_json.write = _ecrire_vrai
    check("registre non écrit : l'adresse n'est PAS donnée, l'erreur le dit",
          not r["ok"] and not r["url"] and "non enregistré" in r["erreur"], r)
    n_copies = len(F.outils("duplicate_link"))
    r = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    check("clic suivant : la même page reprise à son nom, sans nouvelle copie",
          r["ok"] and len(F.outils("duplicate_link")) == n_copies
          and liu.rattachements().get(r["link_id"]) == ID["EUD"], r)

    print("\n— relecture : adresse changée dans GetMySocial —")
    F.liens[r["link_id"]]["shortcode"] = "ibennouveau"
    r2 = liu.creer_pour_identite(111, "ibenhaastrup", "111")
    check("page d'identité : la NOUVELLE adresse est redonnée, et retenue",
          r2["ok"] and r2["url"] == "https://getmysocial.com/ibennouveau" and r2.get("adresse_changee")
          and reg()["liens"]["111:ibenhaastrup"]["public_url"] == r2["url"], r2)
    F.liens[r["link_id"]]["shortcode"] = "ibenencore"
    F.liens[ID["EUD"]]["shortcode"] = "eudneuf"
    act = liu.actualiser(111, liu.liens_equipe(force=True)[0])
    check("actualiser (entretien, sans appel MCP) : adresses de la page et du global suivies",
          act["adresses"] == ["ibenhaastrup"]
          and reg()["liens"]["111:ibenhaastrup"]["public_url"] == "https://getmysocial.com/ibenencore"
          and liu.global_de(111)["public_url"] == "https://getmysocial.com/eudneuf"
          and act["global"]["public_url"] == "https://getmysocial.com/eudneuf", act)
    F.liens[ID["EUD"]]["url"] = OF % 201
    act = liu.actualiser(111, liu.liens_equipe(force=True)[0])
    check("actualiser : global rebranché dans GetMySocial -> page à rebrancher",
          act["a_rebrancher"] == ["ibenhaastrup"] and liu.global_de(111)["code"] == "201", act)

    print("\n— relecture : global retiré de l'équipe —")
    neuf_gms()
    liu.definir_global(111, "msgejessye", "admin1")
    del F.liens[ID["EUD"]]
    liens_ = liu.liens_equipe(force=True)[0]
    check("global_present : faux quand il n'est plus dans la liste, None sans liste",
          liu.global_present(111, liens_) is False and liu.global_present(111, None) is None
          and liu.global_present(999, liens_) is False)
    F.appels.clear()
    rs = [liu.creer_pour_identite(111, "ibenhaastrup", "111") for _ in range(5)]
    forces = [a_ for a_ in F.appels if a_[0] == "list" and a_[2]]
    check("cinq clics, global absent : une relecture forcée au plus, refus clair à chaque fois",
          len(forces) <= 1 and all(not x["ok"] and "n'est plus dans" in x["erreur"] for x in rs),
          (len(forces), rs[-1]))

    print("\n— relecture : gabarits, règle étroite —")
    F.liens["lnk_teamplayer"] = lien_direct("(Teamplayer) 1", "teampl1", "lnk_teamplayer", 150, 1791100200)
    r = liu.definir_global(777, "teampl1", "admin1")
    check("un VA dont le nom contient « teampl » peut avoir un global", r["ok"], r)
    check("est_base : « TEMPLATE x » oui ; « Temple 1 », « Templeton », « (Teamplayer) 1 » non",
          liu.est_base("TEMPLATE x") and liu.est_base("Tempalte x")
          and not any(liu.est_base(n) for n in ("Temple 1", "Templeton 2", "(Teamplayer) 1",
                                                "Twitter VA 5 @teamplayer")))

    # ═══ 8. gms : les deux aides ajoutées ═══════════════════════════════
    print("\n— gms.get_link / gms.update_link —")
    F.appels.clear()
    r = gms.get_link("lnk_base_iben", "6a0e4739bfa0c238f20a8bf5")
    check("gms.get_link : texte JSON décodé, team_id préfixé tm_",
          r["ok"] and r["link"]["display_name"] == "TEMPLATE ibenhaastrup"
          and F.appels[-1] == ("get_link", {"link_id": "lnk_base_iben", "team_id": EQ}), (r, F.appels[-1:]))
    r = gms.get_link("lnk_absent")
    check("gms.get_link : l'erreur remonte", not r["ok"] and "link_not_found" in r["error"])
    r = gms.update_link("lnk_base_zeza", {"display_name": "TEMPALTE zezatwins"}, EQ)
    check("gms.update_link : rend le lien", r["ok"] and r["link"]["id"] == "lnk_base_zeza", r)
    check("gms.get_link sans id : refus sans appel", not gms.get_link("")["ok"])
    check("gms._objet_lien : repr Python et enveloppe « data »",
          gms._objet_lien("{'data': {'id': 'x', 'n': 1}}") == {"id": "x", "n": 1}
          and gms._objet_lien("pas du json") == {})

finally:
    gms._call_tool, gms.list_links_team = SAV
    safe_json.write_text = _write_text_vrai

# ── mise en service par etapes : dossier_ouvert ─────────────────────────────
_CFG_VRAI = liu.CONFIG
liu.CONFIG = TMP / "liens_identite_us_config.json"
try:
    check("etapes : sans config, seul le dossier d'essai (eud0616_94567) recoit le salon",
          liu.dossier_ouvert("eud0616_94567") and liu.dossier_ouvert("EUD0616_94567")
          and not liu.dossier_ouvert("bo7_123") and not liu.dossier_ouvert(""))
    liu.CONFIG.write_text(json.dumps({"dossiers": ["bo7_123"]}), encoding="utf-8")
    check("etapes : la config donne sa propre liste (et remplace l'essai)",
          liu.dossier_ouvert("bo7_123") and not liu.dossier_ouvert("eud0616_94567"))
    liu.CONFIG.write_text(json.dumps({"tous": True}), encoding="utf-8")
    check("etapes : {\"tous\": true} ouvre tous les dossiers", liu.dossier_ouvert("nimporte_qui"))
    liu.CONFIG.write_text("{casse", encoding="utf-8")
    check("etapes : config illisible -> on reste sur l'essai, jamais « tous »",
          liu.dossier_ouvert("eud0616_94567") and not liu.dossier_ouvert("bo7_123"))
finally:
    liu.CONFIG = _CFG_VRAI

check("isolation : aucune écriture hors du dossier temporaire", not HORS_TMP, HORS_TMP[:5])
check("isolation : le vrai registre data/liens_identite_us.json est tel qu'avant",
      _etat_vrai() == VRAI_AVANT, (_etat_vrai(), VRAI_AVANT))
shutil.rmtree(TMP, ignore_errors=True)

print(f"\nRESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
