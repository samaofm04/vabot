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

import numgen
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
ALERTES = []                # alertes au staff (numgen.alerter_staff), rien ne part
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
    numgen.ALERTES_FICHIER = d / "numgen_alertes.json"
    ALERTES.clear()
    for i in range(n_comptes):
        oc.ajouter(f"compte{i + 1}@outlook.com", f"MotDePasse{i + 1}!", SEED)


SAV = (vd.api, vd._EN_FOND, oc.FICHIER, ox.FICHIER, ox._dormir, tickets_discord.role_helper,
       tickets_discord.ticket_de, numgen.ALERTES_FICHIER, numgen._en_production,
       numgen._poster_alerte)
TICKET = "900000000000000001"
try:
    vd._charger_config()
    vd.api = faux_api
    vd._EN_FOND = lambda f: f()
    ox._dormir = lambda s: None
    tickets_discord.role_helper = lambda gid: ""
    tickets_discord.ticket_de = lambda gid, uid: TICKET if uid == VA else ""
    numgen._en_production = lambda: True
    numgen._poster_alerte = lambda texte: (ALERTES.append(texte) or (True, ""))

    # 1. ce qui n'est pas pour nous
    check("autre bouton : rendu au module suivant", ox.traiter({"type": 3, "data": {"custom_id": "numx:prendre"}}) is None)

    # 2. coffre vide
    remise_a_zero(0)
    r = clic("mailx:prendre")
    check("coffre vide : le VA lit que le coffre est vide et que le staff est prévenu",
          r["type"] == 4 and "coffre d'adresses Outlook est vide" in r["data"]["content"]
          and "staff est prévenu" in r["data"]["content"], r)
    clic("mailx:prendre", uid=VA2)
    check("coffre vide : le staff est prévenu UNE fois (2 refus, 1 alerte), sans adresse ni secret",
          len(ALERTES) == 1 and "aucune adresse enregistrée" in ALERTES[0]
          and SEED not in ALERTES[0], ALERTES)
    oc.ajouter("revenu@outlook.com", "MotDePasseR!", SEED)
    oc.ajouter("revenu2@outlook.com", "MotDePasseR2!", SEED)
    clic("mailx:prendre", uid=CHEF, perms=str(0x8))
    check("coffre rempli : l'alerte est levée, la prochaine panne sera redite",
          "outlook:vide" not in numgen._alertes() and len(ALERTES) == 1, (numgen._alertes(), ALERTES))
    clic("mailx:prendre", uid=CHEF, perms=str(0x8), jeton="tokZ")
    check("la DERNIÈRE adresse partie : le staff est prévenu tout de suite, avant tout refus",
          len(ALERTES) == 2 and "toutes déjà données" in ALERTES[1], ALERTES)

    # 3. une adresse : le formulaire rempli, pour lui seul
    remise_a_zero(5)
    r = clic("mailx:prendre")
    code_attendu, _ = totp.code_totp(SEED)

    def lignes(rep):
        blocs = rep["data"]["components"][0]["components"]
        return [b.get("content") or b.get("components", [{}])[0].get("content")
                for b in blocs if b["type"] in (9, 10)]
    check("Prendre : un seul message éphémère en V2, sans suivi",
          r["type"] == 4 and r["data"]["flags"] == ox.nx.V2 | 64 and not suivis(), r)
    check("Prendre : sous le titre, le mail, le mot de passe, puis le code du moment",
          lignes(r) == ["## Adresses Outlook", "📧 `compte1@outlook.com`", "🔑 `MotDePasse1!`",
                        lignes(r)[3]] and lignes(r)[3].startswith("🔐 **%s** · " % code_attendu), lignes(r))
    check("Prendre : un 🔄 pour le code, « Prendre une adresse » en bas",
          ids(r["data"]["components"]) == ["mailx:maj:1", "mailx:prendre"], ids(r["data"]["components"]))
    c1 = oc.compte_par_id("1")
    check("coffre : l'adresse est donnée à ce VA, sur Twitter, horodatée",
          c1["statut"] == "attribue" and c1["uid"] == VA and c1["serveur"] == GID and c1.get("attribue_ts"), c1)
    tout = json.dumps([REPONSES, [kw for *_, kw in APPELS]], ensure_ascii=False)
    check("la clé 2FA n'apparaît dans AUCUN envoi", SEED not in tout and SEED.lower() not in tout)

    # 3 bis. adresse et mot de passe AUSSI dans le salon perso, jamais le code
    au_salon = [kw["json"] for m, ch, kw in APPELS if m == "POST" and ch == f"/channels/{TICKET}/messages"]
    check("salon perso : l'adresse puis le mot de passe, chacun SEUL",
          [m["content"] for m in au_salon] == ["compte1@outlook.com", "MotDePasse1!"], au_salon)
    check("salon perso : messages ordinaires (pas éphémères), nommés par un bouton gris",
          all(m["flags"] == 4 and m["components"][0]["components"][0]["disabled"] for m in au_salon), au_salon)
    check("salon perso : ni le code du moment ni la clé 2FA",
          code_attendu not in json.dumps(au_salon) and SEED not in json.dumps(au_salon), au_salon)

    # 4. une seconde : le formulaire d'avant est effacé, les deux adresses montrées
    r2 = clic("mailx:prendre", jeton="tok2")
    effaces = [ch for m, ch, kw in APPELS if m == "DELETE"]
    check("2e adresse : la plus récente en haut, la première dessous",
          [t for t in lignes(r2) if t.startswith("📧")] == ["📧 `compte2@outlook.com`", "📧 `compte1@outlook.com`"],
          lignes(r2))
    check("2e adresse : le formulaire d'avant est effacé",
          effaces == [f"/webhooks/{APP}/tok/messages/@original"], effaces)
    r3 = clic("mailx:prendre", jeton="tok2b", ephemere=True)
    check("Prendre depuis le formulaire lui-même : changé sur place (type 7)",
          r3["type"] == 7 and len([t for t in lignes(r3) if t.startswith("📧")]) == 3, r3)

    # 5. quota : 3 par jour pour un VA, pas pour le staff
    r = clic("mailx:prendre", jeton="tok4")
    check("4e adresse du jour : refus « 3 adresses aujourd'hui »",
          r["type"] == 4 and "3 adresses aujourd'hui" in r["data"]["content"] and oc.nb_libres() == 2, r)
    for i in range(2):
        clic("mailx:prendre", uid=CHEF, perms=str(0x8), jeton="chef%d" % i)
    check("le staff n'est pas bridé", oc.nb_libres() == 0, oc.nb_libres())
    r = clic("mailx:prendre", uid=VA2)
    check("coffre épuisé : refus clair, staff prévenu",
          "coffre d'adresses Outlook est vide" in r["data"]["content"]
          and len(ALERTES) == 1 and "toutes déjà données" in ALERTES[0], (r, ALERTES))
    check("salon perso : un VA sans salon perso ne bloque rien (rien de posté ailleurs)",
          not [1 for m, ch, kw in APPELS if m == "POST" and ch.startswith("/channels/") and ch != f"/channels/{TICKET}/messages"])

    # 6. Code 2FA depuis le panneau : le même formulaire rempli, déjà déroulé
    APPELS.clear()
    r = clic("mailx:2fa", jeton="tok5")
    check("Code 2FA : rien de reposté dans le salon perso",
          not [1 for m, ch, kw in APPELS if m == "POST" and ch.startswith("/channels/")], APPELS)
    blocs = r["data"]["components"][0]["components"]
    attendu = ["## Adresses Outlook"]
    for n in (3, 2, 1):
        attendu += ["📧 `compte%d@outlook.com`" % n, "🔑 `MotDePasse%d!`" % n, None]
    check("Code 2FA : pour chaque adresse (récente d'abord) : mail, mot de passe, code",
          [t if not str(t).startswith("🔐") else None for t in lignes(r)] == attendu
          and sum(1 for t in lignes(r) if str(t).startswith("🔐 **%s**" % code_attendu)) == 3, lignes(r))
    check("Code 2FA : un 🔄 par adresse, séparateur entre deux adresses",
          [b["accessory"]["custom_id"] for b in blocs if b["type"] == 9] == ["mailx:maj:3", "mailx:maj:2", "mailx:maj:1"]
          and sum(1 for b in blocs if b["type"] == 14) == 2, blocs)
    check("Code 2FA : jamais la clé 2FA", SEED not in json.dumps(r), r)
    check("Code 2FA : le formulaire d'avant est effacé", any(m == "DELETE" for m, ch, kw in APPELS), APPELS)
    r = clic("mailx:maj:2", ephemere=True)
    check("🔄 : le formulaire entier redessiné sur place (type 7)",
          r["type"] == 7 and sum(1 for b in r["data"]["components"][0]["components"] if b["type"] == 9) == 3, r)
    r = clic("mailx:2fa", uid=VA2)
    check("Code 2FA sans adresse : le formulaire vide, aucun texte",
          r["type"] == 4 and lignes(r) == ["## Adresses Outlook", "📧 " + ox.BLANC, "🔑 " + ox.BLANC,
                                           "🔐 " + ox.BLANC_CODE], r)

    # 7. la limite des 40 composants, avec le maximum d'adresses
    remise_a_zero(ox.LISTE_MAX + 2)
    for i in range(ox.LISTE_MAX + 2):
        clic("mailx:prendre", uid=CHEF, perms=str(0x8), jeton="m%d" % i)

    def compter(cs):
        n = 0
        for c in cs or []:
            n += 1 + compter(c.get("components")) + (1 if isinstance(c.get("accessory"), dict) else 0)
        return n
    r = clic("mailx:2fa", uid=CHEF, perms=str(0x8), jeton="mmax")
    check("formulaire plein : 40 composants au plus (Discord refuse au-delà)",
          compter(r["data"]["components"]) <= 40, compter(r["data"]["components"]))
    check("adresse avec « _ » : tirets bas gardés si elle n'est pas en code",
          ox._sans_md("jean_dupont@outlook.com") == "jean\\_dupont@outlook.com")

    # 8. Va IG n'est pas touché
    remise_a_zero(3)
    clic("mailx:prendre")
    c, etat = oc.attribuer(VA, "va")
    check("Va IG : l'adresse Twitter du VA ne tient pas lieu de la sienne",
          etat == "neuf" and c["id"] == "2" and not c.get("serveur"), (c, etat))
    check("Va IG : compte_de_uid rend celle de Va IG", oc.compte_de_uid(VA)["id"] == "2")
    c, etat = oc.attribuer(VA, "va")
    check("Va IG : toujours une seule par VA", etat == "deja" and c["id"] == "2", (c, etat))

    # 9. panneau : retiré du salon (propriétaire, 23/10/2026), jamais reposté ;
    # la mise en page du formulaire vide reste celle des cartes.
    remise_a_zero(0)
    print(ox.poser_panneau(GID))
    check("panneau retiré : poser_panneau ne poste ni ne modifie rien",
          not [1 for m, ch, kw in APPELS if m in ("POST", "PATCH")], APPELS)
    vide = ox.vue_panneau()
    check("formulaire vide : cases mail / mot de passe / code VIDES, aucun texte",
          [c["content"] for c in vide[0]["components"] if c["type"] == 10]
          == ["## Adresses Outlook", "📧 " + ox.BLANC, "🔑 " + ox.BLANC, "🔐 " + ox.BLANC_CODE], vide)

    # 10. la route
    src = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
    i_ox, i_vd = src.find("import outlook_x_discord as _ox"), src.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route /discord/interactions : « mailx: » traité avant la vérification", 0 < i_ox < i_vd)

    # 11. la carte Outlook dans le ticket de chaque VA (comme la carte numéro)
    remise_a_zero(0)
    _sav_tk = tickets_discord.ETAT_FICHIER
    dt = Path(tempfile.mkdtemp(prefix="mailx_tickets_"))
    tickets_discord.ETAT_FICHIER = dt / "tickets.json"
    tickets_discord.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{GID}:{VA}": {"salon": "T1"}, f"{GID}:{VA2}": {"salon": "T2"}}}), encoding="utf-8")

    MOI_TW = vd.bot_du_serveur(GID)["app_id"]

    def api_carte(methode, chemin, **kw):
        APPELS.append((methode, chemin, kw))
        if methode == "POST" and chemin in ("/channels/T1/messages", "/channels/T2/messages"):
            return 200, {"id": "carte-" + chemin.split("/")[2]}
        morceaux = chemin.split("/")
        if methode == "GET" and len(morceaux) == 5 and morceaux[1] == "channels" \
                and morceaux[3] == "messages" and "?" not in chemin:
            if morceaux[4].startswith("accueil"):
                return 200, {"id": morceaux[4], "flags": 0, "author": {"id": MOI_TW},
                             "components": [{"type": 1, "components": [{"type": 2, "custom_id": "mailx:menu"}]}]}
            return 200, {"id": morceaux[4], "flags": ox.nx.V2, "author": {"id": MOI_TW},
                         "components": ox.vue_carte(VA, GID)}
        if methode == "GET" and chemin.startswith("/channels/T") and "?limit" in chemin:
            return 200, []
        return faux_api(methode, chemin, **kw)
    vd.api = api_carte

    def clic_carte(cid, salon="T1", uid=VA, perms="0"):
        p = {"type": 3, "guild_id": GID, "channel_id": salon, "application_id": APP, "token": "tk",
             "data": {"custom_id": cid},
             "member": {"user": {"id": uid, "username": "va" + uid[:2]}, "roles": [], "permissions": perms},
             "message": {"id": "carte-" + salon, "flags": ox.nx.V2}}
        r = ox.traiter(p)
        REPONSES.append(r)
        return r

    def textes_v2(comps):
        out = []
        for c in comps or []:
            if c.get("type") == 10:
                out.append(c["content"])
            out += textes_v2(c.get("components"))
        return out

    b = ox.poser_cartes(GID, seulement="T1")
    posts = [kw["json"] for m, ch, kw in APPELS if m == "POST" and ch == "/channels/T1/messages"]
    check("carte : essai sur UN ticket — le formulaire vide, « Prendre une adresse » seul",
          b["posees"] == ["T1"] and len(posts) == 1
          and textes_v2(posts[0]["components"]) == ["## Adresses Outlook", "📧 " + ox.BLANC,
                                                    "🔑 " + ox.BLANC, "🔐 " + ox.BLANC_CODE]
          and ids(posts[0]["components"]) == ["mailx:prendre"], (b, posts))
    r = clic_carte("mailx:prendre")
    check("carte : coffre vide — dit DANS la carte (type 7), staff prévenu, aucun message privé",
          r["type"] == 7 and any("coffre d'adresses Outlook est vide" in t for t in textes_v2(r["data"]["components"]))
          and len(ALERTES) == 1, (r, ALERTES))
    for i in range(5):
        oc.ajouter(f"carte{i + 1}@outlook.com", f"MdpCarte{i + 1}!", SEED)
    APPELS.clear()
    r = clic_carte("mailx:prendre")
    code_attendu, _ = totp.code_totp(SEED)
    tx = textes_v2(r["data"]["components"])
    check("carte : une adresse — changée sur place, adresse, mot de passe et code du moment",
          r["type"] == 7 and "📧 `carte1@outlook.com`" in tx and "🔑 `MdpCarte1!`" in tx
          and any(code_attendu in t for t in tx) and SEED not in json.dumps(r), tx)
    caches = [kw["json"] for m, ch, kw in APPELS if m == "PATCH" and ch == "/channels/T1/messages/carte-T1"]
    check("carte : le code repart de lui-même (case vide), l'adresse reste",
          caches and "🔐 " + ox.BLANC_CODE in textes_v2(caches[-1]["components"])
          and "📧 `carte1@outlook.com`" in textes_v2(caches[-1]["components"]), caches)
    depots = [kw["json"]["content"] for m, ch, kw in APPELS
              if m == "POST" and ch == f"/channels/{TICKET}/messages"]
    check("carte : l'adresse et le mot de passe partent aussi seuls dans le salon perso (copie sur téléphone)",
          list(dict.fromkeys(depots)) == ["carte1@outlook.com", "MdpCarte1!"], depots)  # faux : journal en double
    r = clic_carte("mailx:2fa")
    check("carte : « Code 2FA » montre les codes sur place", r["type"] == 7
          and any(code_attendu in t for t in textes_v2(r["data"]["components"])), r)
    clic_carte("mailx:prendre")
    clic_carte("mailx:prendre")
    r = clic_carte("mailx:prendre")
    check("carte : 4e adresse du jour — le refus est écrit dans la carte",
          r["type"] == 7 and any("3 adresses aujourd'hui" in t for t in textes_v2(r["data"]["components"])), r)
    ox.poser_cartes(GID, seulement="T2")
    r = clic_carte("mailx:prendre", salon="T2", uid=CHEF, perms=str(0x8))
    check("carte : le manager clique dans le ticket d'un VA — l'adresse est au VA, pas au manager",
          oc.comptes_du_va(VA2, GID) and not oc.comptes_du_va(CHEF, GID), oc.comptes())
    p_menu = {"type": 3, "guild_id": GID, "channel_id": SALON, "application_id": APP, "token": "tm",
              "data": {"custom_id": "mailx:menu"},
              "member": {"user": {"id": VA, "username": "va"}, "roles": [], "permissions": "0"},
              "message": {"flags": ox.nx.V2}}
    r = ox.traiter(p_menu)
    check("menu : depuis le salon commun, une ligne privée avec le lien du salon perso",
          r["type"] == 4 and "<#T1>" in r["data"]["content"], r)
    check("menu : ce renvoi s'efface tout seul",
          ("DELETE", f"/webhooks/{APP}/tm/messages/@original") in [(m, ch) for m, ch, kw in APPELS], APPELS)
    r = ox.traiter(dict(p_menu, channel_id="T1"))
    check("menu : le bouton « 📧 Outlook » du menu épinglé — la carte descend, sans message",
          r == {"type": 6}, r)
    r = ox.traiter(dict(p_menu, member={"user": {"id": CHEF, "username": "chef"}, "roles": [],
                                        "permissions": str(0x8)}))
    check("menu : sans salon perso (le staff), ses adresses s'ouvrent en privé",
          r["type"] == 4 and r["data"]["flags"] == ox.nx.V2 | ox.nx.EPHEMERE
          and textes_v2(r["data"]["components"])[0] == "## Adresses Outlook", r)
    r = ox.traiter(dict(p_menu, member={"user": {"id": CHEF, "username": "chef"}, "roles": [],
                                        "permissions": str(0x8)}, message={"flags": 64}))
    check("menu : le « 📧 Outlook » du menu privé (message classique) ouvre ses adresses à part",
          r["type"] == 4 and r["data"]["flags"] == ox.nx.V2 | ox.nx.EPHEMERE, r)
    check("carte Outlook : l'accueil du ticket (« mailx:menu ») n'est pas une carte",
          not ox.est_carte({"flags": 0, "author": {"id": MOI_TW},
                            "components": [{"type": 1, "components": [{"type": 2, "custom_id": "mailx:menu"}]}]}))
    h = json.loads(ox.FICHIER.read_text(encoding="utf-8"))
    h["cartes"]["T1"]["message"] = "accueil-T1"
    ox.FICHIER.write_text(json.dumps(h), encoding="utf-8")
    APPELS.clear()
    ox.ramener_carte(GID, VA, "T1")
    check("carte Outlook : registre faux — l'accueil n'est JAMAIS effacé",
          not [1 for m, ch, kw in APPELS if m == "DELETE" and "accueil" in ch], APPELS)
    APPELS.clear()
    print(ox.generaliser_cartes(GID))
    pan = [kw["json"] for m, ch, kw in APPELS if ch.startswith(f"/channels/{SALON}/messages")
           and m in ("POST", "PATCH")]
    check("généralisé : plus de panneau dans 📧・adresse-outlook (retiré), rien n'y est posté",
          not pan, pan)
    tickets_discord.ETAT_FICHIER = _sav_tk
    vd.api = faux_api
finally:
    (vd.api, vd._EN_FOND, oc.FICHIER, ox.FICHIER, ox._dormir, tickets_discord.role_helper,
     tickets_discord.ticket_de, numgen.ALERTES_FICHIER, numgen._en_production,
     numgen._poster_alerte) = SAV

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
