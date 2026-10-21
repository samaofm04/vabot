# -*- coding: utf-8 -*-
"""tests_accueils_tickets.py — l'entretien des accueils de tickets.

Audit du 20/10/2026 : une fiche de Twitter pointait vers un salon supprimé à
la main (septofm, 404) ; quatre accueils de Threads reposés le 13/10 n'étaient
pas épinglés (l'ancien l'était encore) ; neuf accueils nommaient le manager
d'avant une réaffectation (steave0454 : « Roucham » au lieu de MOMOBY).

Ce qui est vérifié (tickets_discord.entretenir_accueils, _donner_ticket) :
  - salon supprimé (404, code 10003) : la fiche sort de « tickets », rangée
    datée dans « tickets_disparus », jamais effacée ;
  - un autre refus (403) ou un accueil illisible : rien touché, et c'est dit ;
  - l'accueil qui nomme l'ancien manager : corrigé (description et contenu),
    sans mentionner personne à nouveau ;
  - l'accueil pas épinglé : épinglé, l'ancien accueil 👋 du bot désépinglé,
    jamais un message épinglé par quelqu'un d'autre ;
  - un second passage ne réécrit rien ;
  - la réaffectation (_donner_ticket) met l'accueil à jour tout de suite ;
  - le tour quotidien est branché dans suivre_partout.

Faux Discord, dossier temporaire : aucun appel réseau, rien dans data/.
Lancement : python tests_accueils_tickets.py
"""
from __future__ import annotations

import copy
import inspect
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

import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


G = "1498948161039896586"
TMP = pathlib.Path(tempfile.mkdtemp())
_SAUVE = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "_api")}


def accueil(mid, uid, manager, pinned):
    return {"id": mid, "pinned": pinned, "author": {"id": "BOT"},
            "content": f"<@{uid}> <@{manager}>",
            "embeds": [{"title": "👋 Bienvenue — voici ton espace perso",
                        "description": f"<@{uid}>, tu es confié à <@{manager}>.\n\n"
                                       "**C'est ici que ça se passe :**",
                        "footer": {"text": "YouLab"}}]}


class FauxDiscord:
    def __init__(self):
        self.appels = []
        self.salons = {"s1": 404, "s2": 403, "s3": 200, "s4": 200, "s5": 200}
        self.msgs = {"s3": {"a3": accueil("a3", "u3", "111", False),
                            "vieux3": dict(accueil("vieux3", "u3", "111", True),
                                           author={"id": "SIRI", "bot": True}),
                            "photo3": {"id": "photo3", "pinned": True, "author": {"id": "u3"},
                                       "embeds": [{"title": "👋 Bienvenue chez moi"}]}},
                     "s4": {"a4": accueil("a4", "u4", "444", True)},
                     "s5": {}}

    def ecritures(self):
        return [a for a in self.appels if a[0] != "GET"]

    def api(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw.get("json")))
        p = chemin.strip("/").split("/")
        if chemin == "/users/@me":
            return 200, {"id": "BOT"}
        s = p[1]
        if len(p) == 2:
            code = self.salons.get(s, 404)
            return code, ({"id": s} if code == 200 else
                          {"code": 10003, "message": "Unknown Channel"} if code == 404 else
                          {"code": 50001, "message": "Missing Access"})
        if p[2] == "messages":
            m = self.msgs.get(s, {}).get(p[3])
            if m is None:
                return 404, {"code": 10008}
            if methode == "PATCH":
                m.update(copy.deepcopy(kw.get("json") or {}))
                m.pop("allowed_mentions", None)
            return 200, copy.deepcopy(m)
        if p[2] == "permissions":
            return 204, {}
        if p[2] == "pins":
            if len(p) == 3:
                return 200, [copy.deepcopy(m) for m in self.msgs.get(s, {}).values() if m.get("pinned")]
            m = self.msgs.get(s, {}).get(p[3])
            if m is None:
                return 404, {"code": 10008}
            m["pinned"] = methode == "PUT"
            return 204, {}
        return 404, {}


try:
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.CONFIG_FICHIER = TMP / "tickets_config.json"
    fiches = {f"{G}:u1": {"salon": "s1", "manager": "m1", "accueil": "a1"},
              f"{G}:u2": {"salon": "s2", "manager": "m2", "accueil": "a2"},
              f"{G}:u3": {"salon": "s3", "manager": "222", "manager_avant": "111", "accueil": "a3"},
              f"{G}:u4": {"salon": "s4", "manager": "444", "accueil": "a4"},
              f"{G}:u5": {"salon": "s5", "manager": "m5", "accueil": "a5"},
              "1445108485090971710:u9": {"salon": "s9", "manager": "m9", "accueil": "a9"}}
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": fiches}), encoding="utf-8")
    d = FauxDiscord()
    tk._api = d.api
    b = tk.entretenir_accueils(G)
    etat = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))

    check("salon supprimé (404 Unknown Channel) : la fiche sort de « tickets »",
          f"{G}:u1" not in etat["tickets"] and b["disparus"] == ["u1 (salon s1)"], (b, etat))
    check("… rangée datée dans « tickets_disparus », rien de perdu",
          etat.get("tickets_disparus", {}).get(f"{G}:u1", {}).get("salon") == "s1"
          and etat["tickets_disparus"][f"{G}:u1"].get("disparu"), etat.get("tickets_disparus"))
    check("salon en 403 : fiche gardée, rien écrit, dit dans le bilan",
          f"{G}:u2" in etat["tickets"] and "u2 (HTTP 403)" in b["illisibles"]
          and not [a for a in d.ecritures() if "/s2/" in a[1]], b)
    check("accueil introuvable (404 du message) : rien écrit, dit",
          any(x.startswith("u5 : accueil") for x in b["illisibles"])
          and not [a for a in d.ecritures() if "/s5/" in a[1]], b)
    check("les fiches d'un autre serveur ne sont pas lues",
          not [a for a in d.appels if "/s9" in a[1]] and "1445108485090971710:u9" in etat["tickets"])

    m3 = d.msgs["s3"]["a3"]
    check("accueil de u3 : « tu es confié à <@222> », plus l'ancien manager",
          "tu es confié à <@222>." in m3["embeds"][0]["description"]
          and "<@111>" not in m3["embeds"][0]["description"] and b["managers"] == ["u3"], m3)
    check("… le contenu aussi, sans mentionner personne à nouveau",
          m3["content"] == "<@u3> <@222>"
          and all((a[2] or {}).get("allowed_mentions") == {"parse": []}
                  for a in d.ecritures() if a[0] == "PATCH"), m3["content"])
    check("… épinglé, et l'ancien accueil 👋 désépinglé (posé par Siri, un autre bot)",
          m3["pinned"] and not d.msgs["s3"]["vieux3"]["pinned"] and b["epingles"] == ["u3"], b)
    check("… le message épinglé par le VA lui-même reste épinglé",
          d.msgs["s3"]["photo3"]["pinned"])
    check("accueil déjà juste et épinglé (u4) : aucune écriture",
          not [a for a in d.ecritures() if "/s4/" in a[1]], d.ecritures())

    n = len(d.ecritures())
    b2 = tk.entretenir_accueils(G)
    check("un second passage ne réécrit rien", len(d.ecritures()) == n
          and not (b2["managers"] or b2["epingles"] or b2["disparus"]), (b2, d.ecritures()[n:]))

    # la réaffectation : l'accueil suit tout de suite
    d.msgs["s4"]["a4"] = accueil("a4", "u4", "444", True)
    salon = {"id": "s4", "permission_overwrites": [
        {"id": "444", "type": 1, "allow": str(tk.MANAGER), "deny": "0"},
        {"id": "u4", "type": 1, "allow": str(tk.MEMBRE), "deny": "0"}]}
    fs = {k: dict(v) for k, v in json.loads(tk.ETAT_FICHIER.read_text())["tickets"].items()}
    r = tk._donner_ticket(G, salon, f"{G}:u4", {"user": {"id": "4444"}}, fs)
    a4 = d.msgs["s4"]["a4"]
    check("réaffectation de u4 (444 → 4444) : faite, et l'accueil dit « confié à <@4444> »",
          r == "" and "tu es confié à <@4444>." in a4["embeds"][0]["description"]
          and a4["content"] == "<@u4> <@4444>"
          and json.loads(tk.ETAT_FICHIER.read_text())["tickets"][f"{G}:u4"]["manager"] == "4444",
          (r, a4))

    def plante(*a, **k):
        raise RuntimeError("Discord en panne")
    tk.corriger_manager_accueil, _vrai = plante, tk.corriger_manager_accueil
    salon["permission_overwrites"].append({"id": "4444", "type": 1, "allow": str(tk.MANAGER),
                                           "deny": "0"})
    fs = {k: dict(v) for k, v in json.loads(tk.ETAT_FICHIER.read_text())["tickets"].items()}
    r2 = tk._donner_ticket(G, salon, f"{G}:u4", {"user": {"id": "4545"}}, fs)
    tk.corriger_manager_accueil = _vrai
    check("un accueil qui ne se corrige pas ne défait pas la réaffectation",
          r2 == "" and json.loads(tk.ETAT_FICHIER.read_text())["tickets"][f"{G}:u4"]["manager"]
          == "4545", r2)

    src = inspect.getsource(tk.suivre_partout)
    check("branché dans suivre_partout, une fois par jour et par serveur",
          "entretenir_accueils(gid)" in src and "ENTRETIEN_S" in src)
except Exception as _e:
    import traceback
    check("accueils : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(tk, _k, _v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
