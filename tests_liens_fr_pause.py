"""Liens VA FR : une GetMySocial en pause n'est pas « pas de lien de base ».

06/10/2026, 8h06 : un manager clique « Générer le lien » pour un VA Lola, et
le bot répond « ❌ pas de lien de base « lola_bby » (Lola 1) dans l'équipe
GetMySocial VA IG DISCORD ». Le lien de base existait (quatre liens Lola en
avaient déjà été copiés) : la quota du jour était épuisée jusqu'à 9h33, la
liste de l'équipe revenait vide, et elle était gardée dix minutes comme telle.

Vérifié ici, sans réseau ni vrai data/ (GetMySocial simulé, registre dans un
dossier temporaire) : la vraie raison est dite, avec l'heure de Paris ; rien
n'est créé ; un échec n'est jamais gardé ; une vraie absence reste dite.

Lancer depuis la racine du dépôt : python tests_liens_fr_pause.py
"""
from __future__ import annotations

import io
import pathlib
import shutil
import sys
import tempfile
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms                              # noqa: E402  (le vrai : heure_paris)

# ------------------------------------------------ faux GetMySocial ----------
ETAT_GMS = {"pause": 0, "pause_ecriture": 0, "budget": True, "liste": "ok", "appels": []}
LIENS_EQUIPE = [{"id": "lnk_base_lola", "shortcode": "lola_bby", "display_name": "Lola 1"},
                {"id": "lnk_base_amelia", "shortcode": "amelia_bby", "display_name": "Amelia 1"}]


def _liste(team, force_refresh=False):
    ETAT_GMS["appels"].append(("list_links_team", team))
    if ETAT_GMS["pause"]:
        return {"ok": False, "error": "Quota GetMySocial epuise — reprise vers 09:33 (87 min)"}
    if ETAT_GMS["liste"] == "panne":
        return {"ok": False, "error": "reseau: timeout"}
    return {"ok": True, "links": [dict(l) for l in LIENS_EQUIPE]}


def _outil(nom, args=None):
    ETAT_GMS["appels"].append((nom, args))
    return {"ok": False, "error": "inattendu dans ce test"}


faux = types.ModuleType("gms")
faux.list_links_team = _liste
faux._call_tool = _outil
faux.pause_restante = lambda genre="lecture": (ETAT_GMS["pause_ecriture"] if genre == "ecriture"
                                               else ETAT_GMS["pause"])
faux.budget_ok = lambda tag=None: ETAT_GMS["budget"]
faux.heure_paris = gms.heure_paris
faux.PUBLIC_LINK_DOMAIN = "https://getmysocial.com"
faux.enable_link = lambda lid: _outil("enable_link", lid)
faux.disable_link = lambda lid: _outil("disable_link", lid)
sys.modules["gms"] = faux
faux_mp = types.ModuleType("mypuls")
faux_mp.__getattr__ = lambda nom: (_ for _ in ()).throw(AssertionError(f"MyPuls appelé : {nom}"))
sys.modules["mypuls"] = faux_mp

import liens_fr                         # noqa: E402
import safe_json                        # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="liens_fr_pause_"))
_SAUVE = (liens_fr.ETAT, dict(liens_fr._CACHE_LIENS))
VA, PSEUDO, MANAGER = 1234567890123, "adh", 42


def bac(pause=0, budget=True, liste="ok", pause_ecriture=0):
    liens_fr.ETAT = TMP / f"liens_va_fr_{len(OKS) + len(FAILS)}.json"
    liens_fr._CACHE_LIENS.update(t=0.0, liens=[])
    ETAT_GMS.update(pause=pause, budget=budget, liste=liste, pause_ecriture=pause_ecriture)
    ETAT_GMS["appels"].clear()


try:
    print("\n— 1. l'heure de reprise est celle de Paris")
    # 07:33 UTC le 06/10/2026 (heure d'été) = 09:33 à Paris
    ts = 1791271980.0
    check("heure_paris : 07:33 UTC se dit 09:33", gms.heure_paris(ts) == "09:33",
          gms.heure_paris(ts))
    check("etat_quota et les refus de GetMySocial passent par elle",
          "heure_paris(time.time() + reste)" in (BOT / "gms.py").read_text(encoding="utf-8")
          and (BOT / "gms.py").read_text(encoding="utf-8").count(
              "% (heure_paris(time.time() + _reste), _reste // 60)") == 2)

    print("\n— 2. le cas du 06/10 : quota épuisée, lien de base bien là")
    bac(pause=5220)                 # 87 min
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    check("pas de « pas de lien de base » : la vraie raison",
          not r["ok"] and "lien de base" not in r["erreur"]
          and "GetMySocial est en pause" in r["erreur"], r)
    check("… avec l'heure de reprise à Paris (pas celle du serveur)",
          gms.heure_paris(time.time() + 5220).replace(":", "h") in r["erreur"], r["erreur"])
    check("… et quoi faire : rien n'a été créé, à refaire après l'heure dite",
          "rien n'a été créé" in r["erreur"] and "à refaire après" in r["erreur"]
          and r.get("reessayer") is True)
    check("… sans un seul appel à GetMySocial pendant la pause", ETAT_GMS["appels"] == [],
          ETAT_GMS["appels"])
    check("… et rien d'écrit au registre", not liens_fr.ETAT.exists())

    print("\n— 3. les écritures en pause, les lectures libres")
    bac(pause_ecriture=3600)
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    check("les créations de liens en pause : dit AVANT tout tracking MyPuls",
          not r["ok"] and "créations de liens GetMySocial sont en pause" in r["erreur"]
          and ETAT_GMS["appels"] == [], r)
    bac(budget=False)
    try:
        r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    except RuntimeError as e:            # le faux GetMySocial ne sait pas lire la page
        r = {"ok": False, "erreur": str(e)}
    check("le budget des LECTURES de la principale n'arrête plus la génération "
          "(elle va jusqu'à lire le lien de base)",
          "paie" not in str(r.get("erreur"))
          and any(a[0] == "get_link" for a in ETAT_GMS["appels"]), (r, ETAT_GMS["appels"]))

    print("\n— 4. GetMySocial muet sans pause (réseau)")
    bac(liste="panne")
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    check("liste illisible : « GetMySocial n'a pas rendu la liste », pas « pas de lien de base »",
          not r["ok"] and "n'a pas rendu la liste" in r["erreur"]
          and "lien de base" not in r["erreur"] and "timeout" in r["erreur"], r)
    check("… et rien de copié", not any(a[0] in ("duplicate_link", "copy_link", "create_link")
                                         for a in ETAT_GMS["appels"]), ETAT_GMS["appels"])

    print("\n— 5. un échec n'est jamais gardé pour dix minutes")
    bac(liste="panne")
    check("liste illisible, sans exigence : vide, comme avant (aligner ne bascule rien)",
          liens_fr._liens_equipe(True) == [])
    check("… mais pas mise en mémoire", liens_fr._CACHE_LIENS["t"] == 0.0)
    try:
        liens_fr._liens_equipe(True, strict=True)
        leve = False
    except liens_fr.GmsIndisponible:
        leve = True
    check("exigée, elle lève GmsIndisponible", leve)
    ETAT_GMS["liste"] = "ok"
    check("GetMySocial revenu : le lien de base se retrouve aussitôt",
          liens_fr.lien_de_base("lola") == "lnk_base_lola")
    bac(liste="panne")
    try:
        liens_fr.lien_de_base("lola")
        leve = False
    except liens_fr.GmsIndisponible:
        leve = True
    check("lien_de_base sur une liste illisible : GmsIndisponible, pas \"\"", leve)

    print("\n— 6. une vraie absence reste dite")
    bac()
    sauve = list(LIENS_EQUIPE)
    LIENS_EQUIPE[:] = [l for l in LIENS_EQUIPE if l["shortcode"] != "lola_bby"]
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    LIENS_EQUIPE[:] = sauve
    check("liste lue, lola_bby absent : « pas de lien de base », comme avant",
          not r["ok"] and "pas de lien de base « lola_bby »" in r["erreur"], r)

    print("\n— 7. un lien déjà fait est rendu même pendant la pause")
    bac(pause=5220)
    safe_json.write(liens_fr.ETAT, {"liens": {f"{VA}:lola": {
        "link_id": "lnk_x", "public_url": "https://getmysocial.com/lolaglow",
        "display_name": "Lola VA 28 @adh", "plateformes": ["of"],
        "trackings": {"of": "https://onlyfans.com/itsslolaaaaa/c90"}}}}, indent=1)
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    check("le lien du registre, sans GetMySocial", r["ok"] and r.get("deja")
          and r.get("public_url") == "https://getmysocial.com/lolaglow", r)
    check("… sans « réparation impossible » pour rien, ni appel à GetMySocial",
          not r.get("soucis") and ETAT_GMS["appels"] == [], (r.get("soucis"), ETAT_GMS["appels"]))
    # un lien incomplet, lui, dit pourquoi il n'a pas pu être réparé
    safe_json.write(liens_fr.ETAT, {"liens": {f"{VA}:lola": {
        "link_id": "lnk_x", "public_url": "https://getmysocial.com/lolaglow",
        "display_name": "Lola VA 28 @adh", "plateformes": ["of"], "trackings": {},
        "boutons_a_jour": False}}}, indent=1)
    sys.modules["mypuls"] = types.SimpleNamespace(
        api_tracking_links=lambda **k: [], api_get=lambda *a, **k: {"ok": False, "error": "x"})
    liens_fr._relire_api = lambda nom, cid: ("https://onlyfans.com/itsslolaaaaa/c91", None)
    r = liens_fr.generer(VA, PSEUDO, "lola", par=MANAGER)
    check("lien incomplet pendant la pause : rendu, et le souci dit la vraie raison",
          r["ok"] and r.get("deja") and any("GetMySocial" in x or "Quota" in x
                                            for x in r.get("soucis") or []), r.get("soucis"))
finally:
    liens_fr.ETAT = _SAUVE[0]
    liens_fr._CACHE_LIENS.clear()
    liens_fr._CACHE_LIENS.update(_SAUVE[1])
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
