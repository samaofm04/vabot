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
body{margin:0;background:#0b0e15;color:#e8eaf2;
     font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:19px;margin:0 0 4px}
.sous{color:#8a91a8;font-size:12.5px;margin:0 0 18px}
.bloc{background:#12151f;border:1px solid #1e2430;border-radius:12px;
      padding:14px 16px;margin-bottom:14px}
.bloc h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;
         color:#8a91a8;margin:0 0 10px;font-weight:700}
pre{margin:0;overflow-x:auto;font:12px/1.45 ui-monospace,SFMono-Regular,
    Menlo,Consolas,monospace;color:#d7dbe8;white-space:pre}
.res{font-size:14px;line-height:1.9}
.res b{color:#fff}
.pied{color:#5c6479;font-size:11.5px;text-align:center;margin-top:24px}
@media(max-width:600px){pre{font-size:10.5px}.wrap{padding:14px 10px 40px}}
"""


def _page(titre: str, sous: str, blocs: list, quand: str) -> str:
    """Le HTML complet. Aucun script, aucun lien sortant : rien a cliquer."""
    corps = []
    for nom, valeur, brut in blocs:
        contenu = (("<pre>%s</pre>" % html.escape(valeur)) if brut
                   else ("<div class='res'>%s</div>" % valeur))
        entete = ("<h2>%s</h2>" % html.escape(nom)) if nom.strip() else ""
        corps.append("<div class='bloc'>%s%s</div>" % (entete, contenu))
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        # Pas d'indexation : l'adresse se transmet, elle ne se cherche pas.
        "<meta name='robots' content='noindex,nofollow'>"
        "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
        "<h1>%s</h1><p class='sous'>%s</p>%s"
        "<div class='pied'>Mis à jour %s · lecture seule</div>"
        "</div></body></html>"
        % (html.escape(titre), _CSS, html.escape(titre), html.escape(sous),
           "".join(corps), html.escape(quand))
    )


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
