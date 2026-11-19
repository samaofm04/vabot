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
  3. IL FAUT UN SHIFT ET UNE PLATEFORME. La plateforme se lit sur les roles que
     le serveur avait deja, « CHETTER MYM » et « CHATTER OF » (le proprietaire,
     19/11/2026 : « si les mecs ont le role MYM, c'est qu'ils font partie de
     MYM ; s'ils ont le role OF, ils font partie de OF »), ou a defaut sur un
     role de model (« Amelia MYM » dit MYM). Le role de MODEL ne sert qu'a
     remplir la case « model » : sans lui la ligne est rangee quand meme, et
     sa model reste celle qu'on avait mise a la main.
     Un shift sans plateforme (ou l'inverse) ne range rien : le chatteur est
     compte « incomplet » et l'ecran le nomme, pour que le manager voie quoi finir.
  4. UNE LIGNE JAMAIS RANGEE PAR UN ROLE N'EST PAS ACCUSEE. Le jour de la mise
     en service, personne n'a de role : marquer toutes les lignes « sans role »
     aurait couvert le planning d'alertes pour rien.
  5. LE NOM D'UNE LIGNE EST UN PRENOM, PAS UN SURNOM DISCORD. Sur ce serveur un
     surnom s'ecrit « ✅ Odin 14-20 Emma / Alicia » : le premier rangement reel
     (19/11/2026) a cree une ligne a ce nom, A COTE de la ligne « Odin » que le
     manager avait saisie. On garde donc le prenom seul (nom_propre), et c'est
     lui qu'on cherche parmi les lignes sans Discord avant d'en creer une.
  6. UN NOM ET UN DISCORD QUI DESIGNENT DEUX PERSONNES : ON NE TOUCHE PAS. Le
     meme jour, 8 lignes saisies a la main portaient le Discord d'un AUTRE
     chatteur (« Ronel » avec le pseudo de Yedia, « Her Ab » avec celui de
     Ronel...). Ranger d'apres le pseudo aurait deplace la ligne de Ronel, et
     ses presences, sur le shift de Yedia. Une telle ligne est laissee telle
     quelle et NOMMEE (« discordants ») : c'est a un manager de corriger sa
     case Discord, le rangement reprend tout seul ensuite.
  7. LA PAIE FAIT FOI. Le proprietaire avait deja relie chaque chatteur a son
     Discord dans l'ecran de la paie (43 fiches le 19/11/2026) : « c'est deja
     sync dans l'autre truc, dans les payes ». Ces liens-la (`connus`) sont
     donc repris, sans les ressaisir : une ligne qui porte le prenom d'UN seul
     Discord relie dans la paie le recoit — qu'elle soit vide ou qu'elle porte
     celui d'un autre (regle 6). Chaque reprise est ecrite au journal avec
     l'ancien pseudo : rien n'est perdu, tout se defait a la main.
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
#: Les roles de PLATEFORME, ceux que le serveur avait avant nous (jamais crees
#: ni modifies ici). Compares sans casse ni accent ; « chetter » est bien
#: l'orthographe du serveur, « chatter » est acceptee au cas ou il serait
#: renomme un jour.
ROLES_PLATEFORME = {
    "mym": ("chetter mym", "chatter mym"),
    "of": ("chatter of", "chetter of", "chatter onlyfans", "chetter onlyfans"),
}
ETAT_OK, ETAT_PERDU = "ok", "perdu"
#: Regle 6 : le nom de la ligne et son pseudo Discord designent deux personnes.
ETAT_DISCORDANT = "discordant"


def _norme(texte) -> str:
    """Un nom de role tel qu'on le compare : sans accent, sans casse, espaces
    resserres. « chloe mym » trouve « Chloé MYM », et un manager qui recree un
    role a la main avec une majuscule de travers ne casse rien."""
    plat = unicodedata.normalize("NFD", str(texte or "").strip().lower())
    return " ".join("".join(c for c in plat if unicodedata.category(c) != "Mn").split())


def _nom_nu(texte) -> str:
    """Le prenom au debut d'un bout de surnom Discord, sans ce qui l'entoure.

    Les surnoms du serveur portent le prenom PUIS les horaires, la plateforme,
    la model, des pastilles : « ✅ Charbel MYM 20 2H JULIA », « CEJOTV🏀 »,
    « ✅LAMAR 10% 16/1/2026 », « Miranto 8 14 OF ( Amélia ) ⚠️ ». On lit les
    mots dans l'ordre et on s'arrete au premier qui n'est plus un nom : un
    chiffre, « MYM » / « OF », une model, une ponctuation seule, une pastille.
    Une model en PREMIER mot reste un prenom (une chatteuse s'appelle Sarah).
    """
    fin = {"mym", "of", "onlyfans"} | {_norme(m) for models in MODELS.values() for m in models}
    garde, trait = [], False
    for mot in unicodedata.normalize("NFC", str(texte or "")).split():
        debut, bout = 0, len(mot)
        while debut < bout and not mot[debut].isalnum():
            debut += 1
        while bout > debut and not mot[bout - 1].isalnum():
            bout -= 1
        nu = mot[debut:bout]
        if not nu:
            if garde and mot in ("-", "–") and not trait:
                trait = True        # « Jean - Luc » : le trait relie peut-etre deux bouts du prenom
                continue
            if garde:
                break               # « : », « / », « 🐬 » apres le prenom : le reste est du commentaire
            continue                # la pastille du debut
        if any(c.isdigit() for c in nu) or (garde and _norme(nu) in fin):
            break
        if trait:
            garde[-1] += "-" + nu
            trait = False
        else:
            garde.append(nu)
        if bout < len(mot):
            break                   # une pastille collee a la fin du mot : le nom s'arrete la
    return " ".join(garde)


def noms_possibles(affiche) -> List[str]:
    """Les prenoms qu'un surnom Discord peut cacher, le plus probable d'abord.

    Un seul en general. « Le roi polygame | Salomon » en donne deux : rien ne
    dit de quel cote de la barre est le prenom. Le DERNIER passe d'abord —
    l'usage est « surnom | prenom », et la ligne du planning s'appelle bien
    « salomon ». Jamais vide tant que le surnom ne l'est pas : un surnom dont
    on ne tire rien (« 229 ») est rendu tel quel.
    """
    noms, vus = [], set()
    for bout in reversed(str(affiche or "").split("|")):
        nom = _nom_nu(bout)
        if nom and _norme(nom) not in vus:
            vus.add(_norme(nom))
            noms.append(nom)
    return noms or [" ".join(str(affiche or "").split())]


def nom_propre(affiche) -> str:
    """Le nom qu'une ligne du planning porte pour ce surnom Discord (regle 5)."""
    return noms_possibles(affiche)[0]


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

    {pseudo: {"affiche", "shifts": [creneaux], "plateformes": ["mym", "of"],
              "mym": [models], "of": [models]}}
    pour les membres qui portent AU MOINS UN role qui nous parle (shift,
    model, ou plateforme). `plateformes` : celles que disent ses roles
    CHETTER MYM / CHATTER OF, plus celles de ses roles de model. Les listes
    suivent l'ordre de reference (CRENEAUX, MODELS), pas celui de Discord.
    """
    par_id = {}
    attendus = {_norme(r["nom"]): r for r in roles_attendus()}
    for plateforme, noms in ROLES_PLATEFORME.items():
        for n in noms:
            attendus[n] = {"genre": "plateforme", "plateforme": plateforme}
    for r in (roles_serveur or []):
        a = attendus.get(_norme((r or {}).get("name")))
        if a and r.get("id") is not None:
            par_id[str(r["id"])] = a
    lus = {}
    for m in (membres or []):
        pseudo = chatting._norm_discord((m or {}).get("username"))
        if not pseudo:
            continue
        shifts, models, plateformes = set(), {"mym": set(), "of": set()}, set()
        for rid in (m.get("roles") or []):
            a = par_id.get(str(rid))
            if not a:
                continue
            if a["genre"] == "shift":
                shifts.add(a["creneau"])
            elif a["genre"] == "plateforme":
                plateformes.add(a["plateforme"])
            else:
                models[a["plateforme"]].add(a["model"])
                plateformes.add(a["plateforme"])        # « Amelia MYM » dit aussi MYM
        if not shifts and not plateformes:
            continue
        lus[pseudo] = {"affiche": str(m.get("affiche") or m.get("username") or ""),
                       "shifts": [c for c in chatting.CRENEAUX if c in shifts],
                       "plateformes": [p for p in ("mym", "of") if p in plateformes],
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


def _cle(texte) -> str:
    """Un nom tel qu'on le COMPARE : sans accent, sans casse, lettres et chiffres
    seuls. « Jean-luc » (le planning) et « Jean - Luc » (Discord) sont la meme
    personne ; « Jerry » et « Jerry bgn » restent deux."""
    return "".join(c for c in _norme(texte) if c.isalnum())


def _cles(affiche) -> set:
    """Les noms sous lesquels une ligne peut designer ce membre, tels qu'on les
    compare : ses prenoms possibles, et son surnom entier (une ligne creee
    avant la regle 5 le porte encore)."""
    return {n for n in [_cle(x) for x in noms_possibles(affiche)] + [_cle(affiche)] if n}


def _noms_de(lus, connus) -> Dict[str, set]:
    """{pseudo Discord: les noms qui le designent}, pour tous ceux qu'on connait :
    les membres qui portent un role (leur surnom du serveur) et les chatteurs
    relies dans la paie (le nom retenu la-bas, souvent plus ancien — c'est par
    lui que « AGBEDE 14-20 OF Julia » se revele etre le « Jean-luc » du planning)."""
    noms = {p: _cles(i["affiche"]) for p, i in lus.items()}
    for pseudo, autres in (connus or {}).items():
        for nom in autres or []:
            noms.setdefault(pseudo, set()).update(_cles(nom))
    return noms


def _nom_de(pseudo, lus, connus) -> str:
    """Le prenom a afficher pour ce Discord ("" si on ne le connait pas)."""
    if pseudo in lus:
        return nom_propre(lus[pseudo]["affiche"])
    return next((nom_propre(n) for n in (connus or {}).get(pseudo) or [] if n), "")


def _sans_discord(ligne) -> bool:
    return not str(ligne.get("discord_username") or "").strip()


def _discordantes(lignes, lus, noms_de, connus=None) -> Dict[int, Dict[str, Any]]:
    """Les lignes dont le nom et le pseudo Discord designent deux personnes
    (regle 6) : {id(ligne): {"ligne", "creneau", "discord", "discord_affiche",
    "attendu": [pseudos de ceux qui portent le nom de la ligne]}}.

    Une ligne « Jerry » reliee au Discord de « Skurt » n'en est PAS une : un
    chatteur a souvent un prenom et un surnom, et rien ne les contredit. Il
    faut une preuve, l'une des deux :
      - le nom de la ligne est exactement celui d'un AUTRE Discord connu
        (« Ronel » reliee au Discord de Yedia, alors qu'un Ronel existe) ;
      - le proprietaire du Discord a SA ligne ailleurs dans le planning
        (« Eud » reliee au Discord de Her Ab, alors qu'une ligne « Her Ab » existe).
    """
    par_nom = {}
    for r in lignes:
        n = _cle(r.get("pseudo"))
        if n:
            par_nom.setdefault(n, []).append(r)
    trouve = {}
    for r in lignes:
        pseudo = chatting._norm_discord(r.get("discord_username"))
        nom = _cle(r.get("pseudo"))
        if not pseudo or not nom:
            continue
        siens = noms_de.get(pseudo, set())      # vide : un Discord dont on ne sait rien
        if nom in siens:
            continue
        autres = sorted(p for p in noms_de if p != pseudo and nom in noms_de[p])
        ailleurs = any(x is not r for n in siens for x in par_nom.get(n, []))
        if autres or ailleurs:
            trouve[id(r)] = {"ligne": r.get("pseudo") or "", "creneau": r.get("creneau") or "",
                             "discord": pseudo, "discord_affiche": _nom_de(pseudo, lus, connus),
                             "attendu": autres}
    return trouve


def _reprendre_la_paie(lignes, lus, noms_de, connus, planning) -> List[Dict[str, Any]]:
    """Regle 7 : pose sur les lignes le Discord que la paie connait pour leur
    prenom. Rend ce qui a ete repris, [{planning, ligne, creneau, de, a}].

    Deux cas, et dans les deux il faut UN SEUL Discord de la paie a ce prenom
    (deux « Moyle » relies : on ne devine pas, la ligne reste a corriger) :
      - la ligne n'a pas de Discord ;
      - elle porte celui d'un autre (regle 6).
    Plusieurs passes : « Ronel » portait le Discord de Yedia et « Her Ab »
    celui de Ronel — corriger l'une change ce qu'on sait de l'autre.
    """
    repris = []
    if not connus:
        return repris
    for _ in range(4):
        discordantes = _discordantes(lignes, lus, noms_de, connus)
        change = False
        for r in lignes:
            nom = _cle(r.get("pseudo"))
            if not nom:
                continue
            if _sans_discord(r):
                candidats = sorted(p for p in connus if nom in noms_de.get(p, ()))
            elif id(r) in discordantes:
                candidats = [p for p in discordantes[id(r)]["attendu"] if p in connus]
            else:
                continue
            if len(candidats) != 1:
                continue
            repris.append({"planning": planning, "ligne": r.get("pseudo") or "", "creneau": r.get("creneau") or "",
                           "de": chatting._norm_discord(r.get("discord_username")), "a": candidats[0]})
            r["discord_username"] = candidats[0]
            if r.get("roles_etat") == ETAT_DISCORDANT:
                r.pop("roles_etat")
            change = True
        if not change:
            break
    return repris


def _creee_et_vide(ligne, modele) -> bool:
    """Une ligne que le rangement a creee et ou personne n'a rien saisi depuis :
    ni presence, ni jour off, ni statut, ni model a la main. Elle seule peut
    etre retiree au profit de la ligne saisie a la main (regle 1 : une ligne
    qui porte quoi que ce soit reste)."""
    if ligne.get("roles_etat") not in (ETAT_OK, ETAT_PERDU) or (ligne.get("modele") or "") not in ("", modele or ""):
        return False
    neuve = chatting.nouvelle_ligne(ligne.get("creneau") or "")
    du_rangement = {"id", "creneau", "pseudo", "discord_username", "modele", "roles_etat"}
    return all(ligne.get(c) == neuve.get(c) for c in (set(ligne) | set(neuve)) - du_rangement)


def ranger(data: Dict[str, Any], lus: Dict[str, Dict[str, Any]],
           connus: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Range les plannings de `data` (le contenu de chatting_planning.json, modifie
    SUR PLACE) d'apres ce que les roles disent. Rend le rapport.

    `connus` : {pseudo Discord: [noms]} des chatteurs relies dans la paie
    (regle 7). Sans lui, rien n'est repris : le rangement fait comme avant.

    {"ranges": n, "crees": [...], "deplaces": [...], "models_changes": [...],
     "rattaches": [...], "perdus": [...], "incomplets": [...], "sans_planning": [...],
     "sans_model": [...], "discordants": [...], "en_attente": [...], "doublons": [...],
     "repris": [...]}

    Chaque element nomme le chatteur : le rapport s'affiche, il ne se devine pas.
    Rejouee sans changement de role, elle ne modifie rien.
    """
    rapport = {"ranges": 0, "crees": [], "deplaces": [], "models_changes": [], "rattaches": [],
               "perdus": [], "incomplets": [], "sans_planning": [], "sans_model": [],
               "discordants": [], "en_attente": [], "doublons": [], "repris": []}
    noms_de = _noms_de(lus, connus)
    edts = {}
    for e in data.get("edts") or []:
        p = _plateforme_edt(e)
        if p and p not in edts:
            edts[p] = e
    for pseudo, info in sorted(lus.items()):
        if not info["shifts"] or not info["plateformes"]:
            # Regle 3 : il manque le shift ou la plateforme, on dit lequel.
            rapport["incomplets"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                          "manque": "shift" if not info["shifts"] else "plateforme"})
    for plateforme in ("mym", "of"):
        edt = edts.get(plateforme)
        concernes = {p: i for p, i in lus.items() if i["shifts"] and plateforme in i["plateformes"]}
        if edt is None:
            for pseudo, info in sorted(concernes.items()):
                rapport["sans_planning"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                 "plateforme": SUFFIXE[plateforme]})
            continue
        lignes = edt.setdefault("rows", [])
        # Regle 7 d'abord : ce que la paie sait deja n'a pas a rester « a corriger ».
        rapport["repris"].extend(_reprendre_la_paie(lignes, lus, noms_de, connus, edt.get("name")))
        # Regle 6 : ces lignes-la ne sont ni rangees ni deplacees d'apres leur pseudo.
        discordantes = _discordantes(lignes, lus, noms_de, connus)
        for d in discordantes.values():
            rapport["discordants"].append(dict(d, planning=edt.get("name")))
        for ligne in lignes:
            if id(ligne) in discordantes:
                # Elle le porte sur elle : le manager voit QUELLE ligne corriger. Une
                # marque « rangee » posee d'apres ce pseudo-la ne disait rien de vrai.
                ligne["roles_etat"] = ETAT_DISCORDANT
            elif ligne.get("roles_etat") == ETAT_DISCORDANT:
                ligne.pop("roles_etat")                 # corrigee depuis
        for pseudo, info in sorted(concernes.items()):
            # Pas de role de model sur cette plateforme : on ne touche PAS a la
            # case « model » (celle saisie a la main reste), et on le dit.
            modele = _modele(info[plateforme]) if info[plateforme] else None
            propre = nom_propre(info["affiche"]) or pseudo
            a_lui = [r for r in lignes if chatting._norm_discord(r.get("discord_username")) == pseudo
                     and id(r) not in discordantes]
            for r in a_lui:
                # Regle 5 : une ligne qui porte son surnom entier prend le prenom seul.
                if propre and r.get("pseudo") != propre and _cle(r.get("pseudo")) == _cle(info["affiche"]) \
                        and _cle(propre) != _cle(info["affiche"]):
                    r["pseudo"] = propre
            # Regle 2, l'exception : les lignes sans Discord qui portent son prenom
            # sont les siennes — s'il n'a pas deja une vraie ligne a lui.
            vide = {id(r) for r in a_lui if _creee_et_vide(r, modele)}
            homonymes = [r for r in lignes if _sans_discord(r) and _cle(r.get("pseudo")) in noms_de[pseudo]]
            if homonymes and len(vide) == len(a_lui):
                for r in homonymes:
                    r["discord_username"] = pseudo
                a_lui = a_lui + homonymes
                rapport["rattaches"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                             "planning": edt.get("name")})
            if not a_lui:
                # Sa ligne existe, mais elle porte le Discord d'un autre (regle 6) :
                # en creer une seconde ferait un doublon. Il attend la correction.
                prise = next((d for d in discordantes.values() if _cle(d["ligne"]) in noms_de[pseudo]), None)
                if prise:
                    rapport["en_attente"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                  "planning": edt.get("name"), "ligne": prise["ligne"]})
                    continue
            if modele is None:
                rapport["sans_model"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                              "planning": edt.get("name")})
            # Ses VRAIES lignes (saisies a la main, ou qui portent une presence) passent
            # avant celles que le rangement a creees et ou personne n'a rien mis.
            pleines = [r for r in a_lui if id(r) not in vide]
            vides = [r for r in a_lui if id(r) in vide]
            libres = [r for r in pleines + vides if r.get("creneau") not in info["shifts"]]

            def _suit(ligne, creneau):
                # Il a change de shift : sa ligne SUIT, avec ses presences.
                rapport["deplaces"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                            "planning": edt.get("name"),
                                            "de": ligne.get("creneau"), "a": creneau})
                ligne["creneau"] = creneau

            for creneau in info["shifts"]:
                ligne = next((r for r in pleines if r.get("creneau") == creneau), None)
                if ligne is None and libres and id(libres[0]) not in vide:
                    ligne = libres.pop(0)
                    _suit(ligne, creneau)
                if ligne is None:
                    ligne = next((r for r in vides if r.get("creneau") == creneau), None)
                if ligne is None and libres:
                    ligne = libres.pop(0)
                    _suit(ligne, creneau)
                elif ligne is None:
                    ligne = chatting.nouvelle_ligne(creneau)
                    ligne["discord_username"] = pseudo
                    ligne["pseudo"] = propre
                    lignes.append(ligne)
                    rapport["crees"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                             "planning": edt.get("name"), "creneau": creneau})
                # Une ligne creee par le rangement, restee vide, sur le shift ou sa
                # vraie ligne vient de prendre place : c'etait un doublon (« Odin » le
                # 19/11/2026). Elle seule s'en va — elle ne porte rien (regle 1).
                en_trop = [v for v in vides if v is not ligne and v.get("creneau") == creneau]
                if en_trop:
                    lignes[:] = [r for r in lignes if not any(r is v for v in en_trop)]
                    vides = [v for v in vides if not any(v is x for x in en_trop)]
                    rapport["doublons"].extend({"pseudo": pseudo, "affiche": info["affiche"],
                                                "planning": edt.get("name"), "creneau": creneau}
                                               for _ in en_trop)
                if modele is not None and (ligne.get("modele") or "") != modele:
                    if ligne.get("roles_etat"):         # une ligne neuve n'est pas un « changement »
                        rapport["models_changes"].append({"pseudo": pseudo, "affiche": info["affiche"],
                                                          "planning": edt.get("name"),
                                                          "de": ligne.get("modele") or "", "a": modele})
                    ligne["modele"] = modele
                if not ligne.get("pseudo"):
                    ligne["pseudo"] = propre
                ligne["roles_etat"] = ETAT_OK
                rapport["ranges"] += 1
            for ligne in libres:
                # Une de ses lignes sur un shift dont il n'a plus le role (regle 1 : elle reste).
                if ligne.get("roles_etat") == ETAT_OK:
                    ligne["roles_etat"] = ETAT_PERDU
        for ligne in lignes:
            # Ceux qui n'ont plus AUCUN role ici : leurs lignes deja rangees passent « perdu ».
            pseudo = chatting._norm_discord(ligne.get("discord_username"))
            if pseudo and pseudo not in concernes and ligne.get("roles_etat") == ETAT_OK:
                ligne["roles_etat"] = ETAT_PERDU
        for ligne in lignes:
            if ligne.get("roles_etat") == ETAT_PERDU:
                rapport["perdus"].append({"pseudo": chatting._norm_discord(ligne.get("discord_username")),
                                          "affiche": ligne.get("pseudo") or "",
                                          "planning": edt.get("name"), "creneau": ligne.get("creneau")})
    return rapport


#: Combien de reprises de la paie le fichier du planning garde (les plus recentes).
JOURNAL_MAX = 200


def ranger_le_planning(membres, roles_serveur, connus=None) -> Dict[str, Any]:
    """Lit les roles, range le fichier du planning, garde le rapport. Une seule
    ecriture (atomique, par chatting._save), et seulement si quelque chose a
    change : un rangement sans effet ne reecrit pas le fichier."""
    import json
    data = chatting._load()
    avant = json.dumps(data.get("edts"), sort_keys=True, ensure_ascii=False)
    rapport = ranger(data, lire(membres, roles_serveur), connus)
    rapport["manquants"] = manquants(roles_serveur)
    if rapport["repris"]:
        # Le rapport est remplace au rangement suivant ; l'ANCIEN pseudo d'une ligne
        # corrigee, lui, doit rester lisible : c'est ce qui permet de defaire.
        journal = list(data.get("roles_journal") or [])
        journal.extend(dict(x, le=time.time()) for x in rapport["repris"])
        data["roles_journal"] = journal[-JOURNAL_MAX:]
    change = json.dumps(data.get("edts"), sort_keys=True, ensure_ascii=False) != avant
    ancien = dict(data.get("roles_rangement") or {})
    # « le » = l'heure du dernier rangement qui a CHANGE le planning (c'est ce que
    # l'ecran annonce). Un rapport qui differe sans que rien ne bouge — un role
    # donne a quelqu'un d'incomplet — garde l'heure d'avant.
    rapport["le"] = time.time() if change or not ancien.get("le") else ancien["le"]
    ancien.pop("le", None)
    nouveau = dict(rapport)
    nouveau.pop("le", None)
    if change or ancien != nouveau:
        data["roles_rangement"] = rapport
        chatting._save(data)
    rapport["change"] = change
    return rapport


def journal_des_reprises() -> List[Dict[str, Any]]:
    """Les Discord repris de la paie, du plus ancien au plus recent :
    [{le, planning, ligne, creneau, de, a}] (`de` vide : la case etait vide)."""
    j = chatting._load().get("roles_journal")
    return [x for x in j if isinstance(x, dict)] if isinstance(j, list) else []


def dernier_rapport() -> Optional[Dict[str, Any]]:
    """Le rapport du dernier rangement qui a change quelque chose, ou None."""
    r = chatting._load().get("roles_rangement")
    return r if isinstance(r, dict) else None
