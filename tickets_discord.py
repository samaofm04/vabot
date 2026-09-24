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
    # Le lien GetMySocial vise l'espace EMY TWITTER : sur un autre serveur, le
    # bouton creerait un lien Twitter pour un VA Threads. Pas de bouton, pas
    # de lien au mauvais endroit.
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
    return [{"type": 1, "components": rang}] if rang else []


# compatibilité : l'ancien nom sert encore dans les rattrapages
def bouton_confirmer(uid: str):
    return boutons_va(uid)


def _differer() -> Dict[str, Any]:
    """« Je m'en occupe » : Discord n'attend que 3 s, la chaîne en prend plus."""
    return {"type": 5, "data": {"flags": 64}}


def _suite(jeton: str, texte: str) -> None:
    """Complète la réponse différée, visible du seul manager qui a cliqué."""
    try:
        from verif_discord import APP_ID
    except Exception:
        return
    _api("PATCH", f"/webhooks/{APP_ID}/{jeton}/messages/@original",
         json={"content": texte[:1900]})


def _en_fond(f):
    import threading
    threading.Thread(target=f, daemon=True).start()


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
    if p.get("type") != 3:
        return None
    cid = str(((p.get("data") or {}).get("custom_id")) or "")
    if not (cid.startswith("essai:ok:") or cid.startswith("lien:new:")
            or cid.startswith("lien:off:") or cid.startswith("lien:on:")):
        return None
    gid = str(p.get("guild_id") or "")
    uid = cid.split(":", 2)[2]
    membre = p.get("member") or {}
    qui = str(((membre.get("user") or {}).get("id")) or "")

    rid = role_manager(gid)
    permissions = int(str(membre.get("permissions") or "0") or 0)
    admin = bool(permissions & 0x8)
    if not (admin or (rid and rid in (membre.get("roles") or []))):
        return _ephemere("Seuls les managers peuvent se servir de ces boutons.")

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
    empeche = liens_va.manque()
    if empeche:
        return _ephemere("Rien n'a été créé — " + empeche)

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
                          f'{r["public_url"]}{rang}{note}')
            if salon:
                _api("POST", f"/channels/{salon}/messages",
                     json={"content": f'🔗 <@{uid}>, voici **ton lien** : {r["public_url"]}\n'
                                      "C'est celui-là que tu postes sur Twitter — il compte "
                                      "tes subs pour le podium.",
                           "allowed_mentions": {"users": [uid]}})
        else:
            sup = f'\n⚠️ Tracking link déjà créé : {r["tracking"]}' if r.get("tracking") else ""
            _suite(jeton, "✕ " + str(r.get("erreur") or "échec") + sup)

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
    if r["public_url"] not in d:
        bas = (f'\n\n🔗 **Ton lien** — celui que tu postes sur Twitter :\n'
               f'{r["public_url"]}\n_Il compte tes subs pour le podium._')
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
        etat = _etat()
        fiches = etat.setdefault("tickets", {})
        cle = f"{gid}:{uid}"
        deja = fiches.get(cle) or {}
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
        if rid:
            droits.append({"id": rid, "type": 0, "allow": str(MANAGER), "deny": "0"})
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

        fiches[cle] = {"salon": salon, "manager": mid, "ouvert": int(time.time()),
                       "essai": bool(en_essai),
                       # l'identifiant de l'accueil epingle : c'est LUI qu'on
                       # completera avec le lien, pour que le VA l'ait toujours
                       # sous les yeux au lieu de le chercher dans l'historique
                       "accueil": str(rep_m.get("id") or "")}
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
