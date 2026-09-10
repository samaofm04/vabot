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
#: Trente pendant longtemps, VINGT depuis le 07/09/2026 : le proprietaire a
#: constate que ses VA n'y arrivaient pas et prefere une cible tenable a une
#: cible que personne n'atteint - un objectif jamais atteint ne pilote plus
#: rien, il se lit comme du bruit.
OBJECTIF_DEFAUT = 20

#: Part de l'objectif a partir de laquelle la journee est consideree tenue.
#: 80 % de vingt font seize.
SEUIL_REUSSITE = 0.80

# --- La paie meritee ------------------------------------------------------
# CINQ DOLLARS LA JOURNEE, QUINZE JOURS LA QUINZAINE, SOIXANTE-QUINZE AU BOUT.
# Le calendrier reel donne des quinzaines de treize a seize jours, donc des
# journees a 4,69 $, 5,00 $ ou 5,77 $ selon le mois : trois chiffres a
# expliquer a un VA pour une paie identique. Le proprietaire a tranche - « on
# part du principe que tous les mois font trente jours ». Le modele de paie
# compte donc quinze jours partout, et le calendrier ne le regarde plus.
PAIE_JOUR = 5.0
JOURS_QUINZAINE = 15
PAIE_QUINZAINE = PAIE_JOUR * JOURS_QUINZAINE      # 75 $

# LE DENOMINATEUR EST FIGE A VINGT, ET CE N'EST PAS L'OBJECTIF DE LA FICHE.
# L'objectif sert a dire si la journee est tenue ; il vaut trente par defaut
# et se regle fiche par fiche. La paie, elle, se calcule toujours sur vingt :
# le proprietaire a constate que ses VA ne tiennent pas trente comptes, et il
# ne veut pas qu'un objectif releve sur une fiche fasse mecaniquement baisser
# la paie de ce VA-la. Deux questions differentes, deux nombres differents.
BASE_COMPTES = 20

#: Au-dela de ce nombre de jours d'historique, on oublie. Deux quinzaines
#: pleines plus une marge : de quoi rendre le bilan en cours et le precedent.
HISTO_JOURS = 70


#: Le warm-up est un REGLAGE, pas une constante : l'ecran « Activite VA » le
#: modifie dans ce fichier. On le relit a chaque mesure pour qu'un changement
#: la-bas s'applique ici aussi — deux valeurs de warm-up qui divergent, ce
#: sont deux ecrans qui se contredisent sur le meme compte.
VA_ACT_CFG = DATA_DIR / "va_activity_cfg.json"


#: Le perimetre du scrape, ecrit par l'ecran Jailbreak.
SCRAPE_IDENTS_FILE = DATA_DIR / "scrape_identites.json"


def suivi_actif(identite: str) -> bool:
    """Les comptes de cette identite sont-ils encore scrapes ?

    On relit le fichier plutot que d'importer web_upload : ce module est
    appele DEPUIS web_upload, et le report de minuit tourne sans lui. Meme
    motif que `_regles`, qui relit deja la configuration de l'Activite VA.

    Sans fichier, tout est suivi — c'est l'etat d'avant le reglage, et il ne
    faut surtout pas que son absence eteigne tout le monde.
    """
    try:
        d = safe_json.load(SCRAPE_IDENTS_FILE, default=None)
        if isinstance(d, dict) and isinstance(d.get("actives"), list):
            return str(identite or "").strip().lower() in {
                str(x).strip().lower() for x in d["actives"]}
    except Exception:
        pass
    return True


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
        # La FONCTION d'abord : c'est elle qui lit le reglage. La constante
        # ne sert que si une vieille version du module traine encore.
        if callable(getattr(_ja, "silence_sec", None)):
            silence = int(_ja.silence_sec() or silence)
        else:
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
        # ON FUSIONNE, ON N'ECRASE PAS. La fiche porte aussi le tarif du VA et
        # son nombre de comptes a servir : ecrire l'objectif d'un bloc, comme
        # avant, les aurait effaces sans un mot - et personne ne remarque une
        # paie revenue au defaut avant le virement.
        rec = d.get(k) if isinstance(d.get(k), dict) else {}
        if n <= 0:
            rec.pop("objectif", None)
            if rec:
                rec["modifie"] = int(time.time())
                d[k] = rec
            else:
                d.pop(k, None)
            _save(OBJECTIFS_FILE, d)
            return OBJECTIF_DEFAUT
        rec["objectif"] = n
        rec["modifie"] = int(time.time())
        d[k] = rec
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
                jour: str, silence_sec: int, warmup_jours: int,
                suivi: bool = True) -> dict:
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
    # « NON MESURE » : L'ETAT QUI MANQUAIT.
    # Un compte etait actif ou il ne l'etait pas ; il n'existait pas d'etat
    # « on ne sait pas ». Des qu'on cesse de scraper une identite, sa date de
    # dernier post cesse d'avancer : quarante-huit heures plus tard, TOUS ses
    # comptes basculent en « oublie » — un mot qui accuse le VA — et sa paie
    # tombe a zero. Personne n'a rien fait de mal : on a arrete de regarder.
    #
    # Un compte non mesure n'est ni actif, ni oublie. Il sort du calcul.
    non_mesure = (not banni) and (not suivi)
    if non_mesure:
        actif = False
        oublie = False
    return {
        "handle": h,
        "actif": actif,
        "non_mesure": non_mesure,
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

    suivi = suivi_actif(identite)
    lignes = [etat_compte(c, stats, maintenant, jour, silence_sec, warmup_jours,
                          suivi)
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
        "non_mesures": sum(1 for x in lignes if x.get("non_mesure")),
        # `suivi` voyage avec la mesure : sans lui, l'ecran qui affiche ces
        # chiffres ne peut pas savoir s'ils valent quelque chose.
        "suivi": suivi,
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
    # ON NE GRAVE PAS UNE JOURNEE QU'ON N'A PAS REGARDEE.
    #
    # Une fiche dont l'identite n'est plus scrapee produirait une journee
    # « 0 publie, tout le monde oublie », indiscernable d'une vraie journee a
    # zero une fois ecrite — et c'est ce fichier qui sert a PAYER. Pire : la
    # purge garde les soixante-dix derniers jours, donc ces faux zeros
    # finiraient par chasser les vraies journees du fichier.
    #
    # L'absence, elle, est deja traitee honnetement partout : `bilan_quinzaine`
    # ne compte que les journees notees, `paie_quinzaine` les range dans
    # « jours_non_mesures » et le portail du VA ecrit « pas de releve ce
    # jour-la ». On laisse donc un TROU, qui dit la verite.
    gardes, ignores = [], []
    for e in etats:
        if isinstance(e, dict) and e.get("suivi") is False:
            ignores.append(str(e.get("identite") or "") + "|" + str(e.get("va") or ""))
        else:
            gardes.append(e)
    if ignores:
        print("[objectifs] %d fiche(s) non gravee(s) — identite non suivie : %s"
              % (len(ignores), ", ".join(sorted(set(ignores))[:8])), flush=True)
    etats = gardes
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


# ==============================================================================
# Renommage : suivre une fiche qui change de nom
# ==============================================================================
#
# Les deux fichiers de ce module sont indexes par `cle(identite, va)`, donc par
# DEUX NOMS MODIFIABLES. Renommer une fiche dans jailbreak.json sans toucher a
# ces cles orphelinait tout son passe : le bilan du 20 du mois repartait a
# « aucune journee notee » — dix-neuf jours tenus effaces d un document qui sert
# a PAYER — et `objectif_de` ne retrouvant plus rien rendait OBJECTIF_DEFAUT,
# donc une fiche reglee a 12 comptes voyait son seuil passer de 10 a 24 et
# echouait toutes les nuits suivantes.
#
# Renommer est une operation de routine : le site (✎ Modifier) et le poller
# Google Sheet le font. Ce n etait donc pas un cas tordu.


def _fusionner_jours(dest: dict, source: dict) -> dict:
    """Fond deux enregistrements d historique. La SOURCE l emporte.

    La source est la fiche VIVANTE, celle qu on vient de renommer. La
    destination, quand elle existe, est ce que laisse une fiche disparue qui
    portait deja ce nom. On garde quand meme ses journees : on ne jette rien
    d un document de paie, meme vieux, meme en doublon.
    """
    jd = dest.get("jours") if isinstance(dest.get("jours"), dict) else {}
    js = source.get("jours") if isinstance(source.get("jours"), dict) else {}
    fondu = dict(jd)
    fondu.update(js)
    source["jours"] = fondu
    return source


def _deplacer(chemin, paires, histo: bool) -> tuple:
    """Deplace des cles dans un des deux fichiers. Rend (deplacees, fusions)."""
    d = _load(chemin)
    bouge, fusions = 0, 0
    for ancienne, nouvelle, va, ident in paires:
        if ancienne == nouvelle or ancienne not in d:
            continue
        rec = d.pop(ancienne)
        if nouvelle in d:
            fusions += 1
            if histo and isinstance(rec, dict) and isinstance(d[nouvelle], dict):
                rec = _fusionner_jours(d[nouvelle], rec)
        if histo and isinstance(rec, dict):
            # Les champs d affichage suivent la cle, sinon le bilan afficherait
            # l ancien nom a cote du nouveau.
            if va:
                rec["va"] = va
            if ident:
                rec["identite"] = ident
        d[nouvelle] = rec
        bouge += 1
    if bouge:
        _save(chemin, d)
    return bouge, fusions


def renommer_fiche(identite: str, ancien: str, nouveau: str) -> dict:
    """Fait suivre l historique de paie ET l objectif d une fiche renommee."""
    ident = str(identite or "").strip().lower()
    a = str(ancien or "").strip()
    n = str(nouveau or "").strip()
    if not ident or not a or not n:
        return {"histo": 0, "objectifs": 0, "fusions": 0}
    paires = [(cle(ident, a), cle(ident, n), n, ident)]
    with _LOCK:
        h, hf = _deplacer(HISTO_FILE, paires, True)
        o, of = _deplacer(OBJECTIFS_FILE, paires, False)
    return {"histo": h, "objectifs": o, "fusions": hf + of}


def renommer_identite(ancienne: str, nouvelle: str) -> dict:
    """Idem, mais pour TOUTES les fiches d une identite qui change de nom.

    Renommer une modele passait la hache sur le passe de tous ses VAs d un
    seul coup — le plus gros degat possible sur ce fichier.
    """
    a = str(ancienne or "").strip().lower()
    n = str(nouvelle or "").strip().lower()
    if not a or not n or a == n:
        return {"histo": 0, "objectifs": 0, "fusions": 0}
    total = {"histo": 0, "objectifs": 0, "fusions": 0}
    with _LOCK:
        for chemin, histo, champ in ((HISTO_FILE, True, "histo"),
                                     (OBJECTIFS_FILE, False, "objectifs")):
            d = _load(chemin)
            paires = []
            for k in list(d):
                ks = str(k)
                if ks.startswith(a + "|"):
                    paires.append((ks, n + "|" + ks[len(a) + 1:], "", n))
            bouge, fus = _deplacer(chemin, paires, histo)
            total[champ] = bouge
            total["fusions"] += fus
    return total


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
        suite.append(etat_du_jour(dans[k]) if k in dans else "inconnu")
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


def reglage_paie(identite: str, va: str) -> tuple:
    """(tarif d'une journee, nombre de comptes a servir) pour cette fiche.

    Les deux valeurs sont reglables FICHE PAR FICHE et changent quand on veut.
    Sans reglage, les defauts du module s'appliquent : 5 $ et vingt comptes.
    Un VA paye plus cher, ou charge de dix comptes seulement, se decrit ici
    et nulle part ailleurs.
    """
    rec = _load(OBJECTIFS_FILE).get(cle(identite, va))
    jour_, base_ = PAIE_JOUR, BASE_COMPTES
    if isinstance(rec, dict):
        try:
            v = float(rec.get("paie_jour") or 0)
            if v > 0:
                jour_ = v
        except Exception:
            pass
        try:
            n = int(rec.get("base_comptes") or 0)
            if n > 0:
                base_ = n
        except Exception:
            pass
    return jour_, base_


def fixer_paie(identite: str, va: str, paie_jour=None, base_comptes=None) -> tuple:
    """Regle le tarif et/ou le nombre de comptes. Rend le couple retenu.

    Vide ou zero REMET AU DEFAUT plutot que de poser zero : un tarif nul
    paierait tout le monde a rien, et un nombre de comptes nul ferait une
    division par zero — deux facons silencieuses de casser la paie.
    """
    k = cle(identite, va)
    with _LOCK:
        d = _load(OBJECTIFS_FILE)
        rec = d.get(k) if isinstance(d.get(k), dict) else {}

        if paie_jour is not None:
            try:
                v = float(str(paie_jour).replace(",", ".").strip() or 0)
            except Exception:
                v = 0.0
            # Plafond de bon sens : au-dela c'est une faute de frappe.
            v = max(0.0, min(v, 1000.0))
            if v > 0:
                rec["paie_jour"] = round(v, 2)
            else:
                rec.pop("paie_jour", None)

        if base_comptes is not None:
            try:
                n = int(str(base_comptes).strip() or 0)
            except Exception:
                n = 0
            n = max(0, min(n, 999))
            if n > 0:
                rec["base_comptes"] = n
            else:
                rec.pop("base_comptes", None)

        if rec:
            rec["modifie"] = int(time.time())
            d[k] = rec
        else:
            d.pop(k, None)
        _save(OBJECTIFS_FILE, d)
    return reglage_paie(identite, va)


def paie_quinzaine(identite: str, va: str, jour: str = "") -> dict:
    """Ce que la fiche a MERITE depuis le debut de la quinzaine.

    La regle, telle que le proprietaire l'a posee : la journee vaut 5 $, et
    elle n'est acquise qu'a hauteur des comptes qui ont publie ce jour-la,
    sur vingt. Un seul compte qui publie, c'est 25 centimes ; cinq comptes,
    un quart de la journee, soit 1,25 $. Quinze journees font les 75 $ de la
    quinzaine — tous les mois sont comptes a trente jours, le calendrier reel
    ne change ni la journee ni le total.

    LE PLAFOND A CENT POUR CENT EST VOLONTAIRE. Une fiche qui porte trente
    comptes peut en faire publier vingt-cinq dans la journee ; sans plafond,
    elle gagnerait 125 % d'une journee et la quinzaine depasserait les 75 $
    annonces. On ne paie pas plus que ce qui est promis.

    LES JOURNEES SANS RELEVE NE RAPPORTENT RIEN MAIS SONT COMPTEES A PART.
    Un report qui n'a pas tourne — redemarrage, panne — laisse un trou. Le
    faire passer pour une journee a zero ferait payer au VA une coupure dont
    il n'est pas responsable ; c'est deja la regle de `bilan_quinzaine`, et
    elle vaut a plus forte raison quand il y a de l'argent au bout. Le trou
    est donc rendu dans `jours_non_mesures`, et `projete` dit ce que le meme
    rythme donnerait sur la quinzaine entiere.
    """
    jour = jour or aujourdhui()
    debut, fin = quinzaine(jour)
    d0 = _dt.date.fromisoformat(debut)
    d1 = _dt.date.fromisoformat(fin)
    n_jours = (d1 - d0).days + 1
    par_jour, base_comptes = reglage_paie(identite, va)

    rec = _load(HISTO_FILE).get(cle(identite, va)) or {}
    jours = rec.get("jours") if isinstance(rec.get("jours"), dict) else {}

    lignes, gagne, mesures = [], 0.0, 0
    d = d0
    stop = min(d1, _dt.date.fromisoformat(jour))
    while d <= stop:
        k = d.isoformat()
        v = jours.get(k)
        if isinstance(v, dict):
            publie = int(v.get("publie") or 0)
            part = min(1.0, publie / base_comptes) if base_comptes else 0.0
            montant = part * par_jour
            gagne += montant
            mesures += 1
            lignes.append({"jour": k, "publie": publie, "part": round(part, 4),
                           "montant": round(montant, 2), "mesure": True})
        else:
            lignes.append({"jour": k, "publie": None, "part": None,
                           "montant": 0.0, "mesure": False})
        d += _dt.timedelta(days=1)

    ecoules = len(lignes)
    # Le 31 d'un mois existe au calendrier mais pas dans le modele de paie :
    # quinze journees a 5 $ font les 75 $ promis, et on ne verse pas plus que
    # ce qui est annonce.
    plafond = round(par_jour * JOURS_QUINZAINE, 2)
    gagne = min(gagne, plafond)
    return {
        "debut": debut, "fin": fin,
        "base": plafond, "sur_comptes": base_comptes,
        "jours_payes": JOURS_QUINZAINE,
        "jours_quinzaine": n_jours, "par_jour": round(par_jour, 4),
        "jours_ecoules": ecoules, "jours_mesures": mesures,
        "jours_non_mesures": ecoules - mesures,
        "gagne": round(gagne, 2),
        "projete": round(min(plafond, gagne / mesures * JOURS_QUINZAINE), 2)
                   if mesures else 0.0,
        "pct": round(100.0 * gagne / plafond, 1) if plafond else 0.0,
        "lignes": lignes,
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
            suite.append(etat_du_jour(v))
            cible[1] += 1
            # Le SCORE reste binaire : une journee est tenue ou elle ne l'est
            # pas. L'orange nuance ce qu'on VOIT, pas ce qu'on compte — sinon
            # « 12/14 j » ne voudrait plus rien dire de precis au moment de
            # payer.
            cible[0] += 1 if v.get("atteint") else 0
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


#: Le seuil intermediaire. Au-dessus, la journee n'est pas tenue mais elle
#: n'est pas ratee non plus — c'est le meme decoupage que la pastille de
#: quinzaine (80 % / 50 %), pour qu'un carre et une pastille ne racontent pas
#: deux histoires differentes sur le meme ecran.
SEUIL_MOYEN = 0.50


def etat_du_jour(v) -> str:
    """'tenu' / 'moyen' / 'rate' pour UNE journee enregistree.

    Trois niveaux, pas deux : une bande tout en rouge ne distingue pas le VA
    qui a fait vingt-trois comptes sur trente de celui qui en a fait quatre.
    Au moment de payer, ce n'est pas la meme conversation.

    On se rabat sur `atteint` quand la journee a ete enregistree avant que ces
    chiffres soient gardes — mieux vaut deux niveaux qu'une exception.
    """
    if not isinstance(v, dict):
        return "inconnu"
    # `atteint` FAIT FOI. Il a ete calcule le jour meme, avec l'objectif du
    # jour meme, et c'est lui qui compte dans le score. Recalculer un ratio
    # par-dessus, c'est risquer que la bande dise vert la ou le score dit non
    # tenu — ou l'inverse. On l'a vu tout de suite : `enregistrer_jour` ecrit
    # « actifs: 0 » par defaut, donc toutes les vieilles journees tenues
    # viraient au rouge.
    if v.get("atteint"):
        return "tenu"
    # Le ratio ne sert qu'a DEPARTAGER les journees non tenues : celle a
    # vingt-trois comptes sur trente n'est pas celle a quatre, et au moment de
    # payer ce n'est pas la meme conversation.
    try:
        objectif = int(v.get("objectif") or 0)
        actifs = int(v.get("actifs") or 0)
    except Exception:
        return "rate"
    if objectif <= 0:
        return "rate"
    return "moyen" if (actifs / objectif) >= SEUIL_MOYEN else "rate"


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
