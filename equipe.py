# -*- coding: utf-8 -*-
"""L'equipe Insta : qui est qui, et quel role il tient.

POURQUOI CE FICHIER EXISTE

Le referentiel Jailbreak connait des FICHES VA, pas des personnes. Une fiche
est un nom sous UNE identite : « Noum » chez jessye, « VA NOUM 4X1 » chez lola.
La meme personne a donc autant de fiches que de models qu'elle fait tourner,
et rien ne les reunit. Le proprietaire voulait un endroit ou ecrire « Noum est
chef d'equipe, voila ses fiches » : c'est ce fichier.

LE ROLE EST UNE INFORMATION, PAS UN DROIT. Il n'a aucun lien avec les roles
d'acces des Reglages (owner, chatter...) : un « Manager » ecrit ici n'ouvre
aucun onglet. Les brancher l'un sur l'autre transformerait une fiche de
presentation en porte d'entree.

LA FRONTIERE D'IDENTITE NE SE FRANCHIT PAS PAR LE NOM. Le meme nom de fiche
sous deux creatrices designe deux personnes differentes (clics_personnes et
fusion_vas le disent deja, et des noms comme « Jaurel X2 » / « Jaurel X3 »
existent en production). Le SEUL regroupement automatique permis est le
pseudo Discord : deux fiches qui portent le meme pseudo sont la meme
personne. Tout le reste se rattache a la main.

Ce module ne connait ni Flask ni le disque du referentiel : `vue()` prend les
fiches et les comptes en parametre et rend un dictionnaire. C'est ce qui le
rend testable sans serveur, et importable par le site comme par
identite_admin sans cycle.

RIEN EN SILENCE

- Un fichier present mais illisible n'est JAMAIS pris pour une equipe vide :
  la premiere ecriture suivante graverait ce vide. On leve une erreur nommee
  et on refuse d'ecrire par-dessus.
- Une ecriture ratee leve une erreur nommee : jamais un « ok » menteur.
- Un lien vers une fiche disparue (supprimee, renommee ailleurs, identite
  archivee) reste dans le fichier et s'affiche comme CASSE, avec sa raison.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import safe_json

#: Surchargeable par les tests (monkeypatch) : lu a chaque appel.
EQUIPE_FILE = Path("data") / "equipe.json"

ROLES_DEFAUT = ("VA", "Manager", "Chef d'équipe", "Monteur")
#: Le role propose aux suggestions TANT QUE le fichier n'en dit pas d'autre
#: (cle « role_propose ») : ce sont des fiches VA, par definition. Il est
#: enregistre et suit les renommages : fige ici, renommer « VA » faisait
#: creer par « Tout ajouter » des membres sans role, sans un mot.
ROLE_PROPOSE = "VA"

_MAX_NOM = 80
#: Le nom d'une FICHE se borne comme jailbreak.add_va / update_va le bornent
#: (strip()[:60], espaces internes gardes). Normalise autrement — espaces
#: fusionnes, coupe a 80 — une fiche « VA  Noum » ou un nom de 70 caracteres
#: ne correspondait jamais a son lien : lien casse des la creation.
_MAX_FICHE = 60
_MAX_ROLE = 40
_MAX_DISCORD = 60
_MAX_DISCORDS_AUTRES = 10
_MAX_NOTE = 1000

# Lire-modifier-ecrire sous verrou : le site sert ses requetes sur plusieurs
# fils, et deux clics rapproches (« Ajouter » puis « Tout ajouter ») partaient
# sinon chacun de la meme copie — le second effacait le premier.
_LOCK = threading.RLock()


class ErreurEquipe(Exception):
    """Un refus NOMME : son message se montre tel quel a l'ecran."""


class EquipeIllisible(ErreurEquipe):
    """Le fichier existe mais ne se lit pas : on n'ecrit pas par-dessus."""


class EcritureImpossible(ErreurEquipe):
    """safe_json.write a rendu False : rien n'a ete enregistre."""


# ==============================================================================
# Petits outils
# ==============================================================================

def _chemin(chemin=None) -> Path:
    return Path(chemin) if chemin else Path(EQUIPE_FILE)


def _maintenant() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _date_fr(s) -> str:
    """« 2026-09-25T22:00:00 » -> « 25/09/2026 » ; autre chose, tel quel."""
    s = str(s or "")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    return s


def _propre(v, n: int) -> str:
    """Une chaine d'une ligne, bornee. Les retours a la ligne d'un champ
    « nom » cassaient l'alignement du tableau sans rien apporter.

    Pour le nom, le role et le Discord d'un MEMBRE seulement : le nom d'une
    fiche passe par _nom_fiche."""
    return " ".join(str(v or "").split())[:n]


def _nom_fiche(v) -> str:
    """Le nom d'une fiche VA, borne EXACTEMENT comme jailbreak le borne."""
    return str(v or "").strip()[:_MAX_FICHE]


def _discords(v) -> list:
    """Une liste de pseudos Discord (liste, ou texte separe par des virgules
    ou des retours a la ligne), nettoyes et sans doublon.

    Pas de coupure sur les espaces : un ancien pseudo « Nom Prenom#1234 »
    en contient."""
    if isinstance(v, (list, tuple)):
        brut = [str(x or "") for x in v]
    else:
        brut = str(v or "").replace("\n", ",").split(",")
    out, vus = [], set()
    for x in brut:
        p = _propre(x, _MAX_DISCORD).lstrip("@").strip()
        n = norm_discord(p)
        if n and n not in vus:
            vus.add(n)
            out.append(p)
    return out


def _autres_discords(m: dict, v) -> list:
    """Les pseudos secondaires d'un membre, sans son pseudo principal.

    Refus nomme au-dela de _MAX_DISCORDS_AUTRES plutot qu'une coupure : un
    pseudo perdu en silence redevenait une personne a part."""
    principal = norm_discord(m.get("discord"))
    out = [p for p in _discords(v) if norm_discord(p) != principal]
    if len(out) > _MAX_DISCORDS_AUTRES:
        raise ErreurEquipe(f"Trop d'autres @Discord ({len(out)}) : "
                           f"{_MAX_DISCORDS_AUTRES} au plus.")
    return out


def norm_discord(s) -> str:
    """Le pseudo Discord sous la forme qui sert a COMPARER.

    Meme regle que jailbreak._norm_handle (casse et @ de tete ignores) : si
    les deux divergeaient, une fiche et un membre du meme pseudo ne se
    reconnaitraient pas.
    """
    return str(s or "").strip().lower().lstrip("@").strip()


def _cle(identite, fiche) -> tuple:
    """(identite, fiche) en minuscules : jailbreak compare les noms de fiche
    sans la casse, les liens doivent faire pareil."""
    return (str(identite or "").strip().lower(), str(fiche or "").strip().lower())


def _vide() -> dict:
    return {"roles": list(ROLES_DEFAUT), "membres": [], "masquees": []}


def _nouvel_id(d: dict) -> str:
    pris = {m.get("id") for m in d.get("membres") or []}
    while True:
        i = "m" + secrets.token_hex(4)
        if i not in pris:
            return i


# ==============================================================================
# Lecture / ecriture
# ==============================================================================

def _illisible(p: Path, pourquoi: str) -> EquipeIllisible:
    prev = p.with_suffix(p.suffix + ".prev")
    aide = (f" Une copie de l'état précédent existe : {prev.name}."
            if prev.exists() else "")
    return EquipeIllisible(
        f"{p.name} est illisible ({pourquoi}). Rien ne sera écrit par-dessus "
        f"tant qu'il n'est pas réparé.{aide}")


def _lien_valide(l, p: Path, ou: str) -> dict:
    if not isinstance(l, dict):
        raise _illisible(p, f"{ou} : un lien n'est pas un objet")
    ident = str(l.get("identite") or "").strip().lower()
    fiche = _nom_fiche(l.get("fiche"))
    if not ident or not fiche:
        raise _illisible(p, f"{ou} : un lien sans identité ou sans fiche")
    out = dict(l)
    out["identite"], out["fiche"] = ident, fiche
    if out.get("supprimee") is not None:
        out["supprimee"] = str(out["supprimee"] or "") or _maintenant()
    return out


def _valider(brut, p: Path) -> dict:
    """Controle la forme ENTIERE avant de rendre quoi que ce soit.

    Un membre qui ne serait pas un objet, ou un lien sans fiche, ne peut
    venir que d'une corruption ou d'une retouche a la main. L'ignorer le
    ferait disparaitre a la prochaine ecriture : on prefere refuser.
    """
    if not isinstance(brut, dict):
        raise _illisible(p, "la racine n'est pas un objet")
    roles = brut.get("roles", list(ROLES_DEFAUT))
    membres = brut.get("membres", [])
    masquees = brut.get("masquees", [])
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise _illisible(p, "« roles » n'est pas une liste de textes")
    if not isinstance(membres, list):
        raise _illisible(p, "« membres » n'est pas une liste")
    if not isinstance(masquees, list):
        raise _illisible(p, "« masquees » n'est pas une liste")
    rp = brut.get("role_propose", ROLE_PROPOSE)
    if not isinstance(rp, str):
        raise _illisible(p, "« role_propose » n'est pas un texte")
    d = dict(brut)
    d["roles"] = [_propre(r, _MAX_ROLE) for r in roles if _propre(r, _MAX_ROLE)]
    if "role_propose" in brut:
        d["role_propose"] = _propre(rp, _MAX_ROLE)
    d["membres"] = []
    pris = set()
    # Les ids ecrits dans le fichier, pour qu'un id REDONNE ne tombe jamais
    # sur celui d'un membre plus loin dans la liste.
    ecrits = {str(m.get("id") or "").strip() for m in membres if isinstance(m, dict)}
    for k, m in enumerate(membres):
        if not isinstance(m, dict):
            raise _illisible(p, f"le membre n°{k + 1} n'est pas un objet")
        fiches = m.get("fiches", [])
        if not isinstance(fiches, list):
            raise _illisible(p, f"les fiches du membre n°{k + 1} ne sont pas une liste")
        autres = m.get("discords_autres", [])
        if not isinstance(autres, list) or not all(isinstance(x, str) for x in autres):
            raise _illisible(p, f"les autres @Discord du membre n°{k + 1} ne sont pas une liste de textes")
        mm = dict(m)
        mm["nom"] = _propre(m.get("nom"), _MAX_NOM)
        mm["role"] = _propre(m.get("role"), _MAX_ROLE)
        mm["discord"] = _propre(m.get("discord"), _MAX_DISCORD).lstrip("@")
        principal = norm_discord(mm["discord"])
        mm["discords_autres"] = [x for x in _discords(autres) if norm_discord(x) != principal]
        mm["note"] = str(m.get("note") or "")
        mm["actif"] = m.get("actif") is not False
        mm["fiches"] = [_lien_valide(l, p, f"membre n°{k + 1}") for l in fiches]
        mm.setdefault("cree", "")
        mm.setdefault("modifie", "")
        # Un id manquant ou en double (retouche a la main) : on en redonne un
        # plutot que de refuser le fichier. Il est DERIVE du contenu, pas tire
        # au hasard : un GET n'ecrit rien, et un id aleatoire changeait a
        # chaque lecture — le fragment en montrait un, la requete suivante en
        # relisait un autre, et toute action sur ce membre repondait
        # « introuvable, recharge » en boucle. Grave a la prochaine ecriture.
        i = str(m.get("id") or "").strip()
        if not i or i in pris:
            base = "m" + hashlib.sha1(
                f"{k}|{mm['nom']}|{mm.get('cree') or ''}".encode("utf-8")).hexdigest()[:8]
            i, n = base, 1
            while i in pris or i in ecrits:
                n += 1
                i = f"{base}-{n}"
        mm["id"] = i
        pris.add(i)
        d["membres"].append(mm)
    d["masquees"] = [_lien_valide(l, p, "masquées") for l in masquees]
    return d


def lire(chemin=None) -> dict:
    """L'equipe telle qu'enregistree.

    Fichier absent : structure vide (avec les roles par defaut).
    Fichier present mais illisible : EquipeIllisible, jamais une equipe vide.
    """
    p = _chemin(chemin)
    with _LOCK:
        if not p.exists():
            return _vide()
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception as e:
            raise _illisible(p, str(e)[:120])
        if not txt.strip():
            raise _illisible(p, "fichier vide")
        try:
            brut = json.loads(txt)
        except Exception as e:
            raise _illisible(p, f"JSON invalide : {str(e)[:120]}")
        return _valider(brut, p)


def _ecrire(d: dict, chemin=None) -> None:
    p = _chemin(chemin)
    ok = safe_json.write(p, d, indent=2)
    if ok is not True:
        raise EcritureImpossible(
            f"Écriture de {p.name} impossible : rien n'a été enregistré.")


@contextmanager
def _modifier(chemin=None):
    """Lire -> modifier -> ecrire, sous le verrou. Un refus leve dans le
    bloc n'ecrit rien : le fichier reste tel qu'il etait."""
    with _LOCK:
        d = lire(chemin)
        yield d
        _ecrire(d, chemin)


# ==============================================================================
# Recherches internes
# ==============================================================================

def _membre(d: dict, mid) -> dict:
    mid = str(mid or "").strip()
    for m in d["membres"]:
        if m["id"] == mid:
            return m
    raise ErreurEquipe("Membre introuvable : la liste a changé entre-temps, "
                       "recharge l'onglet.")


def _proprietaire(d: dict, identite, fiche):
    """Le membre qui porte la fiche VIVANTE de ce nom.

    Un lien marque « supprimee » ne compte pas : il visait la fiche d'avant,
    et une fiche recreee sous le meme nom est une autre personne — sans
    cette exception, elle ne pouvait etre ni ajoutee ni masquee."""
    k = _cle(identite, fiche)
    for m in d["membres"]:
        for l in m["fiches"]:
            if not l.get("supprimee") and _cle(l["identite"], l["fiche"]) == k:
                return m
    return None


def role_propose(d: dict) -> str:
    """Le role propose aux suggestions, tel qu'enregistre (« » = aucun)."""
    return str(d.get("role_propose", ROLE_PROPOSE) or "")


def _role_canonique(d: dict, role) -> str:
    """Le role tel qu'il est ecrit dans la liste. Vide = sans role.

    Un role inconnu est REFUSE plutot que cree en douce : sinon une faute de
    frappe dans un formulaire ajoutait un role fantome a la liste.
    """
    role = _propre(role, _MAX_ROLE)
    if not role:
        return ""
    for r in d["roles"]:
        if r.casefold() == role.casefold():
            return r
    raise ErreurEquipe(f"Rôle inconnu : « {role} ». Ajoute-le d'abord dans "
                       "l'éditeur des rôles.")


def _liens_propres(liens) -> list:
    out, vus = [], set()
    for l in liens or []:
        if isinstance(l, dict):
            ident, fiche = l.get("identite"), l.get("fiche")
        else:
            ident, fiche = l
        ident = str(ident or "").strip().lower()
        fiche = _nom_fiche(fiche)
        if not ident or not fiche:
            raise ErreurEquipe("Fiche invalide : identité ou nom manquant.")
        k = _cle(ident, fiche)
        if k in vus:
            continue
        vus.add(k)
        out.append({"identite": ident, "fiche": fiche})
    return out


def _lier_dans(d: dict, m: dict, liens: list) -> dict:
    """Lie des fiches a un membre, TOUT OU RIEN.

    Une fiche n'appartient qu'a une personne : la lier a une seconde
    reviendrait a compter ses comptes deux fois. On refuse nommement, en
    disant a qui elle appartient deja.
    """
    conflits = []
    for l in liens:
        p = _proprietaire(d, l["identite"], l["fiche"])
        if p is not None and p["id"] != m["id"]:
            conflits.append(f"« {l['identite']} · {l['fiche']} » est déjà liée "
                            f"à {p['nom'] or '(sans nom)'}")
    if conflits:
        raise ErreurEquipe("; ".join(conflits) + " — délie-la d'abord.")
    ajoutees = demasquees = 0
    for l in liens:
        k = _cle(l["identite"], l["fiche"])
        deja = next((x for x in m["fiches"] if _cle(x["identite"], x["fiche"]) == k), None)
        if deja is None:
            m["fiches"].append({"identite": l["identite"], "fiche": l["fiche"]})
            ajoutees += 1
        elif deja.get("supprimee"):
            # Son ancien lien visait une fiche supprimee ; la relier, c'est
            # dire que la fiche recreee est bien la sienne.
            deja.pop("supprimee", None)
            deja.pop("motif", None)
            deja["fiche"] = l["fiche"]
            ajoutees += 1
        # Lier une fiche masquee, c'est dire qu'elle EST dans l'equipe : le
        # masquage n'a plus de sens, on le leve.
        avant = len(d["masquees"])
        d["masquees"] = [x for x in d["masquees"]
                         if _cle(x["identite"], x["fiche"]) != k]
        demasquees += avant - len(d["masquees"])
    if ajoutees:
        m["modifie"] = _maintenant()
    return {"ajoutees": ajoutees, "demasquees": demasquees}


# ==============================================================================
# Membres
# ==============================================================================

def _note(v) -> str:
    """Une note, REFUSEE au-dela de _MAX_NOTE plutot que coupee : la fin
    d'une note tronquee en silence etait perdue sans que personne le sache."""
    note = str(v or "").strip()
    if len(note) > _MAX_NOTE:
        raise ErreurEquipe(f"Note trop longue ({len(note)} caractères, "
                           f"{_MAX_NOTE} au plus) : raccourcis-la.")
    return note


def _creer_dans(d: dict, n: dict) -> dict:
    nom = _propre(n.get("nom"), _MAX_NOM)
    if not nom:
        raise ErreurEquipe("Le nom est obligatoire.")
    m = {
        "id": _nouvel_id(d),
        "nom": nom,
        "role": _role_canonique(d, n.get("role")),
        "discord": _propre(n.get("discord"), _MAX_DISCORD).lstrip("@"),
        "discords_autres": [],
        "note": _note(n.get("note")),
        "actif": n.get("actif") is not False,
        "fiches": [],
        "cree": _maintenant(),
        "modifie": _maintenant(),
    }
    m["discords_autres"] = _autres_discords(m, n.get("discords_autres"))
    d["membres"].append(m)
    _lier_dans(d, m, _liens_propres(n.get("fiches")))
    return m


def ajouter_membres(nouveaux, chemin=None) -> list:
    """Cree plusieurs membres en UNE ecriture.

    `nouveaux` : [{nom, role, discord, discords_autres, note, actif, fiches}].
    Tout ou rien : un seul refus (nom vide, role inconnu, fiche deja liee) et
    rien n'est cree.
    """
    with _modifier(chemin) as d:
        return [_creer_dans(d, n) for n in nouveaux or []]


def appliquer_suggestions(ajouts, rattachements, chemin=None) -> dict:
    """« Tout ajouter » : cree des membres ET rattache des fiches a des
    membres existants, en UNE ecriture, tout ou rien.

    `ajouts` : comme ajouter_membres. `rattachements` : [(id_membre, liens)]
    — les suggestions dont le @Discord est deja porte par UN membre : meme
    pseudo = meme personne. Les creer faisait figurer la meme personne deux
    fois, ses comptes Insta repartis sur deux lignes.
    """
    with _modifier(chemin) as d:
        n_fiches = 0
        vers = []
        for mid, liens in rattachements or []:
            m = _membre(d, mid)
            n_fiches += _lier_dans(d, m, _liens_propres(liens))["ajoutees"]
            vers.append(m["nom"])
        crees = [_creer_dans(d, n) for n in ajouts or []]
        return {"crees": crees, "rattachees": len(rattachements or []),
                "fiches_rattachees": n_fiches, "vers": vers}


def ajouter_membre(nom, role="", discord="", note="", actif=True, fiches=(),
                   chemin=None, discords_autres=()) -> dict:
    return ajouter_membres([{"nom": nom, "role": role, "discord": discord,
                             "discords_autres": discords_autres,
                             "note": note, "actif": actif, "fiches": fiches}],
                           chemin=chemin)[0]


def modifier_membre(mid, chemin=None, **champs) -> dict:
    """Change les champs FOURNIS seulement (nom, role, discord,
    discords_autres, note, actif) : le menu deroulant du role n'envoie que le
    role, et ne doit pas effacer la note au passage."""
    inconnus = set(champs) - {"nom", "role", "discord", "discords_autres", "note", "actif"}
    if inconnus:
        raise ErreurEquipe("Champ inconnu : " + ", ".join(sorted(inconnus)))
    with _modifier(chemin) as d:
        m = _membre(d, mid)
        if "nom" in champs:
            nom = _propre(champs["nom"], _MAX_NOM)
            if not nom:
                raise ErreurEquipe("Le nom est obligatoire.")
            m["nom"] = nom
        if "role" in champs:
            # Le formulaire renvoie TOUS les champs. Un role deja porte mais
            # absent de la liste (retouche du fichier a la main) ne doit pas
            # bloquer la correction d'une note : on ne le controle que s'il
            # CHANGE.
            r = _propre(champs["role"], _MAX_ROLE)
            if r.casefold() != m["role"].casefold():
                m["role"] = _role_canonique(d, r)
        if "discord" in champs:
            m["discord"] = _propre(champs["discord"], _MAX_DISCORD).lstrip("@")
        if "discords_autres" in champs:
            m["discords_autres"] = _autres_discords(m, champs["discords_autres"])
        elif "discord" in champs:
            # Le pseudo principal a pu devenir l'un des secondaires : il ne
            # figure pas deux fois.
            m["discords_autres"] = _autres_discords(m, m.get("discords_autres"))
        if "note" in champs:
            # Meme regle que le role : une note deja trop longue (retouche a
            # la main) ne bloque pas le reste tant qu'elle ne change pas.
            note = str(champs["note"] or "").strip()
            if note != m["note"].strip():
                m["note"] = _note(note)
        if "actif" in champs:
            m["actif"] = bool(champs["actif"])
        m["modifie"] = _maintenant()
        return dict(m)


def retirer_membre(mid, chemin=None) -> dict:
    """Retire la personne de l'equipe. Ses fiches VA ne sont PAS touchees :
    elles redeviennent des suggestions."""
    with _modifier(chemin) as d:
        m = _membre(d, mid)
        d["membres"] = [x for x in d["membres"] if x["id"] != m["id"]]
        return m


def lier_fiches(mid, liens, chemin=None) -> dict:
    with _modifier(chemin) as d:
        m = _membre(d, mid)
        r = _lier_dans(d, m, _liens_propres(liens))
        r["membre"] = m["nom"]
        return r


def lier_fiche(mid, identite, fiche, chemin=None) -> dict:
    return lier_fiches(mid, [(identite, fiche)], chemin=chemin)


def delier_fiche(mid, identite, fiche, chemin=None) -> dict:
    """Detache une fiche (y compris un lien casse : c'est ainsi qu'on le
    fait disparaitre, a la main et en connaissance de cause)."""
    k = _cle(identite, fiche)
    with _modifier(chemin) as d:
        m = _membre(d, mid)
        avant = len(m["fiches"])
        m["fiches"] = [l for l in m["fiches"] if _cle(l["identite"], l["fiche"]) != k]
        if len(m["fiches"]) == avant:
            raise ErreurEquipe(f"« {k[0]} · {fiche} » n'est pas liée à "
                               f"{m['nom']} : la liste a changé, recharge.")
        m["modifie"] = _maintenant()
        return {"membre": m["nom"]}


def fusionner(garde_id, absorbe_id, chemin=None) -> dict:
    """Fond `absorbe` dans `garde` : ses fiches passent a `garde`, puis il
    disparait.

    Rien ne se perd : un champ vide chez `garde` prend la valeur de
    `absorbe` ; un @Discord DIFFERENT est garde comme pseudo secondaire (il
    sert encore a reconnaitre la personne — jete, ses nouvelles fiches la
    recreaient en double) ; un role different est reporte dans la note ; les
    deux notes sont mises bout a bout. Si la note reunie depasse
    _MAX_NOTE, refus nomme : la couper perdait la fin au prochain
    « Enregistrer ».
    """
    if str(garde_id or "") == str(absorbe_id or ""):
        raise ErreurEquipe("Choisis deux personnes différentes.")
    with _modifier(chemin) as d:
        g = _membre(d, garde_id)
        a = _membre(d, absorbe_id)
        deja = {_cle(l["identite"], l["fiche"]) for l in g["fiches"]}
        passees = 0
        for l in a["fiches"]:
            if _cle(l["identite"], l["fiche"]) not in deja:
                g["fiches"].append(l)
                passees += 1
        avant = {norm_discord(x) for x in [g["discord"]] + g["discords_autres"]}
        g["discord"] = g["discord"] or a["discord"]
        g["discords_autres"] = _autres_discords(
            g, g["discords_autres"] + [a["discord"]] + a["discords_autres"])
        discords_gardes = [x for x in g["discords_autres"] if norm_discord(x) not in avant]
        note = g["note"]
        role_reporte = ""
        if a["role"] and g["role"] and a["role"].casefold() != g["role"].casefold():
            role_reporte = a["role"]
            note = (note + "\n" + f"Rôle aussi : {a['role']}").strip()
        g["role"] = g["role"] or a["role"]
        if a["note"] and a["note"] not in note:
            note = (note + "\n" + a["note"]).strip()
        if len(note) > _MAX_NOTE:
            raise ErreurEquipe(f"Notes trop longues une fois réunies ({len(note)} caractères, "
                               f"{_MAX_NOTE} au plus) : raccourcis-en une avant de fusionner.")
        g["note"] = note
        g["actif"] = bool(g["actif"] or a["actif"])
        g["modifie"] = _maintenant()
        d["membres"] = [x for x in d["membres"] if x["id"] != a["id"]]
        return {"garde": g["nom"], "absorbe": a["nom"], "fiches": passees,
                "discords_gardes": discords_gardes, "role_reporte": role_reporte}


# ==============================================================================
# Roles
# ==============================================================================

def ajouter_role(nom, chemin=None) -> str:
    nom = _propre(nom, _MAX_ROLE)
    if not nom:
        raise ErreurEquipe("Nom de rôle vide.")
    with _modifier(chemin) as d:
        if any(r.casefold() == nom.casefold() for r in d["roles"]):
            raise ErreurEquipe(f"Le rôle « {nom} » existe déjà.")
        d["roles"].append(nom)
        return nom


def renommer_role(ancien, nouveau, chemin=None) -> int:
    """Renomme un role ; les membres qui le portent suivent. Rend leur
    nombre."""
    nouveau = _propre(nouveau, _MAX_ROLE)
    if not nouveau:
        raise ErreurEquipe("Nouveau nom de rôle vide.")
    with _modifier(chemin) as d:
        ancien_c = _role_canonique(d, ancien)
        if not ancien_c:
            raise ErreurEquipe("Rôle à renommer manquant.")
        if nouveau == ancien_c:
            return 0
        for r in d["roles"]:
            if r.casefold() == nouveau.casefold() and r != ancien_c:
                raise ErreurEquipe(f"Le rôle « {r} » existe déjà.")
        d["roles"] = [nouveau if r == ancien_c else r for r in d["roles"]]
        n = 0
        for m in d["membres"]:
            if m["role"].casefold() == ancien_c.casefold():
                m["role"] = nouveau
                n += 1
        # Le role propose aux suggestions suit, comme les membres.
        if role_propose(d).casefold() == ancien_c.casefold():
            d["role_propose"] = nouveau
        return n


def supprimer_role(nom, chemin=None) -> str:
    """Refuse tant qu'un membre porte le role : sinon ces membres se
    retrouveraient avec un role qui n'existe plus nulle part. Refuse aussi le
    role propose aux suggestions : « Tout ajouter » creerait sinon des
    membres sans role."""
    with _modifier(chemin) as d:
        r = _role_canonique(d, nom)
        if not r:
            raise ErreurEquipe("Rôle à supprimer manquant.")
        n = sum(1 for m in d["membres"] if m["role"].casefold() == r.casefold())
        if n:
            raise ErreurEquipe(f"Le rôle « {r} » est porté par {n} membre(s) : "
                               "change leur rôle avant de le supprimer.")
        if role_propose(d).casefold() == r.casefold():
            raise ErreurEquipe(f"« {r} » est le rôle proposé aux suggestions : choisis-en "
                               "un autre (Rôles → Rôle proposé) avant de le supprimer.")
        d["roles"] = [x for x in d["roles"] if x != r]
        return r


def definir_role_propose(nom, chemin=None) -> str:
    """Le role que recoivent les suggestions ajoutees. « » = aucun."""
    with _modifier(chemin) as d:
        r = _role_canonique(d, nom)
        d["role_propose"] = r
        return r


# ==============================================================================
# Fiches masquees (« pas dans l'equipe »)
# ==============================================================================

def masquer_fiches(liens, chemin=None) -> int:
    """Range des fiches dans « Masquées » : elles ne sont plus proposees.
    Reversible (demasquer_fiche). Refuse une fiche deja liee a quelqu'un :
    elle EST dans l'equipe, la masquer serait contradictoire."""
    liens = _liens_propres(liens)
    with _modifier(chemin) as d:
        conflits = []
        for l in liens:
            p = _proprietaire(d, l["identite"], l["fiche"])
            if p is not None:
                conflits.append(f"« {l['identite']} · {l['fiche']} » est liée à "
                                f"{p['nom'] or '(sans nom)'}")
        if conflits:
            raise ErreurEquipe("; ".join(conflits) + " — délie-la d'abord.")
        # Une masquee marquee « supprimee » visait la fiche d'avant : elle
        # cede la place a la fiche recreee, sinon celle-ci ne se masquait pas.
        cles = {_cle(l["identite"], l["fiche"]) for l in liens}
        d["masquees"] = [x for x in d["masquees"]
                         if not (x.get("supprimee") and _cle(x["identite"], x["fiche"]) in cles)]
        deja = {_cle(x["identite"], x["fiche"]) for x in d["masquees"]}
        n = 0
        for l in liens:
            if _cle(l["identite"], l["fiche"]) not in deja:
                d["masquees"].append({"identite": l["identite"],
                                      "fiche": l["fiche"], "le": _maintenant()})
                n += 1
        return n


def masquer_fiche(identite, fiche, chemin=None) -> int:
    return masquer_fiches([(identite, fiche)], chemin=chemin)


def demasquer_fiche(identite, fiche, chemin=None) -> int:
    k = _cle(identite, fiche)
    with _modifier(chemin) as d:
        avant = len(d["masquees"])
        d["masquees"] = [x for x in d["masquees"]
                         if _cle(x["identite"], x["fiche"]) != k]
        n = avant - len(d["masquees"])
        if not n:
            raise ErreurEquipe(f"« {k[0]} · {fiche} » n'est pas masquée : "
                               "la liste a changé, recharge.")
        return n


# ==============================================================================
# Renommages venus d'ailleurs (fiche VA, identite)
# ==============================================================================

def renommer_fiche(identite, ancien, nouveau, chemin=None) -> int:
    """Une fiche VA renommee dans le referentiel : ses liens suivent.

    Rend le nombre de liens deplaces. N'ecrit rien s'il n'y a rien a faire
    (un fichier absent reste absent).

    A appeler APRES un renommage accepte par jailbreak.update_va, qui refuse
    tout nom deja occupe : le nouveau nom etait donc LIBRE dans le
    referentiel. Un lien qui le portait deja visait une fiche disparue ; le
    laisser tel quel, c'etait lui donner les comptes de la fiche renommee
    (et montrer le vrai proprietaire « aussi liee a »). Il est marque
    supprime — toujours visible, casse, avec sa raison.

    Les liens deja marques « supprimee » ne suivent pas : ils visaient la
    fiche d'avant, pas celle qu'on renomme.
    """
    ident = str(identite or "").strip().lower()
    k = _cle(ident, ancien)
    nouveau = _nom_fiche(nouveau)
    # Un changement de CASSE seule (« noum » -> « Noum ») se suit aussi :
    # la pastille doit afficher le nom tel qu'il est maintenant ecrit.
    if not ident or not k[1] or not nouveau or str(ancien or "").strip() == nouveau:
        return 0
    k_neuf = _cle(ident, nouveau)
    with _LOCK:
        d = lire(chemin)
        n = perimes = 0
        tous = [l for m in d["membres"] for l in m["fiches"]] + d["masquees"]
        if k_neuf != k:
            for l in tous:
                if not l.get("supprimee") and _cle(l["identite"], l["fiche"]) == k_neuf:
                    l["supprimee"], l["motif"] = _maintenant(), "reprise"
                    perimes += 1
        for l in tous:
            if not l.get("supprimee") and _cle(l["identite"], l["fiche"]) == k:
                l["fiche"] = nouveau
                n += 1
        if n or perimes:
            _ecrire(d, chemin)
        return n


def marquer_supprimee(identite, fiche, chemin=None) -> int:
    """Une fiche VA SUPPRIMEE du referentiel : ses liens et ses masquees
    sont marques, avec la date.

    Sans marque, un lien vers une fiche supprimee n'etait casse que tant
    qu'aucune fiche du meme nom n'existait : recreer « Jaurel X2 » pour un
    NOUVEAU VA le ressuscitait, et les comptes du nouveau etaient attribues
    a l'ancien sans une suggestion. Marque, il reste casse (« fiche
    supprimee le … ») et la fiche recreee est proposee comme une autre
    personne. Rend le nombre de liens marques ; n'ecrit rien s'il n'y en a
    aucun.
    """
    k = _cle(identite, fiche)
    if not k[0] or not k[1]:
        return 0
    with _LOCK:
        d = lire(chemin)
        n = 0
        for l in [l for m in d["membres"] for l in m["fiches"]] + d["masquees"]:
            if not l.get("supprimee") and _cle(l["identite"], l["fiche"]) == k:
                l["supprimee"] = _maintenant()
                l.pop("motif", None)
                n += 1
        if n:
            _ecrire(d, chemin)
        return n


def renommer_identite(ancien, nouveau, chemin=None) -> int:
    """Une identite renommee : les liens de ses fiches suivent. Rend leur
    nombre ; n'ecrit rien s'il n'y en a aucun."""
    a = str(ancien or "").strip().lower()
    b = str(nouveau or "").strip().lower()
    if not a or not b or a == b:
        return 0
    with _LOCK:
        d = lire(chemin)
        n = 0
        for m in d["membres"]:
            for l in m["fiches"]:
                if l["identite"] == a:
                    l["identite"] = b
                    n += 1
        for x in d["masquees"]:
            if x["identite"] == a:
                x["identite"] = b
                n += 1
        if n:
            _ecrire(d, chemin)
        return n


def liens_identite(nom, chemin=None) -> dict:
    """Ce que l'equipe sait d'une identite (pour la fiche d'archive).

    Les liens restent dans equipe.json quand une identite est archivee : ils
    s'affichent comme casses. Cette copie permet de les retrouver si
    l'identite revient."""
    nom = str(nom or "").strip().lower()
    d = lire(chemin)
    membres = [{"id": m["id"], "nom": m["nom"], "fiche": l["fiche"]}
               for m in d["membres"] for l in m["fiches"] if l["identite"] == nom]
    masquees = [x["fiche"] for x in d["masquees"] if x["identite"] == nom]
    return {"membres": membres, "masquees": masquees}


# ==============================================================================
# La vue de l'ecran
# ==============================================================================

def vue(fiches_par_identite: dict, comptes_par_identite: dict = None,
        perimetre=None, donnees: dict = None, chemin=None) -> dict:
    """Tout ce que l'onglet affiche, calcule en un seul endroit.

    fiches_par_identite : {identite: [{name, discord_username}]} pour TOUTES
        les identites du referentiel (jailbreak.list_vas_for_identity) — c'est
        ce qui dit si un lien est vivant.
    comptes_par_identite : {identite: [comptes]} — un compte appartient a la
        fiche dont le nom est dans son champ « va ».
    perimetre : les identites de « Comptes par identite » ; seules leurs
        fiches sont PROPOSEES. Les autres ne sont pas ecartees en silence :
        elles sont comptees (hors_perimetre). None = toutes.
    """
    d = donnees if donnees is not None else lire(chemin)
    comptes_par_identite = comptes_par_identite or {}
    perim = None if perimetre is None else {str(i).strip().lower() for i in perimetre}

    # --- Index des fiches vivantes ----------------------------------------
    index, ordre = {}, []
    idents = set()
    sans_nom = doublons = 0
    for ident_brut, fiches in (fiches_par_identite or {}).items():
        ident = str(ident_brut or "").strip().lower()
        if not ident:
            continue
        idents.add(ident)
        par_va = {}
        for a in comptes_par_identite.get(ident_brut, comptes_par_identite.get(ident)) or []:
            if isinstance(a, dict):
                v = str(a.get("va") or "").strip().lower()
                if v:
                    par_va[v] = par_va.get(v, 0) + 1
        for v in fiches or []:
            nom = str((v.get("name") if isinstance(v, dict) else v) or "").strip()
            if not nom:
                sans_nom += 1
                continue
            k = (ident, nom.lower())
            if k in index:
                doublons += 1
                continue
            index[k] = {
                "identite": ident, "fiche": nom,
                "discord": str((v.get("discord_username") if isinstance(v, dict) else "")
                               or "").strip().lstrip("@"),
                "comptes": par_va.get(nom.lower(), 0),
            }
            ordre.append(k)

    def _raison(k, l=None):
        """(code, parametre, texte) : le code et le parametre servent a
        l'ecran, qui compose la phrase en morceaux traduisibles (une phrase
        qui mele libelle et donnees dans un seul noeud de texte restait en
        francais dans l'interface anglaise) ; le texte sert aux journaux."""
        if l is not None and l.get("supprimee"):
            date = _date_fr(l["supprimee"])
            if l.get("motif") == "reprise":
                return ("reprise", date, f"fiche supprimée, nom repris le {date}")
            return ("supprimee", date, f"fiche supprimée le {date}")
        if k[0] not in idents:
            return ("identite", k[0], f"identité « {k[0]} » introuvable (renommée ou archivée ?)")
        return ("absente", k[0], f"fiche absente de {k[0]} (supprimée ou renommée ?)")

    def _casse(l, k, code_param_texte):
        code, param, texte = code_param_texte
        return {"identite": l["identite"], "fiche": l["fiche"], "ok": False, "comptes": 0,
                "code": code, "param": param, "raison": texte}

    # --- Membres ------------------------------------------------------------
    rang = {r.casefold(): i for i, r in enumerate(d["roles"])}
    lies = {}
    membres_out = []
    casses = 0
    # Les pseudos Discord de chaque membre : le sien, ses secondaires, ET
    # ceux des fiches qu'il porte. Sans ces derniers, un membre cree a la
    # main sans @Discord mais lie a une fiche @noum n'etait pas reconnu : la
    # fiche @noum suivante devenait une deuxieme personne.
    discords_membre = {}
    for m in d["membres"]:
        fiches_out, models = [], []
        n_comptes = n_casses = 0
        ds = [norm_discord(x) for x in [m["discord"]] + list(m.get("discords_autres") or [])]
        for l in m["fiches"]:
            k = _cle(l["identite"], l["fiche"])
            info = index.get(k)
            if l.get("supprimee"):
                # Marque a la suppression : casse meme si une fiche du meme
                # nom a ete recreee depuis (c'est une autre personne).
                fiches_out.append(_casse(l, k, _raison(k, l)))
                n_casses += 1
                continue
            if info is not None and k in lies:
                # Deux membres pour une meme fiche : impossible par le site,
                # possible par une retouche a la main. On le MONTRE.
                autre = next((x["nom"] for x in d["membres"] if x["id"] == lies[k]), "?")
                fiches_out.append(_casse(l, k, ("doublon", autre, f"aussi liée à {autre}")))
                n_casses += 1
                continue
            if info is None:
                fiches_out.append(_casse(l, k, _raison(k)))
                n_casses += 1
                continue
            lies[k] = m["id"]
            fiches_out.append({"identite": info["identite"], "fiche": info["fiche"],
                               "ok": True, "comptes": info["comptes"],
                               "discord": info["discord"]})
            ds.append(norm_discord(info["discord"]))
            n_comptes += info["comptes"]
            if info["identite"] not in models:
                models.append(info["identite"])
        discords_membre[m["id"]] = [x for x in dict.fromkeys(ds) if x]
        casses += n_casses
        mo = dict(m)
        mo.update({"fiches": fiches_out, "models": models, "n_comptes": n_comptes,
                   "n_casses": n_casses,
                   "discords_autres": list(m.get("discords_autres") or []),
                   "role_connu": (not m["role"]) or m["role"].casefold() in rang})
        membres_out.append(mo)
    membres_out.sort(key=lambda x: (not x["actif"],
                                    rang.get(x["role"].casefold(), len(rang)) if x["role"] else len(rang) + 1,
                                    x["nom"].casefold()))

    # --- Masquees -------------------------------------------------------------
    masq = set()
    masquees_out = []
    for x in d["masquees"]:
        k = _cle(x["identite"], x["fiche"])
        # Une masquee marquee « supprimee » visait la fiche d'avant : elle ne
        # cache pas une fiche recreee sous le meme nom.
        info = None if x.get("supprimee") else index.get(k)
        if not x.get("supprimee"):
            masq.add(k)
        code, param, texte = ("", "", "") if info else _raison(k, x)
        masquees_out.append({
            "identite": x["identite"],
            "fiche": info["fiche"] if info else x["fiche"],
            "ok": info is not None, "comptes": info["comptes"] if info else 0,
            "code": code, "param": param, "raison": texte,
            "liee": k in lies,
        })
    masquees_existantes = sum(1 for k in masq if k in index and k not in lies)

    # --- Suggestions ----------------------------------------------------------
    par_discord = {}
    for m in d["membres"]:
        for nd in discords_membre.get(m["id"], []):
            par_discord.setdefault(nd, []).append(m["id"])
    rp = role_propose(d)
    rp_canon = next((r for r in d["roles"] if r.casefold() == rp.casefold()), "") if rp else ""
    groupes, ordre_g = {}, []
    hors_perimetre = 0
    libres = []
    for k in ordre:
        if k in lies:
            continue
        info = index[k]
        libres.append({"identite": info["identite"], "fiche": info["fiche"],
                       "discord": info["discord"], "masquee": k in masq})
        if k in masq:
            continue
        if perim is not None and k[0] not in perim:
            hors_perimetre += 1
            continue
        nd = norm_discord(info["discord"])
        # LE SEUL REGROUPEMENT AUTOMATIQUE : le pseudo Discord. Sans pseudo,
        # une fiche = une suggestion, meme si une autre porte le meme nom
        # sous une autre identite (ce sont deux personnes).
        cle = ("d:" + nd) if nd else ("f:" + k[0] + "|" + k[1])
        if cle not in groupes:
            groupes[cle] = {"cle": cle, "nom": info["fiche"], "discord": info["discord"],
                            "role": rp_canon,
                            "fiches": [], "models": [], "n_comptes": 0,
                            "membres_meme_discord": list(par_discord.get(nd, [])) if nd else []}
            ordre_g.append(cle)
        g = groupes[cle]
        g["fiches"].append({"identite": info["identite"], "fiche": info["fiche"],
                            "comptes": info["comptes"]})
        g["n_comptes"] += info["comptes"]
        if info["identite"] not in g["models"]:
            g["models"].append(info["identite"])
    suggestions = [groupes[c] for c in ordre_g]

    roles_out = [{"nom": r, "n": sum(1 for m in d["membres"]
                                     if m["role"].casefold() == r.casefold())}
                 for r in d["roles"]]
    compteurs = {
        "fiches": len(index),
        "liees": len(lies),
        "suggerees": sum(len(s["fiches"]) for s in suggestions),
        "suggestions": len(suggestions),
        "masquees": len(d["masquees"]),
        "masquees_existantes": masquees_existantes,
        "hors_perimetre": hors_perimetre,
        "casses": casses,
        "membres": len(d["membres"]),
        "actifs": sum(1 for m in d["membres"] if m["actif"]),
        "roles": len(d["roles"]),
        "sans_nom": sans_nom,
        "doublons": doublons,
        # Rattachees d'office par « Tout ajouter » (un seul membre a ce
        # @Discord) / laissees (plusieurs : c'est au proprietaire de choisir).
        "a_rattacher": sum(1 for s in suggestions if len(s["membres_meme_discord"]) == 1),
        "a_laisser": sum(1 for s in suggestions if len(s["membres_meme_discord"]) > 1),
    }
    return {"roles": roles_out, "membres": membres_out, "suggestions": suggestions,
            "masquees": masquees_out, "libres": libres, "compteurs": compteurs,
            "role_propose": rp_canon,
            # Enregistre mais absent de la liste des roles (retouche a la
            # main) : les suggestions partiraient sans role, l'ecran le dit.
            "role_propose_inconnu": rp if (rp and not rp_canon) else ""}

def suggestion(v: dict, cle: str) -> dict:
    """La suggestion `cle` de la vue, ou un refus nomme si elle a disparu
    (quelqu'un l'a traitee dans un autre onglet entre-temps)."""
    for s in v.get("suggestions") or []:
        if s["cle"] == cle:
            return s
    raise ErreurEquipe("Cette suggestion n'existe plus : la liste a changé, "
                       "recharge l'onglet.")
