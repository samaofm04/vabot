"""« 📈 Mes subs » : les abonnés d'un VA, aujourd'hui, sur la période, sur la
période d'avant — additionnés.

Propriétaire, 15/10/2026 : « un truc pour le VA, il check son nombre de subs
sur la période ou celle précédente », « pour Twitter, pour IG et pour
Threads ; pour IG faut add MYM et OF ; pour Threads les deux models Emy et
Seren », puis « je veux que le VA reçoive direct le truc additionné ».

Les trackings d'un VA viennent des fiches du site, là où ils ont été créés :
  - Twitter et Threads : liens_va — le tracking Emy du lien et celui de sa
    variante (Seren) ;
  - Va IG : liens_fr — pour chaque model, le tracking OF et le tracking MYM.

Les ABONNÉS, pas les visites (MyPuls donne les deux ; le VA 60 avait 2
visites et 0 sub). OnlyFans : l'API (subscribers_period, par période). MYM :
l'API ne les rend pas (403 sur les créatrices MYM) ; la page « Tracking
Analytics » de MyPuls les donne jour par jour (conversions), relevée chaque
heure sous le verrou de bascule (releve_mym), gardée dans data/.

Une partie illisible n'est jamais un zéro : la période entière est dite
« pas lisible » plutôt qu'un total qui en oublierait une moitié.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
MYM_FICHIER = DATA_DIR / "mym_conversions.json"

TWITTER_ID = "1445108485090971710"
THREADS_ID = "1498948161039896586"
VA_IG_ID = "1505418484052394004"
SERVEURS = {TWITTER_ID, THREADS_ID, VA_IG_ID}

#: Un relevé MYM plus vieux que ça ne dit plus « aujourd'hui » : illisible.
MYM_FRAIS_S = 6 * 3600
#: Le relevé MYM : au plus une fois par heure.
MYM_TOUTES_S = 3600


def disponible(gid: Any) -> bool:
    return str(gid or "") in SERVEURS


def periodes(jour: Optional[dt.date] = None) -> List[Tuple[str, dt.date, dt.date]]:
    """[(clé, début, fin)] : aujourd'hui, la quinzaine en cours jusqu'à
    aujourd'hui, la quinzaine d'avant — le calendrier du classement."""
    import podium_discord as pod
    j = jour or pod._aujourdhui()
    deb, _fin = pod.saison_en_cours(j)
    p_deb, p_fin = pod.saison_en_cours(deb - dt.timedelta(days=1))
    return [("aujourdhui", j, j), ("periode", deb, j), ("precedente", p_deb, p_fin)]


# ─── les trackings d'un VA ───────────────────────────────────────────────
def trackings_du_va(gid: Any, uid: Any) -> List[Tuple[str, str]]:
    """[(plateforme « of » | « mym », adresse)] des trackings de ce VA sur ce
    serveur, sans doublon."""
    gid, uid = str(gid or ""), str(uid or "")
    out: List[Tuple[str, str]] = []
    if gid in (TWITTER_ID, THREADS_ID):
        import liens_va
        f = liens_va.lien_de(gid, uid)
        for url in (f.get("tracking"), (f.get("variante") or {}).get("tracking")):
            if url:
                out.append(("of", str(url)))
    elif gid == VA_IG_ID:
        import liens_fr
        for cle, f in sorted((liens_fr._etat().get("liens") or {}).items()):
            if not cle.startswith(uid + ":") or not isinstance(f, dict):
                continue
            for plat, url in sorted((f.get("trackings") or {}).items()):
                if url:
                    out.append(("mym" if "mym" in str(plat).lower() else "of", str(url)))
    vus, uniques = set(), []
    for x in out:
        if x[1] not in vus:
            vus.add(x[1])
            uniques.append(x)
    return uniques


def pseudo_du_va(gid: Any, uid: Any) -> str:
    """Le pseudo du VA tel que ses fiches le donnent (« adh040 »)."""
    gid, uid = str(gid or ""), str(uid or "")
    if gid in (TWITTER_ID, THREADS_ID):
        import liens_va
        return str(liens_va.lien_de(gid, uid).get("pseudo") or "")
    if gid == VA_IG_ID:
        import liens_fr
        for cle, f in (liens_fr._etat().get("liens") or {}).items():
            if cle.startswith(uid + ":") and isinstance(f, dict) and f.get("pseudo"):
                return str(f["pseudo"])
    return ""


def _norme(x: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(x or "").lower())


def _a_lui(nom: str, pseudo: str) -> bool:
    """Ce tracking est-il au VA ? Son nom MyPuls porte son pseudo
    (« Lola_VA_2_adh040 », « Twitter VA 31 @abdoul_9684 »). Propriétaire,
    15/10/2026, devant 45 subs en septembre pour adh040 : « avant j'avais
    pas de tracking link, c'est juste un truc en général ; faut juste prendre
    le tracking link actuel » -- son bouton MYM était resté sur le tracking
    COMMUN « VA_MARKETING » (création MYM refusée, HTTP 500), aux subs de
    tout le monde depuis juin ; puis « UNIQUEMENT son tracking avec son nom ».
    Sans nom, pas à lui."""
    if not pseudo:
        return True
    return bool(nom) and _norme(pseudo) in _norme(nom)


# ─── OnlyFans : l'API ────────────────────────────────────────────────────
def _subs_of(urls: List[str], d0: str, d1: str) -> Optional[int]:
    """Abonnés OF de ces trackings sur [d0, d1] (API MyPuls), None si MyPuls
    n'a pas répondu. Un tracking tout neuf que l'API ne rend pas encore : 0."""
    if not urls:
        return 0
    import podium_discord as pod
    vus, _raison = pod._lire_mypuls(d0, d1)
    if vus is None:
        return None
    n = 0
    for u in urls:
        v = vus.get(pod.tracking_de(u))
        if v is None:
            continue
        if v.get("subs") is None:
            return None
        n += int(v["subs"])
    return n


# ─── MYM : la page de MyPuls, relevée chaque heure ───────────────────────
def _lire_cache() -> Dict[str, Any]:
    try:
        d = safe_json.load(MYM_FICHIER, default={}) or {}
    except Exception:                                        # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def _subs_mym(urls: List[str], d0: str, d1: str) -> Optional[int]:
    """Conversions MYM de ces trackings sur [d0, d1], d'après le dernier
    relevé ; None si le relevé manque, est trop vieux, ou ne connaît pas un
    de ces trackings (le relevé suivant le rattrapera)."""
    if not urls:
        return 0
    d = _lire_cache()
    if time.time() - float(d.get("releve") or 0) > MYM_FRAIS_S:
        return None
    jours = d.get("trackings") or {}
    n = 0
    for u in urls:
        t = jours.get(u.rstrip("/"))
        if t is None:
            return None
        n += sum(int(v or 0) for j, v in (t.get("jours") or {}).items() if d0 <= j <= d1)
    return n


def _lignes_page(html: str) -> Dict[str, str]:
    """{linkId : adresse} des lignes du tableau « Tracking Analytics »
    (<tr id="row-link-8924"> … data-url="https://mym.fans/app/t/…")."""
    out: Dict[str, str] = {}
    for m in re.finditer(r'<tr id="row-link-(\d+)"(.*?)</tr>', html or "", re.S):
        u = re.search(r'data-url="(https?://[^"]+)"', m.group(2))
        if u:
            out[m.group(1)] = u.group(1).rstrip("/")
    return out


def releve_mym(createurs: Optional[List[int]] = None) -> Dict[str, Any]:
    """Relève, pour chaque créatrice MYM des liens Va IG, les conversions jour
    par jour de chacun de ses trackings, et les garde (MYM_FICHIER).
    Rend {ok, trackings, rates}.

    Sous mypuls._OF_SWITCH_LOCK : MyPuls ne retient qu'UNE créatrice par
    session, et une création de tracking ou un relevé de pushs pris entre
    notre bascule et notre lecture se ferait chez la mauvaise. La créatrice
    servie est vérifiée : les lignes et les chiffres doivent parler des mêmes
    trackings (mêmes linkId), sinon rien n'est gardé pour elle."""
    import mypuls
    if createurs is None:
        import liens_fr
        createurs = sorted({int(m["mym"]) for m in liens_fr.MODELS.values() if m.get("mym")})
    bilan: Dict[str, Any] = {"ok": False, "trackings": 0, "rates": []}
    s = mypuls._make_session()
    if s is None:
        bilan["rates"].append("session MyPuls indisponible (cookies)")
        return bilan
    neuf: Dict[str, Any] = {}
    with mypuls._OF_SWITCH_LOCK:
        for cid in createurs:
            try:
                s.get(f"{mypuls.BASE_URL}/switch-creator/{int(cid)}?from=app_pushs",
                      timeout=mypuls.TIMEOUT, allow_redirects=True)
                page = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
                r = s.get(f"{mypuls.BASE_URL}/tracking-stats/data", timeout=mypuls.TIMEOUT)
                donnees = r.json()
            except Exception as e:                           # noqa: BLE001
                bilan["rates"].append(f"{cid} : {type(e).__name__}: {str(e)[:80]}")
                continue
            lignes = _lignes_page(page.text)
            dates = list(donnees.get("labels") or []) if isinstance(donnees, dict) else []
            series = (donnees.get("daily") or {}) if isinstance(donnees, dict) else {}
            series = series.values() if isinstance(series, dict) else series
            pris = 0
            for sr in series or []:
                if not isinstance(sr, dict):
                    continue
                url = lignes.get(str(sr.get("linkId") or ""))
                if not url:
                    continue
                jours = {}
                for j, v in zip(dates, sr.get("data") or []):
                    c = (v or {}).get("conversions") if isinstance(v, dict) else None
                    if c:
                        jours[str(j)[:10]] = int(c)
                neuf[url] = {"createur": int(cid), "nom": str(sr.get("label") or ""), "jours": jours}
                pris += 1
            if lignes and not pris:
                bilan["rates"].append(f"{cid} : lignes et chiffres ne concordent pas (bascule ?)")
        try:
            mypuls._save_rotated_cookies(s)
        except Exception:                                    # noqa: BLE001
            pass
    if not neuf:
        return bilan
    # ce qui n'a pas été relu cette fois (créatrice en échec) garde l'ancien
    # relevé, plutôt que de disparaître
    ancien = (_lire_cache().get("trackings") or {})
    for u, v in ancien.items():
        neuf.setdefault(u, v)
    safe_json.write(MYM_FICHIER, {"releve": time.time(), "trackings": neuf})
    bilan.update(ok=True, trackings=len(neuf))
    return bilan


_DERNIER_RELEVE = {"t": 0.0}


def releve_mym_si_du() -> Optional[Dict[str, Any]]:
    """Le relevé MYM au plus une fois par heure (boucle du bot)."""
    if time.time() - _DERNIER_RELEVE["t"] < MYM_TOUTES_S:
        return None
    _DERNIER_RELEVE["t"] = time.time()
    return releve_mym()


# ─── le message ──────────────────────────────────────────────────────────
def subs_du_va(gid: Any, uid: Any, jour: Optional[dt.date] = None) -> Dict[str, Any]:
    """{trackings, aujourdhui|periode|precedente : {du, au, n}} — n additionne
    OF et MYM, Emy et Seren ; None si une partie est illisible."""
    ts = trackings_du_va(gid, uid)
    communs = _communs(ts, pseudo_du_va(gid, uid), jour)
    of = [u for p, u in ts if p == "of" and u not in communs]
    mym = [u for p, u in ts if p == "mym" and u not in communs]
    out: Dict[str, Any] = {"trackings": len(ts), "communs": sorted(communs)}
    for cle, a, b in periodes(jour):
        d0, d1 = a.isoformat(), b.isoformat()
        n_of = _subs_of(of, d0, d1)
        n_mym = _subs_mym(mym, d0, d1)
        n = None if n_of is None or n_mym is None else n_of + n_mym
        out[cle] = {"du": d0, "au": d1, "n": n}
    return out


def _communs(ts: List[Tuple[str, str]], pseudo: str, jour: Optional[dt.date] = None) -> set:
    """Les trackings de ce VA qui ne sont PAS à lui : MyPuls les connaît, et
    leur nom ne porte pas son pseudo (voir _a_lui). MyPuls muet ou relevé MYM
    absent : rien n'est écarté, la lecture dira « pas lisible »."""
    if not pseudo or not ts:
        return set()
    noms: Dict[str, str] = {}
    if any(p == "of" for p, _u in ts):
        import podium_discord as pod
        j = (jour or pod._aujourdhui()).isoformat()
        vus, _raison = pod._lire_mypuls(j, j)
        for p, u in ts:
            if p == "of" and vus and pod.tracking_de(u) in vus:
                noms[u] = str(vus[pod.tracking_de(u)].get("nom") or "")
    if any(p == "mym" for p, _u in ts):
        cache = _lire_cache().get("trackings") or {}
        for p, u in ts:
            if p == "mym" and u.rstrip("/") in cache:
                noms[u] = str(cache[u.rstrip("/")].get("nom") or "")
    return {u for u, nom in noms.items() if not _a_lui(nom, pseudo)}


def texte(gid: Any, uid: Any, jour: Optional[dt.date] = None) -> str:
    """Le message privé de « 📈 Mes subs » : trois chiffres, additionnés,
    jamais un montant."""
    if not disponible(gid):
        return "⚠️ Les subs ne sont pas comptés sur ce serveur."
    r = subs_du_va(gid, uid, jour)
    if not r["trackings"]:
        return ("📈 **Tes subs**\nTu n'as pas encore de tracking : tes subs apparaîtront ici "
                "dès que ton lien sera prêt.")

    def ligne(titre, p, dates=True):
        val = f"**{p['n']}**" if p["n"] is not None else "pas lisible pour l'instant"
        if not dates:
            return f"{titre} : {val}"
        du, au = p["du"], p["au"]
        return f"{titre} (du {du[8:10]}/{du[5:7]} au {au[8:10]}/{au[5:7]}) : {val}"
    return "\n".join([
        "📈 **Tes subs**",
        ligne("Aujourd'hui", r["aujourdhui"], dates=False),
        ligne("Cette période", r["periode"]),
        ligne("Période précédente", r["precedente"]),
        "-# MyPuls se met à jour toutes les quelques heures."
        + (" Un tracking commun à plusieurs VA n'est pas compté." if r.get("communs") else ""),
    ])
