# -*- coding: utf-8 -*-
"""Les reels qui explosent : les repérer, les annoncer, et les garder.

LE BESOIN. Le scrape Instagram passe six fois par jour sur les comptes des VA
et lit, entre autres, le nombre de vues de chaque reel. Quand l'un d'eux
décolle — dix mille vues, cinquante mille — deux choses doivent arriver :

  1. on le DIT, tout de suite, dans le salon Discord ;
  2. on le GARDE : le lien, la vidéo téléchargée, la description.

Le second point est le vrai sujet. Un compte qui part en ban emporte le reel
ET sa légende ; on ne peut plus ni le revoir, ni le réutiliser, ni même savoir
ce qui avait marché. Copier le fichier le jour où il tape fort est la seule
fenêtre qui existe. L'annonce, elle, est un confort.

CE QUE CE MODULE FAIT, ET RIEN D'AUTRE : tenir le registre. Il ne télécharge
rien, ne parle pas à Discord et n'appelle aucune API — web_upload.py s'en
charge et vient lui dire ce qui s'est passé. Il est donc testable seul.

QUATRE DÉCISIONS QUI ONT L'AIR ARBITRAIRES ET NE LE SONT PAS
------------------------------------------------------------

**Les vues ne redescendent jamais.** On garde le maximum jamais lu. Un scrape
partiel rend régulièrement 0 vue pour un reel qui en a cinquante mille, et
l'API publique renvoie parfois `video_view_count` absent. Prendre la dernière
valeur ferait osciller le compteur et, pire, ferait retomber un banger sous le
seuil — il serait ré-annoncé au scrape suivant. Dans la vraie vie un compteur
de vues ne descend pas : on modélise ça.

**L'absence de la liste ne prouve RIEN.** L'endpoint public ne rend qu'une
douzaine de posts récents. Un reel de trois semaines en sort tout seul, sans
avoir été supprimé. On note donc `dernier_vu` et on s'arrête là : aucun verdict
de disparition n'est prononcé ici. C'est la même prudence que pour les comptes
« bannis » — une absence est une absence, pas un acte de décès.

**Au-delà de trente jours, on archive sans annoncer.** Le jour du déploiement,
le registre est vide et TOUS les vieux reels au-dessus du seuil ressemblent à
des nouveautés. Annoncer des mois de trafic d'un coup noierait le salon et le
rendrait inutilisable dès le premier jour. Le vieux contenu vaut quand même
d'être sauvegardé : il est enregistré, simplement en silence.

**L'archive ne vit pas dans data/insta/videos.** Ce dossier est purgé de tout
mp4 de plus d'un mois par `cleanup_old_videos()`. Y ranger les bangers
reviendrait à les effacer exactement quand ils deviennent irremplaçables.
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

#: Au-delà, on cesse de réessayer le téléchargement : le reel est supprimé,
#: privé, ou non servi en public. La fiche reste, avec son lien et ses vues.
ESSAIS_VIDEO_MAX = 6

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
            out.append(g)
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

def a_telecharger(limite: int = 20) -> List[dict]:
    """Les bangers dont la vidéo manque encore, les plus récents d'abord.

    On passe les fiches qui ont déjà épuisé leurs essais : un reel supprimé ne
    redeviendra pas téléchargeable, et réessayer six fois par jour pendant des
    mois brûlerait du quota pour rien.
    """
    out = []
    for f in toutes():
        sc = f["shortcode"]
        if video_presente(sc):
            continue
        if _entier(f.get("essais_video")) >= ESSAIS_VIDEO_MAX:
            continue
        out.append(f)
    out.sort(key=lambda f: -_entier(f.get("detecte_le")))
    return out[:max(0, int(limite or 0))]


def noter_telechargement(shortcode: str, reussi: bool,
                         description: str = "", raison: str = "") -> bool:
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
    f["essais_video"] = _entier(f.get("essais_video")) + 1
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

    Les fiches « muettes » (trop vieilles à la détection) n'en font pas partie.
    """
    out = [f for f in toutes()
           if not f.get("muet") and not (f.get("annonce") or {}).get("message_id")]
    return out[:max(0, int(limite or 0))]


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


def noter_annonce(shortcode: str, channel_id, message_id, vues: int = 0) -> bool:
    """Retient OÙ l'annonce a été postée, pour pouvoir l'éditer plus tard."""
    sc = str(shortcode or "")
    d = charger()
    f = (d.get("reels") or {}).get(sc)
    if not isinstance(f, dict):
        return False
    f["annonce"] = {
        "channel_id": int(channel_id or 0),
        "message_id": int(message_id or 0),
        "vues_affichees": _entier(vues) or _entier(f.get("vues")),
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
