"""tests_journal_primes.py — le salon 📈・évolution-des-primes (journal_primes).

Discord, MyPuls et les registres des serveurs sont simulés ; l'état vit dans
un dossier temporaire : rien n'est écrit dans data/, rien ne part sur Discord.

    python tests_journal_primes.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import journal_primes as jp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="journal_primes_"))
jp.FICHIER = TMP / "journal_primes.json"
OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  ok  " if cond else "  KO  ") + nom + ("" if cond else f"  — {detail}"))


# ── les doublures ────────────────────────────────────────────────────────────
BOT = "1552153790701117480"
sys.modules["verif_discord"] = types.SimpleNamespace(
    bot_du_serveur=lambda gid=None: {"app_id": BOT}, api=None, sur_serveur=None)

CATEGORIE = {"id": jp.CATEGORIE, "type": 4, "name": "🔒 ꜱᴛᴀꜰꜰ", "permission_overwrites": [
    {"id": "1552159041084727339", "type": 0, "allow": "1049600", "deny": "0"},
    {"id": "1552167021037490306", "type": 0, "allow": "0", "deny": "1024"},
    {"id": jp.MANAGER, "type": 0, "allow": "68608", "deny": "0"},
    {"id": jp.GID, "type": 0, "allow": "0", "deny": "1024"}]}


class Discord:
    def __init__(self):
        self.salons = [CATEGORIE]
        self.messages = []
        self.creations = []
        self.refuser = False
        self.n = 1000

    def __call__(self, methode, chemin, **kw):
        if methode == "GET" and chemin.startswith("/channels/"):
            sid = chemin.split("/")[2]
            return (200, {"id": sid}) if any(c["id"] == sid for c in self.salons) else (404, {})
        if methode == "GET" and chemin == f"/guilds/{jp.GID}/channels":
            return 200, list(self.salons)
        if methode == "POST" and chemin == f"/guilds/{jp.GID}/channels":
            self.n += 1
            c = dict(kw["json"], id=str(self.n))
            self.salons.append(c)
            self.creations.append(c)
            return 201, c
        if methode == "GET" and chemin.startswith("/users/"):
            uid = chemin.split("/")[2]
            return 200, {"id": uid, "username": "pseudo_" + uid}
        if methode == "POST" and chemin.endswith("/messages"):
            if self.refuser:
                return 429, {}
            self.n += 1
            self.messages.append(kw["json"]["content"])
            return 200, {"id": str(self.n)}
        return 404, {}


REG = {"entretien": {"arrivees": {}, "declarations": {}},
       "agency": {"filleuls": {}}, "twitter": {"filleuls": {}}, "threads": {"filleuls": {}}}
SUBS = {}
jp.registre = lambda p: REG[p]
jp.compteurs = lambda: {}
jp.subs = lambda p, uid, m: SUBS.get((p, uid))


def iso(t):
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def redemarrer(discord):
    """Le processus redémarre : la mémoire repart à zéro, le fichier reste."""
    jp._DIT.clear()
    jp._SALON_VU.clear()
    jp._api = discord


try:
    print("journal_primes")
    check("montants : +0,20 $, +0,50 $, +10 $",
          (jp.montant(20), jp.montant(50), jp.montant(1000)) == ("+0,20 $", "+0,50 $", "+10 $"))

    D = Discord()
    jp._api = D
    avant = time.time() - 86400
    # ce qui est déjà là à la mise en route
    REG["entretien"]["arrivees"]["k1"] = {"uid": "100", "parrain": "200", "joined_at": iso(avant)}
    REG["entretien"]["declarations"]["100"] = {"parrain": "200", "centimes": 20, "date": iso(avant)}
    REG["agency"]["filleuls"]["101"] = {"parrain": "201", "joined_at": iso(avant)}
    REG["twitter"]["filleuls"]["102"] = {"parrain": None, "joined_at": iso(avant)}
    SUBS[("agency", "101")] = 15

    b = jp.tour()
    check("premier tour : le salon est créé une fois, dans 🔒 STAFF", len(D.creations) == 1
          and D.creations[0]["parent_id"] == jp.CATEGORIE and D.creations[0]["name"] == jp.NOM_SALON,
          D.creations)
    dr = {o["id"]: o for o in D.creations[0]["permission_overwrites"]}
    check("droits : VA et @everyone sans la vue", dr[jp.GID]["deny"] == "1024"
          and dr["1552167021037490306"]["deny"] == "1024")
    check("droits : managers en lecture seule", dr[jp.MANAGER]["allow"] == str(1024 | 65536)
          and dr[jp.MANAGER]["deny"] == "2048", dr[jp.MANAGER])
    check("droits : le bot peut poster", dr.get(BOT, {}).get("allow") == str(1024 | 2048 | 16384 | 65536)
          and dr[BOT]["type"] == 1, dr.get(BOT))
    check("premier tour : rien d'avant la mise en route n'est posté", D.messages == [], D.messages)
    check("premier tour : les événements passés sont notés comme référence", b["references"] == 3, b)

    b = jp.tour()
    check("deuxième tour : le filleul déjà à 15 subs ne fait pas « +0,50 $ »", D.messages == [], D.messages)
    check("deuxième tour : son palier 10 est noté comme référence",
          "pal:agency:101:10" in jp._etat()["vus"], jp._etat()["vus"].keys())

    # ── les événements neufs ────────────────────────────────────────────────
    REG["agency"]["filleuls"]["103"] = {"parrain": "203", "joined_at": iso(time.time())}
    jp.tour()
    check("arrivée parrainée : un message, avec les deux pseudos",
          D.messages == ["🚪 <@103> `pseudo_103` a rejoint **TRUST INSTAGRAM**, ramené par <@203> `pseudo_203`"],
          D.messages)

    redemarrer(D)
    jp.tour()
    check("redémarrage : rien n'est reposté", len(D.messages) == 1, D.messages)
    check("redémarrage : le salon n'est pas recréé", len(D.creations) == 1)

    REG["entretien"]["arrivees"]["k2"] = {"uid": "104", "parrain": "200", "joined_at": iso(time.time())}
    REG["entretien"]["declarations"]["104"] = {"parrain": "200", "centimes": 20, "date": iso(time.time() + 1)}
    jp.tour()
    check("recrutement : arrivée puis « +0,20 $ » pour le recruteur", D.messages[1:] == [
        "🚪 <@104> `pseudo_104` a rejoint **TRUST Agency**, ramené par <@200> `pseudo_200`",
        "🎙️ <@200> `pseudo_200` **+0,20 $** · <@104> `pseudo_104` s'est vérifié sur **TRUST Agency** (recrutement)"],
          D.messages)

    # un nouveau filleul (arrivé après la mise en route) part de 0
    SUBS[("agency", "103")] = 0
    jp.tour()
    n0 = len(D.messages)
    SUBS[("agency", "103")] = 11
    jp.tour()
    check("palier 10 : « +0,50 $ » pour le parrain", D.messages[n0:] == [
        "🎯 <@203> `pseudo_203` **+0,50 $** · <@103> `pseudo_103` a atteint **10 subs** sur **TRUST INSTAGRAM**"],
          D.messages[n0:])
    jp.tour()
    check("palier 10 : une seule fois", len(D.messages) == n0 + 1)

    SUBS[("agency", "101")] = 205
    jp.tour()
    check("palier 200 de l'ancien filleul : « +10 $ »", D.messages[-1] ==
          "🏆 <@201> `pseudo_201` **+10 $** · <@101> `pseudo_101` a atteint **200 subs** sur **TRUST INSTAGRAM**",
          D.messages[-1])

    # le même filleul sur les trois serveurs : trois primes
    for p in ("twitter", "threads"):
        REG[p]["filleuls"]["103"] = {"parrain": "203", "joined_at": iso(time.time())}
        SUBS[(p, "103")] = 0
    jp.tour()
    n0 = len(D.messages)
    for p in ("twitter", "threads"):
        SUBS[(p, "103")] = 10
    jp.tour()
    check("par plateforme : 10 subs sur Twitter et Threads = deux « +0,50 $ » de plus",
          sorted(m.split("sur ")[-1] for m in D.messages[n0:]) == ["**TRUST THREADS**", "**TRUST TWITTER**"]
          and all("+0,50 $" in m for m in D.messages[n0:]), D.messages[n0:])

    # recrutement : une déclaration par invité, jamais deux primes
    jp.tour()
    check("recrutement : une seule prime par personne",
          sum("<@104> `pseudo_104` s'est vérifié" in m for m in D.messages) == 1)

    # ── Discord refuse : rien n'est perdu ────────────────────────────────────
    REG["threads"]["filleuls"]["105"] = {"parrain": "205", "joined_at": iso(time.time())}
    D.refuser = True
    n0 = len(D.messages)
    jp.tour()
    D.refuser = False
    jp.tour()
    check("message refusé : reposté au tour suivant, une fois", len(D.messages) == n0 + 1
          and "<@105>" in D.messages[-1], D.messages[n0:])

    # ── au plus MAX_PAR_TOUR messages, le reste au tour suivant ──────────────
    n0 = len(D.messages)
    for i in range(jp.MAX_PAR_TOUR + 2):
        REG["twitter"]["filleuls"][str(300 + i)] = {"parrain": "200", "joined_at": iso(time.time() + i)}
    b = jp.tour()
    check("afflux : MAX_PAR_TOUR messages, le reste en attente",
          len(D.messages) == n0 + jp.MAX_PAR_TOUR and b["en_attente"] == 2, b)
    jp.tour()
    check("afflux : le reste part au tour suivant", len(D.messages) == n0 + jp.MAX_PAR_TOUR + 2)

    # ── un registre refait d'un coup : noté, pas posté ───────────────────────
    n0 = len(D.messages)
    for i in range(jp.SEUIL_MASSE + 5):
        REG["threads"]["filleuls"][str(500 + i)] = {"parrain": "200", "joined_at": iso(time.time())}
    jp.tour()
    jp.tour()
    check("registre refait : aucun message en masse", len(D.messages) == n0, D.messages[n0:])

    # ── une source illisible au départ : ses anciens ne partent pas ensuite ──
    import json
    for f in TMP.iterdir():          # le fichier ET sa copie .prev
        f.unlink()
    redemarrer(D)
    sauve = jp.registre
    jp.registre = lambda p: None if p == "twitter" else REG[p]
    n0 = len(D.messages)
    jp.tour()
    jp.registre = sauve
    jp.tour()
    jp.tour()
    check("état perdu : le salon est retrouvé par son nom, pas recréé", len(D.creations) == 1)
    check("état perdu, source revenue plus tard : rien de reposté", len(D.messages) == n0, D.messages[n0:])
    check("état écrit en JSON lisible", isinstance(json.loads(jp.FICHIER.read_text()), dict))

    # ── arrivée relevée tard (parrain confirmé à la main) : sa date ──────────
    REG["agency"]["filleuls"]["106"] = {"parrain": "201", "joined_at": "2026-11-05T10:00:00+00:00"}
    jp.tour()
    check("arrivée relevée tard : « arrivé le 05/11 »", D.messages[-1].endswith("· arrivé le 05/11"),
          D.messages[-1])

    # ── le branchement dans le site ──────────────────────────────────────────
    src = (ICI / "web_upload.py").read_text(encoding="utf-8")
    check("web_upload : le fil démarre sur la machine de production seulement",
          '_machine_proprietaire("journal-primes")' in src and "_jp_boot.demarrer()" in src)
    check("web_upload : le fil est surveillé (_FILS_DISCORD)",
          '"journal_primes": ("journal-primes"' in src)
    check("journal_primes : écritures par safe_json seulement",
          "write_text" not in (ICI / "journal_primes.py").read_text(encoding="utf-8"))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{len(OK)} ok, {len(KO)} échec(s)")
sys.exit(1 if KO else 0)
