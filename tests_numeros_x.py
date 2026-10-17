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
CODES = []                  # réponses successives de get_code
REGLE = {"achat": True, "annuler": (True, "ACCESS_CANCEL"), "messages": []}


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw))
    if methode == "GET" and chemin.startswith(f"/channels/{SALON}/messages"):
        return 200, REGLE["messages"]
    if methode == "POST" and chemin == f"/channels/{SALON}/messages":
        return 200, {"id": "999"}
    return 200, {}


def faux_numero(service="tw", country="187"):
    ACHATS.append((service, country))
    if not REGLE["achat"]:
        return False, "solde insuffisant"
    n = len(ACHATS)
    return True, {"id": f"act{n}", "phone": f"+1555000{n:04d}", "provider": "herosms",
                  "country": country}


def faux_code(act_id, provider="getatext"):
    assert provider == "herosms", provider
    return CODES.pop(0) if CODES else ("wait", "")


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
    for l in (APPELS, ACHATS, ANNULES, FINIS, RETRY, CODES):
        l.clear()
    REGLE.update(achat=True, annuler=(True, "ACCESS_CANCEL"), messages=[])
    nx._ACHATS.clear()
    nx._ECOUTES.clear()
    nx._REPRIS[0] = True
    d = Path(tempfile.mkdtemp(prefix="numx_"))
    nx.FICHIER = d / "numeros_x.json"
    num.HISTO_FILE = d / "numgen_historique.json"


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
       numgen.herosms_key)
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
          "## `+15550000001`" in t1 and any("En attente du code" in t for t in t1), t1)
    check("1re édition : Redemander / Autre / Annuler, liés au numéro",
          boutons(patches[0]) == ["numx:retry:act1", "numx:autre:act1", "numx:annuler:act1"]
          if patches else False, patches)
    t2 = textes(patches[1]) if len(patches) > 1 else []
    check("2e édition : 🇺🇸 🔑 Code : `482913`", "🇺🇸 🔑 **Code : `482913`**" in t2, t2)
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
          len(ACHATS) == 1 and "🇺🇸 🔑 **Code : `482913`**" in textes(r["data"]["components"]), r)
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
    check("Autre : le nouveau numéro s'affiche", "## `+15550000002`" in textes(dernier_patch()),
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

    # 9. quota : 3 par jour pour un VA, pas pour le staff
    remise_a_zero()
    for _ in range(3):
        nx.traiter(clic("numx:prendre"))
        nx.traiter(clic("numx:annuler:act%d" % len(ACHATS), ephemere=True))
    r = nx.traiter(clic("numx:prendre"))
    check("4e numéro du jour : refus « 3 numéros aujourd'hui », rien d'acheté",
          r["type"] == 4 and any("3 numéros aujourd'hui" in t for t in textes(r["data"]["components"]))
          and len(ACHATS) == 3, r)
    r = nx.traiter(clic("numx:prendre", uid=VA2))
    check("un autre VA a son propre compte", len(ACHATS) == 4, ACHATS)
    for _ in range(3):
        nx.traiter(clic("numx:prendre", uid=CHEF, perms=str(0x8)))
        nx.traiter(clic("numx:annuler:act%d" % len(ACHATS), uid=CHEF, perms=str(0x8), ephemere=True))
    nx.traiter(clic("numx:prendre", uid=CHEF, perms=str(0x8)))
    check("le staff n'est pas bridé (4e numéro accepté)", len(ACHATS) == 8, ACHATS)

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
    check("achat refusé : la raison s'affiche, avec le bouton pour réessayer",
          any("solde insuffisant" in t for t in textes(dernier_patch()))
          and boutons(dernier_patch()) == ["numx:prendre"], dernier_patch())
    check("achat refusé : rien au registre ni à l'historique",
          nx._actif(f"{GID}:{VA}") is None and num._histo_lire() == [])

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
          and "🇺🇸 🔑 **Code : `135790`**" in textes(dernier_patch()), APPELS)

    # 12. Nouveau code
    remise_a_zero()
    CODES.extend([("code", "111111"), ("wait", ""), ("code", "222222")])
    nx.traiter(clic("numx:prendre"))
    r = nx.traiter(clic("numx:retry:act1", ephemere=True))
    check("Nouveau code : demandé à HeroSMS", RETRY == ["act1"], RETRY)
    check("Nouveau code : le nouveau code s'affiche", "🇺🇸 🔑 **Code : `222222`**" in textes(dernier_patch()),
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
          and textes(posts[0]["components"]) == ["## Numéro X"], posts)
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
finally:
    (vd.api, vd._EN_FOND, nx.FICHIER, num.HISTO_FILE, nx._dormir, tickets_discord.role_helper,
     numgen.get_number_herosms, numgen.get_code, numgen.cancel, numgen.finish, numgen.retry,
     numgen.herosms_key) = SAV

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
