# -*- coding: utf-8 -*-
"""tests_helper_discord.py — le rôle 🤝 Helper, au même niveau que Manager.

Propriétaire, 13/10/2026 : « un rôle helper sans être manager, avec les mêmes
accès », « pour les mecs au même niveau que les managers ».

Ce qui est vérifié :
  - aligner_helper crée le rôle s'il manque, avec les droits de serveur du
    Manager, et le range sous lui ;
  - il recopie la ligne du Manager sur chaque salon qui en a une (catégories,
    tickets, salons du staff), et seulement ceux-là ;
  - un second tour ne fait rien ; une ligne Helper différente est remise au
    niveau du Manager ; une ligne Helper posée à la main ailleurs reste ;
  - Discord refuse les droits de serveur : le rôle naît quand même, et c'est dit ;
  - au plus MAX_HELPER_PAR_TOUR salons par tour, le reste au suivant ;
  - un Helper déjà créé à la main est repris, pas doublé ;
  - role_manager ne prend jamais le Helper pour le Manager, et le tour de rôle
    des tickets (managers) ne le sert pas ;
  - les boutons : tickets, vérification, quêtes acceptent le Helper, refusent
    un VA ;
  - un ticket ou une catégorie neuve porte la ligne Helper ;
  - hors des serveurs à tickets, role_helper ne demande rien à Discord.

Faux Discord en mémoire : aucun appel réseau, rien n'est écrit dans data/.
Lancement : python tests_helper_discord.py
"""
from __future__ import annotations

import io
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import quetes_discord as qd            # noqa: E402
import tickets_discord as tk           # noqa: E402
import verif_discord as vd             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


G = "1445108485090971710"              # YouLab TWITTER : dans SERVEURS_TICKETS
ROLE_MGR, ROLE_VERIF = "900", "700"
PERMS_MGR = "268435456"                # gérer les rôles, pour voir qu'il est recopié


class FauxDiscord:
    def __init__(self, avec_helper=False, salons_va=3):
        self.roles = [{"id": ROLE_MGR, "name": "🛡️ Manager", "permissions": PERMS_MGR,
                       "hoist": True, "mentionable": True, "position": 12},
                      {"id": ROLE_VERIF, "name": "✅ Vérifié", "permissions": "0", "position": 3}]
        if avec_helper:
            self.roles.append({"id": "950", "name": "Helper", "permissions": "0", "position": 2})
        ligne_mgr = {"id": ROLE_MGR, "type": 0, "allow": str(tk.MANAGER), "deny": "0"}
        self.salons = {
            "c1": {"id": "c1", "type": 4, "name": "🔵┤ Manager YAZID ├🔵",
                   "permission_overwrites": [{"id": G, "type": 0, "allow": "0", "deny": "1024"},
                                             dict(ligne_mgr)]},
            "staff": {"id": "staff", "type": 0, "name": "⏳┃en-attente",
                      "permission_overwrites": [{"id": ROLE_MGR, "type": 0, "allow": "1024",
                                                 "deny": "2048"}]},
            "public": {"id": "public", "type": 0, "name": "📋┃règles",
                       "permission_overwrites": []},
        }
        for i in range(salons_va):
            self.salons[f"va{i}"] = {"id": f"va{i}", "type": 0, "parent_id": "c1",
                                     "name": f"─│🔵┤-va-x{i}",
                                     "permission_overwrites": [dict(ligne_mgr)]}
        self.appels = []
        self.membres = []
        self.refus_droits_serveur = False
        self.cree = 0

    def __call__(self, methode, chemin, **kw):
        self.appels.append((methode, chemin))
        corps = kw.get("json")
        if methode == "GET" and chemin == f"/guilds/{G}/roles":
            return 200, [dict(r) for r in self.roles]
        if methode == "POST" and chemin == f"/guilds/{G}/roles":
            if self.refus_droits_serveur and corps.get("permissions") != "0":
                return 403, {"message": "Missing Permissions"}
            self.cree += 1
            r = dict(corps, id=f"95{self.cree}", position=1)
            self.roles.append(r)
            return 200, dict(r)
        if methode == "PATCH" and chemin == f"/guilds/{G}/roles":
            for p in corps:
                for r in self.roles:
                    if r["id"] == p["id"]:
                        r["position"] = p["position"]
            return 200, [dict(r) for r in self.roles]
        if methode == "GET" and chemin == f"/guilds/{G}/channels":
            return 200, [{**c, "permission_overwrites": [dict(o) for o in c["permission_overwrites"]]}
                         for c in self.salons.values()]
        if methode == "PUT" and "/permissions/" in chemin:
            cid, oid = chemin.split("/")[2], chemin.split("/")[4]
            lignes = [o for o in self.salons[cid]["permission_overwrites"] if o["id"] != oid]
            lignes.append({"id": oid, **corps})
            self.salons[cid]["permission_overwrites"] = lignes
            return 204, {}
        if methode == "POST" and chemin == f"/guilds/{G}/channels":
            return 201, {"id": "neuf", **corps}
        if methode == "GET" and chemin == f"/guilds/{G}/members":
            return 200, [dict(m) for m in self.membres]
        return 404, {"message": f"route inconnue {methode} {chemin}"}

    def ligne(self, cid, oid):
        return next((o for o in self.salons[cid]["permission_overwrites"] if o["id"] == oid), None)

    def helper(self):
        return next((r for r in self.roles if "helper" in r["name"].lower()), None)


_SAUVE = (tk._api, tk._config, qd._api if hasattr(qd, "_api") else None)
tk._config = lambda: {}


def monde(**kw):
    f = FauxDiscord(**kw)
    tk._api = f
    tk._CACHE_HELPER.clear()
    return f


try:
    # ── création + recopie ───────────────────────────────────────────────
    f = monde()
    b = tk.aligner_helper(G)
    h = f.helper()
    check("rôle créé : « 🤝 Helper »", b["cree"] and h and h["name"] == tk.ROLE_HELPER_NOM, b)
    check("droits de serveur du Manager recopiés, affichage séparé comme lui",
          h and h["permissions"] == PERMS_MGR and h["hoist"] and h["mentionable"], h)
    check("rangé sous Manager (position demandée = celle du Manager)",
          h and h["position"] == 12, h)
    hid = h["id"] if h else ""
    voulu = {"allow": str(tk.MANAGER), "deny": "0"}
    check("catégorie du manager : ligne Helper = ligne Manager",
          (f.ligne("c1", hid) or {}).get("allow") == voulu["allow"], f.salons["c1"])
    check("chaque ticket de VA : ligne Helper posée",
          all((f.ligne(f"va{i}", hid) or {}).get("allow") == voulu["allow"] for i in range(3)))
    check("salon du staff : allow ET deny recopiés tels quels",
          (f.ligne("staff", hid) or {}) .get("allow") == "1024"
          and (f.ligne("staff", hid) or {}).get("deny") == "2048", f.salons["staff"])
    check("salon sans ligne Manager : rien ajouté", f.ligne("public", hid) is None)
    check("bilan : 5 salons alignés", b["copies"] == 5 and not b["rates"], b)

    f.appels.clear()
    b2 = tk.aligner_helper(G)
    check("second tour : rien écrit (idempotent)",
          b2["copies"] == 0 and b2["deja"] == 5 and not b2["cree"]
          and not [a for a in f.appels if a[0] != "GET"], (b2, f.appels))

    f.salons["va0"]["permission_overwrites"] = [
        o if o["id"] != hid else {**o, "allow": "1024"} for o in f.salons["va0"]["permission_overwrites"]]
    f.salons["public"]["permission_overwrites"].append({"id": hid, "type": 0, "allow": "1024", "deny": "0"})
    b3 = tk.aligner_helper(G)
    check("ligne Helper différente : remise au niveau du Manager",
          (f.ligne("va0", hid) or {}).get("allow") == voulu["allow"] and b3["copies"] == 1, b3)
    check("ligne Helper posée à la main là où le Manager n'est pas : gardée",
          (f.ligne("public", hid) or {}).get("allow") == "1024")

    # ── refus des droits de serveur ──────────────────────────────────────
    f = monde()
    f.refus_droits_serveur = True
    b = tk.aligner_helper(G)
    h = f.helper()
    check("droits de serveur refusés : rôle créé quand même, sans droits",
          b["cree"] and h and h["permissions"] == "0", (b, h))
    check("… et c'est dit dans le bilan",
          any("droits de serveur" in r for r in b["rates"]), b)
    check("… les salons sont alignés malgré tout", b["copies"] == 5, b)

    # ── plafond par tour ─────────────────────────────────────────────────
    f = monde(salons_va=tk.MAX_HELPER_PAR_TOUR + 5)
    b = tk.aligner_helper(G)
    check(f"au plus {tk.MAX_HELPER_PAR_TOUR} salons par tour, le reste reporté",
          b["copies"] == tk.MAX_HELPER_PAR_TOUR and b["reportes"] == 7, b)
    b = tk.aligner_helper(G)
    check("le tour suivant finit le travail", b["copies"] == 7 and b["reportes"] == 0, b)

    # ── Helper créé à la main ────────────────────────────────────────────
    f = monde(avec_helper=True)
    b = tk.aligner_helper(G)
    check("Helper déjà là : repris, pas doublé",
          not b["cree"] and f.cree == 0 and (f.ligne("va1", "950") or {}).get("allow") == str(tk.MANAGER), b)

    # ── jamais pris pour le Manager ──────────────────────────────────────
    f = monde()
    f.roles.insert(0, {"id": "960", "name": "🤝 Helper", "permissions": "0", "position": 13})
    check("role_manager ne prend pas le Helper, même placé au-dessus",
          tk.role_manager(G) == ROLE_MGR, tk.role_manager(G))
    check("role_helper le trouve", tk.role_helper(G) == "960")
    f.roles.append({"id": "961", "name": "Helper manager", "position": 0})
    tk._CACHE_HELPER.clear()
    check("un « Helper manager » n'est pas pris pour le Helper", tk.role_helper(G) == "960")
    f.membres = [{"user": {"id": "1"}, "roles": [ROLE_MGR]},
                 {"user": {"id": "2"}, "roles": ["960"]},
                 {"user": {"id": "3"}, "roles": [ROLE_MGR, "960"]}]
    tk._CACHE.clear()
    ids = sorted(str(m["user"]["id"]) for m in tk.managers(G, force=True))
    check("tour de rôle des tickets : un Helper seul n'y est pas, un Manager-Helper oui",
          ids == ["1", "3"], ids)
    tk._CACHE.clear()

    # ── boutons ──────────────────────────────────────────────────────────
    f = monde()
    tk.aligner_helper(G)
    hid = f.helper()["id"]
    helper = {"user": {"id": "55"}, "roles": [ROLE_VERIF, hid], "permissions": "0"}
    va = {"user": {"id": "66"}, "roles": [ROLE_VERIF], "permissions": "0"}
    check("tickets : le Helper a les boutons des managers", tk._est_manager_brut(G, helper))
    check("tickets : un VA ne les a pas", not tk._est_manager_brut(G, va))
    r = tk.traiter({"type": 3, "guild_id": G, "member": va,
                    "data": {"custom_id": "lien:off:66"}})
    check("tickets : refus du VA nomme les helpers",
          r and "helpers" in r["data"]["content"], r)
    cfg = vd.serveur(G)
    check("vérification : le Helper peut valider une entrée", vd._est_manager(helper, cfg))
    check("vérification : un VA non", not vd._est_manager(va, cfg))
    check("vérification : le Manager toujours", vd._est_manager(
        {"roles": [cfg["role_manager"]], "permissions": "0"}, cfg))
    _rm = tk.role_manager
    tk.role_manager = lambda gid: ROLE_MGR
    check("quêtes : le Helper a les boutons des managers",
          qd._est_manager({"member": helper}, G))
    check("quêtes : un VA non", not qd._est_manager({"member": va}, G))
    tk.role_manager = _rm

    # ── salons neufs ─────────────────────────────────────────────────────
    f.appels.clear()
    code, _ = tk._creer_categorie(G, {"user": {"id": "1", "username": "spectrum"}}, ROLE_MGR)
    post = [a for a in f.appels if a == ("POST", f"/guilds/{G}/channels")]
    check("catégorie neuve : créée", code == 201 and post)
    lignes = tk._droits_staff(ROLE_MGR, hid)
    check("catégorie / ticket neufs : Manager ET Helper avec les droits manager",
          [l["id"] for l in lignes] == [ROLE_MGR, hid]
          and all(l["allow"] == str(tk.MANAGER) for l in lignes), lignes)
    check("sans Helper sur le serveur : seule la ligne Manager",
          [l["id"] for l in tk._droits_staff(ROLE_MGR, "")] == [ROLE_MGR])

    # ── hors périmètre ───────────────────────────────────────────────────
    f = monde()
    f.appels.clear()
    check("Entretien / Va IG : role_helper rend « » sans appeler Discord",
          tk.role_helper("1505418484052394004") == "" and not f.appels, f.appels)
finally:
    tk._api, tk._config = _SAUVE[0], _SAUVE[1]
    tk._CACHE_HELPER.clear()

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
