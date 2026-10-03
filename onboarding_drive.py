"""Le Drive range les vidéos, le plan les ramasse tout seul.

Le propriétaire dépose ses vidéos dans un dossier par étape, sur Google Drive.
Ce module les y trouve et les rattache à l'étape correspondante du plan — qui
les publie ensuite dans Discord. Personne ne recopie une adresse à la main.

LE NUMÉRO EN TÊTE DU DOSSIER FAIT LOI. « 01 - JOUR 0 … » va à la deuxième
étape, quoi qu'il arrive au titre ensuite. Se fier au titre aurait casse le
rattachement au premier mot change, et une video serait partie sur le mauvais
jour sans que personne le voie.

UNE VIDÉO N'EST AJOUTÉE QU'UNE FOIS. On reconnaît un fichier à son identifiant
Drive, pas à son nom : renommer un fichier ne doit pas le faire apparaître en
double dans le message.

RIEN N'EST SUPPRIMÉ. Retirer une vidéo du Drive ne la retire pas de l'étape :
le plan reste la source, et on n'efface pas le travail de quelqu'un sur la foi
d'un dossier qu'on a peut-être mal lu.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "onboarding_drive.json"

# Mon Drive > Unbording, partagé avec le compte de service en Éditeur
RACINE_DEFAUT = "1ZxZCjY8VclVX3VDaisdECX1u6UIs8RTz"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOC = "application/vnd.google-apps.document"
NOM_DOC = "texte"
MEDIA = ("video/", "image/")
ETAT_FICHIER = DATA_DIR / "onboarding_drive_etat.json"


def _etat() -> Dict[str, Any]:
    try:
        return safe_json.load(ETAT_FICHIER, default={}) or {}
    except Exception:
        return {}


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _empreinte(t: str) -> str:
    import hashlib
    return hashlib.sha1(str(t or "").strip().encode("utf-8")).hexdigest()


def texte_de_etape(etape: Dict[str, Any]) -> str:
    """Ce qu'on écrit dans le doc : le titre, puis le corps de l'étape."""
    titre = ((etape.get("icon") or "") + " " + (etape.get("title") or "")).strip()
    return (titre + "\n\n" + (etape.get("description") or "").strip()).strip() + "\n"


def _lire_doc(session, doc_id: str) -> Optional[str]:
    r = session.get(f"{API}/{doc_id}/export",
                    params={"mimeType": "text/plain", "supportsAllDrives": "true"},
                    timeout=60)
    if r.status_code != 200:
        print(f"[drive] doc {doc_id} illisible : HTTP {r.status_code}", flush=True)
        return None
    # On decode NOUS-MEMES en UTF-8 : Google n'annonce pas l'encodage de
    # l'export, requests retombe alors sur le latin-1 et « passées » revenait
    # « passÃ©es » — tout le texte du plan s'abimait a chaque tour.
    try:
        texte = r.content.decode("utf-8")
    except UnicodeDecodeError:
        texte = r.content.decode("utf-8", errors="replace")
        print(f"[drive] doc {doc_id} : octets illisibles remplaces", flush=True)
    return texte.replace("\r\n", "\n").replace("\ufeff", "")


def _ecrire_doc(session, doc_id: str, texte: str) -> bool:
    r = session.patch(f"{UPLOAD}/{doc_id}",
                      params={"uploadType": "media", "supportsAllDrives": "true"},
                      data=str(texte).encode("utf-8"),
                      headers={"Content-Type": "text/plain; charset=UTF-8"}, timeout=120)
    if r.status_code not in (200, 201):
        print(f"[drive] ecriture du doc {doc_id} : HTTP {r.status_code}", flush=True)
        return False
    return True


def _creer_doc(session, parent: str, nom: str, texte: str) -> str:
    meta = json.dumps({"name": nom, "parents": [parent], "mimeType": DOC},
                      ensure_ascii=False)
    lim = "----vaboundary42"
    corps = (f"--{lim}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
             f"--{lim}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{texte}\r\n"
             f"--{lim}--\r\n").encode("utf-8")
    r = session.post(UPLOAD, params={"uploadType": "multipart", "supportsAllDrives": "true"},
                     data=corps,
                     headers={"Content-Type": f"multipart/related; boundary={lim}"},
                     timeout=120)
    return r.json().get("id", "") if r.status_code in (200, 201) else ""


def _corps_du_doc(texte: str) -> str:
    """Le doc porte le titre en premiere ligne : on ne garde que le corps.

    Sans ca, le titre serait recopie dans la description et apparaitrait deux
    fois dans le message Discord.
    """
    lignes = str(texte or "").split("\n")
    if lignes and lignes[0].strip():
        lignes = lignes[1:]
    return "\n".join(lignes).strip()


def config() -> Dict[str, Any]:
    try:
        return safe_json.load(CONFIG_FICHIER, default={}) or {}
    except Exception:
        return {}


def racine() -> str:
    return str(config().get("racine") or RACINE_DEFAUT)


def actif() -> bool:
    return config().get("actif", True) is not False


def _enfants(session, parent: str) -> List[Dict[str, Any]]:
    r = session.get(API, params={"q": f"'{parent}' in parents and trashed = false",
                                 "fields": "files(id,name,mimeType,size,createdTime)",
                                 "pageSize": 200, "orderBy": "name",
                                 "includeItemsFromAllDrives": "true",
                                 "supportsAllDrives": "true"}, timeout=60)
    if r.status_code != 200:
        print(f"[drive] lecture de {parent} : HTTP {r.status_code}", flush=True)
        return []
    return r.json().get("files", [])


def _rang(nom: str) -> Optional[int]:
    """« 03 - JOUR 1 … » → 3. None si le dossier n'est pas numéroté."""
    m = re.match(r"\s*(\d{1,2})\s*[-–—]", str(nom or ""))
    return int(m.group(1)) if m else None


def _deja(etape: Dict[str, Any], file_id: str) -> bool:
    """Ce fichier Drive est-il déjà rattaché ? On compare l'identifiant."""
    for m in (etape.get("media") or []):
        if file_id and file_id in str(m.get("url") or "") + str(m.get("name") or ""):
            return True
    return False


def scanner() -> Dict[str, Any]:
    """Ramasse les vidéos du Drive et les rattache aux étapes. Rend le bilan."""
    bilan = {"ajoutes": [], "textes": [], "ignores": [], "rates": []}
    if not actif():
        bilan["rates"].append("ramassage désactivé")
        return bilan
    try:
        import gdrive_sync as g
        import onboarding as ob
        session = g._session()
    except Exception as e:
        bilan["rates"].append(f"Drive indisponible : {type(e).__name__}: {e}")
        return bilan
    if session is None:
        bilan["rates"].append("Drive indisponible : pas de session")
        return bilan

    etapes = ob.list_steps()
    etat = _etat()
    change = False
    for d in _enfants(session, racine()):
        if not str(d.get("mimeType", "")).endswith("folder"):
            continue
        n = _rang(d.get("name"))
        if n is None or n >= len(etapes):
            bilan["ignores"].append(f'{d.get("name")} (hors plan)')
            continue
        etape = etapes[n]
        # --- le texte : un Google Doc, ouvert et modifiable d'un clic
        try:
            _texte(session, ob, d, etape, etat, bilan)
            etape = ob.get_step(etape["id"]) or etape
        except Exception as e:
            bilan["rates"].append(f'texte de {etape.get("title")} : '
                                  f'{type(e).__name__}: {e}')
        for f in _enfants(session, d["id"]):
            if not str(f.get("mimeType", "")).startswith(MEDIA):
                continue
            etape = ob.get_step(etape["id"]) or etape      # relire : on vient d'ecrire
            if _deja(etape, f["id"]):
                continue
            url = f'https://drive.google.com/file/d/{f["id"]}/view'
            r = ob.add_media_link(etape["id"], url, f.get("name") or "vidéo")
            if r.get("ok"):
                bilan["ajoutes"].append(f'{etape.get("title")} ← {f.get("name")}')
                change = True
            else:
                bilan["rates"].append(f'{f.get("name")} : {r.get("error")}')
    _ecrire(etat)
    if change or bilan.get("textes"):
        # On publie TOUT DE SUITE, sans passer par la minuterie : elle meurt
        # avec le processus, et un ramassage lance a la main laissait donc les
        # videos rattachees au plan mais absentes de Discord — on croyait que
        # la synchro ne marchait pas.
        try:
            import onboarding_discord as od
            bilan["publication"] = od.publier()
        except Exception as e:
            bilan["rates"].append(f"publication : {type(e).__name__}: {e}")
    return bilan


def _texte(session, ob, dossier: Dict[str, Any], etape: Dict[str, Any],
           etat: Dict[str, Any], bilan: Dict[str, Any]) -> None:
    """Tient le doc et l'étape d'accord. Le dernier qui a écrit l'emporte.

    Le doc est créé au premier passage avec le texte de l'étape. Ensuite, si le
    doc a changé, il remonte dans l'étape ; sinon, si l'étape a changé sur le
    site, elle redescend dans le doc. Sans cette comparaison, chaque tour aurait
    écrasé l'un par l'autre, et une correction sur deux serait partie en fumée.
    """
    cle = str(etape.get("id") or "")
    fiche = (etat.setdefault("textes", {})).setdefault(cle, {})
    attendu = texte_de_etape(etape)

    doc_id = str(fiche.get("doc") or "")
    if not doc_id:
        for f in _enfants(session, dossier["id"]):
            if f.get("mimeType") == DOC and str(f.get("name") or "").startswith(NOM_DOC):
                doc_id = f["id"]
                break
    if not doc_id:
        doc_id = _creer_doc(session, dossier["id"], NOM_DOC, attendu)
        if not doc_id:
            bilan["rates"].append(f'{etape.get("title")} : doc non cree')
            return
        fiche.update({"doc": doc_id, "doc_h": _empreinte(attendu),
                      "plan_h": _empreinte(attendu)})
        bilan["textes"].append(f'{etape.get("title")} : doc cree')
        return

    fiche["doc"] = doc_id
    lu = _lire_doc(session, doc_id)
    if lu is None:
        return
    h_doc, h_plan = _empreinte(lu), _empreinte(attendu)
    if h_doc != str(fiche.get("doc_h") or ""):
        # le doc a bouge : il fait foi
        corps = _corps_du_doc(lu)
        if corps != (etape.get("description") or "").strip():
            ob.update_step(etape["id"], description=corps)
            bilan["textes"].append(f'{etape.get("title")} : texte repris du doc')
        fiche["doc_h"] = h_doc
        fiche["plan_h"] = _empreinte(texte_de_etape(ob.get_step(etape["id"]) or etape))
        return
    if h_plan != str(fiche.get("plan_h") or ""):
        # c'est le site qui a bouge : le doc suit
        if _ecrire_doc(session, doc_id, attendu):
            fiche["doc_h"] = _empreinte(attendu)
            fiche["plan_h"] = h_plan
            bilan["textes"].append(f'{etape.get("title")} : doc mis a jour')
