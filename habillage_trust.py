"""habillage_trust.py — l'espace d'affiliation des VA de TRUST, au thème TRUST.

Propriétaire, 07/11/2026 : « enlève youl4b du titre des pages, mets trust »,
et pour la page d'affiliation « le thème comme pour le tracking des subs, un
truc vraiment carré » — le thème de « Tes stats » (stats_va).

La page /affiliation/mon-espace est fabriquée par affiliation_site.py, un
fichier du VPS hors git (thème Mario, « YOUL4B · VA … »). On ne la réécrit
pas là-bas : on l'habille ici, à la sortie, pour TRUST TWITTER, TRUST THREADS
et TRUST INSTAGRAM (« agency »). Va IG (« instagram ») garde sa page.
Ce qui n'est pas retrouvé dans la page est signalé dans le journal, jamais
laissé de côté en silence.
"""
from __future__ import annotations

import re
from typing import Optional

import domaines
import stats_va

#: plateforme d'affiliation → (bandeau, nom court)
NOMS = {
    "threads": ("TRUST THREADS", "Threads"),
    "twitter": ("TRUST TWITTER", "Twitter"),
    "agency": ("TRUST INSTAGRAM", "Instagram"),
}

#: Le thème de « Tes stats » (mêmes couleurs, même bandeau), plus les cartes
#: de l'espace d'affiliation. `section .copier-lien` : la page pose plus bas
#: sa propre règle `.copier-lien` ; à spécificité égale, elle gagnerait.
STYLE = stats_va._STYLE + """
main{max-width:640px;margin:0 auto}
h1{font-size:22px}
main>p{color:var(--faible);font-size:13px;margin:0 0 16px}
section{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px 16px;margin:0 0 10px}
section h2{font-size:13px;font-weight:600;color:var(--faible);margin:0 0 6px}
section p{margin:0;font-size:14px;overflow-wrap:anywhere}
section a{color:var(--acc);font-weight:600;text-decoration:none}
section .copier-lien{background:var(--acc);color:#1c0a02;border:0;border-radius:8px;padding:8px 16px;font:inherit;font-weight:700;cursor:pointer;margin:10px 10px 0 0}
section .copie-statut{color:var(--faible);font-size:12px}
footer{color:var(--faible);font-size:12px;line-height:1.6;margin:14px 0 0}
"""

_RE_TITRE = re.compile(r"<title>[^<]*</title>")
_RE_STYLE = re.compile(r"<style>.*?</style>", re.S)
_RE_BANDEAU = re.compile(r"<small>[^<]*YOUL4B[^<]*</small>")
# l'affiche est au décor Mario ; ses deux montants sont écrits dans la page
_RE_AFFICHE = re.compile(r'<figure class="aff-poster">.*?</figure>', re.S)
_NOMS_YOULAB = (("YouL4b", "TRUST"), ("YOUL4B", "TRUST"), ("YouLab", "TRUST"), ("YOULAB", "TRUST"))


def affiliation(html: str, plateforme: str) -> str:
    """La page d'affiliation de `plateforme` au thème TRUST."""
    bandeau, court = NOMS[plateforme]
    h, n_titre = _RE_TITRE.subn("<title>Mon affiliation · TRUST</title>" + domaines.ICONE_LIEN, html, count=1)
    # le premier <style> est celui du thème (Mario) ; le second, celui du
    # bouton « Copier », reste
    h, n_style = _RE_STYLE.subn(lambda _m: "<style>" + STYLE + "</style>", h, count=1)
    h, n_bandeau = _RE_BANDEAU.subn(f'<div class="marque">{bandeau}</div>', h, count=1)
    h = _RE_AFFICHE.sub("", h)
    if plateforme == "agency":
        # « Ton lien personnel · Agency », « pour Agency » : TRUST INSTAGRAM
        h = h.replace(" Agency", " " + court)
    for avant, apres in _NOMS_YOULAB:
        h = h.replace(avant, apres)
    manque = [nom for nom, n in (("titre", n_titre), ("thème", n_style), ("bandeau", n_bandeau)) if not n]
    if manque:
        print(f"[habillage_trust] affiliation {plateforme} : {', '.join(manque)} introuvable(s) "
              "— affiliation_site.py a changé ?", flush=True)
    return h


def plateforme_affiliation(jeton: Optional[str]) -> Optional[str]:
    """La plateforme du lien d'affiliation, par affiliation_site (hors git) :
    même règle que sa page, personnel(). None hors VPS ou lien inconnu."""
    try:
        import affiliation_site
    except ImportError:
        return None
    uid = affiliation_site.identite(jeton)
    if not uid:
        return None
    uid = str(uid)
    return uid.split(":", 1)[0] if uid.startswith(("twitter:", "instagram:", "agency:")) else "threads"


def installer(app) -> None:
    from flask import request

    @app.after_request
    def _habiller_affiliation(r):
        if (request.path != "/affiliation/mon-espace" or r.status_code != 200
                or r.mimetype != "text/html" or r.direct_passthrough):
            return r
        try:
            p = plateforme_affiliation(request.args.get("t"))
            if p in NOMS:
                r.set_data(affiliation(r.get_data(as_text=True), p))
        except Exception as e:      # la page d'origine plutôt qu'une erreur 500
            print(f"[habillage_trust] {type(e).__name__}: {e}", flush=True)
        return r
