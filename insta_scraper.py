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
    if auth.get("csrftoken"):
        L.context._session.cookies.set("csrftoken", auth["csrftoken"], domain=".instagram.com")
    L.context._session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    # Marquer comme connecté (sinon instaloader refuse certaines requêtes)
    L.context.username = auth.get("username") or "_session_user_"
    return L


def scrape_profile(username: str, limit: int = 12) -> dict:
    """Scrape un profil : profil info + N derniers posts.

    Retourne {"profile": {...}, "reels": [...], "scraped_at": timestamp}
    ou {"error": "message"}
    """
    if not INSTALOADER_OK:
        return {"error": "instaloader pas installé (auto-pull devrait l'installer)"}
    username = _clean_username(username)
    if not username:
        return {"error": "username vide"}
    L = _make_loader()
    if L is None:
        return {"error": "Aucune session configurée (Settings → Instagram)"}
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
            time.sleep(0.6)  # rate-limit defensif
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
    except instaloader.exceptions.ConnectionException as e:
        return {"error": f"Erreur connexion (rate-limit ?) : {e}"}
    except Exception as e:
        log.error(f"Scrape {username} échoué: {e}")
        return {"error": f"Erreur: {type(e).__name__}: {e}"}


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
