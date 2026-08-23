# -*- coding: utf-8 -*-
"""tests_revenus_paie.py — banc d'essai des deux chemins qui portent de l'argent :
l'agregat API de la page Revenus (mypuls.api_overview) et l'onglet qui sert a
payer (ventes_export.paie_quinzaine).

Lancer :  python tests_revenus_paie.py       (depuis le dossier bot/)

100 % EN MEMOIRE : aucun acces reseau, aucune ecriture dans data/. L'API MyPuls
est bouchonnee en remplacant trois fonctions du module mypuls, restaurees a la
fin de chaque cas.

Chacune des verifications ci-dessous ECHOUE sur la version d'avant correctif —
c'est la seule raison d'etre de ce fichier. Deux regressions etaient passees a
travers les suites vertes :

  1. api_overview convertissait float(v) AVANT de regarder si le libelle etait
     connu : une valeur non numerique sous un libelle inconnu faisait lever
     l'agregat ENTIER. Le seul appelant avale l'exception, donc la page Revenus
     retombait en silence sur le scraping — qui ne contient pas les revenus
     « post ». Total sous-evalue, sans un mot a l'ecran.

  2. paie_quinzaine attribuait une vraie commission et un vrai « A payer » aux
     ventes dont la date est illisible, et les classait EN TETE de l'onglet de
     paie. Payees une premiere fois la, puis une seconde fois une fois la date
     rattachee a sa vraie quinzaine.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mypuls                      # noqa: E402
import ventes_export as ve         # noqa: E402

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (("  [%s]" % detail) if detail and not cond else ""))


# ====================================================================== API
class _ApiBouchon:
    """Remplace les trois portes d'entree de l'API le temps d'un cas.

    api_overview les resout comme des globales du module : les reaffecter
    suffit, et le vrai reseau n'est jamais touche."""

    def __init__(self, by_type, total=1100.0, currency="USD", platform="mym"):
        self.by_type, self.total = by_type, total
        self.currency, self.platform = currency, platform

    def __enter__(self):
        self._sauve = (mypuls.api_configured, mypuls.api_creators_cached,
                       mypuls.api_creator_stats_cached)
        mypuls.api_configured = lambda: True
        mypuls.api_creators_cached = lambda force=False: [
            {"id": 1, "pseudo": "lola", "active": True,
             "platform": self.platform, "currency": self.currency}]
        mypuls.api_creator_stats_cached = lambda cid, d1, d2: {
            "ok": True,
            "data": {"revenue": {"total": self.total, "currency": self.currency,
                                 "by_type": self.by_type}}}
        mypuls._API_OVERVIEW_CACHE.clear()
        return self

    def __exit__(self, *a):
        (mypuls.api_configured, mypuls.api_creators_cached,
         mypuls.api_creator_stats_cached) = self._sauve
        mypuls._API_OVERVIEW_CACHE.clear()
        return False


def _overview(by_type, **kw):
    """Un appel d'api_overview sur un bouchon. Rend (resultat, exception)."""
    with _ApiBouchon(by_type, **kw):
        try:
            return mypuls.api_overview("2026-08-01", "2026-08-15", 1.14), None
        except Exception as e:                       # noqa: BLE001
            return None, e


def test_api_overview():
    print("\n--- api_overview : un libelle qu'on ne comprend pas ne doit pas "
          "emporter l'agregat ---")

    # (1) valeur non numerique sous un libelle INCONNU. Avant correctif :
    #     TypeError: float() argument must be ... not 'dict'.
    out, err = _overview({"message": 100, "breakdown": {"a": 1}})
    check("by_type avec un sous-objet inconnu : pas d'exception",
          err is None, repr(err))
    check("by_type avec un sous-objet inconnu : ok=True",
          bool(out and out.get("ok")), repr(out))
    check("by_type avec un sous-objet inconnu : total_usd intact (1100.0)",
          bool(out) and out.get("total_usd") == 1100.0,
          out and out.get("total_usd"))
    check("by_type avec un sous-objet inconnu : la carte Messages est remplie",
          bool(out) and out["types"].get("Messages") == 100.0,
          out and out["types"])
    check("by_type avec un sous-objet inconnu : le libelle est REMONTE, "
          "pas avale en silence",
          bool(out) and any("breakdown" in x
                            for x in out["types_hors"]["libelles"]),
          out and out["types_hors"])

    # (2) montant a la francaise sous un libelle inconnu. Avant correctif :
    #     ValueError: could not convert string to float: '50,00'.
    out, err = _overview({"message": 100, "media_prive": "50,00"})
    check("by_type avec '50,00' sous un libelle inconnu : pas d'exception",
          err is None, repr(err))
    check("by_type avec '50,00' sous un libelle inconnu : ok=True et "
          "total_usd intact",
          bool(out) and out.get("ok") and out.get("total_usd") == 1100.0,
          repr(out))
    check("by_type avec '50,00' sous un libelle inconnu : le libelle est "
          "remonte",
          bool(out) and any("media_prive" in x
                            for x in out["types_hors"]["libelles"]),
          out and out["types_hors"])

    # (3) un montant illisible sous un libelle CONNU ne doit pas non plus
    #     faire tomber la creatrice entiere.
    out, err = _overview({"message": 100, "tip": "n/a"})
    check("montant illisible sous un libelle connu : pas d'exception",
          err is None, repr(err))
    check("montant illisible sous un libelle connu : le reste est compte",
          bool(out) and out["types"].get("Messages") == 100.0,
          out and out["types"])

    # (4) garde-fou de la fonctionnalite VOULUE par le commit : un libelle
    #     inconnu mais LISIBLE garde son montant. Sans ca, « Media prive »
    #     redisparait des cartes.
    out, err = _overview({"message": 100, "media_prive": 50})
    check("libelle inconnu lisible : le montant est conserve dans types_hors",
          bool(out) and out["types_hors"]["montant"] == 50.0,
          out and out["types_hors"])
    check("libelle inconnu lisible : son libelle est nomme en clair",
          bool(out) and out["types_hors"]["libelles"] == ["media_prive"],
          out and out["types_hors"])


# ===================================================================== PAIE
# Le scenario est celui du docstring du commit lui-meme : une vente datee, une
# vente « hier soir » (format que MyPuls ecrit parfois), une vente sans date.
_VENTES = [
    {"date": "05/08/2026 14:32", "chatter": "alice", "creator": "lola",
     "fan": "f1", "amount": 100, "currency": "EUR", "type": "PPV"},
    {"date": "hier soir", "chatter": "alice", "creator": "lola",
     "fan": "f2", "amount": 999, "currency": "EUR", "type": "PPV"},
    {"date": "", "chatter": "bob", "creator": "lola",
     "fan": "f3", "amount": 500, "currency": "USD", "type": "Tip"},
]


def test_paie_quinzaine():
    print("\n--- paie_quinzaine : une vente sans periode n'est pas payable ---")
    lignes = ve.lignes_ventes(_VENTES)
    cols, out = ve.paie_quinzaine(lignes,
                                  commissions={"alice": 20, "bob": 20},
                                  eur_usd=1.10)
    i_quinz = cols.index("Quinzaine")
    i_ca = cols.index("CA total (USD)")
    i_pct = cols.index("Commission %")
    i_pay = cols.index("A payer (USD)")

    # Ce que le commit a voulu, et qui doit tenir : plus rien n'est jete.
    check("les 3 ventes sont dans l'onglet (aucune jetee en silence)",
          len(out) == 3, "%d lignes" % len(out))

    illisibles = [r for r in out if r[i_quinz] == ve.QUINZAINE_INCONNUE]
    check("les 2 ventes a date illisible ont bien leur propre ligne",
          len(illisibles) == 2, "%d lignes" % len(illisibles))

    # Ce qui manquait : la ligne « a rattacher a la main » annoncait une somme
    # a verser. Avant correctif : 219.78 (alice) et 100.00 (bob).
    check("aucune commission sur une vente sans periode",
          all(r[i_pct] == 0.0 for r in illisibles),
          [r[i_pct] for r in illisibles])
    check("aucun « A payer » sur une vente sans periode",
          all(r[i_pay] == 0.0 for r in illisibles),
          [r[i_pay] for r in illisibles])

    # ... mais le CA reste chiffre et visible : c'etait tout l'interet de les
    # garder. Une ligne a 0 partout serait une regression de l'autre cote.
    check("le CA de ces ventes reste visible et chiffre",
          all(r[i_ca] > 0 for r in illisibles),
          [r[i_ca] for r in illisibles])

    # Le total de l'onglet : seule la vraie quinzaine est payable.
    # 100 EUR x 1.10 = 110 USD, a 20 % => 22.00. Avant correctif : 341.78.
    total_paye = round(sum(r[i_pay] for r in out), 2)
    check("total « A payer » de l'onglet = 22.00 USD (la seule vraie "
          "quinzaine)", total_paye == 22.00, total_paye)

    # Et la vraie quinzaine, elle, garde sa commission : le garde-fou ne doit
    # pas eteindre la paie normale.
    vraies = [r for r in out if r[i_quinz] != ve.QUINZAINE_INCONNUE]
    check("la vraie quinzaine reste payee normalement",
          len(vraies) == 1 and vraies[0][i_pct] == 20.0
          and vraies[0][i_pay] == 22.00,
          vraies)

    print("\n--- paie_quinzaine : « Indetermine (Creatrice) » reste non paye "
          "(non-regression) ---")
    lignes_na = ve.lignes_ventes([
        {"date": "05/08/2026 14:32", "chatter": "Indetermine (Creatrice)",
         "creator": "lola", "fan": "f4", "amount": 300, "currency": "EUR",
         "type": "PPV"}])
    _c2, out2 = ve.paie_quinzaine(lignes_na, commissions={"_defaut_": 20},
                                  eur_usd=1.10)
    check("une vente non attribuee n'est jamais payee",
          len(out2) == 1 and out2[0][i_pay] == 0.0, out2)


if __name__ == "__main__":
    test_api_overview()
    test_paie_quinzaine()
    print("\n%d OK, %d FAIL" % (len(OKS), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1 if FAILS else 0)
