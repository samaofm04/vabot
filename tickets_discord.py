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
SERVEURS_TICKETS = {"1445108485090971710",    # YouLab TWITTER
                    "1498948161039896586"}    # YouLab THREADS

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
    poses = (_config().get("managers") or {}).get(gid) or []
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


def _creer_lien(gid: str, uid: str, par: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Le bouton « Créer son lien » : MyPuls puis GetMySocial, en différé.

    Rien n'est créé tant que la configuration manque : MyPuls ne sait pas
    supprimer un tracking link, un lien posé chez la mauvaise modèle resterait
    là pour toujours.
    """
    import liens_va
    if str(gid) not in liens_va.SERVEURS:
        return _ephemere("Les liens GetMySocial ne sont pas encore branchés sur ce serveur.")
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
        r = liens_va.creer_pour(gid, uid, pseudo, par=par,
                                manager=nom_manager(gid, uid))
        if r.get("ok"):
            _poser_lien_dans_accueil(gid, uid, salon, r)
            note = ("\n⚠️ Destination provisoire (celle du gabarit) : le tracking "
                    "link MyPuls reste à créer et à rattacher."
                    if r.get("provisoire") else "")
            rang = f' · rangé dans **{r["groupe"]}**' if r.get("groupe") else ""
            _suite(jeton, f'✅ VA {r.get("numero")} — lien créé pour <@{uid}> : '
                          f'{r["public_url"]}{rang}{note}', p)
            if salon:
                _api("POST", f"/channels/{salon}/messages",
                     json={"content": f'🔗 <@{uid}>, voici **ton lien** : {r["public_url"]}\n'
                                      + ("C'est celui-là que tu postes sur Twitter — il compte "
                                         "tes subs pour le podium." if plateforme == "Twitter"
                                         else f"C'est celui-là que tu mets sur {plateforme}."),
                           "allowed_mentions": {"users": [uid]}})
        else:
            sup = f'\n⚠️ Tracking link déjà créé : {r["tracking"]}' if r.get("tracking") else ""
            _suite(jeton, "✕ " + str(r.get("erreur") or "échec") + sup, p)

    _EN_FOND(travail)
    return _differer()


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
            "name": f'{PREFIXE}🔵{BARRE}-va-{AROBASE}{identifiant(gid, uid)}',
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
    poses = (_config().get("managers") or {}).get(gid) or []
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
        _synchro_liens(gid, sur_serveur)
    return out


# Les liens GetMySocial suivent les catégories (liens_va.synchroniser) : pour
# Twitter, la boucle du podium s'en charge (web_upload._sync_liens_va) ; Threads
# n'y passe pas (podium seul), alors c'est ici, juste après le rangement des VA
# qu'elle doit suivre. Pas les deux pour un même serveur : l'outil GetMySocial
# est limité en débit.
SYNCHRO_LIENS_ICI = {"1498948161039896586"}      # YouLab THREADS
SYNCHRO_LIENS_S = 1800
_SYNCHRO_VUE: Dict[str, float] = {}


def _synchro_liens(gid: str, sur_serveur) -> None:
    if gid not in SYNCHRO_LIENS_ICI:
        return
    if time.time() - _SYNCHRO_VUE.get(gid, 0) < SYNCHRO_LIENS_S:
        return
    _SYNCHRO_VUE[gid] = time.time()
    try:
        import liens_va
        with sur_serveur(gid):
            redessiner_boutons(gid)
            b = liens_va.synchroniser(gid)
        if any(b.get(k) for k in ("groupes_crees", "deplaces", "rates")):
            print(f"[lien] synchro {gid} : {b}", flush=True)
    except Exception as e:
        print(f"[lien] synchro {gid} : {type(e).__name__}: {e}", flush=True)


# Les accueils ouverts AVANT que Threads ait ses liens (13/10/2026) n'ont pas
# « Créer son lien » : boutons_va ne le mettait pas hors de Twitter. Sans ce
# rattrapage, ces VA restaient sans bouton pour toujours. Une fois par accueil
# (« boutons » dans la fiche), pas à chaque tour.
BOUTONS_VERSION = 2


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
