# -*- coding: utf-8 -*-
"""tests_bangers_fr.py — bangers et all-banger du serveur FR « Va IG ».

Demande du propriétaire (03/10/2026) : « banger et all-banger comme sur les
US » pour le marché FR —
  - un salon 💥・banger-<model> PAR model, et son 💥・all-banger-<model>
    (pas de all-banger commun : « pas de allbanger dans va ig ») ;
  - Youl4b garde SEULEMENT Jessye, exactement comme avant ;
  - aucun Apify pour le FR (le propriétaire le refuse) : relevé du scrape
    déjà payé et téléchargement CDN gratuit ;
  - même rythme (9 h Paris, la veille) que les US.
Puis le 06/10/2026 :
  - « check juste les id » : TOUS les comptes de l'identité de la model,
    plus de filtre « VA du Discord » ;
  - « pour le serveur IG mets 1000 » : seuil 1 000 vues pour les models FR,
    à la détection comme à la sélection (Jessye garde le sien, 10 000) ;
  - « Poster les anciens bangers » : un rattrapage, une fois PAR MODEL (une
    model sans relevé attend), dans les seuls 💥・all-banger-<model>, par
    tranches, sans rien de payant, du plus ancien au plus récent ;
  - « mets pas de @ de Discord pour Va IG » / « mets le numéro du VA » :
    cartes du matin et récapitulatif anonymes, « Amelia VA 3 » ; la carte
    all-banger ne nomme aucun VA, comme sur Youl4b ;
  - les favoris automatiques ne reçoivent que ce qu'ils recevaient avant.

Tout se joue dans un dossier temporaire, avec de faux serveurs Discord (les
VRAIS composants de discord.py, relus du payload qu'il assemble), un faux
jailbreak.json et des pièges sur Apify et HikerAPI : aucun appel réseau, rien
n'est écrit dans data/. Lancement : python tests_bangers_fr.py
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402

import safe_json                        # noqa: E402
import bangers as bg                    # noqa: E402
import all_banger as ab                 # noqa: E402
import jailbreak                        # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


ns = types.SimpleNamespace

# ---------------------------------------------------------------- bac a sable --
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bangers_fr_test_"))
_SAV_BG = {k: getattr(bg, k) for k in ("FICHIER", "DOSSIER", "DETAILS_DIR", "DOSSIER_JOURNEES",
                                       "CACHE_SCRAPE", "CACHE_VIDEOS", "_video_valide")}
_SAV_AB = {k: getattr(ab, k) for k in ("FICHIER", "DOSSIER_CACHE_INSTA", "FICHIER_HIKER",
                                       "_est_une_video")}
_SAV_JB = (jailbreak.list_all, jailbreak.list_accounts)
_VRAIE_SONDE = bg._video_valide
import liens_fr                         # noqa: E402
_SAV_LF = {k: getattr(liens_fr, k) for k in ("NUMEROS", "ETAT")}
liens_fr.NUMEROS = TMP / "numeros_va_fr.json"
liens_fr.ETAT = TMP / "liens_va_fr.json"
# Les numéros de Va IG (cogs/outils.numeroter) : bob est « Amelia VA 3 »,
# zoe « Emma VA 2 », lea « Lola VA 4 ».
safe_json.write(liens_fr.NUMEROS, {"amelia": {"555": 3}, "emma": {"556": 2}, "lola": {"557": 4}})

bg.FICHIER = TMP / "bangers.json"
bg.DOSSIER = TMP / "bangers"
bg.DETAILS_DIR = TMP / "bangers_details"
bg.DOSSIER_JOURNEES = TMP / "bangers_journees"
bg.CACHE_SCRAPE = TMP / "insta_cache"
bg.CACHE_VIDEOS = TMP / "insta_videos"
ab.FICHIER = TMP / "bangers_all.json"
ab.DOSSIER_CACHE_INSTA = TMP / "insta_videos"
ab.FICHIER_HIKER = TMP / "bangers_all_hiker.json"
for _d in (bg.DOSSIER, bg.DETAILS_DIR, bg.CACHE_SCRAPE, bg.CACHE_VIDEOS):
    _d.mkdir(parents=True, exist_ok=True)

# ffprobe n'existe pas partout : la sonde est remplacée par la signature MP4,
# la vraie est vérifiée à part quand ffmpeg est là.
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000


def _sonde(p):
    try:
        return p.stat().st_size > 1024 and p.read_bytes()[4:8] == b"ftyp"
    except OSError:
        return False


bg._video_valide = _sonde
ab._est_une_video = _sonde

# Le faux jailbreak.json : deux VA Discord (bob pour amelia, zoe pour emma), un
# VA du site seul (Site, sans pseudo Discord), et Jessye.
JB = {
    "jessye": {"accounts": [{"username": "jessy.one", "va": "Safidy"}],
               "vas": [{"name": "Safidy", "discord_username": "safidy"}]},
    "amelia": {"accounts": [{"username": "amelia.va1", "va": "bob"},
                            {"username": "Amelia.Site", "va": "Site"},
                            {"username": "amelia.parti", "va": "parti"}],
               "vas": [{"name": "bob", "discord_username": "bob"},
                       {"name": "Site", "discord_username": ""},
                       {"name": "parti", "discord_username": "parti"}]},
    "emma": {"accounts": [{"username": "emma.va", "va": "zoe"}],
             "vas": [{"name": "zoe", "discord_username": "zoe"}]},
}
jailbreak.list_all = lambda: json.loads(json.dumps(JB))
jailbreak.list_accounts = lambda ident: json.loads(json.dumps((JB.get(ident) or {}).get("accounts") or []))

# QUE PERSONNE N'APPELLE UNE SOURCE PAYANTE. Chaque porte est un piège qui note
# l'appel (et lève : un appel ne doit pas passer inaperçu).
INTERDITS, _SAV_PIEGES = [], []


def _piege(nom):
    def f(*a, **k):
        INTERDITS.append(nom)
        raise AssertionError("appel payant interdit : " + nom)
    return f


for _mod, _fn in (("apify_reels", "fetch_reel_details"), ("apify_reels", "configured"),
                  ("hiker_reels", "scrape_profile"), ("hiker_reels", "_appel"),
                  ("hiker_reels", "get_token"), ("hiker_reels", "_consommer"),
                  ("veille_telegram", "download_via_ytdlp")):
    try:
        _m = __import__(_mod)
    except Exception:
        continue
    if hasattr(_m, _fn):
        _SAV_PIEGES.append((_m, _fn, getattr(_m, _fn)))
        setattr(_m, _fn, _piege(_mod + "." + _fn))

# Le CDN gratuit : un faux téléchargement qui note l'adresse.
import veille_telegram as _vt          # noqa: E402
_SAV_PIEGES.append((_vt, "download_video_bytes", _vt.download_video_bytes))
CDN = []


def _cdn(url, timeout=25, info=None):
    CDN.append(url)
    return MP4


_vt.download_video_bytes = _cdn

# Les journaux, pour « dit une fois ».
JOURNAL = []


class _Oreille(logging.Handler):
    def emit(self, rec):
        JOURNAL.append(rec.getMessage())


_OREILLE = _Oreille()
for _n in ("vabot.bangers", "vabot.all_banger"):
    logging.getLogger(_n).addHandler(_OREILLE)
    logging.getLogger(_n).setLevel(logging.INFO)

# --------------------------------------------------------- faux Discord --
_IDS = [7000]


class Msg:
    def __init__(self, mid, payload, nonce, noms):
        self.id = mid
        self.author = ns(id=42)
        self.nonce = None              # Discord ne le rend pas à la relecture
        self.content = payload.get("content")
        self.embeds = []
        self.attachments = [ns(filename=n) for n in noms]
        self.mention_everyone = False
        self.components = [discord.components._component_factory(c)
                           for c in (payload.get("components") or [])]


class Salon:
    def __init__(self, cid, nom, guild, droits=True, categorie=None):
        self.id, self.name, self.guild, self.position = cid, nom, guild, 0
        self.category = ns(name=categorie) if categorie else None
        self.envois, self.messages, self.droits = [], {}, droits

    async def send(self, content=None, files=None, nonce=None, allowed_mentions=None,
                   view=None, **kw):
        # LE VRAI assemblage de discord.py : ce que Discord recevrait.
        p = discord.http.handle_message_parameters(
            content=content, files=files if files is not None else discord.utils.MISSING,
            view=view, nonce=nonce, allowed_mentions=allowed_mentions)
        payload = p.payload if p.payload is not None else json.loads(p.multipart[0]["value"])
        _IDS[0] += 1
        noms = [f.filename for f in (files or [])]
        m = Msg(_IDS[0], payload, nonce, noms)
        self.envois.append({"payload": payload, "nonce": nonce, "noms": noms, "am": allowed_mentions})
        self.messages[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.messages[int(mid)]

    def history(self, limit=200, after=None):
        async def _gen():
            for m in list(self.messages.values()):
                yield m
        return _gen()

    def permissions_for(self, moi):
        d = bool(self.droits)
        return ns(view_channel=d, send_messages=d, attach_files=d, read_message_history=d)


class Guild:
    def __init__(self, gid, membres=()):
        self.id, self.filesize_limit, self.me = gid, 10 * 1024 * 1024, object()
        self.text_channels, self.members, self.chunked = [], list(membres), True

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == int(cid)), None)


def client_de(*guilds):
    par_id = {g.id: g for g in guilds}

    def get_channel(cid):
        for g in guilds:
            c = g.get_channel(cid)
            if c is not None:
                return c
        return None
    return ns(user=ns(id=42), get_guild=lambda gid: par_id.get(int(gid)), get_channel=get_channel)


def contenus(envoi):
    """Les textes de la carte (TextDisplay), telle que Discord la recevrait."""
    cs = (envoi.get("payload") or {}).get("components") or []
    out = []
    for c in cs:
        for x in (c.get("components") or []):
            if x.get("type") == 10:
                out.append(x.get("content") or "")
    return out


# ----------------------------------------------------------------- données --
JOUR, DEBUT, FIN, _ = bg.fenetre_veille()
HIER = DEBUT + 3600
AVANT_HIER = DEBUT - 86400 + 3600
safe_json.write(bg.FICHIER, {"seuil": 10000, "reels": {
    "JESSY01": {"compte": "jessy.one", "identite": "jessye", "va": "Safidy", "vues": 20000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/JESSY01/", "description": "j"},
    "FRAME01": {"compte": "amelia.va1", "identite": "amelia", "va": "bob", "vues": 15000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FRAME01/",
                "description": "courte"},
    "FRAME02": {"compte": "amelia.site", "identite": "amelia", "va": "Site", "vues": 40000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FRAME02/"},
    "FRAME03": {"compte": "amelia.va1", "identite": "amelia", "va": "bob", "vues": 500,
                "poste_le": HIER},
    "FRAME04": {"compte": "amelia.va1", "identite": "amelia", "va": "bob", "vues": 90000,
                "poste_le": AVANT_HIER},
    "FRAME05": {"compte": "amelia.va1", "identite": "amelia", "va": "bob", "vues": 12000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FRAME05/"},
    "FREMMA1": {"compte": "emma.va", "identite": "emma", "va": "zoe", "vues": 30000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FREMMA1/"},
    # Entre 1 000 et 9 999 vues : un banger pour une model FR, pas pour Jessye.
    "FRAME07": {"compte": "amelia.va1", "identite": "amelia", "va": "bob", "vues": 2500,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FRAME07/"},
    "JESSY03": {"compte": "jessy.one", "identite": "jessye", "va": "Safidy", "vues": 2500,
                "poste_le": HIER},
    "FRLOLA1": {"compte": "lola.one", "identite": "lola", "va": "lea", "vues": 5000,
                "poste_le": HIER, "url": "https://www.instagram.com/p/FRLOLA1/"},
}})
# Le relevé du scrape (déjà payé) : statistiques, légende complète, lien CDN.
RELEVE_LE = int(time.time()) - 3600
safe_json.write(bg.CACHE_SCRAPE / "amelia.va1.json", {"scraped_at": RELEVE_LE, "reels": [
    {"shortcode": "FRAME01", "views": 18000, "likes": 900, "comments": 1,
     "caption": "La légende complète #fr_tag", "video_url": "https://cdn.test/FRAME01.mp4"},
    {"shortcode": "FRAME05", "views": 11000, "likes": 50, "comments": 3, "caption": "",
     "video_url": "https://cdn.test/FRAME05.mp4"}]})
(bg.CACHE_VIDEOS / "FRAME01.mp4").write_bytes(MP4)      # le cache des Trends

US = bg.salon_us()
AMELIA, EMMA, LOLA, JULIA = (bg.salon_fr(m) for m in ("amelia", "emma", "lola", "julia"))

try:
    # ============================================================ 1. config --
    check("config : Youl4b garde Jessye, son salon fixe et son dossier de journaux",
          (US["identite"], US["guild_id"], US["channel_id"], US["dossier"], US["apify"])
          == ("jessye", 1535758943324999711, 1548115360702664804, bg.DOSSIER_JOURNEES, True))
    check("config : six models FR, chacune son salon, son sous-dossier, sans Apify, "
          "plus de filtre Discord, anonymes",
          [s["identite"] for s in bg.salons_fr()] == ["amelia", "emma", "sarah", "julia", "lola", "alicia"]
          and all(s["guild_id"] == 1505418484052394004 and not s["apify"] and not s["discord_seulement"]
                  and s["anonyme"] is True
                  and s["dossier"] == bg.DOSSIER_JOURNEES / "fr" / s["identite"]
                  and s["channel_id"] == bg.SALONS_FR[s["identite"]] for s in bg.salons_fr()))
    check("config : Jessye n'est ni anonyme ni filtrée",
          not US.get("anonyme") and not US["discord_seulement"])
    check("seuil : 1 000 pour chaque model FR, le seuil réglable (10 000) pour Jessye",
          bg.SEUIL_FR == 1000 and all(bg.seuil_de(m) == 1000 for m in bg.MODELS_FR)
          and bg.seuil_de("jessye") == bg.seuil() == 10000 and bg.seuil_de("") == 10000
          and bg.seuil_de("Amelia ") == 1000)
    check("config : le libellé est la model (Amélia), pas Jessye",
          AMELIA["libelle"] == "Amélia" and EMMA["libelle"] == "Emma")
    check("config : Jessye passe d'abord", [s["cle"] for s in bg.salons()][0] == "us")

    # ====================================================== 2. comptes admis --
    check("admis : seuls les comptes des VA Discord de la model (pseudo connu)",
          bg.comptes_admis("amelia") == {"amelia.va1", "amelia.parti"},
          bg.comptes_admis("amelia"))
    check("admis : les membres connus, un VA parti du serveur ne compte plus",
          bg.comptes_admis("amelia", {"bob", "zoe"}) == {"amelia.va1"},
          bg.comptes_admis("amelia", {"bob", "zoe"}))
    check("admis : un VA du site sans pseudo Discord n'entre pas (aucun membre à son nom)",
          "amelia.site" not in bg.comptes_admis("amelia")
          and "amelia.site" not in bg.comptes_admis("amelia", {"bob", "zoe"}))
    check("admis : chaque model a les siens", bg.comptes_admis("emma") == {"emma.va"})
    # Le bouton nomme le VA d'après son pseudo Discord, mais add_va refuse un
    # nom déjà pris : une fiche du site (ou fabriquée par add_account) gardait
    # un pseudo vide, et les bangers d'un VA bien présent sur Va IG partaient
    # en hors_discord.
    _JOURNAL_AVANT = len(JOURNAL)
    check("admis : fiche sans pseudo au NOM d'un membre de Va IG : admise",
          "amelia.site" in bg.comptes_admis("amelia", {"bob", "site"}))
    check("admis : … et c'est COMPTÉ et nommé dans le journal",
          any("admis par leur nom" in l and "site" in l for l in JOURNAL[_JOURNAL_AVANT:]),
          JOURNAL[_JOURNAL_AVANT:])
    JB["amelia"]["accounts"].append({"username": "amelia.implicite", "va": "Toto"})
    JB["amelia"]["vas"].append({"name": "Autre", "discord_username": "quelquun"})
    JB["amelia"]["accounts"].append({"username": "amelia.autre", "va": "Autre"})
    try:
        check("admis : fiche implicite (nom porté par des comptes seuls) au nom d'un membre : admise",
              "amelia.implicite" in bg.comptes_admis("amelia", {"bob", "toto"})
              and "amelia.implicite" not in bg.comptes_admis("amelia"))
        check("admis : un pseudo renseigné et différent fait foi, pas le nom",
              "amelia.autre" not in bg.comptes_admis("amelia", {"autre"})
              and "amelia.autre" in bg.comptes_admis("amelia", {"quelquun"}))
    finally:
        JB["amelia"]["accounts"] = [a for a in JB["amelia"]["accounts"]
                                    if a["username"] not in ("amelia.implicite", "amelia.autre")]
        JB["amelia"]["vas"] = [v for v in JB["amelia"]["vas"] if v["name"] != "Autre"]

    # ==================== 2 bis. le bouton « 📷 Mes comptes » pose le pseudo --
    # Le VRAI jailbreak, sur un fichier du bac à sable (jamais data/), et les
    # VRAIES fonctions du bouton relues de cogs/user.py (sans charger le cog).
    import ast as _ast
    _src_user = (BOT / "cogs" / "user.py").read_text(encoding="utf-8")
    _ns_user = {"__builtins__": __builtins__, "log": logging.getLogger("vabot.user")}
    for _n in _ast.parse(_src_user).body:
        if ((isinstance(_n, _ast.FunctionDef) and _n.name in
             ("_comptes_fr_du_va", "_relier_fiche_discord", "_enregistrer_comptes_fr"))
                or (isinstance(_n, _ast.Assign) and any(getattr(t, "id", "") == "COMPTES_FR_MAX"
                                                        for t in _n.targets))):
            exec(compile(_ast.Module(body=[_n], type_ignores=[]), "cogs/user.py", "exec"), _ns_user)
    import sheets_sync as _ss
    _SAV_JBF = {k: getattr(jailbreak, k) for k in ("DATA_DIR", "JAILBREAK_FILE", "BACKUP_DIR",
                                                   "PREV_FILE", "TOMB_FILE")}
    _SAV_LG = dict(jailbreak._LAST_GOOD)
    _SAV_PUSH = _ss.push_all_async
    _stub_jb = (jailbreak.list_all, jailbreak.list_accounts)
    try:
        _ss.push_all_async = lambda *a, **k: None          # jamais vers les vrais Sheets
        jailbreak.DATA_DIR = TMP / "jb"
        jailbreak.JAILBREAK_FILE = TMP / "jb" / "jailbreak.json"
        jailbreak.BACKUP_DIR = TMP / "jb" / "backups"
        jailbreak.PREV_FILE = TMP / "jb" / "jailbreak.prev.json"
        jailbreak.TOMB_FILE = TMP / "jb" / "tombstones.json"
        jailbreak.list_all, jailbreak.list_accounts = _SAV_JB
        jailbreak.add_va("amelia", "Toto")                  # créée sur le site, sans pseudo
        jailbreak.add_account("amelia", "amelia.lea", va="lea")   # fiche fabriquée, pseudo vide
        jailbreak.add_va("amelia", "Marc", discord_username="marc_ig")
        _r = _ns_user["_enregistrer_comptes_fr"]("amelia", "toto", ["amelia.toto1"])
        _fiche = {str(v["name"]).lower(): v for v in jailbreak.list_all()["amelia"]["vas"]}
        check("bouton : fiche du site sans pseudo -> le pseudo Discord y est posé",
              _r["ajoutes"] == ["amelia.toto1"] and _fiche["toto"]["discord_username"] == "toto"
              and bg.comptes_admis("amelia", {"toto"}) >= {"amelia.toto1"}
              and bg.comptes_admis("amelia") >= {"amelia.toto1"}, (_r, _fiche.get("toto")))
        _ns_user["_enregistrer_comptes_fr"]("amelia", "lea", ["amelia.lea2"])
        _fiche = {str(v["name"]).lower(): v for v in jailbreak.list_all()["amelia"]["vas"]}
        check("bouton : fiche fabriquée par add_account -> pseudo posé, ses comptes comptent",
              _fiche["lea"]["discord_username"] == "lea"
              and {"amelia.lea", "amelia.lea2"} <= bg.comptes_admis("amelia")
              and len(jailbreak.accounts_for_discord_username("lea")) == 2, _fiche.get("lea"))
        _ns_user["_enregistrer_comptes_fr"]("amelia", "marc", ["amelia.marc1"])
        _fiche = {str(v["name"]).lower(): v for v in jailbreak.list_all()["amelia"]["vas"]}
        check("bouton : un pseudo déjà renseigné et différent n'est pas écrasé",
              _fiche["marc"]["discord_username"] == "marc_ig", _fiche.get("marc"))
    finally:
        jailbreak.list_all, jailbreak.list_accounts = _stub_jb
        for _k, _v in _SAV_JBF.items():
            setattr(jailbreak, _k, _v)
        jailbreak._LAST_GOOD.clear()
        jailbreak._LAST_GOOD.update(_SAV_LG)
        _ss.push_all_async = _SAV_PUSH

    # ======================================================= 3. sélection --
    sel_us = [f["shortcode"] for f in bg.selection_jour(bg.toutes(), bg.seuil_de("jessye"), JOUR)]
    check("sélection US : inchangée, Jessye seule, à 10 000 (JESSY03 à 2 500 n'y est pas)",
          sel_us == ["JESSY01"], sel_us)
    sel_am = [f["shortcode"] for f in bg.selection_jour(bg.toutes(), bg.seuil_de("amelia"), JOUR,
                                                         identite="amelia")]
    check("sélection FR : la veille, au-dessus de 1 000, TOUS les comptes de la model, elle seule",
          sel_am == ["FRAME02", "FRAME01", "FRAME05", "FRAME07"], sel_am)
    sel_lola = [f["shortcode"] for f in bg.selection_jour(bg.toutes(), 1000, JOUR, identite="lola")]
    check("sélection FR : un compte de Lola va chez Lola, jamais chez Amelia",
          sel_lola == ["FRLOLA1"] and "FRLOLA1" not in sel_am, sel_lola)

    # ============================================ 3 bis. détection (examiner) --
    # Le seuil vaut là où les bangers NAISSENT : examiner ouvre la fiche et
    # le all-banger lance le téléchargement gratuit.
    _rdet = bg.examiner("amelia.va1", [{"shortcode": "DETFR01", "views": 1500, "taken_at": AVANT_HIER,
                                        "video_url": "https://cdn.test/DETFR01.mp4"}],
                        identite="amelia", va="bob")
    _rdet_us = bg.examiner("jessy.one", [{"shortcode": "DETUS01", "views": 1500, "taken_at": AVANT_HIER}],
                           identite="jessye", va="Safidy")
    _rdet_x = bg.examiner("inconnu.x", [{"shortcode": "DETXX01", "views": 1500, "taken_at": AVANT_HIER}])
    check("détection : un reel FR à 1 500 vues devient un banger (seuil de détection 1 000)",
          [f["shortcode"] for f in _rdet["nouveaux"]] == ["DETFR01"]
          and bg.fiche("DETFR01").get("seuil_detection") == 1000
          and bg.fiche("DETFR01").get("identite") == "amelia", _rdet)
    check("détection : 1 500 vues ne suffisent ni à Jessye ni à un compte sans identité (10 000)",
          not _rdet_us["nouveaux"] and not bg.fiche("DETUS01")
          and not _rdet_x["nouveaux"] and not bg.fiche("DETXX01"))
    _jobs = ab.signaler(_rdet["nouveaux"], [{"shortcode": "DETFR01",
                                             "video_url": "https://cdn.test/DETFR01.mp4"}])
    check("détection : le nouveau banger FR part au téléchargement all-banger (lien gratuit du scrape)",
          [j["shortcode"] for j in _jobs] == ["DETFR01"]
          and ab.entree("DETFR01").get("etat") == "video", _jobs)
    ab._EN_COURS.discard("DETFR01")
    # Les favoris automatiques ne reçoivent que ce qu'ils recevaient avant :
    # un banger FR sous le seuil réglable n'y part pas (dit une fois).
    _favoris = []
    ab.APRES_ARCHIVAGE.append(_favoris.append)
    try:
        for _j in _jobs:
            ab.traiter_job(_j, telecharger_octets=lambda u, i: MP4)
        _jfav = ab.signaler([{"shortcode": "DETFR02", "poste_le": AVANT_HIER}],
                            [{"shortcode": "DETFR02", "video_url": "https://cdn.test/DETFR02.mp4"}])
        _d_reg = bg.charger()
        _d_reg["reels"]["DETFR02"] = {"compte": "amelia.va1", "identite": "amelia", "va": "bob",
                                      "vues": 25000, "poste_le": AVANT_HIER}
        bg._ecrire(_d_reg)
        for _j in _jfav:
            ab.traiter_job(_j, telecharger_octets=lambda u, i: MP4)
    finally:
        ab.APRES_ARCHIVAGE.remove(_favoris.append)
    # Le choix se fait LÀ OÙ les favoris prennent leur travail : leur passage
    # de tous les quarts d'heure relit bangers.json (favoris_auto._a_traiter).
    # Un garde-fou posé sur le seul appel après archivage ne le voyait pas.
    import contextlib as _ctx
    import favoris_auto as _fa
    _sortie_fa = io.StringIO()
    with _ctx.redirect_stdout(_sortie_fa):
        _fa_neufs = _fa._a_traiter({"active_depuis": int(time.time()) - 3600, "bangers": {}}, False)
        _fa_tous = _fa._a_traiter({"active_depuis": int(time.time()) - 3600, "bangers": {}}, True)
        _fa_repris = _fa._a_traiter({"active_depuis": int(time.time()) - 3600, "bangers": {
            "DETFR01": {"etat": "a_reprendre", "essais": 1}}}, False)
    check("détection : favoris automatiques inchangés -- leur passage périodique ne prend pas un "
          "banger FR sous 10 000, prend celui au-dessus, et le dit",
          ab.entree("DETFR01").get("etat") == "pret" and bg.video_presente("DETFR01")
          and _favoris == ["DETFR01", "DETFR02"]
          and _fa_neufs == ["DETFR02"] and _fa_tous == ["DETFR02"]
          and "1 banger(s) des models de Va IG sous 10000 vues" in _sortie_fa.getvalue(),
          (_fa_neufs, _fa_tous, _sortie_fa.getvalue()))
    check("détection : … une pose « à reprendre » (déjà analysée) reste reprise",
          _fa_repris == ["DETFR01", "DETFR02"], _fa_repris)
    check("détection : une seule règle (bangers.pour_les_favoris), Jessye et l'identité vide intactes",
          not bg.pour_les_favoris({"identite": "amelia", "vues": 9999})
          and bg.pour_les_favoris({"identite": "amelia", "vues": 10000})
          and bg.pour_les_favoris({"identite": "jessye", "vues": 1500})
          and bg.pour_les_favoris({"identite": "", "vues": 1500})
          and "pour_les_favoris" in __import__("inspect").getsource(_fa._a_traiter)
          and not hasattr(ab, "_pour_les_favoris"))
    _src_ex = __import__("inspect").getsource(bg._examiner_dans)
    check("détection : le crible prend le seuil DE L'IDENTITÉ", "seuil_de(identite)" in _src_ex)

    # ========================================== 4. publication US inchangée --
    us_prep, us_pub, us_rec = [], [], []

    def _prep_us(fiches):
        us_prep.extend(f["shortcode"] for f in fiches)
        return {f["shortcode"]: dict(f, video_disponible=False) for f in fiches}

    def _pub_us(f, it):
        us_pub.append(f["shortcode"])
        return {"message_id": 501, "channel_id": bg.CHANNEL_ID}

    def _rec_us(j, i, page):
        us_rec.append(page["texte"])
        return {"message_id": 502, "channel_id": bg.CHANNEL_ID}

    b_us = bg.publier_journee(JOUR, _prep_us, _pub_us, _rec_us, strict_veille=True)
    j_us = json.loads((bg.DOSSIER_JOURNEES / (JOUR + ".json")).read_text(encoding="utf-8"))
    check("US : journal au premier niveau, Jessye seule, terminé, au seuil réglable (10 000)",
          b_us.get("termine") and set(j_us["reels"]) == {"JESSY01"} and us_pub == ["JESSY01"]
          and "salon" not in j_us and "hors_discord" not in j_us and j_us["seuil"] == 10000, b_us)
    check("US : récapitulatif « · Jessye », lien vers le salon de Youl4b",
          us_rec and us_rec[0].startswith("## Bangers du ") and " · Jessye" in us_rec[0]
          and f"/channels/{bg.GUILD_ID}/{bg.CHANNEL_ID}/501" in us_rec[0], us_rec[:1])
    check("US : l'annonce des détails porte le salon de Youl4b",
          bg.lire_details("JESSY01").get("annonce", {}).get("channel_id") == bg.CHANNEL_ID)
    check("US : aucun journal FR créé par la publication de Jessye",
          not (bg.DOSSIER_JOURNEES / "fr").exists())
    _v, _fs = bg.fiche_discord({"shortcode": "JESSY01", "compte": "jessy.one", "va": "Safidy",
                                "jour_bilan": JOUR, "vues": 20000, "url": "https://www.instagram.com/p/JESSY01/"},
                               None)
    _txt_us = json.dumps(_v.to_components(), ensure_ascii=False)
    check("US : la carte du matin dit toujours « Jessye · Bangers du »",
          "Jessye · Bangers du" in _txt_us and "Amélia" not in _txt_us)
    for _f in _fs:
        _f.close()
    # Jessye garde la mention de son VA (non notifiante) : rien d'anonyme sur Youl4b.
    _v, _fs = bg.fiche_discord({"shortcode": "JESSY01", "compte": "jessy.one", "va": "Safidy",
                                "discord_id": "777", "jour_bilan": JOUR, "vues": 20000,
                                "url": "https://www.instagram.com/p/JESSY01/"}, None)
    _txt_us2 = json.dumps(_v.to_components(), ensure_ascii=False)
    for _f in _fs:
        _f.close()
    _us_fiches = bg.rattacher_gerants({"JESSY01": {"shortcode": "JESSY01", "va": "Safidy"}}, US,
                                      {"Safidy": "777"})
    _us_rec = bg.textes_recap({"jour": JOUR, "reels": {"JESSY01": {
        "etat": "envoye", "message_id": 501, "fiche": dict(_us_fiches["JESSY01"], compte="jessy.one")}}})
    check("US : la carte et le récapitulatif de Jessye mentionnent toujours le VA (<@777> · Safidy)",
          "**Géré par :** <@777> · Safidy" in _txt_us2
          and _us_fiches["JESSY01"].get("discord_id") == "777" and "va_libelle" not in _us_fiches["JESSY01"]
          and "• <@777> → [@jessy.one]" in _us_rec[0]["texte"] and _us_rec[0]["mentions"] == ["777"],
          (_txt_us2[:200], _us_rec))

    # =================================== 5. publication FR, de bout en bout --
    gfr = Guild(bg.GUILD_FR, [ns(name="bob", id=555, bot=False), ns(name="zoe", id=556, bot=False),
                              ns(name="robot", id=9, bot=True)])
    s_am = Salon(880001, "💥・banger-amelia", gfr)          # recréé : id ≠ secours
    s_all_am = Salon(880002, "💥・all-banger-amelia", gfr)   # son miroir, PAS ce salon
    s_julia = Salon(bg.SALONS_FR["julia"], "renommé-à-la-main", gfr)
    s_lola = Salon(880004, "💥・banger-lola", gfr, droits=False)
    # Les anciens salons rangés aux archives sous le MEME nom, plus haut
    # (Va IG, 03/10/2026) : jamais eux.
    s_vieux_am = Salon(770001, "💥・banger-amelia", gfr, categorie="🗄️ Archives salons")
    s_vieux_all = Salon(770002, "💥・all-banger-amelia", gfr, categorie="🗄️ Archives salons")
    s_allfr = s_all_am
    gfr.text_channels = [s_vieux_am, s_vieux_all, s_all_am, s_am, s_julia, s_lola]
    gus = Guild(bg.GUILD_ID, [ns(name="safidy", id=777, bot=False)])
    s_us = Salon(bg.CHANNEL_ID, "💥・banger", gus)
    s_allus = Salon(1553240454961569832, "💣・all-banger", gus)
    gus.text_channels = [s_us, s_allus]
    CLIENT = client_de(gus, gfr)

    ch, gerants, s_res, pseudos = asyncio.run(bg.contexte_salon(CLIENT, AMELIA))
    check("salon FR : trouvé par son NOM (« 💥・banger-amelia »), pas « all-banger-amelia »"
          " ni l'ancien des archives",
          ch is s_am and s_res["channel_id"] == 880001 and AMELIA["channel_id"] != 880001)
    check("salon FR : le all-banger de la model, par son nom, hors archives",
          bg.salon_banger_de(gfr, "amelia", all_banger=True) is s_all_am
          and bg.salon_banger_de(gfr, "julia", all_banger=True) is None)
    _arch_secours = Salon(bg.SALONS_FR["emma"], "💥・banger-emma", gfr, categorie="🗄️ Archives tickets")
    gfr.text_channels.append(_arch_secours)
    try:
        asyncio.run(bg.contexte_salon(CLIENT, EMMA))
        _err_a = ""
    except bg.SalonAbsent as e:
        _err_a = str(e)
    gfr.text_channels.remove(_arch_secours)
    check("salon FR : l'identifiant de secours rangé aux archives n'est pas pris",
          "aucun salon « banger-emma »" in _err_a, _err_a)
    check("salon FR : gérants et membres lus sur le serveur FR",
          gerants == {"bob": "555"} and pseudos == {"bob", "zoe"}, (gerants, pseudos))
    ch_j, _g, s_j, _p = asyncio.run(bg.contexte_salon(CLIENT, JULIA))
    check("salon FR : renommé à la main, retrouvé par l'identifiant de secours",
          ch_j is s_julia and s_j["channel_id"] == bg.SALONS_FR["julia"])
    ch_u, g_u, s_u, _p = asyncio.run(bg.contexte_salon(CLIENT))
    check("salon US : le salon fixe de Youl4b, comme avant",
          ch_u is s_us and s_u["cle"] == "us" and g_u == {"Safidy": "777"})
    ch_u2, g_u2 = asyncio.run(bg.contexte_publication(CLIENT))
    check("salon US : contexte_publication rend toujours (salon, gérants)",
          ch_u2 is s_us and g_u2 == {"Safidy": "777"})
    for _s, _attendu in ((EMMA, "aucun salon « banger-emma » sur Va IG"),
                         (LOLA, "le bot n'a pas le droit")):
        try:
            asyncio.run(bg.contexte_salon(CLIENT, _s))
            _err = ""
        except bg.SalonAbsent as e:
            _err = str(e)
        check(f"salon FR : {_s['identite']} -> SalonAbsent ({_attendu[:30]}…)", _attendu in _err, _err)

    admis = bg.comptes_admis("amelia", pseudos)
    fr_pub = []

    def _prep_fr(fiches):
        # Le même chemin que le site (web_upload._banger_cycle).
        return bg.rattacher_gerants(bg.preparer_fiches_gratuit(fiches, "amelia"), s_res, gerants)

    def _pub_fr(f, it):
        fr_pub.append(f["shortcode"])
        return asyncio.run(bg.publier_fiche_discord(CLIENT, ch, f, it, s_res))

    def _rec_fr(j, i, page):
        return asyncio.run(bg.publier_recap_discord(CLIENT, ch, j, i, page, s_res))

    n_cdn = len(CDN)
    b_fr = bg.publier_journee(JOUR, _prep_fr, _pub_fr, _rec_fr, strict_veille=True,
                              salon=s_res, admis=admis)
    p_fr = bg.DOSSIER_JOURNEES / "fr" / "amelia" / (JOUR + ".json")
    j_fr = json.loads(p_fr.read_text(encoding="utf-8")) if p_fr.exists() else {}
    check("FR : journal dans son sous-dossier fr/amelia, terminé, au seuil 1 000",
          p_fr.exists() and b_fr.get("termine") and j_fr.get("salon") == "fr:amelia"
          and j_fr.get("seuil") == 1000, b_fr)
    check("FR : TOUS les comptes de la model (le VA du site sans Discord aussi), elle seule",
          set(j_fr.get("reels") or {}) == {"FRAME01", "FRAME02", "FRAME05", "FRAME07"}
          and fr_pub == ["FRAME02", "FRAME01", "FRAME05", "FRAME07"],
          (sorted(j_fr.get("reels") or {}), fr_pub))
    check("FR : plus rien d'écarté « hors Discord »",
          not j_fr.get("hors_discord") and not any("écarté" in l for l in JOURNAL), j_fr.get("hors_discord"))
    check("FR : Jessye n'est pas dans le salon d'Amélia, ni Amélia chez Jessye, ni Lola chez Amélia",
          "JESSY01" not in (j_fr.get("reels") or {}) and "FRLOLA1" not in (j_fr.get("reels") or {})
          and not ({"FRAME01", "FRAME05"} & set(json.loads((bg.DOSSIER_JOURNEES / (JOUR + ".json"))
                                                           .read_text(encoding="utf-8"))["reels"]))
          and not any("jessy.one" in t or "lola.one" in t for e in s_am.envois for t in contenus(e)))
    check("FR : AUCUN appel Apify ni HikerAPI", not INTERDITS, INTERDITS)
    check("FR : la vidéo vient du cache des Trends (copie), puis du CDN gratuit",
          bg.video_presente("FRAME01") and (bg.CACHE_VIDEOS / "FRAME01.mp4").exists()
          and bg.video_presente("FRAME05") and CDN[n_cdn:] == ["https://cdn.test/FRAME05.mp4"],
          CDN[n_cdn:])
    check("FR : aucun tampon ne reste dans l'archive",
          not [p.name for p in bg.DOSSIER.iterdir() if not p.name.endswith(".mp4")],
          sorted(p.name for p in bg.DOSSIER.iterdir()))
    d1 = bg.lire_details("FRAME01")
    check("FR : statistiques du relevé du scrape (vues max, likes, commentaires)",
          (d1.get("vues_actuelles"), d1.get("likes"), d1.get("commentaires"),
           d1.get("statistiques_source"), d1.get("statistiques_le")) == (18000, 900, 1, "scrape", RELEVE_LE), d1)
    check("FR : la description la plus longue connue (légende du relevé)",
          d1.get("description") == "La légende complète #fr_tag")
    check("FR : l'annonce des détails porte le salon FR, jamais celui de Youl4b",
          d1.get("annonce", {}).get("channel_id") == 880001)

    # La carte, telle que Discord la reçoit.
    cartes_toutes = [e for e in s_am.envois if any("### @" in t for t in contenus(e))]
    cartes = [e for e in cartes_toutes if e["noms"][:1] == ["FRAME01.mp4"]]
    c1 = contenus(cartes[0]) if cartes else []
    entete = c1[0] if c1 else ""
    ENTETE_MATIN_FR = entete
    check("FR : la carte dit « Amélia · Bangers du », jamais Jessye",
          "Amélia · Bangers du " in entete and "Jessye" not in json.dumps(cartes, ensure_ascii=False,
                                                                          default=str), entete)
    check("FR : la carte dit le VA par son NUMÉRO (« Amelia VA 3 »), sans mention ni nom",
          entete.startswith("### @amelia.va1\n**Géré par :** Amelia VA 3\nAmélia · Bangers du ")
          and "<@" not in entete and "bob" not in entete
          and cartes[0]["am"].to_dict().get("parse") == [], entete)
    # Les cartes partent dans l'ordre de la journée (fr_pub) ; deux n'ont pas
    # de vidéo, donc pas de pièce jointe pour les reconnaître.
    _gerants_cartes = {sc: re.search(r"\*\*Géré par :\*\* ([^\n]*)", contenus(e)[0]).group(1)
                       for sc, e in zip(fr_pub, cartes_toutes)}
    check("FR : un VA sans numéro connu est « VA » (jamais son nom) et c'est COMPTÉ au journal",
          len(cartes_toutes) == 4
          and _gerants_cartes == {"FRAME02": "VA", "FRAME01": "Amelia VA 3", "FRAME05": "Amelia VA 3",
                                  "FRAME07": "Amelia VA 3"}
          and "Site" not in json.dumps([contenus(e) for e in cartes_toutes], ensure_ascii=False)
          and any("1 fiche(s) sans numéro de VA" in l and "FRAME02" in l for l in JOURNAL),
          (_gerants_cartes, [l for l in JOURNAL if "numéro" in l]))
    _carte02 = next((contenus(e)[0] for e in cartes_toutes
                     if any("@amelia.site" in t for t in contenus(e))), "")
    check("FR : … la carte du compte sans VA du Discord dit « Géré par : VA »",
          "**Géré par :** VA\n" in _carte02, _carte02)
    check("FR : AUCUNE mention dans tout le salon (cartes et bilan), aucune notification",
          not any("<@" in t for e in s_am.envois for t in contenus(e))
          and all(e["am"].to_dict() == {"parse": []} for e in s_am.envois))
    check("FR : la carte dit d'où vient le chiffre (relevé du scrape)",
          "**18 000** vues" in entete and "**1** commentaire " in entete
          and "**900** likes" in entete and "Relevé du scrape du" in entete
          and "vérifiées" not in entete, entete)
    check("FR : vidéo jointe, description à copier, bouton Instagram",
          cartes and cartes[0]["noms"] == ["FRAME01.mp4", "FRAME01_description.txt"]
          and any(t.startswith("**Description à copier**") and "#fr_tag" in t for t in c1))
    recaps = [e for e in s_am.envois if any(t.startswith("## Bangers du") for t in contenus(e))]
    r1 = contenus(recaps[0])[0] if recaps else ""
    if __import__("os").environ.get("BANGERS_FR_VOIR"):
        # Rien ne remplace un rendu réel : la carte et le bilan tels que
        # Discord les reçoit (BANGERS_FR_VOIR=1 python tests_bangers_fr.py).
        for _e in s_am.envois:
            print("----- #" + s_am.name, _e["noms"], "nonce", _e["nonce"])
            print(json.dumps(_e["payload"].get("components"), ensure_ascii=False, indent=1)[:3000])
    RECAP_FR = r1
    j_fr = json.loads(p_fr.read_text(encoding="utf-8"))
    check("FR : récapitulatif « · Amélia », liens vers le salon FR, les VA par leur numéro, sans mention",
          " · Amélia" in r1 and f"/channels/{bg.GUILD_FR}/880001/" in r1
          and str(bg.GUILD_ID) not in r1 and "<@" not in r1 and "bob" not in r1
          and "• Amelia VA 3 → [@amelia.va1]" in r1 and "• VA → [@amelia.site]" in r1
          and all(not p.get("mentions") for p in j_fr.get("recaps") or []), r1[:400])
    check("FR : le récapitulatif ne parle plus de reels écartés",
          "écarté" not in r1, r1[-300:])
    _vide = bg.textes_recap({"jour": JOUR, "reels": {},
                             "hors_discord": [{"shortcode": "X1", "compte": "a", "va": ""},
                                              {"shortcode": "X2", "compte": "b", "va": ""}]}, AMELIA)
    _vide = _vide[0]["texte"] if _vide else ""
    check("FR : tout écarté -> jamais « aucun reel au-dessus du seuil », le compte est donné",
          "Aucun reel au-dessus du seuil" not in _vide and "2 reels au-dessus du seuil écartés" in _vide
          and "Aucun reel des comptes de VA du Discord" in _vide, _vide)
    _us_vide = bg.textes_recap({"jour": JOUR, "reels": {}})[0]["texte"]
    check("US : le récapitulatif vide est inchangé",
          _us_vide.endswith("Aucun reel au-dessus du seuil repéré dans les données disponibles "
                            "pour cette journée.") and "écarté" not in _us_vide, _us_vide)
    check("FR : nonces propres au salon (un même « recap:0 » que Jessye rendrait SON message)",
          recaps and recaps[0]["nonce"] != bg.nonce_banger(JOUR, "recap:0")
          and cartes[0]["nonce"] == bg.nonce_banger(JOUR, "fr:amelia:FRAME01")
          and bg.nonce_banger(JOUR, "FRAME01") != cartes[0]["nonce"])
    check("FR : une journée terminée ne repart pas",
          bg.publier_journee(JOUR, _prep_fr, _pub_fr, _rec_fr, salon=s_res, admis=admis).get("termine")
          and fr_pub == ["FRAME02", "FRAME01", "FRAME05", "FRAME07"])
    # Plus de liste des comptes Discord : Emma se fige sans elle, avec ses
    # seuls comptes (ni Amelia, ni Lola).
    _emma_pub = []
    _b_em = bg.publier_journee(
        JOUR, lambda fs: {f["shortcode"]: dict(f) for f in fs},
        lambda f, it: _emma_pub.append(f["shortcode"]) or {"message_id": 9101,
                                                           "channel_id": EMMA["channel_id"]},
        lambda j, i, page: {"message_id": 9102, "channel_id": EMMA["channel_id"]},
        strict_veille=True, salon=EMMA, admis=None)
    _j_em = json.loads((bg.DOSSIER_JOURNEES / "fr" / "emma" / (JOUR + ".json")).read_text(encoding="utf-8"))
    check("FR : sans liste des comptes Discord, la journée d'Emma se fige quand même, Emma seule",
          _b_em.get("termine") and set(_j_em["reels"]) == {"FREMMA1"} and _emma_pub == ["FREMMA1"]
          and _j_em["seuil"] == 1000, (_b_em, sorted(_j_em.get("reels") or {})))
    # Une journée FR ouverte avant le 06/10 (ancien seuil) mais pas figée :
    # la sélection prend 1 000.
    _jour_av = (bg.datetime.strptime(JOUR, "%Y-%m-%d") - bg.timedelta(days=1)).strftime("%Y-%m-%d")
    _dos_lola = bg.salon_fr("lola")["dossier"]
    safe_json.write(_dos_lola / (_jour_av + ".json"), {"schema": 1, "jour": _jour_av, "seuil": 10000,
                                                       "reels": {}, "salon": "fr:lola"})
    _t_av = bg.datetime.combine(bg.datetime.strptime(_jour_av, "%Y-%m-%d").date(), bg.dt_time.min,
                                bg.TZ).timestamp()
    _d_reg = bg.charger()
    _d_reg["reels"]["FRLOLA0"] = {"compte": "lola.one", "identite": "lola", "va": "lea", "vues": 1800,
                                  "poste_le": int(_t_av) + 7200}
    bg._ecrire(_d_reg)
    bg.publier_journee(_jour_av, lambda fs: {f["shortcode"]: dict(f) for f in fs},
                       lambda f, it: {"message_id": 9201, "channel_id": bg.salon_fr("lola")["channel_id"]},
                       lambda j, i, page: {"message_id": 9202, "channel_id": bg.salon_fr("lola")["channel_id"]},
                       salon=bg.salon_fr("lola"))
    _j_av = json.loads((_dos_lola / (_jour_av + ".json")).read_text(encoding="utf-8"))
    check("FR : une journée ouverte à l'ancien seuil (10 000) et pas figée sélectionne à 1 000",
          _j_av["seuil"] == 1000 and set(_j_av["reels"]) == {"FRLOLA0"}, _j_av)

    # Le piège est réel : la préparation US passe toujours par Apify.
    n_int = len(INTERDITS)
    try:
        bg.preparer_fiches([dict(bg.fiche("JESSY01"), shortcode="JESSY01")])
    except Exception:
        pass
    check("US : la préparation de Jessye passe toujours par Apify (le piège la voit)",
          INTERDITS[n_int:][:1] == ["apify_reels.configured"], INTERDITS[n_int:])
    del INTERDITS[n_int:]

    # ================================ 6. un salon absent ne retient personne --
    publies = []

    def _un(s):
        c, g, sr, mb = asyncio.run(bg.contexte_salon(CLIENT, s))
        if sr["identite"] == "julia":
            raise RuntimeError("panne propre à julia")
        publies.append(sr["cle"])
        return {"jour": JOUR, "annonces": 0, "termine": True}

    n_j = len(JOURNAL)
    liste = [US, EMMA, LOLA, JULIA, AMELIA]
    r1 = bg.publier_salons(liste, _un, JOUR)
    r2 = bg.publier_salons(liste, _un, JOUR)
    check("salons : un salon FR absent ou en panne ne retient ni les autres ni Jessye",
          publies == ["us", "fr:amelia"] * 2 and r1["fr:emma"].get("attente")
          and r1["fr:lola"].get("attente") and r1["fr:julia"].get("erreur")
          and r1["us"].get("termine") and r1["fr:amelia"].get("termine"), (publies, r1))
    _lignes = JOURNAL[n_j:]
    check("salons : chaque cause est dite UNE fois (la boucle repasse chaque minute)",
          sum("banger-emma" in l for l in _lignes) == 1 and sum("lola" in l.lower() for l in _lignes) == 1
          and sum("panne propre à julia" in l for l in _lignes) == 1, _lignes)
    _src_wu = (BOT / "web_upload.py").read_text(encoding="utf-8")
    _cyc = _src_wu.split("def _banger_cycle()", 1)[-1].split("\n_BANGER_TEST", 1)[0]
    check("site : le cycle du matin passe par tous les salons, chacun dans son try",
          "bg.publier_salons(bg.salons(), publier, jour)" in _cyc
          and "bg.preparer_fiches(fiches) if s[\"apify\"]" in _cyc
          and "bg.preparer_fiches_gratuit(fiches, s[\"identite\"])" in _cyc
          and "if s[\"discord_seulement\"] else None" in _cyc
          and "salon=s, admis=admis" in _cyc)
    check("site : les gérants passent par rattacher_gerants (Va IG : le numéro, jamais l'id)",
          "bg.rattacher_gerants(resultat, s, gerants)" in _cyc and "discord_id" not in _cyc)
    _dem = _src_wu.split("def _start_all_banger_daemon()", 1)[-1].split("\ndef ", 1)[0]
    check("site : le fil all-banger fait le rattrapage FR (rattraper_fr=True)",
          "rattraper_fr=True" in _dem, _dem[-400:])

    _v_am = bg._verrou_du_dossier(bg.salon_fr("amelia")["dossier"])
    _v_am.acquire()
    try:
        check("verrous : une model FR en cours ne rend pas Jessye « en cours »",
              bg._verrou_du_dossier(bg.DOSSIER_JOURNEES) is bg._JOURNEE_LOCK
              and bg._JOURNEE_LOCK.acquire(blocking=False) and (bg._JOURNEE_LOCK.release() or True)
              and not _v_am.acquire(blocking=False)
              and bg._verrou_du_dossier(bg.salon_fr("julia")["dossier"]) is not _v_am)
    finally:
        _v_am.release()

    # ============================================================ 7. all-banger --
    ab._SALON_BANGER.update(quand=0.0, ids=frozenset())
    ab._SALONS_FR.update(quand=0.0, racine="", ids={})
    ab._DITS.clear()
    for sc in ("JESSY01", "FRAME02", "HORS001", "FRAME09"):
        if not bg.video_presente(sc):
            bg.chemin_video(sc).write_bytes(MP4)
    ab._ecrire({"schema": 1, "rattrapage": {"fait_le": 1}, "reels": {
        "JESSY01": {"etat": "pret", "poste_le": HIER},
        "FRAME01": {"etat": "pret", "poste_le": HIER},
        "FRAME05": {"etat": "pret", "poste_le": HIER + 60},
        "FRAME02": {"etat": "pret", "poste_le": HIER},       # paru le matin depuis le 06/10
        "HORS001": {"etat": "pret", "poste_le": HIER}}})
    perim_us = ab.passes_par_salon_banger(force=True)
    perim_fr = ab.passes_par_salons_fr(force=True)
    check("all-banger : le périmètre US ne voit pas les journaux FR",
          "JESSY01" in perim_us and not ({"FRAME01", "FRAME05"} & set(perim_us)), sorted(perim_us))
    check("all-banger : le périmètre FR = les journaux FR « envoye », avec leur model",
          perim_fr == {"FRAME01": "amelia", "FRAME02": "amelia", "FRAME05": "amelia",
                       "FRAME07": "amelia", "FREMMA1": "emma", "FRLOLA0": "lola"}, perim_fr)
    check("all-banger : a_poster() (US) inchangé, a_poster('fr:amelia') a les siens",
          ab.a_poster() == ["JESSY01"] and ab.a_poster("fr:amelia") == ["FRAME01", "FRAME02", "FRAME05"]
          and ab.a_poster("fr:julia") == [],
          (ab.a_poster(), ab.a_poster("fr:amelia")))
    check("all-banger : un banger FR va au all-banger de SA model",
          ab._marche_de("X", {"etat": "pret"}, frozenset(), {"X": "julia"}) == "fr:julia"
          and ab._marche_de("X", {"etat": "pret"}, frozenset(), {"X": "inconnue"}) is None
          and ab.guild_du_marche("fr:julia") == bg.GUILD_FR and ab.guild_du_marche("us") == bg.GUILD_ID)
    check("all-banger : signaler reste sans identité (un banger FR est inscrit)",
          [j["shortcode"] for j in ab.signaler(
              [{"shortcode": "FRAME09", "poste_le": HIER, "identite": "amelia"}],
              [{"shortcode": "FRAME09", "video_url": "https://cdn.test/FRAME09.mp4"}])] == ["FRAME09"])
    ab._EN_COURS.discard("FRAME09")

    def poster(sc, e):
        return asyncio.run(ab.envoyer(CLIENT, sc, e))

    b7 = ab.traiter_envois(poster, dormir=lambda s: None)
    reg = ab.charger()["reels"]
    check("all-banger : Jessye dans le all-banger de Youl4b, Amélia dans 💥・all-banger-amelia",
          [e["noms"] for e in s_allus.envois] == [["JESSY01.mp4"]]
          and [e["noms"] for e in s_allfr.envois] == [["FRAME01.mp4"], ["FRAME02.mp4"], ["FRAME05.mp4"]]
          and b7["envoyes"] == 4, b7)
    _txt_allfr = [contenus(e) for e in s_allfr.envois]
    CARTE_ALL_FR = s_allfr.envois[0]["payload"].get("components") if s_allfr.envois else None
    # La carte all-banger reste celle du propriétaire (26/09/2026 : « pas
    # besoin du nom du VA », « réel, description et voir le reel sur
    # Instagram. C'est tout. ») : anonyme comme sur Youl4b, aucun VA.
    check("all-banger FR : la carte reste la même que sur Youl4b (vues, description, bouton), "
          "ni mention, ni nom, ni numéro de VA",
          not ab.NUMERO_VA_ALL_BANGER_FR
          and _txt_allfr and _txt_allfr[0][0] == "**18 000** vues" and _txt_allfr[1][0] == "**40 000** vues"
          and not any("<@" in x or "bob" in x or "Site" in x or "Géré par" in x or "VA" in x
                      for c in _txt_allfr for x in c)
          and all(e["am"].to_dict() == {"parse": []} for e in s_allfr.envois)
          and "va_numero" not in ab.entree("FRAME01"), _txt_allfr)
    _txt_allus = [contenus(e) for e in s_allus.envois]
    check("all-banger US : la carte de Youl4b est inchangée (vues seules, aucun VA)",
          _txt_allus and _txt_allus[0][0] == "**20 000** vues"
          and not any("Géré par" in x for c in _txt_allus for x in c)
          and "va_numero" not in ab.entree("JESSY01"), _txt_allus)
    check("all-banger : chaque entrée garde son marché et son salon",
          (reg["FRAME01"].get("marche"), reg["FRAME01"].get("guild_id"), reg["FRAME01"].get("channel_id"))
          == ("fr:amelia", bg.GUILD_FR, 880002)
          and not s_vieux_all.envois
          and reg["JESSY01"].get("channel_id") == 1553240454961569832
          and reg["JESSY01"].get("marche") == "us")
    check("all-banger : un banger jamais paru le matin ne part nulle part",
          reg["HORS001"]["etat"] == "pret" and reg["FRAME02"]["etat"] == "envoye")

    # Le all-banger FR manque (ni son nom, ni l'identifiant de secours) :
    # Youl4b part quand même, une ligne au journal.
    gfr.text_channels = [s_am, Salon(1, "général", gfr)]
    d = ab.charger()
    d["reels"].update({"JESSY02": {"etat": "pret", "poste_le": HIER}, "FRAME01": dict(reg["FRAME01"])})
    d["reels"]["FRAME05"] = {"etat": "pret", "poste_le": HIER + 60}
    ab._ecrire(d)
    bg.chemin_video("JESSY02").write_bytes(MP4)
    _j_us = json.loads((bg.DOSSIER_JOURNEES / (JOUR + ".json")).read_text(encoding="utf-8"))
    _j_us["reels"]["JESSY02"] = {"etat": "envoye", "message_id": 503}
    safe_json.write(bg.DOSSIER_JOURNEES / (JOUR + ".json"), _j_us)
    ab._SALON_BANGER.update(quand=0.0)
    n_j, n_us = len(JOURNAL), len(s_allus.envois)
    b8 = ab.traiter_envois(poster, dormir=lambda s: None)
    b8b = ab.traiter_envois(poster, dormir=lambda s: None)
    check("all-banger : le salon FR manque -> Youl4b part quand même",
          [e["noms"] for e in s_allus.envois[n_us:]] == [["JESSY02.mp4"]]
          and ab.entree("FRAME05")["etat"] == "pret", b8)
    check("all-banger : la cause FR est à part (la cadence du fil reste celle de Youl4b)",
          not b8.get("attente") and "all-banger-amelia" in (b8.get("attentes") or {}).get("fr:amelia", ""), b8)
    check("all-banger : salon FR absent -> journalisé UNE fois",
          sum("aucun salon" in l and "Va IG" in l for l in JOURNAL[n_j:]) == 1, JOURNAL[n_j:])

    # L'inverse : le all-banger de Youl4b manque, le FR part.
    gfr.text_channels = [s_am, s_allfr, s_vieux_all]
    gus.text_channels = [s_us]
    d = ab.charger()
    d["reels"]["JESSY01"] = {"etat": "pret", "poste_le": HIER}
    ab._ecrire(d)
    n_fr = len(s_allfr.envois)
    b9 = ab.traiter_envois(poster, dormir=lambda s: None)
    check("all-banger : le salon de Youl4b manque -> le FR part quand même",
          [e["noms"] for e in s_allfr.envois[n_fr:]] == [["FRAME05.mp4"]]
          and ab.entree("JESSY01")["etat"] == "pret" and "Youl4b" in b9.get("attente", ""), b9)
    gus.text_channels = [s_us, s_allus]

    # Reprise après coupure : l'intention FR est revérifiée dans LE salon FR.
    d = ab.charger()
    d["reels"]["FRAME05"] = dict(d["reels"]["FRAME05"], etat="envoi", intention_le=1.0,
                                 marche="fr:amelia", nonce=ab.nonce_de("FRAME05"))
    ab._ecrire(d)
    n_fr, n_us = len(s_allfr.envois), len(s_allus.envois)
    b10 = ab.traiter_envois(poster, dormir=lambda s: None)
    check("all-banger : reprise -> retrouvé dans le salon FR, rien de reposté nulle part",
          b10["retrouves"] == 1 and len(s_allfr.envois) == n_fr
          and ab.entree("FRAME05")["channel_id"] == 880002
          and [e["noms"] for e in s_allus.envois[n_us:]] == [["JESSY01.mp4"]], b10)

    # L'interrupteur (NUMERO_VA_ALL_BANGER_FR), si le propriétaire veut le
    # numéro sur cette carte aussi : « Amelia VA 3 », jamais le nom ; « VA »
    # sans numéro, dit au journal.
    ab.NUMERO_VA_ALL_BANGER_FR = True
    try:
        n_fr = len(s_allfr.envois)
        _r_num = [asyncio.run(ab.envoyer(CLIENT, _sc, {"marche": "fr:amelia", "verifier": False}))
                  for _sc in ("FRAME01", "FRAME02")]
    finally:
        ab.NUMERO_VA_ALL_BANGER_FR = False
    _txt_num = [contenus(e) for e in s_allfr.envois[n_fr:]]
    check("all-banger FR : interrupteur allumé -> « Géré par : Amelia VA 3 » / « VA », sans mention ni nom",
          [c[0] for c in _txt_num] == ["**18 000** vues\n**Géré par :** Amelia VA 3",
                                       "**40 000** vues\n**Géré par :** VA"]
          and [r.get("va_numero") for r in _r_num] == [3, 0]
          and not any("<@" in x or "bob" in x or "Site" in x for c in _txt_num for x in c)
          and any("FRAME02" in l and "pas de numéro de VA (VA absent du serveur)" in l for l in JOURNAL),
          (_txt_num, _r_num))

    # Le vrai chemin du fil : poster_via_bot -> boucle du bot -> envoyer, qui
    # route vers le serveur du marché inscrit sur l'entrée.
    boucle = asyncio.new_event_loop()
    fil = threading.Thread(target=boucle.run_forever, daemon=True)
    fil.start()
    try:
        bot = ns(user=CLIENT.user, get_guild=CLIENT.get_guild, loop=boucle, is_ready=lambda: True)
        bg.chemin_video("FRAME06").write_bytes(MP4)
        n_fr = len(s_allfr.envois)
        r_bot = ab.poster_via_bot(bot, "FRAME06", {"marche": "fr:amelia", "verifier": False})
        check("all-banger : poster_via_bot -> le marché fr:amelia va à 💥・all-banger-amelia",
              r_bot.get("channel_id") == 880002 and len(s_allfr.envois) == n_fr + 1, r_bot)
    finally:
        boucle.call_soon_threadsafe(boucle.stop)
        fil.join(5)

    check("all-banger : aucun appel Apify ni HikerAPI de toute la chaîne", not INTERDITS, INTERDITS)

    # ====================================================== 9. rattrapage FR --
    # « Poster les anciens bangers » (06/10/2026) : une fois PAR MODEL, dans
    # les seuls 💥・all-banger-<model>, du plus ancien au plus récent, rien de
    # payant ; une vidéo introuvable est comptée et dite, pas postée. Par
    # tranches (Youl4b poste entre deux), jamais sur un disque plein.
    R = TMP / "rfr"
    for _d in ("bangers", "details", "journees", "cache", "videos"):
        (R / _d).mkdir(parents=True, exist_ok=True)
    bg.FICHIER, bg.DOSSIER, bg.DETAILS_DIR = R / "bangers.json", R / "bangers", R / "details"
    bg.DOSSIER_JOURNEES, bg.CACHE_SCRAPE, bg.CACHE_VIDEOS = R / "journees", R / "cache", R / "videos"
    ab.FICHIER, ab.DOSSIER_CACHE_INSTA = R / "bangers_all.json", R / "videos"
    ab._SALON_BANGER.update(quand=0.0, ids=frozenset())
    ab._SALONS_FR.update(quand=0.0, racine="", ids={})
    ab._DITS.clear()
    bg._DITS.clear()
    ab._EN_COURS.clear()
    ab._FR_VUS.clear()
    ab._FR_ESSAI["quand"] = 0.0
    while not ab.FILE.empty():
        ab.FILE.get_nowait()
    _JB_AVANT = json.loads(json.dumps(JB))
    J, T0 = 86400, int(time.time())

    # a) Sans le site, jamais ; sans rien de lisible, différé (rien de « fait »).
    JB.clear()
    JB["jessye"] = _JB_AVANT["jessye"]
    safe_json.write(bg.FICHIER, {"seuil": 10000, "reels": {}})
    ab._ecrire({"schema": 1, "rattrapage": {"fait_le": 1}, "reels": {}})
    _t_sans = ab.tour(lambda sc, e: {"incertain": "x"}, lambda: True, dormir=lambda s: None)
    _t_vide = ab.tour(lambda sc, e: {"incertain": "x"}, lambda: True, dormir=lambda s: None,
                      rattraper_fr=True)
    check("rattrapage FR : jamais par défaut (tour sans rattraper_fr)",
          "rattrapage_fr" not in _t_sans and not ab.rattrapage_fr_etat(), _t_sans)
    check("rattrapage FR : rien de lisible -> chaque model différée, avec sa cause, rien de « fait »",
          set((_t_vide.get("rattrapage_fr") or {}).get("en_attente") or {}) == set(bg.MODELS_FR)
          and _t_vide["rattrapage_fr"]["en_attente"]["amelia"] == "aucun compte dans jailbreak.json"
          and not ab.rattrapage_fr_etat() and not ab.rattrapage_fr_fait(), _t_vide)

    # b) Les données : relevés du scrape (lecture seule), registre existant.
    #    Emma n'a pas encore de relevé : elle attendra (sans perdre son tour).
    JB.clear()
    JB.update(json.loads(json.dumps(_JB_AVANT)))
    JB["amelia"]["accounts"].append({"username": "partage.x", "va": "bob"})
    # Un compte passé de Lola à Amelia : sa vieille fiche dit encore « lola ».
    JB["amelia"]["accounts"].append({"username": "moved.acc", "va": "bob"})
    JB["lola"] = {"accounts": [{"username": "lola.one", "va": "lea"}, {"username": "partage.x", "va": "lea"}],
                  "vas": [{"name": "lea", "discord_username": "lea"}]}

    def _r(sc, vues, age, url=None, caption=""):
        return {"shortcode": sc, "is_video": True, "views": vues, "taken_at": T0 - age * J,
                "video_url": url, "caption": caption, "url": f"https://www.instagram.com/p/{sc}/"}

    _releve_am = {"scraped_at": T0 - 3600, "reels": [
        _r("RFA0001", 1500, 40, "https://cdn.test/RFA0001.mp4", "vieille légende"),
        _r("RFA0002", 800, 30, "https://cdn.test/RFA0002.mp4"),          # sous 1 000
        _r("RFA0003", 5000, 10),                                          # cache des Trends
        _r("RFA0004", 3000, 5, "https://cdn.test/dead/RFA0004.mp4"),      # lien expiré
        _r("RFA0005", 2000, 20),                                          # aucune source
        {"shortcode": "RFAPHOT", "is_video": False, "views": None, "taken_at": T0 - 2 * J}]}
    safe_json.write(bg.CACHE_SCRAPE / "amelia.va1.json", _releve_am)
    safe_json.write(bg.CACHE_SCRAPE / "lola.one.json", {"scraped_at": T0 - 3600, "reels": [
        _r("RFL0001", 1200, 3, "https://cdn.test/RFL0001.mp4")]})
    safe_json.write(bg.CACHE_SCRAPE / "partage.x.json", {"scraped_at": T0 - 3600, "reels": [
        _r("RFX0001", 9000, 4, "https://cdn.test/RFX0001.mp4")]})

    def _f(compte, ident, vues, age, **kw):
        return dict({"compte": compte, "identite": ident, "va": "bob" if ident == "amelia" else "Safidy",
                     "vues": vues, "poste_le": T0 - age * J, "detecte_le": T0 - age * J + 3600}, **kw)

    safe_json.write(bg.FICHIER, {"seuil": 10000, "reels": {
        "RFA0010": _f("amelia.va1", "amelia", 20000, 15),   # déjà posté dans le all-banger de Youl4b
        "RFA0011": _f("amelia.va1", "amelia", 12000, 12),   # prêt, jamais paru (ancien filtre)
        "RFA0012": _f("amelia.va1", "amelia", 15000, 8),    # déjà dans 💥・all-banger-amelia
        "RFA0013": _f("amelia.va1", "amelia", 11000, 9, essai=True),
        "RFA0014": _f("amelia.va1", "amelia", 3000, 13),    # vidéo ratée à l'époque
        "RFM0001": _f("moved.acc", "lola", 6000, 70),       # compte qui n'est plus à Lola
        "RFJ0001": _f("jessy.one", "jessye", 50000, 6)}})
    ab._ecrire({"schema": 1, "rattrapage": {"fait_le": 1}, "reels": {
        "RFA0010": {"etat": "envoye", "message_id": 4242, "channel_id": 1553240454961569832,
                    "poste_le": T0 - 15 * J, "sans_txt": True},
        "RFA0011": {"etat": "pret", "poste_le": T0 - 12 * J},
        "RFA0012": {"etat": "envoye", "message_id": 4243, "channel_id": 990002, "marche": "fr:amelia",
                    "poste_le": T0 - 8 * J},
        "RFA0014": {"etat": "echec", "raison": "plus_revu_dans_un_scrape", "poste_le": T0 - 13 * J},
        "RFJ0001": {"etat": "envoye", "message_id": 4244, "channel_id": 1553240454961569832}}})
    for _sc in ("RFA0010", "RFA0011", "RFM0001"):
        bg.chemin_video(_sc).write_bytes(MP4)
    for _sc in ("RFA0003", "RFA0014"):
        (bg.CACHE_VIDEOS / (_sc + ".mp4")).write_bytes(MP4)
    CDN_R = []

    def _octets_r(url, info):
        CDN_R.append(url)
        if "/dead/" in url:
            info["reason"] = "http_403"
            return None
        return MP4

    # Une coupure (déploiement) en pleine récupération, au 3e reel.
    class _Coupure(BaseException):
        pass

    _n_coupe = {"n": 0}

    def _coupe():
        _n_coupe["n"] += 1
        if _n_coupe["n"] == 3:
            raise _Coupure()

    n_int, n_j = len(INTERDITS), len(JOURNAL)
    ab._FR_ESSAI["quand"] = 0.0             # le tour « vide » de a) vient de regarder
    try:
        ab.rattrapage_fr(telecharger_octets=_octets_r, entre_deux=_coupe)
        _coupe_ok = False
    except _Coupure:
        _coupe_ok = True
    _am1, _lo1, _em1 = (ab.rattrapage_fr_model(m) for m in ("amelia", "lola", "emma"))
    _ins = _am1.get("inscription") or {}
    check("rattrapage FR : l'inscription est écrite d'un coup, model par model, avant la récupération",
          _coupe_ok and _am1.get("commence_le") and _lo1.get("commence_le") == _am1.get("commence_le")
          and not _am1.get("fait_le") and not _lo1.get("fait_le")
          and _ins == {"trouves": 8, "a_recuperer": 6, "jumeaux": 1, "deja_postes": 1,
                       "deja_en_file": 0, "deja_prets": 1, "en_telechargement": 0,
                       "repris_apres_echec": 1, "autre_model": 0}
          and (_lo1.get("inscription") or {}).get("trouves") == 1
          and (_lo1.get("inscription") or {}).get("a_recuperer") == 1
          and not any(ab.rattrapage_fr_model(m) for m in ("emma", "sarah", "julia", "alicia")),
          (_ins, _lo1))
    _lus_am, _lus_lo = _am1.get("lus") or {}, _lo1.get("lus") or {}
    _cles = ("comptes", "releves_lus", "comptes_sans_releve", "comptes_ambigus", "reels_lus", "fiches_ouvertes")
    check("rattrapage FR : chaque compte est compté, par model (lu, sans relevé, à plusieurs identités)",
          tuple(_lus_am.get(k) for k in _cles) == (5, 1, 3, 1, 6, 4)
          and tuple(_lus_lo.get(k) for k in _cles) == (2, 1, 0, 1, 1, 1)
          and any("plusieurs identités" in l and "@partage.x" in l for l in JOURNAL[n_j:]),
          (_lus_am, _lus_lo))
    check("rattrapage FR : une model sans relevé (Emma) attend, sans être « faite », et c'est dit",
          not _em1 and not ab.rattrapage_fr_fait()
          and any("rattrapage FR de emma différé" in l and "aucun relevé lisible sur 1 compte(s)" in l
                  for l in JOURNAL[n_j:]), [l for l in JOURNAL[n_j:] if "emma" in l])
    check("rattrapage FR : les reels des relevés au-dessus de 1 000 sont ouverts au registre, à 1 000",
          bg.fiche("RFA0001").get("seuil_detection") == 1000 and bg.fiche("RFA0001").get("muet") is True
          and bg.fiche("RFL0001").get("identite") == "lola" and bg.fiche("RFA0003").get("va") == "bob"
          and not bg.fiche("RFA0002") and not bg.fiche("RFAPHOT") and not bg.fiche("RFX0001"))
    check("rattrapage FR : « les comptes de Lola pour Lola » -- la fiche d'un compte qui n'est plus "
          "à Lola n'est postée nulle part, comptée et nommée",
          not ab.entree("RFM0001") and (_lus_lo.get("exclus") or {}).get("compte_hors_model") == 1
          and (_lus_am.get("exclus") or {}).get("essais") == 1
          and any("n'est plus à lola" in l and "RFM0001 (@moved.acc)" in l for l in JOURNAL[n_j:]),
          (_lus_lo.get("exclus"), [l for l in JOURNAL[n_j:] if "RFM0001" in l]))
    check("rattrapage FR : rien ne part avant la fin de la récupération (ordre chronologique)",
          ab.entree("RFA0001").get("etat") == "pret" and ab.entree("RFA0011").get("marche_fr") == "fr:amelia"
          and ab.entree("RFA0005").get("etat") == "echec"
          and ab.a_poster("fr:amelia") == [] and ab.a_poster("fr:lola") == [] and ab.a_poster() == [],
          (ab.a_poster("fr:amelia"), ab.entree("RFA0001")))

    # Pendant la récupération, le banger d'hier paraît le matin dans
    # 💥・banger-amelia : il ATTEND la fin, puis part à sa place (le dernier).
    _d_reg = bg.charger()
    _d_reg["reels"]["RFH0001"] = _f("amelia.va1", "amelia", 4000, 1)
    bg._ecrire(_d_reg)
    bg.chemin_video("RFH0001").write_bytes(MP4)
    _jour_h = bg.datetime.fromtimestamp(T0 - J, bg.TZ).strftime("%Y-%m-%d")
    safe_json.write(bg.DOSSIER_JOURNEES / "fr" / "amelia" / (_jour_h + ".json"),
                    {"schema": 1, "jour": _jour_h, "salon": "fr:amelia",
                     "reels": {"RFH0001": {"etat": "envoye", "message_id": 6001}}})
    # … et Youl4b a son banger du matin à poster, lui aussi.
    _d = ab.charger()
    _d["reels"]["RFH0001"] = {"etat": "pret", "poste_le": T0 - J}
    _d["reels"]["RFJ0002"] = {"etat": "pret", "poste_le": T0 - J}
    ab._ecrire(_d)
    bg.chemin_video("RFJ0002").write_bytes(MP4)
    safe_json.write(bg.DOSSIER_JOURNEES / (_jour_h + ".json"),
                    {"schema": 1, "jour": _jour_h, "reels": {"RFJ0002": {"etat": "envoye", "message_id": 6002}}})
    ab._SALON_BANGER.update(quand=0.0)
    ab._SALONS_FR.update(quand=0.0)
    n_j = len(JOURNAL)
    check("rattrapage FR : le banger du matin de la model en cours attend (il ne passe pas devant "
          "l'historique), Youl4b non, et c'est dit",
          ab.a_poster("fr:amelia") == [] and ab.a_poster() == ["RFJ0002"]
          and any("attendent la fin du rattrapage FR" in l and "fr:amelia" in l for l in JOURNAL[n_j:]),
          (ab.a_poster("fr:amelia"), ab.a_poster(), JOURNAL[n_j:]))

    # Le redémarrage : un reel apparu entre-temps dans un relevé n'est PAS inscrit.
    safe_json.write(bg.CACHE_SCRAPE / "amelia.va1.json",
                    dict(_releve_am, reels=_releve_am["reels"] + [_r("RFA0099", 4000, 2, "https://cdn.test/RFA0099.mp4")]))
    ab._FR_VUS.clear()                       # un redémarrage vide la mémoire du processus
    n_j = len(JOURNAL)
    b_t1 = ab.rattrapage_fr(telecharger_octets=_octets_r, par_tour=1)
    check("rattrapage FR : reprise après l'arrêt, sans réinscription, une TRANCHE à la fois",
          any("repris après un arrêt : amelia, lola" in l for l in JOURNAL[n_j:])
          and b_t1.get("suite") is True and b_t1.get("traites") == 2 and not b_t1.get("faites")
          and ab.rattrapage_fr_model("amelia").get("inscription") == _ins
          and ab.rattrapage_fr_model("amelia").get("commence_le") == _am1["commence_le"]
          and not ab.entree("RFA0099") and not bg.fiche("RFA0099")
          and ab.entree("RFA0010@fr:amelia").get("etat") == "pret" and ab.entree("RFA0014").get("etat") == "pret"
          and ab.entree("RFA0003").get("etat") == "rattrapage_fr", b_t1)

    # Le disque plein : la récupération s'arrête, le dit, ne perd rien.
    _sav_place = ab._place_libre
    ab._place_libre = lambda: 200 * 2 ** 20
    n_j = len(JOURNAL)
    try:
        b_p = ab.rattrapage_fr(telecharger_octets=_octets_r)
    finally:
        ab._place_libre = _sav_place
    check("rattrapage FR : place insuffisante -> pause dite, rien téléchargé, rien perdu",
          "200 Mio libres" in (b_p.get("pause") or "") and not b_p.get("traites")
          and ab.entree("RFA0003").get("etat") == "rattrapage_fr" and len(CDN_R) == 1
          and any("rattrapage FR en pause" in l for l in JOURNAL[n_j:]), (b_p, CDN_R))

    # Un tour du fil : une tranche, puis les envois — Youl4b part sans
    # attendre la fin du rattrapage FR, la tranche suivante est demandée tout de suite.
    _sav_pt = ab.RATTRAPAGE_FR_PAR_TOUR
    ab.RATTRAPAGE_FR_PAR_TOUR = 1
    _postes_t = []

    def _poster_t(sc, e):
        _postes_t.append((sc, e.get("marche")))
        return {"message_id": 7700 + len(_postes_t), "channel_id": 1553240454961569832}

    try:
        _t_tr = ab.tour(_poster_t, lambda: True, dormir=lambda s: None, rattraper_fr=True,
                        telecharger_octets=_octets_r)
    finally:
        ab.RATTRAPAGE_FR_PAR_TOUR = _sav_pt
    check("rattrapage FR : entre deux tranches, Youl4b poste (le FR en cours attend)",
          _postes_t == [("RFJ0002", "us")] and (_t_tr.get("rattrapage_fr") or {}).get("suite") is True
          and ab.entree("RFA0003").get("etat") == "pret" and ab.entree("RFA0004").get("etat") == "rattrapage_fr",
          (_postes_t, _t_tr.get("rattrapage_fr")))
    _src_ab = __import__("inspect").getsource(ab.demarrer)
    check("rattrapage FR : le fil enchaîne la tranche suivante (pas dix minutes plus tard)",
          "RATTRAPAGE_FR_ENTRE_TRANCHES_SEC" in _src_ab and ab.RATTRAPAGE_FR_ENTRE_TRANCHES_SEC < 10)

    n_j = len(JOURNAL)
    b_r = ab.rattrapage_fr(telecharger_octets=_octets_r)
    _bam = ab.rattrapage_fr_model("amelia").get("bilan") or {}
    _blo = ab.rattrapage_fr_model("lola").get("bilan") or {}
    check("rattrapage FR : dernière tranche -> amelia et lola « faites », bilan par model "
          "(en file, sans vidéo et pourquoi)",
          b_r.get("faites") == ["amelia", "lola"] and not b_r.get("suite")
          and ab.rattrapage_fr_model("amelia").get("fait_le") and ab.rattrapage_fr_model("lola").get("fait_le")
          and (_bam.get("en_file"), _bam.get("sans_video"), _blo.get("en_file")) == (5, 2, 1)
          and _bam["raisons_sans_video"] == {"rattrapage_fr:http_403": 1, "rattrapage_fr:pas_de_lien": 1},
          (b_r, _bam, _blo))
    check("rattrapage FR : vidéos gratuites seulement (archive, cache des Trends, CDN du relevé)",
          [ab.entree(k).get("source") for k in ("RFA0001", "RFA0003", "RFA0010@fr:amelia", "RFA0014",
                                                "RFL0001")] == ["cdn", "cache", "archive", "cache", "cdn"]
          and CDN_R == ["https://cdn.test/RFA0001.mp4", "https://cdn.test/dead/RFA0004.mp4",
                        "https://cdn.test/RFL0001.mp4"]
          and not INTERDITS[n_int:], (CDN_R, INTERDITS[n_int:]))
    check("rattrapage FR : sans vidéo -> compté, raison gardée, pas posté",
          ab.entree("RFA0004").get("etat") == "echec" and ab.entree("RFA0005").get("etat") == "echec"
          and ab.entree("RFA0004").get("raison") == "rattrapage_fr:http_403")
    check("rattrapage FR : déjà posté sur Youl4b -> une JUMELLE pour Va IG, l'original intact",
          ab.entree("RFA0010@fr:amelia").get("etat") == "pret"
          and ab.entree("RFA0010@fr:amelia").get("reel") == "RFA0010"
          and ab.entree("RFA0010") == {"etat": "envoye", "message_id": 4242,
                                       "channel_id": 1553240454961569832, "poste_le": T0 - 15 * J,
                                       "sans_txt": True})
    check("rattrapage FR : déjà dans son all-banger, Jessye, essai : on n'y touche pas",
          ab.entree("RFA0012").get("message_id") == 4243 and "marche_fr" not in ab.entree("RFA0012")
          and "marche_fr" not in ab.entree("RFJ0001") and not ab.entree("RFA0013"))
    check("rattrapage FR : une vidéo ratée autrefois est retentée gratuitement",
          ab.entree("RFA0014").get("etat") == "pret"
          and ab.entree("RFA0014").get("raison_avant") == "plus_revu_dans_un_scrape")
    _res = [l for l in JOURNAL[n_j:] if "vidéos récupérées" in l]
    check("rattrapage FR : le résumé de chaque model est au journal",
          len(_res) == 2 and "amelia : 8 trouvé(s), 5 en file, 0 posté(s), 2 sans vidéo" in _res[0]
          and "lola : 1 trouvé(s), 1 en file" in _res[1], _res)

    # Emma est scrapée ensuite : SON rattrapage part à son tour, les autres
    # ne sont pas refaits.
    JB["emma"]["accounts"] = [{"username": "emma.va", "va": "zoe"}]
    safe_json.write(bg.CACHE_SCRAPE / "emma.va.json", {"scraped_at": T0 - 600, "reels": [
        _r("REM0001", 2500, 50, "https://cdn.test/REM0001.mp4")]})
    _n_cdn = len(CDN_R)
    b_em = ab.rattrapage_fr(telecharger_octets=_octets_r)
    check("rattrapage FR : relevé arrivé plus tard -> différé au plus cinq minutes (pas un relevé "
          "relu à chaque tranche)", not b_em.get("inscrites") and not ab.rattrapage_fr_model("emma")
          and len(CDN_R) == _n_cdn, b_em)
    ab._FR_ESSAI["quand"] = 0.0
    b_em = ab.rattrapage_fr(telecharger_octets=_octets_r)
    check("rattrapage FR : … puis Emma a SON rattrapage, une fois, et amelia / lola ne sont pas refaites",
          b_em.get("inscrites") == ["emma"] and b_em.get("faites") == ["emma"]
          and CDN_R[_n_cdn:] == ["https://cdn.test/REM0001.mp4"]
          and ab.entree("REM0001").get("marche_fr") == "fr:emma"
          and ab.rattrapage_fr_model("amelia").get("inscription") == _ins
          and ab.rattrapage_fr_model("amelia").get("commence_le") == _am1["commence_le"], b_em)
    _n_cdn = len(CDN_R)
    ab._FR_ESSAI["quand"] = 0.0
    b_2 = ab.rattrapage_fr(telecharger_octets=_octets_r)
    check("rattrapage FR : une seule fois par model (un nouvel appel ne touche à rien des faites)",
          not b_2.get("inscrites") and not b_2.get("traites") and len(CDN_R) == _n_cdn
          and set(b_2.get("en_attente") or {}) == {"sarah", "julia", "alicia"}
          and all(ab.rattrapage_fr_model(m).get("fait_le") for m in ("amelia", "lola", "emma")), b_2)

    # c) Les envois : chaque reel dans le all-banger de SA model, du plus ancien
    #    au plus récent, au rythme ordinaire ; les salons du matin n'ont rien.
    gfr2 = Guild(bg.GUILD_FR, [ns(name="bob", id=555, bot=False), ns(name="lea", id=557, bot=False)])
    s2_b_am, s2_ab_am = Salon(990001, "💥・banger-amelia", gfr2), Salon(990002, "💥・all-banger-amelia", gfr2)
    s2_b_lo, s2_ab_lo = Salon(990003, "💥・banger-lola", gfr2), Salon(990004, "💥・all-banger-lola", gfr2)
    s2_ab_em = Salon(990006, "💥・all-banger-emma", gfr2)
    gfr2.text_channels = [s2_b_am, s2_ab_am, s2_b_lo, s2_ab_lo, s2_ab_em]
    gus2 = Guild(bg.GUILD_ID, [])
    s2_us, s2_allus = Salon(bg.CHANNEL_ID, "💥・banger", gus2), Salon(1553240454961569832, "💣・all-banger", gus2)
    gus2.text_channels = [s2_us, s2_allus]
    CLIENT2 = client_de(gus2, gfr2)
    _pauses = []

    def poster2(sc, e):
        return asyncio.run(ab.envoyer(CLIENT2, sc, e))

    b_env = ab.traiter_envois(poster2, dormir=_pauses.append)
    check("rattrapage FR : du plus ancien au plus récent, dans le all-banger de SA model -- le "
          "banger du matin retenu part à sa place, le dernier",
          [e["noms"] for e in s2_ab_am.envois] == [["RFA0001.mp4"], ["RFA0010.mp4"], ["RFA0014.mp4"],
                                                   ["RFA0011.mp4"], ["RFA0003.mp4"], ["RFH0001.mp4"]]
          and [e["noms"] for e in s2_ab_lo.envois] == [["RFL0001.mp4"]]
          and [e["noms"] for e in s2_ab_em.envois] == [["REM0001.mp4"]] and b_env["envoyes"] == 8,
          ([e["noms"] for e in s2_ab_am.envois], b_env))
    check("rattrapage FR : seulement les all-banger (ni les salons du matin, ni Youl4b)",
          not s2_b_am.envois and not s2_b_lo.envois and not s2_us.envois and not s2_allus.envois)
    check("rattrapage FR : au rythme ordinaire (DELAI_ENTRE_MESSAGES entre deux messages)",
          _pauses.count(ab.DELAI_ENTRE_MESSAGES) == 7, _pauses)
    check("rattrapage FR : la jumelle a son nonce et son message, l'original garde le sien",
          s2_ab_am.envois[1]["nonce"] == ab.nonce_de("RFA0010@fr:amelia") != ab.nonce_de("RFA0010")
          and ab.entree("RFA0010@fr:amelia").get("channel_id") == 990002
          and ab.entree("RFA0010").get("message_id") == 4242)
    _cartes_r = [contenus(e) for e in s2_ab_am.envois + s2_ab_lo.envois + s2_ab_em.envois]
    check("rattrapage FR : cartes anonymes (vues, description, bouton ; ni mention, ni VA)",
          [c[0] for c in _cartes_r][:2] == ["**1 500** vues", "**20 000** vues"]
          and _cartes_r[6][0] == "**1 200** vues"
          and not any("<@" in x or "bob" in x or "lea" in x or "Géré par" in x for c in _cartes_r for x in c)
          and all(e["am"].to_dict() == {"parse": []}
                  for e in s2_ab_am.envois + s2_ab_lo.envois + s2_ab_em.envois), _cartes_r)
    n_j = len(JOURNAL)
    _suivi = ab.suivre_rattrapage_fr(b_env)
    _fin = [l for l in JOURNAL[n_j:] if "terminé" in l]
    check("rattrapage FR : bilan final de chaque model une fois tout posté, noté clos",
          all(ab.rattrapage_fr_model(m).get("clos_le") for m in ("amelia", "lola", "emma"))
          and _suivi["amelia"]["postes"] == 5 and len(_fin) == 3
          and any("amelia : 8 trouvé(s), 0 en file, 5 posté(s), 2 sans vidéo" in l for l in _fin)
          and any("lola : 1 trouvé(s), 0 en file, 1 posté(s), 0 sans vidéo" in l for l in _fin)
          and not ab.suivre_rattrapage_fr(b_env), (_fin, _suivi))

    # d) Un scrape apporte plus tard un lien neuf pour un reel resté sans
    #    vidéo : repris gratuitement, toujours vers SON all-banger.
    _jobs5 = ab.signaler([], [{"shortcode": "RFA0005", "video_url": "https://cdn.test/RFA0005.mp4"}])
    for _j in _jobs5:
        ab.traiter_job(_j, telecharger_octets=_octets_r)
    check("rattrapage FR : sans vidéo, puis lien neuf d'un scrape -> récupéré, vers 💥・all-banger-amelia",
          [j["shortcode"] for j in _jobs5] == ["RFA0005"] and ab.entree("RFA0005").get("etat") == "pret"
          and ab.a_poster("fr:amelia") == ["RFA0005"] and ab.a_poster("fr:lola") == [],
          (ab.entree("RFA0005"), ab.a_poster("fr:amelia")))
    _n_cdn = len(CDN_R)
    ab._FR_ESSAI["quand"] = 0.0
    _t_apres = ab.tour(poster2, lambda: True, dormir=lambda s: None, rattraper_fr=True,
                       telecharger_octets=_octets_r)
    check("rattrapage FR : le fil ne refait aucune model faite, il poste seulement le reel repris",
          not (_t_apres.get("rattrapage_fr") or {}).get("inscrites")
          and not (_t_apres.get("rattrapage_fr") or {}).get("traites")
          and s2_ab_am.envois[-1]["noms"] == ["RFA0005.mp4"] and len(CDN_R) == _n_cdn, _t_apres)
    check("rattrapage FR : aucun appel Apify ni HikerAPI", not INTERDITS[n_int:], INTERDITS[n_int:])
    if __import__("os").environ.get("BANGERS_FR_VOIR"):
        print("----- entête de la carte du matin (Va IG) :\n" + ENTETE_MATIN_FR)
        print("----- récapitulatif (Va IG) :\n" + RECAP_FR)
        print("----- carte 💥・all-banger-amelia :\n"
              + json.dumps(CARTE_ALL_FR, ensure_ascii=False, indent=1))
    JB.clear()
    JB.update(_JB_AVANT)

    # ===================================== 8. la vraie sonde, si ffmpeg est là --
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        vraie = TMP / "vraie.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vraie)],
                       capture_output=True, timeout=60)
        fausse = TMP / "fausse.mp4"
        fausse.write_bytes(b"<html>" + b"x" * 4000)
        check("sonde : ffprobe reconnaît une vraie vidéo et refuse une page d'erreur",
              _VRAIE_SONDE(vraie) and not _VRAIE_SONDE(fausse))
    else:
        print("     (ffmpeg absent : sonde ffprobe non vérifiée sur ce poste)")
except Exception as _e:
    import traceback
    traceback.print_exc()
    check("bangers FR : testable", False, repr(_e)[:300])
finally:
    for _k, _v in _SAV_BG.items():
        setattr(bg, _k, _v)
    for _k, _v in _SAV_AB.items():
        setattr(ab, _k, _v)
    jailbreak.list_all, jailbreak.list_accounts = _SAV_JB
    for _k, _v in _SAV_LF.items():
        setattr(liens_fr, _k, _v)
    for _m, _fn, _o in _SAV_PIEGES:
        setattr(_m, _fn, _o)
    for _n in ("vabot.bangers", "vabot.all_banger"):
        logging.getLogger(_n).removeHandler(_OREILLE)
    ab._SALON_BANGER.update(quand=0.0, ids=frozenset())
    ab._SALONS_FR.update(quand=0.0, racine="", ids={})
    ab._EN_COURS.clear()
    ab._DITS.clear()
    bg._DITS.clear()
    ab._FR_VUS.clear()
    ab._FR_ESSAI["quand"] = 0.0
    while not ab.FILE.empty():
        ab.FILE.get_nowait()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
