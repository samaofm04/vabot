# -*- coding: utf-8 -*-
"""tests_ticket_allege.py — le ticket de TRUST INSTAGRAM allégé (05/11/2026).

Propriétaire : « ça tu peux remove ici, le spoofer, le download, le truc mes
stats et tout, ils sont dans outils ; garde bien contenu et passer débutant »,
puis « garder 💳 Paiement ». Le ticket perd 📈 Mes stats, 📤 Spoofer,
⬇️ Download, 📱 Numéro et sa carte numéro ; il garde son lien, sa page, son 💳,
🎬 Contenu et la rangée des managers. 📋・menu (salon commun) garde 📈.

Rien ne part vers Discord : verif_discord.api et tickets_discord._api sont
remplacés ; l'état vit dans un dossier temporaire.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import liens_va as lv
import numgen
import numeros_x_discord as nx
import tickets_discord as tk
import verif_discord as vd
from cogs import numeros as num

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:400]}]"))


AG, TW, TH = tk.AGENCY_IG_ID, tk.TWITTER_ID, tk.THREADS_ID
VA, VA2, VA3, VA5 = "4001", "4002", "4003", "4005"
RETIRES = ("subs:total:", "outk:", "numx:menu")


def ids(rangs):
    return [[b.get("custom_id") for b in r.get("components") or []] for r in rangs]


def plats(rangs):
    return [c for r in ids(rangs) for c in r]


SAV = (vd.api, tk._api, tk.ETAT_FICHIER, nx.FICHIER, lv.lien_de, lv.est_actif,
       nx._REPRIS[0], numgen.get_number, numgen.get_code, numgen.getatext_key, numgen.compte,
       vd._EN_FOND, nx._dormir, num.HISTO_FILE, numgen.ALERTES_FICHIER)
ACHATS = []


class _Stop(Exception):
    """Fin de l'écoute d'un numéro : rien ne tourne en fond après le test."""


def _direct(f):
    try:
        f()
    except _Stop:
        pass


def _stop(_s):
    raise _Stop()


try:
    vd._charger_config()
    # aucune écoute ni achat réel : les numéros fabriqués ici ne doivent rien
    # demander à GetAText
    nx._REPRIS[0] = True
    numgen.get_code = lambda act_id, provider="getatext": ("wait", "")
    numgen.get_number = lambda service="ig", country=None, cpt="": (
        ACHATS.append((service, country)) or (True, {"id": f"g{len(ACHATS)}", "phone": "+15550001",
                                                    "provider": "getatext"}))
    numgen.getatext_key = lambda: "cle-ga"
    numgen.compte = lambda gid: ""
    vd._EN_FOND = _direct
    nx._dormir = _stop
    d = Path(tempfile.mkdtemp(prefix="ticket_allege_"))
    tk.ETAT_FICHIER = d / "tickets.json"
    nx.FICHIER = d / "numeros_x.json"
    # l'historique des numéros et les alertes aussi : un achat de test ne doit
    # rien écrire dans data/ (il y comptait ensuite dans le quota du jour)
    num.HISTO_FILE = d / "numgen_historique.json"
    numgen.ALERTES_FICHIER = d / "numgen_alertes.json"

    # 1. les rangées du ticket
    print("1. le ticket")
    for confirme, lien in ((False, True), (True, False), (True, True), (False, False)):
        r = tk.boutons_va(VA, confirme=confirme, a_un_lien=lien, gid=AG)
        c = plats(r)
        complet = plats(tk._boutons_va_complets(VA, confirme=confirme, a_un_lien=lien, gid=AG))
        check(f"Agency (confirmé={confirme}, lien={lien}) : plus de 📈 📤 ⬇️ 📱",
              not [x for x in c if x.startswith(RETIRES)], c)
        check(f"… garde 💳, 🎬 et chaque bouton des managers, dans le même ordre",
              f"usdc:set:{VA}" in c and f"cnt:o:{VA}" in c
              and c == [x for x in complet if not x.startswith(RETIRES)], (c, complet))
        check("… aucune rangée vide, cinq boutons au plus par rangée",
              all(1 <= len(x) <= 5 for x in ids(r)) and len(r) <= 5, ids(r))
    r = tk.boutons_va(VA, confirme=False, a_un_lien=True, gid=AG)
    check("VA en essai avec lien : 💳 · 🎬 📷 · (🌱 Passer Débutant, 🚫 Désactiver le lien)",
          ids(r) == [[f"usdc:set:{VA}"], [f"cnt:o:{VA}", f"cpt:o:{VA}"],
                     [f"essai:deb:{VA}", f"lien:off:{VA}"]], ids(r))
    complet = plats(tk._boutons_va_complets(VA, confirme=False, a_un_lien=True, gid=AG))
    check("la rangée complète garde 📈 📤 ⬇️ 📱 (📋・menu et le menu privé du staff la lisent)",
          {f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}", "numx:menu"} <= set(complet), complet)
    for gid, nom in ((TH, "Threads"), ("1", "un autre serveur")):
        pareil = all(tk.boutons_va(VA, confirme=c, a_un_lien=l, gid=gid)
                     == tk._boutons_va_complets(VA, confirme=c, a_un_lien=l, gid=gid)
                     for c, l in ((False, True), (True, False), (False, False)))
        check(f"{nom} : rangées inchangées", pareil)
    # (son 📈 Mes stats vient d'un patch du VPS, absent ici : « inchangées » le couvre)
    # 06/11/2026 : Twitter perd 📱 et 📧 à son tour (🧰 OUTILS TWITTER), rien d'autre
    tw_t, tw_c = plats(tk.boutons_va(VA, a_un_lien=True, gid=TW)), plats(tk._boutons_va_complets(VA, a_un_lien=True, gid=TW))
    check("Twitter : le ticket perd 📱 Numéro et 📧 Outlook, et seulement eux",
          "numx:menu" not in tw_t and "mailx:menu" not in tw_t
          and tw_t == [x for x in tw_c if x not in ("numx:menu", "mailx:menu")] and "numx:menu" in tw_c, (tw_t, tw_c))
    check("BOUTONS_VERSION ≥ 12 : les accueils déjà postés seront redessinés une fois",
          tk.BOUTONS_VERSION >= 12)
    m = tk.menu_prive(AG, VA)
    c = [b["custom_id"] for r in m["data"]["components"] for b in r["components"]]
    check("menu privé du staff (pas le ticket) : inchangé, il garde 📈 📤 ⬇️ 📱",
          {f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}", "numx:menu"} <= set(c), c)

    # le menu en blocs du ticket
    corps = tk._corps_menu(AG, VA, tk.boutons_va(VA, a_un_lien=True, gid=AG))
    cids = nx._ids(corps)
    check("menu en blocs du ticket : 💳 dans sa section, 🎬, managers ; rien de retiré",
          f"usdc:set:{VA}" in cids and f"cnt:o:{VA}" in cids
          and not [x for x in cids if x.startswith(RETIRES)] and len(cids) == len(set(cids)), cids)

    # 2. le redessin des accueils déjà postés
    print("2. redessin")
    PATCHS = []

    def faux_api_tk(methode, chemin, **kw):
        if methode == "PATCH":
            PATCHS.append((chemin, kw.get("json")))
        return 200, {}
    tk._api = faux_api_tk
    lv.lien_de = lambda g, u: {"public_url": "https://gms.example/x"}
    lv.est_actif = lambda g, u: True
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{AG}:{VA}": {"salon": "S1", "accueil": "A1", "boutons": 11},
        f"{AG}:{VA2}": {"salon": "S2", "accueil": "A2", "boutons": tk.BOUTONS_VERSION},
        f"{TW}:{VA}": {"salon": "S3", "accueil": "A3", "boutons": 11}}}), encoding="utf-8")
    b = tk._redessiner_boutons_sans_menus(AG)
    p1 = [j for ch, j in PATCHS if ch == "/channels/S1/messages/A1"]
    check("l'accueil d'un ticket marqué 11 est redessiné sans 📈 📤 ⬇️ 📱",
          b["faits"] == [VA] and p1 and not [x for x in plats(p1[0]["components"]) if x.startswith(RETIRES)]
          and f"cnt:o:{VA}" in plats(p1[0]["components"]), (b, PATCHS))
    check("… un accueil déjà à jour (BOUTONS_VERSION) n'est pas touché",
          not [1 for ch, j in PATCHS if ch.endswith("/A2")], PATCHS)
    f = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))["tickets"][f"{AG}:{VA}"]
    check("… et marqué à jour (une fois)", f.get("boutons") == tk.BOUTONS_VERSION, f)
    # BOUTONS_VERSION est commun : Twitter (et Threads) sont redessinés une fois
    # aussi, avec EXACTEMENT leurs boutons d'avant
    PATCHS.clear()
    tk._redessiner_boutons_sans_menus(TW)
    p3 = [j for ch, j in PATCHS if ch == "/channels/S3/messages/A3"]
    # (depuis le 06/11, Twitter perd lui aussi 📱 et 📧 : TICKET_SANS)
    check("Twitter : redessiné une fois, sans 📱 ni 📧 (et rien d'autre de retiré)",
          p3 and p3[0]["components"] == tk.boutons_va(VA, confirme=False, a_un_lien=True, gid=TW, lien_actif=True)
          and not [x for x in plats(p3[0]["components"]) if x in ("numx:menu", "mailx:menu")], (PATCHS,))

    # 3. les cartes numéro des tickets
    print("3. cartes numéro")
    MOI = vd.bot_du_serveur(AG)["app_id"]
    APPELS = []
    MSGS = {}                 # (salon, id) -> message ; absent : 404
    LISTES = {}               # salon -> 50 derniers messages

    def carte(mid, auteur=None):
        return {"id": mid, "flags": nx.V2, "author": {"id": auteur or MOI},
                "components": nx.vue_panneau(nx.SERVEURS[AG])}

    def faux_api(methode, chemin, **kw):
        APPELS.append((methode, chemin))
        morceaux = chemin.split("?")[0].strip("/").split("/")
        if methode == "GET" and "?limit=" in chemin:
            return 200, LISTES.get(morceaux[1], [])
        if methode == "GET" and len(morceaux) == 4 and morceaux[2] == "messages":
            m = MSGS.get((morceaux[1], morceaux[3]))
            return (200, m) if m else (404, {"message": "Unknown Message"})
        if methode == "DELETE":
            MSGS.pop((morceaux[1], morceaux[3]), None)
            return 204, {}
        if methode == "POST":
            return 200, {"id": "neuf"}
        return 200, {}
    vd.api = faux_api

    def monde():
        APPELS.clear()
        MSGS.clear()
        LISTES.clear()
        tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
            f"{AG}:{VA}": {"salon": "T1"}, f"{AG}:{VA2}": {"salon": "T2"},
            f"{AG}:{VA3}": {"salon": "T3"}, f"{AG}:{VA5}": {"salon": "T5"},
            f"{TH}:{VA}": {"salon": "H1"}}}), encoding="utf-8")
        MSGS.update({("T1", "c1"): carte("c1"), ("T2", "c2"): carte("c2"),
                     ("T3", "acc3"): {"id": "acc3", "flags": 0, "author": {"id": MOI},
                                      "components": [{"type": 1, "components": [
                                          {"type": 2, "custom_id": "numx:menu"}]}]},
                     ("T5", "c5"): carte("c5"), ("H1", "h1"): carte("h1")})
        LISTES["T5"] = [{"id": "x", "flags": 0, "author": {"id": "123"}}, MSGS[("T5", "c5")]]
        # T1 : la carte du registre, et un doublon hors registre (figé sur
        # « ⏳ Recherche… », sans bouton) ; le menu en blocs n'est pas une carte
        MSGS[("T1", "c1bis")] = {"id": "c1bis", "flags": nx.V2, "author": {"id": MOI},
                                 "components": nx.vue_attente("⏳ Recherche d'un numéro…", None,
                                                              nx.SERVEURS[AG])}
        MSGS[("T1", "menu1")] = {"id": "menu1", "flags": nx.V2, "author": {"id": MOI},
                                 "components": tk._corps_menu(AG, VA, tk.boutons_va(VA, a_un_lien=True, gid=AG))}
        LISTES["T1"] = [MSGS[("T1", "menu1")], MSGS[("T1", "c1")], MSGS[("T1", "c1bis")],
                        MSGS[("T3", "acc3")]]
        now = int(time.time())
        nx.FICHIER.write_text(json.dumps({
            "cartes": {"T1": {"message": "c1", "uid": VA, "gid": AG},
                       "T2": {"message": "c2", "uid": VA2, "gid": AG},
                       "T3": {"message": "acc3", "uid": VA3, "gid": AG},
                       "H1": {"message": "h1", "uid": VA, "gid": TH}},
            "actifs": {f"{AG}:{VA2}": {"id": "n2", "valeur": "+1555", "par": VA2, "pris_le": now - 60},
                       f"{AG}:{VA}": {"id": "n1", "valeur": "+1556", "par": VA, "pris_le": now - 3600,
                                      "clos": "fini", "code": "123"}},
            "messages": {f"{AG}:{VA}": {"carte": True, "salon": "T1", "message": "c1"},
                         f"{AG}:{VA2}": {"carte": True, "salon": "T2", "message": "c2"}}}),
            encoding="utf-8")

    monde()
    b = nx.retirer_cartes(AG, essai=True, chercher=True)
    check("essai : la liste de ce qui partirait, rien de retiré ni d'écrit",
          sorted(b["retirees"]) == ["T1", "T5"] and b["cartes"] == 3 and b["en_cours"] == ["T2"]
          and b["pas_carte"] == ["T3"] and not [1 for m, ch in APPELS if m == "DELETE"]
          and set(nx._lire()["cartes"]) == {"T1", "T2", "T3", "H1"}, (b, APPELS))
    monde()
    b = nx.retirer_cartes(AG, chercher=True)
    dels = sorted(ch for m, ch in APPELS if m == "DELETE")
    check("toutes les cartes de Wario partent : registre, doublon figé « ⏳ » du même ticket, "
          "carte hors registre",
          dels == ["/channels/T1/messages/c1", "/channels/T1/messages/c1bis", "/channels/T5/messages/c5"]
          and sorted(b["retirees"]) == ["T1", "T5"] and b["cartes"] == 3, (b, dels))
    check("… jamais le menu en blocs ni l'accueil", ("T1", "menu1") in MSGS and ("T3", "acc3") in MSGS)
    check("un numéro en cours (attente de code) : sa carte reste jusqu'au tour suivant",
          b["en_cours"] == ["T2"] and "T2" in nx._lire()["cartes"]
          and nx._lire()["messages"].get(f"{AG}:{VA2}"), b)
    check("le registre pointait sur l'accueil : jamais effacé, juste oublié",
          b["pas_carte"] == ["T3"] and ("T3", "acc3") in MSGS and "T3" not in nx._lire()["cartes"], b)
    check("la carte retirée sort du registre, et le message de la personne avec",
          "T1" not in nx._lire()["cartes"] and f"{AG}:{VA}" not in nx._lire()["messages"], nx._lire())
    check("Threads garde sa carte", "H1" in nx._lire()["cartes"] and ("H1", "h1") in MSGS)
    # 20 min plus tard : la carte vidée part au tour de la boucle (poser_cartes)
    h = json.loads(nx.FICHIER.read_text(encoding="utf-8"))
    h["actifs"][f"{AG}:{VA2}"]["clos"] = "expire"
    nx.FICHIER.write_text(json.dumps(h), encoding="utf-8")
    APPELS.clear()
    bz = nx.poser_cartes(AG)
    check("le tour de la boucle (poser_cartes) : ne pose rien, retire la carte qui attendait",
          not [1 for m, ch in APPELS if m == "POST"] and bz["retirees"] == ["T2"]
          and ("T2", "c2") not in MSGS, (bz, APPELS))
    APPELS.clear()
    bz = nx.poser_cartes(AG)
    check("… puis plus rien à faire", bz["retirees"] == [] and not [1 for m, ch in APPELS if m == "DELETE"], bz)
    monde()
    APPELS.clear()
    check("un vieux « 📱 Numéro » (ramener_carte) ne repose pas de carte",
          nx.ramener_carte(AG, VA, "T1") == "deja" and not [1 for m, ch in APPELS if m == "POST"], APPELS)
    p = {"type": 3, "guild_id": AG, "channel_id": "T1", "token": "t", "application_id": MOI,
         "data": {"custom_id": "numx:menu"},
         "member": {"user": {"id": VA}, "roles": [], "permissions": "0"}, "message": {"flags": 0}}
    r = nx.traiter(p)
    check("… cliqué dans le ticket : il dit où prendre le numéro, en privé",
          r["type"] == 4 and nx.TEXTE_NUMERO_AILLEURS in json.dumps(r, ensure_ascii=False)
          and not [1 for m, ch in APPELS if m == "POST"], r)
    check("Threads : ramener_carte repose toujours sa carte",
          nx.ramener_carte(TH, VA, "H1") == "ramenee", APPELS)

    # une carte pas encore retirée ne vend plus rien
    def clic(cid, salon, gid=AG, uid=VA, mid=None):
        return {"type": 3, "guild_id": gid, "channel_id": salon, "token": "t", "application_id": MOI,
                "data": {"custom_id": cid},
                "member": {"user": {"id": uid}, "roles": [], "permissions": "0"},
                "message": {"flags": nx.V2, **({"id": mid} if mid else {})}}
    monde()
    ACHATS.clear()
    r = nx.traiter(clic("numx:prendre", "T1", mid="c1"))
    check("« Prendre un numéro » sur la carte d'un ticket : rien d'acheté, il dit où le prendre",
          not ACHATS and nx.TEXTE_NUMERO_AILLEURS in json.dumps(r, ensure_ascii=False), r)
    r = nx.traiter(clic("numx:prendre", "T1", mid="c1bis"))
    check("… pareil depuis une carte hors registre", not ACHATS
          and nx.TEXTE_NUMERO_AILLEURS in json.dumps(r, ensure_ascii=False), r)
    r = nx.traiter(clic("numx:autre:n2", "T2", uid=VA2, mid="c2"))
    check("« 🔁 Autre » dans un ticket : refusé aussi, le numéro en cours reste",
          not ACHATS and nx.TEXTE_NUMERO_AILLEURS in json.dumps(r, ensure_ascii=False)
          and not nx._actif(f"{AG}:{VA2}").get("clos"), r)
    r = nx.traiter(clic("numx:prendre", "H1", gid=TH, mid="h1"))
    check("Threads : la carte du ticket vend toujours", len(ACHATS) == 1, (ACHATS, r))
    r = nx.traiter(clic("numx:prendre", "PRIVE", uid=VA3))
    check("hors ticket (menu privé du staff) : rien ne change", len(ACHATS) == 2, (ACHATS, r))
    # un achat en cours (clé dans _ACHATS, la carte en « ⏳ Recherche… ») : la
    # carte reste, ni retirée ni oubliée du registre — le numéro payé doit
    # pouvoir s'y afficher
    monde()
    nx._ACHATS.add(f"{AG}:{VA}")
    try:
        b = nx.retirer_cartes(AG, chercher=True)
    finally:
        nx._ACHATS.discard(f"{AG}:{VA}")
    check("achat en cours (_ACHATS) : la carte reste, toujours au registre et au message de la personne",
          "T1" in b["en_cours"] and ("T1", "c1") in MSGS and "T1" in nx._lire()["cartes"]
          and nx._lire()["messages"].get(f"{AG}:{VA}"), b)
finally:
    (vd.api, tk._api, tk.ETAT_FICHIER, nx.FICHIER, lv.lien_de, lv.est_actif,
     nx._REPRIS[0], numgen.get_number, numgen.get_code, numgen.getatext_key, numgen.compte,
     vd._EN_FOND, nx._dormir, num.HISTO_FILE, numgen.ALERTES_FICHIER) = SAV

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
