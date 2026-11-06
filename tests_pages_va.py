# -*- coding: utf-8 -*-
"""tests_pages_va.py — la page GetMySocial modifiable des VA de TRUST TWITTER (06/11/2026).

Propriétaire : « je veux avoir 2 liens pour les VA, un direct et un landing page
qu'ils peuvent modifier » ; photo (il dépose une image), nom et bio, texte du
bouton, image de fond ; même tracking, pays, safe page, PAS de 70/30 (« ça doit pas être 70 30 ») ; (
page) ; essai sur lui seul, hors classement.

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


def f_duplicate(src, sc, nom="", url="", team_id=None):
    APPELS.append(("duplicate", src, sc, nom, url, team_id))
    lid = "lnk_page_" + sc
    PAGES[lid] = page_neuve(lid)
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
       tk.role_helper, tk._maj_menu_v2, tk._EN_FOND, tk._suite)
FICHES = {f"{TW}:{MOI}": dict(FICHE)}
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
    check("pilote : le propriétaire seul sur Twitter", pv.ouverte(TW, MOI) and not pv.ouverte(TW, VA)
          and not pv.ouverte("1488331963575177247", MOI))

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
    check("lien direct coupé : la page naît coupée aussi",
          r["ok"] and pv.page_de(TW, VA).get("actif") is False and any(a[0] == "disable" for a in APPELS), r)

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
        lv._basculer_sans_page = lambda g, u, a: {"ok": True}
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
    check("un VA hors pilote : menu inchangé", tk._corps_menu(TW, VA, []) == tk._corps_menu_sans_page(TW, VA, []))
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
    d["pages"][f"{TW}:{MOI}"] = dict(sauve, etat="ratee")
    pv._ecrire(d)
    check("page ratée : « À reprendre » avec 🔁 Réessayer (manager)",
          "**📄 Ta page**\n-# À reprendre" in textes(tk._corps_menu(TW, MOI, []))
          and f"page:new:{MOI}" in ids(tk._corps_menu(TW, MOI, [])))
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
    check("✏️ Modifier : la fenêtre s'ouvre", r.get("type") == 9 and r["data"]["custom_id"] == f"page:f:{MOI}", r)
    r = tk.traiter(clic(f"page:o:{MOI}", qui=AUTRE))
    check("un autre membre (pas manager) : refusé", r["type"] == 4 and r["data"]["flags"] == 64, r)
    r = tk.traiter(clic(f"page:o:{VA}", qui=VA))
    check("hors pilote : refusé", r["type"] == 4 and "Pas encore" in r["data"]["content"], r)

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
                                                                   "photo": None, "fond": None}
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
    r = tk.traiter(clic(f"page:new:{MOI}", qui=MOI))
    check("📄 Créer par un non-manager : refusé", r["type"] == 4 and "manager" in r["data"]["content"], r)
    check("un clic d'un autre module passe son chemin", tk._page(clic("usdc:set:1")) is None)

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
     tk.role_helper, tk._maj_menu_v2, tk._EN_FOND, tk._suite) = SAV

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
