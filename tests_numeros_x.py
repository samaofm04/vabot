# -*- coding: utf-8 -*-
"""tests_numeros_x.py — « Numéro X » : un numéro HeroSMS et son code, sur YouLab TWITTER.

Rien ne part ni vers Discord ni vers HeroSMS : verif_discord.api et les appels
de numgen sont remplacés, le travail « en fond » tourne tout de suite, l'état
et l'historique vivent dans un dossier temporaire.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numgen
import numeros_x_discord as nx
import tickets_discord
import verif_discord as vd
from cogs import numeros as num

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:400]}]"))


GID, SALON, APP = vd.TWITTER_ID, "1552392915622436874", "1552153790701117480"
VA, VA2, CHEF = "111111111111111111", "222222222222222222", "333333333333333333"
APPELS, ACHATS, ANNULES, FINIS, RETRY = [], [], [], [], []
ALERTES = []                # alertes au staff (numgen.alerter_staff), rien ne part
CODES = []                  # réponses successives de get_code
REGLE = {"achat": True, "annuler": (True, "ACCESS_CANCEL"), "messages": []}


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw))
    if methode == "GET" and chemin.startswith("/channels/") and "/messages" in chemin:
        return 200, REGLE["messages"]
    if methode == "POST" and chemin == f"/channels/{SALON}/messages":
        return 200, {"id": "999"}
    return 200, {}


def faux_numero(service="tw", country="187"):
    ACHATS.append((service, country))
    if REGLE["achat"] == "NO_NUMBERS":
        return False, numgen._human("NO_NUMBERS")
    if not REGLE["achat"]:
        return False, "solde insuffisant"
    n = len(ACHATS)
    return True, {"id": f"act{n}", "phone": f"+1555000{n:04d}", "provider": "herosms",
                  "country": country}


def faux_code(act_id, provider="getatext"):
    FOURNIS.append(("code", provider))
    return CODES.pop(0) if CODES else ("wait", "")


FOURNIS = []                # (appel, fournisseur) vus par les faux de numgen


def faux_numero_getatext(service="ig", country=None):
    ACHATS.append(("getatext", service, country))
    n = len(ACHATS)
    return True, {"id": f"ga{n}", "phone": f"+1555111{n:04d}", "provider": "getatext",
                  "country": country}


def faux_annuler(act_id, provider="getatext"):
    ANNULES.append(act_id)
    return REGLE["annuler"]


def faux_finir(act_id, provider="getatext"):
    FINIS.append(act_id)
    return "ACCESS_ACTIVATION"


def faux_retry(act_id, provider="getatext"):
    RETRY.append(act_id)
    return True, "ACCESS_RETRY_GET"


def clic(cid, uid=VA, ephemere=False, perms="0", roles=(), gid=GID, jeton="tok"):
    p = {"type": 3, "guild_id": gid, "channel_id": SALON, "application_id": APP,
         "token": jeton, "data": {"custom_id": cid},
         "member": {"user": {"id": uid, "username": "va" + uid[:2]}, "roles": list(roles),
                    "permissions": perms}}
    if ephemere:
        p["message"] = {"flags": 64 | nx.V2}
    else:
        p["message"] = {"flags": nx.V2}
    return p


def textes(comps):
    out = []
    for c in comps or []:
        if c.get("type") == 10:
            out.append(c["content"])
        out += textes(c.get("components"))
    return out


def boutons(comps):
    return nx._ids(comps)


def dernier_patch():
    for m, ch, kw in reversed(APPELS):
        if m == "PATCH" and "/messages/@original" in ch:
            return (kw.get("json") or {}).get("components") or []
    return []


def remise_a_zero():
    """Un dossier NEUF à chaque fois : effacer le fichier ne suffit pas,
    safe_json le restaure depuis sa copie .prev."""
    for l in (APPELS, ACHATS, ANNULES, FINIS, RETRY, CODES, ALERTES):
        l.clear()
    REGLE.update(achat=True, annuler=(True, "ACCESS_CANCEL"), messages=[])
    nx._ACHATS.clear()
    nx._ECOUTES.clear()
    nx._REPRIS[0] = True
    d = Path(tempfile.mkdtemp(prefix="numx_"))
    nx.FICHIER = d / "numeros_x.json"
    num.HISTO_FILE = d / "numgen_historique.json"
    numgen.ALERTES_FICHIER = d / "numgen_alertes.json"


class _Stop(Exception):
    """Fin de l'écoute dans les tests : plus aucune réponse de HeroSMS prévue."""


def dormir(_s):
    if not CODES:
        raise _Stop()


def direct(f):
    try:
        f()
    except _Stop:
        pass

SAV = (vd.api, vd._EN_FOND, nx.FICHIER, num.HISTO_FILE, nx._dormir, tickets_discord.role_helper,
       numgen.get_number_herosms, numgen.get_code, numgen.cancel, numgen.finish, numgen.retry,
       numgen.herosms_key, numgen.ALERTES_FICHIER, numgen._en_production, numgen._poster_alerte)
try:
    vd._charger_config()
    vd.api = faux_api
    vd._EN_FOND = direct
    remise_a_zero()
    nx._dormir = dormir
    tickets_discord.role_helper = lambda gid: ""
    numgen.get_number_herosms = faux_numero
    numgen.get_code = faux_code
    numgen.cancel = faux_annuler
    numgen.finish = faux_finir
    numgen.retry = faux_retry
    numgen.herosms_key = lambda: "cle-de-test"
    numgen._en_production = lambda: True
    numgen._poster_alerte = lambda texte: (ALERTES.append(("?", texte)) or (True, ""))

    # 1. ce qui n'est pas pour nous
    check("autre bouton : rendu au module suivant", nx.traiter(clic("copie")) is None)
    check("commande slash : rendue au module suivant", nx.traiter({"type": 2, "data": {"name": "x"}}) is None)
    r = nx.traiter(clic("numx:prendre", gid="1505418484052394004"))
    check("autre serveur : refus éphémère, rien d'acheté",
          r["type"] == 4 and r["data"]["flags"] == 64 and not ACHATS, r)

    # 2. pas de clé
    numgen.herosms_key = lambda: ""
    r = nx.traiter(clic("numx:prendre"))
    check("sans clé HeroSMS : refus éphémère qui le dit, rien d'acheté",
          r["type"] == 4 and any("clé HeroSMS" in t for t in textes(r["data"]["components"]))
          and not ACHATS, r)
    numgen.herosms_key = lambda: "cle-de-test"

    # 3. le parcours : prendre, attendre, code
    remise_a_zero()
    CODES.extend([("wait", ""), ("wait", ""), ("code", "482913")])
    r = nx.traiter(clic("numx:prendre"))
    check("panneau : la réponse est un NOUVEAU message éphémère en V2",
          r["type"] == 4 and r["data"]["flags"] == nx.V2 | 64, r)
    check("panneau : « Recherche d'un numéro… » tout de suite",
          any("Recherche" in t for t in textes(r["data"]["components"])), r)
    check("achat chez HeroSMS : service tw, États-Unis", ACHATS == [("tw", "187")], ACHATS)
    patches = [kw["json"]["components"] for m, ch, kw in APPELS if m == "PATCH"]
    check("le numéro s'affiche (collé) puis le code arrive : deux éditions",
          len(patches) == 2, patches)
    t1 = textes(patches[0]) if patches else []
    check("1re édition : le numéro collé et « En attente du code… »",
          "🇺🇸 `+15550000001`" in t1 and any("En attente du code" in t for t in t1), t1)
    check("1re édition : Redemander / Autre / Annuler, liés au numéro",
          boutons(patches[0]) == ["numx:retry:act1", "numx:autre:act1", "numx:annuler:act1"]
          if patches else False, patches)
    t2 = textes(patches[1]) if len(patches) > 1 else []
    check("2e édition : 🇺🇸 🔑 Code : `482913`", "🔐 **482913**" in t2, t2)
    check("2e édition : C'est bon / Nouveau code / Autre",
          boutons(patches[1]) == ["numx:fini:act1", "numx:retry:act1", "numx:autre:act1"]
          if len(patches) > 1 else False, patches)
    check("l'édition vise le message éphémère du clic",
          all(ch == f"/webhooks/{APP}/tok/messages/@original" for m, ch, kw in APPELS if m == "PATCH"),
          APPELS)
    h = num._histo_lire()
    check("historique de Va IG : la prise est notée sur le serveur Twitter, avec son code",
          len(h) == 1 and h[0]["serveur"] == GID and str(h[0]["par"]) == VA
          and h[0]["fournisseur"] == "herosms" and h[0]["service"] == "tw" and h[0].get("code_le"), h)
    check("quota : ce numéro compte (numeros_du_jour de Va IG)", num.numeros_du_jour(VA, GID) == 1)

    # 4. un second clic ne rachète pas
    r = nx.traiter(clic("numx:prendre", jeton="tok2"))
    check("second clic : le même numéro, avec son code, sans nouvel achat",
          len(ACHATS) == 1 and "🔐 **482913**" in textes(r["data"]["components"]), r)
    check("second clic : le message retenu est le nouveau", nx._message(f"{GID}:{VA}")["jeton"] == "tok2")
    check("second clic : l'ancien message est effacé (un seul message à l'écran)",
          ("DELETE", f"/webhooks/{APP}/tok/messages/@original") in [(m, ch) for m, ch, kw in APPELS], APPELS)
    n_del = len([1 for m, *_ in APPELS if m == "DELETE"])
    r = nx.traiter(clic("numx:prendre", jeton="tok3", ephemere=True))
    check("clic depuis le message lui-même : changé sur place, rien d'effacé",
          r["type"] == 7 and len([1 for m, *_ in APPELS if m == "DELETE"]) == n_del, r)

    # 5. C'est bon
    n_patch = len([1 for m, *_ in APPELS if m == "PATCH"])
    r = nx.traiter(clic("numx:fini:act1", ephemere=True))
    check("C'est bon : le message éphémère est remplacé sur place (type 7)",
          r["type"] == 7 and "numx:prendre" in boutons(r["data"]["components"]), r)
    check("C'est bon : activation close chez HeroSMS", FINIS == ["act1"], FINIS)
    check("C'est bon : fini noté", bool(num._histo_lire()[0].get("fini_le")))

    # 6. Annuler, Autre
    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    r = nx.traiter(clic("numx:annuler:act1", ephemere=True))
    check("Annuler : réponse immédiate « Annulation… », sans bouton",
          r["type"] == 7 and any("Annulation" in t for t in textes(r["data"]["components"]))
          and not boutons(r["data"]["components"]), r)
    check("Annuler : rendu à HeroSMS", ANNULES == ["act1"], ANNULES)
    check("Annuler : « Numéro annulé. » et le bouton pour en reprendre un",
          any("annulé" in t for t in textes(dernier_patch())) and boutons(dernier_patch()) == ["numx:prendre"],
          dernier_patch())
    check("Annuler : noté à l'historique", bool(num._histo_lire()[0].get("annule_le")))

    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    nx.traiter(clic("numx:autre:act1", ephemere=True))
    check("Autre : l'ancien est rendu, un nouveau est acheté",
          ANNULES == ["act1"] and len(ACHATS) == 2, (ANNULES, ACHATS))
    check("Autre : le nouveau numéro s'affiche", "🇺🇸 `+15550000002`" in textes(dernier_patch()),
          dernier_patch())
    check("Autre : l'ancien bouton ne touche plus le nouveau numéro",
          nx.traiter(clic("numx:annuler:act1", ephemere=True))["type"] == 7 and len(ANNULES) == 1, ANNULES)

    # 7. rendu refusé (trop tôt) : le numéro reste, avec la raison
    remise_a_zero()
    REGLE["annuler"] = (False, "annulation trop tôt — attends ~2 min")
    nx.traiter(clic("numx:prendre"))
    nx.traiter(clic("numx:annuler:act1", ephemere=True))
    a = nx._actif(f"{GID}:{VA}")
    check("rendu refusé : le numéro reste actif, la raison est affichée",
          not a.get("clos") and any("trop tôt" in t for t in textes(dernier_patch()))
          and "numx:annuler:act1" in boutons(dernier_patch()), (a, dernier_patch()))

    # 8. C'est bon sans code ne lâche pas un numéro payé
    r = nx.traiter(clic("numx:fini:act1", ephemere=True))
    check("C'est bon sans code : rien n'est clos", not FINIS and not nx._actif(f"{GID}:{VA}").get("clos"),
          FINIS)

    # 9. quota : 3 codes par jour pour un VA, pas pour le staff
    remise_a_zero()
    for _ in range(3):
        nx.traiter(clic("numx:prendre"))
        nx.traiter(clic("numx:annuler:act%d" % len(ACHATS), ephemere=True))
    r = nx.traiter(clic("numx:prendre"))
    check("3 numéros annulés sans code ne comptent pas : le 4e est acheté",
          len(ACHATS) == 4 and r["type"] == 4, (ACHATS, r))
    nx.traiter(clic("numx:annuler:act4", ephemere=True))
    check("Annuler sans code : « il ne compte pas » affiché",
          any("ne compte pas" in t for t in textes(dernier_patch())), dernier_patch())
    remise_a_zero()
    for i in range(1, 4):
        nx.traiter(clic("numx:prendre"))
        CODES.append(("code", "11111%d" % i))
        direct(lambda: nx._ecouter(f"{GID}:{VA}", "act%d" % i, nx.SERVEURS[GID]))
        nx.traiter(clic("numx:fini:act%d" % i, ephemere=True))
    r = nx.traiter(clic("numx:prendre"))
    check("4e numéro après 3 codes reçus : refus « 3 codes reçus aujourd'hui », rien d'acheté",
          r["type"] == 4 and any("3 codes reçus aujourd'hui" in t for t in textes(r["data"]["components"]))
          and len(ACHATS) == 3, r)
    r = nx.traiter(clic("numx:prendre", uid=VA2))
    check("un autre VA a son propre compte", len(ACHATS) == 4, ACHATS)
    for i in range(5, 8):
        nx.traiter(clic("numx:prendre", uid=CHEF, perms=str(0x8)))
        CODES.append(("code", "22222%d" % i))
        direct(lambda: nx._ecouter(f"{GID}:{CHEF}", "act%d" % i, nx.SERVEURS[GID]))
        nx.traiter(clic("numx:fini:act%d" % i, uid=CHEF, perms=str(0x8), ephemere=True))
    nx.traiter(clic("numx:prendre", uid=CHEF, perms=str(0x8)))
    check("le staff n'est pas bridé (4e numéro accepté après 3 codes)", len(ACHATS) == 8, ACHATS)
    check("quota : un numéro en attente de code compte", num.numeros_du_jour(VA2, GID) == 1)
    h = num._histo_lire()
    h[-1].update(fournisseur="getatext", serveur="1505418484052394004", annule_le=int(time.time()))
    num._histo_ecrire(h)
    check("quota : hors des panneaux REST (Va IG FR), un numéro GetAText annulé sans code compte encore",
          num.numeros_du_jour(CHEF, "1505418484052394004") == 1,
          num.numeros_du_jour(CHEF, "1505418484052394004"))

    # 10. historique illisible : aucun achat
    remise_a_zero()
    from unittest import mock
    with mock.patch.object(num, "numeros_du_jour", side_effect=ValueError("illisible")):
        r = nx.traiter(clic("numx:prendre"))
    check("historique illisible : refus, rien d'acheté",
          any("historique" in t for t in textes(r["data"]["components"])) and not ACHATS, r)

    # 11. achat refusé par HeroSMS
    remise_a_zero()
    REGLE["achat"] = False
    nx.traiter(clic("numx:prendre"))
    nx.traiter(clic("numx:prendre"))
    check("achat refusé, solde vide : le VA lit « sans crédit, le staff est prévenu », avec le bouton",
          any("sans crédit" in t and "staff est prévenu" in t for t in textes(dernier_patch()))
          and boutons(dernier_patch()) == ["numx:prendre"], dernier_patch())
    check("solde vide : le staff est prévenu une fois, pas à chaque clic (2 clics, 1 alerte)",
          len(ALERTES) == 1 and "HeroSMS sans crédit" in ALERTES[0][1]
          and "credit:herosms" in numgen._alertes(), ALERTES)
    check("achat refusé : rien au registre ni à l'historique",
          nx._actif(f"{GID}:{VA}") is None and num._histo_lire() == [])
    REGLE["achat"] = "NO_NUMBERS"
    nx.traiter(clic("numx:prendre"))
    check("achat refusé pour une autre raison : la raison telle quelle",
          any("aucun numéro" in t for t in textes(dernier_patch())), dernier_patch())
    REGLE["achat"] = True
    nx.traiter(clic("numx:prendre"))
    check("le service revient : l'alerte est levée, la prochaine panne sera redite",
          "credit:herosms" not in numgen._alertes(), numgen._alertes())

    # 11 bis. un clic pendant l'achat ne crée ni n'efface aucun message
    remise_a_zero()
    nx._ACHATS.add(f"{GID}:{VA}")
    r = nx.traiter(clic("numx:prendre", jeton="tokB"))
    check("clic pendant l'achat : simplement accusé (type 6), rien d'acheté ni d'effacé",
          r == {"type": 6} and not ACHATS and not any(m == "DELETE" for m, *_ in APPELS), r)
    nx._ACHATS.clear()

    # 11 ter. un numéro du premier jour (jeton rangé dans l'activation)
    remise_a_zero()
    nx._ecrire({"actifs": {f"{GID}:{VA}": {"id": "vieux", "provider": "herosms", "valeur": "+15559990000",
                                           "par": VA, "pris_le": int(time.time()), "jeton": "tokV",
                                           "jeton_le": time.time(), "app": APP}}})
    CODES.append(("code", "135790"))
    nx._ecouter(f"{GID}:{VA}", "vieux", nx.SERVEURS[GID])
    check("ancien format : le code s'affiche dans le message de son jeton",
          any(m == "PATCH" and ch == f"/webhooks/{APP}/tokV/messages/@original" for m, ch, kw in APPELS)
          and "🔐 **135790**" in textes(dernier_patch()), APPELS)

    # 12. Nouveau code
    remise_a_zero()
    CODES.extend([("code", "111111"), ("wait", ""), ("code", "222222")])
    nx.traiter(clic("numx:prendre"))
    r = nx.traiter(clic("numx:retry:act1", ephemere=True))
    check("Nouveau code : demandé à HeroSMS", RETRY == ["act1"], RETRY)
    check("Nouveau code : le nouveau code s'affiche", "🔐 **222222**" in textes(dernier_patch()),
          dernier_patch())

    # 13. expiration : 20 min sans code
    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    d = json.loads(nx.FICHIER.read_text(encoding="utf-8"))
    d["actifs"][f"{GID}:{VA}"]["pris_le"] = int(time.time()) - nx.DUREE_NUMERO_SEC - 5
    nx.FICHIER.write_text(json.dumps(d), encoding="utf-8")
    nx._ecouter(f"{GID}:{VA}", "act1", nx.SERVEURS[GID])
    check("20 min sans code : numéro rendu et clos, le VA le lit",
          "act1" in ANNULES and nx._actif(f"{GID}:{VA}").get("clos") == "expire"
          and any("Aucun code" in t for t in textes(dernier_patch())), dernier_patch())
    r = nx.traiter(clic("numx:prendre"))
    check("après expiration : un nouveau numéro est acheté", len(ACHATS) == 2, ACHATS)
    check("nouvelle activation : aucun jeton rangé dedans (un seul message, ailleurs)",
          "jeton" not in nx._actif(f"{GID}:{VA}"), nx._actif(f"{GID}:{VA}"))

    # 14. jeton périmé : pas d'édition (Discord la refuserait)
    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    d = json.loads(nx.FICHIER.read_text(encoding="utf-8"))
    d["messages"][f"{GID}:{VA}"]["le"] = time.time() - 16 * 60
    nx.FICHIER.write_text(json.dumps(d), encoding="utf-8")
    n_av = len(APPELS)
    check("jeton de plus de 15 min : aucune édition tentée",
          nx._redessiner(f"{GID}:{VA}", nx.SERVEURS[GID]) == 0 and len(APPELS) == n_av)

    # 15. redémarrage : l'écoute reprend au premier clic
    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    nx._ECOUTES.clear()
    nx._REPRIS[0] = False
    CODES.append(("code", "777777"))
    nx.traiter(clic("numx:prendre", uid=VA2))
    check("après un redémarrage, le code d'un numéro en attente s'affiche",
          nx._actif(f"{GID}:{VA}").get("code") == "777777", nx._actif(f"{GID}:{VA}"))

    # 15 bis. ... et dès le démarrage du site, sans attendre un clic
    remise_a_zero()
    nx.traiter(clic("numx:prendre"))
    nx._ECOUTES.clear()
    nx._REPRIS[0] = False
    CODES.append(("code", "246802"))
    _sav_dormir, _sav_thread = nx._dormir, nx.threading.Thread
    nx._dormir = lambda s: None

    class _FilDirect:
        def __init__(self, target, daemon=None):
            self.t = target

        def start(self):
            self.t()
    nx.threading.Thread = _FilDirect
    try:
        nx.demarrer()
    finally:
        nx._dormir, nx.threading.Thread = _sav_dormir, _sav_thread
    check("démarrage du site : le code d'un numéro en attente s'affiche sans clic",
          nx._actif(f"{GID}:{VA}").get("code") == "246802", nx._actif(f"{GID}:{VA}"))
    src_w = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
    check("démarrage du site : branché à côté des autres démons",
          "_nx_boot.demarrer()" in src_w)

    # 16. le panneau du salon
    remise_a_zero()
    print(nx.poser_panneau(GID))
    posts = [kw["json"] for m, ch, kw in APPELS if m == "POST"]
    check("panneau absent : posé en V2, un seul bouton « Prendre un numéro »",
          len(posts) == 1 and posts[0]["flags"] == nx.V2 and boutons(posts[0]["components"]) == ["numx:prendre"]
          and textes(posts[0]["components"])[0] == "## Numéro X"
          and all(t.endswith("\u00a0`") for t in textes(posts[0]["components"])[1:]), posts)
    check("panneau : les cases numéro et code sont vides, aucun texte",
          textes(posts[0]["components"]) == ["## Numéro X", "🇺🇸 " + nx.BLANC, "🔐 " + nx.BLANC_CODE], posts)
    REGLE["messages"] = [{"id": "42", "author": {"id": vd.bot_du_serveur(GID)["app_id"]},
                          "components": nx.vue_panneau()}]
    APPELS.clear()
    nx.poser_panneau(GID)
    check("panneau présent : remis à neuf, jamais un second",
          [(m, ch) for m, ch, kw in APPELS if m in ("POST", "PATCH")] == [("PATCH", f"/channels/{SALON}/messages/42")],
          APPELS)

    # 17. HeroSMS : refus en JSON ramenés au protocole
    numgen.get_number_herosms, numgen.get_code = SAV[6], SAV[7]
    check("HeroSMS : refus JSON lu comme BAD_KEY",
          numgen._human(numgen._texte_herosms('{"title":"BAD_KEY","details":"Unauthorized"}')) == "clé API refusée")
    check("HeroSMS : un texte du protocole passe tel quel",
          numgen._texte_herosms("ACCESS_NUMBER:1:15551234567") == "ACCESS_NUMBER:1:15551234567")
    _sav_stubs = numgen._stubs
    numgen._stubs = lambda prov, action, **kw: "ACCESS_NUMBER:987:15551234567" if prov == "herosms" else "X"
    check("HeroSMS : getNumber -> numéro avec +, fournisseur herosms",
          numgen.get_number_herosms("tw", "187") == (True, {"id": "987", "phone": "+15551234567",
                                                             "provider": "herosms", "country": "187"}))
    numgen._stubs = lambda prov, action, **kw: "NO_NUMBERS"
    check("HeroSMS : pas de numéro -> message lisible, aucun autre pays essayé",
          numgen.get_number_herosms("tw", "187") == (False, numgen._human("NO_NUMBERS")))
    numgen._stubs = _sav_stubs
    check("status : herosms_ok hors de sms_ok", "herosms_ok" in numgen.status())

    # 18. la route du site passe le clic au module
    src = (Path(__file__).resolve().parent / "web_upload.py").read_text(encoding="utf-8")
    i_nx, i_vd = src.find("import numeros_x_discord as _nx"), src.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route /discord/interactions : « numx: » traité avant la vérification", 0 < i_nx < i_vd)

    # 19. le récap « debrief-day » de Twitter, posté par REST (Luigi)
    remise_a_zero()
    d = Path(tempfile.mkdtemp(prefix="numx_recap_"))
    _sav_recap = nx.RECAP_FICHIER
    nx.RECAP_FICHIER = d / "numeros_x_recap.json"
    MOI = vd.bot_du_serveur(GID)["app_id"]
    DEBRIEF = "777000000000000001"
    ETAT = {"salons": [{"id": "1", "type": 0, "name": "📱・numéro-usa", "position": 1}],
            "messages": [], "n": 0}

    def api_recap(methode, chemin, **kw):
        APPELS.append((methode, chemin, kw))
        if methode == "GET" and chemin == f"/guilds/{GID}/channels":
            return 200, ETAT["salons"]
        if methode == "GET" and chemin.startswith(f"/guilds/{GID}/members/"):
            return 200, {"nick": "Freezy", "user": {"id": chemin.rsplit("/", 1)[1], "username": "fz"}}
        if methode == "GET" and chemin.startswith(f"/channels/{DEBRIEF}/messages"):
            return 200, ETAT["messages"]
        if methode == "POST" and chemin == f"/channels/{DEBRIEF}/messages":
            ETAT["n"] += 1
            return 200, {"id": "9%d" % ETAT["n"]}
        if methode == "PATCH" and chemin.startswith(f"/channels/{DEBRIEF}/messages/"):
            return 200, {"id": chemin.rsplit("/", 1)[1]}
        return 404, {"message": "inconnu"}

    def ecrits():
        return [(m, ch) for m, ch, kw in APPELS if m in ("POST", "PATCH")]

    def corps(kw):
        if "json" in kw:
            return kw["json"]
        return json.loads(kw["data"]["payload_json"])

    vd.api = api_recap
    numgen.get_number_herosms, numgen.get_code = faux_numero, faux_code
    _sav_mp = num.machine_prod
    num.machine_prod = lambda: True
    nx._SALONS.clear()
    nx._NOMS.clear()
    nx._RECAP.update(gen=None, jour=None, reveil=0.0)
    maintenant = time.time()
    hier = maintenant - 86400
    # un numéro d'hier (code reçu), pris avant que le salon existe
    num.histo_prise({"id": "h1", "kind": "sms", "provider": "herosms", "service": "tw",
                     "valeur": "+15550001111", "par": VA, "pris_le": int(hier)},
                    channel=nx.SimpleNamespace(id=SALON, guild=nx.SimpleNamespace(id=GID)),
                    user=nx.SimpleNamespace(id=VA, display_name="Freezy"), maintenant=hier)
    num.histo_evenement("sms", "h1", "code", maintenant=hier + 60)
    b = nx.recap_tour(maintenant, forcer=True)
    nx._SALONS.clear()
    b2 = nx.recap_tour(maintenant + 61, forcer=True)
    reg = json.loads(nx.RECAP_FICHIER.read_text(encoding="utf-8"))
    check("récap Twitter : sans salon « debrief-day », rien n'est posté",
          GID in b["sans_salon"] and not ecrits(), ecrits())
    check("récap Twitter : l'absence du salon est retenue (dite une fois, même après un redémarrage)",
          reg["dits"].get(f"salon:{GID}") == "absent" and GID in b2["sans_salon"], reg)

    ETAT["salons"].append({"id": DEBRIEF, "type": 0, "name": "📊・debrief-day", "position": 5})
    nx._SALONS.clear()
    APPELS.clear()
    b = nx.recap_tour(maintenant + 120, forcer=True)
    posts = [kw for m, ch, kw in APPELS if m == "POST"]
    check("récap Twitter : le salon créé, la veille (avec ses numéros) puis le jour sont postés",
          len(b["postes"]) == 2 and len(posts) == 2
          and [c for c, g in b["postes"]] == sorted(c for c, g in b["postes"]), (b, ecrits()))
    check("récap Twitter : messages V2, sans mention",
          all(corps(kw).get("flags") == nx.V2 and corps(kw)["allowed_mentions"] == {"parse": []}
              for kw in posts), [corps(kw) for kw in posts])
    titres = [t for kw in posts for t in textes(corps(kw)["components"]) if t.startswith("## ")]
    check("récap Twitter : le même titre que le récap d'origine",
          any(t.startswith("## " + num.titre_recap(num.jour_benin(hier), False)) for t in titres), titres)
    APPELS.clear()
    b = nx.recap_tour(maintenant + 180, forcer=True)
    check("récap Twitter : sans nouveau chiffre, aucune écriture", not ecrits(), ecrits())
    nx.traiter(clic("numx:prendre", uid=VA2))
    APPELS.clear()
    b = nx.recap_tour(maintenant + 240)
    check("récap Twitter : un numéro de plus ÉDITE le message du jour (jamais un second)",
          b["edites"] and not b["postes"]
          and [m for m, ch in ecrits()] == ["PATCH"], (b, ecrits()))
    reg = json.loads(nx.RECAP_FICHIER.read_text(encoding="utf-8"))
    cle_hier = num.jour_benin(hier).isoformat()
    check("récap Twitter : la veille est figée au registre", reg["jours"][cle_hier][GID].get("fige"), reg)
    # registre perdu : le message est retrouvé dans le salon, pas reposté
    nx.RECAP_FICHIER.unlink()
    for suffixe in (".prev",):
        p_prev = nx.RECAP_FICHIER.with_name(nx.RECAP_FICHIER.name + suffixe)
        if p_prev.exists():
            p_prev.unlink()
    ETAT["messages"] = [{"id": "92", "author": {"id": MOI},
                         "attachments": [{"filename": num.NOM_IMAGE_RECAP % num.jour_benin(maintenant).isoformat()}],
                         "components": [{"type": 10, "content": "## " + num.titre_recap(num.jour_benin(maintenant), False)}]},
                        {"id": "91", "author": {"id": MOI},
                         "attachments": [{"filename": num.NOM_IMAGE_RECAP % cle_hier}],
                         "components": [{"type": 10, "content": "## " + num.titre_recap(num.jour_benin(hier), False)}]}]
    APPELS.clear()
    nx._RECAP.update(gen=None)
    b = nx.recap_tour(maintenant + 300, forcer=True)
    check("récap Twitter : registre perdu, les messages sont retrouvés et édités, aucun reposté",
          not [1 for m, ch in ecrits() if m == "POST"] and ecrits(), ecrits())
    APPELS.clear()
    b = nx.recap_tour(maintenant + 360)
    check("récap Twitter : un tour sans événement ne relit rien et n'écrit rien",
          not APPELS or all(m == "GET" for m, ch, kw in APPELS), APPELS)
    num.machine_prod = lambda: False
    APPELS.clear()
    nx.traiter(clic("numx:prendre", uid=CHEF, perms=str(0x8)))
    APPELS.clear()
    b = nx.recap_tour(maintenant + 420)
    check("récap Twitter : hors du VPS, rien ne part", not ecrits(), ecrits())
    num.machine_prod = _sav_mp
    nx.RECAP_FICHIER = _sav_recap
    vd.api = faux_api

    # 21. le même panneau sur YouLab THREADS : Instagram chez GetAText, son propre quota
    remise_a_zero()
    numgen.get_number_herosms, numgen.get_code = faux_numero, faux_code
    _sav_gn, _sav_gk = numgen.get_number, numgen.getatext_key
    numgen.get_number, numgen.getatext_key = faux_numero_getatext, (lambda: "cle-ga")
    TH = vd.THREADS_ID
    r = nx.traiter(clic("numx:prendre", gid=TH))
    check("Threads : le numéro est pris chez GetAText (comme Instagram), service Instagram, États-Unis",
          ACHATS == [("getatext", "ig", "187")], ACHATS)
    check("Threads : la carte Instagram, « …. » pendant la recherche, puis le numéro en gros",
          textes(r["data"]["components"])[:2] == ["## `….`", "🇺🇸 ⏳ Recherche d'un numéro…"]
          and textes(dernier_patch())[:2] == ["## `+15551110001`", "🇺🇸 ⏳ En attente du code…"],
          (r, dernier_patch()))
    check("Threads : en attente, « Redemander un code » (bleu) · « Autre » · « Annuler » (rouge)",
          boutons(dernier_patch()) == ["numx:retry:ga1", "numx:autre:ga1", "numx:annuler:ga1"]
          and [b["style"] for b in dernier_patch()[0]["components"][1]["components"]] == [1, 2, 4],
          dernier_patch())
    carte = dernier_patch()[0]
    vignette = (carte["components"][0].get("accessory") or {}).get("media", {}).get("url", "")
    check("Threads : carte rose, l'icône Instagram en vignette, servie par le site (versionnée)",
          carte["accent_color"] == nx.ROSE and carte["components"][0]["type"] == 9
          and vignette.startswith(vd.SITE.rstrip("/") + "/static/numeros/numero_instagram.png?v="),
          carte)
    check("Threads : l'icône existe dans static/ (sinon 404 gardé 7 jours par Cloudflare)",
          (Path(__file__).resolve().parent / "static/numeros/numero_instagram.png").is_file())
    a = nx._actif(f"{TH}:{VA}")
    check("Threads : noté à l'historique sur le serveur Threads",
          a and num._histo_lire()[0]["serveur"] == TH and num._histo_lire()[0]["service"] == "ig",
          num._histo_lire())
    CODES.append(("code", "135790"))
    direct(lambda: nx._ecouter(f"{TH}:{VA}", a["id"], nx.SERVEURS[TH]))
    check("Threads : le code arrive dans LA MÊME carte, sous le numéro",
          textes(dernier_patch())[:2] == ["## `+15551110001`", "🇺🇸 🔑 **Code : `135790`**"]
          and boutons(dernier_patch()) == ["numx:fini:ga1", "numx:retry:ga1", "numx:autre:ga1"],
          dernier_patch())
    check("Threads : le quota de Twitter n'est pas touché",
          num.numeros_du_jour(VA, TH) == 1 and num.numeros_du_jour(VA, GID) == 0)
    APPELS.clear()
    print(nx.poser_panneau(TH))
    posts = [(ch, kw["json"]) for m, ch, kw in APPELS if m == "POST"]
    check("Threads : dans 📱・numéro-usa, la carte vide « …. » · en attente · « Prendre un numéro » bleu",
          len(posts) == 1 and posts[0][0] == "/channels/%s/messages" % nx.SERVEURS[TH]["salon"]
          and textes(posts[0][1]["components"]) == ["## `….`", "🇺🇸 ⏳ En attente"]
          and boutons(posts[0][1]["components"]) == ["numx:prendre"]
          and posts[0][1]["components"][0]["components"][1]["components"][0]["style"] == 1, posts)
    check("Twitter : toujours « Numéro X »", textes(nx.vue_panneau(nx.SERVEURS[GID]))[0] == "## Numéro X")
    check("Threads : le code est lu chez GetAText, pas chez HeroSMS",
          FOURNIS and FOURNIS[-1] == ("code", "getatext"), FOURNIS[-3:])
    FIN = len(ANNULES)
    nx.traiter(clic("numx:prendre", gid=TH, uid=VA2))
    a2 = nx._actif(f"{TH}:{VA2}")
    nx.traiter(clic("numx:annuler:%s" % a2["id"], gid=TH, uid=VA2, ephemere=True))
    check("Threads : Annuler rend le numéro (chez GetAText) et il ne compte pas",
          ANNULES[FIN:] == [a2["id"]] and num.numeros_du_jour(VA2, TH) == 0
          and any("ne compte pas" in t for t in textes(dernier_patch())), (ANNULES, dernier_patch()))
    check("Threads : après Annuler, la carte redevient vide, prête pour un autre numéro",
          textes(dernier_patch())[:2] == ["## `….`", "🇺🇸 ⏳ En attente"]
          and boutons(dernier_patch()) == ["numx:prendre"], dernier_patch())
    numgen.get_number, numgen.getatext_key = _sav_gn, _sav_gk

    # 22. Threads : UNE carte dans le ticket de chaque VA, changée sur place
    remise_a_zero()
    numgen.get_number, numgen.getatext_key = faux_numero_getatext, (lambda: "cle-ga")
    numgen.get_code = faux_code
    TH = vd.THREADS_ID
    dt = Path(tempfile.mkdtemp(prefix="numx_tickets_"))
    _sav_tk = tickets_discord.ETAT_FICHIER
    tickets_discord.ETAT_FICHIER = dt / "tickets.json"
    tickets_discord.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{TH}:{VA}": {"salon": "T1", "manager": CHEF}, f"{TH}:{VA2}": {"salon": "T2"},
        f"{TH}:444444444444444444": {"salon": "T3"},
        f"{GID}:{VA}": {"salon": "TW1"}}}), encoding="utf-8")

    def api_cartes(methode, chemin, **kw):
        APPELS.append((methode, chemin, kw))
        if methode == "POST" and chemin in ("/channels/T1/messages", "/channels/T2/messages"):
            return 200, {"id": "carte-" + chemin.split("/")[2]}
        if methode == "GET" and chemin.startswith("/channels/T") and "?limit" in chemin:
            return 200, []
        if methode == "GET" and chemin == f"/guilds/{TH}/members/444444444444444444":
            return 404, {"message": "Unknown Member"}
        return faux_api(methode, chemin, **kw)
    vd.api = api_cartes

    def clic_carte(cid, salon="T1", uid=VA, perms="0"):
        p = clic(cid, uid=uid, gid=TH, perms=perms)
        p["channel_id"] = salon
        p["message"] = {"id": "carte-" + salon, "flags": nx.V2}
        return p

    def patch_carte(salon="T1"):
        for m, ch, kw in reversed(APPELS):
            if m == "PATCH" and ch == f"/channels/{salon}/messages/carte-{salon}":
                return kw["json"]["components"]
        return []

    b = nx.poser_cartes(TH, seulement="T1")
    posts = [(ch, kw["json"]) for m, ch, kw in APPELS if m == "POST"]
    check("ticket : essai sur UN ticket — sa carte vide « …. », « Prendre un numéro », rien ailleurs",
          b["posees"] == ["T1"] and len(posts) == 1 and posts[0][0] == "/channels/T1/messages"
          and textes(posts[0][1]["components"]) == ["## `….`", "🇺🇸 ⏳ En attente"]
          and boutons(posts[0][1]["components"]) == ["numx:prendre"], (b, posts))
    APPELS.clear()
    b = nx.poser_cartes(TH)
    check("ticket : les autres tickets de Threads reçoivent la leur, jamais une seconde, Twitter non",
          b["posees"] == ["T2"] and b["deja"] == 1 and b["partis"] == ["T3"]
          and [ch for m, ch, kw in APPELS if m == "POST"] == ["/channels/T2/messages"], (b, APPELS))
    APPELS.clear()
    r = nx.traiter(clic_carte("numx:prendre"))
    check("ticket : le clic change la carte SUR PLACE (type 7), aucun message éphémère",
          r["type"] == 7 and textes(r["data"]["components"])[:2] == ["## `….`", "🇺🇸 ⏳ Recherche d'un numéro…"]
          and not any("/webhooks/" in ch for m, ch, kw in APPELS), (r, APPELS))
    check("ticket : le numéro s'écrit dans la MÊME carte, par le bot",
          textes(patch_carte())[:2] == ["## `+15551110001`", "🇺🇸 ⏳ En attente du code…"]
          and not [1 for m, ch, kw in APPELS if m == "POST"], (patch_carte(), APPELS))
    CODES.append(("code", "975310"))
    direct(lambda: nx._ecouter(f"{TH}:{VA}", "ga1", nx.SERVEURS[TH]))
    check("ticket : le code arrive dans la carte",
          textes(patch_carte())[:2] == ["## `+15551110001`", "🇺🇸 🔑 **Code : `975310`**"], patch_carte())
    r = nx.traiter(clic_carte("numx:fini:ga1", uid=CHEF, perms=str(0x8)))
    check("ticket : le manager clique « C'est bon » pour son VA : c'est le numéro du VA qui se clôt",
          r["type"] == 7 and nx._actif(f"{TH}:{VA}").get("clos") == "fini"
          and boutons(r["data"]["components"]) == ["numx:prendre"], r)
    nx.traiter(clic_carte("numx:prendre", salon="T2", uid=CHEF, perms=str(0x8)))
    check("ticket : un numéro pris par le manager dans le ticket d'un VA est au VA (quota, historique)",
          nx._actif(f"{TH}:{VA2}") is not None and nx._actif(f"{TH}:{CHEF}") is None
          and num._histo_lire()[-1]["par"] == VA2, num._histo_lire()[-1])
    APPELS.clear()
    print(nx.generaliser_cartes(TH))
    panneau = [kw["json"] for m, ch, kw in APPELS
               if ch.startswith("/channels/%s/messages" % nx.SERVEURS[TH]["salon"]) and m in ("POST", "PATCH")]
    check("ticket : généralisé — le panneau de 📱・numéro-usa n'est plus qu'une ligne qui renvoie au salon perso",
          nx._cartes_auto(TH) and panneau and textes(panneau[-1]["components"]) == [nx.TEXTE_RENVOI]
          and not boutons(panneau[-1]["components"]), panneau)
    check("ticket : Twitter garde son panneau commun", not nx._cartes_auto(GID))
    tickets_discord.ETAT_FICHIER = _sav_tk
    numgen.get_number, numgen.getatext_key = _sav_gn, _sav_gk
    vd.api = faux_api

    # 20. le récap du bot admin ne garde plus Twitter (Luigi le poste)
    check("cog : Twitter fait partie des serveurs du récap REST", GID in num._serveurs_rest())
    check("cog : les chiffres de Twitter sont écartés de son bilan",
          num._sans_rest({GID: 1, "1535758943324999711": 2}) == {"1535758943324999711": 2})

    class _Bot:
        guilds = []
    cog = num.NumerosCog.__new__(num.NumerosCog)
    cog._recap_postes = {}
    regc = {"jours": {"2026-10-17": {GID: {"finalise": False, "sans_salon": True, "numeros": 4},
                                     "1535758943324999711": {"finalise": True}}}}
    _sav_ecr = num._recap_ecrire
    num._recap_ecrire = lambda r: None
    try:
        cog._retirer_rest(regc)
    finally:
        num._recap_ecrire = _sav_ecr
    check("cog : les vieilles fiches « sans_salon » de Twitter sortent du registre, la journée se clôt",
          GID not in regc["jours"]["2026-10-17"] and num._jour_fini(regc["jours"]["2026-10-17"]), regc)
finally:
    (vd.api, vd._EN_FOND, nx.FICHIER, num.HISTO_FILE, nx._dormir, tickets_discord.role_helper,
     numgen.get_number_herosms, numgen.get_code, numgen.cancel, numgen.finish, numgen.retry,
     numgen.herosms_key, numgen.ALERTES_FICHIER, numgen._en_production,
     numgen._poster_alerte) = SAV

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
