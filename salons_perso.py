"""Chacun son salon : tout membre de l'équipe a son salon perso.

Propriétaire, 31/10/2026 : « il me faut un truc pour fixer les salons […]
tout le monde doit avoir son salon ». Sur TRUST TWITTER, samuel.0314
(🤝 Helper, ancien manager) n'en avait aucun et a dû le demander. Deux trous
dans tickets_discord :
  - ouvrir_tickets_verifies écarte le staff (Manager, Helper) exprès ;
  - il ne sert que les Vérifiés apparus APRÈS son tout premier passage : ceux
    qui étaient déjà là ce jour-là n'en ont jamais eu (3 sur TRUST THREADS).

Ici, à chaque tour des serveurs à tickets (suivre_partout, toutes les 10
minutes), tout le serveur est relu : un membre qui porte un rôle de
ROLES_AVEC_SALON, aucun de ROLES_SANS_SALON, et qui n'a pas de salon vivant
reçoit le sien — le même que celui d'un VA (tickets_discord.ouvrir_ticket :
nom, catégorie du manager, droits, accueil épinglé, menu).

Ce qui n'est JAMAIS refait tout seul : un salon supprimé à la main. vectorofm
a supprimé le sien sur TRUST INSTAGRAM dix minutes après sa création
(23/10/2026), septofm a perdu le sien sur TRUST TWITTER le 24/10 (« non,
laisse », 31/10) ; le recréer toutes les 10 minutes, ce serait se battre
contre le propriétaire. Ces membres sont comptés et dits, pas servis — refaire(gid,
uid) le fait sur demande.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional

import tickets_discord as tk

#: Les rôles qui donnent un salon, lus dans leur nom sans emoji ni accent
#: (« ✅ Vérifié » → verifie) : un rôle redécoré à la main reste reconnu.
#: BOSS compris : propriétaire, 31/10/2026, à la question « qui ? » — Manager,
#: Helper, VA et BOSS.
ROLES_AVEC_SALON = {"boss", "manager", "helper", "verifie", "confirme", "debutant", "essai"}
#: Jamais de salon, même avec un rôle ci-dessus. Vide : ⏳ En attente, 🚩 Suspect
#: et les sans-rôle n'en ont pas parce qu'ils ne sont pas dans la liste du haut.
ROLES_SANS_SALON: set = set()
#: Le staff : pas de 🧪 Essai, pas de « tu es confié à », et un manager reçoit
#: son salon dans SA catégorie.
ROLES_STAFF = {"boss", "manager", "helper"}
#: Déjà un niveau : on ne lui ajoute pas 🧪 (un ⭐ Confirmé resterait marqué
#: en essai). Un ✅ Vérifié sans niveau démarre en essai, comme tout nouveau.
ROLES_NIVEAU = {"confirme", "debutant", "essai"}
#: Salons créés par tour et par serveur : une erreur de rôle (✅ posé à tout le
#: serveur) ne doit pas ouvrir 200 salons d'un coup. Le reste au tour suivant.
MAX_PAR_TOUR = 3


def _mots(nom: Any) -> set:
    """« 🛡️ Manager » → {manager} ; « ⏳ En attente » → {en, attente}."""
    plat = unicodedata.normalize("NFKD", str(nom or "")).lower()
    lettres = "".join(c if c.isascii() and c.isalpha() else " " for c in plat
                      if not unicodedata.combining(c))
    return set(lettres.split())


def _pseudo(m: Dict[str, Any]) -> str:
    return str((m.get("user") or {}).get("username") or tk._uid(m))


def _salon_a_la_main(salons: List[Dict[str, Any]], cats: Dict[str, str], uid: str) -> str:
    """Un salon de VA fait à la main pour ce membre, sans fiche : rangé dans
    une catégorie de manager, il y est nommé comme membre (sans le droit de
    gérer les messages, que le manager a). « » s'il n'y en a pas. En ouvrir
    un second ferait un doublon : on le signale à la place."""
    for c in salons:
        if c.get("type") == 4 or not cats.get(str(c.get("parent_id") or "")):
            continue
        for o in c.get("permission_overwrites") or []:
            if str(o.get("id")) != uid or str(o.get("type", "1")) not in ("1", "member"):
                continue
            try:
                allow = int(str(o.get("allow") or "0"))
            except ValueError:
                continue
            if allow & tk.VOIR and not allow & tk.GERER_MSG:
                return str(c.get("id"))
    return ""


def etat_des_salons(gid: str) -> Optional[Dict[str, Any]]:
    """Qui devrait avoir son salon, et ce qu'il en est. None : Discord muet
    (rôles, salons ou membres illisibles) — dans le doute, rien n'est fait.

    {"servis": n, "manquants": [...], "supprimes": [...], "sans_fiche": [...]},
    chaque entrée {uid, pseudo, nom, roles, staff, essai, salon}."""
    gid = str(gid)
    code, roles = tk._api("GET", f"/guilds/{gid}/roles")
    if code != 200 or not isinstance(roles, list):
        return None
    code, salons = tk._api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        return None
    membres = tk._par_la_liste(gid, None, strict=True)
    if membres is None:
        return None
    noms = {str(r.get("id")): str(r.get("name") or "") for r in roles}
    mots = {rid: _mots(n) for rid, n in noms.items()}
    vivants = {str(c.get("id")) for c in salons}
    cats = {str(c.get("id")): tk._cle_categorie(c.get("name"))
            for c in salons if c.get("type") == 4}
    etat = tk._etat()
    fiches = etat.get("tickets") or {}
    disparus = etat.get("tickets_disparus") or {}
    out: Dict[str, Any] = {"servis": 0, "manquants": [], "supprimes": [], "sans_fiche": []}
    for m in membres:
        u = m.get("user") or {}
        uid = str(u.get("id") or "")
        if not uid or u.get("bot"):
            continue
        les_siens = set().union(*(mots.get(str(r), set()) for r in m.get("roles") or []))
        if les_siens & ROLES_SANS_SALON or not les_siens & ROLES_AVEC_SALON:
            continue
        cle = f"{gid}:{uid}"
        salon = str((fiches.get(cle) or {}).get("salon") or "")
        if salon in vivants:
            out["servis"] += 1
            continue
        x = {"uid": uid, "pseudo": _pseudo(m),
             "nom": str(m.get("nick") or u.get("global_name") or ""),
             "roles": [noms.get(str(r), str(r)) for r in m.get("roles") or []],
             "staff": bool(les_siens & ROLES_STAFF),
             "essai": not les_siens & ROLES_NIVEAU and not les_siens & ROLES_STAFF,
             "salon": ""}
        # une fiche dont le salon n'existe plus : supprimé à la main, depuis
        # moins d'un jour (entretenir_accueils ne l'a pas encore rangée)
        ancien = salon or str((disparus.get(cle) or {}).get("salon") or "")
        if ancien:
            x["salon"] = ancien
            out["supprimes"].append(x)
            continue
        main = _salon_a_la_main(salons, cats, uid)
        if main:
            x["salon"] = main
            out["sans_fiche"].append(x)
            continue
        out["manquants"].append(x)
    return out


def _qui(liste: List[Dict[str, Any]]) -> str:
    return ", ".join(x["pseudo"] for x in liste[:8]) + (f" (+{len(liste) - 8})" if len(liste) > 8 else "")


def reparer_salons(gid: str, ecrire: bool = True,
                   max_par_tour: int = MAX_PAR_TOUR) -> Dict[str, Any]:
    """Un tour : ouvre le salon de chaque membre qui n'en a pas (au plus
    max_par_tour). `ecrire` False : ne crée rien, rend ce qui serait créé
    (« a_creer »). Ne lève jamais : l'appelant est la boucle du podium."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"crees": [], "rates": [], "reportes": [], "a_creer": [],
                             "supprimes": [], "sans_fiche": [], "servis": 0, "ignore": ""}
    try:
        e = etat_des_salons(gid)
    except Exception as ex:                                  # noqa: BLE001
        e = None
        bilan["ignore"] = f"{type(ex).__name__}: {ex}"
    if e is None:
        bilan["ignore"] = bilan["ignore"] or "rôles, salons ou membres illisibles"
        tk._dire(f"salons-perso:{gid}", f"{gid} : salons perso — {bilan['ignore']}, rien touché")
        return bilan
    tk._dire(f"salons-perso:{gid}", "")
    for k in ("servis", "supprimes", "sans_fiche"):
        bilan[k] = e[k]
    # Dit une fois (pas toutes les 10 minutes), redit si la liste change
    tk._dire(f"salons-perso-laisses:{gid}",
             (f"{gid} : salon supprimé à la main, pas refait : {_qui(e['supprimes'])}. "
              if e["supprimes"] else "")
             + (f"{gid} : salon fait à la main sans fiche, pas doublé : {_qui(e['sans_fiche'])}"
                if e["sans_fiche"] else ""))
    if not ecrire:
        bilan["a_creer"] = e["manquants"]
        return bilan
    cfg = None
    try:
        from verif_discord import serveur
        cfg = serveur(gid)
    except Exception as ex:                                  # noqa: BLE001
        bilan["ignore"] = f"serveur inconnu : {type(ex).__name__}: {ex}"
        return bilan
    for x in e["manquants"]:
        if len(bilan["crees"]) + len(bilan["rates"]) >= max_par_tour:
            bilan["reportes"].append(x)
            continue
        salon = tk.ouvrir_ticket(x["uid"], cfg, essai=x["essai"], staff=x["staff"])
        (bilan["crees"] if salon else bilan["rates"]).append(dict(x, salon=salon))
    if bilan["crees"] or bilan["rates"]:
        print(f"[salons] {gid} : {len(bilan['crees'])} salon(s) perso ouvert(s)"
              + (f" ({_qui(bilan['crees'])})" if bilan["crees"] else "")
              + (f", raté(s) : {_qui(bilan['rates'])}" if bilan["rates"] else "")
              + (f", {len(bilan['reportes'])} au prochain tour" if bilan["reportes"] else ""),
              flush=True)
    return bilan


def refaire(gid: str, uid: str) -> str:
    """Rouvre, sur demande, le salon d'un membre dont le salon a été supprimé
    à la main. Rend l'identifiant du nouveau salon, ou « »."""
    e = etat_des_salons(gid) or {}
    x = next((y for k in ("supprimes", "manquants") for y in e.get(k) or []
              if y["uid"] == str(uid)), None)
    if not x:
        return ""
    from verif_discord import serveur
    return tk.ouvrir_ticket(x["uid"], serveur(str(gid)), essai=x["essai"], staff=x["staff"])
