# -*- coding: utf-8 -*-
"""Les bangers de Youl4b et de Va IG, recopiés sur You US et You FR.

POURQUOI (propriétaire, 10/11/2026)
    « Sur FR … il va falloir quand même retrouver banger Emma, banger Amelia
    … et sur l'autre, comme d'hab, banger et all-banger », puis « oui, les
    bangers ». You US et You FR sont ses propres équipes : aucun de leurs
    comptes n'est encore dans le relevé, rien n'alimenterait leurs salons.
    Ils reçoivent donc, en COPIE, ce qui paraît dans les salons de leur
    marché (guild_features.BANGERS_MIROIR) :

        You US   💥・banger          la publication du matin de Youl4b (Jessye)
                 💣・all-banger      le all-banger de Youl4b
        You FR   🔥・banger-<model>  la publication du matin de Va IG, model
                                     par model

CE QUI EST RECOPIÉ, ET CE QUI NE L'EST PAS
    La carte, faite des MÊMES briques que la source (bangers.fiche_discord,
    all_banger.vue_message) avec la vidéo de l'archive. Sans la ligne « Géré
    par » : le VA est celui de Youl4b ou de Va IG, un inconnu là-bas. Pas le
    récapitulatif du matin : c'est le classement des VA de l'autre serveur.
    Une carte rééditée à la source (statistiques rafraîchies) ne l'est pas ici.

POURQUOI UN MODULE À PART, QUI NE FAIT QUE LIRE LES AUTRES
    Une fiche de banger ne garde qu'UNE annonce (details['annonce'], vérifiée
    dans bangers.publier_journee) : un second salon sur les mêmes reels
    l'écraserait et ferait refuser la journée suivante de Youl4b. C'est pour
    ça que le 💥・banger de YouCham n'a jamais été branché. Ici, les journaux
    du matin et le registre all-banger sont LUS, jamais écrits ; la copie a
    son propre journal (data/bangers_miroir.json). Une panne ici ne retient
    ni Youl4b ni Va IG.

SANS DOUBLE ENVOI
    L'intention est écrite AVANT l'envoi (état « envoi »), comme la
    publication du matin. Après une coupure, on regarde d'abord dans le salon
    (all_banger.retrouver) ; on ne renvoie que si le message n'y est pas.
    Journal perdu (data/ repartie de zéro) : avant le premier envoi dans un
    salon, son historique est relu et ce qui s'y trouve déjà est noté
    (amorce) — sans ça, toute la semaine repartait une seconde fois.

À LA MISE EN SERVICE
    Les RATTRAPAGE_JOURS derniers jours sont recopiés, du plus ancien au plus
    récent, PAR_TOUR cartes au plus par salon et par passage : un salon vide
    n'apprend rien à personne.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import pathlib
import re
import time
from typing import Dict, List, Optional

import safe_json

import all_banger as _ab
import bangers as _bg

log = logging.getLogger("vabot.bangers_miroir")

_ICI = pathlib.Path(__file__).resolve().parent

#: Le journal de la copie. À elle seule : bangers.json et bangers_all.json
#: sont réécrits en entier par les scrapes et par le fil d'envoi.
JOURNAL = _ICI / "data" / "bangers_miroir.json"

#: Ce qui est recopié à la mise en service d'un salon, en jours.
RATTRAPAGE_JOURS = 7

#: Au-delà, une parution n'est plus regardée : relire tous les journaux
#: depuis la mise en service, toutes les dix minutes, c'était des centaines
#: de fichiers au bout de quelques mois. Plus large que le rattrapage : une
#: panne de quelques jours se rattrape encore.
FENETRE_JOURS = 10

#: Une carte à la fois, avec un court répit (all_banger.DELAI_ENTRE_MESSAGES).
DELAI_ENTRE_MESSAGES = 4.0

#: Cartes tentées au plus par SALON et par passage : le reste part au passage
#: suivant (dix minutes plus tard). Par salon, pas pour tout le passage : à
#: la mise en service, les premiers salons de la liste auraient sinon pris
#: tout le quota et les autres seraient restés vides une heure.
PAR_TOUR = 30

#: Refus nets de Discord (4xx) tolérés pour UNE carte avant de la classer.
ESSAIS_MAX = 3

#: Une intention plus jeune que ça peut encore être en vol : on ne la vérifie
#: pas tout de suite (all_banger.DELAI_VERIFICATION).
DELAI_VERIFICATION = 120.0

#: Messages relus dans un salon à l'amorce (journal absent).
AMORCE_MESSAGES = 600

#: Une entrée du journal plus vieille que ça ne sert plus : sa parution est
#: sortie de FENETRE_JOURS depuis longtemps, elle ne sera plus jamais candidate.
PURGE_JOURS = 45

#: Les états où une carte n'a plus rien à attendre.
TERMINAUX = ("envoye", "trop_lourd", "echec")

_RE_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Ce qui a déjà été dit, par cause : la boucle repasse toutes les dix
#: minutes. Effacé quand la cause disparaît, pour qu'une rechute se voie.
_DITS: set = set()

#: Un passage à la fois : la boucle, et un appel à la main.
_VERROUS: Dict[int, asyncio.Lock] = {}


def _dire_une_fois(cle: str, message: str, niveau=logging.WARNING) -> None:
    if cle in _DITS:
        return
    _DITS.add(cle)
    log.log(niveau, message)


def _oublier(prefixe: str) -> None:
    for k in [k for k in _DITS if k.startswith(prefixe)]:
        _DITS.discard(k)


# ------------------------------------------------------------ destinations --

def destinations() -> List[dict]:
    """Les salons qui reçoivent une copie, dans l'ordre des passages.

    Lus dans guild_features.BANGERS_MIROIR (id du serveur -> marché) : aucun
    id n'est recopié ici. Chaque destination a sa clé (« <serveur>:<salon> »),
    celle de son journal."""
    import guild_features as gf
    out = []
    for gid, marche in sorted(gf.BANGERS_MIROIR.items()):
        serveur = gf.US_GUILDS.get(gid, gid)
        base = {"guild_id": int(gid), "serveur": serveur}
        if marche == "us":
            out.append(dict(base, cle=f"{gid}:banger", genre="matin", nom="banger",
                            model="", source=_bg.salon_us()))
            out.append(dict(base, cle=f"{gid}:all-banger", genre="all", nom="all-banger",
                            model="", source=None))
        elif marche == "fr":
            for m in _bg.MODELS_FR:
                out.append(dict(base, cle=f"{gid}:banger-{m}", genre="matin",
                                nom="banger-" + m, model=m, source=_bg.salon_fr(m)))
        else:
            _dire_une_fois(f"marche:{gid}:{marche}", f"[bangers-miroir] {serveur} : marché "
                           f"« {marche} » inconnu, rien n'y est recopié")
    return out


def salon_de(guild, dest):
    """Le salon de cette destination sur le serveur, par son nom sans décor,
    hors archives ; None s'il n'existe pas (supprimé, renommé autrement)."""
    if dest["genre"] == "all":
        return _ab.trouver_salon(guild)
    if dest["model"]:
        return _bg.salon_banger_de(guild, dest["model"])
    trouves = [c for c in (getattr(guild, "text_channels", None) or [])
               if not _bg.dans_archives(c) and _bg._nom_de_salon(getattr(c, "name", "")) == "banger"]
    if not trouves:
        return None
    trouves.sort(key=lambda c: (getattr(c, "position", 0) or 0, getattr(c, "id", 0) or 0))
    return trouves[0]


def nonce(dest, shortcode: str) -> str:
    """Le nonce Discord de cette copie : le même reel a un nonce par salon."""
    return hashlib.sha256(f"miroir:{dest['cle']}:{shortcode}".encode()).hexdigest()[:24]


# ----------------------------------------------------------------- journal --

def _vide() -> dict:
    return {"schema": 1, "destinations": {}, "envois": {}}


def charger() -> dict:
    d = safe_json.load(JOURNAL, None)
    if not isinstance(d, dict):
        return _vide()
    for k in ("destinations", "envois"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _ecrire(d: dict) -> bool:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write(JOURNAL, d))


def _cle(dest, shortcode: str) -> str:
    return f"{dest['cle']}|{shortcode}"


def _purger(d: dict, maintenant: float) -> int:
    """Retire les entrées tranchées depuis plus de PURGE_JOURS. Jamais une
    intention en cours."""
    limite = maintenant - PURGE_JOURS * 86400
    vieux = [k for k, e in d["envois"].items()
             if isinstance(e, dict) and e.get("etat") in TERMINAUX
             and 0 < float(e.get("le") or 0) < limite]
    for k in vieux:
        d["envois"].pop(k, None)
    return len(vieux)


# --------------------------------------------------------------- candidats --

def _borne(depuis: float, maintenant: float) -> float:
    return max(float(depuis or 0), maintenant - FENETRE_JOURS * 86400)


def candidats_matin(dest, depuis: float, maintenant: Optional[float] = None) -> tuple:
    """([{"sc", "jour", "fiche"}], [journaux illisibles]) : les fiches PARUES
    dans le salon du matin de la source, du jour le plus ancien au plus
    récent, dans l'ordre où elles y ont été postées.

    Paru = état « envoye » avec son message : une fiche en attente, en
    doublon ou retirée n'est pas recopiée. Un journal illisible est NOMMÉ,
    jamais sauté en silence ; les autres jours partent."""
    now = time.time() if maintenant is None else float(maintenant)
    dossier = pathlib.Path(dest["source"]["dossier"])
    premier = datetime.datetime.fromtimestamp(_borne(depuis, now), _bg.TZ).date().isoformat()
    out, illisibles = [], []
    try:
        fichiers = sorted(dossier.glob("*.json"))
    except OSError:
        fichiers = []
    for p in fichiers:
        jour = p.stem
        if not _RE_JOUR.fullmatch(jour) or jour < premier:
            continue
        try:
            record = _bg._lire_journee(jour, dossier)
        except Exception as e:                                # noqa: BLE001
            illisibles.append(f"{jour} ({type(e).__name__})")
            continue
        for sc, item in ((record or {}).get("reels") or {}).items():
            if not isinstance(item, dict) or item.get("etat") != "envoye" \
                    or not item.get("message_id"):
                continue
            f = item.get("fiche")
            if not isinstance(f, dict) or not f.get("compte") or not f.get("url"):
                illisibles.append(f"{jour}/{sc} (fiche incomplète)")
                continue
            out.append({"sc": sc, "jour": jour,
                        "fiche": dict(f, shortcode=sc, jour_bilan=f.get("jour_bilan") or jour)})
    return out, illisibles


def candidats_all(dest, depuis: float, maintenant: Optional[float] = None) -> tuple:
    """([{"sc", "entree"}], []) : les bangers POSTÉS dans le all-banger de
    Youl4b, dans l'ordre où ils y sont arrivés.

    Ni les jumelles (« <sc>@fr:<model> ») ni les marchés FR : ceux-là sont
    les all-banger de Va IG. Une entrée d'avant le champ `marche` est de
    Youl4b (il n'y avait que lui)."""
    now = time.time() if maintenant is None else float(maintenant)
    borne = _borne(depuis, now)
    trouves = []
    for cle, e in (_ab.charger().get("reels") or {}).items():
        if not isinstance(e, dict) or e.get("etat") != "envoye" or not e.get("message_id"):
            continue
        if "@" in cle or str(e.get("marche") or "us") != "us":
            continue
        quand = _bg._entier(e.get("envoye_le"))
        if quand < borne:
            continue
        trouves.append((quand, cle, e))
    trouves.sort(key=lambda x: (x[0], x[1]))
    return [{"sc": cle, "entree": dict(e)} for _q, cle, e in trouves], []


def candidats(dest, depuis: float, maintenant: Optional[float] = None) -> tuple:
    return (candidats_all if dest["genre"] == "all" else candidats_matin)(dest, depuis, maintenant)


def _preparer_all(shortcode: str, entree: dict, cache: dict) -> dict:
    """Ce que montre la carte all-banger : description, lien, vues — lus
    comme all_banger.envoyer les lit. Le registre des bangers (des milliers
    de fiches) n'est chargé qu'UNE fois par passage (`cache`)."""
    if "fiches" not in cache:
        try:
            cache["fiches"] = _bg.charger().get("reels") or {}
        except Exception:                                     # noqa: BLE001
            cache["fiches"] = {}
    fiche = cache["fiches"].get(shortcode)
    fiche = fiche if isinstance(fiche, dict) else {}
    return {"description": _ab.description_de(shortcode, fiche),
            "url": _ab.url_de(shortcode, fiche),
            "vues": _ab.vues_de(shortcode, entree, fiche)}


# ------------------------------------------------------------------- envoi --

async def _envoyer(salon, dest, cand, limite: int, cache: dict, repit=None) -> dict:
    """Poste UNE copie. `repit` est attendu juste avant l'envoi à Discord,
    jamais pour une carte qui ne part pas (trop lourde, vidéo disparue).
    Rend un seul de ces cas (ceux d'all_banger.envoyer) :
      {"message_id", "channel_id"}   posté
      {"trop_lourd", "taille", "limite"}
      {"echec": raison}              définitif (vidéo disparue)
      {"refuse": raison, "status"}   Discord a dit non pour CETTE carte
      {"salon_absent": raison}       salon ou droits : rien ne partira ici
      {"incertain": raison}          peut-être parti : on vérifiera"""
    import discord
    sc = cand["sc"]
    fichiers = []
    try:
        if dest["genre"] == "all":
            if not _bg.video_presente(sc):
                return {"echec": "video_disparue"}
            fichier = _bg.chemin_video(sc)
            taille = fichier.stat().st_size
            if taille > limite:
                return {"trop_lourd": True, "taille": taille, "limite": limite}
            prep = await asyncio.to_thread(_preparer_all, sc, cand["entree"], cache)
            vue, fichiers = _ab.vue_message(sc, fichier, prep["description"], prep["url"],
                                            prep["vues"])
        else:
            fichier = _bg.chemin_video(sc) if _bg.video_presente(sc) else None
            # anonyme : jamais la mention ni le nom du VA, même si la fiche
            # (Youl4b) porte encore son id Discord.
            vue, fichiers = _bg.fiche_discord(cand["fiche"], fichier, limite,
                                              libelle=dest["source"]["libelle"],
                                              anonyme=True, sans_gerant=True)
    except Exception as ex:                                   # noqa: BLE001
        for f in fichiers:
            f.close()
        return {"refuse": f"carte:{type(ex).__name__}", "status": 0}
    try:
        if repit is not None:
            await repit()
        m = await salon.send(view=vue, files=fichiers, nonce=nonce(dest, sc),
                             allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as ex:
        status = int(getattr(ex, "status", 0) or 0)
        if status == 413:
            return {"trop_lourd": True, "taille": 0, "limite": limite}
        if status in (401, 403, 404):
            return {"salon_absent": f"Discord refuse l'envoi dans #{salon.name} (http_{status})"}
        if 400 <= status < 500:
            return {"refuse": f"http_{status}", "status": status}
        return {"incertain": f"http_{status}"}
    except Exception as ex:                                   # noqa: BLE001
        return {"incertain": type(ex).__name__}
    finally:
        for f in fichiers:
            f.close()
    return {"message_id": m.id, "channel_id": salon.id}


async def _amorcer(client, salon, dest, a_faire, journal, maintenant: float) -> int:
    """Journal sans trace de ce salon : note comme postées les copies qui s'y
    trouvent DÉJÀ (relues dans l'historique). Rend leur nombre ; lève
    discord.HTTPException si l'historique ne se lit pas — l'appelant n'envoie
    alors rien, plutôt que de tout reposter à l'aveugle."""
    moi = getattr(getattr(client, "user", None), "id", None)
    messages = []
    async for m in salon.history(limit=AMORCE_MESSAGES):
        if getattr(getattr(m, "author", None), "id", None) == moi:
            messages.append(m)
    if not messages:
        return 0
    n = 0
    for cand in a_faire:
        sc = cand["sc"]
        trouve = next((m for m in messages if _ab._porte_le_reel(m, sc, nonce(dest, sc))), None)
        if trouve is None:
            continue
        journal["envois"][_cle(dest, sc)] = {
            "etat": "envoye", "message_id": int(trouve.id), "channel_id": int(salon.id),
            "le": int(maintenant), "retrouve": True}
        n += 1
    return n


def _droits_manquants(salon, moi) -> list:
    if moi is None or not hasattr(salon, "permissions_for"):
        return []
    droits = salon.permissions_for(moi)
    return [nom for nom, attr in (("voir le salon", "view_channel"), ("écrire", "send_messages"),
                                  ("joindre un fichier", "attach_files"),
                                  ("voir les anciens messages", "read_message_history"))
            if not getattr(droits, attr, True)]


async def tour(client, dormir=None, maintenant: Optional[float] = None,
               par_tour: Optional[int] = None) -> dict:
    """Un passage : chaque destination reçoit ce qui est paru à sa source et
    qu'elle n'a pas encore. Tourne dans la boucle du bot. Rend le bilan.

    UNE DESTINATION ARRÊTÉE NE RETIENT PAS LES AUTRES : salon absent, droits
    manquants, issue incertaine n'arrêtent que la leur. Seul un journal
    impossible à écrire arrête tout — sans lui, rien ne dit plus ce qui est
    déjà parti."""
    boucle = asyncio.get_running_loop()
    verrou = _VERROUS.setdefault(id(boucle), asyncio.Lock())
    if verrou.locked():
        return {"en_cours": True}
    async with verrou:
        return await _tour(client, dormir or asyncio.sleep, maintenant,
                           PAR_TOUR if par_tour is None else int(par_tour))


async def _tour(client, dormir, maintenant, par_tour) -> dict:
    import discord
    bilan = {"envoyes": 0, "retrouves": 0, "trop_lourds": 0, "echecs": 0, "refus": 0,
             "incertains": 0, "restants": 0, "attentes": {}}

    def now() -> float:
        return time.time() if maintenant is None else float(maintenant)

    journal = await asyncio.to_thread(charger)
    cache: dict = {}
    parti = {"deja": False}

    async def repit() -> None:
        # Une carte à la fois, avec un court répit — pas avant la première.
        if parti["deja"]:
            await dormir(DELAI_ENTRE_MESSAGES)
        parti["deja"] = True

    async def sauver() -> bool:
        if await asyncio.to_thread(_ecrire, journal):
            return True
        bilan["attentes"]["journal"] = "journal non enregistré"
        log.error("[bangers-miroir] journal non enregistré : envois suspendus")
        return False

    if _purger(journal, now()):
        if not await sauver():
            return bilan

    for dest in destinations():
        cle_d, nom = dest["cle"], f"{dest['serveur']} · {dest['nom']}"

        def attendre(cause: str, _cle_d=cle_d, _nom=nom) -> None:
            bilan["attentes"][_cle_d] = cause
            _dire_une_fois(f"attente:{_cle_d}:{cause}",
                           f"[bangers-miroir] {_nom} : {cause} — ce salon attend, les autres "
                           f"continuent")

        guild = client.get_guild(dest["guild_id"])
        if guild is None or getattr(guild, "unavailable", False):
            attendre("serveur hors de portée du bot")
            continue
        salon = salon_de(guild, dest)
        if salon is None:
            attendre(f"aucun salon « {dest['nom']} » sur le serveur")
            continue
        manque = _droits_manquants(salon, getattr(guild, "me", None))
        if manque:
            attendre(f"le bot n'a pas le droit de {', '.join(manque)} dans #{salon.name}")
            continue

        etat_d = journal["destinations"].setdefault(cle_d, {})
        if not etat_d.get("depuis"):
            etat_d["depuis"] = int(now() - RATTRAPAGE_JOURS * 86400)
            if not await sauver():
                return bilan
        try:
            cands, illisibles = await asyncio.to_thread(candidats, dest, etat_d["depuis"], now())
        except Exception as ex:                               # noqa: BLE001
            attendre(f"source illisible ({type(ex).__name__}: {str(ex)[:120]})")
            continue
        if illisibles:
            _dire_une_fois(f"illisibles:{cle_d}:{','.join(illisibles[:5])}",
                           f"[bangers-miroir] {nom} : {len(illisibles)} parution(s) illisible(s), "
                           f"non recopiée(s) : {', '.join(illisibles[:5])}"
                           + (" …" if len(illisibles) > 5 else ""))

        def etat(c) -> str:
            e = journal["envois"].get(_cle(dest, c["sc"]))
            return str(e.get("etat") or "") if isinstance(e, dict) else ""

        a_faire = [c for c in cands if etat(c) not in TERMINAUX]
        if not a_faire:
            _oublier(f"attente:{cle_d}:")
            continue

        if not etat_d.get("amorce"):
            try:
                retrouves = await _amorcer(client, salon, dest, a_faire, journal, now())
            except discord.HTTPException as ex:
                attendre(f"relecture de #{salon.name} impossible "
                         f"(http_{getattr(ex, 'status', 0)}) : rien n'est envoyé à l'aveugle")
                continue
            etat_d["amorce"] = True
            if not await sauver():
                return bilan
            if retrouves:
                bilan["retrouves"] += retrouves
                log.info(f"[bangers-miroir] {nom} : {retrouves} copie(s) déjà dans le salon, "
                         f"notée(s) sans renvoi (journal absent)")
            a_faire = [c for c in a_faire if etat(c) not in TERMINAUX]

        limite = int(getattr(guild, "filesize_limit", 0) or _ab.LIMITE_DEFAUT)
        arret = False
        tentes = 0
        for i, cand in enumerate(a_faire):
            if arret:
                break
            if tentes >= par_tour:
                bilan["restants"] += len(a_faire) - i
                break
            sc = cand["sc"]
            k = _cle(dest, sc)
            e = journal["envois"].get(k)
            e = dict(e) if isinstance(e, dict) else {}
            if e.get("etat") == "envoi":
                # Un passage précédent a peut-être posté cette carte : on
                # regarde dans le salon AVANT de renvoyer.
                age = now() - float(e.get("intention_le") or 0)
                if age < DELAI_VERIFICATION:
                    bilan["incertains"] += 1
                    attendre("un envoi récent attend sa vérification")
                    break
                try:
                    trouve = await _ab.retrouver(client, salon, sc,
                                                 float(e.get("intention_le") or 0),
                                                 nonce=nonce(dest, sc))
                except discord.HTTPException as ex:
                    attendre(f"relecture de #{salon.name} impossible "
                             f"(http_{getattr(ex, 'status', 0)})")
                    break
                if trouve is not None:
                    journal["envois"][k] = {"etat": "envoye", "message_id": int(trouve.id),
                                            "channel_id": int(salon.id), "le": int(now()),
                                            "retrouve": True}
                    bilan["retrouves"] += 1
                    if not await sauver():
                        return bilan
                    continue
                # absent du salon : il repart, à sa place
            essais = int(e.get("essais") or 0)
            journal["envois"][k] = {"etat": "envoi", "intention_le": now(), "essais": essais}
            if not await sauver():
                return bilan
            res = await _envoyer(salon, dest, cand, limite, cache, repit)
            tentes += 1
            if res.get("message_id"):
                journal["envois"][k] = {"etat": "envoye", "message_id": int(res["message_id"]),
                                        "channel_id": int(res.get("channel_id") or 0),
                                        "le": int(now())}
                bilan["envoyes"] += 1
            elif res.get("trop_lourd"):
                journal["envois"][k] = {"etat": "trop_lourd", "le": int(now()),
                                        "taille": int(res.get("taille") or 0),
                                        "limite": int(res.get("limite") or 0)}
                bilan["trop_lourds"] += 1
                log.warning(f"[bangers-miroir] {nom} : {sc} trop lourd pour ce serveur "
                            f"({int(res.get('taille') or 0) / 1048576:.1f} Mo > "
                            f"{int(res.get('limite') or 0) / 1048576:.0f} Mo) — non recopié")
            elif res.get("echec"):
                journal["envois"][k] = {"etat": "echec", "le": int(now()),
                                        "cause": str(res["echec"])[:80]}
                bilan["echecs"] += 1
                log.warning(f"[bangers-miroir] {nom} : {sc} non recopié ({res['echec']})")
            elif res.get("refuse"):
                essais += 1
                bilan["refus"] += 1
                if essais >= ESSAIS_MAX:
                    journal["envois"][k] = {"etat": "echec", "le": int(now()), "essais": essais,
                                            "cause": str(res["refuse"])[:80]}
                    log.warning(f"[bangers-miroir] {nom} : {sc} refusé par Discord "
                                f"({res['refuse']}) {essais} fois — abandonné")
                else:
                    journal["envois"][k] = {"etat": "attente", "essais": essais,
                                            "cause": str(res["refuse"])[:80]}
                    log.warning(f"[bangers-miroir] {nom} : {sc} refusé par Discord "
                                f"({res['refuse']}), essai {essais}/{ESSAIS_MAX} — les suivants partent")
            elif res.get("salon_absent"):
                # Rien n'est parti : l'intention est retirée, la cause dite.
                journal["envois"][k] = {"etat": "attente", "essais": essais}
                attendre(str(res["salon_absent"]))
                arret = True
            else:
                # Peut-être parti : l'état « envoi » reste, la vérification tranchera.
                bilan["incertains"] += 1
                attendre(f"issue d'envoi incertaine ({res.get('incertain') or 'inconnue'}) : "
                         f"vérification au prochain passage")
                arret = True
            if not await sauver():
                return bilan
        if not arret and cle_d not in bilan["attentes"]:
            _oublier(f"attente:{cle_d}:")

    if any(bilan[k] for k in ("envoyes", "retrouves", "trop_lourds", "echecs", "refus", "incertains")):
        log.info(f"[bangers-miroir] passage : {bilan['envoyes']} copie(s) postée(s), "
                 f"{bilan['retrouves']} retrouvée(s), {bilan['trop_lourds']} trop lourde(s), "
                 f"{bilan['echecs']} échec(s), {bilan['refus']} refus, "
                 f"{bilan['incertains']} incertaine(s), {bilan['restants']} au passage suivant")
    return bilan
