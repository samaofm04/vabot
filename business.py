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
REVENUES_FILE = BUSINESS_DIR / "revenues.json"
VA_PAYMENTS_FILE = BUSINESS_DIR / "va_payments.json"
IDENTITY_PLATFORMS_FILE = BUSINESS_DIR / "identity_platforms.json"

# Plateformes par défaut
DEFAULT_IDENTITY_PLATFORMS = {
    "julia": ["OF", "MYM"],
    "lola": ["OF", "MYM"],
    "amelia": ["OF", "MYM"],
    "sarah": ["MYM"],
    "emma": ["MYM"],
}

PLATFORMS = ["OF", "MYM"]


def load_identity_platforms() -> dict:
    """Retourne un mapping {identity: [platforms]}"""
    if not IDENTITY_PLATFORMS_FILE.exists():
        return dict(DEFAULT_IDENTITY_PLATFORMS)
    try:
        return json.loads(IDENTITY_PLATFORMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_IDENTITY_PLATFORMS)


def save_identity_platforms(data: dict):
    _ensure()
    IDENTITY_PLATFORMS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def set_identity_platform(identity: str, platform: str, active: bool):
    """Active ou désactive une plateforme pour une identité."""
    data = load_identity_platforms()
    identity = identity.lower().strip()
    if identity not in data:
        data[identity] = []
    if active and platform not in data[identity]:
        data[identity].append(platform)
    elif not active and platform in data[identity]:
        data[identity].remove(platform)
    save_identity_platforms(data)


def identities_for_platform(platform: str) -> list:
    """Liste les identités présentes sur une plateforme."""
    data = load_identity_platforms()
    return sorted([ident for ident, plats in data.items() if platform in plats])


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


def add_sfs(identity: str, partner: str, date_iso: str, time_str: str,
            platform: str = "OF", status: str = "scheduled", notes: str = "",
            receiver_identity: str = ""):
    """Ajoute une entrée SFS planifiée.

    identity         : modèle qui ENVOIE (celle qui poste sur OF/MyM)
    partner          : @ du partenaire externe (compte tiers)
    receiver_identity: modèle qui RECEVRA le SFS (la promo). Si vide,
                       par defaut = identity (auto-SFS = la modele s envoie a elle-meme)
    """
    items = _load(SFS_FILE)
    new_id = int(time.time() * 1000)
    items.append({
        "id": new_id,
        "identity": identity.lower().strip(),
        "receiver_identity": (receiver_identity or identity).lower().strip(),
        "partner": partner.strip().replace("@", ""),
        "date": date_iso,
        "time": time_str,
        "platform": platform.upper(),
        "status": status,  # scheduled | to_program
        "notes": notes.strip()[:200],
        "done": False,
        "created_at": int(time.time()),
    })
    items.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    _save(SFS_FILE, items)
    return new_id


def sfs_weekly_received(target_per_week: int = 3) -> Dict:
    """Calcule pour chaque modele combien de SFS elle a RECU cette semaine
    (lundi -> dimanche actuel) et retourne celles en danger (< target).

    Retourne :
    {
      'week_start': '2026-06-01', 'week_end': '2026-06-07', 'target': 3,
      'by_receiver': {'amelia': 2, 'emma': 4, 'lola': 0},
      'in_danger': [{'identity': 'amelia', 'received': 2, 'missing': 1},
                    {'identity': 'lola', 'received': 0, 'missing': 3}]
    }
    """
    import datetime as _dt
    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())  # lundi
    sunday = monday + _dt.timedelta(days=6)
    week_start_iso = monday.isoformat()
    week_end_iso = sunday.isoformat()
    items = list_sfs()
    by_receiver = {}
    for it in items:
        d = it.get("date", "")
        if not (week_start_iso <= d <= week_end_iso):
            continue
        rcv = (it.get("receiver_identity") or it.get("identity") or "").lower().strip()
        if not rcv:
            continue
        by_receiver[rcv] = by_receiver.get(rcv, 0) + 1
    # Liste des identites connues pour completer celles a 0
    try:
        identities = list((load_identity_platforms() or {}).keys())
    except Exception:
        identities = list(by_receiver.keys())
    in_danger = []
    for ident in identities:
        n = by_receiver.get(ident, 0)
        if n < target_per_week:
            in_danger.append({
                "identity": ident,
                "received": n,
                "missing": target_per_week - n,
            })
    in_danger.sort(key=lambda x: x["missing"], reverse=True)
    return {
        "week_start": week_start_iso,
        "week_end": week_end_iso,
        "target": target_per_week,
        "by_receiver": by_receiver,
        "in_danger": in_danger,
    }


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


# ============ REVENUS (Chatteurs OnlyFans) ============

def list_revenues() -> List[Dict]:
    return _load(REVENUES_FILE)


def add_revenue(identity: str, chatter: str, amount: float, date_iso: str,
                source: str = "OnlyFans", notes: str = ""):
    items = _load(REVENUES_FILE)
    new_id = int(time.time() * 1000)
    items.append({
        "id": new_id,
        "identity": identity.lower().strip(),
        "chatter": chatter.strip(),
        "amount": float(amount),
        "date": date_iso,
        "source": source,
        "notes": notes.strip()[:200],
        "created_at": int(time.time()),
    })
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    _save(REVENUES_FILE, items)
    return new_id


def remove_revenue(item_id: int) -> bool:
    items = _load(REVENUES_FILE)
    n_before = len(items)
    items = [x for x in items if x.get("id") != item_id]
    if len(items) == n_before:
        return False
    _save(REVENUES_FILE, items)
    return True


def revenue_stats() -> Dict:
    items = list_revenues()
    if not items:
        return {
            "total_all_time": 0,
            "total_this_month": 0,
            "by_identity": {},
            "by_chatter": {},
        }
    current_month = time.strftime("%Y-%m")
    total = sum(x.get("amount", 0) for x in items)
    total_month = sum(
        x.get("amount", 0) for x in items
        if x.get("date", "").startswith(current_month)
    )
    by_ident = {}
    by_chat = {}
    for x in items:
        ident = x.get("identity", "?")
        chat = x.get("chatter", "?")
        by_ident[ident] = by_ident.get(ident, 0) + x.get("amount", 0)
        by_chat[chat] = by_chat.get(chat, 0) + x.get("amount", 0)
    return {
        "total_all_time": round(total, 2),
        "total_this_month": round(total_month, 2),
        "by_identity": {k: round(v, 2) for k, v in by_ident.items()},
        "by_chatter": {k: round(v, 2) for k, v in by_chat.items()},
    }


# ============ PAIE VAS ============

def list_va_payments() -> List[Dict]:
    return _load(VA_PAYMENTS_FILE)


def add_va_payment(va_username: str, amount: float, date_iso: str,
                   description: str = "", paid: bool = False, payment_method: str = ""):
    items = _load(VA_PAYMENTS_FILE)
    new_id = int(time.time() * 1000)
    items.append({
        "id": new_id,
        "va_username": va_username.strip(),
        "amount": float(amount),
        "date": date_iso,
        "description": description.strip()[:200],
        "paid": bool(paid),
        "payment_method": payment_method.strip(),
        "created_at": int(time.time()),
    })
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    _save(VA_PAYMENTS_FILE, items)
    return new_id


def remove_va_payment(item_id: int) -> bool:
    items = _load(VA_PAYMENTS_FILE)
    n_before = len(items)
    items = [x for x in items if x.get("id") != item_id]
    if len(items) == n_before:
        return False
    _save(VA_PAYMENTS_FILE, items)
    return True


def toggle_va_payment_paid(item_id: int) -> bool:
    items = _load(VA_PAYMENTS_FILE)
    for x in items:
        if x.get("id") == item_id:
            x["paid"] = not x.get("paid", False)
            _save(VA_PAYMENTS_FILE, items)
            return True
    return False


def va_payment_stats() -> Dict:
    items = list_va_payments()
    if not items:
        return {
            "total_due": 0,
            "total_paid": 0,
            "total_unpaid": 0,
            "by_va": {},
        }
    total_paid = sum(x.get("amount", 0) for x in items if x.get("paid"))
    total_unpaid = sum(x.get("amount", 0) for x in items if not x.get("paid"))
    by_va = {}
    for x in items:
        va = x.get("va_username", "?")
        if va not in by_va:
            by_va[va] = {"paid": 0, "unpaid": 0}
        if x.get("paid"):
            by_va[va]["paid"] += x.get("amount", 0)
        else:
            by_va[va]["unpaid"] += x.get("amount", 0)
    return {
        "total_due": round(total_paid + total_unpaid, 2),
        "total_paid": round(total_paid, 2),
        "total_unpaid": round(total_unpaid, 2),
        "by_va": {k: {"paid": round(v["paid"], 2), "unpaid": round(v["unpaid"], 2)} for k, v in by_va.items()},
    }


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
