# -*- coding: utf-8 -*-
"""Tests autonomes du salon -generateur-de-lien (cogs/generateur_lien.py).

Isoles : ils tournent dans un dossier temporaire (le vrai data/ n'est ni lu
ni ecrit), Discord est simule, et liens_identite_us est une DOUBLURE --
aucun appel a GetMySocial, MyPuls ni Discord. Lancement :

    venv/bin/python tests_generateur_lien.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE))
_TMP = Path(tempfile.mkdtemp(prefix="tests_gdl_"))
os.chdir(_TMP)
(_TMP / "data").mkdir()

OK, KO = [], []


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  ✅ " if cond else "  ❌ ") + nom + ("" if cond else f"  -- {str(detail)[:400]}"))


# ───────────────────────────────────────────── doublure du module liens ──

GID = "1535758943324999711"
VA_ID, ADMIN_ID, AUTRE_ID = 900000000000000001, 900000000000000002, 900000000000000003

lu = types.ModuleType("liens_identite_us")
lu.GUILD_ID = GID
lu.EQUIPE = "tm_6a0e4739bfa0c238f20a8bf5"
lu.REGISTRE = _TMP / "data" / "liens_identite_us.json"
#: mise en service par etapes (liens_identite_us.dossier_ouvert) : les
#: dossiers ou le salon a le droit d'exister
OUVERTS = {"bob"}
lu.dossier_ouvert = lambda base: str(base or "").lower() in OUVERTS
ETAT = {"liens": [], "raison": "", "globaux": {}, "actifs": 3, "bases": ["ibenhaastrup", "themikkiangel"],
        "creer": [], "definir": [], "appels_liste": 0, "creer_rend": None, "definir_rend": None}


def _liens_equipe(force=False):
    ETAT["appels_liste"] += 1
    return (list(ETAT["liens"]), ETAT["raison"])


def _global_de(uid):
    return ETAT["globaux"].get(str(uid))


def _definir_global(uid, valeur, par, partis=None):
    ETAT["definir"].append((uid, valeur, par) if partis is None else (uid, valeur, par, list(partis)))
    if ETAT.get("definir_fn"):
        r = ETAT["definir_fn"](uid, valeur, par, partis)
        if r.get("ok"):
            ETAT["globaux"][str(uid)] = r["global"]
        return r
    r = ETAT["definir_rend"] or {"ok": True, "erreur": "", "global": {
        "link_id": "lnk_g", "shortcode": "msgejessye", "url": "https://onlyfans.com/jessyewdiference/c117",
        "nom": "EUD", "personne": "eud", "spam": False, "par": str(par), "quand": int(time.time())}}
    if r.get("ok"):
        ETAT["globaux"][str(uid)] = r["global"]
    return r


def _creer(uid, identite, par):
    ETAT["creer"].append((uid, identite, par))
    r = ETAT["creer_rend"] or {"ok": True, "url": f"https://getmysocial.com/{identite}eud",
                                "deja": False, "repare": False, "erreur": ""}
    if r.get("ok"):
        reg = json.loads(lu.REGISTRE.read_text()) if lu.REGISTRE.exists() else {}
        reg.setdefault("liens", {})[f"{uid}:{identite}"] = {
            "link_id": f"lnk_{identite}", "shortcode": f"{identite}eud", "identite": identite,
            "public_url": r["url"], "etat": "ok", "par": str(par), "quand": int(time.time())}
        lu.REGISTRE.write_text(json.dumps(reg))
    return r


lu.liens_equipe = _liens_equipe
lu.global_de = _global_de
lu.definir_global = _definir_global
lu.creer_pour_identite = _creer
lu.liens_du_va = lambda uid, liens=None: [l for l in (liens or []) if l.get("va") == uid]
lu.liens_actifs = lambda uid, liens=None: ETAT["actifs"]
def _reg_liens(uid):
    reg = json.loads(lu.REGISTRE.read_text()) if lu.REGISTRE.exists() else {}
    return [dict(e) for k, e in (reg.get("liens") or {}).items() if k.startswith(f"{uid}:")]


def _proposables(idents, liens=None, uid=None):
    ok = {e.get("identite") for e in _reg_liens(uid) if e.get("etat") == "ok"} if uid else set()
    return [(i, i in ok) for i in idents if i in ETAT["bases"]]


lu.identites_proposables = _proposables
lu.liens_de = _reg_liens
lu.bases = lambda liens=None: {}
lu.rattachements = lambda: {}
lu.global_present = lambda uid, liens: (None if liens is None else
                                        bool(ETAT["globaux"].get(str(uid)))
                                        and str(uid) not in ETAT.get("globaux_absents", set()))
lu.a_rebrancher = lambda uid: list(ETAT.get("a_rebrancher", {}).get(str(uid), []))


def _actualiser(uid, liens):
    ETAT.setdefault("actualises", []).append(uid)
    return dict(ETAT.get("actualiser_rend", {}).get(str(uid)) or {})


lu.actualiser = _actualiser
lu.est_base = lambda nom: str(nom).upper().startswith("TEMPLATE ")
lu.identite_de_base = lambda nom: None
sys.modules["liens_identite_us"] = lu

import discord                                           # noqa: E402
import cogs.generateur_lien as gl                        # noqa: E402
import cogs.welcome as wl                                # noqa: E402

IDENTS_US = ["ibenhaastrup", "themikkiangel", "e30princesss"]
gl.identites_us = lambda: list(IDENTS_US)
gl.emojis = lambda guild, idents: {}

DITS = []


async def _dire_double(interaction, texte):
    DITS.append(texte)
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except Exception:
        pass


async def _accuser_double(interaction):
    if not interaction.response.is_done():
        await interaction.response.defer()


gl._dire = _dire_double
gl._accuser = _accuser_double


# ───────────────────────────────────────────────────── Discord simule ──

class Perms:
    def __init__(s, admin=False, gerer=False):
        s.administrator, s.manage_guild = admin, gerer


class Membre:
    def __init__(s, i, nom, admin=False, bot=False):
        s.id, s.name, s.bot = i, nom, bot
        s.guild_permissions = Perms(admin)
        s.mention = f"<@{i}>"


class Ow:
    def __init__(s, voir=True, ecrire=True):
        s.view_channel, s.send_messages = voir, ecrire


class Comp:
    """Un composant tel que Discord le rend dans message.components."""

    def __init__(s, d):
        s._d = d
        s.custom_id = d.get("custom_id")
        s.content = d.get("content")
        s.children = [Comp(x) for x in d.get("components") or []]

    def to_dict(s):
        return s._d


MOI = Membre(1, "Yoshi", bot=True)


class Message:
    _n = 0

    def __init__(s, salon, auteur, contenu=None, vue=None, kw=None):
        Message._n += 1
        s.id, s.channel, s.author, s.content, s.kw = Message._n, salon, auteur, contenu, kw or {}
        s._poser(vue)

    def _poser(s, vue):
        s.vue = vue
        s.components = [Comp(d) for d in (vue.to_components() if vue is not None else [])]

    async def edit(s, view=None, **kw):
        s.salon_edite = True
        s.channel.editions += 1
        s._poser(view)

    async def delete(s):
        s.channel.messages.remove(s)


class Salon:
    _n = 100

    def __init__(s, nom, guilde, cat=None, ow=None):
        Salon._n += 1
        s.id, s.name, s.guild, s.category = Salon._n, nom, guilde, cat
        s.overwrites = ow or {}
        s.messages, s.editions = [], 0
        guilde.text_channels.append(s)

    async def send(s, content=None, view=None, **kw):
        m = Message(s, MOI, content, view, kw)
        s.messages.append(m)
        return m

    async def history(s, limit=100):
        for m in list(reversed(s.messages))[:limit]:
            yield m


class Guilde:
    def __init__(s, i=int(GID)):
        s.id, s.name, s.text_channels, s.categories, s.emojis = i, "Youl4b", [], [], []
        s.members = []
        s.fetches = []

    def get_member(s, i):
        return next((m for m in s.members if m.id == int(i)), None)

    async def fetch_member(s, i):
        s.fetches.append(int(i))
        m = s.get_member(i)
        if m is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")
        return m


class Bot:
    def __init__(s):
        s.user, s.guilds, s.cogs, s.dyn = MOI, [], {}, []

    def get_cog(s, nom):
        return s.cogs.get(nom)

    def add_dynamic_items(s, *items):
        s.dyn += list(items)


class Reponse:
    def __init__(s):
        s.done, s.modal, s.envoyes, s.defer_kw = False, None, [], None

    def is_done(s):
        return s.done

    async def defer(s, **kw):
        s.done, s.defer_kw = True, kw

    async def send_message(s, content=None, **kw):
        s.done = True
        s.envoyes.append((content, kw))

    async def send_modal(s, m):
        s.done, s.modal = True, m


class Suite:
    def __init__(s):
        s.envoyes = []

    async def send(s, content=None, **kw):
        s.envoyes.append((content, kw))


class Inter:
    def __init__(s, user, guilde, salon, message, client):
        s.user, s.guild, s.channel, s.message, s.client = user, guilde, salon, message, client
        s.response, s.followup = Reponse(), Suite()
        s.type = discord.InteractionType.component
        s.data = {}
        s.originales = []

    async def edit_original_response(s, view=None, **kw):
        s.originales.append(view)
        if s.message is not None:
            await s.message.edit(view=view)


def lancer(coro):
    return asyncio.run(coro)


def textes(vue):
    return [i.content for i in vue.walk_children() if isinstance(i, discord.ui.TextDisplay)]


def _a_plat(vue):
    """Les composants de la vue, un element dynamique remplace par ce qu'il porte."""
    return [getattr(i, "item", i) if isinstance(i, discord.ui.DynamicItem) else i
            for i in vue.walk_children()]


def menus(vue):
    return [i for i in _a_plat(vue) if isinstance(i, discord.ui.Select)]


def boutons(vue):
    return [i for i in _a_plat(vue) if isinstance(i, discord.ui.Button)]


def ids(vue):
    return [getattr(i, "custom_id", None) for i in vue.walk_children()
            if getattr(i, "custom_id", None)]


# ════════════════════════════════════════════════════ 1. la vue du panneau ══
print("\n1. Le panneau : limites Discord")


class Emo:
    def __init__(s, nom, i):
        s.name, s.id, s.animated = nom, i, False

    def __str__(s):
        return f"<:{s.name}:{s.id}>"


def _entrees(n, cree_tous=False):
    return [(f"id{i:03d}", f"🏅 Id{i:03d}", discord.PartialEmoji(name=f"id{i:03d}", id=10**17 + i),
             cree_tous or i % 2 == 0) for i in range(n)]


TPL_MENU = re.compile(gl.GdlIdentites.__discord_ui_compiled_template__.pattern)
TPL_GLOB = re.compile(gl.GdlGlobal.__discord_ui_compiled_template__.pattern)
for n in (0, 1, 24, 25, 26, 60, 450, 500):
    sortie = io.StringIO()
    with redirect_stdout(sortie):
        v = gl.vue_panneau(VA_ID, 3, True, _entrees(n))
    comps = list(v.walk_children())
    sels = menus(v)
    cids = ids(v)
    v.to_components()           # la serialisation ne doit pas lever
    check(f"{n} identites : <= 40 composants V2 ({len(comps)})", len(comps) <= 40, len(comps))
    check(f"{n} identites : <= 25 options par menu",
          all(len(s.options) <= 25 for s in sels), [len(s.options) for s in sels])
    check(f"{n} identites : custom_id < 100 et uniques",
          all(len(c) < 100 for c in cids) and len(cids) == len(set(cids)), cids)
    check(f"{n} identites : chaque menu suit son motif, le bouton aussi",
          sels and all(TPL_MENU.fullmatch(s.custom_id) for s in sels)
          and len(boutons(v)) == 1 and all(TPL_GLOB.fullmatch(b.custom_id) for b in boutons(v)))
    vus = [o.value for s in sels for o in s.options if o.value != "_"]
    attendu = min(n, gl.MAX_MENUS * gl.TAILLE_MENU)
    check(f"{n} identites : {attendu} proposees, chacune une fois",
          len(vus) == attendu and len(set(vus)) == attendu, len(vus))
    if n > gl.MAX_MENUS * gl.TAILLE_MENU:
        check(f"{n} identites : ce qui ne tient pas est DIT au journal",
              "NON proposees" in sortie.getvalue(), sortie.getvalue()[:200])
    check(f"{n} identites : options <= 100 caracteres",
          all(len(o.label) <= 100 and len(o.value) <= 100 for s in sels for o in s.options))

v = gl.vue_panneau(VA_ID, 3, True, _entrees(30))
check("plusieurs menus : intitules par plage (1–25, 26–30)",
      [s.placeholder for s in menus(v)] == ["🪪 1–25…", "🪪 26–30…"], [s.placeholder for s in menus(v)])
v = gl.vue_panneau(VA_ID, 3, True, _entrees(4))
check("un seul menu : intitule « Choisis une identité »",
      [s.placeholder for s in menus(v)] == [gl.INTITULE_MENU])
check("✅ sur les identites deja creees, pas sur les autres",
      [o.label.endswith("✅") for o in menus(v)[0].options] == [True, False, True, False],
      [o.label for o in menus(v)[0].options])
check("emoji id<nom> sur chaque option",
      all(o.emoji is not None and o.emoji.name.startswith("id") for o in menus(v)[0].options))
check("aucun texte de notice : le seul texte est le compteur",
      textes(v) == ["## 🟢 3 liens actifs"], textes(v))
check("bouton admin « 🔗 Lien global », gris",
      [(b.label, str(b.emoji), b.style) for b in boutons(v)]
      == [("Lien global", "🔗", discord.ButtonStyle.secondary)])
check("compteur : 0 / 1 / 2 / inconnu",
      [gl.texte_compteur(x) for x in (0, 1, 2, None)]
      == ["## 🟢 0 lien actif", "## 🟢 1 lien actif", "## 🟢 2 liens actifs", "## 🟢 ? liens actifs"])
v = gl.vue_panneau(VA_ID, 0, False, _entrees(4))
check("sans lien global : UN menu grise « En attente du lien global »",
      [(s.placeholder, s.disabled) for s in menus(v)] == [(gl.INTITULE_VERROU, True)])
v = gl.vue_panneau(VA_ID, 0, True, [])
check("aucune page de base : UN menu grise « Aucune identité »",
      [(s.placeholder, s.disabled) for s in menus(v)] == [(gl.INTITULE_VIDE, True)])
v = gl.vue_panneau(VA_ID, None, False, [], actif=False)
check("module absent : UN menu grise « indisponible »",
      [(s.placeholder, s.disabled) for s in menus(v)] == [(gl.INTITULE_INDISPO, True)])
sortie = io.StringIO()
with redirect_stdout(sortie):
    v = gl.vue_panneau(VA_ID, 1, True, [("bad name", "Bad", None, False), ("ok", "Ok", None, False)])
check("un nom inutilisable n'est pas propose, et c'est dit",
      [o.value for o in menus(v)[0].options] == ["ok"] and "inutilisable" in sortie.getvalue())

e = gl.vue_etiquette("Ibenhaastrup", discord.PartialEmoji(name="idibenhaastrup", id=10**17),
                     gl.cid_identite(VA_ID, "ibenhaastrup"))
b = e.children[0]
check("etiquette d'un lien : un bouton gris DESACTIVE, au nom de l'identite, une rangee",
      len(e.children) == 1 and b.disabled and b.style == discord.ButtonStyle.secondary
      and b.label == "Ibenhaastrup" and b.custom_id == f"gdl:e:{VA_ID}:ibenhaastrup"
      and len(e.to_components()) <= 5)


# ════════════════════════════════════════════ 2. admin contre VA, salons ══
print("\n2. Droits")
VA = Membre(VA_ID, "eud0616_94567")
ADMIN = Membre(ADMIN_ID, "patron", admin=True)
AUTRE = Membre(AUTRE_ID, "autre")
check("admin du serveur -> admin", gl.est_admin(ADMIN))
check("gerer le serveur -> admin", gl.est_admin(type("M", (), {"id": 5, "guild_permissions": Perms(gerer=True)})()))
check("VA -> pas admin", not gl.est_admin(VA))
(_TMP / "data" / "whitelist.json").write_text(json.dumps([AUTRE_ID]))
check("liste blanche du bot -> admin", gl.est_admin(AUTRE))
(_TMP / "data" / "whitelist.json").write_text("[]")

G = Guilde()
CAT = type("Cat", (), {"id": 1, "name": "eud0616_94567"})()
S = Salon("eud0616_94567-generateur-de-lien", G, CAT, {VA: Ow(), MOI: Ow()})
CONTENT = Salon("eud0616_94567-content", G, CAT, {VA: Ow()})
check("salon reconnu, decor a la main compris",
      gl.est_salon(S) and gl.est_salon(type("C", (), {"name": "🔗・bob-generateur-de-lien"})()))
check("salon de service (all-…) jamais pris pour un salon de VA",
      not gl.est_salon(type("C", (), {"name": "all-generateur-de-lien"})()))
check("le VA du salon : le membre humain qui y voit", gl.vas_du_salon(S) == [VA])
S2 = Salon("autre-generateur-de-lien", G, CAT, {VA: Ow(), AUTRE: Ow()})
check("dossier partage : tous ses VA, celui au nom du salon d'abord (ordre stable)",
      gl.vas_du_salon(S2) == [AUTRE, VA], gl.vas_du_salon(S2))
G.text_channels.remove(S2)
check("serveur : Youl4b US seulement",
      gl.serveur_ok(G) and not gl.serveur_ok(Guilde(1445108485090971710)))

BOT = Bot()
BOT.guilds = [G]
COG = gl.GenerateurLien(BOT)
BOT.cogs["GenerateurLien"] = COG

# bouton global : VA refuse, admin -> fenetre pre-remplie
ETAT["globaux"][str(VA_ID)] = {"shortcode": "msgejessye", "nom": "EUD", "url": "https://onlyfans.com/x/c117"}
it = Inter(VA, G, S, None, BOT)
DITS.clear()
lancer(gl.GdlGlobal(VA_ID).callback(it))
check("🔗 cliqué par un VA : refusé (dans son -content), aucune fenetre",
      it.response.modal is None and DITS == ["🔒 Réservé aux admins."], (it.response.modal, DITS))
it = Inter(ADMIN, G, S, None, BOT)
lancer(gl.GdlGlobal(VA_ID).callback(it))
m = it.response.modal
check("🔗 cliqué par un admin : fenetre, pre-remplie du global actuel",
      isinstance(m, gl.FenetreGlobal) and m.uid == VA_ID and m.valeur.default == "msgejessye"
      and m.custom_id.startswith(f"gdl:fen:{VA_ID}:") and len(m.custom_id) < 100
      and m.custom_id in gl._OUVERTES)
it = Inter(ADMIN, Guilde(1445108485090971710), S, None, BOT)
lancer(gl.GdlGlobal(VA_ID).callback(it))
check("🔗 hors du serveur US : refus ephemere", it.response.modal is None
      and it.response.envoyes and it.response.envoyes[0][1].get("ephemeral"))


# ════════════════════════════════════════════ 3. le panneau dans le salon ══
print("\n3. Le panneau dans le salon (entretien)")
ETAT["liens"] = [{"id": "lnk_g", "va": VA_ID, "status": "active"}]
ETAT["actifs"] = 1
n1 = lancer(COG.assurer_panneau(S))
pan = [m for m in S.messages if gl.est_panneau(m, MOI.id)]
glob = [m for m in S.messages if gl.est_message_global(m, MOI.id)]
check("salon vide : UN panneau pose, puis le lien global SEUL (dans cet ordre)",
      n1 == 1 and len(pan) == 1 and len(glob) == 1 and S.messages.index(pan[0]) < S.messages.index(glob[0]),
      [(m.content, gl.custom_ids(m)) for m in S.messages])
check("le lien global : l'adresse seule, sans apercu ni mention, bouton gris « 🌐 Global »",
      glob and glob[0].content == "https://getmysocial.com/msgejessye"
      and glob[0].kw.get("suppress_embeds") is True
      and glob[0].kw.get("allowed_mentions") is not None
      and [(b.label, str(b.emoji), b.disabled) for b in glob[0].vue.children] == [("Global", "🌐", True)])
check("le panneau montre le compteur et le menu actif",
      textes(pan[0].vue) == ["## 🟢 1 lien actif"]
      and [s.disabled for s in menus(pan[0].vue)] == [False]
      and [o.value for o in menus(pan[0].vue)[0].options] == ["ibenhaastrup", "themikkiangel"])
ed0 = S.editions
n2 = lancer(COG.assurer_panneau(S))
check("2e passage, rien n'a change : aucune edition, aucun message", n2 == 0 and S.editions == ed0
      and len(S.messages) == 2)
ETAT["actifs"] = 4
n3 = lancer(COG.assurer_panneau(S))
check("le compteur a bouge : le panneau est EDITE sur place (pas repose)",
      n3 == 1 and S.editions == ed0 + 1 and textes(pan[0].vue) == ["## 🟢 4 liens actifs"]
      and S.messages[0] is pan[0])
ETAT["raison"], ETAT["actifs"] = "quota GetMySocial", 0
n4 = lancer(COG.assurer_panneau(S, *lancer(COG.liste())))
check("GetMySocial indisponible : le panneau garde son chiffre et ses identites",
      n4 == 0 and textes(pan[0].vue) == ["## 🟢 4 liens actifs"])
ETAT["raison"], ETAT["actifs"] = "", 4
lancer(S.send(view=gl.vue_panneau(VA_ID, 9, True, [])))
n5 = lancer(COG.assurer_panneau(S))
check("deux panneaux : le plus recent part, le plus ancien (en tete) est garde",
      sum(1 for m in S.messages if gl.est_panneau(m, MOI.id)) == 1 and S.messages[0] is pan[0], n5)
glob[0].channel.messages.remove(glob[0])
lancer(COG.assurer_panneau(S))
check("lien global supprime a la main : repose a l'entretien",
      sum(1 for m in S.messages if gl.est_message_global(m, MOI.id)) == 1)
AUTRE_G = Guilde(1445108485090971710)
SX = Salon("bob-generateur-de-lien", AUTRE_G, CAT, {VA: Ow()})
check("hors du serveur US : aucun panneau", lancer(COG.assurer_panneau(SX)) == 0 and not SX.messages)
SV = Salon("all-generateur-de-lien", G, CAT, {VA: Ow()})
check("salon de service : aucun panneau", lancer(COG.assurer_panneau(SV)) == 0 and not SV.messages)
G.text_channels.remove(SV)

# compteur : creations recentes absentes de la liste en cache
lu.REGISTRE.write_text(json.dumps({"liens": {
    f"{VA_ID}:ibenhaastrup": {"link_id": "lnk_i", "identite": "ibenhaastrup", "etat": "ok",
                              "quand": int(time.time()) - 60},
    f"{VA_ID}:themikkiangel": {"link_id": "lnk_t", "identite": "themikkiangel", "etat": "ok",
                               "quand": "2026-01-01T00:00:00"},
    f"{VA_ID}:e30princesss": {"link_id": "lnk_e", "identite": "e30princesss", "etat": "a_reparer",
                              "quand": int(time.time())}}}))
ETAT["actifs"] = 2
check("compteur : + la creation d'il y a une minute absente du cache, rien pour l'ancienne ni l'a_reparer",
      gl.compter(VA_ID, ETAT["liens"]) == 3, gl.compter(VA_ID, ETAT["liens"]))
ETAT["liens"].append({"id": "lnk_i", "va": VA_ID, "status": "active"})
check("compteur : une creation deja dans la liste n'est pas comptee deux fois",
      gl.compter(VA_ID, ETAT["liens"]) == 2)
check("compteur : liste indisponible -> None (le chiffre affiche est garde)",
      gl.compter(VA_ID, None) is None)
_ent, _sans = gl.entrees_panneau(VA_ID, G, ETAT["liens"])
check("coches : celles du module (identites_proposables avec uid), rien de relu a cote",
      [(e[0], e[3]) for e in _ent] == [("ibenhaastrup", True), ("themikkiangel", True)]
      and _sans == ["e30princesss"], (_ent, _sans))
lu.REGISTRE.write_text("{}")
ETAT["liens"] = [{"id": "lnk_g", "va": VA_ID, "status": "active"}]


# ═══════════════════════════════════════════════ 4. choisir une identite ══
print("\n4. Choisir une identite")
ETAT["actifs"] = 1
lancer(COG.assurer_panneau(S))
PAN = next(m for m in S.messages if gl.est_panneau(m, MOI.id))


def choisir(user, ident):
    it = Inter(user, G, S, PAN, BOT)
    DITS.clear()
    lancer(COG.choisir(it, VA_ID, ident))
    return it


avant = len(S.messages)
it = choisir(VA, "ibenhaastrup")
nouveaux = S.messages[avant:]
check("le VA choisit : creer_pour_identite(uid, identite, par)",
      ETAT["creer"][-1] == (VA_ID, "ibenhaastrup", VA_ID), ETAT["creer"])
check("le lien arrive SEUL dans un message ordinaire, bouton gris au nom de l'identite",
      len(nouveaux) == 1 and nouveaux[0].content == "https://getmysocial.com/ibenhaastrupeud"
      and nouveaux[0].kw.get("suppress_embeds") is True
      and [(b.label, b.disabled, b.custom_id) for b in nouveaux[0].vue.children]
      == [("Ibenhaastrup", True, f"gdl:e:{VA_ID}:ibenhaastrup")], [(m.content) for m in nouveaux])
check("aucun message dans le -content quand tout va bien", DITS == [], DITS)
check("le clic est acquitte en silence (defer)", it.response.done and it.response.defer_kw == {})
check("le panneau est redessine : compteur +1 (creation recente), coche ✅",
      textes(PAN.vue) == ["## 🟢 2 liens actifs"]
      and [o.label for o in menus(PAN.vue)[0].options][0].endswith("✅"),
      (textes(PAN.vue), [o.label for o in menus(PAN.vue)[0].options]))
ETAT["creer_rend"] = {"ok": True, "url": "https://getmysocial.com/ibenhaastrupeud", "deja": True,
                      "repare": False, "erreur": ""}
choisir(VA, "ibenhaastrup")
check("rechoisir : le MEME lien, et un seul message pour cette identite dans le salon",
      sum(1 for m in S.messages if gl.est_message_identite(m, MOI.id, "ibenhaastrup", VA_ID)) == 1
      and S.messages[-1].content == "https://getmysocial.com/ibenhaastrupeud")
ETAT["creer_rend"] = {"ok": False, "url": "", "deja": False, "repare": False,
                      "erreur": "page de base sans bouton OnlyFans"}
avant = len(S.messages)
choisir(VA, "themikkiangel")
check("echec : rien dans le salon, l'erreur dans le -content du VA",
      len(S.messages) == avant and DITS == ["❌ Themikkiangel : page de base sans bouton OnlyFans"], DITS)
ETAT["creer_rend"] = None
n_creer = len(ETAT["creer"])
choisir(AUTRE, "themikkiangel")
check("un autre membre (ni le VA, ni admin) : refuse, rien cree",
      len(ETAT["creer"]) == n_creer and DITS == ["🔒 Ce salon n'est pas le tien."], DITS)
choisir(ADMIN, "themikkiangel")
check("un admin peut creer pour le VA (par = l'admin)",
      ETAT["creer"][-1] == (VA_ID, "themikkiangel", ADMIN_ID))
n_creer = len(ETAT["creer"])
choisir(VA, "inconnue")
check("identite absente de la liste US : refusee, rien cree",
      len(ETAT["creer"]) == n_creer and DITS and "plus proposée" in DITS[0], DITS)
COG.en_cours.add(VA_ID)
choisir(VA, "ibenhaastrup")
COG.en_cours.discard(VA_ID)
check("deja une creation en cours : dit, rien cree",
      len(ETAT["creer"]) == n_creer and DITS == ["⏳ Un lien est déjà en cours de création."], DITS)
it = Inter(VA, Guilde(1445108485090971710), S, PAN, BOT)
DITS.clear()
lancer(COG.choisir(it, VA_ID, "ibenhaastrup"))
check("hors du serveur US : refuse, rien cree", len(ETAT["creer"]) == n_creer and DITS)
ETAT["raison"] = "quota"
_lu_liste = list(ETAT["liens"])
ETAT["liens"] = []
_avant_txt = textes(PAN.vue)
_avant_emp = gl.empreinte_message(PAN)
_ed_avant = S.editions
choisir(VA, "ibenhaastrup")
check("clic pendant une panne GetMySocial : le panneau n'est PAS vide (« Aucune identité »)",
      textes(PAN.vue) == _avant_txt and [s.placeholder for s in menus(PAN.vue)] == [gl.INTITULE_MENU],
      [s.placeholder for s in menus(PAN.vue)])
check("… mais il est REDESSINE a l'identique : le menu reprend son intitule (rechoisir marche)",
      S.editions == _ed_avant + 1 and gl.empreinte_message(PAN) == _avant_emp,
      (S.editions - _ed_avant))
ETAT["raison"], ETAT["liens"] = "", _lu_liste
n_creer = len(ETAT["creer"])
_lu_vrai = gl._lu
gl._lu = lambda: None
choisir(VA, "ibenhaastrup")
check("module absent : dit, rien cree, panneau en menu grise",
      len(ETAT["creer"]) == n_creer and "indisponible" in (DITS or [""])[0]
      and [s.placeholder for s in menus(PAN.vue)] == [gl.INTITULE_INDISPO])
gl._lu = _lu_vrai
lancer(COG.assurer_panneau(S))

# le menu route vers choisir
appels = []


async def _choisir_double(interaction, uid, ident):
    appels.append((uid, ident))
COG.choisir, _choisir_vrai = _choisir_double, COG.choisir
sel = gl.GdlIdentites(VA_ID, 0, bloc=[("ibenhaastrup", "Ibenhaastrup", None, False)])
sel.item._values = ["ibenhaastrup"]
lancer(sel.callback(Inter(VA, G, S, PAN, BOT)))
COG.choisir = _choisir_vrai
check("le menu (motif gdl:id:<uid>:<n>) route le choix vers le cog",
      appels == [(VA_ID, "ibenhaastrup")])
rec = lancer(gl.GdlIdentites.from_custom_id(None, None, TPL_MENU.fullmatch(f"gdl:id:{VA_ID}:1")))
check("apres un redemarrage, le menu se reconstruit de son custom_id",
      rec.uid == VA_ID and rec.n == 1 and rec.item.custom_id == f"gdl:id:{VA_ID}:1")


# ═════════════════════════════════════════════ 5. poser le lien global ══
print("\n5. Poser le lien global")
ETAT["globaux"].pop(str(VA_ID), None)
SG = Salon("zoe-generateur-de-lien", G, CAT, {Membre(77, "zoe"): Ow()})
ZOE = 77
lancer(COG.assurer_panneau(SG))
PZ = next(m for m in SG.messages if gl.est_panneau(m, MOI.id))
check("sans global : menu grise, aucun message de lien",
      [s.disabled for s in menus(PZ.vue)] == [True] and len(SG.messages) == 1)
it = Inter(ADMIN, G, SG, PZ, BOT)
it.type = discord.InteractionType.modal_submit
lancer(COG.definir(it, ZOE, "msgejessye"))
gz = [m for m in SG.messages if gl.est_message_global(m, MOI.id)]
check("admin : definir_global(uid, valeur, par) appele",
      ETAT["definir"][-1] == (ZOE, "msgejessye", ADMIN_ID), ETAT["definir"])
check("le global est poste SEUL, bouton gris « 🌐 Global »",
      len(gz) == 1 and gz[0].content == "https://getmysocial.com/msgejessye")
check("le panneau se deverrouille (menu actif)", [s.disabled for s in menus(PZ.vue)] == [False])
check("l'admin lit le resultat en ephemere",
      it.followup.envoyes and it.followup.envoyes[-1][0].startswith("✅")
      and it.followup.envoyes[-1][1].get("ephemeral"))
lancer(COG.definir(Inter(ADMIN, G, SG, PZ, BOT), ZOE, "msgejessye"))
check("reposer le global : l'ancien message part, un seul reste",
      sum(1 for m in SG.messages if gl.est_message_global(m, MOI.id)) == 1)
ETAT["definir_rend"] = {"ok": False, "erreur": "« EUD » est deja le lien global de bob", "global": {}}
avant = len(SG.messages)
it = Inter(ADMIN, G, SG, PZ, BOT)
lancer(COG.definir(it, ZOE, "EUD"))
check("refus du module : dit a l'admin, rien poste",
      len(SG.messages) == avant and it.followup.envoyes[-1][0].startswith("❌")
      and "deja le lien global" in it.followup.envoyes[-1][0])
ETAT["definir_rend"] = None
it = Inter(VA, G, SG, PZ, BOT)
n_def = len(ETAT["definir"])
lancer(COG.definir(it, ZOE, "msgejessye"))
check("fenetre soumise par un non-admin : refusee", len(ETAT["definir"]) == n_def)

# fenetre ouverte avant un redemarrage
repris = []
_disp = gl.FenetreGlobal._dispatch_submit


def _disp_double(self, interaction, comps, resolved):
    repris.append(self.custom_id)

    async def _r():
        return None
    return asyncio.ensure_future(_r())


gl.FenetreGlobal._dispatch_submit = _disp_double


async def _reprise():
    it = Inter(ADMIN, G, SG, PZ, BOT)
    it.type = discord.InteractionType.modal_submit
    it.data = {"custom_id": f"gdl:fen:{ZOE}:deadbeef", "components": []}
    await COG.on_interaction(it)
    f = gl.FenetreGlobal(ZOE)
    it2 = Inter(ADMIN, G, SG, PZ, BOT)
    it2.type = discord.InteractionType.modal_submit
    it2.data = {"custom_id": f.custom_id, "components": []}
    await COG.on_interaction(it2)
    await asyncio.sleep(0)
lancer(_reprise())
gl.FenetreGlobal._dispatch_submit = _disp
check("fenetre d'avant redemarrage reprise ; celles de ce processus laissees a discord.py",
      repris == [f"gdl:fen:{ZOE}:deadbeef"], repris)


# ══════════════════════════════════════════════════ 6. l'entretien entier ══
print("\n6. Entretien")
_comp = wl.completer_dossiers_us
appels_comp = []


async def _comp_double(guild, suffixes=("spoofer",)):
    appels_comp.append((guild.id, tuple(suffixes)))
    return {"crees": [], "sans_va": [], "erreurs": []}
wl.completer_dossiers_us = _comp_double
_dodo = gl.asyncio.sleep


async def _vite(*a, **k):
    return None
gl.asyncio.sleep = _vite
G2 = Guilde()
SA = Salon("ana-generateur-de-lien", G2, CAT, {Membre(55, "ana"): Ow()})
SB = Salon("ben-generateur-de-lien", G2, CAT, {Membre(56, "ben"): Ow()})
SC = Salon("ana-content", G2, CAT, {})
HORS = Guilde(1445108485090971710)
SH = Salon("cid-generateur-de-lien", HORS, CAT, {Membre(57, "cid"): Ow()})
BOT.guilds = [G2, HORS]
ETAT["appels_liste"] = 0
sortie = io.StringIO()
with redirect_stdout(sortie):
    lancer(COG._entretien.coro(COG))
check("entretien : les dossiers existants recoivent leur salon (completer_dossiers_us)",
      appels_comp == [(G2.id, (gl.SUFFIXE,))], appels_comp)
check("entretien : UNE lecture de la liste GetMySocial pour tous les salons",
      ETAT["appels_liste"] == 1, ETAT["appels_liste"])
check("entretien : un panneau dans chaque salon du serveur US, aucun ailleurs",
      all(any(gl.est_panneau(m, MOI.id) for m in s.messages) for s in (SA, SB))
      and not SH.messages and not SC.messages)
check("entretien : les identites US sans page de base sont dites au journal",
      "e30princesss" in sortie.getvalue() and "TEMPLATE" in sortie.getvalue(), sortie.getvalue()[:300])
ETAT["raison"] = "quota"
with redirect_stdout(io.StringIO()):
    lancer(COG._entretien.coro(COG))
check("GetMySocial indisponible : nouvel essai dans l heure", COG._entretien.minutes == gl.REESSAI_MINUTES
      and not COG._entretien.hours)
ETAT["raison"] = ""
with redirect_stdout(io.StringIO()):
    lancer(COG._entretien.coro(COG))
check("puis retour au rythme sobre (toutes les 4 h)", COG._entretien.hours == gl.ENTRETIEN_HEURES >= 3)
wl.completer_dossiers_us = _comp
gl.asyncio.sleep = _dodo


# ═════════════════════════════════ 7. dossiers, droits, reconciliateur ══
print("\n7. Dossiers US (cogs/welcome.py)")
suf = wl.US_TICKET_SUFFIXES
check("suffixe « generateur-de-lien » ajoute, en DERNIER (aucun dossier existant a reordonner)",
      suf[-1] == "generateur-de-lien" and suf.count("generateur-de-lien") == 1, suf)
check("-spoofer reste juste apres -menu (cogs/spoofer._bien_range)",
      suf[0] == "menu" and suf[1] == "spoofer")
check("le suffixe du cog est celui de welcome", gl.SUFFIXE in suf)
src_w = (RACINE / "cogs" / "welcome.py").read_text(encoding="utf-8")
expr = '"|".join(_re.escape(s) for s in US_TICKET_SUFFIXES)'
check("/ticketsall construit toujours son motif depuis le tuple", expr in src_w)
pat = re.compile(r"-(" + "|".join(re.escape(s) for s in suf) + r")$")
check("le motif du reconciliateur reconnait le salon (decore ou non), pas un salon voisin",
      bool(pat.search(wl.nom_sans_decor("eud0616_94567-generateur-de-lien")))
      and bool(pat.search(wl.nom_sans_decor("🔗・eud0616_94567-generateur-de-lien")))
      and not pat.search("eud0616_94567-generateur"))


class _GDroits:
    default_role, me = "tous", "bot"
    members = []


ow = wl._us_droits_ticket(_GDroits(), [VA], "generateur-de-lien")
ow_menu = wl._us_droits_ticket(_GDroits(), [VA], "menu")
ow_ct = wl._us_droits_ticket(_GDroits(), [VA], "content")
check("droits identiques a -menu : le VA voit, n'ecrit pas, ne joint rien",
      ow[VA].view_channel and ow[VA].send_messages is False and ow[VA].attach_files is False
      and (ow[VA].view_channel, ow[VA].send_messages, ow[VA].attach_files, ow[VA].read_message_history)
      == (ow_menu[VA].view_channel, ow_menu[VA].send_messages, ow_menu[VA].attach_files,
          ow_menu[VA].read_message_history))
check("-content reste en ecriture", ow_ct[VA].send_messages is True)


class _CatD:
    _n = 500

    def __init__(s, nom, g):
        _CatD._n += 1
        s.id, s.name, s.text_channels = _CatD._n, nom, []
        g.categories.append(s)


class _SalD:
    _n = 5000

    def __init__(s, nom, cat, g, ow=None, pos=None):
        _SalD._n += 1
        s.id, s.name, s.category, s.guild = _SalD._n, nom, cat, g
        s.category_id, s.overwrites = cat.id, ow or {}
        s.position = _SalD._n if pos is None else pos
        s.deplace = 0
        g.text_channels.append(s)
        cat.text_channels.append(s)

    async def move(s, **kw):
        s.deplace += 1
        s.category_id, s.position = kw["category"].id, kw.get("offset", 0)


class _GD:
    def __init__(s):
        s.text_channels, s.categories, s.crees = [], [], []
        s.default_role, s.me, s.members = "tous", "bot", []

    async def create_text_channel(s, nom, category=None, overwrites=None, reason=None):
        s.crees.append((nom, overwrites))
        return _SalD(nom, category, s, overwrites)


async def _dossiers():
    dort = wl.asyncio.sleep
    wl.asyncio.sleep = _vite
    try:
        g = _GD()
        bob = Membre(11, "bob")
        cat = _CatD("bob", g)
        for s in suf[:-1]:
            _SalD(f"bob-{s}", cat, g, {bob: Ow()})
        # un 2e dossier, PAS ouvert : il ne recoit rien
        zoe = Membre(12, "zoe")
        catz = _CatD("zoe", g)
        for s in suf[:-1]:
            _SalD(f"zoe-{s}", catz, g, {zoe: Ow()})
        b1 = await wl.completer_dossiers_us(g, ("generateur-de-lien",))
        b2 = await wl.completer_dossiers_us(g, ("generateur-de-lien",))
        return g, b1, b2, bob
    finally:
        wl.asyncio.sleep = dort
gD, b1, b2, bob = lancer(_dossiers())
cree = dict(gD.crees).get("bob-generateur-de-lien") or {}
check("dossier existant : -generateur-de-lien cree, une fois", b1["crees"] == ["bob-generateur-de-lien"]
      and b2["crees"] == [], (b1, b2))
check("etape d'essai : un dossier non ouvert ne recoit PAS le salon",
      "zoe-generateur-de-lien" not in dict(gD.crees), [n for n, _o in gD.crees])
check("une seule regle d'ouverture (welcome delegue a liens_identite_us.dossier_ouvert)",
      wl.gdl_ouvert("bob") and not wl.gdl_ouvert("zoe")
      and "_salon_voulu(_us_base(member), suffix)" in src_w
      and "_salon_voulu(base, s)" in src_w)
check("cree en lecture seule pour le VA du dossier",
      bob in cree and cree[bob].view_channel and cree[bob].send_messages is False)
check("aucun salon deplace (le nouveau arrive en fin de dossier, a sa place)",
      all(c.deplace == 0 for c in gD.text_channels), [(c.name, c.deplace) for c in gD.text_channels])
check("create_us_tickets pose le panneau du generateur",
      '_ensure_gdl_panel(bot, chans["generateur-de-lien"])' in src_w)
poses = []


class _CogP:
    async def assurer_panneau(self, ch):
        poses.append(ch.name)
lancer(wl._ensure_gdl_panel(type("B", (), {"get_cog": lambda s, n: _CogP() if n == "GenerateurLien" else None})(),
                            type("C", (), {"name": "bob-generateur-de-lien"})()))
lancer(wl._ensure_gdl_panel(type("B", (), {"get_cog": lambda s, n: _CogP()})(),
                            type("C", (), {"name": "all-generateur-de-lien"})()))
check("_ensure_gdl_panel : panneau via le cog, jamais dans un salon de service",
      poses == ["bob-generateur-de-lien"], poses)


# ══════════════════════════════════ 8. custom_id : aucun chevauchement ══
print("\n8. Prefixe custom_id")
fichiers = subprocess.run(["git", "ls-files", "*.py", "*.js"], cwd=RACINE, capture_output=True,
                          text=True).stdout.split()
autres_motifs, litteraux, gdl_ailleurs = [], set(), []
for f in fichiers:
    if f in ("cogs/generateur_lien.py", "tests_generateur_lien.py"):
        continue
    try:
        t = (RACINE / f).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    autres_motifs += re.findall(r'template\s*=\s*r?"([^"]+)"', t)
    for lit in re.findall(r'custom_id\s*=\s*f?["\']([^"\']+)["\']', t):
        litteraux.add(re.sub(r"\{[^}]*\}", "1", lit))
    if re.search(r'["\']gdl:', t):
        gdl_ailleurs.append(f)
# les motifs dynamiques ecrits par variable (cogs/cta_reminder.py)
autres_motifs += [r"annonce_post:(?P<tache>[a-z_]+)", r"annonce_comptes:(?P<jour>[0-9]{8})"]
nos_ids = [f"gdl:id:{VA_ID}:0", f"gdl:gl:{VA_ID}", f"gdl:fen:{VA_ID}:abcd1234", f"gdl:g:{VA_ID}",
           f"gdl:e:{VA_ID}:ibenhaastrup", "gdl:valeur"]
check(f"{len(autres_motifs)} motifs dynamiques existants : aucun ne prend un custom_id gdl:",
      len(autres_motifs) >= 15
      and not [(m, i) for m in autres_motifs for i in nos_ids if re.fullmatch(m, i)])
check(f"nos motifs ne prennent aucun des {len(litteraux)} custom_id litteraux du depot",
      not [x for x in litteraux if TPL_MENU.fullmatch(x) or TPL_GLOB.fullmatch(x)])
connus = ("jbus:", "jbg:", "jbmenu", "cmenu:", "cmenu2:", "genlink:", "spf:", "numgen:", "lien:",
          "essai:", "usdc:", "copie:", "dl:", "sessions:", "annonce_")
check("prefixe gdl: distinct de tous les prefixes publies",
      not any(p.startswith("gdl") or "gdl:".startswith(p) for p in connus)
      and not any(x.startswith("gdl:") for x in litteraux))
check("aucun autre fichier n'emploie « gdl: »", gdl_ailleurs == [], gdl_ailleurs)
check("toutes nos chaines custom_id commencent par gdl:",
      all(i.startswith(gl.PREFIXE) for i in nos_ids)
      and all(v.startswith(gl.PREFIXE) for k, v in vars(gl).items() if k.startswith("CID_")))


# ═════════════════════════════════════════════════════ 9. le cog lui-meme ══
print("\n9. Le cog")
check("aucune commande slash (bot principal a 100/100)",
      gl.GenerateurLien.__cog_app_commands__ == []
      and "app_commands" not in (RACINE / "cogs" / "generateur_lien.py").read_text(encoding="utf-8"))
main_src = (RACINE / "main.py").read_text(encoding="utf-8")
check("charge sur le bot principal (MAIN_COGS), pas sur le bot admin",
      '"generateur_lien"' in main_src.split("MAIN_COGS")[1].split("]")[0]
      and '"generateur_lien"' not in main_src.split("ADMIN_COGS")[1].split("]")[0])


async def _charger():
    b = Bot()
    c = gl.GenerateurLien(b)
    demarre = []

    class _Boucle:
        def is_running(self):
            return False

        def start(self):
            demarre.append(1)
    c._entretien = _Boucle()
    await c.cog_load()
    return b.dyn, demarre
dyn, dem = lancer(_charger())
check("cog_load : menus et bouton rattaches apres redemarrage, entretien lance",
      set(dyn) == {gl.GdlIdentites, gl.GdlGlobal} and dem == [1])
src_cog = (RACINE / "cogs" / "generateur_lien.py").read_text(encoding="utf-8")
check("jamais d'epinglage", ".pin(" not in src_cog)
src_user = (RACINE / "cogs" / "user.py").read_text(encoding="utf-8")
check("les aides de cogs/user existent avec la signature attendue",
      "async def _jb_dire(interaction, texte, quoi=" in src_user
      and "async def _jb_accuser(interaction, quoi=" in src_user
      and "def _jb_emojis_presents(guild, models)" in src_user
      and 'def _jb_models_marche(marche="us")' in src_user)

# ══════════════════════════════════════════ 10. relecture : les defauts ══
print("\n10. Relecture")
GR = Guilde()
BOT.guilds = [GR]
ANA, BEN = Membre(910000000000000011, "ana"), Membre(910000000000000012, "ben")
GR.members = [ANA, BEN, ADMIN]
CATR = type("Cat", (), {"id": 9, "name": "ana"})()
ETAT["liens"] = [{"id": "lnk_ga", "va": ANA.id, "status": "active"},
                 {"id": "lnk_gb", "va": BEN.id, "status": "active"}]
ETAT["raison"], ETAT["creer_rend"], ETAT["definir_rend"] = "", None, None
ETAT["globaux"][str(ANA.id)] = {"link_id": "lnk_ga", "shortcode": "anajessye", "nom": "(Ana) 1",
                                "public_url": "https://getmysocial.com/anajessye"}
ETAT["globaux"][str(BEN.id)] = {"link_id": "lnk_gb", "shortcode": "benjessye", "nom": "(Ben) 1",
                                "public_url": "https://getmysocial.com/benjessye"}
lu.REGISTRE.write_text("{}")

# dossier partage : un panneau par VA, a son nom
SP = Salon("ana-generateur-de-lien", GR, CATR, {ANA: Ow(), BEN: Ow(), MOI: Ow()})
lancer(COG.assurer_panneau(SP))
pans = [m for m in SP.messages if gl.est_panneau(m, MOI.id)]
check("dossier partage : un panneau par VA (celui du dossier d'abord), chacun a son nom",
      [gl.uid_du_panneau(m, MOI.id) for m in pans] == [ANA.id, BEN.id]
      and textes(pans[0].vue)[0].endswith(" · ana") and textes(pans[1].vue)[0].endswith(" · ben"),
      [(gl.uid_du_panneau(m, MOI.id), textes(m.vue)) for m in pans])
glob_p = [m for m in SP.messages if gl.est_message_global(m, MOI.id)]
check("dossier partage : le global de chacun, a son nom",
      sorted((m.content, m.vue.children[0].label) for m in glob_p)
      == [("https://getmysocial.com/anajessye", "Global · ana"),
          ("https://getmysocial.com/benjessye", "Global · ben")], [(m.content) for m in glob_p])
it = Inter(BEN, GR, SP, pans[1], BOT)
DITS.clear()
lancer(COG.choisir(it, BEN.id, "ibenhaastrup"))
lien_b = [m for m in SP.messages if gl.est_message_identite(m, MOI.id, "ibenhaastrup", BEN.id)]
check("dossier partage : le second VA cree SON lien depuis SON panneau",
      ETAT["creer"][-1] == (BEN.id, "ibenhaastrup", BEN.id) and len(lien_b) == 1
      and lien_b[0].vue.children[0].label == "Ibenhaastrup · ben" and DITS == [], (ETAT["creer"][-1:], DITS))
n_creer = len(ETAT["creer"])
it = Inter(BEN, GR, SP, pans[0], BOT)
DITS.clear()
lancer(COG.choisir(it, ANA.id, "ibenhaastrup"))
check("dossier partage : le menu de l'autre VA est refuse, avec la raison",
      len(ETAT["creer"]) == n_creer and DITS and "menu" in DITS[0], DITS)
SP.overwrites.pop(BEN)
lancer(COG.assurer_panneau(SP))
check("un VA retire du dossier : son panneau part, l'autre perd le nom (salon a un seul VA)",
      [gl.uid_du_panneau(m, MOI.id) for m in SP.messages if gl.est_panneau(m, MOI.id)] == [ANA.id]
      and textes(next(m for m in SP.messages if gl.est_panneau(m, MOI.id)).vue) == [gl.texte_compteur(ETAT["actifs"])],
      [textes(m.vue) for m in SP.messages if gl.est_panneau(m, MOI.id)])

# message « 🌐 Global » : adresse changee -> repostee
SR = Salon("ben-generateur-de-lien", GR, CATR, {BEN: Ow(), MOI: Ow()})
lancer(COG.assurer_panneau(SR))
ETAT["globaux"][str(BEN.id)]["public_url"] = "https://getmysocial.com/benneuf"
lancer(COG.assurer_panneau(SR))
gb = [m for m in SR.messages if gl.est_message_global(m, MOI.id, BEN.id)]
check("global dont l'adresse a change : l'ancien message part, le nouveau arrive",
      [m.content for m in gb] == ["https://getmysocial.com/benneuf"], [m.content for m in gb])
ed = len(SR.messages)
lancer(COG.assurer_panneau(SR))
check("… et rien ne bouge au passage suivant", len(SR.messages) == ed and
      [m.content for m in SR.messages if gl.est_message_global(m, MOI.id, BEN.id)]
      == ["https://getmysocial.com/benneuf"])

# adresse d'une page changee dans GetMySocial, pages a rebrancher : l'entretien suit
reg_ = {"liens": {f"{BEN.id}:ibenhaastrup": {"link_id": "lnk_ib", "identite": "ibenhaastrup", "etat": "ok",
                                              "public_url": "https://getmysocial.com/ibenneuf",
                                              "quand": int(time.time())}}}
lu.REGISTRE.write_text(json.dumps(reg_))
ETAT["actualiser_rend"] = {str(BEN.id): {"adresses": ["ibenhaastrup"], "a_rebrancher": ["themikkiangel"]}}
n_creer = len(ETAT["creer"])
lancer(COG.assurer_panneau(SR))
ETAT["actualiser_rend"] = {}
li = [m for m in SR.messages if gl.est_message_identite(m, MOI.id, "ibenhaastrup", BEN.id)]
check("entretien : l'adresse changee d'une page est repostee",
      [m.content for m in li] == ["https://getmysocial.com/ibenneuf"], [m.content for m in li])
check("entretien : les pages a rebrancher le sont, sans clic du VA",
      ETAT["creer"][n_creer:] == [(BEN.id, "themikkiangel", "entretien")], ETAT["creer"][n_creer:])
check("entretien : liste GetMySocial lue une fois, actualiser sans appel de plus",
      BEN.id in ETAT.get("actualises", []))

# global remplace par l'admin : les pages donnees sont rebranchees tout de suite
ETAT["definir_rend"] = {"ok": True, "erreur": "", "global": {
    "link_id": "lnk_gb2", "shortcode": "bendeux", "nom": "(Ben) 2", "public_url": "https://getmysocial.com/bendeux"},
    "remplace": {"nom": "(Ben) 1"}, "a_rebrancher": ["ibenhaastrup", "themikkiangel"]}
PR = next(m for m in SR.messages if gl.est_panneau(m, MOI.id))
it = Inter(ADMIN, GR, SR, PR, BOT)
n_creer = len(ETAT["creer"])
lancer(COG.definir(it, BEN.id, "bendeux"))
check("global remplace : chaque page donnee rebranchee aussitot (creer_pour_identite, par l'admin)",
      ETAT["creer"][n_creer:] == [(BEN.id, "ibenhaastrup", ADMIN_ID), (BEN.id, "themikkiangel", ADMIN_ID)],
      ETAT["creer"][n_creer:])
check("… et l'admin le lit", "2/2 page(s) d'identité rebranchée(s)" in it.followup.envoyes[-1][0],
      it.followup.envoyes[-1:])
ETAT["definir_rend"] = None

# global d'un VA parti : repris apres verification aupres de Discord
PARTI = "910000000000000099"


def _def_reprise(uid, valeur, par, partis):
    if not partis:
        return {"ok": False, "erreur": "« (Moan) 1 » est déjà le lien global d'un autre VA",
                "autre_uid": PARTI}
    return {"ok": True, "erreur": "", "repris_de": PARTI, "pages_du_parti": 2,
            "global": {"link_id": "lnk_moan", "shortcode": "moanjessye", "nom": "(Moan) 1",
                       "public_url": "https://getmysocial.com/moanjessye"}}


ETAT["definir_fn"] = _def_reprise
it = Inter(ADMIN, GR, SR, PR, BOT)
lancer(COG.definir(it, BEN.id, "moanjessye"))
check("global d'un VA parti (Discord : membre inconnu) : repris, et dit a l'admin",
      ETAT["definir"][-1] == (BEN.id, "moanjessye", ADMIN_ID, [PARTI])
      and GR.fetches == [int(PARTI)] and it.followup.envoyes[-1][0].startswith("✅")
      and "parti" in it.followup.envoyes[-1][0], (ETAT["definir"][-2:], it.followup.envoyes[-1:]))
GR.members.append(Membre(int(PARTI), "toujourslà"))
it = Inter(ADMIN, GR, SR, PR, BOT)
n_def = len(ETAT["definir"])
lancer(COG.definir(it, BEN.id, "moanjessye"))
check("… mais pas celui d'un VA toujours membre : refus tel quel",
      len(ETAT["definir"]) == n_def + 1 and it.followup.envoyes[-1][0].startswith("❌"))
ETAT["definir_fn"] = None

# global retire de l'equipe : panneau en attente
ETAT["globaux_absents"] = {str(BEN.id)}
v = COG.vue_pour(BEN.id, GR, ETAT["liens"])
check("global retire de JESSY LE RETOUR : menu grise « En attente du lien global »",
      [(x.placeholder, x.disabled) for x in menus(v)] == [(gl.INTITULE_VERROU, True)])
v = COG.vue_pour(BEN.id, GR, None)
check("… sans liste (GetMySocial muet), on ne verrouille pas sur un doute",
      [x.disabled for x in menus(v)] == [False])
ETAT["globaux_absents"] = set()

# un panneau reconstruit de son message garde chiffre, coches, nom
v0 = gl.vue_panneau(ANA.id, 7, True, [("ibenhaastrup", "🥇 Iben", None, True),
                                      ("themikkiangel", "Mikki", None, False)], nom="ana")
m0 = Message(SP, MOI, None, v0)
v1 = gl.vue_du_message(ANA.id, m0)
check("vue_du_message : la meme empreinte (chiffre, options, coches, nom)",
      v1 is not None and gl.empreinte_vue(v1) == gl.empreinte_message(m0))

print(f"\n{len(OK)} ok, {len(KO)} en echec")
for k in KO:
    print("  ECHEC :", k)
sys.exit(1 if KO else 0)
