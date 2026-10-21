"""Le VA parti de Va IG : salon gardé, fiche marquée « parti », lien coupé.

Propriétaire, 21/10/2026 : « Oui, garder le salon ». Avant, on_member_remove
planifiait la suppression du salon 7 jours après le départ, et
check_pending_deletions effaçait le salon ET la fiche (3usg, prévu le 21/10 à
20:12). Désormais, sur Va IG, la fiche est marquée comme les tickets Twitter /
Threads (tickets_discord.marquer_parti), le salon reste, un message le dit, et
l'entrée de pending_deletions.json reste sans date (« garder ») :
liens_fr.couper_partis y lit les partis pour couper leur lien.

Lancer depuis la racine du dépôt : python tests_depart_va_ig.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402

import cogs.welcome as w                # noqa: E402
import liens_fr                         # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


IG = 1505418484052394004
AUTRE = 1445108485090971710

TMP = pathlib.Path(tempfile.mkdtemp(prefix="depart_va_ig_"))
w.PENDING_DELETIONS_FILE = TMP / "pending_deletions.json"
w.USERS_FILE = TMP / "users.json"
liens_fr.PARTIS = w.PENDING_DELETIONS_FILE


class Rep:
    def __init__(self, status):
        self.status, self.reason = status, "x"


def introuvable(code):
    return discord.NotFound(Rep(404), {"code": code, "message": "Unknown"})


class Salon:
    def __init__(self, cid, nom):
        self.id, self.name = cid, nom
        self.envois, self.supprime = [], False

    async def send(self, texte=None, **kw):
        self.envois.append((texte, kw))

    async def delete(self, reason=None):
        self.supprime = True


class Guilde:
    def __init__(self, gid, salons, membres=(), fetch=None):
        self.id, self.name = gid, f"serveur {gid}"
        self._salons = {s.id: s for s in salons}
        self._membres = {m.id: m for m in membres}
        self._fetch = fetch or {}

    def get_channel(self, cid):
        return self._salons.get(int(cid))

    def get_member(self, uid):
        return self._membres.get(int(uid))

    async def fetch_member(self, uid):
        r = self._fetch.get(int(uid))
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise introuvable(10007)
        return r


def run(coro):
    return asyncio.run(coro)


def membre(uid, nom, guilde):
    return types.SimpleNamespace(id=uid, name=nom, bot=False, guild=guilde)


# 1. départ vu par on_member_remove sur Va IG : rien de supprimé, fiche marquée
t3usg = Salon(1555791095101923410, "🔴-1-va-3usg")
g = Guilde(IG, [t3usg])
w.save_users({"881568604557037628": {"identity": "lola", "channel_id": t3usg.id}})
w.save_pending({})
cog = w.Welcome.__new__(w.Welcome)
run(w.Welcome.on_member_remove(cog, membre(881568604557037628, "3usg", g)))
p = w.load_pending()["881568604557037628"]
check("Va IG : départ noté sans date de suppression", p.get("garder") is True
      and "delete_at" not in p and p.get("user_name") == "3usg" and p.get("guild_id") == IG, p)
fiche = w.load_users()["881568604557037628"]
check("la fiche est marquée « parti » (même forme que tickets_discord)",
      isinstance(fiche.get("parti"), dict) and fiche["parti"].get("quand"), fiche)
texte, kw = t3usg.envois[0] if t3usg.envois else ("", {})
check("le ticket est prévenu, sans mention", "a quitté le serveur" in (texte or "")
      and "reste tel quel" in texte and kw.get("allowed_mentions") is not None
      and not kw["allowed_mentions"].users, t3usg.envois)
check("partis_fr le liste", list(w.partis_fr()) == ["881568604557037628"], w.partis_fr())

# 2. l'heure suivante : le salon n'est pas supprimé, la fiche reste
expire = Salon(42, "va-ancien")
gu = Guilde(AUTRE, [expire])
pend = w.load_pending()
pend["7"] = {"channel_id": 42, "guild_id": AUTRE, "delete_at": "2020-01-01T00:00:00+00:00",
             "user_name": "ancien"}
w.save_pending(pend)
users = w.load_users()
users["7"] = {"identity": "x", "channel_id": 42}
w.save_users(users)
cog.bot = types.SimpleNamespace(guilds=[], get_guild=lambda i: {IG: g, AUTRE: gu}.get(i))
run(w.Welcome.check_pending_deletions.coro(cog))
check("Va IG : ni salon ni fiche supprimés", not t3usg.supprime
      and "881568604557037628" in w.load_users() and "881568604557037628" in w.load_pending())
check("ailleurs, la règle des 7 jours reste", expire.supprime and "7" not in w.load_users()
      and "7" not in w.load_pending())

# 3. liens_fr.couper_partis lit toujours les partis de Va IG
vus = []
_aligner = liens_fr.aligner
liens_fr.aligner = lambda membres, force=False: vus.extend(membres) or []
try:
    liens_fr.couper_partis()
finally:
    liens_fr.aligner = _aligner
check("couper_partis voit le parti (uid, pseudo, aucun model)",
      vus == [("881568604557037628", "3usg", [])], vus)

# 4. un 2e départ constaté ne double rien
n = len(t3usg.envois)
r = run(w.marquer_parti_fr(g, "881568604557037628", "3usg", t3usg.id))
check("déjà marqué : rien de plus", r is False and len(t3usg.envois) == n)

# 5. retour : la marque tombe, message, plus dans pending
run(w.marquer_revenu_fr(g, membre(881568604557037628, "3usg", g)))
fiche = w.load_users()["881568604557037628"]
check("revenu : fiche sans « parti », entrée retirée",
      "parti" not in fiche and fiche.get("revenu") and "881568604557037628" not in w.load_pending(),
      fiche)
check("revenu : le ticket est prévenu", "de retour" in (t3usg.envois[-1][0] or ""), t3usg.envois[-1])

# 6. rattrapage : parti pendant un arrêt (ou entrée retirée à la main)
present = membre(1, "present", None)
tp, ta, tq = Salon(101, "t-present"), Salon(102, "t-absent"), Salon(103, "t-doute")
g6 = Guilde(IG, [tp, ta, tq, t3usg], membres=[present],
            fetch={3: introuvable(10004)})
w.save_pending({})
w.save_users({"1": {"identity": "lola", "channel_id": 101},
              "2": {"identity": "lola", "channel_id": 102, "discord_username": "absent"},
              "3": {"identity": "lola", "channel_id": 103},
              "4": {"identity": "lola", "channel_id": 999}})
marques = run(w.suivre_departs_fr(None, g6))
check("seul le membre confirmé absent (10007) est marqué", marques == ["2"], marques)
check("son pseudo est gardé pour couper son lien",
      w.load_pending()["2"]["user_name"] == "absent", w.load_pending())
check("2e passage : rien de plus", run(w.suivre_departs_fr(None, g6)) == [])

# 7. /pendingdeletions le dit
lignes = []


class Reponse:
    async def send_message(self, texte, **k):
        lignes.append(texte)


async def _admin(self, inter):
    return True
w.Welcome.require_admin = _admin
run(w.Welcome.pendingdeletions.callback(cog, types.SimpleNamespace(response=Reponse())))
check("/pendingdeletions : « salon gardé »", lignes and "salon gardé" in lignes[0], lignes)

print(f"\n{len(OKS)} OK, {len(FAILS)} échec(s)")
sys.exit(1 if FAILS else 0)
