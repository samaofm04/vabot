# -*- coding: utf-8 -*-
"""tests_liens_jb_fr.py — quatre liens GetMySocial neufs par VA de You FR.

Propriétaire, 10/11/2026, devant l'équipe GetMySocial « VA JB FR » : « je veux
que tout le monde ait un lien pour les 4 models Amelia, Emma, Lola et
Alicia », « crée que des nouveaux liens », et dans 🗓️・répartition-va,
chaque VA « sous les 4 models ».

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. Qui : You FR seul, les 4 models, les membres qui ont un rôle de model.
  2. La création : la PAGE d'abord (dans VA JB FR, dans le groupe de la
     model, à l'image de la page modèle, sans bouton OF/MYM), puis les
     trackings à son nom, puis les boutons vers eux ; registre à part ;
     idempotent.
  3. Les ratés : page refusée = aucun tracking et arrêt ; adresse prise =
     la suivante ; tracking raté = page gardée et reprise ; boutons refusés =
     trackings gardés et repris (jamais recréés) ; plafond de l'offre = arrêt.
  4. Le passage : tout ce qui manque, arrêt après deux échecs de suite.
  5. La liste : sous les 4 models, chaque VA avec son lien JB ; Sarah et
     Julia restent par rôle.
  6. Le cog : passage des 30 minutes et rôle donné.

Lancement : python tests_liens_jb_fr.py
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

VRAIS = [BOT / "data" / n for n in ("liens_jb_fr.json", "liens_va_fr.json", "jailbreak.json",
                                     "jb_va_liens.json", "comptes_tickets.json")]
AVANT = [f.stat().st_mtime if f.exists() else None for f in VRAIS]

import gms                              # noqa: E402
import guild_features as gf             # noqa: E402
import liens_fr                         # noqa: E402
import liens_jb_fr as lj                # noqa: E402
import liens_va                         # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


ns = types.SimpleNamespace
TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_liens_jb_"))
lj.ETAT = TMP / "liens_jb_fr.json"
lj.time.sleep = lambda s: None
YOU_FR, YOU_US = int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)

# ── faux GetMySocial et MyPuls ────────────────────────────────────────────
GABARITS = {
    m: {"id": f"lnk_{m}tlg", "shortcode": f"{m}tlg", "bio": f"Bio {m}", "name_user": m.capitalize(),
        "profile_picture": f"https://images.getmysocial.com/{m}/pp.jpg",
        "profile_picture_slides": [{"url": f"https://images.getmysocial.com/{m}/s1.jpg",
                                    "media_type": "image", "_id": "abc"}],
        "background_image": f"https://images.getmysocial.com/{m}/bg.jpg",
        "background_color": 0, "texts_color": 0, "buttons_styles": 0, "template": 0,
        "font_family": 1, "verified_badge": True, "location": {"display": 0, "text_color": ""},
        "whitelabel": True,
        "status": "active", "group_id": None, "team_id": None, "notes": None,
        "buttons": ([{"block_id": "b1", "label": "Mon OF", "url": "https://onlyfans.com/lashwana/c45",
                      "icon_url": None}] if m in ("amelia", "lola") else [])
        + [{"block_id": "b2", "label": "Mon MYM", "url": "https://mym.fans/Lashwanaargm",
            "icon_url": f"https://images.getmysocial.com/{m}/i.png"}]}
    for m in ("amelia", "emma", "lola", "alicia")}
liens_fr.lien_de_base = lambda m: GABARITS[m]["id"] if m in GABARITS else ""
liens_fr.lire_lien = lambda lid: dict(GABARITS[lid[4:-3]])
liens_fr.gms_indisponible = lambda: PAUSE["v"]
liens_va.groupe_manager = lambda equipe, nom: f"grp_{nom.lower()}" if equipe == lj.EQUIPE else ""
PAUSE = {"v": ""}
APPELS = []
PRIS = {"ameliacandy2"}
REFUS = {"create": "", "update": "", "tracking": False}
_n = {"lien": 0, "trk": 0}


def faux_call_tool(nom, args=None, **k):
    APPELS.append((nom, dict(args or {})))
    if nom == "create_link":
        if REFUS["create"]:
            return {"ok": False, "error": REFUS["create"]}
        if args["shortcode"] in PRIS:
            return {"ok": False, "error": "409 shortcode_taken"}
        PRIS.add(args["shortcode"])
        _n["lien"] += 1
        return {"ok": True, "data": {"id": f"lnk_new{_n['lien']}", "shortcode": args["shortcode"]}}
    if nom == "update_link":
        if REFUS["update"]:
            return {"ok": False, "error": REFUS["update"]}
        return {"ok": True, "data": {"id": args["link_id"]}}
    return {"ok": False, "error": "inattendu"}


def faux_tracking(nom, cid):
    APPELS.append(("tracking", {"nom": nom, "cid": cid}))
    if REFUS["tracking"]:
        return {"ok": False, "erreur": "MyPuls refuse"}
    _n["trk"] += 1
    if cid in (769, 1733, 1116, 2896):
        return {"ok": True, "url": f"https://mym.fans/app/t/{nom}"}
    return {"ok": True, "url": f"https://onlyfans.com/x/c{_n['trk']}"}


gms._call_tool = faux_call_tool
liens_fr.creer_tracking = faux_tracking
liens_fr._mots_doux = lambda model, essai: f"{model}candy{essai - 6}"


def appels(nom):
    return [a for n, a in APPELS if n == nom]


def reset():
    APPELS.clear()
    for f in TMP.iterdir():
        f.unlink()
    REFUS.update(create="", update="", tracking=False)
    PAUSE["v"] = ""


class Role:
    def __init__(self, name):
        self.name = name


def membre(uid, name, roles=(), bot=False):
    return ns(id=uid, name=name, bot=bot, roles=[Role(r) for r in roles])


def guilde(gid=YOU_FR, membres=None):
    return ns(id=gid, name="You FR", members=membres if membres is not None else [
        membre(1, "york_emerick12", ("Amelia", "Emma")), membre(2, "faxx103", ("Amelia",)),
        membre(3, "noum0075"), membre(4, "Ryuk.exe", ("Ryuk",), bot=True),
        membre(5, "fandresena0372", ("Lola",))])


# ── 1. Qui ────────────────────────────────────────────────────────────────
print("\n── 1. Qui")
check("You FR : les 4 models", lj.models_du_serveur(ns(id=YOU_FR)) == ("amelia", "emma", "lola", "alicia"))
check("You US, Va IG : aucun", not lj.models_du_serveur(ns(id=YOU_US))
      and not lj.models_du_serveur(ns(id=1505418484052394004)))
g = guilde()
check("les VA : un rôle de model au moins, ni bot, triés",
      lj.vas_du_serveur(g) == [(5, "fandresena0372"), (2, "faxx103"), (1, "york_emerick12")],
      lj.vas_du_serveur(g))
check("12 liens à créer (3 VA × 4 models)", len(lj.manquants(g)) == 12, lj.manquants(g))

# ── 2. La création ────────────────────────────────────────────────────────
print("\n── 2. La création")
reset()
r = lj.creer(2, "faxx103", "amelia")
creations = appels("create_link")
check("créé, au nom « Amelia JB 1 @faxx103 »", r["ok"] and r["display_name"] == "Amelia JB 1 @faxx103", r)
c0 = creations[0] if creations else {}
check("la page d'abord : dans l'équipe VA JB FR, groupe Amelia, page de type landing",
      c0.get("team_id") == lj.EQUIPE and c0.get("group_id") == "grp_amelia" and c0.get("type") == "landing")
check("… à l'image de la page modèle (bio, photo, fond, diapos)",
      c0.get("bio") == "Bio amelia" and c0.get("profile_picture", "").endswith("/amelia/pp.jpg")
      and c0.get("background_image", "").endswith("/amelia/bg.jpg")
      and c0.get("profile_picture_slides") == [{"url": "https://images.getmysocial.com/amelia/s1.jpg",
                                                 "media_type": "image"}], c0)
check("… sans aucun bouton OF/MYM (jamais le compte d'exemple)", c0.get("buttons") == [], c0.get("buttons"))
check("… types adaptés (couleurs en texte, pas de buttons_styles nombre, location sans vide)",
      c0.get("background_color") == "0" and "buttons_styles" not in c0
      and c0.get("location") == {"display": 0} and "status" not in c0 and "notes" not in c0, c0)
check("… adresse prise : la suivante (ameliacandy2 → ameliacandy3)",
      [a["shortcode"] for a in creations] == ["ameliacandy2", "ameliacandy3"], creations)
trk = appels("tracking")
check("puis les trackings, à son nom, OF et MYM d'Amelia",
      [(t["nom"], t["cid"]) for t in trk] == [("Amelia_JB_1_faxx103", 769), ("Amelia_JB_1_faxx103", 3106)]
      or sorted((t["nom"], t["cid"]) for t in trk) == [("Amelia_JB_1_faxx103", 769), ("Amelia_JB_1_faxx103", 3106)],
      trk)
maj = appels("update_link")
urls = [b.get("url") for b in (maj[0].get("buttons") if maj else [])]
check("puis les boutons, vers SES trackings, sans block_id",
      len(maj) == 1 and maj[0]["link_id"] == "lnk_new1" and maj[0]["team_id"] == lj.EQUIPE
      and any("onlyfans.com/x/" in u for u in urls) and "https://mym.fans/app/t/Amelia_JB_1_faxx103" in urls
      and not any("lashwana" in u.lower() for u in urls)
      and not any("block_id" in b for b in maj[0]["buttons"]), maj)
e = lj.lien_de(2, "amelia")
check("whitelabel recopié à la création ET reposé avec les boutons",
      c0.get("whitelabel") is True and maj and maj[0].get("whitelabel") is True)
check("noté dans le registre à part (data/liens_jb_fr.json)",
      e and e["public_url"] == "https://getmysocial.com/ameliacandy3" and e["link_id"] == "lnk_new1"
      and lj.lien_public(2, "amelia") == e["public_url"], e)
n = len(APPELS)
r2 = lj.creer(2, "faxx103", "amelia")
check("idempotent : déjà là, rendu sans aucun appel", r2["ok"] and r2["deja"] and len(APPELS) == n)
r3 = lj.creer(1, "york_emerick12", "emma")
check("Emma : MYM seul, numéro 1 de la model Emma",
      r3["ok"] and r3["display_name"] == "Emma JB 1 @york_emerick12"
      and list(r3["trackings"]) == ["mym"], r3)
r4 = lj.creer(1, "york_emerick12", "amelia")
check("deuxième lien Amelia : numéro 2", r4["display_name"] == "Amelia JB 2 @york_emerick12", r4)

# ── 3. Les ratés ──────────────────────────────────────────────────────────
print("\n── 3. Les ratés")
reset()
REFUS["create"] = "400 invalid_request: bad field"
r = lj.creer(2, "faxx103", "lola")
check("page refusée : AUCUN tracking créé, arrêt demandé",
      not r["ok"] and r["arret"] and not appels("tracking") and not lj.lien_de(2, "lola"), r)

reset()
REFUS["create"] = "403 plan_limit_reached"
r = lj.creer(2, "faxx103", "lola")
check("plafond de l'offre : arrêt, aucun tracking", not r["ok"] and r["arret"] and not appels("tracking"), r)

reset()
REFUS["tracking"] = True
r = lj.creer(2, "faxx103", "lola")
ech = lj._echec_de(2, "lola")
check("tracking raté : page gardée dans « echecs »", not r["ok"] and ech and ech["link_id"], (r, ech))
REFUS["tracking"] = False
APPELS.clear()
r = lj.creer(2, "faxx103", "lola")
check("… le passage suivant REPREND la page (aucune autre création)",
      r["ok"] and not appels("create_link") and r["link_id"] == ech["link_id"]
      and not lj._echec_de(2, "lola"), r)

reset()
REFUS["update"] = "500 boom"
r = lj.creer(2, "faxx103", "emma")
ech = lj._echec_de(2, "emma")
check("boutons refusés : trackings gardés", not r["ok"] and ech and ech["trackings"].get("mym"), ech)
REFUS["update"] = ""
APPELS.clear()
r = lj.creer(2, "faxx103", "emma")
check("… le passage suivant reprend page ET trackings (aucun tracking recréé)",
      r["ok"] and not appels("tracking") and not appels("create_link")
      and r["trackings"] == ech["trackings"], r)

reset()
PAUSE["v"] = "GetMySocial est en pause (quota du jour épuisé) jusque vers 09h33"
r = lj.creer(2, "faxx103", "alicia")
check("GetMySocial en pause : rien, arrêt", not r["ok"] and r["arret"] and not APPELS, r)

# ── 4. Le passage ─────────────────────────────────────────────────────────
print("\n── 4. Le passage")
reset()
g = guilde()
b = lj.assurer(g)
check("les 12 liens créés, aucun échec", len(b["crees"]) == 12 and not b["echecs"], b)
check("plus rien à créer ensuite", lj.manquants(g) == [])
b = lj.assurer(g)
check("second passage : rien", not b["crees"] and not b["echecs"], b)

reset()
REFUS["tracking"] = True
b = lj.assurer(g)
check("deux échecs de suite : arrêt, la suite n'est pas tentée",
      len(b["echecs"]) == 2 and b["arret"]
      and len({a["display_name"] for a in appels("create_link")}) == 2, b)
REFUS["tracking"] = False

# ── 5. La liste ───────────────────────────────────────────────────────────
print("\n── 5. La liste")
import repartition_va as rv             # noqa: E402
rv.page_comptes = lambda gid, uid, nom, model: f"https://youl4b.com/mes-comptes/{uid}{model}"
import cartes_va_fr as cv               # noqa: E402
cv._statuts_gms = lambda: {}
liens_fr.lien_de = lambda uid, model: {"public_url": f"https://getmysocial.com/vaig{uid}{model}",
                                       "link_id": "x"}
reset()
g = guilde()
lj.assurer(g)
cols = [("amelia", [("faxx103", 2), ("york_emerick12", 1)]), ("emma", [("york_emerick12", 1)]),
        ("sarah", []), ("julia", [("york_emerick12", 1)]), ("lola", [("fandresena0372", 5)]),
        ("alicia", [])]
jb = lj.models_du_serveur(g)
tous = [(nom, uid) for uid, nom in lj.vas_du_serveur(g)]
cols2 = [(m, tous if m in jb else vas) for m, vas in cols]
dd = dict(rv.donnees_details(YOU_FR, cols2, jb))
check("Alicia : les 3 VA (aucun n'a le rôle), chacun avec son lien JB",
      dd["alicia"].count("**") == 6 and "🔗 " + lj.lien_public(5, "alicia") in dd["alicia"]
      and "🔗 " + lj.lien_public(1, "alicia") in dd["alicia"], dd["alicia"])
check("Amelia : le lien JB, pas celui de Va IG",
      "getmysocial.com/vaig" not in dd["amelia"] and lj.lien_public(2, "amelia") in dd["amelia"])
check("Julia (hors des 4) : par rôle, avec le lien de Va IG",
      "**york\\_emerick12**" in dd["julia"] and "getmysocial.com/vaig1julia" in dd["julia"]
      and "faxx103" not in dd["julia"], dd["julia"])
src = (BOT / "repartition_va.py").read_text(encoding="utf-8")
check("la répartition branche les 4 models sur tous les VA",
      "tous if m in jb else vas" in src and "donnees_details, guild.id, colonnes, jb" in src)

# ── 6. Le cog ─────────────────────────────────────────────────────────────
print("\n── 6. Le cog")
csrc = (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
check("passage des 30 minutes et rôle donné lancent les liens JB",
      "await self._liens_jb(guild)" in csrc and "self._lancer_liens_jb(guild)" in csrc
      and "asyncio.to_thread(lj.assurer, guild, a_faire)" in csrc)
check("un passage à la fois par serveur", "self._jb_en_cours" in csrc)
from cogs import pseudomodel as cpm     # noqa: E402
reset()
VUS = []


async def _scenario():
    cog = cpm.PseudoModel.__new__(cpm.PseudoModel)
    cog.bot, cog._taches, cog._jb_en_cours = ns(guilds=[]), set(), set()
    rv.planifier = lambda guild, delai=5.0: VUS.append(guild.id) or True
    g = guilde()
    await cog._liens_jb(g)
    return g


g = asyncio.new_event_loop().run_until_complete(_scenario())
check("le cog crée ce qui manque puis rafraîchit la liste",
      lj.manquants(g) == [] and VUS == [YOU_FR], (lj.manquants(g), VUS))

APRES = [f.stat().st_mtime if f.exists() else None for f in VRAIS]
check("vrai data/ intact", APRES == AVANT, list(zip([f.name for f in VRAIS], AVANT, APRES)))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
