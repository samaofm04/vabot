# -*- coding: utf-8 -*-
"""clics_portail.py — le report des clics, lisible par un simple lien.

LE MANQUE QUE CA COMBLE. Le report part sur Discord, dans un salon d'un
serveur. Pour qu'une deuxieme equipe le lise — celle qui s'occupe de
Twitter, sur un autre serveur — il faudrait y installer le bot : de
nouvelles permissions, de nouveaux salons, une deuxieme configuration a
tenir, et un bot de plus a surveiller. Pour de la LECTURE, c'est cher.

Ce module ouvre une porte etroite :

    https://youl4b.com/clics/<jeton>

Le jeton donne UNE page, en lecture seule, qui montre exactement ce que
Discord montre : le resume, les abonnes par lien, le detail par lien. On
envoie l'adresse, la personne l'ouvre dans son navigateur, et c'est tout.

CE QUI N'Y EST PAS, ET N'Y SERA PAS. Aucun bouton, aucun formulaire, aucune
navigation : il n'y a rien a atteindre depuis cette page parce qu'il n'y a
rien d'autre de charge. Un lien se recopie, se transfere, finit dans une
conversation de groupe — ce qui passe par la doit pouvoir etre lu par
quelqu'un a qui il n'etait pas destine sans que ce soit une fuite. Des
clics et des abonnes, ce sont des chiffres de travail ; des identifiants,
non, et il n'y en a pas ici.

UN JETON PAR REPORT, pas par personne. Le report Discord montre deja tout
le monde a tous ceux qui lisent le salon : une page qui montre la meme
chose n'expose rien de plus. Des liens par personne demanderaient un jeton
par VA, donc une distribution a tenir, pour un ecran que personne n'a
demande.

LE CONTENU N'EST PAS RECALCULE ICI. La page appelle la MEME fonction que
Discord (`_build_group_report`) et met en forme ce qu'elle rend. Deux
chemins de calcul finiraient par diverger, et le jour ou ils divergent,
c'est le chiffre affiche a l'equipe qui devient faux sans que personne ne
le voie.
"""
from __future__ import annotations

import html
import json
import re
import secrets
import time
from pathlib import Path

import safe_json

RACINE = "/clics"
FICHIER = Path("data") / "clics_portail.json"

#: Le rendu est garde quelques minutes. Le report interroge GetMySocial et
#: MyPuls ; sans cache, dix personnes qui ouvrent le lien en meme temps font
#: dix fois le travail — et le quota MyPuls est de 60 requetes par minute.
TTL_RENDU = 240
_CACHE: dict = {}


# ==============================================================================
# Les jetons
# ==============================================================================

def _charger() -> dict:
    try:
        d = json.loads(FICHIER.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ecrire(d: dict) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER, d, indent=2)


def liste() -> list:
    """[{jeton, cle, libelle, cree, vues}] — le jeton COMPLET.

    Il est rendu en entier parce que la seule chose qu'on veuille en faire,
    c'est le recopier. Le masquer obligerait a le regenerer pour le relire.
    """
    return [{"jeton": j, **(v if isinstance(v, dict) else {})}
            for j, v in sorted(_charger().items(),
                               key=lambda x: -(x[1] or {}).get("cree", 0))]


def creer(cle: str, libelle: str = "", portee: dict | None = None) -> str:
    """Un jeton pour un report, ou pour un ESPACE GetMySocial. Rend le jeton.

    DEUX PORTEES POSSIBLES, et la seconde n'est pas un raffinement :

    - un report deja configure sur Discord (`serveur:salon`) ;
    - un espace GetMySocial DIRECTEMENT (`{team_id, group_id, marche...}`).

    Le second cas existe parce qu'une equipe peut avoir besoin de lire des
    chiffres sans qu'on ait configure de salon pour eux — c'est meme la
    raison d'etre de ce module : ne pas installer le bot ailleurs. Exiger un
    report Discord prealable aurait remis exactement la dependance qu'on
    voulait retirer.

    UN SEUL jeton par portee : en creer un second ne ferait que semer des
    adresses qui montrent la meme chose, sans moyen de savoir laquelle a ete
    envoyee a qui.
    """
    d = _charger()
    for j, v in d.items():
        if isinstance(v, dict) and v.get("cle") == cle:
            return j
    jeton = secrets.token_urlsafe(18)
    d[jeton] = {"cle": str(cle), "libelle": str(libelle or "")[:80],
                "cree": int(time.time()), "vues": 0}
    if portee:
        # La portee est RECOPIEE dans le jeton, pas relue ailleurs : un espace
        # renomme ou un salon reconfigure ne doit pas changer ce qu'une
        # adresse deja envoyee affiche.
        d[jeton]["portee"] = {k: str(v)[:60] for k, v in portee.items() if v}
    _ecrire(d)
    return jeton


def revoquer(jeton: str) -> bool:
    d = _charger()
    if jeton in d:
        del d[jeton]
        _ecrire(d)
        return True
    return False


def _noter_vue(jeton: str) -> None:
    """Compte les ouvertures. Sans ca, on ne sait pas si le lien sert."""
    d = _charger()
    v = d.get(jeton)
    if isinstance(v, dict):
        v["vues"] = int(v.get("vues") or 0) + 1
        v["vu"] = int(time.time())
        _ecrire(d)


# ==============================================================================
# La page
# ==============================================================================

_CSS = """
/* Les couleurs vivent dans des variables POUR QUE LE SVG LES PARTAGE : la
   courbe est dessinee dans le HTML, elle peut donc lire var(--accent) comme
   le reste. Avant, ses bleus etaient ecrits en dur et survivaient seuls a
   tout changement de theme. */
:root{
  --fond:#faf9f5; --surface:#ffffff; --surface-2:#f4f2ea; --bordure:#e6e2d7;
  --texte:#1f1e1d; --attenue:#6f6b60; --faible:#9a9689;
  --accent:#d97757; --accent-doux:rgba(217,119,87,.12);
  --vert:#4f7d5b; --rouge:#bf4d3b;
  --ombre:0 1px 2px rgba(31,30,29,.05), 0 6px 18px -8px rgba(31,30,29,.10);
  --serif:ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif,
         "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji";
  --sans:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --chiffres:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media(prefers-color-scheme:dark){:root{
  --fond:#1f1e1d; --surface:#262624; --surface-2:#2f2f2c; --bordure:#3b3a37;
  --texte:#f5f4ee; --attenue:#a8a49a; --faible:#7d7a71;
  --accent:#e08b6b; --accent-doux:rgba(224,139,107,.16);
  --vert:#7bab86; --rouge:#e08776;
  --ombre:0 1px 2px rgba(0,0,0,.28), 0 6px 18px -8px rgba(0,0,0,.40);
}}

*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);
     -webkit-font-smoothing:antialiased;font:15px/1.6 var(--sans)}
.wrap{max-width:960px;margin:0 auto;padding:40px 20px 72px}

header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}
h1{font:600 27px/1.25 var(--serif);margin:0;letter-spacing:-.01em}
.tag{font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
     color:var(--accent);background:var(--accent-doux);
     border-radius:999px;padding:4px 11px}
.sous{color:var(--attenue);font-size:13.5px;margin:0 0 28px}

/* Les tuiles. Le chiffre d'abord, en serif : c'est lui qu'on vient lire. */
.cartes,.kpis{display:grid;gap:12px;margin-bottom:24px;
              grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
.carte,.kpi{background:var(--surface);border:1px solid var(--bordure);
            border-radius:12px;padding:16px 18px;box-shadow:var(--ombre)}
.carte .q,.kpi .q{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
                  color:var(--attenue);font-weight:600;margin-bottom:8px}
.carte .v,.kpi .v{font:600 28px/1.1 var(--serif);letter-spacing:-.02em;
                  font-variant-numeric:tabular-nums}
.kpi .v{font-size:31px}
.carte .s,.kpi .s{font-size:12px;color:var(--faible);margin-top:5px}
.carte.forte{border-color:var(--accent);background:var(--surface)}
.carte.forte .v,.kpi.a .v{color:var(--accent)}

/* L'EVOLUTION EST LE POINT DU TABLEAU. Deux quinzaines cote a cote ne
   disent rien tant qu'on doit soustraire de tete : la fleche le fait. */
.ev{font-size:12px;font-weight:600;font-variant-numeric:tabular-nums}
.ev.up{color:var(--vert)}
.ev.dn{color:var(--rouge)}
.ev.eq{color:var(--faible);font-weight:400}

/* Un en-tete qui coiffe deux colonnes : sans lui, « us » et « 🌍 » se
   suivent sans qu'on sache a quelle periode ils appartiennent. */
th.grp{text-align:center;color:var(--attenue);font-weight:600;
       border-bottom:1px solid var(--bordure);padding-bottom:6px;font-size:10.5px}
th.sub{padding-top:4px;font-size:10px;color:var(--faible)}
tr.tetes2 th{border-bottom:1px solid var(--bordure)}

/* Les onglets. GetMySocial met une barre laterale ; sur un telephone elle
   mange la moitie de l ecran, alors qu il n y a que deux vues. */
.onglets{display:flex;gap:6px;margin:0 0 26px;flex-wrap:wrap}
.onglets a{font-size:13.5px;font-weight:500;color:var(--attenue);
           text-decoration:none;padding:7px 15px;border-radius:999px}
.onglets a:hover{background:var(--surface-2);color:var(--texte)}
.onglets a.on{background:var(--accent-doux);color:var(--accent);font-weight:600}

/* Le palmares : le classement, pas le tableau. On vient y voir QUI porte le
   trafic, pas comparer trente lignes - c est le role de l autre vue. */
.top{padding:2px 20px 16px}
.li{display:flex;align-items:center;gap:12px;padding:10px 0;font-size:13.5px;
    border-top:1px solid var(--bordure)}
.li:first-child{border-top:none}
.li .r{width:28px;height:22px;flex:none;display:inline-flex;align-items:center;
       justify-content:center;font-size:11px;font-weight:600;color:var(--attenue);
       background:var(--surface-2);border-radius:999px}
.li.podium .r{background:var(--accent-doux);color:var(--accent)}
.li .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.li .c{font-family:var(--chiffres);font-size:12.5px;font-weight:600;
       font-variant-numeric:tabular-nums;flex:none}
.li .ab{width:84px;text-align:right;color:var(--attenue);font-size:12px;flex:none}
h2 .tout{float:right;font:600 11.5px/1 var(--sans);color:var(--accent);
         text-decoration:none;background:var(--accent-doux);
         border-radius:999px;padding:6px 12px;text-transform:none;letter-spacing:0}

.graph{padding:4px 18px 18px}
.graph svg{display:block;width:100%;height:auto}

/* Trois listes cote a cote : pays, appareils, provenance. */
.trio{display:grid;gap:16px;margin-bottom:20px;
      grid-template-columns:repeat(auto-fit,minmax(258px,1fr))}
.trio section{margin:0}
.barres{padding:2px 18px 16px}
.br{display:flex;align-items:center;gap:12px;margin:10px 0;font-size:13.5px}
.br .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
       color:var(--texte)}
.br .j{width:84px;height:6px;background:var(--surface-2);border-radius:999px;
       overflow:hidden;flex:none}
.br .j i{display:block;height:100%;border-radius:999px;background:var(--accent)}
.br .c{width:54px;text-align:right;font-family:var(--chiffres);font-size:12.5px;
       font-variant-numeric:tabular-nums;font-weight:600;color:var(--texte);flex:none}

section{background:var(--surface);border:1px solid var(--bordure);border-radius:12px;
        padding:4px 0 8px;margin-bottom:20px;overflow:hidden;box-shadow:var(--ombre)}
section>h2{font:600 16px/1.3 var(--serif);color:var(--texte);margin:0;
           padding:18px 20px 12px;letter-spacing:-.005em}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:10px 15px;text-align:right;white-space:nowrap}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
   color:var(--attenue);font-weight:600;border-bottom:1px solid var(--bordure)}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;
   background:var(--surface);font-weight:500}
tbody tr:nth-child(even) td,
tbody tr:nth-child(even) td:first-child{background:var(--surface-2)}
tbody tr:hover td,
tbody tr:hover td:first-child{background:var(--accent-doux)}
/* Les chiffres en chasse fixe : c'est ce qui aligne les colonnes du haut en
   bas. Releve sur le tableau de bord d'origine, et c'est ce qui le rendait
   lisible sur trente lignes. */
td.n{font-family:var(--chiffres);font-size:12.5px;font-weight:600;
     font-variant-numeric:tabular-nums}
td.z{color:var(--faible);font-weight:400}     /* un zero ne doit pas crier */
td.g{color:var(--attenue);font-weight:400}    /* la colonne globale, en retrait */
.gr{border-left:1px solid var(--bordure)}

.pied{color:var(--faible);font-size:12px;text-align:center;margin-top:32px;
      line-height:1.8}
@media(max-width:620px){
  .wrap{padding:24px 12px 48px}
  h1{font-size:21px}
  th,td{padding:9px 11px;font-size:12.5px}
  .carte .v{font-size:23px}.kpi .v{font-size:26px}
}
"""


def _num(v) -> str:
    """12345 -> « 12 345 ». Une espace fine insecable, pas une virgule."""
    try:
        return "{:,}".format(int(v)).replace(",", "\u202f")
    except (TypeError, ValueError):
        return "—"


def _case(v, doux: bool = False) -> str:
    """Une cellule de chiffre. Un ZERO s'efface au lieu de crier.

    Sur trente lignes dont vingt a zero, des zeros en gras noient les trois
    chiffres qui comptent — on les met en gris, et l'oeil va tout seul la ou
    il se passe quelque chose.
    """
    n = 0
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        n = 0
    classe = "n z" if n == 0 else ("n g" if doux else "n")
    return "<td class='%s'>%s</td>" % (classe, _num(n) if v is not None else "—")


def _table(entetes: list, lignes: list, coiffe: str = "") -> str:
    """Une vraie table. `entetes` = [(libelle, ouvre_un_groupe)].

    `coiffe` est une rangee d'en-tete supplementaire, posee AU-DESSUS : elle
    sert quand plusieurs colonnes appartiennent a une meme periode et qu'on
    ne saurait pas, sinon, a laquelle « 🌍 » se rapporte.
    """
    th = "".join("<th%s>%s</th>" % (" class='gr'" if g else "", html.escape(t))
                 for t, g in entetes)
    return ("<div class='scroll'><table><thead>%s<tr class='tetes2'>%s</tr>"
            "</thead><tbody>%s</tbody></table></div>"
            % (coiffe, th, "".join(lignes)))


def _evolution(courant, precedent) -> str:
    """« +12 », « −5 », « = » — la comparaison, faite pour le lecteur.

    Deux colonnes cote a cote demandent une soustraction de tete, trente
    fois. Sans reference (quinzaine precedente a zero), on ne montre RIEN
    plutot qu'un « +100 % » qui n'a pas de sens.
    """
    try:
        c, pr = int(courant or 0), int(precedent or 0)
    except (TypeError, ValueError):
        return "<td></td>"
    if c == pr:
        return "<td class='ev eq'>=</td>"
    d = c - pr
    return ("<td class='ev %s'>%s%s</td>"
            % ("up" if d > 0 else "dn", "+" if d > 0 else "−", _num(abs(d))))


def _courbe(points: list) -> str:
    """Une aire, dessinee en SVG COTE SERVEUR.

    Pas de bibliotheque de graphiques : la page ne charge aucun script, et
    c'est ce qui lui permet de s'ouvrir partout, y compris la ou le
    JavaScript est bloque. Un <svg> est du HTML, il ne demande rien a
    personne.
    """
    vals = [max(0, int(p.get("v") or 0)) for p in points]
    if not vals or max(vals) == 0:
        return ""
    L, H, m = 720.0, 150.0, 8.0
    hi = float(max(vals))
    n = len(vals)
    pas = (L - 2 * m) / max(1, n - 1)
    # DE LA PLACE AU-DESSUS DU PIC. Avec la meme marge en haut et en bas, le
    # sommet touchait le bord et son chiffre sortait du cadre : « 505 » etait
    # rase par le haut du SVG. Le pic monte donc au plus haut a 22 px du bord.
    haut = 22.0
    pts = [(m + i * pas, H - m - (v / hi) * (H - m - haut)) for i, v in enumerate(vals)]
    ligne = " ".join("%.1f,%.1f" % xy for xy in pts)
    aire = "%s %.1f,%.1f %.1f,%.1f" % (ligne, pts[-1][0], H - m, pts[0][0], H - m)
    # Les reperes : le plus haut, et le dernier. Deux chiffres suffisent a
    # lire une courbe ; une grille complete ferait du bruit pour rien.
    i_hi = vals.index(max(vals))
    reperes = "".join(
        "<circle cx='%.1f' cy='%.1f' r='3.5' fill='var(--accent)'/>"
        "<text x='%.1f' y='%.1f' fill='var(--accent)' font-size='11' font-weight='700'"
        " text-anchor='middle'>%s</text>"
        % (pts[i][0], pts[i][1], pts[i][0], max(12, pts[i][1] - 9), _num(vals[i]))
        for i in {i_hi, n - 1})
    etiq = "".join(
        "<text x='%.1f' y='%.1f' fill='var(--faible)' font-size='9.5' text-anchor='%s'>%s</text>"
        % (pts[i][0], H - 1, "start" if i == 0 else "end",
           html.escape(str(points[i].get("j") or "")))
        for i in (0, n - 1) if n > 1)
    return (
        "<div class='graph'><svg viewBox='0 0 %d %d' preserveAspectRatio='none'"
        " role='img' aria-label='Évolution'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
        "<stop offset='0' stop-color='var(--accent)' stop-opacity='.22'/>"
        "<stop offset='1' stop-color='var(--accent)' stop-opacity='0'/>"
        "</linearGradient></defs>"
        "<polygon points='%s' fill='url(#g)'/>"
        "<polyline points='%s' fill='none' stroke='var(--accent)' stroke-width='2'"
        " stroke-linejoin='round' stroke-linecap='round'/>%s%s</svg></div>"
        % (int(L), int(H), aire, ligne, reperes, etiq))


def _barres(titre: str, lignes: list) -> str:
    """Une liste avec sa jauge. `lignes` = [(libelle, compte)]."""
    if not lignes:
        return ""
    hi = max((int(c or 0) for _l, c in lignes), default=0) or 1
    corps = "".join(
        "<div class='br'><div class='n'>%s</div>"
        "<div class='j'><i style='width:%.0f%%'></i></div>"
        "<div class='c'>%s</div></div>"
        % (html.escape(str(l)[:34]), 100.0 * int(c or 0) / hi, _num(c))
        for l, c in lignes[:6])
    return ("<section><h2>%s</h2><div class='barres'>%s</div></section>"
            % (html.escape(titre), corps))


def _audience(a: dict, intercale: str = "") -> str:
    """Les cartes, la courbe et les trois listes. '' si rien n'est venu."""
    if not isinstance(a, dict) or not a:
        # Ce qu on nous a confie a intercaler ne doit pas disparaitre avec
        # l audience : GetMySocial peut ne pas repondre, le palmares vient
        # du report et reste juste.
        return intercale
    out = []
    vues = int(a.get("pages_vues") or 0)
    clics = int(a.get("clics") or 0)
    uniques = int(a.get("visiteurs") or 0)
    taux = (100.0 * clics / vues) if vues else 0.0
    # LA TROISIEME CARTE DEPEND DE CE QUE LES CHIFFRES PERMETTENT DE DIRE.
    #
    # Sur un espace de liens DIRECTS, chaque page vue est un clic : le taux
    # vaut 100 % tous les jours et n'apprend rien. (Le 40 % du tableau de
    # bord de GetMySocial porte sur tout le compte, pages d'atterrissage
    # comprises — ce n'est pas la meme population.) On montre alors les clics
    # par visiteur, qui dit quelque chose : au-dessus de 1, des gens
    # reviennent.
    if vues and clics and abs(vues - clics) > max(1, vues * 0.02):
        troisieme = ("<div class='q'>Taux de clic</div><div class='v'>%.1f%%</div>"
                     "<div class='s'>%s clic(s)</div>" % (taux, _num(clics)))
    elif uniques:
        troisieme = ("<div class='q'>Clics par visiteur</div>"
                     "<div class='v'>%.2f</div>"
                     "<div class='s'>%s clic(s) · liens directs</div>"
                     % (clics / uniques, _num(clics)))
    else:
        troisieme = ("<div class='q'>Clics</div><div class='v'>%s</div>"
                     "<div class='s'>sur la période</div>" % _num(clics))
    out.append(
        "<div class='kpis'>"
        "<div class='kpi a'><div class='q'>Pages vues</div><div class='v'>%s</div>"
        "<div class='s'>%s</div></div>"
        "<div class='kpi b'><div class='q'>Visiteurs uniques</div><div class='v'>%s</div>"
        "<div class='s'>%s%% des pages vues</div></div>"
        "<div class='kpi c'>%s</div>"
        "</div>"
        % (_num(vues), html.escape(str(a.get("periode") or "")),
           _num(uniques), ("%.0f" % (100.0 * uniques / vues)) if vues else "—",
           troisieme))
    c = _courbe(a.get("serie") or [])
    if c:
        out.append("<section><h2>Trafic jour par jour</h2>%s</section>" % c)
    if intercale:
        out.append(intercale)
    trio = "".join([
        _barres("Pays", a.get("pays") or []),
        _barres("Appareils", a.get("appareils") or []),
        _barres("Provenance", a.get("referrers") or []),
    ])
    if trio:
        out.append("<div class='trio'>%s</div>" % trio)
    return "".join(out)


def _palmares(rangs: list, jeton: str) -> str:
    """Les huit liens qui portent le trafic, classes.

    Le tableau complet dit tout mais ne HIERARCHISE rien : sur trente lignes,
    on ne voit pas qui tire. C est la question de la vue d ensemble.
    """
    if not rangs:
        return ""
    lignes = []
    for i, r in enumerate(rangs[:8]):
        lignes.append(
            "<div class='li%s'><span class='r'>%d</span>"
            "<span class='n'>%s</span><span class='c'>%s</span>"
            "<span class='ab'>%s</span></div>"
            % (" podium" if i < 3 else "", i + 1,
               html.escape(str(r.get("lien") or "")),
               _num(r.get("clics")),
               ("%s abonné%s" % (_num(r.get("abonnes")),
                                 "s" if int(r.get("abonnes") or 0) > 1 else ""))
               if r.get("abonnes") else "—"))
    tout = ("<a class='tout' href='%s/%s/liens'>Tout voir</a>"
            % (RACINE, html.escape(str(jeton)))) if jeton else ""
    return ("<section><h2>Top liens%s</h2><div class='top'>%s</div></section>"
            % (tout, "".join(lignes)))


def _rangs(d: dict) -> list:
    """Clics et abonnes de la quinzaine, par lien, du plus fort au plus faible."""
    ab = {str(r.get("lien") or ""): r for r in (d.get("abonnes") or [])}
    out = []
    for r in (d.get("par_lien") or []):
        nom = str(r.get("lien") or "")
        per = r.get("periodes") or []
        # La quinzaine, pas aujourd hui : un classement sur une seule journee
        # change tous les matins et ne dit rien de qui travaille.
        v = per[2] if len(per) > 2 else None
        clics = 0
        if isinstance(v, dict):
            clics = v.get("marche")
            if clics is None:
                clics = v.get("total") or 0
        out.append({"lien": nom, "clics": int(clics or 0),
                    "abonnes": int((ab.get(nom) or {}).get("quinz") or 0)})
    out.sort(key=lambda r: (-r["clics"], -r["abonnes"]))
    return [r for r in out if r["clics"] or r["abonnes"]]


def _onglets(jeton: str, vue: str) -> str:
    """Deux liens, aucun script. Le lien de la vue courante reste cliquable :
    le desactiver casserait le rafraichissement d une page ouverte."""
    if not jeton:
        return ""
    j = html.escape(str(jeton))
    return ("<nav class='onglets'>"
            "<a class='%s' href='%s/%s'>Vue d’ensemble</a>"
            "<a class='%s' href='%s/%s/liens'>Liens</a></nav>"
            % ("on" if vue != "liens" else "", RACINE, j,
               "on" if vue == "liens" else "", RACINE, j))


def _page_donnees(titre: str, sous: str, d: dict, quand: str,
                  jeton: str = "", vue: str = "ensemble") -> str:
    """La page, batie sur les DONNEES et non sur du texte deja mis en forme.

    Rejouer un tableau a chasse fixe en HTML demanderait de le reanalyser,
    c'est-a-dire de dependre de la largeur des colonnes choisie pour Discord.
    Le report porte donc ses lignes brutes (`donnees_clics`) : Discord les
    ignore, cette page les met en forme.
    """
    dr = d.get("drapeau") or "🌍"
    corps = []
    ensemble = (vue != "liens")

    # --- Le resume, en cartes -------------------------------------------
    cartes = []
    for i, r in enumerate(d.get("resume") or []):
        m, t = r.get("marche"), r.get("total")
        val = _num(m if m is not None else t)
        sous_l = ("🌍 %s" % _num(t)) if m is not None else ""
        cartes.append(
            "<div class='carte%s'><div class='q'>%s</div>"
            "<div class='v'>%s %s</div><div class='s'>%s</div></div>"
            % (" forte" if i == 0 else "", html.escape(str(r.get("quand") or "")),
               dr if m is not None else "🌍", val, sous_l))
    if cartes and ensemble:
        corps.append("<div class='cartes'>%s</div>" % "".join(cartes))

    if ensemble:
        # L'audience vient de GetMySocial, pas du report : elle repond a une
        # autre question — d'ou vient le trafic, et converti-t-il — la ou le
        # report dit qui a clique.
        # Le palmares est INTERCALE dans l audience, entre la courbe et les
        # trois listes : place a la suite, il tombait sous « Provenance »,
        # loin de la question qu il eclaire.
        corps.append(_audience(d.get("audience") or {},
                               _palmares(_rangs(d), jeton)))

    # --- UNE SEULE TABLE : clics ET abonnes, par lien --------------------
    #
    # Les deux etaient dans deux tableaux separes, l'un sous l'autre. On
    # lisait « 1090 clics » quinze lignes plus haut que « 7 abonnes » sans
    # jamais les rapprocher — alors que la question est justement celle-la :
    # ce trafic convertit-il ? Sur une meme ligne, la reponse se voit.
    #
    # « Hier » a saute : deux informations demandees, aujourd'hui et les deux
    # quinzaines. Une colonne de plus ne se lit pas sur un telephone.
    ab = {str(r.get("lien") or ""): r for r in (d.get("abonnes") or [])}
    pl = d.get("par_lien") or []
    if (pl or ab) and not ensemble:
        avec_marche = any(p.get("marche") is not None
                          for r in pl for p in (r.get("periodes") or []))

        # L'ordre vient des clics (tous les liens y sont) ; un lien qui
        # n'aurait que des abonnes est ajoute a la fin plutot qu'oublie.
        clics = {str(r.get("lien") or ""): (r.get("periodes") or []) for r in pl}
        # ORDRE ALPHABETIQUE, sur la liste FUSIONNEE. Reprendre l'ordre des
        # clics puis coller les autres a la fin remettait exactement le
        # defaut qu'on venait de corriger : quelqu'un qu'on cherche n'est pas
        # ou on l'attend. La parenthese de tete est ignoree, comme ailleurs.
        # LA MEME CLE QUE LE REPORT, importee et non recopiee : « VA 10 »
        # doit se ranger apres « VA 2 » des deux cotes, et deux copies d'une
        # regle de tri finissent toujours par diverger d'un caractere.
        try:
            from cogs.clickrecap import _cle_tri
        except Exception:
            def _cle_tri(n):
                return (str(n or "").lower(),)
        noms = sorted(set(clics) | set(ab), key=_cle_tri)

        lignes = []
        for nom in noms:
            per = clics.get(nom) or []
            a = ab.get(nom) or {}

            def _clic(k):
                """Le clic d'une periode : le marche s'il existe, sinon le total."""
                if k >= len(per):
                    return None
                v = per[k]
                return v.get("marche") if avec_marche and v.get("marche") is not None \
                    else v.get("total")

            lignes.append(
                "<tr><td>%s</td>%s%s%s%s%s%s</tr>"
                % (html.escape(nom),
                   _case(_clic(0)), _case(a.get("auj")),
                   _case(_clic(2), doux=True), _case(a.get("quinz")),
                   _case(a.get("prec"), doux=True),
                   _evolution(a.get("quinz"), a.get("prec"))))

        coiffe = ("<tr><th></th>"
                  "<th class='grp' colspan='2'>Aujourd'hui</th>"
                  "<th class='grp gr' colspan='2'>Quinzaine</th>"
                  "<th class='grp gr' colspan='2'>Précédente</th></tr>")
        ent = [("Lien", False), ("Clics", False), ("Abonnés", False),
               ("Clics", True), ("Abonnés", False),
               ("Abonnés", True), ("Évol.", False)]
        corps.append(
            "<section><h2>Par lien — %s vs %s</h2>%s</section>"
            % (html.escape(str(d.get("quinzaine") or "quinzaine")),
               html.escape(str(d.get("precedente") or "précédente")),
               _table(ent, lignes, coiffe)))

    return _enveloppe(titre, sous, "".join(corps), quand, jeton, vue)


def _enveloppe(titre: str, sous: str, corps: str, quand: str,
               jeton: str = "", vue: str = "ensemble") -> str:
    """Le HTML autour. Aucun script, et aucun lien SORTANT : les deux seuls
    liens de la page menent a ses propres vues."""
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        # Pas d'indexation : l'adresse se transmet, elle ne se cherche pas.
        "<meta name='robots' content='noindex,nofollow'>"
        "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
        "<header><h1>%s</h1><span class='tag'>lecture seule</span></header>"
        "<p class='sous'>%s</p>%s%s"
        "<div class='pied'>Mis à jour %s</div>"
        "</div></body></html>"
        % (html.escape(titre), _CSS, html.escape(titre), html.escape(sous),
           _onglets(jeton, vue), corps, html.escape(quand))
    )


def _page(titre: str, sous: str, blocs: list, quand: str) -> str:
    """Repli : le texte du report tel quel.

    Sert quand le report ne porte pas ses donnees structurees — une version
    plus ancienne, ou un chemin qu'on n'a pas prevu. Moins beau, mais JUSTE :
    mieux vaut un tableau a chasse fixe que rien.
    """
    corps = []
    for nom, valeur, brut in blocs:
        contenu = (("<pre style='margin:0;overflow-x:auto;font:12px/1.45 "
                    "ui-monospace,Menlo,Consolas,monospace;color:#d7dbe8;"
                    "white-space:pre;padding:0 18px 14px'>%s</pre>"
                    % html.escape(valeur)) if brut
                   else ("<div style='padding:0 18px 14px;line-height:1.9'>%s</div>"
                         % valeur))
        entete = ("<h2>%s</h2>" % html.escape(nom)) if nom.strip() else ""
        corps.append("<section>%s%s</section>" % (entete, contenu))
    return _enveloppe(titre, sous, "".join(corps), quand)


def register(app, deps):
    """Branche `/clics/<jeton>`.

    `deps` doit fournir :
        construire(cle, portee) -> embed | None   le MEME report que Discord.
        `portee` est None pour un report configure, ou le descripteur d'un
        espace GetMySocial.
    """
    from flask import Response

    construire = deps["construire"]

    def _rendre(jeton, vue):
        d = _charger().get(str(jeton or ""))
        if not isinstance(d, dict):
            # 404 et pas 403 : un jeton faux ne doit pas apprendre a celui
            # qui l'essaie qu'il a « presque » trouve quelque chose.
            return Response("Page introuvable.", status=404,
                            mimetype="text/plain; charset=utf-8")

        cle = str(d.get("cle") or "")
        portee = d.get("portee") if isinstance(d.get("portee"), dict) else None
        hit = _CACHE.get((cle, vue))
        if hit and (time.time() - hit[0]) < TTL_RENDU:
            _noter_vue(jeton)
            return Response(hit[1], mimetype="text/html; charset=utf-8")

        # `construire` rend (embed, donnees) — les donnees ne peuvent pas
        # voyager sur l'embed, discord.Embed declare __slots__.
        emb, _d = None, None
        try:
            r = construire(cle, portee)
            if isinstance(r, tuple):
                emb, _d = r
            else:
                emb = r
        except Exception as e:                       # noqa: BLE001
            emb = None
            print("[clics-portail] %s: %s" % (type(e).__name__, e), flush=True)
        if emb is None:
            # ON NE MONTRE PAS DE ZEROS. Une source injoignable rend un
            # tableau vide, qui se lit « personne n'a rien fait » — c'est
            # faux, et c'est pire que pas de page du tout.
            return Response(
                _page("Rapport indisponible",
                      "La source n'a pas répondu. Réessaie dans quelques minutes.",
                      [], time.strftime("%d/%m %H:%M")),
                status=503, mimetype="text/html; charset=utf-8")

        # LES DONNEES D'ABORD. Le texte du report reste en repli : mieux
        # vaut un tableau a chasse fixe que pas de page.
        if isinstance(_d, dict) and (_d.get("resume") or _d.get("abonnes")):
            page = _page_donnees(str(emb.title or "Clics"),
                                 str(emb.description or "").replace("**", ""),
                                 _d, time.strftime("%d/%m %H:%M"),
                                 str(jeton), vue)
            _CACHE[(cle, vue)] = (time.time(), page)
            _noter_vue(jeton)
            return Response(page, mimetype="text/html; charset=utf-8")

        blocs = []
        for f in (emb.fields or []):
            v = str(f.value or "")
            brut = v.startswith("```")
            if brut:
                v = v.strip("`").strip("\n")
            else:
                # Le resume arrive en Markdown Discord : on rend le gras et
                # le code, le reste part en texte echappe.
                v = html.escape(v)
                v = v.replace("**", "<b>", 1)
                while "**" in v:
                    v = v.replace("**", "</b>", 1)
                    if "**" in v:
                        v = v.replace("**", "<b>", 1)
                v = v.replace("`", "").replace("\n", "<br>")
            blocs.append((str(f.name or "").strip("​"), v, brut))

        page = _page(str(emb.title or "Clics"),
                     str(emb.description or "").replace("**", ""),
                     blocs, time.strftime("%d/%m %H:%M"))
        _CACHE[(cle, vue)] = (time.time(), page)
        _noter_vue(jeton)
        return Response(page, mimetype="text/html; charset=utf-8")


    @app.route(RACINE + "/<jeton>")
    def clics_portail_page(jeton):
        return _rendre(jeton, "ensemble")

    @app.route(RACINE + "/<jeton>/liens")
    def clics_portail_liens(jeton):
        return _rendre(jeton, "liens")
