"""sheets_sync.py — Sync 2 sens des comptes Jailbreak (jailbreak.json) <-> Google Sheet.

Structure : 1 ONGLET PAR IDENTITE (amelia, julia, emma, jessye, ...). Colonnes :
    id | username | password | email | two_fa | va | notes

Config (dans data/) :
  - google_service_account.json : cle du compte de service Google (uploadee par l'user)
  - sheets_config.json          : {"sheet_id": "..."}

FAIL-SAFE : si non configure / gspread absent -> no-op, aucune exception propagee a
l'appelant. Le push est declenche apres chaque `jailbreak._save`; le pull est fait par
un poller (cogs/sheetssync.py). Convergence : le push ne reecrit un onglet que si ses
comptes ont change (hash), le pull ne sauve que s'il y a un vrai changement.
"""
from __future__ import annotations

import json
import time
import hashlib
import threading
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "sheets_config.json"
SA_FILE = DATA_DIR / "google_service_account.json"

HEADER = ["id", "username", "password", "email", "two_fa", "va", "notes"]
_FIELDS = ("username", "password", "email", "two_fa", "va", "notes")

_lock = threading.Lock()
_last_hash: dict = {}   # identity -> hash des comptes (evite les reecritures inutiles)


# ---------- Config ----------
def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def gspread_available() -> bool:
    try:
        import gspread  # noqa: F401
        from google.oauth2.service_account import Credentials  # noqa: F401
        return True
    except Exception:
        return False


def is_configured() -> bool:
    return bool(load_config().get("sheet_id")) and SA_FILE.exists()


def service_account_email() -> str:
    try:
        return json.loads(SA_FILE.read_text(encoding="utf-8")).get("client_email", "")
    except Exception:
        return ""


# ---------- Client Google ----------
def _client():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(SA_FILE), scopes=scopes)
    return gspread.authorize(creds)


def _open_sheet():
    return _client().open_by_key(load_config()["sheet_id"])


def test_connection() -> tuple:
    """(ok: bool, message: str)."""
    if not gspread_available():
        return False, "Librairie `gspread` absente sur le VPS — fais `pip install gspread`."
    if not is_configured():
        return False, "Pas encore configuré (clé de service + sheet_id manquants)."
    try:
        sh = _open_sheet()
        return True, f"Connecté au Sheet « {sh.title} »."
    except Exception as e:
        return False, f"Accès au Sheet impossible : {e}"


# ---------- Helpers ----------
def _acct_row(a: dict) -> list:
    return [str(a.get("id", "") or ""), a.get("username", "") or "",
            a.get("password", "") or "", a.get("email", "") or "",
            a.get("two_fa", "") or "", a.get("va", "") or "", a.get("notes", "") or ""]


def _accts_hash(accts: list) -> str:
    payload = json.dumps([_acct_row(a) for a in accts], ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _ws_write(ws, rows) -> None:
    """Ecrit `rows` a partir de A1, tolerant aux differences de signature gspread 5/6."""
    try:
        ws.update(range_name="A1", values=rows, value_input_option="RAW")
    except TypeError:
        try:
            ws.update("A1", rows, value_input_option="RAW")   # gspread 5.x
        except Exception:
            ws.update(rows)                                    # dernier recours


def _rows_hash(rows) -> str:
    return hashlib.md5(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------- Vues LECTURE SEULE : 1 onglet par (identité, VA), nom "identité va" ----------
_VIEW_HEADER = ["username", "password", "email", "two_fa", "notes"]


def _safe_tab_title(name: str) -> str:
    t = (name or "").strip()
    for ch in ":\\/?*[]":
        t = t.replace(ch, " ")
    return t[:99]


def _view_tab_names() -> set:
    try:
        return {str(x).strip().lower() for x in (load_config().get("va_view_tabs") or [])}
    except Exception:
        return set()


def _is_va_tab(title: str) -> bool:
    """Onglet 'vue' (lecture seule) -> ignoré par le poller."""
    t = (title or "").strip().lower()
    return t.startswith("👤") or t in _view_tab_names()


def _push_va_views(sh, existing: dict, data: dict, force: bool) -> None:
    """Un onglet LECTURE SEULE par couple (identité, VA), nommé 'identité va' (ex
    'lola jhon'), trié pour grouper les mêmes identités côte à côte. Le poller les
    ignore (le nom n'est pas une identité). Nettoie les vues obsolètes (suivi via
    config 'va_view_tabs' + anciens onglets 👤). Réordonne si la structure change."""
    pairs = {}
    for identity, entry in (data or {}).items():
        if not isinstance(entry, dict):
            continue
        for a in entry.get("accounts") or []:
            va = (a.get("va") or "").strip()
            if not va:
                continue
            pairs.setdefault((str(identity), va), []).append([
                a.get("username", "") or "", a.get("password", "") or "",
                a.get("email", "") or "", a.get("two_fa", "") or "",
                a.get("notes", "") or ""])
    wanted = {}
    changed = False
    for (identity, va), rows in pairs.items():
        title = _safe_tab_title(f"{identity} {va}")
        key = title.strip().lower()
        full = [_VIEW_HEADER] + sorted(rows, key=lambda r: r[0].lower())
        h = _rows_hash(full)
        ws = existing.get(key)
        if ws is None:
            ws = sh.add_worksheet(title=title, rows=max(len(full) + 5, 20), cols=len(_VIEW_HEADER))
            existing[key] = ws
            changed = True
        if force or _last_hash.get(title) != h:
            ws.clear()
            _ws_write(ws, full)
            _last_hash[title] = h
        wanted[key] = ws
    # Vues obsolètes (suivies en config, ou anciens onglets 👤) -> supprimées
    for key in (_view_tab_names() | {k for k in list(existing) if str(k).startswith("👤")}):
        if key in wanted:
            continue
        ws = existing.get(key)
        if ws is not None:
            try:
                sh.del_worksheet(ws)
                existing.pop(key, None)
                changed = True
            except Exception:
                pass
    # Mémoriser la liste des vues (nettoyage futur + skip du poller)
    try:
        cfg = load_config()
        cfg["va_view_tabs"] = sorted(wanted.keys())
        save_config(cfg)
    except Exception:
        pass
    # Réordonner : autres (Feuille 1) + identités triées + vues triées (groupées par identité)
    if changed or force:
        try:
            identity_names = {str(k).strip().lower() for k in (data or {}).keys()}
            allws = sh.worksheets()
            views = [w for w in allws if w.title.strip().lower() in wanted]
            idents = [w for w in allws if w.title.strip().lower() in identity_names]
            others = [w for w in allws if w not in views and w not in idents]
            idents.sort(key=lambda w: w.title.lower())
            views.sort(key=lambda w: w.title.lower())
            sh.reorder_worksheets(others + idents + views)
        except Exception:
            pass


# ---------- Site -> Sheet ----------
def push_all(data: dict, force: bool = False) -> bool:
    """Ecrit chaque identite dans SON onglet (rewrite). Ne reecrit que les onglets dont
    les comptes ont change (sauf force=True). Best-effort (retourne False si echec)."""
    if not (is_configured() and gspread_available()):
        return False
    try:
        with _lock:
            sh = _open_sheet()
            existing = {ws.title.strip().lower(): ws for ws in sh.worksheets()}
            for identity, entry in (data or {}).items():
                if not isinstance(entry, dict):
                    continue
                accts = entry.get("accounts") or []
                h = _accts_hash(accts)
                if not force and _last_hash.get(identity) == h:
                    continue
                ws = existing.get(str(identity).strip().lower())
                if ws is None:
                    ws = sh.add_worksheet(title=str(identity),
                                          rows=max(len(accts) + 10, 20), cols=len(HEADER))
                    existing[str(identity).strip().lower()] = ws
                rows = [HEADER] + [_acct_row(a) for a in accts]
                ws.clear()
                _ws_write(ws, rows)
                _last_hash[identity] = h
            # Vues lecture seule par VA (onglets 👤 Nom)
            _push_va_views(sh, existing, data, force)
            return True
    except Exception as e:
        print(f"[sheets_sync] push_all: {e}", flush=True)
        return False


def push_all_async(data: dict) -> None:
    """Push en arriere-plan (non bloquant, ne casse jamais l'appelant)."""
    if not (is_configured() and gspread_available()):
        return
    try:
        snapshot = json.loads(json.dumps(data or {}))  # copie profonde
        threading.Thread(target=push_all, args=(snapshot,), daemon=True).start()
    except Exception:
        pass


# ---------- Sheet -> Site ----------
def pull_all() -> dict | None:
    """Lit tous les onglets -> {identity_lower: [row dict, ...]}. None si erreur."""
    if not (is_configured() and gspread_available()):
        return None
    try:
        sh = _open_sheet()
        out = {}
        for ws in sh.worksheets():
            if _is_va_tab(ws.title):
                continue  # onglet vue-par-VA (lecture seule) -> jamais lu comme identité
            identity = ws.title.strip().lower()
            values = ws.get_all_values()
            if not values:
                out[identity] = []
                continue
            header = [str(h).strip().lower() for h in values[0]]
            accts = []
            for r in values[1:]:
                d = {header[i]: (str(r[i]).strip() if i < len(r) else "")
                     for i in range(len(header))}
                if not (d.get("username") or "").strip():
                    continue
                accts.append(d)
            out[identity] = accts
        return out
    except Exception as e:
        print(f"[sheets_sync] pull_all: {e}", flush=True)
        return None


def pull_and_merge() -> tuple:
    """Applique le Sheet dans jailbreak.json : upsert par `id`, ajoute les nouveaux
    (id vide/inconnu), supprime ceux absents du Sheet (ANTI-WIPE : seulement si
    l'onglet contient au moins 1 compte). Retourne (changed: bool, summary: str)."""
    import jailbreak as jb
    sheet = pull_all()
    if sheet is None:
        return False, "Sheet indisponible"
    data = jb._load()

    used_ids = set()
    for entry in data.values():
        for a in (entry.get("accounts") or []):
            try:
                used_ids.add(int(a.get("id", 0)))
            except Exception:
                pass
    _next = [int(time.time() * 1000)]

    def _gen_id():
        while _next[0] in used_ids:
            _next[0] += 1
        nid = _next[0]
        used_ids.add(nid)
        _next[0] += 1
        return nid

    added = updated = removed = 0
    for identity, rows in sheet.items():
        entry = data.get(identity)
        if not isinstance(entry, dict):
            continue  # identite pas dans jailbreak (= dossier absent) -> on ne cree pas
        accts = entry.setdefault("accounts", [])
        by_id = {}
        for a in accts:
            try:
                by_id[int(a.get("id", 0))] = a
            except Exception:
                pass
        seen = set()
        for row in rows:
            username = (row.get("username") or "").strip()
            if not username:
                continue
            rid = (row.get("id") or "").strip()
            acct = by_id.get(int(rid)) if rid.isdigit() else None
            if acct is not None:
                seen.add(int(acct.get("id", 0)))
                ch = False
                for f in _FIELDS:
                    v = (row.get(f) or "").strip()
                    if (acct.get(f) or "") != v:
                        acct[f] = v
                        ch = True
                if ch:
                    updated += 1
            else:
                nid = _gen_id()
                accts.append({
                    "id": nid, "username": username[:80],
                    "password": (row.get("password") or "").strip()[:200],
                    "email": (row.get("email") or "").strip()[:120],
                    "two_fa": (row.get("two_fa") or "").strip()[:500],
                    "two_fa_validated": False,
                    "va": (row.get("va") or "").strip()[:60],
                    "notes": (row.get("notes") or "").strip()[:500],
                    "created_at": int(time.time()),
                })
                seen.add(nid)
                added += 1
        # Suppressions (anti-wipe : uniquement si l'onglet a des comptes)
        if rows:
            kept = []
            for a in accts:
                try:
                    aid = int(a.get("id", 0))
                except Exception:
                    aid = 0
                if aid and aid not in seen:
                    removed += 1
                else:
                    kept.append(a)
            entry["accounts"] = kept
            accts = kept
        # Assure que les 'va' des comptes existent dans entry["vas"] (coherence)
        vas = entry.setdefault("vas", [])
        have = {(_v.get("name") if isinstance(_v, dict) else _v or "").strip().lower()
                for _v in vas}
        for a in accts:
            va = (a.get("va") or "").strip()
            if va and va.lower() not in have:
                vas.append({"name": va, "discord_username": ""})
                have.add(va.lower())

    changed = bool(added or updated or removed)
    if changed:
        jb._save(data)  # declenche push_all_async -> converge (idempotent)
    return changed, f"+{added} ajout(s) · {updated} modif(s) · -{removed} suppr."
