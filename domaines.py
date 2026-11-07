"""domaines.py — quel domaine sert quoi : youl4b.com ou trust-ofm.com.

Propriétaire, 07/11/2026 : « trust-ofm.com … les trucs pour les stats et
tout, mets-les dans ce domaine stp, que les VA ils voient, tu vois
affiliation, tracking des liens, pour les trucs liés à TRUST Instagram,
Twitter et Threads ».

- Les adresses que le bot donne aux VA de TRUST TWITTER, TRUST INSTAGRAM et
  TRUST THREADS (page perso « 📈 Mes stats », vérification, espace
  d'affiliation) partent sur SITE_TRUST. Une seule table décide, ici : deux
  listes de serveurs auraient fini par ne plus dire la même chose.
- Tout le reste (dashboard, /trust/liens des managers, les autres serveurs)
  reste sur SITE.
- C'est la MÊME application des deux côtés : les liens youl4b.com déjà
  distribués continuent de marcher. Sur trust-ofm.com, seules les pages des
  VA répondent (garde) : la connexion du dashboard n'y existe pas.
"""
from __future__ import annotations

from typing import Any

SITE = "https://youl4b.com"
SITE_TRUST = "https://trust-ofm.com"

TRUST_TWITTER = "1445108485090971710"
TRUST_INSTAGRAM = "1488331963575177247"
TRUST_THREADS = "1498948161039896586"
SERVEURS_TRUST = frozenset({TRUST_TWITTER, TRUST_INSTAGRAM, TRUST_THREADS})

HOTES_TRUST = frozenset({"trust-ofm.com", "www.trust-ofm.com"})

#: Ce que trust-ofm.com sert : les pages ouvertes par un lien du bot, et ce
#: qu'elles chargent. Préfixes de chemin. Le reste rend une page neutre.
CHEMINS_TRUST = (
    "/mes-stats",                 # stats_va : la page perso du VA
    "/verif/",                    # verif_discord : la vérification (GET + POST)
    "/affiliation/mon-espace",    # affiliation_site (VPS) : l'espace du parrain
    "/affiliation/affiche.png",   # l'affiche de cet espace
    "/static/",
    "/favicon.svg", "/favicon.ico",
    "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
)

PAGE_NEUTRE = ("<!doctype html><html lang=fr><meta charset=utf-8>"
               "<meta name=viewport content='width=device-width,initial-scale=1'>"
               "<meta name=robots content=noindex><title>TRUST</title>"
               "<body style='margin:0;min-height:100vh;display:flex;align-items:center;"
               "justify-content:center;font-family:system-ui,sans-serif;background:#0e0e10;"
               "color:#a1a1aa;padding:16px;text-align:center'>"
               "<p>Page introuvable. Ouvre ton lien personnel depuis Discord.</p></body></html>")


def site(gid: Any = None) -> str:
    """Le domaine des adresses données sur ce serveur Discord."""
    return SITE_TRUST if str(gid or "") in SERVEURS_TRUST else SITE


def hote_trust(hote: Any) -> bool:
    """La requête vise-t-elle trust-ofm.com ? (port et casse ignorés)"""
    return str(hote or "").split(":", 1)[0].strip().lower() in HOTES_TRUST


def chemin_trust(chemin: Any) -> bool:
    """Ce chemin est-il servi sur trust-ofm.com ? Un préfixe en « / » couvre
    tout ce qu'il y a dessous, les autres valent le chemin exact."""
    c = str(chemin or "")
    return any(c == p or (p.endswith("/") and c.startswith(p)) for p in CHEMINS_TRUST)


def installer(app) -> None:
    """La garde de trust-ofm.com : hors CHEMINS_TRUST, une page neutre en
    404. Sans elle, trust-ofm.com/ ouvrait la connexion du dashboard."""
    from flask import Response, request

    @app.before_request
    def _garde_trust():
        if not hote_trust(request.host) or chemin_trust(request.path):
            return None
        r = Response(PAGE_NEUTRE, status=404, mimetype="text/html")
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Robots-Tag"] = "noindex, nofollow"
        return r
