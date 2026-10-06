# -*- coding: utf-8 -*-
"""Archive des bangers et sélection quotidienne : Jessye / Youl4b, et les
models du serveur FR « Va IG » (un salon chacune, depuis le 03/10/2026).

Le registre conserve tous les liens, descriptions et vidéos récupérées.
La production passe par publier_journee : à partir de 9 h (Europe/Paris),
tous les reels publiés la veille au-dessus du seuil, avec un journal durable
par salon (cf. salons()).
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

#: LE SEUIL DES MODELS DU SERVEUR FR « Va IG » (MODELS_FR), fixe. Le
#: propriétaire, 06/10/2026 : « pour le serveur IG mets 1000 ». Depuis le
#: 03/10, ses salons 💥・banger-<model> ne disaient chaque matin que « Aucun
#: reel au-dessus du seuil » : à 10 000 vues, ses comptes n'y arrivaient
#: jamais. Il vaut À LA DÉTECTION (examiner, qui ouvre la fiche et lance le
#: téléchargement all-banger) comme à la sélection du matin — un seul des
#: deux, et un reel à 3 000 vues était soit jamais archivé, soit jamais posté.
#: Jessye / Youl4b et les autres identités gardent le seuil réglable (seuil()).
SEUIL_FR = 1_000

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


def seuil_de(identite) -> int:
    """Le seuil d'une identité : SEUIL_FR pour une model de Va IG, le seuil
    réglable (seuil()) pour toutes les autres, Jessye comprise."""
    return SEUIL_FR if str(identite or "").strip().lower() in MODELS_FR else seuil()


def pour_les_favoris(f) -> bool:
    """Les favoris automatiques (favoris_auto) analysent-ils ce banger ? Ce
    qu'ils prenaient avant le 06/10/2026, rien de plus : une fiche d'une
    model de Va IG sous le seuil réglable (seuil()) n'était pas un banger.

    SEUIL_FR a été demandé pour les salons de Va IG, pas pour les favoris :
    chaque banger reçu y est analysé (plusieurs secondes) et ce qu'il trouve
    est proposé dans « À vérifier ». Sans cette règle, les reels FR de 1 000
    à 9 999 vues — rattrapage FR compris, des centaines — l'auraient inondé.
    UNE règle, lue par favoris_auto._a_traiter, là où il choisit son travail
    (un garde-fou posé seulement sur l'appel après archivage ne voyait pas
    son passage de tous les quarts d'heure, qui relit ce registre)."""
    f = f if isinstance(f, dict) else {}
    ident = str(f.get("identite") or "").strip().lower()
    return not (ident in MODELS_FR and _entier(f.get("vues")) < seuil())


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

    Le seuil est celui de l'identité (seuil_de) : SEUIL_FR pour une model de
    Va IG, le seuil réglable pour les autres.
    """
    now = float(maintenant or time.time())
    d = charger()
    nouveaux, montes, change = _examiner_dans(d["reels"], compte, reels, identite, va, now)
    if change:
        _ecrire(d)
    return {"nouveaux": nouveaux, "montes": montes}


def inscrire_comptes(lots, maintenant: float = 0.0) -> dict:
    """examiner() pour PLUSIEURS comptes, en UNE lecture et UNE écriture du
    registre. `lots` : [(compte, reels, identite, va)].

    Sert au rattrapage FR (all_banger.rattrapage_fr), qui relit d'un coup les
    relevés de tous les comptes des models : un examen par compte, c'était
    autant de réécritures complètes de bangers.json, chacune pouvant écraser
    celle d'un scrape parti en même temps (examiner n'a pas de verrou).
    Rend {"nouvelles": fiches ouvertes, "par_identite": {identité: fiches
    ouvertes}, "ecrit": registre enregistré ?} — le rattrapage FR fait son
    bilan model par model."""
    now = float(maintenant or time.time())
    d = charger()
    avant = len(d["reels"])
    par_identite: dict = {}
    change = False
    for compte, reels, identite, va in (lots or []):
        n0 = len(d["reels"])
        _n, _m, c = _examiner_dans(d["reels"], compte, reels, identite, va, now)
        cle = str(identite or "").strip().lower()
        par_identite[cle] = par_identite.get(cle, 0) + len(d["reels"]) - n0
        change = change or c
    ecrit = _ecrire(d) if change else True
    return {"nouvelles": len(d["reels"]) - avant, "par_identite": par_identite, "ecrit": bool(ecrit)}


def _examiner_dans(reg: dict, compte: str, reels, identite: str, va: str,
                   now: float) -> tuple:
    """Le crible d'examiner, sur un registre DÉJÀ chargé : (nouveaux, montés,
    changé ?). L'écriture reste à l'appelant."""
    s = seuil_de(identite)
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

    return nouveaux, montes, change


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


# Sélection quotidienne — publication de la veille, un salon par marché.
"""Sélection du matin : publications de la veille, un salon 💥・banger par marché.

Youl4b (US) : Jessye seule, dans son salon fixe, comme avant. Serveur FR
« Va IG » (03/10/2026) : un salon « 💥・banger-<model> » par model. Depuis le
06/10/2026, TOUS les comptes de l'identité de la model (« check juste les
id : les comptes de Lola pour Lola »), plus seulement ceux des VA du Discord,
au seuil SEUIL_FR, et les cartes y sont anonymes (le VA par son numéro).

Le journal fige tous les reels éligibles une fois par jour. Une intention d'envoi est
écrite AVANT Discord : un résultat incertain ne provoque jamais un doublon.
Les archives restent dans bangers.py ; ce module ne supprime aucun contenu.
"""
from datetime import datetime, time as dt_time, timedelta
import fcntl
import json
import logging
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import safe_json

log = logging.getLogger("vabot.bangers")

TZ = ZoneInfo("Europe/Paris")
HEURE = 9
IDENTITE = "jessye"
GUILD_ID = 1535758943324999711
CHANNEL_ID = 1548115360702664804
DOSSIER_JOURNEES = Path(__file__).resolve().parent / "data" / "bangers_journees"
_JOURNEE_LOCK = threading.Lock()
#: Un verrou par journal de model FR. Avec le seul _JOURNEE_LOCK, la
#: préparation d'une model FR (téléchargements CDN, jusqu'à 60 s chacun) rendait
#: « en cours » la journée de Jessye lancée à côté (bouton du site, boucle).
_VERROUS_FR: dict = {}
_VERROUS_FR_GARDE = threading.Lock()


def _verrou_du_dossier(dossier) -> threading.Lock:
    """Jessye garde _JOURNEE_LOCK, partagé avec cycle_quotidien (même dossier) ;
    chaque journal FR a le sien."""
    if Path(dossier) == Path(DOSSIER_JOURNEES):
        return _JOURNEE_LOCK
    with _VERROUS_FR_GARDE:
        return _VERROUS_FR.setdefault(str(dossier), threading.Lock())

# Serveur FR « Va IG » (le propriétaire, 03/10/2026 : « banger et all-banger
# comme sur les US »). Par model, deux salons visibles des seuls VA qui ont
# son rôle : 💥・banger-<model> et son miroir 💥・all-banger-<model>
# (all_banger.py). PAS de all-banger commun (« pas de allbanger dans va ig »).
# Youl4b ne garde QUE Jessye : un reel FR posté là-bas serait lu par des VA
# qui ne travaillent pas cette model.
GUILD_FR = 1505418484052394004
MODELS_FR = ("amelia", "emma", "sarah", "julia", "lola", "alicia")
#: Les salons recréés le 03/10/2026, en tête de la catégorie de chaque model.
#: Le NOM est cherché d'abord, HORS archives : les anciens 💥・banger-<model>
#: ont été rangés dans « 🗄️ Archives salons » sous le même nom, et le plus
#: haut placé des deux était l'archivé. Ces identifiants ne servent que de
#: secours (cf. contexte_salon).
SALONS_FR = {"amelia": 1555783269172117706, "emma": 1555783279251165327,
             "julia": 1555783289199919124, "lola": 1555783298633171024,
             "sarah": 1555783308858761228, "alicia": 1555783318362923148}
#: « 💥・all-banger-<model> », juste sous le 💥・banger de la model : même
#: recherche par le nom (salon_banger_de(..., all_banger=True)).
ALL_BANGERS_FR = {"amelia": 1555784484081901588, "julia": 1555784490276888689,
                  "lola": 1555784496182206505, "sarah": 1555784501341331596,
                  "alicia": 1555784507351900291, "emma": 1555784513009885257}
#: Le nom affiché dans la carte et le récapitulatif, comme les menus FR
#: (cogs/user._capitalize_smart) l'écrivent.
LIBELLES_FR = {"amelia": "Amélia"}


def salon_us() -> dict:
    """Le salon 💥・banger de Youl4b : Jessye, salon fixe, préparation Apify.

    Relu à chaque appel, jamais figé à l'import : les essais déplacent
    DOSSIER_JOURNEES et les autres constantes du module."""
    return {"cle": "us", "marche": "us", "identite": IDENTITE, "libelle": "Jessye",
            "serveur": "Youl4b", "guild_id": GUILD_ID, "channel_id": CHANNEL_ID,
            "nom": "", "dossier": DOSSIER_JOURNEES, "apify": True,
            "discord_seulement": False}


def salon_fr(model) -> dict:
    """Le salon « 💥・banger-<model> » du serveur FR.

    Son journal vit à part (DOSSIER_JOURNEES/fr/<model>) : celui de Jessye
    reste au premier niveau, là où passes_par_salon_banger le lit. Jamais
    d'Apify (le propriétaire le refuse) : preparer_fiches_gratuit.

    PLUS DE FILTRE « VA DU DISCORD » (06/10/2026). Avec lui, la plupart des
    comptes des models — tenus par des VA sans pseudo Discord sur leur fiche
    — étaient écartés, et chaque matin le salon ne disait rien. Le
    propriétaire : « check juste les id : les comptes de Lola pour Lola,
    Amelia pour Amelia ». La sélection prend donc toute fiche dont l'identité
    est la model (selection_jour), et rien d'une autre.

    `anonyme` : sur Va IG, aucune mention ni nom de VA dans les cartes et le
    récapitulatif (« j'ai peur qu'ils se volent, fais en mode anonyme »),
    le VA par son numéro, « Amelia VA 3 » (anonymiser_fr)."""
    m = str(model or "").strip().lower()
    return {"cle": "fr:" + m, "marche": "fr:" + m, "identite": m,
            "libelle": LIBELLES_FR.get(m, m.capitalize()), "serveur": "Va IG",
            "guild_id": GUILD_FR, "channel_id": SALONS_FR.get(m, 0), "nom": "banger-" + m,
            "dossier": DOSSIER_JOURNEES / "fr" / m, "apify": False,
            "discord_seulement": False, "anonyme": True}


def salons_fr() -> list:
    return [salon_fr(m) for m in MODELS_FR]


def salons() -> list:
    """Tous les salons du matin, Jessye d'abord."""
    return [salon_us()] + salons_fr()


def _salon(salon) -> dict:
    return salon if salon is not None else salon_us()


class SalonAbsent(LookupError):
    """Le salon d'une model est introuvable, ou le bot n'y a pas ses droits :
    cette model est passée, les autres et Jessye continuent."""


#: Les messages déjà journalisés une fois (salon FR absent…), par salon. Remis
#: à zéro quand sa journée est terminée : une rechute se dit de nouveau.
_DITS: set = set()


def _dire_une_fois(cle: str, message: str, niveau=logging.WARNING) -> None:
    if cle in _DITS:
        return
    _DITS.add(cle)
    log.log(niveau, message)


def fenetre_veille(maintenant=None):
    now = time.time() if maintenant is None else maintenant
    local = datetime.fromtimestamp(now, TZ)
    jour = local.date() - timedelta(days=1)
    debut = datetime.combine(jour, dt_time.min, TZ).timestamp()
    fin = datetime.combine(local.date(), dt_time.min, TZ).timestamp()
    return jour.isoformat(), debut, fin, local.hour >= HEURE


def selection_veille(reels, seuil, maintenant=None, identite=None):
    """Date de publication connue, bornes [minuit, minuit[, seuil courant."""
    _, debut, fin, _ = fenetre_veille(maintenant)
    ident = IDENTITE if identite is None else identite
    candidats = []
    for f in reels:
        try:
            if (f.get("identite") == ident and not f.get("essai")
                    and debut <= int(f.get("poste_le") or 0) < fin
                    and int(f.get("vues") or 0) >= seuil):
                candidats.append(f)
        except (TypeError, ValueError, OverflowError):
            continue
    return sorted(candidats, key=lambda f: (-int(f["vues"]), f["shortcode"]))


def _lire_journee(jour, dossier=None):
    path = (DOSSIER_JOURNEES if dossier is None else Path(dossier)) / (jour + ".json")
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


def _sauver_journee(record, dossier=None):
    dossier = DOSSIER_JOURNEES if dossier is None else Path(dossier)
    if not safe_json.write(dossier / (record["jour"] + ".json"), record):
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


def selection_jour(reels, seuil_vues, jour, identite=None):
    date = datetime.strptime(jour, '%Y-%m-%d').date()
    if date.isoformat() != jour:
        raise ValueError('Date invalide')
    debut = datetime.combine(date, dt_time.min, TZ).timestamp()
    fin = datetime.combine(date + timedelta(days=1), dt_time.min, TZ).timestamp()
    ident = IDENTITE if identite is None else identite
    result = []
    for f in reels:
        try:
            if (f.get('identite') == ident and not f.get('essai')
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
                'statistiques_le', 'statistiques_source', 'erreur_apify', 'erreur_video',
                'empreinte', 'annonce'):
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


#: Le relevé du scrape (HikerAPI, déjà payé), un fichier par compte : vues,
#: likes, commentaires, légende et lien CDN de chaque reel. Lu, jamais écrit ici.
CACHE_SCRAPE = _ICI / 'data' / 'insta' / 'cache'
#: Le cache vidéo des Trends : une copie s'y prend, jamais un déplacement.
CACHE_VIDEOS = _ICI / 'data' / 'insta' / 'videos'


def _reel_du_scrape(compte, sc):
    """(le reel `sc` tel que le dernier scrape de @compte l'a vu, date du relevé),
    ou ({}, 0) : compte jamais scrapé, relevé illisible, reel sorti de la liste."""
    h = str(compte or '').strip().lower().lstrip('@')
    if not h or '/' in h or '\\' in h or h.startswith('.'):
        return {}, 0
    try:
        d = json.loads((CACHE_SCRAPE / (h + '.json')).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}, 0
    if not isinstance(d, dict):
        return {}, 0
    for r in d.get('reels') or []:
        if isinstance(r, dict) and str(r.get('shortcode') or '') == sc:
            return r, _entier(d.get('scraped_at'))
    return {}, 0


def _video_valide(chemin):
    """Un vrai fichier vidéo : ffprobe quand il est là, sinon la signature MP4
    (« ftyp »). Sans ce repli, un poste sans ffprobe levait et laissait le
    tampon derrière lui."""
    import shutil
    import subprocess
    try:
        if chemin.stat().st_size <= 1024:
            return False
    except OSError:
        return False
    if shutil.which('ffprobe'):
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                    '-show_entries', 'stream=codec_type', '-of', 'json', str(chemin)],
                                   capture_output=True, text=True, timeout=20)
            return probe.returncode == 0 and bool(json.loads(probe.stdout or '{}').get('streams'))
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
    try:
        with open(chemin, 'rb') as fh:
            return b'ftyp' in fh.read(64)
    except OSError:
        return False


def _preparer_gratuit_un(f):
    import os
    import shutil
    sc = f['shortcode']
    d = lire_details(sc)
    reel, releve_le = _reel_du_scrape(f.get('compte'), sc)
    if reel:
        # Un compteur ne redescend pas : le plus haut entre le registre et le relevé.
        d.update(vues_actuelles=max(_entier(reel.get('views')), _entier(f.get('vues'))),
                 likes=_entier(reel.get('likes')), commentaires=_entier(reel.get('comments')),
                 statistiques_source='scrape')
        if releve_le:
            d['statistiques_le'] = releve_le
    else:
        # Dit dans les détails : la carte montre alors « — » et les vues du
        # registre, pas des zéros inventés.
        d.setdefault('statistiques_source', 'absente')
    textes = [str(f.get('description') or ''), str(d.get('description') or ''),
              str((reel or {}).get('caption') or '')]
    try:
        if chemin_description(sc).exists():
            textes.append(chemin_description(sc).read_text(encoding='utf-8', errors='replace'))
    except OSError:
        pass
    desc = max((t.strip() for t in textes), key=len)
    if len(desc) > len(str(d.get('description') or '')):
        d['description'] = desc
    target = chemin_video(sc)
    if not video_presente(sc) and not d.get('video_tentee'):
        d['video_tentee'] = True
        sauver_details(sc, d)
        DOSSIER.mkdir(parents=True, exist_ok=True)
        # Un suffixe qui n'est PAS .mp4 : un glob("*.mp4") ne doit jamais
        # prendre un tampon pour une vidéo de l'archive.
        tmp = target.with_name(sc + '.preparation.part')
        try:
            cached = CACHE_VIDEOS / (sc + '.mp4')
            if cached.is_file() and cached.stat().st_size > 1024:
                shutil.copyfile(cached, tmp)
            elif reel.get('video_url'):
                # UN GET sur le CDN d'Instagram, sans clé ni cookie : gratuit.
                from veille_telegram import download_video_bytes
                info = {}
                blob = download_video_bytes(reel['video_url'], timeout=60, info=info)
                if blob:
                    tmp.write_bytes(blob)
                else:
                    d['erreur_video'] = str(info.get('reason') or 'telechargement_impossible')[:120]
            else:
                d['erreur_video'] = 'aucune_source_gratuite'
            if tmp.exists():
                if _video_valide(tmp):
                    os.replace(tmp, target)
                    d['erreur_video'] = ''
                else:
                    d['erreur_video'] = 'fichier_video_invalide'
        finally:
            if tmp.exists():
                tmp.unlink()
    if video_presente(sc) and 'empreinte' not in d:
        d['empreinte'] = empreinte_contenu(target)
    sauver_details(sc, d)
    return donnees_fiche(f)


def preparer_fiches_gratuit(fiches, identite):
    """La préparation des fiches SANS rien payer (serveur FR, 03/10/2026).

    Le propriétaire refuse Apify (« j'peux rien avec ») : tout vient de ce
    qui est déjà payé ou gratuit —
      statistiques  le dernier relevé du scrape (CACHE_SCRAPE) : vues, likes,
                    commentaires, légende ;
      vidéo         l'archive des bangers (all_banger l'y a descendue à la
                    détection), sinon le cache des Trends, sinon UN GET sur le
                    lien CDN du relevé ;
      empreinte     calculée ici (ffmpeg), pour regrouper les copies.
    Une vidéo introuvable n'arrête rien : la fiche part avec son lien, et la
    raison reste dans les détails (erreur_video). Rend {shortcode: fiche}."""
    import jailbreak
    import subprocess
    fiches = rattacher_proprietaires(fiches, jailbreak.list_accounts(identite))
    out = {}
    for f in fiches:
        try:
            out[f['shortcode']] = _preparer_gratuit_un(f)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            d = lire_details(f['shortcode'])
            d['erreur_video'] = type(error).__name__
            sauver_details(f['shortcode'], d)
            out[f['shortcode']] = donnees_fiche(f)
    return out


def _handle(compte) -> str:
    return str(compte or '').strip().lower().lstrip('@')


def comptes_admis(identite, membres=None) -> set:
    """Les comptes Instagram d'une model tenus par un VA du Discord FR.

    PLUS UTILISÉ PAR LES SALONS FR depuis le 06/10/2026 (salon_fr :
    discord_seulement False, tous les comptes de l'identité). Gardé pour un
    salon qui le redemanderait (publier_journee, `admis`).

    Le propriétaire (03/10/2026) : seuls comptent les comptes des VA Discord.
    Un compte est admis si son VA (jailbreak.json, sous CETTE model) porte un
    pseudo Discord — le bouton « 📷 Mes comptes » l'y écrit
    (cogs/user._enregistrer_comptes_fr) — et, quand on connaît les membres du
    serveur (`membres` : leurs pseudos), si ce pseudo en fait partie. Un VA du
    site seul, sans Discord, n'entre pas. `membres` vide ou None : on ne sait
    pas qui est sur le serveur (intention « membres » absente), le pseudo seul
    suffit — écarter tout le monde sur une liste vide serait se taire.

    Fiche SANS pseudo Discord mais dont le NOM est le pseudo d'un membre du
    serveur : admise. Le bouton nomme le VA d'après son pseudo Discord, mais
    add_va refuse un nom déjà pris — fiche créée sur le site, ou fabriquée
    par add_account avec un pseudo vide : les comptes s'y rangeaient sans que
    le pseudo soit jamais écrit, et tous les bangers d'un VA bien présent sur
    Va IG partaient en `hors_discord`. Seulement quand les membres sont
    connus : sans eux, un nom ne prouve rien. Une fiche dont le pseudo est
    renseigné et DIFFÉRENT reste jugée sur ce pseudo-là."""
    import jailbreak
    entree = (jailbreak.list_all() or {}).get(str(identite or '').strip().lower()) or {}
    pseudos = {str(m or '').strip().lstrip('@').casefold() for m in (membres or ())}
    pseudos.discard('')
    vas_ok, par_nom = set(), []
    declares = set()
    for va in entree.get('vas') or []:
        if not isinstance(va, dict):
            continue
        nom = str(va.get('name') or '').strip().casefold()
        pseudo = str(va.get('discord_username') or '').strip().lstrip('@').casefold()
        if nom:
            declares.add(nom)
        if nom and pseudo and (not pseudos or pseudo in pseudos):
            vas_ok.add(nom)
        elif nom and not pseudo and pseudos and nom in pseudos:
            vas_ok.add(nom)
            par_nom.append(nom)
    # Fiches implicites (un nom porté par des comptes, absent de vas[]) : même
    # cas — le bouton y range les comptes sans qu'aucune fiche ne reçoive le
    # pseudo.
    if pseudos:
        for a in entree.get('accounts') or []:
            nom = str(a.get('va') or '').strip().casefold() if isinstance(a, dict) else ''
            if nom and nom not in declares and nom not in vas_ok and nom in pseudos:
                vas_ok.add(nom)
                par_nom.append(nom)
    if par_nom:
        # Compté et nommé : c'est le signe qu'une fiche attend son pseudo
        # Discord (à poser sur le site, ou par un nouveau clic du VA).
        log.info(f"[bangers] {identite} : {len(par_nom)} VA admis par leur nom faute de pseudo "
                 f"Discord sur la fiche : " + ', '.join(sorted(par_nom)[:10])
                 + (' …' if len(par_nom) > 10 else ''))
    return {_handle(a.get('username')) for a in entree.get('accounts') or []
            if isinstance(a, dict) and _handle(a.get('username'))
            and str(a.get('va') or '').strip().casefold() in vas_ok}


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


# ------------------------------------------------ Va IG : le VA par son numéro --
#
# Le propriétaire, 06/10/2026 : « mets pas de @ de Discord pour Va IG, j'ai
# peur qu'ils se volent, fais en mode anonyme », puis « mets le numéro du
# VA ». Sur Va IG, un VA est « Amelia VA 3 » partout : ticket, lien
# GetMySocial, podium (liens_fr.numero_va, data/numeros_va_fr.json). Les
# cartes du matin et le récapitulatif disent CE numéro là où ils mettaient la
# mention, jamais le pseudo ni le nom ; un VA sans numéro connu est « VA »,
# compté au journal. La carte all-banger, elle, ne nomme aucun VA, comme sur
# Youl4b (all_banger.NUMERO_VA_ALL_BANGER_FR, coupé).


def gerants_fr(entree, membres) -> dict:
    """{nom du VA : id Discord} pour une model FR (`entree` : son identité de
    jailbreak.json, `membres` : ceux du serveur).

    D'abord le pseudo Discord écrit sur la fiche (gerants_discord, comme
    Jessye). Puis la règle de comptes_admis pour une fiche SANS pseudo, ou un
    VA implicite (un nom porté par des comptes, absent de vas[]) : le membre
    dont le pseudo EST le nom du VA. Le bouton « 📷 Mes comptes » nomme le VA
    d'après son pseudo sans toujours pouvoir l'écrire (add_va refuse un nom
    déjà pris) : sans ce repli, un VA bien présent sur Va IG restait « VA ».
    Un pseudo renseigné et différent fait foi ; un nom porté par deux fiches,
    ou par deux membres, ne désigne personne."""
    entree = entree if isinstance(entree, dict) else {}
    vas = [v for v in entree.get('vas') or [] if isinstance(v, dict)]
    membres = list(membres or [])
    out = gerants_discord(vas, membres)
    par_pseudo = {}
    for m in membres:
        if not getattr(m, 'bot', False):
            par_pseudo.setdefault(str(getattr(m, 'name', '') or '').casefold(), []).append(m)
    noms = {}
    for v in vas:
        noms.setdefault(str(v.get('name') or '').strip(), []).append(v)
    sans_pseudo = [n for n, rows in noms.items() if n and len(rows) == 1
                   and not str(rows[0].get('discord_username') or '').strip().lstrip('@')]
    declares = {n.casefold() for n in noms if n}
    sans_pseudo += sorted({str(a.get('va') or '').strip() for a in entree.get('accounts') or []
                           if isinstance(a, dict) and str(a.get('va') or '').strip()
                           and str(a.get('va') or '').strip().casefold() not in declares})
    for n in sans_pseudo:
        trouves = par_pseudo.get(n.casefold(), [])
        if n not in out and len(trouves) == 1:
            out[n] = str(trouves[0].id)
    return out


def numero_va_fr(model, uid) -> int:
    """Le numéro du VA (id Discord `uid`) dans cette model, 0 s'il n'en a pas.

    LECTURE SEULE (creer=False) : un numéro se donne dans l'ordre des tickets
    de la catégorie (cogs/outils.numeroter), une carte ne doit pas en
    attribuer un au passage."""
    if not str(uid or '').strip().isdigit():
        return 0
    try:
        import liens_fr
        return int(liens_fr.numero_va(int(uid), str(model or '').strip().lower(), creer=False) or 0)
    except Exception as e:                                    # noqa: BLE001
        _dire_une_fois(f"numero_fr|{type(e).__name__}",
                       f"[bangers] numéros des VA FR illisibles ({type(e).__name__}: {e}) : "
                       f"les cartes disent « VA »")
        return 0


def libelle_va_fr(model, numero) -> str:
    """« Amelia VA 3 », écrit comme le podium et le lien GetMySocial
    (liens_fr.MODELS) ; « VA » sans numéro."""
    if not numero:
        return 'VA'
    m = str(model or '').strip().lower()
    try:
        import liens_fr
        nom = liens_fr.MODELS[m]['nom']
    except Exception:                                         # noqa: BLE001
        nom = m.capitalize()
    return f'{nom} VA {int(numero)}'


def anonymiser_fr(fiches, model, gerants) -> dict:
    """Va IG : chaque fiche préparée reçoit `va_libelle` (« Amelia VA 3 ») et
    `va_numero`, et PERD `discord_id` : rien dans la carte ni le récapitulatif
    ne peut plus mentionner ou nommer le VA. Rend `fiches` ({sc: fiche}).

    Un VA sans numéro (inconnu du compte, absent du serveur, pas encore
    numéroté) est affiché « VA » : COMPTÉ et dit au journal, avec la cause."""
    par_nom = {str(k).strip().casefold(): str(v) for k, v in (gerants or {}).items()}
    numeros, sans = {}, []
    for sc, f in (fiches or {}).items():
        va = str(f.get('va') or '').strip()
        uid = par_nom.get(va.casefold(), '') if va else ''
        if uid not in numeros:
            numeros[uid] = numero_va_fr(model, uid)
        n = numeros[uid]
        f.pop('discord_id', None)
        f['va_numero'] = n
        f['va_libelle'] = libelle_va_fr(model, n)
        if not n:
            cause = ('compte sans VA' if not va else 'VA absent du serveur' if not uid
                     else 'VA sans numéro')
            sans.append(f"{f.get('shortcode') or sc} ({cause}{' : ' + va if va else ''})")
    if sans:
        log.info(f"[bangers] {model} : {len(sans)} fiche(s) sans numéro de VA, affichée(s) « VA » : "
                 + ', '.join(sans[:10]) + (' …' if len(sans) > 10 else ''))
    return fiches


def gerant_fr(model, fiche, membres) -> tuple:
    """(« Amelia VA 3 » ou « VA », numéro, cause) du VA qui tient AUJOURD'HUI
    le compte de cette fiche (rattacher_proprietaires), pour le all-banger
    quand all_banger.NUMERO_VA_ALL_BANGER_FR est allumé (coupé par défaut).
    Le all-banger n'a pas la préparation du matin sous la main : même règle,
    même table de numéros. `cause` dit pourquoi il n'y a pas de numéro ("" sinon)."""
    import jailbreak
    m = str(model or '').strip().lower()
    entree = (jailbreak.list_all() or {}).get(m) or {}
    f = rattacher_proprietaires([dict(fiche or {})], entree.get('accounts') or [])[0]
    va = str(f.get('va') or '').strip()
    uid = {k.casefold(): v for k, v in gerants_fr(entree, membres).items()}.get(va.casefold(), '') \
        if va else ''
    n = numero_va_fr(m, uid)
    cause = ('' if n else 'compte sans VA' if not va else 'VA absent du serveur' if not uid
             else 'VA sans numéro')
    return libelle_va_fr(m, n), n, cause


def rattacher_gerants(fiches, salon, gerants) -> dict:
    """Après la préparation du matin : qui gère chaque fiche. Jessye : l'id
    Discord du VA (`discord_id`, mention non notifiante), comme avant. Un
    salon anonyme (Va IG) : son numéro, jamais son id (anonymiser_fr)."""
    s = _salon(salon)
    if s.get('anonyme'):
        return anonymiser_fr(fiches, s['identite'], gerants)
    for f in fiches.values():
        f['discord_id'] = gerants.get(f.get('va'), '')
    return fiches


def _nombre(value):
    try:
        return f'{int(value):,}'.replace(',', ' ') if value is not None and int(value) >= 0 else '—'
    except (ValueError, TypeError):
        return '—'


def _mention_gerant(f):
    name = str(f.get('va') or 'Non renseigné')
    uid = str(f.get('discord_id') or '')
    return ('<@' + uid + '> · ' if uid.isdigit() else '') + name


def fiche_discord(f, fichier, limite=25 * 1024 * 1024, libelle='Jessye', anonyme=False):
    """Une carte native Discord ; fichiers texte complets, mentions non notifiantes.

    La vidéo, la description et le bouton viennent des briques partagées avec
    le salon « all-banger » (bloc_video_discord, blocs_description_discord) ;
    seul l'en-tête (compte, VA, statistiques) est propre au message du matin.
    `libelle` : la model du salon (« Jessye » sur Youl4b, « Amélia »… sur le
    serveur FR).

    `anonyme` (Va IG) : le VA par son numéro (`va_libelle`, anonymiser_fr),
    jamais sa mention ni son nom — même pour une fiche préparée avant cette
    règle, qui porte encore `discord_id` : elle dit alors « VA ».
    """
    import discord
    date = datetime.strptime(f['jour_bilan'], '%Y-%m-%d').strftime('%d/%m/%Y')
    vues = f.get('vues_actuelles') if f.get('vues_actuelles') is not None else f.get('vues')
    commentaires = f.get('commentaires')
    label = 'commentaire' if commentaires == 1 else 'commentaires'
    gerant = str(f.get('va_libelle') or 'VA') if anonyme else _mention_gerant(f)
    header = (f"### @{f['compte']}\n**Géré par :** {gerant}\n"
              f"{libelle} · Bangers du {date}\n\n**{_nombre(vues)}** vues  ·  "
              f"**{_nombre(commentaires)}** {label}  ·  **{_nombre(f.get('likes'))}** likes")
    if f.get('vues_actuelles') is None:
        header += '\n-# Vues du dernier relevé disponible'
    elif f.get('statistiques_le'):
        at = datetime.fromtimestamp(f['statistiques_le'], TZ).strftime('%d/%m à %H:%M')
        # Le relevé du scrape (serveur FR, sans Apify) n'est pas une
        # vérification du jour : la carte dit d'où vient le chiffre.
        header += (f'\n-# Relevé du scrape du {at} · heure de Paris'
                   if f.get('statistiques_source') == 'scrape'
                   else f'\n-# Statistiques vérifiées le {at} · heure de Paris')
    children = [discord.ui.TextDisplay(header), discord.ui.Separator()]
    files = []
    if fichier and fichier.is_file() and fichier.stat().st_size <= limite:
        galerie, video = bloc_video_discord(f['shortcode'], fichier, 'Vidéo de @' + f['compte'])
        files.append(video)
        children.append(galerie)
    else:
        raison = ('La vidéo est archivée, mais dépasse la taille acceptée par Discord.'
                  if fichier else 'La vidéo n’a pas pu être récupérée. Le lien reste conservé.')
        children.append(discord.ui.TextDisplay('**Vidéo indisponible dans Discord**\n' + raison))
    children.append(discord.ui.Separator())
    blocs, joints = blocs_description_discord(f['shortcode'], f.get('description'), f['url'])
    children.extend(blocs)
    files.extend(joints)
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_colour=COULEUR_FICHE))
    return view, files


#: Le liseré des cartes de bangers, le même partout (matin et « all-banger ») :
#: le salon doit reconnaître une carte de banger d'un coup d'œil.
COULEUR_FICHE = 0x5865F2


def bloc_video_discord(shortcode, fichier, description=None):
    """La vidéo d'un banger en galerie (Components V2) et le fichier à joindre.

    Commun à la fiche du matin et au salon « all-banger » : la galerie pointe
    sur `attachment://<shortcode>.mp4`, et c'est ce NOM de pièce jointe que
    les vérifications anti-doublon relisent ensuite dans le salon. Deux
    constructions séparées pouvaient diverger sans que rien ne le dise.
    `description` est le texte alternatif de la vidéo (None : aucun).
    """
    galerie, fichiers = bloc_medias_discord([(fichier, shortcode + '.mp4', description)])
    return galerie, fichiers[0]


def bloc_medias_discord(medias):
    """Une galerie (Components V2) et ses pièces jointes, pour [(fichier, nom, alt)].

    La brique de bloc_video_discord, partagée avec les cartes de livraison du
    salon -content des VA (cogs/user.py) : une galerie ne montre une pièce
    jointe que si `attachment://<nom>` désigne EXACTEMENT le nom donné au
    fichier ; deux constructions séparées pouvaient diverger en silence.
    `nom` doit rester dans [a-zA-Z0-9_.-] : Discord réécrit les autres noms
    au téléversement, et la galerie pointerait alors dans le vide.

    Un fichier absent lève (FileNotFoundError) après avoir refermé ceux déjà
    ouverts : sans ça, chaque essai raté laissait un descripteur ouvert.
    """
    import discord
    items, fichiers = [], []
    try:
        for fichier, nom, description in medias:
            items.append(discord.MediaGalleryItem('attachment://' + nom, description=description))
            fichiers.append(discord.File(str(fichier), filename=nom))
    except Exception:
        for f in fichiers:
            f.close()
        raise
    return discord.ui.MediaGallery(*items), fichiers


#: Au-delà, un texte « à copier » est coupé à l'affichage et marqué d'un « … ».
#: Une légende Instagram fait 2200 signes au plus ; un message en composants
#: n'en porte que 4000 en tout.
PLAFOND_A_COPIER = 3500


def texte_a_copier(texte, plafond=PLAFOND_A_COPIER):
    """(texte tel qu'il s'affiche dans un bloc de code, coupé ?).

    Un bloc déjà entouré de ``` est déballé ; les ``` restants sont cassés
    (« ` ` ` ») : ils fermeraient le bloc par le milieu et la suite sortirait
    interprétée en Markdown — des « _ » de hashtags mangés, justement ce que
    le bloc évite."""
    display = str(texte or '').strip()
    if display.startswith('```\n') and display.endswith('```'):
        display = display[4:-3].strip()
    display = display.replace('```', '` ` `')
    coupe = len(display) > plafond
    if coupe:
        display = display[:plafond] + '…'
    return display, coupe


def contenu_a_copier(titre, texte, plafond=PLAFOND_A_COPIER):
    """« **<titre>** » puis le texte dans un bloc de code, et s'il a été coupé.

    La MÊME mise en forme pour les bangers (« Description à copier ») et les
    cartes de livraison des VA : le propriétaire copie de l'un comme de
    l'autre, une coupe différente d'un côté aurait donné deux textes."""
    display, coupe = texte_a_copier(texte, plafond)
    return '**' + titre + '**\n```\n' + display + '\n```', coupe


def blocs_description_discord(shortcode, description, url, joindre_fichier=True):
    """« Description à copier » puis le bouton « Voir le reel sur Instagram ».

    Rend (composants, fichiers). Les deux messages de bangers (la fiche du
    matin, le salon « all-banger ») les montrent À L'IDENTIQUE : le
    propriétaire les copie de l'un comme de l'autre, une coupe différente
    d'un côté aurait donné deux textes pour le même reel.

    Le texte va dans un bloc de code : il s'y copie tel quel (pas d'italique
    mangé entre deux « _ » de hashtags, pas de lien déroulé). Au-delà de 2700
    signes il est coupé à l'affichage — un message en composants ne porte que
    4000 signes en tout — et le fichier joint garde TOUJOURS le texte complet.

    `joindre_fichier=False` (salon « all-banger ») : pas de .txt joint. Le
    propriétaire n'en veut pas là (26/09/2026, « je veux pas le truc
    description ») : le bloc à copier suffit. Le texte y est alors montré
    jusqu'à 3500 signes (une légende Instagram en fait 2200 au plus) ; au-delà,
    coupé et marqué d'un « … ».
    """
    import discord
    import io
    children, files = [], []
    desc = str(description or '')
    if desc:
        plafond = 2700 if joindre_fichier else PLAFOND_A_COPIER
        contenu, coupe = contenu_a_copier('Description à copier', desc, plafond)
        suffix = '\nTexte complet dans le fichier ci-dessous.' if coupe and joindre_fichier else ''
        children.append(discord.ui.TextDisplay(contenu + suffix))
        if joindre_fichier:
            filename = shortcode + '_description.txt'
            files.append(discord.File(io.BytesIO(desc.encode('utf-8')), filename=filename))
            children.append(discord.ui.File('attachment://' + filename))
    else:
        children.append(discord.ui.TextDisplay('**Description**\nAucune description récupérée pour ce reel.'))
    children.append(discord.ui.ActionRow(discord.ui.Button(label='Voir le reel sur Instagram', url=url)))
    return children, files


def textes_recap(record, salon=None):
    """Pages sans plafond de reels ; une mention par personne sur l'ensemble du bilan.

    Salon anonyme (Va IG) : AUCUNE mention, le VA par son numéro
    (`va_libelle`), « VA » à défaut — jamais son nom."""
    s = _salon(salon)
    anonyme = bool(s.get('anonyme'))
    jour = datetime.strptime(record['jour'], '%Y-%m-%d').strftime('%d/%m/%Y')
    visibles = [(sc, it) for sc, it in record['reels'].items() if it['etat'] in ('envoye', 'doublon')]
    videos = sum(bool(it.get('fiche', {}).get('video_disponible')) for _, it in visibles if it['etat'] == 'envoye')
    descs = sum(bool(it.get('fiche', {}).get('description')) for _, it in visibles if it['etat'] == 'envoye')
    titre = f'## Bangers du {jour} · {s["libelle"]}'
    prefix = (titre + f'\n**{len(visibles)} reels repérés** · **{videos} vidéos disponibles** · **{descs} descriptions**\n'
              'Cliquez sur votre compte pour ouvrir sa fiche.\n\n')
    pages = []; texte = prefix; mentions = []; tagged = set()
    for sc, item in visibles:
        f = item['fiche']; uid = str(f.get('discord_id') or '')
        if anonyme:
            nouveau, who = False, str(f.get('va_libelle') or 'VA')
        else:
            nouveau = uid.isdigit() and uid not in tagged
            who = '<@' + uid + '>' if nouveau else str(f.get('va') or 'VA non renseigné')
        mid = item.get('message_id')
        if item['etat'] == 'doublon':
            mid = record['reels'][item['doublon_de']].get('message_id')
        url = f'https://discord.com/channels/{s["guild_id"]}/{s["channel_id"]}/{mid}'
        ligne = f"• {who} → [@{f['compte']}]({url})"
        if item['etat'] == 'doublon': ligne += ' · même vidéo'
        elif not f.get('video_disponible'): ligne += ' · vidéo indisponible'
        if len(texte) + len(ligne) + 1 > 3700:
            pages.append({'texte': texte.rstrip(), 'mentions': mentions})
            texte = titre + ' · suite\n\n'; mentions = []
        texte += ligne + '\n'
        if nouveau:
            tagged.add(uid); mentions.append(uid)
    hors = len(record.get('hors_discord') or [])
    if not visibles:
        # FR : des reels au-dessus du seuil ont pu être écartés (comptes sans VA
        # du Discord). Dire « aucun reel au-dessus du seuil » était faux, et la
        # journée figée ne les rendait plus jamais.
        texte = titre + ('\nAucun reel des comptes de VA du Discord au-dessus du seuil pour cette journée.'
                         if hors else
                         '\nAucun reel au-dessus du seuil repéré dans les données disponibles pour cette journée.')
    if any(it['etat'] == 'ignore' for it in record['reels'].values()):
        texte += '\n-# Certaines anciennes publications supprimées ont été conservées hors du récapitulatif.'
    if hors:
        texte += (f"\n-# {hors} reel{'s' if hors > 1 else ''} au-dessus du seuil "
                  f"écarté{'s' if hors > 1 else ''} : comptes reliés à aucun VA du Discord "
                  "(bouton « 📷 Mes comptes »).")
    pages.append({'texte': texte.rstrip(), 'mentions': mentions})
    return pages


def publier_journee(jour, preparer, publier, recapituler, *, maintenant=None, strict_veille=False,
                    salon=None, admis=None):
    """Journal durable, reprise sans double envoi, bilan seulement après les fiches.

    `salon` (salon_us() par défaut) : l'identité, le salon et le dossier du
    journal. Le seuil de la sélection est celui de l'identité (seuil_de :
    SEUIL_FR pour une model de Va IG). `admis` : pour un salon
    `discord_seulement` (plus aucun depuis le 06/10/2026), les comptes des VA
    du Discord (comptes_admis), relevés AVANT que la journée ne soit figée ;
    un reel d'un autre compte est écarté, compté et nommé dans le journal
    (`hors_discord`), jamais en silence."""
    s = _salon(salon)
    dossier = Path(s['dossier'])
    canal = int(s['channel_id'] or 0)
    clock = time.time() if maintenant is None else maintenant
    date = datetime.strptime(jour, '%Y-%m-%d').date()
    if date.isoformat() != jour or date >= datetime.fromtimestamp(clock, TZ).date():
        raise ValueError('Seules les journées terminées peuvent être publiées')
    bilan = {'jour': jour, 'annonces': 0, 'reeditions': 0, 'recaps': 0, 'doublons': 0}
    if strict_veille and jour != fenetre_veille(clock)[0]:
        return dict(bilan, attente='Journée hors sélection')
    verrou_fil = _verrou_du_dossier(dossier)
    if not verrou_fil.acquire(blocking=False):
        return dict(bilan, en_cours=True)
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        with (dossier / '.lock').open('a') as verrou:
            try:
                fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return dict(bilan, en_cours=True)
            record = _lire_journee(jour, dossier)
            if record and record.get('termine') and record.get('format') == FORMAT_DISCORD:
                return dict(bilan, termine=True, total=len(record['reels']))
            if record is None:
                record = {'schema': 1, 'jour': jour, 'seuil': seuil_de(s['identite']), 'reels': {},
                          'cree_le': clock}
                if s['cle'] != 'us':
                    record['salon'] = s['cle']
            if record.get('format') != FORMAT_DISCORD:
                if s['identite'] in MODELS_FR:
                    # Une journée FR ouverte avant le 06/10 mais pas encore figée
                    # porte l'ancien seuil (10 000) : la sélection prend SEUIL_FR.
                    record['seuil'] = SEUIL_FR
                if s.get('discord_seulement') and admis is None:
                    # Sans la liste, on ne sait pas quels comptes comptent : on
                    # ne fige rien plutôt que de tout prendre.
                    raise ValueError('Comptes des VA Discord inconnus : sélection différée')
                hors = []
                for f in selection_jour(toutes(), record['seuil'], jour, identite=s['identite']):
                    if s.get('discord_seulement') and _handle(f.get('compte')) not in admis:
                        hors.append({'shortcode': f['shortcode'], 'compte': _handle(f.get('compte')),
                                     'va': str(f.get('va') or '')})
                        continue
                    a = f.get('annonce') or {}
                    if a.get('message_id') and int(a.get('channel_id') or 0) != canal:
                        raise ValueError('Annonce existante hors Youl4b : vérification requise'
                                         if s['cle'] == 'us' else
                                         f"Annonce existante hors de #{s['nom']} : vérification requise")
                    item = record['reels'].setdefault(f['shortcode'], {})
                    if item.get('etat') not in ('envoi', 'a_verifier'):
                        item.update(etat='attente', message_id=item.get('message_id') or a.get('message_id'))
                    item.setdefault('fiche', dict(f, jour_bilan=jour))
                if s.get('discord_seulement'):
                    record.update(hors_discord=hors, comptes_discord=len(admis))
                    if hors:
                        log.info(f"[bangers] {s['libelle']} {jour} : {len(hors)} reel(s) écarté(s), "
                                 f"comptes sans VA du Discord FR : "
                                 + ', '.join('@' + h['compte'] for h in hors[:10])
                                 + (' …' if len(hors) > 10 else ''))
                record.update(format=FORMAT_DISCORD, selection_complete=True)
                _sauver_journee(record, dossier)
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
                    _sauver_journee(record, dossier)
                    raise
                _sauver_journee(record, dossier)
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
                    _sauver_journee(record, dossier); bilan['doublons'] += 1
                    continue
                uncertain = item['etat'] in ('envoi', 'a_verifier') and not item.get('message_id')
                edition = bool(item.get('message_id'))
                item.update(etat='edition' if edition else 'envoi', intention_le=item.get('intention_le') or time.time())
                _sauver_journee(record, dossier)
                result = publier(f, dict(item, verifier_seulement=uncertain))
                if result.get('supprime') and edition:
                    item['etat'] = 'ignore'
                elif result.get('message_id') and int(result.get('channel_id') or 0) == canal:
                    item.update(etat='envoye', message_id=int(result['message_id']))
                    _sauver_journee(record, dossier)
                    d = lire_details(sc)
                    d['annonce'] = {'message_id': int(result['message_id']), 'channel_id': canal,
                        'vues_affichees': f.get('vues_actuelles') or f.get('vues'),
                        'avec_video': bool(f.get('video_disponible')), 'le': int(time.time())}
                    sauver_details(sc, d)
                    if fp: fingerprints[fp] = sc
                    bilan['reeditions' if edition else 'annonces'] += 1
                else:
                    item['etat'] = 'a_verifier'
                    _sauver_journee(record, dossier)
                    return dict(bilan, a_verifier=sc)
                _sauver_journee(record, dossier)
            pages = record.setdefault('recaps', [])
            if not pages:
                pages.extend(dict(p, etat='attente') for p in textes_recap(record, s))
                _sauver_journee(record, dossier)
            for index, page in enumerate(pages):
                if page['etat'] == 'envoye': continue
                uncertain = page['etat'] in ('envoi', 'a_verifier')
                page.update(etat='envoi', intention_le=page.get('intention_le') or time.time())
                _sauver_journee(record, dossier)
                result = recapituler(jour, index, dict(page, verifier_seulement=uncertain))
                if not result.get('message_id') or int(result.get('channel_id') or 0) != canal:
                    page['etat'] = 'a_verifier'; _sauver_journee(record, dossier)
                    return dict(bilan, a_verifier='recap')
                page.update(etat='envoye', message_id=int(result['message_id']))
                _sauver_journee(record, dossier); bilan['recaps'] += 1
            record.update(termine=True, termine_le=time.time())
            _sauver_journee(record, dossier)
            return dict(bilan, termine=True, total=len(record['reels']))
    finally:
        verrou_fil.release()


def publier_salons(liste, publier_un, jour='') -> dict:
    """La publication du matin, salon par salon. Rend {cle du salon: bilan}.

    CHAQUE SALON DANS SON PROPRE TRY : un salon FR absent, sans droits ou en
    panne ne retient ni les autres models, ni Jessye. Une cause est dite UNE
    fois par salon (la boucle du matin repasse chaque minute) ; elle se redit
    après une reprise."""
    out = {}
    for s in liste:
        cle = s['cle']
        try:
            b = publier_un(s)
        except SalonAbsent as e:
            _dire_une_fois(f"{cle}|absent|{e}",
                           f"[bangers] {s['libelle']} ({s['serveur']}) : {e} — ce salon est passé, "
                           f"les autres continuent")
            out[cle] = {'jour': jour, 'annonces': 0, 'attente': str(e)}
            continue
        except Exception as e:                                # noqa: BLE001
            _dire_une_fois(f"{cle}|erreur|{jour}|{type(e).__name__}",
                           f"[bangers] {s['libelle']} ({s['serveur']}) : journée interrompue : "
                           f"{type(e).__name__}: {str(e)[:160]}", logging.ERROR)
            out[cle] = {'jour': jour, 'erreur': 'Envoi interrompu : vérifier le journal du jour'}
            continue
        out[cle] = b
        if cle != 'us' and 'désactivée' in str(b.get('attente') or ''):
            # Une model FR hors des identités scrapées n'a aucun banger : le dire.
            _dire_une_fois(f"{cle}|desactivee",
                           f"[bangers] {s['libelle']} ({s['serveur']}) : {b['attente']} "
                           f"(identités scrapées) — pas de publication du matin", logging.INFO)
        if cle != 'us' and b.get('a_verifier'):
            # Une issue incertaine reste « à vérifier » jusqu'à ce qu'on regarde :
            # la boucle repasse chaque minute, le dire une fois suffit.
            _dire_une_fois(f"{cle}|a_verifier|{jour}|{b['a_verifier']}",
                           f"[bangers] {s['libelle']} ({s['serveur']}) : envoi de "
                           f"{b['a_verifier']} à vérifier dans #{s['nom']} — la journée attend")
        if b.get('termine'):
            # La journée est faite : une rechute demain se dira de nouveau.
            for k in [k for k in _DITS if k.startswith(cle + '|')]:
                _DITS.discard(k)
        if cle != 'us' and any(b.get(k) for k in ('annonces', 'reeditions', 'recaps', 'doublons')):
            log.info(f"[bangers] {s['libelle']} ({s['serveur']}) : {b}")
    return out


def _nom_de_salon(nom) -> str:
    """Le nom d'un salon sans ce qu'on ajoute devant à la main (« 💥・ »)."""
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:                                         # noqa: BLE001
        return re.sub(r'^[^a-z0-9_-]+', '', str(nom or '').strip().lower())


def dans_archives(c) -> bool:
    """Un salon rangé dans une catégorie d'archives (« 🗄️ Archives … »)."""
    cat = getattr(c, 'category', None)
    return cat is not None and 'archives' in str(getattr(cat, 'name', '')).lower()


def salon_banger_de(guild, model, all_banger=False):
    """Le salon texte « 💥・banger-<model> » du serveur (ou, `all_banger`, son
    miroir « 💥・all-banger-<model> »), par son nom, hors archives, ou None.

    « all-banger-<model> » n'est pas le salon du matin : y poster les fiches
    mélangerait les deux fils."""
    m = str(model or '').strip().lower()
    cible = ('all-banger-' if all_banger else 'banger-') + m
    trouves = []
    for c in getattr(guild, 'text_channels', None) or []:
        if dans_archives(c):
            continue
        n = _nom_de_salon(getattr(c, 'name', ''))
        if not (n == cible or n.endswith('-' + cible)):
            continue
        if all_banger or not n.endswith('all-' + cible):
            trouves.append(c)
    if not trouves:
        return None
    trouves.sort(key=lambda c: (getattr(c, 'position', 0) or 0, getattr(c, 'id', 0) or 0))
    if len(trouves) > 1:
        _dire_une_fois(f"plusieurs|{cible}", f"[bangers] plusieurs salons « {cible} » : "
                       f"envoi dans #{trouves[0].name} ({trouves[0].id})")
    return trouves[0]


async def contexte_salon(client, salon=None):
    """(salon Discord, gérants {VA: id Discord}, salon résolu, pseudos des membres).

    Jessye : le salon fixe de Youl4b, comme avant. Une model FR : son salon
    cherché par le NOM sur le serveur FR, l'identifiant de SALONS_FR en
    secours ; absent ou sans les droits d'écrire, de joindre un fichier et de
    relire l'historique → SalonAbsent (cette model seule est passée). Les
    droits sont vérifiés AVANT toute intention d'envoi : un refus après
    l'intention laissait la fiche « à vérifier » pour toujours."""
    import jailbreak
    s = dict(_salon(salon))
    if s['cle'] == 'us':
        channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
        if channel.guild.id != GUILD_ID:
            raise ValueError('Salon hors Youl4b')
    else:
        guild = client.get_guild(int(s['guild_id']))
        if guild is None:
            raise SalonAbsent(f"serveur {s['serveur']} hors de portée du bot")
        channel = salon_banger_de(guild, s['identite'])
        if channel is None and s.get('channel_id') and hasattr(guild, 'get_channel'):
            channel = guild.get_channel(int(s['channel_id']))
            if channel is not None and dans_archives(channel):
                channel = None
        if channel is None:
            raise SalonAbsent(f"aucun salon « {s['nom']} » sur {s['serveur']}")
        if getattr(getattr(channel, 'guild', None), 'id', None) != int(s['guild_id']):
            raise ValueError(f"Salon hors du serveur {s['serveur']}")
        moi = getattr(guild, 'me', None)
        if moi is not None and hasattr(channel, 'permissions_for'):
            droits = channel.permissions_for(moi)
            manque = [n for n, a in (('voir le salon', 'view_channel'), ('écrire', 'send_messages'),
                                     ('joindre un fichier', 'attach_files'),
                                     ('voir les anciens messages', 'read_message_history'))
                      if not getattr(droits, a, True)]
            if manque:
                raise SalonAbsent(f"le bot n'a pas le droit de {', '.join(manque)} "
                                  f"dans #{channel.name}")
        s['channel_id'] = channel.id
    guild = channel.guild
    membres = guild.members if guild.chunked else [m async for m in guild.fetch_members(limit=None)]
    entree = jailbreak.list_all().get(s['identite']) or {}
    vas = entree.get('vas') or []
    pseudos = {m.name for m in membres if not getattr(m, 'bot', False)}
    # Va IG : les gérants servent au NUMÉRO du VA (anonymiser_fr), avec le
    # repli par le nom ; Jessye garde exactement sa règle.
    gerants = gerants_discord(vas, membres) if s['cle'] == 'us' else gerants_fr(entree, membres)
    return channel, gerants, s, pseudos


async def contexte_publication(client):
    """Le contexte du salon de Jessye : (salon Discord, gérants)."""
    channel, gerants, _s, _pseudos = await contexte_salon(client)
    return channel, gerants


def nonce_banger(jour, reference):
    import hashlib
    return hashlib.sha256((jour + ':' + reference).encode()).hexdigest()[:24]


def _prefixe_nonce(s) -> str:
    """Rien pour Jessye (nonces d'avant inchangés) ; la clé du salon sinon.

    discord.py envoie `enforce_nonce` : un même nonce revenu en quelques
    minutes rend le message DÉJÀ créé. Le récapitulatif de Jessye et celui
    d'une model FR, postés à la même minute avec « recap:0 », auraient
    partagé le leur — et la model n'aurait jamais eu le sien."""
    return '' if s['cle'] == 'us' else s['cle'] + ':'


async def _retrouver_nonce(channel, client, nonce, depuis):
    from datetime import timezone
    after = datetime.fromtimestamp(max(0, depuis - 10), timezone.utc)
    async for message in channel.history(limit=200, after=after):
        if message.author.id == client.user.id and str(message.nonce or '') == nonce:
            return message
    return None


async def publier_fiche_discord(client, channel, f, item, salon=None):
    import discord
    s = _salon(salon)
    assert channel.id == int(s['channel_id']) and channel.guild.id == int(s['guild_id'])
    nonce = nonce_banger(f['jour_bilan'], _prefixe_nonce(s) + f['shortcode'])
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
    view, files = fiche_discord(f, fichier, getattr(channel.guild, 'filesize_limit', 25 * 1024 * 1024),
                                libelle=s['libelle'], anonyme=bool(s.get('anonyme')))
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


async def publier_recap_discord(client, channel, jour, index, page, salon=None):
    import discord
    s = _salon(salon)
    assert channel.id == int(s['channel_id']) and channel.guild.id == int(s['guild_id'])
    nonce = nonce_banger(jour, _prefixe_nonce(s) + 'recap:' + str(index))
    if page.get('verifier_seulement'):
        found = await _retrouver_nonce(channel, client, nonce, page['intention_le'])
        return {'message_id': found.id, 'channel_id': channel.id} if found else {}
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(page['texte']), accent_colour=0x5865F2))
    if s.get('anonyme'):
        # Va IG : personne n'est mentionné, même par un vieux récapitulatif.
        mentions = discord.AllowedMentions.none()
    else:
        users = [discord.Object(id=int(uid)) for uid in page['mentions']]
        mentions = discord.AllowedMentions(everyone=False, users=users, roles=False, replied_user=False)
    message = await channel.send(view=view, nonce=nonce, allowed_mentions=mentions)
    verified = await channel.fetch_message(message.id)
    assert verified.components[0].to_dict()['components'][0]['content'] == page['texte']
    assert not verified.mention_everyone
    return {'message_id': verified.id, 'channel_id': channel.id}
