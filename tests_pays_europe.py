# -*- coding: utf-8 -*-
"""tests_pays_europe.py — les pays riches d'Europe gardent le tracking du VA
sur TRUST TWITTER et TRUST INSTAGRAM, pas sur Threads (06/11/2026).

Propriétaire : « Europe seulement », « uniquement pour Twitter et Instagram ;
pour Threads que du US comme d'hab ». Sans réseau ni data/ : gms remplacé,
registres dans un dossier temporaire.
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

import gms                     # noqa: E402
import liens_va as lv          # noqa: E402
import pages_va as pv          # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


TW, TH, AG = lv.TWITTER_ID, lv.THREADS_ID, lv.AGENCY_IG_ID
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pays_europe_"))
SAV = (lv.ETAT_FICHIER, lv.config, gms.get_link, gms.update_link, lv.lia_seule, lv.PAUSE_PAYS_S, pv.FICHIER)
lv.ETAT_FICHIER = TMP / "liens_va.json"
pv.FICHIER = TMP / "pages_va.json"
CONFIG = {}
lv.config = lambda: dict(CONFIG)
lv.lia_seule = lambda g="": {"controle": 70, "base_modele": 30}
lv.PAUSE_PAYS_S = 0
EQ = {g: lv.espace(g)["equipe"] for g in (TW, TH, AG)}
EUROPE = {"FR", "DE", "CH", "AT", "BE", "NL", "LU", "DK", "SE", "NO", "FI", "IS", "MC", "LI", "AD"}
AVANT = {"US", "CA", "AU", "GB", "NZ", "IE", "BJ", "MG"}

# ── faux GetMySocial : liens directs et landings, geofilters gardés ──────
LIENS, ECRITS, REFUS = {}, [], {}


def f_get(lid, team_id=None):
    l = LIENS.get(lid)
    return {"ok": True, "link": json.loads(json.dumps(l))} if l else {"ok": False, "error": "404"}


def f_update(lid, champs, team_id=None):
    ECRITS.append((lid, team_id))
    if lid in REFUS:
        return {"ok": False, "error": REFUS[lid]}
    LIENS[lid].update(json.loads(json.dumps(champs)))
    return {"ok": True}


gms.get_link, gms.update_link = f_get, f_update


def direct(lid, tracking="https://onlyfans.com/liasxcret/c76"):
    LIENS[lid] = {"id": lid, "type": "direct", "url": tracking, "geofilters": [], "buttons": []}


def landing(lid, tracking="https://onlyfans.com/liasxcret/c76"):
    LIENS[lid] = {"id": lid, "type": "landing", "url": "", "buttons": [
        {"label": "MY FREE 0F", "url": tracking, "geofilters": []},
        {"label": "MY TELEGRAM", "url": "https://t.me/m/x"}]}


def vers_la_base(geo):
    """Les pays envoyés au compte de base (donc SANS le tracking du VA)."""
    return {x["country_code"] for x in geo or []}


try:
    # ── 1. les listes ────────────────────────────────────────────────────
    print("1. Listes par serveur")
    ct, ch, ca = (lv.cibles_pays(EQ[g]) for g in (TW, TH, AG))
    check("Twitter : l'Europe riche en plus des pays d'avant", ct == AVANT | EUROPE, sorted(ct))
    check("Instagram : pareil", ca == AVANT | EUROPE, sorted(ca))
    check("Threads : inchangé (« que du US comme d'hab »)", ch == AVANT, sorted(ch))
    check("Espagne, Italie, Portugal : dehors partout", not ({"ES", "IT", "PT"} & (ct | ca | ch)))
    check("sans équipe (hors poser_pays) : la liste d'avant", lv.cibles_pays() == AVANT)
    check("les 15 codes existent", EUROPE <= set(lv.TOUS_LES_PAYS))

    # ── 2. poser_pays : la liste suit l'équipe du lien ───────────────────
    print("2. poser_pays")
    direct("d_tw")
    r = lv.poser_pays("d_tw", EQ[TW])
    base = vers_la_base(LIENS["d_tw"]["geofilters"])
    check("lien direct Twitter : France, Allemagne, Suisse… gardent le tracking ; Espagne part à la base",
          r["ok"] and not (EUROPE & base) and "ES" in base and "US" not in base
          and len(base) == len(lv.TOUS_LES_PAYS) - len(AVANT | EUROPE), (r, sorted(EUROPE & base)))
    direct("d_th")
    lv.poser_pays("d_th", EQ[TH])
    check("lien direct Threads : la France part toujours à la base",
          EUROPE <= vers_la_base(LIENS["d_th"]["geofilters"]))
    landing("p_ig")
    r = lv.poser_pays("p_ig", EQ[AG])
    b0 = LIENS["p_ig"]["buttons"]
    check("landing Instagram : la règle sur le bouton OnlyFans seul, Europe gardée ; Telegram intact",
          r["ok"] and not (EUROPE & vers_la_base(b0[0]["geofilters"])) and "geofilters" not in b0[1], b0)
    check("après l'appel, plus d'équipe en cours (la liste d'avant hors poser_pays)",
          lv.cibles_pays() == AVANT and lv._EQUIPE_PAYS.get() == "")

    # ── 3. les liens déjà posés : repris une fois, avec la nouvelle liste ─
    print("3. Reprise des liens")
    sig_tw = lv.signature_pays(TW)
    lv._ecrire({"liens": {
        f"{TW}:1": {"link_id": "d_tw1", "actif": True, "pays": True, "shortcode": "a"},
        f"{TW}:2": {"link_id": "d_tw2", "actif": False, "pays": True, "shortcode": "b"},
        f"{TW}:3": {"link_id": "d_tw3", "actif": True, "pays": True, "pays_cibles": sig_tw, "shortcode": "c"},
        f"{TH}:4": {"link_id": "d_th4", "actif": True, "pays": True, "shortcode": "d"},
        f"{AG}:5": {"link_id": "d_ag5", "actif": True, "pays": True, "shortcode": "e"},
    }})
    for lid in ("d_tw1", "d_tw2", "d_tw3", "d_th4", "d_ag5"):
        direct(lid)
    ECRITS.clear()
    lv.reprendre_pays(TW)
    e = lv._etat()["liens"]
    check("Twitter, posé avec l'ancienne liste : reposé, la liste notée",
          [x for x, _t in ECRITS] == ["d_tw1"] and e[f"{TW}:1"]["pays"] is True
          and e[f"{TW}:1"].get("pays_cibles") == sig_tw and not e[f"{TW}:1"].get("pays_liste_due"), (ECRITS, e[f"{TW}:1"]))
    check("Twitter, coupé : marqué à refaire (son rallumage reposera les pays), pas touché maintenant",
          e[f"{TW}:2"]["pays"] is False and e[f"{TW}:2"].get("pays_liste_due") == sig_tw)
    check("… le rallumage repose bien un lien dont « pays » n'est pas vrai",
          'poser_pays(lid, equipe) if actif and l.get("pays") is not True' in (BOT / "liens_va.py").read_text(encoding="utf-8"))
    check("Twitter, déjà à la nouvelle liste : pas touché", e[f"{TW}:3"].get("pays_cibles") == sig_tw
          and "d_tw3" not in [x for x, _t in ECRITS])
    ECRITS.clear()
    lv.reprendre_pays(TH)
    check("Threads : rien reposé, rien marqué", not ECRITS and "pays_liste_due" not in lv._etat()["liens"][f"{TH}:4"])
    lv.reprendre_pays(AG)
    e = lv._etat()["liens"]
    check("Instagram : reposé avec l'Europe", [x for x, _t in ECRITS] == ["d_ag5"]
          and not (EUROPE & vers_la_base(LIENS["d_ag5"]["geofilters"]))
          and e[f"{AG}:5"].get("pays_cibles") == lv.signature_pays(AG))
    ECRITS.clear()
    lv.reprendre_pays(TW)
    lv.reprendre_pays(AG)
    check("passage suivant : plus rien à faire", not ECRITS, ECRITS)

    # un lien posé par ce processus (créé ou rallumé après la mise en service)
    direct("d_tw9")
    lv.poser_pays("d_tw9", EQ[TW])
    d = lv._etat()
    d["liens"][f"{TW}:9"] = {"link_id": "d_tw9", "actif": True, "pays": True, "shortcode": "n"}
    lv._ecrire(d)
    ECRITS.clear()
    lv.reprendre_pays(TW)
    check("lien neuf, déjà posé avec la nouvelle liste : pas reposé, la liste notée",
          not ECRITS and lv._etat()["liens"][f"{TW}:9"].get("pays_cibles") == sig_tw, ECRITS)

    # un lien que GetMySocial refuse : ESSAIS_PAYS essais, puis « à vérifier », pas de boucle
    d = lv._etat()
    d["liens"][f"{TW}:6"] = {"link_id": "d_tw6", "actif": True, "pays": True, "shortcode": "f"}
    lv._ecrire(d)
    direct("d_tw6")
    REFUS["d_tw6"] = "refus"
    ECRITS.clear()
    for _ in range(lv.ESSAIS_PAYS + 4):
        lv.reprendre_pays(TW)
    f6 = lv._etat()["liens"][f"{TW}:6"]
    check("refusé : ESSAIS_PAYS essais puis « pays_a_verifier », jamais remis à zéro par la nouvelle liste",
          len([x for x, _t in ECRITS if x == "d_tw6"]) == lv.ESSAIS_PAYS and f6.get("pays_a_verifier") is True
          and f6.get("pays_liste_due") == sig_tw, (len(ECRITS), f6))
    check("… et il est dit à chaque passage (pas écarté en silence)", lv._rendre_essais_passagers(TW) == ["f"])
    REFUS.pop("d_tw6")

    # une panne passagère (quota, 429) ne compte pas comme un essai
    d = lv._etat()
    d["liens"][f"{TW}:10"] = {"link_id": "d_tw10", "actif": True, "pays": True, "shortcode": "q"}
    lv._ecrire(d)
    direct("d_tw10")
    REFUS["d_tw10"] = "HTTP 429 (rate-limit GetMySocial)"
    for _ in range(lv.ESSAIS_PAYS + 3):
        lv.reprendre_pays(TW)
    f10 = lv._etat()["liens"][f"{TW}:10"]
    check("panne passagère (429) : jamais « à vérifier », reprise au passage suivant",
          f10.get("pays") is False and not f10.get("pays_a_verifier") and int(f10.get("pays_essais") or 0) == 0, f10)
    REFUS.pop("d_tw10")
    lv.reprendre_pays(TW)
    f10 = lv._etat()["liens"][f"{TW}:10"]
    check("… GetMySocial revenu : posé avec la nouvelle liste", f10.get("pays") is True
          and f10.get("pays_cibles") == sig_tw and not (EUROPE & vers_la_base(LIENS["d_tw10"]["geofilters"])), f10)

    # retour en arrière : un serveur retiré de PAYS_EN_PLUS revient à la liste de base
    _vplus = dict(lv.PAYS_EN_PLUS)
    lv.PAYS_EN_PLUS.pop(AG)
    try:
        ECRITS.clear()
        lv.reprendre_pays(AG)
        f5 = lv._etat()["liens"][f"{AG}:5"]
        check("Instagram retiré de la liste : ses liens reposés, la France repart à la base",
              [x for x, _t in ECRITS] == ["d_ag5"] and EUROPE <= vers_la_base(LIENS["d_ag5"]["geofilters"])
              and f5.get("pays_cibles") == lv.signature_pays_avant(), (ECRITS, f5))
        pv._noter(AG, "5#9", link_id="p_ag9", etat="prete", actif=True, manques=[],
                  pays_cibles=",".join(sorted(AVANT | EUROPE)))
        check("… ses pages aussi (marquées « pays »)", "5#9" in pv._marquer_liste_pays(AG))
        pv._ecrire({"pages": {k: v for k, v in pv._lire()["pages"].items() if k != f"{AG}:5#9"}})
    finally:
        lv.PAYS_EN_PLUS.clear()
        lv.PAYS_EN_PLUS.update(_vplus)
    lv.reprendre_pays(AG)
    ECRITS.clear()
    lv.reprendre_pays(TH)
    check("Threads, jamais dans la liste : toujours rien reposé", not ECRITS, ECRITS)

    # règle coupée ({} dans la config) : elle ne vaut que pour les liens à venir
    d = lv._etat()
    d["liens"][f"{TW}:7"] = {"link_id": "d_tw7", "actif": True, "pays": True, "shortcode": "g"}
    lv._ecrire(d)
    CONFIG["pays"] = {}
    try:
        check("règle coupée : aucun lien marqué", lv._marquer_liste_pays(TW) == []
              and "pays_liste_due" not in lv._etat()["liens"][f"{TW}:7"])
    finally:
        CONFIG.pop("pays")

    # ── 4. les pages ─────────────────────────────────────────────────────
    print("4. Pages")
    pv._ecrire({"pages": {
        f"{TW}:1": {"link_id": "p_tw1", "etat": "prete", "actif": True, "manques": [], "essais": {"pays": 2}},
        f"{TW}:3": {"link_id": "p_tw3", "etat": "prete", "actif": True, "manques": [], "pays_cibles": sig_tw},
        f"{TW}:8": {"link_id": "p_tw8", "etat": "ratee", "actif": False, "manques": []},
        f"{AG}:5#2": {"link_id": "p_ag5", "etat": "prete", "actif": True, "manques": ["70/30"]},
    }})
    m_tw = pv._marquer_liste_pays(TW)
    m_ag = pv._marquer_liste_pays(AG)
    p = pv._lire()["pages"]
    check("page Twitter à l'ancienne liste : « pays » à refaire, son compteur remis à zéro",
          m_tw == ["1"] and p[f"{TW}:1"]["manques"] == ["pays"] and "pays" not in (p[f"{TW}:1"].get("essais") or {})
          and p[f"{TW}:1"].get("pays_liste_due") == sig_tw, (m_tw, p[f"{TW}:1"]))
    check("page déjà à la nouvelle liste, ou ratée : pas touchée",
          p[f"{TW}:3"]["manques"] == [] and p[f"{TW}:8"]["manques"] == [])
    check("page Instagram (place 2) : « pays » ajouté sans perdre le reste (70/30)",
          m_ag == ["5#2"] and p[f"{AG}:5#2"]["manques"] == ["70/30", "pays"], p[f"{AG}:5#2"])
    check("Threads : aucune page marquée", pv._marquer_liste_pays(TH) == [])
    check("remarqué au passage suivant : rien (une fois par liste)", pv._marquer_liste_pays(TW) == [])
    # la reprise (simulée) a reposé les pays de la page Twitter
    pv._noter(TW, "1", manques=[], pays=True)
    pv._noter_liste_pays(TW)
    p = pv._lire()["pages"]
    check("page reposée : la liste notée", p[f"{TW}:1"].get("pays_cibles") == sig_tw
          and not p[f"{TW}:1"].get("pays_liste_due"), p[f"{TW}:1"])
    pv._noter_liste_pays(AG)
    check("page encore à faire : rien noté", not pv._lire()["pages"][f"{AG}:5#2"].get("pays_cibles"))

    # l'enveloppe : marquer, la reprise, puis noter
    APPELS = []
    _vr = pv._reprendre_pages_sans_liste
    pv._reprendre_pages_sans_liste = lambda g: (APPELS.append(
        ("reprise", sorted(pv._lire()["pages"][f"{AG}:5#2"]["manques"]))) or {})
    try:
        pv._noter(AG, "5#2", pays_liste_due="", pays_cibles="")
        pv.reprendre_pages(AG)
    finally:
        pv._reprendre_pages_sans_liste = _vr
    check("reprendre_pages : la page est marquée AVANT la reprise", APPELS == [("reprise", ["70/30", "pays"])], APPELS)
finally:
    (lv.ETAT_FICHIER, lv.config, gms.get_link, gms.update_link, lv.lia_seule, lv.PAUSE_PAYS_S, pv.FICHIER) = SAV

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
