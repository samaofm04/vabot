# -*- coding: utf-8 -*-
"""planning_roles.py — les roles Discord par shift et par model, et le
rangement du planning des chatteurs d'apres ces roles.

DEMANDE DU PROPRIETAIRE (18/11/2026, validee le 19 : « Oui, vas-y ») : sur son
serveur Discord des chatteurs (YouLab AGENCY), un role par SHIFT et un role
par MODEL (« Amelia MYM »...), que ses managers attribuent. Le site lit ces
roles et range le planning tout seul : chaque chatteur dans le bon planning
(MYM ou OnlyFans), dans le bloc de son shift, avec sa ou ses models.

CE MODULE NE PARLE PAS A DISCORD. Il recoit la liste des membres et celle des
roles (lues par web_upload, avec le bot sans programme) et il decide. Tout ce
qui est ici se teste sans bot ni reseau.

LES REGLES, DANS L'ORDRE OU ELLES COMPTENT

  1. RIEN N'EST EFFACE. Une ligne dont le chatteur a perdu ses roles reste, avec
     son historique de presence ; elle est seulement marquee « perdu ». Un
     manager qui retire un role par erreur ne doit pas faire disparaitre trois
     mois de presences.
  2. ON NE TOUCHE QUE CE QUI EST RELIE A UN DISCORD. Une ligne saisie a la main
     sans pseudo Discord n'est jamais deplacee : rien ne dit de qui elle parle.
     Seule exception, sure : son nom est EXACTEMENT le surnom d'un membre range
     — on y pose alors son pseudo au lieu de creer un doublon.
  3. IL FAUT LES DEUX ROLES. Un shift sans model (ou l'inverse) ne range rien :
     le chatteur est compte « incomplet » et l'ecran le nomme, pour que le
     manager voie quoi finir.
  4. UNE LIGNE JAMAIS RANGEE PAR UN ROLE N'EST PAS ACCUSEE. Le jour de la mise
     en service, personne n'a de role : marquer toutes les lignes « sans role »
     aurait couvert le planning d'alertes pour rien.
"""
from __future__ import annotations

import time
import unicodedata
from typing import Any, Dict, List, Optional

import chatting

#: Les models, par plateforme. Seulement celles que MyPuls connait (decision du
#: proprietaire : « mets que les modeles que tu vois sur MyPuls », sans Lia, le
#: marche US). L'ORDRE est celui de l'affichage. Chaque nom doit exister dans
#: la liste du planning (chatting.MODELES_MYM / MODELES_OF) : un test le verifie.
MODELS = {
    "mym": ["Emma", "Lola", "Alicia", "Amelia", "Julia", "Kiara", "Sarah", "Aimee", "Chloé"],
    "of": ["Lola", "Amelia", "Julia"],
}
#: Ce qui suit le nom de la model dans le nom du role : « Amelia MYM », « Lola OF ».
SUFFIXE = {"mym": "MYM", "of": "OF"}
ETAT_OK, ETAT_PERDU = "ok", "perdu"


def _norme(texte) -> str:
    """Un nom de role tel qu'on le compare : sans accent, sans casse, espaces
    resserres. « chloe mym » trouve « Chloé MYM », et un manager qui recree un
    role a la main avec une majuscule de travers ne casse rien."""
    plat = unicodedata.normalize("NFD", str(texte or "").strip().lower())
    return " ".join("".join(c for c in plat if unicodedata.category(c) != "Mn").split())


def roles_attendus() -> List[Dict[str, str]]:
    """Les 16 roles, dans l'ordre : les shifts, puis les models MYM, puis OF.

    {nom, genre: "shift" | "model", creneau | (plateforme, model)}
    """
    liste = [{"nom": c, "genre": "shift", "creneau": c} for c in chatting.CRENEAUX]
    for plateforme, models in MODELS.items():
        for m in models:
            liste.append({"nom": "%s %s" % (m, SUFFIXE[plateforme]), "genre": "model",
                          "plateforme": plateforme, "model": m})
    return liste


def manquants(roles_serveur) -> List[str]:
    """Les noms des roles attendus que le serveur n'a pas encore."""
    presents = {_norme((r or {}).get("name")) for r in (roles_serveur or [])}
    return [r["nom"] for r in roles_attendus() if _norme(r["nom"]) not in presents]


def lire(membres, roles_serveur) -> Dict[str, Dict[str, Any]]:
    """Ce que les roles disent de chaque membre.

    {pseudo: {"affiche", "shifts": [creneaux], "mym": [models], "of": [models]}}
    pour les membres qui portent AU MOINS UN de nos roles. Les listes suivent
    l'ordre de reference (CRENEAUX, MODELS), pas celui de Discord.
    """
    par_id = {}
    attendus = {_norme(r["nom"]): r for r in roles_attendus()}
    for r in (roles_serveur or []):
        a = attendus.get(_norme((r or {}).get("name")))
        if a and r.get("id") is not None:
            par_id[str(r["id"])] = a
    lus = {}
    for m in (membres or []):
        pseudo = chatting._norm_discord((m or {}).get("username"))
        if not pseudo:
            continue
        shifts, models = set(), {"mym": set(), "of": set()}
        for rid in (m.get("roles") or []):
            a = par_id.get(str(rid))
            if not a:
                continue
            if a["genre"] == "shift":
                shifts.add(a["creneau"])
            else:
                models[a["plateforme"]].add(a["model"])
        if not shifts and not models["mym"] and not models["of"]:
            continue
        lus[pseudo] = {"affiche": str(m.get("affiche") or m.get("username") or ""),
                       "shifts": [c for c in chatting.CRENEAUX if c in shifts],
                       "mym": [x for x in MODELS["mym"] if x in models["mym"]],
                       "of": [x for x in MODELS["of"] if x in models["of"]]}
    return lus


def _plateforme_edt(edt: Dict[str, Any]) -> str:
    """"mym", "of" ou "" (planning des managers, ou planning au nom libre).
    Meme lecture du nom que chatting.models_for_edt."""
    if edt.get("kind") == "manager":
        return ""
    n = str(edt.get("name") or "").lower()
    if "mym" in n:
        return "mym"
    if "of" in n or "onlyfans" in n:
        return "of"
    return ""


def _modele(models: List[str]) -> str:
    """Les models d'une ligne, comme le planning les ecrit : « Julia+Lola »,
    par ordre alphabetique (c'est la forme que ses cases portent deja)."""
    return "+".join(sorted(models, key=_norme))


def ranger(data: Dict[str, Any], lus: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Range les plannings de `data` (le contenu de chatting_planning.json, modifie
    SUR PLACE) d'apres ce que les roles disent. Rend le rapport.

    {"ranges": n, "crees": [...], "deplaces": [...], "models_changes": [...],
     "rattaches": [...], "perdus": [...], "incomplets": [...], "sans_planning": [...]}

    Chaque element nomme le chatteur : le rapport s'affiche, il ne se devine pas.
    Rejouee sans changement de role, elle ne modifie rien.
    """
    rapport = {"ranges": 0, "crees": [], "deplaces": [], "models_changes": [], "rattaches": [],
               "perdus": [], "incomplets": [], "sans_planning": []}
    edts = {}
    for e in data.get("edts") or []:
        p = _plateforme_edt(e)
        if p and p not in edts:
            edts[p] = e
    for pseudo, info in sorted(lus.items()):
        if not info["shifts"] or not (info["mym"] or info["of"]):
            # Regle 3 : il manque le shift ou la model, on dit lequel.
            rapport["incomplets"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                          "manque": "shift" if not info["shifts"] else "model"})
    for plateforme in ("mym", "of"):
        edt = edts.get(plateforme)
        concernes = {p: i for p, i in lus.items() if i["shifts"] and i[plateforme]}
        if edt is None:
            for pseudo, info in sorted(concernes.items()):
                rapport["sans_planning"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                 "plateforme": SUFFIXE[plateforme]})
            continue
        lignes = edt.setdefault("rows", [])
        for pseudo, info in sorted(concernes.items()):
            modele = _modele(info[plateforme])
            a_lui = [r for r in lignes if chatting._norm_discord(r.get("discord_username")) == pseudo]
            if not a_lui:
                # Regle 2, l'exception : une ligne sans Discord qui porte exactement son surnom.
                nom = _norme(info["affiche"])
                homonymes = [r for r in lignes if not r.get("discord_username") and nom
                             and _norme(r.get("pseudo")) == nom]
                if len(homonymes) == 1:
                    homonymes[0]["discord_username"] = pseudo
                    a_lui = homonymes
                    rapport["rattaches"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                 "planning": edt.get("name")})
            libres = [r for r in a_lui if r.get("creneau") not in info["shifts"]]
            for creneau in info["shifts"]:
                ligne = next((r for r in a_lui if r.get("creneau") == creneau), None)
                if ligne is None and libres:
                    # Il a change de shift : sa ligne SUIT, avec ses presences.
                    ligne = libres.pop(0)
                    rapport["deplaces"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                "planning": edt.get("name"),
                                                "de": ligne.get("creneau"), "a": creneau})
                    ligne["creneau"] = creneau
                elif ligne is None:
                    ligne = chatting.nouvelle_ligne(creneau)
                    ligne["discord_username"] = pseudo
                    ligne["pseudo"] = info["affiche"]
                    lignes.append(ligne)
                    rapport["crees"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                             "planning": edt.get("name"), "creneau": creneau})
                if (ligne.get("modele") or "") != modele:
                    if ligne.get("roles_etat"):         # une ligne neuve n'est pas un « changement »
                        rapport["models_changes"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                          "planning": edt.get("name"),
                                                          "de": ligne.get("modele") or "", "a": modele})
                    ligne["modele"] = modele
                if not ligne.get("pseudo"):
                    ligne["pseudo"] = info["affiche"]
                ligne["roles_etat"] = ETAT_OK
                rapport["ranges"] += 1
            for ligne in libres:
                # Une de ses lignes sur un shift dont il n'a plus le role (regle 1 : elle reste).
                if ligne.get("roles_etat") == ETAT_OK:
                    ligne["roles_etat"] = ETAT_PERDU
        # Ceux qui n'ont plus AUCUN role ici : leurs lignes deja rangees passent « perdu ».
        for ligne in lignes:
            pseudo = chatting._norm_discord(ligne.get("discord_username"))
            if pseudo and pseudo not in concernes and ligne.get("roles_etat") == ETAT_OK:
                ligne["roles_etat"] = ETAT_PERDU
        for ligne in lignes:
            if ligne.get("roles_etat") == ETAT_PERDU:
                rapport["perdus"].append({"pseudo": chatting._norm_discord(ligne.get("discord_username")),
                                          "affiche": ligne.get("pseudo") or "",
                                          "planning": edt.get("name"), "creneau": ligne.get("creneau")})
    return rapport


def ranger_le_planning(membres, roles_serveur) -> Dict[str, Any]:
    """Lit les roles, range le fichier du planning, garde le rapport. Une seule
    ecriture (atomique, par chatting._save), et seulement si quelque chose a
    change : un rangement sans effet ne reecrit pas le fichier."""
    import json
    data = chatting._load()
    avant = json.dumps(data.get("edts"), sort_keys=True, ensure_ascii=False)
    rapport = ranger(data, lire(membres, roles_serveur))
    rapport["le"] = time.time()
    rapport["manquants"] = manquants(roles_serveur)
    change = json.dumps(data.get("edts"), sort_keys=True, ensure_ascii=False) != avant
    ancien = dict(data.get("roles_rangement") or {})
    ancien.pop("le", None)
    nouveau = dict(rapport)
    nouveau.pop("le", None)
    if change or ancien != nouveau:
        data["roles_rangement"] = rapport
        chatting._save(data)
    rapport["change"] = change
    return rapport


def dernier_rapport() -> Optional[Dict[str, Any]]:
    """Le rapport du dernier rangement qui a change quelque chose, ou None."""
    r = chatting._load().get("roles_rangement")
    return r if isinstance(r, dict) else None
