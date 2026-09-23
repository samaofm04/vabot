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
"""
from __future__ import annotations

import json
import re
import string
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "tickets.json"
CONFIG_FICHIER = DATA_DIR / "tickets_config.json"

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

PREFIXE = "─│"      # « ─│ » : Discord retire « -| » d'un nom de salon texte
BARRE = "┤"              # « ┤ »


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


def role_manager(gid: str) -> str:
    """L'identifiant du rôle Manager du serveur, ou « »."""
    code, rep = _api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(rep, list):
        return ""
    for r in rep:
        if "manager" in str(r.get("name", "")).lower():
            return str(r.get("id"))
    return ""


def _par_la_liste(gid: str, rid: str) -> Optional[List[Dict[str, Any]]]:
    """Les membres via /guilds/{id}/members. None si Discord refuse (403)."""
    code, rep = _api("GET", f"/guilds/{gid}/members", params={"limit": 1000})
    if code != 200 or not isinstance(rep, list):
        return None
    return [m for m in rep if rid in (m.get("roles") or [])]


def _par_la_recherche(gid: str, rid: str) -> List[Dict[str, Any]]:
    """Les membres via la recherche, balayée sur a-z et 0-9 (voir l'en-tête)."""
    trouves: Dict[str, Dict[str, Any]] = {}
    for q in string.ascii_lowercase + string.digits:
        code, rep = _api("GET", f"/guilds/{gid}/members/search",
                         params={"query": q, "limit": 100})
        if code != 200 or not isinstance(rep, list):
            continue
        for m in rep:
            if rid in (m.get("roles") or []):
                trouves[str(((m.get("user") or {}).get("id")))] = m
        time.sleep(0.25)
    return list(trouves.values())


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
        out = [{"user": {"id": str(u)}} for u in poses]
    else:
        rid = role_manager(gid)
        if not rid:
            return []
        out = _par_la_liste(gid, rid)
        if out is None:                       # 403 : l'autorisation manque
            out = _par_la_recherche(gid, rid)
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
    d = _etat()
    tours = d.setdefault("tours", {})
    i = int(tours.get(str(gid)) or 0) % len(liste)
    tours[str(gid)] = (i + 1) % len(liste)
    _ecrire_etat(d)
    return liste[i]


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
    court = (lettres or morceaux or [""])[0]
    return (court or str(u.get("id") or "?")).upper()[:24]


def _salon_existe(cid: str) -> bool:
    return bool(cid) and _api("GET", f"/channels/{cid}")[0] == 200


def categorie_du_manager(gid: str, m: Dict[str, Any]) -> str:
    """La catégorie « 🔵┤ Manager X ├🔵 », créée si elle manque."""
    nom = f"🔵{BARRE} Manager {_nom_court(m)} ├🔵"
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code == 200 and isinstance(rep, list):
        for c in rep:
            if c.get("type") == 4 and c.get("name") == nom:
                return str(c["id"])
    rid = role_manager(gid)
    droits = [{"id": gid, "type": 0, "allow": "0", "deny": str(VOIR)}]
    if rid:
        droits.append({"id": rid, "type": 0, "allow": str(MANAGER), "deny": "0"})
    code, rep = _api("POST", f"/guilds/{gid}/channels",
                     json={"name": nom, "type": 4, "permission_overwrites": droits})
    return str(rep.get("id")) if code == 201 and rep.get("id") else ""


def _pseudo(gid: str, uid: str) -> str:
    code, rep = _api("GET", f"/guilds/{gid}/members/{uid}")
    if code == 200 and isinstance(rep, dict):
        u = rep.get("user") or {}
        brut = rep.get("nick") or u.get("global_name") or u.get("username") or ""
        propre = re.sub(r"[^a-z0-9._-]+", "-", str(brut).lower()).strip("-")
        if propre:
            return propre[:60]
    return f"membre-{uid[-6:]}"


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

        # Déjà un ticket ouvert : on ne le double pas (une deuxième
        # vérification du même membre ne doit pas créer un second salon).
        etat = _etat()
        fiches = etat.setdefault("tickets", {})
        cle = f"{gid}:{uid}"
        deja = fiches.get(cle) or {}
        if deja.get("salon") and _salon_existe(deja["salon"]):
            return str(deja["salon"])

        liste = managers(gid)
        choisi = _prochain(gid, liste)
        rid = role_manager(gid)

        parent = categorie_du_manager(gid, choisi) if choisi else ""
        droits = [{"id": gid, "type": 0, "allow": "0", "deny": str(VOIR)},
                  {"id": uid, "type": 1, "allow": str(MEMBRE), "deny": "0"}]
        if rid:
            droits.append({"id": rid, "type": 0, "allow": str(MANAGER), "deny": "0"})
        if choisi:
            droits.append({"id": str((choisi.get("user") or {}).get("id")),
                           "type": 1, "allow": str(MANAGER), "deny": "0"})

        corps: Dict[str, Any] = {
            "name": f'{PREFIXE}🔵{BARRE}-va-{_pseudo(gid, uid)}',
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
                "Personne d'autre que toi et les managers ne voit ce salon."),
            "footer": {"text": "YouLab • Ton manager te répond ici"},
        }
        mentions = {"users": [uid] + ([mid] if mid else [])}
        if not mid and rid:
            mentions["roles"] = [rid]
        _api("POST", f"/channels/{salon}/messages",
             json={"content": f"<@{uid}> {qui}", "embeds": [embed],
                   "allowed_mentions": mentions})

        fiches[cle] = {"salon": salon, "manager": mid, "ouvert": int(time.time())}
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
