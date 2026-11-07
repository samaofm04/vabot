"""journal_primes.py — 📈・évolution-des-primes, sur TRUST Agency (staff).

Propriétaire, 07/11/2026 : « un salon qui dit : sama a join, ramené par …,
et après ça dit recruteur +0,2, +0,5, +10, peu importe, message par
message ». Un message par événement, au moment où il est relevé :

- arrivée parrainée : « @X a rejoint TRUST INSTAGRAM, ramené par @Y », sur
  le serveur de recrutement (TRUST Agency) et sur les trois TRUST ;
- recrutement : « @Y +0,20 $ » quand une personne qu'il a invitée sur TRUST
  Agency se vérifie — une seule fois par personne, même si le parrain
  travaille sur les trois serveurs (il n'y a qu'un serveur de recrutement,
  et une seule déclaration par invité) ;
- paliers : « @Y +0,50 $ » quand un filleul atteint 10 subs, « +10 $ » à
  200, plateforme par plateforme (10 subs sur les trois = 3 × 0,50 $).

Rien n'est calculé ici : on lit les registres que tiennent déjà les relevés
de chaque serveur, sans rien y écrire (comme habillage_trust) —
entretien_parrainage (TRUST Agency), agency_accueil (TRUST INSTAGRAM),
twitter_accueil (TRUST TWITTER), threads_accueil (TRUST THREADS) — et les
subs comme les espaces d'affiliation (affiliation_privee.compteurs,
affiliation_sources.subs). Jamais lien_pour() : il créerait une invitation.

Ce qui était déjà là à la mise en route n'est PAS posté : au premier relevé
réussi de chaque source, ses événements sont notés comme référence. Pour les
paliers, un filleul dont les subs se lisent pour la première fois prend sa
valeur du moment comme référence — sauf s'il est arrivé après la mise en
route (il est parti de 0 sous nos yeux). L'état (data/journal_primes.json,
safe_json) garde chaque événement posté : un redémarrage ne reposte rien.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import safe_json

GID = "1552152470464110703"                      # TRUST Agency (recrutement)
NOM_SALON = "📈・évolution-des-primes"
#: 🔒 ꜱᴛᴀꜰꜰ : le salon prend les droits de la catégorie (BOSS et managers,
#: aucun VA), managers en lecture seule comme 🚪・arrivées-sur-le-serveur — un
#: journal où personne n'écrit. Pas ceux de 💰・bilan-invitations : ils
#: nomment un manager, pas le rôle, et un manager nommé demain n'y aurait
#: rien vu.
CATEGORIE = "1552167027504971826"
MANAGER = "1552167022324879422"                  # 🛡️ Manager
VOIR, ECRIRE, LIENS, HISTORIQUE = 1024, 2048, 16384, 65536
SUJET = ("Chaque arrivée parrainée, chaque recrutement vérifié (+0,20 $) et chaque palier "
         "de filleul (+0,50 $ à 10 subs, +10 $ à 200, par plateforme), au moment où il arrive.")

DATA_DIR = Path(__file__).resolve().parent / "data"
FICHIER = DATA_DIR / "journal_primes.json"
PERIODE_S = 120
#: au plus autant de messages par tour ; le reste part au tour suivant
MAX_PAR_TOUR = 10
#: plus d'événements neufs d'un coup : c'est un registre refait ou abîmé, pas
#: une soirée chargée (quelques arrivées par jour). Notés sans message, et dit.
SEUIL_MASSE = 40
#: une arrivée relevée longtemps après (parrain confirmé à la main) dit sa date
ARRIVEE_TARDIVE_S = 6 * 3600

#: plateforme → (serveur, nom affiché)
SERVEURS = {
    "entretien": ("1552152470464110703", "TRUST Agency"),
    "agency": ("1488331963575177247", "TRUST INSTAGRAM"),
    "twitter": ("1445108485090971710", "TRUST TWITTER"),
    "threads": ("1498948161039896586", "TRUST THREADS"),
}
#: les paliers de parrainage, en centimes (agency_accueil.panneau, twitter_accueil.panneau)
PALIERS = ((10, 50), (200, 1000))
PRIX_RECRUTEMENT = 20

TZ = ZoneInfo("Europe/Paris")
#: le salon n'est revérifié (un GET) qu'une fois tous les quarts d'heure
SALON_VU_S = 900

LOCK = threading.RLock()
_TOUR = threading.Lock()
_DEMARRE = False
_DIT: Dict[str, str] = {}
_SALON_VU: Dict[str, float] = {}


def _dire(cle: str, texte: str) -> None:
    """Une panne qui dure ne s'imprime qu'une fois ; texte vide = rétabli."""
    if _DIT.get(cle, "") != texte:
        _DIT[cle] = texte
        if texte:
            print(f"[journal-primes] {texte}", flush=True)


def _api(methode: str, chemin: str, **kw):
    import verif_discord as vd
    return vd.api(methode, chemin, gid=GID, **kw)


def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(FICHIER, default={}) or {}
    except Exception:                                        # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write(FICHIER, d)


def montant(centimes: int) -> str:
    """+0,20 $, +0,50 $, +10 $."""
    c = int(centimes)
    return f"+{c // 100} $" if c % 100 == 0 else f"+{c // 100},{c % 100:02d} $"


def _ts(iso: Any) -> Optional[float]:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


# ─── les sources (lecture seule) ─────────────────────────────────────────────
def registre(plateforme: str) -> Optional[Dict[str, Any]]:
    """L'état du relevé de `plateforme`, ou None (module absent, illisible)."""
    try:
        if plateforme == "entretien":
            import entretien_parrainage as m
            with m.LOCK:
                return m.lire()
        if plateforme == "agency":
            import agency_accueil as m
            return m.registre()
        if plateforme == "twitter":
            import twitter_accueil as m
            return m.lire()
        if plateforme == "threads":
            import threads_accueil as m
            return m.lire()
    except Exception as e:                                   # noqa: BLE001
        _dire(f"src:{plateforme}", f"registre {plateforme} illisible : {type(e).__name__}: {e}")
        return None
    return None


def evenements_registre(plateforme: str, d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Les arrivées parrainées (et, pour TRUST Agency, les recrutements
    vérifiés) d'un registre. Clés stables : une par personne et par serveur."""
    out: List[Dict[str, Any]] = []
    if plateforme == "entretien":
        vus = set()
        for a in (d.get("arrivees") or {}).values():
            a = a or {}
            uid, p = str(a.get("uid") or ""), str(a.get("parrain") or "")
            if uid and p and p != uid and uid not in vus:
                vus.add(uid)
                out.append({"cle": f"arr:entretien:{uid}", "type": "arrivee", "plateforme": plateforme,
                            "filleul": uid, "parrain": p, "quand": _ts(a.get("joined_at"))})
        for uid, r in (d.get("declarations") or {}).items():
            r = r or {}
            p = str(r.get("parrain") or "")
            if p:
                out.append({"cle": f"rec:{uid}", "type": "recrutement", "plateforme": plateforme,
                            "filleul": str(uid), "parrain": p,
                            "centimes": int(r.get("centimes") or PRIX_RECRUTEMENT),
                            "quand": _ts(r.get("date"))})
        return out
    for uid, f in (d.get("filleuls") or {}).items():
        f = f or {}
        p = str(f.get("parrain") or "")
        if p and p != str(uid):
            quand = _ts(f.get("joined_at")) or (float(f["date"]) if isinstance(f.get("date"), (int, float)) else None)
            out.append({"cle": f"arr:{plateforme}:{uid}", "type": "arrivee", "plateforme": plateforme,
                        "filleul": str(uid), "parrain": p, "quand": quand})
    return out


def compteurs() -> Optional[Dict[str, Any]]:
    """Les vrais subs de chaque tracking (un appel MyPuls, gardé 10 min par
    affiliation_privee) ; None si MyPuls ne rend pas tout."""
    try:
        import affiliation_privee
        return affiliation_privee.compteurs()
    except Exception as e:                                   # noqa: BLE001
        _dire("subs", f"subs illisibles : {type(e).__name__}: {e}")
        return None


def subs(plateforme: str, uid: str, metrics: Optional[Dict[str, Any]]) -> Optional[int]:
    """Les vrais subs cumulés du filleul `uid` sur `plateforme`, à la règle
    de son espace d'affiliation ; None = inconnu (aucun palier décidé)."""
    if metrics is None:
        return None
    try:
        import affiliation_sources
        import liens_va
        return affiliation_sources.subs(plateforme, liens_va.lien_de(SERVEURS[plateforme][0], uid) or {}, metrics)
    except Exception as e:                                   # noqa: BLE001
        _dire(f"subs:{plateforme}", f"subs {plateforme} illisibles : {type(e).__name__}: {e}")
        return None


# ─── le salon ────────────────────────────────────────────────────────────────
def droits_salon(categorie: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Les droits de la catégorie, managers en lecture seule, et le bot qui
    poste (son rôle n'y a que la vue)."""
    import verif_discord as vd
    bot = str(vd.bot_du_serveur(GID).get("app_id") or "")
    out = []
    for o in categorie.get("permission_overwrites") or []:
        o = {k: str(o[k]) if k != "type" else o[k] for k in ("id", "type", "allow", "deny")}
        if o["id"] == MANAGER:
            o.update(allow=str(VOIR | HISTORIQUE), deny=str(ECRIRE))
        if o["id"] != bot:
            out.append(o)
    if bot:
        out.append({"id": bot, "type": 1, "allow": str(VOIR | ECRIRE | LIENS | HISTORIQUE), "deny": "0"})
    return out


def assurer_salon() -> str:
    """L'identifiant du salon, créé au premier tour dans 🔒 STAFF
    (droits_salon). Retrouvé par son nom si l'état est perdu :
    jamais deux salons. "" si Discord refuse (le tour suivant réessaie)."""
    with LOCK:
        salon = str(_etat().get("salon") or "")
    if salon and time.time() - _SALON_VU.get(salon, 0) < SALON_VU_S:
        return salon
    if salon:
        code, _ = _api("GET", f"/channels/{salon}")
        if code == 200:
            _SALON_VU[salon] = time.time()
            return salon
        if code != 404:
            _dire("salon", f"salon illisible (HTTP {code})")
            return ""
    code, salons = _api("GET", f"/guilds/{GID}/channels")
    if code != 200 or not isinstance(salons, list):
        _dire("salon", f"salons de TRUST Agency illisibles (HTTP {code})")
        return ""
    trouve = next((str(c["id"]) for c in salons if isinstance(c, dict) and c.get("type") == 0
                   and c.get("name") == NOM_SALON), "")
    if not trouve:
        cat = next((c for c in salons if isinstance(c, dict) and str(c.get("id")) == CATEGORIE), None)
        if not cat:
            _dire("salon", "catégorie 🔒 STAFF introuvable : droits du salon inconnus, rien créé")
            return ""
        code, rep = _api("POST", f"/guilds/{GID}/channels",
                         json={"name": NOM_SALON, "type": 0, "parent_id": CATEGORIE, "topic": SUJET,
                               "permission_overwrites": droits_salon(cat)})
        if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
            _dire("salon", f"création du salon refusée (HTTP {code})")
            return ""
        trouve = str(rep["id"])
        print(f"[journal-primes] salon {NOM_SALON} créé ({trouve})", flush=True)
    with LOCK:
        d = _etat()
        d["salon"] = trouve
        _ecrire(d)
    _dire("salon", "")
    _SALON_VU[trouve] = time.time()
    return trouve


# ─── les messages ────────────────────────────────────────────────────────────
def pseudo(uid: str, noms: Dict[str, str]) -> str:
    """Le pseudo Discord de `uid` (gardé dans l'état) : une mention d'un
    membre absent de TRUST Agency ne s'affiche pas toujours."""
    if uid in noms:
        return noms[uid]
    code, u = _api("GET", f"/users/{uid}")
    if code == 200 and isinstance(u, dict):
        noms[uid] = str(u.get("username") or u.get("global_name") or "")
    elif code == 404:
        noms[uid] = ""
    return noms.get(uid, "")


def _qui(uid: str, noms: Dict[str, str]) -> str:
    p = noms.get(uid) or ""
    # backticks : un pseudo à tiret bas ne passe pas en italique
    return f"<@{uid}>" + (f" `{p}`" if p else "")


def texte(e: Dict[str, Any], noms: Dict[str, str], maintenant: Optional[float] = None) -> str:
    serveur = SERVEURS[e["plateforme"]][1]
    f, p = _qui(e["filleul"], noms), _qui(e["parrain"], noms)
    if e["type"] == "arrivee":
        t = f"🚪 {f} a rejoint **{serveur}**, ramené par {p}"
        q = e.get("quand")
        if q and (maintenant or time.time()) - q > ARRIVEE_TARDIVE_S:
            t += " · arrivé le " + dt.datetime.fromtimestamp(q, TZ).strftime("%d/%m")
        return t
    if e["type"] == "recrutement":
        return f"🎙️ {p} **{montant(e['centimes'])}** · {f} s'est vérifié sur **TRUST Agency** (recrutement)"
    icone = "🏆" if e["seuil"] >= 200 else "🎯"
    return f"{icone} {p} **{montant(e['centimes'])}** · {f} a atteint **{e['seuil']} subs** sur **{serveur}**"


def _poster(salon: str, e: Dict[str, Any], contenu: str) -> str:
    nonce = hashlib.sha256(f"journal-primes:{e['cle']}".encode()).hexdigest()[:24]
    code, rep = _api("POST", f"/channels/{salon}/messages",
                     json={"content": contenu, "allowed_mentions": {"parse": []},
                           "nonce": nonce, "enforce_nonce": True})
    return str(rep.get("id") or "") if code in (200, 201) and isinstance(rep, dict) else ""


# ─── un tour ─────────────────────────────────────────────────────────────────
def tour() -> Dict[str, Any]:
    """Un relevé : les événements neufs postés, un message chacun. Rend le bilan."""
    if not _TOUR.acquire(blocking=False):
        return {"occupe": True}
    try:
        return _tour()
    finally:
        _TOUR.release()


def _tour() -> Dict[str, Any]:
    bilan: Dict[str, Any] = {"postes": 0, "references": 0, "en_attente": 0}
    salon = assurer_salon()
    if not salon:
        return bilan
    registres = {p: registre(p) for p in SERVEURS}
    metrics = compteurs()
    maintenant = time.time()
    with LOCK:
        d = _etat()
        debut = float(d.setdefault("debut", maintenant))
        vus = d.setdefault("vus", {})
        sources = d.setdefault("sources", {})
        suivis = d.setdefault("subs", {})
        neufs: List[Dict[str, Any]] = []
        inconnus = 0

        def noter(e: Dict[str, Any]) -> None:
            if e["cle"] not in vus:
                vus[e["cle"]] = {"ref": 1, "t": int(maintenant)}
                bilan["references"] += 1

        for plateforme, reg in registres.items():
            if reg is None:
                continue
            _dire(f"src:{plateforme}", "")
            evts = evenements_registre(plateforme, reg)
            if plateforme not in sources:
                # premier relevé réussi de cette source : ce qui y est déjà
                # n'est pas reposté
                sources[plateforme] = int(maintenant)
                for e in evts:
                    noter(e)
                continue
            neufs += [e for e in evts if e["cle"] not in vus]
            if plateforme == "entretien" or metrics is None:
                continue
            for e in evts:
                n = subs(plateforme, e["filleul"], metrics)
                if n is None:
                    inconnus += 1
                    continue
                cle_s = f"{plateforme}:{e['filleul']}"
                paliers = [{"cle": f"pal:{cle_s}:{s}", "type": "palier", "plateforme": plateforme,
                            "filleul": e["filleul"], "parrain": e["parrain"], "seuil": s,
                            "centimes": c, "quand": maintenant} for s, c in PALIERS if n >= s]
                premier = cle_s not in suivis
                suivis[cle_s] = n
                if premier and not (e.get("quand") and e["quand"] >= debut):
                    # ses subs se lisent pour la première fois, et il était
                    # là avant nous : sa valeur du moment est la référence
                    for pal in paliers:
                        noter(pal)
                    continue
                neufs += [pal for pal in paliers if pal["cle"] not in vus]
        if len(neufs) > SEUIL_MASSE:
            for e in neufs:
                noter(e)
            print(f"[journal-primes] {len(neufs)} événements neufs d'un coup : registre refait ? "
                  "Notés sans message.", flush=True)
            neufs = []
        noms = d.setdefault("noms", {})
        _ecrire(d)
    if metrics is None:
        _dire("subs", "subs MyPuls indisponibles : paliers non relevés ce tour")
    else:
        _dire("subs", "")
        # même règle que les espaces d'affiliation : une somme partielle ne
        # valide aucun palier. Le 07/11, les trackings Emy et Seren (retirées
        # de MyPuls le 03/11) rendaient ainsi inconnus la plupart des
        # filleuls Twitter et Threads — dit, pas tu.
        _dire("inconnus", f"{inconnus} filleul(s) aux subs inconnus (pas de tracking, ou un tracking "
                          "absent de MyPuls) : leurs paliers ne sont pas relevés" if inconnus else "")
    bilan["subs_inconnus"] = inconnus
    if bilan["references"]:
        print(f"[journal-primes] {bilan['references']} événement(s) déjà passé(s) noté(s) "
              "comme référence, sans message", flush=True)
    # les messages hors du verrou, dans l'ordre où les choses sont arrivées ;
    # à heure égale, l'arrivée avant le recrutement avant les paliers
    rang = {"arrivee": 0, "recrutement": 1, "palier": 2}
    neufs.sort(key=lambda e: (e.get("quand") or maintenant, rang[e["type"]], e.get("seuil", 0)))
    bilan["en_attente"] = max(0, len(neufs) - MAX_PAR_TOUR)
    for e in neufs[:MAX_PAR_TOUR]:
        for uid in (e["filleul"], e["parrain"]):
            pseudo(uid, noms)
        mid = _poster(salon, e, texte(e, noms, maintenant))
        if not mid:
            _dire("poste", f"message refusé par Discord ({e['cle']}) : le tour suivant reprend")
            break
        _dire("poste", "")
        with LOCK:
            d = _etat()
            d.setdefault("vus", {})[e["cle"]] = {"m": mid, "t": int(time.time())}
            d.setdefault("noms", {}).update(noms)
            _ecrire(d)
        bilan["postes"] += 1
    if bilan["postes"]:
        print(f"[journal-primes] {bilan['postes']} message(s) posté(s)"
              + (f", {bilan['en_attente']} au tour suivant" if bilan["en_attente"] else ""), flush=True)
    return bilan


def demarrer() -> bool:
    """Le relevé, toutes les deux minutes, dans son fil (web_upload.create_app,
    sur la machine de production seulement). Une fois par processus."""
    global _DEMARRE
    with LOCK:
        if _DEMARRE:
            return False
        _DEMARRE = True

    def boucle():
        time.sleep(30)                   # laisser les relevés des serveurs repartir
        while True:
            try:
                import verif_discord as vd
                with vd.sur_serveur(GID):
                    tour()
            except Exception as e:                           # noqa: BLE001
                print(f"[journal-primes] relevé : {type(e).__name__}: {e}", flush=True)
            time.sleep(PERIODE_S)

    threading.Thread(target=boucle, daemon=True, name="journal-primes").start()
    return True
