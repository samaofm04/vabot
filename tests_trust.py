# -*- coding: utf-8 -*-
"""tests_trust.py — les trois serveurs renommés TRUST (24/10/2026).

Propriétaire : « oui, passe en TRUST partout ». Tout ce que les bots REST
écrivent sur TRUST TWITTER, TRUST THREADS et TRUST INSTAGRAM passe par
verif_discord.api et y prend le nom TRUST ; Entretien et Va IG gardent YouLab.

Ce qui est vérifié :
  - en_trust : « YouLab Twitter » → « TRUST Twitter », « Agency VA INSTAGRAM »
    → « TRUST INSTAGRAM », « YouLab Agency » → « TRUST Instagram », « YOULAB • »
    → « TRUST • », dans les embeds, le contenu et les boutons ; le reste (les
    adresses youl4b.com, les nombres) ne bouge pas ;
  - api : un POST / PATCH vers ces trois serveurs (donné, courant, dans le
    chemin, ou par le salon connu) est renommé, multipart compris ; un GET,
    ou un autre serveur, est laissé tel quel.

Aucun appel réseau. Lancement : python tests_trust.py
"""
from __future__ import annotations

import io
import json
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import verif_discord as vd             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


msg = {"content": "<@1>", "embeds": [{"title": "✨ Bienvenue dans l’équipe YouLab Twitter !",
                                      "description": "🚪 Nouvelle arrivée sur YouLab THREADS · https://youl4b.com/x",
                                      "footer": {"text": "YOULAB • Marché US"}, "color": 123},
                                     {"title": "🚪 Arrivée sur Agency VA INSTAGRAM",
                                      "footer": {"text": "YouLab Agency • Vérification validée ✓"}}],
       "components": [{"type": 1, "components": [{"type": 2, "label": "YouLab • Menu"}]}]}
t = vd.en_trust(msg)
check("en_trust : titres, descriptions, pieds, boutons", 
      t["embeds"][0]["title"] == "✨ Bienvenue dans l’équipe TRUST Twitter !"
      and t["embeds"][0]["description"] == "🚪 Nouvelle arrivée sur TRUST THREADS · https://youl4b.com/x"
      and t["embeds"][0]["footer"]["text"] == "TRUST • Marché US"
      and t["embeds"][1]["title"] == "🚪 Arrivée sur TRUST INSTAGRAM"
      and t["embeds"][1]["footer"]["text"] == "TRUST Instagram • Vérification validée ✓"
      and t["components"][0]["components"][0]["label"] == "TRUST • Menu"
      and t["embeds"][0]["color"] == 123 and t["content"] == "<@1>", t)
check("… l'original n'est pas touché", msg["embeds"][0]["title"].endswith("YouLab Twitter !"))

envois = []
_vrai = vd._api_sans_trust
try:
    vd._api_sans_trust = lambda methode, chemin, **kw: envois.append((methode, chemin, kw)) or (200, {})
    corps = {"embeds": [{"title": "YouLab Twitter"}]}
    vd.api("POST", "/channels/c1/messages", gid=vd.TWITTER_ID, json=corps)
    check("POST vers TRUST TWITTER (serveur donné) : renommé",
          envois[-1][2]["json"]["embeds"][0]["title"] == "TRUST Twitter", envois[-1])
    vd.api("POST", "/channels/c1/messages", gid=vd.GUILD_ID, json=corps)
    check("POST vers Entretien : YouLab gardé", envois[-1][2]["json"]["embeds"][0]["title"] == "YouLab Twitter")
    with vd.sur_serveur(vd.AGENCY_IG_ID):
        vd.api("PATCH", "/channels/c2/messages/m", json={"embeds": [{"footer": {"text": "Agency VA INSTAGRAM • Départs"}}]})
    check("PATCH sous le serveur courant (Agency) : renommé",
          envois[-1][2]["json"]["embeds"][0]["footer"]["text"] == "TRUST INSTAGRAM • Départs", envois[-1])
    vd._SALON_SERVEUR["333"] = vd.THREADS_ID
    vd.api("POST", "/channels/333/messages", data={"payload_json": json.dumps({"content": "YouLab THREADS"})},
           files={"files[0]": ("a.png", b"x", "image/png")})
    check("multipart vers un salon connu de Threads : payload_json renommé",
          json.loads(envois[-1][2]["data"]["payload_json"])["content"] == "TRUST THREADS", envois[-1])
    vd.api("POST", f"/guilds/{vd.TWITTER_ID}/channels", json={"name": "YouLab-annonces"})
    check("le serveur dans le chemin : renommé", envois[-1][2]["json"]["name"] == "TRUST-annonces")
    vd.api("GET", "/channels/c1/messages", gid=vd.TWITTER_ID, params={"q": "YouLab"})
    check("un GET n'est pas touché", envois[-1][2]["params"] == {"q": "YouLab"})
    vd.api("POST", "/channels/inconnu/messages", json=corps)
    check("salon inconnu, sans serveur : laissé tel quel",
          envois[-1][2]["json"]["embeds"][0]["title"] == "YouLab Twitter")
finally:
    vd._api_sans_trust = _vrai

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
