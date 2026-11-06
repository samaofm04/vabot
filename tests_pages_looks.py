# -*- coding: utf-8 -*-
"""tests_pages_looks.py — le choix du look des pages TRUST TWITTER (06/11/2026).

Propriétaire : « quand ils cliquent sur modifier [...] ils peuvent choisir leur
template [...] brune, blonde [...] et après ils peuvent modifier par eux-mêmes
[...] toujours une seule page en safe page sur Twitter » ; « Template » renommé
« Général ». Sans réseau ni data/ : gms remplacé, registre temporaire.
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

import gms                     # noqa: E402
import liens_va as lv          # noqa: E402
import pages_va as pv          # noqa: E402
import tickets_discord as tk   # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


TW, AG = pv.TWITTER_ID, pv.AGENCY_IG_ID
VA, AUTRE = "4001", "4002"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pages_looks_"))
TRACK = "https://onlyfans.com/liasxcret/c76"
PAGE = {"id": "lnk_page", "type": "landing", "display_name": "Twitter VA 96 @x page",
        "profile_picture": "https://images.getmysocial.com/u/links/x/profile.jpg",
        "profile_picture_slides": [{"url": "https://images.getmysocial.com/u/vieille.jpg"}],
        "background_image": "https://images.getmysocial.com/u/links/x/background.jpg",
        "buttons": [{"label": "MY FREE 0F", "url": TRACK, "geofilters": [{"country_code": "ES"}] * 233},
                    {"label": "MY TELEGRAM", "url": "https://t.me/m/x"}]}
LIENS, ECRITS, REGLE = {}, [], {"casse_of": False, "relu_autre": False}


def f_get(lid, team_id=None):
    l = LIENS.get(lid)
    return {"ok": True, "link": json.loads(json.dumps(l))} if l else {"ok": False, "error": "404"}


def f_update(lid, champs, team_id=None):
    ECRITS.append((lid, json.loads(json.dumps(champs))))
    l = LIENS[lid]
    l.update(json.loads(json.dumps(champs)))
    if REGLE["relu_autre"]:
        l["background_image"] = "https://images.getmysocial.com/u/autre.jpg"
    if REGLE["casse_of"]:
        l["buttons"][0]["url"] = "https://onlyfans.com/liasxcret/c1"
    return {"ok": True, "link": l}


SAV = (gms.get_link, gms.update_link, pv.FICHIER, lv.lien_de, tk._suite, tk._EN_FOND, tk._fiche)
SUITES = []
try:
    gms.get_link, gms.update_link = f_get, f_update
    pv.FICHIER = TMP / "pages_va.json"
    lv.lien_de = lambda g, u: ({"link_id": "lnk_direct", "public_url": "https://getmysocial.com/d", "tracking": TRACK,
                                "numero": 96, "pseudo": "x", "actif": True} if str(u).split("#")[0] == VA else {})
    tk._suite = lambda jeton, texte, p=None: SUITES.append(texte)
    tk._EN_FOND = lambda f: f()
    tk._fiche = lambda g, u: {}

    print("1. Les looks")
    lk = pv.looks(TW)
    check("Twitter : 3 looks, « Brune », « Blonde », « Général » (plus « Template »)",
          [x[0] for x in lk] == ["brune", "blonde", "general"] and [x[2] for x in lk] == ["Brune", "Blonde", "Général"], lk)
    check("chaque look : une photo et un fond chez GetMySocial",
          all(x[3].startswith("https://images.getmysocial.com/") and x[4].startswith("https://images.getmysocial.com/")
              for x in lk))
    check("TRUST INSTAGRAM : les mêmes looks depuis le 06/11 au soir (page 1 = son lien, tests_pages_ig_lien)",
          pv.looks(AG) == lk)

    print("2. appliquer_look")
    LIENS["lnk_page"] = json.loads(json.dumps(PAGE))
    pv._noter(TW, VA, link_id="lnk_page", etat="prete", actif=True, shortcode="cherrydollyy")
    r = pv.appliquer_look(TW, VA, "blonde")
    l = LIENS["lnk_page"]
    _c, _e, _lib, ph, fd = lk[1]
    envoye = ECRITS[-1][1] if ECRITS else {}
    check("look Blonde : photo et fond posés, diapo vidée (une vieille diapo restait affichée)",
          r["ok"] and l["profile_picture"] == ph and l["background_image"] == fd and l["profile_picture_slides"] == [], r)
    check("… seuls nom, photo, diapo et fond envoyés : boutons, tracking, pays, Telegram jamais réécrits",
          set(envoye) == {"display_name", "profile_picture", "profile_picture_slides", "background_image"}
          and l["buttons"][0]["url"] == TRACK and len(l["buttons"][0]["geofilters"]) == 233
          and l["buttons"][1]["url"] == "https://t.me/m/x", envoye)
    check("… le look noté dans le registre (vert dans le choix)", pv.page_de(TW, VA).get("look") == "blonde")
    check("look inconnu : refusé, rien envoyé", not pv.appliquer_look(TW, VA, "rousse")["ok"])
    n = len(ECRITS)
    check("sans page : refusé, rien envoyé", not pv.appliquer_look(TW, AUTRE, "brune")["ok"] and len(ECRITS) == n)
    REGLE["relu_autre"] = True
    r = pv.appliquer_look(TW, VA, "brune")
    REGLE["relu_autre"] = False
    check("relu autrement : dit (pas de faux « ✅ »), look pas noté",
          not r["ok"] and "relue" in r["erreur"] and pv.page_de(TW, VA).get("look") == "blonde", r)
    REGLE["casse_of"] = True
    r = pv.appliquer_look(TW, VA, "brune")
    REGLE["casse_of"] = False
    check("bouton OnlyFans changé à la relecture : dit, pas de « ✅ »", not r["ok"] and "OnlyFans" in r["erreur"], r)
    LIENS["lnk_page"] = json.loads(json.dumps(PAGE))

    print("3. Le bouton ✏️ et les clics")

    def clic(cid, qui=VA, typ=3, gid=TW):
        return {"type": typ, "guild_id": gid, "channel_id": "T1", "token": "jeton", "application_id": "app",
                "member": {"user": {"id": qui}, "roles": [], "permissions": "0"},
                "data": {"custom_id": cid}, "message": {"id": "m", "flags": 32768}}

    def ids(rep):
        return [b.get("custom_id") for row in (rep.get("data") or {}).get("components") or []
                for b in row.get("components") or []]
    r = tk.traiter(clic(f"page:o:{VA}"))
    check("✏️ Modifier : un choix en privé — 3 looks puis « ✏️ Modifier moi-même »",
          r.get("type") == 4 and r["data"]["flags"] == tk.EPHEMERE
          and ids(r) == [f"page:lbrune:{VA}", f"page:lblonde:{VA}", f"page:lgeneral:{VA}", f"page:m:{VA}"], r)
    styles = [b.get("style") for b in r["data"]["components"][0]["components"]]
    check("… le look en place est en vert (Blonde), les autres gris",
          styles == [2, 3, 2, 1], styles)
    check("… au plus 5 boutons, custom_id courts, finis par l'uid",
          len(ids(r)) <= 5 and all(len(c) <= 100 and c.endswith(f":{VA}") for c in ids(r)))
    r = tk.traiter(clic(f"page:m:{VA}"))
    check("« Modifier moi-même » : la fenêtre d'avant (photo, nom, bio, bouton, fond)",
          r.get("type") == 9 and r["data"]["custom_id"] == f"page:f:{VA}" and len(r["data"]["components"]) == 5, r)
    SUITES.clear()
    r = tk.traiter(clic(f"page:lgeneral:{VA}"))
    check("un look cliqué : en fond (réponse différée), puis « ✅ Look « Général » posé »",
          r == {"type": 5, "data": {"flags": 64}} and SUITES and SUITES[-1].startswith("✅ Look « Général » posé")
          and LIENS["lnk_page"]["profile_picture"] == lk[2][3], (r, SUITES))
    r = tk.traiter(clic(f"page:lrousse:{VA}"))
    check("un look inconnu : refusé", r["type"] == 4 and "Look inconnu" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:lbrune:{VA}", qui=AUTRE))
    check("le look d'un autre VA : refusé", r["type"] == 4 and "Seul ce VA" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:lbrune:{AUTRE}", qui=AUTRE))
    check("sans page : « Pas encore » (ni lien ni page)", r["type"] == 4 and "Pas encore" in r["data"]["content"], r)
    _vl = dict(pv.LOOKS)
    pv.LOOKS.clear()
    try:
        r = tk.traiter(clic(f"page:o:{VA}"))
        check("serveur sans looks : ✏️ ouvre la fenêtre directement (comme avant)",
              r.get("type") == 9 and r["data"]["custom_id"] == f"page:f:{VA}", r)
    finally:
        pv.LOOKS.update(_vl)
finally:
    (gms.get_link, gms.update_link, pv.FICHIER, lv.lien_de, tk._suite, tk._EN_FOND, tk._fiche) = SAV

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
