# -*- coding: utf-8 -*-
"""tests_garde_creatrice.py — un tracking neuf naît chez la bonne créatrice.

Depuis le 28/10/2026, les liens des VA partent sur Lia (MyPuls 3992). La garde
du patch local 99-z-tracking-creator-guard (VPS) ne vérifie qu'Emy et Seren :
une bascule MyPuls ratée aurait créé le tracking d'un VA chez la créatrice
d'avant, et MyPuls ne sait pas l'effacer.

Ce qui est vérifié (liens_va.creer_tracking, enveloppe _garde_creatrice ;
revenus_segments) :
  - page MyPuls de Lia seule : création, sous le verrou de bascule, cookies
    tournés enregistrés AVANT ;
  - page d'une autre créatrice, ou bascule renvoyée ailleurs : rien créé ;
  - tracking rendu hors du profil de Lia : arrêt dit (« arreter ») ;
  - créatrice que la table ne connaît pas (MYM) : rien ne change ;
  - sans creator_id : celle de la config ;
  - _creer_ou_reprendre passe par la garde pour créer, pas pour reprendre ;
  - Lia est comptée en OF US dans les revenus ;
  - le parrainage d'Agency garde les subs Emy d'un filleul basculé (cumul).

Faux MyPuls : aucun appel réseau, rien dans data/.
Lancement : python tests_garde_creatrice.py
"""
from __future__ import annotations

import io
import json
import pathlib
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import mypuls                          # noqa: E402
import revenus_segments as rs          # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


LIA = "https://onlyfans.com/liasxcret"


def page(*profils):
    return "".join(f'<tr id="row-link-{i}"><td>x</td><td>{p}/c{i}</td></tr>'
                   for i, p in enumerate(profils, 1))


class Rep:
    def __init__(self, texte="", code=200):
        self.text, self.status_code = texte, code


class Sess:
    """La session MyPuls : la page de tracking-stats montre la créatrice
    qu'on lui a dit de montrer (MONDE["page"])."""
    def get(self, url, **kw):
        JOURNAL.append(("get", url.split("mypuls.app")[-1], mypuls._OF_SWITCH_LOCK._is_owned()))
        if "/switch-creator/" in url:
            return Rep(code=MONDE["code_bascule"])
        return Rep(MONDE["page"])


JOURNAL: list = []
MONDE = {"page": page(LIA, LIA), "code_bascule": 200, "rendu": f"{LIA}/c200"}


def faux_creer(nom, creator_id=None):
    JOURNAL.append(("creer", nom, creator_id, mypuls._OF_SWITCH_LOCK._is_owned()))
    return {"ok": True, "url": MONDE["rendu"], "code": MONDE["rendu"].rsplit("/", 1)[-1], "erreur": ""}


TMP = pathlib.Path(tempfile.mkdtemp(prefix="garde_creatrice_"))
_SAUVE_LV = {k: getattr(lv, k) for k in ("CONFIG_FICHIER", "_tracking_existant")}
_SAUVE_MP = {k: getattr(mypuls, k) for k in ("_make_session", "_save_rotated_cookies")}
try:
    lv.CONFIG_FICHIER = TMP / "liens_va_config.json"
    lv.CONFIG_FICHIER.write_text(json.dumps({"creator_id": 3992, "modele": "Lia", "mypuls_actif": True}))
    mypuls._make_session = lambda: Sess()
    mypuls._save_rotated_cookies = lambda s: JOURNAL.append(("cookies",))
    garde = lv._garde_creatrice(faux_creer)

    # ── la table, une seule ──
    check("Lia dans la table des comptes OF : profil liasxcret",
          lv.profil_of(3992) == LIA and rs.COMPTES_OF[3992] == ("Lia", "liasxcret"), lv.profil_of(3992))
    check("… Lia comptée en OF US dans les revenus (plus en OF FR)",
          rs.creator_segment(3992, "onlyfans") == "of_us" and 3992 in mypuls.OF_US_CREATOR_IDS)
    check("creer_tracking du module est gardé, son corps reste joignable (.brut)",
          lv.creer_tracking.__wrapped__ is not None and hasattr(lv.creer_tracking, "brut")
          and lv.creer_tracking.brut is lv.creer_tracking.__wrapped__.brut)

    # ── bascule réussie ──
    JOURNAL.clear()
    r = garde("Twitter VA 150 @neuf", 3992)
    etapes = [e[0] for e in JOURNAL]
    check("page de Lia seule : tracking créé chez Lia",
          r.get("ok") and r["url"] == f"{LIA}/c200" and ("creer", "Twitter VA 150 @neuf", 3992, True) in JOURNAL,
          (r, JOURNAL))
    check("… bascule vérifiée, cookies enregistrés, PUIS création — tout sous le verrou",
          etapes == ["get", "get", "cookies", "creer"]
          and JOURNAL[0][1].startswith("/switch-creator/3992") and JOURNAL[1][1] == "/tracking-stats/"
          and all(e[-1] is True for e in JOURNAL if e[0] in ("get", "creer")), JOURNAL)

    # ── sans creator_id : la config ──
    JOURNAL.clear()
    r = garde("Twitter VA 151 @cfg")
    check("sans creator_id : la créatrice de la config (Lia), vérifiée",
          r.get("ok") and JOURNAL[0][1].startswith("/switch-creator/3992")
          and ("creer", "Twitter VA 151 @cfg", None, True) in JOURNAL, JOURNAL)

    # ── bascule ratée : page d'une autre ──
    for label, pg, code in (("page de Seren (bascule restée sur elle)", page("https://onlyfans.com/seren.vale"), 200),
                            ("page de Lia ET d'Emy", page(LIA, "https://onlyfans.com/emy.brw"), 200),
                            ("page vide", "", 200),
                            ("bascule renvoyée ailleurs (HTTP 302 suivi en 404)", page(LIA), 404)):
        MONDE.update(page=pg, code_bascule=code)
        JOURNAL.clear()
        r = garde("Twitter VA 152 @rate", 3992)
        check(f"{label} : rien créé, dit",
              not r.get("ok") and r.get("refuse") and "rien créé" in r.get("erreur", "")
              and not [e for e in JOURNAL if e[0] == "creer"], (r, JOURNAL))
    MONDE.update(page=page(LIA), code_bascule=200)

    # ── créé quand même ailleurs ──
    MONDE["rendu"] = "https://onlyfans.com/emy.brw/c140"
    r = garde("Twitter VA 153 @ailleurs", 3992)
    check("tracking rendu chez Emy : arrêt dit, adresse donnée pour vérifier",
          not r.get("ok") and r.get("arreter") and r.get("tracking") == "https://onlyfans.com/emy.brw/c140", r)
    MONDE["rendu"] = f"{LIA}/c200"

    # ── créatrice inconnue de la table (MYM) ──
    JOURNAL.clear()
    r = garde("Amelia_VA_9", 769)
    check("créatrice hors table (MYM 769) : création directe, aucune bascule de plus",
          r.get("ok") and [e[0] for e in JOURNAL] == ["creer"], JOURNAL)

    # ── session absente ──
    mypuls._make_session = lambda: None
    JOURNAL.clear()
    r = garde("Twitter VA 154 @sans", 3992)
    check("sans session MyPuls : refusé, rien créé",
          not r.get("ok") and r.get("refuse") and not JOURNAL, (r, JOURNAL))
    mypuls._make_session = lambda: Sess()

    # ── _creer_ou_reprendre : créer passe par la garde, reprendre non ──
    _sauve_ct = lv.creer_tracking
    try:
        lv.creer_tracking = garde
        lv._tracking_existant = lambda nom, cid: ({"url": f"{LIA}/c60", "code": "c60"}
                                                  if nom == "Twitter VA 32 @bid_a" else None)
        JOURNAL.clear()
        r = lv._creer_ou_reprendre("Twitter VA 32 @bid_a", 3992)
        check("tracking déjà chez Lia : repris, aucune bascule",
              r.get("ok") and r.get("repris") and not JOURNAL, (r, JOURNAL))
        r = lv._creer_ou_reprendre("Twitter VA 155 @nouveau", 3992)
        check("tracking neuf : créé à travers la garde",
              r.get("ok") and [e[0] for e in JOURNAL] == ["get", "get", "cookies", "creer"], (r, JOURNAL))
    finally:
        lv.creer_tracking = _sauve_ct

    # ── parrainage Agency : le cumul garde les subs Emy d'avant la bascule ──
    import agency_accueil as aa
    fiche = {"tracking": f"{LIA}/c104", "anciens_trackings": ["https://onlyfans.com/emy.brw/c117/"],
             "variante": {"posee": True, "tracking": "https://onlyfans.com/seren.vale/c240"}}
    compte = {f"{LIA}/c104": 1, "https://onlyfans.com/emy.brw/c117": 7, "https://onlyfans.com/seren.vale/c240": 1}
    check("parrainage Agency : Lia + Seren + Emy d'avant la bascule (1 + 1 + 7)",
          aa.subs_fiche(fiche, compte) == 9, aa.subs_fiche(fiche, compte))
    check("… une adresse que MyPuls ne rend pas : inconnu, pas un cumul partiel",
          aa.subs_fiche(fiche, {f"{LIA}/c104": 1, "https://onlyfans.com/seren.vale/c240": 1}) is None)
finally:
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    for k, v in _SAUVE_MP.items():
        setattr(mypuls, k, v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
