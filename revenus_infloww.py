"""Ventes OnlyFans lues chez Infloww, pour les créatrices que MyPuls ne voit pas.

Depuis le 11/10/2026 vers 20 h 15 (Paris), aucune clé MyPuls ne voit plus
Jessye (3107) ni Khloé (3108) : « Creator not in your scope ». Le dashboard les
retirait de TOUTES les périodes, sans un mot — 19 049,84 $ nets manquaient à
septembre, 9 463,71 $ à octobre au 26 (audit du 26/10/2026). Infloww les a,
vente par vente, et concordait au centime avec MyPuls sur les seize jours où
les deux les voyaient.

Règles, chacune pour une raison :
- une créatrice ne vient JAMAIS des deux sources : visible chez MyPuls, elle
  reste à MyPuls (Emy) — et MyPuls reprend la main tout seul le jour où il
  revoit Jessye ou Khloé ;
- le rattachement se fait par pseudo OnlyFans (revenus_segments.COMPTES_OF),
  le seul identifiant que les deux sources partagent ;
- jours de Paris, comme MyPuls : la page /infloww découpe en UTC, et ses
  chiffres du jour ne se comparent pas à ceux du dashboard (25/10 : Emy
  526,36 $ en UTC, 595,84 $ à Paris) ;
- `undo` et `pending_return` sont exclus (infloww.STATUTS_EXCLUS) ;
- net = net d'Infloww, en USD ; les types passent par mypuls.famille_api, la
  même table que MyPuls — deux tables de classement, deux comportements.

Lecture seule : ce module n'écrit que le cache d'infloww.py.
"""
import datetime as dt
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import infloww
from revenus_segments import ATTENDUES_INFLOWW, COMPTES_OF, creator_segment

PARIS = ZoneInfo("Europe/Paris")
CHEMIN = "/v1/transactions"


def _norm(s: Any) -> str:
    """« Khloe 💕 » -> « khloe », « Khloé » -> « khloe » : pour comparer des
    noms, jamais pour classer de l'argent (ça, ce sont les ids)."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _id_mypuls(pseudo_of: str) -> Optional[int]:
    p = str(pseudo_of or "").strip().lower()
    for cid, (_nom, ps) in COMPTES_OF.items():
        if ps == p:
            return cid
    return None


def jour_paris(ms: Any) -> str:
    try:
        v = int(float(ms or 0))
    except (TypeError, ValueError):
        return ""
    if not v:
        return ""
    return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).astimezone(PARIS).date().isoformat()


def _demi_mois(debut: dt.date, fin: dt.date) -> Iterable[Tuple[dt.date, dt.date]]:
    """Tranches calées sur le calendrier (1-15, 16-fin de mois).

    Calées pour être PARTAGÉES : « Aujourd'hui », « Cette semaine » et « Ce
    mois » relisent les mêmes tranches en cache au lieu d'une fenêtre chacune.
    Un demi-mois et pas un mois : à Paris, octobre dure 31 jours ET une heure
    (passage à l'heure d'hiver), juste au-dessus des 31 jours qu'Infloww
    accepte par requête.
    """
    d = dt.date(debut.year, debut.month, 1 if debut.day <= 15 else 16)
    while d <= fin:
        if d.day == 1:
            f = d.replace(day=15)
        else:
            f = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        yield d, f
        d = f + dt.timedelta(days=1)


def _ms_paris(jour: dt.date) -> dt.datetime:
    return dt.datetime.combine(jour, dt.time(0, 0), PARIS).astimezone(dt.timezone.utc)


def _tranche(creator_id: str, a: dt.date, b: dt.date) -> Dict[str, Any]:
    """Les ventes de [a 00:00, b 23:59:59.999] heure de Paris, en cache.

    endTime jamais dans le futur (Infloww le refuse) : la tranche en cours
    s'arrête à « maintenant moins une minute », et sa clé de cache ne porte
    pas l'heure — elle se relit au bout de dix minutes, comme les autres
    lectures récentes d'infloww.py.
    """
    debut = _ms_paris(a)
    fin = min(_ms_paris(b + dt.timedelta(days=1)) - dt.timedelta(milliseconds=1),
              infloww._maintenant())
    if fin <= debut:
        return {"l": [], "tronque": False}

    def fab():
        lot, tronque = infloww._pages(CHEMIN, {
            "creatorId": creator_id, "platformCode": infloww.PLATEFORME, "limit": 100,
            "startTime": infloww._ms(debut), "endTime": infloww._ms(fin)})
        return {"l": [infloww._vente(x) for x in lot], "tronque": tronque}
    # dix minutes pour ce qui bouge encore (retenue OnlyFans d'environ 7 jours,
    # remboursements), une heure pour le reste
    duree = infloww._duree_pour(b, recent_jours=8)
    return infloww._avec_cache(f"paris:ventes:{creator_id}:{a}:{b}", fab, duree)[0] or {}


def ventes_paris(creator_id: str, debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """Les ventes d'une créatrice Infloww sur des jours de Paris, résumées.

    Rend, en dollars : net, brut, types {carte: net}, hors {montant, libelles},
    jours {AAAA-MM-JJ: net}, nb, exclues (undo / pending_return), ecartees
    (devise inattendue — comptées, jamais jetées en silence).
    Lève infloww.ErreurInfloww si une tranche ne se lit pas, ou si la
    pagination a été coupée : un total tronqué ne doit pas passer pour complet.
    """
    import mypuls
    taches = [(lambda a=a, b=b: _tranche(creator_id, a, b)) for a, b in _demi_mois(debut, fin)]
    lignes: List[Dict[str, Any]] = []
    for v, err in infloww._parallele(taches):
        if err is not None:
            raise err
        if (v or {}).get("tronque"):
            raise infloww.ErreurInfloww("liste de ventes coupée par le garde-fou de pagination")
        lignes += (v or {}).get("l") or []
    d0, d1 = debut.isoformat(), fin.isoformat()
    net = brut = 0
    types: Dict[str, int] = {}
    jours: Dict[str, int] = {}
    hors = {"montant": 0, "libelles": []}
    vus, nb, exclues, ecartees = set(), 0, 0, 0
    for x in lignes:
        j = jour_paris(x.get("t"))
        if not (d0 <= j <= d1):
            continue
        # une même vente ne compte qu'une fois, même si deux tranches la rendaient
        cle = x.get("id") or x.get("tx")
        if cle:
            if cle in vus:
                continue
            vus.add(cle)
        if x.get("statut") in infloww.STATUTS_EXCLUS:
            exclues += 1
            continue
        if (x.get("devise") or infloww.DEVISE) != infloww.DEVISE:
            ecartees += 1
            continue
        n = int(x.get("net") or 0)
        nb += 1
        net += n
        brut += int(x.get("brut") or 0)
        jours[j] = jours.get(j, 0) + n
        carte = mypuls.famille_api(x.get("type"))
        if carte:
            types[carte] = types.get(carte, 0) + n
        else:
            hors["montant"] += n
            lib = str(x.get("type") or "(type vide)")
            if lib not in hors["libelles"] and len(hors["libelles"]) < 12:
                hors["libelles"].append(lib)
    return {"net": net / 100, "brut": brut / 100,
            "types": {k: v / 100 for k, v in types.items()},
            "hors": {"montant": hors["montant"] / 100, "libelles": hors["libelles"]},
            "jours": {k: v / 100 for k, v in sorted(jours.items())},
            "nb": nb, "exclues": exclues, "ecartees": ecartees}


def _attendue(c: Dict[str, Any]) -> Optional[str]:
    """La clé d'ATTENDUES_INFLOWW qui désigne cette créatrice Infloww, s'il y en a une."""
    noms = [_norm(c.get(k)) for k in ("name", "nickName", "userName")]
    for cle in ATTENDUES_INFLOWW:
        if any(n and (n == cle or n.startswith(cle)) for n in noms):
            return cle
    return None


def complement(vus: Iterable[Any], debut: dt.date, fin: dt.date, segment: str = "all",
               exclure: Iterable[str] = (), of_mypuls: Iterable[Tuple[Any, str]] = (),
               recentes: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """Ce qu'Infloww ajoute à un agrégat MyPuls sur [debut, fin], jours de Paris.

    vus       : ids que MyPuls compte (actifs dans /creators) ;
    exclure   : noms normalisés des modèles écartées (EXCLUDED_MODELS) ;
    of_mypuls : (id, pseudo) des créatrices OnlyFans de MyPuls — garde-fou
                contre une créatrice des deux côtés que la table ne rattache
                pas encore ;
    recentes  : {id: nom} des créatrices relevées avec du chiffre ces 45
                derniers jours : si l'une disparaît partout, le total est
                PARTIEL et il faut le dire.

    Rend {creatrices: [{nom, id_mypuls, pseudo_of, segment, net, brut, types,
    hors, jours, nb}], erreurs: [texte] (lecture ratée : passager),
    manquantes: [{nom, segment, raison}] (absence durable), a_classer: [nom]
    (marché inconnu, comptée en OF FR), a_rattacher: [nom]}.
    """
    vus = {int(v) for v in vus if str(v).lstrip("-").isdigit()}
    excl = {e for e in exclure if e}
    out: Dict[str, Any] = {"creatrices": [], "erreurs": [], "manquantes": [],
                           "a_classer": [], "a_rattacher": []}
    connectees: Optional[List[Dict[str, Any]]] = None
    panne = ""
    if not infloww.configure():
        panne = "clé Infloww absente"
    else:
        try:
            connectees = infloww.creatrices()
        except infloww.ErreurInfloww as e:
            panne = f"Infloww injoignable ({str(e)[:60]})"
    pseudos = {str(c.get("userName") or "").strip().lower() for c in connectees or []}
    noms_mp = [(_norm(p), cid) for cid, p in of_mypuls if _norm(p)]
    couvertes = set()          # ids MyPuls que l'une ou l'autre source compte
    for c in connectees or []:
        pseudo = str(c.get("userName") or "").strip().lower()
        cid = _id_mypuls(pseudo)
        if cid is not None and cid in vus:
            continue                       # MyPuls la voit : elle reste à MyPuls
        nom = COMPTES_OF[cid][0] if cid is not None else str(
            c.get("name") or c.get("nickName") or pseudo).strip()
        if cid is None:
            # Une créatrice que la table ne connaît pas, mais dont MyPuls a un
            # compte OnlyFans du même nom : la compter ici la doublerait.
            n = _norm(c.get("name") or c.get("nickName"))
            if n and any(m == n or m.startswith(n) or n.startswith(m) for m, _ in noms_mp):
                out["a_rattacher"].append(nom)
                continue
        if excl and any(_norm(x).startswith(e) for e in excl for x in (nom, pseudo)):
            continue
        if cid is not None:
            seg = creator_segment(cid, "onlyfans")
            couvertes.add(cid)
        else:
            seg = ATTENDUES_INFLOWW.get(_attendue(c) or "") or None
            if seg is None:
                seg = "of_fr"
                out["a_classer"].append(nom)
        if segment != "all" and seg != segment:
            continue
        try:
            v = ventes_paris(str(c.get("id")), debut, fin)
        except infloww.ErreurInfloww as e:
            out["erreurs"].append(f"{nom} (Infloww): {str(e)[:60]}")
            continue
        out["creatrices"].append(dict(v, nom=nom, id_mypuls=cid, pseudo_of=pseudo, segment=seg))

    def manque(nom, seg, raison, passagere=False):
        if segment != "all" and seg != segment:
            return
        if passagere:
            out["erreurs"].append(f"{nom}: {raison}")
        else:
            out["manquantes"].append({"nom": nom, "segment": seg, "raison": raison})

    attendues_ids = dict(recentes or {})
    for cid, (nom, _ps) in COMPTES_OF.items():
        attendues_ids.setdefault(cid, nom)
    for cid, nom in sorted(attendues_ids.items()):
        if cid in vus or cid in couvertes:
            continue
        if any(_norm(nom).startswith(e) for e in excl):
            continue
        seg = creator_segment(cid, "onlyfans" if cid in COMPTES_OF else "")
        ps = COMPTES_OF.get(cid, ("", ""))[1]
        if ps and ps in pseudos:
            continue                       # lue chez Infloww, hors du segment demandé
        if panne and ps:
            manque(nom, seg, panne, passagere=True)
        else:
            manque(nom, seg, "plus vue par MyPuls" + (", ni par Infloww" if ps else ""))
    for cle, seg_a in ATTENDUES_INFLOWW.items():
        if any(_attendue(c) == cle for c in connectees or []):
            continue
        if any(m == cle or m.startswith(cle) for m, _ in noms_mp):
            continue                       # arrivée chez MyPuls : comptée là-bas
        nom = cle.capitalize()
        if panne:
            manque(nom, seg_a or "of_fr", panne, passagere=True)
        else:
            manque(nom, seg_a or "of_fr", "pas encore visible par la clé Infloww du site")
    return out
