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

Et le départ d'un VA (tickets_discord.suivre_departs, une fois l'heure) :
  - absent du serveur (404 « Unknown Member ») : fiche « parti », son lien
    coupé (pas supprimé, ✅ Réactiver sur l'accueil), ses doublons au même nom
    aussi, et seulement eux ; le ticket le dit, sans mentionner personne ;
  - un autre refus ne conclut rien ; un second passage ne refait rien ;
  - revenu : il rentre, son lien reste coupé ;
  - le podium le sort des périodes qui vont jusqu'à son départ, pas des
    semaines d'avant ; sa prime n'est pas annoncée (suivi_va).

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

    # ── le départ d'un VA ────────────────────────────────────────────────
    import types
    import datetime as dt
    import liens_va as lv
    import podium_discord as pd
    import suivi_va as sv
    _SAUVE_LV = {k: getattr(lv, k) for k in ("ETAT_FICHIER", "espace")}
    _SAUVE_GMS = sys.modules.get("gms")
    _SAUVE_SV = sv.ETAT_FICHIER
    try:
        lv.ETAT_FICHIER = TMP / "liens_va.json"
        lv.espace = lambda gid="": {"equipe": "tm_th", "plateforme": "Threads"}
        nom83 = "Threads VA 83 @fabiano.18_"
        lv.ETAT_FICHIER.write_text(json.dumps({"liens": {
            f"{G}:83": {"pseudo": "fabiano.18_", "numero": 83, "link_id": "lnk_b",
                        "shortcode": "babebbyy", "public_url": "https://getmysocial.com/babebbyy"},
            f"{G}:80": {"pseudo": "2xdeux", "numero": 80, "link_id": "lnk_o",
                        "shortcode": "otheryy", "public_url": "https://getmysocial.com/otheryy"}}}),
            encoding="utf-8")
        g = types.ModuleType("gms")
        g.liens = [{"id": "lnk_b", "display_name": nom83, "status": "active", "shortcode": "babebbyy"},
                   {"id": "lnk_p", "display_name": nom83, "status": "active", "shortcode": "pearlkittyy"},
                   {"id": "lnk_o", "display_name": "Threads VA 80 @2xdeux", "status": "active",
                    "shortcode": "otheryy"}]
        g.coupes = []

        def _statut(lid, actif):
            g.coupes.append((lid, actif))
            for x in g.liens:
                if x["id"] == lid:
                    x["status"] = "active" if actif else "inactive"
            return {"ok": True}
        g.disable_link = lambda lid: _statut(lid, False)
        g.enable_link = lambda lid: _statut(lid, True)
        g.list_links_team = lambda team, force_refresh=False: {"ok": True, "links": copy.deepcopy(g.liens)}
        sys.modules["gms"] = g
        tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
            f"{G}:83": {"salon": "s83", "manager": "999", "accueil": "a83", "confirme": True},
            f"{G}:80": {"salon": "s80", "manager": "999", "accueil": "a80"},
            f"{G}:81": {"salon": "s81", "manager": "999", "accueil": "a81"}}}), encoding="utf-8")
        membres = {"83": 404, "80": 200, "81": 500}
        d2 = FauxDiscord()
        d2.msgs = {"s83": {"a83": accueil("a83", "83", "999", True)}, "s80": {}, "s81": {}}
        d2.salons.update({"s83": 200, "s80": 200, "s81": 200})
        _vrai_api = d2.api

        def api2(methode, chemin, **kw):
            p_ = chemin.strip("/").split("/")
            if p_[0] == "guilds" and p_[2] == "members":
                d2.appels.append((methode, chemin, None))
                c = membres[p_[3]]
                return c, ({"code": 10007, "message": "Unknown Member"} if c == 404 else
                           {"user": {"id": p_[3]}} if c == 200 else {"message": "panne"})
            if methode == "POST" and p_[2] == "messages":
                d2.appels.append((methode, chemin, kw.get("json")))
                return 200, {"id": "m"}
            return _vrai_api(methode, chemin, **kw)
        tk._api = api2
        b3 = tk.suivre_departs(G)
        etat = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))
        f83 = etat["tickets"][f"{G}:83"]
        check("départ (404 Unknown Member) : fiche marquée « parti », les autres non",
              b3["partis"] == ["83"] and isinstance(f83.get("parti"), dict)
              and not etat["tickets"][f"{G}:80"].get("parti")
              and "81 (HTTP 500)" in b3["illisibles"] and not etat["tickets"][f"{G}:81"].get("parti"), b3)
        check("… son lien coupé, pas supprimé, et son doublon au même nom (pearlkittyy) aussi",
              ("lnk_b", False) in g.coupes and ("lnk_p", False) in g.coupes
              and not [c for c in g.coupes if c[0] == "lnk_o"]
              and not lv.est_actif(G, "83"), g.coupes)
        msg = [j for (m_, c_, j) in d2.appels if m_ == "POST" and c_ == "/channels/s83/messages"]
        check("… le ticket le dit, sans mentionner personne : parti, lien réactivable, salon gardé",
              msg and "a quitté le serveur" in msg[0]["content"] and "Réactiver le lien" in msg[0]["content"]
              and msg[0]["allowed_mentions"] == {"parse": []}, msg)
        a83 = d2.msgs["s83"]["a83"]
        boutons = [b_["custom_id"] for r_ in a83.get("components") or [] for b_ in r_["components"]]
        check("… l'accueil marqué « 👋 Parti », bouton ✅ Réactiver à la place de 🚫",
              tk.MARQUE_PARTI in a83["embeds"][0]["description"]
              and "lien:on:83" in boutons and "lien:off:83" not in boutons, (a83, boutons))
        n = len(g.coupes)
        n_post = len([a_ for a_ in d2.appels if a_[0] == "POST"])
        tk.suivre_departs(G)
        check("un second passage ne refait rien",
              len(g.coupes) == n and len([a_ for a_ in d2.appels if a_[0] == "POST"]) == n_post)

        # le podium : sorti des périodes qui vont jusqu'à son départ
        auj = dt.date.today()
        cl = {"lignes": [{"va": "Threads 83", "numero": 83, "clics": 54},
                         {"va": "Threads 80", "numero": 80, "clics": 15}],
              "illisibles": ["Threads 83"], "frais": True}
        cl_v = pd._sans_partis(G, cl, auj)
        cl_p = pd._sans_partis(G, cl, auj - dt.timedelta(days=3))
        check("podium en cours : VA 83 retiré des lignes et des sans-relevé, et noté",
              [x["va"] for x in cl_v["lignes"]] == ["Threads 80"] and cl_v["illisibles"] == []
              and cl_v["partis"] == ["Threads 83"], cl_v)
        check("… une semaine finie avant son départ le garde", cl_p == cl, cl_p)
        check("… Twitter, sans VA parti, n'est pas touché",
              pd._sans_partis("1445108485090971710", cl, auj) == cl)

        # sa prime : pas annoncée
        sv.ETAT_FICHIER = TMP / "suivi_va.json"
        n_post = len([a_ for a_ in d2.appels if a_[0] == "POST"])
        bp = sv.annoncer_primes(G, {"lignes": [{"va": "Threads 83", "clics": 54},
                                               {"va": "Threads 80", "clics": 15}]},
                                auj - dt.timedelta(days=9), auj - dt.timedelta(days=3))
        posts = [a_ for a_ in d2.appels if a_[0] == "POST"][n_post:]
        check("prime d'un VA parti : annulée, pas annoncée ; le 2e garde la sienne",
              bp.get("partis") == ["fabiano.18_"] and [c_ for (_m, c_, _j) in posts] == ["/channels/s80/messages"]
              and "5.00$" in str(posts[0][2]), (bp, posts))

        # il revient
        membres["83"] = 200
        b4 = tk.suivre_departs(G)
        etat = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))
        a83 = d2.msgs["s83"]["a83"]
        check("revenu : plus « parti », marque retirée de l'accueil, son lien reste coupé",
              b4["revenus"] == ["83"] and not etat["tickets"][f"{G}:83"].get("parti")
              and etat["tickets"][f"{G}:83"].get("revenu")
              and tk.MARQUE_PARTI not in a83["embeds"][0]["description"]
              and not lv.est_actif(G, "83") and ("lnk_b", True) not in g.coupes, (b4, g.coupes))
        check("… et il rentre au classement", pd._sans_partis(G, cl, auj) == cl)
        src = inspect.getsource(tk.suivre_partout)
        check("branché dans suivre_partout, une fois l'heure",
              "suivre_departs(gid)" in src and "DEPARTS_S" in src)

        # Va IG : ses VA partis (cogs/welcome.py les note dans
        # pending_deletions.json) ont leurs liens coupés comme un rôle retiré
        import liens_fr
        _sauve_fr = {k: getattr(liens_fr, k) for k in ("PARTIS", "ETAT", "_liens_equipe")}
        try:
            liens_fr.PARTIS = TMP / "pending_deletions.json"
            liens_fr.ETAT = TMP / "liens_va_fr.json"
            liens_fr.PARTIS.write_text(json.dumps({
                "881568604557037628": {"channel_id": 1, "guild_id": int(liens_fr.VA_IG),
                                       "delete_at": "2026-10-21T20:12:05+00:00", "user_name": "3usg"},
                "42": {"channel_id": 2, "guild_id": 999, "user_name": "ailleurs"}}), encoding="utf-8")
            fr = [{"id": "lnk_fr1", "display_name": "Amelia VA 3 @3usg", "status": "active"},
                  {"id": "lnk_fr2", "display_name": "Amelia VA 5 @ailleurs", "status": "active"},
                  {"id": "lnk_fr3", "display_name": "Lola VA 7 @quelquun", "status": "active"}]
            liens_fr._liens_equipe = lambda force=False, strict=False: fr
            g.coupes.clear()
            faits = liens_fr.couper_partis()
            check("Va IG : le lien du VA parti (3usg) coupé, pas ceux des autres ni d'un autre serveur",
                  [(f_["nom"], f_["actif"], f_["ok"]) for f_ in faits] == [("Amelia VA 3 @3usg", False, True)]
                  and g.coupes == [("lnk_fr1", False)], (faits, g.coupes))
            reg_fr = json.loads(liens_fr.ETAT.read_text(encoding="utf-8"))
            check("… noté dans « coupes_role » : rendu tout seul s'il revient avec ses rôles",
                  "lnk_fr1" in (reg_fr.get("coupes_role") or {}), reg_fr)
            check("branché dans suivre_partout, une fois l'heure",
                  "liens_fr.couper_partis()" in inspect.getsource(tk.suivre_partout))
        finally:
            for _k, _v in _sauve_fr.items():
                setattr(liens_fr, _k, _v)
    finally:
        for _k, _v in _SAUVE_LV.items():
            setattr(lv, _k, _v)
        sv.ETAT_FICHIER = _SAUVE_SV
        if _SAUVE_GMS is not None:
            sys.modules["gms"] = _SAUVE_GMS
        else:
            sys.modules.pop("gms", None)
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
