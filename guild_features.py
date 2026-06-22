"""Gating des fonctions par serveur Discord (multi-serveurs).

Principe :
- Un serveur NON listé dans data/guild_features.json a **toutes** les fonctions
  (le serveur principal n'est donc jamais impacté, aucune config requise).
- Un serveur **listé** n'a QUE les fonctions de sa liste (serveur « bridé »).

Fonctions (clés) :
- contenu    : menu de contenu (Reel/Story/Post/Pseudo/Name/Bio/PP) + boutons
               Ajouter un compte / Mes comptes Insta
- onboarding : parcours d'arrivée (vidéos + étapes)
- clics      : bouton Mes clics + récap quotidien des clics
- liens      : Demander un lien + Générer le lien (GMS)
- tickets    : création auto d'un salon/ticket à l'arrivée d'un membre
- statut     : ronds 🟢/🟠/🔴 d'activité devant les salons va-
"""
import json
import pathlib

_FILE = pathlib.Path(__file__).resolve().parent / "data" / "guild_features.json"

ALL_FEATURES = ("contenu", "onboarding", "clics", "liens", "tickets", "statut")


def _load() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> bool:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def _gid(guild_or_id):
    """Accepte un id, un objet guild, ou None -> renvoie un str ou None."""
    if guild_or_id is None:
        return None
    gid = getattr(guild_or_id, "id", guild_or_id)
    try:
        return str(int(gid))
    except Exception:
        return None


def get_features(guild_or_id) -> set:
    """Set des fonctions activées pour ce serveur.
    Serveur inconnu / non configuré -> TOUTES les fonctions (non bridé)."""
    gid = _gid(guild_or_id)
    if gid is None:
        return set(ALL_FEATURES)
    v = _load().get(gid)
    if v is None:
        return set(ALL_FEATURES)
    if not isinstance(v, list):
        return set(ALL_FEATURES)
    return {x for x in v if x in ALL_FEATURES}


def enabled(guild_or_id, feature: str) -> bool:
    """True si `feature` est active sur ce serveur (toujours True si non bridé)."""
    return feature in get_features(guild_or_id)


def is_restricted(guild_or_id) -> bool:
    """True si le serveur est explicitement configuré (bridé)."""
    gid = _gid(guild_or_id)
    return gid is not None and gid in _load()


def set_features(guild_or_id, features) -> set:
    """Définit la liste des fonctions d'un serveur (le bride). Retourne le set."""
    gid = _gid(guild_or_id)
    if gid is None:
        return set(ALL_FEATURES)
    d = _load()
    d[gid] = [f for f in features if f in ALL_FEATURES]
    _save(d)
    return get_features(gid)


def clear_guild(guild_or_id) -> bool:
    """Retire le bridage d'un serveur -> il repasse à TOUTES les fonctions."""
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load()
    if gid in d:
        d.pop(gid, None)
        _save(d)
        return True
    return False


# ---- Mode Threads (par serveur) : menu réduit + comptes Threads au lieu d'Instagram ----
# Stocké à part pour ne pas toucher le format des fonctions. Défaut = OFF partout
# (donc le serveur principal reste en mode Instagram normal).
_THREADS_FILE = pathlib.Path(__file__).resolve().parent / "data" / "guild_threads.json"


def _load_threads() -> dict:
    try:
        d = json.loads(_THREADS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def threads_mode(guild_or_id) -> bool:
    """True si le serveur est en mode Threads (menu réduit + comptes threads.net)."""
    gid = _gid(guild_or_id)
    return bool(gid is not None and _load_threads().get(gid))


def set_threads(guild_or_id, on: bool) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_threads()
    if on:
        d[gid] = True
    else:
        d.pop(gid, None)
    try:
        _THREADS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _THREADS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return False
    return bool(on)


# ---- Catégorie d'accueil des nouveaux VAs (par serveur) ----
# Si définie, les nouveaux salons va- d'un serveur vont dans CETTE catégorie
# (ex: "Equipe 1") au lieu d'une catégorie par identité.
_VACAT_FILE = pathlib.Path(__file__).resolve().parent / "data" / "va_category.json"


def _load_vacat() -> dict:
    try:
        d = json.loads(_VACAT_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_va_category_id(guild_or_id):
    """ID de la catégorie où placer les nouveaux salons va- de ce serveur, ou None."""
    gid = _gid(guild_or_id)
    if gid is None:
        return None
    try:
        return int(_load_vacat().get(gid)) if _load_vacat().get(gid) else None
    except Exception:
        return None


def set_va_category(guild_or_id, category_id) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_vacat()
    if category_id:
        d[gid] = int(category_id)
    else:
        d.pop(gid, None)
    try:
        _VACAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _VACAT_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return False
    return True


# ---- Identité par défaut d'un serveur (ex: "jessye" pour le marché US) ----
# Si définie, les nouveaux VAs de ce serveur reçoivent CETTE identité au lieu
# de la rotation normale (qui exclut les identités jailbreak-only). Permet
# d'avoir un marché US séparé du marché français.
_SVID_FILE = pathlib.Path(__file__).resolve().parent / "data" / "server_identity.json"


def _load_svid() -> dict:
    try:
        d = json.loads(_SVID_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_server_identity(guild_or_id):
    """Identité par défaut des VAs de ce serveur (str), ou None."""
    gid = _gid(guild_or_id)
    if gid is None:
        return None
    v = _load_svid().get(gid)
    return v if (isinstance(v, str) and v.strip()) else None


def set_server_identity(guild_or_id, ident) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_svid()
    if ident and str(ident).strip():
        d[gid] = str(ident).strip().lower()
    else:
        d.pop(gid, None)
    try:
        _SVID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SVID_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return False
    return True
