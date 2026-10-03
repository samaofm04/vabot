"""Le plan d'onboarding du site, publié et tenu à jour dans un salon Discord.

Le plan vit sur le tableau de bord : c'est là qu'on écrit une étape, qu'on
dépose une vidéo, qu'on réordonne. Les VA, eux, lisent Discord. Sans pont
entre les deux, chaque correction obligeait à tout reposter à la main — et au
bout de deux fois, les deux versions ne disaient plus la même chose.

CE MODULE NE REPOSTE PAS, IL CORRIGE. Un message déjà publié est MODIFIÉ sur
place : les liens que les VA se sont envoyés continuent de marcher, et le
salon ne se remplit pas d'une nouvelle copie à chaque virgule changée.

IL NE TOUCHE QUE CE QU'IL A ÉCRIT. Les messages écrits à la main dans le salon
restent là où ils sont : le pont ne connaît que les messages dont il garde
l'identifiant, et il refuse d'en adopter un qu'il n'a pas posté.

RIEN NE PART SANS CHANGEMENT RÉEL. Chaque étape porte une empreinte (son
texte plus ses médias) : tant qu'elle ne bouge pas, aucun appel n'est fait.
Sans cette empreinte, une sauvegarde du site aurait réécrit les neuf messages
à chaque frappe.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "onboarding_discord.json"
ETAT_FICHIER = DATA_DIR / "onboarding_discord_etat.json"

MAX_TEXTE = 2000
MAX_FICHIER = 24 * 1024 * 1024      # Discord refuse au-delà sans boost
MAX_JOINTES = 10
ATTENTE_S = 6.0                      # on laisse la rafale de frappes se calmer


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


def actif() -> bool:
    c = config()
    return bool(c.get("actif")) and bool(c.get("salon"))


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


# ─── ce qu'une étape donne comme message ─────────────────────────────────
def texte_de(etape: Dict[str, Any]) -> str:
    """Le message tel qu'il sera lu : titre en gras, corps, liens à la fin."""
    titre = ((etape.get("icon") or "") + " " + (etape.get("title") or "")).strip()
    corps = (etape.get("description") or "").strip()
    liens = [m.get("name") or m.get("url") for m in (etape.get("media") or [])
             if m.get("kind") == "link" and (m.get("name") or m.get("url"))]
    txt = f"**{titre}**" + (f"\n\n{corps}" if corps else "")
    if liens:
        txt += "\n\n" + "\n".join("📎 " + str(l) for l in liens)
    return txt[:MAX_TEXTE]


def fichiers_de(etape: Dict[str, Any]) -> Tuple[List[Tuple[str, bytes]], List[str]]:
    """(fichiers lisibles, ce qui a été écarté et pourquoi).

    Un média trop lourd ou disparu du disque n'est pas tu : le compte rendu le
    nomme, sinon on chercherait longtemps pourquoi une vidéo manque.
    """
    pris: List[Tuple[str, bytes]] = []
    ecartes: List[str] = []
    for m in (etape.get("media") or []):
        if m.get("kind") == "link":
            continue
        chemin = Path(str(m.get("path") or ""))
        nom = str(m.get("name") or chemin.name or "media")
        if not chemin.exists():
            ecartes.append(f"{nom} (fichier absent)")
            continue
        taille = chemin.stat().st_size
        if taille > MAX_FICHIER:
            ecartes.append(f"{nom} ({taille // (1024 * 1024)} Mo, trop lourd pour Discord)")
            continue
        if len(pris) >= MAX_JOINTES:
            ecartes.append(f"{nom} (plus de {MAX_JOINTES} pièces jointes)")
            continue
        try:
            pris.append((nom, chemin.read_bytes()))
        except Exception as e:
            ecartes.append(f"{nom} ({type(e).__name__})")
    return pris, ecartes


def empreinte(etape: Dict[str, Any]) -> str:
    """Change dès que le message rendu changerait — et pas avant."""
    med = [(str(m.get("id")), str(m.get("kind")), str(m.get("name")),
            str(m.get("size") or ""), str(m.get("url") or ""))
           for m in (etape.get("media") or [])]
    brut = json.dumps([texte_de(etape), sorted(med)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()


# ─── publier ─────────────────────────────────────────────────────────────
def publier(force: bool = False) -> Dict[str, Any]:
    """Aligne le salon sur le plan. Rend le compte rendu de ce qui a bougé."""
    bilan = {"crees": [], "corriges": [], "effaces": [], "inchanges": 0,
             "ecartes": [], "rates": []}
    if not actif():
        bilan["rates"].append("pont désactivé (data/onboarding_discord.json)")
        return bilan
    salon = str(config().get("salon"))
    try:
        import onboarding as ob
        etapes = ob.list_steps()
    except Exception as e:
        bilan["rates"].append(f"plan illisible : {type(e).__name__}: {e}")
        return bilan

    d = _etat()
    connus = d.setdefault("messages", {})
    vivants = set()

    for etape in etapes:
        sid = str(etape.get("id") or "")
        if not sid:
            continue
        vivants.add(sid)
        emp = empreinte(etape)
        fiche = connus.get(sid) or {}
        if fiche.get("id") and fiche.get("empreinte") == emp and not force:
            bilan["inchanges"] += 1
            continue
        txt = texte_de(etape)
        fichiers, ecartes = fichiers_de(etape)
        bilan["ecartes"] += [f'{etape.get("title")} : {x}' for x in ecartes]
        corps = {"content": txt, "allowed_mentions": {"parse": []}}

        if fiche.get("id"):
            # On REMPLACE les pièces jointes : sans la liste, Discord garde les
            # anciennes, et une vidéo remplacée se serait retrouvée en double.
            corps["attachments"] = [{"id": i, "filename": n}
                                    for i, (n, _o) in enumerate(fichiers)]
            if fichiers:
                code, rep = _api_fichiers("PATCH",
                                          f'/channels/{salon}/messages/{fiche["id"]}',
                                          corps, fichiers)
            else:
                code, rep = _api("PATCH", f'/channels/{salon}/messages/{fiche["id"]}',
                                 json=corps)
            if code == 200:
                connus[sid] = {"id": fiche["id"], "empreinte": emp}
                bilan["corriges"].append(etape.get("title"))
                continue
            # le message a pu être supprimé à la main : on en refait un
            print(f'[onboarding] correction refusée (HTTP {code}) pour '
                  f'{etape.get("title")!r}, nouveau message', flush=True)

        if fichiers:
            corps["attachments"] = [{"id": i, "filename": n}
                                    for i, (n, _o) in enumerate(fichiers)]
            code, rep = _api_fichiers("POST", f"/channels/{salon}/messages",
                                      corps, fichiers)
        else:
            corps.pop("attachments", None)
            code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
        if code == 200 and rep.get("id"):
            connus[sid] = {"id": str(rep["id"]), "empreinte": emp}
            bilan["crees"].append(etape.get("title"))
        else:
            bilan["rates"].append(f'{etape.get("title")} : HTTP {code} '
                                  f'{str(rep.get("message") or "")[:80]}')
        time.sleep(1.0)

    # une étape supprimée du plan n'a plus à traîner dans le salon
    for sid in [s for s in list(connus) if s not in vivants]:
        mid = str((connus.get(sid) or {}).get("id") or "")
        if mid:
            c, _r = _api("DELETE", f"/channels/{salon}/messages/{mid}")
            bilan["effaces"].append(sid if c in (200, 204) else f"{sid} (HTTP {c})")
        connus.pop(sid, None)
    _ecrire(d)
    return bilan


def _api_fichiers(methode: str, chemin: str, payload: Dict[str, Any], fichiers):
    """Comme _api, mais en multipart — Discord veut ça pour les pièces jointes."""
    import json as _j
    import os as _os
    import urllib.error
    import urllib.request
    from verif_discord import _token
    limite = "----youl4b" + _os.urandom(12).hex()
    morceaux = []

    def champ(entete: bytes, contenu: bytes):
        morceaux.append(b"--" + limite.encode() + b"\r\n" + entete + b"\r\n\r\n"
                        + contenu + b"\r\n")

    champ(b'Content-Disposition: form-data; name="payload_json"\r\n'
          b"Content-Type: application/json",
          _j.dumps(payload, ensure_ascii=False).encode())
    for i, (nom, octets) in enumerate(fichiers):
        sur = nom.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
        champ(f'Content-Disposition: form-data; name="files[{i}]"; filename="{sur}"'
              .encode() + b"\r\nContent-Type: application/octet-stream", octets)
    morceaux.append(b"--" + limite.encode() + b"--\r\n")
    corps = b"".join(morceaux)
    req = urllib.request.Request(
        "https://discord.com/api/v10" + chemin, data=corps, method=methode,
        headers={"Authorization": "Bot " + _token(),
                 "Content-Type": f"multipart/form-data; boundary={limite}",
                 "User-Agent": "DiscordBot (youl4b, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            brut = r.read()
            return r.status, (_j.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, _j.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


# ─── adoption des messages déjà postés ───────────────────────────────────
def adopter(ids: List[str]) -> Dict[str, Any]:
    """Relie des messages DÉJÀ postés aux étapes, dans l'ordre du plan.

    Sert une seule fois, pour reprendre la main sur ce qui a été publié avant
    le pont. On refuse un message que le bot n'a pas écrit : on ne modifiera
    jamais le message de quelqu'un d'autre.
    """
    import onboarding as ob
    salon = str(config().get("salon") or "")
    etapes = ob.list_steps()
    if len(ids) != len(etapes):
        return {"ok": False, "erreur": f"{len(ids)} messages pour {len(etapes)} étapes"}
    code, moi = _api("GET", "/users/@me")
    mon_id = str((moi or {}).get("id") or "")
    d = _etat()
    connus = d.setdefault("messages", {})
    pris = []
    for etape, mid in zip(etapes, ids):
        c, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
        if c != 200:
            return {"ok": False, "erreur": f"message {mid} illisible (HTTP {c})"}
        if str(((msg.get("author") or {}).get("id")) or "") != mon_id:
            return {"ok": False, "erreur": f"le message {mid} n'est pas du bot : refus"}
        connus[str(etape["id"])] = {"id": str(mid), "empreinte": empreinte(etape)}
        pris.append(etape.get("title"))
    _ecrire(d)
    return {"ok": True, "adoptes": pris}


# ─── déclenchement depuis le site ────────────────────────────────────────
_MINUTERIE: Optional[threading.Timer] = None
_VERROU = threading.Lock()


def planifier(delai: float = ATTENTE_S) -> None:
    """Demande une publication bientôt, et une seule.

    Le site enregistre à chaque frappe : publier à chaque appel aurait tapé
    sur Discord vingt fois pour une phrase. On attend que ça se calme.
    """
    global _MINUTERIE
    if not actif():
        return
    with _VERROU:
        if _MINUTERIE is not None:
            _MINUTERIE.cancel()
        _MINUTERIE = threading.Timer(delai, _tour)
        _MINUTERIE.daemon = True
        _MINUTERIE.start()


def _tour() -> None:
    try:
        b = publier()
        if any(b[k] for k in ("crees", "corriges", "effaces", "ecartes", "rates")):
            print(f"[onboarding] publication : {b}", flush=True)
    except Exception as e:
        print(f"[onboarding] publication : {type(e).__name__}: {e}", flush=True)
