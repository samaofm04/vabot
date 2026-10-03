# -*- coding: utf-8 -*-
"""Les liens GetMySocial des VA du serveur FR (Va IG), un par VA et par model.

POURQUOI (proprietaire, 03/10/2026)
    « Pour le lien de tracking, pareil que pour Twitter, tu crées pour le VA
    tranquillement. » Chaque model a, dans l'equipe GetMySocial des VA, un
    lien de base « <Model> 1 » (getmysocial.com/<model>_bby) : une page aux
    boutons OF et/ou MYM. Le lien d'un VA en est la COPIE, dont chaque bouton
    pointe vers un lien de tracking MyPuls cree pour lui (« fais automatique
    depuis MyPuls », MYM comme OF), range dans le groupe de la model, nomme
    « Amelia VA 3 @pseudo ».

DECLENCHEMENT
    Sur demande seulement : le VA clique « Demander un lien », un manager
    « Générer le lien » (cogs/user.GenLinkButton). Un tracking link MyPuls ne
    s'efface pas : un humain valide chaque creation.

CE QUI N'EST JAMAIS FAIT EN SILENCE
    Un bouton dont le tracking n'a pas pu etre cree est RETIRE de la copie (les
    liens de base pointent vers un compte d'exemple), et la raison remonte au
    manager (`soucis`). Sans aucun tracking, ou si la copie garde les boutons
    du lien de base, aucun lien n'est donne au VA. Une creation sans
    plateforme reconnue est refusee avant de rien payer.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

_RACINE = Path(__file__).resolve().parent
ETAT = _RACINE / "data" / "liens_va_fr.json"

#: L'equipe GetMySocial des liens des VA du serveur FR. Proprietaire,
#: 03/10/2026 : « faut creer dans ce groupe, par categorie » -- VA IG
#: DISCORD, un groupe par model. GetMySocial ne copie un lien que DANS son
#: equipe (404 link_not_in_team, essaye le 03/10) : les liens de base
#: <model>_bby doivent y etre.
EQUIPE = "tm_6ac06401e06eabe3b9ef45f6"          # VA IG DISCORD
#: Par model : son nom, ses createurs MyPuls (OF : revenus_segments.py ;
#: MYM : KNOWN_MYM_IDS). Le lien de base et le groupe se trouvent dans
#: l'equipe (lien_de_base, groupe_de) : rien d'ecrit en dur qui deviendrait faux.
MODELS: Dict[str, Dict[str, Any]] = {
    "amelia": {"nom": "Amelia", "of": 3106, "mym": 769},
    "lola": {"nom": "Lola", "of": 3673, "mym": 1116},
    "julia": {"nom": "Julia", "of": 3109, "mym": 679},
    "sarah": {"nom": "Sarah", "of": None, "mym": 1469},
    "alicia": {"nom": "Alicia", "of": None, "mym": 2896},
    "emma": {"nom": "Emma", "of": None, "mym": 1733},
}
_CACHE_LIENS: Dict[str, Any] = {"t": 0.0, "liens": []}
#: Comptes SANS LIMITE : chaque « Demander un lien » cree un NOUVEAU lien,
#: tout de suite, sans manager. Proprietaire, 03/10/2026 : « pour moi Mario,
#: mets un truc sans limite, comme ca je peux check » -- marioofm, son compte
#: de test VA (role Amelia sur Va IG). Chaque essai est REEL : trackings MyPuls
#: (ils ne s'effacent pas) et lien GetMySocial, gardes dans « essais » du
#: registre pour le menage. Son compte principal 7🎰 (seven_ofm) aussi : il
#: teste depuis celui-ci et tombait sur « demande deja en attente » (03/10).
SANS_LIMITE = {479005370438778891, 402069419393679370}


#: Comptes dont le lien de CHAQUE model reste en service, roles ou pas :
#: aligner ne les coupe jamais. Proprietaire, 03/10/2026 : « nourdine229_08534,
#: mon VA manager : un lien pour chaque model », « les 6 tournent en meme
#: temps pour lui, sans les desactiver » ; puis « pour york_emerick12 aussi,
#: priscah0908_23400 et fahnih_37050 ».
TOUTES_MODELS = {1454580913190211730,    # nourdine229_08534
                 1390429527087251618,    # york_emerick12 (BOSS, sans ticket)
                 1525406324970618890,    # priscah0908_23400
                 1525508553081753621}    # fahnih_37050


def sans_limite(uid) -> bool:
    try:
        return int(uid) in SANS_LIMITE
    except (TypeError, ValueError):
        return False


def _liens_equipe(force: bool = False) -> List[Dict[str, Any]]:
    """Les liens de l'equipe, gardes 10 min : le quota GetMySocial est
    partage avec le reste du site."""
    import gms
    if force or time.time() - _CACHE_LIENS["t"] > 600:
        r = gms.list_links_team(EQUIPE)
        ls = r.get("links") if isinstance(r, dict) else r
        _CACHE_LIENS.update(t=time.time(), liens=list(ls or []))
    return _CACHE_LIENS["liens"]


def lien_de_base(model: str) -> str:
    """L'id du lien de base de la model dans l'equipe : adresse « <model>_bby »
    (ou qui commence ainsi), sinon nomme « <Model> 1 ». "" s'il n'y est pas."""
    nom = MODELS.get(model, {}).get("nom", model)
    for force in (False, True):
        for l in _liens_equipe(force):
            sc = str(l.get("shortcode") or "").lower()
            dn = str(l.get("display_name") or "").strip().lower()
            if sc == f"{model}_bby" or sc.startswith(f"{model}_bby") or dn == f"{nom.lower()} 1":
                return str(l.get("id") or "")
    return ""


def groupe_de(model: str) -> str:
    """Le groupe de la model dans l'equipe, cree s'il manque (liens_va)."""
    import liens_va
    return liens_va.groupe_manager(EQUIPE, MODELS.get(model, {}).get("nom", model))

#: Une creation a la fois. La createrice active de MyPuls est un etat du
#: SERVEUR MyPuls, attache au cookie partage : deux creations croisees (ou une
#: autre tache qui bascule entre-temps) poseraient un tracking chez la
#: mauvaise model -- et il ne s'efface pas.
_VERROU = threading.Lock()


def nom_tracking(nom: str) -> str:
    """Le nom du tracking MyPuls : lettres, chiffres, - et _, jamais d'espace.
    MYM refusait « Emma VA 2 @pseudo » (« Nom refusé : utilisez uniquement des
    lettres, des chiffres, un tiret (-) ou un tiret bas (_), sans espace ni
    accent », 03/10/2026) ; proprietaire : « mets des tirets bas, jamais
    d'espace ». « Emma VA 2 @pseudo » -> « Emma_VA_2_pseudo »."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]+", "_", t)).strip("_-")
    return t[:60] or "VA"


def plateforme(url: str) -> str:
    """« of », « mym », ou "" pour l'adresse d'un bouton."""
    u = str(url or "").lower()
    if "onlyfans.com/" in u:
        return "of"
    if "mym.fans/" in u or "mym.me/" in u:
        return "mym"
    return ""


def _etat() -> Dict[str, Any]:
    d = safe_json.load(ETAT, default={}) or {}
    return d if isinstance(d, dict) else {}


def lien_de(uid, model: str) -> Optional[Dict[str, Any]]:
    return (_etat().get("liens") or {}).get(f"{int(uid)}:{str(model).lower()}")


def _numero(model: str) -> int:
    """Le prochain numero de VA de cette model : « Amelia 1 » est le lien de
    base, les VA commencent a 2. Les essais du compte sans limite, les liens
    retires (/resetlien) et les tentatives ratees apres creation comptent
    aussi : leur nom « Amelia VA n » existe deja chez MyPuls."""
    d = _etat()
    pris = [int(e.get("numero") or 0) for k, e in (d.get("liens") or {}).items()
            if k.endswith(":" + model) and isinstance(e, dict)]
    for liste in ("essais", "echecs", "retires"):
        pris += [int(e.get("numero") or 0) for e in (d.get(liste) or [])
                 if isinstance(e, dict) and e.get("model") == model]
    return max([1] + pris) + 1


def model_du_nom(display_name: str) -> str:
    """« Amelia VA 3 @pseudo » -> « amelia » ; "" si ce n'est pas un nom de
    lien de VA FR."""
    m = re.match(r"^\s*(\S+) VA \d+(?:-\d+)? @", str(display_name or ""))
    if not m:
        return ""
    return next((k for k, c in MODELS.items() if c["nom"].lower() == m.group(1).lower()), "")


def liens_gms_de(pseudo: str, model: str = "", force: bool = True) -> List[Dict[str, Any]]:
    """Les liens FR d'un VA retrouves A LEUR NOM dans l'equipe (« Amelia VA 3
    @pseudo ») : filet quand le registre ne les a pas. Le 03/10/2026,
    /resetlien n'y a pas trouve le lien de Mario cree une demi-heure plus tot
    (cause inconnue, le registre n'est lisible que sur le VPS)."""
    pseudo = str(pseudo or "").strip().lower()
    if not pseudo:
        return []
    out = []
    for l in _liens_equipe(force):
        dn = str(l.get("display_name") or "").strip()
        if not dn.lower().endswith(f" @{pseudo}"):
            continue
        mod = model_du_nom(dn)
        if mod and (not model or mod == model):
            out.append(l)
    return out


def _reparer(uid, model: str, entree: Dict[str, Any]):
    """Complete SUR PLACE le lien d'un VA dont un bouton n'a pas son tracking
    (MYM refuse ou non relu a la creation) : meme adresse, rien a supprimer
    puis refaire. Proprietaire, 03/10/2026 : « un truc fixe pour reparer sans
    avoir a supprimer et refaire des liens a chaque fois ».

    Le tracking manquant est d'abord cherche dans MyPuls A SON NOM (cree mais
    jamais relu : pas de doublon), cree sinon ; les boutons sont reposes
    depuis le lien de base (un bouton retire revient). Rend (entree, change).
    Rien a faire : aucun appel reseau si l'entree connait ses plateformes."""
    import gms
    cfg = MODELS.get(model) or {}
    urls = dict(entree.get("trackings") or {})
    gabarit, base = lien_de_base(model), None
    attendues = entree.get("plateformes")
    if attendues is None:
        if not gabarit:
            return entree, False
        base = lire_lien(gabarit)
        attendues = sorted({plateforme(b.get("url")) for b in base.get("buttons") or []} - {""})
    manquantes = [p for p in attendues if cfg.get(p) and not urls.get(p)]
    if (not manquantes and entree.get("boutons_a_jour") is not False) or not entree.get("link_id"):
        if entree.get("plateformes") is None:
            # notees une fois : les clics suivants ne relisent plus le lien de base
            entree = {**entree, "plateformes": attendues}
            d = _etat()
            d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
            safe_json.write(ETAT, d, indent=1)
        return entree, False
    nomt = nom_tracking(entree.get("display_name") or "")
    soucis, nouveaux = [], {}
    for p in manquantes:
        cid = int(cfg[p])
        try:
            url, _ = _relire_api(nomt, cid)
        except Exception as e:                               # noqa: BLE001
            url = ""
            print(f"[liens_fr] reparation : relecture API impossible ({e})", flush=True)
        if not url:
            t = creer_tracking(nomt, cid)
            url = t.get("url") if t.get("ok") else ""
            if not url:
                soucis.append(f"{p.upper()} : {t.get('erreur')} — bouton toujours absent")
        if url:
            nouveaux[p] = url
    urls.update(nouveaux)
    etaient_ok = boutons_ok = entree.get("boutons_a_jour")
    if nouveaux or boutons_ok is False:
        try:
            base = base or lire_lien(gabarit)
            copie = lire_lien(entree["link_id"])
            # la version de la COPIE quand elle a encore le bouton (ses images),
            # celle du lien de base pour un bouton qui avait ete retire
            libelle = lambda b: str(b.get("label") or b.get("title") or "")
            dans_copie = {libelle(b): b for b in copie.get("buttons") or []}
            boutons = [dans_copie.get(libelle(b), b) for b in base.get("buttons") or []]
            r = gms._call_tool("update_link", {"link_id": entree["link_id"], "team_id": EQUIPE,
                                               "buttons": boutons_remplaces(boutons, urls)})
            boutons_ok = bool(r.get("ok"))
            if not boutons_ok:
                soucis.append(f"boutons non mis à jour ({r.get('error')}) — réessayé au prochain clic")
        except Exception as e:                               # noqa: BLE001
            boutons_ok = False
            soucis.append(f"boutons non mis à jour ({type(e).__name__}: {e}) — réessayé au prochain clic")
    entree = {**entree, "trackings": urls, "plateformes": attendues, "soucis": soucis,
              "boutons_a_jour": boutons_ok, "repare": int(time.time())}
    d = _etat()
    d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(ETAT, d, indent=1):
        soucis.append("registre data/liens_va_fr.json non écrit")
    print(f"[liens_fr] reparation de {entree.get('display_name')} : ajout {sorted(nouveaux)}, "
          f"boutons {'ok' if boutons_ok else 'NON'}", flush=True)
    # change = un bouton de plus, ou des boutons enfin reposes -- pas un essai rate
    return entree, bool(nouveaux) or (etaient_ok is False and boutons_ok is True)


# ─── Le numero du VA : le meme dans le nom de son salon et dans son lien ──
#: Proprietaire, 03/10/2026 : « le numero du VA a cote [du salon] », puis
#: « faut que ce soit synchro avec le lien » -- seven_ofm est « Amelia VA 3 »
#: dans GetMySocial, son salon doit dire 3. UN numero par (model, VA), donne
#: une fois et garde : dans l'ordre des salons de la categorie, ou celui de
#: son lien s'il en a deja un. Jamais redonne a un autre (un nom de tracking
#: MyPuls deja pris resterait ambigu). Fichier a part, son propre verrou :
#: generer() tient _VERROU pendant tout son reseau.
NUMEROS = _RACINE / "data" / "numeros_va_fr.json"
_VERROU_NUM = threading.Lock()
#: Numeros donnes a la main par le proprietaire : {model: {uid: numero}}.
#: « prisca amelia 1 » (03/10/2026) : Priscah (priscah0908_23400) est
#: Amelia VA 1 -- celui qui le portait (marioofm, son compte de test, sans
#: lien vivant) en recoit un autre, libre. Re-applique a chaque appel : un
#: fichier numeros_va_fr.json remis a zero n'efface pas la volonte.
NUMEROS_IMPOSES: Dict[str, Dict[int, int]] = {
    "amelia": {1525406324970618890: 1},
}


def _imposer(model: str, numeros: Dict[str, Any]) -> bool:
    """Applique NUMEROS_IMPOSES a la table de cette model ; True si elle a
    change. Celui qui occupait un numero impose prend le plus petit libre."""
    voulus = NUMEROS_IMPOSES.get(model) or {}
    if not voulus:
        return False
    par = numeros.setdefault(model, {})
    change = False
    for uid, n in voulus.items():
        if par.get(str(uid)) == n:
            continue
        for autre, v in list(par.items()):
            if int(v) == n and autre != str(uid):
                pris = _pris(model, numeros) | set(voulus.values())
                par[autre] = next(i for i in range(1, 100000) if i not in pris)
                print(f"[liens_fr] {model} {n} impose a {uid} : {autre} passe a {par[autre]}", flush=True)
        par[str(uid)] = n
        change = True
    return change


def _pris(model: str, numeros: Dict[str, Any]) -> set:
    """Les numeros deja portes dans cette model : VA numerotes, liens,
    essais, echecs, retraits."""
    pris = {int(v) for v in (numeros.get(model) or {}).values() if str(v).isdigit()}
    d = _etat()
    pris |= {int(e.get("numero") or 0) for k, e in (d.get("liens") or {}).items()
             if k.endswith(":" + model) and isinstance(e, dict)}
    for liste in ("essais", "echecs", "retires"):
        pris |= {int(e.get("numero") or 0) for e in (d.get(liste) or [])
                 if isinstance(e, dict) and e.get("model") == model}
    return pris - {0}


def numero_va(uid, model: str, creer: bool = True) -> int:
    """Le numero du VA dans cette model (0 s'il n'en a pas et creer=False)."""
    model = str(model or "").strip().lower()
    with _VERROU_NUM:
        numeros = safe_json.load(NUMEROS, default={}) or {}
        if _imposer(model, numeros) and not safe_json.write(NUMEROS, numeros, indent=1):
            print(f"[liens_fr] numeros imposes de {model} NON enregistres", flush=True)
        par = numeros.setdefault(model, {})
        if str(int(uid)) in par:
            return int(par[str(int(uid))])
        if not creer:
            return 0
        pris = _pris(model, numeros) | set((NUMEROS_IMPOSES.get(model) or {}).values())
        n = int((lien_de(uid, model) or {}).get("numero") or 0)
        if not n or n in {int(v) for v in par.values()}:
            n = next(i for i in range(1, 100000) if i not in pris)
        par[str(int(uid))] = n
        if not safe_json.write(NUMEROS, numeros, indent=1):
            print(f"[liens_fr] numero {n} de {uid} ({model}) NON enregistre", flush=True)
        return n


def retirer(uid) -> List[Dict[str, Any]]:
    """/resetlien (serveur FR) : sort les liens de ce VA du registre « liens »
    -- sa prochaine demande en refera un -- et les garde dans « retires » :
    leurs trackings MyPuls existent toujours, leur numero reste pris."""
    with _VERROU:
        d = _etat()
        liens = d.get("liens") or {}
        sortis = [{**liens.pop(k), "retire": int(time.time())}
                  for k in [k for k, e in liens.items()
                            if k.startswith(f"{int(uid)}:") and isinstance(e, dict)]]
        if sortis:
            d.setdefault("retires", []).extend(sortis)
            if not safe_json.write(ETAT, d, indent=1):
                raise RuntimeError("registre data/liens_va_fr.json non écrit")
        return sortis


# ─── Le lien suit le role ─────────────────────────────────────────────────
_RE_NOM_VA = re.compile(r"^\s*\S+ VA \d+(?:-\d+)? @(\S+)\s*$")


def _actif_gms(l: Dict[str, Any]) -> Optional[bool]:
    """Le lien est-il en service chez GetMySocial (`status` « active ») ?
    None si la liste ne le dit pas."""
    s = str(l.get("status") or "").strip().lower()
    return (s == "active") if s else None


def aligner(membres, force: bool = False) -> List[Dict[str, Any]]:
    """Le lien d'un VA pour une model suit le ROLE de cette model : coupe dans
    GetMySocial (disable_link) quand le VA ne l'a plus, remis en service
    quand il le retrouve. Proprietaire, 03/10/2026 : « ok vas-y pour les
    disable, et pour MyPuls pas besoin de supprimer » -- RIEN n'est supprime :
    l'adresse est deja dans les stories du VA, ses clics restent, et un role
    retire par erreur se repare en le redonnant.

    `membres` : [(uid, pseudo Discord, [models de ses roles])], les SEULS VA
    traites : un VA que le bot ne voit pas garde ses liens tels quels. Les
    liens sont lus dans l'equipe (rattaches par le registre, sinon A LEUR
    NOM « Amelia VA 3 @pseudo ») : le registre du VPS a deja perdu une
    entree, et les essais des comptes sans limite n'y sont pas.

    Ne remet en service QUE ce que cette fonction a coupe (« coupes_role »
    du registre) : un lien coupe a la main dans GetMySocial le reste.
    Rend les bascules tentees : [{uid, model, nom, actif, ok, erreur}]."""
    import gms
    par_uid, par_pseudo = {}, {}
    for uid, pseudo, models in membres or []:
        try:
            u = str(int(uid))
        except (TypeError, ValueError):
            continue
        par_uid[u] = ({str(m).strip().lower() for m in models or []}
                      if int(u) not in TOUTES_MODELS else set(MODELS))
        if pseudo:
            par_pseudo[str(pseudo).strip().lower()] = u
    if not par_uid:
        return []
    faits = []
    with _VERROU:
        d = _etat()
        liens = d.get("liens") or {}
        par_lien = {str(e.get("link_id")): k.split(":", 1)[0] for k, e in liens.items()
                    if isinstance(e, dict) and e.get("link_id")}
        coupes = d.get("coupes_role") if isinstance(d.get("coupes_role"), dict) else {}
        for l in _liens_equipe(force):
            dn, lid = str(l.get("display_name") or ""), str(l.get("id") or "")
            model, m = model_du_nom(dn), _RE_NOM_VA.match(dn)
            if not model or not lid:
                continue
            uid = par_lien.get(lid) or (par_pseudo.get(m.group(1).lower()) if m else None)
            if uid not in par_uid:
                continue
            voulu, actif = model in par_uid[uid], _actif_gms(l)
            if actif is None:
                print(f"[liens_fr] {dn} : etat inconnu chez GetMySocial (status "
                      f"{l.get('status')!r}), laisse tel quel", flush=True)
                continue
            if actif == voulu or (voulu and lid not in coupes):
                continue
            try:
                r = gms.enable_link(lid) if voulu else gms.disable_link(lid)
            except Exception as e:                           # noqa: BLE001
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            ok = bool(r.get("ok"))
            if ok:
                # la liste est gardee 10 min : sans ca, chaque passage
                # refaisait la meme bascule jusqu'a son rafraichissement
                l["status"] = "active" if voulu else "disabled"
                if voulu:
                    coupes.pop(lid, None)
                else:
                    coupes[lid] = {"nom": dn, "uid": uid, "model": model, "quand": int(time.time())}
                for k, e in liens.items():
                    if isinstance(e, dict) and str(e.get("link_id")) == lid:
                        e["actif"] = voulu
            faits.append({"uid": uid, "model": model, "nom": dn, "actif": voulu, "ok": ok,
                          "erreur": "" if ok else str(r.get("error") or "refus GetMySocial")[:160]})
            print(f"[liens_fr] {dn} {'remis en service' if voulu else 'coupe'} "
                  f"(role {model} {'rendu' if voulu else 'retire'}) : "
                  f"{'ok' if ok else 'ECHEC ' + faits[-1]['erreur']}", flush=True)
        if any(f["ok"] for f in faits):
            d["coupes_role"] = coupes
            ETAT.parent.mkdir(parents=True, exist_ok=True)
            if not safe_json.write(ETAT, d, indent=1):
                print("[liens_fr] registre data/liens_va_fr.json non ecrit apres bascule", flush=True)
    return faits


# ─── GetMySocial ──────────────────────────────────────────────────────────
def _objet(res: Dict[str, Any]) -> Dict[str, Any]:
    """L'objet lien d'une reponse MCP (dict, ou texte JSON / repr)."""
    d = res.get("data") if isinstance(res, dict) else None
    if isinstance(d, str):
        for lire in (json.loads, __import__("ast").literal_eval):
            try:
                d = lire(d)
                break
            except Exception:                                # noqa: BLE001
                continue
    if isinstance(d, dict) and isinstance(d.get("data"), dict) and "buttons" not in d:
        d = d["data"]
    return d if isinstance(d, dict) else {}


def lire_lien(link_id: str) -> Dict[str, Any]:
    import gms
    res = gms._call_tool("get_link", {"link_id": link_id, "team_id": EQUIPE})
    if not res.get("ok"):
        raise RuntimeError(f"lien {link_id} illisible : {res.get('error')}")
    return _objet(res)


def _mots_doux(model: str, essai: int) -> str:
    """Une adresse courte mignonne, comme les liens Twitter (emycute, emylovee)."""
    try:
        import liens_va
        return liens_va.mots_doux(model, essai)
    except Exception:                                        # noqa: BLE001
        return f"{model}{essai + 2}"


def boutons_remplaces(boutons: List[Dict[str, Any]], urls: Dict[str, str]) -> List[Dict[str, Any]]:
    """Les boutons tels quels (images, effets, couleurs : un update_link
    remplace TOUT le tableau), seule l'adresse des boutons OF / MYM change.

    Un bouton OF / MYM SANS tracking est RETIRE : les six liens de base
    pointent vers un compte d'exemple (Lashwana, constate le 03/10/2026). Le
    premier lien de Mario a garde le bouton MYM de Lashwana (MyPuls refusait
    le tracking MYM) : les fans d'Amelia seraient partis chez une autre."""
    out = []
    for b in boutons or []:
        b2 = copy.deepcopy(b)
        p = plateforme(b2.get("url"))
        if p:
            if not urls.get(p):
                continue
            b2["url"] = urls[p]
        out.append(b2)
    return out


# ─── MyPuls ──────────────────────────────────────────────────────────────
def creer_tracking(nom: str, creator_id: int) -> Dict[str, Any]:
    """Un tracking link MyPuls pour cette createrice (OF ou MYM). Rend
    {ok, url, erreur}. La relecture passe par l'API (toutes plateformes) :
    la page ne laisse lire que les adresses OnlyFans."""
    import liens_va
    r = liens_va.creer_tracking(nom, creator_id)
    if r.get("ok") and r.get("url"):
        return _verifie_createrice(r, creator_id)
    if r.get("refuse"):
        return r                        # refuse avant creation : rien n'existe
    # Cree mais pas relu dans la page : l'API, TOUTES ses pages (au-dela des
    # 500 premiers trackings, le plus recent n'est pas dans la premiere), et
    # l'adresse quel que soit le nom de son champ.
    vu = None
    try:
        for _ in range(3):
            url, vu = _relire_api(nom, creator_id)
            if url:
                return {"ok": True, "url": url, "code": (vu or {}).get("code"), "erreur": ""}
            time.sleep(3)
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "erreur": f"créé, relecture MyPuls impossible : {type(e).__name__}: {e}"}
    # Le diagnostic, pour corriger sans acces au serveur : ce que MyPuls a
    # repondu a la creation, et ce que l'API en dit.
    diag = (f"réponse : {json.dumps(r.get('reponse'), ensure_ascii=False)[:200]}" if r.get("reponse")
            else f"{r.get('erreur')}")
    diag += (f" · API : {json.dumps(vu, ensure_ascii=False)[:250]}" if vu
             else " · absent de l'API")
    return {"ok": False, "erreur": f"créé, mais adresse introuvable ({diag}) — à vérifier dans MyPuls"}


def _relire_api(nom: str, creator_id: int):
    """(adresse, ligne brute) du tracking `nom` de cette createrice dans l'API
    MyPuls, page apres page ; ("", None) s'il n'y est pas."""
    import mypuls
    for page in range(1, 6):
        res = mypuls.api_get("tracking-links", {"per_page": 500, "page": page})
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error"))[:150])
        d = res.get("data")
        items = d if isinstance(d, list) else None
        if items is None and isinstance(d, dict):
            inner = d.get("data")
            items = inner.get("data") if isinstance(inner, dict) else inner
        items = [it for it in (items or []) if isinstance(it, dict)]
        for it in items:
            if str(it.get("creator_id")) == str(creator_id) and str(it.get("name") or "").strip() == nom:
                import liens_va
                return (str(it.get("url") or "") or liens_va._adresse_dans(it)), it
        if len(items) < 500:
            break
    return "", None


def _verifie_createrice(r: Dict[str, Any], creator_id: int) -> Dict[str, Any]:
    """Le tracking est-il bien chez CETTE createrice ? La bascule MyPuls est
    partagee avec d'autres taches (push, file OF) : une bascule entre la
    notre et la creation le poserait ailleurs. Introuvable dans l'API (delai) :
    on le garde, sans pouvoir le dire."""
    try:
        import mypuls
        for l in mypuls.api_tracking_links(force=True) or []:
            if l.get("url") == r.get("url"):
                if str(l.get("creator_id")) != str(creator_id):
                    return {"ok": False, "url": r.get("url"),
                            "erreur": f"créé chez la créatrice {l.get('creator_id')} au lieu de "
                                      f"{creator_id} ({r.get('url')}) — à corriger dans MyPuls"}
                break
    except Exception as e:                                   # noqa: BLE001
        print(f"[liens_fr] verification de la createrice impossible : {e}", flush=True)
    return r


# ─── Le parcours ─────────────────────────────────────────────────────────
def generer(uid, pseudo: str, model: str, par: Any = None) -> Dict[str, Any]:
    """Le lien de ce VA pour cette model. Rend {ok, deja, public_url,
    display_name, soucis, erreur}. Idempotent : un lien deja fait est rendu
    tel quel, sans rien recreer -- sauf pour un compte SANS_LIMITE."""
    import gms
    model = str(model or "").strip().lower()
    cfg = MODELS.get(model)
    if not cfg:
        return {"ok": False, "erreur": f"« {model} » n'est pas une model FR"}
    with _VERROU:
        deja = lien_de(uid, model)
        if deja and deja.get("public_url"):
            # un bouton sans tracking : repare sur place, meme adresse ; un
            # compte sans limite n'a un NOUVEAU lien que si rien n'etait a reparer
            try:
                deja, change = _reparer(uid, model, deja)
            except Exception as e:                           # noqa: BLE001
                deja, change = {**deja, "soucis": [f"réparation impossible : {type(e).__name__}: {e}"]}, False
            if change or not sans_limite(uid):
                return {"ok": True, "deja": True, "vient_d_etre_repare": change, **deja}
        if not sans_limite(uid):
            # absent du registre mais present dans GetMySocial a son nom : on le
            # reprend (et le registre est repare) au lieu d'un doublon -- avec
            # des trackings MyPuls en plus, qui ne s'effacent pas
            trouve = next(iter(liens_gms_de(pseudo, model, force=False)), None)
            if trouve and trouve.get("shortcode"):
                entree = {"pseudo": pseudo, "model": model, "link_id": str(trouve.get("id") or ""),
                          "shortcode": trouve["shortcode"], "display_name": trouve.get("display_name"),
                          "public_url": f"{gms.PUBLIC_LINK_DOMAIN}/{trouve['shortcode']}",
                          "numero": int((re.search(r" VA (\d+)(?:-\d+)? @", str(trouve.get("display_name"))) or [0, 0])[1]),
                          "repris": "trouvé à son nom dans GetMySocial, absent du registre",
                          "par": str(par or ""), "quand": int(time.time())}
                d = _etat()
                d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
                ETAT.parent.mkdir(parents=True, exist_ok=True)
                safe_json.write(ETAT, d, indent=1)
                print(f"[liens_fr] {entree['display_name']} repris de GetMySocial (absent du registre)", flush=True)
                # repris tel quel, il pouvait garder les boutons du lien de base :
                # « Amelia VA 1 @priscah0908_23400 » pointait chez Lashwana (03/10)
                try:
                    entree, change = _reparer(uid, model, entree)
                except Exception as e:                       # noqa: BLE001
                    entree, change = {**entree, "soucis": [f"réparation impossible : {type(e).__name__}: {e}"]}, False
                return {"ok": True, "deja": True, "vient_d_etre_repare": change, **entree}
        gabarit = lien_de_base(model)
        if not gabarit:
            return {"ok": False, "erreur": f"pas de lien de base « {model}_bby » ({cfg['nom']} 1) "
                                           "dans l'équipe GetMySocial VA IG DISCORD"}
        base = lire_lien(gabarit)
        plates = sorted({plateforme(b.get("url")) for b in base.get("buttons") or []} - {""})
        if not plates:
            return {"ok": False, "erreur": f"le lien de base de {cfg['nom']} n'a aucun bouton OF ni MYM"}
        n = numero_va(uid, model)
        nom = f"{cfg['nom']} VA {n} @{pseudo}"[:60]
        noms_pris = {str(e.get("display_name")) for e in
                     list((_etat().get("liens") or {}).values()) + _etat().get("essais", [])
                     + _etat().get("echecs", []) + _etat().get("retires", []) if isinstance(e, dict)}
        if sans_limite(uid):
            # un lien de plus pour le meme VA : son numero, et un rang (« 3-2 »)
            k = 2
            while nom in noms_pris:
                nom = f"{cfg['nom']} VA {n}-{k} @{pseudo}"[:60]
                k += 1
        # deja essaye sous ce nom (un echec) : ses trackings existent peut-etre
        reessai = nom in noms_pris
        # douteux : trackings demandes a MyPuls sans confirmation (MYM non
        # relu, poste chez une autre createrice) -- peut-etre crees quand meme
        urls, douteux, soucis, link_id = {}, {}, [], ""

        def _echec(erreur: str) -> Dict[str, Any]:
            """Rate APRES une creation definitive (tracking MyPuls, copie
            GetMySocial) : la tentative est notee (son numero reste pris) et
            ses adresses sont rendues -- pas un « lien non cree » sans rien,
            suivi au clic d'apres de nouveaux trackings au meme nom."""
            if urls or douteux or link_id:
                d = _etat()
                d.setdefault("echecs", []).append({
                    "uid": str(uid), "pseudo": pseudo, "model": model, "numero": n,
                    "display_name": nom, "trackings": dict(urls), "douteux": dict(douteux),
                    "link_id": link_id, "erreur": erreur, "quand": int(time.time())})
                ETAT.parent.mkdir(parents=True, exist_ok=True)
                if not safe_json.write(ETAT, d, indent=1):
                    soucis.append(f"registre data/liens_va_fr.json non écrit : le numéro {n} "
                                  f"n'est pas réservé, un nouveau clic recréera « {nom} »")
            out = {"ok": False, "erreur": erreur, "soucis": list(soucis), "trackings": dict(urls)}
            if link_id:
                out["soucis"].append(f"copie GetMySocial {link_id} déjà créée, avec les boutons "
                                     "du lien de base : à supprimer dans GetMySocial")
            return out

        try:
            for p in plates:
                cid = cfg.get(p)
                if not cid:
                    soucis.append(f"{p.upper()} : aucune créatrice MyPuls pour {cfg['nom']} — bouton retiré")
                    continue
                douteux[p] = "demandé"
                t = {}
                if reessai:
                    # le tracking d'un essai rate au meme nom : repris, pas recree
                    try:
                        u, _ = _relire_api(nom_tracking(nom), int(cid))
                        t = {"ok": True, "url": u} if u else {}
                    except Exception as e:                   # noqa: BLE001
                        print(f"[liens_fr] relecture avant reessai impossible : {e}", flush=True)
                if not t:
                    t = creer_tracking(nom_tracking(nom), int(cid))
                if t.get("ok"):
                    urls[p] = t["url"]
                    douteux.pop(p, None)
                else:
                    douteux[p] = t.get("url") or t.get("erreur") or "?"
                    soucis.append(f"{p.upper()} : {t.get('erreur')} — bouton retiré")
            if not urls:
                # chaque bouton du lien partirait chez le compte d'exemple
                return _echec("aucun tracking MyPuls créé : lien non fabriqué")

            lien, sc = None, ""
            for essai in range(12):
                # a partir du numero du VA : sinon le 13e VA d'une model epuisait
                # les douze essais sur des adresses deja prises
                sc = _mots_doux(model, max(0, n - 2) + essai)
                r = gms.duplicate_link(gabarit, sc, nom, "", EQUIPE)
                if r.get("ok"):
                    lien = r.get("link") or {}
                    break
                if "shortcode" not in str(r.get("error") or "").lower():
                    return _echec(f"GetMySocial : {r.get('error')}")
            if not lien or not lien.get("id"):
                return _echec("GetMySocial : aucune adresse libre")
            link_id = str(lien["id"])

            # Les boutons : relus sur la COPIE (ses images sont les siennes), seule
            # l'adresse OF / MYM change, et le lien rejoint le groupe de la model.
            # La copie existe deja : un refus ici (quota, 429) devient un souci,
            # comme un update_link refuse, et le lien est enregistre quand meme.
            maj = {"link_id": link_id, "team_id": EQUIPE, "display_name": nom}
            try:
                boutons = lire_lien(link_id).get("buttons") or []
            except Exception as e:                           # noqa: BLE001
                # ceux du lien de base, lus plus haut : jamais la copie telle
                # quelle, dont les boutons vont chez le compte d'exemple
                boutons = base.get("buttons") or []
                soucis.append(f"copie illisible ({e}) : boutons repris du lien de base")
            maj["buttons"] = boutons_remplaces(boutons, urls)
            try:
                groupe = groupe_de(model)
            except Exception as e:                           # noqa: BLE001
                groupe = ""
                print(f"[liens_fr] groupe de {model} : {type(e).__name__}: {e}", flush=True)
            if groupe:
                maj["group_id"] = groupe
            else:
                soucis.append(f"groupe « {cfg['nom']} » introuvable et non créé : lien hors groupe")
            r = gms._call_tool("update_link", maj)
            if not r.get("ok"):
                # la copie garde les boutons du lien de base (compte d'exemple) :
                # la donner au VA enverrait ses fans chez une autre
                return _echec(f"boutons non mis à jour ({r.get('error')})")
        except Exception as e:                               # noqa: BLE001
            return _echec(f"interrompu : {type(e).__name__}: {e}")
        public = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
        entree = {"pseudo": pseudo, "model": model, "numero": n, "link_id": link_id,
                  "shortcode": sc, "public_url": public, "display_name": nom,
                  "trackings": urls, "soucis": soucis, "par": str(par or ""),
                  "plateformes": plates, "boutons_a_jour": True,
                  "quand": int(time.time())}
        d = _etat()
        d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
        if sans_limite(uid):
            d.setdefault("essais", []).append(entree)
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(ETAT, d, indent=1):
            soucis.append("registre data/liens_va_fr.json non écrit : un 2e clic recréerait")
        print(f"[liens_fr] {nom} -> {public} (trackings {sorted(urls)}, soucis {len(soucis)})", flush=True)
        return {"ok": True, "deja": False, **entree}
