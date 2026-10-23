"""agency_accueil.py — Agency VA INSTAGRAM : arrivées, départs, panneau « Se vérifier ».

Propriétaire, 23/10/2026 : « branche les arrivées et la vérification ». Comme
twitter_accueil (fichier du VPS, hors git), sans le parrainage : la liste des
membres est relue à chaque tour des tickets (tickets_discord.suivre_partout,
une dizaine de minutes) ; un membre neuf est annoncé dans
🚪・arrivées-sur-le-serveur, un membre parti dans 👋・départs-et-sanctions.
Au premier passage, les membres déjà là sont notés SANS annonce : 160
« nouvelle arrivée » d'un coup n'apprendraient rien à personne.

Le panneau « Se vérifier » de 🔐・vérification est posé par Wario (le clic va
à l'application qui a posté le message) : verif_discord.assurer_message_verif,
qui ne fait rien quand il est déjà là.

Une liste des membres illisible (403, panne) : rien n'est annoncé ni oublié,
c'est dit, le tour suivant réessaie.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Optional

import safe_json

GID = "1488331963575177247"                      # Agency VA INSTAGRAM
SALON_ARRIVEES = "1562974536662523954"           # 🚪・arrivées-sur-le-serveur
SALON_DEPARTS = "1562974549157351474"            # 👋・départs-et-sanctions
SALON_VERIF = "1562974555423776848"              # 🔐・vérification
SALON_VERIFIES = "1562974542953975978"           # ✅・membres-vérifiés
DATA_DIR = Path(__file__).resolve().parent / "data"
FICHIER = DATA_DIR / "agency_accueil.json"
#: au plus autant d'annonces par tour : un afflux (ou une liste à moitié
#: lue) ne doit pas noyer le salon ; le reste part au tour suivant
MAX_ANNONCES = 20
#: le panneau est revérifié au plus une fois l'heure (un GET de 20 messages)
PANNEAU_S = 3600
#: l'historique (rattraper) : au plus autant de messages par tour, pour ne
#: pas retenir le tour des tickets plusieurs minutes d'affilée
RATTRAPAGE_PAR_TOUR = 40


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


def membres() -> Optional[Dict[str, Dict[str, Any]]]:
    """{uid : membre} sans les bots, toutes pages lues ; None si Discord ne
    rend pas la liste entière."""
    out: Dict[str, Dict[str, Any]] = {}
    apres = ""
    for _ in range(50):
        code, part = _api("GET", f"/guilds/{GID}/members?limit=1000" + (f"&after={apres}" if apres else ""))
        if code != 200 or not isinstance(part, list):
            print(f"[agency] liste des membres illisible (HTTP {code})", flush=True)
            return None
        out.update({str(m["user"]["id"]): m for m in part
                    if isinstance(m, dict) and not (m.get("user") or {}).get("bot")})
        if len(part) < 1000:
            return out
        apres = str(max(int(m["user"]["id"]) for m in part))
    return None


def _poster(salon: str, embed: Dict[str, Any], cle: str) -> str:
    nonce = hashlib.sha256(cle.encode()).hexdigest()[:24]
    code, rep = _api("POST", f"/channels/{salon}/messages",
                     json={"embeds": [embed], "allowed_mentions": {"parse": []},
                           "nonce": nonce, "enforce_nonce": True})
    return str(rep.get("id") or "") if code in (200, 201) and isinstance(rep, dict) else ""


def _nom(m: Dict[str, Any]) -> str:
    u = m.get("user") or {}
    return str(m.get("nick") or u.get("global_name") or u.get("username") or "?")


def _date(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(str(iso or "")) >= 10 else "?"


def rattraper(d: Dict[str, Any], actuels: Dict[str, Dict[str, Any]], role_verifie: str) -> int:
    """L'historique, une fois : propriétaire, 23/10/2026, devant la première
    arrivée annoncée : « remets les mecs ici et tout » — comme sur Twitter, où
    chaque membre a sa ligne. Chaque membre déjà là reçoit la sienne dans
    🚪・arrivées (date d'arrivée, vérifié ou non), dans l'ordre d'arrivée, et
    chaque vérifié sa bienvenue dans ✅・membres-vérifiés. Sans mention : ces
    gens sont là depuis des semaines. RATTRAPAGE_PAR_TOUR messages par tour ;
    rend le nombre posté. Fini quand il n'y a plus rien à poster (« rattrape »)."""
    connus = d.setdefault("membres", {})
    n = 0
    for uid, m in sorted(actuels.items(), key=lambda kv: str(kv[1].get("joined_at") or "")):
        if n >= RATTRAPAGE_PAR_TOUR:
            return n
        f = connus.setdefault(uid, {"joined_at": m.get("joined_at") or ""})
        verifie = bool(role_verifie and role_verifie in (m.get("roles") or []))
        if not f.get("arrivee"):
            embed = {"title": "🚪 Arrivée sur Agency VA INSTAGRAM",
                     "description": (f"<@{uid}> a rejoint le serveur le {_date(m.get('joined_at'))}.\n"
                                     + ("✅ Vérification validée." if verifie else
                                        f"⏳ **Pas encore vérifié.** La vérification se fait dans "
                                        f"<#{SALON_VERIF}>.")),
                     "color": 0x5865F2,
                     "footer": {"text": "Agency VA INSTAGRAM • Arrivées sur le serveur"}}
            mid = _poster(SALON_ARRIVEES, embed, f"{GID}:{uid}:{m.get('joined_at')}:arrivee")
            if not mid:
                return n
            f["arrivee"] = mid
            n += 1
            _ecrire(d)
        if verifie and not f.get("bienvenue"):
            if n >= RATTRAPAGE_PAR_TOUR:
                return n
            embed = {"title": "Bienvenue sur Agency VA INSTAGRAM !",
                     "description": f"<@{uid}>, ta vérification est validée.",
                     "color": 0x22C55E}
            mid = _poster(SALON_VERIFIES, embed, f"{GID}:{uid}:{m.get('joined_at')}:verifie")
            if not mid:
                return n
            f["bienvenue"] = mid
            n += 1
            _ecrire(d)
    d["rattrape"] = int(time.time())
    _ecrire(d)
    return n


def surveiller() -> Dict[str, Any]:
    """Un tour : le panneau, puis les arrivées et les départs. Rend le bilan."""
    bilan: Dict[str, Any] = {"arrivees": 0, "departs": 0, "panneau": ""}
    d = _etat()
    if time.time() - float(d.get("panneau_vu") or 0) >= PANNEAU_S:
        try:
            import verif_discord as vd
            bilan["panneau"] = vd.assurer_message_verif(GID)
        except Exception as e:                               # noqa: BLE001
            bilan["panneau"] = f"{type(e).__name__}: {e}"
        if bilan["panneau"] in ("deja", "pose"):
            d["panneau_vu"] = time.time()
    actuels = membres()
    if actuels is None:
        _ecrire(d)
        return bilan
    connus = d.setdefault("membres", {})
    if not d.get("initialise"):
        d["membres"] = {u: {"joined_at": m.get("joined_at") or ""} for u, m in actuels.items()}
        d["initialise"] = int(time.time())
        _ecrire(d)
        bilan["initialise"] = len(actuels)
        return bilan
    import verif_discord as vd
    role_verifie = (vd.serveur(GID) or {}).get("role_verifie")
    neufs = [u for u in actuels if u not in connus]
    if not d.get("rattrape"):
        bilan["rattrapage"] = rattraper(d, {u: m for u, m in actuels.items() if u in connus},
                                        role_verifie)
        if bilan["rattrapage"]:
            print(f"[agency] historique : {bilan['rattrapage']} message(s) posté(s)", flush=True)
    partis = [u for u in connus if u not in actuels]
    for uid in neufs[:MAX_ANNONCES]:
        m = actuels[uid]
        deja = role_verifie and role_verifie in (m.get("roles") or [])
        embed = {"title": "🚪 Nouvelle arrivée sur Agency VA INSTAGRAM",
                 "description": (f"<@{uid}> vient de rejoindre le serveur.\n"
                                 + ("✅ Vérification déjà validée." if deja else
                                    f"⏳ **Pas encore vérifié.** La vérification se fait dans "
                                    f"<#{SALON_VERIF}>.")),
                 "color": 0x5865F2,
                 "footer": {"text": "Agency VA INSTAGRAM • Arrivées sur le serveur"}}
        mid = _poster(SALON_ARRIVEES, embed, f"{GID}:{uid}:{m.get('joined_at')}:arrivee")
        if not mid:
            break                                   # Discord refuse : le tour suivant reprend
        connus[uid] = {"joined_at": m.get("joined_at") or "", "arrivee": mid}
        bilan["arrivees"] += 1
        _ecrire(d)
    for uid in partis[:MAX_ANNONCES]:
        f = connus.get(uid) or {}
        embed = {"title": "👋 Départ",
                 "description": f"<@{uid}> a quitté le serveur.",
                 "color": 0xE67E22,
                 "footer": {"text": "Agency VA INSTAGRAM • Départs"}}
        mid = _poster(SALON_DEPARTS, embed, f"{GID}:{uid}:{f.get('joined_at')}:depart")
        if not mid:
            break
        d.setdefault("partis", {})[uid] = dict(f, depart=mid, quand=int(time.time()))
        connus.pop(uid, None)
        bilan["departs"] += 1
        _ecrire(d)
    _ecrire(d)
    if bilan["arrivees"] or bilan["departs"]:
        print(f"[agency] {bilan['arrivees']} arrivée(s), {bilan['departs']} départ(s) annoncé(s)",
              flush=True)
    return bilan
