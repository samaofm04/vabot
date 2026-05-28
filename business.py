"""Gestion business : SFS planning + Dépenses + Bilan.

Stocke tout dans data/business/ comme JSON.
"""
import json
import time
import os
from pathlib import Path
from typing import List, Dict

DATA_DIR = Path("data")
BUSINESS_DIR = DATA_DIR / "business"
SFS_FILE = BUSINESS_DIR / "sfs.json"
EXPENSES_FILE = BUSINESS_DIR / "expenses.json"


def _ensure():
    BUSINESS_DIR.mkdir(parents=True, exist_ok=True)


def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(path: Path, data: list):
    _ensure()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============ SFS ============

def list_sfs() -> List[Dict]:
    return _load(SFS_FILE)


def add_sfs(identity: str, partner: str, date_iso: str, time_str: str, notes: str = ""):
    """Ajoute une entrée SFS planifiée."""
    items = _load(SFS_FILE)
    new_id = int(time.time() * 1000)
    items.append({
        "id": new_id,
        "identity": identity.lower().strip(),
        "partner": partner.strip().replace("@", ""),
        "date": date_iso,  # YYYY-MM-DD
        "time": time_str,  # HH:MM
        "notes": notes.strip()[:200],
        "done": False,
        "created_at": int(time.time()),
    })
    items.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    _save(SFS_FILE, items)
    return new_id


def remove_sfs(item_id: int) -> bool:
    items = _load(SFS_FILE)
    n_before = len(items)
    items = [x for x in items if x.get("id") != item_id]
    if len(items) == n_before:
        return False
    _save(SFS_FILE, items)
    return True


def toggle_sfs_done(item_id: int) -> bool:
    items = _load(SFS_FILE)
    for x in items:
        if x.get("id") == item_id:
            x["done"] = not x.get("done", False)
            _save(SFS_FILE, items)
            return True
    return False


def sfs_stats() -> Dict:
    items = list_sfs()
    today = time.strftime("%Y-%m-%d")
    return {
        "total": len(items),
        "today": len([x for x in items if x.get("date") == today]),
        "done": len([x for x in items if x.get("done")]),
        "pending": len([x for x in items if not x.get("done")]),
    }


# ============ DÉPENSES ============

CATEGORIES = [
    "VPS / Hosting",
    "RapidAPI / Scraping",
    "Proxies",
    "Outils / Software",
    "Marketing / Ads",
    "Comptes Instagram",
    "Autre",
]


def list_expenses() -> List[Dict]:
    return _load(EXPENSES_FILE)


def add_expense(category: str, description: str, amount: float,
                date_iso: str, recurring: bool = False):
    items = _load(EXPENSES_FILE)
    new_id = int(time.time() * 1000)
    items.append({
        "id": new_id,
        "category": category,
        "description": description.strip()[:200],
        "amount": float(amount),
        "date": date_iso,
        "recurring": bool(recurring),
        "created_at": int(time.time()),
    })
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    _save(EXPENSES_FILE, items)
    return new_id


def remove_expense(item_id: int) -> bool:
    items = _load(EXPENSES_FILE)
    n_before = len(items)
    items = [x for x in items if x.get("id") != item_id]
    if len(items) == n_before:
        return False
    _save(EXPENSES_FILE, items)
    return True


def expense_stats() -> Dict:
    items = list_expenses()
    if not items:
        return {
            "total_all_time": 0,
            "total_this_month": 0,
            "monthly_recurring": 0,
            "by_category": {},
        }
    current_month = time.strftime("%Y-%m")
    total_all = sum(x.get("amount", 0) for x in items)
    total_month = sum(
        x.get("amount", 0) for x in items
        if x.get("date", "").startswith(current_month)
    )
    monthly_rec = sum(x.get("amount", 0) for x in items if x.get("recurring"))
    by_cat = {}
    for x in items:
        c = x.get("category", "Autre")
        by_cat[c] = by_cat.get(c, 0) + x.get("amount", 0)
    return {
        "total_all_time": round(total_all, 2),
        "total_this_month": round(total_month, 2),
        "monthly_recurring": round(monthly_rec, 2),
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
    }
