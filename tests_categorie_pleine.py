# -*- coding: utf-8 -*-
"""tests_categorie_pleine.py — une catégorie « Manager X » pleine a sa suite.

Discord refuse un 51e salon dans une catégorie. Le 16/11/2026, « 🔵┤ Manager
YOSHIKI ├🔵 » de TRUST INSTAGRAM tenait 50 salons : plus aucun ticket ne
s'ouvrait (CHANNEL_PARENT_MAX_CHANNELS à chaque tour, pour expdie et
stanley010182). Propriétaire : « fais une catégorie 2 alors ».

Ce qui est vérifié (tickets_discord) :
  - catégorie pleine : « 🔵┤ Manager YOSHIKI 2 ├🔵 » est créée, rangée sous la
    première, et le ticket y naît ; le suivant y va sans en créer une autre ;
  - une place se libère dans la première : le ticket suivant y retourne ;
  - la « 2 » pleine aussi : la « 3 » ;
  - un nom retapé à la main (« Manager Yoshiki🥷 ») a sa suite au nom du jour ;
  - la position refusée : la catégorie est créée quand même ;
  - la suite refusée : pas de ticket hors de toute catégorie, et c'est dit ;
  - la « 2 » est lue comme le même manager par les salons ET par les liens
    GetMySocial, et un tour de suivi des managers n'y touche pas ;
  - un manager qui part avec deux catégories : l'arrivé reprend les deux
    (« Manager SPECTRUM » et « Manager SPECTRUM 2 »), jamais un autre arrivé ;
  - un parti seul : ses VA vont dans une catégorie qui a de la place, la suite
    est créée s'il le faut, et la charge d'un manager compte ses deux catégories ;
  - un arrivé qui avait déjà sa catégorie relève les deux catégories du parti ;
  - les deux catégories d'un parti sont renommées d'un bloc ou attendent ; la
    limite connue (la « 2 » refusée après la première) ne perd personne ;
  - une « Manager 1392… » (surnom illisible) n'est jamais prise pour une suite.

Tout se joue dans un dossier temporaire avec un faux Discord en mémoire :
aucun appel réseau, rien n'est écrit dans data/.
Lancement : python tests_categorie_pleine.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


G = "778"
ROLE_MGR = "900"
YOSHIKI, MOAN, VECTOR, SPECTRUM, ZED, LOYC = "101", "102", "103", "104", "105", "106"
N1 = {YOSHIKI: "🔵┤ Manager YOSHIKI ├🔵", MOAN: "🔵┤ Manager MOAN ├🔵",
      VECTOR: "🔵┤ Manager VECTOR ├🔵", SPECTRUM: "🔵┤ Manager SPECTRUM ├🔵",
      ZED: "🔵┤ Manager ZED ├🔵"}


def n2(uid, k=2):
    return N1[uid].replace(" ├🔵", f" {k} ├🔵")


class FauxDiscord:
    """Le serveur en mémoire de tests_managers_auto, avec la règle qui manquait :
    une catégorie ne tient que MAX salons."""
    MAX = 50

    def __init__(self):
        self.roles = [{"id": ROLE_MGR, "name": "🛡️ Manager"},
                      {"id": "800", "name": "🧪 Essai"}, {"id": "700", "name": "✅ Vérifié"}]
        self.membres, self.salons, self.appels, self.refus = {}, {}, [], []
        self.sans_position = False     # 400 sur une catégorie créée avec « position »
        self.sans_categorie = False    # 403 sur toute création de catégorie
        self.avant_salon = None        # appelé une fois, juste avant la création d'un salon
        self.une_fois = {}             # morceau d'adresse -> fonction, appelée au 1er GET qui le contient
        self.salons_lisibles = None    # n : la liste des salons ne se lit que n fois, puis 500
        self.refus_nom = set()         # salons dont le renommage rend 500
        self.suivant = 9000

    def membre(self, uid, username, nick=None, manager=False):
        self.membres[uid] = {"user": {"id": uid, "username": username, "global_name": None},
                             "nick": nick, "roles": [ROLE_MGR] if manager else []}

    def role(self, uid, manager):
        r = self.membres[uid]["roles"]
        if manager and ROLE_MGR not in r:
            r.append(ROLE_MGR)
        if not manager and ROLE_MGR in r:
            r.remove(ROLE_MGR)

    def categorie(self, cid, nom, pos):
        self.salons[cid] = {"id": cid, "type": 4, "name": nom, "position": pos, "guild_id": G,
                            "permission_overwrites": [
                                {"id": G, "type": 0, "allow": "0", "deny": str(tk.VOIR)},
                                {"id": ROLE_MGR, "type": 0, "allow": str(tk.MANAGER), "deny": "0"}]}

    def ticket(self, cid, va, parent, manager, pos=0):
        self.salons[cid] = {"id": cid, "type": 0, "name": f"─│🔵┤-va-＠va{va}",
                            "parent_id": parent, "position": pos, "guild_id": G,
                            "permission_overwrites": [
                                {"id": G, "type": 0, "allow": "0", "deny": str(tk.VOIR)},
                                {"id": va, "type": 1, "allow": str(tk.MEMBRE), "deny": "0"},
                                {"id": ROLE_MGR, "type": 0, "allow": str(tk.MANAGER), "deny": "0"},
                                {"id": manager, "type": 1, "allow": str(tk.MANAGER), "deny": "0"}]}

    def remplir(self, cat, manager, n, debut):
        """n tickets dans `cat` : salons debut…, VA 1debut… Rend {va: (salon, manager)}."""
        out = {}
        for i in range(n):
            cid, va = str(debut + i), str(100000 + debut + i)
            self.membre(va, f"va{va}")
            self.ticket(cid, va, cat, manager, i)
            out[va] = (cid, manager)
        return out

    def ecritures(self):
        return [(m, c, k) for m, c, k in self.appels if m != "GET"]

    def enfants(self, cid):
        return sorted(c["id"] for c in self.salons.values() if c.get("parent_id") == cid)

    def cats(self, nom=None):
        return [c for c in self.salons.values() if c["type"] == 4 and (nom is None or c["name"] == nom)]

    def _plein(self, parent):
        return len(self.enfants(parent)) >= self.MAX

    def __call__(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw))
        base = chemin.split("?", 1)[0]
        corps = kw.get("json") or {}
        p = base.strip("/").split("/")
        plein = (400, {"message": "Invalid Form Body", "code": 50035, "errors": {"parent_id": {
            "_errors": [{"code": "CHANNEL_PARENT_MAX_CHANNELS",
                         "message": "Maximum number of channels in category reached (50)"}]}}})
        if methode == "GET":
            for bout in [b for b in self.une_fois if b in base]:
                self.une_fois.pop(bout)()
        if p[0] == "guilds":
            if base.endswith("/roles") and methode == "GET":
                return 200, copy.deepcopy(self.roles)
            if base.endswith("/channels") and methode == "GET":
                if self.salons_lisibles is not None:
                    if self.salons_lisibles <= 0:
                        return 500, {"message": "panne"}
                    self.salons_lisibles -= 1
                return 200, copy.deepcopy(list(self.salons.values()))
            if base.endswith("/channels") and methode == "POST":
                if corps.get("type") == 4:
                    if self.sans_categorie:
                        self.refus.append(("categorie", corps.get("name")))
                        return 403, {"message": "Missing Permissions"}
                    if self.sans_position and "position" in corps:
                        self.refus.append(("position", corps.get("name")))
                        return 400, {"message": "Invalid Form Body"}
                if corps.get("type") != 4 and self.avant_salon:
                    crochet, self.avant_salon = self.avant_salon, None
                    crochet()
                if corps.get("type") == 4:
                    pass
                elif corps.get("parent_id") and self._plein(corps["parent_id"]):
                    self.refus.append(("plein", corps.get("parent_id")))
                    return plein
                self.suivant += 1
                cid = str(self.suivant)
                c = {"id": cid, "type": corps.get("type", 0), "name": corps.get("name"),
                     "position": corps.get("position", 999 if corps.get("type") == 4 else 50),
                     "guild_id": G,
                     "permission_overwrites": copy.deepcopy(corps.get("permission_overwrites") or [])}
                if corps.get("parent_id"):
                    c["parent_id"] = corps["parent_id"]
                self.salons[cid] = c
                return 201, {"id": cid}
            if base.endswith("/members") and methode == "GET":
                return 403, {"message": "Missing Access"}
            if base.endswith("/members/search"):
                q = str((kw.get("params") or {}).get("query") or "")
                lim = int((kw.get("params") or {}).get("limit") or 100)
                vus = sorted((m for m in self.membres.values()
                              if m["user"]["username"].startswith(q)
                              or str(m.get("nick") or "").lower().startswith(q)),
                             key=lambda m: m["user"]["username"])
                return 200, copy.deepcopy(vus[:lim])
            if "/members/" in base and "/roles/" in base and methode == "PUT":
                return 204, {}
            if len(p) == 4 and p[2] == "members" and methode == "GET":
                m = self.membres.get(p[3])
                return (200, copy.deepcopy(m)) if m else (404, {"message": "Unknown Member"})
        if p[0] == "channels":
            cid = p[1]
            c = self.salons.get(cid)
            if len(p) == 2:
                if methode == "GET":
                    return (200, copy.deepcopy(c)) if c else (404, {})
                if methode == "PATCH":
                    if not c:
                        return 404, {}
                    if "parent_id" in corps and corps["parent_id"] != c.get("parent_id") \
                            and self._plein(corps["parent_id"]):
                        self.refus.append(("plein", corps["parent_id"]))
                        return plein
                    if "name" in corps and cid in self.refus_nom:
                        return 500, {"message": "panne"}
                    if "name" in corps:
                        c["name"] = corps["name"]
                    if "parent_id" in corps:
                        c["parent_id"] = corps["parent_id"]
                    return 200, copy.deepcopy(c)
                if methode == "DELETE":
                    if not c:
                        return 404, {}
                    del self.salons[cid]
                    return 200, copy.deepcopy(c)
            if len(p) == 4 and p[2] == "permissions":
                if not c:
                    return 404, {}
                c["permission_overwrites"] = [o for o in c["permission_overwrites"] if o["id"] != p[3]]
                if methode == "PUT":
                    c["permission_overwrites"].append({"id": p[3], "type": corps.get("type", 1),
                                                       "allow": corps.get("allow", "0"),
                                                       "deny": corps.get("deny", "0")})
                return 204, {}
            if len(p) == 3 and p[2] == "messages" and methode == "POST":
                self.suivant += 1
                return 200, {"id": str(self.suivant)}
            if len(p) == 4 and p[2] == "pins":
                return 204, {}
        return 404, {"message": f"route inconnue {methode} {chemin}"}


TMP = pathlib.Path(tempfile.mkdtemp(prefix="categorie_pleine_"))
_SAUVE = {k: getattr(tk, k) for k in ("_api", "ETAT_FICHIER", "CONFIG_FICHIER", "JOURNAL_FICHIER",
                                       "PAUSE_RECHERCHE_S", "LIMITE_RECHERCHE")}
_n = [0]


def monde(managers=(YOSHIKI,), config=None):
    """tickets_discord remis à zéro sur un dossier neuf et un faux Discord vide."""
    _n[0] += 1
    d = TMP / f"m{_n[0]}"
    d.mkdir()
    tk.ETAT_FICHIER = d / "tickets.json"
    tk.CONFIG_FICHIER = d / "tickets_config.json"
    tk.JOURNAL_FICHIER = d / "managers_auto.json"
    tk.PAUSE_RECHERCHE_S = 0
    tk.LIMITE_RECHERCHE = 100
    for cache in (tk._CACHE, tk._DITS, tk._PAUSE, tk._VU_TOUR, tk._RATES_DITS):
        cache.clear()
    cfg = {"serveurs": [G], "managers_auto_max": 20, "managers_auto_realignes": 200}
    cfg.update(config or {})
    tk.CONFIG_FICHIER.write_text(json.dumps(cfg), encoding="utf-8")
    f = FauxDiscord()
    f.membre(YOSHIKI, "yo_ofm", "Yoshiki")
    f.membre(MOAN, "moan_ofm", "Moan")
    f.membre(VECTOR, "vector.ofm", "Vector")
    f.membre(SPECTRUM, "gh_os_t_1", "Spectrum")
    f.membre(ZED, "zed_ofm", "Zed")
    f.membre(LOYC, "loyc_ofm", "Loÿc")
    for u in managers:
        f.role(u, True)
    for i in range(201, 216):
        f.membre(str(i), f"va{i}")
    tk._api = f
    return f


def poser_fiches(tickets, tours=0):
    fiches = {f"{G}:{va}": {"salon": salon, "manager": mgr, "ouvert": 1, "essai": True, "accueil": ""}
              for va, (salon, mgr) in tickets.items()}
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": fiches, "tours": {G: tours}}), encoding="utf-8")


def fiche(va):
    return (json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8")).get("tickets") or {}).get(f"{G}:{va}") or {}


def muet():
    return contextlib.redirect_stdout(io.StringIO())


def creations_cat(f):
    return [k["json"] for m, c, k in f.ecritures()
            if m == "POST" and c.endswith("/channels") and (k.get("json") or {}).get("type") == 4]


try:
    # ══ 0. le nom de la suite se lit comme le même manager ════════════════
    print("\n— 0. « Manager YOSHIKI 2 » = YOSHIKI, pour les salons et pour les liens")
    my = {"nick": "Yoshiki", "user": {"id": YOSHIKI, "username": "yo_ofm"}}
    check("nom : la première catégorie garde son nom d'avant",
          tk.nom_categorie(my) == N1[YOSHIKI] == tk.nom_categorie(my, 1), tk.nom_categorie(my))
    check("nom : la suite porte le numéro (« … YOSHIKI 2 ├🔵 », « … 3 ├🔵 »)",
          tk.nom_categorie(my, 2) == n2(YOSHIKI) and tk.nom_categorie(my, 3) == n2(YOSHIKI, 3))
    check("clé : la suite désigne le même manager (tickets_discord)",
          tk._cle_categorie(n2(YOSHIKI)) == "YOSHIKI" == tk._cle_categorie(N1[YOSHIKI])
          and tk._cle_categorie(n2(YOSHIKI, 12)) == "YOSHIKI")
    check("clé : liens_va lit la catégorie par la même fonction (un seul rangement)",
          "tk._cle_categorie(c.get(\"name\"))" in (BOT / "liens_va.py").read_text(encoding="utf-8")
          and lv.nom_dans_categorie(n2(YOSHIKI)) == "YOSHIKI 2")
    check("le maximum est celui de Discord (50 salons par catégorie)", tk.MAX_SALONS_CATEGORIE == 50)

    # ══ 1. le cas du 16/11 : 50 salons, deux VA attendent ═════════════════
    print("\n— 1. catégorie pleine : la « 2 » est créée et le ticket y naît")
    f = monde()
    f.categorie("11", N1[YOSHIKI], 7)
    f.categorie("20", "💬 DISCUSSION", 3)
    poser_fiches(f.remplir("11", YOSHIKI, 50, 3000))
    with muet() as sortie:
        sal = tk.ouvrir_ticket("201", {"id": G})
    dit = sortie.getvalue()
    deux = f.cats(n2(YOSHIKI))
    check("plein : le ticket est ouvert (il était refusé à chaque tour)", bool(sal), dit[-300:])
    check("plein : une seule catégorie créée, « 🔵┤ Manager YOSHIKI 2 ├🔵 »",
          len(deux) == 1 and [c["name"] for c in creations_cat(f)] == [n2(YOSHIKI)], creations_cat(f))
    check("plein : le ticket est dans la « 2 », la première reste à 50",
          deux and f.salons[sal].get("parent_id") == deux[0]["id"] and len(f.enfants("11")) == 50)
    check("plein : Discord n'a rien eu à refuser (aucun essai dans la catégorie pleine)",
          not f.refus, f.refus)
    check("plein : la « 2 » est rangée juste sous la première (même position, plus récente)",
          deux and deux[0]["position"] == 7
          and [c["id"] for c in sorted(f.cats(), key=tk._rang)] == ["20", "11", deux[0]["id"]],
          [(c["name"], c["position"]) for c in sorted(f.cats(), key=tk._rang)])
    check("plein : la « 2 » est fermée à @everyone et ouverte au rôle Manager, comme la première",
          deux and {o["id"]: (o["allow"], o["deny"]) for o in deux[0]["permission_overwrites"]}.get(G)
          == ("0", str(tk.VOIR))
          and any(o["id"] == ROLE_MGR for o in deux[0]["permission_overwrites"]),
          deux and deux[0]["permission_overwrites"])
    check("plein : le VA est confié à Yoshiki (fiche et droits du salon)",
          fiche("201").get("manager") == YOSHIKI and fiche("201").get("salon") == sal
          and any(o["id"] == YOSHIKI for o in f.salons[sal]["permission_overwrites"]), fiche("201"))
    check("plein : c'est dit au journal", "pleine" in dit and n2(YOSHIKI) in dit, dit[-300:])
    f.appels.clear()
    with muet():
        sal2 = tk.ouvrir_ticket("202", {"id": G})
    check("plein : le ticket suivant va dans la « 2 », sans troisième catégorie",
          sal2 and f.salons[sal2].get("parent_id") == deux[0]["id"] and not creations_cat(f)
          and not f.refus, (sal2, creations_cat(f), f.refus))
    f.appels.clear()
    with muet():
        b = tk.suivre_managers(G)
    check("plein : le suivi des managers ne touche à rien (deux catégories, un manager)",
          not f.ecritures() and not b["ignore"] and not b["rates"], (f.ecritures(), b))
    check("plein : les fiches de la « 2 » restent à Yoshiki",
          fiche("201").get("manager") == YOSHIKI and fiche("202").get("manager") == YOSHIKI)

    # ══ 2. une place se libère dans la première ═══════════════════════════
    print("\n— 2. une place se libère dans la première : on y retourne")
    del f.salons["3007"]
    f.appels.clear()
    with muet():
        sal3 = tk.ouvrir_ticket("203", {"id": G})
    check("place libérée : le ticket va dans la première, pas dans la « 2 »",
          sal3 and f.salons[sal3].get("parent_id") == "11" and not creations_cat(f),
          sal3 and f.salons[sal3].get("parent_id"))

    # ══ 3. la « 2 » pleine aussi ══════════════════════════════════════════
    print("\n— 3. la « 2 » pleine aussi : la « 3 »")
    f = monde()
    f.categorie("11", N1[YOSHIKI], 4)
    f.categorie("12", n2(YOSHIKI), 5)
    t = f.remplir("11", YOSHIKI, 50, 3000)
    t.update(f.remplir("12", YOSHIKI, 50, 4000))
    poser_fiches(t)
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    trois = f.cats(n2(YOSHIKI, 3))
    check("2 pleines : « 🔵┤ Manager YOSHIKI 3 ├🔵 » créée, le ticket dedans",
          sal and len(trois) == 1 and f.salons[sal].get("parent_id") == trois[0]["id"]
          and not f.refus, (sal, [c["name"] for c in f.cats()], f.refus))
    check("2 pleines : la « 3 » est rangée sous la « 2 »", trois and trois[0]["position"] == 5,
          trois and trois[0]["position"])

    # ══ 4. un nom retapé à la main ════════════════════════════════════════
    print("\n— 4. « Manager Yoshiki🥷 » pleine : sa suite au nom du jour")
    f = monde()
    f.categorie("11", "🔵┤ Manager Yoshiki🥷 ├🔵", 2)
    poser_fiches(f.remplir("11", YOSHIKI, 50, 3000))
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    deux = f.cats(n2(YOSHIKI))
    check("nom retapé : la suite est créée (« … YOSHIKI 2 ├🔵 ») et sert",
          sal and len(deux) == 1 and f.salons[sal].get("parent_id") == deux[0]["id"]
          and len(f.cats()) == 2, [c["name"] for c in f.cats()])
    check("nom retapé : la première n'est ni renommée ni doublée",
          f.salons["11"]["name"] == "🔵┤ Manager Yoshiki🥷 ├🔵" and not f.cats(N1[YOSHIKI]))

    # ══ 5. la position refusée ════════════════════════════════════════════
    print("\n— 5. Discord refuse la position : la catégorie est créée quand même")
    f = monde()
    f.sans_position = True
    f.categorie("11", N1[YOSHIKI], 7)
    poser_fiches(f.remplir("11", YOSHIKI, 50, 3000))
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    deux = f.cats(n2(YOSHIKI))
    check("position refusée : la « 2 » existe et le ticket y est",
          sal and len(deux) == 1 and f.salons[sal].get("parent_id") == deux[0]["id"],
          (sal, f.refus))
    check("position refusée : un seul refus, puis la création sans position",
          f.refus == [("position", n2(YOSHIKI))] and len(creations_cat(f)) == 2
          and "position" not in creations_cat(f)[1], creations_cat(f))

    # ══ 6. la suite refusée ═══════════════════════════════════════════════
    print("\n— 6. Discord refuse la catégorie : pas de ticket perdu hors catégorie")
    f = monde()
    f.sans_categorie = True
    f.categorie("11", N1[YOSHIKI], 7)
    poser_fiches(f.remplir("11", YOSHIKI, 50, 3000))
    with muet() as sortie:
        sal = tk.ouvrir_ticket("201", {"id": G})
    dit = sortie.getvalue()
    hors = [c for c in f.salons.values() if c["type"] == 0 and not c.get("parent_id")]
    check("suite refusée : aucun ticket n'est ouvert, la fiche n'est pas écrite",
          not sal and not fiche("201").get("salon"), (sal, fiche("201")))
    check("suite refusée : aucun salon hors de toute catégorie", not hors, hors)
    check("suite refusée : c'est dit (catégorie non créée, puis salon refusé)",
          "non créée (HTTP 403)" in dit and "création refusée" in dit, dit[-400:])
    check("suite refusée : UNE seule demande de catégorie par ticket, dite une fois",
          len(creations_cat(f)) == 1 and dit.count("non créée") == 1,
          (len(creations_cat(f)), dit.count("non créée")))
    f.sans_categorie = False
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    check("suite refusée : au tour suivant, tout rentre dans l'ordre",
          sal and f.cats(n2(YOSHIKI)) and f.salons[sal].get("parent_id") == f.cats(n2(YOSHIKI))[0]["id"])

    # ══ 6 bis. la catégorie se remplit pendant qu'on ouvre le ticket ══════
    print("\n— 6 bis. la 50e place est prise entre la lecture et la création")
    f = monde()
    f.categorie("11", N1[YOSHIKI], 7)
    poser_fiches(f.remplir("11", YOSHIKI, 49, 3000))
    f.avant_salon = lambda: f.ticket("3999", "215", "11", YOSHIKI, 99)   # un autre ticket, au même instant
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    deux = f.cats(n2(YOSHIKI))
    check("course : le ticket est ouvert quand même, dans la « 2 » créée à la volée",
          sal and len(deux) == 1 and f.salons[sal].get("parent_id") == deux[0]["id"]
          and len(f.enfants("11")) == 50, (sal, f.refus, [c["name"] for c in f.cats()]))
    check("course : un seul refus de Discord, puis la seconde tentative",
          f.refus == [("plein", "11")], f.refus)

    print("\n— 6 ter. … et la liste des salons ne se relit pas : rien à l'aveugle")
    f = monde()
    f.categorie("11", N1[YOSHIKI], 7)
    poser_fiches(f.remplir("11", YOSHIKI, 49, 3000))
    f.avant_salon = lambda: f.ticket("3999", "215", "11", YOSHIKI, 99)
    f.salons_lisibles = 1                                 # la seconde lecture tombe en panne
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    check("relecture en panne : aucune catégorie créée à l'aveugle (pas de second « Manager YOSHIKI »)",
          not creations_cat(f) and len(f.cats()) == 1, [c["name"] for c in f.cats()])
    check("relecture en panne : le ticket attend le tour suivant, rien hors catégorie",
          not sal and not [c for c in f.salons.values() if c["type"] == 0 and not c.get("parent_id")], sal)

    print("\n— 6 quinquies. la « 2 » se remplit pendant l'ouverture, et la « 3 » est refusée")
    f = monde()
    f.categorie("11", N1[YOSHIKI], 7)
    f.categorie("12", n2(YOSHIKI), 7)
    t = f.remplir("11", YOSHIKI, 50, 3000)
    t.update(f.remplir("12", YOSHIKI, 49, 4000))
    poser_fiches(t)
    f.avant_salon = lambda: f.ticket("4999", "215", "12", YOSHIKI, 99)
    f.sans_categorie = True
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    check("tout plein, suite refusée : un seul salon refusé, pas de second essai dans une catégorie pleine",
          not sal and f.refus == [("plein", "12"), ("categorie", n2(YOSHIKI, 3))], f.refus)

    print("\n— 6 quater. un surnom que la clé relit mal (« Loÿc ») : sa suite est reconnue")
    f = monde(managers=(LOYC,))
    ml = f.membres[LOYC]
    f.categorie("11", tk.nom_categorie(ml), 7)
    poser_fiches(f.remplir("11", LOYC, 50, 3000))
    with muet():
        s1 = tk.ouvrir_ticket("201", {"id": G})
        s2 = tk.ouvrir_ticket("202", {"id": G})
        s3 = tk.ouvrir_ticket("203", {"id": G})
    check("Loÿc : une seule suite pour trois tickets (pas une catégorie par ticket)",
          s1 and s2 and s3 and len(f.cats()) == 2
          and len({f.salons[s]["parent_id"] for s in (s1, s2, s3)}) == 1,
          [c["name"] for c in f.cats()])

    # ══ 7. sans catégorie du tout : comme avant ═══════════════════════════
    print("\n— 7. un manager sans catégorie : la sienne, sans numéro")
    f = monde()
    poser_fiches({})
    with muet():
        sal = tk.ouvrir_ticket("201", {"id": G})
    check("aucune catégorie : « 🔵┤ Manager YOSHIKI ├🔵 » créée, sans numéro ni position",
          sal and [c["name"] for c in f.cats()] == [N1[YOSHIKI]]
          and "position" not in creations_cat(f)[0], creations_cat(f))

    # ══ 8. le manager part avec ses deux catégories, un arrivé ════════════
    print("\n— 8. Vector part avec « VECTOR » et « VECTOR 2 », Spectrum arrive")
    f = monde(managers=(YOSHIKI, SPECTRUM))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    f.categorie("14", n2(VECTOR), 3)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "14", VECTOR)
    poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR)})
    with muet():
        b = tk.suivre_managers(G)
    check("deux catégories : renommées « Manager SPECTRUM » et « Manager SPECTRUM 2 »",
          f.salons["13"]["name"] == N1[SPECTRUM] and f.salons["14"]["name"] == n2(SPECTRUM), b)
    check("deux catégories : aucun VA déplacé, aucune catégorie créée",
          f.enfants("13") == ["303"] and f.enfants("14") == ["304"] and not creations_cat(f)
          and not b["deplaces"], b)
    check("deux catégories : les VA des deux passent à Spectrum",
          fiche("203").get("manager") == SPECTRUM and fiche("204").get("manager") == SPECTRUM,
          (fiche("203"), fiche("204")))
    f.appels.clear()
    with muet():
        tk.suivre_managers(G)
    check("deux catégories : second tour, rien", not f.ecritures(), f.ecritures())

    print("\n— 8 bis. deux arrivés : la « 2 » du parti ne part pas chez le second")
    f = monde(managers=(YOSHIKI, SPECTRUM, ZED))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    f.categorie("14", n2(VECTOR), 3)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "14", VECTOR)
    poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR)})
    with muet():
        b = tk.suivre_managers(G)
    noms = sorted(c["name"] for c in f.cats())
    check("deux arrivés : les deux catégories du parti vont au MÊME arrivé",
          {tk._cle_categorie(f.salons["13"]["name"]), tk._cle_categorie(f.salons["14"]["name"])}
          in ({"SPECTRUM"}, {"ZED"}), noms)
    check("deux arrivés : l'autre a sa catégorie à lui, vide",
          len(f.cats()) == 4 and {tk._cle_categorie(c["name"]) for c in f.cats()}
          == {"YOSHIKI", "SPECTRUM", "ZED"}, noms)
    check("deux arrivés : les deux VA ont le même manager, celui de leur catégorie",
          fiche("203").get("manager") == fiche("204").get("manager") in (SPECTRUM, ZED)
          and tk._nom_court(f.membres[fiche("203")["manager"]])
          == tk._cle_categorie(f.salons["13"]["name"]), (fiche("203"), fiche("204")))

    # ══ 9. un parti seul, la catégorie de celui qui reste est presque pleine
    print("\n— 9. Vector part seul : ses VA vont là où il y a de la place")
    f = monde(managers=(YOSHIKI,))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    t = f.remplir("11", YOSHIKI, 49, 3000)
    for i, va in enumerate(("203", "204", "205")):
        f.ticket(str(303 + i), va, "13", VECTOR, i)
        t[va] = (str(303 + i), VECTOR)
    poser_fiches(t)
    with muet():
        b = tk.suivre_managers(G)
    deux = f.cats(n2(YOSHIKI))
    check("parti seul : aucun déplacement refusé par Discord",
          not f.refus and not [x for x in b["rates"] if "déplacé" in x or "créée" in x],
          (f.refus, b["rates"]))
    check("parti seul : la première est complétée (50), la « 2 » créée pour les autres",
          len(f.enfants("11")) == 50 and len(deux) == 1 and len(f.enfants(deux[0]["id"])) == 2
          and not f.enfants("13"), ([c["name"] for c in f.cats()], len(f.enfants("11"))))
    check("parti seul : les trois VA sont à Yoshiki",
          [fiche(v).get("manager") for v in ("203", "204", "205")] == [YOSHIKI] * 3)
    check("parti seul : le journal nomme la catégorie d'arrivée (« … YOSHIKI 2 »)",
          any(n2(YOSHIKI) in x for x in b["deplaces"]) and any(N1[YOSHIKI] in x for x in b["deplaces"]),
          b["deplaces"])
    f.appels.clear()
    with muet():
        tk.suivre_managers(G)
    check("parti seul : second tour, rien", not f.ecritures(), f.ecritures())

    print("\n— 9 bis. « le moins de VA » compte les deux catégories d'un manager")
    f = monde(managers=(YOSHIKI, MOAN))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("15", n2(YOSHIKI), 2)
    f.categorie("12", N1[MOAN], 3)
    f.categorie("13", N1[VECTOR], 4)
    t = f.remplir("11", YOSHIKI, 3, 3000)
    t.update(f.remplir("15", YOSHIKI, 20, 4000))
    t.update(f.remplir("12", MOAN, 10, 5000))
    f.ticket("303", "203", "13", VECTOR)
    t["203"] = ("303", VECTOR)
    poser_fiches(t)
    with muet():
        b = tk.suivre_managers(G)
    check("charge : Yoshiki a 23 VA (3 + 20), Moan 10 — le VA va chez Moan",
          f.salons["303"]["parent_id"] == "12" and fiche("203").get("manager") == MOAN,
          (f.salons["303"]["parent_id"], b["deplaces"]))

    # ══ 10. l'arrivé avait déjà sa catégorie : il relève les DEUX ═════════
    print("\n— 10. deux arrivés déjà rangés : les deux catégories du parti au même")

    f = monde(managers=(YOSHIKI, VECTOR))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    f.categorie("14", n2(VECTOR), 3)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "14", VECTOR)
    poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR)})
    with muet():
        tk.suivre_managers(G)                       # tout est rangé : la liste est retenue
    f.role(VECTOR, False)
    f.role(SPECTRUM, True)
    f.role(ZED, True)
    f.categorie("16", N1[SPECTRUM], 5)              # créées par un ticket avant le tour
    f.categorie("17", N1[ZED], 6)
    tk._CACHE.clear()
    with muet():
        b = tk.suivre_managers(G)
    ou = {f.salons["303"]["parent_id"], f.salons["304"]["parent_id"]}
    check("relève : les VA des deux catégories du parti vont chez le même arrivé",
          len(ou) == 1 and ou <= {"16", "17"}
          and fiche("203").get("manager") == fiche("204").get("manager") in (SPECTRUM, ZED),
          (ou, b["deplaces"], b["reportes"]))

    # ══ 11. un ticket crée la « 2 » pendant le tour du suivi ══════════════
    print("\n— 11. le suivi et un ticket au même instant : une seule « 2 »")
    f = monde(managers=(YOSHIKI,))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    t = f.remplir("11", YOSHIKI, 50, 3000)
    f.ticket("303", "203", "13", VECTOR)
    t["203"] = ("303", VECTOR)
    poser_fiches(t)

    def ticket_entre_temps():             # un autre fil : la « 2 » naît après la lecture du tour
        f.categorie("77", n2(YOSHIKI), 1)
        f.ticket("3998", "214", "77", YOSHIKI)
    f.une_fois = {"/roles": ticket_entre_temps, "/members/search": ticket_entre_temps}

    def une_seule(fn=ticket_entre_temps, vu=[]):
        if not vu:
            vu.append(1)
            fn()
    f.une_fois = {"/roles": une_seule, "/members/search": une_seule}
    with muet():
        b = tk.suivre_managers(G)
    check("au même instant : le tour retrouve la « 2 » créée entre-temps, il n'en crée pas une autre",
          len(f.cats(n2(YOSHIKI))) == 1 and not creations_cat(f) and not b["creees"],
          ([c["name"] for c in f.cats()], b["creees"]))
    check("au même instant : le VA du parti est rangé dans cette « 2 », chez Yoshiki",
          f.salons["303"]["parent_id"] == "77" and fiche("203").get("manager") == YOSHIKI
          and not f.refus, (f.salons["303"]["parent_id"], f.refus, b["rates"]))

    # ══ 12. un groupe se renomme d'un bloc, ou attend ═════════════════════
    print("\n— 12. budget du tour : le second parti (2 catégories) attend en entier")

    def deux_partis(f):
        f.categorie("11", N1[YOSHIKI], 1)
        f.categorie("13", N1[VECTOR], 2)
        f.categorie("14", n2(VECTOR), 3)
        f.categorie("15", N1[MOAN], 4)
        f.categorie("16", n2(MOAN), 5)
        f.ticket("301", "201", "11", YOSHIKI)
        f.ticket("303", "203", "13", VECTOR)
        f.ticket("304", "204", "14", VECTOR)
        f.ticket("305", "205", "15", MOAN)
        f.ticket("306", "206", "16", MOAN)
        poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR),
                      "205": ("305", MOAN), "206": ("306", MOAN)})

    f = monde(managers=(YOSHIKI, SPECTRUM, ZED), config={"managers_auto_max": 3})
    deux_partis(f)
    with muet():
        b = tk.suivre_managers(G)
    cles = [tk._cle_categorie(f.salons[c]["name"]) for c in ("13", "14", "15", "16")]
    check("budget : le premier parti est renommé en entier (2 renommages)",
          cles[0] == cles[1] and cles[0] in ("SPECTRUM", "ZED"), cles)
    check("budget : le second attend EN ENTIER (pas la première seule), et c'est dit",
          cles[2:] == ["MOAN", "MOAN"] and len(b["reportes"]) == 2, (cles, b["reportes"]))
    with muet():
        b = tk.suivre_managers(G)
    cles = [tk._cle_categorie(f.salons[c]["name"]) for c in ("13", "14", "15", "16")]
    check("budget : au tour suivant le second est renommé en entier, chez l'autre arrivé",
          cles[2] == cles[3] and {cles[0], cles[2]} == {"SPECTRUM", "ZED"}
          and sorted(c["name"] for c in f.cats() if tk._cle_categorie(c["name"]) != "YOSHIKI")
          == sorted([N1[SPECTRUM], n2(SPECTRUM), N1[ZED], n2(ZED)]), [c["name"] for c in f.cats()])
    check("budget : aucun VA déplacé, aucune catégorie créée",
          [f.salons[s]["parent_id"] for s in ("303", "304", "305", "306")] == ["13", "14", "15", "16"]
          and not creations_cat(f), creations_cat(f))

    print("\n— 12 bis. la première refusée : la « 2 » n'est pas renommée seule")
    f = monde(managers=(YOSHIKI, SPECTRUM))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    f.categorie("14", n2(VECTOR), 3)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "14", VECTOR)
    poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR)})
    f.refus_nom = {"13"}
    with muet():
        b = tk.suivre_managers(G)
    check("première refusée : ni l'une ni l'autre n'est renommée, aucun VA ne bouge",
          f.salons["13"]["name"] == N1[VECTOR] and f.salons["14"]["name"] == n2(VECTOR)
          and f.enfants("13") == ["303"] and f.enfants("14") == ["304"] and not creations_cat(f),
          ([c["name"] for c in f.cats()], b))
    f.refus_nom = set()
    tk._RATES_DITS.clear()
    with muet():
        b = tk.suivre_managers(G)
    check("première refusée : au tour suivant le groupe entier passe à Spectrum",
          f.salons["13"]["name"] == N1[SPECTRUM] and f.salons["14"]["name"] == n2(SPECTRUM)
          and fiche("203").get("manager") == SPECTRUM and fiche("204").get("manager") == SPECTRUM, b)

    # ══ 13. la « 2 » refusée après la première : la limite connue ═════════
    print("\n— 13. la « 2 » refusée après la première : personne n'est perdu")
    f = monde(managers=(YOSHIKI, VECTOR))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("13", N1[VECTOR], 2)
    f.categorie("14", n2(VECTOR), 3)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "14", VECTOR)
    poser_fiches({"201": ("301", YOSHIKI), "203": ("303", VECTOR), "204": ("304", VECTOR)})
    with muet():
        tk.suivre_managers(G)                # tout est rangé : la liste d'avant est retenue
    f.role(VECTOR, False)
    f.role(SPECTRUM, True)
    tk._CACHE.clear()
    f.refus_nom = {"14"}
    with muet():
        b = tk.suivre_managers(G)
    check("limite : la première passe à Spectrum, la « 2 » refusée garde son nom (dit)",
          f.salons["13"]["name"] == N1[SPECTRUM] and f.salons["14"]["name"] == n2(VECTOR)
          and any("refusé" in x for x in b["rates"]), ([c["name"] for c in f.cats()], b["rates"]))
    f.refus_nom = set()
    tk._RATES_DITS.clear()
    with muet():
        tk.suivre_managers(G)
        tk.suivre_managers(G)
    check("limite : le VA de la « 2 » finit chez un manager du jour (Spectrum), dans SA catégorie",
          fiche("204").get("manager") == SPECTRUM
          and tk._cle_categorie(f.salons[f.salons["304"]["parent_id"]]["name"]) == "SPECTRUM",
          (fiche("204"), f.salons["304"]["parent_id"]))
    check("limite : aucun salon supprimé ni hors catégorie, « VECTOR 2 » vide est gardée",
          "14" in f.salons and not f.enfants("14")
          and not [c for c in f.salons.values() if c["type"] == 0 and not c.get("parent_id")],
          [c["name"] for c in f.cats()])

    # ══ 14. un nom tout en chiffres n'est pas une suite ═══════════════════
    print("\n— 14. « Manager 1392… » (surnom illisible) parti : jamais renommée en « X 2 »")
    f = monde(managers=(YOSHIKI,))
    f.categorie("11", N1[YOSHIKI], 1)
    f.categorie("15", "🔵┤ Manager 1392000000000000001 ├🔵", 2)
    f.ticket("301", "201", "11", YOSHIKI)
    f.ticket("305", "205", "15", "1392000000000000001")
    f.ticket("306", "206", "15", "1392000000000000001")
    poser_fiches({"201": ("301", YOSHIKI), "205": ("305", "1392000000000000001"),
                  "206": ("306", "1392000000000000001")})
    with muet():
        tk.suivre_managers(G)
        tk.suivre_managers(G)
    check("nom en chiffres : ses VA rejoignent « Manager YOSHIKI », aucune « YOSHIKI 2 »",
          f.salons["305"]["parent_id"] == "11" and f.salons["306"]["parent_id"] == "11"
          and not f.cats(n2(YOSHIKI))
          and f.salons["15"]["name"] == "🔵┤ Manager 1392000000000000001 ├🔵",
          [c["name"] for c in f.cats()])

except Exception as _e:
    import traceback
    check("catégorie pleine : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(tk, _k, _v)
    for _c in (tk._CACHE, tk._DITS, tk._PAUSE, tk._VU_TOUR, tk._RATES_DITS):
        _c.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
