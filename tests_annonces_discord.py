# -*- coding: utf-8 -*-
"""tests_annonces_discord.py — /annonce : le texte d'un manager publié PAR LE BOT.

Rien ne part vers Discord : verif_discord.api est remplacé par un salon en
mémoire, le travail « en fond » tourne tout de suite.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import annonces_discord as an
import verif_discord as vd

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:300]}]"))


GID, SALON, APP = "1505418484052394004", "1555772854182609006", "1552153790701117480"
APPELS = []
REFUS = {"salon": None}


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw))
    if methode == "POST" and chemin.startswith("/channels/"):
        if REFUS["salon"]:
            return REFUS["salon"], {"message": "Missing Permissions"}
        return 200, {"id": str(9000 + len(APPELS))}
    if methode == "POST" and "/commands" in chemin:
        return 201, {"id": "c1"}
    return 200, {}


class _Rep:
    content = b"\x89PNG-fausse-image"

    def raise_for_status(self):
        pass


SAV = (vd.api, vd._EN_FOND, vd.serveur, vd.app_de_reponse, vd.bot_du_serveur)
import requests
SAV_GET = requests.get
try:
    vd.api = faux_api
    vd._EN_FOND = lambda f: f()
    vd.serveur = lambda gid=None: {"id": GID, "role_manager": "1505821464375328798"} if str(gid) == GID else None
    vd.app_de_reponse = lambda p=None, gid=None: APP
    vd.bot_du_serveur = lambda gid=None: {"app_id": APP}
    requests.get = lambda url, timeout=30: _Rep()

    def commande(perms="8", roles=(), ping=None, image=None):
        opts = []
        if ping is not None:
            opts.append({"name": "ping", "type": 5, "value": ping})
        data = {"name": "annonce", "options": opts}
        if image:
            opts.append({"name": "image", "type": 11, "value": "77"})
            data["resolved"] = {"attachments": {"77": image}}
        return {"type": 2, "guild_id": GID, "channel_id": SALON, "data": data, "token": "tok",
                "member": {"permissions": perms, "roles": list(roles), "user": {"id": "42"}}}

    def fenetre(cle, texte, perms="8"):
        return {"type": 5, "guild_id": GID, "channel_id": SALON, "token": "tok2",
                "application_id": APP,
                "data": {"custom_id": f"annonce:{cle}",
                         "components": [{"type": 1, "components": [{"type": 4, "custom_id": "texte", "value": texte}]}]},
                "member": {"permissions": perms, "roles": [], "user": {"id": "42"}}}

    # 1. un VA (ni admin, ni role manager) : refuse, rien d'ouvert
    r = an.traiter(commande(perms="0"))
    check("un VA : « Réservé aux managers », pas de fenêtre", r["type"] == 4 and "managers" in r["data"]["content"], r)
    # 2. le role manager du serveur suffit
    r = an.traiter(commande(perms="0", roles=["1505821464375328798"]))
    check("rôle manager : la fenêtre s'ouvre", r["type"] == 9 and r["data"]["custom_id"].startswith("annonce:"), r)
    # 3. admin : fenetre, puis texte publie PAR LE BOT dans le salon de la commande
    APPELS.clear()
    r = an.traiter(commande())
    cle = r["data"]["custom_id"].split(":", 1)[1]
    champ = r["data"]["components"][0]["components"][0]
    check("fenêtre : un grand champ de texte (4000 max)", champ["style"] == 2 and champ["max_length"] == 4000)
    r2 = an.traiter(fenetre(cle, "Bonjour à tous !\nDemain, nouvelle règle."))
    check("envoi : réponse différée éphémère (3 s de Discord tenues)", r2 == {"type": 5, "data": {"flags": 64}}, r2)
    posts = [a for a in APPELS if a[0] == "POST" and a[1] == f"/channels/{SALON}/messages"]
    check("publiée dans le salon de la commande, un seul message",
          len(posts) == 1 and posts[0][2]["json"]["content"] == "Bonjour à tous !\nDemain, nouvelle règle.", posts)
    check("sans ping demandé : aucune mention ne part", posts[0][2]["json"]["allowed_mentions"] == {"parse": []})
    patch = [a for a in APPELS if a[0] == "PATCH"]
    check("le manager lit « ✅ Annonce publiée » avec le lien",
          patch and patch[0][1] == f"/webhooks/{APP}/tok2/messages/@original"
          and "✅ Annonce publiée" in patch[0][2]["json"]["content"]
          and f"/channels/{GID}/{SALON}/" in patch[0][2]["json"]["content"], patch)
    # 4. la meme fenetre renvoyee deux fois ne publie pas deux fois
    APPELS.clear()
    r3 = an.traiter(fenetre(cle, "Bonjour à tous !"))
    check("fenêtre déjà utilisée : rien de republié, le texte est rendu",
          r3["type"] == 4 and "relance /annonce" in r3["data"]["content"]
          and "Bonjour à tous !" in r3["data"]["content"]
          and not [a for a in APPELS if a[0] == "POST"], r3)
    # 5. ping : @everyone en tete, mention autorisee sur le premier message seulement
    APPELS.clear()
    cle = an.traiter(commande(ping=True))["data"]["custom_id"].split(":", 1)[1]
    long = ("Paragraphe " + "x" * 900 + "\n\n") * 4
    an.traiter(fenetre(cle, long))
    posts = [a for a in APPELS if a[0] == "POST"]
    check("texte de 3600+ caractères : coupé en plusieurs messages de 2000 au plus",
          len(posts) >= 2 and all(len(a[2]["json"]["content"]) <= 2000 for a in posts), [len(a[2]["json"]["content"]) for a in posts])
    check("ping : @everyone en tête du premier message",
          posts[0][2]["json"]["content"].startswith("@everyone\n"))
    check("ping : une seule notification (premier message seulement)",
          posts[0][2]["json"]["allowed_mentions"] == {"parse": ["everyone"]}
          and all(a[2]["json"]["allowed_mentions"] == {"parse": []} for a in posts[1:]))
    check("coupé aux paragraphes, rien de perdu",
          "".join(a[2]["json"]["content"] for a in posts).count("x") == 3600)
    # 6. image : remise sous le dernier message, en multipart
    APPELS.clear()
    im = {"id": "77", "url": "https://cdn.discordapp.com/ephemeral/x.png", "filename": "regle.png",
          "content_type": "image/png", "size": 1234}
    cle = an.traiter(commande(image=im))["data"]["custom_id"].split(":", 1)[1]
    an.traiter(fenetre(cle, "Voici le planning"))
    posts = [a for a in APPELS if a[0] == "POST"]
    p0 = posts[0][2] if posts else {}
    check("image : envoyée avec le texte (multipart, files[0])",
          len(posts) == 1 and "files" in p0 and p0["files"]["files[0]"][0] == "regle.png"
          and json.loads(p0["data"]["payload_json"])["attachments"] == [{"id": 0, "filename": "regle.png"}], p0)
    check("image trop lourde : refusée avant tout",
          "trop lourde" in an.traiter(commande(image=dict(im, size=30 * 1024 * 1024)))["data"]["content"])
    # 7. le bot n'a pas le droit d'ecrire : le texte revient au manager
    APPELS.clear()
    REFUS["salon"] = 403
    cle = an.traiter(commande())["data"]["custom_id"].split(":", 1)[1]
    an.traiter(fenetre(cle, "Texte important"))
    REFUS["salon"] = None
    patch = [a for a in APPELS if a[0] == "PATCH"]
    check("salon refusé : « ❌ non publiée (HTTP 403…) » et le texte rendu",
          patch and "❌ Annonce non publiée (HTTP 403" in patch[0][2]["json"]["content"]
          and "Texte important" in patch[0][2]["json"]["content"], patch)
    # 8. ce qui n'est pas pour nous passe
    check("/quetes et les autres fenêtres : None (la main passe)",
          an.traiter({"type": 2, "data": {"name": "quetes"}}) is None
          and an.traiter({"type": 5, "data": {"custom_id": "usdc:form:1"}}) is None
          and an.traiter({"type": 3, "data": {"custom_id": "annonce:x"}}) is None)
    # 9. la commande : cachee aux non-admins, deux options
    APPELS.clear()
    an.enregistrer_commande(GID)
    c = APPELS[0][2]["json"]
    check("enregistrement : sous l'app du bot du serveur, cachée aux non-admins",
          APPELS[0][1] == f"/applications/{APP}/guilds/{GID}/commands" and c["name"] == "annonce"
          and c["default_member_permissions"] == "8"
          and [o["name"] for o in c["options"]] == ["ping", "image"], c)
    # 10. la route du site passe par le module, avant la verification
    src = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
    i_an, i_vd = src.find("import annonces_discord as _an"), src.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route /discord/interactions : /annonce traité avant la vérification", 0 < i_an < i_vd)
    # 11. coupe
    check("couper : un texte court reste entier", an.couper("abc") == ["abc"])
    check("couper : sans espace, coupe dure à 2000", [len(x) for x in an.couper("y" * 4500)] == [2000, 2000, 500])
finally:
    vd.api, vd._EN_FOND, vd.serveur, vd.app_de_reponse, vd.bot_du_serveur = SAV
    requests.get = SAV_GET

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
