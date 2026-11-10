# -*- coding: utf-8 -*-
"""tests_cartes_va_fr.py — les cartes de model des VA de You FR.

Propriétaire, 10/11/2026 : « tu peux leur donner leurs liens gms pour leurs
models et le lien pour qu'ils ajoutent des comptes pour leurs models ».
Maquette validée : une carte par model, son lien GMS, 📷 Ajouter mes comptes.
Pour les VA sans lien : « donne-moi déjà les trucs et on fixe ».

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. Le serveur : You FR seul.
  2. Le lien GMS : celui du registre, montré s'il est en service ou d'état
     inconnu, caché s'il est coupé, absent s'il n'existe pas.
  3. La carte : titre de la model, lien s'il y en a un, bouton 📷 au
     custom_id persistant « cvf:<model>:<VA> », couleur du rôle.
  4. Le passage : une carte par (VA, model) dans son -content, posée une
     fois, réécrite quand son lien arrive, retirée avec le rôle ; un VA sans
     salon est compté ; Discord en panne n'arrête pas les autres.
  5. Le clic : le VA reçoit SA page en privé ; un manager celle du VA ; un
     autre VA est refusé.
  6. La page : comptes_tickets.page_du_va prend la model donnée et reprend la
     fiche qui porte déjà le pseudo Discord (« York Eméric » @york_emerick12)
     au lieu d'en créer une seconde ; deux fiches au même pseudo : aucune.
  7. Le cog : le bouton est enregistré, les rôles déclenchent un passage.

Lancement : python tests_cartes_va_fr.py
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

VRAIS = [BOT / "data" / n for n in ("jailbreak.json", "jb_va_liens.json", "comptes_tickets.json",
                                     "cartes_va_fr.json")]
AVANT = [f.stat().st_mtime if f.exists() else None for f in VRAIS]

import discord                          # noqa: E402

import cartes_va_fr as cv               # noqa: E402
import comptes_tickets as ct            # noqa: E402
import guild_features as gf             # noqa: E402
import jailbreak as jb                  # noqa: E402
import liens_fr                         # noqa: E402
import outils_communs as oc             # noqa: E402
import va_portal as vp                  # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_cartes_va_fr_"))
cv.ETAT = TMP / "cartes_va_fr.json"
jb.JAILBREAK_FILE = TMP / "jailbreak.json"
jb.PREV_FILE = TMP / "jailbreak.prev.json"
jb.BACKUP_DIR = TMP / "jailbreak_backups"
jb.TOMB_FILE = TMP / "jb_tombstones.json"
vp.LIENS_FILE = TMP / "jb_va_liens.json"
ct.LIAISONS_FILE = TMP / "comptes_tickets.json"

ns = types.SimpleNamespace
YOU_FR, YOU_US = int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)
YORK, FAHNIH, FENO, CHEF, AUTRE = 1390429527087251618, 1525508553081753621, 1561628437938970677, 77, 88

REGISTRE = {
    f"{YORK}:amelia": {"public_url": "https://getmysocial.com/ameliacandy2", "link_id": "lnk_a"},
    f"{YORK}:emma": {"public_url": "https://getmysocial.com/emmababy2", "link_id": "lnk_e"},
    f"{YORK}:alicia": {"public_url": "https://getmysocial.com/aliciacutie", "link_id": "lnk_c"},
    f"{FAHNIH}:alicia": {"public_url": "https://getmysocial.com/aliciababe", "link_id": "lnk_f"},
}
liens_fr.lien_de = lambda uid, model: REGISTRE.get(f"{int(uid)}:{model}")
STATUTS = {"lnk_a": True, "lnk_e": True, "lnk_c": True, "lnk_f": True}
cv._statuts_gms = lambda: dict(STATUTS)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── faux Discord ──────────────────────────────────────────────────────────
class Message:
    def __init__(self, salon, mid, view):
        self.salon, self.id, self.view = salon, mid, view
        self.edits = 0

    async def edit(self, view=None):
        self.edits += 1
        self.view = view

    async def delete(self):
        self.salon.messages = [m for m in self.salon.messages if m is not self]


class Salon:
    _n = 5000

    def __init__(self, name):
        Salon._n += 1
        self.id, self.name = Salon._n, name
        self.messages = []
        self.panne = False

    async def send(self, view=None):
        if self.panne:
            raise discord.HTTPException(ns(status=503, reason="x"), "panne")
        Salon._n += 1
        m = Message(self, Salon._n, view)
        self.messages.append(m)
        return m

    async def fetch_message(self, mid):
        for m in self.messages:
            if m.id == mid:
                return m
        raise discord.NotFound(ns(status=404, reason="x"), "Unknown Message")


class Role:
    def __init__(self, name, couleur=0):
        self.name, self.colour = name, ns(value=couleur)


class Membre:
    def __init__(self, uid, name, roles=(), bot=False, admin=False):
        self.id, self.name, self.bot = uid, name, bot
        self.roles = [Role(r) for r in roles]
        self.guild_permissions = ns(administrator=admin, manage_guild=False, manage_channels=False)


class Guilde:
    def __init__(self, gid, membres):
        self.id, self.name = gid, "You FR"
        self.members = membres
        self.roles = [Role("Amelia", 0xE91E63), Role("Emma", 0x9B59B6), Role("Alicia", 0xF1C40F),
                      Role("Lola", 0xE67E22)]
        self.salons = {}

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return next((s for s in self.salons.values() if s.id == cid), None)


SANS_SALON = set()


def content_de(guild, membre):
    if membre is None or membre.name in SANS_SALON:
        return None
    return guild.salons.setdefault(membre.id, Salon(f"{membre.name}-content"))


oc.content_de = content_de


async def _vite(*a, **k):
    return None


def nouvelle_guilde():
    return Guilde(YOU_FR, [
        Membre(YORK, "york_emerick12", ("Amelia", "Emma", "Alicia")),
        Membre(FAHNIH, "fahnih_37050", ("Alicia",)),
        Membre(FENO, "fenoainir", ("Amelia",)),
        Membre(CHEF, "noum0075"),
        Membre(1505416430840189041, "Ryuk.exe", ("Ryuk",), bot=True),
    ])


def textes(view):
    out = []
    for c in view.to_components():
        for e in c.get("components", []):
            if e.get("type") == 10:
                out.append(e.get("content"))
    return out


def boutons(view):
    out = []
    for c in view.to_components():
        for e in c.get("components", []):
            if e.get("type") == 1:
                out += [b for b in e.get("components", []) if b.get("type") == 2]
    return out


def reset():
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    cv._VERROUS.clear()
    cv._PLANIFIES.clear()
    cv._ENCORE.clear()
    SANS_SALON.clear()


# ── 1. Le serveur ─────────────────────────────────────────────────────────
print("\n── 1. Le serveur")
check("You FR a les cartes", cv.serveur(ns(id=YOU_FR)))
check("You US, Va IG, YouCham ne les ont pas",
      not any(cv.serveur(ns(id=g)) for g in (YOU_US, 1505418484052394004, 1565640097146347533)))

# ── 2. Le lien GMS ────────────────────────────────────────────────────────
print("\n── 2. Le lien GMS")
check("lien du registre en service : montré",
      cv.lien_gms(YORK, "amelia", STATUTS) == "https://getmysocial.com/ameliacandy2")
check("lien d'état inconnu (liste illisible) : montré",
      cv.lien_gms(YORK, "amelia", {}) == "https://getmysocial.com/ameliacandy2")
check("lien coupé chez GetMySocial : caché",
      cv.lien_gms(YORK, "amelia", {"lnk_a": False}) == "")
check("pas de lien pour cette model : rien", cv.lien_gms(FENO, "amelia", STATUTS) == "")

# ── 3. La carte ───────────────────────────────────────────────────────────
print("\n── 3. La carte")
v = cv.vue("amelia", YORK, "https://getmysocial.com/ameliacandy2", 0xE91E63)
comp = v.to_components()
check("une carte (conteneur) au liseré du rôle",
      len(comp) == 1 and comp[0].get("type") == 17 and comp[0].get("accent_color") == 0xE91E63, comp)
check("titre de la model, puis le lien",
      textes(v) == ["### 🩷 AMELIA", "🔗 https://getmysocial.com/ameliacandy2"], textes(v))
b = boutons(v)
check("bouton 📷 Ajouter mes comptes, persistant, au nom du VA",
      len(b) == 1 and b[0].get("custom_id") == f"cvf:amelia:{YORK}"
      and b[0].get("label") == "Ajouter mes comptes" and b[0]["emoji"]["name"] == "📷", b)
import re as _re                       # noqa: E402
m = _re.fullmatch(cv.BoutonComptes.__discord_ui_compiled_template__, f"cvf:amelia:{YORK}")
check("le motif du bouton relit la model et le VA",
      m is not None and m["model"] == "amelia" and int(m["uid"]) == YORK)
v2 = cv.vue("amelia", FENO, "", None)
check("sans lien : titre et bouton seulement (« on fixe » ensuite)",
      textes(v2) == ["### 🩷 AMELIA"] and len(boutons(v2)) == 1, textes(v2))
check("aucun montant sur une carte", "$" not in str(comp) and "€" not in str(comp))

# ── 4. Le passage ─────────────────────────────────────────────────────────
print("\n── 4. Le passage")
reset()
cv.asyncio.sleep = _vite
g = nouvelle_guilde()
bl = run(cv.assurer(g))
york = g.salons[YORK]
check("york_emerick12 : trois cartes, Amelia Emma Alicia dans l'ordre",
      [textes(m.view)[0] for m in york.messages] == ["### 🩷 AMELIA", "### 💜 EMMA", "### 💛 ALICIA"],
      [textes(m.view) for m in york.messages])
check("… chacune avec son lien",
      [textes(m.view)[1] for m in york.messages] == [
          "🔗 https://getmysocial.com/ameliacandy2", "🔗 https://getmysocial.com/emmababy2",
          "🔗 https://getmysocial.com/aliciacutie"])
check("fahnih : une carte Alicia avec aliciababe",
      [textes(m.view) for m in g.salons[FAHNIH].messages]
      == [["### 💛 ALICIA", "🔗 https://getmysocial.com/aliciababe"]])
check("fenoainir (pas de lien) : une carte Amelia sans lien",
      [textes(m.view) for m in g.salons[FENO].messages] == [["### 🩷 AMELIA"]])
check("personne sans rôle de model ni bot : aucune carte",
      CHEF not in g.salons and 1505416430840189041 not in g.salons)
check("bilan : 5 posées", bl["posees"] == 5 and not bl["rates"], bl)

bl = run(cv.assurer(g))
check("second passage : rien de posé ni réécrit",
      bl["posees"] == 0 and bl["maj"] == 0 and len(york.messages) == 3, bl)

REGISTRE[f"{FENO}:amelia"] = {"public_url": "https://getmysocial.com/ameliafeno", "link_id": "lnk_n"}
STATUTS["lnk_n"] = True
bl = run(cv.assurer(g))
feno = g.salons[FENO]
check("le lien de fenoainir arrive : sa carte est RÉÉCRITE, pas doublée",
      bl["maj"] == 1 and len(feno.messages) == 1 and feno.messages[0].edits == 1
      and textes(feno.messages[0].view) == ["### 🩷 AMELIA", "🔗 https://getmysocial.com/ameliafeno"], bl)

STATUTS["lnk_n"] = False
bl = run(cv.assurer(g))
check("son lien est coupé chez GetMySocial : la carte le retire",
      bl["maj"] == 1 and textes(feno.messages[0].view) == ["### 🩷 AMELIA"], bl)

g.get_member(YORK).roles = [Role("Amelia"), Role("Alicia")]
bl = run(cv.assurer(g))
check("rôle Emma retiré à york : sa carte Emma part, les autres restent",
      bl["retirees"] == 1 and [textes(m.view)[0] for m in york.messages]
      == ["### 🩷 AMELIA", "### 💛 ALICIA"], bl)

g.get_member(YORK).roles.append(Role("Emma"))
bl = run(cv.assurer(g))
check("rôle Emma rendu : une carte Emma neuve",
      bl["posees"] == 1 and "### 💜 EMMA" in [textes(m.view)[0] for m in york.messages], bl)

york.messages = [m for m in york.messages if textes(m.view)[0] != "### 🩷 AMELIA"]
bl = run(cv.assurer(g))
check("carte supprimée à la main : reposée",
      bl["posees"] == 1 and "### 🩷 AMELIA" in [textes(m.view)[0] for m in york.messages], bl)

g.members = [m for m in g.members if m.id != FAHNIH]
bl = run(cv.assurer(g))
check("VA parti du serveur : sa carte est retirée",
      bl["retirees"] == 1 and g.salons[FAHNIH].messages == [], bl)

reset()
g = nouvelle_guilde()
SANS_SALON.add("fenoainir")
g.salons[FAHNIH] = Salon("fahnih_37050-content")
g.salons[FAHNIH].panne = True
bl = run(cv.assurer(g))
check("VA sans -content : compté et nommé, pas sauté en silence",
      bl["sans_salon"] == ["fenoainir"], bl)
check("Discord en panne pour un salon : compté, les autres VA servis",
      any(str(FAHNIH) in r for r in bl["rates"]) and len(g.salons[YORK].messages) == 3, bl)

reset()
gu = Guilde(YOU_US, [Membre(YORK, "york_emerick12", ("Amelia",))])
bl = run(cv.assurer(gu))
check("You US : aucune carte", not gu.salons and bl["posees"] == 0)

# ── 5. Le clic ────────────────────────────────────────────────────────────
print("\n── 5. Le clic")
APPELS = []


def faux_page(gid, uid, nom_actuel, model=""):
    APPELS.append((gid, uid, nom_actuel, model))
    return f"https://youl4b.com/mes-comptes/jeton-{uid}-{model}", nom_actuel, ""


class Reponse:
    def __init__(self, it):
        self.it = it

    async def send_message(self, texte, ephemeral=False, view=None):
        self.it.envois.append(("direct", texte, ephemeral, view))

    async def defer(self, ephemeral=False, thinking=False):
        self.it.differe = ephemeral


class Suite:
    def __init__(self, it):
        self.it = it

    async def send(self, texte, view=None, ephemeral=False):
        self.it.envois.append(("suite", texte, ephemeral, view))


class Interaction:
    def __init__(self, guild, membre):
        self.guild, self.user = guild, membre
        self.envois, self.differe = [], None
        self.response, self.followup = Reponse(self), Suite(self)


_vrai_page = ct.page_du_va
ct.page_du_va = faux_page
g = nouvelle_guilde()
it = Interaction(g, g.get_member(YORK))
run(cv.repondre_clic(it, "emma", YORK))
genre, texte, eph, view = it.envois[-1]
check("le VA : sa page, en privé, model Emma",
      genre == "suite" and eph and it.differe is True and texte == "📷 **Mes comptes · Emma**"
      and APPELS[-1] == (str(YOU_FR), str(YORK), "york_emerick12", "emma"), it.envois)
lien = [c for c in view.children if getattr(c, "url", None)]
check("… un bouton « Ouvrir ma page » vers /mes-comptes/",
      len(lien) == 1 and lien[0].label == "Ouvrir ma page"
      and lien[0].url.startswith("https://youl4b.com/mes-comptes/"), lien)

it = Interaction(g, Membre(CHEF, "noum0075", admin=True))
run(cv.repondre_clic(it, "amelia", FENO))
check("un manager dans le salon du VA : la page DU VA",
      APPELS[-1] == (str(YOU_FR), str(FENO), "fenoainir", "amelia")
      and it.envois[-1][1] == "📷 **Comptes de @fenoainir · Amelia**", it.envois)

n = len(APPELS)
it = Interaction(g, g.get_member(FAHNIH))
run(cv.repondre_clic(it, "amelia", YORK))
check("un autre VA : refusé, rien préparé",
      len(APPELS) == n and it.envois[-1][0] == "direct" and it.envois[-1][2] is True
      and str(YORK) in it.envois[-1][1], it.envois)

ct.page_du_va = lambda *a, **k: ("", "", "❌ Le nom **x** est déjà utilisé")
it = Interaction(g, g.get_member(YORK))
run(cv.repondre_clic(it, "amelia", YORK))
check("un refus de la page est dit au VA", it.envois[-1][1].startswith("❌ Le nom"), it.envois)
ct.page_du_va = _vrai_page

# ── 6. La page (comptes_tickets) ──────────────────────────────────────────
print("\n── 6. La page")
reset()
jb.add_va("emma", "York Eméric", discord_username="york_emerick12")
jb.add_va("amelia", "Lumière", discord_username="lumiere0562")
jb.add_va("lola", "A", discord_username="double")
jb.add_va("lola", "B", discord_username="double")
check("fiche_au_pseudo : la fiche faite à la main au même pseudo",
      ct.fiche_au_pseudo("emma", "york_emerick12") == "York Eméric"
      and ct.fiche_au_pseudo("emma", "@York_Emerick12") == "York Eméric")
check("fiche_au_pseudo : deux fiches au même pseudo -> aucune",
      ct.fiche_au_pseudo("lola", "double") == "")
url, nom, refus = ct.page_du_va(str(YOU_FR), str(YORK), "york_emerick12", "emma")
check("page Emma de york : SA fiche « York Eméric », pas une seconde",
      not refus and nom == "York Eméric" and url.startswith("https://youl4b.com/mes-comptes/")
      and [v["name"] for v in jb.list_vas_for_identity("emma")] == ["York Eméric"], (url, nom, refus))
url2, nom2, _r = ct.page_du_va(str(YOU_FR), str(YORK), "york_emerick12", "emma")
check("recliquer rend le même lien", url2 == url and nom2 == nom)
url3, nom3, refus3 = ct.page_du_va(str(YOU_FR), str(YORK), "york_emerick12", "amelia")
check("page Amelia de york (aucune fiche) : une fiche neuve à son pseudo, lien à part",
      not refus3 and nom3 == "york_emerick12" and url3 != url
      and any(v.get("name") == "york_emerick12" and v.get("discord_username") == "york_emerick12"
              for v in jb.list_vas_for_identity("amelia")), (url3, nom3, refus3))
rec = vp.resoudre(url.rsplit("/", 1)[-1])
check("le jeton pointe sur la bonne model et la bonne fiche",
      rec and rec.get("identite") == "emma" and rec.get("va") == "York Eméric", rec)
check("les liaisons sont par model et par id Discord",
      set((ct._liaisons().get("emma") or {})) == {str(YORK)}
      and set((ct._liaisons().get("amelia") or {})) == {str(YORK)})
url4, nom4, refus4 = ct.page_du_va(str(YOU_FR), "999", "york_emerick12", "emma")
check("un AUTRE id qui prend le même pseudo : refusé (la fiche est liée à york)",
      refus4 and not url4, (url4, nom4, refus4))

# ── 7. Le cog ─────────────────────────────────────────────────────────────
print("\n── 7. Le cog")
src = (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
check("le bouton des cartes est enregistré au chargement du cog",
      "add_dynamic_items(cv.BoutonComptes)" in src and "async def cog_load" in src)
check("rôle donné ou retiré, départ, rôle renommé : un passage des cartes",
      src.count("cv.planifier(") >= 3)
check("le passage des 30 minutes repasse les cartes", "await cv.assurer(guild)" in src)
check("aucune commande slash", "app_commands" not in src and "@commands.command" not in src)
mod = (BOT / "cartes_va_fr.py").read_text(encoding="utf-8")
check("cartes : rôles lus par pseudo_model, écriture atomique",
      "pm.models_du_membre" in mod and "safe_json.write" in mod and "write_text" not in mod)

APRES = [f.stat().st_mtime if f.exists() else None for f in VRAIS]
check("vrai data/ intact (jailbreak, portail, liaisons, cartes)", APRES == AVANT,
      list(zip([f.name for f in VRAIS], AVANT, APRES)))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
