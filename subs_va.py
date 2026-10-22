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
# Agency VA INSTAGRAM (22/10/2026) : ses VA ont leur fiche liens_va, comme
# Twitter et Threads (un tracking Emy chacun, lien direct)
AGENCY_IG_ID = "1488331963575177247"
SERVEURS = {TWITTER_ID, THREADS_ID, VA_IG_ID, AGENCY_IG_ID}

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
    if gid in (TWITTER_ID, THREADS_ID, AGENCY_IG_ID):
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
    if gid in (TWITTER_ID, THREADS_ID, AGENCY_IG_ID):
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
    import podium_discord as pod
    if pod._profil(gid).get("mes_stats"):
        return _texte_stats(gid, uid, r)
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


def _texte_stats(gid: Any, uid: Any, r: Dict[str, Any]) -> str:
    """« 📈 Mes stats » (Threads, Twitter : clé « mes_stats » du profil du podium) : les
    abonnés, comme « Mes subs », puis les clics de son lien sur les mêmes
    périodes, écrits comme la quinzaine du salon statistiques (« US : n · GBL :
    n », US = les pays du serveur : US + UK + Canada sur Threads, US sur
    Twitter). Jamais un montant."""
    import podium_discord as pod
    cles = ("aujourdhui", "periode", "precedente")
    titres = {"aujourdhui": "Aujourd'hui", "periode": "Cette période",
              "precedente": "Période précédente"}

    def quand(p: Dict[str, Any], cle: str) -> str:
        if cle == "aujourdhui":
            return titres[cle]
        du, au = p["du"], p["au"]
        return f"{titres[cle]} (du {du[8:10]}/{du[5:7]} au {au[8:10]}/{au[5:7]})"
    out = ["📈 **Tes stats**", "**Subs**"]
    if r["trackings"]:
        for cle in cles:
            n = r[cle]["n"]
            out.append(f"{quand(r[cle], cle)} : "
                       + (f"**{n}**" if n is not None else "pas lisible pour l'instant"))
    else:
        out.append("Tu n'as pas encore de tracking : tes subs apparaîtront ici dès que ton "
                   "lien sera prêt.")
    clics = pod.clics_du_va(str(gid), str(uid),
                            [(dt.date.fromisoformat(r[c]["du"]), dt.date.fromisoformat(r[c]["au"]))
                             for c in cles])
    pf = pod._profil(gid)
    noms = {"US": "US", "GB": "UK", "CA": "Canada"}
    pays = " + ".join(noms.get(p, p) for p in (pf.get("pays_subs") or pf.get("pays") or ("US",)))
    out.append(f"**Clics de ton lien** (US = {pays} · GBL = tous pays)"
               if pays != "US" else "**Clics de ton lien** (US · GBL = tous pays)")
    if clics is None:
        out.append("Pas encore de lien : tes clics apparaîtront ici dès qu'il sera créé.")
    else:
        for cle, v in zip(cles, clics):
            out.append(f"{quand(r[cle], cle)} : "
                       + (f"US : **{v[0]}** · GBL : **{v[1]}**" if v is not None
                          else "pas lisible pour l'instant"))
    out.append("-# MyPuls et GetMySocial se mettent à jour toutes les quelques heures."
               + (" Un tracking commun à plusieurs VA n'est pas compté." if r.get("communs") else ""))
    return "\n".join(out)


# ─── Va IG : le classement de la quinzaine aux abonnés ───────────────────
# Propriétaire, 15/10/2026, devant « Instagram VA 11 — 181 subs » (des clics
# FR) quand « Mes subs » disait 2 : le classement de Va IG compte maintenant
# les VRAIS abonnés, comme le bouton — mêmes trackings, même règle (« à son
# nom »). Une entité = un VA dans une model (« Amelia VA 3 »), celle que
# podium_discord._marque affiche « Instagram VA n ».
def entites_va_ig() -> Dict[str, Dict[str, Any]]:
    """{« amelia:3 » : {nom « Amelia VA 3 », model, numero, pseudo, uids,
    trackings [(plateforme, adresse)]}} d'après les fiches liens_fr."""
    import liens_fr
    out: Dict[str, Dict[str, Any]] = {}
    for cle, f in sorted((liens_fr._etat().get("liens") or {}).items()):
        if not isinstance(f, dict) or ":" not in cle:
            continue
        uid, model = cle.split(":", 1)
        n = f.get("numero")
        if model not in liens_fr.MODELS or not str(n or "").isdigit():
            continue
        k = f"{model}:{int(n)}"
        e = out.setdefault(k, {"nom": f'{liens_fr.MODELS[model]["nom"]} VA {int(n)}',
                               "model": model, "numero": int(n),
                               "pseudo": str(f.get("pseudo") or ""), "uids": [], "trackings": []})
        e["uids"].append(uid)
        for plat, url in sorted((f.get("trackings") or {}).items()):
            t = ("mym" if "mym" in str(plat).lower() else "of", str(url or ""))
            if t[1] and t not in e["trackings"]:
                e["trackings"].append(t)
    return out


def _subs_entite(e: Dict[str, Any], d0: str, d1: str) -> Optional[int]:
    communs = _communs(e["trackings"], e["pseudo"])
    of = [u for p, u in e["trackings"] if p == "of" and u not in communs]
    mym = [u for p, u in e["trackings"] if p == "mym" and u not in communs]
    n_of, n_mym = _subs_of(of, d0, d1), _subs_mym(mym, d0, d1)
    return None if n_of is None or n_mym is None else n_of + n_mym


def classement_va_ig(debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """La forme de podium_discord.classement() — {lignes, illisibles, frais,
    …} — en abonnés : « clics » y porte le nombre d'abonnés de la période.
    Un VA illisible (MyPuls muet) est dit, jamais compté zéro."""
    d0, d1 = debut.isoformat(), fin.isoformat()
    ents = entites_va_ig()
    lignes, illisibles = [], []
    for _k, e in sorted(ents.items()):
        n = _subs_entite(e, d0, d1)
        if n is None:
            illisibles.append(e["nom"])
            continue
        lignes.append({"va": e["nom"], "numero": e["numero"], "clics": n,
                       "liens": len(e["trackings"]), "spam": False, "model": e["model"]})
    lignes.sort(key=lambda x: (-x["clics"], x["model"], x["numero"]))
    return {"lignes": lignes, "illisibles": sorted(illisibles), "frais": True,
            "entites": len(ents), "liens": sum(len(e["trackings"]) for e in ents.values()),
            "sans_numero": [], "gabarits": [], "source": "abonnes", "erreur": ""}


def totaux_va_ig() -> Dict[str, int]:
    """{« Amelia VA 3 » : abonnés depuis la création de ses trackings} : OF au
    compteur de MyPuls (subscribers_total), MYM à la somme de tous les jours
    relevés. Un VA illisible est laissé de côté (l'ancien total reste)."""
    out: Dict[str, int] = {}
    for _k, e in sorted(entites_va_ig().items()):
        # sans tracking : 0 ici, comme avant (le classement de Va IG l'affiche)
        total = subs_depuis_toujours(e["trackings"], e["pseudo"]) if e["trackings"] else 0
        if total is not None:
            out[e["nom"]] = total
    return out


def subs_depuis_toujours(trackings: List[Tuple[str, str]], pseudo: str) -> Optional[int]:
    """Les abonnés de ces trackings depuis leur création, ceux à son nom
    seulement : OF au compteur de MyPuls (subscribers_total), MYM à la somme
    de tous les jours relevés. None si une partie est illisible — l'all-time
    de Va IG (totaux_va_ig) et celui de la quinzaine de Threads."""
    if not trackings:
        return None                     # pas de tracking : rien à compter, pas zéro
    import podium_discord as pod
    j = pod._aujourdhui().isoformat()
    vus, _raison = pod._lire_mypuls(j, j)
    cache = _lire_cache()
    mym_ok = time.time() - float(cache.get("releve") or 0) <= MYM_FRAIS_S
    jours = cache.get("trackings") or {}
    communs = _communs(trackings, pseudo)
    total = 0
    for p, u in trackings:
        if u in communs:
            continue
        if p == "of":
            v = (vus or {}).get(pod.tracking_de(u)) if vus is not None else None
            if vus is None or (v is not None and v.get("subs_total") is None):
                return None
            total += int((v or {}).get("subs_total") or 0)
        else:
            t = jours.get(u.rstrip("/"))
            if not mym_ok or t is None:
                return None
            total += sum(int(x or 0) for x in (t.get("jours") or {}).values())
    return total



def pseudos_va_ig(debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """Le classement de la quinzaine avec, pour le STAFF seulement, le numéro
    Instagram et le pseudo de chaque ligne (« 👀 Pseudos »). Les VA, eux, ne
    lisent que « Instagram VA n »."""
    import podium_discord as pod
    cl = classement_va_ig(debut, fin)
    ents = entites_va_ig()
    par_nom = {e["nom"]: (k, e) for k, e in ents.items()}
    table = pod.numeros_instagram({k for k, _e in par_nom.values()})
    out = []
    for x in cl["lignes"]:
        k, e = par_nom.get(x["va"], ("", {}))
        out.append({"instagram": table.get(k), "pseudo": e.get("pseudo", ""), "nom": x["va"],
                    "subs": x["clics"]})
    for nom in cl["illisibles"]:
        k, e = par_nom.get(nom, ("", {}))
        out.append({"instagram": table.get(k), "pseudo": e.get("pseudo", ""), "nom": nom,
                    "subs": None})
    return out


# ─── Agency VA INSTAGRAM : ses classements aux abonnés ───────────────────
# Propriétaire, 22/10/2026 : podium, bonus, quinzaine et primes « comme
# Twitter », AUX SUBS (« Instagram VA 12 — 56 subs · 🌐 56 all-time »), puis
# « mettre les stats de Instagram aussi avec le 0 devant », précisé le
# 23/10 : « je parle de VA de Youl4b » — les VA de Twitter (JESSY LE RETOUR,
# registre des trackings), ceux de « Threads VA 1nn » à Threads. Ils
# rejoignent la QUINZAINE d'Agency en « Instagram VA 012 » (leur numéro du
# registre, un 0 devant, trois chiffres), à leurs abonnés comptés comme la
# quinzaine de Twitter (Emy et Seren de leurs trackings). La semaine et le
# bonus, qui paient, restent aux VA d'Agency (question des primes posée,
# défaut : rien pour eux). Deux chiffres = Agency, un 0 devant = Youl4b.
def libelle_agency(n: Any) -> str:
    return f"Instagram VA {int(n)}"


def libelle_youl4b_agency(n: Any) -> str:
    return f"Instagram VA 0{int(n):02d}"


def entites_agency() -> Dict[str, Dict[str, Any]]:
    """{uid : {nom « Instagram VA 12 », numero, pseudo, uid, trackings}} d'après
    les fiches liens_va d'Agency. Un lien coupé (VA parti) n'y est pas ; un VA
    sans tracking non plus (rien à compter, et pas un zéro inventé)."""
    import liens_va
    out: Dict[str, Dict[str, Any]] = {}
    for cle, f in sorted((liens_va._etat().get("liens") or {}).items()):
        if not cle.startswith(AGENCY_IG_ID + ":") or not isinstance(f, dict):
            continue
        n, t = f.get("numero"), str(f.get("tracking") or "")
        if f.get("actif") is False or not str(n or "").isdigit() or not t:
            continue
        uid = cle.split(":", 1)[1]
        out[uid] = {"nom": libelle_agency(n), "numero": int(n), "uid": uid,
                    "pseudo": str(f.get("pseudo") or ""), "trackings": [("of", t)]}
    return out


def _youl4b_relabel(va: Any) -> str:
    """« VA 12 » (Twitter) → « Instagram VA 012 » ; « » si ce n'est pas un VA
    numéroté."""
    m = re.fullmatch(r"VA (\d+)", str(va or "").strip())
    return libelle_youl4b_agency(m.group(1)) if m else ""


def classement_agency(debut: dt.date, fin: dt.date, avec_youl4b: bool = False) -> Dict[str, Any]:
    """La forme de podium_discord.classement(), en abonnés (« clics » porte les
    abonnés de la période) : les VA d'Agency, et avec `avec_youl4b` ceux de
    Youl4b (Twitter, partis exclus) en « Instagram VA 0nn », marqués
    « youl4b ». Un VA illisible est dit, jamais compté zéro."""
    d0, d1 = debut.isoformat(), fin.isoformat()
    ents = entites_agency()
    lignes: List[Dict[str, Any]] = []
    illisibles: List[str] = []
    for _uid, e in sorted(ents.items(), key=lambda kv: kv[1]["numero"]):
        n = _subs_entite(e, d0, d1)
        if n is None:
            illisibles.append(e["nom"])
            continue
        lignes.append({"va": e["nom"], "numero": e["numero"], "clics": n,
                       "liens": len(e["trackings"]), "spam": False, "model": ""})
    nb_y, frais, erreur = 0, True, ""
    if avec_youl4b:
        import podium_discord as pod
        tw = pod.classement(debut, fin, gid=pod.TWITTER_ID, mesure="tracking_abonnes",
                            etiquette=pod.ETIQUETTE_QUINZAINE)
        frais, erreur = bool(tw.get("frais")), str(tw.get("erreur") or "")
        for x in tw["lignes"]:
            lib = _youl4b_relabel(x["va"])
            if lib:
                nb_y += 1
                lignes.append({"va": lib, "numero": int(x["numero"]), "clics": int(x["clics"]),
                               "liens": int(x.get("liens") or 0), "spam": False, "model": "",
                               "youl4b": True})
        illisibles += [lib for lib in map(_youl4b_relabel, tw.get("illisibles") or []) if lib]
    lignes.sort(key=lambda x: (-x["clics"], x["va"]))
    return {"lignes": lignes, "illisibles": sorted(illisibles), "frais": frais,
            "entites": len(ents) + nb_y, "liens": len(ents), "sans_numero": [],
            "gabarits": [], "source": "agency_abonnes", "erreur": erreur}


def totaux_agency() -> Dict[str, int]:
    """{« Instagram VA 12 » : abonnés depuis la création de son tracking}, VA
    d'Agency seuls. Ceux de Youl4b n'ont pas de 🌐 all-time, comme à Twitter
    (alltime_subs faux) : leurs abonnés d'avant le passage sur Emy manquent,
    un total « depuis toujours » serait faux. Un illisible est laissé de côté
    (l'ancien total reste, podium_discord.alltime)."""
    out: Dict[str, int] = {}
    for _uid, e in sorted(entites_agency().items()):
        total = subs_depuis_toujours(e["trackings"], e["pseudo"])
        if total is not None:
            out[e["nom"]] = total
    return out


def noms_agency() -> Dict[str, str]:
    """« 👀 Pseudos » d'Agency : {libellé : qui}. « Instagram VA 12 » → son
    pseudo ; « Instagram VA 012 » → « Nom (VA 12 · Twitter) »."""
    import podium_discord as pod
    out = {e["nom"]: e["pseudo"] or "?" for e in entites_agency().values()}
    for n, nom in pod._noms_registre().items():
        out[libelle_youl4b_agency(n)] = f"{nom or '?'} (VA {n} · Twitter)"
    return out
