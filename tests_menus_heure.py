# -*- coding: utf-8 -*-
"""tests_menus_heure.py — le menu ramené en bas des tickets, chaque heure.

Propriétaire, 25/10/2026 : « un truc qui renvoie le menu, toujours le menu
d'accueil, généré toutes les heures, et remove les autres ».

Ce qui est vérifié (tickets_discord.ramener_menus, _menage_ticket) :
  - menu déjà en bas : rien n'est posé ni épinglé (pas de bruit) ; relancé
    tout de suite, le tour n'écrit rien ;
  - conversation dessous : copie neuve en bas, épinglée, l'ancienne retirée,
    sans mention ;
  - le ménage retire les copies du menu que la fiche ne connaît pas et les
    avis « … a épinglé un message » de NOS bots ;
  - jamais touchés : l'accueil, la copie de la fiche, les messages des
    membres, la carte numéro, un avis posé par un humain, un message d'un
    autre bot, une copie de moins de 5 min (un clic en train de la poser) ;
  - VA parti : son ticket n'est pas lu ; fiche sans accueil : dite au bilan ;
    salon supprimé : rien reposé ;
  - les autres heures, les derniers messages seulement ; une fois par jour,
    tout le ticket (les avis du 22/10 sont loin au-dessus) ;
  - nos bots : Luigi, Bowser, Wario, Yoshi, Peach ;
  - un bilan court au journal à chaque tour ;
  - branché dans suivre_partout, une fois l'heure, en fond, sur Twitter,
    Threads et Agency.

Faux Discord, dossier temporaire : aucun appel réseau, rien dans data/.
Lancement : python tests_menus_heure.py
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import pathlib
import shutil
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import liens_va as lv                  # noqa: E402
import tickets_discord as tk           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


G = "1445108485090971710"
NOUS, AUTRE_BOT, HUMAIN = "1552153790701117480", "4242", "999"
_SEQ = [0]


def sf(age_s=0.0):
    """Un id Discord daté d'il y a `age_s` secondes (l'heure est dans l'id)."""
    _SEQ[0] += 1
    ms = int((time.time() - age_s) * 1000)
    return str(((ms - 1420070400000) << 22) + _SEQ[0])


RANGS = [{"type": 1, "components": [
    {"type": 2, "style": 2, "label": "Mon adresse USDC", "custom_id": "usdc:set:{u}"},
    {"type": 2, "style": 2, "label": "Numéro", "custom_id": "numx:menu"}]}]


class FauxDiscord:
    def __init__(self):
        self.salons = {}                 # salon -> {id: message}
        self.epingles = set()
        self.appels = []
        self.lectures = []

    def poser(self, salon, m):
        self.salons.setdefault(salon, {})[m["id"]] = m
        return m["id"]

    def fil(self, salon):
        return sorted(self.salons.get(salon, {}), key=int)

    def api(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw.get("json")))
        morceaux = chemin.split("?")[0].strip("/").split("/")
        salon = morceaux[1]
        if salon not in self.salons:
            return 404, {"message": "Unknown Channel", "code": 10003}
        ms = self.salons[salon]
        if methode == "GET" and "?" in chemin:
            q = dict(x.split("=") for x in chemin.split("?", 1)[1].split("&"))
            self.lectures.append((salon, q))
            ids = [i for i in reversed(self.fil(salon)) if "before" not in q or int(i) < int(q["before"])]
            return 200, [ms[i] for i in ids[:int(q["limit"])]]
        if methode == "GET":
            return (200, ms[morceaux[3]]) if morceaux[3] in ms else (404, {})
        if methode == "POST":
            mid = self.poser(salon, {"id": sf(), "type": 0, "author": {"id": NOUS, "bot": True},
                                     "content": kw["json"].get("content"),
                                     "components": kw["json"]["components"]})
            return 200, {"id": mid}
        if methode == "PUT" and "/pins/" in chemin:
            self.epingles.add(morceaux[3])
            self.poser(salon, {"id": sf(), "type": 6, "author": {"id": NOUS, "bot": True},
                               "message_reference": {"message_id": morceaux[3]}})
            return 204, {}
        if methode == "DELETE":
            self.epingles.discard(morceaux[3])
            return (204, {}) if ms.pop(morceaux[3], None) else (404, {})
        if methode == "PATCH":
            if morceaux[3] not in ms:
                return 404, {}
            ms[morceaux[3]].update(kw.get("json") or {})
            return 200, {}
        return 200, {}


def accueil(d, salon, u, age):
    return d.poser(salon, {"id": sf(age), "type": 0, "author": {"id": NOUS, "bot": True},
                           "embeds": [{"title": "Bienvenue"}],
                           "components": json.loads(json.dumps(RANGS).replace("{u}", u))})


def copie(d, salon, u, age, auteur=NOUS):
    return d.poser(salon, {"id": sf(age), "type": 0, "author": {"id": auteur, "bot": True},
                           "content": "📋 **Menu**",
                           "components": json.loads(json.dumps(RANGS).replace("{u}", u))})


def avis(d, salon, cible, age, auteur=NOUS, bot=True):
    return d.poser(salon, {"id": sf(age), "type": 6, "author": {"id": auteur, "bot": bot},
                           "message_reference": {"message_id": cible}})


def membre(d, salon, age, u="5"):
    return d.poser(salon, {"id": sf(age), "type": 0, "author": {"id": u}, "content": "salut"})


def carte(d, salon, age):
    # la carte numéro : composants v2, aucun texte
    return d.poser(salon, {"id": sf(age), "type": 0, "author": {"id": NOUS, "bot": True},
                           "content": "", "flags": 32768,
                           "components": [{"type": 17, "components": [{"type": 10, "content": "📱"}]}]})


TMP = pathlib.Path(tempfile.mkdtemp(prefix="menus_heure_"))
_SAUVE = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "_api_reseau", "_en_fond", "_nos_bots",
                                      "_PAS_TICKET_S", "_PAS_SUPPRESSION_S")}
_SAUVE_LV = lv.lien_de
try:
    J = 86400
    d = FauxDiscord()
    # U1 : menu en bas, la carte numéro dessous ; l'avis de l'accueil (22/10) traîne
    A1 = accueil(d, "S1", "U1", 3 * J)
    N1 = avis(d, "S1", A1, 3 * J - 1)
    H1 = membre(d, "S1", 2 * J)
    M1 = copie(d, "S1", "U1", J)
    K1 = carte(d, "S1", J - 5)
    # U2 : conversation sous le menu, une copie orpheline, un avis d'humain,
    # une copie d'un autre bot, une copie de nous toute jeune
    A2 = accueil(d, "S2", "U2", 3 * J)
    N2h = avis(d, "S2", A2, 3 * J - 1, auteur=HUMAIN, bot=False)
    O2 = copie(d, "S2", "U2", 2 * J)
    X2 = copie(d, "S2", "U2", 2 * J - 5, auteur=AUTRE_BOT)
    M2 = copie(d, "S2", "U2", J)
    H2 = membre(d, "S2", 3600)
    Y2 = copie(d, "S2", "U2", 30)
    # U3 parti, U4 sans accueil, U5 salon supprimé
    A3 = accueil(d, "S3", "U3", 3 * J)
    N3 = avis(d, "S3", A3, 3 * J - 1)
    # U6 : l'avis est loin au-dessus (130 messages), le menu en bas
    A6 = accueil(d, "S6", "U6", 4 * J)
    N6 = avis(d, "S6", A6, 4 * J - 1)
    for i in range(130):
        membre(d, "S6", 3 * J - i)
    M6 = copie(d, "S6", "U6", 1000)

    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{G}:U1": {"salon": "S1", "accueil": A1, "menu": M1, "menu_texte": "📋 **Menu**"},
        f"{G}:U2": {"salon": "S2", "accueil": A2, "menu": M2, "menu_texte": "📋 **Menu**"},
        f"{G}:U3": {"salon": "S3", "accueil": A3, "parti": True},
        f"{G}:U4": {"salon": "S4"},
        f"{G}:U5": {"salon": "S5", "accueil": "1"},
        f"{G}:U6": {"salon": "S6", "accueil": A6, "menu": M6, "menu_texte": "📋 **Menu**"},
        "1:U9": {"salon": "S9", "accueil": "2"}}}), encoding="utf-8")
    d.salons["S4"] = {}
    tk._api_reseau = d.api
    tk._en_fond = lambda f: f()
    tk._nos_bots = lambda: {NOUS}
    tk._PAS_TICKET_S = tk._PAS_SUPPRESSION_S = 0
    lv.lien_de = lambda gid, uid: {}

    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        b = tk.ramener_menus(G, profond=False)
    journal = sortie.getvalue()
    fiches = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))["tickets"]
    s1, s2 = d.salons["S1"], d.salons["S2"]

    check("menu déjà en bas (la carte numéro dessous) : rien posé, rien épinglé dans le ticket",
          not [a for a in d.appels if a[0] in ("POST", "PUT") and "/S1/" in a[1]]
          and fiches[f"{G}:U1"]["menu"] == M1, [a for a in d.appels if "/S1/" in a[1]])
    check("… l'avis d'épingle de notre bot sous l'accueil est retiré",
          N1 not in s1, d.fil("S1"))
    check("… l'accueil, le membre, la copie de la fiche et la carte numéro restent",
          all(x in s1 for x in (A1, H1, M1, K1)), d.fil("S1"))
    neuf = fiches[f"{G}:U2"]["menu"]
    check("conversation sous le menu : copie neuve en bas, épinglée, l'ancienne retirée",
          neuf not in (M2, "") and d.fil("S2")[-1] == neuf and neuf in d.epingles
          and M2 not in s2, d.fil("S2"))
    post = [a for a in d.appels if a[0] == "POST" and "/S2/" in a[1]]
    check("… une seule copie posée, sans mention, « 📋 Menu » et les boutons de l'accueil",
          len(post) == 1 and post[0][2]["allowed_mentions"] == {"parse": []}
          and post[0][2]["content"].startswith("📋 **Menu**")
          and post[0][2]["components"] == s2[A2]["components"], post)
    check("… l'avis de cette épingle-là ne reste pas",
          not [m for m in s2.values() if m.get("type") == 6
               and (m.get("message_reference") or {}).get("message_id") == neuf], d.fil("S2"))
    check("le ménage retire la copie orpheline (pas dans la fiche)", O2 not in s2, d.fil("S2"))
    check("… jamais : l'avis posé par un humain, la copie d'un autre bot, une copie de moins de 5 min",
          N2h in s2 and X2 in s2 and Y2 in s2, d.fil("S2"))
    check("… ni l'accueil, ni le message du membre", A2 in s2 and H2 in s2)
    check("VA parti : son ticket n'est pas lu, son avis reste",
          not [a for a in d.appels if "/S3/" in a[1]] and N3 in d.salons["S3"])
    check("fiche sans accueil : dite au bilan, pas de menu posé",
          b["sans_accueil"] == ["U4"] and not [a for a in d.appels if "/S4/" in a[1]], b)
    check("salon supprimé : rien reposé, compté en échec",
          any("U5" in x for x in b["echec"])
          and not [a for a in d.appels if a[0] == "POST" and "/S5/" in a[1]], b["echec"])
    check("un autre serveur : pas touché", not [a for a in d.appels if "/S9/" in a[1]])
    check("les autres heures, les derniers messages seulement : l'avis loin au-dessus reste",
          N6 in d.salons["S6"] and ("S6", {"limit": str(tk.MENAGE_DERNIERS)}) in d.lectures
          and not [q for s, q in d.lectures if s == "S6" and ("before" in q or q["limit"] == "100")],
          d.lectures[-3:])
    check("bilan du tour : 4 tickets, 1 ramené, 2 déjà en bas, 1 orpheline, 1 avis",
          (b["tickets"], b["ramene"], b["deja"], b["copies"], b["avis"]) == (4, 1, 2, 1, 1), b)
    check("… écrit au journal en une ligne",
          "menus de l'heure" in journal and "1 ramené(s) en bas" in journal
          and "2 déjà en bas" in journal and "sans accueil : ['U4']" in journal, journal)

    n = len(d.appels)
    with contextlib.redirect_stdout(io.StringIO()):
        b2 = tk.ramener_menus(G, profond=False)
    check("relancé tout de suite : rien n'est écrit (pas de bruit)",
          not [a for a in d.appels[n:] if a[0] in ("POST", "PUT", "DELETE", "PATCH")]
          and b2["ramene"] == 0, d.appels[n:])

    n = len(d.appels)
    with contextlib.redirect_stdout(io.StringIO()):
        b3 = tk.ramener_menus(G, profond=True)
    check("une fois par jour, tout le ticket : l'avis loin au-dessus est retiré (page suivante lue)",
          N6 not in d.salons["S6"] and b3["avis"] == 1
          and any("before" in q for s, q in d.lectures if s == "S6"), d.lectures[-4:])
    check("… et rien d'autre ne bouge", A6 in d.salons["S6"] and M6 in d.salons["S6"]
          and len(d.salons["S6"]) == 132 and not [a for a in d.appels[n:] if a[0] in ("POST", "PUT")])

    tk._PROFOND_VU.clear()
    vus = []
    _vrai_menage = tk._menage_ticket
    tk._menage_ticket = lambda gid, uid, salon, bots, profond=False: (
        vus.append(profond) or {"copies": 0, "avis": 0, "rates": 0, "absent": 0})
    with contextlib.redirect_stdout(io.StringIO()):
        tk.ramener_menus(G)
        tk.ramener_menus(G)
    tk._menage_ticket = _vrai_menage
    check("le premier tour du jour relit tout, les suivants non",
          vus[:4] == [True] * 4 and vus[4:] == [False] * 4, vus)

    tk._nos_bots = _SAUVE["_nos_bots"]
    check("nos bots : Luigi, Bowser, Wario, Yoshi, Peach",
          tk._nos_bots() >= {"1552153790701117480", "1552789379574145126", "1552785601051365516",
                             "1505416430840189041", "1509505792666108074"}, tk._nos_bots())
    check("une copie du menu se reconnaît (nos bots, « 📋 Menu », des boutons) ; pas la carte numéro",
          tk.est_copie_du_menu(s1[M1], {NOUS}) and not tk.est_copie_du_menu(s1[K1], {NOUS})
          and not tk.est_copie_du_menu(s1[A1], {NOUS})
          and not tk.est_copie_du_menu(s2[X2], {NOUS}))

    src = inspect.getsource(tk.suivre_partout)
    check("branché dans suivre_partout, une fois l'heure, en fond",
          "ramener_menus(g)" in src and "_en_fond(" in src and "MENUS_HEURE_S" in src
          and tk.MENUS_HEURE_S == 3600)
    check("sur Twitter, Threads et Agency",
          tk.MENUS_HEURE_ICI == {"1445108485090971710", "1498948161039896586", "1488331963575177247"})
finally:
    for k, v in _SAUVE.items():
        setattr(tk, k, v)
    lv.lien_de = _SAUVE_LV
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
