"""Scraper Instagram via instaloader + session cookies.
Stocke watchlist + cache des reels dans data/insta/.
"""
import os
import json
import time
import logging
from pathlib import Path
from typing import List, Optional

try:
    import instaloader
    INSTALOADER_OK = True
except ImportError:
    INSTALOADER_OK = False

log = logging.getLogger("vabot.insta")

DATA_DIR = Path("data")
INSTA_DIR = DATA_DIR / "insta"
AUTH_FILE = INSTA_DIR / "auth.json"
WATCHLIST_FILE = INSTA_DIR / "watchlist.json"
CACHE_DIR = INSTA_DIR / "cache"


def _ensure_dirs():
    INSTA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============ AUTH ============

def load_auth() -> dict:
    if not AUTH_FILE.exists():
        return {}
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_auth(data: dict):
    _ensure_dirs()
    AUTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(AUTH_FILE, 0o600)
    except Exception:
        pass


def is_auth_configured() -> bool:
    a = load_auth()
    return bool(a.get("sessionid"))


def auth_status() -> str:
    a = load_auth()
    if not a.get("sessionid"):
        return "❌ Non configuré"
    sid = a["sessionid"]
    return f"✅ Session active (sessionid {sid[:8]}...{sid[-4:]})"


# ============ WATCHLIST ============

def load_watchlist() -> List[str]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_watchlist(usernames: List[str]):
    _ensure_dirs()
    WATCHLIST_FILE.write_text(
        json.dumps(usernames, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def add_to_watchlist(username: str) -> bool:
    username = _clean_username(username)
    if not username:
        return False
    wl = load_watchlist()
    if username in wl:
        return False
    wl.append(username)
    save_watchlist(wl)
    return True


def remove_from_watchlist(username: str) -> bool:
    username = _clean_username(username)
    wl = load_watchlist()
    if username not in wl:
        return False
    wl.remove(username)
    save_watchlist(wl)
    return True


def _clean_username(u: str) -> str:
    return (u or "").lower().strip().replace("@", "").rstrip("/").split("/")[-1]


# ============ SCRAPER ============

def _make_loader() -> Optional["instaloader.Instaloader"]:
    if not INSTALOADER_OK:
        return None
    auth = load_auth()
    sessionid = auth.get("sessionid")
    if not sessionid:
        return None
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        max_connection_attempts=2,
        request_timeout=15,
    )
    # Inject cookies
    L.context._session.cookies.set("sessionid", sessionid, domain=".instagram.com")
    if auth.get("ds_user_id"):
        L.context._session.cookies.set("ds_user_id", auth["ds_user_id"], domain=".instagram.com")
    csrftoken = auth.get("csrftoken", "")
    if csrftoken:
        L.context._session.cookies.set("csrftoken", csrftoken, domain=".instagram.com")
    # Headers CRITIQUES pour eviter 400 Bad Request sur GraphQL
    L.context._session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "X-IG-App-ID": "936619743392459",  # OBLIGATOIRE depuis update Insta 2024
        "X-Requested-With": "XMLHttpRequest",
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "Origin": "https://www.instagram.com",
        "Referer": "https://www.instagram.com/",
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    if csrftoken:
        L.context._session.headers["X-CSRFToken"] = csrftoken
    # Marquer comme connecté (sinon instaloader refuse certaines requêtes)
    L.context.username = auth.get("username") or "_session_user_"
    return L


def _scrape_via_web_api(username: str, limit: int) -> dict:
    """Scrape via API web Instagram (plus stable que GraphQL ces derniers temps)."""
    import requests
    auth = load_auth()
    sessionid = auth.get("sessionid")
    if not sessionid:
        return {"error": "Aucune session"}
    s = requests.Session()
    s.cookies.set("sessionid", sessionid, domain=".instagram.com")
    if auth.get("ds_user_id"):
        s.cookies.set("ds_user_id", auth["ds_user_id"], domain=".instagram.com")
    csrftoken = auth.get("csrftoken", "")
    if csrftoken:
        s.cookies.set("csrftoken", csrftoken, domain=".instagram.com")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"https://www.instagram.com/{username}/",
    }
    if csrftoken:
        headers["X-CSRFToken"] = csrftoken
    # 1) Profil info via endpoint web_profile_info
    try:
        r = s.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers=headers,
            timeout=15,
        )
        if r.status_code == 404:
            return {"error": f"Profil @{username} introuvable"}
        if r.status_code != 200:
            return {"error": f"Erreur profil: HTTP {r.status_code}"}
        data = r.json()
        user = data.get("data", {}).get("user", {})
        if not user:
            return {"error": "Réponse profil vide"}
    except Exception as e:
        return {"error": f"Erreur fetch profil: {e}"}

    profile_data = {
        "username": user.get("username", username),
        "full_name": user.get("full_name", ""),
        "followers": user.get("edge_followed_by", {}).get("count", 0),
        "following": user.get("edge_follow", {}).get("count", 0),
        "posts_count": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url", ""),
        "biography": (user.get("biography") or "")[:300],
        "is_private": user.get("is_private", False),
        "is_verified": user.get("is_verified", False),
    }

    # 2) Posts via les edges déjà dans la réponse profil
    edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])
    reels = []
    for edge in edges[:limit]:
        node = edge.get("node", {})
        try:
            caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""
            shortcode = node.get("shortcode", "")
            is_video = node.get("is_video", False)
            reel = {
                "shortcode": shortcode,
                "is_video": is_video,
                "views": node.get("video_view_count") if is_video else None,
                "likes": node.get("edge_liked_by", {}).get("count")
                    or node.get("edge_media_preview_like", {}).get("count", 0),
                "comments": node.get("edge_media_to_comment", {}).get("count", 0),
                "caption": caption[:280],
                "thumbnail_url": node.get("display_url", ""),
                "video_url": node.get("video_url") if is_video else None,
                "date": "",
                "url": f"https://www.instagram.com/p/{shortcode}/",
            }
            reels.append(reel)
        except Exception as e:
            log.warning(f"Parse post: {e}")

    result = {
        "profile": profile_data,
        "reels": reels,
        "scraped_at": time.time(),
    }
    _ensure_dirs()
    (CACHE_DIR / f"{username}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def scrape_profile(username: str, limit: int = 12) -> dict:
    """Scrape un profil : profil info + N derniers posts.

    Tente d'abord l'API web (plus stable), puis fallback sur instaloader.
    """
    username = _clean_username(username)
    if not username:
        return {"error": "username vide"}
    auth = load_auth()
    if not auth.get("sessionid"):
        return {"error": "Aucune session configurée (Settings → Instagram)"}

    # Tentative 1 : API web directe (plus fiable)
    result = _scrape_via_web_api(username, limit)
    if "error" not in result:
        return result
    web_error = result["error"]

    # Tentative 2 : instaloader en fallback
    if not INSTALOADER_OK:
        return {"error": f"API web KO: {web_error}"}
    L = _make_loader()
    if L is None:
        return {"error": f"API web KO ({web_error}) + instaloader KO"}
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        reels = []
        count = 0
        for post in profile.get_posts():
            if count >= limit:
                break
            try:
                reel = {
                    "shortcode": post.shortcode,
                    "is_video": post.is_video,
                    "views": post.video_view_count if post.is_video else None,
                    "likes": post.likes,
                    "comments": post.comments,
                    "caption": (post.caption or "")[:280],
                    "thumbnail_url": post.url,
                    "video_url": post.video_url if post.is_video else None,
                    "date": post.date_local.isoformat(),
                    "url": f"https://www.instagram.com/p/{post.shortcode}/",
                }
                reels.append(reel)
                count += 1
            except Exception as e:
                log.warning(f"Erreur lecture post {post.shortcode}: {e}")
            time.sleep(0.6)
        result = {
            "profile": {
                "username": profile.username,
                "full_name": profile.full_name,
                "followers": profile.followers,
                "following": profile.followees,
                "posts_count": profile.mediacount,
                "profile_pic_url": profile.profile_pic_url,
                "biography": (profile.biography or "")[:300],
                "is_private": profile.is_private,
                "is_verified": profile.is_verified,
            },
            "reels": reels,
            "scraped_at": time.time(),
        }
        _ensure_dirs()
        (CACHE_DIR / f"{username}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result
    except instaloader.exceptions.ProfileNotExistsException:
        return {"error": f"Profil @{username} introuvable"}
    except instaloader.exceptions.LoginRequiredException:
        return {"error": "Session expirée — recharge les cookies dans Settings"}
    except Exception as e:
        return {"error": f"API web KO ({web_error}) + instaloader: {type(e).__name__}: {e}"}


def get_cached(username: str) -> Optional[dict]:
    f = CACHE_DIR / f"{_clean_username(username)}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_all_cached_reels() -> list:
    """Retourne tous les reels en cache (toutes plateformes), chacun avec son _owner."""
    out = []
    if not CACHE_DIR.exists():
        return out
    for f in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            owner = data.get("profile", {}).get("username", f.stem)
            owner_profile = data.get("profile", {})
            scraped = data.get("scraped_at", 0)
            for r in data.get("reels", []):
                r["_owner"] = owner
                r["_owner_full_name"] = owner_profile.get("full_name", "")
                r["_owner_followers"] = owner_profile.get("followers", 0)
                r["_owner_pp"] = owner_profile.get("profile_pic_url", "")
                r["_scraped_at"] = scraped
                out.append(r)
        except Exception as e:
            log.error(f"Lecture cache {f}: {e}")
    return out


def watchlist_status() -> list:
    """Liste enrichie : username + last_scrape + nb_reels."""
    wl = load_watchlist()
    out = []
    for u in wl:
        data = get_cached(u)
        if data:
            out.append({
                "username": u,
                "scraped_at": data.get("scraped_at", 0),
                "nb_reels": len(data.get("reels", [])),
                "followers": data.get("profile", {}).get("followers", 0),
                "full_name": data.get("profile", {}).get("full_name", ""),
            })
        else:
            out.append({
                "username": u,
                "scraped_at": 0,
                "nb_reels": 0,
                "followers": 0,
                "full_name": "",
            })
    return out
