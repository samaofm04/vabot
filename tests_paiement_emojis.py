"""Capture du wallet USDC et serveur d'emojis plein (cogs/user.py).

Audit du 20/10/2026 :
- la capture d'écran du wallet n'arrivait jamais. Le bot attendait un message
  « image ou skip » dans le salon, mais sans l'intention Message Content
  (main.py ne la demande pas) Discord lui livre les messages du salon SANS
  texte ni pièces jointes : l'attente finissait toujours en « ⏳ Pas de capture
  reçue ». La capture se dépose maintenant dans le formulaire, et un message
  vide du salon est relu par l'API (comme cogs/bases_identite.py) ;
- le serveur Spam a 50 emojis sur 50, tous utiles : chaque redessin
  redemandait les 4 photos manquantes, refusées (30008), et Discord a fini par
  imposer une heure d'attente. Les emojis se créent maintenant sur
  l'APPLICATION du bot (2 000 places, tous ses serveurs) ; ceux du serveur ne
  servent qu'en repli, et un serveur plein n'y est plus redemandé tant qu'il
  ne change pas.

Vérifié ici sans réseau ni data/ : le vrai discord.py lit le formulaire tel
que Discord l'envoie ; le reste passe par de faux objets.

Lancer depuis la racine du dépôt : python tests_paiement_emojis.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import pathlib
import sys
import tempfile
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402
import cogs.user as U                   # noqa: E402

OKS, FAILS = [], []


def check(nom, cond, detail=""):
    if cond:
        OKS.append(nom)
        print("OK   " + nom)
    else:
        FAILS.append(nom)
        print("FAIL " + nom + (f"  [{str(detail)[:400]}]" if detail != "" else ""))


# ───────────────────────────── capture du wallet ─────────────────────────────
print("=" * 70)
print("1) Le formulaire USDC porte la capture (lu par le vrai discord.py)")
print("=" * 70)


class FauxCogModal:
    def __init__(self):
        self.appels = []

    async def _save_crypto_and_ask_screenshot(self, interaction, info, capture=None):
        self.appels.append((info, capture))


def soumettre(modal, adresse, fichiers):
    """Rejoue la soumission telle que Discord l'envoie (composants Label)."""
    comps = [{"type": 18, "id": 1, "component": {
                 "type": 4, "id": 2, "custom_id": modal.addr.custom_id, "value": adresse}},
             {"type": 18, "id": 3, "component": {
                 "type": 19, "id": 4, "custom_id": modal.capture.custom_id,
                 "values": [f["id"] for f in fichiers]}}]
    resolu = {"attachments": {f["id"]: f for f in fichiers}} if fichiers else {}
    inter = types.SimpleNamespace(_state=types.SimpleNamespace(http=None), guild_id=None, guild=None,
                                  user=types.SimpleNamespace(id=42), client=None)

    async def go():
        await modal._dispatch_submit(inter, comps, resolu)
    asyncio.run(go())


_png = {"id": "555", "filename": "wallet.png", "size": 1234, "url": "https://cdn.discordapp.com/x/wallet.png",
        "proxy_url": "https://media.discordapp.net/x/wallet.png", "content_type": "image/png"}
_cog = FauxCogModal()
_m = U._CryptoAddressModal(_cog, "Solana")
_d = _m.to_dict()
_types = [c["type"] for c in _d["components"]]
_sous = [c["component"]["type"] for c in _d["components"]]
check("formulaire : deux libellés, l'adresse (texte) puis la capture (fichier, facultative)",
      _types == [18, 18] and _sous == [4, 19]
      and _d["components"][1]["component"].get("required") is False
      and _d["components"][1]["component"].get("max_values") == 1, _d)
check("formulaire : libellés dans les limites de Discord (45 car.)",
      all(len(c["label"]) <= 45 for c in _d["components"]), [c["label"] for c in _d["components"]])
soumettre(_m, "  So1anaWa11et  ", [_png])
check("soumission avec image : adresse nettoyée et capture transmise",
      len(_cog.appels) == 1 and _cog.appels[0][0] == {"method": "USDC", "chain": "Solana",
                                                      "address": "So1anaWa11et"}
      and getattr(_cog.appels[0][1], "url", "") == _png["url"], _cog.appels)
_cog2 = FauxCogModal()
_m2 = U._CryptoAddressModal(_cog2, "ETH")
soumettre(_m2, "0xabc", [])
check("soumission sans image : capture None (on la demandera dans le salon)",
      len(_cog2.appels) == 1 and _cog2.appels[0][1] is None, _cog2.appels)


print()
print("=" * 70)
print("2) Enregistrement : formulaire, salon, relecture par l'API")
print("=" * 70)


class FauxReponse:
    def __init__(self, journal):
        self.j = journal

    async def send_message(self, texte, **kw):
        self.j.append(("reponse", texte))


class FauxSuivi:
    def __init__(self, journal):
        self.j = journal

    async def send(self, texte, **kw):
        self.j.append(("suivi", texte))


class FauxPJ:
    def __init__(self, url):
        self.url = url


class FauxSalon:
    def __init__(self, cid, relus=None):
        self.id = cid
        self.relus = relus or {}        # id du message -> ce que l'API rend
        self.relectures = []

    async def fetch_message(self, mid):
        self.relectures.append(mid)
        r = self.relus.get(mid)
        if isinstance(r, Exception):
            raise r
        return r


def message(mid, salon, auteur=42, contenu="", pieces=()):
    return types.SimpleNamespace(id=mid, channel=salon, author=types.SimpleNamespace(id=auteur),
                                 content=contenu, attachments=list(pieces))


class FauxClient:
    def __init__(self, messages):
        self.file = list(messages)
        self.attentes = 0

    async def wait_for(self, evt, check=None, timeout=None):
        self.attentes += 1
        while self.file:
            m = self.file.pop(0)
            if check is None or check(m):
                return m
        raise asyncio.TimeoutError


class FauxCog:
    """Le vrai code d'enregistrement, sur un faux stockage."""
    _save_crypto_and_ask_screenshot = U.UserCog._save_crypto_and_ask_screenshot
    _relire_message = U.UserCog._relire_message

    def __init__(self):
        self.ecrits, self.notifs = [], []

    def _store_payment(self, uid, info):
        self.ecrits.append(dict(info))
        return True

    async def _notify_payment(self, interaction, info, screenshot_att=None):
        self.notifs.append(screenshot_att)


def scenario(messages, capture=None, salon=None):
    salon = salon or FauxSalon(7)
    j = []
    inter = types.SimpleNamespace(user=types.SimpleNamespace(id=42), channel=salon,
                                  client=FauxClient(messages), response=FauxReponse(j),
                                  followup=FauxSuivi(j))
    cog = FauxCog()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        asyncio.run(cog._save_crypto_and_ask_screenshot(
            inter, {"method": "USDC", "chain": "Solana", "address": "So1"}, capture=capture))
    return cog, j, inter, out.getvalue()


_cap = FauxPJ("https://cdn/x.png")
cog, j, inter, _ = scenario([], capture=_cap)
check("formulaire avec capture : écrite avec l'adresse, « complet », notif avec l'image, aucune attente",
      cog.ecrits[-1].get("screenshot") == "https://cdn/x.png" and "complet" in j[0][1]
      and cog.notifs == [_cap] and inter.client.attentes == 0, (cog.ecrits, j, cog.notifs))

# Le cas de production : intention absente, le message arrive VIDE, l'API le rend.
_s = FauxSalon(7, relus={100: types.SimpleNamespace(content="", attachments=[FauxPJ("https://cdn/w.png")])})
cog, j, inter, _ = scenario([message(100, _s)], salon=_s)
check("salon, message livré vide : relu par l'API, capture enregistrée",
      _s.relectures == [100] and cog.ecrits[-1].get("screenshot") == "https://cdn/w.png"
      and any("Capture reçue" in t for _k, t in j) and getattr(cog.notifs[-1], "url", "") == "https://cdn/w.png",
      (_s.relectures, cog.ecrits, j))

# Même relu, il reste vide (intention absente du portail) : le dire tout de suite.
_s = FauxSalon(7, relus={101: types.SimpleNamespace(content="", attachments=[])})
cog, j, inter, log_ = scenario([message(101, _s)], salon=_s)
check("salon, vide même relu : le bot le dit tout de suite (formulaire), adresse gardée",
      any("Je ne vois pas ton image" in t and "formulaire" in t for _k, t in j)
      and "screenshot" not in cog.ecrits[-1] and cog.notifs == [None]
      and inter.client.attentes == 1 and "illisible" in log_, (j, log_))

_s = FauxSalon(7, relus={102: discord.NotFound(types.SimpleNamespace(status=404, reason="nf"), "x")})
cog, j, inter, log_ = scenario([message(102, _s)], salon=_s)
check("salon, relecture refusée : dit au journal, et au VA",
      "non relu" in log_ and any("Je ne vois pas ton image" in t for _k, t in j), (j, log_))

# Intention présente : le texte arrive. Un « ok » ne clôt pas l'attente.
_s = FauxSalon(7)
cog, j, inter, _ = scenario([message(103, _s, contenu="ok j'envoie"),
                             message(104, _s, auteur=99, pieces=[FauxPJ("https://cdn/autre.png")]),
                             message(105, _s, pieces=[FauxPJ("https://cdn/moi.png")])], salon=_s)
check("salon, texte puis image : on attend l'image, celle d'un autre membre ignorée",
      cog.ecrits[-1].get("screenshot") == "https://cdn/moi.png" and inter.client.attentes == 2
      and _s.relectures == [], (cog.ecrits, inter.client.attentes))

_s = FauxSalon(7)
cog, j, inter, _ = scenario([message(106, _s, contenu=" SKIP ")], salon=_s)
check("salon, « skip » : sans capture, adresse gardée",
      any("sans capture" in t for _k, t in j) and "screenshot" not in cog.ecrits[-1], j)

cog, j, inter, _ = scenario([])
check("salon, rien en 5 min : « Pas de capture reçue », adresse gardée",
      any("Pas de capture reçue" in t for _k, t in j) and cog.notifs == [None], j)


# ───────────────────────────── serveur d'emojis plein ─────────────────────────────
print()
print("=" * 70)
print("3) Serveur d'emojis plein : redemandé seulement quand il change")
print("=" * 70)

_MOI = 777


def _http_exc(code, msg):
    return discord.HTTPException(types.SimpleNamespace(status=400, reason="Bad Request"),
                                 {"code": code, "message": msg})


class FauxEmoji:
    def __init__(self, nom, auteur=_MOI):
        self.name = nom
        self.animated = False
        self.user = types.SimpleNamespace(id=auteur)

    async def delete(self, reason=None):
        raise AssertionError("aucun emoji utile ne doit être supprimé")


class FauxServeur:
    def __init__(self, noms, limite=50):
        self.id = 1535758943324999711
        self.name = "Youl4b ( Spam )"
        self.emoji_limit = limite
        self.emojis = [FauxEmoji(n) for n in noms]
        self.me = types.SimpleNamespace(id=_MOI)
        self.creations, self.lectures = [], 0

    async def fetch_emojis(self):
        self.lectures += 1
        return list(self.emojis)

    async def create_custom_emoji(self, name, image, reason=None):
        self.creations.append(name)
        if sum(1 for e in self.emojis if not e.animated) >= self.emoji_limit:
            raise _http_exc(30008, "Maximum number of emojis reached (50)")
        e = FauxEmoji(name)
        self.emojis.append(e)
        return e


_TMP = pathlib.Path(tempfile.mkdtemp())
_PNG = _TMP / "pp.png"
from PIL import Image                   # noqa: E402
Image.new("RGBA", (8, 8), (200, 50, 50, 255)).save(_PNG)

_MANQUANTES = ["ava_estradaa", "adelears", "sea62145", "mialobosco"]
_PRESENTES = [f"model{i}" for i in range(25)]
_noms = ([U._identity_emoji_name(m) for m in _PRESENTES]
         + sorted(set(U._ICONES_ACTIONS.values())))
_noms += [f"idreserve{i}" for i in range(50 - len(_noms))]
_orig = (U._identity_pp_file, U._emojis_utiles_noms)
U._identity_pp_file = lambda m: _PNG
U._SERVEURS_PLEINS.clear()
U._EMOJIS_CREES.clear()


class Journal(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lignes = []

    def emit(self, r):
        self.lignes.append(r.getMessage())


_jl = Journal()
U.log.addHandler(_jl)
try:
    srv = FauxServeur(_noms)
    U._emojis_utiles_noms = lambda: {e.name for e in srv.emojis}   # tous utiles
    check("départ : le serveur a 50 emojis sur 50", len(srv.emojis) == 50, len(srv.emojis))
    _models = _PRESENTES + _MANQUANTES
    out = asyncio.run(U.ensure_identity_emojis(srv, _models))
    check("1er redessin : une lecture pour chercher de la place, aucune création refusée",
          srv.lectures == 1 and srv.creations == [] and len(out) == len(_PRESENTES),
          (srv.lectures, srv.creations, len(out)))
    _pleins = [l for l in _jl.lignes if "plein" in l]
    check("1er redessin : le journal nomme le serveur et les 4 models sans photo, une fois",
          len(_pleins) == 1 and all(m in _pleins[0] for m in _MANQUANTES) and "50/50" in _pleins[0],
          _jl.lignes)
    n = len(_jl.lignes)
    for _ in range(3):
        out = asyncio.run(U.ensure_identity_emojis(srv, _models))
        asyncio.run(U.ensure_identity_emojis(srv, ["reserve_neuve"], raison="reserve"))
    check("redessins suivants : aucun appel à Discord, aucune ligne",
          srv.lectures == 1 and srv.creations == [] and len(_jl.lignes) == n
          and len(out) == len(_PRESENTES), (srv.lectures, srv.creations, _jl.lignes[n:]))

    # Une place se libère (emoji supprimé à la main) : on réessaie, une fois.
    srv.emojis.pop()
    asyncio.run(U.ensure_identity_emojis(srv, _models))
    check("une place libérée : une photo créée, la suivante refusée, puis on s'arrête",
          srv.creations == [U._identity_emoji_name(_MANQUANTES[0]),
                            U._identity_emoji_name(_MANQUANTES[1])]
          and len(srv.emojis) == 50, srv.creations)
    c = len(srv.creations)
    asyncio.run(U.ensure_identity_emojis(srv, _models))
    check("… et de nouveau plus rien tant que rien ne bouge", len(srv.creations) == c, srv.creations)

    # Boost : la limite monte, tout passe.
    srv.emoji_limit = 100
    out = asyncio.run(U.ensure_identity_emojis(srv, _models))
    check("boost (limite 100) : les photos manquantes sont créées",
          all(m in out for m in _MANQUANTES), sorted(set(_MANQUANTES) - set(out)))

    # Au bout de 6 h, on retente même si rien n'a bougé (une model sortie des
    # menus libère une place, mais seul _liberer_emojis la reprend).
    srv2 = FauxServeur(_noms)
    srv2.id = 99
    U._emojis_utiles_noms = lambda: {e.name for e in srv2.emojis}
    asyncio.run(U.ensure_identity_emojis(srv2, _models))
    l1 = srv2.lectures
    lim, nb, _q = U._SERVEURS_PLEINS[99]
    U._SERVEURS_PLEINS[99] = (lim, nb, time.monotonic() - U._SERVEUR_PLEIN_TTL_S - 1)
    asyncio.run(U.ensure_identity_emojis(srv2, _models))
    check("au bout de 6 h : une nouvelle recherche de place", srv2.lectures == l1 + 1,
          (l1, srv2.lectures))

    # Icônes d'actions : même règle.
    srv3 = FauxServeur(_noms)
    srv3.id = 98
    for nom in ("vapost", "vabio", "vaname"):
        srv3.emojis = [e for e in srv3.emojis if e.name != nom]
    srv3.emojis += [FauxEmoji(f"idbouche{i}") for i in range(3)]
    asyncio.run(U.ensure_action_emojis(srv3))
    check("icônes d'actions, serveur plein : un seul refus, puis on s'arrête",
          len(srv3.creations) == 1, srv3.creations)
    asyncio.run(U.ensure_action_emojis(srv3))
    check("icônes d'actions : redessin suivant sans appel", len(srv3.creations) == 1, srv3.creations)
finally:
    U._identity_pp_file, U._emojis_utiles_noms = _orig
    U.log.removeHandler(_jl)


# ───────────────────────────── emojis d'application ─────────────────────────────
print()
print("=" * 70)
print("4) Emojis d'application : créés une fois, pour tous les serveurs du bot")
print("=" * 70)
# Accord du propriétaire le 21/10/2026 : 2 000 places par application, au lieu
# de 50 par serveur.


class FauxClientAppli:
    def __init__(self, existants=(), lent=False, refus=None, lecture_ko=False):
        self.appli = {n: FauxEmoji(n) for n in existants}
        self.lectures, self.creations = 0, []
        self.lent, self.refus, self.lecture_ko = lent, refus, lecture_ko

    async def fetch_application_emojis(self):
        self.lectures += 1
        if self.lecture_ko:
            raise _http_exc(0, "panne")
        return list(self.appli.values())

    async def create_application_emoji(self, name, image):
        self.creations.append(name)
        await asyncio.sleep(0)               # laisse passer l'autre redessin
        if self.lent:
            await asyncio.sleep(3600)        # limite Discord : discord.py attend
        if self.refus:
            raise self.refus
        e = FauxEmoji(name)
        self.appli[name] = e
        return e


def serveur_appli(client, noms=None, gid=1535758943324999711, bot=_MOI):
    s = FauxServeur(_noms if noms is None else noms)
    s.id = gid
    s.me = types.SimpleNamespace(id=bot)
    s._state = types.SimpleNamespace(_get_client=lambda: client)
    return s


def remise_a_zero():
    U._EMOJIS_APPLI.clear()
    U._APPLI_PAUSE.clear()
    U._APPLI_VERROUS.clear()
    U._SERVEURS_PLEINS.clear()
    U._EMOJIS_CREES.clear()


_tous_noms = sorted({U._identity_emoji_name(m) for m in _models} | set(U._ICONES_ACTIONS.values()))
_jl = Journal()
U.log.addHandler(_jl)
_orig_delai = U._APPLI_DELAI_S
U._identity_pp_file = lambda m: _PNG
try:
    remise_a_zero()
    cli = FauxClientAppli()
    spam = serveur_appli(cli)                          # 50/50 : le cas du Spam
    out = asyncio.run(U.ensure_identity_emojis(spam, _models))
    act = asyncio.run(U.ensure_action_emojis(spam))
    check("Spam plein : les 29 photos et les 21 icônes créées sur l'APPLICATION, rien sur le serveur",
          sorted(cli.creations) == _tous_noms and spam.creations == [] and spam.lectures == 0,
          (len(cli.creations), spam.creations))
    check("les 4 models sans photo l'ont maintenant",
          all(out.get(m) is cli.appli[U._identity_emoji_name(m)] for m in _MANQUANTES), out)
    check("menus et icônes : l'emoji de l'application passe devant celui du serveur",
          all(out[m] is cli.appli[U._identity_emoji_name(m)] for m in _models)
          and all(act[c] is cli.appli[n] for c, n in U._ICONES_ACTIONS.items()), "")
    check("lecture au clic (icones_actions, _jb_emojis_presents) : emojis de l'application",
          all(v is cli.appli[U._ICONES_ACTIONS[c]] for c, v in U.icones_actions(spam).items())
          and len(U.icones_actions(spam)) == len(U._ICONES_ACTIONS)
          and all(U._jb_emojis_presents(spam, _models)[m] is cli.appli[U._identity_emoji_name(m)]
                  for m in _models), "")
    check("liste de l'application lue une seule fois", cli.lectures == 1, cli.lectures)

    fr = serveur_appli(cli, noms=[], gid=42)            # un autre serveur, aucun emoji à lui
    n = len(cli.creations)
    out_fr = asyncio.run(U.ensure_identity_emojis(fr, _models))
    asyncio.run(U.ensure_action_emojis(fr))
    check("autre serveur du même bot : tout est déjà là, aucune création, aucune lecture",
          len(cli.creations) == n and cli.lectures == 1 and fr.creations == []
          and len(out_fr) == len(_models), (cli.creations[n:], cli.lectures))

    peach = FauxServeur(_noms)                          # bot admin : ne lit que le serveur
    peach.me = types.SimpleNamespace(id=999)
    _pp = U._jb_emojis_presents(peach, _PRESENTES)
    check("Peach (maquettes /demo) : emojis du serveur, jamais ceux de Yoshi",
          len(_pp) == len(_PRESENTES) and all(e in peach.emojis for e in _pp.values()), _pp)

    # Deux redessins en même temps (menu puis ✨ General) : une seule création par nom.
    remise_a_zero()
    cli = FauxClientAppli()
    spam = serveur_appli(cli)

    async def deux():
        await asyncio.gather(U.ensure_identity_emojis(spam, _MANQUANTES),
                             U.ensure_identity_emojis(spam, _MANQUANTES))
    asyncio.run(deux())
    check("deux redessins simultanés : liste lue une fois, chaque emoji créé une fois",
          sorted(cli.creations) == sorted(U._identity_emoji_name(m) for m in _MANQUANTES)
          and cli.lectures == 1, (cli.creations, cli.lectures))

    # Création trop lente (limite Discord) : on n'attend pas une heure.
    remise_a_zero()
    U._APPLI_DELAI_S = 0.05
    cli = FauxClientAppli(lent=True)
    spam = serveur_appli(cli)
    t0 = time.monotonic()
    out = asyncio.run(U.ensure_identity_emojis(spam, _models))
    duree = time.monotonic() - t0
    check("création trop lente : abandon après le délai, pause d'1 h, le reste n'est pas tenté",
          len(cli.creations) == 1 and duree < 2 and any("trop lent" in l for l in _jl.lignes),
          (cli.creations, duree))
    check("… et le menu garde les photos du serveur", all(m in out for m in _PRESENTES)
          and not any(m in out for m in _MANQUANTES), sorted(out))
    asyncio.run(U.ensure_identity_emojis(spam, _models))
    check("… redessin suivant : aucune tentative pendant la pause", len(cli.creations) == 1,
          cli.creations)
    U._APPLI_DELAI_S = _orig_delai

    # Refus de Discord : dit, pause de 10 min, liste relue ensuite.
    remise_a_zero()
    cli = FauxClientAppli(refus=_http_exc(50035, "Invalid Form Body"))
    spam = serveur_appli(cli)
    asyncio.run(U.ensure_identity_emojis(spam, _MANQUANTES))
    asyncio.run(U.ensure_identity_emojis(spam, _MANQUANTES))
    check("refus : dit au journal, un seul essai, la liste sera relue",
          len(cli.creations) == 1 and any("refuse" in l for l in _jl.lignes)
          and cli.lectures == 2 and 500 < U._APPLI_PAUSE[_MOI] - time.monotonic() <= 600,
          (cli.creations, cli.lectures))

    # Liste de l'application illisible : comme avant, sur le serveur.
    remise_a_zero()
    cli = FauxClientAppli(lecture_ko=True)
    srv = serveur_appli(cli, noms=[])
    out = asyncio.run(U.ensure_identity_emojis(srv, _MANQUANTES))
    check("liste illisible : repli sur le serveur (création serveur), dit au journal",
          cli.creations == [] and len(srv.creations) == len(_MANQUANTES)
          and any("illisibles" in l for l in _jl.lignes), (cli.creations, srv.creations))
finally:
    U._APPLI_DELAI_S = _orig_delai
    U._identity_pp_file = _orig[0]
    U.log.removeHandler(_jl)
    remise_a_zero()


print()
print("=" * 70)
print(f"{len(OKS)} OK · {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  FAIL " + f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
