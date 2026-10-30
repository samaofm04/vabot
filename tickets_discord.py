"""Un nouveau vérifié est confié à un manager, qui reçoit son ticket.

À la fin de la vérification, le membre reçoit ✅ Vérifié — et jusqu'ici rien
d'autre : il attendait dans un serveur muet que quelqu'un le remarque. Ce
module lui ouvre un salon privé, rangé dans la catégorie du manager à qui il
est confié, et les deux y sont mentionnés.

La répartition est un TOUR DE RÔLE simple, gardé sur disque : deux arrivées de
suite ne tombent pas sur le même manager.

POURQUOI UN FICHIER À PART. Le point d'accroche dans verif_discord.py tient en
quatre lignes, sous try/except : un ticket qui échoue ne doit jamais empêcher
une vérification d'aboutir. Le reste vit ici.

COMMENT ON TROUVE LES MANAGERS. Discord refuse au bot la liste des membres
(HTTP 403 « Missing Access » : l'autorisation « Server Members Intent » est
désactivée pour l'application SEVEN). La RECHERCHE de membres, elle, répond.
On balaye donc l'alphabet et les chiffres, et on garde ceux qui portent le
rôle Manager — 36 requêtes, gardées une heure en mémoire. Mesure du
23/09/2026 : 221 membres retrouvés, les 2 managers trouvés.
Le jour où l'autorisation sera activée, `_par_la_liste` répondra et le
balayage ne servira plus. Une liste posée à la main dans
data/tickets_config.json l'emporte toujours sur les deux.

LES CATÉGORIES SUIVENT LE RÔLE (13/10/2026) : toutes les 10 minutes,
suivre_partout() relit les managers en mode strict et aligne les catégories
« Manager X » sur eux — voir la section du même nom, en bas du fichier.
"""
from __future__ import annotations

import json
import re
import string
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "tickets.json"
CONFIG_FICHIER = DATA_DIR / "tickets_config.json"
# Une seule main à la fois sur tickets.json : un ticket s'ouvre (fil de la
# vérification) pendant que le suivi des managers (boucle du podium) réécrit
# des fiches. Chaque lecture-modification-écriture se fait sous ce verrou, et
# relit le fichier juste avant d'écrire — sinon le dernier écrivain efface
# l'autre sans un mot.
_VERROU = threading.RLock()

# Une heure : un manager nommé aujourd'hui doit pouvoir recevoir quelqu'un
# dans la journée, sans qu'on relance 36 requêtes à chaque arrivée.
CACHE_MANAGERS_S = 3600
_CACHE: Dict[str, Dict[str, Any]] = {}

# Droits dans le ticket (voir Discord : Permissions).
VOIR = 1 << 10            # 1024     VIEW_CHANNEL
ECRIRE = 1 << 11          # 2048     SEND_MESSAGES
LIENS = 1 << 14           # 16384    EMBED_LINKS
FICHIERS = 1 << 15        # 32768    ATTACH_FILES
HISTORIQUE = 1 << 16      # 65536    READ_MESSAGE_HISTORY
GERER_MSG = 1 << 13       # 8192     MANAGE_MESSAGES
MEMBRE = VOIR | ECRIRE | LIENS | FICHIERS | HISTORIQUE
MANAGER = MEMBRE | GERER_MSG

PREFIXE = "─│"
# Discord RETIRE l'arobase d'un nom de salon (et le point) : « va-@moan_ofm »
# revenait « va-moan_ofm ». Le sosie pleine chasse, lui, passe intact — la même
# ruse que ─ │ ┤, vérifiée en créant un salon jetable.
AROBASE = "\uff20"

# Le parcours à manager + salon perso ne vaut que pour YouLab TWITTER. Le
# serveur Entretien doit rester tel qu'il était : on n'y ouvre aucun ticket.
# Agency VA INSTAGRAM (22/10/2026), servi par Wario : ses accueils ont les
# boutons de Twitter (boutons_va). Dans le périmètre depuis le 23/10/2026
# (propriétaire : « branche les arrivées et la vérification ») : ticket à la
# vérification, suivi des managers, départs — comme Twitter.
AGENCY_IG_ID = "1488331963575177247"
SERVEURS_TICKETS = {"1445108485090971710",    # YouLab TWITTER
                    "1498948161039896586",    # YouLab THREADS
                    AGENCY_IG_ID}             # Agency VA INSTAGRAM

#: Les managers d'un serveur quand data/tickets_config.json n'en pose pas.
#: Agency, 23/10/2026 : Gone et Yoshiki reçoivent les VA ; le propriétaire
#: (vectorofm) et septofm ont 🛡️ Manager sans en recevoir — sans cette liste,
#: le tour de rôle leur aurait donné des VA et une catégorie chacun.
MANAGERS_POSES: Dict[str, List[str]] = {
    AGENCY_IG_ID: ["1392192812073615391",     # Gone (jrm_12.)
                   "1502081637591289877"],    # Yoshiki (yo_ofm)
}


def _poses(gid: str) -> List[Any]:
    """La liste fixe des managers : tickets_config.json, sinon MANAGERS_POSES."""
    return ((_config().get("managers") or {}).get(str(gid))
            or MANAGERS_POSES.get(str(gid)) or [])

# Tout nouveau arrivant est en essai, sans exception : le role est pose en
# meme temps que son salon. Ce qui le fera passer « confirme » viendra plus
# tard ; en attendant, personne n'est confirme par defaut.
ROLE_ESSAI_NOM = "🧪 Essai"
ROLE_CONFIRME_NOM = "⭐ Confirmé"      # « ─│ » : Discord retire « -| » d'un nom de salon texte
BARRE = "┤"              # « ┤ »

# Helper : « au même niveau que les managers » (propriétaire, 13/10/2026) —
# mêmes salons, mêmes boutons — mais sans être manager : aucun VA ne lui est
# confié, il n'a pas de catégorie et le suivi des managers l'ignore. Son nom
# ne doit pas contenir « manager » : role_manager() prend le premier rôle qui
# le contient, et un « Helper manager » serait devenu LE rôle Manager.
ROLE_HELPER_NOM = "🤝 Helper"
COULEUR_HELPER = 0x2DD4BF
# Le rôle est relu à chaque bouton cliqué (comme role_manager) : 10 minutes de
# cache suffisent, un helper nommé attend au pire ce délai.
CACHE_HELPER_S = 600
_CACHE_HELPER: Dict[str, Dict[str, Any]] = {}
# Droits recopiés par tour : ~200 salons de VA au premier passage, sans
# monopoliser le débit de Discord ; le reste attend le tour suivant.
MAX_HELPER_PAR_TOUR = 40


def _api(methode: str, chemin: str, **kw):
    """Le client REST de verif_discord : un seul endroit qui connaît le jeton."""
    from verif_discord import api
    return api(methode, chemin, **kw)


def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(ETAT_FICHIER, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ecrire_etat(d: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[ticket] état non écrit : {type(e).__name__}: {e}", flush=True)


def _config() -> Dict[str, Any]:
    try:
        d = safe_json.load(CONFIG_FICHIER, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _role_manager_sur(gid: str) -> Optional[str]:
    """Comme role_manager, mais None quand Discord n'a pas répondu.

    « Ce serveur n'a pas de rôle Manager » et « je n'ai pas pu lire les rôles »
    ne mènent pas au même geste : le suivi automatique des catégories ne doit
    rien toucher sur une panne."""
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return None
    for r in rep:
        if "manager" in str(r.get("name", "")).lower():
            return str(r.get("id"))
    return ""


def role_manager(gid: str) -> str:
    """L'identifiant du rôle Manager du serveur, ou « »."""
    return _role_manager_sur(gid) or ""


def _est_helper(r: Dict[str, Any]) -> bool:
    nom = str(r.get("name", "")).lower()
    return "helper" in nom and "manager" not in nom


def role_helper(gid: str) -> str:
    """L'identifiant du rôle Helper, ou « ». Hors des serveurs à tickets : « »
    sans rien demander à Discord (verif_discord l'appelle pour tout serveur)."""
    gid = str(gid or "")
    if gid not in set(str(s) for s in (_config().get("serveurs") or SERVEURS_TICKETS)):
        return ""
    hit = _CACHE_HELPER.get(gid)
    if hit and time.time() - hit["ts"] < CACHE_HELPER_S:
        return hit["v"]
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return hit["v"] if hit else ""
    v = next((str(r.get("id")) for r in rep if _est_helper(r)), "")
    _CACHE_HELPER[gid] = {"ts": time.time(), "v": v}
    return v


def _droits_staff(rid: str, hid: str) -> List[Dict[str, Any]]:
    """Les lignes de rôle d'un salon de VA : Manager, et Helper au même niveau."""
    return [{"id": r, "type": 0, "allow": str(MANAGER), "deny": "0"} for r in (rid, hid) if r]


def _helper_ignore(gid: str, bilan: Dict[str, Any], raison: str) -> Dict[str, Any]:
    """Rien n'a pu être fait : dit une fois (pas toutes les 10 minutes)."""
    bilan["ignore"] = raison
    _dire(f"helper-ignore:{gid}", f"{gid} : helper — {raison}, rien touché")
    return bilan


def aligner_helper(gid: str) -> Dict[str, Any]:
    """Crée le rôle Helper s'il manque, puis lui donne, salon par salon, les
    mêmes droits que le rôle Manager (catégories, tickets, salons du staff).

    N'enlève rien : un salon où le Manager n'a pas de ligne garde celle du
    Helper, posée à la main. Rend le bilan, et le dit quand il a agi ou raté."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"cree": False, "copies": 0, "deja": 0, "reportes": 0,
                             "rates": [], "ignore": ""}
    code, roles = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(roles, list):
        return _helper_ignore(gid, bilan, f"rôles illisibles (HTTP {code})")
    mgr = next((r for r in roles if "manager" in str(r.get("name", "")).lower()), None)
    if not mgr:
        return _helper_ignore(gid, bilan, "pas de rôle Manager à recopier")
    hlp = next((r for r in roles if _est_helper(r)), None)
    if not hlp:
        corps = {"name": ROLE_HELPER_NOM, "color": COULEUR_HELPER,
                 "permissions": str(mgr.get("permissions") or "0"),
                 "hoist": bool(mgr.get("hoist")), "mentionable": bool(mgr.get("mentionable"))}
        code, rep = _api("POST", f"/guilds/{gid}/roles", json=corps)
        if code in (400, 403):
            # Discord refuse de donner un droit que le bot n'a pas lui-même :
            # le rôle naît sans droits de serveur, les salons font le reste.
            corps["permissions"] = "0"
            bilan["rates"].append(f"droits de serveur du Manager non recopiés (HTTP {code})")
            code, rep = _api("POST", f"/guilds/{gid}/roles", json=corps)
        if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
            return _helper_ignore(gid, bilan, f"rôle Helper non créé (HTTP {code}) {str(rep)[:80]}")
        hlp = rep
        bilan["cree"] = True
        # juste sous Manager dans la liste des membres ; un refus ne change
        # que l'affichage, les droits sont les mêmes
        c2, r2 = _api("PATCH", f"/guilds/{gid}/roles",
                      json=[{"id": str(hlp["id"]), "position": int(mgr.get("position") or 1)}])
        if c2 != 200:
            bilan["rates"].append(f"rôle non remonté sous Manager (HTTP {c2})")
    mid, hid = str(mgr["id"]), str(hlp["id"])
    _CACHE_HELPER[gid] = {"ts": time.time(), "v": hid}

    code, salons = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        return _helper_ignore(gid, bilan, f"salons illisibles (HTTP {code})")
    _dire(f"helper-ignore:{gid}", "")
    for c in salons:
        lignes = {str(o.get("id")): o for o in (c.get("permission_overwrites") or [])}
        m = lignes.get(mid)
        if not m:
            continue
        voulu = (str(m.get("allow") or "0"), str(m.get("deny") or "0"))
        h = lignes.get(hid)
        if h and (str(h.get("allow") or "0"), str(h.get("deny") or "0")) == voulu:
            bilan["deja"] += 1
            continue
        if bilan["copies"] >= MAX_HELPER_PAR_TOUR:
            bilan["reportes"] += 1
            continue
        code, rep = _api("PUT", f"/channels/{c['id']}/permissions/{hid}",
                         json={"type": 0, "allow": voulu[0], "deny": voulu[1]})
        if code in (200, 204):
            bilan["copies"] += 1
        else:
            bilan["rates"].append(f"{c.get('name')} (HTTP {code})")
            if code == 429:
                break
    texte = (("rôle créé · " if bilan["cree"] else "")
             + f"{bilan['copies']} salon(s) alignés, {bilan['deja']} déjà bons, "
             f"{bilan['reportes']} au prochain tour"
             + (" · ratés : " + ", ".join(bilan["rates"][:6]) if bilan["rates"] else ""))
    if bilan["cree"] or bilan["copies"] or bilan["reportes"]:
        print(f"[helper] {gid} : {texte}", flush=True)
        _dire(f"helper:{gid}", "")
    else:
        # un refus qui dure (droit manquant dans un salon du staff) se dit
        # une fois, pas toutes les 10 minutes ; « » efface sans bruit
        _dire(f"helper:{gid}", f"{gid} : helper — {texte}" if bilan["rates"] else "")
    return bilan


PAGE_MEMBRES = 1000         # le maximum que Discord rend par page
PAGES_MAX = 50              # 50 000 membres : au-delà, on ne prétend plus savoir


def _par_la_liste(gid: str, rid: str, strict: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Les membres via /guilds/{id}/members. None si Discord refuse (403).

    strict=True (suivi des catégories) lit TOUTES les pages : une seule page
    de 1000, c'était un manager au-delà pris pour parti, sa catégorie vidée.
    Une page refusée, ou qui n'avance plus, rend None — la recherche prend
    alors le relais, plutôt qu'une liste tronquée qui passerait pour sûre."""
    code, rep = _api("GET", f"/guilds/{gid}/members", params={"limit": PAGE_MEMBRES})
    if code != 200 or not isinstance(rep, list):
        return None
    tous = list(rep)
    pages = 1
    while strict and len(rep) >= PAGE_MEMBRES:
        ids = [int(i) for i in (str((m.get("user") or {}).get("id") or "") for m in rep)
               if i.isdigit()]
        apres = max(ids) if ids else 0
        if pages >= PAGES_MAX or not ids:
            _dire(f"pages:{gid}", f"{gid} : liste des membres trop longue "
                                         f"({len(tous)} lus) — on passe par la recherche")
            return None
        code, rep = _api("GET", f"/guilds/{gid}/members",
                         params={"limit": PAGE_MEMBRES, "after": str(apres)})
        if code != 200 or not isinstance(rep, list):
            _dire(f"pages:{gid}", f"{gid} : page {pages + 1} des membres refusée "
                                         f"(HTTP {code}) — on passe par la recherche")
            return None
        neufs = [m for m in rep
                 if str((m.get("user") or {}).get("id") or "").isdigit()
                 and int((m.get("user") or {}).get("id")) > apres]
        if rep and not neufs:
            # Discord ignorerait « after » : la même page reviendrait sans fin
            _dire(f"pages:{gid}", f"{gid} : la liste des membres ne pagine pas "
                                         "— on passe par la recherche")
            return None
        tous.extend(neufs)
        pages += 1
    if strict:
        # « pages » n'est pas effacé par un tour réussi (la recherche qui prend
        # le relais réussit) : sinon la même phrase reviendrait toutes les 10 min
        _dire(f"pages:{gid}", "")
    return [m for m in tous if rid in (m.get("roles") or [])]


# Pause entre deux recherches de membres (les tests la mettent à zéro).
PAUSE_RECHERCHE_S = 0.25
LIMITE_RECHERCHE = 100


def _par_la_recherche(gid: str, rid: str, strict: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Les membres via la recherche, balayée sur a-z et 0-9 (voir l'en-tête).

    strict=True sert au suivi automatique des catégories, où un manager
    MANQUÉ passerait pour un manager PARTI — et ses VA seraient redistribués.
    On y rend donc None dès qu'une requête échoue, on balaye aussi « _ » et
    « . » (un identifiant Discord peut commencer par eux), et une lettre qui
    remplit la page (100 réponses, la limite de Discord) est reprise sur deux
    lettres plutôt que tronquée en silence."""
    trouves: Dict[str, Dict[str, Any]] = {}
    lettres = string.ascii_lowercase + string.digits + ("_." if strict else "")
    file = list(lettres)
    while file:
        q = file.pop(0)
        code, rep = _api("GET", f"/guilds/{gid}/members/search",
                         params={"query": q, "limit": LIMITE_RECHERCHE})
        if code != 200 or not isinstance(rep, list):
            if strict:
                _dire(f"liste-detail:{gid}", f"{gid} : recherche « {q} » refusée "
                                             f"(HTTP {code}) — liste des managers incomplète")
                return None
            continue
        for m in rep:
            if rid in (m.get("roles") or []):
                trouves[str(((m.get("user") or {}).get("id")))] = m
        if strict and len(rep) >= LIMITE_RECHERCHE:
            if len(q) >= 3:
                _dire(f"liste-detail:{gid}", f"{gid} : plus de {LIMITE_RECHERCHE} membres "
                                             f"en « {q} » — liste des managers incomplète")
                return None
            file.extend(q + c for c in lettres)
        if PAUSE_RECHERCHE_S:
            time.sleep(PAUSE_RECHERCHE_S)
    return list(trouves.values())


def _membres_poses(gid: str, poses: List[Any], strict: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Les managers de la liste fixe (tickets_config.json), relus chez Discord.

    Sans leur surnom, _nom_court rendait l'identifiant : la catégorie devenait
    « Manager 1445… » alors que nom_manager (lien GetMySocial) disait
    « YAZID » — deux noms pour le même manager. Relu une fois, le même nom
    sert partout. Strict : un manager illisible rend None (on ne sait pas)."""
    out: List[Dict[str, Any]] = []
    for u in poses:
        code, m = _api("GET", f"/guilds/{gid}/members/{u}")
        if code == 200 and isinstance(m, dict) and (m.get("user") or {}).get("id"):
            out.append(m)
        elif strict:
            _dire(f"liste-detail:{gid}", f"{gid} : manager {u} de la liste fixe illisible "
                                         f"(HTTP {code}) — data/tickets_config.json à vérifier")
            return None
        else:
            out.append({"user": {"id": str(u)}})
    return out


def managers(gid: str, force: bool = False) -> List[Dict[str, Any]]:
    """Les membres qui portent le rôle Manager, triés pour un tour de rôle stable.

    Rend [] si on ne peut pas les déterminer — l'appelant ouvre alors le ticket
    au rôle Manager entier plutôt qu'à personne."""
    gid = str(gid)
    hit = _CACHE.get(gid)
    if hit and not force and time.time() - hit["ts"] < CACHE_MANAGERS_S:
        return hit["v"]
    poses = _poses(gid)
    if poses:
        out = _membres_poses(gid, poses) or []
    else:
        rid = role_manager(gid)
        if not rid:
            return []
        out = _par_la_liste(gid, rid)
        if out is None:                       # 403 : l'autorisation manque
            out = _par_la_recherche(gid, rid) or []
    # Tri par identifiant : l'ordre du tour de rôle ne dépend pas de celui,
    # arbitraire, dans lequel Discord a répondu.
    out.sort(key=lambda m: str((m.get("user") or {}).get("id")))
    if out:
        _CACHE[gid] = {"ts": time.time(), "v": out}
    return out


def _prochain(gid: str, liste: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Le manager suivant dans le tour de rôle, et avance le compteur."""
    if not liste:
        return None
    with _VERROU:
        d = _etat()
        tours = d.setdefault("tours", {})
        i = int(tours.get(str(gid)) or 0) % len(liste)
        tours[str(gid)] = (i + 1) % len(liste)
        _ecrire_etat(d)
    return liste[i]


#: Les mots de rôle qu'un surnom porte DEVANT le prénom. Constaté sur Threads
#: le 13/10/2026 : « MANAGER | Momoby » et « MANAGER | Abdoul » donnaient tous
#: deux « MANAGER » — une catégorie « Manager MANAGER », puis « deux managers
#: au même nom », et plus rien ne bougeait. Seulement en tête, et seulement
#: s'il reste un nom derrière : un surnom « Boss » tout court reste « BOSS ».
MOTS_DE_ROLE = {"MANAGER", "MANAGERS", "HELPER", "BOSS", "ADMIN", "STAFF", "MODO"}


def _nom_court(m: Dict[str, Any]) -> str:
    """Le nom porté par la catégorie, comme « Manager FANI ».

    Les surnoms Discord sont décorés : « 🎯│𝑴𝑶𝑨𝑵 » doit donner « MOAN », pas
    une catégorie illisible. NFKC ramène d'abord les lettres fantaisie
    (𝑴𝑶𝑨𝑵, ｍｏａｎ…) à des lettres normales — sans lui, il ne resterait rien à
    garder. On ne garde ensuite que lettres et chiffres, et on prend le
    premier morceau : « samuel.0314 » -> « SAMUEL »."""
    import unicodedata
    u = m.get("user") or {}
    brut = (m.get("nick") or u.get("global_name") or u.get("username") or "").strip()
    plat = unicodedata.normalize("NFKC", brut)
    morceaux = [x for x in re.split(r"[^0-9A-Za-zÀ-ÿ]+", plat) if x]
    # Un morceau purement numérique (« 0314 ») ne nomme personne.
    lettres = [x for x in morceaux if not x.isdigit()]
    # ni un mot de rôle devant le prénom (« MANAGER | Abdoul » -> ABDOUL)
    while len(lettres) > 1 and lettres[0].upper() in MOTS_DE_ROLE:
        lettres = lettres[1:]
    court = (lettres or morceaux or [""])[0]
    return (court or str(u.get("id") or "?")).upper()[:24]


def _salon_existe(cid: str) -> bool:
    return bool(cid) and _api("GET", f"/channels/{cid}")[0] == 200


def nom_categorie(m: Dict[str, Any]) -> str:
    """« 🔵┤ Manager YAZID ├🔵 » — le seul endroit qui fabrique ce nom."""
    return f"🔵{BARRE} Manager {_nom_court(m)} ├🔵"


def _cle_categorie(nom: Any) -> str:
    """Le manager que nomme une catégorie, réduit comme _nom_court : « YAZID ».

    La lecture du nom est CELLE de liens_va (nom_dans_categorie) : deux
    lectures différentes auraient donné deux rangements, l'un pour les
    salons, l'autre pour les liens GetMySocial. On la réduit ensuite comme un
    surnom : une catégorie renommée à la main « Manager Spectrum🥷 » désigne
    bien SPECTRUM, au lieu d'en faire recréer une seconde. « » : ce n'est pas
    une catégorie de manager."""
    import liens_va
    x = liens_va.nom_dans_categorie(str(nom or ""))
    if not x:
        return ""
    court = _nom_court({"nick": x, "user": {"id": ""}})
    return "" if court == "?" else court


def _rang(c: Dict[str, Any]):
    """L'ordre d'affichage Discord : position, puis identifiant."""
    i = str(c.get("id") or "")
    return (int(c.get("position") or 0), int(i) if i.isdigit() else 0, i)


def _categorie_de(salons: List[Dict[str, Any]], m: Dict[str, Any]) -> str:
    """La catégorie existante de ce manager parmi `salons`, ou « »."""
    nom, cle = nom_categorie(m), _nom_court(m)
    cats = sorted((c for c in salons if c.get("type") == 4), key=_rang)
    for c in cats:
        if c.get("name") == nom:
            return str(c["id"])
    for c in cats:
        if _cle_categorie(c.get("name")) == cle:
            return str(c["id"])
    return ""


def _creer_categorie(gid: str, m: Dict[str, Any], rid: Optional[str] = None):
    """Crée la catégorie du manager. Rend (code HTTP, identifiant ou « »)."""
    if rid is None:
        rid = role_manager(gid)
    droits = [{"id": gid, "type": 0, "allow": "0", "deny": str(VOIR)}]
    droits += _droits_staff(rid, role_helper(gid))
    code, rep = _api("POST", f"/guilds/{gid}/channels",
                     json={"name": nom_categorie(m), "type": 4,
                           "permission_overwrites": droits})
    ok = code == 201 and isinstance(rep, dict) and rep.get("id")
    return code, (str(rep["id"]) if ok else "")


def categorie_du_manager(gid: str, m: Dict[str, Any]) -> str:
    """La catégorie « 🔵┤ Manager X ├🔵 », créée si elle manque.

    Trouvée aussi quand son nom a été retapé à la main (casse, emoji) : le
    13/10 le propriétaire a renommé « Manager VECTOR » en « Manager SPECTRUM »
    lui-même ; une comparaison au caractère près en aurait recréé une."""
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code == 200 and isinstance(rep, list):
        deja = _categorie_de(rep, m)
        if deja:
            return deja
    return _creer_categorie(gid, m)[1]


#: Les serveurs dont les salons de VA portent le numéro du VA, comme Va IG
#: (« 🔴-21-va-… ») : « ─│🔵┤-61-va-＠momobtn ». Propriétaire, 13/10/2026,
#: devant les tickets de Threads : « faut mettre le numéro du VA ».
NUMERO_DANS_SALON = {"1498948161039896586",     # YouLab THREADS
                     # Agency VA INSTAGRAM, propriétaire 23/10/2026 : « après
                     # tu donnes des numéros aux VA » — « ─│🔵┤-12-va-＠pseudo »,
                     # le numéro de « Instagram VA 12 » (table commune)
                     "1488331963575177247"}


def numero_va(gid: str, uid: str, pseudo: str = "") -> int:
    """Le numéro du VA sur ce serveur : celui de son lien (« Threads VA 61
    @momobtn »), sinon celui que liens_va lui réserve — la même table : le
    lien créé ensuite portera le même. 0 si on ne sait pas."""
    try:
        import liens_va as lv
        n = int((lv.lien_de(gid, uid) or {}).get("numero") or 0)
        if not n and pseudo:
            n = int(lv.numero_de(pseudo) or 0)
        return n
    except Exception as e:                                   # noqa: BLE001
        print(f"[ticket] numéro de {uid} : {type(e).__name__}: {e}", flush=True)
        return 0


def nom_salon_va(gid: str, uid: str, pseudo: str) -> str:
    """« ─│🔵┤-va-＠pseudo », et sur Threads « ─│🔵┤-61-va-＠pseudo »."""
    n = numero_va(gid, uid, pseudo) if str(gid) in NUMERO_DANS_SALON else 0
    return f'{PREFIXE}🔵{BARRE}' + (f"-{n}" if n else "") + f"-va-{AROBASE}{pseudo}"


#: La pastille du salon d'un VA (le rond entre « ─│ » et « ┤ ») dit si son
#: lien fait des clics. Propriétaire, 13/10/2026, pour Threads : « bleu il est
#: là, vert il fait des clics, rouge il est là mais il fait pas de clics par
#: rapport à son lien », puis, le même jour : « au pire orange avec lien mais
#: pas de visite ». Sur les JOURS_CLICS_SALON derniers jours, aujourd'hui
#: compris — la fenêtre du ⚙️ « 0 clic sur J-2..J » du récap des clics.
#:   🔵 il est là, pas encore de lien
#:   🟢 son lien a eu au moins une visite
#:   🟠 il a un lien, mais aucune visite (neuf, coupé ou inactif)
#:   🔴 pas de lien, et plus rien sur le serveur depuis JOURS_CLICS_SALON jours
#:      (ni message dans un salon, ni clic sur un bouton du bot), ticket ouvert
#:      depuis au moins autant. Propriétaire, même jour : « le VA il est là mais
#:      répond pas, inactif dans le serveur de partout, en rouge depuis 2 j »,
#:      « sans lien »
COULEUR_DANS_SALON = {"1498948161039896586"}     # YouLab THREADS
JOURS_CLICS_SALON = 2
ROND_LA, ROND_CLICS, ROND_RIEN, ROND_ABSENT = "🔵", "🟢", "🟠", "🔴"


_ACTIVITE: Dict[str, float] = {}
_ACTIVITE_LUE = [False]
_ACTIVITE_ECRITE = [0.0]


def _fichier_activite() -> Path:
    # relu à chaque appel : les tests déplacent ETAT_FICHIER
    return ETAT_FICHIER.parent / "activite_va.json"


def noter_activite(gid: str, uid: str, quand: Optional[float] = None) -> None:
    """Le VA `uid` a fait quelque chose sur ce serveur (COULEUR_DANS_SALON) :
    un clic sur un bouton du bot, ou un message relu à la synchro. Gardé sur
    disque, une écriture par minute au plus : un redémarrage ne le fait pas
    passer au rouge."""
    gid, uid = str(gid or ""), str(uid or "")
    if gid not in COULEUR_DANS_SALON or not uid.isdigit():
        return
    t = float(quand or time.time())
    with _VERROU:
        _charger_activite()
        cle = f"{gid}:{uid}"
        if t <= _ACTIVITE.get(cle, 0):
            return
        _ACTIVITE[cle] = t
        if time.time() - _ACTIVITE_ECRITE[0] >= 60:
            _ACTIVITE_ECRITE[0] = time.time()
            try:
                safe_json.write(_fichier_activite(), dict(_ACTIVITE))
            except Exception as e:                           # noqa: BLE001
                print(f"[ticket] activité non enregistrée : {type(e).__name__}: {e}", flush=True)


def noter_clic(charge: Dict[str, Any]) -> None:
    """Un clic reçu par la route des interactions (Bowser sur Threads)."""
    try:
        u = ((charge.get("member") or {}).get("user") or charge.get("user") or {})
        if not u.get("bot"):
            noter_activite(str(charge.get("guild_id") or ""), str(u.get("id") or ""))
    except Exception:                                        # noqa: BLE001
        pass


def _charger_activite() -> None:
    if _ACTIVITE_LUE[0]:
        return
    _ACTIVITE_LUE[0] = True
    d = safe_json.load(_fichier_activite(), default={}) or {}
    if isinstance(d, dict):
        for k, v in d.items():
            try:
                _ACTIVITE[str(k)] = max(float(v), _ACTIVITE.get(str(k), 0))
            except (TypeError, ValueError):
                pass


def derniere_activite(gid: str, uid: str) -> float:
    with _VERROU:
        _charger_activite()
        return float(_ACTIVITE.get(f"{gid}:{uid}", 0))


def _relire_messages(gid: str, salons: List[Dict[str, Any]]) -> int:
    """Note l'activité de chaque auteur des messages récents du serveur : les
    cent derniers messages de chaque salon texte que le bot lit. Rend le
    nombre de salons lus."""
    import datetime as dt
    depuis = time.time() - JOURS_CLICS_SALON * 86400
    lus = 0
    for c in salons:
        if not isinstance(c, dict) or c.get("type", 0) not in (0, 5):
            continue
        code, msgs = _api("GET", f'/channels/{c.get("id")}/messages', params={"limit": "100"})
        if code != 200 or not isinstance(msgs, list):
            continue                       # salon fermé au bot : rien à en dire
        lus += 1
        for m in msgs:
            a = (m or {}).get("author") or {}
            if a.get("bot") or not a.get("id"):
                continue
            try:
                t = dt.datetime.fromisoformat(str(m.get("timestamp"))).timestamp()
            except (TypeError, ValueError):
                continue
            if t >= depuis:
                noter_activite(gid, str(a["id"]), t)
    return lus


def _clics_recents(gid: str) -> Optional[Dict[str, int]]:
    """{identifiant du lien: visites sur les derniers jours} pour TOUS les liens
    de l'espace GetMySocial du serveur, en un appel (get_link_metrics, par
    page de cent). None si GetMySocial ne répond pas : la pastille reste alors
    ce qu'elle est, plutôt que de passer au rouge sur une panne."""
    import datetime as dt
    import gms
    import liens_va as lv
    try:
        from zoneinfo import ZoneInfo
        auj = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:                                        # noqa: BLE001
        auj = dt.date.today()
    args: Dict[str, Any] = {"team_id": str(lv.espace(gid)["equipe"]), "limit": 100,
                            "start_date": (auj - dt.timedelta(days=JOURS_CLICS_SALON)).isoformat(),
                            "end_date": auj.isoformat(), "timezone": "Europe/Paris"}
    out: Dict[str, int] = {}
    for _page in range(20):
        r = gms._call_tool("get_link_metrics", args)
        d = r.get("data") if r.get("ok") else None
        lignes = d.get("data") if isinstance(d, dict) else None
        if not isinstance(lignes, list):
            print(f"[ticket] {gid} : visites des liens illisibles ({str(r.get('error'))[:80]}) "
                  "— pastilles laissées telles quelles", flush=True)
            return None
        for x in lignes:
            if isinstance(x, dict) and x.get("key"):
                out[str(x["key"])] = int(x.get("pageviews") or 0)
        if not d.get("has_more") or not d.get("next_cursor"):
            return out
        args["cursor"] = d["next_cursor"]
    return out


def rond_du_va(gid: str, uid: str, clics: Optional[Dict[str, int]],
               fiche: Optional[Dict[str, Any]] = None) -> str:
    """La pastille du salon de ce VA (voir COULEUR_DANS_SALON). « » : on ne sait
    pas (visites illisibles), le salon garde la sienne."""
    import liens_va as lv
    l = lv.lien_de(gid, uid) or {}
    lid = str(l.get("link_id") or "")
    if not lid:
        delai = JOURS_CLICS_SALON * 86400
        ouvert = float((fiche or {}).get("ouvert") or 0)
        if (time.time() - ouvert >= delai
                and time.time() - derniere_activite(gid, uid) >= delai):
            return ROND_ABSENT
        return ROND_LA
    if l.get("actif") is False:
        return ROND_RIEN
    if clics is None:
        return ""
    if int(clics.get(lid) or 0) > 0:
        return ROND_CLICS
    return ROND_RIEN


def numeroter_salons(gid: str, max_par_tour: int = 10) -> Dict[str, Any]:
    """Le nom des salons de VA de ce serveur : le numéro du VA
    (NUMERO_DANS_SALON) et la pastille de ses clics (COULEUR_DANS_SALON),
    « ─│🟢┤-61-va-＠momobtn ». Les deux en UN renommage : Discord ne renomme un
    salon que deux fois par dix minutes. Un nom déjà juste n'est pas touché ;
    au plus `max_par_tour` renommages par passage, le reste au suivant."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"renommes": [], "rates": []}
    numeroter, colorer = gid in NUMERO_DANS_SALON, gid in COULEUR_DANS_SALON
    if not (numeroter or colorer):
        return bilan
    fiches = {k.split(":", 1)[1]: f for k, f in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(f, dict) and f.get("salon")}
    if not fiches:
        return bilan
    code, salons = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        bilan["rates"].append(f"salons illisibles (HTTP {code})")
        return bilan
    par_id = {str(c.get("id")): c for c in salons if isinstance(c, dict)}
    clics = _clics_recents(gid) if colorer else None
    if colorer:
        import liens_va as lv
        if any(not (lv.lien_de(gid, u) or {}).get("link_id") for u in fiches):
            # un VA sans lien peut passer au rouge : qui a écrit, et où
            _relire_messages(gid, salons)
    for uid, f in fiches.items():
        if len(bilan["renommes"]) >= max_par_tour:
            break
        c = par_id.get(str(f["salon"]))
        nom = str((c or {}).get("name") or "")
        i = nom.find(f"-va-{AROBASE}")
        if not c or i < 0 or not nom.startswith(PREFIXE) or BARRE not in nom[:i]:
            continue                      # salon disparu, ou pas un ticket au format
        pseudo = nom[i + len(f"-va-{AROBASE}"):]
        tete = nom[:i]
        j = tete.find(BARRE)
        rond = tete[len(PREFIXE):j]
        deja = re.search(r"-(\d+)$", tete)
        n = int(deja.group(1)) if deja else (numero_va(gid, uid, pseudo) if numeroter else 0)
        if colorer:
            rond = rond_du_va(gid, uid, clics, f) or rond
        voulu = (f"{PREFIXE}{rond}{BARRE}" + (f"-{n}" if n else "")
                 + f"-va-{AROBASE}{pseudo}")
        if voulu == nom:
            continue
        code, rep = _api("PATCH", f"/channels/{c['id']}", json={"name": voulu})
        if code == 200:
            bilan["renommes"].append(voulu)
        else:
            bilan["rates"].append(f"{nom} : HTTP {code}")
            if code == 429:
                break
    if bilan["renommes"] or bilan["rates"]:
        print(f"[ticket] {gid} : noms des salons : {bilan}", flush=True)
    return bilan


#: Les serveurs dont les salons de VA sont rangés par pastille, puis par
#: numéro, dans chaque catégorie de manager. Propriétaire, 13/10/2026 :
#: « propose-moi quelque chose pour trier tout le monde » — choisi : 🟢 en
#: haut, puis 🟠, puis 🔵, et à couleur égale le numéro du VA.
TRI_SALONS = {"1498948161039896586"}             # YouLab THREADS
ORDRE_RONDS = (ROND_CLICS, ROND_RIEN, ROND_LA, ROND_ABSENT)


def _cle_tri(nom: str):
    """(rang de la pastille, numéro, nom) d'un salon de VA « ─│🟢┤-61-va-＠x »."""
    i = nom.find(f"-va-{AROBASE}")
    tete = nom[:i] if i >= 0 else nom
    j = tete.find(BARRE)
    rond = tete[len(PREFIXE):j] if tete.startswith(PREFIXE) and j > 0 else ""
    rang = ORDRE_RONDS.index(rond) if rond in ORDRE_RONDS else len(ORDRE_RONDS)
    m = re.search(r"-(\d+)$", tete)
    return (rang, int(m.group(1)) if m else 10 ** 6, nom)


def trier_salons(gid: str) -> Dict[str, Any]:
    """Range les salons de VA de chaque catégorie (TRI_SALONS) : pastille,
    puis numéro. Les places déjà occupées par ces salons sont redistribuées
    entre eux (les autres salons ne bougent pas), en UN appel pour tout le
    serveur, et seulement si l'ordre a changé — les positions ne comptent
    pas dans la limite des renommages."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"categories": [], "rates": []}
    if gid not in TRI_SALONS:
        return bilan
    code, salons = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        bilan["rates"].append(f"salons illisibles (HTTP {code})")
        return bilan
    cats = {str(c.get("id")): str(c.get("name") or "") for c in salons
            if isinstance(c, dict) and c.get("type") == 4}
    groupes: Dict[str, List[Dict[str, Any]]] = {}
    for c in salons:
        if (isinstance(c, dict) and c.get("type", 0) == 0
                and str(c.get("parent_id") or "") in cats
                and f"-va-{AROBASE}" in str(c.get("name") or "")
                and str(c.get("name") or "").startswith(PREFIXE)):
            groupes.setdefault(str(c["parent_id"]), []).append(c)
    changes: List[Dict[str, Any]] = []
    for cid, enfants in groupes.items():
        actuel = sorted(enfants, key=_rang)
        voulu = sorted(enfants, key=lambda c: _cle_tri(str(c.get("name") or "")))
        if [str(c["id"]) for c in actuel] == [str(c["id"]) for c in voulu]:
            continue
        places = sorted(int(c.get("position") or 0) for c in enfants)
        if len(set(places)) < len(places):
            # des positions en double (Discord en laisse) : des places neuves,
            # à la suite de la plus basse, plutôt qu'un ordre au hasard
            places = [places[0] + k for k in range(len(places))]
        changes += [{"id": str(c["id"]), "position": pos} for c, pos in zip(voulu, places)]
        bilan["categories"].append(cats[cid])
    if not changes:
        return bilan
    code, rep = _api("PATCH", f"/guilds/{gid}/channels", json=changes)
    if code not in (200, 204):
        bilan["rates"].append(f"ordre refusé (HTTP {code}) {str(rep)[:80]}")
    print(f"[ticket] {gid} : salons triés (pastille, numéro) : {bilan}", flush=True)
    return bilan


def identifiant(gid: str, uid: str) -> str:
    """Le VRAI identifiant Discord : « abdoul_9684 », pas « Abdoul ».

    Le nom affiche se change d'un clic et n'est pas unique : deux « Abdoul »
    auraient eu le meme salon et le meme lien. L'identifiant, lui, ne bouge
    pas — c'est lui qui nomme le salon et le lien du VA.
    """
    code, rep = _api("GET", f"/guilds/{gid}/members/{uid}")
    if code == 200 and isinstance(rep, dict):
        brut = ((rep.get("user") or {}).get("username") or "").strip()
        propre = re.sub(r"[^a-z0-9._-]+", "-", brut.lower()).strip("-")
        if propre:
            return propre[:60]
    return _pseudo(gid, uid)


def _pseudo(gid: str, uid: str) -> str:
    code, rep = _api("GET", f"/guilds/{gid}/members/{uid}")
    if code == 200 and isinstance(rep, dict):
        u = rep.get("user") or {}
        brut = rep.get("nick") or u.get("global_name") or u.get("username") or ""
        propre = re.sub(r"[^a-z0-9._-]+", "-", str(brut).lower()).strip("-")
        if propre:
            return propre[:60]
    return f"membre-{uid[-6:]}"


def role_essai(gid: str) -> str:
    """L'identifiant du rôle « en essai » du serveur, ou « » s'il n'existe pas.

    On ne le CRÉE pas ici : créer un rôle au vol depuis une vérification, c'est
    risquer d'en semer un par serveur inconnu. Absent, on le dit et on continue
    — le salon vaut mieux que rien.
    """
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return ""
    voulu = str(_config().get("role_essai") or ROLE_ESSAI_NOM)
    for r in rep:
        if str(r.get("name") or "").strip() == voulu:
            return str(r["id"])
    return ""


def poser_essai(gid: str, uid: str) -> bool:
    """Met le nouveau en essai. Rend Faux si le rôle manque ou si Discord refuse."""
    rid = role_essai(gid)
    if not rid:
        print(f"[ticket] rôle « {ROLE_ESSAI_NOM} » introuvable sur {gid} : "
              f"{uid} n'est PAS marqué en essai", flush=True)
        return False
    code, rep = _api("PUT", f"/guilds/{gid}/members/{uid}/roles/{rid}")
    if code not in (200, 204):
        print(f"[ticket] essai refusé pour {uid} (HTTP {code}) {str(rep)[:120]}",
              flush=True)
        return False
    return True


def boutons_va(uid: str, confirme: bool = False, a_un_lien: bool = False,
               gid: str = "", lien_actif: bool = True):
    """La rangée de boutons de l'accueil. Seuls les managers peuvent s'en servir.

    Un bouton dont l'action est déjà faite disparaît : laisser « Confirmer »
    sous un VA confirmé invite à un clic qui ne fera rien, et on finit par
    croire que le bouton est cassé.
    """
    rang: List[Dict[str, Any]] = []
    if not confirme:
        rang.append({"type": 2, "style": 3, "label": "Confirmer le VA",
                     "custom_id": f"essai:ok:{uid}", "emoji": {"name": "⭐"}})
    # Chaque serveur a son espace GetMySocial (liens_va.espace) : Twitter dans
    # EMY TWITTER, Threads dans EMY THREADS. Un serveur sans espace n'a pas de
    # bouton, plutot qu'un lien au mauvais endroit.
    try:
        import liens_va as _lv
        lien_possible = (not gid) or str(gid) in _lv.SERVEURS
    except Exception:
        lien_possible = False
    if not a_un_lien and lien_possible:
        rang.append({"type": 2, "style": 1, "label": "Créer son lien",
                     "custom_id": f"lien:new:{uid}", "emoji": {"name": "🔗"}})
    elif a_un_lien:
        # Couper, pas supprimer : le VA peut s'y remettre, son adresse est deja
        # postee sur Twitter, et un lien coupe garde son historique de clics.
        if lien_actif:
            rang.append({"type": 2, "style": 4, "label": "Désactiver le lien",
                         "custom_id": f"lien:off:{uid}", "emoji": {"name": "🚫"}})
        else:
            rang.append({"type": 2, "style": 3, "label": "Réactiver le lien",
                         "custom_id": f"lien:on:{uid}", "emoji": {"name": "✅"}})
    # celui-ci est pour le VA lui-meme, pas pour son manager
    rang.append({"type": 2, "style": 2, "label": "Mon adresse USDC",
                 "custom_id": f"usdc:set:{uid}", "emoji": {"name": "💳"}})
    return [{"type": 1, "components": rang}] if rang else []


# compatibilité : l'ancien nom sert encore dans les rattrapages
def bouton_confirmer(uid: str):
    return boutons_va(uid)


def _differer() -> Dict[str, Any]:
    """« Je m'en occupe » : Discord n'attend que 3 s, la chaîne en prend plus."""
    return {"type": 5, "data": {"flags": 64}}


def _suite(jeton: str, texte: str, p: Optional[Dict[str, Any]] = None) -> None:
    """Complète la réponse différée, visible du seul manager qui a cliqué.

    Sous l'application qui a REÇU le clic (p["application_id"]) : le jeton
    d'interaction est à elle. Un APP_ID en dur répondait au nom de Siri à un
    clic reçu par le bot Threads, et Discord refusait — « réfléchit… » à vie.
    """
    try:
        from verif_discord import app_de_reponse
    except Exception as e:
        print(f"[ticket] réponse différée perdue : {type(e).__name__}: {e}", flush=True)
        return
    _api("PATCH", f"/webhooks/{app_de_reponse(p)}/{jeton}/messages/@original",
         json={"content": texte[:1900]})


def _en_fond(f):
    """Le fil emporte une copie du contexte : un fil neuf part d'un contexte
    vide, et le travail d'un clic sur Threads perdait son serveur courant —
    ses appels seraient partis avec le bot par défaut (Siri)."""
    import contextvars
    import threading
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(f,), daemon=True).start()


_EN_FOND = _en_fond


def _role_nomme(gid: str, nom: str) -> str:
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return ""
    for r in rep:
        if str(r.get("name") or "").strip() == nom:
            return str(r["id"])
    return ""


def role_confirme(gid: str) -> str:
    return _role_nomme(gid, str(_config().get("role_confirme") or ROLE_CONFIRME_NOM))


def confirmer(gid: str, uid: str, par: str = "") -> Dict[str, Any]:
    """Fait passer un VA d'essai à confirmé. Rend {ok, erreur}.

    On POSE d'abord, on RETIRE ensuite : si le retrait échoue, le VA est
    confirmé avec un badge d'essai en trop — visible, rattrapable. L'inverse
    l'aurait laissé sans rien, et personne ne s'en serait aperçu.
    """
    rc = role_confirme(gid)
    if not rc:
        return {"ok": False, "erreur": f"rôle « {ROLE_CONFIRME_NOM} » introuvable sur ce serveur"}
    code, rep = _api("PUT", f"/guilds/{gid}/members/{uid}/roles/{rc}")
    if code not in (200, 204):
        return {"ok": False, "erreur": f"Discord a refusé le rôle (HTTP {code}) "
                                       f"{str(rep.get('message') or '')[:80]}"}
    re_ = role_essai(gid)
    reste_essai = False
    if re_:
        c2, _r = _api("DELETE", f"/guilds/{gid}/members/{uid}/roles/{re_}")
        reste_essai = c2 not in (200, 204)
        if reste_essai:
            print(f"[ticket] {uid} confirmé mais l'essai n'a pas pu être retiré "
                  f"(HTTP {c2})", flush=True)
    with _VERROU:
        etat = _etat()
        fiche = (etat.setdefault("tickets", {})).setdefault(f"{gid}:{uid}", {})
        fiche["essai"] = False
        fiche["confirme"] = {"par": str(par), "quand": int(time.time())}
        _ecrire_etat(etat)
    return {"ok": True, "erreur": "", "reste_essai": reste_essai}


def _ephemere(txt: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": txt, "flags": 64}}


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Le bouton « Confirmer le VA ». Rend None quand ce n'est pas le nôtre."""
    p = p or {}
    if p.get("type") not in (3, 5):
        return None
    cid = str(((p.get("data") or {}).get("custom_id")) or "")
    if p.get("type") == 5:                      # une fenêtre de saisie renvoyée
        return _recevoir_adresse(p)
    if not (cid.startswith("essai:ok:") or cid.startswith("lien:new:")
            or cid.startswith("lien:off:") or cid.startswith("lien:on:")
            or cid.startswith("usdc:set:")):
        return None
    gid = str(p.get("guild_id") or "")
    uid = cid.split(":", 2)[2]
    membre = p.get("member") or {}
    qui = str(((membre.get("user") or {}).get("id")) or "")

    # L'adresse de paiement est la seule chose que le VA remplit lui-même :
    # c'est la SIENNE, et personne d'autre ne doit pouvoir la changer.
    if cid.startswith("usdc:set:"):
        if qui != uid and not _est_manager_brut(gid, membre):
            return _ephemere("Seul ce VA peut renseigner son adresse.")
        return _fenetre_adresse(gid, uid)

    if not _est_manager_brut(gid, membre):
        return _ephemere("Seuls les managers et les helpers peuvent se servir de ces boutons.")

    if cid.startswith("lien:new:"):
        return _creer_lien(gid, uid, qui, p)
    if cid.startswith("lien:off:") or cid.startswith("lien:on:"):
        return _basculer_lien(gid, uid, p, actif=cid.startswith("lien:on:"))

    fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    if fiche.get("confirme"):
        return _ephemere("Ce VA est déjà confirmé.")

    res = confirmer(gid, uid, par=qui)
    if not res["ok"]:
        return _ephemere("✕ " + res["erreur"])

    msg = (p.get("message") or {})
    embeds = msg.get("embeds") or []
    if embeds:
        d = embeds[0].get("description") or ""
        # l'encart perd sa ligne d'essai et garde la trace de qui a tranche
        d = "\n".join(l for l in d.split("\n") if "démarres en essai" not in l)
        embeds[0]["description"] = (d.rstrip() + f"\n\n⭐ **VA confirmé** par <@{qui}>.")
        embeds[0]["color"] = 0x22C55E
    alerte = ("\n⚠️ Le badge 🧪 Essai n'a pas pu être retiré — à enlever à la main."
              if res.get("reste_essai") else "")
    # type 7 : on remplace le message cliqué, le bouton disparaît avec
    # le bouton « Créer son lien » reste : il n'a rien à voir avec l'essai
    import liens_va as _lv
    reste = boutons_va(uid, confirme=True,
                       a_un_lien=bool(_lv.lien_de(gid, uid).get("public_url")), gid=gid)
    return {"type": 7, "data": {"embeds": embeds, "components": reste,
                                "content": (msg.get("content") or "")
                                           + f"\n⭐ Confirmé par <@{qui}>." + alerte,
                                "allowed_mentions": {"parse": []}}}


def _est_manager_brut(gid: str, membre: Dict[str, Any]) -> bool:
    """Administrateur, Manager ou Helper : le Helper a les mêmes boutons."""
    perms = int(str(membre.get("permissions") or "0") or 0)
    if perms & 0x8:
        return True
    roles = membre.get("roles") or []
    rid = role_manager(gid)
    if rid and rid in roles:
        return True
    hid = role_helper(gid)
    return bool(hid and hid in roles)


def _fenetre_adresse(gid: str, uid: str) -> Dict[str, Any]:
    """La fenêtre de saisie : SEVEN ne lit aucun message, c'est sa seule prise."""
    import suivi_va
    deja = suivi_va.adresse_de(gid, uid)
    return {"type": 9, "data": {
        "custom_id": f"usdc:form:{uid}",
        "title": "Ton adresse USDC (réseau Solana)",
        "components": [{"type": 1, "components": [{
            "type": 4, "custom_id": "adresse", "style": 1,
            "label": "Adresse Solana", "min_length": 32, "max_length": 44,
            "required": True, "value": deja,
            "placeholder": "C'est là que tes primes seront envoyées"}]}]}}


def _recevoir_adresse(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La fenêtre revient remplie."""
    import suivi_va
    cid = str(((p.get("data") or {}).get("custom_id")) or "")
    if not cid.startswith("usdc:form:"):
        return None
    gid = str(p.get("guild_id") or "")
    uid = cid.split(":", 2)[2]
    qui = str((((p.get("member") or {}).get("user")) or {}).get("id") or "")
    if qui != uid and not _est_manager_brut(gid, p.get("member") or {}):
        return _ephemere("Seul ce VA peut renseigner son adresse.")
    valeur = ""
    for rang in ((p.get("data") or {}).get("components") or []):
        for champ in (rang.get("components") or []):
            if champ.get("custom_id") == "adresse":
                valeur = str(champ.get("value") or "")
    r = suivi_va.poser_adresse(gid, uid, valeur)
    if not r.get("ok"):
        return _ephemere("✕ " + r["erreur"])
    a = r["adresse"]
    return _ephemere(f"✅ Adresse enregistrée : `{a[:6]}…{a[-4:]}`\n"
                     "Tes primes partiront là-dessus, sans avoir à la redemander.")


def _basculer_lien(gid: str, uid: str, p: Dict[str, Any], actif: bool) -> Dict[str, Any]:
    """Coupe ou remet en service le lien, et retourne le bouton en face."""
    import liens_va
    r = liens_va.basculer(gid, uid, actif)
    if not r.get("ok"):
        return _ephemere("✕ " + str(r.get("erreur") or "échec"))
    fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    _marquer_lien_dans_accueil(gid, uid, str(p.get("channel_id") or ""), actif)
    mot = "remis en service" if actif else "coupé"
    return _ephemere(f'{"✅" if actif else "🚫"} Lien {mot} : {r.get("url") or ""}\n'
                     + ("Ses clics recomptent." if actif else
                        "Il ne renvoie plus personne. Son historique de clics est gardé, "
                        "tu peux le rallumer quand tu veux."))


def _marquer_lien_dans_accueil(gid: str, uid: str, salon: str, actif: bool) -> None:
    """Dit dans l'accueil épinglé que le lien est coupé, et retourne le bouton.

    Le VA doit comprendre pourquoi son lien ne marche plus sans avoir à
    demander : c'est écrit là où il regarde déjà.
    """
    fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    mid = str(fiche.get("accueil") or "")
    if not (mid and salon):
        return
    code, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
    if code != 200:
        print(f"[lien] accueil illisible (HTTP {code}) : etat du lien non affiché",
              flush=True)
        return
    embeds = msg.get("embeds") or [{}]
    d = str(embeds[0].get("description") or "")
    marque = "\n🚫 _Lien coupé par ton manager — il ne renvoie plus personne._"
    d = d.replace(marque, "")
    if not actif:
        d = d.rstrip() + marque
    embeds[0]["description"] = d[:4096]
    _api("PATCH", f"/channels/{salon}/messages/{mid}",
         json={"embeds": embeds,
               "components": boutons_va(uid, confirme=bool(fiche.get("confirme")),
                                        a_un_lien=True, gid=gid, lien_actif=actif)})


# Les créations de lien en cours, par VA (« gid:uid » -> heure du clic). Le
# 17/10/2026 à 02:01, un double clic sur « Créer son lien » (VA 83 de Threads)
# a lancé deux chaînes : « déjà un lien ? » passait deux fois avant que la
# première n'écrive le registre, et GetMySocial a reçu deux liens
# (pearlkittyy, hors registre, dans l'accueil ; babebbyy au registre).
_CREATIONS: Dict[str, float] = {}
_CREATIONS_VERROU = threading.Lock()
# au-delà, une chaîne restée bloquée (réseau) ne prive plus le VA du bouton
CREATION_MAX_S = 600


def _prendre_creation(cle: str) -> float:
    """Réserve la création du lien de ce VA. 0.0 si une autre est en cours."""
    with _CREATIONS_VERROU:
        t0 = _CREATIONS.get(cle)
        if t0 and time.time() - t0 < CREATION_MAX_S:
            return 0.0
        t = time.time()
        _CREATIONS[cle] = t
        return t


def _rendre_creation(cle: str, t: float) -> None:
    # seulement la SIENNE : une réservation expirée puis reprise par un autre
    # clic ne doit pas être libérée par la première chaîne qui finit
    with _CREATIONS_VERROU:
        if _CREATIONS.get(cle) == t:
            _CREATIONS.pop(cle, None)


def _creer_lien(gid: str, uid: str, par: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Le bouton « Créer son lien » : MyPuls puis GetMySocial, en différé.

    Rien n'est créé tant que la configuration manque : MyPuls ne sait pas
    supprimer un tracking link, un lien posé chez la mauvaise modèle resterait
    là pour toujours.

    Une seule création à la fois par VA (_prendre_creation), réservée AVANT
    « déjà un lien ? » et rendue après l'écriture du registre : un second clic
    voit soit la réservation, soit le lien.
    """
    import liens_va
    if str(gid) not in liens_va.SERVEURS:
        return _ephemere("Les liens GetMySocial ne sont pas encore branchés sur ce serveur.")
    cle = f"{gid}:{uid}"
    t = _prendre_creation(cle)
    if not t:
        return _ephemere("⏳ Le lien de ce VA est déjà en cours de création — "
                         "un seul clic suffit, la réponse arrive.")
    lance = False
    try:
        deja = liens_va.lien_de(gid, uid)
        if deja.get("public_url"):
            return _ephemere(f'Ce VA a déjà son lien : {deja["public_url"]}\n'
                             f'(destination : {deja.get("tracking") or "?"})')
        empeche = liens_va.manque(gid)
        if empeche:
            return _ephemere("Rien n'a été créé — " + empeche)
        plateforme = liens_va.espace(gid)["plateforme"]

        jeton = str(p.get("token") or "")
        salon = str(p.get("channel_id") or "")
        pseudo = identifiant(gid, uid)

        def travail():
            try:
                _travail_lien(gid, uid, par, p, jeton, salon, pseudo, plateforme)
            finally:
                _rendre_creation(cle, t)

        _EN_FOND(travail)
        lance = True
        return _differer()
    finally:
        if not lance:
            _rendre_creation(cle, t)


def _travail_lien(gid: str, uid: str, par: str, p: Dict[str, Any], jeton: str,
                  salon: str, pseudo: str, plateforme: str) -> None:
    """La chaîne de « Créer son lien », en fond : le lien, puis la réponse au
    manager et le message au VA."""
    import liens_va
    r = liens_va.creer_pour(gid, uid, pseudo, par=par,
                            manager=nom_manager(gid, uid))
    if r.get("ok"):
        _poser_lien_dans_accueil(gid, uid, salon, r)
        note = ("\n⚠️ Destination provisoire (celle du gabarit) : le tracking "
                "link MyPuls reste à créer et à rattacher."
                if r.get("provisoire") else "")
        rang = f' · rangé dans **{r["groupe"]}**' if r.get("groupe") else ""
        v = r.get("variante") or {}
        # Propriétaire, 15/10/2026 : « arrête de dire tracking pour elle et
        # elle » — ni Emy ni Seren dans les messages. Un 50/50 posé ne se
        # dit plus ; un 50/50 en plan se dit encore, sans nom de modèle
        # (le lien marche, tout part sur un seul tracking en attendant).
        if v and not v.get("ok"):
            ab = ("\n⚠️ Partage A/B pas encore posé : tout part sur un seul tracking "
                  "en attendant."
                  + (" Recolle le cookie GetMySocial (Settings › Intégrations) : il se "
                     "posera tout seul." if v.get("cookie") else " Il sera repris tout seul."))
        else:
            ab = ""
        _suite(jeton, f'✅ VA {r.get("numero")} — lien créé pour <@{uid}> : '
                      f'{r["public_url"]}{rang}{ab}{note}', p)
        if salon:
            _api("POST", f"/channels/{salon}/messages",
                 json={"content": message_lien_va(uid, r["public_url"], plateforme),
                       "allowed_mentions": {"users": [uid]}})
    else:
        sup = f'\n⚠️ Tracking link déjà créé : {r["tracking"]}' if r.get("tracking") else ""
        _suite(jeton, "✕ " + str(r.get("erreur") or "échec") + sup, p)


def message_lien_va(uid: str, url: str, plateforme: str = "Twitter") -> str:
    """Le message qui donne son lien au VA, dans son ticket. Un seul endroit :
    la création et le nettoyage des vieux messages écrivent le même.

    Propriétaire, 15/10/2026 : « juste dire voilà ton lien avec le tracking de
    sub » — ni modèle, ni consigne en plus."""
    # Threads a ses trackings par VA depuis le 15/10/2026 : même message
    if plateforme in ("Twitter", "Threads"):
        return f"🔗 <@{uid}>, voilà ton lien avec ton tracking de subs : {url}"
    return f"🔗 <@{uid}>, voici **ton lien** : {url}\nC'est celui-là que tu mets sur {plateforme}."


def _est_message_de_lien(texte: str) -> bool:
    """Un message du bot qui donnait son lien au VA (tous les libellés qu'il a
    eus : « voici ton lien », « voilà ton lien »)."""
    t = str(texte or "").lower()
    return "getmysocial.com/" in t and ("ton lien" in t or "**ton lien**" in t)


def nettoyer_messages_lien(gid: str, pages: int = 5) -> Dict[str, Any]:
    """Remet le BON lien dans les messages du bot qui en donnaient un, ticket
    par ticket. Rend {corriges, a_jour, rates}.

    Propriétaire, 15/10/2026 : « tu peux clean les liens dans les conv ». Les
    adresses ont été renommées (« emycute » → « bbyy ») : les anciens
    messages menaient à une page morte, ou chez un autre VA. Corrigés plutôt
    que supprimés : le fil du ticket garde sa forme, et rien ne se perd.
    Seuls les messages DU BOT sont touchés — Discord refuse de toute façon
    d'éditer ceux des autres."""
    import liens_va
    gid = str(gid)
    bilan: Dict[str, Any] = {"corriges": [], "a_jour": 0, "rates": []}
    code, moi = _api("GET", "/users/@me")
    bot_id = str((moi or {}).get("id") or "") if code == 200 and isinstance(moi, dict) else ""
    if not bot_id:
        bilan["rates"].append(f"identité du bot illisible (HTTP {code})")
        return bilan
    plateforme = liens_va.espace(gid)["plateforme"]
    tickets = _etat().get("tickets") or {}
    for cle, l in sorted((liens_va._etat().get("liens") or {}).items()):
        if not cle.startswith(f"{gid}:") or not l.get("public_url"):
            continue
        uid = cle.split(":", 1)[1]
        salon = str((tickets.get(cle) or {}).get("salon") or "")
        if not salon:
            bilan["rates"].append(f'{l.get("pseudo")} : pas de salon connu')
            continue
        voulu = message_lien_va(uid, l["public_url"], plateforme)
        avant = ""
        for _ in range(max(1, pages)):
            chemin = f"/channels/{salon}/messages?limit=100" + (f"&before={avant}" if avant else "")
            code, msgs = _api("GET", chemin)
            if code != 200 or not isinstance(msgs, list):
                bilan["rates"].append(f'{l.get("pseudo")} : salon illisible (HTTP {code})')
                break
            for m in msgs:
                if str((m.get("author") or {}).get("id") or "") != bot_id:
                    continue
                if not _est_message_de_lien(m.get("content")):
                    continue
                if m.get("content") == voulu:
                    bilan["a_jour"] += 1
                    continue
                c2, _r = _api("PATCH", f'/channels/{salon}/messages/{m["id"]}',
                              json={"content": voulu, "allowed_mentions": {"parse": []}})
                if c2 == 200:
                    bilan["corriges"].append(f'{l.get("pseudo")} ({m["id"]})')
                else:
                    bilan["rates"].append(f'{l.get("pseudo")} : message {m["id"]} non corrigé (HTTP {c2})')
            if len(msgs) < 100:
                break
            avant = str(msgs[-1].get("id") or "")
    return bilan


def nom_manager(gid: str, uid: str) -> str:
    """« YAZID » : le manager du VA, tel qu'il nomme sa catégorie Discord.

    Le même nom court des deux côtés — la catégorie Discord et le groupe
    GetMySocial. Deux écritures différentes auraient donné deux rangements.
    """
    fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    mid = str(fiche.get("manager") or "")
    if not mid:
        return ""
    code, m = _api("GET", f"/guilds/{gid}/members/{mid}")
    return _nom_court(m) if code == 200 and isinstance(m, dict) else ""


def _poser_lien_dans_accueil(gid: str, uid: str, salon: str, r: Dict[str, Any]) -> None:
    """Écrit le lien DANS l'accueil épinglé, et retire le bouton devenu inutile.

    Un message de plus se serait enfoui sous la conversation en trois jours.
    L'accueil, lui, est épinglé : le VA y retrouve son lien à vie.
    """
    fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    mid = str(fiche.get("accueil") or "")
    if not mid:
        # ticket ouvert avant qu'on garde l'identifiant : on le retrouve parmi
        # les épinglés plutôt que d'abandonner
        code, pins = _api("GET", f"/channels/{salon}/pins")
        items = pins.get("items") if isinstance(pins, dict) else pins
        for x in (items or []):
            m = x.get("message") if isinstance(x, dict) and "message" in x else x
            if str(((m.get("embeds") or [{}])[0].get("title")) or "").startswith("👋"):
                mid = str(m.get("id") or "")
                break
    if not mid:
        print(f"[lien] accueil introuvable dans {salon} : lien non épinglé", flush=True)
        return
    code, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
    if code != 200:
        print(f"[lien] accueil illisible (HTTP {code}) : lien non épinglé", flush=True)
        return
    embeds = msg.get("embeds") or [{}]
    d = str(embeds[0].get("description") or "")
    # on REFAIT le bloc au lieu de l'ajouter seulement s'il manque : un lien
    # rebranché sur son propre tracking link gardait sinon la mention
    # « destination provisoire » alors qu'elle n'était plus vraie
    i = d.find("🔗 **Ton lien**")
    if i >= 0:
        d = d[:i].rstrip()
    plateforme = str(r.get("plateforme") or "Twitter")
    bas = (f'\n\n🔗 **Ton lien** — celui que tu postes sur {plateforme} :\n'
           f'{r["public_url"]}'
           + ("\n_Il compte tes subs pour le podium._" if plateforme == "Twitter" else ""))
    if r.get("provisoire"):
        bas += "\n_(destination provisoire, à rattacher côté MyPuls)_"
    embeds[0]["description"] = (d.rstrip() + bas)[:4096]
    confirme = bool(fiche.get("confirme"))
    _api("PATCH", f"/channels/{salon}/messages/{mid}",
         json={"embeds": embeds,
               "components": boutons_va(uid, confirme=confirme, a_un_lien=True, gid=gid)})


def ouvrir_ticket(uid: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    """Confie le nouveau à un manager et lui ouvre son salon privé.

    Rend l'identifiant du salon, ou « » si rien n'a pu être fait — jamais une
    exception : l'appelant est la fin d'une vérification réussie.
    """
    try:
        if cfg is None:
            from verif_discord import serveur
            cfg = serveur()
        gid = str((cfg or {}).get("id") or "")
        uid = str(uid)
        if not gid or not uid:
            return ""
        permis = set(_config().get("serveurs") or SERVEURS_TICKETS)
        if gid not in permis:
            # on le DIT : un ticket qui ne s'ouvre pas sans un mot dans les
            # journaux passerait pour une panne le jour où on l'attend
            print(f"[ticket] {gid} hors périmètre : aucun salon ouvert pour {uid}",
                  flush=True)
            return ""

        # Déjà un ticket ouvert : on ne le double pas (une deuxième
        # vérification du même membre ne doit pas créer un second salon).
        cle = f"{gid}:{uid}"
        deja = (_etat().get("tickets") or {}).get(cle) or {}
        if deja.get("salon") and _salon_existe(deja["salon"]):
            return str(deja["salon"])

        # avant le salon : s'il rate, le membre est quand même en essai
        en_essai = poser_essai(gid, uid)

        liste = managers(gid)
        choisi = _prochain(gid, liste)
        rid = role_manager(gid)

        parent = categorie_du_manager(gid, choisi) if choisi else ""
        droits = [{"id": gid, "type": 0, "allow": "0", "deny": str(VOIR)},
                  {"id": uid, "type": 1, "allow": str(MEMBRE), "deny": "0"}]
        droits += _droits_staff(rid, role_helper(gid))
        if choisi:
            droits.append({"id": str((choisi.get("user") or {}).get("id")),
                           "type": 1, "allow": str(MANAGER), "deny": "0"})

        corps: Dict[str, Any] = {
            # « ─│🔵┤-va-＠pseudo », le numéro du VA devant sur Threads
            "name": nom_salon_va(gid, uid, identifiant(gid, uid)),
            "type": 0, "permission_overwrites": droits,
            "topic": "Ton espace perso : questions, preuves, bonus. "
                     "Ton manager te répond ici.",
        }
        if parent:
            corps["parent_id"] = parent
        code, rep = _api("POST", f"/guilds/{gid}/channels", json=corps)
        if code != 201 or not rep.get("id"):
            print(f"[ticket] {uid} : création refusée (HTTP {code}) "
                  f"{str(rep)[:160]}", flush=True)
            return ""
        salon = str(rep["id"])

        mid = str((choisi.get("user") or {}).get("id")) if choisi else ""
        qui = f"<@{mid}>" if mid else (f"<@&{rid}>" if rid else "un manager")
        embed = {
            "title": "👋 Bienvenue — voici ton espace perso",
            "color": 0x3B82F6,
            "description": (
                f"<@{uid}>, tu es confié à {qui}.\n\n"
                "**C'est ici que ça se passe :**\n"
                "• tes questions,\n"
                "• tes preuves et tes captures,\n"
                "• la réclamation de tes bonus et de tes quêtes.\n\n"
                + ("🧪 **Tu démarres en essai.** Tout le monde commence là — "
                   "ton manager te dira ce qu'il attend de toi.\n\n" if en_essai else "")
                + "Personne d'autre que toi et les managers ne voit ce salon."),
            "footer": {"text": "YouLab • Ton manager te répond ici"},
        }
        mentions = {"users": [uid] + ([mid] if mid else [])}
        if not mid and rid:
            mentions["roles"] = [rid]
        code_m, rep_m = _api("POST", f"/channels/{salon}/messages",
                             json={"content": f"<@{uid}> {qui}", "embeds": [embed],
                                   "components": boutons_va(uid, confirme=not en_essai,
                                                            gid=gid),
                                   "allowed_mentions": mentions})
        # Épinglé : le VA doit retrouver son accueil et son bouton des semaines
        # plus tard, sans remonter la conversation. Un échec d'épinglage ne
        # doit pas faire rater le ticket — on le dit, et on continue.
        if code_m == 200 and rep_m.get("id"):
            code_p, rep_p = _api("PUT", f'/channels/{salon}/pins/{rep_m["id"]}')
            if code_p not in (200, 204):
                print(f"[ticket] accueil non épinglé dans {salon} (HTTP {code_p}) "
                      f"{str(rep_p)[:100]}", flush=True)

        # Relu ICI, pas repris de la lecture du début : entre les deux,
        # _prochain a avancé le tour de rôle et le suivi des managers a pu
        # réécrire une fiche. Réécrire la vieille copie annulait les deux —
        # le compteur ne bougeait jamais et tous les nouveaux VA tombaient sur
        # le même manager (constaté à la revue du 13/10/2026).
        with _VERROU:
            etat = _etat()
            fiches = etat.setdefault("tickets", {})
            fiches[cle] = {"salon": salon, "manager": mid, "ouvert": int(time.time()),
                           "essai": bool(en_essai),
                           # l'identifiant de l'accueil epingle : c'est LUI qu'on
                           # completera avec le lien, pour que le VA l'ait toujours
                           # sous les yeux au lieu de le chercher dans l'historique
                           "accueil": str(rep_m.get("id") or ""),
                           # ses boutons sont déjà ceux du jour (redessiner_boutons)
                           "boutons": BOUTONS_VERSION}
            _ecrire_etat(etat)
        print(f"[ticket] {uid} -> salon {salon}"
              + (f", manager {mid}" if mid else ", aucun manager trouvé"), flush=True)
        return salon
    except Exception as e:
        print(f"[ticket] {uid} : {type(e).__name__}: {e}", flush=True)
        return ""


def ticket_de(gid: str, uid: str) -> str:
    """Le salon perso d'un membre, ou « » — utilisé par les quêtes."""
    return str(((_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}).get("salon") or "")


# ─── les catégories suivent le rôle Manager ──────────────────────────────
# Une catégorie « Manager X » ne naissait qu'à l'ouverture d'un ticket, et rien
# ne réagissait à un changement de rôle. Le 13/10/2026, Vector a perdu le rôle
# Manager et Spectrum l'a reçu : il a fallu renommer « Manager VECTOR » en
# « Manager SPECTRUM » à la main, et les fiches des VA nommaient encore Vector
# (c'est lui que les alertes « ce VA dort » et la paie auraient mentionné).
# Désormais, toutes les 10 minutes (boucle du podium, web_upload.py) :
#   - un manager parti ET un arrivé : la catégorie du parti est RENOMMÉE au
#     nom de l'arrivé, ses VA restent dedans et passent à lui ;
#   - un arrivé seul : sa catégorie est créée, vide ; le tour de rôle le sert ;
#   - un parti seul : ses VA sont répartis au tour de rôle chez les autres,
#     puis sa catégorie est supprimée — SEULEMENT si elle est vide. Deux
#     exceptions : un VA dont le manager est toujours là (deux catégories
#     pour la même personne) retourne chez lui, et un arrivé qui a déjà sa
#     catégorie reçoit les VA du parti qu'il relève ;
#   - un VA dont le salon est dans la catégorie d'un manager voit sa fiche
#     (tickets.json) et ses droits suivre ce manager — comme son lien
#     GetMySocial le fait déjà (liens_va.synchroniser).
# Aucun salon n'est jamais supprimé. Dans le doute (Discord muet, liste
# incomplète, deux managers au même nom), on ne touche à rien et on le dit.

JOURNAL_FICHIER = DATA_DIR / "managers_auto.json"
# Gestes par tour (renommer, créer, déplacer, supprimer) : un rôle retiré par
# erreur ne doit pas vider une catégorie de 30 VA en une fois. Le reste attend
# le tour suivant, 10 minutes plus tard, et c'est écrit dans le journal.
MAX_CHANGEMENTS = 5
# Fiches remises au manager de leur catégorie, par tour (deux appels de droits
# chacune, sans la limite des renommages).
MAX_REALIGNES = 10
# Après un 429, on laisse Discord tranquille : un renommage de catégorie est
# limité à 2 par 10 minutes, et _http a déjà réessayé plusieurs fois.
PAUSE_LIMITE_S = 600
TOUR_MIN_S = 540
_DITS: Dict[str, str] = {}
_RATES_DITS: Dict[str, float] = {}
REDIRE_RATE_S = 6 * 3600
_PAUSE: Dict[str, float] = {}
_VU_TOUR: Dict[str, float] = {}


class _Limite(Exception):
    """Discord a répondu 429 : la suite du tour attend le suivant."""


def _dire(sujet: str, texte: str) -> None:
    """Un état qui dure se dit UNE fois (sinon toutes les 10 minutes, et plus
    personne ne lit le journal) ; « » l'efface sans bruit, pour qu'une
    rechute se redise."""
    if _DITS.get(sujet, "") != texte:
        _DITS[sujet] = texte
        if texte:
            print(f"[managers] {texte}", flush=True)


def _uid(m: Dict[str, Any]) -> str:
    return str((m.get("user") or {}).get("id") or "")


def _managers_surs(gid: str):
    """(liste_fixe, rid, managers) — managers à None quand on ne SAIT pas.

    managers() rend [] sur une panne, et un balayage à moitié raté y passe
    pour une liste : c'est assez pour confier un ticket, pas pour décider
    qu'un manager est parti. Ici, le moindre doute rend None. Une liste sûre
    remplace aussi le cache d'une heure : le tour de rôle des nouveaux tickets
    ne sert plus un manager parti au-delà du tour suivant."""
    poses = _poses(gid)
    if poses:
        out = _membres_poses(gid, poses, strict=True)
        rid = ""
    else:
        rid = _role_manager_sur(gid)
        if rid is None:
            _dire(f"liste-detail:{gid}", f"{gid} : rôles illisibles")
            return False, "", None
        if not rid:
            return False, "", []
        out = _par_la_liste(gid, rid, strict=True)
        if out is None:
            out = _par_la_recherche(gid, rid, strict=True)
    if out is None:
        return bool(poses), rid, None
    out.sort(key=lambda m: _uid(m))
    if out:
        _CACHE[gid] = {"ts": time.time(), "v": list(out)}
    return bool(poses), rid, out


def _au_tour(gid: str, liste: List[Dict[str, Any]]):
    """Le manager dont c'est le tour, SANS avancer : on n'avance qu'une fois
    le salon réellement déplacé (_tour_fait), sinon un échec sautait quelqu'un."""
    i = int((_etat().get("tours") or {}).get(str(gid)) or 0) % len(liste)
    return i, liste[i]


def _tour_fait(gid: str, i: int, n: int) -> None:
    with _VERROU:
        d = _etat()
        d.setdefault("tours", {})[str(gid)] = (i + 1) % n
        _ecrire_etat(d)


def _journaliser(lignes: List[Dict[str, Any]]) -> None:
    """Chaque geste, gardé sur disque : « pourquoi mon VA a changé de
    catégorie ? » doit avoir sa réponse après un redémarrage."""
    try:
        d = safe_json.load(JOURNAL_FICHIER, default={}) or {}
        if not isinstance(d, dict):
            d = {}
        d["journal"] = ((d.get("journal") or []) + lignes)[-300:]
        safe_json.write(JOURNAL_FICHIER, d)
    except Exception as e:
        print(f"[managers] journal non écrit : {type(e).__name__}: {e}", flush=True)


def _connus(gid: str) -> Optional[set]:
    """Les managers du dernier tour où tout était rangé, ou None (premier tour).

    « Arrivé » ne veut pas dire « sans catégorie » : un VA vérifié entre le
    changement de rôle et le tour suivant (au redémarrage, la boucle dort
    90 s) crée « Manager SPECTRUM » — Spectrum n'était alors plus un arrivé, et
    les VA de Vector partaient chez tout le monde au lieu de passer à lui.
    C'est la liste d'avant, gardée sur disque, qui dit qui vient d'arriver."""
    try:
        d = safe_json.load(JOURNAL_FICHIER, default={}) or {}
        v = ((d.get("connus") or {}) if isinstance(d, dict) else {}).get(str(gid))
        return set(str(x) for x in v) if isinstance(v, list) else None
    except Exception as e:
        print(f"[managers] liste d'avant illisible : {type(e).__name__}: {e}", flush=True)
        return None


def _retenir(gid: str, liste: List[Dict[str, Any]]) -> None:
    """Retient les managers d'un tour où plus aucun VA n'attend chez un parti.

    Pas avant : tant que les VA de Vector passent à Spectrum (5 gestes par
    tour), Spectrum doit rester l'arrivé d'un tour à l'autre."""
    ids = sorted(_uid(m) for m in liste)
    try:
        d = safe_json.load(JOURNAL_FICHIER, default={}) or {}
        if not isinstance(d, dict):
            d = {}
        if (d.get("connus") or {}).get(str(gid)) == ids:
            return
        d.setdefault("connus", {})[str(gid)] = ids
        safe_json.write(JOURNAL_FICHIER, d)
    except Exception as e:
        print(f"[managers] liste des managers non retenue : {type(e).__name__}: {e}",
              flush=True)


def _donner_ticket(gid: str, salon: Dict[str, Any], cle: str, m: Dict[str, Any],
                   fiches: Dict[str, Any]) -> str:
    """Le ticket passe au manager m. Rend « » si c'est fait, sinon pourquoi.

    Les droits redeviennent ceux d'un ticket neuf (ouvrir_ticket) : le
    manager du VA nommé dans le salon. L'ancien perd SA ligne — celle que
    ouvrir_ticket avait posée (droit de gérer les messages), jamais celle du
    VA ni une autre ; le rôle Manager, lui, garde la sienne. La fiche n'est
    écrite qu'une fois Discord d'accord : un échec se reprend au tour suivant
    au lieu de laisser une fiche qui ment."""
    cid = str(salon.get("id"))
    mid = _uid(m)
    avant = str((fiches.get(cle) or {}).get("manager") or "")
    va = cle.split(":", 1)[1]
    lignes = {str(o.get("id")): o for o in (salon.get("permission_overwrites") or [])}
    if mid not in lignes:
        code, rep = _api("PUT", f"/channels/{cid}/permissions/{mid}",
                         json={"type": 1, "allow": str(MANAGER), "deny": "0"})
        if code == 429:
            raise _Limite(f"droits du salon {cid}")
        if code not in (200, 204):
            return f"droits refusés (HTTP {code}) {str(rep)[:80]}"
        salon.setdefault("permission_overwrites", []).append(
            {"id": mid, "type": 1, "allow": str(MANAGER), "deny": "0"})
    if avant == mid:
        # même manager (VA regroupé chez lui) : sa fiche dit déjà vrai, la
        # réécrire aurait laissé un « manager_avant » qui ment
        return ""
    o = lignes.get(avant) or {}
    membre = str(o.get("type", "1")) in ("1", "member")     # pas une ligne de rôle
    try:
        gere = bool(int(str(o.get("allow") or "0")) & GERER_MSG)
    except ValueError:
        gere = False
    if avant and avant not in (mid, va) and o and membre and gere:
        code, rep = _api("DELETE", f"/channels/{cid}/permissions/{avant}")
        if code == 429:
            raise _Limite(f"droits du salon {cid}")
        if code not in (200, 204, 404):
            return f"ancien manager non retiré (HTTP {code}) {str(rep)[:80]}"
        salon["permission_overwrites"] = [x for x in salon.get("permission_overwrites") or []
                                          if str(x.get("id")) != avant]
    with _VERROU:
        d = _etat()
        f = (d.setdefault("tickets", {})).get(cle)
        if not isinstance(f, dict):
            return "fiche disparue de tickets.json"
        f["manager"] = mid
        f["manager_avant"] = avant
        f["reassigne"] = int(time.time())
        _ecrire_etat(d)
    fiches[cle] = dict(f)
    # l'accueil épinglé nomme le manager : sans ça il gardait l'ancien
    # (steave0454 lisait « Roucham », son manager était MOMOBY). Un échec ici
    # ne défait pas la réaffectation : entretenir_accueils le reprend
    try:
        r = corriger_manager_accueil(cid, mid, str(f.get("accueil") or ""))
        if r not in ("fait", "deja"):
            print(f"[managers] {gid} : accueil de {va} pas mis à jour ({r})", flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[managers] {gid} : accueil de {va} : {type(e).__name__}: {e}", flush=True)
    return ""


def suivre_managers(gid: str) -> Dict[str, Any]:
    """Un tour : aligne les catégories « Manager X » sur les managers du jour.

    Rend le bilan : renommees, creees, deplaces, supprimees, realignes,
    reportes, rates, gardees, adoptes (tickets sans fiche, fiche refaite), et
    « ignore » (pourquoi rien n'a été fait)."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"renommees": [], "creees": [], "deplaces": [],
                             "supprimees": [], "realignes": [], "reportes": [],
                             "rates": [], "gardees": [], "adoptes": [], "ignore": ""}
    journal: List[Dict[str, Any]] = []

    def noter(quoi: str, texte: str) -> None:
        bilan[quoi].append(texte)
        if quoi == "reportes":
            return                        # dit en une ligne à la fin du tour
        if quoi == "rates":
            # un refus qui dure (droit manquant…) se redirait toutes les 10 min
            if time.time() - _RATES_DITS.get(texte, 0) < REDIRE_RATE_S:
                return
            _RATES_DITS[texte] = time.time()
        journal.append({"quand": int(time.time()), "serveur": gid,
                        "quoi": quoi, "texte": texte})
        print(f"[managers] {gid} : {texte}", flush=True)

    def ignorer(raison: str, sujet: str) -> Dict[str, Any]:
        bilan["ignore"] = raison
        _dire(f"{sujet}:{gid}", f"{gid} : {raison}")
        return bilan

    cfg = _config()
    if cfg.get("managers_auto") is False:
        return ignorer("suivi des managers coupé (tickets_config.json : managers_auto)",
                       "coupe")
    if gid not in set(str(s) for s in (cfg.get("serveurs") or SERVEURS_TICKETS)):
        bilan["ignore"] = "hors périmètre des tickets"
        return bilan
    code, salons = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        return ignorer(f"salons illisibles (HTTP {code}) : rien touché", "salons")
    _dire(f"salons:{gid}", "")
    cats = [c for c in salons if c.get("type") == 4 and _cle_categorie(c.get("name"))]
    if not cats:
        # ce serveur ne range pas ses VA par manager : rien à suivre, et pas
        # 38 recherches de membres pour rien
        bilan["ignore"] = "aucune catégorie « Manager X » sur ce serveur"
        return bilan

    fixe, rid, liste = _managers_surs(gid)
    if liste is None:
        return ignorer("managers indéterminables (Discord muet ou liste incomplète) : "
                       "rien touché", "liste")
    if not liste:
        return ignorer("aucun manager trouvé : rien touché", "liste")
    _dire(f"liste:{gid}", "")
    _dire(f"liste-detail:{gid}", "")

    try:
        return _suivre(gid, cfg, salons, cats, fixe, rid, liste, bilan, noter, ignorer)
    except _Limite as e:
        _PAUSE[gid] = time.time() + PAUSE_LIMITE_S
        noter("rates", f"Discord limite le débit ({e}) : la suite attend le prochain tour")
        return bilan
    finally:
        if bilan["reportes"]:
            print(f"[managers] {gid} : {len(bilan['reportes'])} geste(s) reporté(s) "
                  f"au prochain tour : " + " · ".join(bilan["reportes"][:8]), flush=True)
        if journal:
            _journaliser(journal)


def _suivre(gid, cfg, salons, cats, fixe, rid, liste, bilan, noter, ignorer):
    fiches = {k: dict(v) for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict)}
    salon_fiche = {str(f.get("salon")): k for k, f in fiches.items() if f.get("salon")}

    def enfants(cat_id: str) -> List[Dict[str, Any]]:
        return sorted((c for c in salons if str(c.get("parent_id") or "") == str(cat_id)),
                      key=_rang)

    def suivis(cat_id: str) -> List[Dict[str, Any]]:
        return [c for c in enfants(cat_id) if str(c.get("id")) in salon_fiche]

    def candidats(cat: Dict[str, Any]) -> set:
        """Les managers que les fiches donnent aux VA de cette catégorie."""
        return {str(fiches[salon_fiche[str(c["id"])]].get("manager") or "")
                for c in suivis(str(cat["id"]))} - {""}

    def a_nous(c: Dict[str, Any]) -> bool:
        """Au format exact des tickets, ou des VA dedans. Une catégorie qui
        dit « Manager » sans être l'une des nôtres (« 🛡️┤ Manager STAFF ├🛡️ »,
        salons d'équipe) ne doit être ni renommée ni supprimée."""
        n = str(c.get("name") or "")
        return ((n.startswith(f"🔵{BARRE} Manager ") and n.endswith(" ├🔵"))
                or bool(suivis(str(c["id"]))))

    def analyser():
        noms: Dict[str, List[Dict[str, Any]]] = {}
        for m in liste:
            noms.setdefault(_nom_court(m), []).append(m)
        prises = {_cle_categorie(c.get("name")) for c in cats}
        orphelines = []
        for c in sorted(cats, key=_rang):
            if _cle_categorie(c.get("name")) in noms:
                continue
            if a_nous(c):
                orphelines.append(c)
            else:
                _dire(f"etrangere:{gid}:{c.get('id')}",
                      f"{gid} : « {c.get('name')} » ignorée — ni au format des tickets "
                      "ni de VA dedans")
        nouveaux = [m for m in liste if _nom_court(m) not in prises]
        return noms, orphelines, nouveaux

    noms, orphelines, nouveaux = analyser()

    # Un manager porte encore le rôle mais la recherche l'a manqué ? Les fiches
    # des VA de sa catégorie le nomment : on le vérifie par son identifiant
    # AVANT de le croire parti. Une liste fixe, elle, fait foi telle quelle.
    if orphelines and not fixe:
        connus = {_uid(m) for m in liste}
        retrouves = False
        for o in orphelines:
            for mid in sorted(candidats(o) - connus):
                code, m = _api("GET", f"/guilds/{gid}/members/{mid}")
                if code == 200 and isinstance(m, dict):
                    if rid in (m.get("roles") or []):
                        _dire(f"manque:{gid}:{mid}", f"{gid} : {mid} porte le rôle Manager "
                                                     "mais la recherche l'avait manqué — gardé")
                        liste.append(m)
                        connus.add(mid)
                        retrouves = True
                elif code != 404:
                    return ignorer(f"manager {mid} de « {o.get('name')} » illisible "
                                   f"(HTTP {code}) : rien touché", "verif")
        if retrouves:
            liste.sort(key=lambda m: _uid(m))
            _CACHE[gid] = {"ts": time.time(), "v": list(liste)}
            noms, orphelines, nouveaux = analyser()
    _dire(f"verif:{gid}", "")

    doubles = {n: ms for n, ms in noms.items() if len(ms) > 1}
    if doubles:
        # Deux managers, un seul nom de catégorie : à qui iraient les VA ? On
        # ne devine pas — un surnom qui les distingue débloque tout.
        txt = " ; ".join(f"{n} ({', '.join(_uid(m) for m in ms)})"
                         for n, ms in sorted(doubles.items()))
        return ignorer(f"deux managers au même nom : {txt} — rien touché", "doubles")
    _dire(f"doubles:{gid}", "")
    unique = {n: ms[0] for n, ms in noms.items()}

    # Les paires parti -> arrivé. D'abord par la personne : une catégorie dont
    # les fiches nomment l'arrivé est la sienne (il a changé de surnom). Puis
    # dans l'ordre : catégories par position, managers par identifiant.
    paires = []
    restent_o, restent_n = list(orphelines), list(nouveaux)
    for o in list(restent_o):
        c = candidats(o)
        n = next((m for m in restent_n if _uid(m) in c), None)
        if n is not None:
            paires.append((o, n))
            restent_o.remove(o)
            restent_n.remove(n)
    while restent_o and restent_n:
        paires.append((restent_o.pop(0), restent_n.pop(0)))

    # Un arrivé qui a DÉJÀ sa catégorie (un ticket l'a créée avant ce tour) :
    # pas de renommage possible, mais les VA du parti passent quand même à
    # lui — déplacés dans sa catégorie — au lieu d'aller au tour de rôle.
    deja_vus = _connus(gid)
    prises = {_cle_categorie(c.get("name")) for c in cats}
    arrives = [m for m in liste if deja_vus is not None and _uid(m) not in deja_vus
               and _nom_court(m) in prises]
    releve: Dict[str, Dict[str, Any]] = {}
    for o in restent_o:
        if not arrives:
            break
        if suivis(str(o["id"])):
            releve[str(o["id"])] = arrives.pop(0)

    reste = int(cfg.get("managers_auto_max") or MAX_CHANGEMENTS)

    def ajouter_categorie(m: Dict[str, Any]) -> str:
        code, cid = _creer_categorie(gid, m, rid if rid else None)
        if code == 429:
            raise _Limite(f"création de « {nom_categorie(m)} »")
        if not cid:
            noter("rates", f"« {nom_categorie(m)} » non créée (HTTP {code})")
            return ""
        c = {"id": cid, "type": 4, "name": nom_categorie(m), "position": 10 ** 6}
        salons.append(c)
        cats.append(c)
        noter("creees", f"« {c['name']} » créée pour {_uid(m)}")
        return cid

    # 1. parti + arrivé : on renomme, les VA restent dedans
    for o, m in paires:
        avant, voulu = str(o.get("name")), nom_categorie(m)
        if reste <= 0:
            noter("reportes", f"renommer « {avant} » en « {voulu} »")
            continue
        code, rep = _api("PATCH", f"/channels/{o['id']}", json={"name": voulu})
        if code == 429:
            raise _Limite(f"renommage de « {avant} »")
        if code != 200:
            noter("rates", f"renommage de « {avant} » refusé (HTTP {code}) {str(rep)[:80]}")
            continue
        o["name"] = voulu
        reste -= 1
        noter("renommees", f"« {avant} » → « {voulu} » : ses {len(suivis(str(o['id'])))} "
                           f"VA passent à {_uid(m)}")

    # 2. arrivé sans catégorie à reprendre : la sienne, vide
    for m in restent_n:
        if reste <= 0:
            noter("reportes", f"créer « {nom_categorie(m)} »")
            continue
        if ajouter_categorie(m):
            reste -= 1

    # 3. parti sans catégorie à reprendre : chaque VA s'en va, puis la
    #    catégorie vide. Où il va, dans cet ordre :
    #    a. son manager (sa fiche) est toujours là, avec SA catégorie : chez
    #       lui. Sans ça (revue du 13/10) : Yazid devient « Zed », le
    #       renommage prend un 429, un ticket ouvert pendant la pause crée
    #       « Manager ZED » — et au tour suivant les VA de Yazid, toujours
    #       manager, partaient chez Moan et Spectrum ;
    #    b. un arrivé qui avait déjà sa catégorie relève ce parti : chez lui ;
    #    c. sinon le tour de rôle.
    cibles = list(liste)
    par_uid = {_uid(m): m for m in liste}
    for o in restent_o:
        oid = str(o["id"])
        for c in suivis(oid):
            if reste <= 0:
                noter("reportes", f"déplacer « {c.get('name')} » hors de « {o.get('name')} »")
                continue
            cle = salon_fiche[str(c["id"])]
            i = None
            m = par_uid.get(str(fiches[cle].get("manager") or ""))
            if m is not None:
                dest = _categorie_de(cats, m)
                if not dest or dest == oid:
                    # sa catégorie est à créer (reportée, ou refusée) : on
                    # attend qu'elle existe plutôt que de le confier à un autre
                    noter("reportes", f"« {c.get('name')} » attend « {nom_categorie(m)} »")
                    continue
                pourquoi = "son manager, sous son nom du jour"
            elif oid in releve:
                m = releve[oid]
                dest = _categorie_de(cats, m)
                pourquoi = "l'arrivé qui relève ce manager"
            else:
                i, m = _au_tour(gid, cibles)
                dest = _categorie_de(cats, m)
                pourquoi = "tour de rôle"
            if not dest:
                if reste < 2:
                    noter("reportes", f"créer « {nom_categorie(m)} » puis y déplacer "
                                      f"« {c.get('name')} »")
                    continue
                dest = ajouter_categorie(m)
                if not dest:
                    continue
                reste -= 1
            # parent seul, sans lock_permissions : le salon garde SES droits,
            # comme un ticket neuf (ouvrir_ticket ne les synchronise pas sur
            # la catégorie) ; _donner_ticket y change ensuite le manager
            code, rep = _api("PATCH", f"/channels/{c['id']}", json={"parent_id": dest})
            if code == 429:
                raise _Limite(f"déplacement de « {c.get('name')} »")
            if code != 200:
                noter("rates", f"« {c.get('name')} » non déplacé (HTTP {code}) {str(rep)[:80]}")
                continue
            c["parent_id"] = dest
            reste -= 1
            if i is not None:
                # le tour de rôle n'avance que s'il a servi, et une fois le
                # salon réellement déplacé
                _tour_fait(gid, i, len(cibles))
            noter("deplaces", f"« {c.get('name')} » : « {o.get('name')} » → "
                              f"« {nom_categorie(m)} » ({pourquoi})")
            pb = _donner_ticket(gid, c, cle, m, fiches)
            if pb:
                noter("rates", f"« {c.get('name')} » déplacé, mais {pb} — repris au prochain tour")

        restants = enfants(oid)
        if restants:
            if not suivis(oid):
                # des salons que tickets.json ne connaît pas : on ne devine
                # pas à qui ils vont, la catégorie reste et on le dit
                txt = ", ".join(str(c.get("name")) for c in restants[:6])
                _dire(f"gardee:{gid}:{oid}",
                      f"{gid} : « {o.get('name')} » gardée — {len(restants)} salon(s) "
                      f"hors tickets dedans ({txt}) : à ranger à la main")
                bilan["gardees"].append(str(o.get("name")))
            continue
        if reste <= 0:
            noter("reportes", f"supprimer « {o.get('name')} », vide")
            continue
        # relu juste avant : un ticket ouvert entre-temps dedans la sauve
        code, frais = _api("GET", f"/guilds/{gid}/channels")
        if code != 200 or not isinstance(frais, list):
            noter("rates", f"« {o.get('name')} » non supprimée : salons illisibles (HTTP {code})")
            continue
        dedans = [c for c in frais if str(c.get("parent_id") or "") == oid]
        if dedans:
            noter("rates", f"« {o.get('name')} » non supprimée : {len(dedans)} salon(s) "
                           "arrivé(s) dedans entre-temps")
            continue
        code, rep = _api("DELETE", f"/channels/{oid}")
        if code == 429:
            raise _Limite(f"suppression de « {o.get('name')} »")
        if code in (200, 204):
            reste -= 1
            salons[:] = [c for c in salons if str(c.get("id")) != oid]
            cats[:] = [c for c in cats if str(c.get("id")) != oid]
            _dire(f"gardee:{gid}:{oid}", "")
            noter("supprimees", f"« {o.get('name')} » supprimée (vide)")
        else:
            noter("rates", f"« {o.get('name')} » non supprimée (HTTP {code}) {str(rep)[:80]}")

    def _gere(o: Dict[str, Any]) -> bool:
        """La ligne d'un manager : « gérer les messages » (MANAGER), pas un VA."""
        try:
            return bool(int(str(o.get("allow") or "0")) & GERER_MSG)
        except ValueError:
            return False

    # 3 bis. un ticket que tickets.json ne connaît pas, rangé chez un manager
    #    du jour : sa fiche est refaite d'après ses droits, puis l'étape 4 le
    #    traite comme les autres. Constaté le 13/10/2026 sur Va Twitter : deux
    #    des trois tickets de « Manager SPECTRUM » (repris de Vector) n'avaient
    #    pas de fiche — Vector y gardait sa ligne, Spectrum n'y avait pas la
    #    sienne, et rien ne le disait. On ne devine rien : un salon au nom d'un
    #    ticket, UN SEUL membre aux droits d'un VA (sans « gérer les
    #    messages »), et ce membre sans autre ticket connu. Sinon, dit et laissé.
    for cat in sorted(cats, key=_rang):
        if not unique.get(_cle_categorie(cat.get("name"))):
            continue
        for c in enfants(str(cat["id"])):
            cid = str(c.get("id"))
            if (cid in salon_fiche or c.get("type", 0) != 0
                    or f"-va-{AROBASE}" not in str(c.get("name") or "")):
                continue
            membres = [o for o in (c.get("permission_overwrites") or [])
                       if str(o.get("type", "1")) in ("1", "member")]
            vas = [str(o.get("id")) for o in membres if not _gere(o)]
            chefs = [str(o.get("id")) for o in membres if _gere(o)]
            if len(vas) != 1:
                _dire(f"sansfiche:{gid}:{cid}",
                      f"{gid} : « {c.get('name')} » sans fiche dans tickets.json et "
                      f"{len(vas)} membre(s) aux droits d'un VA : à ranger à la main")
                continue
            cle = f"{gid}:{vas[0]}"
            with _VERROU:
                d = _etat()
                tk = d.setdefault("tickets", {})
                f = tk.get(cle) if isinstance(tk.get(cle), dict) else {}
                if f.get("salon") and str(f.get("salon")) != cid:
                    _dire(f"sansfiche:{gid}:{cid}",
                          f"{gid} : « {c.get('name')} » sans fiche, mais {vas[0]} a déjà "
                          f"le ticket {f.get('salon')} : à ranger à la main")
                    continue
                # l'ancien manager : la ligne « gérer les messages » que
                # ouvrir_ticket avait posée, s'il n'y en a qu'une ; l'étape 4
                # la retire en donnant le ticket au manager de la catégorie
                f = dict(f, salon=cid, manager=chefs[0] if len(chefs) == 1 else "",
                         adopte=int(time.time()))
                tk[cle] = f
                _ecrire_etat(d)
            _dire(f"sansfiche:{gid}:{cid}", "")
            fiches[cle] = dict(f)
            salon_fiche[cid] = cle
            noter("adoptes", f"« {c.get('name')} » : fiche refaite pour {vas[0]} "
                             f"(manager d'avant : {f['manager'] or 'aucun'})")

    # 4. chaque VA rangé chez un manager a ce manager dans sa fiche et ses droits
    reste_r = int(cfg.get("managers_auto_realignes") or MAX_REALIGNES)
    for cat in sorted(cats, key=_rang):
        m = unique.get(_cle_categorie(cat.get("name")))
        if not m:
            continue
        for c in suivis(str(cat["id"])):
            cle = salon_fiche[str(c["id"])]
            if str(fiches[cle].get("manager") or "") == _uid(m):
                continue
            if reste_r <= 0:
                noter("reportes", f"fiche de « {c.get('name')} » → {_uid(m)}")
                continue
            avant = str(fiches[cle].get("manager") or "") or "personne"
            pb = _donner_ticket(gid, c, cle, m, fiches)
            reste_r -= 1
            if pb:
                noter("rates", f"« {c.get('name')} » : {pb}")
            else:
                noter("realignes", f"« {c.get('name')} » : manager {avant} → {_uid(m)} "
                                   f"(catégorie « {cat.get('name')} »)")

    # 5. plus un VA chez un parti : cette liste devient « celle d'avant » du
    #    prochain changement de rôle (voir _connus)
    _n, orph_fin, _a = analyser()
    if not any(suivis(str(o["id"])) for o in orph_fin):
        _retenir(gid, liste)
    return bilan


#: Au plus tant de tickets ouverts par passage pour des Vérifiés posés à la
#: main : une erreur de rôle sur cinquante membres ne doit pas ouvrir
#: cinquante salons d'un coup — le reste attend le passage suivant.
MAX_TICKETS_VERIFIES = 5


def _fichier_verifies() -> Path:
    # relu à chaque appel : les tests déplacent ETAT_FICHIER
    return ETAT_FICHIER.parent / "verifies_connus.json"


def ouvrir_tickets_verifies(gid: str) -> Dict[str, Any]:
    """Un ticket pour chaque NOUVEAU Vérifié du serveur, même posé à la main.

    Propriétaire, 13/10/2026 : « quand je mets quelqu'un en Vérifié, ça doit
    lui ouvrir un ticket automatiquement ». Jusque-là, seul le parcours de
    vérification du bot ouvrait le salon (verif_discord._ouvrir) : un rôle posé
    à la main dans Discord ne donnait rien. Bowser et Luigi ne reçoivent pas
    les événements de Discord : la liste des Vérifiés est relue à chaque tour.

    « Nouveau » : absent de la liste du passage précédent. Au tout premier
    passage, les Vérifiés déjà là sont NOTÉS, pas servis — sans ça, chaque
    ancien membre aurait reçu un ticket d'un coup. Un staff (Manager, Helper)
    n'en reçoit pas. Un Vérifié qui a déjà son ticket n'en reçoit pas un
    second (ouvrir_ticket le rend tel quel). Liste illisible : rien n'est
    touché, et c'est dit."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"ouverts": [], "deja": [], "staff": [], "rates": [], "ignore": ""}
    try:
        from verif_discord import serveur
        cfg = serveur(gid)
    except Exception:                                        # noqa: BLE001
        cfg = None
    rid = str((cfg or {}).get("role_verifie") or "")
    if not cfg or not rid:
        bilan["ignore"] = "pas de rôle Vérifié connu"
        return bilan
    membres = _par_la_liste(gid, rid, strict=True)
    if membres is None:
        bilan["ignore"] = "liste des membres illisible"
        _dire(f"verifies:{gid}", f"{gid} : liste des Vérifiés illisible — pas de ticket "
                                  "automatique ce tour-ci")
        return bilan
    _dire(f"verifies:{gid}", "")
    actuels = {str((m.get("user") or {}).get("id")): m for m in membres
               if not (m.get("user") or {}).get("bot") and (m.get("user") or {}).get("id")}
    with _VERROU:
        tout = safe_json.load(_fichier_verifies(), default={}) or {}
    if not isinstance(tout, dict):
        tout = {}
    if gid not in tout:
        tout[gid] = sorted(actuels)
        safe_json.write(_fichier_verifies(), tout)
        print(f"[ticket] {gid} : {len(actuels)} Vérifié(s) déjà là, notés — les "
              "suivants auront leur ticket tout seuls", flush=True)
        bilan["ignore"] = "premier passage : liste notée"
        return bilan
    connus = set(str(x) for x in tout.get(gid) or [])
    staff = {str(r) for r in (cfg.get("role_manager"), role_helper(gid)) if r}
    traites = set()
    for uid in sorted(set(actuels) - connus):
        m = actuels[uid]
        if staff & set(str(r) for r in (m.get("roles") or [])):
            bilan["staff"].append(uid)
            traites.add(uid)
            continue
        if len(bilan["ouverts"]) >= MAX_TICKETS_VERIFIES:
            break                          # la suite au passage suivant
        fiche = (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
        avait = str(fiche.get("salon") or "")
        salon = ouvrir_ticket(uid, cfg)
        if not salon:
            bilan["rates"].append(uid)     # retenté au passage suivant
            continue
        traites.add(uid)
        (bilan["deja"] if salon == avait else bilan["ouverts"]).append(uid)
    # ceux qui ne sont plus Vérifiés sortent de la liste : reposé plus tard, le
    # rôle leur rouvrira (ou leur rendra) leur salon
    tout[gid] = sorted((connus & set(actuels)) | traites)
    safe_json.write(_fichier_verifies(), tout)
    if bilan["ouverts"] or bilan["rates"]:
        print(f"[ticket] {gid} : Vérifiés posés à la main : {bilan}", flush=True)
    return bilan


def suivre_partout() -> Dict[str, Any]:
    """Un tour sur chaque serveur à tickets, chacun sous SON bot.

    Ne lève jamais : l'appelant est la boucle du podium, qu'une erreur ici ne
    doit pas arrêter."""
    out: Dict[str, Any] = {}
    try:
        from verif_discord import sur_serveur
        permis = sorted(set(str(s) for s in (_config().get("serveurs") or SERVEURS_TICKETS)))
    except Exception as e:
        _dire("partout", f"suivi des managers indisponible : {type(e).__name__}: {e}")
        return out
    for gid in permis:
        maintenant = time.time()
        if maintenant < _PAUSE.get(gid, 0):
            continue
        if maintenant - _VU_TOUR.get(gid, 0) < TOUR_MIN_S:
            continue
        _VU_TOUR[gid] = maintenant
        try:
            with sur_serveur(gid):
                out[gid] = suivre_managers(gid)
        except Exception as e:
            print(f"[managers] {gid} : {type(e).__name__}: {e}", flush=True)
        # À part : un Helper sans ses salons ne doit pas attendre qu'un tour
        # des managers réussisse, ni le faire échouer.
        try:
            with sur_serveur(gid):
                aligner_helper(gid)
        except Exception as e:
            print(f"[helper] {gid} : {type(e).__name__}: {e}", flush=True)
        # Un Vérifié posé à la main reçoit son ticket, comme au bout du parcours
        try:
            with sur_serveur(gid):
                ouvrir_tickets_verifies(gid)
        except Exception as e:
            print(f"[ticket] {gid} : Vérifiés : {type(e).__name__}: {e}", flush=True)
        # une fois l'heure : qui est parti, qui est revenu
        if maintenant - _DEPARTS_VU.get(gid, 0) >= DEPARTS_S:
            _DEPARTS_VU[gid] = maintenant
            try:
                with sur_serveur(gid):
                    suivre_departs(gid)
            except Exception as e:
                print(f"[ticket] {gid} : départs : {type(e).__name__}: {e}", flush=True)
        # une fois par jour : salons supprimés, manager et épingle des accueils
        if maintenant - _ENTRETIEN_VU.get(gid, 0) >= ENTRETIEN_S:
            _ENTRETIEN_VU[gid] = maintenant
            try:
                with sur_serveur(gid):
                    entretenir_accueils(gid)
            except Exception as e:
                print(f"[ticket] {gid} : accueils : {type(e).__name__}: {e}", flush=True)
        _synchro_liens(gid, sur_serveur)
        _couper_seren(gid)
        # 🧪 / 🌱 / ⭐ posés à la main dans Discord : la fiche et le menu suivent
        if gid in NIVEAUX_ICI:
            try:
                with sur_serveur(gid):
                    synchroniser_niveaux(gid)
            except Exception as e:
                print(f"[ticket] {gid} : niveaux : {type(e).__name__}: {e}", flush=True)
        # une fois l'heure, le menu en bas de chaque ticket — en fond : plus
        # de soixante tickets espacés d'une seconde arrêteraient le podium
        if gid in MENUS_HEURE_ICI and maintenant - _MENUS_VU.get(gid, 0) >= MENUS_HEURE_S:
            _MENUS_VU[gid] = maintenant
            with sur_serveur(gid):
                _en_fond(lambda g=gid: ramener_menus(g))
        # Agency VA INSTAGRAM : arrivées, départs et parrainage ne passent
        # plus ici mais par le fil d'agency_accueil, chaque minute — le
        # parrain se lit à la différence d'usage des invitations, et dix
        # minutes entre deux relevés mélangeaient les arrivées.
    # Va IG n'a pas de tickets ici (bot principal), mais ses VA partis gardaient
    # leurs liens en service : coupés une fois l'heure (liens_fr.couper_partis)
    if time.time() - _DEPARTS_VU.get("va_ig", 0) >= DEPARTS_S:
        _DEPARTS_VU["va_ig"] = time.time()
        try:
            import liens_fr
            liens_fr.couper_partis()
        except Exception as e:
            print(f"[liens_fr] VA partis de Va IG : {type(e).__name__}: {e}", flush=True)
    return out


# Les liens GetMySocial suivent les catégories (liens_va.synchroniser) : pour
# Twitter, la boucle du podium s'en charge (web_upload._sync_liens_va) ; Threads
# n'y passe pas (podium seul), alors c'est ici, juste après le rangement des VA
# qu'elle doit suivre. Pas les deux pour un même serveur : l'outil GetMySocial
# est limité en débit.
SYNCHRO_LIENS_ICI = {"1498948161039896586"}      # YouLab THREADS
SYNCHRO_LIENS_S = 1800
_SYNCHRO_VUE: Dict[str, float] = {}
_SEREN_VUE: Dict[str, float] = {}


def _couper_seren(gid: str) -> None:
    """Seren en pause (liens_va.SEREN_EN_PAUSE, 21/10/2026) : les 50/50 encore
    allumés de Twitter ET de Threads s'éteignent, toutes les 30 minutes. Pas
    dans _synchro_liens : Twitter n'y passe pas (web_upload._sync_liens_va, que
    des patchs du VPS réécrivent). En fond : une liste de liens et quelques
    appels par lien ne doivent pas retenir le tour des tickets."""
    try:
        import liens_va
        if str(gid) not in liens_va.SERVEURS:
            return
        en_pause = bool(getattr(liens_va, "SEREN_EN_PAUSE", False))
    except Exception:                                        # noqa: BLE001
        return
    if time.time() - _SEREN_VUE.get(gid, 0) < SYNCHRO_LIENS_S:
        return
    _SEREN_VUE[gid] = time.time()

    def _fond():
        if not en_pause:
            # Pause levée (24/10/2026) : les fiches coupées repassent « à
            # poser » ; reprendre_variantes (boucle du podium) refait leur
            # 50/50 vers leur tracking Seren d'avant. Rien à faire une fois
            # toutes reprises. Occupé (une reprise tourne) : au tour suivant.
            try:
                r = liens_va.remettre_seren(gid)
                if r.get("a_reposer") or r.get("occupe"):
                    _SEREN_VUE[gid] = 0 if r.get("occupe") else _SEREN_VUE[gid]
                    print(f"[lien] Seren revient {gid} : {r}", flush=True)
            except Exception as e:                           # noqa: BLE001
                print(f"[lien] Seren revient {gid} : {type(e).__name__}: {e}", flush=True)
            return
        try:
            b = liens_va.couper_seren(gid)
            if b.get("coupes") or b.get("rates"):
                print(f"[lien] Seren en pause {gid} : {len(b['coupes'])} 50/50 éteint(s) "
                      f"{b['coupes'][:40]}, ratés {b['rates'][:5]}", flush=True)
        except Exception as e:                               # noqa: BLE001
            print(f"[lien] Seren en pause {gid} : {type(e).__name__}: {e}", flush=True)
    threading.Thread(target=_fond, daemon=True).start()


def _synchro_liens(gid: str, sur_serveur) -> None:
    if gid not in SYNCHRO_LIENS_ICI:
        return
    if time.time() - _SYNCHRO_VUE.get(gid, 0) < SYNCHRO_LIENS_S:
        return
    _SYNCHRO_VUE[gid] = time.time()
    try:
        import liens_va
        with sur_serveur(gid):
            numeroter_salons(gid)
            trier_salons(gid)
            redessiner_boutons(gid)
            b = liens_va.synchroniser(gid)
        if any(b.get(k) for k in ("groupes_crees", "deplaces", "rates", "groupes_supprimes",
                                  "sortis")):
            print(f"[lien] synchro {gid} : {b}", flush=True)
        # Threads a ses trackings par VA depuis le 15/10/2026 : les liens d'avant
        # reçoivent les leurs (Emy, puis Seren et le 50/50), en fond comme sur
        # Twitter (web_upload._sync_liens_va)
        if liens_va.espace(gid).get("variante") and liens_va.en_attente(gid):
            def _variantes():
                try:
                    bv = liens_va.reprendre_variantes(gid)
                    if bv.get("poses") or bv.get("rates") or bv.get("a_verifier"):
                        print(f"[lien] 50/50 {gid} : {len(bv['poses'])} pose(s), rates "
                              f"{bv['rates'][:5]}, a verifier {bv['a_verifier'][:5]}", flush=True)
                except Exception as e:                       # noqa: BLE001
                    print(f"[lien] 50/50 {gid} : {type(e).__name__}: {e}", flush=True)
            threading.Thread(target=_variantes, daemon=True).start()
    except Exception as e:
        print(f"[lien] synchro {gid} : {type(e).__name__}: {e}", flush=True)


# Les accueils ouverts AVANT que Threads ait ses liens (13/10/2026) n'ont pas
# « Créer son lien » : boutons_va ne le mettait pas hors de Twitter. Sans ce
# rattrapage, ces VA restaient sans bouton pour toujours. Une fois par accueil
# (« boutons » dans la fiche), pas à chaque tour.
# 3 (15/10/2026) : « 📈 Mes subs » rejoint la rangée sur Twitter et Threads
# (bouton posé par un patch local du VPS, 99-z-tickets-subs-total) : les
# accueils déjà postés sont redessinés une fois pour le montrer.
# 4 (21/10/2026) : « 📈 Mes subs » devient « 📈 Mes stats » sur Threads
# (_avec_mes_stats) : ses accueils déjà postés sont redessinés une fois.
# 5 (21/10/2026) : sur Twitter aussi.
# 6 (23/10/2026) : « 📱 Numéro » en dernier, sur les trois serveurs
# (NUMERO_DANS_MENU).
# 7 (23/10/2026) : « 📧 Outlook » juste après, sur Twitter seulement.
# 8 (23/10/2026) : deux rangées, celle du VA puis celle des managers
# (_deux_rangees, maquette validée).
# 9 (24/10/2026) : « 🌱 Passer Débutant » à la place de « Confirmer » pour un VA
# encore en essai (NIVEAUX_ICI).
# 10 (30/10/2026) : « 📤 Spoofer » et « ⬇️ Download » dans la rangée du VA, sur
# TRUST INSTAGRAM seulement (OUTILS_DANS_MENU, outils_tickets).
# 11 (30/10/2026) : « 🎬 Contenu » sur une 2e rangée du VA, TRUST INSTAGRAM
# seulement (CONTENU_DANS_MENU, contenu_tickets).
BOUTONS_VERSION = 11


def redessiner_boutons(gid: str) -> Dict[str, Any]:
    """Remet la rangée de boutons à jour sous chaque accueil de ce serveur."""
    import liens_va as lv
    gid = str(gid)
    bilan: Dict[str, Any] = {"faits": [], "sans_accueil": [], "rates": []}
    fiches = {k: dict(v) for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict)}
    finis = []
    for cle, f in fiches.items():
        if int(f.get("boutons") or 0) >= BOUTONS_VERSION:
            continue
        uid = cle.split(":", 1)[1]
        salon, mid = str(f.get("salon") or ""), str(f.get("accueil") or "")
        if not (salon and mid):
            bilan["sans_accueil"].append(uid)       # dit une fois, pas à chaque tour
            finis.append(cle)
            continue
        lien = lv.lien_de(gid, uid)
        rang = boutons_va(uid, confirme=bool(f.get("confirme")),
                          a_un_lien=bool(lien.get("public_url")), gid=gid,
                          lien_actif=lv.est_actif(gid, uid))
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}",
                         json={"components": rang})
        if code == 200:
            bilan["faits"].append(uid)
            finis.append(cle)
        elif code == 404:
            # accueil supprimé à la main : rien à redessiner, on ne réessaie pas
            bilan["sans_accueil"].append(uid)
            finis.append(cle)
        else:
            bilan["rates"].append(f"{uid} (HTTP {code})")
            if code == 429:
                break
    if finis:
        with _VERROU:
            d = _etat()
            for cle in finis:
                f = (d.get("tickets") or {}).get(cle)
                if isinstance(f, dict):
                    f["boutons"] = BOUTONS_VERSION
            _ecrire_etat(d)
    if bilan["faits"] or bilan["sans_accueil"] or bilan["rates"]:
        print(f"[ticket] boutons {gid} : {len(bilan['faits'])} accueil(s) redessiné(s)"
              + (f", sans accueil : {bilan['sans_accueil']}" if bilan["sans_accueil"] else "")
              + (f", ratés : {bilan['rates']}" if bilan["rates"] else ""), flush=True)
    return bilan


# ─── l'entretien des accueils ───────────────────────────────────────────
# Audit du 20/10/2026 : une fiche de Twitter pointait vers un salon supprimé à
# la main (septofm, 404), quatre accueils de Threads reposés le 13/10 n'étaient
# pas épinglés (l'ancien l'était encore, ou rien), et neuf accueils nommaient
# le manager d'avant une réaffectation (steave0454 : « Roucham » au lieu de
# MOMOBY). Le VA cherche son bouton 💳 et son manager dans l'accueil épinglé :
# ce qu'il y lit doit être vrai. Une fois par jour et par serveur.
ENTRETIEN_S = 86400
_ENTRETIEN_VU: Dict[str, float] = {}
_RE_CONFIE = re.compile(r"(tu es confié à )(<@&?\d+>|un manager)")


def corriger_manager_accueil(salon: str, mid: str, accueil: str,
                             msg: Optional[Dict[str, Any]] = None) -> str:
    """« tu es confié à <@ancien> » → le manager du jour, dans l'accueil.
    Rend « fait », « deja » (rien à changer) ou ce qui a empêché."""
    if not (salon and mid and accueil):
        return "deja"
    if msg is None:
        code, msg = _api("GET", f"/channels/{salon}/messages/{accueil}")
        if code != 200 or not isinstance(msg, dict):
            return f"accueil illisible (HTTP {code})"
    embeds = msg.get("embeds") or []
    d = str((embeds[0] if embeds else {}).get("description") or "")
    m = _RE_CONFIE.search(d)
    if not m or m.group(2) == f"<@{mid}>":
        return "deja"
    embeds[0]["description"] = _RE_CONFIE.sub(rf"\g<1><@{mid}>", d, count=1)
    corps: Dict[str, Any] = {"embeds": embeds, "allowed_mentions": {"parse": []}}
    contenu = str(msg.get("content") or "")
    if m.group(2) in contenu:
        corps["content"] = contenu.replace(m.group(2), f"<@{mid}>", 1)
    code, rep = _api("PATCH", f"/channels/{salon}/messages/{accueil}", json=corps)
    return "fait" if code == 200 else f"HTTP {code} {str(rep)[:80]}"


def _epingler_accueil(salon: str, accueil: str, bot_id: str) -> str:
    """Épingle l'accueil du jour, et retire l'épingle des anciens accueils
    « 👋 Bienvenue » postés par un bot (Siri avant Bowser sur Threads), jamais
    d'un message de membre : un seul « message épinglé » à lire.
    Rend « fait » ou ce qui a empêché."""
    code, rep = _api("PUT", f"/channels/{salon}/pins/{accueil}")
    if code not in (200, 204):
        return f"épinglage refusé (HTTP {code}) {str(rep)[:80]}"
    code, pins = _api("GET", f"/channels/{salon}/pins")
    items = pins.get("items") if isinstance(pins, dict) else pins
    for x in (items if code == 200 and isinstance(items, list) else []):
        m = x.get("message") if isinstance(x, dict) and "message" in x else x
        if not isinstance(m, dict) or str(m.get("id")) == accueil:
            continue
        titre = str(((m.get("embeds") or [{}])[0].get("title")) or "")
        auteur = m.get("author") or {}
        if titre.startswith("👋 Bienvenue") and (auteur.get("bot") or str(auteur.get("id")) == bot_id):
            _api("DELETE", f"/channels/{salon}/pins/{m['id']}")
    return "fait"


def entretenir_accueils(gid: str) -> Dict[str, Any]:
    """Chaque fiche de ticket de ce serveur, face à Discord :

    - salon supprimé (404 « Unknown Channel », code 10003) : la fiche sort de
      « tickets » et passe dans « tickets_disparus », datée — jamais effacée ;
      un autre refus (403, 429, panne) ne touche à rien ;
    - accueil qui nomme l'ancien manager : corrigé ;
    - accueil pas épinglé : épinglé, l'ancien accueil 👋 désépinglé.

    Rend le bilan, dit au journal quand il y a quelque chose."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"disparus": [], "managers": [], "epingles": [],
                             "rates": [], "illisibles": []}
    fiches = {k: dict(v) for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict)}
    code, moi = _api("GET", "/users/@me")
    bot_id = str((moi or {}).get("id") or "") if code == 200 and isinstance(moi, dict) else ""
    disparus: Dict[str, Dict[str, Any]] = {}
    for cle, f in sorted(fiches.items()):
        uid = cle.split(":", 1)[1]
        salon, accueil = str(f.get("salon") or ""), str(f.get("accueil") or "")
        if not salon:
            continue
        code, ch = _api("GET", f"/channels/{salon}")
        if code == 404 and isinstance(ch, dict) and int(ch.get("code") or 0) == 10003:
            disparus[cle] = f
            bilan["disparus"].append(f"{uid} (salon {salon})")
            continue
        if code != 200:
            bilan["illisibles"].append(f"{uid} (HTTP {code})")
            continue
        if not accueil:
            continue
        code, msg = _api("GET", f"/channels/{salon}/messages/{accueil}")
        if code != 200 or not isinstance(msg, dict):
            bilan["illisibles"].append(f"{uid} : accueil (HTTP {code})")
            continue
        r = corriger_manager_accueil(salon, str(f.get("manager") or ""), accueil, msg)
        if r == "fait":
            bilan["managers"].append(uid)
        elif r != "deja":
            bilan["rates"].append(f"{uid} : manager, {r}")
        if not msg.get("pinned") and bot_id:
            r = _epingler_accueil(salon, accueil, bot_id)
            (bilan["epingles"].append(uid) if r == "fait"
             else bilan["rates"].append(f"{uid} : {r}"))
    if disparus:
        with _VERROU:
            d = _etat()
            fs = d.setdefault("tickets", {})
            garde = d.setdefault("tickets_disparus", {})
            for cle, f in disparus.items():
                if cle in fs:
                    garde[cle] = dict(fs.pop(cle), disparu=int(time.time()))
            _ecrire_etat(d)
    if any(bilan.values()):
        print(f"[ticket] accueils {gid} : {bilan}", flush=True)
    return bilan


# ─── le départ d'un VA ──────────────────────────────────────────────────
# Audit du 20/10/2026 : fabiano.18_ (VA 83 de Threads) avait quitté le serveur
# le 19/10 et gardait tout — ticket, fiches, deux liens GetMySocial actifs,
# sa ligne au classement. Bowser et Luigi ne reçoivent pas les événements de
# Discord : chaque fiche est relue, une fois l'heure. Propriétaire, 21/10/2026 :
# le ticket « marqué 👋 parti », le salon tel quel, le VA sorti des classements,
# « son lien est disable, si il revient je peux le renable » — désactivé,
# jamais supprimé ; le bouton ✅ Réactiver le lien de l'accueil le rallume.
DEPARTS_S = 3600
_DEPARTS_VU: Dict[str, float] = {}
MARQUE_PARTI = "\n👋 _Parti du serveur — son lien est désactivé, réactivable ici._"


def partis(gid: str) -> Dict[str, float]:
    """{uid : heure où son départ a été constaté} des VA partis de ce serveur.
    Lu par le podium (sortis des classements) et par suivi_va (ni alerte, ni
    prime)."""
    out: Dict[str, float] = {}
    for cle, f in (_etat().get("tickets") or {}).items():
        if (str(cle).startswith(f"{gid}:") and isinstance(f, dict)
                and isinstance(f.get("parti"), dict)):
            out[str(cle).split(":", 1)[1]] = float(f["parti"].get("quand") or 0)
    return out


def _couper_liens_du_va(gid: str, uid: str) -> Dict[str, Any]:
    """Son lien coupé par liens_va.basculer (c'est lui que « ✅ Réactiver le
    lien » rallume), et les autres liens actifs au MÊME nom dans l'espace
    GetMySocial du serveur — le double clic du 17/10 avait laissé pearlkittyy
    hors registre. Désactivés, jamais supprimés. Rend {coupe, doublons, erreur}."""
    import liens_va as lv
    out: Dict[str, Any] = {"coupe": False, "doublons": [], "erreur": ""}
    l = lv.lien_de(gid, uid)
    if not l.get("shortcode"):
        return out
    if lv.est_actif(gid, uid):
        r = lv.basculer(gid, uid, False)
        out["coupe"] = bool(r.get("ok"))
        if not r.get("ok"):
            out["erreur"] = str(r.get("erreur") or "refus")[:120]
    try:
        import gms
        lid = str(lv.lien_de(gid, uid).get("link_id") or l.get("link_id") or "")
        rep = gms.list_links_team(str(lv.espace(gid)["equipe"]), force_refresh=True)
        liens = rep.get("links") or [] if isinstance(rep, dict) else []
        nom = next((str(x.get("display_name") or "") for x in liens
                    if str(x.get("id")) == lid), "")
        for x in liens:
            if (nom and str(x.get("display_name") or "") == nom and str(x.get("id")) != lid
                    and str(x.get("status") or "active").lower() == "active"):
                r = gms.disable_link(str(x["id"]))
                if r.get("ok"):
                    out["doublons"].append(str(x.get("shortcode") or x["id"]))
                else:
                    out["erreur"] += f' doublon {x.get("shortcode")} : {str(r.get("error"))[:60]}'
    except Exception as e:                                   # noqa: BLE001
        out["erreur"] += f" doublons : {type(e).__name__}: {str(e)[:80]}"
    return out


def _marquer_accueil(gid: str, uid: str, f: Dict[str, Any], parti: bool) -> None:
    """La ligne « 👋 Parti » dans l'accueil, posée ou retirée, et les boutons
    du lien tel qu'il est (coupé : ✅ Réactiver)."""
    import liens_va as lv
    salon, mid = str(f.get("salon") or ""), str(f.get("accueil") or "")
    if not (salon and mid):
        return
    code, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
    if code != 200 or not isinstance(msg, dict):
        return
    embeds = msg.get("embeds") or [{}]
    d = str(embeds[0].get("description") or "").replace(MARQUE_PARTI, "")
    embeds[0]["description"] = ((d.rstrip() + MARQUE_PARTI) if parti else d)[:4096]
    a_un_lien = bool(lv.lien_de(gid, uid).get("public_url"))
    _api("PATCH", f"/channels/{salon}/messages/{mid}",
         json={"embeds": embeds,
               "components": boutons_va(uid, confirme=bool(f.get("confirme")),
                                        a_un_lien=a_un_lien, gid=gid,
                                        lien_actif=lv.est_actif(gid, uid))})


def marquer_parti(gid: str, uid: str) -> Dict[str, Any]:
    """Le VA a quitté le serveur : fiche marquée, lien coupé, ticket prévenu.
    Le salon reste tel quel. Rend le bilan."""
    gid, uid = str(gid), str(uid)
    cle = f"{gid}:{uid}"
    with _VERROU:
        d = _etat()
        f = (d.get("tickets") or {}).get(cle)
        if not isinstance(f, dict) or f.get("parti"):
            return {"ok": False}
        f["parti"] = {"quand": int(time.time())}
        f.pop("revenu", None)
        _ecrire_etat(d)
        f = dict(f)
    liens = _couper_liens_du_va(gid, uid)
    jour = time.strftime("%d/%m/%Y")
    lien = ""
    if liens["coupe"] or liens["doublons"]:
        lien = ("🚫 Son lien est désactivé, pas supprimé : **✅ Réactiver le lien**, sur "
                "l'accueil, le remet en service s'il revient.\n")
    salon = str(f.get("salon") or "")
    if salon:
        _api("POST", f"/channels/{salon}/messages",
             json={"content": f"👋 <@{uid}> a quitté le serveur (constaté le **{jour}**).\n"
                              + lien + "Ce salon reste tel quel. Il ne compte plus dans les "
                              "classements.", "allowed_mentions": {"parse": []}})
        _marquer_accueil(gid, uid, f, parti=True)
    print(f"[ticket] {gid} : {uid} parti — lien coupé : {liens['coupe']}, doublons coupés : "
          f"{liens['doublons']}" + (f", souci : {liens['erreur']}" if liens["erreur"] else ""),
          flush=True)
    return {"ok": True, **liens}


def marquer_revenu(gid: str, uid: str) -> None:
    """Revenu sur le serveur : il rentre dans les classements. Son lien reste
    coupé — le rallumer est une décision (bouton ✅ Réactiver le lien)."""
    gid, uid = str(gid), str(uid)
    with _VERROU:
        d = _etat()
        f = (d.get("tickets") or {}).get(f"{gid}:{uid}")
        if not isinstance(f, dict) or not f.get("parti"):
            return
        f.pop("parti", None)
        f["revenu"] = int(time.time())
        _ecrire_etat(d)
        f = dict(f)
    salon = str(f.get("salon") or "")
    if salon:
        _api("POST", f"/channels/{salon}/messages",
             json={"content": f"👋 <@{uid}> est de retour sur le serveur. Son lien reste "
                              "désactivé : **✅ Réactiver le lien**, sur l'accueil, le remet "
                              "en service.", "allowed_mentions": {"parse": []}})
        _marquer_accueil(gid, uid, f, parti=False)
    print(f"[ticket] {gid} : {uid} revenu sur le serveur (lien toujours coupé)", flush=True)


def suivre_departs(gid: str) -> Dict[str, Any]:
    """Chaque VA à ticket de ce serveur : encore là ? Absent (404 « Unknown
    Member », code 10007) : marquer_parti. Revenu : marquer_revenu. Tout autre
    refus ne conclut rien, et c'est dit. Rend le bilan."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"partis": [], "revenus": [], "illisibles": []}
    fiches = {k: v for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict)}
    for cle, f in sorted(fiches.items()):
        uid = cle.split(":", 1)[1]
        code, m = _api("GET", f"/guilds/{gid}/members/{uid}")
        if code == 404 and isinstance(m, dict) and int(m.get("code") or 0) == 10007:
            if not f.get("parti") and marquer_parti(gid, uid).get("ok"):
                bilan["partis"].append(uid)
        elif code == 200:
            if f.get("parti"):
                marquer_revenu(gid, uid)
                bilan["revenus"].append(uid)
        else:
            bilan["illisibles"].append(f"{uid} (HTTP {code})")
    if any(bilan.values()):
        print(f"[ticket] départs {gid} : {bilan}", flush=True)
    return bilan


# ─── « 📈 Mes stats » ───────────────────────────────────────────────────
# Le bouton « 📈 Mes subs » (subs:total:) est posé par un patch local du VPS
# (99-z-tickets-subs-total) dans boutons_va ; son libellé change ici, APRÈS
# coup, sans toucher aux lignes du patch. Propriétaire, 21/10/2026 : « pour
# mes sub change et mets mes stats, ça montre les sub et click ». La réponse,
# elle, est subs_va.texte (abonnés + clics). Par serveur : clé « mes_stats »
# du profil du podium (Threads, Twitter).
_boutons_va_avant_stats = boutons_va


def _avec_mes_stats(gid: str) -> bool:
    try:
        import podium_discord as pod
        return bool(pod._profil(str(gid or "")).get("mes_stats")) if gid else False
    except Exception:                                        # noqa: BLE001
        return False


# « 📱 Numéro » (propriétaire, 23/10/2026, sur le menu épinglé d'un ticket :
# « je veux que ça soit une option dans le menu pin ») : la carte numéro du VA
# de ce ticket redescend tout en bas. Le clic est à numeros_x_discord._menu
# (traiter, plus haut, rend None pour « numx: » : la route le lui passe).
NUMERO_DANS_MENU = {"1445108485090971710",    # YouLab TWITTER
                    "1498948161039896586",    # YouLab THREADS
                    AGENCY_IG_ID}
# « 📧 Outlook » juste après (propriétaire, 23/10/2026 : « pour twitter mets ça
# aussi dans leur ticket comme sur threads ») : la carte Outlook du VA
# redescend (outlook_x_discord._menu). Twitter seulement : Agency n'a pas de
# coffre Outlook, Va IG a son propre parcours.
OUTLOOK_DANS_MENU = {"1445108485090971710"}   # YouLab TWITTER


def boutons_va(uid: str, confirme: bool = False, a_un_lien: bool = False,
               gid: str = "", lien_actif: bool = True):
    """boutons_va (voir plus haut), « 📈 Mes stats » au lieu de « 📈 Mes subs »
    sur un serveur à clé « mes_stats ». Agency VA INSTAGRAM (22/10/2026) : le
    patch du VPS ne pose « Mes subs » que sur Twitter et Threads, le bouton
    est ajouté ici."""
    rangs = _boutons_va_avant_stats(uid, confirme=confirme, a_un_lien=a_un_lien,
                                    gid=gid, lien_actif=lien_actif)
    if str(gid) == AGENCY_IG_ID and rangs and not any(
            str(b.get("custom_id") or "").startswith("subs:total:")
            for r in rangs for b in r.get("components") or []):
        rangs[-1].setdefault("components", []).append(
            {"type": 2, "style": 3, "label": "Mes stats",
             "custom_id": f"subs:total:{uid}", "emoji": {"name": "📈"}})
    if _avec_mes_stats(gid):
        for r in rangs:
            for b in r.get("components") or []:
                if str(b.get("custom_id") or "").startswith("subs:total:"):
                    b["label"] = "Mes stats"
    for serveurs, bouton in ((NUMERO_DANS_MENU, {"type": 2, "style": 2, "label": "Numéro",
                                                  "emoji": {"name": "📱"}, "custom_id": "numx:menu"}),
                             (OUTLOOK_DANS_MENU, {"type": 2, "style": 2, "label": "Outlook",
                                                  "emoji": {"name": "📧"}, "custom_id": "mailx:menu"})):
        if str(gid) not in serveurs or any(b.get("custom_id") == bouton["custom_id"]
                                           for r in rangs for b in r.get("components") or []):
            continue
        if rangs and len(rangs[-1].get("components") or []) < 5:
            rangs[-1].setdefault("components", []).append(bouton)
        else:                                   # rangée pleine : Discord en refuse un 6e
            rangs.append({"type": 1, "components": [bouton]})
    if str(gid) in NUMERO_DANS_MENU:
        rangs = _deux_rangees(rangs)
    return rangs


#: Les boutons que seuls les managers peuvent utiliser (traiter les refuse au
#: VA) : leur propre rangée, sous celle du VA.
_BOUTONS_MANAGERS = ("essai:ok:", "lien:new:", "lien:off:", "lien:on:")


def _deux_rangees(rangs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """La rangée du VA (USDC, Mes stats, Numéro, Outlook), puis celle des
    managers (Confirmer, le lien). Maquette validée par le propriétaire le
    23/10/2026 (« Oui, vas-y ») : mélangés sur une rangée, le VA cliquait des
    boutons qui lui répondaient « seuls les managers ». Cinq par rangée au
    plus : Discord refuse le menu entier au sixième."""
    boutons = [b for r in rangs for b in (r.get("components") or [])]
    va = [b for b in boutons if not str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)]
    chefs = [b for b in boutons if str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)]
    return [{"type": 1, "components": groupe[i:i + 5]}
            for groupe in (va, chefs) for i in range(0, len(groupe), 5)]


# ─── Agency VA INSTAGRAM : adopter les salons faits à la main ────────────
# 22/10/2026 : 29 salons perso existaient déjà, nommés au prénom (« zaid »),
# rangés dans « 🔵┤ Manager GONE ├🔵 » et « 🔵┤ Manager YOSHIKI ├🔵 », le VA
# en membre du salon. Le propriétaire veut les adopter comme tickets, sans en
# recréer, et voir d'abord un ticket rendu. Adopter = la fiche de
# tickets.json + l'accueil épinglé avec les boutons (Créer son lien, Mon
# adresse USDC, Mes stats). NI les droits du salon NI son nom ne changent :
# ce sera son accord, à part. Sans mention : 29 notifications d'un coup pour
# un salon que le VA connaît déjà n'apprendraient rien.
def adopter_salon(gid: str, cid: str, manager_id: str = "",
                  poster: bool = False, renommer: bool = False,
                  uid_va: str = "") -> Dict[str, Any]:
    """Ce que l'adoption du salon `cid` ferait ({ok, uid, manager, essai,
    nom, corps, erreur}), et le fait si `poster`. Refuse ce qui n'est pas sûr :
    un salon hors des catégories de managers, zéro ou plusieurs VA en membres,
    un VA qui a déjà son ticket. `renommer` : le salon prend le nom d'un
    ticket, numéro du VA compris (nom_salon_va) — propriétaire, 23/10/2026,
    « tu donnes des numéros aux VA ». Un salon déjà adopté (même salon dans
    sa fiche) n'a pas de second accueil : seul le nom est refait. `uid_va` :
    le VA désigné à la main quand le salon a plusieurs membres (« israel » :
    le VA et son leader, 23/10/2026) ; il doit en être membre, et il est en
    essai s'il n'est pas confirmé (⏳ En attente compris)."""
    gid, cid = str(gid), str(cid)
    code, c = _api("GET", f"/channels/{cid}")
    if code != 200 or not isinstance(c, dict):
        return {"ok": False, "erreur": f"salon illisible (HTTP {code})"}
    code_p, cat = _api("GET", f"/channels/{c.get('parent_id')}") if c.get("parent_id") else (0, {})
    if not (code_p == 200 and _cle_categorie((cat or {}).get("name"))):
        return {"ok": False, "erreur": f"« {c.get('name')} » n'est pas dans une catégorie de manager"}
    code_r, roles = _api("GET", f"/guilds/{gid}/roles")
    noms = {str(r.get("id")): str(r.get("name") or "") for r in roles} if code_r == 200 else {}
    vas = []
    for o in c.get("permission_overwrites") or []:
        if str(o.get("type", "1")) not in ("1", "member"):
            continue
        code_m, m = _api("GET", f"/guilds/{gid}/members/{o['id']}")
        if code_m != 200:
            continue
        rs = [noms.get(str(x), "") for x in m.get("roles") or []]
        if any("manager" in r.lower() for r in rs):
            continue                          # le salon d'un manager, pas d'un VA
        vas.append((str(o["id"]), m, rs))
    if uid_va:
        vas = [v for v in vas if v[0] == str(uid_va)]
        if not vas:
            return {"ok": False, "erreur": f"« {c.get('name')} » : {uid_va} n'en est pas membre"}
    if len(vas) != 1:
        return {"ok": False, "erreur": f"« {c.get('name')} » : {len(vas)} VA en membres, "
                                       f"à voir à la main"}
    uid, membre, rs = vas[0]
    cle = f"{gid}:{uid}"
    deja = (_etat().get("tickets") or {}).get(cle) or {}
    if deja.get("salon") and str(deja["salon"]) != cid:
        return {"ok": False, "erreur": f"{uid} a déjà le ticket {deja['salon']}"}
    pseudo = re.sub(r"[^a-z0-9._-]+", "-", str((membre.get("user") or {}).get("username")
                                                  or "").lower()).strip("-")[:60] \
        or _pseudo(gid, uid)
    nom = nom_salon_va(gid, uid, pseudo)
    if deja.get("accueil") and str(deja.get("salon")) == cid:
        # déjà adopté : le nom seulement
        out = {"ok": True, "uid": uid, "pseudo": pseudo, "manager": deja.get("manager", ""),
               "essai": bool(deja.get("essai")), "salon": cid, "nom": nom, "corps": None,
               "deja": True, "erreur": ""}
        if poster and renommer and c.get("name") != nom:
            code_n, rep_n = _api("PATCH", f"/channels/{cid}", json={"name": nom})
            if code_n != 200:
                return dict(out, ok=False, erreur=f"renommage refusé (HTTP {code_n}) {str(rep_n)[:100]}")
        return out
    essai = any(r in (ROLE_ESSAI_NOM, "VA débutant") for r in rs) or (
        bool(uid_va) and ROLE_CONFIRME_NOM not in rs)
    if not manager_id:
        voulu = _cle_categorie(cat.get("name"))
        trouves = [m for m in managers(gid) if _nom_court(m) == voulu]
        manager_id = str((trouves[0].get("user") or {}).get("id")) if len(trouves) == 1 else ""
    import liens_va
    lien = liens_va.lien_de(gid, uid)
    qui = f"<@{manager_id}>" if manager_id else "ton manager"
    embed = {
        "title": "👋 Ton espace perso",
        "color": 0x3B82F6,
        "description": (
            f"<@{uid}>, tu es suivi par {qui}.\n\n"
            "**C'est ici que ça se passe :**\n"
            "• tes questions,\n"
            "• tes preuves et tes captures,\n"
            "• ton lien, tes stats et ton adresse de paiement (boutons ci-dessous).\n\n"
            "Personne d'autre que toi et les managers ne voit ce salon."),
        "footer": {"text": "YouLab • Ton manager te répond ici"},
    }
    corps = {"content": "", "embeds": [embed],
             "components": boutons_va(uid, confirme=not essai,
                                      a_un_lien=bool(lien.get("public_url")), gid=gid,
                                      lien_actif=liens_va.est_actif(gid, uid)),
             "allowed_mentions": {"parse": []}}
    out = {"ok": True, "uid": uid, "pseudo": pseudo, "manager": manager_id, "essai": essai,
           "salon": cid, "nom": nom, "corps": corps, "erreur": ""}
    if not poster:
        return out
    if renommer and c.get("name") != nom:
        code_n, rep_n = _api("PATCH", f"/channels/{cid}", json={"name": nom})
        if code_n != 200:
            return dict(out, ok=False, erreur=f"renommage refusé (HTTP {code_n}) {str(rep_n)[:100]}")
    code_m, rep_m = _api("POST", f"/channels/{cid}/messages", json=corps)
    if code_m != 200 or not rep_m.get("id"):
        return dict(out, ok=False, erreur=f"accueil refusé (HTTP {code_m}) {str(rep_m)[:120]}")
    code_e, rep_e = _api("PUT", f'/channels/{cid}/pins/{rep_m["id"]}')
    if code_e not in (200, 204):
        print(f"[ticket] accueil non épinglé dans {cid} (HTTP {code_e}) {str(rep_e)[:100]}",
              flush=True)
    with _VERROU:
        d = _etat()
        tk = d.setdefault("tickets", {})
        tk[cle] = dict(tk.get(cle) or {}, salon=cid, manager=manager_id, essai=essai,
                       accueil=str(rep_m["id"]), boutons=BOUTONS_VERSION,
                       adopte=int(time.time()), ouvert=int((tk.get(cle) or {}).get("ouvert")
                                                           or time.time()))
        _ecrire_etat(d)
    print(f"[ticket] {gid} : « {c.get('name')} » adopté pour {uid} (manager {manager_id or '?'})",
          flush=True)
    return dict(out, accueil=str(rep_m["id"]))


# ─── le menu reposé en bas du ticket ────────────────────────────────────
# Propriétaire, 23/10/2026 : « 📱・numéro-usa devient un salon menu avec un
# bouton qui active leur menu dans leur propre salon ». Dans un ticket où la
# conversation continue, le menu épinglé remonte et le VA ne le trouve plus.
# Le bouton du salon (numeros_x_discord._menu) appelle ramener_menu : une
# COPIE des boutons de l'accueil (« menu » dans la fiche) est posée en bas et
# épinglée, l'ancienne copie retirée ; l'accueil épinglé ne bouge pas. Sans
# salon perso (le staff), menu_prive : la rangée du VA, pour lui seul.
def _sans_ids(x: Any) -> Any:
    """Les composants tels que Discord les rend portent un « id » propre au
    message : reposés ailleurs, sans lui."""
    if isinstance(x, list):
        return [_sans_ids(y) for y in x]
    if isinstance(x, dict):
        return {k: _sans_ids(v) for k, v in x.items() if k != "id"}
    return x


def _rangs_du_menu(gid: str, uid: str, f: Dict[str, Any], salon: str) -> List[Dict[str, Any]]:
    """Les boutons de l'accueil tels qu'ils sont affichés (un patch du VPS y
    ajoute les siens) ; accueil illisible : refaits comme redessiner_boutons."""
    mid = str(f.get("accueil") or "")
    if mid:
        code, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
        if code == 200 and isinstance(msg, dict) and msg.get("components"):
            return _sans_ids(msg["components"])
    import liens_va as lv
    return boutons_va(uid, confirme=bool(f.get("confirme")),
                      a_un_lien=bool(lv.lien_de(gid, uid).get("public_url")),
                      gid=gid, lien_actif=lv.est_actif(gid, uid))


def _texte_menu(gid: str, uid: str) -> str:
    """« 📋 Menu », et le lien du VA dessous quand il en a un en service
    (propriétaire, 23/10/2026 : « mets aussi leur lien s'il a un lien »,
    comme la ligne de menu de Va IG). Coupé, ou VA parti : rien. Entre
    chevrons : sans eux, Discord poserait l'aperçu de la page sous le menu."""
    texte = "📋 **Menu**"
    try:
        import liens_va as lv
        l = lv.lien_de(gid, uid)
        url = str(l.get("public_url") or "")
        parti = ((_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}).get("parti")
        if url and l.get("actif", True) is not False and not parti:
            texte += f"\n🔗 <{url}>"
    except Exception as e:                                   # noqa: BLE001
        print(f"[ticket] menu : lien de {uid} illisible ({type(e).__name__}: {e})", flush=True)
    return texte


def _noter_texte_menu(cle: str, texte: str) -> None:
    with _VERROU:
        d = _etat()
        g = (d.get("tickets") or {}).get(cle)
        if isinstance(g, dict) and g.get("menu_texte") != texte:
            g["menu_texte"] = texte
            _ecrire_etat(d)


def _epingler_sans_avis(salon: str, mid: str) -> None:
    """Épingle `mid`, puis retire l'avis « … a épinglé un message » que
    Discord pose dessous : à chaque clic, il aurait poussé le menu d'un cran
    et encombré le ticket (l'avis exaspère le propriétaire)."""
    code, _r = _api("PUT", f"/channels/{salon}/pins/{mid}")
    if code not in (200, 204):
        print(f"[ticket] menu {mid} non épinglé dans {salon} (HTTP {code})", flush=True)
        return
    code, ms = _api("GET", f"/channels/{salon}/messages?limit=5")
    for m in (ms if code == 200 and isinstance(ms, list) else []):
        # type 6 : CHANNEL_PINNED_MESSAGE, qui renvoie au message épinglé
        if m.get("type") == 6 and str((m.get("message_reference") or {}).get("message_id")) == mid:
            _api("DELETE", f"/channels/{salon}/messages/{m['id']}")


def ramener_menu(gid: str, uid: str, salon: str, en_dernier: bool = False) -> str:
    """Le menu du ticket de `uid` en bas de `salon`, épinglé : « deja » (il y
    est, rien que des messages de bots dessous — la carte numéro), « ramene »,
    ou « echec ». Ne lève jamais.

    `en_dernier` (outils_tickets, après une livraison) : le menu doit être LE
    dernier message. Les fichiers livrés sont des messages de bot : sans ça,
    « rien que des bots dessous » laissait cinq versions spoofées entre le
    menu et le bas du ticket jusqu'au tour de l'heure."""
    try:
        import verif_discord as vd
        gid, uid, salon = str(gid), str(uid), str(salon)
        cle = f"{gid}:{uid}"
        f = (_etat().get("tickets") or {}).get(cle) or {}
        if not salon or str(f.get("salon") or "") != salon:
            print(f"[ticket] menu : {salon} n'est pas le ticket de {uid}", flush=True)
            return "echec"
        with vd.sur_serveur(gid):
            rangs = _rangs_du_menu(gid, uid, f, salon)
            if not rangs:
                return "echec"
            texte = _texte_menu(gid, uid)
            copie, accueil = str(f.get("menu") or ""), str(f.get("accueil") or "")
            code, ms = _api("GET", f"/channels/{salon}/messages?limit=10")
            for m in (ms if code == 200 and isinstance(ms, list) else []):
                if str(m.get("id")) in {copie, accueil} - {""}:
                    if str(m["id"]) == copie and (_sans_ids(m.get("components")) != rangs
                                                  or m.get("content") != texte):
                        _api("PATCH", f"/channels/{salon}/messages/{copie}",
                             json={"content": texte, "components": rangs})
                        _noter_texte_menu(cle, texte)
                    return "deja"
                if en_dernier or not (m.get("author") or {}).get("bot") or m.get("type") == 6:
                    break
            code, rep = _api("POST", f"/channels/{salon}/messages",
                             json={"content": texte, "components": rangs,
                                   "allowed_mentions": {"parse": []}})
            if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
                print(f"[ticket] menu de {uid} non reposé (HTTP {code}) {str(rep)[:120]}", flush=True)
                return "echec"
            neuf = str(rep["id"])
            with _VERROU:
                d = _etat()
                g = (d.get("tickets") or {}).get(cle)
                if isinstance(g, dict):
                    g["menu"] = neuf
                    g["menu_texte"] = texte
                    _ecrire_etat(d)
            _epingler_sans_avis(salon, neuf)
            if copie:
                # retirée : son épingle part avec elle (404 : retirée à la main)
                _api("DELETE", f"/channels/{salon}/messages/{copie}")
        return "ramene"
    except Exception as e:                                   # noqa: BLE001
        print(f"[ticket] menu de {uid} : {type(e).__name__}: {e}", flush=True)
        return "echec"


def menu_prive(gid: str, uid: str) -> Dict[str, Any]:
    """Sans salon perso (le staff, ou un VA pas encore servi) : la rangée du
    VA (USDC, Mes stats, Numéro, Outlook) pour lui seul, comme la carte
    numéro privée (01eed36). Rien n'est écrit dans un ticket."""
    siens = [b for r in boutons_va(str(uid), confirme=True, a_un_lien=False, gid=str(gid))
             for b in (r.get("components") or [])
             if not str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)]
    rangs = [{"type": 1, "components": siens[i:i + 5]} for i in range(0, len(siens), 5)]
    return {"type": 4, "data": {"content": _texte_menu(str(gid), str(uid)), "components": rangs,
                                "flags": 64,
                                "allowed_mentions": {"parse": []}}}


# La copie suit l'accueil : toute rangée de boutons posée sur un accueil (lien
# créé, coupé, VA parti, redessin…) l'est aussi sur sa copie. Un seul point de
# passage plutôt qu'un appel dans chacune des fonctions qui le font — une
# copie restée « Désactiver le lien » sous un lien déjà coupé tromperait. (La
# copie elle-même repasse par ici : aucun accueil ne porte son id, ça
# s'arrête là.)
_api_reseau = _api


def _miroir(chemin: str, rangs: Any) -> None:
    morceaux = chemin.strip("/").split("/")
    if len(morceaux) != 4 or morceaux[0] != "channels" or morceaux[2] != "messages":
        return
    salon, mid = morceaux[1], morceaux[3]
    for cle, f in (_etat().get("tickets") or {}).items():
        if (isinstance(f, dict) and str(f.get("accueil") or "") == mid and f.get("menu")
                and str(f.get("salon") or "") == salon):
            gid, _sep, uid = str(cle).partition(":")
            texte = _texte_menu(gid, uid)
            code, _r = _api("PATCH", f"/channels/{salon}/messages/{f['menu']}",
                            json={"content": texte, "components": _sans_ids(rangs)})
            if code == 200:
                _noter_texte_menu(cle, texte)
            return


def _api(methode: str, chemin: str, **kw):   # noqa: F811
    rep = _api_reseau(methode, chemin, **kw)
    corps = kw.get("json")
    if methode == "PATCH" and isinstance(corps, dict) and "components" in corps and rep[0] == 200:
        try:
            _miroir(chemin, corps["components"])
        except Exception as e:                               # noqa: BLE001
            print(f"[ticket] copie du menu non suivie : {type(e).__name__}: {e}", flush=True)
    return rep


# « Confirmer le VA » répond en réécrivant le message cliqué (type 7) : pas
# d'appel PATCH à suivre. Cliqué sur l'accueil, la copie reçoit la nouvelle
# rangée ; cliqué sur la copie, c'est l'accueil (son encart garde l'ancien
# texte d'essai : « ⭐ VA confirmé » s'écrit quand on clique l'accueil).
_traiter_sans_copie = traiter


def _jumeau(salon: str, mid: str, rangs: Any) -> None:
    for f in (_etat().get("tickets") or {}).values():
        if not isinstance(f, dict) or str(f.get("salon") or "") != salon:
            continue
        if str(f.get("accueil") or "") == mid:
            _miroir(f"/channels/{salon}/messages/{mid}", rangs)
        elif str(f.get("menu") or "") == mid and f.get("accueil"):
            _api_reseau("PATCH", f"/channels/{salon}/messages/{f['accueil']}",
                        json={"components": _sans_ids(rangs)})
        return


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:   # noqa: F811
    rep = _traiter_sans_copie(p)
    if isinstance(rep, dict) and rep.get("type") == 7 and "components" in (rep.get("data") or {}):
        salon = str((p or {}).get("channel_id") or "")
        mid = str(((p or {}).get("message") or {}).get("id") or "")
        rangs = rep["data"]["components"]
        _en_fond(lambda: _jumeau(salon, mid, rangs))
    return rep


# Le lien change aussi sans toucher l'accueil (nouvelle adresse,
# liens_va.changer_adresse) : à chaque passage de redessiner_boutons (le tour
# des liens, une demi-heure), le texte attendu est comparé à celui posé — sur
# place, sans appel à Discord tant que rien n'a bougé. Les menus posés avant
# le lien (23/10/2026) le reçoivent au premier passage.
_redessiner_boutons_sans_menus = redessiner_boutons


def rafraichir_menus(gid: str) -> Dict[str, Any]:
    gid = str(gid)
    bilan: Dict[str, Any] = {"faits": [], "partis": [], "rates": []}
    fiches = {k: dict(v) for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict) and v.get("menu")}
    for cle, f in fiches.items():
        uid = cle.split(":", 1)[1]
        texte = _texte_menu(gid, uid)
        if f.get("menu_texte") == texte:
            continue
        code, _r = _api("PATCH", f"/channels/{f.get('salon')}/messages/{f['menu']}",
                        json={"content": texte})
        if code == 200:
            _noter_texte_menu(cle, texte)
            bilan["faits"].append(uid)
        elif code == 404:
            # retiré à la main : oublié, le prochain clic en repose un
            with _VERROU:
                d = _etat()
                g = (d.get("tickets") or {}).get(cle)
                if isinstance(g, dict) and str(g.get("menu") or "") == str(f["menu"]):
                    g.pop("menu", None)
                    g.pop("menu_texte", None)
                    _ecrire_etat(d)
            bilan["partis"].append(uid)
        else:
            bilan["rates"].append(f"{uid} (HTTP {code})")
            if code == 429:
                break
    if bilan["faits"] or bilan["rates"]:
        print(f"[ticket] menus {gid} : {len(bilan['faits'])} lien(s) mis à jour"
              + (f", ratés : {bilan['rates']}" if bilan["rates"] else ""), flush=True)
    return bilan


def redessiner_boutons(gid: str) -> Dict[str, Any]:   # noqa: F811
    bilan = _redessiner_boutons_sans_menus(gid)
    try:
        bilan["menus"] = rafraichir_menus(gid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[ticket] menus {gid} : {type(e).__name__}: {e}", flush=True)
    return bilan


# ─── trois niveaux : 🧪 Essai › 🌱 Débutant › ⭐ Confirmé ────────────────
# Propriétaire, 24/10/2026 : « de base il est en essai ; à la place de passer
# direct confirmé, passe débutant, et quand il est débutant il y a le bouton
# confirmer ». Le rôle 🌱 Débutant existe sur les trois serveurs (créé à la
# main, entre ⭐ Confirmé et 🧪 Essai). La rangée des managers porte donc
# « 🌱 Passer Débutant » pour un VA en essai, « ⭐ Confirmer le VA » pour un
# débutant, et plus rien une fois confirmé. Un vieux « Confirmer » (menu pas
# encore redessiné) cliqué sur un VA en essai le fait passer débutant : une
# étape à la fois.
ROLE_DEBUTANT_NOM = "🌱 Débutant"
NIVEAUX_ICI = NUMERO_DANS_MENU
_BOUTONS_MANAGERS = _BOUTONS_MANAGERS + ("essai:deb:",)


def role_debutant(gid: str) -> str:
    return _role_nomme(gid, str(_config().get("role_debutant") or ROLE_DEBUTANT_NOM))


def _fiche(gid: str, uid: str) -> Dict[str, Any]:
    return (_etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}


def passer_debutant(gid: str, uid: str, par: str = "") -> Dict[str, Any]:
    """D'essai à débutant. Rend {ok, erreur, reste_essai}. Comme confirmer :
    on POSE d'abord, on RETIRE ensuite — un badge d'essai en trop se voit,
    un VA sans aucun rôle de niveau, non."""
    rd = role_debutant(gid)
    if not rd:
        return {"ok": False, "erreur": f"rôle « {ROLE_DEBUTANT_NOM} » introuvable sur ce serveur"}
    code, rep = _api("PUT", f"/guilds/{gid}/members/{uid}/roles/{rd}")
    if code not in (200, 204):
        return {"ok": False, "erreur": f"Discord a refusé le rôle (HTTP {code}) "
                                       f"{str((rep or {}).get('message') or '')[:80]}"}
    re_ = role_essai(gid)
    reste_essai = False
    if re_:
        c2, _r = _api("DELETE", f"/guilds/{gid}/members/{uid}/roles/{re_}")
        reste_essai = c2 not in (200, 204)
        if reste_essai:
            print(f"[ticket] {uid} débutant mais l'essai n'a pas pu être retiré (HTTP {c2})",
                  flush=True)
    with _VERROU:
        etat = _etat()
        fiche = (etat.setdefault("tickets", {})).setdefault(f"{gid}:{uid}", {})
        fiche["essai"] = False
        fiche["debutant"] = {"par": str(par), "quand": int(time.time())}
        _ecrire_etat(etat)
    return {"ok": True, "erreur": "", "reste_essai": reste_essai}


_confirmer_sans_debutant = confirmer


def confirmer(gid: str, uid: str, par: str = "") -> Dict[str, Any]:   # noqa: F811
    """confirmer (plus haut), et le 🌱 Débutant retiré : un confirmé ne garde
    pas le badge de l'étape d'avant."""
    r = _confirmer_sans_debutant(gid, uid, par)
    if r.get("ok") and str(gid) in NIVEAUX_ICI:
        rd = role_debutant(gid)
        if rd:
            c, _r = _api("DELETE", f"/guilds/{gid}/members/{uid}/roles/{rd}")
            if c not in (200, 204, 404):
                print(f"[ticket] {uid} confirmé, 🌱 Débutant non retiré (HTTP {c})", flush=True)
    return r


_boutons_va_sans_niveaux = boutons_va


def boutons_va(uid: str, confirme: bool = False, a_un_lien: bool = False,   # noqa: F811
               gid: str = "", lien_actif: bool = True):
    """boutons_va (plus haut) ; un VA encore en essai voit « 🌱 Passer
    Débutant » à la place de « Confirmer le VA » (NIVEAUX_ICI)."""
    rangs = _boutons_va_sans_niveaux(uid, confirme=confirme, a_un_lien=a_un_lien,
                                     gid=gid, lien_actif=lien_actif)
    if str(gid) not in NIVEAUX_ICI or confirme or _fiche(str(gid), str(uid)).get("debutant"):
        return rangs
    for r in rangs:
        for i, b in enumerate(r.get("components") or []):
            if str(b.get("custom_id") or "") == f"essai:ok:{uid}":
                r["components"][i] = {"type": 2, "style": 3, "label": "Passer Débutant",
                                      "custom_id": f"essai:deb:{uid}", "emoji": {"name": "🌱"}}
    return rangs


def _clic_debutant(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """« 🌱 Passer Débutant » (ou un vieux « Confirmer » sur un VA en essai) ;
    None quand ce n'est pas ce clic-là."""
    cid = str(((p or {}).get("data") or {}).get("custom_id") or "")
    gid = str((p or {}).get("guild_id") or "")
    if (p or {}).get("type") != 3 or gid not in NIVEAUX_ICI:
        return None
    if not (cid.startswith("essai:deb:") or cid.startswith("essai:ok:")):
        return None
    uid = cid.split(":", 2)[2]
    fiche = _fiche(gid, uid)
    if cid.startswith("essai:ok:") and (fiche.get("debutant") or fiche.get("confirme")):
        return None                        # « Confirmer » d'un débutant : le chemin d'avant
    membre = p.get("member") or {}
    qui = str(((membre.get("user") or {}).get("id")) or "")
    if not _est_manager_brut(gid, membre):
        return _ephemere("Seuls les managers et les helpers peuvent se servir de ces boutons.")
    if fiche.get("confirme"):
        return _ephemere("Ce VA est déjà confirmé.")
    if fiche.get("debutant"):
        return _ephemere("Ce VA est déjà débutant.")
    res = passer_debutant(gid, uid, par=qui)
    if not res["ok"]:
        return _ephemere("✕ " + res["erreur"])
    import liens_va as _lv
    rangs = boutons_va(uid, confirme=False, a_un_lien=bool(_lv.lien_de(gid, uid).get("public_url")),
                       gid=gid, lien_actif=_lv.est_actif(gid, uid))
    msg = p.get("message") or {}
    alerte = ("\n⚠️ Le badge 🧪 Essai n'a pas pu être retiré — à enlever à la main."
              if res.get("reste_essai") else "")
    if str(msg.get("id") or "") == str(fiche.get("menu") or ""):
        # le menu reposé en bas du ticket : son texte reste le sien
        data = {"content": _texte_menu(gid, uid) + alerte, "components": rangs}
    else:
        embeds = msg.get("embeds") or []
        if embeds:
            d = embeds[0].get("description") or ""
            d = "\n".join(l for l in d.split("\n") if "démarres en essai" not in l)
            embeds[0]["description"] = d.rstrip() + f"\n\n🌱 **VA débutant** — par <@{qui}>."
        data = {"embeds": embeds, "components": rangs,
                "content": (msg.get("content") or "") + f"\n🌱 Débutant par <@{qui}>." + alerte}
    data["allowed_mentions"] = {"parse": []}
    return {"type": 7, "data": data}


_traiter_sans_niveaux = traiter


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:   # noqa: F811
    rep = _clic_debutant(p)
    if rep is None:
        return _traiter_sans_niveaux(p)
    if rep.get("type") == 7:
        salon = str((p or {}).get("channel_id") or "")
        mid = str(((p or {}).get("message") or {}).get("id") or "")
        rangs = rep["data"]["components"]
        _en_fond(lambda: _jumeau(salon, mid, rangs))
    return rep


# Le niveau posé À LA MAIN (clic droit › Rôles dans Discord) vaut le bouton :
# propriétaire, 24/10/2026, « soit par rôle, soit dans le ticket, le manager
# peut faire ça ». Luigi, Bowser et Wario ne reçoivent pas les événements de
# Discord : les rôles sont relus à chaque tour des tickets. Le plus haut niveau
# porté décide (⭐ > 🌱 > 🧪) ; ceux du dessous, posés en trop, sont retirés
# comme le ferait le bouton ; la fiche suit, et le menu (accueil, et sa copie
# par le miroir) est redessiné. Un VA sans aucun rôle de niveau : rien ne
# bouge (on ne devine pas). Audit du 20/10/2026 : « rôles, tickets.json et
# accueils désaccordés après des gestes faits à la main ».
_ORDRE_NIVEAUX = ("confirme", "debutant", "essai")


def _ids_niveaux(gid: str) -> Dict[str, str]:
    """{niveau : id du rôle} en une lecture des rôles ; {} si l'un manque."""
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return {}
    cfg = _config()
    noms = {"confirme": str(cfg.get("role_confirme") or ROLE_CONFIRME_NOM),
            "debutant": str(cfg.get("role_debutant") or ROLE_DEBUTANT_NOM),
            "essai": str(cfg.get("role_essai") or ROLE_ESSAI_NOM)}
    par_nom = {str(r.get("name") or "").strip(): str(r.get("id")) for r in rep}
    ids = {n: par_nom.get(nom, "") for n, nom in noms.items()}
    return ids if all(ids.values()) else {}


def _niveau_fiche(f: Dict[str, Any]) -> str:
    if f.get("confirme"):
        return "confirme"
    if f.get("debutant"):
        return "debutant"
    return "essai" if f.get("essai") else ""


def synchroniser_niveaux(gid: str) -> Dict[str, Any]:
    """Un passage : chaque ticket du serveur prend le niveau de ses rôles.
    Rend {suivis: [(uid, avant, après)], nettoyes: [(uid, niveau retiré)],
    rates, ignore}. Liste ou rôles illisibles : rien n'est touché, et dit."""
    import liens_va as lv
    gid = str(gid)
    bilan: Dict[str, Any] = {"suivis": [], "nettoyes": [], "rates": [], "ignore": ""}
    ids = _ids_niveaux(gid)
    if not ids:
        bilan["ignore"] = "rôles de niveau introuvables"
        _dire(f"niveaux:{gid}", f"{gid} : rôles 🧪 / 🌱 / ⭐ introuvables — niveaux non suivis")
        return bilan
    # les porteurs de chaque niveau (la liste filtre par rôle) : un VA sans
    # aucun rôle de niveau n'y est pas, et c'est voulu
    roles_de: Dict[str, set] = {}
    for n in _ORDRE_NIVEAUX:
        membres = _par_la_liste(gid, ids[n], strict=True)
        if membres is None:
            bilan["ignore"] = "liste des membres illisible"
            return bilan
        for m in membres:
            if (m.get("user") or {}).get("id"):
                roles_de[str(m["user"]["id"])] = set(str(r) for r in (m.get("roles") or []))
    _dire(f"niveaux:{gid}", "")
    fiches = {k: dict(v) for k, v in (_etat().get("tickets") or {}).items()
              if str(k).startswith(f"{gid}:") and isinstance(v, dict) and not v.get("parti")}
    for cle, f in sorted(fiches.items()):
        uid = cle.split(":", 1)[1]
        rs = roles_de.get(uid)
        if rs is None:
            continue                       # parti : suivre_departs s'en occupe
        niveau = next((n for n in _ORDRE_NIVEAUX if ids[n] in rs), "")
        if not niveau:
            continue
        for n in _ORDRE_NIVEAUX[_ORDRE_NIVEAUX.index(niveau) + 1:]:
            if ids[n] in rs:
                c, _r = _api("DELETE", f"/guilds/{gid}/members/{uid}/roles/{ids[n]}")
                if c in (200, 204, 404):
                    bilan["nettoyes"].append((uid, n))
                else:
                    bilan["rates"].append(f"{uid} : {n} non retiré (HTTP {c})")
        avant = _niveau_fiche(f)
        if niveau == avant:
            continue
        maintenant = int(time.time())
        with _VERROU:
            d = _etat()
            g = (d.get("tickets") or {}).get(cle)
            if not isinstance(g, dict):
                continue
            if niveau == "confirme":
                g["confirme"] = g.get("confirme") or {"par": "role", "quand": maintenant}
                g["essai"] = False
            elif niveau == "debutant":
                g.pop("confirme", None)
                g["debutant"] = g.get("debutant") or {"par": "role", "quand": maintenant}
                g["essai"] = False
            else:
                g.pop("confirme", None)
                g.pop("debutant", None)
                g["essai"] = True
            _ecrire_etat(d)
        bilan["suivis"].append((uid, avant, niveau))
        salon, mid = str(f.get("salon") or ""), str(f.get("accueil") or "")
        if salon and mid:
            rangs = boutons_va(uid, confirme=niveau == "confirme",
                               a_un_lien=bool(lv.lien_de(gid, uid).get("public_url")),
                               gid=gid, lien_actif=lv.est_actif(gid, uid))
            c, _r = _api("PATCH", f"/channels/{salon}/messages/{mid}", json={"components": rangs})
            if c not in (200, 404):
                bilan["rates"].append(f"{uid} : menu non redessiné (HTTP {c})")
    if bilan["suivis"] or bilan["nettoyes"] or bilan["rates"]:
        print(f"[ticket] niveaux {gid} : {bilan['suivis']} ; retirés {bilan['nettoyes']}"
              + (f" ; ratés {bilan['rates']}" if bilan["rates"] else ""), flush=True)
    return bilan


# ─── le menu ramené en bas, chaque heure ────────────────────────────────
# Propriétaire, 25/10/2026 : « un truc qui renvoie le menu, toujours le menu
# d'accueil, généré toutes les heures, et remove les autres ». La nuit
# d'avant, ramener_menu lancé à la main avait posé les 35 copies d'Agency ;
# Twitter (25 tickets) et Threads (12) n'en avaient presque aucune. Chaque
# heure, chaque ticket en service passe par ramener_menu : déjà en bas, rien
# n'est écrit (pas de bruit) ; sinon, copie neuve en bas, l'ancienne retirée.
# Avant lui, le ménage : les copies du menu que la fiche ne connaît pas, et
# les avis « … a épinglé un message » de NOS bots — au relevé du 25/10, un
# sous chaque accueil épinglé (25 sur Twitter, 16 sur Threads, 35 sur
# Agency), et aucune copie orpheline. L'accueil, la copie de la fiche, les
# messages des membres, la carte numéro et les avis posés par un humain ne
# sont jamais touchés.
MENUS_HEURE_ICI = NUMERO_DANS_MENU
MENUS_HEURE_S = 3600
#: une fois par jour, le ménage relit tout le ticket (les avis du 22/10 sont
#: loin au-dessus) ; les autres heures, les derniers messages suffisent
MENAGE_PROFOND_S = 86400
MENAGE_DERNIERS = 50
#: nos bots : Yoshi (principal) et Peach (admin) manquent à
#: verif_discord.bots(), qui ne tient que les bots REST ; Bowser y vient de la
#: config (absente, son id manquait). verif_discord.bots() s'y ajoute : un bot
#: remplacé est reconnu sans toucher ici.
BOTS_CONNUS = {"1505416430840189041",     # Yoshi
               "1509505792666108074",     # Peach
               "1552153790701117480",     # Luigi (Twitter)
               "1552789379574145126",     # Bowser (Threads)
               "1552785601051365516"}     # Wario (Agency)
#: ramener_menu poste PUIS écrit la fiche : une copie de moins de 5 min n'est
#: jamais prise pour une orpheline (un clic peut être en train de la poser)
COPIE_JEUNE_S = 300
_PAS_TICKET_S = 1.0
_PAS_SUPPRESSION_S = 0.5
_MENUS_VU: Dict[str, float] = {}
_PROFOND_VU: Dict[str, float] = {}
_MENUS_EN_COURS: set = set()


def _nos_bots() -> set:
    import verif_discord as vd
    return ({str(b.get("app_id") or "") for b in vd.bots()} | BOTS_CONNUS) - {""}


def _age_message_s(mid: Any, maintenant: Optional[float] = None) -> float:
    """L'âge d'un message, lu dans son id (l'heure Discord y est écrite)."""
    try:
        return (maintenant or time.time()) - ((int(mid) >> 22) + 1420070400000) / 1000
    except (TypeError, ValueError):
        return 0.0


def est_copie_du_menu(m: Dict[str, Any], bots: set) -> bool:
    """Une copie du menu : de nos bots, « 📋 Menu » en tête, des boutons. La
    carte numéro (composants v2, sans texte) et l'accueil (un encart) n'en
    sont pas."""
    return (str((m.get("author") or {}).get("id") or "") in bots
            and m.get("type") in (0, 19) and bool(m.get("components"))
            and str(m.get("content") or "").startswith("📋 **Menu**"))


def _menage_ticket(gid: str, uid: str, salon: str, bots: set,
                   profond: bool = False) -> Dict[str, int]:
    """Retire de `salon` les copies du menu que la fiche ne connaît pas et les
    avis d'épingle de nos bots. Rend {copies, avis, rates, absent}."""
    out = {"copies": 0, "avis": 0, "rates": 0, "absent": 0}
    avant, pages = "", 0
    while True:
        lim = 100 if profond else MENAGE_DERNIERS
        code, ms = _api("GET", f"/channels/{salon}/messages?limit={lim}"
                               + (f"&before={avant}" if avant else ""))
        if code != 200 or not isinstance(ms, list):
            # 404 : salon supprimé (entretenir_accueils s'en charge, une fois
            # par jour) — rien à y reposer
            out["absent" if code == 404 else "rates"] += 1
            if code != 404:
                print(f"[ticket] ménage du ticket de {uid} : lecture refusée (HTTP {code})",
                      flush=True)
            return out
        # relue à chaque page : une copie posée par un clic entre-temps
        f = _fiche(gid, uid)
        garder = {str(f.get("menu") or ""), str(f.get("accueil") or "")} - {""}
        for m in ms:
            mid = str(m.get("id") or "")
            if not mid or mid in garder or _age_message_s(mid) < COPIE_JEUNE_S:
                continue
            if m.get("type") == 6 and str((m.get("author") or {}).get("id") or "") in bots:
                quoi = "avis"
            elif est_copie_du_menu(m, bots):
                quoi = "copies"
            else:
                continue
            c, _r = _api("DELETE", f"/channels/{salon}/messages/{mid}")
            if c in (200, 204, 404):
                out[quoi] += 1
            else:
                out["rates"] += 1
                print(f"[ticket] ménage du ticket de {uid} : {mid} non retiré (HTTP {c})", flush=True)
            time.sleep(_PAS_SUPPRESSION_S)
        pages += 1
        if not profond or len(ms) < 100 or pages >= 50:
            return out
        avant = str(ms[-1].get("id") or "")
        time.sleep(_PAS_SUPPRESSION_S)


def ramener_menus(gid: str, profond: Optional[bool] = None) -> Dict[str, Any]:
    """Le tour de l'heure sur un serveur : ménage, puis ramener_menu, ticket
    par ticket. Un bilan court au journal, à chaque tour. Ne lève jamais."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"tickets": 0, "ramene": 0, "deja": 0, "echec": [],
                             "sans_accueil": [], "copies": 0, "avis": 0, "rates": 0}
    if gid in _MENUS_EN_COURS:
        return bilan
    _MENUS_EN_COURS.add(gid)
    try:
        if profond is None:
            profond = time.time() - _PROFOND_VU.get(gid, 0) >= MENAGE_PROFOND_S
        if profond:
            _PROFOND_VU[gid] = time.time()
        bots = _nos_bots()
        fiches = sorted((k, dict(v)) for k, v in (_etat().get("tickets") or {}).items()
                        if str(k).startswith(f"{gid}:") and isinstance(v, dict)
                        and v.get("salon") and not v.get("parti"))
        for cle, f in fiches:
            uid = cle.split(":", 1)[1]
            if not f.get("accueil"):
                # pas d'accueil, pas de menu à recopier : dit, pas écarté
                bilan["sans_accueil"].append(uid)
                continue
            bilan["tickets"] += 1
            try:
                m = _menage_ticket(gid, uid, str(f["salon"]), bots, profond=profond)
                for k in ("copies", "avis", "rates"):
                    bilan[k] += m[k]
                if m["absent"]:
                    bilan["echec"].append(f"{uid} (salon introuvable)")
                    continue
            except Exception as e:                           # noqa: BLE001
                bilan["rates"] += 1
                print(f"[ticket] ménage du ticket de {uid} : {type(e).__name__}: {e}", flush=True)
            r = ramener_menu(gid, uid, str(f["salon"]))
            if r in ("ramene", "deja"):
                bilan[r] += 1
            else:
                bilan["echec"].append(uid)
            time.sleep(_PAS_TICKET_S)
        print(f"[ticket] menus de l'heure {gid} : {bilan['tickets']} ticket(s), "
              f"{bilan['ramene']} ramené(s) en bas, {bilan['deja']} déjà en bas"
              + (f", échecs {bilan['echec']}" if bilan["echec"] else "")
              + f" ; ménage{' complet' if profond else ''} : {bilan['copies']} copie(s) "
                f"orpheline(s), {bilan['avis']} avis d'épingle retiré(s)"
              + (f", {bilan['rates']} raté(s)" if bilan["rates"] else "")
              + (f" ; sans accueil : {bilan['sans_accueil']}" if bilan["sans_accueil"] else ""),
              flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[ticket] menus de l'heure {gid} : {type(e).__name__}: {e}", flush=True)
    finally:
        _MENUS_EN_COURS.discard(gid)
    return bilan


# ─── 📤 Spoofer et ⬇️ Download (TRUST INSTAGRAM, 30/10/2026) ─────────────
# Propriétaire : les outils des salons perso de Youl4b dans le ticket, « je
# veux vraiment un ticket pour le VA comme maintenant », puis « vas-y ajoute
# dans trust agency ». Deux boutons de la rangée du VA (préfixe « outk: »,
# hors _BOUTONS_MANAGERS), juste avant « 📱 Numéro », qui reste le dernier
# (BOUTONS_VERSION 6) : 💳 · 📈 · 📤 · ⬇️ · 📱 — cinq, le plafond d'une
# rangée ; un bouton de plus déborderait sur une rangée (_deux_rangees) au
# lieu de faire refuser le menu. Enveloppe, et pas une ligne dans boutons_va :
# le patch du VPS 99-z-tickets-subs-total réécrit le corps d'origine. Le clic
# est à outils_tickets (traiter, plus haut, rend None pour « outk: »).
OUTILS_DANS_MENU = {AGENCY_IG_ID}
#: Le préfixe des clics servis par outils_tickets (il le lit ici).
OUTILS_PREFIXE = "outk:"
_boutons_va_sans_outils = boutons_va


def boutons_outils(uid: str) -> List[Dict[str, Any]]:
    """📤 Spoofer et ⬇️ Download. Décrits ICI, pas demandés à outils_tickets :
    quand la rangée venait de son import, un module absent ou cassé un instant
    (oublié d'un commit, poussé au suivant) donnait une rangée sans eux, que
    redessiner_boutons marquait pourtant à jour (BOUTONS_VERSION) — ni les
    accueils ni leurs copies ne les recevaient plus jamais. Le module ne sert
    que les clics : absent, un clic répond « réessaie », et ça remarche dès
    qu'il arrive, sans redessin."""
    return [{"type": 2, "style": 2, "label": "Spoofer", "emoji": {"name": "📤"},
             "custom_id": f"{OUTILS_PREFIXE}spf:{uid}"},
            {"type": 2, "style": 2, "label": "Download", "emoji": {"name": "⬇️"},
             "custom_id": f"{OUTILS_PREFIXE}dl:{uid}"}]


def boutons_va(uid: str, confirme: bool = False, a_un_lien: bool = False,   # noqa: F811
               gid: str = "", lien_actif: bool = True):
    rangs = _boutons_va_sans_outils(uid, confirme=confirme, a_un_lien=a_un_lien,
                                    gid=gid, lien_actif=lien_actif)
    if str(gid) not in OUTILS_DANS_MENU:
        return rangs
    neufs = boutons_outils(str(uid))
    plats = [b for r in rangs for b in (r.get("components") or [])]
    deja = {str(b.get("custom_id") or "") for b in plats}
    neufs = [b for b in neufs if b["custom_id"] not in deja]
    if not neufs:
        return rangs
    i = next((k for k, b in enumerate(plats) if b.get("custom_id") == "numx:menu"), None)
    if i is None:                       # sans Numéro : au bout de la rangée du VA
        i = max([k + 1 for k, b in enumerate(plats)
                 if not str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)] or [0])
    plats[i:i] = neufs
    return _deux_rangees([{"type": 1, "components": plats}])


# ─── Un ramener_menu à la fois par ticket ────────────────────────────────
# Depuis les outils (30/10/2026), le menu est reposé après chaque livraison, de
# deux fils différents (le spoof dans un fil du site, le téléchargement sur la
# boucle de Yoshi), en plus du tour de l'heure et de 📱 Numéro. Deux appels
# en même temps lisaient tous deux « menu pas en bas », postaient chacun une
# copie et l'épinglaient, puis retiraient la même ancienne : la fiche ne
# gardait que la dernière, l'autre restait épinglée, orpheline, jusqu'au
# ménage — qui ne la voit plus derrière trente posts d'un « Tout ». Enveloppe
# plutôt que dans le corps : les appels du module (ramener_menus) passent par
# ce nom, donc par elle, et le corps garde ses lignes.
_VERROUS_MENU: Dict[str, threading.RLock] = {}
_ramener_menu_sans_verrou = ramener_menu


def ramener_menu(gid: str, uid: str, salon: str, en_dernier: bool = False) -> str:  # noqa: F811
    with _VERROU:
        verrou = _VERROUS_MENU.setdefault(str(salon), threading.RLock())
    with verrou:
        return _ramener_menu_sans_verrou(gid, uid, salon, en_dernier=en_dernier)


ramener_menu.__doc__ = _ramener_menu_sans_verrou.__doc__


# ─── 🎬 Contenu (TRUST INSTAGRAM, 30/10/2026) ───────────────────────────
# Propriétaire : le menu des identités US dans le ticket des VA de TRUST
# INSTAGRAM, le contenu livré « dans leur ticket de base » (« je trouve que
# c'est plutôt pas mal »). La rangée du VA est pleine (💳 · 📈 · 📤 · ⬇️ · 📱 :
# cinq, un sixième ferait refuser le menu entier) : le bouton a SA rangée,
# la 2e du VA, au-dessus de celle des managers. Toujours la sienne, même
# quand la première a de la place : le VA le retrouve au même endroit d'un
# ticket à l'autre. Enveloppe en fin de fichier, comme les outils : le patch
# du VPS 99-z-tickets-subs-total réécrit le corps d'origine. Le clic est à
# contenu_tickets (préfixes hors _BOUTONS_MANAGERS : traiter, plus haut, rend
# None pour eux). Twitter et Threads ne changent pas.
CONTENU_DANS_MENU = {AGENCY_IG_ID}
#: Les préfixes des clics servis par contenu_tickets (il les lit ici) : le
#: panneau et ses menus, puis le ✨ General.
CONTENU_PREFIXE = "cnt:"
CONTENU_GENERAL_PREFIXE = "cng:"
_boutons_va_sans_contenu = boutons_va


def bouton_contenu(uid: str) -> Dict[str, Any]:
    """« 🎬 Contenu ». Décrit ICI, comme 📤 et ⬇️ : la rangée ne dépend pas
    du module qui sert les clics (absent un instant, un clic répond
    « réessaie », et le menu, marqué à jour par BOUTONS_VERSION, garde son
    bouton)."""
    return {"type": 2, "style": 1, "label": "Contenu", "emoji": {"name": "🎬"},
            "custom_id": f"{CONTENU_PREFIXE}o:{uid}"}


def boutons_va(uid: str, confirme: bool = False, a_un_lien: bool = False,   # noqa: F811
               gid: str = "", lien_actif: bool = True):
    rangs = _boutons_va_sans_contenu(uid, confirme=confirme, a_un_lien=a_un_lien,
                                     gid=gid, lien_actif=lien_actif)
    if str(gid) not in CONTENU_DANS_MENU:
        return rangs
    bouton = bouton_contenu(str(uid))
    plats = [b for r in rangs for b in (r.get("components") or [])]
    if any(b.get("custom_id") == bouton["custom_id"] for b in plats):
        return rangs
    va = [b for b in plats if not str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)]
    chefs = [b for b in plats if str(b.get("custom_id") or "").startswith(_BOUTONS_MANAGERS)]
    # Cinq par rangée, cinq rangées au plus : Discord refuse le menu ENTIER
    # au-delà (VA, 🎬, managers : trois aujourd'hui).
    lignes = ([va[i:i + 5] for i in range(0, len(va), 5)] + [[bouton]]
              + [chefs[i:i + 5] for i in range(0, len(chefs), 5)])
    return [{"type": 1, "components": l} for l in lignes if l]
