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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import safe_json

DATA_DIR = Path("data")
PLANNING_FILE = DATA_DIR / "chatting_planning.json"

CRENEAUX = ["02h-08h", "08h-14h", "14h-20h", "20h-02h"]

#: LE FUSEAU DES CRENEAUX. Jusqu ici « 08h-14h » ne voulait rien dire : les
#: quatre creneaux etaient des chaines jamais converties en heures, et
#: personne n avait eu a decider de quelle horloge il s agissait. Le
#: proprietaire pose ses shifts a SON horloge (choix du 22/09/2026), donc
#: Paris -- et Paris change d heure deux fois par an, ce qui se paie
#: exactement sur ces creneaux :
#:   - 29/03/2026 : 02h00 N EXISTE PAS, l horloge saute a 03h00, et le
#:     creneau 02h-08h ne dure que 5 heures reelles.
#:   - 25/10/2026 : 02h00 arrive DEUX fois, et il en dure 7.
#: Les deux cas sont traites, pas esperes. Et toute duree se calcule sur
#: .timestamp() : soustraire deux datetime portant le meme tzinfo rend la
#: difference d horloge murale et ignore le fuseau.
FUSEAU_CRENEAUX = "Europe/Paris"

#: Les creneaux, avec enfin des heures. UNE SEULE table : un second parsing
#: ailleurs, c est deux comportements le jour ou l un des deux change.
#: fin <= debut veut dire que le shift franchit minuit.
CRENEAUX_HORAIRES = {
    "02h-08h": (2, 8),
    "08h-14h": (8, 14),
    "14h-20h": (14, 20),
    "20h-02h": (20, 2),
}
DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
DAYS_FULL = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DAYS_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
STATUTS = ["Ancien", "Nouveau", "Support"]
OFF_OPTIONS = ["FULLTIME", "Lundi", "Mardi", "Mercredi", "Jeudi",
               "Vendredi", "Samedi", "Dimanche", "PAS DE REPONSE"]
PRESENCE_VALUES = ["Present", "Absent", "Retard", "Coupure", "OFF"]

#: LE JOUR DE REPOS, TRADUIT UNE SEULE FOIS. La colonne « off » porte des
#: noms COMPLETS (« Dimanche ») tandis que les cases de jour portent trois
#: lettres (« dim ») : aucune correspondance n existait, et quiconque en
#: aurait eu besoin en aurait invente une deuxieme — le piege « deux
#: mappings valent deux comportements » que ce depot a deja paye cher.
#:
#: Sans elle, un pointage automatique marquerait « Absent » le jour de repos
#: declare de quelqu un. Les donnees reelles montrent que la contradiction
#: existe deja a la main : quatre lignes declarent un repos et disent
#: « Present » ce jour-la.
JOUR_DE_REPOS = {nom: cle for nom, cle in zip(DAYS_FULL, DAYS)}


def jour_de_repos(row: Dict[str, Any]) -> str:
    """La cle de jour ou cette personne ne travaille pas, ou "".

    "" veut dire « aucun repos connu » — FULLTIME, PAS DE REPONSE, ou une
    valeur qu on ne comprend pas. C est un etat distinct de « repos le
    lundi » et il ne doit pas se confondre avec lui : sur une valeur
    inconnue on s abstient, on ne devine pas.
    """
    return JOUR_DE_REPOS.get((row.get("off") or "").strip(), "")


def creneau_lisible(creneau: str) -> str:
    """« 02h-08h » -> « 02h - 08h », pour l en-tete de colonne.

    Le rendu faisait .replace('h-', 'h - ').replace('-', ' - ') puis ajoutait
    un « h » : la deuxieme substitution retouchait le tiret deja espace et le
    « h » final doublait celui de la chaine. L ecran affichait « 02h  -  08hh ».
    Le calcul vivait a DEUX endroits identiques dans web_upload ; il n y en a
    plus qu un, ici, avec le reste du vocabulaire des creneaux.
    """
    return str(creneau or "").replace("-", " - ")


def _day_parts(v):
    """Une case de jour peut contenir 1 OU 2 valeurs separees par '+' (case
    divisee, ex: 'Present+Coupure'). Retourne la liste des valeurs valides."""
    return [p for p in str(v or "").split("+") if p in PRESENCE_VALUES]


def _valid_day_value(v):
    """True si v est une valeur de jour valide : 1 valeur, ou 2 separees par '+'
    (toutes dans PRESENCE_VALUES)."""
    parts = str(v or "").split("+")
    return 1 <= len(parts) <= 2 and all(p in PRESENCE_VALUES for p in parts)


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

def creneau_franchit_minuit(creneau: str) -> bool:
    """Ce creneau passe-t-il de l autre cote de minuit ?"""
    h = CRENEAUX_HORAIRES.get((creneau or "").strip())
    return bool(h) and h[1] <= h[0]


def _zone():
    from zoneinfo import ZoneInfo
    return ZoneInfo(FUSEAU_CRENEAUX)


def _instant_mural(jour: date, heure: int):
    """Une heure MURALE de Paris -> un instant reel, et ce qu elle avait de tordu.

    Rend (datetime aware, anomalie) ou anomalie vaut "" (cas normal),
    "inexistante" (l horloge a saute par-dessus cette heure-la) ou
    "ambigue" (cette heure arrive deux fois cette nuit).

    Python ne previent d aucun des deux : datetime(2026,3,29,2,0, tz=Paris)
    ne leve rien et rend un instant qui se relit 03:00. On le DETECTE en
    relisant l heure murale apres un aller-retour par UTC, au lieu de
    l esperer. fold=0 donne le bon instant dans les deux cas -- l instant du
    saut pour une heure inexistante, la PREMIERE occurrence pour une heure
    ambigue -- et la premiere est bien celle ou le shift commence : prendre
    la seconde declarerait en retard quelqu un qui est a l heure.
    """
    z = _zone()
    dt = datetime(jour.year, jour.month, jour.day, heure, 0, tzinfo=z)
    relu = dt.astimezone(timezone.utc).astimezone(z)
    if relu.hour != heure:
        return dt, "inexistante"
    if dt.utcoffset() != dt.replace(fold=1).utcoffset():
        return dt, "ambigue"
    return dt, ""


def fenetre_shift(creneau: str, jour_debut) -> Optional[Dict[str, Any]]:
    """Les deux instants qui bornent un shift, et sa duree REELLE.

    `jour_debut` est le jour ou le shift COMMENCE (date ou 'AAAA-MM-JJ').
    Rend None si le creneau est inconnu : inconnu veut dire inconnu, pas
    « on suppose ». L intervalle est demi-ouvert [debut, fin) -- sans ca,
    02h00 appartiendrait a la fois au shift 20h-02h qui finit et au 02h-08h
    qui commence, et une personne tenant les deux serait jugee deux fois
    pour la meme minute.
    """
    h = CRENEAUX_HORAIRES.get((creneau or "").strip())
    if not h:
        return None
    if isinstance(jour_debut, str):
        try:
            jour_debut = datetime.strptime(jour_debut, "%Y-%m-%d").date()
        except ValueError:
            return None
    debut, anom_d = _instant_mural(jour_debut, h[0])
    jour_fin = jour_debut + timedelta(days=1) if h[1] <= h[0] else jour_debut
    fin, anom_f = _instant_mural(jour_fin, h[1])
    duree = int(fin.timestamp() - debut.timestamp())   # jamais fin - debut
    anomalies = [a for a in (anom_d, anom_f) if a]
    return {"creneau": creneau, "jour": jour_debut.isoformat(),
            "debut": debut, "fin": fin, "duree_s": duree,
            "franchit_minuit": h[1] <= h[0],
            "anomalie": " + ".join(anomalies)}


def shift_a(instant) -> Optional[Dict[str, Any]]:
    """Quel shift couvre cet instant, et surtout QUEL JOUR il porte.

    C est la regle qui manquait partout. Le planning range par jour de
    calendrier : une minute de 00h45 tombait donc dans la colonne du
    LENDEMAIN alors que le proprietaire l a cochee la veille, et le dimanche
    soir basculait carrement dans la semaine suivante. On rattache au jour
    de DEBUT du shift -- sessions_voc fait deja exactement ca pour les
    sessions nocturnes des VA.

    `instant` doit etre un datetime aware. Rend None hors de tout shift
    (ce qui n arrive pas aujourd hui : les quatre creneaux couvrent 24 h,
    mais un creneau retire demain ne doit pas rendre un verdict au hasard).
    """
    if instant.tzinfo is None:
        raise ValueError("shift_a exige un datetime aware")
    ici = instant.astimezone(_zone())
    # La veille aussi : un shift de nuit commence hier et couvre ce matin.
    for jour in (ici.date() - timedelta(days=1), ici.date()):
        for creneau in CRENEAUX:
            f = fenetre_shift(creneau, jour)
            if f and f["debut"].timestamp() <= instant.timestamp() < f["fin"].timestamp():
                return f
    return None


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
    safe_json.write_text(PLANNING_FILE, json.dumps(data, indent=2, ensure_ascii=False))


# ==================== EDT CRUD ====================

def list_edts() -> List[Dict[str, Any]]:
    return _load().get("edts", [])


def get_edt(edt_id: str) -> Optional[Dict[str, Any]]:
    for e in list_edts():
        if e.get("id") == edt_id:
            return e
    return None


def create_edt(name: str, kind: str = "chatter") -> Dict[str, Any]:
    """kind = 'chatter' (créneaux fixes) ou 'manager' (horaire libre par ligne)."""
    name = (name or "").strip() or "EDT sans nom"
    data = _load()
    edt = {"id": f"edt_{uuid.uuid4().hex[:10]}", "name": name, "kind": kind, "rows": []}
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
    data = _load()
    for e in data["edts"]:
        if e["id"] == edt_id:
            # Board manager = horaire LIBRE (texte) ; chatteur = créneau fixe
            if e.get("kind") == "manager":
                cre = (creneau or "").strip()
            else:
                cre = creneau if creneau in CRENEAUX else "02h-08h"
            row = {
                "id": f"row_{uuid.uuid4().hex[:10]}",
                "creneau": cre,
                "pseudo": "",
                # Le pseudo Discord du chatteur. C'est le SEUL identifiant qui
                # le relie a une vraie personne : « pseudo » est un texte libre
                # saisi a la main, qui ne correspond a rien d'autre dans le
                # systeme. Rempli = rattachement valide ; vide = a verifier.
                "discord_username": "",
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


def _norm_discord(v) -> str:
    """Un pseudo Discord, tel qu'il sert de cle.

    On accepte ce que l'utilisateur colle — « @Mariamos », « Mariamos »,
    un espace en trop — et on range toujours la meme forme : sans arobase,
    sans espace, en minuscules. Discord est lui-meme passe aux pseudos en
    minuscules, et deux orthographes pour une personne, c'est exactement le
    « deux endroits decident la meme chose » que ce depot paie cher.
    """
    t = str(v or "").strip().lstrip("@").strip()
    return t.lower()[:40]


def update_cell(edt_id: str, row_id: str, field: str, value: str,
                week_start: str = "") -> bool:
    """Update une cellule.
    field = pseudo / discord_username / statut / modele / off / creneau
          | lun/mar/.../dim (pour la semaine donnee)
    """
    data = _load()
    for e in data["edts"]:
        if e["id"] != edt_id:
            continue
        for r in e["rows"]:
            if r["id"] != row_id:
                continue
            if field == "discord_username":
                r[field] = _norm_discord(value)
            elif field in ("pseudo", "statut", "modele", "off", "creneau"):
                r[field] = value
            elif field in DAYS:
                ws = parse_week_start(week_start or current_week_start())
                if "presence_by_week" not in r:
                    r["presence_by_week"] = {}
                if ws not in r["presence_by_week"]:
                    r["presence_by_week"][ws] = _empty_presence()
                if not _valid_day_value(value):
                    value = "Present"
                r["presence_by_week"][ws][field] = value
                # Une saisie humaine se signe. C est ce qui permettra a un
                # pointage automatique de ne JAMAIS ecraser une correction :
                # sans origine, le robot re-accuse en boucle et la
                # contestation devient insoluble.
                _marquer_origine(r, ws, field, "main", "")
            else:
                return False
            _save(data)
            return True
    return False


# ==================== Origine d une case ====================
#
# L origine ne peut PAS vivre dans la valeur du jour. Deux filtres la
# detruisent en silence : update_cell coerce toute valeur inconnue en
# « Present » a l ecriture, et row_presence refait le meme menage a la
# lecture. « Retard#auto » devient donc « Present » — l accusation se
# transforme en presence. Le seul rangement non destructif est une cle
# soeur, parallele a presence_by_week.

def _marquer_origine(row: Dict[str, Any], ws: str, jour: str,
                     src: str, motif: str) -> None:
    src_par_sem = row.setdefault("presence_src_by_week", {})
    src_par_sem.setdefault(ws, {})[jour] = {
        "src": src,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "motif": motif or "",
    }


def origine_case(row: Dict[str, Any], week_start: str, jour: str) -> Dict[str, Any]:
    """Qui a ecrit cette case, et pourquoi. {} si personne ne l a jamais fait.

    {} n est pas « ecrit a la main » : c est « jamais touchee ». Les deux ne
    doivent pas se confondre, parce qu une case jamais touchee se lit
    « Present » par defaut — ce qui ressemble a une presence CONSTATEE alors
    que personne n a rien constate.
    """
    src = row.get("presence_src_by_week") or {}
    sem = src.get(week_start) or src.get(parse_week_start(week_start)) or {}
    v = sem.get(jour)
    return dict(v) if isinstance(v, dict) else {}


def poser_auto(edt_id: str, row_id: str, week_start: str, jour: str,
               valeur: str, motif: str) -> Dict[str, Any]:
    """Ecrit UNE case au nom du robot, ou dit precisement pourquoi il s abstient.

    Rend {"ok": bool, "raison": str}. Jamais un booleen nu : un refus muet
    est indistinguable d un succes, et c est exactement le silence dont ce
    projet s est deja mordu les doigts.

    Trois interdits, chacun ne d une mesure :

    1. NE MATERIALISER QUE LE JOUR VISE. update_cell cree la semaine avec
       sept « Present » quand elle n existe pas. Un robot qui passerait par
       la affirmerait la presence de six autres jours, jours FUTURS compris.
    2. NE JAMAIS ECRASER UNE SAISIE HUMAINE. Une correction du proprietaire
       gele la case definitivement : sans ca, le robot la re-ecrase au
       passage suivant et la correction ne tient pas une minute.
    3. NE JAMAIS TOUCHER AU JOUR DE REPOS DECLARE.
    """
    if not _valid_day_value(valeur):
        return {"ok": False, "raison": "valeur refusee : %r" % valeur}
    if jour not in DAYS:
        return {"ok": False, "raison": "jour inconnu : %r" % jour}
    ws = parse_week_start(week_start)
    data = _load()
    for e in data["edts"]:
        if e["id"] != edt_id:
            continue
        for r in e["rows"]:
            if r["id"] != row_id:
                continue
            if jour_de_repos(r) == jour:
                return {"ok": False, "raison": "jour de repos declare"}
            orig = origine_case(r, ws, jour)
            if orig.get("src") == "main":
                return {"ok": False, "raison": "saisie a la main, gelee"}
            pbw = r.setdefault("presence_by_week", {})
            # setdefault({}) et NON _empty_presence() : les six autres jours
            # restent reellement vides.
            sem = pbw.setdefault(ws, {})
            if sem.get(jour) == valeur and orig.get("src") == "auto":
                return {"ok": False, "raison": "deja pose"}
            sem[jour] = valeur
            _marquer_origine(r, ws, jour, "auto", motif)
            _save(data)
            return {"ok": True, "raison": motif}
        return {"ok": False, "raison": "ligne introuvable"}
    return {"ok": False, "raison": "EDT introuvable"}


# ==================== Presence helpers ====================

def row_presence(row: Dict[str, Any], week_start: str) -> Dict[str, str]:
    """Retourne le dict de presence pour une row sur une semaine donnee.
    Defaut a 'Present' pour tous les jours si non renseigne.
    """
    pbw = row.get("presence_by_week", {})
    # NORMALISER COMME LES ECRIVAINS. update_cell, import_week et
    # fill_row_week passent tous les trois par parse_week_start ; cette
    # lecture-ci faisait un acces BRUT. Une semaine rangee sous son lundi
    # « 2026-09-21 » et relue avec « 2026-09-22 » rendait donc sept
    # « Present » et perdait l incident, sans un mot. Un automate qui lirait
    # avec date.today() ecrirait sous le lundi et relirait du vide : il
    # reposerait le meme verdict a chaque passage.
    p = pbw.get(week_start) or pbw.get(parse_week_start(week_start))
    if not p:
        return _empty_presence()
    out = _empty_presence()
    out.update({k: v for k, v in p.items() if k in DAYS and _valid_day_value(v)})
    return out


def row_counts(row: Dict[str, Any], week_start: str) -> Dict[str, int]:
    """Retourne {retards, absences} pour une row sur une semaine donnee.
    Une case divisee (ex 'Present+Absent') compte l'incident present dedans."""
    pres = row_presence(row, week_start)
    retards = sum(1 for d in DAYS if "Retard" in _day_parts(pres.get(d)))
    absences = sum(1 for d in DAYS if "Absent" in _day_parts(pres.get(d)))
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
        parts = _day_parts(row_presence(row, ws).get(dk, "Present"))
        if "Absent" in parts:
            absn += 1
        if "Retard" in parts:
            retn += 1
        if "Coupure" in parts:
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
