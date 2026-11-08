"""trust_agency_anciens.py — les anciens messages du bot sur TRUST Agency,
au nom TRUST Agency.

Depuis le 07/11/2026 (2a0bd1c), tout ce que le bot écrit sur le serveur de
recrutement passe par verif_discord.api, qui remplace « YouLab » par « TRUST
Agency ». Ce qui était posté AVANT gardait l'ancien nom : propriétaire,
08/11, devant une carte « En attente d'un manager » du 20/10 : « c'est encore
écrit ici youlab ». 186 messages du bot étaient concernés (annonces des
entretiens, départs, membres vérifiés, cartes de vérification du staff,
arrivées) ; il a dit « oui, les 186 ».

Une seule passe, au démarrage du bot sur la machine de production : chaque
message du bot (et lui seul : les autres ne lui appartiennent pas) qui porte
encore l'ancien nom est réécrit avec la table de verif_discord (table_marque)
— texte, embeds riches, boutons ; le reste du message ne bouge pas. Chaque
message traité est noté (data/trust_agency_anciens.json, safe_json) : un
redémarrage reprend où la passe s'était arrêtée, et une passe finie ne
repart plus. Ce qui n'a pas pu être réécrit est compté et dit, jamais tu.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

GID = "1552152470464110703"                      # TRUST Agency (recrutement)
DATA_DIR = Path(__file__).resolve().parent / "data"
FICHIER = DATA_DIR / "trust_agency_anciens.json"
#: les formes de l'ancien nom ; la table de verif_discord les remplace
ANCIEN = ("YouLab", "YOULAB")
#: un PATCH par seconde au plus : 186 messages, trois minutes, sans 429
PAUSE_S = 1.0
#: pages de 100 messages lues au plus par salon (l'historique entier, à ce jour)
PAGES_MAX = 50
#: ce qu'un embed reçu garde quand on le renvoie : le reste (proxy_url,
#: width, height, provider, video…) est calculé par Discord
_EMBED = ("title", "description", "url", "timestamp", "color")
_SOUS = {"footer": ("text", "icon_url"), "image": ("url",), "thumbnail": ("url",),
         "author": ("name", "url", "icon_url")}

_DEMARRE = False
LOCK = threading.Lock()


def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(FICHIER, default={}) or {}
    except Exception:                                        # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write(FICHIER, d)


def _porte(x: Any) -> bool:
    s = json.dumps(x, ensure_ascii=False)
    return any(a in s for a in ANCIEN)


def embed_a_renvoyer(e: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: e[k] for k in _EMBED if k in e}
    for k, champs in _SOUS.items():
        if isinstance(e.get(k), dict):
            sous = {c: e[k][c] for c in champs if c in e[k]}
            if sous:
                out[k] = sous
    if isinstance(e.get("fields"), list):
        out["fields"] = [{c: f[c] for c in ("name", "value", "inline") if c in f}
                         for f in e["fields"] if isinstance(f, dict)]
    return out


def corps_corrige(m: Dict[str, Any], table) -> Optional[Dict[str, Any]]:
    """Le PATCH qui remet `m` au nom TRUST Agency, None s'il n'y a rien à
    faire. Lève ValueError quand l'ancien nom est dans quelque chose que le
    bot ne peut pas renvoyer (aperçu d'un lien, par exemple)."""
    import verif_discord as vd
    corps: Dict[str, Any] = {}
    if _porte(m.get("content") or ""):
        corps["content"] = m["content"]
    embeds = m.get("embeds") or []
    if _porte(embeds):
        if any((e or {}).get("type", "rich") != "rich" for e in embeds):
            raise ValueError("embed non riche (aperçu de lien) : impossible à renvoyer tel quel")
        corps["embeds"] = [embed_a_renvoyer(e) for e in embeds]
    if _porte(m.get("components") or []):
        corps["components"] = m["components"]
    if not corps:
        return None
    corps = vd.en_trust(corps, table)
    if _porte(corps):
        raise ValueError("l'ancien nom resterait après remplacement")
    return corps


def messages(salon: str) -> Optional[List[Dict[str, Any]]]:
    """Tout l'historique lisible du salon ; None si Discord ne le rend pas."""
    import verif_discord as vd
    out: List[Dict[str, Any]] = []
    avant = ""
    for _ in range(PAGES_MAX):
        code, page = vd.api("GET", f"/channels/{salon}/messages?limit=100" + (f"&before={avant}" if avant else ""),
                            gid=GID)
        if code != 200 or not isinstance(page, list):
            return None                  # une page manquée : le salon sera repris
        out += page
        if len(page) < 100:
            break
        avant = str(page[-1]["id"])
    return out


def passe() -> Dict[str, Any]:
    """La passe entière. Rend le bilan ; rien si elle est déjà finie."""
    import verif_discord as vd
    with LOCK:
        d = _etat()
    if d.get("termine"):
        return {"deja": d["termine"]}
    table = vd.table_marque(GID)
    bot = str(vd.bot_du_serveur(GID).get("app_id") or "")
    if not table or not bot:
        print("[trust-agency-anciens] table de noms ou bot inconnu : rien fait", flush=True)
        return {"erreur": "table ou bot"}
    code, salons = vd.api("GET", f"/guilds/{GID}/channels", gid=GID)
    if code != 200 or not isinstance(salons, list):
        print(f"[trust-agency-anciens] salons illisibles (HTTP {code}) : réessai au prochain démarrage", flush=True)
        return {"erreur": f"salons HTTP {code}"}
    faits = d.setdefault("faits", {})
    echecs = d.setdefault("echecs", {})
    bilan = {"corriges": 0, "echecs": 0, "salons_illisibles": 0}
    for s in salons:
        if not isinstance(s, dict) or s.get("type") not in (0, 5):
            continue
        ms = messages(str(s["id"]))
        if ms is None:
            bilan["salons_illisibles"] += 1
            echecs["salon:" + str(s["id"])] = "historique illisible"
            continue
        for m in ms:
            mid = str(m.get("id") or "")
            if mid in faits or str((m.get("author") or {}).get("id")) != bot:
                continue
            try:
                corps = corps_corrige(m, table)
            except ValueError as e:
                echecs[mid] = str(e)
                bilan["echecs"] += 1
                continue
            if corps is None:
                continue
            code, _rep = vd.api("PATCH", f"/channels/{s['id']}/messages/{mid}", json=corps, gid=GID)
            if code == 200:
                faits[mid] = int(time.time())
                echecs.pop(mid, None)
                bilan["corriges"] += 1
            else:
                echecs[mid] = f"HTTP {code}"
                bilan["echecs"] += 1
            with LOCK:
                _ecrire(d)
            time.sleep(PAUSE_S)
    if not bilan["salons_illisibles"]:
        d["termine"] = int(time.time())
    d["bilan"] = bilan
    with LOCK:
        _ecrire(d)
    print(f"[trust-agency-anciens] {bilan['corriges']} message(s) remis au nom TRUST Agency, "
          f"{bilan['echecs']} impossible(s), {bilan['salons_illisibles']} salon(s) illisible(s)"
          + ("" if d.get("termine") else " — reprise au prochain démarrage"), flush=True)
    return bilan


def demarrer() -> bool:
    """La passe, une fois, dans son fil (web_upload.create_app, machine de
    production seulement) ; rien quand elle est déjà finie."""
    global _DEMARRE
    if _DEMARRE or _etat().get("termine"):
        return False
    _DEMARRE = True

    def fil():
        time.sleep(90)                   # laisser les relevés du démarrage passer d'abord
        try:
            passe()
        except Exception as e:                               # noqa: BLE001
            print(f"[trust-agency-anciens] {type(e).__name__}: {e}", flush=True)

    threading.Thread(target=fil, daemon=True, name="trust-agency-anciens").start()
    return True
