"""tests_trust_agency_anciens.py — les anciens messages de TRUST Agency au nom
TRUST Agency (trust_agency_anciens). Discord simulé, état temporaire.

    python tests_trust_agency_anciens.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import verif_discord as vrai  # noqa: E402  (la vraie table de noms)
import trust_agency_anciens as taa  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="taa_"))
taa.FICHIER = TMP / "trust_agency_anciens.json"
taa.PAUSE_S = 0
OK, KO = [], []
BOT, AUTRE = "111", "222"


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  ok  " if cond else "  KO  ") + nom + ("" if cond else f"  — {detail}"))


def msg(mid, auteur=BOT, **kw):
    return dict({"id": mid, "author": {"id": auteur}, "content": "", "embeds": [], "components": []}, **kw)


SALONS = {"10": [msg("1", content="Bienvenue chez YouLab"),
                 msg("2", embeds=[{"type": "rich", "title": "⏳ En attente d'un manager",
                                   "footer": {"text": "YouLab • Vérification — ✅ accepté par vectorofm",
                                              "proxy_icon_url": "x"},
                                   "thumbnail": {"url": "https://cdn/a.png", "proxy_url": "p", "width": 8},
                                   "fields": [{"name": "Membre", "value": "@Toky", "inline": True}]}]),
                 msg("3", content="déjà TRUST Agency"),
                 msg("4", auteur=AUTRE, content="YouLab, écrit par un humain")],
          "20": [msg("5", embeds=[{"type": "link", "title": "youl4b.com", "description": "YouLab"}]),
                 msg("6", content="dans l'agence YouLab")]}


class Discord:
    def __init__(self):
        self.patchs = {}
        self.refus = set()
        self.illisible = set()

    def api(self, methode, chemin, **kw):
        if methode == "GET" and chemin == f"/guilds/{taa.GID}/channels":
            return 200, [{"id": "10", "type": 0}, {"id": "20", "type": 5}, {"id": "30", "type": 2}]
        if methode == "GET" and chemin.startswith("/channels/"):
            sid = chemin.split("/")[2]
            return (403, {}) if sid in self.illisible else (200, list(SALONS.get(sid, [])))
        if methode == "PATCH":
            mid = chemin.rsplit("/", 1)[1]
            if mid in self.refus:
                return 403, {}
            self.patchs[mid] = kw["json"]
            return 200, {}
        return 404, {}


D = Discord()
sys.modules["verif_discord"] = types.SimpleNamespace(
    api=lambda *a, **k: D.api(*a, **k), en_trust=vrai.en_trust, table_marque=vrai.table_marque,
    bot_du_serveur=lambda gid=None: {"app_id": BOT})

try:
    print("trust_agency_anciens")
    D.refus = {"6"}
    b = taa.passe()
    check("texte : « YouLab » devient « TRUST Agency »", D.patchs.get("1") == {"content": "Bienvenue chez TRUST Agency"},
          D.patchs.get("1"))
    e = (D.patchs.get("2") or {}).get("embeds", [{}])[0]
    check("carte : le pied « YouLab • Vérification » devient « TRUST Agency • Vérification »",
          e.get("footer") == {"text": "TRUST Agency • Vérification — ✅ accepté par vectorofm"}, e)
    check("carte : le reste est renvoyé tel quel, sans les champs calculés par Discord",
          e.get("title") == "⏳ En attente d'un manager" and e.get("thumbnail") == {"url": "https://cdn/a.png"}
          and e.get("fields") == [{"name": "Membre", "value": "@Toky", "inline": True}] and "type" not in e, e)
    check("un message sans l'ancien nom n'est pas touché", "3" not in D.patchs)
    check("un message d'un autre auteur n'est pas touché", "4" not in D.patchs)
    check("un aperçu de lien n'est pas renvoyé, et c'est compté",
          "5" not in D.patchs and "aperçu" in taa._etat()["echecs"].get("5", ""), taa._etat()["echecs"])
    check("un refus de Discord est compté", taa._etat()["echecs"].get("6") == "HTTP 403" and b["echecs"] == 2, b)
    check("passe finie : notée", bool(taa._etat().get("termine")) and b["corriges"] == 2, b)
    n = len(D.patchs)
    check("passe finie : elle ne repart plus", taa.passe().get("deja") and len(D.patchs) == n)

    # un salon illisible : la passe n'est pas close, la suivante reprend sans refaire
    for f in TMP.iterdir():
        f.unlink()
    D2 = D.__class__()
    D2.illisible = {"20"}
    D = D2
    b = taa.passe()
    check("salon illisible : passe non close", not taa._etat().get("termine") and b["salons_illisibles"] == 1, b)
    D.illisible = set()
    p1 = dict(D.patchs)
    D.patchs = {}
    taa.passe()
    check("reprise : les messages déjà corrigés ne sont pas refaits",
          "1" in p1 and "1" not in D.patchs and "6" in D.patchs, (sorted(p1), sorted(D.patchs)))
    check("« dans l'agence YouLab » devient « chez TRUST Agency » (table de verif_discord)",
          D.patchs.get("6") == {"content": "chez TRUST Agency"}, D.patchs.get("6"))
    src = (ICI / "web_upload.py").read_text(encoding="utf-8")
    check("web_upload : la passe démarre sur la machine de production seulement",
          '_machine_proprietaire("trust-agency-anciens")' in src and "_taa_boot.demarrer()" in src)
    check("écritures par safe_json seulement",
          "write_text" not in (ICI / "trust_agency_anciens.py").read_text(encoding="utf-8"))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{len(OK)} ok, {len(KO)} échec(s)")
sys.exit(1 if KO else 0)
