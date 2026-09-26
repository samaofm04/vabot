# -*- coding: utf-8 -*-
"""hiker_medias.py — un compte Instagram lu par HikerAPI, pour le téléchargeur.

POURQUOI CE MODULE
    Le panneau « Téléchargement » des salons <va>-download lisait les profils
    par Apify, puis par une session Instagram (cookies + yt-dlp). Apify est
    écarté (le propriétaire n'en veut plus), la session met en jeu le compte
    de l'agence, et yt-dlp ne sait pas descendre une image : « Posts photo »
    échouait à tous les coups, la photo de profil aussi (elle exigeait une
    session). HikerAPI est la source Instagram retenue (hiker_reels.py) : une
    requête payante par page, les octets pris sur le CDN d'Instagram, gratuits.

CE QUI COÛTE, CE QUI NE COÛTE RIEN
    payant  /v1/user/by/username   la fiche : photo HD, bio, compteurs, privé
            /v2/user/medias        les publications, 1 requête par page
            /v2/user/clips         les reels, 1 requête par page
            /gql/user/clips        les reels triés par vues (« Top reels »)
            /v1/media/by/code      un lien CDN expiré, publication par publication
    gratuit les octets (CDN), tout fichier déjà sur le disque, et toute
            redemande d'un compte dans les 24 h (cache de listing).

JAMAIS PAYER DEUX FOIS
    - le listing d'un compte est gardé 24 h (data/telechargement/listes/) : la
      même demande le lendemain matin ne coûte rien ; une demande plus longue
      que la précédente reprend la pagination là où elle s'était arrêtée ;
    - les fichiers sont rangés par shortcode (data/telechargement/medias/,
      « <code>.mp4 », « <code>_<n>.jpg » pour la n-ième image d'un carrousel),
      et les caches du reste du bot passent avant (data/insta/videos,
      data/bangers, data/insta/pp) : un fichier présent n'est jamais
      retéléchargé ;
    - un lien CDN expire en quelques heures : si un fichier manque ET que son
      lien est mort, on relit CETTE publication seulement (1 requête).

RÉSERVE À PART
    Le suivi des comptes épuise chaque soir l'enveloppe commune de
    hiker_reels (PLAFOND_JOUR) et le vault a la sienne : le téléchargeur a donc
    SA réserve (data/telechargement_hiker.json, 300 requêtes par jour par
    défaut, ~0,25 $). Un VA qui la vide ne prive pas l'Analytique, et
    inversement ; quand elle est atteinte, le VA le lit en clair.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

# Chemins ABSOLUS, comme hiker_reels : un lancement depuis un autre dossier
# repartait sinon d'un compteur neuf et doublait la réserve sans rien dire.
_ICI = Path(__file__).resolve().parent
DATA_DIR = _ICI / "data"
DOSSIER = DATA_DIR / "telechargement"
LISTES = DOSSIER / "listes"
MEDIAS = DOSSIER / "medias"
JOURNAL_PURGE = DOSSIER / "purges.json"
BUDGET_FILE = DATA_DIR / "telechargement_hiker.json"

#: Réserve du jour, en requêtes. Réglable sans redéploiement : une clé
#: « plafond » dans data/telechargement_hiker.json l'emporte.
PLAFOND_JOUR = 300

#: Un listing sert 24 h. Au-delà, les vues ont bougé et des publications sont
#: arrivées : relire est la moindre des choses.
TTL_LISTE = 24 * 3600

#: Un fichier du cache que personne n'a redemandé depuis 30 jours part à la
#: purge. Sans ça, chaque profil descendu restait pour toujours sur le VPS.
PURGE_JOURS = 30

#: Une photo de profil de moins d'une semaine est « récente » : on la renvoie
#: sans rien relire. Une PP change rarement plus souvent.
PP_FRAICHE_SEC = 7 * 86400

#: Plafonds de pages par lecture (12 publications par page, mesuré par le
#: vault sur /v2/user/clips). Ils bornent le coût d'un compte énorme.
MAX_PAGES_POSTS = 25        # ~300 publications pour trouver N photos
MAX_PAGES_REELS = 20        # 200 reels récents au plus (N plafonné à 200)
MAX_PAGES_TOP = 50          # 600 reels, la même borne que le vault

#: En dessous, ce n'est pas un média : une page d'erreur ou un corps vide.
TAILLE_MINI = 512


# ─────────────────────────────────────────────────────────────── erreurs ──

class ErreurHiker(RuntimeError):
    """Une erreur à montrer TELLE QUELLE au VA."""


class ReserveEpuisee(ErreurHiker):
    """La réserve du jour du téléchargeur est vide."""


class SoldeEpuise(ErreurHiker):
    """HTTP 402 : le solde prépayé HikerAPI est à zéro."""


class ProfilIntrouvable(ErreurHiker):
    pass


class LienExpire(RuntimeError):
    """Le CDN a refusé le lien (403/404/410) : il faut relire la publication."""


class Compteur:
    """Ce qu'une demande a coûté et d'où viennent ses fichiers.

    Le bilan final le dit au VA (« 0 crédit » ou « N requêtes HikerAPI ») :
    sans lui, impossible de savoir si le cache a servi ou si l'on a payé.
    """

    def __init__(self):
        self.requetes = 0          # requêtes HikerAPI envoyées
        self.rafraichies = 0       # publications relues pour un lien expiré
        self.reutilises = 0        # fichiers déjà sur le disque
        self.telecharges = 0       # fichiers descendus du CDN (gratuit)
        self.echecs = 0


# ─────────────────────────────────────────────────────────────── réserve ──

_VERROU_BUDGET = threading.Lock()


def _jour() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def budget() -> dict:
    """{jour, utilise, plafond, restant} de la réserve du téléchargeur."""
    d = safe_json.load(BUDGET_FILE, default={})
    d = d if isinstance(d, dict) else {}
    try:
        plafond = int(d.get("plafond") or PLAFOND_JOUR)
    except (TypeError, ValueError):
        plafond = PLAFOND_JOUR
    jour = _jour()
    utilise = int(d.get("utilise") or 0) if d.get("jour") == jour else 0
    return {"jour": jour, "utilise": utilise, "plafond": plafond,
            "restant": max(0, plafond - utilise)}


def _consommer(n: int = 1) -> bool:
    """Réserve n requêtes AVANT l'appel ; faux si la réserve est vide.

    Fermé si le compteur ne s'écrit pas (disque plein, droits) : un garde-fou
    qui s'autorise tout seul quand ça va mal n'en est pas un — c'est la règle
    de hiker_reels._consommer et de vault_social._consommer_insta.
    """
    with _VERROU_BUDGET:
        e = budget()
        if e["restant"] < n:
            return False
        brut = safe_json.load(BUDGET_FILE, default={})
        neuf = {"jour": e["jour"], "utilise": e["utilise"] + n}
        if isinstance(brut, dict) and brut.get("plafond"):
            neuf["plafond"] = brut["plafond"]      # le réglage du propriétaire reste
        if not safe_json.write(BUDGET_FILE, neuf):
            print("[telechargement] compteur HikerAPI non écrit, appel refusé",
                  flush=True)
            return False
        return True


def _hk():
    import hiker_reels
    return hiker_reels


def _requete(compteur: Optional[Compteur], chemin: str, timeout: int = 60,
             **params) -> Tuple[Any, str]:
    """UN appel HikerAPI, compté sur la réserve du téléchargeur.

    Rend (données, "") ou (None, erreur). Lève ReserveEpuisee / SoldeEpuise :
    ces deux-là arrêtent la demande entière, rien ne sert d'insister.
    """
    hk = _hk()
    jeton = hk.get_token()
    if not jeton:
        raise ErreurHiker("jeton HikerAPI absent (à renseigner sur le site)")
    if not _consommer(1):
        b = budget()
        raise ReserveEpuisee(
            f"réserve HikerAPI du téléchargeur atteinte pour aujourd'hui "
            f"({b['utilise']}/{b['plafond']} requêtes) — réessaie demain")
    if compteur is not None:
        compteur.requetes += 1
    data, err = hk._appel(chemin, jeton, timeout, **params)
    if err:
        if err.startswith("HTTP 402"):
            raise SoldeEpuise("solde HikerAPI épuisé — il faut recharger le "
                              "compte HikerAPI (hikerapi.com)")
        return None, err
    return data, ""


# ──────────────────────────────────────────────────── lecture des formes ──

def _pseudo(p: str) -> str:
    return (p or "").strip().lstrip("@").lower()


def _meilleure_image(m: dict) -> str:
    """L'URL de la plus grande image, quelle que soit la forme rendue.

    Trois formes coexistent : celle d'Instagram (image_versions2.candidates),
    celle des modèles HikerAPI v1 (image_versions / thumbnail_url) et celle du
    GraphQL (display_url). On lit les trois plutôt que de parier sur l'une.
    """
    if not isinstance(m, dict):
        return ""
    cands = None
    iv2 = m.get("image_versions2")
    if isinstance(iv2, dict):
        cands = iv2.get("candidates")
    if not cands and isinstance(m.get("image_versions"), list):
        cands = m.get("image_versions")
    if isinstance(cands, list):
        bons = [c for c in cands if isinstance(c, dict) and c.get("url")]
        if bons:
            meilleure = max(bons, key=lambda c: (int(c.get("width") or 0)
                                                 * int(c.get("height") or 0)))
            return str(meilleure["url"])
    for cle in ("display_url", "thumbnail_url", "thumbnail_src"):
        if m.get(cle):
            return str(m[cle])
    return ""


def _est_video(m: dict) -> bool:
    if m.get("media_type") == 2 or m.get("is_video") is True:
        return True
    if m.get("media_type") in (1, 8):
        return False
    return bool(_hk()._url_video(m))


def _vues(m: dict):
    for cle in ("play_count", "ig_play_count", "view_count",
                "video_play_count", "video_view_count"):
        v = m.get(cle)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _legende(m: dict) -> str:
    leg = _hk()._legende(m)
    if not leg:
        # Forme GraphQL : edge_media_to_caption.edges[0].node.text
        try:
            leg = m["edge_media_to_caption"]["edges"][0]["node"]["text"] or ""
        except (KeyError, IndexError, TypeError):
            leg = ""
    return str(leg or "").strip()


def _enfants(m: dict) -> list:
    for cle in ("carousel_media", "resources"):
        v = m.get(cle)
        if isinstance(v, list) and v:
            return [x for x in v if isinstance(x, dict)]
    try:
        aretes = m["edge_sidecar_to_children"]["edges"]
        return [a.get("node") for a in aretes if isinstance(a, dict)
                and isinstance(a.get("node"), dict)]
    except (KeyError, TypeError):
        return []


def normaliser(m: dict) -> Optional[dict]:
    """Une publication, dans la forme du téléchargeur. None si illisible.

    {code, genre: photo|video|carrousel, date, legende, vues, likes,
     elements: [{type: photo|video, url}]} — un carrousel porte TOUTES ses
    images et vidéos, dans l'ordre (c'était perdu avec yt-dlp).
    """
    if not isinstance(m, dict):
        return None
    if isinstance(m.get("media"), dict):
        m = m["media"]
    code = str(m.get("code") or m.get("shortcode") or "").strip()
    if not code:
        return None
    hk = _hk()
    enfants = _enfants(m)
    elements = []
    if enfants:
        genre = "carrousel"
        for e in enfants:
            if _est_video(e):
                elements.append({"type": "video", "url": hk._url_video(e)})
            else:
                elements.append({"type": "photo", "url": _meilleure_image(e)})
    elif _est_video(m):
        genre = "video"
        elements.append({"type": "video", "url": hk._url_video(m)})
    else:
        genre = "photo"
        elements.append({"type": "photo", "url": _meilleure_image(m)})
    return {
        "code": code,
        "genre": genre,
        "date": hk._horodatage(m.get("taken_at_ts") or m.get("taken_at")
                               or m.get("taken_at_timestamp")),
        "legende": _legende(m),
        "vues": _vues(m),
        "likes": int(m.get("like_count") or 0),
        "elements": elements,
    }


def _deballer(x):
    if isinstance(x, dict) and isinstance(x.get("node"), dict):
        x = x["node"]
    if isinstance(x, dict) and isinstance(x.get("media"), dict):
        x = x["media"]
    return x


def _ressemble_media(m) -> bool:
    return (isinstance(m, dict) and bool(m.get("code") or m.get("shortcode"))
            and any(k in m for k in ("pk", "id", "media_type", "__typename")))


def _medias_dans(obj, profondeur: int = 0) -> list:
    """La liste de publications d'une réponse de forme mal connue (GraphQL).

    La doc HikerAPI ne décrit pas le corps de /gql/user/clips (schéma vide) :
    on cherche la première liste d'objets qui ressemblent à des publications,
    à plat ou sous edges/node/media.
    """
    if profondeur > 6:
        return []
    if isinstance(obj, list):
        trouves = [_deballer(x) for x in obj]
        trouves = [x for x in trouves if _ressemble_media(x)]
        if trouves:
            return trouves
        for x in obj:
            r = _medias_dans(x, profondeur + 1)
            if r:
                return r
        return []
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r = _medias_dans(v, profondeur + 1)
                if r:
                    return r
    return []


def _curseur(obj, profondeur: int = 0) -> str:
    """Le curseur de la page suivante, "" s'il n'y en a plus."""
    if profondeur > 5:
        return ""
    if isinstance(obj, list):
        # Forme « chunk » : [publications, curseur]
        if len(obj) == 2 and isinstance(obj[1], str):
            return obj[1]
        return ""
    if not isinstance(obj, dict):
        return ""
    if obj.get("more_available") is False or obj.get("has_next_page") is False:
        return ""
    for cle in ("next_page_id", "next_max_id", "max_id", "end_cursor"):
        v = obj.get(cle)
        if isinstance(v, (str, int)) and str(v):
            return str(v)
    for v in obj.values():
        if isinstance(v, dict):
            r = _curseur(v, profondeur + 1)
            if r:
                return r
    return ""


def _page_v2(data) -> Tuple[list, str]:
    """Une page de /v2/user/medias ou /v2/user/clips : (objets, suivant).

    PageResponse : {"response": <réponse brute d'Instagram>, "next_page_id"}.
    Les reels arrivent emballés ({"media": {...}}), les publications à plat.
    """
    data = data if isinstance(data, dict) else {}
    rep = data.get("response")
    items = rep.get("items") if isinstance(rep, dict) else None
    if not isinstance(items, list):
        items = data.get("items") if isinstance(data.get("items"), list) else []
    return items, str(data.get("next_page_id") or "")


# ──────────────────────────────────────────────────────── cache de listing ──

_VERROU_LISTES = threading.RLock()


def _chemin_liste(pseudo: str) -> Path:
    # « .cache.json » : safe_json ne double pas un cache d'une copie .prev.
    return LISTES / f"{_pseudo(pseudo)}.cache.json"


def _charger(pseudo: str) -> dict:
    """Le listing gardé du compte, sans les sections de plus de 24 h."""
    d = safe_json.load(_chemin_liste(pseudo), default={})
    d = d if isinstance(d, dict) else {}
    maintenant = time.time()
    for cle in list(d):
        sec = d.get(cle)
        if (not isinstance(sec, dict)
                or maintenant - float(sec.get("lu_a") or 0) > TTL_LISTE):
            d.pop(cle, None)
    return d


def _ranger(pseudo: str, d: dict) -> None:
    with _VERROU_LISTES:
        safe_json.write(_chemin_liste(pseudo), d, indent=None)


def profil_en_cache(pseudo: str) -> Optional[dict]:
    """La fiche gardée (moins de 24 h), sans rien payer. None sinon."""
    return _charger(pseudo).get("profil")


def pk_connu(pseudo: str) -> str:
    """L'identifiant numérique du compte s'il est déjà connu, gratuitement.

    hiker_reels le retient pour le suivi des comptes : un compte suivi n'a
    donc jamais besoin de la requête « fiche » pour être listé.
    """
    fiche = profil_en_cache(pseudo)
    if fiche and fiche.get("pk"):
        return str(fiche["pk"])
    try:
        return str(_hk()._pk_cache().get(_pseudo(pseudo)) or "")
    except Exception:
        return ""


def profil(pseudo: str, compteur: Optional[Compteur] = None,
           forcer: bool = False) -> dict:
    """La fiche du compte : pk, nom, bio, photo HD, compteurs, privé.

    Gardée 24 h. forcer=True la relit (un lien de photo expiré).
    """
    pseudo = _pseudo(pseudo)
    cache = _charger(pseudo)
    if cache.get("profil") and not forcer:
        return cache["profil"]
    data, err = _requete(compteur, "/v1/user/by/username", 45, username=pseudo)
    if err:
        if "404" in err or "not found" in err.lower():
            raise ProfilIntrouvable(f"compte @{pseudo} introuvable sur Instagram")
        raise ErreurHiker("HikerAPI : " + err)
    data = data if isinstance(data, dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    pk = user.get("pk") or user.get("id")
    if not pk:
        raise ProfilIntrouvable(f"compte @{pseudo} introuvable (aucun identifiant)")
    try:
        _hk()._pk_retenir(pseudo, pk)
    except Exception:
        pass
    fiche = {
        "pseudo": user.get("username") or pseudo,
        "pk": str(pk),
        "nom": (user.get("full_name") or "").strip(),
        "bio": (user.get("biography") or "").strip(),
        "pp": (user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""),
        "posts": int(user.get("media_count") or 0),
        "abonnes": int(user.get("follower_count") or 0),
        "prive": bool(user.get("is_private")),
        "lu_a": time.time(),
    }
    cache = _charger(pseudo)
    cache["profil"] = fiche
    _ranger(pseudo, cache)
    return fiche


def _pk(pseudo: str, compteur: Optional[Compteur]) -> str:
    pk = pk_connu(pseudo)
    if pk:
        return pk
    return profil(pseudo, compteur)["pk"]


def _lire(pseudo: str, section: str, chemin: str, suffisant, max_pages: int,
          compteur: Optional[Compteur]) -> Tuple[list, str]:
    """Pagine une liste jusqu'à ce que `suffisant(items)` soit vrai.

    Reprend là où la lecture précédente (moins de 24 h) s'était arrêtée : une
    demande de 60 après une demande de 30 ne paie que les pages en plus.
    Chaque page est rangée dès qu'elle est lue — un redémarrage en pleine
    lecture ne fait pas repayer ce qui l'a déjà été.
    Rend (publications, note) ; la note dit tout arrêt anticipé.
    """
    pseudo = _pseudo(pseudo)
    cache = _charger(pseudo)
    sec = cache.get(section) or {"lu_a": time.time(), "items": [],
                                 "suivant": "", "fin": False, "pages": 0,
                                 "illisibles": 0}
    note = ""
    pk = ""
    while (not suffisant(sec["items"]) and not sec.get("fin")
           and int(sec.get("pages") or 0) < max_pages):
        if not pk:
            pk = _pk(pseudo, compteur)
        params = {"user_id": pk}
        if sec.get("suivant"):
            params["page_id"] = sec["suivant"]
        try:
            data, err = _requete(compteur, chemin, 60, **params)
        except ErreurHiker as e:
            if not sec["items"]:
                raise
            note = f"lecture arrêtée après {len(sec['items'])} publication(s) : {e}"
            break
        if err:
            vide = ("404" in err and "not found" in err.lower()
                    and not sec["items"])
            if vide:
                # Un compte sans publication (ou sans reel) n'est pas une
                # panne : /v2/user/clips rend 404 « Entries not found ».
                sec["fin"] = True
                break
            if not sec["items"]:
                raise ErreurHiker("HikerAPI : " + err)
            note = f"lecture arrêtée après {len(sec['items'])} publication(s) : {err[:120]}"
            break
        objets, suivant = _page_v2(data)
        vus = {p["code"] for p in sec["items"]}
        for o in objets:
            p = normaliser(o)
            if p is None:
                # Compté, jamais tu : le bilan dit combien d'objets n'ont pas
                # pu être lus plutôt que de laisser croire à un profil court.
                sec["illisibles"] = int(sec.get("illisibles") or 0) + 1
                continue
            if p["code"] not in vus:
                vus.add(p["code"])
                sec["items"].append(p)
        sec["pages"] = int(sec.get("pages") or 0) + 1
        sec["suivant"] = suivant
        if not suivant or not objets:
            sec["fin"] = True
        # Relu avant d'écrire : _pk() a pu ranger la fiche entre-temps, et
        # réécrire la copie du début l'effaçait (une requête payée pour rien).
        cache = _charger(pseudo)
        cache[section] = sec
        _ranger(pseudo, cache)
    if (not note and not sec.get("fin") and not suffisant(sec["items"])
            and int(sec.get("pages") or 0) >= max_pages):
        note = (f"lecture plafonnée à {max_pages} pages "
                f"({len(sec['items'])} publications examinées)")
    if sec.get("illisibles"):
        note = (note + " ; " if note else "") + (
            f"{sec['illisibles']} objet(s) de la liste illisible(s), ignoré(s)")
    return sec["items"], note


def publications(pseudo: str, combien: int, compteur: Optional[Compteur] = None,
                 photos_seulement: bool = False) -> Tuple[list, str]:
    """Les `combien` publications les plus récentes (/v2/user/medias).

    photos_seulement : les `combien` dernières publications PHOTO (photo
    seule ou carrousel), quitte à lire plus de pages. Sans ce filtre, UNE
    seule lecture sert photos ET vidéos (le bouton « Tout »).
    """
    def garde(p):
        return (p.get("genre") != "video") if photos_seulement else True

    items, note = _lire(pseudo, "posts", "/v2/user/medias",
                        lambda it: sum(1 for p in it if garde(p)) >= combien,
                        MAX_PAGES_POSTS, compteur)
    return [p for p in items if garde(p)][:combien], note


def reels(pseudo: str, combien: int, compteur: Optional[Compteur] = None
          ) -> Tuple[list, str]:
    """Les `combien` reels les plus récents (/v2/user/clips)."""
    items, note = _lire(pseudo, "reels", "/v2/user/clips",
                        lambda it: len(it) >= combien, MAX_PAGES_REELS, compteur)
    return items[:combien], note


#: Passe à True si /gql/user/clips a rendu une page qui n'était PAS triée par
#: vues : payer la sonde à chaque « Top reels » pour le même refus n'aurait pas
#: de sens. Remis à zéro au redémarrage.
_GQL_TRI_KO = False


def _par_vues(items: list) -> list:
    return sorted(items, key=lambda p: (p.get("vues") or 0), reverse=True)


def top_reels(pseudo: str, combien: int, compteur: Optional[Compteur] = None
              ) -> Tuple[list, str, str]:
    """Les `combien` reels les PLUS VUS de tout le profil.

    Avant, le tri se faisait parmi les 30 dernières publications : un reel à
    2 millions posté il y a six mois n'apparaissait jamais. Trois voies, de la
    moins chère à la plus chère :
      1. une liste de reels COMPLÈTE déjà lue (24 h) : on la trie, 0 requête ;
      2. /gql/user/clips?sort_by_views=true (paramètre documenté) : Instagram
         trie lui-même, une page suffit souvent ;
      3. sinon la liste entière par /v2/user/clips (plafonnée à 600 reels),
         triée ici par vues.
    Rend (reels, note, source).
    """
    global _GQL_TRI_KO
    pseudo = _pseudo(pseudo)
    cache = _charger(pseudo)
    r = cache.get("reels")
    if isinstance(r, dict) and r.get("fin"):
        return _par_vues(r["items"])[:combien], "", "liste complète déjà lue"
    t = cache.get("top")
    if isinstance(t, dict) and (len(t.get("items") or []) >= combien or t.get("fin")):
        return t["items"][:combien], "", t.get("source") or "cache"

    if not _GQL_TRI_KO:
        sec = t if isinstance(t, dict) else {"lu_a": time.time(), "items": [],
                                             "suivant": "", "fin": False,
                                             "pages": 0, "source": "tri Instagram"}
        pk = _pk(pseudo, compteur)
        trie, panne = True, ""
        while (len(sec["items"]) < combien and not sec.get("fin")
               and int(sec.get("pages") or 0) < MAX_PAGES_TOP):
            params = {"user_id": pk, "sort_by_views": "true"}
            if sec.get("suivant"):
                params["max_id"] = sec["suivant"]
            data, err = _requete(compteur, "/gql/user/clips", 60, **params)
            if err:
                # Une panne passagère n'est pas un refus du tri : on se replie
                # pour CETTE demande, sans condamner la voie pour les suivantes.
                trie, panne = False, err
                break
            objets = _medias_dans(data)
            page = [p for p in (normaliser(o) for o in objets) if p]
            vues = [p.get("vues") for p in page]
            # Le tri doit se VOIR : des vues connues, décroissantes, et qui
            # prolongent la page d'avant. Sinon HikerAPI a ignoré le paramètre
            # (ou la forme a changé) et « Top reels » mentirait.
            precedent = sec["items"][-1].get("vues") if sec["items"] else None
            if not page and not sec["items"]:
                # Rien de lisible dès la première page : compte sans reel, ou
                # forme inconnue. La liste /v2 tranchera (1 requête si vide),
                # sans condamner le tri pour les autres comptes.
                trie, panne = False, "première page vide"
                break
            if (not page or any(v is None for v in vues)
                    or any(vues[i] < vues[i + 1] for i in range(len(vues) - 1))
                    or (precedent is not None and vues and vues[0] > precedent)):
                trie = False
                break
            deja = {p["code"] for p in sec["items"]}
            sec["items"] += [p for p in page if p["code"] not in deja]
            sec["pages"] = int(sec.get("pages") or 0) + 1
            sec["suivant"] = _curseur(data)
            if not sec["suivant"]:
                sec["fin"] = True
            cache = _charger(pseudo)
            cache["top"] = sec
            _ranger(pseudo, cache)
        if trie and sec["items"]:
            return sec["items"][:combien], "", "tri Instagram (sort_by_views)"
        if not panne:
            _GQL_TRI_KO = True
        print(f"[telechargement] /gql/user/clips sans tri par vues exploitable "
              f"pour @{pseudo} ({panne[:120] or 'page non triée'}) : repli sur "
              f"la liste complète", flush=True)
        repli = "tri d'Instagram indisponible, liste complète triée ici"
    else:
        repli = ""

    items, note = _lire(pseudo, "reels", "/v2/user/clips", lambda it: False,
                        MAX_PAGES_TOP, compteur)
    note = "; ".join(x for x in (repli, note) if x)
    return _par_vues(items)[:combien], note, "liste complète triée par vues"


# ────────────────────────────────────────────────────────────── fichiers ──

def permalien(code: str) -> str:
    return f"https://www.instagram.com/p/{code}/"


def nom_fichier(code: str, i: int, total: int, type_: str) -> str:
    ext = "mp4" if type_ == "video" else "jpg"
    return f"{code}.{ext}" if total <= 1 else f"{code}_{i}.{ext}"


def _valide(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size >= TAILLE_MINI
    except OSError:
        return False


def _toucher(p: Path) -> None:
    """Remet à maintenant la date d'un fichier du cache qu'on vient de servir :
    c'est elle que la purge regarde (« non redemandé depuis 30 jours »)."""
    try:
        if MEDIAS in p.parents:
            os.utime(p, None)
    except OSError:
        pass


def fichier_existant(code: str, i: int, total: int, type_: str) -> Optional[Path]:
    """Le fichier s'il est déjà quelque part sur le disque, sinon None.

    Le cache du téléchargeur d'abord, puis ceux du reste du bot : la veille
    garde les reels dans data/insta/videos, l'archive des bangers dans
    data/bangers. Même shortcode, même vidéo : inutile de la redescendre.
    """
    propre = MEDIAS / nom_fichier(code, i, total, type_)
    if _valide(propre):
        return propre
    if type_ == "video" and total <= 1:
        for autre in (DATA_DIR / "insta" / "videos" / f"{code}.mp4",
                      DATA_DIR / "bangers" / f"{code}.mp4"):
            if _valide(autre):
                return autre
    return None


def lien_expire(url: str, marge: int = 120) -> bool:
    """Vrai si le lien CDN porte une échéance (oe=, en hexadécimal) passée."""
    m = re.search(r"[?&]oe=([0-9A-Fa-f]{6,})", url or "")
    if not m:
        return False
    try:
        return int(m.group(1), 16) < time.time() + marge
    except ValueError:
        return False


def _telecharger_cdn(url: str, dest: Path) -> Path:
    """GET sur le CDN d'Instagram, écrit atomiquement (.part puis rename).

    Même principe que vault_social._telecharger_direct, mais qui sait aussi
    les images et distingue un lien EXPIRÉ (à relire) d'une vraie panne.
    """
    if not url:
        raise LienExpire("aucun lien rendu par HikerAPI")
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=60, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
            "Referer": "https://www.instagram.com/"}) as r:
        if r.status_code in (403, 404, 410):
            raise LienExpire(f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        with open(part, "wb") as f:
            for bloc in r.iter_content(1 << 16):
                f.write(bloc)
    if part.stat().st_size < TAILLE_MINI:
        part.unlink()
        raise RuntimeError("fichier vide reçu")
    os.replace(part, dest)
    return dest


def _rafraichir(pseudo: str, code: str, compteur: Optional[Compteur]) -> Optional[dict]:
    """Relit UNE publication (/v1/media/by/code) pour des liens neufs.

    C'est « relister seulement ce qui manque » : une requête pour cette
    publication, pas la relecture du profil. Le listing gardé est mis à jour
    pour que la demande suivante profite des liens neufs.
    """
    data, err = _requete(compteur, "/v1/media/by/code", 45, code=code)
    if err:
        return None
    data = data if isinstance(data, dict) else {}
    media = data.get("media") if isinstance(data.get("media"), dict) else data
    neuf = normaliser(media)
    if neuf is None:
        return None
    if compteur is not None:
        compteur.rafraichies += 1
    if pseudo:
        cache = _charger(pseudo)
        change = False
        for sec in cache.values():
            if not isinstance(sec, dict) or not isinstance(sec.get("items"), list):
                continue
            for j, p in enumerate(sec["items"]):
                if isinstance(p, dict) and p.get("code") == code:
                    ancien = sec["items"][j]
                    neuf_garde = dict(neuf)
                    # Les vues du listing d'origine restent : c'est sur elles
                    # que « Top reels » a trié.
                    if ancien.get("vues") is not None:
                        neuf_garde["vues"] = ancien["vues"]
                    sec["items"][j] = neuf_garde
                    change = True
        if change:
            _ranger(pseudo, cache)
    return neuf


def preparer_post(post: dict, compteur: Optional[Compteur] = None,
                  pseudo: str = "") -> List[dict]:
    """Les fichiers d'une publication, sur le disque. Un dict par élément :
    {i, type, chemin (Path|None), reutilise (bool), erreur (str)}.

    Ne lève pas : un élément qui échoue est rendu avec son erreur, pour que la
    publication parte avec ce qui a marché et le dise.
    """
    elements = post.get("elements") or []
    total = len(elements)
    code = post.get("code") or ""
    res, a_relire = [], []
    for i, el in enumerate(elements, start=1):
        r = {"i": i, "type": el.get("type") or "photo", "chemin": None,
             "reutilise": False, "erreur": ""}
        res.append(r)
        deja = fichier_existant(code, i, total, r["type"])
        if deja is not None:
            _toucher(deja)
            r["chemin"], r["reutilise"] = deja, True
            if compteur is not None:
                compteur.reutilises += 1
            continue
        url = el.get("url") or ""
        if not url or lien_expire(url):
            a_relire.append(r)
            continue
        try:
            r["chemin"] = _telecharger_cdn(url, MEDIAS / nom_fichier(code, i, total, r["type"]))
            if compteur is not None:
                compteur.telecharges += 1
        except LienExpire:
            a_relire.append(r)
        except Exception as e:
            r["erreur"] = str(e)[:160]
    if a_relire and code:
        try:
            neuf = _rafraichir(pseudo, code, compteur)
        except ErreurHiker as e:
            neuf, raison = None, str(e)
        else:
            raison = "relecture de la publication impossible"
        neufs = (neuf or {}).get("elements") or []
        for r in a_relire:
            if len(neufs) != total or not neufs[r["i"] - 1].get("url"):
                r["erreur"] = f"lien expiré ; {raison}"
                continue
            if lien_expire(neufs[r["i"] - 1]["url"]):
                r["erreur"] = "lien expiré, et la relecture rend un lien déjà expiré"
                continue
            try:
                r["chemin"] = _telecharger_cdn(
                    neufs[r["i"] - 1]["url"],
                    MEDIAS / nom_fichier(code, r["i"], total, r["type"]))
                if compteur is not None:
                    compteur.telecharges += 1
            except Exception as e:
                r["erreur"] = f"lien expiré, relu mais refusé : {str(e)[:120]}"
    if compteur is not None:
        compteur.echecs += sum(1 for r in res if r["chemin"] is None)
    return res


def pp_locale(pseudo: str) -> Optional[Path]:
    """Une photo de profil RÉCENTE déjà sur le disque (moins d'une semaine)."""
    pseudo = _pseudo(pseudo)
    for p in (MEDIAS / f"pp_{pseudo}.jpg", DATA_DIR / "insta" / "pp" / f"{pseudo}.jpg"):
        try:
            if _valide(p) and time.time() - p.stat().st_mtime < PP_FRAICHE_SEC:
                return p
        except OSError:
            continue
    return None


def photo_de_profil(pseudo: str, fiche: Optional[dict],
                    compteur: Optional[Compteur] = None) -> Tuple[Optional[Path], str]:
    """La photo de profil HD, SANS session Instagram. (chemin, raison).

    L'ancienne voie exigeait des cookies : sans eux, « Photo de profil
    indisponible » à chaque clic. Le lien HD de la fiche HikerAPI se télécharge
    comme n'importe quel fichier du CDN.
    """
    pseudo = _pseudo(pseudo)
    deja = pp_locale(pseudo)
    if deja is not None:
        # Le cache du téléchargeur : on rafraîchit sa date pour la purge. Celui
        # de la veille (data/insta/pp) n'est pas à nous, on n'y touche pas.
        _toucher(deja)
        if compteur is not None:
            compteur.reutilises += 1
        return deja, ""
    dest = MEDIAS / f"pp_{pseudo}.jpg"
    for essai in (0, 1):
        url = (fiche or {}).get("pp") or ""
        if url and not lien_expire(url):
            try:
                _telecharger_cdn(url, dest)
                if compteur is not None:
                    compteur.telecharges += 1
                return dest, ""
            except LienExpire:
                pass
            except Exception as e:
                return None, str(e)[:160]
        if essai == 0:
            # Une fiche lue à l'instant sans lien : la relire ne donnerait rien
            # de plus, et coûterait une requête.
            if url == "" and fiche and time.time() - float(fiche.get("lu_a") or 0) < 600:
                break
            # Lien mort (fiche gardée depuis des heures) : UNE relecture.
            fiche = profil(pseudo, compteur, forcer=True)
    return None, "aucune photo de profil lisible"


# ──────────────────────────────────────────────────────────────── purge ──

def purger(jours: int = PURGE_JOURS, maintenant: Optional[float] = None) -> dict:
    """Retire du cache les médias non redemandés depuis `jours` jours.

    Seul le dossier du téléchargeur est concerné — jamais data/insta ni
    data/bangers, qui ne sont pas à lui. Les fichiers restent de toute façon
    dans le salon « all-download », qui sert d'archive au propriétaire.
    Journalisé (data/telechargement/purges.json + le journal du bot).
    """
    maintenant = time.time() if maintenant is None else maintenant
    limite = maintenant - jours * 86400
    n, octets, rates = 0, 0, 0
    if MEDIAS.is_dir():
        for f in MEDIAS.iterdir():
            try:
                if not f.is_file():
                    continue
                st = f.stat()
                # Un .part vieux d'un jour est le reste d'une coupure.
                vieux = (st.st_mtime < limite
                         or (f.name.endswith(".part") and st.st_mtime < maintenant - 86400))
                if vieux:
                    f.unlink()
                    n += 1
                    octets += st.st_size
            except OSError:
                rates += 1
    listes = 0
    if LISTES.is_dir():
        for f in LISTES.glob("*.cache.json*"):
            try:
                if f.stat().st_mtime < maintenant - 2 * TTL_LISTE:
                    f.unlink()
                    listes += 1
            except OSError:
                rates += 1
    bilan = {"quand": int(maintenant), "fichiers": n, "octets": octets,
             "listes": listes, "rates": rates, "jours": jours}
    if n or listes or rates:
        print(f"[telechargement] purge : {n} fichier(s) ({octets / 1048576:.1f} Mo) "
              f"non redemandé(s) depuis {jours} j, {listes} liste(s) périmée(s)"
              + (f", {rates} impossible(s) à retirer" if rates else ""), flush=True)
        journal = safe_json.load(JOURNAL_PURGE, default=[])
        journal = journal if isinstance(journal, list) else []
        journal = (journal + [bilan])[-200:]
        safe_json.write(JOURNAL_PURGE, journal, indent=None)
    return bilan
