# -*- coding: utf-8 -*-
"""tests_bangers_fr.py — bangers et all-banger du serveur FR « Va IG ».

Demande du propriétaire (03/10/2026) : « banger et all-banger comme sur les
US » pour le marché FR —
  - un salon 💥・banger-<model> PAR model, et son 💥・all-banger-<model>
    (pas de all-banger commun : « pas de allbanger dans va ig ») ;
  - Youl4b garde SEULEMENT Jessye, exactement comme avant ;
  - seuls comptent les comptes Instagram des VA du Discord FR ;
  - aucun Apify pour le FR (le propriétaire le refuse) : relevé du scrape
    déjà payé et téléchargement CDN gratuit ;
  - même rythme (9 h Paris, la veille) et même seuil que les US.

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
    check("config : six models FR, chacune son salon, son sous-dossier, sans Apify",
          [s["identite"] for s in bg.salons_fr()] == ["amelia", "emma", "sarah", "julia", "lola", "alicia"]
          and all(s["guild_id"] == 1505418484052394004 and not s["apify"] and s["discord_seulement"]
                  and s["dossier"] == bg.DOSSIER_JOURNEES / "fr" / s["identite"]
                  and s["channel_id"] == bg.SALONS_FR[s["identite"]] for s in bg.salons_fr()))
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
    sel_us = [f["shortcode"] for f in bg.selection_jour(bg.toutes(), 10000, JOUR)]
    check("sélection US : inchangée, Jessye seule", sel_us == ["JESSY01"], sel_us)
    sel_am = [f["shortcode"] for f in bg.selection_jour(bg.toutes(), 10000, JOUR, identite="amelia")]
    check("sélection FR : la veille, au-dessus du seuil, la model seule",
          sel_am == ["FRAME02", "FRAME01", "FRAME05"], sel_am)

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
    check("US : journal au premier niveau, Jessye seule, terminé",
          b_us.get("termine") and set(j_us["reels"]) == {"JESSY01"} and us_pub == ["JESSY01"]
          and "salon" not in j_us and "hors_discord" not in j_us, b_us)
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
        r = bg.preparer_fiches_gratuit(fiches, "amelia")
        for f in r.values():
            f["discord_id"] = gerants.get(f.get("va"), "")
        return r

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
    check("FR : journal dans son sous-dossier fr/amelia, terminé",
          p_fr.exists() and b_fr.get("termine") and j_fr.get("salon") == "fr:amelia", b_fr)
    check("FR : seuls les comptes des VA Discord, la model seule",
          set(j_fr.get("reels") or {}) == {"FRAME01", "FRAME05"} and fr_pub == ["FRAME01", "FRAME05"],
          (sorted(j_fr.get("reels") or {}), fr_pub))
    check("FR : le reel d'un compte sans VA Discord est écarté, COMPTÉ et nommé",
          [h["shortcode"] for h in j_fr.get("hors_discord") or []] == ["FRAME02"]
          and any("écarté" in l and "@amelia.site" in l for l in JOURNAL), j_fr.get("hors_discord"))
    check("FR : Jessye n'est pas dans le salon d'Amélia, ni Amélia chez Jessye",
          "JESSY01" not in (j_fr.get("reels") or {})
          and not ({"FRAME01", "FRAME05"} & set(json.loads((bg.DOSSIER_JOURNEES / (JOUR + ".json"))
                                                           .read_text(encoding="utf-8"))["reels"]))
          and not any("jessy.one" in t for e in s_am.envois for t in contenus(e)))
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
    cartes = [e for e in s_am.envois if any("### @" in t for t in contenus(e))]
    c1 = contenus(cartes[0]) if cartes else []
    entete = c1[0] if c1 else ""
    check("FR : la carte dit « Amélia · Bangers du », jamais Jessye",
          "Amélia · Bangers du " in entete and "Jessye" not in json.dumps(cartes, ensure_ascii=False,
                                                                          default=str), entete)
    check("FR : la carte nomme le gérant sans le notifier",
          "<@555> · bob" in entete and cartes[0]["am"].to_dict().get("parse") == [], entete)
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
    check("FR : récapitulatif « · Amélia », liens vers le salon FR, une mention",
          " · Amélia" in r1 and f"/channels/{bg.GUILD_FR}/880001/" in r1
          and str(bg.GUILD_ID) not in r1 and "<@555>" in r1, r1[:200])
    check("FR : le récapitulatif DIT combien de reels ont été écartés (comptes hors Discord)",
          "1 reel au-dessus du seuil écarté" in r1 and "@amelia.site" not in r1, r1[-300:])
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
          and fr_pub == ["FRAME01", "FRAME05"])
    try:
        bg.publier_journee(JOUR, _prep_fr, _pub_fr, _rec_fr, salon=EMMA, admis=None)
        _e = ""
    except ValueError as e:
        _e = str(e)
    check("FR : sans la liste des comptes Discord, rien n'est figé",
          "Comptes des VA Discord inconnus" in _e
          and not (bg.DOSSIER_JOURNEES / "fr" / "emma" / (JOUR + ".json")).exists(), _e)

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
          and "bg.comptes_admis(s[\"identite\"], membres)" in _cyc
          and "salon=s, admis=admis" in _cyc)

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
        "FRAME02": {"etat": "pret", "poste_le": HIER},       # écarté le matin : jamais paru
        "HORS001": {"etat": "pret", "poste_le": HIER}}})
    perim_us = ab.passes_par_salon_banger(force=True)
    perim_fr = ab.passes_par_salons_fr(force=True)
    check("all-banger : le périmètre US ne voit pas les journaux FR",
          "JESSY01" in perim_us and not ({"FRAME01", "FRAME05"} & set(perim_us)), sorted(perim_us))
    check("all-banger : le périmètre FR = les journaux FR « envoye », avec leur model",
          perim_fr == {"FRAME01": "amelia", "FRAME05": "amelia"}, perim_fr)
    check("all-banger : a_poster() (US) inchangé, a_poster('fr:amelia') a les siens",
          ab.a_poster() == ["JESSY01"] and ab.a_poster("fr:amelia") == ["FRAME01", "FRAME05"]
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
          and [e["noms"] for e in s_allfr.envois] == [["FRAME01.mp4"], ["FRAME05.mp4"]]
          and b7["envoyes"] == 3, b7)
    check("all-banger : chaque entrée garde son marché et son salon",
          (reg["FRAME01"].get("marche"), reg["FRAME01"].get("guild_id"), reg["FRAME01"].get("channel_id"))
          == ("fr:amelia", bg.GUILD_FR, 880002)
          and not s_vieux_all.envois
          and reg["JESSY01"].get("channel_id") == 1553240454961569832
          and reg["JESSY01"].get("marche") == "us")
    check("all-banger : un banger jamais paru le matin ne part nulle part",
          reg["FRAME02"]["etat"] == "pret" and reg["HORS001"]["etat"] == "pret")

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
    for _m, _fn, _o in _SAV_PIEGES:
        setattr(_m, _fn, _o)
    for _n in ("vabot.bangers", "vabot.all_banger"):
        logging.getLogger(_n).removeHandler(_OREILLE)
    ab._SALON_BANGER.update(quand=0.0, ids=frozenset())
    ab._SALONS_FR.update(quand=0.0, racine="", ids={})
    ab._EN_COURS.clear()
    ab._DITS.clear()
    bg._DITS.clear()
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
