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
import re
import time
import hashlib
import threading
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "sheets_config.json"
SA_FILE = DATA_DIR / "google_service_account.json"

HEADER = ["username", "password", "email", "two_fa", "va", "notes", "statut"]
_FIELDS = ("password", "email", "two_fa", "va", "notes")  # champs maj (username = la clé)

# Statut BANNI : lu du cache du scraper Insta (va_insta_3_stats_cache.json, clé =
# username). Colonne INFO en lecture seule (le pull ne la remonte pas au site).
_BAN_FILE = DATA_DIR / "va_insta_3_stats_cache.json"
_ban_cache = {"ts": 0.0, "set": set()}


def _banned_usernames() -> set:
    """Set des usernames (lower) marqués banned par le scraper. Cache 30 s."""
    now = time.time()
    if now - _ban_cache["ts"] < 30:
        return _ban_cache["set"]
    banned = set()
    try:
        d = json.loads(_BAN_FILE.read_text(encoding="utf-8"))
        for handle, st in (d or {}).items():
            if isinstance(st, dict) and st.get("banned"):
                banned.add(str(handle).strip().lower())
    except Exception:
        pass
    _ban_cache["ts"] = now
    _ban_cache["set"] = banned
    return banned


def _statut(username: str) -> str:
    return "🚫 BANNI" if (username or "").strip().lower() in _banned_usernames() else ""

_lock = threading.Lock()
_last_hash: dict = {}   # identity -> hash des comptes (evite les reecritures inutiles)
# Diagnostic du dernier push mode dossier (pour messages d'erreur clairs)
_LAST_FOLDER: dict = {"ok": 0, "err": ""}


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
    cfg = load_config()
    return SA_FILE.exists() and bool(cfg.get("sheet_id") or cfg.get("folder_id"))


def set_folder(url_or_id: str) -> str:
    """Active le mode « 1 classeur par identité » : enregistre le dossier Drive
    (partagé avec le compte de service). Retourne l'id du dossier."""
    fid = parse_folder_id(url_or_id)
    cfg = load_config()
    cfg["folder_id"] = fid
    cfg.setdefault("sheets", {})
    save_config(cfg)
    return fid


def service_account_email() -> str:
    try:
        return json.loads(SA_FILE.read_text(encoding="utf-8")).get("client_email", "")
    except Exception:
        return ""


# ---------- Client Google ----------
def _client():
    import gspread
    from google.oauth2.service_account import Credentials
    # drive : requis pour CRÉER des classeurs + les ranger dans un dossier partagé
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(str(SA_FILE), scopes=scopes)
    return gspread.authorize(creds)


# ---------- Mode « 1 classeur par identité » (dossier Drive) ----------
def parse_folder_id(url_or_id: str) -> str:
    """Extrait l'ID d'un dossier Drive depuis un lien complet ou un ID brut."""
    s = (url_or_id or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    return s  # supposé déjà un ID


def folder_mode() -> bool:
    return bool(load_config().get("folder_id"))


def is_paused() -> bool:
    """Sync gelée (sécurité) : ni push ni pull. Évite d'écraser des données."""
    return bool(load_config().get("paused"))


def set_paused(v: bool) -> bool:
    cfg = load_config()
    cfg["paused"] = bool(v)
    save_config(cfg)
    return cfg["paused"]


def restore_from_single_sheet() -> tuple:
    """URGENCE — réimporte les comptes depuis TOUTES les sources Google dispo :
    les classeurs par identité (mode dossier) ET l'ancien Sheet unique.
    100 % ADDITIF : n'efface JAMAIS rien, ajoute seulement les comptes absents.
    Reconstruit aussi la liste des VA."""
    if not (SA_FILE.exists() and gspread_available()):
        return False, "Clé de service / gspread manquants."
    cfg = load_config()
    try:
        import jailbreak as jb
        gc = _client()
    except Exception as e:
        return False, f"Connexion Google impossible : {e}"
    # Sources : classeurs par identité + ancien Sheet unique
    books, errs = [], []
    for _key, _sid in (cfg.get("sheets") or {}).items():
        try:
            books.append(gc.open_by_key(_sid))
        except Exception as e:
            errs.append(f"{_key}: {str(e)[:40]}")
    sid = (cfg.get("sheet_id") or "").strip()
    if sid:
        try:
            books.append(gc.open_by_key(sid))
        except Exception as e:
            errs.append(f"ancien Sheet: {str(e)[:40]}")
    if not books:
        return False, "Aucun classeur lisible. " + (" · ".join(errs) if errs else "")
    data = jb._load()
    known = {str(k).strip().lower(): k for k in (data or {}).keys()}
    used_ids = set()
    for entry in (data or {}).values():
        for a in (entry.get("accounts") or []):
            try:
                used_ids.add(int(a.get("id", 0)))
            except Exception:
                pass
    nxt = [int(time.time() * 1000)]

    def _gen():
        while nxt[0] in used_ids:
            nxt[0] += 1
        v = nxt[0]
        used_ids.add(v)
        nxt[0] += 1
        return v

    added, tabs = 0, 0
    all_ws = []
    for _b in books:
        try:
            all_ws += list(_b.worksheets())
        except Exception:
            pass
    for ws in all_ws:
        title = ws.title.strip()
        tl = title.lower()
        identity, va_tab = None, ""
        if tl in known:
            identity = known[tl]
        else:
            parts = title.split(" ", 1)
            if len(parts) == 2 and parts[0].strip().lower() in known:
                identity = known[parts[0].strip().lower()]
                va_tab = parts[1].strip()
        if not identity:
            continue
        try:
            rows = _parse_ws(ws)
        except Exception:
            continue
        if not rows:
            continue
        tabs += 1
        entry = data.setdefault(identity, {"vas": [], "accounts": []})
        entry.setdefault("accounts", [])
        entry.setdefault("vas", [])
        by_u = {(a.get("username") or "").strip().lower(): a
                for a in entry["accounts"] if (a.get("username") or "").strip()}
        for r in rows:
            u = (r.get("username") or "").strip()
            if not u or u.lower() in by_u:
                continue
            va = (r.get("va") or "").strip() or va_tab
            acct = _row_new_account(u, r, va, _gen)
            entry["accounts"].append(acct)
            by_u[u.lower()] = acct
            added += 1
    # reconstruit la liste des VA à partir des comptes
    for entry in (data or {}).values():
        if not isinstance(entry, dict):
            continue
        have = {str((v.get("name") if isinstance(v, dict) else v) or "").strip().lower()
                for v in (entry.get("vas") or [])}
        for v in sorted({(a.get("va") or "").strip()
                         for a in (entry.get("accounts") or []) if (a.get("va") or "").strip()}):
            if v.lower() not in have:
                entry.setdefault("vas", []).append(v)
                have.add(v.lower())
    jb._save(data)
    msg = f"{added} compte(s) restauré(s) — {len(books)} classeur(s), {tabs} onglet(s) lus."
    if errs:
        msg += f" (illisibles : {' · '.join(errs[:3])})"
    return True, msg


def identity_names() -> list:
    """Liste des identités jailbreak (pour dire à l'user quels classeurs créer)."""
    try:
        import jailbreak as jb
        return [str(k) for k in (jb._load() or {}).keys()]
    except Exception:
        return []


def _ensure_identity_sheet(gc, identity: str, cfg: dict):
    """Retourne le classeur Google de l'identité, en le CRÉANT dans le dossier
    partagé s'il n'existe pas encore. Mémorise l'id dans cfg['sheets']."""
    key = str(identity).strip().lower()
    sheets = cfg.setdefault("sheets", {})
    sid = sheets.get(key)
    if sid:
        try:
            return gc.open_by_key(sid)
        except Exception:
            pass  # supprimé / inaccessible -> on retente
    title = f"VA JB — {identity}"
    # 1) RÉUTILISE un classeur EXISTANT (créé par l'user dans le dossier partagé) ->
    #    AUCUNE création, donc pas de blocage "quota compte de service". Tolérant sur
    #    le nom : « VA JB — lola », « lola », ou tout titre contenant « lola ».
    for cand in (title, str(identity)):
        try:
            sh = gc.open(cand)
            sheets[key] = sh.id
            save_config(cfg)
            return sh
        except Exception:
            pass
    try:
        fid0 = cfg.get("folder_id")
        if fid0 and hasattr(gc, "list_spreadsheet_files"):
            for f in gc.list_spreadsheet_files(folder_id=fid0):
                words = (f.get("name") or "").strip().lower().replace("—", " ").split()
                if key in words:
                    sh = gc.open_by_key(f["id"])
                    sheets[key] = sh.id
                    save_config(cfg)
                    return sh
    except Exception:
        pass
    # 2) sinon on TENTE de créer (échoue si compte de service sans quota de stockage
    #    -> l'appelant remonte l'erreur claire).
    fid = cfg.get("folder_id") or None
    try:
        sh = gc.create(title, folder_id=fid)
    except TypeError:
        sh = gc.create(title)
    sheets[key] = sh.id
    save_config(cfg)
    # Sécurité d'accès : partage direct avec l'owner si un email est configuré
    owner = cfg.get("share_email")
    if owner:
        try:
            sh.share(owner, perm_type="user", role="writer")
        except Exception:
            pass
    return sh


def _open_sheet():
    return _client().open_by_key(load_config()["sheet_id"])


def test_connection() -> tuple:
    """(ok: bool, message: str)."""
    if not gspread_available():
        return False, "Librairie `gspread` absente sur le VPS — fais `pip install gspread`."
    if not is_configured():
        return False, "Pas encore configuré (clé de service + sheet_id/dossier manquants)."
    cfg = load_config()
    try:
        if cfg.get("folder_id"):
            gc = _client()
            sheets = cfg.get("sheets") or {}
            n = len(sheets)
            if sheets:
                sh = gc.open_by_key(next(iter(sheets.values())))
                return True, f"Mode 1 classeur/identité — {n} classeur(s) (ex : « {sh.title} »)."
            return True, "Mode 1 classeur/identité — dossier configuré, 0 classeur (fais `/sheetsync push`)."
        sh = _open_sheet()
        return True, f"Connecté au Sheet « {sh.title} »."
    except Exception as e:
        return False, f"Accès impossible : {e}"


# ---------- Helpers ----------
def _acct_row(a: dict) -> list:
    u = a.get("username", "") or ""
    return [u, a.get("password", "") or "",
            a.get("email", "") or "", a.get("two_fa", "") or "",
            a.get("va", "") or "", a.get("notes", "") or "", _statut(u)]


def _accts_hash(accts: list) -> str:
    payload = json.dumps([_acct_row(a) for a in accts], ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _entry_hash(entry: dict) -> str:
    """Hash d'une identité = ses COMPTES **et** sa liste de VA. Indispensable :
    sinon ajouter un VA sans ajouter de compte laissait l'identité « inchangée »
    et son onglet VA n'était jamais créé."""
    accts = entry.get("accounts") or []
    vas = sorted(str((v.get("name") if isinstance(v, dict) else v) or "").strip().lower()
                 for v in (entry.get("vas") or []))
    payload = json.dumps({"a": [_acct_row(a) for a in accts], "v": vas}, ensure_ascii=False)
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
_VIEW_HEADER = ["username", "password", "email", "two_fa", "notes", "statut"]


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


def _push_va_views(sh, existing: dict, data: dict, force: bool, save_cfg: bool = True) -> list:
    """Un onglet par couple (identité, VA), nommé 'identité va' (ex
    'lola jhon'), trié pour grouper les mêmes identités côte à côte. Le poller les
    ignore (le nom n'est pas une identité). Nettoie les vues obsolètes (suivi via
    config 'va_view_tabs' + anciens onglets 👤). Réordonne si la structure change."""
    pairs = {}
    canon = {}  # (identité, va) insensible à la casse -> clé canonique

    def _key(identity, va):
        k = (str(identity).strip().lower(), va.strip().lower())
        if k not in canon:
            canon[k] = (str(identity), va.strip())
        return canon[k]

    for identity, entry in (data or {}).items():
        if not isinstance(entry, dict):
            continue
        # 1) TOUS les VAs déclarés -> onglet créé même SANS compte (sinon les
        #    nouveaux VAs — bo7/andry — n'apparaissaient jamais dans le Sheet)
        for v in entry.get("vas") or []:
            name = (v.get("name") if isinstance(v, dict) else v) or ""
            name = str(name).strip()
            if name:
                pairs.setdefault(_key(identity, name), [])
        # 2) les comptes remplissent les onglets
        for a in entry.get("accounts") or []:
            va = (a.get("va") or "").strip()
            if not va:
                continue
            _u = a.get("username", "") or ""
            pairs.setdefault(_key(identity, va), []).append([
                _u, a.get("password", "") or "",
                a.get("email", "") or "", a.get("two_fa", "") or "",
                a.get("notes", "") or "", _statut(_u)])
    wanted = {}
    changed = False
    for (identity, va), rows in pairs.items():
        title = _safe_tab_title(f"{identity} {va}")
        key = title.strip().lower()
        # ORDRE D'AJOUT (pas alphabétique) : rows est déjà dans l'ordre du fichier
        full = [_VIEW_HEADER] + rows
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
    # Mémoriser la liste des vues (nettoyage futur). En mode dossier on accumule
    # côté appelant (save_cfg=False) pour ne pas écraser les vues des autres classeurs.
    if save_cfg:
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
    return wanted   # {clé onglet -> worksheet} (VA views créées)


# ---------- Mise en forme "pro" des classeurs ----------
_HDR_BG = {"red": 0.118, "green": 0.161, "blue": 0.231}   # bleu nuit
_BAND2 = {"red": 0.949, "green": 0.965, "blue": 0.980}    # ligne paire très claire
_WHITE = {"red": 1, "green": 1, "blue": 1}


def _beautify_sheet(sh, tab_ncols: dict) -> None:
    """Applique un style pro à des onglets d'un classeur, en UN SEUL batch :
    en-tête bleu nuit figé (texte blanc gras) + colonnes auto-ajustées + lignes
    alternées + filtre. Idempotent (supprime les bandes existantes avant)."""
    if not tab_ncols:
        return
    try:
        meta = sh.fetch_sheet_metadata()
    except Exception:
        return
    reqs = []
    # 1) supprime les bandes existantes (sinon addBanding échoue au 2e passage)
    for s in meta.get("sheets", []):
        for b in (s.get("bandedRanges") or []):
            reqs.append({"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}})
    for s in meta.get("sheets", []):
        sid = s["properties"]["sheetId"]
        if sid not in tab_ncols:
            continue
        ncols = max(1, int(tab_ncols[sid]))
        rowcount = int(s["properties"].get("gridProperties", {}).get("rowCount", 1000))
        full = {"sheetId": sid, "startRowIndex": 0, "endRowIndex": rowcount,
                "startColumnIndex": 0, "endColumnIndex": ncols}
        head = {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": ncols}
        reqs += [
            {"updateSheetProperties": {"properties": {"sheetId": sid,
                "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": head, "cell": {"userEnteredFormat": {
                "backgroundColor": _HDR_BG, "verticalAlignment": "MIDDLE",
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)"}},
            {"autoResizeDimensions": {"dimensions": {"sheetId": sid,
                "dimension": "COLUMNS", "startIndex": 0, "endIndex": ncols}}},
            {"addBanding": {"bandedRange": {"range": full, "rowProperties": {
                "headerColor": _HDR_BG, "firstBandColor": _WHITE, "secondBandColor": _BAND2}}}},
            {"setBasicFilter": {"filter": {"range": full}}},
        ]
    if reqs:
        try:
            sh.batch_update({"requests": reqs})
        except Exception as e:
            print(f"[sheets_sync] beautify: {e}", flush=True)


# ---------- Site -> Sheet ----------
def _dedup_accounts(data: dict) -> int:
    """Retire les comptes en double (même username, insensible casse) DANS une
    identité — garde la ligne la plus remplie. Retourne le nombre supprimé.
    (Un redémarrage pile pendant un ajout avait pu créer des doublons qui
    s'auto-répliquaient à chaque sync.)"""
    removed = 0
    for entry in (data or {}).values():
        if not isinstance(entry, dict):
            continue
        seen = {}
        out = []
        for a in (entry.get("accounts") or []):
            u = (a.get("username") or "").strip().lower()
            if not u:
                out.append(a)
                continue
            if u not in seen:
                seen[u] = a
                out.append(a)
            else:
                # garde la ligne la plus complète (plus de champs remplis)
                prev = seen[u]
                score = lambda x: sum(1 for f in ("password", "email", "two_fa", "notes") if (x.get(f) or "").strip())
                if score(a) > score(prev):
                    out[out.index(prev)] = a
                    seen[u] = a
                removed += 1
        if removed:
            entry["accounts"] = out
    return removed


def push_all(data: dict, force: bool = False) -> bool:
    """Dispatcher : mode DOSSIER (1 classeur/identité) si folder_id configuré,
    sinon ancien mode (1 seul Sheet, N onglets)."""
    # En PAUSE : on bloque les push AUTOMATIQUES, mais un push MANUEL (force=True)
    # reste autorisé — c'est le sens site -> Sheet, il ne peut pas vider le site,
    # et il est indispensable pour repeupler les classeurs après une restauration.
    if is_paused() and not force:
        return False
    if not (is_configured() and gspread_available()):
        return False
    if folder_mode():
        return _push_all_folder(data, force)
    return _push_all_single(data, force)


def _push_all_folder(data: dict, force: bool = False) -> bool:
    """1 CLASSEUR par identité (rangé dans le dossier partagé). L'onglet principal
    est nommé comme l'identité (compat avec pull_and_merge). Best-effort."""
    try:
        if _dedup_accounts(data):
            import jailbreak as jb
            jb._save(data)
    except Exception:
        pass
    cfg = load_config()
    _LAST_FOLDER["ok"] = 0
    _LAST_FOLDER["err"] = ""
    all_views = []
    try:
        with _lock:
            gc = _client()
            for identity, entry in (data or {}).items():
                if not isinstance(entry, dict):
                    continue
                accts = entry.get("accounts") or []
                h = _entry_hash(entry)
                if not force and _last_hash.get(identity) == h:
                    continue
                try:
                    sh = _ensure_identity_sheet(gc, identity, cfg)
                except Exception as e:
                    if not _LAST_FOLDER["err"]:
                        _LAST_FOLDER["err"] = str(e)[:250]
                    print(f"[sheets_sync] création classeur '{identity}': {e}", flush=True)
                    continue
                ws = sh.sheet1  # 1re feuille = TOUS les comptes de l'identité
                if ws.title.strip().lower() != str(identity).strip().lower():
                    try:
                        ws.update_title(str(identity))
                    except Exception:
                        pass
                rows = [HEADER] + [_acct_row(a) for a in accts]
                ws.clear()
                _ws_write(ws, rows)
                tab_ncols = {ws.id: len(HEADER)}   # onglet principal = 7 colonnes
                # + 1 ONGLET PAR VA dans CE classeur (ex 'julia Jaurel') — accumulé
                # pour la config (pas d'écrasement entre classeurs).
                try:
                    existing = {w.title.strip().lower(): w for w in sh.worksheets()}
                    va_wanted = _push_va_views(sh, existing, {identity: entry}, force, save_cfg=False)
                    all_views += list(va_wanted.keys())
                    for vw in va_wanted.values():
                        tab_ncols[vw.id] = len(_VIEW_HEADER)   # onglets VA = 6 colonnes
                except Exception as e:
                    print(f"[sheets_sync] vues VA '{identity}': {e}", flush=True)
                # Mise en forme "pro" de tout le classeur (1 batch)
                _beautify_sheet(sh, tab_ncols)
                _last_hash[identity] = h
                _LAST_FOLDER["ok"] += 1
            # sauvegarde unique de la liste des vues (tous classeurs confondus)
            try:
                c2 = load_config()
                c2["va_view_tabs"] = sorted(set(all_views))
                save_config(c2)
            except Exception:
                pass
            return True
    except Exception as e:
        if not _LAST_FOLDER["err"]:
            _LAST_FOLDER["err"] = str(e)[:250]
        print(f"[sheets_sync] push_all_folder: {e}", flush=True)
        return False


def _push_all_single(data: dict, force: bool = False) -> bool:
    """Ecrit chaque identite dans SON onglet (rewrite). Ne reecrit que les onglets dont
    les comptes ont change (sauf force=True). Best-effort (retourne False si echec)."""
    if not (is_configured() and gspread_available()):
        return False
    # Dédup préventive (les doublons se répliquaient à chaque sync)
    try:
        if _dedup_accounts(data):
            import jailbreak as jb
            jb._save(data)
    except Exception:
        pass
    try:
        with _lock:
            sh = _open_sheet()
            existing = {ws.title.strip().lower(): ws for ws in sh.worksheets()}
            for identity, entry in (data or {}).items():
                if not isinstance(entry, dict):
                    continue
                accts = entry.get("accounts") or []
                h = _entry_hash(entry)
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
    """Dispatcher : lit les classeurs par identité (mode dossier) OU le Sheet unique.
    Retourne {titre_onglet: [row dict, ...]}. None si erreur."""
    if not (is_configured() and gspread_available()):
        return None
    if folder_mode():
        return _pull_all_folder()
    return _pull_all_single()


def _parse_ws(ws) -> list:
    values = ws.get_all_values()
    if not values:
        return []
    header = [str(h).strip().lower() for h in values[0]]
    accts = []
    for r in values[1:]:
        d = {header[i]: (str(r[i]).strip() if i < len(r) else "")
             for i in range(len(header))}
        if not (d.get("username") or "").strip():
            continue
        accts.append(d)
    return accts


def _pull_all_folder() -> dict | None:
    """Lit chaque classeur par identité -> {titre_onglet: rows}. Les titres restent
    le nom de l'identité (compat pull_and_merge)."""
    cfg = load_config()
    try:
        gc = _client()
        out = {}
        for key, sid in (cfg.get("sheets") or {}).items():
            try:
                sh = gc.open_by_key(sid)
            except Exception:
                continue  # classeur supprimé / inaccessible -> ignoré (pas de wipe)
            for ws in sh.worksheets():
                out[ws.title.strip()] = _parse_ws(ws)
        return out
    except Exception as e:
        print(f"[sheets_sync] pull_all_folder: {e}", flush=True)
        return None


def _pull_all_single() -> dict | None:
    """Lit tous les onglets -> {identity_lower: [row dict, ...]}. None si erreur."""
    if not (is_configured() and gspread_available()):
        return None
    try:
        sh = _open_sheet()
        out = {}
        for ws in sh.worksheets():
            title = ws.title.strip()   # nom ORIGINAL (classification identité/VA dans le merge)
            values = ws.get_all_values()
            if not values:
                out[title] = []
                continue
            header = [str(h).strip().lower() for h in values[0]]
            accts = []
            for r in values[1:]:
                d = {header[i]: (str(r[i]).strip() if i < len(r) else "")
                     for i in range(len(header))}
                if not (d.get("username") or "").strip():
                    continue
                accts.append(d)
            out[title] = accts
        return out
    except Exception as e:
        print(f"[sheets_sync] pull_all: {e}", flush=True)
        return None


def check_sync() -> str:
    """Compare jailbreak.json (site) et les onglets IDENTITÉ du Sheet -> rapport texte
    des écarts (comptes en plus / en moins par identité). Read-only (ne modifie rien)."""
    if not (is_configured() and gspread_available()):
        return "❌ Pas configuré / gspread absent."
    import jailbreak as jb
    data = jb._load()
    sheet = pull_all()
    if sheet is None:
        return "❌ Sheet illisible pour l'instant — réessaie."
    known = {str(k).strip().lower(): k for k in data.keys()}
    sheet_by_id = {}
    for title, rows in sheet.items():
        tl = title.strip().lower()
        if tl in known:
            sheet_by_id[tl] = {(r.get("username") or "").strip().lower()
                               for r in rows if (r.get("username") or "").strip()}
    lines = []
    tj = ts = tmiss = textra = 0
    for il, orig in sorted(known.items()):
        entry = data.get(orig) or {}
        ju = {(a.get("username") or "").strip().lower()
              for a in (entry.get("accounts") or []) if (a.get("username") or "").strip()}
        su = sheet_by_id.get(il, set())
        tj += len(ju)
        ts += len(su)
        miss = ju - su   # sur le site mais PAS dans le Sheet
        extra = su - ju  # dans le Sheet mais PAS sur le site
        tmiss += len(miss)
        textra += len(extra)
        if miss or extra or il not in sheet_by_id:
            tag = " (onglet absent du Sheet)" if il not in sheet_by_id else ""
            lines.append(
                f"• **{orig}** : site {len(ju)} / sheet {len(su)}{tag}"
                + (f" · +{len(extra)} en trop au Sheet" if extra else "")
                + (f" · {len(miss)} manquant(s) au Sheet" if miss else ""))
    head = f"📊 **Vérif sync** — site : **{tj}** comptes · Sheet : **{ts}** comptes\n"
    if not lines:
        return head + "✅ **Tout est identique** — aucun écart (même comptes des deux côtés)."
    body = "\n".join(lines[:20])
    if len(lines) > 20:
        body += f"\n… +{len(lines) - 20} autre(s)"
    return (head + f"⚠️ **Écarts** (manque au Sheet : {tmiss} · en trop au Sheet : {textra}) :\n"
            + body + "\n\n_Pour réaligner : `/sheetsync push` (site → Sheet) ou `/sheetsync pull` (Sheet → site)._")


def _row_new_account(u, r, va, gen_id):
    return {
        "id": gen_id(), "username": u[:80],
        "password": (r.get("password") or "").strip()[:200],
        "email": (r.get("email") or "").strip()[:120],
        "two_fa": (r.get("two_fa") or "").strip()[:500],
        "two_fa_validated": False,
        "va": (va or "").strip()[:60],
        "notes": (r.get("notes") or "").strip()[:500],
        "created_at": int(time.time()),
    }


def pull_and_merge() -> tuple:
    """Applique le Sheet dans jailbreak.json. 2 types d'onglets ÉDITABLES :
      - IDENTITÉ (nom = 'amelia') : gouverne TOUS les comptes de l'identité.
      - PAR VA (nom = 'amelia andry') : gouverne les comptes de cette identité gérés
        par ce VA.
    Règle : un compte est SUPPRIMÉ s'il est absent d'un onglet NON VIDE où il devrait
    figurer (identité OU son onglet VA) -> supprimer d'un côté supprime partout. Un
    username nouveau -> ajouté. ANTI-WIPE : un onglet VIDE n'entraîne aucune suppression.
    Retourne (changed, summary)."""
    import jailbreak as jb
    if is_paused():
        return False, "Sync en PAUSE (aucune modification appliquée)."
    sheet = pull_all()
    if sheet is None:
        return False, "Sheet indisponible"
    data = jb._load()
    known = {str(k).strip().lower() for k in data.keys()}

    # Classer les onglets du Sheet
    id_tabs = {}                 # identity_lower -> rows
    va_tabs = {}                 # identity_lower -> {va_lower: (va_display, rows)}
    for title, rows in sheet.items():
        tl = title.strip().lower()
        if tl in known:
            id_tabs[tl] = rows
        else:
            parts = title.strip().split(" ", 1)
            if len(parts) == 2 and parts[0].strip().lower() in known and parts[1].strip():
                va_tabs.setdefault(parts[0].strip().lower(), {})[parts[1].strip().lower()] = \
                    (parts[1].strip(), rows)

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
    for identity in list(data.keys()):
        entry = data[identity]
        if not isinstance(entry, dict):
            continue
        il = str(identity).strip().lower()
        va_meta = va_tabs.get(il, {})
        if il not in id_tabs and not va_meta:
            continue  # rien pour cette identité dans le Sheet -> on ne touche pas
        accts = entry.setdefault("accounts", [])

        # Présences (onglets NON VIDES seulement = anti-wipe)
        id_rows = id_tabs.get(il)
        id_present = None
        if id_rows:
            id_present = {(r.get("username") or "").strip().lower()
                          for r in id_rows if (r.get("username") or "").strip()}
        va_present = {}
        for vl, (vdisp, rows) in va_meta.items():
            if rows:
                va_present[vl] = {(r.get("username") or "").strip().lower()
                                  for r in rows if (r.get("username") or "").strip()}

        # --- SUPPRESSIONS : absent d'un onglet non vide où il devrait figurer ---
        to_delete, kept = [], []
        for a in accts:
            u = (a.get("username") or "").strip().lower()
            vx = (a.get("va") or "").strip().lower()
            gone = (id_present is not None and u and u not in id_present) or \
                   (vx and vx in va_present and u and u not in va_present[vx])
            (to_delete if gone else kept).append(a)
        # GARDE-FOU anti-suppression massive : si un seul sync voudrait supprimer
        # BEAUCOUP de comptes d'une identité (>10 ET >40%), c'est louche (lecture
        # partielle du Sheet / bug) -> on N'APPLIQUE PAS (protège la data). Les
        # suppressions volontaires en masse passent par /jailbreakreset ou le site.
        n_before = len(accts)
        deleted = set()
        if to_delete and len(to_delete) > max(10, int(n_before * 0.4)):
            print(f"[sheets_sync] anti-mass-delete {identity}: -{len(to_delete)}/{n_before} IGNORÉ",
                  flush=True)
        else:
            entry["accounts"] = kept
            accts = kept
            removed += len(to_delete)
            deleted = {(a.get("username") or "").strip().lower()
                       for a in to_delete if (a.get("username") or "").strip()}
        by_uname = {}
        for a in accts:
            u = (a.get("username") or "").strip().lower()
            if u and u not in by_uname:
                by_uname[u] = a

        # --- MAJ + AJOUTS depuis l'onglet IDENTITÉ (va = colonne 'va') ---
        if id_rows:
            seen = set()
            for r in id_rows:
                u = (r.get("username") or "").strip()
                if not u or u.lower() in seen:
                    continue
                seen.add(u.lower())
                acct = by_uname.get(u.lower())
                if acct is not None:
                    ch = False
                    for f in _FIELDS:
                        v = (r.get(f) or "").strip()
                        if (acct.get(f) or "") != v:
                            acct[f] = v
                            ch = True
                    if acct.get("username") != u:
                        acct["username"] = u[:80]
                        ch = True
                    if ch:
                        updated += 1
                elif u.lower() not in deleted:
                    acct = _row_new_account(u, r, (r.get("va") or "").strip(), _gen_id)
                    accts.append(acct)
                    by_uname[u.lower()] = acct
                    added += 1

        # --- MAJ + AJOUTS depuis les onglets PAR VA (va = nom de l'onglet) ---
        for vl, (vdisp, rows) in va_meta.items():
            seen = set()
            for r in rows:
                u = (r.get("username") or "").strip()
                if not u or u.lower() in seen:
                    continue
                seen.add(u.lower())
                acct = by_uname.get(u.lower())
                if acct is not None:
                    ch = False
                    for f in ("password", "email", "two_fa", "notes"):
                        v = (r.get(f) or "").strip()
                        if (acct.get(f) or "") != v:
                            acct[f] = v
                            ch = True
                    if ch:
                        updated += 1
                elif u.lower() not in deleted:
                    acct = _row_new_account(u, r, vdisp, _gen_id)
                    accts.append(acct)
                    by_uname[u.lower()] = acct
                    added += 1

        # Cohérence : les 'va' des comptes existent dans entry["vas"]
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
        jb._save(data)  # -> push_all_async régénère tous les onglets (converge)
    return changed, f"+{added} ajout(s) · {updated} modif(s) · -{removed} suppr."
