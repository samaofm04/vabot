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
    return bool(a.get("sessionid") or a.get("rapidapi_key"))


def auth_status() -> str:
    a = load_auth()
    parts = []
    if a.get("rapidapi_key"):
        k = a["rapidapi_key"]
        host = a.get("rapidapi_host", "instagram-scraper-stable-api.p.rapidapi.com")
        parts.append(f"✅ RapidAPI activé ({k[:6]}...{k[-4:]} via {host})")
    if a.get("sessionid"):
        sid = a["sessionid"]
        parts.append(f"✅ Session cookie ({sid[:8]}...{sid[-4:]})")
    if not parts:
        return "❌ Non configuré (ni RapidAPI ni cookies)"
    return " — ".join(parts)


# ============ WATCHLIST ============

def load_watchlist() -> List[str]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_watchlist(usernames: List[str]):
    # Écriture ATOMIQUE (temp + replace) : un crash en plein write ne tronque plus
    # le fichier (sinon load_watchlist renvoyait [] et un add écrasait toute la liste).
    _ensure_dirs()
    tmp = WATCHLIST_FILE.with_suffix(WATCHLIST_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(usernames, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(WATCHLIST_FILE))


def rebuild_watchlist_from_cache() -> int:
    """Récupère les comptes depuis les fichiers de cache (data/insta/cache/*.json)
    et les FUSIONNE dans la watchlist. Répare une watchlist vidée/corrompue sans
    perdre les comptes déjà scrapés. Retourne le nombre de comptes récupérés."""
    if not CACHE_DIR.exists():
        return 0
    wl = load_watchlist()
    existing = {(u or "").lower().strip() for u in wl}
    added = 0
    for f in CACHE_DIR.glob("*.json"):
        name = f.stem.lower().strip()
        if name and name not in existing:
            wl.append(name)
            existing.add(name)
            added += 1
    if added:
        save_watchlist(wl)
    return added


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
    # Nettoie aussi le cache reels du compte (sinon ses reels resteraient
    # dans get_all_cached_reels() / la page Trends).
    try:
        (CACHE_DIR / f"{username}.json").unlink(missing_ok=True)
    except Exception:
        pass
    return True


def _clean_username(u: str) -> str:
    return (u or "").lower().strip().replace("@", "").rstrip("/").split("/")[-1]


# Instagram epoch en millisecondes (2011-08-24 21:07:01 UTC)
INSTAGRAM_EPOCH_MS = 1314220021721


def _timestamp_from_pk(pk) -> int:
    """Extrait le timestamp Unix (secondes) depuis un pk Instagram.

    Le pk encode le timestamp en ms dans ses 41 bits hauts (shift de 23).
    """
    try:
        pk_int = int(pk)
        ts_ms = (pk_int >> 23) + INSTAGRAM_EPOCH_MS
        return ts_ms // 1000
    except Exception:
        return 0


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


def _scrape_via_rapidapi_single_post(shortcode: str) -> dict:
    """Fetch un POST UNIQUE via RapidAPI (endpoint specific shortcode).
    Tente plusieurs noms d'endpoints car Stable API les a changes plusieurs fois.

    Retourne {video_url, shortcode} ou {} si tout echoue.
    """
    import requests
    auth = load_auth()
    api_key = auth.get("rapidapi_key", "").strip()
    if not api_key:
        return {}
    host = auth.get("rapidapi_host", "instagram-scraper-stable-api.p.rapidapi.com").strip()
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": host,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    base = f"https://{host}"
    # Endpoints possibles (essai dans l'ordre)
    endpoints = [
        "/ig_get_post_info_v2.php",
        "/ig_get_post_info.php",
        "/get_ig_post_info.php",
        "/get_ig_media_info.php",
        "/get_ig_media_info_v2.php",
        "/ig_get_media_info.php",
    ]
    candidates = []
    for ep in endpoints:
        try:
            r = requests.post(
                f"{base}{ep}",
                headers=headers,
                data={"shortcode": shortcode, "code_or_id_or_url": shortcode},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            try:
                body = r.json()
            except Exception:
                continue
            # Cherche video_url dans le body avec _extract_video_url
            def walk(node, depth=0):
                if depth > 6 or not isinstance(node, (dict, list)):
                    return
                if isinstance(node, dict):
                    # Direct keys
                    for k in ("video_url", "playback_url", "playable_url",
                              "playable_url_quality_hd"):
                        v = node.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            candidates.append(v)
                    vv = node.get("video_versions") or []
                    if isinstance(vv, list):
                        for x in vv:
                            if isinstance(x, dict):
                                u = x.get("url") or x.get("src")
                                if isinstance(u, str) and u.startswith("http"):
                                    candidates.append(u)
                    for sub in node.values():
                        walk(sub, depth + 1)
                elif isinstance(node, list):
                    for it in node:
                        walk(it, depth + 1)
            walk(body)
            if candidates:
                return {"video_url": candidates[0], "shortcode": shortcode}
        except Exception:
            continue
    return {}


def _scrape_ig_page_for_video(shortcode: str) -> str:
    """Fallback SANS API ni owner : scrape les pages /p/ et /embed/ pour un
    video_url (plusieurs User-Agents + regex). Retourne "" si rien trouve.
    (Copie self-contained du helper de web_upload pour rester utilisable ici.)
    """
    if not shortcode:
        return ""
    import requests as _rq
    import re as _re
    urls_to_try = [
        f"https://www.instagram.com/p/{shortcode}/embed/captioned/",
        f"https://www.instagram.com/p/{shortcode}/embed/",
        f"https://www.instagram.com/reel/{shortcode}/embed/",
        f"https://www.instagram.com/p/{shortcode}/",
        f"https://www.instagram.com/reel/{shortcode}/",
    ]
    user_agents = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Mozilla/5.0 (compatible; Twitterbot/1.0)",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    patterns = [
        r'"video_url"\s*:\s*"([^"]+)"',
        r'"playable_url"\s*:\s*"([^"]+)"',
        r'"playable_url_quality_hd"\s*:\s*"([^"]+)"',
        r'"video_versions"\s*:\s*\[\s*\{[^}]*"url"\s*:\s*"([^"]+)"',
        r'<meta\s+property="og:video"\s+content="([^"]+)"',
        r'<meta\s+property="og:video:secure_url"\s+content="([^"]+)"',
        r'<meta\s+name="twitter:player:stream"\s+content="([^"]+)"',
        r'src=\"(https://[^\"]*\.mp4[^\"]*)\"',
        r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
    ]
    for url in urls_to_try:
        for ua in user_agents:
            try:
                r = _rq.get(
                    url,
                    headers={
                        "User-Agent": ua,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                html = r.text
                for pat in patterns:
                    for m in _re.finditer(pat, html):
                        u = m.group(1)
                        try:
                            u = u.encode().decode("unicode_escape")
                        except Exception:
                            pass
                        u = u.replace("&amp;", "&").replace("\\/", "/")
                        if not u.startswith("http"):
                            continue
                        u_low = u.lower()
                        if ".m3u8" in u_low or ".mpd" in u_low:
                            continue
                        if any(ext in u_low for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                            continue
                        if ".mp4" in u_low or "fcdn.net/v/" in u_low or "cdninstagram.com/v/" in u_low:
                            return u
            except Exception:
                continue
    return ""


def get_video_url_for_shortcode(shortcode: str, owner_username: str = "") -> dict:
    """Resout un video_url FRAIS pour un reel/post a partir de son shortcode.

    Cascade IDENTIQUE a celle (eprouvee) de /insta/proxy_video, la 1ere qui
    rend une video gagne :
      1) **Reels du proprietaire** via scrape_profile(owner, limit=500) —
         l'endpoint /get_ig_user_reels.php alimente les stats tous les jours
         donc CONFIRME fiable. limit=500 pour couvrir aussi les vieux reels.
      2) Endpoint RapidAPI "post unique" (rapide mais fragile, souvent vide).
      3) Scrape direct de la page IG /p/ et /embed/ (SANS API ni owner).

    `owner_username` = le @compte source (stocke dans chaque reel de veille).
    Retourne {"video_url": str, "source": str, "trace": [str, ...]} ; video_url
    vide si rien trouve. La trace sert au diagnostic (remontee dans l'alerte UI).
    """
    trace = []
    sc = (shortcode or "").strip()
    if not sc:
        return {"video_url": "", "source": "", "trace": ["pas_de_shortcode"]}
    # 1) Reels du proprietaire (endpoint fiable) -> matche le shortcode
    owner = (owner_username or "").lstrip("@").strip()
    if owner:
        try:
            data = scrape_profile(owner, limit=500)
            if isinstance(data, dict) and not data.get("error"):
                reels = data.get("reels") or []
                for r in reels:
                    if (r.get("shortcode") or "") == sc and (r.get("video_url") or "").strip():
                        return {"video_url": r["video_url"], "source": "owner_reels",
                                "trace": trace + [f"owner_reels:match({len(reels)})"]}
                trace.append(f"owner_reels:pas_de_match({len(reels)})")
            else:
                err = (data or {}).get("error", "") if isinstance(data, dict) else ""
                trace.append("owner_reels:err:" + str(err)[:90])
        except Exception as e:
            trace.append(f"owner_reels:exc:{type(e).__name__}:{str(e)[:70]}")
    else:
        trace.append("owner_reels:pas_de_owner")
    # 2) Endpoint post-unique (best effort)
    try:
        rp = _scrape_via_rapidapi_single_post(sc)
        if rp.get("video_url"):
            return {"video_url": rp["video_url"], "source": "single_post",
                    "trace": trace + ["single_post:ok"]}
        trace.append("single_post:vide")
    except Exception as e:
        trace.append(f"single_post:exc:{type(e).__name__}")
    # 3) Scrape direct de la page IG (no-API, no-owner)
    try:
        u = _scrape_ig_page_for_video(sc)
        if u:
            return {"video_url": u, "source": "page_scrape",
                    "trace": trace + ["page_scrape:ok"]}
        trace.append("page_scrape:vide")
    except Exception as e:
        trace.append(f"page_scrape:exc:{type(e).__name__}")
    return {"video_url": "", "source": "", "trace": trace}


def _scrape_via_rapidapi(username: str, limit: int) -> dict:
    """Scrape via RapidAPI : Instagram Scraper Stable API.

    Endpoints utilisés:
    - /ig_get_fb_profile_v3.php : profil (Account Data V2)
    - /ig_get_user_reels.php : reels (User Reels) [à vérifier]

    Method: POST avec body form-urlencoded.
    Param: username_or_url
    """
    import requests
    auth = load_auth()
    api_key = auth.get("rapidapi_key", "").strip()
    if not api_key:
        return {"error": "Pas de clé RapidAPI configurée"}
    host = auth.get("rapidapi_host", "instagram-scraper-stable-api.p.rapidapi.com").strip()
    # Auto-correction : si le host est foireux (= contient la clé par accident), fallback default
    DEFAULT_HOST = "instagram-scraper-stable-api.p.rapidapi.com"
    if (not host or "." not in host or "/" in host or " " in host
            or len(host) > 100 or host.startswith("http") or host == api_key
            or "rapidapi.com" not in host):
        log.warning(f"Host RapidAPI invalide ('{host[:30]}...') -> utilisation du défaut")
        host = DEFAULT_HOST
        # Auto-réparer dans le fichier auth
        try:
            auth["rapidapi_host"] = DEFAULT_HOST
            save_auth(auth)
        except Exception:
            pass
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": host,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    base = f"https://{host}"

    # PROFIL + REELS EN PARALLELE : 2 appels reseau independants. On lance le
    # profil dans un thread pendant qu'on fetch les reels -> le scrape prend
    # ~le temps du plus lent (1 aller-retour reseau) au lieu de leur somme.
    import threading as _thr
    _prof_box = {}

    def _fetch_profile_resp():
        try:
            _prof_box["resp"] = requests.post(
                f"{base}/ig_get_fb_profile_v3.php",
                headers=headers,
                data={"username_or_url": username},
                timeout=12,
            )
        except Exception as _e:
            _prof_box["exc"] = _e

    _prof_thread = _thr.Thread(target=_fetch_profile_resp, daemon=True)
    _prof_thread.start()

    # 2) User reels - boucle avec pagination (tourne PENDANT le fetch du profil)
    reels = []
    one_month_ago = int(time.time()) - 30 * 86400  # 30 jours en secondes
    # 2 pages = ~24 reels les plus récents par compte (couvre 24h/7j/30j) tout en
    # divisant ~par 2 la conso RapidAPI -> le plan payant dure bien plus longtemps.
    max_pages = 2  # Limite max d'API calls par profil
    pagination_token = ""
    pages_fetched = 0
    try:
        while pages_fetched < max_pages:
            r = requests.post(
                f"{base}/get_ig_user_reels.php",
                headers=headers,
                data={
                    "username_or_url": username,
                    "amount": str(limit),
                    "pagination_token": pagination_token,
                },
                timeout=12,
            )
            log.info(f"RapidAPI reels page {pages_fetched+1} HTTP {r.status_code} pour {username}")
            pages_fetched += 1
            if r.status_code != 200:
                log.warning(f"Reels HTTP {r.status_code}: {r.text[:200]}")
                break
            posts_data = r.json()
            items = posts_data.get("reels") or posts_data.get("items") or posts_data.get("data") or []
            if not items:
                break
            oldest_taken_at_this_page = None
            # DEBUG : dump le premier item pour debugging
            if pages_fetched == 1 and items:
                first = items[0]
                log.info(f"[DEBUG_CAPTION] First reel structure for @{username}: keys={list(first.keys()) if isinstance(first, dict) else type(first).__name__}")
                if isinstance(first, dict):
                    media_dbg = first.get("media") or first.get("node", {}).get("media") if isinstance(first.get("node"), dict) else first
                    if isinstance(media_dbg, dict):
                        log.info(f"[DEBUG_CAPTION] media keys: {list(media_dbg.keys())[:30]}")
                        # Specifiquement, regarde la structure caption
                        cap_check = media_dbg.get("caption")
                        log.info(f"[DEBUG_CAPTION] caption field: type={type(cap_check).__name__} value={repr(cap_check)[:200]}")
            for it in items:
                try:
                    node = it.get("node") if isinstance(it, dict) else None
                    if node and isinstance(node, dict):
                        media = node.get("media", node)
                    else:
                        media = it.get("media") if isinstance(it, dict) else it
                    if not isinstance(media, dict):
                        continue
                    shortcode = media.get("code") or media.get("shortcode") or ""
                    is_video = media.get("media_type") == 2 or media.get("is_video", True)
                    caption = _extract_caption_robust(media)
                    # DEBUG : log les premieres captions trouvees ou pas
                    if not caption and shortcode:
                        log.info(f"[DEBUG_CAPTION] @{username} {shortcode}: NO caption found. Top-level keys: {list(media.keys())[:20]}")
                    thumb = ""
                    iv2 = media.get("image_versions2", {})
                    candidates = iv2.get("candidates", []) if isinstance(iv2, dict) else []
                    if candidates:
                        # PERF page Trends : les cartes font ~280px de large. Charger le
                        # candidat 1080px (candidates[0] = le plus grand) = ~150-300 Ko
                        # par miniature pour rien. On prend le PLUS PETIT candidat >= 480px
                        # (net en retina) -> ~10x moins de données -> la grille s'affiche
                        # bien plus vite. Fallback : le plus grand si aucune largeur connue.
                        def _cw(c):
                            try:
                                return int(c.get("width") or 0)
                            except (TypeError, ValueError):
                                return 0
                        sized = [c for c in candidates if isinstance(c, dict) and c.get("url")]
                        big_enough = [c for c in sized if _cw(c) >= 480]
                        if big_enough:
                            chosen = min(big_enough, key=lambda c: _cw(c) or 99999)
                        elif sized:
                            chosen = sized[0]
                        else:
                            chosen = None
                        if chosen:
                            thumb = chosen.get("url", "")
                    if not thumb:
                        thumb = media.get("thumbnail_url") or media.get("display_url") or ""
                    # Extraction ULTRA-thorough du video_url.
                    # Couvre toutes les structures connues de RapidAPI / IG API.
                    def _extract_video_url(node):
                        """Recursif : cherche video_url dans node + sous-noeuds."""
                        if not isinstance(node, dict):
                            return None
                        # Direct keys
                        for k in ("video_url", "playback_url", "playable_url",
                                  "playable_url_quality_hd", "video_dash_manifest"):
                            v = node.get(k)
                            if isinstance(v, str) and v.startswith("http"):
                                return v
                        # video_versions list
                        vv = node.get("video_versions") or []
                        if isinstance(vv, list):
                            for v in vv:
                                if isinstance(v, dict):
                                    u = v.get("url") or v.get("src")
                                    if isinstance(u, str) and u.startswith("http"):
                                        return u
                        # Carousels / nested items - essaie tous les noms possibles
                        for child_key in ("carousel_media", "child_items",
                                          "carousel_media_attachments",
                                          "carousel", "media_attachments",
                                          "children", "items"):
                            children = node.get(child_key)
                            if not isinstance(children, list):
                                continue
                            for item in children:
                                u = _extract_video_url(item)
                                if u:
                                    return u
                        # Edge cases : .video, .clips_metadata
                        for nested in ("video", "clips_metadata", "media"):
                            sub = node.get(nested)
                            if isinstance(sub, dict):
                                u = _extract_video_url(sub)
                                if u:
                                    return u
                        return None
                    video_url = _extract_video_url(media)
                    # Re-evalue is_video si on a trouve une video
                    if video_url and not is_video:
                        is_video = True
                    taken_at = media.get("taken_at") or 0
                    pk = media.get("pk") or (media.get("id", "").split("_")[0] if media.get("id") else "")
                    if not taken_at and pk:
                        taken_at = _timestamp_from_pk(pk)
                    if oldest_taken_at_this_page is None or (taken_at and taken_at < oldest_taken_at_this_page):
                        oldest_taken_at_this_page = taken_at
                    reel = {
                        "shortcode": shortcode,
                        "is_video": is_video,
                        "views": media.get("play_count") or media.get("video_view_count") or media.get("view_count"),
                        "likes": media.get("like_count") or 0,
                        "comments": media.get("comment_count") or 0,
                        "caption": caption[:280],
                        "thumbnail_url": thumb,
                        "video_url": video_url,
                        "taken_at": taken_at,
                        "date": "",
                        "url": f"https://www.instagram.com/p/{shortcode}/" if shortcode else "",
                    }
                    reels.append(reel)
                except Exception as e:
                    log.warning(f"Parse RapidAPI reel: {e}")
            # Assez de reels -> stop. 'limit' controle donc le nb de pages =
            # la vitesse du scrape (avant, on allait toujours jusqu'a 5 pages /
            # 1 mois, ce qui etait lent).
            if len(reels) >= limit:
                break
            # Pagination : continuer si on n'a pas encore atteint 1 mois OU pas de token
            next_token = posts_data.get("pagination_token") or posts_data.get("next_max_id") or ""
            if not next_token:
                break  # plus de pages
            if oldest_taken_at_this_page and oldest_taken_at_this_page < one_month_ago:
                break  # on a déjà 1 mois de contenu
            pagination_token = next_token
            time.sleep(0.3)  # petit délai entre les pages
    except Exception as e:
        log.warning(f"Fetch reels via RapidAPI: {e}")

    # Recupere le resultat du profil (lance en parallele) + validation/parse
    _prof_thread.join()
    if _prof_box.get("exc") is not None:
        _pe = _prof_box["exc"]
        return {"error": f"Erreur fetch profil: {type(_pe).__name__}: {_pe}"}
    r = _prof_box.get("resp")
    if r is None:
        return {"error": "Pas de reponse profil RapidAPI"}
    log.info(f"RapidAPI profile HTTP {r.status_code} pour {username}")
    if r.status_code == 401 or r.status_code == 403:
        return {"error": f"Clé RapidAPI invalide ou non-abonné (HTTP {r.status_code}). Vérifie sur RapidAPI."}
    if r.status_code == 429:
        return {"error": "Quota RapidAPI épuisé (HTTP 429). Upgrade ton plan ou attends."}
    if r.status_code == 404:
        return {"error": f"Endpoint introuvable (HTTP 404). L'API a peut-être changé."}
    if r.status_code != 200:
        return {"error": f"RapidAPI HTTP {r.status_code}: {r.text[:200]}"}
    try:
        user = r.json()
    except Exception:
        return {"error": f"Réponse non-JSON: {r.text[:150]}"}
    if isinstance(user, dict):
        if "user" in user and isinstance(user["user"], dict):
            user = user["user"]
        elif "data" in user and isinstance(user["data"], dict):
            user = user["data"]
    if not isinstance(user, dict) or not (user.get("username") or user.get("pk") or user.get("id")):
        err_msg = user.get("error") or user.get("message") or user.get("detail") if isinstance(user, dict) else str(user)
        return {"error": f"Réponse vide/invalide. {err_msg or str(user)[:150]}"}
    pic = ""
    if isinstance(user.get("hd_profile_pic_url_info"), dict):
        pic = user["hd_profile_pic_url_info"].get("url", "")
    if not pic:
        pic = user.get("profile_pic_url", "")
    profile_data = {
        "username": user.get("username") or username,
        "full_name": user.get("full_name", ""),
        "followers": user.get("follower_count", 0),
        "following": user.get("following_count", 0),
        "posts_count": user.get("media_count", 0),
        "profile_pic_url": pic,
        "biography": (user.get("biography") or "")[:300],
        "is_private": user.get("is_private", False),
        "is_verified": user.get("is_verified", False),
        "pk": user.get("pk") or user.get("id"),
    }

    result = {
        "profile": profile_data,
        "reels": reels,
        "scraped_at": time.time(),
        "source": "rapidapi",
    }
    _ensure_dirs()
    (CACHE_DIR / f"{username}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


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
            caption = _extract_caption_robust(node)
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


def scrape_profile(username: str, limit: int = 50) -> dict:
    """Scrape un profil : profil info + N derniers posts.

    Ordre de tentatives :
    1. RapidAPI (le plus fiable, payant) - si clé configurée
    2. API web directe avec cookies
    3. instaloader en dernier fallback
    """
    username = _clean_username(username)
    if not username:
        return {"error": "username vide"}
    auth = load_auth()
    errors = []

    # Tentative 0 : RapidAPI (PRIORITAIRE si clé configurée)
    if auth.get("rapidapi_key"):
        result = _scrape_via_rapidapi(username, limit)
        if "error" not in result:
            return result
        errors.append(f"RapidAPI: {result['error']}")
        log.warning(f"RapidAPI échoué pour {username}: {result['error']}")
        # Mode RapidAPI STRICT : la clé est configurée -> on NE bascule PAS sur les
        # cookies Instagram (Web/instaloader). On renvoie l'erreur RapidAPI telle
        # quelle (ex: quota épuisé). L'utilisateur veut fonctionner SEULEMENT via
        # l'API payante. (Le scrape remarchera dès que la quota se recharge.)
        return {"error": " | ".join(errors)}

    if not auth.get("sessionid"):
        if errors:
            return {"error": " | ".join(errors)}
        return {"error": "Aucune session ni clé RapidAPI configurée (Settings → Instagram)"}

    # Tentative 1 : API web directe (plus fiable)
    result = _scrape_via_web_api(username, limit)
    if "error" not in result:
        return result
    errors.append(f"Web API: {result['error']}")

    # Tentative 2 : instaloader en fallback
    if not INSTALOADER_OK:
        return {"error": " | ".join(errors)}
    L = _make_loader()
    if L is None:
        errors.append("instaloader: pas de session valide")
        return {"error": " | ".join(errors)}
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
            time.sleep(0.2)
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
        errors.append(f"instaloader: profil introuvable")
        return {"error": " | ".join(errors)}
    except instaloader.exceptions.LoginRequiredException:
        errors.append("instaloader: session expirée")
        return {"error": " | ".join(errors)}
    except Exception as e:
        errors.append(f"instaloader: {type(e).__name__}: {e}")
        return {"error": " | ".join(errors)}


def get_cached(username: str) -> Optional[dict]:
    f = CACHE_DIR / f"{_clean_username(username)}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_caption_robust(media_or_node: dict) -> str:
    """Essaie plusieurs champs Instagram pour trouver la caption.

    Champs possibles selon l'endpoint :
    - REST API :    media.caption.text (objet ou string)
    - GraphQL :     node.edge_media_to_caption.edges[0].node.text
    - clip media :  media.clips_metadata.clips_caption.text
    - fallback :    media.title

    Retourne "" si rien trouve.
    """
    if not isinstance(media_or_node, dict):
        return ""
    # Path 1 : caption (REST)
    cap_obj = media_or_node.get("caption")
    if isinstance(cap_obj, dict):
        text = cap_obj.get("text", "")
        if text:
            return str(text)
    elif isinstance(cap_obj, str) and cap_obj:
        return cap_obj
    # Path 2 : edge_media_to_caption (GraphQL)
    edges = media_or_node.get("edge_media_to_caption", {})
    if isinstance(edges, dict):
        e_list = edges.get("edges", [])
        if e_list and isinstance(e_list, list):
            first = e_list[0]
            if isinstance(first, dict):
                node = first.get("node", {})
                if isinstance(node, dict):
                    text = node.get("text", "")
                    if text:
                        return str(text)
    # Path 3 : clips_metadata (reels-specific)
    clips = media_or_node.get("clips_metadata", {})
    if isinstance(clips, dict):
        cc = clips.get("clips_caption", {})
        if isinstance(cc, dict):
            text = cc.get("text", "")
            if text:
                return str(text)
        # Music caption ?
        music = clips.get("music_info", {})
        if isinstance(music, dict):
            sub = music.get("music_asset_info", {})
            if isinstance(sub, dict):
                title = sub.get("title", "")
                # Ne pas retourner le titre du son comme caption (different !)
    # Path 4 : title fallback
    title = media_or_node.get("title")
    if isinstance(title, str) and title:
        return title
    return ""


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
    """Liste enrichie : username + last_scrape + nb_reels + profile_pic."""
    wl = load_watchlist()
    out = []
    for u in wl:
        data = get_cached(u)
        if data:
            prof = data.get("profile", {})
            out.append({
                "username": u,
                "scraped_at": data.get("scraped_at", 0),
                "nb_reels": len(data.get("reels", [])),
                "followers": prof.get("followers", 0),
                "full_name": prof.get("full_name", ""),
                "profile_pic_url": prof.get("profile_pic_url", ""),
                "is_verified": prof.get("is_verified", False),
            })
        else:
            out.append({
                "username": u,
                "scraped_at": 0,
                "nb_reels": 0,
                "followers": 0,
                "full_name": "",
                "profile_pic_url": "",
                "is_verified": False,
            })
    return out
