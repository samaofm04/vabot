"""chatting.py - Planning des chatteurs (style Excel, multi-EDT).

Stockage : data/chatting_planning.json
Structure :
{
    "edts": [
        {
            "id": "edt_xxx",
            "name": "EDT 1 OF",
            "rows": [
                {
                    "id": "row_xxx",
                    "creneau": "02h-08h",     # 02h-08h | 08h-14h | 14h-20h | 20h-02h
                    "pseudo": "Mariamos",
                    "statut": "Ancien",       # Ancien | Nouveau | Support
                    "modele": "Les 3 (Julia+Amelia+Lola)",
                    "off": "FULLTIME",        # Lundi..Dimanche | FULLTIME | PAS DE REPONSE
                    "presence": {
                        "lun": "Present", "mar": "Present", "mer": "Present",
                        "jeu": "Present", "ven": "Present", "sam": "Present",
                        "dim": "Present"
                    }
                }
            ]
        }
    ]
}

Valeurs de presence : "Present" | "Absent" | "Retard" | "Coupure" | "OFF"
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

DATA_DIR = Path("data")
PLANNING_FILE = DATA_DIR / "chatting_planning.json"

CRENEAUX = ["02h-08h", "08h-14h", "14h-20h", "20h-02h"]
DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
DAYS_FULL = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
STATUTS = ["Ancien", "Nouveau", "Support"]
OFF_OPTIONS = ["FULLTIME", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche", "PAS DE REPONSE"]
PRESENCE_VALUES = ["Present", "Absent", "Retard", "Coupure", "OFF"]

# Defauts modeles (liste evolutive cote UI)
DEFAULT_MODELES = ["", "Julia", "Amelia", "Lola", "Sarah", "Emma",
                   "Amelia+Lola", "Lola+Emma", "Julia+Sarah",
                   "Les 3 (Julia+Amelia+Lola)", "Toutes (Julia+Amelia+Lola+Sarah+Emma)"]


def _load() -> Dict[str, Any]:
    if not PLANNING_FILE.exists():
        return {"edts": []}
    try:
        data = json.loads(PLANNING_FILE.read_text(encoding="utf-8"))
        if "edts" not in data:
            data["edts"] = []
        return data
    except Exception:
        return {"edts": []}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLANNING_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_edts() -> List[Dict[str, Any]]:
    return _load().get("edts", [])


def get_edt(edt_id: str) -> Optional[Dict[str, Any]]:
    for e in list_edts():
        if e.get("id") == edt_id:
            return e
    return None


def create_edt(name: str) -> Dict[str, Any]:
    name = (name or "").strip() or "EDT sans nom"
    data = _load()
    edt = {
        "id": f"edt_{uuid.uuid4().hex[:10]}",
        "name": name,
        "rows": [],
    }
    data["edts"].append(edt)
    _save(data)
    return edt


def rename_edt(edt_id: str, new_name: str) -> bool:
    data = _load()
    for e in data["edts"]:
        if e["id"] == edt_id:
            e["name"] = (new_name or "").strip() or e["name"]
            _save(data)
            return True
    return False


def delete_edt(edt_id: str) -> bool:
    data = _load()
    before = len(data["edts"])
    data["edts"] = [e for e in data["edts"] if e["id"] != edt_id]
    if len(data["edts"]) != before:
        _save(data)
        return True
    return False


def _empty_presence() -> Dict[str, str]:
    return {d: "Present" for d in DAYS}


def add_row(edt_id: str, creneau: str = "02h-08h") -> Optional[Dict[str, Any]]:
    if creneau not in CRENEAUX:
        creneau = "02h-08h"
    data = _load()
    for e in data["edts"]:
        if e["id"] == edt_id:
            row = {
                "id": f"row_{uuid.uuid4().hex[:10]}",
                "creneau": creneau,
                "pseudo": "",
                "statut": "Nouveau",
                "modele": "",
                "off": "",
                "presence": _empty_presence(),
            }
            e["rows"].append(row)
            _save(data)
            return row
    return None


def delete_row(edt_id: str, row_id: str) -> bool:
    data = _load()
    for e in data["edts"]:
        if e["id"] == edt_id:
            before = len(e["rows"])
            e["rows"] = [r for r in e["rows"] if r["id"] != row_id]
            if len(e["rows"]) != before:
                _save(data)
                return True
    return False


def update_cell(edt_id: str, row_id: str, field: str, value: str) -> bool:
    """Update une cellule. field = pseudo/statut/modele/off/lun/mar/mer/jeu/ven/sam/dim."""
    data = _load()
    for e in data["edts"]:
        if e["id"] != edt_id:
            continue
        for r in e["rows"]:
            if r["id"] != row_id:
                continue
            if field in ("pseudo", "statut", "modele", "off", "creneau"):
                r[field] = value
            elif field in DAYS:
                if "presence" not in r:
                    r["presence"] = _empty_presence()
                # Valider la valeur
                if value not in PRESENCE_VALUES:
                    value = "Present"
                r["presence"][field] = value
            else:
                return False
            _save(data)
            return True
    return False


def row_counts(row: Dict[str, Any]) -> Dict[str, int]:
    """Retourne {retards, absences} pour une row."""
    pres = row.get("presence", {})
    retards = sum(1 for d in DAYS if pres.get(d) == "Retard")
    absences = sum(1 for d in DAYS if pres.get(d) == "Absent")
    return {"retards": retards, "absences": absences}


def import_from_xlsx_data(name: str, rows_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cree un EDT a partir de donnees structurees (utilise pour seed depuis xlsx)."""
    edt = create_edt(name)
    data = _load()
    for e in data["edts"]:
        if e["id"] == edt["id"]:
            for r in rows_data:
                row = {
                    "id": f"row_{uuid.uuid4().hex[:10]}",
                    "creneau": r.get("creneau", "02h-08h"),
                    "pseudo": r.get("pseudo", ""),
                    "statut": r.get("statut", "Nouveau"),
                    "modele": r.get("modele", ""),
                    "off": r.get("off", ""),
                    "presence": r.get("presence") or _empty_presence(),
                }
                e["rows"].append(row)
            _save(data)
            return e
    return edt
