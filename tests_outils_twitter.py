# -*- coding: utf-8 -*-
"""tests_outils_twitter.py — 🧰 OUTILS TWITTER (06/11/2026).

Propriétaire, sur TRUST TWITTER : « tu peux faire un truc outils Twitter et
tu mets le numéro, adresse, numéro, spoofer vraiment séparé » ; ses réponses :
📱 numéro, 📧 adresse, 📤 spoofer, pas de download ; les tickets gardent leurs
cartes et leurs boutons.

Ce qui est vérifié, sans réseau ni data/ :
  1. les panneaux de Twitter : Numéro X (numx:prendre), Adresses Outlook
     (mailx:prendre), un bouton Spoofer (outk:spf:commun) ; ceux d'Instagram
     ne changent pas ;
  2. 📤 cliqué dans le salon commun ouvre la fenêtre du cliqueur ; la fenêtre
     validée dit où arrivent les versions (son ticket) ; sans ticket : refus ;
     le menu ne redescend pas après un spoof sur Twitter (Instagram : comme avant) ;
  3. 📱 et 📧 cliqués dans leur salon : servis par numeros_x_discord et
     outlook_x_discord en privé (pas de carte) ;
  4. l'installation : le plan sans rien écrire (essai) ; puis la catégorie
     créée aux droits de 📧・adresse-outlook et rangée après 📚 RESSOURCES,
     📱・numéro et 📤・spoofer créés, 📧・adresse-outlook DÉPLACÉ (pas recréé),
     rangés, les 3 panneaux posés ; relancée, rien de refait ; un panneau
     disparu est reposé au démarrage ;
  5. ce qui manque arrête avant toute écriture.

Lancement : python tests_outils_twitter.py
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import numeros_x_discord as nx    # noqa: E402
import outils_tickets as ot       # noqa: E402
import outlook_x_discord as ox    # noqa: E402
import tickets_discord as tk      # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:500]}]"))


AG, TW = tk.AGENCY_IG_ID, tk.TWITTER_ID
VA, VA2, CHEF = "4001", "4002", "4999"
TICKET, ADRESSE, RESSOURCES, EQUIPE, ACCUEIL = "7201", ot.ADRESSE_OUTLOOK_TWITTER, "300", "400", "100"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="outils_twitter_"))
ot.SALONS_FICHIER = TMP / "outils_salons.json"
ot.ETAT = TMP / "outils_tickets.json"
ETAT = {"tickets": {f"{TW}:{VA}": {"salon": TICKET}, f"{AG}:{VA}": {"salon": "7001"}}}
_sav = (tk._etat, tk.role_manager, tk.role_helper, ot._api, tk.ramener_menu)
tk._etat = lambda: ETAT
tk.role_manager = lambda gid: "R_MANAGER"
tk.role_helper = lambda gid: "R_HELPER"


def membre(uid, chef=False):
    return {"user": {"id": uid, "username": "bob"}, "roles": ["R_MANAGER"] if chef else [],
            "permissions": "0"}


def ids(composants):
    out, pile = [], list(composants or [])
    while pile:
        c = pile.pop(0)
        if isinstance(c, dict):
            if c.get("custom_id"):
                out.append(c["custom_id"])
            pile += list(c.get("components") or [])
            if isinstance(c.get("accessory"), dict):
                pile.append(c["accessory"])
    return out


def textes(composants):
    out, pile = [], list(composants or [])
    while pile:
        c = pile.pop(0)
        if isinstance(c, dict):
            if c.get("type") == 10:
                out.append(c["content"])
            pile += list(c.get("components") or [])
    return out


# ── le faux Discord ───────────────────────────────────────────────────────
DROITS = [{"id": TW, "type": 0, "allow": "0", "deny": "377957125120"},
          {"id": "R_VERIFIE", "type": 0, "allow": "66624", "deny": "377957124096"},
          {"id": "R_MANAGER", "type": 0, "allow": "377957239872", "deny": "0"}]
APPELS = []
MONDE = {}


def nouveau_monde():
    MONDE.clear()
    MONDE.update({"salons": [
        {"id": ACCUEIL, "type": 4, "name": "🏠 ACCUEIL", "position": 0},
        {"id": RESSOURCES, "type": 4, "name": "📚 RESSOURCES", "position": 3},
        {"id": EQUIPE, "type": 4, "name": "💼 ÉQUIPE", "position": 4},
        {"id": ADRESSE, "type": 0, "name": "📧・adresse-outlook", "parent_id": RESSOURCES,
         "position": 25, "permission_overwrites": [dict(o) for o in DROITS]},
        {"id": "1552392915622436874", "type": 0, "name": "📋・menu", "parent_id": RESSOURCES,
         "position": 26, "permission_overwrites": [dict(o) for o in DROITS]}],
        "messages": {}, "suivant": 900, "panne": False})
    APPELS.clear()


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw.get("json")))
    if MONDE.get("panne"):
        return 0, {"message": "injoignable"}
    morceaux = chemin.split("?")[0].strip("/").split("/")
    j = kw.get("json")
    if methode == "GET" and chemin == f"/guilds/{TW}/channels":
        return 200, [dict(c) for c in MONDE["salons"]]
    if methode == "POST" and chemin == f"/guilds/{TW}/channels":
        MONDE["suivant"] += 1
        c = dict(j, id=str(MONDE["suivant"]), position=99)
        MONDE["salons"].append(c)
        return 201, dict(c)
    if methode == "PATCH" and chemin == f"/guilds/{TW}/channels":
        for x in j:
            for c in MONDE["salons"]:
                if c["id"] == x["id"]:
                    c["position"] = x["position"]
        return 204, {}
    if methode == "PATCH" and morceaux[0] == "channels" and len(morceaux) == 2:
        for c in MONDE["salons"]:
            if c["id"] == morceaux[1]:
                c.update(j)
                return 200, dict(c)
        return 404, {"code": 10003}
    if morceaux[0] == "channels" and len(morceaux) >= 3 and morceaux[2] == "messages":
        salon = morceaux[1]
        ms = MONDE["messages"].setdefault(salon, [])
        if methode == "GET" and len(morceaux) == 3:
            return 200, list(reversed(ms))
        if methode == "GET":
            m = next((m for m in ms if m["id"] == morceaux[3]), None)
            return (200, m) if m else (404, {"code": 10008})
        if methode == "POST":
            MONDE["suivant"] += 1
            m = dict(j, id=str(MONDE["suivant"]), author={"id": "bot"})
            ms.append(m)
            return 200, m
    return 404, {"message": "inconnu"}


try:
    ot._api = faux_api

    # ── 1. les panneaux ───────────────────────────────────────────────────
    print("1. Les panneaux de Twitter")
    pn = ot._panneaux(TW)
    check("Twitter : 📱・numéro, 📧・adresse-outlook, 📤・spoofer, dans cet ordre, pas de download",
          [(c, n) for c, n, _m, _f in pn] == [("numero", "📱・numéro"), ("adresse", "📧・adresse-outlook"),
                                                ("spoofer", "📤・spoofer")], pn)
    corps = {c: f() for c, _n, _m, f in pn}
    marques = {c: m for c, _n, m, _f in pn}
    check("📱 : le formulaire Numéro X de numeros_x_discord (numx:prendre), en V2",
          marques["numero"] == "numx:prendre" and "numx:prendre" in ids(corps["numero"]["components"])
          and corps["numero"]["components"] == nx.vue_panneau(nx.SERVEURS[TW])
          and corps["numero"]["flags"] == ot.V2, corps["numero"])
    check("📧 : le formulaire Adresses Outlook d'outlook_x_discord (mailx:prendre)",
          marques["adresse"] == "mailx:prendre" and corps["adresse"]["components"] == ox.vue_panneau()
          and "mailx:prendre" in ids(corps["adresse"]["components"]), corps["adresse"])
    check("📤 : le panneau « Spoofer » d'Instagram, tel quel (bouton seul, ou la carte et sa vignette)",
          ids(corps["spoofer"]["components"]) == ["outk:spf:commun"]
          and textes(corps["spoofer"]["components"]) in ([], ["## Spoofer"])
          and corps["spoofer"] == ot.corps_panneau("spoofer"))
    check("Instagram inchangé : 📋 menu, 📤 spoofer, ⬇️ download",
          [(c, n, m) for c, n, m, _f in ot._panneaux(AG)]
          == [(c, n, b[2]) for c, n, b in ot.PANNEAUX]
          and all(f() == ot.corps_panneau(c) for c, _n, _m, f in ot._panneaux(AG)))
    check("Twitter est un serveur à salons communs (les clics outk: y sont acceptés)",
          TW in ot.SERVEURS and TW in ot.SALONS_COMMUNS and AG in ot.SALONS_COMMUNS)
    check("… sans boutons outils dans les tickets Twitter (ils gardent leurs boutons d'avant)",
          TW not in tk.OUTILS_DANS_MENU and not [c for c in ids(tk.boutons_va(VA, gid=TW))
                                                 if c.startswith("outk:")])

    # ── 2. 📤 depuis le salon commun ──────────────────────────────────────
    print("2. 📤 Spoofer depuis 📤・spoofer")

    def clic(cid, uid=VA, salon="901", chef=False, typ=3):
        return {"type": typ, "guild_id": TW, "channel_id": salon, "application_id": "app",
                "token": "jeton", "member": membre(uid, chef), "data": {"custom_id": cid},
                "message": {"id": "m1", "flags": 32768}}
    r = ot.traiter(clic("outk:spf:commun"))
    check("le clic ouvre la fenêtre du cliqueur (fichier + nombre)",
          r.get("type") == 9 and r["data"]["custom_id"] == f"outk:spff:{VA}", r)
    r = ot.traiter(clic("outk:spf:commun", uid=VA2))
    check("sans ticket sur Twitter : refus en privé, rien ouvert",
          r.get("type") == 4 and r["data"]["content"] == ot.TEXTE_SANS_TICKET and r["data"]["flags"] == 64, r)
    _vrai = ot._recevoir_spoofer
    VUS = []
    ot._recevoir_spoofer = lambda p, t: (VUS.append(t) or {"type": 6})
    try:
        r = ot.traiter(clic(f"outk:spff:{VA}", typ=5))
    finally:
        ot._recevoir_spoofer = _vrai
    check("la fenêtre validée : livrée dans SON ticket, et l'accusé dit où",
          VUS and VUS[0]["salon"] == TICKET and VUS[0]["uid"] == VA and VUS[0].get("commun")
          and r["type"] == 4 and f"<#{TICKET}>" in r["data"]["content"], (VUS, r))
    RAMENES = []
    tk.ramener_menu = lambda g, u, s, en_dernier=False: (RAMENES.append(g) or "deja")
    ot._ramener_menu(TW, VA, TICKET)
    ot._ramener_menu(AG, VA, "7001")
    check("après un spoof, le menu ne redescend pas sur Twitter ; Instagram comme avant",
          RAMENES == [AG], RAMENES)
    tk.ramener_menu = _sav[4]

    # ── 3. 📱 et 📧 dans leur salon ───────────────────────────────────────
    print("3. 📱 et 📧 dans leur salon, la carte du ticket suit")
    import time as _t
    import numgen
    import outlook_comptes as oc
    import verif_discord as vd
    NUM_SALON, CARTE, CARTE_OX = "901", "8001", "8101"
    API3 = []

    def api3(methode, chemin, **kw):
        API3.append((methode, chemin, kw.get("json")))
        return 200, {"id": "x"}
    _s3 = (vd.api, vd._EN_FOND, nx.FICHIER, nx._dormir, nx.numeros_du_jour, numgen.herosms_key,
           numgen.get_number_herosms, numgen.get_code, ox.FICHIER, ox._dormir, oc.nb_libres,
           oc.nb_du_jour, oc.attribuer_une_de_plus, oc.comptes_du_va, oc.texte_2fa, tk.ticket_de,
           numgen.alerter_staff, numgen.fin_alerte, tk.ETAT_FICHIER, numgen.finish)
    CODES = []
    # le registre des tickets, lu par numeros_x_discord et outlook_x_discord
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.ETAT_FICHIER.write_text(json.dumps(ETAT), encoding="utf-8")
    numgen.finish = lambda act_id, provider="herosms": "ACCESS_ACTIVATION"

    class _Stop(Exception):
        pass

    def dormir(_s):
        if not CODES:
            raise _Stop()

    def direct(f):
        try:
            f()
        except _Stop:
            pass
    try:
        vd.api, vd._EN_FOND = api3, direct
        nx.FICHIER = TMP / "numeros_x.json"
        nx._dormir = dormir
        nx.numeros_du_jour = lambda uid, gid: 0
        numgen.herosms_key = lambda: "cle-hero"
        numgen.get_number_herosms = lambda service, country: (True, {"id": "h1", "phone": "+15550001111",
                                                                       "provider": "herosms"})
        numgen.get_code = lambda act_id, provider="herosms": CODES.pop(0) if CODES else ("wait", "")
        nx.FICHIER.write_text(json.dumps({
            "cartes": {TICKET: {"message": CARTE, "uid": VA, "gid": TW}},
            "messages": {f"{TW}:{VA}": {"carte": True, "salon": TICKET, "message": CARTE, "le": 1}},
            "actifs": {}}), encoding="utf-8")
        nx._ACHATS.clear()
        nx._ECOUTES.clear()
        nx._REPRIS[0] = True
        r = nx.traiter(clic("numx:prendre", salon=NUM_SALON))
        m = nx._lire()["messages"][f"{TW}:{VA}"]
        check("📱 pris dans le salon : réponse en privé (V2 | éphémère), jamais dans le salon",
              r.get("type") == 4 and r["data"]["flags"] == nx.V2 | nx.EPHEMERE
              and not [a for a in API3 if a[0] == "POST" and a[1] == f"/channels/{NUM_SALON}/messages"], r)
        check("… la carte du ticket reste SON message (le privé s'y ajoute)",
              m.get("carte") and m.get("message") == CARTE and (m.get("prive") or {}).get("jeton") == "jeton", m)
        patchs = [a for a in API3 if a[0] == "PATCH"]
        check("… le numéro s'écrit dans la carte du ticket ET dans le privé",
              any(a[1] == f"/channels/{TICKET}/messages/{CARTE}" for a in patchs)
              and any("/webhooks/" in a[1] and "/jeton/" in a[1] for a in patchs), patchs)
        API3.clear()
        CODES.append(("code", "246810"))
        direct(lambda: nx._ecouter(f"{TW}:{VA}", "h1", nx.SERVEURS[TW]))
        vus = [json.dumps(a[2], ensure_ascii=False) for a in API3 if a[0] == "PATCH"]
        check("le code arrive dans les deux (carte et privé)",
              any(a[1] == f"/channels/{TICKET}/messages/{CARTE}" for a in API3 if a[0] == "PATCH")
              and any("/webhooks/" in a[1] for a in API3 if a[0] == "PATCH")
              and all("246810" in v for v in vus) and len(vus) == 2, API3)
        h = json.loads(nx.FICHIER.read_text(encoding="utf-8"))
        h["actifs"][f"{TW}:{VA}"]["pris_le"] = int(_t.time()) - nx.DUREE_NUMERO_SEC - 5
        nx.FICHIER.write_text(json.dumps(h), encoding="utf-8")
        check("au bout de 20 min, la carte est bien vidée (elle n'a pas été décrochée)",
              nx.vider_cartes_echues() == [f"{TW}:{VA}"]
              and nx._actif(f"{TW}:{VA}").get("clos") == "fini")

        def depart():
            nx.FICHIER.write_text(json.dumps({
                "cartes": {TICKET: {"message": CARTE, "uid": VA, "gid": TW}},
                "messages": {f"{TW}:{VA}": {"carte": True, "salon": TICKET, "message": CARTE, "le": 1}},
                "actifs": {}}), encoding="utf-8")
            nx._ACHATS.clear()
            nx._ECOUTES.clear()
            nx.traiter(clic("numx:prendre", salon=NUM_SALON))
            CODES.append(("code", "135790"))
            direct(lambda: nx._ecouter(f"{TW}:{VA}", "h1", nx.SERVEURS[TW]))
            API3.clear()
        depart()
        p = clic("numx:fini:h1", salon=NUM_SALON)
        p["message"]["flags"] = nx.V2 | nx.EPHEMERE
        r = nx.traiter(p)
        carte = [a for a in API3 if a[0] == "PATCH" and a[1] == f"/channels/{TICKET}/messages/{CARTE}"]
        check("« ✅ C'est bon » dans le privé : la carte du ticket se ferme aussi",
              r.get("type") == 7 and carte and "C'est bon" in json.dumps(carte[-1][2], ensure_ascii=False)
              and nx._actif(f"{TW}:{VA}").get("clos") == "fini", (r, API3))
        depart()
        pc = clic("numx:retry:h1", salon=TICKET)
        pc["message"]["id"] = CARTE
        nx.traiter(pc)
        m = nx._lire()["messages"][f"{TW}:{VA}"]
        check("un clic sur la carte ensuite : le privé encore ouvert reste suivi",
              m.get("carte") and (m.get("prive") or {}).get("jeton") == "jeton", m)
        # un VA sans carte : comme avant (le privé est son message)
        nx.FICHIER.write_text(json.dumps({"cartes": {}, "messages": {}, "actifs": {}}), encoding="utf-8")
        r = nx.traiter(clic("numx:prendre", uid=VA2, salon=NUM_SALON))
        check("un VA sans carte : comme avant, le privé est son message",
              r.get("type") == 4 and nx._lire()["messages"].get(f"{TW}:{VA2}", {}).get("jeton") == "jeton")

        # 📧 : l'adresse prise dans le salon redessine la carte Outlook du ticket
        ox.FICHIER = TMP / "outlook_x.json"
        ox.FICHIER.write_text(json.dumps({"cartes": {TICKET: {"message": CARTE_OX, "uid": VA, "gid": TW}},
                                          "messages": {}}), encoding="utf-8")
        ox._dormir = lambda s: None
        MES = []
        oc.nb_libres = lambda: 5
        oc.nb_du_jour = lambda uid, gid=None: 0
        oc.attribuer_une_de_plus = lambda uid, nom, gid=None: (
            MES.append({"id": 7, "email": "a@outlook.com", "password": "pw", "va": uid}) or (MES[-1], "ok"))
        oc.comptes_du_va = lambda uid, gid=None: list(MES)
        oc.texte_2fa = lambda c, maintenant=None: ("", "123456", 20)
        tk.ticket_de = lambda g, u: TICKET
        numgen.alerter_staff = lambda *a, **k: "deja"
        numgen.fin_alerte = lambda *a, **k: None
        API3.clear()
        r = ox.traiter(clic("mailx:prendre", salon=ADRESSE))
        carte_ox = [a for a in API3 if a[0] == "PATCH" and a[1] == f"/channels/{TICKET}/messages/{CARTE_OX}"]
        check("📧 pris dans le salon : en privé, et la carte Outlook du ticket montre l'adresse",
              r.get("type") == 4 and r["data"]["flags"] & nx.EPHEMERE and carte_ox
              and "a@outlook.com" in json.dumps(carte_ox[-1][2]) and "123456" not in json.dumps(carte_ox[-1][2]),
              (r, API3))
        check("… adresse et mot de passe déposés dans le ticket (comme avant)",
              len([a for a in API3 if a[0] == "POST" and a[1] == f"/channels/{TICKET}/messages"]) == 2, API3)
        # un ancien salon du VA (supprimé puis refait) reste au registre, en premier
        ox.FICHIER.write_text(json.dumps({"cartes": {"6999": {"message": "8999", "uid": VA, "gid": TW},
                                                     TICKET: {"message": CARTE_OX, "uid": VA, "gid": TW}},
                                          "messages": {}}), encoding="utf-8")
        API3.clear()
        ox.maj_carte_du_va(TW, VA)
        check("la carte redessinée est celle de son ticket ACTUEL, pas l'ancienne",
              [a[1] for a in API3 if a[0] == "PATCH"] == [f"/channels/{TICKET}/messages/{CARTE_OX}"], API3)
    finally:
        (vd.api, vd._EN_FOND, nx.FICHIER, nx._dormir, nx.numeros_du_jour, numgen.herosms_key,
         numgen.get_number_herosms, numgen.get_code, ox.FICHIER, ox._dormir, oc.nb_libres,
         oc.nb_du_jour, oc.attribuer_une_de_plus, oc.comptes_du_va, oc.texte_2fa, tk.ticket_de,
         numgen.alerter_staff, numgen.fin_alerte, tk.ETAT_FICHIER, numgen.finish) = _s3
    check("Outlook : son ancien panneau reste coupé (le nôtre le remplace)",
          ox.SERVEURS[TW].get("panneau") is False and "pas de panneau" in ox.poser_panneau(TW))

    # ── 3b. le « c'est bon » : plus de cartes ni de boutons 📱 📧 dans les tickets
    print("3b. Tickets sans cartes numéro / Outlook (06/11)")
    check("Twitter : cartes numéro ET Outlook retirées des tickets",
          TW in nx.CARTES_RETIREES and TW in ox.CARTES_RETIREES)
    check("chaque serveur renvoie à SON 📱・numéro",
          "OUTILS TWITTER" in nx.texte_numero_ailleurs(TW) and "OUTILS INSTAGRAM" in nx.texte_numero_ailleurs(AG)
          and "OUTILS TWITTER" in ox.TEXTE_ADRESSE_AILLEURS)
    figee = {"id": "c", "flags": nx.V2, "author": {"id": "moi"},
             "components": [{"type": 17, "components": [{"type": 10, "content": "## Numéro X"},
                                                        {"type": 10, "content": "🇺🇸 ⏳ Recherche d'un numéro…"}]}]}
    check("une carte Twitter figée sans bouton est reconnue (retirée elle aussi)", nx._carte_a_retirer(figee, "moi")
          and not nx._carte_a_retirer(dict(figee, flags=0), "moi"))
    plats_tw = [c for r in tk.boutons_va(VA, a_un_lien=True, gid=TW) for c in ids([r])]
    check("ticket Twitter : plus de 📱 Numéro ni 📧 Outlook dans le menu",
          "numx:menu" not in plats_tw and "mailx:menu" not in plats_tw and tk.BOUTONS_VERSION >= 13, plats_tw)
    import verif_discord as vd2
    _s3b = (vd2.api, nx.FICHIER, ox.FICHIER, tk.ETAT_FICHIER)
    API3B = []
    try:
        tk.ETAT_FICHIER = TMP / "tickets3b.json"
        tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {f"{TW}:{VA}": {"salon": TICKET}}}), encoding="utf-8")
        nx.FICHIER = TMP / "numeros_x3b.json"
        ox.FICHIER = TMP / "outlook_x3b.json"
        moi = vd2.bot_du_serveur(TW)["app_id"]
        carte_n = {"id": "cn", "flags": nx.V2, "author": {"id": moi}, "components": nx.vue_panneau(nx.SERVEURS[TW])}
        carte_o = {"id": "co", "flags": nx.V2, "author": {"id": moi}, "components": ox.vue_carte(VA, TW)}
        MSG3 = {("cn"): carte_n, ("co"): carte_o}

        def api3b(methode, chemin, **kw):
            API3B.append((methode, chemin))
            if methode == "GET" and "?limit" in chemin:
                return 200, list(MSG3.values())
            if methode == "GET":
                m = MSG3.get(chemin.rsplit("/", 1)[1])
                return (200, m) if m else (404, {})
            if methode == "DELETE":
                MSG3.pop(chemin.rsplit("/", 1)[1], None)
                return 204, {}
            return 200, {"id": "neuf"}
        vd2.api = api3b
        nx.FICHIER.write_text(json.dumps({"cartes": {TICKET: {"message": "cn", "uid": VA, "gid": TW}},
                                          "messages": {}, "actifs": {}}), encoding="utf-8")
        ox.FICHIER.write_text(json.dumps({"cartes": {TICKET: {"message": "co", "uid": VA, "gid": TW}},
                                          "messages": {}}), encoding="utf-8")
        bn = nx.poser_cartes(TW)
        bo = ox.poser_cartes(TW)
        check("le tour de la boucle ne pose plus de carte : il retire la carte numéro et la carte Outlook",
              not [a for a in API3B if a[0] == "POST"] and bn.get("retirees") == [TICKET]
              and bo.get("retirees") == [TICKET] and not MSG3, (bn, bo, API3B))
        check("… et les registres les oublient", not nx._lire()["cartes"] and not ox._lire()["cartes"])
        API3B.clear()
        check("un vieux « 📱 Numéro » / « 📧 Outlook » ne repose pas de carte",
              nx.ramener_carte(TW, VA, TICKET) == "deja" and ox.ramener_carte(TW, VA, TICKET) == "deja"
              and not [a for a in API3B if a[0] == "POST"], API3B)
        r = ox.traiter(clic("mailx:menu", salon=TICKET))
        check("… cliqué dans le ticket : dit où prendre l'adresse", r["type"] == 4
              and r["data"]["content"] == ox.TEXTE_ADRESSE_AILLEURS, r)
    finally:
        (vd2.api, nx.FICHIER, ox.FICHIER, tk.ETAT_FICHIER) = _s3b

    # ── 4. l'installation ─────────────────────────────────────────────────
    print("4. L'installation")
    nouveau_monde()
    b = ot.installer_salons_twitter(essai=True)
    ecrits = [a for a in APPELS if a[0] != "GET"]
    check("essai : le plan, rien d'écrit",
          not ecrits and not b["rates"] and any("créer la catégorie 🧰 OUTILS TWITTER" in x for x in b["plan"])
          and any("après 📚 RESSOURCES" in x for x in b["plan"])
          and any("créer 📱・numéro" in x for x in b["plan"])
          and any("déplacer 📧・adresse-outlook" in x for x in b["plan"])
          and any("créer 📤・spoofer" in x for x in b["plan"])
          and not ot._etat_salons().get(TW), (b, ecrits))
    b = ot.installer_salons_twitter(essai=False)
    s = {c["id"]: c for c in MONDE["salons"]}
    cat = next((c for c in MONDE["salons"] if c["type"] == 4 and "OUTILS TWITTER" in c["name"]), None)
    check("la catégorie 🧰 OUTILS TWITTER, aux droits de 📧・adresse-outlook",
          cat and cat["permission_overwrites"] == [dict(o) for o in DROITS], (cat, b))
    cats = sorted([c for c in MONDE["salons"] if c["type"] == 4], key=lambda c: c["position"])
    check("… rangée juste après 📚 RESSOURCES",
          [c["id"] for c in cats] == [ACCUEIL, RESSOURCES, cat["id"], EQUIPE], [c["name"] for c in cats])
    dedans = sorted([c for c in MONDE["salons"] if c.get("parent_id") == cat["id"]],
                    key=lambda c: c["position"])
    check("dedans : 📱・numéro, 📧・adresse-outlook, 📤・spoofer, dans cet ordre",
          [c["name"] for c in dedans] == ["📱・numéro", "📧・adresse-outlook", "📤・spoofer"], dedans)
    check("📧・adresse-outlook DÉPLACÉ (même id, ses droits gardés), pas recréé",
          dedans[1]["id"] == ADRESSE and s[ADRESSE]["permission_overwrites"] == [dict(o) for o in DROITS]
          and sum(1 for c in MONDE["salons"] if "adresse" in c["name"]) == 1, dedans)
    check("📱・numéro et 📤・spoofer créés aux mêmes droits (lecture seule pour ✅ Vérifié)",
          all(c["permission_overwrites"] == [dict(o) for o in DROITS] for c in (dedans[0], dedans[2])))
    check("📋・menu ne bouge pas", s["1552392915622436874"]["parent_id"] == RESSOURCES)
    pan = {c["id"]: MONDE["messages"].get(c["id"]) or [] for c in dedans}
    check("les 3 panneaux posés, un par salon, chacun le sien",
          [ids(m["components"]) for c in dedans for m in pan[c["id"]]]
          == [ids(nx.vue_panneau(nx.SERVEURS[TW])), ids(ox.vue_panneau()), ["outk:spf:commun"]]
          and sorted(b["faits"][-3:]) == sorted(["panneau numero posé", "panneau adresse posé",
                                                   "panneau spoofer posé"]), (pan, b))
    f = ot._etat_salons().get(TW) or {}
    check("la fiche : les 3 salons, leurs panneaux, « installe »",
          f.get("installe") and all(f.get(k, {}).get("salon") and f.get(k, {}).get("panneau")
                                    for k in ("numero", "adresse", "spoofer")), f)
    APPELS.clear()
    b = ot.installer_salons_twitter(essai=False)
    check("relancée : rien de créé, déplacé ni reposé",
          not [a for a in APPELS if a[0] in ("POST", "DELETE")]
          and not [a for a in APPELS if a[0] == "PATCH" and a[1].startswith("/channels/")]
          and not b["rates"], (b, [a for a in APPELS if a[0] != "GET"]))
    # un panneau supprimé à la main : reposé au démarrage, une fois
    MONDE["messages"][dedans[2]["id"]] = []
    APPELS.clear()
    b = ot.assurer_panneaux(TW)
    b2 = ot.assurer_panneaux(TW)
    check("un panneau disparu est reposé (une fois), les autres sont vus en place",
          b["poses"] == ["spoofer"] and sorted(b["ok"]) == ["adresse", "numero"]
          and b2["poses"] == [] and sorted(b2["ok"]) == ["adresse", "numero", "spoofer"], (b, b2))
    MONDE["panne"] = True
    APPELS.clear()
    b = ot.assurer_panneaux(TW)
    check("Discord injoignable : rien reposté", not [a for a in APPELS if a[0] == "POST"] and b["rates"], b)
    MONDE["panne"] = False
    # la fiche a perdu 📱・numéro (création rendue en erreur alors que Discord
    # l'avait faite) : retrouvé par son nom au démarrage, noté, son panneau vu
    d = json.loads(ot.SALONS_FICHIER.read_text(encoding="utf-8"))
    d[TW].pop("numero", None)
    ot.SALONS_FICHIER.write_text(json.dumps(d), encoding="utf-8")
    b = ot.assurer_panneaux(TW)
    check("📱・numéro absent de la fiche : retrouvé par son nom et noté (pas « introuvable »)",
          "numero" in b["ok"] and (ot._etat_salons()[TW].get("numero") or {}).get("salon") == dedans[0]["id"]
          and not b["rates"], b)
    # la catégorie déplacée à la main en bas : la relance la remet après 📚 RESSOURCES
    for c in MONDE["salons"]:
        if c["id"] == cat["id"]:
            c["position"] = 50
    APPELS.clear()
    b = ot.installer_salons_twitter(essai=False)
    cats = sorted([c for c in MONDE["salons"] if c["type"] == 4], key=lambda c: c["position"])
    check("relancée, la catégorie mal rangée revient juste après 📚 RESSOURCES",
          [c["id"] for c in cats] == [ACCUEIL, RESSOURCES, cat["id"], EQUIPE]
          and any("juste après" in x for x in b["faits"]), (b, [c["name"] for c in cats]))

    # ── 5. ce qui manque arrête tout ──────────────────────────────────────
    print("5. Ce qui manque")
    ot.SALONS_FICHIER = TMP / "outils_salons_2.json"
    nouveau_monde()
    MONDE["salons"] = [c for c in MONDE["salons"] if c["id"] != ADRESSE]
    b = ot.installer_salons_twitter(essai=False)
    check("📧・adresse-outlook introuvable : rien d'écrit",
          not [a for a in APPELS if a[0] != "GET"] and b["rates"], b)
    nouveau_monde()
    for c in MONDE["salons"]:
        if c["id"] == ADRESSE:
            c["permission_overwrites"] = [o for o in c["permission_overwrites"] if o["id"] != TW]
    b = ot.installer_salons_twitter(essai=False)
    check("droits du modèle ouverts à @everyone : rien d'écrit",
          not [a for a in APPELS if a[0] != "GET"] and b["rates"], b)
    nouveau_monde()
    MONDE["panne"] = True
    b = ot.installer_salons_twitter(essai=False)
    check("salons illisibles : rien d'écrit", b["rates"] and not b["faits"], b)
finally:
    (tk._etat, tk.role_manager, tk.role_helper, ot._api, tk.ramener_menu) = _sav

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
