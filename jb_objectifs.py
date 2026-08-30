# -*- coding: utf-8 -*-
"""jb_objectifs.py - l'objectif d'une fiche VA, et ou elle en est.

Une fiche VA (un couple identite + nom du VA, c'est-a-dire UN telephone) doit
tenir un nombre de comptes VIVANTS. Par defaut trente. Ce module tient cet
objectif, mesure ou en est chaque fiche, garde la trace de chaque journee, et
en tire le bilan de la quinzaine.

**Ce qu'est un compte actif, et pourquoi.** Un compte compte comme actif s'il
n'est pas banni ET s'il remplit l'une des deux conditions suivantes :

  - il a publie dans les 48 dernieres heures ;
  - il a ete cree il y a moins de cinq jours.

La premiere est la regle d'assiduite deja en place dans `jb_activity`
(SILENCE_SEC = 48 h) ; la seconde est le warm-up de cinq jours deja annonce a
l'ecran de l'Activite VA. Rien n'est invente ici : un compte tout neuf ne
publie pas encore, et le compter en faute reviendrait a punir un VA pour avoir
fait exactement ce qu'on lui demande. Ces deux valeurs sont RELUES depuis
`jb_activity` quand il est disponible, pour qu'un changement la-bas ne laisse
pas deux regles differentes tourner en meme temps.

**Une seule fonction de calcul.** `etat_fiche` sert au tableau de bord ET au
report de minuit. Deux implementations de « combien de comptes actifs ? »
finiraient par se contredire, et c'est le genre de desaccord qu'on ne
remarque que le jour ou quelqu'un conteste une retenue de paie.

**La source des chiffres est le cache de scrape**, `va_insta_3_stats_cache`,
c'est-a-dire exactement ce que les lignes du tableau affichent. C'est une
lecon deja payee : les compteurs de la fiche VA lisaient autrefois un scan
separe et souvent perime, d'ou des ecrans qui annoncaient « 8/10 scrapes »
et « 2 actifs » sans que ce soit reconciliable.

Stockage (data/, jamais dans git) :
    jb_objectifs.json       -> {"<identite>|<va>": {"objectif": 30, ...}}
    jb_report_comptes.json  -> {"<identite>|<va>": {"jours": {"AAAA-MM-JJ": {...}}}}
"""
from __future__ import annotations

import datetime as _dt
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path("data")
OBJECTIFS_FILE = DATA_DIR / "jb_objectifs.json"
HISTO_FILE = DATA_DIR / "jb_report_comptes.json"

_LOCK = threading.RLock()

#: Ce qu'on attend d'un telephone tant que personne n'a dit autre chose.
OBJECTIF_DEFAUT = 30

#: Part de l'objectif a partir de laquelle la journee est consideree tenue.
#: 80 % de trente font vingt-quatre.
SEUIL_REUSSITE = 0.80

#: Au-dela de ce nombre de jours d'historique, on oublie. Deux quinzaines
#: pleines plus une marge : de quoi rendre le bilan en cours et le precedent.
HISTO_JOURS = 70


#: Le warm-up est un REGLAGE, pas une constante : l'ecran « Activite VA » le
#: modifie dans ce fichier. On le relit a chaque mesure pour qu'un changement
#: la-bas s'applique ici aussi — deux valeurs de warm-up qui divergent, ce
#: sont deux ecrans qui se contredisent sur le meme compte.
VA_ACT_CFG = DATA_DIR / "va_activity_cfg.json"


def _regles() -> tuple:
    """(secondes de silence tolerees, jours de warm-up).

    Les deux valeurs viennent d'ailleurs, a dessein : le silence de
    `jb_activity.SILENCE_SEC`, le warm-up du reglage de l'Activite VA. Ce
    module ne definit aucune regle d'assiduite qui lui soit propre — les
    valeurs ecrites ci-dessous ne servent que si la source est illisible, et
    elles doivent rester identiques aux siennes.
    """
    silence, warmup = 48 * 3600, 5
    try:
        import jb_activity as _ja
        silence = int(getattr(_ja, "SILENCE_SEC", silence) or silence)
    except Exception:
        pass
    try:
        cfg = safe_json.load(VA_ACT_CFG, default={}) or {}
        if isinstance(cfg, dict):
            warmup = int(cfg.get("warmup_days") or warmup)
    except Exception:
        pass
    return max(1, silence), max(0, warmup)


# ==============================================================================
# Cles et stockage
# ==============================================================================

def cle(identite: str, va: str) -> str:
    """La cle d'une fiche. Minuscules des deux cotes : le nom d'un VA se
    ressaisit a la main, et « Noum » ne doit pas devenir une autre fiche que
    « noum »."""
    return f"{str(identite or '').strip().lower()}|{str(va or '').strip().lower()}"


def _load(chemin: Path) -> Dict[str, Any]:
    d = safe_json.load(chemin, default={})
    return d if isinstance(d, dict) else {}


def _save(chemin: Path, d: Dict[str, Any]) -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return bool(safe_json.write(chemin, d))
    except Exception:
        return False


def objectif_de(identite: str, va: str) -> int:
    """L'objectif de cette fiche, ou le defaut si personne ne l'a fixe."""
    rec = _load(OBJECTIFS_FILE).get(cle(identite, va))
    if isinstance(rec, dict):
        try:
            n = int(rec.get("objectif") or 0)
            if n > 0:
                return n
        except Exception:
            pass
    return OBJECTIF_DEFAUT


def tous_les_objectifs() -> Dict[str, int]:
    out = {}
    for k, rec in _load(OBJECTIFS_FILE).items():
        if isinstance(rec, dict):
            try:
                n = int(rec.get("objectif") or 0)
                if n > 0:
                    out[k] = n
            except Exception:
                pass
    return out


def fixer_objectif(identite: str, va: str, objectif) -> int:
    """Fixe l'objectif d'une fiche. Rend la valeur retenue.

    `objectif` vide, nul ou negatif REMET LA FICHE AU DEFAUT au lieu de poser
    zero : un objectif a zero serait toujours atteint, ce qui est la meilleure
    facon de rendre un indicateur muet sans que personne s'en apercoive.
    """
    k = cle(identite, va)
    try:
        n = int(str(objectif).strip() or 0)
    except Exception:
        n = 0
    # Plafond de bon sens : au-dela, c'est une faute de frappe, pas un objectif.
    n = max(0, min(n, 999))
    with _LOCK:
        d = _load(OBJECTIFS_FILE)
        if n <= 0:
            d.pop(k, None)
            _save(OBJECTIFS_FILE, d)
            return OBJECTIF_DEFAUT
        d[k] = {"objectif": n, "modifie": int(time.time())}
        _save(OBJECTIFS_FILE, d)
        return n


# ==============================================================================
# Mesure
# ==============================================================================

def _handle(brut: str) -> str:
    """Meme normalisation que le scrape, sinon on cherche la mauvaise cle."""
    h = str(brut or "").strip().lstrip("@").strip()
    h = re.sub(r"[^a-zA-Z0-9_.]", "", h).lower()
    return h if h and len(h) <= 30 else ""


def _jour_paris(ts: float) -> str:
    """Le jour calendaire d'un horodatage, en heure de Paris.

    Les cles de `reel_days` sont ecrites en date Paris. Comparer avec une date
    UTC ferait glisser d'un jour tout ce qui est publie apres 22 h l'ete —
    c'est-a-dire une bonne partie des publications du soir.
    """
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.fromtimestamp(ts, ZoneInfo("Europe/Paris")).date().isoformat()
    except Exception:
        return _dt.datetime.fromtimestamp(ts).date().isoformat()


def aujourdhui() -> str:
    return _jour_paris(time.time())


def etat_compte(compte: dict, stats: dict, maintenant: float,
                jour: str, silence_sec: int, warmup_jours: int) -> dict:
    """Ce qu'on sait d'UN compte aujourd'hui.

    Rend {actif, banni, warmup, publie_aujourdhui, cree_aujourdhui, oublie}.
    Un compte peut etre a la fois `warmup` et `publie_aujourdhui` : ce sont
    deux faits, pas deux categories exclusives.
    """
    h = _handle(compte.get("username"))
    s = (stats or {}).get(h) or {}
    banni = bool(s.get("banned"))

    cree = 0
    try:
        cree = int(compte.get("created_at") or 0)
    except Exception:
        cree = 0
    en_warmup = bool(cree) and (maintenant - cree) < warmup_jours * 86400
    cree_aujourdhui = bool(cree) and _jour_paris(cree) == jour

    # A-t-il publie AUJOURD'HUI ? reel_days compte les reels par jour de
    # publication, les reels a zero vue compris — c'est la seule source qui
    # dise « il a publie » plutot que « il a fait des vues ».
    publie = False
    for source in ("reel_days", "post_days"):
        try:
            if int((s.get(source) or {}).get(jour) or 0) > 0:
                publie = True
                break
        except Exception:
            pass

    # A-t-il publie dans les 48 h ?
    recent = False
    brut = s.get("last_reel_at") or s.get("last_post_at")
    if brut:
        try:
            d = _dt.datetime.fromisoformat(str(brut).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=_dt.timezone.utc)
            recent = (maintenant - d.timestamp()) <= silence_sec
        except Exception:
            recent = False

    actif = (not banni) and (recent or en_warmup)
    # Un compte en warm-up n'est PAS un oubli : il n'a rien oublie, il n'a
    # simplement pas encore commence. Un banni non plus — il n'y a plus
    # personne derriere.
    oublie = (not banni) and (not en_warmup) and (not recent)
    return {
        "handle": h,
        "actif": actif,
        "banni": banni,
        "warmup": en_warmup,
        "publie_aujourdhui": publie,
        "cree_aujourdhui": cree_aujourdhui,
        "oublie": oublie,
        "jamais_scrape": not s,
    }


def etat_fiche(identite: str, va: str, comptes: List[dict],
               stats: dict, maintenant: Optional[float] = None,
               jour: str = "") -> dict:
    """Ou en est une fiche AUJOURD'HUI. La seule fonction qui compte.

    Le tableau de bord et le report de minuit l'appellent tous les deux : deux
    facons de compter « les comptes actifs » finiraient par se contredire, et
    ce desaccord ne se remarque que le jour ou quelqu'un conteste sa paie.
    """
    maintenant = time.time() if maintenant is None else maintenant
    jour = jour or _jour_paris(maintenant)
    silence_sec, warmup_jours = _regles()

    lignes = [etat_compte(c, stats, maintenant, jour, silence_sec, warmup_jours)
              for c in (comptes or []) if isinstance(c, dict)]

    objectif = objectif_de(identite, va)
    actifs = sum(1 for x in lignes if x["actif"])
    seuil = _seuil(objectif)
    return {
        "identite": str(identite or ""),
        "va": str(va or ""),
        "jour": jour,
        "total": len(lignes),
        "actifs": actifs,
        "bannis": sum(1 for x in lignes if x["banni"]),
        "warmup": sum(1 for x in lignes if x["warmup"]),
        "publie": sum(1 for x in lignes if x["publie_aujourdhui"]),
        "ajoutes": sum(1 for x in lignes if x["cree_aujourdhui"]),
        "oublies": sum(1 for x in lignes if x["oublie"]),
        "jamais_scrapes": sum(1 for x in lignes if x["jamais_scrape"]),
        "objectif": objectif,
        "seuil": seuil,
        "pct": round(100.0 * actifs / objectif, 1) if objectif else 0.0,
        "atteint": actifs >= seuil,
    }


def _seuil(objectif: int) -> int:
    """Le nombre de comptes actifs a partir duquel la journee est tenue.

    On arrondit au SUPERIEUR : a 80 % de trente, vingt-quatre virgule zero
    tombe juste, mais sur un objectif de dix-neuf le seuil vaut 15,2 — et
    accepter quinze reviendrait a valider 78,9 %, c'est-a-dire moins que ce
    qui est annonce.
    """
    import math
    return max(1, int(math.ceil(objectif * SEUIL_REUSSITE))) if objectif else 0


# ==============================================================================
# Historique et quinzaine
# ==============================================================================

def quinzaine(jour: str) -> tuple:
    """(premier jour, dernier jour) de la quinzaine qui contient `jour`.

    Du 1 au 15, puis du 16 a la fin du mois — les memes bornes que le report
    de clics et que la paie, pour qu'un VA n'ait pas deux calendriers.
    """
    d = _dt.date.fromisoformat(jour)
    if d.day <= 15:
        return (d.replace(day=1).isoformat(), d.replace(day=15).isoformat())
    if d.month == 12:
        fin = _dt.date(d.year, 12, 31)
    else:
        fin = _dt.date(d.year, d.month + 1, 1) - _dt.timedelta(days=1)
    return (d.replace(day=16).isoformat(), fin.isoformat())


def enregistrer_jour(etats: List[dict], jour: str = "") -> int:
    """Grave le bilan du jour pour chaque fiche. Rend le nombre de fiches ecrites.

    Idempotent : relancer le report deux fois le meme jour reecrit la meme
    journee au lieu de la compter deux fois.
    """
    jour = jour or aujourdhui()
    if not etats:
        return 0
    with _LOCK:
        d = _load(HISTO_FILE)
        limite = (_dt.date.fromisoformat(jour) - _dt.timedelta(days=HISTO_JOURS)).isoformat()
        for e in etats:
            k = cle(e.get("identite"), e.get("va"))
            rec = d.get(k) if isinstance(d.get(k), dict) else {}
            jours = rec.get("jours") if isinstance(rec.get("jours"), dict) else {}
            jours[jour] = {
                "total": e.get("total", 0), "actifs": e.get("actifs", 0),
                "publie": e.get("publie", 0), "ajoutes": e.get("ajoutes", 0),
                "oublies": e.get("oublies", 0), "bannis": e.get("bannis", 0),
                "objectif": e.get("objectif", 0), "atteint": bool(e.get("atteint")),
            }
            # Purge des jours trop vieux, sinon le fichier grossit sans fin.
            jours = {j: v for j, v in jours.items() if str(j) >= limite}
            rec["jours"] = jours
            rec["va"] = e.get("va") or rec.get("va") or ""
            rec["identite"] = e.get("identite") or rec.get("identite") or ""
            d[k] = rec
        _save(HISTO_FILE, d)
        return len(etats)


def bilan_quinzaine(identite: str, va: str, jour: str = "") -> dict:
    """Le bilan de la quinzaine en cours pour une fiche.

    `jours_tenus` sur `jours_notes` : on ne compte QUE les journees pour
    lesquelles un report existe. Un report qui n'a pas tourne (redemarrage,
    panne) ne doit pas se lire comme une journee ratee — sinon la premiere
    coupure de service transforme un bon VA en mauvais.
    """
    jour = jour or aujourdhui()
    debut, fin = quinzaine(jour)
    rec = _load(HISTO_FILE).get(cle(identite, va)) or {}
    jours = rec.get("jours") if isinstance(rec.get("jours"), dict) else {}
    dans = {j: v for j, v in jours.items() if debut <= str(j) <= fin and isinstance(v, dict)}
    notes = len(dans)
    tenus = sum(1 for v in dans.values() if v.get("atteint"))

    # La suite JOUR PAR JOUR, du debut de la quinzaine jusqu'a aujourd'hui.
    # C'est ce qui sert a payer : un total « 12/14 » ne dit pas s'il a lache
    # trois jours d'affilee ou un jour de temps en temps, et ce n'est pas la
    # meme conversation. On s'arrete a AUJOURD'HUI : afficher les jours a venir
    # comme non tenus reprocherait a quelqu'un de ne pas avoir encore vecu.
    suite = []
    d = _dt.date.fromisoformat(debut)
    stop = min(_dt.date.fromisoformat(fin), _dt.date.fromisoformat(jour))
    while d <= stop:
        k = d.isoformat()
        if k in dans:
            suite.append("tenu" if dans[k].get("atteint") else "rate")
        else:
            suite.append("inconnu")     # pas de report ce jour-la
        d += _dt.timedelta(days=1)
    # La bande couvre TOUTE la quinzaine ecoulee, y compris les jours d'avant
    # la premiere mesure. Elle a un temps ete rognee de ses jours sans donnee
    # en tete, parce qu'ils s'affichaient en carres BLANCS et se lisaient comme
    # autant d'echecs. Le probleme etait la couleur, pas leur presence : le
    # blanc est devenu un carre sombre, qui se lit « rien », et la bande fait
    # de nouveau la longueur de la quinzaine — quinze jours, seize, ou
    # vingt-huit en fevrier.
    #
    # Elle s'arrete a AUJOURD'HUI : les jours a venir ne sont pas pre-remplis.

    return {
        "debut": debut, "fin": fin,
        "jours_notes": notes, "jours_tenus": tenus,
        "pct": round(100.0 * tenus / notes, 1) if notes else 0.0,
        "pastille": pastille(tenus, notes),
        "suite": suite,
    }


def bilan_mois(identite: str, va: str, jour: str = "") -> dict:
    """Le MOIS entier, jour par jour, coupé en ses deux quinzaines de paie.

    Le bilan ne portait que sur la quinzaine en cours. Au moment de payer on
    veut voir le mois : la quinzaine qu'on solde, et celle d'avant qui donne
    le contexte. Les deux moitiés restent distinctes — ce sont deux périodes
    de paie, pas une seule longue bande.

    La suite s'arrête à `jour` : les jours à venir ne sont pas pré-remplis.
    """
    jour = jour or aujourdhui()
    d = _dt.date.fromisoformat(jour)
    debut = d.replace(day=1)
    if d.month == 12:
        fin = _dt.date(d.year, 12, 31)
    else:
        fin = _dt.date(d.year, d.month + 1, 1) - _dt.timedelta(days=1)

    rec = _load(HISTO_FILE).get(cle(identite, va)) or {}
    jours = rec.get("jours") if isinstance(rec.get("jours"), dict) else {}

    suite, q1, q2 = [], [0, 0], [0, 0]      # [tenus, notes] par quinzaine
    cur, stop = debut, min(fin, d)
    while cur <= stop:
        k = cur.isoformat()
        v = jours.get(k)
        cible = q1 if cur.day <= 15 else q2
        if isinstance(v, dict):
            tenu = bool(v.get("atteint"))
            suite.append("tenu" if tenu else "rate")
            cible[1] += 1
            cible[0] += 1 if tenu else 0
        else:
            suite.append("inconnu")
        cur += _dt.timedelta(days=1)

    # La pastille porte sur la quinzaine EN COURS : c'est celle qu'on solde.
    encours = q1 if d.day <= 15 else q2
    return {
        "debut": debut.isoformat(), "fin": fin.isoformat(), "jour": jour,
        "suite": suite,
        "coupure": 15,                      # nombre de jours de la 1re moitie
        "q1_tenus": q1[0], "q1_notes": q1[1],
        "q2_tenus": q2[0], "q2_notes": q2[1],
        "jours_tenus": encours[0], "jours_notes": encours[1],
        "pct": round(100.0 * encours[0] / encours[1], 1) if encours[1] else 0.0,
        "pastille": pastille(encours[0], encours[1]),
    }


def pastille(tenus: int, notes: int) -> str:
    """La pastille de la quinzaine. '⚪' tant qu'on n'a rien a dire.

    Volontairement muette au debut : afficher un rouge apres une seule journee
    notee, c'est condamner quelqu'un sur un echantillon d'un.
    """
    if notes < 3:
        return "⚪"
    part = tenus / notes
    if part >= 0.8:
        return "🟢"
    if part >= 0.5:
        return "🟠"
    return "🔴"
