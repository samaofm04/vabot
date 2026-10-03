# -*- coding: utf-8 -*-
"""tests_annonces_post.py — le salon « rappels » de Va IG.

Demandes du propriétaire (03/10/2026) :
  - « dans annonce le bot il dit c'est l'heure de poster et tout, c'est le mec
    qui clique mais tout le monde peut le faire, chacun voit son truc en vert,
    ça change que pour lui » ;
  - « c'est ici maintenant pour envoyer les notifs, et chacun voit son truc a
    lui » : le salon « ─│⏰┤-rappels » (catégorie NOTIFICATION), jamais
    « ⏱️・heure-de-post », qui est devenu le sien ;
  - « si le mec il clique pas sur j'ai posté mon reel, ça le relance 3 dans la
    journée et c'est tout » : relances anonymes, sans mention, sans MP ;
  - « un tous les lundi, jeudi et dimanche qui dit : bro si t'as un compte,
    faut avoir 3 comptes créés ».

Ce qui est vérifié :
  - le salon : « rappels » par son nom décoré, jamais heure-de-post (même par
    l'id ou renommé), jamais un salon d'une catégorie d'archives ;
  - horaire des annonces sur une journée simulée, deux VA sur le même bouton,
    réponse éphémère, message public jamais édité, bouton de la veille grisé ;
  - relances : heures prévues, au plus 3 par tâche, aucune quand tous les VA
    éligibles ont cliqué (sans rôle de model ou absent du cache : pas
    éligible), pas de rattrapage après une coupure, jamais moins d'une heure
    après une annonce tardive (posée à 16h59 : pas de relance à 17h00), pas de
    doublon après un redémarrage (état présent, perdu, ou qui nomme l'annonce
    sans la relance), texte du propriétaire à 21h pour la CTA, même bouton que
    l'annonce, grisées le lendemain ;
  - message comptes : lundi, jeudi, dimanche seulement, à partir de 12h, une
    fois par jour, retrouvé après redémarrage ; le bouton répond en éphémère
    avec 0, 1, 2 et 3 comptes de SES models Va IG (comptes US ignorés), et
    neutre sans fiche ou sans rôle ;
  - les autres serveurs : rien dans leur salon, rappels par ticket inchangés.

Tout se joue dans un dossier temporaire : faux Discord en mémoire, horloge
simulée (heure de Paris), jailbreak.json de bac à sable. Aucun appel réseau,
rien n'est écrit dans data/.
Lancement : python tests_annonces_post.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import logging
import pathlib
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                         # noqa: E402
import guild_features as gf            # noqa: E402
import jailbreak                       # noqa: E402
import safe_json                       # noqa: E402
from cogs import cta_reminder as c     # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


PARIS = ZoneInfo("Europe/Paris")
VAIG = 1505418484052394004
AUTRE = 1111111111111111111
SALON_ID = 1555954270304473118          # ─│⏰┤-rappels
HDP_ID = 1555926908229914684            # ⏱️・heure-de-post, au propriétaire
NOM_SALON = "─│⏰┤-rappels"
BOT_ID = 4242

# Les textes, écrits ici en dur : un mot changé dans le module doit se voir.
T_RELANCE = {
    "story": "📷 **Rappel — story du jour**\n"
             "Si ce n'est pas encore fait, poste ta story et clique le bouton vert.",
    "reel": "🎬 **Rappel — reel du jour**\n"
            "Si ce n'est pas encore fait, poste ton reel et clique le bouton vert.",
}
T_CTA_21 = ("📸 **Si t'as pas encore fait ta story CTA du jour, fais-la !**\n"
            "Clique le bouton vert quand c'est fait.")
T_CTA_23 = ("📸 **Dernier rappel — story CTA du jour**\n"
            "Si t'as pas encore fait ta story CTA, fais-la maintenant et clique le bouton vert.")
T_COMPTES = ("📱 **Tes comptes**\nBro, il faut avoir **3 comptes** créés. Si t'en as qu'un, "
             "crée les autres et ajoute-les avec 📷 Mes comptes dans ton ticket.")
T_NEUTRE = ("📷 Rien à afficher : ce bouton sert aux VA qui ont un ticket et une model "
            "sur ce serveur.")

# ------------------------------------------------------------ bac à sable --
# data/ réel : rien ne doit y apparaître ni y changer
_REEL = [BOT / "data" / n for n in ("annonces_post.json", "cta_reminder_state.json",
                                     "users.json", "guild_features.json", "jailbreak.json")]


def _empreinte(p):
    try:
        st = p.stat()
        return (st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        return None


_AVANT = {str(p): _empreinte(p) for p in _REEL}

TMP = pathlib.Path(tempfile.mkdtemp(prefix="annonces_post_test_"))
_SAUVE_C = {k: getattr(c, k) for k in ("DATA_DIR", "USERS_FILE", "STATE_FILE",
                                        "TRACKING_STATE_FILE", "ANNONCES_FILE", "_paris_now",
                                        "JOURS_COMPTES")}
_SAUVE_GF = {k: getattr(gf, k) for k in ("_FILE", "_THREADS_FILE", "_VACAT_FILE", "_SVID_FILE")}
_SAUVE_JB = {k: getattr(jailbreak, k) for k in ("DATA_DIR", "JAILBREAK_FILE", "BACKUP_DIR",
                                                "PREV_FILE", "TOMB_FILE")}
_SAUVE_LG = dict(jailbreak._LAST_GOOD)
c.DATA_DIR = TMP
c.USERS_FILE = TMP / "users.json"
c.STATE_FILE = TMP / "cta_reminder_state.json"
c.TRACKING_STATE_FILE = TMP / "account_tracking_state.json"
c.ANNONCES_FILE = TMP / "annonces_post.json"
gf._FILE = TMP / "guild_features.json"
gf._THREADS_FILE = TMP / "guild_threads.json"
gf._VACAT_FILE = TMP / "va_category.json"
gf._SVID_FILE = TMP / "server_identity.json"
(TMP / "jb").mkdir()
jailbreak.DATA_DIR = TMP / "jb"
jailbreak.JAILBREAK_FILE = TMP / "jb" / "jailbreak.json"
jailbreak.BACKUP_DIR = TMP / "jb" / "backups"
jailbreak.PREV_FILE = TMP / "jb" / "jailbreak.prev.json"
jailbreak.TOMB_FILE = TMP / "jb" / "tombstones.json"
jailbreak._LAST_GOOD["data"] = None
# Le message comptes (lundi, jeudi, dimanche) est mis à l'épreuve à part : les
# premières sections tombent un dimanche (04/10) et compteraient ses messages.
c.JOURS_COMPTES = ()

HEURE = [dt.datetime(2026, 10, 3, 9, 0, tzinfo=PARIS)]
c._paris_now = lambda: HEURE[0]


def a(jour: dt.date, h: int, m: int = 0):
    HEURE[0] = dt.datetime(jour.year, jour.month, jour.day, h, m, tzinfo=PARIS)


# logs du module : comptés, pas affichés
class _Journal(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lignes = []

    def emit(self, record):
        self.lignes.append((record.levelno, record.getMessage()))


JOURNAL = _Journal()
c.log.addHandler(JOURNAL)
c.log.setLevel(logging.DEBUG)
c.log.propagate = False


def logs(contient, niveau=logging.WARNING):
    return [m for lv, m in JOURNAL.lignes if lv >= niveau and contient in m]


# ---------------------------------------------------------- faux Discord --
class FakeUser:
    def __init__(self, uid, bot=False):
        self.id = uid
        self.bot = bot
        self.name = f"u{uid}"
        self.mention = f"<@{uid}>"


class FakeRole:
    def __init__(self, name, position):
        self.name = name
        self.position = position


class FakeMember(FakeUser):
    def __init__(self, uid, name, guild, roles=()):
        super().__init__(uid)
        self.name = name
        self.guild = guild
        self.roles = [FakeRole(r, 10 - i) for i, r in enumerate(roles)]


class FakeCategory:
    def __init__(self, cid, name):
        self.id = cid
        self.name = name


class FakeComp:
    def __init__(self, it):
        base = getattr(it, "item", it)          # DynamicItem -> bouton porté
        self.custom_id = getattr(it, "custom_id", None)
        self.disabled = bool(getattr(base, "disabled", False))
        self.label = getattr(base, "label", None)
        self.style = getattr(base, "style", None)
        self.emoji = getattr(base, "emoji", None)


class FakeRow:
    def __init__(self, children):
        self.children = children


def _composants(view):
    if view is None:
        return []
    return [FakeRow([FakeComp(it) for it in view.children])]


class FakeMessage:
    _n = [1000]

    def __init__(self, channel, author, content, view=None, **kw):
        FakeMessage._n[0] += 1
        self.id = FakeMessage._n[0]
        self.channel = channel
        self.author = author
        self.content = content
        self.view = view
        self.components = _composants(view)
        self.kwargs = kw
        self.edits = []
        self.created_at = HEURE[0].astimezone(dt.timezone.utc)
        self.cid0 = self.components[0].children[0].custom_id if self.components else None

    async def edit(self, **kw):
        self.edits.append(kw)
        if "content" in kw:
            self.content = kw["content"]
        if "view" in kw:
            self.view = kw["view"]
            self.components = _composants(kw["view"])
        return self

    def bouton(self):
        return self.components[0].children[0]


class _Partiel:
    def __init__(self, channel, mid):
        self.channel = channel
        self.id = mid

    async def edit(self, **kw):
        m = next((x for x in self.channel.messages if x.id == self.id), None)
        if m is None:
            raise discord.NotFound(_FauxHTTP(404), "Unknown Message")
        return await m.edit(**kw)


class _FauxHTTP:
    def __init__(self, status):
        self.status = status
        self.reason = "faux"


class FakeChannel:
    def __init__(self, cid, name, guild=None, category=None):
        self.id = cid
        self.name = name
        self.guild = guild
        self.category = category
        self.messages = []
        self.envois = 0
        self.echecs_envoi = 0           # nombre d'envois qui doivent échouer
        self.historique_lu = 0
        # "ok" ; "vide" = le bot n'a pas « Voir les anciens messages » (Discord
        # rend alors une liste VIDE, sans erreur) ; "refuse" = 403 à la lecture
        self.historique_mode = "ok"

    async def send(self, content=None, view=None, **kw):
        self.envois += 1
        if self.echecs_envoi > 0:
            self.echecs_envoi -= 1
            raise discord.Forbidden(_FauxHTTP(403), "Missing Permissions")
        auteur = self.guild.bot.user if self.guild is not None else FakeUser(BOT_ID, True)
        m = FakeMessage(self, auteur, content, view, **kw)
        self.messages.append(m)
        return m

    def history(self, limit=100):
        self.historique_lu += 1
        mode = self.historique_mode
        msgs = [] if mode == "vide" else list(reversed(self.messages))[:limit]

        async def gen():
            if mode == "refuse":
                raise discord.Forbidden(_FauxHTTP(403), "Missing Access")
            for m in msgs:
                yield m
        return gen()

    def get_partial_message(self, mid):
        return _Partiel(self, mid)


class FakeGuild:
    def __init__(self, gid, name, bot, salons=()):
        self.id = gid
        self.name = name
        self.bot = bot
        self.text_channels = []
        self.categories = []
        self.members = {}
        for s in salons:
            self.ajoute(s)

    def categorie(self, nom):
        cat = next((x for x in self.categories if x.name == nom), None)
        if cat is None:
            cat = FakeCategory(90000 + len(self.categories), nom)
            self.categories.append(cat)
        return cat

    def ajoute(self, ch, categorie=None):
        ch.guild = self
        if categorie is not None:
            ch.category = self.categorie(categorie)
        self.text_channels.append(ch)
        return ch

    def get_channel(self, cid):
        return next((ch for ch in self.text_channels if ch.id == int(cid)), None)

    def get_member(self, uid):
        return self.members.get(int(uid))


class FakeBot:
    def __init__(self):
        self.user = FakeUser(BOT_ID, bot=True)
        self.guilds = []
        self.vues = []
        self.dyn = []

    def add_view(self, v, message_id=None):
        self.vues.append(v)

    def add_dynamic_items(self, *its):
        self.dyn.extend(its)

    def get_channel(self, cid):
        for g in self.guilds:
            ch = g.get_channel(cid)
            if ch is not None:
                return ch
        return None

    def get_guild(self, gid):
        return next((g for g in self.guilds if g.id == int(gid)), None)

    async def fetch_channel(self, cid):
        raise discord.NotFound(_FauxHTTP(404), "Unknown Channel")

    async def wait_until_ready(self):
        await asyncio.Event().wait()          # jamais prêt : les boucles attendent


class FakeResponse:
    def __init__(self):
        self.envoyes = []
        self.editions = []
        self.differes = []

    async def send_message(self, content=None, *, view=None, ephemeral=False, **kw):
        self.envoyes.append({"content": content, "view": view, "ephemeral": ephemeral, **kw})

    async def edit_message(self, **kw):
        self.editions.append(kw)

    async def defer(self, **kw):
        self.differes.append(kw)


class FakeInteraction:
    def __init__(self, user, guild_id, message, guild=None):
        self.user = user
        self.guild_id = guild_id
        self.guild = guild
        self.message = message
        self.response = FakeResponse()
        self.data = {"custom_id": message.bouton().custom_id}


MOTIF = c.AnnoncePostButton.__discord_ui_compiled_template__
MOTIF_C = c.AnnonceComptesButton.__discord_ui_compiled_template__


async def cliquer(msg, user, guild_id=VAIG, guild=None):
    """Chemin du ViewStore : motif -> from_custom_id -> callback."""
    inter = FakeInteraction(user, guild_id, msg, guild)
    cid = inter.data["custom_id"]
    for cls in (c.AnnoncePostButton, c.AnnonceComptesButton):
        mt = cls.__discord_ui_compiled_template__.fullmatch(cid)
        if mt:
            item = await cls.from_custom_id(inter, None, mt)
            await item.callback(inter)
            return inter
    raise AssertionError(f"bouton inconnu : {cid}")


class _EtatF:
    """État minimal pour un vrai ViewStore de discord.py."""


async def cliquer_apres_redemarrage(vue, user, guild_id=VAIG, guild=None):
    """Le vrai parcours de discord.py après un redémarrage : ViewStore neuf qui
    ne connaît que les motifs de cog_load, message rebâti depuis les dicts de
    composants (View.from_message), from_custom_id puis callback."""
    from discord.components import _component_factory
    from discord.ui.view import ViewStore
    import types
    bot = FakeBot()
    cog = c.CTAReminderCog.__new__(c.CTAReminderCog)
    cog.bot = bot
    await cog.cog_load()
    store = ViewStore(_EtatF())
    for v in bot.vues:
        store.add_view(v)
    store.add_dynamic_items(*bot.dyn)
    msg = types.SimpleNamespace(
        id=987654, flags=types.SimpleNamespace(components_v2=False, ephemeral=False),
        components=[_component_factory(d) for d in vue.to_components()])
    cid = vue.children[0].custom_id
    inter = types.SimpleNamespace(user=user, guild_id=guild_id, guild=guild, message=msg,
                                  response=FakeResponse(),
                                  data={"custom_id": cid, "component_type": 2})
    store.dispatch_view(2, cid, inter)
    for _ in range(300):                   # la réponse comptes passe par un thread
        await asyncio.sleep(0.01)
        if inter.response.envoyes:
            break
    for _ in range(5):
        await asyncio.sleep(0)
    return inter


def monde(nom_salon=NOM_SALON, salon_id=SALON_ID, autre_salon=True):
    """Bot présent sur Va IG et sur un autre serveur. Va IG a aussi, AVANT le
    bon salon dans la liste, un vieux « rappels » rangé dans les archives et
    « ⏱️・heure-de-post », le salon du propriétaire : ni l'un ni l'autre ne
    doit rien recevoir. L'autre serveur a les deux noms et ne reçoit rien."""
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    JOURNAL.lignes.clear()
    bot = FakeBot()
    vaig = FakeGuild(VAIG, "Va IG", bot)
    for cat in ("NOTIFICATION", "📦 ARCHIVES", "amelia", "julia"):
        vaig.categorie(cat)
    vaig.archive = vaig.ajoute(FakeChannel(5, "rappels"), "📦 ARCHIVES")
    vaig.ajoute(FakeChannel(1, "📢・annonces"))
    vaig.hdp = vaig.ajoute(FakeChannel(HDP_ID, "⏱️・heure-de-post"), "NOTIFICATION")
    salon = vaig.ajoute(FakeChannel(salon_id, nom_salon), "NOTIFICATION") if nom_salon else None
    autre = FakeGuild(AUTRE, "YouLab AGENCY", bot)
    salon_autre = autre.ajoute(FakeChannel(2, NOM_SALON)) if autre_salon else None
    autre.hdp = autre.ajoute(FakeChannel(3, "⏱️・heure-de-post"))
    bot.guilds = [vaig, autre]
    return bot, vaig, salon, autre, salon_autre


def intacts(vaig, autre):
    """Les salons qui ne doivent JAMAIS rien recevoir."""
    return (vaig.hdp.messages == [] and vaig.archive.messages == []
            and all(ch.messages == [] for ch in autre.text_channels))


def ajouter_va(guild, uid, nom, ticket_id, roles=("Amelia",), cache=True):
    """Ticket va- dans la catégorie de la model, membre avec ses rôles ; rend
    la fiche users.json."""
    guild.ajoute(FakeChannel(ticket_id, f"va-{nom}"), (roles[0] if roles else "amelia").lower())
    if cache:
        guild.members[uid] = FakeMember(uid, nom, guild, roles)
    return {"channel_id": ticket_id, "identity": (roles[0] if roles else "amelia").lower()}


def run(coro):
    return asyncio.run(coro)


def perdre_etat():
    """data/ perdu (ou pas copié sur le VPS) : le fichier ET sa copie .prev,
    sinon safe_json restaure l'état et l'historique n'est jamais mis à l'épreuve."""
    for f in (c.ANNONCES_FILE, c.ANNONCES_FILE.with_suffix(".json.prev")):
        if f.exists():
            f.unlink()


def cids(salon):
    return [m.cid0 for m in salon.messages]


def de_tache(salon, t, jour8):
    return [m for m in salon.messages if m.cid0 == f"annonce_post:{t}:{jour8}"]


def relances_de(salon, t, jour8):
    return [m for m in de_tache(salon, t, jour8) if not m.content.startswith(c._entete_annonce(t))]


def heures(msgs):
    return [m.created_at.astimezone(PARIS).hour for m in msgs]


def mentions_aucune(m):
    am = m.kwargs.get("allowed_mentions")
    return (isinstance(am, discord.AllowedMentions) and not am.everyone and not am.users
            and not am.roles)


J1 = dt.date(2026, 10, 3)     # samedi
J2 = dt.date(2026, 10, 4)     # dimanche
J3 = dt.date(2026, 10, 5)     # lundi

try:
    # ======================================================== 1. drapeaux --
    check("Va IG reçoit les annonces", gf.annonces_post_enabled(VAIG)
          and gf.annonces_post_enabled(str(VAIG)))
    check("un autre serveur n'en reçoit pas", not gf.annonces_post_enabled(AUTRE))
    check("serveur inconnu (None) : pas d'annonce", not gf.annonces_post_enabled(None))
    check("Va IG : rappels par ticket toujours coupés", not gf.reminders_enabled(VAIG))
    check("autre serveur : rappels par ticket toujours actifs", gf.reminders_enabled(AUTRE))

    # ================================================== 1b. le bon salon --
    check("nom décoré reconnu", c._nom_nu(NOM_SALON) == "rappels"
          and c._nom_nu("⏰ Rappels") == "rappels" and c._nom_nu("⏱️・heure-de-post") == "heure-de-post")
    bot, vaig, salon, autre, salon_autre = monde()
    check("salon : « ─│⏰┤-rappels », pas le « rappels » des archives placé avant",
          c.salon_annonces(vaig) is salon, getattr(c.salon_annonces(vaig), "id", None))
    check("salon : rien sur l'autre serveur par ce chemin (pas dans ANNONCES_POST)",
          not gf.annonces_post_enabled(autre))
    bot, vaig, salon, autre, salon_autre = monde(nom_salon=None)
    check("seuls un « rappels » d'archives et heure-de-post : aucun salon",
          c.salon_annonces(vaig) is None)
    vaig.ajoute(FakeChannel(SALON_ID, "vieux-notifs"), "📦 ARCHIVES")
    check("le salon de repli rangé dans les archives : refusé, même par son id",
          c.salon_annonces(vaig) is None)
    bot, vaig, salon, autre, salon_autre = monde(nom_salon=None)
    vaig.hdp.name = "rappels"
    check("heure-de-post renommé « rappels » : refusé par son id", c.salon_annonces(vaig) is None)
    bot, vaig, salon, autre, salon_autre = monde(nom_salon=None)
    vaig.ajoute(FakeChannel(77, "⏱️・heure-de-post-rappels"), "NOTIFICATION")
    check("« heure-de-post-rappels » : refusé par son nom", c.salon_annonces(vaig) is None)
    bot, vaig, salon, autre, salon_autre = monde()
    autre_cand = FakeChannel(78, "rappels-managers")
    vaig.text_channels.insert(0, autre_cand)
    autre_cand.guild, autre_cand.category = vaig, vaig.categorie("NOTIFICATION")
    check("deux salons « rappels… » : le nom exact gagne", c.salon_annonces(vaig) is salon)
    check("constantes : heure-de-post interdit, repli = rappels",
          HDP_ID in c.SALONS_INTERDITS and c.SALON_ANNONCES_ID[str(VAIG)] == SALON_ID)

    # ============================================== 2. journée simulée --
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 9, 59)
    run(ap.tick())
    check("9h59 : rien", salon.messages == [], [m.content for m in salon.messages])

    a(J1, 10, 0)
    run(ap.tick())
    check("10h00 : une annonce (la story) dans « rappels »", len(salon.messages) == 1, len(salon.messages))
    story = salon.messages[0]
    b = story.bouton()
    check("story : custom_id du jour", b.custom_id == "annonce_post:story:20261003", b.custom_id)
    check("story : bouton vert", b.style == discord.ButtonStyle.success, b.style)
    check("story : libellé du bouton de la tâche", b.label == c.TASK_CONFIG["story"]["btn_label"], b.label)
    check("story : pas le custom_id de TaskDoneView", b.custom_id != "story_done_button")
    check("aucune mention possible (AllowedMentions.none)", mentions_aucune(story),
          story.kwargs.get("allowed_mentions"))
    check("texte : sans <@ ni @everyone", "<@" not in story.content and "@everyone" not in story.content)
    check("texte : emoji + libellé + date", story.content.startswith("📷 **Story du jour** — 03/10"),
          story.content[:60])
    check("texte : limite de la tâche", c.TASK_CONFIG["story"]["limit_note"] in story.content)
    check("texte : prérequis adaptés", "Si pas encore prêt, ignore ce message." in story.content)
    check("texte : pas le texte des tickets", "pour ne plus avoir de rappel" not in story.content
          and "ces rappels" not in story.content)
    check("texte : court", len(story.content) < 500, len(story.content))
    check("heure-de-post, archives et l'autre serveur : rien", intacts(vaig, autre))

    a(J1, 10, 1)
    run(ap.tick())
    a(J1, 10, 30)
    run(ap.tick())
    a(J1, 15, 59)
    run(ap.tick())
    check("10h01 / 10h30 / 15h59 : rien de neuf", len(salon.messages) == 1, len(salon.messages))
    lu = salon.historique_lu
    check("état présent : le salon n'est relu qu'une fois (au premier envoi)", lu == 1, lu)
    check("sans aucun VA : pas de relance à 12h ni 15h, dit une fois par heure",
          len(logs("pas de relance story a 15h", logging.INFO)) == 1,
          logs("pas de relance", logging.INFO))

    # redémarrage du bot à 16h20 : nouvelle instance, mémoire vide
    ap = c.AnnoncesPost(bot)
    a(J1, 16, 20)
    run(ap.tick())
    check("16h20 après redémarrage : le reel est posé", len(salon.messages) == 2
          and salon.messages[-1].bouton().custom_id == "annonce_post:reel:20261003",
          cids(salon))
    reel = salon.messages[-1]
    check("reel : texte du reel", reel.content.startswith("🎬 **Reel du jour** — 03/10")
          and c.TASK_CONFIG["reel"]["limit_note"] in reel.content, reel.content[:80])
    a(J1, 16, 21)
    run(ap.tick())
    ap = c.AnnoncesPost(bot)
    a(J1, 16, 25)
    run(ap.tick())
    check("16h21 / nouveau redémarrage 16h25 : reel posé une seule fois", len(salon.messages) == 2,
          len(salon.messages))

    a(J1, 19, 59)
    run(ap.tick())
    check("19h59 : rien de neuf", len(salon.messages) == 2)
    a(J1, 20, 0)
    run(ap.tick())
    cta = salon.messages[-1]
    check("20h00 : la story CTA", len(salon.messages) == 3
          and cta.bouton().custom_id == "annonce_post:cta:20261003"
          and cta.content.startswith("📸 **Story CTA du jour** — 03/10"), cids(salon))
    a(J1, 23, 30)
    run(ap.tick())
    check("23h30 : rien de neuf, et heure-de-post / archives / autre serveur toujours vides",
          len(salon.messages) == 3 and intacts(vaig, autre))
    etat = c._load_annonces()
    check("état : trois tâches du jour pour Va IG, rien pour l'autre",
          set(etat.get(str(VAIG), {})) == {"story", "reel", "cta"}
          and all(e["jour"] == "2026-10-03" for e in etat[str(VAIG)].values())
          and str(AUTRE) not in etat, etat)
    check("état : ids des messages et salon « rappels »", etat[str(VAIG)]["reel"]["message"] == reel.id
          and etat[str(VAIG)]["story"]["salon"] == SALON_ID, etat)

    # ====================================== 3. deux clics, même message --
    a(J1, 10, 5)
    u1, u2, u3 = FakeUser(501), FakeUser(502), FakeUser(503)
    contenu_avant = story.content
    i1 = run(cliquer(story, u1))
    i2 = run(cliquer(story, u2))
    for nom, i in (("VA 1", i1), ("VA 2", i2)):
        r = i.response.envoyes
        check(f"{nom} : une réponse éphémère", len(r) == 1 and r[0]["ephemeral"] is True, r)
        v = r[0]["view"] if r else None
        bt = v.children[0] if v is not None and v.children else None
        check(f"{nom} : son bouton vert grisé « ✅ Story postée »",
              bt is not None and bt.style == discord.ButtonStyle.success and bt.disabled
              and bt.label == "✅ Story postée", getattr(bt, "label", None))
        check(f"{nom} : texte « noté pour toi »", r and "Story notée pour toi" in (r[0]["content"] or ""),
              r and r[0]["content"])
        check(f"{nom} : aucune édition du message cliqué", i.response.editions == [])
    check("mark_done : VA 1 et VA 2 chacun pour soi",
          c.is_done_today("501", "story") and c.is_done_today("502", "story"))
    check("mark_done : un VA qui n'a pas cliqué reste à faire", not c.is_done_today("503", "story"))
    check("mark_done : le reel du VA 1 n'est pas touché", not c.is_done_today("501", "reel"))
    check("message public jamais édité", story.edits == [] and story.content == contenu_avant
          and story.bouton().label == c.TASK_CONFIG["story"]["btn_label"]
          and not story.bouton().disabled, story.edits)
    st = c._load_state()
    check("mark_done écrit dans le jour de Paris", "2026-10-03" in st
          and st["2026-10-03"].get("501", {}).get("story", {}).get("done") is True, st)

    i1b = run(cliquer(story, u1))
    r = i1b.response.envoyes
    bt = r[0]["view"].children[0] if r and r[0]["view"] is not None else None
    check("double clic : « déjà noté », éphémère", r and r[0]["ephemeral"] and "Déjà noté" in r[0]["content"],
          r)
    check("double clic : bouton vert grisé « déjà notée aujourd'hui »",
          bt is not None and bt.style == discord.ButtonStyle.success and bt.disabled
          and bt.label == "✅ Story déjà notée aujourd'hui", getattr(bt, "label", None))
    check("double clic : message public toujours intact", story.edits == [])
    # même clic, mais par le vrai ViewStore après un redémarrage
    u4 = FakeUser(504)
    ir = run(cliquer_apres_redemarrage(c.vue_annonce("story", "20261003"), u4))
    r = ir.response.envoyes
    check("après redémarrage (vrai ViewStore) : le bouton répond, en éphémère, une fois",
          len(r) == 1 and r[0]["ephemeral"] and r[0]["view"].children[0].label == "✅ Story postée"
          and ir.response.editions == [], r)
    check("après redémarrage : mark_done du cliqueur", c.is_done_today("504", "story"))
    ir2 = run(cliquer_apres_redemarrage(c.vue_annonce("story", "20261003"), u4))
    check("après redémarrage : double clic -> « déjà noté »",
          len(ir2.response.envoyes) == 1 and "Déjà noté" in ir2.response.envoyes[0]["content"],
          ir2.response.envoyes)
    i_reel = run(cliquer(reel, u3))
    bt = i_reel.response.envoyes[0]["view"].children[0]
    check("reel : accord masculin « ✅ Reel posté »", bt.label == "✅ Reel posté", bt.label)
    check("reel : mark_done du cliqueur seulement", c.is_done_today("503", "reel")
          and not c.is_done_today("501", "reel"))

    # ======================================== 4. lendemain : la veille --
    a(J2, 9, 0)
    iy = run(cliquer(story, u3))
    r = iy.response.envoyes
    check("bouton d'hier avant l'annonce du jour : « ce bouton était pour le 03/10 »",
          r and r[0]["ephemeral"] and r[0]["content"] == "⏳ Ce bouton était pour le 03/10.", r)
    check("bouton d'hier : ne valide pas aujourd'hui", not c.is_done_today("503", "story"))
    run(ap.tick())
    check("9h00 le lendemain : rien, la story d'hier pas encore grisée",
          len(salon.messages) == 3 and story.edits == [])

    a(J2, 10, 0)
    run(ap.tick())
    story2 = salon.messages[-1]
    check("10h00 le lendemain : nouvelle story", len(salon.messages) == 4
          and story2.bouton().custom_id == "annonce_post:story:20261004",
          story2.bouton().custom_id)
    check("story d'hier : une seule édition, bouton gris désactivé",
          len(story.edits) == 1 and story.bouton().disabled
          and story.bouton().style == discord.ButtonStyle.secondary
          and story.bouton().label == "Journée du 03/10 terminée", [story.edits, story.bouton().label])
    check("story d'hier : seule la vue change (texte intact, jamais supprimée)",
          set(story.edits[0]) == {"view"} and story.content == contenu_avant and story in salon.messages)
    check("story d'hier : le bouton gris n'est plus un bouton d'annonce",
          not MOTIF.fullmatch(story.bouton().custom_id or ""), story.bouton().custom_id)
    check("reel et CTA d'hier : pas encore touchés", reel.edits == [] and cta.edits == [])
    iy2 = run(cliquer(reel, u3))
    check("bouton reel d'hier, reel du jour pas encore posté : pas de « plus bas »",
          iy2.response.envoyes[0]["content"] == "⏳ Ce bouton était pour le 03/10.",
          iy2.response.envoyes)
    # le bouton d'hier encore affiché chez un VA (message pas rafraîchi)
    vieux = FakeMessage(salon, bot.user, "x", c.vue_annonce("story", "20261003"))
    iy3 = run(cliquer(vieux, u1))
    check("bouton story d'hier, story du jour posée : « Celui d'aujourd'hui est plus bas. »",
          iy3.response.envoyes[0]["content"]
          == "⏳ Ce bouton était pour le 03/10. Celui d'aujourd'hui est plus bas.",
          iy3.response.envoyes)
    check("clic d'hier : jamais d'édition", iy3.response.editions == [] and iy2.response.editions == [])
    i_auj = run(cliquer(story2, u1))
    check("story du jour : le VA 1 repart de zéro (nouveau jour)",
          i_auj.response.envoyes[0]["view"].children[0].label == "✅ Story postée"
          and c.is_done_today("501", "story"))

    a(J2, 16, 0)
    run(ap.tick())
    check("16h00 le lendemain : reel posté, reel d'hier grisé",
          len(salon.messages) == 5 and reel.bouton().disabled
          and reel.bouton().label == "Journée du 03/10 terminée" and cta.edits == [])

    # édition impossible (message d'hier effacé à la main) : log, on continue
    salon.messages.remove(cta)
    a(J2, 20, 0)
    run(ap.tick())
    check("CTA d'hier effacée : la CTA du jour part quand même",
          len(salon.messages) == 5 and salon.messages[-1].bouton().custom_id == "annonce_post:cta:20261004",
          cids(salon))
    check("CTA d'hier effacée : échec de l'édition journalisé", len(logs("pas grise")) == 1,
          logs("pas grise"))

    # ================================== 5. CTA trop tard / juste à temps --
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 23, 0)
    run(ap.tick())
    check("bot relancé à 23h00 sans rien posé : aucune annonce tardive", salon.messages == [],
          [m.content[:30] for m in salon.messages])
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 22, 59)
    run(ap.tick())
    check("22h59 : la CTA seule (reel fini à 21h59, story à 19h59)",
          cids(salon) == ["annonce_post:cta:20261003"], cids(salon))
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 20, 30)
    run(ap.tick())
    check("relance à 20h30 : reel puis CTA, dans l'ordre de la journée",
          cids(salon) == ["annonce_post:reel:20261003", "annonce_post:cta:20261003"], cids(salon))

    # ========================== 6. redémarrage sans état : historique --
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    premier = salon.messages[0]
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 5)
    run(ap.tick())
    etat = c._load_annonces()
    check("état perdu : l'annonce du jour est retrouvée, pas reposée",
          len(salon.messages) == 1 and etat.get(str(VAIG), {}).get("story", {}).get("message") == premier.id
          and etat[str(VAIG)]["story"].get("retrouve") is True, etat)
    check("état perdu : l'heure de l'annonce retrouvée vient du message",
          etat[str(VAIG)]["story"].get("pose") == "10:00", etat[str(VAIG)]["story"])
    # un message d'un humain qui porterait le custom_id du jour ne compte pas
    salon.messages.append(FakeMessage(salon, FakeUser(77), "copie", c.vue_annonce("reel", "20261003")))
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J1, 16, 0)
    run(ap.tick())
    check("bouton du jour posté par un autre que le bot : ignoré, le bot pose le reel",
          sum(1 for m in salon.messages if m.author.id == BOT_ID
              and m.bouton().custom_id == "annonce_post:reel:20261003") == 1
          and len(salon.messages) == 3, [(m.author.id, m.bouton().custom_id) for m in salon.messages])
    check("…et la story du jour, retrouvée, n'est pas reposée",
          sum(1 for m in salon.messages if m.bouton().custom_id == "annonce_post:story:20261003") == 1)
    # état perdu ET nouveau jour : l'annonce d'hier trouvée au salon est grisée
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J2, 10, 0)
    run(ap.tick())
    check("état perdu le lendemain : nouvelle story, celle d'hier (trouvée au salon) grisée",
          salon.messages[-1].bouton().custom_id == "annonce_post:story:20261004"
          and premier.bouton().disabled and premier.bouton().label == "Journée du 03/10 terminée",
          [premier.bouton().label, salon.messages[-1].bouton().custom_id])

    # ============================== 7. salon introuvable : un log par jour --
    bot, vaig, salon, autre, salon_autre = monde(nom_salon=None)
    ap = c.AnnoncesPost(bot)
    for h, m in ((10, 0), (10, 1), (10, 30), (16, 0), (20, 0)):
        a(J1, h, m)
        run(ap.tick())
    check("salon introuvable : un seul log sur la journée", len(logs("aucun salon")) == 1,
          logs("aucun salon"))
    check("salon introuvable : rien posté nulle part, ni dans heure-de-post ni aux archives",
          all(not ch.messages for ch in vaig.text_channels) and intacts(vaig, autre))
    a(J2, 10, 0)
    run(ap.tick())
    a(J2, 10, 1)
    run(ap.tick())
    check("salon introuvable : un log de plus le lendemain", len(logs("aucun salon")) == 2,
          logs("aucun salon"))

    # repli sur l'id : salon renommé sans « rappels »
    bot, vaig, salon, autre, salon_autre = monde(nom_salon="📌・notifs")
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    check("salon renommé : retrouvé par son id", len(salon.messages) == 1 and intacts(vaig, autre),
          len(salon.messages))
    # salon trouvé par le nom même si son id n'est pas celui de Va IG
    bot, vaig, salon, autre, salon_autre = monde(salon_id=123456)
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    check("salon trouvé par le nom (autre id)", len(salon.messages) == 1 and intacts(vaig, autre))

    # envoi refusé : nouvel essai chaque minute, un seul log
    bot, vaig, salon, autre, salon_autre = monde()
    salon.echecs_envoi = 2
    ap = c.AnnoncesPost(bot)
    for m in (0, 1, 2, 3):
        a(J1, 10, m)
        run(ap.tick())
    check("envoi refusé deux fois : posté à la 3e minute, une seule fois",
          len(salon.messages) == 1 and salon.envois == 3, (len(salon.messages), salon.envois))
    check("envoi refusé : un seul log", len(logs("pas poste")) == 1, logs("pas poste"))

    # ====== 7b. état impossible à écrire (disque plein, data/ en lecture seule) --
    # safe_json.write ne lève pas : il rend False. Sans garde en mémoire, la
    # tâche paraît due à chaque minute et seul l'historique empêchait de
    # reposter — or un bot sans « Voir les anciens messages » reçoit une liste
    # VIDE de Discord : une annonce par minute pendant toute la fenêtre.
    def bloquer(nom):
        """Le parent du fichier est un FICHIER : l'écriture échoue sans lever."""
        bloc = TMP / "bloque"
        if bloc.is_dir():
            shutil.rmtree(bloc)
        bloc.write_text("x", encoding="utf-8")
        return bloc / nom

    for mode in ("vide", "refuse", "ok"):
        bot, vaig, salon, autre, salon_autre = monde()
        c.ANNONCES_FILE = bloquer("annonces_post.json")
        salon.historique_mode = mode
        ap = c.AnnoncesPost(bot)
        for m in range(10):
            a(J1, 10, m)
            run(ap.tick())
        check(f"état non écrit, historique {mode} : la story posée UNE fois en 10 minutes",
              len(salon.messages) == 1, len(salon.messages))
        check(f"état non écrit, historique {mode} : un seul avertissement « pas enregistré »",
              len(logs("pas enregistr")) == 1, logs("pas enregistr"))
        check(f"état non écrit, historique {mode} : le salon n'est pas relu chaque minute",
              salon.historique_lu == 1, salon.historique_lu)
        check(f"état non écrit, historique {mode} : pas de « retrouvée » à chaque minute",
              len(logs("retrouvee", logging.INFO)) == 0, logs("retrouvee", logging.INFO))
        a(J1, 16, 0)
        run(ap.tick())
        a(J1, 16, 1)
        run(ap.tick())
        check(f"état non écrit, historique {mode} : le reel part quand même, une fois",
              cids(salon) == ["annonce_post:story:20261003", "annonce_post:reel:20261003"],
              cids(salon))
        c.ANNONCES_FILE = TMP / "annonces_post.json"
    # état non écrit, annonce retrouvée par l'historique après un redémarrage :
    # gardée en mémoire, pas relue ni re-journalisée chaque minute
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    c.ANNONCES_FILE = bloquer("annonces_post.json")
    ap = c.AnnoncesPost(bot)
    lu0 = salon.historique_lu
    for m in range(1, 6):
        a(J1, 10, m)
        run(ap.tick())
    check("état non écrit, annonce retrouvée : pas reposée, salon relu une seule fois",
          len(salon.messages) == 1 and salon.historique_lu - lu0 == 1,
          (len(salon.messages), salon.historique_lu - lu0))
    check("état non écrit, annonce retrouvée : « retrouvée » journalisée une fois",
          len(logs("retrouvee", logging.INFO)) == 1, logs("retrouvee", logging.INFO))
    c.ANNONCES_FILE = TMP / "annonces_post.json"

    # clic alors que l'état des rappels ne s'écrit pas : jamais « noté » à tort
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    story_b = salon.messages[0]
    c.STATE_FILE = bloquer("cta_reminder_state.json")
    u9 = FakeUser(901)
    check("mark_done rend False quand l'état ne s'écrit pas", c.mark_done("900", "story") is False)
    for n in (1, 2):
        ib = run(cliquer(story_b, u9))
        r = ib.response.envoyes
        check(f"état non écrit, clic {n} : « pas pu le noter », éphémère, sans bouton vert",
              len(r) == 1 and r[0]["ephemeral"] is True
              and r[0]["content"] == "⚠️ Pas pu le noter, réessaie dans un instant."
              and r[0]["view"] is None, r)
    check("état non écrit : le clic n'est pas compté", not c.is_done_today("901", "story"))
    check("état non écrit : échec journalisé", len(logs("pas note")) >= 1, logs("pas note"))
    c.STATE_FILE = TMP / "cta_reminder_state.json"
    check("mark_done rend True quand l'état s'écrit", c.mark_done("900", "story") is True)
    ib = run(cliquer(story_b, u9))
    check("état revenu : le clic suivant est noté, en vert",
          ib.response.envoyes and ib.response.envoyes[0]["view"] is not None
          and ib.response.envoyes[0]["view"].children[0].label == "✅ Story postée"
          and c.is_done_today("901", "story"), ib.response.envoyes)
    check("état non écrit : message public jamais édité", story_b.edits == [])

    # ======================================== 8. relances : une journée --
    bot, vaig, salon, autre, salon_autre = monde()
    autre.ajoute(FakeChannel(32, "va-jules"))
    users = {
        "701": ajouter_va(vaig, 701, "zoe77", 41, ("Amelia",)),
        "702": ajouter_va(vaig, 702, "marc88", 42, ("Julia",)),
        "703": ajouter_va(vaig, 703, "sansrole99", 43, ()),                  # aucun rôle de model
        "704": ajouter_va(vaig, 704, "absent55", 44, ("Amelia",), cache=False),  # pas en cache
        "705": {"channel_id": 32, "identity": "jules"},                       # ticket ailleurs
    }
    safe_json.write(c.USERS_FILE, users)
    m701, m702 = vaig.members[701], vaig.members[702]
    tickets = [vaig.get_channel(i) for i in (41, 42, 43, 44)]
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    story = salon.messages[0]
    a(J1, 11, 59)
    run(ap.tick())
    check("relances : rien avant 12h", len(salon.messages) == 1, cids(salon))
    a(J1, 12, 0)
    run(ap.tick())
    check("12h00 : une relance story", len(salon.messages) == 2, cids(salon))
    r12 = salon.messages[-1]
    check("relance story : texte exact", r12.content == T_RELANCE["story"], r12.content)
    check("relance : MÊME bouton que l'annonce (custom_id, libellé, vert)",
          r12.bouton().custom_id == story.bouton().custom_id == "annonce_post:story:20261003"
          and r12.bouton().label == story.bouton().label
          and r12.bouton().style == discord.ButtonStyle.success, r12.bouton().custom_id)
    check("relance : aucune mention possible", mentions_aucune(r12), r12.kwargs)
    check("relance : anonyme (ni <@, ni @everyone, ni nom de VA)",
          "<@" not in r12.content and "@everyone" not in r12.content
          and not any(n in r12.content for n in ("zoe77", "marc88", "sansrole99", "absent55")))
    check("relance : rien dans les tickets ni en MP (aucun autre envoi)",
          all(t.messages == [] for t in tickets) and intacts(vaig, autre))
    check("VA absent du cache des membres : ignoré, dit une fois",
          len(logs("absent(s) du cache")) == 1 and "704" in logs("absent(s) du cache")[0],
          logs("absent"))
    # L'état ne nomme pas encore la relance de 12h : le salon est relu une fois
    # avant de la poser (comme avant la première annonce), pas à chaque minute.
    check("relance : le salon relu une fois avant de la poser", salon.historique_lu == 2,
          salon.historique_lu)
    for m in (1, 30, 59):
        a(J1, 12, m)
        run(ap.tick())
    check("12h01 / 12h30 / 12h59 : pas de deuxième relance dans l'heure", len(salon.messages) == 2)
    check("12h01 / 12h30 / 12h59 : le salon n'est plus relu", salon.historique_lu == 2,
          salon.historique_lu)
    check("relance enregistrée dans l'état (heure -> message)",
          c._load_annonces()[str(VAIG)]["story"]["relances"] == {"12": r12.id},
          c._load_annonces()[str(VAIG)]["story"])

    a(J1, 12, 10)
    ic = run(cliquer(r12, m701))
    rr = ic.response.envoyes
    check("clic sur la relance : éphémère, noté pour le seul cliqueur",
          len(rr) == 1 and rr[0]["ephemeral"] and "Story notée pour toi" in rr[0]["content"]
          and c.is_done_today("701", "story") and not c.is_done_today("702", "story"), rr)
    check("clic sur la relance : ni la relance ni l'annonce éditées",
          r12.edits == [] and story.edits == [] and ic.response.editions == [])
    run(cliquer(story, m702))
    a(J1, 15, 0)
    run(ap.tick())
    a(J1, 15, 30)
    run(ap.tick())
    check("15h00 : tous les VA éligibles ont cliqué -> pas de relance "
          "(le sans-rôle et l'absent ne comptent pas)", len(salon.messages) == 2, cids(salon))
    check("15h00 : « les 2 VA ont clique » dit une fois",
          len(logs("pas de relance story a 15h, les 2 VA ont clique", logging.INFO)) == 1,
          logs("pas de relance", logging.INFO))

    a(J1, 16, 0)
    run(ap.tick())
    a(J1, 17, 0)
    run(ap.tick())
    r17 = salon.messages[-1]
    check("17h00 : relance reel, texte exact", len(salon.messages) == 4
          and r17.content == T_RELANCE["reel"] and r17.cid0 == "annonce_post:reel:20261003",
          (cids(salon), r17.content))
    ap = c.AnnoncesPost(bot)
    a(J1, 17, 30)
    run(ap.tick())
    check("redémarrage à 17h30, état présent : pas de relance en double", len(salon.messages) == 4)
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    lu0 = salon.historique_lu
    a(J1, 17, 45)
    run(ap.tick())
    etat = c._load_annonces()[str(VAIG)]
    check("redémarrage à 17h45, état perdu : la relance de 17h retrouvée au salon, pas reposée",
          len(salon.messages) == 4 and etat["reel"]["relances"] == {"17": r17.id}
          and etat["reel"].get("retrouve") is True, (cids(salon), etat.get("reel")))
    check("état perdu : la story retrouvée garde sa relance de 12h",
          etat["story"]["relances"] == {"12": r12.id}, etat.get("story"))
    check("état perdu : le salon relu une seule fois pour tout le tour",
          salon.historique_lu - lu0 == 1, salon.historique_lu - lu0)
    a(J1, 18, 0)
    run(ap.tick())
    check("18h00 : story déjà faite par tous -> pas de relance", len(salon.messages) == 4)
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J1, 19, 0)
    run(ap.tick())
    check("19h00, état perdu : la relance reel de 19h part (seule 17h est au salon)",
          len(salon.messages) == 5 and salon.messages[-1].content == T_RELANCE["reel"], cids(salon))
    a(J1, 20, 0)
    run(ap.tick())
    a(J1, 21, 0)
    run(ap.tick())
    check("21h00 : relance reel ET relance CTA, une chacune", len(salon.messages) == 8
          and cids(salon)[-2:] == ["annonce_post:reel:20261003", "annonce_post:cta:20261003"],
          cids(salon))
    r21c = salon.messages[-1]
    check("CTA 21h : les mots du propriétaire", r21c.content == T_CTA_21, r21c.content)
    run(cliquer(salon.messages[-2], m701))
    a(J1, 22, 0)
    run(ap.tick())
    check("22h00 : relance CTA (le reel n'a pas d'heure 22)", len(salon.messages) == 9
          and salon.messages[-1].cid0 == "annonce_post:cta:20261003"
          and salon.messages[-1].content == T_CTA_21, cids(salon))
    a(J1, 23, 0)
    run(ap.tick())
    check("23h00 : dernière relance CTA", len(salon.messages) == 10
          and salon.messages[-1].content == T_CTA_23, salon.messages[-1].content)
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J1, 23, 10)
    run(ap.tick())
    a(J1, 23, 59)
    run(ap.tick())
    check("redémarrage à 23h10, état perdu : la relance de 23h n'est pas reposée",
          len(salon.messages) == 10, cids(salon))
    check("relances retrouvées : la CTA les reprend dans l'état",
          set(c._load_annonces()[str(VAIG)]["cta"]["relances"]) == {"21", "22", "23"},
          c._load_annonces()[str(VAIG)].get("cta"))
    nb = {t: heures(relances_de(salon, t, "20261003")) for t in ("story", "reel", "cta")}
    check("au plus 3 relances par tâche, aux heures prévues",
          nb == {"story": [12], "reel": [17, 19, 21], "cta": [21, 22, 23]}, nb)
    check("annonce + relances : un seul bouton par message, toujours celui du jour",
          all(len(m.components[0].children) == 1 for m in salon.messages))
    check("journée de relances : heure-de-post, archives, tickets, autre serveur intacts",
          intacts(vaig, autre) and all(t.messages == [] for t in tickets))

    # ===================== 9. relances : la veille passe au gris aussi --
    rel_story = relances_de(salon, "story", "20261003")
    rel_reel = relances_de(salon, "reel", "20261003")
    rel_cta = relances_de(salon, "cta", "20261003")
    a(J2, 10, 0)
    run(ap.tick())
    check("lendemain 10h : la relance story d'hier grisée avec son annonce (par le salon relu)",
          all(len(m.edits) == 1 and m.bouton().disabled
              and m.bouton().label == "Journée du 03/10 terminée" for m in rel_story + [story]),
          [(m.cid0, len(m.edits)) for m in rel_story + [story]])
    check("relance grisée : texte intact, jamais supprimée",
          rel_story[0].content == T_RELANCE["story"] and rel_story[0] in salon.messages)
    a(J2, 16, 0)
    run(ap.tick())
    check("lendemain 16h : les 3 relances reel d'hier grisées, une édition chacune",
          len(rel_reel) == 3 and all(len(m.edits) == 1 and m.bouton().disabled for m in rel_reel),
          [len(m.edits) for m in rel_reel])
    # Discord rend un historique vide : seul l'état nomme les relances d'hier
    salon.historique_mode = "vide"
    a(J2, 20, 0)
    run(ap.tick())
    check("lendemain 20h, historique vide : les relances CTA d'hier grisées grâce à l'état",
          len(rel_cta) == 3 and all(len(m.edits) == 1 and m.bouton().disabled for m in rel_cta),
          [len(m.edits) for m in rel_cta])
    salon.historique_mode = "ok"
    a(J2, 12, 0)

    # ============================ 10. relances : coupures et cas limites --
    def monde_va(*vas):
        w = monde()
        us = {str(uid): ajouter_va(w[1], uid, nom, tid, roles, cache)
              for uid, nom, tid, roles, cache in vas}
        safe_json.write(c.USERS_FILE, us)
        return w

    UN_VA = (701, "zoe77", 41, ("Amelia",), True)
    # bot coupé de 10h05 à 12h59 puis de 15h01 à 18h30 : rien n'est rattrapé
    bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    a(J1, 13, 0)
    run(ap.tick())
    a(J1, 14, 59)
    run(ap.tick())
    check("coupure pendant 12h : pas de relance rattrapée à 13h ni 14h59",
          relances_de(salon, "story", "20261003") == [], cids(salon))
    a(J1, 15, 0)
    run(ap.tick())
    a(J1, 18, 30)
    run(ap.tick())
    a(J1, 18, 31)
    run(ap.tick())
    check("coupure de 15h01 à 18h30 : une seule relance story à 18h30, pas d'empilement",
          heures(relances_de(salon, "story", "20261003")) == [15, 18],
          heures(relances_de(salon, "story", "20261003")))
    check("18h30 : le reel (dans sa fenêtre) est posé, sans relance de 17h",
          len(de_tache(salon, "reel", "20261003")) == 1
          and relances_de(salon, "reel", "20261003") == [], cids(salon))
    # annonce posée pendant une heure de relance : pas de relance dans la foulée
    bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
    ap = c.AnnoncesPost(bot)
    a(J1, 12, 10)
    run(ap.tick())
    a(J1, 12, 40)
    run(ap.tick())
    check("bot démarré à 12h10 : l'annonce story seule, pas de relance dans la même heure",
          cids(salon) == ["annonce_post:story:20261003"], cids(salon))
    a(J1, 15, 0)
    run(ap.tick())
    check("…puis la relance de 15h", heures(relances_de(salon, "story", "20261003")) == [15])
    # Annonce posée à hh:5x (bot revenu en retard) : l'heure de relance suivante
    # commence une minute plus tard. Comparer les seules heures laissait partir
    # « si ce n'est pas encore fait » une minute après « c'est l'heure ».
    for (h0, m0), h1, t in (((11, 59), 12, "story"), ((16, 59), 17, "reel"),
                            ((20, 59), 21, "cta"), ((14, 58), 15, "story")):
        bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
        ap = c.AnnoncesPost(bot)
        a(J1, h0, m0)
        run(ap.tick())
        for m in (0, 1, 30, m0 - 1):
            a(J1, h1, m)
            run(ap.tick())
        check(f"annonce {t} posée à {h0}h{m0}, bot qui tourne : pas de relance à {h1}h00, "
              f"{h1}h30 ni {h1}h{m0 - 1:02d} (moins d'une heure après)",
              relances_de(salon, t, "20261003") == [],
              [(m.created_at.astimezone(PARIS).strftime("%H:%M"), m.content[:30])
               for m in de_tache(salon, t, "20261003")])
        a(J1, h1, m0)
        run(ap.tick())
        check(f"annonce {t} posée à {h0}h{m0} : la relance de {h1}h part à {h1}h{m0}, "
              f"une heure après, une seule",
              [m.created_at.astimezone(PARIS).strftime("%H:%M")
               for m in relances_de(salon, t, "20261003")] == [f"{h1}:{m0}"],
              [m.created_at.astimezone(PARIS).strftime("%H:%M")
               for m in relances_de(salon, t, "20261003")])
    # même chose quand l'annonce n'est connue que par le salon (état perdu)
    bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
    ap = c.AnnoncesPost(bot)
    a(J1, 16, 59)
    run(ap.tick())
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J1, 17, 0)
    run(ap.tick())
    check("annonce reel de 16h59 retrouvée au salon à 17h00 : pas de relance dans la foulée",
          relances_de(salon, "reel", "20261003") == [], cids(salon))
    # relance postée mais pas enregistrée (disque plein, ou coupure pendant
    # l'envoi), puis redémarrage dans l'heure : l'état nomme l'annonce, pas la
    # relance. Sans relecture du salon, elle repartait une seconde fois.
    for mode_rel in ("disque plein", "coupure pendant l'envoi"):
        bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
        ap = c.AnnoncesPost(bot)
        a(J1, 10, 0)
        run(ap.tick())
        etat_10h = c._load_annonces()
        if mode_rel == "disque plein":
            c.ANNONCES_FILE = bloquer("annonces_post.json")
        a(J1, 12, 0)
        run(ap.tick())
        c.ANNONCES_FILE = TMP / "annonces_post.json"
        safe_json.write(c.ANNONCES_FILE, etat_10h)        # l'état d'avant la relance
        r_12 = relances_de(salon, "story", "20261003")
        ap = c.AnnoncesPost(bot)
        lu0 = salon.historique_lu
        for m in (30, 31, 45, 59):
            a(J1, 12, m)
            run(ap.tick())
        check(f"relance pas enregistrée ({mode_rel}), redémarrage à 12h30 : pas reposée",
              heures(relances_de(salon, "story", "20261003")) == [12],
              heures(relances_de(salon, "story", "20261003")))
        check(f"relance pas enregistrée ({mode_rel}) : le salon relu une seule fois dans l'heure",
              salon.historique_lu - lu0 == 1, salon.historique_lu - lu0)
        check(f"relance pas enregistrée ({mode_rel}) : l'état la reprend",
              len(r_12) == 1 and c._load_annonces()[str(VAIG)]["story"].get("relances")
              == {"12": r_12[0].id}, c._load_annonces().get(str(VAIG), {}).get("story"))
        a(J1, 15, 0)
        run(ap.tick())
        check(f"relance pas enregistrée ({mode_rel}) : 15h part normalement",
              heures(relances_de(salon, "story", "20261003")) == [12, 15],
              heures(relances_de(salon, "story", "20261003")))
    # 23h sans annonce CTA du jour : pas de relance, salon relu une seule fois
    bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
    ap = c.AnnoncesPost(bot)
    for m in (0, 1, 2, 30):
        a(J1, 23, m)
        run(ap.tick())
    check("23h sans annonce CTA : aucune relance", salon.messages == [], cids(salon))
    check("23h sans annonce CTA : salon relu une fois, dit une fois",
          salon.historique_lu == 1
          and len(logs("pas de relance cta a 23h, l'annonce du jour n'a pas ete postee",
                        logging.INFO)) == 1, (salon.historique_lu, logs("pas de relance", logging.INFO)))
    # personne d'éligible : un sans-rôle et un absent du cache
    bot, vaig, salon, autre, salon_autre = monde_va((703, "sansrole99", 43, (), True),
                                                    (704, "absent55", 44, ("Amelia",), False))
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    for m in (0, 1, 2):
        a(J1, 12, m)
        run(ap.tick())
    check("aucun VA éligible : pas de relance", relances_de(salon, "story", "20261003") == [])
    check("aucun VA éligible : dit une fois",
          len(logs("pas de relance story a 12h, aucun VA", logging.INFO)) == 1,
          logs("pas de relance", logging.INFO))
    # une fiche dont le ticket est ailleurs ne rend pas éligible ici
    bot, vaig, salon, autre, salon_autre = monde()
    autre.ajoute(FakeChannel(32, "va-jules"))
    vaig.members[705] = FakeMember(705, "jules", vaig, ("Amelia",))
    safe_json.write(c.USERS_FILE, {"705": {"channel_id": 32}})
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    a(J1, 12, 0)
    run(ap.tick())
    check("membre de Va IG dont le ticket est sur un autre serveur : pas éligible",
          relances_de(salon, "story", "20261003") == [] and intacts(vaig, autre))
    # envoi refusé : réessayé dans l'heure, un seul log
    bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
    ap = c.AnnoncesPost(bot)
    a(J1, 10, 0)
    run(ap.tick())
    salon.echecs_envoi = 1
    for m in (0, 1, 2):
        a(J1, 12, m)
        run(ap.tick())
    check("relance refusée une fois : postée à la minute suivante, une seule",
          heures(relances_de(salon, "story", "20261003")) == [12]
          and len(logs("relance story de 12h pas postee")) == 1,
          (heures(relances_de(salon, "story", "20261003")), logs("pas postee")))
    # état des annonces impossible à écrire : une relance quand même, pas une par minute
    for mode in ("ok", "vide"):
        bot, vaig, salon, autre, salon_autre = monde_va(UN_VA)
        salon.historique_mode = mode
        ap = c.AnnoncesPost(bot)
        a(J1, 10, 0)
        run(ap.tick())
        c.ANNONCES_FILE = bloquer("annonces_post.json")
        for m in range(8):
            a(J1, 12, m)
            run(ap.tick())
        check(f"état non écrit, historique {mode} : UNE relance en 8 minutes",
              heures(relances_de(salon, "story", "20261003")) == [12],
              heures(relances_de(salon, "story", "20261003")))
        c.ANNONCES_FILE = TMP / "annonces_post.json"

    # ================================= 11. message comptes : le calendrier --
    c.JOURS_COMPTES = _SAUVE_C["JOURS_COMPTES"]
    check("message comptes : lundi, jeudi, dimanche à 12h", tuple(c.JOURS_COMPTES) == (0, 3, 6)
          and c.HEURE_COMPTES == 12)

    def comptes(salon):
        return [m for m in salon.messages if (m.cid0 or "").startswith("annonce_comptes:")]

    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    for jour in (dt.date(2026, 10, 3), dt.date(2026, 10, 6), dt.date(2026, 10, 7),
                 dt.date(2026, 10, 9)):
        for h in (12, 18, 23):
            a(jour, h, 0)
            run(ap.tick())
    check("samedi, mardi, mercredi, vendredi : aucun message comptes", comptes(salon) == [],
          [m.cid0 for m in comptes(salon)])

    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J3, 11, 59)
    run(ap.tick())
    check("lundi 11h59 : pas encore", comptes(salon) == [])
    a(J3, 12, 0)
    run(ap.tick())
    mc = comptes(salon)
    check("lundi 12h00 : un message comptes", len(mc) == 1, len(mc))
    mc = mc[0]
    check("message comptes : texte exact", mc.content == T_COMPTES, mc.content)
    bt = mc.bouton()
    check("message comptes : un seul bouton « 📷 Mes comptes », persistant par le jour",
          len(mc.components[0].children) == 1 and bt.custom_id == "annonce_comptes:20261005"
          and bt.label == "Mes comptes" and str(bt.emoji) == "📷", (bt.custom_id, bt.label, bt.emoji))
    check("message comptes : aucune mention possible, aucun <@", mentions_aucune(mc)
          and "<@" not in mc.content and "@everyone" not in mc.content)
    for h, m in ((12, 1), (18, 0), (23, 59)):
        a(J3, h, m)
        run(ap.tick())
    check("lundi 12h01 / 18h / 23h59 : toujours un seul", len(comptes(salon)) == 1)
    ap = c.AnnoncesPost(bot)
    a(J3, 13, 0)
    run(ap.tick())
    check("redémarrage, état présent : pas reposé", len(comptes(salon)) == 1)
    perdre_etat()
    ap = c.AnnoncesPost(bot)
    a(J3, 14, 0)
    run(ap.tick())
    check("redémarrage, état perdu : retrouvé au salon, pas reposé",
          len(comptes(salon)) == 1
          and c._load_annonces()[str(VAIG)]["comptes"] == {"jour": "2026-10-05", "message": mc.id,
                                                           "salon": SALON_ID, "retrouve": True},
          c._load_annonces().get(str(VAIG), {}).get("comptes"))
    a(dt.date(2026, 10, 6), 0, 0)
    run(ap.tick())
    a(dt.date(2026, 10, 6), 12, 0)
    run(ap.tick())
    check("mardi : rien de neuf", len(comptes(salon)) == 1)
    a(dt.date(2026, 10, 8), 12, 0)
    run(ap.tick())
    check("jeudi 12h : le message du jeudi", [m.cid0 for m in comptes(salon)]
          == ["annonce_comptes:20261005", "annonce_comptes:20261008"], [m.cid0 for m in comptes(salon)])
    a(dt.date(2026, 10, 11), 12, 0)
    run(ap.tick())
    check("dimanche 12h : le message du dimanche", comptes(salon)[-1].cid0 == "annonce_comptes:20261011")
    check("le bouton comptes des jours d'avant reste cliquable (jamais grisé)",
          all(m.edits == [] for m in comptes(salon)))
    check("message comptes : jamais sur l'autre serveur, ni heure-de-post, ni archives",
          intacts(vaig, autre))
    bot, vaig, salon, autre, salon_autre = monde()
    ap = c.AnnoncesPost(bot)
    a(J3, 23, 30)
    run(ap.tick())
    a(dt.date(2026, 10, 6), 0, 0)
    run(ap.tick())
    check("bot démarré lundi 23h30 : le message part, rien le mardi à minuit",
          [m.cid0 for m in comptes(salon)] == ["annonce_comptes:20261005"], cids(salon))

    # =========================== 12. message comptes : le bouton répond --
    safe_json.write(jailbreak.JAILBREAK_FILE, {
        "amelia": {
            "vas": [{"name": "zero_va", "discord_username": "zero_va"},
                    {"name": "un_va", "discord_username": "un_va"},
                    {"name": "deuxc_va", "discord_username": "deuxc_va"},
                    {"name": "trois_va", "discord_username": "trois_va"},
                    {"name": "site_va", "discord_username": ""}],   # fiche du site, sans pseudo
            "accounts": [{"username": "amelia.un1", "va": "un_va"},
                         {"username": "amelia.dc1", "va": "deuxc_va"},
                         {"username": "amelia.dc2", "va": "deuxc_va"},
                         {"username": "amelia.trois1", "va": "trois_va"},
                         {"username": "amelia.trois2", "va": "trois_va"},
                         {"username": "amelia.site1", "va": "site_va"},
                         {"username": "amelia.autre", "va": "quelquun"}]},
        "julia": {
            "vas": [{"name": "trois_va", "discord_username": "trois_va"},
                    {"name": "Lea", "discord_username": "lea_dc"}],   # fiche nommée autrement
            "accounts": [{"username": "julia_trois_3", "va": "trois_va"},
                         {"username": "julia.lea1", "va": "Lea"}]},
        # Identité US : six VA sont arrivés sur Va IG avec une identité US
        # (welcome.identite_pour_serveur). Leurs comptes US ne sont pas des
        # comptes Va IG : ils ne doivent ni compter ni s'afficher.
        "themikkiangel": {
            "vas": [{"name": "Noum", "discord_username": "noum0075"},
                    {"name": "trois_va", "discord_username": "trois_va"}],
            "accounts": [{"username": f"mikki.us{i}", "va": "Noum"} for i in range(1, 5)]
                        + [{"username": "mikki.trois", "va": "trois_va"}]},
    })
    jb_avant = _empreinte(jailbreak.JAILBREAK_FILE)
    bot, vaig, salon, autre, salon_autre = monde()
    autre.ajoute(FakeChannel(32, "va-jules"))
    us = {
        "801": ajouter_va(vaig, 801, "zero_va", 51, ("Amelia",)),
        "802": ajouter_va(vaig, 802, "un_va", 52, ("Amelia",)),
        "803": ajouter_va(vaig, 803, "trois_va", 53, ("Amelia", "Julia")),
        "804": ajouter_va(vaig, 804, "site_va", 54, ("Amelia",)),
        "805": ajouter_va(vaig, 805, "sansrole_va", 55, ()),
        "808": ajouter_va(vaig, 808, "deuxc_va", 58, ("Amelia",)),
        "809": ajouter_va(vaig, 809, "noum0075", 59, ("Amelia",)),
        "810": ajouter_va(vaig, 810, "lea_dc", 60, ("Julia",)),
        "807": {"channel_id": 32},
    }
    vaig.members[806] = FakeMember(806, "sansfiche_va", vaig, ("Amelia",))
    vaig.members[807] = FakeMember(807, "ailleurs_va", vaig, ("Amelia",))
    safe_json.write(c.USERS_FILE, us)
    etat_rappels_avant = c._load_state()
    ap = c.AnnoncesPost(bot)
    a(J3, 12, 0)
    run(ap.tick())
    mc = comptes(salon)[0]
    a(J3, 12, 5)
    attendu = {
        801: "📷 **Tes comptes enregistrés : 0**\n"
             "Il t'en manque 3 : crée-les et ajoute-les avec 📷 Mes comptes dans ton ticket.",
        802: "📷 **Tes comptes enregistrés : 1**\n• @amelia.un1\n"
             "Il t'en manque 2 : crée-les et ajoute-les avec 📷 Mes comptes dans ton ticket.",
        808: "📷 **Tes comptes enregistrés : 2**\n• @amelia.dc1\n• @amelia.dc2\n"
             "Il t'en manque 1 : crée-le et ajoute-le avec 📷 Mes comptes dans ton ticket.",
        803: "📷 **Tes comptes enregistrés : 3**\n• @amelia.trois1\n• @amelia.trois2\n"
             "• @julia\\_trois\\_3\n✅ T'as tes 3 comptes.",
        804: "📷 **Tes comptes enregistrés : 1**\n• @amelia.site1\n"
             "Il t'en manque 2 : crée-les et ajoute-les avec 📷 Mes comptes dans ton ticket.",
        809: "📷 **Tes comptes enregistrés : 0**\n"
             "Il t'en manque 3 : crée-les et ajoute-les avec 📷 Mes comptes dans ton ticket.",
        810: "📷 **Tes comptes enregistrés : 1**\n• @julia.lea1\n"
             "Il t'en manque 2 : crée-les et ajoute-les avec 📷 Mes comptes dans ton ticket.",
        805: T_NEUTRE,
        806: T_NEUTRE,
        807: T_NEUTRE,
    }
    noms = {801: "0 compte", 802: "1 compte", 808: "2 comptes",
            803: "3 comptes (deux models, son compte US ignoré)",
            804: "fiche du site sans pseudo", 809: "4 comptes US, aucun sur Va IG",
            810: "fiche Va IG reliée par le pseudo Discord, nom différent",
            805: "sans rôle de model", 806: "sans fiche", 807: "ticket sur un autre serveur"}
    for uid, txt in attendu.items():
        ic = run(cliquer(mc, vaig.members[uid], guild=vaig))
        rr = ic.response.envoyes
        check(f"bouton comptes, {noms[uid]} : réponse éphémère exacte",
              len(rr) == 1 and rr[0]["ephemeral"] is True and rr[0]["content"] == txt
              and rr[0]["view"] is None and ic.response.editions == [],
              rr and rr[0]["content"])
        check(f"bouton comptes, {noms[uid]} : aucune mention possible",
              isinstance(rr[0].get("allowed_mentions"), discord.AllowedMentions)
              and not rr[0]["allowed_mentions"].users and not rr[0]["allowed_mentions"].everyone)
    check("bouton comptes : le message public jamais édité", mc.edits == [])
    check("bouton comptes : rien d'écrit (ni comptes ni clics)",
          _empreinte(jailbreak.JAILBREAK_FILE) == jb_avant and c._load_state() == etat_rappels_avant)
    ir = run(cliquer_apres_redemarrage(c.vue_comptes("20261005"), vaig.members[802], guild=vaig))
    check("bouton comptes après redémarrage (vrai ViewStore) : répond, éphémère",
          len(ir.response.envoyes) == 1 and ir.response.envoyes[0]["ephemeral"]
          and ir.response.envoyes[0]["content"] == attendu[802], ir.response.envoyes)
    a(dt.date(2026, 10, 8), 9, 0)
    vieux = FakeMessage(salon, bot.user, T_COMPTES, c.vue_comptes("20261001"))
    ic = run(cliquer(vieux, vaig.members[803], guild=vaig))
    check("bouton comptes d'un autre jour : toujours valable",
          ic.response.envoyes and ic.response.envoyes[0]["content"] == attendu[803],
          ic.response.envoyes)
    # guild absente de l'interaction : retrouvée par le client
    import types as _types
    inter = FakeInteraction(vaig.members[802], VAIG, mc)
    inter.client = _types.SimpleNamespace(get_guild=bot.get_guild)
    run(c.repondre_clic_comptes(inter))
    check("interaction sans guild : retrouvée par son id", inter.response.envoyes
          and inter.response.envoyes[0]["content"] == attendu[802], inter.response.envoyes)
    check("texte comptes : au-delà de 3, toujours « ✅ »",
          c.texte_comptes_du_va(["a", "b", "c", "d"]).endswith("✅ T'as tes 3 comptes."))

    # ============ 13. les autres serveurs : rien posé, rappels par ticket --
    bot, vaig, salon, autre, salon_autre = monde()
    ticket_vaig = vaig.ajoute(FakeChannel(31, "va-1-amelia"))
    ticket_autre = autre.ajoute(FakeChannel(32, "va-jules"))
    vaig.members[601] = FakeMember(601, "amelia_va", vaig, ("Amelia",))
    autre.members[602] = FakeMember(602, "jules", autre, ())
    safe_json.write(c.USERS_FILE, {"601": {"channel_id": 31}, "602": {"channel_id": 32}})
    cog = c.CTAReminderCog.__new__(c.CTAReminderCog)
    cog.bot = bot
    cog.annonces = c.AnnoncesPost(bot)
    a(J1, 16, 0)
    run(c.CTAReminderCog.check_loop.coro(cog))
    run(cog.annonces.tick())
    check("rappel par ticket : l'autre serveur reçoit son reel comme avant",
          len(ticket_autre.messages) == 1 and "<@602>" in ticket_autre.messages[0].content
          and ticket_autre.messages[0].bouton().custom_id == "reel_done_button",
          [m.content[:40] for m in ticket_autre.messages])
    check("rappel par ticket : rien dans le ticket Va IG", ticket_vaig.messages == [])
    check("annonce : Va IG seulement (story encore dans sa fenêtre + reel)",
          cids(salon) == ["annonce_post:story:20261003", "annonce_post:reel:20261003"]
          and salon_autre.messages == [], (cids(salon), len(salon_autre.messages)))
    for h in (17, 19, 21):
        a(J1, h, 0)
        run(cog.annonces.tick())
    a(J3, 12, 0)
    run(cog.annonces.tick())
    check("relances et message comptes : rien sur l'autre serveur (salons « rappels » et "
          "heure-de-post compris)", all(ch.messages == [] for ch in autre.text_channels
                                         if ch is not ticket_autre) and vaig.hdp.messages == [])
    check("relances : Va IG en a bien reçu (le VA 601 n'a pas cliqué)",
          heures(relances_de(salon, "reel", "20261003")) == [17, 19, 21])
    check("annonce : aucune trace de l'autre serveur dans l'état", str(AUTRE) not in c._load_annonces())

    # ================================== 14. custom_id aller-retour --
    async def _aller_retour():
        res = []
        for t in ("reel", "story", "cta"):
            for j8 in ("20261003", "20270101", "20261231"):
                cid = c.custom_id_annonce(t, j8)
                mt = MOTIF.fullmatch(cid)
                it = await c.AnnoncePostButton.from_custom_id(None, None, mt) if mt else None
                res.append((cid, bool(mt) and mt["tache"] == t and mt["jour"] == j8,
                            it is not None and it.custom_id == cid and it.tache == t and it.jour8 == j8,
                            len(cid) <= 100))
        for j8 in ("20261005", "20270101"):
            cid = c.custom_id_comptes(j8)
            mt = MOTIF_C.fullmatch(cid)
            it = await c.AnnonceComptesButton.from_custom_id(None, None, mt) if mt else None
            res.append((cid, bool(mt) and mt["jour"] == j8,
                        it is not None and it.custom_id == cid and it.jour8 == j8, len(cid) <= 100))
        return res
    rr = run(_aller_retour())
    check("custom_id : motif -> tâche et jour, pour chaque tâche et le message comptes",
          all(x[1] for x in rr), rr)
    check("custom_id : from_custom_id rend le même bouton", all(x[2] for x in rr), rr)
    check("custom_id : sous la limite Discord de 100", all(x[3] for x in rr))
    refus = ["reel_done_button", "story_done_button", "cta_done_button",
             "annonce_post:foo:20261003", "annonce_post:reel:2026100",
             "annonce_post:reel:20261003x", "annonce_post_fini:reel:20261003",
             "xannonce_post:reel:20261003", "annonce_comptes:20261005"]
    check("custom_id : rien d'autre ne correspond (TaskDoneView, gris, comptes, déformés)",
          not any(MOTIF.fullmatch(x) for x in refus), [x for x in refus if MOTIF.fullmatch(x)])
    refus_c = ["annonce_comptes:2026100", "annonce_comptes:20261005x", "annonce_post:reel:20261003",
               "track_c1_actif"]
    check("custom_id comptes : rien d'autre ne correspond",
          not any(MOTIF_C.fullmatch(x) for x in refus_c), [x for x in refus_c if MOTIF_C.fullmatch(x)])
    v = c.vue_annonce("cta", "20261003")
    check("vue d'annonce : un seul bouton, vert, persistant (timeout None)",
          len(v.children) == 1 and v.timeout is None and v.children[0].item.style == discord.ButtonStyle.success)
    v = c.vue_comptes("20261005")
    check("vue comptes : un seul bouton, persistant (timeout None)",
          len(v.children) == 1 and v.timeout is None)

    # ======================= 15. enregistrement : TaskDoneView toujours là --
    bot = FakeBot()
    cog = c.CTAReminderCog.__new__(c.CTAReminderCog)
    cog.bot = bot
    run(cog.cog_load())
    ids_vues = {getattr(it, "custom_id", None) for v in bot.vues for it in v.children}
    check("TaskDoneView : les trois boutons des tickets toujours enregistrés",
          {"reel_done_button", "story_done_button", "cta_done_button"} <= ids_vues
          and sum(isinstance(v, c.TaskDoneView) for v in bot.vues) == 3, ids_vues)
    check("AccountTrackingView toujours enregistrée",
          any(isinstance(v, c.AccountTrackingView) for v in bot.vues))
    check("boutons d'annonce et de comptes enregistrés (add_dynamic_items)",
          c.AnnoncePostButton in bot.dyn and c.AnnonceComptesButton in bot.dyn, bot.dyn)
    check("suivi des comptes par ticket : toujours coupé sur Va IG (SANS_RAPPELS)",
          "1505418484052394004" in gf.SANS_RAPPELS and not gf.reminders_enabled(VAIG))

    async def _cycle():
        b2 = FakeBot()
        cg = c.CTAReminderCog(b2)
        await asyncio.sleep(0)
        ok = cg.check_loop.is_running() and cg.annonces_loop.is_running()
        cg.cog_unload()
        await asyncio.sleep(0)
        return ok, isinstance(cg.annonces, c.AnnoncesPost)
    ok, inst = run(_cycle())
    check("le cog démarre les deux boucles et les arrête", ok and inst)

    src_cog = (BOT / "cogs" / "cta_reminder.py").read_text(encoding="utf-8")
    check("aucune commande slash ajoutée (bot principal à 100/100)",
          src_cog.count("@app_commands.command(") == 2, src_cog.count("@app_commands.command("))
    check("le module ne nomme plus heure-de-post que pour l'interdire",
          "SALON_ANNONCES_NOM = \"rappels\"" in src_cog and "1555926908229914684" in src_cog
          and src_cog.count("1555926908229914684") == 1)
    src_w = (BOT / "cogs" / "welcome.py").read_text(encoding="utf-8")
    check("pont d'activité (Welcome.on_interaction) toujours en place",
          "async def on_interaction(self, interaction)" in src_w
          and "cog._record(interaction.user.id)" in src_w)

finally:
    for k, v in _SAUVE_C.items():
        setattr(c, k, v)
    for k, v in _SAUVE_GF.items():
        setattr(gf, k, v)
    for k, v in _SAUVE_JB.items():
        setattr(jailbreak, k, v)
    jailbreak._LAST_GOOD.clear()
    jailbreak._LAST_GOOD.update(_SAUVE_LG)
    shutil.rmtree(TMP, ignore_errors=True)

_APRES = {str(p): _empreinte(p) for p in _REEL}
check("rien écrit ni modifié dans le vrai data/", _AVANT == _APRES,
      {k: (_AVANT[k], _APRES[k]) for k in _AVANT if _AVANT[k] != _APRES[k]})

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
