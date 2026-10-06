"""GetMySocial : la quota est PAR CLÉ, et une clé épuisée passe la main.

06/10/2026. La doc de l'API v3 : « Per-API-key, per-tier, rolling window »,
10 000 lectures par jour et par clé, les écritures à part. Le relevé de la
semaine du 29/09 : la clé principale à ~10 250 appels par jour, les quatre
« dash » à ~1 860 chacune. La pause était pourtant UNIQUE : la principale
épuisée, tout s'arrêtait jusqu'à 9h33, écritures comprises (« Générer le
lien » d'un VA Lola a échoué à 8h06). Et ~1 830 appels list_recent_visitors
par jour partaient pour rien : identifiant de lien vide (400) ou lien
supprimé (404 link_not_found).

Vérifié ici sans réseau (réponses simulées clé par clé) ni vrai data/.
Lancer depuis la racine du dépôt : python tests_gms_cles.py
"""
from __future__ import annotations

import io
import pathlib
import shutil
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms                              # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


MAIN, D1, D2 = "gms_live_principale_aaaaaaaa", "gms_live_dash1_bbbbbbbb", "gms_live_dash2_cccccccc"
JOUR = ("Error 429 (rate_limit_exceeded): RATE_LIMITED: retry after 7836s. Do not retry "
        "before then. Requests remaining this minute: 117, today: 0.")
APPELS = []                    # (outil, clé, args)
EPUISEES = set()               # (clé, genre) dont la journée est finie chez « GetMySocial »
REPONSES = {}                  # outil -> réponse forcée


def faux_brut(tool_name, args=None, _retry=True, _429=0):
    cle = gms._effective_key()
    APPELS.append((tool_name, cle, dict(args or {})))
    genre = gms.genre_outil(tool_name)
    if gms.pause_cle(cle, genre):
        return {"ok": False, "error": "Quota GetMySocial epuise — reprise vers 09:33 (120 min)"}
    if (cle, genre) in EPUISEES:
        gms._noter_refus(JOUR, cle, genre)
        return {"ok": False, "error": JOUR}
    if tool_name in REPONSES:
        return REPONSES[tool_name]
    return {"ok": True, "data": {"cle": cle}}


TMP = pathlib.Path(tempfile.mkdtemp(prefix="gms_cles_"))
_SAUVE = {k: getattr(gms, k) for k in ("get_api_key", "get_dash_keys", "_call_tool_brut",
                                       "_BUDGET_FICHIER")}


def remise():
    APPELS.clear()
    EPUISEES.clear()
    REPONSES.clear()
    gms._PAUSES.clear()
    gms._SANTE.clear()
    gms._LIENS_SUPPRIMES.clear()
    gms._BUDGET.update({"heures": {}, "plafond": None, "lu": True, "ecrit": 0.0, "depuis": None})
    gms._DIT_TROP.clear()


try:
    gms.get_api_key = lambda: MAIN
    gms.get_dash_keys = lambda: [D1, D2]
    gms._call_tool_brut = faux_brut
    gms._BUDGET_FICHIER = TMP / "gms_budget.json"

    print("\n— 1. lectures et écritures, chacune son panier")
    check("list_*, get_*, _ping sont des lectures ; le reste, des écritures",
          gms.genre_outil("list_recent_visitors") == "lecture"
          and gms.genre_outil("get_analytics_overview") == "lecture"
          and gms.genre_outil("_ping") == "lecture"
          and gms.genre_outil("update_link") == "ecriture"
          and gms.genre_outil("duplicate_link") == "ecriture")

    print("\n— 2. le cas du 06/10 : la principale épuisée en lecture")
    remise()
    EPUISEES.add((MAIN, "lecture"))
    r = gms._call_tool("list_links", {"limit": 100})
    check("la lecture passe quand même, sur une clé du pool",
          r["ok"] and r["data"]["cle"] in (D1, D2), r)
    check("… après UN seul refus de la principale", [a[1] for a in APPELS][0] == MAIN
          and len(APPELS) == 2, APPELS)
    check("la principale est en pause (lectures), les autres non",
          gms.pause_cle(MAIN) > 0 and not gms.pause_cle(D1) and not gms.pause_cle(D2))
    check("pause_restante : 0 tant qu'une clé est libre (le podium, les liens FR continuent)",
          gms.pause_restante() == 0)
    APPELS.clear()
    r = gms._call_tool("get_analytics_overview", {"timeframe": "today"})
    check("les lectures suivantes vont directement au pool, sans retoucher la principale",
          r["ok"] and all(a[1] != MAIN for a in APPELS), APPELS)
    APPELS.clear()
    r = gms._call_tool("update_link", {"link_id": "lnk_abc"})
    check("une ÉCRITURE part toujours de la principale : sa journée d'écritures n'est pas finie",
          r["ok"] and APPELS[0][1] == MAIN, APPELS)
    check("les écritures ne sont pas en pause", gms.pause_restante("ecriture") == 0)

    print("\n— 3. toutes les clés épuisées : là, on attend")
    EPUISEES.update({(D1, "lecture"), (D2, "lecture")})
    APPELS.clear()
    r = gms._call_tool("list_links", {})
    r2 = gms._call_tool("list_links", {})
    check("la première essaie chaque clé libre une fois, puis renonce",
          not r["ok"] and sorted(a[1] for a in APPELS[:2]) == sorted([D1, D2]), APPELS)
    check("la suivante n'ouvre même pas la connexion", not r2["ok"] and len(APPELS) == 2
          and "Quota GetMySocial epuise" in r2["error"], (r2, APPELS))
    check("pause_restante : le temps avant qu'une clé revienne", pause := gms.pause_restante(),
          pause)
    check("… et l'état le dit, clé par clé, sans montrer les clés",
          len(gms.etat_quota()["cles"]) == 3
          and all("…" in c["cle"] and c["lecture_s"] > 0 for c in gms.etat_quota()["cles"]))
    gms._quota_libere(D2, "lecture")
    EPUISEES.discard((D2, "lecture"))
    APPELS.clear()
    r = gms._call_tool("list_links", {})
    check("une clé revenue sert aussitôt", r["ok"] and APPELS[-1][1] == D2, APPELS)

    print("\n— 3b. une réponse déjà en vol ne rouvre pas une pause posée après son départ")
    remise()
    parti = time.time() - 5
    gms._noter_refus(JOUR, D1, "lecture")
    gms._quota_libere(D1, "lecture", parti)
    check("succès parti avant la pause : la pause tient", gms.pause_cle(D1) > 0)
    gms._quota_libere(D1, "lecture", time.time() + 1)
    check("succès parti après : la pause est levée", gms.pause_cle(D1) == 0)

    print("\n— 4. le travail de fond ne prend pas la journée de la paie")
    remise()
    with gms.api_tag("widget-vas"):
        gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_a"], "limit": 100})
        gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_b"], "limit": 100})
    check("le widget des VA (fond) lit sur le pool, en alternant les clés",
          [a[1] for a in APPELS] in ([D1, D2], [D2, D1]), APPELS)
    APPELS.clear()
    with gms.api_tag("podium"):
        gms._call_tool("get_analytics_overview", {"link_ids": ["lnk_a"]})
    check("la paie (podium) lit sur la principale", APPELS[-1][1] == MAIN, APPELS)
    APPELS.clear()
    with gms.api_tag("dashboard"), gms.use_key(D2):
        gms._call_tool("get_analytics_overview", {"link_ids": ["lnk_a"]})
    check("la clé choisie par l'appelant (use_key) passe d'abord", APPELS[-1][1] == D2, APPELS)
    APPELS.clear()
    with gms.use_key(D1):
        gms._call_tool("update_link", {"link_id": "lnk_a"})
    check("… sauf pour une écriture, toujours sur la principale", APPELS[-1][1] == MAIN, APPELS)

    print("\n— 5. le budget de la principale : la paie garde sa réserve, le reste va au pool")
    remise()
    gms._BUDGET.update({"plafond": 10000, "heures": {gms._heure_cle(): 9990}})
    with gms.api_tag("podium"):
        gms._call_tool("get_analytics_overview", {"timeframe": "today"})
    check("au plus juste : la paie passe encore sur la principale", APPELS[-1][1] == MAIN)
    gms._call_tool("get_analytics_overview", {"timeframe": "today"})
    check("une lecture ordinaire part sur le pool au lieu d'être refusée",
          APPELS[-1][1] in (D1, D2), APPELS)
    APPELS.clear()
    r = gms._call_tool("update_link", {"link_id": "lnk_a"})
    check("une écriture, elle, passe : ses paniers sont à part du budget des lectures",
          r["ok"] and APPELS[-1][1] == MAIN, r)
    check("seuls les appels de la principale comptent dans son budget",
          gms._BUDGET["heures"][gms._heure_cle()] == 9990)
    gms._api_note(200, "ecriture")
    check("… et seulement ses LECTURES", gms._BUDGET["heures"][gms._heure_cle()] == 9990)
    gms._api_note(200)
    with gms.use_key(D1):
        gms._api_note(200)
    check("… un appel du pool n'y entre pas",
          gms._BUDGET["heures"][gms._heure_cle()] == 9991)
    check("un refus « today: 0 » d'une clé du pool n'apprend rien à la principale",
          (gms._noter_refus(JOUR, D1, "lecture") or True)
          and gms._BUDGET["plafond"] == 10000)

    print("\n— 6. les liens d'un appel : jamais vides, jamais supprimés")
    remise()
    r = gms._call_tool("list_recent_visitors", {"link_ids": [], "limit": 100})
    check("liste vide : pas d'appel (ce serait « tout le compte »)",
          not r["ok"] and not APPELS and "aucun lien" in r["error"], r)
    r = gms._call_tool("list_recent_visitors", {"link_ids": ["", " ", None], "limit": 100})
    check("identifiants vides : pas d'appel (c'était un 400 invalid_request)",
          not r["ok"] and not APPELS, r)
    gms._call_tool("list_recent_visitors", {"link_ids": ["", "lnk_a", "lnk_a",
                                                          "6a0e5415a5835045d4a1a4d2"]})
    check("les vides sont retirés, les doublons aussi, le préfixe ajouté",
          APPELS[-1][2]["link_ids"] == ["lnk_a", "lnk_6a0e5415a5835045d4a1a4d2"], APPELS[-1])
    gms._call_tool("get_link", {"link_id": "lnk_z", "team_id": "tm_x"})
    check("un appel à un seul lien garde sa forme (link_id)",
          APPELS[-1][2] == {"link_id": "lnk_z", "team_id": "tm_x"}, APPELS[-1])
    # plus de 20 liens : GetMySocial refuse (400, vérifié le 06/10), on n'appelle pas
    n = len(APPELS)
    with gms.api_tag("widget-vas"):
        r = gms._call_tool("list_recent_visitors",
                           {"link_ids": [f"lnk_{i}" for i in range(21)], "limit": 100})
    check("21 liens dans une statistique : pas d'appel (c'étaient les ~1 395 400 par jour)",
          not r["ok"] and len(APPELS) == n and "20" in r["error"], r)
    with gms.api_tag("widget-vas"):
        r = gms._call_tool("list_recent_visitors",
                           {"link_ids": [f"lnk_{i}" for i in range(20)], "limit": 100})
    check("20 liens passent", r["ok"] and len(APPELS) == n + 1)
    with gms.api_tag("widget-vas"):
        gms._call_tool("assign_links_to_group", {"link_ids": [f"lnk_{i}" for i in range(30)]})
    check("hors statistiques, pas de limite à 20 (une écriture de groupe)",
          len(APPELS[-1][2]["link_ids"]) == 30)
    # un lien supprimé, nommé dans le refus
    REPONSES["list_recent_visitors"] = {"ok": False, "error":
                                        "Error 404 (link_not_found): Link lnk_mort not found"}
    gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_vif", "lnk_mort"]})
    REPONSES.clear()
    n = len(APPELS)
    with gms.api_tag("widget-vas"):
        gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_vif", "lnk_mort"]})
    check("travail de fond : le lien supprimé est retiré, les autres lus",
          len(APPELS) == n + 1 and APPELS[-1][2]["link_ids"] == ["lnk_vif"], APPELS[-1])
    with gms.api_tag("podium"):
        r = gms._call_tool("get_analytics_overview", {"link_ids": ["lnk_vif", "lnk_mort"]})
    check("paie : pas de total calculé sans un lien — refusé, et le lien est nommé",
          not r["ok"] and "lnk_mort" in r["error"] and len(APPELS) == n + 1, r)
    # un lot refusé sans nommer le lien
    REPONSES["list_recent_visitors"] = {"ok": False, "error": "Error 404 (link_not_found)"}
    gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_p", "lnk_q"]})
    REPONSES.clear()
    n = len(APPELS)
    r = gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_q", "lnk_p"]})
    check("un lot refusé sans nom n'est pas redemandé (dans n'importe quel ordre)",
          not r["ok"] and len(APPELS) == n and "déjà refusé" in r["error"], r)
    gms._call_tool("list_recent_visitors", {"link_ids": ["lnk_p"]})
    check("… mais chacun de ses liens, seul, l'est encore", len(APPELS) == n + 1)
    REPONSES["list_recent_visitors"] = {"ok": False, "error": "HTTP 404 : session expirée"}
    gms._call_tool("list_recent_visitors", {"link_id": "lnk_s"})
    REPONSES.clear()
    n = len(APPELS)
    gms._call_tool("list_recent_visitors", {"link_id": "lnk_s"})
    check("un 404 qui n'est pas link_not_found (session MCP) ne condamne aucun lien",
          len(APPELS) == n + 1)
    # une copie toute neuve peut répondre link_not_found une seconde : hors
    # statistiques, rien n'est oublié (la génération du lien d'un VA en dépend)
    REPONSES["get_link"] = {"ok": False, "error": "Error 404 (link_not_found): lnk_neuf"}
    gms._call_tool("get_link", {"link_id": "lnk_neuf"})
    REPONSES.clear()
    n = len(APPELS)
    r = gms._call_tool("update_link", {"link_id": "lnk_neuf", "buttons": []})
    check("hors statistiques, un link_not_found n'oublie aucun lien (copie toute neuve)",
          r["ok"] and len(APPELS) == n + 1, r)
    gms._LIENS_SUPPRIMES["lnk_vieux"] = time.time() - 1
    gms._call_tool("list_recent_visitors", {"link_id": "lnk_vieux"})
    check("au bout de six heures, un lien est redemandé", APPELS[-1][2].get("link_id") == "lnk_vieux")

    print("\n— 7. la liste des liens d'une équipe (REST) suit les mêmes règles")
    remise()
    import requests as _rq

    class R:
        def __init__(self, code, js=None, texte=""):
            self.status_code, self._js, self.text = code, js or {}, texte

        def json(self):
            return self._js

    vus = []

    def faux_get(url, headers=None, timeout=None):
        cle = headers["Authorization"].split()[-1]
        vus.append(cle)
        if cle == MAIN:
            return R(429, texte=JOUR)
        return R(200, {"data": [{"id": "lnk_1"}], "has_more": False})

    vrai_get = _rq.get
    _rq.get = faux_get
    try:
        gms._LINKS_TEAM_CACHE.clear()
        r = gms.list_links_team("tm_x", force_refresh=True)
        check("la principale épuisée : la même page est relue sur une clé du pool",
              r["ok"] and r["links"] == [{"id": "lnk_1"}] and vus[0] == MAIN
              and vus[1] in (D1, D2), (r, vus))
        vus.clear()
        r = gms.list_links_team("tm_x", force_refresh=True)
        check("la suivante va directement au pool", r["ok"] and MAIN not in vus, vus)
    finally:
        _rq.get = vrai_get
        gms._LINKS_TEAM_CACHE.clear()

    print("\n— 8. le compteur d'avant (toutes clés mêlées) n'est pas relu")
    gms._BUDGET_FICHIER.write_text('{"heures": {"%s": 17000}, "plafond": 13}' % gms._heure_cle(),
                                   encoding="utf-8")
    gms._BUDGET.update({"heures": {}, "plafond": None, "lu": False, "ecrit": 0.0})
    check("un fichier sans version 2 est ignoré (17 000 appels de cinq clés ne sont pas "
          "ceux de la principale)", gms.appels_24h() == 0 and gms.budget()["plafond"] is None)
    gms._api_note(200)
    gms._budget_ecrire(force=True)
    check("le nouveau fichier porte sa version et son départ",
          '"version": 2' in gms._BUDGET_FICHIER.read_text(encoding="utf-8")
          and gms._BUDGET["depuis"])
    gms._BUDGET["heures"] = {gms._heure_cle(): 6000}
    gms._budget_noter_plafond(gms.appels_24h())
    check("compteur de moins de 24 h : un refus n'apprend AUCUN plafond (il ignore la veille)",
          gms.budget()["plafond"] is None)
    gms._BUDGET["depuis"] = time.time() - 86400 - 60
    gms._budget_noter_plafond(gms.appels_24h())
    check("fenêtre couverte : le plafond s'apprend", gms.budget()["plafond"] == 6000)
    gms._BUDGET["depuis"] = None
finally:
    for k, v in _SAUVE.items():
        setattr(gms, k, v)
    gms._PAUSES.clear()
    gms._SANTE.clear()
    gms._LIENS_SUPPRIMES.clear()
    gms._BUDGET.update({"heures": {}, "plafond": None, "lu": False, "ecrit": 0.0})
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
