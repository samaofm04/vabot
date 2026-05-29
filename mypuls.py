"""Client pour l'API MyPuls / MymUtils (mymutils.fr).

MyPuls.app est la nouvelle UI au-dessus du backend `mymutils.fr` utilisé par
l'extension Chrome "MymUtils". L'auth se fait via la clé API "Connexion
Extension Chrome" disponible dans le profil MyPuls.

Pattern : POST `{"token": KEY, "modelName": MYM_USERNAME}` en JSON body.

Endpoints utilisés ici :
- POST /userInfo  -> retourne {res, email, revenues (HTML), modeles (HTML)}
- POST /claim     -> claime un modèle (normalement fait auto par l'extension)

PRÉREQUIS : au moins un modèle MYM doit avoir été "claimed" pour ce token,
sinon /userInfo retourne "Erreur vous n'êtes pas connecté : 2".
Le claim se fait normalement automatiquement par l'extension Chrome quand
l'utilisateur visite creators.mym.fans connecté au compte modèle.

Stockage local : data/mypuls_config.json
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "mypuls_config.json"
API_BASE = "https://mymutils.fr"
TIMEOUT = 30


# ============ Config ============

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def save_api_key(key: str):
    cfg = load_config()
    cfg["api_key"] = key.strip()
    save_config(cfg)


def get_api_key() -> str:
    return load_config().get("api_key", "")


def is_configured() -> bool:
    k = get_api_key()
    # La clé est une chaîne hex de 64 caractères
    return bool(k) and len(k) >= 32


# ============ Mapping identité VA -> nom modèle MYM ============

def get_model_for_identity(identity: str) -> str:
    cfg = load_config()
    mapping = cfg.get("model_map", {})
    return mapping.get(identity.lower().strip(), "")


def set_model_for_identity(identity: str, model_name: str):
    cfg = load_config()
    mapping = cfg.get("model_map", {})
    ident = identity.lower().strip()
    model_clean = model_name.strip()
    if model_clean:
        mapping[ident] = model_clean
    else:
        mapping.pop(ident, None)
    cfg["model_map"] = mapping
    save_config(cfg)


def list_model_map() -> Dict[str, str]:
    return load_config().get("model_map", {})


def list_unique_models() -> List[str]:
    """Liste sans doublon des noms MYM mappés."""
    return sorted(set(list_model_map().values()))


# ============ Appels API ============

def _post(path: str, payload: dict) -> Dict[str, Any]:
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "Clé API MyPuls non configurée"}
    body = dict(payload)
    body["token"] = api_key
    try:
        r = requests.post(
            f"{API_BASE}{path}",
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=TIMEOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:200]}"}
    text = r.text
    # Le serveur renvoie "Erreur ..." en plain text en cas d'erreur
    if text.startswith("Erreur") or text.strip() == "Error":
        return {"ok": False, "error": text.strip()[:300]}
    # Sinon : essayer de parser en JSON
    try:
        data = json.loads(text)
    except Exception:
        # Pas du JSON, retourner le texte brut
        return {"ok": True, "data": text}
    return {"ok": True, "data": data}


def user_info(model_name: str) -> Dict[str, Any]:
    """Récupère les infos d'un modèle. Retourne :
    {ok, data: {res, email, revenues (HTML), modeles (HTML), ...}, error}
    """
    if not model_name.strip():
        return {"ok": False, "error": "modelName requis"}
    return _post("/userInfo", {"modelName": model_name.strip()})


def claim_model(model_name: str) -> Dict[str, Any]:
    """Réclame un nom de modèle pour ce token.

    Note : normalement fait automatiquement par l'extension Chrome quand
    l'utilisateur visite creators.mym.fans logué en tant que ce modèle.
    Appeler manuellement sans être logué sur MYM échouera probablement.
    """
    if not model_name.strip():
        return {"ok": False, "error": "modelName requis"}
    return _post(f"/claim?modelName={model_name.strip()}", {"modelName": model_name.strip()})


def ping() -> Dict[str, Any]:
    """Test : vérifie que le serveur répond. Difficile de différencier
    'token invalide' de 'aucun modèle claimed' sans essayer un vrai nom de
    modèle. Cette fonction confirme juste que le serveur tourne et accepte
    le format de la requête."""
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "Clé API MyPuls non configurée"}
    try:
        r = requests.post(
            f"{API_BASE}/userInfo",
            headers={"Content-Type": "application/json"},
            json={"token": api_key, "modelName": ""},
            timeout=TIMEOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    return {
        "ok": True,
        "info": "Serveur joignable. Pour vérifier ton token et voir tes ventes, configure un modèle ci-dessous."
    }
