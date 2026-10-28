"""Cartes ⏸️ Suspension temporaire : raison lue dans l'audit, bouton ▶️ Lever.

    python tests_suspensions.py

Aucun appel à Discord : verif_discord.api est remplacé par un faux qui rejoue
les réponses vues sur TRUST TWITTER le 28/10/2026.
"""
import time

import suspensions_discord as su
import verif_discord as v

G = "1445108485090971710"
UID = "1494993640173338644"
MANAGER_ROLE = v.serveur(G)["role_manager"]
OK = ECHECS = 0


def verifier(nom, cond):
    global OK, ECHECS
    if cond:
        OK += 1
        print("OK  ", nom)
    else:
        ECHECS += 1
        print("ECHEC", nom)


def snowflake(t):
    return str((int(t * 1000) - 1420070400000) << 22)


class Faux:
    def __init__(self, auto=(), main=(), membre_fin=None, code_patch=200, code_membre=200):
        self.auto, self.main = list(auto), list(main)
        self.membre_fin, self.code_patch, self.code_membre = membre_fin, code_patch, code_membre
        self.appels = []

    def __call__(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw))
        if chemin.endswith("/auto-moderation/rules"):
            return 200, [{"name": "Anti-arnaque", "actions": [
                {"type": 1, "metadata": {"custom_message": "Message bloqué : il ressemble à une arnaque."}},
                {"type": 3, "metadata": {"duration_seconds": 600}}]}]
        if chemin.endswith("/audit-logs"):
            t = kw["params"]["action_type"]
            return 200, {"audit_log_entries": self.auto if t == 145 else self.main}
        if methode == "GET" and "/members/" in chemin:
            if self.code_membre != 200:
                return self.code_membre, {}
            return 200, {"communication_disabled_until": self.membre_fin}
        if methode == "PATCH" and "/members/" in chemin:
            return self.code_patch, {}
        if chemin.startswith("/webhooks/"):
            return 200, {}
        return 404, {}


def avec(faux):
    v.api = faux
    su._REGLES.clear()
    return faux


maintenant = time.time()
entree_auto = {"id": snowflake(maintenant - 30), "target_id": UID, "user_id": UID,
               "options": {"auto_moderation_rule_name": "Anti-arnaque", "channel_id": "1562235373147394159"}}
entree_staff = {"id": snowflake(maintenant - 20), "target_id": UID, "user_id": "479005370438778891",
                "reason": "spam en salon", "changes": [{"key": "communication_disabled_until",
                                                        "new_value": "2026-10-28T12:00:00+00:00"}]}
levee_staff = {"id": snowflake(maintenant - 10), "target_id": UID, "user_id": "479005370438778891",
               "changes": [{"key": "communication_disabled_until", "old_value": "x"}]}

# ── raison ──
avec(Faux(auto=[entree_auto]))
r = su.raison(G, UID, maintenant)
verifier("AutoMod : nom de la règle", "« Anti-arnaque »" in r)
verifier("AutoMod : le message montré au membre", "il ressemble à une arnaque" in r)
verifier("AutoMod : le salon", "<#1562235373147394159>" in r)

avec(Faux(main=[entree_staff, levee_staff]))
r = su.raison(G, UID, maintenant)
verifier("staff : qui a suspendu", "<@479005370438778891>" in r)
verifier("staff : sa raison", "spam en salon" in r)

avec(Faux(auto=[entree_auto], main=[entree_staff]))
verifier("la plus récente des deux l'emporte", "Suspendu par" in su.raison(G, UID, maintenant))

avec(Faux(main=[levee_staff]))
verifier("une levée n'est pas une raison", "introuvable" in su.raison(G, UID, maintenant))

vieille = dict(entree_auto, id=snowflake(maintenant - 3 * 3600))
avec(Faux(auto=[vieille]))
verifier("une vieille suspension n'est pas reprise", "introuvable" in su.raison(G, UID, maintenant))

autre = dict(entree_auto, target_id="1")
avec(Faux(auto=[autre]))
verifier("la suspension d'un autre membre n'est pas reprise", "introuvable" in su.raison(G, UID, maintenant))


class Refus(Faux):
    def __call__(self, methode, chemin, **kw):
        return (403, {}) if chemin.endswith("/audit-logs") else super().__call__(methode, chemin, **kw)


avec(Refus())
verifier("audit refusé : dit, pas tu", "HTTP 403" in su.raison(G, UID, maintenant))

# ── completer : la carte telle que membres_evenements l'écrit ──
fin = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(maintenant + 600))
passe = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(maintenant - 60))


def carte_me(kind="suspendu", fin_ts=maintenant + 600):
    titres = {"suspendu": "⏸️ Suspension temporaire", "retabli": "▶️ Suspension levée", "depart": "👋 Un membre a quitté le serveur"}
    libelles = {"suspendu": "Suspension temporaire", "retabli": "Suspension levée", "depart": "Départ du serveur"}
    desc = f"<@{UID}> · `@bigmaxm`\n\nDiscord indique une exclusion temporaire (timeout)."
    if kind == "suspendu":
        desc += f"\nFin prévue : <t:{int(fin_ts)}:F>."
    return {"embeds": [{"title": titres[kind], "description": desc,
                        "footer": {"text": f"YouLab Twitter • {libelles[kind]}"}}],
            "allowed_mentions": {"parse": []}, "nonce": "k", "enforce_nonce": True}


avec(Faux(auto=[entree_auto]))
corps = carte_me()
verifier("completer : carte ⏸️ reconnue", su.completer(corps, G) is True)
verifier("completer : la raison sous le texte", "Anti-arnaque" in corps["embeds"][0]["description"]
         and corps["embeds"][0]["description"].startswith(f"<@{UID}>"))
verifier("completer : le bouton", corps.get("components", [{}])[0]["components"][0]["custom_id"] == f"susp:lever:{UID}")
corps = carte_me(fin_ts=maintenant - 60)
su.completer(corps, G)
verifier("completer : pas de bouton sur une suspension déjà finie", "components" not in corps)
for kind in ("retabli", "depart"):
    corps = carte_me(kind)
    avant = repr(corps)
    verifier(f"completer : carte {kind} laissée telle quelle", su.completer(corps, G) is False and repr(corps) == avant)
verifier("completer : un message sans encadré passe", su.completer({"content": "x"}, G) is False)

# ── brancher : sur une copie du membres_evenements du VPS (son publier) ──
import sys
import types

envois = []
faux_me = types.ModuleType("membres_evenements")
faux_me.api = lambda g, methode, chemin, **kw: (envois.append((methode, chemin, kw)) or (200, {"id": "9"}))


def publier(g, corps):                    # ce que fait membres_evenements.publier
    return faux_me.api(g, "POST", "/channels/1560153647395115058/messages", json=corps)


sys.modules["membres_evenements"] = faux_me
import importlib.util
_trouve = importlib.util.find_spec
importlib.util.find_spec = lambda nom, *a: object() if nom == "membres_evenements" else _trouve(nom, *a)
try:
    verifier("brancher : branché", su.brancher() is True)
    enveloppe = faux_me.api
    verifier("brancher : une seule enveloppe (create_app rappelé)", su.brancher() is True and faux_me.api is enveloppe)
    avec(Faux(auto=[entree_auto]))
    publier(G, carte_me())
    publier(G, carte_me("depart"))
    faux_me.api(G, "GET", f"/guilds/{G}/members")
    verifier("brancher : la carte ⏸️ part avec raison et bouton",
             "Anti-arnaque" in envois[0][2]["json"]["embeds"][0]["description"] and envois[0][2]["json"].get("components"))
    verifier("brancher : la carte de départ part telle quelle", "components" not in envois[1][2]["json"])
    verifier("brancher : les lectures passent", envois[2][:2] == ("GET", f"/guilds/{G}/members"))

    class Casse(Faux):
        def __call__(self, methode, chemin, **kw):
            raise RuntimeError("panne")
    avec(Casse())
    publier(G, carte_me())
    verifier("brancher : une panne de la raison n'empêche pas la carte", len(envois) == 4)
finally:
    importlib.util.find_spec = _trouve
    del sys.modules["membres_evenements"]

# ── traiter ──
v._EN_FOND = lambda f: f()
carte = {"embeds": [{"description": "Discord indique…", "footer": {"text": "YouLab Twitter • Suspension temporaire"}}],
         "components": su.composants(UID)}


def clic(roles=(), permissions="0", cid=f"susp:lever:{UID}"):
    return {"type": 3, "guild_id": G, "application_id": "1552153790701117480", "token": "jeton",
            "data": {"custom_id": cid},
            "member": {"user": {"id": "42", "username": "johnmzn"}, "roles": list(roles), "permissions": permissions},
            "message": {"embeds": [dict(e) for e in carte["embeds"]], "components": carte["components"]}}


verifier("un autre bouton n'est pas le sien", su.traiter({"type": 3, "data": {"custom_id": "copie"}}) is None)

f = avec(Faux(membre_fin=fin))
rep = su.traiter(clic())
verifier("un VA est refusé", rep["type"] == 4 and "Réservé" in rep["data"]["content"])
verifier("un VA ne lève rien", not any(m == "PATCH" for m, _, _ in f.appels))

f = avec(Faux(membre_fin=fin))
rep = su.traiter(clic(roles=[MANAGER_ROLE]))
patch = [kw for m, c, kw in f.appels if m == "PATCH" and "/members/" in c]
maj = [kw for m, c, kw in f.appels if c.startswith("/webhooks/")]
verifier("manager : réponse différée", rep == {"type": 6})
verifier("manager : la suspension est levée", patch and patch[0]["json"] == {"communication_disabled_until": None})
verifier("manager : la carte dit qui", maj and "johnmzn" in maj[0]["json"]["embeds"][0]["description"])
verifier("manager : le bouton disparaît", maj and maj[0]["json"]["components"] == [])

f = avec(Faux(membre_fin=fin))
su.traiter(clic(permissions=str(1 << 40)))
verifier("droit d'exclure temporairement : accepté", any(m == "PATCH" and "/members/" in c for m, c, _ in f.appels))

f = avec(Faux(membre_fin=fin, code_patch=403))
su.traiter(clic(roles=[MANAGER_ROLE]))
maj = [kw for m, c, kw in f.appels if c.startswith("/webhooks/")]
verifier("échec : le bouton reste", maj and maj[0]["json"]["components"] == carte["components"])
verifier("échec : le code est dit", maj and "HTTP 403" in maj[0]["json"]["embeds"][0]["description"])

f = avec(Faux(membre_fin=passe))
su.traiter(clic(roles=[MANAGER_ROLE]))
maj = [kw for m, c, kw in f.appels if c.startswith("/webhooks/")]
verifier("déjà finie : rien à lever, c'est dit", not any(m == "PATCH" and "/members/" in c for m, c, _ in f.appels)
         and "déjà terminée" in maj[0]["json"]["embeds"][0]["description"])

f = avec(Faux(code_membre=404))
su.traiter(clic(roles=[MANAGER_ROLE]))
maj = [kw for m, c, kw in f.appels if c.startswith("/webhooks/")]
verifier("parti : c'est dit, bouton retiré", "quitté" in maj[0]["json"]["embeds"][0]["description"]
         and maj[0]["json"]["components"] == [])

print(f"\nRESULTAT : {OK} OK / {ECHECS} ECHEC(S)")
raise SystemExit(1 if ECHECS else 0)
