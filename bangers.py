# -*- coding: utf-8 -*-
"""Archive des bangers et sélection quotidienne de Jessye / Youl4b.

Le registre conserve tous les liens, descriptions et vidéos récupérées.
La production passe par publier_journee : à partir de 9 h (Europe/Paris),
tous les reels publiés la veille au-dessus du seuil, avec un journal durable.
Les anciens sélecteurs glissants restent pour compatibilité ; le site ne
les utilise plus pour envoyer ou télécharger automatiquement.
"""
from __future__ import annotations

import pathlib
import re
import time
from typing import Any, Dict, List

import safe_json

_ICI = pathlib.Path(__file__).resolve().parent
FICHIER = _ICI / "data" / "bangers.json"

#: Les fichiers archivés. DÉLIBÉRÉMENT hors de data/insta/videos, que le démon
#: de scrape purge au bout de 31 jours (cf. cleanup_old_videos).
DOSSIER = _ICI / "data" / "bangers"

#: À partir de combien de vues un reel est un banger. Réglable depuis le site.
SEUIL_DEFAUT = 10_000

#: Bornes du réglage. En dessous de mille, tout devient un banger et l'alerte
#: ne veut plus rien dire ; au-dessus d'un million, elle ne sonnera jamais.
SEUIL_MIN, SEUIL_MAX = 1_000, 1_000_000

#: Passé cet âge, on archive sans annoncer (cf. l'en-tête).
AGE_MAX_ANNONCE_SEC = 30 * 86400

#: Combien d'annonces au maximum par passage de scrape. Le reste attend le
#: passage suivant — il y en a six par jour, la file s'écoule vite. Sans ce
#: plafond, le premier démarrage poste des dizaines de messages d'affilée.
PLAFOND_ANNONCES = 12

#: LA FENÊTRE DU TÉLÉCHARGEMENT. On ne descend que ce qui vient d'être posté.
#: Chaque vidéo coûte un appel Apify, et un reel d'avant-hier ne sera pas plus
#: intéressant demain — il est déjà dans le registre avec son lien et ses vues.
#: Sans cette borne, relancer le cycle repartait chercher des reels vieux de
#: plusieurs jours, encore et encore : c'est ce que le propriétaire a vu brûler.
FENETRE_VIDEO_SEC = 24 * 3600

#: COMBIEN DE VIDÉOS PAR JOUR, AU MAXIMUM. « Juste les 10/15 meilleurs reels
#: des 24 dernières heures, c'est tout. » Le plafond est GLISSANT (les
#: dernières 24 h, pas « depuis minuit ») : un quota calé sur minuit se
#: viderait d'un coup à 00h05 en six passages d'affilée.
PLAFOND_VIDEOS_JOUR = 12

#: Au-delà, on cesse de réessayer le téléchargement : le reel est supprimé,
#: privé, ou non servi en public. La fiche reste, avec son lien et ses vues.
ESSAIS_VIDEO_MAX = 6

#: ÉCHECS QUI NE COMPTENT PAS. Ceux-là ne disent rien du reel — ils disent que
#: NOTRE configuration est en panne : cookies absents ou refusés, yt-dlp pas
#: installé, jeton Apify manquant. Les décompter serait une mécanique perverse :
#: le cycle tourne toutes les heures, donc un cookie périmé un dimanche soir
#: aurait brûlé les six tentatives avant le lundi matin et condamné pour
#: toujours des bangers parfaitement téléchargeables. On réessaie tant que la
#: panne est de notre côté ; c'est la réparer qui débloque tout d'un coup.
RAISONS_DE_NOTRE_FAUTE = ("login_requis_cookies", "ytdlp_absent",
                          "apify_non_configure", "aucune_source")

_SC_OK = re.compile(r"^[A-Za-z0-9_-]{5,30}$")


# ---------------------------------------------------------------- registre --

def _vide() -> dict:
    return {"seuil": SEUIL_DEFAUT, "reels": {}}


def charger() -> dict:
    d = safe_json.load(FICHIER, None)
    if not isinstance(d, dict):
        return _vide()
    if not isinstance(d.get("reels"), dict):
        d["reels"] = {}
    try:
        d["seuil"] = int(d.get("seuil") or SEUIL_DEFAUT)
    except Exception:
        d["seuil"] = SEUIL_DEFAUT
    return d


def _ecrire(d: dict) -> bool:
    return safe_json.write(FICHIER, d)


def seuil() -> int:
    """Le nombre de vues à partir duquel un reel est un banger."""
    return _borner(charger().get("seuil"))


def _borner(v) -> int:
    try:
        n = int(v)
    except Exception:
        return SEUIL_DEFAUT
    return max(SEUIL_MIN, min(SEUIL_MAX, n))


def fixer_seuil(v) -> int:
    """Change le seuil. Rend la valeur RÉELLEMENT enregistrée, pas celle reçue.

    Baisser le seuil ne ré-annonce pas le passé : un reel déjà dans le registre
    y reste tel quel, et ceux qui viennent de passer sous la nouvelle barre
    seront pris au prochain scrape, avec leur âge — donc en silence s'ils sont
    vieux. C'est voulu : changer un réglage ne doit pas déclencher une salve.
    """
    d = charger()
    d["seuil"] = _borner(v)
    _ecrire(d)
    return d["seuil"]


# ---------------------------------------------------------------- lecture --

def toutes() -> List[dict]:
    """Toutes les fiches, la plus vue en premier."""
    d = charger()
    out = []
    for sc, f in (d.get("reels") or {}).items():
        if isinstance(f, dict):
            g = dict(f)
            g["shortcode"] = sc
            out.append(donnees_fiche(g) if (DETAILS_DIR / (sc + ".json")).exists() else g)
    out.sort(key=lambda f: -int(f.get("vues") or 0))
    return out


def fiche(shortcode: str) -> dict:
    return dict((charger().get("reels") or {}).get(str(shortcode or ""), {}))


def chemin_video(shortcode: str) -> pathlib.Path:
    return DOSSIER / f"{shortcode}.mp4"


def chemin_description(shortcode: str) -> pathlib.Path:
    return DOSSIER / f"{shortcode}.txt"


def video_presente(shortcode: str) -> bool:
    """Un fichier d'un kilo-octet n'est pas une vidéo : c'est un reste d'échec."""
    try:
        f = chemin_video(shortcode)
        return f.exists() and f.stat().st_size > 1024
    except Exception:
        return False


# --------------------------------------------------------------- détection --

def examiner(compte: str, reels, identite: str = "", va: str = "",
             maintenant: float = 0.0) -> dict:
    """Passe les reels d'UN compte au crible et met le registre à jour.

    Rend {"nouveaux": [fiches], "montes": [fiches]} :
      - « nouveaux »  : franchissent le seuil pour la première fois ;
      - « montes »    : déjà connus, mais leur compteur a bougé (c'est ce qui
                        permet de ré-éditer l'annonce avec le chiffre du jour).

    `compte` est le pseudo Instagram propriétaire. `identite` et `va` peuvent
    être vides : on ne sait pas toujours à qui appartient un compte, et une
    fiche sans identité vaut mieux qu'un banger perdu.
    """
    now = float(maintenant or time.time())
    s = seuil()
    d = charger()
    reg = d["reels"]
    nouveaux, montes = [], []
    change = False
    cpt = str(compte or "").strip().lstrip("@").lower()

    for r in (reels or []):
        if not isinstance(r, dict):
            continue
        sc = str(r.get("shortcode") or "").strip()
        if not _SC_OK.match(sc):
            continue
        vues = _entier(r.get("views"))
        f = reg.get(sc)

        if f is None:
            # LE SEUIL NE S'APPLIQUE QU'À L'ENTRÉE. Une fois la fiche ouverte,
            # elle ne se referme plus, même si le seuil monte ensuite.
            if vues < s:
                continue
            age = max(0.0, now - float(r.get("taken_at") or 0)) if r.get("taken_at") else 0.0
            f = {
                "compte": cpt,
                "identite": str(identite or "").strip().lower(),
                "va": str(va or "").strip(),
                "url": str(r.get("url") or "")
                       or (f"https://www.instagram.com/p/{sc}/" if sc else ""),
                "miniature": str(r.get("thumbnail_url") or ""),
                "vues": vues,
                "vues_detection": vues,
                "seuil_detection": s,
                "poste_le": _entier(r.get("taken_at")),
                "detecte_le": int(now),
                "dernier_vu": int(now),
                "video": "attente",        # attente | ok | perdue
                "essais_video": 0,
                "description": str(r.get("caption") or ""),
                # Un reel déjà vieux est archivé mais pas annoncé : voir
                # l'en-tête du module. « muet » n'est PAS « annoncé », les deux
                # se distinguent pour qu'on puisse toujours l'envoyer à la main.
                "muet": bool(r.get("taken_at")) and age > AGE_MAX_ANNONCE_SEC,
                "annonce": {},
            }
            reg[sc] = f
            change = True
            if not f["muet"]:
                nouveaux.append(dict(f, shortcode=sc))
            continue

        # Fiche connue : on rafraîchit ce qui peut avoir bougé.
        f["dernier_vu"] = int(now)
        change = True
        # LE MAXIMUM, JAMAIS LA DERNIÈRE VALEUR (cf. l'en-tête du module).
        if vues > _entier(f.get("vues")):
            f["vues"] = vues
            montes.append(dict(f, shortcode=sc))
        # Ces champs-là n'existaient pas forcément à la création, ou étaient
        # vides parce que la source du jour ne les donne pas. On les complète
        # sans jamais écraser par du vide.
        for cle, val in (("identite", str(identite or "").strip().lower()),
                         ("va", str(va or "").strip()),
                         ("miniature", str(r.get("thumbnail_url") or "")),
                         ("description", str(r.get("caption") or ""))):
            if val and not f.get(cle):
                f[cle] = val
        if not f.get("compte") and cpt:
            f["compte"] = cpt

    if change:
        _ecrire(d)
    return {"nouveaux": nouveaux, "montes": montes}


def _entier(v) -> int:
    try:
        n = int(v or 0)
    except Exception:
        return 0
    return max(0, n)


# ---------------------------------------------------------------- archivage --

def a_telecharger(limite: int = 0, maintenant: float = 0.0) -> List[dict]:
    """Les MEILLEURS reels des dernières 24 h. Rien d'autre.

    AVANT : toutes les fiches sans vidéo, les plus récemment DÉTECTÉES
    d'abord, huit par passage et six passages par jour. Une fiche restait
    candidate indéfiniment, donc relancer le cycle repartait chercher des
    reels de l'avant-veille — et chaque essai coûte un appel Apify.

    MAINTENANT, trois bornes :
      la FENÊTRE   on ne regarde que ce qui a été POSTÉ dans les 24 h ;
      le CLASSEMENT  on prend les plus VUS d'abord, pas les derniers aperçus ;
      le PLAFOND   au maximum PLAFOND_VIDEOS_JOUR par 24 h glissantes, et ce
                   qui a déjà été descendu pendant ces 24 h est DÉCOMPTÉ —
                   sans ça, six passages par jour prendraient six fois le
                   plafond.

    Ce qui sort de la fenêtre sans avoir été descendu ne le sera jamais : la
    fiche garde son lien, ses vues et sa description, seul le fichier manque.
    C'est le prix demandé, et il est dit à l'écran (« hors sélection »).

    `limite` ne sert qu'à demander MOINS que le plafond ; elle ne permet
    jamais d'en prendre plus.
    """
    now = float(maintenant or time.time())
    depuis = now - FENETRE_VIDEO_SEC
    deja, out = 0, []
    for f in toutes():
        # Ce qui a ete descendu pendant la fenetre compte contre le plafond,
        # que le fichier soit encore la ou non.
        if _entier(f.get("video_le")) >= depuis:
            deja += 1
        sc = f["shortcode"]
        if video_presente(sc):
            continue
        if _entier(f.get("essais_video")) >= ESSAIS_VIDEO_MAX:
            continue
        if not dans_la_fenetre(f, now):
            continue
        out.append(f)
    # LE MEILLEUR D'ABORD. Le tri par date de detection faisait descendre un
    # reel a 10 001 vues avant un reel a 300 000 vues repere dix minutes plus
    # tard : quand le plafond mord, c'est le second qu'on veut.
    out.sort(key=lambda f: (-_entier(f.get("vues")),
                            -_entier(f.get("poste_le"))))
    reste = max(0, PLAFOND_VIDEOS_JOUR - deja)
    if limite:
        reste = min(reste, max(0, int(limite)))
    return out[:reste]


def dans_la_fenetre(f: dict, maintenant: float = 0.0) -> bool:
    """Ce reel est-il assez récent pour mériter un téléchargement ?

    On se cale sur la date de PUBLICATION : un reel repéré aujourd'hui mais
    posté il y a trois jours n'a pas à coûter un appel.

    REPLI SUR LA DÉTECTION quand la publication est inconnue. Toutes les
    sources ne donnent pas `taken_at` ; exiger cette date aurait coupé TOUS
    les téléchargements le jour où la source change, sans un mot. Un reel
    découvert dans les dernières 24 h est de toute façon récent.
    """
    now = float(maintenant or time.time())
    ref = _entier((f or {}).get("poste_le")) or _entier((f or {}).get("detecte_le"))
    return bool(ref) and ref >= now - FENETRE_VIDEO_SEC


def noter_telechargement(shortcode: str, reussi: bool,
                         description: str = "", raison: str = "",
                         trace=None) -> bool:
    """Enregistre le résultat d'une tentative de téléchargement.

    Un échec n'efface rien : la fiche garde son lien, ses vues et sa
    description. C'est tout l'intérêt d'avoir séparé le registre du fichier —
    « pas de vidéo » devient « on a quand même le lien », pas « on a perdu le
    banger ». `raison` vient de yt-dlp (login_requis_cookies, trop_gros_50mb,
    audience_restreinte…) et sert à distinguer « ce reel est mort » de « nos
    cookies sont périmés », deux problèmes qui n'ont pas la même réponse.
    """
    sc = str(shortcode or "")
    d = charger()
    f = (d.get("reels") or {}).get(sc)
    if not isinstance(f, dict):
        return False
    # UN ÉCHEC DE NOTRE CÔTÉ NE CONSOMME PAS D'ESSAI (cf. RAISONS_DE_NOTRE_FAUTE).
    notre_faute = (not reussi) and str(raison or "") in RAISONS_DE_NOTRE_FAUTE
    if not notre_faute:
        f["essais_video"] = _entier(f.get("essais_video")) + 1
    f["essais_bloques"] = _entier(f.get("essais_bloques")) + (1 if notre_faute else 0)
    # LA TRACE, ETAPE PAR ETAPE. Une raison unique ne dit pas si l'API n'était
    # pas branchée, si la page publique a rendu vide, ou si ce sont les
    # cookies : trois pannes différentes qui n'ont pas la même réparation.
    if trace:
        f["trace_video"] = [str(x)[:70] for x in list(trace)[:8]]
    if reussi:
        f["video"] = "ok"
        f["video_le"] = int(time.time())
        f.pop("raison_video", None)
    else:
        if raison:
            f["raison_video"] = str(raison)[:80]
        # « perdue » ne veut pas dire effacée : la fiche, le lien et la
        # description restent. Seul le fichier manque.
        f["video"] = ("perdue" if f["essais_video"] >= ESSAIS_VIDEO_MAX
                      else "attente")
    # La description trouvée par le téléchargeur est souvent PLUS COMPLÈTE que
    # celle du scrape, qui est tronquée à 280 signes. On garde la plus longue.
    desc = str(description or "").strip()
    if desc and len(desc) > len(str(f.get("description") or "")):
        f["description"] = desc
    _ecrire(d)
    return True


# ----------------------------------------------------------------- annonce --

def a_annoncer(limite: int = PLAFOND_ANNONCES) -> List[dict]:
    """Les bangers jamais annoncés, du plus vu au moins vu.

    ON ATTEND LA VIDÉO. Le message Discord PORTE le fichier — c'est la
    sauvegarde, il n'y en a pas d'autre : `data/` n'est pas dans git et
    /admin/backup_data écarte les .mp4. Une annonce postée avant le
    téléchargement partirait sans pièce jointe, et on ne la rattraperait
    jamais : la fiche serait marquée annoncée, et la seule copie hors du VPS
    n'existerait pas.

    On laisse donc deux tentatives au téléchargeur avant d'annoncer quand
    même. Deux, pas six : au-delà, mieux vaut un message avec le lien seul
    qu'un banger dont personne n'entend jamais parler.

    Les fiches « muettes » (trop vieilles à la détection) n'en font pas partie.
    """
    out = []
    for f in toutes():
        if f.get("muet") or (f.get("annonce") or {}).get("message_id"):
            continue
        # Les essais BLOQUÉS comptent ici, alors qu'ils ne comptent pas comme
        # tentatives : sinon des cookies périmés empêcheraient l'annonce
        # ÉTERNELLEMENT, et on ne saurait même pas qu'un reel a explosé. La
        # vidéo, elle, sera envoyée en réponse dès qu'elle descendra
        # (cf. a_completer).
        tentatives = _entier(f.get("essais_video")) + _entier(f.get("essais_bloques"))
        if not video_presente(f["shortcode"]) and tentatives < 2:
            continue                      # laisse au téléchargeur le temps
        out.append(f)
    return out[:max(0, int(limite or 0))]


def a_completer() -> List[dict]:
    """Les bangers annoncés SANS la vidéo, dont le fichier existe maintenant.

    Le message Discord est la sauvegarde. Quand l'annonce est partie sans
    pièce jointe — cookies périmés ce jour-là — et que le fichier finit par
    descendre, il faut le poster, sinon la seule copie reste sur le VPS et
    toute la fonctionnalité rate son but.
    """
    out = []
    for f in toutes():
        a = f.get("annonce") or {}
        if not a.get("message_id") or a.get("avec_video"):
            continue
        if video_presente(f["shortcode"]):
            out.append(f)
    return out


def noter_video_envoyee(shortcode: str) -> bool:
    """La vidéo a rejoint son annonce : ne plus la renvoyer."""
    sc = str(shortcode or "")
    d = charger()
    f = (d.get("reels") or {}).get(sc)
    if not isinstance(f, dict) or not isinstance(f.get("annonce"), dict):
        return False
    f["annonce"]["avec_video"] = True
    _ecrire(d)
    return True


def forcer(compte: str, reel: dict, identite: str = "", va: str = "") -> dict:
    """Entre un reel au registre SANS regarder le seuil ni son âge.

    Sert au bouton d'essai : on veut voir la chaîne complète tourner —
    téléchargement, envoi Discord, pièce jointe — sur du contenu réel, sans
    attendre qu'un reel atteigne dix mille vues. La fiche est marquée `essai`
    pour qu'on puisse la distinguer plus tard d'une vraie détection.

    Si le reel est DÉJÀ au registre, on ne touche à rien et on rend sa fiche :
    un essai ne doit pas réinitialiser un banger authentique.
    """
    sc = str((reel or {}).get("shortcode") or "").strip()
    if not _SC_OK.match(sc):
        return {}
    d = charger()
    if sc in d["reels"]:
        return dict(d["reels"][sc], shortcode=sc)
    now = time.time()
    vues = _entier((reel or {}).get("views"))
    d["reels"][sc] = {
        "compte": str(compte or "").strip().lstrip("@").lower(),
        "identite": str(identite or "").strip().lower(),
        "va": str(va or "").strip(),
        "url": str((reel or {}).get("url") or "")
               or f"https://www.instagram.com/p/{sc}/",
        "miniature": str((reel or {}).get("thumbnail_url") or ""),
        "vues": vues,
        "vues_detection": vues,
        "seuil_detection": 0,
        "poste_le": _entier((reel or {}).get("taken_at")),
        "detecte_le": int(now),
        "dernier_vu": int(now),
        "video": "attente",
        "essais_video": 0,
        "description": str((reel or {}).get("caption") or ""),
        "muet": False,
        "essai": True,
        "annonce": {},
    }
    _ecrire(d)
    return dict(d["reels"][sc], shortcode=sc)


def a_reediter(ecart_mini: float = 0.25) -> List[dict]:
    """Les annonces dont le chiffre affiché a pris au moins 25 % de retard.

    Ré-éditer à chaque vue coûterait un appel Discord par reel et par scrape
    pour un chiffre qui n'a pas bougé à l'œil. Un quart de plus, ça se voit.
    """
    out = []
    for f in toutes():
        a = f.get("annonce") or {}
        if not a.get("message_id"):
            continue
        vu = _entier(f.get("vues"))
        aff = _entier(a.get("vues_affichees"))
        if vu > aff and (aff == 0 or (vu - aff) / float(aff) >= ecart_mini):
            out.append(f)
    return out


def noter_annonce(shortcode: str, channel_id, message_id, vues: int = 0,
                  avec_video: bool = None) -> bool:
    """Retient OÙ l'annonce a été postée, pour pouvoir l'éditer plus tard."""
    sc = str(shortcode or "")
    d = charger()
    f = (d.get("reels") or {}).get(sc)
    if not isinstance(f, dict):
        return False
    ancienne = f.get("annonce") if isinstance(f.get("annonce"), dict) else {}
    f["annonce"] = {
        "channel_id": int(channel_id or 0),
        "message_id": int(message_id or 0),
        "vues_affichees": _entier(vues) or _entier(f.get("vues")),
        # Une ré-édition du compteur ne doit pas faire oublier que la vidéo
        # avait déjà été envoyée — sinon on la reposte à chaque mise à jour.
        "avec_video": bool(ancienne.get("avec_video")) if avec_video is None
                      else bool(avec_video),
        "le": int(time.time()),
    }
    _ecrire(d)
    return True


def demuter(shortcode: str) -> bool:
    """Rend annonçable un banger archivé en silence (trop vieux à la détection).

    Sert au bouton « envoyer quand même » : l'ancienneté est une raison de ne
    pas déranger, pas une raison d'interdire.
    """
    sc = str(shortcode or "")
    d = charger()
    f = (d.get("reels") or {}).get(sc)
    if not isinstance(f, dict) or not f.get("muet"):
        return False
    f["muet"] = False
    _ecrire(d)
    return True


# ------------------------------------------------------------------ bilan --

def bilan() -> dict:
    """De quoi afficher une ligne d'état sans relire tout le registre."""
    fs = toutes()
    return {
        "seuil": seuil(),
        "total": len(fs),
        "avec_video": sum(1 for f in fs if video_presente(f["shortcode"])),
        "perdues": sum(1 for f in fs if f.get("video") == "perdue"),
        "en_attente": sum(1 for f in fs
                          if not video_presente(f["shortcode"])
                          and f.get("video") != "perdue"),
        "a_annoncer": len(a_annoncer(limite=10_000)),
        "muets": sum(1 for f in fs if f.get("muet")),
        "meilleur": (fs[0] if fs else None),
    }


# Sélection quotidienne — publication de la veille, Jessye / Youl4b.
"""Sélection du matin : publications de la veille, uniquement Jessye / Youl4b.

Le journal fige tous les reels éligibles une fois par jour. Une intention d'envoi est
écrite AVANT Discord : un résultat incertain ne provoque jamais un doublon.
Les archives restent dans bangers.py ; ce module ne supprime aucun contenu.
"""
from datetime import datetime, time as dt_time, timedelta
import fcntl
import json
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import safe_json

TZ = ZoneInfo("Europe/Paris")
HEURE = 9
IDENTITE = "jessye"
GUILD_ID = 1535758943324999711
CHANNEL_ID = 1548115360702664804
DOSSIER_JOURNEES = Path(__file__).resolve().parent / "data" / "bangers_journees"
_JOURNEE_LOCK = threading.Lock()


def fenetre_veille(maintenant=None):
    now = time.time() if maintenant is None else maintenant
    local = datetime.fromtimestamp(now, TZ)
    jour = local.date() - timedelta(days=1)
    debut = datetime.combine(jour, dt_time.min, TZ).timestamp()
    fin = datetime.combine(local.date(), dt_time.min, TZ).timestamp()
    return jour.isoformat(), debut, fin, local.hour >= HEURE


def selection_veille(reels, seuil, maintenant=None):
    """Date de publication connue, bornes [minuit, minuit[, seuil courant."""
    _, debut, fin, _ = fenetre_veille(maintenant)
    candidats = []
    for f in reels:
        try:
            if (f.get("identite") == IDENTITE and not f.get("essai")
                    and debut <= int(f.get("poste_le") or 0) < fin
                    and int(f.get("vues") or 0) >= seuil):
                candidats.append(f)
        except (TypeError, ValueError, OverflowError):
            continue
    return sorted(candidats, key=lambda f: (-int(f["vues"]), f["shortcode"]))


def _lire_journee(jour):
    path = DOSSIER_JOURNEES / (jour + ".json")
    if not path.exists():
        return None
    # Pas de repli vers un journal plus ancien : il pourrait oublier un envoi.
    record = json.loads(path.read_text())
    if (record.get("schema") != 1 or record.get("jour") != jour
            or not isinstance(record.get("reels"), dict)):
        raise ValueError("Journal bangers invalide ; aucun nouvel envoi")
    return record


def empreinte_contenu(fichier):
    """Identité exacte des images ET du son décodés, hors métadonnées MP4.

    Pas de rapprochement sur les légendes ou la miniature : une simple
    ressemblance ne suffit pas à masquer un reel. Sans vidéo lisible, on ne
    conclut pas à un doublon. Les variantes recadrées/réencodées peuvent rester.
    """
    import hashlib
    import subprocess
    if not fichier or not fichier.is_file():
        return ""
    try:
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,duration",
            "-of", "json", str(fichier)
        ], capture_output=True, text=True, timeout=15, check=True)
        streams = json.loads(probe.stdout).get("streams") or []
        formats = [next((s for s in streams if s.get("codec_type") == kind), {})
                   for kind in ("video", "audio")]
        formats = [s for s in formats if s]
        if not formats or formats[0].get("codec_type") != "video":
            return ""
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-i", str(fichier),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1",
            "-c:a", "pcm_s16le", "-f", "streamhash", "-hash", "sha256", "-"
        ], capture_output=True, text=True, timeout=60, check=True)
        lignes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lignes or not all(re.fullmatch(r"\d+,[va],SHA256=[a-fA-F0-9]{64}", line)
                                  for line in lignes):
            return ""
        payload = json.dumps(formats, sort_keys=True) + "\n" + "\n".join(lignes)
        return "decoded-v1:" + hashlib.sha256(payload.encode()).hexdigest()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def _sauver_journee(record):
    if not safe_json.write(DOSSIER_JOURNEES / (record["jour"] + ".json"), record):
        raise OSError("Journal bangers non enregistré ; envoi interrompu")


def etat_quotidien(registre, maintenant=None):
    jour, _, _, pret = fenetre_veille(maintenant)
    record = _lire_journee(jour)
    candidats = selection_veille(registre.toutes(), registre.seuil(), maintenant)
    reels = record["reels"] if record else {
        f["shortcode"]: {"etat": "envoye" if (f.get("annonce") or {}).get("message_id")
                         else "attente"} for f in candidats}
    return {"jour": jour, "heure": HEURE, "total": len(reels),
            "envoyes": sum(r.get("etat") == "envoye" for r in reels.values()),
            "doublons": sum(r.get("etat") == "doublon" for r in reels.values()),
            "non_verifies": sum(r.get("etat") == "envoye" and not r.get("empreinte")
                                 for r in reels.values()),
            "a_verifier": sum(r.get("etat") in {"envoi", "a_verifier"} for r in reels.values()),
            "fige": record is not None, "pret": pret}


def cycle_quotidien(registre, telecharger, envoyer, *, actif, disponible, maintenant=None):
    now = time.time() if maintenant is None else maintenant
    jour, _, _, pret = fenetre_veille(now)
    bilan = {"jour": jour, "annonces": 0, "telecharges": 0, "echecs": 0,
             "a_verifier": 0, "reeditions": 0, "doublons": 0}
    if not actif or not disponible or not pret:
        return dict(bilan, attente="suivi arrêté" if not actif else
                    "bot déconnecté" if not disponible else "envoi à 09:00 (Paris)")
    if not _JOURNEE_LOCK.acquire(blocking=False):
        return dict(bilan, en_cours=True)
    try:
        DOSSIER_JOURNEES.mkdir(parents=True, exist_ok=True)
        with (DOSSIER_JOURNEES / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return dict(bilan, en_cours=True)
            record = _lire_journee(jour)
            if record is None:
                record = {"schema": 1, "jour": jour, "cree_le": now,
                          "seuil": registre.seuil(), "reels": {}}
            # Les journaux de l'ancien plafond sont complétés une seule fois,
            # sans réinitialiser leurs messages ni leurs intentions d'envoi.
            if not record.get("selection_complete"):
                for f in selection_veille(registre.toutes(), record["seuil"], now):
                    a = f.get("annonce") or {}
                    record["reels"].setdefault(f["shortcode"], {
                        "etat": "envoye" if a.get("message_id") else "attente",
                        "message_id": a.get("message_id"), "video_tentee": False})
                record["selection_complete"] = True
                _sauver_journee(record)
            # Inclure les vidéos déjà envoyées ce jour, sans les reposter.
            enrichi = False
            for sc, item in record["reels"].items():
                if item.get("etat") == "envoye" and "empreinte" not in item:
                    item["empreinte"] = empreinte_contenu(
                        registre.chemin_video(sc) if registre.video_presente(sc) else None)
                    enrichi = True
            if enrichi:
                _sauver_journee(record)
            empreintes = {r["empreinte"]: sc for sc, r in record["reels"].items()
                          if r.get("empreinte") and r.get("etat") in {"envoye", "envoi", "a_verifier"}}
            for sc, item in record["reels"].items():
                if item["etat"] in {"envoi", "a_verifier"}:
                    bilan["a_verifier"] += 1
                    continue
                if item["etat"] != "attente":
                    continue
                # Une longue récupération qui traverse minuit ne poste pas
                # la sélection de l'avant-veille dans la nouvelle journée.
                clock = now if maintenant is not None else time.time()
                if fenetre_veille(clock)[0] != jour:
                    break
                f = registre.fiche(sc)
                f["shortcode"] = sc
                if not selection_veille([f], record["seuil"], clock):
                    item["etat"] = "ignore"
                    _sauver_journee(record)
                    continue
                if (f.get("annonce") or {}).get("message_id"):
                    item.update(etat="envoye", message_id=f["annonce"]["message_id"])
                    _sauver_journee(record)
                    continue
                if not registre.video_presente(sc) and not item["video_tentee"]:
                    item["video_tentee"] = True
                    _sauver_journee(record)
                    ok, desc, raison, trace = telecharger(sc, f.get("url") or "")
                    registre.noter_telechargement(sc, ok, description=desc,
                                                 raison=raison, trace=trace)
                    bilan["telecharges" if ok else "echecs"] += 1
                clock = now if maintenant is not None else time.time()
                if fenetre_veille(clock)[0] != jour:
                    break
                f = dict(registre.fiche(sc), shortcode=sc, jour_bilan=jour)
                fichier = registre.chemin_video(sc) if registre.video_presente(sc) else None
                if "empreinte" not in item:
                    item["empreinte"] = empreinte_contenu(fichier)
                    _sauver_journee(record)
                empreinte = item["empreinte"]
                original = empreintes.get(empreinte) if empreinte else None
                if original and original != sc:
                    sur = record["reels"][original]["etat"] == "envoye"
                    item.update(etat="doublon" if sur else "a_verifier", doublon_de=original)
                    _sauver_journee(record)
                    bilan["doublons" if sur else "a_verifier"] += 1
                    continue
                clock = now if maintenant is not None else time.time()
                if fenetre_veille(clock)[0] != jour:
                    break
                item["etat"] = "envoi"
                _sauver_journee(record)
                # Si le processus s'arrête ici, « envoi » empêche un nouvel
                # essai aveugle. La vérification se fait sur le salon réel.
                ok, cid, mid, info = envoyer(f, fichier)
                if ok and int(cid) == CHANNEL_ID and mid:
                    item.update(etat="envoye", message_id=int(mid))
                    _sauver_journee(record)
                    if empreinte:
                        empreintes[empreinte] = sc
                    registre.noter_annonce(sc, cid, mid, vues=int(f["vues"]),
                                          avec_video=bool(fichier))
                    bilan["annonces"] += 1
                else:
                    item.update(etat="a_verifier", erreur=str(info)[:160])
                    _sauver_journee(record)
                    bilan["a_verifier"] += 1
                    break
            return bilan
    finally:
        _JOURNEE_LOCK.release()


# Présentation complète et rattrapage explicite : le même moteur pour les deux.
DETAILS_DIR = _ICI / 'data' / 'bangers_details'
FORMAT_DISCORD = 2


def selection_jour(reels, seuil_vues, jour):
    date = datetime.strptime(jour, '%Y-%m-%d').date()
    if date.isoformat() != jour:
        raise ValueError('Date invalide')
    debut = datetime.combine(date, dt_time.min, TZ).timestamp()
    fin = datetime.combine(date + timedelta(days=1), dt_time.min, TZ).timestamp()
    result = []
    for f in reels:
        try:
            if (f.get('identite') == IDENTITE and not f.get('essai')
                    and debut <= int(f.get('poste_le') or 0) < fin
                    and int(f.get('vues') or 0) >= seuil_vues):
                result.append(f)
        except (ValueError, TypeError, OverflowError):
            pass
    return sorted(result, key=lambda f: (-int(f['vues']), f['shortcode']))


def lire_details(sc):
    if not _SC_OK.fullmatch(sc):
        raise ValueError('Shortcode invalide')
    path = DETAILS_DIR / (sc + '.json')
    # Une tentative payante interrompue ne doit pas être oubliée via un ancien backup.
    return json.loads(path.read_text()) if path.exists() else {}


def sauver_details(sc, data):
    if not _SC_OK.fullmatch(sc) or not safe_json.write(DETAILS_DIR / (sc + '.json'), data):
        raise OSError('Détails banger non sauvegardés')


def donnees_fiche(f):
    out = dict(f)
    details = lire_details(f['shortcode'])
    for key in ('likes', 'commentaires', 'vues_actuelles', 'publication_apify',
                'statistiques_le', 'erreur_apify', 'erreur_video', 'empreinte', 'annonce'):
        if key in details:
            out[key] = details[key]
    if details.get('description'):
        out['description'] = details['description']
    out['video_disponible'] = video_presente(f['shortcode'])
    if out['video_disponible']:
        out['video'] = 'ok'
    return out


def rattacher_proprietaires(fiches, comptes):
    """Compte exact du site → VA actuel ; aucune supposition en cas d'ambiguïté."""
    table = {}
    for compte in comptes:
        handle = str(compte.get('username') or '').strip().lower().lstrip('@')
        va = str(compte.get('va') or '').strip()
        if handle and va:
            table.setdefault(handle, set()).add(va)
    resultat = []
    for source in fiches:
        f = dict(source)
        candidats = table.get(str(f.get('compte') or '').strip().lower().lstrip('@'), set())
        if len(candidats) == 1:
            va = next(iter(candidats))
            if va != f.get('va'):
                f.setdefault('va_archive', f.get('va', ''))
                f['va'] = va
        resultat.append(f)
    return resultat


def preparer_fiches(fiches):
    """Métadonnées + vidéo dans un appel Apify ; cache durable entre redémarrages."""
    import apify_reels
    import jailbreak
    fiches = rattacher_proprietaires(fiches, jailbreak.list_accounts(IDENTITE))
    from concurrent.futures import ThreadPoolExecutor
    from veille_telegram import download_video_bytes
    import os
    import shutil
    import subprocess
    manquants = [f for f in fiches if not lire_details(f['shortcode']).get('apify_tente')]
    for start in range(0, len(manquants), 20):
        lot = manquants[start:start + 20]
        if not apify_reels.configured():
            raise RuntimeError('Apify non configuré : préparation différée')
        for f in lot:
            d = lire_details(f['shortcode'])
            d.update(apify_tente=True, tentative_le=time.time(), erreur_apify='verification_interrompue')
            sauver_details(f['shortcode'], d)
        diag = {}
        res = apify_reels.fetch_reel_details([f['url'] for f in lot], diag=diag)
        if diag.get('status') not in (200, 201):
            # Le serveur a refusé le run : réessai possible après temporisation.
            # Un timeout est incertain : conserver l'intention pour éviter de repayer.
            if diag.get('status') in (401, 402, 403, 429):
                for f in lot:
                    d = lire_details(f['shortcode']); d['apify_tente'] = False
                    sauver_details(f['shortcode'], d)
                raise RuntimeError(diag.get('error') or 'Apify indisponible')
            res = {}
        for f in lot:
            sc = f['shortcode']; d = lire_details(sc)
            item = res.get(sc)
            if item:
                d.update(item, statistiques_le=time.time())
            else:
                d['erreur_apify'] = diag.get('error') or 'resultat_absent'
            sauver_details(sc, d)

    def media_impl(f):
        sc = f['shortcode']; d = lire_details(sc)
        target = chemin_video(sc)
        DOSSIER.mkdir(parents=True, exist_ok=True)
        if not video_presente(sc) and not d.get('video_tentee'):
            d['video_tentee'] = True
            sauver_details(sc, d)
            cached = _ICI / 'data' / 'insta' / 'videos' / (sc + '.mp4')
            tmp = target.with_suffix('.preparation.mp4')
            if cached.exists() and cached.stat().st_size > 1024:
                shutil.copyfile(cached, tmp)
            elif d.get('video_url'):
                info = {}
                blob = download_video_bytes(d['video_url'], timeout=60, info=info)
                if blob:
                    tmp.write_bytes(blob)
                else:
                    d['erreur_video'] = str(info.get('reason') or 'telechargement_impossible')[:120]
            if tmp.exists():
                probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_type', '-of', 'json', str(tmp)],
                    capture_output=True, text=True, timeout=20)
                if probe.returncode == 0 and json.loads(probe.stdout).get('streams'):
                    os.replace(tmp, target)
                    d['erreur_video'] = ''
                else:
                    tmp.unlink()
                    d['erreur_video'] = 'fichier_video_invalide'
        if video_presente(sc) and 'empreinte' not in d:
            d['empreinte'] = empreinte_contenu(target)
        if d.get('description'):
            chemin_description(sc).write_text(d['description'], encoding='utf-8')
        d.pop('video_url', None)  # URLs CDN signées inutiles après téléchargement.
        sauver_details(sc, d)
        return donnees_fiche(f)

    def media(f):
        try:
            return media_impl(f)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            d = lire_details(f['shortcode'])
            d['erreur_video'] = type(error).__name__
            d.pop('video_url', None)
            sauver_details(f['shortcode'], d)
            return donnees_fiche(f)

    with ThreadPoolExecutor(max_workers=3) as pool:
        return {f['shortcode']: f for f in pool.map(media, fiches)}


def gerants_discord(vas, membres):
    handles = {}
    for member in membres:
        if not getattr(member, 'bot', False):
            handles.setdefault(member.name.casefold(), []).append(member)
    result = {}
    names = {}
    for va in vas:
        name = str(va.get('name') or '').strip()
        names.setdefault(name, []).append(va)
    for name, rows in names.items():
        if len(rows) != 1:
            continue
        handle = str(rows[0].get('discord_username') or '').strip().lstrip('@').casefold()
        matches = handles.get(handle, [])
        if name and len(matches) == 1:
            result[name] = str(matches[0].id)
    return result


def _nombre(value):
    try:
        return f'{int(value):,}'.replace(',', ' ') if value is not None and int(value) >= 0 else '—'
    except (ValueError, TypeError):
        return '—'


def _mention_gerant(f):
    name = str(f.get('va') or 'Non renseigné')
    uid = str(f.get('discord_id') or '')
    return ('<@' + uid + '> · ' if uid.isdigit() else '') + name


def fiche_discord(f, fichier, limite=25 * 1024 * 1024):
    """Une carte native Discord ; fichiers texte complets, mentions non notifiantes."""
    import discord
    import io
    date = datetime.strptime(f['jour_bilan'], '%Y-%m-%d').strftime('%d/%m/%Y')
    vues = f.get('vues_actuelles') if f.get('vues_actuelles') is not None else f.get('vues')
    commentaires = f.get('commentaires')
    label = 'commentaire' if commentaires == 1 else 'commentaires'
    header = (f"### @{f['compte']}\n**Géré par :** {_mention_gerant(f)}\n"
              f"Jessye · Bangers du {date}\n\n**{_nombre(vues)}** vues  ·  "
              f"**{_nombre(commentaires)}** {label}  ·  **{_nombre(f.get('likes'))}** likes")
    if f.get('vues_actuelles') is None:
        header += '\n-# Vues du dernier relevé disponible'
    elif f.get('statistiques_le'):
        at = datetime.fromtimestamp(f['statistiques_le'], TZ).strftime('%d/%m à %H:%M')
        header += f'\n-# Statistiques vérifiées le {at} · heure de Paris'
    children = [discord.ui.TextDisplay(header), discord.ui.Separator()]
    files = []
    if fichier and fichier.is_file() and fichier.stat().st_size <= limite:
        filename = f['shortcode'] + '.mp4'
        files.append(discord.File(str(fichier), filename=filename))
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(
            'attachment://' + filename, description='Vidéo de @' + f['compte'])))
    else:
        raison = ('La vidéo est archivée, mais dépasse la taille acceptée par Discord.'
                  if fichier else 'La vidéo n’a pas pu être récupérée. Le lien reste conservé.')
        children.append(discord.ui.TextDisplay('**Vidéo indisponible dans Discord**\n' + raison))
    children.append(discord.ui.Separator())
    desc = str(f.get('description') or '')
    if desc:
        display = desc.strip()
        if display.startswith('```\n') and display.endswith('```'):
            display = display[4:-3].strip()
        display = display.replace('```', '` ` `')
        suffix = ''
        if len(display) > 2700:
            display = display[:2700] + '…'
            suffix = '\nTexte complet dans le fichier ci-dessous.'
        children.append(discord.ui.TextDisplay('**Description à copier**\n```\n' + display + '\n```' + suffix))
        filename = f['shortcode'] + '_description.txt'
        files.append(discord.File(io.BytesIO(desc.encode('utf-8')), filename=filename))
        children.append(discord.ui.File('attachment://' + filename))
    else:
        children.append(discord.ui.TextDisplay('**Description**\nAucune description récupérée pour ce reel.'))
    children.append(discord.ui.ActionRow(discord.ui.Button(label='Voir le reel sur Instagram', url=f['url'])))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_colour=0x5865F2))
    return view, files


def textes_recap(record):
    """Pages sans plafond de reels ; une mention par personne sur l'ensemble du bilan."""
    jour = datetime.strptime(record['jour'], '%Y-%m-%d').strftime('%d/%m/%Y')
    visibles = [(sc, it) for sc, it in record['reels'].items() if it['etat'] in ('envoye', 'doublon')]
    videos = sum(bool(it.get('fiche', {}).get('video_disponible')) for _, it in visibles if it['etat'] == 'envoye')
    descs = sum(bool(it.get('fiche', {}).get('description')) for _, it in visibles if it['etat'] == 'envoye')
    titre = f'## Bangers du {jour} · Jessye'
    prefix = (titre + f'\n**{len(visibles)} reels repérés** · **{videos} vidéos disponibles** · **{descs} descriptions**\n'
              'Cliquez sur votre compte pour ouvrir sa fiche.\n\n')
    pages = []; texte = prefix; mentions = []; tagged = set()
    for sc, item in visibles:
        f = item['fiche']; uid = str(f.get('discord_id') or '')
        nouveau = uid.isdigit() and uid not in tagged
        who = '<@' + uid + '>' if nouveau else str(f.get('va') or 'VA non renseigné')
        mid = item.get('message_id')
        if item['etat'] == 'doublon':
            mid = record['reels'][item['doublon_de']].get('message_id')
        url = f'https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}/{mid}'
        ligne = f"• {who} → [@{f['compte']}]({url})"
        if item['etat'] == 'doublon': ligne += ' · même vidéo'
        elif not f.get('video_disponible'): ligne += ' · vidéo indisponible'
        if len(texte) + len(ligne) + 1 > 3700:
            pages.append({'texte': texte.rstrip(), 'mentions': mentions})
            texte = titre + ' · suite\n\n'; mentions = []
        texte += ligne + '\n'
        if nouveau:
            tagged.add(uid); mentions.append(uid)
    if not visibles:
        texte = titre + '\nAucun reel au-dessus du seuil repéré dans les données disponibles pour cette journée.'
    if any(it['etat'] == 'ignore' for it in record['reels'].values()):
        texte += '\n-# Certaines anciennes publications supprimées ont été conservées hors du récapitulatif.'
    pages.append({'texte': texte.rstrip(), 'mentions': mentions})
    return pages


def publier_journee(jour, preparer, publier, recapituler, *, maintenant=None, strict_veille=False):
    """Journal durable, reprise sans double envoi, bilan seulement après les fiches."""
    clock = time.time() if maintenant is None else maintenant
    date = datetime.strptime(jour, '%Y-%m-%d').date()
    if date.isoformat() != jour or date >= datetime.fromtimestamp(clock, TZ).date():
        raise ValueError('Seules les journées terminées peuvent être publiées')
    bilan = {'jour': jour, 'annonces': 0, 'reeditions': 0, 'recaps': 0, 'doublons': 0}
    if strict_veille and jour != fenetre_veille(clock)[0]:
        return dict(bilan, attente='Journée hors sélection')
    if not _JOURNEE_LOCK.acquire(blocking=False):
        return dict(bilan, en_cours=True)
    try:
        DOSSIER_JOURNEES.mkdir(parents=True, exist_ok=True)
        with (DOSSIER_JOURNEES / '.lock').open('a') as verrou:
            try:
                fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return dict(bilan, en_cours=True)
            record = _lire_journee(jour)
            if record and record.get('termine') and record.get('format') == FORMAT_DISCORD:
                return dict(bilan, termine=True, total=len(record['reels']))
            if record is None:
                record = {'schema': 1, 'jour': jour, 'seuil': seuil(), 'reels': {}, 'cree_le': clock}
            if record.get('format') != FORMAT_DISCORD:
                for f in selection_jour(toutes(), record['seuil'], jour):
                    a = f.get('annonce') or {}
                    if a.get('message_id') and int(a.get('channel_id') or 0) != CHANNEL_ID:
                        raise ValueError('Annonce existante hors Youl4b : vérification requise')
                    item = record['reels'].setdefault(f['shortcode'], {})
                    if item.get('etat') not in ('envoi', 'a_verifier'):
                        item.update(etat='attente', message_id=item.get('message_id') or a.get('message_id'))
                    item.setdefault('fiche', dict(f, jour_bilan=jour))
                record.update(format=FORMAT_DISCORD, selection_complete=True)
                _sauver_journee(record)
            if record.get('preparation_apres', 0) > clock:
                return dict(bilan, attente='Préparation temporairement indisponible')
            a_preparer = [it['fiche'] for it in record['reels'].values() if not it.get('prepare')]
            if a_preparer:
                try:
                    resultat = preparer(a_preparer)
                    for sc, f in resultat.items():
                        if sc not in record['reels']: raise ValueError('Résultat hors sélection')
                        record['reels'][sc].update(fiche=dict(f, jour_bilan=jour), prepare=True)
                    assert all(it.get('prepare') for it in record['reels'].values())
                    record.pop('erreur_preparation', None)
                except Exception as error:
                    record.update(erreur_preparation=type(error).__name__ + ': ' + str(error)[:150], preparation_apres=clock + 1800)
                    _sauver_journee(record)
                    raise
                _sauver_journee(record)
            fingerprints = {it['fiche'].get('empreinte'): sc for sc, it in record['reels'].items()
                            if it['etat'] == 'envoye' and it['fiche'].get('empreinte')}
            for sc, item in record['reels'].items():
                if item['etat'] in ('envoye', 'doublon', 'ignore'): continue
                if strict_veille and jour != fenetre_veille(time.time() if maintenant is None else maintenant)[0]:
                    return dict(bilan, attente='Journée terminée pendant le traitement')
                f = item['fiche']; fp = f.get('empreinte')
                original = fingerprints.get(fp) if fp else None
                if original and original != sc and not item.get('message_id'):
                    item.update(etat='doublon', doublon_de=original)
                    _sauver_journee(record); bilan['doublons'] += 1
                    continue
                uncertain = item['etat'] in ('envoi', 'a_verifier') and not item.get('message_id')
                edition = bool(item.get('message_id'))
                item.update(etat='edition' if edition else 'envoi', intention_le=item.get('intention_le') or time.time())
                _sauver_journee(record)
                result = publier(f, dict(item, verifier_seulement=uncertain))
                if result.get('supprime') and edition:
                    item['etat'] = 'ignore'
                elif result.get('message_id') and int(result.get('channel_id') or 0) == CHANNEL_ID:
                    item.update(etat='envoye', message_id=int(result['message_id']))
                    _sauver_journee(record)
                    d = lire_details(sc)
                    d['annonce'] = {'message_id': int(result['message_id']), 'channel_id': CHANNEL_ID,
                        'vues_affichees': f.get('vues_actuelles') or f.get('vues'),
                        'avec_video': bool(f.get('video_disponible')), 'le': int(time.time())}
                    sauver_details(sc, d)
                    if fp: fingerprints[fp] = sc
                    bilan['reeditions' if edition else 'annonces'] += 1
                else:
                    item['etat'] = 'a_verifier'
                    _sauver_journee(record)
                    return dict(bilan, a_verifier=sc)
                _sauver_journee(record)
            pages = record.setdefault('recaps', [])
            if not pages:
                pages.extend(dict(p, etat='attente') for p in textes_recap(record))
                _sauver_journee(record)
            for index, page in enumerate(pages):
                if page['etat'] == 'envoye': continue
                uncertain = page['etat'] in ('envoi', 'a_verifier')
                page.update(etat='envoi', intention_le=page.get('intention_le') or time.time())
                _sauver_journee(record)
                result = recapituler(jour, index, dict(page, verifier_seulement=uncertain))
                if not result.get('message_id') or int(result.get('channel_id') or 0) != CHANNEL_ID:
                    page['etat'] = 'a_verifier'; _sauver_journee(record)
                    return dict(bilan, a_verifier='recap')
                page.update(etat='envoye', message_id=int(result['message_id']))
                _sauver_journee(record); bilan['recaps'] += 1
            record.update(termine=True, termine_le=time.time())
            _sauver_journee(record)
            return dict(bilan, termine=True, total=len(record['reels']))
    finally:
        _JOURNEE_LOCK.release()


async def contexte_publication(client):
    import jailbreak
    channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
    if channel.guild.id != GUILD_ID:
        raise ValueError('Salon hors Youl4b')
    guild = channel.guild
    membres = guild.members if guild.chunked else [m async for m in guild.fetch_members(limit=None)]
    vas = (jailbreak.list_all().get(IDENTITE) or {}).get('vas') or []
    return channel, gerants_discord(vas, membres)


def nonce_banger(jour, reference):
    import hashlib
    return hashlib.sha256((jour + ':' + reference).encode()).hexdigest()[:24]


async def _retrouver_nonce(channel, client, nonce, depuis):
    from datetime import timezone
    after = datetime.fromtimestamp(max(0, depuis - 10), timezone.utc)
    async for message in channel.history(limit=200, after=after):
        if message.author.id == client.user.id and str(message.nonce or '') == nonce:
            return message
    return None


async def publier_fiche_discord(client, channel, f, item):
    import discord
    assert channel.id == CHANNEL_ID and channel.guild.id == GUILD_ID
    nonce = nonce_banger(f['jour_bilan'], f['shortcode'])
    if item.get('verifier_seulement'):
        found = await _retrouver_nonce(channel, client, nonce, item['intention_le'])
        return {'message_id': found.id, 'channel_id': channel.id} if found else {}
    old = None
    if item.get('message_id'):
        try:
            old = await channel.fetch_message(int(item['message_id']))
        except discord.NotFound:
            return {'supprime': True}
        assert old.author.id == client.user.id
        data = json.dumps({'content': old.content, 'embeds': [e.to_dict() for e in old.embeds],
                           'components': [c.to_dict() for c in old.components]})
        assert f['shortcode'] in data, 'Message différent du reel attendu'
    fichier = chemin_video(f['shortcode']) if video_presente(f['shortcode']) else None
    view, files = fiche_discord(f, fichier, getattr(channel.guild, 'filesize_limit', 25 * 1024 * 1024))
    try:
        if old:
            message = await old.edit(content=None, embeds=[], attachments=files, view=view,
                                     allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(view=view, files=files, nonce=nonce,
                                         allowed_mentions=discord.AllowedMentions.none())
        verified = await channel.fetch_message(message.id)
        expected = view.to_components()[0]['components']
        actual = verified.components[0].to_dict()['components']
        assert [c['type'] for c in actual] == [c['type'] for c in expected]
        assert [c.get('content') for c in actual if c['type'] == 10] == [c.get('content') for c in expected if c['type'] == 10]
        return {'message_id': verified.id, 'channel_id': channel.id}
    finally:
        for file in files: file.close()


async def publier_recap_discord(client, channel, jour, index, page):
    import discord
    assert channel.id == CHANNEL_ID and channel.guild.id == GUILD_ID
    nonce = nonce_banger(jour, 'recap:' + str(index))
    if page.get('verifier_seulement'):
        found = await _retrouver_nonce(channel, client, nonce, page['intention_le'])
        return {'message_id': found.id, 'channel_id': channel.id} if found else {}
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(page['texte']), accent_colour=0x5865F2))
    users = [discord.Object(id=int(uid)) for uid in page['mentions']]
    message = await channel.send(view=view, nonce=nonce,
        allowed_mentions=discord.AllowedMentions(everyone=False, users=users, roles=False, replied_user=False))
    verified = await channel.fetch_message(message.id)
    assert verified.components[0].to_dict()['components'][0]['content'] == page['texte']
    assert not verified.mention_everyone
    return {'message_id': verified.id, 'channel_id': channel.id}
