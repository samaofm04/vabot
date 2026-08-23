"""veille_tiktok.py — Veille TikTok : les meilleures vidéos d'un compte.

**Séparé de `veille.py`**, qui stocke les reels Instagram mis en favori à la
main. Ici on part d'un *compte* concurrent et on redescend ses meilleures
vidéos, classées par performance. Deux besoins différents, deux fichiers de
données différents : `data/veille_tiktok.json` ne croise jamais
`data/veille_reels.json`.

## Pourquoi Apify et pas yt-dlp

Le même constat que `veille_telegram.py` a déjà fait pour Instagram, vérifié le
22/08/2026 sur TikTok : yt-dlp se fait jeter. TikTok répond **HTTP 200 avec un
corps vide** (yt-dlp l'annonce en « Failed to parse JSON », ce qui envoie vers
un faux diagnostic), et la page profil revient truffée de marqueurs `captcha` /
`blocked` / `Slardar`, l'anti-bot de ByteDance. Apify scrape avec SES proxies :
zéro cookie, zéro compte de l'agence exposé, pas de 429.

## Ce que ça coûte

L'actor est facturé **0,005 $ par résultat**. Le tri `popular` est appliqué
*côté Apify* : pour avoir le top 30 d'un compte on demande 30 résultats, pas
200 qu'on trierait ensuite. Un compte = ~0,15 $. Les filtres de date et le
téléchargement des vidéos sont des options facturées en plus — d'où
`avec_video=False` par défaut.

## Les quatre classements

    vues      la portée brute — ce que le compte a fait de plus gros
    taux      (likes + commentaires + partages) / vues — la qualité du contenu
    surperf   vues / vues médianes DU COMPTE — ce qui a percé pour lui
    recent    vues par jour depuis la publication — ce qui monte maintenant

`surperf` est celui qui sert à s'inspirer : une vidéo à 200 k vues sur un
compte qui plafonne à 20 k est un signal ; la même sur un compte à 2 M n'en est
aucun. Le tri par vues brutes ne fait que remonter les gros comptes.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

import apify_reels
import safe_json

DATA_DIR = Path("data")
STORE = DATA_DIR / "veille_tiktok.json"

#: Même forme que les reels Instagram (`data/insta/videos/<shortcode>.mp4`),
#: pour qu'il n'y ait qu'une convention à connaître dans le projet.
VIDEOS_DIR = DATA_DIR / "tiktok" / "videos"

#: 114 M de runs, c'est le scraper TikTok de référence sur Apify.
ACTOR = "clockworks~tiktok-scraper"
BASE = "https://api.apify.com/v2"

#: En dessous de ce nombre de vues, le taux d'engagement ne veut rien dire :
#: 3 likes sur 5 vues font 60 %, ce qui trusterait tout le haut du classement.
SEUIL_TAUX = 500

TRIS = ("vues", "taux", "surperf", "recent")


# --------------------------------------------------------------- stockage --

def configured() -> bool:
    """Le token Apify est partagé avec `apify_reels` : un seul à renseigner."""
    return apify_reels.configured()


def _load() -> Dict[str, Any]:
    try:
        d = safe_json.load_or_prev(STORE)
        if not isinstance(d, dict):
            return {"videos": {}}
        d.setdefault("videos", {})
        return d
    except Exception:
        return {"videos": {}}


def _save(d: Dict[str, Any]) -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return safe_json.write(STORE, d)
    except Exception:
        return False


# ------------------------------------------------------------ collecte --

def _nombre(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _texte(x) -> str:
    """Une URL, qu'elle arrive en chaîne ou en liste.

    L'actor rend `videoMeta.coverUrl` en chaîne mais `covers` en liste selon
    les versions : normaliser ici évite de traîner le doute partout ailleurs.
    """
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, (list, tuple)):
        for e in x:
            if isinstance(e, str) and e.strip():
                return e.strip()
    return ""


def _date(item: Dict[str, Any]) -> str:
    """La date de publication, en AAAA-MM-JJ."""
    iso = (item.get("createTimeISO") or "").strip()
    if len(iso) >= 10:
        return iso[:10]
    ts = _nombre(item.get("createTime"))
    if ts:
        try:
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            pass
    return ""


def fiche(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Un résultat brut de l'actor -> une fiche à nous.

    On ne garde que ce qui sert au classement et à l'affichage. Le reste du
    payload (musique, effets, sous-titres) est volumineux et inutile ici.
    """
    if not isinstance(item, dict):
        return None
    vid = str(item.get("id") or "").strip()
    if not vid:
        return None
    auteur = item.get("authorMeta") or {}
    video = item.get("videoMeta") or {}
    medias = [u for u in (item.get("mediaUrls") or []) if u]
    return {
        "id": vid,
        "compte": (auteur.get("name") or "").strip(),
        "nom_affiche": (auteur.get("nickName") or "").strip(),
        "url": (item.get("webVideoUrl") or "").strip(),
        "titre": " ".join((item.get("text") or "").split())[:400],
        "date": _date(item),
        "duree": _nombre(video.get("duration")),
        "vues": _nombre(item.get("playCount")),
        "likes": _nombre(item.get("diggCount")),
        "commentaires": _nombre(item.get("commentCount")),
        "partages": _nombre(item.get("shareCount")),
        "favoris": _nombre(item.get("collectCount")),
        "couverture": _texte(video.get("coverUrl")) or _texte(item.get("covers")),
        "video_url": medias[0] if medias else "",
        "releve_le": datetime.now().isoformat(timespec="seconds"),
    }


def collecter(comptes: List[str], par_compte: int = 30, tri: str = "popular",
              depuis_jours: int = 0, avec_video: bool = False,
              timeout: int = 300,
              diag: Optional[Dict[str, Any]] = None
              ) -> Tuple[List[Dict[str, Any]], str]:
    """Interroge Apify et rend (fiches, erreur).

    `tri` est le tri demandé **à Apify** : "popular", "latest" ou "oldest".
    C'est lui qui décide ce qu'on paye — "popular" avec par_compte=30 coûte 30
    résultats, là où récupérer tout un compte pour le trier soi-même en
    coûterait des centaines.

    `diag` (optionnel) est rempli comme dans `apify_reels.fetch_video_urls` :
    {sent, status, resolved, error}. L'appelant peut ainsi afficher pourquoi
    ça n'a rien donné sans deviner.
    """
    comptes = [str(c or "").strip().lstrip("@") for c in (comptes or [])]
    comptes = [c for c in comptes if c]
    if diag is not None:
        diag.update({"sent": len(comptes), "status": None, "resolved": 0,
                     "error": ""})
    if not comptes:
        return [], "aucun compte"

    tok = apify_reels.get_token()
    if not tok:
        msg = "Aucun token Apify (Réglages -> Token API Apify)"
        if diag is not None:
            diag["error"] = msg
        return [], msg

    corps: Dict[str, Any] = {
        "profiles": comptes,
        "resultsPerPage": max(1, int(par_compte)),
        "profileSorting": tri if tri in ("popular", "latest", "oldest")
                          else "popular",
        "profileScrapeSections": ["videos"],
        "shouldDownloadVideos": bool(avec_video),
        "shouldDownloadCovers": True,
        "shouldDownloadAvatars": False,
        "shouldDownloadSlideshowImages": False,
        "shouldDownloadMusicCovers": False,
    }
    if depuis_jours and depuis_jours > 0:
        # Option facturée en plus : on ne la pose que si elle est demandée.
        corps["oldestPostDateUnified"] = (
            datetime.now(timezone.utc) - timedelta(days=int(depuis_jours))
        ).strftime("%Y-%m-%d")

    try:
        r = requests.post(
            f"{BASE}/acts/{ACTOR}/run-sync-get-dataset-items?token={tok}",
            json=corps, timeout=timeout)
        if diag is not None:
            diag["status"] = r.status_code
        if r.status_code not in (200, 201):
            msg = f"HTTP {r.status_code}: {r.text[:180]}"
            if diag is not None:
                diag["error"] = msg
            return [], msg
        items = r.json()
        if not isinstance(items, list):
            msg = f"réponse inattendue: {str(items)[:180]}"
            if diag is not None:
                diag["error"] = msg
            return [], msg
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:150]}"
        if diag is not None:
            diag["error"] = msg
        return [], msg

    fiches = []
    for it in items:
        f = fiche(it)
        # Un compte inexistant fait rendre à l'actor un item d'erreur sans id :
        # `fiche` le refuse, on ne le compte donc pas comme un résultat.
        if f and f.get("compte"):
            fiches.append(f)
    if diag is not None:
        diag["resolved"] = len(fiches)
    return fiches, "" if fiches else "aucune vidéo (compte privé ou vide ?)"


def enregistrer(fiches: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Fusionne dans le magasin. Rend (nouvelles, mises à jour).

    Les compteurs d'une vidéo bougent avec le temps : un relevé plus récent
    écrase l'ancien. Mais on garde `video_fichier` s'il existait déjà — une
    vidéo téléchargée ne doit pas être perdue par un simple rafraîchissement.
    """
    d = _load()
    vids = d["videos"]
    neuf = maj = 0
    for f in fiches or []:
        cle = str(f.get("id") or "")
        if not cle:
            continue
        ancienne = vids.get(cle)
        if ancienne:
            for garde in ("video_fichier", "vu_par", "note"):
                if ancienne.get(garde) and not f.get(garde):
                    f[garde] = ancienne[garde]
            maj += 1
        else:
            neuf += 1
        vids[cle] = f
    _save(d)
    return neuf, maj


# --------------------------------------------------------- fichiers video --

def chemin_video(vid: str) -> Path:
    return VIDEOS_DIR / f"{str(vid or '').strip()}.mp4"


def a_le_fichier(vid: str) -> bool:
    """Vrai si la vidéo est sur le disque et non tronquée."""
    try:
        p = chemin_video(vid)
        return p.exists() and p.stat().st_size > 1024
    except Exception:
        return False


def rapatrier(fiches: List[Dict[str, Any]], timeout: int = 120) -> Tuple[int, int]:
    """Descend les mp4 depuis Apify. Rend (téléchargées, échecs).

    Les `video_url` viennent du magasin de clés Apify, rempli quand la collecte
    a tourné avec `avec_video=True`. **Ces URL expirent** : on rapatrie donc
    dans la foulée de la collecte, jamais des jours plus tard. Passé ce délai,
    il faut relancer une collecte — d'où le fait qu'on ne réessaie pas tout
    seul une URL morte, ça ne ferait que perdre du temps.

    On ne passe jamais par le CDN de TikTok : c'est précisément lui qui bloque.
    """
    ok = rate = 0
    for f in fiches or []:
        vid = str(f.get("id") or "")
        url = (f.get("video_url") or "").strip()
        if not vid or not url:
            continue
        if a_le_fichier(vid):
            ok += 1
            continue
        cible = chemin_video(vid)
        try:
            VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
            r = requests.get(url, stream=True, timeout=timeout)
            if r.status_code != 200:
                r.close()
                rate += 1
                continue
            # Fichier temporaire puis renommage : une coupure en plein
            # téléchargement laisserait sinon un mp4 tronqué que
            # `a_le_fichier` prendrait pour bon.
            tmp = cible.with_suffix(".mp4.part")
            with tmp.open("wb") as fh:
                for bloc in r.iter_content(chunk_size=65536):
                    if bloc:
                        fh.write(bloc)
            r.close()
            if tmp.stat().st_size > 1024:
                tmp.replace(cible)
                ok += 1
                _marquer_fichier(vid)
            else:
                tmp.unlink(missing_ok=True)
                rate += 1
        except Exception:
            try:
                cible.with_suffix(".mp4.part").unlink(missing_ok=True)
            except Exception:
                pass
            rate += 1
    return ok, rate


def _marquer_fichier(vid: str) -> None:
    d = _load()
    f = d["videos"].get(str(vid))
    if isinstance(f, dict):
        f["video_fichier"] = True
        _save(d)


# ------------------------------------------------------------ classement --

def _age_jours(f: Dict[str, Any]) -> Optional[float]:
    d = (f.get("date") or "").strip()
    if not d:
        return None
    try:
        pub = datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        return None
    return max(1.0, float((datetime.now() - pub).days))


def medianes(vids: Dict[str, Any]) -> Dict[str, float]:
    """Vues médianes par compte — le dénominateur de `surperf`."""
    par: Dict[str, List[int]] = {}
    for f in (vids or {}).values():
        if isinstance(f, dict) and f.get("vues"):
            par.setdefault(f.get("compte") or "", []).append(f["vues"])
    return {k: float(statistics.median(v)) for k, v in par.items() if v}


def scores(f: Dict[str, Any], meds: Dict[str, float]) -> Dict[str, Any]:
    vues = f.get("vues") or 0
    inter = sum(f.get(k) or 0
                for k in ("likes", "commentaires", "partages", "favoris"))
    taux = (inter / vues) if vues >= SEUIL_TAUX else None
    med = meds.get(f.get("compte") or "")
    surperf = (vues / med) if (med and vues) else None
    age = _age_jours(f)
    return {
        "vues": vues or None,
        "taux": taux,
        "surperf": surperf,
        "recent": (vues / age) if (age and vues) else None,
    }


def classer(tri: str = "vues", n: int = 20, comptes: Optional[List[str]] = None,
            depuis: Optional[int] = None, min_vues: int = 0
            ) -> List[Dict[str, Any]]:
    """Classe ce qui est déjà en magasin. Ne coûte aucune requête."""
    if tri not in TRIS:
        tri = "vues"
    vids = _load().get("videos", {})
    meds = medianes(vids)
    vise = {str(c or "").strip().lstrip("@").lower()
            for c in (comptes or []) if str(c or "").strip()}
    borne = None
    if depuis:
        borne = (datetime.now() - timedelta(days=int(depuis))).date()

    retenues = []
    for f in vids.values():
        if not isinstance(f, dict):
            continue
        if vise and (f.get("compte") or "").lower() not in vise:
            continue
        if min_vues and (f.get("vues") or 0) < min_vues:
            continue
        if borne is not None:
            d = (f.get("date") or "").strip()
            if not d:
                continue
            try:
                if datetime.strptime(d, "%Y-%m-%d").date() < borne:
                    continue
            except ValueError:
                continue
        s = scores(f, meds)
        if s.get(tri) is None:
            continue
        g = dict(f)
        g["scores"] = s
        retenues.append(g)

    retenues.sort(key=lambda g: g["scores"][tri], reverse=True)
    return retenues[:n] if n else retenues


def comptes_suivis() -> List[Dict[str, Any]]:
    """Les comptes présents en magasin, avec leur volume et leur médiane."""
    vids = _load().get("videos", {})
    meds = medianes(vids)
    par: Dict[str, int] = {}
    for f in vids.values():
        if isinstance(f, dict) and f.get("compte"):
            par[f["compte"]] = par.get(f["compte"], 0) + 1
    return sorted(
        ({"compte": c, "videos": n, "vues_medianes": meds.get(c, 0)}
         for c, n in par.items()),
        key=lambda d: -d["videos"])


def oublier_compte(compte: str) -> int:
    """Retire toutes les vidéos d'un compte. Rend le nombre retiré."""
    cible = str(compte or "").strip().lstrip("@").lower()
    if not cible:
        return 0
    d = _load()
    avant = len(d["videos"])
    d["videos"] = {k: v for k, v in d["videos"].items()
                   if not (isinstance(v, dict)
                           and (v.get("compte") or "").lower() == cible)}
    retires = avant - len(d["videos"])
    if retires:
        _save(d)
    return retires
