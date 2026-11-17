"""Un QR code, sans dépendance : l'adresse USDC d'un VA en carré à scanner.

Propriétaire, 17/11/2026, pour la colonne « Adresse USDC » des pages de stats :
« j'aimerais juste avoir un QR code [...] que je puisse le scanner directement,
et quand je clique, je vois ça au centre, en plus gros ».

Ni `qrcode` ni `segno` ne sont installés sur le VPS, et le déploiement ne lance
pas pip : une dépendance de plus aurait cassé l'import au premier push. D'où
cet encodeur, réduit à ce qu'il faut : mode octet, niveau de correction M,
versions 1 à 6 (106 octets au plus ; une adresse Solana en fait 44, une
adresse Ethereum 42). Le QR dit l'adresse SEULE, sans « solana: » devant :
c'est ce que lisent tous les portefeuilles et les retraits des plateformes.

Le QR est fabriqué depuis l'adresse enregistrée, jamais depuis l'image que le
VA a pu envoyer dans Discord (data/usdc_qr/) : celle-là est une capture de son
application, que rien ne relie à l'adresse qu'on paie.

Vérifié le 17/11/2026 avec un décodeur indépendant (OpenCV QRCodeDetector) ;
tests_qr_code.py fige les matrices relues ce jour-là.
"""
from __future__ import annotations

import functools
from typing import List, Tuple

#: version -> (octets de correction par bloc, blocs, octets de données par bloc), niveau M
_BLOCS_M = {1: (10, 1, 16), 2: (16, 1, 28), 3: (26, 1, 44), 4: (18, 2, 32), 5: (24, 2, 43), 6: (16, 4, 27)}
#: version -> centres des mires d'alignement
_ALIGNEMENT = {1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30), 6: (6, 34)}
OCTETS_MAX = _BLOCS_M[6][1] * _BLOCS_M[6][2] - 2


# ─── Reed-Solomon sur GF(256), polynôme 0x11D ────────────────────────────
def _fois(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _diviseur(degre: int) -> List[int]:
    r = [0] * (degre - 1) + [1]
    racine = 1
    for _ in range(degre):
        for j in range(degre):
            r[j] = _fois(r[j], racine)
            if j + 1 < degre:
                r[j] ^= r[j + 1]
        racine = _fois(racine, 2)
    return r


def _reste(donnees: List[int], diviseur: List[int]) -> List[int]:
    r = [0] * len(diviseur)
    for o in donnees:
        facteur = o ^ r.pop(0)
        r.append(0)
        for i, c in enumerate(diviseur):
            r[i] ^= _fois(c, facteur)
    return r


# ─── les octets à poser ──────────────────────────────────────────────────
def _version(n_octets: int) -> int:
    for v in sorted(_BLOCS_M):
        if n_octets <= _BLOCS_M[v][1] * _BLOCS_M[v][2] - 2:
            return v
    raise ValueError(f"texte trop long pour ce QR ({n_octets} octets, {OCTETS_MAX} au plus)")


def _mots(donnees: bytes, version: int) -> List[int]:
    """Données (mode octet) puis correction, blocs entrelacés."""
    ec, nb, par_bloc = _BLOCS_M[version]
    capacite = nb * par_bloc
    bits: List[int] = []

    def pousse(v: int, n: int) -> None:
        bits.extend((v >> i) & 1 for i in range(n - 1, -1, -1))

    pousse(0b0100, 4)                       # mode octet
    pousse(len(donnees), 8)                 # longueur sur 8 bits (versions 1 à 9)
    for o in donnees:
        pousse(o, 8)
    pousse(0, min(4, capacite * 8 - len(bits)))
    pousse(0, -len(bits) % 8)
    mots = [sum(b << (7 - j) for j, b in enumerate(bits[i:i + 8])) for i in range(0, len(bits), 8)]
    remplissage = 0xEC                      # les octets de bourrage de la norme, en alternance
    while len(mots) < capacite:
        mots.append(remplissage)
        remplissage ^= 0xEC ^ 0x11
    blocs = [mots[i * par_bloc:(i + 1) * par_bloc] for i in range(nb)]
    diviseur = _diviseur(ec)
    corr = [_reste(b, diviseur) for b in blocs]
    return ([b[i] for i in range(par_bloc) for b in blocs]
            + [c[i] for i in range(ec) for c in corr])


# ─── la matrice ──────────────────────────────────────────────────────────
_MASQUES = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _bits_format(masque: int) -> int:
    """Les 15 bits de format : niveau M (00), masque, BCH(15,5), XOR 0x5412."""
    donnees = masque                        # niveau M = 00 devant le masque
    reste = donnees
    for _ in range(10):
        reste = (reste << 1) ^ ((reste >> 9) * 0x537)
    return ((donnees << 10) | reste) ^ 0x5412


def _poser_format(m: List[List[bool]], masque: int) -> None:
    n = len(m)
    bits = _bits_format(masque)

    def bit(i: int) -> bool:
        return (bits >> i) & 1 == 1

    for i in range(6):
        m[i][8] = bit(i)
    m[7][8], m[8][8], m[8][7] = bit(6), bit(7), bit(8)
    for i in range(9, 15):
        m[8][14 - i] = bit(i)
    for i in range(8):
        m[8][n - 1 - i] = bit(i)
    for i in range(8, 15):
        m[n - 15 + i][8] = bit(i)
    m[n - 8][8] = True                      # le module toujours noir


def _penalite(m: List[List[bool]]) -> int:
    """Les quatre règles de la norme : le masque retenu est celui qui se lit
    le mieux (pas de grandes plages unies, pas de fausse mire)."""
    n = len(m)
    p = 0
    for bande in m + [[m[y][x] for y in range(n)] for x in range(n)]:
        suite = 1
        for i in range(1, n):
            if bande[i] == bande[i - 1]:
                suite += 1
                p += 3 if suite == 5 else (1 if suite > 5 else 0)
            else:
                suite = 1
        s = "".join("1" if c else "0" for c in bande)
        p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                p += 3
    noirs = sum(sum(1 for c in ligne if c) for ligne in m)
    total = n * n
    p += ((abs(noirs * 20 - total * 10) + total - 1) // total - 1) * 10
    return p


def _base(version: int) -> Tuple[List[List[bool]], List[List[bool]]]:
    """(modules, réservés) : mires, lignes de synchro, place du format."""
    n = 17 + 4 * version
    m = [[False] * n for _ in range(n)]
    f = [[False] * n for _ in range(n)]

    def pose(x: int, y: int, noir: bool) -> None:
        m[y][x], f[y][x] = noir, True

    for i in range(n):
        pose(6, i, i % 2 == 0)
        pose(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < n and 0 <= y < n:
                    pose(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    pos = _ALIGNEMENT[version]
    dernier = len(pos) - 1
    for i, ax in enumerate(pos):
        for j, ay in enumerate(pos):
            if (i, j) in ((0, 0), (0, dernier), (dernier, 0)):
                continue                    # là, il y a déjà une grande mire
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    pose(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
    # la place des bits de format (et du module noir), posés après le masque
    for i in range(9):
        f[i][8] = f[8][i] = True
    for i in range(8):
        f[8][n - 1 - i] = f[n - 1 - i][8] = True
    return m, f


def matrice(texte: str) -> List[List[bool]]:
    """Les modules du QR de `texte` (True = noir), sans marge. Lève ValueError
    au-delà de OCTETS_MAX octets."""
    donnees = str(texte).encode("utf-8")
    version = _version(len(donnees))
    base, reserve = _base(version)
    n = len(base)
    mots = _mots(donnees, version)
    i = 0
    for droite in range(n - 1, 0, -2):
        if droite <= 6:
            droite -= 1                     # la colonne 6 est la ligne de synchro
        for v in range(n):
            for j in range(2):
                x = droite - j
                y = (n - 1 - v) if (droite + 1) & 2 == 0 else v
                if not reserve[y][x] and i < len(mots) * 8:
                    base[y][x] = (mots[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
    meilleur, score = None, None
    for k, masque in enumerate(_MASQUES):
        m = [[c != (masque(x, y) and not reserve[y][x]) for x, c in enumerate(ligne)]
             for y, ligne in enumerate(base)]
        _poser_format(m, k)
        p = _penalite(m)
        if score is None or p < score:
            meilleur, score = m, p
    return meilleur


@functools.lru_cache(maxsize=1024)
def svg(texte: str, marge: int = 4) -> str:
    """Le QR de `texte` en SVG : fond blanc (aussi sur une page sombre, sinon
    il ne se lit pas), marge de 4 modules, net à toute taille. Gardé en
    mémoire : la page de la direction en dessine ~80 et se recharge toutes
    les 8 s pendant une lecture."""
    m = matrice(texte)
    n = len(m)
    t = n + 2 * marge
    d = []
    for y, ligne in enumerate(m):
        x = 0
        while x < n:
            if not ligne[x]:
                x += 1
                continue
            x0 = x
            while x < n and ligne[x]:
                x += 1
            d.append(f"M{x0 + marge} {y + marge}h{x - x0}v1h-{x - x0}z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {t} {t}" shape-rendering="crispEdges" '
            f'role="img" aria-label="QR code"><path fill="#fff" d="M0 0h{t}v{t}H0z"/>'
            f'<path fill="#000" d="{"".join(d)}"/></svg>')
