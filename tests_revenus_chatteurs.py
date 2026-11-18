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

            # ---- le bloc des chiffres facon Dashboard, la legende, les courbes
            cases = re.findall(r"<div class='mp-apercu-case[^>]*>.*?<div class='mp-apercu-nom'>(.*?)</div></div>", page, re.S)
            # l'interface se traduit : « Pourboires » sort « Tips » en anglais
            noms = ["Pourboires" if n == "Tips" else n
                    for n in (re.sub(r"<[^>]+>", "", c).split("≈")[0].strip() for c in cases)]
            check("le bloc des chiffres est celui du Dashboard : le total a gauche, six cases",
                  "class='mp-apercu-total" in page and len(cases) == 6 and "mypuls-stats-grid'" not in page, noms)
            check("... dans l'ordre de sa capture : Media on demand et Médias push a la place d'Abonnements et de "
                  "Parrainage, « Unlock ratio » en bas a droite a la place de Streams",
                  noms == ["Media on demand", "PPV débloqués", "Messages (PPV)", "Pourboires", "Médias push",
                           "Unlock ratio"], noms)
            check("... sans abonnements, parrainage ni streams",
                  not any(m in " ".join(noms) for m in ("Abonnement", "Parrainage", "Streams", "Posts")), noms)
            check("... media push et media a la demande : un tiret tant que MyPuls n'en envoie pas, jamais « $0.00 »",
                  "<span data-mp-stat='ca_push'>—</span>" in page and "<span data-mp-stat='ca_demande'>—</span>" in page)
            check("... et il garde les reperes que les scripts remplissent (total, PPV, pourboires, ventes, chatteurs)",
                  all(("data-mp-stat='%s'" % k) in page for k in
                      ("ca_total", "ca_ppv", "ca_tips", "nb_tx", "active_chatters", "nb_ppv", "unlock_ratio")))
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
    _tmp = tempfile.mkdtemp(prefix="tests_revenus_chatteurs_")
    try:
        test_photo_model(_tmp)
        test_identifiant(_tmp)
        test_chatting_par_rest(_tmp)
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
