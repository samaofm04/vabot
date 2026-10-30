# -*- coding: utf-8 -*-
"""tests_outils_tickets.py — 📤 Spoofer et ⬇️ Download dans les tickets TRUST INSTAGRAM.

Propriétaire, 30/10/2026 : les outils des salons perso de Youl4b dans le
ticket du VA, un bouton par outil dans son menu, le résultat dans son ticket.

Ce qui est vérifié (outils_tickets, tickets_discord, cogs/telechargement) :
  - la rangée du VA d'Agency : 💳 · 📈 · 📤 Spoofer · ⬇️ Download · 📱 — cinq,
    jamais six ; Twitter et Threads : rien ne change ; BOUTONS_VERSION monte ;
  - le menu privé du staff porte les outils, et un clic hors ticket est refusé
    poliment en privé ; un autre VA est refusé ; le manager dans le ticket d'un
    VA y est servi ;
  - 📤 : la fenêtre (Label 18 + FileUpload 19, menu 1 à 5, 5 par défaut) ; la
    validation télécharge la pièce jointe, fabrique N versions SUR LA BOUCLE
    du bot principal SOUS le verrou _FILE de cogs/spoofer, les poste dans le
    ticket (multipart, jeton du bot), puis remet le menu en dernier ;
  - le vrai moteur photo de cogs/spoofer : N versions aux md5 différents ;
  - trop lourd (repartir ou 413) : compté et dit, jamais écarté en silence ;
  - un spoof à la fois par ticket ; format refusé ; boucle absente, ou
    sentinelle de discord.py avant le login de Yoshi ;
  - seule l'ATTENTE du verrou est bornée : file trop longue dite sans
    « ratée » ni verrou perdu ; une fabrication longue jamais annulée (verrou
    tenu jusqu'au bout, dossier rangé après sa fin réelle) ;
  - ticket supprimé : rien encodé après l'attente, livraison arrêtée au
    premier 404 (spoof comme téléchargement), verrous rendus ;
  - la rangée ne dépend pas d'outils_tickets (module absent : 📤 et ⬇️ quand
    même, BOUTONS_VERSION n'est pas consommé sur une rangée sans eux) ;
  - la limite lue au niveau de boost (10 / 50 / 100 Mio), en cache ;
  - ⬇️ : la fenêtre, les choix en privé, la livraison PAR
    Telechargement.livrer dans le ticket (même ordre, même format), la copie
    dans all-download de Youl4b, l'anti double-clic partagé — refusé DANS la
    réponse au clic, jamais par un suivi webhook —, le menu reposé ;
  - ramener_menu(en_dernier=True) : le menu redevient le dernier message, sans
    avis d'épingle ; deux appels simultanés n'en font qu'une copie ;
  - un travail coupé par un redémarrage est annoncé dans son ticket ; l'état
    non réécrit : rien annoncé (sinon à chaque déploiement), dit au journal ;
  - la route : tickets_discord et les quêtes laissent passer « outk: » ;
  - aucun texte ne dit « YouLab ».

Faux Discord, faux HikerAPI, dossier temporaire : aucun appel réseau, rien
dans data/. Lancement : python tests_outils_tickets.py
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                         # noqa: E402
import hiker_medias as hm              # noqa: E402
import outils_tickets as ot            # noqa: E402
import tickets_discord as tk           # noqa: E402
from cogs import spoofer as spf        # noqa: E402
from cogs import telechargement as tl  # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:600]}]" if detail and not cond else ""))


AG, TW, TH = tk.AGENCY_IG_ID, "1445108485090971710", "1498948161039896586"
VA, VA2, CHEF = "4001", "4002", "4999"
S, S2, ACC = "7001", "7002", "8001"
APP = "1552785601051365516"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="outils_tickets_"))
TEXTES = []                            # tout ce que le VA peut lire : jamais « YouLab »


def membre(uid, chef=False, nom="bob"):
    return {"user": {"id": uid, "username": nom}, "roles": ["R_MANAGER"] if chef else [],
            "permissions": "0"}


def clic(cid, uid=VA, salon=S, chef=False, gid=AG):
    return {"type": 3, "guild_id": gid, "channel_id": salon, "application_id": APP,
            "token": "jeton-" + cid, "member": membre(uid, chef), "data": {"custom_id": cid},
            "message": {"id": "m1", "flags": 0}}


def fenetre(cid, composants, resolved=None, uid=VA, salon=S, chef=False):
    p = clic(cid, uid, salon, chef)
    p["type"] = 5
    p["data"] = {"custom_id": cid, "components": composants, "resolved": resolved or {}}
    return p


def noter_textes(rep):
    TEXTES.append(json.dumps(rep, ensure_ascii=False))
    return rep


# ─── faux Discord (REST de Wario) ─────────────────────────────────────────
class FauxRest:
    def __init__(self):
        self.appels, self.messages, self.prives = [], [], []
        self.niveau = 0
        self.refus_413_au_dela = None       # octets : un fichier plus lourd -> 413
        self.n = 0
        self.verrou = threading.Lock()
        self.disparus = set()               # salons supprimés : GET et POST en 404 (10003)
        self.post_404 = set()               # salons dont seuls les POST sont en 404
        self.reste_avant_404 = {}           # salon -> POST encore acceptés, puis supprimé

    def api(self, methode, chemin, **kw):
        with self.verrou:
            self.appels.append((methode, chemin, kw.get("gid")))
            inconnu = (404, {"message": "Unknown Channel", "code": 10003})
            if methode == "GET" and chemin.startswith("/guilds/"):
                if self.niveau is None:
                    return 500, {"message": "panne"}
                return 200, {"id": chemin.rsplit("/", 1)[1], "premium_tier": self.niveau}
            if methode == "GET" and chemin.startswith("/channels/"):
                return inconnu if chemin.split("/")[2] in self.disparus else (200, {"id": "c"})
            if methode == "POST" and chemin.startswith("/webhooks/"):
                self.prives.append((chemin, kw.get("json")))
                TEXTES.append(json.dumps(kw.get("json"), ensure_ascii=False))
                return 200, {"id": "w"}
            if methode == "POST" and chemin.startswith("/channels/"):
                salon = chemin.split("/")[2]
                if salon in self.reste_avant_404:
                    if self.reste_avant_404[salon] <= 0:
                        self.disparus.add(salon)
                    self.reste_avant_404[salon] -= 1
                if salon in self.disparus or salon in self.post_404:
                    return inconnu
                if "json" in kw:
                    corps, fichiers = kw["json"], []
                else:
                    corps = json.loads(kw["data"]["payload_json"])
                    fichiers = [(nom, octets) for nom, octets, _t in kw["files"].values()]
                if (self.refus_413_au_dela is not None
                        and any(len(o) > self.refus_413_au_dela for _n, o in fichiers)):
                    return 413, {"message": "Request entity too large", "code": 40005}
                self.n += 1
                m = {"id": f"x{self.n}", "salon": salon, "content": corps.get("content", ""),
                     "fichiers": fichiers, "corps": corps}
                self.messages.append(m)
                TEXTES.append(m["content"])
                return 200, {"id": m["id"]}
            return 200, {}


# ─── faux bot principal : une vraie boucle asyncio dans son fil ───────────
class FausseArchive:
    name = "all-download"

    def __init__(self):
        self.envois = []

    async def send(self, content=None, files=None, allowed_mentions=None, **kw):
        self.envois.append({"content": content or "", "fichiers": [f.filename for f in (files or [])],
                            "am": allowed_mentions})


class FauxBot:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.fil = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.fil.start()
        self.cogs = {}
        self.archive = FausseArchive()
        self.youl4b = SimpleNamespace(id=tl.SERVEUR_ID, name="Youl4b", text_channels=[self.archive])

    def get_cog(self, nom):
        return self.cogs.get(nom)

    def get_guild(self, gid):
        return self.youl4b if int(gid) == tl.SERVEUR_ID else None


def attendre(cond, s=10.0):
    fin = time.time() + s
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "DATA_DIR", "role_manager", "role_helper",
                                         "ramener_menu",
                                         "_api_reseau")}
_SAUVE_OT = {k: getattr(ot, k) for k in ("_api", "_fond", "_dormir", "_bot_principal", "_telecharger",
                                         "ETAT", "LIMITES_BOOST", "FILE_MAX_S", "GARDE_FABRICATION_S",
                                         "RESERVATION_MAX_S", "_log")}
_SAUVE_SPF = {k: getattr(spf, k) for k in ("versions_photo", "versions_video", "_trop_longue")}
_SAUVE_HM = {k: getattr(hm, k) for k in ("profil", "profil_en_cache", "pp_locale", "pk_connu",
                                         "photo_de_profil", "publications", "reels", "top_reels",
                                         "preparer_post", "permalien", "budget")}
_SAUVE_TL = {"PAUSE_ENTRE_POSTS": tl.PAUSE_ENTRE_POSTS}
bot = None
try:
    # _ecrire_etat crée DATA_DIR : sans ça, un data/ vide apparaissait
    tk.DATA_DIR = TMP
    tk.ETAT_FICHIER = TMP / "tickets.json"
    tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
        f"{AG}:{VA}": {"salon": S, "accueil": ACC, "confirme": True},
        f"{AG}:{VA2}": {"salon": S2, "accueil": "8002", "confirme": True}}}), encoding="utf-8")
    tk.role_manager = lambda gid: "R_MANAGER"
    tk.role_helper = lambda gid: "R_HELPER"
    MENUS = []
    tk.ramener_menu = lambda gid, uid, salon, en_dernier=False: (
        MENUS.append((gid, uid, salon, en_dernier)), "ramene")[1]
    rest = FauxRest()
    ot._api = rest.api
    ot._fond = lambda f: f()
    ot._dormir = lambda s: None
    ot.ETAT = TMP / "outils_tickets.json"
    ot._LIMITES.clear()
    bot = FauxBot()
    # le cog Spoofer de Yoshi : son module porte LE verrou _FILE
    bot.cogs["Spoofer"] = spf.Spoofer(SimpleNamespace())
    ot._bot_principal = lambda: bot

    # ── 1. le menu ───────────────────────────────────────────────────────
    def ids(rangs):
        return [[b.get("custom_id") for b in r.get("components") or []] for r in rangs]

    for confirme, lien in ((False, True), (True, False), (True, True)):
        r = ids(tk.boutons_va(VA, confirme=confirme, a_un_lien=lien, gid=AG))
        check(f"Agency (confirmé={confirme}, lien={lien}) : rangée du VA = USDC, stats, 📤, ⬇️, "
              "Numéro — cinq, le Numéro reste le dernier",
              r[0] == [f"usdc:set:{VA}", f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}",
                       "numx:menu"] and all(len(x) <= 5 for x in r)
              and not [c for x in r[1:] for c in x if c.startswith("outk:")], r)
    b = {x["custom_id"]: x for x in ot.boutons(VA)}
    check("les deux boutons : « 📤 Spoofer » et « ⬇️ Download »",
          (b[f"outk:spf:{VA}"]["label"], b[f"outk:spf:{VA}"]["emoji"]) == ("Spoofer", {"name": "📤"})
          and (b[f"outk:dl:{VA}"]["label"], b[f"outk:dl:{VA}"]["emoji"]) == ("Download", {"name": "⬇️"}))
    check("un seul endroit décrit les boutons et leur préfixe (tickets_discord)",
          ot.boutons(VA) == tk.boutons_outils(VA) and ot.PREFIXE == tk.OUTILS_PREFIXE == "outk:")
    # Le module oublié d'un commit (ou cassé un instant) : la rangée ne doit pas
    # en dépendre — redessiner_boutons l'aurait marquée à jour (BOUTONS_VERSION)
    # sans 📤 ni ⬇️, et plus aucun accueil ne les aurait reçus.
    _mod_ot = sys.modules.get("outils_tickets")
    sys.modules["outils_tickets"] = None             # « import outils_tickets » lève
    try:
        r = ids(tk.boutons_va(VA, confirme=True, a_un_lien=True, gid=AG))
    except Exception as e:                           # noqa: BLE001
        r = [repr(e)]
    finally:
        sys.modules["outils_tickets"] = _mod_ot
    check("outils_tickets introuvable : la rangée du VA porte quand même 📤 et ⬇️ (rien de consommé)",
          r and r[0] == [f"usdc:set:{VA}", f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}",
                         "numx:menu"], r)
    pareils = True
    for gid in (TW, TH, "1"):
        for confirme, lien in ((False, True), (True, False), (False, False)):
            avec = tk.boutons_va(VA, confirme=confirme, a_un_lien=lien, gid=gid)
            sans = tk._boutons_va_sans_outils(VA, confirme=confirme, a_un_lien=lien, gid=gid)
            pareils = pareils and avec == sans and "outk:" not in json.dumps(avec)
    check("Twitter, Threads, autre serveur : la rangée ne change pas", pareils)
    check("BOUTONS_VERSION à 10 : les accueils et leurs copies sont redessinés",
          tk.BOUTONS_VERSION >= 10)
    mp = tk.menu_prive(AG, CHEF)
    cmp_ = [c for x in ids(mp["data"]["components"]) for c in x]
    check("menu privé du staff : les outils y sont, cinq par rangée au plus",
          f"outk:spf:{CHEF}" in cmp_ and f"outk:dl:{CHEF}" in cmp_
          and all(len(x["components"]) <= 5 for x in mp["data"]["components"]), mp)

    # ── 2. la route ──────────────────────────────────────────────────────
    import quetes_discord
    for p in (clic(f"outk:spf:{VA}"), fenetre(f"outk:spff:{VA}", [])):
        check(f"route : tickets_discord et les quêtes laissent passer « outk: » (type {p['type']})",
              tk.traiter(p) is None and quetes_discord.traiter(p) is None)
    check("traiter : None pour un clic qui n'est pas « outk: »",
          ot.traiter(clic("numx:menu")) is None and ot.traiter({"type": 1}) is None)
    src_wu = (BOT / "web_upload.py").read_text(encoding="utf-8")
    i_tk, i_ot = src_wu.find("_rep_tk = _tk.traiter(charge)"), src_wu.find("_rep_ot = _ot.traiter(charge)")
    i_vd = src_wu.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route : branché dans _discord_repondre, après les tickets, avant la vérification",
          0 < i_tk < i_ot < i_vd, (i_tk, i_ot, i_vd))
    check("démarrage : la reprise des travaux interrompus est branchée (hors banc d'essai)",
          "_ot_boot.demarrer()" in src_wu and '_machine_proprietaire("outils-tickets")' in src_wu)

    # ── 3. qui peut cliquer ──────────────────────────────────────────────
    r = noter_textes(ot.traiter(clic(f"outk:spf:{CHEF}", uid=CHEF, salon="9999", chef=True)))
    check("hors ticket (menu privé du staff) : refus poli, en privé",
          r["type"] == 4 and r["data"]["flags"] == 64 and r["data"]["content"] == ot.TEXTE_HORS_TICKET, r)
    r = noter_textes(ot.traiter(clic(f"outk:dl:{VA}", uid=VA2, salon=S)))
    check("un autre VA dans ce ticket : refusé, en privé",
          r["type"] == 4 and r["data"]["flags"] == 64 and r["data"]["content"] == ot.TEXTE_PAS_A_TOI, r)
    r = noter_textes(ot.traiter(clic(f"outk:spf:{VA}", gid=TW)))
    check("un autre serveur : refusé", r["type"] == 4 and r["data"]["flags"] == 64, r)

    # ── 4. 📤 la fenêtre ─────────────────────────────────────────────────
    r = noter_textes(ot.traiter(clic(f"outk:spf:{VA}")))
    comp = (r.get("data") or {}).get("components") or []
    sel = (comp[1].get("component") or {}) if len(comp) > 1 else {}
    check("📤 : la fenêtre s'ouvre tout de suite (type 9), titre « Spoofer »",
          r["type"] == 9 and r["data"]["title"] == "Spoofer"
          and r["data"]["custom_id"] == f"outk:spff:{VA}", r)
    check("… un Label (18) qui porte le champ fichier (19), un seul fichier",
          comp and comp[0]["type"] == 18 and comp[0]["component"]["type"] == 19
          and comp[0]["component"]["max_values"] == 1 and comp[0]["component"]["min_values"] == 1, comp)
    check("… et un Label avec le menu 1 à 5, 5 par défaut",
          len(comp) == 2 and comp[1]["type"] == 18 and sel.get("type") == 3
          and [o["value"] for o in sel.get("options") or []] == ["1", "2", "3", "4", "5"]
          and [o["value"] for o in sel["options"] if o.get("default")] == ["5"], comp)
    r = noter_textes(ot.traiter(clic(f"outk:spf:{VA}", uid=CHEF, chef=True)))
    check("le manager dans le ticket du VA : la fenêtre, pour le VA du ticket",
          r["type"] == 9 and r["data"]["custom_id"] == f"outk:spff:{VA}", r)

    # ── 5. 📤 la validation : faux moteur, sur la boucle, sous le verrou ──
    SOURCE = TMP / "source.jpg"
    SOURCE.write_bytes(b"\xff\xd8\xff" + b"photo" * 400)
    TELECHARGES = []

    def faux_telecharger(url, dest, plafond):
        TELECHARGES.append((url, plafond))
        shutil.copy(SOURCE, dest)
        return ""
    ot._telecharger = faux_telecharger
    FAB = {"fil": None, "verrou": None, "tailles": None}

    async def fausses_photos(src, dossier, q):
        FAB["fil"] = threading.current_thread()
        FAB["verrou"] = spf._FILE.locked()
        sorties = []
        for i in range(q):
            t = (FAB["tailles"] or {}).get(i, 2000)
            p = pathlib.Path(dossier) / f"IMG_{1000 + i}.JPG"
            p.write_bytes(os.urandom(t))
            sorties.append(p)
        return sorties, 0
    spf.versions_photo = fausses_photos

    def soumettre_spoof(nom="photo.jpg", q="3", taille=2000, uid=VA, chef=False, salon=S):
        return ot.traiter(fenetre(f"outk:spff:{VA}", [
            {"type": 18, "id": 1, "component": {"type": 19, "id": 2, "custom_id": "fichier",
                                                "values": ["555"]}},
            {"type": 18, "id": 3, "component": {"type": 3, "id": 4, "custom_id": "nombre",
                                                "values": [q]}}],
            {"attachments": {"555": {"id": "555", "filename": nom, "size": taille,
                                     "url": "https://cdn.discordapp.com/ephemeral/555/" + nom}}},
            uid=uid, chef=chef, salon=salon))

    n0 = len(rest.messages)
    r = soumettre_spoof()
    neufs = rest.messages[n0:]
    check("validation : accusé silencieux (type 6), rien d'éphémère", r == {"type": 6}, r)
    check("… la pièce jointe est téléchargée tout de suite, à son adresse",
          TELECHARGES and TELECHARGES[-1][0].endswith("/555/photo.jpg"), TELECHARGES)
    check("… fabriquée sur la boucle du bot principal, sous le verrou _FILE de cogs/spoofer",
          FAB["fil"] is bot.fil and FAB["verrou"] is True, FAB)
    check("… 3 versions postées dans le ticket, en UN message (multipart), sans texte",
          len(neufs) == 1 and neufs[0]["salon"] == S and len(neufs[0]["fichiers"]) == 3
          and not neufs[0]["content"]
          and [a["filename"] for a in neufs[0]["corps"]["attachments"]]
          == [n for n, _o in neufs[0]["fichiers"]], neufs)
    check("… avec le jeton de Wario (le serveur du ticket), sans mention",
          all(g == AG for m_, c_, g in rest.appels if m_ == "POST" and c_.startswith("/channels/"))
          and neufs[0]["corps"]["allowed_mentions"] == {"parse": []})
    check("… puis le menu redevient le dernier message du ticket (en_dernier)",
          MENUS and MENUS[-1] == (AG, VA, S, True), MENUS)
    check("… plus rien en cours : ni verrou de ticket, ni marque sur le disque",
          S not in ot._SPOOFS and not ot._lire_etat()["en_cours"])
    check("limite lue au niveau de boost (une lecture GET /guilds)",
          [c for m_, c, _g in rest.appels if m_ == "GET" and c.startswith("/guilds/")] == [f"/guilds/{AG}"],
          rest.appels)
    check("… et le ticket relu une fois le verrou pris (supprimé pendant l'attente : rien à encoder)",
          (("GET", f"/channels/{S}", AG) in rest.appels), rest.appels)

    MENUS.clear()
    n0 = len(rest.messages)
    r = soumettre_spoof(uid=CHEF, chef=True)
    check("le manager valide dans le ticket du VA : livré dans CE ticket",
          r == {"type": 6} and rest.messages[n0:] and all(m["salon"] == S for m in rest.messages[n0:])
          and MENUS[-1] == (AG, VA, S, True), (r, rest.messages[n0:]))
    r = noter_textes(soumettre_spoof(uid=VA2))
    check("un autre VA qui valide une fenêtre dans ce ticket : refusé",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_PAS_A_TOI, r)

    # trop lourd : repartir l'écarte, et c'est DIT
    ot.LIMITES_BOOST = {0: 1024 * 1024, 1: 1024 * 1024, 2: 50 * 1024 * 1024, 3: 100 * 1024 * 1024}
    ot._LIMITES.clear()
    FAB["tailles"] = {1: 900 * 1024}
    n0 = len(rest.messages)
    soumettre_spoof(q="3")
    neufs = rest.messages[n0:]
    check("une version au-delà de la limite du serveur : 2 envoyées, 1 trop lourde, DIT dans le ticket",
          len(neufs) == 2 and len(neufs[0]["fichiers"]) == 2
          and neufs[1]["content"] == "🎭 photo.jpg : 2/3 — 1 trop lourde(s) pour Discord", neufs)
    # Discord refuse quand même (413) : compté comme trop lourd
    FAB["tailles"] = None
    rest.refus_413_au_dela = 1000
    n0 = len(rest.messages)
    soumettre_spoof(q="2")
    neufs = rest.messages[n0:]
    rest.refus_413_au_dela = None
    check("413 malgré le calcul : compté et dit, rien d'écarté en silence",
          len(neufs) == 1 and neufs[0]["content"] == "🎭 photo.jpg : 0/2 — 2 trop lourde(s) pour Discord",
          neufs)
    ot.LIMITES_BOOST = _SAUVE_OT["LIMITES_BOOST"]

    # un spoof à la fois par ticket
    ot._SPOOFS.add(S)
    r1 = noter_textes(ot.traiter(clic(f"outk:spf:{VA}")))
    r2 = noter_textes(soumettre_spoof())
    ot._SPOOFS.discard(S)
    check("un spoof en cours dans ce ticket : le bouton et la fenêtre le disent, rien n'est lancé",
          r1["type"] == 4 and r1["data"]["content"] == ot.TEXTE_SPOOF_EN_COURS
          and r2["type"] == 4 and r2["data"]["content"] == ot.TEXTE_SPOOF_EN_COURS, (r1, r2))
    r = noter_textes(soumettre_spoof(nom="notes.txt"))
    check("format refusé, en privé, avant tout téléchargement",
          r["type"] == 4 and "format non pris" in r["data"]["content"], r)
    r = noter_textes(soumettre_spoof(taille=spf.TAILLE_MAX + 1))
    check("source au-delà de 200 Mo : refusée et dite", r["type"] == 4 and "trop lourd" in r["data"]["content"], r)
    r = noter_textes(ot.traiter(fenetre(f"outk:spff:{VA}", [], {})))
    check("fenêtre sans fichier : dit", r["type"] == 4 and "Aucun fichier" in r["data"]["content"], r)
    ot._bot_principal = lambda: None
    r = noter_textes(soumettre_spoof())
    ot._bot_principal = lambda: bot
    check("bot principal indisponible : dit, rien lancé (jamais hors du verrou de Yoshi)",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_INDISPONIBLE and S not in ot._SPOOFS, r)
    # Avant le login de Yoshi, discord.py met dans Client.loop une sentinelle
    # dont tout attribut lève (MISSING après sa fermeture) ; main.py lance le
    # site AVANT le bot.
    reps = []
    for sentinelle in (discord.client._loop, discord.utils.MISSING):
        faux = SimpleNamespace(loop=sentinelle, get_cog=bot.get_cog)
        ot._bot_principal = lambda faux=faux: faux
        for f_ in (lambda: soumettre_spoof(), lambda: ot.traiter(clic("outk:dlo:tout:5:sky.ards"))):
            try:
                reps.append(noter_textes(f_()))
            except Exception as e:                   # noqa: BLE001
                reps.append(repr(e))
    ot._bot_principal = lambda: bot
    check("Yoshi pas encore connecté (boucle sentinelle de discord.py) : « Indisponible », sans exception",
          len(reps) == 4 and all(isinstance(x, dict) and x["type"] == 4
                                 and x["data"]["content"] == ot.TEXTE_INDISPONIBLE for x in reps)
          and S not in ot._SPOOFS and not ot._lire_etat()["en_cours"], reps)
    check("le moteur est le module du cog Spoofer CHARGÉ (son verrou _FILE, pas une copie)",
          ot._moteur(bot) is spf and ot._moteur(bot)._FILE is spf._FILE)
    _cog_spf = bot.cogs.pop("Spoofer")
    r = noter_textes(soumettre_spoof())
    bot.cogs["Spoofer"] = _cog_spf
    check("cog Spoofer pas encore chargé (démarrage) : dit, rien lancé",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_INDISPONIBLE and S not in ot._SPOOFS
          and not ot._lire_etat()["en_cours"], r)

    # vidéo trop longue : refusée avant le verrou, dite dans le ticket
    async def trop_longue(src, plafond):
        return True
    spf._trop_longue = trop_longue
    ot.LIMITES_BOOST = {0: 1024 * 1024, 1: 1024 * 1024, 2: 1024 * 1024, 3: 1024 * 1024}
    ot._LIMITES.clear()
    SOURCE.write_bytes(b"\x00" * (2 * 1024 * 1024))
    n0 = len(rest.messages)
    MENUS.clear()
    soumettre_spoof(nom="clip.mov", taille=2 * 1024 * 1024)
    neufs = rest.messages[n0:]
    check("vidéo trop longue pour tenir : dite dans le ticket, le menu reposé",
          len(neufs) == 1 and "trop longue" in neufs[0]["content"] and MENUS, neufs)
    spf._trop_longue = _SAUVE_SPF["_trop_longue"]
    ot.LIMITES_BOOST = _SAUVE_OT["LIMITES_BOOST"]
    ot._LIMITES.clear()

    # la file : seule l'ATTENTE du verrou est bornée, jamais la fabrication
    def sur_la_boucle(coro):
        return asyncio.run_coroutine_threadsafe(coro, bot.loop).result(5)

    ot.FILE_MAX_S = 0.3
    sur_la_boucle(spf._FILE.acquire())               # un spoof de Youl4b tient le verrou
    FAB["fil"] = None
    MENUS.clear()
    n0 = len(rest.messages)
    soumettre_spoof(q="3")
    neufs = rest.messages[n0:]
    bot.loop.call_soon_threadsafe(spf._FILE.release)
    attendre(lambda: not spf._FILE.locked())
    check("verrou tenu au-delà de l'attente permise : « trop de spoofs en attente », rien fabriqué, "
          "aucune « ratée », le menu reposé",
          len(neufs) == 1
          and neufs[0]["content"] == "⏳ photo.jpg : trop de spoofs en attente, renvoie-le plus tard."
          and FAB["fil"] is None and MENUS and S not in ot._SPOOFS, neufs)
    check("… et le verrou n'est pas perdu : libre et entier une fois rendu par son détenteur",
          not spf._FILE.locked() and spf._FILE._value == 1, spf._FILE)

    async def photos_lentes(src, dossier, q):
        FAB["dossier"] = pathlib.Path(dossier)
        await asyncio.to_thread(time.sleep, 0.8)     # l'encodage, dans son fil
        FAB["verrou_fin"] = spf._FILE.locked()
        sorties, ratees = await fausses_photos(src, dossier, q)   # écrit DANS le dossier
        FAB["ecrit"] = True
        return sorties, ratees
    spf.versions_photo = photos_lentes
    ot.FILE_MAX_S = 0.2
    FAB.update(verrou_fin=None, ecrit=False, dossier=None)
    n0 = len(rest.messages)
    soumettre_spoof(q="3")
    neufs = rest.messages[n0:]
    check("fabrication plus longue que l'attente permise, verrou pris : menée à son terme, jamais "
          "annulée — 3 versions livrées, verrou tenu jusqu'au bout, dossier rangé après",
          len(neufs) == 1 and len(neufs[0]["fichiers"]) == 3 and FAB["verrou_fin"] is True
          and FAB["ecrit"] and not spf._FILE.locked() and not FAB["dossier"].exists(), neufs)
    # au-delà de la garde, le site cesse d'attendre SANS annuler : le verrou
    # reste tenu par l'encodage, le dossier vit jusqu'à sa fin réelle
    ot.FILE_MAX_S, ot.GARDE_FABRICATION_S = 0.1, 0.2
    FAB.update(verrou_fin=None, ecrit=False, dossier=None)
    n0 = len(rest.messages)
    soumettre_spoof(q="3")
    neufs = rest.messages[n0:]
    encore_la = FAB["dossier"] is not None and FAB["dossier"].exists()
    tenu = spf._FILE.locked()
    fini = attendre(lambda: FAB["ecrit"] and not spf._FILE.locked() and not FAB["dossier"].exists())
    check("garde dépassée : « bloqué » dit dans le ticket, sans rien annuler (verrou encore tenu, "
          "dossier encore là), puis l'encodage finit et le dossier part",
          len(neufs) == 1 and neufs[0]["content"] == "🎭 photo.jpg : bloqué, renvoie-le plus tard."
          and encore_la and tenu and fini and FAB["verrou_fin"] is True and S not in ot._SPOOFS,
          (neufs, encore_la, tenu, fini))
    ot.FILE_MAX_S = _SAUVE_OT["FILE_MAX_S"]
    ot.GARDE_FABRICATION_S = _SAUVE_OT["GARDE_FABRICATION_S"]
    spf.versions_photo = fausses_photos

    # le ticket supprimé : pendant l'attente du verrou, puis pendant la livraison
    rest.disparus.add(S)
    FAB["fil"] = None
    MENUS.clear()
    n0, a0 = len(rest.messages), len(rest.appels)
    soumettre_spoof(q="3")
    posts = [c for m_, c, _g in rest.appels[a0:] if m_ == "POST"]
    rest.disparus.discard(S)
    check("ticket supprimé pendant l'attente : rien encodé sous le verrou de tous, rien posté, menu non "
          "reposé, plus rien en cours",
          FAB["fil"] is None and not posts and not MENUS and S not in ot._SPOOFS
          and not ot._lire_etat()["en_cours"], (FAB["fil"], posts, MENUS))
    ot.LIMITES_BOOST = {0: 1024 * 1024, 1: 1024 * 1024, 2: 1024 * 1024, 3: 1024 * 1024}
    ot._LIMITES.clear()
    FAB["tailles"] = {0: 500 * 1024, 1: 500 * 1024, 2: 500 * 1024}   # un lot par version
    rest.post_404.add(S)
    n0, a0 = len(rest.messages), len(rest.appels)
    soumettre_spoof(q="3")
    posts = [c for m_, c, _g in rest.appels[a0:] if m_ == "POST"]
    rest.post_404.discard(S)
    FAB["tailles"] = None
    ot.LIMITES_BOOST = _SAUVE_OT["LIMITES_BOOST"]
    ot._LIMITES.clear()
    check("ticket supprimé pendant la livraison : arrêt au premier 404 (1 envoi tenté sur 3 lots), pas de "
          "bilan, menu non reposé",
          posts == [f"/channels/{S}/messages"] and not MENUS and S not in ot._SPOOFS, (posts, MENUS))

    # ── 6. le VRAI moteur photo de cogs/spoofer (métadonnées US, md5) ────
    spf.versions_photo = _SAUVE_SPF["versions_photo"]
    try:
        import image_transform as it
        from PIL import Image
        _cfg_sauve = it.CONFIG_FILE
        it.CONFIG_FILE = TMP / "image_transform.json"
        img = Image.new("RGB", (64, 48), (200, 120, 40))
        img.save(SOURCE, "JPEG", quality=90)
        n0 = len(rest.messages)
        soumettre_spoof(q="3")
        neufs = rest.messages[n0:]
        md5s = {hashlib.md5(o).hexdigest() for m in neufs for _n, o in m["fichiers"]}
        check("vrai moteur photo : 3 versions JPG, toutes différentes (md5) de la source et entre elles",
              len(neufs) == 1 and len(neufs[0]["fichiers"]) == 3 and len(md5s) == 3
              and hashlib.md5(SOURCE.read_bytes()).hexdigest() not in md5s
              and all(n.endswith(".JPG") for n, _o in neufs[0]["fichiers"]), neufs)
        it.CONFIG_FILE = _cfg_sauve
    except ImportError as e:
        check("vrai moteur photo : testable", False, repr(e))

    # ── 7. la limite au niveau de boost ──────────────────────────────────
    for niveau, mio in ((0, 10), (1, 10), (2, 50), (3, 100)):
        ot._LIMITES.clear()
        rest.niveau = niveau
        check(f"boost niveau {niveau} : {mio} Mio par fichier", ot.limite_fichiers(AG) == mio * 1024 * 1024)
    n = len(rest.appels)
    ot.limite_fichiers(AG)
    check("… gardée en cache (aucune lecture de plus)", len(rest.appels) == n)
    ot._LIMITES.clear()
    rest.niveau = None
    check("illisible : 10 Mio, le plus petit", ot.limite_fichiers(AG) == 10 * 1024 * 1024)
    rest.niveau = 0
    ot._LIMITES.clear()

    # ── 8. ⬇️ la fenêtre, puis les choix en privé ────────────────────────
    r = noter_textes(ot.traiter(clic(f"outk:dl:{VA}")))
    comp = (r.get("data") or {}).get("components") or []
    check("⬇️ : la fenêtre du compte (pseudo, combien 30 par défaut)",
          r["type"] == 9 and r["data"]["custom_id"] == f"outk:dlf:{VA}"
          and [c["component"]["custom_id"] for c in comp] == ["pseudo", "combien"]
          and all(c["type"] == 18 and c["component"]["type"] == 4 for c in comp)
          and comp[1]["component"]["placeholder"] == "30", r)

    def soumettre_compte(pseudo, combien="5", uid=VA, chef=False):
        return ot.traiter(fenetre(f"outk:dlf:{VA}", [
            {"type": 18, "component": {"type": 4, "custom_id": "pseudo", "value": pseudo}},
            {"type": 18, "component": {"type": 4, "custom_id": "combien", "value": combien}}],
            uid=uid, chef=chef))
    r = noter_textes(soumettre_compte("https://www.instagram.com/Sky.Ards/"))
    choix = [c for x in r["data"].get("components") or [] for c in x["components"]]
    check("validée : les choix en PRIVÉ (Tout · Photo de profil · Bio / Posts photo · Reels · Top reels)",
          r["type"] == 4 and r["data"]["flags"] == 64 and r["data"]["content"] == "⬇️ **@sky.ards** · 5"
          and [c["label"] for c in choix] == ["Tout", "Photo de profil", "Bio", "Posts photo", "Reels",
                                              "Top reels"]
          and [len(x["components"]) for x in r["data"]["components"]] == [3, 3]
          and choix[0]["custom_id"] == "outk:dlo:tout:5:sky.ards", r)
    r = noter_textes(soumettre_compte("#pas un pseudo"))
    check("pseudo invalide : refusé, comme sur Youl4b", r["type"] == 4 and "pseudo" in r["data"]["content"], r)
    r = noter_textes(soumettre_compte("sky.ards", "999"))
    check("combien borné à 200", "· 200" in r["data"]["content"], r)
    check("lire_compte : la même lecture que la fenêtre de Youl4b",
          tl.lire_compte("@Sky.Ards?igsh=x", "") == ("sky.ards", 30, "")
          and tl.lire_compte("", "")[2] == "Pseudo invalide.")

    # ── 9. ⬇️ la livraison : Telechargement.livrer, tel quel ─────────────
    tl.PAUSE_ENTRE_POSTS = 0
    MEDIAS = TMP / "medias"
    MEDIAS.mkdir()
    (MEDIAS / "pp.jpg").write_bytes(b"p" * 3000)
    (MEDIAS / "C1_1.jpg").write_bytes(b"c" * 4000)
    (MEDIAS / "V1.mp4").write_bytes(b"v" * 5000)
    HM = {"requetes": 0}

    def compter(cpt):
        if cpt is not None:
            cpt.requetes += 1
            HM["requetes"] += 1
    hm.pp_locale = lambda u: None
    hm.pk_connu = lambda u: "123"
    hm.profil_en_cache = lambda u: None

    def faux_profil(u, cpt=None, *a, **k):
        compter(cpt)
        return {"nom": "Sky", "posts": 2, "abonnes": 10, "bio": "Ma bio", "prive": False}
    hm.profil = faux_profil
    hm.photo_de_profil = lambda u, fiche, cpt: (MEDIAS / "pp.jpg", "")
    POSTS = [{"code": "C1", "genre": "photo", "date": 1761800000, "legende": "légende photo"},
             {"code": "V1", "genre": "video", "date": 1761800000, "legende": "légende reel"}]

    def fausses_publications(u, combien, cpt=None, photos_seules=False):
        compter(cpt)
        return ([p for p in POSTS if p["genre"] != "video"] if photos_seules else list(POSTS)), ""
    hm.publications = fausses_publications
    hm.reels = lambda u, combien, cpt=None: ([POSTS[1]], "")
    hm.top_reels = lambda u, combien, cpt=None: ([dict(POSTS[1], vues=1234)], "", "vues")
    hm.preparer_post = lambda post, cpt, u: [{"i": 1, "chemin": MEDIAS / ("%s%s" % (
        post["code"], "_1.jpg" if post["genre"] == "photo" else ".mp4")), "erreur": ""}]
    hm.permalien = lambda code: f"https://www.instagram.com/p/{code}/"
    hm.budget = lambda: {"utilise": 7, "plafond": 300}

    cog = tl.Telechargement(SimpleNamespace())
    bot.cogs["Telechargement"] = cog
    MENUS.clear()
    n0 = len(rest.messages)
    r = ot.traiter(clic("outk:dlo:tout:5:sky.ards"))
    check("un choix : accusé silencieux (type 6), les choix restent", r == {"type": 6}, r)
    fini = attendre(lambda: MENUS and not cog._en_cours_va)
    neufs = rest.messages[n0:]
    textes = [m["content"] for m in neufs]
    check("… livré dans le TICKET, rien en éphémère", fini and neufs and all(m["salon"] == S for m in neufs)
          and not rest.prives, (fini, neufs[:3], rest.prives))
    attendu = ["**@sky.ards** - Sky - 2 posts, 10 abonnes", "Photo de profil", "Bio :", "Ma bio",
               "1 publication(s) photo, 1 reel(s). Envoi au fil de l'eau.", "--- POSTS PHOTO (1) ---"]
    check("… dans l'ordre et le format de Youl4b : en-tête, photo de profil, bio, posts photo, reels, bilan",
          textes[:6] == attendu and textes[6].startswith("#1 - ") and textes[6].endswith("légende photo")
          and textes[7] == "--- REELS (1) ---" and textes[8].endswith("légende reel")
          and textes[9].startswith("Termine pour @sky.ards — ") and "reserve du jour 7/300" in textes[9],
          textes)
    check("… les fichiers avec leur publication (un message par publication)",
          [n for n, _o in neufs[1]["fichiers"]] == ["pp.jpg"]
          and [n for n, _o in neufs[6]["fichiers"]] == ["C1_1.jpg"]
          and [n for n, _o in neufs[8]["fichiers"]] == ["V1.mp4"], [(m["content"][:20], m["fichiers"] and
                                                                      [n for n, _o in m["fichiers"]])
                                                                     for m in neufs])
    arch = bot.archive.envois
    check("… une copie dans all-download de Youl4b, qui dit d'où elle vient, sans notifier",
          arch and all(e["content"].startswith(f"📥 <@{VA}> · @sky.ards · Tout · TRUST INSTAGRAM · ")
                       for e in arch)
          and any(e["fichiers"] == ["V1.mp4"] for e in arch)
          and all(e["am"] is not None and e["am"].users is False for e in arch), arch[:3])
    check("… puis le menu redevient le dernier message du ticket", MENUS[-1] == (AG, VA, S, True), MENUS)

    # le manager, dans le ticket du VA : livré là, réservé au nom du VA du ticket
    MENUS.clear()
    bot.archive.envois.clear()
    n0 = len(rest.messages)
    ot.traiter(clic("outk:dlo:bio:5:sky.ards", uid=CHEF, chef=True))
    attendre(lambda: MENUS and not cog._en_cours_va)
    neufs = rest.messages[n0:]
    check("le manager dans le ticket du VA : la bio livrée dans CE ticket",
          neufs and all(m["salon"] == S for m in neufs) and "Ma bio" in [m["content"] for m in neufs]
          and bot.archive.envois[0]["content"].startswith(f"📥 <@{CHEF}> · @sky.ards · Bio"), neufs)

    # anti double-clic : le verrou du cog de Youl4b, partagé — et le refus est
    # LA réponse au clic : un suivi par webhook partait parfois avant que
    # Discord ait reçu l'accusé, qui le rejetait (le VA ne voyait rien)
    cog.reserver(int(VA), "autre.compte")
    n0, p0 = len(rest.messages), len(rest.prives)
    r = noter_textes(ot.traiter(clic("outk:dlo:reels:5:sky.ards")))
    time.sleep(0.2)
    cog.liberer(int(VA), "autre.compte")
    check("un téléchargement déjà en cours pour ce VA : refusé DANS la réponse au clic (éphémère), "
          "aucun suivi par webhook, rien livré",
          r["type"] == 4 and r["data"]["flags"] == 64 and "pas fini" in r["data"]["content"]
          and len(rest.prives) == p0 and len(rest.messages) == n0, (r, rest.prives[p0:]))
    # deux clics en rafale sur l'éphémère des choix
    porte = threading.Event()

    def profil_lent(u, cpt=None, *a, **k):
        porte.wait(5)
        return faux_profil(u, cpt)
    hm.profil = profil_lent
    MENUS.clear()
    r1 = ot.traiter(clic("outk:dlo:bio:5:sky.ards"))
    r2 = noter_textes(ot.traiter(clic("outk:dlo:tout:5:sky.ards")))
    porte.set()
    attendre(lambda: MENUS and not cog._en_cours_va)
    hm.profil = faux_profil
    check("deux clics en rafale : le premier part (type 6), le second refusé dans sa réponse, sans webhook",
          r1 == {"type": 6} and r2["type"] == 4 and r2["data"]["flags"] == 64
          and "pas fini" in r2["data"]["content"] and len(rest.prives) == p0, (r1, r2))
    # la boucle de Yoshi trop lente pour réserver dans le temps du clic
    ot.RESERVATION_MAX_S = 0.2
    bot.loop.call_soon_threadsafe(time.sleep, 0.8)
    n0 = len(rest.messages)
    r = noter_textes(ot.traiter(clic("outk:dlo:tout:5:sky.ards")))
    time.sleep(1.0)
    ot.RESERVATION_MAX_S = _SAUVE_OT["RESERVATION_MAX_S"]
    check("boucle de Yoshi trop lente : « Indisponible » tout de suite, et la réservation tardive n'est "
          "pas prise (le VA peut relancer)",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_INDISPONIBLE
          and not cog._en_cours_va and not cog._en_cours_pseudo and len(rest.messages) == n0,
          (r, cog._en_cours_va))
    r = noter_textes(ot.traiter(clic("outk:dlo:tout:5:sky.ards", uid=VA2)))
    check("un autre VA clique un choix dans ce ticket : refusé",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_PAS_A_TOI, r)

    # trop lourd pour le serveur : DIT, la livraison continue
    ot.LIMITES_BOOST = {0: 1024 * 1024, 1: 1024 * 1024, 2: 1024 * 1024, 3: 1024 * 1024}
    ot._LIMITES.clear()
    (MEDIAS / "V1.mp4").write_bytes(b"v" * (2 * 1024 * 1024))
    MENUS.clear()
    n0 = len(rest.messages)
    ot.traiter(clic("outk:dlo:reels:5:sky.ards"))
    attendre(lambda: MENUS and not cog._en_cours_va)
    textes = [m["content"] for m in rest.messages[n0:]]
    check("un reel au-delà de la limite du serveur : la taille et le lien, compté au bilan",
          any("V1.mp4 : 2.0 Mo, au-dela de la limite de 1 Mo de ce serveur" in t for t in textes)
          and any(t.startswith("Termine pour @sky.ards") and "1 trop lourd(s), donne(s) en lien" in t
                  for t in textes), textes)
    ot.LIMITES_BOOST = _SAUVE_OT["LIMITES_BOOST"]
    ot._LIMITES.clear()
    (MEDIAS / "V1.mp4").write_bytes(b"v" * 5000)

    # le ticket supprimé pendant un « Tout » de dix publications
    POSTS[:] = [{"code": f"C{i}", "genre": "photo", "date": 1761800000, "legende": f"légende {i}"}
                for i in range(1, 11)]
    for i in range(1, 11):
        (MEDIAS / f"C{i}_1.jpg").write_bytes(b"c" * 4000)
    PREPARES = []
    _prep = hm.preparer_post

    def preparer_compte(post, cpt, u):
        PREPARES.append(post["code"])
        return _prep(post, cpt, u)
    hm.preparer_post = preparer_compte
    rest.reste_avant_404[S] = 5         # en-tête, PP, « Bio : », bio, annonce : puis supprimé
    MENUS.clear()
    a0 = len(rest.appels)
    ot.traiter(clic("outk:dlo:tout:30:sky.ards"))
    fini = attendre(lambda: not cog._en_cours_va and not cog._en_cours_pseudo
                    and not ot._lire_etat()["en_cours"])
    time.sleep(0.3)
    posts = [c for m_, c, _g in rest.appels[a0:] if m_ == "POST" and c == f"/channels/{S}/messages"]
    rest.reste_avant_404.pop(S, None)
    rest.disparus.discard(S)
    hm.preparer_post = _prep
    check("ticket supprimé pendant un téléchargement : arrêt au premier 404 (rien de plus téléchargé ni "
          "posté), verrous du VA et du compte rendus, menu non reposé",
          fini and len(posts) == 6 and len(PREPARES) <= 1 and not MENUS, (fini, len(posts), PREPARES, MENUS))
    POSTS[:] = [{"code": "C1", "genre": "photo", "date": 1761800000, "legende": "légende photo"},
                {"code": "V1", "genre": "video", "date": 1761800000, "legende": "légende reel"}]
    bot.cogs.pop("Telechargement", None)
    r = noter_textes(ot.traiter(clic("outk:dlo:tout:5:sky.ards")))
    check("cog du téléchargement absent : dit, rien lancé",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_INDISPONIBLE, r)

    # ── 10. ramener_menu(en_dernier=True), le vrai ───────────────────────
    tk.ramener_menu = _SAUVE_TK["ramener_menu"]

    class FauxTicket:
        def __init__(self):
            self.fil, self.msgs, self.n = [], {}, 0
            self.lent = 0.0                  # secondes par relecture du ticket

        def poser(self, m):
            self.msgs[m["id"]] = m
            self.fil.append(m["id"])

        def api(self, methode, chemin, **kw):
            if methode == "GET" and "?limit=" in chemin:
                lim = int(chemin.rsplit("=", 1)[1])
                vus = [self.msgs[i] for i in reversed(self.fil) if i in self.msgs][:lim]
                time.sleep(self.lent)
                return 200, vus
            if methode == "GET":
                i = chemin.rsplit("/", 1)[1]
                return (200, self.msgs[i]) if i in self.msgs else (404, {})
            if methode == "POST":
                self.n += 1
                i = f"c{self.n}"
                self.poser({"id": i, "type": 0, "author": {"id": "w", "bot": True},
                            "content": kw["json"].get("content"), "components": kw["json"]["components"]})
                return 200, {"id": i}
            if methode == "PUT" and "/pins/" in chemin:
                self.n += 1
                self.poser({"id": f"p{self.n}", "type": 6, "author": {"id": "w", "bot": True},
                            "message_reference": {"message_id": chemin.rsplit("/", 1)[1]}})
                return 204, {}
            if methode == "DELETE":
                i = chemin.rsplit("/", 1)[1]
                self.fil = [x for x in self.fil if x != i]
                return (204, {}) if self.msgs.pop(i, None) else (404, {})
            return 200, {}
    ft = FauxTicket()
    rangs = tk.boutons_va(VA, confirme=True, a_un_lien=False, gid=AG)
    ft.poser({"id": ACC, "type": 0, "author": {"id": "w", "bot": True}, "components": rangs})
    ft.poser({"id": "menu0", "type": 0, "author": {"id": "w", "bot": True},
              "content": "📋 **Menu**", "components": rangs})
    for i in range(3):                     # trois livraisons de Wario sous le menu
        ft.poser({"id": f"f{i}", "type": 0, "author": {"id": "w", "bot": True}, "content": ""})
    e_ = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))
    e_["tickets"][f"{AG}:{VA}"]["menu"] = "menu0"
    tk.ETAT_FICHIER.write_text(json.dumps(e_), encoding="utf-8")
    tk._api_reseau = ft.api
    import liens_va as lv
    _lien_sauve = lv.lien_de
    lv.lien_de = lambda gid, uid: {}
    try:
        check("ramener_menu sans en_dernier : des messages de bots dessous, « deja » (comme avant)",
              tk.ramener_menu(AG, VA, S) == "deja" and ft.fil[-1] == "f2")
        r_ = tk.ramener_menu(AG, VA, S, en_dernier=True)
        neuf = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))["tickets"][f"{AG}:{VA}"]["menu"]
        check("ramener_menu(en_dernier=True) après une livraison : menu reposé en DERNIER, l'ancien retiré, "
              "sans avis d'épingle",
              r_ == "ramene" and ft.fil[-1] == neuf and "menu0" not in ft.msgs
              and not [m for m in ft.msgs.values() if m.get("type") == 6], (r_, ft.fil))
        check("… redemandé tout de suite : déjà le dernier, rien reposé",
              tk.ramener_menu(AG, VA, S, en_dernier=True) == "deja" and ft.fil[-1] == neuf)
        # deux livraisons qui finissent ensemble (le spoof dans un fil du site,
        # le téléchargement sur la boucle de Yoshi) : un seul menu au bout
        for i in range(3):
            ft.poser({"id": f"g{i}", "type": 0, "author": {"id": "w", "bot": True}, "content": ""})
        ft.lent = 0.3
        rs = []
        fils = [threading.Thread(target=lambda: rs.append(tk.ramener_menu(AG, VA, S, en_dernier=True)))
                for _ in range(2)]
        for f_ in fils:
            f_.start()
        for f_ in fils:
            f_.join(10)
        ft.lent = 0.0
        copies = [i for i in ft.fil if i in ft.msgs and ft.msgs[i].get("content") == "📋 **Menu**"]
        neuf = json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))["tickets"][f"{AG}:{VA}"]["menu"]
        check("deux ramener_menu en même temps sur un ticket : UNE copie du menu, en dernier, celle de la "
              "fiche (pas d'orpheline épinglée)",
              sorted(rs) == ["deja", "ramene"] and copies == [neuf] and ft.fil[-1] == neuf,
              (rs, copies, neuf, ft.fil[-4:]))
    finally:
        lv.lien_de = _lien_sauve
        tk._api_reseau = _SAUVE_TK["_api_reseau"]

    # ── 11. un travail coupé par un redémarrage ──────────────────────────
    tk.ramener_menu = lambda gid, uid, salon, en_dernier=False: (
        MENUS.append((gid, uid, salon, en_dernier)), "ramene")[1]
    import safe_json
    # une marque par (ticket, outil) : un spoof et un téléchargement tournent
    # ensemble dans un ticket, la fin de l'un n'efface pas la marque de l'autre
    ot._noter(S, "spoofer", {"gid": AG, "uid": VA, "nom": "clip.mov"})
    ot._noter(S, "download", {"gid": AG, "uid": VA, "nom": "sky.ards"})
    ot._noter(S, "download", None)
    check("marques : la fin du téléchargement laisse celle du spoof du même ticket",
          list(ot._lire_etat()["en_cours"]) == [f"{S}:spoofer"], ot._lire_etat())
    safe_json.write(ot.ETAT, {"en_cours": {
        f"{S}:spoofer": {"salon": S, "quoi": "spoofer", "gid": AG, "uid": VA, "nom": "clip.mov",
                         "processus": "ancien"},
        f"{S2}:download": {"salon": S2, "quoi": "download", "gid": AG, "uid": VA2, "nom": "sky.ards",
                           "processus": "ancien"},
        "7003:spoofer": {"salon": "7003", "quoi": "spoofer", "gid": AG, "uid": "4003", "nom": "x.jpg",
                         "processus": ot._PROCESSUS}}})
    MENUS.clear()
    n0 = len(rest.messages)
    nb = ot.prevenir_interrompus()
    neufs = {m["salon"]: m["content"] for m in rest.messages[n0:]}
    check("redémarrage : chaque ticket coupé l'apprend, le travail de CE processus n'est pas touché",
          nb == 2 and neufs.get(S) == "🎭 clip.mov : interrompu par un redémarrage, renvoie-le."
          and neufs.get(S2) == "⬇️ @sky.ards : interrompu par un redémarrage, relance-le."
          and list(ot._lire_etat()["en_cours"]) == ["7003:spoofer"]
          and sorted(MENUS) == sorted([(AG, VA, S, True), (AG, VA2, S2, True)]),
          (nb, neufs, ot._lire_etat(), MENUS))
    # l'état ne peut pas être réécrit (disque plein, droits) : annoncer
    # maintenant, c'était annoncer de nouveau à chaque déploiement, sans trace
    safe_json.write(ot.ETAT, {"en_cours": {
        f"{S}:spoofer": {"salon": S, "quoi": "spoofer", "gid": AG, "uid": VA, "nom": "clip.mov",
                         "processus": "ancien"}}})
    LOGS = []
    ot._log = LOGS.append
    _ecrire = safe_json.write
    safe_json.write = lambda *a, **k: False
    n0 = len(rest.messages)
    try:
        nb = ot.prevenir_interrompus()
    finally:
        safe_json.write = _ecrire
        ot._log = _SAUVE_OT["_log"]
    check("état non réécrit au démarrage : rien annoncé, c'est DIT au journal, la marque attend le "
          "démarrage suivant",
          nb == 0 and len(rest.messages) == n0 and any("non écrit" in l_ for l_ in LOGS)
          and list(ot._lire_etat()["en_cours"]) == [f"{S}:spoofer"], (nb, LOGS))
    n0 = len(rest.messages)
    check("… qui l'annonce, une fois", ot.prevenir_interrompus() == 1
          and [m["content"] for m in rest.messages[n0:]]
          == ["🎭 clip.mov : interrompu par un redémarrage, renvoie-le."]
          and ot.prevenir_interrompus() == 0)

    # ── 12. aucun texte ne dit « YouLab » ────────────────────────────────
    tout = "\n".join(TEXTES) + "\n" + "\n".join(m["content"] for m in rest.messages)
    check("aucun texte (réponses, fenêtres, ticket) ne dit « YouLab »",
          "youlab" not in tout.lower() and len(TEXTES) > 20, len(TEXTES))
except Exception as _e:
    import traceback
    check("outils des tickets : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-2500:])
finally:
    for _k, _v in _SAUVE_TK.items():
        setattr(tk, _k, _v)
    for _k, _v in _SAUVE_OT.items():
        setattr(ot, _k, _v)
    for _k, _v in _SAUVE_SPF.items():
        setattr(spf, _k, _v)
    for _k, _v in _SAUVE_HM.items():
        setattr(hm, _k, _v)
    for _k, _v in _SAUVE_TL.items():
        setattr(tl, _k, _v)
    if bot is not None:
        bot.loop.call_soon_threadsafe(bot.loop.stop)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
