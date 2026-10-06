"""Le podium de la semaine : un classement des subs, posté chaque lundi.

La semaine court du LUNDI au DIMANCHE, et le message part le lundi suivant :
il récapitule la semaine qui vient de finir, jamais celle en cours.

CE QU'ON COMPTE. « Subs » veut dire ici des clics. Sur Twitter (VA US), depuis
le 06/10/2026 : les clics des liens de tracking OnlyFans des VA, lus dans
MyPuls, et chaque VA est reconnu à son tracking (clé « mesure », voir
_classement_tracking). Ailleurs (Va IG) : les clics venus du marché du serveur
sur les liens GetMySocial — la mesure que le tableau de bord appelle « Clics
US » ou « Clics FR ».

LA LISTE DES LIENS EST LUE EN DIRECT, jamais dans le cache du site. Le cache
`gmsdash_links.json` avait treize liens quand GetMySocial en portait
trente-trois : neuf personnes manquaient, dont celle qui avait fait le plus de
subs de la semaine. Un podium bâti là-dessus payait la mauvaise personne. Si
GetMySocial ne répond pas, on se rabat sur le cache — et le message le DIT.

UNE PERSONNE, PLUSIEURS LIENS. Certains en ont quatre. Leurs clics sont
additionnés en un seul appel : GetMySocial calcule alors le détail par pays
sur l'ensemble, ce qu'une somme de relevés séparés ne sait pas faire (chaque
lien ne rend que son top ~10 de pays, et la traîne se perdait).

LE LIEN « SPAM » COMPTE À PART, comme une personne de plus — c'est la règle
voulue : il porte son propre trafic, il a son propre numéro.

LES NUMÉROS NE BOUGENT JAMAIS. Le classement est anonyme : personne ne doit
lire le prénom d'un autre à côté d'un chiffre. Mais un numéro attribué par le
rang ne voudrait rien dire — on ne se reconnaîtrait pas d'une semaine sur
l'autre. La table personne → numéro est donc gardée dans un fichier, et elle
reprend les anciens numéros de GetMySocial (VA 1 = BO7, VA 2 = Safidy…) pour
que rien ne change pour ceux qui étaient déjà là.

UN RELEVÉ RATÉ N'EST PAS UN ZÉRO. Si GetMySocial ne répond pas pour quelqu'un,
il est mis de côté et le message le dit : un zéro inventé le ferait tomber du
podium, et c'est de l'argent.

LES RÔLES NE SONT PAS POSÉS PAR LE BOT. Rien ne relie un numéro de VA à un
compte Discord, et le bot n'a pas la permission de lire la liste des membres.
Les primes se réclament à la main, comme le bonus du jour.

UN MESSAGE PAR PÉRIODE, ET IL RESTE. Propriétaire, 03/10/2026 : « il reste
fixe et un autre se lance », « que ça reste là, la période après la période,
le truc bouge plus ». Chaque semaine et chaque quinzaine a SON message, jamais
effacé : vivant pendant la période, puis figé sur place sur les chiffres de
la période entière, avec une ligne qui dit que c'est fini. Un message neuf
part ensuite, en dessous. Avant, la semaine finie restait « SEMAINE EN COURS
— Rien n'est joué » avec des chiffres vieux de deux heures, à côté d'un
podium posté à part et mêlé au message de la semaine suivante.

VA IG MONTRE AUSSI LES VA US, POUR LE MOMENT (clé « avec_us » de SERVEURS,
voir là pour couper). Les VA de Twitter y paraissent sous leur vrai libellé
anonyme (« VA 12 ») avec leurs clics US ; l'en-tête dit que le classement
couvre toute l'agence, sans marque FR/US ligne à ligne. Le relevé de
Twitter est repris en mémoire, pas refait.

LES PRIMES DE VA IG VONT AUX TROIS PREMIERS DE CE CLASSEMENT MÊLÉ, VA FR
comme VA US (propriétaire, 03/10/2026 : « les primes elles vont aux 3
meilleurs VA, c'est tout, pas de distinction pour le moment »), s'ils ont
au moins un sub. suivi_va reçoit la liste mêlée, dans l'ordre affiché : un
VA FR gagnant est prévenu dans son ticket au montant de son VRAI rang. Un
VA US n'a pas de ticket sur Va IG ; primé ici, il l'est TOUJOURS aussi sur
Twitter, pour les mêmes subs (le tri mêlé garde l'ordre de Twitter) : le
journal le dit, rang et prime Twitter à l'appui, et laisse au propriétaire
la prime Va IG (en plus, ou à personne : « un seul prix par personne »).
Sans relevé US, ce podium ne sait pas qui sont ses trois premiers : il
attend, comme sans relevé FR. Un VA US sans relevé y décale peut-être les
rangs payés : le podium part (« à confirmer avant de payer »), mais les
annonces privées attendent le relevé complet, puis le podium est corrigé
sur place. Le relevé gardé pour figer reste celui des seuls VA FR (le
relevé US vit en mémoire, voir _releve_us).

LE BOUTON « 🔄 METTRE À JOUR » (clé « bouton_maj », Va IG seulement).
Propriétaire, 03/10/2026 : « mets un truc pour reload a la main », « le
bouton refresh ». Deux heures entre deux relevés, c'est long quand un VA
vient de faire ses subs. Le message vivant de la semaine et les pages
vivantes de la quinzaine portent ce bouton ; un message figé (« terminée »,
podium, semaine ou quinzaine finie) n'en porte jamais : une période finie n'a
plus rien à mettre à jour. Réservé au staff (traiter, plus bas). Le clic
relance rafraichir puis rafraichir_subs sans attendre leur rythme, mais
leurs règles de gel restent maîtresses : un clic le lundi à 3h ne lance pas
la semaine neuve avant le podium. Un seul passage à la fois (_exclusif) :
un clic pendant le tour de la boucle, ou l'inverse, ne poste rien deux fois.

LE THÈME MARIO (clé « theme », Va IG seulement). Propriétaire, 03/10/2026 :
« tu penses y'a moyen de faire un theme Mario pour tout ca », puis « vas-y ».
« Grand Prix des subs » pour la semaine, « Championnat des subs » pour la
quinzaine, les têtes de Mario, Luigi et Peach aux trois premières places
(emojis du serveur, posés par _assurer_emojis ; 👑 ⭐ 🍄 tant qu'ils
manquent), 🪙 à la place du 💰, une vignette du site en haut à droite, le
bouton « Relancer la course ». Rien d'autre ne bouge : mêmes chiffres, mêmes
primes, mêmes avertissements, même pied. Sans la clé, le message d'avant.
Un message figé relit la liste des têtes juste avant son rendu
(_tetes_sures) : il ne gardera jamais pour toujours une tête disparue.

Ce que podium.json en retient :
  vivants[gid]       semaine, message, vu, dernier (relevé gardé pour figer
                     sans GetMySocial), termine (le lundi, « terminée » déjà dit)
  postes["gid:lundi"]   le message du podium (celui de la semaine, figé)
  figes[gid][lundi]     historique des semaines figées (mode podium, reposte
                        ou sans_podium ; ping = la mention @everyone,
                        ping_a_refaire si Discord l'a refusée en passant ;
                        primes_attente = le relevé FR du podium, tant que
                        ses annonces privées attendent le relevé US complet)
  subs[gid]          saison, messages (les pages), vu, dernier
  subs_a_figer[gid][debut]  quinzaine finie pas encore figée (essais, depuis ;
                        pages/faites une fois calculées, pour reprendre sans
                        relever GetMySocial une seconde fois ; sans_bouton
                        quand le bouton 🔄 de ses pages est déjà retiré)
  subs_figes[gid][debut]    historique des quinzaines figées

Et podium_emojis.json : {gid: {nom: id}} des têtes du thème sur chaque
serveur, plus _essais[gid] (jour du dernier passage chez Discord, et l'échec
s'il y en a eu un) — un essai par jour au plus.
"""
from __future__ import annotations

import base64
import contextvars
import datetime as dt
import functools
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "podium.json"
CONFIG_FICHIER = DATA_DIR / "podium_config.json"
NUMEROS_FICHIER = DATA_DIR / "podium_numeros.json"
LIENS_CACHE = DATA_DIR / "gmsdash_links.json"

SALON_PODIUM = "─│🏆┤-podium"
SALON_SUBS = "─│📊┤-subs"
SALON_BONUS = "─│💸┤-bonus-journalier"
PRIMES_JOUR = [7.50, 5.00, 3.50]
ALLTIME_FICHIER = DATA_DIR / "podium_alltime.json"
ALLTIME_DEPUIS = "2024-01-01"     # avant les premiers liens : « depuis toujours »
# Les espaces GetMySocial qui portent des liens de VA. Il y en a DEUX : les
# anciens liens vivent dans « JESSY LE RETOUR », les nouveaux sont generes
# dans « EMY TWITTER ». N'en lire qu'un rendait l'autre invisible au
# classement — quelqu'un aurait travaille sans jamais apparaitre.
EQUIPES_VA = ["tm_6a0e4739bfa0c238f20a8bf5",   # JESSY LE RETOUR
              "tm_6ab46ebb11a0232c11211b1a"]   # EMY TWITTER
EQUIPE_VA = EQUIPES_VA[0]                      # garde l'ancien nom lisible

# Les serveurs ou le podium, les subs et le bonus sont publies, et CE QUE
# chacun compte. Les chiffres de Twitter affiches sur Threads seraient faux ;
# Va IG (serveur FR, proprietaire 03/10/2026 : « lance le truc des subs comme
# pour Twitter avec le numero du VA », « fais aussi le podium », primes
# « comme Twitter ») a SES liens, SES pays et ses numeros « Amelia VA 3 » --
# les memes que le nom du ticket et le lien (liens_fr.numero_va).
TWITTER_ID = "1445108485090971710"
VA_IG_ID = "1505418484052394004"
SERVEURS: Dict[str, Dict[str, Any]] = {
    TWITTER_ID: {"equipes": None,                # podium_config, sinon EQUIPES_VA
                 "pays": ("US",), "marche": "US", "source": "Twitter 🐦",
                 "bot": "Luigi", "fr": False, "bonus": True, "minutes": None,
                 "alltime": None,                # ALLTIME_FICHIER
                 # Propriétaire, 06/10/2026 : « compte uniquement que les clics
                 # sur inflow », pour les seuls VA US. Les clics des liens de
                 # tracking (MyPuls), plus ceux de GetMySocial ; « pays » ne sert
                 # plus qu'au relevé GetMySocial que Va IG garde de ces VA. Voir
                 # _classement_tracking. POUR REVENIR AUX CLICS GETMYSOCIAL :
                 # retirer cette clé, rien d'autre.
                 "mesure": "tracking"},
    VA_IG_ID: {"equipes": ["tm_6ac06401e06eabe3b9ef45f6"],   # VA IG DISCORD (liens_fr.EQUIPE)
               # le marche FR : les memes pays que le report des clics (clickrecap.MARCHES)
               "pays": ("FR", "BE", "CH", "LU", "MC"), "marche": "FR",
               "source": "Instagram 📸", "bot": "Luigi", "fr": True,
               # pas de salon bonus sur Va IG ; deux heures entre deux releves :
               # un appel GetMySocial par VA, et le quota est partage avec le site
               "bonus": False, "minutes": 120, "alltime": "podium_alltime_va_ig.json",
               # TEMPORAIRE. Avec trois VA, le podium et les subs de Va IG avaient
               # l'air vides. Proprietaire, 03/10/2026 : « pour les subs mais aussi
               # le mec du US, comme ca ca fait comme si y'a des vrais mecs », « mets
               # les VA US aussi », « juste pour le moment, je te dirai pour couper
               # plus tard ». Les VA de Twitter (« VA 7 », clics US) s'affichent
               # alors a cote des VA FR, partout sur Va IG. Les primes vont aux
               # trois premiers de ce classement mele, VA US compris (meme jour :
               # « les primes elles vont aux 3 meilleurs VA, c'est tout, pas de
               # distinction pour le moment ») ; un VA US prime ici l'est toujours
               # aussi sur Twitter (memes subs) : sa prime Va IG reste a trancher
               # par le proprietaire, le journal la lui pose.
               # Il voulait aussi les faire passer pour des VA « Alicia » :
               # refuse, ce serait preter le travail d'un VA a un autre sur un
               # classement qui paie. Compromis annonce : leur vrai libelle
               # (« VA 12 »), un en-tete « toute l'agence », aucune marque FR/US
               # ligne a ligne. POUR COUPER : retirer cette cle, rien d'autre (sans
               # elle, chaque message redevient exactement celui d'avant, et les
               # primes celles des seuls VA FR).
               "avec_us": True,
               # Le nom des VA US sur Va IG : ils travaillent Jessye, et Amelia
               # EST Jessye sur le marche FR (proprietaire, 03/10/2026 : « c'est
               # la meme personne », « ou sinon ecris Jessye »). « Jessye VA 12 »
               # et pas « Amelia VA 12 » : Amelia a ses propres numeros FR, un
               # vrai « Amelia VA 12 » se serait cru sur le podium.
               "nom_us": "Jessye",
               # Le bouton « 🔄 Mettre à jour » sous les messages VIVANTS (proprietaire,
               # 03/10/2026 : « mets un truc pour reload a la main », « le bouton
               # refresh ») : deux heures entre deux releves, le staff veut voir les
               # subs tout de suite. Lu par _boutons et traiter seulement. POUR LE
               # RETIRER : False, pas la cle retiree. False enleve aussi le bouton des
               # messages deja postes, a leur prochaine edition ; sans la cle, rien
               # n'est envoye a Discord (Twitter, a l'octet pres comme avant) et un
               # bouton deja pose resterait.
               "bouton_maj": True,
               # L'habillage « Mario Kart » du podium et du classement subs.
               # Proprietaire, 03/10/2026 :
               # « tu penses y'a moyen de faire un theme Mario pour tout ca »,
               # puis « vas-y » (les bots s'appellent deja Mario, Luigi,
               # Peach…). Voir THEMES : titres, couleurs, vignette, tetes des
               # personnages au top 3, bouton « Relancer la course ».
               # Les chiffres, les primes, les avertissements et le pied ne
               # changent pas. POUR LE RETIRER : enlever cette cle ; chaque message
               # redevient celui d'avant, a l'octet pres, au passage suivant (les
               # messages deja figes gardent leur habillage).
               "theme": "mario"},
}


def _profil(gid: Optional[str] = None) -> Dict[str, Any]:
    """Ce que compte ce serveur. Sans serveur (pages du site, anciens appels) :
    Twitter, comme avant."""
    return SERVEURS.get(str(gid or "")) or SERVEURS[TWITTER_ID]

PRIMES = [10.0, 5.0, 3.0]
# Le nom du bot que les membres voient change : « Siri » jusqu'au 03/10/2026,
# « Luigi » depuis (son application s'appelle SEVEN dans le portail Discord, un
# nom que personne ne peut mentionner). Un VA envoye chercher « @Siri » ne
# trouvait plus personne. Le nom a mentionner se lit donc dans le profil du
# serveur, SERVEURS[gid]["bot"] -- jamais ecrit en dur dans un message.
MEDAILLES = ["🥇", "🥈", "🥉"]
COMBIEN_AFFICHES = 15
HEURE_POST = 9          # lundi, heure française
MINUTES_LIVE = 60       # entre deux rafraîchissements du message vivant

# Les numéros que GetMySocial portait avant d'être renommé. Ils sont repris
# tels quels : quelqu'un qui était VA 12 reste VA 12.
NUMEROS_HISTORIQUES = {
    "BO7": 1, "Safidy": 2, "Laboule": 3, "VA 1 Noum": 4, "Bryan": 5,
    "Mykey": 6, "Miranto": 7, "VA 2 Noum": 8, "VA 3 Noum": 9,
    "Abdoul": 10, "Kylmich": 11, "Roucham": 12, "Gerome": 13,
}


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


# Le VPS tourne en UTC, le Mac en heure de Paris : sans cela, « lundi 09h »
# tombait a 11h francaise, et la semaine basculait le lundi a 02h. Tout ce qui
# touche aux dates passe par ici.
def _maintenant() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None)
    except Exception:
        return dt.datetime.now()


def _aujourdhui() -> dt.date:
    return _maintenant().date()


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


# ─── le thème (clé « theme » de SERVEURS) ────────────────────────────────
# Un thème ne touche QUE l'habillage : titres, couleurs, vignette, marqueurs
# des places, libellé du bouton. Les rangs, les montants, les règles de prime,
# les avertissements et le pied restent ceux du message sans thème : ce
# message paie, et son sens ne doit pas dépendre d'un décor. Un serveur sans
# la clé (Twitter) reçoit exactement le message d'avant.
THEMES: Dict[str, Dict[str, Any]] = {
    "mario": {
        # le message de la semaine : vivant, « terminée » (lundi avant 9h), final
        "titres": {"en_cours": "🏁 GRAND PRIX DES SUBS — COURSE EN COURS 🍄",
                   "termine": "🏁 GRAND PRIX DES SUBS — COURSE TERMINÉE",
                   "final": "🏆 GRAND PRIX DES SUBS — PODIUM DE LA SEMAINE"},
        "lignes": {"en_cours": "🔴 _La course continue… rien n'est joué !_",
                   # même promesse que sans thème : l'heure, et CE message
                   "termine": "🏁 _Ligne d'arrivée franchie ! Le podium officiel arrive {quand}, "
                              "sur ce message._",
                   "final": "🔒 _Course terminée : le podium ne bougera plus._"},
        # rouge Mario pendant la course, or une fois la ligne franchie
        "couleurs": {"en_cours": 0xE52521, "termine": 0xF8C51C, "final": 0xF8C51C},
        "primes": "🏆 **Le podium de la course gagne des pièces :**",
        # la quinzaine : bleu Mario vivante, or figée
        "subs": "🏎️ Championnat des subs",
        "couleurs_subs": {"vivant": 0x049CD8, "final": 0xF8C51C},
        # servies par Flask (dossier static/ du dépôt), publiques pour Discord
        "vignettes": {"podium": "podium/grand_prix.png", "subs": "podium/championnat.png"},
        # 1er, 2e, 3e : les têtes des personnages (emojis du serveur, voir
        # _assurer_emojis), sinon ces trois-là
        "emojis": ["kart_mario", "kart_luigi", "kart_peach"],
        "repli": ["👑", "⭐", "🍄"],
        "piece": "🪙",                 # à la place du 💰 : même montant, même règle
        # Devant les places 4 et plus. Proprietaire, 03/10/2026 : « la liste
        # de VA et tout, et pour le podium aussi, tout le VA quoi » -- le rond
        # vert laissait le reste du classement hors de la course. Un kart dit
        # qu'ils y sont encore ; les trois premiers gardent leur tête.
        "suite": "🏎️",
        "bouton": "Relancer la course",
    },
}

# Les PNG des têtes, versionnés avec le code (le VPS n'a rien à dessiner).
EMOJIS_DOSSIER = Path(__file__).resolve().parent / "emojis"
EMOJI_MAX_OCTETS = 256 * 1024          # au-delà, Discord refuse l'emoji
# Le dossier static/ du dépôt, que Flask (web_upload) sert à /static/ : les
# vignettes y sont, Discord va les y chercher.
STATIC_DOSSIER = Path(__file__).resolve().parent / "static"


def _theme(gid: Optional[str]) -> Optional[Dict[str, Any]]:
    """L'habillage du serveur, ou None (pas de clé, thème inconnu, pas de serveur)."""
    if not gid:
        return None
    return THEMES.get(str(_profil(gid).get("theme") or ""))


def _fichier_emojis() -> Path:
    # relu à chaque appel, pas figé à l'import : les tests déplacent DATA_DIR
    # dans un dossier temporaire, et le vrai data/ ne doit jamais être touché
    return DATA_DIR / "podium_emojis.json"


def _emojis_connus(gid: str) -> Dict[str, str]:
    """{nom: id} des têtes connues sur ce serveur, lues dans le cache. Aucun réseau."""
    d = _lire(_fichier_emojis(), {})
    g = d.get(str(gid)) if isinstance(d, dict) else None
    if not isinstance(g, dict):
        return {}
    return {str(k): str(v) for k, v in g.items() if str(v).isdigit()}


def _marqueurs(gid: Optional[str], tetes: bool = True) -> List[str]:
    """Les marqueurs des trois premières places. Appelé par les rendus : il
    LIT le cache, il ne demande jamais rien à Discord (le rendu doit marcher
    sans réseau, et un relevé ne doit pas attendre des emojis).

    Les trois têtes ou aucune : un Mario à côté d'un ⭐ ferait croire à un
    message cassé. Sans thème, les médailles d'avant.
    `tetes=False` : 👑 ⭐ 🍄 même si le cache a les têtes (message figé dont
    les têtes n'ont pas pu être vérifiées, voir _tetes_sures).
    """
    th = _theme(gid)
    if not th:
        return list(MEDAILLES)
    ids = _emojis_connus(str(gid))
    if tetes and all(n in ids for n in th["emojis"]):
        return [f"<:{n}:{ids[n]}>" for n in th["emojis"]]
    return list(th["repli"])


@functools.lru_cache(maxsize=None)
def _version_statique(rel: str) -> str:
    """Les huit premiers caractères du md5 de static/<rel>, ou "" s'il manque.

    Lu une fois par processus : un déploiement redémarre le bot, et l'image
    ne change qu'avec lui.
    """
    try:
        return hashlib.md5((STATIC_DOSSIER / rel).read_bytes()).hexdigest()[:8]
    except OSError as e:
        # dit une seule fois (le résultat est gardé), pas à chaque rendu : la
        # vignette manquera sur Discord, le message, lui, part entier
        print(f"[podium] vignette static/{rel} illisible ({type(e).__name__}) : adresse "
              "sans version, l'image manquera sur Discord", flush=True)
        return ""


def _vignette(th: Dict[str, Any], quoi: str) -> Dict[str, str]:
    """La vignette en haut à droite de l'embed : une adresse publique du site,
    que Discord va chercher lui-même.

    L'adresse porte la version du fichier (« ?v= »). Le site marque toute
    réponse sous /static/, 404 compris, « public, max-age=604800, immutable »
    (web_upload._perf_after_request), et Cloudflare s'y tient : une seule
    demande de l'adresse AVANT la mise en ligne (le 03/10, en relisant ce
    thème) gardait le 404 sept jours dans le cache de Cloudflare, et le
    podium serait resté sans image. La requête fait partie de la clé de cache
    de Cloudflare (vérifié : un « ?v= » neuf repart chez Flask) ; une image
    changée plus tard sous le même nom change aussi d'adresse, et se voit
    aussitôt au lieu d'une semaine après.
    """
    from verif_discord import SITE
    rel = th["vignettes"][quoi]
    v = _version_statique(rel)
    return {"url": f'{SITE.rstrip("/")}/static/{rel}' + (f"?v={v}" if v else "")}


def _tetes_du_serveur(liste: List[Any], noms: List[str], connus: Dict[str, str]) -> Dict[str, str]:
    """{nom: id} des têtes que la liste des emojis du serveur porte vraiment.

    La liste fait foi, pas le cache. Une tête « indisponible » (perdue avec
    les boosts du serveur) ne s'affiche plus : elle ne compte pas. Deux du
    même nom : celle du cache si elle y est encore (celle des messages déjà
    postés).
    """
    sur_place: Dict[str, List[str]] = {}
    for e in liste:
        if (isinstance(e, dict) and e.get("name") in noms and str(e.get("id") or "").isdigit()
                and e.get("available", True) is not False):
            sur_place.setdefault(str(e["name"]), []).append(str(e["id"]))
    return {n: (connus[n] if connus.get(n) in sur_place[n] else sur_place[n][0])
            for n in noms if sur_place.get(n)}


def _tetes_sures(gid: str) -> bool:
    """Juste avant le rendu d'un message FIGÉ : les têtes du cache sont-elles
    encore sur le serveur ? False : ce message-là prend 👑 ⭐ 🍄.

    _assurer_emojis ne regarde la liste qu'une fois par jour. Une tête
    supprimée à la main entre-temps gardait son identifiant dans le cache,
    et un message figé l'affichait POUR TOUJOURS en « :kart_luigi: »
    (reproduit en revue : supprimée le lundi à 8h, vérifiée à 00h10, le
    podium de 9h la portait ; la pose du lendemain ne touche plus un message
    figé). Ici, une simple lecture de la liste, hors de la limite d'un essai
    par jour : aucune création, aucune permission requise, et quelques gels
    par semaine seulement. Appelé par poster_podium, _figer_semaine,
    _primes_retenues et _figer_quinzaine ; jamais par un rendu, ni pour le
    « terminée » du lundi, que le podium de 9h réécrit de toute façon.

    Une tête disparue quitte aussi le cache : les messages vivants passent
    en 👑 ⭐ 🍄 jusqu'à ce que la pose du lendemain la refasse. Liste
    illisible : False — 👑 ⭐ 🍄 sont toujours justes, une tête invérifiée
    ne l'est peut-être plus, et ce message ne sera jamais corrigé — mais le
    cache est gardé (une liste ratée ne prouve rien, voir _assurer_emojis).
    Sans thème, ou sans les trois têtes au cache, rien à relire : aucun appel.
    """
    th = _theme(gid)
    noms = list((th or {}).get("emojis") or [])
    if not noms:
        return True
    gid = str(gid)
    connus = _emojis_connus(gid)
    if not all(n in connus for n in noms):
        return True                    # le rendu est déjà en repli
    repli = " ".join(th["repli"])
    try:
        code, rep = _api("GET", f"/guilds/{gid}/emojis")
    except Exception as e:
        code, rep = None, f"{type(e).__name__}: {e}"
    if code != 200 or not isinstance(rep, list):
        print(f"[podium] {gid} : têtes du thème non vérifiées avant un message figé (liste "
              f"illisible, HTTP {code}) {str(rep)[:120]} — {repli} sur ce message", flush=True)
        return False
    neufs = _tetes_du_serveur(rep, noms, connus)
    if any(neufs.get(n) != connus.get(n) for n in noms):
        d = _lire(_fichier_emojis(), {})
        if not isinstance(d, dict):
            d = {}
        d[gid] = neufs
        safe_json.write(_fichier_emojis(), d)
        partis = [n for n in noms if n not in neufs]
        refaits = [n for n in noms if n in neufs and neufs[n] != connus[n]]
        print(f"[podium] {gid} : têtes du thème relues avant un message figé"
              + (f" — plus sur le serveur : {', '.join(partis)} (supprimée(s) à la main ?), "
                 f"{repli} sur ce message et jusqu'à la pose de demain" if partis else "")
              + (f" — reposée(s) à la main sous un autre identifiant, reprise(s) : "
                 f"{', '.join(refaits)}" if refaits else ""), flush=True)
    return True


def _assurer_emojis(gid: str) -> Dict[str, str]:
    """Pose sur le serveur les têtes des personnages (kart_mario…), une fois.

    Appelé par les passages qui parlent DÉJÀ à Discord (rafraichir,
    rafraichir_subs, poster_podium, et donc les gels), jamais par un rendu.
    Le cache data/podium_emojis.json garde {serveur: {nom: id}} ; Discord
    n'est interrogé qu'une fois par jour au plus : la liste des emojis du
    serveur (une tête supprimée à la main est vue, et refaite), puis la
    création de celles qui manquent, depuis les PNG de emojis/.

    Rien ici ne doit bloquer ni casser un podium : sans la permission
    « Gérer les expressions » (403, Discord 50013), serveur plein ou Discord
    en panne, le message part avec 👑 ⭐ 🍄, le journal le dit UNE fois, et
    l'essai suivant attend le lendemain — pas une rafale de refus toutes les
    dix minutes. Une liste illisible ne crée rien : sans elle, on ne sait pas
    si les têtes existent déjà, et Discord accepte deux emojis du même nom
    (un emplacement perdu sur cinquante).
    """
    th = _theme(gid)
    noms = list((th or {}).get("emojis") or [])
    if not noms:
        return {}
    gid = str(gid)
    try:
        return _assurer_emojis_sur(gid, noms, th)
    except Exception as e:
        # l'essai du jour est déjà noté (voir plus bas) : pas de nouvel essai
        # avant demain, même sur une erreur inattendue
        print(f"[podium] {gid} : têtes du thème : {type(e).__name__}: {e} — marqueurs "
              f"{' '.join(th['repli'])} en attendant, nouvel essai demain", flush=True)
        return _emojis_connus(gid)


def _assurer_emojis_sur(gid: str, noms: List[str], th: Dict[str, Any]) -> Dict[str, str]:
    fichier = _fichier_emojis()
    d = _lire(fichier, {})
    if not isinstance(d, dict):
        d = {}
    connus = _emojis_connus(gid)
    essais = d.get("_essais") if isinstance(d.get("_essais"), dict) else {}
    d["_essais"] = essais
    jour = _aujourdhui().isoformat()
    if (essais.get(gid) or {}).get("jour") == jour:
        return connus
    # noté AVANT d'appeler Discord : une exception plus bas, ou un arrêt du
    # bot au milieu, ne relance pas l'essai au passage suivant
    essais[gid] = {"jour": jour}
    safe_json.write(fichier, d)

    repli = " ".join(th["repli"])
    code, rep = _api("GET", f"/guilds/{gid}/emojis")
    if code != 200 or not isinstance(rep, list):
        echec = f"liste des emojis du serveur illisible (HTTP {code}) {str(rep)[:120]}"
        essais[gid]["echec"] = echec
        safe_json.write(fichier, d)
        print(f"[podium] {gid} : têtes du thème non vérifiées — {echec}. "
              + ("Têtes du cache gardées" if all(n in connus for n in noms)
                 else f"Marqueurs {repli} en attendant")
              + ", nouvel essai demain", flush=True)
        return connus

    # ce que le serveur porte vraiment : la liste fait foi, pas le cache
    neufs = _tetes_du_serveur(rep, noms, connus)
    disparus = [n for n in noms if n in connus and n not in neufs]

    crees: List[str] = []
    echec = ""
    for n in [n for n in noms if n not in neufs]:
        png = EMOJIS_DOSSIER / f"{n}.png"
        try:
            octets = png.read_bytes()
        except OSError as e:
            echec = f"{png.name} illisible ({type(e).__name__})"
            break
        if len(octets) > EMOJI_MAX_OCTETS:
            echec = f"{png.name} trop lourd ({len(octets)} octets, Discord en refuse plus de 256 Ko)"
            break
        code, rep = _api("POST", f"/guilds/{gid}/emojis", json={
            "name": n, "roles": [],
            "image": "data:image/png;base64," + base64.b64encode(octets).decode("ascii")})
        if code in (200, 201) and isinstance(rep, dict) and str(rep.get("id") or "").isdigit():
            neufs[n] = str(rep["id"])
            crees.append(n)
            continue
        dc = rep.get("code") if isinstance(rep, dict) else None
        echec = (f"création de {n} refusée (HTTP {code}" + (f", Discord {dc}" if dc else "") + ")"
                 + (" : il manque au bot la permission « Gérer les expressions »"
                    if code == 403 or dc == 50013 else f" {str(rep)[:120]}"))
        # la même cause refuserait les suivantes : on s'arrête là, demain on
        # ne refera que celles qui manquent encore
        break

    d[gid] = neufs
    if echec:
        essais[gid]["echec"] = echec
    safe_json.write(fichier, d)
    if echec:
        print(f"[podium] {gid} : têtes du thème incomplètes — {echec}. Marqueurs {repli} en "
              f"attendant, nouvel essai demain"
              + (f" (prêtes : {', '.join(sorted(neufs))})" if neufs else ""), flush=True)
    elif crees or disparus or neufs != connus:
        trouvees = [n for n in noms if n in neufs and n not in crees and connus.get(n) != neufs[n]]
        print(f"[podium] {gid} : têtes du thème prêtes"
              + (f", créées : {', '.join(crees)}" if crees else "")
              + (f", trouvées sur le serveur : {', '.join(trouvees)}" if trouvees else "")
              + (f" (supprimées à la main, refaites : {', '.join(disparus)})" if disparus else ""),
              flush=True)
    return neufs


# ─── un seul passage à la fois ───────────────────────────────────────────
# La boucle de dix minutes (web_upload) et le bouton « 🔄 Mettre à jour »
# (traiter) appellent les mêmes fonctions. Deux passages en même temps
# liraient chacun l'état, posteraient chacun le message neuf de la semaine
# (ou de la quinzaine), et le dernier à écrire effacerait l'autre : un
# message en double dans le salon, et un message vivant oublié. Le verrou est
# UN pour tout le module, pas un par serveur : podium.json est un seul
# fichier pour tous les serveurs, et un clic sur Va IG pendant que la boucle
# écrit Twitter perdrait l'écriture de l'un des deux (chacun réécrit le
# fichier entier, lu avant l'autre).
# Jamais d'attente : le clic répond « déjà en cours » (Discord ne donne que
# 3 s pour répondre), la boucle saute ce passage et le refait au tour suivant.
_VERROU = threading.Lock()
# vrai dans le travail d'un clic, qui tient déjà le verrou (pris par
# traiter, rendu par _maj_en_fond, dans un autre fil)
_TIENT = contextvars.ContextVar("podium_tient_le_verrou", default=False)


def _exclusif(f):
    @functools.wraps(f)
    def enveloppe(gid, *args, **kw):
        if _TIENT.get():
            return f(gid, *args, **kw)
        if not _VERROU.acquire(blocking=False):
            print(f"[podium] {f.__name__} {gid} : une mise à jour tourne déjà (bouton 🔄 ou "
                  "boucle), passage sauté, repris au prochain tour", flush=True)
            return ""
        jeton = _TIENT.set(True)
        try:
            return f(gid, *args, **kw)
        finally:
            _TIENT.reset(jeton)
            _VERROU.release()
    return enveloppe


# ─── la semaine ──────────────────────────────────────────────────────────
def saison_en_cours(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """La quinzaine : du 1er au 15, ou du 16 à la fin du mois.

    Même découpage que les rangs et les quêtes — un seul calendrier dans la
    tête des VA, sinon « la saison » ne veut plus rien dire.
    """
    j = jour or _aujourdhui()
    if j.day <= 15:
        return j.replace(day=1), j.replace(day=15)
    fin = (j.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return j.replace(day=16), fin


def semaine_en_cours(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi de la semaine où l'on est, et AUJOURD'HUI.

    La fin n'est pas le dimanche à venir : demander des clics sur des jours
    qui n'existent pas encore ne rend rien de plus, et afficher « au 28/09 »
    un mardi laisserait croire que la semaine est finie.
    """
    j = jour or _aujourdhui()
    return j - dt.timedelta(days=j.weekday()), j


def semaine_passee(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi et le dimanche de la semaine QUI VIENT DE FINIR.

    Un lundi, rend la semaine d'avant. Un autre jour, la dernière semaine
    complète : un rattrapage à la main donne alors le même message.
    """
    j = jour or _aujourdhui()
    lundi = j - dt.timedelta(days=j.weekday() + 7)
    return lundi, lundi + dt.timedelta(days=6)


# ─── qui est qui ─────────────────────────────────────────────────────────
def personne(nom_du_lien: str) -> Tuple[str, bool]:
    """« (Gerome) SPAM » → (« Gerome », True). « ( BO7 ) 1 » → (« BO7 », False).
    « Roucham - ( spam ) » (nom Infloww) → (« Roucham », True)."""
    n = str(nom_du_lien or "").strip()
    # Le nom des trackings Infloww, que le propriétaire veut aussi pour les
    # liens GetMySocial (06/10/2026 : « mettre exactement le même nom que celle
    # du inflow ») : la personne est AVANT les parenthèses, qui disent seulement
    # normal ou spam. La règle des parenthèses aurait donné « normal » à tous.
    # La même règle que le report des clics (clics_personnes.nom_infloww) : deux
    # lectures d'un même nom finissent par dire deux personnes.
    import clics_personnes as _cp
    infloww = _cp.nom_infloww(n)
    if infloww:
        nom, spam = personne(infloww[0])
        return nom, spam or infloww[1]
    # « Twitter VA 1 @abdoul », « va_@abdoul » : quand le nom porte une
    # arobase, c'est le pseudo qui suit qui designe la personne. Sans cette
    # regle, le nom entier devenait la cle — un numero de VA par libelle, et
    # « Twitter VA 1 @abdoul » n'aurait rien eu a voir avec « abdoul ».
    arobase = re.search(r"@\s*([A-Za-z0-9._-]{2,32})", n)
    if arobase:
        return arobase.group(1).strip("._-"), ("SPAM" in n.upper())
    dedans = re.search(r"\(([^)]*)\)", n)
    if dedans:
        base = dedans.group(1).strip()
    else:
        # PAS de rognage du chiffre final. « BO7 » devenait « BO » : une entite
        # fantome, un numero de VA gaspille a vie, et les clics du vrai BO7
        # coupes en deux. Et rogner « VA 9 » aurait donne « VA », ce qui fond
        # en un seul compte tous les liens du cache de repli. Sans parentheses,
        # le nom est pris tel quel.
        base = re.sub(r"\s+SPAM\s*$", "", n, flags=re.IGNORECASE).strip()
    return (base or n), ("SPAM" in n.upper())


def cle_entite(nom: str, spam: bool) -> str:
    return f"{nom} SPAM" if spam else nom


def liens_bruts(gid: Optional[str] = None) -> Tuple[List[Dict[str, Any]], bool]:
    """(liens, frais) sur TOUS les espaces de VA du serveur.

    `frais` n'est vrai que si chaque espace a repondu. Un seul repli sur le
    cache suffit a le rendre faux : le message le dira, plutot que de laisser
    croire a une liste complete.
    """
    equipes = list(_profil(gid).get("equipes") or _config().get("equipes") or
                   ([_config()["equipe"]] if _config().get("equipe") else EQUIPES_VA))
    tout: List[Dict[str, Any]] = []
    vus = set()
    frais = True
    for equipe in equipes:
        liens = None
        try:
            import gms
            # force_refresh : la liste est mise en cache deux minutes cote gms,
            # et un lien cree la veille doit apparaitre des le lendemain.
            with _etiquette("podium"):
                r = gms.list_links_team(equipe, force_refresh=True) or {}
            vivants = r.get("links") or r.get("data") or []
            if r.get("ok") is not False and vivants:
                liens = vivants
        except Exception as e:
            print(f"[podium] liste {equipe} : {type(e).__name__}: {e}", flush=True)
        if liens is None:
            frais = False
            liens = _lire(LIENS_CACHE, {}).get(equipe) or []
            print(f"[podium] espace {equipe} : repli sur le cache "
                  f"({len(liens)} lien(s))", flush=True)
        for l in liens:
            if isinstance(l, dict) and l.get("id") and l["id"] not in vus:
                vus.add(l["id"])
                tout.append(l)
    return tout, frais


def _nom_du_lien(l: Dict[str, Any]) -> str:
    return str(l.get("display_name") or l.get("title") or l.get("shortcode") or "")


def gabarits(liens: List[Dict[str, Any]],
             rattachements: Optional[Dict[str, str]] = None) -> List[str]:
    """Les noms des liens qu'entites() écarte comme gabarits, pour le dire.

    Les pages de base des liens d'identité US (« TEMPLATE ibenhaastrup »)
    vivent dans JESSY LE RETOUR, au milieu des liens des VA : un gabarit
    écarté sans trace, c'est un lien que personne ne regarde plus."""
    import clics_personnes as _cp
    ratt = _cp.rattachements_identite() if rattachements is None else rattachements
    return sorted(_nom_du_lien(l) for l in liens
                  if _cp.commence_par_gabarit(_nom_du_lien(l)) and str(l.get("id") or "") not in ratt)


def entites(liens: List[Dict[str, Any]],
            rattachements: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
    """{clé: {nom, spam, ids}} — une personne, ou son lien SPAM, comptés à part.

    DEUX EXCEPTIONS AU NOM DU LIEN, et ce sont les mêmes partout (podium,
    page Infloww, paie : tous passent par ici) :
      - un GABARIT n'est personne : la page de base « TEMPLATE ibenhaastrup »
        prenait sinon un numéro de VA à vie dans podium_numeros.json, une
        ligne de la page Infloww et des appels GetMySocial chaque jour. La
        règle ÉTROITE (clics_personnes.commence_par_gabarit : le nom commence
        par le mot), pas celle du report des clics : en sous-chaîne, « Twitter
        VA 5 @teamplayer » sortait du podium, de la page Infloww et de la paie ;
      - une PAGE D'IDENTITÉ US va à la personne de son lien global, par le
        registre (clics_personnes.rattachements_identite), quel que soit son
        nom — tant que le global est dans la même liste. Ses clics comptent
        alors pour lui, et son lien de suivi est le sien.
    `rattachements` : {id page: id global}, lu dans le registre si absent."""
    import clics_personnes as _cp
    ratt = _cp.rattachements_identite() if rattachements is None else rattachements
    noms = {str(l.get("id")): _nom_du_lien(l) for l in liens if l.get("id")}
    out: Dict[str, Dict[str, Any]] = {}
    for l in liens:
        lid = str(l["id"])
        nom_l = _nom_du_lien(l)
        if _cp.commence_par_gabarit(nom_l) and lid not in ratt:
            continue
        glob = ratt.get(lid, "")
        if glob in noms and not _cp.commence_par_gabarit(noms[glob]):
            nom_l = noms[glob]
        nom, spam = personne(nom_l)
        c = cle_entite(nom, spam)
        e = out.setdefault(c, {"nom": nom, "spam": spam, "ids": []})
        e["ids"].append(lid)
    return out


def entites_fr(liens: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Va IG : {« amelia:3 »: {nom « Amelia VA 3 », model, numero, ids}}.

    Le numero est dans le nom du lien (« Amelia VA 3 @pseudo ») : c'est celui
    du VA dans sa model, le meme que son ticket. Les liens en plus d'un compte
    de test (« Amelia VA 3-2 @… ») vont au meme VA ; le lien de base « Amelia
    1 » et tout ce qui n'est pas un lien de VA est ecarte. Aucun pseudo dans
    le libelle : le classement reste anonyme, comme sur Twitter."""
    import liens_fr
    out: Dict[str, Dict[str, Any]] = {}
    for l in liens:
        dn = str(l.get("display_name") or "").strip()
        model = liens_fr.model_du_nom(dn)
        m = re.search(r" VA (\d+)(?:-\d+)? @", dn)
        if not model or not m:
            continue
        n = int(m.group(1))
        cle = f"{model}:{n}"
        e = out.setdefault(cle, {"nom": f'{liens_fr.MODELS[model]["nom"]} VA {n}', "spam": False,
                                 "ids": [], "model": model, "numero": n})
        e["ids"].append(str(l["id"]))
    return out


def _clics(pays: Optional[Dict[str, Any]], profil: Dict[str, Any]) -> int:
    return sum(int((pays or {}).get(p) or 0) for p in profil["pays"])


def numeros(cles: List[str], attribuer: bool = True) -> Dict[str, int]:
    """La table clé → numéro de VA, complétée et gardée sur disque.

    Un numéro déjà donné ne change plus. Les nouveaux sont attribués dans
    l'ordre alphabétique, pour qu'un même lot donne toujours le même résultat.
    """
    table = dict(_lire(NUMEROS_FICHIER, {}))
    if not table:
        table = {k: v for k, v in NUMEROS_HISTORIQUES.items()}
    pris = set(int(v) for v in table.values())
    neuf = False
    if not attribuer:
        # Liste non rafraichie : les noms viennent du cache, qui porte l'ANCIENNE
        # convention (« VA 9 », « Gaspacio »). Leur donner un numero le graverait
        # pour toujours, sur une panne passagere. On rend ce qu'on sait deja.
        return {k: int(v) for k, v in table.items()}
    for c in sorted(cles):
        if c in table:
            continue
        n = 1
        while n in pris:
            n += 1
        table[c] = n
        pris.add(n)
        neuf = True
    if neuf:
        safe_json.write_text(NUMEROS_FICHIER,
                             json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True))
    return {k: int(v) for k, v in table.items()}


# ─── Twitter : les clics des liens de tracking (clé « mesure ») ──────────
# Propriétaire, 06/10/2026 : « compte uniquement que les clics sur inflow ».
# Les liens de JESSY LE RETOUR venaient de passer sur des pages Emy, chacune
# avec le tracking Infloww de son VA (« Roucham - ( normal ) », emy.brw/c42),
# et il voulait nommer les liens GetMySocial exactement comme dans Infloww. Or
# le podium reconnaissait chaque VA au nom du lien. Depuis, sur Twitter :
#   - un VA est reconnu à son TRACKING : onlyfans.com/<créatrice>/cNN, l'url du
#     lien direct ou celle d'un bouton de la page ;
#   - le numéro d'un tracking est gravé à sa première lecture
#     (podium_trackings.json) : renommer le lien ou le tracking ne le change
#     plus, et plusieurs liens sur un même tracking ne le comptent qu'une fois ;
#   - les clics sont les visites du tracking sur la période, lues dans MyPuls
#     (Infloww ne donne qu'un total depuis la création). Tous pays : MyPuls ne
#     les découpe pas ;
#   - un tracking qui n'est plus derrière aucun lien actif (le VA est passé
#     sur un autre, son lien est désactivé) compte jusqu'au jour où on l'a vu
#     partir, pas après : la semaine du changement garde ses clics d'avant.
# Le registre se tient avec la liste fraîche des liens. Sans elle (GetMySocial
# en pause ou muet), on compte les trackings déjà connus : un lien tout neuf
# attend son retour, et ses clics de la période ne sont pas perdus pour autant
# (MyPuls les rend par période, une fois le tracking connu).
# Va IG garde ses clics GetMySocial, y compris pour les VA US qu'il affiche :
# ses primes mêlent les deux marchés, et les y mesurer autrement aurait changé
# ce que touchent les VA FR (propriétaire : « Seulement les VA US »).
MP_CACHE_S = 90
#: Un tracking neuf que MyPuls ne connaît pas encore : on attend qu'il le
#: connaisse (son nom peut seul départager certains VA), mais pas plus que ça.
#: Au-delà, c'est le lien qui pointe vers un tracking qui n'existe pas.
ATTENTE_MYPULS_J = 2
#: Une liste de liens lue il y a moins que ça suffit : la pause nocturne de
#: GetMySocial ne doit pas afficher « liste non rafraîchie » chaque nuit.
FRAIS_REGISTRE_H = 24
#: MyPuls met ses trackings à jour par paliers de plusieurs heures (06/10 : rien
#: entre 02h53 et 08h04, puis rien jusqu'à 10h54 au moins). Une journée finie à
#: minuit n'a donc tous ses clics que le lendemain matin : le bonus de la veille
#: est complété jusqu'à cette heure-là, et la quinzaine attend pour se figer.
RATTRAPAGE_MYPULS_H = 12
_MP_LUS: Dict[Tuple[str, str], Tuple[float, Dict[str, Dict[str, Any]]]] = {}
_URL_TRACKING = re.compile(r"onlyfans\.com/([A-Za-z0-9._-]+)/c(\d+)(?:[/?#]|$)", re.IGNORECASE)


def _fichier_trackings() -> Path:
    # relu à chaque appel, comme _fichier_releves : les tests déplacent DATA_DIR
    return DATA_DIR / "podium_trackings.json"


def _source(gid: Optional[str] = None, mesure: Optional[str] = None) -> str:
    """Ce que valent les clics : « tracking » (MyPuls) ou « gms »."""
    return str(mesure or _profil(gid).get("mesure") or "gms")


def _service(gid: Optional[str] = None) -> str:
    """Le service à nommer quand un relevé manque."""
    return "MyPuls" if _source(gid) == "tracking" else "GetMySocial"


def _pause_pour(gid: Optional[str]) -> bool:
    """La pause de GetMySocial n'arrête que ce qui en dépend. Sur Twitter, la
    liste des liens attend son retour ; le registre et MyPuls suffisent, et le
    bonus du jour (payé) ne doit pas se figer pendant des heures."""
    return _pause_gms() if _source(gid) == "gms" else False


def _mesure_dite(pf: Dict[str, Any]) -> str:
    """Ce que le message dit compter : « tracking OF », ou le marché (« US »)."""
    return "tracking OF" if pf.get("mesure") == "tracking" else str(pf["marche"])


def tracking_de(url: Any) -> str:
    """« https://onlyfans.com/Emy.Brw/c042/ » → « emy.brw/c42 » ; "" si l'url
    n'est pas un lien de tracking OnlyFans (« onlyfans.com/emy.brw » seul)."""
    m = _URL_TRACKING.search(str(url or "").strip())
    return f"{m.group(1).lower()}/c{int(m.group(2))}" if m else ""


def trackings_du_lien(l: Dict[str, Any]) -> List[str]:
    """Les trackings d'un lien : son url (lien direct), celles de ses boutons
    (page). Un bouton éteint, s'il le dit, n'envoie personne."""
    urls = [l.get("url")] + [
        b.get("url") for b in (l.get("buttons") or [])
        if isinstance(b, dict) and b.get("enabled") is not False and b.get("active") is not False
        and b.get("hidden") is not True and b.get("visible") is not False]
    out: List[str] = []
    for u in urls:
        t = tracking_de(u)
        if t and t not in out:
            out.append(t)
    return out


def _actif(l: Dict[str, Any]) -> bool:
    # un lien désactivé ne reçoit plus personne
    return str(l.get("status") or "active").strip().lower() == "active"


def _norme(cle: str) -> str:
    """« Gérôme », « GEROME », « gerome » : la même clé (MyPuls écrit « Gérôme »
    et « Eud », les liens « (Gerome) » et « EUD »)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(cle or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().casefold()


def _base_nom(cle: str) -> str:
    """« tsiry 1 SPAM » → « tsiry » ; « VA 2 Narovana » → « narovana » : ce qui
    nomme la personne, sans SPAM, ni numéro de téléphone, ni « VA n » de tête."""
    n = re.sub(r"\s+SPAM$", "", str(cle or "").strip(), flags=re.IGNORECASE)
    n = re.sub(r"\s+\d+$", "", n)
    n = re.sub(r"^va\s*\d+\s+", "", _norme(n))
    return n.strip()


def _meme_personne(a: str, b: str) -> bool:
    """« tsiry 1 » et « tsiry 2 » (deux téléphones), « (VA 2 Narovana) » et
    « Narovana - ( normal ) » (un renommage à moitié fait) : une personne.
    « VA 1 Noum » et « VA 2 Noum » restent deux personnes."""
    x, y = _base_nom(a), _base_nom(b)
    if not x or not y:
        return False
    if x == y:
        return _norme(a) == _norme(b) or not (re.match(r"^va\s*\d", _norme(a))
                                              and re.match(r"^va\s*\d", _norme(b)))
    return len(x) >= 3 and len(y) >= 3 and (x in y or y in x)


def _personnes(cles: List[str]) -> List[List[str]]:
    """Les clés regroupées par personne (voir _meme_personne)."""
    groupes: List[List[str]] = []
    for c in cles:
        for g in groupes:
            if any(_meme_personne(c, x) for x in g):
                g.append(c)
                break
        else:
            groupes.append([c])
    return groupes


def _proche(nom: str, cles: List[str]) -> bool:
    """Le nom d'un tracking neuf ressemble-t-il à l'un des noms connus d'un
    numéro ? « Ricrado » / « Ricardo », « Niavo » / « VA 1 Niavo » : oui.
    Sert à ne pas donner à un VA neuf, sur un lien repris, le numéro de celui
    qui l'avait avant lui."""
    import difflib
    x = _base_nom(nom)
    for c in cles:
        y = _base_nom(c)
        if x and y and (x in y or y in x or difflib.SequenceMatcher(None, x, y).ratio() >= 0.6):
            return True
    return False


def _lire_mypuls(du: str, au: str, forcer: bool = False
                 ) -> Tuple[Optional[Dict[str, Dict[str, Any]]], str]:
    """{tracking: {visites, total, nom}} de TOUS les trackings MyPuls sur
    [du, au] (jours de Paris, bornes comprises), ou (None, pourquoi).
    visites : sur la période ; total : depuis la création, jusqu'à `au`.

    L'API brute, pas mypuls.api_tracking_links : celle-ci rend [] (ou une
    vieille liste) quand l'API tombe, et une panne serait passée pour des
    zéros — de l'argent. Les bornes que MyPuls dit avoir comptées sont
    vérifiées, et une liste tronquée est refusée."""
    t0 = time.time()
    deja = _MP_LUS.get((du, au))
    if deja and not forcer and 0 <= t0 - deja[0] < MP_CACHE_S:
        return deja[1], ""
    try:
        import mypuls
        r = mypuls.api_get("tracking-links", {"per_page": 500, "from": du, "to": au})
    except Exception as e:                                   # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict) or not r.get("ok"):
        return None, (str((r or {}).get("error") if isinstance(r, dict) else r or "")[:200]
                      or "pas de réponse")
    d = r.get("data")
    items = d.get("data") if isinstance(d, dict) else None
    if not isinstance(items, list):
        return None, "réponse MyPuls sans liste de trackings"
    per = d.get("period") if isinstance(d.get("period"), dict) else {}
    if str(per.get("from") or "")[:10] != du or str(per.get("to") or "")[:10] != au:
        return None, (f'MyPuls a compté du {str(per.get("from") or "?")[:10]} au '
                      f'{str(per.get("to") or "?")[:10]}, pas du {du} au {au}')
    try:
        compte = int(d.get("count"))
    except (TypeError, ValueError):
        compte = None
    if compte is not None and compte > len(items):
        # l'API rend tout d'un coup (vérifié le 06/10 : 654 sur 654, `page`
        # ignoré). Si un jour elle découpe : les pages suivantes, et si le
        # compte n'y est toujours pas, on le dit au lieu de compter zéro
        vus_url = {str(it.get("url") or "").lower() for it in items if isinstance(it, dict)}
        for page in range(2, 21):
            try:
                r2 = mypuls.api_get("tracking-links", {"per_page": 500, "from": du, "to": au,
                                                       "page": page})
            except Exception:                                # noqa: BLE001
                break
            d2 = r2.get("data") if isinstance(r2, dict) and r2.get("ok") else None
            neufs = [it for it in ((d2 or {}).get("data") or []) if isinstance(it, dict)
                     and str(it.get("url") or "").lower() not in vus_url]
            if not neufs:
                break
            items = items + neufs
            vus_url |= {str(it.get("url") or "").lower() for it in neufs}
            if len(items) >= compte:
                break
        if compte > len(items):
            return None, f"MyPuls annonce {compte} trackings et n'en rend que {len(items)}"
    out: Dict[str, Dict[str, Any]] = {}
    ecartes, doublons = 0, 0
    for it in items:
        t = tracking_de(it.get("url")) if isinstance(it, dict) else ""
        if not t:
            ecartes += 1
            continue
        if t in out:
            # la première ligne fait foi, comme sur la page Liens Infloww
            doublons += 1
            continue

        def _n(x):
            try:
                return int(x)
            except (TypeError, ValueError):
                return None
        out[t] = {"visites": _n(it.get("visits_period")), "total": _n(it.get("visits_total")),
                  "nom": str(it.get("name") or "").strip()}
    if ecartes or doublons:
        print(f"[podium] MyPuls {du} → {au} : {ecartes} ligne(s) sans url de tracking, "
              f"{doublons} en double (la première gardée)", flush=True)
    _MP_LUS[(du, au)] = (t0, out)
    for k in [k for k, (t, _) in _MP_LUS.items() if not 0 <= t0 - t < MP_CACHE_S]:
        _MP_LUS.pop(k, None)
    return out, ""


def _lire_registre() -> Dict[str, Any]:
    """{trackings: {t: entrée}, attente: {t: …}, frais: dernière liste fraîche}."""
    reg = _lire(_fichier_trackings(), {})
    if not isinstance(reg, dict):
        reg = {}
    for k in ("trackings", "attente"):
        if not isinstance(reg.get(k), dict):
            reg[k] = {}

    def jour_ok(x) -> bool:
        try:
            return len(str(x)) == 10 and bool(dt.date.fromisoformat(str(x)))
        except ValueError:
            return False
    # Le registre se corrige à la main (un tracking passé à quelqu'un d'autre) :
    # une entrée mal écrite est écartée et dite, jamais une exception qui
    # arrêterait toute la boucle (Va IG, les liens, le Drive passent après)
    for t, e in list(reg["trackings"].items()):
        ok = isinstance(e, dict) and jour_ok(e.get("vu")) and jour_ok(e.get("premier"))
        try:
            ok = ok and int(e.get("numero")) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            print(f"[podium] podium_trackings.json : entrée {t} illisible, écartée : "
                  f"{str(e)[:160]}", flush=True)
            reg["trackings"].pop(t)
    for t, e in list(reg["attente"].items()):
        if not isinstance(e, dict) or not jour_ok(e.get("premier")):
            reg["attente"].pop(t)
    return reg


def _suivre_trackings(reg: Dict[str, Any], liens: List[Dict[str, Any]],
                      noms_mp: Dict[str, str], jour: str, maintenant: str
                      ) -> Dict[str, Any]:
    """Tient le registre à jour sur la liste FRAÎCHE des liens et une lecture
    MyPuls RÉUSSIE (sans elles, ne pas l'appeler : un numéro gravé sur une
    information incomplète l'est pour toujours).

    Un tracking neuf prend le numéro que donnent, ensemble :
      a. ses liens, quand ils portaient déjà un tracking enregistré (le même
         lien GetMySocial passé de jessyewdiference/c88 à emy.brw/c42 : même
         VA, même normal ou spam) ;
      b. le nom de ses liens (« (Roucham) 1 » → 12 ; « tsiry 1 » et « tsiry 2 »,
         deux téléphones d'une même personne, → le plus petit) ;
      c. son nom dans MyPuls (« Laboule ( X ) » → 34).
    Un seul numéro : il le prend. Aucun : un numéro neuf, comme un VA neuf.
    Plusieurs, ou des liens qui nomment plusieurs personnes : CONFLIT, il
    n'est pas enregistré et les VA en cause passent « sans relevé » tant que
    ça dure (le journal dit pourquoi) — jamais les clics d'un autre sur un VA
    au hasard. Seul le lien le dit (a), et le nom ne ressemble à aucun de ceux
    du numéro : un lien repris par un autre VA, conflit aussi.
    Un tracking que MyPuls ne connaît pas encore attend son nom (au plus
    ATTENTE_MYPULS_J jours) : « Ricrado » ou un bouton spam sur la page d'un
    VA ne se départagent qu'avec lui. Ses VA probables passent sans relevé.
    Son nom Infloww (« Ricrado - ( normal ) ») devient alias du numéro trouvé :
    un lien renommé comme dans Infloww retrouve le même VA, ici comme dans le
    relevé GetMySocial que garde Va IG.
    Rend {sans_tracking, conflits: {tracking enregistré: VA en doute}}."""
    import clics_personnes as _cp
    regs: Dict[str, Dict[str, Any]] = reg["trackings"]
    attente: Dict[str, Dict[str, Any]] = reg["attente"]
    ratt = _cp.rattachements_identite()
    noms = {str(l.get("id")): _nom_du_lien(l) for l in liens if l.get("id")}
    derriere: Dict[str, List[Tuple[str, str]]] = {}
    sans: List[str] = []
    for l in liens:
        lid = str(l.get("id") or "")
        nom_l = _nom_du_lien(l)
        if not _actif(l) or (_cp.commence_par_gabarit(nom_l) and lid not in ratt):
            continue
        # une page d'identité US est à la personne de son lien global (entites)
        glob = ratt.get(lid, "")
        if glob in noms and not _cp.commence_par_gabarit(noms[glob]):
            nom_l = noms[glob]
        ts = trackings_du_lien(l)
        if not ts:
            sans.append(nom_l)
        for t in ts:
            if (lid, nom_l) not in derriere.setdefault(t, []):
                derriere[t].append((lid, nom_l))

    table = dict(_lire(NUMEROS_FICHIER, {})) or dict(NUMEROS_HISTORIQUES)
    index: Dict[str, set] = {}
    for k, v in table.items():
        index.setdefault(_norme(k), set()).add(int(v))

    def num(cle: str) -> Optional[int]:
        s = index.get(_norme(cle)) or set()
        return next(iter(s)) if len(s) == 1 else None

    def par_les_noms(liens_t: List[Tuple[str, str]], spam: bool) -> Tuple[set, int]:
        """(numéros que donnent les noms des liens, nombre de personnes qu'ils
        nomment). Le nom dit la personne ; normal ou spam, c'est le tracking
        qui le dit (une page porte souvent les deux boutons)."""
        cles = sorted({cle_entite(personne(nom)[0], spam) for _, nom in liens_t})
        groupes = _personnes(cles)
        nums: set = set()
        for g in groupes:
            # deux téléphones d'une personne, deux numéros : le plus petit
            ng = {n for n in (num(c) for c in g) if n is not None}
            if ng:
                nums.add(min(ng))
        return nums, len(groupes)

    def par_le_nom_mypuls(nom_mp: str) -> str:
        # seul un nom de VA en dit quelque chose : « Roucham - ( normal ) » ou
        # « Twitter VA 31 @pseudo ». « Twitter », « VA 3 », « E » ou « SFS 06/10 »
        # sont des libellés, qui rencontreraient par hasard une clé du tableau
        if nom_mp and (_cp.nom_infloww(nom_mp) or "@" in nom_mp):
            return cle_entite(*personne(nom_mp))
        return ""

    conflits: Dict[str, List[int]] = {}
    for t, e in regs.items():
        if t in derriere:
            e.update(actif=True, vu=jour,
                     ids=sorted({lid for lid, _ in derriere[t]} | set(e.get("ids") or []))[-12:],
                     liens=sorted({nom for _, nom in derriere[t]})[:8])
            # un tracking derrière les liens d'une autre personne aussi, ou
            # dont les liens disent aujourd'hui un autre VA : il a peut-être
            # changé de mains. Le numéro gravé reste, mais ses VA passent sans
            # relevé tant que ça dure — pas de prime sur les clics d'un autre
            nums, n_pers = par_les_noms(derriere[t], bool(e.get("spam")))
            doute = sorted((nums | {int(e["numero"])}) if n_pers > 1 or nums - {int(e["numero"])}
                           else [])
            if doute:
                conflits[t] = doute
            if doute != (e.get("doute") or []):
                print(f'[podium] tracking {t} (VA {e["numero"]}) : ses liens '
                      f'{sorted({nom for _, nom in derriere[t]})[:6]} disent VA {doute} — '
                      "sans relevé jusqu'à ce que GetMySocial ou podium_trackings.json soit "
                      "corrigé" if doute else
                      f"[podium] tracking {t} (VA {e['numero']}) : liens et numéro de nouveau "
                      "d'accord", flush=True)
                if doute:
                    e["doute"] = doute
                else:
                    e.pop("doute", None)
        elif e.get("actif"):
            # parti aujourd'hui : il compte jusqu'à aujourd'hui compris
            e.update(actif=False, vu=jour)
            print(f'[podium] tracking {t} (VA {e["numero"]}) : plus derrière aucun lien actif, '
                  f"compté jusqu'au {jour}", flush=True)

    a_numeroter: List[Tuple[str, str]] = []
    alias: Dict[str, int] = {}
    for t in sorted(derriere):
        if t in regs:
            attente.pop(t, None)
            continue
        nom_mp = noms_mp.get(t, "")
        att = attente.setdefault(t, {"premier": jour})
        att.update(liens=sorted({nom for _, nom in derriere[t]})[:8],
                   ids=sorted({lid for lid, _ in derriere[t]}))
        cle_t = par_le_nom_mypuls(nom_mp)
        if nom_mp and (_cp.nom_infloww(nom_mp) or "@" in nom_mp):
            spam = personne(nom_mp)[1]
        else:
            spam = any(personne(nom)[1] for _, nom in derriere[t])
        ids_t = {lid for lid, _ in derriere[t]}
        # a : le même lien portait, avant, un tracking aujourd'hui quitté
        quittes = {u: e for u, e in regs.items()
                   if not e.get("actif") and ids_t & set(e.get("ids") or [])
                   and bool(e.get("spam")) == spam}
        a = {int(e["numero"]) for e in quittes.values()}
        b, n_pers = par_les_noms(derriere[t], spam)
        c = {num(cle_t)} - {None} if cle_t else set()
        cands = a | b | c
        trop_tot = (not nom_mp
                    and (dt.date.fromisoformat(jour) - dt.date.fromisoformat(att["premier"])).days
                    < ATTENTE_MYPULS_J)
        pourquoi = ""
        if trop_tot:
            pourquoi = "pas encore dans MyPuls"
        elif n_pers > 1:
            pourquoi = f"derrière les liens de {n_pers} personnes"
        elif len(cands) > 1:
            pourquoi = f"liens et nom aux numéros {sorted(cands)}"
        elif a and not (b | c):
            # seul le lien le dit : renommé, ou repris par quelqu'un d'autre ?
            # Le nom tranche, s'il ressemble à l'un de ceux du numéro
            nom_neuf = cle_t or cle_entite(*personne(derriere[t][0][1]))
            n_a = next(iter(a))
            if not _proche(nom_neuf, [k for k, v in table.items() if int(v) == n_a]
                           + [str(e.get("cle") or "") for e in quittes.values()]):
                pourquoi = f"lien repris par quelqu'un d'autre ? (il était au VA {n_a})"
        if pourquoi:
            if att.get("pourquoi") != pourquoi:
                print(f"[podium] tracking {t} ({nom_mp or '?'}) en attente : {pourquoi} — "
                      f"liens {att['liens']}", flush=True)
            att.update(pourquoi=pourquoi, numeros=sorted(cands),
                       conflit=not trop_tot)
            continue
        cle = cle_t or cle_entite(personne(derriere[t][0][1])[0], spam)
        n = next(iter(cands)) if cands else None
        regs[t] = {"numero": n, "cle": cle, "spam": spam, "nom": nom_mp,
                   "liens": att["liens"], "ids": att["ids"], "mp": bool(nom_mp),
                   "premier": att["premier"], "vu": jour, "actif": True}
        attente.pop(t, None)
        # le lien passe au nouveau tracking : l'ancien n'en témoigne plus (un
        # lien repris plus tard par quelqu'un d'autre n'hérite pas de ce VA)
        for e in quittes.values():
            e["ids"] = sorted(set(e.get("ids") or []) - ids_t)
        if n is None:
            a_numeroter.append((t, cle))
        elif cle_t and _cp.nom_infloww(nom_mp) and num(cle_t) is None:
            alias[cle_t] = n
        print(f"[podium] tracking {t} ({nom_mp or 'inconnu de MyPuls'}) : "
              + (f"VA {n}" if n is not None else "numéro neuf")
              + f" (liens {att['liens'][:4]})", flush=True)
    for t in [t for t in attente if t not in derriere]:
        attente.pop(t, None)
    if a_numeroter:
        tab = numeros(sorted({c for _, c in a_numeroter}))
        for t, c in a_numeroter:
            regs[t]["numero"] = int(tab[c])
            print(f"[podium] tracking {t} : VA {tab[c]} (neuf)", flush=True)
            # Va IG compte encore ces VA par le nom de leurs liens (relevé
            # GetMySocial) : le même numéro des deux côtés, pas « VA 46 » ici et
            # « VA 47 » là-bas pour la même personne
            for nom in regs[t]["liens"]:
                k = cle_entite(personne(nom)[0], bool(regs[t]["spam"]))
                if num(k) is None:
                    alias.setdefault(k, int(tab[c]))
    if alias:
        tab = dict(_lire(NUMEROS_FICHIER, {})) or dict(NUMEROS_HISTORIQUES)
        ajoute = {k: v for k, v in alias.items() if k not in tab}
        if ajoute:
            tab.update(ajoute)
            safe_json.write_text(NUMEROS_FICHIER, json.dumps(tab, ensure_ascii=False,
                                                             indent=2, sort_keys=True))
    reg["frais"] = maintenant
    return {"sans_tracking": sorted(sans), "conflits": conflits}


def _classement_tracking(debut: dt.date, fin: dt.date, gid: Optional[str] = None,
                         cumul: bool = False) -> Dict[str, Any]:
    """classement() sur les clics des liens de tracking : la même forme
    {lignes, illisibles, frais, …}, pour que le reste (numéros affichés, gel,
    primes) ne voie pas la différence. En plus : sans_tracking (liens actifs
    sans tracking, pas comptés), introuvables (trackings que MyPuls n'a jamais
    rendus, au-delà de l'attente : comptés zéro), en_attente (trackings neufs
    sans numéro encore), source, erreur.
    `cumul` : le total depuis la création (visits_total) au lieu des visites
    de la période — MyPuls ne garde pas tout l'historique jour par jour.

    UNE LECTURE RATÉE N'EST JAMAIS UN ZÉRO. MyPuls muet : aucun relevé (les
    messages restent tels quels). Un tracking qu'il a déjà rendu et qu'il ne
    rend plus (une clé qui ne voit pas cette créatrice) : relu une fois, puis
    son VA passe sans relevé."""
    d0, d1 = debut.isoformat(), fin.isoformat()
    aujourd = _aujourdhui()
    jour = aujourd.isoformat()
    vide = {"lignes": [], "illisibles": [], "frais": False, "entites": 0, "liens": 0,
            "sans_numero": [], "gabarits": [], "sans_tracking": [], "introuvables": [],
            "en_attente": [], "conflits": [], "source": "tracking", "erreur": ""}
    liens, frais_liste = liens_bruts(gid)
    reg = _lire_registre()
    avant = json.dumps(reg, sort_keys=True, ensure_ascii=False)
    regs = reg["trackings"]
    lus: Dict[Tuple[str, str], Tuple[Optional[Dict[str, Dict[str, Any]]], str]] = {}

    def lire(du: str, au: str):
        if (du, au) not in lus:
            vus, raison = _lire_mypuls(du, au)
            connus = {t for t, e in regs.items() if isinstance(e, dict) and e.get("mp")}
            if vus is not None and connus - set(vus):
                # les clés MyPuls ne voient pas toutes les mêmes créatrices,
                # et l'appel tourne de l'une à l'autre : une seconde chance
                vus2, raison2 = _lire_mypuls(du, au, forcer=True)
                if vus2 is not None and len(connus - set(vus2)) < len(connus - set(vus)):
                    vus = vus2
            lus[(du, au)] = (vus, raison)
        return lus[(du, au)]

    principal, raison = lire(d0, d1)
    if principal is None:
        print(f"[podium] MyPuls {d0} → {d1} : {raison} — aucun relevé", flush=True)
        return dict(vide, erreur=raison, liens=len(liens))
    for t, e in regs.items():
        if isinstance(e, dict) and t in principal:
            e["mp"] = True          # MyPuls l'a rendu : son absence, un jour, sera une panne
    import clics_personnes as _cp
    info: Dict[str, Any] = {"sans_tracking": [], "conflits": {}}
    if frais_liste:
        info = _suivre_trackings(reg, liens, {t: v["nom"] for t, v in principal.items()},
                                 jour, _maintenant().isoformat(timespec="minutes"))
    gab = gabarits(liens, _cp.rattachements_identite())
    # une liste lue il y a peu suffit : la pause de GetMySocial chaque nuit ne
    # doit pas dire « des comptes peuvent manquer » à chaque passage
    try:
        recente = (_maintenant() - dt.datetime.fromisoformat(str(reg.get("frais") or ""))
                   ).total_seconds() < FRAIS_REGISTRE_H * 3600
    except ValueError:
        recente = False
    frais = bool(frais_liste or recente)

    par_va: Dict[int, List[Tuple[str, str, Dict[str, Any]]]] = {}
    for t, e in regs.items():
        if not isinstance(e, dict) or e.get("numero") is None:
            continue
        fin_t = d1 if e.get("actif") else min(d1, str(e.get("vu") or ""))
        if fin_t < d0:
            continue
        par_va.setdefault(int(e["numero"]), []).append((t, fin_t, e))

    illisibles: set = set()
    introuvables: List[str] = []
    totaux: Dict[int, int] = {}
    for n in sorted(par_va):
        total = 0
        for t, fin_t, e in par_va[n]:
            garde = e.get("cumul") or {}
            if cumul and not e.get("actif") and garde.get("au") == fin_t:
                # un tracking quitté ne bouge plus : son total est gardé
                total += int(garde.get("n") or 0)
                continue
            vus, _ = lire(d0, fin_t)
            v = (vus or {}).get(t)
            if vus is None:
                illisibles.add(n)
            elif v is None:
                deja = bool(e.get("mp"))
                jeune = (aujourd - dt.date.fromisoformat(str(e.get("premier") or jour))
                         ).days < ATTENTE_MYPULS_J
                if deja or jeune:
                    illisibles.add(n)
                else:
                    # jamais rendu par MyPuls, bien au-delà de l'attente : le
                    # lien pointe vers un tracking qui n'existe pas. Zéro, et dit
                    introuvables.append(t)
            else:
                x = v["total"] if cumul else v["visites"]
                if x is None:
                    illisibles.add(n)
                else:
                    total += x
                    if cumul and not e.get("actif"):
                        e["cumul"] = {"au": fin_t, "n": x}
        totaux[n] = total
    en_attente: List[str] = []
    conflits: List[str] = []
    for t, e in regs.items():
        if e.get("doute") and (e.get("actif") or str(e.get("vu") or "") >= d0):
            # ses liens disent un autre VA, ou plusieurs : à corriger à la main
            illisibles.update(int(x) for x in e["doute"])
            conflits.append(t)
    for t, att in reg["attente"].items():
        if str(att.get("premier") or "") > d1:
            continue            # vu après la période : il n'y était pour rien
        nums = [int(x) for x in (att.get("numeros") or [])]
        if att.get("conflit"):
            conflits.append(t)
        if nums:
            # un VA dont un tracking attend : son compte n'est pas complet
            illisibles.update(nums)
        elif not att.get("conflit"):
            en_attente.append(t)
    lignes = [{"va": f"VA {n}", "numero": n, "clics": totaux[n],
               "liens": len(par_va[n]),
               "spam": any(bool(e.get("spam")) for _, _, e in par_va[n]), "model": ""}
              for n in sorted(par_va) if n not in illisibles]
    if json.dumps(reg, sort_keys=True, ensure_ascii=False) != avant:
        safe_json.write(_fichier_trackings(), reg)
    if not lignes:
        # tout le monde sans relevé, c'est que la lecture n'a rien donné :
        # « aucun relevé », et les messages restent comme ils sont
        print(f"[podium] {d0} → {d1} : aucun VA lisible ({len(illisibles)} sans relevé)",
              flush=True)
        return dict(vide, erreur="aucun VA lisible", liens=len(liens), frais=frais)
    if info["sans_tracking"]:
        print(f'[podium] {len(info["sans_tracking"])} lien(s) actif(s) sans tracking OnlyFans, '
              "pas comptés : " + ", ".join(info["sans_tracking"][:8]), flush=True)
    if introuvables:
        print(f"[podium] {len(introuvables)} tracking(s) que MyPuls n'a jamais rendus, comptés "
              "à zéro (lien à vérifier) : " + ", ".join(sorted(introuvables)[:8]), flush=True)
    lignes.sort(key=lambda x: (-x["clics"], x["model"], x["numero"]))
    return {"lignes": lignes, "illisibles": sorted(f"VA {n}" for n in illisibles),
            "frais": frais, "entites": len(par_va), "liens": len(liens), "sans_numero": [],
            "gabarits": gab, "sans_tracking": info["sans_tracking"],
            "introuvables": sorted(set(introuvables)), "en_attente": sorted(en_attente),
            "conflits": sorted(set(conflits)), "source": "tracking", "erreur": ""}


# ─── le classement ───────────────────────────────────────────────────────
def classement(debut: dt.date, fin: dt.date, pause: float = 0.3,
               gid: Optional[str] = None, mesure: Optional[str] = None) -> Dict[str, Any]:
    """{lignes, illisibles, frais} — les clics du marché du serveur (US pour
    Twitter) par entité, du plus fort au plus faible. Twitter : les clics
    des liens de tracking (_classement_tracking). `mesure="gms"` force les
    clics GetMySocial (le relevé US que Va IG garde, voir _releve_us)."""
    if _source(gid, mesure) == "tracking":
        # pas gardé pour Va IG : il mêle des clics GetMySocial (_releve_us)
        return _classement_tracking(debut, fin, gid)
    import gms
    profil = _profil(gid)
    d0, d1 = debut.isoformat(), fin.isoformat()
    liens, frais = liens_bruts(gid)
    gab: List[str] = []
    if profil["fr"]:
        ents = entites_fr(liens)
        # le numero vient du nom du lien : rien a attribuer ici, et la table
        # de Twitter (podium_numeros.json) n'est pas touchee
        table = {c: e["numero"] for c, e in ents.items()}
    else:
        import clics_personnes as _cp
        ratt = _cp.rattachements_identite()
        ents = entites(liens, ratt)
        gab = gabarits(liens, ratt)
        if gab:
            # ni numero, ni ligne, ni appel : mais dit, une fois par releve
            print(f"[podium] {len(gab)} gabarit(s) ecarte(s) : " + ", ".join(gab[:6]), flush=True)
        # Twitter compte ses VA aux trackings : là, et là seulement, naissent
        # les numéros. Le relevé GetMySocial que Va IG garde de ces VA n'en
        # invente pas (un lien renommé avant que le registre ne le voie aurait
        # pris un numéro neuf, puis disputé le sien à son tracking)
        table = numeros(list(ents.keys()), attribuer=frais and _source(gid) == "gms")
    sans_numero = [c for c in ents if c not in table]
    if sans_numero:
        print(f"[podium] {len(sans_numero)} compte(s) sans numero, ecartes : "
              + ", ".join(sorted(sans_numero)[:6]), flush=True)
    lignes: List[Dict[str, Any]] = []
    illisibles: List[str] = []
    for cle, e in ents.items():
        if cle not in table:
            continue
        try:
            with _etiquette("podium"):
                _, pays = gms.analytics_for_links(e["ids"], d0, d1)
        except Exception:
            pays = None
        va = e["nom"] if profil["fr"] else f'VA {table.get(cle, 0)}'
        if pays is None:
            illisibles.append(va)
        else:
            lignes.append({"va": va, "numero": table.get(cle, 999),
                           "clics": _clics(pays, profil),
                           "liens": len(e["ids"]), "spam": e["spam"],
                           "model": e.get("model", "")})
        time.sleep(pause)
    # à égalité, le numéro départage : deux relevés de la même semaine doivent
    # rendre le même ordre, sinon le podium changerait tout seul d'un appel à l'autre
    lignes.sort(key=lambda x: (-x["clics"], x["model"], x["numero"]))
    out = {"lignes": lignes, "illisibles": sorted(illisibles), "frais": frais,
           "entites": len(ents), "liens": len(liens),
           "sans_numero": sorted(sans_numero), "gabarits": gab}
    # Twitter relève de toute façon ses VA pour ses propres messages : Va IG
    # reprend ce relevé au lieu d'en refaire un (voir _releve_us)
    _retenir(gid, debut, fin, out)
    return out


def _fichier_alltime(gid: Optional[str] = None, mesure: Optional[str] = None) -> Path:
    """Un fichier par serveur, et par mesure : les totaux GetMySocial des VA US
    (que Va IG affiche encore) et ceux de leurs trackings (Twitter, depuis le
    06/10/2026) ne se mêlent jamais."""
    profil = _profil(gid)
    if _source(gid, mesure) == "tracking":
        return DATA_DIR / "podium_alltime_tracking.json"
    return DATA_DIR / profil["alltime"] if profil.get("alltime") else ALLTIME_FICHIER


def alltime(gid: Optional[str] = None, mesure: Optional[str] = None) -> Dict[str, int]:
    """Le total « depuis toujours » par entité, recalculé une fois par jour.

    Ce chiffre ne bouge presque pas d'une heure à l'autre : le redemander à
    chaque rafraîchissement doublait le nombre d'appels pour rien, et volait
    le quota du tableau de bord. Un fichier par serveur : « VA 3 » de Twitter
    et « Amelia VA 3 » de Va IG ne sont pas la même personne.
    """
    profil = _profil(gid)
    fichier = _fichier_alltime(gid, mesure)
    cache = _lire(fichier, {})
    if cache.get("jour") == _aujourdhui().isoformat() and cache.get("totaux"):
        return {k: int(v) for k, v in cache["totaux"].items()}
    if _source(gid, mesure) == "tracking":
        # le total cumulé de chaque tracking : MyPuls ne garde pas tout
        # l'historique jour par jour (c47 : 20 378 visites rendues sur
        # « 2024 → 2026 », 31 030 au compteur)
        cl = _classement_tracking(dt.date.fromisoformat(ALLTIME_DEPUIS), _aujourdhui(), gid,
                                  cumul=True)
        totaux = dict(cache.get("totaux") or {})
        for x in cl["lignes"]:
            totaux[x["va"]] = int(x["clics"])
        # un relevé troué garde l'ancien total de ceux qui manquent. Gravé pour
        # la journée quand même : un conflit qui dure le referait à chaque
        # passage (deux listes GetMySocial et MyPuls), pour un chiffre qui ne
        # paie rien. Sans aucune ligne, il sera refait au prochain passage
        jour = _aujourdhui().isoformat() if cl["lignes"] else str(cache.get("jour") or "")
        if totaux:
            safe_json.write_text(fichier, json.dumps({"jour": jour, "totaux": totaux},
                                                     ensure_ascii=False, indent=2,
                                                     sort_keys=True))
        return {k: int(v) for k, v in totaux.items()}
    import gms
    liens, _ = liens_bruts(gid)
    if profil["fr"]:
        ents = entites_fr(liens)
        table = {c: e["numero"] for c, e in ents.items()}
    else:
        ents = entites(liens)
        table = numeros(list(ents.keys()), attribuer=_source(gid) == "gms")
    fin = _aujourdhui().isoformat()
    totaux = dict(cache.get("totaux") or {})
    for cle, e in ents.items():
        if cle not in table:
            continue                # sans numéro (voir classement) : pas de « VA 0 »
        try:
            with _etiquette("podium"):
                _, pays = gms.analytics_for_links(e["ids"], ALLTIME_DEPUIS, fin)
        except Exception:
            pays = None
        if pays is not None:
            # un relevé raté garde l'ancien total plutôt que de l'effacer
            totaux[e["nom"] if profil["fr"] else f'VA {table.get(cle, 0)}'] = _clics(pays, profil)
        time.sleep(0.3)
    safe_json.write_text(fichier,
                         json.dumps({"jour": fin, "totaux": totaux},
                                    ensure_ascii=False, indent=2, sort_keys=True))
    return {k: int(v) for k, v in totaux.items()}


# ─── Va IG : les VA US à côté des VA FR (temporaire, clé « avec_us ») ─────
# Les relevés de Twitter gardés en mémoire : {(gid, début, fin): {t, jour, cl}}.
# Un relevé, c'est un appel GetMySocial par VA de Twitter (une trentaine) :
# Twitter le fait déjà pour ses propres messages, Va IG le reprend. Un relevé
# de moins de deux heures (le rythme de Va IG) est repris tel quel ; un relevé
# pris APRÈS la fin de sa période la compte entière, et vaut pour toujours.
CACHE_US_MIN = 120
#: Les relevés de Twitter gardés pour Va IG. SUR DISQUE, pas seulement en
#: mémoire : le bot redémarre à chaque déploiement — soixante-six fois le
#: 03/10/2026 — et chaque redémarrage jetait ce que _releve_us est fait pour
#: réutiliser. Résultat : un relevé complet de vingt-sept appels refait au
#: passage suivant (et la quota GetMySocial, commune aux quatre clés du compte,
#: épuisée en fin de journée), ou, quand elle l'était déjà, les VA de Jessye
#: absents du podium alors qu'on les avait lus une heure plus tôt.
_RELEVES: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_RELEVES_LUS = False


def _fichier_releves() -> Path:
    # relu à chaque appel, pas figé à l'import : les tests déplacent DATA_DIR
    # dans un dossier temporaire, et le vrai data/ ne doit jamais être touché
    return DATA_DIR / "podium_releves.json"


def _cle_releve(cle: Tuple[str, str, str]) -> str:
    return "|".join(cle)


def _charger_releves() -> None:
    """Reprend les relevés du disque, une fois par processus."""
    global _RELEVES_LUS
    if _RELEVES_LUS:
        return
    _RELEVES_LUS = True
    d = _lire(_fichier_releves(), {})
    if not isinstance(d, dict):
        return
    t = time.time()
    repris = 0
    for k, e in d.items():
        bouts = str(k).split("|")
        if len(bouts) != 3 or not isinstance(e, dict):
            continue
        cl = e.get("cl")
        if not isinstance(cl, dict) or not cl.get("lignes"):
            continue
        # la même fenêtre de quatre jours qu'en mémoire : un relevé plus vieux
        # ne dit plus rien de la période en cours
        if not 0 <= t - float(e.get("t") or 0) <= 4 * 86400:
            continue
        _RELEVES[(bouts[0], bouts[1], bouts[2])] = {
            "t": float(e.get("t") or 0), "essai": float(e.get("essai") or e.get("t") or 0),
            "jour": str(e.get("jour") or ""), "cl": cl}
        repris += 1
    if repris:
        print(f"[podium] {repris} relevé(s) repris du disque (les VA de l'autre "
              "marché restent affichés après un redémarrage)", flush=True)


def _sauver_releves() -> None:
    """Écriture atomique : une coupure au mauvais moment laisserait un JSON
    tronqué, et le podium repartirait sans aucun relevé gardé."""
    try:
        safe_json.write(_fichier_releves(),
                        {_cle_releve(k): v for k, v in _RELEVES.items()})
    except Exception as e:                                   # noqa: BLE001
        print(f"[podium] relevés non enregistrés ({type(e).__name__}: {e}) — ils "
              "seront perdus au prochain redémarrage", flush=True)


def _qualite(cl: Dict[str, Any]) -> Tuple[bool, int, int]:
    """Plus grand = plus complet : liste des liens fraîche, moins de VA
    illisibles, plus de VA classés."""
    return (bool(cl.get("frais", True)), -len(cl.get("illisibles") or []),
            len(cl.get("lignes") or []))


def _retenir(gid: Optional[str], debut: dt.date, fin: dt.date, cl: Dict[str, Any]) -> None:
    """Garde un relevé de Twitter pour Va IG. Un relevé vide ne remplace rien,
    et un relevé plus pauvre ne remplace pas celui, plus complet, d'une
    période déjà finie."""
    if str(gid or "") != TWITTER_ID or not (cl or {}).get("lignes"):
        return
    _charger_releves()
    t = time.time()
    # quatre jours : une quinzaine figée au bout de 48 h (ABANDON_FIGER_H)
    # trouve encore le relevé de sa période entière
    for k in [k for k, e in _RELEVES.items() if not 0 <= t - e["t"] <= 4 * 86400]:
        _RELEVES.pop(k, None)
    cle = (TWITTER_ID, debut.isoformat(), fin.isoformat())
    jour = _aujourdhui().isoformat()
    neuf = {"lignes": [dict(x) for x in cl["lignes"]],
            "illisibles": list(cl.get("illisibles") or []),
            "frais": bool(cl.get("frais", True))}
    ancien = _RELEVES.get(cle)
    if (ancien and ancien["jour"] > fin.isoformat() and jour > fin.isoformat()
            and _qualite(ancien["cl"]) > _qualite(neuf)):
        # la période est finie, ses clics ne bougent plus : le relevé complet
        # de 00h10 restait écrasé par celui du podium de 9h où un VA n'avait
        # pas répondu, et Va IG figeait son podium sans ce VA, sans un mot
        ancien["essai"] = t
        _sauver_releves()
        return
    _RELEVES[cle] = {"t": t, "essai": t, "jour": jour, "cl": neuf}
    _sauver_releves()


def _releve_us(debut: dt.date, fin: dt.date) -> Optional[Dict[str, Any]]:
    """Le classement des VA de Twitter sur cette période, sans le refaire si
    Twitter vient de le faire. None si on ne l'a pas (pause, panne, vide).

    Un relevé pris après la fin de sa période la compte entière. S'il lui
    manque des VA (illisibles), il est relu, deux heures au moins après le
    dernier essai ; en attendant il est rendu tel quel, et le message dit
    qui manque (un VA illisible n'est pas un zéro, ni un absent)."""
    _charger_releves()
    cle = (TWITTER_ID, debut.isoformat(), fin.isoformat())
    e = _RELEVES.get(cle)
    t = time.time()
    entier = bool(e) and e["jour"] > fin.isoformat()
    if e:
        if entier:
            if (not e["cl"]["illisibles"] or _pause_gms()
                    or 0 <= t - float(e.get("essai") or e["t"]) < CACHE_US_MIN * 60):
                return e["cl"]
        # moins de deux heures ne suffit que pour une période en cours : la
        # quinzaine figée à 00h10 n'a pas à reprendre le relevé de 23h50,
        # qui n'a pas les clics de la dernière demi-heure
        elif fin >= _aujourdhui() and 0 <= t - e["t"] < CACHE_US_MIN * 60:
            return e["cl"]
    if _pause_gms():
        # quota épuisé : des chiffres US périmés, ou pris avant la fin de la
        # période (et figés pour toujours), seraient pires que de ne pas les
        # montrer — le message reste alors celui des seuls VA FR
        return None
    try:
        # les clics GetMySocial, même quand Twitter compte ceux des trackings :
        # Va IG les mêle à ses VA FR, mesurés ainsi, et les paie au rang
        cl = classement(debut, fin, gid=TWITTER_ID, mesure="gms")
    except Exception as ex:
        print(f"[podium] relevé US pour Va IG : {type(ex).__name__}: {ex}", flush=True)
        cl = {}
    _retenir(TWITTER_ID, debut, fin, cl)
    e2 = _RELEVES.get(cle)
    if e2 and ((cl or {}).get("lignes") or entier):
        # relevé raté : un relevé entier déjà gardé, même troué, vaut mieux que
        # rien (ses absents sont dits) ; un relevé d'avant la fin, non
        e2["essai"] = t
        _sauver_releves()
        return e2["cl"]
    return None


def _nom_us(pf: Dict[str, Any], va: str) -> str:
    """« VA 12 » de Twitter tel qu'il s'affiche sur ce serveur (« Jessye VA 12 »)."""
    return f'{pf["nom_us"]} {va}' if pf.get("nom_us") else str(va)


def _us_manquants(us: Optional[Dict[str, Any]]) -> List[str]:
    """Les VA US sans relevé, absents d'un classement mêlé : à dire, jamais à taire."""
    return list((us or {}).get("illisibles") or []) if (us or {}).get("lignes") else []


def _mele(gid: Optional[str]) -> bool:
    """Ce serveur montre-t-il les VA US à côté des siens ? Le seul endroit qui
    lit la clé « avec_us » : la retirer coupe tout d'un coup."""
    return str(gid or "") != TWITTER_ID and bool(_profil(gid).get("avec_us"))


def _us_pour(gid: Optional[str], debut: dt.date, fin: dt.date,
             cl: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Les VA US à montrer à côté des VA FR de ce serveur, ou None.

    None aussi quand le relevé FR est vide : un classement fait des seuls VA
    US ne doit jamais paraître sur Va IG (personne n'y serait payable).
    """
    if not _mele(gid):
        return None
    if not (cl or {}).get("lignes"):
        return None
    us = _releve_us(debut, fin)
    if us is None:
        print(f"[podium] {gid} : VA US non affichés ({debut} → {fin}), relevé Twitter "
              "indisponible — message avec les seuls VA FR", flush=True)
    elif us.get("illisibles"):
        print(f'[podium] {gid} : {len(us["illisibles"])} VA US sans relevé, signalés dans le '
              "message : " + ", ".join(us["illisibles"][:8]), flush=True)
    return us


def _melange(cl: Dict[str, Any], us: Optional[Dict[str, Any]],
             pf: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Les lignes FR et US en une seule liste, du plus fort au plus faible.

    None quand il n'y a rien à mêler : le message est alors exactement celui
    d'avant. Chaque ligne garde son marché en interne (rien ne l'affiche :
    il sert à garder les VA FR visibles, à prendre le bon all-time, à nommer
    au journal les VA US primés, déjà primés sur Twitter).

    « prime » va aux trois premiers de CETTE liste, quel que soit leur marché
    (propriétaire, 03/10/2026 : « les primes elles vont aux 3 meilleurs VA,
    c'est tout »), au montant de leur rang, s'ils ont au moins un sub — la
    règle de suivi_va._annoncer_primes_fr, qui reçoit cette même liste (voir
    _classement_paye) et passe un gagnant à zéro sans donner sa prime au
    suivant. À égalité de clics, le tri stable garde l'ordre de chaque
    classement, VA FR d'abord : le même ordre à chaque relevé, et donc la
    même prime.
    """
    if not us or not us.get("lignes") or not cl.get("lignes"):
        return None
    tw = SERVEURS[TWITTER_ID]
    fr = [dict(x, marche=pf["marche"]) for x in cl["lignes"]]
    # « affiche » : le nom montre ; « va » reste le libelle de Twitter, celui
    # des totaux all-time et du journal des primes a payer a la main
    autres = [dict(x, marche=tw["marche"], affiche=_nom_us(pf, x["va"])) for x in us["lignes"]]
    mix = sorted(fr + autres, key=lambda x: (-int(x.get("clics") or 0),
                                             x["marche"] != pf["marche"]))
    for rang, x in enumerate(mix[:len(PRIMES)]):
        if int(x.get("clics") or 0) > 0:
            x["prime"] = PRIMES[rang]
    return mix


def _classement_paye(gid: Optional[str], cl: Dict[str, Any],
                     us: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Le classement que suivi_va paie : celui que le podium AFFICHE.

    Mêlé (Va IG, clé « avec_us ») : la liste de toute l'agence, dans l'ordre
    du message. suivi_va annonce au rang de la ligne : un VA FR 2e derrière un
    VA US apprend « 2e — 5$ », comme le dit son 💰. Avant, il recevait le
    classement FR seul, et l'aurait annoncé 1er. Une ligne US n'a pas de
    model : suivi_va ne lui trouve aucun ticket et la range dans « inconnus »
    — _payer la nomme au journal, avec sa prime Twitter.
    Sans VA US à côté, le classement FR, comme avant.
    """
    mix = _melange(cl, us, _profil(gid))
    return cl if mix is None else dict(cl, lignes=mix)


# ─── le message ──────────────────────────────────────────────────────────
def _heure_podium() -> int:
    return int(_config().get("heure") or HEURE_POST)


def _horodatage() -> str:
    return _maintenant().strftime("%d/%m à %Hh%M")


def _instantane(cl: Dict[str, Any], fin: Optional[dt.date] = None) -> Dict[str, Any]:
    """Ce qu'on garde du dernier relevé réussi, pour pouvoir figer sans GetMySocial.

    Si GetMySocial ne rend rien le jour où une période se termine, son message
    doit quand même cesser de se dire « en cours » : on le fige alors sur ces
    chiffres-là, et le message dit de quand ils datent. `fin` : le dernier
    jour que ce relevé demandait (voir _couvre).
    """
    return {"lignes": [dict(x) for x in (cl.get("lignes") or [])],
            "illisibles": list(cl.get("illisibles") or []),
            "frais": bool(cl.get("frais", True)),
            "sans_numero": list(cl.get("sans_numero") or []),
            "sans_tracking": list(cl.get("sans_tracking") or []),
            "introuvables": list(cl.get("introuvables") or []),
            "en_attente": list(cl.get("en_attente") or []),
            "conflits": list(cl.get("conflits") or []),
            "le": _horodatage(),
            "jusqu_au": fin.isoformat() if fin else "",
            "le_iso": _maintenant().isoformat(timespec="minutes")}


def _couvre(snap: Dict[str, Any], fin: dt.date) -> bool:
    """Le relevé gardé compte-t-il la période ENTIÈRE, son dernier jour compris ?

    Il faut qu'il ait demandé ce jour-là ET qu'il ait été pris après : un
    relevé du dimanche 20h n'a pas les clics du dimanche soir. Celui du lundi
    00h10 (« semaine terminée ») les a : figer dessus ne trompe personne, et
    se passe d'un nouvel appel à GetMySocial.
    """
    try:
        return (bool(snap.get("lignes"))
                and str(snap.get("jusqu_au") or "") >= fin.isoformat()
                and str(snap.get("le_iso") or "")[:10] > fin.isoformat())
    except Exception:
        return False


# Un 403 de Discord n'est pas toujours définitif : 50001 (Missing Access) et
# 50013 (Missing Permissions) viennent des réglages du salon, et l'accès revient
# quand on le rend. Les prendre pour « message supprimé » notait la semaine
# figée et l'oubliait : une fois l'accès rendu, elle restait « SEMAINE EN
# COURS » pour toujours.
ACCES_RETIRE = (50001, 50013)


def _passager(code: Any, rep: Any = None) -> bool:
    """Discord injoignable, qui freine, ou un salon dont l'accès a été retiré :
    ça repassera, on réessaie plus tard sur le MÊME message.

    Un 404 (message supprimé à la main) ou un 403 50005 (message posté par un
    autre bot, que celui-ci ne peut pas éditer) ne repassera jamais : là, on
    se rabat tout de suite au lieu d'attendre pour rien.
    """
    try:
        c = int(code)
    except Exception:
        return True
    if c == 403 and isinstance(rep, dict):
        try:
            return int(rep.get("code") or 0) in ACCES_RETIRE
        except Exception:
            return False
    return c <= 0 or c == 429 or c >= 500


BOUTON_MAJ = "podium:maj"


def _boutons(gid: Optional[str], vivant: bool) -> Dict[str, Any]:
    """Ce qu'un message envoyé à Discord porte en plus de son embed.

    Vivant, sur un serveur à bouton : le bouton « 🔄 Mettre à jour ». Figé :
    « components » vide, envoyé exprès. Une édition qui ne dit rien des
    composants les GARDE : le message figé aurait encore proposé de mettre à
    jour une période finie. Serveur sans la clé (Twitter) : rien du tout, le
    message est celui d'avant, à l'octet près.
    Avec un thème, seul le libellé change (« Relancer la course ») : l'emoji
    et le custom_id restent, un bouton déjà posé continue de marcher.
    """
    pf = _profil(gid)
    if "bouton_maj" not in pf:
        return {}
    if not (vivant and pf["bouton_maj"]):
        return {"components": []}
    th = _theme(gid)
    return {"components": [{"type": 1, "components": [{
        "type": 2, "style": 2, "label": th["bouton"] if th else "Mettre à jour",
        "emoji": {"name": "🔄"}, "custom_id": BOUTON_MAJ}]}]}


def _notes_tracking(cl: Dict[str, Any]) -> List[str]:
    """Ce que le comptage par tracking (Twitter) laisse de côté, dit en
    nombre seulement : le classement est anonyme, un nom de lien n'y a pas
    sa place (le journal les nomme)."""
    out: List[str] = []
    n = len(cl.get("sans_tracking") or [])
    if n:
        out.append(f"ℹ️ _{n} lien{'s' if n > 1 else ''} sans tracking OnlyFans, "
                   f"pas compté{'s' if n > 1 else ''}._")
    n = len(cl.get("en_attente") or [])
    if n:
        # un VA neuf : pas encore de numéro, il paraîtra quand MyPuls le
        # connaîtra, avec tous ses clics de la période
        out.append(f"ℹ️ _{n} tracking{'s' if n > 1 else ''} neuf{'s' if n > 1 else ''} "
                   f"pas encore dans MyPuls, pas encore classé{'s' if n > 1 else ''}._")
    n = len(cl.get("conflits") or [])
    if n:
        # ne se règle pas tout seul : un lien GetMySocial à corriger
        out.append(f"⚠️ _{n} tracking{'s' if n > 1 else ''} partagé{'s' if n > 1 else ''} entre "
                   f"plusieurs VA ou changé{'s' if n > 1 else ''} de mains : leurs VA restent "
                   "sans relevé jusqu'à correction des liens._")
    n = len(cl.get("introuvables") or [])
    if n:
        out.append(f"⚠️ _{n} tracking{'s' if n > 1 else ''} introuvable{'s' if n > 1 else ''} "
                   f"dans MyPuls, compté{'s' if n > 1 else ''} à zéro : lien à vérifier._")
    return out


def _avert_dernier_releve(snap: Dict[str, Any], periode: str, gid: Optional[str] = None) -> str:
    return (f'⚠️ _Chiffres du dernier relevé ({snap.get("le") or "date inconnue"}) : '
            f"{_service(gid)} n'a pas rendu {periode} entière._")


def _avert_us(us: Optional[Dict[str, Any]], etat: str, liste_dite: bool = False,
              pf: Optional[Dict[str, Any]] = None) -> List[str]:
    """Les lignes « ⚠️ » d'un classement mêlé pour les VA US qui y manquent.

    Avant, un VA de Twitter sans relevé disparaissait du message de Va IG sans
    un mot (le journal seul le disait), et les médailles glissaient d'un cran.
    Les mots restent neutres (« Sans relevé », pas « VA US ») : le classement
    se présente comme celui de toute l'agence, sans marché ligne à ligne,
    mais qui manque est toujours dit, nom par nom.
    `etat` : en_cours, termine, paie (podium arrêté) ou final (quinzaine,
    sans prime) — ce qui sera encore relu, ou ce qu'il reste à faire.
    `liste_dite` : la liste FR, elle aussi périmée, l'a déjà dit — sans
    marché, une seconde ligne presque identique ne dirait rien de plus.
    """
    out: List[str] = []
    # les noms tels que le classement les montre (« Jessye VA 3 »)
    manque = [_nom_us(pf or {}, v) for v in _us_manquants(us)]
    if manque:
        plus = len(manque) > 1
        suite = {"en_cours": (", ils remonteront" if plus else ", il remontera")
                             + " au prochain passage.",
                 "termine": (", ils seront relus" if plus else ", il sera relu")
                            + " pour le podium officiel.",
                 # le podium arrêté paie les trois premiers de toute l'agence :
                 # un VA US absent a pu en être, et décaler les rangs payés —
                 # le même avertissement qu'un VA FR illisible
                 "paie": ", à confirmer avant de payer."}.get(etat, ".")
        out += ["", "⚠️ **Sans relevé** : " + ", ".join(manque)
                + f' — {"absents" if plus else "absent"} de ce classement' + suite]
    if (us or {}).get("lignes") and not us.get("frais", True) and not liste_dite:
        out += ["", "⚠️ _Liste des liens non rafraîchie : des VA peuvent manquer._"]
    return out


def _lignes_podium_mix(mix: List[Dict[str, Any]], pf: Dict[str, Any],
                       med: Optional[List[str]] = None,
                       th: Optional[Dict[str, Any]] = None) -> List[str]:
    """Les lignes du podium quand VA FR et VA US sont mêlés.

    Médailles et 💰 aux trois premières places, quel que soit le marché — le
    💰 seulement sur une ligne d'au moins un sub (voir _melange). Rien d'autre
    à côté du montant : le rang de la ligne EST celui que suivi_va annonce, et
    celui qu'on donne pour réclamer. Tous les VA FR restent visibles, même
    au-delà des quinze premiers : ce sont eux qui lisent ce salon, et un VA US
    plus fort en clics ne doit pas leur cacher leur rang.
    `med`, `th` : les marqueurs et le thème du serveur (têtes, 🪙, 🏎️) ; sans
    eux, les médailles et le 💰 d'avant.
    """
    med = med or MEDAILLES
    piece = th["piece"] if th else "💰"
    suite = f'{th["suite"]} ' if th else ""
    montres = [i for i, x in enumerate(mix)
               if i < COMBIEN_AFFICHES or x["marche"] == pf["marche"]]
    out: List[str] = []
    avant = -1
    for i in montres:
        x = mix[i]
        if i != avant + 1:
            out.append("…")
        avant = i
        if i < 3:
            # le même 💰 que Twitter ; absent sur une ligne à zéro sub, que
            # suivi_va ne paie pas (signalé le 03/10 : « 0 subs · 💰 3$ »)
            queue = f' · {piece} **{x["prime"]:.0f}$**' if x.get("prime") else ""
            out.append(f'{med[i]} **{x.get("affiche") or x["va"]}** — **{x["clics"]}** subs{queue}')
        else:
            out.append(f'{i + 1}. {suite}{x.get("affiche") or x["va"]} — **{x["clics"]}** subs')
    reste = len(mix) - len(montres)
    if reste > 0:
        out.append(f'… _et {reste} autre{"s" if reste > 1 else ""}_ 👏')
    return out


def embed_podium(cl: Dict[str, Any], debut: dt.date, fin: dt.date,
                 en_cours: bool = False, gid: Optional[str] = None,
                 termine: bool = False, avertissement: str = "",
                 us: Optional[Dict[str, Any]] = None, tetes: bool = True) -> Dict[str, Any]:
    """Le message de la semaine, dans l'un de ses trois états :

    - `en_cours` : le message vivant, réédité tout au long de la semaine ;
    - `termine` : le lundi avant l'heure du podium — la semaine entière est
      comptée, le podium officiel est annoncé pour l'heure dite ;
    - ni l'un ni l'autre : le résultat final. Il ne bougera plus, et il le dit.

    `us` (Va IG, clé « avec_us ») : le classement des VA de Twitter, mêlé à
    celui des VA FR (`cl`) ; les primes vont aux trois premiers de la liste
    mêlée, celle que suivi_va reçoit (_classement_paye).

    `tetes=False` (thème) : 👑 ⭐ 🍄 au lieu des têtes du cache — un message
    figé dont les têtes n'ont pas pu être vérifiées (_tetes_sures).
    """
    pf = _profil(gid)
    lignes = cl["lignes"]
    mix = _melange(cl, us, pf)
    tw = SERVEURS[TWITTER_ID]
    # le thème ne change que l'habillage (voir THEMES) ; sans lui, chaque
    # chaîne ci-dessous est celle d'avant
    th = _theme(gid)
    etat = "en_cours" if en_cours else "termine" if termine else "final"
    med = _marqueurs(gid, tetes)
    # mêlé, l'en-tête dit seulement que le classement couvre toute l'agence :
    # c'est vrai, et c'est le compromis annoncé au propriétaire (pas de VA US
    # rebaptisés en VA FR, pas de marché ligne à ligne)
    abo = (f'Abonnements via {pf["source"]} — clics **{_mesure_dite(pf)}**' if mix is None
           else "Abonnements de **toute l'agence**")
    if en_cours:
        c = [f'🗓️ **Semaine en cours** — depuis le **{debut.strftime("%d/%m")}**, '
             f'arrêté au **{fin.strftime("%d/%m")}**',
             abo,
             (th["lignes"]["en_cours"] if th
              else "🔴 _Mis à jour tout seul, plusieurs fois par jour. Rien n'est joué._"), ""]
    else:
        # passé l'heure (bot redémarré pendant que le podium échoue), « à 9h »
        # serait déjà faux
        quand = (f"ce lundi à {_heure_podium()}h" if _maintenant().hour < _heure_podium()
                 else "dans la journée")
        if th:
            dit = th["lignes"][etat].format(quand=quand)
        else:
            dit = (f"🏁 _Semaine terminée. Le podium officiel arrive {quand}, sur ce message._"
                   if termine
                   else "🔒 _Semaine terminée : classement arrêté, il ne bougera plus._")
        c = [f'🗓️ Semaine du **{debut.strftime("%d/%m")}** au **{fin.strftime("%d/%m/%Y")}**',
             abo, dit, ""]
    if mix is not None:
        c += _lignes_podium_mix(mix, pf, med, th)
    else:
        piece = th["piece"] if th else "💰"
        suite = f'{th["suite"]} ' if th else ""
        for i, x in enumerate(lignes[:COMBIEN_AFFICHES]):
            if i < 3:
                c.append(f'{med[i]} **{x["va"]}** — **{x["clics"]}** subs '
                         f'· {piece} **{PRIMES[i]:.0f}$**')
            else:
                c.append(f'{i + 1}. {suite}{x["va"]} — **{x["clics"]}** subs')
        reste = len(lignes) - COMBIEN_AFFICHES
        if reste > 0:
            c.append(f'… _et {reste} autre{"s" if reste > 1 else ""}_ 👏')
    if not lignes:
        c.append("_Aucun relevé cette semaine._")

    # mêlé aussi, les mots de Twitter : les primes vont aux trois premiers du
    # classement affiché, VA US compris (propriétaire, 03/10/2026), et le rang
    # affiché est celui qu'on réclame. Avant, « 🥈 2e VA FR » renvoyait à un
    # second classement, celui des seuls VA FR, que le message ne montrait pas.
    c += ["", th["primes"] if th else "🎁 **Les 3 meilleurs de la semaine touchent une prime :**"]
    for i, p in enumerate(PRIMES):
        c.append(f'{med[i]} {i + 1}{"er" if i == 0 else "e"} → **{p:.0f}$**')
    c += ["", f'💸 **Pour recevoir ta prime :** envoie un message à **@{pf["bot"]}** dans '
              "**ton espace perso** avec **ton rang de la semaine** et **ton adresse "
              "USDC (réseau Solana)**.",
          "Un seul prix par personne · payé à la main après vérification",
          "", "🔢 _Ton numéro de VA ne change jamais : c'est le même chaque semaine._"]

    if cl["illisibles"]:
        # « il remontera au prochain passage » n'est vrai que du message
        # vivant : un message figé n'a plus de prochain passage
        c += ["", "⚠️ **Classement incomplet** : " + ", ".join(cl["illisibles"])
                  + " — relevé indisponible"
                  + (", il remontera au prochain passage." if en_cours
                     else ", il sera relu pour le podium officiel." if termine
                     else ", à confirmer avant de payer.")]
    if not cl["frais"]:
        c += ["", "⚠️ _Liste des liens non rafraîchie (GetMySocial injoignable) : "
                  "des comptes peuvent manquer._"]
    if cl.get("sans_numero"):
        c += [f'ℹ️ _{len(cl["sans_numero"])} compte(s) pas encore numéroté(s), '
              "écarté(s) le temps que la liste revienne._"]
    c += _notes_tracking(cl)
    if mix is not None:
        c += _avert_us(us, "en_cours" if en_cours else "termine" if termine else "paie",
                       liste_dite=not cl["frais"], pf=pf)
    if avertissement:
        c += ["", avertissement]

    pied = (f'YOULAB • Marché {pf["marche"]} · comptes VA, sans pseudo' if mix is None
            else f'YOULAB • Marchés {pf["marche"]} + {tw["marche"]} · comptes VA, sans pseudo')
    if en_cours:
        pied += " · mis à jour " + _horodatage()
    elif termine:
        pied += " · semaine terminée · relevé du " + _horodatage()
    else:
        pied += " · résultat final"
    texte = "\n".join(c)
    if len(texte) > 4096 and th:
        # L'habillage rallonge le message. Une tête de personnage s'écrit
        # « <:kart_mario:1234…> », 33 caractères contre un pour 👑, et il y en
        # a six (podium et bloc des primes) : près de deux cents de plus. Le
        # kart des places 4 et plus en ajoute trois par ligne : une centaine
        # de VA FR, encore deux cents. Relu en revue : à 100 VA FR, le message
        # sans thème tenait, celui du thème était coupé au milieu de la
        # réclamation des primes. Le thème ne doit jamais faire couper ce qui
        # tiendrait sans lui : il cède son habillage, le plus lourd d'abord,
        # tant que ça ne tient pas. Ainsi réduit, il n'est jamais plus long
        # que sans thème (ses lignes d'état et de primes sont plus courtes, ou
        # égales pour « terminée »). Les remplacements donnent exactement le
        # rendu sans cet habillage : aucun nom de VA ne contient « <:kart_ »,
        # et seules les lignes de rang commencent par « 4. 🏎️ ».
        retire = []
        if med != th["repli"]:
            for tete, repli in zip(med, th["repli"]):
                texte = texte.replace(tete, repli)
            retire.append(f"les têtes ({' '.join(th['repli'])} à la place)")
        if len(texte) > 4096:
            texte = re.sub(rf"^(\d+)\. {re.escape(th['suite'])} ", r"\1. ", texte, flags=re.M)
            retire.append(f"le {th['suite']} des places 4 et plus")
        print(f"[podium] {gid} : podium trop long avec l'habillage du thème — retiré : "
              f"{', '.join(retire)}", flush=True)
    if len(texte) > 4096:
        # Discord refuse au-delà : coupé, mais jamais sans le dire
        print(f"[podium] {gid} : podium de {len(texte)} caractères, coupé à 4096 (limite de "
              f"Discord) : la fin du message manque", flush=True)
    if th:
        return {"title": th["titres"][etat],
                "color": th["couleurs"][etat],
                "thumbnail": _vignette(th, "podium"),
                "description": texte[:4096],
                "footer": {"text": pied}}
    return {"title": ("🔴 PODIUM SUBS — SEMAINE EN COURS" if en_cours
                      else "🏁 PODIUM SUBS — SEMAINE TERMINÉE" if termine
                      else "🏆 PODIUM SUBS DE LA SEMAINE"),
            "color": 0xE67E22 if en_cours else 0x95A5A6 if termine else 0xF1C40F,
            "description": texte[:4096],
            "footer": {"text": pied}}


def pages_subs(cl: Dict[str, Any], debut: dt.date, fin: dt.date,
               totaux: Dict[str, int], gid: Optional[str] = None,
               final: bool = False, avertissement: str = "",
               us: Optional[Dict[str, Any]] = None,
               totaux_us: Optional[Dict[str, int]] = None,
               tetes: bool = True) -> List[Dict[str, Any]]:
    """Le classement de la quinzaine, découpé en autant de messages qu'il faut.

    Discord coupe une description à 4096 caractères. Plutôt que de tronquer —
    ce qui ferait croire à quelqu'un du bas de tableau qu'il n'existe pas —, on
    répartit sur plusieurs messages, numérotés « page 2/3 ». Le total de la
    période va sur la dernière page : c'est là qu'on le cherche.

    `final` : la quinzaine est finie, ces pages ne bougeront plus. Le titre
    porte ses dates (plusieurs quinzaines figées se suivent dans le salon) et
    plus rien ne promet un « prochain passage ».

    `us`, `totaux_us` (Va IG, clé « avec_us ») : les VA de Twitter et leurs
    totaux « depuis toujours », mêlés aux VA FR.
    `tetes=False` : comme embed_podium (page figée aux têtes invérifiées).
    """
    p = _profil(gid)
    lignes = cl["lignes"]
    mix = _melange(cl, us, p)
    tw = SERVEURS[TWITTER_ID]
    # le thème : titre, couleur, vignette, têtes au top 3 et 🏎️ ensuite. La
    # quinzaine ne paie rien : pas de 🪙 ici, comme pas de 💰 sans thème
    th = _theme(gid)
    med = _marqueurs(gid, tetes)
    suite = f'{th["suite"]} ' if th else ""
    if mix is None:
        tete = (f'🗓️ Période **{debut.strftime("%d/%m")} → {fin.strftime("%d/%m/%Y")}** '
                f'· depuis le {debut.strftime("%d/%m")} à 00h00\n'
                f'Clics **{_mesure_dite(p)}** · **{len(lignes)}** comptes classés\n')
    else:
        # le même en-tête que le podium mêlé : toute l'agence, sans marché
        tete = (f'🗓️ Période **{debut.strftime("%d/%m")} → {fin.strftime("%d/%m/%Y")}** '
                f'· depuis le {debut.strftime("%d/%m")} à 00h00\n'
                f"Subs de **toute l'agence** · **{len(mix)}** comptes classés\n")
    if final:
        tete += "🔒 _Période terminée : classement arrêté, il ne bougera plus._\n"

    rangs = []
    for i, x in enumerate(lignes if mix is None else mix):
        if mix is None:
            at = totaux.get(x["va"])
        else:
            # « VA 3 » de Twitter et « Amelia VA 3 » ne sont pas la même
            # personne : chaque total vient du fichier de son serveur
            at = (totaux if x["marche"] == p["marche"] else (totaux_us or {})).get(x["va"])
        suffixe = f' · 🌐 {at} all-time' if at is not None else ""
        nom = x.get("affiche") or x["va"]
        rangs.append(f'{med[i]} **{nom}** — **{x["clics"]}** subs{suffixe}'
                     if i < 3 else
                     f'{i + 1}. {suite}{nom} — {x["clics"]} subs{suffixe}')
    if not rangs:
        rangs = ["_Aucun relevé pour cette période._"]

    # mêlé : un seul total, celui de toutes les lignes affichées — l'en-tête
    # annonce toute l'agence, un total par marché redirait ce qu'on ne dit plus
    total = sum(int(x["clics"]) for x in (lignes if mix is None else mix))
    queue = [f'\n👥 **Total période**\n**{total}** subs']
    if cl["illisibles"]:
        if final:
            queue.append("\n⚠️ Relevé indisponible : " + ", ".join(cl["illisibles"])
                         + " — à confirmer.")
        else:
            # la quota GetMySocial n'explique rien quand les clics viennent
            # de MyPuls (Twitter) : les noms, alors
            pourquoi = _quota_dit() if _source(gid) == "gms" else ""
            if pourquoi:
                # la raison, pas le mur de noms : vingt-trois lignes de VA
                # prenaient la moitié du message sans rien expliquer
                queue.append(f'\n⚠️ **{len(cl["illisibles"])}** compte(s) sans relevé '
                             f'— {pourquoi}.')
            else:
                queue.append("\n⚠️ Sans relevé cette fois : " + ", ".join(cl["illisibles"])
                             + " — ils remonteront au prochain passage.")
    if not cl["frais"]:
        queue.append("\n⚠️ _Liste des liens non rafraîchie : des comptes peuvent manquer._")
    queue += ["\n" + x for x in _notes_tracking(cl)]
    if mix is not None:
        queue += ["\n" + x for x in _avert_us(us, "final" if final else "en_cours",
                                               liste_dite=not cl["frais"], pf=p) if x]
    if avertissement:
        queue.append("\n" + avertissement)
    bas = "\n".join(queue)

    # on remplit page par page, en gardant de la place pour l'en-tête ; la
    # dernière doit aussi loger le total, d'où la marge plus large. Les
    # lignes sont comptées telles qu'écrites : une tête du thème (« <:kart_
    # mario:…> », 33 caractères) pèse ce qu'elle pèse, et pousse la ligne
    # suivante sur une autre page plutôt que de la faire couper
    MARGE = 3600
    pages: List[List[str]] = [[]]
    taille = len(tete)
    for r in rangs:
        if taille + len(r) + 1 > MARGE and pages[-1]:
            pages.append([])
            taille = len(tete)
        pages[-1].append(r)
        taille += len(r) + 1
    # le total ne tient plus sur la dernière page : il prend la sienne
    if len("\n".join([tete] + pages[-1])) + len(bas) > 4000:
        pages.append([])

    out = []
    for n, page in enumerate(pages, start=1):
        corps = tete + "\n" + "\n".join(page)
        if n == len(pages):
            corps += "\n" + bas
        marches = (f'Marché {p["marche"]}' if mix is None
                   else f'Marchés {p["marche"]} + {tw["marche"]}')
        pied = (f'YOULAB • {marches} · comptes VA, sans pseudo · '
                + ("résultat final" if final else "mis à jour " + _horodatage()))
        if len(pages) > 1:
            pied = f"page {n}/{len(pages)} · " + pied
        if len(corps) > 4096:
            # un bas de page démesuré (des dizaines d'illisibles) : Discord
            # refuse au-delà, la coupe est dite au journal
            print(f"[podium] {gid} : page {n}/{len(pages)} de la quinzaine, {len(corps)} "
                  "caractères, coupée à 4096 (limite de Discord)", flush=True)
        if th:
            nom_q = th["subs"]
            out.append({"title": (f'{nom_q} — quinzaine du {debut.strftime("%d/%m")} '
                                  f'au {fin.strftime("%d/%m")} (terminée)' if final
                                  else f"{nom_q} — la quinzaine")
                                 + (f" ({n}/{len(pages)})" if len(pages) > 1 else ""),
                        "color": th["couleurs_subs"]["final" if final else "vivant"],
                        "thumbnail": _vignette(th, "subs"),
                        "description": corps[:4096],
                        "footer": {"text": pied}})
            continue
        titre = (f'📊 Classement subs — quinzaine du {debut.strftime("%d/%m")} '
                 f'au {fin.strftime("%d/%m")} (terminée)' if final
                 else "📊 Classement subs — la quinzaine")
        out.append({"title": titre + (f" ({n}/{len(pages)})" if len(pages) > 1 else ""),
                    "color": 0x64748B if final else 0x3B82F6,
                    "description": corps[:4096],
                    "footer": {"text": pied}})
    return out


def _alltime_lu(gid: Optional[str] = None, mesure: Optional[str] = None) -> Dict[str, int]:
    """Le dernier total « depuis toujours » connu, SANS appeler GetMySocial.

    Figer une quinzaine ne doit rien coûter de plus au quota, et doit marcher
    pendant une pause de GetMySocial : le total relevé le jour de la fin (ou
    la veille) est le bon chiffre pour une page qui ne bougera plus.
    """
    try:
        return {k: int(v) for k, v in
                (_lire(_fichier_alltime(gid, mesure), {}).get("totaux") or {}).items()}
    except Exception:
        return {}


# Une quinzaine finie dont le relevé complet rate (GetMySocial en pause, muet,
# ou un VA illisible) est réessayée, mais pas à chaque tour : chaque essai
# coûte un appel par VA, et le quota est partagé avec le tableau de bord.
# Au bout de 48 h, on fige avec ce qu'on a — rien ne reste « vivant » à vie.
ESSAI_FIGER_MIN = 120
ABANDON_FIGER_H = 48


@_exclusif
def rafraichir_subs(gid: str, jour: Optional[dt.date] = None, forcer: bool = False) -> str:
    """Met à jour (ou crée) le classement vivant de la quinzaine, sur N pages.

    Une quinzaine nouvelle veut des messages neufs. Mais AVANT de les poster,
    les pages de la quinzaine finie sont figées sur place, sur les chiffres de
    la période entière (propriétaire, 03/10/2026 : « que ça reste là, la
    période après la période, le truc bouge plus »). Avant, elles restaient
    telles quelles : « mis à jour », « ils remonteront au prochain passage »,
    et des chiffres vieux d'une heure ou deux.

    `forcer` (bouton « 🔄 Mettre à jour ») : relève la quinzaine vivante même
    si son dernier relevé a moins de deux heures. Le gel des quinzaines finies
    n'en est pas changé (ses essais gardent leur espacement).
    """
    gid = str(gid)
    debut, fin_saison = saison_en_cours(jour)
    aujourd = jour or _aujourdhui()
    d = _etat()
    vivants = d.setdefault("subs", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid, _config().get("salon_subs") or SALON_SUBS)
    if not salon:
        print(f"[podium] salon {SALON_SUBS} introuvable sur {gid}", flush=True)
        return ""
    # les têtes du thème avant tout rendu (pages vivantes ET figées) : ici, où
    # l'on parle déjà à Discord, jamais dans pages_subs
    _assurer_emojis(gid)

    # `message` (au singulier) est l'ancien format : un seul identifiant
    ids = list(garde.get("messages") or ([garde["message"]] if garde.get("message") else []))
    ancienne = str(garde.get("saison") or "")
    if ancienne != debut.isoformat():
        if ids and ancienne and ancienne < debut.isoformat():
            # noté AVANT d'essayer : si le relevé rate ou si le bot redémarre
            # au milieu, la quinzaine reste à figer, elle n'est pas oubliée
            d.setdefault("subs_a_figer", {}).setdefault(gid, {})[ancienne] = {
                "fin": saison_en_cours(dt.date.fromisoformat(ancienne))[1].isoformat(),
                "messages": [str(x) for x in ids], "depuis": time.time(), "essais": 0,
                "dernier": garde.get("dernier") or {}}
            vivants.pop(gid, None)
            _ecrire(d)
            print(f"[podium] quinzaine {ancienne} finie sur {gid} : {len(ids)} page(s) à figer",
                  flush=True)
        ids = []                      # quinzaine nouvelle : messages neufs
    # les quinzaines finies d'abord : leurs pages restent AU-DESSUS des neuves
    _figer_quinzaines(gid, d, salon)
    # figer a pu reprendre des pages vivantes de la quinzaine neuve (voir
    # _page_neuve) : on repart de ce qu'il en reste
    garde = vivants.get(gid) or {}
    if str(garde.get("saison") or "") == debut.isoformat():
        ids = [str(x) for x in (garde.get("messages")
                                or ([garde["message"]] if garde.get("message") else []))]
    if jour is None and not forcer and not _subs_du(gid, garde):
        # on n'est passé que pour réécrire des pages figées déjà calculées
        # (Discord les avait refusées) : la quinzaine vivante garde son rythme,
        # et ce passage ne coûte aucun relevé. Le bouton 🔄 passe outre : sans
        # ça, un clic moins de deux heures après le dernier relevé ne
        # changeait rien au classement
        return str((ids or [""])[0])

    if _pause_pour(gid):
        # on n'est passé que pour figer sans GetMySocial (48 h écoulées)
        print("[podium] GetMySocial en pause : classement de la quinzaine remis au prochain tour",
              flush=True)
        return ""
    # on s'arrête à aujourd'hui : demander des jours qui n'existent pas encore
    # ne rend rien de plus, et laisserait croire que la quinzaine est finie
    cl = classement(debut, min(aujourd, fin_saison), gid=gid)
    if not cl["lignes"] and not cl["illisibles"]:
        print("[podium] aucun relevé, classement subs laissé tel quel", flush=True)
        return str((ids or [""])[0])
    try:
        totaux = alltime(gid)
    except Exception as e:
        print(f"[podium] all-time indisponible : {type(e).__name__}: {e}", flush=True)
        totaux = {}
    us = _us_pour(gid, debut, min(aujourd, fin_saison), cl)
    # le total « depuis toujours » des VA US : celui que Twitter relève chaque
    # jour pour lui-même, lu sans appeler GetMySocial
    pages = pages_subs(cl, debut, fin_saison, totaux, gid=gid, us=us,
                       # les totaux GetMySocial des VA US, comme leurs clics ici
                       totaux_us=alltime(TWITTER_ID, mesure="gms") if us else None)

    neufs: List[str] = []
    for i, page in enumerate(pages):
        corps = {"embeds": [page], **_boutons(gid, True)}
        if i < len(ids):
            code, rep = _api("PATCH", f"/channels/{salon}/messages/{ids[i]}", json=corps)
            if code == 200:
                neufs.append(ids[i])
                continue
            if _passager(code, rep):
                # la page est toujours là : en poster une autre laissait celle-ci
                # « mis à jour » pour toujours, jamais figée, à côté de la neuve
                print(f"[podium] page {i + 1} : Discord indisponible (HTTP {code}), "
                      "gardée pour le prochain passage", flush=True)
                neufs.append(ids[i])
                continue
            # supprimé à la main : on en refait un plutôt que de rester muet
            print(f"[podium] page {i + 1} inéditable (HTTP {code}), reposte", flush=True)
        code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
        if code != 200 or not rep.get("id"):
            print(f"[podium] page {i + 1} refusée (HTTP {code}) {str(rep)[:140]}", flush=True)
            continue
        neufs.append(str(rep["id"]))

    # la liste a raccourci : les pages en trop diraient n'importe quoi
    for surplus in ids[len(pages):]:
        c, _r = _api("DELETE", f"/channels/{salon}/messages/{surplus}")
        print(f"[podium] page en trop {surplus} retirée (HTTP {c})", flush=True)

    if not neufs:
        return ""
    vivants[gid] = {"saison": debut.isoformat(), "messages": neufs, "vu": time.time(),
                    "dernier": _instantane(cl, min(aujourd, fin_saison)),
                    "format": FORMAT_AFFICHAGE}
    _ecrire(d)
    print(f'[podium] classement subs {debut} → {fin_saison} : {len(cl["lignes"])} comptes, '
          f'{len(neufs)} page(s)', flush=True)
    return neufs[0]


def _figer_quinzaines(gid: str, d: Dict[str, Any], salon: str) -> None:
    attente = (d.get("subs_a_figer") or {}).get(gid) or {}
    for saison in sorted(attente):
        fige = False
        try:
            fige = _figer_quinzaine(gid, d, salon, saison, attente[saison])
        except Exception as e:
            # une quinzaine qui ne se fige pas ne doit pas bloquer la neuve
            print(f"[podium] quinzaine {saison} à figer sur {gid} : {type(e).__name__}: {e}",
                  flush=True)
        if not fige:
            try:
                _quinzaine_sans_bouton(gid, d, salon, saison)
            except Exception as e:
                print(f"[podium] quinzaine {saison} sur {gid}, bouton 🔄 à retirer : "
                      f"{type(e).__name__}: {e}", flush=True)


def _quinzaine_sans_bouton(gid: str, d: Dict[str, Any], salon: str, saison: str) -> None:
    """Retire le bouton 🔄 des pages d'une quinzaine finie qui attend son gel.

    Figée tout de suite (le cas courant), ses pages perdent le bouton avec
    leur embed final : rien à faire ici. Mais un VA illisible à minuit, une
    pause de GetMySocial ou un refus de Discord la laissent en attente jusqu'à
    48 h, et ses pages gardaient le bouton tout ce temps : un clic répondait
    « mise à jour lancée » sans jamais les toucher (le clic relève la
    quinzaine VIVANTE). La semaine, elle, le perd dès « terminée » le lundi.
    Seuls les composants sont envoyés : Discord garde l'embed qu'on ne lui
    renvoie pas, les derniers chiffres restent affichés jusqu'au gel.
    Une fois par quinzaine (« sans_bouton ») ; Discord en panne passagère :
    nouvel essai au passage suivant. Twitter (sans la clé) : rien, aucun appel.
    """
    retrait = _boutons(gid, False)
    rec = (((d.get("subs_a_figer") or {}).get(gid) or {}).get(saison))
    if not retrait or not isinstance(rec, dict) or rec.get("sans_bouton"):
        return
    ids = [str(x) for x in (rec.get("messages") or [])]
    # les pages déjà réécrites figées (« faites ») n'ont plus de bouton
    reste, perdues = 0, []
    for mid in ids[int(rec.get("faites") or 0):]:
        if not mid:
            continue
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json=retrait)
        if code != 200 and _passager(code, rep):
            reste += 1
        elif code != 200:
            # supprimée à la main (404) : plus de bouton à retirer, le gel la
            # refera ; dit au journal, pas oublié
            perdues.append(f"{mid} (HTTP {code})")
    if reste:
        print(f"[podium] quinzaine {saison} sur {gid} : bouton 🔄 de {reste} page(s) pas "
              "retiré (Discord indisponible), nouvel essai au prochain passage", flush=True)
        return
    rec["sans_bouton"] = True
    _ecrire(d)
    print(f"[podium] quinzaine {saison} sur {gid} : finie, pas encore figée — bouton 🔄 retiré "
          f"de ses pages" + (f", page(s) introuvable(s) : {', '.join(perdues)}" if perdues else ""),
          flush=True)


def _page_neuve(gid: str, d: Dict[str, Any], salon: str, saison: str,
                corps: Dict[str, Any]) -> Tuple[str, int, Any]:
    """Un message de plus pour une quinzaine figée, à SA place dans le salon.

    Figée en retard (relevé raté à minuit, page supprimée à la main), elle a
    déjà sous elle les pages de la quinzaine neuve : un POST passerait en
    dessous, et les deux périodes se mêleraient dans le salon. La première
    page vivante de la quinzaine neuve, qui la suit immédiatement, est donc
    reprise et devient la page figée ; la quinzaine neuve repart en messages
    neufs, en dessous, au même passage (« vu » remis à zéro).
    Rend (id, code, réponse) ; id vide si rien n'a pu être écrit.
    """
    vif = (d.get("subs") or {}).get(gid) or {}
    attente = (d.get("subs_a_figer") or {}).get(gid) or {}
    pages = vif.get("messages")
    # une quinzaine plus récente encore en attente se placera elle-même :
    # on ne lui vole pas la place
    if (str(vif.get("saison") or "") > saison and isinstance(pages, list)
            and not any(s > saison for s in attente)):
        while pages:
            cand = str(pages[0])
            code, rep = _api("PATCH", f"/channels/{salon}/messages/{cand}", json=corps)
            if code == 200:
                pages.pop(0)
                vif["vu"] = 0
                print(f"[podium] page vivante {cand} de la quinzaine {vif.get('saison')} reprise "
                      f"pour la quinzaine figée {saison} (elle repart en dessous)", flush=True)
                return cand, code, rep
            if _passager(code, rep):
                return "", code, rep
            pages.pop(0)               # supprimée à la main : la suivante
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code == 200 and isinstance(rep, dict) and rep.get("id"):
        return str(rep["id"]), code, rep
    return "", code, rep


def _figer_quinzaine(gid: str, d: Dict[str, Any], salon: str, saison: str,
                     rec: Dict[str, Any]) -> bool:
    """Fige les pages d'une quinzaine finie, sur les chiffres de la période entière.

    Rend True une fois figée (elle quitte alors `subs_a_figer` et n'est plus
    jamais retouchée). Un relevé incomplet laisse la quinzaine en attente :
    nouvel essai dans ESSAI_FIGER_MIN minutes, et passé ABANDON_FIGER_H
    heures, on fige avec ce qu'on a, en le disant.

    Les pages, une fois calculées, sont gardées dans l'état, et chaque page
    écrite y est notée aussitôt. Si Discord refuse une page en passant, le
    tour suivant reprend là où on en était : sans relever GetMySocial une
    seconde fois (un appel par VA), sans reposter une page déjà refaite, et
    sans jamais noter « figée » une quinzaine à qui il manque une page.
    """
    t = time.time()
    abandon = t - float(rec.get("depuis") or t) >= ABANDON_FIGER_H * 3600
    # le premier passage après 48 h n'attend pas l'espacement des essais : il
    # fige avec ce qu'on a, quoi que rende GetMySocial
    premier_abandon = abandon and not rec.get("abandon")
    if abandon:
        rec["abandon"] = True
    debut, fin = dt.date.fromisoformat(saison), dt.date.fromisoformat(str(rec["fin"]))
    if (not rec.get("pages") and not abandon and _source(gid) == "tracking"
            and _maintenant() < dt.datetime.combine(fin + dt.timedelta(days=1),
                                                    dt.time(RATTRAPAGE_MYPULS_H))):
        # figée à 00h10, elle aurait gardé pour toujours les chiffres du
        # dernier palier de MyPuls, sans les dernières heures de la période
        return False
    if not rec.get("pages"):
        if (not premier_abandon and rec.get("essai")
                and t - float(rec["essai"]) < ESSAI_FIGER_MIN * 60):
            return False
        cl: Optional[Dict[str, Any]] = None
        raison = ""
        if _pause_pour(gid):
            raison = "GetMySocial en pause"
        else:
            cl = classement(debut, fin, gid=gid)
            rec["essais"] = int(rec.get("essais") or 0) + 1
            if not cl["lignes"]:
                raison = "aucun relevé"
            elif cl["illisibles"]:
                raison = "relevé illisible : " + ", ".join(cl["illisibles"])
        us: Optional[Dict[str, Any]] = None
        us_lu = False
        if not raison:
            # Va IG (clé « avec_us ») : les VA US affichés doivent être entiers
            # eux aussi. Figée à 00h10 sur un relevé de Twitter où un VA n'avait
            # pas répondu, la page le perdait pour toujours, alors que Twitter,
            # lui, attendait et figeait complet deux heures plus tard.
            us, us_lu = _us_pour(gid, debut, fin, cl), True
            if _us_manquants(us):
                raison = "relevé US illisible : " + ", ".join(_us_manquants(us))
        rec["essai"] = t
        avert = ""
        if raison:
            if not abandon:
                print(f"[podium] quinzaine {debut} → {fin} pas encore figée sur {gid} ({raison}) : "
                      f"nouvel essai dans {ESSAI_FIGER_MIN} min, figée quoi qu'il arrive "
                      f"{ABANDON_FIGER_H} h après la fin", flush=True)
                _ecrire(d)
                return False
            if cl is None or not cl["lignes"]:
                snap = rec.get("dernier") or {}
                if snap.get("lignes"):
                    cl = snap
                    avert = "" if _couvre(snap, fin) else _avert_dernier_releve(snap, "la période", gid)
                else:
                    cl = {"lignes": [], "illisibles": list((cl or {}).get("illisibles") or []),
                          "frais": bool((cl or {}).get("frais", True))}
                    avert = f"⚠️ _{_service(gid)} n'a rendu aucun chiffre pour cette période._"
            print(f"[podium] quinzaine {debut} → {fin} sur {gid} : {raison} depuis "
                  f"{ABANDON_FIGER_H} h, figée avec ce qu'on a", flush=True)
        # gardées AVANT d'écrire : un refus de Discord ou un redémarrage au
        # milieu reprend ces pages-là, il ne relève pas GetMySocial à nouveau
        # (et ne risque pas de remplacer des chiffres complets par un relevé
        # plus pauvre, deux heures plus tard)
        if not us_lu:
            us = _us_pour(gid, debut, fin, cl)
        # figées pour toujours : les têtes du thème relues juste avant
        tetes = _tetes_sures(gid)
        rec["pages"] = pages_subs(cl, debut, fin, _alltime_lu(gid), gid=gid, final=True,
                                  avertissement=avert, us=us,
                                  totaux_us=_alltime_lu(TWITTER_ID, mesure="gms") if us else None,
                                  tetes=tetes)
        rec["complet_calc"] = not raison
        rec["comptes"] = len(cl["lignes"])
        rec["faites"] = 0
        _ecrire(d)

    pages = list(rec["pages"])
    # une entrée par page, à sa place : la page i du salon est ids[i]
    ids = [str(x) for x in (rec.get("messages") or [])]
    manquantes = [int(x) for x in (rec.get("manquantes") or [])]

    def en_attente(faites: int) -> bool:
        rec["messages"] = ids
        rec["faites"] = faites
        _ecrire(d)
        return False

    for i in range(int(rec.get("faites") or 0), len(pages)):
        # figée : le bouton 🔄 de la page vivante s'en va avec elle
        corps = {"embeds": [pages[i]], **_boutons(gid, False)}
        mid = ""
        if i < len(ids) and ids[i]:
            code, rep = _api("PATCH", f"/channels/{salon}/messages/{ids[i]}", json=corps)
            if code == 200:
                mid = ids[i]
            elif _passager(code, rep):
                print(f"[podium] quinzaine {debut} : page {i + 1} — Discord indisponible "
                      f"(HTTP {code}), reprise au prochain tour", flush=True)
                return en_attente(i)
            else:
                # supprimée à la main : refaite, sinon des VA disparaîtraient du
                # classement final
                print(f"[podium] page figée {i + 1} inéditable (HTTP {code}), reposte", flush=True)
        if not mid:
            mid, code, rep = _page_neuve(gid, d, salon, saison, corps)
        if not mid:
            if abandon and not _passager(code, rep):
                # 48 h passées et Discord refuse pour de bon : figée sans
                # cette page, et l'historique le dit
                print(f"[podium] quinzaine {debut} : page figée {i + 1} refusée pour de bon "
                      f"(HTTP {code}) {str(rep)[:140]} — figée SANS elle", flush=True)
                manquantes.append(i + 1)
                rec["manquantes"] = manquantes
                continue
            # pas noté figé avec une page en moins : les VA de cette page et le
            # total (sur la dernière) disparaîtraient du classement final
            print(f"[podium] quinzaine {debut} : page figée {i + 1} refusée (HTTP {code}) "
                  f"{str(rep)[:140]} — reprise au prochain tour", flush=True)
            return en_attente(i)
        if i < len(ids):
            ids[i] = mid
        else:
            ids.append(mid)
        # noté page par page : un échec plus loin ne la fera pas reposter
        rec["messages"] = ids
        rec["faites"] = i + 1
        _ecrire(d)

    # moins de pages qu'en direct : les pages en trop diraient n'importe quoi
    reste = []
    for surplus in ids[len(pages):]:
        c, r = _api("DELETE", f"/channels/{salon}/messages/{surplus}")
        print(f"[podium] page en trop {surplus} retirée (HTTP {c})", flush=True)
        if c not in (200, 204) and _passager(c, r):
            reste.append(surplus)     # encore « mis à jour » : à retirer au prochain tour
    if reste:
        ids[len(pages):] = reste
        return en_attente(len(pages))

    ecrites = [ids[k] for k in range(len(pages)) if k + 1 not in manquantes and k < len(ids)]
    complet = bool(rec.get("complet_calc")) and not manquantes
    fige = {"fin": fin.isoformat(), "messages": ecrites, "complet": complet,
            "essais": int(rec.get("essais") or 0),
            "le": _maintenant().isoformat(timespec="minutes")}
    if manquantes:
        fige["manquantes"] = manquantes
    d.setdefault("subs_figes", {}).setdefault(gid, {})[saison] = fige
    attente = (d.get("subs_a_figer") or {}).get(gid) or {}
    attente.pop(saison, None)
    if not attente:
        (d.get("subs_a_figer") or {}).pop(gid, None)
    _ecrire(d)
    print(f'[podium] quinzaine {debut} → {fin} figée sur {gid} : {rec.get("comptes", 0)} comptes, '
          f'{len(ecrites)} page(s){"" if complet else " (incomplète)"}'
          + (f", page(s) {manquantes} MANQUANTE(S)" if manquantes else ""), flush=True)
    return True


def _subs_du(gid: str, garde: Dict[str, Any], t: Optional[float] = None) -> bool:
    """Le classement vivant de la quinzaine a-t-il passé l'âge (ou n'existe pas) ?"""
    if garde.get("saison") != saison_en_cours()[0].isoformat():
        return True
    if not (garde.get("messages") or garde.get("message")):
        return True
    if garde.get("format") != FORMAT_AFFICHAGE:
        # presentation changee : refaire tout de suite. ICI, et pas seulement
        # dans a_rafraichir_subs : rafraichir_subs repose la meme question et
        # sortait sans rien faire (constate le 03/10 apres f6b44cf)
        return True
    minutes = int(_profil(gid).get("minutes") or _config().get("minutes_subs")
                  or _config().get("minutes") or MINUTES_LIVE)
    return (t or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


#: La presentation des messages vivants. A CHANGER a chaque modification de ce
#: qu'ils affichent (libelles, primes, bouton…) : un message ecrit dans un
#: autre format est refait au passage suivant, sans attendre sa cadence (deux
#: heures sur Va IG). Le 03/10/2026, le nouveau podium (primes au top 3,
#: « Jessye VA n ») n'aurait paru que deux heures apres sa mise en ligne.
#: Le 03/10/2026 au soir : le thème Mario de Va IG (titres, têtes, bouton
#: « Relancer la course ») — sans ce changement, il n'aurait paru qu'au relevé
#: suivant, deux heures après la mise en ligne. Puis le kart des places 4 et
#: plus : marqueur change, donc format change — le message avait justement
#: garde son rond vert apres la mise en ligne, faute d'avoir touche a cette
#: ligne.
#: Le 06/10/2026 : Twitter compte les clics des trackings (« clics tracking
#: OF » au lieu de « clics US »).
FORMAT_AFFICHAGE = "2026-10-06-clics-tracking"


def a_rafraichir_subs(gid: str, maintenant: Optional[float] = None) -> bool:
    gid = str(gid)
    t = maintenant or time.time()
    d = _etat()
    # une quinzaine finie qui attend depuis 48 h se fige MAINTENANT, sans
    # attendre le prochain passage (deux heures sur Va IG) ni la fin d'une
    # pause de GetMySocial : elle se fige alors sur son dernier relevé.
    # Une fois : ce passage calcule ses pages, et si Discord refuse alors
    # d'écrire, c'est la règle suivante (pages gardées) qui le fait repasser
    attente = (d.get("subs_a_figer") or {}).get(gid) or {}
    if any(t - float(r.get("depuis") or t) >= ABANDON_FIGER_H * 3600 and not r.get("abandon")
           for r in attente.values()):
        return True
    # des pages figées déjà calculées que Discord a refusées : les réécrire
    # ne coûte aucun relevé, on n'attend pas deux heures avec une page qui
    # se dit encore « mis à jour »
    if any(r.get("pages") for r in attente.values()):
        return True
    if _pause_pour(gid):
        return False
    return _subs_du(gid, (d.get("subs") or {}).get(gid) or {}, t)


def embed_bonus(cl: Dict[str, Any], jour: dt.date,
                gid: Optional[str] = None) -> Dict[str, Any]:
    """Le bonus du jour : les trois premiers de la JOURNÉE, et ce qu'ils gagnent."""
    lignes = cl["lignes"]
    c = [f'📅 Journée du **{jour.strftime("%d/%m/%Y")}** · clics **{_mesure_dite(_profil(gid))}** '
         f'· **{len(lignes)}** comptes suivis', ""]
    for i in range(3):
        x = lignes[i] if i < len(lignes) else None
        if x is None:
            c.append(f'{MEDAILLES[i]} **—** · **{PRIMES_JOUR[i]:.2f}$**')
        else:
            c.append(f'{MEDAILLES[i]} **{x["va"]}** — **{x["clics"]}** subs '
                     f'→ **{PRIMES_JOUR[i]:.2f}$**')
    # tout le monde a zéro : le dire, sinon un podium de zéros ressemble à un bug
    if lignes and not any(x["clics"] for x in lignes[:3]):
        c += ["", "_Personne n'a encore de sub aujourd'hui — le classement bouge "
                  "dès le premier._"]
    c += ["", "————————————",
          f'🎁 **Pour recevoir ton bonus :** envoie un message à **@{_profil(gid)["bot"]}** dans '
          "**ton espace perso** avec **ton rang du jour (top 1, 2 ou 3)** et "
          "**ton adresse USDC (réseau Solana)**.",
          "Un seul prix par personne · payé à la main après vérification"]
    if cl["illisibles"]:
        c += ["", "⚠️ Sans relevé aujourd'hui : " + ", ".join(cl["illisibles"])
                  + " — à confirmer avant de payer."]
    if not cl["frais"]:
        c += ["", "⚠️ _Liste des liens non rafraîchie : des comptes peuvent manquer._"]
    if _notes_tracking(cl):
        c += [""] + _notes_tracking(cl)
    return {"title": f'💸 Bonus subs du jour — {jour.strftime("%d/%m/%Y")}',
            "color": 0x22C55E,
            "description": "\n".join(c)[:4096],
            "footer": {"text": "YOULAB • Marché US · comptes VA, sans pseudo · mis à jour "
                               + _maintenant().strftime("%d/%m à %Hh%M")}}


@_exclusif                      # il écrit lui aussi dans podium.json
def rafraichir_bonus(gid: str, jour: Optional[dt.date] = None) -> str:
    """Met à jour (ou crée) le bonus du jour. Un message NEUF par journée."""
    gid = str(gid)
    j = jour or _aujourdhui()
    d = _etat()
    vivants = d.setdefault("bonus", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid, _config().get("salon_bonus") or SALON_BONUS)
    if not salon:
        print(f"[podium] salon {SALON_BONUS} introuvable sur {gid}", flush=True)
        return ""
    if jour is None:
        _bonus_veille(gid, d, salon, j)
    cl = classement(j, j, gid=gid)
    if not cl["lignes"] and not cl["illisibles"]:
        print("[podium] aucun relevé, bonus du jour laissé tel quel", flush=True)
        return str(garde.get("message") or "")
    corps = {"embeds": [embed_bonus(cl, j, gid)]}

    mid = str(garde.get("message") or "")
    if mid and garde.get("jour") == j.isoformat():
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json=corps)
        if code == 200:
            garde["vu"] = time.time()
            vivants[gid] = garde
            _ecrire(d)
            return mid
        print(f"[podium] édition bonus refusée (HTTP {code}), nouveau message", flush=True)
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi bonus refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    if mid and str(garde.get("jour") or "") < j.isoformat() and _source(gid) == "tracking":
        # le bonus d'hier, à compléter demain matin (voir _bonus_veille)
        d.setdefault("bonus_veille", {})[gid] = {"jour": str(garde["jour"]), "message": mid}
    vivants[gid] = {"jour": j.isoformat(), "message": str(rep["id"]), "vu": time.time()}
    _ecrire(d)
    print(f'[podium] bonus du jour {j} : {len(cl["lignes"])} comptes', flush=True)
    return str(rep["id"])


def _bonus_veille(gid: str, d: Dict[str, Any], salon: str, j: dt.date) -> None:
    """Le bonus d'HIER, complété le matin. Payé au rang du jour, il gardait
    sinon les chiffres du dernier palier de MyPuls avant minuit, sans les
    dernières heures de la journée. Réédité (Discord ne notifie pas une
    édition) jusqu'à RATTRAPAGE_MYPULS_H, puis laissé tel quel."""
    v = (d.get("bonus_veille") or {}).get(gid) or {}
    if not v:
        return
    try:
        jv = dt.date.fromisoformat(str(v.get("jour")))
    except ValueError:
        jv = None
    if jv is None or (j - jv).days != 1 or _maintenant().hour >= RATTRAPAGE_MYPULS_H:
        d["bonus_veille"].pop(gid, None)
        _ecrire(d)
        return
    clv = classement(jv, jv, gid=gid)
    if not clv["lignes"]:
        return
    code, _rep = _api("PATCH", f'/channels/{salon}/messages/{v["message"]}',
                      json={"embeds": [embed_bonus(clv, jv, gid)]})
    if code == 200:
        print(f"[podium] bonus du {jv} complété : {len(clv['lignes'])} comptes", flush=True)
    elif not _passager(code, _rep):
        d["bonus_veille"].pop(gid, None)      # supprimé à la main : on n'insiste pas
        _ecrire(d)


def a_rafraichir_bonus(gid: str, maintenant: Optional[float] = None) -> bool:
    if _pause_pour(gid) or not _profil(gid).get("bonus", True):
        return False
    garde = (_etat().get("bonus") or {}).get(str(gid)) or {}
    if garde.get("jour") != _aujourdhui().isoformat():
        return True
    minutes = int(_config().get("minutes_bonus") or _config().get("minutes") or MINUTES_LIVE)
    return (maintenant or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


def _nom_nu(nom) -> str:
    """Le nom du salon sans la décoration posée devant à la main.

    La MÊME normalisation que cogs/outils et cogs/welcome (nom_sans_decor) :
    deux façons de lire un nom de salon, c'est un salon reconnu d'un côté et
    pas de l'autre. Importée ici plutôt que recopiée, et seulement à l'appel —
    un relevé doit pouvoir tourner sans discord.py.
    """
    try:
        from cogs.welcome import nom_sans_decor
        nu = nom_sans_decor(nom)
    except Exception:                                        # noqa: BLE001
        nu = str(nom or "").strip().lower()
    return nu.lstrip("-_ ")


def _salon(gid: str, voulu: str = "") -> str:
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return ""
    voulu = voulu or _config().get("salon") or SALON_PODIUM
    for x in rep:
        if x.get("name") == voulu:
            return str(x["id"])
    # LE PROPRIETAIRE REDECORE SES SALONS A LA MAIN. « ⬇️・all-download » avait
    # deja fait disparaitre les copies de telechargement sans un mot (journal du
    # 26/09) ; un « ─│🏁┤-podium » repeint en thème Mario aurait fait pareil au
    # podium. On retombe donc sur le nom NU, comme le reste du dépôt.
    cible = _nom_nu(voulu)
    trouves = [x for x in rep if _nom_nu(x.get("name")) == cible] if cible else []
    if len(trouves) == 1:
        print(f"[podium] {gid} : salon « {voulu} » retrouvé sous le nom "
              f"« {trouves[0].get('name')} » (même nom nu)", flush=True)
        return str(trouves[0]["id"])
    if len(trouves) > 1:
        # choisir au hasard, ce serait poster le podium dans le mauvais salon
        print(f"[podium] {gid} : {len(trouves)} salons se lisent « {cible} » ("
              + ", ".join(str(x.get("name")) for x in trouves)
              + ") — aucun choisi, il faut en renommer un", flush=True)
    return ""


# ─── la semaine finie : figée sur place ──────────────────────────────────
MENTION_PODIUM = "@everyone 🏆 Podium subs de la semaine !"


def _serveur_connu(d: Dict[str, Any], gid: str) -> bool:
    """Le serveur a déjà un podium derrière lui (message vivant, podium posté
    ou semaine figée). Un serveur tout neuf n'a pas de podium à attendre."""
    return bool((d.get("vivants") or {}).get(gid)
                or (d.get("figes") or {}).get(gid)
                or any(str(k).startswith(f"{gid}:") for k in (d.get("postes") or {})))


def _attente_podium(d: Dict[str, Any], gid: str, jour: Optional[dt.date] = None) -> bool:
    """Vrai le lundi tant que le podium de la semaine finie n'est pas parti.

    Pendant ce temps, la semaine neuve n'a pas de message : posté à 00h10,
    il passerait AU-DESSUS du podium de 09h dans le salon, et les semaines ne
    se liraient plus dans l'ordre. Le mardi, la semaine neuve part quoi qu'il
    arrive (le message de la semaine finie est alors figé sans podium).
    Une date passée à la main (rattrapage) n'attend rien : on ne sait pas
    l'heure qu'il « est » ce jour-là.
    """
    auj = _aujourdhui()
    j = jour or auj
    if j != auj or j.weekday() != 0:
        return False
    if (d.get("postes") or {}).get(f"{gid}:{semaine_passee(j)[0].isoformat()}"):
        return False
    return _serveur_connu(d, gid)


def _semaine_terminee(gid: str, d: Dict[str, Any], salon: str, garde: Dict[str, Any]) -> None:
    """Le lundi avant le podium, le message de la semaine finie le DIT.

    Une seule fois, sur les chiffres de la semaine entière (lundi → dimanche) :
    le dernier passage du dimanche datait d'une ou deux heures. Ensuite, plus
    aucun appel à GetMySocial jusqu'au podium — le drapeau `termine` y veille.
    """
    lundi = dt.date.fromisoformat(str(garde["semaine"]))
    dimanche = lundi + dt.timedelta(days=6)
    cl: Optional[Dict[str, Any]] = classement(lundi, dimanche, gid=gid)
    avert = ""
    if cl["lignes"]:
        garde["dernier"] = _instantane(cl, dimanche)
    else:
        # un classement vide remplacerait des chiffres corrects par rien
        snap = garde.get("dernier") or {}
        cl = snap if snap.get("lignes") else None
        avert = _avert_dernier_releve(snap, "la semaine", gid) if cl else ""
    if cl is None:
        # rien à montrer : le message garde ses chiffres, le podium de 09h le figera
        print(f"[podium] semaine {lundi} terminée sur {gid} : aucun relevé, message laissé "
              "tel quel jusqu'au podium", flush=True)
    else:
        code, _rep = _api("PATCH", f"/channels/{salon}/messages/{garde['message']}",
                          json={"embeds": [embed_podium(cl, lundi, dimanche, gid=gid,
                                                        termine=True, avertissement=avert,
                                                        us=_us_pour(gid, lundi, dimanche, cl))],
                                # la semaine est finie : plus de bouton 🔄
                                **_boutons(gid, False)})
        if code != 200:
            # une seule tentative : le podium de 09h repasse de toute façon
            # sur ce message (ou en poste un neuf s'il a disparu)
            print(f"[podium] semaine {lundi} : message {garde['message']} inéditable "
                  f"(HTTP {code}), le podium s'en chargera", flush=True)
        else:
            print(f"[podium] semaine {lundi} → {dimanche} terminée sur {gid}, "
                  f"podium à {_heure_podium()}h", flush=True)
    garde["termine"] = True
    garde["vu"] = time.time()
    d.setdefault("vivants", {})[gid] = garde
    _ecrire(d)


def _figer_semaine(gid: str, d: Dict[str, Any], salon: str, garde: Dict[str, Any]) -> bool:
    """Fige le message d'une semaine finie dont le podium n'est jamais parti.

    Le podium a raté tout le lundi (GetMySocial muet), ou le bot était éteint :
    sans ça, le message restait « SEMAINE EN COURS — Rien n'est joué » pour
    toujours, au-dessus de la semaine suivante. Ni @everyone ni primes ici :
    ils n'appartiennent qu'au podium du lundi.

    Rend False si Discord est en panne passagère ou l'accès au salon retiré
    (403 50001/50013) : le message vivant est gardé, et le tour suivant
    réessaie sans redemander les chiffres (l'embed attend dans l'état). Rend
    False aussi pendant une pause de GetMySocial sans relevé de la semaine
    entière : figer des chiffres partiels pour toujours serait pire qu'attendre.
    """
    lundi = dt.date.fromisoformat(str(garde["semaine"]))
    dimanche = lundi + dt.timedelta(days=6)
    mid = str(garde.get("message") or "")
    embed = garde.get("embed_final")
    complet = bool(garde.get("embed_complet"))
    if not embed:
        snap = garde.get("dernier") or {}
        avert = ""
        if _pause_pour(gid):
            # quota épuisé : on fige sur le relevé « terminée » du lundi, qui
            # compte déjà la semaine entière. Sans lui, on attend la fin de la
            # pause plutôt que de figer pour toujours des chiffres partiels.
            if not _couvre(snap, dimanche):
                print(f"[podium] semaine {lundi} : GetMySocial en pause et pas de relevé de la "
                      "semaine entière, figée à la fin de la pause", flush=True)
                return False
            cl = snap
            complet = not snap.get("illisibles")
        else:
            cl = classement(lundi, dimanche, gid=gid)
            complet = bool(cl["lignes"]) and not cl["illisibles"]
            if not cl["lignes"]:
                if snap.get("lignes"):
                    cl = snap
                    couvre = _couvre(snap, dimanche)
                    avert = "" if couvre else _avert_dernier_releve(snap, "la semaine", gid)
                    complet = couvre and not snap.get("illisibles")
                else:
                    cl = {"lignes": [], "illisibles": list(cl.get("illisibles") or []),
                          "frais": bool(cl.get("frais", True))}
                    avert = f"⚠️ _{_service(gid)} n'a rendu aucun chiffre pour cette semaine._"
        us = _us_pour(gid, lundi, dimanche, cl)
        if _us_manquants(us):
            complet = False            # le message le dit : des VA US y manquent
        # figé pour toujours : les têtes du thème relues juste avant
        tetes = _tetes_sures(gid)
        embed = embed_podium(cl, lundi, dimanche, gid=gid, avertissement=avert, us=us, tetes=tetes)
    code, _rep = _api("PATCH", f"/channels/{salon}/messages/{mid}",
                      json={"embeds": [embed], **_boutons(gid, False)})
    if code != 200 and _passager(code, _rep):
        garde["embed_final"] = embed
        garde["embed_complet"] = complet
        d.setdefault("vivants", {})[gid] = garde
        _ecrire(d)
        print(f"[podium] semaine {lundi} : Discord indisponible ou salon inaccessible "
              f"(HTTP {code}), message figé au prochain tour", flush=True)
        return False
    if code != 200:
        print(f"[podium] semaine {lundi} : message {mid} inéditable (HTTP {code}, supprimé "
              "à la main ?) — rien à figer", flush=True)
    d.setdefault("figes", {}).setdefault(gid, {})[lundi.isoformat()] = {
        "message": mid, "fin": dimanche.isoformat(), "mode": "sans_podium",
        "edite": code == 200, "complet": complet,
        "le": _maintenant().isoformat(timespec="minutes")}
    print(f"[podium] semaine {lundi} → {dimanche} figée sans podium sur {gid} "
          f'({"chiffres complets" if complet else "chiffres partiels"})', flush=True)
    return True


def _mentionner(gid: str, salon: str, mid: str, reponse: bool = True) -> Tuple[str, str]:
    """La mention @everyone du podium. Rend (id du message, reste à faire).

    Une édition ne notifie personne : la mention part à côté, en RÉPONSE au
    message figé, pour qu'un clic y mène. Mais répondre exige « Lire
    l'historique des messages » dans le salon (Discord 160002), ce que l'ancien
    podium, posté d'un bloc avec @everyone, ne demandait pas : un refus de ce
    genre (4xx) repart tout de suite en mention simple, avec le lien du
    podium. Discord en panne (429, 5xx) n'a rien créé : « reste à faire »
    dit sous quelle forme réessayer au tour suivant. Un délai dépassé (code
    0) a pu passer quand même : pas de second essai, un @everyone en double
    dérangerait tout le serveur.
    """
    base = {"content": MENTION_PODIUM, "allowed_mentions": {"parse": ["everyone"]}}
    if reponse:
        code, rep = _api("POST", f"/channels/{salon}/messages", json=dict(
            base, message_reference={"message_id": mid, "fail_if_not_exists": False}))
        if code == 200 and isinstance(rep, dict) and rep.get("id"):
            return str(rep["id"]), ""
        print(f"[podium] mention @everyone en réponse refusée (HTTP {code}) {str(rep)[:140]}",
              flush=True)
        if code <= 0:
            return "", ""
        if code == 429 or code >= 500:
            return "", "reponse"
    lien = f"https://discord.com/channels/{gid}/{salon}/{mid}"
    code, rep = _api("POST", f"/channels/{salon}/messages",
                     json=dict(base, content=f"{MENTION_PODIUM}\n➡️ {lien}"))
    if code == 200 and isinstance(rep, dict) and rep.get("id"):
        return str(rep["id"]), ""
    print(f"[podium] mention @everyone simple refusée (HTTP {code}) {str(rep)[:140]}", flush=True)
    return "", ("simple" if code == 429 or code >= 500 else "")


def _payer(gid: str, debut: dt.date, fin: dt.date, cl: Dict[str, Any],
           us: Optional[Dict[str, Any]]) -> None:
    """Les primes de la semaine, annoncées chacune dans le salon du gagnant.

    Le podium public reste anonyme ; le nom, le montant et l'adresse ne se
    disent que dans le salon privé du gagnant, son manager mentionné.
    Mêlé (Va IG) : suivi_va reçoit la liste affichée, pour annoncer à chaque
    VA FR le montant de son VRAI rang (2e derrière un VA US : 5$, pas 10$).
    """
    paye = _classement_paye(gid, cl, us)
    pf = _profil(gid)
    rang_tw = {x["va"]: i for i, x in enumerate((us or {}).get("lignes") or [])}
    doubles = []
    for x in paye["lignes"][:len(PRIMES)]:
        if not x.get("prime") or x.get("marche", pf["marche"]) == pf["marche"]:
            continue
        r = rang_tw.get(x["va"])
        tw = (f'aussi {r + 1}{"er" if r == 0 else "e"} du classement Twitter, memes subs : '
              f"prime Twitter {PRIMES[r]:.2f}$" if r is not None and r < len(PRIMES)
              else "hors du podium Twitter")
        doubles.append(f'{x["va"]} : {x["prime"]:.2f}$ ({tw})')
    if doubles:
        # Un VA US n'a pas de ticket sur Va IG (suivi_va le range dans
        # « inconnus »), et il est TOUJOURS aussi primé sur Twitter pour les
        # mêmes subs : le tri mêlé garde l'ordre de Twitter, les VA US du top 3
        # d'ici sont les premiers de là-bas. Ce journal disait « a payer A LA
        # MAIN … personne n'est prevenu » : suivi à la lettre, il faisait payer
        # deux fois les mêmes subs, quand les deux podiums disent « un seul prix
        # par personne ». Le choix revient au propriétaire.
        print(f"[podium] {gid} {debut} : prime(s) Va IG a des VA US, A TRANCHER : "
              + ", ".join(doubles) + ' -- "un seul prix par personne" : la prime Va IG en plus '
              "du prix Twitter, ou a personne ? Au proprietaire. Aucun ticket sur Va IG : rien "
              "n'y est annonce.", flush=True)
    try:
        import suivi_va
        b = suivi_va.annoncer_primes(gid, paye, debut, fin)
        if any(b.values()):
            print(f"[podium] primes annoncees : {b}", flush=True)
    except Exception as e:
        print(f"[podium] annonce des primes : {type(e).__name__}: {e}", flush=True)


def _primes_retenues(gid: str, d: Dict[str, Any], debut: dt.date, fin: dt.date,
                     fg: Dict[str, Any], mid: str) -> None:
    """Les annonces privées d'un podium mêlé parti sans tous ses VA US.

    Appelé à chaque tour du lundi, le podium déjà posté. Le relevé US est relu
    au plus toutes les deux heures (_releve_us) ; tant qu'un VA y manque, rien
    ne bouge. Complet : le podium est réédité sur place, sur le relevé FR de
    9h et ce relevé US (une édition ne notifie personne, pas de second
    @everyone), puis les primes sont annoncées sur cette liste-là. Jamais
    complet de la journée : rien n'est annoncé, le podium dit « à confirmer
    avant de payer », et le journal de 9h l'a dit — mieux qu'un montant faux
    promis en privé.
    """
    snap = (fg.get("primes_attente") or {}).get("cl") or {}
    if _source(gid) == "tracking":
        # Twitter : ses propres VA manquaient (pas de VA US mêlés ici). Le
        # relevé de la semaine est refait, au plus une fois l'heure
        t = time.time()
        if 0 <= t - float(fg.get("essai_tw") or 0) < 3600:
            return
        fg["essai_tw"] = t
        cl2 = classement(debut, fin, gid=gid)
        if not cl2["lignes"] or cl2["illisibles"]:
            _ecrire(d)
            return
        snap, us = _instantane(cl2, fin), None
    else:
        us = _releve_us(debut, fin)
        if not snap.get("lignes") or us is None or _us_manquants(us):
            return
    salon = _salon(gid)
    if not salon:
        return
    # le podium figé est réécrit : ses têtes relues juste avant, comme à 9h
    tetes = _tetes_sures(gid)
    code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}",
                     json={"embeds": [embed_podium(snap, debut, fin, gid=gid, us=us, tetes=tetes)],
                           **_boutons(gid, False)})
    if code != 200 and _passager(code, rep):
        print(f"[podium] {gid} {debut} : podium a corriger, Discord indisponible (HTTP {code}) -- "
              "nouvel essai au prochain tour", flush=True)
        return
    if code != 200:
        print(f"[podium] {gid} {debut} : podium {mid} ineditable (HTTP {code}, supprime a la "
              "main ?) -- primes annoncees sur le releve complet quand meme", flush=True)
    print(f"[podium] {gid} {debut} : releve {'des VA de Twitter' if us is None else 'US'} "
          "complet -- podium corrige sur place, primes annoncees", flush=True)
    # annoncer AVANT d'oublier l'attente : un arrêt entre les deux refait le
    # tour suivant, et suivi_va ne redit jamais une prime déjà dite
    _payer(gid, debut, fin, snap, us)
    fg.pop("primes_attente", None)
    fg["complet"] = code == 200 and not snap.get("illisibles")
    fg["corrige"] = _maintenant().isoformat(timespec="minutes")
    _ecrire(d)


@_exclusif
def poster_podium(gid: str, jour: Optional[dt.date] = None,
                  mentionner: bool = True, forcer: bool = False) -> str:
    """Le podium de la semaine passée. Une fois.

    Il ne poste pas un message de plus : il FIGE sur place celui de la
    semaine (chiffres du lundi au dimanche, « il ne bougera plus »), puis
    mentionne tout le monde en RÉPONSE à ce message. Avant, chaque semaine
    laissait un « SEMAINE EN COURS » orphelin aux chiffres périmés, et un
    podium posté à part, mélangé au message de la semaine suivante.
    Le message a disparu (supprimé à la main) : le podium est posté à neuf.
    `forcer` : refait le podium sur le même message s'il existe.
    """
    gid = str(gid)
    # avant tout rendu, y compris la correction des primes retenues plus bas
    _assurer_emojis(gid)
    debut, fin = semaine_passee(jour)
    d = _etat()
    postes = d.setdefault("postes", {})
    cle = f"{gid}:{debut.isoformat()}"
    if postes.get(cle) and not forcer:
        fg = ((d.get("figes") or {}).get(gid) or {}).get(debut.isoformat()) or {}
        if mentionner and fg.get("ping_a_refaire") and not fg.get("ping"):
            # le podium est figé, mais Discord avait refusé la mention en
            # passant : elle seule repart (aucun relevé), tant que c'est lundi
            salon = _salon(gid)
            if salon:
                ping, reste = _mentionner(gid, salon, str(postes[cle]),
                                          reponse=fg["ping_a_refaire"] != "simple")
                fg["ping"] = ping
                if reste:
                    fg["ping_a_refaire"] = reste
                else:
                    fg.pop("ping_a_refaire", None)
                _ecrire(d)
                if ping:
                    print(f"[podium] {debut} : mention @everyone partie au nouvel essai", flush=True)
        if fg.get("primes_attente"):
            # les annonces privées attendent le relevé US complet (voir plus
            # bas) : tant que c'est lundi, chaque tour regarde s'il l'est
            _primes_retenues(gid, d, debut, fin, fg, str(postes[cle]))
        return str(postes[cle])
    salon = _salon(gid)
    if not salon:
        print(f"[podium] salon {SALON_PODIUM} introuvable sur {gid}", flush=True)
        return ""
    cl = classement(debut, fin, gid=gid)
    if not cl["lignes"]:
        # GetMySocial muet un lundi matin : sans cela on publiait un podium VIDE
        # avec @everyone, et la semaine etait marquee comme faite POUR TOUJOURS.
        # On ne note rien : le tour suivant, dans dix minutes, reessaiera.
        print(f'[podium] {debut} → {fin} : aucun releve payable '
              f'({cl["entites"]} entites, {len(cl["illisibles"])} illisible(s)) — '
              "rien poste, nouvel essai au prochain tour", flush=True)
        return ""
    # sur Va IG, les VA US sont classés à côté des VA FR, et les primes vont
    # aux trois premiers de l'ensemble (suivi_va, plus bas, reçoit la liste
    # mêlée). Un relevé FR vide est déjà reparti plus haut : jamais un podium
    # de VA US seuls, que personne sur Va IG ne pourrait réclamer.
    us = _us_pour(gid, debut, fin, cl)
    if _mele(gid) and us is None:
        # Sans relevé US, ce podium ne sait pas qui sont ses trois premiers.
        # Avant, il partait avec les seuls VA FR, payait leurs trois premiers
        # (un VA FR 2e derrière un VA US apprenait « 1e — 10$ ») et se figeait
        # ainsi pour toujours. Même règle qu'un relevé FR raté : rien posté,
        # nouvel essai au prochain tour ; le mardi, la semaine se fige sans
        # podium ni prime (_figer_semaine), comme sans relevé FR.
        print(f"[podium] {gid} {debut} : releve US indisponible -- podium retenu (ses primes vont "
              "aux 3 premiers de toute l'agence, VA US compris), nouvel essai au prochain tour",
              flush=True)
        return ""
    # Ce podium ne bougera plus : ses têtes sont relues juste avant (la pose
    # du jour a pu précéder une suppression à la main, voir _tetes_sures)
    tetes = _tetes_sures(gid)
    embed = embed_podium(cl, debut, fin, gid=gid, us=us, tetes=tetes)

    vivants = d.setdefault("vivants", {})
    vivant = vivants.get(gid) or {}
    fige = ((d.get("figes") or {}).get(gid) or {}).get(debut.isoformat()) or {}
    if forcer and postes.get(cle):
        cible = str(postes[cle])
    elif vivant.get("semaine") == debut.isoformat() and vivant.get("message"):
        cible = str(vivant["message"])
    else:
        cible = str(fige.get("message") or "")

    mid, mode, ping, reste = "", "podium", "", ""
    if cible:
        # figé : le bouton 🔄 du message vivant s'en va
        code, _rep = _api("PATCH", f"/channels/{salon}/messages/{cible}",
                          json={"embeds": [embed], **_boutons(gid, False)})
        if code == 200:
            mid = cible
        elif _passager(code, _rep):
            print(f"[podium] {debut} : Discord indisponible ou salon inaccessible (HTTP {code}), "
                  "nouvel essai au prochain tour", flush=True)
            return ""
        else:
            print(f"[podium] message de la semaine {cible} inéditable (HTTP {code}) : "
                  "podium posté à neuf", flush=True)
    if mid:
        if mentionner:
            ping, reste = _mentionner(gid, salon, mid)
            if not ping:
                print(f"[podium] {debut} : le podium est figé sans mention"
                      + (" — nouvel essai au prochain tour" if reste else ""), flush=True)
    else:
        corps: Dict[str, Any] = {"embeds": [embed], **_boutons(gid, False)}
        if mentionner:
            corps["content"] = MENTION_PODIUM
            corps["allowed_mentions"] = {"parse": ["everyone"]}
        code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
        if code != 200 or not rep.get("id"):
            print(f"[podium] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
            return ""
        mid, mode = str(rep["id"]), "reposte"
    postes[cle] = mid
    d.setdefault("figes", {}).setdefault(gid, {})[debut.isoformat()] = {
        "message": mid, "fin": fin.isoformat(), "mode": mode, "ping": ping,
        # complet : rien ne manque au message, VA US affichés compris
        "complet": not cl["illisibles"] and not _us_manquants(us),
        "le": _maintenant().isoformat(timespec="minutes")}
    if reste:
        d["figes"][gid][debut.isoformat()]["ping_a_refaire"] = reste
    manque_us = _us_manquants(us)
    # Twitter sur les trackings : un VA sans relevé y dure (tracking que MyPuls
    # ne rend pas encore, lien partagé à corriger) et a pu être dans le top 3.
    # Les annonces privées attendent un relevé complet, relu toutes les heures
    # ce lundi (_primes_retenues) ; le podium dit déjà « à confirmer ».
    manque_tw = list(cl["illisibles"]) if _source(gid) == "tracking" else []
    if manque_tw and not manque_us:
        d["figes"][gid][debut.isoformat()]["primes_attente"] = {"cl": _instantane(cl, fin)}
        d["figes"][gid][debut.isoformat()]["essai_tw"] = time.time()
        print(f'[podium] {gid} {debut} : {len(manque_tw)} VA sans relevé '
              f'({", ".join(manque_tw[:8])}) -- annonces privees des primes RETENUES, relevé '
              "refait toutes les heures ce lundi ; des qu'il est complet, le podium est "
              "corrige sur place et les primes annoncees.", flush=True)
    elif manque_us:
        # Un VA US sans relevé a pu être dans le top 3 : les rangs payés
        # peuvent encore bouger. Le podium le dit (« à confirmer avant de
        # payer »), mais suivi_va, lui, promettait tout de suite en privé : un
        # VA FR 1er ici, 2e une fois le VA US relu, apprenait « 1e — 10$ » pour
        # une place à 5$, et le podium, posté une fois, ne revenait jamais
        # dessus. Le relevé FR est gardé ; _primes_retenues corrige le podium
        # et annonce dès que le relevé US est complet.
        d["figes"][gid][debut.isoformat()]["primes_attente"] = {"cl": _instantane(cl, fin)}
        print(f'[podium] {gid} {debut} : releve US incomplet ({", ".join(manque_us)}) -- annonces '
              "privees des primes RETENUES : un absent peut changer les rangs payes. Relu toutes "
              "les 2 h ce lundi ; des qu'il est complet, le podium est corrige sur place et les "
              "primes annoncees.", flush=True)
    else:
        _payer(gid, debut, fin, cl, us)
    # Le message vivant de la semaine ecoulee est devenu le podium : il n'est
    # plus vivant. Celui de la semaine neuve part juste apres (rafraichir, meme
    # tour de boucle), en dessous du podium.
    if vivant.get("semaine") == debut.isoformat():
        vivants.pop(gid, None)
    _ecrire(d)
    print(f'[podium] {debut} → {fin} figée dans {gid} ({mode}) : {len(cl["lignes"])} entités, '
          f'{len(cl["illisibles"])} illisible(s), liste {"fraîche" if cl["frais"] else "du cache"}',
          flush=True)
    return mid


@_exclusif
def rafraichir(gid: str, jour: Optional[dt.date] = None) -> str:
    """Met à jour (ou crée) le message VIVANT de la semaine en cours.

    Le message est RÉÉDITÉ, jamais reposté : un classement qui s'empile vingt
    fois par jour noierait le salon, et Discord ne notifie pas une édition —
    personne n'est dérangé pour trois clics de plus.

    Une semaine nouvelle veut un message neuf, mais pas avant que l'ancien
    soit fini : le lundi, il dit « semaine terminée » en attendant le podium
    (qui le fige), et la semaine neuve ne part qu'après le podium. Si le
    podium n'est jamais venu, l'ancien est figé ici, sans mention.
    """
    gid = str(gid)
    debut, fin = semaine_en_cours(jour)
    d = _etat()
    vivants = d.setdefault("vivants", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid)
    if not salon:
        print(f"[podium] salon {SALON_PODIUM} introuvable sur {gid}", flush=True)
        return ""
    # avant tout rendu : la semaine vivante, « terminée » et le gel du mardi
    _assurer_emojis(gid)

    ancienne = str(garde.get("semaine") or "")
    if garde.get("message") and ancienne and ancienne < debut.isoformat():
        if (ancienne == (debut - dt.timedelta(days=7)).isoformat()
                and _attente_podium(d, gid, jour)):
            if not garde.get("termine"):
                _semaine_terminee(gid, d, salon, garde)
            return str(garde["message"])
        # mardi (ou plus tard) sans podium : on ne laisse JAMAIS un « en cours »
        # derrière soi
        if not _figer_semaine(gid, d, salon, garde):
            return ""
        vivants.pop(gid, None)
        garde = {}
        _ecrire(d)
    if not garde.get("message") and _attente_podium(d, gid, jour):
        print(f"[podium] {gid} : semaine du {debut} retenue jusqu'au podium "
              "de la semaine passée", flush=True)
        return ""
    if _pause_pour(gid):
        # on n'est passé que pour figer la semaine finie sur ses chiffres
        # gardés : la semaine neuve attend GetMySocial pour avoir les siens
        print(f"[podium] {gid} : GetMySocial en pause, semaine du {debut} lancée à son retour",
              flush=True)
        return ""

    cl = classement(debut, fin, gid=gid)
    if not cl["lignes"] and not cl["illisibles"]:
        # aucun relevé du tout : on ne remplace pas un classement correct par du vide
        print("[podium] aucun relevé, message vivant laissé tel quel", flush=True)
        return str(garde.get("message") or "")
    corps = {"embeds": [embed_podium(cl, debut, fin, en_cours=True, gid=gid,
                                     us=_us_pour(gid, debut, fin, cl))],
             **_boutons(gid, True)}

    mid = str(garde.get("message") or "")
    if mid and garde.get("semaine") == debut.isoformat():
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json=corps)
        if code == 200 or _passager(code, rep):
            if code != 200:
                # Discord en panne passagère (ou l'accès au salon retiré) : le
                # message est toujours là. En poster un autre laissait celui-ci
                # « SEMAINE EN COURS » pour toujours, jamais figé, à côté du
                # neuf. Le passage compte quand même (pas un relevé toutes les
                # 10 min) : réessai à l'heure suivante, sur le même message.
                print(f"[podium] édition du message vivant {mid} refusée (HTTP {code}), "
                      "nouvel essai au prochain passage", flush=True)
            garde["vu"] = time.time()
            garde["dernier"] = _instantane(cl, fin)
            # même sur une panne passagère : le passage compte (pas un relevé
            # GetMySocial toutes les 10 min pour un Discord en panne)
            garde["format"] = FORMAT_AFFICHAGE
            vivants[gid] = garde
            _ecrire(d)
            return mid
        # le message a été supprimé à la main : on en refait un plutôt que de
        # rester muet jusqu'à la semaine prochaine
        print(f"[podium] édition refusée (HTTP {code}), nouveau message", flush=True)

    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    vivants[gid] = {"semaine": debut.isoformat(), "message": str(rep["id"]), "vu": time.time(),
                    "dernier": _instantane(cl, fin), "format": FORMAT_AFFICHAGE}
    _ecrire(d)
    print(f'[podium] message vivant {debut} → {fin} : {len(cl["lignes"])} entités', flush=True)
    return str(rep["id"])


def _figeable_sans_gms(d: Dict[str, Any], gid: str, garde: Dict[str, Any]) -> bool:
    """La semaine finie peut-elle être figée maintenant, sans GetMySocial ?

    Oui si la porte du lundi est ouverte et qu'on a déjà ses chiffres entiers :
    le relevé « terminée » du lundi, ou l'embed final qui attendait un Discord
    revenu. Sans ça, une pause du quota (jusqu'à 24 h) laissait le message
    dire « le podium officiel arrive ce lundi à 9h » le mardi, et la semaine
    neuve attendait avec lui.
    """
    sem = str(garde.get("semaine") or "")
    courante = semaine_en_cours()[0]
    if not garde.get("message") or not sem or sem >= courante.isoformat():
        return False
    if sem == (courante - dt.timedelta(days=7)).isoformat() and _attente_podium(d, gid):
        return False
    try:
        dimanche = dt.date.fromisoformat(sem) + dt.timedelta(days=6)
    except Exception:
        return False
    return bool(garde.get("embed_final")) or _couvre(garde.get("dernier") or {}, dimanche)


def a_rafraichir(gid: str, maintenant: Optional[float] = None) -> bool:
    """Vrai quand le message vivant a passé l'âge, ou n'existe pas encore."""
    gid = str(gid)
    if _pause_pour(gid):
        d = _etat()
        return _figeable_sans_gms(d, gid, (d.get("vivants") or {}).get(gid) or {})
    d = _etat()
    garde = (d.get("vivants") or {}).get(gid) or {}
    if garde.get("semaine") != semaine_en_cours()[0].isoformat():
        if _attente_podium(d, gid):
            # lundi, podium pas encore parti : la semaine neuve attend. Reste
            # seulement à dire « terminée » (une fois) ou à figer un message
            # plus vieux encore ; tout autre passage serait un appel
            # GetMySocial pour rien.
            if not garde.get("message"):
                return False
            passee = semaine_passee()[0].isoformat()
            ancienne = str(garde.get("semaine") or "")
            return ancienne < passee or (ancienne == passee and not garde.get("termine"))
        return True
    if garde.get("message") and garde.get("format") != FORMAT_AFFICHAGE:
        return True                     # presentation changee : refaire tout de suite
    minutes = int(_profil(gid).get("minutes") or _config().get("minutes") or MINUTES_LIVE)
    return (maintenant or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


def _etiquette(nom: str):
    """L'etiquette d'appel GetMySocial (gms.api_tag), qui garde au podium sa
    reserve quand le budget du jour baisse (gms.PRIORITES).

    NE DOIT JAMAIS FAIRE TOMBER UN RELEVE : les suites de tests remplacent
    `gms` par un faux module sans api_tag, et une etiquette de comptabilite
    n'a pas a decider si le podium sort ou non. Sans elle, l'appel part quand
    meme -- il est seulement compte comme « autres ».
    """
    import contextlib
    try:
        import gms
        return gms.api_tag(nom)
    except Exception:                                        # noqa: BLE001
        return contextlib.nullcontext()


def _quota_dit() -> str:
    """« quota GetMySocial épuisée, reprise vers 07h28 », ou "" si ce n'est pas elle.

    Vingt-trois noms alignés ne disent pas POURQUOI ils manquent : le
    propriétaire a lu cette liste comme une panne du classement, alors que la
    quota JOURNALIÈRE du compte — commune aux quatre clés, elles appartiennent
    toutes au même compte — était simplement à zéro. La raison vaut mieux que
    la liste. Rend "" dès qu'on ne sait pas : on ne remplace jamais les noms
    par une explication qu'on n'a pas.
    """
    try:
        import gms
        e = gms.etat_quota() or {}
    except Exception:                                        # noqa: BLE001
        return ""
    if not int(e.get("pause_s") or 0):
        return ""
    h = str(e.get("reprise") or "").replace(":", "h")
    return ("quota GetMySocial épuisée pour aujourd'hui"
            + (f", reprise vers {h}" if h else "")
            + " — leurs chiffres reviennent seuls")


def _pause_gms() -> bool:
    """GetMySocial nous a dit de nous calmer : on saute ce tour.

    Sans ça, le rafraîchissement tapait dans un quota déjà épuisé et volait
    les appels du tableau de bord, qui sert de vraies pages à de vraies gens.
    """
    try:
        import gms
        return int(gms.pause_restante() or 0) > 0
    except Exception:
        return False


def a_poster(maintenant: Optional[dt.datetime] = None) -> bool:
    """Vrai un lundi, passé l'heure de publication."""
    n = maintenant or _maintenant()
    return n.weekday() == 0 and n.hour >= _heure_podium()


# ─── le bouton « 🔄 Mettre à jour » ──────────────────────────────────────
# Deux minutes entre deux clics sur un même serveur : un relevé, c'est un
# appel GetMySocial par VA, et le quota est partagé avec le tableau de bord.
# En mémoire : un redémarrage le remet à zéro, sans conséquence.
ATTENTE_MAJ_S = 120
_DERNIER_CLIC: Dict[str, float] = {}


def _ephemere(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte[:2000], "flags": 64,
                                "allowed_mentions": {"parse": []}}}


def _en_fond(f) -> None:
    # le fil de verif_discord, comme /annonce : les tests le remplacent par un
    # appel direct. Le serveur du clic, lui, est reposé par _maj_en_fond.
    from verif_discord import _EN_FOND
    _EN_FOND(f)


def _staff(p: Dict[str, Any]) -> bool:
    """La même règle que /annonce (annonces_discord._manager) : administrateur,
    gestion des rôles, ou rôle manager du serveur."""
    import verif_discord as vd
    cfg = vd.serveur(str(p.get("guild_id") or ""))
    membre = p.get("member") or {}
    try:
        if cfg is not None:
            return vd._est_manager(membre, cfg)
        return bool(vd._permissions(membre) & 0x8)
    except Exception:
        return False


def _maj_en_fond(gid: str, suivi: Optional[Dict[str, bool]] = None) -> None:
    """Le travail d'un clic, après la réponse à Discord : la semaine, puis la
    quinzaine, hors rythme. Leurs règles de gel décident encore de tout (le
    lundi avant le podium, la semaine neuve attend, clic ou pas). Le verrou,
    pris par traiter, est rendu ici quoi qu'il arrive."""
    if suivi is not None:
        suivi["parti"] = True          # désormais, c'est ici que le verrou se rend
    jeton = _TIENT.set(True)
    try:
        import verif_discord as vd
        with vd.sur_serveur(gid):
            for nom, f in (("message de la semaine", lambda: rafraichir(gid)),
                           ("classement de la quinzaine", lambda: rafraichir_subs(gid, forcer=True))):
                try:
                    f()
                except Exception as e:
                    # la quinzaine passe quand même si la semaine a échoué
                    print(f"[podium] {gid} bouton 🔄 : {nom} : {type(e).__name__}: {e}", flush=True)
        print(f"[podium] {gid} : mise à jour à la main (bouton 🔄) terminée", flush=True)
    except Exception as e:
        print(f"[podium] {gid} bouton 🔄 : {type(e).__name__}: {e}", flush=True)
    finally:
        _TIENT.reset(jeton)
        _VERROU.release()


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Le clic sur « 🔄 Mettre à jour ». None si ce n'est pas ce bouton :
    l'appelant (web_upload, /discord/interactions) passe au module suivant.

    Toujours une réponse éphémère, tout de suite (3 s au plus pour Discord) ;
    le relevé, lui, prend une minute et part en fond."""
    p = p or {}
    if p.get("type") != 3 or str((p.get("data") or {}).get("custom_id") or "") != BOUTON_MAJ:
        return None
    gid = str(p.get("guild_id") or "")
    if not _staff(p):
        return _ephemere("🔒 Réservé au staff.")
    if not (SERVEURS.get(gid) or {}).get("bouton_maj"):
        # un bouton resté d'avant sur un serveur qui n'en veut plus : rien à
        # lancer, et rien de faux à promettre
        return _ephemere("ℹ️ Ce classement se met à jour tout seul, plusieurs fois par jour.")
    if not _VERROU.acquire(blocking=False):
        return _ephemere("⏳ Mise à jour déjà en cours.")
    suivi = {"parti": False}
    try:
        t = time.time()
        dernier = _DERNIER_CLIC.get(gid)
        if dernier is not None and 0 <= t - dernier < ATTENTE_MAJ_S:
            return _ephemere("⏳ Déjà mis à jour il y a moins de 2 minutes.")
        if _pause_gms():
            return _ephemere("⏸️ GetMySocial est en pause : le podium et le classement se "
                             "mettront à jour au prochain passage.")
        uid = str(((p.get("member") or {}).get("user") or {}).get("id") or "")
        print(f"[podium] {gid} : bouton 🔄 par {uid or '?'}, mise à jour lancée", flush=True)
        _DERNIER_CLIC[gid] = t
        try:
            _en_fond(lambda: _maj_en_fond(gid, suivi))
        except Exception as e:
            print(f"[podium] {gid} bouton 🔄 : lancement impossible : {type(e).__name__}: {e}",
                  flush=True)
            if not suivi["parti"]:
                _DERNIER_CLIC.pop(gid, None)
                return _ephemere("❌ Mise à jour impossible pour le moment : réessaie dans un instant.")
        else:
            # le fil est lancé : c'est LUI qui rendra le verrou, même s'il n'a
            # pas encore commencé. Le rendre ici aussi laisserait la boucle
            # entrer pendant le travail du clic, et poster en double.
            suivi["parti"] = True
        return _ephemere("🔄 Mise à jour lancée : le podium et le classement changent dans une minute.")
    finally:
        # aucun travail lancé (refus, ou fil qui n'a pas pu partir) : personne
        # d'autre ne rendrait le verrou, et le podium resterait bloqué pour de bon
        if not suivi["parti"]:
            _VERROU.release()
