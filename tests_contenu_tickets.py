# -*- coding: utf-8 -*-
"""tests_contenu_tickets.py — 🎬 Contenu dans les tickets TRUST INSTAGRAM.

Propriétaire, 30/10/2026 : le menu des identités US dans le ticket des VA de
TRUST INSTAGRAM, le contenu livré dans leur ticket.

Ce qui est vérifié (contenu_tickets, tickets_discord, cogs/user) :
  - le menu du ticket d'Agency : rangée du VA (5), puis « 🎬 Contenu » seul
    sur la 2e rangée, puis les managers ; Twitter, Threads : rien ne change ;
    BOUTONS_VERSION monte ; la rangée ne dépend pas de contenu_tickets ;
  - la route : tickets, quêtes et outils laissent passer « cnt: »/« cng: » ;
  - les droits : hors ticket, autre VA, autre serveur refusés ; le manager
    dans le ticket du VA servi ;
  - le panneau éphémère : V2 (flags), ≤ 25 options par menu, ≤ 5 boutons par
    rangée, ≤ 40 composants, custom_id ≤ 100, toutes les identités US une
    fois (37 puis 120) ; identité et quantité dans chaque custom_id ; un seul
    message réécrit (réponse 7) ; « Choisir ma brute » absent ;
  - la quantité (fenêtre, nombre refusé), le ✨ General (réserve, retour) ;
  - la livraison : sur la boucle du bot principal, identité imposée, dans le
    TICKET (cartes V2 en multipart, textes à copier seuls, barre éditée sur
    place), jeton du bot (jamais le webhook du clic), menu reposé en bas ;
  - trop lourd : jamais lu ni envoyé (le message ENTIER borné, moins la marge
    de l'enveloppe), dit par la commande — ou, à défaut, à la fin, une fois
    par fichier ; les fichiers lus dans un fil, jamais sur la boucle ;
  - un choix de menu refusé ou mis en file : le message redessiné (7), la
    raison en tête, aucune option restée choisie ;
  - deux livraisons du même ticket l'une après l'autre, ⬇️/📤 compris (verrou
    commun d'outils_tickets) ; un clic en file le dit ; file bornée ;
    rythme de 5 messages / 5 s ;
  - ticket supprimé pendant la livraison : arrêtée, rien de plus ;
  - redémarrage : chaque livraison coupée annoncée, celles en file comprises,
    en un message par ticket (outils_tickets) ;
  - aucune réponse ni aucun message ne dit « YouLab ».

Faux Discord, faux contenu, dossier temporaire : aucun appel réseau, rien
dans data/. Lancement : python tests_contenu_tickets.py
"""
from __future__ import annotations

import asyncio
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
import brutes_off                      # noqa: E402
import identite_pause                  # noqa: E402
import outils_tickets as ot            # noqa: E402
import tickets_discord as tk           # noqa: E402
import type_identite as ti             # noqa: E402
from cogs import user as u             # noqa: E402

import contenu_tickets as ct           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:600]}]" if detail and not cond else ""))


AG, TW, TH = tk.AGENCY_IG_ID, "1445108485090971710", "1498948161039896586"
VA, VA2, CHEF = "4001", "4002", "4999"
S, S2, ACC = "7001", "7002", "8001"
APP = "1552785601051365516"
V2 = 1 << 15
TMP = pathlib.Path(tempfile.mkdtemp(prefix="contenu_tickets_"))
TEXTES = []                            # tout ce que le VA peut lire : jamais « YouLab »
MODELS = ["lola", "julia"] + [f"m{i:03d}" for i in range(35)]          # 37 identités US


def membre(uid, chef=False, nom="bob"):
    return {"user": {"id": uid, "username": nom}, "roles": ["R_MANAGER"] if chef else [],
            "permissions": "0"}


def clic(cid, uid=VA, salon=S, chef=False, gid=AG, valeurs=None):
    p = {"type": 3, "guild_id": gid, "channel_id": salon, "application_id": APP,
         "token": "jeton-" + cid, "member": membre(uid, chef, nom="vanom" if uid == VA else "bob"),
         "data": {"custom_id": cid}, "message": {"id": "m1", "flags": 64 | V2}}
    if valeurs is not None:
        p["data"]["values"] = list(valeurs)
        p["data"]["component_type"] = 3
    return p


def fenetre(cid, nombre, uid=VA, salon=S, chef=False):
    p = clic(cid, uid, salon, chef)
    p["type"] = 5
    p["data"] = {"custom_id": cid, "components": [
        {"type": 18, "id": 1, "component": {"type": 4, "id": 2, "custom_id": "nombre",
                                            "value": nombre}}]}
    return p


def rep_de(p):
    r = ct.traiter(p)
    TEXTES.append(json.dumps(r, ensure_ascii=False))
    return r


def tous(composants):
    """Tous les composants, à plat."""
    out = []
    for c in composants or []:
        if isinstance(c, dict):
            out.append(c)
            out += tous(c.get("components"))
    return out


def ids_de(composants):
    return [c["custom_id"] for c in tous(composants) if c.get("custom_id")]


def tete(r):
    """Le texte posé en tête d'un écran redessiné (type 7), ou None."""
    comps = ((r or {}).get("data") or {}).get("components") or [{}]
    return comps[0].get("content") if comps[0].get("type") == 10 else None


def coches(r):
    """Les options restées choisies dans les menus d'un écran."""
    return [o for c in tous(((r or {}).get("data") or {}).get("components"))
            if c.get("type") == 3 for o in c.get("options") or [] if o.get("default")]


def valide(composants):
    """(ok, pourquoi) : ce que Discord accepte d'un message V2."""
    plats = tous(composants)
    if ct.compter(composants) > 40:
        return False, f"{ct.compter(composants)} composants"
    for c in plats:
        if c.get("type") == 1 and not 1 <= len(c.get("components") or []) <= 5:
            return False, f"rangée de {len(c.get('components') or [])}"
        if c.get("type") == 3 and not 1 <= len(c.get("options") or []) <= 25:
            return False, f"menu de {len(c.get('options') or [])} options"
        if len(str(c.get("custom_id") or "")) > 100:
            return False, f"custom_id trop long {c['custom_id']}"
    cids = [c["custom_id"] for c in plats if c.get("custom_id")]
    if len(cids) != len(set(cids)):
        return False, "custom_id en double"
    return True, ""


# ─── faux Discord (REST de Wario) ─────────────────────────────────────────
class FauxRest:
    def __init__(self):
        self.appels, self.messages, self.editions, self.retraits = [], [], [], []
        self.niveau = 0
        self.n = 0
        self.verrou = threading.Lock()
        self.disparus = set()
        self.reste_avant_404 = {}

    def api(self, methode, chemin, **kw):
        with self.verrou:
            self.appels.append((methode, chemin, kw.get("gid")))
            inconnu = (404, {"message": "Unknown Channel", "code": 10003})
            morceaux = chemin.split("/")
            if methode == "GET" and chemin.startswith("/guilds/"):
                return 200, {"id": morceaux[2], "premium_tier": self.niveau}
            if chemin.startswith("/channels/"):
                salon = morceaux[2]
                if methode == "POST" and salon in self.reste_avant_404:
                    if self.reste_avant_404[salon] <= 0:
                        self.disparus.add(salon)
                    self.reste_avant_404[salon] -= 1
                if salon in self.disparus:
                    return inconnu
                if methode == "PATCH":
                    self.editions.append((salon, morceaux[4], kw.get("json")))
                    TEXTES.append(json.dumps(kw.get("json"), ensure_ascii=False))
                    return 200, {"id": morceaux[4]}
                if methode == "DELETE":
                    self.retraits.append((salon, morceaux[4]))
                    return 204, {}
                if methode == "POST":
                    if "json" in kw:
                        corps, fichiers = kw["json"], []
                    else:
                        corps = json.loads(kw["data"]["payload_json"])
                        fichiers = [(nom, octets) for nom, octets, _t in kw["files"].values()]
                    self.n += 1
                    m = {"id": str(9000 + self.n), "salon": salon, "content": corps.get("content", ""),
                         "fichiers": fichiers, "corps": corps, "fil": threading.current_thread()}
                    self.messages.append(m)
                    TEXTES.append(json.dumps(corps, ensure_ascii=False))
                    return 200, {"id": m["id"]}
            return 200, {}


class FauxBot:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.fil = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.fil.start()
        self.cogs = {}

    def get_cog(self, nom):
        return self.cogs.get(nom)

    def get_guild(self, _gid):
        return None

    def get_channel(self, _cid):
        return None


def attendre(cond, s=10.0):
    fin = time.time() + s
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def livraison_finie(salon=S, s=10.0):
    return attendre(lambda: salon not in ct._EN_FILE, s)


# ─── faux contenu : les VRAIES commandes, leurs sources remplacées ────────
IMAGES = TMP / "images"
IMAGES.mkdir()
for i in range(6):
    (IMAGES / f"pp_{i}.jpg").write_bytes(b"\xff\xd8\xff" + bytes([i]) * 900)
GROSSE = IMAGES / "grosse.jpg"
GROSSE.write_bytes(b"\xff\xd8\xff" + b"g" * 5000)
VIDEO = TMP / "clip.mp4"
VIDEO.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 1500)
TIRAGES = []                            # (quoi, identité demandée, model réelle, fil)
SOURCE_PP = {"grosse": False}


def faux_pp(identity=None):
    TIRAGES.append(("pp", identity, u._MODEL_REELLE.get(), threading.current_thread()))
    if SOURCE_PP["grosse"]:
        return GROSSE
    deja = sum(1 for t in TIRAGES if t[0] == "pp")
    return IMAGES / f"pp_{(deja - 1) % 6}.jpg"


def faux_post(identity):
    TIRAGES.append(("post", identity, u._MODEL_REELLE.get(), threading.current_thread()))
    return IMAGES / "pp_5.jpg", "ma caption _avec_ des tirets", "ma description @rien", None


class FauxCog(u.UserCog):
    """Le cog du menu : _run_for_model, profilepic, post sont les VRAIS. Les
    trois Trash (des méthodes, pas des commandes) simulent des rendus."""

    def __init__(self, bot):
        super().__init__(bot)
        self.ordre = []                 # (début|fin, n°)
        self.bloque = None              # threading.Event : le rendu attend
        self.n = 0

    async def templatetrash(self, interaction, nombre=3):
        """une vidéo + sa description, par la carte de livraison"""
        self.n += 1
        k = self.n
        self.ordre.append(("debut", k))
        TIRAGES.append(("trash", u._IDENTITY_OVERRIDE.get(), u._MODEL_REELLE.get(),
                        threading.current_thread()))
        if self.bloque is not None:
            await asyncio.to_thread(self.bloque.wait, 10)
        await interaction.response.defer()
        await u._livrer_contenu(interaction, 1, 1, u.get_user_identity(interaction.user.id),
                                [(VIDEO, "trash_1.mp4")], textes=[(u._T_DESC, f"desc trash {k}")],
                                quoi="TRASH")
        self.ordre.append(("fin", k))

    async def templatetrashbanger(self, interaction, nombre=3):
        """un fichier trop lourd dont l'échec n'est PAS dit par la commande"""
        try:
            await interaction.followup.send(file=discord.File(str(GROSSE), filename="grosse.jpg"))
        except discord.HTTPException:
            pass

    async def bruttrash(self, interaction, nombre=3):
        """une barre de progression, éditée sur place"""
        suivi = u._Progression(interaction, 2, "Essai", mot="Reel")
        suivi.DELAI_MINI = 0
        await suivi.demarrer()
        await suivi.un_de_plus()
        await suivi.un_de_plus()


_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "DATA_DIR", "role_manager", "role_helper",
                                         "ramener_menu")}
_SAUVE_OT = {k: getattr(ot, k) for k in ("_api", "_dormir", "_bot_principal", "ETAT", "_log")}
_SAUVE_CT = {k: getattr(ct, k) for k in ("_patienter", "FILE_MAX")}
_SAUVE_U = {k: getattr(u, k) for k in ("_jb_models_marche", "random_profile_pic", "random_post_for",
                                       "load_image_config")}
_SAUVE_TI = {k: getattr(ti, k) for k in ("reserves_liees",)}
_SAUVE_IP = {k: getattr(identite_pause, k) for k in ("en_pause",)}
_SAUVE_BO = {k: getattr(brutes_off, k) for k in ("lister",)}
bot = None
try:
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
    ot._dormir = lambda s: None
    ot.ETAT = TMP / "outils_tickets.json"
    ot._LIMITES.clear()
    PATIENCES = []

    async def _sans_attendre(s):
        PATIENCES.append(s)
    ct._patienter = _sans_attendre
    u._jb_models_marche = lambda marche="us": list(MODELS) if marche == "us" else ["amelia"]
    u.random_profile_pic = faux_pp
    u.random_post_for = faux_post
    u.load_image_config = lambda: {"enabled": False}
    LIES = {"lola": (["brune", "blonde"], [("rousse", "marché FR")])}
    ti.reserves_liees = lambda m: LIES.get(m, ([], []))
    EN_PAUSE = set()
    identite_pause.en_pause = lambda n: str(n).strip().lower() in EN_PAUSE
    # les brutes de la model (gardes du ✨ General : Trash pose sur une brute)
    brutes_off.lister = lambda d, *a, **k: [VIDEO] if "lola" in str(d) else []
    bot = FauxBot()
    cog = FauxCog(bot)
    bot.cogs["UserCog"] = cog
    ot._bot_principal = lambda: bot

    # ── 1. le menu du ticket ─────────────────────────────────────────────
    def ids(rangs):
        return [[b.get("custom_id") for b in r.get("components") or []] for r in rangs]

    for confirme, lien in ((False, True), (True, False), (True, True)):
        r = ids(tk.boutons_va(VA, confirme=confirme, a_un_lien=lien, gid=AG))
        check(f"Agency (confirmé={confirme}, lien={lien}) : rangée du VA (5), puis « 🎬 Contenu » "
              "seul sur la 2e, puis les managers",
              r[0] == [f"usdc:set:{VA}", f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}",
                       "numx:menu"]
              and r[1] == [f"cnt:o:{VA}"] and len(r) == 3
              and all(c.startswith(tk._BOUTONS_MANAGERS) for c in r[2])
              and all(1 <= len(x) <= 5 for x in r) and len(r) <= 5, r)
    b = ct.bouton(VA)
    check("le bouton : « 🎬 Contenu », décrit dans tickets_discord, préfixes lus là-bas",
          (b["label"], b["emoji"]) == ("Contenu", {"name": "🎬"}) and b == tk.bouton_contenu(VA)
          and ct.PREFIXE == tk.CONTENU_PREFIXE == "cnt:" and ct.GENERAL == tk.CONTENU_GENERAL_PREFIXE
          == "cng:" and ct.SERVEURS is tk.CONTENU_DANS_MENU and tk.CONTENU_DANS_MENU == {AG}
          and not b["custom_id"].startswith(tk._BOUTONS_MANAGERS))
    pareils = True
    for gid in (TW, TH, "1"):
        for confirme, lien in ((False, True), (True, False), (False, False)):
            avec = tk.boutons_va(VA, confirme=confirme, a_un_lien=lien, gid=gid)
            sans = tk._boutons_va_sans_contenu(VA, confirme=confirme, a_un_lien=lien, gid=gid)
            pareils = pareils and avec == sans and "cnt:" not in json.dumps(avec)
    check("Twitter, Threads, autre serveur : le menu ne change pas", pareils)
    _mod = sys.modules.get("contenu_tickets")
    sys.modules["contenu_tickets"] = None             # « import contenu_tickets » lève
    try:
        r = ids(tk.boutons_va(VA, confirme=True, a_un_lien=True, gid=AG))
    except Exception as e:                           # noqa: BLE001
        r = [repr(e)]
    finally:
        sys.modules["contenu_tickets"] = _mod
    check("contenu_tickets introuvable : le menu porte quand même 🎬 (rien de consommé)",
          len(r) == 3 and r[1] == [f"cnt:o:{VA}"], r)
    check("BOUTONS_VERSION à 11 : les accueils et leurs copies sont redessinés",
          tk.BOUTONS_VERSION >= 11)
    mp = tk.menu_prive(AG, CHEF)
    cmp_ = [c for x in ids(mp["data"]["components"]) for c in x]
    check("menu privé du staff : 🎬 y est, cinq par rangée au plus",
          f"cnt:o:{CHEF}" in cmp_ and all(len(x["components"]) <= 5 for x in mp["data"]["components"]),
          mp)

    # ── 2. la route ──────────────────────────────────────────────────────
    import quetes_discord
    for p in (clic(f"cnt:o:{VA}"), clic("cng:a:lola:brune:pp:5"), fenetre("cnt:qm:lola", "3")):
        check(f"route : tickets, quêtes et outils laissent passer « {p['data']['custom_id'][:4]} » "
              f"(type {p['type']})",
              tk.traiter(p) is None and quetes_discord.traiter(p) is None and ot.traiter(p) is None)
    check("traiter : None pour ce qui n'est pas « cnt: »/« cng: »",
          ct.traiter(clic("numx:menu")) is None and ct.traiter(clic("outk:dl:1")) is None
          and ct.traiter({"type": 1}) is None)
    src_wu = (BOT / "web_upload.py").read_text(encoding="utf-8")
    i_ot, i_ct = src_wu.find("_rep_ot = _ot.traiter(charge)"), src_wu.find("_rep_ct = _ct.traiter(charge)")
    i_vd = src_wu.find("return jsonify(_vd.traiter_interaction(charge))")
    check("route : branché dans _discord_repondre, après les outils, avant la vérification",
          0 < i_ot < i_ct < i_vd, (i_ot, i_ct, i_vd))

    # ── 3. qui peut cliquer ──────────────────────────────────────────────
    r = rep_de(clic(f"cnt:o:{CHEF}", uid=CHEF, salon="9999", chef=True))
    check("hors ticket (menu privé du staff) : refus poli, en privé",
          r["type"] == 4 and r["data"]["flags"] == 64 and r["data"]["content"] == ot.TEXTE_HORS_TICKET, r)
    r = rep_de(clic(f"cnt:o:{VA}", uid=VA2, salon=S))
    check("un autre VA dans ce ticket : refusé, en privé",
          r["type"] == 4 and r["data"]["flags"] == 64 and r["data"]["content"] == ot.TEXTE_PAS_A_TOI, r)
    r = rep_de(clic(f"cnt:o:{VA}", gid=TW))
    check("un autre serveur : refusé", r["type"] == 4 and r["data"]["flags"] == 64, r)
    n0 = len(TIRAGES)
    r = rep_de(clic("cnt:a:lola:pp:2", uid=VA2))
    time.sleep(0.2)
    check("un autre VA qui clique une action du panneau : refusé, rien de lancé",
          r["data"]["content"] == ot.TEXTE_PAS_A_TOI and len(TIRAGES) == n0 and S not in ct._EN_FILE, r)

    # ── 4. le menu des identités ─────────────────────────────────────────
    r = rep_de(clic(f"cnt:o:{VA}"))
    comps = r["data"]["components"]
    ok, pourquoi = valide(comps)
    menus = [c for c in tous(comps) if c.get("type") == 3]
    vus = [o["value"] for m_ in menus for o in m_["options"]]
    check("🎬 : le menu des identités en éphémère V2 (réponse 4, flags 64|V2), sans texte",
          r["type"] == 4 and r["data"]["flags"] == 64 | V2 and "content" not in r["data"], r["data"].keys())
    check("… valide pour Discord (≤ 25 options par menu, ≤ 5 par rangée, ≤ 40 composants)", ok, pourquoi)
    check("… chaque identité US une fois et une seule (37 : quatre menus de 10)",
          sorted(vus) == sorted(MODELS) and len(menus) == 4
          and all(len(m_["options"]) <= 10 for m_ in menus), (len(menus), len(vus)))
    # la quantité par défaut est CELLE du menu US (_JB_QTE_DEFAUT : 5 dans git,
    # un patch du VPS la met à 1) : jamais une seconde valeur ici
    Q = u._JB_QTE_DEFAUT
    check(f"… la quantité par défaut du menu US ({Q}) est dans le custom_id de chaque menu",
          [m_["custom_id"] for m_ in menus] == [f"cnt:ms:{i}:{Q}" for i in range(4)],
          [m_["custom_id"] for m_ in menus])
    MODELS[:] = ["lola", "julia"] + [f"m{i:03d}" for i in range(118)]
    r120 = rep_de(clic(f"cnt:o:{VA}"))
    ok, pourquoi = valide(r120["data"]["components"])
    vus = [o["value"] for c in tous(r120["data"]["components"]) if c.get("type") == 3 for o in c["options"]]
    check("120 identités : toutes là, une fois, et le message reste valide (menus de 10)",
          ok and sorted(vus) == sorted(MODELS), (pourquoi, len(vus)))
    MODELS[:] = ["lola", "julia"] + [f"m{i:03d}" for i in range(35)]
    trop = [{"type": 17, "components": [{"type": 1, "components": [
        {"type": 3, "custom_id": "cnt:ms:0:5", "options": [{"label": str(i), "value": str(i)}
                                                          for i in range(26)]}]}]}]
    try:
        ct._maj(trop)
        dit = ""
    except ct._Refus as e:
        dit = str(e)
    check("un écran hors des limites de Discord (26 options, ou plus de 40 composants) : jamais "
          "envoyé, dit", dit == ct.TEXTE_TROP_CHARGE, dit)
    r = rep_de(clic(f"cnt:o:{VA}", uid=CHEF, chef=True))
    check("le manager dans le ticket du VA : le menu s'ouvre", r["type"] == 4 and r["data"]["flags"] & V2, r)

    # ── 5. le panneau ────────────────────────────────────────────────────
    r = rep_de(clic("cnt:ms:0:5", valeurs=["lola"]))
    comps = r["data"]["components"]
    pid = ids_de(comps)
    ok, pourquoi = valide(comps)
    textes = [c.get("content") for c in tous(comps) if c.get("type") == 10]
    check("choix d'une identité : le MÊME message devient son panneau (réponse 7, V2)",
          r["type"] == 7 and r["data"]["flags"] == V2, r["type"])
    check("… valide pour Discord", ok, pourquoi)
    check("… l'identité et la quantité dans CHAQUE custom_id d'action",
          "cnt:qb:lola:5" in pid and "cnt:a:lola:pp:5" in pid and "cnt:a:lola:storyme:5" in pid
          and "cnt:s:lola:caption:5" in pid and "cnt:s:lola:flash:5" in pid
          and all(":lola:" in i for i in pid if i.startswith(("cnt:a:", "cnt:s:", "cnt:qb:"))), pid)
    check("… les actions du menu US : Name, Pseudo, PP, Bio, Story me/life/travel, Story CTA, Post, "
          "menus Brut, Caption, Template, Trash, Flash",
          all(f"cnt:a:lola:{k}:5" in pid for k in ("name", "pseudo", "pp", "bio", "storyme", "stlife",
                                                   "sttravel", "storycta", "post"))
          and all(f"cnt:s:lola:{f}:5" in pid for f in ("brut", "caption", "template", "trash", "flash")),
          pid)
    opts = [o["value"] for c in tous(comps) if c.get("custom_id") == "cnt:s:lola:brut:5" for o in c["options"]]
    check("… « 🎛️ Choisir ma brute » absent (vue de Yoshi, clics jamais reçus par Wario)",
          "brutchoix" not in json.dumps(comps) and opts == ["brute", "brutbanger"], opts)
    check("… en-tête : le nom seul ; « 👤 Identité » et « ✨ General » (réserves liées)",
          textes == ["## Lola"] and "cnt:i:5" in pid and "cnt:g:lola:5" in pid, (textes, pid[-3:]))
    check("… plus aucun custom_id du menu US (« jbus: », « jbg: ») : Wario ne les sert pas",
          not [i for i in pid if not i.startswith(("cnt:", "cng:"))], pid)
    r = rep_de(clic("cnt:ms:0:5", valeurs=["julia"]))
    check("julia, sans réserve liée : pas de ✨ General",
          "cnt:g:julia:5" not in ids_de(r["data"]["components"]) and "cnt:i:5" in ids_de(r["data"]["components"]))
    r = rep_de(clic("cnt:ms:0:5", valeurs=["amelia"]))
    ok, pourquoi = valide(r["data"]["components"])
    check("une identité hors des identités US (forgée, ou retirée depuis) : refusée — le menu des "
          "identités REDESSINÉ sur place (7), la raison en tête, aucune option restée choisie",
          r["type"] == 7 and r["data"]["flags"] == V2 and "identités US" in (tete(r) or "")
          and not coches(r) and "cnt:ms:0:5" in ids_de(r["data"]["components"]) and ok, (r["type"], tete(r)))
    EN_PAUSE.add("lola")
    r = rep_de(clic("cnt:ms:0:5", valeurs=["lola"]))
    r2 = rep_de(clic("cnt:a:lola:pp:5"))
    EN_PAUSE.discard("lola")
    check("une identité en pause : refusée (la raison de la pause), jamais « réservé Jailbreak » — "
          "menu redessiné (7) ; le bouton, lui, en privé (4)",
          r["type"] == 7 and r2["type"] == 4 and "Jailbreak" not in (tete(r) or "Jailbreak")
          and tete(r) == r2["data"]["content"], (r, r2))
    r = rep_de(clic("cnt:ms:0:5", valeurs=["lola"]))
    check("… la pause levée, rechoisir lola dans le même menu ouvre son panneau (le choix n'était "
          "pas resté affiché)", r["type"] == 7 and "cnt:a:lola:pp:5" in ids_de(r["data"]["components"])
          and tete(r) is None, r["type"])
    r = rep_de(clic("cnt:i:5"))
    check("👤 Identité : retour au menu des identités, sur place",
          r["type"] == 7 and [c["custom_id"] for c in tous(r["data"]["components"]) if c.get("type") == 3][0]
          == "cnt:ms:0:5", r["type"])

    # ── 6. la quantité ───────────────────────────────────────────────────
    r = rep_de(clic("cnt:qb:lola:5"))
    champ = (r.get("data") or {}).get("components", [{}])[0].get("component") or {}
    check("🔢 : la fenêtre de saisie (réponse 9), pré-remplie, l'identité dans son custom_id",
          r["type"] == 9 and r["data"]["custom_id"] == "cnt:qm:lola" and champ.get("value") == "5"
          and champ.get("custom_id") == "nombre", r)
    r = rep_de(fenetre("cnt:qm:lola", "7"))
    pid = ids_de(r["data"]["components"])
    check("… 7 validé : le panneau réécrit sur place, 7 dans chaque custom_id",
          r["type"] == 7 and "cnt:a:lola:pp:7" in pid and "cnt:qb:lola:7" in pid and "cnt:i:7" in pid, pid)
    r1, r2 = rep_de(fenetre("cnt:qm:lola", "abc")), rep_de(fenetre("cnt:qm:lola", "500"))
    check("… « abc » ou 500 : refusés en privé, avec ce qui était tapé",
          r1["type"] == 4 and "« abc »" in r1["data"]["content"]
          and r2["type"] == 4 and "entre 1 et 100" in r2["data"]["content"], (r1, r2))

    # ── 7. une action : livrée dans le TICKET ────────────────────────────
    MENUS.clear()
    TIRAGES.clear()
    n0, a0 = len(rest.messages), len(rest.appels)
    r = rep_de(clic("cnt:a:lola:pp:3"))
    fini = livraison_finie()
    neufs = rest.messages[n0:]
    check("PP ×3 : accusé silencieux (type 6), rien d'éphémère", r == {"type": 6} and fini, r)
    check("… tirée sur la boucle du bot principal, pour l'identité du clic",
          [t[:2] for t in TIRAGES] == [("pp", "lola")] * 3 and all(t[3] is bot.fil for t in TIRAGES),
          TIRAGES)
    check("… 3 cartes V2 dans le ticket (flags V2, sans texte), chacune avec sa photo en multipart",
          len(neufs) == 3 and all(m["salon"] == S and m["corps"].get("flags", 0) & V2
                                  and "content" not in m["corps"] and len(m["fichiers"]) == 1
                                  for m in neufs), [(m["corps"].get("flags"), m["content"]) for m in neufs])
    gal = [c for m in neufs for c in tous(m["corps"]["components"]) if c.get("type") == 12]
    check("… la galerie pointe EXACTEMENT la pièce jointe (attachment://nom)",
          len(gal) == 3 and all(g_["items"][0]["media"]["url"] == "attachment://" + m["fichiers"][0][0]
                                for g_, m in zip(gal, neufs))
          and all(m["corps"]["attachments"][0]["filename"] == m["fichiers"][0][0] for m in neufs), gal[:1])
    entetes = [c["content"] for m in neufs for c in tous(m["corps"]["components"]) if c.get("type") == 10]
    check("… « 1/3 · lola », « 2/3 · lola », « 3/3 · lola »",
          entetes == ["**1/3** · lola", "**2/3** · lola", "**3/3** · lola"], entetes)
    check("… avec le jeton de Wario (le serveur du ticket), sans mention, jamais par le webhook du clic",
          all(g == AG for m_, c_, g in rest.appels[a0:] if c_.startswith("/channels/"))
          and all(m["corps"]["allowed_mentions"] == {"parse": []} for m in neufs)
          and not [c_ for _m, c_, _g in rest.appels if "/webhooks/" in c_ or "/interactions/" in c_])
    check("… puis le menu redevient le dernier message du ticket (en_dernier)",
          MENUS == [(AG, VA, S, True)], MENUS)
    check("… plus rien en file ni de marque de travail en cours",
          S not in ct._EN_FILE and not ot._lire_etat()["en_cours"], ot._lire_etat())

    # un post : la carte, puis CHAQUE texte à copier seul dans son message
    n0 = len(rest.messages)
    MENUS.clear()
    rep_de(clic("cnt:a:lola:post:1"))
    livraison_finie()
    neufs = rest.messages[n0:]
    contenus = [m["content"] for m in neufs]
    etiquettes = [[c.get("label") for c in tous(m["corps"].get("components")) if c.get("type") == 2]
                  for m in neufs]
    check("Post : la carte (V2), puis la caption SEULE, puis la description SEULE (copie sur téléphone)",
          len(neufs) == 3 and neufs[0]["corps"].get("flags", 0) & V2 and len(neufs[0]["fichiers"]) == 1
          and contenus[1:] == ["ma caption _avec_ des tirets", "ma description @rien"], contenus)
    check("… chaque texte nommé par une étiquette grise, désactivée, sans aperçu de lien ni mention",
          etiquettes[1:] == [["📝 Caption"], ["📄 Description"]]
          and all(c.get("disabled") for m in neufs[1:] for c in tous(m["corps"]["components"])
                  if c.get("type") == 2)
          and all(m["corps"].get("flags", 0) & 4 and not m["corps"].get("flags", 0) & V2 for m in neufs[1:])
          and all(m["corps"]["allowed_mentions"] == {"parse": []} for m in neufs), etiquettes)
    check("… et le menu reposé", MENUS == [(AG, VA, S, True)], MENUS)

    # le manager clique dans le ticket du VA : livré dans CE ticket, pour le VA
    n0 = len(rest.messages)
    TIRAGES.clear()
    MENUS.clear()
    r = rep_de(clic("cnt:a:julia:pp:1", uid=CHEF, chef=True))
    livraison_finie()
    check("le manager dans le ticket du VA : livré dans CE ticket, menu du VA reposé",
          r == {"type": 6} and [m["salon"] for m in rest.messages[n0:]] == [S]
          and TIRAGES[0][1] == "julia" and MENUS == [(AG, VA, S, True)], (r, MENUS))

    # un menu de famille : réponse 7 (le menu reprend son intitulé) + livraison
    n0 = len(rest.messages)
    TIRAGES.clear()
    r = rep_de(clic("cnt:s:lola:trash:4", valeurs=["templatetrash"]))
    livraison_finie()
    neufs = rest.messages[n0:]
    defauts = [o for c in tous(r["data"]["components"]) if c.get("type") == 3 for o in c["options"]
               if o.get("default")]
    check("menu Trash : le panneau redessiné (aucune option restée cochée), la vidéo livrée + sa "
          "description seule",
          r["type"] == 7 and not defauts and "cnt:s:lola:trash:4" in ids_de(r["data"]["components"])
          and len(neufs) == 2 and neufs[0]["fichiers"][0][0] == "trash_1.mp4"
          and neufs[1]["content"].startswith("desc trash") and TIRAGES[0][1] == "lola", [m["content"] for m in neufs])
    r = rep_de(clic("cnt:s:lola:caption:5", valeurs=["pp"]))
    r2 = rep_de(clic("cnt:s:lola:brut:5", valeurs=["brutchoix"]))
    r3 = rep_de(clic("cnt:a:lola:zzz:5"))
    time.sleep(0.2)
    check("une option hors de sa famille, « Choisir ma brute » (menus) : le panneau redessiné (7), "
          "la raison en tête, aucune option restée choisie ; une action inconnue (bouton) : en privé ; "
          "rien de lancé",
          r["type"] == 7 and tete(r) == ct.TEXTE_INCONNUE and not coches(r)
          and r2["type"] == 7 and tete(r2) == ct.TEXTE_EXCLUE and not coches(r2)
          and "cnt:a:lola:pp:5" in ids_de(r["data"]["components"])
          and r3["type"] == 4 and S not in ct._EN_FILE, (tete(r), tete(r2), r3))

    # une barre de progression : postée puis éditée sur place
    e0 = len(rest.editions)
    n0 = len(rest.messages)
    rep_de(clic("cnt:s:lola:trash:2", valeurs=["bruttrash"]))
    livraison_finie()
    barre = rest.messages[n0:]
    ed = rest.editions[e0:]
    check("barre de progression : postée dans le ticket, puis éditée SUR PLACE (PATCH), terminée",
          len(barre) == 1 and barre[0]["corps"].get("embeds")
          and ed and all(e[0] == S and e[1] == barre[0]["id"] for e in ed)
          and "terminé" in json.dumps(ed[-1][2], ensure_ascii=False), (barre, ed))

    # ── 8. trop lourd ────────────────────────────────────────────────────
    from cogs import telechargement as tl
    ot._LIMITES[AG] = (tl._MARGE_ENVOI + 2000, time.time() + 3600)
    SOURCE_PP["grosse"] = True
    n0 = len(rest.messages)
    MENUS.clear()
    rep_de(clic("cnt:a:lola:pp:1"))
    livraison_finie()
    neufs = rest.messages[n0:]
    check("PP au-delà de la limite du serveur : jamais envoyée, DITE dans le ticket (par la commande), "
          "le menu reposé",
          not [f for m in neufs for f in m["fichiers"] if len(f[1]) > 2000]
          and len(neufs) == 1 and "trop lourd" in neufs[0]["content"] and MENUS, [m["content"] for m in neufs])
    n0 = len(rest.messages)
    rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrashbanger"]))
    livraison_finie()
    neufs = rest.messages[n0:]
    check("une commande qui tait le refus : la livraison le dit à la fin, une fois",
          len(neufs) == 1 and neufs[0]["content"].startswith("⚠️ 1 fichier trop lourd pour Discord (")
          and neufs[0]["content"].endswith(" Mo au plus) : pas envoyé."),
          [m["content"] for m in neufs])
    SOURCE_PP["grosse"] = False
    ot._LIMITES.clear()

    # ── 9. le ✨ General ──────────────────────────────────────────────────
    r = rep_de(clic("cnt:g:lola:5"))
    gid_ = ids_de(r["data"]["components"])
    ok, pourquoi = valide(r["data"]["components"])
    check("✨ General : sur place (7), valide, réserve active brune, retour au panneau et aux identités",
          r["type"] == 7 and ok and "cng:a:lola:brune:pp:5" in gid_ and "cng:r:lola:blonde:5" in gid_
          and "cng:s:lola:brune:trash:5" in gid_ and "cnt:p:lola:5" in gid_ and "cnt:i:5" in gid_,
          (pourquoi, gid_))
    r = rep_de(clic("cng:r:lola:blonde:5"))
    check("… choisir blonde : le General passe sur elle",
          r["type"] == 7 and "cng:a:lola:blonde:pp:5" in ids_de(r["data"]["components"]))
    r = rep_de(clic("cng:qb:lola:blonde:5"))
    r2 = rep_de(fenetre("cng:qm:lola:blonde", "2"))
    check("… sa quantité : la fenêtre, puis le General à 2, réserve gardée",
          r["type"] == 9 and r["data"]["custom_id"] == "cng:qm:lola:blonde"
          and r2["type"] == 7 and "cng:a:lola:blonde:pp:2" in ids_de(r2["data"]["components"]), (r, r2))
    TIRAGES.clear()
    n0 = len(rest.messages)
    r = rep_de(clic("cng:a:lola:brune:pp:2"))
    livraison_finie()
    check("… PP du General : contenu de la RÉSERVE, brute de la model, livré dans le ticket",
          r == {"type": 6} and [t[:3] for t in TIRAGES] == [("pp", "brune", "lola")] * 2
          and len(rest.messages[n0:]) == 2 and all(m["salon"] == S for m in rest.messages[n0:]),
          (r, TIRAGES))
    TIRAGES.clear()
    r = rep_de(clic("cng:s:lola:brune:trash:5", valeurs=["templatetrash"]))
    livraison_finie()
    check("… menu Trash du General : redessiné sur place, livré (réserve brune, brute de lola)",
          r["type"] == 7 and TIRAGES and TIRAGES[0][1:3] == ("brune", "lola"), (r, TIRAGES))
    r = rep_de(clic("cng:s:julia:brune:trash:5", valeurs=["templatetrash"]))
    LIES["julia"] = (["brune"], [])
    r2 = rep_de(clic("cng:s:julia:brune:trash:5", valeurs=["templatetrash"]))
    LIES.pop("julia")
    check("… Trash pour une model sans brute : refusé AVANT tout rendu, en nommant la model — le "
          "menu du General redessiné (7), la raison en tête",
          r["type"] == 7 and r2["type"] == 7 and "Julia" in (tete(r2) or "")
          and "brute" in (tete(r2) or "") and not coches(r2) and tete(r), (tete(r), tete(r2)))
    r = rep_de(clic("cng:a:lola:rousse:pp:2"))
    r2 = rep_de(clic("cng:a:julia:brune:pp:2"))
    check("… une réserve non liée : refusée en privé, avec la raison (gardes du General)",
          r["type"] == 4 and "rousse" in r["data"]["content"].lower() and "marché FR" in r["data"]["content"]
          and r2["type"] == 4, (r, r2))
    r = rep_de(clic("cnt:p:lola:5"))
    check("… ↩️ : retour au panneau de lola", r["type"] == 7 and "cnt:a:lola:pp:5" in ids_de(r["data"]["components"]))

    # ── 10. deux livraisons dans le même ticket : l'une après l'autre ────
    def marques(salon=S):
        return {k: v for k, v in ot._lire_etat()["en_cours"].items() if k.startswith(f"{salon}:contenu")}

    cog.ordre.clear()
    cog.bloque = threading.Event()
    r1 = rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrash"]))
    attendre(lambda: cog.ordre)
    r2 = rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrash"]))
    time.sleep(0.2)
    en_cours = marques()
    check("pendant le rendu : la seconde attend (une seule commencée), UNE marque par livraison, "
          "celle en file comprise",
          cog.ordre == [("debut", cog.n)] and len(en_cours) == 2
          and all(v["quoi"] == "contenu" and v["uid"] == VA for v in en_cours.values()), (cog.ordre, en_cours))
    check("… la première part sans un mot (panneau redessiné, rien en tête) ; la seconde dit qu'elle "
          "est en file, en tête du panneau redessiné",
          r1["type"] == 7 and tete(r1) is None
          and r2["type"] == 7 and tete(r2) == ct.TEXTE_EN_FILE.format(n=1) and not coches(r2),
          (tete(r1), tete(r2)))
    r3 = rep_de(clic("cnt:a:lola:pp:1"))
    check("… un bouton cliqué derrière elles : « ⏳ En file (2 avant) », en privé (un accusé muet "
          "laissait recliquer)",
          r3["type"] == 4 and r3["data"]["flags"] == 64
          and r3["data"]["content"] == ct.TEXTE_EN_FILE.format(n=2), r3)
    ct.FILE_MAX = 3
    r = rep_de(clic("cnt:a:lola:pp:1"))
    r4 = rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrash"]))
    ct.FILE_MAX = _SAUVE_CT["FILE_MAX"]
    check("… la file pleine : un bouton refusé en privé ; un menu redessiné (7), la raison en tête — "
          "le même choix rechoisi plus tard repartira ; rien de lancé",
          r["type"] == 4 and r["data"]["content"] == ct.TEXTE_FILE
          and r4["type"] == 7 and tete(r4) == ct.TEXTE_FILE and not coches(r4)
          and len(marques()) == 3, (r, tete(r4), marques()))
    cog.bloque.set()
    livraison_finie()
    k = cog.n
    check("… puis les deux, l'une APRÈS l'autre (jamais mêlées)",
          cog.ordre == [("debut", k - 1), ("fin", k - 1), ("debut", k), ("fin", k)], cog.ordre)
    cog.bloque = None
    check("… et plus de marque en cours", not ot._lire_etat()["en_cours"], ot._lire_etat())
    check("… et plus personne ne tient le ticket", not ot.ticket_occupe(S))

    # l'arrêt du bot (un déploiement) coupe une livraison ET celle en file :
    # leurs marques restent, le redémarrage les annonce toutes, en un message
    cog.bloque = threading.Event()
    cog.ordre.clear()
    MENUS.clear()
    rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrash"]))
    attendre(lambda: cog.ordre)
    rep_de(clic("cnt:a:lola:post:1"))
    time.sleep(0.2)

    async def _couper():
        for tache in asyncio.all_tasks():
            if getattr(tache.get_coro(), "__name__", "") == "_livrer":
                tache.cancel()
    asyncio.run_coroutine_threadsafe(_couper(), bot.loop).result(5)
    livraison_finie()
    cog.bloque.set()
    time.sleep(0.2)
    restees = marques()
    noms = [v["nom"] for v in sorted(restees.values(), key=lambda v: v["ordre"])]
    check("arrêt du bot pendant une livraison, une autre en file : les DEUX marques restent, rien "
          "reposé, la file libérée, le ticket rendu",
          len(restees) == 2 and noms[1] == "Post · lola" and not MENUS and S not in ct._EN_FILE
          and not ot.ticket_occupe(S), (restees, MENUS))
    # le redémarrage : un autre processus relit les marques
    import safe_json
    etat_ = ot._lire_etat()
    for v in etat_["en_cours"].values():
        v["processus"] = "ancien"
    safe_json.write(ot.ETAT, etat_)
    n0 = len(rest.messages)
    nb = ot.prevenir_interrompus()
    dits = [m["content"] for m in rest.messages[n0:]]
    check("… au redémarrage : UN message dans le ticket nomme les deux, dans l'ordre des clics, puis "
          "le menu reposé ; plus aucune marque",
          nb == 1 and dits == [f"🎬 {noms[0]}, {noms[1]} : interrompus par un redémarrage, relance-les."]
          and MENUS == [(AG, VA, S, True)] and not ot._lire_etat()["en_cours"], (dits, MENUS))
    cog.bloque = None

    # le rythme : 5 messages par 5 s et par ticket
    ct._RYTHME.clear()
    PAUSES = [ct._son_tour("x1") for _ in range(7)] + [ct._son_tour("x2")]
    check("rythme : cinq messages passent, le sixième attend son tour (un autre ticket, non)",
          PAUSES[:5] == [0.0] * 5 and 4.5 < PAUSES[5] <= ct.RYTHME_S + 0.1 and PAUSES[7] == 0.0,
          PAUSES)
    check("… et l'attente se fait sur la boucle (asyncio.sleep), jamais dans un fil : les "
          "livraisons au-delà de 5 messages ont attendu leur tour",
          PATIENCES and all(x > 0 for x in PATIENCES), PATIENCES[:5])

    # ── 11. ticket supprimé pendant la livraison ─────────────────────────
    MENUS.clear()
    n0 = len(rest.messages)
    rest.reste_avant_404[S] = 1
    rep_de(clic("cnt:a:lola:pp:4"))
    livraison_finie()
    neufs = rest.messages[n0:]
    check("ticket supprimé après la 1re carte : livraison arrêtée, menu pas reposé, plus de marque",
          len(neufs) == 1 and not MENUS and not ot._lire_etat()["en_cours"] and S not in ct._EN_FILE,
          (len(neufs), MENUS))
    rest.disparus.discard(S)
    rest.reste_avant_404.pop(S, None)

    # ── 11 bis. un ⬇️ ou un 📤 tient le ticket : la 🎬 attend son tour ────
    def sur_boucle(coro):
        return asyncio.run_coroutine_threadsafe(coro, bot.loop).result(10)

    async def _tenir():
        v_ = ot.verrou_livraison(S)
        await v_.acquire()
        return v_
    tenu = sur_boucle(_tenir())
    n0 = len(rest.messages)
    MENUS.clear()
    r = rep_de(clic("cnt:a:lola:pp:1"))
    time.sleep(0.3)
    pendant = len(rest.messages) - n0
    bot.loop.call_soon_threadsafe(tenu.release)
    livraison_finie()
    check("un téléchargement (ou un spoof) tient le ticket : le clic dit « ⏳ En file » en privé, rien "
          "posté avant qu'il le rende — jamais entre une carte et son texte —, puis livré, menu reposé",
          r == ot._ephemere(ct.TEXTE_EN_FILE_AUTRE) and pendant == 0
          and len(rest.messages) - n0 == 1 and MENUS == [(AG, VA, S, True)], (r, pendant, MENUS))
    # et dans l'autre sens : un travail du site (le spoofer) attend la 🎬
    cog.bloque = threading.Event()
    cog.ordre.clear()
    rep_de(clic("cnt:s:lola:trash:1", valeurs=["templatetrash"]))
    attendre(lambda: cog.ordre)
    pris = ot._prendre_ticket(bot.loop, S, attente_max=0.3)
    cog.bloque.set()
    livraison_finie()
    time.sleep(0.1)
    libre = not ot.ticket_occupe(S)
    pris2 = ot._prendre_ticket(bot.loop, S, attente_max=2)
    occupe2 = ot.ticket_occupe(S)
    ot._rendre_ticket(bot.loop, pris2)
    attendre(lambda: not ot.ticket_occupe(S), 2)
    check("… un spoof prêt pendant une 🎬 : il attend (rien tant qu'elle tient le ticket), son attente "
          "bornée abandonnée SANS garder le ticket ; libre, il le prend puis le rend",
          pris is None and libre and pris2 is not None and occupe2 and not ot.ticket_occupe(S),
          (pris, libre, pris2, occupe2))
    cog.bloque = None

    # ── 11 ter. le poids : mesuré sans lire, le message entier borné ──────
    from cogs import telechargement as tl

    class Compteur(io.BytesIO):
        """Un fichier qui note qui le lit."""

        def __init__(self, octets):
            super().__init__(octets)
            self.lectures = []

        def read(self, *a):
            self.lectures.append(threading.current_thread())
            return super().read(*a)

    def envoi(livreur, **kw):
        try:
            sur_boucle(livreur.envoyer(None, kw))
            return None
        except discord.HTTPException as e:
            return e

    liv = ct._Livreur(AG, S, tl._MARGE_ENVOI + 2000)
    n0 = len(rest.messages)
    gros = Compteur(b"x" * 2500)
    e1 = envoi(liv, file=discord.File(gros, filename="gros.jpg"))
    gros2 = Compteur(b"x" * 2500)
    e1b = envoi(liv, file=discord.File(gros2, filename="gros.jpg"))
    check("un fichier au-delà du plafond (limite − marge de l'enveloppe) : 413 sans l'avoir LU (ni sur "
          "la boucle ni ailleurs) ni envoyé ; refusé deux fois (carte, ancien envoi), compté UNE fois",
          e1 is not None and e1.status == 413 and e1b is not None and not gros.lectures
          and not gros2.lectures and len(rest.messages) == n0 and list(liv.lourds) == ["gros.jpg"]
          and "trop lourd" in str(e1), (e1, liv.lourds))
    a_, b_ = Compteur(b"a" * 1200), Compteur(b"b" * 1200)
    e2 = envoi(liv, files=[discord.File(a_, filename="a.jpg"), discord.File(b_, filename="b.jpg")])
    check("deux fichiers qui passent chacun, pas ensemble : 413 (Discord borne le message entier), rien "
          "lu ni envoyé",
          e2 is not None and e2.status == 413 and not a_.lectures and not b_.lectures
          and len(rest.messages) == n0 and sorted(liv.lourds) == ["a.jpg", "b.jpg", "gros.jpg"], e2)
    a2 = Compteur(b"a" * 800)
    vrai = discord.File(str(IMAGES / "pp_1.jpg"), filename="pp_1.jpg")
    e3 = envoi(liv, files=[discord.File(a2, filename="a.jpg"), vrai])
    check("… a.jpg repart avec une petite : envoyé, lu DANS UN FIL (jamais sur la boucle de Yoshi), "
          "fichier refermé comme discord.py le fait, et a.jpg n'est plus compté trop lourd",
          e3 is None and len(rest.messages) == n0 + 1 and a2.lectures
          and all(f_ is not bot.fil for f_ in a2.lectures) and vrai.fp.closed
          and sorted(liv.lourds) == ["b.jpg", "gros.jpg"], (e3, liv.lourds))
    n0 = len(rest.messages)
    sur_boucle(liv.dire_les_lourds())
    check("… la fin dit les DEUX restés en route, une fois",
          [m["content"] for m in rest.messages[n0:]]
          == [f"⚠️ 2 fichiers trop lourds pour Discord ({ct._mo(liv.plafond)} Mo au plus) : pas envoyés."],
          [m["content"] for m in rest.messages[n0:]])
    idx = src_wu.find("import contenu_tickets as _ct")
    check("route : contenu_tickets importé pour SES clics seulement (fichier manquant : les autres "
          "interactions des trois serveurs ne le touchent pas), préfixes ceux de tickets_discord",
          idx > 0 and 'startswith(("cnt:", "cng:"))' in src_wu[max(0, idx - 400):idx]
          and (tk.CONTENU_PREFIXE, tk.CONTENU_GENERAL_PREFIXE) == ("cnt:", "cng:"))

    # ── 12. redémarrage, bot indisponible ────────────────────────────────
    safe_json.write(ot.ETAT, {"en_cours": {f"{S}:contenu": {
        "salon": S, "quoi": "contenu", "gid": AG, "uid": VA, "nom": "Caption · lola",
        "processus": "ancien"}}})
    MENUS.clear()
    n0 = len(rest.messages)
    nb = ot.prevenir_interrompus()
    check("redémarrage pendant une livraison : annoncé dans le ticket, le menu reposé",
          nb == 1 and [m["content"] for m in rest.messages[n0:]]
          == ["🎬 Caption · lola : interrompu par un redémarrage, relance-le."]
          and MENUS == [(AG, VA, S, True)], [m["content"] for m in rest.messages[n0:]])
    ot._bot_principal = lambda: None
    r = rep_de(clic(f"cnt:o:{VA}"))
    ot._bot_principal = lambda: bot
    check("bot principal indisponible : « Indisponible », rien d'ouvert",
          r["type"] == 4 and r["data"]["content"] == ot.TEXTE_INDISPONIBLE, r)
    faux = SimpleNamespace(loop=discord.client._loop, get_cog=bot.get_cog)
    ot._bot_principal = lambda: faux
    try:
        r1 = rep_de(clic("cnt:ms:0:5", valeurs=["lola"]))
        r2 = rep_de(clic("cnt:a:lola:pp:1"))
    finally:
        ot._bot_principal = lambda: bot
    check("Yoshi pas encore connecté (boucle sentinelle) : le panneau s'affiche, l'action dit "
          "« Indisponible » sans exception, rien en file",
          r1["type"] == 7 and r2["type"] == 4 and r2["data"]["content"] == ot.TEXTE_INDISPONIBLE
          and S not in ct._EN_FILE, (r1.get("type"), r2))

    # ── 13. aucune réponse ne dit « YouLab », une seule réponse par clic ──
    tout = "\n".join(TEXTES) + "\n" + "\n".join(json.dumps(m["corps"], ensure_ascii=False)
                                                for m in rest.messages)
    check("aucun texte (réponses, panneaux, ticket) ne dit « YouLab »",
          "youlab" not in tout.lower() and len(TEXTES) > 40, len(TEXTES))
    check("jamais de suivi par le jeton du clic (une seule réponse par interaction)",
          not [c_ for _m, c_, _g in rest.appels if c_.startswith(("/webhooks/", "/interactions/"))])
except Exception as _e:
    import traceback
    check("contenu des tickets : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-2500:])
finally:
    for _k, _v in _SAUVE_TK.items():
        setattr(tk, _k, _v)
    for _k, _v in _SAUVE_OT.items():
        setattr(ot, _k, _v)
    for _k, _v in _SAUVE_CT.items():
        setattr(ct, _k, _v)
    for _k, _v in _SAUVE_U.items():
        setattr(u, _k, _v)
    for _k, _v in _SAUVE_TI.items():
        setattr(ti, _k, _v)
    for _k, _v in _SAUVE_IP.items():
        setattr(identite_pause, _k, _v)
    for _k, _v in _SAUVE_BO.items():
        setattr(brutes_off, _k, _v)
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
