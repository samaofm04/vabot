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

import datetime as dt
import re
from html import escape as _esc
from typing import Any, Dict, List, Optional, Tuple

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
section p+p{margin-top:6px}
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
.tuiles{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0 0}
.tuile{background:var(--fond);border:1px solid var(--bord);border-radius:10px;padding:10px 12px}
.tuile small{display:block;color:var(--faible);font-size:11.5px;margin:0 0 3px}
.tuile b{font-size:20px;color:var(--acc);font-variant-numeric:tabular-nums}
.tuile span{display:block;color:var(--faible);font-size:12px}
"""

_RE_TITRE = re.compile(r"<title>[^<]*</title>")
_RE_STYLE = re.compile(r"<style>.*?</style>", re.S)
_RE_BANDEAU = re.compile(r"<small>[^<]*YOUL4B[^<]*</small>")
# l'affiche est au décor Mario ; ses deux montants sont écrits dans la page
_RE_AFFICHE = re.compile(r'<figure class="aff-poster">.*?</figure>', re.S)
_NOMS_YOULAB = (("YouL4b", "TRUST"), ("YOUL4B", "TRUST"), ("YouLab", "TRUST"), ("YOULAB", "TRUST"))


def affiliation(html: str, plateforme: str, uid: Optional[str] = None) -> str:
    """La page d'affiliation de `plateforme` au thème TRUST ; avec `uid`, la
    carte de ses invitations sur le serveur de recrutement."""
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
    # Threads (affiliation_privee, hors git) annonçait encore « tous les
    # trackings » : faux depuis la règle des primes du 08/11
    h = h.replace(ANCIENNE_REGLE_THREADS, REGLE_PRIMES)
    h = filleuls(h, plateforme, uid)
    if uid:
        carte = carte_recrutement(recrutement(uid))
        if carte:
            h = h.replace("<footer>", carte + "<footer>", 1)
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


def _ligne(tete: str, n: Optional[int], message: str, ou: str = "", note: str = "") -> str:
    """Un filleul : nom, état, subs (et où ils comptent), ses deux barres."""
    nom, _, etat = tete.partition(" — ")
    haut = (f'<div class="fil-tete"><b>{nom.strip()}</b>'
            + (f'<span class="etat">{etat.strip()}</span>' if etat.strip() else "")
            + (f'<span class="nb">{n} subs{" · " + ou if ou else ""}</span>' if n is not None else "") + "</div>")
    if n is None:
        return f'<div class="fil">{haut}<div class="fil-msg">{message}</div></div>'
    return (f'<div class="fil">{haut}{_cases(n, 10, "Objectif 10")}{_cases(n, 200, "Objectif 200")}'
            + (f'<div class="fil-msg">{note}</div>' if note else "") + "</div>")


def _carte(lignes: list, total: str, note: str = "") -> str:
    return (f"<section><h2>👥 Tes filleuls · {total}</h2>" + "".join(lignes)
            + (f'<p class="fil-note">{note}</p>' if note else "") + "</section>")


# ─── la règle des primes (propriétaire, 07-08/11/2026) ─────────────────────
# « juste tu prends là où le mec il a le plus de subs », « que pour lia » : un
# filleul ne rapporte qu'une prime, comptée sur la plateforme où il a le plus
# de subs de Lia (parmi celles où il a un parrain). Le salon 🤝・qui-t-a-invité
# paie sur cette règle (journal_primes) : la page la lit au même endroit,
# sinon elle montrerait des barres pleines là où rien n'est payé.
LIBELLES = {"agency": "Instagram", "twitter": "Twitter", "threads": "Threads"}
INCONNU_LIA = "Subs de Lia indisponibles pour le moment : aucun palier compté."
ANCIENNE_REGLE_THREADS = ("Les compteurs additionnent les vrais nouveaux abonnés de tous les trackings du "
                          "filleul, anciens compris, cumulés sur ses liens individuels.")
REGLE_PRIMES = "Comptés sur les liens de Lia, sur la plateforme où le filleul a le plus de subs."
#: noms lus sur Discord (journal_primes.pseudo), gardés le temps du processus :
#: sans eux, les filleuls de Twitter et Threads s'affichaient en identifiants
_NOMS_LUS: Dict[str, str] = {}
_LECTURES_MAX = 25          # par page : au-delà, l'identifiant (page lente sinon)


def _etat_filleul(plateforme: str, reg: Dict[str, Any], f: str) -> str:
    """L'état affiché par les panneaux (agency_accueil, twitter/threads_accueil)."""
    fiche = (reg.get("filleuls") or {}).get(f) or {}
    if plateforme == "agency":
        if f in (reg.get("partis") or {}) and f not in (reg.get("membres") or {}):
            return "👋 Parti du serveur"
        return "✅ Vérifié" if fiche.get("verifie") else "⏳ Pas encore vérifié"
    return "✅ Vérifié" if fiche.get("verified") else "👋 Arrivé, non vérifié"


def _noms_connus(regs: Dict[str, Any], jp: Any) -> Dict[str, str]:
    """uid → nom : ceux que le salon a déjà lus sur Discord, ceux du registre
    d'Agency, ceux de la page des affiliations (affiliation_site)."""
    import safe_json
    noms: Dict[str, str] = {}
    try:
        import affiliation_site
        noms.update({str(u): str(n) for u, n in ((affiliation_site._NOMS or {}).get("values") or {}).items() if n})
    except Exception:                                        # noqa: BLE001
        pass
    for cle in ("membres", "partis"):
        noms.update({str(u): str(m.get("nom")) for u, m in ((regs.get("agency") or {}).get(cle) or {}).items()
                     if isinstance(m, dict) and m.get("nom")})
    noms.update({str(u): str(n) for u, n in ((safe_json.load(jp.FICHIER, default={}) or {}).get("noms") or {}).items()
                 if n})
    return noms


def lignes_filleuls(plateforme: str, uid: str) -> Optional[List[str]]:
    """Les filleuls de `uid` sur `plateforme`, à la règle des primes. None si
    une source manque : la page garde alors le texte des panneaux."""
    try:
        import journal_primes as jp
    except ImportError:
        return None
    regs = {p: jp.registre(p) for p in LIBELLES}
    if regs.get(plateforme) is None:
        return None
    arrivees = [e for p, d in regs.items() if d is not None
                for e in jp.evenements_registre(p, d) if e.get("type") == "arrivee"]
    siens = sorted((e for e in arrivees if e["plateforme"] == plateforme and e["parrain"] == str(uid)),
                   key=lambda e: e.get("quand") or 0)
    if not siens:
        return []
    metrics = jp.compteurs()
    noms = _noms_connus(regs, jp)
    lectures = 0
    for e in siens:
        f = e["filleul"]
        if not noms.get(f) and f not in _NOMS_LUS and lectures < _LECTURES_MAX:
            lectures += 1
            jp.pseudo(f, _NOMS_LUS)
        if not noms.get(f) and _NOMS_LUS.get(f):
            noms[f] = _NOMS_LUS[f]
    lignes = []
    for e in siens:
        f = e["filleul"]
        tete = "@" + _esc(noms.get(f) or f) + " — " + _etat_filleul(plateforme, regs[plateforme], f)
        best = jp.meilleure_plateforme([x for x in arrivees if x["filleul"] == f], metrics)
        if not best:
            lignes.append(_ligne(tete, None, INCONNU_LIA))
            continue
        note = ""
        if best["parrain"] != str(uid):
            note = f"Sa prime va à son parrain sur {LIBELLES.get(best['plateforme'], best['plateforme'])}."
        lignes.append(_ligne(tete, best["subs"], "", LIBELLES.get(best["plateforme"], ""), note))
    return lignes


def filleuls(h: str, plateforme: str, uid: Optional[str] = None) -> str:
    """Les filleuls réunis en une carte, en carrés. Avec `uid` (la page en
    ligne) : à la règle des primes ; sans (ou source illisible) : les chiffres
    écrits par les panneaux."""
    lignes = lignes_filleuls(plateforme, uid) if uid else None
    if lignes:
        blocs = list(_RE_THREADS.finditer(h)) if plateforme == "threads" else []
        carte = _carte(lignes, str(len(lignes)))
        if plateforme == "threads" and blocs:
            return h[:blocs[0].start()] + carte + "".join(
                h[a.end():b.start()] for a, b in zip(blocs, blocs[1:])) + h[blocs[-1].end():]
        h = _RE_PROGRESSION.sub("", h)
        compte = _RE_COMPTE.search(h)
        if compte:
            return h[:compte.start()] + carte + h[compte.end():]
        print(f"[habillage_trust] filleuls {plateforme} : rubrique « Tes filleuls » introuvable", flush=True)
        return h.replace("<footer>", carte + "<footer>", 1)
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


# ─── les invitations du serveur de recrutement (propriétaire, 07/11/2026 :
# « quand il invite quelqu'un dans le serveur recrutement il gagne 0,20 ») ──
# Les chiffres sont ceux du bilan que le bot poste chaque semaine
# (entretien_parrainage / entretien_espaces, hors git) : mêmes déclarations,
# même semaine close le dimanche à 23 h 59. Lecture seule : lien_pour()
# créerait une invitation Discord, on lit seulement celle qui existe.
def recrutement(uid: str, maintenant: Optional[dt.datetime] = None) -> Optional[Dict[str, Any]]:
    """Le lien et les invitations vérifiées de `uid`, ou None hors VPS."""
    try:
        import entretien_parrainage as e
    except ImportError:
        return None
    uid = str(uid)
    with e.LOCK:
        etat = e.lire()
    semaine = e.semaine(maintenant or dt.datetime.now(e.TZ))
    siennes = [r for r in (etat.get("declarations") or {}).values() if r.get("parrain") == uid]
    cette = [r for r in siennes if r.get("semaine") == semaine]
    debut = dt.date.fromisoformat(semaine)
    code = ((etat.get("liens") or {}).get(uid) or {}).get("code")
    return {"lien": f"https://discord.gg/{code}" if code else "",
            "prix": e.euros(e.PRIX_CENTIMES),
            "du": debut.strftime("%d/%m"), "au": (debut + dt.timedelta(days=6)).strftime("%d/%m"),
            "semaine": (len(cette), e.euros(sum(int(r.get("centimes", 0)) for r in cette))),
            "total": (len(siennes), e.euros(sum(int(r.get("centimes", 0)) for r in siennes))),
            "attente": sum(1 for r in (etat.get("en_attente") or {}).values() if r.get("parrain") == uid)}


def carte_recrutement(d: Optional[Dict[str, Any]]) -> str:
    if not d:
        return ""
    if d["lien"]:
        l = _esc(d["lien"], quote=True)
        lien = (f'<p><a href="{l}" target="_blank" rel="noreferrer">{l}</a></p>'
                f'<button type="button" class="copier-lien" data-lien="{l}">📋 Copier le lien</button>'
                '<span class="copie-statut" role="status" aria-live="polite"></span>')
    else:
        lien = '<p class="fil-msg">Ton lien d\'invitation t\'attend sur le serveur de recrutement TRUST Agency.</p>'
    (n_s, m_s), (n_t, m_t) = d["semaine"], d["total"]
    return ("<section><h2>🎙️ Recrutement · TRUST Agency</h2>"
            f"<p>Invite des personnes sur le serveur de recrutement : <b>{d['prix']}</b> par personne "
            "qui se vérifie.</p>" + lien
            + '<div class="tuiles">'
            f'<div class="tuile"><small>Cette semaine · du {d["du"]} au {d["au"]}</small><b>{n_s}</b>'
            f'<span>vérifiée(s) · {m_s}</span></div>'
            f'<div class="tuile"><small>Depuis le début</small><b>{n_t}</b><span>vérifiée(s) · {m_t}</span></div>'
            "</div>"
            f'<p class="fil-note">⏳ {d["attente"]} en attente de vérification · semaine close le dimanche '
            "à 23 h 59 (heure de Paris)</p></section>")


def qui_affiliation(jeton: Optional[str]) -> Optional[Tuple[str, str]]:
    """(plateforme, uid) du lien d'affiliation, par affiliation_site (hors
    git) : même règle que sa page, personnel(). None hors VPS ou lien inconnu."""
    try:
        import affiliation_site
    except ImportError:
        return None
    cle = affiliation_site.identite(jeton)
    if not cle:
        return None
    cle = str(cle)
    if cle.startswith(("twitter:", "instagram:", "agency:")):
        p, _, uid = cle.partition(":")
        return p, uid
    return "threads", cle


def plateforme_affiliation(jeton: Optional[str]) -> Optional[str]:
    q = qui_affiliation(jeton)
    return q[0] if q else None


def installer(app) -> None:
    from flask import request

    @app.after_request
    def _habiller_affiliation(r):
        if (request.path != "/affiliation/mon-espace" or r.status_code != 200
                or r.mimetype != "text/html" or r.direct_passthrough):
            return r
        try:
            q = qui_affiliation(request.args.get("t"))
            if q and q[0] in NOMS:
                r.set_data(affiliation(r.get_data(as_text=True), q[0], q[1]))
        except Exception as e:      # la page d'origine plutôt qu'une erreur 500
            print(f"[habillage_trust] {type(e).__name__}: {e}", flush=True)
        return r
