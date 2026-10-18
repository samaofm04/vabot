# -*- coding: utf-8 -*-
"""tests_outlook_x.py — adresses Outlook du coffre, pour les VA de YouLab TWITTER.

Rien ne part vers Discord : verif_discord.api est remplacé, le travail « en
fond » tourne tout de suite, le coffre et les messages vivent dans un dossier
temporaire. La clé 2FA ne doit apparaître dans AUCUN envoi.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import outlook_comptes as oc
import outlook_x_discord as ox
import tickets_discord
import totp
import verif_discord as vd

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:400]}]"))


GID, SALON, APP = vd.TWITTER_ID, "1552392906340565114", "1552153790701117480"
VA, VA2, CHEF = "111111111111111111", "222222222222222222", "333333333333333333"
SEED = "JBSWY3DPEHPK3PXP"
APPELS, REPONSES = [], []
REGLE = {"messages": []}


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw))
    if methode == "POST" and chemin.startswith(f"/webhooks/{APP}/"):
        return 200, {"id": "suivi%d" % len(APPELS)}
    if methode == "GET" and chemin.startswith(f"/channels/{SALON}/messages"):
        return 200, REGLE["messages"]
    if methode == "DELETE":
        return 204, {}
    return 200, {"id": "999"}


def clic(cid, uid=VA, perms="0", jeton="tok", ephemere=False):
    p = {"type": 3, "guild_id": GID, "channel_id": SALON, "application_id": APP, "token": jeton,
         "data": {"custom_id": cid},
         "member": {"user": {"id": uid, "username": "va" + uid[:2]}, "roles": [], "permissions": perms},
         "message": {"flags": 64 if ephemere else ox.nx.V2}}
    r = ox.traiter(p)
    REPONSES.append(r)
    return r


def suivis(jeton="tok"):
    return [kw["json"] for m, ch, kw in APPELS if m == "POST" and ch.startswith(f"/webhooks/{APP}/{jeton}")]


def ids(comps):
    return ox.nx._ids(comps)


def remise_a_zero(n_comptes=0):
    APPELS.clear()
    REGLE["messages"] = []
    d = Path(tempfile.mkdtemp(prefix="mailx_"))
    oc.FICHIER = d / "outlook_comptes.json"
    ox.FICHIER = d / "outlook_x.json"
    for i in range(n_comptes):
        oc.ajouter(f"compte{i + 1}@outlook.com", f"MotDePasse{i + 1}!", SEED)


SAV = (vd.api, vd._EN_FOND, oc.FICHIER, ox.FICHIER, ox._dormir, tickets_discord.role_helper,
       tickets_discord.ticket_de)
TICKET = "900000000000000001"
try:
    vd._charger_config()
    vd.api = faux_api
    vd._EN_FOND = lambda f: f()
    ox._dormir = lambda s: None
    tickets_discord.role_helper = lambda gid: ""
    tickets_discord.ticket_de = lambda gid, uid: TICKET if uid == VA else ""

    # 1. ce qui n'est pas pour nous
    check("autre bouton : rendu au module suivant", ox.traiter({"type": 3, "data": {"custom_id": "numx:prendre"}}) is None)

    # 2. coffre vide
    remise_a_zero(0)
    r = clic("mailx:prendre")
    check("coffre vide : refus éphémère qui le dit", r["type"] == 4 and "Plus d'adresse" in r["data"]["content"], r)

    # 3. une adresse : trois messages, chacun seul
    remise_a_zero(5)
    r = clic("mailx:prendre")
    check("1er message (réponse au clic) : l'adresse SEULE, éphémère, sans aperçu",
          r["type"] == 4 and r["data"]["content"] == "compte1@outlook.com" and r["data"]["flags"] == 64 | 4, r)
    check("1er message : nommé par un bouton gris désactivé « 📧 Adresse »",
          r["data"]["components"][0]["components"][0].get("disabled") is True
          and r["data"]["components"][0]["components"][0]["label"] == "📧 Adresse", r)
    s = suivis()
    check("deux suivis : le mot de passe seul, puis le code seul", len(s) == 2, s)
    check("2e message : le mot de passe SEUL", s and s[0]["content"] == "MotDePasse1!", s)
    code_attendu, _ = totp.code_totp(SEED)
    check("3e message : le code à 6 chiffres du moment, SEUL",
          len(s) > 1 and s[1]["content"] == code_attendu and len(code_attendu) == 6, s)
    check("3e message : « Nouveau code » lié à l'adresse",
          len(s) > 1 and "mailx:code:1" in ids(s[1]["components"]), s)
    c1 = oc.compte_par_id("1")
    check("coffre : l'adresse est donnée à ce VA, sur Twitter, horodatée",
          c1["statut"] == "attribue" and c1["uid"] == VA and c1["serveur"] == GID and c1.get("attribue_ts"), c1)
    tout = json.dumps([REPONSES, [kw for *_, kw in APPELS]], ensure_ascii=False)
    check("la clé 2FA n'apparaît dans AUCUN envoi", SEED not in tout and SEED.lower() not in tout)

    # 3 bis. adresse et mot de passe AUSSI dans le salon perso, jamais le code
    au_salon = [kw["json"] for m, ch, kw in APPELS if m == "POST" and ch == f"/channels/{TICKET}/messages"]
    check("salon perso : l'adresse puis le mot de passe, chacun seul",
          [m["content"] for m in au_salon] == ["compte1@outlook.com", "MotDePasse1!"], au_salon)
    check("salon perso : messages ordinaires (pas éphémères), nommés par un bouton gris",
          all(m["flags"] == 4 and m["components"][0]["components"][0]["disabled"] for m in au_salon), au_salon)
    check("salon perso : ni le code du moment ni la clé 2FA",
          code_attendu not in json.dumps(au_salon) and SEED not in json.dumps(au_salon), au_salon)

    # 4. une seconde : le jeu précédent est effacé
    r2 = clic("mailx:prendre", jeton="tok2")
    effaces = [ch for m, ch, kw in APPELS if m == "DELETE"]
    check("2e adresse : la suivante du coffre", r2["data"]["content"] == "compte2@outlook.com", r2)
    check("2e adresse : les trois messages d'avant sont effacés",
          len(effaces) == 3 and effaces[0] == f"/webhooks/{APP}/tok/messages/@original"
          and all(e.startswith(f"/webhooks/{APP}/tok/messages/suivi") for e in effaces[1:]), effaces)
    s2 = suivis("tok2")
    check("2e adresse : son code propose l'autre adresse du VA",
          len(s2) > 1 and "mailx:voir:1" in ids(s2[1]["components"]), s2)

    # 5. quota : 3 par jour pour un VA, pas pour le staff
    clic("mailx:prendre", jeton="tok3")
    r = clic("mailx:prendre", jeton="tok4")
    check("4e adresse du jour : refus « 3 adresses aujourd'hui »",
          r["type"] == 4 and "3 adresses aujourd'hui" in r["data"]["content"] and oc.nb_libres() == 2, r)
    for i in range(2):
        clic("mailx:prendre", uid=CHEF, perms=str(0x8), jeton="chef%d" % i)
    check("le staff n'est pas bridé", oc.nb_libres() == 0, oc.nb_libres())
    r = clic("mailx:prendre", uid=VA2)
    check("coffre épuisé : refus clair", "Plus d'adresse" in r["data"]["content"], r)

    check("salon perso : un VA sans salon perso ne bloque rien (rien de posté, il a reçu son éphémère)",
          not [1 for m, ch, kw in APPELS if m == "POST" and ch.startswith("/channels/") and ch != f"/channels/{TICKET}/messages"])

    # 6. Code 2FA depuis le panneau : TOUTES ses adresses, chacune avec son code (déjà déroulé)
    APPELS.clear()
    r = clic("mailx:2fa", jeton="tok5")
    check("Code 2FA : rien de reposté dans le salon perso",
          not [1 for m, ch, kw in APPELS if m == "POST" and ch.startswith("/channels/")], APPELS)
    check("Code 2FA : un seul message éphémère en V2, sans suivi",
          r["type"] == 4 and r["data"]["flags"] == ox.nx.V2 | 64 and not suivis("tok5"), r)
    blocs = r["data"]["components"][0]["components"]
    textes = [b["components"][0]["content"] for b in blocs]
    code_now = totp.code_totp(SEED)[0]
    check("Code 2FA : les 3 adresses du VA, la plus récente d'abord, chacune avec son code",
          [t.split("\n")[0] for t in textes] == ["compte3@outlook.com", "compte2@outlook.com", "compte1@outlook.com"]
          and all(("🔐 **%s**" % code_now) in t for t in textes), textes)
    check("Code 2FA : un 🔄 par adresse", [b["accessory"]["custom_id"] for b in blocs]
          == ["mailx:maj:3", "mailx:maj:2", "mailx:maj:1"], blocs)
    check("Code 2FA : ni mot de passe ni clé 2FA dans la liste",
          "MotDePasse" not in json.dumps(r) and SEED not in json.dumps(r), r)
    check("Code 2FA : le jeu d'avant est effacé",
          any(m == "DELETE" and "/tok4/" not in ch for m, ch, kw in APPELS), APPELS)
    r = clic("mailx:maj:2", ephemere=True)
    check("🔄 : la liste entière redessinée sur place (type 7)",
          r["type"] == 7 and len(r["data"]["components"][0]["components"]) == 3, r)
    r = clic("mailx:2fa", uid=VA2)
    check("Code 2FA sans adresse : il est invité à en prendre une",
          "pas encore d'adresse" in r["data"]["content"], r)
    check("adresse avec « _ » : tirets bas gardés à l'affichage",
          ox._sans_md("jean_dupont@outlook.com") == "jean\\_dupont@outlook.com")

    # 7. Nouveau code / voir
    r = clic("mailx:code:1", ephemere=True)
    check("Nouveau code : le message du code changé sur place (type 7), code seul",
          r["type"] == 7 and r["data"]["content"] == totp.code_totp(SEED)[0], r)
    r = clic("mailx:code:1", uid=VA2, ephemere=True)
    check("le code d'une adresse d'un autre : refusé", r["type"] == 4 and "pas à toi" in r["data"]["content"], r)
    r = clic("mailx:voir:2", ephemere=True, jeton="tok6")
    check("voir une autre adresse : son jeu complet", r["data"]["content"] == "compte2@outlook.com", r)
    tout = json.dumps([REPONSES, [kw for *_, kw in APPELS]], ensure_ascii=False)
    check("toujours aucune clé 2FA dans les envois", SEED not in tout)

    # 8. Va IG n'est pas touché
    remise_a_zero(3)
    clic("mailx:prendre")
    c, etat = oc.attribuer(VA, "va")
    check("Va IG : l'adresse Twitter du VA ne tient pas lieu de la sienne",
          etat == "neuf" and c["id"] == "2" and not c.get("serveur"), (c, etat))
    check("Va IG : compte_de_uid rend celle de Va IG", oc.compte_de_uid(VA)["id"] == "2")
    c, etat = oc.attribuer(VA, "va")
    check("Va IG : toujours une seule par VA", etat == "deja" and c["id"] == "2", (c, etat))

    # 9. panneau
    remise_a_zero(0)
    print(ox.poser_panneau(GID))
    posts = [kw["json"] for m, ch, kw in APPELS if m == "POST" and ch.startswith("/channels/")]
    check("panneau : V2, « Prendre une adresse » et « Code 2FA »",
          len(posts) == 1 and posts[0]["flags"] == ox.nx.V2
          and ids(posts[0]["components"]) == ["mailx:prendre", "mailx:2fa"], posts)
    REGLE["messages"] = [{"id": "77", "author": {"id": vd.bot_du_serveur(GID)["app_id"]},
                          "components": ox.vue_panneau()}]
    APPELS.clear()
    ox.poser_panneau(GID)
    check("panneau présent : remis à neuf, jamais un second",
          [(m, ch) for m, ch, kw in APPELS if m in ("POST", "PATCH")] == [("PATCH", f"/channels/{SALON}/messages/77")],
          APPELS)

    # 10. la route
    src = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
    i_ox, i_vd = src.find("import outlook_x_discord as _ox"), src.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route /discord/interactions : « mailx: » traité avant la vérification", 0 < i_ox < i_vd)
finally:
    (vd.api, vd._EN_FOND, oc.FICHIER, ox.FICHIER, ox._dormir, tickets_discord.role_helper,
     tickets_discord.ticket_de) = SAV

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
