"""tests_journal_primes.py — le salon 🤝・qui-t-a-invité (journal_primes).

Discord, MyPuls et les registres des serveurs sont simulés ; l'état vit dans
un dossier temporaire : rien n'est écrit dans data/, rien ne part sur Discord.

    python tests_journal_primes.py
"""
from __future__ import annotations

import json
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

MODELE = {"id": jp.SALON_MODELE, "type": 0, "name": "🤝・parrainage", "parent_id": jp.CATEGORIE,
          "permission_overwrites": [
              {"id": "1552159041084727339", "type": 0, "allow": "117760", "deny": "0"},
              {"id": jp.GID, "type": 0, "allow": "0", "deny": "377957124096"}]}
ANCIEN = {"id": "777", "type": 0, "name": "📈・évolution-des-primes", "parent_id": "1552167027504971826",
          "topic": "ancien", "permission_overwrites": [{"id": jp.GID, "type": 0, "allow": "0", "deny": "1024"}]}


class Discord:
    def __init__(self, salons):
        self.salons = [dict(c) for c in salons]
        self.messages = []
        self.creations = []
        self.patchs = []
        self.refuser = False
        self.n = 1000

    def __call__(self, methode, chemin, **kw):
        if methode == "GET" and chemin == f"/guilds/{jp.GID}/channels":
            return 200, [dict(c) for c in self.salons]
        if methode == "POST" and chemin == f"/guilds/{jp.GID}/channels":
            self.n += 1
            c = dict(kw["json"], id=str(self.n))
            self.salons.append(c)
            self.creations.append(c)
            return 201, c
        if methode == "PATCH" and chemin.startswith("/channels/"):
            sid = chemin.split("/")[2]
            c = next(c for c in self.salons if c["id"] == sid)
            c.update(kw["json"])
            self.patchs.append(sid)
            return 200, c
        if methode == "GET" and chemin.startswith("/users/"):
            uid = chemin.split("/")[2]
            return 200, {"id": uid, "username": "u" + uid, "global_name": "Nom " + uid}
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


def nouveaux(D, n0):
    return D.messages[n0:]


try:
    print("journal_primes")
    check("montants : +0,20 $, +0,50 $, +10 $ ; total 0,90 $",
          (jp.montant(20), jp.montant(50), jp.montant(1000), jp.dollars(90))
          == ("+0,20 $", "+0,50 $", "+10 $", "0,90 $"))

    # ── l'ancien salon staff est repris, renommé, ouvert à tous ──────────────
    D = Discord([MODELE, ANCIEN])
    jp._api = D
    jp._ecrire({"salon": "777"})
    avant = time.time() - 86400
    REG["entretien"]["arrivees"]["k1"] = {"uid": "100", "parrain": "200", "joined_at": iso(avant)}
    REG["entretien"]["declarations"]["100"] = {"parrain": "200", "centimes": 20, "date": iso(avant),
                                               "semaine": jp.semaine(avant)}
    REG["agency"]["filleuls"]["101"] = {"parrain": "201", "joined_at": iso(avant)}
    REG["twitter"]["filleuls"]["102"] = {"parrain": None, "joined_at": iso(avant)}
    SUBS[("agency", "101")] = 15

    b = jp.tour()
    s = next(c for c in D.salons if c["id"] == "777")
    check("ancien salon repris : pas de second salon", D.creations == [] and D.patchs == ["777"],
          (D.creations, D.patchs))
    check("ancien salon : renommé 🤝・qui-t-a-invité, dans 🤝 AFFILIATION",
          s["name"] == "🤝・qui-t-a-invité" and s["parent_id"] == jp.CATEGORIE, s)
    dr = {o["id"]: o for o in s["permission_overwrites"]}
    check("droits : ceux de 🤝・parrainage (tout le monde lit, personne n'écrit)",
          dr[jp.GID]["deny"] == "377957124096" and not int(dr[jp.GID]["deny"]) & 1024, dr.get(jp.GID))
    check("droits : le bot peut poster", dr.get(BOT, {}).get("allow") == str(1024 | 2048 | 16384 | 65536)
          and dr[BOT]["type"] == 1, dr.get(BOT))
    check("premier tour : rien d'avant la mise en route n'est posté", D.messages == [], D.messages)
    check("premier tour : les événements passés sont notés comme référence", b["references"] == 3, b)

    redemarrer(D)
    jp._SALON_VU.clear()
    jp.tour()
    check("salon déjà conforme : plus aucun changement", D.patchs == ["777"], D.patchs)
    check("deuxième tour : le filleul déjà à 15 subs ne fait pas « +0,50 $ »", D.messages == [], D.messages)
    check("deuxième tour : son palier 10 est noté comme référence", "pal:101:10" in jp._etat()["vus"])

    # ── les événements neufs ────────────────────────────────────────────────
    REG["agency"]["filleuls"]["103"] = {"parrain": "203", "joined_at": iso(time.time())}
    jp.tour()
    check("arrivée parrainée : un message, noms en gras",
          D.messages == ["🚪 **Nom 103** a rejoint **TRUST INSTAGRAM**, invité par **Nom 203**"], D.messages)

    redemarrer(D)
    jp.tour()
    check("redémarrage : rien n'est reposté", len(D.messages) == 1, D.messages)

    n0 = len(D.messages)
    t = time.time()
    REG["entretien"]["arrivees"]["k2"] = {"uid": "104", "parrain": "200", "joined_at": iso(t)}
    REG["entretien"]["declarations"]["104"] = {"parrain": "200", "centimes": 20, "date": iso(t + 1),
                                               "semaine": jp.semaine(t)}
    jp.tour()
    tot = "0,40 $" if jp.semaine(avant) == jp.semaine(t) else "0,20 $"
    check("recrutement : arrivée puis « +0,20 $ pour lui » et le total de sa semaine", nouveaux(D, n0) == [
        "🚪 **Nom 104** a rejoint **TRUST Agency**, invité par **Nom 200**",
        f"**Nom 104** a été invité par **Nom 200** — +0,20 $ pour lui 💸\nTotal pour cette semaine : **{tot}**"],
          nouveaux(D, n0))

    # un nouveau filleul (arrivé après la mise en route) part de 0
    SUBS[("agency", "103")] = 0
    jp.tour()
    n0 = len(D.messages)
    SUBS[("agency", "103")] = 11
    jp.tour()
    check("palier 10 : « +0,50 $ pour lui » et le total du parrain", nouveaux(D, n0) == [
        "**Nom 103**, invité par **Nom 203**, a atteint **10 subs** sur **TRUST INSTAGRAM** — "
        "+0,50 $ pour lui 💸\nTotal pour cette semaine : **0,50 $**"], nouveaux(D, n0))
    jp.tour()
    check("palier 10 : une seule fois", len(D.messages) == n0 + 1)

    # le même filleul sur les deux autres serveurs : toujours UNE prime
    n0 = len(D.messages)
    for p in ("twitter", "threads"):
        REG[p]["filleuls"]["103"] = {"parrain": "203", "joined_at": iso(time.time())}
        SUBS[(p, "103")] = 30
    jp.tour()
    check("une prime par filleul : 10 subs ailleurs ne rapportent rien de plus",
          all(m.startswith("🚪") for m in nouveaux(D, n0)) and len(nouveaux(D, n0)) == 2, nouveaux(D, n0))

    # la plateforme où il a le plus de subs décide (et son parrain)
    n0 = len(D.messages)
    t = time.time()
    REG["twitter"]["filleuls"]["107"] = {"parrain": "210", "joined_at": iso(t)}
    REG["threads"]["filleuls"]["107"] = {"parrain": "211", "joined_at": iso(t)}
    SUBS[("twitter", "107")], SUBS[("threads", "107")] = 3, 0
    jp.tour()
    SUBS[("threads", "107")] = 12
    jp.tour()
    pal = [m for m in nouveaux(D, n0) if "subs**" in m]
    check("meilleure plateforme : Threads (12) l'emporte sur Twitter (3), prime au parrain de Threads",
          len(pal) == 1 and "sur **TRUST THREADS**" in pal[0] and "invité par **Nom 211**" in pal[0], pal)

    # gains de la semaine : recrutements + paliers du même parrain
    n0 = len(D.messages)
    REG["threads"]["filleuls"]["108"] = {"parrain": "200", "joined_at": iso(time.time())}
    SUBS[("threads", "108")] = 0
    jp.tour()
    SUBS[("threads", "108")] = 10
    jp.tour()
    attendu = 20 * sum(1 for r in REG["entretien"]["declarations"].values()
                       if r["parrain"] == "200" and r["semaine"] == jp.semaine(time.time())) + 50
    check("total de la semaine : recrutements et paliers s'additionnent",
          D.messages[-1].endswith(f"Total pour cette semaine : **{jp.dollars(attendu)}**"), D.messages[-1])

    SUBS[("agency", "101")] = 205
    jp.tour()
    check("palier 200 de l'ancien filleul : « +10 $ »", "**200 subs**" in D.messages[-1]
          and "+10 $ pour lui 💸" in D.messages[-1] and "invité par **Nom 201**" in D.messages[-1],
          D.messages[-1])

    # recrutement : une déclaration par invité, jamais deux primes
    check("recrutement : une seule prime par personne",
          sum("**Nom 104** a été invité" in m for m in D.messages) == 1)

    # ── Discord refuse : rien n'est perdu ────────────────────────────────────
    REG["threads"]["filleuls"]["105"] = {"parrain": "205", "joined_at": iso(time.time())}
    D.refuser = True
    n0 = len(D.messages)
    jp.tour()
    D.refuser = False
    jp.tour()
    check("message refusé : reposté au tour suivant, une fois",
          len(D.messages) == n0 + 1 and "Nom 105" in D.messages[-1], nouveaux(D, n0))

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
    check("registre refait : aucun message en masse", len(D.messages) == n0, nouveaux(D, n0))

    # ── un nom à étoiles ne casse pas le gras ────────────────────────────────
    check("nom à caractères Markdown échappé",
          jp._qui("9", {"9": "a*b_c"}) == "**a\\*b\\_c**" and jp._qui("8", {}) == "<@8>")

    # ── état perdu : le salon est retrouvé par son nom, rien de reposté ──────
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
    check("état perdu : le salon est retrouvé par son nom, pas recréé",
          D.creations == [] and jp._etat().get("salon") == "777", (D.creations, jp._etat().get("salon")))
    check("état perdu, source revenue plus tard : rien de reposté", len(D.messages) == n0, nouveaux(D, n0))
    check("état écrit en JSON lisible", isinstance(json.loads(jp.FICHIER.read_text()), dict))

    # ── aucun salon : il est créé, au bon endroit ────────────────────────────
    for f in TMP.iterdir():
        f.unlink()
    D2 = Discord([MODELE])
    redemarrer(D2)
    jp.tour()
    check("aucun salon : créé une fois, dans 🤝 AFFILIATION", len(D2.creations) == 1
          and D2.creations[0]["parent_id"] == jp.CATEGORIE and D2.creations[0]["name"] == jp.NOM_SALON,
          D2.creations)
    jp._SALON_VU.clear()
    jp.tour()
    check("aucun salon : pas recréé au tour suivant", len(D2.creations) == 1 and D2.patchs == [], D2.patchs)

    # ── arrivée relevée tard (parrain confirmé à la main) : sa date ──────────
    REG["agency"]["filleuls"]["106"] = {"parrain": "201", "joined_at": "2026-11-05T10:00:00+00:00"}
    jp.tour()
    check("arrivée relevée tard : « arrivé le 05/11 »", D2.messages[-1].endswith("· arrivé le 05/11"),
          D2.messages[-1:])

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
