"""comptes_tickets.py — « 📷 Mes comptes » des VA de TRUST INSTAGRAM.

Propriétaire, 08/11/2026, devant @lia sur la page Jailbreak (Accounts) :
comme sur Va IG, « un truc qui s'appelle mes comptes, ça leur donne le lien
pour qu'ils puissent ajouter des comptes avec le lien », et « quand le mec il
ajoute des comptes, ça prend son @Discord ». Ses choix du même jour : le
bouton dans le menu du ticket ET dans le 📋 menu du salon commun, le @Discord
seulement (l'email Discord, aucun bot ne le reçoit : il faudrait une connexion
« avec Discord » sur la page), pas de maximum de comptes.

- Le lien est celui du portail du site (va_portal, /mes-comptes/<jeton>),
  celui que le dashboard donne déjà aux VA de Jessye : les comptes arrivent
  sur la page Jailbreak sous la model du serveur (MODELE), rattachés au VA.
- La fiche porte l'identifiant Discord du VA (« abdoul_9684 ») comme nom et
  comme pseudo, comme le bouton de Va IG (cogs/user._enregistrer_comptes_fr) :
  une autre règle ferait deux sortes de fiches sur la même page.
- Un nom déjà porté par un AUTRE pseudo Discord n'est pas écrasé : le VA le
  lit, un manager tranche. Jamais de fiche prise en silence.
- Le lien est stable : recliquer rend le même (va_portal.creer_lien est
  idempotent), celui qui circule déjà ne casse pas.
- LE LIEN SUIT L'ID DISCORD, PAS LE PSEUDO. Un pseudo se change et se libère :
  relu à la relecture du 08/11, un VA qui reprenait l'ancien pseudo d'un autre
  recevait SA page (mots de passe, 2FA, retrait de comptes), et celui qui
  s'était renommé tombait sur une fiche neuve et vide. Le jeton donné à un id
  est gardé (LIAISONS_FILE) et rendu tant qu'il vit ; un pseudo déjà lié à un
  autre id est refusé. Le jeton suit les renommages faits sur le site.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import safe_json

AGENCY_IG_ID = "1488331963575177247"

#: Serveur → model dont la page Jailbreak reçoit les comptes.
MODELE: Dict[str, str] = {AGENCY_IG_ID: "lia"}

#: Le préfixe des clics : celui du bouton, décrit dans tickets_discord
#: (bouton_comptes), qui le pose à côté de 🎬 et dans le menu commun.
PREFIXE = "cpt:"

TEXTE_NOM_PRIS = ("❌ Le nom **{nom}** est déjà utilisé sur la page de {model} par un autre "
                  "compte Discord. Préviens un manager.")
TEXTE_PANNE = "❌ Ta page n'a pas pu être préparée. Réessaie dans un instant."

#: {model: {id Discord du VA: jeton du portail}}.
LIAISONS_FILE = Path("data") / "comptes_tickets.json"
_VERROU = threading.Lock()


def _propre(nom: Any) -> str:
    """L'identifiant Discord tel que tickets_discord.identifiant le nettoie."""
    return re.sub(r"[^a-z0-9._-]+", "-", str(nom or "").strip().lower()).strip("-")[:60]


def fiche(model: str, nom: str) -> Tuple[bool, str]:
    """(True, "") quand la fiche `nom` de `model` existe et porte ce pseudo
    Discord ; (False, raison à dire au VA) sinon. Crée la fiche au besoin."""
    import jailbreak as jb
    if jb.add_va(model, nom, discord_username=nom):
        return True, ""
    # add_va refuse un nom déjà porté (fiche déclarée, ou comptes seuls)
    entree = (jb.list_all() or {}).get(model) or {}
    vas = entree.get("vas") if isinstance(entree, dict) else []
    f = next((v for v in vas or [] if isinstance(v, dict)
              and str(v.get("name") or "").strip().lower() == nom), None)
    pseudo = str((f or {}).get("discord_username") or "").strip().lstrip("@").lower()
    if pseudo == nom:
        return True, ""
    if pseudo:
        print(f"[comptes] {model}/{nom} porte le pseudo Discord « {pseudo} » : laissé tel quel",
              flush=True)
        return False, TEXTE_NOM_PRIS.format(nom=nom, model=model.capitalize())
    # fiche sans pseudo, ou nom porté par des comptes seuls : update_va la
    # matérialise et lui pose le pseudo
    if jb.update_va(model, nom, discord_username=nom):
        return True, ""
    print(f"[comptes] {model}/{nom} : fiche ni créée ni reliée", flush=True)
    return False, TEXTE_PANNE


def lien(gid: str, model: str, nom: str) -> str:
    """L'adresse de la page du VA, sur le domaine de son serveur ; "" si le
    jeton n'a pas pu être écrit."""
    import va_portal as vp
    jeton = vp.creer_lien(model, nom)
    # creer_lien rend son jeton même quand l'écriture a raté : relu ici, un
    # lien qui répondrait « plus valable » au premier clic ne part pas
    if not jeton or vp.resoudre(jeton) is None:
        return ""
    return adresse(gid, jeton)


def adresse(gid: str, jeton: str) -> str:
    import domaines
    import va_portal as vp
    return f"{domaines.site(gid)}{vp.RACINE}/{jeton}"


def _liaisons() -> Dict[str, Dict[str, str]]:
    d = safe_json.load(LIAISONS_FILE, {})
    return d if isinstance(d, dict) else {}


def _fiche_vivante(model: str, nom: str) -> bool:
    import jailbreak as jb
    entree = (jb.list_all() or {}).get(model) or {}
    return isinstance(entree, dict) and nom.lower() in jb.noms_occupes(entree)


def page_du_va(gid: str, uid: str, nom_actuel: str) -> Tuple[str, str, str]:
    """(adresse, nom de la fiche, refus) pour le VA `uid` : sa page déjà liée
    si elle vit encore, sinon une neuve au nom `nom_actuel` (son identifiant
    Discord d'aujourd'hui). `nom_actuel` vide : seule une page liée sert."""
    import va_portal as vp
    model = MODELE[gid]
    with _VERROU:
        d = _liaisons()
        a_lui = d.setdefault(model, {})
        jeton = str(a_lui.get(uid) or "")
        rec = vp.resoudre(jeton) if jeton else None
        if rec is not None:
            nom = str(rec.get("va") or "")
            if nom and _fiche_vivante(model, nom):
                return adresse(gid, jeton), nom, ""
        # pas de page liée, ou fermée / fiche retirée sur le site
        nom = _propre(nom_actuel)
        if not nom or nom.isdigit():
            return "", "", TEXTE_PANNE
        for autre, j in a_lui.items():
            r = vp.resoudre(j) if autre != uid else None
            if r is not None and str(r.get("va") or "").strip().lower() == nom:
                print(f"[comptes] {model}/{nom} déjà lié à l'id {autre} : refusé pour {uid}", flush=True)
                return "", "", TEXTE_NOM_PRIS.format(nom=nom, model=model.capitalize())
        ok, raison = fiche(model, nom)
        if not ok:
            return "", "", raison
        url = lien(gid, model, nom)
        if not url:
            print(f"[comptes] {model}/{nom} : jeton non écrit", flush=True)
            return "", "", TEXTE_PANNE
        a_lui[uid] = url.rsplit("/", 1)[-1]
        if not safe_json.write(LIAISONS_FILE, d):
            print(f"[comptes] liaison {model}/{uid} non écrite", flush=True)
            return "", "", TEXTE_PANNE
        return url, nom, ""


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La réponse à un clic « cpt: », ou None si ce n'est pas le nôtre."""
    p = p or {}
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if p.get("type") != 3 or not cid.startswith(PREFIXE):
        return None
    import outils_tickets as ot
    # le VA du ticket, ou un manager dans ce ticket ; dans le salon commun,
    # le cliqueur et son ticket (une seule règle pour les boutons du ticket)
    t, refus = ot._ticket_du_clic(p, set(MODELE))
    if t is None:
        return ot._ephemere(refus)
    gid, uid = t["gid"], t["uid"]
    a_lui = t["qui"] == uid
    if a_lui:
        nom_actuel = _propre(t.get("nom"))
    else:
        # un manager dans le ticket d'un VA : la page liée à CE VA ; à défaut,
        # son identifiant Discord d'aujourd'hui (jamais le pseudo noté à
        # « Créer son lien », figé, ni le nom affiché)
        import tickets_discord as tk
        code, rep = tk._api("GET", f"/guilds/{gid}/members/{uid}")
        nom_actuel = (_propre((rep.get("user") or {}).get("username"))
                      if code == 200 and isinstance(rep, dict) else "")
    url, nom, refus = page_du_va(gid, uid, nom_actuel)
    if refus:
        return ot._ephemere(refus)
    if a_lui:
        texte = ("📷 **Mes comptes Instagram**\n"
                 "Ajoute tes comptes sur ta page : ils sont rangés à ton nom "
                 f"(**@{nom}**). Garde ce lien pour toi.")
    else:
        texte = f"📷 **Page des comptes de @{nom}**\nLe même lien que le sien, à ne pas diffuser."
    return ot._ephemere(texte, [{"type": 1, "components": [
        {"type": 2, "style": 5, "label": "Ouvrir ma page" if a_lui else "Ouvrir sa page",
         "url": url}]}])
