# -*- coding: utf-8 -*-
"""tests_niveaux_va.py — 🧪 Essai › 🌱 Débutant › ⭐ Confirmé dans le menu des tickets.

Propriétaire, 24/10/2026 : « de base il est en essai ; à la place de passer
direct confirmé, passe débutant, et quand il est débutant il y a le bouton
confirmer ». Twitter, Threads, Agency (NIVEAUX_ICI).

Ce qui est vérifié :
  - la rangée des managers : « 🌱 Passer Débutant » pour un VA en essai,
    « ⭐ Confirmer le VA » pour un débutant, rien pour un confirmé ; ailleurs
    (autre serveur) rien ne change ; pas de bouton de niveau dans le menu
    privé ;
  - le clic « Passer Débutant » : 🌱 posé puis 🧪 retiré, fiche « debutant »,
    réponse type 7 avec « Confirmer » à la place, l'encart perd sa ligne
    d'essai ; refusé à un VA, sans rôle 🌱 sur le serveur : dit ;
  - un vieux « Confirmer » cliqué sur un VA en essai le fait passer débutant ;
    sur un débutant : le chemin de confirmation d'avant ;
  - confirmer retire aussi 🌱 Débutant ;
  - un niveau posé À LA MAIN (synchroniser_niveaux, au tour des tickets) :
    le plus haut porté décide, ceux du dessous sont retirés, la fiche suit et
    le menu est redessiné ; rien sans rôle de niveau, ni liste illisible.

Faux Discord, dossier temporaire : aucun appel réseau, rien dans data/.
Lancement : python tests_niveaux_va.py
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

import liens_va as lv                  # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


TW, AG = "1445108485090971710", tk.AGENCY_IG_ID
TMP = pathlib.Path(tempfile.mkdtemp(prefix="niveaux_va_"))
_SAUVE = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "_api_reseau", "_en_fond", "_traiter_sans_niveaux")}
_SAUVE_LV = (lv.lien_de, lv.est_actif)
ROLES = [{"id": "r_essai", "name": "🧪 Essai"}, {"id": "r_deb", "name": "🌱 Débutant"},
         {"id": "r_conf", "name": "⭐ Confirmé"}]
appels = []


MEMBRES = {"ok": True, "m": []}


def faux_api(methode, chemin, **kw):
    appels.append((methode, chemin))
    if methode == "GET" and chemin.endswith("/roles"):
        return 200, list(ROLES)
    if methode == "GET" and chemin.endswith("/members"):
        return (200, list(MEMBRES["m"])) if MEMBRES["ok"] else (403, {})
    if methode in ("PUT", "DELETE") and "/roles/" in chemin:
        _g, _sep, reste = chemin.partition("/members/")
        uid, _r, rid = reste.partition("/roles/")
        for m in MEMBRES["m"]:
            if m["user"]["id"] == uid:
                if methode == "DELETE" and rid in m["roles"]:
                    m["roles"].remove(rid)
                elif methode == "PUT" and rid not in m["roles"]:
                    m["roles"].append(rid)
        return 204, {}
    return 200, {}


def ids(rangs):
    return [b.get("custom_id") for r in rangs for b in r.get("components") or []]


def ecrire(fiches):
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": fiches}), encoding="utf-8")


def fiche(cle):
    return json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))["tickets"][cle]


try:
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk._api_reseau = faux_api
    tk._en_fond = lambda f: f()
    lv.lien_de = lambda gid, uid: {"public_url": "https://getmysocial.com/x"}
    lv.est_actif = lambda gid, uid: True
    ecrire({f"{TW}:1": {"salon": "s1", "accueil": "a1", "essai": True},
            f"{TW}:2": {"salon": "s2", "accueil": "a2", "debutant": {"par": "m"}},
            f"{TW}:3": {"salon": "s3", "accueil": "a3", "confirme": {"par": "m"}},
            f"{AG}:4": {"salon": "s4", "accueil": "a4", "essai": True}})

    r1 = ids(tk.boutons_va("1", confirme=False, a_un_lien=True, gid=TW))
    check("VA en essai : « 🌱 Passer Débutant », plus « Confirmer »",
          "essai:deb:1" in r1 and "essai:ok:1" not in r1, r1)
    b = [x for r in tk.boutons_va("1", confirme=False, a_un_lien=True, gid=TW)
         for x in r["components"] if x.get("custom_id") == "essai:deb:1"][0]
    check("… le bouton : 🌱 Passer Débutant", (b["label"], b["emoji"]) == ("Passer Débutant", {"name": "🌱"}), b)
    r2 = ids(tk.boutons_va("2", confirme=False, a_un_lien=True, gid=TW))
    check("VA débutant : « ⭐ Confirmer le VA »", "essai:ok:2" in r2 and "essai:deb:2" not in r2, r2)
    r3 = ids(tk.boutons_va("3", confirme=True, a_un_lien=True, gid=TW))
    check("VA confirmé : plus de bouton de niveau",
          not [c for c in r3 if c.startswith("essai:")], r3)
    check("Agency aussi", "essai:deb:4" in ids(tk.boutons_va("4", confirme=False, a_un_lien=True, gid=AG)))
    autre = ids(tk.boutons_va("1", confirme=False, a_un_lien=True, gid="99"))
    check("un autre serveur : « Confirmer » comme avant", "essai:ok:1" in autre and "essai:deb:1" not in autre,
          autre)
    rg = tk.boutons_va("1", confirme=False, a_un_lien=True, gid=TW)
    check("… dans la rangée des managers", "essai:deb:1" in ids(rg[-1:]) and "essai:deb:1" not in ids(rg[:1]),
          [ids([r]) for r in rg])
    check("menu privé : pas de bouton de niveau",
          not [c for c in ids(tk.menu_prive(TW, "1")["data"]["components"]) if c.startswith("essai:")])

    mgr = {"user": {"id": "m9"}, "permissions": "8", "roles": []}
    clic = {"type": 3, "guild_id": TW, "channel_id": "s1", "member": mgr,
            "message": {"id": "a1", "content": "<@1>", "embeds": [
                {"description": "Bienvenue\n🧪 **Tu démarres en essai.** blabla\nfin"}]},
            "data": {"custom_id": "essai:deb:1"}}
    appels.clear()
    rep = tk.traiter(clic)
    f1 = fiche(f"{TW}:1")
    poses = [a for a in appels if a[0] in ("PUT", "DELETE")]
    check("clic « Passer Débutant » : 🌱 posé PUIS 🧪 retiré, fiche débutant",
          poses == [("PUT", f"/guilds/{TW}/members/1/roles/r_deb"),
                    ("DELETE", f"/guilds/{TW}/members/1/roles/r_essai")]
          and f1.get("debutant", {}).get("par") == "m9" and f1.get("essai") is False, (poses, f1))
    check("… réponse type 7 : « Confirmer » à la place, l'encart perd sa ligne d'essai, sans mention",
          rep["type"] == 7 and "essai:ok:1" in ids(rep["data"]["components"])
          and "essai:deb:1" not in ids(rep["data"]["components"])
          and "démarres en essai" not in rep["data"]["embeds"][0]["description"]
          and "🌱 **VA débutant** — par <@m9>." in rep["data"]["embeds"][0]["description"]
          and rep["data"]["allowed_mentions"] == {"parse": []}, rep)
    check("… redemandé : « déjà débutant »", "déjà débutant" in tk.traiter(clic)["data"]["content"])
    va = dict(clic, member={"user": {"id": "1"}, "permissions": "0", "roles": []})
    ecrire({f"{TW}:1": {"salon": "s1", "accueil": "a1", "essai": True}})
    check("un VA qui clique : refusé", "Seuls les managers" in tk.traiter(va)["data"]["content"]
          and not fiche(f"{TW}:1").get("debutant"))
    ROLES[1] = {"id": "r_deb", "name": "autre chose"}
    check("pas de rôle 🌱 Débutant sur le serveur : dit, rien changé",
          "introuvable" in tk.traiter(clic)["data"]["content"] and not fiche(f"{TW}:1").get("debutant"))
    ROLES[1] = {"id": "r_deb", "name": "🌱 Débutant"}

    vieux = dict(clic, data={"custom_id": "essai:ok:1"})
    rv = tk.traiter(vieux)
    check("vieux « Confirmer » sur un VA en essai : il passe débutant (une étape à la fois)",
          rv["type"] == 7 and fiche(f"{TW}:1").get("debutant") and not fiche(f"{TW}:1").get("confirme"), rv)
    vus = []
    tk._traiter_sans_niveaux = lambda p: vus.append(p["data"]["custom_id"]) or {"type": 4, "data": {}}
    tk.traiter(vieux)
    check("… « Confirmer » sur un débutant : le chemin de confirmation d'avant", vus == ["essai:ok:1"], vus)
    tk._traiter_sans_niveaux = _SAUVE["_traiter_sans_niveaux"]

    appels.clear()
    rc = tk.confirmer(TW, "1", par="m9")
    check("confirmer : ⭐ posé, 🧪 retiré, 🌱 retiré aussi",
          rc["ok"] and ("PUT", f"/guilds/{TW}/members/1/roles/r_conf") in appels
          and ("DELETE", f"/guilds/{TW}/members/1/roles/r_deb") in appels
          and fiche(f"{TW}:1").get("confirme"), appels)
    check("BOUTONS_VERSION à 9 : les menus postés sont redessinés", tk.BOUTONS_VERSION >= 9)

    # ── le rôle posé à la main ────────────────────────────────────────────
    ecrire({f"{TW}:5": {"salon": "s5", "accueil": "a5", "essai": True},
            f"{TW}:6": {"salon": "s6", "accueil": "a6", "confirme": {"par": "m"}},
            f"{TW}:7": {"salon": "s7", "accueil": "a7", "essai": True},
            f"{TW}:8": {"salon": "s8", "accueil": "a8", "debutant": {"par": "m"}},
            f"{TW}:9": {"salon": "s9", "accueil": "a9", "essai": True}})
    MEMBRES["m"] = [{"user": {"id": "5"}, "roles": ["r_essai", "r_conf"]},     # deux niveaux à la main
                    {"user": {"id": "6"}, "roles": ["r_deb"]},                # rétrogradé à la main
                    {"user": {"id": "7"}, "roles": ["r_essai"]},              # rien n'a changé
                    {"user": {"id": "8"}, "roles": []}]                       # aucun rôle de niveau
    appels.clear()
    bn = tk.synchroniser_niveaux(TW)
    suivis = {u: (a, n) for u, a, n in bn["suivis"]}
    check("Essai + Confirmé posés à la main : confirmé, 🧪 retiré, fiche et menu suivent",
          suivis.get("5") == ("essai", "confirme") and ("5", "essai") in bn["nettoyes"]
          and ("DELETE", f"/guilds/{TW}/members/5/roles/r_essai") in appels
          and fiche(f"{TW}:5").get("confirme") and fiche(f"{TW}:5").get("essai") is False
          and ("PATCH", "/channels/s5/messages/a5") in appels, (bn, appels))
    check("Confirmé remplacé par 🌱 à la main : débutant, la fiche perd « confirme », menu « Confirmer »",
          suivis.get("6") == ("confirme", "debutant") and not fiche(f"{TW}:6").get("confirme")
          and fiche(f"{TW}:6").get("debutant"), bn)
    check("rien de changé, ou aucun rôle de niveau, ou parti : rien touché",
          "7" not in suivis and "8" not in suivis and "9" not in suivis
          and fiche(f"{TW}:8").get("debutant") and ("PATCH", "/channels/s7/messages/a7") not in appels, bn)
    n = len(appels)
    check("second passage : plus rien à faire", not tk.synchroniser_niveaux(TW)["suivis"]
          and not [a for a in appels[n:] if a[0] in ("PATCH", "DELETE", "PUT")], appels[n:])
    MEMBRES["ok"] = False
    check("liste des membres illisible : rien touché", tk.synchroniser_niveaux(TW)["ignore"])
    MEMBRES["ok"] = True
    ROLES[1] = {"id": "r_deb", "name": "autre"}
    check("un rôle de niveau introuvable : rien touché, dit", tk.synchroniser_niveaux(TW)["ignore"])
    ROLES[1] = {"id": "r_deb", "name": "🌱 Débutant"}
    import inspect
    check("branché au tour des tickets (Twitter, Threads, Agency)",
          "synchroniser_niveaux(gid)" in inspect.getsource(tk.suivre_partout))
except Exception as _e:
    import traceback
    check("niveaux : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(tk, _k, _v)
    lv.lien_de, lv.est_actif = _SAUVE_LV
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
