# -*- coding: utf-8 -*-
"""tests_outlook.py — banc d'essai du coffre d'adresses Outlook.

Lancer :  python tests_outlook.py

Autonome : repertoire data TEMPORAIRE, faux objets Discord (interactions,
salons, messages) qui ENREGISTRENT ce qui serait envoye (ephemere, edition,
livraison). AUCUN reseau, aucune vraie donnee touchee.

Verifie :
  - TOTP RFC 6238 (SHA1) : vecteur officiel + le calcul du temps restant ;
  - l'ajout refuse un seed base32 invalide, accepte un valide ;
  - le pool : Valider prend un libre, le passe « attribue », n'en reprend
    jamais un deja attribue, et dit « aucune libre » quand il n'en reste plus ;
  - la garde manager (role ou droits serveur) ;
  - la livraison : adresse + mot de passe dans le ticket, le SEED nulle part,
    le mot de passe absent de la carte publique, le repli si le ticket manque ;
  - le bouton 2FA : code a 6 chiffres sans seed / « fais la demande » sinon ;
  - la page /outlook : auth + admin exiges, seed ET mot de passe masques dans
    le HTML, et l'ajout qui refuse un mauvais seed.
"""
import asyncio
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# data/ temporaire AVANT d'importer les modules qui figent des chemins.
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="outlook_test_"))

import totp
import outlook_comptes as oc
import cogs.outlook as ck

# Rediriger TOUS les fichiers vers le temporaire.
oc.DATA_DIR = _TMP
oc.FICHIER = _TMP / "outlook_comptes.json"
ck.PANNEAUX_FILE = _TMP / "outlook_panneaux.json"
ck.DEMANDES_FILE = _TMP / "outlook_demandes.json"
ck.USERS_FILE = _TMP / "users.json"

SEED = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # secret ASCII « 12345678901234567890 »

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))


def _reset(comptes=None, users=None):
    """Remet le coffre, les demandes et les tickets a un etat connu."""
    import safe_json
    safe_json.write(oc.FICHIER, {"comptes": comptes or []})
    safe_json.write(ck.DEMANDES_FILE, {})
    safe_json.write(ck.PANNEAUX_FILE, {})
    ck.USERS_FILE.write_text(json.dumps(users or {}), encoding="utf-8")


# ---- Faux objets Discord ----------------------------------------------------

class FRole:
    def __init__(self, i):
        self.id = i


class FPerms:
    def __init__(self, administrator=False, manage_roles=False):
        self.administrator = administrator
        self.manage_roles = manage_roles


class FUser:
    def __init__(self, uid, display_name="?", roles=None, perms=None):
        self.id = uid
        self.display_name = display_name
        self.roles = roles or []
        self.guild_permissions = perms


class FMessage:
    _n = 70000

    def __init__(self, mid=None):
        FMessage._n += 1
        self.id = mid if mid is not None else FMessage._n
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


class FChannel:
    def __init__(self, cid, name="salon"):
        self.id = cid
        self.name = name
        self.sent = []       # liste de (contenu, kwargs)

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return FMessage()


class FResponse:
    def __init__(self):
        self.sends = []      # send_message
        self.edits = []      # edit_message

    async def send_message(self, content=None, **kw):
        self.sends.append((content, kw))

    async def edit_message(self, **kw):
        self.edits.append(kw)


class FBot:
    def __init__(self, channels=None):
        self._channels = channels or {}

    def get_channel(self, cid):
        return self._channels.get(int(cid))

    def get_cog(self, name):
        return None


class FInteraction:
    def __init__(self, user, channel, client, message=None):
        self.user = user
        self.channel = channel
        self.client = client
        self.message = message
        self.channel_id = getattr(channel, "id", None)
        self.response = FResponse()


def _tout(*objets) -> str:
    """Concatene tout ce qui a ete 'rendu' vers Discord pour chercher un secret."""
    morceaux = []
    for o in objets:
        if isinstance(o, FResponse):
            morceaux.append(str(o.sends) + str(o.edits))
        elif isinstance(o, FChannel):
            morceaux.append(str(o.sent))
        elif isinstance(o, FMessage):
            morceaux.append(str(o.edits))
        else:
            morceaux.append(str(o))
    return "\n".join(morceaux)


# ---- 1) TOTP ----------------------------------------------------------------

def test_totp():
    code, reste = totp.code_totp(SEED, 59)
    check("TOTP RFC6238 : t=59 -> 287082", code == "287082", code)
    check("TOTP : 6 chiffres", len(code) == 6 and code.isdigit())
    check("TOTP temps restant t=59 -> 1 s", reste == 1, reste)
    check("TOTP temps restant t=30 -> 30 s", totp.code_totp(SEED, 30)[1] == 30)
    check("TOTP temps restant t=45 -> 15 s", totp.code_totp(SEED, 45)[1] == 15)
    check("seed valide reconnu", totp.seed_valide(SEED))
    check("seed minuscule accepte", totp.seed_valide(SEED.lower()))
    check("seed invalide refuse (1/8/0/9 hors base32)", not totp.seed_valide("188888"))
    check("seed invalide refuse (ponctuation)", not totp.seed_valide("pas du base32 !"))
    check("seed vide refuse", not totp.seed_valide(""))


# ---- 2) Ajout (logique pure) ------------------------------------------------

def test_ajout():
    _reset()
    ok, res = oc.ajouter("a@outlook.com", "MotDePasseAAA", "mauvais!!")
    check("ajout : seed invalide refuse", not ok and isinstance(res, str))
    check("ajout : rien stocke apres refus", len(oc.comptes()) == 0)
    ok, res = oc.ajouter("a@outlook.com", "MotDePasseAAA", SEED)
    check("ajout : seed valide accepte", ok)
    check("ajout : compte stocke, statut libre", len(oc.comptes()) == 1
          and oc.comptes()[0]["statut"] == "libre")
    check("ajout : seed range normalise", oc.comptes()[0]["seed"] == SEED)
    ok, res = oc.ajouter("", "x", SEED)
    check("ajout : adresse vide refusee", not ok)


# ---- 3) Pool ----------------------------------------------------------------

def test_pool():
    _reset()
    oc.ajouter("un@outlook.com", "PW1", SEED)
    compte, etat = oc.attribuer("111", "Bob")
    check("pool : un libre attribue au VA", compte is not None and etat == "neuf")
    c = oc.comptes()[0]
    check("pool : passe a attribue (uid/va/date)",
          c["statut"] == "attribue" and c["uid"] == "111" and c["va"] == "Bob"
          and bool(c["attribue_le"]))
    # Plus de libre : un AUTRE VA n'obtient rien.
    compte2, etat2 = oc.attribuer("222", "Alice")
    check("pool : plus de libre -> aucune", compte2 is None and etat2 == "vide")
    check("pool : le compte de Bob est intact", oc.comptes()[0]["uid"] == "111")
    # Re-demande du MEME VA : on lui rend le sien, pas un neuf (pas de double).
    oc.ajouter("deux@outlook.com", "PW2", SEED)   # un libre a nouveau
    compte3, etat3 = oc.attribuer("111", "Bob")
    check("pool : meme VA -> son compte, pas un neuf",
          etat3 == "deja" and compte3["email"] == "un@outlook.com")
    check("pool : le libre neuf n'a pas ete touche", oc.nb_libres() == 1)
    check("pool : un deja attribue n'est jamais repris",
          all(c["uid"] != "333" for c in oc.comptes()))
    check("compte_de_uid trouve l'attribue", oc.compte_de_uid("111") is not None)
    check("compte_de_uid rend None pour un inconnu", oc.compte_de_uid("999") is None)


# ---- 4) Garde manager -------------------------------------------------------

def test_manager():
    bot = FBot()
    cog = ck.OutlookCog(bot)
    salon = FChannel(1, "adresse-outlook")
    vue = ck.CarteValidation(cog)

    async def run():
        # Porte le role manager
        mgr_role = FUser(10, "M", roles=[FRole(ck.ROLE_MANAGER)], perms=FPerms())
        itx = FInteraction(mgr_role, salon, bot, message=FMessage())
        check("manager : role manager passe", await vue.interaction_check(itx))
        # Admin serveur sans le role
        mgr_admin = FUser(11, "A", roles=[FRole(999)], perms=FPerms(administrator=True))
        itx2 = FInteraction(mgr_admin, salon, bot, message=FMessage())
        check("manager : droits admin passent", await vue.interaction_check(itx2))
        # Ni l'un ni l'autre
        quidam = FUser(12, "Q", roles=[FRole(999)], perms=FPerms())
        itx3 = FInteraction(quidam, salon, bot, message=FMessage())
        ref = await vue.interaction_check(itx3)
        check("manager : quidam refuse", not ref)
        check("manager : quidam prevenu en ephemere",
              itx3.response.sends and itx3.response.sends[0][1].get("ephemeral") is True)

    asyncio.run(run())


# ---- 5) Flux complet : demande -> validation -> livraison -------------------

def test_flux_livraison():
    _reset(users={"111": {"channel_id": 999}})
    oc.ajouter("a@outlook.com", "SuperMotDePasse", SEED)
    ticket = FChannel(999, "va-ticket")
    salon = FChannel(1, "adresse-outlook")
    bot = FBot({999: ticket})
    cog = ck.OutlookCog(bot)

    async def run():
        va = FUser(111, "Bob")
        itx = FInteraction(va, salon, bot)
        await cog.demander(itx)
        check("demande : ephemere au VA",
              itx.response.sends and "manager" in itx.response.sends[0][0].lower())
        carte_contenu, carte_kw = salon.sent[-1]
        check("demande : la carte pingue le role manager",
              ("<@&%d>" % ck.ROLE_MANAGER) in carte_contenu)
        check("demande : la carte nomme le VA", ("<@%d>" % va.id) in carte_contenu)
        am = carte_kw.get("allowed_mentions")
        check("demande : seul le role manager est notifie",
              am is not None and getattr(am, "everyone", True) is False)
        # Retrouver l'id de la carte dans le registre des demandes.
        import safe_json
        dem = safe_json.load(ck.DEMANDES_FILE)
        mid = int(list(dem.keys())[0])
        carte_msg = FMessage(mid=mid)
        mgr = FUser(222, "Alice", perms=FPerms(administrator=True))
        itx2 = FInteraction(mgr, salon, bot, message=carte_msg)
        await cog.valider(itx2)
        check("validation : carte editee 'Attribuee'",
              itx2.response.edits and "Attribu" in itx2.response.edits[0]["content"])
        check("livraison : un message depose dans le ticket du VA", len(ticket.sent) == 1)
        livre = ticket.sent[-1][0]
        check("livraison : l'adresse est dans le ticket", "a@outlook.com" in livre)
        check("livraison : le mot de passe est dans le ticket", "SuperMotDePasse" in livre)
        check("livraison : la consigne 2FA renvoie au salon", "Code 2FA" in livre)
        # LE SEED n'apparait NULLE PART.
        rendu = _tout(itx.response, salon, itx2.response, ticket, carte_msg)
        check("securite : le seed n'est dans AUCUN envoi Discord", SEED not in rendu, "seed fuite !")
        # Le mot de passe n'est pas sur la carte publique.
        carte_rendu = _tout(salon, itx2.response, carte_msg)
        check("securite : le mot de passe n'est pas sur la carte publique",
              "SuperMotDePasse" not in carte_rendu)
        # Le compte est marque attribue.
        check("validation : compte marque attribue au bon VA",
              oc.compte_de_uid("111") is not None)
        # Re-demander quand on a deja un compte -> on renvoie au bouton 2FA.
        itx_bis = FInteraction(va, salon, bot)
        await cog.demander(itx_bis)
        check("demande : deja un compte -> renvoi vers 2FA",
              itx_bis.response.sends and "2FA" in itx_bis.response.sends[0][0]
              and len(salon.sent) == 1)   # pas de nouvelle carte

    asyncio.run(run())


# ---- 6) Repli : ticket manquant ---------------------------------------------

def test_repli_ticket():
    _reset(users={})       # aucun ticket connu pour ce VA
    oc.ajouter("a@outlook.com", "PWX", SEED)
    salon = FChannel(1, "adresse-outlook")
    bot = FBot({})         # aucun salon
    cog = ck.OutlookCog(bot)

    async def run():
        va = FUser(111, "Bob")
        itx = FInteraction(va, salon, bot)
        await cog.demander(itx)
        import safe_json
        mid = int(list(safe_json.load(ck.DEMANDES_FILE).keys())[0])
        mgr = FUser(222, "Alice", perms=FPerms(administrator=True))
        itx2 = FInteraction(mgr, salon, bot, message=FMessage(mid=mid))
        await cog.valider(itx2)
        # L'attribution n'est PAS perdue malgre le ticket manquant.
        check("repli : l'attribution est conservee", oc.compte_de_uid("111") is not None)
        # La carte signale que la livraison a echoue (note + manuel).
        contenu = itx2.response.edits[0]["content"] if itx2.response.edits else ""
        check("repli : la carte signale l'echec de livraison",
              "impossible" in contenu.lower() or "⚠" in contenu, contenu)

    asyncio.run(run())


# ---- 7) Pool vide a la validation -------------------------------------------

def test_validation_vide():
    _reset(users={"111": {"channel_id": 999}, "222": {"channel_id": 998}})
    oc.ajouter("seul@outlook.com", "PW", SEED)
    salon = FChannel(1, "adresse-outlook")
    bot = FBot({999: FChannel(999), 998: FChannel(998)})
    cog = ck.OutlookCog(bot)

    async def run():
        import safe_json
        # VA A prend le seul compte.
        a = FUser(111, "A")
        ia = FInteraction(a, salon, bot)
        await cog.demander(ia)
        mid_a = int([k for k, v in safe_json.load(ck.DEMANDES_FILE).items()
                     if v["uid"] == "111"][0])
        mgr = FUser(222, "Mgr", perms=FPerms(administrator=True))
        await cog.valider(FInteraction(mgr, salon, bot, message=FMessage(mid=mid_a)))
        # VA B demande alors qu'il n'y a plus rien.
        b = FUser(333, "B")
        ib = FInteraction(b, salon, bot)
        await cog.demander(ib)
        mid_b = int([k for k, v in safe_json.load(ck.DEMANDES_FILE).items()
                     if v["uid"] == "333"][0])
        itx_b = FInteraction(mgr, salon, bot, message=FMessage(mid=mid_b))
        await cog.valider(itx_b)
        check("validation vide : manager averti 'aucune libre'",
              itx_b.response.sends and "libre" in itx_b.response.sends[0][0].lower())
        check("validation vide : rien d'edite (pas d'attribution)",
              not itx_b.response.edits)
        check("validation vide : B n'a pas de compte", oc.compte_de_uid("333") is None)

    asyncio.run(run())


# ---- 8) Bouton 2FA ----------------------------------------------------------

def test_2fa():
    _reset()
    oc.ajouter("a@outlook.com", "PW", SEED)
    oc.attribuer("111", "Bob")
    salon = FChannel(1, "adresse-outlook")
    bot = FBot()
    cog = ck.OutlookCog(bot)

    async def run():
        # VA attribue -> code a 6 chiffres, ephemere, sans seed.
        va = FUser(111, "Bob")
        itx = FInteraction(va, salon, bot)
        await cog.code_2fa(itx)
        contenu, kw = itx.response.sends[0]
        check("2FA : reponse ephemere", kw.get("ephemeral") is True)
        import re
        m = re.search(r"\*\*(\d{6})\*\*", contenu)
        check("2FA : un code a 6 chiffres", bool(m), contenu)
        check("2FA : l'adresse est rappelee", "a@outlook.com" in contenu)
        check("2FA : le seed n'apparait pas", SEED not in _tout(itx.response))
        # VA sans compte -> on l'invite a demander.
        autre = FUser(888, "Zoe")
        itx2 = FInteraction(autre, salon, bot)
        await cog.code_2fa(itx2)
        check("2FA : sans compte -> 'fais la demande'",
              itx2.response.sends and "demande" in itx2.response.sends[0][0].lower())

    asyncio.run(run())


# ---- 9) Page /outlook (dashboard) -------------------------------------------

def test_dashboard():
    _reset()
    import web_upload as w
    app = w.create_app()
    app.config["TESTING"] = True
    _orig = w._load_web_users

    # Admin (owner) : acces complet.
    w._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    c = app.test_client()
    with c.session_transaction() as s:
        s["auth"] = True
        s["username"] = "boss"
        s["role"] = "owner"
    # Ajout valide via la VRAIE route (le chemin d'ajout de la page).
    r = c.post("/outlook/add", data={"email": "a@outlook.com",
                                     "password": "MotDePasseSecret",
                                     "seed": SEED})
    check("page : ajout valide accepte (303)", r.status_code == 303, r.status_code)
    check("page : compte stocke", len(oc.comptes()) == 1)
    # Ajout d'un mauvais seed : refuse, rien stocke.
    r2 = c.post("/outlook/add", data={"email": "b@outlook.com",
                                      "password": "pw", "seed": "pas-base32-!"})
    check("page : mauvais seed refuse (400)", r2.status_code == 400, r2.status_code)
    check("page : mauvais seed non stocke", len(oc.comptes()) == 1)
    # Rendu : masquage.
    g = c.get("/outlook")
    html = g.get_data(as_text=True)
    check("page : rendue pour l'admin (200)", g.status_code == 200, g.status_code)
    check("page : le seed est ABSENT du HTML", SEED not in html)
    check("page : le mot de passe est ABSENT du HTML", "MotDePasseSecret" not in html)
    check("page : l'adresse est visible", "a@outlook.com" in html)
    check("page : le masque est present", oc.MASQUE in html)
    # Finding 2 : le navigateur ne doit pas retenir le mot de passe ni le seed.
    check("page : mot de passe en champ masque (type=password)",
          "name='password' type='password'" in html)
    check("page : autocomplete desactive (mot de passe + seed)",
          html.count("autocomplete='off'") >= 3)
    check("page : seed sans correction auto (spellcheck=false)",
          "spellcheck='false'" in html)

    # Non authentifie -> redirige vers l'accueil.
    canon = app.test_client()
    ra = canon.get("/outlook")
    check("page : anonyme redirige (302)", ra.status_code in (301, 302), ra.status_code)

    # Role restreint -> refuse (403), en lecture comme en ecriture.
    w._load_web_users = lambda: {"chat": {"role": "chatter", "password": "x"}}
    cr = app.test_client()
    with cr.session_transaction() as s:
        s["auth"] = True
        s["username"] = "chat"
        s["role"] = "chatter"
    check("page : role restreint refuse en lecture (403)",
          cr.get("/outlook").status_code == 403)
    check("page : role restreint refuse en ecriture (403)",
          cr.post("/outlook/add", data={"email": "x", "password": "y",
                                        "seed": SEED}).status_code == 403)
    w._load_web_users = _orig


# ---- 10) Panneau : un seul, jamais deux (finding 3) -------------------------
# Faux salon capable d'historique/suppression (les FChannel ci-dessus ne le
# sont pas), pour prouver que le panneau n'est jamais double.

import discord as _discord


class _Resp404:
    status = 404
    reason = "Not Found"


class FBtn:
    def __init__(self, cid):
        self.custom_id = cid


class FRow:
    def __init__(self, kids):
        self.children = kids


class FPanelMsg:
    _n = 80000

    def __init__(self, author_id, custom_ids, content=None, mid=None):
        FPanelMsg._n += 1
        self.id = mid if mid is not None else FPanelMsg._n
        self.author = FUser(author_id)
        self.content = content
        self.components = [FRow([FBtn(c) for c in custom_ids])] if custom_ids else []
        self.deleted = False
        self.edits = []

    async def delete(self):
        self.deleted = True

    async def edit(self, **kw):
        self.edits.append(kw)


class _AIter:
    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FPanelChannel:
    def __init__(self, cid, bot_id, name="adresse-outlook"):
        self.id = cid
        self.name = name
        self._bot = bot_id
        self.msgs = []

    async def send(self, content=None, view=None, **kw):
        cids = [getattr(ch, "custom_id", None)
                for ch in (getattr(view, "children", []) or [])]
        m = FPanelMsg(self._bot, [c for c in cids if c], content=content)
        self.msgs.append(m)
        return m

    async def fetch_message(self, mid):
        for m in self.msgs:
            if m.id == int(mid) and not m.deleted:
                return m
        raise _discord.NotFound(_Resp404(), "introuvable")

    def history(self, limit=None):
        live = [m for m in reversed(self.msgs) if not m.deleted]
        return _AIter(live[:limit] if limit else live)

    def panneaux_vivants(self):
        return [m for m in self.msgs if not m.deleted
                and any(b.custom_id in ck.CID_PANNEAU
                        for r in m.components for b in r.children)]


class FPanelBot:
    def __init__(self, bot_id=500500, channels=None):
        self.user = FUser(bot_id)
        self._ch = channels or {}

    def get_channel(self, cid):
        return self._ch.get(int(cid))

    def get_cog(self, name):
        return None


def test_panneau_unique():
    _reset()
    bot = FPanelBot()
    cog = ck.OutlookCog(bot)
    ch = FPanelChannel(1, bot.user.id)

    async def run():
        import safe_json
        await cog._assurer_panneau(ch)
        check("panneau : un seul au 1er passage", len(ch.panneaux_vivants()) == 1)
        mid1 = ch.panneaux_vivants()[0].id
        # data/ reparti de zero (le VPS repart d'un etat vide a chaque push),
        # mais le message du panneau est toujours dans le salon.
        safe_json.write(ck.PANNEAUX_FILE, {})
        await cog._assurer_panneau(ch)
        vivants = ch.panneaux_vivants()
        check("panneau : PAS de doublon apres perte du registre",
              len(vivants) == 1, "%d panneaux" % len(vivants))
        check("panneau : le panneau existant est reutilise",
              vivants and vivants[0].id == mid1)
        check("panneau : le registre repointe le panneau retrouve",
              safe_json.load(ck.PANNEAUX_FILE).get("1") == mid1)
        # Deux panneaux deja presents (sequelle d'un vieux doublon) -> menage.
        safe_json.write(ck.PANNEAUX_FILE, {})
        await ch.send(ck.TEXTE_PANNEAU, view=ck.PanneauOutlook(cog))
        check("panneau : deux panneaux presents avant menage",
              len(ch.panneaux_vivants()) == 2)
        await cog._assurer_panneau(ch)
        check("panneau : le doublon est balaye (retour a un seul)",
              len(ch.panneaux_vivants()) == 1, "%d panneaux" % len(ch.panneaux_vivants()))
        # Registre pointant un message disparu -> on ne double pas non plus.
        safe_json.write(ck.PANNEAUX_FILE, {"1": 424242})
        await cog._assurer_panneau(ch)
        check("panneau : registre perime (message absent) -> toujours un seul",
              len(ch.panneaux_vivants()) == 1, "%d panneaux" % len(ch.panneaux_vivants()))

    asyncio.run(run())


# ---- 11) Double validation concurrente (finding 4) --------------------------

def test_double_validation():
    _reset(users={"111": {"channel_id": 999}})
    oc.ajouter("a@outlook.com", "SuperMotDePasse", SEED)

    class SlowTicket(FPanelChannel):
        async def send(self, content=None, **kw):
            await asyncio.sleep(0)     # cede la main : simule la latence reseau
            m = FPanelMsg(self._bot, [], content=content)
            self.msgs.append(m)
            return m

    ticket = SlowTicket(999, 500500, "ticket")
    salon = FPanelChannel(1, 500500)
    bot = FPanelBot(channels={999: ticket})
    cog = ck.OutlookCog(bot)

    async def run():
        import safe_json
        await cog.demander(FInteraction(FUser(111, "Bob"), salon, bot))
        mid = int(list(safe_json.load(ck.DEMANDES_FILE).keys())[0])
        mgr = FUser(222, "Alice", perms=FPerms(administrator=True))
        i1 = FInteraction(mgr, salon, bot, message=FPanelMsg(500500, [], mid=mid))
        i2 = FInteraction(mgr, salon, bot, message=FPanelMsg(500500, [], mid=mid))
        # Deux managers valident la MEME carte en meme temps.
        await asyncio.gather(cog.valider(i1), cog.valider(i2))
        livraisons = [m for m in ticket.msgs if "SuperMotDePasse" in (m.content or "")]
        check("double validation : le mot de passe n'est livre QU'UNE fois",
              len(livraisons) == 1, "%d livraisons" % len(livraisons))
        check("double validation : un seul compte attribue",
              sum(1 for c in oc.comptes() if c["statut"] == "attribue") == 1)
        # Le second clic a ete prevenu, pas edite deux fois en 'Attribuee'.
        edits = (i1.response.edits, i2.response.edits)
        attrib = sum(1 for e in edits if e and "Attribu" in e[0].get("content", ""))
        check("double validation : une seule carte editee 'Attribuee'", attrib == 1)

    asyncio.run(run())


# ---- 12) Demande repetee avant validation (finding 5) -----------------------

def test_demande_doublon():
    _reset(users={"111": {"channel_id": 999}})
    oc.ajouter("a@outlook.com", "PW", SEED)
    salon = FPanelChannel(1, 500500)
    bot = FPanelBot(channels={999: FPanelChannel(999, 500500)})
    cog = ck.OutlookCog(bot)

    async def run():
        va = FUser(111, "Bob")
        await cog.demander(FInteraction(va, salon, bot))
        await cog.demander(FInteraction(va, salon, bot))
        i3 = FInteraction(va, salon, bot)
        await cog.demander(i3)
        cartes = [m for m in salon.msgs if "demande une adresse" in (m.content or "")]
        check("demande doublon : une seule carte pour 3 clics",
              len(cartes) == 1, "%d cartes" % len(cartes))
        check("demande doublon : les clics suivants previennent en ephemere",
              i3.response.sends and "attente" in i3.response.sends[0][0].lower())

    asyncio.run(run())


def main():
    print("=" * 70)
    print("tests_outlook.py — coffre d'adresses Outlook")
    print("=" * 70)
    test_totp()
    test_ajout()
    test_pool()
    test_manager()
    test_flux_livraison()
    test_repli_ticket()
    test_validation_vide()
    test_2fa()
    test_dashboard()
    test_panneau_unique()
    test_double_validation()
    test_demande_doublon()
    print("=" * 70)
    print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
    if FAILS:
        for f in FAILS:
            print("  - " + f)
    print("=" * 70)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
