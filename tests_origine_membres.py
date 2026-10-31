"""Cartes d'accueil : le lien d'arrivée (de la part de qui) et le motif du départ.

    python tests_origine_membres.py

Aucun appel à Discord : verif_discord.api est remplacé par un faux qui rejoue
les formes vues sur TRUST Threads le 31/10/2026 (recherche de membres,
invitations, journal d'audit). Les modules hors git (membres_evenements,
threads_accueil) sont des faux qui postent comme eux.
"""
import sys
import time
import types

import origine_membres as om
import verif_discord as v

G = v.THREADS_ID
OK = ECHECS = 0
om.RECHERCHE_ESSAIS = (0, 0, 0)


def verifier(nom, cond, detail=""):
    global OK, ECHECS
    if cond:
        OK += 1
        print("OK  ", nom)
    else:
        ECHECS += 1
        print("ECHEC", nom, detail)


def snowflake(t):
    return str((int(t * 1000) - 1420070400000) << 22)


MAINTENANT = time.time()
# des identifiants Discord réels de forme (17 à 19 chiffres) : les cartes les relisent ainsi
PARTI, AUTRE, ARRIVE = "1470195742223241439", "1470195742223241440", "1398950213703696414"
STAFF_ROLE = v.serveur(G)["role_manager"]


class Faux:
    """Discord tel que le bot le lit : membres, invitations, journal, recherche."""

    def __init__(self, sources=None, invites=None, audit=None, code_audit=200, recherche_vide=0):
        self.sources = sources or {}
        self.invites = invites if invites is not None else []
        self.audit = audit or []
        self.code_audit = code_audit
        self.recherche_vide = recherche_vide      # nombre de recherches sans résultat avant l'index
        self.appels = []
        self.membres = {"700": {"user": {"id": "700", "username": "vectorofm"}, "roles": [STAFF_ROLE]},
                        "701": {"user": {"id": "701", "username": "momobtn"}, "roles": []},
                        "702": {"user": {"id": "702", "username": "Meyzah.exe", "bot": True}, "roles": []}}

    def __call__(self, methode, chemin, **kw):
        self.appels.append((methode, chemin))
        if chemin.endswith("/members-search"):
            if self.recherche_vide:
                self.recherche_vide -= 1
                return 200, {"members": []}
            uid = kw["json"]["and_query"]["user_id"]["or_query"][0]
            if uid not in self.sources:
                return 200, {"members": []}
            code, typ, par = self.sources[uid]
            return 200, {"members": [{"member": {"user": {"id": uid}}, "source_invite_code": code,
                                      "join_source_type": typ, "inviter_id": par}]}
        if chemin.endswith("/invites"):
            return 200, list(self.invites)
        if chemin.endswith("/audit-logs"):
            if self.code_audit != 200:
                return self.code_audit, {"message": "Missing Permissions"}
            t = kw["params"]["action_type"]
            return 200, {"audit_log_entries": [e for e in self.audit if e["action_type"] == t],
                         "users": [{"id": "700", "username": "vectorofm"}, {"id": "702", "username": "Meyzah.exe", "bot": True}]}
        if "/members/" in chemin:
            m = self.membres.get(chemin.rsplit("/", 1)[1])
            return (200, m) if m else (404, {})
        if chemin == f"/guilds/{G}":
            return 200, {"owner_id": "479005370438778891", "vanity_url_code": None,
                         "roles": [{"id": STAFF_ROLE, "name": "🛡️ Manager", "permissions": "0"}]}
        return 404, {}


def avec(faux):
    om._CACHE.clear()
    v.api = lambda methode, chemin, gid=None, **kw: faux(methode, chemin, **kw)
    return faux


# ── départs : le journal d'audit ──────────────────────────────────────────
kick = {"id": snowflake(MAINTENANT - 30), "action_type": 20, "target_id": PARTI, "user_id": "700",
        "reason": "Plus actif"}
avec(Faux(audit=[kick]))
m = om.motif_depart(G, PARTI, "2026-10-01T10:00:00+00:00", MAINTENANT)
verifier("exclusion au journal : exclu, par qui, pourquoi",
         m["kind"] == "exclu" and m["auteur"] == "700" and m["auteur_nom"] == "vectorofm" and m["raison"] == "Plus actif", m)
t = om.texte_depart(m)
verifier("… la carte le dit", t["titre"] == "🚫 Un membre a été exclu"
         and "👮 **Exclu par** <@700> · `@vectorofm`" in t["texte"] and "**Raison** : Plus actif" in t["texte"], t)

ban = dict(kick, id=snowflake(MAINTENANT - 10), action_type=22, user_id="702", reason="")
avec(Faux(audit=[kick, ban]))
m = om.motif_depart(G, PARTI, None, MAINTENANT)
verifier("exclu puis banni : le dernier geste compte, un bot est dit bot, sans raison c'est dit",
         m["kind"] == "banni" and "(bot)" in om.texte_depart(m)["texte"]
         and "Aucune raison donnée." in om.texte_depart(m)["texte"], m)

avec(Faux(audit=[kick]))
m = om.motif_depart(G, PARTI, time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(MAINTENANT)), MAINTENANT + 60)
verifier("exclusion d'AVANT sa dernière arrivée : pas celle de ce départ", m["kind"] == "depart" and m["lu"], m)

avec(Faux(audit=[dict(kick, target_id=AUTRE)]))
m = om.motif_depart(G, PARTI, None, MAINTENANT)
verifier("rien au journal : parti de lui-même", m == {"kind": "depart", "lu": True, "http": 200}
         and om.texte_depart(m)["titre"] == "👋 Un membre est parti de lui-même", m)

avec(Faux(code_audit=403))
m = om.motif_depart(G, PARTI, None, MAINTENANT)
verifier("journal refusé : dit, pas de conclusion", not m["lu"] and "HTTP 403" in om.texte_depart(m)["texte"]
         and om.texte_depart(m)["titre"] == "👋 Un membre a quitté le serveur", m)


def carte_me(kind="depart", uid=None):
    """La carte telle que membres_evenements.carte l'écrit."""
    titres = {"depart": "👋 Un membre a quitté le serveur", "exclu": "🚫 Un membre a été exclu",
              "banni": "⛔ Un membre a été banni"}
    phrases = {"depart": "Son départ du serveur a été constaté.", "exclu": "Discord confirme son exclusion du serveur.",
               "banni": "Discord confirme son bannissement du serveur."}
    libelles = {"depart": "Départ du serveur", "exclu": "Membre exclu", "banni": "Membre banni"}
    uid = uid or PARTI
    return {"embeds": [{"title": titres[kind], "description": f"<@{uid}> · `@dsdsf_97901`\n\n{phrases[kind]}",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(MAINTENANT)),
                        "footer": {"text": f"YouLab Threads • {libelles[kind]}"},
                        "author": {"name": f"dsd • {libelles[kind]}"}}],
            "allowed_mentions": {"parse": []}, "nonce": "k", "enforce_nonce": True}


avec(Faux(audit=[kick]))
corps = carte_me("exclu")
verifier("carte 🚫 de membres_evenements : complétée", om.completer(corps, G) is True)
e = corps["embeds"][0]
verifier("… « exclu par » à la place de « Discord confirme »",
         "Discord confirme" not in e["description"] and "👮 **Exclu par** <@700>" in e["description"]
         and e["description"].startswith(f"<@{PARTI}> · `@dsdsf_97901`"), e)
avant = repr(corps)
verifier("… une seule fois", om.completer(corps, G) is False and repr(corps) == avant)

corps = carte_me("depart")
om.completer(corps, G)
e = corps["embeds"][0]
verifier("carte 👋 « départ » mais exclusion au journal : titre, pied et nom corrigés",
         e["title"] == "🚫 Un membre a été exclu" and e["footer"]["text"] == "YouLab Threads • Membre exclu"
         and e["author"]["name"] == "dsd • Membre exclu", e)

avec(Faux())
corps = carte_me("depart")
om.completer(corps, G)
e = corps["embeds"][0]
verifier("carte 👋 sans rien au journal : « parti de lui-même »",
         e["title"] == "👋 Un membre est parti de lui-même" and "🚶 **Parti de lui-même**" in e["description"]
         and e["footer"]["text"] == "YouLab Threads • Départ volontaire", e)

for autre in ({"embeds": [{"title": "⏸️ Suspension temporaire", "description": f"<@{PARTI}>"}]},
              {"content": "x"}, {"embeds": [{"title": "✨ Bienvenue dans l’équipe YouLab Threads !",
                                             "description": f"<@{PARTI}>, ta vérification est validée."}]}):
    avant = repr(autre)
    verifier(f"autre message laissé tel quel ({str(autre)[:40]})", om.completer(autre, G) is False and repr(autre) == avant)


# ── arrivées : la source notée par Discord, le registre de parrainage ─────
LIENS = {"701": {"code": "TPTaHwuSK7"}}
INVITES = [{"code": "nekk7gb6n", "uses": 7, "inviter": {"id": "700"}, "channel": {"id": "5555"}},
           {"code": "TPTaHwuSK7", "uses": 7, "inviter": {"id": "702", "bot": True}, "channel": {"id": "6666"}},
           {"code": "perso701", "uses": 1, "inviter": {"id": "701"}, "channel": {"id": "7777"}},
           {"code": "bot702", "uses": 2, "inviter": {"id": "702"}, "channel": {"id": "6666"}}]

avec(Faux(sources={"50": ("TPTaHwuSK7", 5, "702")}, invites=INVITES))
l = om.lignes_arrivee(G, "50", LIENS, "701", True)
verifier("lien de parrainage : de la part du parrain du registre",
         l == "\n🔗 **Lien** : 🤝 **De la part de** <@701> : son lien de parrainage `TPTaHwuSK7`", l)

avec(Faux(sources={"51": ("nekk7gb6n", 5, "700")}, invites=INVITES))
l = om.lignes_arrivee(G, "51", LIENS, None, True)
verifier("lien du staff : qui l'a créé, dans quel salon, aucun parrain",
         "🛡️ Lien du staff `nekk7gb6n`, créé par <@700> · `@vectorofm` dans <#5555> · aucun parrain" in l, l)

avec(Faux(sources={"52": ("perso701", 5, "701")}, invites=INVITES))
l = om.lignes_arrivee(G, "52", LIENS, None, True)
verifier("lien Discord d'un membre : de lui, hors parrainage",
         "👥 Lien de <@701> · `@momobtn` `perso701` dans <#7777> · hors parrainage, aucun parrain enregistré" in l, l)

avec(Faux(sources={"53": ("bot702", 5, "702")}, invites=INVITES))
l = om.lignes_arrivee(G, "53", LIENS, None, True)
verifier("lien créé par le bot hors registre : dit", "🤖 Lien `bot702` créé par le bot dans <#6666>" in l, l)

avec(Faux(sources={"54": ("ancien", 5, "")}, invites=INVITES))
l = om.lignes_arrivee(G, "54", LIENS, None, True)
verifier("lien expiré sans auteur : écrit, pas inventé", "`ancien`, auteur inconnu" in l, l)

avec(Faux(sources={"55": ("", 3, "")}, invites=INVITES))
l = om.lignes_arrivee(G, "55", LIENS, None, True)
verifier("arrivé sans invitation : la source Discord", "aucun, arrivé sans invitation (découverte de serveurs)" in l, l)

avec(Faux(sources={"56": ("TPTaHwuSK7", 5, "702")}, invites=INVITES))
l = om.lignes_arrivee(G, "56", LIENS, "999", True)
verifier("registre et Discord en désaccord : les deux, et « à vérifier »",
         "<@701>" in l and "⚠️ Le parrainage a noté <@999> : origine à vérifier." in l, l)
l = om.lignes_arrivee(G, "56", LIENS, None, True)
verifier("lien de parrainage mais pas compté au registre : dit", "Pas compté dans son parrainage" in l, l)
l = om.lignes_arrivee(G, "56", LIENS, None, False)
verifier("… mais pas tant que le registre n'a pas traité l'arrivée", "Pas compté" not in l, l)

f = avec(Faux(sources={"57": ("nekk7gb6n", 5, "700")}, invites=INVITES, recherche_vide=2))
l = om.lignes_arrivee(G, "57", LIENS, None, True)
verifier("pas encore indexé : la recherche est refaite", "nekk7gb6n" in l
         and sum(1 for a in f.appels if a[1].endswith("/members-search")) == 3, f.appels)

avant = {"nekk7gb6n": 6, "TPTaHwuSK7": 7, "perso701": 1, "bot702": 2}
avec(Faux(invites=INVITES))
l = om.lignes_arrivee(G, "58", LIENS, None, True, avant)
verifier("Discord muet, une invitation a monté : « probable », avec son auteur",
         l.startswith("\n🔗 **Lien** probable (comptage des invitations) : 🛡️ Lien du staff `nekk7gb6n`"), l)
avant2 = dict(avant, TPTaHwuSK7=6)
l = om.lignes_arrivee(G, "58", LIENS, None, True, avant2)
verifier("Discord muet, deux invitations ont monté : plusieurs possibles, nommées",
         "plusieurs possibles, `TPTaHwuSK7` (parrainage de <@701>), `nekk7gb6n`" in l, l)
l = om.lignes_arrivee(G, "58", LIENS, None, True, dict(avant, nekk7gb6n=7))
verifier("Discord muet, rien n'a monté : inconnu, écrit", "🔗 **Lien** inconnu" in l, l)
l = om.lignes_arrivee(G, "58", LIENS, "701", True, None)
verifier("Discord muet mais le registre a un parrain : il est dit",
         "🔗 **Lien** inconnu" in l and "🤝 Parrain noté par le parrainage : <@701>." in l, l)


# ── brancher : sur des faux membres_evenements et threads_accueil ─────────
envois = []
faux_me = types.ModuleType("membres_evenements")
faux_me.api = lambda g, methode, chemin, **kw: (envois.append((g, methode, chemin, kw)) or (200, {"id": "9"}))
faux_me.lire = lambda: {G: {"events": {"k": {"kind": "depart", "date": MAINTENANT,
                                              "member": {"user": {"id": PARTI}, "joined_at": "2026-10-01T10:00:00+00:00"}}}}}
faux_th = types.ModuleType("threads_accueil")
faux_th.GID = G
faux_th.api = lambda methode, chemin, **kw: (envois.append((G, methode, chemin, kw)) or (200, {"id": "8"}))
faux_th.lire = lambda: {"liens": LIENS, "filleuls": {ARRIVE: {"parrain": "701", "source": "invitation_unique"}},
                        "invite_uses": avant}
sys.modules["membres_evenements"] = faux_me
sys.modules["threads_accueil"] = faux_th
import importlib.util
_trouve = importlib.util.find_spec
importlib.util.find_spec = (lambda nom, *a: object() if nom in ("membres_evenements", "threads_accueil")
                            else (None if nom == "twitter_accueil" else _trouve(nom, *a)))
try:
    fait = om.brancher()
    verifier("brancher : membres_evenements et threads_accueil, pas twitter_accueil absent",
             fait == {"membres_evenements": True, "threads_accueil": True, "twitter_accueil": False}, fait)
    enveloppe = faux_me.api
    verifier("brancher : une seule enveloppe (create_app rappelé)", om.brancher()["membres_evenements"]
             and faux_me.api is enveloppe)
    avec(Faux(audit=[kick], sources={ARRIVE: ("TPTaHwuSK7", 5, "702")}, invites=INVITES))
    faux_me.api(G, "POST", "/channels/1560153660242137180/messages", json=carte_me("depart"))
    verifier("départ posté par membres_evenements : exclu par, à l'envoi",
             "👮 **Exclu par** <@700>" in envois[-1][3]["json"]["embeds"][0]["description"], envois[-1])
    arrivee = {"embeds": [{"title": "🚪 Nouvelle arrivée sur YouLab Threads",
                           "description": f"<@{ARRIVE}> vient de rejoindre le serveur.\n⏳ **Pas encore vérifié.** "
                                          "La vérification se fait dans <#1552664979218497610>.\nInvité par <@701>."}],
               "content": "", "allowed_mentions": {"parse": [], "users": []}}
    faux_th.api("POST", "/channels/1560075217903161441/messages", json=arrivee)
    d = envois[-1][3]["json"]["embeds"][0]["description"]
    verifier("arrivée postée par threads_accueil : le lien et le parrain, « Invité par » repris",
             "🤝 **De la part de** <@701> : son lien de parrainage `TPTaHwuSK7`" in d and "Invité par" not in d
             and d.startswith(f"<@{ARRIVE}> vient de rejoindre le serveur."), d)
    faux_th.api("GET", f"/guilds/{G}/members")
    verifier("les lectures passent sans rien toucher", envois[-1][1:3] == ("GET", f"/guilds/{G}/members"))

    class Casse(Faux):
        def __call__(self, methode, chemin, **kw):
            raise RuntimeError("panne")
    avec(Casse())
    n = len(envois)
    faux_me.api(G, "POST", "/channels/1/messages", json=carte_me("depart"))
    verifier("une panne de lecture n'empêche pas la carte de partir", len(envois) == n + 1)
finally:
    importlib.util.find_spec = _trouve
    del sys.modules["membres_evenements"], sys.modules["threads_accueil"]

print(f"\n{OK} OK, {ECHECS} ECHEC")
sys.exit(1 if ECHECS else 0)
