# -*- coding: utf-8 -*-
"""outlook_comptes.py — le coffre des adresses Outlook du proprietaire.

POURQUOI (demande du proprietaire, Va IG) : il garde SES comptes Outlook
(adresse + mot de passe + secret 2FA) sur une page du site. Un VA en demande
un ; le manager, qui est a cote de lui, valide ; le bot envoie alors l'adresse
et le mot de passe dans le ticket du VA, et le code 2FA se tire a la demande
dans le salon adresse-outlook. Le secret 2FA (« le code a 13 chiffres ») ne
sort JAMAIS : ni vers Discord, ni dans le HTML -- il ne sert qu'a calculer le
code du moment, cote serveur (totp.py).

Logique PURE (ni Discord ni Flask) pour qu'elle soit testable seule :
attribution du pool, recherche par VA, ajout/suppression, et les textes
livres (ou le secret n'apparait, par construction, jamais).

Ecritures ATOMIQUES (safe_json) : une coupure au mauvais moment laissait
sinon un JSON tronque et le proprietaire perdait des comptes.
"""
from __future__ import annotations

import time
from pathlib import Path

import safe_json
import totp

DATA_DIR = Path("data")
FICHIER = DATA_DIR / "outlook_comptes.json"

#: Ce qu'on affiche a la place d'un secret : jamais le seed, jamais le mot de
#: passe sur la page admin. Le mot de passe ne se voit QUE dans le ticket du VA.
MASQUE = "••••••"   # ••••••

#: Le salon ou tirer le code 2FA (nom affiche dans la livraison).
SALON_2FA = "adresse-outlook"


def charger() -> dict:
    d = safe_json.load(FICHIER, default={"comptes": []})
    if not isinstance(d, dict):
        d = {"comptes": []}
    liste = d.get("comptes")
    if not isinstance(liste, list):
        liste = []
    d["comptes"] = [c for c in liste if isinstance(c, dict)]
    return d


def _ecrire(d: dict) -> None:
    """Ecrit le coffre de facon atomique. LEVE si l'ecriture echoue : un compte
    attribue mais jamais inscrit s'afficherait « libre » et serait redonne a
    quelqu'un d'autre -- on prefere remonter l'echec."""
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(FICHIER, d):
        raise OSError("%s non ecrit" % FICHIER.name)


def comptes() -> list:
    return charger()["comptes"]


def _horodatage(maintenant=None) -> str:
    t = time.time() if maintenant is None else maintenant
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def _nouvel_id(d: dict) -> str:
    """Un identifiant numerique jamais reutilise (le max + 1) : reutiliser
    celui d'un compte supprime ferait pointer un vieux lien ailleurs."""
    n = 0
    for c in d["comptes"]:
        try:
            n = max(n, int(c.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return str(n + 1)


def ajouter(email: str, password: str, seed: str):
    """Ajoute un compte. Rend (True, compte) ou (False, raison).

    Le seed DOIT etre un base32 valide : sinon le code 2FA serait faux en
    silence. On le range normalise (majuscules, sans espaces)."""
    email = (email or "").strip()
    password = password or ""
    seed = (seed or "").strip()
    if not email or not password or not seed:
        return False, "Adresse, mot de passe et code 2FA sont tous obligatoires."
    if not totp.seed_valide(seed):
        return False, "Le code 2FA n'est pas un secret base32 valide."
    d = charger()
    compte = {
        "id": _nouvel_id(d),
        "email": email,
        "password": password,
        "seed": seed.replace(" ", "").replace("-", "").upper(),
        "statut": "libre",
        "uid": "",
        "va": "",
        "attribue_le": "",
        "note": "",
    }
    d["comptes"].append(compte)
    _ecrire(d)
    return True, compte


def supprimer(cid) -> bool:
    """Supprime un compte par id. Rend False si rien n'a bouge (id inconnu) :
    on ne cache pas un echec de suppression."""
    d = charger()
    avant = len(d["comptes"])
    d["comptes"] = [c for c in d["comptes"] if str(c.get("id")) != str(cid)]
    if len(d["comptes"]) == avant:
        return False
    _ecrire(d)
    return True


def compte_de_uid(uid):
    """Le compte attribue a ce VA (uid Discord), ou None."""
    uid = str(uid)
    for c in comptes():
        if c.get("statut") == "attribue" and str(c.get("uid")) == uid:
            return c
    return None


def attribuer(uid, va_nom: str, maintenant=None):
    """Attribue un compte LIBRE au VA et le marque « attribue ». Jamais deux
    fois le meme compte, jamais un deja attribue, jamais de recyclage.

    Rend (compte, etat) :
      - (compte, "deja") : ce VA en avait deja un -> on rend le sien, pas un neuf ;
      - (compte, "neuf") : un compte libre vient de lui etre attribue ;
      - (None,   "vide") : plus aucun compte libre.
    """
    d = charger()
    uid = str(uid)
    # Deja une adresse pour ce VA : ne pas en bruler une seconde (double clic,
    # deux managers, demande repetee avant validation).
    for c in d["comptes"]:
        if c.get("statut") == "attribue" and str(c.get("uid")) == uid:
            return c, "deja"
    for c in d["comptes"]:
        if c.get("statut") == "libre":
            c["statut"] = "attribue"
            c["uid"] = uid
            c["va"] = va_nom or ""
            c["attribue_le"] = _horodatage(maintenant)
            _ecrire(d)
            return c, "neuf"
    return None, "vide"


def nb_libres() -> int:
    return sum(1 for c in comptes() if c.get("statut") == "libre")


# ---- Textes livres (PURS) : le seed n'y figure jamais -----------------------

def texte_livraison(compte: dict) -> str:
    """Le message depose dans le ticket du VA : adresse + mot de passe, et OU
    tirer le code. JAMAIS le seed."""
    return (
        "\U0001F4E7 **Ton adresse Outlook**\n"
        "Adresse : `%s`\n"
        "Mot de passe : `%s`\n"
        "\U0001F510 Ton code 2FA : clique sur « Code 2FA » dans #%s"
        % (compte.get("email", ""), compte.get("password", ""), SALON_2FA)
    )


def texte_2fa(compte: dict, maintenant=None):
    """L'ephemere du bouton « Code 2FA » : adresse + code du moment + reste.
    Rend (texte, code, secondes). JAMAIS le seed."""
    code, restantes = totp.code_totp(compte.get("seed", ""), maintenant)
    texte = ("\U0001F4E7 %s\n\U0001F510 Code 2FA : **%s** · encore %d s"
             % (compte.get("email", ""), code, restantes))
    return texte, code, restantes
