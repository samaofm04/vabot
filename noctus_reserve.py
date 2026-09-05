# -*- coding: utf-8 -*-
"""Reserve de vidéos déjà montées, servies instantanément aux VA.

POURQUOI

Chaque bouton qui livre une vidéo la fabrique au moment du clic : 15 à 30
secondes par vidéo, jusqu'à trois par clic. Le VA attend devant Discord. Le
travail est le même s'il est fait la veille — il suffit qu'il soit fait
*avant*.

CE QUI COMPTE, ET CE QUI NE COMPTE PAS

Pour qu'un clic soit instantané, la réserve n'a pas besoin d'être grosse :
elle a besoin de **ne jamais être vide**. Un clic prend au plus trois vidéos ;
s'il y en a cinq qui attendent, c'est instantané. En stocker des milliers ne
rend rien de plus instantané — ça les rend seulement périmées, puisque les
templates et les captions changent tous les jours.

D'où un tampon court, rempli en continu, et une empreinte qui écarte ce qui
ne correspond plus à ce que le bouton produirait aujourd'hui.

LA REGLE QU'ON NE CASSE PAS

Deux comptes ne doivent jamais poster la même vidéo. Aujourd'hui l'unicité
vient de ce qu'on génère à chaque clic. Ici elle vient d'un renommage : servir
une variante, c'est la déplacer hors du stock. Le noyau garantit qu'un seul
appelant gagne ce renommage, même si deux VA cliquent dans la même seconde.

Un fichier sorti ne revient JAMAIS au stock, même si l'envoi Discord échoue :
une erreur d'envoi ne prouve pas que Discord n'a rien reçu. Perdre une
variante coûte 25 secondes de calcul ; un doublon coûte un shadowban.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path

import safe_json

#: Racine du stock. Surchargée par les tests, jamais en production.
RACINE = Path(os.environ.get("NOCTUS_RESERVE_DIR") or "data/noctus/reserve")

#: Profondeur visée par identité et par famille. Se règle sans toucher au code
#: (NOCTUS_RESERVE_PROFONDEUR), mais la valeur par défaut est celle qui compte :
#: le `.env` est dans le .gitignore, donc lui seul arrive jusqu'au VPS.
#:
#: SIX depuis le 04/09/2026, demandé : « toujours 6 d'avance ». Un clic livre
#: au plus trois vidéos, donc cinq suffisaient déjà à rendre tout clic
#: instantané ; le sixième est une marge, pas une accélération. Ne pas monter
#: beaucoup plus haut : le stock ne va pas plus vite, il vieillit — les
#: templates et les captions changent tous les jours, et `purger_perimes()`
#: jette ce qui ne correspond plus.
PROFONDEUR = max(1, int(os.environ.get("NOCTUS_RESERVE_PROFONDEUR") or "6"))

#: Les familles qui paient une génération. Les autres servent des fichiers
#: existants et n'ont rien à gagner ici.
FAMILLES = ("caption", "montage", "reelmonte", "template", "template_brut",
            "flash", "flash_banger", "flash_brut")

#: Quel BOUTON du menu est servi par quelle famille de la réserve.
#:
#: Les deux vocabulaires existaient déjà, chacun juste de son côté : le menu
#: parle en boutons (« ⭐⭐ Flash + Brut »), la réserve range par recette
#: (`flash_brut`). Tant que personne d'autre que Discord ne servait ces
#: vidéos, la traduction se faisait dans le corps de chaque bouton et n'avait
#: pas besoin d'exister ailleurs.
#:
#: Elle existe ici parce que le PARC demande maintenant « un capbanger pour
#: emma » sans passer par Discord, et qu'il ne peut pas deviner que cela se
#: range sous `caption`. Relevé bouton par bouton depuis cogs/user.py
#: (les `famille=` passés à _gen_and_send*), pas supposé.
#:
#: « 💬 Caption » (reelcaption) N'Y EST PAS, et ce n'est pas un oubli : son
#: bouton appelle la génération avec `famille=""` (cogs/user.py:3491), donc
#: rien n'est jamais mis en réserve pour lui. Le dire par une absence plutôt
#: que par une entrée vide : l'appelant qui ne trouve rien sait qu'il doit
#: générer, au lieu d'attendre un stock qui ne viendra pas.
FAMILLE_PAR_ACTION = {
    "capbanger": "caption",              # ⭐ Caption
    "montagebanger": "montage",          # ⭐⭐ Caption + Vidéo brut
    "reelmonte": "reelmonte",            # 🎞️ Template
    "templatebanger": "template",        # ⭐ Template
    "templatebrut": "template_brut",     # ⭐⭐ Template + Brut
    "templateflash": "flash",            # ⚡ Flash
    "templateflashbanger": "flash_banger",   # ⭐ Flash
    "templateflashbrut": "flash_brut",   # ⭐⭐ Flash + Brut
}


def famille_de(action: str):
    """La famille de réserve d'un bouton du menu, ou None s'il n'en a pas."""
    return FAMILLE_PAR_ACTION.get(str(action or "").strip().lower())

#: Le renommage suffit à l'unicité ; ce verrou évite seulement que deux fils
#: se disputent systématiquement le même candidat, et garde le déplacement
#: solidaire de sa ligne de journal.
_VERROU = threading.Lock()


def _dossier(identite: str, famille: str, quoi: str) -> Path:
    return RACINE / (identite or "?").lower() / (famille or "?") / quoi


def _journal() -> Path:
    return RACINE / "_journal.jsonl"


def _noter(evenement: dict) -> None:
    """Ajoute une ligne au journal. Ne lève jamais.

    Le journal dit qui a reçu quoi. Il n'est PAS la source de vérité du stock
    — le fichier l'est — mais il permet de reconstituer après coup ce qui est
    parti chez qui, ce qu'aucun listing de dossier ne raconte.
    """
    try:
        p = _journal()
        p.parent.mkdir(parents=True, exist_ok=True)
        evenement = dict(evenement)
        evenement.setdefault("ts", int(time.time()))
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(evenement, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _signature_fichier(p) -> str:
    """Taille et date d'un fichier, sans le lire.

    Lire des centaines de mégaoctets à chaque empreinte coûterait plus cher
    que la génération qu'on cherche à éviter. Taille + date suffisent : on ne
    se défend pas contre une falsification, seulement contre un fichier
    remplacé depuis.
    """
    try:
        st = Path(p).stat()
        return "%d-%d" % (st.st_size, st.st_mtime_ns)
    except Exception:
        return "absent"


def empreinte(identite: str, famille: str, source, brutes=(), caption=None,
              draft=None) -> str:
    """Ce qui identifie la RECETTE d'une variante.

    Deux variantes de même empreinte sont interchangeables : elles auraient
    ete produites par le meme bouton, avec les memes ingredients, aujourd'hui.

    L'empreinte porte le CONTENU des ingrédients, pas seulement leurs noms :
    un admin qui corrige le texte d'une caption, ou qui déplace le point de
    coupe d'un template, doit invalider ce qui a été fabriqué avant — sinon la
    réserve continue de servir l'ancienne version pendant des jours, et
    personne ne comprend pourquoi.
    """
    morceaux = [
        (identite or "").lower(),
        famille or "",
        Path(source).name if source else "",
        _signature_fichier(source) if source else "",
    ]
    for b in sorted(str(x) for x in (brutes or ())):
        morceaux += [Path(b).name, _signature_fichier(b)]
    if caption is not None:
        if isinstance(caption, dict):
            morceaux += [str(caption.get("id") or ""),
                         str(caption.get("text") or ""),
                         str(caption.get("desc") or "")]
        else:
            morceaux.append(str(caption))
    if isinstance(draft, dict):
        # Seuls les champs qui atteignent vraiment le moteur : un brouillon
        # porte aussi des notes d'interface, dont un changement ne modifie
        # aucune image.
        utiles = {c: draft.get(c) for c in
                  ("segments", "font", "style", "cut_at", "global_pos")
                  if c in draft}
        morceaux.append(json.dumps(utiles, sort_keys=True, ensure_ascii=False))
    return hashlib.sha1("\x00".join(morceaux).encode("utf-8")).hexdigest()


def deposer(identite: str, famille: str, mp4, emp: str, desc: str = "",
            recette: dict | None = None) -> Path | None:
    """Range une vidéo fraîchement produite dans le stock. Rend son chemin.

    Le fichier est DEPLACE, pas copié : il quitte ainsi le dossier des
    modèles, que chaque nouvelle génération purge en ne gardant que les douze
    plus récents. Une réserve rangée là-bas serait détruite au treizième clic.
    """
    source = Path(mp4)
    if not source.is_file():
        return None
    libre = _dossier(identite, famille, "libre")
    libre.mkdir(parents=True, exist_ok=True)
    jeton = uuid.uuid4().hex
    cible = libre / (jeton + ".mp4")
    try:
        try:
            os.replace(str(source), str(cible))
        except OSError:
            # Systèmes de fichiers différents : on recopie, puis on efface.
            import shutil
            shutil.copy2(str(source), str(cible))
            try:
                source.unlink()
            except Exception:
                pass
    except Exception:
        return None

    fiche = {"identite": (identite or "").lower(), "famille": famille,
             "empreinte": emp, "desc": desc or "",
             "recette": recette or {}, "cree_le": int(time.time()),
             "octets": cible.stat().st_size if cible.exists() else 0}
    safe_json.write(libre / (jeton + ".json"), fiche)
    _noter({"acte": "depose", "identite": identite, "famille": famille,
            "jeton": jeton, "empreinte": emp})
    return cible


def _fiches_libres(identite: str, famille: str):
    libre = _dossier(identite, famille, "libre")
    if not libre.is_dir():
        return []
    sortie = []
    for j in libre.glob("*.json"):
        mp4 = j.with_suffix(".mp4")
        if not mp4.is_file():
            continue                       # fiche orpheline : rien à servir
        fiche = safe_json.load(j, default=None)
        if isinstance(fiche, dict):
            sortie.append((mp4, j, fiche))
    return sortie


def compter(identite: str, famille: str, emp: str | None = None) -> int:
    """Combien de variantes attendent. Avec `emp`, seulement celles à jour."""
    return sum(1 for _m, _j, f in _fiches_libres(identite, famille)
               if emp is None or f.get("empreinte") == emp)


#: La réserve sert-elle ? Coupée le 05/09/2026 à la demande du propriétaire,
#: le temps d'écarter tout doute pendant qu'on cherchait un mélange
#: d'identités sur Discord.
#:
#: ELLE EST DANS LE CODE, PAS DANS LE .env : celui-ci est gitignoré et
#: n'arrive jamais jusqu'au VPS. Remettre True rallume tout, le stock est
#: resté intact — rien n'a été effacé.
#:
#: Couper le remplisseur (MAIN_COGS) ne suffisait PAS : les cases déjà
#: pleines auraient continué d'être servies. Il faut les deux robinets.
#:
#: RALLUMEE le 05/09 une fois le chemin réparé (d0458d9) : le verdict
#: d'assemblage voyage désormais avec la vidéo, donc une variante servie
#: depuis le stock avertit le VA comme le ferait une génération fraîche.
ACTIF = True


def prendre(identite: str, famille: str, emp: str | None = None,
            demandeur: str = "", fiche_out=None) -> tuple:
    """Sort UNE variante du stock. Rend (chemin, description) ou (None, "").

    C'est le renommage qui garantit l'unicité, pas le verrou : le noyau ne
    laisse qu'un seul appelant réussir `os.replace`. Le perdant reçoit
    FileNotFoundError et passe au candidat suivant.

    Rend (None, "") quand la réserve est coupée : c'est exactement ce que
    rend un stock vide, donc chaque appelant repart en génération à la
    demande sans qu'une seule ligne de plus soit nécessaire ailleurs.
    """
    if not ACTIF:
        return None, ""
    # « repli » absent = fiche d'AVANT le correctif du 05/09 : on ignore si
    # cette variante est un montage ou un template nu, donc on ne la sert pas.
    # Une fiche ecrite depuis porte toujours la cle, meme a False.
    candidats = [(m, j, f) for m, j, f in _fiches_libres(identite, famille)
                 if (emp is None or f.get("empreinte") == emp)
                 and "repli" in (f.get("recette") or {})]
    if not candidats:
        return None, ""
    random.shuffle(candidats)
    servi = _dossier(identite, famille, "servi")
    servi.mkdir(parents=True, exist_ok=True)

    with _VERROU:
        for mp4, fiche_json, fiche in candidats:
            cible = servi / mp4.name
            try:
                os.replace(str(mp4), str(cible))
            except FileNotFoundError:
                continue                   # un autre l'a pris : au suivant
            except OSError:
                continue
            try:
                fiche_json.unlink()
            except Exception:
                pass
            _noter({"acte": "sorti", "identite": identite, "famille": famille,
                    "jeton": mp4.stem, "empreinte": fiche.get("empreinte"),
                    "demandeur": demandeur})
            # La fiche part avec la vidéo : elle porte le verdict d'assemblage
            # calculé à la fabrication. Sans lui, l'appelant ne peut pas
            # distinguer un montage réussi d'un template nu, et servirait le
            # second en disant « poste-la telle quelle ».
            if isinstance(fiche_out, dict):
                fiche_out.clear()
                fiche_out.update(fiche)
            return cible, str(fiche.get("desc") or "")
    return None, ""


def solder(chemin, motif: str = "envoye") -> None:
    """Efface une variante sortie, quoi qu'il soit arrivé à l'envoi.

    Elle ne retourne JAMAIS au stock. Un échec d'envoi Discord ne prouve pas
    que Discord n'a rien reçu ; re-servir le fichier serait précisément le
    doublon qu'on interdit.
    """
    p = Path(chemin)
    try:
        if p.is_file():
            p.unlink()
    except Exception:
        pass
    _noter({"acte": motif, "jeton": p.stem})


def purger_perimes(identite: str, famille: str, emp_courante: str) -> int:
    """Jette ce qui ne correspond plus à la recette d'aujourd'hui.

    Sans ça, un template retouché laisserait la réserve servir l'ancienne
    version jusqu'à épuisement — un défaut invisible, puisque les fichiers
    sont bien là et que rien n'échoue.
    """
    jetes = 0
    for mp4, fiche_json, fiche in _fiches_libres(identite, famille):
        if fiche.get("empreinte") == emp_courante:
            continue
        for f in (mp4, fiche_json):
            try:
                f.unlink()
            except Exception:
                pass
        jetes += 1
    if jetes:
        _noter({"acte": "perime", "identite": identite, "famille": famille,
                "combien": jetes})
    return jetes


def manque(identite: str, famille: str, emp: str,
           profondeur: int | None = None) -> int:
    """Combien de variantes il reste à fabriquer pour atteindre la cible."""
    vise = PROFONDEUR if profondeur is None else max(0, int(profondeur))
    return max(0, vise - compter(identite, famille, emp))


def etat() -> dict:
    """Ce que contient la réserve, par identité et par famille."""
    sortie: dict = {}
    if not RACINE.is_dir():
        return sortie
    for dossier_identite in sorted(RACINE.iterdir()):
        if not dossier_identite.is_dir() or dossier_identite.name.startswith("_"):
            continue
        for dossier_famille in sorted(dossier_identite.iterdir()):
            if not dossier_famille.is_dir():
                continue
            n = compter(dossier_identite.name, dossier_famille.name)
            if n:
                sortie["%s/%s" % (dossier_identite.name,
                                  dossier_famille.name)] = n
    return sortie
