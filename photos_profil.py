"""photos_profil.py — trouver des photos de profil (dessins, anime, cartoon)
et apprendre, à force de OK / Non, ce que le propriétaire veut.

Page /pfp du dashboard, réservée à l'administration. On décrit l'image
cherchée, la page montre une grille ; chaque OK télécharge l'original dans
data/pfp/<style>/garde/, chaque Non l'écarte pour de bon. Les deux nourrissent
le classement des recherches suivantes.

Sources — mesurées le 05/10/2026 DEPUIS LE VPS, pas depuis le Mac :
- Pinterest direct : mur « Connectez-vous » dès la recherche, aucune image
  sans compte. Pas de source directe, donc.
- Yandex Images : 30 images par page, 6 pages distinctes, très majoritairement
  des épingles Pinterest (i.pinimg.com). La recherche PAR IMAGE (envoi du
  fichier) rend 40 images voisines : c'est elle qui fait « Pour toi ».
- Bing Images : 35 images, mais depuis le VPS la page 2 rend les MÊMES 35
  (depuis le Mac, elle avançait). Sans le cookie ADLT=MODERATE, certaines
  requêtes (« anime girl pink hair pfp ») tombaient à 12 images hors sujet.
  Bing ne sert donc qu'en complément, sur la première page.
- DuckDuckGo : 403 depuis le VPS.

Apprentissage : CLIP ViT-B/32 (partie image), en ONNX, sur la machine. Rien
de payant, rien d'envoyé à une API. Chaque image devient un vecteur ; une
image candidate est classée selon sa ressemblance aux OK moins sa
ressemblance aux Non (moyenne des 3 plus proches de chaque côté). Le modèle
(352 Mo, empreinte vérifiée) se télécharge au premier usage et se décharge
après 15 min sans servir : le processus est aussi celui du bot.

Rien n'est écarté en silence : les images qui ressemblent aux Non, les
doublons d'images déjà jugées et les pannes de source sont comptés et
renvoyés à la page.
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
RACINE = DATA_DIR / "pfp"
STYLES_FILE = RACINE / "styles.json"
MODELE_FILE = RACINE / "modele" / "clip-vit-b32-vision.onnx"

# Révision figée : un modèle remplacé sur Hugging Face ne doit pas changer
# les vecteurs déjà enregistrés (ils ne seraient plus comparables).
MODELE_URL = ("https://huggingface.co/Qdrant/clip-ViT-B-32-vision/resolve/"
              "e0c24ed0fa57fa3e4f97f30de74c51d944036ace/model.onnx")
MODELE_SHA256 = "c68d3d9a200ddd2a8c8a5510b576d4c94d1ae383bf8b36dd8c084f94e1fb4d63"
MODELE_TAILLE = 351686194

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129 Safari/537.36")

# Deux images à plus de 0,95 de cosinus sont la même image (recadrée,
# recompressée, autre taille) : Pinterest republie la même épingle sous des
# adresses différentes, et Yandex la rend plusieurs fois.
SEUIL_DOUBLON = 0.95
# Une candidate plus proche des Non que des OK, d'au moins cet écart, part
# dans « ressemblent à tes Non » (repliée, jamais supprimée). Mesuré le
# 05/10 sur 4 OK / 4 Non pris dans la même recherche : l'écart OK − Non des
# candidates suivantes allait de −0,09 à +0,02. À 0,02, 27 images sur 29
# partaient de côté — tout le lot. Il faut un écart net, et assez de Non
# pour qu'il veuille dire quelque chose.
ECART_NON = 0.06
MIN_NON_POUR_ECARTER = 3
# « ★ proche » : au moins aussi proche d'un OK que deux OK du même style
# entre eux (0,70 à 0,83 dans la même mesure ; un autre thème : ~0,58).
SEUIL_PROCHE = 0.80
K_VOISINS = 3

MAX_IMAGE = 20 * 1024 * 1024

#: Banques d'images : leurs aperçus portent un filigrane (« VectorStock »,
#: « alamy » en travers de l'image, vu dans les résultats du 05/10), donc
#: aucune n'est utilisable en PP ni en story. Écartées et comptées.
_BANQUES = re.compile(r"(?:^|\.)(?:vectorstock|alamy|shutterstock|dreamstime|istockphoto|gettyimages|"
                      r"depositphotos|123rf|freepik|canstockphoto|bigstockphoto|pond5|colourbox|vecteezy|"
                      r"pngtree|pikbest|lovepik|stock\.adobe)\.", re.I)
MAX_EXEMPLES = 30

_ID_STYLE = re.compile(r"^[0-9a-f]{8}$")
_CLE = re.compile(r"^[a-z0-9]{1,40}$")
_NOM_FICHIER = re.compile(r"^[a-z0-9]{1,40}\.(?:jpg|png|gif)$")
_PIN = re.compile(r"https?://i\.pinimg\.com/[^/]+/(?:[0-9a-f]{2}/){3}([0-9a-f]{32})\.(?:jpe?g|png|gif|webp)",
                  re.I)


class ErreurSource(Exception):
    """Une source n'a pas répondu comme prévu ; le message va sur la page."""


# ---------------------------------------------------------------- catégories

#: Ce qu'on cherche, et où ça part. Le propriétaire, le 05/10/2026 : « met moi
#: un truc pour life, me et travel et night [...] pp aussi ». Chaque catégorie
#: est un style (elle apprend ses propres OK / Non), avec un format par défaut
#: (une story est verticale, une PP carrée) et une destination :
#: - pp : profile_pics/ des identités, que sert le bouton 🖼 PP du menu ;
#: - me : stories/ des models elles-mêmes (📖 Story me), sans type ;
#: - life / travel / night : stories/ des RÉSERVES, avec ce type dans
#:   types_story — ce que servent 🌿 Story life et ✈️ Story travel. Un type
#:   absent de types_story.TYPES (night, au 05/10) n'a pas de bouton dans le
#:   menu Discord : la page cherche et garde, mais refuse de pousser des
#:   stories que rien ne servirait.
USAGES: Dict[str, Dict[str, Any]] = {
    "pp": {"nom": "PP", "emoji": "🖼", "format": "carre", "dest": "pp", "unite": "PP",
           "phrase": "dans les photos de profil des models cochées. Les VA les reçoivent avec le bouton 🖼 PP du menu Discord.",
           "idees": ["anime girl pfp", "cartoon girl pfp aesthetic", "kawaii cat pfp", "y2k cartoon pfp"]},
    "me": {"nom": "Story me", "emoji": "📖", "format": "vertical", "dest": "me", "unite": "stories",
           "phrase": "dans les stories des models cochées. Les VA les reçoivent avec le bouton 📖 Story me.",
           "idees": ["mirror selfie aesthetic no face", "outfit of the day aesthetic", "nails aesthetic hand",
                     "makeup vanity aesthetic"]},
    "life": {"nom": "Story life", "emoji": "🌿", "format": "vertical", "dest": "reserve", "unite": "life",
             "phrase": "dans les stories 🌿 Life des réserves cochées. Les VA les reçoivent avec le bouton 🌿 Story life.",
             # le propriétaire, le 05/10 : « comme si j'étais une fille de 18,
             # 19, 20, 21, 22 ans [...] des trucs mignons », « pas des trucs de
             # fou », puis sa liste de moments — « sans la tête bien sûr ».
             # [libellé affiché, recherche] : « pov » ramène des photos prises
             # par elle-même, sans visage ; l'anglais, plus d'images Pinterest.
             "idees": [["☕ Café", "pov coffee shop aesthetic"], ["🍸 Bar", "pov cocktails with friends aesthetic"],
                       ["🥐 Petit-déj", "pov breakfast aesthetic"], ["🎬 Cinéma", "pov movie theater popcorn aesthetic"],
                       ["🏋️ Salle de sport", "faceless gym girl aesthetic"], ["🎧 Musique", "pov headphones music aesthetic"],
                       ["📺 Netflix", "pov netflix night in aesthetic"], ["🍝 Restaurant", "pov restaurant dinner aesthetic"],
                       ["🍳 Repas", "pov homemade meal aesthetic"], ["🛋️ Chill maison", "pov cozy night in aesthetic"],
                       ["👯 Entre amies", "faceless girls night out aesthetic"],
                       ["📚 Fac", "pov university study aesthetic"], ["🎤 Événement", "pov concert crowd aesthetic"],
                       ["🎉 Fête", "pov birthday party aesthetic"], ["🥂 Soirée", "pov house party aesthetic"],
                       ["🪩 Boîte", "pov nightclub aesthetic"]]},
    "travel": {"nom": "Story travel", "emoji": "✈️", "format": "vertical", "dest": "reserve", "unite": "travel",
               "phrase": "dans les stories ✈️ Travel des réserves cochées. Les VA les reçoivent avec le bouton ✈️ Story travel.",
               "idees": [["👯 Girls trip", "pov girls trip aesthetic"], ["🏖️ Plage", "pov beach day aesthetic"],
                         ["🚗 Road trip", "pov road trip aesthetic"], ["☀️ Vacances", "pov summer vacation aesthetic"],
                         ["🚆 Train", "pov train window view aesthetic"], ["🍦 Glace", "pov ice cream beach aesthetic"],
                         ["✈️ Aéroport", "pov airport aesthetic"], ["⛺ Camping", "pov camping aesthetic"]]},
    "night": {"nom": "Story night", "emoji": "🌙", "format": "vertical", "dest": "reserve", "unite": "night",
              "phrase": "dans les stories 🌙 Night des réserves cochées. Les VA les reçoivent avec le bouton 🌙 Story night.",
              "idees": ["night city lights aesthetic", "night drive car aesthetic", "club party night aesthetic",
                        "cocktail bar night aesthetic", "rooftop night aesthetic"]},
}
#: format -> (paramètre iorient de Yandex, filtre qft de Bing)
FORMATS = {"carre": ("square", "+filterui:aspect-square"),
           "vertical": ("vertical", "+filterui:aspect-tall"),
           "tout": (None, None)}


def _format(fmt: Any, defaut: str = "carre") -> str:
    if fmt is True:
        return "carre"
    if fmt is False:
        return "tout"
    return fmt if fmt in FORMATS else defaut


def _types_story():
    try:
        import types_story
        return types_story
    except Exception:
        return None


def pousse_possible(usage: str) -> Tuple[bool, str]:
    u = USAGES.get(usage) or {}
    if u.get("dest") != "reserve":
        return True, ""
    ts = _types_story()
    if ts is None or usage not in getattr(ts, "TYPES", {}):
        return False, (f"Le type {u.get('nom', usage)} n'existe pas encore : aucun bouton {u.get('emoji', '')} "
                       f"{u.get('nom', usage)} dans le menu Discord ne servirait ces stories. "
                       "Tu peux déjà chercher et garder.")
    return True, ""


# ---------------------------------------------------------------- styles

_VERROU_STYLES = threading.RLock()
_VERROUS: Dict[str, threading.RLock] = {}


def _verrou(style_id: str) -> threading.RLock:
    with _VERROU_STYLES:
        v = _VERROUS.get(style_id)
        if v is None:
            v = _VERROUS[style_id] = threading.RLock()
        return v


def styles() -> List[Dict[str, Any]]:
    """Les styles, catégories d'abord. Chaque catégorie de USAGES en a au
    moins un, créé au premier passage ; un style d'avant les catégories
    (« Mon style », le premier jour) devient la catégorie PP."""
    with _VERROU_STYLES:
        d = safe_json.load(STYLES_FILE, default={}) or {}
        lst = [s for s in d.get("styles") or [] if isinstance(s, dict) and _ID_STYLE.match(str(s.get("id")))]
        change = False
        for s in lst:
            if s.get("usage") not in USAGES:
                s["usage"] = "pp"
                if s.get("nom") == "Mon style":
                    s["nom"] = USAGES["pp"]["nom"]
                change = True
        presents = {s["usage"] for s in lst}
        for u, meta in USAGES.items():
            if u not in presents:
                lst.append({"id": secrets.token_hex(4), "nom": meta["nom"], "usage": u,
                            "cree": int(time.time()), "recherches": []})
                change = True
        if change:
            safe_json.write(STYLES_FILE, {"styles": lst})
    ordre = list(USAGES)
    return sorted(lst, key=lambda s: (ordre.index(s["usage"]), s.get("cree", 0)))


def _style(style_id: str) -> Optional[Dict[str, Any]]:
    if not _ID_STYLE.match(str(style_id or "")):
        return None
    return next((s for s in styles() if s["id"] == style_id), None)


def _enregistrer_styles(lst: List[Dict[str, Any]]) -> None:
    safe_json.write(STYLES_FILE, {"styles": lst})


def creer_style(nom: str, usage: str = "pp", idees: Optional[List[str]] = None) -> Dict[str, Any]:
    nom = re.sub(r"\s+", " ", str(nom or "")).strip()[:60] or "Nouveau style"
    usage = usage if usage in USAGES else "pp"
    with _VERROU_STYLES:
        lst = styles()
        s = {"id": secrets.token_hex(4), "nom": nom, "usage": usage, "cree": int(time.time()), "recherches": []}
        if idees:
            s["idees"] = [re.sub(r"\s+", " ", str(x)).strip()[:80] for x in idees if str(x).strip()][:10]
        lst.append(s)
        _enregistrer_styles(lst)
    return s


def renommer_style(style_id: str, nom: str) -> bool:
    nom = re.sub(r"\s+", " ", str(nom or "")).strip()[:60]
    if not nom:
        return False
    with _VERROU_STYLES:
        lst = styles()
        for s in lst:
            if s["id"] == style_id:
                s["nom"] = nom
                _enregistrer_styles(lst)
                return True
    return False


def _noter_recherche(style_id: str, requete: str) -> None:
    with _VERROU_STYLES:
        lst = styles()
        for s in lst:
            if s["id"] == style_id:
                r = [x for x in s.get("recherches") or [] if x.lower() != requete.lower()]
                s["recherches"] = ([requete] + r)[:12]
                _enregistrer_styles(lst)
                return


def _dossier(style_id: str) -> Path:
    return RACINE / style_id


def _fichier_avis(style_id: str) -> Path:
    return _dossier(style_id) / "avis.json"


def _avis(style_id: str) -> Dict[str, Dict[str, Any]]:
    d = safe_json.load(_fichier_avis(style_id), default={}) or {}
    return {k: v for k, v in d.items() if isinstance(v, dict) and _CLE.match(k)}


def _enregistrer_avis(style_id: str, avis: Dict[str, Dict[str, Any]]) -> None:
    safe_json.write(_fichier_avis(style_id), avis, indent=None)


# ---------------------------------------------------------------- réseau

def _url_publique(u: str) -> bool:
    """Les adresses d'images viennent de la page, donc du navigateur : le
    serveur ne doit pas aller chercher une adresse interne (127.0.0.1,
    réseau du VPS) parce qu'on la lui a passée."""
    try:
        p = urllib.parse.urlsplit(u)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80)):
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        return True
    except Exception:
        return False


def _telecharger(u: str, max_octets: int = MAX_IMAGE, timeout: float = 15) -> Optional[bytes]:
    """GET d'une image publique ; redirections suivies à la main pour que
    chacune repasse par _url_publique. None si refusé, trop gros ou en panne."""
    for _ in range(4):
        if not _url_publique(u):
            return None
        try:
            r = requests.get(u, headers={"User-Agent": UA, "Referer": "https://www.pinterest.com/"},
                             timeout=timeout, stream=True, allow_redirects=False)
        except Exception:
            return None
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            u = urllib.parse.urljoin(u, r.headers["Location"])
            r.close()
            continue
        if r.status_code != 200:
            r.close()
            return None
        buf = io.BytesIO()
        try:
            for bloc in r.iter_content(65536):
                buf.write(bloc)
                if buf.tell() > max_octets:
                    return None
        except Exception:
            return None
        finally:
            r.close()
        return buf.getvalue()
    return None


_YX_VERROU = threading.Lock()
_YX_DERNIER = [0.0]
_YX_SESSION: List[Any] = []


def _yx_session():
    # curl_cffi imite un vrai Chrome jusqu'à la poignée de main TLS ; il est
    # déjà sur le VPS (yt-dlp[curl-cffi]). Sans lui, requests en repli.
    if not _YX_SESSION:
        try:
            from curl_cffi import requests as cr
            _YX_SESSION.append(cr.Session(impersonate="chrome"))
        except Exception:
            s = requests.Session()
            s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,fr;q=0.8"})
            _YX_SESSION.append(s)
    return _YX_SESSION[0]


def _yx_espacer() -> None:
    # une requête Yandex à la fois, et au moins 1,2 s entre deux : c'est le
    # rythme auquel les essais du 05/10 n'ont jamais vu de captcha
    attente = _YX_DERNIER[0] + 1.2 - time.time()
    if attente > 0:
        time.sleep(attente)
    _YX_DERNIER[0] = time.time()


def _etat_yandex(texte: str, url_finale: str) -> Dict[str, Any]:
    if "showcaptcha" in (url_finale or "") or ("captcha" in texte[:30000].lower() and "data-state" not in texte):
        raise ErreurSource("Yandex demande une vérification anti-robot (trop de recherches d'un coup). "
                           "Réessaie dans quelques minutes.")
    for brut in re.findall(r'data-state="([^"]+)"', texte):
        try:
            j = json.loads(_html.unescape(brut))
        except Exception:
            continue
        if isinstance(j, dict) and isinstance(j.get("initialState"), dict):
            return j["initialState"]
    raise ErreurSource("Yandex a répondu sans liste d'images (page changée ?).")


def _entites_yandex(etat: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = ((etat.get("serpList") or {}).get("items") or {})
    ents = items.get("entities") or {}
    ordre = items.get("keys") or list(ents.keys())
    return [ents[k] for k in ordre if isinstance(ents.get(k), dict)]


def yandex_texte(requete: str, page: int = 0, fmt: Any = "carre") -> Tuple[List[Dict[str, Any]], bool]:
    """(candidates, fin) pour une page de recherche texte."""
    params = {"text": requete, "p": max(0, int(page))}
    orient = FORMATS[_format(fmt)][0]
    if orient:
        params["iorient"] = orient
    with _YX_VERROU:
        _yx_espacer()
        try:
            r = _yx_session().get("https://yandex.com/images/search", params=params, timeout=25)
        except Exception as e:
            raise ErreurSource(f"Yandex injoignable ({type(e).__name__}).")
    if r.status_code != 200:
        raise ErreurSource(f"Yandex a répondu HTTP {r.status_code}.")
    etat = _etat_yandex(r.text, str(r.url))
    cands = [c for c in (depuis_yandex(e) for e in _entites_yandex(etat)) if c]
    sl = etat.get("serpList") or {}
    der = sl.get("lastPage")
    fin = not cands or (isinstance(der, int) and int(page) >= der)
    return cands, fin


def yandex_similaires(image: bytes) -> List[Dict[str, Any]]:
    """Recherche PAR IMAGE : on envoie le fichier (marche aussi pour un
    exemple qui n'a pas d'adresse publique), Yandex rend ses voisines."""
    req = json.dumps({"blocks": [{"block": "b-page_type_search-by-image__link"}]})
    params = {"rpt": "imageview", "format": "json", "request": req}
    s = _yx_session()
    with _YX_VERROU:
        _yx_espacer()
        try:
            try:
                from curl_cffi import CurlMime
                mp = CurlMime()
                mp.addpart(name="upfile", content_type="image/jpeg", filename="image.jpg", data=image)
                r = s.post("https://yandex.com/images/search", params=params, multipart=mp, timeout=30)
            except ImportError:
                r = s.post("https://yandex.com/images/search", params=params,
                           files={"upfile": ("image.jpg", image, "image/jpeg")}, timeout=30)
            p = (r.json().get("blocks") or [{}])[0].get("params") or {}
        except ErreurSource:
            raise
        except Exception as e:
            raise ErreurSource(f"Yandex n'a pas accepté l'image ({type(e).__name__}).")
        if not p.get("cbirId") or not p.get("originalImageUrl"):
            raise ErreurSource("Yandex n'a pas rendu d'identifiant pour l'image envoyée.")
        _yx_espacer()
        try:
            r2 = s.get("https://yandex.com/images/search",
                       params={"cbir_id": p["cbirId"], "url": p["originalImageUrl"],
                               "rpt": "imageview", "cbir_page": "similar"}, timeout=30)
        except Exception as e:
            raise ErreurSource(f"Yandex injoignable ({type(e).__name__}).")
    etat = _etat_yandex(r2.text, str(r2.url))
    return [c for c in (depuis_yandex(e) for e in _entites_yandex(etat)) if c]


def bing(requete: str, fmt: Any = "carre") -> List[Dict[str, Any]]:
    params = {"q": requete, "first": 0, "count": 35, "mmasync": 1}
    qft = FORMATS[_format(fmt)][1]
    if qft:
        params["qft"] = qft
    try:
        r = requests.get("https://www.bing.com/images/async", params=params, timeout=20,
                         headers={"User-Agent": UA, "Cookie": "SRCHHPGUSR=ADLT=MODERATE",
                                  "Accept-Language": "en-US,en;q=0.9,fr;q=0.8"})
    except Exception as e:
        raise ErreurSource(f"Bing injoignable ({type(e).__name__}).")
    if r.status_code != 200:
        raise ErreurSource(f"Bing a répondu HTTP {r.status_code}.")
    out = []
    for brut in re.findall(r'\sm="(\{[^"]+\})"', r.text):
        try:
            c = depuis_bing(json.loads(_html.unescape(brut)))
        except Exception:
            continue
        if c:
            out.append(c)
    return out


# ---------------------------------------------------------------- candidates

def cle_image(urls: List[str]) -> str:
    """Même épingle Pinterest = même clé, quelle que soit la taille servie
    (236x, 474x, 736x, originals) : c'est le hachage dans l'adresse."""
    for u in urls:
        m = _PIN.search(u or "")
        if m:
            return "p" + m.group(1).lower()
    u = next((u for u in urls if u), "")
    return "u" + hashlib.sha1(u.split("#")[0].encode("utf-8", "ignore")).hexdigest()[:24]


def _trier_urls(cands: List[Tuple[str, int, int]]) -> List[str]:
    vus, out = set(), []
    for u, w, h in cands:
        u = (u or "").strip()
        if u.startswith("//"):
            u = "https:" + u
        u = re.sub(r"\?nii=t$", "", u)
        if not u.startswith(("http://", "https://")) or u in vus:
            continue
        if w and h and min(w, h) < 200:
            continue          # avatars Steam 64 px et autres vignettes : inutilisables en photo de profil
        vus.add(u)
        out.append((u, w or 0, h or 0))
    out.sort(key=lambda x: (0 if "pinimg.com/originals/" in x[0] else 1, -(x[1] * x[2])))
    return [u for u, _, _ in out]


def depuis_yandex(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    vd = e.get("viewerData") or {}
    brutes = [(e.get("origUrl") or "", e.get("origWidth") or 0, e.get("origHeight") or 0)]
    for d in (vd.get("dups") or []) + (vd.get("preview") or []):
        if isinstance(d, dict):
            brutes.append((d.get("url") or "", d.get("w") or 0, d.get("h") or 0))
    urls = _trier_urls(brutes)
    vign = (vd.get("thumb") or {}).get("url") or e.get("image") or ""
    if vign.startswith("//"):
        vign = "https:" + vign
    if not urls or not vign:
        return None
    sn = e.get("snippet") or {}
    return {"cle": cle_image(urls), "img": urls[0], "alt": urls[1:4], "vign": vign,
            "page": str(sn.get("url") or "")[:500],
            "titre": re.sub(r"<[^>]+>", "", str(sn.get("title") or e.get("alt") or ""))[:140],
            "w": int(e.get("origWidth") or e.get("width") or 0),
            "h": int(e.get("origHeight") or e.get("height") or 0), "src": "yandex"}


def depuis_bing(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    urls = _trier_urls([(m.get("murl") or "", 0, 0)])
    vign = m.get("turl") or ""
    if not urls or not vign.startswith("http"):
        return None
    return {"cle": cle_image(urls), "img": urls[0], "alt": [], "vign": vign,
            "page": str(m.get("purl") or "")[:500], "titre": str(m.get("t") or "")[:140],
            "w": 0, "h": 0, "src": "bing"}


# ---------------------------------------------------------------- modèle

_MODELE = {"etat": "absent", "pct": 0, "erreur": ""}
_MODELE_VERROU = threading.Lock()
_SESSION: List[Any] = []
_SESSION_USAGE = [0.0]
_INFERENCE = threading.Lock()
_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)


def etat_modele() -> Dict[str, Any]:
    """État de l'apprentissage, pour la page. Déclenche le téléchargement
    du modèle s'il manque."""
    with _MODELE_VERROU:
        if _MODELE["etat"] in ("telechargement", "pret"):
            return dict(_MODELE)
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
        except Exception:
            _MODELE.update(etat="indisponible", erreur="onnxruntime n'est pas installé sur ce serveur")
            return dict(_MODELE)
        if MODELE_FILE.exists() and MODELE_FILE.stat().st_size == MODELE_TAILLE:
            _MODELE.update(etat="pret", pct=100, erreur="")
            return dict(_MODELE)
        if _MODELE["etat"] == "erreur" and time.time() - _MODELE.get("depuis", 0) < 600:
            return dict(_MODELE)          # pas de nouvel essai en boucle
        _MODELE.update(etat="telechargement", pct=0, erreur="")
        threading.Thread(target=_telecharger_modele, daemon=True, name="pfp-modele").start()
        return dict(_MODELE)


def _telecharger_modele() -> None:
    part = MODELE_FILE.with_suffix(".onnx.part")
    try:
        MODELE_FILE.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        n = 0
        with requests.get(MODELE_URL, stream=True, timeout=60, headers={"User-Agent": UA}) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for bloc in r.iter_content(1 << 20):
                    f.write(bloc)
                    h.update(bloc)
                    n += len(bloc)
                    _MODELE["pct"] = min(99, int(n * 100 / MODELE_TAILLE))
                f.flush()
                os.fsync(f.fileno())
        if n != MODELE_TAILLE or h.hexdigest() != MODELE_SHA256:
            raise ValueError(f"fichier reçu différent de l'attendu ({n} octets)")
        os.replace(part, MODELE_FILE)
        with _MODELE_VERROU:
            _MODELE.update(etat="pret", pct=100, erreur="")
        print("[pfp] modèle CLIP téléchargé et vérifié", flush=True)
    except Exception as e:
        try:
            part.unlink()
        except Exception:
            pass
        with _MODELE_VERROU:
            _MODELE.update(etat="erreur", erreur=f"téléchargement du modèle : {type(e).__name__} : {e}"[:300],
                           depuis=time.time())
        print(f"[pfp] modèle CLIP : {e}", flush=True)


def _session_onnx():
    with _MODELE_VERROU:
        _SESSION_USAGE[0] = time.time()
        if _SESSION:
            return _SESSION[0]
        import onnxruntime as ort
        so = ort.SessionOptions()
        # le VPS n'a que 2 cœurs et ils servent aussi le bot et le site
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        _SESSION.append(ort.InferenceSession(str(MODELE_FILE), so, providers=["CPUExecutionProvider"]))
        threading.Thread(target=_decharger_si_inactif, daemon=True, name="pfp-dechargement").start()
        return _SESSION[0]


def _decharger_si_inactif() -> None:
    # ~400 Mo de mémoire dans le processus du bot : rendus après 15 min sans servir
    while True:
        time.sleep(60)
        with _MODELE_VERROU:
            if _SESSION and time.time() - _SESSION_USAGE[0] > 900:
                _SESSION.clear()
                return


def _pret() -> bool:
    return etat_modele()["etat"] == "pret"


def _pixels(image: bytes):
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(image))
    im.seek(0)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fond = Image.new("RGBA", im.size, (255, 255, 255, 255))
        fond.alpha_composite(im)
        im = fond
    im = im.convert("RGB")
    w, h = im.size
    k = 224 / min(w, h)
    im = im.resize((max(224, round(w * k)), max(224, round(h * k))), Image.BICUBIC)
    w, h = im.size
    g, t = (w - 224) // 2, (h - 224) // 2
    a = np.asarray(im.crop((g, t, g + 224, t + 224)), dtype=np.float32) / 255.0
    a = (a - np.array(_MEAN, dtype=np.float32)) / np.array(_STD, dtype=np.float32)
    return a.transpose(2, 0, 1)


def vecteurs(images: List[Optional[bytes]]):
    """Un vecteur normé (512 flottants) par image, None si l'image est
    illisible ou si le modèle n'est pas prêt."""
    import numpy as np
    out: List[Any] = [None] * len(images)
    if not _pret():
        return out
    lots = []
    for i, b in enumerate(images):
        if not b:
            continue
        try:
            lots.append((i, _pixels(b)))
        except Exception:
            pass
    s = _session_onnx()
    for d in range(0, len(lots), 16):
        part = lots[d:d + 16]
        with _INFERENCE:
            v = s.run(None, {"pixel_values": np.stack([p for _, p in part])})[0]
        v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)
        for (i, _), x in zip(part, v):
            out[i] = x.astype(np.float32)
    return out


def _vec_vers_txt(v) -> str:
    import numpy as np
    return base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode("ascii")


def _txt_vers_vec(t: str):
    import numpy as np
    try:
        v = np.frombuffer(base64.b64decode(t), dtype=np.float16).astype(np.float32)
        return v if v.shape == (512,) else None
    except Exception:
        return None


# vecteurs des candidates déjà vues, par clé : « Charger plus » ou une
# seconde recherche ne retéléchargent pas les mêmes vignettes
_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_CACHE_VERROU = threading.Lock()
_CACHE_MAX = 6000
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="pfp-vign")


def _vecteurs_candidates(cands: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not _pret():
        return {}
    res: Dict[str, Any] = {}
    manquent = []
    with _CACHE_VERROU:
        for c in cands:
            if c["cle"] in _CACHE:
                res[c["cle"]] = _CACHE[c["cle"]]
                _CACHE.move_to_end(c["cle"])
            else:
                manquent.append(c)
    if manquent:
        octets = list(_POOL.map(lambda c: _telecharger(c["vign"], 3 * 1024 * 1024, 12), manquent))
        vs = vecteurs(octets)
        with _CACHE_VERROU:
            for c, v in zip(manquent, vs):
                if v is not None:
                    res[c["cle"]] = _CACHE[c["cle"]] = v
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return res


def _completer_vecteurs(style_id: str, avis: Dict[str, Dict[str, Any]], limite: int = 40) -> None:
    """Les avis donnés avant que le modèle soit prêt n'ont pas de vecteur :
    on les calcule au fil des recherches (fichier gardé, sinon vignette)."""
    if not _pret():
        return
    sans = [(k, e) for k, e in avis.items() if e.get("v") in ("ok", "non") and not e.get("vec")][:limite]
    if not sans:
        return
    dossier = _dossier(style_id) / "garde"

    def _octets(ke):
        k, e = ke
        f = e.get("fichier")
        if f and (dossier / f).is_file():
            return (dossier / f).read_bytes()
        return _telecharger(e.get("vign") or "", 3 * 1024 * 1024, 12)

    vs = vecteurs(list(_POOL.map(_octets, sans)))
    with _verrou(style_id):
        frais = _avis(style_id)
        for (k, _), v in zip(sans, vs):
            if v is not None and k in frais:
                frais[k]["vec"] = avis[k]["vec"] = _vec_vers_txt(v)
        _enregistrer_avis(style_id, frais)


# ---------------------------------------------------------------- classement

def _banque(c: Dict[str, Any]) -> bool:
    for u in (c.get("img"), c.get("page")):
        h = urllib.parse.urlsplit(str(u or "")).hostname or ""
        if _BANQUES.search(h):
            return True
    return False


def _classer(style_id: str, cands: List[Dict[str, Any]], erreurs: List[str], fin: bool,
             titre: str) -> Dict[str, Any]:
    import numpy as np
    avis = _avis(style_id)
    vus, uniques, deja, filigranes = set(), [], 0, 0
    for c in cands:
        if c["cle"] in vus:
            continue
        vus.add(c["cle"])
        if _banque(c):
            filigranes += 1
            continue
        if c["cle"] in avis:
            deja += 1
            continue
        uniques.append(c)
    _completer_vecteurs(style_id, avis)
    vecs = _vecteurs_candidates(uniques)
    pos = [v for v in (_txt_vers_vec(e["vec"]) for e in avis.values() if e.get("v") == "ok" and e.get("vec"))
           if v is not None]
    neg = [v for v in (_txt_vers_vec(e["vec"]) for e in avis.values() if e.get("v") == "non" and e.get("vec"))
           if v is not None]
    juges = pos + neg
    P = np.stack(pos) if pos else None
    N = np.stack(neg) if neg else None
    J = np.stack(juges) if juges else None

    def _proche(M, v):
        if M is None:
            return None
        s = np.sort(M @ v)[-K_VOISINS:]
        return float(s.mean())

    gardees, ecartees, doublons = [], [], 0
    retenus: List[Any] = []
    for c in uniques:
        v = vecs.get(c["cle"])
        if v is not None:
            # même image sous une autre adresse : déjà jugée, ou déjà dans ce lot
            if J is not None and float((J @ v).max()) >= SEUIL_DOUBLON:
                doublons += 1
                continue
            if any(float(r @ v) >= SEUIL_DOUBLON for r in retenus):
                doublons += 1
                continue
            retenus.append(v)
            sp, sn = _proche(P, v), _proche(N, v)
            c["sp"] = None if sp is None else round(sp, 3)
            c["sn"] = None if sn is None else round(sn, 3)
            c["score"] = (sp or 0.0) - (sn or 0.0)
            c["proche"] = sp is not None and sp >= SEUIL_PROCHE and (sn is None or sp >= sn)
            if len(neg) >= MIN_NON_POUR_ECARTER and sn is not None and sn - (sp or 0.0) > ECART_NON:
                ecartees.append(c)
                continue
        gardees.append(c)
    classe = bool(pos or neg) and bool(vecs)
    if classe:
        # les candidates sans vecteur (vignette illisible) restent, en fin de liste
        gardees.sort(key=lambda c: c.get("score", -9), reverse=True)
        ecartees.sort(key=lambda c: c.get("score", -9), reverse=True)
    return {"ok": True, "titre": titre, "images": gardees, "ecartees": ecartees,
            "doublons": doublons, "deja_jugees": deja, "filigranes": filigranes, "fin": fin, "erreurs": erreurs,
            "classe": classe, "sans_vecteur": sum(1 for c in uniques if c["cle"] not in vecs) if vecs else 0,
            "apprentissage": {"ok": len(pos), "non": len(neg)}}


def chercher(style_id: str, requete: str, page: int = 0, fmt: Any = None) -> Dict[str, Any]:
    st = _style(style_id)
    if not st:
        return {"ok": False, "erreur": "Style inconnu."}
    fmt_ = _format(fmt, USAGES[st["usage"]]["format"])
    requete = re.sub(r"\s+", " ", str(requete or "")).strip()[:200]
    if not requete:
        return {"ok": False, "erreur": "Décris l'image cherchée."}
    page = max(0, min(int(page or 0), 20))
    cands, erreurs, fin = [], [], False
    try:
        c, fin = yandex_texte(requete, page, fmt_)
        cands += c
    except ErreurSource as e:
        erreurs.append(f"Yandex : {e}")
        fin = page > 0
    if page == 0:
        try:
            cands += bing(requete, fmt_)
        except ErreurSource as e:
            erreurs.append(f"Bing : {e}")
        _noter_recherche(style_id, requete)
    return _classer(style_id, cands, erreurs, fin, requete)


def _octets_pour_graine(style_id: str, e: Dict[str, Any]) -> Optional[bytes]:
    f = e.get("fichier")
    p = _dossier(style_id) / "garde" / str(f or "")
    if f and _NOM_FICHIER.match(f) and p.is_file():
        b = p.read_bytes()
    else:
        b = _telecharger(e.get("vign") or "", 3 * 1024 * 1024, 12) or _telecharger(e.get("img") or "")
    if not b:
        return None
    # Yandex attend un JPEG raisonnable : un PNG de 8 Mo est réduit avant l'envoi
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(b))
        im.seek(0)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            fond = Image.new("RGBA", im.size, (255, 255, 255, 255))
            fond.alpha_composite(im)
            im = fond
        im = im.convert("RGB")
        im.thumbnail((800, 800))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=90)
        return out.getvalue()
    except Exception:
        return None


def pour_toi(style_id: str) -> Dict[str, Any]:
    """Les voisines (recherche par image) de trois images gardées — celles
    qui ont le moins servi de graine, les plus récentes d'abord — classées
    par tout ce qui a été appris. Chaque appel prend les trois suivantes."""
    if not _style(style_id):
        return {"ok": False, "erreur": "Style inconnu."}
    with _verrou(style_id):
        avis = _avis(style_id)
        oks = [(k, e) for k, e in avis.items() if e.get("v") == "ok"]
        if not oks:
            return {"ok": False, "erreur": "Garde au moins une image (OK) ou ajoute un exemple d'abord."}
        oks.sort(key=lambda ke: (ke[1].get("graine", 0), -ke[1].get("t", 0)))
        graines = oks[:3]
        for k, _ in graines:
            avis[k]["graine"] = int(avis[k].get("graine", 0)) + 1
        _enregistrer_avis(style_id, avis)
    cands, erreurs = [], []
    for k, e in graines:
        b = _octets_pour_graine(style_id, e)
        if not b:
            erreurs.append("Une image gardée n'a pas pu être relue (vignette disparue).")
            continue
        try:
            cands += yandex_similaires(b)
        except ErreurSource as x:
            erreurs.append(f"Yandex : {x}")
            break
    return _classer(style_id, cands, erreurs, False, "Pour toi")


def similaires(style_id: str, cle: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """« Plus comme ça » sur une seule image, gardée ou encore à juger."""
    if not _style(style_id):
        return {"ok": False, "erreur": "Style inconnu."}
    e = _avis(style_id).get(cle) or _meta_propre(meta)
    if not e:
        return {"ok": False, "erreur": "Image inconnue."}
    b = _octets_pour_graine(style_id, e)
    if not b:
        return {"ok": False, "erreur": "Impossible de relire cette image."}
    try:
        cands = yandex_similaires(b)
        erreurs: List[str] = []
    except ErreurSource as x:
        cands, erreurs = [], [f"Yandex : {x}"]
    return _classer(style_id, cands, erreurs, False, "Plus comme ça")


# ---------------------------------------------------------------- avis

_TELECHARGEMENTS = ThreadPoolExecutor(max_workers=3, thread_name_prefix="pfp-garde")


def _meta_propre(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ce que la page renvoie d'une candidate : revalidé, rien d'autre gardé."""
    if not isinstance(meta, dict):
        return None

    def _u(x):
        x = str(x or "")[:1000]
        return x if x.startswith(("http://", "https://")) else ""

    img, vign = _u(meta.get("img")), _u(meta.get("vign"))
    if not img and not vign:
        return None
    return {"img": img, "vign": vign, "alt": [a for a in (_u(x) for x in (meta.get("alt") or [])[:4]) if a],
            "page": _u(meta.get("page")), "titre": str(meta.get("titre") or "")[:140],
            "src": str(meta.get("src") or "")[:12]}


def _vers_corbeille(style_id: str, nom: str) -> None:
    """Le site n'efface jamais une image : elle part dans la corbeille du style."""
    if not nom or not _NOM_FICHIER.match(nom):
        return
    src = _dossier(style_id) / "garde" / nom
    if src.is_file():
        dst = _dossier(style_id) / "corbeille"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst / f"{int(time.time())}_{nom}"))


def juger(style_id: str, cle: str, verdict: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    if not _style(style_id):
        return {"ok": False, "erreur": "Style inconnu."}
    if not _CLE.match(str(cle or "")) or verdict not in ("ok", "non", "annuler"):
        return {"ok": False, "erreur": "Demande invalide."}
    with _verrou(style_id):
        avis = _avis(style_id)
        ancien = avis.get(cle)
        if verdict == "annuler":
            if ancien:
                _vers_corbeille(style_id, ancien.get("fichier") or "")
                del avis[cle]
                _enregistrer_avis(style_id, avis)
            return {"ok": True, "cle": cle, "v": None, "stats": _stats(avis)}
        m = _meta_propre(meta) if not ancien else None
        if not ancien and not m:
            return {"ok": False, "erreur": "Image sans adresse."}
        e = ancien or m
        if ancien and ancien.get("v") == "ok" and verdict == "non":
            _vers_corbeille(style_id, ancien.get("fichier") or "")
            e.pop("fichier", None)
        e["v"] = verdict
        e["t"] = int(time.time())
        with _CACHE_VERROU:
            v = _CACHE.get(cle)
        if v is not None and not e.get("vec"):
            e["vec"] = _vec_vers_txt(v)
        avis[cle] = e
        _enregistrer_avis(style_id, avis)
        stats = _stats(avis)
    if verdict == "ok" and not e.get("fichier"):
        _TELECHARGEMENTS.submit(_garder, style_id, cle)
    return {"ok": True, "cle": cle, "v": verdict, "stats": stats}


def _format_image(b: bytes) -> Optional[Tuple[bytes, str]]:
    """(octets, extension) prêts pour X / Twitter, qui prend JPG, PNG et GIF :
    un WebP (ou un HEIC d'iPhone) est converti en PNG. None si ce n'est pas
    une image."""
    try:
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        im = Image.open(io.BytesIO(b))
        im.verify()
        im = Image.open(io.BytesIO(b))
        fmt = (im.format or "").upper()
        if min(im.size) < 64:
            return None
        if fmt == "JPEG":
            return b, "jpg"
        if fmt in ("PNG", "GIF"):
            return b, fmt.lower()
        out = io.BytesIO()
        im.seek(0)
        im.convert("RGBA").save(out, "PNG")
        return out.getvalue(), "png"
    except Exception:
        return None


def _garder(style_id: str, cle: str) -> None:
    with _verrou(style_id):
        e = dict(_avis(style_id).get(cle) or {})
    if e.get("v") != "ok":
        return
    pret, essais = None, [u for u in [e.get("img")] + list(e.get("alt") or []) + [e.get("vign")] if u]
    for u in essais:
        b = _telecharger(u)
        pret = _format_image(b) if b else None
        if pret:
            break
    dossier = _dossier(style_id) / "garde"
    nom = None
    if pret:
        nom = f"{cle}.{pret[1]}"
        dossier.mkdir(parents=True, exist_ok=True)
        tmp = dossier / (nom + ".tmp")
        with open(tmp, "wb") as f:
            f.write(pret[0])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dossier / nom)
    with _verrou(style_id):
        avis = _avis(style_id)
        cur = avis.get(cle)
        if not cur or cur.get("v") != "ok":
            # annulé pendant le téléchargement : le fichier suit la règle commune
            if nom:
                _vers_corbeille(style_id, nom)
            return
        if nom:
            cur["fichier"] = nom
            cur.pop("echec", None)
        else:
            cur["echec"] = "Aucune des adresses de l'image n'a répondu."
            print(f"[pfp] {style_id}/{cle} : original introuvable ({len(essais)} adresses essayées)", flush=True)
        _enregistrer_avis(style_id, avis)


def reessayer(style_id: str, cle: str) -> Dict[str, Any]:
    if not _style(style_id) or not _CLE.match(str(cle or "")):
        return {"ok": False, "erreur": "Demande invalide."}
    e = _avis(style_id).get(cle)
    if not e or e.get("v") != "ok":
        return {"ok": False, "erreur": "Image non gardée."}
    _TELECHARGEMENTS.submit(_garder, style_id, cle)
    return {"ok": True}


def ajouter_exemples(style_id: str, fichiers: List[Tuple[str, bytes]]) -> Dict[str, Any]:
    """Les photos que le propriétaire utilise déjà : gardées comme des OK,
    elles amorcent le classement et « Pour toi »."""
    if not _style(style_id):
        return {"ok": False, "erreur": "Style inconnu."}
    ajoutes, refuses = [], []
    prets = []
    for nom, b in fichiers[:MAX_EXEMPLES]:
        f = _format_image(b) if b and len(b) <= MAX_IMAGE else None
        if not f:
            refuses.append(nom or "?")
            continue
        prets.append((nom, b, f))
    if len(fichiers) > MAX_EXEMPLES:
        refuses += [n or "?" for n, _ in fichiers[MAX_EXEMPLES:]]
    vs = vecteurs([b for _, b, _ in prets])
    dossier = _dossier(style_id) / "garde"
    dossier.mkdir(parents=True, exist_ok=True)
    with _verrou(style_id):
        avis = _avis(style_id)
        for (nom, b, (octets, ext)), v in zip(prets, vs):
            cle = "x" + hashlib.sha1(b).hexdigest()[:24]
            fichier = f"{cle}.{ext}"
            tmp = dossier / (fichier + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(octets)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dossier / fichier)
            e = {"v": "ok", "t": int(time.time()), "img": "", "vign": "", "alt": [], "page": "",
                 "titre": str(nom or "")[:140], "src": "exemple", "fichier": fichier}
            if v is not None:
                e["vec"] = _vec_vers_txt(v)
            avis[cle] = e
            ajoutes.append(cle)
        _enregistrer_avis(style_id, avis)
        stats = _stats(avis)
    return {"ok": True, "ajoutes": len(ajoutes), "refuses": refuses, "stats": stats}


def _stats(avis: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    return {"ok": sum(1 for e in avis.values() if e.get("v") == "ok"),
            "non": sum(1 for e in avis.values() if e.get("v") == "non")}


def gardees(style_id: str) -> List[Dict[str, Any]]:
    avis = _avis(style_id)
    out = []
    for k, e in sorted(avis.items(), key=lambda ke: -ke[1].get("t", 0)):
        if e.get("v") != "ok":
            continue
        out.append({"cle": k, "fichier": e.get("fichier") or "", "vign": e.get("vign") or "",
                    "img": e.get("img") or "", "page": e.get("page") or "", "titre": e.get("titre") or "",
                    "src": e.get("src") or "", "echec": e.get("echec") or "",
                    "en_cours": not e.get("fichier") and not e.get("echec"),
                    # « us » / « fr » : les envois d'avant le bouton unique
                    "pousse_n": len({i for v in (e.get("pousse") or {}).values() for i in (v or [])})})
    return out


def chemin_fichier(style_id: str, nom: str) -> Optional[Path]:
    if not _ID_STYLE.match(str(style_id or "")) or not _NOM_FICHIER.match(str(nom or "")):
        return None
    p = _dossier(style_id) / "garde" / nom
    return p if p.is_file() else None


def archive_zip(style_id: str) -> Optional[Tuple[bytes, str]]:
    s = _style(style_id)
    if not s:
        return None
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for g in gardees(style_id):
            p = chemin_fichier(style_id, g["fichier"])
            if p:
                z.write(p, p.name)
                n += 1
    nom = re.sub(r"[^A-Za-z0-9_-]+", "-", s["nom"]).strip("-").lower() or "style"
    return buf.getvalue(), f"pfp-{nom}-{n}.zip"


# ---------------------------------------------------------------- pousser vers les models

#: Les photos de profil que le bouton 🖼 PP du menu Discord donne aux VA
#: vivent par identité : data/identities/<id>/profile_pics/pp_N.ext. Le
#: marché de l'identité (marche.py) dit de quel côté elle est : US = OnlyFans,
#: FR = MYM ; il n'est plus qu'un drapeau sur la page : le propriétaire a
#: retiré les deux boutons OF / MYM (« je me suis trompé », 05/10) — une PP
#: suit le LOOK d'un groupe de models, pas son marché. « tout » = les deux
#: marchés. Ce module ne connaît ni la liste des identités ni leurs
#: dossiers : le site les lui passe à register() (_PP), pour qu'il n'importe
#: pas web_upload et qu'une seule règle décide quelles identités existent.
MARCHES = {"us": "OF", "fr": "MYM"}
_PP: Dict[str, Any] = {}
_EXT_PP = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _pp_branche() -> bool:
    return all(callable(_PP.get(k)) for k in ("identites", "marche", "dossier"))


def _photos_pp(d: Path) -> List[Path]:
    if not d.is_dir():
        return []
    return [x for x in d.iterdir() if x.is_file() and x.suffix.lower() in _EXT_PP]


def _dossier_dest(identite: str, usage: str) -> Path:
    """profile_pics/ pour une PP, stories/ (son voisin) pour une story."""
    d = _PP["dossier"](identite)
    return d if USAGES[usage]["dest"] == "pp" else d.parent / "stories"


def _nature(identite: str) -> str:
    try:
        return str(_PP["nature"](identite)) if callable(_PP.get("nature")) else ""
    except Exception:
        return ""


def _empreintes_exemples(style_id: Optional[str]) -> Dict[int, set]:
    """{taille: {md5}} des exemples d'un style — les photos que les models
    utilisent déjà et qui ont servi à l'amorcer."""
    out: Dict[int, set] = {}
    if not style_id or not _style(style_id):
        return out
    for e in _avis(style_id).values():
        if e.get("v") == "ok" and e.get("src") == "exemple":
            f = chemin_fichier(style_id, e.get("fichier") or "")
            if f:
                b = f.read_bytes()
                out.setdefault(len(b), set()).add(hashlib.md5(b).hexdigest())
    return out


def cibles(marche: str, usage: str = "pp", style_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Les identités d'un marché où cette catégorie peut partir, avec ce
    qu'elles ont déjà : PP pour une PP, stories pour Story me, stories de ce
    type pour une réserve. « coche » : la proposition par défaut de la page.

    Un style amorcé avec les PP d'un groupe (les 18 PP blondes de blonde,
    ellieann...) coche les identités qui ont déjà ces PP — et elles seules :
    chaque groupe de models a son look, et le cocher partout aurait mis des
    blondes chez les brunes."""
    u = USAGES.get(usage)
    if (marche not in MARCHES and marche != "tout") or not u or not _pp_branche():
        return []
    exemples = _empreintes_exemples(style_id) if u["dest"] != "reserve" else {}
    reg = {}
    if u["dest"] == "reserve":
        ts = _types_story()
        if ts is None or usage not in getattr(ts, "TYPES", {}):
            return []
        reg = ts.lire()
    out = []
    for i in sorted(_PP["identites"](), key=str.lower):
        try:
            mk = _PP["marche"](i)
        except Exception:
            continue
        if marche != "tout" and mk != marche:
            continue
        nat = _nature(i)
        if u["dest"] == "reserve" and nat != "reserve":
            continue
        if u["dest"] == "me" and nat == "reserve":
            continue          # une réserve n'a pas de Story me : ses stories ont un type
        photos = _photos_pp(_dossier_dest(i, usage))
        if u["dest"] == "reserve":
            n = sum(1 for x in photos if reg.get(_types_story().cle(i, x.name)) == usage)
            coche = True      # peu de réserves, et c'est tout leur rôle
        else:
            n = len(photos)
            coche = n > 0
        meme_look = 0
        if exemples:
            meme_look = sum(1 for x in photos if x.stat().st_size in exemples
                            and hashlib.md5(x.read_bytes()).hexdigest() in exemples[x.stat().st_size])
            coche = meme_look > 0
        out.append({"id": i, "n": n, "coche": coche, "look": meme_look, "marche": mk})
    return out


def pousser(style_id: str, cles: List[str], marche: str, identites: List[str]) -> Dict[str, Any]:
    # marche : « tout », ou « us » / « fr » pour ne viser qu'un côté
    """COPIE des images gardées là où la catégorie du style les envoie (PP,
    Story me, story typée d'une réserve). Une image déjà présente dans un
    dossier (mêmes octets) n'y est pas recopiée : pousser deux fois ne fait
    pas de doublon côté VA."""
    st = _style(style_id)
    if not st:
        return {"ok": False, "erreur": "Style inconnu."}
    usage = st["usage"]
    u = USAGES[usage]
    if marche not in MARCHES and marche != "tout":
        return {"ok": False, "erreur": "Marché inconnu."}
    if not _pp_branche():
        return {"ok": False, "erreur": "Les dossiers des models ne sont pas branchés sur cette page."}
    possible, raison = pousse_possible(usage)
    if not possible:
        return {"ok": False, "erreur": raison}
    valides = {c["id"].lower(): c["id"] for c in cibles(marche, usage)}   # sans le look : il ne fait que cocher
    demandees = list(dict.fromkeys(str(i or "").strip().lower() for i in (identites or [])[:100]))
    tgts = [valides[x] for x in demandees if x in valides]
    refusees = [x for x in demandees if x and x not in valides]
    if not tgts:
        quoi = "réserve" if u["dest"] == "reserve" else "model"
        return {"ok": False, "erreur": f"Aucune {quoi} cochée."}
    avis = _avis(style_id)
    images, sans_fichier = [], 0
    for k in list(dict.fromkeys(cles or []))[:500]:
        e = avis.get(str(k))
        if not e or e.get("v") != "ok":
            continue
        f = chemin_fichier(style_id, e.get("fichier") or "")
        if f:
            images.append((str(k), f.read_bytes(), f.suffix.lower()))
        else:
            sans_fichier += 1
    if not images:
        return {"ok": False, "erreur": "Aucune image prête : téléchargement en cours ou échoué."}
    empreintes = {k: hashlib.md5(b).hexdigest() for k, b, _ in images}
    ts = _types_story() if u["dest"] == "reserve" else None
    copiees, deja, fait, a_typer = 0, 0, {}, {}
    for t in tgts:
        d = _dossier_dest(t, usage)
        d.mkdir(parents=True, exist_ok=True)
        # comparer par taille d'abord : l'empreinte n'est calculée que pour
        # les fichiers de même taille (un dossier en compte jusqu'à 240)
        par_taille: Dict[int, List[Path]] = {}
        for x in _photos_pp(d):
            par_taille.setdefault(x.stat().st_size, []).append(x)
        for k, b, ext in images:
            meme = next((x for x in par_taille.get(len(b), [])
                         if hashlib.md5(x.read_bytes()).hexdigest() == empreintes[k]), None)
            if meme is not None:
                deja += 1
                fait.setdefault(k, []).append(t)
                a_typer.setdefault(t, []).append(meme.name)   # déjà là, mais peut-être sans type
                continue
            if u["dest"] == "pp":
                # même nommage que /upload/pp et /cloud/pp_apply
                n = len(list(d.glob("*"))) + 1
                cible = d / f"pp_{n}{ext}"
                while cible.exists():
                    n += 1
                    cible = d / f"pp_{n}{ext}"
            else:
                # une story garde un nom lisible et propre à l'image
                cible = d / f"pfp_{k[:17]}{ext}"
                n = 2
                while cible.exists():
                    cible = d / f"pfp_{k[:17]}_{n}{ext}"
                    n += 1
            tmp = d / f".{cible.name}.tmp"
            with open(tmp, "wb") as fh:
                fh.write(b)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, cible)
            par_taille.setdefault(len(b), []).append(cible)
            copiees += 1
            fait.setdefault(k, []).append(t)
            a_typer.setdefault(t, []).append(cible.name)
    erreurs = []
    if ts is not None:
        # sans type, une story de réserve n'est servie par aucun bouton
        for t, noms in a_typer.items():
            try:
                ts.poser(t, noms, usage)
            except Exception as e:
                erreurs.append(f"{t} : type {usage} non posé ({type(e).__name__})")
    with _verrou(style_id):
        frais = _avis(style_id)
        for k, lst in fait.items():
            if k in frais:
                p = frais[k].setdefault("pousse", {})
                p["ids"] = sorted(set(p.get("ids") or []) | set(lst))
        _enregistrer_avis(style_id, frais)
    if copiees and callable(_PP.get("apres")):
        try:
            _PP["apres"]()            # compteurs des menus du site à jour
        except Exception:
            pass
    print(f"[pfp] poussé {u['nom']} ({marche}) : {copiees} copie(s), {deja} déjà là, "
          f"{len(images)} image(s) x {len(tgts)} identité(s)" + (f", {len(erreurs)} erreur(s)" if erreurs else ""),
          flush=True)
    return {"ok": True, "copiees": copiees, "deja": deja, "images": len(images), "models": len(tgts),
            "sans_fichier": sans_fichier, "refusees": refusees, "erreurs": erreurs,
            "gardees": gardees(style_id)}


def etat(style_id: Optional[str] = None) -> Dict[str, Any]:
    lst = styles()
    s = _style(style_id) if style_id else None
    s = s or lst[0]
    usages = {}
    for k, u in USAGES.items():
        possible, raison = pousse_possible(k)
        usages[k] = {c: u[c] for c in ("nom", "emoji", "format", "dest", "unite", "phrase", "idees")}
        usages[k].update(possible=possible, raison=raison)
    return {"styles": [{"id": x["id"], "nom": x["nom"], "usage": x["usage"]} for x in lst], "style": s["id"],
            "usage": s["usage"], "usages": usages, "idees": s.get("idees") or USAGES[s["usage"]]["idees"],
            "recherches": s.get("recherches") or [], "stats": _stats(_avis(s["id"])),
            "gardees": gardees(s["id"]), "modele": etat_modele(), "pp": _pp_branche()}


# ---------------------------------------------------------------- page

def page_html(style_id: Optional[str] = None) -> str:
    try:
        donnees = etat(style_id)
    except Exception as e:
        donnees = {"styles": [], "style": "", "recherches": [], "stats": {"ok": 0, "non": 0},
                   "gardees": [], "modele": {"etat": "erreur", "erreur": f"{type(e).__name__} : {e}"}}
    j = json.dumps(donnees, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE.replace("__DONNEES__", j)


_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Photos de profil</title>
<style>
:root{--fond:#151515;--carte:#222;--bord:#3a3a3a;--texte:#f2f2f2;--faible:#9a9a9a;--bleu:#1677FF;
  --vert:#22c55e;--rouge:#ef4444;--ambre:#f59e0b}
*{box-sizing:border-box}
body{margin:0 auto;background:var(--fond);color:var(--texte);font:14px/1.5 -apple-system,system-ui,sans-serif;
  padding:18px 16px 60px;max-width:1280px}
a{color:#69a7ff}
h1{font-size:20px;margin:0}
.tete{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.tete .retour{color:var(--faible);text-decoration:none;font-size:13px}
.sous{color:var(--faible);font-size:13px;margin:0 0 14px}
.styles{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.chip{padding:6px 12px;border:1px solid var(--bord);border-radius:999px;background:none;color:var(--faible);
  font:inherit;font-size:13px;cursor:pointer}
.chip.on{background:var(--bleu);border-color:var(--bleu);color:#fff}
.chip.petit{padding:3px 10px;font-size:12px}
.barre{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.barre input[type=text]{flex:1 1 280px;min-width:0;padding:11px 14px;border-radius:10px;border:1px solid var(--bord);
  background:#0e0e0e;color:var(--texte);font:inherit;font-size:15px}
.btn{padding:10px 16px;border-radius:10px;border:1px solid var(--bord);background:var(--carte);color:var(--texte);
  font:inherit;font-weight:600;cursor:pointer;white-space:nowrap;text-decoration:none;display:inline-block}
.btn.bleu{background:var(--bleu);border-color:var(--bleu);color:#fff}
.btn:disabled{opacity:.45;cursor:default}
.case{color:var(--faible);font-size:13px;display:flex;gap:6px;align-items:center;cursor:pointer}
.sel{padding:10px 10px;border-radius:10px;border:1px solid var(--bord);background:#0e0e0e;color:var(--texte);font:inherit;
  font-size:13.5px}
.chip.idee{border-style:dashed}
.chip .sep{opacity:.5}
.note-dest{font-size:12.5px;color:var(--ambre);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.4);
  border-radius:10px;padding:8px 12px;margin:0 0 12px}
body.vertical .carte .im{aspect-ratio:9/16}
/* « Tout pousser en Story travel pour MYM » dépassait l'écran d'un téléphone */
.barre .btn{white-space:normal;max-width:100%}
.recentes{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 12px}
.appr{font-size:12.5px;color:var(--faible);background:var(--carte);border:1px solid var(--bord);border-radius:10px;
  padding:8px 12px;margin:0 0 14px}
.appr b{color:var(--texte)}
.ongs{display:flex;gap:2px;border-bottom:1px solid var(--bord);margin:10px 0 14px}
.ong{padding:8px 14px;color:var(--faible);background:none;border:0;border-bottom:2px solid transparent;font:inherit;
  font-size:14px;cursor:pointer}
.ong.on{color:var(--texte);border-bottom-color:var(--bleu);font-weight:600}
.titre-res{font-size:15px;font-weight:700;margin:4px 0 4px}
.infos{color:var(--faible);font-size:12px;margin:0 0 10px}
.err{background:rgba(239,68,68,.12);border:1px solid var(--rouge);border-radius:10px;padding:10px 14px;margin:8px 0;
  font-size:13px}
.grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.carte{background:var(--carte);border:2px solid var(--bord);border-radius:12px;overflow:hidden;display:flex;
  flex-direction:column;transition:opacity .2s}
.carte .im{position:relative;aspect-ratio:1;overflow:hidden;background:#0b0b0b;cursor:zoom-in}
/* en absolu : une image en hauteur ne doit pas agrandir sa case (sans ça,
   toute la ligne de la grille s'étirait et les autres cartes restaient à
   moitié vides) */
.carte .im img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
.carte .top{position:absolute;left:6px;top:6px;background:rgba(22,119,255,.92);color:#fff;font-size:11px;
  font-weight:700;padding:1px 7px;border-radius:999px}
.carte .act{display:flex;gap:6px;padding:6px}
.carte .act button{flex:1;padding:9px 0;border-radius:8px;border:1px solid var(--bord);background:#1a1a1a;
  color:var(--texte);font:inherit;font-weight:700;cursor:pointer}
.carte .act .ok:hover{border-color:var(--vert)} .carte .act .non:hover{border-color:var(--rouge)}
.carte .act .plus{flex:0 0 40px}
.carte.v-ok{border-color:var(--vert)}
.carte.v-non{border-color:var(--rouge);opacity:.45}
.carte .etat{display:none;padding:7px 8px;font-size:12.5px;align-items:center;justify-content:space-between;gap:6px}
.carte.v-ok .etat,.carte.v-non .etat{display:flex}
.carte.v-ok .act,.carte.v-non .act{display:none}
.carte .etat button{background:none;border:0;color:#69a7ff;font:inherit;font-size:12.5px;cursor:pointer;padding:0}
.carte .note{font-size:11.5px;color:var(--ambre);padding:0 8px 7px}
.suite{text-align:center;margin:18px 0}
.replie{margin-top:22px;border-top:1px dashed var(--bord);padding-top:12px}
.vide{color:var(--faible);background:var(--carte);border:1px dashed var(--bord);border-radius:12px;padding:16px;
  font-size:13.5px}
.attente{color:var(--faible);padding:24px 0;text-align:center}
.attente::before{content:"";display:inline-block;width:14px;height:14px;border:2px solid var(--faible);
  border-top-color:transparent;border-radius:50%;margin-right:8px;vertical-align:-2px;animation:t 1s linear infinite}
@keyframes t{to{transform:rotate(360deg)}}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;
  flex-direction:column;gap:10px;z-index:9;padding:16px}
#zoom.on{display:flex}
#zoom img{max-width:min(92vw,900px);max-height:78vh;border-radius:10px}
#zoom .lien{color:#cfd8e3;font-size:13px;max-width:90vw;overflow-wrap:anywhere;text-align:center}
#toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#000;color:#fff;border:1px solid var(--bord);
  padding:9px 16px;border-radius:10px;font-size:13px;display:none;z-index:12;max-width:90vw}
input[type=file]{display:none}
.pousse{display:flex;gap:6px;padding:6px 6px 0}
.pousse button{flex:1;padding:8px 0;border-radius:8px;border:1px solid var(--bord);background:#1a1a1a;color:var(--texte);
  font:inherit;font-size:12.5px;font-weight:700;cursor:pointer}
.pousse button.fait{border-color:var(--vert)}
.pousse button:disabled{opacity:.4;cursor:default}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;
  z-index:11;padding:16px}
#modal[hidden]{display:none}
#modal .boite{background:var(--carte);border:1px solid var(--bord);border-radius:14px;padding:16px;width:min(440px,100%);
  max-height:86vh;display:flex;flex-direction:column;gap:10px}
#modal h3{margin:0;font-size:16px}
#modal .m-sous{color:var(--faible);font-size:12.5px;margin:0}
#modal .m-liste{overflow:auto;border:1px solid var(--bord);border-radius:10px;padding:4px 0;min-height:60px}
.m-ligne{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;font-size:14px}
.m-ligne:hover{background:#1a1a1a}
.m-ligne input{width:18px;height:18px;margin:0}
.m-ligne .m-n{margin-left:auto;color:var(--faible);font-size:12px}
#modal .m-bas{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
@media (max-width:520px){.grille{grid-template-columns:repeat(2,1fr);gap:8px}.btn{padding:10px 12px}}
</style></head><body>
<div class="tete"><a class="retour" href="/">← Dashboard</a><h1>Photos de profil</h1></div>
<p class="sous">Choisis la catégorie, décris l'image, garde (OK) ou écarte (Non) : chaque catégorie apprend tes goûts à part.
Les gardées se poussent en PP ou en story chez les models choisies. Images trouvées sur Pinterest via Yandex et Bing.</p>
<div class="styles" id="styles"></div>
<div class="barre">
  <input type="text" id="q" placeholder="ex. anime girl pink hair pfp, chat noir dessin, cartoon boy cap" autocomplete="off">
  <select id="format" class="sel" title="Forme des images cherchées"><option value="carre">Carré</option>
    <option value="vertical">Vertical (story)</option><option value="tout">Tout format</option></select>
  <button class="btn bleu" id="go">Chercher</button>
  <button class="btn" id="pourtoi" title="Des images proches de celles que tu as gardées">✨ Pour toi</button>
  <button class="btn" id="ajout" title="Les photos que tu utilises déjà : elles apprennent ton style tout de suite">📎 Mes exemples</button>
  <input type="file" id="fichiers" accept="image/*" multiple>
</div>
<div class="recentes" id="recentes"></div>
<div class="appr" id="appr"></div>
<div class="ongs"><button class="ong on" data-o="res">Résultats</button><button class="ong" data-o="garde">Gardées</button></div>
<div id="v-res"><div class="vide">Écris ce que tu cherches (l'anglais rapporte plus d'images Pinterest), ou ajoute 2-3 exemples puis « ✨ Pour toi ».</div></div>
<div id="v-garde" hidden></div>
<div id="zoom"><img alt="" referrerpolicy="no-referrer"><div class="lien"></div></div>
<div id="toast"></div>
<div id="modal" hidden><div class="boite">
  <h3></h3><p class="m-sous"></p>
  <div class="m-liste"></div>
  <div class="m-bas"><button class="btn" id="m-tout">Tout cocher</button><button class="btn" id="m-annuler">Annuler</button>
  <button class="btn bleu" id="m-ok">Pousser</button></div>
</div></div>
<script id="pfp-donnees" type="application/json">__DONNEES__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("pfp-donnees").textContent);
var S = {style: D.style, res: null, req: null, page: 0, occupe: false, stats: D.stats, gardees: D.gardees, modele: D.modele, pp: D.pp};
var U = (D.usages || {})[D.usage] || {nom: "PP", emoji: "🖼", format: "carre", dest: "pp", unite: "PP", phrase: "", idees: [], possible: true};
var DRAPEAUX = {us: "🇺🇸", fr: "🇫🇷"};
var P = {cles: []};
var $ = function(id){ return document.getElementById(id); };

function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]; }); }

function toast(t){ var e = $("toast"); e.textContent = t; e.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(function(){ e.style.display = "none"; }, 3200); }

function post(url, corps){
  return fetch(url, {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "Accept": "application/json"},
    body: JSON.stringify(corps)}).then(function(r){
      return r.json().catch(function(){ return {ok: false, erreur: "Réponse illisible (HTTP " + r.status + ")"}; });
    }).catch(function(){ return {ok: false, erreur: "Le serveur ne répond pas."}; });
}

// une idée : « recherche », ou [libellé affiché, recherche]
function idee(x){ return Array.isArray(x) ? {l: x[0], q: x[1]} : {l: x, q: x}; }

function rendreStyles(){
  var h = D.styles.map(function(s){
    var u = (D.usages || {})[s.usage] || {};
    return "<button class=\"chip" + (s.id === S.style ? " on" : "") + "\" data-s=\"" + esc(s.id) + "\""
      + " title=\"" + esc(u.nom || "") + "\">" + esc((u.emoji ? u.emoji + " " : "") + s.nom) + "</button>";
  }).join("");
  h += "<button class=\"chip\" id=\"nouveau\">＋ Nouveau style</button>";
  h += "<button class=\"chip\" id=\"renommer\" title=\"Renommer le style affiché\">✏️</button>";
  $("styles").innerHTML = h;
  var deja = {};
  var rec = (D.recherches || []).map(function(r){ deja[r.toLowerCase()] = 1;
    return "<button class=\"chip petit\" data-r=\"" + esc(r) + "\">" + esc(r) + "</button>"; });
  // des idées de départ propres à la catégorie, après les recherches déjà faites
  var idees = (D.idees || U.idees || []).map(idee).filter(function(r){ return !deja[r.q.toLowerCase()]; }).map(function(r){
    return "<button class=\"chip petit idee\" data-r=\"" + esc(r.q) + "\" title=\"Cherche : " + esc(r.q) + "\">💡 " + esc(r.l) + "</button>"; });
  $("recentes").innerHTML = rec.concat(idees).join("");
}

function rendreAppr(){
  var m = S.modele || {}, st = S.stats || {ok: 0, non: 0}, t;
  if (m.etat === "pret") {
    t = st.ok + st.non === 0
      ? "Apprentissage prêt : tes premiers OK / Non vont ranger les résultats."
      : "Appris : <b>" + st.ok + " OK</b> · <b>" + st.non + " Non</b>. Les images les plus proches de tes OK passent en premier ; celles qui ressemblent à tes Non sont mises de côté.";
  } else if (m.etat === "telechargement") {
    t = "Le modèle qui apprend ton style se télécharge (" + (m.pct || 0) + " %, une seule fois). Tes OK / Non sont déjà enregistrés et compteront dès qu'il sera prêt.";
  } else {
    t = "Apprentissage indisponible : " + esc(m.erreur || m.etat) + ". La recherche et les OK / Non marchent quand même.";
  }
  $("appr").innerHTML = t;
  $("pourtoi").disabled = !st.ok;
}

function suivreModele(){
  if ((S.modele || {}).etat !== "telechargement") return;
  setTimeout(function(){
    fetch("/pfp/etat?style=" + encodeURIComponent(S.style), {credentials: "same-origin"})
      .then(function(r){ return r.json(); }).then(function(j){ S.modele = j.modele; rendreAppr(); suivreModele(); })
      .catch(function(){ setTimeout(suivreModele, 8000); });
  }, 4000);
}

function carte(c, i){
  var titre = c.titre || "";
  if (c.sp != null || c.sn != null) {
    titre += (titre ? "\n" : "") + "Ressemble à tes OK : " + (c.sp == null ? "—" : Math.round(c.sp * 100) + " %")
      + " · à tes Non : " + (c.sn == null ? "—" : Math.round(c.sn * 100) + " %");
  }
  var top = c.proche ? "<span class=\"top\">★ proche</span>" : "";
  return "<div class=\"carte\" data-cle=\"" + esc(c.cle) + "\" title=\"" + esc(titre) + "\">"
    + "<div class=\"im\"><img loading=\"lazy\" referrerpolicy=\"no-referrer\" src=\"" + esc(c.vign) + "\" alt=\"\">" + top + "</div>"
    + "<div class=\"act\"><button class=\"ok\">✅ OK</button><button class=\"non\">❌ Non</button>"
    + "<button class=\"plus\" title=\"Plus comme ça\">🔁</button></div>"
    + "<div class=\"etat\"><span class=\"lib\"></span><button class=\"annuler\">annuler</button></div></div>";
}

function rendreRes(){
  var r = S.res, h = "";
  if (!r) return;
  h += "<div class=\"titre-res\">" + esc(r.titre) + "</div>";
  var infos = [r.images.length + " image(s)"];
  if (r.classe) infos.push("rangées selon tes goûts");
  if (r.deja_jugees) infos.push(r.deja_jugees + " déjà jugée(s), masquée(s)");
  if (r.doublons) infos.push(r.doublons + " doublon(s) d'images déjà vues, masqué(s)");
  if (r.filigranes) infos.push(r.filigranes + " image(s) de banques d'images (filigrane) écartée(s)");
  if (r.sans_vecteur) infos.push(r.sans_vecteur + " vignette(s) illisible(s), en fin de liste");
  h += "<div class=\"infos\">" + esc(infos.join(" · ")) + "</div>";
  (r.erreurs || []).forEach(function(e){ h += "<div class=\"err\">" + esc(e) + "</div>"; });
  if (!r.images.length && !(r.ecartees || []).length) {
    h += "<div class=\"vide\">Aucune nouvelle image. Essaie d'autres mots" + (S.req && S.req.type === "texte" ? " ou « Charger plus »" : "") + ".</div>";
  }
  h += "<div class=\"grille\" id=\"g-res\">" + r.images.map(carte).join("") + "</div>";
  if (S.req && S.req.type === "texte" && !r.fin) {
    h += "<div class=\"suite\"><button class=\"btn\" id=\"plus\">Charger plus</button></div>";
  } else if (S.req && S.req.type === "pourtoi") {
    h += "<div class=\"suite\"><button class=\"btn\" id=\"encore\">✨ Encore</button></div>";
  }
  if ((r.ecartees || []).length) {
    h += "<div class=\"replie\"><button class=\"btn\" id=\"voir-ec\">Voir " + r.ecartees.length + " image(s) qui ressemblent à tes Non</button>"
      + "<div class=\"grille\" id=\"g-ec\" hidden style=\"margin-top:10px\">" + r.ecartees.map(function(c){ return carte(c, 99); }).join("") + "</div></div>";
  }
  $("v-res").innerHTML = h;
}

function trouver(cle){
  var r = S.res; if (!r) return null;
  var lst = r.images.concat(r.ecartees || []);
  for (var i = 0; i < lst.length; i++) if (lst[i].cle === cle) return lst[i];
  return null;
}

function lancer(req){
  if (S.occupe) return;
  S.occupe = true; S.req = req;
  var ajout = req.page > 0;
  if (!ajout) $("v-res").innerHTML = "<div class=\"attente\">" + (req.type === "texte" ? "Recherche…" : "Recherche d'images proches de tes gardées (jusqu'à 30 s)…") + "</div>";
  else { var b = $("plus"); if (b) { b.disabled = true; b.textContent = "Chargement…"; } }
  montrer("res");
  var url = req.type === "texte" ? "/pfp/chercher" : (req.type === "pourtoi" ? "/pfp/pour-toi" : "/pfp/similaires");
  post(url, {style: S.style, q: req.q, page: req.page, format: $("format").value, cle: req.cle, meta: req.meta}).then(function(j){
    S.occupe = false;
    if (!j.ok) {
      if (ajout) { toast(j.erreur || "Erreur"); rendreRes(); }
      else $("v-res").innerHTML = "<div class=\"err\">" + esc(j.erreur || "Erreur") + "</div>";
      return;
    }
    if (ajout && S.res) {
      var vus = {}; S.res.images.concat(S.res.ecartees || []).forEach(function(c){ vus[c.cle] = 1; });
      S.res.images = S.res.images.concat(j.images.filter(function(c){ return !vus[c.cle]; }));
      S.res.ecartees = (S.res.ecartees || []).concat((j.ecartees || []).filter(function(c){ return !vus[c.cle]; }));
      S.res.fin = j.fin; S.res.erreurs = j.erreurs; S.res.doublons += j.doublons; S.res.deja_jugees += j.deja_jugees;
      S.res.filigranes = (S.res.filigranes || 0) + (j.filigranes || 0);
      S.res.classe = S.res.classe || j.classe;
    } else { S.res = j; }
    if (req.type === "texte" && req.page === 0) ajouterRecente(req.q);
    rendreRes();
  });
}

function ajouterRecente(q){
  D.recherches = [q].concat((D.recherches || []).filter(function(x){ return x.toLowerCase() !== q.toLowerCase(); })).slice(0, 12);
  rendreStyles();
}

function juger(el, v){
  var cle = el.getAttribute("data-cle"), c = trouver(cle) || {};
  el.classList.remove("v-ok", "v-non");
  if (v !== "annuler") el.classList.add("v-" + v);
  el.querySelector(".lib").textContent = v === "ok" ? "✅ Gardée" : "❌ Non";
  post("/pfp/avis", {style: S.style, cle: cle, v: v, meta: c}).then(function(j){
    if (!j.ok) { el.classList.remove("v-ok", "v-non"); toast(j.erreur || "Pas enregistré"); return; }
    S.stats = j.stats; rendreAppr();
    if (v === "ok" || v === "annuler") rafraichirGardees();
  });
}

function rafraichirGardees(){
  fetch("/pfp/etat?style=" + encodeURIComponent(S.style), {credentials: "same-origin"})
    .then(function(r){ return r.json(); }).then(function(j){
      S.gardees = j.gardees; S.stats = j.stats; S.modele = j.modele; rendreAppr(); rendreGardees();
      if (S.gardees.some(function(g){ return g.en_cours; })) { clearTimeout(rafraichirGardees.t); rafraichirGardees.t = setTimeout(rafraichirGardees, 3000); }
    }).catch(function(){});
}

function carteGardee(x){
  var src = x.fichier ? "/pfp/fichier/" + encodeURIComponent(S.style) + "/" + encodeURIComponent(x.fichier) : x.vign;
  var bas;
  if (x.fichier) bas = "<a href=\"" + esc(src) + "\" download>⬇️ Télécharger</a>";
  else if (x.echec) bas = "<span>Original introuvable</span> <button class=\"reessayer\">réessayer</button>";
  else bas = "<span>Téléchargement…</span>";
  var ex = x.src === "exemple";
  return "<div class=\"carte v-ok\" data-cle=\"" + esc(x.cle) + "\" title=\"" + esc(x.titre) + "\">"
    + "<div class=\"im\"><img loading=\"lazy\" referrerpolicy=\"no-referrer\" src=\"" + esc(src) + "\" alt=\"\"></div>"
    + (ex ? "" : "<div class=\"pousse\"><button class=\"p-un" + (x.pousse_n ? " fait" : "") + "\"" + (x.fichier && U.possible ? "" : " disabled")
      + " title=\"" + esc(!U.possible ? U.raison : (x.pousse_n ? "Déjà chez " + x.pousse_n + " model(s)" : "Pousser en " + U.nom)) + "\">"
      + (x.pousse_n ? "📤 Poussée ✓ (" + x.pousse_n + ")" : "📤 Pousser") + "</button></div>")
    + "<div class=\"etat\" style=\"display:flex\">" + bas + "<button class=\"retirer\">retirer</button></div>"
    + "</div>";
}

function rendreGardees(){
  var tout = S.gardees || [];
  // les exemples (photos déjà chez les models) apprennent le style ; ils ne
  // se mélangent pas aux trouvailles et ne repartent pas avec « Tout pousser »
  var g = tout.filter(function(x){ return x.src !== "exemple"; });
  var ex = tout.filter(function(x){ return x.src === "exemple"; });
  var h = "";
  if (!U.possible) h += "<div class=\"note-dest\">" + esc(U.raison) + "</div>";
  if (!g.length && !ex.length) { $("v-garde").innerHTML = h + "<div class=\"vide\">Rien de gardé dans ce style pour l'instant.</div>"; majOnglets(); return; }
  var off = U.possible ? "" : " disabled title=\"" + esc(U.raison) + "\"";
  h += "<div class=\"barre\"><a class=\"btn bleu\" href=\"/pfp/zip/" + encodeURIComponent(S.style) + "\">⬇️ Tout télécharger (.zip)</a>"
    + "<button class=\"btn pousser-tout\"" + off + ">📤 Tout pousser en " + esc(U.nom) + "</button></div>";
  h += g.length ? "<div class=\"grille\">" + g.map(carteGardee).join("") + "</div>"
    : "<div class=\"vide\">Aucune trouvaille gardée pour l'instant : cherche, puis ✅ OK.</div>";
  if (ex.length) {
    h += "<div class=\"replie\"><button class=\"btn\" id=\"voir-ex\">Exemples du style (" + ex.length + ") : tes photos de départ</button>"
      + "<div class=\"grille\" id=\"g-ex\" hidden style=\"margin-top:10px\">" + ex.map(carteGardee).join("") + "</div></div>";
  }
  $("v-garde").innerHTML = h;
  majOnglets();
}

function lireMemo(){
  try { var v = JSON.parse(localStorage.getItem("pfp-cibles-" + S.style) || "null"); return Array.isArray(v) ? v : null; }
  catch (e) { return null; }
}
function ecrireMemo(ids){ try { localStorage.setItem("pfp-cibles-" + S.style, JSON.stringify(ids)); } catch (e) {} }

function cochees(){
  return Array.prototype.slice.call(document.querySelectorAll("#modal .m-liste input:checked")).map(function(i){ return i.value; });
}
function majCompte(){
  var n = cochees().length, b = $("m-ok");
  b.disabled = !n;
  var quoi = U.dest === "reserve" ? "réserve" : "model";
  b.textContent = n ? "Pousser vers " + n + " " + quoi + "(s)" : "Coche au moins une " + quoi;
}

function ouvrirPousser(cles){
  if (!S.pp) { toast("Les dossiers des models ne sont pas branchés sur cette page."); return; }
  if (!U.possible) { toast(U.raison); return; }
  if (!cles.length) { toast("Aucune image prête : attends la fin du téléchargement."); return; }
  P.cles = cles;
  var md = $("modal"), liste = md.querySelector(".m-liste");
  md.querySelector("h3").textContent = "📤 Pousser en " + U.emoji + " " + U.nom;
  md.querySelector(".m-sous").textContent = cles.length + " image(s) à copier " + U.phrase + " Une image déjà présente n'est pas recopiée.";
  liste.innerHTML = "<div class=\"attente\">Chargement…</div>";
  $("m-ok").disabled = true;
  md.hidden = false;
  fetch("/pfp/cibles?marche=tout&style=" + encodeURIComponent(S.style), {credentials: "same-origin"}).then(function(r){ return r.json(); }).then(function(j){
    var lst = j.cibles || [], memo = lireMemo();
    if (!lst.length) {
      liste.innerHTML = "<div class=\"vide\">Aucune " + (U.dest === "reserve" ? "réserve" : "model") + " pour " + esc(U.nom) + ".</div>";
      majCompte(); return;
    }
    liste.innerHTML = lst.map(function(x){
      var coche = memo ? memo.indexOf(x.id) >= 0 : x.coche;
      return "<label class=\"m-ligne\"><input type=\"checkbox\" value=\"" + esc(x.id) + "\"" + (coche ? " checked" : "") + ">"
        + "<span>" + (DRAPEAUX[x.marche] || "") + " " + esc(x.id) + "</span><span class=\"m-n\">" + (x.look ? x.look + " du style · " : "") + x.n + " " + esc(U.unite) + "</span></label>";
    }).join("");
    majCompte();
  }).catch(function(){ liste.innerHTML = "<div class=\"err\">Liste des models illisible.</div>"; });
}

function fermerPousser(){ $("modal").hidden = true; }

function lancerPousser(){
  var ids = cochees(), b = $("m-ok");
  if (!ids.length) return;
  ecrireMemo(ids);
  b.disabled = true; b.textContent = "Copie…";
  post("/pfp/pousser", {style: S.style, cles: P.cles, marche: "tout", identites: ids}).then(function(j){
    if (!j.ok) { toast(j.erreur || "Rien n'a été poussé"); majCompte(); return; }
    fermerPousser();
    var t = "✅ " + j.copiees + " copie(s) en " + U.nom + " chez " + j.models + " "
      + (U.dest === "reserve" ? "réserve(s)" : "model(s)");
    if (j.deja) t += " · " + j.deja + " déjà là";
    if (j.sans_fichier) t += " · " + j.sans_fichier + " image(s) pas encore téléchargée(s), ignorée(s)";
    if ((j.erreurs || []).length) t += " · ⚠️ " + j.erreurs.join(" ; ");
    toast(t);
    if (j.gardees) { S.gardees = j.gardees; rendreGardees(); }
  });
}

function majOnglets(){
  document.querySelector(".ong[data-o=garde]").textContent = "Gardées (" + (S.gardees || []).filter(function(x){ return x.src !== "exemple"; }).length + ")";
}

function montrer(o){
  document.querySelectorAll(".ong").forEach(function(b){ b.classList.toggle("on", b.getAttribute("data-o") === o); });
  $("v-res").hidden = o !== "res"; $("v-garde").hidden = o !== "garde";
}

function zoom(src, lien){
  var z = $("zoom"); z.querySelector("img").src = src;
  z.querySelector(".lien").innerHTML = lien ? "<a href=\"" + esc(lien) + "\" target=\"_blank\" rel=\"noopener noreferrer\">Voir la source</a>" : "";
  z.classList.add("on");
}

function changerStyle(id){
  location.href = "/pfp?style=" + encodeURIComponent(id);
}

document.addEventListener("click", function(ev){
  var t = ev.target, el;
  if (t.closest("#zoom")) { if (!t.closest("a")) $("zoom").classList.remove("on"); return; }
  if ((el = t.closest(".chip[data-s]"))) { if (el.getAttribute("data-s") !== S.style) changerStyle(el.getAttribute("data-s")); return; }
  if ((el = t.closest(".chip[data-r]"))) { $("q").value = el.getAttribute("data-r"); lancer({type: "texte", q: $("q").value, page: 0}); return; }
  if (t.id === "nouveau") {
    var nom = prompt("Nom du nouveau style (il partira en " + U.emoji + " " + U.nom + ", comme celui affiché) :");
    if (nom) post("/pfp/style", {action: "creer", nom: nom, usage: D.usage}).then(function(j){ if (j.ok) changerStyle(j.style.id); else toast(j.erreur || "Erreur"); });
    return;
  }
  if (t.id === "renommer") {
    var cur = D.styles.filter(function(s){ return s.id === S.style; })[0] || {};
    var n2 = prompt("Nouveau nom :", cur.nom || "");
    if (n2) post("/pfp/style", {action: "renommer", id: S.style, nom: n2}).then(function(j){ if (j.ok) location.reload(); else toast(j.erreur || "Erreur"); });
    return;
  }
  if ((el = t.closest(".ong"))) { var o = el.getAttribute("data-o"); montrer(o); if (o === "garde") rafraichirGardees(); return; }
  if (t.id === "plus") { lancer({type: "texte", q: S.req.q, page: S.req.page + 1}); return; }
  if (t.id === "encore") { lancer({type: "pourtoi", page: 0}); return; }
  if (t.id === "voir-ec") { var g = $("g-ec"); g.hidden = !g.hidden; return; }
  if (t.id === "voir-ex") { var gx = $("g-ex"); gx.hidden = !gx.hidden; return; }
  if (t.closest("#modal")) {
    if (t.id === "m-annuler" || t.id === "modal") fermerPousser();
    else if (t.id === "m-ok") lancerPousser();
    else if (t.id === "m-tout") {
      var cases = document.querySelectorAll("#modal .m-liste input"), toutes = cochees().length === cases.length;
      cases.forEach(function(i){ i.checked = !toutes; }); majCompte();
    } else if (t.closest(".m-ligne")) setTimeout(majCompte, 0);
    return;
  }
  if ((el = t.closest(".pousser-tout"))) {
    ouvrirPousser((S.gardees || []).filter(function(x){ return x.fichier && x.src !== "exemple"; }).map(function(x){ return x.cle; }));
    return;
  }
  var c = t.closest(".carte");
  if (!c) return;
  if (t.closest(".im")) {
    var x = trouver(c.getAttribute("data-cle"));
    var im = c.querySelector("img");
    zoom(x ? (x.img || x.vign) : im.src, x ? x.page : "");
    return;
  }
  if (t.closest("#v-garde")) {
    if (t.classList.contains("p-un")) { ouvrirPousser([c.getAttribute("data-cle")]); return; }
    if (t.classList.contains("retirer")) {
      if (!confirm("Retirer cette image des gardées ? Elle part dans la corbeille du style ; les copies déjà poussées aux models restent.")) return;
      post("/pfp/avis", {style: S.style, cle: c.getAttribute("data-cle"), v: "annuler"}).then(function(j){
        if (j.ok) { S.stats = j.stats; rendreAppr(); rafraichirGardees(); } else toast(j.erreur || "Erreur"); });
    } else if (t.classList.contains("reessayer")) {
      post("/pfp/reessayer", {style: S.style, cle: c.getAttribute("data-cle")}).then(function(){ setTimeout(rafraichirGardees, 1500); });
    }
    return;
  }
  if (t.classList.contains("ok")) juger(c, "ok");
  else if (t.classList.contains("non")) juger(c, "non");
  else if (t.classList.contains("annuler")) juger(c, "annuler");
  else if (t.classList.contains("plus")) {
    var m = trouver(c.getAttribute("data-cle"));
    lancer({type: "similaires", page: 0, cle: c.getAttribute("data-cle"), meta: m});
  }
});

$("go").addEventListener("click", function(){
  var q = $("q").value.trim(); if (!q) { $("q").focus(); return; }
  lancer({type: "texte", q: q, page: 0});
});
$("q").addEventListener("keydown", function(e){ if (e.key === "Enter") $("go").click(); });
$("pourtoi").addEventListener("click", function(){ lancer({type: "pourtoi", page: 0}); });
$("ajout").addEventListener("click", function(){ $("fichiers").click(); });
$("fichiers").addEventListener("change", function(){
  var f = $("fichiers").files; if (!f.length) return;
  var fd = new FormData(); fd.append("style", S.style);
  for (var i = 0; i < f.length; i++) fd.append("images", f[i]);
  toast("Envoi de " + f.length + " exemple(s)…");
  fetch("/pfp/exemples", {method: "POST", credentials: "same-origin", body: fd, headers: {"Accept": "application/json"}})
    .then(function(r){ return r.json(); }).then(function(j){
      $("fichiers").value = "";
      if (!j.ok) { toast(j.erreur || "Envoi refusé"); return; }
      S.stats = j.stats; rendreAppr();
      toast(j.ajoutes + " exemple(s) ajouté(s)" + (j.refuses.length ? ", " + j.refuses.length + " refusé(s) (pas une image)" : ""));
      rafraichirGardees();
    }).catch(function(){ toast("Envoi impossible"); });
});

$("format").value = U.format || "carre";
document.body.classList.toggle("vertical", U.format === "vertical");
var ID0 = D.idees || U.idees || [];
if (ID0.length) $("q").placeholder = "ex. " + ID0.slice(0, 3).map(function(x){ return idee(x).q; }).join(", ");
rendreStyles(); rendreAppr(); rendreGardees(); suivreModele();
})();
</script>
</body></html>
"""


# ---------------------------------------------------------------- routes

def register(app, is_auth, is_admin, pp: Optional[Dict[str, Any]] = None):
    """Routes /pfp/*. Admin seulement : la page télécharge sur le serveur et
    écrit dans data/. Les POST viennent de la page elle-même (Sec-Fetch-Site),
    en plus du cookie SameSite=Lax de la session.

    `pp` : ce que le site prête pour « Pousser pour OF / MYM » — identites()
    (la liste des identités), marche(id) (« fr » / « us »), nature(id)
    (« modele » / « identite » / « reserve »), dossier(id) (son dossier de
    photos de profil ; stories/ est son voisin) et apres() (rafraîchir ses
    compteurs)."""
    from flask import Response, jsonify, redirect, request, send_file
    if pp:
        _PP.update(pp)

    def _refus_lecture():
        if not is_auth():
            return redirect("/")
        if not is_admin():
            return Response("Réservé à l'administration.", status=403, mimetype="text/plain")
        return None

    def _refus_ecriture():
        if not is_auth() or not is_admin():
            return jsonify({"ok": False, "erreur": "Réservé à l'administration."}), 403
        if (request.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
            return jsonify({"ok": False, "erreur": "Envoi refusé : il ne vient pas de la page."}), 403
        return None

    def _corps() -> Dict[str, Any]:
        j = request.get_json(silent=True)
        return j if isinstance(j, dict) else {}

    def _json(d, code=200):
        r = jsonify(d)
        r.status_code = code
        r.headers["Cache-Control"] = "no-store"
        return r

    def _protege(fn):
        try:
            return _json(fn())
        except Exception as e:
            # une panne s'affiche sur la page, pas en page blanche
            print(f"[pfp] {request.path} : {type(e).__name__} : {e}", flush=True)
            return _json({"ok": False, "erreur": f"{type(e).__name__} : {e}"[:300]}, 500)

    @app.route("/pfp")
    def pfp_page():
        refus = _refus_lecture()
        if refus is not None:
            return refus
        r = Response(page_html(request.args.get("style")), mimetype="text/html")
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Robots-Tag"] = "noindex, nofollow"
        return r

    @app.route("/pfp/etat")
    def pfp_etat():
        refus = _refus_lecture()
        if refus is not None:
            return _json({"ok": False}, 403)
        return _protege(lambda: dict(etat(request.args.get("style")), ok=True))

    @app.route("/pfp/chercher", methods=["POST"])
    def pfp_chercher():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        return _protege(lambda: chercher(str(c.get("style") or ""), str(c.get("q") or ""),
                                         int(c.get("page") or 0), c.get("format")))

    @app.route("/pfp/pour-toi", methods=["POST"])
    def pfp_pour_toi():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        return _protege(lambda: pour_toi(str(c.get("style") or "")))

    @app.route("/pfp/similaires", methods=["POST"])
    def pfp_similaires():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        return _protege(lambda: similaires(str(c.get("style") or ""), str(c.get("cle") or ""),
                                           c.get("meta") or {}))

    @app.route("/pfp/avis", methods=["POST"])
    def pfp_avis():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        return _protege(lambda: juger(str(c.get("style") or ""), str(c.get("cle") or ""),
                                      str(c.get("v") or ""), c.get("meta") or {}))

    @app.route("/pfp/reessayer", methods=["POST"])
    def pfp_reessayer():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        return _protege(lambda: reessayer(str(c.get("style") or ""), str(c.get("cle") or "")))

    @app.route("/pfp/exemples", methods=["POST"])
    def pfp_exemples():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        fichiers = [(f.filename or "", f.read(MAX_IMAGE + 1)) for f in request.files.getlist("images")]
        return _protege(lambda: ajouter_exemples(str(request.form.get("style") or ""), fichiers))

    @app.route("/pfp/style", methods=["POST"])
    def pfp_style():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()

        def _faire():
            if c.get("action") == "creer":
                return {"ok": True, "style": creer_style(str(c.get("nom") or ""), str(c.get("usage") or "pp"))}
            if c.get("action") == "renommer":
                return {"ok": renommer_style(str(c.get("id") or ""), str(c.get("nom") or ""))}
            return {"ok": False, "erreur": "Action inconnue."}
        return _protege(_faire)

    @app.route("/pfp/cibles")
    def pfp_cibles():
        refus = _refus_lecture()
        if refus is not None:
            return _json({"ok": False}, 403)
        m = str(request.args.get("marche") or "")
        st = _style(str(request.args.get("style") or "")) or {}
        u = st.get("usage") or "pp"
        return _protege(lambda: {"ok": True, "marche": m, "nom": MARCHES.get(m, ""), "usage": u,
                                 "cibles": cibles(m, u, st.get("id"))})

    @app.route("/pfp/pousser", methods=["POST"])
    def pfp_pousser():
        refus = _refus_ecriture()
        if refus is not None:
            return refus
        c = _corps()
        cles = c.get("cles") if isinstance(c.get("cles"), list) else []
        ids = c.get("identites") if isinstance(c.get("identites"), list) else []
        return _protege(lambda: pousser(str(c.get("style") or ""), [str(x) for x in cles],
                                        str(c.get("marche") or ""), [str(x) for x in ids]))

    @app.route("/pfp/fichier/<style_id>/<nom>")
    def pfp_fichier(style_id, nom):
        refus = _refus_lecture()
        if refus is not None:
            return refus
        p = chemin_fichier(style_id, nom)
        if not p:
            return Response("Introuvable.", status=404, mimetype="text/plain")
        return send_file(p, max_age=3600)

    @app.route("/pfp/zip/<style_id>")
    def pfp_zip(style_id):
        refus = _refus_lecture()
        if refus is not None:
            return refus
        z = archive_zip(style_id)
        if not z:
            return Response("Style inconnu.", status=404, mimetype="text/plain")
        return send_file(io.BytesIO(z[0]), mimetype="application/zip", as_attachment=True,
                         download_name=z[1])
