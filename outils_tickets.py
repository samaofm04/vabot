# -*- coding: utf-8 -*-
"""📤 Spoofer et ⬇️ Download dans le ticket d'un VA de TRUST INSTAGRAM.

POURQUOI (propriétaire, 30/10/2026)
    Les outils des salons perso de Youl4b (<pseudo>-spoofer, <pseudo>-download)
    dans le ticket TRUST INSTAGRAM, un bouton par outil dans le menu du
    ticket, et le résultat « chez lui », dans son ticket : « je veux vraiment
    un ticket pour le VA comme maintenant » (pas de salons en plus), puis
    « vas-y ajoute dans trust agency ». Twitter et Threads ne changent pas.

OÙ ÇA VIT
    Deux boutons de la rangée du VA du menu épinglé (tickets_discord, enveloppe
    de boutons_va en fin de fichier) : 💳 · 📈 · 📤 Spoofer · ⬇️ Download · 📱.
    Cinq : le plafond d'une rangée, un sixième ferait refuser tout le menu.
    TRUST INSTAGRAM n'a que Wario, en REST, sans gateway : chaque clic arrive
    sur /discord/interactions (web_upload._discord_repondre) et passe ici.

    📤 ouvre directement la fenêtre (comme la ligne du ticket de Va IG) : le
       fichier (FileUpload dans un Label) et le nombre de versions (1 à 5).
    ⬇️ ouvre la fenêtre du compte (pseudo, combien), puis un message privé
       porte les choix : Tout · Photo de profil · Bio · Posts photo · Reels ·
       Top reels. Le choix seul est privé : un éphémère disparaît au
       rechargement de Discord, le résultat ne doit jamais y vivre.

OÙ PARTENT LES FICHIERS
    TOUJOURS dans le ticket où l'on a cliqué — même quand c'est le manager qui
    clique pour son VA (règle de cogs/outils.ou_livrer) —, postés avec le jeton
    de Wario : le jeton d'un clic meurt au bout de 15 minutes, un spoof en file
    derrière d'autres en prend parfois plus. Hors d'un ticket (le menu privé
    du staff), on refuse plutôt que de livrer dans un salon que d'autres
    voient. Après chaque livraison, le menu est reposé en dernier
    (tickets_discord.ramener_menu, en_dernier) : sans ça, les fichiers
    l'enterraient jusqu'au tour de l'heure.

LE MÊME MOTEUR QUE YOUL4B
    Spoofer : cogs/spoofer.versions_photo / versions_video (métadonnées US,
    moteur des brutes, chaque version vérifiée par md5), sous SON verrou
    _FILE : la coroutine est planifiée sur la boucle de Yoshi, qui tourne dans
    le même processus que le site. Un asyncio.Semaphore appartient à la boucle
    qui l'attend : un second verrou côté Flask aurait laissé deux encodages
    tourner en même temps sur un VPS à deux cœurs — exactement ce que le
    verrou unique empêche (« cinq re-encodages de trois VA en même temps
    faisaient rater leurs trois secondes aux autres panneaux »). Seule
    l'ATTENTE de ce verrou est bornée, jamais la fabrication : l'encodage
    tourne dans un fil (asyncio.to_thread), qu'annuler la tâche n'arrête pas.

    Download : Telechargement.livrer de cogs/telechargement, tel quel (même
    ordre, même format, même réserve HikerAPI de 300 requêtes, même cache, même
    anti double-clic), lancé sur la boucle de Yoshi avec le ticket habillé en
    salon (_SalonTicket). La copie part dans all-download de Youl4b, chez
    Yoshi, comme aujourd'hui.

LIMITE DE TAILLE
    Celle du serveur selon son niveau de boost (GET /guilds, en cache une
    heure) : 10 Mio sans boost ou au niveau 1, 50 au niveau 2, 100 au niveau 3.
    Rien n'est écarté en silence : un fichier trop lourd est compté et dit.

CE QUI N'EST PAS ICI
    Aucune route : /discord/interactions est déjà publique et signée. Aucun
    texte de notice ; et jamais « YouLab » — les réponses d'interaction ne
    passent pas par la traduction TRUST de verif_discord.api.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import safe_json
# Le préfixe vit avec les boutons, dans tickets_discord : le menu et les clics
# ne peuvent pas diverger.
from tickets_discord import OUTILS_PREFIXE as PREFIXE

AGENCY_IG_ID = "1488331963575177247"
#: Les serveurs où ces boutons existent (tickets_discord.OUTILS_DANS_MENU).
SERVEURS = {AGENCY_IG_ID}

DATA_DIR = Path(__file__).resolve().parent / "data"
#: Les travaux en cours, par ticket : un redémarrage (chaque déploiement) les
#: coupe ; au démarrage suivant, le VA l'apprend dans son ticket au lieu
#: d'attendre des fichiers qui ne viendront pas.
ETAT = DATA_DIR / "outils_tickets.json"
#: Ce processus : un travail lancé juste après le démarrage n'est pas pris
#: pour un travail interrompu.
_PROCESSUS = os.urandom(6).hex()

QTE_DEFAUT = 5
QTE_MAX = 5
COMBIEN_DEFAUT = 30

MIO = 1024 * 1024
LIMITE_DEFAUT = 10 * MIO
#: Par fichier, selon le niveau de boost du serveur (premium_tier).
LIMITES_BOOST = {0: 10 * MIO, 1: 10 * MIO, 2: 50 * MIO, 3: 100 * MIO}
LIMITE_CACHE_S = 3600
#: Une lecture ratée est retentée plus tôt qu'une lecture réussie.
LIMITE_REESSAI_S = 300

#: Pause entre deux messages d'une livraison : 5 messages / 5 s par salon.
PAUSE_ENVOI = 1.0
#: Au-delà de cette attente du verrou unique, le spoof est rendu au VA
#: (« trop de spoofs en attente ») sans avoir rien encodé.
FILE_MAX_S = 30 * 60
#: Une fois le verrou pris, la fabrication n'est JAMAIS annulée (son ffmpeg
#: continuerait dans son fil, verrou rendu). Le pire mesuré : 5 versions × 3
#: essais × 300 s (délai de ffmpeg) = 75 min. Au-delà de cette garde, le fil
#: du site cesse d'attendre et le dit, sans rien annuler.
GARDE_FABRICATION_S = 3 * 3600
#: Le temps laissé à la boucle de Yoshi pour réserver un téléchargement
#: pendant le clic (Discord en laisse 3 pour répondre).
RESERVATION_MAX_S = 1.5
#: Le premier tour après le démarrage attend que le site et Wario soient prêts.
REPRISE_DELAI_S = 20

TEXTE_HORS_TICKET = "Ça se lance depuis le salon perso d'un VA."
TEXTE_PAS_A_TOI = "Seul ce VA ou son manager peut s'en servir."
TEXTE_INDISPONIBLE = "Indisponible pour le moment, réessaie dans un instant."
TEXTE_SPOOF_EN_COURS = "⏳ Ton spoof précédent n'est pas fini."
#: Les refus déjà dits (ou sans personne à qui le dire) : pas de bilan
#: « x/q — ratée(s) » par-dessus.
_REFUS_SANS_BILAN = ("telechargement", "duree", "file", "bloque", "disparu")

_VERROU = threading.RLock()
#: Les tickets dont un spoof tourne : un à la fois par ticket. Deux fenêtres
#: ouvertes par deux clics peuvent être validées toutes les deux.
_SPOOFS: set = set()
_LIMITES: Dict[str, Tuple[int, float]] = {}
_DEMARRE = [False]


def _log(texte: str) -> None:
    print(f"[outils] {texte}", flush=True)


def _fond(f):
    """Travail après la réponse à Discord (3 s pour l'avoir). Le fil emporte
    le contexte (serveur courant). Remplacé par un appel direct dans les tests."""
    import verif_discord as vd
    vd._EN_FOND(f)


def _dormir(s: float) -> None:
    time.sleep(s)


def _api(methode: str, chemin: str, **kw):
    import verif_discord as vd
    return vd.api(methode, chemin, **kw)


# ─── Les boutons du menu ──────────────────────────────────────────────────
def boutons(uid: str) -> List[Dict[str, Any]]:
    """Les deux boutons de la rangée du VA, tels que tickets_discord les
    insère (ils y sont décrits : la rangée ne dépend pas de ce module)."""
    import tickets_discord as tk
    return tk.boutons_outils(uid)


def _ephemere(texte: str, composants: Optional[list] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {"content": texte, "flags": 64, "allowed_mentions": {"parse": []}}
    if composants:
        data["components"] = composants
    return {"type": 4, "data": data}


# ─── Qui clique, dans quel ticket ─────────────────────────────────────────
def _tickets(gid: str) -> Dict[str, str]:
    """{salon perso: VA} des tickets de ce serveur (data/tickets.json)."""
    import tickets_discord as tk
    out: Dict[str, str] = {}
    for k, v in ((tk._etat().get("tickets") or {}).items()):
        g, _sep, uid = str(k).partition(":")
        if g == str(gid) and uid.isdigit() and isinstance(v, dict) and v.get("salon"):
            out[str(v["salon"])] = uid
    return out


def _ticket_du_clic(p: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], str]:
    """({gid, salon, uid (le VA du ticket), qui (le cliqueur)}, "") ou (None,
    le refus). Le VA du ticket ou un manager/helper, comme 💳 et 📈 : un autre
    VA ne se sert pas des outils d'un ticket qui n'est pas le sien."""
    gid = str(p.get("guild_id") or "")
    if gid not in SERVEURS:
        return None, "Ce bouton ne sert pas sur ce serveur."
    salon = str(p.get("channel_id") or "")
    vau = _tickets(gid).get(salon)
    if not vau:
        # le menu privé du staff (menu_prive), ou un vieux message ailleurs
        return None, TEXTE_HORS_TICKET
    membre = p.get("member") or {}
    qui = str(((membre.get("user") or {}).get("id")) or "")
    if qui != vau:
        import tickets_discord as tk
        if not tk._est_manager_brut(gid, membre):
            return None, TEXTE_PAS_A_TOI
    nom = str(((membre.get("user") or {}).get("username")) or qui)
    return {"gid": gid, "salon": salon, "uid": vau, "qui": qui, "nom": nom}, ""


def _champs(composants: Any) -> Dict[str, Any]:
    """{custom_id: valeur} d'une fenêtre renvoyée : rangées (type 1) comme
    étiquettes (type 18, dont l'enfant est sous « component »). Une liste
    (« values ») pour les fichiers et les menus, un texte (« value ») sinon."""
    out: Dict[str, Any] = {}
    pile = list(composants or [])
    while pile:
        c = pile.pop()
        if not isinstance(c, dict):
            continue
        cid = c.get("custom_id")
        if cid:
            out[str(cid)] = c.get("values") if "values" in c else c.get("value")
        pile += list(c.get("components") or [])
        if isinstance(c.get("component"), dict):
            pile.append(c["component"])
    return out


# ─── La boucle de Yoshi ───────────────────────────────────────────────────
def _bot_principal():
    """Yoshi (discord.py, gateway) : sa boucle porte le verrou du spoofer et
    le cog du téléchargement. main.py le donne au site (set_bot_ref)."""
    wu = sys.modules.get("web_upload")
    return getattr(wu, "_BOT_REF", None) if wu is not None else None


def _boucle(bot) -> Optional[asyncio.AbstractEventLoop]:
    """La boucle de Yoshi si elle tourne, sinon None. Avant son login,
    discord.py met dans Client.loop un _LoopSentinel dont TOUT attribut lève
    (MISSING après sa fermeture) ; main.py lance le site avant le bot. Le try
    couvre donc tout : sans ça, un clic dans ces secondes-là remontait
    l'AttributeError et le VA lisait « ❌ Erreur » au lieu d'« Indisponible »."""
    try:
        boucle = getattr(bot, "loop", None)
        if boucle is None or boucle.is_closed() or not boucle.is_running():
            return None
        return boucle
    except Exception:                                        # noqa: BLE001
        return None


def _journaliser_fin(quoi: str):
    def _fin(fut):
        try:
            exc = fut.exception()
        except BaseException:                                # annulé
            return
        if exc is not None:
            _log(f"{quoi} : {type(exc).__name__}: {exc}")
    return _fin


# ─── Limite de taille du serveur ──────────────────────────────────────────
def limite_fichiers(gid: str) -> int:
    """Ce que le serveur accepte par fichier, lu à son niveau de boost (lecture
    seule, en cache une heure). Illisible : 10 Mio, le plus petit — un fichier
    refusé quand même (413) reste compté et dit."""
    gid = str(gid)
    c = _LIMITES.get(gid)
    if c and time.time() < c[1]:
        return c[0]
    code, rep = _api("GET", f"/guilds/{gid}", gid=gid)
    if code == 200 and isinstance(rep, dict):
        try:
            niveau = int(rep.get("premium_tier") or 0)
        except (TypeError, ValueError):
            niveau = 0
        lim = LIMITES_BOOST.get(niveau, LIMITE_DEFAUT)
        _LIMITES[gid] = (lim, time.time() + LIMITE_CACHE_S)
        return lim
    _log(f"niveau de boost de {gid} illisible (HTTP {code}) : {LIMITE_DEFAUT // MIO} Mio par fichier")
    _LIMITES[gid] = (LIMITE_DEFAUT, time.time() + LIMITE_REESSAI_S)
    return LIMITE_DEFAUT


# ─── Écrire dans le ticket ────────────────────────────────────────────────
def _type_mime(nom: str) -> str:
    return mimetypes.guess_type(nom)[0] or "application/octet-stream"


def poster(gid: str, salon: str, texte: str = "", fichiers=()) -> Tuple[int, Any]:
    """Un message dans le ticket, avec le jeton de Wario. `fichiers` :
    [(nom, octets)]. Rend (code, corps) ; ne lève pas."""
    corps: Dict[str, Any] = {"allowed_mentions": {"parse": []}}
    if texte:
        corps["content"] = texte[:2000]
    chemin = f"/channels/{salon}/messages"
    try:
        if not fichiers:
            return _api("POST", chemin, json=corps, gid=gid)
        corps["attachments"] = [{"id": i, "filename": nom} for i, (nom, _o) in enumerate(fichiers)]
        return _api("POST", chemin, gid=gid,
                    data={"payload_json": json.dumps(corps, ensure_ascii=False)},
                    files={f"files[{i}]": (nom, octets, _type_mime(nom))
                           for i, (nom, octets) in enumerate(fichiers)})
    except Exception as e:                                   # noqa: BLE001
        return 0, {"message": f"{type(e).__name__}: {str(e)[:160]}"}


def _trop_lourd(code: int, rep: Any) -> bool:
    return code == 413 or (isinstance(rep, dict) and rep.get("code") == 40005)


def _ticket_disparu(code: int, rep: Any) -> bool:
    """Discord dit le salon inconnu : le ticket a été supprimé."""
    return code == 404 or (isinstance(rep, dict) and rep.get("code") == 10003)


def _ticket_existe(gid: str, salon: str) -> bool:
    """False seulement quand Discord dit le ticket supprimé : une panne de
    lecture ne bloque pas un spoof."""
    try:
        code, rep = _api("GET", f"/channels/{salon}", gid=gid)
    except Exception:                                        # noqa: BLE001
        return True
    return not _ticket_disparu(code, rep)


def _dire(gid: str, salon: str, texte: str) -> bool:
    code, rep = poster(gid, salon, texte)
    if code not in (200, 201):
        _log(f"message non posté dans {salon} (HTTP {code}) {str(rep)[:120]} : {texte[:120]}")
        return False
    return True


def _ramener_menu(gid: str, uid: str, salon: str) -> None:
    """Le menu redevient le dernier message du ticket, sans avis d'épingle."""
    try:
        import tickets_discord as tk
        if tk.ramener_menu(gid, uid, salon, en_dernier=True) == "echec":
            _log(f"menu du ticket {salon} non reposé en bas après une livraison")
    except Exception as e:                                   # noqa: BLE001
        _log(f"menu du ticket {salon} : {type(e).__name__}: {e}")


# ─── Les travaux en cours (pour un redémarrage) ───────────────────────────
def _lire_etat() -> Dict[str, Any]:
    d = safe_json.load(ETAT, default={}) or {}
    if not isinstance(d, dict):
        _log(f"{ETAT.name} n'est pas un objet JSON : repart à vide")
        d = {}
    if not isinstance(d.get("en_cours"), dict):
        d["en_cours"] = {}
    return d


def _noter(salon: str, quoi: str, info: Optional[Dict[str, Any]]) -> None:
    """Marque (ou efface) le travail `quoi` du ticket `salon`. Une marque par
    outil : un spoof et un téléchargement tournent ensemble dans un ticket, la
    fin de l'un effaçait sinon la marque de l'autre."""
    cle = f"{salon}:{quoi}"
    with _VERROU:
        d = _lire_etat()
        if info is None:
            if d["en_cours"].pop(cle, None) is None:
                return
        else:
            d["en_cours"][cle] = dict(info, salon=str(salon), quoi=quoi,
                                      processus=_PROCESSUS, t=int(time.time()))
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(ETAT, d, indent=1):
            _log(f"{ETAT.name} non écrit : un redémarrage ne serait pas annoncé")


def prevenir_interrompus() -> int:
    """Les travaux coupés par le redémarrage : le VA l'apprend dans son ticket.
    Ceux de ce processus (lancés depuis) ne sont pas touchés. Rend le nombre
    de tickets prévenus."""
    with _VERROU:
        d = _lire_etat()
        coupes = {s: i for s, i in d["en_cours"].items()
                  if isinstance(i, dict) and i.get("processus") != _PROCESSUS}
        for s in coupes:
            d["en_cours"].pop(s, None)
        if coupes and not safe_json.write(ETAT, d, indent=1):
            # Les marques restent sur le disque : annoncer maintenant, c'était
            # annoncer de nouveau à chaque déploiement, sans trace de pourquoi.
            # Remis au prochain démarrage, qui réessaiera l'écriture.
            _log(f"{ETAT.name} non écrit : {len(coupes)} annonce(s) de redémarrage "
                 "remise(s) au prochain démarrage")
            return 0
    n = 0
    for cle, i in coupes.items():
        salon = str(i.get("salon") or cle.split(":", 1)[0])
        gid, uid = str(i.get("gid") or AGENCY_IG_ID), str(i.get("uid") or "")
        if i.get("quoi") == "download":
            texte = f"⬇️ @{i.get('nom') or '?'} : interrompu par un redémarrage, relance-le."
        else:
            texte = f"🎭 {i.get('nom') or 'fichier'} : interrompu par un redémarrage, renvoie-le."
        if _dire(gid, salon, texte):
            n += 1
            if uid:
                _ramener_menu(gid, uid, salon)
    if coupes:
        _log(f"reprise : {n}/{len(coupes)} ticket(s) prévenu(s) d'un travail interrompu")
    return n


def demarrer() -> None:
    """Au démarrage du site (web_upload) : une fois par processus."""
    if _DEMARRE[0]:
        return
    _DEMARRE[0] = True
    try:
        _fond(lambda: (_dormir(REPRISE_DELAI_S), prevenir_interrompus()))
    except Exception as e:                                   # noqa: BLE001
        _log(f"reprise non lancée ({type(e).__name__}: {e})")


# ─── L'aiguillage ─────────────────────────────────────────────────────────
def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La réponse à un clic ou une fenêtre « outk: », ou None si ce n'est pas
    le nôtre : la route passe au module suivant."""
    p = p or {}
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if not cid.startswith(PREFIXE) or p.get("type") not in (3, 5):
        return None
    action = cid[len(PREFIXE):].split(":", 1)[0]
    t, refus = _ticket_du_clic(p)
    if t is None:
        return _ephemere(refus)
    if p.get("type") == 3:
        if action == "spf":
            return _clic_spoofer(t)
        if action == "dl":
            return _fenetre_download(t)
        if action == "dlo":
            return _clic_option(p, t, cid)
    else:
        if action == "spff":
            return _recevoir_spoofer(p, t)
        if action == "dlf":
            return _recevoir_download(p, t)
    return _ephemere("Action inconnue.")


# ─── 📤 Spoofer ───────────────────────────────────────────────────────────
def _moteur(bot=None):
    """Le module du spoofer de Yoshi. Avec le bot : celui de SON cog chargé
    (« Spoofer »), donc SON verrou _FILE — discord.py exécute l'extension dans
    un module neuf, et un « cogs.spoofer » importé d'ici avant lui (un clic
    dans les secondes du démarrage) porterait un autre verrou. None si le cog
    n'est pas chargé. Sans bot : le module en service, pour ses constantes."""
    import importlib
    if bot is None:
        return importlib.import_module("cogs.spoofer")
    try:
        cog = bot.get_cog("Spoofer")
    except Exception:                                        # noqa: BLE001
        cog = None
    if cog is None:
        return None
    nom = type(cog).__module__
    return sys.modules.get(nom) or importlib.import_module(nom)


def fenetre_spoofer(uid: str) -> Dict[str, Any]:
    """Le fichier et le nombre de versions, dans une seule fenêtre."""
    return {"type": 9, "data": {
        "custom_id": f"{PREFIXE}spff:{uid}", "title": "Spoofer",
        "components": [
            {"type": 18, "label": "Photo ou vidéo",
             "component": {"type": 19, "custom_id": "fichier", "min_values": 1,
                           "max_values": 1, "required": True}},
            {"type": 18, "label": "Combien de versions",
             "component": {"type": 3, "custom_id": "nombre", "min_values": 1, "max_values": 1,
                           "required": True,
                           "options": [{"label": str(i), "value": str(i),
                                        "default": i == QTE_DEFAUT}
                                       for i in range(1, QTE_MAX + 1)]}}]}}


def _clic_spoofer(t: Dict[str, str]) -> Dict[str, Any]:
    # rien de lent avant la fenêtre : elle doit être la toute première réponse
    if t["salon"] in _SPOOFS:
        return _ephemere(TEXTE_SPOOF_EN_COURS)
    return fenetre_spoofer(t["uid"])


def _borne(q: Any) -> int:
    try:
        q = int(q)
    except (TypeError, ValueError):
        return QTE_DEFAUT
    return q if 1 <= q <= QTE_MAX else QTE_DEFAUT


def _recevoir_spoofer(p: Dict[str, Any], t: Dict[str, str]) -> Dict[str, Any]:
    data = p.get("data") or {}
    champs = _champs(data.get("components"))
    ids = [str(x) for x in (champs.get("fichier") or [])]
    pieces = ((data.get("resolved") or {}).get("attachments") or {})
    piece = pieces.get(ids[0]) if ids else None
    if not isinstance(piece, dict) or not piece.get("url"):
        return _ephemere("📎 Aucun fichier reçu.")
    q = _borne((champs.get("nombre") or [QTE_DEFAUT])[0])
    bot = _bot_principal()
    boucle = _boucle(bot)
    moteur = _moteur(bot) if boucle is not None else None
    if moteur is None:
        # jamais hors du verrou de Yoshi : sans sa boucle ni son cog, rien
        _log("spoofer : boucle ou cog Spoofer du bot principal indisponible, rien n'est lancé")
        return _ephemere(TEXTE_INDISPONIBLE)
    nom = str(piece.get("filename") or "fichier")
    ext = Path(nom).suffix.lower()
    if ext not in moteur.VIDEOS and ext not in moteur.PHOTOS:
        return _ephemere(f"📎 {nom} : format non pris (photo ou vidéo).")
    taille = int(piece.get("size") or 0)
    if taille > moteur.TAILLE_MAX:
        return _ephemere(f"📎 {nom} : {taille // MIO} Mo, trop lourd "
                         f"(au plus {moteur.TAILLE_MAX // MIO} Mo).")
    with _VERROU:
        if t["salon"] in _SPOOFS:
            return _ephemere(TEXTE_SPOOF_EN_COURS)
        _SPOOFS.add(t["salon"])
    try:
        _noter(t["salon"], "spoofer", {"gid": t["gid"], "uid": t["uid"], "nom": nom[:120]})
        _fond(lambda: _travail_spoof(t, piece, q, boucle, moteur))
    except Exception as e:                                   # noqa: BLE001
        _SPOOFS.discard(t["salon"])
        _noter(t["salon"], "spoofer", None)
        _log(f"spoofer non lancé dans {t['salon']} ({type(e).__name__}: {e})")
        return _ephemere(TEXTE_INDISPONIBLE)
    # accusé de réception silencieux : les versions arrivent dans le ticket
    return {"type": 6}


def _telecharger(url: str, dest: Path, plafond: int) -> str:
    """La pièce jointe de la fenêtre, TOUT DE SUITE : son adresse signée
    expire. « » si tout va bien, sinon la raison à dire au VA."""
    import requests
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as r:
            if r.status_code != 200:
                return f"fichier illisible chez Discord (HTTP {r.status_code}), renvoie-le."
            n = 0
            with dest.open("wb") as f:
                for bloc in r.iter_content(1 << 20):
                    n += len(bloc)
                    if n > plafond:
                        return f"trop lourd (au plus {plafond // MIO} Mo)."
                    f.write(bloc)
    except Exception as e:                                   # noqa: BLE001
        _log(f"pièce jointe non téléchargée : {type(e).__name__}: {str(e)[:160]}")
        return "fichier non récupéré, renvoie-le."
    if n == 0:
        return "fichier vide, renvoie-le."
    return ""


async def _fabriquer(spf, src: Path, dossier: Path, q: int, video: bool, complet, force_ext,
                     plafond: int, identite: str, attente_max: float, encore_la=None):
    """Sur la boucle de Yoshi : (sorties, ratées, refus). Le contrôle de durée
    se fait AVANT le verrou, comme dans cogs/spoofer : q ré-encodages sous le
    verrou unique pour « 0/q trop lourdes », c'est la file de tous bloquée.

    Seule l'attente du verrou est bornée (refus « file »). Le délai portait
    sur toute la fabrication et l'annulait : `async with` rendait le verrou
    alors que l'encodage, dans son fil (asyncio.to_thread), continuait — le
    spoof suivant lançait son ffmpeg à côté, deux encodages sur deux cœurs, et
    le dossier était effacé sous l'orphelin."""
    if complet and await spf._trop_longue(src, plafond):
        return [], 0, "duree"
    try:
        await asyncio.wait_for(spf._FILE.acquire(), attente_max)
    except asyncio.TimeoutError:
        return [], 0, "file"
    try:
        # Le ticket a pu être supprimé pendant l'attente : rien à encoder sous
        # le verrou de tous pour un salon qui n'existe plus.
        if encore_la is not None and not await asyncio.to_thread(encore_la):
            return [], 0, "disparu"
        if video:
            sorties, ratees = await spf.versions_video(src, dossier, q, identite,
                                                       complet=complet, force_ext=force_ext)
        else:
            sorties, ratees = await spf.versions_photo(src, dossier, q)
    finally:
        spf._FILE.release()
    return list(sorties), int(ratees), ""


def _ranger_dossier(d: Path, fut) -> None:
    """Le dossier de travail part quand la fabrication a VRAIMENT fini : une
    fabrication encore en route (garde dépassée) y écrit toujours."""
    if fut is not None and not fut.done():
        fut.add_done_callback(lambda _f: shutil.rmtree(d, ignore_errors=True))
    else:
        shutil.rmtree(d, ignore_errors=True)


def _travail_spoof(t: Dict[str, str], piece: Dict[str, Any], q: int, boucle,
                   spf) -> Dict[str, Any]:
    """Télécharge, fabrique q versions (boucle de Yoshi, module `spf` de son
    cog), les poste dans le ticket. Rend le bilan (journal, tests)."""
    from cogs import telechargement as tl
    gid, salon, vau = t["gid"], t["salon"], t["uid"]
    nom = str(piece.get("filename") or "fichier")
    ext = Path(nom).suffix.lower()
    video = ext in spf.VIDEOS
    bilan: Dict[str, Any] = {"q": q, "livrees": 0, "ratees": 0, "lourdes": 0, "refus": ""}
    limite, complet, dit, fut = 0, None, False, None
    # « spoof_ » : le préfixe que cogs/spoofer balaie au démarrage si un
    # redémarrage laisse un dossier derrière lui. Pas de TemporaryDirectory :
    # il s'effaçait à la sortie du fil du site, même fabrication en route.
    d = Path(tempfile.mkdtemp(prefix="spoof_"))
    try:
        src = d / ("source" + ext)
        err = _telecharger(str(piece.get("url") or ""), src, spf.TAILLE_MAX)
        if err:
            bilan["refus"] = "telechargement"
            dit = _dire(gid, salon, f"📎 {nom} : {err}")
            return bilan
        taille = src.stat().st_size
        limite = limite_fichiers(gid)
        # En « métadonnées seules », une version pèse autant que la source :
        # une vidéo trop lourde pour repartir passe en mode complet (débit
        # borné). Un .webm / .mkv aussi : le remux en .mp4 n'est pas fiable.
        complet = True if (video and (taille > limite - tl._MARGE_ENVOI
                                      or ext in spf._A_REENCODER)) else None
        fut = asyncio.run_coroutine_threadsafe(
            _fabriquer(spf, src, d, q, video, complet,
                       ".mp4" if ext in spf._A_REENCODER else None,
                       limite - tl._MARGE_ENVOI, f"spoofer {t.get('nom') or t['qui']}",
                       FILE_MAX_S, lambda: _ticket_existe(gid, salon)),
            boucle)
        try:
            sorties, ratees, refus = fut.result(timeout=FILE_MAX_S + GARDE_FABRICATION_S)
        except concurrent.futures.TimeoutError:
            # JAMAIS fut.cancel() : le verrou serait rendu sous un ffmpeg qui
            # tourne encore. Le dossier attend la fin réelle (_ranger_dossier).
            bilan.update(refus="bloque", ratees=q)
            _log(f"spoofer {nom} dans {salon} : toujours en fabrication après "
                 f"{(FILE_MAX_S + GARDE_FABRICATION_S) // 60} min, on cesse d'attendre")
            dit = _dire(gid, salon, f"🎭 {nom} : bloqué, renvoie-le plus tard.")
            return bilan
        if refus == "duree":
            bilan.update(refus="duree", lourdes=q)
            dit = _dire(gid, salon, f"📎 {nom} : trop longue pour tenir sur Discord une "
                                    "fois re-encodée — envoie-la plus courte.")
            return bilan
        if refus == "file":
            # rien n'a raté : c'est la file qui était trop longue
            bilan["refus"] = "file"
            dit = _dire(gid, salon, f"⏳ {nom} : trop de spoofs en attente, renvoie-le plus tard.")
            return bilan
        if refus == "disparu":
            bilan["refus"] = "disparu"
            _log(f"spoofer {nom} : ticket {salon} supprimé pendant l'attente, rien fabriqué")
            return bilan
        bilan["ratees"] = ratees
        lots, lourds = tl.repartir(sorties, limite)
        bilan["lourdes"] = len(lourds)
        for i, lot in enumerate(lots):
            code, rep = poster(gid, salon, "", [(Path(x).name, Path(x).read_bytes()) for x in lot])
            if _ticket_disparu(code, rep):
                # ticket supprimé : les lots suivants iraient tous au même 404
                bilan["refus"] = "disparu"
                _log(f"spoofer {nom} : ticket {salon} supprimé pendant la livraison, arrêtée "
                     f"({bilan['livrees']}/{q} livrée(s))")
                return bilan
            dit = True
            if code in (200, 201):
                bilan["livrees"] += len(lot)
            elif _trop_lourd(code, rep):
                bilan["lourdes"] += len(lot)
            else:
                bilan["ratees"] += len(lot)
                _log(f"spoofer : envoi refusé dans {salon} (HTTP {code}) {str(rep)[:120]}")
            if i < len(lots) - 1:
                _dormir(PAUSE_ENVOI)
    except Exception as e:                                   # noqa: BLE001
        _log(f"spoofer {nom} dans {salon} : {type(e).__name__}: {e}")
        bilan["ratees"] = max(0, q - bilan["livrees"] - bilan["lourdes"])
    finally:
        try:
            if bilan["livrees"] < q and bilan["refus"] not in _REFUS_SANS_BILAN:
                morceaux = []
                if bilan["ratees"]:
                    morceaux.append(f"{bilan['ratees']} ratée(s)")
                if bilan["lourdes"]:
                    morceaux.append(f"{bilan['lourdes']} trop lourde(s) pour Discord")
                dit = _dire(gid, salon, f"🎭 {nom} : {bilan['livrees']}/{q}"
                            + (" — " + ", ".join(morceaux) if morceaux else "")) or dit
            if dit and bilan["refus"] != "disparu":
                _ramener_menu(gid, vau, salon)
        finally:
            _ranger_dossier(d, fut)
            with _VERROU:
                _SPOOFS.discard(salon)
            _noter(salon, "spoofer", None)
            _log(f"spoofer {nom} ({'video' if video else 'photo'}, ticket {salon}, limite "
                 f"{limite // MIO} Mio{', complet' if complet else ''}) : {bilan}")
    return bilan


# ─── ⬇️ Download ──────────────────────────────────────────────────────────
#: Les choix, rangée par rangée, comme le panneau -download de Youl4b.
_RANGEES_OPTIONS = ((("tout", 3), ("pp", 1), ("bio", 1)),
                    (("photos", 1), ("reels", 1), ("top", 2)))


def _fenetre_download(t: Dict[str, str]) -> Dict[str, Any]:
    return {"type": 9, "data": {
        "custom_id": f"{PREFIXE}dlf:{t['uid']}", "title": "Quel compte ?",
        "components": [
            {"type": 18, "label": "Pseudo Instagram",
             "component": {"type": 4, "custom_id": "pseudo", "style": 1, "required": True,
                           "max_length": 120,
                           "placeholder": "sky.ards  ou  https://instagram.com/sky.ards"}},
            {"type": 18, "label": f"Combien au maximum (défaut {COMBIEN_DEFAUT})",
             "component": {"type": 4, "custom_id": "combien", "style": 1, "required": False,
                           "max_length": 3, "placeholder": str(COMBIEN_DEFAUT)}}]}}


def vue_options(pseudo: str, n: int) -> List[Dict[str, Any]]:
    from cogs import telechargement as tl
    return [{"type": 1, "components": [
        {"type": 2, "style": style, "label": tl.OPTIONS[cle][0],
         "custom_id": f"{PREFIXE}dlo:{cle}:{n}:{pseudo}"} for cle, style in rangee]}
        for rangee in _RANGEES_OPTIONS]


def _recevoir_download(p: Dict[str, Any], t: Dict[str, str]) -> Dict[str, Any]:
    from cogs import telechargement as tl
    champs = _champs((p.get("data") or {}).get("components"))
    pseudo, n, refus = tl.lire_compte(champs.get("pseudo") or "", champs.get("combien") or "")
    if refus:
        return _ephemere(refus)
    # le choix seul est privé : les fichiers partiront dans le ticket
    return _ephemere(f"⬇️ **@{pseudo}** · {n}", vue_options(pseudo, n))


def _clic_option(p: Dict[str, Any], t: Dict[str, str], cid: str) -> Dict[str, Any]:
    from cogs import telechargement as tl
    morceaux = cid[len(PREFIXE):].split(":", 3)
    if len(morceaux) != 4 or morceaux[1] not in tl.OPTIONS:
        return _ephemere("Action inconnue.")
    _a, cle, n, pseudo = morceaux
    try:
        n = max(1, min(int(n), 200))
    except ValueError:
        n = COMBIEN_DEFAUT
    if not tl._PSEUDO_OK.match(pseudo):
        return _ephemere(f"« {pseudo} » ne ressemble pas à un pseudo Instagram.")
    bot = _bot_principal()
    boucle = _boucle(bot)
    cog = bot.get_cog("Telechargement") if boucle is not None else None
    if cog is None:
        _log("download : bot principal ou cog Telechargement indisponible, rien n'est lancé")
        return _ephemere(TEXTE_INDISPONIBLE)
    vau = int(t["uid"])
    occupe = _reserver(boucle, cog, vau, pseudo)
    if occupe is None:
        _log("download : la boucle du bot principal n'a pas réservé à temps, rien n'est lancé")
        return _ephemere(TEXTE_INDISPONIBLE)
    if occupe:
        # la réponse AU clic : en suivi (webhook) après l'accusé, le refus
        # partait parfois avant que Discord ait reçu l'accusé, qui le rejetait
        # (webhook inconnu) — le VA ne voyait rien
        return _ephemere(occupe)
    try:
        fut = asyncio.run_coroutine_threadsafe(_travail_download(bot, cog, t, pseudo, n, cle), boucle)
    except Exception as e:                                   # noqa: BLE001
        _liberer(boucle, cog, vau, pseudo)
        _log(f"download @{pseudo} non lancé dans {t['salon']} ({type(e).__name__}: {e})")
        return _ephemere(TEXTE_INDISPONIBLE)
    fut.add_done_callback(_journaliser_fin(f"download @{pseudo} dans {t['salon']}"))
    # accusé silencieux : les choix restent, les fichiers arrivent dans le ticket
    return {"type": 6}


def _reserver(boucle, cog, uid: int, pseudo: str) -> Optional[str]:
    """Le verrou du VA et du compte (Telechargement.reserver, partagé avec
    Youl4b), pris SUR la boucle de Yoshi où il vit — reserver est synchrone,
    rien ne passe entre le test et la prise — mais PENDANT le clic, pour que
    le refus soit la réponse au clic. Rend "" (réservé : _travail_download
    libère), la phrase de refus, ou None (boucle trop lente : rien de pris)."""
    etat = {"abandon": False, "fait": False, "rep": ""}
    garde = threading.Lock()

    async def _sur_la_boucle():
        # Sous `garde` : un abandon (délai dépassé côté site) et la prise ne
        # se croisent pas — sinon une réservation tardive restait prise sans
        # personne pour la libérer, et le VA ne pouvait plus rien télécharger.
        with garde:
            if etat["abandon"]:
                return
            etat["rep"] = cog.reserver(uid, pseudo)
            etat["fait"] = True

    try:
        fut = asyncio.run_coroutine_threadsafe(_sur_la_boucle(), boucle)
        fut.result(timeout=RESERVATION_MAX_S)
    except Exception:                                        # noqa: BLE001
        pass                    # boucle fermée, délai ou erreur : tranché ci-dessous
    with garde:
        if not etat["fait"]:
            etat["abandon"] = True
            return None
        return str(etat["rep"] or "")


def _liberer(boucle, cog, uid: int, pseudo: str) -> None:
    """Rend une réservation que rien n'a lancée, sur la boucle où vit le
    verrou ; boucle fermée : plus personne ne s'y croise."""
    try:
        boucle.call_soon_threadsafe(cog.liberer, uid, pseudo)
    except Exception:                                        # noqa: BLE001
        cog.liberer(uid, pseudo)


class _SalonTicket:
    """Le ticket tel que cogs/telechargement l'attend d'un salon discord.py
    (send, name, guild.filesize_limit), posté par REST avec Wario : Yoshi, qui
    fait tourner le téléchargement, n'est pas sur TRUST INSTAGRAM."""

    def __init__(self, gid: str, salon: str, limite: int):
        self.gid, self.id = str(gid), int(salon)
        self.name = f"ticket {salon}"
        self.mention = f"<#{salon}>"
        self.guild = SimpleNamespace(id=int(gid), name="TRUST INSTAGRAM",
                                     filesize_limit=int(limite), text_channels=[])
        #: la tâche de Telechargement.livrer, annulée si le ticket disparaît
        self.tache: Optional[asyncio.Task] = None
        self.disparu = False

    async def send(self, content=None, files=None, **_kw):
        import discord
        if self.disparu:
            # plus aucun POST vers un salon supprimé (l'annulation de la tâche
            # prend effet à son prochain await)
            raise discord.HTTPException(SimpleNamespace(status=404, reason=""),
                                        {"code": 10003, "message": "Unknown Channel"})
        fichiers = [(f.filename, f.fp.read()) for f in (files or [])]
        code, rep = await asyncio.to_thread(poster, self.gid, str(self.id), content or "", fichiers)
        if code not in (200, 201):
            if _ticket_disparu(code, rep) and not self.disparu:
                # _poster avale l'erreur et livrer continuait : chaque média
                # téléchargé et mis en cache, deux POST en 404 par
                # publication, et les verrous du VA et du compte (partagé avec
                # Youl4b) pris jusqu'au bout, pour un ticket supprimé
                self.disparu = True
                _log(f"download : ticket {self.id} supprimé pendant la livraison, arrêtée")
                if self.tache is not None:
                    self.tache.cancel()
            # _poster (cogs/telechargement) attend l'exception de discord.py :
            # un 413 y devient « trop lourd », le reste un envoi refusé — et la
            # livraison continue
            raise discord.HTTPException(SimpleNamespace(status=code, reason=""),
                                        rep if isinstance(rep, (dict, str)) else str(rep))
        return rep


async def _travail_download(bot, cog, t: Dict[str, str], pseudo: str, n: int, cle: str) -> None:
    """Sur la boucle de Yoshi : la demande entière, par Telechargement.livrer.
    La réservation est déjà prise (_reserver, pendant le clic) : on la rend."""
    from cogs import telechargement as tl
    gid, salon, vau = t["gid"], t["salon"], t["uid"]
    ticket: Optional[_SalonTicket] = None
    try:
        await asyncio.to_thread(_noter, salon, "download", {"gid": gid, "uid": vau, "nom": pseudo})
        limite = await asyncio.to_thread(limite_fichiers, gid)
        archive = tl.salon_all_download(bot.get_guild(tl.SERVEUR_ID)
                                        if hasattr(bot, "get_guild") else None)
        court = tl.OPTIONS[cle][0]
        ticket = _SalonTicket(gid, salon, limite)
        ticket.tache = asyncio.ensure_future(cog.livrer(
            ticket, pseudo, n,
            avatar=cle in ("tout", "pp"), bio=cle in ("tout", "bio"),
            photos=cle in ("tout", "photos"), reels=cle in ("tout", "reels", "top"),
            par_vues=(cle == "top"), demandeur=SimpleNamespace(id=int(t["qui"])),
            # l'archive de Youl4b dit d'où vient la demande
            option=f"{court} · TRUST INSTAGRAM", archive=archive))
        try:
            await ticket.tache
        except asyncio.CancelledError:
            if not ticket.disparu:
                raise                       # c'est nous qui sommes annulés (arrêt du bot)
    finally:
        cog.liberer(int(vau), pseudo)
        await asyncio.to_thread(_noter, salon, "download", None)
        if ticket is None or not ticket.disparu:
            await asyncio.to_thread(_ramener_menu, gid, vau, salon)
