# -*- coding: utf-8 -*-
"""Report de fin de journee, par fiche VA : ou en est son telephone.

Chaque nuit a 1 h (Paris), ce cog poste dans le salon configure un message
par fiche VA :

    Report du 30/08 · @jessye
    x/30 = comptes qui tournent. OK = objectif tenu.

    OK  VA NOUM 1X1 · 39 comptes · 26/30 · pas d oubli
    KO  VA NOUM 1X2 · 12 comptes ·  4/30 · 8 oublis

Puis il tient a jour le BILAN DU MOIS, epingle : une ligne par fiche, le
pseudo Discord a payer, et le mois entier jour par jour en carres, coupe par
une barre entre les deux quinzaines de paie.

    VA NOUM 1X1 @noum0075 · 1–15 : 13/14 · 16–fin : 12/15 · 26/30
    01/08 ..........#..#.┃...#....#..#... 31/08

Il part en EMBED, et pas par coquetterie : un message ordinaire plafonne a
2000 unites, un embed a 4096. C'est ce qui permet de tenir vingt-deux fiches
et un mois de carres dans UN SEUL message — un bilan coupe en deux se lit
comme un bilan incomplet, et on cherche les VAs manquants.

Attention en mesurant : Discord compte en UTF-16, donc un carre colore vaut
DEUX unites. Compter en caracteres Python faisait fabriquer des messages
refuses a l'envoi, dont l'erreur partait dans un journal que personne ne lit.

DEUX SALONS, DEUX CONVENTIONS DE NOM :

    report-compte*     le report du jour
    report-quinzaine*  le bilan, s'il existe — sinon il reste avec le jour

Les deux ne se lisent pas au meme moment ni pour la meme raison : l'un le
matin pour voir qui a decroche, l'autre au moment de payer. Laisses ensemble,
le bilan descend sous quinze jours de reports et l'epingle ne se retrouve
plus. Le suffixe restreint la portee : « report-compte-jessye » ne suit que
jessye.

**Aucune commande slash, et c'est contraint.** Discord plafonne une
APPLICATION a 100 commandes globales, et ce bot y est deja : quatre cogs
(vaactivity, vasort, tgrouter, numeros) ne se chargent plus depuis un
moment, en silence, pour cette raison — leurs commandes n'existent plus sur
Discord. En ajouter trois faisait echouer celui-ci exactement pareil.

Le report n'en a pas besoin : il tourne seul chaque nuit. Le salon se
trouve par CONVENTION DE NOM (voir plus haut). On cree le salon, il est
servi. Le declenchement manuel vit sur le tableau de bord, bouton « Report
des comptes ».

Trois autres choses valent d'etre dites, parce qu'elles ne se devinent pas :

**Le calcul n'est pas ici.** Il vit dans `jb_objectifs`, et le tableau de bord
appelle la meme fonction. Deux facons de compter « les comptes actifs »
finiraient par se contredire, et ce desaccord ne se remarque que le jour ou
quelqu'un conteste une retenue de paie.

**Ce cog ne scrape RIEN.** Il lit le cache des stats, celui que le scrape
automatique remplit a 00 h et 12 h. D'ou l'heure de publication : 1 h, pas
minuit. Cloturer a 00 h 05 revenait a juger la journee sur les chiffres de
midi — un compte publie le soir aurait ete compte « oublie », et son VA paye
la-dessus.

**Un report manque n'est pas une journee ratee.** Le bilan de quinzaine
compte les journees TENUES sur les journees NOTEES : si le bot etait a
l'arret a minuit, la journee n'existe pas, elle ne compte ni en bien ni en
mal. Sans ca, la premiere coupure de service transformait un bon VA en
mauvais.

**Le message epingle est reecrit, jamais reposte.** Un bilan qui s'empile
chaque nuit devient illisible en une semaine, et l'epingle ne designe plus
rien.
"""
import asyncio
import calendar
import datetime
import json
import re
import pathlib
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import safe_json

_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "report_comptes.json"

#: Longueur maxi d'un message, EN UNITES DISCORD (voir _taille).
_MAX_MSG = 1850

#: Longueur maxi de la DESCRIPTION d'un embed. Discord y accepte 4096 unités,
#: contre 2000 pour un message ordinaire — c'est ce qui permet de tenir tout
#: le bilan dans UN SEUL message, comme demandé : « je veux qu'en un morceau
#: il y ait tous les VA ». Avec vingt-deux fiches et un mois de carrés
#: chacune, un message ordinaire en demandait deux, et un bilan coupé en deux
#: se lit comme un bilan incomplet.
#:
#: Marge volontaire sous les 4096 : le nombre de fiches grandit, et déborder
#: fait refuser le message ENTIER par Discord.
#: 850, alors que Discord annonce 4096 pour une description d'embed.
#:
#: Ce chiffre n'est pas theorique, il est MESURE. Le bot a envoye trois
#: messages — 8 fiches/1337u, 8 fiches/1306u, 5 fiches/923u — et Discord n'a
#: affiche que 6, 6 et 5 fiches. Celui de 923 unites est passe ENTIER ; les
#: deux de ~1320 ont perdu leurs deux dernieres fiches chacun. La coupe se
#: situe donc autour de 1100, tres loin des 4096 annonces, et elle est
#: SILENCIEUSE : le message part, Discord repond 200, et deux VAs manquent au
#: bilan de paie.
#:
#: On se tient donc sous la seule taille dont on a la preuve qu'elle passe. Le
#: proprietaire a dit « fais plusieurs trucs s'il le faut » : mieux vaut cinq
#: messages complets que trois amputes.
_MAX_EMBED = 850


def _taille(txt: str) -> int:
    """La longueur d'un texte TELLE QUE DISCORD LA COMPTE.

    Discord plafonne un message a 2000 unites UTF-16, pas a 2000 caracteres
    Python. Un carre colore (🟥, hors du plan de base) compte donc pour DEUX.

    Ca n'a rien d'academique : avec trente et un carres par fiche, un bloc de
    vingt fiches faisait 1700 « caracteres » pour Python et 2340 pour Discord.
    Les gros morceaux etaient donc REFUSES a l'envoi, l'erreur partait dans un
    journal que personne ne lit, et seul le dernier petit morceau arrivait. On
    lisait quatre fiches sur vingt et on croyait a un bug de calcul.
    """
    return len(str(txt or "").encode("utf-16-le")) // 2

#: Les deux conventions de nom. Le report du jour et le bilan de quinzaine ne
#: se lisent pas au meme moment ni pour la meme raison : l'un se regarde le
#: matin pour savoir qui a decroche, l'autre au moment de payer. Les laisser
#: dans le meme salon, c'est un bilan qui descend sous quinze jours de reports
#: et une epingle que plus personne ne retrouve.
#:
#: Si aucun salon de quinzaine n'existe, le bilan reste dans le salon du jour :
#: separer est une possibilite, pas une obligation, et personne ne doit se
#: retrouver sans bilan pour avoir omis de creer un salon.
#: Plusieurs noms acceptes par role, parce que le proprietaire nomme ses
#: salons comme il les pense — « report-day » lui vient plus naturellement que
#: « report-compte ». Une seule liste par role : ce sont des synonymes, pas
#: deux comportements.
PREFIXES_JOUR = ("report-compte", "report-day", "report-jour", "report-quotidien")
PREFIXES_MOIS = ("report-quinzaine", "report-mois", "report-du-mois",
                 "report-month", "report-paie")
#: Gardes pour le code qui n'en veut qu'un (l'analyse du suffixe d'identite).
PREFIXE_JOUR = PREFIXES_JOUR[0]
PREFIXE_QUINZAINE = PREFIXES_MOIS[0]

#: L'heure (Paris) a laquelle la journee de la veille est clôturée. Une heure
#: apres minuit, pas a minuit : le scrape automatique des stats tourne a 00 h,
#: et ce report LIT ce que le scrape ecrit. Cloturer a 00 h 05 revenait a juger
#: la journee sur les chiffres de midi.
HEURE_REPORT = 1

#: Version de mise en forme du bilan. A INCREMENTER des qu'on change son
#: apparence : le message epingle est REECRIT, jamais repose, donc un
#: changement de format ne se voyait qu'a la publication suivante — et on
#: attendait 1 h du matin en croyant que ca ne marchait pas. Quand le numero
#: stocke ne correspond plus, la boucle republie une fois, tout de suite.
FORMAT_BILAN = 16


# ==============================================================================
# Heure de Paris — recopiee de clickrecap : meme besoin, meme methode, et le
# projet tourne sans zoneinfo garanti sur toutes les machines.
# ==============================================================================

def _last_sunday(year: int, month: int) -> int:
    return max(d for d in range(25, 32)
               if datetime.date(year, month, d).weekday() == 6)


def _paris_now() -> datetime.datetime:
    """Heure locale de Paris calculee depuis l'UTC (CET=+1, CEST=+2)."""
    u = datetime.datetime.utcnow()
    y = u.year
    debut = datetime.datetime(y, 3, _last_sunday(y, 3), 1)
    fin = datetime.datetime(y, 10, _last_sunday(y, 10), 1)
    return u + datetime.timedelta(hours=2 if (debut <= u < fin) else 1)


# ==============================================================================
# Configuration : quel salon, sur quel serveur
# ==============================================================================

def _cle(guild_id, channel_id) -> str:
    """Un report par SALON, pas un par serveur.

    Meme choix que le report de clics : le proprietaire peut vouloir un salon
    par marche ou par equipe sur un meme serveur.
    """
    return "%s:%s" % (guild_id, channel_id)


def _load_cfg() -> dict:
    d = safe_json.load(_CFG_FILE, default={})
    return d if isinstance(d, dict) else {}


def _save_cfg(d: dict) -> bool:
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        return bool(safe_json.write(_CFG_FILE, d))
    except Exception:
        return False


def _reports_configures(cfg: dict) -> list:
    return [(str(k), c) for k, c in (cfg or {}).items()
            if isinstance(c, dict) and c.get("channel_id")]


# ==============================================================================
# Mise en forme
# ==============================================================================

def _barre(actifs: int, objectif: int, largeur: int = 10) -> str:
    """Une barre de progression en carres. Plafonnee a l'objectif : depasser
    n'allonge pas la barre, ca se lit sur le chiffre."""
    if objectif <= 0:
        return ""
    plein = max(0, min(largeur, round(largeur * actifs / objectif)))
    return "▰" * plein + "▱" * (largeur - plein)


def ligne_fiche(e: dict) -> str:
    """UNE ligne par fiche. Volontairement court.

    La premiere version faisait cinq lignes par VA, avec les pourcentages, la
    barre de progression et la phrase qui explique combien il manque. Sur
    vingt-quatre fiches ca donnait un mur que personne ne lit — et le
    proprietaire l'a dit tout net : « je veux pas un truc si complet ».

    Trois faits, dans l'ordre ou il les a dictes : combien de comptes en tout,
    combien tournent sur l'objectif, combien d'oublis. Le detail (warm-up,
    bannis, ajouts du jour, pourcentages) reste calcule et enregistre — il vit
    sur la fiche du tableau de bord, pas dans un message qu'on lit d'un coup
    d'oeil le matin.
    """
    marque = "✅" if e["atteint"] else "🔴"
    oublis = (f"{e['oublies']} oubli" + ("s" if e["oublies"] > 1 else "")
              if e["oublies"] else "pas d'oubli")
    return (f"{marque} **{e['va']}** · {e['total']} comptes · "
            f"**{e['actifs']}/{e['objectif']}** · {oublis}")


def bloc_jour(etats: list, jour: str, identite: str = "") -> list:
    """Le report du jour, en UN message — ou plusieurs si Discord refuse.

    Un message par fiche faisait vingt-quatre notifications d'affilee chaque
    nuit. Une seule liste se lit d'un coup et ne noie pas le salon.

    La legende est ecrite UNE fois en tete, pas repetee sur chaque ligne : sans
    elle, « 16/30 » ne dit pas de quoi on parle ; repetee vingt-quatre fois,
    elle redevient le mur qu'on vient d'enlever.
    """
    def _d(j):
        try:
            return datetime.date.fromisoformat(j).strftime("%d/%m")
        except Exception:
            return j
    portee = f" · `@{identite}`" if identite else ""
    tete = [f"📊 **Report du {_d(jour)}**{portee}",
            "_x/30 = comptes qui tournent (ont publié sous 48 h, ou créés il y "
            "a peu). ✅ = objectif tenu._", ""]
    if not etats:
        return ["\n".join(tete + ["_Aucune fiche à suivre._"])]
    # Meme ordre que le site, demande explicitement. On a d'abord trie du pire
    # au meilleur — plus efficace pour reperer qui decroche, mais on perdait la
    # correspondance ligne a ligne avec l'ecran qu'on a sous les yeux, et c'est
    # elle qui compte quand on passe de l'un a l'autre. La pastille rouge
    # suffit a reperer les fiches en peine.
    messages, bloc = [], list(tete)
    for e in etats:
        ligne = ligne_fiche(e)
        # On coupe AVANT de depasser, et chaque morceau reprend la legende :
        # un deuxieme message sans en-tete est une liste de chiffres nus.
        if sum(_taille(x) + 1 for x in bloc) + _taille(ligne) > _MAX_MSG:
            messages.append("\n".join(bloc))
            bloc = list(tete)
        bloc.append(ligne)
    messages.append("\n".join(bloc))
    return messages


#: Un carré par jour. « inconnu » n'est ni vert ni rouge : une nuit où le
#: report n'a pas tourné n'est pas une faute du VA, et la payer comme telle
#: serait une erreur qu'on ne pourrait pas lui défendre.
#:
#: Sombre plutôt que blanc — demandé, et meilleur : le blanc SAUTE aux yeux
#: dans un salon sombre, si bien qu'une quinzaine à peine commencée avait
#: l'air d'un mur d'échecs. Le carré sombre se lit « rien », ce qu'il est.
#: Deux couleurs, pas trois : demande, et redemande. Le carre sombre du
#: « pas de report cette nuit-la » disparait, il devient rouge.
#:
#: Ce que ca coute, et c'est dit dans la legende du message pour que personne
#: ne le lise de travers : une nuit ou le bot n'a pas tourne s'affiche
#: desormais comme une journee non tenue, alors que le VA n'y est pour rien.
#: Le COMPTE, lui, reste honnete — `jours_notes` ne compte que les journees
#: reellement mesurees, donc le score « 12/14 » ne bouge pas. Seule la bande
#: est rouge.
# Reconnait une ligne de fiche, et seulement elle : « <carre> **<nom>**
# ... · 9/30 ». Le titre du bilan lui ressemble (emoji puis gras) mais ne
# se termine pas par deux nombres separes d'une barre.
#: Deux retours a la ligne. Ecrit ainsi parce que les antislash ne
#: survivent pas toujours aux outils qui editent ce fichier.
_SAUT = chr(10) + chr(10)
_LIGNE_FICHE = re.compile(r"^\S+ \*\*.+?\*\*.*\d+/\d+$", re.M)

_CARRES = {"tenu": "🟩", "moyen": "🟠", "rate": "🟥", "inconnu": "🟥"}


def suite_jours(suite, debut: str = "", coupure: int = 0) -> str:
    """La quinzaine jour par jour, en carrés, encadrée par ses dates.

    Un total « 12/14 » ne dit pas s'il a lâché trois jours d'affilée ou un
    jour de temps en temps — et ce n'est pas la même conversation au moment
    de payer.

    La bande commence toujours au 1er du mois, et l'en-tête du message donne
    la période : c'est ce qui permet de dire « tu as lâché le 19 » sans avoir
    à répéter les dates sur chaque ligne.
    """
    suite = list(suite or [])
    if not suite:
        return ""
    if coupure and 0 < coupure < len(suite):
        # La barre marque la frontiere des deux quinzaines de paie. Sans elle,
        # trente et un carres a la file ne disent pas ou s'arrete la periode
        # qu'on solde.
        bande = ("".join(_CARRES.get(x, "⬛") for x in suite[:coupure])
                 + "┃" + "".join(_CARRES.get(x, "⬛") for x in suite[coupure:]))
    else:
        bande = "".join(_CARRES.get(x, "⬛") for x in suite)
    # PAS de dates autour de la bande. Elles y ont ete un temps, et sur un
    # panneau Discord etroit elles cassaient la ligne en trois : la date seule,
    # les carres, la date seule. Un mur gris illisible. L'en-tete du message
    # donne deja la periode, et la bande commence toujours au 1er : compter
    # est immediat, et la ligne tient.
    return bande


def bloc_quinzaine(lignes: list, debut: str, fin: str, identite: str = "",
                   ecartees=None) -> list:
    """Le bilan du MOIS, une fiche par bloc, dans l'ordre du site.

    Rend une LISTE de messages. Un mois de carrés pour vingt-quatre fiches
    dépasse largement les deux mille caractères de Discord : la version
    précédente rendait un seul texte, qu'on tronquait — donc des VAs
    disparaissaient du bilan de paie sans un mot. On découpe, et chaque
    morceau reprend l'en-tête.

    L'ordre est celui de l'écran Social Analytics, pas un classement : on
    passe de l'un à l'autre en permanence, et deux ordres différents obligent
    à chercher la ligne au lieu de la lire.
    """
    def _d(j):
        try:
            return datetime.date.fromisoformat(j).strftime("%d/%m")
        except Exception:
            return j
    portee = f" · `@{identite}`" if identite else ""
    tete = [f"📌 **Bilan du mois — du {_d(debut)} au {_d(fin)}**{portee}",
            "_Un carré par jour : 🟩 objectif tenu · 🟠 à mi-chemin (50 % au "
            "moins) · 🟥 loin du compte — ou pas de report cette nuit-là, "
            "auquel cas ça ne compte pas dans le score._",
            "_Une journée est tenue quand la fiche atteint 80 % de son "
            "objectif. La barre ┃ sépare les deux quinzaines de paie._",
            ""]
    if not lignes:
        return ["\n".join(tete + ["_Aucune fiche suivie pour l'instant._"])]
    # Le NOMBRE de fiches, écrit dans le message. Sans lui, « il en manque »
    # et « il n'y en a que six » ne se distinguent pas : on ne sait pas si le
    # rendu a coupé ou si le calcul n'a rien trouvé de plus. On a cherché du
    # côté du rendu alors que la réponse était peut-être dans le compte.
    tete = list(tete)
    tete.insert(-1, f"_{len(lignes)} fiche(s) suivie(s)._")

    # Meme ordre que le site, comme le report du jour.
    messages, bloc = [], list(tete)
    for x in lignes:
        b, e = x["bilan"], x["e"]
        # Les deux quinzaines sont annoncees separement : ce sont deux
        # periodes de paie, pas une seule longue bande.
        moities = []
        if b.get("q1_notes"):
            moities.append(f"1–15 : {b['q1_tenus']}/{b['q1_notes']}")
        if b.get("q2_notes"):
            moities.append(f"16–fin : {b['q2_tenus']}/{b['q2_notes']}")
        detail = " · ".join(moities) or "aucune journée notée"
        # Le « @ » Discord, parce que ce message sert à PAYER : le nom de la
        # fiche désigne un téléphone, pas quelqu'un à qui virer de l'argent.
        qui = str(e.get("discord") or "").strip()
        qui = f" `@{qui}`" if qui else ""
        # `.get` partout, et ce n'est pas de la superstition : une fiche dont
        # le bilan manquait levait KeyError sur 'pastille', l'exception
        # remontait jusqu'au try/except de `publier`, et le bilan ENTIER
        # partait en fumée — vingt et une fiches perdues pour une seule
        # défaillante, avec pour toute trace une ligne dans un journal.
        part = [f"{b.get('pastille') or '⚪'} **{e.get('va', '?')}**{qui} · "
                f"{detail} · {e.get('actifs', 0)}/{e.get('objectif', 0)}"]
        carres = suite_jours(b.get("suite"), b.get("debut") or debut,
                             b.get("coupure") or 15)
        if carres:
            part.append(carres)
        part.append("")            # une ligne vide : sans elle, deux bandes de
                                   # trente carres se lisent comme une seule
        # On coupe AVANT de dépasser, et jamais au milieu d'une fiche : une
        # fiche dont le nom est dans un message et les carrés dans le suivant
        # est illisible au moment précis où on s'en sert.
        if (sum(_taille(y) + 1 for y in bloc)
                + sum(_taille(y) + 1 for y in part)) > _MAX_EMBED:
            messages.append("\n".join(bloc))
            # VIDE, plus `list(tete)`. L'en-tete pesait trois phrases et
            # quatre cents unites, recopiees sur CHAQUE morceau : de la
            # place perdue sur une limite qu'on sait etroite, et surtout la
            # meme legende a relire cinq fois d'affilee. Les morceaux se
            # suivent, celle du premier vaut pour tous.
            #
            # Effet de bord bienvenu : les morceaux suivants tiennent six
            # fiches au lieu de quatre, donc il y en a moins.
            bloc = []
        bloc.extend(part)
    messages.append("\n".join(bloc))
    # RECOMPTER ce qui part vraiment. La numerotation « partie 1/6 » etait le
    # seul signal qu'un morceau manquait, et elle vient de sauter : on remplace
    # une devinette par une verification. Si le decoupage perd une fiche, on
    # l'ECRIT dans le message — pas dans un journal du VPS que personne ne lit.
    #
    # Ce document sert a PAYER. Une fiche qui disparait sans bruit, c'est
    # quelqu'un qui n'est pas paye, et ca s'est produit deux fois ce soir : une
    # fois sur une exception qui emportait tout le bilan, une fois sur Discord
    # qui tronquait a mi-message en repondant « OK ».
    # LES FICHES ECARTEES SONT NOMMEES. Une fiche sans aucun compte rattache
    # ne peut pas etre notee — mais la taire rendait « qui manque ? » sans
    # reponse : rien ne distinguait un VA qui n'existe pas d'un VA dont le
    # telephone est vide. Et un telephone vide, sur un document de paie,
    # c'est justement ce qu'il faut voir.
    if ecartees:
        noms = ", ".join(n for _i, n in ecartees)
        messages[-1] += (
            f"{_SAUT}🚫 _{len(ecartees)} fiche(s) sans aucun compte rattaché, "
            f"donc non notées : {noms}._")
    ecrites = sum(len(_LIGNE_FICHE.findall(m)) for m in messages)
    if ecrites != len(lignes):
        messages[-1] += (
            f"\n\n⚠️ **{abs(len(lignes) - ecrites)} fiche(s) manquante(s)** — "
            f"{ecrites} affichée(s) sur {len(lignes)} suivie(s). Prévenir un admin.")
    # PAS de « partie 1/6 ». Elle servait a distinguer « le bilan complet »
    # de « la moitie du bilan » quand chaque morceau rouvrait sur le meme
    # titre. Un seul le porte desormais : un message sans titre est
    # visiblement une suite, la question ne se pose plus. Et le vrai
    # garde-fou reste le recomptage de `publier`, qui ecrit dans le message
    # lui-meme s'il manque une fiche — un numero ne faisait que le suggerer.
    return messages


def _mois(jour: str) -> tuple:
    """(premier, dernier) jour du mois qui contient `jour`."""
    d = datetime.date.fromisoformat(jour)
    debut = d.replace(day=1)
    fin = (datetime.date(d.year, 12, 31) if d.month == 12
           else datetime.date(d.year, d.month + 1, 1) - datetime.timedelta(days=1))
    return debut.isoformat(), fin.isoformat()


def _tronquer(txt: str) -> str:
    """Dernier filet du report DU JOUR. Compte comme Discord, pas comme Python.

    Il ne s'applique plus au bilan : celui-ci part en embed et se découpe
    proprement. Ici il ne sert que si la liste du jour explose, et il coupe
    LIGNE par ligne — au caractère, il tranchait un carré en deux, ce qui
    donne un point d'interrogation à l'écran.
    """
    if _taille(txt) <= _MAX_MSG:
        return txt
    lignes = txt.split("\n")
    pied = "\n…_(liste tronquée — Discord limite la taille d'un message)_"
    while lignes and (sum(_taille(x) + 1 for x in lignes)
                      + _taille(pied)) > _MAX_MSG:
        lignes.pop()
    return "\n".join(lignes) + pied


# ==============================================================================
# Collecte
# ==============================================================================

def identite_du_salon(nom: str, identites) -> str:
    """L'identite que ce salon suit, d'apres son NOM. '' = toutes.

    « report-compte » suit tout le monde ; « report-compte-jessye » ne suit
    que jessye. Le nom porte deja la convention qui designe ces salons, il
    peut aussi en porter la portee : on lit le salon et on sait ce qu'il
    contient, sans aller chercher un reglage ailleurs.

    Un suffixe qui ne correspond a AUCUNE identite connue est traite comme une
    simple etiquette (« report-comptes-equipe-1 ») et ne filtre rien. Le
    contraire serait pire : un salon nomme un peu de travers deviendrait vide
    sans que personne comprenne pourquoi.
    """
    n = str(nom or "").lower().replace("_", "-").strip()
    for base in tuple(PREFIXES_JOUR) + tuple(PREFIXES_MOIS):
        for prefixe in (base + "s-", base + "-"):
            if n.startswith(prefixe):
                suffixe = n[len(prefixe):].strip("-")
                for ident in (identites or []):
                    if str(ident).lower() == suffixe:
                        return str(ident).lower()
                return ""
    return ""


def etats_du_jour(jour: str = "", identite_voulue: str = "",
                  ecartees=None) -> list:
    """L'etat de CHAQUE fiche VA aujourd'hui, dans l'ordre identite puis VA.

    Une fiche sans le moindre compte est ecartee : poster « 0 / 30 » pour un
    telephone qui n'a encore rien ne ferait que du bruit.

    Mais ecartee N'EST PAS oubliee. Passer une liste a `ecartees` la remplit
    des (identite, nom) mis de cote. La question « qui manque ? » etait sans
    reponse possible tant que ce `continue` ne laissait aucune trace : ni le
    proprietaire ni moi ne pouvions distinguer « ce VA n'existe pas » de « ce
    VA existe mais son telephone n'a aucun compte rattache ». C'est
    exactement ce que le CLAUDE.md de ce depot interdit — ne jamais ecarter
    en silence, compter et remonter.

    On passe une liste plutot que de garder un etat de module : cette
    fonction est appelee depuis `asyncio.to_thread`, et deux appels
    concurrents se marcheraient dessus.
    """
    import jailbreak as jb
    import jb_objectifs as ob
    try:
        import web_upload as w
        stats = w._load_insta_3_stats_cache() or {}
    except Exception:
        stats = {}
    maintenant = time.time()
    jour = jour or ob.aujourdhui()
    out = []
    voulue = str(identite_voulue or "").strip().lower()
    for identite, entree in (jb.list_all() or {}).items():
        if not isinstance(entree, dict):
            continue
        if voulue and str(identite).lower() != voulue:
            continue
        comptes = [a for a in (entree.get("accounts") or []) if isinstance(a, dict)]
        # Les fiches DECLAREES, plus celles que seuls leurs comptes designent :
        # une fiche implicite s'affiche sur le dashboard, elle doit compter ici.
        # Le pseudo Discord est releve en meme temps que le nom de la fiche :
        # le bilan de quinzaine sert a PAYER, et « VA NOUM 1X1 » designe un
        # telephone, pas quelqu'un a qui virer de l'argent.
        noms, vus, discord = [], set(), {}
        for v in (entree.get("vas") or []):
            nom = (v.get("name") if isinstance(v, dict) else v) or ""
            nom = str(nom).strip()
            if nom and nom.lower() not in vus:
                vus.add(nom.lower())
                noms.append(nom)
                if isinstance(v, dict):
                    discord[nom.lower()] = str(v.get("discord_username") or "").strip()
        for a in comptes:
            nom = str(a.get("va") or "").strip()
            if nom and nom.lower() not in vus:
                vus.add(nom.lower())
                noms.append(nom)
        for nom in noms:
            siens = [a for a in comptes
                     if str(a.get("va") or "").strip().lower() == nom.lower()]
            if not siens:
                if ecartees is not None:
                    ecartees.append((str(identite), nom))
                continue
            e = ob.etat_fiche(identite, nom, siens, stats, maintenant, jour)
            e["discord"] = discord.get(nom.lower(), "")
            out.append(e)
    # PAS de tri. L'ordre dans lequel on vient de parcourir jailbreak.json est
    # exactement celui du site : les identites dans l'ordre du fichier, et les
    # fiches dans l'ordre de `vas` — que le proprietaire a range a la main
    # (reorder_vas). Trier ici, meme alphabetiquement, cassait la
    # correspondance entre l'ecran et le message.
    return out


# ==============================================================================
# Le bouton Rafraichir
# ==============================================================================

#: Delai minimum entre deux rafraichissements d'un meme salon. Recalculer le
#: bilan lit tout le referentiel et tout le cache de stats : sans ce delai,
#: trois clics de suite le font trois fois pour rien.
_ATTENTE_S = 45
_DERNIER_CLIC = {}


class BilanRefreshView(discord.ui.View):
    """Le bouton « Rafraichir » pose sous le bilan.

    `timeout=None` et un `custom_id` fixe : la vue est REENREGISTREE au
    demarrage du bot (voir cog_load), donc le bouton repond encore apres un
    redemarrage. Sans ca le message epingle deviendrait un decor mort, et
    c'est le genre de panne qu'on ne remarque qu'en cliquant.

    Un bouton ne consomme AUCUNE commande slash — le seul moyen d'offrir un
    declenchement depuis Discord sur ce bot, qui est au plafond des cent.
    """

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Rafraîchir", emoji="🔄",
                       style=discord.ButtonStyle.secondary,
                       custom_id="reportcomptes:refresh")
    async def b_refresh(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        cog = self.cog or interaction.client.get_cog("ReportComptes")
        if cog is None:
            await interaction.response.send_message(
                "⚠️ Module indisponible.", ephemeral=True)
            return
        cid = getattr(interaction.channel, "id", None)
        reste = _ATTENTE_S - (time.time() - _DERNIER_CLIC.get(cid, 0))
        if reste > 0:
            # On le DIT au lieu de ne rien faire : un bouton muet passe pour
            # casse, et la personne reclique.
            await interaction.response.send_message(
                f"⏳ Déjà rafraîchi il y a moins d'une minute — "
                f"réessaie dans {int(reste)} s.", ephemeral=True)
            return
        _DERNIER_CLIC[cid] = time.time()
        await interaction.response.defer(ephemeral=True)
        try:
            jour = _paris_now().date().isoformat()
            # `cibles=[]` : on ne repost PAS le report du jour, on ne refait
            # que le bilan. Cliquer « rafraichir » sous un bilan ne doit pas
            # deverser vingt-quatre lignes dans le salon d'a cote.
            res = await cog.publier(jour, cibles=[])
        except Exception as e:                      # noqa: BLE001
            await interaction.followup.send(
                f"✕ Échec : {str(e)[:150]}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Bilan refait — {res.get('fiches', 0)} fiche(s).", ephemeral=True)


# ==============================================================================
# Le cog
# ==============================================================================

class ReportComptes(commands.Cog):
    """Report de minuit par fiche VA + bilan de quinzaine epingle."""

    def __init__(self, bot):
        self.bot = bot
        self._dernier_jour = ""
        self.boucle.start()

    async def cog_load(self):
        """Réenregistre la vue : sans ça le bouton du message épinglé ne
        répond plus après un redémarrage, et le message devient un décor."""
        try:
            self.bot.add_view(BilanRefreshView(self))
        except Exception as e:                      # noqa: BLE001
            print(f"[report-comptes] vue non enregistrée : {e}", flush=True)

    def cog_unload(self):
        self.boucle.cancel()

    # ---- la boucle -------------------------------------------------------
    @tasks.loop(minutes=20)
    async def boucle(self):
        """Poste une fois par jour, apres minuit a Paris.

        On scrute toutes les vingt minutes au lieu de programmer un reveil a
        minuit pile : un redemarrage a 00 h 03 ne doit pas faire sauter la
        journee. Le garde-fou est la date deja traitee, pas l'heure.
        """
        try:
            maintenant = _paris_now()
            jour = maintenant.date().isoformat()

            # PREMIER PASSAGE. Un salon « report-compte » qui vient d'etre cree
            # n'a aucune raison d'attendre minuit pour montrer quelque chose :
            # on l'a cree justement pour voir. Un salon est « neuf » tant qu'il
            # n'a pas de message epingle enregistre — donc une seule fois.
            cfg = _load_cfg()
            # Un salon du jour est neuf tant qu'il n'a jamais recu de report ;
            # un salon de quinzaine, tant qu'il n'a pas son epingle. Deux
            # marqueurs parce que ce sont deux choses differentes : le salon
            # du jour n'a pas d'epingle quand le bilan vit ailleurs.
            neufs = [(cle, ch) for cle, ch in self.salons_report()
                     if not (cfg.get(cle) or {}).get("dernier_jour")]
            # « pin_ids » au pluriel : le bilan tient en plusieurs messages
            # depuis qu'il porte le mois entier. La boucle cherchait encore
            # l'ancien « pin_id » au singulier — elle croyait donc le salon
            # eternellement neuf, et le republiait tous les vingt tours.
            def _a_refaire(cle):
                rec = cfg.get(cle) or {}
                if not (rec.get("pin_ids") or rec.get("pin_id")):
                    return True                 # jamais publie
                # Format change depuis la derniere ecriture : on reecrit une
                # fois, sans attendre 1 h. C'est ce qui manquait — un nouveau
                # rendu restait invisible des heures, et se lisait comme une
                # panne.
                return rec.get("format") != FORMAT_BILAN
            pin_neuf = any(_a_refaire(cle) for cle, _ch in self.salons_quinzaine())
            if neufs or pin_neuf:
                noms = ", ".join(str(getattr(c, "name", "?")) for _k, c in neufs)
                print(f"[report-comptes] premier passage : {noms or 'bilan seul'}",
                      flush=True)
                await self.publier(jour, cibles=neufs or None)

            # À 1 h, pas à minuit — et ce n'est pas un détail. Le report ne
            # scrape rien : il lit le cache des stats. Or ce cache est
            # rafraîchi automatiquement à 00 h. Publier à 00 h 05 revenait donc
            # à clôturer la journée sur les chiffres de MIDI : un compte qui
            # publie le soir serait compté « oublié », et son VA payé dessus.
            # Une heure laisse le scrape finir.
            if maintenant.hour != HEURE_REPORT or self._dernier_jour == jour:
                return
            # La journee qu'on cloture est CELLE QUI VIENT DE FINIR.
            veille = (maintenant.date() - datetime.timedelta(days=1)).isoformat()
            self._dernier_jour = jour
            await self.publier(veille)
        except Exception as e:
            print(f"[report-comptes] boucle : {e}", flush=True)

    @boucle.before_loop
    async def avant(self):
        await self.bot.wait_until_ready()

    # ---- publication -----------------------------------------------------
    async def publier(self, jour: str, salon_force=None, cibles=None) -> dict:
        """Poste le report de `jour` dans tous les salons configures.

        `salon_force` sert au declenchement manuel : on publie la, et nulle
        part ailleurs.
        """
        import jb_objectifs as ob
        if cibles is None:
            if salon_force is not None:
                cibles = [(_cle(getattr(salon_force.guild, "id", 0), salon_force.id),
                           salon_force)]
            else:
                cibles = self.salons_report()

        # La MESURE est faite une fois, sur tout le monde, et elle est gravee
        # une fois. Elle ne depend pas de qui la regarde : un salon qui ne
        # suit que jessye ne doit pas empecher les autres fiches d'etre
        # comptees dans leur bilan de quinzaine.
        #
        # On grave AVANT de poster : si Discord refuse (permission, panne), la
        # journee reste comptee. L'inverse aurait perdu la mesure a cause d'un
        # probleme d'affichage.
        # `ecartees` : les fiches sans aucun compte, que la mesure met de
        # cote. On les recolte pour les NOMMER dans le bilan au lieu de les
        # laisser disparaitre — « qui manque ? » doit avoir une reponse
        # dans le message lui-meme.
        ecartees = []
        tous = await asyncio.to_thread(etats_du_jour, jour, "", ecartees)
        await asyncio.to_thread(ob.enregistrer_jour, tous, jour)

        bilans = {}
        for e in tous:
            bilans[(e["identite"].lower(), e["va"].lower())] = await asyncio.to_thread(
                ob.bilan_mois, e["identite"], e["va"], jour)

        try:
            import jailbreak as _jb_id
            identites = list((_jb_id.list_all() or {}).keys())
        except Exception:
            identites = []

        # Le bilan part dans SES salons s'il en existe. Sinon il reste avec le
        # report du jour : personne ne doit se retrouver sans bilan pour avoir
        # omis de créer un salon.
        salons_pin = self.salons_quinzaine() if salon_force is None else []
        pin_a_part = bool(salons_pin)
        if not pin_a_part:
            salons_pin = list(cibles)

        def _pour(ch):
            """(identité suivie, fiches, lignes de bilan, écartées) pour ce salon.

            Les écartées sont filtrées par la MEME identité que les fiches :
            un salon qui ne suit que jessye ne doit pas afficher les
            téléphones vides d'une autre modèle.
            """
            v = identite_du_salon(getattr(ch, "name", ""), identites)
            ets = [e for e in tous if not v or e["identite"].lower() == v]
            ec = [(i, n) for i, n in ecartees if not v or str(i).lower() == v]
            return v, ets, [{"e": e, "bilan": bilans.get(
                (e["identite"].lower(), e["va"].lower())) or {}} for e in ets], ec

        n_msg, n_fiches = 0, 0
        for cle, ch in cibles:
            # Chaque salon ne reçoit QUE ce qu'il annonce suivre.
            voulue, etats, lignes_bilan, ecartes_ci = _pour(ch)
            n_fiches = max(n_fiches, len(etats))
            try:
                for morceau in bloc_jour(etats, jour, voulue):
                    await ch.send(_tronquer(morceau))
                    n_msg += 1
                    await asyncio.sleep(0.6)     # on ne bouscule pas Discord
                if not pin_a_part:
                    await self._poser_bilan(ch, cle, bloc_quinzaine(
                        lignes_bilan, _mois(jour)[0], _mois(jour)[1], voulue,
                        ecartes_ci))
                # « Ce salon a deja recu un report. » Marque a part de
                # l'epingle : quand le bilan part dans son propre salon,
                # celui-ci n'a plus d'epingle du tout — s'y fier l'aurait
                # laisse eternellement « neuf », donc republiant toutes les
                # vingt minutes.
                self._marquer_servi(cle, ch, jour)
            except discord.Forbidden:
                print(f"[report-comptes] pas le droit d'écrire dans {ch}", flush=True)
            except Exception as e:
                print(f"[report-comptes] envoi : {e}", flush=True)

        if pin_a_part:
            debut, fin = _mois(jour)
            for cle, ch in salons_pin:
                voulue, _ets, lignes_bilan, ecartes_ci = _pour(ch)
                # Compter ICI aussi : le bouton « Rafraichir » ne refait que
                # le bilan (cibles vide), donc la boucle du jour ne tourne pas
                # et le compte restait a zero. « Bilan refait — 0 fiche(s) »
                # se lit comme un echec alors que tout s'est bien passe.
                n_fiches = max(n_fiches, len(_ets))
                try:
                    await self._poser_bilan(
                        ch, cle, bloc_quinzaine(lignes_bilan, debut, fin,
                                                voulue, ecartes_ci))
                except discord.Forbidden:
                    print(f"[report-comptes] pas le droit d'écrire dans {ch}", flush=True)
                except Exception as e:
                    print(f"[report-comptes] bilan : {e}", flush=True)

        return {"fiches": n_fiches, "messages": n_msg,
                "salons": len(cibles) + (len(salons_pin) if pin_a_part else 0)}

    def _marquer_servi(self, cle: str, ch, jour: str) -> None:
        """Note qu'un salon a recu son report, et quel jour."""
        try:
            cfg = _load_cfg()
            rec = cfg.get(cle) if isinstance(cfg.get(cle), dict) else {
                "guild_id": getattr(getattr(ch, "guild", None), "id", 0),
                "channel_id": ch.id}
            rec["dernier_jour"] = jour
            cfg[cle] = rec
            _save_cfg(cfg)
        except Exception as e:                      # noqa: BLE001
            print(f"[report-comptes] marquage : {e}", flush=True)

    def _salons(self, prefixes) -> list:
        """[(cle, salon)] des salons dont le nom commence par l'un des prefixes.

        Le proprietaire cree le salon, il est servi — pas de commande a
        lancer, et rien a reparametrer apres un changement de serveur.

        Les prefixes du MOIS sont testes avant ceux du jour par l'appelant :
        « report-mois » commence aussi par... non, justement pas. Mais si un
        jour deux listes se recouvrent, c'est ici qu'il faudra trancher.
        """
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        out = []
        for c in getattr(self.bot, "get_all_channels", lambda: [])():
            nom = str(getattr(c, "name", "") or "").lower().replace("_", "-")
            if hasattr(c, "send") and any(nom.startswith(x) for x in prefixes):
                out.append((_cle(getattr(c.guild, "id", 0), c.id), c))
        return out

    def salons_report(self) -> list:
        """Ou va le report DU JOUR.

        La configuration par identifiant reste lue si elle existe : elle sert
        aux salons qui ne suivent pas la convention de nom.
        """
        out = self._salons(PREFIXES_JOUR)
        vus = {ch.id for _c, ch in out}
        for cle, cfg in _reports_configures(_load_cfg()):
            try:
                ch = self.bot.get_channel(int(cfg.get("channel_id") or 0))
            except Exception:
                ch = None
            if ch is None or ch.id in vus:
                continue
            # Le salon du BILAN a lui aussi une entree de configuration — c'est
            # la qu'on garde les identifiants de ses messages epingles. Sans ce
            # filtre il remontait ici, et recevait le report du jour EN PLUS du
            # bilan : deux choses dans le salon qu'on venait justement de creer
            # pour n'en avoir qu'une.
            nom = str(getattr(ch, "name", "") or "").lower().replace("_", "-")
            if any(nom.startswith(x) for x in PREFIXES_MOIS):
                continue
            vus.add(ch.id)
            out.append((cle, ch))
        return out

    def salons_quinzaine(self) -> list:
        """Ou va le BILAN de quinzaine. Vide = il reste dans le salon du jour."""
        return self._salons(PREFIXES_MOIS)

    async def _poser_bilan(self, ch, cle, messages: list):
        """Le bilan du mois, en un ou plusieurs messages RÉÉCRITS sur place.

        Un mois de carrés pour vingt-quatre fiches ne tient pas dans les deux
        mille caractères de Discord. On garde donc une LISTE d'identifiants,
        et on réécrit chacun. Le nombre de fiches bouge d'un jour à l'autre :

        - moins de messages qu'avant : les surnuméraires sont vidés, pas
          supprimés — ce dépôt n'efface rien, et un message effacé emporterait
          les annotations posées à la main dessus ;
        - plus de messages qu'avant : on en ajoute à la suite.

        Seul le premier est épinglé : c'est lui qui porte l'en-tête.
        """
        cfg = _load_cfg()
        c = cfg.get(cle) if isinstance(cfg.get(cle), dict) else {
            "guild_id": getattr(getattr(ch, "guild", None), "id", 0),
            "channel_id": ch.id}
        ids = list(c.get("pin_ids") or [])
        if not ids and c.get("pin_id"):
            ids = [c["pin_id"]]                 # ancien format, un seul message
        # Les morceaux doivent SE SUIVRE. Discord ne deplace pas un message :
        # quand leur nombre change, reecrire « celui d'avant » laisse le
        # premier morceau la ou il etait — parfois une heure plus haut dans le
        # salon — et les suivants tout en bas. On lit alors trois fiches et on
        # croit que les autres manquent. C'est arrive, et ca s'est lu comme un
        # bug de calcul.
        #
        # Dans ce cas on republie l'ensemble a la suite, et on VIDE les anciens
        # au lieu de les supprimer : ce depot n'efface rien, et un message
        # efface emporterait ce qu'on aurait annote dessus.
        if len(ids) != len(messages):
            for mid in ids:
                await self._ecrire_epingle(
                    ch, mid, "_(bilan déplacé plus bas — ce message ne sert plus)_",
                    epingler=False)
            ids = []
        neufs = []
        for i, texte in enumerate(messages):
            mid = ids[i] if i < len(ids) else 0
            # Le bouton va sur le DERNIER morceau : c'est celui du bas, le plus
            # proche de la zone de saisie, donc celui qu'on a sous la main.
            vue = BilanRefreshView(self) if i == len(messages) - 1 else None
            nouv = await self._ecrire_epingle(ch, mid, texte,
                                              epingler=(i == 0), vue=vue)
            if nouv is None:                    # échec passager : on garde l'ancien
                nouv = mid
            neufs.append(nouv)
        # Les messages en trop sont VIDÉS, jamais supprimés.
        for mid in ids[len(messages):]:
            await self._ecrire_epingle(ch, mid, "_(suite du bilan — vide ce mois-ci)_",
                                       epingler=False)
            neufs.append(mid)
        # Ce qui a REELLEMENT ete envoye : taille et nombre de fiches par
        # message. Discord affiche six fiches la ou le message en annonce
        # vingt et une ; sans cette trace, impossible de savoir si le bot a
        # envoye vingt et une ou si Discord en a mange quinze.
        self.dernier_envoi = [
            {"unites": _taille(m),
             "fiches": sum(1 for l in m.splitlines()
                           if l.startswith(("⚪", "🟢", "🟠", "🔴"))),
             "id": neufs[i] if i < len(neufs) else None}
            for i, m in enumerate(messages)]
        c["pin_ids"] = [m for m in neufs if m]
        c["format"] = FORMAT_BILAN
        c.pop("pin_id", None)
        cfg[cle] = c
        _save_cfg(cfg)

    @staticmethod
    def _embed(texte: str):
        """Le bilan dans un embed : 4096 unités au lieu de 2000.

        C'est la seule façon de tenir toutes les fiches dans UN message. La
        couleur reprend le gris de fond de Discord — un bilan n'est ni une
        alerte ni une félicitation, et une bande colorée à gauche viendrait
        contredire les carrés qui, eux, veulent dire quelque chose.
        """
        return discord.Embed(description=texte, colour=0x2B2D31)

    async def _ecrire_epingle(self, ch, mid, texte: str, epingler: bool, vue=None):
        """Réécrit le message `mid`, ou en crée un. Rend son identifiant."""
        if mid:
            try:
                msg = await ch.fetch_message(int(mid))
                # `view=` est passé même à None : sans ça, un morceau qui
                # n'est plus le dernier garderait son bouton, et on aurait
                # trois « Rafraîchir » empilés.
                # `content=None` efface le texte des anciens bilans, qui
                # étaient postés en clair : sans ça on lirait le bilan deux
                # fois, une en texte et une dans l'embed.
                await msg.edit(content=None, embed=self._embed(texte), view=vue)
                return int(mid)
            except discord.NotFound:
                print(f"[report-comptes] message {mid} effacé — on en repose un",
                      flush=True)
            except Exception as e:
                # On NE reposte PAS : reposter sur une erreur passagère, c'est
                # fabriquer le doublon qu'on veut éviter.
                print(f"[report-comptes] message illisible ({type(e).__name__}) — "
                      f"on garde l'existant", flush=True)
                return None
        try:
            emb = self._embed(texte)
            msg = (await ch.send(embed=emb, view=vue) if vue
                   else await ch.send(embed=emb))
            if epingler:
                try:
                    await msg.pin()
                except Exception:
                    pass                        # pas le droit d'épingler : tant pis
            return msg.id
        except Exception as e:
            print(f"[report-comptes] envoi du bilan : {e}", flush=True)
            return None

    # ---- pas de commande slash, et c'est un choix contraint -------------
    #
    # Discord plafonne une APPLICATION a 100 commandes slash globales. Ce bot
    # y est deja : quatre cogs (vaactivity, vasort, tgrouter, numeros) ne se
    # chargent plus depuis un moment, en silence, pour cette raison. En
    # ajouter trois de plus faisait echouer celui-ci exactement pareil.
    #
    # Ce report n'a de toute facon pas besoin d'une commande : il tourne tout
    # seul apres minuit. Ne restait que la configuration du salon — remplacee
    # par une convention : le report va dans TOUT salon dont le nom commence
    # par « report-compte ». Le proprietaire cree le salon, il est servi.
    # Un declenchement manuel existe depuis le tableau de bord.


async def setup(bot):
    await bot.add_cog(ReportComptes(bot))
