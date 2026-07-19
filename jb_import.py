"""Import/restauration des comptes Jailbreak depuis un export Google Drive.

Accepte le .zip du dossier « VA JB » (1 .xlsx par identité) OU un .xlsx seul.
Structure attendue dans chaque classeur :
  - onglet nommé comme l'identité  -> colonnes username|password|email|two_fa|va|notes|statut
  - onglets « identité VA »        -> mêmes colonnes SANS 'va' (le VA vient du nom d'onglet)

100 % ADDITIF : ne supprime jamais rien, n'écrase pas un compte existant, ne
duplique pas. Reconstruit la liste des VA de chaque identité.
"""
import io
import zipfile
from pathlib import Path

_FIELDS = ("password", "email", "two_fa", "notes")


def _cells(row) -> list:
    return [("" if c is None else str(c)).strip() for c in (row or ())]


def _parse_ws(ws, identity: str) -> list:
    """Retourne [{username, password, email, two_fa, va, notes}] d'un onglet."""
    title = (ws.title or "").strip()
    ident_l = (identity or "").strip().lower()
    tl = title.lower()
    # VA déduit du nom d'onglet (« amelia Bo07 » -> « Bo07 »)
    va_tab = ""
    if tl != ident_l and tl.startswith(ident_l + " "):
        va_tab = title[len(identity):].strip()

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    first = [c.lower() for c in _cells(rows[0])]
    has_header = "username" in first
    header = first if has_header else []
    body = rows[1:] if has_header else rows

    out = []
    for r in body:
        vals = _cells(r)
        if not vals:
            continue
        u = vals[0]
        if not u or u.lower() == "username":
            continue
        d = {"username": u, "va": va_tab}
        if header:
            for i, h in enumerate(header):
                if i >= len(vals):
                    break
                v = vals[i]
                if not v:
                    continue
                if h in _FIELDS:
                    d[h] = v
                elif h == "va" and not va_tab:
                    d["va"] = v
        # sans en-tête : on ne garde QUE le username (le reste serait du bruit)
        out.append(d)
    return out


def parse_upload(filename: str, blob: bytes) -> dict:
    """-> {identity: [comptes]}. Accepte .zip (dossier exporté) ou .xlsx seul."""
    import openpyxl
    books = []  # (identity, bytes)
    name = (filename or "").lower()
    if name.endswith(".zip") or blob[:2] == b"PK" and name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                if n.lower().endswith(".xlsx") and not n.split("/")[-1].startswith("~"):
                    books.append((Path(n).stem, z.read(n)))
    elif name.endswith(".xlsx"):
        books.append((Path(filename).stem, blob))
    else:
        raise ValueError("Format non supporté (attendu : .zip du dossier ou .xlsx).")

    out = {}
    for identity, data in books:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception:
            continue
        accts = []
        # l'onglet principal (nom == identité) d'abord : il porte la colonne 'va'
        sheets = sorted(wb.worksheets,
                        key=lambda w: 0 if (w.title or "").strip().lower() == identity.lower() else 1)
        for ws in sheets:
            try:
                accts += _parse_ws(ws, identity)
            except Exception:
                continue
        if accts:
            out[identity] = accts
    return out


def restore(parsed: dict) -> dict:
    """Fusion ADDITIVE dans jailbreak.json. Retourne un rapport détaillé."""
    import time
    import jailbreak as jb
    data = jb._load() or {}
    known = {str(k).strip().lower(): k for k in data.keys()}

    used = set()
    for entry in data.values():
        for a in (entry.get("accounts") or []):
            try:
                used.add(int(a.get("id", 0)))
            except Exception:
                pass
    nxt = [int(time.time() * 1000)]

    def _gen():
        while nxt[0] in used:
            nxt[0] += 1
        v = nxt[0]
        used.add(v)
        nxt[0] += 1
        return v

    report, total_add, total_fill = {}, 0, 0
    for identity, accts in (parsed or {}).items():
        real = known.get(identity.strip().lower(), identity)
        entry = data.setdefault(real, {"vas": [], "accounts": []})
        entry.setdefault("accounts", [])
        entry.setdefault("vas", [])
        by_u = {(a.get("username") or "").strip().lower(): a
                for a in entry["accounts"] if (a.get("username") or "").strip()}
        added = filled = 0
        for r in accts:
            u = (r.get("username") or "").strip()
            if not u:
                continue
            cur = by_u.get(u.lower())
            if cur is None:
                acct = {"id": _gen(), "username": u[:80],
                        "password": (r.get("password") or "")[:200],
                        "email": (r.get("email") or "")[:120],
                        "two_fa": (r.get("two_fa") or "")[:500],
                        "two_fa_validated": False,
                        "va": (r.get("va") or "")[:60],
                        "notes": (r.get("notes") or "")[:500]}
                entry["accounts"].append(acct)
                by_u[u.lower()] = acct
                added += 1
            else:
                # complète les champs VIDES uniquement (jamais d'écrasement)
                ch = False
                for f in ("password", "email", "two_fa", "notes", "va"):
                    v = (r.get(f) or "").strip()
                    if v and not (cur.get(f) or "").strip():
                        cur[f] = v
                        ch = True
                if ch:
                    filled += 1
        # reconstruit les VA de l'identité
        have = {str((v.get("name") if isinstance(v, dict) else v) or "").strip().lower()
                for v in entry["vas"]}
        for v in sorted({(a.get("va") or "").strip() for a in entry["accounts"] if (a.get("va") or "").strip()}):
            if v.lower() not in have:
                entry["vas"].append(v)
                have.add(v.lower())
        report[real] = {"added": added, "filled": filled, "total": len(entry["accounts"])}
        total_add += added
        total_fill += filled
    jb._save(data)
    return {"identities": report, "added": total_add, "filled": total_fill}
