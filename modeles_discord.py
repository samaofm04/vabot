"""Le salon « modèle à suivre » suit la watchlist Instagram du site.

Un compte ajouté à la watchlist apparaît dans le salon tout seul, sous forme
de lien cliquable. Sans ça, la liste postée vieillit en silence : le site
connaît douze comptes de plus et les VA suivent toujours les anciens.

CE QUI EST POSTÉ, ET DANS QUEL ORDRE. Seuls les comptes ACTIFS : un profil
introuvable ou sans un seul reel n'est pas un modèle à suivre. Les nouveaux
partent du plus gros au plus petit, comme la première fournée.

ON N'EFFACE RIEN. Un compte qui meurt reste dans le salon : le supprimer
effacerait aussi la raison pour laquelle un VA l'avait suivi, et Discord ne
rend pas un message supprimé. Ce qui tombe est SIGNALÉ, pas retiré.

ON NE REPOSTE JAMAIS. Le fichier d'état retient ce qui est déjà parti ; un
redémarrage du site ne refait pas défiler soixante liens.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "modeles_suivre.json"
CONFIG_FICHIER = DATA_DIR / "modeles_suivre_config.json"

# Va IG → le salon « 👤・modele-a-suivre »
SALON_DEFAUT = "1555926748573597849"
SERVEUR_DEFAUT = "1505418484052394004"


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


def actifs() -> Optional[List[Dict[str, Any]]]:
    """Les comptes actifs de la watchlist, du plus gros au plus petit.

    None quand la watchlist est illisible : « je ne sais pas » n'est pas
    « elle est vide ». Sans cette distinction, une lecture ratée aurait fait
    passer tout le monde pour disparu.
    """
    try:
        import insta_scraper
        lignes = insta_scraper.watchlist_status()
    except Exception as e:
        print(f"[modeles] watchlist illisible : {type(e).__name__}: {e}", flush=True)
        return None
    if not isinstance(lignes, list):
        return None
    vivants = [r for r in lignes
               if r.get("dead_days") is None and int(r.get("nb_reels") or 0) > 0]
    vivants.sort(key=lambda r: -int(r.get("followers") or 0))
    return vivants


def lien(username: str) -> str:
    return "https://instagram.com/" + str(username or "").lstrip("@")


def synchroniser(gid: str = "", salon: str = "") -> Dict[str, Any]:
    """Poste les comptes actifs qui ne sont pas encore dans le salon."""
    c = config()
    salon = str(salon or c.get("salon") or SALON_DEFAUT)
    bilan = {"ajoutes": [], "tombes": [], "deja": 0, "rates": []}

    liste = actifs()
    if liste is None:
        bilan["rates"].append("watchlist illisible : rien posté")
        return bilan

    d = _etat()
    postes = d.setdefault("postes", {})
    vivants = {str(r.get("username") or "") for r in liste}

    # un compte connu qui n'est plus actif : on le DIT, on ne l'efface pas
    bilan["tombes"] = sorted(n for n in postes if n and n not in vivants)

    for r in liste:
        nom = str(r.get("username") or "")
        if not nom:
            continue
        if postes.get(nom):
            bilan["deja"] += 1
            continue
        code, rep = _api("POST", f"/channels/{salon}/messages",
                         json={"content": lien(nom),
                               "allowed_mentions": {"parse": []}})
        if code != 200 or not (rep or {}).get("id"):
            bilan["rates"].append(f'{nom} : HTTP {code}')
            continue
        postes[nom] = {"message": str(rep["id"]), "quand": int(time.time()),
                       "abonnes": int(r.get("followers") or 0)}
        bilan["ajoutes"].append(nom)
        time.sleep(1.0)        # Discord n'aime pas plus de ~5 messages / 5 s

    if bilan["ajoutes"]:
        _ecrire(d)
    return bilan


def amorcer(salon: str = "", gid: str = "") -> Dict[str, Any]:
    """Enregistre ce qui est DÉJÀ dans le salon, sans rien reposter.

    Sert une fois, après une première fournée envoyée à la main : sans ça le
    premier tour automatique aurait reposté les soixante liens.
    """
    salon = str(salon or config().get("salon") or SALON_DEFAUT)
    code, ms = _api("GET", f"/channels/{salon}/messages", params={"limit": 100})
    if code != 200 or not isinstance(ms, list):
        return {"ok": False, "erreur": f"salon illisible (HTTP {code})"}
    d = _etat()
    postes = d.setdefault("postes", {})
    vus = 0
    for m in ms:
        txt = str(m.get("content") or "").strip()
        if "instagram.com/" not in txt:
            continue
        nom = txt.rsplit("instagram.com/", 1)[-1].strip().strip("/")
        if nom and nom not in postes:
            postes[nom] = {"message": str(m.get("id") or ""),
                           "quand": int(time.time()), "abonnes": 0}
            vus += 1
    _ecrire(d)
    return {"ok": True, "repris": vus, "total": len(postes)}
