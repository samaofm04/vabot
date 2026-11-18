# -*- coding: utf-8 -*-
"""tests_revenus_chatteurs.py — la liste des chatteurs de « Revenus chatteurs ».

Lancer :  python tests_revenus_chatteurs.py       (depuis le dossier bot/)

AUCUN RESEAU, AUCUNE ECRITURE DANS data/ : l'API MyPuls est bouchonnee, et le
programme se place dans un dossier temporaire avant de monter l'application —
la fiche des chatteurs (le Discord relie) s'ecrit donc la-bas, jamais dans le
vrai data/. Ne pas lancer dans /opt/va-bot pour autant : voir CLAUDE.md.

Ce que ce fichier garde :
  - la periode d'avant : une quinzaine se compare a la quinzaine d'avant, pas
    aux 15 jours glissants (un jour manquait, tous les % sortaient trop hauts) ;
  - les messages : si MyPuls ignorait le filtre par compte, la somme serait
    multipliee par le nombre de comptes sans une erreur — on doit le VOIR ;
  - une vente sans chatteur retrouve sa ligne (elle disparaissait au filtre) ;
  - relier un Discord est refuse a un role restreint ;
  - le JavaScript rendu passe `node --check` (une apostrophe mal placee casse
    le script de la page entiere, en silence).

Avec MAQUETTE_SORTIE=/chemin/page.html, la page rendue est aussi ecrite la,
complement compris, pour la regarder dans un navigateur.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ICI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import mypuls                      # noqa: E402
import revenus_chatteurs as rc     # noqa: E402

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (("  [%s]" % (detail,)) if detail != "" and not cond else ""))


# ============================================================ jeu d'essai
COMPTES = {"Lolatacrush": 1116, "Emmabrn": 1733, "Amelia": 3106, "Lola ღ": 3673, "Lia": 3992}
_PLATEFORMES = {1116: "mym", 1733: "mym", 3106: "onlyfans", 3673: "onlyfans", 3992: "onlyfans"}
_N = [0]


def _v(compte, chatteur, uid, montant, devise, genre, quand):
    _N[0] += 1
    return {"creator": compte, "attributed_user": chatteur, "attributed_user_id": uid,
            "fan": "fan%d" % _N[0], "amount": montant,
            "net": round(montant * (0.8 if devise == "USD" else 1), 2),
            "currency": devise, "kind": genre, "type": "", "date": quand, "payment_id": _N[0]}


VENTES = {
    "2026-11-01": [
        _v("Lolatacrush", "moyle@example.com", 1, 100, "EUR", "ppv", "2026-11-03T10:00:00+01:00"),
        _v("Lolatacrush", "moyle@example.com", 1, 50, "EUR", "tip", "2026-11-04T21:00:00+01:00"),
        _v("Lolatacrush", "Tsiry", 2, 40, "EUR", "ppv", "2026-11-05T03:00:00+01:00"),
        _v("Lolatacrush", "", None, 15.33, "EUR", "tip", "2026-11-06T12:00:00+01:00"),
        _v("Lolatacrush", "mazid", 4, 20, "EUR", "ppv", "2026-11-06T13:00:00+01:00"),
        _v("Emmabrn", "Tsiry", 2, 60, "EUR", "tip", "2026-11-07T15:00:00+01:00"),
        _v("Amelia", "Baadooo", 3, 200, "USD", "ppv", "2026-11-08T16:00:00+01:00"),
        _v("Amelia", "Ivan", 5, 120, "USD", "ppv", "2026-11-09T09:00:00+01:00"),
        _v("Lola ღ", "mazid", 4, 30, "USD", "tip", "2026-11-10T22:00:00+01:00"),
        _v("Lola ღ", "mazid", 4, 50, "USD", "ppv", "2026-11-11T23:30:00+01:00"),
        _v("Lola ღ", "Baadooo", 3, 80, "USD", "ppv", "2026-11-12T11:00:00+01:00"),
        _v("Lia", "", None, 300, "USD", "ppv", "2026-11-13T18:00:00+01:00"),
    ],
    "2026-10-16": [
        _v("Lolatacrush", "moyle@example.com", 1, 80, "EUR", "ppv", "2026-10-20T10:30:00+02:00"),
        _v("Lolatacrush", "moyle@example.com", 1, 20, "EUR", "tip", "2026-10-21T21:10:00+02:00"),
        _v("Lolatacrush", "Tsiry", 2, 100, "EUR", "ppv", "2026-10-22T04:00:00+02:00"),
        _v("Amelia", "Baadooo", 3, 100, "USD", "ppv", "2026-10-23T16:00:00+02:00"),
        _v("Lola ღ", "mazid", 4, 10, "USD", "tip", "2026-10-24T22:00:00+02:00"),
    ],
}
MESSAGES = {
    "2026-11-01": {
        "1116": {"moyle@example.com": (500, 20), "Tsiry": (300, 10), "mazid": (50, 2)},
        "1733": {"Tsiry": (200, 5)},
        "3106": {"Baadooo": (400, 30), "Ivan": (100, 8)},
        "3673": {"mazid": (250, 9), "Baadooo": (150, 12)},
        "3992": {},
    },
    "2026-10-16": {
        "1116": {"moyle@example.com": (600, 25), "Tsiry": (250, 12)},
        "1733": {}, "3106": {"Baadooo": (500, 20)}, "3673": {"mazid": (100, 3)}, "3992": {},
    },
}


def _stats_messages(debut, fin, creator="all", _ignorer_le_filtre=False):
    jour = str(debut)[:10]
    par_compte = MESSAGES.get(jour, {})
    if creator == "all" or _ignorer_le_filtre:
        somme = {}
        for lignes in par_compte.values():
            for nom, (m, e) in lignes.items():
                a = somme.setdefault(nom, [0, 0])
                a[0] += m
                a[1] += e
        lignes = {k: tuple(v) for k, v in somme.items()}
    else:
        lignes = par_compte.get(str(creator), {})
    return {"ok": True, "par_chatteur": [
        {"user": nom, "total_messages": m, "ppv_messages": e, "ppv_sold": 0, "distinct_fans": 1, "total_words": 1}
        for nom, (m, e) in lignes.items()], "non_attribues": 0}


class Bouchon:
    """Toutes les portes de MyPuls que la page et le complement empruntent."""

    NOMS = ("is_configured", "fetch_team_stats", "api_team_money", "api_team_messages_stats",
            "api_users", "list_creators", "api_creators_cached", "get_eur_usd_rate")

    def __init__(self, messages=_stats_messages):
        self.messages = messages

    def __enter__(self):
        self._sauve = {n: getattr(mypuls, n) for n in self.NOMS}
        mypuls.is_configured = lambda: True
        mypuls.api_team_money = lambda start, end, *a, **k: {
            "ok": True, "ventes": VENTES.get(str(start)[:10], []), "pages": 1,
            "total_annonce": len(VENTES.get(str(start)[:10], [])), "tronque": False}
        mypuls.api_team_messages_stats = self.messages
        mypuls.fetch_team_stats = lambda start_date="", end_date="", use_cache=True: \
            mypuls._team_stats_par_api(start_date, end_date)
        mypuls.api_users = lambda: {"ok": True, "membres": [
            {"user_id": 1, "is_active_now": True, "last_activity_at": "2026-11-18T00:42:26+01:00"},
            {"user_id": 3, "is_active_now": False, "last_activity_at": "2026-11-17T21:05:19+01:00"}]}
        mypuls.list_creators = lambda force_refresh=False: {"ok": True, "creators": dict(COMPTES)}
        mypuls.api_creators_cached = lambda force=False: [
            {"id": cid, "pseudo": nom, "platform": _PLATEFORMES[cid], "active": True}
            for nom, cid in COMPTES.items()]
        mypuls.get_eur_usd_rate = lambda force_refresh=False: {
            "rate": 1.10, "date": "2026-11-17", "source": "ecb", "cached_age_h": 1}
        rc.vider_cache()
        return self

    def __exit__(self, *a):
        for n, f in self._sauve.items():
            setattr(mypuls, n, f)
        rc.vider_cache()
        return False


# =============================================================== le module
def test_periode():
    print("\n--- la periode d'avant ---")
    P = rc.periode_precedente
    check("1-15 novembre -> 16-31 octobre (la quinzaine d'avant, pas 15 jours glissants)",
          P("2026-11-01", "2026-11-15") == ("2026-10-16", "2026-10-31"), P("2026-11-01", "2026-11-15"))
    check("16-30 novembre -> 1-15 novembre",
          P("2026-11-16", "2026-11-30") == ("2026-11-01", "2026-11-15"), P("2026-11-16", "2026-11-30"))
    check("1-15 mars -> 16-28 fevrier (mois court)",
          P("2026-03-01", "2026-03-15") == ("2026-02-16", "2026-02-28"), P("2026-03-01", "2026-03-15"))
    check("1-15 janvier -> 16-31 decembre de l'annee d'avant",
          P("2027-01-01", "2027-01-15") == ("2026-12-16", "2026-12-31"), P("2027-01-01", "2027-01-15"))
    check("un mois entier -> le mois d'avant",
          P("2026-11-01", "2026-11-30") == ("2026-10-01", "2026-10-31"), P("2026-11-01", "2026-11-30"))
    check("7 jours quelconques -> les 7 jours juste avant",
          P("2026-11-12", "2026-11-18") == ("2026-11-05", "2026-11-11"), P("2026-11-12", "2026-11-18"))
    check("un seul jour -> la veille",
          P("2026-11-18", "2026-11-18") == ("2026-11-17", "2026-11-17"), P("2026-11-18", "2026-11-18"))
    check("les shifts : 3 h -> 2h-8h, 23 h et 1 h -> 20h-2h, heure illisible -> aucun",
          [rc.creneau(h) for h in (3, 9, 15, 23, 1, -1)] == [0, 1, 2, 3, 3, -1],
          [rc.creneau(h) for h in (3, 9, 15, 23, 1, -1)])


def test_agregat():
    print("\n--- les ventes de la periode d'avant, resserrees ---")
    with Bouchon():
        ventes = mypuls.fetch_team_stats("2026-10-16", "2026-10-31")["transactions"]
        lignes = rc.agreger_ventes(ventes)
    par = {(l[0], l[1], l[2]): l for l in lignes}
    check("une ligne par (chatteur, model, shift) : 5 ventes -> 5 lignes", len(lignes) == 5, len(lignes))
    m = par.get(("moyle@example.com", "Lolatacrush", 1))
    check("PPV de 10 h 30 : shift 8h-14h, en euros, compte comme 1 PPV debloque",
          bool(m) and m[3] == 0 and m[4] == 80 and m[5] == 80 and m[6] == 0 and m[7] == 1, m)
    m = par.get(("moyle@example.com", "Lolatacrush", 3))
    check("pourboire de 21 h 10 : shift 20h-2h, range en tips", bool(m) and m[4] == 20 and m[5] == 0 and m[6] == 20, m)
    m = par.get(("baadooo", "Amelia", 2))
    check("vente OnlyFans : marquee en dollars", bool(m) and m[3] == 1 and m[4] == 100, m)
    sans = rc.agreger_ventes([{"chatter": "", "creator": "Lia", "amount": 9, "currency": "USD",
                               "type": "Média privé", "date": "2026-10-20T10:00:00+02:00"}])
    check("une vente sans chatteur porte le nom de SA ligne (pas une cle vide)",
          sans and sans[0][0] == rc.SANS_CHATTEUR.lower(), sans)
    check("un montant illisible n'emporte pas les autres ventes",
          len(rc.agreger_ventes([{"chatter": "a", "creator": "c", "amount": "abc", "type": "PPV", "date": ""},
                                 {"chatter": "a", "creator": "c", "amount": 5, "type": "PPV", "date": ""}])) == 1)


def test_messages():
    print("\n--- messages et PPV envoyes, compte par compte ---")
    with Bouchon():
        r = rc.messages("2026-11-01", "2026-11-15", COMPTES)
    par = {(l[0], l[1]): l for l in r["lignes"]}
    check("le detail par compte recoupe le total : il est garde", r["par_compte"] is True and not r["erreurs"], r)
    check("mazid : 50 messages sur le compte MYM, 250 sur le compte OnlyFans",
          par.get(("mazid", "Lolatacrush"), [0, 0, 0])[2] == 50 and par.get(("mazid", "Lola ღ"), [0, 0, 0])[2] == 250, par)
    with Bouchon(messages=lambda d, f, creator="all": _stats_messages(d, f, creator, _ignorer_le_filtre=True)):
        r = rc.messages("2026-11-01", "2026-11-15", COMPTES)
    check("MyPuls ignore le filtre par compte : la somme gonflee n'est PAS affichee",
          r["par_compte"] is False and all(l[1] == "*" for l in r["lignes"]), r["lignes"][:3])
    check("... et c'est dit, avec les deux chiffres", any("ne recoupe pas" in e for e in r["erreurs"]), r["erreurs"])
    check("... le total rendu est le vrai (moyle : 500, pas 5 fois 500)",
          {l[0]: l[2] for l in r["lignes"]}.get("moyle@example.com") == 500, r["lignes"])
    with Bouchon(messages=lambda d, f, creator="all": {"ok": False, "error": "Quota MyPuls atteint (429)"}):
        r = rc.messages("2026-11-01", "2026-11-15", COMPTES)
    check("l'appel echoue : aucune ligne, et l'erreur est nommee",
          r["lignes"] == [] and any("429" in e for e in r["erreurs"]), r)


def test_complement():
    print("\n--- le complement lu apres la page ---")
    with Bouchon():
        ventes = mypuls.fetch_team_stats("2026-11-01", "2026-11-15")["transactions"]
        c = rc.complement("2026-11-01", "2026-11-15", COMPTES, ventes)
        check("reponse entiere, sans erreur", c.get("ok") is True and c.get("erreurs") == [], c.get("erreurs"))
        check("compare a la quinzaine d'avant", c.get("avant") == ["2026-10-16", "2026-10-31"], c.get("avant"))
        check("les frais envoyes sont ceux du tableau de bord (OF 20 %, MYM 26 %)",
              c.get("frais") == {"of": 0.20, "mym": 0.26}, c.get("frais"))
        check("presence : moyle en ligne, Baadooo vu le 17/11, Tsiry sans fiche d'equipe -> absent",
              c["presence"].get("moyle@example.com", [None])[0] is True
              and c["presence"].get("baadooo", [None])[0] is False and "tsiry" not in c["presence"], c["presence"])
        appels = []
        vraie = mypuls.api_users
        mypuls.api_users = lambda: (appels.append(1), vraie())[1]
        rc.complement("2026-11-01", "2026-11-15", COMPTES, ventes)
        check("une reponse saine est gardee en memoire : pas de second aller-retour", appels == [], appels)
    with Bouchon(messages=lambda d, f, creator="all": {"ok": False, "error": "Quota MyPuls atteint (429)"}):
        ventes = mypuls.fetch_team_stats("2026-11-01", "2026-11-15")["transactions"]
        c = rc.complement("2026-11-01", "2026-11-15", COMPTES, ventes)
        check("messages en panne : la reponse reste ok, les ventes d'avant sont la",
              c.get("ok") is True and c.get("ventes_avant") and c.get("messages") is None, c.get("messages"))
        check("... l'erreur est remontee", any("429" in e for e in c.get("erreurs") or []), c.get("erreurs"))
        appels = []
        mypuls.api_users = lambda: (appels.append(1), {"ok": True, "membres": []})[1]
        rc.complement("2026-11-01", "2026-11-15", COMPTES, ventes)
        check("une reponse amputee n'est PAS gardee : la suivante retente", appels == [1], appels)
    check("periode illisible : refus net, pas d'exception",
          rc.complement("hier", "demain", COMPTES).get("ok") is False)


# ================================================================ le site
def _scripts(html):
    """Les <script> rendus, sans ceux qui ne sont pas du JavaScript."""
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I):
        attrs, corps = m.group(1), m.group(2)
        if "src=" in attrs or not corps.strip():
            continue
        if re.search(r"type=['\"]?(application/(ld\+)?json|text/template|text/plain)", attrs, re.I):
            continue
        yield corps


def test_site(tmp):
    print("\n--- la page et ses deux routes ---")
    import web_upload as w
    sauve = (w._load_web_users, w._discord_observable, w._resolve_discord_user_by_handle,
             w._membres_discord_pour_liste, mypuls.DATA_DIR, mypuls.CHATTERS_FILE)
    # Tout ce qui s'ecrit pendant ce cas tombe dans le dossier temporaire.
    os.chdir(tmp)
    mypuls.DATA_DIR = pathlib.Path(tmp) / "data"
    mypuls.CHATTERS_FILE = mypuls.DATA_DIR / "mypuls_chatters.json"
    try:
        app = w.create_app()
        app.config["TESTING"] = True
        # Les deux comptes existent : is_auth refuse une session dont le
        # compte n'est plus dans le fichier.
        w._load_web_users = lambda: {"chatteur1": {"role": "chatter", "password": "x"},
                                     "mont1": {"role": "montage", "password": "x"},
                                     "boss": {"role": "owner", "password": "x"}}
        w._discord_observable = lambda: True
        w._resolve_discord_user_by_handle = lambda h, g="": (
            {"id": "42", "username": "ba_doo", "display_name": "Baadooo",
             "avatar_url": "https://cdn.discordapp.com/avatars/42/a.png?size=128"}
            if str(h).lower() == "ba_doo" else None)
        w._membres_discord_pour_liste = lambda g="": (
            "<option value='ba_doo'>Baadooo</option><option value='tsiry.r'>Tsiry</option>", 2, False)
        admin = app.test_client()
        with admin.session_transaction() as s:
            s["auth"], s["username"], s["role"] = True, "boss", "owner"
        chatteur = app.test_client()
        with chatteur.session_transaction() as s:
            s["auth"], s["username"], s["role"] = True, "chatteur1", "chatter"

        with Bouchon():
            # ---- relier un Discord
            r = chatteur.post("/mypuls/chatter/set_discord", data={"name": "Baadooo", "discord": "ba_doo"})
            check("role restreint : relier un Discord est refuse (403)", r.status_code == 403, r.status_code)
            check("... et rien n'a ete ecrit", mypuls.get_chatter_discord("Baadooo") == "")
            r = admin.post("/mypuls/chatter/set_discord", data={"name": "Baadooo", "discord": "@Ba_Doo "})
            j = r.get_json() or {}
            check("admin : le pseudo est garde sans arobase, en minuscules, et la photo revient",
                  j.get("ok") and j.get("discord") == "ba_doo" and j.get("trouve") is True
                  and "cdn.discordapp.com" in (j.get("avatar") or ""), j)
            check("... il est sur la fiche du chatteur", mypuls.get_chatter_discord("Baadooo") == "ba_doo")
            # Un patch local du serveur s'accroche a ce dictionnaire : une cle
            # de plus l'a fait tomber le 18/11/2026 (adresses crypto perdues
            # de vue sur la page de paie).
            check("... la fiche garde EXACTEMENT ses six cles (un patch du serveur s'y accroche)",
                  sorted(mypuls.get_chatter_meta("Baadooo")) == ["commission_pct", "crypto_address", "crypto_file",
                                                                 "crypto_network", "crypto_type", "paid_periods"],
                  sorted(mypuls.get_chatter_meta("Baadooo")))
            check("... la commission de la fiche n'a pas bouge",
                  mypuls.get_chatter_meta("Baadooo")["commission_pct"] == mypuls.DEFAULT_COMMISSION_PCT)
            j = (admin.post("/mypuls/chatter/set_discord", data={"name": "Tsiry", "discord": "inconnu99"}).get_json() or {})
            check("pseudo que le bot ne trouve pas : garde, mais dit introuvable",
                  j.get("ok") and j.get("discord") == "inconnu99" and j.get("trouve") is False
                  and j.get("verifiable") is True and not j.get("avatar"), j)
            j = (admin.post("/mypuls/chatter/set_discord",
                            data={"name": "Indéterminé (Créatrice)", "discord": "x"}).get_json() or {})
            check("« Indéterminé (Créatrice) » n'est pas un chatteur : rien a relier", j.get("ok") is False, j)
            j = (admin.post("/mypuls/chatter/set_discord", data={"name": "Tsiry", "discord": ""}).get_json() or {})
            check("pseudo vide : le lien est retire", j.get("ok") and mypuls.get_chatter_discord("Tsiry") == "", j)

            # ---- le complement
            url = "/mypuls/chatters/complement.json?start=2026-11-01&end=2026-11-15"
            check("complement : refuse sans session (401)", app.test_client().get(url).status_code == 401)
            monteur = app.test_client()
            with monteur.session_transaction() as s:
                s["auth"], s["username"], s["role"] = True, "mont1", "montage"
            check("complement : refuse a un role qui n'a pas l'ecran des revenus (403)",
                  monteur.get(url).status_code == 403, monteur.get(url).status_code)
            # Le role « chatter » possede l'onglet Revenus : il lit ici ce
            # qu'il voit deja sur la page, rien de plus.
            check("complement : suit la garde de l'onglet (un role qui a l'ecran le lit)",
                  chatteur.get(url).status_code == 200, chatteur.get(url).status_code)
            comp = admin.get(url).get_json() or {}
            check("complement : rendu a l'admin, sans erreur", comp.get("ok") is True and comp.get("erreurs") == [],
                  comp.get("erreurs"))

            # ---- la page
            page = admin.get("/?tab=revenus&mp_start=2026-11-01&mp_end=2026-11-15").get_data(as_text=True)
            check("la liste des chatteurs est dans la page", "id='mp-tab-chatters'" in page, len(page))
            check("les deux boutons du tableau de bord y sont ($ / €, Net / Brut)",
                  "mp-fx-cur" in page and "mp-fx-mode" in page and "mpFxToggle('mode')" in page)
            m = re.search(r"window\.__mpChatterExtra = (\{.*?\});</script>", page, re.S)
            extra = json.loads(m.group(1)) if m else {}
            check("le Discord relie de Baadooo arrive avec sa photo",
                  extra.get("Baadooo", {}).get("avatar", "").startswith("https://cdn.discordapp.com/"), extra)
            check("la liste des membres n'est PAS dans la page (elle est servie a tous les roles)",
                  "<datalist id='mp-discord-membres'></datalist>" in page and "value='ba_doo'" not in page)
            j = admin.get("/mypuls/chatters/membres_discord.json").get_json() or {}
            check("... elle est lue a part par un acces complet",
                  j.get("ok") and "value='ba_doo'" in (j.get("options") or "") and j.get("nb") == 2, j)
            check("... et refusee a un role restreint, meme s'il a l'onglet Revenus (403)",
                  chatteur.get("/mypuls/chatters/membres_discord.json").status_code == 403,
                  chatteur.get("/mypuls/chatters/membres_discord.json").status_code)
            m = re.search(r"window\.__mpTransactions = (\[.*?\]);</script>", page, re.S)
            tx = json.loads(m.group(1)) if m else []
            check("chaque vente porte sa famille (PPV / pourboire)",
                  len(tx) == 12 and sorted({t.get("k") for t in tx}) == ["p", "t"], [t.get("k") for t in tx])
            sans = [t for t in tx if t.get("h") == rc.SANS_CHATTEUR]
            check("les 2 ventes sans chatteur portent le nom de leur ligne (plus de cle vide)",
                  len(sans) == 2 and not [t for t in tx if not t.get("h")], [t.get("h") for t in tx])
            check("... et cette ligne existe dans le tableau, jamais payee",
                  "data-chatter='(non attribué)'" in page and "mp-row-orphelin" in page)
            m = re.search(r"window\.__mpCryptoData = (\{.*?\});</script>", page, re.S)
            crypto = json.loads(m.group(1)) if m else {}
            check("... commission nulle pour elle dans le recalcul du navigateur",
                  crypto.get(rc.SANS_CHATTEUR, {}).get("commission_pct") == 0.0
                  and crypto.get(rc.SANS_CHATTEUR, {}).get("non_attribue") is True, crypto.get(rc.SANS_CHATTEUR))
            check("le script de la liste est celui du look TRUST", "mp-trust" in page and "mpRevenueBase" in page)

            # ---- le JavaScript rendu
            node = shutil.which("node")
            if node:
                rates = []
                blocs = [b for b in _scripts(page) if "mp" in b or "fx" in b]
                for i, bloc in enumerate(blocs):
                    f = pathlib.Path(tmp) / ("bloc%d.js" % i)
                    f.write_text(bloc, encoding="utf-8")
                    p = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
                    if p.returncode:
                        rates.append((i, p.stderr.strip().splitlines()[:4]))
                check("les %d scripts rendus de la page passent node --check" % len(blocs),
                      bool(blocs) and not rates, rates[:2])
            else:
                print("     (node absent : scripts non verifies)")

            sortie = os.environ.get("MAQUETTE_SORTIE")
            if sortie:
                # Le complement est servi sur place : la page se regarde sans serveur.
                bouchon = ("<script>window.__compBouchon=%s;(function(){var f=window.fetch;"
                           "window.fetch=function(u,o){if(String(u).indexOf('complement.json')>=0)"
                           "return Promise.resolve({status:200,json:function(){return Promise.resolve(window.__compBouchon);}});"
                           "return f?f(u,o):Promise.reject('hors ligne');};})();</script>"
                           % json.dumps(comp, ensure_ascii=False).replace("<", "\\u003c"))
                pathlib.Path(sortie).write_text(page.replace("<head>", "<head>" + bouchon, 1), encoding="utf-8")
                print("     page ecrite : " + sortie)
    finally:
        (w._load_web_users, w._discord_observable, w._resolve_discord_user_by_handle,
         w._membres_discord_pour_liste, mypuls.DATA_DIR, mypuls.CHATTERS_FILE) = sauve
        os.chdir(str(ICI))


if __name__ == "__main__":
    test_periode()
    test_agregat()
    test_messages()
    test_complement()
    _tmp = tempfile.mkdtemp(prefix="tests_revenus_chatteurs_")
    try:
        test_site(_tmp)
    except Exception as e:                                   # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("la page et ses routes : testables", False, repr(e)[:160])
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    print("\n%d OK, %d FAIL" % (len(OKS), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1 if FAILS else 0)
