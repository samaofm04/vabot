# -*- coding: utf-8 -*-
"""tests_pages_va.py — la page GetMySocial modifiable des VA de TRUST TWITTER (06/11/2026).

Propriétaire : « je veux avoir 2 liens pour les VA, un direct et un landing page
qu'ils peuvent modifier » ; photo (il dépose une image), nom et bio, texte du
bouton, image de fond ; même tracking, pays, safe page, PAS de 70/30 (« ça doit pas être 70 30 ») ;
essai sur lui seul, hors classement — puis (06/11) « pour tout le monde » : sur
Twitter 1 lien direct + 1 page, que le VA crée lui-même. TRUST INSTAGRAM
(7b) : 3 pages FIXES par VA (un gabarit par place), créées d'office par la
reprise, non modifiables ; des pages en plus à la demande, acceptées par un
manager seul, modifiables ; le 70/30 « Lia seule » sur toutes, jamais sur
Twitter.

Sans réseau ni data/ : gms, requests et liens_va sont remplacés là où il faut,
le registre vit dans un dossier temporaire.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import time

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms                     # noqa: E402
import liens_va as lv          # noqa: E402
import pages_va as pv          # noqa: E402
import podium_discord as pod   # noqa: E402
import tickets_discord as tk   # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:500]}]"))


TW = pv.TWITTER_ID
MOI, VA, AUTRE = "479005370438778891", "4001", "4002"
EQ = "tm_6ab46ebb11a0232c11211b1a"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pages_va_"))
pv.FICHIER = TMP / "pages_va.json"
FICHE = {"link_id": "lnk_direct", "tracking": "https://onlyfans.com/liasxcret/c300", "numero": 160,
         "pseudo": "yous1m", "public_url": "https://getmysocial.com/direct1", "groupe": "Manager JOHN",
         "actif": True}

# ── faux GetMySocial ──────────────────────────────────────────────────────
APPELS = []
PAGES = {}
REGLE = {"maj_ok": True, "relu_autre": False, "post_status": 201, "vieille_image": False}


def page_neuve(lid):
    return {"id": lid, "type": "landing", "display_name": "x", "name_user": "{{color:#ffffff}}Lia  ♡{{/color}}",
            "bio": "{{color:#ffffff}}posting my secretttts :3{{/color}}",
            "background_image": "https://images.getmysocial.com/links/u/gab/1700000000000-aa/background.jpg",
            "profile_picture": "https://images.getmysocial.com/u/1700000000000-bb.jpg",
            "buttons": [{"label": "“exclusive” stuff lol ", "url": "https://onlyfans.com/liasxcret",
                         "geofilters": [{"country_code": "FR", "destination_url": "https://onlyfans.com/liasxcret"}]},
                        {"label": "Insta", "url": "https://instagram.com/x"}]}


#: Les gabarits de TRUST INSTAGRAM portent un 2e bouton, Telegram, qui ne doit
#: jamais bouger.
GABARITS_IG = set(pv.GABARITS_PLACE.get(pv.AGENCY_IG_ID, {}).values()) | {pv.GABARIT_PAGE.get(pv.AGENCY_IG_ID)}


def f_duplicate(src, sc, nom="", url="", team_id=None):
    APPELS.append(("duplicate", src, sc, nom, url, team_id))
    if src in REGLE.get("dup_refus", ()):
        # un vrai refus (pas une panne passagère : celle-ci ne compte pas d'essai)
        return {"ok": False, "error": REGLE.get("dup_erreur") or "gabarit introuvable"}
    lid = "lnk_page_" + sc
    if lid in PAGES:
        return {"ok": False, "error": "shortcode already taken"}     # comme GetMySocial : adresse prise
    PAGES[lid] = page_neuve(lid)
    PAGES[lid]["display_name"] = nom or "x"
    if sc in REGLE.get("perdue", ()):
        # la copie est faite, mais la réponse se perd : gms renvoie l'appel,
        # qui trouve l'adresse prise (par cette même copie)
        return {"ok": False, "error": "shortcode already taken"}
    if src in GABARITS_IG:
        PAGES[lid]["buttons"] = [PAGES[lid]["buttons"][0], {"label": "Telegram 💬", "url": "https://t.me/liaprivate"}]
    return {"ok": True, "link": {"id": lid}}


def f_update(lid, champs, team_id=None):
    APPELS.append(("update", lid, json.loads(json.dumps(champs)), team_id))
    if not REGLE["maj_ok"]:
        return {"ok": False, "error": "refus"}
    if lid in PAGES:
        for k, v in champs.items():
            PAGES[lid][k] = v
        if REGLE["relu_autre"] and "name_user" in champs:
            PAGES[lid]["name_user"] = "autre chose"
    return {"ok": True, "link": PAGES.get(lid, {})}


def f_get(lid, team_id=None):
    APPELS.append(("get", lid))
    return {"ok": True, "link": json.loads(json.dumps(PAGES.get(lid, {})))}


def f_disable(lid):
    APPELS.append(("disable", lid))
    return {"ok": True}


def f_enable(lid):
    APPELS.append(("enable", lid))
    return {"ok": True}


def f_delete(lid):
    APPELS.append(("delete", lid))
    return {"ok": True}


class Rep:
    def __init__(self, status, corps):
        self.status_code, self._c = status, corps

    def json(self):
        return self._c


def f_post(url, headers=None, data=None, files=None, timeout=None):
    APPELS.append(("post", url, dict(data or {}), sorted((files or {}).keys())))
    ms = 1600000000000 if REGLE["vieille_image"] else int(time.time() * 1000)
    corps = {"id": "lnk_tmp_" + str(len(APPELS))}
    if "profilePicture" in (files or {}):
        corps["profile_picture"] = f"https://images.getmysocial.com/u/{ms}-cafe12.jpg"
    if "backgroundImage" in (files or {}):
        corps["background_image"] = f"https://images.getmysocial.com/u/{ms}-fond34.jpg"
    return Rep(REGLE["post_status"], corps)


import requests  # noqa: E402

SAV = (gms.duplicate_link, gms.update_link, gms.get_link, gms.disable_link, gms.enable_link,
       gms.delete_link, gms.get_api_key, requests.post, lv.lien_de, lv.espace, lv._poser_tracking,
       lv.poser_pays, lv._poser_base_seule, lv.ranger, lv.lia_seule, tk._etat, tk.role_manager,
       tk.role_helper, tk._maj_menu_v2, tk._EN_FOND, tk._suite, tk._api_reseau, lv._etat,
       gms._call_tool, pv._cookie_ok, pv._FIL)
VRAI_POSER_TRACKING = lv._poser_tracking
VRAI_POSER_BASE_SEULE = lv._poser_base_seule
#: Les autres attributs remplacés (relectures du 06/11), remis à la fin.
SAV2 = {(m, n): getattr(m, n) for m, n in (
    (gms, "pause_restante"), (gms, "list_links_team"), (gms, "lire_ab_testing"), (gms, "_ab_prive"),
    (lv, "_page_du_lien"), (lv, "nom_de_page"), (lv, "espace"), (tk, "ATTENTE_AVANT_PATCH_S"),
    (tk, "REDESSIN_LISTE_S"), (tk, "_noter_menu_v2"), (pv, "_ecrire"))}
FICHES = {f"{TW}:{MOI}": dict(FICHE)}
SAV_TK = (tk.ETAT_FICHIER, tk._api_reseau)
# aucune voie vers le vrai état des tickets ni vers Discord
tk.ETAT_FICHIER = TMP / "tickets.json"
tk._api_reseau = lambda *a, **k: (0, None)
try:
    gms.duplicate_link, gms.update_link, gms.get_link = f_duplicate, f_update, f_get
    gms.disable_link, gms.enable_link, gms.delete_link = f_disable, f_enable, f_delete
    gms.get_api_key = lambda: "cle-test"
    requests.post = f_post
    lv.lien_de = lambda g, u: dict(FICHES.get(f"{g}:{u}", {}))
    lv.espace = lambda g="": {"equipe": EQ}
    POSES = []
    lv._poser_tracking = lambda lid, t, nom, eq: (POSES.append((lid, t)) or {"ok": True})
    lv.poser_pays = lambda lid, eq, *a: (APPELS.append(("pays", lid)) or {"ok": True})
    AB = []
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": True})
    lv.ranger = lambda eq, lid, nom: (APPELS.append(("ranger", lid, nom)) or nom)
    lv.lia_seule = lambda g="": {"controle": 70, "base_modele": 30}

    # ── 1. ce que tape le VA, les couleurs, les images ────────────────────
    print("1. Saisie, couleurs, images")
    check("balisage {{color}} et jetons {city} retirés, contrôles retirés",
          pv.nettoyer("{{color:#fff}}Lia{{/color}} de {city}\x07", 40) == "Lia de city")
    check("longueur bornée, une ligne pour le nom", pv.nettoyer("a\nb" + "x" * 99, 10) == "a bxxxxxxx")
    check("bio : 4 lignes au plus, lignes vides retirées",
          pv.nettoyer("1\n\n2\n3\n4\n5", 160, lignes=4) == "1\n2\n3\n4")
    check("le texte au meilleur contraste : clair sur foncé, foncé sur clair et sur orange / rose vif",
          pv.couleur_texte("#000000") == "#FFFFFF" and pv.couleur_texte("#FFFFFF") == "#111111"
          and pv.couleur_texte("#FACC15") == "#111111" and pv.couleur_texte("#1E3A8A") == "#FFFFFF"
          and pv.couleur_texte("#F97316") == "#111111" and pv.couleur_texte("#EC4899") == "#111111"
          and pv.couleur_texte("#7F1D1D") == "#FFFFFF")
    check("une couleur invalide est refusée", pv.couleur_valide("rouge") == "" and pv.couleur_valide("#ec4899") == "#EC4899")
    check("19 fonds proposés (25 au plus), tous valides",
          len(pv.COULEURS) <= 25 and all(pv.couleur_valide(h) == h for _n, h in pv.COULEURS))
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1200, 700), (10, 200, 10)).save(b, "PNG")
    j, err = pv.preparer_photo(b.getvalue())
    im = Image.open(io.BytesIO(j)) if j else None
    check("photo : recadrée carrée 800 px, en JPEG", im is not None and im.size == (800, 800) and im.format == "JPEG", err)
    check("photo illisible : refusée, dit", pv.preparer_photo(b"pas une image")[0] is None
          and "illisible" in pv.preparer_photo(b"pas une image")[1])
    check("photo trop lourde : refusée", pv.preparer_photo(b"x" * (pv.PHOTO_MAX + 1))[0] is None)
    t = io.BytesIO()
    im_t = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    im_t.paste((10, 10, 200, 255), (150, 150, 250, 250))
    im_t.save(t, "PNG")
    jt, _e = pv.preparer_photo(t.getvalue())
    pix = Image.open(io.BytesIO(jt)).getpixel((5, 5)) if jt else None
    check("photo transparente : posée sur du blanc (pas du noir)", pix and min(pix) > 240, pix)
    g = io.BytesIO()
    Image.new("1", (8000, 6000)).save(g, "PNG")
    check("photo géante en pixels : refusée avant décodage", pv.preparer_photo(g.getvalue())[0] is None
          and "pixels" in pv.preparer_photo(g.getvalue())[1])
    fond = Image.open(io.BytesIO(pv.image_unie("#EC4899")))
    check("fond : une image unie de la couleur", fond.size == pv.FOND_TAILLE and fond.getpixel((5, 5))[0] > 200)

    # ── 2. pilote ────────────────────────────────────────────────────────
    AG = pv.AGENCY_IG_ID
    GAB_BRUNE, GAB_BLONDE, GAB_TEMPLATE = ("lnk_6aedd88bc7881b6c8066a247", "lnk_6aedd88cc7881b6c8066a28c",
                                           "lnk_6aedd88dc7881b6c8066a2c0")
    check("Twitter ouvert à tous les VA ; TRUST INSTAGRAM aussi (PILOTE « * », sinon pas de reprise)",
          pv.ouverte(TW, MOI) and pv.ouverte(TW, VA) and pv.ouverte(AG, MOI) and pv.PILOTE[AG] == {"*"}
          and not pv.ouverte("999", MOI))
    check("un gabarit par place fixe sur TRUST INSTAGRAM (brune, blonde, template), liatemplate au-delà",
          [pv.gabarit(AG, n) for n in (1, 2, 3, 4, 10)] == [GAB_BRUNE, GAB_BLONDE, GAB_TEMPLATE,
                                                            GAB_TEMPLATE, GAB_TEMPLATE]
          and pv.GABARIT_PAGE[AG] == GAB_TEMPLATE and isinstance(pv.GABARIT_PAGE[AG], str))
    check("Twitter : son gabarit reste une chaîne, la même pour sa page",
          isinstance(pv.GABARIT_PAGE[TW], str) and pv.gabarit(TW, 1) == pv.GABARIT_PAGE[TW]
          and not pv.GABARITS_PLACE.get(TW))
    check("une page par VA sur Twitter (1 direct + 1 page, modifiable) ; 3 places fixes sur TRUST INSTAGRAM",
          pv.pages_max(TW) == 1 and pv.places(TW, VA) == [1] and pv.fixes(TW) == 0 and pv.modifiable(TW, 1)
          and pv.fixes(AG) == 3 and pv.places(AG, VA) == [1, 2, 3] and pv.pages_max(AG) == 3
          and not pv.modifiable(AG, 3) and pv.modifiable(AG, 4) and pv.pages_max("999") == 1)
    check("le 70/30 des pages : TRUST INSTAGRAM seul (« ça doit pas être 70 30 » pour Twitter)",
          pv.AB_PAGES == {AG} and pv.ab_voulu(AG) and not pv.ab_voulu(TW))
    check("places : « uid », « uid#2 », « uid#3 »", pv.place(VA, 1) == VA and pv.place(VA, 2) == f"{VA}#2"
          and pv._vrai_uid(f"{VA}#3") == VA)

    # ── 3. création ──────────────────────────────────────────────────────
    print("3. Création")
    r = pv.creer_page(TW, VA)
    check("sans lien direct : refusée, rien créé", not r["ok"] and "lien direct" in r["erreur"]
          and not [a for a in APPELS if a[0] == "duplicate"], r)
    APPELS.clear()
    r = pv.creer_page(TW, MOI, par=MOI)
    pg = pv.page_de(TW, MOI)
    lid = pg.get("link_id")
    dup = [a for a in APPELS if a[0] == "duplicate"]
    check("copie du gabarit de page de l'équipe, en page (sans adresse), au nom « … page »",
          r["ok"] and dup and dup[0][1] == pv.GABARIT_PAGE[TW] and dup[0][4] == "" and dup[0][5] == EQ
          and dup[0][3] == "Twitter VA 160 @yous1m page", (r, dup))
    check("son bouton sur le MÊME tracking que le lien direct", POSES == [(lid, FICHE["tracking"])], POSES)
    check("pays sur la page, safe page posée, rangée chez son manager",
          ("pays", lid) in APPELS and ("ranger", lid, "Manager JOHN") in APPELS
          and any(a[0] == "update" and a[1] == lid and a[2].get("bot_protection") == {"mode": "safe_page"}
                  for a in APPELS), APPELS)
    check("PAS de 70/30 sur la page (« ça doit pas être 70 30 »)", not AB, AB)
    check("base de la page : liaseeo (copie dans l'équipe)", pv.GABARIT_PAGE[TW] == "lnk_6aed1548c7881b6c805e773a")
    check("registre : adresse, actif, ce qu'affiche la page (sans balisage)",
          pg.get("public_url", "").startswith("https://getmysocial.com/") and pg.get("actif") is True
          and pg["champs"] == {"nom": "Lia ♡", "bio": "posting my secretttts :3",
                               "bouton": "“exclusive” stuff lol"}, pg)
    APPELS.clear()
    r2 = pv.creer_page(TW, MOI)
    check("relancée : déjà là, rien recréé", r2.get("deja") and not [a for a in APPELS if a[0] == "duplicate"], r2)
    # échecs : la copie COUPÉE, jamais supprimée
    FICHES[f"{TW}:{VA}"] = dict(FICHE, numero=161, pseudo="va1")
    lv._poser_tracking = lambda lid, t, nom, eq: {"ok": False, "erreur": "aucun bouton"}
    APPELS.clear()
    r = pv.creer_page(TW, VA)
    check("tracking non posé : la copie coupée (pas supprimée), notée « ratee », dit",
          not r["ok"] and any(a[0] == "disable" for a in APPELS) and not any(a[0] == "delete" for a in APPELS)
          and pv.page_de(TW, VA).get("actif") is False and pv.page_de(TW, VA).get("etat") == "ratee", (r, APPELS))
    APPELS.clear()
    pv.suivre_bascule(TW, VA, True)
    check("une page ratée ne se rallume jamais par la bascule", not APPELS, APPELS)
    lid_rate = pv.page_de(TW, VA)["link_id"]
    lv._poser_tracking = lambda lid, t, nom, eq: (POSES.append((lid, t)) or {"ok": True})
    APPELS.clear()
    r = pv.creer_page(TW, VA)
    check("relancée après l'échec : reprise sur la MÊME copie (pas de seconde), prête ET rallumée",
          r["ok"] and not [a for a in APPELS if a[0] == "duplicate"] and pv.page_de(TW, VA)["link_id"] == lid_rate
          and pv.page_de(TW, VA)["etat"] == "prete" and pv.page_de(TW, VA)["actif"] is True
          and ("enable", lid_rate) in APPELS, (r, APPELS))
    pv._ecrire({"pages": {k: v for k, v in pv._lire()["pages"].items() if k != f"{TW}:{VA}"}})
    lv.poser_pays = lambda lid, eq, *a: (_ for _ in ()).throw(RuntimeError("panne"))
    APPELS.clear()
    r = pv.creer_page(TW, VA)
    check("une exception au milieu : coupée, notée « ratee », dite, jamais levée",
          not r["ok"] and any(a[0] == "disable" for a in APPELS) and pv.page_de(TW, VA).get("actif") is False
          and pv.page_de(TW, VA).get("etat") == "ratee", r)
    lv.poser_pays = lambda lid, eq, *a: (APPELS.append(("pays", lid)) or {"ok": True})
    pv._ecrire({"pages": {k: v for k, v in pv._lire()["pages"].items() if k != f"{TW}:{VA}"}})
    FICHES[f"{TW}:{VA}"]["actif"] = False
    APPELS.clear()
    r = pv.creer_page(TW, VA)
    check("lien direct coupé : création refusée, rien copié (pas de « ✅ » sur une adresse morte)",
          not r["ok"] and "désactivé" in r["erreur"] and not pv.page_de(TW, VA)
          and not [a for a in APPELS if a[0] == "duplicate"], r)
    FICHES[f"{TW}:{VA}"]["actif"] = True
    # un manager clique « 🚫 Désactiver » PENDANT la copie : liens_va.basculer
    # écrit la fiche (coupée) et met la bascule des pages en file
    import threading as _th
    VERROU_LIBRE = []
    _vp = lv._poser_tracking

    def tracking_pendant_desactiver(lid, t, nom, eq):
        FICHES[f"{TW}:{VA}"]["actif"] = False
        essai = []

        def tenter():
            # un autre fil (la bascule en fond) : relâché par lui-même s'il l'a eu
            v = pv._verrou_page(f"{TW}:{VA}")
            pris = v.acquire(blocking=False)
            essai.append(pris)
            if pris:
                v.release()
        fil = _th.Thread(target=tenter)
        fil.start()
        fil.join()
        VERROU_LIBRE.append(essai[0])
        return _vp(lid, t, nom, eq)
    lv._poser_tracking = tracking_pendant_desactiver
    APPELS.clear()
    r = pv.creer_page(TW, VA)
    lv._poser_tracking = _vp
    check("direct coupé pendant la création : fiche relue à la fin, la page naît coupée",
          r["ok"] and pv.page_de(TW, VA).get("actif") is False and pv.page_de(TW, VA).get("etat") == "prete"
          and any(a[0] == "disable" for a in APPELS), (r, pv.page_de(TW, VA)))
    check("la création tient le verrou de la page (bascule, reprise et Réessayer attendent)",
          VERROU_LIBRE == [False], VERROU_LIBRE)
    FICHES[f"{TW}:{VA}"]["actif"] = False
    for manque in ({"numero": None}, {"pseudo": ""}):
        FICHES[f"{TW}:{AUTRE}"] = dict(FICHE, **manque)
        r = pv.creer_page(TW, AUTRE)
        check(f"fiche sans {list(manque)[0]} : refusée (pas de « VA None @None page »)",
              not r["ok"] and "manquant" in r["erreur"], r)
    FICHES.pop(f"{TW}:{AUTRE}")

    # ── 4. modification ──────────────────────────────────────────────────
    print("4. Modification")
    APPELS.clear()
    r = pv.modifier_page(TW, MOI, nom="Lia {{color:#000}}x{{/color}}", bio="hello\nworld")
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    check("nom et bio : nettoyés, envoyés, relus ; aucune image envoyée",
          r["ok"] and up["name_user"] == "{{color:#ffffff}}Lia x{{/color}}"
          and up["bio"] == "{{color:#ffffff}}hello\nworld{{/color}}" and up.get("display_name")
          and not [a for a in APPELS if a[0] == "post"], (r, up))
    APPELS.clear()
    r = pv.modifier_page(TW, MOI, bouton="Mon OF 🔥")
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    bs = up.get("buttons") or []
    check("texte du bouton : le tableau ENTIER renvoyé, seul le bouton OnlyFans change, tracking et pays gardés",
          r["ok"] and len(bs) == 2 and bs[0]["label"] == "Mon OF 🔥" and bs[0]["url"] == "https://onlyfans.com/liasxcret"
          and bs[0]["geofilters"] and bs[1]["label"] == "Insta", bs)
    APPELS.clear()
    r = pv.modifier_page(TW, MOI, couleur="#ffffff")
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    post = [a for a in APPELS if a[0] == "post"]
    check("couleur : une image unie envoyée (page temporaire supprimée), fond + couleurs posés",
          r["ok"] and post and post[0][3] == ["backgroundImage"] and post[0][2].get("type") == "landing"
          and post[0][2].get("team_id") == EQ[3:]
          and up["custom_background_color"] == "#FFFFFF" and up["custom_text_color"] == "#111111"
          and up["background_image"].startswith("https://images.getmysocial.com/")
          and any(a[0] == "delete" and a[1].startswith("lnk_tmp_") for a in APPELS), (r, up, APPELS))
    APPELS.clear()
    j, _e = pv.preparer_photo(b.getvalue())
    r = pv.modifier_page(TW, MOI, photo=j)
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    check("photo : envoyée par une page temporaire (supprimée), profil + diapo posés",
          r["ok"] and up["profile_picture"].startswith("https://images.getmysocial.com/")
          and up["profile_picture_slides"] == [{"url": up["profile_picture"], "media_type": "image"}]
          and any(a[0] == "delete" for a in APPELS), (r, up))
    check("registre : ce qui a changé noté, sans balisage (préremplit la fenêtre)",
          pv.page_de(TW, MOI)["champs"] == {"nom": "Lia x", "bio": "hello\nworld", "bouton": "Mon OF 🔥",
                                             "couleur": "#FFFFFF"}, pv.page_de(TW, MOI)["champs"])
    APPELS.clear()
    fj, _e = pv.preparer_fond(b.getvalue())
    imf = Image.open(io.BytesIO(fj)) if fj else None
    check("image de fond préparée : 9:16 (1080×1920), JPEG", imf is not None and imf.size == (1080, 1920)
          and imf.format == "JPEG", _e)
    r = pv.modifier_page(TW, MOI, fond=fj)
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    post = [a for a in APPELS if a[0] == "post"]
    check("image de fond : envoyée par une page temporaire (supprimée), seul le fond change",
          r["ok"] and r["faits"] == ["fond"] and post and post[0][3] == ["backgroundImage"]
          and up["background_image"].startswith("https://images.getmysocial.com/")
          and "custom_background_color" not in up and "name_user" not in up and "buttons" not in up
          and any(a[0] == "delete" for a in APPELS), (r, up))
    # le texte modifié garde la couleur du texte de la page de base (blanc sur le canard)
    lidp = pv.page_de(TW, MOI)["link_id"]
    PAGES[lidp]["name_user"] = "{{color:#ffffff}}*Lia  ♡*{{/color}}"
    APPELS.clear()
    r = pv.modifier_page(TW, MOI, nom="Emma ♡")
    up = [a for a in APPELS if a[0] == "update"][-1][2]
    check("nom changé : gardé en blanc comme celui de la base ({{color:#ffffff}})",
          up["name_user"] == "{{color:#ffffff}}Emma ♡{{/color}}" and pv.page_de(TW, MOI)["champs"]["nom"] == "Emma ♡",
          up.get("name_user"))
    REGLE["vieille_image"] = True
    APPELS.clear()
    r = pv.modifier_page(TW, MOI, photo=j)
    check("photo refusée par GetMySocial (image par défaut) : dit, rien posé, page temporaire supprimée",
          not r["ok"] and "refusée" in r["erreur"] and not [a for a in APPELS if a[0] == "update"]
          and any(a[0] == "delete" for a in APPELS), (r, APPELS))
    REGLE["vieille_image"] = False
    REGLE["relu_autre"] = True
    r = pv.modifier_page(TW, MOI, nom="Nouveau")
    check("relu autrement : dit (pas de faux « à jour »)", not r["ok"] and "name_user" in r["erreur"], r)
    REGLE["relu_autre"] = False
    r = pv.modifier_page(TW, MOI)
    check("rien à changer : rien envoyé", r["ok"] and r["faits"] == [])
    check("sans page : refusé", not pv.modifier_page(TW, AUTRE, nom="x")["ok"])

    # ── 5. la page suit le lien direct ───────────────────────────────────
    print("5. Bascule")
    APPELS.clear()
    pv.suivre_bascule(TW, MOI, False)
    pv.suivre_bascule(TW, MOI, False)
    check("lien coupé : la page coupée, une fois", [a[0] for a in APPELS] == ["disable"]
          and pv.page_de(TW, MOI)["actif"] is False, APPELS)
    APPELS.clear()
    pv.suivre_bascule(TW, MOI, True)
    check("rallumé : la page aussi", [a[0] for a in APPELS] == ["enable"] and pv.page_de(TW, MOI)["actif"] is True)
    _vrai_bs = lv._basculer_sans_page
    try:
        import threading as _th
        lv._basculer_sans_page = lambda g, u, a: {"ok": True}
        APPELS.clear()
        retenue = _th.Event()
        _vdis = gms.disable_link
        gms.disable_link = lambda lid: (retenue.wait(5), _vdis(lid))[1]
        import verif_discord as vd
        MENUS_FOND = []
        tk._maj_menu_v2 = lambda g, u, *a, **k: MENUS_FOND.append((g, u, vd._SERVEUR_COURANT.get())) or 0
        t0 = time.time()
        with vd.sur_serveur(TW):
            r_off = lv.basculer(TW, MOI, False)
            rendu_vite = time.time() - t0 < 1 and not APPELS
            r_on = lv.basculer(TW, MOI, True)
        retenue.set()
        pv._FILE.join()
        gms.disable_link = _vdis
        check("… puis le menu du ticket est remis à jour (une fois par bascule), sous le serveur du clic",
              MENUS_FOND == [(TW, MOI, TW), (TW, MOI, TW)], MENUS_FOND)
        check("liens_va.basculer : rend la main sans attendre GetMySocial (la page suit en fond)",
              r_off == {"ok": True} and r_on == {"ok": True} and rendu_vite, (r_off, APPELS))
        check("… et dans l'ordre : coupée puis rallumée", [a[0] for a in APPELS] == ["disable", "enable"]
              and pv.page_de(TW, MOI)["actif"] is True, APPELS)
        # jamais le vrai ici : il lirait data/tickets.json et enverrait un PATCH
        # à Discord (MOI est le vrai uid du propriétaire) ; SAV le remet à la fin
        tk._maj_menu_v2 = lambda g, u, *a, **k: 0
        pv.EN_FOND = lambda f: f()      # la suite, sans fil
        APPELS.clear()
        lv.basculer(TW, MOI, False)
        coupe = [a[0] for a in APPELS]
        lv.basculer(TW, MOI, True)
        check("liens_va.basculer (le vrai) : la page coupée puis rallumée avec le direct",
              coupe == ["disable"] and [a[0] for a in APPELS] == ["disable", "enable"], APPELS)
        lv._basculer_sans_page = lambda g, u, a: {"ok": False, "erreur": "x"}
        APPELS.clear()
        lv.basculer(TW, MOI, False)
        check("… le direct refusé : la page ne bouge pas", not APPELS, APPELS)
        lv._basculer_sans_page = lambda g, u, a: {"ok": True}
        _sb = pv.suivre_bascule
        pv.suivre_bascule = lambda *a: (_ for _ in ()).throw(RuntimeError("panne"))
        check("… une panne du suivi ne remonte pas", lv.basculer(TW, MOI, True) == {"ok": True})
        pv.suivre_bascule = _sb
    finally:
        lv._basculer_sans_page = _vrai_bs
    gms.disable_link = lambda lid: (APPELS.append(("disable", lid)) or {"ok": False, "error": "429"})
    APPELS.clear()
    pv.suivre_bascule(TW, MOI, False)
    check("coupure refusée par GetMySocial : notée « a_couper »", pv.page_de(TW, MOI).get("a_couper") is True)
    gms.disable_link = f_disable

    # ── 5b. la reprise (synchro des liens) ───────────────────────────────
    print("5b. Reprise")
    FICHES[f"{TW}:{MOI}"]["actif"] = False
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    check("direct coupé, page restée vivante : coupée à la reprise",
          MOI in bl["coupees"] and pv.page_de(TW, MOI)["actif"] is False
          and not pv.page_de(TW, MOI).get("a_couper"), bl)
    FICHES[f"{TW}:{MOI}"]["actif"] = True
    pv.suivre_bascule(TW, MOI, True)
    FICHES[f"{TW}:{MOI}"]["tracking"] = "https://onlyfans.com/liasxcret/c999"
    POSES.clear()
    AB.clear()
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    lidm = pv.page_de(TW, MOI)["link_id"]
    check("tracking du direct changé (changement de model) : le bouton de la page suit, pays refaits, pas de 70/30",
          MOI in bl["trackings"] and POSES == [(lidm, "https://onlyfans.com/liasxcret/c999")]
          and ("pays", lidm) in APPELS and not AB
          and pv.page_de(TW, MOI)["tracking"] == "https://onlyfans.com/liasxcret/c999", (bl, POSES, AB))
    FICHES[f"{TW}:{MOI}"]["tracking"] = FICHE["tracking"]
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(manques=["70/30"], essais={}, tracking=FICHE["tracking"])
    pv._ecrire(d0)
    AB.clear()
    pv.reprendre_pages(TW)
    check("une ancienne étape 70/30 tombe, sans rien poser", not AB and pv.page_de(TW, MOI)["manques"] == [], AB)
    lv.poser_pays = lambda lid, eq, *a: {"ok": False, "erreur": "x"}
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(manques=["pays"], essais={})
    pv._ecrire(d0)
    for _ in range(4):
        pv.reprendre_pages(TW)
    pg5 = pv.page_de(TW, MOI)
    check("étape ratée : ESSAIS_REPRISE fois, puis « a_verifier » (compté par étape)",
          pg5["manques"] == ["pays"] and pg5["essais"].get("pays") == pv.ESSAIS_REPRISE and pg5["a_verifier"] is True, pg5)
    lv.poser_pays = lambda lid, eq, *a: (APPELS.append(("pays", lid)) or {"ok": True})
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(essais={})
    pv._ecrire(d0)
    bl = pv.reprendre_pages(TW)
    check("… reprise réussie : plus rien à faire", MOI in bl["reprises"] and pv.page_de(TW, MOI)["manques"] == [], bl)
    # tracking changé mais page illisible : rien noté (re-tenté au passage suivant)
    FICHES[f"{TW}:{MOI}"]["tracking"] = "https://onlyfans.com/liasxcret/c777"
    _vrai_get = gms.get_link
    gms.get_link = lambda lid, team_id=None: {"ok": False, "error": "429"}
    bl = pv.reprendre_pages(TW)
    check("tracking changé, page illisible : le tracking n'est PAS noté suivi",
          pv.page_de(TW, MOI)["tracking"] == FICHE["tracking"] and bl["rates"], bl)
    gms.get_link = _vrai_get
    bl = pv.reprendre_pages(TW)
    check("… lisible au passage suivant : re-pointée", MOI in bl["trackings"]
          and pv.page_de(TW, MOI)["tracking"] == "https://onlyfans.com/liasxcret/c777", bl)
    FICHES[f"{TW}:{MOI}"]["tracking"] = FICHE["tracking"]
    pv.reprendre_pages(TW)
    # rallumage, page ratée vivante, création interrompue, manager changé
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(actif=False, a_rallumer=True)
    pv._ecrire(d0)
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    check("direct en service, page coupée (rallumage raté avant) : rallumée",
          MOI in bl["rallumees"] and pv.page_de(TW, MOI)["actif"] is True and any(a[0] == "enable" for a in APPELS), bl)
    d0 = pv._lire()
    d0["pages"][f"{TW}:{VA}"].update(etat="ratee", actif=True, a_couper=True)
    pv._ecrire(d0)
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    check("page ratée encore vivante (coupure ratée) : coupée par la reprise, jamais rallumée",
          VA in bl["coupees"] and pv.page_de(TW, VA)["actif"] is False and not any(a[0] == "enable" for a in APPELS), bl)
    d0 = pv._lire()
    d0["pages"][f"{TW}:{VA}"].update(etat="en_cours", actif=True, a_couper=False, quand=int(time.time()) - 3600)
    pv._ecrire(d0)
    bl = pv.reprendre_pages(TW)
    check("création interrompue (redémarrage) depuis longtemps : coupée, notée ratée",
          VA in bl["coupees"] and pv.page_de(TW, VA)["etat"] == "ratee", bl)
    FICHES[f"{TW}:{MOI}"]["groupe"] = "Manager PAUL"
    APPELS.clear()
    pv.reprendre_pages(TW)
    check("VA passé chez un autre manager : la page suit", ("ranger", pv.page_de(TW, MOI)["link_id"], "Manager PAUL") in APPELS
          and pv.page_de(TW, MOI)["groupe"] == "Manager PAUL", APPELS)
    FICHES[f"{TW}:{MOI}"]["groupe"] = FICHE["groupe"]
    # page temporaire d'images non supprimée : coupée, notée, supprimée à la reprise
    gms.delete_link = lambda lid: (APPELS.append(("delete", lid)) or {"ok": False, "error": "x"})
    pv._retirer_temporaire(EQ, "pgimgx", "lnk_tmp_x")
    check("page temporaire non supprimée : coupée et notée", "lnk_tmp_x" in (pv._lire().get("orphelines") or {})
          and ("disable", "lnk_tmp_x") in APPELS)
    gms.delete_link = f_delete
    d_o = pv._lire()
    d_o["orphelines"]["lnk_tmp_x"]["equipe"] = "tm_autre_serveur"
    pv._ecrire(d_o)
    APPELS.clear()
    pv.reprendre_pages(TW)
    check("une orpheline d'une autre équipe : laissée à la reprise de son serveur",
          "lnk_tmp_x" in (pv._lire().get("orphelines") or {}) and ("delete", "lnk_tmp_x") not in APPELS, APPELS)
    d_o = pv._lire()
    d_o["orphelines"]["lnk_tmp_x"]["equipe"] = EQ
    pv._ecrire(d_o)
    pv.reprendre_pages(TW)
    check("… supprimée à la reprise suivante", "lnk_tmp_x" not in (pv._lire().get("orphelines") or {}))
    src = (BOT / "liens_va.py").read_text(encoding="utf-8")
    # essais remis à zéro pour de bon (pas fusionnés)
    pv._noter(TW, MOI, essais={"pays": 3})
    pv._noter(TW, MOI, essais={})
    check("un compteur remis à {} est vraiment vidé", pv.page_de(TW, MOI)["essais"] == {})
    # une page au rallumage incertain (a_rallumer) est coupée quand le direct l'est
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(actif=False, a_rallumer=True, a_couper=False)
    pv._ecrire(d0)
    APPELS.clear()
    pv.suivre_bascule(TW, MOI, False)
    check("enable incertain puis VA coupé : la page est coupée quand même",
          ("disable", pv.page_de(TW, MOI)["link_id"]) in APPELS and not pv.page_de(TW, MOI).get("a_rallumer"), APPELS)
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(actif=False, a_rallumer=True)
    pv._ecrire(d0)
    FICHES[f"{TW}:{MOI}"]["actif"] = False
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    check("… et par la reprise (direct coupé)", MOI in bl["coupees"] and not pv.page_de(TW, MOI).get("a_rallumer"), bl)
    FICHES[f"{TW}:{MOI}"]["actif"] = True
    pv.reprendre_pages(TW)
    # le plafond par passage ne bloque ni coupures ni rallumages
    _vrai_plaf = pv.PAGES_PAR_PASSE
    pv.PAGES_PAR_PASSE = 0
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(actif=False, manques=["pays"], essais={})
    pv._ecrire(d0)
    APPELS.clear()
    bl = pv.reprendre_pages(TW)
    check("plafond atteint : le rallumage passe quand même ; le reste attend (sans compter)",
          MOI in bl["rallumees"] and pv.page_de(TW, MOI)["essais"] == {} and pv.page_de(TW, MOI)["manques"] == ["pays"], bl)
    pv.PAGES_PAR_PASSE = _vrai_plaf
    pv.reprendre_pages(TW)
    check("la synchro des liens (30 min) lance la reprise des pages du pilote",
          "pages_va.reprendre_pages(gid)" in src and "_synchroniser_sans_pages = synchroniser" in src)
    _vs, _vr, _vpil = lv._synchroniser_sans_pages, pv.reprendre_pages, pv.PILOTE.get(TW)
    REPRISES = []
    lv._synchroniser_sans_pages = lambda g: {}
    pv.reprendre_pages = lambda g: (REPRISES.append(str(g)) or {})
    pv.PILOTE.pop(TW, None)             # serveur refermé, ses pages restent notées
    try:
        lv.synchroniser(TW)
        lv.synchroniser("999")          # ni pilote ni page : rien
    finally:
        lv._synchroniser_sans_pages, pv.reprendre_pages = _vs, _vr
        if _vpil is not None:
            pv.PILOTE[TW] = _vpil
    check("… et de tout serveur qui a des pages notées, même refermé (vrai appel de synchroniser)",
          REPRISES == [TW] and pv.a_des_pages(TW) and not pv.a_des_pages("999"), REPRISES)

    # ── 6. le menu et la fenêtre ─────────────────────────────────────────
    print("6. Menu et fenêtre")

    def textes(c):
        out, pile = [], list(c or [])
        while pile:
            x = pile.pop(0)
            if isinstance(x, dict):
                if x.get("type") == 10:
                    out.append(x["content"])
                pile += list(x.get("components") or [])
                if isinstance(x.get("accessory"), dict):
                    pile.append(x["accessory"])
        return out

    def ids(c):
        out, pile = [], list(c or [])
        while pile:
            x = pile.pop(0)
            if isinstance(x, dict):
                if x.get("custom_id"):
                    out.append(x["custom_id"])
                pile += list(x.get("components") or [])
                if isinstance(x.get("accessory"), dict):
                    pile.append(x["accessory"])
        return out
    tk._etat = lambda: {"tickets": {f"{TW}:{MOI}": {"salon": "T1"}}}
    corps = tk._corps_menu(TW, MOI, [])
    t = textes(corps)
    i_lien = next(k for k, x in enumerate(t) if x.startswith("**🔗 Ton lien**"))
    check("pilote : « 📄 Ta page » juste sous « 🔗 Ton lien », avec ✏️ Modifier",
          t[i_lien + 1].startswith("**📄 Ta page**\nhttps://getmysocial.com/") and f"page:o:{MOI}" in ids(corps), t)
    FICHES[f"{TW}:{VA}"]["actif"] = True
    check("un membre sans lien direct : menu inchangé",
          tk._corps_menu(TW, AUTRE, []) == tk._corps_menu_sans_page(TW, AUTRE, []))
    check("Twitter : une seule page, jamais de « Page 2 » à créer",
          not [c for c in ids(tk._corps_menu(TW, MOI, [])) if c.startswith("page:new2")]
          and "1 page(s) au plus" in pv.creer_page(TW, MOI, n=2)["erreur"])
    _vf = tk._fiche
    tk._fiche = lambda g, u: {"parti": 1}
    check("parti : ni lien ni page dans son menu", tk._section_page(TW, MOI) is None)
    tk._fiche = _vf
    d = pv._lire()
    d["pages"][f"{TW}:{MOI}"]["actif"] = False
    pv._ecrire(d)
    check("page coupée : « 🚫 Désactivée pour le moment », sans bouton",
          "**📄 Ta page**\n🚫 Désactivée pour le moment" in textes(tk._corps_menu(TW, MOI, []))
          and f"page:o:{MOI}" not in ids(tk._corps_menu(TW, MOI, [])))
    d["pages"][f"{TW}:{MOI}"]["actif"] = True
    sauve = d["pages"].pop(f"{TW}:{MOI}")
    pv._ecrire(d)
    check("lien direct sans page : « 📄 Créer »", f"page:new:{MOI}" in ids(tk._corps_menu(TW, MOI, [])))
    FICHES[f"{TW}:{MOI}"]["actif"] = False
    check("… direct désactivé : pas de « 📄 Créer » (la page naîtrait morte)",
          not [c for c in ids(tk._corps_menu(TW, MOI, [])) if c.startswith("page:")]
          and "**🔗 Ton lien**" in "".join(textes(tk._corps_menu(TW, MOI, []))))
    FICHES[f"{TW}:{MOI}"]["actif"] = True
    d["pages"][f"{TW}:{MOI}"] = dict(sauve, etat="ratee")
    pv._ecrire(d)
    check("page ratée : « À reprendre » avec 🔁 Réessayer (manager)",
          "**📄 Ta page**\n-# À reprendre" in textes(tk._corps_menu(TW, MOI, []))
          and f"page:new:{MOI}" in ids(tk._corps_menu(TW, MOI, [])))
    FICHES[f"{TW}:{MOI}"]["actif"] = False
    check("… direct désactivé : « 🚫 Désactivée », sans 🔁 Réessayer",
          "**📄 Ta page**\n🚫 Désactivée pour le moment" in textes(tk._corps_menu(TW, MOI, []))
          and f"page:new:{MOI}" not in ids(tk._corps_menu(TW, MOI, [])))
    FICHES[f"{TW}:{MOI}"]["actif"] = True
    d["pages"][f"{TW}:{MOI}"] = sauve
    pv._ecrire(d)
    f = tk.fenetre_page(TW, MOI)
    comps = f["data"]["components"]
    check("fenêtre : 5 composants — photo, nom, bio, bouton, image de fond (facultatives) ; préremplie",
          f["type"] == 9 and f["data"]["custom_id"] == f"page:f:{MOI}" and len(comps) == 5
          and comps[0]["component"]["type"] == 19 and comps[0]["component"]["required"] is False
          and comps[1]["component"].get("value") == pv.page_de(TW, MOI)["champs"]["nom"]
          and comps[2]["component"]["style"] == 2
          and comps[3]["component"].get("value") == "Mon OF 🔥"
          and comps[4]["component"]["type"] == 19 and comps[4]["component"]["custom_id"] == "fond"
          and comps[4]["component"]["required"] is False, comps)
    d["pages"][f"{TW}:{MOI}"]["champs"]["nom"] = "x" * 60
    pv._ecrire(d)
    check("un texte trop long n'est pas prérempli (Discord refuserait la fenêtre)",
          "value" not in tk.fenetre_page(TW, MOI)["data"]["components"][1]["component"])
    d["pages"][f"{TW}:{MOI}"]["champs"]["nom"] = "Lia x"
    pv._ecrire(d)

    # ── 7. les clics ─────────────────────────────────────────────────────
    print("7. Clics")
    tk.role_manager = lambda g: "R_MANAGER"
    tk.role_helper = lambda g: ""
    SUITES, MAJ = [], []
    tk._suite = lambda jeton, texte, p=None: SUITES.append(texte)
    tk._maj_menu_v2 = lambda g, u, *a, **k: MAJ.append(u) or 200
    tk._EN_FOND = lambda f: f()
    # le fil d'un ✅ attend la réponse type 7 avant son PATCH, et la liste ✏️
    # redessine le menu après la fenêtre : ici tout tourne sur place
    tk.ATTENTE_AVANT_PATCH_S = 0
    tk.REDESSIN_LISTE_S = 0
    gms.pause_restante = lambda genre="lecture": 0

    def clic(cid, qui=MOI, typ=3, comps=None, resolved=None, perms="0"):
        p = {"type": typ, "guild_id": TW, "channel_id": "T1", "token": "jeton", "application_id": "app",
             "member": {"user": {"id": qui}, "roles": [], "permissions": perms},
             "data": {"custom_id": cid}, "message": {"id": "m", "flags": 32768}}
        if comps is not None:
            p["data"]["components"] = comps
        if resolved is not None:
            p["data"]["resolved"] = resolved
        return p
    r = tk.traiter(clic(f"page:o:{MOI}"))
    # 06/11 : sur Twitter, ✏️ propose d'abord un look (tests_pages_looks.py),
    # « ✏️ Modifier moi-même » (page:m) ouvre la fenêtre
    check("✏️ Modifier (Twitter) : le choix du look, avec « Modifier moi-même »",
          r.get("type") == 4 and f"page:m:{MOI}" in json.dumps(r), r)
    r = tk.traiter(clic(f"page:m:{MOI}"))
    check("✏️ Modifier moi-même : la fenêtre s'ouvre", r.get("type") == 9 and r["data"]["custom_id"] == f"page:f:{MOI}", r)
    r = tk.traiter(clic(f"page:o:{MOI}", qui=AUTRE))
    check("un autre membre (pas manager) : refusé", r["type"] == 4 and r["data"]["flags"] == 64, r)
    r = tk.traiter(clic(f"page:o:{AUTRE}", qui=AUTRE))
    check("✏️ Modifier sans page : refusé", r["type"] == 4 and "Pas encore de page" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:o2:{MOI}"))
    check("une place au-delà du plafond (page 2 sur Twitter) : refusée",
          r["type"] == 4 and "Pas encore ouvert" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:oo:{MOI}"))
    check("un custom_id abîmé : « Action inconnue. »", r["data"].get("content") == "Action inconnue.", r)

    def fen(nom="Lia x", bio="hello\nworld", bouton="Mon OF 🔥", fond=None, photo=None):
        return [{"type": 18, "component": {"type": 19, "custom_id": "photo", "values": photo or []}},
                {"type": 18, "component": {"type": 4, "custom_id": "nom", "value": nom}},
                {"type": 18, "component": {"type": 4, "custom_id": "bio", "value": bio}},
                {"type": 18, "component": {"type": 4, "custom_id": "bouton", "value": bouton}},
                {"type": 18, "component": {"type": 19, "custom_id": "fond", "values": fond or []}}]
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen()))
    check("fenêtre renvoyée sans changement : « Rien n'a changé. », rien envoyé",
          r["type"] == 4 and r["data"]["content"] == "Rien n'a changé.", r)
    VUS = []
    _vrai_mod = pv.modifier_page
    pv.modifier_page = lambda g, u, **k: (VUS.append(k) or {"ok": True, "faits": list(k)})
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(nom="Nouveau")))
    check("seuls les champs changés partent (le nom), en fond ; « ✅ Ta page est à jour. »",
          r == {"type": 5, "data": {"flags": 64}} and VUS[-1] == {"nom": "Nouveau", "bio": None, "bouton": None,
                                                                   "photo": None, "fond": None, "n": 1}
          and SUITES[-1] == "✅ Ta page est à jour.", (r, VUS, SUITES))
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(bio="")))
    check("la bio vidée : voulue (le champ était prérempli)", VUS[-1]["bio"] == "", VUS[-1])
    d2 = pv._lire()
    d2["pages"][f"{TW}:{MOI}"]["champs"]["bio"] = "y" * 200
    pv._ecrire(d2)
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(bio="")))
    check("bio trop longue pour être préremplie : revenue vide = gardée, pas effacée",
          r["data"].get("content") == "Rien n'a changé.", r)
    d2["pages"][f"{TW}:{MOI}"]["champs"]["bio"] = "hello\nworld"
    pv._ecrire(d2)
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(nom="")))
    check("un nom vidé : gardé (rien à changer)", r["data"].get("content") == "Rien n'a changé.", r)
    att = {"attachments": {"9": {"url": "https://cdn.discordapp.com/x.png", "content_type": "application/pdf",
                                 "size": 100}}}
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(photo=["9"]), resolved=att))
    check("une pièce qui n'est pas une image : refusée tout de suite", "pas une image" in r["data"]["content"], r)
    att["attachments"]["9"].update(content_type="image/png", size=pv.PHOTO_MAX + 1)
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(photo=["9"]), resolved=att))
    check("une image trop lourde : refusée tout de suite", "trop lourde" in r["data"]["content"], r)
    att["attachments"]["9"].update(size=1000)
    tk._telecharger_image = lambda url, plafond: (b.getvalue(), "")
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(photo=["9"]), resolved=att))
    check("une photo déposée : téléchargée, préparée (JPEG), envoyée",
          VUS[-1]["photo"] and VUS[-1]["photo"][:2] == b"\xff\xd8" and VUS[-1]["fond"] is None, str(VUS[-1])[:200])
    att["attachments"]["8"] = dict(att["attachments"]["9"])
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(fond=["8"]), resolved=att))
    imv = Image.open(io.BytesIO(VUS[-1]["fond"])) if VUS[-1].get("fond") else None
    check("une image de fond déposée : préparée en 9:16, envoyée (la photo reste)",
          imv is not None and imv.size == (1080, 1920) and VUS[-1]["photo"] is None, str(VUS[-1])[:200])
    att["attachments"]["8"]["content_type"] = "text/plain"
    r = tk.traiter(clic(f"page:f:{MOI}", typ=5, comps=fen(fond=["8"]), resolved=att))
    check("un fond qui n'est pas une image : refusé tout de suite", "pas une image" in r["data"]["content"], r)
    pv.modifier_page = _vrai_mod
    APPELS.clear()
    r = tk.traiter(clic(f"page:new:{MOI}", perms=str(0x8)))
    check("📄 Créer (manager) : déjà une page → dit, rien recréé",
          r == {"type": 5, "data": {"flags": 64}} and SUITES[-1].startswith("✅ Ta page")
          and not [a for a in APPELS if a[0] == "duplicate"], (r, SUITES[-1]))
    d1 = pv._lire()
    d1["pages"][f"{TW}:{MOI}"]["manques"] = ["safe page"]
    pv._ecrire(d1)
    tk.traiter(clic(f"page:new:{MOI}", perms=str(0x8)))
    check("📄 Créer : les étapes manquées sont dites (« ⚠️ À reprendre »)", "⚠️ À reprendre : safe page" in SUITES[-1],
          SUITES[-1])
    d1["pages"][f"{TW}:{MOI}"]["manques"] = []
    pv._ecrire(d1)
    r = tk.traiter(clic(f"page:new:{MOI}", qui=AUTRE))
    check("📄 Créer par un autre membre (pas manager) : refusé",
          r["type"] == 4 and "Seul ce VA ou son manager" in r["data"]["content"], r)
    n_suites = len(SUITES)
    r = tk.traiter(clic(f"page:new:{MOI}", qui=MOI))
    check("📄 Créer par le VA lui-même (sans être manager) : accepté",
          r == {"type": 5, "data": {"flags": 64}} and len(SUITES) == n_suites + 1
          and SUITES[-1].startswith("✅ Ta page"), (r, SUITES[-1:]))
    check("un clic d'un autre module passe son chemin", tk._page(clic("usdc:set:1")) is None)

    # ── 7b. TRUST INSTAGRAM : 3 pages fixes, des pages à la demande, le 70/30 ─
    print("7b. TRUST INSTAGRAM : pages fixes, demandes, 70/30")
    VI, VI_COUPE, VI_PARTI, VI_SANS, VI5, VI6 = "4100", "4101", "4102", "4103", "4105", "4106"
    MGR, MGR2, HELPER = "5001", "5002", "5003"
    TRK = "https://onlyfans.com/liasxcret/c400"

    def fiche_ig(numero, pseudo, **k):
        return dict(FICHE, numero=numero, pseudo=pseudo, tracking=TRK, link_id=f"lnk_direct_{pseudo}",
                    public_url=f"https://getmysocial.com/direct{pseudo}", **k)
    FICHES[f"{AG}:{VI}"] = fiche_ig(141, "vaig")
    FICHES[f"{AG}:{VI_COUPE}"] = fiche_ig(142, "vacoupe", actif=False)
    FICHES[f"{AG}:{VI_PARTI}"] = fiche_ig(143, "vaparti")
    FICHES[f"{AG}:{VI_SANS}"] = dict(fiche_ig(144, "vasans"), tracking="")
    FICHES[f"{AG}:{VI5}"] = dict(fiche_ig(145, "vacinq"), tracking="https://onlyfans.com/liasxcret/c405")
    TICKETS = {f"{TW}:{MOI}": {"salon": "T1"}, f"{AG}:{VI}": {"salon": "T9"},
               f"{AG}:{VI_PARTI}": {"salon": "T11", "parti": {"quand": 1}}, f"{AG}:{VI5}": {"salon": "T15"},
               f"{AG}:{VI6}": {"salon": "T16"}}
    tk._etat = lambda: {"tickets": TICKETS}
    lv._etat = lambda: {"liens": FICHES}
    lv.espace = lambda g="": dict({"equipe": EQ}, **({"plateforme": "Instagram"} if str(g) == AG else {}))
    pv._FIL = lambda f: f()
    COOKIE = {"ok": True}
    pv._cookie_ok = lambda: COOKIE["ok"]
    POSTS = []

    def f_api_reseau(m, chemin, **kw):
        POSTS.append((m, chemin, json.loads(json.dumps(kw.get("json")))))
        if m == "POST" and REGLE.get("post_discord", 200) != 200:
            return REGLE["post_discord"], {"message": "refus"}
        return 200, ({"id": f"M{len(POSTS)}"} if m == "POST" else {})
    tk._api_reseau = f_api_reseau

    def clic_ig(cid, qui=VI, typ=3, roles=None, perms="0", comps=None, values=None, mid="M0", salon="T9"):
        q = {"type": typ, "guild_id": AG, "channel_id": salon, "token": "jeton", "application_id": "app",
             "member": {"user": {"id": qui}, "roles": list(roles or []), "permissions": perms},
             "data": {"custom_id": cid}, "message": {"id": mid, "flags": 0}}
        if comps is not None:
            q["data"]["components"] = comps
        if values is not None:
            q["data"]["values"] = values
        return q

    def dups(depuis=0):
        """Les copies demandées (une adresse déjà prise refait une copie sous
        une autre adresse : une seule par nom de page, la dernière)."""
        par_nom = {}
        for a in APPELS[depuis:]:
            if a[0] == "duplicate":
                par_nom.pop(a[3], None)
                par_nom[a[3]] = a
        return list(par_nom.values())

    # ── le menu avant toute page ──
    sec = tk._sections_page(AG, VI)
    check("aucune page : « 📄 Tes pages », les 3 places « ⏳ en préparation », ➕ Demander une page",
          textes(sec) == ["**📄 Tes pages**\nPage 1 · ⏳ en préparation\nPage 2 · ⏳ en préparation\n"
                          "Page 3 · ⏳ en préparation"] and ids(sec) == [f"pgd:new:{VI}"], sec)
    check("le message du menu ne garde aucun « 📄 Créer » sur TRUST INSTAGRAM (création d'office)",
          not [c for c in ids(tk._corps_menu(AG, VI, [])) if c.startswith("page:new")])

    # ── création automatique ──
    print("7b-1. Création automatique des places fixes")
    APPELS.clear()
    POSES.clear()
    AB.clear()
    MAJ.clear()
    bl = pv.creer_pages_manquantes(AG)
    d1 = dups()
    check("un passage : CREATIONS_PAR_PASSE (3) créations, la page 1 de chacun avant la page 2 de personne",
          pv.CREATIONS_PAR_PASSE == 3 and bl["creees"] == [VI, VI5, f"{VI}#2"] and bl["restent"] == 3
          and len(d1) == 3, (bl, d1))
    check("chaque place copie SON gabarit : brune (page 1), blonde (page 2)",
          [a[1] for a in d1] == [GAB_BRUNE, GAB_BRUNE, GAB_BLONDE], d1)
    check("VA coupé, parti, sans tracking : écartés ET comptés (rien en silence)",
          bl["ignores"] == {"sans_lien": 1, "coupe": 1, "parti": 1}
          and not [a for a in d1 if "vacoupe" in a[3] or "vaparti" in a[3] or "vasans" in a[3]], bl)
    p1 = pv.page_de(AG, VI)
    check("page 1 : nommée « Instagram VA 141 @vaig page », sur le tracking du VA, prête, menu remis à jour",
          p1.get("nom") == "Instagram VA 141 @vaig page" and p1.get("etat") == "prete"
          and (p1["link_id"], TRK) in POSES and VI in MAJ, (p1, POSES, MAJ))
    check("70/30 posé sur chaque page, avec SON id, son tracking, son adresse (et la safe page des 30 %)",
          len(AB) == 3 and AB[0] == {"link_id": p1["link_id"], "tracking": TRK, "shortcode": p1["shortcode"], "safe_page": True}
          and AB[1]["tracking"] == "https://onlyfans.com/liasxcret/c405"
          and p1.get("ab", {}).get("ok") is True and p1.get("manques") == [], (AB, p1))
    check("pays, safe page, rangée chez son manager, comme Twitter",
          ("pays", p1["link_id"]) in APPELS and ("ranger", p1["link_id"], "Manager JOHN") in APPELS
          and any(a[0] == "update" and a[1] == p1["link_id"] and a[2].get("bot_protection") == {"mode": "safe_page"}
                  for a in APPELS), APPELS)
    n_dup = len(APPELS)
    bl = pv.reprendre_pages(AG)
    d2 = dups(n_dup)
    check("la reprise (synchro des liens) lance la suite : les 3 places restantes, liatemplate pour la 3",
          sorted(a[3] for a in d2) == sorted(["Instagram VA 141 @vaig page 3", "Instagram VA 145 @vacinq page 2",
                                              "Instagram VA 145 @vacinq page 3"])
          and {a[1] for a in d2 if a[3].endswith("page 3")} == {GAB_TEMPLATE}, d2)
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    check("tout est prêt : plus rien créé au passage suivant", not dups(n_dup) and not bl["creees"], bl)
    check("jamais de fiche « uid#n » sans page dans le registre des pages",
          all(isinstance(v, dict) and v.get("link_id") for v in pv._lire()["pages"].values()))
    sec = tk._sections_page(AG, VI)
    t0 = textes(sec)[0]
    check("menu : les 3 adresses, sans ✏️ (fixes), puis ➕",
          t0.startswith("**📄 Tes pages**\nPage 1 · https://getmysocial.com/")
          and t0.count("https://getmysocial.com/") == 3 and ids(sec) == [f"pgd:new:{VI}"], sec)
    check("Twitter : jamais de création automatique (le VA clique 📄 Créer)",
          pv.creer_pages_manquantes(TW)["creees"] == [] and pv.lancer_creations(TW) == "rien")
    pv._LOT_CREATIONS.acquire()
    try:
        check("un lot qui tourne encore : le passage suivant n'en lance pas un second (verrou non bloquant)",
              pv.lancer_creations(AG) == "occupee")
    finally:
        pv._LOT_CREATIONS.release()
    check("… et le verrou est rendu après un lot", pv.lancer_creations(AG) == "lancee"
          and pv._LOT_CREATIONS.acquire(blocking=False) and (pv._LOT_CREATIONS.release() or True))

    # une page ratée ne bloque pas les autres ; compteur d'essais par place
    FICHES[f"{AG}:{VI6}"] = fiche_ig(146, "vasix")
    REGLE["dup_refus"] = {GAB_BRUNE}
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    check("page 1 refusée par GetMySocial : les pages 2 et 3 créées quand même (plus de « page n-1 prête »)",
          bl["creees"] == [f"{VI6}#2", f"{VI6}#3"] and len(bl["ratees"]) == 1
          and not pv.page_de(AG, VI6).get("link_id"), bl)
    check("… place sans page : « ⏳ en préparation » (pas de fiche vide dans « pages »)",
          "Page 1 · ⏳ en préparation" in textes(tk._sections_page(AG, VI6))[0]
          and f"{AG}:{VI6}" not in pv._lire()["pages"])
    for _ in range(3):
        bl = pv.creer_pages_manquantes(AG)
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    check("ESSAIS_CREATION échecs : la place passe « à vérifier », n'est plus tentée, dite au journal",
          pv.creation_a_verifier(AG, VI6, 1) and VI6 in bl["a_verifier"] and not dups(n_dup)
          and (pv._lire().get("creations") or {}).get(f"{AG}:{VI6}", {}).get("essais") == pv.ESSAIS_CREATION, bl)
    check("… menu : « ⚠️ à reprendre »", "Page 1 · ⚠️ à reprendre" in textes(tk._sections_page(AG, VI6))[0])
    REGLE["dup_refus"] = set()
    d0 = pv._lire()
    d0["creations"].pop(f"{AG}:{VI6}")
    pv._ecrire(d0)
    bl = pv.creer_pages_manquantes(AG)
    check("… sa clé retirée de « creations » : recréée, compteur effacé",
          bl["creees"] == [VI6] and f"{AG}:{VI6}" not in (pv._lire().get("creations") or {}), bl)
    _vplaf = pv.CREATIONS_PAR_PASSE
    pv.CREATIONS_PAR_PASSE = 0
    FICHES[f"{AG}:9999"] = fiche_ig(199, "vaneuf")
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    check("plafond à 0 : rien créé, tout « restent »", not dups(n_dup) and bl["restent"] == 3, bl)
    pv.CREATIONS_PAR_PASSE = _vplaf
    FICHES.pop(f"{AG}:9999")

    # ── le 70/30 : attente du cookie, reprise, plafond, rattrapage ──
    print("7b-2. Le 70/30 des pages")
    lid1 = pv.page_de(AG, VI)["link_id"]
    d0 = pv._lire()
    d0["pages"][f"{AG}:{VI}"].update(manques=["70/30"], essais={}, ab={"ok": False})
    pv._ecrire(d0)
    COOKIE["ok"] = False
    AB.clear()
    for _ in range(4):
        bl = pv.reprendre_pages(AG)
    pg = pv.page_de(AG, VI)
    check("cookie absent : le 70/30 n'est pas tenté, attend SANS compter d'essai (ni « à vérifier »)",
          not AB and pg["manques"] == ["70/30"] and not (pg.get("essais") or {}).get("70/30")
          and not pg.get("a_verifier") and bl["ab_en_attente"] >= 1
          and not [r for r in bl["rates"] if r.startswith(VI + " ")], (AB, pg, bl))
    COOKIE["ok"] = True
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": False, "cookie": True,
                                                                       "erreur": "cookie refusé"})
    bl = pv.reprendre_pages(AG)
    pg = pv.page_de(AG, VI)
    check("cookie refusé par GetMySocial : jamais compté, les suivantes attendent aussi",
          len(AB) == 1 and not (pg.get("essais") or {}).get("70/30") and pg["manques"] == ["70/30"], (AB, pg))
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": True})
    AB.clear()
    bl = pv.reprendre_pages(AG)
    pg = pv.page_de(AG, VI)
    check("cookie revenu : posé à la reprise sur la page (son id, son tracking), noté ok",
          AB == [{"link_id": lid1, "tracking": TRK, "shortcode": pg["shortcode"], "safe_page": True}] and pg["manques"] == []
          and pg["ab"]["ok"] is True and VI in bl["reprises"], (AB, pg, bl))
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": False, "erreur": "A/B inattendu"})
    d0 = pv._lire()
    d0["pages"][f"{AG}:{VI}"].update(manques=["70/30"], essais={}, ab={"ok": False})
    pv._ecrire(d0)
    for _ in range(4):
        pv.reprendre_pages(AG)
    pg = pv.page_de(AG, VI)
    check("70/30 refusé (pas le cookie) : ESSAIS_REPRISE fois, puis « à vérifier »",
          pg["essais"].get("70/30") == pv.ESSAIS_REPRISE and pg["a_verifier"] is True, pg)
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": True})
    # rattrapage et plafond : toutes les pages prêtes SANS note ab
    d0 = pv._lire()
    for k, v in d0["pages"].items():
        if k.startswith(f"{AG}:"):
            v.update(manques=[], essais={}, a_verifier=False)
            v.pop("ab", None)
    pv._ecrire(d0)
    a_rattraper = len([k for k in d0["pages"] if k.startswith(f"{AG}:")])
    AB.clear()
    bl = pv.reprendre_pages(AG)
    check("rattrapage : une page prête sans 70/30 noté le reçoit ; AB_PAR_PASSE (3) au plus par passage",
          pv.AB_PAR_PASSE == 3 and len(AB) == 3 and a_rattraper > 3 and bl["ab_en_attente"] == a_rattraper - 3,
          (len(AB), bl))
    for _ in range(5):
        pv.reprendre_pages(AG)
    check("… les suivantes aux passages d'après, sans rien compter",
          all(v.get("ab", {}).get("ok") and not v.get("essais") for k, v in pv._lire()["pages"].items()
              if k.startswith(f"{AG}:")), len(AB))
    # changement de model : bouton, pays ET 70/30 refaits
    FICHES[f"{AG}:{VI}"]["tracking"] = "https://onlyfans.com/autre/c401"
    AB.clear()
    POSES.clear()
    _vpp = pv.PAGES_PAR_PASSE
    pv.PAGES_PAR_PASSE = 100
    bl = pv.reprendre_pages(AG)
    pv.PAGES_PAR_PASSE = _vpp
    check("tracking du direct changé : les 3 pages re-pointées, pays et 70/30 refaits sur le NOUVEAU tracking",
          sorted(bl["trackings"]) == sorted([VI, f"{VI}#2", f"{VI}#3"])
          and len([a for a in AB if a["tracking"] == "https://onlyfans.com/autre/c401"]) == 3
          and all(t == "https://onlyfans.com/autre/c401" for _l, t in POSES), (bl, AB, POSES))
    FICHES[f"{AG}:{VI}"]["tracking"] = TRK
    pv.PAGES_PAR_PASSE = 100
    pv.reprendre_pages(AG)
    pv.PAGES_PAR_PASSE = _vpp
    # Twitter : jamais de 70/30, même avec le cookie
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(manques=["70/30"], essais={})
    d0["pages"][f"{TW}:{MOI}"].pop("ab", None)
    pv._ecrire(d0)
    AB.clear()
    pv.reprendre_pages(TW)
    check("Twitter : jamais de 70/30 (étape retirée, rien posé, pas de rattrapage)",
          not AB and pv.page_de(TW, MOI)["manques"] == [], AB)
    check("couper une page : disable_link, jamais l'A/B éteint",
          "allumer_ab_testing" not in (BOT / "pages_va.py").read_text(encoding="utf-8")
          and "_ab_prive" not in (BOT / "pages_va.py").read_text(encoding="utf-8"))

    # ── le bouton Telegram des gabarits ──
    print("7b-3. Le bouton Telegram reste intact")
    lid2 = pv.page_de(AG, pv.place(VI, 2))["link_id"]
    tg_avant = [b for b in PAGES[lid2]["buttons"] if "t.me/" in str(b.get("url"))]

    def f_call(nom, args):
        APPELS.append(("call", nom, args.get("link_id")))
        if nom == "get_link":
            return {"ok": True, "data": json.loads(json.dumps(PAGES.get(args["link_id"], {})))}
        if nom == "update_link":
            PAGES[args["link_id"]]["buttons"] = json.loads(json.dumps(args["buttons"]))
            return {"ok": True}
        return {"ok": False}
    gms._call_tool = f_call
    r = VRAI_POSER_TRACKING(lid2, "https://onlyfans.com/liasxcret/c999", "Instagram VA 141 @vaig page 2", EQ)
    bs = PAGES[lid2]["buttons"]
    check("le vrai _poser_tracking : seul le bouton OnlyFans prend le tracking, Telegram (adresse, texte) intact",
          r.get("ok") and tg_avant and [b for b in bs if "t.me/" in str(b.get("url"))] == tg_avant
          and [b["url"] for b in bs if "onlyfans.com" in b["url"]] == ["https://onlyfans.com/liasxcret/c999"]
          and len(bs) == 2, (r, bs))
    check("les boutons visés (texte du bouton, pays) : les OnlyFans seuls, jamais t.me",
          [b["url"] for b in pv._boutons_of(bs)] == ["https://onlyfans.com/liasxcret/c999"])
    VRAI_POSER_TRACKING(lid2, TRK, "Instagram VA 141 @vaig page 2", EQ)

    # ── les places fixes ne se modifient pas ──
    print("7b-4. Places fixes : refusées côté serveur")
    for qui_f, roles_f, perms_f in ((VI, [], "0"), (MGR, ["R_MANAGER"], str(0x8))):
        r = tk.traiter(clic_ig(f"page:o2:{VI}", qui=qui_f, roles=roles_f, perms=perms_f))
        check(f"✏️ sur une place fixe ({'le VA' if qui_f == VI else 'un manager admin'}) : refusé, aucune fenêtre",
              r["type"] == 4 and "Page fixe" in r["data"]["content"], r)
    VUS3 = []
    _vmod = pv.modifier_page
    pv.modifier_page = lambda g, u, **k: (VUS3.append(k) or {"ok": True})
    r = tk.traiter(clic_ig(f"page:f:{VI}", typ=5, comps=fen(nom="Pirate")))
    pv.modifier_page = _vmod
    check("fenêtre forgée sur la page 1 (fixe) : refusée, rien modifié",
          r["type"] == 4 and "Page fixe" in r["data"]["content"] and not VUS3, r)
    APPELS.clear()
    r = pv.modifier_page(AG, VI, nom="Pirate", n=3)
    check("pages_va.modifier_page refuse une place fixe AVANT tout appel GetMySocial",
          not r["ok"] and "page fixe" in r["erreur"] and not APPELS, (r, APPELS))
    r = tk.traiter(clic_ig(f"page:new2:{VI}"))
    check("« 📄 Créer » forgé sur TRUST INSTAGRAM : refusé (création d'office)",
          r["type"] == 4 and "toutes seules" in r["data"]["content"], r)
    r = tk.traiter(clic_ig(f"page:o4:{VI}"))
    check("✏️ d'une page 4 jamais acceptée : « Pas encore ouvert. »", "Pas encore ouvert" in r["data"]["content"], r)

    # ── demander une page ──
    print("7b-5. ➕ Demander une page")
    POSTS.clear()
    MAJ.clear()
    r = tk.traiter(clic_ig(f"pgd:new:{VI}"))
    dem = pv.demande_en_attente(AG, VI)
    post = [x for x in POSTS if x[0] == "POST"]
    check("➕ par le VA : réponse différée, demande notée « attente », message posé dans SON ticket",
          r == {"type": 5, "data": {"flags": 64}} and dem.get("etat") == "attente"
          and len(post) == 1 and post[0][1] == "/channels/T9/messages", (r, dem, POSTS))
    corps_dem = post[0][2]
    did = dem.get("id", "")
    check("le message : « 📄 Demande de page — <@VA> … », ✅ / ❌ avec l'id de la demande",
          corps_dem["content"] == f"📄 **Demande de page** — <@{VI}> demande une nouvelle page."
          and ids(corps_dem["components"]) == [f"pgd:ok:{VI}:{did}", f"pgd:non:{VI}:{did}"]
          and len(did) >= 8, corps_dem)
    check("… sans pinger de rôle (le VA seul), et pas pris pour une copie du menu par le ménage",
          corps_dem["allowed_mentions"] == {"parse": [], "users": [VI]}
          and not corps_dem["content"].startswith(("📋 **Menu**", "## 📋 Ton menu"))
          and not tk.est_copie_du_menu({"author": {"id": "B"}, "type": 0, "content": corps_dem["content"],
                                        "components": corps_dem["components"]}, {"B"}), corps_dem)
    check("… le VA est prévenu, son menu remis à jour, l'id du message noté",
          SUITES[-1].startswith("📄 Demande envoyée") and VI in MAJ
          and pv.demande_en_attente(AG, VI).get("message") == "M1", (SUITES[-1:], MAJ))
    check("registre : clé « demandes » à part, aucune fiche « uid#4 » dans « pages »",
          did in (pv._lire().get("demandes") or {}) and f"{AG}:{VI}#4" not in pv._lire()["pages"])
    r = tk.traiter(clic_ig(f"pgd:new:{VI}"))
    check("2e clic : « demande déjà en attente », rien reposté",
          r["type"] == 4 and "déjà en attente" in r["data"]["content"]
          and len([x for x in POSTS if x[0] == "POST"]) == 1, r)
    sec = tk._sections_page(AG, VI)
    att = [x for x in (sec[-1].get("components") or [])]
    check("menu : « ⏳ Demande en attente » (désactivé) à la place de ➕",
          len(att) == 1 and att[0]["custom_id"] == f"pgd:att:{VI}" and att[0].get("disabled") is True
          and f"pgd:new:{VI}" not in ids(sec), sec[-1])
    r = tk.traiter(clic_ig(f"pgd:new:{VI}", qui=AUTRE))
    check("➕ par un autre membre : refusé", r["type"] == 4 and "Seul ce VA" in r["data"]["content"], r)

    # ── accepter / refuser : un manager seulement ──
    print("7b-6. ✅ / ❌ : un manager seulement, un seul clic gagnant")
    tk.role_helper = lambda g: "R_HELPER"
    for nom_c, qui_c, roles_c in (("le VA lui-même (même avec le rôle Manager)", VI, ["R_MANAGER"]),
                                  ("un Helper", HELPER, ["R_HELPER"]), ("un membre", AUTRE, [])):
        r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did}", qui=qui_c, roles=roles_c, mid="M1"))
        check(f"✅ par {nom_c} : refusé, rien décidé",
              r["type"] == 4 and "Seul un manager" in r["data"]["content"]
              and pv.demande_en_attente(AG, VI).get("id") == did, r)
    check("(_droit_usdc, lui, laisse passer le VA et le Helper : la fonction dédiée est nécessaire)",
          tk._droit_usdc(AG, VI, clic_ig("x", qui=VI)) and tk._droit_usdc(AG, VI, clic_ig("x", qui=HELPER,
                                                                                         roles=["R_HELPER"]))
          and not tk._manager_des_pages(AG, VI, {"user": {"id": HELPER}, "roles": ["R_HELPER"]}))
    POSTS.clear()
    MAJ.clear()
    n_dup = len(APPELS)
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did}", qui=MGR, roles=["R_MANAGER"], mid="M1"))
    p4 = pv.page_de(AG, pv.place(VI, 4))
    check("✅ par un manager : le message devient « ✅ Acceptée par <@manager> — page 4 en création », sans boutons",
          r["type"] == 7 and r["data"]["components"] == []
          and r["data"]["content"].endswith(f"✅ Acceptée par <@{MGR}> — page 4 en création")
          and r["data"]["allowed_mentions"] == {"parse": []}, r)
    check("… la page 4 créée (gabarit liatemplate), son 70/30, le message mis à jour avec l'adresse, le menu aussi",
          p4.get("etat") == "prete" and [a[1] for a in dups(n_dup)] == [GAB_TEMPLATE]
          and p4.get("ab", {}).get("ok") and VI in MAJ
          and any(x[0] == "PATCH" and x[1] == "/channels/T9/messages/M1"
                  and x[2]["content"].endswith(f"page 4 : {p4.get('public_url')}") and x[2]["components"] == []
                  for x in POSTS), (p4, POSTS))
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did}", qui=MGR2, roles=["R_MANAGER"], mid="M1"))
    r2 = tk.traiter(clic_ig(f"pgd:non:{VI}:{did}", qui=MGR2, perms=str(0x8), mid="M1"))
    check("un 2e manager (✅ puis ❌) : « Déjà acceptée par <@1er> — page 4. », rien de plus",
          r["type"] == 7 and r["data"]["content"].endswith(f"Déjà acceptée par <@{MGR}> — page 4.")
          and r2["type"] == 7 and "Déjà acceptée" in r2["data"]["content"]
          and pv.places(AG, VI) == [1, 2, 3, 4], (r, r2))
    # redémarrage : tout est relu sur le disque (aucun verrou en mémoire ne tient)
    import importlib  # noqa: E402
    fichier_reg = pv.FICHIER
    importlib.reload(pv)
    pv.FICHIER = fichier_reg
    pv._FIL = lambda f: f()
    pv._cookie_ok = lambda: COOKIE["ok"]
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did}", qui=MGR2, roles=["R_MANAGER"], mid="M1"))
    check("après un redémarrage : le vieux ✅ dit « Déjà acceptée », aucune page en plus",
          r["type"] == 7 and "Déjà acceptée" in r["data"]["content"] and pv.places(AG, VI) == [1, 2, 3, 4], r)
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:deadbeef00", qui=MGR, roles=["R_MANAGER"]))
    check("un id de demande inconnu : refusé", r["type"] == 4 and "inconnue" in r["data"]["content"], r)
    # la page acceptée se modifie, comme celle de Twitter
    sec = tk._sections_page(AG, VI)
    check("menu : « Page 4 · adresse » et un bouton ✏️ Page 4, puis ➕ de nouveau",
          f"Page 4 · {p4['public_url']}" in textes(sec)[0] and ids(sec) == [f"page:o4:{VI}", f"pgd:new:{VI}"], sec)
    r = tk.traiter(clic_ig(f"page:o4:{VI}"))
    check("✏️ Page 4 par le VA : sa fenêtre (« Ma page 4 »)",
          r.get("type") == 9 and r["data"]["custom_id"] == f"page:f4:{VI}" and r["data"]["title"] == "Ma page 4", r)
    APPELS.clear()
    r = pv.modifier_page(AG, VI, nom="Quatre", bouton="Mon OF", n=4)
    maj = [a for a in APPELS if a[0] == "update"]
    bs4 = PAGES[p4["link_id"]]["buttons"]
    check("modifier_page(n=4) : seule la page 4 touchée, le bouton Telegram garde son texte et son adresse",
          r.get("ok") and maj and all(a[1] == p4["link_id"] for a in maj)
          and [b["label"] for b in bs4 if "t.me/" in b["url"]] == ["Telegram 💬"]
          and [b["label"] for b in bs4 if "onlyfans.com" in b["url"]] == ["Mon OF"], (r, bs4))
    # refus, puis place unique même si la copie rate
    tk.traiter(clic_ig(f"pgd:new:{VI}"))
    did2 = pv.demande_en_attente(AG, VI)["id"]
    MAJ.clear()
    r = tk.traiter(clic_ig(f"pgd:non:{VI}:{did2}", qui=MGR, roles=["R_MANAGER"], mid="M2"))
    check("❌ par un manager : « ❌ Refusée par <@manager>. », sans boutons, aucune page, menu remis à jour",
          r["type"] == 7 and r["data"]["content"].endswith(f"❌ Refusée par <@{MGR}>.")
          and r["data"]["components"] == [] and pv.places(AG, VI) == [1, 2, 3, 4] and VI in MAJ, r)
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did2}", qui=MGR2, roles=["R_MANAGER"], mid="M2"))
    check("le ✅ d'une demande refusée : « Déjà refusée par <@manager>. »",
          r["type"] == 7 and r["data"]["content"].endswith(f"Déjà refusée par <@{MGR}>."), r)
    REGLE["dup_refus"] = {GAB_TEMPLATE}
    tk.traiter(clic_ig(f"pgd:new:{VI}"))
    did3 = pv.demande_en_attente(AG, VI)["id"]
    POSTS.clear()
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did3}", qui=MGR, roles=["R_MANAGER"], mid="M3"))
    check("acceptée mais copie refusée : page 5 attribuée, le message dit l'échec et la reprise",
          "page 5 en création" in r["data"]["content"] and not pv.page_de(AG, pv.place(VI, 5)).get("link_id")
          and any(x[0] == "PATCH" and "page 5 pas encore créée" in x[2]["content"] for x in POSTS), (r, POSTS))
    tk.traiter(clic_ig(f"pgd:new:{VI}"))
    did4 = pv.demande_en_attente(AG, VI)["id"]
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did4}", qui=MGR2, roles=["R_MANAGER"], mid="M4"))
    check("la demande suivante prend la page 6 : jamais deux fois la même place (même sans page 5)",
          "page 6 en création" in r["data"]["content"] and pv.places(AG, VI) == [1, 2, 3, 4, 5, 6], r)
    REGLE["dup_refus"] = set()
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    check("la reprise crée les pages acceptées restées sans page, en premier",
          bl["creees"][:2] == [f"{VI}#5", f"{VI}#6"] and pv.page_de(AG, pv.place(VI, 6)).get("etat") == "prete",
          bl)
    # le message n'a pas pu être posé : la demande est annulée, le VA peut recliquer
    REGLE["post_discord"] = 500
    r = tk.traiter(clic_ig(f"pgd:new:{VI}"))
    check("message de demande refusé par Discord : demande annulée (pas « en attente » à vie), dit au VA",
          not pv.demande_en_attente(AG, VI) and SUITES[-1].startswith("✕ Demande non envoyée"), SUITES[-1:])
    REGLE["post_discord"] = 200
    _vapi = tk._api_reseau
    tk._api_reseau = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("Discord injoignable"))
    r = tk.traiter(clic_ig(f"pgd:new:{VI}"))
    tk._api_reseau = _vapi
    check("… Discord injoignable (exception) : annulée aussi, dit au VA",
          not pv.demande_en_attente(AG, VI) and SUITES[-1].startswith("✕ Demande non envoyée"), SUITES[-1:])
    r = tk.traiter(clic_ig(f"pgd:new:{VI}"))
    check("… le VA reclique : nouvelle demande notée", r["type"] == 5 and pv.demande_en_attente(AG, VI))
    did5 = pv.demande_en_attente(AG, VI)["id"]
    _vdec = pv.decider_demande
    pv.decider_demande = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("panne"))
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did5}", qui=MGR, roles=["R_MANAGER"]))
    pv.decider_demande = _vdec
    check("une panne pendant ✅ : « Une erreur est survenue » (pas « Action inconnue »)",
          r["type"] == 4 and "erreur est survenue" in r["data"]["content"], r)
    _vecr = pv._ecrire
    pv._ecrire = lambda d: False
    r = tk.traiter(clic_ig(f"pgd:ok:{VI}:{did5}", qui=MGR, roles=["R_MANAGER"]))
    pv._ecrire = _vecr
    check("disque refusé au moment de trancher : rien décidé, dit au manager",
          r["type"] == 4 and "rien n'est décidé" in r["data"]["content"]
          and pv.demande_en_attente(AG, VI).get("id") == did5, r)
    tk.traiter(clic_ig(f"pgd:non:{VI}:{did5}", qui=MGR, roles=["R_MANAGER"]))
    check("lien direct coupé : pas de ➕ (et refusé au clic)",
          (FICHES[f"{AG}:{VI}"].update(actif=False) or True)
          and f"pgd:new:{VI}" not in ids(tk._sections_page(AG, VI))
          and "désactivé" in tk.traiter(clic_ig(f"pgd:new:{VI}"))["data"]["content"])
    FICHES[f"{AG}:{VI}"]["actif"] = True

    # ── beaucoup de pages : liste déroulante, page 10, ≤ 40 composants ──
    print("7b-7. Beaucoup de pages")
    import contenu_tickets as ct  # noqa: E402
    try:
        rangs_ig = tk.boutons_va(VI, a_un_lien=True, gid=AG)
    except Exception as e:                                   # noqa: BLE001
        rangs_ig = []
        print(f"(boutons_va réel indisponible ici : {type(e).__name__}: {e})")
    for _ in range(8):                  # pages 7 à 14
        tk.traiter(clic_ig(f"pgd:new:{VI}"))
        dx = pv.demande_en_attente(AG, VI)["id"]
        tk.traiter(clic_ig(f"pgd:ok:{VI}:{dx}", qui=MGR, roles=["R_MANAGER"]))
        if len(pv.places_acceptees(AG, VI)) == 5:
            sec5 = tk._sections_page(AG, VI)
            corps5 = tk._corps_menu(AG, VI, rangs_ig)
            check("5 pages acceptées : une rangée de 5 boutons « ✏️ Page n » (le plus lourd), menu ≤ 40 composants",
                  [c for c in ids(sec5) if c.startswith("page:o")] == [f"page:o{n}:{VI}" for n in range(4, 9)]
                  and ct.compter(corps5) <= 40 and f"page:o8:{VI}" in ids(corps5), (ids(sec5), ct.compter(corps5)))
    acc = pv.places_acceptees(AG, VI)
    check("sans maximum : 11 pages acceptées (4 à 14), toutes prêtes",
          acc == list(range(4, 15)) and all(pv.page_de(AG, pv.place(VI, n)).get("etat") == "prete" for n in acc),
          acc)
    tk.traiter(clic_ig(f"pgd:new:{VI}"))
    dx = pv.demande_en_attente(AG, VI)["id"]
    tk.traiter(clic_ig(f"pgd:ok:{VI}:{dx}", qui=MGR, roles=["R_MANAGER"]))
    sec = tk._sections_page(AG, VI)
    sel = [c for x in sec for c in (x.get("components") or []) if c.get("type") == 3]
    check("3 fixes + 12 acceptées : une liste déroulante (page:sel), 12 choix, les plus récentes d'abord",
          len(sel) == 1 and sel[0]["custom_id"] == f"page:sel:{VI}"
          and [o["value"] for o in sel[0]["options"]] == [str(n) for n in range(15, 3, -1)]
          and not [c for c in ids(sec) if c.startswith("page:o")], sec)
    lourds = [{"type": 1, "components": [{"type": 2, "style": 2, "label": f"b{i}{j}", "custom_id": f"x:{i}{j}:{VI}"}
                                         for j in range(5)]} for i in range(3)]
    for nom_r, rg in (("rangées réelles du ticket", rangs_ig), ("3 rangées pleines", lourds)):
        corps = tk._corps_menu(AG, VI, rg)
        check(f"menu entier ({nom_r}, 3 fixes + 12 pages) : ≤ 40 composants, « 📄 Tes pages » dedans",
              ct.compter(corps) <= 40 and any(x.startswith("**📄 Tes pages**") for x in textes(corps)),
              ct.compter(corps))
    _vmax = tk.COMPOSANTS_MAX_V2
    base = ct.compter(tk._corps_menu_sans_page(AG, VI, lourds))
    tk.COMPOSANTS_MAX_V2 = base + 3
    corps = tk._corps_menu(AG, VI, lourds)
    tk.COMPOSANTS_MAX_V2 = base
    corps0 = tk._corps_menu(AG, VI, lourds)
    tk.COMPOSANTS_MAX_V2 = _vmax
    check("garde-fou : trop juste, le menu garde « Tes pages » sans ✏️ ; sans place, sans sections (jamais > max)",
          ct.compter(corps) <= base + 3 and any(x.startswith("**📄 Tes pages**") for x in textes(corps))
          and ct.compter(corps0) == base, (ct.compter(corps), ct.compter(corps0), base))
    r = tk.traiter(clic_ig(f"page:sel:{VI}", values=["10"]))
    check("la liste : « Page 10 » choisie → la même fenêtre (page:f10)",
          r.get("type") == 9 and r["data"]["custom_id"] == f"page:f10:{VI}", r)
    r = tk.traiter(clic_ig(f"page:o10:{VI}"))
    check("page:o10 accepté (\\d* : plus d'un chiffre)", r.get("type") == 9 and r["data"]["custom_id"] == f"page:f10:{VI}", r)
    r = tk.traiter(clic_ig(f"page:sel:{VI}", values=["2"]))
    check("la liste forgée sur une place fixe : refusée", "Page fixe" in r["data"]["content"], r)
    r = tk.traiter(clic_ig(f"page:sel:{VI}", values=["99"]))
    check("la liste sur une page jamais acceptée : « Pas encore ouvert. »", "Pas encore ouvert" in r["data"]["content"], r)
    VUS4 = []
    _vmod = pv.modifier_page
    pv.modifier_page = lambda g, u, **k: (VUS4.append(k) or {"ok": True, "faits": ["nom"]})
    p10 = pv.page_de(AG, pv.place(VI, 10))
    tk.traiter(clic_ig(f"page:f10:{VI}", typ=5, comps=fen(nom="Dix", bio=p10["champs"].get("bio", ""),
                                                         bouton=p10["champs"].get("bouton", ""))))
    pv.modifier_page = _vmod
    check("la fenêtre de la page 10 modifie la page 10", VUS4 and VUS4[-1].get("n") == 10
          and VUS4[-1].get("nom") == "Dix", VUS4)
    # la bascule suit toutes les places, acceptées comprises
    APPELS.clear()
    pv.suivre_bascule(AG, VI, False)
    coup = [a[1] for a in APPELS if a[0] == "disable"]
    check("direct coupé : ses 3 pages fixes ET ses 12 pages acceptées coupées", len(coup) == 15, len(coup))
    APPELS.clear()
    pv.suivre_bascule(AG, VI, True)
    check("rallumé : les 15 suivent", len([a for a in APPELS if a[0] == "enable"]) == 15)
    n_dup = len(APPELS)
    FICHES[f"{AG}:{VI}"]["actif"] = False
    bl = pv.creer_pages_manquantes(AG)
    FICHES[f"{AG}:{VI}"]["actif"] = True
    check("un VA coupé n'a pas de création automatique", not dups(n_dup) and bl["ignores"]["coupe"] == 2, bl)
    try:
        eph = tk.menu_ephemere(AG, VI)["data"]["components"]
        check("📋・menu du salon commun : ni « 📄 Tes pages » ni ✏️ / ➕ (le ticket seul les porte) ; "
              "le menu du ticket, juste après, les garde",
              not [c for c in ids(eph) if c.startswith(("page:", "pgd:"))]
              and not any(x.startswith("**📄") for x in textes(eph))
              and f"pgd:new:{VI}" in ids(tk._corps_menu(AG, VI, [])), ids(eph))
    except Exception as e:                                   # noqa: BLE001
        check("📋・menu du salon commun : construit", False, f"{type(e).__name__}: {e}")
    # ── 7d. Relectures du 06/11 : ce que trois relecteurs ont trouvé ───────
    print("7d. Relectures : demandes orphelines, disque, pannes passagères, adresses, A/B")
    GETS = {}                           # chemin → code d'un GET Discord

    def f_api2(m, chemin, **kw):
        POSTS.append((m, chemin, json.loads(json.dumps(kw.get("json")))))
        if m == "GET":
            return GETS.get(chemin, 200), {}
        if m == "POST" and REGLE.get("post_discord", 200) != 200:
            return REGLE["post_discord"], {"message": "refus"}
        return 200, ({"id": f"M{len(POSTS)}"} if m == "POST" else {})
    tk._api_reseau = f_api2
    gms.list_links_team = lambda eq, force_refresh=False: (APPELS.append(("list", eq)) or {
        "ok": True, "links": [{"id": k, "display_name": v.get("display_name")} for k, v in PAGES.items()]})
    _vplaf = pv.CREATIONS_PAR_PASSE
    _vpp = pv.PAGES_PAR_PASSE

    def tout_creer():
        pv.CREATIONS_PAR_PASSE = 100
        try:
            return pv.creer_pages_manquantes(AG)
        finally:
            pv.CREATIONS_PAR_PASSE = _vplaf

    def vieillir(did, s):
        d0 = pv._lire()
        d0["demandes"][did]["quand"] -= s
        pv._ecrire(d0)

    check("pannes passagères reconnues (quota, 429, réseau, 5xx, session MCP), pas les vrais refus",
          all(pv.erreur_passagere(e) for e in (
              "GetMySocial : Quota GetMySocial epuise (ecritures) — reprise vers 18:00 (40 min)",
              "HTTP 429 (rate-limit GetMySocial)", "Erreur réseau : Read timed out", "HTTP 502 : Bad Gateway",
              "Impossible d'initialiser la session MCP", "reseau: ConnectionError"))
          and not any(pv.erreur_passagere(e) for e in (
              "shortcode already taken", "gabarit introuvable", "A/B inattendu, rien touché : {}",
              "bouton non posé (aucun bouton) : page coupée")))

    # ── une demande que plus aucun bouton ne peut trancher ──
    VO = "4120"
    FICHES[f"{AG}:{VO}"] = fiche_ig(150, "vaorph")
    TICKETS[f"{AG}:{VO}"] = {"salon": "T20"}
    tout_creer()
    r0 = pv.demander_page(AG, VO, par=VO)          # notée… puis le bot redémarre avant le POST
    POSTS.clear()
    r = tk.traiter(clic_ig(f"pgd:new:{VO}", qui=VO, salon="T20"))
    check("redémarrage entre la note et le message : dans les 10 min, « déjà en attente » (le fil le pose peut-être)",
          r["type"] == 4 and "déjà en attente" in r["data"]["content"] and not POSTS, r)
    vieillir(r0["id"], pv.DEMANDE_SANS_MESSAGE_S + 5)
    MAJ.clear()
    bl = pv.creer_pages_manquantes(AG)
    check("… au-delà de DEMANDE_SANS_MESSAGE_S : la reprise l'annule, le dit, remet le menu à jour, ➕ revient",
          pv.demande(r0["id"]).get("etat") == "annulee" and VO in MAJ
          and f"pgd:new:{VO}" in ids(tk._sections_page(AG, VO))
          and any(a.startswith(VO) for a in (bl.get("demandes") or {}).get("annulees", [])),
          (pv.demande(r0["id"]), bl.get("demandes")))
    r1 = pv.demander_page(AG, VO, par=VO)
    vieillir(r1["id"], pv.DEMANDE_SANS_MESSAGE_S + 5)
    POSTS.clear()
    r = tk.traiter(clic_ig(f"pgd:new:{VO}", qui=VO, salon="T20"))
    neuve = pv.demande_en_attente(AG, VO)
    check("… ou le VA reclique ➕ avant la reprise : l'orpheline annulée, une neuve notée ET postée",
          r["type"] == 5 and pv.demande(r1["id"]).get("etat") == "annulee"
          and neuve.get("id") not in ("", r1["id"]) and neuve.get("message")
          and [x[1] for x in POSTS if x[0] == "POST"] == ["/channels/T20/messages"], (r, neuve, POSTS))
    chemin_m = f"/channels/T20/messages/{neuve['message']}"
    for code_get in (500, 403):
        GETS[chemin_m] = code_get
        pv.creer_pages_manquantes(AG)
    check("message relu, Discord en panne (500) ou sans accès (403) : rien annulé",
          pv.demande(neuve["id"]).get("etat") == "attente" and ("GET", chemin_m, None) in POSTS)
    GETS[chemin_m] = 404
    MAJ.clear()
    pv.creer_pages_manquantes(AG)
    check("message supprimé dans le ticket (GET 404) : annulée, menu remis à jour, ➕ revient",
          pv.demande(neuve["id"]).get("etat") == "annulee" and VO in MAJ
          and f"pgd:new:{VO}" in ids(tk._sections_page(AG, VO)), pv.demande(neuve["id"]))
    tk.traiter(clic_ig(f"pgd:new:{VO}", qui=VO, salon="T20"))
    did_t = pv.demande_en_attente(AG, VO)["id"]
    TICKETS[f"{AG}:{VO}"]["salon"] = "T21"
    pv.creer_pages_manquantes(AG)
    check("ticket refait (autre salon) : la demande de l'ancien annulée",
          pv.demande(did_t).get("etat") == "annulee", pv.demande(did_t))
    TICKETS[f"{AG}:{VO}"]["salon"] = "T20"

    # ── ✅ revérifie que le VA est en service (une seule règle) ──
    tk.traiter(clic_ig(f"pgd:new:{VO}", qui=VO, salon="T20"))
    did_p = pv.demande_en_attente(AG, VO)["id"]
    TICKETS[f"{AG}:{VO}"]["parti"] = {"quand": 1}
    n_dup = len(APPELS)
    r = tk.traiter(clic_ig(f"pgd:ok:{VO}:{did_p}", qui=MGR, roles=["R_MANAGER"], salon="T20"))
    check("✅ pour un VA parti entre-temps : refusé, rien décidé, aucune copie",
          r["type"] == 4 and "rien n'est décidé" in r["data"]["content"]
          and pv.demande(did_p).get("etat") == "attente" and not dups(n_dup), r)
    pv.creer_pages_manquantes(AG)
    check("… la reprise annule la demande d'un VA parti", pv.demande(did_p).get("etat") == "annulee")
    del TICKETS[f"{AG}:{VO}"]["parti"]
    tk.traiter(clic_ig(f"pgd:new:{VO}", qui=VO, salon="T20"))
    did_c = pv.demande_en_attente(AG, VO)["id"]
    FICHES[f"{AG}:{VO}"]["actif"] = False
    pv.suivre_bascule(AG, VO, False)            # comme liens_va.basculer
    r = tk.traiter(clic_ig(f"pgd:ok:{VO}:{did_c}", qui=MGR, roles=["R_MANAGER"], salon="T20"))
    r2 = tk.traiter(clic_ig(f"pgd:non:{VO}:{did_c}", qui=MGR, roles=["R_MANAGER"], salon="T20"))
    check("lien coupé : ✅ refusé, ❌ reste possible",
          r["type"] == 4 and "lien coupé" in r["data"]["content"]
          and r2["type"] == 7 and pv.demande(did_c).get("etat") == "refusee", (r, r2))
    sec = tk._sections_page(AG, VO)
    check("… et son menu : ses pages « 🚫 désactivée », pas de ➕",
          textes(sec)[0].count("🚫 désactivée") == 3 and not [c for c in ids(sec) if c.startswith("pgd:")], sec)
    FICHES[f"{AG}:{VO}"]["actif"] = True
    pv.suivre_bascule(AG, VO, True)
    VS = "4121"
    FICHES[f"{AG}:{VS}"] = dict(fiche_ig(151, "vasanstrk"), tracking="")
    TICKETS[f"{AG}:{VS}"] = {"salon": "T22"}
    sec = tk._sections_page(AG, VS)
    check("lien sans tracking : « ⚠️ lien incomplet » (et pas « ⏳ en préparation » à vie), pas de ➕",
          textes(sec)[0].count("⚠️ lien incomplet") == 3 and not [c for c in ids(sec) if c.startswith("pgd:")], sec)
    r = tk.traiter(clic_ig(f"pgd:new:{VS}", qui=VS, salon="T22"))
    check("… ➕ forgé : refusé, rien noté (la même règle que la création automatique)",
          r["type"] == 4 and "ton lien" in r["data"]["content"] and not pv.demande_en_attente(AG, VS), r)
    n_dup = len(APPELS)
    r = pv.creer_page(AG, VI_PARTI, n=1)
    check("creer_page sur TRUST INSTAGRAM pour un VA parti : refusé, aucune copie",
          not r["ok"] and "hors service" in r["erreur"] and not dups(n_dup), r)
    check("une seule règle : en_service (lien complet, en service, pas parti)",
          pv.en_service(AG, VI) == (True, "") and pv.en_service(AG, VS) == (False, "sans_lien")
          and pv.en_service(AG, VI_COUPE) == (False, "coupe") and pv.en_service(AG, VI_PARTI) == (False, "parti"))

    # ── VA parti dont le salon a été supprimé (ticket dans « tickets_disparus ») ──
    # prod 06/11 : le VA 110 (parti le 28/10, salon effacé, direct jamais coupé)
    # a reçu sa page 1 — _fiche rendait {} et en_service le jugeait en service
    VD, VD2 = "4131", "4132"
    FICHES[f"{AG}:{VD}"] = fiche_ig(161, "vadisparu")
    FICHES[f"{AG}:{VD2}"] = fiche_ig(162, "vaeffaceparerreur")
    _vetat_d = tk._etat
    tk._etat = lambda: {"tickets": TICKETS, "tickets_disparus": {
        f"{AG}:{VD}": {"salon": "T31", "parti": {"quand": 1}, "disparu": 2},
        f"{AG}:{VD2}": {"salon": "T32", "disparu": 2}}}
    try:
        check("ticket disparu avec « parti » : hors service (parti)", pv.en_service(AG, VD) == (False, "parti"),
              pv.en_service(AG, VD))
        check("ticket disparu SANS « parti » (salon effacé par erreur) : reste en service",
              pv.en_service(AG, VD2) == (True, ""), pv.en_service(AG, VD2))
        check("… même règle quand l'appelant passe le ticket vide (lot de création : tickets.get(...) or {})",
              pv.en_service(AG, VD, fiche=FICHES[f"{AG}:{VD}"], ticket={}) == (False, "parti"))
        n_dup = len(APPELS)
        r = pv.creer_page(AG, VD, n=1)
        check("creer_page pour un VA parti au salon disparu : refusé, aucune copie",
              not r["ok"] and "hors service" in r["erreur"] and not dups(n_dup), r)
    finally:
        tk._etat = _vetat_d
        FICHES.pop(f"{AG}:{VD}", None)
        FICHES.pop(f"{AG}:{VD2}", None)

    # ── tickets illisibles ──
    _vetat = tk._etat
    tk._etat = lambda: {}
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    tk._etat = _vetat
    check("tickets illisibles (tk._etat rend {}) : aucune création, dit (personne n'était plus « parti »)",
          bl.get("erreur") == "tickets illisibles" and not dups(n_dup), bl)

    # ── un registre qui refuse d'écrire ──
    VD = "4123"
    FICHES[f"{AG}:{VD}"] = fiche_ig(153, "vadisque")
    _vecr = pv._ecrire
    pv._ecrire = lambda d: False
    n_dup = len(APPELS)
    for _ in range(4):
        bl = pv.creer_pages_manquantes(AG)
    pv._ecrire = _vecr
    check("registre qui refuse d'écrire, 4 passages : aucune copie GetMySocial (contrôle avant le lot), dit",
          not dups(n_dup) and bl.get("erreur") == "registre non écrit" and bl["restent"] >= 3, bl)
    ECRITS = {"n": 0}

    def ecrire_puis_refuser(d):
        ECRITS["n"] += 1
        return _vecr(d) if ECRITS["n"] == 1 else False
    pv._ecrire = ecrire_puis_refuser
    n_ap = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    pv._ecrire = _vecr
    copies = [a for a in APPELS[n_ap:] if a[0] == "duplicate"]
    coupees = [a[1] for a in APPELS[n_ap:] if a[0] == "disable"]
    check("… la note de la copie refusée (disque plein entre-temps) : copie coupée aussitôt, le lot s'arrête",
          len(copies) == 1 and coupees == ["lnk_page_" + copies[0][2]] and bl.get("erreur") == "registre non écrit"
          and not pv.page_de(AG, VD).get("link_id"), (copies, coupees, bl))
    n_ap = len(APPELS)
    tout_creer()
    check("… le disque revenu : ses 3 pages créées, l'ancienne copie (coupée, inconnue du registre) recoupée, pas rallumée",
          all(pv.page_de(AG, pv.place(VD, n)).get("etat") == "prete" for n in (1, 2, 3))
          and ("disable", "lnk_page_" + copies[0][2]) in APPELS[n_ap:]
          and ("enable", "lnk_page_" + copies[0][2]) not in APPELS[n_ap:], APPELS[n_ap:][:8])

    # ── une panne passagère de GetMySocial ne compte pas ──
    VQ1, VQ2 = "4124", "4125"
    FICHES[f"{AG}:{VQ1}"] = fiche_ig(154, "vaquota")
    FICHES[f"{AG}:{VQ2}"] = fiche_ig(155, "vaquotb")
    REGLE["dup_refus"] = {GAB_BRUNE, GAB_BLONDE, GAB_TEMPLATE}
    REGLE["dup_erreur"] = "Quota GetMySocial epuise (ecritures) — reprise vers 18:00 (40 min)"
    n_dup = len(APPELS)
    for _ in range(6):
        bl = pv.creer_pages_manquantes(AG)
    nb = len([a for a in APPELS[n_dup:] if a[0] == "duplicate"])
    cr = pv._lire().get("creations") or {}
    check("quota épuisé 6 passages : une copie tentée par passage (le lot s'arrête), aucun essai compté, rien « à vérifier »",
          nb == 6 and not [k for k in cr if f":{VQ1}" in k or f":{VQ2}" in k]
          and bl["passageres"] and not [x for x in bl["a_verifier"] if x.startswith((VQ1, VQ2))], (nb, cr, bl))
    check("… menu : « ⏳ en préparation » (pas « ⚠️ à reprendre »)",
          textes(tk._sections_page(AG, VQ1))[0].count("⏳ en préparation") == 3)
    REGLE["dup_refus"], REGLE["dup_erreur"] = set(), None
    tout_creer()
    check("… le quota revenu : créées", all(pv.page_de(AG, pv.place(u, n)).get("etat") == "prete"
                                            for u in (VQ1, VQ2) for n in (1, 2, 3)))
    VW = "4126"
    FICHES[f"{AG}:{VW}"] = fiche_ig(156, "vapause")
    gms.pause_restante = lambda genre="lecture": 1800 if genre == "ecriture" else 0
    n_dup = len(APPELS)
    bl = pv.creer_pages_manquantes(AG)
    gms.pause_restante = lambda genre="lecture": 0
    check("écritures GetMySocial en pause : aucune copie tentée, rien compté, dit",
          not dups(n_dup) and bl["passageres"] and bl["restent"] == 3
          and not [k for k in (pv._lire().get("creations") or {}) if f":{VW}" in k], bl)
    d0 = pv._lire()
    d0.setdefault("creations", {})[f"{AG}:{VW}"] = {"essais": 3, "a_verifier": True, "erreur": "refus",
                                                    "quand": int(time.time()) - pv.CREATION_REESSAI_S - 60}
    d0["creations"][f"{AG}:{VW}#2"] = {"essais": 3, "a_verifier": True, "erreur": "refus", "quand": int(time.time())}
    pv._ecrire(d0)
    t_vw = textes(tk._sections_page(AG, VW))[0]
    check("« à vérifier » depuis plus de CREATION_REESSAI_S : retentée (plus figée à vie) ; récente : attend encore",
          not pv.creation_a_verifier(AG, VW, 1) and pv.creation_a_verifier(AG, VW, 2)
          and "Page 1 · ⏳ en préparation" in t_vw and "Page 2 · ⚠️ à reprendre" in t_vw, t_vw)
    bl = tout_creer()
    check("… le passage suivant la recrée", pv.page_de(AG, VW).get("etat") == "prete"
          and not pv.page_de(AG, pv.place(VW, 2)).get("link_id"), bl)
    d0 = pv._lire()
    d0["creations"].pop(f"{AG}:{VW}#2", None)
    pv._ecrire(d0)
    tout_creer()
    # la reprise : panne passagère sur TRUST INSTAGRAM, règle d'avant sur Twitter
    _vpays = lv.poser_pays
    lv.poser_pays = lambda lid, eq, *a: {"ok": False, "erreur": "Erreur réseau : Read timed out"}
    d0 = pv._lire()
    d0["pages"][f"{AG}:{VI5}"].update(manques=["pays"], essais={}, a_verifier=False)
    d0["pages"][f"{TW}:{MOI}"].update(manques=["pays"], essais={}, a_verifier=False)
    pv._ecrire(d0)
    pv.PAGES_PAR_PASSE = 100
    for _ in range(4):
        bl = pv.reprendre_pages(AG)
        pv.reprendre_pages(TW)
    pv.PAGES_PAR_PASSE = _vpp
    lv.poser_pays = _vpays
    p5 = pv.page_de(AG, VI5)
    check("reprise sur TRUST INSTAGRAM : pays refusés par une panne passagère, refaits sans compter d'essai",
          p5["manques"] == ["pays"] and not (p5.get("essais") or {}).get("pays") and not p5.get("a_verifier")
          and any(x.startswith(VI5) for x in bl["passageres"]), (p5, bl.get("passageres")))
    pm = pv.page_de(TW, MOI)
    check("… Twitter garde sa règle : chaque échec compte, « à vérifier » au bout de ESSAIS_REPRISE",
          (pm.get("essais") or {}).get("pays") == pv.ESSAIS_REPRISE and pm.get("a_verifier") is True, pm)
    d0 = pv._lire()
    d0["pages"][f"{TW}:{MOI}"].update(manques=[], essais={}, a_verifier=False, pays=True)
    pv._ecrire(d0)
    pv.PAGES_PAR_PASSE = 100
    pv.reprendre_pages(AG)
    pv.PAGES_PAR_PASSE = _vpp

    # ── adresses : les paires d'abord sur TRUST INSTAGRAM ──
    seuls = {lv._deux_y(m) for m in lv.MOTS_THREADS}
    ig = [a for a in APPELS if a[0] == "duplicate" and str(a[3]).startswith("Instagram VA")]
    check("TRUST INSTAGRAM : chaque copie part des paires de mots (les 25 mots seuls sont pris chez GetMySocial)",
          ig and not [a for a in ig if a[2] in seuls], [a[2] for a in ig if a[2] in seuls][:5])
    FICHES[f"{TW}:4129"] = dict(FICHE, numero=170, pseudo="vatw")
    n_ap = len(APPELS)
    r = pv.creer_page(TW, "4129")
    tw = [a for a in APPELS[n_ap:] if a[0] == "duplicate"]
    check("… Twitter garde son ordre (un mot seul d'abord), sans 70/30 ni relecture de l'équipe",
          r["ok"] and tw and tw[0][2] in seuls and not [a for a in APPELS[n_ap:] if a[0] == "list"], (r, tw))

    # ── réponse perdue : la 1re copie existe, le renvoi dit « adresse prise » ──
    VP = "4131"
    FICHES[f"{AG}:{VP}"] = fiche_ig(161, "vaperdue")
    nom_p = "Instagram VA 161 @vaperdue page"
    sc0 = lv.mots_sans_prenom(nom_p, len(lv.MOTS_THREADS))
    REGLE["perdue"] = {sc0}
    n_ap = len(APPELS)
    r = pv.creer_page(AG, VP, n=1)
    REGLE["perdue"] = set()
    pgp = pv.page_de(AG, VP)
    coup = [a[1] for a in APPELS[n_ap:] if a[0] == "disable"]
    check("réponse perdue de GetMySocial : la copie orpheline (même nom, inconnue du registre) coupée, jamais supprimée ; "
          "la bonne gardée",
          r["ok"] and pgp.get("link_id") and pgp["link_id"] != "lnk_page_" + sc0 and coup == ["lnk_page_" + sc0]
          and ("delete", "lnk_page_" + sc0) not in APPELS[n_ap:], (r, coup))

    # ── une copie qui hérite d'un A/B inconnu de son gabarit ──
    VX = "4130"
    FICHES[f"{AG}:{VX}"] = fiche_ig(160, "vaab")
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {
        "ok": False, "inattendu": True, "erreur": "A/B inattendu, rien touché : {'variants': ['Variant 1']}"})
    n_ap = len(APPELS)
    r = pv.creer_page(AG, VX, par="auto", n=1)
    pgx = pv.page_de(AG, VX)
    check("A/B inattendu hérité du gabarit : la copie coupée (disable_link), jamais donnée, « ⚠️ à reprendre »",
          not r["ok"] and pgx.get("etat") == "ratee" and pgx.get("actif") is False
          and ("disable", pgx.get("link_id")) in APPELS[n_ap:] and pv.etat_place(AG, VX, 1) == ("a_reprendre", "")
          and not [a for a in APPELS[n_ap:] if a[0] == "ranger"], (r, pgx))
    lv._poser_base_seule = lambda g, u, lien=None: (AB.append(lien) or {"ok": True})
    n_ap = len(APPELS)
    tout_creer()
    pgx2 = pv.page_de(AG, VX)
    check("… A/B normal ensuite : la MÊME copie reprise et rallumée, aucune nouvelle copie de la page 1",
          pgx2.get("etat") == "prete" and pgx2.get("link_id") == pgx.get("link_id")
          and ("enable", pgx["link_id"]) in APPELS[n_ap:]
          and not [a for a in APPELS[n_ap:] if a[0] == "duplicate" and a[3] == "Instagram VA 160 @vaab page"], pgx2)

    # ── la branche 30 % : la safe page posée sur sa copie temporaire ──
    VUES = []
    LECTURES = {"n": 0}

    def f_lire_ab(lid, eq):
        LECTURES["n"] += 1
        if LECTURES["n"] == 1:
            return {"ok": True, "config": {}}
        return {"ok": True, "config": {"enabled": True, "controlWeight": 70,
                                       "variants": [{"name": "Base Lia", "weight": 30, "variantId": "v1"}]}}
    sav_ab = (gms.duplicate_link, gms.update_link, gms.delete_link, lv.poser_pays, lv.espace)
    gms.duplicate_link = lambda src, sc, nom="", url="", team_id=None: (
        VUES.append(("dup", src)) or {"ok": True, "link": {"id": "lnk_abtmp", "url": url}})
    gms.update_link = lambda lid, champs, team_id=None: (VUES.append(("update", lid, champs)) or {"ok": True})
    gms.delete_link = lambda lid: (VUES.append(("delete", lid)) or {"ok": True})
    gms.lire_ab_testing = f_lire_ab
    gms._ab_prive = lambda m, lid, eq, corps: (VUES.append(("ab", lid)) or {"ok": True})
    lv._page_du_lien = lambda lid, eq: "https://onlyfans.com/liasxcret"
    lv.nom_de_page = lambda page: "Lia"
    lv.poser_pays = lambda lid, eq, *a: (VUES.append(("pays", lid)) or {"ok": True})
    lv.espace = lambda g="": {"equipe": EQ, "source_variante": "lnk_source"}
    try:
        r = VRAI_POSER_BASE_SEULE(AG, VI, lien=pv._lien_ab("lnk_pg", TRK, "pgx"))
        ordre = [v[0] for v in VUES]
        sp = [v for v in VUES if v[0] == "update" and v[1] == "lnk_abtmp"]
        check("70/30 d'une page (vrai _poser_base_seule) : pays PUIS safe page sur la copie temporaire, AVANT "
              "l'enregistrement de l'A/B (la variante est figée), copie supprimée ensuite",
              r.get("ok") and sp and sp[0][2].get("bot_protection") == {"mode": "safe_page"}
              and ordre.index("pays") < ordre.index("update") < ordre.index("ab") < ordre.index("delete"), (r, VUES))
        VUES.clear()
        LECTURES["n"] = 0
        r = VRAI_POSER_BASE_SEULE(AG, VI, lien={"link_id": "lnk_direct_x", "tracking": TRK, "shortcode": "d"})
        check("… un lien direct (sans le drapeau) : rien de changé, pas de safe page posée",
              r.get("ok") and not [v for v in VUES if v[0] == "update"], VUES)
        VUES.clear()
        LECTURES["n"] = 0
        gms.update_link = lambda lid, champs, team_id=None: (VUES.append(("update", lid, champs)) or {
            "ok": False, "error": "refus"})
        r = VRAI_POSER_BASE_SEULE(AG, VI, lien=pv._lien_ab("lnk_pg", TRK, "pgx"))
        check("… safe page refusée sur la copie : pas d'A/B enregistré (rien de non protégé), copie supprimée",
              not r.get("ok") and "safe page" in r.get("erreur", "") and ("ab", "lnk_pg") not in VUES
              and ("delete", "lnk_abtmp") in VUES, (r, VUES))
    finally:
        (gms.duplicate_link, gms.update_link, gms.delete_link, lv.poser_pays, lv.espace) = sav_ab

    # ── reprise : rien à faire, rien d'écrit ──
    pv.PAGES_PAR_PASSE = 100
    pv.reprendre_pages(AG)
    pv.reprendre_pages(AG)
    pv.PAGES_PAR_PASSE = _vpp
    ECR, LUS = [], []
    _vecr, _vlien, _vlancer = pv._ecrire, lv.lien_de, pv.lancer_creations
    pv._ecrire = lambda d: (ECR.append(1) or _vecr(d))
    lv.lien_de = lambda g, u: (LUS.append(u) or _vlien(g, u))
    pv.lancer_creations = lambda g: "rien"
    try:
        bl = pv.reprendre_pages(AG)
    finally:
        pv._ecrire, lv.lien_de, pv.lancer_creations = _vecr, _vlien, _vlancer
    check("reprise sans rien à faire : aucune écriture du registre (réécrit pour chaque page à chaque passage)",
          not ECR and not bl["rates"], (len(ECR), bl))
    check("… la fiche du direct lue une fois par VA et par passage (pas une fois par page)",
          len(LUS) == len(set(LUS)) and VI in LUS, LUS)

    # ── changement de model : les boutons re-pointés ont leur plafond ──
    FICHES[f"{AG}:{VI}"]["tracking"] = "https://onlyfans.com/autre/c402"
    POSES.clear()
    bl = pv.reprendre_pages(AG)
    n_vi = len(pv.liens_des_pages(AG, VI))
    check(f"changement de model, {n_vi} pages d'un VA : toutes re-pointées au 1er passage "
          "(REPOINTES_PAR_PASSE à part de PAGES_PAR_PASSE)",
          n_vi >= 15 and len([1 for _l, t in POSES if t.endswith("c402")]) == n_vi
          and len([u for u in bl["trackings"] if u.split("#")[0] == VI]) == n_vi, (len(POSES), bl["trackings"]))
    FICHES[f"{AG}:{VI}"]["tracking"] = TRK
    pv.PAGES_PAR_PASSE = 100
    for _ in range(3):
        pv.reprendre_pages(AG)
    pv.PAGES_PAR_PASSE = _vpp
    FICHES[f"{TW}:{MOI}"]["tracking"] = "https://onlyfans.com/liasxcret/c301"
    FICHES[f"{TW}:4129"]["tracking"] = "https://onlyfans.com/liasxcret/c302"
    pv.PAGES_PAR_PASSE = 1
    bl = pv.reprendre_pages(TW)
    pv.PAGES_PAR_PASSE = _vpp
    check("… Twitter garde son plafond commun (PAGES_PAR_PASSE)", len(bl["trackings"]) == 1, bl["trackings"])
    FICHES[f"{TW}:{MOI}"]["tracking"] = FICHE["tracking"]
    FICHES[f"{TW}:4129"]["tracking"] = FICHE["tracking"]
    pv.PAGES_PAR_PASSE = 100
    pv.reprendre_pages(TW)
    pv.PAGES_PAR_PASSE = _vpp

    # ── le message de la demande, après la copie ──
    check("✅ suivi d'une copie réussie : le message porte l'adresse, noté (la reprise ne le réécrira pas)",
          pv.demande(did).get("message_maj"))
    VM = "4128"
    FICHES[f"{AG}:{VM}"] = fiche_ig(158, "vamsg")
    TICKETS[f"{AG}:{VM}"] = {"salon": "T28"}
    tout_creer()
    tk.traiter(clic_ig(f"pgd:new:{VM}", qui=VM, salon="T28"))
    dm = pv.demande_en_attente(AG, VM)
    REGLE["dup_refus"] = {GAB_TEMPLATE}
    tk.traiter(clic_ig(f"pgd:ok:{VM}:{dm['id']}", qui=MGR, roles=["R_MANAGER"], mid=dm["message"], salon="T28"))
    REGLE["dup_refus"] = set()
    POSTS.clear()
    tout_creer()
    p4m = pv.page_de(AG, pv.place(VM, 4))
    patch = [x for x in POSTS if x[0] == "PATCH" and x[1] == f"/channels/T28/messages/{dm['message']}"]
    check("copie ratée au ✅ puis faite par la reprise : le message de la demande prend l'adresse (fini « en création »)",
          p4m.get("etat") == "prete" and len(patch) == 1
          and patch[0][2]["content"].endswith(f"✅ Acceptée par <@{MGR}> — page 4 : {p4m['public_url']}")
          and patch[0][2]["components"] == [] and pv.demande(dm["id"]).get("message_maj"), (p4m, POSTS))
    POSTS.clear()
    pv._apres_creation(AG, VM, 4, p4m["public_url"])
    check("… une seule fois", not [x for x in POSTS if x[0] == "PATCH" and dm["message"] in x[1]], POSTS)
    tk.ATTENTE_AVANT_PATCH_S = 0.3
    tk.traiter(clic_ig(f"pgd:new:{VM}", qui=VM, salon="T28"))
    dm2 = pv.demande_en_attente(AG, VM)
    REGLE["dup_refus"] = {GAB_TEMPLATE}
    t_clic = time.time()
    tk.traiter(clic_ig(f"pgd:ok:{VM}:{dm2['id']}", qui=MGR, roles=["R_MANAGER"], mid=dm2["message"], salon="T28"))
    duree = time.time() - t_clic
    REGLE["dup_refus"] = set()
    tk.ATTENTE_AVANT_PATCH_S = 0
    check("échec immédiat après ✅ : le PATCH attend ATTENTE_AVANT_PATCH_S (la réponse type 7 passe avant lui)",
          duree >= 0.3, duree)
    tout_creer()

    # ── la liste ✏️ : toutes les pages acceptées, 25 au plus ──
    VL = "4127"
    FICHES[f"{AG}:{VL}"] = fiche_ig(157, "valiste")
    TICKETS[f"{AG}:{VL}"] = {"salon": "T27"}

    def forger_pages(jusqua):
        d0 = pv._lire()
        for n in range(1, jusqua + 1):
            d0["pages"][f"{AG}:{pv.place(VL, n)}"] = {
                "link_id": f"lnk_l{n}", "public_url": f"https://getmysocial.com/l{n}", "etat": "prete",
                "actif": True, "tracking": TRK, "ab": {"ok": True}, "manques": [], "essais": {}, "pays": True,
                "groupe": "Manager JOHN"}
            if n > pv.fixes(AG):
                d0["demandes"][f"ab{n:08x}"] = {"gid": AG, "uid": VL, "etat": "acceptee", "place": n}
        pv._ecrire(d0)
    forger_pages(25)
    sec = tk._sections_page(AG, VL)
    sel = [c for x in sec for c in (x.get("components") or []) if c.get("type") == 3]
    vals = [o["value"] for o in sel[0]["options"]] if sel else []
    check("22 pages acceptées (4 à 25) : la liste ✏️ les propose TOUTES, 4 et 5 comprises (pas seulement les "
          "20 lignes montrées)",
          vals == [str(n) for n in range(25, 3, -1)] and "-# + 2 page(s) plus ancienne(s)" in textes(sec)[0], vals)
    forger_pages(31)
    sec = tk._sections_page(AG, VL)
    sel = [c for x in sec for c in (x.get("components") or []) if c.get("type") == 3]
    vals = [o["value"] for o in sel[0]["options"]] if sel else []
    check("28 pages acceptées : 25 choix, les plus récentes ; menu entier ≤ 40 composants",
          vals == [str(n) for n in range(31, 6, -1)] and ct.compter(tk._corps_menu(AG, VL, rangs_ig)) <= 40, vals)
    d0 = pv._lire()
    for k in [k for k in d0["pages"] if k.startswith(f"{AG}:{VL}")]:
        d0["pages"].pop(k)
    for k in [k for k, x in d0["demandes"].items() if x.get("uid") == VL]:
        d0["demandes"].pop(k)
    pv._ecrire(d0)
    FICHES.pop(f"{AG}:{VL}")

    # ── la liste ✏️ redessinée après la fenêtre ──
    TICKETS[f"{AG}:{VI}"].update(menu="MV2", menu_v2=1, menu_rangs=[{"type": 1, "components": [
        {"type": 2, "style": 2, "label": "💳", "custom_id": f"usdc:set:{VI}"}]}])
    NOTES_MENU = []
    tk._noter_menu_v2 = lambda cle, mid, rangs, corps, pose=False: NOTES_MENU.append((cle, mid))
    POSTS.clear()
    p_sel = clic_ig(f"page:sel:{VI}", values=["10"], mid="MV2")
    p_sel["message"]["flags"] = 1 << 15
    r = tk.traiter(p_sel)
    patch = [x for x in POSTS if x[0] == "PATCH" and x[1] == "/channels/T9/messages/MV2"]
    check("liste ✏️ du menu du ticket : la fenêtre, PUIS le menu renvoyé tel quel (Discord y garderait le choix, "
          "et le rechoisir n'enverrait rien)",
          r.get("type") == 9 and r["data"]["custom_id"] == f"page:f10:{VI}" and len(patch) == 1
          and f"page:sel:{VI}" in ids(patch[0][2]["components"]) and NOTES_MENU == [(f"{AG}:{VI}", "MV2")],
          (r.get("type"), POSTS))
    POSTS.clear()
    p_sel = clic_ig(f"page:sel:{VI}", values=["10"], mid="UN_AUTRE")
    p_sel["message"]["flags"] = 1 << 15
    tk.traiter(p_sel)
    check("… jamais un autre message que le menu noté du VA", not [x for x in POSTS if x[0] == "PATCH"], POSTS)
    for k in ("menu", "menu_v2", "menu_rangs"):
        TICKETS[f"{AG}:{VI}"].pop(k, None)
    for u in (VO, VS, VD, VQ1, VQ2, VW, VP, VX, VM):
        FICHES.pop(f"{AG}:{u}", None)
    FICHES.pop(f"{TW}:4129", None)
    # ── 7c. la pastille du salon compte la page ─────────────────────────
    print("7c. Pastille")
    pl = pv.page_de(TW, MOI)["link_id"]
    check("pastille : des visites sur la page seule = 🟢 (comme sur le direct)",
          tk.rond_du_va(TW, MOI, {pl: 5}) == tk.ROND_CLICS and tk.rond_du_va(TW, MOI, {}) == tk.ROND_RIEN
          and tk.rond_du_va(TW, MOI, {"lnk_direct": 2}) == tk.ROND_CLICS)
    check("les pages d'un VA, toutes places, et pas celles d'un autre",
          pv.liens_des_pages(TW, MOI) == [pl] and pv.page_de(TW, VA)["link_id"] not in pv.liens_des_pages(TW, MOI))

    # ── 8. hors classement ───────────────────────────────────────────────
    print("8. Hors classement")
    _vrais_partis = pod._partis_sans_pilotes
    pod._partis_sans_pilotes = lambda g: {}
    try:
        check("Twitter : le pilote (VA 160) sorti des classements comme un parti, depuis le début du pilote",
              pod._partis(TW) == {"VA 160": pod.DEBUT_PILOTE}, pod._partis(TW))
        check("ailleurs : rien", pod._partis("1488331963575177247") == {})
    finally:
        pod._partis_sans_pilotes = _vrais_partis
finally:
    (gms.duplicate_link, gms.update_link, gms.get_link, gms.disable_link, gms.enable_link,
     gms.delete_link, gms.get_api_key, requests.post, lv.lien_de, lv.espace, lv._poser_tracking,
     lv.poser_pays, lv._poser_base_seule, lv.ranger, lv.lia_seule, tk._etat, tk.role_manager,
     tk.role_helper, tk._maj_menu_v2, tk._EN_FOND, tk._suite, tk._api_reseau, lv._etat,
     gms._call_tool, pv._cookie_ok, pv._FIL) = SAV
    for (m, n), v in SAV2.items():
        setattr(m, n, v)
    tk.ETAT_FICHIER, tk._api_reseau = SAV_TK

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
