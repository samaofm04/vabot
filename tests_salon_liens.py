# -*- coding: utf-8 -*-
"""tests_salon_liens.py — le salon 🔗・liens de You FR.

Propriétaire, 10/11/2026 : « un endroit avec écrit liens, et ça range par
catégorie, et ça @ la personne et [le] lien après » ; un message par model,
les @ notifient.

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. Le texte : en-tête de la model, « <@VA> lien » triés, « — » sans VA,
     coupé avant 2000 signes.
  2. L'attente : rien n'est posté tant qu'un lien JB manque (l'envoi notifie).
  3. Le salon : créé dans 📣 ANNONCES ET SUIVI, quatre messages envoyés en
     texte, @ autorisés (utilisateurs seulement), aperçus retirés.
  4. La suite : rien de renvoyé ; un lien nouveau = message MODIFIÉ (pas de
     nouvelle notification) ; un message supprimé = renvoyé ; data/ perdu =
     messages retrouvés par leur en-tête.
  5. Le cog : le salon suit chaque passage des liens JB, même sans création.

Lancement : python tests_salon_liens.py
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

VRAIS = [BOT / "data" / n for n in ("salon_liens.json", "liens_jb_fr.json")]
AVANT = [f.stat().st_mtime if f.exists() else None for f in VRAIS]

import discord                          # noqa: E402

import guild_features as gf             # noqa: E402
import liens_jb_fr as lj                # noqa: E402
import salon_liens as sl                # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


ns = types.SimpleNamespace
TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_salon_liens_"))
sl.ETAT = TMP / "salon_liens.json"
lj.ETAT = TMP / "liens_jb_fr.json"


def _interdit(*a, **k):
    raise RuntimeError("création de lien JB interdite dans un essai")


lj.creer = _interdit
YOU_FR, YOU_US = int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)
RYUK = 1505416430840189041
import safe_json                        # noqa: E402


def registre(liens):
    safe_json.write(lj.ETAT, {"liens": {f"{u}:{m}": {"public_url": f"https://getmysocial.com/{m}{u}"}
                                        for u, m in liens}})


class Message:
    def __init__(self, canal, mid, content, author=RYUK):
        self.canal, self.id, self.content, self.author = canal, mid, content, ns(id=author)
        self.edits, self.supprime_aperçus = 0, None

    async def edit(self, content=None, suppress=None):
        self.edits += 1
        self.content, self.supprime_aperçus = content, suppress

    async def delete(self):
        self.canal.messages = [m for m in self.canal.messages if m is not self]


class Canal:
    _n = 7000

    def __init__(self, name, category=None):
        Canal._n += 1
        self.id, self.name, self.category = Canal._n, name, category
        self.messages, self.envois = [], []

    async def send(self, content=None, suppress_embeds=False, allowed_mentions=None):
        Canal._n += 1
        m = Message(self, Canal._n, content)
        self.messages.append(m)
        self.envois.append((content, suppress_embeds, allowed_mentions))
        return m

    async def fetch_message(self, mid):
        for m in self.messages:
            if m.id == mid:
                return m
        raise discord.NotFound(ns(status=404, reason="x"), "Unknown Message")

    def history(self, limit=50):
        c = self

        async def gen():
            for m in sorted(c.messages, key=lambda m: -m.id)[:limit]:
                yield m
        return gen()


class Guilde:
    def __init__(self, gid=YOU_FR):
        self.id, self.name = gid, "You FR"
        self.me = ns(id=RYUK)
        self.categories = [ns(id=1, name="📣 ANNONCES ET SUIVI")]
        self.text_channels = []
        self.creations = []
        self.members = [ns(id=2, name="faxx103", bot=False, roles=[ns(name="Amelia")]),
                        ns(id=1, name="york_emerick12", bot=False, roles=[ns(name="Emma")]),
                        ns(id=3, name="noum0075", bot=False, roles=[]),
                        ns(id=RYUK, name="Ryuk.exe", bot=True, roles=[ns(name="Ryuk")])]

    async def create_text_channel(self, name, category=None, overwrites=None, reason=None):
        c = Canal(name, category)
        self.creations.append((name, category))
        self.text_channels.append(c)
        return c


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def reset():
    for f in TMP.iterdir():
        f.unlink()
    sl._VERROUS.clear()
    sl._DITS.clear()


TOUS = [(u, m) for u in (1, 2) for m in ("amelia", "emma", "lola", "alicia")]

# ── 1. Le texte ───────────────────────────────────────────────────────────
print("\n── 1. Le texte")
reset()
registre(TOUS)
g = Guilde()
t = sl.texte_model(g, "amelia")
check("en-tête puis « <@VA> lien », triés par nom (faxx103 avant york)",
      t == "### 🩷 AMELIA\n<@2> https://getmysocial.com/amelia2\n<@1> https://getmysocial.com/amelia1", t)
check("ni bot ni membre sans rôle de model", "<@3>" not in t and f"<@{RYUK}>" not in t)
registre([])
check("aucun lien : « — »", sl.texte_model(g, "lola") == "### 🧡 LOLA\n—")
lj.vas_du_serveur = (lambda vrai: (lambda guild: [(i, f"va{i:03d}") for i in range(200)]
                                   if getattr(guild, "beaucoup", False) else vrai(guild)))(lj.vas_du_serveur)
registre([(i, "emma") for i in range(200)])
gb = Guilde()
gb.beaucoup = True
tb = sl.texte_model(gb, "emma")
check("200 VA : coupé en « … +N » sous 2000 signes", len(tb) <= 2000 and tb.splitlines()[-1].startswith("… +"),
      len(tb))

# ── 2. L'attente ──────────────────────────────────────────────────────────
print("\n── 2. L'attente")
reset()
registre(TOUS[:-1])                      # il manque york/alicia
g = Guilde()
b = run(sl.assurer(g))
check("un lien manque : rien de posté, pas de salon, et c'est dit",
      b["attente"] == 1 and not g.creations and not b["envoyes"], b)

# ── 3. Le salon ───────────────────────────────────────────────────────────
print("\n── 3. Le salon")
registre(TOUS)
b = run(sl.assurer(g))
canal = g.text_channels[0] if g.text_channels else None
check("tous les liens là : salon 🔗・liens créé dans 📣 ANNONCES ET SUIVI",
      g.creations == [("🔗・liens", g.categories[0])], g.creations)
check("quatre messages, un par model, dans l'ordre",
      canal and [m.content.split("\n")[0] for m in canal.messages]
      == ["### 🩷 AMELIA", "### 💜 EMMA", "### 🧡 LOLA", "### 💛 ALICIA"], b)
envoi = canal.envois[0] if canal and canal.envois else (None, None, None)
am = envoi[2]
check("envoyés en texte, aperçus retirés, @ des utilisateurs seuls (pas de rôle, pas de @everyone)",
      envoi[1] is True and am is not None and am.users is True and am.roles is False
      and am.everyone is False, envoi)
check("aucun montant", not any("$" in m.content or "€" in m.content for m in canal.messages))

# ── 4. La suite ───────────────────────────────────────────────────────────
print("\n── 4. La suite")
b = run(sl.assurer(g))
check("second passage : rien d'envoyé ni de réécrit", not b["envoyes"] and not b["maj"]
      and len(canal.envois) == 4, b)
g.members.append(ns(id=4, name="nouvelle", bot=False, roles=[ns(name="Lola")]))
registre(TOUS + [(4, m) for m in ("amelia", "emma", "lola", "alicia")])
b = run(sl.assurer(g))
check("nouveau VA et ses liens : les 4 messages MODIFIÉS (pas d'envoi, pas de notification)",
      b["maj"] == ["amelia", "emma", "lola", "alicia"] and not b["envoyes"] and len(canal.envois) == 4
      and "<@4> https://getmysocial.com/lola4" in canal.messages[2].content
      and canal.messages[2].supprime_aperçus is True, b)
lola = canal.messages[2]
canal.messages.remove(lola)
b = run(sl.assurer(g))
check("message supprimé à la main : renvoyé, une seule fois",
      b["envoyes"] == ["lola"] and sum(1 for m in canal.messages if m.content.startswith("### 🧡 LOLA")) == 1, b)
for f in TMP.iterdir():
    if f.name.startswith("salon_liens"):
        f.unlink()
canal.messages.append(Message(canal, 1, "### 💜 EMMA\nvieux doublon"))
b = run(sl.assurer(g))
check("data/ perdu : salon retrouvé par son nom, messages par leur en-tête, doublon retiré",
      len(g.creations) == 1 and not b["envoyes"]
      and sum(1 for m in canal.messages if m.content.startswith("### 💜 EMMA")) == 1, (b, len(canal.messages)))
gu = Guilde(YOU_US)
b = run(sl.assurer(gu))
check("You US : rien", not gu.creations and not b["envoyes"] and not b["attente"], b)

# ── 5. Le cog ─────────────────────────────────────────────────────────────
print("\n── 5. Le cog")
src = (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
corps = src[src.index("async def _liens_jb"):src.index("def _liens_va_ig")]
check("le salon suit chaque passage des liens JB, même sans création",
      "await sl.assurer(guild)" in corps
      and corps.index("await sl.assurer(guild)") > corps.index("if a_faire:"))
rvsrc = (BOT / "repartition_va.py").read_text(encoding="utf-8")
check("création du salon partagée avec la répartition (creer_salon_annonces)",
      "async def creer_salon_annonces" in rvsrc
      and "rv.creer_salon_annonces" in (BOT / "salon_liens.py").read_text(encoding="utf-8"))

APRES = [f.stat().st_mtime if f.exists() else None for f in VRAIS]
check("vrai data/ intact", APRES == AVANT, list(zip([f.name for f in VRAIS], AVANT, APRES)))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
