# -*- coding: utf-8 -*-
"""tests_outils_salons_ig.py — les outils en salons communs de TRUST INSTAGRAM,
et la page de stats dans le menu de TRUST THREADS (04/11/2026).

Propriétaire, devant les 🧰 OUTILS de YouCham : « j'aimerais bien que ça se
passe comme ça maintenant pour Instagram aussi. Tu peux garder ce qu'il y a
dans le ticket, rajoute ça », « intègre déjà les outils, soit le menu, le
spoofer, le download, le numéro » ; et du menu de Threads : « il manque les
trucs pour mes stats et tout [...] un peu comme sur Twitter ».

Ce qui est vérifié, sans réseau ni data/ :
  1. Threads : la page perso (stats_va), « 📊 Tes stats » dans le menu en
     blocs, pas dans l'accueil ; TRUST INSTAGRAM garde son menu texte ;
  2. un clic hors ticket sur TRUST INSTAGRAM sert le ticket DU CLIQUEUR ;
     sans ticket : refus en privé ; dans un ticket : comme avant ; ailleurs :
     refusé ;
  3. 📋 Ouvrir mon menu : un éphémère en blocs (lien, page, paiement, 📈, 🎬),
     sans 📤 ⬇️ 📱 ni boutons de manager, custom_id uniques ; une panne
     répond « réessaie » ;
  4. 📤 et ⬇️ des salons ouvrent les fenêtres du cliqueur ; lancés d'un salon
     commun, l'accusé dit OÙ ça arrive ; dans le ticket, il reste muet ;
     🎬 lancé du menu commun dit aussi où ;
  5. les panneaux : un bouton, sans texte ; reposés seulement s'ils ont
     disparu, jamais en double, jamais quand Discord ne répond pas, jamais
     dans un salon supprimé ;
  6. l'installation : le plan sans rien écrire (essai), puis les salons
     créés aux droits de 📱・numéro + 🌱 Débutant, rangés en tête, l'ancien
     panneau de 📋・menu modifié (rien supprimé) ; relancée, elle ne refait
     rien.

Lancement : python tests_outils_salons_ig.py
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import contenu_tickets as ct   # noqa: E402
import liens_va                # noqa: E402
import outils_tickets as ot    # noqa: E402
import stats_va                # noqa: E402
import suivi_va                # noqa: E402
import tickets_discord as tk   # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:500]}]"))


AG, TW, TH = tk.AGENCY_IG_ID, tk.TWITTER_ID, tk.THREADS_ID
VA, VA2, CHEF = "4001", "4002", "4999"
TICKET, TICKET2, COMMUN = "7001", "7002", "9100"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="outils_salons_"))
ot.SALONS_FICHIER = TMP / "outils_salons.json"
ot.ETAT = TMP / "outils_tickets.json"
ETAT = {"tickets": {f"{AG}:{VA}": {"salon": TICKET, "confirme": None, "essai": True},
                    f"{AG}:{VA2}": {"salon": TICKET2},
                    f"{TH}:{VA}": {"salon": "7301"}, f"{TW}:{VA}": {"salon": "7201"}}}
tk._etat = lambda: ETAT
tk._ecrire_etat = lambda d: None
tk.role_manager = lambda gid: "R_MANAGER"
tk.role_helper = lambda gid: "R_HELPER"
LIENS = {AG: {"numero": 160, "pseudo": "yous1m", "public_url": "https://getmysocial.com/bunnycocoyy"},
         TH: {"numero": 92, "pseudo": "fiable0010", "public_url": "https://getmysocial.com/velvetstarryy"},
         TW: {"numero": 124, "pseudo": "bigmaxm", "public_url": "https://getmysocial.com/bbycandyy"}}
liens_va.lien_de = lambda g, u: dict(LIENS.get(str(g), {})) if str(u) == VA else {}
liens_va.est_actif = lambda g, u: True
stats_va.jeton = lambda g, u: f"cle-{g}-{u}-xxxxxxxxxxxxxxxx"
suivi_va.paiement_de = lambda g, u: {"adresse": "EmXtAAAAAAAAAAAAAAAAAAAAAAAAAAz2Vt", "reseau": "solana"}
tk._emoji_texte = lambda g, r: ""


def membre(uid, chef=False):
    return {"user": {"id": uid, "username": "bob"}, "roles": ["R_MANAGER"] if chef else [],
            "permissions": "0"}


def clic(cid, uid=VA, salon=COMMUN, gid=AG, chef=False, flags=32768):
    return {"type": 3, "guild_id": gid, "channel_id": salon, "application_id": "app",
            "token": "jeton", "member": membre(uid, chef), "data": {"custom_id": cid},
            "message": {"id": "m1", "flags": flags}}


def ids(composants):
    out, pile = [], list(composants or [])
    while pile:
        c = pile.pop(0)
        if c.get("custom_id"):
            out.append(c["custom_id"])
        pile += list(c.get("components") or [])
        if isinstance(c.get("accessory"), dict):
            pile.append(c["accessory"])
    return out


def textes(composants):
    out, pile = [], list(composants or [])
    while pile:
        c = pile.pop(0)
        if c.get("type") == 10:
            out.append(c["content"])
        pile += list(c.get("components") or [])
    return out


def urls(composants):
    out, pile = [], list(composants or [])
    while pile:
        c = pile.pop(0)
        if c.get("url"):
            out.append((c.get("label"), c["url"]))
        pile += list(c.get("components") or [])
        if isinstance(c.get("accessory"), dict):
            pile.append(c["accessory"])
    return out


# ── 1. Threads : la page dans le menu ─────────────────────────────────────
print("1. TRUST THREADS : 📊 Tes stats dans le menu")
check("stats_va : Threads a sa page, à son bandeau",
      TH in stats_va.SERVEURS and stats_va.MARQUES[TH] == ("TRUST THREADS", "Threads")
      and stats_va.lien(TH, VA).startswith("https://youl4b.com/mes-stats?t="))
check("le menu en blocs de Threads porte la page, comme Twitter",
      TH in tk.MENU_PAGE_STATS and TW in tk.MENU_PAGE_STATS)
rangs_th = tk.boutons_va(VA, a_un_lien=True, gid=TH)
corps = tk._corps_menu(TH, VA, rangs_th)
check("Threads : « 📊 Tes stats » et « Voir ma page » vers sa page",
      any(t.startswith("**📊 Tes stats**") for t in textes(corps))
      and ("Voir ma page", stats_va.lien(TH, VA)) in urls(corps), textes(corps))
check("Threads : en-tête « Threads VA 92 · @fiable0010 »",
      any("Threads VA 92 · @fiable0010" in t for t in textes(corps)), textes(corps))
check("Threads : pas dans l'accueil (ligne_page_perso vide)", tk.ligne_page_perso(TH, VA) == "")
check("Threads : le menu texte (4 tickets à l'accueil-menu) la porte aussi",
      "📊 Tes stats : <" in tk._texte_menu(TH, VA))
check("TRUST INSTAGRAM : le menu texte du ticket ne change pas (pas de ligne 📊)",
      "📊" not in tk._texte_menu(AG, VA) and AG not in tk.MENU_PAGE_STATS)
check("TRUST INSTAGRAM : l'accueil garde sa ligne de page (03/11)",
      "Ta page de stats" in tk.ligne_page_perso(AG, VA))

print("1 bis. TRUST THREADS : payé aux clics (« Système de paiement par clics »)")
# l'image du propriétaire, ligne par ligne : (tranche, base, prime, total)
IMAGE = [(100, 5, 0, 5), (200, 10, 1, 11), (300, 15, 2, 17), (400, 20, 3, 23), (500, 25, 5, 30),
         (600, 30, 6, 36), (700, 35, 7, 42), (800, 40, 9, 49), (900, 45, 11, 56), (1000, 50, 13, 63),
         (1100, 55, 14, 69), (1200, 60, 16, 76), (1300, 65, 18, 83), (1400, 70, 20, 90),
         (1500, 75, 22, 97), (1600, 80, 23, 103), (1700, 85, 25, 110), (1800, 90, 27, 117),
         (1900, 95, 28, 123), (2000, 100, 30, 130), (2100, 105, 31, 136), (2200, 110, 33, 143),
         (2300, 115, 34, 149), (2400, 120, 36, 156), (2500, 125, 37, 162), (2600, 130, 39, 169),
         (2700, 135, 40, 175), (2800, 140, 42, 182), (2900, 145, 43, 188)]
check("les 29 lignes de l'image : base + prime = total", all(b + p == t for _n, b, p, t in IMAGE))
check("paie_clics rend le total de chaque tranche, du bas au haut de la tranche",
      all(stats_va.paie_clics(n) == t and stats_va.paie_clics(n + 99) == t for n, _b, _p, t in IMAGE),
      [(n, stats_va.paie_clics(n)) for n, *_r in IMAGE if stats_va.paie_clics(n) != _r[2]])
check("moins de 100 clics : 0 $ ; 3 000 et plus : 188 $ (« au dessus de 3000 tu mets 188 $ pareil »)",
      stats_va.paie_clics(0) == 0.0 and stats_va.paie_clics(99) == 0.0
      and stats_va.paie_clics(3000) == 188.0 and stats_va.paie_clics(12000) == 188.0
      and stats_va.paie_clics(None) is None)
import datetime as dt  # noqa: E402
import podium_discord as pod  # noqa: E402
_auj, _cdv = pod._aujourdhui, pod.clics_du_va
pod._aujourdhui = lambda: dt.date(2026, 11, 4)
CLICS = {(dt.date(2026, 10, 16), dt.date(2026, 10, 31)): 450, (dt.date(2026, 11, 1), dt.date(2026, 11, 4)): 230,
         (dt.date(2026, 11, 4), dt.date(2026, 11, 4)): 46, (dt.date(2026, 10, 1), dt.date(2026, 10, 15)): 3100}
DEMANDES = []


def _clics(g, u, periodes):
    DEMANDES.append((g, list(periodes)))
    return [None if p not in CLICS else (CLICS[p], CLICS[p] * 3) for p in periodes]


pod.clics_du_va = _clics
check("quinzaine précédente (450 clics) : 23 $", stats_va._gagne_clics(TH, VA, "2026-10-16", "2026-10-31") == 23.0)
check("cette quinzaine jusqu'à aujourd'hui (230) : 11 $",
      stats_va._gagne_clics(TH, VA, "2026-11-01", "2026-11-04") == 11.0)
check("deux quinzaines : 23 + 11 = 34 $", stats_va._gagne_clics(TH, VA, "2026-10-16", "2026-11-04") == 34.0)
check("aujourd'hui seul : sa part de la quinzaine (46 / 230 × 11 = 2,20 $)",
      stats_va._gagne_clics(TH, VA, "2026-11-04", "2026-11-04") == 2.2)
check("une quinzaine à 3 100 clics : 188 $, plus la suivante (23 $)",
      stats_va._gagne_clics(TH, VA, "2026-10-01", "2026-10-31") == 211.0)
check("une quinzaine illisible chez GetMySocial : rien d'inventé",
      stats_va._gagne_clics(TH, VA, "2026-09-16", "2026-10-31") is None)
check("Twitter et Instagram gardent la grille aux subs", stats_va.GRILLE_CLICS_ICI == {TH})
_sub = (stats_va._subs, stats_va._clics_infloww, stats_va._somme_mypuls, stats_va._gagne)
stats_va._subs = lambda *a: (2, [])
stats_va._clics_infloww = lambda *a: {"n": 24}
stats_va._somme_mypuls = lambda *a: 0
stats_va._gagne = lambda *a, **k: 999.0
import subs_va  # noqa: E402
subs_va.trackings_du_va = lambda g, u: [("of", "https://onlyfans.com/liasxcret/c75")]
ch = stats_va.chiffres(TH, VA, "2026-11-01", "2026-11-04")
check("la page de Threads : « Gagné » à la grille aux clics (11 $), pas aux subs",
      ch["gagne"] == 11.0 and ch["us"] == 230, ch)
check("Twitter : toujours la grille aux subs", stats_va.chiffres(TW, VA, "2026-11-01", "2026-11-04")["gagne"] == 999.0)
html = stats_va.page_html(ch, "t")
check("en-tête de colonne « Clics US·UK·CA GMS » sur Threads", "Clics US·UK·CA GMS" in html and "11,00" in html
      or "11.00" in html, html[html.find("<table"):html.find("<table") + 400])
check("Instagram garde « Clics US GMS »", "Clics US GMS" in stats_va.page_html(dict(ch, gid=AG), "t"))
stats_va._subs, stats_va._clics_infloww, stats_va._somme_mypuls, stats_va._gagne = _sub
pod._aujourdhui, pod.clics_du_va = _auj, _cdv

# ── 2. le ticket servi ────────────────────────────────────────────────────
print("2. Qui est servi, où")
t, r = ot._ticket_du_clic(clic("outk:spf:commun"))
check("salon commun : le ticket DU CLIQUEUR, marqué commun",
      t == {"gid": AG, "salon": TICKET, "uid": VA, "qui": VA, "nom": "bob", "commun": "1"} and r == "", (t, r))
t, r = ot._ticket_du_clic(clic("outk:spf:commun", uid=VA2))
check("un autre VA : SON ticket, pas celui du premier", t and t["salon"] == TICKET2 and t["uid"] == VA2, t)
t, r = ot._ticket_du_clic(clic("outk:spf:commun", uid=CHEF, chef=True))
check("sans ticket (le staff) : refus en privé", t is None and r == ot.TEXTE_SANS_TICKET, (t, r))
t, r = ot._ticket_du_clic(clic(f"outk:spf:{VA}", uid=CHEF, salon=TICKET, chef=True))
check("dans un ticket : comme avant (le manager sert le VA du ticket, pas « commun »)",
      t and t["salon"] == TICKET and t["uid"] == VA and t["qui"] == CHEF and "commun" not in t, t)
t, r = ot._ticket_du_clic(clic(f"outk:spf:{VA}", uid=VA2, salon=TICKET))
check("un autre VA dans un ticket : toujours refusé", t is None and r == ot.TEXTE_PAS_A_TOI, r)
t, r = ot._ticket_du_clic(clic("outk:spf:commun", gid=TW, salon="1"))
check("un autre serveur : refusé", t is None, r)
rep = ot.traiter(clic("outk:spf:commun", uid=CHEF, chef=True))
check("le refus part en privé", rep["type"] == 4 and rep["data"]["flags"] == 64
      and rep["data"]["content"] == ot.TEXTE_SANS_TICKET, rep)

# ── 3. 📋 Ouvrir mon menu ─────────────────────────────────────────────────
print("3. 📋 Ouvrir mon menu")
rep = ot.traiter(clic("outk:menu"))
d = rep.get("data") or {}
cids = ids(d.get("components"))
check("un éphémère en blocs (flags 64 | 32768), sans texte hors blocs",
      rep["type"] == 4 and d.get("flags") == 64 | 32768 and "content" not in d, rep)
check("en-tête « 📋 Ton menu » et « Instagram VA 160 · @yous1m »",
      textes(d["components"])[0] == "## 📋 Ton menu\n-# Instagram VA 160 · @yous1m", textes(d["components"]))
check("🔗 son lien, 📊 sa page, 💳 son paiement",
      ("Ouvrir", LIENS[AG]["public_url"]) in urls(d["components"])
      and ("Voir ma page", stats_va.lien(AG, VA)) in urls(d["components"])
      and any(x.startswith("**💳 Paiement**\nUSDC · Solana · `EmXt…z2Vt`") for x in textes(d["components"])),
      (urls(d["components"]), textes(d["components"])))
check("boutons : 💳 (Modifier), 📈 Mes stats, 🎬 Contenu — rien d'autre",
      sorted(cids) == sorted([f"usdc:set:{VA}", f"subs:total:{VA}", f"cnt:o:{VA}"]), cids)
check("ni 📤 ⬇️ 📱 (leurs salons), ni boutons de manager",
      not any(c.startswith(("outk:", "numx:", "essai:", "lien:")) for c in cids), cids)
check("chaque custom_id une seule fois (sinon Discord refuse le message)", len(cids) == len(set(cids)), cids)
check("couleur d'Instagram", d["components"][0].get("accent_color") == 0xE1306C)
check("le menu du VA du ticket quand on clique DANS un ticket (même règle que 📤)",
      "Instagram VA 160" in json.dumps(ot.traiter(clic("outk:menu", uid=CHEF, salon=TICKET, chef=True)),
                                       ensure_ascii=False))
rep = ot.traiter(clic("outk:menu", uid=CHEF, chef=True))
d2 = rep.get("data") or {}
check("sans ticket (le staff) : SON menu quand même, sans 🎬 (rien où livrer) — pas un refus",
      rep["type"] == 4 and d2.get("flags") == 64 | 32768
      and sorted(ids(d2.get("components"))) == sorted([f"usdc:set:{CHEF}", f"subs:total:{CHEF}"]), rep)
avant = tk.menu_ephemere
tk.menu_ephemere = lambda g, u, **k: (_ for _ in ()).throw(RuntimeError("fiche illisible"))
rep = ot.traiter(clic("outk:menu"))
check("une panne : « réessaie », en privé", rep["type"] == 4 and rep["data"]["content"] == ot.TEXTE_INDISPONIBLE, rep)
tk.menu_ephemere = avant
# 05/11/2026 : « c'est bon » — 📈 📤 ⬇️ 📱 quittent le ticket, 💳 et 🎬 restent
_t = set(ids(tk.boutons_va(VA, a_un_lien=True, gid=AG)))
check("le ticket perd 📈 📤 ⬇️ 📱 (ils sont dans les outils), garde 💳 et 🎬",
      {f"usdc:set:{VA}", f"cnt:o:{VA}"} <= _t
      and not {f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}", "numx:menu"} & _t, _t)

# ── 4. 📤 et ⬇️ ───────────────────────────────────────────────────────────
print("4. 📤 Spoofer et ⬇️ Download des salons")
rep = ot.traiter(clic("outk:spf:commun"))
check("📤 : la fenêtre du spoofer, au nom du cliqueur",
      rep["type"] == 9 and rep["data"]["custom_id"] == f"outk:spff:{VA}", rep)
rep = ot.traiter(clic("outk:dl:commun", uid=VA2))
check("⬇️ : la fenêtre du compte, au nom du cliqueur",
      rep["type"] == 9 and rep["data"]["custom_id"] == f"outk:dlf:{VA2}", rep)
ot._recevoir_spoofer = lambda p, t: {"type": 6}
ot._clic_option = lambda p, t, cid: {"type": 6}
f = clic(f"outk:spff:{VA}")
f["type"] = 5
rep = ot.traiter(f)
check("📤 lancé d'un salon commun : « tes versions arrivent dans <#ticket> », en privé",
      rep["type"] == 4 and rep["data"]["flags"] == 64 and f"<#{TICKET}>" in rep["data"]["content"]
      and "versions" in rep["data"]["content"], rep)
rep = ot.traiter(clic("outk:dlo:tout:30:sky.ards"))
check("⬇️ lancé d'un salon commun : « ça arrive dans <#ticket> »",
      rep["type"] == 4 and f"<#{TICKET}>" in rep["data"]["content"] and rep["data"]["content"].startswith("⬇️"), rep)
f = clic(f"outk:spff:{VA}", salon=TICKET)
f["type"] = 5
check("dans le ticket : l'accusé reste muet (les fichiers arrivent sous ses yeux)",
      ot.traiter(f) == {"type": 6} and ot.traiter(clic("outk:dlo:tout:30:sky.ards", salon=TICKET)) == {"type": 6})
FILE = {"r": ""}
ct._lancer_dans_le_ticket = lambda *a, **k: FILE["r"]
t_commun = {"gid": AG, "salon": TICKET, "uid": VA, "qui": VA, "commun": "1"}
check("🎬 lancé du menu commun : « 📥 Ça arrive dans <#ticket> »",
      ct._lancer(t_commun, None, None, "lola", "pp", None, False, 1) == f"📥 Ça arrive dans <#{TICKET}>.")
FILE["r"] = ct.TEXTE_EN_FILE.format(n=2)
check("🎬 en file : la phrase nomme le ticket",
      ct._lancer(t_commun, None, None, "lola", "pp", None, False, 1) == f"⏳ En file (2 avant), ça arrive dans <#{TICKET}>.")
FILE["r"] = ""
check("🎬 dans le ticket : rien ne change",
      ct._lancer(dict(t_commun, commun=""), None, None, "lola", "pp", None, False, 1) == ""
      and ct._lancer({k: v for k, v in t_commun.items() if k != "commun"}, None, None, "l", "pp", None, False, 1) == "")

# ── 5. les panneaux ───────────────────────────────────────────────────────
print("5. Les panneaux")
for cle, _nom, (lib, emo, cid) in ot.PANNEAUX:
    c = ot.corps_panneau(cle)
    b = c["components"][0]["components"]
    check(f"{cle} : un bouton « {emo} {lib} », sans texte",
          c["flags"] == 32768 and len(c["components"]) == 1 and len(b) == 1 and b[0]["custom_id"] == cid
          and "content" not in c)
    check(f"{cle} : son clic est servi (« {cid.split(':')[1]} »)",
          ot.traiter(clic(cid))["type"] in (4, 9))


class Faux:
    def __init__(self):
        self.appels, self.messages, self.n = [], {}, 500
        self.supprimes, self.panne_get = set(), False

    def api(self, methode, chemin, **kw):
        self.appels.append((methode, chemin, kw.get("json")))
        morceaux = chemin.strip("/").split("/")
        if morceaux[0] == "channels" and morceaux[1] in self.supprimes:
            return 404, {"code": 10003, "message": "Unknown Channel"}
        if methode == "GET" and len(morceaux) == 4 and morceaux[2] == "messages":
            if self.panne_get:
                return 503, {"message": "panne"}
            m = self.messages.get(morceaux[3])
            return (200, m) if m else (404, {"code": 10008, "message": "Unknown Message"})
        if methode == "GET" and chemin.startswith("/channels/") and "messages?" in chemin:
            return 200, [m for m in self.messages.values() if m["channel_id"] == morceaux[1]]
        if methode == "POST" and morceaux[-1] == "messages":
            self.n += 1
            m = dict(kw["json"], id=str(self.n), channel_id=morceaux[1], author={"id": "BOT"})
            self.messages[m["id"]] = m
            return 200, m
        return 200, {}


faux = Faux()
ot._api = faux.api
ASSURER = ot.assurer_panneaux
ot._noter_salon(AG, "menu", salon="9200")
ot._noter_salon(AG, "spoofer", salon="9201")
ot._noter_salon(AG, "download", salon="9202")
faux.messages["M0"] = {"id": "M0", "channel_id": "9200", "author": {"id": "BOT"},
                       "components": [{"type": 1, "components": [{"type": 2, "custom_id": "numx:menu"}]}]}
b = ot.assurer_panneaux(AG)
check("pas encore installé : rien (📋・menu porte encore l'ancien panneau), aucun appel",
      b == {"ok": [], "poses": [], "rates": [], "supprimes": []} and not faux.appels, (b, faux.appels))
ot._noter_salon(AG, "installe", quand=1)
b = ot.assurer_panneaux(AG)
check("l'ancien « Afficher le menu » encore là : pas de second panneau de menu, et c'est dit",
      "menu" not in b["poses"] and any("numx:menu" in r for r in b["rates"]), b)
faux.messages["M0"]["components"] = [ot.corps_panneau("menu")["components"][0]]
check("premier passage : les deux panneaux posés, ids notés",
      sorted(b["poses"]) == ["download", "spoofer"]
      and ot._etat_salons()[AG]["spoofer"].get("panneau"), (b, ot._etat_salons()))
n = len([a for a in faux.appels if a[0] == "POST"])
b = ot.assurer_panneaux(AG)
check("deuxième passage : rien de reposté (lus par leur id)",
      len([a for a in faux.appels if a[0] == "POST"]) == n and sorted(b["ok"]) == ["download", "menu", "spoofer"], b)
mid = ot._etat_salons()[AG]["spoofer"]["panneau"]
del faux.messages[mid]
b = ot.assurer_panneaux(AG)
check("un panneau effacé à la main : reposé, une fois",
      b["poses"] == ["spoofer"] and ot._etat_salons()[AG]["spoofer"]["panneau"] != mid, b)
faux.panne_get = True
n = len([a for a in faux.appels if a[0] == "POST"])
b = ot.assurer_panneaux(AG)
check("Discord ne répond pas : rien de reposté (un second panneau vaut moins)",
      len([a for a in faux.appels if a[0] == "POST"]) == n and len(b["rates"]) == 3, b)
faux.panne_get = False
d = ot._etat_salons()
d[AG]["download"].pop("panneau")
import safe_json  # noqa: E402
safe_json.write(ot.SALONS_FICHIER, d)
b = ot.assurer_panneaux(AG)
check("fiche perdue : le panneau retrouvé dans le salon, pas un second",
      "download" in b["ok"] and not b["poses"] and ot._etat_salons()[AG]["download"].get("panneau"), b)
faux.supprimes.add("9202")
n = len([a for a in faux.appels if a[0] == "POST"])
b = ot.assurer_panneaux(AG)
check("salon supprimé à la main : jamais refait, rien posté",
      b["supprimes"] == ["download"] and len([a for a in faux.appels if a[0] == "POST"]) == n, b)
check("le démarrage repose les panneaux (après la reprise)",
      "_fond(_au_demarrage)" in (BOT / "outils_tickets.py").read_text())
APPELS = []
ot._dormir = lambda s: APPELS.append(("dormir", s))
ot.prevenir_interrompus = lambda: (_ for _ in ()).throw(RuntimeError("état illisible"))
ot.assurer_panneaux = lambda g: APPELS.append(("panneaux", g))
ot._au_demarrage()
check("au démarrage : une reprise qui lève n'empêche pas les panneaux",
      APPELS == [("dormir", ot.REPRISE_DELAI_S), ("panneaux", AG)], APPELS)
ot.assurer_panneaux = ASSURER

# ── 6. l'installation ─────────────────────────────────────────────────────
print("6. L'installation")
ESSAI_R, DEB_R, CONF_R, MAN_R = "R_ESSAI", "R_DEB", "R_CONF", "R_MAN"
tk.role_essai = lambda g: ESSAI_R
tk.role_debutant = lambda g: DEB_R
DROITS_NUM = [{"id": ESSAI_R, "type": 0, "allow": "1049600", "deny": "377957124096"},
              {"id": CONF_R, "type": 0, "allow": "1049600", "deny": "377957124096"},
              {"id": MAN_R, "type": 0, "allow": "377958173696", "deny": "0"},
              {"id": AG, "type": 0, "allow": "0", "deny": "377958173696"},
              {"id": "REM", "type": 1, "allow": "379904", "deny": "0"}]


class Serveur(Faux):
    def __init__(self):
        super().__init__()
        self.salons = [{"id": "C", "type": 4, "name": "🧰 OUTILS INSTAGRAM", "position": 4},
                       {"id": "A1", "type": 0, "name": "🧹・nettoyage-vidéo", "parent_id": "C", "position": 0},
                       {"id": "A2", "type": 0, "name": "📸・story-cta", "parent_id": "C", "position": 1},
                       {"id": "MENU", "type": 0, "name": "📋・menu", "parent_id": "C", "position": 2,
                        "permission_overwrites": [o for o in DROITS_NUM if o["type"] == 0]},
                       {"id": "A3", "type": 0, "name": "📚・ressources", "parent_id": "C", "position": 3},
                       {"id": "NUM", "type": 0, "name": "📱・numéro", "parent_id": "C", "position": 4,
                        "permission_overwrites": DROITS_NUM}]
        self.messages = {"OLD": {"id": "OLD", "channel_id": "MENU", "author": {"id": "BOT"}, "flags": 32768,
                                 "components": [{"type": 1, "components": [
                                     {"type": 2, "label": "Afficher le menu", "custom_id": "numx:menu"}]}]},
                         "NUMUS": {"id": "NUMUS", "channel_id": "MENU", "author": {"id": "AUTRE"},
                                   "components": [{"type": 1, "components": [
                                       {"type": 2, "label": "Prendre un numéro",
                                        "custom_id": "sms:prendre:ig:187"}]}]}}

    def api(self, methode, chemin, **kw):
        if methode == "GET" and chemin == f"/guilds/{AG}/channels":
            self.appels.append((methode, chemin, None))
            return 200, [dict(c) for c in self.salons]
        if methode == "GET" and chemin == "/users/@me":
            return 200, {"id": "BOT"}
        if methode == "POST" and chemin == f"/guilds/{AG}/channels":
            self.appels.append((methode, chemin, kw.get("json")))
            self.n += 1
            c = dict(kw["json"], id=f"NEUF{self.n}")
            self.salons.append(c)
            return 201, c
        if methode == "PUT" and "/permissions/" in chemin:
            self.appels.append((methode, chemin, kw.get("json")))
            cid, rid = chemin.split("/")[2], chemin.split("/")[4]
            for c in self.salons:
                if c["id"] == cid:
                    c.setdefault("permission_overwrites", []).append(dict(kw["json"], id=rid))
            return 204, None
        if methode == "PATCH" and "/messages/" in chemin:
            self.appels.append((methode, chemin, kw.get("json")))
            mid = chemin.rsplit("/", 1)[1]
            self.messages[mid] = dict(self.messages[mid], **kw["json"])
            return 200, self.messages[mid]
        if methode == "PATCH" and chemin == f"/guilds/{AG}/channels":
            self.appels.append((methode, chemin, kw.get("json")))
            for p in kw["json"]:
                for c in self.salons:
                    if c["id"] == p["id"]:
                        c["position"] = p["position"]
            return 204, None
        return super().api(methode, chemin, **kw)


ot.SALONS_FICHIER = TMP / "outils_salons_2.json"
srv = Serveur()
ot._api = srv.api
plan = ot.installer_salons(AG, essai=True)
ecrits = [a for a in srv.appels if a[0] != "GET"]
check("essai : le plan, et rien d'écrit", not ecrits and not ot._etat_salons(), ecrits)
check("essai : créer 📤・spoofer et ⬇️・download, 🌱 dans 📋・menu et 📱・numéro, ranger, modifier l'ancien menu",
      plan["plan"][:2] == ["🌱 Débutant dans 📋・menu", "créer 📤・spoofer"]
      and "créer ⬇️・download" in plan["plan"] and "🌱 Débutant dans 📱・numéro" in plan["plan"]
      and any(p.startswith("ranger") for p in plan["plan"])
      and any("Ouvrir mon menu" in p for p in plan["plan"]), plan)
r = ot.installer_salons(AG, essai=False)
check("installation : aucun raté", not r["rates"], r)
neufs = [c for c in srv.salons if c["id"].startswith("NEUF")]
check("deux salons créés, dans la catégorie, à leurs noms",
      sorted(c["name"] for c in neufs) == sorted(["📤・spoofer", "⬇️・download"])
      and all(c["parent_id"] == "C" for c in neufs), neufs)
dr = {o["id"]: o for o in neufs[0]["permission_overwrites"]}
check("leurs droits : ceux de 📱・numéro (rôles), + 🌱 Débutant comme 🧪 Essai, + le bot ; pas Rem",
      dr[ESSAI_R]["deny"] == "377957124096" and dr[DEB_R]["allow"] == "1049600"
      and dr[DEB_R]["deny"] == "377957124096" and dr[AG]["deny"] == "377958173696"
      and "REM" not in dr and dr["BOT"]["type"] == 1, dr)
check("🌱 Débutant ajouté à 📋・menu et à 📱・numéro (il n'y voyait rien)",
      all(any(o["id"] == DEB_R for o in c.get("permission_overwrites") or [])
          for c in srv.salons if c["id"] in ("MENU", "NUM")))
ordre = [c["name"] for c in sorted([c for c in srv.salons if c.get("parent_id") == "C"],
                                   key=lambda c: (c["position"], c["id"]))]
check("rangés en tête : menu · spoofer · download · numéro, les autres ensuite, dans leur ordre",
      ordre == ["📋・menu", "📤・spoofer", "⬇️・download", "📱・numéro", "🧹・nettoyage-vidéo",
                "📸・story-cta", "📚・ressources"], ordre)
check("l'ancien panneau de 📋・menu devient « Ouvrir mon menu » (modifié, rien supprimé)",
      ids(srv.messages["OLD"]["components"]) == ["outk:menu"]
      and ot._etat_salons()[AG]["menu"]["panneau"] == "OLD"
      and not any(a[0] == "DELETE" for a in srv.appels), srv.messages["OLD"])
check("le message d'un autre bot dans 📋・menu n'est pas touché",
      ids(srv.messages["NUMUS"]["components"]) == ["sms:prendre:ig:187"])
check("les panneaux 📤 et ⬇️ posés dans leurs salons",
      {m["channel_id"]: ids(m["components"]) for m in srv.messages.values() if m["channel_id"].startswith("NEUF")}
      == {c["id"]: [ot.corps_panneau("spoofer" if "spoofer" in c["name"] else "download")["components"][0]
                    ["components"][0]["custom_id"]] for c in neufs})
n = len([a for a in srv.appels if a[0] in ("POST", "PUT") or (a[0] == "PATCH" and "/messages/" in a[1])])
r = ot.installer_salons(AG, essai=False)
check("relancée : ni salon, ni droit, ni panneau de plus",
      len([a for a in srv.appels if a[0] in ("POST", "PUT") or (a[0] == "PATCH" and "/messages/" in a[1])]) == n
      and not r["rates"], (r, srv.appels[-6:]))


print("7. Les cas de la relecture")
# un salon renommé à la main : repris par son id, pas recréé
for c in srv.salons:
    if c["name"] == "⬇️・download":
        c["name"] = "⬇️・telechargement"
n_salons = len(srv.salons)
r = ot.installer_salons(AG, essai=False)
check("salon renommé : repris par son id à la relance, aucun second ⬇️",
      len(srv.salons) == n_salons and not r["rates"], r)
# la fiche perdue (data/ refait), l'installation notée : retrouvés par leur nom
d = ot._etat_salons()
for cle in ("menu", "spoofer"):
    d[AG][cle].pop("salon", None)
safe_json.write(ot.SALONS_FICHIER, d)
n_post = len([a for a in srv.appels if a[0] == "POST"])
b = ot.assurer_panneaux(AG)
check("fiche sans les ids : salons retrouvés par leur nom, notés, aucun panneau en double",
      ot._etat_salons()[AG]["menu"].get("salon") == "MENU" and ot._etat_salons()[AG]["spoofer"].get("salon")
      and len([a for a in srv.appels if a[0] == "POST"]) == n_post and not b["rates"], (b, ot._etat_salons()))
# Débutant introuvable / bot inconnu : rien d'écrit
ot.SALONS_FICHIER = TMP / "outils_salons_3.json"
for nom_cas, regle in (("rôle 🌱 Débutant introuvable", lambda: setattr(tk, "role_debutant", lambda g: "")),
                       ("identité du bot illisible", None)):
    srv2 = Serveur()
    if regle:
        regle()
    else:
        _api2 = srv2.api
        srv2.api = lambda m, c, **kw: (503, {"message": "panne"}) if c == "/users/@me" else _api2(m, c, **kw)
    ot._api = srv2.api
    r = ot.installer_salons(AG, essai=False)
    ecrits = [a for a in srv2.appels if a[0] != "GET"]
    check(f"{nom_cas} : dit dans les ratés, rien d'écrit avant", r["rates"] and not ecrits
          and any(nom_cas.split(" ")[0] in x for x in r["rates"]), (r, ecrits))
    tk.role_debutant = lambda g: DEB_R
# la modification de l'ancien panneau refusée : pas de second panneau à côté
ot.SALONS_FICHIER = TMP / "outils_salons_4.json"
srv3 = Serveur()
_api3 = srv3.api
srv3.api = lambda m, c, **kw: ((503, {"message": "panne"}) if m == "PATCH" and "/messages/OLD" in c
                               else _api3(m, c, **kw))
ot._api = srv3.api
r = ot.installer_salons(AG, essai=False)
menus = [m for m in srv3.messages.values() if m["channel_id"] == "MENU" and "outk:menu" in ids(m.get("components"))]
check("ancien panneau non modifiable (503) : dit, et aucun « Ouvrir mon menu » posé à côté",
      not menus and any("numx:menu" in x for x in r["rates"]), (r, menus))
srv3.api = _api3
ot._api = srv3.api
srv3.messages["NEW"] = {"id": "NEW", "channel_id": "MENU", "author": {"id": "BOT"},
                        "components": [ot.corps_panneau("menu")["components"][0]]}
r = ot.installer_salons(AG, essai=False)
check("ancien et neuf côte à côte : rien supprimé, c'est dit",
      "OLD" in srv3.messages and any("encore à côté" in x for x in r["rates"])
      and not any(a[0] == "DELETE" for a in srv3.appels), r)
# numeros_x_discord ne repose plus son panneau dans 📋・menu repris
import numeros_x_discord as nx  # noqa: E402
import verif_discord as vd  # noqa: E402
import contextlib  # noqa: E402
_vd = (vd.api, vd.sur_serveur, vd.bot_du_serveur)
APPELS_NX = []
vd.sur_serveur = lambda g: contextlib.nullcontext()
vd.bot_du_serveur = lambda g: {"app_id": "BOT"}
vd.api = lambda m, c, **kw: (APPELS_NX.append((m, c)), (200, [srv3.messages["NEW"]]) if m == "GET" else (200, {}))[1]
rep = nx.poser_panneau(AG)
check("« numeros_x_discord poser agency » : rien posé dans le 📋・menu repris",
      "rien posé" in rep and [a for a in APPELS_NX if a[0] != "GET"] == [], (rep, APPELS_NX))
vd.api, vd.sur_serveur, vd.bot_du_serveur = _vd


print("8. Le menu du ticket Instagram en blocs (« pas très carré »)")
rangs_ag = tk.boutons_va(VA, a_un_lien=True, gid=AG)
corps_ag = tk._corps_menu(AG, VA, rangs_ag)
cids_ag = ids(corps_ag)
check("TRUST INSTAGRAM : le menu du ticket est en blocs (MENU_V2), Twitter et Threads aussi",
      {AG, TW, TH} <= tk.MENU_V2)
check("en-tête « Instagram VA 160 · @yous1m », 🔗 lien, 📊 page, 💳 paiement",
      textes(corps_ag)[0] == "## 📋 Ton menu\n-# Instagram VA 160 · @yous1m"
      and ("Ouvrir", LIENS[AG]["public_url"]) in urls(corps_ag)
      and ("Voir ma page", stats_va.lien(AG, VA)) in urls(corps_ag)
      and any(x.startswith("**💳 Paiement**") for x in textes(corps_ag)), (textes(corps_ag), urls(corps_ag)))
check("les boutons du ticket y sont (💳 🎬 et ceux des managers, plus 📈 📤 ⬇️ 📱), chacun une fois",
      {f"usdc:set:{VA}", f"cnt:o:{VA}"} <= set(cids_ag)
      and not {f"subs:total:{VA}", f"outk:spf:{VA}", f"outk:dl:{VA}", "numx:menu"} & set(cids_ag)
      and any(c.startswith(("essai:", "lien:")) for c in cids_ag)
      and len(cids_ag) == len(set(cids_ag)), cids_ag)


def compter(cs):
    n, pile = 0, list(cs)
    while pile:
        c = pile.pop()
        n += 1
        pile += list(c.get("components") or [])
        if isinstance(c.get("accessory"), dict):
            pile.append(c["accessory"])
    return n


check("sous les 40 composants d'un message (Discord refuse au-delà)", compter(corps_ag) <= 40, compter(corps_ag))
check("aucune rangée de plus de 5 boutons",
      all(len(c.get("components") or []) <= 5 for c in corps_ag[0]["components"] if c.get("type") == 1))
check("le 💳 garde la fenêtre Solana d'Instagram (pas le choix du réseau)", AG not in tk.USDC_RESEAUX_ICI)
MAJ = []
tk._maj_menu_v2 = lambda g, u, *a, **k: MAJ.append((g, u)) or 200
tk._EN_FOND = lambda f: f()
tk._recevoir_adresse_sans_menu = lambda p: {"type": 4, "data": {"content": "✅ Adresse enregistrée : `Em…`"}}
f = clic(f"usdc:form:{VA}")
f["type"] = 5
tk._recevoir_adresse(f)
check("une adresse enregistrée : la section 💳 du menu est remise à jour aussitôt", MAJ == [(AG, VA)], MAJ)
tk._recevoir_adresse_sans_menu = lambda p: {"type": 4, "data": {"content": "✕ adresse invalide"}}
tk._recevoir_adresse(f)
check("une adresse refusée : rien n'est réécrit", MAJ == [(AG, VA)], MAJ)


print("9. Un lien désactivé garde sa page de stats (« mets un lien mais désactivé »)")
LIENS[TH] = dict(LIENS[TH], actif=False)
corps_off = tk._corps_menu(TH, VA, tk.boutons_va(VA, a_un_lien=True, gid=TH, lien_actif=False))
check("Threads, lien coupé : « 🔗 Ton lien — 🚫 Désactivé », sans son adresse ni « Ouvrir »",
      "**🔗 Ton lien**\n🚫 Désactivé pour le moment" in textes(corps_off)
      and not any(u == LIENS[TH]["public_url"] for _l, u in urls(corps_off))
      and LIENS[TH]["public_url"] not in json.dumps(corps_off), textes(corps_off))
check("… et « 📊 Tes stats » / « Voir ma page » toujours là",
      ("Voir ma page", stats_va.lien(TH, VA)) in urls(corps_off), urls(corps_off))
check("le menu texte aussi : désactivé, puis la page",
      "🔗 🚫 Désactivé pour le moment" in tk._texte_menu(TH, VA) and "📊 Tes stats : <" in tk._texte_menu(TH, VA)
      and LIENS[TH]["public_url"] not in tk._texte_menu(TH, VA), tk._texte_menu(TH, VA))
LIENS[TH] = {k: v for k, v in LIENS[TH].items() if k != "actif"}
ETAT["tickets"][f"{TH}:{VA}"]["parti"] = {"quand": 1}
check("un VA parti : ni lien ni page", not any(l == "Voir ma page" for l, _u in urls(
    tk._corps_menu(TH, VA, tk.boutons_va(VA, a_un_lien=True, gid=TH)))))
ETAT["tickets"][f"{TH}:{VA}"].pop("parti")
check("lien actif : comme avant (« Ouvrir » vers son lien)",
      ("Ouvrir", LIENS[TH]["public_url"]) in urls(tk._corps_menu(TH, VA, tk.boutons_va(VA, a_un_lien=True, gid=TH))))

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
