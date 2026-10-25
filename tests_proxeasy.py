"""Tests de proxeasy.py, sans réseau : ProxEasy et Discord sont simulés.

Lancer : python tests_proxeasy.py — n'écrit rien dans le vrai data/ (la clé et
l'état vont dans un dossier temporaire).
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import proxeasy

OK = ECHECS = 0


def verifier(nom, cond):
    global OK, ECHECS
    if cond:
        OK += 1
        print("OK   " + nom)
    else:
        ECHECS += 1
        print("ECHEC " + nom)


class Rep:
    def __init__(self, code, corps=None):
        self.status_code = code
        self.ok = 200 <= code < 300
        self._corps = corps
        self.content = b"" if corps is None else json.dumps(corps).encode()

    def json(self):
        if self._corps is None:
            raise ValueError("vide")
        return self._corps


SERVEUR = proxeasy.SERVEUR
CLE_REST = "pe_live_" + "x" * 40 + "WXYZ"


class Faux:
    """Un ProxEasy et un Discord en mémoire."""

    def __init__(self):
        self.cle_valide = CLE_REST
        self.services = {sid: {"id": sid, "status": "active", "capabilities": ["credentials"],
                               "next_due_date": "2026-11-25"} for sid in (2528, 2529, 2216)}
        self.services[2213] = {"id": 2213, "status": "terminated", "capabilities": []}
        self.creds = {sid: {"host": f"h{sid}.cn.fxdx.in", "socks": 17000 + sid % 100,
                            "http": 18000 + sid % 100, "user": f"u{sid}", "pass": f"p{sid}"}
                      for sid in self.services}
        prive = [{"id": SERVEUR, "type": 0, "allow": "0", "deny": str(proxeasy.VOIR)},
                 {"id": "900", "type": 1, "allow": str(proxeasy.VOIR), "deny": "0"}]
        self.salons = [
            {"id": "101", "type": 0, "name": "🌐・proxyeasy-1-pe-2528", "permission_overwrites": prive},
            {"id": "102", "type": 0, "name": "🌐・proxyeasy-2-pe-2529", "permission_overwrites": prive},
            {"id": "103", "type": 0, "name": "🌐・proxyeasy-3-pe-2216", "permission_overwrites": prive},
            {"id": "104", "type": 0, "name": "proxyeasy-4-pe-9999", "permission_overwrites": prive},
            {"id": proxeasy.SUIVI, "type": 0, "name": "suivi-proxy", "permission_overwrites": prive},
            {"id": "105", "type": 0, "name": "general", "permission_overwrites": []},
        ]
        self.roles = [{"id": SERVEUR, "name": "@everyone", "permissions": str(proxeasy.VOIR)},
                      {"id": "7", "name": "BOSS", "permissions": str(proxeasy.ADMINISTRATEUR)}]
        self.messages = {}           # salon -> {id: contenu}
        self.ecritures = []          # (méthode, chemin)
        self.prochain = 1000
        self.vus_bearer = set()

    # ProxEasy
    def get(self, url, params=None, headers=None, timeout=None):
        jeton = (headers or {}).get("Authorization", "")
        self.vus_bearer.add(jeton)
        if jeton != "Bearer " + self.cle_valide:
            return Rep(401, {"error": {"code": "invalid_token", "message": "A valid API credential is required."}})
        chemin = url.replace(proxeasy.API, "")
        if chemin == "/services":
            return Rep(200, {"data": {"items": list(self.services.values()), "next_cursor": None},
                             "request_id": "r"})
        if chemin.startswith("/services/") and chemin.endswith("/credentials"):
            sid = int(chemin.split("/")[2])
            c = self.creds[sid]
            return Rep(200, {"data": {"service_id": sid, "endpoints": [
                {"protocol": "http", "host": c["host"], "port": c["http"], "username": c["user"], "password": c["pass"]},
                {"protocol": "socks5", "host": c["host"], "port": c["socks"], "username": c["user"], "password": c["pass"]},
            ]}, "request_id": "r"})
        return Rep(404, {"error": {"code": "not_found", "message": "Route not found."}})

    # Discord
    def request(self, methode, url, json=None, timeout=None, headers=None):
        chemin = url.replace(proxeasy.DISCORD, "")
        p = chemin.strip("/").split("/")
        if methode != "GET":
            self.ecritures.append((methode, chemin, (json or {}).get("content")))
        if chemin == f"/guilds/{SERVEUR}/roles":
            return Rep(200, self.roles)
        if chemin == f"/guilds/{SERVEUR}/channels":
            return Rep(200, self.salons)
        if p[:3] == ["guilds", SERVEUR, "members"]:
            return Rep(200, {"nick": "NOUM VA", "user": {"username": "noum"}})
        if p[0] == "channels" and p[2] == "messages":
            boite = self.messages.setdefault(p[1], {})
            if methode == "POST":
                self.prochain += 1
                boite[str(self.prochain)] = json["content"]
                return Rep(200, {"id": str(self.prochain), "content": json["content"], "flags": json.get("flags")})
            mid = p[3]
            if mid not in boite:
                return Rep(404, {"message": "Unknown Message"})
            if methode == "GET":
                return Rep(200, {"id": mid, "content": boite[mid]})
            if methode == "PATCH":
                boite[mid] = json["content"]
                return Rep(200, {"id": mid, "content": json["content"]})
            if methode == "DELETE":
                del boite[mid]
                return Rep(204)
        return Rep(404, {})


def contenus(f, salon):
    return list(f.messages.get(salon, {}).values())


def principal():
    tmp = Path(tempfile.mkdtemp(prefix="proxeasy-test-"))
    proxeasy.CLE = tmp / "proxeasy_cle.json"
    proxeasy.ETAT = tmp / "proxeasy_salons.json"
    os.environ["DISCORD_TOKEN"] = "jeton-de-test"
    f = Faux()
    proxeasy.requests.get = f.get
    proxeasy.requests.request = f.request
    journal = []
    import builtins
    print_vrai = builtins.print
    builtins.print = lambda *a, **k: (journal.append(" ".join(map(str, a))), print_vrai(*a, **k))

    ok, msg = proxeasy.enregistrer_cle("pe_mcp_82d0_" + "a" * 40, "admin")
    verifier("la clé MCP est refusée avec l'explication", not ok and "MCP" in msg and not proxeasy.CLE.exists())
    ok, msg = proxeasy.enregistrer_cle("mauvaise-cle-" + "b" * 30, "admin")
    verifier("une clé refusée par ProxEasy n'est pas gardée", not ok and "refuse" in msg and not proxeasy.CLE.exists())
    ok, msg = proxeasy.enregistrer_cle("  Bearer " + CLE_REST + "\n", "admin")
    verifier("la bonne clé est gardée (Bearer et blancs retirés)", ok and proxeasy.cle() == CLE_REST)
    verifier("le message ne montre que la fin de la clé", "WXYZ" in msg and CLE_REST[:20] not in msg)
    verifier("fichier de la clé en 600", stat.S_IMODE(proxeasy.CLE.stat().st_mode) == 0o600)
    e = proxeasy.etat_cle()
    verifier("etat_cle : fin seulement", e["fin"] == "WXYZ" and "cle" not in e)
    page = proxeasy.panneau_html()
    verifier("la page ne contient jamais la clé", CLE_REST not in page and CLE_REST[:-4] not in page and "…WXYZ" in page)

    # arrêt : lecture seule
    b = proxeasy.synchroniser()
    verifier("arrêt : aucune écriture Discord", f.ecritures == [])
    verifier("arrêt : les 4 salons proxy relevés, pas les autres", [l["service"] for l in b["salons"]] == [2528, 2529, 2216, 9999])
    verifier("qui voit : le membre autorisé et les admins",
             b["salons"][0]["voient"] == ["NOUM VA", "@BOSS"])
    verifier("pe-9999 introuvable noté sur la page", "introuvable" in b["salons"][3].get("probleme", ""))

    # essai : le premier salon seulement
    proxeasy.choisir_mode("essai")
    b = proxeasy.synchroniser()
    c = f.creds[2528]
    verifier("essai : quatre messages dans proxyeasy-1, hôte / port SOCKS5 / utilisateur / mot de passe",
             contenus(f, "101") == [c["host"], str(c["socks"]), c["user"], c["pass"]])
    verifier("essai : rien dans les autres salons", not contenus(f, "102") and not contenus(f, "103"))
    posts = [e for e in f.ecritures if e[0] == "POST" and e[1].startswith("/channels/101/")]
    verifier("essai : les quatre messages sont silencieux", len(posts) == 4)
    alertes = [e for e in f.ecritures if e[1] == f"/channels/{proxeasy.SUIVI}/messages"]
    verifier("pe-9999 introuvable dit dans suivi-proxy", len(alertes) == 1 and "pe-9999" in alertes[0][2])

    f.ecritures.clear()
    proxeasy.synchroniser()
    verifier("deuxième tour : rien n'est réécrit, l'alerte n'est pas redite", f.ecritures == [])

    # identifiants changés : édités en place
    f.creds[2528]["pass"] = "nouveau"
    f.ecritures.clear()
    b = proxeasy.synchroniser()
    verifier("mot de passe changé : un seul message édité, rien de reposé",
             [e[0] for e in f.ecritures] == ["PATCH"] and contenus(f, "101")[3] == "nouveau")

    # un message effacé à la main : le jeu est reposé dans l'ordre
    ids = list(f.messages["101"])
    del f.messages["101"][ids[1]]
    f.ecritures.clear()
    proxeasy.synchroniser()
    verifier("message effacé : quatre reposés, les restes effacés",
             contenus(f, "101") == [c["host"], str(c["socks"]), c["user"], "nouveau"]
             and len(f.messages["101"]) == 4
             and sum(1 for e in f.ecritures if e[0] == "POST") == 4)

    # tous : chaque salon, et un nouveau salon reçoit ses logins seul
    proxeasy.choisir_mode("tous")
    f.salons.append({"id": "110", "type": 0, "name": "🌐・proxyeasy-10-pe-2216",
                     "permission_overwrites": f.salons[0]["permission_overwrites"]})
    proxeasy.synchroniser()
    verifier("tous : chaque salon a ses logins", all(len(contenus(f, s)) == 4 for s in ("101", "102", "103", "110")))

    # expiré : dit une fois, puis levé
    f.services[2529]["status"] = "terminated"
    f.ecritures.clear()
    proxeasy.synchroniser()
    proxeasy.synchroniser()
    al = [e for e in f.ecritures if e[1] == f"/channels/{proxeasy.SUIVI}/messages"]
    verifier("expiré : dit une seule fois dans suivi-proxy", len(al) == 1 and "terminated" in al[0][2] and "<#102>" in al[0][2])
    f.services[2529]["status"] = "active"
    f.ecritures.clear()
    proxeasy.synchroniser()
    al = [e for e in f.ecritures if e[1] == f"/channels/{proxeasy.SUIVI}/messages"]
    verifier("revenu : un ✅ dans suivi-proxy", len(al) == 1 and al[0][2].startswith("✅"))

    # salon ouvert à tous : rien n'y part
    f.salons.append({"id": "111", "type": 0, "name": "proxyeasy-11-pe-2528",
                     "permission_overwrites": []})
    f.ecritures.clear()
    b = proxeasy.synchroniser()
    verifier("salon visible de tous : aucun login posté", not contenus(f, "111"))
    verifier("salon visible de tous : dit dans suivi-proxy",
             any("<#111>" in (e[2] or "") for e in f.ecritures))

    # clé révoquée : dite, le relevé s'arrête
    f.cle_valide = "autre"
    f.ecritures.clear()
    b = proxeasy.synchroniser()
    verifier("clé révoquée : erreur sur la page et alerte",
             "invalid_token" in b["erreur"]
             and any("refuse la clé" in (e[2] or "") for e in f.ecritures))

    tout = "\n".join(journal) + proxeasy.ETAT.read_text()
    secrets = [CLE_REST, "nouveau"] + [v["pass"] for v in f.creds.values()]
    verifier("ni la clé ni un mot de passe dans le journal ou l'état",
             not any(s in tout for s in secrets))
    builtins.print = print_vrai
    print(f"\nRESULTAT : {OK} OK / {ECHECS} ECHEC(S)")
    return 1 if ECHECS else 0


if __name__ == "__main__":
    sys.exit(principal())
