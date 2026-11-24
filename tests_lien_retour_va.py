# -*- coding: utf-8 -*-
"""tests_lien_retour_va.py — le bouton du lien suit le registre des liens.

Propriétaire, 24/11/2026, capture d'un ticket de TRUST TWITTER (VA 223) : « un
va a quitté le serv, son lien a été désactivé, mais maintenant je peux plus
rien faire ». Parti, son lien avait été coupé ; revenu, un ticket NEUF portait
« 🔗 Créer son lien » sous « 🚫 Désactivé pour le moment », et le clic répondait
« Ce VA a déjà son lien » — ✅ Réactiver le lien n'était nulle part.

Ce qui est vérifié :
  - boutons_va lit au registre ce que l'appelant ne dit pas du lien : coupé,
    ✅ Réactiver ; en service, 🚫 Désactiver ; aucun, 🔗 Créer ; ce que
    l'appelant dit reste ce qu'il dit ; un registre illisible ne lève pas ;
  - un ticket neuf (ouvrir_ticket) pour un VA au lien coupé porte ✅ Réactiver
    le lien, jamais « Créer son lien » ;
  - « Créer son lien » cliqué sur un lien coupé : rien n'est créé (ni lien, ni
    tracking), la réponse porte ✅ Réactiver le lien, l'accueil et son menu en
    blocs reprennent le bon bouton ; ce ✅ rallume, et la réponse éphémère
    perd son bouton ;
  - rattraper_boutons_lien : un menu resté sur « Créer son lien » alors que le
    registre a un lien est redessiné (accueil et menu), compté et dit au
    journal ; rien n'est envoyé à Discord quand tout concorde ; « Créer son
    lien » n'est jamais remis d'office ; accueil retiré à la main : le menu
    est corrigé quand même.

Faux Discord, dossier temporaire : aucun appel réseau, rien dans data/.
Lancement : python tests_lien_retour_va.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:600]}]" if detail and not cond else ""))


import liens_va as lv          # noqa: E402
import pages_va                # noqa: E402
import stats_va                # noqa: E402
import suivi_va                # noqa: E402
import tickets_discord as tk   # noqa: E402

G = tk.TWITTER_ID
U, NEUF, ACTIF, CHEF = "223", "224", "225", "42"
URL = "https://getmysocial.com/bbypeachyy"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="lien_retour_"))
_SAUVE_TK = {k: getattr(tk, k) for k in ("ETAT_FICHIER", "CONFIG_FICHIER", "DATA_DIR", "USDC_QR_DOSSIER",
                                         "USDC_EMOJIS_FICHIER", "_api_reseau", "_EN_FOND", "_en_fond",
                                         "_app_du_serveur")}
_SAUVE_LV = {k: getattr(lv, k) for k in ("lien_de", "basculer", "creer_pour", "manque")}
_SAUVE_AUTRES = (suivi_va.ETAT_FICHIER, pages_va.FICHIER, stats_va.lien)

tk.ETAT_FICHIER = TMP / "tickets.json"
tk.CONFIG_FICHIER = TMP / "tickets_config.json"
tk.DATA_DIR = TMP
tk.USDC_QR_DOSSIER = TMP / "usdc_qr"
tk.USDC_EMOJIS_FICHIER = TMP / "usdc_emojis.json"
suivi_va.ETAT_FICHIER = TMP / "suivi_va.json"
pages_va.FICHIER = TMP / "pages_va.json"          # jamais le vrai registre des pages
stats_va.lien = lambda gid, uid: ""               # aucune clé de page de stats écrite
tk._EN_FOND = lambda f: f()
tk._en_fond = lambda f: f()
tk._app_du_serveur = lambda g: ""

# le registre des liens, en mémoire : {uid: fiche}
LIENS = {}
CASSE = [False]
BASCULES, CREATIONS = [], []


def _lien_de(gid, uid):
    if CASSE[0]:
        raise OSError("registre illisible")
    return dict(LIENS.get(str(uid)) or {}) if str(gid) == G else {}


def _basculer(gid, uid, actif):
    BASCULES.append((str(uid), bool(actif)))
    LIENS[str(uid)]["actif"] = bool(actif)
    return {"ok": True, "url": LIENS[str(uid)]["public_url"], "actif": bool(actif), "erreur": ""}


def _creer_pour(gid, uid, pseudo, **kw):
    CREATIONS.append(str(uid))
    return {"ok": False, "erreur": "ne devait pas être appelé"}


lv.lien_de = _lien_de
lv.basculer = _basculer
lv.creer_pour = _creer_pour
lv.manque = lambda gid="": ""


def lien(actif):
    return {"public_url": URL, "shortcode": "bbypeachyy", "link_id": "lnk_1", "numero": 223,
            "pseudo": "lafouilne", "tracking": "https://onlyfans.com/liasxcret/c177", "actif": actif}


class FauxDiscord:
    def __init__(self):
        self.appels, self.messages, self.fil, self.salons = [], {}, {}, {}
        self.n = 0

    def api(self, methode, chemin, **kw):
        corps = kw.get("json") or {}
        self.appels.append((methode, chemin, corps))
        base = chemin.split("?", 1)[0]
        p = base.strip("/").split("/")
        if p[0] == "guilds":
            if base.endswith("/roles") and methode == "GET":
                return 200, [{"id": "800", "name": "🧪 Essai"}]     # pas de rôle Manager : aucun manager
            if base.endswith("/channels") and methode == "POST":
                self.n += 1
                cid = f"s{self.n}"
                self.salons[cid] = dict(corps, id=cid)
                return 201, {"id": cid}
            if "/roles/" in base:
                return 204, {}
            if len(p) == 4 and p[2] == "members" and methode == "GET":
                return 200, {"user": {"id": p[3], "username": f"va{p[3]}"}, "roles": []}
            return 200, []
        if p[0] == "channels" and len(p) == 2:
            return (200, self.salons[p[1]]) if p[1] in self.salons else (404, {"code": 10003})
        if p[0] == "channels" and p[2] == "pins":
            return 204, {}
        if p[0] == "channels" and p[2] == "messages":
            salon = p[1]
            if len(p) == 3 and methode == "GET":
                lim = int(chemin.rsplit("=", 1)[1]) if "limit=" in chemin else 50
                return 200, [self.messages[m] for m in reversed(self.fil.get(salon, []))][:lim]
            if len(p) == 3 and methode == "POST":
                self.n += 1
                mid = f"m{self.n}"
                self.messages[mid] = {"id": mid, "type": 0, "author": {"id": "bot", "bot": True},
                                      "content": corps.get("content"), "flags": corps.get("flags", 0),
                                      "embeds": corps.get("embeds") or [],
                                      "components": corps.get("components") or []}
                self.fil.setdefault(salon, []).append(mid)
                return 200, {"id": mid}
            mid = p[3]
            if mid not in self.messages:
                return 404, {"code": 10008}
            if methode == "GET":
                return 200, json.loads(json.dumps(self.messages[mid]))
            if methode == "PATCH":
                for k in ("components", "content", "embeds"):
                    if k in corps:
                        self.messages[mid][k] = corps[k]
                return 200, {}
            if methode == "DELETE":
                self.fil[salon] = [m for m in self.fil.get(salon, []) if m != mid]
                self.messages.pop(mid, None)
                return 204, {}
        return 200, {}

    def ecrits(self):
        return [a for a in self.appels if a[0] != "GET"]


def etat():
    return json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))


def fiche(uid):
    return (etat().get("tickets") or {}).get(f"{G}:{uid}") or {}


def ids(x):
    """Tous les custom_id, à toute profondeur (rangées d'un accueil ou blocs d'un menu)."""
    if isinstance(x, list):
        return [c for y in x for c in ids(y)]
    if isinstance(x, dict):
        return ([str(x["custom_id"])] if x.get("custom_id") else []) + [c for v in x.values() for c in ids(v)]
    return []


def du_lien(x):
    return [c for c in ids(x) if c.startswith("lien:")]


def textes(x):
    if isinstance(x, list):
        return [t for y in x for t in textes(y)]
    if isinstance(x, dict):
        return ([str(x["content"])] if x.get("type") == 10 else []) + [t for v in x.values() for t in textes(v)]
    return []


def muet():
    return contextlib.redirect_stdout(io.StringIO())


def clic(cid, salon, mid, flags=0, qui=CHEF, perms="8"):
    return {"type": 3, "guild_id": G, "channel_id": salon, "token": "jeton", "application_id": "1",
            "data": {"custom_id": cid}, "message": {"id": mid, "flags": flags},
            "member": {"permissions": perms, "roles": [], "user": {"id": qui}}}


def monde():
    """Dossier remis à zéro, faux Discord vide, registre vide."""
    # « .prev » compris : safe_json restaurerait l'état du monde d'avant
    for f in TMP.glob("tickets*"):
        f.unlink(missing_ok=True)
    for cache in (tk._CACHE, tk._CREATIONS):
        cache.clear()
    LIENS.clear()
    BASCULES.clear()
    CREATIONS.clear()
    d = FauxDiscord()
    tk._api_reseau = d.api
    return d


def ticket_fautif(d, uid=U):
    """Le ticket tel que l'ancien code le laissait : un accueil « Créer son
    lien » (posé sans lire le registre), puis son menu en blocs, qui recopie
    ses rangées. Rend (salon, accueil, menu)."""
    salon = "5000"
    d.salons[salon] = {"id": salon}
    rangs = tk.boutons_va(uid, confirme=False, a_un_lien=False, gid=G)
    _c, rep = d.api("POST", f"/channels/{salon}/messages",
                    json={"embeds": [{"title": "👋 Bienvenue", "description": "…"}], "components": rangs})
    tk._ecrire_etat({"tickets": {f"{G}:{uid}": {"salon": salon, "accueil": rep["id"], "essai": True,
                                                "ouvert": 1, "boutons": tk.BOUTONS_VERSION}}})
    with muet():
        tk.ramener_menu(G, uid, salon)
    return salon, rep["id"], str(fiche(uid).get("menu") or "")


try:
    # ══ 0. boutons_va : ce qui n'est pas dit est lu au registre ═══════════
    print("\n— 0. boutons_va lit le registre des liens")
    monde()
    check("pas de lien au registre : « Créer son lien »", du_lien(tk.boutons_va(U, gid=G)) == [f"lien:new:{U}"],
          du_lien(tk.boutons_va(U, gid=G)))
    LIENS[U] = lien(False)
    check("lien coupé au registre, rien de dit : ✅ Réactiver, pas « Créer son lien »",
          du_lien(tk.boutons_va(U, gid=G)) == [f"lien:on:{U}"], du_lien(tk.boutons_va(U, gid=G)))
    check("… « a un lien » dit, « en service » oublié (Confirmer le VA, suivi_va) : ✅ Réactiver",
          du_lien(tk.boutons_va(U, confirme=True, a_un_lien=True, gid=G)) == [f"lien:on:{U}"])
    LIENS[U] = lien(True)
    check("lien en service au registre : 🚫 Désactiver",
          du_lien(tk.boutons_va(U, gid=G)) == [f"lien:off:{U}"])
    check("ce que l'appelant dit reste ce qu'il dit (coupé à l'instant : ✅ Réactiver)",
          du_lien(tk.boutons_va(U, a_un_lien=True, gid=G, lien_actif=False)) == [f"lien:on:{U}"]
          and du_lien(tk.boutons_va(U, a_un_lien=False, gid=G)) == [f"lien:new:{U}"])
    LIENS[U] = lien(False)
    check("… et dans l'autre sens (rallumé à l'instant : 🚫 Désactiver)",
          du_lien(tk.boutons_va(U, a_un_lien=True, gid=G, lien_actif=True)) == [f"lien:off:{U}"])
    check("sans serveur (bouton_confirmer) : comme avant, aucune lecture",
          du_lien(tk.bouton_confirmer(U)) == [f"lien:new:{U}"])
    CASSE[0] = True
    with muet() as sortie:
        r = tk.boutons_va(U, gid=G)
    CASSE[0] = False
    check("registre illisible : pas d'exception, c'est dit au journal",
          du_lien(r) == [f"lien:new:{U}"] and "illisible" in sortie.getvalue(), sortie.getvalue())
    check("la rangée du VA et le reste ne changent pas (💳 toujours là)",
          f"usdc:set:{U}" in ids(tk.boutons_va(U, gid=G)))

    # ══ 1. un ticket NEUF pour un VA qui a déjà son lien ══════════════════
    print("\n— 1. ouvrir_ticket : le VA revenu a déjà son lien")
    d = monde()
    LIENS[U] = lien(False)
    LIENS[ACTIF] = dict(lien(True), public_url="https://getmysocial.com/autre", numero=225)
    with muet():
        s_u = tk.ouvrir_ticket(U, {"id": G})
        s_n = tk.ouvrir_ticket(NEUF, {"id": G})
        s_a = tk.ouvrir_ticket(ACTIF, {"id": G})
    acc = {x: d.messages.get(str(fiche(x).get("accueil"))) or {} for x in (U, NEUF, ACTIF)}
    check("les trois tickets sont ouverts, accueil noté", all((s_u, s_n, s_a)) and all(acc.values()),
          (s_u, s_n, s_a))
    check("lien coupé à son départ : l'accueil neuf porte ✅ Réactiver le lien",
          du_lien(acc[U].get("components")) == [f"lien:on:{U}"], du_lien(acc[U].get("components")))
    check("… et pas « Créer son lien » (le clic répondait « a déjà son lien », sans issue)",
          f"lien:new:{U}" not in ids(acc[U].get("components")))
    check("un nouveau, sans lien : « Créer son lien », comme avant",
          du_lien(acc[NEUF].get("components")) == [f"lien:new:{NEUF}"])
    check("un VA dont le lien est en service (salon refait) : 🚫 Désactiver le lien",
          du_lien(acc[ACTIF].get("components")) == [f"lien:off:{ACTIF}"])
    check("ouvrir un ticket ne rallume rien et ne crée rien", not BASCULES and not CREATIONS,
          (BASCULES, CREATIONS))
    with muet():
        tk.ramener_menu(G, U, s_u)
    menu = d.messages.get(str(fiche(U).get("menu"))) or {}
    check("son menu en blocs : « 🚫 Désactivé pour le moment » ET ✅ Réactiver (plus de contradiction)",
          any("Désactivé pour le moment" in t for t in textes(menu.get("components")))
          and du_lien(menu.get("components")) == [f"lien:on:{U}"], du_lien(menu.get("components")))

    # ══ 2. « Créer son lien » cliqué alors que le lien existe ═════════════
    print("\n— 2. le clic « Créer son lien » sur un lien coupé donne ✅ Réactiver")
    d = monde()
    LIENS[U] = lien(False)
    salon, accueil, menu = ticket_fautif(d)
    check("le ticket fautif d'avant : accueil et menu portent « Créer son lien »",
          du_lien(d.messages[accueil]["components"]) == [f"lien:new:{U}"]
          and du_lien(d.messages[menu]["components"]) == [f"lien:new:{U}"] and bool(menu))
    with muet():
        refus = tk.traiter(clic(f"lien:new:{U}", salon, menu, flags=tk.V2, qui=U, perms="0"))
    check("le VA lui-même : refusé (bouton de manager), rien ne bouge",
          "managers" in str((refus or {}).get("data", {}).get("content"))
          and du_lien(d.messages[accueil]["components"]) == [f"lien:new:{U}"])
    with muet():
        rep = tk.traiter(clic(f"lien:new:{U}", salon, menu, flags=tk.V2))
    data = (rep or {}).get("data") or {}
    check("réponse au manager : éphémère, dit que le lien existe et qu'il est coupé",
          (rep or {}).get("type") == 4 and data.get("flags") == 64 and "coupé" in str(data.get("content"))
          and URL in str(data.get("content")), rep)
    check("… avec ✅ Réactiver le lien dans la réponse même, et rien d'autre",
          ids(data.get("components")) == [f"lien:on:{U}"]
          and "Réactiver" in str(data.get("components")), data.get("components"))
    check("rien n'est créé (ni lien, ni tracking MyPuls) et rien n'est rallumé d'office",
          not CREATIONS and not BASCULES and LIENS[U]["actif"] is False, (CREATIONS, BASCULES))
    check("la création n'est pas restée réservée (un vrai clic repasserait)", not tk._CREATIONS, tk._CREATIONS)
    check("l'accueil reprend le bon bouton : ✅ Réactiver",
          du_lien(d.messages[accueil]["components"]) == [f"lien:on:{U}"])
    check("… et son menu en blocs suit (copie)",
          du_lien(d.messages[menu]["components"]) == [f"lien:on:{U}"]
          and du_lien(fiche(U).get("menu_rangs")) == [f"lien:on:{U}"])
    with muet():
        rep2 = tk.traiter(clic(f"lien:on:{U}", salon, "ephemere", flags=64))
    data2 = (rep2 or {}).get("data") or {}
    check("✅ cliqué dans la réponse : le lien est rallumé (liens_va.basculer, une fois)",
          BASCULES == [(U, True)] and LIENS[U]["actif"] is True, BASCULES)
    check("… la réponse éphémère est remplacée, son bouton parti (pas de second clic)",
          (rep2 or {}).get("type") == 7 and data2.get("components") == []
          and "remis en service" in str(data2.get("content")), rep2)
    check("… accueil et menu passent à 🚫 Désactiver le lien, « Ton lien » revient",
          du_lien(d.messages[accueil]["components"]) == [f"lien:off:{U}"]
          and du_lien(d.messages[menu]["components"]) == [f"lien:off:{U}"]
          and any(URL in t for t in textes(d.messages[menu]["components"])),
          (du_lien(d.messages[accueil]["components"]), textes(d.messages[menu]["components"])))
    with muet():
        rep3 = tk.traiter(clic(f"lien:off:{U}", salon, accueil))
    check("🚫 cliqué sur l'accueil : réponse éphémère neuve, comme avant (type 4)",
          (rep3 or {}).get("type") == 4 and BASCULES[-1] == (U, False), rep3)

    print("\n— 2 bis. « Créer son lien » cliqué sur un lien EN SERVICE")
    d = monde()
    LIENS[U] = lien(True)
    salon, accueil, menu = ticket_fautif(d)
    with muet():
        rep = tk.traiter(clic(f"lien:new:{U}", salon, accueil))
    data = (rep or {}).get("data") or {}
    check("même réponse qu'avant (« a déjà son lien », destination), sans bouton",
          (rep or {}).get("type") == 4 and str(data.get("content")).startswith("Ce VA a déjà son lien : " + URL)
          and "liasxcret/c177" in str(data.get("content")) and not data.get("components"), rep)
    check("… rien créé, rien basculé", not CREATIONS and not BASCULES)
    check("… et le bouton fautif part : accueil et menu passent à 🚫 Désactiver le lien",
          du_lien(d.messages[accueil]["components"]) == [f"lien:off:{U}"]
          and du_lien(d.messages[menu]["components"]) == [f"lien:off:{U}"])

    # ══ 3. le rattrapage du tour des liens ════════════════════════════════
    print("\n— 3. rattraper_boutons_lien : les tickets déjà faux, comptés et redessinés")
    d = monde()
    LIENS[U] = lien(False)
    salon, accueil, menu = ticket_fautif(d)
    d.appels.clear()
    with muet() as sortie:
        bilan = tk.redessiner_boutons(G)
    dit = sortie.getvalue()
    liens = bilan.get("liens") or {}
    check("le tour des liens passe par le rattrapage et le rend dans son bilan",
          len(liens.get("faux") or []) == 1 and len(liens.get("redessines") or []) == 1
          and not liens.get("rates"), bilan)
    check("… il dit au journal combien, et lequel (VA 223 @lafouilne)",
          "1 ticket(s)" in dit and "VA 223 @lafouilne" in dit and "lien:new" in dit, dit)
    check("… l'accueil et le menu portent ✅ Réactiver ; le lien, lui, reste coupé",
          du_lien(d.messages[accueil]["components"]) == [f"lien:on:{U}"]
          and du_lien(d.messages[menu]["components"]) == [f"lien:on:{U}"]
          and not BASCULES and LIENS[U]["actif"] is False)
    d.appels.clear()
    with muet() as sortie:
        bilan2 = tk.redessiner_boutons(G)
    check("second passage : plus rien de faux, RIEN d'envoyé à Discord, rien au journal",
          not (bilan2.get("liens") or {}).get("faux") and not d.appels
          and "boutons du lien" not in sortie.getvalue(), (bilan2, d.appels))

    d = monde()
    salon, accueil, menu = ticket_fautif(d)          # pas de lien : « Créer son lien » est juste
    d.appels.clear()
    with muet():
        b = tk.rattraper_boutons_lien(G)
    check("un VA sans lien : rien à rattraper, rien d'envoyé", not b["faux"] and not d.appels)

    d = monde()
    LIENS[U] = lien(True)
    salon, accueil, menu = ticket_fautif(d)
    with muet():
        tk.redessiner_boutons(G)                       # accueil et menu : 🚫 Désactiver
    LIENS.clear()                                      # le registre « perd » le lien (illisible, vidé)
    d.appels.clear()
    with muet():
        b = tk.rattraper_boutons_lien(G)
    check("registre sans le lien : « Créer son lien » n'est JAMAIS remis d'office",
          not b["faux"] and not d.ecrits()
          and du_lien(d.messages[accueil]["components"]) == [f"lien:off:{U}"], (b, d.ecrits()))

    d = monde()
    LIENS[U] = lien(False)
    salon, accueil, menu = ticket_fautif(d)
    d.messages.pop(accueil)                            # accueil retiré à la main
    with muet():
        b = tk.rattraper_boutons_lien(G)
    check("accueil retiré à la main (404) : le menu est corrigé quand même, et compté",
          len(b["faux"]) == 1 and len(b["redessines"]) == 1
          and du_lien(d.messages[menu]["components"]) == [f"lien:on:{U}"], b)
    d.appels.clear()
    with muet():
        b = tk.rattraper_boutons_lien(G)
    check("… et il ne revient pas à chaque tour", not b["faux"] and not d.appels, (b, d.appels))

    d = monde()
    LIENS[U] = lien(False)
    salon, accueil, menu = ticket_fautif(d)
    vrai_api = d.api
    tk._api_reseau = lambda m, c, **kw: (500, {}) if m == "PATCH" else vrai_api(m, c, **kw)
    with muet() as sortie:
        b = tk.rattraper_boutons_lien(G)
    tk._api_reseau = vrai_api
    check("Discord en panne : compté dans « ratés » et dit, pas avalé",
          len(b["faux"]) == 1 and not b["redessines"] and "HTTP 500" in str(b["rates"])
          and "ratés" in sortie.getvalue(), (b, sortie.getvalue()))
    with muet():
        b = tk.rattraper_boutons_lien(G)
    check("… repris au tour suivant", len(b["redessines"]) == 1
          and du_lien(d.messages[accueil]["components"]) == [f"lien:on:{U}"], b)
finally:
    for k, v in _SAUVE_TK.items():
        setattr(tk, k, v)
    for k, v in _SAUVE_LV.items():
        setattr(lv, k, v)
    suivi_va.ETAT_FICHIER, pages_va.FICHIER, stats_va.lien = _SAUVE_AUTRES
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
