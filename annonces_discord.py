"""Les annonces du propriétaire, écrites À TRAVERS le bot (Va IG, 03/10/2026).

Propriétaire : « je veux faire comme pour Twitter : j'écris dans le truc à
travers le bot ». Sur Twitter, l'annonce de 📢┃annonces est signée Luigi.exe,
pas le compte du propriétaire. Ici, /annonce (sous l'application du bot du
serveur, Luigi sur Va IG) ouvre une fenêtre. Le texte tapé part dans le salon
où la commande a été lancée, publié PAR LE BOT.

POURQUOI UNE COMMANDE, ET PAS « LE BOT RECOPIE CE QUE J'ÉCRIS ». Recopier
un message demanderait l'intention « contenu des messages » sur le bot
principal. Sans le réglage côté Discord, cette intention empêche le bot de
se connecter du tout. La commande arrive sur /discord/interactions comme
/quetes, et le message part en REST avec le jeton du bot du serveur.

Réservée aux managers : administrateur, gestion des rôles ou rôle manager du
serveur (verif_discord._est_manager). Elle est aussi cachée aux autres :
default_member_permissions = Administrateur. Un VA ne la voit pas dans sa
liste.

Options : `ping` (mentionner @everyone) et `image` (une pièce jointe, remise
sous l'annonce). Un texte de plus de 2000 caractères (limite d'un message
Discord) part en plusieurs messages, coupés aux paragraphes.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Optional

#: La fenêtre ouverte par /annonce ne porte que du texte : le salon, le ping
#: et l'image de la commande attendent ici sa validation (un seul processus :
#: le site tourne dans le bot). Au-delà, Discord a de toute façon fermé la
#: fenêtre.
_BROUILLONS: Dict[str, Dict[str, Any]] = {}
BROUILLON_MAX_S = 15 * 60
LIMITE_MESSAGE = 2000
LIMITE_FENETRE = 4000
#: Discord refuse au-delà de 25 Mo pour un bot sans boost ; on refuse avant
#: de télécharger.
IMAGE_MAX_OCTETS = 24 * 1024 * 1024

ADMINISTRATEUR = "8"


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


def _en_fond(f):
    from verif_discord import _EN_FOND
    _EN_FOND(f)


def _ephemere(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte[:2000], "flags": 64,
                                "allowed_mentions": {"parse": []}}}


def _manager(p: Dict[str, Any]) -> bool:
    import verif_discord as vd
    gid = str(p.get("guild_id") or "")
    cfg = vd.serveur(gid)
    membre = p.get("member") or {}
    try:
        if cfg is not None:
            return vd._est_manager(membre, cfg)
        return bool(vd._permissions(membre) & 0x8)
    except Exception:
        return False


def _purger(maintenant: Optional[float] = None) -> None:
    t = time.time() if maintenant is None else maintenant
    for k in [k for k, b in _BROUILLONS.items() if t - b.get("t", 0) > BROUILLON_MAX_S]:
        _BROUILLONS.pop(k, None)


def couper(texte: str, limite: int = LIMITE_MESSAGE) -> List[str]:
    """Le texte en morceaux d'au plus `limite` caractères, coupés à la fin
    d'un paragraphe, sinon d'une ligne, sinon d'un mot. Rien n'est perdu."""
    reste = (texte or "").strip()
    out: List[str] = []
    while len(reste) > limite:
        tranche = reste[:limite]
        coupe = max(tranche.rfind("\n\n"), -1)
        if coupe < limite // 3:
            coupe = tranche.rfind("\n")
        if coupe < limite // 3:
            coupe = tranche.rfind(" ")
        if coupe < limite // 3:
            coupe = limite
        out.append(reste[:coupe].rstrip())
        reste = reste[coupe:].lstrip("\n ")
    if reste:
        out.append(reste)
    return out


def _option(data: Dict[str, Any], nom: str):
    for o in data.get("options") or []:
        if o.get("name") == nom:
            return o.get("value")
    return None


def _fenetre(cle: str) -> Dict[str, Any]:
    return {"type": 9, "data": {
        "custom_id": f"annonce:{cle}",
        "title": "Annonce",
        "components": [{"type": 1, "components": [{
            "type": 4, "custom_id": "texte", "style": 2, "label": "Ton annonce",
            "min_length": 1, "max_length": LIMITE_FENETRE, "required": True,
            "placeholder": "Écris ton annonce : le bot la publie dans ce salon."}]}]}}


def _texte_de(p: Dict[str, Any]) -> str:
    for rang in (p.get("data") or {}).get("components") or []:
        for c in rang.get("components") or []:
            if c.get("custom_id") == "texte":
                return str(c.get("value") or "")
    return ""


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La commande /annonce et sa fenêtre. None si ce n'est pas pour nous :
    l'appelant passe la main au module suivant (même porte que /quetes)."""
    t = p.get("type")
    data = p.get("data") or {}
    if t == 2:
        if (data.get("name") or "") != "annonce":
            return None
        if not _manager(p):
            return _ephemere("Réservé aux managers.")
        _purger()
        image = None
        aid = _option(data, "image")
        if aid:
            image = ((data.get("resolved") or {}).get("attachments") or {}).get(str(aid))
            if image and int(image.get("size") or 0) > IMAGE_MAX_OCTETS:
                return _ephemere("❌ Image trop lourde (25 Mo au plus).")
        cle = secrets.token_hex(6)
        _BROUILLONS[cle] = {"t": time.time(), "salon": str(p.get("channel_id") or ""),
                            "gid": str(p.get("guild_id") or ""), "ping": bool(_option(data, "ping")),
                            "image": image,
                            "uid": str(((p.get("member") or {}).get("user") or {}).get("id") or "")}
        return _fenetre(cle)
    if t == 5:
        cid = str(data.get("custom_id") or "")
        if not cid.startswith("annonce:"):
            return None
        if not _manager(p):
            return _ephemere("Réservé aux managers.")
        brouillon = _BROUILLONS.pop(cid.split(":", 1)[1], None)
        texte = _texte_de(p).strip()
        if brouillon is None:
            # bot redemarre entre la commande et l'envoi : le texte est rendu
            # au manager plutot que perdu
            return _ephemere("⏳ Fenêtre expirée : relance /annonce. Ton texte :\n" + texte[:1900])
        if not texte:
            return _ephemere("Annonce vide : rien n'a été publié.")
        import verif_discord as vd
        app = vd.app_de_reponse(p, brouillon["gid"])
        jeton = str(p.get("token") or "")
        _en_fond(lambda: _publier_et_dire(brouillon, texte, app, jeton))
        return {"type": 5, "data": {"flags": 64}}        # « le bot réfléchit », éphémère
    return None


def _image(brouillon: Dict[str, Any]):
    """(nom, octets, type) de l'image jointe à la commande, ou None.
    Téléchargée tout de suite : l'adresse d'une pièce jointe d'interaction
    est signée et expire."""
    im = brouillon.get("image")
    if not im or not im.get("url"):
        return None
    import requests
    r = requests.get(im["url"], timeout=30)
    r.raise_for_status()
    return (str(im.get("filename") or "image.png"), r.content,
            str(im.get("content_type") or "application/octet-stream"))


def publier(brouillon: Dict[str, Any], texte: str) -> Dict[str, Any]:
    """Publie l'annonce dans le salon du brouillon, au nom du bot.
    -> {"ok": bool, "ids": [...], "erreur": str}"""
    ping = brouillon.get("ping") or "@everyone" in texte or "@here" in texte
    if brouillon.get("ping") and "@everyone" not in texte:
        texte = "@everyone\n" + texte
    morceaux = couper(texte)
    salon = brouillon["salon"]
    try:
        image = _image(brouillon)
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "ids": [], "erreur": f"image illisible ({type(e).__name__})"}
    ids: List[str] = []
    for i, morceau in enumerate(morceaux):
        payload: Dict[str, Any] = {
            "content": morceau,
            # le ping ne part qu'avec le PREMIER morceau : un texte coupe en
            # trois ne doit pas notifier trois fois
            "allowed_mentions": {"parse": ["everyone"] if (ping and i == 0) else []}}
        dernier = i == len(morceaux) - 1
        if dernier and image is not None:
            nom, octets, typ = image
            payload["attachments"] = [{"id": 0, "filename": nom}]
            code, rep = _api("POST", f"/channels/{salon}/messages",
                             data={"payload_json": json.dumps(payload)},
                             files={"files[0]": (nom, octets, typ)})
        else:
            code, rep = _api("POST", f"/channels/{salon}/messages", json=payload)
        if code not in (200, 201) or not (rep or {}).get("id"):
            msg = str((rep or {}).get("message") or "")[:120]
            return {"ok": False, "ids": ids, "erreur": f"HTTP {code}{' : ' + msg if msg else ''}"}
        ids.append(str(rep["id"]))
    return {"ok": True, "ids": ids, "erreur": ""}


def _publier_et_dire(brouillon: Dict[str, Any], texte: str, app: str, jeton: str) -> None:
    try:
        r = publier(brouillon, texte)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "ids": [], "erreur": f"{type(e).__name__}: {e}"[:160]}
    if r["ok"]:
        lien = f'https://discord.com/channels/{brouillon["gid"]}/{brouillon["salon"]}/{r["ids"][0]}'
        dire = f"✅ Annonce publiée : {lien}"
        print(f'[annonce] publiée dans {brouillon["salon"]} ({len(r["ids"])} message(s))', flush=True)
    else:
        # le texte revient au manager : rien de ce qu'il a tapé n'est perdu
        dire = (f'❌ Annonce non publiée ({r["erreur"]})'
                + (f' — {len(r["ids"])} morceau(x) déjà parti(s)' if r["ids"] else "")
                + ". Ton texte :\n" + texte[:1700])
        print(f'[annonce] ÉCHEC dans {brouillon["salon"]} : {r["erreur"]}', flush=True)
    if app and jeton:
        _api("PATCH", f"/webhooks/{app}/{jeton}/messages/@original",
             json={"content": dire[:2000], "allowed_mentions": {"parse": []}})


def enregistrer_commande(gid: str) -> bool:
    """Déclare /annonce sur le serveur, sous l'application du bot de CE
    serveur (Luigi sur Va IG). Discord la garde : à relancer seulement si
    elle change. Ne touche pas aux autres commandes (/quetes)."""
    from verif_discord import bot_du_serveur
    app = bot_du_serveur(gid)["app_id"]
    code, rep = _api("POST", f"/applications/{app}/guilds/{gid}/commands", json={
        "name": "annonce", "type": 1,
        "description": "Écrire une annonce, publiée dans ce salon par le bot",
        "default_member_permissions": ADMINISTRATEUR,
        "options": [
            {"type": 5, "name": "ping", "description": "Mentionner @everyone", "required": False},
            {"type": 11, "name": "image", "description": "Une image sous l'annonce", "required": False},
        ]})
    ok = code in (200, 201)
    print(f'[annonce] /annonce {"enregistrée" if ok else "refusée"} sur {gid} : '
          f'HTTP {code} {"" if ok else str(rep)[:160]}', flush=True)
    return ok
