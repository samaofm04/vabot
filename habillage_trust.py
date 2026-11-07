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
.fil{padding:12px 0;border-top:1px solid var(--bord)}
.fil:first-of-type{border-top:0;padding-top:4px}
.fil-tete{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin:0 0 8px}
.fil-tete b{font-size:15px;overflow-wrap:anywhere}
.fil-tete .etat{color:var(--faible);font-size:12px}
.fil-tete .nb{margin-left:auto;color:var(--acc);font-weight:700;font-size:15px;white-space:nowrap}
.fil-msg{color:var(--faible);font-size:13px}
.pal{display:grid;grid-template-columns:86px minmax(0,240px) auto;align-items:center;gap:10px;margin:5px 0}
.pal .lib{color:var(--faible);font-size:12px}
.pal .cases{display:grid;grid-template-columns:repeat(10,1fr);gap:3px}
.pal .cases i{display:block;aspect-ratio:1;border-radius:3px;background:var(--bord)}
.pal .cases i.on{background:var(--acc)}
.pal.ok .cases i{background:#4ade80}
.pal .pct{font-size:12px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.pal.ok .pct{color:#4ade80}
.fil-note{color:var(--faible);font-size:12px;margin:8px 0 0}
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
    h = filleuls(h, plateforme)
    manque = [nom for nom, n in (("titre", n_titre), ("thème", n_style), ("bandeau", n_bandeau)) if not n]
    if manque:
        print(f"[habillage_trust] affiliation {plateforme} : {', '.join(manque)} introuvable(s) "
              "— affiliation_site.py a changé ?", flush=True)
    return h


# ─── les filleuls en carrés (propriétaire, 07/11/2026 : « des carrés de 0 à
# 100 avec les subs, qui avance ») ───────────────────────────────────────────
# Les trois panneaux (hors git) n'écrivent pas la progression pareil :
#   TRUST INSTAGRAM : une rubrique « 📊 Progression du filleul » par filleul,
#                     « @nom — état<br>60 vrais subs · Objectif 10 : … » ;
#   TRUST TWITTER   : la même, sans l'état ;
#   TRUST THREADS   : tous dans « 👥 Tes filleuls · N », séparés par <br><br>,
#                     « @nom — état<br>🎯 10 : 60/10 subs · … <br>🏆 200 : … ».
# Un filleul dont les subs ne se lisent pas garde son texte, sous son nom.
_RE_PROGRESSION = re.compile(r"<section><h2>📊 Progression du filleul</h2><p>(.*?)</p></section>", re.S)
_RE_COMPTE = re.compile(r"<section><h2>👥 Tes filleuls</h2><p>(\d+) filleul\(s\) enregistré\(s\)\.</p></section>")
_RE_THREADS = re.compile(r"<section><h2>👥 (?:Tes filleuls · (\d+)|Suite des filleuls)</h2><p>(.*?)</p></section>", re.S)
_RE_SUBS = re.compile(r"^(\d+) vrais subs · Objectif 10")
_RE_SUBS_THREADS = re.compile(r"🎯 10 : (\d+)/10 subs")


def _cases(n: int, seuil: int, lib: str) -> str:
    """Dix carrés de 0 à 100 % ; celui en cours se remplit à moitié, au quart…"""
    pct = min(100.0, n * 100 / seuil)
    plein, reste = int(pct // 10), pct % 10
    cases = []
    for i in range(10):
        if i < plein:
            cases.append('<i class="on"></i>')
        elif i == plein and reste:
            cases.append(f'<i style="background:linear-gradient(90deg,var(--acc) {reste * 10:g}%,var(--bord) 0)"></i>')
        else:
            cases.append("<i></i>")
    texte = f"{pct:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    ok = n >= seuil
    return (f'<div class="pal{" ok" if ok else ""}"><span class="lib">{lib}</span>'
            f'<span class="cases" role="img" aria-label="{texte} % de l\'{lib.lower()}">{"".join(cases)}</span>'
            f'<span class="pct">{texte} %{" ✓" if ok else ""}</span></div>')


def _ligne(tete: str, n: Optional[int], message: str) -> str:
    nom, _, etat = tete.partition(" — ")
    haut = (f'<div class="fil-tete"><b>{nom.strip()}</b>'
            + (f'<span class="etat">{etat.strip()}</span>' if etat.strip() else "")
            + (f'<span class="nb">{n} subs</span>' if n is not None else "") + "</div>")
    if n is None:
        return f'<div class="fil">{haut}<div class="fil-msg">{message}</div></div>'
    return f'<div class="fil">{haut}{_cases(n, 10, "Objectif 10")}{_cases(n, 200, "Objectif 200")}</div>'


def _carte(lignes: list, total: str, note: str = "") -> str:
    return (f"<section><h2>👥 Tes filleuls · {total}</h2>" + "".join(lignes)
            + (f'<p class="fil-note">{note}</p>' if note else "") + "</section>")


def filleuls(h: str, plateforme: str) -> str:
    """Les rubriques de progression des filleuls réunies en une carte, en carrés."""
    if plateforme in ("agency", "twitter"):
        lignes = []
        for m in _RE_PROGRESSION.finditer(h):
            tete, _, suite = m.group(1).partition("<br>")
            s = _RE_SUBS.match(suite.strip())
            lignes.append(_ligne(tete, int(s.group(1)) if s else None, suite))
        if not lignes:
            return h
        h = _RE_PROGRESSION.sub("", h)
        compte = _RE_COMPTE.search(h)
        carte = _carte(lignes, compte.group(1) if compte else str(len(lignes)))
        if compte:
            return h[:compte.start()] + carte + h[compte.end():]
        print(f"[habillage_trust] filleuls {plateforme} : rubrique « Tes filleuls » introuvable", flush=True)
        return h.replace("<footer>", carte + "<footer>", 1)
    if plateforme == "threads":
        blocs = list(_RE_THREADS.finditer(h))
        if not blocs or blocs[0].group(1) in (None, "0"):
            return h
        lignes, note = [], ""
        for b in blocs:
            for entree in b.group(2).split("<br><br>"):
                if entree.startswith("…"):
                    note = entree
                    continue
                tete, _, suite = entree.partition("<br>")
                s = _RE_SUBS_THREADS.search(suite)
                lignes.append(_ligne(tete, int(s.group(1)) if s else None, suite))
        carte = _carte(lignes, blocs[0].group(1), note)
        return h[:blocs[0].start()] + carte + "".join(
            h[a.end():b.start()] for a, b in zip(blocs, blocs[1:])) + h[blocs[-1].end():]
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
