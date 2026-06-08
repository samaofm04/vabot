"""chatting.py - Planning des chatteurs (multi-EDT, multi-semaines).

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
                    "creneau": "02h-08h",
                    "pseudo": "Mariamos",
                    "statut": "Ancien",
                    "modele": "Les 3...",
                    "off": "FULLTIME",
                    "presence_by_week": {
                        "2026-05-26": {"lun":"Present","mar":"Present",...},
                        "2026-06-02": {...}
                    }
                }
            ]
        }
    ]
}

week_start = lundi de la semaine, format YYYY-MM-DD
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

DATA_DIR = Path("data")
PLANNING_FILE = DATA_DIR / "chatting_planning.json"

CRENEAUX = ["02h-08h", "08h-14h", "14h-20h", "20h-02h"]
DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
DAYS_FULL = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DAYS_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
STATUTS = ["Ancien", "Nouveau", "Support"]
OFF_OPTIONS = ["FULLTIME", "Lundi", "Mardi", "Mercredi", "Jeudi",
               "Vendredi", "Samedi", "Dimanche", "PAS DE REPONSE"]
PRESENCE_VALUES = ["Present", "Absent", "Retard", "Coupure", "OFF"]

DEFAULT_MODELES = ["", "Julia", "Amelia", "Lola", "Sarah", "Emma", "Kiara"]

# Listes des modeles par plateforme (utilisees pour le multi-select)
MODELES_OF = ["Julia", "Amelia", "Lola"]
MODELES_MYM = ["Lola", "Julia", "Amelia", "Kiara", "Sarah", "Emma"]


def models_for_edt(edt_name: str) -> List[str]:
    """Retourne la liste des modeles disponibles pour un EDT (selon son nom)."""
    n = (edt_name or "").lower()
    if "mym" in n:
        return MODELES_MYM
    if "of" in n or "onlyfans" in n:
        return MODELES_OF
    # Defaut : union des deux
    return sorted(set(MODELES_OF + MODELES_MYM))


# ==================== Week helpers ====================

def week_start_for(d: date) -> date:
    """Retourne le lundi de la semaine de la date donnee."""
    return d - timedelta(days=d.weekday())


def current_week_start() -> str:
    """Lundi de cette semaine en YYYY-MM-DD."""
    return week_start_for(date.today()).isoformat()


def parse_week_start(s: str) -> str:
    """Parse une date YYYY-MM-DD et retourne le lundi de cette semaine."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        return week_start_for(d).isoformat()
    except Exception:
        return current_week_start()


def shift_week(week_start_iso: str, delta_weeks: int) -> str:
    """Decale d un certain nombre de semaines."""
    try:
        d = datetime.strptime(week_start_iso, "%Y-%m-%d").date()
        new_d = d + timedelta(weeks=delta_weeks)
        return new_d.isoformat()
    except Exception:
        return current_week_start()


def week_dates(week_start_iso: str) -> List[date]:
    """Retourne les 7 dates de la semaine (lundi -> dimanche)."""
    try:
        d = datetime.strptime(week_start_iso, "%Y-%m-%d").date()
    except Exception:
        d = date.today()
    return [d + timedelta(days=i) for i in range(7)]


def week_label(week_start_iso: str) -> str:
    """Retourne un label lisible : 'Sem du 26 mai au 1 juin'."""
    mois = ["", "janv.", "fev.", "mars", "avril", "mai", "juin",
            "juill.", "aout", "sept.", "oct.", "nov.", "dec."]
    try:
        d = datetime.strptime(week_start_iso, "%Y-%m-%d").date()
    except Exception:
        d = date.today()
    end = d + timedelta(days=6)
    if d.month == end.month:
        return f"{d.day}-{end.day} {mois[d.month]} {end.year}"
    return f"{d.day} {mois[d.month]} - {end.day} {mois[end.month]} {end.year}"


def iso_week_number(week_start_iso: str) -> int:
    try:
        d = datetime.strptime(week_start_iso, "%Y-%m-%d").date()
        return d.isocalendar()[1]
    except Exception:
        return 0


# ==================== Storage ====================

def _load() -> Dict[str, Any]:
    if not PLANNING_FILE.exists():
        return {"edts": []}
    try:
        data = json.loads(PLANNING_FILE.read_text(encoding="utf-8"))
        if "edts" not in data:
            data["edts"] = []
        # Migration : si une row a 'presence' (ancien format), migre vers
        # presence_by_week[current_week]
        cw = current_week_start()
        changed = False
        for e in data["edts"]:
            for r in e.get("rows", []):
                if "presence" in r and "presence_by_week" not in r:
                    r["presence_by_week"] = {cw: r.pop("presence")}
                    changed = True
                if "presence_by_week" not in r:
                    r["presence_by_week"] = {}
                    changed = True
        if changed:
            _save(data)
        return data
    except Exception:
        return {"edts": []}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLANNING_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ==================== EDT CRUD ====================

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
    edt = {"id": f"edt_{uuid.uuid4().hex[:10]}", "name": name, "rows": []}
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


# ==================== Row CRUD ====================

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
                "presence_by_week": {},
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


def update_cell(edt_id: str, row_id: str, field: str, value: str,
                week_start: str = "") -> bool:
    """Update une cellule.
    field = pseudo / statut / modele / off / creneau (permanent)
          | lun/mar/.../dim (pour la semaine donnee)
    """
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
                ws = parse_week_start(week_start or current_week_start())
                if "presence_by_week" not in r:
                    r["presence_by_week"] = {}
                if ws not in r["presence_by_week"]:
                    r["presence_by_week"][ws] = _empty_presence()
                if value not in PRESENCE_VALUES:
                    value = "Present"
                r["presence_by_week"][ws][field] = value
            else:
                return False
            _save(data)
            return True
    return False


# ==================== Presence helpers ====================

def row_presence(row: Dict[str, Any], week_start: str) -> Dict[str, str]:
    """Retourne le dict de presence pour une row sur une semaine donnee.
    Defaut a 'Present' pour tous les jours si non renseigne.
    """
    pbw = row.get("presence_by_week", {})
    p = pbw.get(week_start)
    if not p:
        return _empty_presence()
    out = _empty_presence()
    out.update({k: v for k, v in p.items() if k in DAYS and v in PRESENCE_VALUES})
    return out


def row_counts(row: Dict[str, Any], week_start: str) -> Dict[str, int]:
    """Retourne {retards, absences} pour une row sur une semaine donnee."""
    pres = row_presence(row, week_start)
    retards = sum(1 for d in DAYS if pres.get(d) == "Retard")
    absences = sum(1 for d in DAYS if pres.get(d) == "Absent")
    return {"retards": retards, "absences": absences}


def row_incidents_in_range(row: Dict[str, Any], start: date, end: date) -> Dict[str, int]:
    """Compte {absences, retards, coupures} pour une row sur la plage de dates
    [start, end] INCLUS.

    Itere jour par jour (et non semaine par semaine) afin de gerer correctement
    les semaines a cheval sur la frontiere d une periode de paie (ex: le 15/16).
    Les jours non renseignes comptent comme 'Present' (0 incident)."""
    absn = retn = coupn = 0
    d = start
    while d <= end:
        ws = week_start_for(d).isoformat()
        dk = DAYS[d.weekday()]
        v = row_presence(row, ws).get(dk, "Present")
        if v == "Absent":
            absn += 1
        elif v == "Retard":
            retn += 1
        elif v == "Coupure":
            coupn += 1
        d += timedelta(days=1)
    return {"absences": absn, "retards": retn, "coupures": coupn}


def pay_periods_for_month(year: int, month: int) -> List:
    """Retourne les 2 periodes de paie d un mois sous forme de tuples de dates :
    [(1er, 15), (16, dernier jour du mois)]."""
    import calendar as _cal
    last = _cal.monthrange(year, month)[1]
    return [
        (date(year, month, 1), date(year, month, 15)),
        (date(year, month, 16), date(year, month, last)),
    ]


def edt_weeks_with_data(edt_id: str) -> List[str]:
    """Liste les week_start qui ont des donnees pour cet EDT."""
    edt = get_edt(edt_id)
    if not edt:
        return []
    weeks = set()
    for r in edt.get("rows", []):
        weeks.update((r.get("presence_by_week") or {}).keys())
    return sorted(weeks)


def import_week(edt_id: str, creneau: str, week_start: str,
                rows: List[Dict[str, Any]], replace_creneau: bool = False) -> Dict[str, int]:
    """Import en masse pour 1 creneau + 1 semaine. FUSION intelligente :
    - si une ligne existe deja dans ce creneau avec le MEME pseudo -> on met
      juste a jour sa presence pour week_start (les autres semaines de cette
      ligne ne sont PAS touchees) + statut/modele/off si fournis. Pas de doublon.
    - sinon -> on cree une nouvelle ligne.

    rows = [{pseudo, statut, modele, off, presence:{lun..dim}}, ...]
    replace_creneau=True : repart de zero pour ce creneau (supprime ses lignes
    avant import) -> ATTENTION supprime aussi leurs autres semaines.
    Retourne {created, updated}."""
    data = _load()
    edt = None
    for e in data["edts"]:
        if e["id"] == edt_id:
            edt = e
            break
    if not edt:
        return {"created": 0, "updated": 0}
    ws = parse_week_start(week_start or current_week_start())
    if creneau not in CRENEAUX:
        creneau = CRENEAUX[0]
    edt.setdefault("rows", [])
    if replace_creneau:
        edt["rows"] = [r for r in edt["rows"] if r.get("creneau") != creneau]

    def _norm_pseudo(s):
        return (s or "").strip().lower()

    # Lignes existantes du creneau (pour la fusion par pseudo)
    existing = [r for r in edt["rows"] if r.get("creneau") == creneau]
    used_ids = set()
    n_created = n_updated = 0
    for r in rows:
        pseudo = (r.get("pseudo") or "").strip()
        if not pseudo:
            continue  # on ne cree pas de ligne sans pseudo
        statut = (r.get("statut") or "Nouveau").strip().capitalize()
        if statut not in STATUTS:
            statut = "Nouveau"
        modele = (r.get("modele") or "").strip()
        off = (r.get("off") or "").strip()
        pres_in = r.get("presence") or {}
        pres = _empty_presence()
        for d in DAYS:
            v = pres_in.get(d)
            if v in PRESENCE_VALUES:
                pres[d] = v
        # Cherche une ligne existante (meme creneau, meme pseudo, pas deja prise)
        match = None
        for er in existing:
            if id(er) in used_ids:
                continue
            if _norm_pseudo(er.get("pseudo")) == _norm_pseudo(pseudo):
                match = er
                break
        if match is not None:
            match.setdefault("presence_by_week", {})[ws] = pres
            if statut:
                match["statut"] = statut
            if modele:
                match["modele"] = modele
            if off:
                match["off"] = off
            used_ids.add(id(match))
            n_updated += 1
        else:
            new_row = {
                "id": "row_" + uuid.uuid4().hex[:10],
                "creneau": creneau,
                "pseudo": pseudo,
                "statut": statut,
                "modele": modele,
                "off": off,
                "presence_by_week": {ws: pres},
            }
            edt["rows"].append(new_row)
            existing.append(new_row)
            used_ids.add(id(new_row))
            n_created += 1
    _save(data)
    return {"created": n_created, "updated": n_updated}


def fill_row_week(edt_id: str, row_id: str, week_start: str, value: str) -> bool:
    """Met TOUS les jours (lun..dim) d'une ligne a la meme valeur de presence
    pour la semaine donnee. Pour le bouton 'remplir la ligne'."""
    if value not in PRESENCE_VALUES:
        return False
    data = _load()
    ws = parse_week_start(week_start or current_week_start())
    for e in data["edts"]:
        if e["id"] != edt_id:
            continue
        for r in e.get("rows", []):
            if r["id"] != row_id:
                continue
            r.setdefault("presence_by_week", {})[ws] = {d: value for d in DAYS}
            _save(data)
            return True
    return False
