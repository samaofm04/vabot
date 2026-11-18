# -*- coding: utf-8 -*-
"""revenus_managers.py — la paie des managers et des mini-boss.

DEMANDE DU PROPRIETAIRE (18/11/2026) : « je paye mes mini-boss et mes managers
chatter. Les managers prennent un pourcentage par rapport au modele qu'ils
surveillent, pendant quelques shifts. J'aimerais leur attribuer directement
des shifts et un pourcentage, et que ca apparaisse au meme endroit que les
chatteurs. » Il a valide une maquette : deux onglets a cote de « Chatteurs »
et « Transactions », et pour chaque manager un CARRE, une ligne par model,
une colonne par shift, ou l'on coche ce qu'il surveille.

CE QUE CE MODULE DECIDE, ET LUI SEUL

  - la MATRICE : le chiffre d'affaires de chaque model, heure par heure, sur
    la periode affichee (un manager surveille des plages d'heures LIBRES : les
    quatre shifts du site, ou « 8h-12h », ou « 22h-4h »). Une seule fabrique : la page ne reclasse rien de son
    cote, elle additionne des cases deja calculees ici ;
  - ce que chacun TOUCHE : la somme de ses cases, fois son pourcentage ;
  - ce qui est GARDE : data/mypuls_managers.json, ecrit par safe_json.

LA BASE EST CELLE DE LA PAIE DES CHATTEURS : MYM net, OnlyFans brut, en
dollars au taux de la paie. Deux bases pour deux paies de la meme page
auraient fini par se contredire.

TOUTES LES VENTES DE LA MODEL COMPTENT, y compris celles que MyPuls ne
rattache a aucun chatteur (un tiers du chiffre en novembre 2026). C'est le
choix de la maquette qu'il a validee : « un pourcentage de mon CA ». La part
sans chatteur est rendue A PART pour chaque case, et l'ecran la dit : il doit
pouvoir voir sur quoi il paie, pas le deviner.

RIEN N'EST EFFACE. Retirer un manager le range dans « retires », avec la
date : une paie deja cochee doit rester explicable.
"""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

import safe_json

ROLES = ("manager", "miniboss")
#: Le perimetre d'un mini-boss. « of » = tout OnlyFans (FR et US).
PORTEES = ("tout", "mym", "of", "choix")
NB_SHIFTS = 4
_VERROU = threading.RLock()


def _fichier() -> Path:
    import mypuls
    return Path(mypuls.DATA_DIR) / "mypuls_managers.json"


# ------------------------------------------------------------------ lecture
def charger() -> dict:
    """Le fichier, remis en forme : jamais une cle manquante a tester ailleurs."""
    d = safe_json.load(_fichier(), default={})
    if not isinstance(d, dict):
        d = {}
    personnes = [p for p in (d.get("personnes") or []) if isinstance(p, dict) and p.get("id")]
    for p in personnes:
        # relu a chaque fois : une fiche de la premiere version (numeros de
        # shift) sort deja en plages d'heures, et sera reecrite ainsi
        p["cases"] = _cases(p.get("cases"))
    return {"personnes": personnes,
            "paye": d.get("paye") if isinstance(d.get("paye"), dict) else {},
            "retires": d.get("retires") if isinstance(d.get("retires"), list) else []}


def _ecrire(d: dict) -> None:
    safe_json.write(_fichier(), d)


def personnes(role: str = "") -> list:
    return [p for p in charger()["personnes"] if not role or p.get("role") == role]


def trouver(pid: str):
    for p in charger()["personnes"]:
        if p.get("id") == pid:
            return p
    return None


# ------------------------------------------------------------- validation
def _pct(v) -> float:
    """Un pourcentage entre 0 et 100. « 3,5 » comme « 3.5 »."""
    try:
        x = float(str(v if v is not None else "0").replace(",", ".").replace("%", "").strip() or 0)
    except (TypeError, ValueError):
        raise ValueError("Pourcentage illisible : %r" % (v,))
    if not 0 <= x <= 100:
        raise ValueError("Pourcentage hors de 0-100 : %s" % x)
    return round(x, 4)


def creneaux_du_site() -> list:
    """Les quatre shifts du site, proposes d'office comme colonnes du carre."""
    import revenus_chatteurs
    return [list(c) for c in revenus_chatteurs.CRENEAUX]


def heures_de(plage) -> list:
    """Les heures pleines couvertes par [de, a[, en passant minuit s'il le faut.

    [8, 12] -> 8, 9, 10, 11.   [22, 4] -> 22, 23, 0, 1, 2, 3.
    de == a : la journee entiere (« de 8 h a 8 h » fait le tour du cadran).
    """
    de, a = int(plage[0]) % 24, int(plage[1]) % 24
    if de == a:
        return list(range(24))
    heures, h = [], de
    while h != a:
        heures.append(h)
        h = (h + 1) % 24
    return heures


def _plage(v):
    """Une plage [de, a] propre, ou None.

    HEURES LIBRES (demande du 18/11/2026 : « shift 8-12 », et sur Discord un
    manager est note « 22h-4h », a cheval sur deux shifts du site). Un manager
    surveille donc des plages d'heures quelconques, plus les quatre shifts.

    Un ENTIER est l'ancien numero de shift (0 a 3), celui que la premiere
    version enregistrait : il est relu comme la plage du shift, sans que
    personne ait a recocher quoi que ce soit.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit()):
        i, site = int(v), creneaux_du_site()
        return list(site[i]) if 0 <= i < len(site) else None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            de, a = int(v[0]), int(v[1])
        except (TypeError, ValueError):
            return None
        if 0 <= de <= 23 and 0 <= a <= 24:
            return [de, a % 24]
    return None


def _cases(v) -> dict:
    """{cle de model: [[de, a], ...]} — plages triees, sans doublon.

    Une model sans aucune plage cochee ne reste pas dans le fichier : une cle
    vide se lirait « il surveille cette model » dans un an.
    """
    out = {}
    if not isinstance(v, dict):
        return out
    for cle, plages in v.items():
        cle = str(cle).strip()
        if not cle or not isinstance(plages, (list, tuple, set)):
            continue
        bonnes = []
        for brut in plages:
            pl = _plage(brut)
            if pl is not None and pl not in bonnes:
                bonnes.append(pl)
        if bonnes:
            out[cle] = sorted(bonnes)
    return out


def _discord(v) -> str:
    # meme forme que mypuls.set_discord : sans arobase, en minuscules
    return str(v or "").strip().lstrip("@").strip().lower()[:40]


def enregistrer(champs: dict) -> dict:
    """Cree (sans `id`) ou met a jour un manager / mini-boss. Rend la fiche.

    Leve ValueError avec un message lisible : il remonte tel quel a l'ecran.
    Seules les cles PRESENTES dans `champs` sont touchees — cocher « Paye »
    ou corriger une adresse ne doit pas pouvoir vider un carre de shifts.
    """
    import mypuls
    champs = dict(champs or {})
    with _VERROU:
        d = charger()
        pid = str(champs.get("id") or "").strip()
        fiche = next((p for p in d["personnes"] if p.get("id") == pid), None) if pid else None
        if pid and fiche is None:
            raise ValueError("Fiche introuvable (elle a peut-être été retirée)")
        if fiche is None:
            role = str(champs.get("role") or "").strip()
            if role not in ROLES:
                raise ValueError("Rôle inconnu : %r" % role)
            fiche = {"id": ("m_" if role == "manager" else "b_") + secrets.token_hex(4),
                     "role": role, "nom": "", "discord": "", "pct": 0.0, "cases": {},
                     "portee": "tout", "models": [], "cree": time.time()}
            d["personnes"].append(fiche)
            champs.setdefault("nom", "")
        if "nom" in champs:
            nom = " ".join(str(champs.get("nom") or "").split())[:60]
            if not nom:
                raise ValueError("Il faut un nom")
            fiche["nom"] = nom
        if "pct" in champs:
            fiche["pct"] = _pct(champs.get("pct"))
        if "cases" in champs:
            fiche["cases"] = _cases(champs.get("cases"))
        if "portee" in champs:
            portee = str(champs.get("portee") or "").strip()
            if portee not in PORTEES:
                raise ValueError("Périmètre inconnu : %r" % portee)
            fiche["portee"] = portee
        if "models" in champs:
            fiche["models"] = sorted({str(m).strip() for m in (champs.get("models") or []) if str(m).strip()})
        if "discord" in champs:
            pseudo = _discord(champs.get("discord"))
            if pseudo != fiche.get("discord"):
                # un autre Discord (ou plus aucun) : la photo retenue n'est plus la sienne
                for cle in ("discord_avatar", "discord_nom", "discord_maj"):
                    fiche.pop(cle, None)
            fiche["discord"] = pseudo
        if "crypto_type" in champs:
            t = str(champs.get("crypto_type") or "").strip().upper()
            if t and t not in mypuls.CRYPTO_TYPES:
                raise ValueError("Crypto inconnue : %s" % t)
            fiche["crypto_type"] = t
        if "crypto_network" in champs:
            fiche["crypto_network"] = str(champs.get("crypto_network") or "").strip()[:30]
        if "crypto_address" in champs:
            fiche["crypto_address"] = str(champs.get("crypto_address") or "").strip()[:120]
        fiche["maj"] = time.time()
        _ecrire(d)
        return dict(fiche)


def retenir_discord(pid: str, avatar: str, nom: str) -> None:
    """Ce que Discord a rendu pour lui (photo, nom affiche), a la date du jour."""
    with _VERROU:
        d = charger()
        for p in d["personnes"]:
            if p.get("id") == pid:
                p["discord_avatar"], p["discord_nom"] = str(avatar or ""), str(nom or "")
                p["discord_maj"] = time.time()
                _ecrire(d)
                return


def retirer(pid: str) -> bool:
    """Range la fiche dans « retires ». Rien n'est efface."""
    with _VERROU:
        d = charger()
        garde, parti = [], None
        for p in d["personnes"]:
            if p.get("id") == pid and parti is None:
                parti = p
            else:
                garde.append(p)
        if parti is None:
            return False
        d["personnes"] = garde
        d["retires"].append(dict(parti, retire=time.time()))
        _ecrire(d)
        return True


def _cle_periode(debut: str, fin: str) -> str:
    return "%s|%s" % (str(debut)[:10], str(fin)[:10])


def marquer_paye(pid: str, debut: str, fin: str, paye: bool) -> list:
    """Coche ou decoche « Paye » pour UNE periode. Rend les ids payes."""
    with _VERROU:
        d = charger()
        if not any(p.get("id") == pid for p in d["personnes"]):
            raise ValueError("Fiche introuvable")
        cle = _cle_periode(debut, fin)
        ids = [i for i in (d["paye"].get(cle) or []) if i != pid]
        if paye:
            ids.append(pid)
        if ids:
            d["paye"][cle] = ids
        else:
            d["paye"].pop(cle, None)
        _ecrire(d)
        return ids


def payes(debut: str, fin: str) -> list:
    return list(charger()["paye"].get(_cle_periode(debut, fin)) or [])


# ------------------------------------------------------------------ calcul
def cle_model(nom: str, comptes: dict) -> str:
    """L'identifiant MyPuls quand on le connait (il survit a un renommage,
    comme Emy devenue emy.brww), sinon le nom."""
    cid = (comptes or {}).get(nom)
    return str(cid) if cid not in (None, "") else "nom:" + str(nom)


def _ligne_vide(nom: str, segment: str) -> dict:
    return {"nom": nom, "segment": segment,
            "heures": [0.0] * 24, "sans_chatteur_h": [0.0] * 24,
            "shifts": [0.0] * NB_SHIFTS, "sans_chatteur": [0.0] * NB_SHIFTS,
            "total": 0.0, "sans_heure": 0.0}


def matrice(ventes, taux: float, comptes: dict = None, segments: dict = None) -> dict:
    """Le chiffre d'affaires de chaque model, shift par shift.

    {"lignes": {cle: {"nom", "segment", "heures": [24], "sans_chatteur_h": [24],
                      "shifts": [4], "sans_chatteur": [4], "total", "sans_heure"}},
     "ordre": [cles, du plus gros chiffre au plus petit],
     "ecartees": n}

    `heures` : le chiffre de chaque heure de Paris (0 a 23), base de la paie,
    en dollars (MYM net converti, OnlyFans brut). C'est de la que sort TOUTE
    plage d'heures, libre ou non. `shifts` en est le resume par shift du site.
    `sans_chatteur_h` / `sans_chatteur` : la part que MyPuls ne rattache a personne.
    `total` : la model sur 24 h, ventes sans heure lisible comprises
    (`sans_heure`) — c'est la base d'un mini-boss, qui n'a pas de shift.
    `ecartees` : ventes sans nom de model, comptees nulle part ici ; le nombre
    remonte pour etre dit, jamais ecarte en silence.
    """
    import revenus_chatteurs
    from revenus_dates import transaction_hour
    try:
        from ventes_export import est_non_attribue
    except Exception:                                   # noqa: BLE001
        def est_non_attribue(_n):
            return False
    lignes, ecartees = {}, 0
    for t in (ventes or []):
        nom = str(t.get("creator") or "").strip()
        if not nom:
            ecartees += 1
            continue
        try:
            montant = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            montant = 0.0
        devise = str(t.get("currency") or "").upper()
        usd = montant if ("USD" in devise or "$" in devise) else montant * float(taux or 1)
        cle = cle_model(nom, comptes)
        l = lignes.get(cle)
        if l is None:
            l = lignes[cle] = _ligne_vide(nom, (segments or {}).get(nom, ""))
        l["total"] += usd
        heure = transaction_hour(t.get("date"))
        if not 0 <= heure <= 23:
            l["sans_heure"] += usd
            continue
        sans = not str(t.get("chatter") or "").strip() or est_non_attribue(str(t.get("chatter")))
        l["heures"][heure] += usd
        if sans:
            l["sans_chatteur_h"][heure] += usd
        s = revenus_chatteurs.creneau(heure)
        if s >= 0:
            l["shifts"][s] += usd
            if sans:
                l["sans_chatteur"][s] += usd
    # TOUTES les models connues ont leur ligne, meme sans vente : sur une
    # periode courte (« Aujourd'hui »), le carre n'aurait montre que deux ou
    # trois models et on n'aurait pas pu cocher les autres.
    for nom in (comptes or {}):
        cle = cle_model(nom, comptes)
        if cle not in lignes:
            lignes[cle] = _ligne_vide(str(nom), (segments or {}).get(nom, ""))
    for l in lignes.values():
        for champ in ("shifts", "sans_chatteur", "heures", "sans_chatteur_h"):
            l[champ] = [round(x, 2) for x in l[champ]]
        l["total"], l["sans_heure"] = round(l["total"], 2), round(l["sans_heure"], 2)
    ordre = sorted(lignes, key=lambda k: (-lignes[k]["total"], lignes[k]["nom"].lower()))
    return {"lignes": lignes, "ordre": ordre, "ecartees": ecartees}


def dans_la_portee(fiche: dict, cle: str, ligne: dict) -> bool:
    """Cette model est-elle dans le perimetre de ce mini-boss ?"""
    portee = fiche.get("portee") or "tout"
    seg = ligne.get("segment") or ""
    if portee == "tout":
        return True
    if portee == "mym":
        return seg == "mym"
    if portee == "of":
        return seg in ("of_fr", "of_us")
    return cle in set(fiche.get("models") or [])


def du(fiche: dict, mat: dict) -> dict:
    """Ce que cette personne touche sur la matrice de la periode.

    {"ca", "a_payer", "nb_cases", "nb_models", "sans_chatteur"}

    Manager : pour chaque model, les heures de ses plages (comptees une seule
    fois si deux plages se recoupent). Une plage cochee sur une model sans
    vente dans la periode vaut zero mais reste cochee : la periode suivante
    peut la remplir.
    Mini-boss : les models de son perimetre, sur 24 h.
    """
    lignes = (mat or {}).get("lignes") or {}
    ca = sans = 0.0
    nb_cases = 0
    models = set()
    if fiche.get("role") == "miniboss":
        for cle, l in lignes.items():
            if dans_la_portee(fiche, cle, l):
                ca += l["total"]
                sans += sum(l["sans_chatteur"])
                models.add(cle)
    else:
        for cle, plages in _cases(fiche.get("cases")).items():
            nb_cases += len(plages)
            models.add(cle)
            l = lignes.get(cle)
            if not l:
                continue
            # L'UNION des heures : deux plages qui se recoupent pour la meme
            # model (14h-20h et 18h-22h) ne paient pas deux fois 18h-20h.
            heures = set()
            for pl in plages:
                heures.update(heures_de(pl))
            ca += sum(l["heures"][h] for h in heures)
            sans += sum(l["sans_chatteur_h"][h] for h in heures)
    pct = float(fiche.get("pct") or 0)
    return {"ca": round(ca, 2), "a_payer": round(ca * pct / 100.0, 2), "nb_cases": nb_cases,
            "nb_models": len(models), "sans_chatteur": round(sans, 2)}
