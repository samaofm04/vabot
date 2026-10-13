"""Les salons banger sont en lecture seule : seul le bot y poste.

Propriétaire, 13/10/2026 : « pour les salons banger, all banger, tu peux
bloquer les messages pour que personne ne puisse écrire dedans », « faut que
personne puisse écrire ».

Constaté avant : sur Va IG, le rôle de la model refusait déjà l'écriture,
mais chaque VA avait « voir + écrire » à SON nom (cogs/welcome.py,
sync_general_channel_access et l'entretien des 10 minutes), et un droit au
nom du membre passe devant celui du rôle ; sur Youl4b, 💥・banger et
💣・all-banger n'avaient aucun réglage.

Vérifié ici, sans Discord (salons, rôles et membres faux, vrais
discord.PermissionOverwrite) :
  1. quels salons sont des bangers (et lesquels n'en sont pas) ;
  2. un VA reçoit « voir + lire » sur ses bangers, « écrire » ailleurs ;
  3. verrouiller_bangers : @everyone, rôles et VA perdent l'écriture, gardent
     la vue ; le bot, les autres bots et les rôles d'intégration gardent
     tout ; archives et autres salons intacts ; UNE modification par salon ;
     rien au second passage ;
  4. la boucle des 10 minutes, rejouée : VA au nom, puis verrou, sur chaque
     serveur, et l'erreur d'un serveur n'arrête pas les autres.

Lancer depuis la racine du dépôt : python tests_bangers_lecture_seule.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402
import cogs.welcome as w                # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


PO = discord.PermissionOverwrite
_RIEN = object()


class Cible:
    def __init__(self, i, nom, bot=False, managed=False):
        self.id, self.name, self.bot, self.managed = i, nom, bot, managed

    def __eq__(self, o):
        return isinstance(o, Cible) and o.id == self.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return self.name


class Categorie:
    def __init__(self, nom):
        self.name = nom


class Salon:
    def __init__(self, nom, ows=None, cat=None):
        self.name, self.category = nom, cat
        self._ow = dict(ows or {})
        self.edits, self.poses = [], []

    @property
    def overwrites(self):
        return {k: PO(**dict(v)) for k, v in self._ow.items()}

    def overwrites_for(self, t):
        return PO(**dict(self._ow.get(t, PO())))

    async def set_permissions(self, target, *, overwrite=_RIEN, reason=None, **kw):
        # comme discord.py : des mots-clés REMPLACENT le droit du membre
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

    def peut_ecrire(self, t):
        return self._ow.get(t, PO()).send_messages

    def voit(self, t):
        return self._ow.get(t, PO()).view_channel


class Guilde:
    def __init__(self, gid, salons, membres=()):
        self.id = gid
        self.default_role = Cible(gid, "@everyone")
        self.me = Cible(1, "Yoshi", bot=True)
        self.text_channels = salons
        self._membres = {m.id: m for m in membres}

    def get_member(self, uid):
        return self._membres.get(uid)


def lancer(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ 1
print("\n— 1. quels salons sont des bangers")
oui = ["💥・banger", "💣・all-banger", "💥・banger-amelia", "💥・all-banger-emma",
       "banger‑lola", "all‑banger‑julia", "BANGER-Sarah"]
non = ["général", "general-amelia", "📸-exemple-compte-lola", "ancien-all-banger-global",
       "ancien-banger-julia-0310", "tall-banger", "bangers", "banger-talk-x", "💬・discussion-banger"]
check("bangers reconnus (emoji, tiret d'iPhone, majuscules)",
      all(w.salon_banger(n) for n in oui), [n for n in oui if not w.salon_banger(n)])
check("le reste n'en est pas (archivés renommés « ancien- », autres salons)",
      not any(w.salon_banger(n) for n in non), [n for n in non if w.salon_banger(n)])

# ------------------------------------------------------------------ 2
print("\n— 2. ce qu'un VA reçoit sur ses salons")
d_b = w.droits_va_salon(Salon("💥・banger-amelia"))
d_g = w.droits_va_salon(Salon("general-amelia"))
check("banger : voir et relire, ni écrire, ni fil, ni fichier",
      d_b["view_channel"] and d_b["read_message_history"]
      and not any(d_b[k] for k in ("send_messages", "send_messages_in_threads",
                                   "create_public_threads", "create_private_threads",
                                   "attach_files")), d_b)
check("general : il écrit, comme avant", d_g["send_messages"] and d_g["attach_files"], d_g)

va = Cible(100, "paul")
g_s = Salon("general-amelia")
b_s = Salon("💥・banger-amelia")
a_s = Salon("💥・all-banger-amelia")
e_s = Salon("💥・banger-emma")
gd = Guilde(9, [g_s, b_s, a_s, e_s])
lancer(w.sync_general_channel_access(gd, va, "amelia"))
check("arrivée d'un VA amelia : il voit ses deux bangers sans pouvoir y écrire",
      b_s.voit(va) is True and b_s.peut_ecrire(va) is False
      and a_s.voit(va) is True and a_s.peut_ecrire(va) is False)
check("… et écrit dans son general", g_s.voit(va) is True and g_s.peut_ecrire(va) is True)
check("… et ne voit pas le banger d'une autre model", e_s.voit(va) is not True)

# ------------------------------------------------------------------ 3
print("\n— 3. le verrou")
amelia = Cible(500, "Amelia")
staff = Cible(600, "Manager")
integ = Cible(700, "Bot role", managed=True)
autre_bot = Cible(2, "Peach", bot=True)
va2 = Cible(101, "lea")
archives = Categorie("🗄️ Archives salons")
ig_b = Salon("💥・banger-amelia", {
    Cible(9, "@everyone"): PO(view_channel=False),
    amelia: PO(view_channel=True, send_messages=False),
    staff: PO(view_channel=True, send_messages=True),
    va: PO(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
    va2: PO(view_channel=False),
    autre_bot: PO(view_channel=True, send_messages=True),
    integ: PO(send_messages=True)})
ig_arch = Salon("💥・banger-julia", {va: PO(view_channel=True, send_messages=True)}, cat=archives)
ig_gen = Salon("general-amelia", {va: PO(view_channel=True, send_messages=True)})
g_ig = Guilde(9, [ig_b, ig_arch, ig_gen])
bil = lancer(w.verrouiller_bangers(g_ig))
ev = g_ig.default_role
check("@everyone : ni écrire, ni fils ; il ne voit toujours pas le salon",
      ig_b.peut_ecrire(ev) is False and ig_b._ow[ev].send_messages_in_threads is False
      and ig_b._ow[ev].create_public_threads is False and ig_b.voit(ev) is False)
check("le VA garde la vue, perd l'écriture et les fichiers",
      ig_b.voit(va) is True and ig_b.peut_ecrire(va) is False
      and ig_b._ow[va].attach_files is False and ig_b._ow[va].read_message_history is True)
check("le rôle de la model, le staff : plus d'écriture, la vue reste",
      ig_b.peut_ecrire(amelia) is False and ig_b.voit(amelia) is True
      and ig_b.peut_ecrire(staff) is False and ig_b.voit(staff) is True)
check("un VA caché le reste (vue refusée gardée)", ig_b.voit(va2) is False)
check("le bot écrit, droit posé noir sur blanc ; les autres bots et le rôle d'intégration intacts",
      ig_b.peut_ecrire(g_ig.me) is True and ig_b._ow[g_ig.me].attach_files is True
      and ig_b._ow[g_ig.me].embed_links is True
      and ig_b.peut_ecrire(autre_bot) is True and ig_b.peut_ecrire(integ) is True)
check("UNE modification pour tout le salon, aucune par membre",
      len(ig_b.edits) == 1 and not ig_b.poses and bil["corriges"] == 1, (ig_b.edits, ig_b.poses))
check("archives et autres salons : intacts",
      not ig_arch.edits and ig_arch.peut_ecrire(va) is True
      and not ig_gen.edits and ig_gen.peut_ecrire(va) is True)
bil2 = lancer(w.verrouiller_bangers(g_ig))
check("second passage : rien à refaire, aucun appel", bil2["corriges"] == 0 and len(ig_b.edits) == 1, bil2)

y_b, y_a, y_g = Salon("💥・banger"), Salon("💣・all-banger"), Salon("général")
g_y = Guilde(8, [y_g, y_b, y_a])
lancer(w.verrouiller_bangers(g_y))
check("Youl4b (aucun réglage) : @everyone ne peut plus écrire dans 💥・banger et 💣・all-banger",
      y_b.peut_ecrire(g_y.default_role) is False and y_a.peut_ecrire(g_y.default_role) is False
      and y_b.voit(g_y.default_role) is None)
check("… le bot si ; le salon général pas touché",
      y_b.peut_ecrire(g_y.me) is True and not y_g.edits and not y_g._ow)


class Boum(Salon):
    async def edit(self, **kw):
        raise discord.HTTPException(type("R", (), {"status": 403, "reason": "x"})(), "refus")


g_err = Guilde(7, [Boum("💥・banger"), Salon("💣・all-banger")])
bil3 = lancer(w.verrouiller_bangers(g_err))
check("un salon refusé est compté, le suivant est quand même fermé",
      len(bil3["rates"]) == 1 and g_err.text_channels[1].peut_ecrire(g_err.default_role) is False, bil3)

# ------------------------------------------------------------------ 4
print("\n— 4. la boucle des 10 minutes, rejouée")
va3 = Cible(102, "zoe")
l_b = Salon("💥・banger-amelia", {Cible(5, "@everyone"): PO(view_channel=False),
                                  va3: PO(view_channel=True, send_messages=True)})
l_n = Salon("💥・all-banger-amelia", {Cible(5, "@everyone"): PO(view_channel=False)})
l_g = Salon("general-amelia", {Cible(5, "@everyone"): PO(view_channel=False)})
g_l = Guilde(5, [l_b, l_n, l_g], membres=[va3])
class SalonCasse:
    @property
    def name(self):
        raise RuntimeError("salon illisible")


g_casse = Guilde(4, [SalonCasse()])
g_y2 = Guilde(3, [Salon("💥・banger")])
_sauve = (w.load_users, w.identites_du_membre)
try:
    w.load_users = lambda: {"102": {"identity": "amelia"}}
    w.identites_du_membre = lambda m, i: [i]

    class FauxBot:
        guilds = [g_l, g_casse, g_y2]

    lancer(w.Welcome.auto_secure_general_channels.coro(type("S", (), {"bot": FauxBot()})()))
finally:
    w.load_users, w.identites_du_membre = _sauve
check("un VA arrivé sur all-banger y voit sans écrire ; son ancien droit d'écrire sur banger tombe",
      l_n.voit(va3) is True and l_n.peut_ecrire(va3) is False
      and l_b.voit(va3) is True and l_b.peut_ecrire(va3) is False)
check("… il écrit toujours dans general", l_g.peut_ecrire(va3) is True)
check("… et le serveur suivant (Youl4b) est fermé aussi, malgré un serveur en erreur avant",
      g_y2.text_channels[0].peut_ecrire(g_y2.default_role) is False)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
