# -*- coding: utf-8 -*-
"""tests_menu_ticket.py — le menu reposé en bas du ticket (tickets_discord.ramener_menu).

Propriétaire, 23/10/2026 : « 📱・numéro-usa devient un salon menu avec un
bouton qui active leur menu dans leur propre salon ».

Ce qui est vérifié :
  - une copie des boutons de l'accueil est postée en bas du ticket, épinglée,
    sans mention, sans les « id » des composants rendus par Discord ; l'avis
    « … a épinglé un message » est retiré ;
  - l'accueil épinglé ne bouge pas ; l'ancienne copie est retirée ;
  - déjà en bas (rien que des messages de bots dessous) : « deja », rien posé ;
  - un salon qui n'est pas le ticket du VA, un refus Discord, une panne :
    « echec », sans exception ;
  - la copie suit l'accueil : un PATCH de ses boutons est recopié sur elle ;
    la réponse type 7 de « Confirmer le VA » passe à l'autre message ;
  - menu_prive (staff sans salon) : la rangée du VA pour lui seul, sans
    bouton de manager.

Faux Discord, dossier temporaire : aucun appel réseau, rien dans data/.
Lancement : python tests_menu_ticket.py
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

import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


G, U, S, ACC = "1445108485090971710", "777", "5000", "9001"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="menu_ticket_"))
_SAUVE = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "_api_reseau", "_en_fond", "_traiter_sans_copie")}
RANGS_ACCUEIL = [
    {"type": 1, "id": 1, "components": [
        {"type": 2, "id": 2, "style": 2, "label": "Mon adresse USDC", "custom_id": f"usdc:set:{U}"},
        {"type": 2, "id": 3, "style": 3, "label": "Mes stats", "custom_id": f"subs:total:{U}"},
        {"type": 2, "id": 4, "style": 2, "label": "Numéro", "custom_id": "numx:menu"}]},
    {"type": 1, "id": 5, "components": [
        {"type": 2, "id": 6, "style": 3, "label": "Confirmer le VA", "custom_id": f"essai:ok:{U}"},
        {"type": 2, "id": 7, "style": 4, "label": "Désactiver le lien", "custom_id": f"lien:off:{U}"}]}]


class FauxDiscord:
    def __init__(self):
        self.appels = []
        self.messages = {ACC: {"id": ACC, "type": 0, "author": {"id": "bot", "bot": True},
                               "components": RANGS_ACCUEIL}}
        self.fil = [ACC]                    # du plus ancien au plus récent
        self.epingles = {ACC}
        self.refus_post = False
        self.n = 0

    def _ajouter(self, m):
        self.messages[m["id"]] = m
        self.fil.append(m["id"])

    def humain(self):
        self.n += 1
        self._ajouter({"id": f"h{self.n}", "type": 0, "author": {"id": U}})

    def api(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw.get("json")))
        if methode == "GET" and "?limit=" in chemin:
            lim = int(chemin.rsplit("=", 1)[1])
            return 200, [self.messages[m] for m in reversed(self.fil)][:lim]
        if methode == "GET":
            mid = chemin.rsplit("/", 1)[1]
            return (200, self.messages[mid]) if mid in self.messages else (404, {})
        if methode == "POST":
            if self.refus_post:
                return 403, {"message": "Missing Access"}
            self.n += 1
            mid = f"c{self.n}"
            self._ajouter({"id": mid, "type": 0, "author": {"id": "bot", "bot": True},
                           "components": kw["json"]["components"]})
            return 200, {"id": mid}
        if methode == "PUT" and "/pins/" in chemin:
            mid = chemin.rsplit("/", 1)[1]
            self.epingles.add(mid)
            self.n += 1
            self._ajouter({"id": f"p{self.n}", "type": 6, "author": {"id": "bot", "bot": True},
                           "message_reference": {"message_id": mid}})
            return 204, {}
        if methode == "DELETE":
            mid = chemin.rsplit("/", 1)[1]
            self.fil = [m for m in self.fil if m != mid]
            self.epingles.discard(mid)
            return (204, {}) if self.messages.pop(mid, None) else (404, {})
        if methode == "PATCH":
            mid = chemin.rsplit("/", 1)[1]
            if mid in self.messages and "components" in (kw.get("json") or {}):
                self.messages[mid]["components"] = kw["json"]["components"]
            return 200, {}
        return 200, {}


def etat():
    return json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))


def ids_de(rangs):
    return [b.get("custom_id") for r in rangs for b in r.get("components") or []]


try:
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{G}:{U}": {"salon": S, "accueil": ACC, "manager": "1", "confirme": False}}}), encoding="utf-8")
    d = FauxDiscord()
    tk._api_reseau = d.api
    tk._en_fond = lambda f: f()

    check("accueil tout juste posé, rien dessous : déjà en bas", tk.ramener_menu(G, U, S) == "deja"
          and not [a for a in d.appels if a[0] in ("POST", "DELETE", "PUT")], d.appels)
    d.humain(); d.humain()
    r1 = tk.ramener_menu(G, U, S)
    post = [a for a in d.appels if a[0] == "POST"]
    c1 = etat()["tickets"][f"{G}:{U}"].get("menu")
    check("conversation dessous : le menu est reposé en bas du ticket et épinglé",
          r1 == "ramene" and len(post) == 1 and post[0][1] == f"/channels/{S}/messages"
          and d.fil[-1] == c1 and c1 in d.epingles, (r1, d.fil, d.epingles))
    check("… l'avis « a épinglé un message » est retiré",
          not [m for m in d.messages.values() if m.get("type") == 6], d.fil)
    corps = post[0][2]
    check("… les mêmes boutons que l'accueil (rangée du VA, rangée des managers), sans « id », sans mention",
          ids_de(corps["components"]) == ids_de(RANGS_ACCUEIL) and len(corps["components"]) == 2
          and '"id"' not in json.dumps(corps["components"])
          and corps["allowed_mentions"] == {"parse": []}, corps)
    check("… l'accueil épinglé ne bouge pas", ACC in d.messages and ACC in d.epingles
          and not [a for a in d.appels if a[0] in ("PATCH", "DELETE") and a[1].endswith(ACC)])
    n = len(d.appels)
    check("redemandé tout de suite : déjà en bas, rien reposé", tk.ramener_menu(G, U, S) == "deja"
          and not [a for a in d.appels[n:] if a[0] in ("POST", "DELETE", "PUT")], d.appels[n:])
    d._ajouter({"id": "carte", "type": 0, "author": {"id": "bot", "bot": True}})
    check("la carte numéro (un bot) en dessous : toujours déjà en bas", tk.ramener_menu(G, U, S) == "deja")
    d.humain()
    r2 = tk.ramener_menu(G, U, S)
    c2 = etat()["tickets"][f"{G}:{U}"].get("menu")
    check("la conversation reprend : un nouveau menu en bas, épinglé, l'ancien retiré",
          r2 == "ramene" and c2 != c1 and c1 not in d.messages and c1 not in d.epingles
          and d.fil[-1] == c2 and c2 in d.epingles, (r2, d.fil, d.epingles))

    # la copie suit l'accueil (tickets_discord._api, PATCH des composants)
    nouveaux = [{"type": 1, "components": [
        {"type": 2, "style": 2, "label": "Mon adresse USDC", "custom_id": f"usdc:set:{U}"}]},
        {"type": 1, "components": [
            {"type": 2, "style": 3, "label": "Réactiver le lien", "custom_id": f"lien:on:{U}"}]}]
    tk._api("PATCH", f"/channels/{S}/messages/{ACC}", json={"components": nouveaux})
    check("lien coupé (boutons de l'accueil changés) : le menu du bas suit",
          ids_de(d.messages[c2]["components"]) == [f"usdc:set:{U}", f"lien:on:{U}"], d.messages[c2])
    n = len(d.appels)
    tk._api("PATCH", f"/channels/{S}/messages/{c2}", json={"components": nouveaux})
    tk._api("PATCH", f"/channels/{S}/messages/{ACC}", json={"content": "x"})
    check("… un PATCH sans boutons, ou du menu lui-même : rien de plus",
          len(d.appels) == n + 2, d.appels[n:])

    # « Confirmer le VA » : réponse type 7 sur un des deux, l'autre suit
    apres = [RANGS_ACCUEIL[0], {"type": 1, "components": [RANGS_ACCUEIL[1]["components"][1]]}]
    tk._traiter_sans_copie = lambda p: {"type": 7, "data": {"components": apres}}
    tk.traiter({"type": 3, "channel_id": S, "message": {"id": ACC}, "data": {"custom_id": f"essai:ok:{U}"}})
    check("« Confirmer » cliqué sur l'accueil : le menu du bas perd le bouton aussi",
          f"essai:ok:{U}" not in ids_de(d.messages[c2]["components"]), d.messages[c2])
    d.messages[ACC]["components"] = RANGS_ACCUEIL
    tk.traiter({"type": 3, "channel_id": S, "message": {"id": c2}, "data": {"custom_id": f"essai:ok:{U}"}})
    check("« Confirmer » cliqué sur le menu du bas : l'accueil perd le bouton aussi",
          f"essai:ok:{U}" not in ids_de(d.messages[ACC]["components"]), d.messages[ACC])
    tk._traiter_sans_copie = lambda p: None
    check("… un clic qui n'est pas à nous : None, comme avant", tk.traiter({"type": 3}) is None)
    tk._traiter_sans_copie = _SAUVE["_traiter_sans_copie"]

    check("pas son ticket : echec", tk.ramener_menu(G, U, "4242") == "echec")
    check("pas de fiche : echec", tk.ramener_menu(G, "888", S) == "echec")
    d.humain(); d.refus_post = True
    check("Discord refuse le menu : echec, l'ancien gardé",
          tk.ramener_menu(G, U, S) == "echec" and c2 in d.messages
          and etat()["tickets"][f"{G}:{U}"]["menu"] == c2)
    tk._api_reseau = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("réseau"))
    check("une panne : echec, sans exception", tk.ramener_menu(G, U, S) == "echec")

    for gid, outlook in ((G, ["mailx:menu"]), (tk.AGENCY_IG_ID, [])):
        mp = tk.menu_prive(gid, "55")
        cids = ids_de(mp["data"]["components"])
        check(f"menu privé ({'Twitter' if outlook else 'Agency'}) : la rangée du VA pour lui seul, "
              "sans bouton de manager",
              mp["type"] == 4 and mp["data"]["flags"] == 64 and cids[0] == "usdc:set:55"
              and "numx:menu" in cids and [c for c in cids if c == "mailx:menu"] == outlook
              and not [c for c in cids if c.startswith(tk._BOUTONS_MANAGERS)]
              and all(len(r["components"]) <= 5 for r in mp["data"]["components"]), mp)
except Exception as _e:
    import traceback
    check("menu du ticket : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
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
