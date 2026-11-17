"""Le QR de l'adresse USDC (qr_code.py) : un carré qu'un téléphone lit.

Propriétaire, 17/11/2026 : « juste un QR code [...] que je puisse le scanner
directement ». Un QR faux ne se voit pas à l'œil, et celui-ci sert à PAYER :
un module de travers, c'est un paiement qui ne part pas -- ou, pire, un QR
qui dirait une autre adresse.

Ce que ce fichier prouve, sans réseau, sans dépendance, sans rien écrire :
  1. Relecture : chaque QR est relu ICI par un décodeur écrit à part (format,
     masque, parcours, désentrelacement, syndromes de Reed-Solomon par tables
     de logarithmes, alors que l'encodeur divise bit à bit) et redonne le
     texte exact : 200 adresses Solana et Ethereum tirées au sort, et chaque
     longueur de 1 à 106 octets.
  2. Les trois matrices relues le 17/11/2026 par OpenCV (QRCodeDetector, un
     décodeur que nous n'avons pas écrit) sont figées par leur empreinte.
  3. La forme : taille par longueur, mires, module noir, bits de format
     valides et en double, niveau M ; au-delà de 106 octets : ValueError.
  4. Le SVG : fond blanc, marge de 4 modules, que des tracés simples, gardé
     en mémoire.

Lancer depuis la racine du dépôt : python tests_qr_code.py
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import random
import re
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import qr_code                  # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


# ─── un décodeur écrit à part ────────────────────────────────────────────
EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i], LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf(a, b):
    return 0 if not a or not b else EXP[LOG[a] + LOG[b]]


MASQUES = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
           lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
           lambda x, y: (x * y) % 2 + (x * y) % 3 == 0, lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
           lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0]
#: version -> (blocs, octets de données par bloc, octets de correction par bloc), niveau M : la table de la norme,
#: recopiée ici et non lue dans qr_code
NORME_M = {1: (1, 16, 10), 2: (1, 28, 16), 3: (1, 44, 26), 4: (2, 32, 18), 5: (2, 43, 24), 6: (4, 27, 16)}


def format_lu(m):
    """(niveau, masque) lus autour de la mire en haut à gauche, None si le code BCH ne tombe pas juste."""
    bits = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
    v = sum(1 << i for i, b in enumerate(bits) if b) ^ 0x5412
    r = v
    for i in range(14, 9, -1):
        if (r >> i) & 1:
            r ^= 0x537 << (i - 10)
    return None if r else (v >> 13, (v >> 10) & 7)


def format_bis(m):
    n = len(m)
    bits = [m[8][n - 1 - i] for i in range(8)] + [m[n - 15 + i][8] for i in range(8, 15)]
    return sum(1 << i for i, b in enumerate(bits) if b)


def reserve(n, version):
    """Les modules qui ne portent pas de données, recalculés ici."""
    f = [[False] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            if x == 6 or y == 6 or (x < 9 and y < 9) or (x >= n - 8 and y < 9) or (x < 9 and y >= n - 8):
                f[y][x] = True
    if version >= 2:
        c = n - 7
        for y in range(c - 2, c + 3):
            for x in range(c - 2, c + 3):
                f[y][x] = True
    return f


def lire(m):
    """Le texte d'un QR (mode octet, niveau M, versions 1 à 6). Lève AssertionError si quelque chose cloche."""
    n = len(m)
    version = (n - 17) // 4
    fmt = format_lu(m)
    assert fmt is not None, "format illisible"
    niveau, masque = fmt
    assert niveau == 0, f"niveau {niveau}, pas M"
    nb, par_bloc, ec = NORME_M[version]
    f = reserve(n, version)
    bits = []
    x = n - 1
    monte = True
    while x > 0:
        if x == 6:
            x -= 1
        for y in (range(n - 1, -1, -1) if monte else range(n)):
            for xx in (x, x - 1):
                if not f[y][xx]:
                    bits.append(m[y][xx] != MASQUES[masque](xx, y))
        monte = not monte
        x -= 2
    total = nb * (par_bloc + ec)
    assert len(bits) >= total * 8, "pas assez de modules"
    mots = [sum(b << (7 - j) for j, b in enumerate(bits[i * 8:i * 8 + 8])) for i in range(total)]
    donnees = [mots[i:nb * par_bloc:nb] for i in range(nb)]
    corr = [mots[nb * par_bloc + i::nb] for i in range(nb)]
    for d, c in zip(donnees, corr):
        for j in range(ec):
            s = 0
            for o in d + c:
                s = gf(s, EXP[j]) ^ o
            assert s == 0, f"syndrome {j} non nul"
    flux = "".join(f"{o:08b}" for d in donnees for o in d)
    assert flux[:4] == "0100", "pas le mode octet"
    longueur = int(flux[4:12], 2)
    return bytes(int(flux[12 + 8 * i:20 + 8 * i], 2) for i in range(longueur)).decode("utf-8")


def empreinte(m):
    return hashlib.sha256("\n".join("".join("1" if c else "0" for c in ligne) for ligne in m).encode()).hexdigest()


SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
ETH = "0x52908400098527886E0F7030069857D2E4169EE7"

print("1. Relecture par un décodeur écrit à part")
check("l'adresse Solana d'exemple", lire(qr_code.matrice(SOL)) == SOL)
check("l'adresse Ethereum d'exemple", lire(qr_code.matrice(ETH)) == ETH)
random.seed(20261117)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
adresses = (["".join(random.choice(B58) for _ in range(random.choice((32, 43, 44)))) for _ in range(120)]
            + ["0x" + "".join(random.choice("0123456789abcdefABCDEF") for _ in range(40)) for _ in range(80)])
rates = []
for a in adresses:
    try:
        if lire(qr_code.matrice(a)) != a:
            rates.append(a)
    except Exception as e:                                   # noqa: BLE001
        rates.append(f"{a} : {e}")
check("200 adresses tirées au sort (Solana 32, 43, 44 caractères ; Ethereum) : toutes relues à l'identique",
      not rates, rates[:3])
rates = []
for n in range(1, qr_code.OCTETS_MAX + 1):
    t = "".join(random.choice(B58) for _ in range(n))
    try:
        if lire(qr_code.matrice(t)) != t:
            rates.append(n)
    except Exception as e:                                   # noqa: BLE001
        rates.append(f"{n} : {e}")
check("chaque longueur de 1 à 106 octets (toutes les versions, les capacités pile pleines)", not rates, rates[:5])
check("un texte accentué (UTF-8)", lire(qr_code.matrice("réseau · à payer")) == "réseau · à payer")
abime = [ligne[:] for ligne in qr_code.matrice(SOL)]
abime[20][20] = not abime[20][20]
try:
    lire(abime)
    vu = False
except AssertionError:
    vu = True
check("le décodeur n'est pas complaisant : un module retourné est vu (syndrome)", vu)

print("2. Les matrices relues par OpenCV le 17/11/2026")
FIGEES = {SOL: (33, "5431b242bde49ff377aba9db82b4f562316a1451b6becdcf5ba06df68b9f5541"),
          ETH: (29, "863fa638f69dc7a8fc2b6c93703be15c4da3ef19433fef26c32b5c6f1651f6fb"),
          "HELLO WORLD": (21, "2d21897bf5a7ac606d02da07bdd5e7f02a8b90097f12404b1f7d764f18ef618c")}
for t, (n, h) in FIGEES.items():
    m = qr_code.matrice(t)
    check(f"« {t[:12]}… » : {n} modules, la matrice relue ce jour-là", len(m) == n and empreinte(m) == h,
          (len(m), empreinte(m)))

print("3. La forme")
tailles = {n: len(qr_code.matrice("a" * n)) for n in (1, 14, 15, 26, 27, 42, 43, 62, 63, 84, 85, 106)}
check("la taille suit la longueur (capacités du niveau M : 14, 26, 42, 62, 84, 106 octets)",
      tailles == {1: 21, 14: 21, 15: 25, 26: 25, 27: 29, 42: 29, 43: 33, 62: 33, 63: 37, 84: 37, 85: 41, 106: 41},
      tailles)
check("la table des blocs est celle de la norme",
      {v: (b, d, e) for v, (e, b, d) in qr_code._BLOCS_M.items()} == NORME_M)
try:
    qr_code.matrice("a" * 107)
    refuse = False
except ValueError:
    refuse = True
check("107 octets : ValueError, pas un QR tronqué", refuse)
m = qr_code.matrice(SOL)
n = len(m)
MIRE = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]


def mire(x0, y0):
    return ["".join("1" if m[y0 + j][x0 + i] else "0" for i in range(7)) for j in range(7)] == MIRE


check("carrée, trois mires aux coins, pas la quatrième",
      all(len(ligne) == n for ligne in m) and mire(0, 0) and mire(n - 7, 0) and mire(0, n - 7)
      and not mire(n - 7, n - 7))
check("les mires sont entourées de blanc", not any(m[7][i] or m[i][7] or m[7][n - 1 - i] or m[n - 8][i]
                                                   or m[i][n - 8] or m[n - 1 - i][7] for i in range(8)))
check("lignes de synchro alternées", all(m[6][i] == (i % 2 == 0) and m[i][6] == (i % 2 == 0) for i in range(8, n - 8)))
check("le module toujours noir", m[n - 8][8] is True)
fmt = format_lu(m)
bits1 = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
check("bits de format : code BCH juste, niveau M, écrits deux fois à l'identique",
      fmt is not None and fmt[0] == 0 and format_bis(m) == sum(1 << i for i, b in enumerate(bits1) if b), fmt)
check("même texte, même QR", qr_code.matrice(SOL) == m)
check("un caractère de différence : un autre QR", qr_code.matrice(SOL[:-1] + "V") != m)

print("4. Le SVG")
s = qr_code.svg(SOL)
check("viewBox : 33 modules + 4 de marge de chaque côté", f'viewBox="0 0 {n + 8} {n + 8}"' in s)
check("fond BLANC d'abord (sur la page sombre, un QR sans fond ne se lit pas), modules noirs dessus",
      s.index('fill="#fff" d="M0 0h41v41H0z"') < s.index('fill="#000"'))
chemin = re.search(r'fill="#000" d="([^"]*)"', s).group(1)
check("que des tracés simples (M h v z, chiffres) : rien qui s'exécute, rien à échapper",
      re.fullmatch(r"(M\d+ \d+h\d+v1h-\d+z)+", chemin) is not None and "<script" not in s and "&" not in s)
dessin = [[False] * n for _ in range(n)]
for x0, y0, w in re.findall(r"M(\d+) (\d+)h(\d+)v1", chemin):
    for i in range(int(w)):
        dessin[int(y0) - 4][int(x0) - 4 + i] = True
check("le dessin est la matrice, module pour module (et se relit)", dessin == m and lire(dessin) == SOL)
check("gardé en mémoire : la page de la direction en dessine ~80 par affichage", qr_code.svg(SOL) is s)
check("aucun astérisque ni apostrophe (le SVG part dans du HTML bâti en Python)", "*" not in s and "'" not in s)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
