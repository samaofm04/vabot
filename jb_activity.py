"""Activité VA (comptes jailbreak).

- Scan quotidien de chaque compte JB via insta_scraper/RapidAPI : dernier post
  (taken_at) + vues du dernier reel + vues sur 14 jours.
- Pénalités VA : 1 pénalité par VA et par JOUR s'il a, ce jour-là, AU MOINS un
  compte silencieux depuis >48 h (peu importe combien de comptes en faute = 1/j).
- Résumé pour la page site « Activité VA ».

Stockage (data/, VPS-only) :
  jb_activity.json     -> {username: {last_post_ts, last_views, views_14d, is_private, scanned_at, error}}
  jb_va_penalties.json -> {va_lower: {"va": <affichage>, "days": ["YYYY-MM-DD", ...]}}
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
ACT_FILE = DATA_DIR / "jb_activity.json"
PEN_FILE = DATA_DIR / "jb_va_penalties.json"
SCAN_MARK = DATA_DIR / "jb_activity_lastscan.txt"

SILENCE_SEC = 48 * 3600         # >48 h sans poster = en faute
WEEKS2_SEC = 14 * 24 * 3600     # fenêtre "vues 14 jours"
_BAN_FILE = DATA_DIR / "va_insta_3_stats_cache.json"   # {handle: {banned: true}}
_lock = threading.Lock()
_scanning = {"on": False, "done": 0, "total": 0, "errors": 0}


def _banned() -> set:
    """Usernames (lower) marqués bannis par le scraper -> jamais pénalisés."""
    out = set()
    try:
        d = json.loads(_BAN_FILE.read_text(encoding="utf-8"))
        for handle, st in (d or {}).items():
            if isinstance(st, dict) and st.get("banned"):
                out.add(str(handle).strip().lower())
    except Exception:
        pass
    return out


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(p: Path, d: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _acct_state(username: str, info: dict, now: float, banned: set) -> str:
    """État d'un compte pour l'accountability :
    'banned'  -> banni (exclu)
    'never'   -> scanné OK mais AUCUN reel jamais posté (exclu)
    'nodata'  -> jamais scanné / erreur / privé (on ne sait pas -> exclu)
    'silent'  -> a des reels mais rien depuis >48 h  => PÉNALISÉ
    'ok'      -> a posté il y a <48 h
    Seul 'silent' déclenche une pénalité."""
    if (username or "").strip().lower() in banned:
        return "banned"
    if not info or info.get("error"):
        return "nodata"
    if info.get("is_private"):
        return "nodata"
    # scanné avec succès : jamais posté de reel ?
    if not (info.get("reels_count") or info.get("last_post_ts")):
        return "never"
    last = info.get("last_post_ts") or 0
    if not last:                 # a des reels mais aucun timestamp exploitable
        return "nodata"
    return "silent" if (now - last) > SILENCE_SEC else "ok"


# ---------- SCAN (dernier post + vues par compte) ----------
def scan_all(limit_reels: int = 6, sleep: float = 0.4) -> dict:
    """Scrape chaque compte JB et met à jour jb_activity.json. Best-effort.
    Retourne {scanned, errors, total}."""
    try:
        import jailbreak as jb
        import insta_scraper as ig
    except Exception as e:
        return {"error": f"module indispo: {e}"}
    data = jb._load()
    act = _load(ACT_FILE)
    accounts = []
    for identity, entry in (data or {}).items():
        for a in (entry.get("accounts") or []):
            u = (a.get("username") or "").strip()
            if u:
                accounts.append(u)
    accounts = list(dict.fromkeys(accounts))  # dédoublonne en gardant l'ordre
    _scanning.update(on=True, done=0, total=len(accounts), errors=0)
    now0 = time.time()
    try:
        for u in accounts:
            try:
                res = ig._scrape_via_rapidapi(u, limit=limit_reels)
            except Exception as e:
                res = {"error": str(e)[:120]}
            now = time.time()
            if res.get("error"):
                rec = act.get(u) or {}
                rec.update(error=str(res["error"])[:120], scanned_at=now)
                act[u] = rec
                _scanning["errors"] += 1
            else:
                reels = res.get("reels") or []
                taken = [r.get("taken_at") or 0 for r in reels if r.get("taken_at")]
                last_ts = max(taken) if taken else 0
                last_reel = max(reels, key=lambda r: r.get("taken_at") or 0) if reels else {}
                v14 = sum((r.get("views") or 0) for r in reels
                          if (r.get("taken_at") or 0) >= now - WEEKS2_SEC)
                act[u] = {
                    "last_post_ts": last_ts,
                    "last_views": (last_reel or {}).get("views") or 0,
                    "views_14d": v14,
                    "reels_count": len(reels),
                    "is_private": bool((res.get("profile") or {}).get("is_private")),
                    "scanned_at": now,
                    "error": "",
                }
            _scanning["done"] += 1
            if sleep:
                time.sleep(sleep)
        _save(ACT_FILE, act)
        try:
            SCAN_MARK.write_text(_today(), encoding="utf-8")
        except Exception:
            pass
    finally:
        _scanning["on"] = False
    return {"scanned": _scanning["done"] - _scanning["errors"],
            "errors": _scanning["errors"], "total": len(accounts),
            "seconds": round(time.time() - now0)}


# ---------- PÉNALITÉS (1/VA/jour si ≥1 compte silencieux >48h) ----------
def compute_penalties(day: str = None) -> dict:
    """Pour le jour donné (défaut aujourd'hui) : +1 pénalité à chaque VA ayant au
    moins un compte silencieux >48 h. Dédup par (VA, jour). Retourne {added, vas}."""
    try:
        import jailbreak as jb
    except Exception:
        return {"added": 0}
    day = day or _today()
    data = jb._load()
    act = _load(ACT_FILE)
    banned = _banned()
    now = time.time()
    faulty = {}  # va_lower -> {"va": affichage, "accounts": set(usernames fautifs)}
    for entry in (data or {}).values():
        for a in (entry.get("accounts") or []):
            va = (a.get("va") or "").strip()
            if not va:
                continue
            u = (a.get("username") or "").strip()
            # SEUL l'état 'silent' pénalise (banni / jamais posté / sans data = exclus)
            if _acct_state(u, act.get(u), now, banned) == "silent":
                f = faulty.setdefault(va.lower(), {"va": va, "accounts": set()})
                if u:
                    f["accounts"].add(u)
    with _lock:
        pen = _load(PEN_FILE)
        added = 0
        for vl, info in faulty.items():
            rec = pen.setdefault(vl, {"va": info["va"], "days": [], "by_day": {}})
            rec["va"] = info["va"]
            rec.setdefault("by_day", {})
            if day not in rec["days"]:
                rec["days"].append(day)
                added += 1
            # quels comptes ont provoqué la pénalité ce jour-là (union)
            prev = set(rec["by_day"].get(day, []))
            rec["by_day"][day] = sorted(prev | info["accounts"])
        _save(PEN_FILE, pen)
    return {"added": added, "vas": sorted(v["va"] for v in faulty.values())}


def add_manual_penalty(va: str, day: str = None) -> bool:
    """Ajoute une pénalité manuelle à un VA (jour précis, défaut aujourd'hui)."""
    va = (va or "").strip()
    if not va:
        return False
    day = day or _today()
    with _lock:
        pen = _load(PEN_FILE)
        rec = pen.setdefault(va.lower(), {"va": va, "days": []})
        rec["va"] = va
        rec["days"].append(day)  # manuel = peut cumuler dans la journée
        _save(PEN_FILE, pen)
    return True


def remove_penalty(va: str, day: str = None) -> bool:
    """Retire UNE pénalité d'un VA (dernière du jour donné, défaut aujourd'hui)."""
    va = (va or "").strip().lower()
    day = day or _today()
    with _lock:
        pen = _load(PEN_FILE)
        rec = pen.get(va)
        if not rec or day not in rec.get("days", []):
            return False
        rec["days"].remove(day)
        _save(PEN_FILE, pen)
    return True


# ---------- RÉSUMÉ pour le site ----------
def va_summary(month: str = None) -> list:
    """Par VA : nb comptes, comptes silencieux MAINTENANT, sans données, pénalités
    du mois, identités concernées, vues 14j cumulées. Trié par pénalités décroissant."""
    try:
        import jailbreak as jb
    except Exception:
        return []
    month = month or _today()[:7]
    data = jb._load()
    act = _load(ACT_FILE)
    pen = _load(PEN_FILE)
    banned = _banned()
    now = time.time()
    vas = {}
    for identity, entry in (data or {}).items():
        for a in (entry.get("accounts") or []):
            va = (a.get("va") or "").strip()
            if not va:
                continue
            vl = va.lower()
            u = (a.get("username") or "").strip()
            d = vas.setdefault(vl, {"va": va, "accounts": 0, "silent_now": 0,
                                    "no_data": 0, "banned": 0, "never": 0, "views_14d": 0,
                                    "identities": set(), "silent_accounts": []})
            d["accounts"] += 1
            d["identities"].add(identity)
            info = act.get(u) or {}
            state = _acct_state(u, info, now, banned)
            d["views_14d"] += info.get("views_14d") or 0
            if state == "banned":
                d["banned"] += 1
            elif state == "never":
                d["never"] += 1           # jamais posté -> exclu (ni pénalité ni "sans data")
            elif state == "nodata":
                d["no_data"] += 1
            elif state == "silent":
                d["silent_now"] += 1
                last = info.get("last_post_ts") or 0
                d["silent_accounts"].append({
                    "u": u, "identity": identity, "hours": int((now - last) // 3600)})
    out = []
    for vl, d in vas.items():
        rec = pen.get(vl) or {"days": []}
        d["penalties_month"] = sum(1 for day in rec.get("days", []) if str(day).startswith(month))
        d["identities"] = sorted(d["identities"])
        d["silent_accounts"].sort(key=lambda x: -x["hours"])
        out.append(d)
    out.sort(key=lambda x: (-x["penalties_month"], -x["silent_now"], x["va"].lower()))
    return out


def scan_status() -> dict:
    d = dict(_scanning)
    d["last_scan"] = ""
    try:
        d["last_scan"] = SCAN_MARK.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return d


# ---------- Job quotidien ----------
def _daily_loop():
    while True:
        try:
            if scan_status().get("last_scan") != _today() and not _scanning["on"]:
                scan_all()
                compute_penalties()
        except Exception as e:
            print(f"[jb_activity] daily: {e}", flush=True)
        time.sleep(1800)  # revérifie toutes les 30 min (rattrape si le bot était off)


def start_daily(delay: float = 60.0) -> None:
    """Démarre le job quotidien (idempotent)."""
    if getattr(start_daily, "_started", False):
        return
    start_daily._started = True

    def _run():
        time.sleep(delay)
        _daily_loop()
    threading.Thread(target=_run, daemon=True, name="jb-activity").start()


def scan_async() -> None:
    """Lance un scan + calcul pénalités en arrière-plan (bouton « scanner »)."""
    if _scanning["on"]:
        return

    def _run():
        scan_all()
        compute_penalties()
    threading.Thread(target=_run, daemon=True, name="jb-scan").start()
