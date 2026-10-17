# -*- coding: utf-8 -*-
"""tests_verif_manager.py — « Vérifier » et /verifier : un manager vérifie
un membre, avec ou sans alerte, et le sort de ⏳ En attente.

Rien ne part vers Discord : verif_discord.api est remplacé par un serveur en
mémoire, les fiches vont dans un dossier temporaire, le ticket est simulé
(il écrirait data/tickets.json), le travail « en fond » tourne tout de suite.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tickets_discord as tk
import verif_discord as vd

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:300]}]"))


TW = vd.TWITTER_ID
CFG = vd.serveur(TW)
CIBLE, AUTRE, MGR_ID = "700000000000000001", "700000000000000002", "700000000000000009"
HELPER = "777"
APPELS, TICKETS = [], []
REPONSE = {"role": 204}
ALERTES = [
    {"id": "m1", "embeds": [{"title": "⏳ En attente d'un manager"}],
     "components": [{"type": 1, "components": [{"type": 2, "custom_id": f"verif:ok:{CIBLE}"},
                                               {"type": 2, "custom_id": f"verif:ban:{CIBLE}"}]}]},
    {"id": "m2", "embeds": [{"title": "⏳ En attente d'un manager"}],
     "components": [{"type": 1, "components": [{"type": 2, "custom_id": f"verif:ok:{AUTRE}"}]}]},
]


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw.get("json")))
    if chemin == f"/guilds/{TW}/roles":
        return 200, [{"id": HELPER, "name": "🤝 Helper"}, {"id": CFG["role_manager"], "name": "🛡️ Manager"}]
    if methode == "PUT" and "/roles/" in chemin:
        return REPONSE["role"], {}
    if methode == "GET" and chemin.startswith(f"/channels/{CFG['salon_attente']}/messages"):
        return 200, [dict(m) for m in ALERTES]
    if methode == "GET" and chemin.startswith("/channels/"):
        return 200, []
    if methode == "POST" and "/commands" in chemin:
        return 201, {"id": "c1"}
    return 200, {"id": "9"}


def commande(cible=CIBLE, roles_cible=(), perms="0", roles=(), slash=False, bot=False, absent=False, token="tok"):
    res = {"users": {cible: {"id": cible, "username": "nouveau_va", "bot": bot}}}
    if not absent:
        res["members"] = {cible: {"roles": list(roles_cible)}}
    data = {"name": vd.COMMANDE_SLASH if slash else vd.COMMANDE_MEMBRE, "type": 1 if slash else 2, "resolved": res}
    if slash:
        data["options"] = [{"name": "membre", "type": 6, "value": cible}]
    else:
        data["target_id"] = cible
    return {"type": 2, "guild_id": TW, "token": token, "application_id": "123456789012345678", "data": data,
            "member": {"user": {"id": MGR_ID, "username": "manager_x"}, "roles": list(roles), "permissions": perms}}


def appels(m=None, debut=""):
    return [(a, c, j) for a, c, j in APPELS if (m is None or a == m) and c.startswith(debut)]


_dT = Path(tempfile.mkdtemp())
SAV = (vd.api, vd._EN_FOND, vd.DATA_DIR, vd.FICHES, vd.LIENS, vd.SECRET_FILE, tk.ouvrir_ticket, dict(tk._CACHE_HELPER))
try:
    vd.api = faux_api
    vd._EN_FOND = lambda f: f()
    vd.DATA_DIR, vd.FICHES, vd.LIENS, vd.SECRET_FILE = _dT, _dT / "verif_membres.json", _dT / "verif_liens.json", _dT / "s"
    tk.ouvrir_ticket = lambda uid, cfg=None: TICKETS.append((uid, cfg["id"])) or "salon1"
    tk._CACHE_HELPER.clear()
    MGR = [CFG["role_manager"]]
    import time as _t
    vd._ecrire_fiches({vd._cle(TW, CIBLE): {"user_id": CIBLE, "guild_id": TW, "ts": _t.time(), "etat": "attente"}})

    # 1. un VA : refusé, rien ne bouge
    r = vd.traiter_interaction(commande(roles_cible=[CFG["role_attente"]]))
    check("un VA : « Réservé aux managers », aucun rôle touché",
          "managers" in r["data"]["content"] and not appels("PUT"), r)

    # 2. un manager, membre en attente avec une alerte (menu du membre)
    APPELS.clear()
    r = vd.traiter_interaction(commande(roles_cible=[CFG["role_attente"]], roles=MGR))
    roles_cible = f"/guilds/{TW}/members/{CIBLE}/roles/"
    fin = appels("PATCH", "/webhooks/")
    check("manager : réponse différée et éphémère (le travail part après)",
          r == {"type": 5, "data": {"flags": 64}}, r)
    check("manager : ✅ Vérifié posé sur LE membre, ⏳ et 🚩 retirés",
          ("PUT", roles_cible + CFG["role_verifie"]) in [(a, c) for a, c, _ in APPELS]
          and ("DELETE", roles_cible + CFG["role_attente"]) in [(a, c) for a, c, _ in APPELS]
          and ("DELETE", roles_cible + CFG["role_suspect"]) in [(a, c) for a, c, _ in APPELS])
    check("manager : bienvenue postée une fois, ticket ouvert (comme « Accepter »)",
          len(appels("POST", f"/channels/{CFG['salon_bienvenue']}/messages")) == 1 and TICKETS == [(CIBLE, TW)],
          (appels("POST"), TICKETS))
    patch_alerte = appels("PATCH", f"/channels/{CFG['salon_attente']}/messages/")
    check("son alerte perd ses boutons, celle d'un autre reste",
          [c.rsplit("/", 1)[1] for _, c, _ in patch_alerte] == ["m1"]
          and patch_alerte[0][2]["components"] == []
          and "vérifié par manager_x" in patch_alerte[0][2]["embeds"][0]["footer"]["text"], patch_alerte)
    trace = appels("POST", f"/channels/{CFG['salon_entrees']}/messages")
    check("une trace dans #entrées, sans notifier personne",
          len(trace) == 1 and CIBLE in trace[0][2]["embeds"][0]["description"]
          and "manager_x" in trace[0][2]["embeds"][0]["description"]
          and trace[0][2]["allowed_mentions"] == {"parse": []}, trace)
    fiche = vd._fiches().get(vd._cle(TW, CIBLE)) or {}
    check("fiche : « ok », avec le nom du manager",
          fiche.get("etat") == "ok" and "manager_x" in fiche.get("decision_manager", ""), fiche)
    check("le manager lit le résultat (« est vérifié », alerte close)",
          len(fin) == 1 and fin[0][1] == "/webhooks/123456789012345678/tok/messages/@original"
          and "est vérifié" in fin[0][2]["content"] and "alerte est close" in fin[0][2]["content"], fin)
    check("après la décision, le verrou est rendu", not vd._DECISIONS_EN_COURS)

    # 3. /verifier membre:@… — même chose, pour un membre sans alerte ni rôle
    APPELS.clear()
    TICKETS.clear()
    r = vd.traiter_interaction(commande(cible=AUTRE + "0", roles_cible=[], roles=MGR, slash=True))
    check("/verifier : le membre de l'option est vérifié, même sans alerte",
          r["type"] == 5 and ("PUT", f"/guilds/{TW}/members/{AUTRE}0/roles/{CFG['role_verifie']}")
          in [(a, c) for a, c, _ in APPELS] and TICKETS == [(AUTRE + "0", TW)]
          and "alerte" not in appels("PATCH", "/webhooks/")[0][2]["content"], APPELS)

    # 4. déjà vérifié : rien n'est rejoué
    APPELS.clear()
    r = vd.traiter_interaction(commande(roles_cible=[CFG["role_verifie"]], roles=MGR))
    check("déjà vérifié : le dit, sans reposter de bienvenue", "déjà vérifié" in r["data"]["content"]
          and not appels("PUT") and not appels("POST"), r)
    # vérifié mais encore en attente : on le sort de l'attente
    APPELS.clear()
    r = vd.traiter_interaction(commande(roles_cible=[CFG["role_verifie"], CFG["role_attente"]], roles=MGR))
    check("vérifié ET en attente : sorti de ⏳ En attente", r["type"] == 5
          and ("DELETE", roles_cible + CFG["role_attente"]) in [(a, c) for a, c, _ in APPELS])

    # 5. absent, bot, cible introuvable
    APPELS.clear()
    r1 = vd.traiter_interaction(commande(absent=True, roles=MGR))
    r2 = vd.traiter_interaction(commande(bot=True, roles=MGR))
    check("membre absent du serveur / bot : refusé sans rien toucher",
          "pas sur ce serveur" in r1["data"]["content"] and "bot" in r2["data"]["content"]
          and r1["data"]["allowed_mentions"] == {"parse": []} and not appels("PUT"), (r1, r2))

    # 6. deux managers en même temps sur le même membre
    APPELS.clear()
    file = []
    vd._EN_FOND = file.append
    r1 = vd.traiter_interaction(commande(roles_cible=[CFG["role_attente"]], roles=MGR, token="t1"))
    r2 = vd.traiter_interaction(commande(roles_cible=[CFG["role_attente"]], roles=MGR, token="t2"))
    check("double clic : une seule décision, rien d'appelé avant la réponse",
          r1["type"] == 5 and "déjà en cours" in r2["data"]["content"] and len(file) == 1 and not APPELS)
    file.pop()()
    vd._EN_FOND = lambda f: f()

    # 7. Discord refuse le rôle
    APPELS.clear()
    REPONSE["role"] = 403
    vd.traiter_interaction(commande(cible=AUTRE + "1", roles=MGR))
    fin = appels("PATCH", "/webhooks/")
    check("rôle refusé (403) : « Échec », pas de trace ni de bienvenue",
          "Échec (HTTP 403)" in fin[0][2]["content"] and not appels("POST"), APPELS)
    APPELS.clear()
    REPONSE["role"] = 404
    vd.traiter_interaction(commande(cible=AUTRE + "2", roles=MGR))
    check("parti entre-temps (404) : le dit", "quitté le serveur" in appels("PATCH", "/webhooks/")[0][2]["content"])
    REPONSE["role"] = 204

    # 8. qui est manager
    APPELS.clear()
    r = vd.traiter_interaction(commande(cible=AUTRE + "3", roles=[HELPER]))
    check("Twitter : le Helper peut vérifier (même niveau que Manager)", r["type"] == 5, r)
    r = vd.traiter_interaction(commande(cible=AUTRE + "4", perms=str(0x8)))
    check("un administrateur peut vérifier", r["type"] == 5, r)
    vaig = vd.serveur(vd.VA_IG_ID)
    check("Va IG : le rôle manager est 🛡️ Manager, pas BOSS",
          vaig["role_manager"] == "1555968604032213102")
    check("Va IG : un 🛡️ Manager est reconnu, un VA non",
          vd._est_manager({"roles": ["1555968604032213102"], "permissions": "0"}, vaig)
          and not vd._est_manager({"roles": [vaig["role_verifie"], "1555743334813671495"], "permissions": "0"}, vaig))

    # 9. ce qui n'est pas cette commande
    r = vd.traiter_interaction({"type": 2, "guild_id": TW, "data": {"name": "autre"}, "member": {}})
    check("une autre commande : « Action inconnue »", "inconnue" in r["data"]["content"], r)
    r = vd.traiter_interaction({"type": 5, "guild_id": TW, "data": {"custom_id": "x"}, "member": {}})
    check("une fenêtre : toujours « Action inconnue »", "inconnue" in r["data"]["content"], r)
    import annonces_discord as an
    import copie_discord as cp
    import quetes_discord as qd
    cmd = commande(roles=MGR)
    check("les autres modules de la route laissent passer la commande",
          an.traiter(cmd) is None and cp.traiter(cmd) is None and qd.traiter(cmd) is None and tk.traiter(cmd) is None)

    # 10. déclaration : sous le bot du serveur, cachée à qui ne peut pas expulser
    APPELS.clear()
    b = vd.enregistrer_commandes(TW)
    posts = appels("POST")
    app = vd.bot_du_serveur(TW)["app_id"]
    check("déclaration : deux commandes, sous l'application du bot du serveur",
          [c for _, c, _ in posts] == [f"/applications/{app}/guilds/{TW}/commands"] * 2
          and [j["name"] for _, _, j in posts] == ["Vérifier", "verifier"]
          and [j["type"] for _, _, j in posts] == [2, 1] and b == {"Vérifier": 201, "verifier": 201}, posts)
    check("déclaration : réservée à qui peut expulser (Manager, Helper, BOSS), option membre obligatoire",
          all(j["default_member_permissions"] == "2" for _, _, j in posts)
          and posts[1][2]["options"] == [{"type": 6, "name": "membre", "description": "La personne à vérifier",
                                          "required": True}], posts)
finally:
    vd.api, vd._EN_FOND, vd.DATA_DIR, vd.FICHES, vd.LIENS, vd.SECRET_FILE, tk.ouvrir_ticket, _ch = SAV
    tk._CACHE_HELPER.clear()
    tk._CACHE_HELPER.update(_ch)

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
