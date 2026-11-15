"""TRUST TWITTER en pages, comme TRUST INSTAGRAM (03/11/2026).

Propriétaire : « mets aussi des landing pages pour Twitter comme pour IG ».
Les liens existants ont été passés en page ce soir-là ; ce fichier prouve que
les liens NEUFS naissent en page, sans réseau :
  1. espace(Twitter) : gabarit = la page modèle, landing, et les copies des
     branches de l'A/B partent de l'ancien gabarit DIRECT (source_variante).
  2. creer_gms sur Twitter : copie de la page sans adresse, puis le tracking
     du VA posé sur son bouton OnlyFans (comme Agency).
  3. Threads et Agency ne bougent pas.

04/11/2026, « urgent » : « repasse toutes les pages Twitter en lien direct,
pas de landing page » : GABARIT_PAGE_TWITTER vide, un lien neuf naît direct ;
les pages restent possibles derrière l'interrupteur (1. et 2.).

15/11/2026 : « les liens directs des VA, tu mets juste des landing pages à la
place », sur les trois TRUST, au look Général. Les liens existants de Twitter
et de Threads ont été repassés en page ce jour-là ; ici :
  0. par défaut, un lien neuf naît en page sur Twitter ET sur Threads, et
     l'interrupteur vide ramène le lien direct ;
  2c. un lien neuf de Threads copie la page de SON équipe ; sans tracking,
      la page garde le bouton du gabarit (elle n'est pas coupée) ;
  4. rebrancher un lien qui est une page pose le tracking sur son bouton —
     jamais typeLink « directlink », qui en referait un lien direct.

Lancer depuis la racine du dépôt : python tests_twitter_pages.py
"""
from __future__ import annotations

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

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


import liens_va as lv     # noqa: E402
import gms                # noqa: E402
# Le renvoi des autres pays vers le compte de base, tel qu'il reviendrait :
# coupé par défaut le 11/11/2026 (liens_va.FILTRE_PAYS) ; le défaut est
# vérifié par tests_sans_filtres_trust.py.
lv.FILTRE_PAYS = True

DIRECT = "lnk_ancien_direct"
lv.config = lambda: {"gabarit": DIRECT, "equipe": "tm_twitter", "modele": "Lia"}

print("0. Par défaut, depuis le 15/11 : une page, sur Twitter et sur Threads")
PAGE_TW, PAGE_TH = lv.GABARIT_PAGE_TWITTER, lv.GABARIT_PAGE_THREADS
e0, t0 = lv.espace(lv.TWITTER_ID), lv.espace(lv.THREADS_ID)
check("les deux gabarits de page sont posés, un par équipe",
      PAGE_TW.startswith("lnk_") and PAGE_TH.startswith("lnk_") and PAGE_TW != PAGE_TH, (PAGE_TW, PAGE_TH))
check("Twitter : un lien neuf copie la page, l'ancien gabarit direct reste la source des branches d'A/B",
      e0["gabarit"] == PAGE_TW and e0.get("landing") is True and e0.get("source_variante") == DIRECT, e0)
check("Threads : un lien neuf copie la page de SON équipe, emythreadsb reste la source des branches d'A/B",
      t0["gabarit"] == PAGE_TH and t0.get("landing") is True
      and t0["equipe"] == lv.ESPACE_THREADS["equipe"]
      and t0.get("source_variante") == lv.ESPACE_THREADS["source_variante"], t0)
# Lia seule, sans la marge des 30 % depuis le 10/11/2026 : ni Seren ni « Base Lia »
check("… Lia seule, sans marge : ni Seren ni 70/30", e0.get("variante") is None
      and e0.get("base_seule") is None and t0.get("variante") is None and t0.get("base_seule") is None, (e0, t0))
lv.GABARIT_PAGE_TWITTER = lv.GABARIT_PAGE_THREADS = ""
e0, t0 = lv.espace(lv.TWITTER_ID), lv.espace(lv.THREADS_ID)
check("interrupteurs vides : le lien direct revient, sur les deux serveurs",
      e0["gabarit"] == DIRECT and not e0.get("landing")
      and t0["gabarit"] == lv.ESPACE_THREADS["gabarit"] and not t0.get("landing"), (e0, t0))
lv.GABARIT_PAGE_TWITTER = "lnk_page_modele"

print("1. L'espace Twitter, interrupteur des pages ouvert")
e = lv.espace(lv.TWITTER_ID)
check("gabarit = la page modèle, en page", e["gabarit"] == lv.GABARIT_PAGE_TWITTER and e.get("landing") is True, e)
check("les copies des branches de l'A/B partent de l'ancien gabarit direct", e.get("source_variante") == DIRECT, e)
check("espace() sans serveur = Twitter, pareil", lv.espace("")["gabarit"] == lv.GABARIT_PAGE_TWITTER)
check("Lia seule, sans marge, inchangée par les pages", e.get("variante") is None
      and e.get("base_seule") is None, e)

print("2. Un lien neuf sur Twitter")
APPELS = []


def _dup(src, sc, nom, url="", team=None):
    APPELS.append(("dup", src, url, team))
    return {"ok": True, "link": {"id": "lnk_neuf", "shortcode": sc}}


def _tool(nom, args):
    APPELS.append((nom, args.get("link_id")))
    if nom == "get_link":
        return {"ok": True, "data": {"buttons": [{"label": "“exclusive” stuff lol", "url": BOUTONS[0]}]}}
    if nom == "update_link":
        BOUTONS[0] = args["buttons"][0]["url"]
        return {"ok": True}
    return {"ok": True}


BOUTONS = ["https://onlyfans.com/liasxcret"]
_d, _t = gms.duplicate_link, gms._call_tool
gms.duplicate_link, gms._call_tool = _dup, _tool
try:
    r = lv.creer_gms("Twitter VA 200 @essai", "https://onlyfans.com/liasxcret/c999", lv.TWITTER_ID)
finally:
    gms.duplicate_link, gms._call_tool = _d, _t
dups = [a for a in APPELS if a[0] == "dup"]
check("copie de la PAGE modèle, sans adresse (une page n'en prend pas)",
      dups and dups[0][1] == lv.GABARIT_PAGE_TWITTER and dups[0][2] == "", dups)
check("le tracking du VA posé sur le bouton OnlyFans", r.get("ok") and BOUTONS[0] == "https://onlyfans.com/liasxcret/c999",
      (r, BOUTONS))

print("2b. Bénin et Madagascar gardent le tracking, comme les US (03/11)")
geo = lv.regles_pays("https://onlyfans.com/liasxcret")
codes = {x["country_code"] for x in geo}
check("BJ et MG ne sont pas renvoyés vers le compte de base, les US non plus ; FR oui",
      not ({"BJ", "MG", "US", "CA", "AU", "GB", "NZ", "IE"} & codes) and "FR" in codes and len(geo) == 248, len(geo))

print("2c. Un lien neuf sur Threads")
lv.GABARIT_PAGE_THREADS = "lnk_page_threads"
APPELS.clear()
BOUTONS[0] = "https://onlyfans.com/liasxcret"
COUPES = []
_d, _t, _c = gms.duplicate_link, gms._call_tool, gms.disable_link
gms.duplicate_link, gms._call_tool = _dup, _tool
gms.disable_link = lambda lid: COUPES.append(lid) or {"ok": True}
try:
    r = lv.creer_gms("Threads VA 201 @essai", "https://onlyfans.com/liasxcret/c998", lv.THREADS_ID)
    dups = [a for a in APPELS if a[0] == "dup"]
    check("copie de la page de l'équipe Threads, sans adresse",
          dups and dups[0][1] == "lnk_page_threads" and dups[0][2] == ""
          and dups[0][3] == lv.ESPACE_THREADS["equipe"], dups)
    check("le tracking du VA posé sur le bouton OnlyFans", r.get("ok")
          and BOUTONS[0] == "https://onlyfans.com/liasxcret/c998" and not COUPES, (r, BOUTONS, COUPES))
    # sans tracking (MyPuls fermé) : la page garde le bouton du gabarit. Avant
    # le 15/11, _poser_tracking refusait (« lien ou tracking manquant ») et la
    # copie était coupée : le VA n'avait pas de lien.
    APPELS.clear()
    BOUTONS[0] = "https://onlyfans.com/liasxcret"
    r = lv.creer_gms("Threads VA 202 @essai", "", lv.THREADS_ID)
    check("sans tracking : la page est gardée telle quelle, ni réécrite ni coupée",
          r.get("ok") and r.get("id") == "lnk_neuf" and not COUPES
          and not [a for a in APPELS if a[0] == "update_link"]
          and BOUTONS[0] == "https://onlyfans.com/liasxcret", (r, APPELS, COUPES))
finally:
    gms.duplicate_link, gms._call_tool, gms.disable_link = _d, _t, _c

print("3. Agency ne bouge pas, et chaque serveur a sa page")
check("Threads : pas la page Twitter", lv.espace(lv.THREADS_ID).get("gabarit") != lv.GABARIT_PAGE_TWITTER)
check("Agency : sa page à elle", lv.espace(lv.AGENCY_IG_ID).get("gabarit") == lv.ESPACE_AGENCY_IG["gabarit"])

print("4. Rebrancher un lien qui est une page")
ETAT = {"liens": {f"{lv.TWITTER_ID}:7": {"shortcode": "lilyy", "link_id": "lnk_page", "numero": 7,
                                         "pseudo": "essai", "public_url": "https://getmysocial.com/lilyy",
                                         "tracking": ""}}}
ENVOIS = []
PAGE = {"type": "landing", "buttons": [{"label": "MY FREE 0F", "url": "https://onlyfans.com/liasxcret"},
                                       {"label": "MY TELEGRAM", "url": "https://t.me/m/x"}]}


def _tool4(nom, args):
    if nom == "get_link":
        return {"ok": True, "data": dict(PAGE, buttons=[dict(b) for b in PAGE["buttons"] or []] or None)}
    if nom == "update_link":
        ENVOIS.append(args)
        if args.get("buttons"):
            PAGE["buttons"] = [dict(b) for b in args["buttons"]]
        if args.get("typeLink") == "directlink":
            PAGE.update(type="directlink", buttons=None)
        return {"ok": True}
    return {"ok": True}


_sauve = (lv._etat, lv._ecrire, lv._creer_ou_reprendre, lv.creer_tracking, lv.config, gms._call_tool)
lv._etat = lambda: ETAT
lv._ecrire = lambda d: ETAT.update(d)
lv._creer_ou_reprendre = lambda nom, creator_id=None: {"ok": True, "url": "https://onlyfans.com/liasxcret/c777",
                                                       "code": "c777"}
lv.creer_tracking = lambda nom, creator_id=None: {"ok": True, "url": "https://onlyfans.com/liasxcret/c777",
                                                  "code": "c777"}
lv.config = lambda: {"gabarit": DIRECT, "equipe": "tm_twitter", "modele": "Lia", "mypuls_actif": True,
                     "creator_id": 3992}
gms._call_tool = _tool4
try:
    r = lv.rebrancher(lv.TWITTER_ID, "7")
    f = ETAT["liens"][f"{lv.TWITTER_ID}:7"]
    check("le tracking va sur le bouton OnlyFans, le Telegram ne bouge pas, la fiche le note",
          r.get("ok") and [b["url"] for b in PAGE["buttons"] or []] == ["https://onlyfans.com/liasxcret/c777",
                                                                         "https://t.me/m/x"]
          and f.get("tracking") == "https://onlyfans.com/liasxcret/c777" and f.get("code") == "c777", (r, PAGE, f))
    check("jamais typeLink « directlink » ni « url » sur une page : elle reste une page",
          PAGE["type"] == "landing" and ENVOIS
          and not [a for a in ENVOIS if a.get("typeLink") or a.get("url")], ENVOIS)
    # un vieux lien encore direct (les liens coupés restés sur Emy) : l'ancien chemin
    ENVOIS.clear()
    f.update(tracking="", code="")
    PAGE.update(type="directlink", buttons=None, url="https://onlyfans.com/liasxcret")
    r = lv.rebrancher(lv.TWITTER_ID, "7")
    check("un lien encore direct : l'ancien chemin (destination + typeLink directlink)",
          r.get("ok") and [a for a in ENVOIS if a.get("typeLink") == "directlink"
                           and a.get("url") == "https://onlyfans.com/liasxcret/c777"], (r, ENVOIS))
finally:
    lv._etat, lv._ecrire, lv._creer_ou_reprendre, lv.creer_tracking, lv.config, gms._call_tool = _sauve

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
