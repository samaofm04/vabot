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
import time

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
    check("... et c'est dit, avec les deux chiffres", any("ne recoupe pas" in e for e in r["notes"]), r["notes"])
    check("... comme un constat, pas une panne : la reponse sera gardee, sans rappeler MyPuls a chaque page",
          r["erreurs"] == [], r["erreurs"])
    with Bouchon():
        r = rc.messages("2026-11-01", "2026-11-15", {})
    check("liste des comptes vide : total tous comptes, et c'est dit",
          r["par_compte"] is False and any("liste des comptes" in e for e in r["erreurs"]), r["erreurs"])
    check("... le total rendu est le vrai (moyle : 500, pas 5 fois 500)",
          {l[0]: l[2] for l in r["lignes"]}.get("moyle@example.com") == 500, r["lignes"])
    with Bouchon(messages=lambda d, f, creator="all": {"ok": False, "error": "Quota MyPuls atteint (429)"}):
        r = rc.messages("2026-11-01", "2026-11-15", COMPTES)
    check("l'appel echoue : aucune ligne, et l'erreur est nommee",
          r["lignes"] == [] and any("429" in e for e in r["erreurs"]), r)
    appels = []

    def un_compte_refuse(d, f, creator="all"):
        appels.append(str(creator))
        if str(creator) == "1733":
            return {"ok": False, "error": "Quota MyPuls atteint (429)"}
        return _stats_messages(d, f, creator)
    with Bouchon(messages=un_compte_refuse):
        r = rc.messages("2026-11-01", "2026-11-15", COMPTES)
    check("un compte refuse : on n'insiste pas sur les suivants (pas de rafale), et c'est dit UNE fois",
          appels == ["all", "1116", "1733"] and len(r["erreurs"]) == 1 and "Emmabrn" in r["erreurs"][0], (appels, r["erreurs"]))
    check("... le total tous comptes est affiche a la place", r["par_compte"] is False and all(l[1] == "*" for l in r["lignes"]))
    appels.clear()
    with Bouchon(messages=lambda d, f, creator="all": (appels.append(str(creator)), _stats_messages(d, f, creator))[1]):
        rc.messages("2026-11-01", "2026-11-15", COMPTES)
        n = len(appels)
        rc.messages("2026-11-01", "2026-11-15", COMPTES)
    check("les messages d'un compte sont gardes en memoire : aucun nouvel appel a la deuxieme lecture",
          n == 6 and len(appels) == 6, appels)


def test_cles_et_repli():
    print("\n--- MyPuls qui flanche : les cles et les derniers chiffres lus ---")
    sauve = (mypuls._cles_brutes, mypuls.api_configured, mypuls._make_session)
    maintenant = time.time()
    cles = [{"id": "saine", "token": "t1", "html_suite": 0},
            {"id": "ecartee", "token": "t2", "html_suite": 3, "html_ts": maintenant},
            {"id": "reessayee", "token": "t3", "html_suite": 4, "html_ts": maintenant - mypuls.PAUSE_HTML_S - 5},
            {"id": "ancienne", "token": "t4", "html_suite": 3}]
    try:
        mypuls._cles_brutes = lambda: cles
        tirees = {mypuls._cle_disponible()[0] for _ in range(60)}
        check("une cle qui vient de rendre 3 pages d'affilee est ecartee",
              "ecartee" not in tirees and "saine" in tirees, tirees)
        check("... mais REESSAYEE au bout de 10 minutes (avant : ecartee pour toujours, 8 cles sur 11 le 18/11/2026)",
              "reessayee" in tirees and "ancienne" in tirees, tirees)
    finally:
        mypuls._cles_brutes = sauve[0]

    with Bouchon() as b:
        vraie = b._sauve["fetch_team_stats"]
        try:
            mypuls.api_configured = lambda: True
            mypuls._make_session = lambda: None
            mypuls._STATS_CACHE.clear()
            r = vraie("2026-11-01", "2026-11-15", use_cache=True)
            check("lecture normale : 12 ventes, rien de perime", r.get("ok") and len(r["transactions"]) == 12 and "perime" not in r)
            mypuls.api_team_money = lambda *a, **k: {"ok": False, "error": "Réponse non-JSON"}
            for v in mypuls._STATS_CACHE.values():
                v["ts"] = 1.0
            r = vraie("2026-11-01", "2026-11-15", use_cache=True)
            check("MyPuls ne repond plus : les derniers chiffres lus sont resservis, pas une page d'erreur",
                  r.get("ok") is True and len(r["transactions"]) == 12 and isinstance(r.get("perime"), dict), r.get("error"))
            check("... avec l'heure de lecture et la VRAIE cause (l'API), pas « format de page inattendu »",
                  r["perime"].get("lu_a") == 1.0 and "API MyPuls indisponible (Réponse non-JSON)" in r["perime"].get("erreur", ""),
                  r.get("perime"))
            r = vraie("2026-09-01", "2026-09-15", use_cache=True)
            check("une periode jamais lue : erreur nette, avec la vraie cause, rien d'invente",
                  r.get("ok") is False and "API MyPuls indisponible" in (r.get("error") or ""), r)
        finally:
            mypuls.api_configured, mypuls._make_session = sauve[1], sauve[2]
            mypuls._STATS_CACHE.clear()


def test_longues_periodes():
    print("\n--- « Tout » et « Année » : MyPuls refuse plus de 92 jours ---")
    T = mypuls.tranches_api
    check("15 jours : une seule tranche, l'appel part tel quel", T("2026-11-01", "2026-11-15") == [("2026-11-01", "2026-11-15")])
    tr = T("2026-01-01", "2026-11-18")
    check("l'annee (322 jours) : 4 tranches de 90 jours au plus, de la plus recente a la plus ancienne",
          len(tr) == 4 and tr[0] == ("2026-08-21", "2026-11-18") and tr[-1][0] == "2026-01-01", tr)
    from datetime import date as _d
    check("... sans trou ni chevauchement",
          all((_d.fromisoformat(tr[i][0]) - _d.fromisoformat(tr[i + 1][1])).days == 1 for i in range(len(tr) - 1))
          and all((_d.fromisoformat(f) - _d.fromisoformat(d)).days <= 89 for d, f in tr), tr)
    sauve = (mypuls._api_team_money_tranche, mypuls._api_team_messages_stats_tranche)
    appels = []

    def fausse_tranche(start, end, *a, **k):
        appels.append((start, end))
        if (_d.fromisoformat(end) - _d.fromisoformat(start)).days > 91:
            return {"ok": False, "error": "HTTP 400 : Period too large (max 92 days)."}
        # des ventes seulement depuis juin 2026
        lot = [{"creator": "Lola", "attributed_user": "moyle", "amount": 10, "currency": "EUR", "kind": "ppv",
                "date": end + "T10:00:00+01:00"}] if end >= "2026-06-01" else []
        return {"ok": True, "ventes": lot, "pages": 1, "total_annonce": len(lot), "tronque": False}
    try:
        mypuls._api_team_money_tranche = fausse_tranche
        r = mypuls.api_team_money("1970-01-01", "2026-11-18")
        check("« Tout » (depuis 1970) : lu par tranches, aucune ne depasse 92 jours, pas d'erreur",
              r.get("ok") is True and len(r["ventes"]) >= 2, (r.get("ok"), r.get("error")))
        check("... et la lecture s'arrete apres six mois sans vente, au lieu de remonter 230 tranches jusqu'en 1970",
              len(appels) <= 6 and "lecture arrêtée" in (r.get("arret") or ""), (len(appels), r.get("arret")))
        # Le 18/11, l'ecran disait « aucune vente sur 180 jours avant le
        # 2023-12-05 » alors que le trou constate COMMENCAIT a cette date.
        check("... et la phrase borne le trou constate par ses deux dates, a la francaise",
              (r.get("arret") or "").startswith("aucune vente du 24/11/2025 au 22/05/2026 (180 jours)"),
              r.get("arret"))
        appels.clear()
        r = mypuls.api_team_money("2026-11-01", "2026-11-15")
        check("une periode courte : un seul appel, comme avant", len(appels) == 1 and r.get("ok"), appels)
        mypuls._api_team_money_tranche = lambda s, e, *a, **k: (
            {"ok": False, "error": "Quota MyPuls atteint (429)"} if e < "2026-08-21" else fausse_tranche(s, e))
        r = mypuls.api_team_money("2026-01-01", "2026-11-18")
        check("une tranche refusee : la lecture echoue en le disant, pas de total ampute presente comme entier",
              r.get("ok") is False and "429" in (r.get("error") or "") and "ventes du" in (r.get("error") or ""), r.get("error"))
        mypuls._api_team_messages_stats_tranche = lambda s, e, creator="all": {
            "ok": True, "non_attribues": 1,
            "par_chatteur": [{"user": "Moyle", "total_messages": 100, "ppv_messages": 4, "ppv_sold": 1,
                              "distinct_fans": 10, "total_words": 500}]}
        r = mypuls.api_team_messages_stats("2026-01-01", "2026-11-18")
        check("messages sur une longue periode : additionnes tranche par tranche (4 x 100)",
              r.get("ok") and r["par_chatteur"][0]["total_messages"] == 400 and r["par_chatteur"][0]["ppv_messages"] == 16
              and r.get("fans_approximatifs") is True, r)
    finally:
        mypuls._api_team_money_tranche, mypuls._api_team_messages_stats_tranche = sauve
    c = rc.complement("2026-01-01", "2026-11-18", COMPTES)
    check("le complement d'une longue periode : pas de comparaison, et c'est dit (aucun appel a MyPuls)",
          c.get("ok") is True and c.get("ventes_avant") is None and c.get("avant") is None
          and any("90 jours" in n for n in c.get("notes") or []), c.get("notes"))


def test_comptes():
    print("\n--- la liste des comptes ---")
    with Bouchon():
        check("par l'API : les 5 comptes, avec leur identifiant", rc.comptes() == COMPTES, rc.comptes())
        # Le cas constate en ligne le 18/11/2026 : la lecture par cookie rend vide.
        mypuls.list_creators = lambda force_refresh=False: {"ok": False, "error": "cookie"}
        check("la lecture par cookie echoue : la liste vient quand meme de l'API", rc.comptes() == COMPTES, rc.comptes())
        mypuls.list_creators = lambda force_refresh=False: {"ok": True, "creators": {"Ancienne": 7}}
        mypuls.api_creators_cached = lambda force=False: (_ for _ in ()).throw(RuntimeError("API en panne"))
        check("l'API echoue : la lecture par cookie complete", rc.comptes() == {"Ancienne": 7}, rc.comptes())


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


class _Membre:
    def __init__(self, uid, name, nick=""):
        self.id, self.name, self.global_name, self.display_name, self.nick, self.bot = uid, name, "", nick or name, nick, False
        self.display_avatar = type("A", (), {"url": "https://cdn.discordapp.com/avatars/%d/x.png?size=1024" % uid})()


class _Serveur:
    def __init__(self, gid, name, membres):
        self.id, self.name, self.members = gid, name, membres


class _Bot:
    def __init__(self, serveurs, pret=True):
        self.guilds, self._pret = serveurs, pret

    def is_ready(self):
        return self._pret


def test_deux_bots():
    print("\n--- un pseudo Discord se cherche chez les DEUX bots ---")
    import web_upload as w
    sauve = (w._BOT_REF, w._BOT_ADMIN_REF)
    commun = _Serveur(1, "Va IG", [_Membre(10, "abdoul_9684")])
    chatteurs = _Serveur(2, "Youlab Chatting", [_Membre(20, "ba_doo", "BA DOO OF 14 20H")])
    try:
        w._BOT_REF, w._BOT_ADMIN_REF = _Bot([commun]), None
        w._DISCORD_RESOLVE_CACHE.clear()
        check("bot principal seul : « ba_doo » introuvable (le cas du 18/11/2026)",
              w._resolve_discord_user_by_handle("ba_doo") is None)
        w._BOT_ADMIN_REF = _Bot([commun, chatteurs])
        w._DISCORD_RESOLVE_CACHE.clear()
        info = w._resolve_discord_user_by_handle("ba_doo") or {}
        check("le bot admin voit le serveur des chatteurs : « ba_doo » est trouve, avec sa photo en 128 px",
              info.get("username") == "ba_doo" and "size=128" in (info.get("avatar_url") or ""), info)
        check("un serveur vu par les deux bots n'est compte qu'une fois",
              [g.name for g in w._guildes_des_bots()] == ["Va IG", "Youlab Chatting"],
              [g.name for g in w._guildes_des_bots()])
        options, nb, _ = w._membres_discord_pour_liste("")
        check("la liste a choisir propose les membres des deux bots", nb == 2 and "value='ba_doo'" in options, (nb, options))
        d = w._discord_du_chatteur("inconnu99")
        check("pseudo introuvable : la reponse dit sur quels serveurs on a cherche",
              d["trouve"] is False and d["verifiable"] is True and d["serveurs"] == ["Va IG", "Youlab Chatting"], d)
        w._BOT_ADMIN_REF = _Bot([chatteurs], pret=False)
        w._DISCORD_RESOLVE_CACHE.clear()
        check("un bot pas pret ne compte pas : il n'a rien regarde",
              [g.name for g in w._guildes_des_bots()] == ["Va IG"] and w._resolve_discord_user_by_handle("ba_doo") is None)
        # Le serveur de chatting : reconnu par son nom, jamais par un prefixe.
        w._BOT_REF, w._BOT_ADMIN_REF = _Bot([commun, _Serveur(3, "YouLab AGENCY THREADS", [_Membre(30, "va_threads")])]), None
        check("aucun bot sur le serveur de chatting : il n'est pas reconnu (« ... THREADS » n'est pas lui)",
              w._guilde_chatteurs() == "", w._guilde_chatteurs())
        w._BOT_ADMIN_REF = _Bot([_Serveur(4, "YouLab  Agency", [_Membre(20, "ba_doo")])])
        check("un bot le voit : son nom exact est rendu, quelle que soit la casse",
              w._guilde_chatteurs() == "YouLab  Agency", w._guilde_chatteurs())
        options, nb, _ = w._membres_discord_pour_liste(w._guilde_chatteurs())
        check("... et sa liste ne contient QUE ses membres (pas les VA des autres serveurs)",
              nb == 1 and "value='ba_doo'" in options and "abdoul_9684" not in options and "va_threads" not in options, options)
        w._BOT_REF, w._BOT_ADMIN_REF = None, None
        check("aucun bot : rien n'est verifiable, on n'accuse personne",
              w._discord_observable() is False and w._discord_du_chatteur("ba_doo")["verifiable"] is False)
    finally:
        w._BOT_REF, w._BOT_ADMIN_REF = sauve
        w._DISCORD_RESOLVE_CACHE.clear()


def test_identifiant(tmp):
    print("\n--- relier par l'IDENTIFIANT Discord (sans serveur commun) ---")
    import verif_discord
    import web_upload as w
    sauve = (w._BOT_REF, w._BOT_ADMIN_REF, verif_discord.api, mypuls.DATA_DIR, mypuls.CHATTERS_FILE)
    mypuls.DATA_DIR = pathlib.Path(tmp) / "data_id"
    mypuls.CHATTERS_FILE = mypuls.DATA_DIR / "mypuls_chatters.json"
    appels = []
    connus = {"1551685501927424071": {"id": "1551685501927424071", "username": "ba_doo",
                                      "global_name": "BA DOO OF 14 20H", "avatar": "abc123"},
              "222222222222222222": {"id": "222222222222222222", "username": "sans_photo",
                                     "global_name": None, "avatar": None}}

    def faux_api(methode, chemin, **kw):
        appels.append((methode, chemin))
        uid = chemin.rsplit("/", 1)[-1]
        return (200, connus[uid]) if uid in connus else (404, {"message": "Unknown User"})
    try:
        # Le cas du 18/11/2026 : aucun bot ne partage de serveur avec le chatteur.
        w._BOT_REF, w._BOT_ADMIN_REF = _Bot([_Serveur(1, "Va IG", [_Membre(10, "abdoul_9684")])]), None
        verif_discord.api = faux_api
        check("17 a 20 chiffres = un identifiant ; un pseudo, meme en chiffres courts, n'en est pas un",
              w._est_identifiant_discord("1551685501927424071") and not w._est_identifiant_discord("ba_doo")
              and not w._est_identifiant_discord("12345"))
        check("pendant le rendu de la page : AUCUNE lecture chez Discord",
              w._discord_du_chatteur("1551685501927424071")["trouve"] is False and appels == [], appels)
        etat = w._relier_discord_du_chatteur("Baadooo", "1551685501927424071")
        check("en reliant : la photo et le nom viennent de Discord, sans serveur commun",
              etat["trouve"] and etat["par_id"] and etat["affiche"] == "BA DOO OF 14 20H"
              and etat["avatar"] == "https://cdn.discordapp.com/avatars/1551685501927424071/abc123.png?size=128", etat)
        fiche = mypuls.get_chatter_discord_fiche("Baadooo")
        check("... et ils sont retenus sur la fiche", fiche["avatar"].endswith("abc123.png?size=128") and fiche["maj"] > 0, fiche)
        appels.clear()
        rendu = w._discord_du_chatteur(fiche["discord"], fiche)
        check("au rendu suivant : la photo retenue est servie, toujours sans lecture chez Discord",
              rendu["trouve"] and rendu["avatar"] == fiche["avatar"] and appels == [], (rendu, appels))
        etat = w._relier_discord_du_chatteur("Ivan", "222222222222222222")
        check("un compte sans photo recoit la pastille par defaut de Discord",
              etat["trouve"] and "/embed/avatars/" in etat["avatar"] and etat["affiche"] == "sans_photo", etat)
        etat = w._relier_discord_du_chatteur("Tsiry", "999999999999999999")
        check("identifiant inconnu : dit introuvable, apres verification",
              etat["trouve"] is False and etat["verifiable"] is True and etat["par_id"] is True, etat)
        appels.clear()
        check("la reverification du jour ne relit pas ce qui vient d'etre verifie",
              w._rafraichir_discord_des_chatteurs(["Baadooo", "Ivan", "Tsiry", ""]) == {} and appels == [], appels)
        # Le lendemain : la fiche a plus de 24 h.
        data = mypuls._load_chatters()
        data["baadooo"]["discord_maj"] = 1.0
        mypuls._save_chatters(data)
        connus["1551685501927424071"]["avatar"] = "nouvelle"
        maj = w._rafraichir_discord_des_chatteurs(["Baadooo", "Ivan"])
        check("... mais reprend une fiche de plus de 24 h, et sa nouvelle photo",
              list(maj) == ["Baadooo"] and maj["Baadooo"]["avatar"].endswith("nouvelle.png?size=128")
              and len(appels) == 1, (maj, appels))
        # Un chatteur relie par identifiant AVANT cette version : rien de retenu.
        mypuls.set_discord("Vieux", "1551685501927424071")
        check("un identifiant saisi sans verification retenue : pas dit introuvable, il sera verifie",
              w._discord_du_chatteur("1551685501927424071", mypuls.get_chatter_discord_fiche("Vieux"))["verifiable"] is False)
        check("... et la reverification le prend en charge",
              "Vieux" in w._rafraichir_discord_des_chatteurs(["Vieux"]))
        mypuls.set_discord("Baadooo", "autre_pseudo")
        check("changer de Discord oublie la photo de l'ancien",
              mypuls.get_chatter_discord_fiche("Baadooo") == {"discord": "autre_pseudo", "avatar": "", "nom": "", "maj": 0.0},
              mypuls.get_chatter_discord_fiche("Baadooo"))
    finally:
        (w._BOT_REF, w._BOT_ADMIN_REF, verif_discord.api, mypuls.DATA_DIR, mypuls.CHATTERS_FILE) = sauve
        w._DISCORD_RESOLVE_CACHE.clear()


def test_chatting_par_rest(tmp):
    print("\n--- le serveur de chatting lu par un bot SANS programme ---")
    import verif_discord
    import web_upload as w
    sauve = (w._BOT_REF, w._BOT_ADMIN_REF, verif_discord.bots, verif_discord._http, mypuls.DATA_DIR, mypuls.CHATTERS_FILE)
    mypuls.DATA_DIR = pathlib.Path(tmp) / "data_rest"
    mypuls.CHATTERS_FILE = mypuls.DATA_DIR / "mypuls_chatters.json"
    appels = []
    serveurs = [{"id": "1", "name": "Va IG"}, {"id": "2", "name": "YouLab AGENCY THREADS"}]
    membres = [
        {"user": {"id": "111111111111111111", "username": "tsiry0403", "global_name": "Tsiry", "avatar": "h1"}, "nick": "Tsiry 02-08 / mercredi"},
        {"user": {"id": "222222222222222222", "username": "ba_doo", "global_name": None, "avatar": None}, "nick": None},
        {"user": {"id": "333333333333333333", "username": "un_bot", "bot": True}},
    ]

    def faux_http(bot, methode, chemin, **kw):
        appels.append(chemin)
        if chemin == "/users/@me/guilds":
            return 200, list(serveurs)
        if chemin.startswith("/guilds/9/members"):
            return 200, list(membres)
        return 404, {}

    def remise_a_zero():
        w._CHATTING_REST.update({"serveur": None, "serveur_ts": 0.0, "membres": None, "membres_ts": 0.0})
        w._DISCORD_RESOLVE_CACHE.clear()
        appels.clear()
    try:
        w._BOT_REF, w._BOT_ADMIN_REF = _Bot([_Serveur(1, "Va IG", [_Membre(10, "abdoul_9684")])]), None
        verif_discord.bots = lambda: [{"id": "siri", "nom": "Siri", "app_id": "1552153790701117480", "pret": True}]
        verif_discord._http = faux_http
        remise_a_zero()
        check("aucun bot sur le serveur de chatting : rien n'est vu (« ... THREADS » n'est pas lui)",
              w._serveur_chatting() == {} and w._membres_chatting_par_rest() is None, w._serveur_chatting())
        lien = w._invitation_lecteur_chatting()
        check("le lien d'invitation est celui du bot sans programme, SANS aucune permission",
              "client_id=1552153790701117480" in lien and "permissions=0" in lien and lien.endswith("scope=bot"), lien)
        n = len(appels)
        w._serveur_chatting()
        check("la recherche du serveur est gardee en memoire (pas un appel par ouverture)", len(appels) == n, appels)

        serveurs.append({"id": "9", "name": "YouLab AGENCY"})          # il vient d'etre invite
        remise_a_zero()
        check("une fois invite : le serveur est vu par ce bot",
              w._serveur_chatting() == {"nom": "YouLab AGENCY", "source": "rest"}, w._serveur_chatting())
        liste = w._membres_chatting_par_rest() or []
        check("ses membres sont lus, les bots ecartes",
              [m["username"] for m in liste] == ["tsiry0403", "ba_doo"], [m["username"] for m in liste])
        check("le surnom du serveur sert de nom affiche, la photo est celle de Discord",
              liste and liste[0]["affiche"] == "Tsiry 02-08 / mercredi"
              and liste[0]["avatar_url"] == "https://cdn.discordapp.com/avatars/111111111111111111/h1.png?size=128", liste[:1])
        appels.clear()
        check("pendant le rendu de la page : « tsiry0403 » n'est pas cherche chez Discord",
              w._discord_du_chatteur("tsiry0403")["trouve"] is False and appels == [], appels)
        etat = w._relier_discord_du_chatteur("Tsiry", "tsiry0403")
        check("en reliant : « tsiry0403 » est trouve sur le serveur de chatting, avec sa photo",
              etat["trouve"] and etat["affiche"] == "Tsiry 02-08 / mercredi" and etat["avatar"].endswith("/h1.png?size=128"), etat)
        fiche = mypuls.get_chatter_discord_fiche("Tsiry")
        appels.clear()
        rendu = w._discord_du_chatteur(fiche["discord"], fiche)
        check("au rendu suivant : la photo retenue est servie, sans lecture chez Discord",
              rendu["trouve"] and rendu["avatar"] == etat["avatar"] and appels == [], (rendu, appels))
        check("un pseudo se retrouve aussi par le surnom du serveur ou le nom affiche",
              (w._chatteur_par_rest("Tsiry 02-08 / mercredi") or {}).get("username") == "tsiry0403"
              and (w._chatteur_par_rest("BA_DOO") or {}).get("id") == "222222222222222222")
        etat = w._relier_discord_du_chatteur("Ivan", "pas_la")
        check("un pseudo absent du serveur : dit introuvable, apres verification",
              etat["trouve"] is False and etat["verifiable"] is True, etat)
        # Un pseudo saisi AVANT l'invitation du bot : la reverification le rattrape.
        mypuls.set_discord("Baadooo", "ba_doo")
        maj = w._rafraichir_discord_des_chatteurs(["Baadooo", "Tsiry", "Ivan"])
        check("un pseudo saisi avant l'invitation est rattrape par la reverification, sans rien ressaisir",
              list(maj) == ["Baadooo"] and maj["Baadooo"]["trouve"] and "/embed/avatars/" in maj["Baadooo"]["avatar"], maj)
        appels.clear()
        check("... qui ne relit rien de ce qui vient d'etre verifie",
              w._rafraichir_discord_des_chatteurs(["Baadooo", "Tsiry", "Ivan"]) == {} and appels == [], appels)
    finally:
        (w._BOT_REF, w._BOT_ADMIN_REF, verif_discord.bots, verif_discord._http, mypuls.DATA_DIR, mypuls.CHATTERS_FILE) = sauve
        w._CHATTING_REST.update({"serveur": None, "serveur_ts": 0.0, "membres": None, "membres_ts": 0.0})
        w._DISCORD_RESOLVE_CACHE.clear()


def test_photo_model(tmp):
    print("\n--- la photo d'une model ---")
    sauve = (mypuls._make_session, mypuls.DATA_DIR)
    mypuls.DATA_DIR = pathlib.Path(tmp) / "data_photos"
    JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 20
    appels = []

    class _Rep:
        def __init__(self, type_rendu, corps, code=200):
            self.status_code, self.headers, self.content = code, {"Content-Type": type_rendu}, corps

    class _Session:
        def __init__(self, rep):
            self.rep = rep

        def get(self, *a, **k):
            appels.append(a)
            return self.rep
    try:
        check("une image se reconnait a ses premiers octets, pas a l'en-tete",
              mypuls.type_image(JPEG) == "image/jpeg" and mypuls.type_image(b"\x89PNG\r\n\x1a\n...") == "image/png"
              and mypuls.type_image(b"<!doctype html>") == "" and mypuls.type_image(b"") == "")
        # Le cas du 18/11/2026 : MyPuls renvoie vers /securite/verifier, en 200.
        mypuls._make_session = lambda: _Session(_Rep("image/jpeg", b"\n<!doctype html><title>Verification</title>"))
        r = mypuls.get_avatar_bytes(3673)
        check("cookie mort : la page de MyPuls n'est PAS servie comme une photo, meme annoncee image/jpeg",
              r.get("ok") is False, r)
        check("... et rien n'est garde sur le disque", not mypuls._fichier_avatar(3673).exists())
        mypuls._make_session = lambda: _Session(_Rep("text/html", JPEG))
        r = mypuls.get_avatar_bytes(3673)
        check("une vraie image passe, avec son vrai type", r.get("ok") is True and r.get("content_type") == "image/jpeg"
              and r.get("source") == "mypuls", r)
        check("... et elle est gardee sur le disque", mypuls._fichier_avatar(3673).read_bytes() == JPEG)
        appels.clear()
        mypuls._make_session = lambda: _Session(_Rep("text/html", b"<html>connexion</html>"))
        r = mypuls.get_avatar_bytes(3673)
        check("cookie mort ENSUITE : la photo gardee est resservie, sans rien demander a MyPuls",
              r.get("ok") is True and r.get("content") == JPEG and r.get("source") == "disque" and appels == [], (r.get("source"), appels))
        vieux = time.time() - mypuls.AVATAR_FRAIS_S - 10
        os.utime(mypuls._fichier_avatar(3673), (vieux, vieux))
        r = mypuls.get_avatar_bytes(3673)
        check("photo de plus de 7 jours et MyPuls toujours muet : l'ancienne reste servie",
              r.get("ok") is True and r.get("content") == JPEG and "ancienne" in r.get("source", "") and len(appels) == 1, r.get("source"))
        NEUVE = b"\x89PNG\r\n\x1a\n" + b"neuve" * 10
        mypuls._make_session = lambda: _Session(_Rep("image/png", NEUVE))
        r = mypuls.get_avatar_bytes(3673)
        check("... et des que MyPuls repond, elle est remplacee",
              r.get("content") == NEUVE and mypuls._fichier_avatar(3673).read_bytes() == NEUVE, r.get("source"))
        mypuls._make_session = lambda: None
        check("aucun cookie et rien sur le disque : echec dit, pas d'image inventee",
              mypuls.get_avatar_bytes(1116).get("ok") is False)
    finally:
        mypuls._make_session, mypuls.DATA_DIR = sauve
    import revenus_ui
    from datetime import date
    page = revenus_ui.render_revenus_ui({"Lola": 3673})
    check("l'adresse des photos change chaque jour (une reponse cassee n'est pas gardee 24 h)",
          '"/mypuls/avatar/3673?j=%s"' % date.today().isoformat() in page)


def test_paie_nette():
    print("\n--- la paie des chatteurs sur le net OnlyFans, depuis le 01/11/2026 ---")
    P = mypuls.part_usd_payee
    check("une vente OnlyFans du 01/11/2026 ou apres compte nette (100 $ -> 80 $) ; avant, brute",
          [P(100, "2026-11-01T00:05:00+01:00"), P(100, "2026-11-18T12:00:00+01:00"),
           P(100, "2026-10-31T23:50:00+01:00"), P(100, "2026-06-10T12:00:00+02:00")] == [80.0, 80.0, 100.0, 100.0],
          [P(100, "2026-11-01T00:05:00+01:00"), P(100, "2026-10-31T23:50:00+01:00")])
    check("... le jour se lit a l'heure de Paris : 23 h 30 UTC le 31/10 est deja le 1er novembre",
          P(100, "2026-10-31T23:30:00+00:00") == 80.0, P(100, "2026-10-31T23:30:00+00:00"))
    check("... un jour deja ecrit « AAAA-MM-JJ » et l'ancien format « JJ/MM/AAAA » sont compris",
          [P(50, "2026-11-03"), P(50, "2026-10-20"), P(50, "20/10/2026 14:00"), P(50, "03/11/2026 14:00")]
          == [40.0, 50.0, 50.0, 40.0])
    check("... une date illisible : traitee comme une vente d'aujourd'hui (le net)", P(100, "??") == 80.0)
    check("les frais retires de la paie sont ceux du mode « Net » de la page (une seule valeur)",
          mypuls.FRAIS_OF_PAIE == rc.FRAIS_OF, (mypuls.FRAIS_OF_PAIE, rc.FRAIS_OF))
    B = mypuls.base_paie_usd
    check("base de paie : MYM converti + OnlyFans tel que la paie le compte (100 EUR a 1,10 + 160 $ = 270 $)",
          B({"ca_total": 300, "ca_eur": 100, "ca_usd": 200, "ca_usd_paie": 160}, 1.10) == 270.0)
    check("... sans cette part (ancien releve en memoire) : l'ancienne base, jamais zero",
          B({"ca_total": 300, "ca_eur": 100, "ca_usd": 200}, 1.10) == 310.0)
    check("... si le journal ne recoupe pas le CA (5 %) : on retombe sur le CA entier, comme avant",
          round(B({"ca_total": 500, "ca_eur": 100, "ca_usd": 200, "ca_usd_paie": 160}, 1.10), 2) == 550.0)
    with Bouchon():
        nov = {c["name"]: c for c in mypuls.fetch_team_stats("2026-11-01", "2026-11-15")["chatters"]}
        octo = {c["name"]: c for c in mypuls.fetch_team_stats("2026-10-16", "2026-10-31")["chatters"]}
    check("quinzaine de novembre : Baadooo, 280 $ de ventes OnlyFans -> 224 $ dans sa paie",
          nov["Baadooo"]["ca_usd"] == 280.0 and nov["Baadooo"]["ca_usd_paie"] == 224.0,
          (nov["Baadooo"].get("ca_usd"), nov["Baadooo"].get("ca_usd_paie")))
    check("... mazid, 20 EUR de MYM (inchange) et 80 $ d'OnlyFans (-> 64 $) : base 86 $",
          round(B(nov["mazid"], 1.10), 2) == 86.0, round(B(nov["mazid"], 1.10), 2))
    check("... un chatteur 100 % MYM ne bouge pas (moyle : 150 EUR -> 165 $)",
          round(B(nov["moyle@example.com"], 1.10), 2) == 165.0)
    # Vu en ligne le 18/11 : 1 123,97 $ de ventes -> 899,176 $ nets. Arrondie
    # au centime AVANT le pourcentage, la base donnait 125,89 $ ; le navigateur,
    # qui n'arrondit qu'a la fin, 125,88 $.
    un = [{"name": "ivan", "ca_total": 1123.97, "ca_ppv": 1123.97, "ca_tips": 0.0, "non_attribue": False}]
    mypuls._assembler_stats([{"chatter": "ivan", "creator": "Amelia", "amount": 1123.97, "currency": "USD",
                              "type": "Média privé", "date": "2026-11-05T10:00:00+01:00", "fan": "f"}],
                            un, "2026-11-01", "2026-11-15", {})
    check("la base n'est pas arrondie avant le pourcentage : 14 % de 899,176 $ = 125,88 $, pas 125,89 $",
          round(mypuls.base_paie_usd(un[0], 1.10) * 14 / 100.0, 2) == 125.88,
          (un[0].get("ca_usd_paie"), round(mypuls.base_paie_usd(un[0], 1.10) * 14 / 100.0, 2)))
    check("quinzaine d'octobre, deja reglee sur le brut : rien n'est recalcule (Baadooo 100 $ reste 100 $)",
          octo["Baadooo"]["ca_usd_paie"] == 100.0 and octo["mazid"]["ca_usd_paie"] == 10.0,
          (octo["Baadooo"].get("ca_usd_paie"), octo["mazid"].get("ca_usd_paie")))
    # Le registre des ventes (Excel, Google Sheet) : la meme base que la page.
    import ventes_export as ve
    lignes = ve.lignes_ventes([
        {"chatter": "Baadooo", "creator": "Amelia", "amount": 200, "currency": "USD", "type": "Média privé",
         "date": "2026-11-08T16:00:00+01:00"},
        {"chatter": "Baadooo", "creator": "Amelia", "amount": 100, "currency": "USD", "type": "Média privé",
         "date": "2026-10-23T16:00:00+02:00"},
        {"chatter": "mazid", "creator": "Lolatacrush", "amount": 20, "currency": "EUR", "type": "Média privé",
         "date": "2026-11-06T13:00:00+01:00"}])
    cols, paie = ve.paie_quinzaine(lignes, commissions={"_defaut_": 10}, eur_usd=1.10)
    i_base, i_pay, i_ca = cols.index("Base de paie (USD)"), cols.index("A payer (USD)"), cols.index("CA total (USD)")
    par = {(r[1], r[0]): r for r in paie}
    nov_b = next(r for (nom, q), r in par.items() if nom == "Baadooo" and "novembre" in q)
    oct_b = next(r for (nom, q), r in par.items() if nom == "Baadooo" and "octobre" in q)
    maz = next(r for (nom, q), r in par.items() if nom == "mazid")
    check("registre : la vente OnlyFans de novembre est payee sur le net (base 160 $, a payer 16 $), le CA reste 200 $",
          nov_b[i_base] == 160.0 and nov_b[i_pay] == 16.0 and nov_b[i_ca] == 200.0, nov_b[:12])
    check("... celle d'octobre reste sur le brut (base 100 $, a payer 10 $)",
          oct_b[i_base] == 100.0 and oct_b[i_pay] == 10.0, oct_b[:12])
    check("... et une vente MYM ne change pas (20 EUR -> 22 $, a payer 2,20 $)",
          maz[i_base] == 22.0 and maz[i_pay] == 2.2, maz[:12])


def test_planning_roles():
    print("\n--- planning : les roles Discord par shift et par model, et le rangement ---")
    import copy
    import chatting
    import planning_roles as pr
    attendus = pr.roles_attendus()
    noms = [r["nom"] for r in attendus]
    check("16 roles : les 4 shifts du planning, 9 models MYM, 3 models OnlyFans",
          len(noms) == 16 and noms[:4] == chatting.CRENEAUX and "Amelia MYM" in noms and "Alicia MYM" in noms
          and "Lola OF" in noms, noms)
    check("... sans Lia (marche US), et sans doublon",
          not any(n.split()[0].lower() == "lia" for n in noms) and len(set(noms)) == 16)
    check("... chaque model d'un role existe dans la liste du planning (sinon sa case ne se choisirait pas)",
          set(pr.MODELS["mym"]) <= set(chatting.MODELES_MYM) and set(pr.MODELS["of"]) <= set(chatting.MODELES_OF),
          (pr.MODELS, chatting.MODELES_MYM, chatting.MODELES_OF))
    roles = [{"id": str(100 + i), "name": n} for i, n in enumerate(noms)] + [{"id": "1", "name": "CHETTER MYM"}]
    ident = {r["name"]: r["id"] for r in roles}
    check("roles manquants : les 16 sur un serveur neuf, aucun quand ils y sont",
          len(pr.manquants([{"id": "1", "name": "CHETTER MYM"}])) == 16 and pr.manquants(roles) == [])
    check("... un role recree a la main sans accent ni majuscule est reconnu (« chloe mym », « 02H-08H »)",
          pr.manquants([{"id": "9", "name": "chloe  mym"}, {"id": "8", "name": "02H-08H"}])
          == [n for n in noms if n not in ("Chloé MYM", "02h-08h")])

    def planning():
        mym = {"id": "e1", "name": "Planning MYM", "rows": []}
        of = {"id": "e2", "name": "Planning OnlyFans", "rows": []}
        mgr = {"id": "e3", "name": "Planning Managers", "kind": "manager", "rows": [dict(chatting.nouvelle_ligne(""), pseudo="Ghost")]}
        for creneau, pseudo, dc, modele in (("02h-08h", "Jerry", "skurt01577", "Emma"), ("14h-20h", "Moyle", "moyle0502", "Emma"),
                                            ("08h-14h", "Fessal", "", "Lola"), ("20h-02h", "Sans Discord", "", "")):
            mym["rows"].append(dict(chatting.nouvelle_ligne(creneau), pseudo=pseudo, discord_username=dc, modele=modele,
                                    presence_by_week={"2026-11-16": {"lun": "Retard"}}))
        return {"edts": [mym, of, mgr]}

    def membre(pseudo, affiche, *roles_m):
        return {"username": pseudo, "affiche": affiche, "roles": [ident[r] for r in roles_m] + ["1"]}
    membres = [membre("skurt01577", "Jerry", "02h-08h", "Emma MYM"),
               membre("moyle0502", "Moyle", "20h-02h", "Lola MYM", "Julia MYM"),
               membre("nouveau", "Nouveau", "08h-14h", "14h-20h", "Chloé MYM", "Amelia OF"),
               membre("fessal_dc", "Fessal", "08h-14h", "Lola MYM"),
               membre("demi", "Demi", "02h-08h"),
               membre("autre", "Autre")]
    lus = pr.lire(membres, roles)
    check("lecture : seuls les membres qui portent un de nos roles, dans l'ordre du planning",
          set(lus) == {"skurt01577", "moyle0502", "nouveau", "fessal_dc", "demi"}
          and lus["nouveau"] == {"affiche": "Nouveau", "shifts": ["08h-14h", "14h-20h"], "mym": ["Chloé"], "of": ["Amelia"]},
          lus.get("nouveau"))
    d = planning()
    r = pr.ranger(d, lus)
    mym, of, mgr = d["edts"]
    par = {(x["discord_username"], x["creneau"]): x for x in mym["rows"]}
    check("deja au bon endroit : la ligne ne bouge pas, elle est seulement marquee rangee",
          par[("skurt01577", "02h-08h")]["modele"] == "Emma" and par[("skurt01577", "02h-08h")]["roles_etat"] == "ok")
    check("il change de shift : SA ligne suit, avec ses presences, et prend ses models (« Julia+Lola »)",
          ("moyle0502", "14h-20h") not in par and par[("moyle0502", "20h-02h")]["modele"] == "Julia+Lola"
          and par[("moyle0502", "20h-02h")]["presence_by_week"] == {"2026-11-16": {"lun": "Retard"}}
          and [x["affiche"] for x in r["deplaces"]] == ["Moyle"], r["deplaces"])
    check("un nouveau, deux shifts, MYM et OnlyFans : une ligne par shift dans chaque planning",
          [(x["planning"], x["creneau"]) for x in r["crees"]]
          == [("Planning MYM", "08h-14h"), ("Planning MYM", "14h-20h"),
              ("Planning OnlyFans", "08h-14h"), ("Planning OnlyFans", "14h-20h")]
          and {x["modele"] for x in of["rows"]} == {"Amelia"} and of["rows"][0]["pseudo"] == "Nouveau", r["crees"])
    check("une ligne sans Discord qui porte EXACTEMENT son surnom est rattachee, pas doublee",
          par[("fessal_dc", "08h-14h")]["pseudo"] == "Fessal" and len([x for x in mym["rows"] if x["pseudo"] == "Fessal"]) == 1
          and [x["affiche"] for x in r["rattaches"]] == ["Fessal"], r["rattaches"])
    check("une ligne sans Discord au nom inconnu n'est jamais touchee",
          [x for x in mym["rows"] if x["pseudo"] == "Sans Discord"][0].get("roles_etat") is None)
    check("un shift sans model : rien n'est range, et il est nomme « incomplet »",
          r["incomplets"] == [{"pseudo": "demi", "affiche": "Demi", "manque": "model"}], r["incomplets"])
    check("le planning des managers n'est jamais touche", len(mgr["rows"]) == 1 and mgr["rows"][0].get("roles_etat") is None)
    check("le rapport compte 7 lignes rangees", r["ranges"] == 7, r["ranges"])
    avant = copy.deepcopy(d)
    r2 = pr.ranger(d, lus)
    check("rejoue sans changement de role : rien ne bouge",
          d == avant and not r2["crees"] and not r2["deplaces"] and not r2["rattaches"] and r2["ranges"] == 7)
    membres[0] = membre("skurt01577", "Jerry")                       # un manager lui retire ses roles
    nb = len(mym["rows"])
    r3 = pr.ranger(d, pr.lire(membres, roles))
    check("ses roles sont retires : la ligne RESTE, avec ses presences, marquee « perdu » et nommee",
          len(mym["rows"]) == nb and par[("skurt01577", "02h-08h")]["roles_etat"] == "perdu"
          and par[("skurt01577", "02h-08h")]["presence_by_week"]
          and [(x["affiche"], x["creneau"]) for x in r3["perdus"]] == [("Jerry", "02h-08h")], r3["perdus"])
    membres[0] = membre("skurt01577", "Jerry", "02h-08h", "Emma MYM")
    pr.ranger(d, pr.lire(membres, roles))
    check("... et rendus : la marque repasse a « rangee »", par[("skurt01577", "02h-08h")]["roles_etat"] == "ok")
    sans = {"edts": [{"id": "e3", "name": "Planning Managers", "kind": "manager", "rows": []}]}
    r4 = pr.ranger(sans, lus)
    check("aucun planning MYM ni OnlyFans : rien n'est cree au hasard, les chatteurs concernes sont nommes",
          sans["edts"][0]["rows"] == [] and len(r4["sans_planning"]) == 5, r4["sans_planning"])


def test_managers(tmp):
    print("\n--- managers et mini-boss : la matrice, la paie, le fichier ---")
    import revenus_managers as rm
    sauve = mypuls.DATA_DIR
    mypuls.DATA_DIR = pathlib.Path(tmp) / "data_managers"
    try:
        comptes = {"Lola": 3673, "Emma": 1733, "Lia": 3992, "SansVente": 77}
        segments = {"Lola": "of_fr", "Emma": "mym", "Lia": "of_us", "SansVente": "mym"}

        def v(model, chatteur, montant, devise, quand):
            return {"creator": model, "chatter": chatteur, "amount": montant, "currency": devise,
                    "type": "Média privé", "date": quand}
        ventes = [
            v("Emma", "moyle", 100, "EUR", "2026-11-03T10:00:00+01:00"),      # 8h-14h, 110 $
            v("Emma", "", 50, "EUR", "2026-11-03T21:00:00+01:00"),            # 20h-2h, 55 $, sans chatteur
            v("Emma", "Indéterminé (Créatrice)", 10, "EUR", "2026-11-04T01:30:00+01:00"),   # 20h-2h (passe minuit)
            v("Lola", "baadooo", 200, "USD", "2026-11-03T16:00:00+01:00"),    # 14h-20h, brut
            v("Lola", "baadooo", 40, "USD", "pas une date"),                   # sans heure
            v("Lia", "ivan", 300, "USD", "2026-11-03T03:00:00+01:00"),         # 2h-8h
            v("", "ivan", 999, "USD", "2026-11-03T03:00:00+01:00"),            # sans model
        ]
        mat = rm.matrice(ventes, 1.10, comptes, segments)
        L = mat["lignes"]
        check("matrice : une ligne par model, rangee par son identifiant MyPuls (il survit a un renommage)",
              set(L) == {"3673", "1733", "3992", "77"}, sorted(L))
        check("... MYM en euros converti au taux de la paie, range dans son shift (10 h -> 8h-14h)",
              L["1733"]["shifts"] == [0.0, 110.0, 0.0, 66.0], L["1733"]["shifts"])
        check("... 1 h 30 du matin tombe dans le shift 20h-2h, pas dans 2h-8h", L["1733"]["shifts"][3] == 66.0)
        check("... la part sans chatteur est rendue A PART (vide, ou le libelle de MyPuls)",
              L["1733"]["sans_chatteur"] == [0.0, 0.0, 0.0, 66.0], L["1733"]["sans_chatteur"])
        # Le 18/11, la premiere version payait sur le brut OnlyFans : Esras
        # affichait 134,51 $ la ou le proprietaire attendait 108 $ (5 % du net).
        check("... OnlyFans en dollars : rendu BRUT par MyPuls, compte NET ici (200 $ -> 160 $, frais de 20 % retires)",
              L["3673"]["shifts"] == [0.0, 0.0, 160.0, 0.0] and L["3673"]["heures"][16] == 160.0, L["3673"]["shifts"])
        check("... les frais OnlyFans retires sont rendus a part (40 $ a 16 h, 48 $ sur 24 h) ; aucun sur du MYM",
              L["3673"]["frais_of_h"][16] == 40.0 and L["3673"]["frais_of"] == 48.0 and L["1733"]["frais_of"] == 0.0,
              (L["3673"]["frais_of_h"][16], L["3673"]["frais_of"], L["1733"]["frais_of"]))
        check("... une vente sans heure lisible : hors des shifts, mais dans le total de la model (24 h)",
              L["3673"]["total"] == 192.0 and L["3673"]["sans_heure"] == 32.0, L["3673"])
        check("... une vente sans model : comptee, jamais ecartee en silence", mat["ecartees"] == 1, mat["ecartees"])
        check("... une model sans vente a quand meme sa ligne (sinon on ne pourrait pas la cocher)",
              L["77"]["total"] == 0 and L["77"]["segment"] == "mym")
        check("... l'ordre : du plus gros chiffre au plus petit", mat["ordre"][:3] == ["3992", "3673", "1733"], mat["ordre"])

        g = rm.enregistrer({"role": "manager", "nom": "  Ghost  ", "pct": "3,5", "discord": "@Ghost_45605 ",
                            "cases": {"1733": [3, 1, 1, 9, "x"], "3673": [], "": [0]}})
        check("manager cree : nom nettoye, « 3,5 » lu 3.5, pseudo sans arobase en minuscules",
              g["nom"] == "Ghost" and g["pct"] == 3.5 and g["discord"] == "ghost_45605" and g["id"].startswith("m_"), g)
        check("... les cases : un ancien numero de shift est relu comme sa plage d'heures (1 -> 8h-14h, 3 -> 20h-2h), "
              "sans doublon, hors 0-3 ecartes, model sans plage non gardee",
              g["cases"] == {"1733": [[8, 14], [20, 2]]}, g["cases"])
        d = rm.du(g, mat)
        check("... il touche 3,5 % de ses cases : 110 + 66 = 176 $ -> 6,16 $",
              d["ca"] == 176.0 and d["a_payer"] == 6.16 and d["nb_cases"] == 2 and d["nb_models"] == 1, d)
        check("... dont 66 $ de ventes sans chatteur, dits a part", d["sans_chatteur"] == 66.0, d["sans_chatteur"])
        rm.enregistrer({"id": g["id"], "crypto_type": "usdc", "crypto_address": " 0xabc "})
        g2 = rm.trouver(g["id"])
        check("mise a jour partielle : l'adresse change, le carre et le pourcentage restent",
              g2["crypto_type"] == "USDC" and g2["crypto_address"] == "0xabc" and g2["cases"] == {"1733": [[8, 14], [20, 2]]}
              and g2["pct"] == 3.5, g2)
        for mauvais, quoi in (({"role": "manager", "nom": "X", "pct": "120"}, "pourcentage au-dela de 100"),
                              ({"role": "manager", "nom": "   "}, "nom vide"),
                              ({"role": "patron", "nom": "X"}, "role inconnu"),
                              ({"id": "m_inconnu", "pct": 1}, "fiche inexistante"),
                              ({"id": g["id"], "crypto_type": "DOGE"}, "crypto inconnue")):
            try:
                rm.enregistrer(mauvais)
                refuse = False
            except ValueError:
                refuse = True
            check("refuse : " + quoi, refuse)
        check("... et un refus n'a rien ecrit de travers", len(rm.personnes()) == 1 and rm.trouver(g["id"])["pct"] == 3.5)

        # ---- heures libres (« shift 8-12 », « 22h-4h »)
        check("heures : 8h-12h = 8, 9, 10, 11 ; 22h-4h passe minuit ; « de 8 h a 8 h » = la journee",
              rm.heures_de([8, 12]) == [8, 9, 10, 11] and rm.heures_de([22, 4]) == [22, 23, 0, 1, 2, 3]
              and len(rm.heures_de([8, 8])) == 24)
        check("matrice : les ventes sont rendues HEURE PAR HEURE (10 h, 21 h, 1 h pour Emma)",
              L["1733"]["heures"][10] == 110.0 and L["1733"]["heures"][21] == 55.0 and L["1733"]["heures"][1] == 11.0
              and sum(L["1733"]["heures"]) == 176.0 and L["1733"]["sans_chatteur_h"][21] == 55.0, L["1733"]["heures"])
        libre = {"role": "manager", "pct": 10}
        check("heures libres 8h-12h : la vente de 10 h compte, celle de 21 h non",
              rm.du(dict(libre, cases={"1733": [[8, 12]]}), mat)["ca"] == 110.0)
        check("heures libres 22h-4h : seule la vente de 1 h 30 compte (celle de 21 h est avant)",
              rm.du(dict(libre, cases={"1733": [[22, 4]]}), mat)["ca"] == 11.0)
        d2 = rm.du(dict(libre, cases={"1733": [[20, 2], [22, 4]]}), mat)
        check("deux plages qui se recoupent (20h-2h et 22h-4h) : les heures communes ne paient qu'une fois",
              d2["ca"] == 66.0 and d2["a_payer"] == 6.6 and d2["nb_cases"] == 2, d2)
        check("une plage illisible est ecartee, une plage libre est gardee telle quelle",
              rm._cases({"1733": [[8, 12], [25, 3], ["a", 2], [22, 4], [8, 12]]}) == {"1733": [[8, 12], [22, 4]]})

        b = rm.enregistrer({"role": "miniboss", "nom": "Kiah", "pct": 2})
        base = dict(rm.trouver(b["id"]))
        check("mini-boss « Tout » : 2 % du NET de toutes les models sur 24 h (ventes sans heure comprises)",
              rm.du(base, mat)["ca"] == round(176 + 192 + 240, 2) and rm.du(base, mat)["a_payer"] == 12.16, rm.du(base, mat))
        check("mini-boss « MYM » : les models MYM seulement, deja nettes", rm.du(dict(base, portee="mym"), mat)["ca"] == 176.0)
        dof = rm.du(dict(base, portee="of"), mat)
        check("mini-boss « OnlyFans » : OF FR et OF US ensemble, en net (540 $ brut -> 432 $), frais dits (108 $)",
              dof["ca"] == 432.0 and dof["frais_of"] == 108.0 and dof["a_payer"] == 8.64, dof)
        check("mini-boss « Choisir » : les models cochees, rien d'autre",
              rm.du(dict(base, portee="choix", models=["3992"]), mat)["ca"] == 240.0)
        dman = rm.du({"role": "manager", "pct": 5, "cases": {"3673": [[14, 20]], "1733": [[8, 14]]}}, mat)
        check("manager sur une model OnlyFans et une MYM : 5 % de (160 net + 110) = 13,50 $, pas 5 % du brut",
              dman["ca"] == 270.0 and dman["a_payer"] == 13.5 and dman["frais_of"] == 40.0, dman)

        check("paye : coche pour UNE periode", rm.marquer_paye(g["id"], "2026-11-01", "2026-11-15", True, 6.16) == [g["id"]]
              and rm.payes("2026-11-01", "2026-11-15") == [g["id"]] and rm.payes("2026-11-16", "2026-11-30") == [])
        check("... et le montant verse ce jour-la est garde (il reste explicable si la regle change ensuite)",
              rm.montants_payes("2026-11-01", "2026-11-15") == {g["id"]: 6.16}
              and rm.montants_payes("2026-11-16", "2026-11-30") == {}, rm.montants_payes("2026-11-01", "2026-11-15"))
        check("... et decoche : la case et le montant partent ensemble",
              rm.marquer_paye(g["id"], "2026-11-01", "2026-11-15", False) == []
              and rm.montants_payes("2026-11-01", "2026-11-15") == {})
        check("retirer : la fiche quitte la liste mais reste gardee (rien n'est efface)",
              rm.retirer(g["id"]) is True and rm.trouver(g["id"]) is None
              and [r.get("nom") for r in rm.charger()["retires"]] == ["Ghost"])
        brut = (mypuls.DATA_DIR / "mypuls_managers.json").read_text(encoding="utf-8")
        check("le fichier est ecrit, lisible, par safe_json", json.loads(brut)["personnes"][0]["nom"] == "Kiah")
    finally:
        mypuls.DATA_DIR = sauve


def test_site(tmp):
    print("\n--- la page et ses deux routes ---")
    import web_upload as w
    sauve = (w._load_web_users, w._discord_observable, w._resolve_discord_user_by_handle,
             w._membres_discord_pour_liste, mypuls.DATA_DIR, mypuls.CHATTERS_FILE)
    sauve_guilde = w._serveur_chatting
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

            # ---- deposer la photo d'une model (cookie MyPuls absent du serveur)
            import io
            JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 30
            anonyme = app.test_client()
            depot = "/mypuls/avatar/3673/deposer"
            r = anonyme.post(depot, data={"photo": (io.BytesIO(JPEG), "a.jpg")}, content_type="multipart/form-data")
            check("depot sans session ni jeton : refuse (403)", r.status_code == 403, r.status_code)
            check("un role restreint ne peut pas demander de jeton (403)",
                  chatteur.get("/mypuls/avatars/jeton").status_code == 403)
            jeton = (admin.get("/mypuls/avatars/jeton").get_json() or {}).get("jeton") or ""
            check("un acces complet recoit un jeton de depot", len(jeton) == 32)
            r = anonyme.post(depot, data={"jeton": "faux" * 8, "photo": (io.BytesIO(JPEG), "a.jpg")},
                             content_type="multipart/form-data")
            check("un jeton invente : refuse (403)", r.status_code == 403, r.status_code)
            r = anonyme.post(depot, data={"jeton": jeton, "photo": (io.BytesIO(b"<html>pas une image</html>"), "a.jpg")},
                             content_type="multipart/form-data")
            check("avec le jeton, autre chose qu'une image : refuse (400)", r.status_code == 400, r.status_code)
            r = anonyme.post("/mypuls/avatar/424242/deposer", data={"jeton": jeton, "photo": (io.BytesIO(JPEG), "a.jpg")},
                             content_type="multipart/form-data")
            check("avec le jeton, un compte que le site ne connait pas : refuse (404)", r.status_code == 404, r.status_code)
            r = anonyme.post(depot, data={"jeton": jeton, "photo": (io.BytesIO(JPEG), "a.jpg")},
                             content_type="multipart/form-data")
            check("avec le jeton, la photo d'une model connue : acceptee, et la reponse est lisible depuis mypuls.app",
                  r.status_code == 200 and (r.get_json() or {}).get("ok")
                  and r.headers.get("Access-Control-Allow-Origin") == "https://mypuls.app", (r.status_code, r.get_json()))
            sauve_session = mypuls._make_session
            try:
                mypuls._make_session = lambda: None          # aucun cookie sur le serveur
                r = admin.get("/mypuls/avatar/3673")
                check("... elle est servie ensuite, meme sans aucun cookie MyPuls",
                      r.status_code == 200 and r.data == JPEG and r.mimetype == "image/jpeg", (r.status_code, r.mimetype))
                r = admin.get("/mypuls/avatar/1116")
                check("... une model sans photo deposee : 404, et la reponse n'est pas gardee",
                      r.status_code == 404 and "no-store" in (r.headers.get("Cache-Control") or ""), (r.status_code, r.headers.get("Cache-Control")))
            finally:
                mypuls._make_session = sauve_session

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

            # ---- le planning des chatteurs : il se sert des memes fonctions Discord
            # Le 18/11/2026, en refaisant les photos Discord de cette page, la
            # fonction _etat_discord a ete supprimee alors que le planning
            # l'appelle : « Erreur de chargement » pendant des heures, sans une
            # ligne au journal. Aucun test ne rendait le planning avec un pseudo.
            import chatting
            sauve_chat = (chatting.DATA_DIR, chatting.PLANNING_FILE)
            chatting.DATA_DIR = pathlib.Path(tmp) / "data"
            chatting.PLANNING_FILE = chatting.DATA_DIR / "chatting_planning.json"
            try:
                edt = chatting.create_edt("Planning MYM")
                for pseudo_dc in ("ba_doo", "inconnu_du_serveur", ""):
                    ligne = chatting.add_row(edt["id"], "08h-14h")
                    chatting.update_cell(edt["id"], ligne["id"], "discord_username", pseudo_dc)
                r = admin.get("/?lazy=chatplanning", headers={"X-Tab-Ajax": "1"})
                plan = r.get_data(as_text=True)
                check("planning des chatteurs : l'onglet se charge avec des pseudos Discord dans ses lignes",
                      r.status_code == 200 and "Erreur de chargement" not in plan
                      and plan.count("data-field='discord_username'") == 3, (r.status_code, plan[:120]))
                check("... un pseudo trouve porte sa photo et « Rattache a », un pseudo absent est signale",
                      "Rattache a Baadooo" in plan and "cdn.discordapp.com/avatars/42" in plan
                      and "inconnu_du_serveur" in plan and "⚠" in plan)
                bord, titre, pastille = w._etat_discord("ba_doo", 2, "")
                check("... et le verdict vient d'une seule fonction, toujours la (bordure verte pour un pseudo trouve)",
                      bord == "#22c55e" and titre == "Rattache a Baadooo" and "<img" in pastille, (bord, titre))
                check("... sans pseudo : rien a dire, rien a accuser", w._etat_discord("", 0, "")[0] == "#2a2a2a")
                # Un onglet qui plante doit l'ECRIRE au journal.
                import io, contextlib
                sauve_rendu = w._render_chatplanning_html
                tampon = io.StringIO()
                try:
                    w._render_chatplanning_html = lambda: (_ for _ in ()).throw(NameError("fonction_disparue"))
                    appli2 = w.create_app()
                    appli2.config["TESTING"] = True
                    c2 = appli2.test_client()
                    with c2.session_transaction() as s2:
                        s2["auth"], s2["username"], s2["role"] = True, "boss", "owner"
                    with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
                        casse = c2.get("/?lazy=chatplanning", headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
                finally:
                    w._render_chatplanning_html = sauve_rendu
                check("un onglet qui plante affiche son message ET ecrit la cause au journal (plus jamais en silence)",
                      "Erreur de chargement" in casse and "chatplanning" in tampon.getvalue()
                      and "fonction_disparue" in tampon.getvalue(), tampon.getvalue()[-200:])
                # ---- les roles Discord du planning : creer, ranger, afficher
                import planning_roles as pr_site
                import verif_discord
                noms_r = [x["nom"] for x in pr_site.roles_attendus()]
                serveur_r = {"roles": [{"id": "1", "name": "CHETTER MYM", "permissions": "0"}], "droit": False, "postes": []}

                def faux_http(bot, methode, chemin, **kw):
                    if methode == "POST" and chemin.endswith("/roles"):
                        if not serveur_r["droit"]:
                            return 403, {"message": "Missing Permissions"}
                        serveur_r["postes"].append(kw.get("json"))
                        serveur_r["roles"].append({"id": str(200 + len(serveur_r["roles"])), "name": kw["json"]["name"],
                                                   "permissions": "0"})
                        return 200, serveur_r["roles"][-1]
                    if methode == "GET" and chemin.endswith("/roles"):
                        return 200, list(serveur_r["roles"])
                    return 404, {}
                sauve_r = (w._chatting_par_rest, w._membres_chatting_par_rest, verif_discord._http)
                w._chatting_par_rest = lambda: {"bot": {"id": "siri", "nom": "Siri"}, "gid": "777", "nom": "YouLab AGENCY"}
                membres_r = []
                w._membres_chatting_par_rest = lambda: list(membres_r)
                verif_discord._http = faux_http
                w._CHATTING_REST.update({"roles": None, "roles_ts": 0.0, "rangement_ts": time.time()})
                try:
                    check("roles du planning : refuse sans session (401) et a un chatteur (403)",
                          app.test_client().post("/chatting/roles/creer").status_code == 401
                          and chatteur.post("/chatting/roles/creer").status_code == 403
                          and chatteur.post("/chatting/roles/ranger").status_code == 403)
                    jc = admin.post("/chatting/roles/creer").get_json() or {}
                    check("creer les roles sans le droit : Discord refuse, le site le DIT et donne le lien du droit, rien n'est cree",
                          jc.get("ok") is False and "Gérer les rôles" in (jc.get("message") or "")
                          and "permissions=268435456" in (jc.get("lien") or "") and serveur_r["postes"] == [], jc)
                    serveur_r["droit"] = True
                    jc = admin.post("/chatting/roles/creer").get_json() or {}
                    check("creer les roles avec le droit : les 16, sans aucune permission, et rien d'autre n'est touche",
                          jc.get("ok") is True and [x["name"] for x in serveur_r["postes"]] == noms_r
                          and all(x["permissions"] == "0" and x["mentionable"] is False for x in serveur_r["postes"])
                          and serveur_r["roles"][0]["name"] == "CHETTER MYM", jc.get("message"))
                    jc2 = admin.post("/chatting/roles/creer").get_json() or {}
                    check("... recliquer ne cree rien en double", jc2.get("ok") is True and len(serveur_r["postes"]) == 16, jc2)
                    ident_r = {x["name"]: x["id"] for x in serveur_r["roles"]}
                    membres_r.append({"id": "42", "username": "ba_doo", "affiche": "Baadooo", "pseudos": ["ba_doo", "Baadooo"],
                                      "avatar_url": "", "roles": [ident_r["20h-02h"], ident_r["Sarah MYM"], ident_r["Kiara MYM"]]})
                    membres_r.append({"id": "43", "username": "tout_neuf", "affiche": "Tout Neuf", "pseudos": ["tout_neuf"],
                                      "avatar_url": "", "roles": [ident_r["14h-20h"], ident_r["Alicia MYM"]]})
                    jr = admin.post("/chatting/roles/ranger").get_json() or {}
                    lignes_r = {x["discord_username"]: x for x in chatting.get_edt(edt["id"])["rows"] if x.get("discord_username")}
                    check("ranger : la ligne de ba_doo passe de 08h-14h a 20h-02h avec « Kiara+Sarah », un nouveau est cree",
                          jr.get("ok") is True and lignes_r["ba_doo"]["creneau"] == "20h-02h"
                          and lignes_r["ba_doo"]["modele"] == "Kiara+Sarah" and lignes_r["tout_neuf"]["creneau"] == "14h-20h"
                          and lignes_r["tout_neuf"]["modele"] == "Alicia" and lignes_r["tout_neuf"]["pseudo"] == "Tout Neuf",
                          (jr.get("message"), {k: (v["creneau"], v["modele"]) for k, v in lignes_r.items()}))
                    check("... la ligne d'un pseudo sans role n'a pas bouge",
                          lignes_r["inconnu_du_serveur"]["creneau"] == "08h-14h" and not lignes_r["inconnu_du_serveur"].get("roles_etat"))
                    plan2 = admin.get("/?lazy=chatplanning", headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
                    check("la barre « Rôles Discord » dit ce qui a ete range, sans role a creer, avec le bouton",
                          "id='chat-roles'" in plan2 and "<b>2</b> lignes rangées" in plan2 and "rôles à créer" not in plan2
                          and "Ranger maintenant" in plan2 and "rangé d&#x27;après ses rôles Discord" in plan2,
                          plan2[plan2.find("id='chat-roles'"):][:300] if "id='chat-roles'" in plan2 else "barre absente")
                    membres_r[0]["roles"] = []
                    admin.post("/chatting/roles/ranger")
                    plan3 = admin.get("/?lazy=chatplanning", headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
                    check("role retire : la ligne reste et porte « rôle retiré », la barre nomme le chatteur",
                          len(chatting.get_edt(edt["id"])["rows"]) == 4 and "chat-role-perdu" in plan3
                          and "Rôle retiré, ligne gardée : Baadooo (20h-02h)" in plan3)
                    vue_c = chatteur.get("/?lazy=chatplanning", headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
                    check("un chatteur voit le planning mais pas la barre des roles ni ses boutons",
                          "data-field='discord_username'" in vue_c and "id='chat-roles'" not in vue_c)
                    if shutil.which("node"):
                        rates_p = []
                        for i_s, bloc_s in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", plan2, re.S)):
                            f_s = pathlib.Path(tmp) / ("planning_%d.js" % i_s)
                            f_s.write_text(bloc_s, encoding="utf-8")
                            if subprocess.run([shutil.which("node"), "--check", str(f_s)], capture_output=True).returncode != 0:
                                rates_p.append(i_s)
                        check("les scripts de la page du planning passent node --check (le bouton des roles y est)",
                              not rates_p and "window.chatRoles" in plan2, rates_p)
                finally:
                    w._chatting_par_rest, w._membres_chatting_par_rest, verif_discord._http = sauve_r
            finally:
                chatting.DATA_DIR, chatting.PLANNING_FILE = sauve_chat

            # ---- managers et mini-boss : acces complets seulement
            url_m = "/mypuls/managers.json?start=2026-11-01&end=2026-11-15"
            check("managers : refuse sans session (401)", app.test_client().get(url_m).status_code == 401)
            check("managers : refuse a un chatteur, qui a pourtant l'onglet Revenus (403)",
                  chatteur.get(url_m).status_code == 403, chatteur.get(url_m).status_code)
            jm = admin.get(url_m).get_json() or {}
            check("managers : l'admin recoit la matrice, les 4 shifts et une liste vide",
                  jm.get("ok") is True and jm.get("personnes") == [] and len(jm.get("creneaux") or []) == 4
                  and "1116" in (jm.get("matrice") or {}).get("lignes", {}), jm.get("erreur"))
            fiche = {"role": "manager", "nom": "Ghost", "pct": 10, "discord": "ba_doo", "cases": {"1116": [[8, 14]]}}
            corps = {"fiche": fiche, "start": "2026-11-01", "end": "2026-11-15"}
            r = chatteur.post("/mypuls/managers/enregistrer", json=corps)
            check("managers : un role restreint ne peut rien enregistrer (403)", r.status_code == 403, r.status_code)
            import revenus_managers as rm_site
            check("... et rien n'a ete ecrit", rm_site.personnes() == [])
            jr = admin.post("/mypuls/managers/enregistrer", json=corps).get_json() or {}
            pers = jr.get("personne") or {}
            # Lolatacrush, 8h-14h : 100 + 15,33 (sans chatteur) + 20 euros, a 1,10
            check("managers : cree, et la fiche revient recalculee sur la periode (148,86 $ -> 14,89 $ a 10 %)",
                  jr.get("ok") is True and pers.get("ca") == 148.86 and pers.get("a_payer") == 14.89, pers)
            check("... la part sans chatteur est dite (16,86 $)", pers.get("sans_chatteur") == 16.86, pers.get("sans_chatteur"))
            check("... et la photo Discord est trouvee et retenue",
                  pers.get("discord_trouve") is True and "cdn.discordapp.com" in (pers.get("photo") or ""), pers.get("photo"))
            check("... les plages reviennent en heures, et la matrice porte les 24 heures",
                  pers.get("cases") == {"1116": [[8, 14]]} and len(jm["matrice"]["lignes"]["1116"]["heures"]) == 24, pers.get("cases"))
            jl = admin.post("/mypuls/managers/enregistrer", json={"fiche": {"id": pers.get("id"), "cases": {"1116": [[10, 11]]}},
                                                                "start": "2026-11-01", "end": "2026-11-15"}).get_json() or {}
            check("managers : des heures libres (10h-11h) : seule la vente de 10 h compte (110 $)",
                  (jl.get("personne") or {}).get("ca") == 110.0 and (jl.get("personne") or {}).get("cases") == {"1116": [[10, 11]]},
                  jl.get("personne"))
            jo = admin.post("/mypuls/managers/enregistrer", json={"fiche": {"id": pers.get("id"), "cases": {"3106": [[14, 20], [8, 14]]}},
                                                                "start": "2026-11-01", "end": "2026-11-15"}).get_json() or {}
            check("managers : sur une model OnlyFans, la paie est sur le NET (320 $ brut -> 256 $ -> 25,60 $ a 10 %)",
                  (jo.get("personne") or {}).get("ca") == 256.0 and (jo.get("personne") or {}).get("a_payer") == 25.6
                  and (jo.get("personne") or {}).get("frais_of") == 64.0, jo.get("personne"))
            admin.post("/mypuls/managers/enregistrer", json={"fiche": {"id": pers.get("id"), "cases": {"1116": [[8, 14]]}}})
            ko = admin.post("/mypuls/managers/enregistrer", json={"fiche": {"id": pers.get("id"), "pct": "abc"}}).get_json() or {}
            check("managers : un pourcentage illisible est refuse avec son message", ko.get("ok") is False and "ourcentage" in (ko.get("erreur") or ""), ko)
            rp = admin.post("/mypuls/managers/paye", json={"id": pers.get("id"), "start": "2026-11-01", "end": "2026-11-15", "paye": True})
            check("managers : « Paye » retient le montant calcule PAR LE SERVEUR ce jour-la (14,89 $)",
                  (rp.get_json() or {}).get("paye_montants") == {pers.get("id"): 14.89}
                  and (admin.get(url_m).get_json() or {}).get("paye_montants") == {pers.get("id"): 14.89}, rp.get_json())
            check("managers : « Paye » coche pour la periode affichee, pas pour une autre",
                  (rp.get_json() or {}).get("paye") == [pers.get("id")]
                  and (admin.get(url_m).get_json() or {}).get("paye") == [pers.get("id")]
                  and (admin.get("/mypuls/managers.json?start=2026-10-16&end=2026-10-31").get_json() or {}).get("paye") == [])
            check("... un chatteur ne peut ni cocher ni retirer (403)",
                  chatteur.post("/mypuls/managers/paye", json={"id": pers.get("id"), "start": "a", "end": "b", "paye": True}).status_code == 403
                  and chatteur.post("/mypuls/managers/retirer", json={"id": pers.get("id")}).status_code == 403)
            w._render_mypuls_section_html.invalidate()
            vue_chatteur = chatteur.get("/?tab=revenus&mp_start=2026-11-01&mp_end=2026-11-15").get_data(as_text=True)
            check("la page servie a un chatteur ne contient ni le nom du manager ni ce qu'il touche",
                  "Ghost" not in vue_chatteur and "$14.89" not in vue_chatteur and "148.86" not in vue_chatteur
                  and "mypuls_managers" not in vue_chatteur and "window.__mpManagersUrl" in vue_chatteur)
            check("managers : retirer range la fiche de cote",
                  (admin.post("/mypuls/managers/retirer", json={"id": pers.get("id")}).get_json() or {}).get("ok") is True
                  and (admin.get(url_m).get_json() or {}).get("personnes") == []
                  and len(rm_site.charger()["retires"]) == 1)

            # ---- les posts (case « Posts » du bloc du haut)
            url_p = "/mypuls/chatters/posts.json?start=2026-11-01&end=2026-11-15"
            check("posts : refuse sans session (401)", app.test_client().get(url_p).status_code == 401)
            check("posts : refuse a un role qui n'a pas l'ecran des revenus (403)",
                  monteur.get(url_p).status_code == 403, monteur.get(url_p).status_code)
            sauve_p = (mypuls.api_overview, mypuls.api_configured, mypuls.api_creators_cached,
                       mypuls.api_creator_stats_cached)
            appels_p = []

            def faux_agregat(d0, d1, taux=1.14, force=False, exclude=None, segment="all"):
                appels_p.append((segment, tuple(sorted(exclude or ()))))
                of, mym = {"all": (80.0, 7.4), "mym": (0.0, 7.4), "of_us": (60.0, 0.0), "of_fr": (20.0, 0.0)}[segment]
                return {"ok": True, "types": {"Posts": of + mym, "Messages": 999.0},
                        "types_of": {"Posts": of}, "types_mym": {"Posts": mym}, "errors": [], "manquantes": []}
            try:
                mypuls.api_overview = faux_agregat
                mypuls.api_configured = lambda: True
                mypuls.api_creators_cached = lambda force=False: [{"id": 1, "active": True}, {"id": 2, "active": False}]
                lus = []
                mypuls.api_creator_stats_cached = lambda cid, d0, d1: lus.append(cid) or {"ok": True}
                rp = admin.get(url_p).get_json() or {}
                check("posts : par segment, [net, brut] -- le brut remonte chaque plateforme a son taux (OF /0,80, MYM /0,74)",
                      rp.get("ok") is True and rp.get("posts") == {"all": [87.4, 110.0], "mym": [7.4, 10.0],
                                                                    "of_us": [60.0, 75.0], "of_fr": [20.0, 25.0]},
                      rp)
                check("... lu par la fonction du Dashboard, avec la meme liste de models ecartees",
                      [a[0] for a in appels_p] == ["all", "mym", "of_us", "of_fr"]
                      and all(a[1] == tuple(sorted(w.MODELES_ECARTES_REVENUS)) for a in appels_p), appels_p)
                check("... et les creatrices actives sont lues une a une avant l'agregat (pas de rafale)",
                      lus == [1], lus)
                long_p = admin.get("/mypuls/chatters/posts.json?start=2026-01-01&end=2026-11-18").get_json() or {}
                check("posts : au-dela de 90 jours, rien (MyPuls refuse), sans erreur",
                      long_p.get("posts") is None and long_p.get("erreurs") == [] and len(appels_p) == 4, long_p)
                check("posts : rien de partiel quand tout est lu", rp.get("partiel") is False, rp.get("partiel"))
                mypuls.api_overview = lambda *a, **k: dict(faux_agregat(*a, **k), manquantes=[{"nom": "n°3867"}])
                check("posts : une creatrice que MyPuls ne voit plus du tout ne rend pas le chiffre « partiel »",
                      (admin.get(url_p).get_json() or {}).get("partiel") is False)
                mypuls.api_overview = lambda *a, **k: dict(faux_agregat(*a, **k), errors=["Lia: 429"])
                check("posts : une lecture ratee, si -- le chiffre est alors un minimum",
                      (admin.get(url_p).get_json() or {}).get("partiel") is True)
                mypuls.api_overview = lambda *a, **k: {"ok": False, "error": "Quota MyPuls atteint (429)"}
                ko = admin.get(url_p).get_json() or {}
                check("posts : MyPuls en panne -> pas de chiffre, et la cause est dite",
                      ko.get("posts") is None and "429" in " ".join(ko.get("erreurs") or []), ko)
            finally:
                (mypuls.api_overview, mypuls.api_configured, mypuls.api_creators_cached,
                 mypuls.api_creator_stats_cached) = sauve_p

            # ---- la page
            # Comme en ligne le 18/11/2026 : la lecture par cookie ne rend rien.
            mypuls.list_creators = lambda force_refresh=False: {"ok": False, "error": "cookie"}
            w._render_mypuls_section_html.invalidate()
            page = admin.get("/?tab=revenus&mp_start=2026-11-01&mp_end=2026-11-15").get_data(as_text=True)
            m = re.search(r"window\.__mpCreatorAvatars=(\{.*?\});</script>", page, re.S)
            photos = json.loads(m.group(1)) if m else {}
            check("les photos des models sont la meme quand la lecture par cookie rend vide",
                  str(photos.get("Lola ღ")).startswith("/mypuls/avatar/3673?j=") and len(photos) == 5, photos)
            check("la liste des chatteurs est dans la page", "id='mp-tab-chatters'" in page, len(page))
            check("les deux boutons du tableau de bord y sont ($ / €, Net / Brut)",
                  "mp-fx-cur" in page and "mp-fx-mode" in page and "mpFxToggle('mode')" in page)
            m = re.search(r"window\.__mpChatterExtra = (\{.*?\});</script>", page, re.S)
            extra = json.loads(m.group(1)) if m else {}
            check("le Discord relie de Baadooo arrive avec sa photo",
                  extra.get("Baadooo", {}).get("avatar", "").startswith("https://cdn.discordapp.com/"), extra)
            check("la liste des membres n'est PAS dans la page (elle est servie a tous les roles)",
                  "<datalist id='mp-discord-membres'></datalist>" in page and "value='ba_doo'" not in page)
            w._serveur_chatting = lambda: {"nom": "YouLab AGENCY", "source": "bot"}
            j = admin.get("/mypuls/chatters/membres_discord.json").get_json() or {}
            check("... elle est lue a part par un acces complet, pour le serveur de chatting",
                  j.get("ok") and "value='ba_doo'" in (j.get("options") or "") and j.get("nb") == 2
                  and j.get("serveur") == "YouLab AGENCY", j)
            w._serveur_chatting = lambda: {}
            j = admin.get("/mypuls/chatters/membres_discord.json").get_json() or {}
            check("... aucun bot sur le serveur de chatting : liste VIDE (on ne propose pas les VA a la place)",
                  j.get("ok") and j.get("options") == "" and j.get("nb") == 0 and j.get("serveur") == "", j)
            check("... et le lien pour inviter le bot lecteur est fourni, sans permission",
                  "permissions=0" in (j.get("invitation") or ""), j.get("invitation"))
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
            # Le cas du 18/11/2026 : « Reset cookies » clique, plus aucun cookie.
            sauve_cfg = (mypuls.is_configured, mypuls.api_configured)
            try:
                mypuls.is_configured = lambda: False
                mypuls.api_configured = lambda: True
                w._render_mypuls_section_html.invalidate()
                sans = admin.get("/?tab=revenus&mp_start=2026-11-01&mp_end=2026-11-15").get_data(as_text=True)
                check("sans aucun cookie, mais avec des cles d'API : la page s'affiche quand meme",
                      "id='mp-tab-chatters'" in sans and "Cookies non configurés" not in sans)
                check("... et elle dit ce qui manque (les photos des models), sans rien bloquer",
                      "Aucun cookie MyPuls" in sans)
                mypuls.api_configured = lambda: False
                w._render_mypuls_section_html.invalidate()
                rien = admin.get("/?tab=revenus&mp_start=2026-11-01&mp_end=2026-11-15").get_data(as_text=True)
                check("ni cookie ni cle : la, le formulaire des cookies reste propose",
                      "Cookies non configurés" in rien and "id='mp-tab-chatters'" not in rien)
            finally:
                mypuls.is_configured, mypuls.api_configured = sauve_cfg
                w._render_mypuls_section_html.invalidate()
            check("sans revenu saisi a la main : ni les quatre cases a zero ni le formulaire « Nouveau revenu »",
                  "Nouveau revenu" not in page and "Chatteurs uniques" not in page and "Aucun revenu enregistré" not in page)
            check("le bouton « Réduire » n'est plus la (la ligne entiere ouvre et referme)", "mp-t-reduire" not in page)
            check("les photos de la legende portent leur couleur de repli et l'adresse du jour",
                  "data-couleur='#" in page and re.search(r"/mypuls/avatar/\d+\?j=\d{4}-\d\d-\d\d' data-couleur", page) is not None)

            # ---- la paie des chatteurs : nette depuis le 01/11/2026, serveur ET navigateur
            def a_payer(html, nom):
                m = re.search(r"data-chatter='%s' class='mp-chatter-row'>.*?class='mp-cell-pay'[^>]*>\$([\d.]+)</td>"
                              % re.escape(nom), html, re.S)
                return float(m.group(1)) if m else None
            check("page de novembre : Baadooo est paye sur le net OnlyFans (14 % de 224 $ = 31,36 $, plus 39,20 $)",
                  a_payer(page, "Baadooo") == 31.36, a_payer(page, "Baadooo"))
            check("... mazid : 14 % de (22 $ de MYM + 64 $ d'OnlyFans net) = 12,04 $ ; moyle, tout en MYM, ne bouge pas (23,10 $)",
                  a_payer(page, "mazid") == 12.04 and a_payer(page, "moyle@example.com") == 23.1,
                  (a_payer(page, "mazid"), a_payer(page, "moyle@example.com")))
            m = re.search(r"data-mp-stat='total_pay_usd'[^>]*>\$([\d.]+)<", page)
            check("... le total a payer suit (95,34 $), et la base est ecrite sous le titre",
                  m is not None and float(m.group(1)) == 95.34 and "Paie calculée sur le net depuis le 01/11/2026" in page,
                  m and m.group(1))
            w._render_mypuls_section_html.invalidate()
            page_oct = admin.get("/?tab=revenus&mp_start=2026-10-16&mp_end=2026-10-31").get_data(as_text=True)
            check("page d'octobre (quinzaine deja reglee) : Baadooo reste a 14 % du brut (14,00 $), rien n'est recalcule",
                  a_payer(page_oct, "Baadooo") == 14.0, a_payer(page_oct, "Baadooo"))
            check("la regle est donnee au navigateur, avec les memes constantes que le serveur",
                  "window.__mpPaieNet = {depuis:'%s', frais:%s};" % (mypuls.PAIE_NET_DEPUIS, mypuls.FRAIS_OF_PAIE) in page)
            fonction = re.search(r"function mpPayUsd\(d, pct, rate, perfCa\)\{.*?\n\}\n", page, re.S)
            noeud = shutil.which("node")
            if fonction and noeud:
                essai = (fonction.group(0) + "console.log(JSON.stringify(["
                         "mpPayUsd({ca_eur:20, ca_usd:80, ca_usd_paie:64}, 14, 1.10, 100),"
                         "mpPayUsd({ca_eur:20, ca_usd:80, ca_usd_paie:64}, 14, 1.10, null),"
                         "mpPayUsd({ca_eur:20, ca_usd:80}, 14, 1.10, 100),"
                         "mpPayUsd({ca_eur:20, ca_usd:80, ca_usd_paie:64}, 14, 1.10, 500)].map(function(x){return Math.round(x*100)/100;})));")
                f_js = pathlib.Path(tmp) / "paie.js"
                f_js.write_text(essai, encoding="utf-8")
                sortie_js = subprocess.run([noeud, str(f_js)], capture_output=True, text=True).stdout.strip()
                check("navigateur (mpPayUsd) : meme montant que le serveur (12,04 $), avec ou sans table de reference ; "
                      "sans part nette l'ancien calcul ; journal qui ne recoupe pas -> table de reference, comme avant",
                      sortie_js == "[12.04,12.04,14.28,77]", sortie_js)
            else:
                check("navigateur (mpPayUsd) : la fonction est dans la page", bool(fonction), "introuvable")

            # ---- le bloc des chiffres facon Dashboard, la legende, les courbes
            cases = re.findall(r"<div class='mp-apercu-case[^>]*>.*?<div class='mp-apercu-nom'>(.*?)</div></div>", page, re.S)
            # l'interface se traduit : « Pourboires » sort « Tips » en anglais
            noms = ["Pourboires" if n == "Tips" else n
                    for n in (re.sub(r"<[^>]+>", "", c).split("≈")[0].strip() for c in cases)]
            check("le bloc des chiffres est celui du Dashboard : le total a gauche, six cases",
                  "class='mp-apercu-total" in page and len(cases) == 6 and "mypuls-stats-grid'" not in page, noms)
            check("... dans l'ordre de sa capture : Media on demand et Médias push a la place d'Abonnements et de "
                  "Parrainage, « Unlock ratio » en bas a droite a la place de Streams",
                  noms[:5] == ["Media on demand", "Posts", "Messages (PPV)", "Pourboires", "Médias push"]
                  and noms[5].startswith("Unlock ratio"), noms)
            check("... sans abonnements, parrainage ni streams",
                  not any(m in " ".join(noms) for m in ("Abonnement", "Parrainage", "Streams")), noms)
            check("... « Posts » attend son chiffre (lu apres la page, a la meme source que le Dashboard)",
                  "<span data-mp-stat='ca_posts'>…</span>" in page and "window.__mpPostsUrl = '/mypuls/chatters/posts.json?" in page)
            check("... media push et media a la demande : un tiret tant que MyPuls n'en envoie pas, jamais « $0.00 »",
                  "<span data-mp-stat='ca_push'>—</span>" in page and "<span data-mp-stat='ca_demande'>—</span>" in page)
            check("... et il garde les reperes que les scripts remplissent (total, PPV, pourboires, ventes, chatteurs)",
                  all(("data-mp-stat='%s'" % k) in page for k in
                      ("ca_total", "ca_ppv", "ca_tips", "nb_tx", "active_chatters", "nb_ppv", "unlock_ratio",
                       "ca_posts", "ca_push", "ca_demande")))
            bloc = page[page.index("<div class='mp-apercu'>"):page.index("class='mp-revenue-chart'")]
            check("... une seule devise a la fois : plus aucun « ≈ … € » dans le bloc (ni sous le total, ni sous une case)",
                  "≈" not in bloc and "data-mp-stat-eur" not in bloc)
            visible = re.sub(r"<span hidden>.*?</span></span></span>", "", bloc, flags=re.S)
            check("... ni « ventes » ni « chatteurs actifs » sous le total ; les deux compteurs restent, caches, pour les onglets",
                  "ventes<" not in visible and "chatteurs actifs" not in visible and "data-mp-stat='nb_tx'" not in visible
                  and "<span hidden><span data-mp-stat='nb_tx'>" in bloc and "data-mp-stat='active_chatters'" in bloc)
            m = re.search(r"class='mp-apercu-gros'><span data-mp-stat='ca_total'>\$([\d,]+\.\d\d)</span>", page)
            check("... le total s'ecrit au centime, comme au Dashboard", m is not None, m and m.group(1))
            # Le 18/11, la troisieme model de la legende s'affichait en bleu
            # plein : son style en ligne contenait « background:#a855f7 », que
            # les themes repeignent en couleur d'accent sur tout bouton.
            boutons = re.findall(r"<button type='button' onclick=\"mpToggleCreator[^>]*>", page)
            check("aucune case de la legende ne porte de couleur de fond en ligne (plus de case bleue)",
                  bool(boutons) and not any("background:" in b for b in boutons)
                  and all("--mp-series-color:#" in b for b in boutons), boutons[:1])
            F = rc.famille
            check("une vente « Média push » ou « Média à la demande » irait dans sa case, pas dans les PPV",
                  [F("Média push"), F("Médias push"), F("Média à la demande"), F("Media on demand"),
                   F("Média privé"), F("Pourboires"), F("")] == ["u", "u", "d", "d", "p", "t", ""],
                  [F("Média push"), F("Média à la demande"), F("Media on demand"), F("Média privé")])
            check("les courbes ne sont plus « monotones » (paliers a plat puis montees a pic)",
                  "cubicInterpolationMode" not in page and "tension:.35" in page)

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
        w._serveur_chatting = sauve_guilde
        os.chdir(str(ICI))


if __name__ == "__main__":
    test_periode()
    test_agregat()
    test_messages()
    test_cles_et_repli()
    test_longues_periodes()
    test_comptes()
    test_complement()
    test_deux_bots()
    test_paie_nette()
    test_planning_roles()
    _tmp = tempfile.mkdtemp(prefix="tests_revenus_chatteurs_")
    try:
        test_photo_model(_tmp)
        test_identifiant(_tmp)
        test_chatting_par_rest(_tmp)
        test_managers(_tmp)
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
