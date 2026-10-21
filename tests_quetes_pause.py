"""Quêtes en pause : « pour tous les trucs, pour le moment retire les quêtes ».

13/10/2026 : le propriétaire envoie la capture d'un ticket VA (« 🎯 Quête
validée », « 🎯 Quête à valider » et ses boutons Valider/Refuser) et demande
de retirer les quêtes « pour le moment ». quetes_discord.QUETES_EN_PAUSE.

Vérifié ici, sans réseau ni vrai data/ (Discord simulé, état des quêtes dans
un dossier temporaire) :
- aucune quête du jour n'est postée, sur AUCUN serveur, et le journal le dit
  une fois par jour ;
- le bouton « Valider ma quête » d'un ancien message répond la pause et
  n'écrit rien ;
- une demande déjà partie chez un manager se tranche toujours (crédit) ;
- /quetes montre toujours le total de la saison, avec la ligne de pause ;
- les messages de quête déjà postés perdent leur bouton UNE fois, par le bot
  de leur serveur, sans jamais être effacés ; un échec est réessayé ;
- un verdict de manager tombé pendant le retrait n'est pas écrasé ;
- interrupteur à False : exactement le comportement du module sans la pause
  (le même fichier, gardes de l'interrupteur ôtées — comparé appel par appel
  et octet par octet), et, tant que le module n'a pas évolué depuis, celui de
  quetes_discord.py du commit c5e9f59 ;
- la valeur livrée de l'interrupteur n'est PAS imposée : la reprise (False)
  ne fait échouer aucun test.

Lancer depuis la racine du dépôt : python tests_quetes_pause.py
"""
from __future__ import annotations

import ast
import contextlib
import copy
import datetime as dt
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import quetes_discord as Q              # noqa: E402
import tickets_discord as TK            # noqa: E402
import verif_discord as VD              # noqa: E402

OKS, FAILS = [], []


def check(nom, cond, detail=""):
    if cond:
        OKS.append(nom)
        print("OK   " + nom)
    else:
        FAILS.append(nom)
        print("FAIL " + nom + (f"  [{str(detail)[:300]}]" if detail != "" else ""))


TW, TH, IG, ENT = VD.TWITTER_ID, VD.THREADS_ID, VD.VA_IG_ID, VD.GUILD_ID
AUJ = dt.date.today()
HIER = AUJ - dt.timedelta(days=1)
AVANT_HIER = AUJ - dt.timedelta(days=2)
SALONS = {TW: "7001", TH: "7002", IG: "7003", ENT: "7004"}
MGR = "r-mgr"
TMP = pathlib.Path(tempfile.mkdtemp())


class FauxDiscord:
    """Ce que le module demande à Discord, et sous quel serveur courant."""

    def __init__(self):
        self.appels = []
        self.reponses = {}          # (methode, chemin) -> liste de (code, corps), consommée
        self.pendant = None         # rappel appelé à chaque appel (concurrence)
        self.n = 0

    def __call__(self, methode, chemin, **kw):
        self.appels.append({"m": methode, "p": chemin, "json": kw.get("json"),
                            "gid": VD.serveur_courant()})
        if self.pendant:
            self.pendant(methode, chemin)
        file = self.reponses.get((methode, chemin))
        if file:
            return file.pop(0)
        if methode == "GET" and chemin.startswith("/guilds/") and chemin.endswith("/channels"):
            g = chemin.split("/")[2]
            return 200, [{"id": "1", "name": "général"},
                         {"id": SALONS.get(g, "7999"), "name": Q.SALON_QUETES}]
        self.n += 1
        return 200, {"id": f"m{self.n}"}

    def de(self, methode):
        return [a for a in self.appels if a["m"] == methode]


def reponse(r):
    return ((r or {}).get("data") or {}).get("content", "")


def clic(mod, uid, cid, gid=TW, roles=None, message=None):
    p = {"type": 3, "guild_id": gid, "member": {"user": {"id": uid}, "roles": roles or []},
         "data": {"custom_id": cid}}
    if message:
        p["message"] = {"id": message}
    return mod.traiter(p)


def commande(mod, uid, gid=TW):
    return mod.traiter({"type": 2, "guild_id": gid, "member": {"user": {"id": uid}},
                        "data": {"name": "quetes"}})


def installer(mod, nom, pause=None):
    """Un état neuf dans le dossier temporaire et un faux Discord."""
    mod.ETAT_FICHIER = TMP / f"{nom}.json"
    mod.CATALOGUE_FICHIER = TMP / "pas_de_catalogue.json"
    if mod.ETAT_FICHIER.exists():
        mod.ETAT_FICHIER.unlink()
    f = FauxDiscord()
    mod._api = f
    if pause is not None:
        mod.QUETES_EN_PAUSE = pause
    if hasattr(mod, "_PAUSE_DITE"):
        mod._PAUSE_DITE.clear()
    return f


def etat(mod):
    try:
        return json.loads(mod.ETAT_FICHIER.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def poser_etat(mod, d):
    mod.ETAT_FICHIER.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


@contextlib.contextmanager
def journal():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def passage_du_demon(mod, jour):
    """La boucle de web_upload._start_quete_du_jour_daemon, telle quelle."""
    for gid in VD.SERVEURS_EXTRA:
        with VD.sur_serveur(gid):
            mod.poster_quete(gid, jour)


class _SansPause(ast.NodeTransformer):
    """Le module tel qu'il serait si la pause n'avait jamais été écrite.

    Chaque « if QUETES_EN_PAUSE…: » est remplacé par sa branche else (ici,
    rien) et chaque « with _VERROU_ETAT: » est déroulé : le verrou ne sert
    qu'au retrait des boutons, qui ne tourne qu'en pause. Une lecture de
    l'interrupteur sous une autre forme n'est pas ôtée : elle reste visible
    dans les lectures restantes, et la comparaison est alors déclarée sans
    valeur (sinon elle comparerait le code à lui-même et passerait toujours).
    """

    def __init__(self):
        self.gardes = 0
        self.verrous = 0

    @staticmethod
    def _est_garde(t):
        if isinstance(t, ast.Name) and t.id == "QUETES_EN_PAUSE":
            return True
        # « QUETES_EN_PAUSE and … » : à False, la suite n'est même pas évaluée
        return (isinstance(t, ast.BoolOp) and isinstance(t.op, ast.And)
                and isinstance(t.values[0], ast.Name) and t.values[0].id == "QUETES_EN_PAUSE")

    def visit_If(self, node):
        self.generic_visit(node)
        if self._est_garde(node.test):
            self.gardes += 1
            return node.orelse or None
        return node

    def visit_With(self, node):
        self.generic_visit(node)
        if (len(node.items) == 1 and node.items[0].optional_vars is None
                and isinstance(node.items[0].context_expr, ast.Name)
                and node.items[0].context_expr.id == "_VERROU_ETAT"):
            self.verrous += 1
            return node.body
        return node


def sans_pause(source):
    """(arbre sans la pause, gardes ôtées, verrous déroulés, lignes où
    l'interrupteur est encore lu)."""
    t = _SansPause()
    arbre = t.visit(ast.parse(source))
    for n in ast.walk(arbre):
        # une garde seule dans son bloc le laisserait vide : Python le refuse
        if isinstance(getattr(n, "body", None), list) and not n.body:
            n.body = [ast.Pass()]
    ast.fix_missing_locations(arbre)
    lectures = [n.lineno for n in ast.walk(arbre)
                if isinstance(n, ast.Name) and n.id == "QUETES_EN_PAUSE"
                and not isinstance(n.ctx, ast.Store)]
    return arbre, t.gardes, t.verrous, lectures


def module_de(nom, source_ou_arbre):
    """Un module chargé à part. Son __file__ est dans le dossier temporaire :
    DATA_DIR (voisin de __file__) n'est jamais le vrai data/."""
    m = types.ModuleType(nom)
    m.__file__ = str(TMP / f"{nom}.py")
    exec(compile(source_ou_arbre, m.__file__, "exec"), m.__dict__)
    return m


def definitions(arbre):
    """{nom: forme} des instructions de premier niveau, docstrings ôtées (les
    commentaires ne sont pas dans l'arbre) : ce qui fait le comportement."""
    arbre = copy.deepcopy(arbre)
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                n.body = b[1:] or [ast.Pass()]
    out = {}
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            k = n.name
        elif isinstance(n, ast.Assign):
            k = " = ".join(ast.unparse(c) for c in n.targets)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            k = ast.unparse(n.target)
        elif isinstance(n, ast.ImportFrom):
            k = f"from {n.module} import " + ", ".join(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            k = "import " + ", ".join(a.name for a in n.names)
        else:
            k = ast.unparse(n)[:60]
        while k in out:
            k += "'"
        out[k] = ast.dump(n)
    return out


def module_a_evolue_depuis(ref):
    """Un commit postérieur à `ref` a-t-il touché quetes_discord.py ? Faux
    tant que la pause n'est pas commitée ; None si git ne répond pas."""
    try:
        r = subprocess.run(["git", "log", "--format=%H", f"{ref}..HEAD", "--", "quetes_discord.py"],
                           cwd=BOT, capture_output=True, text=True, timeout=30)
    except Exception:                                        # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


SAUVE = (Q.ETAT_FICHIER, Q.CATALOGUE_FICHIER, Q._api, Q.QUETES_EN_PAUSE,
         TK.ticket_de, TK.role_manager)
TK.role_manager = lambda gid: MGR
TK.ticket_de = lambda gid, uid: f"tick-{uid}"
try:
    # ============================================================ 0. --
    print("=" * 70)
    print("0. L'interrupteur")
    print("=" * 70)
    # « Pour le moment » : la reprise, c'est passer l'interrupteur à False.
    # On vérifie qu'il existe, que c'est un vrai booléen et d'où il vient, PAS
    # sa valeur : imposer True faisait échouer cette suite le jour de la
    # reprise (deux échecs à corriger en même temps, ou à laisser traîner).
    # Les scénarios 1 à 5 forcent la pause, le 6 la lève, quelle que soit la
    # valeur livrée.
    check("l'interrupteur existe et est un vrai booléen", isinstance(SAUVE[3], bool), repr(SAUVE[3]))
    print(f"INFO interrupteur livré : QUETES_EN_PAUSE = {SAUVE[3]} — "
          + ("quêtes en pause" if SAUVE[3] else "quêtes en marche"))
    check("textes de la pause",
          Q.PAUSE_TEXTE == "⏸️ Les quêtes sont en pause pour le moment."
          and Q.PAUSE_LIGNE_MESSAGE == "⏸️ **Quêtes en pause** pour le moment.")
    src = (BOT / "quetes_discord.py").read_text(encoding="utf-8")
    check("le commentaire cite le propriétaire",
          "pour le moment retire les quêtes" in src
          and re.search(r"^QUETES_EN_PAUSE = (True|False)\s*(#.*)?$", src, re.M) is not None)

    # ============================================================ 1. --
    print()
    print("=" * 70)
    print("1. Plus de quête du jour, sur aucun serveur")
    print("=" * 70)
    f = installer(Q, "p1", pause=True)
    with journal() as j1:
        passage_du_demon(Q, AUJ)
        passage_du_demon(Q, AUJ)            # le démon repasse toutes les 10 min
        r_ent = Q.poster_quete(ENT, AUJ)    # même un appel à la main
    check("aucun message posté (Twitter, Threads, Va IG, Entretien)",
          not f.de("POST") and r_ent == "", f.appels)
    check("rien à faire = aucun appel à Discord du tout (pas de GET des salons)", not f.appels, f.appels)
    check("l'état n'a pas reçu de quête postée", not ((etat(Q) or {}).get("postees")), etat(Q))
    lignes = [l for l in j1.getvalue().splitlines() if "en pause (QUETES_EN_PAUSE)" in l]
    check("le journal le dit une fois par serveur et par jour (pas à chaque passage)",
          len([l for l in lignes if TW in l]) == 1 and len([l for l in lignes if TH in l]) == 1,
          lignes)
    check("… et pas pour Va IG, qui n'a jamais eu de quête",
          not [l for l in lignes if IG in l], lignes)
    with journal() as j1b:
        passage_du_demon(Q, AUJ + dt.timedelta(days=1))
    check("le lendemain, une nouvelle ligne",
          len([l for l in j1b.getvalue().splitlines() if "en pause" in l]) == 2, j1b.getvalue())

    # ============================================================ 2. --
    print()
    print("=" * 70)
    print("2. Le bouton d'un ancien message : la pause, et rien d'écrit")
    print("=" * 70)
    f = installer(Q, "p2", pause=True)
    poser_etat(Q, {"postees": {f"{TW}:{HIER}": "500"}, "demandes": {}})
    avant = Q.ETAT_FICHIER.read_bytes()
    r = clic(Q, "99", f"quete:go:{HIER}")
    check("réponse : « ⏸️ Les quêtes sont en pause pour le moment. », éphémère",
          reponse(r) == Q.PAUSE_TEXTE and r["type"] == 4 and r["data"]["flags"] == 64, r)
    check("aucun appel à Discord (rien dans l'espace perso)", not f.appels, f.appels)
    check("l'état n'est pas touché, à l'octet près", Q.ETAT_FICHIER.read_bytes() == avant)
    r = clic(Q, "99", "quete:go")
    check("un bouton sans date répond pareil", reponse(r) == Q.PAUSE_TEXTE)
    r = Q.traiter({"type": 3, "guild_id": TW, "member": {"user": {"id": "9"}},
                   "data": {"custom_id": "verif:start"}})
    check("un bouton qui n'est pas une quête passe toujours la main (None)", r is None)
    check("le PING aussi", Q.traiter({"type": 1}) is None)
    check("le clic d'un non-manager sur Valider reste refusé",
          "Manager" in reponse(clic(Q, "77", f"quete:ok:99:{HIER}")))

    # ============================================================ 3. --
    print()
    print("=" * 70)
    print("3. Une demande déjà partie se tranche toujours")
    print("=" * 70)
    f = installer(Q, "p3", pause=True)
    s = Q.saison(AUJ)
    poser_etat(Q, {"demandes": {
        f"{TW}:99:{AUJ}": {"quete": "subs_jour_5", "titre": "Faire 5 subs aujourd'hui",
                           "montant": 0.5, "etat": "attente", "saison": s, "salon": "tick-99",
                           "message": "800", "demande": 1},
        f"{TW}:88:{AUJ}": {"quete": "tweets_3", "titre": "Poster 3 tweets aujourd'hui",
                           "montant": 0.25, "etat": "attente", "saison": s, "salon": "tick-88",
                           "message": "801", "demande": 1}}})
    check("avant : rien de crédité", Q.gains(TW, "99")["montant"] == 0)
    r = clic(Q, "10", f"quete:ok:99:{AUJ}", roles=[MGR], message="800")
    check("le manager valide : la demande est remplacée par le verdict (type 7, sans boutons)",
          r["type"] == 7 and r["data"]["components"] == []
          and r["data"]["embeds"][0]["title"] == "🎯 Quête validée", r)
    g = Q.gains(TW, "99")
    check("… et la récompense est CRÉDITÉE", g["montant"] == 0.5 and g["quetes"] == 1, g)
    check("… et le membre est prévenu dans son espace perso, total compris",
          any(a["p"] == "/channels/tick-99/messages" and "Total de la saison : **0.50$**"
              in (a["json"] or {}).get("content", "") for a in f.de("POST")), f.appels)
    r = clic(Q, "10", f"quete:no:88:{AUJ}", roles=[MGR], message="801")
    check("un refus aussi passe", r["type"] == 7 and "refusée" in r["data"]["embeds"][0]["title"]
          and ((etat(Q).get("demandes") or {}).get(f"{TW}:88:{AUJ}") or {}).get("etat") == "non")
    r = clic(Q, "10", f"quete:ok:99:{AUJ}", roles=[MGR])
    check("pas de double paiement", "déjà" in reponse(r) and Q.gains(TW, "99")["montant"] == 0.5)

    # ============================================================ 4. --
    print()
    print("=" * 70)
    print("4. /quetes : le total de la saison, et la pause")
    print("=" * 70)
    r = commande(Q, "99")
    check("/quetes avec des gains : total + ligne de pause",
          reponse(r) == (f"💰 Saison **{s}** : **0.50$** sur **1** quête(s) validée(s).\n"
                         "⚠️ Payé après validation de ta période d'essai.\n"
                         "⏸️ Les quêtes sont en pause pour le moment.")
          and r["data"]["flags"] == 64, reponse(r))
    r = commande(Q, "55")
    check("/quetes sans gains : la pause, plus le conseil de cliquer Valider",
          reponse(r) == (f"💰 Aucune quête validée pour la saison **{s}**.\n"
                         "⏸️ Les quêtes sont en pause pour le moment.")
          and "Valider ma quête" not in reponse(r), reponse(r))

    # ============================================================ 5. --
    print()
    print("=" * 70)
    print("5. Les messages déjà postés perdent leur bouton, une fois")
    print("=" * 70)
    f = installer(Q, "p5", pause=True)
    poser_etat(Q, {"postees": {
        f"{TW}:{AVANT_HIER}": "t-ah", f"{TW}:{HIER}": "t-h", f"{TW}:{AUJ}": "t-auj",
        f"{TH}:{HIER}": "s-h", f"{TH}:{AUJ}": "s-auj",
        f"{ENT}:{HIER}": "e-h"},
        "demandes": {f"{TH}:42:{HIER}": {"etat": "attente", "montant": 1.0, "saison": Q.saison(HIER),
                                         "titre": "x", "salon": "tick-42", "message": "900"}}})
    # Threads, hier : posté par Siri avant le bot Threads -> refus définitif
    f.reponses[("PATCH", f"/channels/{SALONS[TH]}/messages/s-h")] = [
        (403, {"code": 50005, "message": "Cannot edit a message authored by another user"})]
    # Twitter, avant-hier : un échec passager, réessayé au passage suivant
    f.reponses[("PATCH", f"/channels/{SALONS[TW]}/messages/t-ah")] = [
        (500, {"message": "panne"})]
    # Twitter, hier : le message a été effacé à la main
    f.reponses[("PATCH", f"/channels/{SALONS[TW]}/messages/t-h")] = [
        (404, {"code": 10008, "message": "Unknown Message"})]
    with journal() as j5:
        passage_du_demon(Q, AUJ)
    patchs = f.de("PATCH")
    check("une modification par message, sur chaque serveur visité",
          sorted(a["p"].rsplit("/", 1)[-1] for a in patchs) == ["s-auj", "s-h", "t-ah", "t-auj", "t-h"],
          [a["p"] for a in patchs])
    check("chaque modification part sous le bot de SON serveur (sur_serveur)",
          all(a["gid"] == (TW if a["p"].startswith(f"/channels/{SALONS[TW]}/") else TH) for a in patchs)
          and all(a["gid"] == a["p"].split("/")[2] for a in f.de("GET")), f.appels)
    check("le bouton disparaît, la ligne de pause est posée, personne n'est notifié",
          all(a["json"] == {"content": "⏸️ **Quêtes en pause** pour le moment.", "components": [],
                            "allowed_mentions": {"parse": []}} for a in patchs), patchs[:1])
    check("l'embed de la quête n'est pas renvoyé (la quête et son montant restent)",
          all("embeds" not in a["json"] for a in patchs))
    check("jamais d'effacement", not f.de("DELETE"))
    check("le plus récent d'abord (celui sur lequel on clique)",
          [a["p"].rsplit("/", 1)[-1] for a in patchs if a["gid"] == TW] == ["t-auj", "t-h", "t-ah"])
    tr = etat(Q).get("pause_boutons") or {}
    check("trace : retirés, disparu et autre bot notés ; l'échec passager NON noté",
          {k: v["etat"] for k, v in tr.items()} == {
              f"{TW}:{AUJ}": "retire", f"{TW}:{HIER}": "absent",
              f"{TH}:{AUJ}": "retire", f"{TH}:{HIER}": "autre_bot"}, tr)
    jl = j5.getvalue()
    check("le journal dit l'échec, le disparu, l'autre bot et le bilan",
          "non retiré" in jl and "HTTP 500" in jl and "introuvable" in jl and "autre bot" in jl
          and f"pause sur {TW} : 1 bouton(s) retiré(s), 1 message(s) disparu(s), 0 d'un autre bot, 1 à réessayer" in jl
          and f"pause sur {TH} : 1 bouton(s) retiré(s), 0 message(s) disparu(s), 1 d'un autre bot, 0 à réessayer" in jl,
          jl)
    check("Entretien (que le démon ne visite pas) : dit au journal, pas modifié",
          f"1 quête(s) postée(s) sur {ENT}" in jl and not [a for a in patchs if "e-h" in a["p"]], jl)
    check("la demande en attente n'a pas bougé",
          ((etat(Q).get("demandes") or {}).get(f"{TH}:42:{HIER}") or {}).get("etat") == "attente")
    n_avant = len(f.appels)
    with journal() as j5b:
        passage_du_demon(Q, AUJ)
    nouveaux = f.appels[n_avant:]
    check("passage suivant : seul l'échec passager est réessayé",
          [a["p"].rsplit("/", 1)[-1] for a in nouveaux if a["m"] == "PATCH"] == ["t-ah"]
          and [a["gid"] for a in nouveaux] == [TW, TW], nouveaux)
    check("… et cette fois il est noté", ((etat(Q).get("pause_boutons") or {}).get(f"{TW}:{AVANT_HIER}") or {}).get("etat") == "retire")
    n_avant = len(f.appels)
    with journal():
        passage_du_demon(Q, AUJ)
        passage_du_demon(Q, AUJ)
    check("ensuite : plus aucun appel à Discord (idempotent)", len(f.appels) == n_avant, f.appels[n_avant:])
    n_avant = len(f.appels)
    with journal(), VD.sur_serveur(TW):        # appelé depuis le travail d'un AUTRE serveur
        b = Q.retirer_boutons(ENT)
    check("retirer_boutons à la main sur Entretien, depuis Twitter : sous le bot d'Entretien",
          b["retires"] == 1 and [a["m"] for a in f.appels[n_avant:]] == ["GET", "PATCH"]
          and all(a["gid"] == ENT for a in f.appels[n_avant:])
          and f.appels[-1]["p"] == f"/channels/{SALONS[ENT]}/messages/e-h", f.appels[n_avant:])

    # salons illisibles (panne Discord) : rien n'est noté, on réessaie
    f = installer(Q, "p5b", pause=True)
    poser_etat(Q, {"postees": {f"{TW}:{AUJ}": "t-auj"}})
    f.reponses[("GET", f"/guilds/{TW}/channels")] = [(503, {"message": "panne"})]
    with journal() as j5c:
        Q.poster_quete(TW, AUJ)
    check("salons illisibles : dit, rien noté, aucune modification",
          "illisibles" in j5c.getvalue() and not f.de("PATCH") and not (etat(Q).get("pause_boutons")),
          j5c.getvalue())
    with journal():
        Q.poster_quete(TW, AUJ)
    check("… et réessayé au passage suivant", len(f.de("PATCH")) == 1
          and ((etat(Q).get("pause_boutons") or {}).get(f"{TW}:{AUJ}") or {}).get("etat") == "retire")

    # salon des quêtes SUPPRIMÉ (Threads, 13/10/2026) : la liste se lit, il n'y
    # est plus. Noté une fois, puis plus aucun appel — avant, le démon
    # réessayait toutes les 10 min, sans fin.
    f = installer(Q, "p5d", pause=True)
    poser_etat(Q, {"postees": {f"{TH}:{AUJ}": "h-auj", f"{TH}:{HIER}": "h-h"}})
    f.reponses[("GET", f"/guilds/{TH}/channels")] = [(200, [{"id": "1", "name": "général"}])]
    with journal() as j5d:
        b = Q.retirer_boutons(TH)
    tr = etat(Q).get("pause_boutons") or {}
    check("salon supprimé : dit une fois, les deux quêtes notées « salon_absent », aucun PATCH",
          "absent de" in j5d.getvalue() and "plus d'essai" in j5d.getvalue() and not f.de("PATCH")
          and {k: v["etat"] for k, v in tr.items()} == {f"{TH}:{AUJ}": "salon_absent",
                                                        f"{TH}:{HIER}": "salon_absent"}
          and b["absents"] == 2 and b["echecs"] == 0, (j5d.getvalue(), tr, b))
    n_avant = len(f.appels)
    with journal() as j5e:
        Q.retirer_boutons(TH)
        Q.retirer_boutons(TH)
    check("… puis plus aucun appel à Discord ni ligne au journal",
          len(f.appels) == n_avant and not j5e.getvalue().strip(), (f.appels[n_avant:], j5e.getvalue()))

    # un manager tranche PENDANT que le démon modifie les messages
    f = installer(Q, "p5c", pause=True)
    poser_etat(Q, {"postees": {f"{TW}:{AUJ}": "t-auj"},
                   "demandes": {f"{TW}:99:{HIER}": {"etat": "attente", "montant": 2.0, "titre": "x",
                                                    "saison": Q.saison(AUJ), "salon": "tick-99",
                                                    "message": "800"}}})
    deja = []

    def _manager_pendant(methode, chemin):
        if methode == "PATCH" and not deja:
            deja.append(1)
            Q._trancher(TW, "99", str(HIER), True, "10", {"message": {"id": "800"}})

    f.pendant = _manager_pendant
    with journal():
        Q.poster_quete(TW, AUJ)
    e5 = etat(Q)
    check("un verdict tombé pendant le retrait n'est pas écrasé (crédit gardé)",
          deja and ((e5.get("demandes") or {}).get(f"{TW}:99:{HIER}") or {}).get("etat") == "ok"
          and ((e5.get("pause_boutons") or {}).get(f"{TW}:{AUJ}") or {}).get("etat") == "retire", e5)

    # ============================================================ 6. --
    print()
    print("=" * 70)
    print("6. Interrupteur à False : le comportement sans la pause, à l'octet près")
    print("=" * 70)
    fige = types.SimpleNamespace(time=lambda: 1760300000.0)

    def scenario(mod):
        fd = installer(mod, "s_" + mod.__name__, pause=False if hasattr(mod, "QUETES_EN_PAUSE") else None)
        mod.time = fige
        rep = []
        sans = TK.ticket_de
        with journal() as jj:
            rep.append(mod.poster_quete(TW, AUJ))
            rep.append(mod.poster_quete(TW, AUJ))
            with VD.sur_serveur(TH):
                rep.append(mod.poster_quete(TH, AUJ, mentionner=False))
            rep.append(mod.poster_quete(IG, AUJ))
            rep.append(commande(mod, "99"))
            TK.ticket_de = lambda gid, uid: ""
            rep.append(clic(mod, "99", f"quete:go:{AUJ}"))
            TK.ticket_de = sans
            rep.append(clic(mod, "99", f"quete:go:{AUJ}"))
            rep.append(clic(mod, "99", f"quete:go:{AUJ}"))
            rep.append(clic(mod, "88", f"quete:go:{HIER}"))
            rep.append(clic(mod, "77", f"quete:ok:99:{AUJ}"))
            rep.append(clic(mod, "10", f"quete:ok:99:{AUJ}", roles=[MGR], message="m3"))
            rep.append(clic(mod, "10", f"quete:no:88:{HIER}", roles=[MGR], message="ailleurs"))
            rep.append(clic(mod, "10", f"quete:ok:99:{AUJ}", roles=[MGR]))
            rep.append(clic(mod, "10", "quete:zz"))
            rep.append(clic(mod, "10", "quete:ok:1"))
            rep.append(commande(mod, "99"))
            rep.append(commande(mod, "88"))
            rep.append(mod.traiter({"type": 3, "data": {"custom_id": "quete:go:x"}}))
            rep.append(mod.traiter({"type": 3, "guild_id": TW, "member": {"user": {"id": "9"}},
                                    "data": {"custom_id": "verif:start"}}))
            rep.append(mod.traiter({"type": 2, "data": {"name": "autre"}}))
        return (json.dumps(rep, ensure_ascii=False, sort_keys=True),
                json.dumps(fd.appels, ensure_ascii=False, sort_keys=True),
                mod.ETAT_FICHIER.read_bytes(), jj.getvalue())

    def comparer(titre, a, b):
        check(f"{titre} : mêmes réponses à chaque clic et commande", a[0] == b[0],
              (a[0][:300], b[0][:300]))
        check(f"{titre} : mêmes appels à Discord, dans le même ordre, même serveur courant",
              a[1] == b[1], (a[1][:300], b[1][:300]))
        check(f"{titre} : même fichier d'état, à l'octet près", a[2] == b[2])
        check(f"{titre} : même journal", a[3] == b[3], (a[3], b[3]))

    try:
        nouveau = scenario(Q)
    finally:
        Q.time = __import__("time")
    check("… le scénario a bien posté, demandé et crédité",
          '"/channels/7001/messages"' in nouveau[1] and b'"etat": "ok"' in nouveau[2]
          and "Valider ma quête" in nouveau[1])
    check("… et, à False, rien de la pause ne tourne (ni trace, ni ligne de pause, ni journal)",
          b"pause_boutons" not in nouveau[2] and Q.PAUSE_LIGNE_MESSAGE not in nouveau[1]
          and Q.PAUSE_TEXTE not in nouveau[0] and "[quetes] pause" not in nouveau[3]
          and "[quetes] en pause" not in nouveau[3], nouveau[3])

    # 6a. Contre le module LUI-MÊME, pause ôtée. Comparer à un commit figé
    # cassait au premier changement légitime du module (un montant du
    # catalogue suffisait : trois échecs pour toujours) ; ici les deux côtés
    # viennent du même fichier, la preuve tient à chaque évolution.
    arbre_sp, n_gardes, n_verrous, lectures = sans_pause(src)
    check("version sans pause : gardes ôtées, l'interrupteur n'est plus lu nulle part",
          n_gardes >= 1 and not lectures,
          f"{n_gardes} garde(s), {n_verrous} verrou(s) déroulé(s), lu encore aux lignes {lectures}")
    try:
        SP = module_de("quetes_discord_sans_pause", arbre_sp)
    except Exception as e:                                   # noqa: BLE001
        SP = None
        check("version sans pause : le module se charge", False, f"{type(e).__name__}: {e}")
    if SP is not None:
        comparer("sans la pause", nouveau, scenario(SP))

    # 6b. Contre c5e9f59, la version d'avant la pause. Ce n'est une preuve
    # que tant que le module n'a pas changé ailleurs que dans la pause :
    # - hors de la pause, définition par définition, le code est celui de
    #   c5e9f59 (commentaires et docstrings mis à part) -> on compare ;
    # - la pause n'est pas encore commitée -> c'est elle qu'on vérifie, on
    #   compare quoi qu'il arrive (un écart de comportement est un échec) ;
    # - sinon le module a évolué depuis : comparaison sautée, et dite.
    AVANT = "c5e9f59"
    try:
        source = subprocess.run(["git", "show", f"{AVANT}:quetes_discord.py"], cwd=BOT,
                                capture_output=True, text=True, check=True, timeout=30).stdout
    except Exception as e:                                   # noqa: BLE001
        source = ""
        print(f"SAUTE la comparaison avec {AVANT} : git show impossible ({e})")
    if source:
        defs_sp = definitions(arbre_sp)
        ecarts = [k for k, v in definitions(ast.parse(source)).items() if defs_sp.get(k) != v]
        evolue = module_a_evolue_depuis(AVANT)
        if ecarts and evolue is not False:
            print(f"SAUTE la comparaison avec {AVANT} : quetes_discord.py a évolué depuis, hors de "
                  f"la pause ({', '.join(ecarts[:8])}"
                  + (" …" if len(ecarts) > 8 else "")
                  + ("" if evolue else " ; historique git illisible")
                  + ") — la comparaison avec la version sans pause (6a) en tient lieu")
        else:
            if ecarts:
                print(f"INFO pause pas encore commitée : hors de la pause, {', '.join(ecarts)} "
                      f"diffère de {AVANT} — comparé quand même")
            V = module_de("quetes_discord_avant", source)
            check(f"{AVANT} n'a pas d'interrupteur (bonne référence)",
                  not hasattr(V, "QUETES_EN_PAUSE") and "pause" not in source.lower())
            comparer(AVANT, nouveau, scenario(V))
finally:
    (Q.ETAT_FICHIER, Q.CATALOGUE_FICHIER, Q._api, Q.QUETES_EN_PAUSE,
     TK.ticket_de, TK.role_manager) = SAUVE
    Q._PAUSE_DITE.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f_ in FAILS:
    print("  - " + f_)
sys.exit(1 if FAILS else 0)
