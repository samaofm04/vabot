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
    if not _consommer(len(codes)):
        e = budget_du_jour()
        if diag is not None:
            diag["error"] = ("enveloppe du jour epuisee (%d/%d)"
                             % (e["utilise"], e["plafond"]))
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


# ── SCRAPE D'UN PROFIL ENTIER ─────────────────────────────────────────────
# Sert de REPLI quand RapidAPI tombe (quota epuise, panne). Rend exactement
# la meme forme que _scrape_via_rapidapi : {profile, reels, scraped_at}.
# Sans ce repli, une seule source epuisee arretait toute la collecte — c'est
# ce qui a rendu le parc aveugle 19 jours en septembre 2026.

_PK_FILE = DATA_DIR / "hiker_pk.json"
_BUDGET_FILE = DATA_DIR / "hiker_budget.json"

# ENVELOPPE QUOTIDIENNE, en requetes.
#
# HikerAPI se paie sur un solde prepaye : rien ne s'arrete tout seul quand
# on depense trop, le solde descend jusqu'a zero et la collecte meurt d'un
# coup. C'est exactement ce qui est arrive avec le quota RapidAPI, brule en
# neuf jours pour trois semaines d'aveuglement.
#
# 1500 requetes par jour = 1,50 $/jour = ~45 $/mois : un solde de 130 $ tient
# pres de trois mois. La veille (59 comptes une fois par jour) en consomme 59,
# le reste sert de repli quand RapidAPI tombe.
#
# Ce plafond n'est PAS une optimisation, c'est un garde-fou : au-dela, on
# refuse et on le DIT, plutot que de vider le solde en silence.
PLAFOND_JOUR = 1500


def _aujourdhui() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


def budget_du_jour() -> dict:
    """{jour, utilise, plafond, restant} — lisible pour l'afficher."""
    try:
        d = safe_json.load_or_prev(_BUDGET_FILE)
        d = d if isinstance(d, dict) else {}
    except Exception:
        d = {}
    jour = _aujourdhui()
    utilise = int(d.get("utilise") or 0) if d.get("jour") == jour else 0
    return {"jour": jour, "utilise": utilise, "plafond": PLAFOND_JOUR,
            "restant": max(0, PLAFOND_JOUR - utilise)}


def _consommer(combien: int) -> bool:
    """Reserve `combien` requetes. Faux si l'enveloppe du jour est epuisee.

    On reserve AVANT d'appeler, pas apres : compter apres coup laisserait
    passer une rafale entiere avant que le compteur ne s'en apercoive.
    """
    etat = budget_du_jour()
    if etat["restant"] < combien:
        return False
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_BUDGET_FILE, json.dumps(
            {"jour": etat["jour"], "utilise": etat["utilise"] + combien},
            ensure_ascii=False))
    except Exception:
        pass
    return True


def _pk_cache() -> dict:
    try:
        d = safe_json.load_or_prev(_PK_FILE)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pk_retenir(username: str, pk) -> None:
    """L'identifiant numerique d'un compte ne change JAMAIS.

    Le retenir supprime un appel sur deux : /v1/user/clips veut un user_id,
    pas un pseudo. A 774 comptes deux fois par jour, c'est 46 000 requetes
    economisees par mois.
    """
    if not username or not pk:
        return
    d = _pk_cache()
    if str(d.get(username) or "") == str(pk):
        return
    d[username] = str(pk)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_PK_FILE, json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def _horodatage(valeur) -> int:
    """taken_at arrive en ISO 8601 ; taken_at_ts en secondes. Les deux existent."""
    if valeur is None:
        return 0
    if isinstance(valeur, (int, float)):
        return int(valeur)
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(
            str(valeur).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _appel(chemin: str, token: str, timeout: int, **params):
    try:
        r = requests.get(BASE + chemin,
                         headers={"x-access-key": token, "Accept": "application/json"},
                         params=params, timeout=timeout)
    except Exception as e:
        return None, str(e)[:160]
    if r.status_code != 200:
        return None, "HTTP %s: %s" % (r.status_code, r.text[:140])
    try:
        return r.json(), ""
    except ValueError:
        return None, "reponse non-JSON"


def scrape_profile(username: str, limit: int = 50) -> dict:
    """Profil + reels recents. Meme contrat que _scrape_via_rapidapi."""
    token = get_token()
    username = (username or "").strip().lstrip("@").lower()
    if not token:
        return {"error": "HikerAPI: jeton absent"}
    if not username:
        return {"error": "HikerAPI: username vide"}

    pk = _pk_cache().get(username) or ""
    # DEUX APPELS, TOUJOURS.
    #
    # J'avais d'abord saute l'appel profil quand le pk etait deja connu,
    # pour economiser une requete. C'etait faux : le profil ne porte pas
    # que le pk, il porte les ABONNES, la PHOTO DE PROFIL et la bio. Sans
    # lui le scrape rendait {followers: 0, profile_pic_url: ""} et les
    # cartes s'affichaient sans avatar. _write_cache rattrapait en gardant
    # l'ancienne valeur, mais un compte jamais releve restait vide, et le
    # compteur d'abonnes de tous les autres cessait d'etre mis a jour.
    if not _consommer(2):
        e = budget_du_jour()
        return {"error": "HikerAPI: enveloppe du jour epuisee (%d/%d requetes). "
                         "Le solde est preserve ; la collecte reprend demain."
                         % (e["utilise"], e["plafond"])}

    data, err = _appel("/v1/user/by/username", token, 45, username=username)
    if err:
        # Un pk deja connu permet de tenter les reels quand meme : mieux
        # vaut des vues sans compteur d'abonnes que rien du tout.
        if not pk:
            return {"error": "HikerAPI: " + err}
        user = {}
    else:
        user = data.get("user") if isinstance(data.get("user"), dict) else (data or {})
        pk = user.get("pk") or user.get("id") or pk
        if not pk:
            return {"error": "HikerAPI: compte sans identifiant (introuvable ?)"}
        _pk_retenir(username, pk)

    data, err = _appel("/v1/user/clips", token, 60, user_id=pk)
    if err:
        # Un pk devenu invalide (compte renomme) : on oublie le cache pour
        # que le prochain passage reparte du pseudo plutot que de s'entetuer.
        if "404" in err or "400" in err:
            d = _pk_cache()
            d.pop(username, None)
            try:
                safe_json.write_text(_PK_FILE, json.dumps(d, ensure_ascii=False))
            except Exception:
                pass
        return {"error": "HikerAPI: " + err}

    items = data if isinstance(data, list) else (
        (data or {}).get("items") or ((data or {}).get("response") or {}).get("items") or [])

    reels = []
    for it in items[:limit]:
        m = it.get("media") if isinstance(it.get("media"), dict) else it
        if not isinstance(m, dict):
            continue
        code = m.get("code") or m.get("shortcode") or ""
        vues = m.get("play_count")
        if vues is None:
            vues = m.get("view_count")
        reels.append({
            "shortcode": code,
            "is_video": True,          # /v1/user/clips ne rend que des videos
            "views": vues,
            "likes": m.get("like_count") or 0,
            "comments": m.get("comment_count") or 0,
            "caption": _legende(m)[:280],
            "thumbnail_url": m.get("thumbnail_url") or "",
            "video_url": _url_video(m),
            "taken_at": _horodatage(m.get("taken_at_ts") or m.get("taken_at")),
            "date": "",
            "url": "https://www.instagram.com/p/%s/" % code if code else "",
        })

    profil = {
        "username": user.get("username") or username,
        "full_name": user.get("full_name") or "",
        "followers": user.get("follower_count") or 0,
        "following": user.get("following_count") or 0,
        "posts_count": user.get("media_count") or 0,
        "profile_pic_url": (user.get("profile_pic_url_hd")
                            or user.get("profile_pic_url") or ""),
        "biography": (user.get("biography") or "")[:300],
        "is_private": bool(user.get("is_private")),
        "is_verified": bool(user.get("is_verified")),
    }

    import time as _t
    return {"profile": profil, "reels": reels, "scraped_at": _t.time()}
