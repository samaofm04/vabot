"""YouCham : outils communs (menu, spoofer, download, numéro) et UN salon perso par VA.

Propriétaire, 30/10/2026, maquette validée : « sur YouCham, un salon où tout
le monde voit un menu en commun, un spoofer en commun, un download en commun,
un numéro en commun, et un content qui est leur ticket à eux, personnel »,
puis « oui vas-y construis-le sur YouCham ». Youl4b garde ses dossiers.

Ce que ce fichier prouve, avec de faux objets Discord (aucun réseau, rien
d'écrit dans le vrai data/) :
  1. La liste : guild_features.OUTILS_COMMUNS = {YouCham}, un serveur US.
  2. L'arrivée sur YouCham : UN salon <pseudo>-content dans 📁 SALONS PERSO
     (privé, rangé par pseudo, débordement à 50) ; Youl4b : toujours 5 salons.
  3. 🧰 OUTILS : quatre salons en lecture seule, créés une fois, panneaux
     posés une fois (bouton du menu persistant).
  4. Chaque outil livre dans le -content du CLIQUEUR, jamais dans le salon
     commun ; deux VA reçoivent chacun chez eux ; l'identité est portée par
     le clic ; le staff sans -content est refusé en éphémère.
  5. /ticketsall sur YouCham : ni les outils ni l'archive ne sont supprimés,
     l'ancien dossier d'essai est rangé.
  6. Aucun texte ne contient « YouLab ».

Lancer depuis la racine du dépôt : python tests_youcham_outils.py
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

import discord  # noqa: E402

OKS, FAILS = [], []
TEXTES = []          # tout ce qui est dit a quelqu'un : aucun « YouLab »


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


YOUL4B = 1535758943324999711
YOUCHAM = 1565640097146347533
VA_IG = 1505418484052394004
RYUK, REM = 1505416430840189041, 1509505792666108074

DATA = BOT / "data"


def _instantane():
    if not DATA.exists():
        return {}
    return {str(p.relative_to(DATA)): p.stat().st_mtime_ns
            for p in DATA.rglob("*") if p.is_file()}


AVANT = _instantane()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="yc_outils_"))


# ─────────────────────────────────────────────────────── faux Discord ──

class _Rep404:
    status, reason = 404, "Not Found"


def _ns_composant(d):
    """Un composant tel que discord.py le rend lu d'un message (custom_id,
    children, accessory, media) a partir du dict d'une vue."""
    n = types.SimpleNamespace(custom_id=d.get("custom_id"), type=d.get("type"))
    enfants = [_ns_composant(x) for x in d.get("components", []) or []]
    n.children = enfants
    n.components = enfants
    if d.get("accessory"):
        n.accessory = _ns_composant(d["accessory"])
    if isinstance(d.get("media"), dict):
        n.media = types.SimpleNamespace(url=d["media"].get("url"))
    return n


class Role:
    def __init__(self, i, name="@everyone"):
        self.id, self.name = i, name

    def __hash__(self):
        return hash(("role", self.id))

    def __eq__(self, o):
        return isinstance(o, Role) and o.id == self.id


class Membre:
    def __init__(self, uid, name, guild=None, bot=False):
        self.id, self.name, self.bot, self.guild = uid, name, bot, guild
        self.roles = []
        self.display_name = name
        self.mention = f"<@{uid}>"

    def __hash__(self):
        return hash(("membre", self.id))

    def __eq__(self, o):
        return isinstance(o, Membre) and o.id == self.id


class Message:
    _n = 900000

    def __init__(self, salon, author, content=None, view=None, ephemeral=False):
        Message._n += 1
        self.id = Message._n
        self.channel, self.author, self.content = salon, author, content
        self.embeds, self.attachments = [], []
        self.flags = types.SimpleNamespace(ephemeral=ephemeral, components_v2=view is not None)
        self.vue = view
        self.components = [_ns_composant(c) for c in (view.to_components() if view else [])]
        self.supprime = False
        self.type = discord.MessageType.default

    async def delete(self, *a, **k):
        self.supprime = True
        if self.channel is not None and self in self.channel.messages:
            self.channel.messages.remove(self)

    async def edit(self, **kw):
        if kw.get("view") is not None:
            self.vue = kw["view"]
            self.components = [_ns_composant(c) for c in kw["view"].to_components()]
        self.channel.edites.append(self.id)


class Salon:
    _n = 1000

    def __init__(self, guild, name, category=None, kind="texte"):
        Salon._n += 1
        self.id, self.name, self.guild, self.kind = Salon._n, name, guild, kind
        self.category_id = getattr(category, "id", None)
        self.position = Salon._n
        self.overwrites = {}
        self.messages, self.edites = [], []
        self.last_message_id = None
        self.supprime = False

    @property
    def category(self):
        return next((c for c in self.guild._cats if c.id == self.category_id), None)

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def send(self, content=None, **kw):
        f = kw.get("file")
        if f is not None:
            try:
                f.close()
            except Exception:
                pass
        for f in kw.get("files") or []:
            try:
                f.close()
            except Exception:
                pass
        m = Message(self, self.guild.me, content, kw.get("view"))
        self.messages.append(m)
        self.last_message_id = m.id
        if content:
            TEXTES.append(str(content))
        return m

    def history(self, limit=100, **kw):
        msgs = list(reversed(self.messages))[:limit]

        async def _gen():
            for m in msgs:
                yield m
        return _gen()

    async def fetch_message(self, mid):
        for m in self.messages:
            if m.id == int(mid):
                return m
        raise discord.NotFound(_Rep404(), "Unknown Message")

    def get_partial_message(self, mid):
        salon = self

        class _P:
            async def delete(self_):
                m = await salon.fetch_message(mid)
                await m.delete()

            async def edit(self_, **kw):
                m = await salon.fetch_message(mid)
                await m.edit(**kw)
        return _P()

    async def pins(self):
        return []

    async def purge(self, limit=100, check=None, **kw):
        partis = [m for m in list(self.messages) if check is None or check(m)]
        for m in partis:
            await m.delete()
        return partis

    async def set_permissions(self, cible, overwrite=None, reason=""):
        if overwrite is None:
            self.overwrites.pop(cible, None)
        else:
            self.overwrites[cible] = overwrite

    async def delete(self, reason=""):
        self.supprime = True
        self.guild._salons.remove(self)
        self.guild.supprimes.append(self.name)

    async def move(self, **kw):
        g = self.guild
        if "category" in kw:
            self.category_id = getattr(kw["category"], "id", None)
        freres = sorted((c for c in g._salons if c.category_id == self.category_id and c is not self),
                        key=lambda c: c.position)
        if kw.get("beginning"):
            freres.insert(0, self)
        elif kw.get("after") is not None:
            freres.insert(freres.index(kw["after"]) + 1, self)
        else:
            freres.append(self)
        for i, c in enumerate(freres):
            c.position = i
        g.deplaces.append((self.name, {k: getattr(v, "name", v) for k, v in kw.items()
                                       if k != "reason"}))


class Categorie:
    _n = 500

    def __init__(self, guild, name):
        Categorie._n += 1
        self.id, self.name, self.guild = Categorie._n, name, guild
        self.position = Categorie._n
        self.overwrites = {}

    @property
    def channels(self):
        return [c for c in self.guild._salons if c.category_id == self.id]

    @property
    def text_channels(self):
        return sorted((c for c in self.channels if c.kind == "texte"), key=lambda c: c.position)

    async def delete(self, reason=""):
        self.guild._cats.remove(self)
        self.guild.supprimes.append("[cat] " + self.name)

    async def move(self, **kw):
        g = self.guild
        cats = sorted((c for c in g._cats if c is not self), key=lambda c: c.position)
        if kw.get("beginning"):
            cats.insert(0, self)
        elif kw.get("after") is not None:
            cats.insert(cats.index(kw["after"]) + 1, self)
        else:
            cats.append(self)
        for i, c in enumerate(cats):
            c.position = i
        g.deplaces.append(("[cat] " + self.name, {k: getattr(v, "name", v) for k, v in kw.items()
                                                 if k != "reason"}))


class Guilde:
    def __init__(self, gid, name):
        self.id, self.name = gid, name
        self.unavailable = False
        self.default_role = Role(gid)
        self.me = Membre(RYUK, "Ryuk.exe", self, bot=True)
        self.members, self.roles, self.emojis = [self.me], [], []
        self._cats, self._salons = [], []
        self.crees, self.supprimes, self.deplaces = [], [], []
        self.filesize_limit = 10 * 1024 * 1024

    @property
    def categories(self):
        return sorted(self._cats, key=lambda c: c.position)

    @property
    def text_channels(self):
        return sorted((c for c in self._salons if c.kind == "texte"),
                      key=lambda c: (getattr(c.category, "position", -1), c.position))

    @property
    def channels(self):
        return list(self._cats) + list(self._salons)

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return next((c for c in self._salons if c.id == cid), None)

    async def create_category(self, name, overwrites=None, reason="", **kw):
        c = Categorie(self, name)
        c.overwrites = overwrites or {}
        self._cats.append(c)
        self.crees.append(("categorie", name))
        return c

    async def create_text_channel(self, name, category=None, overwrites=None, reason="", **kw):
        if category is not None and len(category.channels) >= 50:
            raise discord.HTTPException(types.SimpleNamespace(status=400, reason="Bad Request"),
                                        "Maximum number of channels in category reached (50)")
        c = Salon(self, name, category)
        c.overwrites = overwrites or {}
        self._salons.append(c)
        self.crees.append(("salon", name))
        return c

    def ajoute(self, name, category=None, kind="texte"):
        c = Salon(self, name, category, kind)
        self._salons.append(c)
        return c

    def ajoute_cat(self, name):
        c = Categorie(self, name)
        self._cats.append(c)
        return c


class Rep:
    def __init__(self):
        self.fait, self.type = False, None
        self.envois, self.modales, self.editions = [], [], []

    def is_done(self):
        return self.fait

    async def send_message(self, content=None, **kw):
        self.fait, self.type = True, discord.InteractionResponseType.channel_message
        for f in [kw.get("file")] + list(kw.get("files") or []):
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass
        self.envois.append((content, kw))
        if content:
            TEXTES.append(str(content))

    async def defer(self, **kw):
        self.fait, self.type = True, discord.InteractionResponseType.deferred_message_update

    async def send_modal(self, modal):
        self.fait = True
        self.modales.append(modal)

    async def edit_message(self, **kw):
        self.fait, self.type = True, discord.InteractionResponseType.message_update
        self.editions.append(kw)


class Suivi:
    def __init__(self, itx):
        self.itx, self.envois, self.editions = itx, [], []

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))
        if content:
            TEXTES.append(str(content))
        return Message(self.itx.channel, self.itx.guild.me, content, kw.get("view"),
                       ephemeral=bool(kw.get("ephemeral")))

    async def edit_message(self, mid, **kw):
        self.editions.append((mid, kw))


class Client:
    def __init__(self, cogs=None):
        self.cogs = cogs or {}
        self.user = types.SimpleNamespace(id=RYUK)

    def get_cog(self, nom):
        return self.cogs.get(nom)


class Itx:
    def __init__(self, guilde, salon, user, cogs=None, message=None, ephemere=False):
        self.guild, self.channel, self.user = guilde, salon, user
        self.client = Client(cogs)
        self.response = Rep()
        self.followup = Suivi(self)
        self.message = message or Message(salon, guilde.me, ephemeral=ephemere)
        self.data = {}
        self.filesize_limit = 10 * 1024 * 1024
        self.originale = None

    async def original_response(self):
        self.originale = Message(self.channel, self.guild.me, ephemeral=True)
        return self.originale


def courir(coro):
    return asyncio.run(coro)


def _ids(vue):
    return [getattr(c, "custom_id", None) for c in vue.walk_children()
            if getattr(c, "custom_id", None)]


async def _instant(*a, **k):
    return None


import guild_features as gf  # noqa: E402
import outils_communs as oc  # noqa: E402
import cogs.welcome as w  # noqa: E402

oc.ETAT = TMP / "outils_communs.json"


def youcham(n_va=2, avec_outils=True):
    """YouCham tel qu'il est le 30/10 (catégories communes, all-download),
    plus `n_va` VA déjà arrivés et, si demandé, 🧰 OUTILS posé."""
    g = Guilde(YOUCHAM, "YouCham")
    txt = g.ajoute_cat("Salons textuels")
    g.archive = g.ajoute("⬇️・all-download", txt)
    g.ajoute("général", txt)
    g.rem = Membre(REM, "Rem", g, bot=True)
    g.members.append(g.rem)
    g.vas = []
    for i in range(n_va):
        m = Membre(7000 + i, f"va_{chr(97 + i)}", g)
        g.members.append(m)
        g.vas.append(m)
    g.staff = Membre(6000, "boss_staff", g)
    g.members.append(g.staff)
    if avec_outils:
        cat = g.ajoute_cat(oc.CATEGORIE)
        g.outils = {cle: g.ajoute(nom, cat) for cle, nom in oc.SALONS}
    return g


# ════════════════════════════════════════════════ 1. la liste ══
print("1. La liste des serveurs aux outils communs")
check("OUTILS_COMMUNS = {YouCham}, sous-ensemble des serveurs US",
      gf.OUTILS_COMMUNS == {str(YOUCHAM)} and gf.OUTILS_COMMUNS <= gf.US_GUILD_IDS)
check("YouCham oui (id entier, texte, objet) ; Youl4b, Va IG et rien non",
      gf.outils_communs(YOUCHAM) and gf.outils_communs(str(YOUCHAM))
      and gf.outils_communs(types.SimpleNamespace(id=YOUCHAM))
      and not any(gf.outils_communs(x) for x in (YOUL4B, VA_IG, None, 0, "x")))
check("suffixes : -content seul sur YouCham, dossier complet sur Youl4b",
      w.suffixes_us(Guilde(YOUCHAM, "y")) == ("content",)
      and w.suffixes_us(Guilde(YOUL4B, "l")) == w.US_TICKET_SUFFIXES)
check("Youl4b garde ses 5 salons (+ le générateur) dans le tuple",
      w.US_TICKET_SUFFIXES[:5] == ("menu", "spoofer", "download", "numero-mail", "content"))
_src_oc = (BOT / "outils_communs.py").read_text(encoding="utf-8")
check("outils_communs ne recopie pas l'id de YouCham", str(YOUCHAM) not in _src_oc)


# ═══════════════════════════════════════════ 2. l'arrivée d'un VA ══
print("2. Arrivée : un salon -content, rangé, privé")
poses = []


def _pose(nom):
    async def f(bot, ch, *a, **k):
        poses.append((nom, ch.name))
        return True
    return f


_sauve_d = {k: getattr(w, k) for k in ("_ensure_us_menu", "_ensure_num_panel", "_ensure_dl_panel",
                                       "_ensure_spoof_panel", "_ensure_gdl_panel", "gdl_ouvert",
                                       "_membre_bot_admin", "load_pending", "save_pending",
                                       "load_welcome_config")}
_sleep = asyncio.sleep
try:
    for k in ("_ensure_us_menu", "_ensure_num_panel", "_ensure_dl_panel", "_ensure_spoof_panel",
              "_ensure_gdl_panel"):
        setattr(w, k, _pose(k))
    w.gdl_ouvert = lambda base: False
    w._membre_bot_admin = lambda g: getattr(g, "rem", None)
    w.load_pending = lambda: {}
    w.save_pending = lambda d: None
    w.load_welcome_config = lambda: {"auto_create_ticket_on_join": True}
    asyncio.sleep = _instant

    class _FauxWelcome:
        bot = None

        async def _accueillir(self, member, cfg):
            poses.append(("accueillir", member.name))

    g = youcham(n_va=0)
    nouveau = Membre(7100, "roucham_79944", g)
    g.members.append(nouveau)
    courir(w.Welcome.on_member_join(_FauxWelcome(), nouveau))
    crees = [x for x in g.crees]
    perso = [c for c in g.categories if oc.est_categorie_perso(c)]
    ct = oc.content_de(g, nouveau)
    check("YouCham : l'arrivée crée UNE catégorie 📁 SALONS PERSO et UN salon",
          crees == [("categorie", "📁 SALONS PERSO"), ("salon", "roucham_79944-content")], crees)
    check("le salon s'appelle <pseudo>-content (nom de _us_ticket_name) et vit dans SALONS PERSO",
          ct is not None and ct.name == w._us_ticket_name(nouveau, "content")
          and ct.category is perso[0], getattr(ct, "name", None))
    check("aucun panneau posé à l'arrivée (ni menu, ni numéro, ni spoofer, ni download)",
          not poses, poses)
    ow = ct.overwrites
    check("privé : @everyone ne voit pas ; le VA voit, écrit, joint",
          ow[g.default_role].view_channel is False and ow[nouveau].view_channel is True
          and ow[nouveau].send_messages is True and ow[nouveau].attach_files is True)
    check("Ryuk et Rem y ont leur règle (Rem y écrit la carte du numéro)",
          ow[g.me].send_messages is True and ow[g.rem].send_messages is True
          and ow[g.rem].view_channel is True)
    check("📁 SALONS PERSO cachée à @everyone",
          perso[0].overwrites[g.default_role].view_channel is False)
    cr, err = courir(w.create_us_tickets(g, nouveau))
    check("relancé : rien de plus (idempotent)", not cr and not err and len(g.crees) == 2,
          (cr, err, g.crees))

    # rangé par pseudo, un seul déplacement
    g = youcham(n_va=0)
    cat = courir(oc.categorie_perso(g))
    for n in ("aaa-content", "ccc-content", "eee-content"):
        g.ajoute(n, cat)
    for n, attendu in (("bbb", ["aaa", "bbb", "ccc", "eee"]), ("000", ["000", "aaa", "bbb", "ccc", "eee"]),
                       ("zzz", ["000", "aaa", "bbb", "ccc", "eee", "zzz"])):
        g.deplaces.clear()
        m = Membre(len(g.members) + 8000, n, g)
        g.members.append(m)
        courir(w.create_us_tickets(g, m))
        ordre = [c.name[:-len("-content")] for c in cat.text_channels]
        check(f"rangé par pseudo : {n} à sa place, un déplacement au plus",
              ordre == attendu and len(g.deplaces) <= 1, (ordre, g.deplaces))
    check("le dernier alphabétique n'est pas déplacé (déjà en fin)", not g.deplaces, g.deplaces)
    # un salon tout juste créé n'est pas encore dans le cache de discord.py
    g.deplaces.clear()
    hors_cache = Salon(g, "bbc-content", cat)
    hors_cache.position = 10 ** 6
    courir(oc.ranger_content(hors_cache))
    check("salon pas encore dans le cache : rangé quand même (après bbb)",
          g.deplaces == [("bbc-content", {"after": "bbb-content"})], g.deplaces)

    # débordement à 50
    g = youcham(n_va=0)
    cat1 = courir(oc.categorie_perso(g))
    for i in range(50):
        g.ajoute(f"plein{i:02d}-content", cat1)
    m = Membre(8800, "nouvelle_recrue", g)
    g.members.append(m)
    cr, err = courir(w.create_us_tickets(g, m))
    ct = oc.content_de(g, m)
    check("50 salons dans 📁 SALONS PERSO : « 📁 SALONS PERSO 2 » créée, le salon y va",
          not err and ct is not None and ct.category.name == "📁 SALONS PERSO 2"
          and len(cat1.channels) == 50, (err, getattr(getattr(ct, "category", None), "name", None)))
    m2 = Membre(8801, "deuxieme_recrue", g)
    g.members.append(m2)
    courir(w.create_us_tickets(g, m2))
    check("la suivante va aussi dans « … 2 » (pas de 3e catégorie)",
          oc.content_de(g, m2).category.name == "📁 SALONS PERSO 2"
          and sum(1 for c in g.categories if oc.est_categorie_perso(c)) == 2)

    # ancien dossier (roucham) : le -content rejoint SALONS PERSO, rien de recréé
    g = youcham(n_va=0)
    rc = Membre(7100, "roucham_79944", g)
    g.members.append(rc)
    dossier = g.ajoute_cat("roucham_79944")
    vieux = {s: g.ajoute(f"roucham_79944-{s}", dossier)
             for s in ("menu", "spoofer", "download", "numero-mail", "content")}
    vieux["content"].overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                                   rc: discord.PermissionOverwrite(view_channel=True)}
    cr, err = courir(w.create_us_tickets(g, rc))
    check("ancien dossier : son -content rejoint 📁 SALONS PERSO, aucun salon créé",
          not cr and not err and oc.est_categorie_perso(vieux["content"].category)
          and not any(x[0] == "salon" for x in g.crees), (cr, err, g.crees))
    check("ancien dossier : le salon garde ses droits (pas de synchronisation)",
          vieux["content"].overwrites.get(rc) is not None)

    # pseudo changé : le -content à l'ancien nom est retrouvé par ses droits
    g = youcham(n_va=0)
    cat = courir(oc.categorie_perso(g))
    va = Membre(7200, "x0btc", g)
    g.members.append(va)
    ancien = g.ajoute("4vbtc-content", cat)
    ancien.overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                         va: discord.PermissionOverwrite(view_channel=True), g.me:
                         discord.PermissionOverwrite(view_channel=True)}
    cr, err = courir(w.create_us_tickets(g, va))
    check("pseudo changé : le -content à l'ancien nom est le sien, aucun doublon",
          oc.content_de(g, va) is ancien and not cr, cr)
    manager = Membre(7201, "manager_x", g)
    g.members.append(manager)
    partage = g.ajoute("autre-content", cat)
    partage.overwrites = {va: discord.PermissionOverwrite(view_channel=True),
                          manager: discord.PermissionOverwrite(view_channel=True)}
    check("un -content à DEUX membres nommés n'est le salon d'aucun des deux par repli",
          oc.content_de(g, manager) is None)

    # Youl4b : toujours 5 salons
    gl = Guilde(YOUL4B, "Youl4b")
    ml = Membre(9100, "roucham_79944", gl)
    gl.members.append(ml)
    poses.clear()
    cr, err = courir(w.create_us_tickets(gl, ml))
    check("Youl4b : toujours le dossier de 5 salons, dans l'ordre",
          [c.name for c in gl.text_channels]
          == ["roucham_79944-" + s for s in ("menu", "spoofer", "download", "numero-mail", "content")]
          and gl.crees[0] == ("categorie", "roucham_79944"), [c.name for c in gl.text_channels])
    check("Youl4b : menu, numéro, download et spoofer posés comme avant",
          sorted(p[0] for p in poses) == ["_ensure_dl_panel", "_ensure_num_panel",
                                          "_ensure_spoof_panel", "_ensure_us_menu"], poses)
    check("Youl4b : aucune catégorie 📁 SALONS PERSO",
          not any(oc.est_categorie_perso(c) for c in gl.categories))

    # rattrapage des dossiers : rien sur YouCham
    g = youcham(n_va=1)
    cat = courir(oc.categorie_perso(g))
    c1 = g.ajoute("va_a-content", cat)
    c1.overwrites = {g.vas[0]: discord.PermissionOverwrite(view_channel=True)}
    b = courir(w.completer_dossiers_us(g, ("spoofer", "generateur-de-lien")))
    check("completer_dossiers_us sur YouCham : aucun -spoofer ni -generateur-de-lien",
          not b["crees"] and not any(x[0] == "salon" for x in g.crees), b)
finally:
    for k, v in _sauve_d.items():
        setattr(w, k, v)
    asyncio.sleep = _sleep


# ═══════════════════════════════════════ 3. 🧰 OUTILS et panneaux ══
print("3. Salons communs et panneaux")
import cogs.spoofer as spf  # noqa: E402
import cogs.telechargement as tl  # noqa: E402
import cogs.user as u  # noqa: E402

_sauve_e = {"emojis": (u.ensure_identity_emojis, u.ensure_reserve_emojis, u.ensure_action_emojis),
            "adm": w._membre_bot_admin}


async def _rien_emoji(*a, **k):
    return {}


class _FauxSpfCog:
    def __init__(self, bot):
        self.bot = bot
        self.en_cours = set()

    assurer_panneau = spf.Spoofer.assurer_panneau


class _FauxDlCog:
    def __init__(self, bot):
        self.bot = bot
        self.choix = {}
        self.livrees = []
        self.retenus = []

    def retenir(self, uid, pseudo, n):
        self.retenus.append((uid, pseudo, n))
        self.choix[uid] = (pseudo, n)
        return True

    def reserver(self, uid, pseudo):
        return ""

    def liberer(self, uid, pseudo):
        pass

    async def livrer(self, canal, username, combien, **kw):
        self.livrees.append((canal, username, combien, kw))


class _FauxBot:
    def __init__(self, guildes=()):
        self.user = types.SimpleNamespace(id=RYUK)
        self.guilds = list(guildes)
        self.vues = []
        self.cogs = {}

    def get_cog(self, n):
        return self.cogs.get(n)

    def add_view(self, v):
        self.vues.append(v)


try:
    u.ensure_identity_emojis = u.ensure_reserve_emojis = u.ensure_action_emojis = _rien_emoji
    asyncio.sleep = _instant
    g = youcham(n_va=0, avec_outils=False)
    w._membre_bot_admin = lambda gg: getattr(gg, "rem", None)
    bot = _FauxBot([g])
    bot.cogs = {"Spoofer": _FauxSpfCog(bot), "Telechargement": _FauxDlCog(bot)}
    b1 = courir(oc.assurer(g, bot))
    cat = discord.utils.find(oc.est_categorie_outils, g.categories)
    noms = [c.name for c in cat.text_channels] if cat else []
    check("🧰 OUTILS créée avec ses 4 salons, dans l'ordre de la maquette",
          cat is not None and noms == ["📋・menu", "📤・spoofer", "⬇️・download", "📱・numéro"], noms)
    check("🧰 OUTILS placée en tête du serveur, une fois",
          g.categories[0] is cat and any(d[0] == "[cat] 🧰 OUTILS" for d in g.deplaces), g.deplaces)
    sal = {oc._cle(c.name): c for c in cat.text_channels}
    ok_droits = True
    for c in sal.values():
        o = c.overwrites[g.default_role]
        ok_droits &= (o.view_channel is True and o.read_message_history is True
                      and o.send_messages is False and o.add_reactions is False
                      and o.create_public_threads is False and o.create_private_threads is False
                      and o.send_messages_in_threads is False)
        ok_droits &= c.overwrites[g.me].send_messages is True
    check("lecture seule pour tous : voir, historique ; ni écrire, ni réagir, ni fil",
          ok_droits)
    check("Rem a sa règle dans 📱・numéro seulement",
          g.rem in sal["numero"].overwrites and all(g.rem not in sal[k].overwrites
                                                    for k in ("menu", "spoofer", "download")))
    check("chaque salon commun est reconnu (et le bon outil)",
          all(oc.est_salon_outil(sal[k], k) for k in oc.CLES)
          and not oc.est_salon_outil(sal["menu"], "spoofer"))
    du_bot = lambda c: [m for m in c.messages if m.author.id == RYUK]  # noqa: E731
    check("menu : UN panneau, un bouton « 📋 Ouvrir mon menu », aucun texte",
          len(du_bot(sal["menu"])) == 1 and du_bot(sal["menu"])[0].content is None
          and oc.MENU_ID in oc._ids(du_bot(sal["menu"])[0])
          and not any(isinstance(x, discord.ui.TextDisplay) for x in oc.PanneauMenu().walk_children()))
    check("spoofer : UN panneau [🔢 5][📤 Spoofer]",
          len(du_bot(sal["spoofer"])) == 1
          and {"spf:qb:5", "spf:go:5"} <= oc._ids(du_bot(sal["spoofer"])[0]))
    check("download : UN panneau (compte + options)",
          len(du_bot(sal["download"])) == 1
          and {"dl:compte", "dl:tout", "dl:reels"} <= oc._ids(du_bot(sal["download"])[0]))
    check("numéro : pas posé par Ryuk (c'est Rem, cogs/numeros)", not du_bot(sal["numero"]))
    check("1er passage : bilan sans échec", not b1["rates"], b1)
    n_crees = len(g.crees)
    b2 = courir(oc.assurer(g, bot))
    check("2e passage : rien de créé, aucun panneau reposté",
          len(g.crees) == n_crees and not b2["panneaux"] and not b2["rates"]
          and all(len(du_bot(sal[k])) == 1 for k in ("menu", "spoofer", "download")), b2)
    # état perdu (data/ repartie de zéro) : le panneau est retrouvé dans le salon
    oc.ETAT.unlink()
    b3 = courir(oc.assurer(g, bot))
    check("état perdu : le panneau du menu est retrouvé en relisant le salon, pas reposté",
          len(du_bot(sal["menu"])) == 1 and not b3["panneaux"], b3)
    # panneau supprimé à la main : reposé, une fois
    du_bot(sal["menu"])[0].channel.messages.clear()
    b4 = courir(oc.assurer(g, bot))
    check("panneau supprimé à la main : reposé une fois",
          b4["panneaux"] == ["menu"] and len(du_bot(sal["menu"])) == 1, b4)
    check("Youl4b : aucun salon commun créé", not courir(oc.assurer(Guilde(YOUL4B, "l"), bot))["crees"])
    vue = oc.PanneauMenu()
    check("bouton du menu : vue persistante (custom_id fixe, sans délai)",
          vue.is_persistent() and _ids(vue) == [oc.MENU_ID])
    # le cog Outils l'enregistre au démarrage et lance l'entretien
    import cogs.outils as co  # noqa: E402

    class _Boucle:
        def __init__(self):
            self.lance = False

        def start(self):
            self.lance = True

    fo = types.SimpleNamespace(bot=_FauxBot(), _entretien=_Boucle(), _numeros=_Boucle(),
                               _outils_communs=_Boucle())
    courir(co.Outils.cog_load(fo))
    check("cog Outils : bouton du menu rattaché au démarrage (add_view) et entretien lancé",
          any(isinstance(v, oc.PanneauMenu) for v in fo.bot.vues) and fo._outils_communs.lance)
    vus = []
    _assurer = oc.assurer

    async def _faux_assurer(gg, bb):
        vus.append(gg.id)
        return {}
    oc.assurer = _faux_assurer
    try:
        courir(co.Outils._outils_communs.coro(types.SimpleNamespace(
            bot=_FauxBot([Guilde(YOUL4B, "l"), Guilde(YOUCHAM, "y"), Guilde(VA_IG, "v")]))))
    finally:
        oc.assurer = _assurer
    check("entretien des outils communs : YouCham seul", vus == [YOUCHAM], vus)
finally:
    u.ensure_identity_emojis, u.ensure_reserve_emojis, u.ensure_action_emojis = _sauve_e["emojis"]
    w._membre_bot_admin = _sauve_e["adm"]
    asyncio.sleep = _sleep


# ═══════════════════════════ 4. livraison chez le cliqueur, jamais au commun ══
print("4. Chaque outil livre dans le -content du cliqueur")
g = youcham(n_va=2)
cat_p = None


async def _prepa():
    global cat_p
    cat_p = await oc.categorie_perso(g)
    # d'autres VA d'abord : la recherche « même catégorie » de Youl4b
    # prendrait le premier venu
    for i in range(5):
        autre = Membre(7500 + i, f"aaa_autre{i}", g)
        g.members.append(autre)
        c = g.ajoute(f"aaa_autre{i}-content", cat_p)
        c.overwrites = {autre: discord.PermissionOverwrite(view_channel=True)}
    for va in g.vas:
        c = g.ajoute(w._us_ticket_name(va, "content"), cat_p)
        c.overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                        va: discord.PermissionOverwrite(view_channel=True)}
courir(_prepa())
VA1, VA2, STAFF = g.vas[0], g.vas[1], g.staff
CT1, CT2 = oc.content_de(g, VA1), oc.content_de(g, VA2)
S = g.outils
check("chaque VA a SON -content (pas le premier de la catégorie)",
      CT1.name == "va_a-content" and CT2.name == "va_b-content" and oc.content_de(g, STAFF) is None)


def _commun_vide():
    return all(not [m for m in c.messages if m.content or m.vue] for c in S.values())


# ── 4a. menu
print("  4a. menu")
_vrai_marche = u._jb_models_marche
u._jb_models_marche = lambda marche="us": ["lola", "julia"]


class _FauxUserCog:
    """Le cog du menu : _run_for_model est le VRAI ; chaque action note qui
    l'a demandee, pour quelle identite, et parle par l'interaction recue."""

    def __init__(self):
        self.appels = []

    _run_for_model = u.UserCog._run_for_model

    def __getattr__(self, nom):
        if nom.startswith("__"):
            raise AttributeError(nom)

        async def action(itx, nombre=None):
            self.appels.append((nom, itx.user.id, u._IDENTITY_OVERRIDE.get(), nombre))
            await itx.followup.send(f"{nom} pour {u._IDENTITY_OVERRIDE.get()}")
        return action


UC = _FauxUserCog()
COGS = {"UserCog": UC}
try:
    itx = Itx(g, S["menu"], STAFF, COGS)
    courir(u.ouvrir_menu_commun(itx))
    check("📋 Ouvrir mon menu, staff sans -content : refus court en éphémère",
          itx.response.envois == [(oc.REFUS, {"ephemeral": True})], itx.response.envois)
    itx = Itx(g, S["menu"], VA1, COGS)
    courir(u.ouvrir_menu_commun(itx))
    env = itx.response.envois
    check("📋 Ouvrir mon menu, VA : le menu des models en éphémère, pour lui seul",
          len(env) == 1 and env[0][1].get("ephemeral") is True
          and any(i.startswith("jbus:ms:us:") for i in _ids(env[0][1]["view"])),
          env)
    check("… et rien n'est posé dans le salon commun", _commun_vide())

    async def _choisir(user, model):
        it = Itx(g, S["menu"], user, COGS, ephemere=True)
        await u._jb_model_panneau(it, UC, model)
        return it
    it_lola = courir(_choisir(VA1, "lola"))
    env = it_lola.response.envois
    ids_p = _ids(env[0][1]["view"]) if env else []
    check("choix d'une model : SON panneau en éphémère (identité dans chaque custom_id)",
          len(env) == 1 and env[0][1].get("ephemeral") is True
          and "jbus:qb:lola:5" in ids_p and "jbus:a:lola:pp:5" in ids_p
          and all(":lola:" in i for i in ids_p if i.startswith("jbus:")), ids_p[:6])
    check("le salon commun n'a aucun état de panneau retenu (_JB_PANNEAU_COURANT)",
          S["menu"].id not in u._JB_PANNEAU_COURANT)
    check("le menu des models du salon commun ne garde pas de choix affiché",
          not u._jb_menu_garde_choix(S["menu"]))
    premier = it_lola.originale
    it_julia = courir(_choisir(VA1, "julia"))
    check("nouveau choix : l'ancien panneau de la personne est effacé (05/09 : panneaux empilés)",
          premier is not None and premier.supprime
          and "jbus:a:julia:pp:5" in _ids(it_julia.response.envois[0][1]["view"]))
    it_b = courir(_choisir(VA2, "lola"))
    check("un autre VA qui choisit n'efface pas le panneau du premier",
          it_julia.originale is not None and not it_julia.originale.supprime)

    def _clic_action(user, ident, key, qty):
        it = Itx(g, S["menu"], user, COGS, ephemere=True)
        courir(u.JBActionButton(ident, key, qty).callback(it))
        return it
    UC.appels.clear()
    _clic_action(VA1, "lola", "pp", 3)
    _clic_action(VA2, "julia", "pp", 2)
    check("deux VA, même bouton : chacun reçoit dans SON -content",
          [m.content for m in CT1.messages] == ["profilepic pour lola"]
          and [m.content for m in CT2.messages] == ["profilepic pour julia"],
          ([m.content for m in CT1.messages], [m.content for m in CT2.messages]))
    check("identité et quantité portées par le clic", UC.appels == [
        ("profilepic", VA1.id, "lola", 3), ("profilepic", VA2.id, "julia", 2)], UC.appels)
    check("rien dans le salon commun ni chez les autres VA",
          _commun_vide() and not any(c.messages for c in cat_p.text_channels
                                     if c not in (CT1, CT2)))
    UC.appels.clear()
    it = _clic_action(STAFF, "lola", "pp", 1)
    check("staff sans -content qui clique une action : refus en éphémère, rien de généré",
          not UC.appels and it.response.envois == [(oc.REFUS, {"ephemeral": True})]
          and _commun_vide(), (UC.appels, it.response.envois))
    # le -content ressort du clic, jamais par catégorie ; un clic DANS un -content y reste
    t = types.SimpleNamespace(channel=S["menu"], guild=g, user=VA2)
    check("_us_content_target : depuis le salon commun, le -content du cliqueur",
          u._us_content_target(t) is CT2)
    t = types.SimpleNamespace(channel=CT1, guild=g, user=VA1)
    check("_us_content_target : un clic dans un -content (menu des brutes) y reste",
          u._us_content_target(t) is CT1)
    t = Itx(g, S["menu"], STAFF, COGS)
    r = u._vers_content(t)
    check("_vers_content sans -content dans le salon commun : éphémère, jamais public",
          isinstance(r, u._JBRedirect) and object.__getattribute__(r, "_target") is None)
    # Youl4b : la recherche par dossier ne change pas
    gl = Guilde(YOUL4B, "l")
    dos = gl.ajoute_cat("bob")
    mn, cn = gl.ajoute("bob-menu", dos), gl.ajoute("bob-content", dos)
    check("Youl4b inchangé : depuis -menu, le -content du même dossier",
          u._us_content_target(types.SimpleNamespace(channel=mn, guild=gl, user=None)) is cn)
finally:
    u._jb_models_marche = _vrai_marche


# ── 4b. spoofer
print("  4b. spoofer")
SPF = _FauxSpfCog(_FauxBot())
CSPF = {"Spoofer": SPF}
check("📤・spoofer : salon spoofer (panneaux) et commun YouCham ; pas un salon commun de Va IG",
      spf._est_salon_spoofer(S["spoofer"]) and spf._commun_us(S["spoofer"])
      and not spf._commun_us(CT1))
it = Itx(g, S["spoofer"], STAFF, CSPF)
courir(spf.SpfGo(3).callback(it))
check("📤 Spoofer, staff sans -content : refus éphémère AVANT la fenêtre",
      not it.response.modales and it.response.envois == [(oc.REFUS, {"ephemeral": True})])
it = Itx(g, S["spoofer"], VA1, CSPF)
courir(spf.SpfGo(3).callback(it))
check("📤 Spoofer, VA : la fenêtre, avec le nombre du bouton cliqué (custom_id)",
      len(it.response.modales) == 1 and it.response.modales[0].q == 3)


async def _quantite(user, msg_eph, valeur):
    it = Itx(g, S["spoofer"], user, CSPF, ephemere=msg_eph)
    m = spf.FenetreQuantite(5)
    m.nombre._value = valeur
    await m.on_submit(it)
    return it
it = courir(_quantite(VA1, False, "2"))
env = it.response.envois
check("🔢 dans le salon commun : SON panneau en éphémère, nombre dans le custom_id",
      len(env) == 1 and env[0][1].get("ephemeral") is True
      and "spf:go:2" in _ids(env[0][1]["view"]) and not it.response.editions, env)
check("… le panneau du salon n'est pas redessiné (il reste à 5 pour tous)",
      not S["spoofer"].edites and not it.response.editions)
it = courir(_quantite(VA1, True, "4"))
check("🔢 depuis son panneau éphémère : redessiné sur place, pas un 2e message",
      not it.response.envois and len(it.response.editions) == 1
      and "spf:go:4" in _ids(it.response.editions[0]["view"]))
check("le nombre n'est retenu nulle part (pas de fichier de quantités)",
      not (DATA / "spoofer_qte.json").exists() or "spoofer_qte.json" in AVANT)
for user, ct in ((VA1, CT1), (VA2, CT2)):
    t = Itx(g, S["spoofer"], user, CSPF)
    check(f"spoofer : versions livrées dans le -content de {user.name}",
          spf._cible_content(t) is ct)
check("spoofer : staff sans -content : nulle part",
      spf._cible_content(Itx(g, S["spoofer"], STAFF, CSPF)) is None)
_n1 = len(CT1.messages)
it = Itx(g, S["spoofer"], VA1, CSPF)
b = courir(spf.Spoofer.traiter(SPF, it, types.SimpleNamespace(filename="doc.pdf", size=10), 3))
check("spoofer : un refus (format) est dit dans SON -content, pas au commun",
      b["refus"] == "format" and len(CT1.messages) == _n1 + 1
      and "format non pris" in (CT1.messages[-1].content or "") and _commun_vide(), b)
it = Itx(g, S["spoofer"], STAFF, CSPF)
b = courir(spf.Spoofer.traiter(SPF, it, types.SimpleNamespace(filename="a.jpg", size=10), 3))
check("spoofer : staff (fenêtre déjà ouverte) : refus éphémère, rien livré",
      b["refus"] == "salon" and it.response.envois == [(oc.REFUS, {"ephemeral": True})]
      and _commun_vide(), (b, it.response.envois))
_crees = len(g.crees)
n = courir(spf.Spoofer._provisionner(types.SimpleNamespace(bot=SPF.bot), g))
check("entretien du spoofer sur YouCham : aucun -spoofer provisionné", n == 0 and len(g.crees) == _crees)


# ── 4c. download
print("  4c. download")
DL = _FauxDlCog(_FauxBot())
CDL = {"Telechargement": DL}
check("⬇️・download : salon commun YouCham reconnu, -content non",
      tl._commun_us(S["download"]) and tl._commun(S["download"]) and not tl._commun_us(CT1))
check("download : livraison dans le -content du cliqueur, staff nulle part",
      tl.salon_de_livraison(S["download"], VA1) is CT1
      and tl.salon_de_livraison(S["download"], VA2) is CT2
      and tl.salon_de_livraison(S["download"], STAFF) is None)
P = tl.PanneauTelechargement(DL)
it = Itx(g, S["download"], STAFF, CDL)
courir(P._compte(it))
check("👤 compte, staff sans -content : refus éphémère, pas de fenêtre",
      not it.response.modales and it.response.envois == [(oc.REFUS, {"ephemeral": True})])


async def _compte(user, eph=False):
    it = Itx(g, S["download"], user, CDL, ephemere=eph)
    m = tl.ModalCompte(DL)
    m.pseudo._value = "Sky.Ards"
    m.combien._value = "12"
    await m.on_submit(it)
    return it
it = courir(_compte(VA1))
env = it.response.envois
check("compte choisi au commun : les options en éphémère, pour lui seul",
      len(env) == 1 and env[0][1].get("ephemeral") is True
      and {"dl:compte", "dl:tout", "dl:reels", "dl:top"} <= set(_ids(env[0][1]["view"]))
      and DL.choix[VA1.id] == ("sky.ards", 12), env)
check("… le panneau du salon n'est pas réécrit avec son compte",
      not S["download"].edites and not it.message.supprime)
it = courir(_compte(VA1, eph=True))
check("compte rechoisi depuis son éphémère : redessiné sur place",
      not it.response.envois and len(it.response.editions) == 1)
DL.choix[VA2.id] = ("autre.compte", 5)
for user, ct in ((VA1, CT1), (VA2, CT2)):
    it = Itx(g, S["download"], user, CDL)
    courir(P._lancer(it, "reels"))
    check(f"Reels : livré dans le -content de {user.name}, confirmation éphémère courte",
          DL.livrees[-1][0] is ct and it.response.envois[0][1].get("ephemeral") is True)
DL.choix[STAFF.id] = ("x", 1)
it = Itx(g, S["download"], STAFF, CDL)
n_av = len(DL.livrees)
courir(P._lancer(it, "tout"))
check("Tout, staff sans -content : refus éphémère, rien livré",
      len(DL.livrees) == n_av and it.response.envois == [(oc.REFUS, {"ephemeral": True})])
dem = tl._Demande("sky.ards", "Reels", VA1, CT1)
check("download : la copie part dans le ⬇️・all-download de YouCham",
      dem.archive is g.archive)
check("download : le salon commun n'est pas un -download (ménage quotidien inchangé)",
      not tl._norm(S["download"].name).endswith("-download"))


# ── 4d. numéro
print("  4d. numéro")
import cogs.numeros as nm  # noqa: E402

check("📱・numéro : panneau commun ; un -content n'en est pas un",
      nm._salon_commun(S["numero"]) and not nm._salon_commun(CT1))


class _FauxNum:
    def __init__(self):
        self.bas, self.achats = [], []

    async def _panneau_en_bas(self, canal):
        self.bas.append(canal)

    async def nouvelle_activation(self, itx, kind="sms", service="ig", par=None, canal=None):
        self.achats.append((kind, canal, itx.user.id))
        return True


_status = nm.numgen.status
nm.numgen.status = lambda: {"sms_ok": True, "mail_ok": True}
try:
    FN = _FauxNum()
    for user, ct in ((VA1, CT1), (VA2, CT2)):
        it = Itx(g, S["numero"], user)
        courir(nm.NumerosCog.clic_commun(FN, it, "sms"))
        check(f"📱 Prendre un numéro ({user.name}) : la carte va dans SON -content",
              FN.bas[-1:] == [ct] and FN.achats[-1:] == [("sms", ct, user.id)],
              (FN.bas[-1:], FN.achats[-1:], it.response.envois))
        check(f"… au cliqueur, une confirmation éphémère courte ({user.name})",
              it.followup.envois and it.followup.envois[-1][1].get("ephemeral") is True
              and ct.mention in it.followup.envois[-1][0])
    it = Itx(g, S["numero"], VA1)
    courir(nm.NumerosCog.clic_commun(FN, it, "mail"))
    check("📧 Mail : même règle", FN.achats[-1:] == [("mail", CT1, VA1.id)])
    n_av = len(FN.achats)
    it = Itx(g, S["numero"], STAFF)
    courir(nm.NumerosCog.clic_commun(FN, it, "sms"))
    check("📱 staff sans -content : refus éphémère, rien acheté",
          len(FN.achats) == n_av and it.response.envois[0][0] == oc.REFUS
          and it.response.envois[0][1].get("ephemeral") is True)
    check("pas de quota ni de +33 sur YouCham (règles de -numero-mail de Youl4b)",
          not nm._serveur_fr(CT1) and nm._pays(CT1) is None)
finally:
    nm.numgen.status = _status

# la carte dans le -content : le ménage du panneau n'y touche JAMAIS aux livraisons
_sauve_n = (nm._salon, nm._salon_ecrire, nm._fichier_icone)
nm._salon = lambda cid: {}
nm._salon_ecrire = lambda cid, **k: None
nm._fichier_icone = lambda: None
try:
    livraison = courir(CT1.send("une video livree"))

    class _BotRem:
        user = types.SimpleNamespace(id=RYUK)
    ok = courir(nm.poser_panneau(_BotRem(), CT1, cog=object(), solde="—"))
    check("carte du numéro posée dans le -content, la livraison d'avant est gardée",
          ok and livraison in CT1.messages and not livraison.supprime
          and any("numgen:" in (i or "") for i in oc._ids(CT1.messages[-1])))
finally:
    nm._salon, nm._salon_ecrire, nm._fichier_icone = _sauve_n

# la boucle de Rem pose le panneau du salon commun, et lui seul
poses_n = []
_vrai_poser = nm.poser_panneau


async def _faux_poser(bot, c, cog=None, **k):
    poses_n.append(c.name)
    return True
nm.poser_panneau = _faux_poser
nm._salon = lambda cid: {}
try:
    courir(nm.NumerosCog._panneau_commun.coro(types.SimpleNamespace(
        bot=types.SimpleNamespace(guilds=[g]))))
finally:
    nm.poser_panneau = _vrai_poser
    nm._salon = _sauve_n[0]
check("Rem pose le panneau du 📱・numéro commun, et dans aucun -content",
      poses_n == ["📱・numéro"], poses_n)


# ═══════════════════════════════════════════ 5. /ticketsall sur YouCham ══
print("5. /ticketsall sur YouCham")
_sauve_t = {k: getattr(w, k) for k in ("_membre_bot_admin",)}
try:
    asyncio.sleep = _instant
    w._membre_bot_admin = lambda gg: getattr(gg, "rem", None)
    g = youcham(n_va=2)
    admin = Membre(1, "proprio", g)
    g.members.append(admin)
    cat_p = courir(oc.categorie_perso(g))
    va1, va3 = g.vas[0], g.vas[1]
    c1 = g.ajoute("va_a-content", cat_p)
    c1.overwrites = {va1: discord.PermissionOverwrite(view_channel=True)}
    rc = Membre(7100, "roucham_79944", g)
    g.members.append(rc)
    dossier = g.ajoute_cat("roucham_79944")
    vieux = {s: g.ajoute(f"roucham_79944-{s}", dossier)
             for s in ("menu", "spoofer", "download", "numero-mail", "content")}
    vieux["content"].overwrites = {rc: discord.PermissionOverwrite(view_channel=True)}
    parti = g.ajoute("ancien_va-content", cat_p)
    renomme = Membre(7300, "nouveau_nom", g)
    g.members.append(renomme)
    c_ren = g.ajoute("ancien_nom-content", cat_p)
    c_ren.overwrites = {renomme: discord.PermissionOverwrite(view_channel=True)}
    outils_ids = {c.id for c in g.outils.values()}

    class _FauxW:
        bot = None

        async def require_admin(self, itx):
            return True

    it = Itx(g, g.archive, admin)
    courir(w.Welcome.ticketsall.callback(_FauxW(), it))
    texte, kw = it.response.envois[0]
    vue = kw.get("view")
    check("plan : les 4 salons de l'ancien dossier et le salon du VA parti, rien d'autre",
          "**5** salon(s) à supprimer" in texte and all(f"#roucham_79944-{s}" in texte for s in
                                                       ("menu", "spoofer", "download", "numero-mail"))
          and "#ancien_va-content" in texte, texte)
    check("plan : ni outils, ni archive, ni le -content de roucham, ni celui du VA renommé",
          not any(n in texte for n in ("📋・menu", "all-download", "#roucham_79944-content",
                                        "#ancien_nom-content", "#va_a-content")), texte)
    check("plan : un -content par personne dans 📁 SALONS PERSO ; outils et archive pas touchés",
          "salon `-content` par personne" in texte and "pas touchés" in texte, texte)
    check("plan : les manquants -- le staff et va_b (le renommé a le sien)",
          "**2** salon(s) manquant(s)" in texte, texte)

    async def _confirmer():
        it2 = Itx(g, g.archive, admin)
        await vue.children[0].callback(it2)
        return it2
    it2 = courir(_confirmer())
    restants = {c.id for c in g.text_channels}
    check("après : les 4 salons communs sont toujours là, intacts",
          outils_ids <= restants and all(not c.supprime for c in g.outils.values()))
    check("après : l'archive all-download est toujours là", g.archive.id in restants)
    check("après : l'ancien dossier ne garde que son -content, rangé dans SALONS PERSO",
          all(vieux[s].supprime for s in ("menu", "spoofer", "download", "numero-mail"))
          and not vieux["content"].supprime and oc.est_categorie_perso(vieux["content"].category))
    check("après : la catégorie vide de l'ancien dossier est retirée",
          "[cat] roucham_79944" in g.supprimes, g.supprimes)
    check("après : le -content du VA renommé est gardé (rien perdu de ce qu'il a reçu)",
          not c_ren.supprime)
    check("après : va_b et le staff ont leur -content dans SALONS PERSO, aucun dossier",
          all(oc.content_de(g, m) is not None and oc.est_categorie_perso(oc.content_de(g, m).category)
              for m in (va3, g.staff))
          and not any(n.endswith(("-menu", "-spoofer", "-download", "-numero-mail"))
                      for n in (c.name for c in g.text_channels) if not w.salon_de_service(n)),
          [(m.name, getattr(oc.content_de(g, m), "name", None),
            getattr(getattr(oc.content_de(g, m), "category", None), "name", None))
           for m in (va3, g.staff)] + [c.name for c in g.text_channels])
    recap = it2.followup.envois[-1][0] if it2.followup.envois else ""
    check("récap : 1/1 par personne", "`va_b` — 1/1" in recap and "🛠" not in recap, recap)
finally:
    for k, v in _sauve_t.items():
        setattr(w, k, v)
    asyncio.sleep = _sleep


# ══════════════════════════════════ 7. constats de la relecture (30/10) ══
print("7. Constats de la relecture")


class GuildeLente(Guilde):
    """Discord répond à la création, puis SON événement met l'objet dans le
    cache de discord.py un peu plus tard -- comme en vrai. `vrais` : ce que
    Discord compte dans chaque catégorie, cache ou pas."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.vrais = {}
        self.refus = 0

    async def create_category(self, name, overwrites=None, reason="", **kw):
        await _sleep(0.005)
        c = Categorie(self, name)
        c.overwrites = overwrites or {}
        self.crees.append(("categorie", name))
        asyncio.get_running_loop().call_later(0.05, self._cats.append, c)
        return c

    async def create_text_channel(self, name, category=None, overwrites=None, reason="", **kw):
        await _sleep(0.005)
        if category is not None:
            n = self.vrais.get(category.id, len(category.channels))
            if n >= 50:
                self.refus += 1
                raise discord.HTTPException(types.SimpleNamespace(status=400, reason="Bad Request"),
                                            "In parent_id: Maximum number of channels in category "
                                            "reached (50)")
            self.vrais[category.id] = n + 1
        c = Salon(self, name, category)
        c.overwrites = overwrites or {}
        self.crees.append(("salon", name))
        asyncio.get_running_loop().call_later(0.05, self._salons.append, c)
        return c


def _youcham_lent(n_plein=0):
    g = GuildeLente(YOUCHAM, "YouCham")
    g.rem = Membre(REM, "Rem", g, bot=True)
    g.members.append(g.rem)
    if n_plein:
        cat = g.ajoute_cat(oc.CATEGORIE_PERSO)
        for i in range(n_plein):
            g.ajoute(f"plein{i:02d}-content", cat)
        g.cat1 = cat
    return g


_sauve_7 = {"adm": w._membre_bot_admin, "marche": u._jb_models_marche,
            "emojis": (u.ensure_identity_emojis, u.ensure_reserve_emojis, u.ensure_action_emojis),
            "status": nm.numgen.status}
try:
    w._membre_bot_admin = lambda gg: getattr(gg, "rem", None)
    asyncio.sleep = _instant

    # ── 7a. deux pseudos, une même base (« lea.m » / « leam ») ; pseudo repris
    print("  7a. pseudos qui se ressemblent")
    g = youcham(n_va=0)
    lea, leam = Membre(7600, "lea.m", g), Membre(7601, "leam", g)
    g.members += [lea, leam]
    courir(w.create_us_tickets(g, lea))
    cr, err = courir(w.create_us_tickets(g, leam))
    c_lea, c_leam = oc.content_de(g, lea), oc.content_de(g, leam)
    check("« leam » après « lea.m » : son PROPRE salon, pas celui de lea.m",
          c_lea is not None and c_leam is not None and c_lea is not c_leam
          and c_lea.name == "leam-content" and c_leam.name == "leam-7601-content"
          and cr == [c_leam] and not err,
          (getattr(c_lea, "name", None), getattr(c_leam, "name", None), cr, err))
    check("… à lui seul : sa règle, pas celle de lea.m",
          c_leam.overwrites.get(leam) is not None and lea not in c_leam.overwrites
          and leam not in c_lea.overwrites)
    check("… rangé dans 📁 SALONS PERSO, et relancé : rien de plus",
          oc.est_categorie_perso(c_leam.category)
          and courir(w.create_us_tickets(g, leam)) == ([], []))
    S7 = g.outils
    check("spoofer, download : chacun reçoit chez lui",
          spf._cible_content(Itx(g, S7["spoofer"], leam, CSPF)) is c_leam
          and spf._cible_content(Itx(g, S7["spoofer"], lea, CSPF)) is c_lea
          and tl.salon_de_livraison(S7["download"], leam) is c_leam
          and tl.salon_de_livraison(S7["download"], lea) is c_lea)
    nm.numgen.status = lambda: {"sms_ok": True, "mail_ok": True}
    FN7 = _FauxNum()
    courir(nm.NumerosCog.clic_commun(FN7, Itx(g, S7["numero"], leam), "sms"))
    check("numéro de « leam » : la carte chez lui, jamais chez lea.m",
          FN7.bas == [c_leam] and FN7.achats == [("sms", c_leam, leam.id)], (FN7.bas, FN7.achats))
    u._jb_models_marche = lambda marche="us": ["lola", "julia"]
    UC.appels.clear()
    courir(u.JBActionButton("lola", "pp", 2).callback(Itx(g, S7["menu"], leam, COGS, ephemere=True)))
    check("menu de « leam » : le contenu chez lui",
          [m.content for m in c_leam.messages] == ["profilepic pour lola"] and not c_lea.messages,
          ([m.content for m in c_leam.messages], [m.content for m in c_lea.messages]))

    # un nouveau venu reprend le pseudo d'un VA parti
    g = youcham(n_va=0)
    cat = courir(oc.categorie_perso(g))
    vieux_bob = g.ajoute("bob-content", cat)
    vieux_bob.overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                            discord.Object(id=4242): discord.PermissionOverwrite(view_channel=True)}
    courir(vieux_bob.send("la video du VA parti"))
    bob = Membre(7700, "bob", g)
    g.members.append(bob)
    cr, err = courir(w.create_us_tickets(g, bob))
    c_bob = oc.content_de(g, bob)
    check("pseudo repris : le nouveau « bob » a un salon neuf, pas l'historique de l'ancien",
          c_bob is not None and c_bob is not vieux_bob and c_bob.name == "bob-7700-content"
          and cr == [c_bob] and not vieux_bob.supprime,
          (getattr(c_bob, "name", None), cr, err))

    # /ticketsall : deux salons « leam-content » à deux personnes, et le salon
    # au nom de bob qui n'est pas à lui
    g = youcham(n_va=0)
    admin = Membre(1, "proprio", g)
    lea, leam, bob = Membre(7600, "lea.m", g), Membre(7601, "leam", g), Membre(7700, "bob", g)
    g.members += [admin, lea, leam, bob]
    cat = courir(oc.categorie_perso(g))
    a1 = g.ajoute("leam-content", cat)
    a1.overwrites = {lea: discord.PermissionOverwrite(view_channel=True)}
    a2 = g.ajoute("leam-content", cat)
    a2.overwrites = {leam: discord.PermissionOverwrite(view_channel=True)}
    courir(a2.send("livre a leam"))
    vb = g.ajoute("bob-content", cat)
    vb.overwrites = {discord.Object(id=4242): discord.PermissionOverwrite(view_channel=True)}
    nb = g.ajoute("bob-7700-content", cat)
    nb.overwrites = {bob: discord.PermissionOverwrite(view_channel=True)}

    class _FauxW7:
        bot = None

        async def require_admin(self, itx):
            return True

    it = Itx(g, g.archive, admin)
    courir(w.Welcome.ticketsall.callback(_FauxW7(), it))
    texte, kw = it.response.envois[0]
    check("/ticketsall : deux « leam-content » à deux VA, aucun n'est un doublon à supprimer",
          "#leam-content" not in texte and "rien à supprimer" in texte, texte)
    check("/ticketsall : le salon au nom de bob qui n'est pas à lui est gardé ET signalé",
          "#bob-content porte le nom de bob sans être à lui" in texte
          and "#bob-7700-content" not in texte, texte)
    it2 = Itx(g, g.archive, admin)
    courir(kw["view"].children[0].callback(it2))
    check("/ticketsall confirmé : les deux salons leam et les deux salons bob sont là",
          not any(c.supprime for c in (a1, a2, vb, nb)))
    recap = it2.followup.envois[-1][0] if it2.followup.envois else ""
    check("récap : lea.m, leam et bob à 1/1",
          all(f"`{n}` — 1/1" in recap for n in ("leam", "bob")) and "🛠" not in recap, recap)

    # ── 7b. arrivées simultanées
    print("  7b. arrivées simultanées")

    async def _ensemble(g, membres):
        r = await asyncio.gather(*(w.create_us_tickets(g, m) for m in membres))
        await _sleep(0.12)           # les événements de Discord arrivent
        return r

    g = _youcham_lent()
    A, B = Membre(7801, "arrivee_a", g), Membre(7802, "arrivee_b", g)
    g.members += [A, B]
    r = courir(_ensemble(g, (A, B)))
    perso = [c for c in g.categories if oc.est_categorie_perso(c)]
    check("deux arrivées dans la même seconde : UNE seule 📁 SALONS PERSO",
          [x for x in g.crees if x[0] == "categorie"] == [("categorie", "📁 SALONS PERSO")]
          and len(perso) == 1, g.crees)
    check("… et chacun son -content dedans, sans erreur",
          all(not err for _cr, err in r) and all(
              oc.content_de(g, m) is not None and oc.content_de(g, m).category is perso[0]
              for m in (A, B)), r)

    g = _youcham_lent()
    D = Membre(7806, "arrivee_f", g)
    g.members.append(D)

    async def _deux_fois():
        r1 = await w.create_us_tickets(g, D)
        r2 = await w.create_us_tickets(g, D)      # avant l'événement de Discord
        await _sleep(0.12)
        return r1, r2
    r1, r2 = courir(_deux_fois())
    check("relancé avant que Discord ait tout envoyé : ni second salon, ni déplacement",
          len(r1[0]) == 1 and r2 == ([], []) and not g.deplaces
          and sum(1 for x in g.crees if x[0] == "salon") == 1, (r1, r2, g.deplaces, g.crees))

    g = _youcham_lent(n_plein=49)
    A, B = Membre(7803, "arrivee_c", g), Membre(7804, "arrivee_d", g)
    g.members += [A, B]
    r = courir(_ensemble(g, (A, B)))
    ca, cb = oc.content_de(g, A), oc.content_de(g, B)
    check("à 49 salons, deux arrivées : la 50e dans la catégorie, la suivante dans « … 2 »",
          all(not err for _cr, err in r) and ca is not None and cb is not None
          and ca.category is g.cat1 and cb.category.name == "📁 SALONS PERSO 2"
          and [x for x in g.crees if x[0] == "categorie"] == [("categorie", "📁 SALONS PERSO 2")],
          (r, getattr(getattr(cb, "category", None), "name", None), g.crees))
    check("… sans essai refusé par Discord : le salon tout juste créé est compté",
          g.refus == 0, g.refus)

    g = _youcham_lent(n_plein=49)
    g.vrais[g.cat1.id] = 50          # un 50e que le cache n'a pas encore vu
    C = Membre(7805, "arrivee_e", g)
    g.members.append(C)
    r = courir(_ensemble(g, (C,)))
    cc = oc.content_de(g, C)
    check("Discord dit « pleine » malgré le compte : reprise dans « … 2 », le VA a son salon",
          not r[0][1] and cc is not None and cc.category.name == "📁 SALONS PERSO 2"
          and g.refus == 1, (r, g.refus))

    # ── 7c. outils_communs.py absent du déploiement : Youl4b ne bouge pas
    print("  7c. module absent : Youl4b inchangé")
    gl = Guilde(YOUL4B, "l")
    dos = gl.ajoute_cat("bob")
    mn, cn = gl.ajoute("bob-menu", dos), gl.ajoute("bob-content", dos)
    adm_l = Membre(1, "proprio", gl)
    bob_l = Membre(9200, "bob", gl)
    gl.members += [adm_l, bob_l]
    _vrai_oc = sys.modules["outils_communs"]
    sys.modules["outils_communs"] = None      # « import outils_communs » lève
    try:
        check("module absent : Youl4b, le -content du dossier est toujours trouvé",
              u._us_content_target(types.SimpleNamespace(channel=mn, guild=gl, user=bob_l)) is cn)
        check("module absent : spoofer, download, numéro et menu ne lisent pas YouCham sur Youl4b",
              not spf._clic_us(mn) and not tl._clic_us(mn) and not nm._clic_us(mn)
              and not u._salon_outil_commun(mn) and tl.salon_de_livraison(
                  gl.ajoute("bob-download", dos), bob_l) is cn)
        it = Itx(gl, mn, adm_l)
        courir(w.Welcome.ticketsall.callback(_FauxW7(), it))
        texte = it.response.envois[0][0] if it.response.envois else ""
        check("module absent : /ticketsall sur Youl4b range comme avant",
              "illisible" not in texte and "dossier par personne" in texte, texte)
        g = youcham(n_va=0)
        it = Itx(g, g.archive, Membre(1, "proprio", g))
        courir(w.Welcome.ticketsall.callback(_FauxW7(), it))
        texte = it.response.envois[0][0] if it.response.envois else ""
        check("module absent : /ticketsall sur YouCham refuse (ne supprime rien)",
              "illisible" in texte, texte)
    finally:
        sys.modules["outils_communs"] = _vrai_oc

    # ── 7d. salons communs renommés à la main
    print("  7d. salons communs renommés")
    u.ensure_identity_emojis = u.ensure_reserve_emojis = u.ensure_action_emojis = _rien_emoji
    g = youcham(n_va=2, avec_outils=False)
    cat_p = courir(oc.categorie_perso(g))
    for va in g.vas:
        c = g.ajoute(w._us_ticket_name(va, "content"), cat_p)
        c.overwrites = {va: discord.PermissionOverwrite(view_channel=True)}
    V1, V2, ST = g.vas[0], g.vas[1], g.staff
    K1 = oc.content_de(g, V1)
    bot7 = _FauxBot([g])
    bot7.cogs = {"Spoofer": _FauxSpfCog(bot7), "Telechargement": _FauxDlCog(bot7)}
    courir(oc.assurer(g, bot7))
    cat_o = discord.utils.find(oc.est_categorie_outils, g.categories)
    R = {oc._cle(c.name): c for c in cat_o.text_channels}
    etat = oc._etat().get(str(YOUCHAM)) or {}
    check("assurer note l'id de 🧰 OUTILS et de ses quatre salons (data/, safe_json)",
          etat.get("categorie") == cat_o.id
          and etat.get("salons") == {k: R[k].id for k in oc.CLES}, etat)
    for k, nouveau in (("menu", "📋・menus-va"), ("spoofer", "📤・spoof"),
                       ("download", "⬇️・dl"), ("numero", "📱・phone")):
        R[k].name = nouveau
    cat_o.name = "🧰 TOOLS"
    check("renommés (salons et catégorie) : toujours reconnus, chacun son outil",
          all(oc.est_salon_outil(R[k], k) for k in oc.CLES)
          and oc.est_categorie_outils(cat_o) and not oc.est_salon_outil(R["menu"], "numero"))
    n_crees = len(g.crees)
    b = courir(oc.assurer(g, bot7))
    check("renommés : l'entretien ne recrée ni catégorie ni salon, ne repose aucun panneau",
          len(g.crees) == n_crees and not b["panneaux"] and not b["rates"], (b, g.crees[n_crees:]))
    # numéro : la carte chez le cliqueur, jamais dans le salon renommé
    nm.numgen.status = lambda: {"sms_ok": True, "mail_ok": True}

    class _FauxNum7(_FauxNum):
        clic_commun = nm.NumerosCog.clic_commun

    FN7 = _FauxNum7()
    courir(nm.NumerosCog.clic(FN7, Itx(g, R["numero"], V1), "sms"))
    check("📱 renommé « phone » : la carte dans le -content du cliqueur",
          FN7.bas == [K1] and FN7.achats == [("sms", K1, V1.id)], (FN7.bas, FN7.achats))
    poses_n = []
    nm.poser_panneau = _faux_poser
    nm._salon = lambda cid: {}
    try:
        courir(nm.NumerosCog._panneau_commun.coro(types.SimpleNamespace(
            bot=types.SimpleNamespace(guilds=[g]))))
    finally:
        nm.poser_panneau = _vrai_poser
        nm._salon = _sauve_n[0]
    check("Rem repose son panneau dans le salon renommé, et nulle part ailleurs",
          poses_n == ["📱・phone"], poses_n)
    # download et spoofer
    check("⬇️ renommé : livré chez le cliqueur ; staff nulle part",
          tl.salon_de_livraison(R["download"], V1) is K1
          and tl.salon_de_livraison(R["download"], ST) is None)
    DL7 = _FauxDlCog(_FauxBot())
    it = Itx(g, R["download"], V1, {"Telechargement": DL7})
    m = tl.ModalCompte(DL7)
    m.pseudo._value, m.combien._value = "sky.ards", "5"
    courir(m.on_submit(it))
    check("⬇️ renommé : le compte choisi part en éphémère, le panneau de tous n'est pas réécrit",
          it.response.envois and it.response.envois[0][1].get("ephemeral") is True
          and not R["download"].edites)
    it = Itx(g, R["spoofer"], ST, CSPF)
    courir(spf.SpfGo(3).callback(it))
    check("📤 renommé : staff refusé avant la fenêtre ; ses versions n'iraient nulle part",
          not it.response.modales and it.response.envois == [(oc.REFUS, {"ephemeral": True})]
          and spf._cible_content(Itx(g, R["spoofer"], ST, CSPF)) is None)
    it = Itx(g, R["spoofer"], V1, CSPF)
    fq = spf.FenetreQuantite(5)
    fq.nombre._value = "2"
    courir(fq.on_submit(it))
    check("📤 renommé : le 🔢 donne SON panneau en éphémère, celui du salon ne bouge pas",
          it.response.envois and it.response.envois[0][1].get("ephemeral") is True
          and not R["spoofer"].edites)
    # menu : le choix d'une model ne pose rien dans le salon renommé
    u._jb_models_marche = lambda marche="us": ["lola", "julia"]
    n_msgs = len(R["menu"].messages)
    it = Itx(g, R["menu"], V1, COGS, ephemere=True)
    courir(u._jb_model_panneau(it, UC, "lola"))
    check("📋 renommé : le panneau de la model en éphémère, rien d'épinglé dans le salon",
          it.response.envois and it.response.envois[0][1].get("ephemeral") is True
          and len(R["menu"].messages) == n_msgs and R["menu"].id not in u._JB_PANNEAU_COURANT
          and str(R["menu"].id) not in u._jb_panel_ids())
    # le filet tient même sans data/ (état perdu ET salons renommés)
    oc.ETAT.unlink()
    general = next(c for c in g.text_channels if c.name == "général")
    check("état perdu et salons renommés : plus reconnus par nom, mais rien n'y est livré",
          not oc.est_salon_outil(R["download"])
          and tl.salon_de_livraison(R["download"], ST) is None
          and tl.salon_de_livraison(R["download"], V1) is K1
          and spf._cible_content(Itx(g, R["spoofer"], ST, CSPF)) is None
          and nm._clic_commun(R["numero"]) and u._salon_outil_commun(R["menu"]))
    check("un salon public quelconque (« général ») de YouCham : livraison chez le cliqueur",
          tl.salon_de_livraison(general, V1) is K1 and tl.salon_de_livraison(general, ST) is None
          and spf._cible_content(Itx(g, general, V2, CSPF)) is oc.content_de(g, V2)
          and nm._clic_commun(general) and not nm._salon_commun(general))
    check("… mais un clic DANS un -content y reste (carte du numéro, menu des brutes)",
          not nm._clic_commun(K1) and tl.salon_de_livraison(K1, ST) is K1
          and not u._salon_outil_commun(K1))

    # ── 7e. pas de commande slash dans les salons communs
    print("  7e. lecture seule : pas de commande")
    for nom_cas, gg in (("sans vérification", youcham(n_va=0)),):
        d = oc.droits_outil(gg, (gg.me,))
        o = d[gg.default_role]
        check(f"salons communs ({nom_cas}) : ni commande slash, ni appli externe, ni activité",
              o.use_application_commands is False and o.use_external_apps is False
              and o.use_embedded_activities is False and o.view_channel is True
              and o.send_messages is False and d[gg.me].send_messages is True)
    _rv = oc._role_verifie
    gg = youcham(n_va=0)
    verifie = Role(55, "✅ Vérifié")
    oc._role_verifie = lambda guilde: verifie
    try:
        d = oc.droits_outil(gg, (gg.me,))
    finally:
        oc._role_verifie = _rv
    check("salons communs (avec vérification) : le vérifié voit, sans commande ; @everyone ne voit pas",
          d[gg.default_role].view_channel is False and d[verifie].view_channel is True
          and d[verifie].use_application_commands is False and d[verifie].send_messages is False)

    # ── 7f. changer de model : répondre AVANT d'effacer l'ancien panneau
    print("  7f. changer de model : réponse d'abord")
    g = youcham(n_va=1)
    cat_p = courir(oc.categorie_perso(g))
    kv = g.ajoute(w._us_ticket_name(g.vas[0], "content"), cat_p)
    kv.overwrites = {g.vas[0]: discord.PermissionOverwrite(view_channel=True)}
    it1 = Itx(g, g.outils["menu"], g.vas[0], COGS, ephemere=True)
    courir(u._jb_model_panneau(it1, UC, "lola"))
    ancien = it1.originale
    it2 = Itx(g, g.outils["menu"], g.vas[0], COGS, ephemere=True)
    vu = {}

    async def _effacer(*a, **k):
        vu["repondu"] = it2.response.is_done()
        ancien.supprime = True
    ancien.delete = _effacer
    courir(u._jb_model_panneau(it2, UC, "julia"))
    check("le nouveau panneau part AVANT l'effacement de l'ancien (10062 évité)",
          vu.get("repondu") is True and ancien.supprime, vu)
    check("… et c'est le nouveau qui est retenu pour la prochaine fois",
          u._DERNIER_PANNEAU_JB.get(g.vas[0].id) is it2.originale)
finally:
    w._membre_bot_admin = _sauve_7["adm"]
    u._jb_models_marche = _sauve_7["marche"]
    u.ensure_identity_emojis, u.ensure_reserve_emojis, u.ensure_action_emojis = _sauve_7["emojis"]
    nm.numgen.status = _sauve_7["status"]
    asyncio.sleep = _sleep


# ═══════════════════════════════════════════════════ 6. « YouLab » ══
print("6. Textes")
check("aucun texte dit à quelqu'un ne contient « YouLab »",
      not [t for t in TEXTES if "youlab" in t.lower()], [t for t in TEXTES if "youlab" in t.lower()])
check("ni le module, ni le refus, ni les noms de salons",
      "youlab" not in _src_oc.lower() and "youlab" not in oc.REFUS.lower())
check("refus court, tutoiement, sans montant",
      len(oc.REFUS) < 80 and "Tu " in oc.REFUS and "$" not in oc.REFUS and "€" not in oc.REFUS)

# ═════════════════════════════════════════════════════ isolation ══
check("isolation : rien écrit ni modifié dans le vrai data/", _instantane() == AVANT,
      sorted(set(_instantane().items()) ^ set(AVANT.items()))[:5])

print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
