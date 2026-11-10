# -*- coding: utf-8 -*-
"""tests_repartition_va.py — le salon 🗓️・répartition-va de You FR.

Propriétaire, 10/11/2026 : « sur You FR je peux avoir un emploi du temps avec
les VA par model … crée le channel et tu drop un [message] qui dépend des
rôles sur le serveur », puis « une colonne Amelia, une colonne Emma etc. ».

Ce que ce fichier prouve, avec un faux serveur (aucun réseau, data/ intact) :
  1. Le serveur : You FR seul.
  2. La répartition : les rôles lus sont ceux du pseudo (pseudo_model), un VA
     à deux models est dans les deux colonnes, les bots et le propriétaire
     ne sont pas « sans model », les noms sont triés et échappés, une
     colonne trop longue est coupée en « … +N ».
  3. Le message : six colonnes inline dans l'ordre des models, « Sans model »
     dessous, aucun montant.
  4. Le salon : créé dans 📣 ANNONCES ET SUIVI (ses droits), retrouvé par son
     id après un renommage, jamais un second ; le message posé une fois,
     réécrit seulement s'il change, reposté s'il a été supprimé, doublon
     retiré ; Discord injoignable = rien de reposté.
  5. L'envoi : plusieurs rôles en rafale = un envoi.
  6. Le cog : il écoute rôles, arrivées, départs, rôles renommés, ne déclare
     aucune commande.

Lancement : python tests_repartition_va.py
"""
from __future__ import annotations

import ast
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

import bangers as bg                    # noqa: E402
import guild_features as gf             # noqa: E402
import repartition_va as rv             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_repartition_"))
rv.ETAT = TMP / "repartition_va.json"
VRAI_ETAT = BOT / "data" / "repartition_va.json"
AVANT = VRAI_ETAT.read_bytes() if VRAI_ETAT.exists() else None
VRAI_JB = BOT / "data" / "jailbreak.json"
AVANT_JB = VRAI_JB.stat().st_mtime if VRAI_JB.exists() else None

# Le détail par model lit le registre des liens, la liste GetMySocial et la
# page Virtual Assistants : tout est simulé, la page dans un dossier à part.
import cartes_va_fr as cv               # noqa: E402
import jailbreak as jb                  # noqa: E402
import liens_fr                         # noqa: E402
TMPJB = pathlib.Path(tempfile.mkdtemp(prefix="tst_repartition_jb_"))
jb.JAILBREAK_FILE, jb.PREV_FILE = TMPJB / "jailbreak.json", TMPJB / "jailbreak.prev.json"
jb.BACKUP_DIR, jb.TOMB_FILE = TMPJB / "jailbreak_backups", TMPJB / "jb_tombstones.json"
import comptes_tickets as ct            # noqa: E402
import va_portal as vp                  # noqa: E402
vp.LIENS_FILE = TMPJB / "jb_va_liens.json"
ct.LIAISONS_FILE = TMPJB / "comptes_tickets.json"
VRAIS_PORTAIL = [BOT / "data" / n for n in ("jb_va_liens.json", "comptes_tickets.json")]
AVANT_PORTAIL = [f.stat().st_mtime if f.exists() else None for f in VRAIS_PORTAIL]
REGISTRE = {
    "1390429527087251618:amelia": {"public_url": "https://getmysocial.com/ameliacandy2", "link_id": "a"},
    "1390429527087251618:emma": {"public_url": "https://getmysocial.com/emmababy2", "link_id": "e"},
    "1390429527087251618:alicia": {"public_url": "https://getmysocial.com/aliciacutie", "link_id": "c"},
    "1525508553081753621:alicia": {"public_url": "https://getmysocial.com/aliciababe", "link_id": "f"},
}
liens_fr.lien_de = lambda uid, model: REGISTRE.get(f"{int(uid)}:{model}")
cv._statuts_gms = lambda: {}
jb.add_va("emma", "York Emérick", discord_username="york_emerick12")
jb.add_va("alicia", "York Emérick", discord_username="york_emerick12")
jb.add_va("alicia", "Fahnih", discord_username="fahnih_37050")
jb.add_va("amelia", "fenoainir", discord_username="fenoainir")
for _m, _u, _v in (("emma", "emma_.brunet", "York Emérick"), ("emma", "emmaa.cutty", "York Emérick"),
                   ("alicia", "alicia.qyzelia", "York Emérick"),
                   ("alicia", "alicia_valiriaww", "Fahnih"), ("alicia", "alicia.miaaxx", "Fahnih"),
                   ("amelia", "amelie_kiarrah", "fenoainir")):
    jb.add_account(_m, _u, va=_v)

ns = types.SimpleNamespace
YOU_FR, YOU_US = int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)
PROPRIO = 479005370438778891
RYUK = 1505416430840189041


class Rep:
    status, reason = 404, "Not Found"


class Membre:
    def __init__(self, uid, name, roles=(), bot=False):
        self.id, self.name, self.bot = uid, name, bot
        self.roles = [ns(name=r) for r in roles]


class Message:
    def __init__(self, canal, mid, author_id, embed=None):
        self.canal, self.id, self.author = canal, mid, ns(id=author_id)
        self.embeds = [embed] if embed is not None else []
        self.edits = 0
        self.supprime = False

    async def edit(self, content=None, embed=None):
        self.edits += 1
        self.embeds = [embed]

    async def delete(self):
        self.supprime = True
        self.canal.messages = [m for m in self.canal.messages if m is not self]


class Canal:
    _n = 9000

    def __init__(self, guild, name, category=None, overwrites=None):
        Canal._n += 1
        self.id, self.guild, self.name = Canal._n, guild, name
        self.category, self.overwrites = category, overwrites
        self.messages = []
        self.envois = 0
        self.envois_detail = 0
        self.panne = False

    async def send(self, embed=None):
        # envois : le tableau seul ; le détail par model est compté à part
        if getattr(embed, "title", "") == rv.TITRE:
            self.envois += 1
        else:
            self.envois_detail += 1
        Canal._n += 1
        m = Message(self, Canal._n, self.guild.me.id, embed)
        self.messages.append(m)
        return m

    async def fetch_message(self, mid):
        if self.panne:
            raise discord.HTTPException(ns(status=503, reason="Unavailable"), "panne")
        for m in self.messages:
            if m.id == mid:
                return m
        raise discord.NotFound(Rep(), "Unknown Message")

    def history(self, limit=30):
        canal = self

        async def gen():
            if canal.panne:
                raise discord.HTTPException(ns(status=503, reason="Unavailable"), "panne")
            for m in sorted(canal.messages, key=lambda m: -m.id)[:limit]:
                yield m
        return gen()


class Role:
    """Hashable, comme un vrai rôle : clé des droits d'un salon."""

    def __init__(self, rid, name):
        self.id, self.name = rid, name


class Guilde:
    def __init__(self, gid, membres, avec_categorie=True):
        self.id, self.name, self.owner_id = gid, "You FR", PROPRIO
        self.members = membres
        self.me = Role(RYUK, "Ryuk.exe")
        self.default_role = Role(gid, "@everyone")
        self.categories = [ns(id=1, name="📣 ANNONCES ET SUIVI")] if avec_categorie else []
        self.text_channels = []
        self.creations = []

    async def create_text_channel(self, name, category=None, overwrites=None, reason=None):
        self.creations.append((name, category, overwrites))
        c = Canal(self, name, category, overwrites)
        self.text_channels.append(c)
        return c


def vrais_membres():
    """You FR, relu par REST le 10/11/2026."""
    return [
        Membre(PROPRIO, "yous1m"),
        Membre(1199038414335516765, "noum0075"),
        Membre(1390429527087251618, "york_emerick12", ("Amelia", "Emma", "Alicia")),
        Membre(RYUK, "Ryuk.exe", ("Ryuk",), bot=True),
        Membre(1509505792666108074, "Rem.exe", ("Rem",), bot=True),
        Membre(1525508553081753621, "fahnih_37050", ("Alicia",)),
        Membre(1559806350723125321, "priscah0017_30005", ("Emma",)),
        Membre(1561628437938970677, "fenoainir", ("Amelia",)),
        Membre(1561637336863735813, "eniassy_83352", ("Lola",)),
        Membre(1569319309514113085, "francky04268"),
    ]


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def reset():
    rv._POSE.clear()
    rv._POSE_M.clear()
    rv._PLANIFIES.clear()
    rv._ENCORE.clear()
    rv._VERROUS.clear()
    # safe_json relit le .prev d'un fichier disparu : tout effacer.
    for f in TMP.iterdir():
        f.unlink()


# ── 1. Le serveur ─────────────────────────────────────────────────────────
print("\n── 1. Le serveur")
check("You FR a la répartition", rv.serveur(ns(id=YOU_FR)))
check("You US ne l'a pas", not rv.serveur(ns(id=YOU_US)))
check("Va IG ne l'a pas", not rv.serveur(ns(id=1505418484052394004)))
check("un serveur illisible ne l'a pas", not rv.serveur(None))

# ── 2. La répartition ─────────────────────────────────────────────────────
print("\n── 2. La répartition")
g = Guilde(YOU_FR, vrais_membres())
colonnes, sans = rv.repartition(g)
attendu = [("amelia", ["fenoainir", "york_emerick12"]),
           ("emma", ["priscah0017_30005", "york_emerick12"]),
           ("sarah", []), ("julia", []),
           ("lola", ["eniassy_83352"]),
           ("alicia", ["fahnih_37050", "york_emerick12"])]
check("les colonnes de You FR, dans l'ordre des models", colonnes == attendu, colonnes)
check("l'ordre des colonnes est celui de bangers.MODELS_FR",
      [m for m, _ in colonnes] == list(bg.MODELS_FR))
check("sans model : francky04268 et noum0075 (ni bot, ni propriétaire)",
      sans == ["francky04268", "noum0075"], sans)

g2 = Guilde(YOU_FR, [Membre(1, "b", ("🩷 Amélia",)), Membre(2, "A", ("AMELIA",)),
                     Membre(3, "c", ("Amelia fan club",))])
c2, s2 = rv.repartition(g2)
check("rôle décoré ou accentué reconnu (pseudo_model.cle), tri sans casse",
      c2[0] == ("amelia", ["A", "b"]), c2[0])
check("un rôle qui n'est pas exactement le nom de la model ne compte pas",
      s2 == ["c"], s2)

g3 = Guilde(YOU_FR, [Membre(PROPRIO, "yous1m", ("Lola",))])
c3, s3 = rv.repartition(g3)
check("le propriétaire avec un rôle de model est dans la colonne",
      dict(c3)["lola"] == ["yous1m"] and s3 == [], (c3, s3))

check("un nom à deux _ est échappé (pas d'italique)",
      rv._valeur(["a_b_c"]) == "a\\_b\\_c", rv._valeur(["a_b_c"]))
check("une colonne vide montre —", rv._valeur([]) == "—")
longs = [f"va_numero_{i:03d}_xxxxxxxx" for i in range(80)]
v = rv._valeur(longs)
check("une colonne trop longue est coupée en « … +N » sous 1024 signes",
      len(v) <= 1024 and v.splitlines()[-1].startswith("… +"), (len(v), v[-30:]))
n_vus = len(v.splitlines()) - 1
check("… +N compte exactement ceux qui manquent",
      v.splitlines()[-1] == f"… +{80 - n_vus}", v.splitlines()[-1])

# ── 3. Le message ─────────────────────────────────────────────────────────
print("\n── 3. Le message")
e = rv.embed(g)
d = e.to_dict()
noms = [f["name"] for f in d["fields"]]
check("titre « 🗓️ Répartition VA »", d.get("title") == "🗓️ Répartition VA", d.get("title"))
check("six colonnes, puis Sans model",
      noms == ["🩷 AMELIA · 2", "💜 EMMA · 2", "💙 SARAH · 0", "🩵 JULIA · 0",
               "🧡 LOLA · 1", "💛 ALICIA · 2", "⚪ SANS MODEL · 2"], noms)
check("les six colonnes sont inline (3 par rangée), Sans model non",
      [f["inline"] for f in d["fields"]] == [True] * 6 + [False])
check("colonne Amelia : un VA par ligne",
      d["fields"][0]["value"] == "fenoainir\nyork\\_emerick12", d["fields"][0]["value"])
check("aucune description, aucun pied (pas de notice)",
      "description" not in d and "footer" not in d, d)
texte = str(d)
check("aucun montant dans le message", "$" not in texte and "€" not in texte)
check("l'embed tient dans les limites de Discord (6000)", len(e) <= 6000, len(e))
print("\n   Rendu :")
print("   " + d["title"])
for f in d["fields"]:
    print(f"   [{f['name']}] " + f["value"].replace("\n", " | "))

# ── 4. Le salon et le message ─────────────────────────────────────────────
print("\n── 4. Le salon et le message")
reset()
g = Guilde(YOU_FR, vrais_membres())
b = run(rv.assurer(g))
check("salon absent : créé, nommé 🗓️・répartition-va",
      b["crees"] == ["🗓️・répartition-va"] and len(g.creations) == 1, b)
nom, cat, droits = g.creations[0]
check("créé DANS 📣 ANNONCES ET SUIVI, sans droits à soi (ceux de la catégorie)",
      cat is g.categories[0] and droits is None, g.creations[0])
canal = g.text_channels[0]
check("message posé une fois", b["pose"] and canal.envois == 1, b)
check("salon et message notés dans data/ (copie de test)",
      rv._note(YOU_FR, "salon") == canal.id and rv._note(YOU_FR, "message") == canal.messages[0].id,
      rv._etat())

b = run(rv.assurer(g))
check("second passage : rien de créé, rien de reposté, rien de réécrit",
      not b["crees"] and not b["pose"] and not b["maj"] and canal.envois == 1
      and canal.messages[0].edits == 0, b)

g.members.append(Membre(42, "nouvelle_va", ("Sarah",)))
b = run(rv.assurer(g))
check("rôle Sarah donné : le message est RÉÉCRIT, pas reposté",
      b["maj"] and canal.envois == 1 and canal.messages[0].edits == 1, b)
check("… et Sarah a sa VA",
      canal.messages[0].embeds[0].fields[2].name == "💙 SARAH · 1"
      and canal.messages[0].embeds[0].fields[2].value == "nouvelle\\_va",
      canal.messages[0].embeds[0].fields[2])

canal.name = "📅・planning"
b = run(rv.assurer(g, forcer=True))
check("salon renommé à la main : retrouvé par son id, pas de second",
      not b["crees"] and len(g.creations) == 1, b)

canal.messages.clear()
b = run(rv.assurer(g, forcer=True))
check("message supprimé à la main : reposté au passage forcé",
      b["pose"] and canal.envois == 2
      and [m.embeds[0].title for m in canal.messages].count(rv.TITRE) == 1, b)

# Données perdues (data/ reparti de zéro) : retrouvé par nom et dans le salon.
reset()
canal.name = "🗓️・répartition-va"
autre = Message(canal, 1, 777, discord.Embed(title=rv.TITRE))
vieux = Message(canal, 2, RYUK, rv.embed(g))
canal.messages = [autre, vieux] + canal.messages
b = run(rv.assurer(g))
check("data/ vide : salon retrouvé par son nom", not b["crees"] and len(g.creations) == 1, b)
check("… le doublon du bot est retiré, le plus récent gardé, celui d'un autre laissé",
      vieux.supprime and not autre.supprime and canal.envois == 2, [m.id for m in canal.messages])

reset()
g = Guilde(YOU_FR, vrais_membres())
run(rv.assurer(g))
canal = g.text_channels[0]
canal.panne = True
g.members.append(Membre(43, "x", ("Julia",)))
b = run(rv.assurer(g))
check("Discord injoignable : rien de reposté, l'échec est compté",
      canal.envois == 1 and b["rates"] and not b["pose"], b)

reset()
g = Guilde(YOU_FR, vrais_membres(), avec_categorie=False)
b = run(rv.assurer(g))
_n, cat, droits = g.creations[0]
check("sans 📣 ANNONCES ET SUIVI : créé hors catégorie, lecture seule, et c'est dit",
      cat is None and droits and droits[g.default_role].send_messages is False
      and droits[g.default_role].view_channel is True
      and any("introuvable" in r for r in b["rates"]), (droits, b))

reset()
g = Guilde(YOU_US, vrais_membres())
b = run(rv.assurer(g))
check("You US : rien créé, rien posté", not g.creations and not b["pose"], b)

# ── 4b. Le détail par model : page de comptes et lien GMS de chacun ───────
print("\n── 4b. Le détail par model")
reset()
g = Guilde(YOU_FR, vrais_membres())
g.roles = [ns(name="Amelia", colour=ns(value=0xE91E63)), ns(name="Alicia", colour=ns(value=0xF1C40F))]
b = run(rv.assurer(g))
canal = g.text_channels[0]
titres = [m.embeds[0].title for m in canal.messages]
check("le tableau, puis une carte par model dans l'ordre des models",
      titres == [rv.TITRE, "🩷 AMELIA · 2 VA", "💜 EMMA · 2 VA", "💙 SARAH · 0 VA",
                 "🩵 JULIA · 0 VA", "🧡 LOLA · 1 VA", "💛 ALICIA · 2 VA"], titres)
check("bilan : 6 cartes de model posées", b["details_poses"] == 6 and not b["rates"], b)
desc = {m.embeds[0].title.split(" ")[1]: m.embeds[0].description for m in canal.messages[1:]}
print("   Alicia :", desc["ALICIA"].replace("\n", " | "))
import re as _re                        # noqa: E402
PAGE = r"📷 https://youl4b\.com/mes-comptes/([A-Za-z0-9_-]+)"
m_al = _re.fullmatch(r"\*\*fahnih\\_37050\*\*\n" + PAGE + r"\n🔗 https://getmysocial\.com/aliciababe\n\n"
                     r"\*\*york\\_emerick12\*\*\n" + PAGE + r"\n🔗 https://getmysocial\.com/aliciacutie",
                     desc["ALICIA"])
check("Alicia : chaque VA, son nom, sa page youl4b, puis son lien GMS", m_al is not None, desc["ALICIA"])
check("aucun compte Instagram dans les cartes (« je veux pas les comptes »)",
      not any("@" in d or "compte :" in d or "comptes :" in d for d in desc.values()), desc)
if m_al:
    r1, r2 = vp.resoudre(m_al.group(1)), vp.resoudre(m_al.group(2))
    check("la page de fahnih ouvre SA fiche d'Alicia (« Fahnih », reprise par son pseudo)",
          r1 and r1.get("identite") == "alicia" and r1.get("va") == "Fahnih", r1)
    check("celle de york ouvre « York Emérick » sous Alicia, une autre page",
          r2 and r2.get("identite") == "alicia" and r2.get("va") == "York Emérick"
          and m_al.group(1) != m_al.group(2), r2)
check("sans lien GMS : « pas encore de lien » ; sans fiche : page préparée à son pseudo",
      "**priscah0017\\_30005**\n📷 https://youl4b.com/mes-comptes/" in desc["EMMA"]
      and "🔗 pas encore de lien" in desc["EMMA"]
      and any(v.get("name") == "priscah0017_30005" for v in jb.list_vas_for_identity("emma")),
      desc["EMMA"])
check("Emma : la page de york est celle de sa fiche « York Emérick », pas une seconde",
      [v["name"] for v in jb.list_vas_for_identity("emma")].count("York Emérick") == 1
      and not any(v.get("name") == "york_emerick12" for v in jb.list_vas_for_identity("emma")))
check("model sans VA : —", desc["SARAH"] == "—" and desc["JULIA"] == "—", desc)
check("couleur de la carte = couleur du rôle",
      canal.messages[1].embeds[0].colour.value == 0xE91E63
      and canal.messages[6].embeds[0].colour.value == 0xF1C40F)
check("aucun montant dans les cartes", not any("$" in d or "€" in d for d in desc.values()))

b = run(rv.assurer(g, forcer=True))
check("passage forcé : mêmes pages, rien de reposté ni réécrit",
      b["details_poses"] == 0 and b["details_maj"] == 0 and canal.envois_detail == 6, b)

jb.add_account("alicia", "alicia.neuve", va="Fahnih")
b = run(rv.assurer(g, forcer=True))
check("compte ajouté sur le site : aucune carte réécrite", b["details_maj"] == 0, b)

REGISTRE["1561628437938970677:amelia"] = {"public_url": "https://getmysocial.com/ameliafeno",
                                          "link_id": "n"}
cv._statuts_gms = lambda: {"n": False}
b = run(rv.assurer(g, forcer=True))
check("lien coupé chez GetMySocial : toujours « pas encore de lien »",
      "**fenoainir**\n📷 https://youl4b.com/mes-comptes/" in canal.messages[1].embeds[0].description
      and "🔗 pas encore de lien" in canal.messages[1].embeds[0].description, b)
cv._statuts_gms = lambda: {}
b = run(rv.assurer(g, forcer=True))
check("lien en service : il apparaît sur la carte Amelia",
      b["details_maj"] == 1
      and "🔗 https://getmysocial.com/ameliafeno" in canal.messages[1].embeds[0].description, b)

lola = canal.messages[5]
canal.messages.remove(lola)
b = run(rv.assurer(g, forcer=True))
check("carte supprimée à la main : reposée, pas de doublon",
      b["details_poses"] == 1 and [m.embeds[0].title for m in canal.messages].count("🧡 LOLA · 1 VA") == 1, b)

reset()                                   # data/ reparti de zéro
b = run(rv.assurer(g))
check("data/ vide : les cartes sont retrouvées par leur titre, aucune reposée",
      b["details_poses"] == 0 and len(canal.messages) == 7, (b, len(canal.messages)))

# Un autre id Discord a déjà la fiche « dioplucky » de Lola : sa page est refusée.
ct.page_du_va(str(YOU_FR), "999", "dioplucky", "lola")
g.members.append(Membre(1561658465569472538, "dioplucky", ("Lola",)))
b = run(rv.assurer(g, forcer=True))
d_lola = [m for m in canal.messages if m.embeds[0].title.startswith("🧡 LOLA")][0].embeds[0].description
check("page refusée (fiche liée à un autre id) : « page pas encore prête », et c'est dit",
      "**dioplucky**\n📷 page pas encore prête\n🔗 pas encore de lien" in d_lola, d_lola)

d = rv.description_model([(f"va_{i:03d}", "https://youl4b.com/mes-comptes/" + "x" * 24,
                           "https://getmysocial.com/xxxxxxxxxx") for i in range(80)])
check("80 VA : coupés en « … +N VA », jamais au milieu d'une adresse, sous 4096",
      len(d) <= 4096 and d.splitlines()[-1].startswith("… +") and d.endswith(" VA")
      and d.splitlines()[-3].startswith("🔗 https://getmysocial.com/"), len(d))

# ── 5. L'envoi ────────────────────────────────────────────────────────────
print("\n── 5. L'envoi")
reset()
g = Guilde(YOU_FR, vrais_membres())


async def rafale():
    for _ in range(4):
        rv.planifier(g, delai=0.05)
    t = rv._PLANIFIES.get(YOU_FR)
    await asyncio.sleep(0.2)
    return t


t = run(rafale())
canal = g.text_channels[0] if g.text_channels else None
check("quatre rôles en rafale : un seul envoi", canal is not None and canal.envois == 1,
      canal and canal.envois)
check("… et l'attente est finie", t is not None and t.done())
check("planifier hors You FR ne fait rien", rv.planifier(Guilde(YOU_US, [])) is False)

# ── 6. Le cog ─────────────────────────────────────────────────────────────
print("\n── 6. Le cog")
src = (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
fonctions = {n.name for n in ast.walk(arbre) if isinstance(n, ast.AsyncFunctionDef)}
check("le cog écoute rôles, arrivées, départs et rôles renommés",
      {"on_member_update", "on_member_join", "on_member_remove",
       "on_guild_role_update"} <= fonctions, fonctions)
check("le cog ne déclare aucune commande slash",
      "app_commands" not in src and "@commands.command" not in src
      and "hybrid_command" not in src)
check("le passage des 30 minutes force la répartition",
      "rv.assurer(guild, forcer=True)" in src)
check("un rôle donné planifie la répartition, même hors serveur à pseudo",
      src.index("rv.planifier(guild)") < src.index("if not pm.serveur(guild):"))
check("la répartition lit les rôles de pseudo_model, pas une seconde liste",
      "pm.models_du_membre" in (BOT / "repartition_va.py").read_text(encoding="utf-8")
      and "cle(" not in (BOT / "repartition_va.py").read_text(encoding="utf-8")
      .replace("_cle(", "").replace("oc._cle", ""))
check("écriture atomique (safe_json), jamais write_text",
      "safe_json.write" in (BOT / "repartition_va.py").read_text(encoding="utf-8")
      and "write_text" not in (BOT / "repartition_va.py").read_text(encoding="utf-8"))

# data/ réel intact
apres = VRAI_ETAT.read_bytes() if VRAI_ETAT.exists() else None
check("data/repartition_va.json réel intact", apres == AVANT)
check("data/jailbreak.json réel intact",
      (VRAI_JB.stat().st_mtime if VRAI_JB.exists() else None) == AVANT_JB)
check("pages des comptes réelles intactes (jb_va_liens, comptes_tickets)",
      [f.stat().st_mtime if f.exists() else None for f in VRAIS_PORTAIL] == AVANT_PORTAIL)

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
