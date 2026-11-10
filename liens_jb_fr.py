# -*- coding: utf-8 -*-
"""Les liens « JB FR » : quatre liens GetMySocial neufs par VA de You FR.

POURQUOI (propriétaire, 10/11/2026, devant l'équipe GetMySocial « VA JB FR »
qu'il venait de créer)
    « Tu peux mettre un lien pour chaque [VA] ici aussi, je veux que tout le
    monde ait un lien pour les 4 models Amelia, Emma, Lola et Alicia », puis :
    « crée que des nouveaux liens stp, pour chaque VA 4 liens ». Ses liens de
    Va IG (liens_fr, équipe VA IG DISCORD) ne bougent pas : ceux-ci sont à
    part, dans leur équipe, leur registre et sous leur nom.

CE QU'EST UN LIEN JB FR
    Une page « <Model> JB <n> @<pseudo> » dans l'équipe VA JB FR, rangée dans
    le groupe de la model, faite à l'image de la page modèle de la model
    (« <model>tlg », liens_fr.lien_de_base) : GetMySocial ne copie un lien que
    DANS son équipe (400 link_not_in_team), la page est donc CRÉÉE dans VA JB
    FR en recopiant champ par champ la page modèle (photos et fond acceptés
    tels quels : images.getmysocial.com). Ses boutons OF / MYM pointent vers
    des trackings MyPuls NEUFS, à son nom (« Amelia_JB_1_pseudo ») ; un bouton
    sans tracking est retiré (liens_fr.boutons_remplaces) : jamais le compte
    d'exemple des pages modèles.

QUI, QUAND
    Chaque membre de You FR qui porte au moins un rôle de model
    (pseudo_model) reçoit les quatre, rôle ou pas pour chacune. Le bot les
    crée lui-même : au passage des trente minutes et après un rôle donné
    (cogs/pseudomodel), sous le verrou des liens FR (liens_fr._VERROU) — la
    model active de MyPuls est un état partagé, deux créations croisées
    poseraient un tracking chez la mauvaise model, et il ne s'efface pas.
    Rien n'est jamais coupé ni supprimé ici : un VA qui perd ses rôles garde
    ses liens.

CE QUI NE SE REFAIT PAS
    Un tracking MyPuls ne s'efface pas. Une création qui rate après ses
    trackings est notée (« echecs ») avec eux, et la suivante les REPREND au
    même nom au lieu d'en créer d'autres. GetMySocial en pause ou au plafond
    de l'offre : le passage s'arrête, c'est dit, rien n'est forcé.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

ETAT = Path(__file__).resolve().parent / "data" / "liens_jb_fr.json"

#: L'équipe GetMySocial « VA JB FR », créée par le propriétaire le 10/11/2026.
EQUIPE = "tm_6af336b09855e9c7a7c9c550"

#: Les champs de la page modèle recopiés sur chaque lien (le reste : défauts).
#: Les médias sont des adresses images.getmysocial.com, que create_link
#: accepte telles quelles.
CHAMPS_COPIES = (
    "bio", "name_user", "profile_picture", "profile_picture_slides", "background_image",
    "background_blur", "background_color", "custom_background_color", "custom_text_color",
    "texts_color", "font_family", "buttons_styles", "template", "online", "location",
    "fallback_location", "response_time", "verified_badge", "verified_badge_color",
    "show_profile_picture", "disable_link_logos", "social_media_links", "deeplink_mode",
    "adult_link_captcha", "open_in_new_tab", "domain",
    # sans lui, la page montrait la marque GetMySocial (essai du 10/11/2026 :
    # seul champ différent de la page modèle)
    "whitelabel",
)
#: Au plus autant de créations par passage : 10 VA × 4 tiennent, une erreur
#: de boucle ne viderait pas l'offre GetMySocial.
MAX_PAR_PASSAGE = 60
ESSAIS_ADRESSE = 25

_DITS: set = set()


def _dire_une_fois(cle: str, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        print(texte, flush=True)


# ──────────────────────────────────────────────────────────────── règle ──

def models_du_serveur(guild) -> Tuple[str, ...]:
    """Les models des liens JB de ce serveur (guild_features.LIENS_JB), ou ()."""
    try:
        import guild_features as gf
        return tuple(gf.liens_jb(guild))
    except Exception:                                        # noqa: BLE001
        return ()


def vas_du_serveur(guild) -> List[Tuple[int, str]]:
    """[(id, nom d'utilisateur)] des membres qui portent au moins un rôle de
    model (pseudo_model), triés par nom : ceux qui reçoivent les liens."""
    import pseudo_model as pm
    models = pm.models_du_serveur(guild)
    out = []
    for m in list(getattr(guild, "members", None) or []):
        if getattr(m, "bot", False):
            continue
        if pm.models_du_membre(m, models):
            nom = str(getattr(m, "name", "") or "").strip()
            if nom:
                out.append((int(m.id), nom))
    return sorted(out, key=lambda t: (t[1].casefold(), t[1]))


# ─────────────────────────────────────────────────────────────── registre ──

def _etat() -> Dict[str, Any]:
    d = safe_json.load(ETAT, default={}) or {}
    return d if isinstance(d, dict) else {}


def _ecrire(d: Dict[str, Any]) -> bool:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write(ETAT, d, indent=1))


def lien_de(uid, model: str) -> Optional[Dict[str, Any]]:
    try:
        return (_etat().get("liens") or {}).get(f"{int(uid)}:{str(model).lower()}")
    except (TypeError, ValueError):
        return None


def lien_public(uid, model: str) -> str:
    return str((lien_de(uid, model) or {}).get("public_url") or "")


def _echec_de(uid, model: str) -> Optional[Dict[str, Any]]:
    for e in reversed(_etat().get("echecs") or []):
        if isinstance(e, dict) and str(e.get("uid")) == str(uid) and e.get("model") == model:
            return e
    return None


def _numero(model: str) -> int:
    d = _etat()
    pris = [int(e.get("numero") or 0) for k, e in (d.get("liens") or {}).items()
            if k.endswith(":" + model) and isinstance(e, dict)]
    pris += [int(e.get("numero") or 0) for e in (d.get("echecs") or [])
             if isinstance(e, dict) and e.get("model") == model]
    return max([0] + pris) + 1


def nom_du_lien(model: str, numero: int, pseudo: str) -> str:
    import liens_fr
    nom = liens_fr.MODELS.get(model, {}).get("nom", model.capitalize())
    return f"{nom} JB {numero} @{pseudo}"[:60]


# ───────────────────────────────────────────────────────────── création ──

def _payload_page(gabarit: Dict[str, Any]) -> Dict[str, Any]:
    """Les champs de la page modèle à recopier, sans les vides."""
    out = {}
    for k in CHAMPS_COPIES:
        v = gabarit.get(k)
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = copy.deepcopy(v)
    # get_link rend en nombre ce que create_link veut en texte, et en nombre
    # ce qu'il veut en objet ; un champ vide de « location » serait refusé.
    for k in ("background_color", "texts_color"):
        if k in out:
            out[k] = str(out[k])
    if not isinstance(out.get("buttons_styles"), dict):
        out.pop("buttons_styles", None)
    if isinstance(out.get("location"), dict):
        out["location"] = {k: v for k, v in out["location"].items() if v not in ("", None)}
    # les diapositives : l'adresse et le type, pas l'identifiant interne
    if out.get("profile_picture_slides"):
        out["profile_picture_slides"] = [
            {k: v for k, v in s.items() if k in ("url", "media_type") and v}
            for s in out["profile_picture_slides"] if isinstance(s, dict) and s.get("url")]
    return out


def _boutons(gabarit: Dict[str, Any], urls: Dict[str, str]) -> List[Dict[str, Any]]:
    import liens_fr
    out = []
    for b in liens_fr.boutons_remplaces(gabarit.get("buttons") or [], urls):
        b = {k: v for k, v in b.items() if k != "block_id" and v is not None}
        out.append(b)
    return out


def creer(uid, pseudo: str, model: str, par: Any = "bot") -> Dict[str, Any]:
    """Le lien JB FR de ce VA pour cette model. Idempotent : déjà là, il est
    rendu tel quel. Rend {ok, deja, public_url, display_name, soucis, erreur,
    arret} — `arret` : GetMySocial en pause ou au plafond, le passage doit
    s'arrêter. À appeler HORS de la boucle d'événements (réseau)."""
    import gms
    import liens_fr
    model = str(model or "").strip().lower()
    cfg = liens_fr.MODELS.get(model)
    if not cfg:
        return {"ok": False, "erreur": f"« {model} » n'est pas une model FR"}
    with liens_fr._VERROU:
        deja = lien_de(uid, model)
        if deja and deja.get("public_url"):
            return {"ok": True, "deja": True, **deja}
        pourquoi = liens_fr.gms_indisponible()
        if pourquoi:
            return {"ok": False, "arret": True, "erreur": f"{pourquoi} : rien n'a été créé"}
        try:
            base_id = liens_fr.lien_de_base(model)
        except Exception as e:                               # noqa: BLE001
            return {"ok": False, "arret": True,
                    "erreur": f"liste GetMySocial illisible ({type(e).__name__}: {e})"}
        if not base_id:
            return {"ok": False, "erreur": f"pas de page modèle « {model}tlg » dans VA IG DISCORD"}
        gabarit = liens_fr.lire_lien(base_id)
        plates = sorted({liens_fr.plateforme(b.get("url")) for b in gabarit.get("buttons") or []}
                        - {""})
        if not plates:
            return {"ok": False, "erreur": f"la page modèle de {cfg['nom']} n'a aucun bouton OF ni MYM"}

        # Un essai raté garde sa page et ses trackings : on les reprend.
        ancien = _echec_de(uid, model) or {}
        n = int(ancien.get("numero") or 0) or _numero(model)
        nom = ancien.get("display_name") or nom_du_lien(model, n, pseudo)
        urls: Dict[str, str] = dict(ancien.get("trackings") or {})
        link_id, sc = str(ancien.get("link_id") or ""), str(ancien.get("shortcode") or "")
        soucis: List[str] = []

        def _echec(erreur: str, arret: bool = False) -> Dict[str, Any]:
            if urls or link_id:
                d = _etat()
                d["echecs"] = [e for e in (d.get("echecs") or [])
                               if not (str(e.get("uid")) == str(uid) and e.get("model") == model)]
                d["echecs"].append({"uid": str(uid), "pseudo": pseudo, "model": model, "numero": n,
                                    "display_name": nom, "trackings": dict(urls),
                                    "link_id": link_id, "shortcode": sc,
                                    "erreur": erreur, "quand": int(time.time())})
                if not _ecrire(d):
                    soucis.append("registre data/liens_jb_fr.json non écrit : essai non noté")
            print(f"[liens-jb] {nom} : ECHEC {erreur}", flush=True)
            return {"ok": False, "arret": arret, "erreur": erreur, "soucis": soucis,
                    "trackings": dict(urls)}

        # 1) La PAGE d'abord, sans ses boutons OF / MYM : si GetMySocial la
        #    refuse, aucun tracking MyPuls (ineffaçable) n'a encore été créé.
        if not link_id:
            corps = _payload_page(gabarit)
            corps.update({"type": "landing", "display_name": nom, "team_id": EQUIPE,
                          "buttons": _boutons(gabarit, {})})
            try:
                import liens_va
                groupe = liens_va.groupe_manager(EQUIPE, cfg["nom"])
            except Exception as e:                           # noqa: BLE001
                groupe = ""
                print(f"[liens-jb] groupe {cfg['nom']} : {type(e).__name__}: {e}", flush=True)
            if groupe:
                corps["group_id"] = groupe
            else:
                soucis.append(f"groupe « {cfg['nom']} » introuvable et non créé : lien hors groupe")
            lien = None
            for essai in range(ESSAIS_ADRESSE):
                sc = liens_fr._mots_doux(model, n + 7 + essai)
                r = gms._call_tool("create_link", {**corps, "shortcode": sc})
                if r.get("ok"):
                    lien = liens_fr._objet(r)
                    break
                err = str(r.get("error") or "")
                if "plan_limit" in err:
                    return _echec(f"GetMySocial : plafond de l'offre atteint ({err[:160]})", arret=True)
                if "shortcode" not in err.lower():
                    return _echec(f"GetMySocial refuse la page : {err[:200]}", arret=True)
            if not lien or not lien.get("id"):
                sc = ""
                return _echec("GetMySocial : aucune adresse libre")
            link_id = str(lien["id"])

        # 2) Les trackings MyPuls, à son nom (repris d'un essai raté).
        for p in plates:
            if urls.get(p):
                continue
            cid = cfg.get(p)
            if not cid:
                soucis.append(f"{p.upper()} : aucune créatrice MyPuls pour {cfg['nom']} — bouton retiré")
                continue
            t = liens_fr.creer_tracking(liens_fr.nom_tracking(nom), int(cid))
            if t.get("ok") and t.get("url"):
                urls[p] = t["url"]
            else:
                soucis.append(f"{p.upper()} : {t.get('erreur')} — bouton retiré")
        if not urls:
            return _echec("aucun tracking MyPuls créé : page sans bouton, gardée pour le prochain essai")

        # 3) Les boutons, vers SES trackings.
        maj = {"link_id": link_id, "team_id": EQUIPE, "buttons": _boutons(gabarit, urls)}
        if gabarit.get("whitelabel") is not None:
            # reposé ici : la création l'a ignoré une fois (10/11/2026)
            maj["whitelabel"] = gabarit["whitelabel"]
        r = gms._call_tool("update_link", maj)
        if not r.get("ok"):
            return _echec(f"boutons non posés ({str(r.get('error'))[:160]})")

        public = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
        entree = {"pseudo": pseudo, "model": model, "numero": n, "link_id": link_id,
                  "shortcode": sc, "public_url": public, "display_name": nom,
                  "trackings": urls, "soucis": soucis, "par": str(par or ""),
                  "quand": int(time.time())}
        d = _etat()
        d.setdefault("liens", {})[f"{int(uid)}:{model}"] = entree
        d["echecs"] = [e for e in (d.get("echecs") or [])
                       if not (str(e.get("uid")) == str(uid) and e.get("model") == model)]
        if not _ecrire(d):
            soucis.append("registre data/liens_jb_fr.json non écrit : un passage suivant recréerait")
        print(f"[liens-jb] {nom} -> {public} (trackings {sorted(urls)}, soucis {len(soucis)})",
              flush=True)
        return {"ok": True, "deja": False, **entree}


def manquants(guild) -> List[Tuple[int, str, str]]:
    """[(id, pseudo, model)] des liens JB à créer sur ce serveur."""
    models = models_du_serveur(guild)
    if not models:
        return []
    liens = _etat().get("liens") or {}
    return [(uid, nom, m) for uid, nom in vas_du_serveur(guild) for m in models
            if not (liens.get(f"{uid}:{m}") or {}).get("public_url")]


def assurer(guild, a_faire: Optional[List[Tuple[int, str, str]]] = None) -> Dict[str, Any]:
    """Crée les liens JB qui manquent (bloquant : à lancer dans un fil). Rend
    le bilan ; chaque échec y est compté et imprimé."""
    bilan = {"crees": [], "echecs": [], "arret": ""}
    a_faire = manquants(guild) if a_faire is None else a_faire
    de_suite = 0
    for uid, pseudo, model in a_faire[:MAX_PAR_PASSAGE]:
        try:
            r = creer(uid, pseudo, model, par="bot (You FR, 4 liens par VA)")
        except Exception as e:                               # noqa: BLE001
            r = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        if r.get("ok"):
            de_suite = 0
            if not r.get("deja"):
                bilan["crees"].append(r.get("display_name"))
        else:
            de_suite += 1
            bilan["echecs"].append(f"{pseudo}/{model} : {r.get('erreur')}"[:220])
            # Deux échecs de suite : une cause commune, pas un hasard. On
            # s'arrête avant d'en payer d'autres.
            if r.get("arret") or de_suite >= 2:
                bilan["arret"] = str(r.get("erreur"))
                break
        time.sleep(1.5)                                      # 429 après ~30 créations/min
    if len(a_faire) > MAX_PAR_PASSAGE:
        _dire_une_fois(f"plafond:{len(a_faire)}", f"[liens-jb] {len(a_faire)} liens à créer : "
                       f"{MAX_PAR_PASSAGE} par passage, la suite au prochain")
    if bilan["crees"] or bilan["echecs"]:
        print(f"[liens-jb] {getattr(guild, 'name', '?')} : {len(bilan['crees'])} créé(s), "
              f"echecs {bilan['echecs']}{' — ARRET : ' + bilan['arret'] if bilan['arret'] else ''}",
              flush=True)
    return bilan
