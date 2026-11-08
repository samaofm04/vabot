"""journal_primes.py — 🤝・qui-t-a-invité, sur TRUST Agency (recrutement).

Propriétaire, 07/11/2026 : « un salon qui dit : sama a join, ramené par …,
et après ça dit recruteur +0,2, +0,5, +10, peu importe, message par
message », puis, devant le salon « qui-t-a-invité » d'un autre serveur :
« comme ça je veux, tu vois qui t'a invité et ça dit ». Visible de tout le
serveur, en lecture seule. Un message par événement, au moment où il est
relevé :

- arrivée parrainée : « 🚪 X a rejoint TRUST INSTAGRAM, invité par Y », sur
  le serveur de recrutement (TRUST Agency) et sur les trois TRUST ;
- recrutement : « X a été invité par Y — +0,20 $ pour lui 💸 » quand une
  personne invitée sur TRUST Agency se vérifie. Une seule fois par
  personne : il n'y a qu'un serveur de recrutement, une déclaration par invité ;
- parrainage : « +0,50 $ » quand un filleul atteint 10 subs, « +10 $ » à 200.
  UNE prime par filleul, comptée sur la plateforme où il a le plus de subs
  (propriétaire, 07/11 : « pas pour les 3 […] ça fait trop », « tu prends
  juste là où le mec il a le plus de sub »).

Sous chaque gain, « Total pour cette semaine » du parrain : ses recrutements
de la semaine (même semaine que le bilan d'entretien_parrainage, close le
dimanche à 23 h 59, Paris) et les paliers que ce salon a annoncés.

Rien n'est calculé ailleurs : on lit les registres que tiennent déjà les
relevés de chaque serveur, sans rien y écrire (comme habillage_trust) —
entretien_parrainage (TRUST Agency), agency_accueil (TRUST INSTAGRAM),
twitter_accueil (TRUST TWITTER), threads_accueil (TRUST THREADS) — et les
subs de MyPuls comme les espaces d'affiliation (affiliation_privee.compteurs),
sur les seuls trackings de Lia (voir subs). Jamais lien_pour() : il
créerait une invitation.

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
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import safe_json

GID = "1552152470464110703"                      # TRUST Agency (recrutement)
NOM_SALON = "🤝・qui-t-a-invité"
#: ses anciens noms : un salon qui les porte est repris et renommé, jamais
#: doublé (le 07/11 au soir, « 📈・évolution-des-primes », staff seulement —
#: le propriétaire n'y comprenait rien : « ça doit bien être argent gagné »)
ANCIENS_NOMS = ("📈・évolution-des-primes",)
CATEGORIE = "1560099759824441424"                # 🤝 AFFILIATION
#: 🤝・parrainage, dans la même catégorie : le salon reprend ses droits —
#: tout le monde lit, personne n'écrit (sauf le bot)
SALON_MODELE = "1552159107207790602"
VOIR, ECRIRE, LIENS, HISTORIQUE = 1024, 2048, 16384, 65536
SUJET = "Qui t'a invité, et ce que ça lui rapporte."

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

#: plateforme → (serveur, nom affiché). L'ordre départage deux plateformes à
#: égalité de subs.
SERVEURS = {
    "entretien": ("1552152470464110703", "TRUST Agency"),
    "agency": ("1488331963575177247", "TRUST INSTAGRAM"),
    "twitter": ("1445108485090971710", "TRUST TWITTER"),
    "threads": ("1498948161039896586", "TRUST THREADS"),
}
#: les paliers de parrainage, en centimes (agency_accueil.panneau, twitter_accueil.panneau)
PALIERS = ((10, 50), (200, 1000))
PRIX_RECRUTEMENT = 20
#: les paliers ne comptent que les subs de cette model (« que pour lia »),
#: nommée comme dans la table des comptes OnlyFans (liens_va.nom_de_page)
MODELE_PRIMES = "Lia"

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


def dollars(centimes: int) -> str:
    """0,20 $, 0,50 $, 10 $."""
    c = int(centimes)
    return f"{c // 100} $" if c % 100 == 0 else f"{c // 100},{c % 100:02d} $"


def montant(centimes: int) -> str:
    """+0,20 $, +0,50 $, +10 $."""
    return "+" + dollars(centimes)


def _ts(iso: Any) -> Optional[float]:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def semaine(t: float) -> str:
    """Le lundi (ISO) de la semaine de `t` : la règle du bilan des
    invitations (entretien_parrainage.semaine, VPS), close le dimanche à
    23 h 59, heure de Paris. La sienne quand elle est là."""
    try:
        import entretien_parrainage as e
        return e.semaine(dt.datetime.fromtimestamp(t, e.TZ))
    except ImportError:
        pass
    d = (dt.datetime.fromtimestamp(t, TZ) + dt.timedelta(minutes=1)).date()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


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
                quand = _ts(r.get("date"))
                out.append({"cle": f"rec:{uid}", "type": "recrutement", "plateforme": plateforme,
                            "filleul": str(uid), "parrain": p,
                            "centimes": int(r.get("centimes") or PRIX_RECRUTEMENT), "quand": quand,
                            "semaine": str(r.get("semaine") or (semaine(quand) if quand else ""))})
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
    """Les vrais subs du filleul `uid` sur `plateforme`, sur les seuls
    trackings de Lia (MODELE_PRIMES) ; None = inconnu (aucun palier décidé).

    Propriétaire, 08/11/2026, à propos des filleuls aux subs inconnus :
    « que pour lia ». La règle des espaces d'affiliation
    (affiliation_sources.subs, VPS) additionne TOUS les trackings du filleul,
    Emy et Seren compris ; ces deux-là ne sont plus dans MyPuls depuis le
    03/11, et les 15 filleuls parrainés restaient inconnus, aucun palier ne
    partait. Un tracking de Lia absent de MyPuls rend toujours inconnu : une
    somme partielle ne valide aucun palier."""
    if metrics is None:
        return None
    try:
        import liens_va
        fiche = liens_va.lien_de(SERVEURS[plateforme][0], uid) or {}
        urls = {str(u).strip().rstrip("/").lower() for u in liens_va.trackings_de_fiche(fiche)
                if liens_va.nom_de_page(u) == MODELE_PRIMES}
    except Exception as e:                                   # noqa: BLE001
        _dire(f"subs:{plateforme}", f"subs {plateforme} illisibles : {type(e).__name__}: {e}")
        return None
    if not urls:
        return None
    ns = [metrics.get(u) for u in urls]
    return None if any(not isinstance(n, int) for n in ns) else sum(ns)


def meilleure_plateforme(arrivees: List[Dict[str, Any]],
                         metrics: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Parmi les plateformes où ce filleul a un parrain (ses arrivées), celle
    où il a le plus de subs : {plateforme, subs, parrain}. C'est là, et là
    seulement, que comptent ses paliers. Une plateforme aux subs inconnus ne
    concourt pas ; toutes inconnues : None."""
    connus = []
    for e in arrivees:
        n = subs(e["plateforme"], e["filleul"], metrics)
        if n is not None:
            connus.append((n, -list(SERVEURS).index(e["plateforme"]), e))
    if not connus:
        return None
    n, _, e = max(connus, key=lambda x: (x[0], x[1]))
    return {"plateforme": e["plateforme"], "subs": n, "parrain": e["parrain"]}


# ─── le salon ────────────────────────────────────────────────────────────────
def _permissions_du_bot(bot: str) -> Optional[int]:
    """Les droits du bot sur le serveur (ses rôles), None si illisibles."""
    code, roles = _api("GET", f"/guilds/{GID}/roles")
    code_m, membre = _api("GET", f"/guilds/{GID}/members/{bot}")
    if code != 200 or code_m != 200 or not isinstance(roles, list) or not isinstance(membre, dict):
        return None
    siens = set(map(str, membre.get("roles") or [])) | {GID}
    p = 0
    for r in roles:
        if isinstance(r, dict) and str(r.get("id")) in siens:
            p |= int(r.get("permissions") or 0)
    return p


def droits_salon(modele: Dict[str, Any], actuel: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Les droits de 🤝・parrainage (tout le monde lit, personne n'écrit), et
    le bot qui poste ; `actuel` : le salon à remettre aux droits.

    Discord refuse (403) à un bot de régler un droit qu'il n'a pas lui-même :
    le 08/11, 🤝・parrainage refusait aussi les fils de discussion à
    @everyone, Siri ne les a pas, et le salon restait sous son ancien nom.
    Ces droits-là ne sont ni recopiés ni retirés : ceux que le salon porte
    déjà restent tels quels — et c'est dit. Aucun rôle ne donne les fils sur
    TRUST Agency : rien ne change pour les membres."""
    import verif_discord as vd
    bot = str(vd.bot_du_serveur(GID).get("app_id") or "")
    siens = _permissions_du_bot(bot) if bot else None
    masque = siens if siens is not None and not siens & 8 else ~0    # 8 : administrateur
    deja = {str(o.get("id")): (int(o.get("allow") or 0), int(o.get("deny") or 0))
            for o in (actuel or {}).get("permission_overwrites") or []}
    voulu = {str(o["id"]): (o.get("type", 0), int(o.get("allow") or 0), int(o.get("deny") or 0))
             for o in modele.get("permission_overwrites") or [] if str(o.get("id")) != bot}
    if bot:
        voulu[bot] = (1, VOIR | ECRIRE | LIENS | HISTORIQUE, 0)
    types = {str(o.get("id")): o.get("type", 0) for o in (actuel or {}).get("permission_overwrites") or []}
    out, laisses = [], 0
    for oid in list(voulu) + [i for i in deja if i not in voulu]:
        typ, allow, deny = voulu.get(oid, (types.get(oid, 0), 0, 0))
        a0, d0 = deja.get(oid, (0, 0))
        laisses |= (allow | deny) & ~masque
        allow, deny = (allow & masque) | (a0 & ~masque), (deny & masque) | (d0 & ~masque)
        if allow or deny or oid in voulu:
            out.append({"id": oid, "type": typ, "allow": str(allow), "deny": str(deny)})
    if laisses:
        _dire("droits", f"droits de 🤝・parrainage que le bot n'a pas, non recopiés : {laisses}")
    return out


def _droits(c: Dict[str, Any]) -> set:
    return {(str(o.get("id")), int(o.get("type") or 0), str(o.get("allow")), str(o.get("deny")))
            for o in c.get("permission_overwrites") or []}


def assurer_salon() -> str:
    """L'identifiant du salon : créé au premier tour dans 🤝 AFFILIATION, ou
    repris (même sous un ancien nom) et remis au nom, à la place et aux
    droits attendus. Jamais deux salons. "" si Discord refuse (le tour
    suivant réessaie)."""
    with LOCK:
        salon = str(_etat().get("salon") or "")
    if salon and time.time() - _SALON_VU.get(salon, 0) < SALON_VU_S:
        return salon
    code, salons = _api("GET", f"/guilds/{GID}/channels")
    if code != 200 or not isinstance(salons, list):
        _dire("salon", f"salons de TRUST Agency illisibles (HTTP {code})")
        return salon                  # un salon connu reçoit quand même
    par_id = {str(c.get("id")): c for c in salons if isinstance(c, dict)}
    c = par_id.get(salon) or next((x for x in salons if isinstance(x, dict) and x.get("type") == 0
                                   and x.get("name") in (NOM_SALON,) + ANCIENS_NOMS), None)
    modele = par_id.get(SALON_MODELE)
    if not modele:
        _dire("salon", "🤝・parrainage introuvable : droits du salon inconnus, rien créé ni changé")
        return str(c["id"]) if c else ""
    attendu = {"name": NOM_SALON, "parent_id": CATEGORIE, "topic": SUJET,
               "permission_overwrites": droits_salon(modele, c)}
    if c is None:
        code, rep = _api("POST", f"/guilds/{GID}/channels", json=dict(attendu, type=0))
        if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
            _dire("salon", f"création du salon refusée (HTTP {code})")
            return ""
        c = rep
        print(f"[journal-primes] salon {NOM_SALON} créé ({c['id']})", flush=True)
    elif (c.get("name") != NOM_SALON or str(c.get("parent_id")) != CATEGORIE
          or (c.get("topic") or "") != SUJET or _droits(c) != _droits(attendu)):
        code, _rep = _api("PATCH", f"/channels/{c['id']}", json=attendu)
        if code != 200:
            # le renommage est limité (2 par 10 min) : on poste quand même
            _dire("salon", f"salon {c['id']} non remis à jour (HTTP {code}) : réessai dans 15 min")
            _SALON_VU[str(c["id"])] = time.time()
            return str(c["id"])
        print(f"[journal-primes] salon {c['id']} remis à jour : {NOM_SALON}, 🤝 AFFILIATION, "
              "lu de tous", flush=True)
    sid = str(c["id"])
    if sid != salon:
        with LOCK:
            d = _etat()
            d["salon"] = sid
            _ecrire(d)
    _dire("salon", "")
    _SALON_VU[sid] = time.time()
    return sid


# ─── les messages ────────────────────────────────────────────────────────────
def pseudo(uid: str, noms: Dict[str, str]) -> str:
    """Le nom affiché de `uid` (gardé dans l'état), en gras comme le modèle :
    une mention d'un membre absent de TRUST Agency ne s'affiche pas."""
    if uid in noms:
        return noms[uid]
    code, u = _api("GET", f"/users/{uid}")
    if code == 200 and isinstance(u, dict):
        noms[uid] = str(u.get("global_name") or u.get("username") or "")
    elif code == 404:
        noms[uid] = ""
    return noms.get(uid, "")


_RE_MARKDOWN = re.compile(r"([\\*_~|`>\[\]])")


def _qui(uid: str, noms: Dict[str, str]) -> str:
    # un nom à étoiles ou à tirets bas casserait le gras
    n = _RE_MARKDOWN.sub(r"\\\1", (noms.get(uid) or "").strip())
    return f"**{n}**" if n else f"<@{uid}>"


def texte(e: Dict[str, Any], noms: Dict[str, str], total: int = 0,
          maintenant: Optional[float] = None) -> str:
    serveur = SERVEURS[e["plateforme"]][1]
    f, p = _qui(e["filleul"], noms), _qui(e["parrain"], noms)
    if e["type"] == "arrivee":
        t = f"🚪 {f} a rejoint **{serveur}**, invité par {p}"
        q = e.get("quand")
        if q and (maintenant or time.time()) - q > ARRIVEE_TARDIVE_S:
            t += " · arrivé le " + dt.datetime.fromtimestamp(q, TZ).strftime("%d/%m")
        return t
    if e["type"] == "recrutement":
        t = f"{f} a été invité par {p} — {montant(e['centimes'])} pour lui 💸"
    else:
        t = (f"{f}, invité par {p}, a atteint **{e['seuil']} subs** sur **{serveur}** — "
             f"{montant(e['centimes'])} pour lui 💸")
    return t + f"\nTotal pour cette semaine : **{dollars(total)}**"


def total_semaine(parrain: str, sem: str, entretien: Optional[Dict[str, Any]],
                  gains: Dict[str, Any]) -> int:
    """Ce que `parrain` a gagné la semaine `sem`, en centimes : ses
    recrutements vérifiés (les déclarations du bilan) et les paliers annoncés
    ici."""
    rec = sum(int((r or {}).get("centimes") or 0) for r in ((entretien or {}).get("declarations") or {}).values()
              if str((r or {}).get("parrain") or "") == parrain and (r or {}).get("semaine") == sem)
    return rec + sum(int(g.get("centimes") or 0) for g in gains.values()
                     if g.get("parrain") == parrain and g.get("semaine") == sem)


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
        par_filleul: Dict[str, List[Dict[str, Any]]] = {}
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
            if plateforme != "entretien":
                for e in evts:
                    par_filleul.setdefault(e["filleul"], []).append(e)
        if metrics is not None:
            for uid, arrivees in par_filleul.items():
                m = meilleure_plateforme(arrivees, metrics)
                if m is None:
                    inconnus += 1
                    continue
                paliers = [{"cle": f"pal:{uid}:{s}", "type": "palier", "plateforme": m["plateforme"],
                            "filleul": uid, "parrain": m["parrain"], "seuil": s, "centimes": c,
                            "quand": maintenant, "semaine": semaine(maintenant)}
                           for s, c in PALIERS if m["subs"] >= s]
                premier = uid not in suivis
                suivis[uid] = m["subs"]
                arrive = min((e["quand"] for e in arrivees if e.get("quand")), default=None)
                if premier and not (arrive and arrive >= debut):
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
        gains = dict(d.get("gains") or {})
        _ecrire(d)
    if metrics is None:
        _dire("subs", "subs MyPuls indisponibles : paliers non relevés ce tour")
    else:
        _dire("subs", "")
        # une somme partielle ne valide aucun palier : un filleul sans
        # tracking de Lia lisible reste inconnu — dit, pas tu (le 07/11, les
        # trackings Emy et Seren rendaient ainsi inconnus les 15 filleuls)
        _dire("inconnus", f"{inconnus} filleul(s) aux subs inconnus sur toutes leurs plateformes "
                          "(pas de tracking, ou un tracking absent de MyPuls) : leurs paliers ne sont "
                          "pas relevés" if inconnus else "")
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
        total = 0
        if e["type"] != "arrivee":
            total = total_semaine(e["parrain"], e["semaine"], registres.get("entretien"), gains)
            if e["type"] == "palier":
                total += e["centimes"]          # pas encore dans les gains
        mid = _poster(salon, e, texte(e, noms, total, maintenant))
        if not mid:
            _dire("poste", f"message refusé par Discord ({e['cle']}) : le tour suivant reprend")
            break
        _dire("poste", "")
        with LOCK:
            d = _etat()
            d.setdefault("vus", {})[e["cle"]] = {"m": mid, "t": int(time.time())}
            d.setdefault("noms", {}).update(noms)
            if e["type"] == "palier":
                g = {"parrain": e["parrain"], "filleul": e["filleul"], "centimes": e["centimes"],
                     "semaine": e["semaine"], "plateforme": e["plateforme"], "t": int(time.time())}
                d.setdefault("gains", {})[e["cle"]] = g
                gains[e["cle"]] = g
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
