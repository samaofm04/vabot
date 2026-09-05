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
*{box-sizing:border-box}
body{margin:0;background:#0a0d14;color:#e7eaf3;-webkit-font-smoothing:antialiased;
     font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:26px 18px 64px}
header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:22px;font-weight:700;margin:0;letter-spacing:-.01em}
.tag{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
     color:#7c8398;background:#161a25;border:1px solid #232936;
     border-radius:999px;padding:3px 10px}
.sous{color:#7c8398;font-size:13px;margin:0 0 22px}

/* Le resume : une carte par periode, le chiffre d'abord. */
.cartes{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
        margin-bottom:22px}
.carte{background:#121722;border:1px solid #1f2634;border-radius:13px;padding:13px 15px}
.carte .q{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;
          color:#7c8398;font-weight:700;margin-bottom:7px}
.carte .v{font-size:23px;font-weight:750;letter-spacing:-.02em;line-height:1.1}
.carte .s{font-size:12px;color:#7c8398;margin-top:3px}
.carte.forte{border-color:#31507a;
  background:linear-gradient(180deg,#16233a,#121722)}
.carte.forte .v{color:#7fb2ff}

/* L'EVOLUTION EST LE POINT DU TABLEAU. Deux quinzaines cote a cote ne
   disent rien tant qu'on doit soustraire de tete : la fleche le fait. */
.ev{font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums}
.ev.up{color:#34d399}
.ev.dn{color:#f87171}
.ev.eq{color:#4c5468;font-weight:400}
/* Un en-tete qui coiffe deux colonnes : sans lui, « us » et « 🌍 » se
   suivent sans qu'on sache a quelle periode ils appartiennent. */
th.grp{text-align:center;color:#8891a8;border-bottom:1px solid #232936;
       padding-bottom:5px;font-size:10px}
th.sub{padding-top:4px;font-size:9.5px;color:#5f6779}
tr.tetes2 th{border-bottom:1px solid #1f2634}

section{background:#121722;border:1px solid #1f2634;border-radius:14px;
        padding:4px 0 6px;margin-bottom:18px;overflow:hidden}
section>h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;
           color:#7c8398;margin:0;padding:14px 18px 10px;font-weight:700}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:9px 14px;text-align:right;white-space:nowrap}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#6d7488;
   font-weight:700;border-bottom:1px solid #1f2634}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;
   background:#121722;font-weight:600}
tbody tr:nth-child(even) td{background:#141926}
tbody tr:nth-child(even) td:first-child{background:#141926}
tbody tr:hover td{background:#1a2130}
tbody tr:hover td:first-child{background:#1a2130}
td.n{font-variant-numeric:tabular-nums;font-weight:650}
td.z{color:#4c5468;font-weight:400}          /* un zero ne doit pas crier */
td.g{color:#7c8398;font-weight:500}          /* la colonne globale, en retrait */
.gr{border-left:1px solid #1f2634}
.pied{color:#525a6e;font-size:11.5px;text-align:center;margin-top:26px;line-height:1.7}
@media(max-width:620px){
  .wrap{padding:16px 10px 44px}h1{font-size:18px}
  th,td{padding:8px 10px;font-size:12.5px}
  .carte .v{font-size:20px}
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


def _page_donnees(titre: str, sous: str, d: dict, quand: str) -> str:
    """La page, batie sur les DONNEES et non sur du texte deja mis en forme.

    Rejouer un tableau a chasse fixe en HTML demanderait de le reanalyser,
    c'est-a-dire de dependre de la largeur des colonnes choisie pour Discord.
    Le report porte donc ses lignes brutes (`donnees_clics`) : Discord les
    ignore, cette page les met en forme.
    """
    dr = d.get("drapeau") or "🌍"
    corps = []

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
    if cartes:
        corps.append("<div class='cartes'>%s</div>" % "".join(cartes))

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
    if pl or ab:
        avec_marche = any(p.get("marche") is not None
                          for r in pl for p in (r.get("periodes") or []))

        # L'ordre vient des clics (tous les liens y sont) ; un lien qui
        # n'aurait que des abonnes est ajoute a la fin plutot qu'oublie.
        clics = {str(r.get("lien") or ""): (r.get("periodes") or []) for r in pl}
        # ORDRE ALPHABETIQUE, sur la liste FUSIONNEE. Reprendre l'ordre des
        # clics puis coller les autres a la fin remettait exactement le
        # defaut qu'on venait de corriger : quelqu'un qu'on cherche n'est pas
        # ou on l'attend. La parenthese de tete est ignoree, comme ailleurs.
        _tri = lambda t: re.sub(r"^[^0-9A-Za-z]+", "", str(t)).lower()
        noms = sorted(set(clics) | set(ab), key=_tri)

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

    return _enveloppe(titre, sous, "".join(corps), quand)


def _enveloppe(titre: str, sous: str, corps: str, quand: str) -> str:
    """Le HTML autour. Aucun script, aucun lien sortant : rien a cliquer."""
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        # Pas d'indexation : l'adresse se transmet, elle ne se cherche pas.
        "<meta name='robots' content='noindex,nofollow'>"
        "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
        "<header><h1>%s</h1><span class='tag'>lecture seule</span></header>"
        "<p class='sous'>%s</p>%s"
        "<div class='pied'>Mis à jour %s</div>"
        "</div></body></html>"
        % (html.escape(titre), _CSS, html.escape(titre), html.escape(sous),
           corps, html.escape(quand))
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

    @app.route(RACINE + "/<jeton>")
    def clics_portail_page(jeton):
        d = _charger().get(str(jeton or ""))
        if not isinstance(d, dict):
            # 404 et pas 403 : un jeton faux ne doit pas apprendre a celui
            # qui l'essaie qu'il a « presque » trouve quelque chose.
            return Response("Page introuvable.", status=404,
                            mimetype="text/plain; charset=utf-8")

        cle = str(d.get("cle") or "")
        portee = d.get("portee") if isinstance(d.get("portee"), dict) else None
        hit = _CACHE.get(cle)
        if hit and (time.time() - hit[0]) < TTL_RENDU:
            _noter_vue(jeton)
            return Response(hit[1], mimetype="text/html; charset=utf-8")

        try:
            emb = construire(cle, portee)
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
        _d = getattr(emb, "donnees_clics", None)
        if isinstance(_d, dict) and (_d.get("resume") or _d.get("abonnes")):
            page = _page_donnees(str(emb.title or "Clics"),
                                 str(emb.description or "").replace("**", ""),
                                 _d, time.strftime("%d/%m %H:%M"))
            _CACHE[cle] = (time.time(), page)
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
        _CACHE[cle] = (time.time(), page)
        _noter_vue(jeton)
        return Response(page, mimetype="text/html; charset=utf-8")
