# -*- coding: utf-8 -*-
"""tests_managers_auto.py — les catégories « Manager X » suivent le rôle Manager.

Le 13/10/2026, Vector a perdu le rôle Manager sur YouLab TWITTER et Spectrum
l'a reçu ; la catégorie « 🔵┤ Manager VECTOR ├🔵 » a été renommée à la main.
Propriétaire : « oui fais-le automatique », « et après fais des tests et tout ».

Ce qui est vérifié (tickets_discord.suivre_managers / suivre_partout) :
  - un parti + un arrivé : la catégorie est RENOMMÉE, les VA restent dedans,
    leurs fiches et leurs droits passent à l'arrivé, et la synchro GetMySocial
    (liens_va.synchroniser) range leur lien chez SPECTRUM ;
  - un arrivé seul : sa catégorie est créée, vide ;
  - un parti seul : ses VA vont au tour de rôle chez les autres, la catégorie
    n'est supprimée que vide, tickets.json suit, le prochain ticket ne recrée
    pas « Manager VECTOR » ;
  - Discord muet, recherche incomplète, liste vide : rien n'est touché ;
  - la liste fixe de tickets_config.json fait foi ;
  - un second tour ne fait rien (idempotence) ;
  - deux managers au même nom : rien n'est touché ;
  - 429 : la suite est reportée, le serveur laissé en paix un moment ;
  - au plus N gestes par tour, le reste au tour suivant ;
  - un serveur sans catégorie de manager n'est pas touché ;
  - revue du 13/10 : deux catégories pour la même personne (surnom changé,
    renommage limité) se regroupent chez elle sans tour de rôle ; un arrivé
    qui avait déjà sa catégorie reçoit les VA du parti ; trois tickets de
    suite alternent vraiment ; un ticket n'efface plus une fiche écrite
    entre-temps ; une liste de membres de plus de 1000 est lue en entier ;
    la synchro GetMySocial lit « Manager Spectrum🥷 » comme SPECTRUM.

Tout se joue dans un dossier temporaire avec un faux Discord en mémoire :
aucun appel réseau, rien n'est écrit dans data/.
Lancement : python tests_managers_auto.py
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
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


G = "777"                              # serveur de test (le vrai périmètre n'est pas touché)
ROLE_MGR, ROLE_ESSAI = "900", "800"
YAZID, MOAN, VECTOR, SPECTRUM = "101", "102", "103", "104"
NOM = {YAZID: "🔵┤ Manager YAZID ├🔵", MOAN: "🔵┤ Manager MOAN ├🔵",
       VECTOR: "🔵┤ Manager VECTOR ├🔵", SPECTRUM: "🔵┤ Manager SPECTRUM ├🔵"}


class FauxDiscord:
    """Un serveur Discord en mémoire, assez fidèle pour les routes utilisées."""

    def __init__(self):
        self.roles = [{"id": ROLE_MGR, "name": "🛡️ Manager"},
                      {"id": ROLE_ESSAI, "name": "🧪 Essai"},
                      {"id": "700", "name": "✅ Vérifié"}]
        self.membres = {}
        self.salons = {}
        self.appels = []
        self.pannes = set()          # « roles », « channels », « search:m », « member:103 »
        self.limite = set()          # « nom » : 429 sur un renommage
        self.invisibles = set()      # membres que la recherche ne rend pas
        self.liste_ouverte = False   # True : /members répond (intent activé), par pages
        self.pendant_message = None  # appelé quand un ticket poste son accueil
        self.suivant = 5000

    # --- construction
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
        self.salons[cid] = {"id": cid, "type": 4, "name": nom, "position": pos,
                            "guild_id": G, "permission_overwrites": [
                                {"id": G, "type": 0, "allow": "0", "deny": str(tk.VOIR)},
                                {"id": ROLE_MGR, "type": 0, "allow": str(tk.MANAGER), "deny": "0"}]}

    def ticket(self, cid, va, parent, manager, pos=0):
        """Un salon de VA tel qu'ouvrir_ticket le crée."""
        self.salons[cid] = {"id": cid, "type": 0, "name": f"─│🔵┤-va-＠va{va}",
                            "parent_id": parent, "position": pos, "guild_id": G,
                            "permission_overwrites": [
                                {"id": G, "type": 0, "allow": "0", "deny": str(tk.VOIR)},
                                {"id": va, "type": 1, "allow": str(tk.MEMBRE), "deny": "0"},
                                {"id": ROLE_MGR, "type": 0, "allow": str(tk.MANAGER), "deny": "0"},
                                {"id": manager, "type": 1, "allow": str(tk.MANAGER), "deny": "0"}]}

    # --- lecture des appels
    def ecritures(self):
        return [(m, c, k) for m, c, k in self.appels if m != "GET"]

    def droits(self, cid):
        return {o["id"]: o for o in self.salons[cid]["permission_overwrites"]}

    def enfants(self, cid):
        return sorted(c["id"] for c in self.salons.values() if c.get("parent_id") == cid)

    # --- l'API
    def __call__(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw))
        base = chemin.split("?", 1)[0]
        corps = kw.get("json") or {}
        p = base.strip("/").split("/")
        if p[0] == "guilds":
            if base.endswith("/roles") and methode == "GET":
                return (500, {"message": "panne"}) if "roles" in self.pannes else (200, copy.deepcopy(self.roles))
            if base.endswith("/channels") and methode == "GET":
                if "channels" in self.pannes:
                    return 500, {"message": "panne"}
                return 200, copy.deepcopy(list(self.salons.values()))
            if base.endswith("/channels") and methode == "POST":
                self.suivant += 1
                cid = str(self.suivant)
                c = {"id": cid, "type": corps.get("type", 0), "name": corps.get("name"),
                     "position": 50, "guild_id": G,
                     "permission_overwrites": copy.deepcopy(corps.get("permission_overwrites") or [])}
                if corps.get("parent_id"):
                    c["parent_id"] = corps["parent_id"]
                self.salons[cid] = c
                return 201, {"id": cid}
            if base.endswith("/members") and methode == "GET":
                if not self.liste_ouverte:
                    return 403, {"message": "Missing Access"}
                prm = kw.get("params") or {}
                apres = int(prm.get("after") or 0)
                if apres and "members:page2" in self.pannes:
                    return 500, {"message": "panne"}
                # Discord : triés par identifiant, une page à partir de « after »
                tous = sorted((m for m in self.membres.values() if int(m["user"]["id"]) > apres),
                              key=lambda m: int(m["user"]["id"]))
                return 200, copy.deepcopy(tous[:int(prm.get("limit") or 1)])
            if base.endswith("/members/search"):
                q = str((kw.get("params") or {}).get("query") or "")
                lim = int((kw.get("params") or {}).get("limit") or 100)
                if f"search:{q}" in self.pannes:
                    return 500, {"message": "panne"}
                vus = sorted((m for u, m in self.membres.items() if u not in self.invisibles
                              and (m["user"]["username"].startswith(q)
                                   or str(m.get("nick") or "").lower().startswith(q))),
                             key=lambda m: m["user"]["username"])
                return 200, copy.deepcopy(vus[:lim])
            if "/members/" in base and "/roles/" in base and methode == "PUT":
                return 204, {}
            if len(p) == 4 and p[2] == "members" and methode == "GET":
                uid = p[3]
                if f"member:{uid}" in self.pannes:
                    return 500, {"message": "panne"}
                m = self.membres.get(uid)
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
                    if "name" in corps and "nom" in self.limite:
                        return 429, {"message": "limite Discord"}
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
                oid = p[3]
                if not c:
                    return 404, {}
                c["permission_overwrites"] = [o for o in c["permission_overwrites"] if o["id"] != oid]
                if methode == "PUT":
                    c["permission_overwrites"].append({"id": oid, "type": corps.get("type", 1),
                                                       "allow": corps.get("allow", "0"),
                                                       "deny": corps.get("deny", "0")})
                return 204, {}
            if len(p) == 3 and p[2] == "messages" and methode == "POST":
                if self.pendant_message:
                    self.pendant_message()
                self.suivant += 1
                return 200, {"id": str(self.suivant)}
            if len(p) == 4 and p[2] == "pins":
                return 204, {}
        return 404, {"message": f"route inconnue {methode} {chemin}"}


# ─── un monde neuf par scénario ──────────────────────────────────────────
TMP = pathlib.Path(tempfile.mkdtemp(prefix="managers_auto_"))
_SAUVE = {k: getattr(tk, k) for k in ("_api", "ETAT_FICHIER", "CONFIG_FICHIER",
                                       "JOURNAL_FICHIER", "PAUSE_RECHERCHE_S",
                                       "LIMITE_RECHERCHE")}
_SAUVE_LV = {k: getattr(lv, k) for k in ("ETAT_FICHIER", "groupes", "groupe_manager", "ranger")}
_SAUVE_LV_SERVEURS = set(lv.SERVEURS)
_n = [0]


def monde(config=None, tickets=None, tours=0):
    """Remet tickets_discord à zéro sur un dossier neuf et un faux Discord."""
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
    cfg = {"serveurs": [G]}
    cfg.update(config or {})
    tk.CONFIG_FICHIER.write_text(json.dumps(cfg), encoding="utf-8")
    fiches = {f"{G}:{va}": {"salon": salon, "manager": mgr, "ouvert": 1, "essai": True,
                            "accueil": ""}
              for va, (salon, mgr) in (tickets or {}).items()}
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": fiches, "tours": {G: tours}}),
                               encoding="utf-8")
    f = FauxDiscord()
    f.membre(YAZID, "yazid_ofm", "Yazid")
    f.membre(MOAN, "moan_ofm", "🎯│𝑴𝑶𝑨𝑵")
    f.membre(VECTOR, "vector.ofm", "Vector")
    f.membre(SPECTRUM, "gh_os_t_1", "Spectrum🥷")
    for i in range(201, 216):
        f.membre(str(i), f"va{i}")
    tk._api = f
    return f


def fiche(va):
    return (json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8")).get("tickets") or {}).get(f"{G}:{va}") or {}


def tours():
    return int((json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8")).get("tours") or {}).get(G) or 0)


def calme():
    """Rien imprimé : un tour sans changement ne doit pas remplir le journal."""
    return contextlib.redirect_stdout(io.StringIO())


def base_twitter(f, avec_vector=True):
    """YAZID (11), MOAN (12), et VECTOR (13) si demandé, avec leurs VA."""
    f.categorie("11", NOM[YAZID], 1)
    f.categorie("12", NOM[MOAN], 2)
    f.ticket("301", "201", "11", YAZID, 1)
    f.ticket("302", "202", "12", MOAN, 1)
    if avec_vector:
        f.categorie("13", NOM[VECTOR], 3)
        f.ticket("303", "203", "13", VECTOR, 1)
        f.ticket("304", "204", "13", VECTOR, 2)


TICKETS_BASE = {"201": ("301", YAZID), "202": ("302", MOAN),
                "203": ("303", VECTOR), "204": ("304", VECTOR)}

try:
    # ══ 1. Vector part, Spectrum arrive : on renomme ══════════════════════
    print("\n— 1. Vector perd le rôle, Spectrum le reçoit")
    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    b = tk.suivre_managers(G)
    check("swap : « Manager VECTOR » renommée en « Manager SPECTRUM »",
          f.salons["13"]["name"] == NOM[SPECTRUM] and b["renommees"], b)
    check("swap : un seul renommage, aucune catégorie créée, aucune supprimée",
          len([1 for m, c, k in f.ecritures() if m == "PATCH" and "name" in (k.get("json") or {})]) == 1
          and not [1 for m, c, k in f.ecritures() if m == "POST" and c.endswith("/channels")]
          and not [1 for m, c, k in f.ecritures() if m == "DELETE" and c.count("/") == 2],
          f.ecritures())
    check("swap : les VA restent dans la catégorie (aucun déplacement)",
          f.enfants("13") == ["303", "304"]
          and not [1 for m, c, k in f.ecritures() if "parent_id" in (k.get("json") or {})])
    check("swap : tickets.json — les VA de Vector passent à Spectrum",
          fiche("203").get("manager") == SPECTRUM and fiche("204").get("manager") == SPECTRUM
          and fiche("203").get("manager_avant") == VECTOR, (fiche("203"), fiche("204")))
    d303 = f.droits("303")
    check("swap : droits — Spectrum nommé dans le salon, Vector retiré, VA et rôle intacts",
          d303.get(SPECTRUM, {}).get("allow") == str(tk.MANAGER) and VECTOR not in d303
          and d303.get("203", {}).get("allow") == str(tk.MEMBRE)
          and d303.get(ROLE_MGR, {}).get("allow") == str(tk.MANAGER), d303)
    check("swap : les VA de Yazid et Moan ne bougent pas",
          fiche("201").get("manager") == YAZID and fiche("202").get("manager") == MOAN
          and "manager_avant" not in fiche("201"))
    check("swap : le tour de rôle n'est pas touché", tours() == 0)
    j = json.loads(tk.JOURNAL_FICHIER.read_text(encoding="utf-8"))["journal"]
    check("swap : chaque geste est dans le journal (data/managers_auto.json)",
          [x["quoi"] for x in j] == ["renommees", "realignes", "realignes"], j)
    f.appels.clear()
    check("swap : le cache du tour de rôle est à jour (Vector n'y est plus)",
          [m["user"]["id"] for m in tk.managers(G)] == [YAZID, MOAN, SPECTRUM]
          and not f.appels)

    # la synchro GetMySocial lit la catégorie : le lien suit chez SPECTRUM
    lv.ETAT_FICHIER = TMP / "liens_va.json"
    lv.ETAT_FICHIER.write_text(json.dumps({"liens": {
        f"{G}:203": {"pseudo": "va203", "shortcode": "emycute", "link_id": "L203",
                     "groupe": "VECTOR", "manager": "VECTOR"},
        f"{G}:201": {"pseudo": "va201", "shortcode": "emybaby", "link_id": "L201",
                     "groupe": "YAZID", "manager": "YAZID"}}}), encoding="utf-8")
    ranges = []
    lv.groupes = lambda equipe, essais=3: {"vector": "g1", "yazid": "g2", "moan": "g3",
                                           "spectrum": "g4"}
    lv.groupe_manager = lambda equipe, nom: "g?"
    lv.ranger = lambda equipe, lid, nom: (ranges.append((lid, nom)) or nom)
    lv.SERVEURS.add(G)
    bl = lv.synchroniser(G)
    check("swap : la synchro GetMySocial range le lien du VA chez SPECTRUM",
          ranges == [("L203", "SPECTRUM")], (ranges, bl))

    f.appels.clear()
    with calme() as _:
        b2 = tk.suivre_managers(G)
    check("swap : un second tour ne fait rien (idempotent)",
          not f.ecritures() and not any(b2[k] for k in ("renommees", "creees", "deplaces",
                                                         "supprimees", "realignes")), f.ecritures())

    # ══ 2. Spectrum arrive, personne ne part : sa catégorie, vide ═════════
    print("\n— 2. Spectrum reçoit le rôle, Vector le garde")
    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    for u in (YAZID, MOAN, VECTOR, SPECTRUM):
        f.role(u, True)
    b = tk.suivre_managers(G)
    neuves = [c for c in f.salons.values() if c["type"] == 4 and c["name"] == NOM[SPECTRUM]]
    check("arrivé seul : « Manager SPECTRUM » créée", len(neuves) == 1 and b["creees"], b)
    check("arrivé seul : elle est vide",
          neuves and not f.enfants(neuves[0]["id"]))
    dn = {o["id"]: o for o in (neuves[0]["permission_overwrites"] if neuves else [])}
    check("arrivé seul : mêmes droits qu'une catégorie de ticket (privée, rôle Manager)",
          dn.get(G, {}).get("deny") == str(tk.VOIR)
          and dn.get(ROLE_MGR, {}).get("allow") == str(tk.MANAGER), dn)
    check("arrivé seul : rien d'autre (pas de renommage, déplacement ni suppression)",
          [m for m, c, k in f.ecritures()] == ["POST"], f.ecritures())
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("arrivé seul : second tour, rien", not f.ecritures(), f.ecritures())

    # ══ 3. Vector part sans remplaçant : ses VA au tour de rôle ═══════════
    print("\n— 3. Vector perd le rôle, personne ne le remplace")
    t3 = dict(TICKETS_BASE)
    t3["205"] = ("305", VECTOR)
    f = monde(tickets=t3)
    base_twitter(f)
    f.ticket("305", "205", "13", VECTOR, 3)
    for u in (YAZID, MOAN):
        f.role(u, True)
    b = tk.suivre_managers(G)
    check("parti seul : 3 VA déplacés au tour de rôle (Yazid, Moan, Yazid)",
          [f.salons[c].get("parent_id") for c in ("303", "304", "305")] == ["11", "12", "11"],
          b)
    check("parti seul : tickets.json suit",
          [fiche(v).get("manager") for v in ("203", "204", "205")] == [YAZID, MOAN, YAZID])
    check("parti seul : droits — le nouveau manager nommé, Vector retiré",
          all(VECTOR not in f.droits(c) for c in ("303", "304", "305"))
          and f.droits("304").get(MOAN, {}).get("allow") == str(tk.MANAGER)
          and f.droits("303").get(YAZID, {}).get("allow") == str(tk.MANAGER))
    check("parti seul : déplacés sans synchroniser les droits sur la catégorie",
          all("lock_permissions" not in (k.get("json") or {}) for m, c, k in f.ecritures()))
    check("parti seul : la catégorie vide est supprimée", "13" not in f.salons and b["supprimees"], b)
    check("parti seul : aucun salon supprimé, seulement la catégorie",
          [c for m, c, k in f.ecritures() if m == "DELETE" and c.count("/") == 2] == ["/channels/13"])
    check("parti seul : le tour de rôle a avancé de 3 (prochain : Moan)", tours() == 1, tours())
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("parti seul : second tour, rien", not f.ecritures(), f.ecritures())
    # un ticket ouvert après : chez le bon manager, sans recréer « Manager VECTOR »
    f.appels.clear()
    with calme():
        sal = tk.ouvrir_ticket("209", {"id": G})
    cats_post = [k["json"]["name"] for m, c, k in f.ecritures()
                 if m == "POST" and c.endswith("/channels") and k["json"].get("type") == 4]
    check("ticket suivant : chez Moan (le tour de rôle continue), dans sa catégorie",
          sal and f.salons[sal].get("parent_id") == "12" and fiche("209").get("manager") == MOAN,
          (sal, fiche("209")))
    check("ticket suivant : aucune catégorie recréée (pas de « Manager VECTOR »)",
          not cats_post, cats_post)

    # 3b. un salon inconnu de tickets.json dans la catégorie : elle reste
    print("\n— 3b. un salon hors tickets dans la catégorie du parti")
    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    f.salons["399"] = {"id": "399", "type": 0, "name": "notes-vector", "parent_id": "13",
                       "position": 9, "guild_id": G, "permission_overwrites": []}
    for u in (YAZID, MOAN):
        f.role(u, True)
    b = tk.suivre_managers(G)
    check("salon hors tickets : les VA partent quand même",
          f.salons["303"]["parent_id"] in ("11", "12") and f.salons["304"]["parent_id"] in ("11", "12"))
    check("salon hors tickets : il n'est pas touché, la catégorie est gardée (et dite)",
          f.salons["399"]["parent_id"] == "13" and "13" in f.salons
          and not [1 for m, c, k in f.ecritures() if m == "DELETE" and c == "/channels/13"]
          and b["gardees"] == [NOM[VECTOR]], b)
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        f.appels.clear()
        b2 = tk.suivre_managers(G)
    check("salon hors tickets : second tour sans geste ni redite au journal",
          not f.ecritures() and "gardée" not in sortie.getvalue(), sortie.getvalue())

    # ══ 4. au plus N gestes par tour ══════════════════════════════════════
    print("\n— 4. sept VA chez le parti, cinq gestes par tour")
    t4 = {"201": ("301", YAZID), "202": ("302", MOAN)}
    f = monde(tickets=t4)
    base_twitter(f, avec_vector=False)
    f.categorie("13", NOM[VECTOR], 3)
    for i in range(7):
        va, sal = str(203 + i), str(303 + i)
        f.ticket(sal, va, "13", VECTOR, i)
        t4[va] = (sal, VECTOR)
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{G}:{va}": {"salon": s, "manager": m, "accueil": ""} for va, (s, m) in t4.items()},
        "tours": {G: 0}}), encoding="utf-8")
    for u in (YAZID, MOAN):
        f.role(u, True)
    b = tk.suivre_managers(G)
    check("budget : 5 déplacements au premier tour, 2 reportés, catégorie gardée",
          len(b["deplaces"]) == 5 and len(b["reportes"]) == 2 and "13" in f.salons
          and len(f.enfants("13")) == 2, b)
    b = tk.suivre_managers(G)
    check("budget : le tour suivant finit le travail et supprime la catégorie vide",
          len(b["deplaces"]) == 2 and b["supprimees"] and "13" not in f.salons, b)
    check("budget : répartition au tour de rôle (4 chez Yazid, 3 chez Moan) et fiches à jour",
          [len(f.enfants("11")), len(f.enfants("12"))] == [1 + 4, 1 + 3]
          and all(fiche(str(203 + i)).get("manager") in (YAZID, MOAN) for i in range(7)),
          (f.enfants("11"), f.enfants("12")))
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("budget : troisième tour, rien", not f.ecritures(), f.ecritures())

    # ══ 5. dans le doute, rien ════════════════════════════════════════════
    print("\n— 5. Discord muet ou liste douteuse : rien n'est touché")

    def scenario_depart():
        f = monde(tickets=TICKETS_BASE)
        base_twitter(f)
        for u in (YAZID, MOAN):
            f.role(u, True)
        return f

    f = scenario_depart()
    f.pannes.add("roles")
    with calme():
        b = tk.suivre_managers(G)
    check("rôles illisibles : aucune écriture", not f.ecritures() and b["ignore"], b)
    f = scenario_depart()
    f.pannes.add("search:m")
    with calme():
        b = tk.suivre_managers(G)
    check("une recherche de membres refusée : aucune écriture (liste incomplète)",
          not f.ecritures() and "indéterminables" in b["ignore"], b)
    f = scenario_depart()
    f.pannes.add("channels")
    with calme():
        b = tk.suivre_managers(G)
    check("salons illisibles : aucune écriture", not f.ecritures() and b["ignore"], b)
    f = scenario_depart()
    f.role(YAZID, False)
    f.role(MOAN, False)
    with calme():
        b = tk.suivre_managers(G)
    check("plus personne ne porte le rôle : aucune écriture",
          not f.ecritures() and "aucun manager" in b["ignore"], b)
    f = scenario_depart()
    f.pannes.add(f"member:{VECTOR}")
    with calme():
        b = tk.suivre_managers(G)
    check("le manager « parti » illisible par son identifiant : aucune écriture",
          not f.ecritures() and b["ignore"], b)
    # la recherche rate un manager qui porte pourtant le rôle : ses fiches le
    # nomment, on le vérifie par son identifiant avant de le croire parti
    f = monde(tickets={"201": ("301", YAZID), "202": ("302", MOAN)})
    base_twitter(f, avec_vector=False)
    for u in (YAZID, MOAN):
        f.role(u, True)
    f.invisibles.add(YAZID)
    with calme():
        b = tk.suivre_managers(G)
    check("manager manqué par la recherche mais nommé par ses fiches : gardé, rien touché",
          not f.ecritures() and "11" in f.salons
          and YAZID in [m["user"]["id"] for m in tk._CACHE[G]["v"]], (f.ecritures(), b))
    # la recherche stricte reprend une lettre qui remplit la page
    f = monde()
    f.membres = {}
    f.membre(VECTOR, "vector.ofm", "Vector", manager=True)
    tk.LIMITE_RECHERCHE = 2
    for i, u in enumerate(("va1", "va2", "va3")):
        f.membre(f"6{i}", u)
    trouves = tk._par_la_recherche(G, ROLE_MGR, strict=True)
    approx = tk._par_la_recherche(G, ROLE_MGR)
    check("recherche stricte : une lettre pleine (« v ») est reprise sur deux lettres",
          [m["user"]["id"] for m in (trouves or [])] == [VECTOR]
          and ("GET", f"/guilds/{G}/members/search", {"params": {"query": "ve", "limit": 2}}) in f.appels,
          trouves)
    check("… là où l'ancienne recherche l'aurait manqué", approx == [], approx)
    tk.LIMITE_RECHERCHE = 100

    # ══ 6. la liste fixe fait foi ═════════════════════════════════════════
    print("\n— 6. liste fixe dans tickets_config.json")
    f = monde(config={"managers": {G: [YAZID, MOAN]}}, tickets=TICKETS_BASE)
    base_twitter(f)
    for u in (YAZID, MOAN, VECTOR, SPECTRUM):
        f.role(u, True)                # le rôle dit autre chose : la liste l'emporte
    b = tk.suivre_managers(G)
    check("liste fixe : Vector n'y est pas -> ses VA répartis, sa catégorie supprimée",
          "13" not in f.salons and len(b["deplaces"]) == 2, b)
    check("liste fixe : Spectrum (rôle, mais pas dans la liste) n'a pas de catégorie",
          not [c for c in f.salons.values() if c["name"] == NOM[SPECTRUM]])
    check("liste fixe : aucune recherche de membres",
          not [1 for m, c, k in f.appels if "/members/search" in c])
    f = monde(config={"managers": {G: [YAZID, "999"]}}, tickets=TICKETS_BASE)
    base_twitter(f)
    with calme():
        b = tk.suivre_managers(G)
    check("liste fixe avec un membre introuvable : rien touché", not f.ecritures() and b["ignore"], b)

    # ══ 7. deux managers au même nom ══════════════════════════════════════
    print("\n— 7. deux managers au même nom court")
    f = scenario_depart()
    f.role(SPECTRUM, True)
    f.membres[SPECTRUM]["nick"] = "Yazid 2"          # -> YAZID, comme Yazid
    with calme():
        b = tk.suivre_managers(G)
    check("homonymes : aucune écriture, et la raison est donnée",
          not f.ecritures() and "même nom" in b["ignore"], b)

    # ══ 8. Discord limite le débit ════════════════════════════════════════
    print("\n— 8. 429 sur le renommage")
    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    f.limite.add("nom")
    b = tk.suivre_managers(G)
    check("429 : le renommage est reporté, rien d'autre n'est tenté",
          f.salons["13"]["name"] == NOM[VECTOR]
          and [m for m, c, k in f.ecritures()] == ["PATCH"]
          and fiche("203").get("manager") == VECTOR and any("limite" in r for r in b["rates"]), b)
    check("429 : le serveur est laissé en paix", tk._PAUSE.get(G, 0) > 0)
    f.appels.clear()
    tk.suivre_partout()
    check("429 : pendant la pause, le tour suivant n'appelle même pas Discord", not f.appels, f.appels)
    f.limite.clear()
    tk._PAUSE.clear()
    tk._VU_TOUR.clear()
    r = tk.suivre_partout()
    check("429 : la pause passée, le renommage se fait",
          f.salons["13"]["name"] == NOM[SPECTRUM] and r.get(G, {}).get("renommees"), r)
    f.appels.clear()
    tk.suivre_partout()
    check("tour suivant trop tôt (moins de 9 min) : rien", not f.appels)

    # ══ 9. hors sujet ═════════════════════════════════════════════════════
    print("\n— 9. serveurs qui ne rangent pas leurs VA par manager")
    f = monde()
    f.categorie("21", "📚 Formations", 1)
    f.categorie("22", "💬 Général", 2)
    f.role(YAZID, True)
    with calme():
        b = tk.suivre_managers(G)
    check("sans catégorie « Manager X » : une seule lecture, aucune recherche, rien écrit",
          len(f.appels) == 1 and not f.ecritures() and b["ignore"], f.appels)
    f = monde(config={"serveurs": ["888"]}, tickets=TICKETS_BASE)
    base_twitter(f)
    b = tk.suivre_managers(G)
    check("hors périmètre des tickets : aucun appel", not f.appels and b["ignore"], b)
    f = monde(config={"managers_auto": False}, tickets=TICKETS_BASE)
    base_twitter(f)
    with calme():
        b = tk.suivre_managers(G)
    check("interrupteur managers_auto: false : aucun appel", not f.appels and b["ignore"], b)

    # ══ 10. un manager change de surnom ═══════════════════════════════════
    print("\n— 10. Moan change de surnom pendant que Vector part et Spectrum arrive")
    f = monde(tickets=TICKETS_BASE)
    f.categorie("13", NOM[VECTOR], 1)            # VECTOR en premier : l'ordre seul tromperait
    f.categorie("11", NOM[YAZID], 2)
    f.categorie("12", NOM[MOAN], 3)
    f.ticket("301", "201", "11", YAZID)
    f.ticket("302", "202", "12", MOAN)
    f.ticket("303", "203", "13", VECTOR)
    f.ticket("304", "204", "13", VECTOR)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    f.membres[MOAN]["nick"] = "Moanito"
    b = tk.suivre_managers(G)
    check("surnom changé : sa catégorie le suit (MOAN -> MOANITO), par la personne",
          f.salons["12"]["name"] == "🔵┤ Manager MOANITO ├🔵", f.salons["12"]["name"])
    check("… et VECTOR passe à SPECTRUM",
          f.salons["13"]["name"] == NOM[SPECTRUM], f.salons["13"]["name"])

    # ══ 10b. une catégorie « Manager » qui n'est pas un ticket ════════════
    print("\n— 10b. catégories d'équipe qui disent « Manager »")
    f = monde(tickets=TICKETS_BASE)
    f.categorie("10", "🛡️┤ Manager STAFF ├🛡️", 0)    # en tête : l'ordre seul la prendrait
    f.salons["398"] = {"id": "398", "type": 0, "name": "regles-staff", "parent_id": "10",
                       "position": 0, "guild_id": G, "permission_overwrites": []}
    f.categorie("14", "📋┤ Manager INFOS ├📋", 9)      # vide
    base_twitter(f)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    with calme():
        b = tk.suivre_managers(G)
    check("catégorie d'équipe : ni renommée ni supprimée, même vide",
          f.salons["10"]["name"] == "🛡️┤ Manager STAFF ├🛡️" and "14" in f.salons
          and f.salons["14"]["name"] == "📋┤ Manager INFOS ├📋", b)
    check("… et c'est bien VECTOR qui passe à SPECTRUM",
          f.salons["13"]["name"] == NOM[SPECTRUM], b)

    # ══ 11. l'état de YouLab TWITTER au 13/10 ═════════════════════════════
    print("\n— 11. état du 13/10 : « Manager SPECTRUM » déjà renommée à la main")
    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    f.salons["13"]["name"] = NOM[SPECTRUM]
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    b = tk.suivre_managers(G)
    check("13/10 : ni renommage, ni création, ni déplacement, ni suppression",
          not any(b[k] for k in ("renommees", "creees", "deplaces", "supprimees")), b)
    check("13/10 : les fiches des VA de la catégorie SPECTRUM passent de Vector à Spectrum",
          len(b["realignes"]) == 2 and fiche("203").get("manager") == SPECTRUM
          and VECTOR not in f.droits("304") and SPECTRUM in f.droits("304"), b)
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("13/10 : second tour, rien", not f.ecritures(), f.ecritures())

    # ══ 12. une catégorie renommée à la main n'est pas recréée ════════════
    print("\n— 12. catégorie retapée à la main")
    f = monde()
    f.categorie("13", "🔵┤ Manager Spectrum ├🔵", 3)
    cid = tk.categorie_du_manager(G, f.membres[SPECTRUM])
    check("categorie_du_manager retrouve « Manager Spectrum » (casse différente)",
          cid == "13" and not f.ecritures(), (cid, f.ecritures()))
    check("le nom fabriqué est celui d'avant",
          tk.nom_categorie(f.membres[SPECTRUM]) == NOM[SPECTRUM])

    # ══ 14. deux catégories pour la même personne (revue du 13/10) ════════
    print("\n— 14. Yazid devient « Zed », renommage limité, un ticket crée « Manager ZED »")
    f = monde(tickets={"201": ("301", YAZID), "206": ("306", YAZID), "207": ("307", YAZID),
                       "202": ("302", MOAN), "208": ("308", SPECTRUM)})
    f.categorie("11", NOM[YAZID], 1)
    f.categorie("12", NOM[MOAN], 2)
    f.categorie("14", NOM[SPECTRUM], 3)
    f.ticket("301", "201", "11", YAZID, 1)
    f.ticket("306", "206", "11", YAZID, 2)
    f.ticket("307", "207", "11", YAZID, 3)
    f.ticket("302", "202", "12", MOAN, 1)
    f.ticket("308", "208", "14", SPECTRUM, 1)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    with calme():
        tk.suivre_managers(G)                       # tour calme : la liste est retenue
        f.membres[YAZID]["nick"] = "Zed"
        f.limite.add("nom")
        tk.suivre_managers(G)                       # 429 sur YAZID -> ZED
        sal = tk.ouvrir_ticket("209", {"id": G})    # pendant la pause : tour de Zed
    zed = [c for c in f.salons.values() if c["type"] == 4 and c["name"] == "🔵┤ Manager ZED ├🔵"]
    check("même personne : le ticket ouvert pendant la pause a créé « Manager ZED »",
          len(zed) == 1 and f.salons[sal]["parent_id"] == zed[0]["id"], (zed, sal))
    f.limite.clear()
    tk._PAUSE.clear()
    tours_avant = tours()
    b = tk.suivre_managers(G)
    check("même personne : les 3 VA de Yazid rejoignent « Manager ZED », aucun chez Moan ni Spectrum",
          zed and all(f.salons[c]["parent_id"] == zed[0]["id"] for c in ("301", "306", "307"))
          and f.enfants("12") == ["302"] and f.enfants("14") == ["308"], b)
    check("même personne : fiches et droits de Yazid intacts",
          all(fiche(v).get("manager") == YAZID and "manager_avant" not in fiche(v)
              for v in ("201", "206", "207"))
          and all(f.droits(c).get(YAZID, {}).get("allow") == str(tk.MANAGER)
                  for c in ("301", "306", "307")))
    check("même personne : le tour de rôle n'a pas servi", tours() == tours_avant, (tours(), tours_avant))
    check("même personne : l'ancienne « Manager YAZID », vide, est supprimée",
          "11" not in f.salons and b["supprimees"], b)
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("même personne : second tour, rien", not f.ecritures(), f.ecritures())

    # ══ 15. l'arrivé avait déjà sa catégorie (ticket avant le tour) ═══════
    print("\n— 15. Vector -> Spectrum, mais un ticket a créé « Manager SPECTRUM » avant le tour")

    def connus():
        d = json.loads(tk.JOURNAL_FICHIER.read_text(encoding="utf-8"))
        return (d.get("connus") or {}).get(G)

    f = monde(tickets=TICKETS_BASE)
    base_twitter(f)
    for u in (YAZID, MOAN, VECTOR):
        f.role(u, True)
    with calme():
        tk.suivre_managers(G)                       # avant le changement : tout est rangé
    check("liste retenue après un tour où tout est rangé (data/managers_auto.json)",
          connus() == [YAZID, MOAN, VECTOR], connus())
    f.role(VECTOR, False)
    f.role(SPECTRUM, True)
    tk._CACHE.clear()                               # redémarrage : cache vide
    e = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))
    e["tours"][G] = 2                               # c'est le tour de Spectrum
    tk.ETAT_FICHIER.write_text(json.dumps(e), encoding="utf-8")
    with calme():
        sal = tk.ouvrir_ticket("209", {"id": G})
    sp = [c for c in f.salons.values() if c["type"] == 4 and c["name"] == NOM[SPECTRUM]]
    check("arrivé déjà rangé : le ticket a créé « Manager SPECTRUM »",
          len(sp) == 1 and f.salons[sal]["parent_id"] == sp[0]["id"], sp)
    tours_avant = tours()
    b = tk.suivre_managers(G)
    check("arrivé déjà rangé : les VA de Vector passent chez SPECTRUM (pas au tour de rôle)",
          sp and [f.salons[c]["parent_id"] for c in ("303", "304")] == [sp[0]["id"]] * 2
          and [fiche(v).get("manager") for v in ("203", "204")] == [SPECTRUM, SPECTRUM], b)
    check("arrivé déjà rangé : droits — Spectrum nommé, Vector retiré",
          all(SPECTRUM in f.droits(c) and VECTOR not in f.droits(c) for c in ("303", "304")))
    check("arrivé déjà rangé : le tour de rôle n'a pas servi, « Manager VECTOR » vide supprimée",
          tours() == tours_avant and "13" not in f.salons
          and f.enfants("11") == ["301"] and f.enfants("12") == ["302"], (tours(), b))
    check("arrivé déjà rangé : la liste retenue devient Yazid, Moan, Spectrum",
          connus() == [YAZID, MOAN, SPECTRUM], connus())
    f.appels.clear()
    with calme():
        tk.suivre_managers(G)
    check("arrivé déjà rangé : second tour, rien", not f.ecritures(), f.ecritures())

    # 15b. la relève tient d'un tour à l'autre quand le budget coupe
    f = monde(tickets={"201": ("301", YAZID), "202": ("302", MOAN)})
    base_twitter(f, avec_vector=False)
    f.categorie("13", NOM[VECTOR], 3)
    t15 = {"201": ("301", YAZID), "202": ("302", MOAN)}
    for i in range(7):
        va, s = str(203 + i), str(303 + i)
        f.ticket(s, va, "13", VECTOR, i)
        t15[va] = (s, VECTOR)
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{G}:{va}": {"salon": s, "manager": m, "accueil": ""} for va, (s, m) in t15.items()},
        "tours": {G: 0}}), encoding="utf-8")
    for u in (YAZID, MOAN, VECTOR):
        f.role(u, True)
    with calme():
        tk.suivre_managers(G)
    f.role(VECTOR, False)
    f.role(SPECTRUM, True)
    with calme():
        tk.categorie_du_manager(G, f.membres[SPECTRUM])     # créée hors du suivi
    sp = [c["id"] for c in f.salons.values() if c["type"] == 4 and c["name"] == NOM[SPECTRUM]]
    with calme():
        b1 = tk.suivre_managers(G)
        b2 = tk.suivre_managers(G)
    check("relève sur deux tours (5 + 2 gestes) : les 7 VA de Vector chez SPECTRUM",
          sp and len(b1["deplaces"]) == 5 and len(b2["deplaces"]) == 2
          and f.enfants(sp[0]) == sorted(str(303 + i) for i in range(7))
          and "13" not in f.salons, (b1, b2))
    check("relève sur deux tours : la liste n'est retenue qu'une fois tout rangé",
          connus() == [YAZID, MOAN, SPECTRUM], connus())

    # ══ 16. tour de rôle des nouveaux tickets ═════════════════════════════
    print("\n— 16. trois tickets de suite")
    f = monde(tickets={"201": ("301", YAZID), "202": ("302", MOAN)})
    base_twitter(f, avec_vector=False)
    for u in (YAZID, MOAN):
        f.role(u, True)
    with calme():
        for va in ("210", "211", "212"):
            tk.ouvrir_ticket(va, {"id": G})
    check("trois tickets de suite : Yazid, Moan, Yazid (le compteur avance vraiment)",
          [fiche(v).get("manager") for v in ("210", "211", "212")] == [YAZID, MOAN, YAZID]
          and tours() == 1, ([fiche(v).get("manager") for v in ("210", "211", "212")], tours()))

    def suivi_ecrit_pendant():
        # le suivi des managers réécrit une fiche pendant que le ticket s'ouvre
        e = tk._etat()
        e["tickets"][f"{G}:201"]["manager"] = MOAN
        tk._ecrire_etat(e)
    f.pendant_message = suivi_ecrit_pendant
    with calme():
        tk.ouvrir_ticket("213", {"id": G})
    f.pendant_message = None
    check("un ticket qui s'ouvre n'efface plus une fiche écrite entre-temps",
          fiche("201").get("manager") == MOAN and fiche("213").get("salon"),
          (fiche("201"), fiche("213")))

    # ══ 17. liste des membres ouverte (intent activé), par pages ══════════
    print("\n— 17. /members répond : plus de 1000 membres")

    def plus_de_mille():
        f = monde(tickets={"201": ("301", YAZID), "202": ("302", MOAN)})
        base_twitter(f, avec_vector=False)
        f.categorie("14", NOM[SPECTRUM], 3)          # vide, créée au tour d'avant
        for u in (YAZID, MOAN):
            f.role(u, True)
        for i in range(1000):
            f.membre(str(10 ** 6 + i), f"m{i}")
        f.membre("9" * 18, "gh_os_t_1", "Spectrum🥷", manager=True)    # page 2
        f.membres.pop(SPECTRUM)
        f.liste_ouverte = True
        return f

    f = plus_de_mille()
    with calme():
        b = tk.suivre_managers(G)
    pages = [k.get("params") for m, c, k in f.appels if c.endswith("/members")]
    check("1001 membres : la page 2 est lue, Spectrum gardé, sa catégorie intacte",
          "14" in f.salons and not b["supprimees"] and len(pages) == 2
          and pages[1].get("after") and "9" * 18 in [m["user"]["id"] for m in tk._CACHE[G]["v"]],
          (pages, b))
    f = plus_de_mille()
    f.pannes.add("members:page2")
    with calme():
        b = tk.suivre_managers(G)
    check("page 2 refusée : la recherche prend le relais, rien supprimé",
          "14" in f.salons and not f.ecritures()
          and [1 for m, c, k in f.appels if c.endswith("/members/search")], b)

    # ══ 18. GetMySocial lit la catégorie comme le suivi ═══════════════════
    print("\n— 18. catégorie retapée « Manager Spectrum🥷 » : un seul groupe SPECTRUM")
    f = monde(tickets={"201": ("301", YAZID), "202": ("302", MOAN), "203": ("303", VECTOR)})
    f.categorie("11", NOM[YAZID], 1)
    f.categorie("12", NOM[MOAN], 2)
    f.categorie("13", "🔵┤ Manager Spectrum🥷 ├🔵", 3)
    f.ticket("301", "201", "11", YAZID)
    f.ticket("302", "202", "12", MOAN)
    f.ticket("303", "203", "13", VECTOR)
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    with calme():
        b = tk.suivre_managers(G)
    check("Spectrum🥷 : reconnue comme SPECTRUM, pas renommée, le VA passe à Spectrum",
          f.salons["13"]["name"] == "🔵┤ Manager Spectrum🥷 ├🔵"
          and fiche("203").get("manager") == SPECTRUM, b)
    lv.ETAT_FICHIER = TMP / "liens_va_18.json"
    lv.ETAT_FICHIER.write_text(json.dumps({"liens": {
        f"{G}:203": {"pseudo": "va203", "shortcode": "x", "link_id": "L203",
                     "groupe": "VECTOR"}}}), encoding="utf-8")
    crees, ranges = [], []
    gms_groupes = {"yazid": "g1", "moan": "g2", "vector": "g3"}

    def faux_groupe(equipe, nom):
        if nom.lower() not in gms_groupes:
            gms_groupes[nom.lower()] = "g-" + nom
            crees.append(nom)
        return gms_groupes[nom.lower()]
    lv.groupes = lambda equipe, essais=3: dict(gms_groupes)
    lv.groupe_manager = faux_groupe
    lv.ranger = lambda equipe, lid, nom: (ranges.append((lid, nom)) or (faux_groupe(equipe, nom) and nom))
    lv.SERVEURS.add(G)
    bl = lv.synchroniser(G)
    check("Spectrum🥷 : la synchro GetMySocial range le lien dans SPECTRUM, un seul groupe créé",
          ranges == [("L203", "SPECTRUM")] and crees == ["SPECTRUM"], (ranges, crees, bl))

    # ══ 14. tickets sans fiche dans une catégorie de manager ══════════════
    # Va Twitter, 13/10/2026 : « Manager SPECTRUM » (reprise de Vector) avait
    # trois tickets, dont deux sans fiche dans tickets.json — l'un d'eux, le
    # vieux ticket de VA de Spectrum lui-même. Vector y gardait sa ligne.
    print("\n— 14. tickets sans fiche : fiche refaite d'après les droits, puis rangés")
    f = monde(tickets={"203": ("303", VECTOR), "208": ("399", MOAN), SPECTRUM: (None, None)})
    f.categorie("11", NOM[YAZID], 1)
    f.categorie("12", NOM[MOAN], 2)
    f.categorie("13", NOM[SPECTRUM], 3)
    f.ticket("303", "203", "13", VECTOR, 1)          # avec fiche
    f.ticket("305", "205", "13", VECTOR, 2)          # sans fiche
    f.ticket("306", SPECTRUM, "13", VECTOR, 3)       # le vieux ticket de Spectrum
    f.ticket("307", "206", "13", VECTOR, 4)          # deux membres aux droits de VA
    f.salons["307"]["permission_overwrites"].append(
        {"id": "207", "type": 1, "allow": str(tk.MEMBRE), "deny": "0"})
    f.ticket("308", "208", "13", VECTOR, 5)          # 208 a déjà un autre ticket
    f.salons["309"] = {"id": "309", "type": 0, "name": "─│📌┤-notes", "parent_id": "13",
                       "position": 6, "guild_id": G, "permission_overwrites": [
                           {"id": "209", "type": 1, "allow": str(tk.MEMBRE), "deny": "0"}]}
    for u in (YAZID, MOAN, SPECTRUM):
        f.role(u, True)
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        b = tk.suivre_managers(G)
    dit = sortie.getvalue()
    check("sans fiche : deux tickets repris (305, et le vieux ticket de Spectrum), pas plus",
          len(b["adoptes"]) == 2 and any("305" in x or "va205" in x for x in b["adoptes"])
          and any(f"va{SPECTRUM}" in x for x in b["adoptes"]), b["adoptes"])
    d305 = f.droits("305")
    check("305 : fiche refaite, donnée à Spectrum (manager d'avant : Vector)",
          fiche("205").get("salon") == "305" and fiche("205").get("manager") == SPECTRUM
          and fiche("205").get("manager_avant") == VECTOR and fiche("205").get("adopte"),
          fiche("205"))
    check("305 : droits — Spectrum nommé, Vector retiré, le VA et le rôle intacts",
          d305.get(SPECTRUM, {}).get("allow") == str(tk.MANAGER) and VECTOR not in d305
          and d305.get("205", {}).get("allow") == str(tk.MEMBRE)
          and d305.get(ROLE_MGR, {}).get("allow") == str(tk.MANAGER), d305)
    d306 = f.droits("306")
    check("306 (ticket de Spectrum) : sa fiche vide reprend le salon, Vector retiré, "
          "sa ligne à lui inchangée",
          fiche(SPECTRUM).get("salon") == "306" and fiche(SPECTRUM).get("manager") == SPECTRUM
          and VECTOR not in d306 and d306.get(SPECTRUM, {}).get("allow") == str(tk.MEMBRE),
          (fiche(SPECTRUM), d306))
    check("303 (avec fiche) : rangé comme avant", fiche("203").get("manager") == SPECTRUM
          and VECTOR not in f.droits("303"))
    check("307 (deux membres aux droits de VA) : rien deviné, rien touché, et dit",
          not fiche("206") and not fiche("207") and VECTOR in f.droits("307")
          and "« ─│🔵┤-va-＠va206 » sans fiche" in dit and "2 membre(s)" in dit, dit[-600:])
    check("308 (son VA a déjà un autre ticket) : rien touché, et dit",
          fiche("208").get("salon") == "399" and VECTOR in f.droits("308")
          and "a déjà le ticket 399" in dit, dit[-600:])
    check("309 (pas un salon de ticket) : ignoré", not fiche("209")
          and "─│📌┤-notes" not in dit)
    f.appels.clear()
    with calme():
        b2 = tk.suivre_managers(G)
    check("sans fiche : un second tour ne refait rien (aucune écriture, rien de repris)",
          not f.ecritures() and not b2["adoptes"] and not b2["realignes"], (f.ecritures(), b2))

    # ══ 15. surnoms « MANAGER | Prénom » (Threads, 13/10/2026) ════════════
    print("\n— 15. un mot de rôle devant le prénom ne nomme personne")
    check("_nom_court : « MANAGER | Momoby » → MOMOBY, « HELPER | Roucham » → ROUCHAM, "
          "« Boss » seul reste BOSS",
          tk._nom_court({"nick": "MANAGER | Momoby", "user": {"id": "1"}}) == "MOMOBY"
          and tk._nom_court({"nick": "HELPER | Roucham", "user": {"id": "1"}}) == "ROUCHAM"
          and tk._nom_court({"nick": "Boss", "user": {"id": "1"}}) == "BOSS"
          and tk._nom_court({"nick": "🎯│𝑴𝑶𝑨𝑵", "user": {"id": "1"}}) == "MOAN")
    f = monde(tickets={"201": ("301", "106")})
    f.membre("105", "momobtn", "MANAGER | Momoby", manager=True)
    f.membre("106", "abdoul_9684", "MANAGER | Abdoul", manager=True)
    f.categorie("21", "🔵┤ Manager ABDOUL ├🔵", 1)
    f.categorie("22", "🔵┤ Manager MANAGER ├🔵", 2)
    f.ticket("301", "201", "21", "106", 1)
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        b = tk.suivre_managers(G)
    check("Threads : plus de « deux managers au même nom » ; « Manager MANAGER » devient "
          "« Manager MOMOBY », ABDOUL ne bouge pas, son VA non plus",
          not b["ignore"] and f.salons["22"]["name"] == "🔵┤ Manager MOMOBY ├🔵"
          and f.salons["21"]["name"] == "🔵┤ Manager ABDOUL ├🔵"
          and f.enfants("21") == ["301"] and fiche("201").get("manager") == "106"
          and "même nom" not in sortie.getvalue(), (b, sortie.getvalue()[-400:]))
    f.appels.clear()
    with calme():
        b2 = tk.suivre_managers(G)
    check("… et un second tour ne touche plus à rien", not f.ecritures() and not b2["ignore"],
          (f.ecritures(), b2))

    # ══ 13. branché dans la boucle du podium ══════════════════════════════
    src = (BOT / "web_upload.py").read_text(encoding="utf-8")
    i0 = src.find("def _start_podium_semaine_daemon")
    bloc = src[i0:i0 + 6000]
    check("boucle du podium : suivre_partout() appelé AVANT la synchro GetMySocial",
          "_tk_p.suivre_partout()" in bloc
          and bloc.index("_tk_p.suivre_partout()") < bloc.index("_sync_liens_va(gid)"))
    src_tk = (BOT / "tickets_discord.py").read_text(encoding="utf-8")
    check("tickets.json écrit par safe_json (écriture atomique)",
          "safe_json.write_text(ETAT_FICHIER" in src_tk and "safe_json.write(JOURNAL_FICHIER" in src_tk)

except Exception as _e:
    import traceback
    check("managers auto : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(tk, _k, _v)
    for _k, _v in _SAUVE_LV.items():
        setattr(lv, _k, _v)
    lv.SERVEURS.clear()
    lv.SERVEURS.update(_SAUVE_LV_SERVEURS)
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
