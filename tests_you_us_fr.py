"""You US et You FR : deux serveurs branchés comme YouCham, un marché chacun.

Propriétaire, 10/11/2026 : « un serveur uniquement dédié pour le marché
français … et un exprès pour le marché US, pour mes pôles à moi. Ça reprend
le même style que YouLab Spam … le seul truc qui importe, c'est le bot avec
le menu, le spoofer, download, numéro, email. Ça, il faut que je le retrouve
au niveau des deux nouveaux serveurs », et, pour You FR, « banger Emma,
banger Amelia » comme sur Va IG.

Ce que ce fichier prouve, avec de faux objets Discord (aucun réseau, rien
d'écrit dans data/) :
  1. Les deux serveurs sont dans LA liste (guild_features) : serveurs US,
     outils communs, sans le 📊・click-et-sub de YouCham ; leurs ids ne sont
     recopiés dans aucun module.
  2. Leur bridage vit dans le code (tout sauf « statut »), sans dépendre du
     fichier data/guild_features.json ; une entrée du fichier passe devant.
  3. Le marché suit le SERVEUR : « fr » sur You FR, « us » sur You US, quel
     que soit le rôle du membre ; Va IG, Youl4b et YouCham ne changent pas.
  4. L'arrivée d'un membre : son salon perso (create_us_tickets), jamais le
     ticket VA classique.
  5. Les 💥・banger-<model> de You FR restent ouverts à tous : le tour des
     10 minutes ne les cache pas, ne pose aucun droit au nom d'un VA, et
     ferme quand même l'écriture. Sur Va IG, rien ne change.

Lancer depuis la racine du dépôt : python tests_you_us_fr.py
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

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


YOUL4B = 1535758943324999711
YOUCHAM = 1565640097146347533
VA_IG = 1505418484052394004
TWITTER = 1445108485090971710

# Rien de ce fichier ne doit écrire dans le vrai data/.
DATA = BOT / "data"


def _instantane():
    if not DATA.exists():
        return {}
    return {str(p.relative_to(DATA)): p.stat().st_mtime_ns
            for p in DATA.rglob("*") if p.is_file()}


AVANT = _instantane()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="you_us_fr_"))


def courir(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════ 1. la liste ══
print("1. La liste")
import guild_features as gf  # noqa: E402

YOU_US, YOU_FR = int(gf.YOU_US_GUILD_ID), int(gf.YOU_FR_GUILD_ID)
check("deux ids distincts, de vrais ids Discord, ni Youl4b ni YouCham ni Va IG",
      YOU_US != YOU_FR and min(YOU_US, YOU_FR) > 10 ** 17
      and not {YOU_US, YOU_FR} & {YOUL4B, YOUCHAM, VA_IG, TWITTER}, (YOU_US, YOU_FR))
check("serveurs US (id entier, texte, objet)",
      all(gf.is_us_guild(x) for g in (YOU_US, YOU_FR)
          for x in (g, str(g), types.SimpleNamespace(id=g))))
check("outils communs sur les deux ; pas Youl4b",
      gf.outils_communs(YOU_US) and gf.outils_communs(YOU_FR) and gf.outils_communs(YOUCHAM)
      and not gf.outils_communs(YOUL4B))
check("pas de 📊・click-et-sub : la page de Lia reste celle de YouCham",
      not gf.clics_et_subs(YOU_US) and not gf.clics_et_subs(YOU_FR) and gf.clics_et_subs(YOUCHAM))
check("is_youl4b : toujours Youl4b seul",
      gf.is_youl4b(YOUL4B) and not any(gf.is_youl4b(g) for g in (YOU_US, YOU_FR, YOUCHAM)))
check("ni « numéro seul » ni rappels publics de Va IG",
      not any(gf.numero_seul(g) or gf.annonces_post_enabled(g) for g in (YOU_US, YOU_FR)))
check("noms courts : You US, You FR",
      gf.US_GUILDS[str(YOU_US)] == "You US" and gf.US_GUILDS[str(YOU_FR)] == "You FR")

# Leurs ids ne vivent que dans guild_features.
_copies = []
for p in list(BOT.glob("*.py")) + list((BOT / "cogs").glob("*.py")):
    if p.name.startswith("tests_") or p.name == "guild_features.py":
        continue
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if str(YOU_US) in t or str(YOU_FR) in t:
        _copies.append(p.name)
check("les ids de You US et You FR ne sont recopiés dans aucun module", not _copies, _copies)


# ══════════════════════════════════════════════ 2. le bridage ══
print("2. Fonctions du serveur")
_sauve_file = gf._FILE
try:
    gf._FILE = TMP / "guild_features.json"          # fichier absent
    attendu = {"contenu", "onboarding", "clics", "liens", "tickets", "rappels"}
    check("sans fichier : tout sauf « statut », sur les deux serveurs",
          gf.get_features(YOU_US) == attendu and gf.get_features(YOU_FR) == attendu,
          (gf.get_features(YOU_US), gf.get_features(YOU_FR)))
    check("… « tickets » actif (le salon perso naît à l'arrivée), « statut » non",
          gf.enabled(YOU_FR, "tickets") and gf.enabled(YOU_US, "contenu")
          and not gf.enabled(YOU_FR, "statut") and not gf.enabled(YOU_US, "statut"))
    check("un serveur inconnu garde TOUTES les fonctions",
          gf.get_features(TWITTER) == set(gf.ALL_FEATURES)
          and gf.get_features(YOUL4B) == set(gf.ALL_FEATURES))
    gf._FILE.write_text('{"%d": ["contenu"], "%d": ["contenu", "tickets"]}' % (YOU_FR, YOUCHAM),
                        encoding="utf-8")
    check("une entrée du fichier passe devant le code (You FR bridé à la main)",
          gf.get_features(YOU_FR) == {"contenu"} and gf.get_features(YOU_US) == attendu)
    check("YouCham : toujours son entrée du fichier",
          gf.get_features(YOUCHAM) == {"contenu", "tickets"})
finally:
    gf._FILE = _sauve_file


# ═══════════════════════════════════════════════ 3. le marché ══
print("3. Le marché suit le serveur")
import cogs.welcome as w  # noqa: E402
import cogs.user as u  # noqa: E402

check("guild_features.marche_serveur : fr / us, None ailleurs",
      gf.marche_serveur(YOU_FR) == "fr" and gf.marche_serveur(YOU_US) == "us"
      and gf.marche_serveur(str(YOU_FR)) == "fr"
      and all(gf.marche_serveur(g) is None for g in (YOUL4B, YOUCHAM, VA_IG, None, "x")))
check("SANS_ROLE_JAILBREAK les reprend, Va IG reste « fr »",
      w.SANS_ROLE_JAILBREAK.get(YOU_FR) == "fr" and w.SANS_ROLE_JAILBREAK.get(YOU_US) == "us"
      and w.SANS_ROLE_JAILBREAK.get(VA_IG) == "fr" and len(w.SANS_ROLE_JAILBREAK) == 3,
      w.SANS_ROLE_JAILBREAK)
check("marche_unique : You US et You FR seulement (Va IG garde ses salons par model)",
      w.marche_unique(types.SimpleNamespace(id=YOU_FR)) and w.marche_unique(types.SimpleNamespace(id=YOU_US))
      and not any(w.marche_unique(types.SimpleNamespace(id=g)) for g in (VA_IG, YOUL4B, YOUCHAM))
      and not w.marche_unique(None))


def membre(gid, *roles):
    return types.SimpleNamespace(guild=types.SimpleNamespace(id=gid),
                                 roles=[types.SimpleNamespace(name=r) for r in roles])


check("You FR : menu FR sans aucun rôle", u.marche_du_membre(membre(YOU_FR)) == "fr")
check("You FR : menu FR même avec un rôle « Jailbreak US » posé à la main",
      u.marche_du_membre(membre(YOU_FR, "Jailbreak US")) == "fr")
check("You US : menu US, même avec « Jailbreak FR »",
      u.marche_du_membre(membre(YOU_US)) == "us"
      and u.marche_du_membre(membre(YOU_US, "Jailbreak FR")) == "us")
check("Youl4b et YouCham inchangés : le rôle décide, « us » par défaut",
      u.marche_du_membre(membre(YOUL4B, "Jailbreak FR")) == "fr"
      and u.marche_du_membre(membre(YOUL4B)) == "us"
      and u.marche_du_membre(membre(YOUCHAM, "Jailbreak FR")) == "fr"
      and u.marche_du_membre(membre(YOUCHAM)) == "us")
check("Va IG inchangé : « fr »", u.marche_du_membre(membre(VA_IG, "Jailbreak US")) == "fr")
check("menu ouvert à tous, comme sur Youl4b",
      u._jb_can_use(types.SimpleNamespace(guild=types.SimpleNamespace(id=YOU_FR), user=None))
      and u._jb_can_use(types.SimpleNamespace(guild=types.SimpleNamespace(id=YOU_US), user=None)))

# aucun rôle de marché posé ni créé là-bas
crees = []


class GuildeRoles:
    def __init__(self, gid):
        self.id, self.roles = gid, []

    async def create_role(self, **kw):
        crees.append(kw.get("name"))
        return types.SimpleNamespace(name=kw.get("name"))


r_fr = courir(w.appliquer_roles_marche(GuildeRoles(YOU_FR)))
r_us = courir(w.appliquer_roles_marche(GuildeRoles(YOU_US)))
check("appliquer_roles_marche : rien posé, aucun rôle Jailbreak créé",
      r_fr == (0, 0, 0) and r_us == (0, 0, 0) and not crees, (r_fr, r_us, crees))


# ════════════════════════════════════════════════ 4. l'arrivée ══
print("4. Arrivée d'un membre")
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
gf._FILE = TMP / "absent.json"
try:
    w.create_us_tickets = _faux_us
    w.setup_va_ticket = _faux_classique
    w.load_pending = lambda: {}
    w.save_pending = lambda d: appels.append(("save_pending",))
    w.load_welcome_config = lambda: {"auto_create_ticket_on_join": True}
    # déjà VA sur Va IG : sa fiche vise un salon d'un autre serveur
    w.load_users = lambda: {"77": {"channel_id": 123, "identity": "emma"}}
    w._verif_porte = lambda g: None
    w._verif_config = lambda g: None

    def arrivee(gid, uid=77, bot=False):
        appels.clear()
        g = types.SimpleNamespace(id=gid, name="x")
        m = types.SimpleNamespace(id=uid, name="nouveau", guild=g, bot=bot)
        courir(w.Welcome.on_member_join(FauxCog(), m))
        return list(appels)

    for gid, nom in ((YOU_US, "You US"), (YOU_FR, "You FR")):
        a = arrivee(gid)
        check(f"{nom} : l'arrivée passe par create_us_tickets, jamais par le ticket classique",
              a == [("us", gid, 77)], a)
        check(f"{nom} : un bot qui arrive n'a rien", not arrivee(gid, bot=True))
    a = arrivee(TWITTER)
    check("un autre serveur garde le parcours classique", a == [("accueillir", TWITTER, 77)], a)
finally:
    for k, v in _sauve_w.items():
        setattr(w, k, v)
    gf._FILE = _sauve_file

check("le salon perso seul : suffixes = -content, comme YouCham",
      w.suffixes_us(types.SimpleNamespace(id=YOU_US)) == ("content",)
      and w.suffixes_us(types.SimpleNamespace(id=YOU_FR)) == ("content",))


# ═══════════════════════════ 5. les bangers par model, ouverts à tous ══
print("5. 💥・banger-<model> de You FR")
PO = discord.PermissionOverwrite
_RIEN = object()


class Cible:
    def __init__(self, i, nom, bot=False, managed=False):
        self.id, self.name, self.bot, self.managed = i, nom, bot, managed

    def __eq__(self, o):
        return isinstance(o, Cible) and o.id == self.id

    def __hash__(self):
        return hash(self.id)


class Salon:
    _n = 5000

    def __init__(self, nom, ows=None):
        Salon._n += 1
        self.id, self.name, self.category = Salon._n, nom, None
        self._ow = dict(ows or {})
        self.edits, self.poses = [], []

    @property
    def overwrites(self):
        return {k: PO(**dict(v)) for k, v in self._ow.items()}

    def overwrites_for(self, t):
        return PO(**dict(self._ow.get(t, PO())))

    async def set_permissions(self, target, *, overwrite=_RIEN, reason=None, **kw):
        self.poses.append(target)
        if overwrite is None:
            self._ow.pop(target, None)
        elif overwrite is not _RIEN:
            self._ow[target] = overwrite
        else:
            self._ow[target] = PO(**kw)

    async def edit(self, *, overwrites, reason=None):
        self.edits.append(reason)
        self._ow = dict(overwrites)

    def voit(self, t):
        return self._ow.get(t, PO()).view_channel

    def peut_ecrire(self, t):
        return self._ow.get(t, PO()).send_messages


class Guilde:
    def __init__(self, gid, salons, membres=()):
        self.id = gid
        self.default_role = Cible(gid, "@everyone")
        self.me = Cible(1, "Ryuk", bot=True)
        self.text_channels = salons
        self.members = list(membres)
        self._membres = {m.id: m for m in membres}

    def get_member(self, uid):
        return self._membres.get(uid)


va = Cible(102, "va_emma_de_va_ig")      # VA de Va IG (model emma), aussi membre de You FR
va.roles = []


def serveur(gid):
    return Guilde(gid, [Salon("🔥・banger-emma"), Salon("🗂️・all-banger-emma"),
                        Salon("🔥・banger-amelia"), Salon("💥・banger"), Salon("💣・all-banger"),
                        Salon("💬・général")], membres=[va])


g_fr, g_us, g_ig = serveur(YOU_FR), serveur(YOU_US), serveur(VA_IG)
_sauve = (w.load_users, w.identites_du_membre)
try:
    w.load_users = lambda: {"102": {"identity": "emma"}}
    w.identites_du_membre = lambda m, i: [i]

    class FauxBot:
        guilds = [g_fr, g_us, g_ig]

    import logging

    class _Ecoute(logging.Handler):
        erreurs = []

        def emit(self, rec):
            if rec.levelno >= logging.ERROR:
                _Ecoute.erreurs.append(rec.getMessage())

    _h = _Ecoute()
    w.log.addHandler(_h)
    try:
        courir(w.Welcome.auto_secure_general_channels.coro(type("S", (), {"bot": FauxBot()})()))
        courir(w.Welcome.auto_secure_general_channels.coro(type("S", (), {"bot": FauxBot()})()))
    finally:
        w.log.removeHandler(_h)
finally:
    w.load_users, w.identites_du_membre = _sauve
check("le tour des 10 minutes va au bout, sans erreur", not _Ecoute.erreurs, _Ecoute.erreurs)

for g, nom in ((g_fr, "You FR"), (g_us, "You US")):
    par_model = g.text_channels[:3]
    check(f"{nom} : les banger-<model> ne sont PAS cachés à @everyone",
          all(c.voit(g.default_role) is not False for c in par_model),
          [(c.name, c.voit(g.default_role)) for c in par_model])
    check(f"{nom} : aucun droit posé au nom du VA de Va IG de passage",
          all(va not in c._ow and not c.poses for c in g.text_channels),
          [(c.name, c.poses) for c in g.text_channels if c.poses])
    check(f"{nom} : personne n'écrit dans les bangers, le bot si (verrouiller_bangers)",
          all(c.peut_ecrire(g.default_role) is False and c.peut_ecrire(g.me) is True
              for c in g.text_channels[:5]),
          [(c.name, c.peut_ecrire(g.default_role)) for c in g.text_channels[:5]])
    check(f"{nom} : le 💬・général n'est pas touché",
          not g.text_channels[5]._ow and not g.text_channels[5].edits)
check("Va IG inchangé : banger-emma caché à @everyone, ouvert au VA d'Emma, pas celui d'Amelia",
      g_ig.text_channels[0].voit(g_ig.default_role) is False
      and g_ig.text_channels[0].voit(va) is True
      and g_ig.text_channels[2].voit(g_ig.default_role) is False
      and g_ig.text_channels[2].voit(va) is not True)

# le rôle d'une model posé à la main sur You FR ne réserve rien non plus
s_fr = serveur(YOU_FR)
r = courir(w.sync_general_channel_access(s_fr, va, ["emma"]))
check("sync_general_channel_access sur You FR : rien (0, 0), aucun appel",
      r == (0, 0) and not any(c.poses for c in s_fr.text_channels), r)
s_ig = serveur(VA_IG)
r = courir(w.sync_general_channel_access(s_ig, va, ["emma"]))
check("… sur Va IG : comme avant (ses deux bangers ouverts)", r[0] == 2, r)

# le salon du matin se retrouve par son nom, comme sur Va IG
import bangers as bg  # noqa: E402

check("bangers.salon_banger_de retrouve 🔥・banger-emma et son miroir sur You FR",
      bg.salon_banger_de(g_fr, "emma") is g_fr.text_channels[0]
      and bg.salon_banger_de(g_fr, "emma", all_banger=True) is g_fr.text_channels[1])


# ══════════════════════════════════════════════════════ isolation ══
check("isolation : rien écrit ni modifié dans data/", _instantane() == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
print("=" * 70)
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
