"""domaines.py — quel domaine sert quoi : youl4b.com ou trust-ofm.com.

Propriétaire, 07/11/2026 : « trust-ofm.com … les trucs pour les stats et
tout, mets-les dans ce domaine stp, que les VA ils voient, tu vois
affiliation, tracking des liens, pour les trucs liés à TRUST Instagram,
Twitter et Threads ».

- Les adresses que le bot donne aux VA de TRUST TWITTER, TRUST INSTAGRAM et
  TRUST THREADS (page perso « 📈 Mes stats », espace d'affiliation) partent
  sur SITE_TRUST. Une seule table décide, ici : deux listes de serveurs
  auraient fini par ne plus dire la même chose.
- La vérification reste sur youl4b.com, habillée TRUST (verif_discord) :
  l'identifiant d'appareil qu'elle garde dans le navigateur est propre à
  chaque domaine. Sur trust-ofm.com, un VA qui a déjà deux comptes ne serait
  plus reconnu « même appareil » que ses vérifications d'avant, ni que celles
  de Va IG et de l'Entretien.
- Tout le reste (dashboard, /trust/liens des managers, les autres serveurs)
  reste sur SITE.
- C'est la MÊME application des deux côtés : les liens youl4b.com déjà
  distribués continuent de marcher. Sur trust-ofm.com, seules les pages des
  VA répondent (garde) : la connexion du dashboard n'y existe pas.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
    "/verif/",                    # liens de vérification donnés le 07/11 au soir (15 min)
    "/affiliation/mon-espace",    # affiliation_site (VPS) : l'espace du parrain
    "/affiliation/affiche.png",   # l'affiche de cet espace
    "/trust/liens",               # stats_trust : la page de direction, clé des managers
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

#: L'icône d'onglet des pages TRUST (propriétaire, 07/11/2026 : « enlève
#: youl4b du titre des pages, mets trust ») : sans elle, l'onglet gardait le
#: logo violet Youlab de /favicon.svg. Couleurs de la page « Tes stats ».
ICONE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><title>TRUST</title>'
             '<rect width="64" height="64" rx="14" fill="#f97341"/>'
             '<path d="M15 16h34v9H37v24H27V25H15z" fill="#0e0e10"/></svg>')
#: En data: dans la page, pas en /favicon.svg : un ancien lien youl4b.com
#: aurait reçu le logo Youlab.
ICONE_LIEN = ('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'
              + quote(ICONE_SVG, safe="") + '">')


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
        if not hote_trust(request.host):
            return None
        if request.path in ("/favicon.svg", "/favicon.ico"):
            # l'onglet de toute page de trust-ofm.com, la page neutre comprise
            r = Response(ICONE_SVG, mimetype="image/svg+xml")
            r.headers["Cache-Control"] = "public, max-age=86400"
            return r
        if chemin_trust(request.path):
            return None
        r = Response(PAGE_NEUTRE, status=404, mimetype="text/html")
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Robots-Tag"] = "noindex, nofollow"
        return r
