"""Paliers de numéros SMS par rôle, sur TRUST INSTAGRAM.

Propriétaire, 05/11/2026 : « De base, la limite [...] est de 3 numéros par
jour. Crée-moi un rôle pour 10 numéros, un rôle genre step 2, niveau 2 [...]
jusqu'à 20, et [...] le dernier qui débride jusqu'à 50 numéros par jour »,
« uniquement s'ils ont le rôle [...] si un jour je dois leur remove le rôle,
ils n'ont plus accès ».

Une seule table, lue par les deux boutons qui vendent un numéro sur ce
serveur : la carte du ticket (numeros_x_discord, Wario, par REST) et le
panneau de 📱・numéro (cogs/numeros, Rem). Les deux comptent dans le même
historique (numeros_du_jour) : deux tables, et un VA aurait eu 10 d'un côté,
3 de l'autre.

Les rôles sont relus à CHAQUE achat, jamais gardés : le clic porte ceux du
cliqueur, et ceux d'un autre membre (le VA d'une carte) se lisent chez
Discord à ce moment-là. Le rôle retiré, le clic suivant retrouve la limite de
base. Plusieurs paliers : le plus haut. Une lecture ratée (membre introuvable,
Discord muet) : la limite de base, et c'est dit -- une panne ne débride
personne.
"""
from typing import Any, Dict, Iterable, List, Optional

#: {serveur : {id du rôle : numéros par jour}}. Les rôles ont été créés par
#: Wario le 05/11/2026 (creer_roles) ; un rôle renommé garde son id, et donc
#: son palier. Un rôle supprimé ne débride plus personne.
PALIERS: Dict[str, Dict[str, int]] = {
    "1488331963575177247": {          # TRUST INSTAGRAM (verif_discord.AGENCY_IG_ID)
        "1567957800506761308": 10,    # 📱 Niveau 1 · 10 SMS
        "1567957801702268990": 20,    # 📱 Niveau 2 · 20 SMS
        "1567957802838794382": 50,    # 📱 Niveau 3 · 50 SMS
    },
}

#: Les rôles à créer, dans l'ordre (le plus bas d'abord).
NOMS_ROLES = (("📱 Niveau 1 · 10 SMS", 10), ("📱 Niveau 2 · 20 SMS", 20),
              ("📱 Niveau 3 · 50 SMS", 50))


def _log(texte: str) -> None:
    print(f"[paliers] {texte}", flush=True)


def a_des_paliers(gid: Any) -> bool:
    return bool(PALIERS.get(str(gid or "")))


def quota(gid: Any, roles: Optional[Iterable[Any]], base: int) -> int:
    """La limite du jour d'un membre qui porte `roles` (ids) : la base du
    serveur, ou le plus haut palier qu'il porte. `roles` None (illisibles) :
    la base."""
    table = PALIERS.get(str(gid or "")) or {}
    paliers = [int(table[str(r)]) for r in (roles or ()) if str(r) in table]
    return max([int(base)] + paliers)


def roles_rest(gid: Any, uid: Any) -> Optional[List[str]]:
    """Les rôles de `uid` lus chez Discord par le bot du serveur ; None si la
    lecture rate (membre parti, Discord muet)."""
    try:
        import verif_discord as vd
        with vd.sur_serveur(str(gid)):
            code, m = vd.api("GET", f"/guilds/{gid}/members/{uid}")
    except Exception as e:                                   # noqa: BLE001
        _log(f"rôles de {uid} illisibles ({type(e).__name__}: {e}) : limite de base")
        return None
    if code != 200 or not isinstance(m, dict):
        _log(f"rôles de {uid} illisibles (HTTP {code}) : limite de base")
        return None
    return [str(r) for r in m.get("roles") or []]


def creer_roles(gid: str, essai: bool = True) -> Dict[str, Any]:
    """Crée les rôles de NOMS_ROLES qui manquent (même nom exact : repris,
    pas recréé). Sans permission, sans couleur, ni affichés à part ni
    mentionnables : une étiquette. Rend {nom : id}, et ce qui n'a pas pu se
    faire. `essai` : rien n'est écrit, la liste dit ce qui serait fait."""
    import verif_discord as vd
    with vd.sur_serveur(gid):
        code, roles = vd.api("GET", f"/guilds/{gid}/roles")
        if code != 200 or not isinstance(roles, list):
            return {"erreur": f"rôles illisibles (HTTP {code})"}
        deja = {str(r.get("name")): str(r.get("id")) for r in roles}
        out: Dict[str, Any] = {"roles": {}, "crees": [], "repris": [], "essai": essai}
        for nom, n in NOMS_ROLES:
            if nom in deja:
                out["roles"][nom] = deja[nom]
                out["repris"].append(nom)
                continue
            if essai:
                out["crees"].append(nom)
                continue
            code, r = vd.api("POST", f"/guilds/{gid}/roles",
                             json={"name": nom, "permissions": "0", "hoist": False,
                                   "mentionable": False})
            if code != 200 or not isinstance(r, dict) or not r.get("id"):
                out.setdefault("echecs", []).append(f"{nom} (HTTP {code} {str(r)[:120]})")
                continue
            out["roles"][nom] = str(r["id"])
            out["crees"].append(nom)
    return out
