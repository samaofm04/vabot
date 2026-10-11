# -*- coding: utf-8 -*-
"""totp.py — codes TOTP (RFC 6238) calcules SUR LE SERVEUR, sans dependance.

POURQUOI : le coffre d'adresses Outlook garde un secret TOTP (le « code a 13
chiffres », en realite un secret base32) par compte. Ce secret ne sort JAMAIS
vers Discord ni vers une page : seul le code a 6 chiffres du moment est rendu,
calcule ici. On n'ajoute pas pyotp pour ca -- hmac + hashlib suffisent, et une
dependance de moins est une panne de moins au demarrage du bot.

Compatible RFC 6238 (SHA1, pas de 30 s, 6 chiffres). Verifie par le vecteur de
test officiel : secret ASCII « 12345678901234567890 » (base32
« GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ ») donne « 287082 » a l'instant unix 59.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time


def _decoder_seed(seed: str) -> bytes:
    """Decode un secret base32. LEVE (binascii.Error / ValueError) si invalide.

    Base32 tolere : espaces retires, minuscules acceptees, remplissage « = »
    complete. On NE masque PAS une erreur -- un seed invalide doit etre refuse
    a l'ajout, pas donner un code faux en silence."""
    s = (seed or "").strip().replace(" ", "").replace("-", "").upper()
    if not s:
        raise ValueError("seed vide")
    # base32 se lit par blocs de 8 caracteres : on complete le remplissage.
    s += "=" * ((-len(s)) % 8)
    return base64.b32decode(s, casefold=True)


def seed_valide(seed: str) -> bool:
    """Vrai si `seed` est un base32 decodable et non vide."""
    try:
        return bool(_decoder_seed(seed))
    except (binascii.Error, ValueError):
        return False


def code_totp(seed: str, t: float | None = None, pas: int = 30, chiffres: int = 6):
    """Rend (code, secondes_restantes) pour le secret base32 `seed`.

    `t` : instant unix (defaut : maintenant). `secondes_restantes` : temps
    avant que le code change (encore N s), soit pas - (t mod pas). LEVE si le
    seed est invalide (l'appelant doit l'avoir valide a l'ajout)."""
    cle = _decoder_seed(seed)
    maintenant = int(time.time() if t is None else t)
    compteur = maintenant // pas
    bloc = struct.pack(">Q", compteur)
    digest = hmac.new(cle, bloc, hashlib.sha1).digest()
    # Troncature dynamique (RFC 4226 section 5.3).
    decalage = digest[-1] & 0x0F
    morceau = struct.unpack(">I", digest[decalage:decalage + 4])[0] & 0x7FFFFFFF
    code = str(morceau % (10 ** chiffres)).zfill(chiffres)
    restantes = pas - (maintenant % pas)
    return code, restantes
