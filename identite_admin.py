# -*- coding: utf-8 -*-
"""Renommer ou retirer une identite, sans laisser de liens morts derriere.

POURQUOI CE FICHIER EXISTE

Le nom d'une identite n'est pas une etiquette : c'est une CLE. Il est a la
fois le nom du dossier `data/identities/<nom>`, une cle de premier niveau dans
cinq fichiers JSON, un element de liste dans deux autres, et le premier
segment des identifiants de fichiers (`<nom>|<sous-dossier>|<fichier>`).

La route de renommage existante refusait donc tout ce qui n'etait pas la
Bibliotheque 2, avec ce commentaire : « celles de la Bibliotheque sont
referencees par leur NOM un peu partout -- les renommer casserait ces liens
en silence ». Le refus etait sage tant que personne n'avait fait la liste.
La voici.

LE PRINCIPE : RIEN EN SILENCE

Chaque emplacement est DECLARE ici, dans une seule table. Un renommage rend
le compte de ce qu'il a touche, emplacement par emplacement -- et, surtout,
la liste de ce qu'il NE SAIT PAS suivre. Les salons et categories Discord
portent le nom de l'identite dans leur propre nom : le bot ne peut pas les
renommer depuis le site, et pretendre le contraire serait pire que de se
taire. On le dit.

LA SUPPRESSION N'EFFACE RIEN

Regle du depot : « le site n'efface jamais un media ». Retirer une identite
DEPLACE son dossier dans `data/_corbeille_identites/<nom>-<horodatage>/` et
ecrit a cote un `_fiche.json` portant tout ce qu'on savait d'elle -- son
referentiel Jailbreak (VA et comptes, y compris les bannis, qu'on ne
supprime jamais), son marche, sa nature, ses styles. Revenir en arriere,
c'est remettre le dossier en place et recharger la fiche.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import safe_json

DATA = Path("data")
IDENTITES = DATA / "identities"
CORBEILLE = DATA / "_corbeille_identites"

#: Fichiers ou le nom est une CLE DE PREMIER NIVEAU d'un dictionnaire.
_CLES = (
    ("identity_market.json", "le marche FR/US"),
    ("identity_type.json", "la nature (modele ou identite)"),
    ("identity_styles.json", "les pastilles « ce qui marche »"),
    ("captions.json", "les captions de la Bibliotheque"),
    ("gms_templates.json", "le modele de lien GMS"),
)

#: jailbreak.json N'EST PAS DANS _CLES, ET C'EST VOLONTAIRE.
#:
#: Le renommer a la main (d[neuf] = d.pop(ancien)) marchait -- et court-
#: circuitait tout ce que jailbreak.rename_identity_in_storage fait autour :
#: le verrou reentrant du module, pose contre le poller Sheets et le scrape
#: qui font lire-modifier-ecrire en arriere-plan ; la rotation des
#: sauvegardes ; et surtout l'appel a jb_objectifs.renommer_identite, qui
#: deplace l'HISTORIQUE DE PAIE (cles « identite|va ») et ANNULE le
#: renommage si cet historique ne suit pas. Sans lui, le bilan de quinzaine
#: d'un VA repart a « aucune journee notee ».

#: Fichiers dont une VALEUR porte le nom, pas la cle.
_CHAMPS = (
    ("users.json", "identity", "les fiches VA de Discord"),
)

#: Fichiers qui sont une LISTE de noms.
_LISTES = (
    ("identity_order.json", "l'ordre d'affichage"),
)

#: Fichiers dont une LISTE INTERIEURE porte les noms.
#:
#: scrape_identites.json etait declare comme une liste. C'est un dict :
#: {"actives": [...], "modifie": ...}. La branche « si ce n'est pas une
#: liste, on passe » le sautait donc EN SILENCE -- une identite renommee
#: sortait du perimetre du scrape sans que rien ne l'indique, et ses chiffres
#: cessaient d'avancer. Ce sont ceux sur lesquels se lit la paie des VA.
_SOUS_LISTES = (
    ("scrape_identites.json", "actives", "le perimetre du scrape Instagram"),
)

#: Fichiers dont les cles sont des identifiants « <nom>|<sous-dossier>|<fichier> ».
_PREFIXES = (
    ("fav_brutes.json", "les brutes mises en favori"),
    ("banger_marks.json", "les reels marques banger"),
    ("flash_trend.json", "les montages Flash Trend"),
    ("disabled_reels.json", "les reels mis de cote"),
)

#: Etats dont les CLES SONT DES CHEMINS contenant le nom comme un segment.
#:
#: gdrive_sync_state.json est le plus couteux de toute la carte. Ses cles
#: `uploaded` sont « Bibliotheque/Marche/Identite/Type/fichier » et ses cles
#: `folders` « parentId/Nom ». Non reecrites, la synchro croit que RIEN n'a
#: ete envoye : elle cree un second dossier Drive au nouveau nom et RECOPIE
#: TOUT. Le precedent est ecrit dans gdrive_sync.py lui-meme, ou une fonction
#: de migration existe parce qu'un changement de format de cle non migre
#: « recopiait 2900 fichiers a cote ».
_CHEMINS = (
    ("gdrive_sync_state.json", "l'etat de synchro Google Drive"),
)

#: Arbres de fichiers ranges par identite, HORS de data/identities.
#: Rien ne casse s'ils ne suivent pas -- mais les vignettes deviennent
#: orphelines (regeneration ffmpeg a chaque carte, et l'ancien arbre reste
#: sur le disque pour toujours) et le stock de montages pre-generes devient
#: invisible.
_ARBRES = (
    ("thumbnails", "les vignettes"),
    ("noctus/reserve", "la reserve de montages"),
)

#: Ce qu'aucun code du site ne peut suivre. Dit a l'ecran, jamais tu.
IMPOSSIBLE = (
    "Sur CHAQUE serveur Discord (FR et US) : la categorie, les salons "
    "general-X / banger-X / exemple-compte-X et le role du meme nom portent "
    "l'ancien nom. Le bot ne les retrouve que par ce nom -- et sa boucle de "
    "securite, qui repasse toutes les dix minutes, RETIRE l'acces des VA aux "
    "salons qu'elle ne rattache plus a personne. A renommer sur Discord, pas "
    "seulement pour la forme.",
    "Les menus deja postes gardent l'ancien nom cuit dans leurs boutons : un "
    "clic sur un vieux panneau vise un dossier qui n'existe plus. Il faut les "
    "reposter (/menuall, /resetmenus, /menujailbreakus).",
    "Les liens de suivi GMS deduisent l'identite du suffixe de leur code "
    "(xxxxlola) : les liens existants basculeront en « autres », donc les "
    "clics et les paliers de paie des VA avec eux.",
    "La page publique /bio/<nom> change d'adresse : un lien deja colle dans "
    "une bio Instagram tombera sur une page vide.",
    "Le classeur Google « VA JB — <ancien nom> » devient un fossile ; un neuf "
    "sera cree au nouveau nom.",
    "Les reglages memorises par ton navigateur (onglet courant, filtres, tri) "
    "pointent sur l'ancien nom : ils se retablissent au premier clic.",
)


def _charger(nom_fichier: str):
    return safe_json.load(DATA / nom_fichier, default=None)


def _ecrire(nom_fichier: str, contenu) -> bool:
    return bool(safe_json.write(DATA / nom_fichier, contenu, indent=2))


def normaliser(brut: str) -> str:
    """Le nom tel qu'il sera stocke. Refuse tout ce qui n'est pas sur.

    NI TIRET NI SOULIGNE, ET CE N'EST PAS DE LA PRUDERIE. Le bot retrouve les
    salons d'une identite en extrayant le suffixe de leur nom avec
    `re.match(r"[a-z0-9]+")` (cogs/welcome.py) : il TRONQUE au premier
    separateur. Une identite nommee « marie-lou » aurait des salons
    « general-marie-lou » que le bot lirait « marie » -- introuvables pour
    toujours, et le VA se verrait refuser l'acces a ses propres salons par la
    boucle de securite qui repasse toutes les dix minutes.
    """
    import re
    return re.sub(r"[^a-z0-9]", "", str(brut or "").strip().lower())[:40]


def existe(nom: str) -> bool:
    if (IDENTITES / nom).is_dir():
        return True
    d = _charger("jailbreak.json")
    return isinstance(d, dict) and nom in d


def _segments_renommes(cle, ancien, nouveau):
    """Remplace le segment de chemin egal a `ancien`, sans toucher au reste.

    La comparaison ignore la casse : le Drive ecrit ses dossiers en capitale
    initiale (« root/_Tst_Lilla ») alors que le site range tout en minuscules.
    Comparer strictement laisserait l'etat de synchro intact -- c'est-a-dire
    la re-copie de toute la bibliotheque.
    """
    bouts = str(cle).split("/")
    touche = False
    for k, b in enumerate(bouts):
        if b.strip().lower() == ancien:
            bouts[k] = nouveau
            touche = True
    return ("/".join(bouts), touche)


def _compter(d, teste):
    """Combien d'elements d'un dict OU d'une liste repondent au test."""
    if isinstance(d, dict):
        return sum(1 for k in d if teste(k))
    if isinstance(d, list):
        return sum(1 for k in d if teste(k))
    return 0


def _ou_apparait(nom: str) -> list:
    """Les emplacements qui portent REELLEMENT ce nom, avec leur libelle.

    Sert au recapitulatif montre avant d'agir : une confirmation qui ne dit
    pas ce qu'elle engage n'est pas une confirmation.
    """
    trouves = []
    if (IDENTITES / nom).is_dir():
        n = sum(1 for _ in (IDENTITES / nom).rglob("*") if _.is_file())
        trouves.append({"ou": "le dossier de la Bibliotheque",
                        "detail": f"{n} fichier(s)"})
    d = _charger("jailbreak.json")
    if isinstance(d, dict) and nom in d:
        e = d[nom] if isinstance(d[nom], dict) else {}
        trouves.append({"ou": "le referentiel Jailbreak",
                        "detail": "%d VA, %d compte(s)"
                                  % (len(e.get("vas") or []),
                                     len(e.get("accounts") or []))})
    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if isinstance(d, dict) and nom in d:
            trouves.append({"ou": libelle, "detail": fichier})
    for fichier, champ, libelle in _CHAMPS:
        d = _charger(fichier)
        if isinstance(d, dict):
            n = sum(1 for v in d.values()
                    if (isinstance(v, dict) and str(v.get(champ) or "").lower() == nom)
                    or (isinstance(v, str) and v.lower() == nom))
            if n:
                trouves.append({"ou": libelle, "detail": f"{n} fiche(s)"})
    for fichier, libelle in _LISTES:
        d = _charger(fichier)
        if isinstance(d, list) and nom in [str(x).lower() for x in d]:
            trouves.append({"ou": libelle, "detail": fichier})
    for fichier, champ, libelle in _SOUS_LISTES:
        d = _charger(fichier)
        if isinstance(d, dict) and nom in [str(x).lower() for x in (d.get(champ) or [])]:
            trouves.append({"ou": libelle, "detail": fichier})
    for fichier, libelle in _PREFIXES:
        n = _compter(_charger(fichier),
                     lambda k: str(k).lower().startswith(nom + "|"))
        if n:
            trouves.append({"ou": libelle, "detail": f"{n} entree(s)"})
    for fichier, libelle in _CHEMINS:
        d = _charger(fichier)
        n = 0
        if isinstance(d, dict):
            for bloc in d.values():
                n += _compter(bloc, lambda k: _segments_renommes(k, nom, "x")[1])
        if n:
            trouves.append({"ou": libelle, "detail": f"{n} entree(s)"})
    for sous, libelle in _ARBRES:
        for chemin in (DATA / sous).glob("**/" + nom):
            if chemin.is_dir():
                trouves.append({"ou": libelle, "detail": str(chemin)})
                break
    d = _charger("text_pool.json")
    if isinstance(d, dict):
        n = 0
        for items in d.values():
            if isinstance(items, list):
                n += sum(1 for e in items if isinstance(e, dict)
                         and str(e.get("identity") or "").lower() == nom)
        if n:
            trouves.append({"ou": "les bios et CTA", "detail": f"{n} texte(s)"})
    return trouves


def apercu(nom: str) -> dict:
    """Ce qu'une action sur ce nom toucherait. Ne modifie rien."""
    nom = normaliser(nom)
    emplacements = _ou_apparait(nom)
    vas = comptes = 0
    d = _charger("jailbreak.json")
    if isinstance(d, dict) and isinstance(d.get(nom), dict):
        vas = len(d[nom].get("vas") or [])
        comptes = len(d[nom].get("accounts") or [])
    return {"identite": nom, "existe": existe(nom), "vas": vas, "comptes": comptes,
            "emplacements": emplacements, "impossible": list(IMPOSSIBLE)}


# ==============================================================================
# Renommer
# ==============================================================================

def renommer(ancien: str, nouveau: str) -> dict:
    """Renomme partout ou le nom est une cle. Rend le detail de ce qui a bouge.

    L'ORDRE COMPTE, et il est dicte par le cout d'un echec a mi-chemin.

    1. Le referentiel Jailbreak D'ABORD, par sa propre fonction : elle prend
       le verrou du module contre le poller Sheets et le scrape, fait tourner
       les sauvegardes, deplace l'historique de paie -- et ANNULE tout si cet
       historique ne suit pas. Si elle refuse, rien d'autre n'a bouge.
    2. Le dossier ensuite : la seule etape qui peut echouer pour une cause
       exterieure (fichier ouvert, disque plein).
    3. Les ecritures JSON, atomiques une a une. Celle qui echoue est NOMMEE
       dans le rapport plutot que passee sous silence : on saura quoi
       rattraper a la main.
    """
    ancien, nouveau = normaliser(ancien), normaliser(nouveau)
    if not ancien or not nouveau:
        return {"ok": False, "error": "Nom invalide (lettres et chiffres seulement)"}
    if ancien == nouveau:
        return {"ok": True, "identite": ancien, "touches": [], "echecs": []}
    if not existe(ancien):
        return {"ok": False, "error": f"« {ancien} » n'existe pas"}
    if existe(nouveau) or (IDENTITES / nouveau).exists():
        return {"ok": False, "error": f"« {nouveau} » existe deja"}

    touches, echecs = [], []

    # 1. Le referentiel et la paie, par la porte prevue pour ca.
    try:
        import jailbreak as _jb
        if (_charger("jailbreak.json") or {}).get(ancien) is not None:
            if not _jb.rename_identity_in_storage(ancien, nouveau):
                return {"ok": False,
                        "error": "Le referentiel Jailbreak a refuse le "
                                 "renommage (historique de paie non deplace). "
                                 "Rien n'a ete touche."}
            touches.append({"ou": "le referentiel Jailbreak et l'historique de paie",
                            "detail": "jailbreak.json + jb_objectifs"})
    except Exception as e:
        return {"ok": False, "error": f"Referentiel Jailbreak indisponible ({e}). "
                                      "Rien n'a ete touche."}

    # 2. Le dossier.
    if (IDENTITES / ancien).is_dir():
        try:
            (IDENTITES / ancien).rename(IDENTITES / nouveau)
            touches.append({"ou": "le dossier de la Bibliotheque", "detail": "deplace"})
        except Exception as e:
            echecs.append({"ou": "le dossier de la Bibliotheque", "detail": str(e)[:80]})

    # 3. Les jetons du portail VA. Sans eux, la page du VA repond 200 en
    #    annoncant « aucun compte », et son premier ajout RECREE l'identite
    #    disparue dans le referentiel -- avec des comptes en double derriere.
    try:
        import va_portal as _vp
        n = _vp.renommer_identite(ancien, nouveau)
        if n:
            touches.append({"ou": "les liens du portail VA", "detail": f"{n} jeton(s)"})
    except Exception as e:
        echecs.append({"ou": "les liens du portail VA", "detail": str(e)[:80]})

    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if not isinstance(d, dict) or ancien not in d:
            continue
        d[nouveau] = d.pop(ancien)
        (touches if _ecrire(fichier, d) else echecs).append(
            {"ou": libelle, "detail": fichier})

    for fichier, champ, libelle in _CHAMPS:
        d = _charger(fichier)
        if not isinstance(d, dict):
            continue
        n = 0
        for cle, v in d.items():
            if isinstance(v, dict) and str(v.get(champ) or "").lower() == ancien:
                v[champ] = nouveau
                n += 1
            elif isinstance(v, str) and v.lower() == ancien:
                d[cle] = nouveau
                n += 1
        if n:
            (touches if _ecrire(fichier, d) else echecs).append(
                {"ou": libelle, "detail": f"{n} fiche(s)"})

    for fichier, libelle in _LISTES:
        d = _charger(fichier)
        if not isinstance(d, list):
            continue
        bas = [str(x).lower() for x in d]
        if ancien not in bas:
            continue
        (touches if _ecrire(fichier, [nouveau if x == ancien else x for x in bas])
         else echecs).append({"ou": libelle, "detail": fichier})

    for fichier, champ, libelle in _SOUS_LISTES:
        d = _charger(fichier)
        if not isinstance(d, dict):
            continue
        bas = [str(x).lower() for x in (d.get(champ) or [])]
        if ancien not in bas:
            continue
        d[champ] = [nouveau if x == ancien else x for x in bas]
        (touches if _ecrire(fichier, d) else echecs).append(
            {"ou": libelle, "detail": fichier})

    for fichier, libelle in _PREFIXES:
        d = _charger(fichier)
        n = 0
        if isinstance(d, dict):
            neuf = {}
            for k, v in d.items():
                if str(k).lower().startswith(ancien + "|"):
                    k = nouveau + str(k)[len(ancien):]
                    n += 1
                neuf[k] = v
        elif isinstance(d, list):
            neuf = []
            for k in d:
                if str(k).lower().startswith(ancien + "|"):
                    k = nouveau + str(k)[len(ancien):]
                    n += 1
                neuf.append(k)
        else:
            continue
        if n:
            (touches if _ecrire(fichier, neuf) else echecs).append(
                {"ou": libelle, "detail": f"{n} entree(s)"})

    for fichier, libelle in _CHEMINS:
        d = _charger(fichier)
        if not isinstance(d, dict):
            continue
        n = 0
        for bloc_nom, bloc in list(d.items()):
            if isinstance(bloc, dict):
                neuf = {}
                for k, v in bloc.items():
                    k2, touche = _segments_renommes(k, ancien, nouveau)
                    n += 1 if touche else 0
                    neuf[k2] = v
                d[bloc_nom] = neuf
            elif isinstance(bloc, list):
                neuve = []
                for k in bloc:
                    k2, touche = _segments_renommes(k, ancien, nouveau)
                    n += 1 if touche else 0
                    neuve.append(k2)
                d[bloc_nom] = neuve
        if n:
            (touches if _ecrire(fichier, d) else echecs).append(
                {"ou": libelle, "detail": f"{n} entree(s)"})

    for sous, libelle in _ARBRES:
        base = DATA / sous
        if not base.exists():
            continue
        for chemin in list(base.glob("**/" + ancien)):
            if not chemin.is_dir():
                continue
            cible = chemin.parent / nouveau
            if cible.exists():
                # UN CACHE N'EST PAS UNE DONNEE. Un arbre deja present au
                # nouveau nom (reste d'une identite homonyme retiree) ne doit
                # pas faire remonter un echec : les vignettes se regenerent,
                # la reserve se refabrique. On le NOTE, sans alarmer.
                touches.append({"ou": libelle,
                                "detail": "deja present au nouveau nom, "
                                          "l'ancien sera regenere"})
                continue
            try:
                chemin.rename(cible)
                touches.append({"ou": libelle, "detail": str(chemin.parent)})
            except Exception as e:
                # Meme raison : on le dit, on ne bloque pas.
                touches.append({"ou": libelle,
                                "detail": "non deplace (%s) — sera regenere"
                                          % str(e)[:50]})

    d = _charger("text_pool.json")
    if isinstance(d, dict):
        n = 0
        for items in d.values():
            if isinstance(items, list):
                for e in items:
                    if isinstance(e, dict) and str(e.get("identity") or "").lower() == ancien:
                        e["identity"] = nouveau
                        n += 1
        if n:
            (touches if _ecrire("text_pool.json", d) else echecs).append(
                {"ou": "les bios et CTA", "detail": f"{n} texte(s)"})

    return {"ok": True, "identite": nouveau, "ancien": ancien,
            "touches": touches, "echecs": echecs, "impossible": list(IMPOSSIBLE)}


# ==============================================================================
# Retirer (jamais effacer)
# ==============================================================================

def archiver(nom: str) -> dict:
    """Sort une identite de la circulation, sans rien detruire.

    Le dossier part dans `data/_corbeille_identites/<nom>-<horodatage>/`, et
    un `_fiche.json` garde a cote tout ce qu'on savait d'elle. Ses comptes
    Instagram y compris : la regle de l'agence est que les comptes BANNIS ne
    se suppriment jamais, ils sont la trace de comment et pourquoi un compte
    meurt. Les effacer ici reviendrait a contourner cette regle par la porte
    de derriere.

    La fiche est ecrite AVANT le moindre deplacement, et par safe_json : c'est
    le seul exemplaire de ce qu'on retire, un JSON tronque par une coupure
    rendrait le retour arriere impossible.
    """
    nom = normaliser(nom)
    if not nom:
        return {"ok": False, "error": "Nom invalide"}
    if not existe(nom):
        return {"ok": False, "error": f"« {nom} » n'existe pas"}

    fiche = {"identite": nom, "archivee_le": int(time.time()), "sources": {}}
    d = _charger("jailbreak.json")
    if isinstance(d, dict) and nom in d:
        fiche["sources"]["jailbreak.json"] = d[nom]
    for fichier, libelle in _CLES:
        e = _charger(fichier)
        if isinstance(e, dict) and nom in e:
            fiche["sources"][fichier] = e[nom]
    # Tout ce qui permet de la remettre exactement ou elle etait.
    for fichier, libelle in _LISTES:
        e = _charger(fichier)
        if isinstance(e, list):
            bas = [str(x).lower() for x in e]
            if nom in bas:
                fiche["sources"][fichier] = {"position": bas.index(nom)}
    for fichier, champ, libelle in _SOUS_LISTES:
        e = _charger(fichier)
        if isinstance(e, dict) and nom in [str(x).lower() for x in (e.get(champ) or [])]:
            fiche["sources"][fichier] = {champ: True}
    for fichier, libelle in _PREFIXES:
        e = _charger(fichier)
        gardees = [k for k in (e.keys() if isinstance(e, dict) else (e or []))
                   if str(k).lower().startswith(nom + "|")]
        if gardees:
            fiche["sources"][fichier] = gardees
    e = _charger("text_pool.json")
    if isinstance(e, dict):
        textes = []
        for cat, items in e.items():
            if isinstance(items, list):
                textes += [x for x in items if isinstance(x, dict)
                           and str(x.get("identity") or "").lower() == nom]
        if textes:
            fiche["sources"]["text_pool.json"] = textes

    horodatage = time.strftime("%Y%m%d-%H%M%S")
    dossier = CORBEILLE / f"{nom}-{horodatage}"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(dossier / "_fiche.json", fiche, indent=2):
            return {"ok": False, "error": "La fiche n'a pas pu etre ecrite. "
                                          "Rien n'a ete retire."}
    except Exception as e:
        return {"ok": False, "error": f"Corbeille inaccessible ({e})"}

    retires = []
    if (IDENTITES / nom).is_dir():
        try:
            shutil.move(str(IDENTITES / nom), str(dossier / "media"))
            retires.append({"ou": "le dossier de la Bibliotheque",
                            "detail": "deplace dans la corbeille"})
        except Exception as e:
            return {"ok": False,
                    "error": f"Le dossier n'a pas pu etre deplace ({e}). "
                             "Rien n'a ete retire."}

    # Les jetons du portail se FERMENT, ils ne se suppriment pas : le journal
    # doit rester lisible (c'est ce que dit la fonction elle-meme).
    try:
        import va_portal as _vp
        n = _vp.oublier_identite(nom)
        if n:
            retires.append({"ou": "les liens du portail VA", "detail": f"{n} ferme(s)"})
    except Exception:
        pass

    d = _charger("jailbreak.json")
    if isinstance(d, dict) and nom in d:
        d.pop(nom, None)
        if _ecrire("jailbreak.json", d):
            retires.append({"ou": "le referentiel Jailbreak",
                            "detail": "copie dans la fiche"})
    for fichier, libelle in _CLES:
        e = _charger(fichier)
        if isinstance(e, dict) and nom in e:
            e.pop(nom, None)
            if _ecrire(fichier, e):
                retires.append({"ou": libelle, "detail": "copie dans la fiche"})
    for fichier, libelle in _LISTES:
        e = _charger(fichier)
        if isinstance(e, list) and nom in [str(x).lower() for x in e]:
            if _ecrire(fichier, [x for x in e if str(x).lower() != nom]):
                retires.append({"ou": libelle, "detail": "retiree"})
    for fichier, champ, libelle in _SOUS_LISTES:
        e = _charger(fichier)
        if isinstance(e, dict) and nom in [str(x).lower() for x in (e.get(champ) or [])]:
            e[champ] = [x for x in (e.get(champ) or []) if str(x).lower() != nom]
            if _ecrire(fichier, e):
                retires.append({"ou": libelle, "detail": "retiree"})
    # Les etoiles et les mises de cote : sans ce menage, une identite recreee
    # plus tard sous le MEME nom naitrait deja etoilee.
    for fichier, libelle in _PREFIXES:
        e = _charger(fichier)
        if isinstance(e, dict):
            neuf = {k: v for k, v in e.items()
                    if not str(k).lower().startswith(nom + "|")}
        elif isinstance(e, list):
            neuf = [k for k in e if not str(k).lower().startswith(nom + "|")]
        else:
            continue
        if len(neuf) != len(e) and _ecrire(fichier, neuf):
            retires.append({"ou": libelle, "detail": "copiees dans la fiche"})

    return {"ok": True, "identite": nom, "corbeille": str(dossier),
            "retires": retires, "impossible": list(IMPOSSIBLE)}
