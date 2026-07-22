"""veille_telegram.py - Envoi de liens de reels au bot downloader sur Telegram.

Config stockee dans data/veille_telegram.json :
{
    "bot_token": "...",       # token du BOT TELEGRAM (pas celui du downloader)
    "chat_id": "-100..."       # ID du groupe / chat ou poster
}

Usage typique :
- L user configure une fois le token + chat_id depuis Settings
- Quand il clique 'Envoyer a Veille' sur un reel, on POST l URL au chat
- Le bot downloader (qui est dans ce chat) detecte le lien et telecharge
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "veille_telegram.json"
TG_API_BASE = "https://api.telegram.org"
TIMEOUT = 15


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("bot_token")) and bool(cfg.get("chat_id"))


def set_credentials(bot_token: str, chat_id: str):
    cfg = load_config()
    cfg["bot_token"] = (bot_token or "").strip()
    cfg["chat_id"] = (chat_id or "").strip()
    save_config(cfg)


def send_url(url: str, caption: Optional[str] = None) -> Dict[str, Any]:
    """Envoie un URL au chat configure. Retourne {ok, result|error}.

    Note : si le caption contient deja l URL, on ne la duplique pas.
    """
    cfg = load_config()
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Bot Telegram non configure"}

    # Construit le texte final - evite la duplication de l URL
    if caption:
        if url and url in caption:
            text = caption  # URL deja dans le caption, pas besoin de l ajouter
        else:
            text = f"{caption}\n{url}" if url else caption
    else:
        text = url
    try:
        r = requests.post(
            f"{TG_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=TIMEOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau : {e}"}
    if r.status_code != 200:
        try:
            j = r.json()
            return {"ok": False, "error": f"HTTP {r.status_code}: {j.get('description', '?')}"}
        except Exception:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
    try:
        j = r.json()
        if not j.get("ok"):
            return {"ok": False, "error": j.get("description", "?")}
        return {"ok": True, "message_id": j.get("result", {}).get("message_id")}
    except Exception as e:
        return {"ok": False, "error": f"Reponse invalide : {e}"}


# ============ Download + sendVideo (comme un bot downloader Discord) ============

_IG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "Instagram 250.0.0.21.109"
    ),
    "Accept": "*/*",
    "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
}


def _find_ig_cookies() -> Optional[str]:
    """Cherche un cookies.txt Instagram (format Netscape) a des emplacements
    connus. Permet a yt-dlp de telecharger les reels qui demandent une connexion.
    """
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent
    candidates = [
        _P("data/insta/cookies.txt"),               # chemin VPS (gitignore)
        here / "data" / "insta" / "cookies.txt",
        here.parent / "ig-downloader" / "cookies.txt",  # dev local
    ]
    for c in candidates:
        try:
            if c.exists() and c.stat().st_size > 50:
                return str(c)
        except Exception:
            pass
    return None


def download_via_ytdlp(post_url: str, timeout: int = 25,
                       info: Optional[Dict[str, Any]] = None,
                       use_cookies: bool = True) -> Optional[bytes]:
    """Telecharge la video d'un permalink IG via yt-dlp (comme le bot ig-downloader).

    C'est la methode la PLUS FIABLE : yt-dlp gere l'extraction + l'auth via les
    cookies IG (data/insta/cookies.txt) -> recupere meme les reels que le scrape
    public ne voit pas. Retourne les bytes (<50MB) ou None ; info['reason'] est
    rempli en cas d'echec ('ytdlp_absent', 'audience_restreinte',
    'login_requis_cookies', 'trop_gros_50mb', ...).

    use_cookies=False : extraction PUBLIQUE, sans toucher au cookie IG (aucun
    risque de ban). Utilise pour le pre-telechargement de masse des reels
    recents (le cookie n'est consomme que pour un download unitaire a la demande).
    """
    def _set(reason: str):
        if info is not None:
            info["reason"] = reason
    if not post_url:
        _set("url_vide")
        return None
    try:
        import yt_dlp
    except Exception:
        _set("ytdlp_absent")
        return None
    import tempfile
    import os
    import glob
    import shutil
    tmpdir = tempfile.mkdtemp(prefix="veille_yt_")
    opts = {
        "outtmpl": os.path.join(tmpdir, "v.%(ext)s"),
        "format": "mp4/bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 1,
        "socket_timeout": timeout,
        "max_filesize": 50 * 1024 * 1024,  # Telegram cap : yt-dlp skip si >50MB
    }
    cookies = _find_ig_cookies() if use_cookies else None
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            _ydi = ydl.extract_info(post_url, download=True)
        # Recupere AUSSI la description (caption) du reel -> aucun appel supplementaire
        # (yt-dlp l'a deja extraite en telechargeant). Sert de followup sur Telegram.
        if info is not None and isinstance(_ydi, dict):
            _desc = (_ydi.get("description") or "").strip()
            if _desc:
                info["description"] = _desc
        files = [f for f in glob.glob(os.path.join(tmpdir, "v.*")) if os.path.isfile(f)]
        if not files:
            _set("trop_gros_50mb" if cookies is not None else "ytdlp_pas_de_fichier")
            return None
        path = max(files, key=lambda f: os.path.getsize(f))
        size = os.path.getsize(path)
        if size <= 0:
            _set("ytdlp_fichier_vide")
            return None
        if size > 50 * 1024 * 1024:
            _set("trop_gros_50mb")
            return None
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        low = str(e).lower()
        if "available to everyone" in low or "certain audiences" in low:
            _set("audience_restreinte")
        elif "login required" in low or "rate-limit" in low or "login" in low or "cookies" in low:
            _set("login_requis_cookies")
        elif "max_filesize" in low or "larger than" in low:
            _set("trop_gros_50mb")
        else:
            _set("ytdlp_err:" + str(e)[:90])
        return None
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def download_video_bytes(video_url: str, timeout: int = 25,
                         info: Optional[Dict[str, Any]] = None) -> Optional[bytes]:
    """Telecharge une video depuis un CDN Instagram.

    Retourne les bytes (ou None si erreur / >50 MB / timeout).
    - timeout = 25s (un reel 10-30s pese 2-15 MB, doit downloader en ~5s)
    - 50 MB max (limite Telegram bot upload)
    - `info` : dict optionnel ; si fourni, on y ecrit info['reason'] = la raison
      precise de l'echec ('url_vide', 'trop_gros_50mb', 'http_403', 'corps_vide',
      'exception') -> permet un message d'erreur clair cote appelant.
    """
    def _set(reason: str):
        if info is not None:
            info["reason"] = reason
    if not video_url:
        _set("url_vide")
        return None
    # On essaie 2 jeux de headers : l'app Instagram, puis un navigateur classique
    # avec Referer (certains noeuds CDN scontent renvoient 403 selon le User-Agent).
    header_variants = [
        _IG_HEADERS,
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Referer": "https://www.instagram.com/",
            "Range": "bytes=0-",
        },
    ]
    max_size = 50 * 1024 * 1024  # 50 MB (limite upload bot Telegram)
    last_reason = "echec_inconnu"
    for headers in header_variants:
        try:
            r = requests.get(video_url, headers=headers, timeout=timeout, stream=True)
            if r.status_code not in (200, 206):
                last_reason = f"http_{r.status_code}"
                continue  # 403/410/... -> on tente le jeu de headers suivant
            chunks = []
            total = 0
            too_big = False
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > max_size:
                    too_big = True
                    break  # Trop gros, abandon (inutile de retenter)
            if too_big:
                _set("trop_gros_50mb")
                return None  # >50MB : Telegram refuse, inutile de retenter
            if chunks:
                return b"".join(chunks)
            last_reason = "corps_vide"  # 200 mais 0 octet -> tente variante suivante
        except Exception as e:
            last_reason = f"exception_{type(e).__name__}"
            continue
    _set(last_reason)
    return None


def _refresh_video_url(post_url: str, owner: str = "") -> Optional[str]:
    """Compat : wrapper qui retourne juste le video_url frais."""
    data = refresh_post_data(post_url, owner=owner)
    return data.get("video_url") or None


def _scrape_og_caption(post_url: str) -> str:
    """Fallback no-auth : recupere le og:description meta tag de la page IG
    publique. Ne marche pas toujours (IG cache certains posts derriere un
    wall) mais utile quand instaloader n est pas configure."""
    if not post_url:
        return ""
    try:
        import re as _re
        from html import unescape
        r = requests.get(
            post_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; Telegrambot/1.0; "
                    "+http://telegram.org)"
                ),
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return ""
        # og:description ou meta description
        for pat in (
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        ):
            m = _re.search(pat, r.text)
            if m:
                desc = unescape(m.group(1)).strip()
                # IG met souvent un prefixe "X likes, Y comments - @user on..."
                # On extrait juste le texte de la legende qui est apres le ':'
                # Format typique : '127 likes, 8 comments - "Caption ici"'
                # ou '@user on Instagram: "Caption ici"'
                quote_m = _re.search(r'[:""]\s*["“]([^"”]+)["”]', desc)
                if quote_m:
                    return quote_m.group(1).strip()[:1000]
                # Fallback : on prend tout apres le dernier ':' si y en a un
                if ':' in desc:
                    return desc.rsplit(':', 1)[1].strip().strip('"').strip()[:1000]
                return desc[:1000]
    except Exception:
        pass
    return ""


def refresh_post_data(post_url: str, owner: str = "") -> Dict[str, str]:
    """Re-scrape video_url ET caption depuis le permalink IG.

    Strategie multi-source pour le video_url (cascade) :
    - RapidAPI post-unique (rapide mais fragile) PUIS reels du proprietaire
      via l'endpoint /get_ig_user_reels.php (celui qui marche pour les stats).
    - instaloader (si configure) : complete video_url + caption.
    - fallback no-auth : og:description meta tag pour le caption seulement.

    `owner` = le @compte source du reel (permet le fallback "reels du compte").
    Retourne {video_url, caption, _debug}. Champs vides si tout echoue ;
    _debug contient la trace de resolution (utile pour diagnostiquer).
    """
    import re as _re
    out: Dict[str, str] = {"video_url": "", "caption": "", "_debug": ""}
    if not post_url:
        out["_debug"] = "url_vide"
        return out
    m = _re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', post_url)
    if not m:
        out["_debug"] = "url_sans_shortcode"
        return out
    shortcode = m.group(1)
    # 1) Resolution video_url en cascade : reels-du-proprietaire -> post-unique
    #    -> scrape-page. La tier 3 (scrape page) marche meme SANS cle RapidAPI,
    #    donc on appelle toujours le resolver (pas de gate sur la cle).
    try:
        import insta_scraper
        rp = insta_scraper.get_video_url_for_shortcode(shortcode, owner_username=owner)
        if rp.get("video_url"):
            out["video_url"] = rp["video_url"]
            out["_debug"] = f"video_ok[{rp.get('source','')}]"
        else:
            out["_debug"] = "video_url_introuvable | " + " ; ".join(rp.get("trace", []))[:240]
    except Exception as e:
        out["_debug"] = f"resolver_error: {type(e).__name__}: {str(e)[:150]}"
    # 2) instaloader (si dispo) : complète le video_url manquant + le caption
    if (not out["video_url"]) or (not out["caption"]):
        try:
            import insta_scraper
            loader = insta_scraper._make_loader() if hasattr(insta_scraper, "_make_loader") else None
            if loader is not None:
                import instaloader
                try:
                    post = instaloader.Post.from_shortcode(loader.context, shortcode)
                    if not out["video_url"] and getattr(post, "is_video", False):
                        out["video_url"] = post.video_url or out["video_url"]
                    if not out["caption"]:
                        out["caption"] = (post.caption or "")[:1000]
                except Exception as ee:
                    if not out["_debug"] or "rapidapi" in out["_debug"]:
                        out["_debug"] = f"instaloader_error: {type(ee).__name__}: {str(ee)[:200]}"
        except Exception as e:
            if not out["_debug"] or "rapidapi" in out["_debug"]:
                out["_debug"] = f"instaloader_top: {type(e).__name__}: {str(e)[:200]}"
    # 3) Fallback no-auth pour le caption uniquement
    if not out["caption"]:
        out["caption"] = _scrape_og_caption(post_url)
    return out


# ---- Cache PERSISTANT des file_id Telegram, par shortcode ------------------
# Un reel uploadé UNE fois n'est plus jamais retéléchargé ni re-uploadé :
# Telegram garde sa copie, on renvoie par file_id (instantané). Le self-lookup
# de send_video_from_url fait profiter TOUTES les routes (send unitaire,
# send_day, banger) sans changer leurs appels.
import threading as _threading

FILEID_FILE = Path("data/veille_tg_fileids.json")
_FILEID_LOCK = _threading.Lock()
_FILEID_MEM: Dict[str, Any] = {}


def _fileid_all() -> Dict[str, Any]:
    global _FILEID_MEM
    if not _FILEID_MEM and FILEID_FILE.exists():
        try:
            d = json.loads(FILEID_FILE.read_text(encoding="utf-8"))
            _FILEID_MEM = d if isinstance(d, dict) else {}
        except Exception:
            _FILEID_MEM = {}
    return _FILEID_MEM


def _fileid_save():
    try:
        FILEID_FILE.parent.mkdir(parents=True, exist_ok=True)
        FILEID_FILE.write_text(json.dumps(_FILEID_MEM, ensure_ascii=False),
                               encoding="utf-8")
    except Exception:
        pass


def fileid_get(shortcode: str) -> str:
    if not shortcode:
        return ""
    with _FILEID_LOCK:
        return str((_fileid_all().get(shortcode) or {}).get("file_id") or "")


def fileid_put(shortcode: str, file_id: str):
    if not shortcode or not file_id:
        return
    import time as _t
    with _FILEID_LOCK:
        _fileid_all()[shortcode] = {"file_id": file_id, "ts": int(_t.time())}
        _fileid_save()


def fileid_drop(shortcode: str):
    """file_id refusé par Telegram (invalide/expiré) : purgé pour ne pas
    réessayer en boucle."""
    if not shortcode:
        return
    with _FILEID_LOCK:
        if shortcode in _fileid_all():
            _fileid_all().pop(shortcode, None)
            _fileid_save()


def _tg_post(url: str, *, data=None, json_payload=None, files=None, timeout=30):
    """requests.post vers l'API Telegram avec UNE relance sur 429 (retry_after).
    Sans ça, les envois par file_id (instantanés donc en rafale) perdaient des
    messages en silence (limite ~20 msg/min par groupe)."""
    r = requests.post(url, data=data, json=json_payload, files=files, timeout=timeout)
    if r.status_code == 429:
        try:
            wait = float(((r.json().get("parameters") or {}).get("retry_after")) or 3)
        except Exception:
            wait = 3.0
        import time as _t
        _t.sleep(min(wait + 0.5, 35))
        r = requests.post(url, data=data, json=json_payload, files=files, timeout=timeout)
    return r


def send_video_from_url(video_url: str, caption: str = "",
                        fallback_url: str = "",
                        followup_text: str = "",
                        owner: str = "",
                        tg_file_id: str = "",
                        followup_final: bool = False) -> Dict[str, Any]:
    """Telecharge une video IG et la poste sur Telegram via sendVideo.

    Comportement comme un bot downloader Discord/Telegram :
    - On telecharge la video Instagram en local (bytes)
    - On l upload sur Telegram via sendVideo (multipart)
    - La caption (lien) apparait en dessous de la video
    - Si followup_text est fourni, on envoie un 2e message texte juste
      apres (utilise pour separer la description de la video)

    Args:
        video_url      : URL CDN de la video Instagram
        caption        : Caption sous la video (typiquement juste le lien IG)
        fallback_url   : Si le download / sendVideo echoue, on retombe sur
                         sendMessage avec ce lien Instagram
        followup_text  : Texte d un 2e message envoye juste apres la video
                         (typiquement la description du reel)

    Retourne {ok, mode: "video"|"link", message_id|error}.
    """
    cfg = load_config()
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Bot Telegram non configure"}

    # Verrou d'ORDRE global (RLock réentrant) résolu UNE fois : sérialise TOUS les
    # chemins de post canal (fast-path file_id, download, fallback lien) -> deux
    # reels envoyés en parallèle n'entrelacent jamais leurs messages. Le download,
    # lui, reste hors verrou (téléchargements parallèles OK).
    try:
        import tg_router as _tgr
        _order_lock = _tgr._POST_LOCK
    except Exception:
        import contextlib as _cl
        _order_lock = _cl.nullcontext()

    # Shortcode extrait TOUT DE SUITE : sert au self-lookup file_id, au cache
    # disque et au stockage après upload.
    import re as _re_v
    from pathlib import Path as _Pv
    _scm = _re_v.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', fallback_url or "")
    _sc = _scm.group(1) if _scm else ""

    # 0bis) REUTILISATION du file_id Telegram : si ce reel a deja ete envoye en
    # VIDEO, Telegram a garde sa copie -> on renvoie via le file_id = INSTANTANE
    # (zero telechargement, zero upload). Le vrai "copier-coller" de la video.
    # Self-lookup : même si l'appelant n'a pas fourni tg_file_id (send_day,
    # banger, modal Préparer...), le cache central par shortcode est consulté.
    if not tg_file_id and _sc:
        tg_file_id = fileid_get(_sc)
    if tg_file_id:
        # fast-path SOUS le verrou d'ordre : sendVideo + followup d'un bloc
        # (c'est le cas COURANT — un reel déjà en cache -> renvoi instantané).
        try:
            with _order_lock:
                _rf = _tg_post(
                    f"{TG_API_BASE}/bot{token}/sendVideo",
                    data={"chat_id": chat_id, "caption": (caption or "")[:1024],
                          "video": tg_file_id, "supports_streaming": "true"},
                    timeout=30,
                )
                _jf = _rf.json()
                if _rf.status_code == 200 and _jf.get("ok"):
                    _midf = _jf.get("result", {}).get("message_id")
                    fileid_put(_sc, tg_file_id)
                    if followup_text and followup_text.strip():
                        try:
                            _tg_post(
                                f"{TG_API_BASE}/bot{token}/sendMessage",
                                json_payload={"chat_id": chat_id, "text": followup_text.strip()[:4000],
                                              "disable_web_page_preview": True, "reply_to_message_id": _midf},
                                timeout=15)
                        except Exception:
                            pass
                    return {"ok": True, "mode": "video", "message_id": _midf, "tg_file_id": tg_file_id,
                            "chat_id": chat_id,   # canal Veille -> permet le forward vers les models
                            "has_desc": bool(followup_text and followup_text.strip()),
                            "description": (followup_text or "")}
                # Telegram a répondu mais a REFUSÉ le file_id (invalide/expiré) :
                # on le purge pour ne plus le retenter, et on télécharge normalement
                _desc_err = str(_jf.get("description") or "").lower()
                if "file" in _desc_err or _rf.status_code == 400:
                    fileid_drop(_sc)
                    tg_file_id = ""
        except Exception:
            pass  # file_id invalide/expire -> on retombe sur le telechargement normal

    def _fallback(reason: str) -> Dict[str, Any]:
        if not fallback_url:
            return {"ok": False, "error": reason}
        # POST lien + description SOUS le verrou d'ordre (RLock réentrant : ok même
        # si appelé depuis le bloc download déjà verrouillé) -> ordre préservé.
        with _order_lock:
            # Lien Instagram en premier message
            res = send_url(fallback_url, caption=caption)
            if res.get("ok"):
                res["mode"] = "link"
                res["fallback_reason"] = reason
                # 2e message texte avec la description si dispo
                if followup_text and followup_text.strip():
                    try:
                        requests.post(
                            f"{TG_API_BASE}/bot{token}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": followup_text.strip()[:4000],
                                "disable_web_page_preview": True,
                                "reply_to_message_id": res.get("message_id"),
                            },
                            timeout=15,
                        )
                    except Exception:
                        pass
        return res

    _readable = {
        "url_vide": "aucun lien video stocke",
        "trop_gros_50mb": "video > 50 Mo (limite Telegram, impossible a envoyer)",
        "corps_vide": "le CDN a renvoye un fichier vide",
        "audience_restreinte": "reel a audience restreinte (Instagram bloque le telechargement, meme avec cookies)",
        "login_requis_cookies": "Instagram demande une connexion (ajoute des cookies IG : reglages > Instagram)",
    }
    last_err = ""
    # CACHE disque PARTAGE avec la lecture Trends (data/insta/videos/{sc}.mp4) : un
    # reel deja telecharge (lu sur Trends OU envoye avant) est REUTILISE -> renvoi
    # INSTANTANE + zero appel yt-dlp (donc moins de rate-limit / risque de ban).
    # (_sc / _re_v / _Pv déjà posés en tête de fonction pour le self-lookup)
    _cache_f = (_Pv("data/insta/videos") / f"{_sc}.mp4") if _sc else None
    _desc_f = (_Pv("data/insta/videos") / f"{_sc}.txt") if _sc else None  # sidecar description
    yt_info: Dict[str, Any] = {}
    yt_reason = ""
    video_bytes = None
    if _cache_f and _cache_f.exists() and 1024 < _cache_f.stat().st_size <= 50 * 1024 * 1024:
        try:
            video_bytes = _cache_f.read_bytes()
        except Exception:
            video_bytes = None
        # CACHE HIT : yt-dlp ne tourne pas -> on relit la description sauvegardee a
        # cote (sinon la description manquerait sur un renvoi). Garde l'ordre
        # video -> lien -> description meme depuis le cache.
        # followup_final : la description a été fixée EXPLICITEMENT (modal/brouillon),
        # même vide -> on ne la re-remplit jamais depuis le sidecar/yt-dlp/Apify
        if video_bytes and _desc_f and _desc_f.exists() and not followup_final \
                and (not followup_text or not followup_text.strip()):
            try:
                _ds = _desc_f.read_text(encoding="utf-8").strip()
                if _ds:
                    followup_text = _ds
            except Exception:
                pass
    # 0a) APIFY d'abord (si configuré) : résout le video_url + caption via le
    #     scraper officiel (ZERO cookie, pas de 429) et télécharge. C'est LA
    #     source fiable pour la veille — évite le yt-dlp qui se fait jeter (429).
    if not video_bytes and fallback_url:
        try:
            import apify_reels as _ap
            if _ap.configured():
                _ar = _ap.fetch_video_urls([fallback_url], timeout=90)
                _ad = _ar.get(_sc) or (list(_ar.values())[0] if _ar else None)
                if _ad and _ad.get("video_url"):
                    video_bytes = download_video_bytes(_ad["video_url"])
                    if video_bytes:
                        if _ad.get("caption") and not followup_final \
                                and (not followup_text or not followup_text.strip()):
                            followup_text = _ad["caption"]
                        if _cache_f:   # met en cache (partagé Trends) + sidecar desc
                            try:
                                _cache_f.parent.mkdir(parents=True, exist_ok=True)
                                _cache_f.write_bytes(video_bytes)
                                if _ad.get("caption") and _desc_f:
                                    _desc_f.write_text(_ad["caption"], encoding="utf-8")
                            except Exception:
                                pass
        except Exception:
            pass
    # 0b) yt-dlp depuis le permalink (PUBLIC, sans cookie) si Apify n'a rien.
    #     Recupere AUSSI la description (yt_info['description']).
    if not video_bytes:
        video_bytes = download_via_ytdlp(fallback_url, info=yt_info, use_cookies=False) if fallback_url else None
        yt_reason = yt_info.get("reason", "")
        # Si yt-dlp dit "audience restreinte" ou "trop gros", c'est definitif -> lien
        if not video_bytes and yt_reason in ("audience_restreinte", "trop_gros_50mb"):
            return _fallback("Telechargement impossible : " + _readable.get(yt_reason, yt_reason))
        # Met en cache (partage avec Trends) + SAUVE la description a cote -> dispo
        # meme sur les futurs cache hits (renvois).
        if video_bytes and _cache_f:
            try:
                _cache_f.parent.mkdir(parents=True, exist_ok=True)
                _cache_f.write_bytes(video_bytes)
                if yt_info.get("description") and _desc_f:
                    _desc_f.write_text(yt_info["description"], encoding="utf-8")
            except Exception:
                pass
    # Description : si aucune fournie, utilise celle que yt-dlp a recuperee
    # (sauf followup_final : description explicitement fixee, meme vide)
    if not followup_final and (not followup_text or not followup_text.strip()) \
            and yt_info.get("description"):
        followup_text = yt_info["description"]

    # 1) Fallback : URL CDN directe stockee
    if not video_bytes:
        dl_info: Dict[str, Any] = {}
        video_bytes = download_video_bytes(video_url, info=dl_info)
        if not video_bytes and dl_info.get("reason") == "trop_gros_50mb":
            return _fallback("Telechargement impossible : " + _readable["trop_gros_50mb"])

    # 2) Fallback : re-resout un video_url FRAIS (reels du compte -> post-unique -> page)
    if not video_bytes:
        refreshed = refresh_post_data(fallback_url, owner=owner) if fallback_url else {}
        fresh = refreshed.get("video_url") or ""
        if fresh and fresh != video_url:
            dl_info2: Dict[str, Any] = {}
            video_bytes = download_video_bytes(fresh, info=dl_info2)
            if not video_bytes:
                last_err = _readable.get(
                    dl_info2.get("reason", ""),
                    f"URL fraiche OK mais le CDN refuse le download ({dl_info2.get('reason','?')})",
                )
        if not video_bytes and not last_err:
            # Message d'echec : on privilegie la raison yt-dlp (plus parlante)
            if yt_reason in _readable:
                last_err = _readable[yt_reason]
            else:
                dbg = (refreshed.get("_debug") or "").strip()
                suffix = f" [yt-dlp:{yt_reason}]" if yt_reason else ""
                last_err = (f"video introuvable ({dbg})" if dbg else "video introuvable") + suffix
    if not video_bytes:
        return _fallback(f"Telechargement impossible : {last_err or yt_reason or '?'}")

    # 2+3) POST sous le verrou d'ORDRE global (déjà résolu en tête) : vidéo PUIS
    # description partent d'un bloc -> deux reels envoyés en parallèle n'entrelacent
    # jamais leurs messages. Le DOWNLOAD (au-dessus) reste HORS du verrou.
    with _order_lock:
        # 2) Upload via sendVideo (multipart, fichier en memoire)
        try:
            r = _tg_post(
                f"{TG_API_BASE}/bot{token}/sendVideo",
                data={
                    "chat_id": chat_id,
                    "caption": (caption or "")[:1024],
                    "supports_streaming": "true",
                },
                files={"video": ("reel.mp4", video_bytes, "video/mp4")},
                timeout=60,  # 60s suffit pour un upload de <50MB
            )
        except Exception as e:
            return _fallback(f"Erreur reseau Telegram : {e}")

        if r.status_code != 200:
            try:
                j = r.json()
                return _fallback(f"HTTP {r.status_code}: {j.get('description', '?')}")
            except Exception:
                return _fallback(f"HTTP {r.status_code}")

        _new_fid = ""
        try:
            j = r.json()
            if not j.get("ok"):
                return _fallback(j.get("description", "Reponse Telegram non ok"))
            _res = j.get("result", {})
            msg_id = _res.get("message_id")
            # file_id de la video uploadee -> permet un renvoi INSTANTANE plus tard
            _new_fid = ((_res.get("video") or {}).get("file_id")
                        or (_res.get("document") or {}).get("file_id") or "")
            # stocké dans le cache CENTRAL : toutes les routes en profitent
            if _new_fid and _sc:
                fileid_put(_sc, _new_fid)
        except Exception as e:
            return _fallback(f"Reponse invalide : {e}")

        # 3) Followup texte (la description IG) en message separe
        if followup_text and followup_text.strip():
            try:
                requests.post(
                    f"{TG_API_BASE}/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": followup_text.strip()[:4000],  # Telegram cap 4096
                        "disable_web_page_preview": True,  # Pas d apercu, c est juste du texte
                        "reply_to_message_id": msg_id,  # Threade sous la video
                    },
                    timeout=15,
                )
            except Exception:
                pass  # Followup pas critique, on log pas
        return {
            "ok": True,
            "mode": "video",
            "message_id": msg_id,
            "tg_file_id": _new_fid,
            "chat_id": chat_id,   # canal Veille -> permet le forward vers les models
            "has_desc": bool(followup_text and followup_text.strip()),
            "description": (followup_text or ""),
        }


def test_connection() -> Dict[str, Any]:
    """Test : envoie un message court pour verifier que le bot peut poster."""
    cfg = load_config()
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return {"ok": False, "error": "Pas de config"}
    return send_url("✅ Test de connexion VA Bot - Veille Telegram")
