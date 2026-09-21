"""hiker_reels.py — Resout les video_url des reels via HikerAPI.

HikerAPI rend, en UN SEUL appel par reel, ce que la chaine precedente
demandait a deux fournisseurs : l'URL video (qu'on payait a Apify) et les
vues, la legende, la date (qu'on payait a RapidAPI). Le telechargement des
octets, lui, reste un simple GET sur le CDN Instagram : gratuit.

Pourquoi ce module plutot qu'Apify :
  - Apify facture ~2,30 $ / 1 000 resultats, HikerAPI 0,001 $ / requete ;
  - le solde HikerAPI est PREPAYE et n'expire jamais, la ou un quota
    mensuel laissait le parc aveugle des qu'il etait epuise ;
  - l'actor Apify refuse le lot ENTIER en HTTP 400 des qu'une URL est en
    double, ce qui bloquait des lots complets de 18 videos.

Le jeton est stocke dans data/hiker_config.json (gitignore, VPS
uniquement). JAMAIS commite — meme regle que le jeton Apify.

Mesure du 21/09/2026 : /v1/media/by/code rend video_url, play_count,
caption_text et le proprietaire sur un reel reel du parc.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import requests

import safe_json

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "hiker_config.json"
BASE = "https://api.hikerapi.com"

# Un appel par reel : on parallelise pour que resoudre un lot de 18 ne
# prenne pas 18 fois le temps d'un seul. 4 suffit, HikerAPI n'impose pas
# de limite serree a ce volume et on ne cherche pas a le brusquer.
_OUVRIERS = 4


def _load() -> dict:
    try:
        d = safe_json.load_or_prev(CONFIG_FILE)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(CONFIG_FILE, json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def save_token(token: str):
    d = _load()
    d["token"] = (token or "").strip()
    _save(d)


def get_token() -> str:
    return (_load().get("token") or "").strip()


def configured() -> bool:
    return bool(get_token())


def shortcode(url: str) -> str:
    """Le code du reel dans son lien, ou "" si le lien n'en contient pas."""
    m = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_\-]+)", url or "")
    return m.group(1) if m else ""


def _url_video(media: dict) -> str:
    """L'URL du mp4, quelle que soit la forme rendue.

    HikerAPI expose video_url a plat, mais garde aussi video_versions (la
    forme d'Instagram). On lit les deux plutot que de parier sur l'une.
    """
    direct = (media.get("video_url") or "").strip()
    if direct:
        return direct
    versions = media.get("video_versions") or []
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        return (versions[0].get("url") or "").strip()
    return ""


def _legende(media: dict) -> str:
    leg = media.get("caption_text") or ""
    if not leg and isinstance(media.get("caption"), dict):
        leg = media["caption"].get("text") or ""
    return str(leg or "").strip()


def _un_reel(code: str, token: str, timeout: int) -> tuple:
    """Resout UN reel. Rend (code, fiche) ou (code, None)."""
    try:
        r = requests.get(BASE + "/v1/media/by/code",
                         headers={"x-access-key": token, "Accept": "application/json"},
                         params={"code": code}, timeout=timeout)
    except Exception:
        return code, None
    if r.status_code != 200:
        return code, None
    try:
        data = r.json()
    except ValueError:
        return code, None
    media = data.get("media") if isinstance(data.get("media"), dict) else data
    if not isinstance(media, dict):
        return code, None
    lien = _url_video(media)
    if not lien:
        return code, None
    vues = media.get("play_count")
    if vues is None:
        vues = media.get("view_count")
    return code, {
        "video_url": lien,
        "caption": _legende(media),
        "likes": media.get("like_count") or 0,
        "comments": media.get("comment_count") or 0,
        "owner": (media.get("user") or {}).get("username") or "",
        "views": vues,
    }


def fetch_video_urls(reel_urls: List[str], timeout: int = 240,
                     diag: Dict[str, Any] = None) -> Dict[str, Dict[str, Any]]:
    """Resout une liste de liens reels. MEME CONTRAT que apify_reels.

    Rend {shortcode: {video_url, caption, likes, comments, owner, views}}.
    `diag`, s'il est fourni, recoit {sent, status, resolved, error} comme
    chez Apify : l'appelant peut ainsi retomber sur ses autres methodes
    sans savoir quelle source a repondu.
    """
    token = get_token()
    # Deduplication : deux liens identiques dans le meme lot resoudraient
    # deux fois le meme reel et seraient factures deux fois. dict.fromkeys
    # preserve l'ordre d'origine, contrairement a set().
    codes = list(dict.fromkeys(
        c for c in (shortcode(u) for u in (reel_urls or []) if u) if c))
    if diag is not None:
        diag.update({"sent": len(codes), "status": None, "resolved": 0, "error": ""})
    if not token or not codes:
        if diag is not None:
            diag["error"] = "jeton ou liens absents"
        return {}

    # Le timeout recu vaut pour TOUT le lot chez Apify (un run batch). Ici
    # chaque reel est un appel : on le repartit, avec un plancher pour ne
    # pas couper une reponse lente sur un petit lot.
    par_appel = max(20, int(timeout / max(1, len(codes) / _OUVRIERS)))

    out: Dict[str, Dict[str, Any]] = {}
    try:
        with ThreadPoolExecutor(max_workers=_OUVRIERS) as ex:
            for code, fiche in ex.map(lambda c: _un_reel(c, token, par_appel), codes):
                if fiche:
                    out[code] = fiche
    except Exception as e:
        if diag is not None:
            diag["error"] = str(e)[:180]
        return out

    if diag is not None:
        diag["status"] = 200 if out else 404
        diag["resolved"] = len(out)
        if not out:
            diag["error"] = "aucun reel resolu"
    return out


def test_token() -> dict:
    """Verifie le jeton sans consommer de requete de resolution."""
    token = get_token()
    if not token:
        return {"ok": False, "error": "jeton absent"}
    try:
        r = requests.get(BASE + "/v1/user/by/username",
                         headers={"x-access-key": token, "Accept": "application/json"},
                         params={"username": "instagram"}, timeout=30)
    except Exception as e:
        return {"ok": False, "error": str(e)[:180]}
    if r.status_code == 200:
        return {"ok": True}
    # 402 = solde epuise : le jeton est bon, c'est le credit qui manque.
    if r.status_code == 402:
        return {"ok": False, "error": "solde HikerAPI epuise"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:120]}"}
