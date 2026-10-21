# -*- coding: utf-8 -*-
"""tests_verif_relances.py — relance des alertes de vérification restées sans
décision, et ce qu'on promet au membre une fois validé.

Rien ne part vers Discord : verif_discord.api est remplacé par un serveur en
mémoire, data/ par un dossier temporaire. Les alertes sont datées par leur
identifiant, comme les vraies.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verif_discord as vd

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:300]}]"))


def snowflake(ts: float) -> str:
    return str((int(ts * 1000) - 1420070400000) << 22)


TW = vd.TWITTER_ID
CFG = vd.serveur(TW)
MAINTENANT = time.time()
JOUR = 86400
A, RECENT, PARTI, VERIFIE, TRANCHE, SUSPECT = (f"70000000000000000{i}" for i in range(1, 7))


def alerte(uid, age_j, boutons=True):
    return {"id": snowflake(MAINTENANT - age_j * JOUR), "embeds": [{"title": "⏳ En attente d'un manager"}],
            "components": [{"type": 1, "components": [
                {"type": 2, "custom_id": f"verif:ok:{uid}"}, {"type": 2, "custom_id": f"verif:ban:{uid}"}]}]
            if boutons else []}


ATTENTE = [alerte(A, 3), alerte(RECENT, 1), alerte(PARTI, 5), alerte(VERIFIE, 4), alerte(TRANCHE, 6, boutons=False),
           {"id": snowflake(MAINTENANT - 9 * JOUR), "content": "un message du staff, sans bouton"}]
SUSPICIONS = [alerte(SUSPECT, 6)]
MEMBRES = {A: [CFG["role_attente"]], RECENT: [CFG["role_attente"]], VERIFIE: [CFG["role_verifie"]],
           TRANCHE: [CFG["role_verifie"]], SUSPECT: ["1552474724615852132", CFG["role_suspect"]]}
APPELS = []
POST_CODE = {"v": 200}


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw.get("json"), vd.serveur_courant()))
    if methode == "GET" and chemin.startswith(f"/channels/{CFG['salon_attente']}/messages"):
        return 200, [dict(m) for m in ATTENTE]
    if methode == "GET" and chemin.startswith(f"/channels/{CFG['salon_suspicions']}/messages"):
        return 200, [dict(m) for m in SUSPICIONS]
    if methode == "GET" and chemin.startswith(f"/guilds/{TW}/members/"):
        uid = chemin.rsplit("/", 1)[1]
        return (200, {"roles": MEMBRES[uid]}) if uid in MEMBRES else (404, {"message": "Unknown Member"})
    if methode == "POST" and chemin.startswith("/channels/"):
        return POST_CODE["v"], ({"id": "relance1"} if POST_CODE["v"] == 200 else {"message": "Missing Access"})
    return 404, {}


def postes():
    return [(c, j) for m, c, j, _ in APPELS if m == "POST"]


_dT = Path(tempfile.mkdtemp())
SAV = (vd.api, vd.DATA_DIR, vd.RELANCES)
try:
    vd.api = faux_api
    vd.DATA_DIR, vd.RELANCES = _dT, _dT / "verif_relances.json"

    # ─── l'heure d'une alerte vient de son identifiant ───
    check("date d'un message lue dans son identifiant",
          abs(vd._date_message(snowflake(MAINTENANT - 3 * JOUR)) - (MAINTENANT - 3 * JOUR)) < 0.01)

    # ─── premier passage ───
    POST_CODE["v"] = 500
    b = vd.relancer_alertes(TW, maintenant=MAINTENANT)
    check("relance refusée par Discord : rien de noté, échec remonté",
          not b["relancees"] and any("refusée" in e for e in b["echecs"])
          and ATTENTE[0]["id"] not in vd._relances(), b)
    check("membre parti et membre déjà vérifié : pas de relance, raison gardée",
          b["sans_relance"] == {PARTI: "parti du serveur", VERIFIE: "déjà vérifié à la main dans Discord"}, b)
    APPELS.clear()
    POST_CODE["v"] = 200
    b = vd.relancer_alertes(TW, maintenant=MAINTENANT)
    p = postes()
    check("deux relances : la demande de 3 jours et l'alerte fraude de 6 jours",
          sorted(b["relancees"]) == sorted([ATTENTE[0]["id"], SUSPICIONS[0]["id"]]) and len(p) == 2, b)
    check("l'alerte de 1 jour attend encore", b["recentes"] == 1, b)
    check("… et ils ne sont pas relus au passage suivant", b["deja"] == 2 and not b["sans_relance"], b)
    check("alerte tranchée (boutons retirés) et message sans bouton : ignorés",
          not any(TRANCHE in (j or {}).get("content", "") for _, j in p))
    check("chaque relance part avec le bot du serveur", all(s == TW for m, _, _, s in APPELS if m == "POST"))
    (c1, j1), (c2, j2) = p
    check("relance postée DANS le salon de l'alerte, en réponse à l'alerte",
          c1 == f"/channels/{CFG['salon_attente']}/messages"
          and j1["message_reference"]["message_id"] == ATTENTE[0]["id"]
          and c2 == f"/channels/{CFG['salon_suspicions']}/messages"
          and j2["message_reference"]["message_id"] == SUSPICIONS[0]["id"], (c1, c2))
    check("le rôle manager est mentionné, et lui seul (le membre n'est pas notifié)",
          j1["content"].startswith(f"<@&{CFG['role_manager']}>")
          and j1["allowed_mentions"] == {"roles": [CFG["role_manager"]]}, j1)
    check("texte : depuis combien de jours, qui, et les boutons laissés aux managers",
          "Demande d'accès sans décision depuis 3 jours" in j1["content"] and f"<@{A}>" in j1["content"]
          and "Accepter" in j1["content"] and "Bannir" in j1["content"], j1["content"])
    check("dans 🚩 suspicions, elle dit « Alerte fraude »",
          "Alerte fraude sans décision depuis 6 jours" in j2["content"], j2["content"])
    f = vd._relances()
    check("relances notées dans data/verif_relances.json",
          f.get(ATTENTE[0]["id"], {}).get("relance") == "relance1"
          and f.get(ATTENTE[2]["id"], {}).get("sans_relance") == "parti du serveur", f)

    # ─── une seule fois par alerte ───
    APPELS.clear()
    b = vd.relancer_alertes(TW, maintenant=MAINTENANT + 3 * JOUR)
    check("second passage, trois jours plus tard : aucune nouvelle relance pour les mêmes alertes",
          [x for x in b["relancees"] if x != ATTENTE[1]["id"]] == [] and b["deja"] == 4, b)
    check("… et l'alerte d'hier, devenue vieille de 4 jours, a la sienne",
          b["relancees"] == [ATTENTE[1]["id"]], b)
    APPELS.clear()
    b = vd.relancer_alertes(TW, maintenant=MAINTENANT + 4 * JOUR)
    check("troisième passage : plus rien à poster", postes() == [] and b["deja"] == 5, b)

    # ─── fichier impossible à écrire : on ne poste pas ───
    ATTENTE.append(alerte("700000000000000099", 3.5))   # 3 j pile : même id que A
    MEMBRES["700000000000000099"] = [CFG["role_attente"]]
    sav_ecrire = vd._ecrire_relances
    vd._ecrire_relances = lambda d: False
    APPELS.clear()
    b = vd.relancer_alertes(TW, maintenant=MAINTENANT)
    vd._ecrire_relances = sav_ecrire
    check("fichier des relances non écrit : rien n'est posté (sinon une relance à chaque tour)",
          postes() == [] and b["echecs"], b)

    # ─── la boucle ne s'arme que sur la machine qui poste ───
    sav_env = os.environ.pop("VA_MACHINE_PROD", None)
    check("pas de VA_MACHINE_PROD : relances non armées", vd.armer_relances() is False)
    if sav_env is not None:
        os.environ["VA_MACHINE_PROD"] = sav_env
    check("Entretien n'est pas relancé (ses alertes attendent l'entretien)",
          vd.GUILD_ID not in vd.RELANCE_SERVEURS and TW in vd.RELANCE_SERVEURS)

    # ─── ce qu'on promet au membre ───
    for gid in (TW, vd.THREADS_ID, vd.VA_IG_ID, vd.GUILD_ID):
        t = vd._apres_validation(vd.serveur(gid))
        check(f"{vd.serveur(gid)['nom']} : plus de promesse « #bienvenue »", "bienvenue" not in t.lower(), t)
    check("Twitter : c'est son salon perso qui s'ouvre",
          "salon perso" in vd._apres_validation(CFG), vd._apres_validation(CFG))
    check("Entretien (sans ticket) : c'est le serveur qui s'ouvre",
          "serveur" in vd._apres_validation(vd.serveur(vd.GUILD_ID)))
    e = vd.embed_panneau(CFG)
    check("panneau Twitter : le bon serveur, pas Threads",
          "**YouLab TWITTER**" in e["description"] and "THREADS" not in e["description"], e["description"])
    check("panneau : pas de #bienvenue, le salon perso et l'entretien",
          "#bienvenue" not in e["description"] and "salon perso" in e["description"]
          and "Entretiens" in e["description"], e["description"])
    check("panneau Threads : son propre nom", "**YouLab THREADS**" in vd.embed_panneau(vd.serveur(vd.THREADS_ID))["description"])
    APPELS.clear()
    code = vd.reediter_panneau(TW, "1552192942385537034", "1552194412933816364")
    m, c, j, s = APPELS[-1]
    check("réédition du panneau : PATCH du message, embed seul (le bouton n'est pas touché), bot de Twitter",
          m == "PATCH" and c == "/channels/1552192942385537034/messages/1552194412933816364"
          and set(j) == {"embeds", "allowed_mentions"} and s == TW, (m, c, j, s))
finally:
    vd.api, vd.DATA_DIR, vd.RELANCES = SAV

print(f"\n{len(OK)} OK, {len(KO)} échec(s)")
sys.exit(1 if KO else 0)
