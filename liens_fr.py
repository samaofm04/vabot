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
    Un bouton dont le tracking n'a pas pu etre cree garde l'adresse du lien de
    base, et la raison remonte au manager (`soucis`). Une creation sans
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
    base, les VA commencent a 2."""
    pris = [int(e.get("numero") or 0) for k, e in (_etat().get("liens") or {}).items()
            if k.endswith(":" + model) and isinstance(e, dict)]
    return max([1] + pris) + 1


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
    remplace TOUT le tableau), seule l'adresse des boutons OF / MYM change."""
    out = []
    for b in boutons or []:
        b2 = copy.deepcopy(b)
        p = plateforme(b2.get("url"))
        if p and urls.get(p):
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
    # Cree mais pas relu dans la page (MYM : son adresse n'est pas une adresse
    # OnlyFans) : l'API publique liste toutes les plateformes.
    try:
        import mypuls
        for _ in range(3):
            for l in mypuls.api_tracking_links(force=True) or []:
                if str(l.get("creator_id")) == str(creator_id) and l.get("nom") == nom and l.get("url"):
                    return {"ok": True, "url": l["url"], "code": l.get("code"), "erreur": ""}
            time.sleep(3)
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "erreur": f"relecture MyPuls : {type(e).__name__}: {e}"}
    return {"ok": False, "erreur": r.get("erreur") or "créé ? introuvable à la relecture — à vérifier dans MyPuls"}


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
    tel quel, sans rien recreer."""
    import gms
    model = str(model or "").strip().lower()
    cfg = MODELS.get(model)
    if not cfg:
        return {"ok": False, "erreur": f"« {model} » n'est pas une model FR"}
    with _VERROU:
        deja = lien_de(uid, model)
        if deja and deja.get("public_url"):
            return {"ok": True, "deja": True, **deja}
        gabarit = lien_de_base(model)
        if not gabarit:
            return {"ok": False, "erreur": f"pas de lien de base « {model}_bby » ({cfg['nom']} 1) "
                                           "dans l'équipe GetMySocial VA IG DISCORD"}
        base = lire_lien(gabarit)
        plates = sorted({plateforme(b.get("url")) for b in base.get("buttons") or []} - {""})
        if not plates:
            return {"ok": False, "erreur": f"le lien de base de {cfg['nom']} n'a aucun bouton OF ni MYM"}
        n = _numero(model)
        nom = f"{cfg['nom']} VA {n} @{pseudo}"[:60]

        urls, soucis = {}, []
        for p in plates:
            cid = cfg.get(p)
            if not cid:
                soucis.append(f"{p.upper()} : aucune créatrice MyPuls pour {cfg['nom']} — lien de base gardé")
                continue
            t = creer_tracking(nom, int(cid))
            if t.get("ok"):
                urls[p] = t["url"]
            else:
                soucis.append(f"{p.upper()} : {t.get('erreur')} — lien de base gardé")

        lien, sc = None, ""
        for essai in range(12):
            # a partir du numero du VA : sinon le 13e VA d'une model epuisait
            # les douze essais sur des adresses deja prises
            sc = _mots_doux(model, (n - 2) + essai)
            r = gms.duplicate_link(gabarit, sc, nom, "", EQUIPE)
            if r.get("ok"):
                lien = r.get("link") or {}
                break
            if "shortcode" not in str(r.get("error") or "").lower():
                return {"ok": False, "erreur": f"GetMySocial : {r.get('error')}", "soucis": soucis,
                        "trackings": urls}
        if not lien or not lien.get("id"):
            return {"ok": False, "erreur": "GetMySocial : aucune adresse libre", "soucis": soucis,
                    "trackings": urls}
        link_id = str(lien["id"])

        # Les boutons : relus sur la COPIE (ses images sont les siennes), seule
        # l'adresse OF / MYM change, et le lien rejoint le groupe de la model.
        copie = lire_lien(link_id)
        maj = {"link_id": link_id, "team_id": EQUIPE, "display_name": nom,
               "buttons": boutons_remplaces(copie.get("buttons") or [], urls)}
        groupe = groupe_de(model)
        if groupe:
            maj["group_id"] = groupe
        else:
            soucis.append(f"groupe « {cfg['nom']} » introuvable et non créé : lien hors groupe")
        r = gms._call_tool("update_link", maj)
        if not r.get("ok"):
            soucis.append(f"boutons non mis à jour ({r.get('error')}) : la copie pointe "
                          "encore vers le lien de base")
        public = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
        entree = {"pseudo": pseudo, "model": model, "numero": n, "link_id": link_id,
                  "shortcode": sc, "public_url": public, "display_name": nom,
                  "trackings": urls, "soucis": soucis, "par": str(par or ""),
                  "quand": int(time.time())}
        d = _etat()
        d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(ETAT, d, indent=1):
            soucis.append("registre data/liens_va_fr.json non écrit : un 2e clic recréerait")
        print(f"[liens_fr] {nom} -> {public} (trackings {sorted(urls)}, soucis {len(soucis)})", flush=True)
        return {"ok": True, "deja": False, **entree}
