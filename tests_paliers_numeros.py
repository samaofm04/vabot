# -*- coding: utf-8 -*-
"""tests_paliers_numeros.py — paliers de numéros SMS par rôle (TRUST INSTAGRAM, 05/11/2026).

3 numéros par jour de base ; 📱 Niveau 1 → 10, Niveau 2 → 20, Niveau 3 → 50,
seulement tant que le VA porte le rôle. Les deux boutons qui vendent un numéro
sur ce serveur : la carte du ticket (numeros_x_discord, REST) et le panneau de
📱・numéro (cogs/numeros, Rem).

Rien ne part ni vers Discord ni vers GetAText : verif_discord.api et numgen
sont remplacés, l'état et l'historique vivent dans un dossier temporaire.
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numgen
import numeros_x_discord as nx
import paliers_numeros as pn
import tickets_discord
import verif_discord as vd
from cogs import numeros as num
import cogs.user as cu

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK   " if cond else "FAIL ") + nom + ("" if cond else f"  [{str(detail)[:400]}]"))


AG, TW, TH = vd.AGENCY_IG_ID, vd.TWITTER_ID, vd.THREADS_ID
R10, R20, R50, AUTRE = "900000000000000010", "900000000000000020", "900000000000000050", "900000000000000099"
VA, VA2, CHEF = "111111111111111111", "222222222222222222", "333333333333333333"
APPELS, ACHATS, ANNULES, CODES = [], [], [], []
COMPTE = {}                       # numeros_du_jour simulé : {(uid, gid): n}
MEMBRES = {}                      # GET /guilds/<g>/members/<uid> : {uid: roles} ; absent : 404


def faux_api(methode, chemin, **kw):
    APPELS.append((methode, chemin, kw))
    morceaux = chemin.split("/")
    if methode == "GET" and len(morceaux) == 5 and morceaux[1] == "guilds" and morceaux[3] == "members":
        uid = morceaux[4]
        if uid in MEMBRES:
            return 200, {"user": {"id": uid}, "roles": list(MEMBRES[uid])}
        return 404, {"message": "Unknown Member"}
    return 200, {}


def faux_numero(service="ig", country=None, cpt=""):
    ACHATS.append((service, country, cpt))
    n = len(ACHATS)
    return True, {"id": f"ga{n}", "phone": f"+1555111{n:04d}", "provider": "getatext", "country": country}


def faux_code(act_id, provider="getatext"):
    return CODES.pop(0) if CODES else ("wait", "")


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


def clic(cid, uid=VA, roles=(), gid=AG, perms="0", salon="S1", mid=None, ephemere=False):
    p = {"type": 3, "guild_id": gid, "channel_id": salon, "application_id": "app",
         "token": "tok", "data": {"custom_id": cid},
         "member": {"user": {"id": uid, "username": "va" + uid[:2]}, "roles": list(roles),
                    "permissions": perms},
         "message": {"flags": nx.V2 | (64 if ephemere else 0)}}
    if mid:
        p["message"]["id"] = mid
    return p


def textes(comps):
    out = []
    for c in comps or []:
        if c.get("type") == 10:
            out.append(c["content"])
        out += textes(c.get("components"))
    return out


def tout_texte(r):
    """Le texte de la réponse, puis celui des éditions qui ont suivi."""
    t = textes(((r or {}).get("data") or {}).get("components"))
    for m, ch, kw in APPELS:
        if m == "PATCH":
            t += textes((kw.get("json") or {}).get("components"))
    return " | ".join(t)


def remise_a_zero():
    for l in (APPELS, ACHATS, ANNULES, CODES):
        l.clear()
    COMPTE.clear()
    MEMBRES.clear()
    nx._ACHATS.clear()
    nx._ECOUTES.clear()
    nx._REPRIS[0] = True
    d = Path(tempfile.mkdtemp(prefix="paliers_"))
    nx.FICHIER = d / "numeros_x.json"
    num.HISTO_FILE = d / "numgen_historique.json"
    numgen.ALERTES_FICHIER = d / "numgen_alertes.json"


def prendre(uid=VA, roles=(), gid=AG, n=0, **kw):
    """Un clic « Prendre un numéro » d'un VA qui a déjà `n` codes du jour."""
    remise_a_zero()
    COMPTE[(uid, gid)] = n
    return nx.traiter(clic("numx:prendre", uid=uid, roles=roles, gid=gid, **kw))


SAV = (vd.api, vd._EN_FOND, nx.FICHIER, num.HISTO_FILE, nx._dormir, tickets_discord.role_helper,
       numgen.get_number, numgen.get_code, numgen.cancel, numgen.getatext_key, numgen.compte,
       numgen.ALERTES_FICHIER, nx.numeros_du_jour, dict(pn.PALIERS), num.numeros_du_jour,
       num._ephemere, cu._is_staff_member)
VRAIS_PALIERS = {g: dict(t) for g, t in pn.PALIERS.items()}
try:
    vd._charger_config()
    vd.api = faux_api
    vd._EN_FOND = direct
    nx._dormir = dormir
    tickets_discord.role_helper = lambda gid: ""
    numgen.get_number = faux_numero
    numgen.get_code = faux_code
    numgen.cancel = lambda act_id, provider="getatext": (ANNULES.append(act_id) or (True, "ACCESS_CANCEL"))
    numgen.getatext_key = lambda: "cle-ga"
    numgen.compte = lambda gid: ""
    nx.numeros_du_jour = lambda uid, gid: COMPTE.get((str(uid), str(gid)), 0)
    pn.PALIERS.clear()
    pn.PALIERS[AG] = {R10: 10, R20: 20, R50: 50}

    # 1. la table
    print("1. la table")
    check("sans rôle : la base (3)", pn.quota(AG, [], 3) == 3 and pn.quota(AG, None, 3) == 3)
    check("Niveau 1 → 10, Niveau 2 → 20, Niveau 3 → 50",
          (pn.quota(AG, [R10], 3), pn.quota(AG, [R20], 3), pn.quota(AG, [R50], 3)) == (10, 20, 50))
    check("plusieurs paliers : le plus haut", pn.quota(AG, [R10, R50, R20], 3) == 50)
    check("un autre rôle ne change rien", pn.quota(AG, [AUTRE], 3) == 3)
    check("ids en nombres (discord.py) ou en texte (REST) : pareil", pn.quota(AG, [int(R20)], 3) == 20)
    check("les rôles ne valent que sur leur serveur (Twitter, Threads : 3)",
          pn.quota(TW, [R50], 3) == 3 and pn.quota(TH, [R50], 3) == 3)
    check("seul TRUST INSTAGRAM a des paliers",
          pn.a_des_paliers(AG) and not pn.a_des_paliers(TW) and not pn.a_des_paliers(TH))

    # 2. la carte du ticket (REST, Wario)
    print("2. carte du ticket (REST)")
    r = prendre(n=3)
    check("sans rôle, 3 codes déjà : refusé « 3 codes reçus », rien d'acheté",
          not ACHATS and "3 codes reçus aujourd'hui" in tout_texte(r), tout_texte(r))
    r = prendre(n=2)
    check("sans rôle, 2 codes : le 3e est acheté", len(ACHATS) == 1, ACHATS)
    r = prendre(roles=[R10], n=3)
    check("Niveau 1, 3 codes déjà : le 4e est acheté", len(ACHATS) == 1, (ACHATS, tout_texte(r)))
    r = prendre(roles=[R10], n=9)
    check("Niveau 1, 9 codes : le 10e passe", len(ACHATS) == 1)
    r = prendre(roles=[R10], n=10)
    check("Niveau 1, 10 codes : refusé « 10 codes reçus », rien d'acheté",
          not ACHATS and "10 codes reçus aujourd'hui" in tout_texte(r), tout_texte(r))
    r = prendre(roles=[R20], n=19)
    check("Niveau 2, 19 codes : le 20e passe", len(ACHATS) == 1)
    r = prendre(roles=[R20], n=20)
    check("Niveau 2, 20 codes : refusé « 20 codes »", not ACHATS and "20 codes reçus" in tout_texte(r))
    r = prendre(roles=[R10, R50], n=49)
    check("Niveau 1 + Niveau 3, 49 codes : le 50e passe (le plus haut)", len(ACHATS) == 1)
    r = prendre(roles=[R50], n=50)
    check("Niveau 3, 50 codes : refusé « 50 codes »", not ACHATS and "50 codes reçus" in tout_texte(r))
    r = prendre(roles=[], n=4)
    check("rôle retiré (le clic ne le porte plus) : 4 codes, refusé à 3",
          not ACHATS and "3 codes reçus" in tout_texte(r), tout_texte(r))
    r = prendre(roles=[AUTRE], n=3)
    check("un autre rôle (✅ Vérifié…) ne débride pas", not ACHATS)
    r = prendre(roles=[], n=10, perms=str(0x8))
    check("le staff reste non bridé (sans rôle de palier, 10 codes : acheté)", len(ACHATS) == 1, ACHATS)

    # Annuler / expirer : « il ne compte pas dans tes N du jour » avec SON palier
    r = prendre(roles=[R20], n=5)
    a = nx._actif(f"{AG}:{VA}")
    APPELS.clear()
    nx.traiter(clic("numx:annuler:%s" % a["id"], roles=[R20], ephemere=True))
    check("Annuler sans code : « il ne compte pas dans tes 20 du jour »",
          "il ne compte pas dans tes 20 du jour" in tout_texte(None), tout_texte(None))

    def expirer(a):
        h = json.loads(nx.FICHIER.read_text(encoding="utf-8"))
        h["actifs"][f"{AG}:{VA}"]["pris_le"] = int(time.time()) - nx.DUREE_NUMERO_SEC - 5
        nx.FICHIER.write_text(json.dumps(h), encoding="utf-8")
        APPELS.clear()
        direct(lambda: nx._ecouter(f"{AG}:{VA}", a["id"], nx.SERVEURS[AG]))
        return tout_texte(None)
    r = prendre(roles=[R10], n=5)
    MEMBRES[VA] = [R10]
    t = expirer(nx._actif(f"{AG}:{VA}"))
    check("20 min sans code : « il ne compte pas dans tes 10 du jour » (rôles relus chez Discord)",
          "il ne compte pas dans tes 10 du jour" in t, t)
    r = prendre(roles=[R10], n=5)
    MEMBRES[VA] = []
    t = expirer(nx._actif(f"{AG}:{VA}"))
    check("… rôle retiré pendant les 20 min : la carte dit 3, la limite en vigueur", "dans tes 3 du jour" in t, t)
    r = prendre(roles=[R10], n=5)
    t = expirer(nx._actif(f"{AG}:{VA}"))
    check("… VA introuvable chez Discord : la base (3)", "dans tes 3 du jour" in t, t)
    check("un numéro sans titulaire lisible cite la base du serveur",
          nx._quota_vu({"id": "x"}, nx.SERVEURS[AG]) == 3)

    # « Autre » : relu avec les rôles du clic
    r = prendre(roles=[R10], n=9)
    a = nx._actif(f"{AG}:{VA}")
    COMPTE[(VA, AG)] = 10                       # le numéro en attente compte (numeros_du_jour)
    APPELS.clear()
    nx.traiter(clic("numx:autre:%s" % a["id"], roles=[R10], ephemere=True))
    check("« Autre » au 10e : refusé à 10 (le numéro en cours compte)",
          len(ACHATS) == 1 and "10 codes reçus" in tout_texte(None), (ACHATS, tout_texte(None)))
    r = prendre(roles=[R20], n=9)
    a = nx._actif(f"{AG}:{VA}")
    COMPTE[(VA, AG)] = 10
    nx.traiter(clic("numx:autre:%s" % a["id"], roles=[R20], ephemere=True))
    a2 = nx._actif(f"{AG}:{VA}")
    check("« Autre » au 10e avec Niveau 2 : racheté", len(ACHATS) == 2 and a2 and a2["id"] != a["id"],
          (ACHATS, a2))

    # la carte d'un autre : ses rôles lus chez Discord
    def clic_carte(uid, roles, perms="0"):
        h = json.loads(nx.FICHIER.read_text(encoding="utf-8")) if nx.FICHIER.exists() else {}
        h.setdefault("cartes", {})["T9"] = {"message": "carte-T9", "uid": VA, "gid": AG}
        nx.FICHIER.write_text(json.dumps(h), encoding="utf-8")
        return nx.traiter(clic("numx:prendre", uid=uid, roles=roles, perms=perms, salon="T9", mid="carte-T9"))
    remise_a_zero()
    COMPTE[(VA, AG)] = 5
    MEMBRES[VA] = [R10]
    r = clic_carte(VA2, [])
    check("carte du VA cliquée par un autre (non staff) : les rôles DU VA, lus chez Discord → 10",
          len(ACHATS) == 1 and [ch for m, ch, kw in APPELS if m == "GET" and ch == f"/guilds/{AG}/members/{VA}"],
          (ACHATS, APPELS))
    remise_a_zero()
    COMPTE[(VA, AG)] = 10
    MEMBRES[VA] = [R10]
    r = clic_carte(VA2, [])
    check("… et à 10 codes : refusé « 10 codes reçus »", not ACHATS and "10 codes reçus" in tout_texte(r),
          tout_texte(r))
    remise_a_zero()
    COMPTE[(VA, AG)] = 5
    r = clic_carte(CHEF, [], perms=str(0x8))
    check("carte d'un VA prise par un manager (staff) : achetée, aucune lecture de rôles pendant le clic",
          len(ACHATS) == 1 and not [1 for m, ch, kw in APPELS if "/members/" in ch], APPELS)
    MEMBRES[VA] = [R20]
    t = expirer(nx._actif(f"{AG}:{VA}"))
    check("… à l'expiration, la carte du VA de Niveau 2 dit « tes 20 du jour » (pas 3)",
          "il ne compte pas dans tes 20 du jour" in t, t)
    remise_a_zero()
    COMPTE[(VA, AG)] = 5
    r = clic_carte(VA2, [R50])
    check("… Discord ne le rend pas (parti) : la base, refusé à 3 — les rôles du cliqueur ne comptent pas",
          not ACHATS and "3 codes reçus" in tout_texte(r), tout_texte(r))
    remise_a_zero()
    COMPTE[(VA, AG)] = 5
    r = clic_carte(VA, [R10])
    check("sa propre carte : les rôles du clic, aucun appel à Discord",
          len(ACHATS) == 1 and not [1 for m, ch, kw in APPELS if "/members/" in ch], APPELS)

    # Twitter et Threads : inchangés
    r = prendre(gid=TH, roles=[R50], n=3)
    check("Threads : un rôle de palier n'y vaut rien, refusé à 3", not ACHATS and "3 codes reçus" in tout_texte(r))
    numgen.herosms_key, _sav_hk = (lambda: "cle-hero"), numgen.herosms_key
    numgen.get_number_herosms, _sav_gh = (lambda s, c: faux_numero(s, c)), numgen.get_number_herosms
    try:
        r = prendre(gid=TW, roles=[R50], n=3)
        check("Twitter : refusé à 3", not ACHATS and "3 codes reçus" in tout_texte(r))
        r = prendre(gid=TW, roles=[R50], n=2)
        check("Twitter : le 3e passe, sans lecture de rôles chez Discord",
              len(ACHATS) == 1 and not [1 for m, ch, kw in APPELS if "/members/" in ch], APPELS)
        check("Twitter : « tes 3 du jour », sans lecture de rôles",
              nx._quota_vu(nx._actif(f"{TW}:{VA}"), nx.SERVEURS[TW]) == 3
              and not [1 for m, ch, kw in APPELS if "/members/" in ch], APPELS)
    finally:
        numgen.herosms_key, numgen.get_number_herosms = _sav_hk, _sav_gh

    # 3. le panneau de 📱・numéro (Rem, cogs/numeros)
    print("3. panneau de Rem")
    EPH = []

    async def faux_eph(itx, texte):
        EPH.append(texte)
    num._ephemere = faux_eph
    cu._is_staff_member = lambda u: bool(getattr(u, "staff", False))
    LUS = []

    class Guilde:
        def __init__(self, gid, membres=()):
            self.id, self.name, self._m = int(gid), "TRUST INSTAGRAM", {m.id: m for m in membres}

        def get_member(self, uid):
            return self._m.get(int(uid))

        async def fetch_member(self, uid):
            LUS.append(int(uid))
            if int(uid) in self._f:
                return self._f[int(uid)]
            raise RuntimeError("404 Unknown Member")

    def membre(uid, roles, staff=False):
        return SimpleNamespace(id=int(uid), roles=[SimpleNamespace(id=int(r)) for r in roles],
                               staff=staff, display_name="va")

    def essai(n, roles=(), qui=None, par=None, gid=AG, fetch=None, cache=(), staff=False):
        EPH.clear()
        LUS.clear()
        u = membre(qui or VA, roles, staff)
        g = Guilde(gid, cache)
        g._f = {int(k): v for k, v in (fetch or {}).items()}
        salon = SimpleNamespace(id=5, name="📱・numéro", guild=g)
        num.numeros_du_jour = lambda uid, gid, maintenant=None: n
        itx = SimpleNamespace(user=u, guild=g, channel=salon)
        carte = num._CartePerso(salon, int(par or qui or VA), "va")
        return asyncio.run(num._quota_fr_ok(itx, carte, "sms", par)), list(EPH)

    ok, e = essai(3)
    check("Rem, sans rôle, 3 numéros : refusé « 3 numéros aujourd'hui »",
          ok is False and e and "3 numéros aujourd'hui" in e[0], e)
    ok, e = essai(3, [R10])
    check("Rem, Niveau 1, 3 numéros : le 4e passe", ok is True and not e, e)
    ok, e = essai(10, [R10])
    check("Rem, Niveau 1, 10 numéros : refusé « 10 numéros aujourd'hui »",
          ok is False and e and "10 numéros aujourd'hui" in e[0], e)
    ok, e = essai(19, [R20])
    check("Rem, Niveau 2, 19 : passe", ok is True)
    ok, e = essai(49, [R10, R50])
    check("Rem, Niveau 1 + 3, 49 : passe ; 50 : refusé",
          ok is True and essai(50, [R10, R50])[0] is False)
    ok, e = essai(4, [])
    check("Rem, rôle retiré : 4 numéros, refusé à 3", ok is False and "3 numéros" in e[0], e)
    ok, e = essai(3, [], qui=CHEF, par=VA, fetch={VA: membre(VA, [R20])})
    check("Rem, « Autre » d'un admin pour le VA (par) : les rôles du VA, lus chez Discord → 20",
          ok is True and LUS == [int(VA)], (ok, e, LUS))
    ok, e = essai(3, [R50], qui=CHEF, par=VA, fetch={})
    check("… VA introuvable : la base, refusé à 3 (les rôles de l'admin ne comptent pas)",
          ok is False and "3 numéros" in e[0], (ok, e))
    ok, e = essai(3, [], qui=CHEF, par=VA, cache=[membre(VA, [R10])])
    check("… VA en cache : lu sans appel à Discord", ok is True and not LUS, (ok, LUS))
    ok, e = essai(30, [], staff=True)
    check("Rem : le staff n'est pas bridé", ok is True)
    FR = None
    try:
        from cogs.outils import SERVEURS as _FR
        FR = next(iter(_FR), None)
    except Exception:                                        # noqa: BLE001
        pass
    if FR:
        ok, e = essai(3, [R50], gid=FR)
        check("Rem, serveur FR : un rôle de palier n'y vaut rien (3)", ok is False, e)

    # 4. la création des rôles
    print("4. création des rôles")
    ROLES_SRV = [{"id": AG, "name": "@everyone"}, {"id": "1", "name": "✅ Vérifié"}]
    POSTS = []

    def api_roles(methode, chemin, **kw):
        if methode == "GET" and chemin == f"/guilds/{AG}/roles":
            return 200, [dict(r) for r in ROLES_SRV]
        if methode == "POST" and chemin == f"/guilds/{AG}/roles":
            POSTS.append(kw.get("json"))
            r = {"id": str(800 + len(POSTS)), "name": kw["json"]["name"]}
            ROLES_SRV.append(r)
            return 200, r
        return 404, {}
    vd.api = api_roles
    r = pn.creer_roles(AG)
    check("essai : les 3 rôles seraient créés, rien n'est écrit",
          r["crees"] == [n for n, _q in pn.NOMS_ROLES] and not POSTS and r["essai"], r)
    r = pn.creer_roles(AG, essai=False)
    check("création : 3 rôles, sans permission, ni affichés à part ni mentionnables",
          len(POSTS) == 3 and all(p["permissions"] == "0" and not p["hoist"] and not p["mentionable"]
                                  for p in POSTS) and len(r["roles"]) == 3, (POSTS, r))
    r2 = pn.creer_roles(AG, essai=False)
    check("relancée : rien de recréé, les mêmes ids repris",
          len(POSTS) == 3 and r2["repris"] == [n for n, _q in pn.NOMS_ROLES] and r2["roles"] == r["roles"], r2)
    check("noms : Niveau 1/2/3 avec 10/20/50", [q for _n, q in pn.NOMS_ROLES] == [10, 20, 50]
          and all(f"Niveau {i}" in n and f"{q} SMS" in n for i, (n, q) in enumerate(pn.NOMS_ROLES, 1)))
    vd.api = faux_api

    # 5. la vraie table, telle qu'elle partira
    print("5. table livrée")
    vraie = VRAIS_PALIERS.get(AG) or {}
    check("TRUST INSTAGRAM : 3 rôles, 10 / 20 / 50", sorted(vraie.values()) == [10, 20, 50], vraie)
    check("… des ids Discord", all(str(k).isdigit() and len(str(k)) >= 17 for k in vraie), vraie)
    check("… aucun autre serveur", set(VRAIS_PALIERS) == {AG}, VRAIS_PALIERS)
finally:
    (vd.api, vd._EN_FOND, nx.FICHIER, num.HISTO_FILE, nx._dormir, tickets_discord.role_helper,
     numgen.get_number, numgen.get_code, numgen.cancel, numgen.getatext_key, numgen.compte,
     numgen.ALERTES_FICHIER, nx.numeros_du_jour, _p, num.numeros_du_jour,
     num._ephemere, cu._is_staff_member) = SAV
    pn.PALIERS.clear()
    pn.PALIERS.update(_p)

print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
