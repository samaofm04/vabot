"""Le lien d'un VA : un tracking link MyPuls, et le lien GetMySocial dessus.

Un VA a besoin d'une adresse à poster sur Twitter. Cette adresse doit être à
LUI SEUL, sinon rien ne marche : le podium ne saurait plus qui a amené quel
clic, et MyPuls ne saurait plus quel abonné vient de qui.

La chaîne, dans cet ordre, et l'ordre compte :

1. MyPuls crée le tracking link. C'est lui qui fabrique le code (« c112 ») et
   l'adresse « onlyfans.com/<modèle>/c112 ». L'API publique ne sait que LIRE —
   la création vit dans l'interface, on passe donc par la session à cookies,
   comme le fait déjà le rafraîchissement des pushs.
2. GetMySocial crée le lien court qui pointe dessus, nommé « va_@pseudo », dans
   l'espace des VA. C'est ce lien-là que compte le podium.

MYPULS NE SAIT PAS SUPPRIMER UN TRACKING LINK. Aucune route de suppression
n'existe dans son interface. Un lien créé par erreur reste là pour toujours :
d'où le garde-fou d'unicité — on refuse plutôt que de créer un doublon — et le
refus net quand la configuration manque, plutôt que de deviner une modèle.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "liens_va_config.json"
ETAT_FICHIER = DATA_DIR / "liens_va.json"

EQUIPE_VA = "tm_6a0e4739bfa0c238f20a8bf5"


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    """{creator_id, modele, equipe, gabarit} — ce qu'il faut savoir avant de créer."""
    return _lire(CONFIG_FICHIER, {})


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def manque() -> str:
    """Ce qui empêche de créer un lien aujourd'hui, en une phrase. « » si tout va."""
    c = config()
    if not c.get("creator_id"):
        return ("aucune créatrice choisie : le tracking link serait créé chez "
                "n'importe qui. À poser dans data/liens_va_config.json "
                "(creator_id, modele).")
    if not c.get("gabarit"):
        return ("aucun lien gabarit GetMySocial pour l'espace des VA : la "
                "création copie un lien existant (boutons, pixels, design). "
                "À poser dans data/liens_va_config.json (gabarit).")
    return ""


# ─── MyPuls : le tracking link ───────────────────────────────────────────
def creer_tracking(nom: str, creator_id: Optional[int] = None) -> Dict[str, Any]:
    """Crée un tracking link chez MyPuls. Rend {ok, url, code, erreur}.

    Le lien est créé pour la créatrice SÉLECTIONNÉE : on bascule d'abord, sinon
    il atterrit chez la précédente — et on ne peut pas l'effacer ensuite.
    """
    import mypuls
    cid = int(creator_id or config().get("creator_id") or 0)
    if not cid:
        return {"ok": False, "erreur": "aucune créatrice choisie"}
    nom = str(nom or "").strip()[:60]
    if not nom:
        return {"ok": False, "erreur": "nom vide"}

    s = mypuls._make_session()
    if s is None:
        return {"ok": False, "erreur": "session MyPuls indisponible (cookies)"}
    try:
        s.get(f"{mypuls.BASE_URL}/switch-creator/{cid}?from=app_pushs",
              timeout=mypuls.TIMEOUT, allow_redirects=True)
        page = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
        jeton = ""
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        if m:
            jeton = m.group(1)
        avant = {l["code"] for l in _tracking_de(s, page.text)}
        r = s.post(f"{mypuls.BASE_URL}/tracking-stats/create",
                   data={"name": nom, "_token": jeton},
                   headers={"X-CSRF-TOKEN": jeton,
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json"},
                   timeout=mypuls.TIMEOUT)
        mypuls._save_rotated_cookies(s)
        if r.status_code != 200:
            return {"ok": False, "erreur": f"MyPuls a refusé (HTTP {r.status_code})"}
        try:
            rep = r.json()
        except Exception:
            return {"ok": False, "erreur": "MyPuls a répondu autre chose que du JSON "
                                           "(session expirée ?)"}
        if not rep.get("success"):
            return {"ok": False, "erreur": str(rep.get("message") or "refus MyPuls")[:140]}

        # MyPuls ne rend pas toujours le lien créé : on relit la page et on
        # prend celui qui n'y était pas. Deviner le code (« le dernier + 1 »)
        # donnerait une adresse qui n'existe pas.
        page2 = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
        neufs = [l for l in _tracking_de(s, page2.text) if l["code"] not in avant]
        vise = [l for l in neufs if l["nom"] == nom] or neufs
        if not vise:
            return {"ok": False, "erreur": "créé, mais introuvable à la relecture — "
                                           "à vérifier à la main dans MyPuls"}
        return {"ok": True, "url": vise[0]["url"], "code": vise[0]["code"], "erreur": ""}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:120]}"}


def _tracking_de(session, html: str):
    """Les tracking links lus dans la page : [{code, nom, url}]."""
    out, vus = [], set()
    for m in re.finditer(r'https://onlyfans\.com/([A-Za-z0-9._-]+)/(c\d+)', html):
        code = m.group(2)
        if code in vus:
            continue
        vus.add(code)
        out.append({"code": code, "nom": "", "url": m.group(0)})
    return out


# ─── GetMySocial : le lien court ─────────────────────────────────────────
def creer_gms(nom: str, url: str) -> Dict[str, Any]:
    """Duplique le gabarit vers un lien neuf pointant sur `url`."""
    import gms
    c = config()
    gabarit = str(c.get("gabarit") or "")
    equipe = str(c.get("equipe") or EQUIPE_VA)
    if not gabarit:
        return {"ok": False, "erreur": "aucun gabarit GetMySocial"}
    for _ in range(5):
        sc = gms.generate_random_prefix(4) + "va"
        r = gms.duplicate_link(gabarit, sc, nom, url, equipe)
        if r.get("ok"):
            lien = r.get("link") or {}
            return {"ok": True, "shortcode": sc,
                    "url": f"{gms.PUBLIC_LINK_DOMAIN}/{sc}",
                    "id": str(lien.get("id") or ""), "erreur": ""}
        if "shortcode" not in str(r.get("error") or "").lower():
            return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    return {"ok": False, "erreur": "cinq shortcodes tirés, tous pris"}


# ─── la chaîne ───────────────────────────────────────────────────────────
def lien_de(gid: str, uid: str) -> Dict[str, Any]:
    return (_etat().get("liens") or {}).get(f"{gid}:{uid}") or {}


def creer_pour(gid: str, uid: str, pseudo: str, par: str = "") -> Dict[str, Any]:
    """Toute la chaîne pour un VA. Rend {ok, public_url, tracking, erreur}.

    Refuse si ce VA en a déjà un : MyPuls ne sait pas supprimer, un doublon
    resterait à vie et fausserait les deux classements.
    """
    import time as _t
    deja = lien_de(gid, uid)
    if deja.get("public_url"):
        return {"ok": False, "deja": True, "erreur": "ce VA a déjà un lien",
                "public_url": deja["public_url"], "tracking": deja.get("tracking", "")}
    empeche = manque()
    if empeche:
        return {"ok": False, "erreur": empeche}

    nom = f"VA @{pseudo}"[:60]
    t = creer_tracking(nom)
    if not t.get("ok"):
        return {"ok": False, "erreur": "MyPuls : " + t.get("erreur", "")}
    g = creer_gms(f"va_@{pseudo}"[:60], t["url"])
    if not g.get("ok"):
        # le tracking link est créé et ne peut pas être défait : on le DIT,
        # pour qu'il soit repris à la main plutôt que perdu
        return {"ok": False, "tracking": t["url"],
                "erreur": f'GetMySocial : {g.get("erreur")} — le tracking link '
                          f'{t["code"]} existe déjà chez MyPuls, à réutiliser.'}
    d = _etat()
    (d.setdefault("liens", {}))[f"{gid}:{uid}"] = {
        "pseudo": pseudo, "public_url": g["url"], "shortcode": g["shortcode"],
        "tracking": t["url"], "code": t["code"], "par": str(par),
        "quand": int(_t.time())}
    _ecrire(d)
    return {"ok": True, "public_url": g["url"], "shortcode": g["shortcode"],
            "tracking": t["url"], "erreur": ""}
