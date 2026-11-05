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
    l'enterraient jusqu'au tour de l'heure. Une livraison à la fois par
    ticket, 🎬 Contenu compris (verrou_livraison) : ce que Youl4b rangeait
    dans deux salons tombe ici dans le même.

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
#: Les serveurs aux outils en salons communs (propriétaire, 04/11/2026, devant
#: les 🧰 OUTILS de YouCham : « j'aimerais bien que ça se passe comme ça
#: maintenant pour Instagram aussi ») : un clic hors d'un ticket sert le
#: ticket DU CLIQUEUR (_ticket_du_clic). Les boutons du ticket restent.
SALONS_COMMUNS = {AGENCY_IG_ID}
TEXTE_SANS_TICKET = "Tu n'as pas de ticket ici : rien ne peut t'être livré."
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
#: {ticket: asyncio.Lock}, sur la boucle de Yoshi : UNE livraison à la fois
#: par ticket, tous outils confondus (🎬 contenu_tickets, ⬇️, 📤). Sur Youl4b,
#: contenu et téléchargements partaient dans deux salons (-content,
#: -download) ; ici tout tombe dans le même ticket, et un reel téléchargé
#: s'intercalait entre une carte 🎬 et sa description — collée ensuite sous
#: le mauvais média, sur téléphone.
_LIVRAISONS: Dict[str, asyncio.Lock] = {}
#: Ce qu'un spoof prêt attend son tour dans le ticket (fil du site). Au-delà,
#: il est posté quand même — une livraison bloquée ne doit pas le perdre — et
#: le journal le dit.
ATTENTE_TICKET_S = 30 * 60


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


def _ticket_du_clic(p: Dict[str, Any], serveurs=None) -> Tuple[Optional[Dict[str, str]], str]:
    """({gid, salon, uid (le VA du ticket), qui (le cliqueur)}, "") ou (None,
    le refus). Le VA du ticket ou un manager/helper, comme 💳 et 📈 : un autre
    VA ne se sert pas des outils d'un ticket qui n'est pas le sien.
    `serveurs` : ceux du bouton cliqué (🎬 Contenu a les siens,
    contenu_tickets) ; SERVEURS par défaut. Une seule règle pour tous les
    boutons du ticket : deux copies divergeraient au premier correctif."""
    gid = str(p.get("guild_id") or "")
    if gid not in (SERVEURS if serveurs is None else serveurs):
        return None, "Ce bouton ne sert pas sur ce serveur."
    salon = str(p.get("channel_id") or "")
    tickets = _tickets(gid)
    vau = tickets.get(salon)
    membre = p.get("member") or {}
    qui = str(((membre.get("user") or {}).get("id")) or "")
    if not vau:
        if gid in SALONS_COMMUNS and qui.isdigit():
            # un salon commun de 🧰 OUTILS (04/11/2026), ou l'éphémère qu'il a
            # ouvert : c'est le ticket DU CLIQUEUR qui reçoit, jamais le salon
            # commun (tout le monde y verrait ses fichiers)
            sien = next((s for s, u in sorted(tickets.items()) if u == qui), "")
            if not sien:
                return None, TEXTE_SANS_TICKET
            nom = str(((membre.get("user") or {}).get("username")) or qui)
            return {"gid": gid, "salon": sien, "uid": qui, "qui": qui, "nom": nom,
                    "commun": "1"}, ""
        # le menu privé du staff (menu_prive), ou un vieux message ailleurs
        return None, TEXTE_HORS_TICKET
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


def verrou_livraison(salon: str) -> asyncio.Lock:
    """Le verrou de livraison du ticket (_LIVRAISONS). SUR la boucle de Yoshi
    seulement : un asyncio.Lock appartient à la boucle qui l'attend."""
    return _LIVRAISONS.setdefault(str(salon), asyncio.Lock())


def ticket_occupe(salon: str) -> bool:
    """Une livraison tient-elle le ticket ? Lecture seule, depuis le site."""
    v = _LIVRAISONS.get(str(salon))
    return bool(v is not None and v.locked())


def _prendre_ticket(boucle, salon: str, attente_max: Optional[float] = None):
    """Depuis un fil du site : attend que le ticket soit libre et le prend
    (verrou_livraison, sur la boucle de Yoshi). Rend le verrou, à rendre par
    _rendre_ticket, ou None : boucle arrêtée, ou attente dépassée — on poste
    alors sans lui, et le journal le dit.

    Comme _reserver : sous `garde`, un abandon (attente dépassée) et la prise
    ne se croisent pas. Sans ça, une prise arrivée juste après l'abandon
    restait tenue sans personne pour la rendre, et le ticket ne recevait plus
    rien jusqu'au redémarrage."""
    etat: Dict[str, Any] = {"abandon": False, "pris": None}
    garde = threading.Lock()

    async def _prendre():
        v = verrou_livraison(salon)
        await v.acquire()
        with garde:
            if etat["abandon"]:
                v.release()
                return
            etat["pris"] = v

    try:
        fut = asyncio.run_coroutine_threadsafe(_prendre(), boucle)
    except Exception as e:                                   # noqa: BLE001
        _log(f"ticket {salon} : tour de livraison non pris ({type(e).__name__}: {e}), envoi direct")
        return None
    try:
        fut.result(timeout=ATTENTE_TICKET_S if attente_max is None else attente_max)
    except Exception:                                        # noqa: BLE001
        pass                    # délai, boucle arrêtée : tranché ci-dessous
    with garde:
        if etat["pris"] is None:
            etat["abandon"] = True
            fut.cancel()
            _log(f"ticket {salon} : toujours occupé par une autre livraison, envoi sans attendre")
        return etat["pris"]


def _rendre_ticket(boucle, verrou) -> None:
    if verrou is None:
        return
    try:
        boucle.call_soon_threadsafe(verrou.release)
    except RuntimeError:
        pass                    # boucle fermée : plus personne ne l'attend


class _TourDuTicket:
    """Le tour de livraison d'un travail du site (le spoofer) : pris au
    PREMIER message, rendu à la fin. Jamais pendant la fabrication : un spoof
    en file derrière le verrou de tous aurait bloqué les 🎬 du ticket."""

    def __init__(self, boucle, salon: str):
        self.boucle, self.salon = boucle, str(salon)
        self.verrou = None
        self.demande = False

    def prendre(self) -> None:
        if not self.demande and self.boucle is not None:
            self.demande = True
            self.verrou = _prendre_ticket(self.boucle, self.salon)

    def rendre(self) -> None:
        _rendre_ticket(self.boucle, self.verrou)
        self.verrou = None


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


def _noter(salon: str, quoi: str, info: Optional[Dict[str, Any]], numero: str = "") -> None:
    """Marque (ou efface) le travail `quoi` du ticket `salon`. Une marque par
    outil : un spoof et un téléchargement tournent ensemble dans un ticket, la
    fin de l'un effaçait sinon la marque de l'autre. `numero` : une marque
    par livraison quand l'outil en met plusieurs en file (🎬) — une seule
    clé n'en gardait qu'une, les autres se perdaient sans un mot au
    redémarrage."""
    cle = f"{salon}:{quoi}" + (f":{numero}" if numero else "")
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
    annonces: List[Tuple[str, str, str, str]] = []          # (gid, salon, uid, texte)
    contenus: Dict[str, List[Dict[str, Any]]] = {}
    for cle, i in coupes.items():
        salon = str(i.get("salon") or cle.split(":", 1)[0])
        gid, uid = str(i.get("gid") or AGENCY_IG_ID), str(i.get("uid") or "")
        if i.get("quoi") == "contenu":
            # 🎬 (contenu_tickets) : regroupées par ticket, ci-dessous
            contenus.setdefault(salon, []).append(dict(i, salon=salon, gid=gid, uid=uid))
            continue
        if i.get("quoi") == "download":
            texte = f"⬇️ @{i.get('nom') or '?'} : interrompu par un redémarrage, relance-le."
        else:
            texte = f"🎭 {i.get('nom') or 'fichier'} : interrompu par un redémarrage, renvoie-le."
        annonces.append((gid, salon, uid, texte))
    for salon, liste in contenus.items():
        # Celle en cours ET celles en file derrière elle, dans l'ordre des
        # clics, en un message : le VA sait tout ce qu'il doit relancer.
        liste.sort(key=lambda x: (float(x.get("ordre") or x.get("t") or 0), str(x.get("nom") or "")))
        noms = ", ".join(str(x.get("nom") or "Contenu") for x in liste)
        texte = (f"🎬 {noms} : interrompu par un redémarrage, relance-le." if len(liste) == 1
                 else f"🎬 {noms} : interrompus par un redémarrage, relance-les.")
        annonces.append((liste[0]["gid"], salon, liste[0]["uid"], texte[:2000]))
    n = 0
    for gid, salon, uid, texte in annonces:
        if _dire(gid, salon, texte):
            n += 1
            if uid:
                _ramener_menu(gid, uid, salon)
    if coupes:
        _log(f"reprise : {n}/{len(annonces)} annonce(s) postée(s) pour {len(coupes)} travail(s) "
             "interrompu(s)")
    return n


def demarrer() -> None:
    """Au démarrage du site (web_upload) : une fois par processus."""
    if _DEMARRE[0]:
        return
    _DEMARRE[0] = True
    try:
        _fond(_au_demarrage)
    except Exception as e:                                   # noqa: BLE001
        _log(f"reprise non lancée ({type(e).__name__}: {e})")


def _au_demarrage() -> None:
    """Les travaux interrompus annoncés, puis les panneaux des salons communs
    reposés s'ils ont disparu : l'un qui lève n'empêche pas l'autre."""
    _dormir(REPRISE_DELAI_S)
    try:
        prevenir_interrompus()
    except Exception as e:                                   # noqa: BLE001
        _log(f"reprise : {type(e).__name__}: {e}")
    for g in sorted(SALONS_COMMUNS):
        assurer_panneaux(g)


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
    if t is None and action == "menu" and refus == TEXTE_SANS_TICKET:
        # 📋 sans ticket (le staff, un VA pas encore servi) : son menu quand
        # même, sans 🎬 (qui livre dans un ticket) — l'ancien « Afficher le
        # menu » lui donnait sa rangée en privé (23/10 : « un menu pour les
        # boss, les managers, pour tout le monde »)
        return _menu_commun({"gid": str(p.get("guild_id") or ""), "uid": str(
            (((p.get("member") or {}).get("user")) or {}).get("id") or ""), "sans_ticket": "1"})
    if t is None:
        return _ephemere(refus)
    rep = None
    if p.get("type") == 3:
        if action == "menu":
            return _menu_commun(t)
        if action == "spf":
            rep = _clic_spoofer(t)
        elif action == "dl":
            rep = _fenetre_download(t)
        elif action == "dlo":
            rep = _clic_option(p, t, cid)
    else:
        if action == "spff":
            rep = _recevoir_spoofer(p, t)
        elif action == "dlf":
            rep = _recevoir_download(p, t)
    if rep is None:
        return _ephemere("Action inconnue.")
    if t.get("commun") and rep == {"type": 6}:
        # lancé d'un salon commun : l'accusé silencieux du ticket laissait le
        # VA sans savoir où regarder
        quoi = "tes versions arrivent" if action == "spff" else "ça arrive"
        return _ephemere(f"{'📤' if action == 'spff' else '⬇️'} C'est parti : {quoi} dans <#{t['salon']}>.")
    return rep


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
    # Les messages attendent leur tour dans le ticket (une 🎬 ou un ⬇️ en
    # cours) : jamais entre une carte et le texte à copier qui la suit.
    tour = _TourDuTicket(boucle, salon)

    def dire(texte: str) -> bool:
        tour.prendre()
        return _dire(gid, salon, texte)
    # « spoof_ » : le préfixe que cogs/spoofer balaie au démarrage si un
    # redémarrage laisse un dossier derrière lui. Pas de TemporaryDirectory :
    # il s'effaçait à la sortie du fil du site, même fabrication en route.
    d = Path(tempfile.mkdtemp(prefix="spoof_"))
    try:
        src = d / ("source" + ext)
        err = _telecharger(str(piece.get("url") or ""), src, spf.TAILLE_MAX)
        if err:
            bilan["refus"] = "telechargement"
            dit = dire(f"📎 {nom} : {err}")
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
            dit = dire(f"🎭 {nom} : bloqué, renvoie-le plus tard.")
            return bilan
        if refus == "duree":
            bilan.update(refus="duree", lourdes=q)
            dit = dire(f"📎 {nom} : trop longue pour tenir sur Discord une "
                                    "fois re-encodée — envoie-la plus courte.")
            return bilan
        if refus == "file":
            # rien n'a raté : c'est la file qui était trop longue
            bilan["refus"] = "file"
            dit = dire(f"⏳ {nom} : trop de spoofs en attente, renvoie-le plus tard.")
            return bilan
        if refus == "disparu":
            bilan["refus"] = "disparu"
            _log(f"spoofer {nom} : ticket {salon} supprimé pendant l'attente, rien fabriqué")
            return bilan
        bilan["ratees"] = ratees
        lots, lourds = tl.repartir(sorties, limite)
        bilan["lourdes"] = len(lourds)
        for i, lot in enumerate(lots):
            tour.prendre()
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
                dit = dire(f"🎭 {nom} : {bilan['livrees']}/{q}"
                           + (" — " + ", ".join(morceaux) if morceaux else "")) or dit
            if dit and bilan["refus"] != "disparu":
                _ramener_menu(gid, vau, salon)
        finally:
            tour.rendre()
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
    menu_pose = False
    try:
        await asyncio.to_thread(_noter, salon, "download", {"gid": gid, "uid": vau, "nom": pseudo})
        limite = await asyncio.to_thread(limite_fichiers, gid)
        archive = tl.salon_all_download(bot.get_guild(tl.SERVEUR_ID)
                                        if hasattr(bot, "get_guild") else None)
        court = tl.OPTIONS[cle][0]
        ticket = _SalonTicket(gid, salon, limite)
        # Son tour dans le ticket (verrou_livraison) : une 🎬 en cours y
        # aurait vu ses textes à copier séparés de leur carte par nos reels.
        async with verrou_livraison(salon):
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
                    raise                   # c'est nous qui sommes annulés (arrêt du bot)
            # le menu en dernier AVANT de rendre le ticket : la livraison
            # suivante ne le verra pas s'intercaler entre ses messages
            if not ticket.disparu:
                await asyncio.to_thread(_ramener_menu, gid, vau, salon)
                menu_pose = True
    finally:
        cog.liberer(int(vau), pseudo)
        await asyncio.to_thread(_noter, salon, "download", None)
        if not menu_pose and (ticket is None or not ticket.disparu):
            await asyncio.to_thread(_ramener_menu, gid, vau, salon)


# ─── 🧰 Les salons communs de TRUST INSTAGRAM (04/11/2026) ────────────────
# Propriétaire, devant les 🧰 OUTILS de YouCham (📋 menu, 📤 spoofer,
# ⬇️ download, 📱 numéro) : « j'aimerais bien que ça se passe comme ça
# maintenant pour Instagram aussi. Tu peux garder ce qu'il y a dans le
# ticket, rajoute ça », puis « intègre déjà les outils, soit le menu, le
# spoofer, le download, le numéro ». Quand il dira « c'est bon », les boutons
# du ticket pourront partir ; d'ici là ils restent.
#  - Un panneau par salon, UN bouton, sans texte (le propriétaire déteste les
#    notices), posé par Wario en REST. Le clic arrive ici comme ceux du ticket,
#    et _ticket_du_clic sert le ticket du cliqueur : rien n'est jamais livré
#    dans le salon commun, que tout le monde lit.
#  - 📋・menu ouvre le menu du cliqueur en éphémère, en blocs comme celui de
#    Twitter (tickets_discord.menu_ephemere).
#  - 📱・numéro est à Rem (numeros.py, carte éphémère) : son panneau n'est pas
#    d'ici.
#  - Les salons sont créés une fois (installer_salons, lancé à la main) ; le
#    démarrage ne fait que reposer un panneau disparu (assurer_panneaux). Un
#    salon supprimé à la main n'est jamais refait.
V2 = 1 << 15
SALONS_FICHIER = DATA_DIR / "outils_salons.json"
#: La catégorie des outils (son nom sans décor), celle où vit déjà 📱・numéro.
CATEGORIE_OUTILS = "outils instagram"
#: (clé, nom à la création, (libellé, emoji, custom_id) du bouton). L'ordre est
#: celui des salons en tête de la catégorie, comme sur YouCham ; 📱・numéro
#: ferme la marche.
PANNEAUX = (("menu", "📋・menu", ("Ouvrir mon menu", "📋", f"{PREFIXE}menu")),
            ("spoofer", "📤・spoofer", ("Spoofer", "📤", f"{PREFIXE}spf:commun")),
            ("download", "⬇️・download", ("Download", "⬇️", f"{PREFIXE}dl:commun")))
CLE_NUMERO = "numero"
#: Les droits d'un bot dans un salon où personne d'autre n'écrit : voir,
#: écrire, intégrer, joindre, historique.
DROITS_BOT = 1024 | 2048 | 16384 | 32768 | 65536


def _menu_commun(t: Dict[str, str]) -> Dict[str, Any]:
    """📋 Ouvrir mon menu : le menu du VA (celui du ticket quand on y clique),
    en éphémère. Une panne ne doit jamais laisser le clic sans réponse."""
    import tickets_discord as tk
    try:
        return tk.menu_ephemere(t["gid"], t["uid"], avec_contenu=not t.get("sans_ticket"))
    except Exception as e:                                   # noqa: BLE001
        _log(f"menu commun de {t.get('uid')} : {type(e).__name__}: {e}")
        return _ephemere(TEXTE_INDISPONIBLE)


def corps_panneau(cle: str) -> Dict[str, Any]:
    libelle, emoji, cid = {c: b for c, _n, b in PANNEAUX}[cle]
    return {"flags": V2, "allowed_mentions": {"parse": []},
            "components": [{"type": 1, "components": [
                {"type": 2, "style": 1, "label": libelle, "emoji": {"name": emoji},
                 "custom_id": cid}]}]}


def _cle_salon(nom: Any) -> str:
    """« 📱・numéro » → « numero » : le nom sans décor ni accent, la partie
    après « ・ » s'il y en a une (un salon renommé à la main reste reconnu)."""
    import re
    import unicodedata
    n = str(nom or "")
    if "・" in n:
        n = n.split("・", 1)[1]
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def _ids_message(m: Any) -> set:
    out, pile = set(), list((m or {}).get("components") or []) if isinstance(m, dict) else []
    while pile:
        c = pile.pop()
        if not isinstance(c, dict):
            continue
        if c.get("custom_id"):
            out.add(str(c["custom_id"]))
        pile += list(c.get("components") or [])
        if isinstance(c.get("accessory"), dict):
            pile.append(c["accessory"])
    return out


def _etat_salons() -> Dict[str, Any]:
    d = safe_json.load(SALONS_FICHIER, default={}) or {}
    return d if isinstance(d, dict) else {}


def _noter_salon(gid: str, cle: str, **champs) -> None:
    with _VERROU:
        d = _etat_salons()
        f = d.setdefault(str(gid), {}).setdefault(cle, {})
        f.update({k: str(v) for k, v in champs.items()})
        if not safe_json.write(SALONS_FICHIER, d):
            _log(f"salons communs : fiche {cle} non écrite ({SALONS_FICHIER})")


def _salon_inconnu(code: int, rep: Any) -> bool:
    return isinstance(rep, dict) and rep.get("code") == 10003


#: Ce qui a déjà été dit au journal (salon supprimé, rien d'installé, ancien
#: panneau encore là) : une ligne, pas une par démarrage.
_DITS: set = set()
#: L'ancien panneau de 📋・menu (numeros_x_discord, « 📋 Afficher le menu »).
ANCIEN_MENU = "numx:menu"


def _dire_une_fois(cle: Any, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        _log(texte)


def _categorie_outils(gid: str) -> str:
    """Le nom (sans décor) de la catégorie des outils de ce serveur."""
    return CATEGORIES_OUTILS.get(str(gid), CATEGORIE_OUTILS)


def _lire_categorie(gid: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """(🧰 OUTILS <serveur>, ses salons texte dans leur ordre, tous les salons
    du serveur, raison d'un échec)."""
    code, salons = _api("GET", f"/guilds/{gid}/channels", gid=gid)
    if code != 200 or not isinstance(salons, list):
        return None, [], [], f"salons illisibles (HTTP {code})"
    cat = next((c for c in salons if c.get("type") == 4
                and _cle_salon(c.get("name")).endswith(_categorie_outils(gid))), None)
    if cat is None:
        return None, [], salons, f"catégorie 🧰 {_categorie_outils(gid).upper()} introuvable"
    dedans = sorted([c for c in salons if c.get("parent_id") == cat["id"] and c.get("type") == 0],
                    key=lambda c: (int(c.get("position") or 0), str(c["id"]).zfill(20)))
    return cat, dedans, salons, ""


def _salons_par_cle(gid: str, dedans: List[Dict[str, Any]], tous: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{clé: salon} : par l'id noté d'abord (un salon renommé, même hors de la
    catégorie, reste le sien : sinon une relance en recréait un second), par
    son nom dans la catégorie ensuite."""
    fiches = _etat_salons().get(str(gid)) or {}
    par_id = {str(c.get("id")): c for c in tous}
    # {clé : le nom sans décor qui la reconnaît} — sur Twitter, « adresse »
    # est le salon 📧・adresse-outlook (« adresse outlook »)
    noms = {cle: _cle_salon(nom) for cle, nom, _m, _c in _panneaux(gid)}
    if str(gid) == AGENCY_IG_ID:
        noms.setdefault(CLE_NUMERO, CLE_NUMERO)
    out: Dict[str, Dict[str, Any]] = {}
    for cle in noms:
        c = par_id.get(str((fiches.get(cle) or {}).get("salon") or ""))
        if c is not None and c.get("type") == 0:
            out[cle] = c
    pris = {str(c["id"]) for c in out.values()}
    par_nom = {v: k for k, v in noms.items()}
    for c in dedans:
        k = par_nom.get(_cle_salon(c.get("name")))
        if k and k not in out and str(c["id"]) not in pris:
            out[k] = c
            pris.add(str(c["id"]))
    return out


def assurer_panneaux(gid: str, sauf: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """Le panneau de chaque salon commun, reposé s'il a disparu. Trouvé par
    son id, sinon en relisant le salon ; Discord injoignable : rien n'est
    reposté — un second panneau vaut moins qu'un passage raté. Rien tant que
    installer_salons n'est pas passé (fiche « installe ») : avant, 📋・menu
    porte encore l'ancien panneau, et un second y serait posé à côté. Une
    fiche sans l'id d'un salon (data/ refait) : retrouvé par son nom, noté.
    `sauf` : les clés à ne pas poser. Rend {ok, poses, rates, supprimes}.
    Ne lève pas."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"ok": [], "poses": [], "rates": [], "supprimes": []}
    fiches = _etat_salons().get(gid) or {}
    if not fiches.get("installe"):
        _dire_une_fois((gid, "pas installe"), f"salons communs {gid} : pas installés "
                       "(outils_tickets.installer_salons), aucun panneau posé")
        return bilan
    panneaux = _panneaux(gid)
    try:
        if any(not str((fiches.get(cle) or {}).get("salon") or "") for cle, _n, _m, _c in panneaux):
            _cat, dedans, tous, raison = _lire_categorie(gid)
            if raison:
                bilan["rates"].append(raison)
            a_noter = {c for c, _n, _m, _f in panneaux}       # 📱 de Rem (Instagram) : pas d'ici
            for cle, c in _salons_par_cle(gid, dedans, tous).items():
                if cle in a_noter and not str((fiches.get(cle) or {}).get("salon") or ""):
                    _noter_salon(gid, cle, salon=c["id"])
                    _log(f"salons communs {gid} : {cle} retrouvé par son nom ({c.get('name')})")
            fiches = _etat_salons().get(gid) or {}
    except Exception as e:                                   # noqa: BLE001
        bilan["rates"].append(f"salons ({type(e).__name__}: {e})")
    for cle, _nom, cid, corps in panneaux:
        f = fiches.get(cle) or {}
        salon, mid = str(f.get("salon") or ""), str(f.get("panneau") or "")
        if not salon:
            bilan["rates"].append(f"{cle} (salon introuvable)")
            continue
        try:
            if mid:
                code, m = _api("GET", f"/channels/{salon}/messages/{mid}", gid=gid)
                if code == 200 and cid in _ids_message(m):
                    bilan["ok"].append(cle)
                    continue
                if _salon_inconnu(code, m):
                    bilan["supprimes"].append(cle)
                    continue
                if code != 404:
                    bilan["rates"].append(f"{cle} (HTTP {code})")
                    continue
            code, ms = _api("GET", f"/channels/{salon}/messages?limit=50", gid=gid)
            if _salon_inconnu(code, ms):
                bilan["supprimes"].append(cle)
                continue
            if code != 200 or not isinstance(ms, list):
                bilan["rates"].append(f"{cle} (HTTP {code})")
                continue
            poses = [m for m in ms if isinstance(m, dict) and cid in _ids_message(m)]
            if poses:
                _noter_salon(gid, cle, panneau=max(poses, key=lambda m: str(m["id"]).zfill(20))["id"])
                bilan["ok"].append(cle)
                continue
            if cle in sauf:
                continue
            if cle == "menu" and any(ANCIEN_MENU in _ids_message(m) for m in ms if isinstance(m, dict)):
                # l'ancien « Afficher le menu » est encore là : installer_salons
                # le convertit ; en poser un second ferait deux menus
                bilan["rates"].append("menu (l'ancien panneau numx:menu est encore là)")
                continue
            code, m = _api("POST", f"/channels/{salon}/messages", json=corps(), gid=gid)
            if code in (200, 201) and isinstance(m, dict) and m.get("id"):
                _noter_salon(gid, cle, panneau=m["id"])
                bilan["poses"].append(cle)
            else:
                bilan["rates"].append(f"{cle} (HTTP {code}) {str(m)[:120]}")
        except Exception as e:                               # noqa: BLE001
            bilan["rates"].append(f"{cle} ({type(e).__name__}: {e})")
    neufs = [c for c in bilan["supprimes"] if (gid, "supprime", c) not in _DITS]
    _DITS.update((gid, "supprime", c) for c in neufs)
    if bilan["poses"] or bilan["rates"] or neufs:
        _log(f"salons communs {gid} : posés {bilan['poses']}, ratés {bilan['rates']}, "
             f"supprimés à la main (jamais refaits) {neufs}")
    return bilan


def installer_salons(gid: str, essai: bool = True) -> Dict[str, Any]:
    """Une fois, à la main, SUR LE VPS (la fiche data/outils_salons.json doit
    être celle du bot en service) : dans 🧰 OUTILS INSTAGRAM, 📋・menu (déjà
    là), 📤・spoofer et ⬇️・download (créés) puis 📱・numéro (déjà là, à Rem),
    en tête de la catégorie et dans cet ordre ; chacun en lecture seule, avec
    les droits de 📱・numéro (Essai, Confirmé, Manager, Helper), plus
    🌱 Débutant : ce rôle remplace 🧪 Essai au passage et n'avait AUCUN droit
    sur la catégorie (trois VA ne voyaient pas les outils, 04/11). Puis les
    panneaux. Le panneau d'avant de 📋・menu (« Afficher le menu », numx:menu,
    posé par Wario) devient le nouveau, par modification : rien n'est
    supprimé. Tout ce qui manque (bot, rôles, catégorie) arrête AVANT la
    première écriture. Relançable : les salons sont repris par leur id.
    `essai` : rien n'est écrit, le plan est rendu. Rend {plan, faits, rates}."""
    import tickets_discord as tk
    gid = str(gid)
    out: Dict[str, Any] = {"plan": [], "faits": [], "rates": []}
    cat, dedans, tous, raison = _lire_categorie(gid)
    if raison:
        out["rates"].append(raison)
        return out
    par_cle = _salons_par_cle(gid, dedans, tous)
    numero = par_cle.get(CLE_NUMERO)
    if numero is None:
        out["rates"].append("📱・numéro introuvable : ses droits servent de modèle")
        return out
    deb, essai_rid = tk.role_debutant(gid), tk.role_essai(gid)
    modele = [dict(o) for o in numero.get("permission_overwrites") or [] if int(o.get("type", 0)) == 0]
    ref = next((o for o in modele if o["id"] == essai_rid), None)
    code, moi = _api("GET", "/users/@me", gid=gid)
    bot = str((moi or {}).get("id") or "") if code == 200 and isinstance(moi, dict) else ""
    manque = ([] if deb else ["rôle 🌱 Débutant introuvable (rôles illisibles ?)"]) \
        + ([] if ref else ["droits de 🧪 Essai absents de 📱・numéro"]) \
        + ([] if bot else [f"identité du bot illisible (HTTP {code})"])
    if manque:
        out["rates"] += manque
        out["plan"].append("rien : " + " ; ".join(manque))
        return out
    if not any(o["id"] == deb for o in modele):
        modele.append({"id": deb, "type": 0, "allow": ref["allow"], "deny": ref["deny"]})

    def faire(quoi: str, methode: str, chemin: str, **kw):
        out["plan"].append(quoi)
        if essai:
            return 200, {}
        c, r = _api(methode, chemin, gid=gid, **kw)
        (out["faits"] if c in (200, 201, 204) else out["rates"]).append(
            quoi if c in (200, 201, 204) else f"{quoi} (HTTP {c}) {str(r)[:160]}")
        return c, r

    def debutant(c: Dict[str, Any]) -> None:
        if not any(o.get("id") == deb for o in c.get("permission_overwrites") or []):
            faire(f"🌱 Débutant dans {c.get('name')}", "PUT", f"/channels/{c['id']}/permissions/{deb}",
                  json={"type": 0, "allow": ref["allow"], "deny": ref["deny"]})

    ordre = []
    for cle, nom, _b in PANNEAUX:
        c = par_cle.get(cle)
        if c is None:
            droits = modele + [{"id": bot, "type": 1, "allow": str(DROITS_BOT), "deny": "0"}]
            code, c = faire(f"créer {nom}", "POST", f"/guilds/{gid}/channels",
                            json={"name": nom, "type": 0, "parent_id": cat["id"],
                                  "permission_overwrites": droits})
            if essai:
                c = {"id": f"<{cle}>", "name": nom}
            elif code not in (200, 201) or not isinstance(c, dict) or not c.get("id"):
                continue
        else:
            debutant(c)
        if not essai:
            _noter_salon(gid, cle, salon=c["id"])
        ordre.append(c)
    debutant(numero)
    ordre.append(numero)
    # en tête de la catégorie, dans l'ordre de YouCham ; les autres suivent
    ids = [str(c["id"]) for c in ordre]
    reste = [c for c in dedans if str(c["id"]) not in ids]
    base = min([int(c.get("position") or 0) for c in dedans] or [0])
    positions = [{"id": i, "position": base + k} for k, i in enumerate(ids + [str(c["id"]) for c in reste])
                 if not i.startswith("<")]
    actuel = [str(c["id"]) for c in dedans]
    if [x["id"] for x in positions] != actuel or any(
            int(c.get("position") or 0) != base + k for k, c in enumerate(dedans)):
        faire("ranger menu · spoofer · download · numéro en tête", "PATCH", f"/guilds/{gid}/channels",
              json=positions)
    # l'ancien panneau de 📋・menu (Wario, numx:menu) devient le neuf
    sauf: Tuple[str, ...] = ()
    menu = par_cle.get("menu")
    cid_menu = {c: b for c, _n, b in PANNEAUX}["menu"][2]
    if menu is not None:
        code, ms = _api("GET", f"/channels/{menu['id']}/messages?limit=50", gid=gid)
        if code != 200 or not isinstance(ms, list):
            out["rates"].append(f"📋・menu illisible (HTTP {code}) : son panneau attend la relance")
            sauf = ("menu",)
        else:
            a_nous = [m for m in ms if str((m.get("author") or {}).get("id")) == bot]
            vieux = [m for m in a_nous if ANCIEN_MENU in _ids_message(m)]
            neuf = any(cid_menu in _ids_message(m) for m in a_nous)
            if vieux and neuf:
                out["rates"].append("📋・menu : l'ancien panneau (numx:menu) est encore à côté du neuf ; "
                                    "rien n'est supprimé, à retirer à la main")
            elif vieux:
                c, _r = faire("📋・menu : l'ancien panneau (numx:menu) devient « Ouvrir mon menu »",
                              "PATCH", f"/channels/{menu['id']}/messages/{vieux[0]['id']}",
                              json=corps_panneau("menu"))
                if c == 200 and not essai:
                    _noter_salon(gid, "menu", panneau=vieux[0]["id"])
                elif not essai:
                    sauf = ("menu",)       # pas de second panneau à côté de l'ancien
    if essai:
        out["plan"].append("poser les panneaux manquants")
        return out
    _noter_salon(gid, "installe", quand=int(time.time()))
    if not (_etat_salons().get(gid) or {}).get("installe"):
        out["rates"].append(f"fiche {SALONS_FICHIER} non écrite : le démarrage ne reposera rien")
    b = assurer_panneaux(gid, sauf=sauf)
    out["faits"] += [f"panneau {c} posé" for c in b["poses"]]
    out["rates"] += b["rates"]
    return out


# ─── 🧰 OUTILS TWITTER (06/11/2026) ───────────────────────────────────────
# Propriétaire, sur TRUST TWITTER : « tu peux faire un truc outils Twitter et
# tu mets le numéro, adresse, numéro, spoofer vraiment séparé », puis ses
# réponses : 📱 numéro, 📧 adresse, 📤 spoofer (pas de download) ; les tickets
# GARDENT leurs cartes numéro / Outlook et leurs boutons jusqu'à son « c'est
# bon ». Une catégorie 🧰 OUTILS TWITTER, juste après 📚 RESSOURCES, un outil
# par salon, chacun avec les droits de 📧・adresse-outlook (✅ Vérifié lit,
# personne n'écrit) :
#  - 📱・numéro : le formulaire « Numéro X » de numeros_x_discord (HeroSMS),
#    validé le 18/10 ; un clic hors carte achète en privé, 3 codes par jour,
#    le même compte du jour que la carte du ticket (numeros_du_jour) ;
#  - 📧・adresse-outlook : le salon d'avant, vide depuis le 23/10 (« retire
#    outlook »), DÉPLACÉ dans la catégorie avec ses droits, et le formulaire
#    « Adresses Outlook » d'outlook_x_discord ; l'adresse s'ouvre en privé et
#    part aussi dans le ticket (deposer_au_salon), 3 par jour ;
#  - 📤・spoofer : le même bouton que TRUST INSTAGRAM, les versions livrées
#    dans le ticket du cliqueur (_ticket_du_clic, salon commun), postées par
#    le bot du serveur.
# Chaque panneau appartient au module qui sert ses clics (numx:, mailx:,
# outk:) ; il est posé et reposé ici (assurer_panneaux, au démarrage), une
# seule liste par serveur (_panneaux). Installé une fois, à la main, SUR LE
# VPS : installer_salons_twitter(essai=True) puis essai=False.
TWITTER_ID = "1445108485090971710"
SERVEURS.add(TWITTER_ID)
SALONS_COMMUNS.add(TWITTER_ID)
CATEGORIES_OUTILS: Dict[str, str] = {AGENCY_IG_ID: CATEGORIE_OUTILS, TWITTER_ID: "outils twitter"}
NOM_CATEGORIE_TWITTER = "🧰 OUTILS TWITTER"
#: 📚 RESSOURCES > 📧・adresse-outlook : déplacé, ses droits servent de modèle.
ADRESSE_OUTLOOK_TWITTER = "1552392906340565114"
#: La catégorie après laquelle 🧰 OUTILS TWITTER est rangée (nom sans décor).
CATEGORIE_AVANT_TWITTER = "ressources"


def _corps_numero_twitter() -> Dict[str, Any]:
    import numeros_x_discord as nx
    return {"flags": V2, "allowed_mentions": {"parse": []},
            "components": nx.vue_panneau(nx.SERVEURS[TWITTER_ID])}


def _corps_adresse_twitter() -> Dict[str, Any]:
    import outlook_x_discord as ox
    return {"flags": V2, "allowed_mentions": {"parse": []}, "components": ox.vue_panneau()}


#: (clé, nom à la création, custom_id qui reconnaît le panneau, son corps),
#: dans l'ordre des salons de la catégorie.
PANNEAUX_TWITTER = (
    ("numero", "📱・numéro", "numx:prendre", _corps_numero_twitter),
    ("adresse", "📧・adresse-outlook", "mailx:prendre", _corps_adresse_twitter),
    ("spoofer", "📤・spoofer", f"{PREFIXE}spf:commun", lambda: corps_panneau("spoofer")),
)


def _panneaux(gid: str) -> List[Tuple[str, str, str, Any]]:
    """Les panneaux des salons communs de ce serveur : (clé, nom, custom_id
    qui reconnaît le panneau, fonction qui rend son corps). TRUST INSTAGRAM :
    PANNEAUX (📱・numéro y est à Rem, pas d'ici)."""
    if str(gid) == TWITTER_ID:
        return list(PANNEAUX_TWITTER)
    return [(cle, nom, b[2], (lambda c=cle: corps_panneau(c))) for cle, nom, b in PANNEAUX]


_ramener_menu_partout = _ramener_menu


def _ramener_menu(gid: str, uid: str, salon: str) -> None:   # noqa: F811
    """Sur TRUST TWITTER, le menu ne redescend pas après un spoof : sur TRUST
    INSTAGRAM, une fois les outils en salons communs, le propriétaire l'a
    demandé (« ne renvoie plus le menu à chaque fois dans leur salon »,
    05/11, tickets_discord.MENU_FIXE). Le tour de l'heure, lui, ne change pas."""
    if str(gid) == TWITTER_ID:
        return
    _ramener_menu_partout(gid, uid, salon)


def installer_salons_twitter(essai: bool = True) -> Dict[str, Any]:
    """Une fois, à la main, SUR LE VPS : 🧰 OUTILS TWITTER (créée si elle
    manque, rangée juste après 📚 RESSOURCES), puis 📱・numéro (créé),
    📧・adresse-outlook (déplacé, ses droits gardés) et 📤・spoofer (créé),
    dans cet ordre, chacun avec les droits de 📧・adresse-outlook. Puis les
    panneaux. Ce qui manque (salon modèle, droits fermés à @everyone) arrête
    AVANT la première écriture. Relançable : les salons sont repris par leur
    id (fiche data/outils_salons.json) ou leur nom. `essai` : rien n'est
    écrit, le plan est rendu. Rend {plan, faits, rates}."""
    gid = TWITTER_ID
    out: Dict[str, Any] = {"plan": [], "faits": [], "rates": []}
    code, tous = _api("GET", f"/guilds/{gid}/channels", gid=gid)
    if code != 200 or not isinstance(tous, list):
        out["rates"].append(f"salons illisibles (HTTP {code})")
        return out
    par_id = {str(c.get("id")): c for c in tous}
    note_id = str(((_etat_salons().get(gid) or {}).get("adresse") or {}).get("salon") or "")
    adresse = par_id.get(note_id) or par_id.get(ADRESSE_OUTLOOK_TWITTER)
    if adresse is None or adresse.get("type") != 0:
        out["rates"].append("📧・adresse-outlook introuvable : ses droits servent de modèle")
        return out
    droits = [{"id": str(o["id"]), "type": int(o.get("type", 0)), "allow": str(o.get("allow") or "0"),
               "deny": str(o.get("deny") or "0")}
              for o in adresse.get("permission_overwrites") or [] if o.get("id")]
    if not any(o["id"] == gid and int(o["deny"]) & 1024 for o in droits):
        out["rates"].append("📧・adresse-outlook n'est pas fermé à @everyone : ses droits ne "
                            "peuvent pas servir de modèle, rien n'est fait")
        return out

    def faire(quoi: str, methode: str, chemin: str, **kw):
        out["plan"].append(quoi)
        if essai:
            return 200, {}
        c, r = _api(methode, chemin, gid=gid, **kw)
        (out["faits"] if c in (200, 201, 204) else out["rates"]).append(
            quoi if c in (200, 201, 204) else f"{quoi} (HTTP {c}) {str(r)[:160]}")
        return c, r

    def pos(c):
        return (int(c.get("position") or 0), str(c.get("id")).zfill(20))

    cats = sorted([c for c in tous if c.get("type") == 4], key=pos)
    cat = next((c for c in cats if _cle_salon(c.get("name")).endswith(CATEGORIES_OUTILS[gid])), None)
    if cat is None:
        code, cat = faire(f"créer la catégorie {NOM_CATEGORIE_TWITTER} (droits de 📧・adresse-outlook)",
                          "POST", f"/guilds/{gid}/channels",
                          json={"name": NOM_CATEGORIE_TWITTER, "type": 4, "permission_overwrites": droits})
        if essai:
            cat = {"id": "<categorie>", "name": NOM_CATEGORIE_TWITTER}
        elif code not in (200, 201) or not isinstance(cat, dict) or not cat.get("id"):
            return out
    # rangée juste après 📚 RESSOURCES — vérifié à CHAQUE passage : un
    # rangement raté (Discord muet) se refait à la relance
    avant = next((c for c in cats if _cle_salon(c.get("name")).endswith(CATEGORIE_AVANT_TWITTER)), None)
    if avant is None:
        out["plan"].append("📚 RESSOURCES introuvable : la catégorie reste où elle est")
    else:
        actuel = [str(c["id"]) for c in cats]
        ordre: List[str] = []
        for c in cats:
            if str(c["id"]) == str(cat["id"]):
                continue
            ordre.append(str(c["id"]))
            if c is avant:
                ordre.append(str(cat["id"]))
        if ordre != actuel:
            faire(f"ranger {NOM_CATEGORIE_TWITTER} juste après {avant.get('name')}", "PATCH",
                  f"/guilds/{gid}/channels",
                  json=[{"id": i, "position": k} for k, i in enumerate(ordre) if not i.startswith("<")])
    dedans = sorted([c for c in tous if str(c.get("parent_id") or "") == str(cat["id"])
                     and c.get("type") == 0], key=pos)
    par_cle = _salons_par_cle(gid, dedans, tous)
    par_cle.setdefault("adresse", adresse)
    ordre_salons: List[Dict[str, Any]] = []
    for cle, nom, _m, _c in PANNEAUX_TWITTER:
        c = par_cle.get(cle)
        if c is None:
            code, c = faire(f"créer {nom}", "POST", f"/guilds/{gid}/channels",
                            json={"name": nom, "type": 0, "parent_id": cat["id"],
                                  "permission_overwrites": droits})
            if essai:
                c = {"id": f"<{cle}>", "name": nom}
            elif code not in (200, 201) or not isinstance(c, dict) or not c.get("id"):
                continue
        elif str(c.get("parent_id") or "") != str(cat["id"]):
            code, _r = faire(f"déplacer {c.get('name')} dans {NOM_CATEGORIE_TWITTER} (ses droits gardés)",
                             "PATCH", f"/channels/{c['id']}", json={"parent_id": cat["id"]})
            if not essai and code not in (200, 201):
                continue
        if not essai:
            _noter_salon(gid, cle, salon=c["id"])
        ordre_salons.append(c)
    ids = [str(c["id"]) for c in ordre_salons]
    reste = [str(c["id"]) for c in dedans if str(c["id"]) not in ids]
    voulu = [{"id": i, "position": k} for k, i in enumerate(ids + reste) if not i.startswith("<")]
    if essai or [str(c["id"]) for c in dedans] != ids + reste:
        faire("ranger numéro · adresse · spoofer", "PATCH", f"/guilds/{gid}/channels", json=voulu)
    if essai:
        out["plan"].append("poser les 3 panneaux (Numéro X, Adresses Outlook, Spoofer)")
        return out
    _noter_salon(gid, "installe", quand=int(time.time()))
    if not (_etat_salons().get(gid) or {}).get("installe"):
        out["rates"].append(f"fiche {SALONS_FICHIER} non écrite : le démarrage ne reposera rien")
    b = assurer_panneaux(gid)
    out["faits"] += [f"panneau {c} posé" for c in b["poses"]]
    out["rates"] += b["rates"]
    return out
