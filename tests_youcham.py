"""YouCham, second serveur US, branché « tout comme Youl4b ».

Propriétaire, 30/10/2026 : « oui vas-y branche tout comme youl4b ». YouCham
(1565640097146347533) a recopié les rôles et les salons communs de Youl4b,
sans les dossiers des VA, ni « proxy », ni « base ». Avant ce branchement, un
VA qui y arrivait recevait le ticket VA CLASSIQUE (setup_va_ticket) au lieu
de son dossier perso (create_us_tickets).

Ce que ce fichier prouve, avec de faux objets Discord (aucun réseau, rien
d'écrit dans data/) :
  1. YouCham est un serveur US ; Youl4b l'est toujours ; les autres non.
  2. Un membre qui arrive sur YouCham passe par create_us_tickets, jamais par
     le parcours classique -- même s'il est déjà VA ailleurs (fiche users.json).
  3. create_us_tickets crée son dossier sur YouCham comme sur Youl4b.
  4. Chaque module étendu accepte YouCham : générateur de lien,
     téléchargement (entretien + /menudownload), spoofer, menu Jailbreak,
     alerte des 500 salons.
  5. Chaque module gardé à Youl4b seul refuse ou ignore YouCham :
     bases-identites, ProxEasy, alerte staff des numéros, Infloww, sessions
     vocales, bangers et all-banger.
  6. Youl4b ne change pas ; l'archive commune du téléchargement (Download
     des tickets TRUST INSTAGRAM, outils_tickets) reste Youl4b, et tout nom
     de cogs.telechargement lu par un autre module existe.
  7. Sur un serveur US, vasort et vaactivity ne prennent aucun salon va-…
     pour celui d'un VA (va-managers, vu par Rem administrateur sur YouCham).

Lancer depuis la racine du dépôt : python tests_youcham.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


YOUL4B = 1535758943324999711
YOUCHAM = 1565640097146347533
VA_IG = 1505418484052394004
TWITTER = 1445108485090971710

# Rien de ce fichier ne doit écrire dans le vrai data/ : on relève ce qui y
# est avant, et on compare à la fin.
DATA = BOT / "data"


def _instantane():
    if not DATA.exists():
        return {}
    return {str(p.relative_to(DATA)): p.stat().st_mtime_ns
            for p in DATA.rglob("*") if p.is_file()}


AVANT = _instantane()


# ─────────────────────────────────────────────────────── faux Discord ──

class Role:
    def __init__(self, i, name="@everyone"):
        self.id, self.name = i, name

    def __hash__(self):
        return hash(("role", self.id))


class Membre:
    def __init__(self, uid, name, guild=None, bot=False):
        self.id, self.name, self.bot, self.guild = uid, name, bot, guild
        self.roles = []
        self.display_name = name

    def __hash__(self):
        return hash(("membre", self.id))

    def __eq__(self, o):
        return isinstance(o, Membre) and o.id == self.id


class Salon:
    _n = 1000

    def __init__(self, guild, name, category=None):
        Salon._n += 1
        self.id, self.name, self.guild = Salon._n, name, guild
        self.category = category
        self.category_id = getattr(category, "id", None)
        self.position = Salon._n
        self.overwrites = {}

    async def pins(self):
        return []

    async def move(self, **kw):
        cat = kw.get("category")
        if cat is not None:
            self.category, self.category_id = cat, cat.id


class Categorie(Salon):
    pass


class Guilde:
    def __init__(self, gid, name):
        self.id, self.name = gid, name
        self.unavailable = False
        self.default_role = Role(gid)
        self.me = Membre(1, "Ryuk.exe", self, bot=True)
        self.categories, self.text_channels, self.members = [], [], []
        self.channels = []
        self.crees = []

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)

    async def create_category(self, name, overwrites=None, reason=""):
        c = Categorie(self, name)
        c.overwrites = overwrites or {}
        self.categories.append(c)
        self.channels.append(c)
        self.crees.append(("categorie", name))
        return c

    async def create_text_channel(self, name, category=None, overwrites=None, reason=""):
        c = Salon(self, name, category)
        c.overwrites = overwrites or {}
        self.text_channels.append(c)
        self.channels.append(c)
        self.crees.append(("salon", name))
        return c


def courir(coro):
    return asyncio.run(coro)


# ════════════════════════════════════════ 1. la liste des serveurs US ══
print("1. Serveurs US")
import guild_features as gf  # noqa: E402

check("YouCham est un serveur US (id entier, texte, objet)",
      gf.is_us_guild(YOUCHAM) and gf.is_us_guild(str(YOUCHAM))
      and gf.is_us_guild(types.SimpleNamespace(id=YOUCHAM)))
check("Youl4b reste un serveur US", gf.is_us_guild(YOUL4B))
check("Va IG, Twitter et rien ne sont pas US",
      not any(gf.is_us_guild(g) for g in (VA_IG, TWITTER, None, 0, "x")))
check("is_youl4b : Youl4b seul",
      gf.is_youl4b(YOUL4B) and not gf.is_youl4b(YOUCHAM) and not gf.is_youl4b(None))
check("une seule liste : US_GUILD_IDS = clés de US_GUILDS",
      gf.US_GUILD_IDS == set(gf.US_GUILDS) == {str(YOUL4B), str(YOUCHAM)}, gf.US_GUILDS)
check("libellé des refus : « Youl4b, YouCham »", gf.noms_us() == "Youl4b, YouCham", gf.noms_us())

# Aucun module ne recopie l'id de YouCham : il ne vit que dans guild_features.
_copies = []
for p in list(BOT.glob("*.py")) + list((BOT / "cogs").glob("*.py")):
    if p.name.startswith("tests_") or p.name == "guild_features.py":
        continue
    try:
        if str(YOUCHAM) in p.read_text(encoding="utf-8", errors="replace"):
            _copies.append(p.name)
    except Exception:
        pass
check("l'id de YouCham n'est recopié dans aucun module", not _copies, _copies)


# ═════════════════════════════════════════ 2. l'arrivée d'un membre ══
print("2. Arrivée d'un membre")
import cogs.welcome as w  # noqa: E402

appels = []


async def _faux_us(guild, member, bot=None):
    appels.append(("us", guild.id, member.id))
    return [], []


async def _faux_classique(guild, member, bot=None, isoler=True):
    appels.append(("classique", guild.id, member.id))
    return None, "faux"


class FauxCog:
    bot = None

    async def _accueillir(self, member, cfg):
        appels.append(("accueillir", member.guild.id, member.id))


_sauve_w = {k: getattr(w, k) for k in ("create_us_tickets", "setup_va_ticket", "load_pending",
                                       "save_pending", "load_welcome_config", "load_users",
                                       "_verif_porte", "_verif_config")}
try:
    w.create_us_tickets = _faux_us
    w.setup_va_ticket = _faux_classique
    w.load_pending = lambda: {}
    w.save_pending = lambda d: appels.append(("save_pending",))
    w.load_welcome_config = lambda: {"auto_create_ticket_on_join": True}
    # un VA DEJA VA ailleurs : sa fiche vise un salon d'un autre serveur
    w.load_users = lambda: {"77": {"channel_id": 123, "identity": "julia"}}
    w._verif_porte = lambda g: None
    w._verif_config = lambda g: None

    def arrivee(gid, uid=77):
        appels.clear()
        g = Guilde(gid, "x")
        m = Membre(uid, "nouveau_va", g)
        courir(w.Welcome.on_member_join(FauxCog(), m))
        return list(appels)

    a = arrivee(YOUCHAM)
    check("YouCham : l'arrivée passe par create_us_tickets", a == [("us", YOUCHAM, 77)], a)
    check("YouCham : ni ticket classique ni _accueillir",
          not any(x[0] in ("classique", "accueillir") for x in a), a)
    check("YouCham : un VA déjà VA sur un autre serveur a son dossier quand même "
          "(le refus « déjà VA sur … » est dans setup_va_ticket, jamais atteint)",
          ("us", YOUCHAM, 77) in a, a)
    a = arrivee(YOUL4B)
    check("Youl4b inchangé : create_us_tickets", a == [("us", YOUL4B, 77)], a)
    a = arrivee(TWITTER)
    check("un autre serveur garde le parcours classique (_accueillir)",
          a == [("accueillir", TWITTER, 77)], a)
    bot_m = Membre(78, "unbot", Guilde(YOUCHAM, "x"), bot=True)
    appels.clear()
    courir(w.Welcome.on_member_join(FauxCog(), bot_m))
    check("YouCham : un bot qui arrive n'a rien", not appels, appels)
finally:
    for k, v in _sauve_w.items():
        setattr(w, k, v)


# ═══════════════════════════════ 3. le dossier créé, comme sur Youl4b ══
print("3. Dossier perso")
poses = []


def _pose(nom):
    async def f(bot, ch, *a, **k):
        poses.append((nom, ch.guild.id, ch.name))
        return True
    return f


_sauve_d = {k: getattr(w, k) for k in ("_ensure_us_menu", "_ensure_num_panel", "_ensure_dl_panel",
                                       "_ensure_spoof_panel", "_ensure_gdl_panel", "gdl_ouvert",
                                       "_membre_bot_admin")}
try:
    w._ensure_us_menu = _pose("menu")
    w._ensure_num_panel = _pose("numero")
    w._ensure_dl_panel = _pose("download")
    w._ensure_spoof_panel = _pose("spoofer")
    w._ensure_gdl_panel = _pose("gdl")
    w.gdl_ouvert = lambda base: False          # comme en prod : essai seulement
    w._membre_bot_admin = lambda g: None

    def dossier(gid):
        poses.clear()
        g = Guilde(gid, "x")
        m = Membre(55, "roucham_79944", g)
        g.members.append(m)
        cr, err = courir(w.create_us_tickets(g, m, bot=None))
        return g, cr, err

    gY, crY, errY = dossier(YOUCHAM)
    noms_y = [c.name for c in gY.text_channels]
    attendus = ["roucham_79944-" + s for s in ("menu", "spoofer", "download", "numero-mail", "content")]
    check("YouCham : un dossier (catégorie) au pseudo", gY.crees[0] == ("categorie", "roucham_79944"),
          gY.crees)
    check("YouCham : les 5 salons du dossier, dans l'ordre", noms_y == attendus, noms_y)
    check("YouCham : aucun -generateur-de-lien (essai fermé)",
          not any(n.endswith("generateur-de-lien") for n in noms_y), noms_y)
    check("YouCham : aucune erreur", not errY, errY)
    check("YouCham : menu, numéro, download et spoofer posés",
          sorted(p[0] for p in poses) == ["download", "menu", "numero", "spoofer"], poses)
    menu = gY.text_channels[0]
    ow = menu.overwrites
    check("YouCham : -menu privé (@everyone ne voit pas) et en lecture seule pour le VA",
          ow[gY.default_role].view_channel is False
          and ow[gY.members[0]].view_channel is True and ow[gY.members[0]].send_messages is False)
    gL, crL, errL = dossier(YOUL4B)
    check("Youl4b : le même dossier, salon pour salon",
          [c.name for c in gL.text_channels] == noms_y and gL.crees == gY.crees)
finally:
    for k, v in _sauve_d.items():
        setattr(w, k, v)


# ═══════════════════════════════════════════ 4. les modules étendus ══
print("4. Modules étendus à YouCham")

# Générateur de lien par identité
import cogs.generateur_lien as gl  # noqa: E402

check("générateur : YouCham accepté", gl.serveur_ok(Guilde(YOUCHAM, "YouCham")))
check("générateur : Youl4b accepté", gl.serveur_ok(Guilde(YOUL4B, "Youl4b")))
check("générateur : Va IG, Twitter et sans serveur refusés",
      not gl.serveur_ok(Guilde(VA_IG, "Va IG")) and not gl.serveur_ok(Guilde(TWITTER, "tw"))
      and not gl.serveur_ok(None))
check("générateur : plus de constante de serveur à lui (une seule liste)",
      not hasattr(gl, "GUILD_ID_DEFAUT") and not hasattr(gl, "guild_id"))
import liens_identite_us as lius  # noqa: E402
check("liens_identite_us : plus d'id de serveur recopié", not hasattr(lius, "GUILD_ID"))

# Téléchargement
import cogs.telechargement as tl  # noqa: E402

check("téléchargement : les deux serveurs US, Youl4b d'abord",
      tl.SERVEURS_IDS == (YOUL4B, YOUCHAM), tl.SERVEURS_IDS)
_gids_cmd = sorted(getattr(tl.Telechargement.menudownload, "_guild_ids", None) or [])
check("/menudownload : proposée sur Youl4b et YouCham (commande de serveur)",
      _gids_cmd == [YOUL4B, YOUCHAM], _gids_cmd)
_avant_env = os.environ.get("IG_SERVEUR_ID")
os.environ["IG_SERVEUR_ID"] = "42"
check("IG_SERVEUR_ID posé : un seul serveur, comme avant", tl._serveurs_download() == (42,))
if _avant_env is None:
    os.environ.pop("IG_SERVEUR_ID", None)
else:
    os.environ["IG_SERVEUR_ID"] = _avant_env
check("IG_SERVEUR_ID absent : la liste US", tl._serveurs_download() == (YOUL4B, YOUCHAM))

menages = []


async def _faux_menage(cog, guilde):
    menages.append(guilde.id)
    if guilde.id == YOUCHAM:
        raise RuntimeError("panne YouCham")
    return 2


class _BotTl:
    def __init__(self, guildes):
        self._g = {g.id: g for g in guildes}

    def get_guild(self, gid):
        return self._g.get(gid)


_sauve_menage = tl.remettre_au_propre
try:
    tl.remettre_au_propre = _faux_menage
    fx = types.SimpleNamespace(bot=_BotTl([Guilde(YOUL4B, "Youl4b"), Guilde(YOUCHAM, "YouCham"),
                                           Guilde(VA_IG, "Va IG")]))
    courir(tl.Telechargement._entretien.coro(fx))
    check("téléchargement : ménage quotidien sur Youl4b ET YouCham, pas sur Va IG",
          menages == [YOUL4B, YOUCHAM], menages)
    menages.clear()
    fx = types.SimpleNamespace(bot=_BotTl([Guilde(YOUCHAM, "YouCham")]))
    courir(tl.Telechargement._entretien.coro(fx))
    check("téléchargement : Youl4b absent du bot, YouCham fait quand même",
          menages == [YOUCHAM], menages)
finally:
    tl.remettre_au_propre = _sauve_menage


class _SalonAD:
    def __init__(self, name):
        self.name = name


gY = Guilde(YOUCHAM, "YouCham")
gY.text_channels = [_SalonAD("⬇️・all-download")]
check("archive : un envoi de YouCham va dans le all-download de YouCham",
      tl.salon_all_download(gY) is gY.text_channels[0])

# Spoofer : l'entretien parcourt les serveurs US
import cogs.spoofer as spf  # noqa: E402

vus_spf = []


class _FauxSpf:
    def __init__(self, guildes):
        self.bot = types.SimpleNamespace(guilds=guildes)

    async def _prevenir_interrompus(self):
        return None

    async def _provisionner(self, guilde):
        vus_spf.append(guilde.id)
        return 0

    async def assurer_panneau(self, canal):
        return 0


_sauve_cdu = w.completer_dossiers_us


async def _faux_cdu(guilde, suffixes=("spoofer",)):
    return {"crees": [], "sans_va": [], "erreurs": []}


try:
    w.completer_dossiers_us = _faux_cdu
    courir(spf.Spoofer._entretien.coro(_FauxSpf([Guilde(YOUL4B, "a"), Guilde(YOUCHAM, "b"),
                                                 Guilde(VA_IG, "c")])))
finally:
    w.completer_dossiers_us = _sauve_cdu
check("spoofer : entretien sur Youl4b et YouCham, pas sur Va IG",
      vus_spf == [YOUL4B, YOUCHAM], vus_spf)

# Menu Jailbreak US ouvert à tous
import cogs.user as u  # noqa: E402

check("menu Jailbreak : ouvert à tous sur YouCham comme sur Youl4b",
      u._jb_can_use(types.SimpleNamespace(guild=Guilde(YOUCHAM, "y"), user=None))
      and u._jb_can_use(types.SimpleNamespace(guild=Guilde(YOUL4B, "l"), user=None)))

# Alerte des 500 salons
import alertes_echeances as ae  # noqa: E402

check("500 salons : YouCham surveillé, Youl4b garde son nom « Spam »",
      ae.SERVEURS_SALONS == {str(YOUL4B): "Spam", str(YOUCHAM): "YouCham"}, ae.SERVEURS_SALONS)
check("500 salons : pas d'amorce pour YouCham", str(YOUCHAM) not in ae.AMORCE_SALONS)
etat = {"envoyees": {}, "historique": {}}
mes = {"serveurs": {str(YOUL4B): {"nom": "Youl4b ( Spam )", "salons": 432},
                    str(YOUCHAM): {"nom": "YouCham", "salons": 455}}}
neuves, rearmer = ae.evaluer(mes, etat, 1_800_000_000)
check("500 salons : YouCham à 455 sonne, Youl4b à 432 non",
      [c for c, _ in neuves] == [f"salons:{YOUCHAM}"] and "YouCham" in neuves[0][1], neuves)
etat = {"envoyees": {f"salons:{YOUL4B}": 1}, "historique": {}}
mes["serveurs"][str(YOUL4B)]["salons"] = 460
neuves, _r = ae.evaluer(mes, etat, 1_800_000_000)
check("500 salons : deux serveurs = deux événements (pas de doublon, pas d'oubli)",
      [c for c, _ in neuves] == [f"salons:{YOUCHAM}"], neuves)


# ═══════════════════════════════════════ 5. gardés à Youl4b seul ══
print("5. Gardés à Youl4b seul")
import cogs.bases_identite as bi  # noqa: E402

check("bases-identites : Youl4b oui, YouCham non",
      bi._serveur_us(Guilde(YOUL4B, "l")) and not bi._serveur_us(Guilde(YOUCHAM, "y")))

salons_assures = []


class _FauxBi:
    def __init__(self, guildes):
        self.bot = types.SimpleNamespace(guilds=guildes)
        self.repris = set()
        self._entretien = types.SimpleNamespace(is_running=lambda: False)

    async def assurer_salon(self, guilde):
        salons_assures.append(guilde.id)
        return None                               # rien d'autre à faire ici


courir(bi.BasesIdentite._entretien.coro(_FauxBi([Guilde(YOUL4B, "l"), Guilde(YOUCHAM, "y")])))
check("bases-identites : l'entretien ne crée AUCUN salon sur YouCham",
      salons_assures == [YOUL4B], salons_assures)

import proxeasy  # noqa: E402
check("ProxEasy : Youl4b seul (YouCham n'a pas de catégorie proxy)",
      proxeasy.SERVEUR == str(YOUL4B))
import numgen  # noqa: E402
check("alerte staff des numéros : le debrief-day de Youl4b seul",
      numgen.ALERTES_SALON == "1553627411680338153")
import infloww_liens as il  # noqa: E402
check("inflow-resultat : Youl4b seul (Bixby absent de YouCham, envoi coupé)",
      il.GUILD == str(YOUL4B))
import sessions_voc as sv  # noqa: E402
check("sessions vocales : Youl4b seul (bilan commun ou par serveur : à trancher)",
      sv.SUIVI_GUILD_ID == YOUL4B)
import bangers as bg  # noqa: E402
import all_banger as ab  # noqa: E402
check("bangers : Youl4b seul (une fiche = une annonce : à trancher)",
      bg.GUILD_ID == YOUL4B and bg.salon_us()["guild_id"] == YOUL4B
      and all(int(s["guild_id"]) != YOUCHAM for s in bg.salons()))
check("all-banger : le marché us reste sur Youl4b", ab.guild_du_marche("us") == YOUL4B)


# ═══════════════════════════════════════════ 6. Youl4b inchangé ══
print("6. Youl4b inchangé")
check("Youl4b : SERVEUR_SPAM et sa clé d'alerte inchangés",
      ae.SERVEUR_SPAM == str(YOUL4B) and ae.AMORCE_SALONS[str(YOUL4B)] == ("2026-10-20", 381))
etat = {"envoyees": {}, "historique": {}}
mes = {"serveurs": {str(YOUL4B): {"salons": 451}}}
neuves, _r = ae.evaluer(mes, etat, 1_800_000_000)
check("Youl4b : à 451, l'alerte « Spam » comme avant",
      [c for c, _ in neuves] == [f"salons:{YOUL4B}"] and "« Spam »" in neuves[0][1], neuves)
# L'archive COMMUNE (Download des tickets TRUST INSTAGRAM, outils_tickets)
# reste celle de Youl4b. Le 1er jet de ce branchement avait retiré
# tl.SERVEUR_ID : le rebase sur 38966c2 passait sans conflit, et ce Download
# levait AttributeError avant la livraison, sans rien d'autre qu'une ligne
# au journal.
check("téléchargement : SERVEUR_ID = l'archive commune, Youl4b",
      getattr(tl, "SERVEUR_ID", None) == YOUL4B, getattr(tl, "SERVEUR_ID", "absent"))
os.environ["IG_SERVEUR_ID"] = "42"
check("téléchargement : IG_SERVEUR_ID remplace aussi l'archive commune (essai)",
      getattr(tl, "_serveur_archive_commune", lambda: None)() == 42)
if _avant_env is None:
    os.environ.pop("IG_SERVEUR_ID", None)
else:
    os.environ["IG_SERVEUR_ID"] = _avant_env
check("téléchargement : sans IG_SERVEUR_ID, l'archive commune revient à Youl4b",
      getattr(tl, "_serveur_archive_commune", lambda: None)() == YOUL4B)

# Tout module qui lit cogs.telechargement sous un alias n'y lit que des noms
# qui existent : un nom retiré casse un autre module EN SILENCE (un import
# paresseux dans une fonction, appelée au clic d'un VA).
import re as _re  # noqa: E402
_absents = []
for p in list(BOT.glob("*.py")) + list((BOT / "cogs").glob("*.py")):
    if p.name == "telechargement.py":
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    alias = set(_re.findall(r"(?:from cogs import (?:\w+, )*telechargement as (\w+))"
                            r"|(?:import cogs\.telechargement as (\w+))", txt))
    for a in {x for paire in alias for x in paire if x}:
        for nom in set(_re.findall(r"\b" + _re.escape(a) + r"\.([A-Za-z_]\w*)", txt)):
            if not hasattr(tl, nom):
                _absents.append(f"{p.name}: {a}.{nom}")
    for nom in _re.findall(r"from cogs\.telechargement import ([\w, ]+)", txt):
        for n in (x.strip() for x in nom.split(",")):
            if n and not hasattr(tl, n):
                _absents.append(f"{p.name}: {n}")
check("téléchargement : chaque nom lu par un autre module existe "
      "(outils_tickets, spoofer, outils, user, welcome, tests)", not _absents, _absents)
check("téléchargement : outils_tickets lit bien tl.SERVEUR_ID (sinon ce test ne prouve rien)",
      "tl.SERVEUR_ID" in (BOT / "outils_tickets.py").read_text(encoding="utf-8"))


# ═══════════════════════════════ 7. va-managers n'est pas un VA (US) ══
# 30/10/2026, observé sur YouCham : Rem y est administrateur, il voit donc
# va-managers (pas sur Youl4b). vasort y a posé « ──😴-sans-lien » (09:01,
# puis 09:41 après suppression) et vaactivity a renommé le salon
# « 🔴-va-managers ». Sur un serveur US, un VA a un dossier <pseudo>-menu,
# jamais de salon va-<pseudo>.
print("7. Tri et ronds des salons va- : rien sur un serveur US")
import cogs.vasort as vs  # noqa: E402
import cogs.vaactivity as va  # noqa: E402


class _Http:
    def __init__(self):
        self.appels = []

    async def bulk_channel_update(self, gid, payload, reason=""):
        self.appels.append(payload)


class _G7:
    def __init__(self, gid):
        self.id, self.name = gid, str(gid)
        self.categories, self.text_channels, self.members = [], [], []
        self.roles, self.default_role = [], Role(gid)
        self._state = types.SimpleNamespace(http=_Http())
        self.crees, self.supprimes, self.renommes = [], [], []

    async def create_text_channel(self, name, category=None, overwrites=None, reason=""):
        self.crees.append(name)
        c = _S7(self, name, category)
        return c


class _C7:
    def __init__(self, guild, name):
        self.guild, self.name, self.text_channels = guild, name, []
        guild.categories.append(self)


class _S7:
    _n = 5000

    def __init__(self, guild, name, cat):
        _S7._n += 1
        self.id, self.name, self.guild, self.position = _S7._n, name, guild, _S7._n
        if cat is not None:
            cat.text_channels.append(self)
        guild.text_channels.append(self)

    async def delete(self, reason=""):
        self.guild.supprimes.append(self.name)
        for c in self.guild.categories:
            if self in c.text_channels:
                c.text_channels.remove(self)

    async def edit(self, name=None, reason=""):
        self.guild.renommes.append((self.name, name))
        self.name = name

    async def move(self, **kw):
        self.guild._state.http.appels.append(("move", self.name))


def _suivi(gid, avec_sep=True):
    g = _G7(gid)
    cat = _C7(g, "📊・SUIVI DES VA")
    _S7(g, "📋・suivi", cat)
    if avec_sep:
        _S7(g, vs.SEP_NONE, cat)
    _S7(g, "va-managers", cat)
    return g, cat


g7, cat7 = _suivi(YOUCHAM)
_o, _grp, _seps = vs._split(cat7)
check("vasort : va-managers n'est pas un VA sur YouCham",
      not any(_grp.values()) and "va-managers" in [c.name for c in _o], _grp)
courir(vs.sort_guild(g7))
check("vasort : sur YouCham, le séparateur déjà posé est retiré, aucun autre créé",
      g7.supprimes == [vs.SEP_NONE] and not g7.crees, (g7.supprimes, g7.crees))
check("vasort : sur YouCham, aucun salon déplacé", not g7._state.http.appels,
      g7._state.http.appels)
g7b, _ = _suivi(YOUL4B, avec_sep=False)
courir(vs.sort_guild(g7b))
check("vasort : Youl4b, rien créé ni déplacé, même si Rem y voyait un jour va-managers",
      not g7b.crees and not g7b.supprimes and not g7b._state.http.appels)
# Hors serveur US, le comportement ne change pas : un va-<x> est un VA.
g7c, cat7c = _suivi(VA_IG, avec_sep=False)
_o, _grp, _seps = vs._split(cat7c)
check("vasort : hors serveur US, un va-<x> reste un salon de VA (inchangé)",
      [c.name for c in _grp[2]] == ["va-managers"], _grp)

check("vaactivity : aucun salon va- sur YouCham ni Youl4b",
      va.VAActivity._va_channels(None, _suivi(YOUCHAM)[0]) == []
      and va.VAActivity._va_channels(None, _suivi(YOUL4B)[0]) == [])
_hors = va.VAActivity._va_channels(None, g7c)
check("vaactivity : hors serveur US, va-<x> reste un salon de VA (inchangé)",
      [(c.name, h) for c, h in _hors] == [("va-managers", "managers")], _hors)
# Le renommage lui-même, « statut » forcé actif (le bridage de YouCham dans
# data/guild_features.json du VPS ne doit pas être ce qui protège).
_enabled = gf.enabled
gf.enabled = lambda g, f: True
try:
    _obj = object.__new__(va.VAActivity)
    g7d, _ = _suivi(YOUCHAM, avec_sep=False)
    _obj.bot = types.SimpleNamespace(guilds=[g7d])
    _obj._act = {}
    _st = courir(_obj._apply_all())
finally:
    gf.enabled = _enabled
check("vaactivity : YouCham avec « statut » actif, va-managers n'est pas renommé",
      not g7d.renommes and _st.get("found") == 0, (_st, g7d.renommes))

# ═════════════════════════════════════════════════════ isolation ══
check("isolation : rien écrit ni modifié dans data/", _instantane() == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
