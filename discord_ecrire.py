#!/usr/bin/env python3
"""Écrire dans un salon Discord depuis le Mac, sous l'identité du bot SEVEN.

    python3 discord_ecrire.py

Ouvre une petite page sur http://127.0.0.1:8787 : on choisit le serveur et le
salon, on écrit, SEVEN poste. On peut aussi REPRENDRE un message déjà posté
par le bot pour le corriger — Discord ne laisse modifier que ses propres
messages, et ceux du bot en sont.

LOCAL, ET SEULEMENT LOCAL. Rien n'est déployé, rien ne touche youl4b.com. Le
serveur n'écoute que 127.0.0.1 : la page n'est pas joignable depuis le
réseau, et le jeton ne quitte pas la machine. Fermer la fenêtre du terminal
arrête tout.

Le jeton est lu dans ~/.config/seven_bot_token (ou data/seven_bot_token, ou
la variable SEVEN_BOT_TOKEN) et n'est jamais envoyé à la page.

Rien d'autre que la bibliothèque standard : pas d'installation.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API = "https://discord.com/api/v10"
PORT = 8787
# Publié sur youl4b.com/outil-discord/ par le service du VPS, derrière nginx.
# OUTIL_DISCORD_SERVICE=1 : pas de navigateur à ouvrir, et le code se recharge
# seul après un déploiement. OUTIL_DISCORD_GATE_FICHIER : le secret que nginx
# recopie APRÈS le contrôle de session admin de youl4b.com — sans lui, tout
# programme du VPS pouvait piloter les bots. OUTIL_DISCORD_ORIGINES : les
# adresses du site, seules origines admises en plus de 127.0.0.1. Sur le Mac,
# rien de tout ça : l'outil reste local, comme avant.
SERVICE = os.environ.get("OUTIL_DISCORD_SERVICE") == "1"
PORTE_FICHIER = (os.environ.get("OUTIL_DISCORD_GATE_FICHIER") or "").strip()
ORIGINES_SITE = {o.strip().lower().rstrip("/")
                 for o in (os.environ.get("OUTIL_DISCORD_ORIGINES") or "").split(",")
                 if o.strip()}
# Travail maximal par requête. En ligne, Cloudflare coupe une réponse qui
# tarde plus de 100 s : la page se figeait pendant que le serveur continuait.
# Les longues suppressions avancent donc par tranches, que la page enchaîne
# tant que la réponse dit « suite ».
BUDGET_S = 45.0
MAX_TEXTE = 2000            # limite Discord d'un message
MAX_EMBED = 4096            # limite Discord d'une description d'encadré
COULEUR_DEFAUT = 0x5865F2
# Le blanc braille : Discord refuse un message vide ou fait d'espaces, pas
# celui-là. Posté seul entre deux messages, il fait une ligne vide.
ESPACE = "\u2800"

# Les serveurs de l'agence. Repris de verif_discord.py ; on les met en dur
# pour que cet outil marche même lancé hors du dépôt.
try:
    # meme definition que le bot deploye : deux copies finiraient par diverger
    from copie_discord import bouton as BOUTON_COPIE
    from copie_discord import IDENTIFIANT as ID_COPIE
except Exception:
    BOUTON_COPIE = None
    ID_COPIE = "copie"

SERVEURS = ["1445108485090971710",       # YouLab TWITTER
            "1505418484052394004",       # Va IG (serveur FR) : Luigi y est, meme jeton
            "1498948161039896586",       # YouLab THREADS
            "1552152470464110703"]       # YouLab - Entretien


def jeton() -> str:
    t = (os.environ.get("SEVEN_BOT_TOKEN") or "").strip()
    if t:
        return t
    for p in (Path.home() / ".config" / "seven_bot_token",
              Path(__file__).resolve().parent / "data" / "seven_bot_token"):
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


TOKEN = jeton()

# YouLab THREADS a son propre bot, Jarvis, et Siri n'y est plus : avec le seul
# jeton de Siri, l'outil se ferait refuser tout ce qui touche Threads. Chaque
# serveur parle donc avec le bot qui y est.
THREADS_ID = "1498948161039896586"


def jeton_jarvis() -> str:
    t = (os.environ.get("THREADS_BOT_TOKEN") or "").strip()
    if t:
        return t
    for p in (Path.home() / ".config" / "threads_bot_token",
              Path(__file__).resolve().parent / "data" / "threads_bot_token"):
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


TOKEN_JARVIS = jeton_jarvis()
_SALON_SERVEUR = {}          # salon -> serveur, appris en listant les salons


def _jeton_pour(chemin: str) -> str:
    """Le jeton du bot qui est sur le serveur que vise ce chemin."""
    import re as _re
    m = _re.match(r"^/guilds/(\d+)", chemin)
    gid = m.group(1) if m else ""
    if not gid:
        m = _re.match(r"^/channels/(\d+)", chemin)
        gid = _SALON_SERVEUR.get(m.group(1), "") if m else ""
    if gid == THREADS_ID and TOKEN_JARVIS:
        return TOKEN_JARVIS
    return TOKEN


def api(methode: str, chemin: str, corps=None, params=None, entetes=None):
    """(code, données). Ne lève jamais : la page affiche l'erreur.

    `entetes` s'ajoute aux en-têtes habituels : la suppression d'une
    catégorie y met sa raison, pour qu'elle se lise dans le journal d'audit.
    """
    url = API + chemin
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(corps).encode() if corps is not None else None
    if data is None and methode in ("DELETE", "PUT", "PATCH", "POST"):
        # annonce en JSON sans contenu : Discord repond « invalid JSON » (vu en
        # faisant quitter un serveur a Siri). Un corps vide passe partout.
        data = b"{}"
    en_tetes = {"Authorization": "Bot " + _jeton_pour(chemin),
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (youl4b-local, 1.0)"}
    en_tetes.update(entetes or {})
    req = urllib.request.Request(url, data=data, method=methode, headers=en_tetes)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            brut = r.read()
            return r.status, (json.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


def _multipart(payload: dict, fichiers):
    """Encode un envoi avec pièces jointes pour Discord.

    Discord veut du multipart : un champ `payload_json` avec le message, puis
    `files[0]`, `files[1]`… Et dans le message, une liste `attachments` où
    chaque entrée porte l'indice du fichier correspondant — sans elle, les
    images partent mais ne s'affichent pas.
    """
    limite = "----youl4b" + os.urandom(12).hex()
    morceaux = []

    def champ(entete: bytes, contenu: bytes):
        morceaux.append(b"--" + limite.encode() + b"\r\n" + entete + b"\r\n\r\n"
                        + contenu + b"\r\n")

    champ(b'Content-Disposition: form-data; name="payload_json"\r\n'
          b"Content-Type: application/json",
          json.dumps(payload, ensure_ascii=False).encode())
    for i, (nom, octets) in enumerate(fichiers):
        sur = nom.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
        champ(f'Content-Disposition: form-data; name="files[{i}]"; filename="{sur}"'
              .encode() + b"\r\nContent-Type: application/octet-stream", octets)
    morceaux.append(b"--" + limite.encode() + b"--\r\n")
    return b"".join(morceaux), f"multipart/form-data; boundary={limite}"


def api_fichiers(methode: str, chemin: str, payload: dict, fichiers):
    """Comme api(), mais avec des pièces jointes."""
    corps, type_contenu = _multipart(payload, fichiers)
    req = urllib.request.Request(API + chemin, data=corps, method=methode, headers={
        "Authorization": "Bot " + _jeton_pour(chemin), "Content-Type": type_contenu,
        "User-Agent": "DiscordBot (youl4b-local, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            brut = r.read()
            return r.status, (json.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


import re as _re_salons
_re_ticket = _re_salons.compile(r"(^|-)va-[^-]")


def salons(gid: str):
    """Les salons texte, groupés par catégorie — « name » ou « bio » seuls ne
    disent rien, il y en a dans plusieurs catégories."""
    code, rep = api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return []
    for c in rep:
        _SALON_SERVEUR[str(c["id"])] = str(gid)
    cats = {c["id"]: c.get("name") or "" for c in rep if c.get("type") == 4}
    # Va IG : 160 tickets « 🔴-12-va-pseudo » et les catégories d'archives
    # noyaient la liste (on y cherche annonce, rappels, général-<model>…).
    # Un ticket ou une archive n'est pas un salon où l'on publie pour tous.
    textes = [c for c in rep if c.get("type") in (0, 5)
              and not _re_ticket.search(c.get("name") or "")
              and "archives" not in (cats.get(c.get("parent_id")) or "").lower()]
    textes.sort(key=lambda c: (cats.get(c.get("parent_id"), "~"), c.get("position", 0)))
    return [{"id": str(c["id"]), "nom": c.get("name") or "",
             "categorie": cats.get(c.get("parent_id"), "(sans catégorie)")} for c in textes]


def corps_message(texte: str, titre: str, couleur: str, encadre: bool):
    texte = (texte or "").strip()
    mentions = {"parse": ["everyone", "roles", "users"]}
    if not encadre and not titre:
        return {"content": texte[:MAX_TEXTE], "allowed_mentions": mentions}
    try:
        c = int(str(couleur).lstrip("#"), 16) if couleur else COULEUR_DEFAUT
    except ValueError:
        c = COULEUR_DEFAUT
    e = {"description": texte[:MAX_EMBED], "color": c}
    if titre:
        e["title"] = titre[:256]
    return {"embeds": [e], "allowed_mentions": mentions}


def derniers(salon: str, combien: int = 15):
    """Les derniers messages DU BOT : ceux qu'on peut réécrire."""
    code, rep = api("GET", f"/channels/{salon}/messages", params={"limit": 50})
    if code != 200 or not isinstance(rep, list):
        return []
    out = []
    for m in rep:
        if not ((m.get("author") or {}).get("bot")):
            continue
        # sans ça, la liste des messages à reprendre se remplissait de lignes vides
        if (m.get("content") or "").strip() == ESPACE and not m.get("embeds") \
                and not m.get("attachments"):
            continue
        e = (m.get("embeds") or [{}])[0] if m.get("embeds") else {}
        out.append({"id": str(m.get("id")),
                    "date": str(m.get("timestamp") or "")[:16].replace("T", " "),
                    "encadre": bool(m.get("embeds")),
                    "titre": e.get("title") or "",
                    "couleur": f'{int(e.get("color") or 0):06X}' if e.get("color") else "",
                    "texte": e.get("description") or m.get("content") or "",
                    # les images déjà attachées : on les montre pour pouvoir en
                    # retirer une sans reposter tout le message
                    "images": [{"id": str(a.get("id")), "nom": a.get("filename") or "",
                                "url": a.get("url") or ""}
                               for a in (m.get("attachments") or [])]})
        if len(out) >= combien:
            break
    return out


# ------------------------------------------------ supprimer une catégorie
# Supprimer un salon est définitif : Discord n'a pas de corbeille. Ce n'est
# donc jamais le bot qui décide : le propriétaire choisit la catégorie, voit
# la liste, tape son nom à la main, puis clique.
RAISON_SUPPRESSION = "Suppression demandée par le propriétaire depuis l'outil local"
GENRES = {0: "texte", 2: "vocal", 4: "catégorie", 5: "annonces",
          13: "conférence", 15: "forum", 16: "média"}
# ThreadingHTTPServer : un double clic lancerait deux suppressions en même
# temps, chacune comptant des échecs sur les salons déjà partis.
_VERROU_CATEGORIE = threading.Lock()


def _place(c):
    return (c.get("position") or 0, str(c.get("id") or ""))


def _tous_les_salons(gid: str):
    """(liste, erreur) : tous les salons du serveur, relus chez Discord."""
    code, rep = api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return None, "lecture des salons refusée : " + _raison(code, rep)
    for c in rep:
        # sans ça, le DELETE d'un salon de Threads partirait avec le jeton de
        # Siri, qui n'y est plus, et serait refusé
        _SALON_SERVEUR[str(c.get("id"))] = str(gid)
    return rep, ""


def _raison(code, rep) -> str:
    """Le refus de Discord tel qu'il le dit : message, puis code."""
    rep = rep if isinstance(rep, dict) else {}
    msg = str(rep.get("message") or "").strip()
    if code == 0:
        return "Discord injoignable" + (f" : {msg}" if msg else "")
    detail = f"HTTP {code}" + (f", code {rep.get('code')}" if rep.get("code") else "")
    return f"{msg} ({detail})" if msg else detail


def categories(gid: str):
    """Les catégories d'un serveur de l'outil, avec le nom de leurs salons."""
    gid = str(gid or "").strip()
    if gid not in SERVEURS:
        return {"ok": False, "error": "Ce serveur n'est pas un serveur de l'outil."}
    rep, err = _tous_les_salons(gid)
    if rep is None:
        return {"ok": False, "error": err}
    out = []
    for cat in sorted((c for c in rep if c.get("type") == 4), key=_place):
        cid = str(cat.get("id"))
        enfants = sorted((c for c in rep if str(c.get("parent_id") or "") == cid),
                         key=_place)
        out.append({"id": cid, "nom": cat.get("name") or "", "compte": len(enfants),
                    "salons": [c.get("name") or "" for c in enfants]})
    return {"ok": True, "categories": out}


def _trouver_categorie(cid, gid=""):
    """(serveur, catégorie, enfants, erreur), relus chez Discord à l'instant.

    On ne croit jamais la liste envoyée par la page : entre la préparation et
    le clic, un salon a pu être ajouté ou déplacé.
    """
    cid, gid = str(cid or "").strip(), str(gid or "").strip()
    if not cid.isdigit():
        return None, None, None, "Aucune catégorie choisie."
    if gid and gid not in SERVEURS:
        return None, None, None, ("Ce serveur n'est pas un serveur de l'outil : "
                                  "rien n'est supprimé.")
    lectures = []
    for g in ([gid] if gid else SERVEURS):
        rep, err = _tous_les_salons(g)
        if rep is None:
            lectures.append(err)
            continue
        for c in rep:
            if str(c.get("id")) != cid:
                continue
            if c.get("type") != 4:
                return None, None, None, ("Ce n'est pas une catégorie, c'est un salon : "
                                          "rien n'est supprimé.")
            enfants = sorted((x for x in rep if str(x.get("parent_id") or "") == cid),
                             key=_place)
            return g, c, enfants, ""
    ou = "n'est pas sur ce serveur" if gid else "n'est sur aucun serveur de l'outil"
    return None, None, None, (f"Cette catégorie {ou} : rien n'est supprimé."
                              + (" (" + " ; ".join(lectures) + ")" if lectures else ""))


def _effacer(sid: str, entetes):
    """DELETE d'un salon, en respectant le délai que Discord demande (3 essais)."""
    code, rep = 0, {}
    for essai in range(3):
        code, rep = api("DELETE", f"/channels/{sid}", entetes=entetes)
        if code == 429 and essai < 2:
            attente = float((rep if isinstance(rep, dict) else {}).get("retry_after") or 1)
            time.sleep(min(attente, 30.0) + 0.3)
            continue
        break
    return code, rep


# Un lien de message Discord : clic droit sur le message > « Copier le lien du
# message ». Les variantes ptb./canary. et l'ancien discordapp.com y passent.
_LIEN_MESSAGE = _re_salons.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")
# Le lien d'un SALON (la barre d'adresse) : deux numeros, pas trois. Colle par
# erreur, il etait refuse d'un « Lien non reconnu » qui n'expliquait rien.
_LIEN_SALON = _re_salons.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/?(?:[^\d/]|$)")


def _date_id(mid) -> str:
    """L'heure de création d'un message, lue dans son identifiant."""
    try:
        return datetime.fromtimestamp(((int(mid) >> 22) + 1420070400000) / 1000).strftime("%d/%m %Hh%M")
    except Exception:
        return "?"


def _resume(m: dict) -> str:
    """Une ligne pour reconnaître un message dans une question de confirmation."""
    e = (m.get("embeds") or [{}])[0] or {}
    t = " ".join((m.get("content") or e.get("title") or e.get("description") or "").split())[:60]
    if t:
        return t
    n = len(m.get("attachments") or [])
    return f"[{n} photo(s)]" if n else "[message sans texte]"


def _api_patient(methode: str, chemin: str, corps=None, params=None):
    """api(), mais un 429 (« You are being rate limited ») attend le délai que
    Discord donne puis retente, trois fois au plus.

    Le bot partage son jeton avec le site : un 429 tombe sans prévenir, même
    sur la toute première lecture. « Supprimer tout ce qui est au-dessus »
    répondait alors « Message introuvable » sur un message bien là.
    """
    code, rep = 0, {}
    for essai in range(4):
        code, rep = api(methode, chemin, corps, params)
        if code != 429 or essai == 3:
            break
        attente = float((rep if isinstance(rep, dict) else {}).get("retry_after") or 1)
        time.sleep(min(attente, 30.0) + 0.3)
    return code, rep


def _messages_avant(salon: str, mid: str, plafond: int = 500):
    """Les messages du salon plus ANCIENS que `mid` (lui exclu), du plus récent
    au plus ancien. (liste, encore, erreur) — `encore` : le plafond est atteint."""
    out, avant = [], str(mid)
    while len(out) < plafond:
        code, lot = _api_patient("GET", f"/channels/{salon}/messages",
                                 params={"limit": "100", "before": avant})
        if code != 200:
            return out, False, str((lot or {}).get("message") or f"HTTP {code}")[:120]
        if not lot:
            break
        out += lot
        avant = lot[-1]["id"]
        if len(lot) < 100:
            break
    # garde-fou : jamais le message gardé ni un plus récent, quoi que l'API rende
    out = [x for x in out if int(x["id"]) < int(mid)]
    return out[:plafond], len(out) >= plafond, ""


def _effacer_messages(salon: str, ids, fin: float = 0.0):
    """Efface ces messages. (efface, un_par_un, echecs)

    `fin` : heure au-delà de laquelle on s'arrête (voir BUDGET_S) — après au
    moins une action, pour que chaque tranche avance.

    Discord refuse d'effacer en lot un message de plus de 14 jours : ceux-là
    partent un par un, plus lentement, et sont comptés à part pour que le
    compte rendu colle à ce qui s'est vraiment passé. Un lot refusé retombe en
    un par un plutôt que d'être perdu.
    """
    efface, un_par_un, echecs = 0, 0, []
    # l'heure de création est dans l'identifiant lui-même
    recents = [i for i in ids
               if (int(i) >> 22) + 1420070400000 > (time.time() - 13.5 * 86400) * 1000]
    vieux = [i for i in ids if i not in set(recents)]
    def _assez():
        return bool(fin) and time.time() > fin and bool(efface or echecs)
    for k in range(0, len(recents), 100):
        if _assez():
            return efface, un_par_un, echecs
        lot = recents[k:k + 100]
        if len(lot) < 2:                 # le lot exige au moins deux messages
            vieux = lot + vieux
            continue
        c, rep = _api_patient("POST", f"/channels/{salon}/messages/bulk-delete", {"messages": lot})
        if c in (200, 204):
            efface += len(lot)
        else:
            echecs.append(str((rep or {}).get("message") or f"lot : HTTP {c}")[:120])
            vieux = lot + vieux          # le lot a echoue : un par un
    for mid in vieux:
        if _assez():
            break
        c, rep = _api_patient("DELETE", f"/channels/{salon}/messages/{mid}")
        if c in (200, 204):
            efface += 1
            un_par_un += 1
        else:
            echecs.append(f"{mid} : " + str((rep or {}).get("message") or f"HTTP {c}")[:80])
        time.sleep(1.1)
    return efface, un_par_un, echecs


def _journal(ligne: str):
    """Une ligne par suppression dans le terminal, sans jamais tout arrêter.

    Un terminal qui n'accepte pas l'emoji d'un nom de salon lèverait une
    erreur d'encodage AU MILIEU de la boucle : la moitié des salons partis,
    et la page sans compte rendu.
    """
    try:
        print(ligne, flush=True)
    except Exception:
        try:
            print(ligne.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass


def supprimer_salons_puis_categorie(gid: str, cid: str, nom: str, liste):
    """Supprime chaque salon de `liste`, puis la catégorie si elle est vide.

    La catégorie ne part qu'une fois vide, relue chez Discord : supprimée
    avec un salon dedans, Discord laisse ce salon en vrac en haut du serveur,
    visible de tous. Un salon raté est nommé, avec la raison que Discord donne.
    """
    entetes = {"X-Audit-Log-Reason": urllib.parse.quote(RAISON_SUPPRESSION, safe="")}
    supprimes, echecs = [], []
    for s in liste:
        code, rep = _effacer(s["id"], entetes)
        if code in (200, 204):
            supprimes.append(s["nom"])
            _journal(f"[supprimer catégorie] « {nom} » : salon #{s['nom']} ({s['id']}) supprimé")
        else:
            raison = _raison(code, rep)
            echecs.append({"nom": s["nom"], "id": s["id"], "raison": raison})
            _journal(f"[supprimer catégorie] « {nom} » : salon #{s['nom']} ({s['id']}) "
                     f"PAS supprimé — {raison}")
        time.sleep(0.6)       # Discord coupe vite une rafale de suppressions

    out = {"categorie": nom, "id": cid, "total": len(liste), "supprimes": supprimes,
           "echecs": echecs, "categorie_supprimee": False, "reste": [], "motif": ""}
    if echecs:
        out["reste"] = [e["nom"] for e in echecs]
        out["motif"] = (f"catégorie gardée : {len(echecs)} salon(s) n'ont pas pu "
                        "être supprimés")
    else:
        rep, err = _tous_les_salons(gid)
        if rep is None:
            out["motif"] = "catégorie gardée : impossible de vérifier qu'elle est vide (" + err + ")"
        else:
            out["reste"] = [c.get("name") or "" for c in sorted(rep, key=_place)
                            if str(c.get("parent_id") or "") == cid]
            if out["reste"]:
                out["motif"] = (f"catégorie gardée : il y reste {len(out['reste'])} "
                                "salon(s), arrivés entre-temps — prépare à nouveau")
            else:
                code, rep = _effacer(cid, entetes)
                if code in (200, 204):
                    out["categorie_supprimee"] = True
                    _journal(f"[supprimer catégorie] catégorie « {nom} » ({cid}) supprimée")
                else:
                    out["motif"] = "catégorie gardée : " + _raison(code, rep)
                    _journal(f"[supprimer catégorie] catégorie « {nom} » ({cid}) "
                             f"PAS supprimée — {_raison(code, rep)}")
    out["ok"] = not echecs and out["categorie_supprimee"]
    return out


PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Écrire dans un salon Discord</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--fond:#0b0b10;--carte:#161620;--bord:#2a2a3a;--texte:#e8e8f0;--faible:#8b8ba0;--bleu:#5865F2;--vert:#22c55e;--rouge:#ef4444}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px}
h1{font-size:19px;margin:0 0 4px}
.sous{color:var(--faible);font-size:13px;margin:0 0 20px}
.grille{display:grid;grid-template-columns:1fr 340px;gap:20px;max-width:1180px}
@media(max-width:900px){.grille{grid-template-columns:1fr}}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:14px;padding:16px}
label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--faible);font-weight:700;margin:12px 0 5px}
select,input,textarea{width:100%;padding:10px 12px;background:#0f0f18;border:1px solid var(--bord);color:var(--texte);border-radius:9px;font:inherit}
textarea{min-height:190px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px}
.ligne{display:flex;gap:10px;align-items:end;flex-wrap:wrap}
.ligne>*{flex:1;min-width:120px}
button{padding:11px 18px;border:0;border-radius:9px;font-weight:700;cursor:pointer;font-size:14px}
.envoyer{background:var(--bleu);color:#fff}
.gris{background:#26263a;color:var(--texte)}
.rouge{background:var(--rouge);color:#fff}
.confirme-zone{margin-top:14px;padding:12px 14px;border:1px solid var(--rouge);border-radius:10px;
               font-size:13.5px;line-height:1.55}
.confirme-zone #audessus-texte{white-space:pre-line}
.confirme-boutons{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.confirme-boutons button{font-size:13px;padding:8px 14px}
button:disabled{opacity:.5;cursor:default}
.etat{margin-top:12px;font-size:13.5px;min-height:20px}
.ok{color:var(--vert)}.ko{color:var(--rouge)}
.msg{background:#0f0f18;border:1px solid var(--bord);border-left:3px solid var(--bleu);border-radius:9px;padding:9px 11px;margin-bottom:8px;cursor:pointer}
.msg:hover{background:#151522}
.msg .q{font-size:11px;color:var(--faible)}
.msg .t{font-size:13px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.compte{font-size:11.5px;color:var(--faible);text-align:right;margin-top:4px}
.apercu{background:#0f0f18;border:1px solid var(--bord);border-radius:9px;padding:12px;margin-top:10px;white-space:pre-wrap;font-size:14px;min-height:40px}
.apercu.encadre{border-left:4px solid var(--bleu)}
.apercu .titre{font-weight:700;margin-bottom:6px}
.depot{margin-top:12px;border:2px dashed var(--bord);border-radius:11px;padding:16px;text-align:center;color:var(--faible);font-size:13px;cursor:pointer}
.depot:hover,.depot.survol{border-color:var(--bleu);color:var(--texte);background:rgba(88,101,242,.07)}
.vignettes{display:flex;gap:9px;flex-wrap:wrap;margin-top:10px}
.vignette{position:relative;width:78px;height:78px;border-radius:9px;overflow:hidden;border:1px solid var(--bord)}
.vignette img{width:100%;height:100%;object-fit:cover;display:block}
.vignette .x{position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.72);color:#fff;border:0;font-size:13px;line-height:20px;padding:0;cursor:pointer}
.vignette .v{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.6);color:#9fd3ff;font-size:9px;text-align:center}
.onglets{display:flex;gap:6px;margin-bottom:14px}
.onglets button{background:#0f0f18;color:var(--faible);border:1px solid var(--bord);font-size:13px;padding:8px 14px}
.onglets button.actif{background:var(--bleu);color:#fff;border-color:var(--bleu)}
.bout{background:#0f0f18;border:1px solid var(--bord);border-left:3px solid var(--bleu);border-radius:8px;padding:8px 11px;margin-bottom:7px;display:flex;gap:9px;align-items:start}
.bout .n{color:var(--faible);font-size:11px;font-weight:700;min-width:22px;padding-top:2px}
.bout .c{flex:1;font-size:13px;white-space:pre-wrap;word-break:break-word}
.bout .x{background:transparent;border:0;color:var(--faible);cursor:pointer;font-size:14px;padding:0 4px}
.bout .x:hover{color:var(--rouge)}
.bout.trop{border-left-color:var(--rouge)}
.bout .mini{width:44px;height:44px;object-fit:cover;border-radius:6px;flex:none;
            background:#000}
.bout.photo{border-left-color:#22c55e}
.lien{background:transparent;border:0;color:var(--bleu);font-size:12px;padding:0;
      text-decoration:underline;cursor:pointer;width:auto}
.liste-bouts{max-height:420px;overflow:auto;margin-top:10px}
.case{display:flex;align-items:center;gap:8px;margin-top:11px;color:var(--faible);
      font-size:12px;text-transform:none;letter-spacing:0;cursor:pointer}
.case input{width:auto;margin:0;flex:none}
.case span{flex:1}
.case b{color:var(--texte)}
.danger{display:flex;align-items:center;gap:10px;margin-top:16px;padding-top:14px;
        border-top:1px solid var(--bord);flex-wrap:wrap}
.danger span{color:var(--faible);font-size:11px;line-height:1.45}
.danger button{background:transparent;border:1px solid var(--rouge);color:var(--rouge);
               font-size:12px;padding:7px 13px;white-space:nowrap}
.danger button:hover{background:var(--rouge);color:#fff}
.outil{display:flex;align-items:center;gap:10px;margin-top:16px;flex-wrap:wrap}
.outil span{color:var(--faible);font-size:11px;line-height:1.45}
.outil button{font-size:12px;padding:7px 13px;white-space:nowrap}
.zone-cat{max-width:1180px;margin-top:20px;border-color:rgba(239,68,68,.45)}
.zone-cat h2{font-size:16px;margin:0 0 4px;color:var(--rouge)}
.zone-cat .ligne>.bouton-seul{flex:none;min-width:0}
.catliste{margin-top:12px;background:#0f0f18;border:1px solid var(--bord);border-radius:9px;
          padding:10px 12px;font-size:13px}
.catliste ol{margin:8px 0 0;padding-left:26px;max-height:260px;overflow:auto}
.catliste li{padding:1px 0;word-break:break-word}
.catliste .g{color:var(--faible);font-size:11.5px;margin-left:6px}
.nomattendu{font-weight:700;user-select:all;-webkit-user-select:all}
.echecs{margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--rouge)}
</style></head><body>
<h1>Écrire dans un salon Discord</h1>
<p class="sous">Le message est posté par le bot du serveur (<b>Luigi</b>). Tout se passe sur ta machine — rien n'est déployé.
<span style="opacity:.55">· outil du __DATE__</span></p>
<div class="grille">
  <div class="carte">
    <div class="onglets">
      <button id="onglet-un" class="actif">Un message</button>
      <button id="onglet-lot">Coller en masse</button>
    </div>
    <div class="ligne">
      <div><label>Serveur</label><select id="serveur"></select></div>
      <div><label>Salon</label><select id="salon"></select></div>
    </div>
    <div class="ligne" id="zone-titre">
      <div style="flex:2"><label>Titre <span style="text-transform:none">(vide = message simple, sans encadré)</span></label>
        <input id="titre" placeholder="ex : Infos modèle — Lola"></div>
      <div style="max-width:130px"><label>Couleur</label><input id="couleur" placeholder="5865F2"></div>
    </div>
    <div id="zone-un">
    <label>Message <span style="text-transform:none">— gras **texte**, lien &lt;#salon&gt;, saut de ligne accepté</span></label>
    <textarea id="texte" placeholder="Écris ici…"></textarea>
    <div class="compte" id="compte"></div>
    <div class="depot" id="depot">Glisse tes photos ici, ou clique pour les choisir · 10 max, 9 Mo chacune</div>
    <input type="file" id="fichiers" accept="image/*,video/*" multiple style="display:none">
    <div class="vignettes" id="vignettes"></div>
    <div class="apercu" id="apercu"></div>
    </div>

    <div id="zone-lot" style="display:none">
      <div class="ligne">
        <div><label>Separation</label><select id="sep">
          <option value="auto">Automatique (devine)</option>
          <option value="vide">Ligne vide entre chaque</option>
          <option value="ligne">Un par ligne</option>
          <option value="lien">Une URL par message (le reste est ignore)</option>
          <option value="num">Numerotation (1. 2. 3.)</option>
          <option value="point">Un point suivi d'un espace</option>
          <option value="perso">Separateur a moi</option>
        </select></div>
        <div style="max-width:170px"><label>Lequel</label>
          <input id="sepperso" placeholder="ex : ---" disabled></div>
      </div>
      <label>Colle tout ici <span style="text-transform:none">&mdash; un message par morceau, poste dans l'ordre</span></label>
      <textarea id="brut" placeholder="Colle tes captions, tes liens, tes bios&hellip;"></textarea>
      <div class="compte" id="comptelot"></div>
      <div class="depot" id="depotlot">Glisse tes photos ici, colle-les au clavier (Cmd+V),
        ou clique pour les choisir <span style="opacity:.6">(Cmd+A pour tout prendre)</span>
        &middot; une photo = un message &middot; jusqu'a 300 &middot; 9 Mo chacune
        <div style="margin-top:7px"><button type="button" id="dossier" class="lien">ou choisir un dossier entier</button></div></div>
      <input type="file" id="fichierslot" accept="image/*,video/*" multiple style="display:none">
      <input type="file" id="fichiersdoss" webkitdirectory directory multiple style="display:none">
      <label class="case"><input type="checkbox" id="espace" checked>
        <span>Laisser une <b>ligne vide</b> entre chaque message</span></label>
      <label class="case"><input type="checkbox" id="copier">
        <span>Poser un bouton <b>Copier</b> sous chaque message</span></label>
      <div class="liste-bouts" id="bouts"></div>
    </div>

    <div class="ligne" style="margin-top:14px">
      <button class="envoyer" id="envoyer">Poster</button>
      <button class="gris" id="annuler" style="display:none">Nouveau message</button>
      <button class="rouge" id="supprimer" style="display:none">Supprimer</button>
    </div>
    <div class="outil">
      <button class="gris" id="retirercopier">Retirer les boutons Copier</button>
      <span>enleve le bouton sous les messages deja postes dans ce salon &mdash; le texte et les photos restent</span>
    </div>
    <div class="danger">
      <button class="rouge" id="vider">Vider ce salon</button>
      <span>efface TOUS les messages du salon choisi — il te dit combien avant</span>
    </div>
    <div class="danger">
      <input id="lienhaut" placeholder="lien du premier message a garder" autocomplete="off"
             spellcheck="false" style="flex:1;min-width:240px">
      <button class="rouge" id="audessus">Supprimer tout ce qui est au-dessus</button>
      <span>garde ce message et tout ce qui suit &mdash; sur Discord : clic droit sur le message
        &gt; Copier le lien du message. Il te dit combien avant.</span>
    </div>
    <!-- Confirmation DANS la page, pas confirm() : Chrome peut bloquer les
         boites de dialogue d'une page (case « Empecher cette page… »), et
         confirm() rend alors faux sans rien montrer -- vu en vrai : un clic,
         et rien. -->
    <div id="audessus-ok" class="confirme-zone" style="display:none">
      <div id="audessus-texte"></div>
      <div class="confirme-boutons">
        <button class="rouge" id="audessus-oui">Oui, supprimer</button>
        <button class="gris" id="audessus-non">Annuler</button>
      </div>
    </div>
    <div class="etat" id="etat"></div>
  </div>
  <div class="carte">
    <label style="margin-top:0">Derniers messages du bot dans ce salon</label>
    <p class="sous" style="margin:0 0 10px">Clique pour le reprendre et le corriger.</p>
    <div id="liste"></div>
  </div>
</div>
<div class="carte zone-cat" id="zone-cat">
  <h2>Supprimer une catégorie</h2>
  <p class="sous" style="margin:0">Supprime la catégorie <b>et tous ses salons</b>. C'est définitif : Discord n'a pas de corbeille.
    Rien ne part tant que tu n'as pas tapé son nom.</p>
  <div class="ligne">
    <div><label>Serveur</label><select id="catserveur"></select></div>
    <div style="flex:2;min-width:200px"><label>Catégorie</label><select id="categorie"></select></div>
    <div class="bouton-seul"><button class="gris" id="preparer">Préparer</button></div>
  </div>
  <div id="catliste"></div>
  <div id="catconfirm" style="display:none">
    <label for="nomtape">Tape le nom exact de la catégorie</label>
    <input id="nomtape" placeholder="tape le nom exact de la catégorie" autocomplete="off" spellcheck="false">
    <div class="compte" id="catindice" style="text-align:left"></div>
    <div class="ligne" style="margin-top:12px">
      <div class="bouton-seul"><button class="rouge" id="supprimercat" disabled>Supprimer définitivement</button></div>
    </div>
  </div>
  <div class="etat" id="catetat"></div>
  <div id="catresultat"></div>
</div>
<script>
var E = function(i){ return document.getElementById(i); };
var enCours = null;   // l'id du message qu'on est en train de corriger
var neuves = [];      // images ajoutées maintenant : {nom, b64, url}
var gardees = [];     // images déjà attachées qu'on garde : {id, nom, url}

function vignettes(){
  var z = E('vignettes'); z.innerHTML = '';
  function carte(src, legende, retirer){
    var d = document.createElement('div'); d.className = 'vignette';
    var i = document.createElement('img'); i.src = src; d.appendChild(i);
    if(legende){ var v = document.createElement('div'); v.className = 'v'; v.textContent = legende; d.appendChild(v); }
    var b = document.createElement('button'); b.className = 'x'; b.textContent = '✕';
    b.title = 'Retirer'; b.onclick = retirer; d.appendChild(b);
    z.appendChild(d);
  }
  gardees.forEach(function(g, i){
    carte(g.url, 'déjà là', function(){ gardees.splice(i, 1); vignettes(); });
  });
  neuves.forEach(function(n, i){
    carte(n.url, '', function(){ neuves.splice(i, 1); vignettes(); });
  });
}

function ajouter(liste){
  var restant = 10 - (neuves.length + gardees.length);
  Array.prototype.slice.call(liste, 0, Math.max(0, restant)).forEach(function(f){
    var lect = new FileReader();
    lect.onload = function(){
      var s = String(lect.result);
      neuves.push({nom: f.name, b64: s.slice(s.indexOf(',') + 1), url: s});
      vignettes();
    };
    lect.readAsDataURL(f);
  });
  if(restant <= 0) etat('10 fichiers au maximum par message.', 'ko');
}

E('depot').onclick = function(){ E('fichiers').click(); };
E('fichiers').onchange = function(){ ajouter(this.files); this.value = ''; };
['dragenter','dragover'].forEach(function(e){
  E('depot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.add('survol'); });
});
['dragleave','drop'].forEach(function(e){
  E('depot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.remove('survol'); });
});
E('depot').addEventListener('drop', function(ev){ ajouter(ev.dataTransfer.files); });
// déposer n'importe où dans la page marche aussi, sans ouvrir le fichier
document.addEventListener('dragover', function(e){ e.preventDefault(); });
document.addEventListener('drop', function(e){
  e.preventDefault();
  if(e.target.closest && e.target.closest('#depot')) return;
  if(e.target.closest && e.target.closest('#depotlot')) return;
  if(!e.dataTransfer) return;
  deposer(e, modeLot);
});

function etat(txt, classe){ var e = E('etat'); e.textContent = txt; e.className = 'etat ' + (classe || ''); }

function apercu(){
  var t = E('texte').value, ti = E('titre').value.trim(), c = E('couleur').value.trim();
  var a = E('apercu');
  a.className = 'apercu' + (ti ? ' encadre' : '');
  a.style.borderLeftColor = ti ? ('#' + (c || '5865F2')) : '';
  a.textContent = '';
  if(ti){ var d = document.createElement('div'); d.className = 'titre'; d.textContent = ti; a.appendChild(d); }
  a.appendChild(document.createTextNode(t));
  var max = ti ? 4096 : 2000;
  E('compte').textContent = t.length + ' / ' + max + (t.length > max ? ' — le surplus sera coupé' : '');
  E('compte').style.color = t.length > max ? '#ef4444' : '';
}

var modeLot = false;
var lot = [];   // les morceaux du collage, dans l'ordre ou ils partiront

var NOMS = {num:'numerotation', vide:'ligne vide', ligne:'une par ligne',
            lien:'une URL par message', point:'point suivi d un espace',
            perso:'ton separateur'};

// Discord n'interprete PAS [texte](url) dans un message simple : il l'affiche
// tel quel, et le lien n'est pas cliquable. Une URL nue l'est. On ramene donc
// tout lien masque a son URL — le libelle reste devant quand il dit autre chose.
var RE_MASQUE = /\[([^\]\n]*)\]\((<?)(https?:\/\/[^)\s]+?)>?\)/g;
var remisAPlat = 0;

function nettoyerLiens(m){
  return m.replace(RE_MASQUE, function(_, t, __, u){
    remisAPlat++;
    t = t.trim().replace(/\/+$/, '');
    return (!t || t === u.replace(/\/+$/, '')) ? u : (t + ' ' + u);
  });
}

// Un collage venu d'un tableur, d'une note ou d'un doc traine toujours des
// restes : une puce, un numero, des guillemets autour de tout, deux espaces,
// des caracteres invisibles. Ils partiraient tels quels dans le message.
var nettoyes = 0;
var PAIRES = [['"','"'], ['“','”'], ['«','»'], ["'","'"]];

function nettoyerBrut(m){
  var avant = m;
  m = m.replace(/[​-‏⁠﻿]/g, '');
  // une puce ou un numero EN TETE seulement, et suivi d'une espace : une
  // caption qui commence par un tiret volontaire n'est pas touchee
  m = m.replace(/^\s*(?:[-–—*•·>]|\d{1,3}[.)])[ \t]+/, '');
  m = m.trim();
  // des guillemets qui enferment TOUT le morceau : ceux du texte restent
  for(var i = 0; i < PAIRES.length; i++){
    if(m.length > 1 && m.charAt(0) === PAIRES[i][0] && m.charAt(m.length - 1) === PAIRES[i][1]){
      m = m.slice(1, -1).trim(); break;
    }
  }
  m = m.replace(/[ \t]{2,}/g, ' ');
  if(m !== avant) nettoyes++;
  return m;
}

function detecter(t){
  // la numerotation passe avant la ligne vide : une liste numerotee dont les
  // items sont espaces garderait sinon son "1." colle au debut du message
  if((t.match(/(?:^|\n)[ \t]*\d{1,3}[ \t]*[.)\-][ \t]+/g) || []).length >= 2) return 'num';
  if(/\n[ \t]*\n/.test(t)) return 'vide';
  if(/\n/.test(t)) return 'ligne';
  if((t.match(/https?:\/\//g) || []).length >= 2) return 'lien';
  return 'point';
}

function decouper(t, mode, perso){
  t = String(t || '');
  if(!t.trim()) return [];
  if(mode === 'auto') mode = detecter(t);
  var b;
  if(mode === 'num')        b = t.split(/(?:^|\n)[ \t]*\d{1,3}[ \t]*[.)\-][ \t]+/);
  else if(mode === 'vide')  b = t.split(/\n[ \t]*\n+/);
  else if(mode === 'ligne') b = t.split(/\n+/);
  // une liste de liens collee d'un bloc : on prend les URL une par une
  else if(mode === 'lien')  b = (nettoyerLiens(t).match(/https?:\/\/\S+/g) || []);
  // un point colle a un chiffre ("daddy-19.9") n'est pas une fin de phrase :
  // on ne coupe que sur un point suivi d'une espace
  else if(mode === 'point') b = t.replace(/([.!?…])[ \t]+/g, '$1\u0000').split('\u0000');
  else if(mode === 'perso') b = perso ? t.split(perso) : [t];
  else b = [t];
  remisAPlat = 0; nettoyes = 0;
  return b.map(function(x){ return nettoyerBrut(nettoyerLiens(x.trim())); })
          .filter(function(x){ return x.length; });
}

var photos = [];      // les photos du mode masse : {nom, b64, url}
var apparie = false;  // une caption sous chaque photo, ou chacun son message

// Une photo et une caption vont ensemble quand il y en a autant des deux :
// c'est le cas du contenu legende. Sinon on ne devine pas, on met les textes
// puis les photos, et on le DIT au-dessus de l'apercu.
function composer(){
  var textes = decouper(E('brut').value, E('sep').value, E('sepperso').value);
  var items = [];
  apparie = photos.length > 0 && textes.length === photos.length;
  if(apparie){
    photos.forEach(function(p, i){ items.push({texte: textes[i], photo: p}); });
  } else {
    textes.forEach(function(t){ items.push({texte: t, photo: null}); });
    photos.forEach(function(p){ items.push({texte: '', photo: p}); });
  }
  return items;
}

var MEDIA = /\.(jpe?g|png|gif|webp|heic|heif|bmp|mp4|mov|m4v|webm)$/i;

function ajouterLot(liste){
  var tous = Array.prototype.slice.call(liste);
  // un dossier apporte des .DS_Store, des .txt, des miniatures : on les ecarte,
  // mais on DIT combien, sinon on cherche pourquoi il en manque
  var gardes = tous.filter(function(f){ return MEDIA.test(f.name) && f.size > 0; });
  var ecartes = tous.length - gardes.length;
  var restant = 300 - photos.length;
  var refuses = [];
  gardes.sort(function(a, b){ return a.name.localeCompare(b.name, 'fr', {numeric: true}); });
  gardes.forEach(function(f, i){
    if(i >= restant){ refuses.push(f.name); return; }
    // La place est prise TOUT DE SUITE, dans l'ordre des noms : les lectures
    // finissent dans le desordre, et une caption se retrouvait sous la photo
    // d'a cote. On remplit la case reservee quand la lecture arrive.
    var place = {nom: f.name, b64: '', url: '', octets: f.size, pret: false};
    photos.push(place);
    var lect = new FileReader();
    lect.onload = function(){
      var s = String(lect.result);
      place.b64 = s.slice(s.indexOf(',') + 1);
      place.url = s;
      place.pret = true;
      rendreLot();
    };
    lect.onerror = function(){
      place.pret = 'erreur';
      rendreLot();
    };
    lect.readAsDataURL(f);
  });
  rendreLot();
  var dits = [];
  if(ecartes) dits.push(ecartes + ' fichier(s) ecarte(s) : ni photo ni video');
  if(refuses.length) dits.push(refuses.length + ' en trop (300 au maximum)');
  if(dits.length) etat(gardes.length - refuses.length + ' photo(s) prise(s) · '
                       + dits.join(' · '), refuses.length ? 'ko' : '');
}

function rendreLot(recalculer){
  if(recalculer !== false) lot = composer();
  var z = E('bouts'); z.innerHTML = '';
  lot.forEach(function(m, i){
    var d = document.createElement('div');
    d.className = 'bout' + (m.texte.length > 2000 ? ' trop' : '')
                + (m.photo && !m.texte ? ' photo' : '');
    var n = document.createElement('div'); n.className = 'n'; n.textContent = (i + 1) + '.';
    d.appendChild(n);
    if(m.photo && m.photo.url){
      var im = document.createElement('img'); im.className = 'mini'; im.src = m.photo.url;
      d.appendChild(im);
    } else if(m.photo){
      var at = document.createElement('div'); at.className = 'mini';
      at.style.cssText += ';display:flex;align-items:center;justify-content:center;'
                        + 'color:var(--faible);font-size:10px';
      at.textContent = m.photo.pret === 'erreur' ? '✕' : '…';
      d.appendChild(at);
    }
    var c = document.createElement('div'); c.className = 'c';
    c.textContent = m.texte || (m.photo ? m.photo.nom : '');
    if(!m.texte && m.photo) c.style.color = 'var(--faible)';
    var x = document.createElement('button'); x.className = 'x'; x.textContent = '✕';
    x.title = 'Ne pas envoyer celui-la';
    x.onclick = function(){
      // on retire aussi la photo de la reserve, sinon elle revient au recalcul
      if(m.photo){ var k = photos.indexOf(m.photo); if(k >= 0) photos.splice(k, 1); }
      lot.splice(i, 1); rendreLot(false);
    };
    d.appendChild(c); d.appendChild(x);
    z.appendChild(d);
  });
  var e = E('comptelot');
  if(!lot.length){ e.textContent = E('brut').value.trim() ? 'Rien a decouper.' : ''; e.style.color = ''; return; }
  var avecTexte = lot.filter(function(x){ return x.texte; }).length;
  var avecPhoto = lot.filter(function(x){ return x.photo; }).length;
  var trop = lot.filter(function(x){ return x.texte.length > 2000; }).length;
  var lourdes = photos.filter(function(p){ return p.octets > 9 * 1024 * 1024; });
  // chaque ligne vide est un message de plus, avec sa seconde d attente
  var secondes = Math.ceil(lot.length * 1.1 + avecPhoto * 0.4
                           + (E('espace').checked ? (lot.length - 1) * 1.1 : 0));
  var txt = lot.length + ' message' + (lot.length > 1 ? 's' : '');
  if(avecTexte){
    var m = E('sep').value === 'auto' ? detecter(E('brut').value) : E('sep').value;
    txt += ' · coupe sur : ' + (NOMS[m] || m);
    if(m === 'lien') txt += ' (seules les URL sont gardees)';
  }
  if(avecPhoto) txt += ' · ' + avecPhoto + ' photo(s) triee(s) par nom, ' +
    (apparie ? 'chacune avec la caption en face' : 'une par message');
  txt += ' · environ ' + secondes + ' s d envoi';
  if(remisAPlat) txt += ' · ' + remisAPlat + ' lien(s) [..](..) remis a plat pour rester cliquables';
  if(nettoyes) txt += ' · ' + nettoyes + ' morceau(x) nettoye(s) : puce, numero, guillemets, espaces en trop';
  if(trop) txt += ' · ' + trop + ' depasse(nt) 2000 caracteres, le surplus sera coupe';
  if(lourdes.length) txt += ' · ' + lourdes.length + ' photo(s) de plus de 9 Mo seront refusee(s) par Discord : '
                          + lourdes.slice(0, 2).map(function(p){ return p.nom; }).join(', ');
  if(lot.length > 300) txt += ' · trop d un coup : 300 au maximum';
  e.textContent = txt;
  e.style.color = (trop || lourdes.length || lot.length > 300) ? '#ef4444' : '';
}

function basculer(versLot){
  modeLot = versLot;
  nouveau();
  if(!versLot){ photos = []; lot = []; }
  E('onglet-lot').className = versLot ? 'actif' : '';
  E('onglet-un').className  = versLot ? '' : 'actif';
  E('zone-lot').style.display   = versLot ? '' : 'none';
  E('zone-un').style.display    = versLot ? 'none' : '';
  E('zone-titre').style.display = versLot ? 'none' : '';
  E('envoyer').textContent = versLot ? 'Poster les messages' : 'Poster';
  if(versLot) rendreLot();
}

async function demander(chemin, corps){
  // relatif : sous youl4b.com/outil-discord/, « /salons » partait vers le
  // site lui-meme au lieu de l outil
  chemin = String(chemin).replace(/^\//, '');
  var r, t;
  try {
    r = await fetch(chemin, corps ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(corps)} : undefined);
    t = await r.text();
  } catch(e){
    return {ok: false, error: 'L outil ne repond pas (connexion coupee). Le travail continue peut-etre : verifie le salon avant de relancer.'};
  }
  // En ligne, Cloudflare renvoie une page HTML (524) si l outil tarde : r.json()
  // levait une erreur et la page restait figee sur « en cours ».
  try { return JSON.parse(t); }
  catch(e){ return {ok: false, error: 'Reponse illisible (HTTP ' + r.status + ') : le travail continue peut-etre sur le serveur, verifie le salon avant de relancer.'}; }
}

async function chargerSalons(){
  E('salon').innerHTML = '<option>…</option>';
  var j = await demander('/salons?g=' + encodeURIComponent(E('serveur').value));
  E('salon').innerHTML = '';
  var cat = null;
  (j.salons || []).forEach(function(s){
    if(s.categorie !== cat){ cat = s.categorie;
      var g = document.createElement('optgroup'); g.label = cat; g.id = 'g-' + cat; E('salon').appendChild(g); }
    var o = document.createElement('option'); o.value = s.id; o.textContent = s.nom;
    E('salon').lastChild.appendChild(o);
  });
  if(!(j.salons || []).length) etat('Aucun salon lisible sur ce serveur.', 'ko');
  chargerMessages();
}

async function chargerMessages(){
  E('liste').innerHTML = '<p class="sous">…</p>';
  var j = await demander('/messages?c=' + encodeURIComponent(E('salon').value));
  E('liste').innerHTML = '';
  if(!(j.messages || []).length){ E('liste').innerHTML = '<p class="sous">Le bot n\'a rien posté ici.</p>'; return; }
  j.messages.forEach(function(m){
    var d = document.createElement('div'); d.className = 'msg';
    var q = document.createElement('div'); q.className = 'q';
    q.textContent = m.date + (m.encadre ? ' · encadré' : '');
    var t = document.createElement('div'); t.className = 't';
    t.textContent = m.titre || m.texte.split('\n')[0] || '(vide)';
    d.appendChild(q); d.appendChild(t);
    d.onclick = function(){
      // reprendre un message en mode collage n'aurait pas de sens : on revient
      if(modeLot) basculer(false);
      enCours = m.id;
      E('titre').value = m.titre || ''; E('couleur').value = m.couleur || '';
      E('texte').value = m.texte;
      neuves = []; gardees = (m.images || []).slice();
      E('envoyer').textContent = 'Enregistrer la correction';
      E('annuler').style.display = ''; E('supprimer').style.display = '';
      etat('Tu corriges un message déjà posté.', '');
      apercu(); vignettes(); window.scrollTo(0, 0);
    };
    E('liste').appendChild(d);
  });
}

function nouveau(){
  enCours = null;
  E('titre').value = ''; E('couleur').value = ''; E('texte').value = '';
  neuves = []; gardees = [];
  E('envoyer').textContent = 'Poster';
  E('annuler').style.display = 'none'; E('supprimer').style.display = 'none';
  etat(''); apercu(); vignettes();
}

// Une photo encodee pese un tiers de plus que le fichier : tout envoyer dans
// une seule requete bloquait la page sans rien afficher. On decoupe en
// tranches d'environ 20 Mo, ce qui donne aussi l'avancement au fil de l'eau.
function tranches(items){
  var out = [], cour = [], poids = 0;
  items.forEach(function(it){
    var p = it.photo ? it.photo.b64.length : it.texte.length;
    if(cour.length && (poids + p > 20 * 1024 * 1024 || cour.length >= 10)){
      out.push(cour); cour = []; poids = 0;
    }
    cour.push(it); poids += p;
  });
  if(cour.length) out.push(cour);
  return out;
}

async function envoyerLot(bouton){
  if(!lot.length){ etat('Rien a envoyer : colle ton texte ou depose des photos.', 'ko'); return; }
  if(lot.length > 300){ etat(lot.length + ' messages : trop d un coup (300 au maximum).', 'ko'); return; }
  var pasPretes = lot.filter(function(x){ return x.photo && !x.photo.b64; });
  if(pasPretes.length){
    var casse = pasPretes.filter(function(x){ return x.photo.pret === 'erreur'; });
    etat(casse.length
         ? casse.length + ' photo(s) illisible(s) : ' + casse.slice(0,3).map(function(x){ return x.photo.nom; }).join(', ')
           + ' — retire-les avec la croix.'
         : pasPretes.length + ' photo(s) encore en lecture — attends une seconde.',
         casse.length ? 'ko' : '');
    return;
  }
  var nbPhotos = lot.filter(function(x){ return x.photo; }).length;
  if(!confirm('Poster ' + lot.length + ' messages'
              + (nbPhotos ? ' (dont ' + nbPhotos + ' avec photo)' : '')
              + ', un par un, dans ce salon ?')) return;
  bouton.disabled = true;
  var paquets = tranches(lot), envoyes = 0, echecs = [], fait = 0, espacesRates = 0;
  for(var t = 0; t < paquets.length; t++){
    etat('Envoi… ' + fait + ' / ' + lot.length + ' — laisse la page ouverte.');
    var j = await demander('/poster_lot', {
      salon: E('salon').value, copier: E('copier').checked,
      espace: E('espace').checked, depart: fait,
      messages: paquets[t].map(function(it){
        return {texte: it.texte,
                image: it.photo ? {nom: it.photo.nom, b64: it.photo.b64} : null};
      })});
    if(j.error && !j.envoyes){
      // la tranche entiere a echoue : on s arrete plutot que de continuer en aveugle
      etat('✕ ' + j.error + ' — arrete a ' + envoyes + ' / ' + lot.length, 'ko');
      bouton.disabled = false; chargerMessages(); return;
    }
    envoyes += (j.envoyes || 0);
    espacesRates += (j.espaces_rates || 0);
    echecs = echecs.concat(j.echecs || []);
    fait += paquets[t].length;
  }
  bouton.disabled = false;
  if(echecs.length){
    // on nomme les rates : le reste est parti, il ne faut surtout pas tout reposter
    etat('⚠ ' + envoyes + ' / ' + lot.length + ' postes. Rates : '
         + echecs.slice(0, 8).map(function(x){ return '#' + x.n + ' (' + x.erreur + ')'; }).join(' · ')
         + (echecs.length > 8 ? ' · et ' + (echecs.length - 8) + ' autre(s)' : '')
         + (espacesRates ? ' · ' + espacesRates + ' ligne(s) vide(s) refusee(s)' : ''), 'ko');
  } else if(espacesRates){
    // les messages sont tous partis : on vide quand meme, mais on dit le trou
    etat('✓ ' + envoyes + ' messages postes · ⚠ ' + espacesRates
         + ' ligne(s) vide(s) refusee(s) par Discord : certains se suivent sans espace.', 'ko');
    E('brut').value = ''; photos = []; rendreLot();
  } else {
    etat('✓ ' + envoyes + ' messages postes.', 'ok');
    E('brut').value = ''; photos = []; rendreLot();
  }
  chargerMessages();
}

E('envoyer').onclick = async function(){
  if(modeLot) return envoyerLot(this);
  // une photo seule est un message valable : on n'exige du texte que s'il
  // n'y a rien d'autre à envoyer
  if(!E('texte').value.trim() && !neuves.length && !gardees.length){
    etat('Rien à envoyer : écris un message ou dépose une photo.', 'ko'); return;
  }
  this.disabled = true;
  etat(neuves.length ? ('Envoi de ' + neuves.length + ' fichier(s)…') : 'Envoi…');
  var j = await demander('/poster', {salon: E('salon').value, message: enCours,
    texte: E('texte').value, titre: E('titre').value.trim(), couleur: E('couleur').value.trim(),
    images: neuves.map(function(n){ return {nom: n.nom, b64: n.b64}; }),
    garder: gardees.map(function(g){ return g.id; })});
  this.disabled = false;
  if(!j.ok){ etat('✕ ' + (j.error || 'Erreur'), 'ko'); return; }
  etat(enCours ? '✓ Message corrigé.' : '✓ Message posté.' + (j.coupe ? ' (' + j.coupe + ' caractères coupés)' : ''), 'ok');
  nouveau(); chargerMessages();
};

E('supprimer').onclick = async function(){
  if(!enCours || !confirm('Supprimer ce message du salon ?')) return;
  var j = await demander('/supprimer', {salon: E('salon').value, message: enCours});
  if(!j.ok){ etat('✕ ' + (j.error || 'Erreur'), 'ko'); return; }
  etat('✓ Message supprimé.', 'ok'); nouveau(); chargerMessages();
};

E('vider').onclick = async function(){
  var nom = E('salon').options[E('salon').selectedIndex];
  nom = nom ? nom.textContent : '(ce salon)';
  // premier appel : on ne fait que compter. Rien n'est efface a l'aveugle.
  var q = await demander('/vider', {salon: E('salon').value});
  if(!q.ok){ etat('✕ ' + (q.error || 'Erreur'), 'ko'); return; }
  if(!q.compte){ etat('Ce salon est deja vide.', ''); return; }
  var combien = q.compte + (q.encore ? ' (au moins, il y en a plus de 100)' : '');
  if(!confirm('Effacer ' + combien + ' message(s) dans ' + nom + ' ?\n\n'
              + (q.apercu || []).map(function(x){ return '  • ' + x; }).join('\n')
              + '\n\nC est definitif : Discord n a pas de corbeille.')) return;
  if(!confirm('Vraiment ? ' + nom + ' sera vide.')) return;
  this.disabled = true;
  etat('Effacement en cours… laisse la page ouverte.');
  // l outil travaille par tranches (BUDGET_S) : on enchaine tant qu il dit « suite »
  var j, eff = 0, upu = 0, rates = [];
  do {
    j = await demander('/vider', {salon: E('salon').value, confirme: true});
    eff += j.efface || 0; upu += j.un_par_un || 0; rates = rates.concat(j.echecs || []);
    if(j.suite) etat('Effacement en cours… ' + eff + ' efface(s), je continue. Laisse la page ouverte.');
  } while(j.suite);
  this.disabled = false;
  var txt = eff + ' message(s) efface(s)'
          + (upu ? ' (dont ' + upu + ' un par un, trop vieux pour le lot)' : '');
  if(j.arrete) txt += ' · arrete par securite, il en reste : reclique';
  if(j.error) txt += ' · ' + j.error;
  if(rates.length) txt += ' · rates : ' + rates.slice(0, 10).join(' | ');
  var bon = j.ok && !rates.length;
  etat((bon ? '✓ ' : '⚠ ') + txt, bon ? 'ok' : 'ko');
  chargerMessages();
};

// Le comptage en attente de confirmation : c'est CE lien-la qui sera traite,
// meme si le champ change entre-temps -- celui que la question a montre.
var auDessus = null;
function cacherAuDessus(){ E('audessus-ok').style.display = 'none'; auDessus = null; }

E('audessus').onclick = async function(){
  cacherAuDessus();
  var lien = (E('lienhaut').value || '').trim();
  if(!lien){ etat('Colle d abord le lien du premier message a garder.', 'ko'); return; }
  etat('Je compte les messages au-dessus…');
  // premier appel : on ne fait que compter. Rien n est efface a l aveugle.
  var q;
  try { q = await demander('/au_dessus', {lien: lien}); }
  catch(e){ etat('✕ L outil ne repond pas : relance-le, puis recharge la page.', 'ko'); return; }
  if(!q.ok){ etat('✕ ' + (q.error || 'Erreur'), 'ko'); return; }
  if(!q.compte){ etat('Rien au-dessus de ce message dans ' + q.salon + ' : rien a supprimer.', ''); return; }
  var combien = q.compte + (q.encore ? ' (au moins : reclique ensuite pour la suite)' : '');
  E('audessus-texte').textContent = 'Supprimer ' + combien + ' message(s) AU-DESSUS dans ' + q.salon + ' ?\n'
    + 'Du ' + q.du + ' au ' + q.au + '. Juste au-dessus :\n'
    + (q.apercu || []).map(function(x){ return '  • ' + x; }).join('\n')
    + '\nRESTE : « ' + q.garde + ' » et tout ce qui suit.'
    + '\nC est definitif : Discord n a pas de corbeille.';
  E('audessus-oui').textContent = 'Oui, supprimer ' + q.compte + ' message(s)';
  auDessus = {lien: lien, q: q};
  E('audessus-ok').style.display = 'block';
  etat('', '');
};

E('audessus-non').onclick = function(){
  cacherAuDessus();
  etat('Annule : rien n a ete supprime.', '');
};

E('audessus-oui').onclick = async function(){
  if(!auDessus) return;
  var a = auDessus;
  cacherAuDessus();
  E('audessus').disabled = true;
  etat('Suppression en cours… jusqu a ' + Math.ceil(a.q.compte * 1.2) + ' s, laisse la page ouverte.');
  // l outil travaille par tranches (BUDGET_S) : on enchaine tant qu il dit « suite »
  var j, eff = 0, upu = 0, rates = [];
  do {
    j = await demander('/au_dessus', {lien: a.lien, confirme: true});
    eff += j.efface || 0; upu += j.un_par_un || 0; rates = rates.concat(j.echecs || []);
    if(j.suite) etat('Suppression en cours… ' + eff + ' supprime(s), il en reste ' + j.reste + ', je continue.');
  } while(j.suite);
  E('audessus').disabled = false;
  var txt = eff + ' message(s) supprime(s) dans ' + a.q.salon
          + (upu ? ' (dont ' + upu + ' un par un, trop vieux pour le lot)' : '');
  if(j.reste) txt += ' · il en reste ' + j.reste + (j.encore ? ' (au moins)' : '') + ' au-dessus : reclique';
  if(j.reste === null) txt += ' · le recomptage a echoue : reclique pour verifier';
  if(j.error) txt += ' · ' + j.error;
  if(rates.length) txt += ' · rates : ' + rates.slice(0, 10).join(' | ');
  var bon = j.ok && !rates.length;
  etat((bon ? '✓ ' : '⚠ ') + txt, bon ? 'ok' : 'ko');
  if(bon && j.reste === 0) E('lienhaut').value = '';
  chargerMessages();
};

E('retirercopier').onclick = async function(){
  var nom = E('salon').options[E('salon').selectedIndex];
  nom = nom ? nom.textContent : '(ce salon)';
  // premier appel : on compte seulement, comme pour Vider
  etat('Je cherche les boutons Copier dans ' + nom + '…');
  var q = await demander('/retirer_copier', {salon: E('salon').value});
  if(!q.ok){ etat('✕ ' + (q.error || 'Erreur'), 'ko'); return; }
  if(!q.compte){
    etat('Aucun bouton Copier dans ' + nom
         + (q.complet ? '.' : ' (sur les ' + q.lus + ' derniers messages).'), ''); return;
  }
  if(!confirm('Retirer le bouton Copier de ' + q.compte + ' message(s) dans ' + nom + ' ?\n\n'
              + 'Le texte et les photos restent, rien n est efface.')) return;
  this.disabled = true;
  etat('Retrait en cours… environ ' + Math.ceil(q.compte * 0.8) + ' s, laisse la page ouverte.');
  var j, ret = 0;
  do {
    j = await demander('/retirer_copier', {salon: E('salon').value, confirme: true});
    ret += j.retires || 0;
    if(j.suite) etat('Retrait en cours… ' + ret + ' retire(s), je continue.');
  } while(j.suite);
  this.disabled = false;
  if(j.error && !ret){ etat('✕ ' + j.error, 'ko'); return; }
  var txt = ret + ' bouton(s) Copier retire(s)';
  if(j.nb_echecs) txt += ' · ' + j.nb_echecs + ' rate(s) : ' + (j.echecs || []).join(' | ');
  if(!j.complet) txt += ' · salon tres long : seuls les ' + j.lus + ' derniers messages ont ete lus, reclique';
  etat((j.ok ? '✓ ' : '⚠ ') + txt, j.ok ? 'ok' : 'ko');
  chargerMessages();
};

E('onglet-un').onclick  = function(){ basculer(false); };
E('onglet-lot').onclick = function(){ basculer(true); };
E('brut').oninput = function(){ rendreLot(); };
E('depotlot').onclick = function(ev){
  if(ev.target.id === 'dossier') return;     // le dossier a son propre champ
  E('fichierslot').click();
};
E('dossier').onclick = function(ev){ ev.stopPropagation(); E('fichiersdoss').click(); };
E('fichierslot').onchange = function(){ ajouterLot(this.files); this.value = ''; };
E('fichiersdoss').onchange = function(){ ajouterLot(this.files); this.value = ''; };
['dragenter','dragover'].forEach(function(e){
  E('depotlot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.add('survol'); });
});
['dragleave','drop'].forEach(function(e){
  E('depotlot').addEventListener(e, function(ev){ ev.preventDefault(); this.classList.remove('survol'); });
});
E('depotlot').addEventListener('drop', function(ev){ deposer(ev, true); });
E('brut').addEventListener('paste', function(ev){ collerImages(ev, true); });
E('texte').addEventListener('paste', function(ev){ collerImages(ev, false); });
// coller n'importe ou dans la page marche aussi, pas seulement dans la zone
document.addEventListener('paste', function(ev){
  var t = ev.target;
  if(t && (t.id === 'brut' || t.id === 'texte')) return;   // deja traite au-dessus
  collerImages(ev, modeLot);
});

// Glisser un DOSSIER ne remplit pas `files` : le navigateur ne donne qu'une
// entree, qu'il faut parcourir. Sans ca, deposer un dossier ne faisait rien
// du tout — pas d'erreur, pas de photo, on croyait que l'outil etait casse.
async function fichiersDeEntree(entree){
  if(!entree) return [];
  if(entree.isFile){
    return [await new Promise(function(r){ entree.file(r, function(){ r(null); }); })];
  }
  var lect = entree.createReader(), tout = [], paquet;
  do {
    paquet = await new Promise(function(r){ lect.readEntries(r, function(){ r([]); }); });
    for(var i = 0; i < paquet.length; i++) tout = tout.concat(await fichiersDeEntree(paquet[i]));
  } while(paquet.length);
  return tout;
}

var nColle = 0;

// Une photo collee au clavier arrive sans nom, ou toujours sous le meme
// ("image.png"). Comme l'ordre des photos est celui des noms, elles se
// seraient toutes bousculees : on numerote dans l'ordre du collage.
function collerImages(ev, versLot){
  var dt = ev.clipboardData;
  if(!dt) return false;
  var fichiers = [];
  var items = dt.items || [];
  for(var i = 0; i < items.length; i++){
    if(items[i].kind !== 'file') continue;
    var f = items[i].getAsFile();
    if(f && /^(image|video)\//.test(f.type || '')) fichiers.push(f);
  }
  if(!fichiers.length) return false;        // du texte : collage normal
  ev.preventDefault();
  fichiers = fichiers.map(function(f){
    nColle++;
    var ext = String(f.type).split('/')[1] || 'png';
    if(ext === 'jpeg') ext = 'jpg';
    var nom = 'colle-' + ('000' + nColle).slice(-3) + '.' + ext;
    try { return new File([f], nom, {type: f.type}); }
    catch(e){ return f; }                   // vieux navigateur : on garde tel quel
  });
  if(versLot) ajouterLot(fichiers); else ajouter(fichiers);
  return true;
}

async function deposer(ev, versLot){
  var dt = ev.dataTransfer;
  var entrees = [];
  if(dt.items && dt.items.length && dt.items[0].webkitGetAsEntry){
    for(var i = 0; i < dt.items.length; i++){
      var e = dt.items[i].webkitGetAsEntry && dt.items[i].webkitGetAsEntry();
      if(e) entrees.push(e);
    }
  }
  var fichiers = [];
  if(entrees.length){
    etat('Lecture du dossier…');
    for(var k = 0; k < entrees.length; k++)
      fichiers = fichiers.concat(await fichiersDeEntree(entrees[k]));
    fichiers = fichiers.filter(Boolean);
    etat('');
  } else {
    fichiers = Array.prototype.slice.call(dt.files || []);
  }
  if(!fichiers.length){ etat('Rien de lisible dans ce depot.', 'ko'); return; }
  if(versLot) ajouterLot(fichiers); else ajouter(fichiers);
}
E('sepperso').oninput = function(){ rendreLot(); };
E('espace').onchange = function(){ rendreLot(); };
E('sep').onchange = function(){
  E('sepperso').disabled = this.value !== 'perso';
  rendreLot();
};
// ---- Supprimer une categorie. Deux temps, comme Vider : « Preparer » relit la
// categorie chez Discord et ne touche a rien ; le bouton rouge ne s allume que
// si le nom tape est EXACTEMENT celui de la categorie preparee. Les deux
// poubelles ne different que d un « 2 » : un choix de menu ne suffit pas.
// Les ids montres repartent avec la confirmation : l outil refuse si la
// categorie a change entre-temps, au lieu de supprimer un salon jamais vu.
var pret = null;     // la categorie preparee : {serveur, id, nom, compte, ids}
var tourCat = 0;     // une liste demandee avant la derniere arrive parfois apres

function etatCat(txt, classe){ var e = E('catetat'); e.textContent = txt; e.className = 'etat ' + (classe || ''); }

function nomCorrespond(){
  return !!pret && E('nomtape').value.trim() === pret.nom.trim();
}

function verifierNom(){
  var ok = nomCorrespond(), i = E('catindice');
  E('supprimercat').disabled = !ok;
  if(!pret){ i.textContent = ''; return; }
  if(ok){ i.textContent = '✓ Le nom correspond.'; i.style.color = 'var(--vert)'; }
  else if(E('nomtape').value.trim()){
    i.textContent = 'Pas encore le même nom : le bouton reste éteint.'; i.style.color = 'var(--rouge)';
  } else {
    i.textContent = 'Le bouton s’allume quand le nom est exactement le même.'; i.style.color = '';
  }
}

function oublierPreparation(){
  pret = null;
  E('catliste').innerHTML = ''; E('catliste').className = '';
  E('catconfirm').style.display = 'none';
  E('nomtape').value = '';
  verifierNom();
}

// `garder` : la categorie a laisser choisie apres un rechargement. Apres un
// echec partiel, le menu retombait sur la premiere categorie du serveur.
// `apres` : rechargement qui suit une suppression. Le compte rendu est dans
// #catresultat, que ce rechargement ne touche pas ; une lecture refusee le
// remplacait, et on ne savait plus si la categorie etait partie.
async function chargerCategories(garder, apres){
  var tour = ++tourCat;
  oublierPreparation();
  E('categorie').innerHTML = '<option value="">…</option>';
  var j = await demander('/categories?g=' + encodeURIComponent(E('catserveur').value));
  if(tour !== tourCat) return;
  E('categorie').innerHTML = '';
  if(!j.ok){
    etatCat((apres ? 'Liste des catégories pas relue : ' : '✕ ') + (j.error || 'Erreur'), 'ko');
    return;
  }
  (j.categories || []).forEach(function(c){
    var o = document.createElement('option'); o.value = c.id;
    o.textContent = c.nom + ' — ' + c.compte + ' salon' + (c.compte > 1 ? 's' : '');
    E('categorie').appendChild(o);
    if(garder && c.id === garder) o.selected = true;
  });
  if(!(j.categories || []).length) etatCat('Aucune catégorie sur ce serveur.', '');
}

E('preparer').onclick = async function(){
  oublierPreparation(); E('catresultat').innerHTML = '';
  var cid = E('categorie').value, bouton = this;
  if(!cid){ etatCat('Choisis une catégorie.', 'ko'); return; }
  bouton.disabled = true;
  etatCat('Je relis la catégorie chez Discord…');
  var q = await demander('/supprimer_categorie', {serveur: E('catserveur').value, categorie: cid});
  bouton.disabled = false;
  if(!q.ok){ etatCat('✕ ' + (q.error || 'Erreur'), 'ko'); return; }
  // le menu a pu changer pendant la lecture : on ne prepare que ce qui est choisi
  if(q.id !== E('categorie').value){ etatCat('Le choix a changé pendant la lecture : reclique sur Préparer.', 'ko'); return; }
  pret = {serveur: q.serveur, id: q.id, nom: q.nom, compte: q.compte,
          ids: (q.salons || []).map(function(s){ return s.id; })};
  var z = E('catliste'); z.className = 'catliste'; z.innerHTML = '';
  var t = document.createElement('div');
  t.appendChild(document.createTextNode(q.compte
    ? (q.compte + ' salon' + (q.compte > 1 ? 's' : '') + ' dans ') : 'Aucun salon dans '));
  var b = document.createElement('span'); b.className = 'nomattendu'; b.textContent = q.nom;
  t.appendChild(b);
  t.appendChild(document.createTextNode(q.compte
    ? ' : ils partiront tous, puis la catégorie.' : ' : seule la catégorie partira.'));
  z.appendChild(t);
  if(q.compte){
    var ol = document.createElement('ol');
    (q.salons || []).forEach(function(s){
      var li = document.createElement('li'); li.textContent = s.nom;
      var g = document.createElement('span'); g.className = 'g'; g.textContent = s.genre;
      li.appendChild(g); ol.appendChild(li);
    });
    z.appendChild(ol);
  }
  E('catconfirm').style.display = '';
  verifierNom();
  etatCat('Rien n’est supprimé pour l’instant.', '');
  E('nomtape').focus();
};

// Le compte rendu va dans #catresultat, pas dans #catetat : le rechargement
// des categories qui suit ecrit dans #catetat et l effacait.
function montrerResultat(j){
  var z = E('catresultat'); z.innerHTML = '';
  etatCat('');
  var ligne = document.createElement('div');
  z.appendChild(ligne);
  if(j.error && !j.supprimes){ ligne.className = 'etat ko'; ligne.textContent = '✕ ' + j.error; return; }
  var txt = (j.supprimes || []).length + ' / ' + (j.total || 0) + ' salon(s) supprimé(s)';
  txt += j.categorie_supprimee ? ' · catégorie « ' + j.categorie + ' » supprimée.'
                               : ' · ' + (j.motif || 'catégorie gardée.');
  ligne.className = 'etat ' + (j.ok ? 'ok' : 'ko');
  ligne.textContent = (j.ok ? '✓ ' : '⚠ ') + txt;
  if((j.echecs || []).length){
    // on nomme les rates, avec la raison de Discord : le reste est deja parti
    var ul = document.createElement('ul'); ul.className = 'echecs';
    j.echecs.forEach(function(x){
      var li = document.createElement('li'); li.textContent = x.nom + ' — ' + x.raison;
      ul.appendChild(li);
    });
    z.appendChild(ul);
  }
}

E('nomtape').oninput = verifierNom;
E('supprimercat').onclick = async function(){
  if(!nomCorrespond()) return;
  var p = pret, bouton = this;
  if(!confirm('Supprimer définitivement ' + p.compte + ' salon(s) et la catégorie « ' + p.nom + ' » ?\n\n'
              + 'Discord n’a pas de corbeille : c’est sans retour.')) return;
  var champs = ['supprimercat', 'preparer', 'catserveur', 'categorie', 'nomtape'];
  champs.forEach(function(i){ E(i).disabled = true; });
  etatCat('Suppression en cours… environ ' + Math.ceil(p.compte * 0.9 + 2) + ' s, laisse la page ouverte.');
  var j;
  try {
    j = await demander('/supprimer_categorie', {serveur: p.serveur, categorie: p.id,
                                                confirme: true, nom_tape: E('nomtape').value,
                                                ids_vus: p.ids});
  } catch(e){
    j = {ok: false, error: 'Pas de réponse de l’outil : regarde le terminal avant de recliquer.'};
  }
  champs.forEach(function(i){ E(i).disabled = false; });
  montrerResultat(j);
  chargerCategories(p.id, true);
};
E('catserveur').onchange = function(){ etatCat(''); E('catresultat').innerHTML = ''; chargerCategories(''); };
E('categorie').onchange = function(){ oublierPreparation(); etatCat(''); E('catresultat').innerHTML = ''; };

E('annuler').onclick = nouveau;
E('serveur').onchange = chargerSalons;
E('salon').onchange = chargerMessages;
['texte','titre','couleur'].forEach(function(i){ E(i).oninput = apercu; });

(async function(){
  var j = await demander('/serveurs');
  (j.serveurs || []).forEach(function(s){
    var o = document.createElement('option'); o.value = s.id; o.textContent = s.nom;
    E('serveur').appendChild(o);
    E('catserveur').appendChild(o.cloneNode(true));
  });
  if(!(j.serveurs || []).length){ etat('Aucun serveur joignable — le jeton du bot est-il en place ?', 'ko'); return; }
  chargerSalons(); apercu(); chargerCategories();
})();
</script></body></html>"""


class Poste(BaseHTTPRequestHandler):
    def _envoyer(self, data, code=200):
        brut = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def _lire(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _venu_d_ailleurs(self, ecriture: bool) -> str:
        """Le refus si la requête ne vient pas de la page de l'outil, sinon "".

        Écouter 127.0.0.1 ne suffit pas : n'importe quel site ouvert dans le
        navigateur du propriétaire peut viser 127.0.0.1:8787. Un POST en
        text/plain part sans contrôle préalable du navigateur, et l'outil
        lisait le JSON quand même : la suppression d'une catégorie passait
        depuis une page étrangère (vu à la revue). Avec un nom de domaine qui
        pointe vers 127.0.0.1, cette page pouvait même lire /categories.
        """
        try:
            port = self.server.server_address[1]
        except Exception:
            port = PORT
        locaux = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if (self.headers.get("Host") or "").strip().lower() not in locaux:
            return "Requête refusée : elle ne vient pas de la page de l'outil."
        if PORTE_FICHIER:
            try:
                attendu = Path(PORTE_FICHIER).read_text(encoding="utf-8").strip()
            except Exception:
                attendu = ""
            recu = (self.headers.get("X-Outil-Gate") or "").strip()
            # secret illisible : on refuse plutôt que d'ouvrir sans preuve
            if not attendu or not hmac.compare_digest(recu.encode(), attendu.encode()):
                return "Requête refusée : elle n'est pas passée par youl4b.com."
        origine = self.headers.get("Origin")
        admises = {"http://" + h for h in locaux} | ORIGINES_SITE
        if origine is not None and origine.strip().lower().rstrip("/") not in admises:
            return "Requête refusée : elle vient d'un autre site que l'outil."
        if ecriture:
            # application/json oblige le navigateur à demander la permission
            # avant d'envoyer depuis un autre site ; l'outil ne la donne pas
            genre = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if genre != "application/json":
                return "Requête refusée : l'outil n'accepte que du JSON."
        return ""

    def do_GET(self):
        _DERNIERE_ACTIVITE[0] = time.time()
        refus = self._venu_d_ailleurs(False)
        if refus:
            return self._envoyer({"ok": False, "error": refus}, 403)
        chemin, _, requete = self.path.partition("?")
        q = urllib.parse.parse_qs(requete)
        if chemin == "/":
            # la date du fichier, pas celle du démarrage : on voit d'un coup
            # d'œil qu'un vieil exemplaire tourne encore
            quand = datetime.fromtimestamp(Path(__file__).stat().st_mtime)
            brut = PAGE.replace("__DATE__", quand.strftime("%d/%m %Hh%M")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(brut)))
            self.end_headers()
            self.wfile.write(brut)
            return
        if chemin == "/serveurs":
            out = []
            for gid in SERVEURS:
                code, rep = api("GET", f"/guilds/{gid}")
                if code == 200:
                    out.append({"id": gid, "nom": rep.get("name") or gid})
            return self._envoyer({"serveurs": out})
        if chemin == "/salons":
            return self._envoyer({"salons": salons((q.get("g") or [""])[0])})
        if chemin == "/messages":
            return self._envoyer({"messages": derniers((q.get("c") or [""])[0])})
        if chemin == "/categories":
            return self._envoyer(categories((q.get("g") or [""])[0]))
        self._envoyer({"error": "inconnu"}, 404)

    def do_POST(self):
        # Compté : le redémarrage après un déploiement attend qu'aucun envoi
        # ni aucune suppression ne soit en cours.
        with _VERROU_EN_COURS:
            _EN_COURS[0] += 1
            _DERNIERE_ACTIVITE[0] = time.time()
        try:
            return self._do_post()
        finally:
            with _VERROU_EN_COURS:
                _EN_COURS[0] -= 1
                _DERNIERE_ACTIVITE[0] = time.time()

    def _do_post(self):
        refus = self._venu_d_ailleurs(True)
        if refus:
            return self._envoyer({"ok": False, "error": refus}, 403)
        d = self._lire()
        salon = str(d.get("salon") or "")
        if self.path == "/supprimer":
            code, rep = api("DELETE", f'/channels/{salon}/messages/{d.get("message")}')
            return self._envoyer({"ok": code in (200, 204),
                                  "error": "" if code in (200, 204) else f"HTTP {code}"})
        if self.path == "/poster_lot":
            return self._lot(d)
        if self.path == "/vider":
            return self._vider(d)
        if self.path == "/au_dessus":
            return self._au_dessus(d)
        if self.path == "/retirer_copier":
            return self._retirer_copier(d)
        if self.path == "/supprimer_categorie":
            return self._supprimer_categorie(d)
        if self.path != "/poster":
            return self._envoyer({"error": "inconnu"}, 404)
        texte = str(d.get("texte") or "")
        titre = str(d.get("titre") or "")
        corps = corps_message(texte, titre, str(d.get("couleur") or ""), bool(titre))
        msg = d.get("message")

        # Images : celles qu'on ajoute maintenant, et celles déjà attachées
        # qu'on garde. Discord EFFACE toute pièce jointe absente de la liste
        # `attachments` d'un PATCH — d'où le renvoi explicite des gardées.
        neuves = []
        for im in (d.get("images") or [])[:10]:
            try:
                octets = base64.b64decode(str(im.get("b64") or ""), validate=True)
            except Exception:
                continue
            if octets:
                neuves.append((str(im.get("nom") or "image.png"), octets))
        gardees = [str(x) for x in (d.get("garder") or [])]

        trop = [n for n, o in neuves if len(o) > 9 * 1024 * 1024]
        if trop:
            return self._envoyer({"ok": False,
                                  "error": "Trop lourd pour Discord (9 Mo max) : "
                                           + ", ".join(trop)})
        if neuves or (msg and gardees is not None):
            jointes = [{"id": i} for i in gardees]
            jointes += [{"id": i, "filename": n}
                        for i, (n, _) in enumerate(neuves, start=len(gardees))]
            if msg or neuves:
                corps["attachments"] = jointes

        if msg and neuves:
            code, rep = api_fichiers("PATCH", f"/channels/{salon}/messages/{msg}",
                                     corps, neuves)
        elif msg:
            code, rep = api("PATCH", f"/channels/{salon}/messages/{msg}", corps)
        elif neuves:
            code, rep = api_fichiers("POST", f"/channels/{salon}/messages",
                                     corps, neuves)
        else:
            code, rep = api("POST", f"/channels/{salon}/messages", corps)
        if code != 200:
            return self._envoyer({"ok": False,
                                  "error": f'Discord a refusé (HTTP {code}) : '
                                           f'{str(rep.get("message") or rep)[:160]}'})
        limite = MAX_EMBED if titre else MAX_TEXTE
        return self._envoyer({"ok": True, "id": str(rep.get("id") or ""),
                              "coupe": max(0, len(texte.strip()) - limite)})

    def _lot(self, d):
        """Poste une liste de messages, un par un, dans l'ordre.

        Un élément est un texte, une photo, ou les deux. La page envoie le
        collage par tranches : une photo pèse lourd une fois encodée, et tout
        faire tenir dans une seule requête bloquait la page sans rien afficher.

        Discord accepte environ 5 messages par 5 secondes dans un salon : on
        laisse une seconde entre chaque et on respecte le délai qu'il demande
        quand il dit stop (429). Un envoi raté n'arrête pas les suivants — le
        compte rendu dit lesquels sont passés, pour reprendre la main dessus
        sans tout reposter.
        """
        salon = str(d.get("salon") or "")
        titre = str(d.get("titre") or "")
        couleur = str(d.get("couleur") or "")
        depart = int(d.get("depart") or 0)        # numéro du premier de la tranche

        elements = []
        for x in (d.get("messages") or []):
            if isinstance(x, dict):
                elements.append((str(x.get("texte") or "").strip(), x.get("image")))
            else:
                elements.append((str(x or "").strip(), None))
        elements = [e for e in elements if e[0] or e[1]]

        if not salon or not elements:
            return self._envoyer({"ok": False, "error": "Salon vide ou aucun message"})
        if len(elements) > 300:
            return self._envoyer({"ok": False,
                                  "error": f"{len(elements)} messages : trop d'un coup "
                                           "(300 au maximum). Coupe le collage en deux."})
        espace = bool(d.get("espace"))
        copier = bool(d.get("copier")) and BOUTON_COPIE is not None
        if d.get("copier") and BOUTON_COPIE is None:
            return self._envoyer({"ok": False,
                                  "error": "copie_discord.py est introuvable : "
                                           "pas de bouton Copier possible."})

        def poster(corps, fichier):
            for _ in range(3):
                if fichier:
                    code, rep = api_fichiers("POST", f"/channels/{salon}/messages",
                                             corps, fichier)
                else:
                    code, rep = api("POST", f"/channels/{salon}/messages", corps)
                if code == 429:
                    time.sleep(float(rep.get("retry_after") or 1) + 0.3)
                    continue
                break
            return code, rep

        envoyes, echecs, espaces_rates = 0, [], 0
        for i, (texte, image) in enumerate(elements):
            n = depart + i + 1
            apercu = texte[:60] or (str((image or {}).get("nom") or "")[:60])

            fichier = None
            if image:
                try:
                    octets = base64.b64decode(str(image.get("b64") or ""), validate=True)
                except Exception:
                    octets = b""
                if not octets:
                    echecs.append({"n": n, "apercu": apercu,
                                   "erreur": "photo illisible"})
                    continue
                if len(octets) > 9 * 1024 * 1024:
                    echecs.append({"n": n, "apercu": apercu,
                                   "erreur": f"{len(octets)//(1024*1024)} Mo : "
                                             "trop lourd pour Discord (9 Mo max)"})
                    continue
                fichier = [(str(image.get("nom") or "image.png"), octets)]

            corps = corps_message(texte, titre, couleur, bool(titre))
            # un bouton Copier sous une photo sans légende n'aurait rien à copier
            if copier and texte:
                corps["components"] = BOUTON_COPIE()
            if fichier:
                corps["attachments"] = [{"id": 0, "filename": fichier[0][0]}]

            # La ligne vide est un message À PART, jamais collée au texte : un VA
            # qui fait « Copier le texte » sur un nom doit avoir le nom seul,
            # pas un caractère invisible qui suivrait dans le pseudo du compte.
            # Pas avant le tout premier du collage (depart compte les tranches).
            if espace and depart + i > 0:
                c_esp, _ = poster({"content": ESPACE}, None)
                if c_esp != 200:
                    espaces_rates += 1
                time.sleep(1.0)

            code, rep = poster(corps, fichier)
            if code == 200:
                envoyes += 1
            else:
                echecs.append({"n": n, "apercu": apercu,
                               "erreur": str(rep.get("message") or f"HTTP {code}")[:120]})
            # une photo met plus longtemps à monter : on laisse respirer davantage
            time.sleep(1.3 if fichier else 1.0)
        return self._envoyer({"ok": not echecs, "envoyes": envoyes,
                              "total": len(elements), "echecs": echecs,
                              "espaces_rates": espaces_rates})

    def _vider(self, d):
        """Efface les messages d'un salon — en deux temps, jamais à l'aveugle.

        Sans `confirme`, on rend seulement le nombre : la page peut alors
        demander « vider les 52 messages ? » avec le vrai chiffre sous les yeux.
        Discord refuse d'effacer en lot un message de plus de 14 jours : ceux-là
        partent un par un, plus lentement, et sont comptés à part pour que le
        compte rendu colle à ce qui s'est vraiment passé.
        """
        salon = str(d.get("salon") or "")
        if not salon:
            return self._envoyer({"ok": False, "error": "Aucun salon"})
        code, msgs = api("GET", f"/channels/{salon}/messages", params={"limit": "100"})
        if code != 200:
            return self._envoyer({"ok": False,
                                  "error": str((msgs or {}).get("message") or f"HTTP {code}")})
        if not d.get("confirme"):
            aperçu = [(x.get("content") or "")[:60] for x in msgs[:3]]
            return self._envoyer({"ok": True, "compte": len(msgs), "apercu": aperçu,
                                  "encore": len(msgs) == 100})

        efface, un_par_un, echecs, tours = 0, 0, [], 0
        fin = time.time() + BUDGET_S
        while msgs and tours < 20 and (tours == 0 or time.time() < fin):
            tours += 1
            e, u, ech = _effacer_messages(salon, [x["id"] for x in msgs], fin)
            efface += e
            un_par_un += u
            echecs += ech
            time.sleep(0.6)
            code, msgs = api("GET", f"/channels/{salon}/messages", params={"limit": "100"})
            if code != 200:
                echecs.append(f"relecture : HTTP {code}")
                break
        return self._envoyer({"ok": not echecs, "efface": efface, "un_par_un": un_par_un,
                              "reste": len(msgs), "echecs": echecs[:10],
                              "arrete": tours >= 20 and bool(msgs),
                              # tranche finie, salon pas vide : la page relance
                              "suite": bool(msgs) and efface > 0 and tours < 20})

    def _au_dessus(self, d):
        """Efface tout ce qui est AU-DESSUS d'un message : ce message et tout ce
        qui le suit restent.

        Pour un salon reposté en dessous de l'ancien contenu : « Vider »
        emportait aussi le nouveau. Le salon est celui du LIEN, pas celui du
        menu — c'est lui qui est montré dans la question. Deux temps, comme
        Vider : sans `confirme`, on compte seulement.
        """
        brut = str(d.get("lien") or "")
        m = _LIEN_MESSAGE.search(brut)
        if not m:
            if _LIEN_SALON.search(brut):
                return self._envoyer({"ok": False, "error": "C'est le lien du SALON, pas d'un "
                                      "message (il lui manque le 3e numéro). Sur Discord : clic "
                                      "droit sur le message à garder > Copier le lien du message."})
            vu = " ".join(brut.split())[:80]
            return self._envoyer({"ok": False, "error": "Lien non reconnu (reçu : « " + vu
                                  + " »). Sur Discord : clic droit sur le message > Copier le "
                                  "lien du message."})
        gid, salon, garde = m.groups()
        if gid not in SERVEURS:
            return self._envoyer({"ok": False, "error": "Ce lien n'est pas sur un serveur "
                                  "de l'outil : rien n'est supprimé."})
        # Le bot se choisit d'apres le serveur du salon. Sans ca, un lien de
        # THREADS collé avant d'avoir ouvert ce serveur dans un menu partait
        # avec le jeton de Siri, qui n'y est plus : « Missing Access ».
        _SALON_SERVEUR[salon] = gid
        code, msg = _api_patient("GET", f"/channels/{salon}/messages/{garde}")
        if code == 429:
            return self._envoyer({"ok": False, "error": "Discord demande d'attendre un peu : "
                                  "reclique dans quelques secondes. Rien n'est supprimé."})
        if code != 200:
            return self._envoyer({"ok": False, "error": "Message introuvable : "
                                  + str((msg or {}).get("message") or f"HTTP {code}")[:120]})
        anciens, encore, erreur = _messages_avant(salon, garde)
        if erreur:
            return self._envoyer({"ok": False, "error": "Lecture du salon : " + erreur})
        if not d.get("confirme"):
            print(f"[au-dessus] comptage {salon} : {len(anciens)} message(s) au-dessus "
                  f"de {garde}", flush=True)
            c, info = _api_patient("GET", f"/channels/{salon}")
            return self._envoyer({
                "ok": True, "compte": len(anciens), "encore": encore,
                "salon": (info or {}).get("name") if c == 200 else salon,
                "garde": _resume(msg), "apercu": [_resume(x) for x in anciens[:3]],
                "du": _date_id(anciens[-1]["id"]) if anciens else "",
                "au": _date_id(anciens[0]["id"]) if anciens else ""})
        efface, un_par_un, echecs = _effacer_messages(salon, [x["id"] for x in anciens],
                                                      time.time() + BUDGET_S)
        reste, encore, erreur = _messages_avant(salon, garde)
        print(f"[au-dessus] {salon} : {efface} supprime(s), {len(echecs)} echec(s), "
              f"reste {'?' if erreur else len(reste)}", flush=True)
        if erreur:
            # sans ca, une relecture refusee rendait « reste 0 » : la page
            # annoncait le travail fini et effacait le lien
            echecs.append("relecture : " + erreur)
        return self._envoyer({"ok": not echecs, "efface": efface, "un_par_un": un_par_un,
                              "reste": None if erreur else len(reste), "encore": encore,
                              "echecs": echecs[:10],
                              "suite": not erreur and bool(reste) and efface > 0})

    def _retirer_copier(self, d):
        """Enlève le bouton Copier des messages déjà postés, sans toucher au reste.

        Deux temps, comme Vider : sans `confirme`, on compte seulement. On
        remonte le salon par pages de 100 : les boutons étaient posés sous
        chaque caption depuis le début, les plus vieux messages en ont aussi.
        Seul le bouton Copier part : un autre bouton de la même rangée reste,
        et le texte, l'encadré, les photos ne sont pas renvoyés, donc gardés.
        """
        salon = str(d.get("salon") or "")
        if not salon:
            return self._envoyer({"ok": False, "error": "Aucun salon"})

        a_nettoyer, lus, avant, complet = [], 0, None, False
        for _ in range(50):                     # 5 000 messages au plus
            params = {"limit": "100"}
            if avant:
                params["before"] = avant
            code, msgs = api("GET", f"/channels/{salon}/messages", params=params)
            if code != 200 or not isinstance(msgs, list):
                if not lus:
                    return self._envoyer({"ok": False, "error": str(
                        (msgs or {}).get("message") or f"HTTP {code}")[:160]})
                break                           # complet reste False : la page le dit
            lus += len(msgs)
            for m in msgs:
                if not (m.get("author") or {}).get("bot"):
                    continue
                rangees = m.get("components") or []
                gardees = []
                for r in rangees:
                    autres = [c for c in (r.get("components") or [])
                              if c.get("custom_id") != ID_COPIE]
                    if autres:
                        gardees.append({**r, "components": autres})
                if gardees != rangees:
                    a_nettoyer.append((m["id"], gardees))
            if len(msgs) < 100:
                complet = True
                break
            avant = msgs[-1]["id"]
            time.sleep(0.3)

        if not d.get("confirme"):
            return self._envoyer({"ok": True, "compte": len(a_nettoyer),
                                  "lus": lus, "complet": complet})

        retires, echecs, traites = 0, [], 0
        fin = time.time() + BUDGET_S
        for mid, gardees in a_nettoyer:
            if traites and time.time() > fin:
                break
            traites += 1
            for _ in range(3):
                c, rep = api("PATCH", f"/channels/{salon}/messages/{mid}",
                             {"components": gardees})
                if c == 429:
                    time.sleep(float((rep or {}).get("retry_after") or 1) + 0.3)
                    continue
                break
            if c == 200:
                retires += 1
            else:
                echecs.append(f"{mid} : " + str((rep or {}).get("message") or f"HTTP {c}")[:80])
            time.sleep(0.6)
        return self._envoyer({"ok": not echecs and complet, "retires": retires,
                              "nb_echecs": len(echecs), "echecs": echecs[:5],
                              "lus": lus, "complet": complet,
                              "suite": traites < len(a_nettoyer) and retires > 0})

    def _supprimer_categorie(self, d):
        """Supprime une catégorie et tous ses salons — en deux temps.

        Sans `confirme`, rien ne part : on rend la liste relue chez Discord,
        pour que la page la montre avant. Avec `confirme`, il faut AUSSI le nom
        exact de la catégorie, tapé à la main : une mauvaise ligne choisie
        dans le menu ne suffit pas à vider « 🗑️ POUBELLE 2 » à la place de
        « 🗑️ POUBELLE ». Tout est relu à ce moment-là : la page ne dit ni
        quels salons partent, ni sur quel serveur.

        La page renvoie seulement les ids qu'elle a montrés (`ids_vus`). Ils ne
        choisissent rien : ils servent à refuser si la catégorie a changé.
        Sans ce contrôle, un salon glissé dedans après « Préparer » partait
        sans avoir été vu, et la boîte de confirmation annonçait l'ancien
        nombre.
        """
        gid, cat, enfants, err = _trouver_categorie(d.get("categorie"), d.get("serveur"))
        if err:
            return self._envoyer({"ok": False, "error": err})
        cid, nom = str(cat.get("id")), cat.get("name") or ""
        liste = [{"nom": c.get("name") or "", "id": str(c.get("id")), "type": c.get("type"),
                  "genre": GENRES.get(c.get("type"), f"type {c.get('type')}")}
                 for c in enfants]
        if not d.get("confirme"):
            return self._envoyer({"ok": True, "serveur": gid, "id": cid, "nom": nom,
                                  "salons": liste, "compte": len(liste)})
        if str(d.get("nom_tape") or "").strip() != nom.strip():
            return self._envoyer({"ok": False, "refuse": True,
                                  "error": f"Le nom tapé n'est pas « {nom} » : "
                                           "rien n'est supprimé."})
        vus = d.get("ids_vus")
        if not isinstance(vus, list):
            return self._envoyer({"ok": False, "refuse": True,
                                  "error": "La page n'a pas dit quels salons elle a montrés : "
                                           "reclique sur Préparer. Rien n'est supprimé."})
        if {str(x) for x in vus} != {s["id"] for s in liste}:
            return self._envoyer({"ok": False, "refuse": True, "change": True,
                                  "error": f"La catégorie a changé depuis « Préparer » "
                                           f"({len(vus)} salon(s) montrés, {len(liste)} "
                                           "maintenant) : reclique sur Préparer. "
                                           "Rien n'est supprimé."})
        if not _VERROU_CATEGORIE.acquire(blocking=False):
            return self._envoyer({"ok": False, "error": "Une suppression est déjà en "
                                                        "cours : attends qu'elle finisse."})
        try:
            _journal(f"[supprimer catégorie] « {nom} » ({cid}) : {len(liste)} salon(s) "
                     "à supprimer, à la demande du propriétaire")
            return self._envoyer(supprimer_salons_puis_categorie(gid, cid, nom, liste))
        finally:
            _VERROU_CATEGORIE.release()

    def log_message(self, *a):
        pass          # le terminal reste lisible


_EN_COURS = [0]
_VERROU_EN_COURS = threading.Lock()
_DERNIERE_ACTIVITE = [0.0]


def _calme(maintenant: float) -> bool:
    """Rien en cours ET rien depuis une minute. Un compteur à zéro ne suffit
    pas : entre deux tranches d'un envoi en lot, il retombe à zéro, et un
    redémarrage à ce moment coupait le lot en silence."""
    return _EN_COURS[0] == 0 and maintenant - _DERNIERE_ACTIVITE[0] > 60


def _relancer_si_modifie(intervalle: float = 20.0):
    """Service du VPS : quitte quand le fichier change (déploiement), systemd
    relance le nouveau code. Sans ça, l'outil en ligne gardait l'ancienne
    version jusqu'au prochain redémarrage du serveur."""
    try:
        depart = Path(__file__).stat().st_mtime
    except Exception:
        return
    while True:
        time.sleep(intervalle)
        try:
            if Path(__file__).stat().st_mtime == depart:
                continue
        except Exception:
            continue
        while not _calme(time.time()):
            time.sleep(2)
        print("[service] nouveau code déployé : redémarrage", flush=True)
        os._exit(0)


def main():
    if SERVICE and (not PORTE_FICHIER or not ORIGINES_SITE):
        print("Service sans OUTIL_DISCORD_GATE_FICHIER ou OUTIL_DISCORD_ORIGINES : "
              "refusé, l'outil serait ouvert à tout le VPS.", file=sys.stderr)
        return 1
    if not TOKEN:
        print("Jeton du bot introuvable.\n"
              "Attendu dans ~/.config/seven_bot_token, data/seven_bot_token, "
              "ou la variable SEVEN_BOT_TOKEN.", file=sys.stderr)
        return 1
    # 127.0.0.1 et pas 0.0.0.0 : la page n'est pas joignable depuis le réseau.
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Poste)
    except OSError as e:
        if getattr(e, "errno", None) not in (48, 98):   # EADDRINUSE mac / linux
            raise
        # sans ce message, l'ancien exemplaire continuait de servir sa vieille
        # page et on cherchait la correction pendant dix minutes
        print(f"Le port {PORT} est déjà pris : un autre exemplaire tourne.\n"
              "Fais Ctrl+C dans sa fenêtre, ou : pkill -f discord_ecrire.py\n"
              "Attention, celui-là sert peut-être une version plus ancienne.",
              file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{PORT}"
    print(f"Écrire dans un salon Discord : {url}\nCtrl+C pour arrêter.", flush=True)
    if SERVICE:
        threading.Thread(target=_relancer_si_modifie, daemon=True).start()
    else:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
