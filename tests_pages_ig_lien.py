# -*- coding: utf-8 -*-
"""tests_pages_ig_lien.py — TRUST INSTAGRAM : la page 1 est le lien principal
(06/11/2026 au soir).

Propriétaire : « il n'y a pas 3 pages d'un coup, il y a une seule page pour
l'instant et puis on ajoute tranquillement […] comme sur Twitter, il y a les
options blonde, brune, général, mais par défaut, à tout le monde, la brune » ;
« tu gardes que celui qui est là, ou au pire tu disable la page » ; le look =
photo et fond seulement. Sans réseau ni data/ : gms et liens_va remplacés,
registre temporaire.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading

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
SORTIES = []


def _interdit(*a, **k):
    SORTIES.append(str(a[1:2])[:80])
    raise OSError("réseau interdit dans tests_pages_ig_lien")


socket.socket.connect = _interdit
socket.socket.connect_ex = _interdit
socket.getaddrinfo = _interdit


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:500]}]"))


AG, TW = pv.AGENCY_IG_ID, pv.TWITTER_ID
VA, VA2, VA3, VA4, AUTRE = "5001", "5002", "5003", "5004", "5009"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="pages_ig_lien_"))
BRUNE = pv.looks(TW)[0]
BLONDE = pv.looks(TW)[1]


def track(n):
    return f"https://onlyfans.com/liasxcret/c{n}"


def lien_gms(lid, sc, n, nom):
    return {"id": lid, "type": "landing", "display_name": nom,
            "profile_picture": f"https://images.getmysocial.com/links/x/{sc}/profile.jpg",
            "background_image": f"https://images.getmysocial.com/links/x/{sc}/background.jpg",
            "buttons": [{"label": "“exclusive” stuff lol", "url": track(n),
                         "geofilters": [{"country_code": "ES"}] * 233},
                        {"label": "MY TELEGRAM", "url": "https://t.me/m/x"}]}


LIENS = {}
APPELS = []
REGLE = {"refus_disable": set(), "refus_update": set(), "liste_ok": True}
# le registre au moment de chaque coupure (l'ordre rangement → coupure)
VU_A_LA_COUPURE = {}


def f_get(lid, team_id=None):
    l = LIENS.get(lid)
    return {"ok": True, "link": json.loads(json.dumps(l))} if l else {"ok": False, "error": "404"}


def f_update(lid, champs, team_id=None):
    APPELS.append(("update", lid, sorted(champs)))
    if lid in REGLE["refus_update"]:
        return {"ok": False, "error": "500 panne"}
    LIENS[lid].update(json.loads(json.dumps(champs)))
    return {"ok": True, "link": LIENS[lid]}


def f_disable(lid):
    APPELS.append(("disable", lid))
    VU_A_LA_COUPURE[lid] = [c for c, p in pv._lire()["pages"].items() if p.get("link_id") == lid]
    if lid in REGLE["refus_disable"]:
        return {"ok": False, "error": "429"}
    if lid in LIENS:
        LIENS[lid]["actif"] = False
    return {"ok": True}


def f_enable(lid):
    APPELS.append(("enable", lid))
    return {"ok": True}


def f_liste(equipe, force_refresh=False):
    APPELS.append(("liste", equipe, force_refresh))
    if not REGLE["liste_ok"]:
        return {"ok": False, "error": "429"}
    return {"ok": True, "links": [{"id": k, "display_name": v.get("display_name")} for k, v in LIENS.items()]}


FICHES = {}


def fiche(n, pseudo, lid, sc, actif=True):
    return {"link_id": lid, "public_url": f"https://getmysocial.com/{sc}", "shortcode": sc,
            "tracking": track(n), "numero": n, "pseudo": pseudo, "actif": actif}


SAV = {(m, n): getattr(m, n) for m, n in (
    (gms, "get_link"), (gms, "update_link"), (gms, "disable_link"), (gms, "enable_link"),
    (gms, "list_links_team"), (lv, "_etat"), (pv, "FICHIER"), (pv, "EN_FOND"), (pv, "LOOKS_PAR_PASSE"),
    (pv, "_reprendre_pages_avant_page1"), (tk, "_suite"), (tk, "_EN_FOND"), (tk, "_fiche"),
    (tk, "_maj_menu_v2"), (tk, "_api_reseau"))}
SUITES, MENUS = [], []
try:
    gms.get_link, gms.update_link, gms.disable_link, gms.enable_link = f_get, f_update, f_disable, f_enable
    gms.list_links_team = f_liste
    lv._etat = lambda: {"liens": FICHES}
    pv.FICHIER = TMP / "pages_va.json"
    pv.EN_FOND = lambda f: f()
    tk._suite = lambda jeton, texte, p=None: SUITES.append(texte)
    tk._EN_FOND = lambda f: f()
    tk._fiche = lambda g, u: {"salon": "T1"}
    tk._maj_menu_v2 = lambda g, u, *a, **k: MENUS.append((g, u)) or 1
    tk._api_reseau = lambda *a, **k: (0, None)

    print("1. Les règles")
    check("TRUST INSTAGRAM : plus de places fixes (FIXES vide), mais toujours des pages à la demande",
          pv.fixes(AG) == 0 and pv.sur_demande(AG) and not pv.FIXES and not pv.GABARITS_PLACE)
    check("… sa page 1 est le lien principal : plancher 1, aucune place gérée sans demande",
          pv.lien_page_1(AG) and pv.plancher(AG) == 1 and pv.places(AG, VA) == [] and pv.pages_max(AG, VA) == 1)
    check("… une page demandée copie la brune (liabrune), à toute place",
          pv.gabarit(AG, 2) == pv.gabarit(AG, 7) == "lnk_6aedd88bc7881b6c8066a247")
    check("… la page 1 ne se modifie pas par la fenêtre ; les pages demandées oui",
          not pv.modifiable(AG, 1) and pv.modifiable(AG, 2) and pv.modifiable(AG, 9))
    check("… les mêmes looks que Twitter (Brune, Blonde, Général), brune par défaut",
          pv.looks(AG) == pv.looks(TW) and pv.LOOK_DEFAUT.get(AG) == "brune")
    check("Twitter inchangé : pas de demandes, plancher 0, 1 page modifiable, pas de look par défaut",
          not pv.sur_demande(TW) and not pv.lien_page_1(TW) and pv.plancher(TW) == 0
          and pv.places(TW, VA) == [1] and pv.modifiable(TW, 1) and not pv.LOOK_DEFAUT.get(TW))

    print("2. Rangement des pages fixes de l'après-midi")
    for lid, sc, n, nom in (("lnk_m1", "sweetpearlyy", 92, "Instagram VA 92 @fiable0010"),
                            ("lnk_m2", "lildreamyy", 93, "Instagram VA 93 @b"),
                            ("lnk_m3", "babeyy", 94, "Instagram VA 94 @c"),
                            ("lnk_m4", "angelyy", 95, "Instagram VA 95 @d"),
                            ("lnk_p1", "velvetcandyy", 92, "Instagram VA 92 @fiable0010 page"),
                            ("lnk_p2", "honeycutieyy", 92, "Instagram VA 92 @fiable0010 page 2"),
                            ("lnk_p3", "pearlbbyy", 93, "Instagram VA 93 @b page"),
                            ("lnk_p4", "bbybunnyy", 94, "Instagram VA 94 @c page"),
                            ("lnk_t1", "starrdollyy", 160, "Twitter VA 160 @x page"),
                            ("lnk_gab", "tpligbrune1", 1, "Gabarit page IG 1 (liabrune)")):
        LIENS[lid] = lien_gms(lid, sc, n, nom)
    FICHES.update({f"{AG}:{VA}": fiche(92, "fiable0010", "lnk_m1", "sweetpearlyy"),
                   f"{AG}:{VA2}": fiche(93, "b", "lnk_m2", "lildreamyy"),
                   f"{AG}:{VA3}": fiche(94, "c", "lnk_m3", "babeyy", actif=False),
                   f"{AG}:{VA4}": fiche(95, "d", "lnk_m4", "angelyy")})
    pv._noter(AG, VA, link_id="lnk_p1", shortcode="velvetcandyy", public_url="https://getmysocial.com/velvetcandyy",
              etat="prete", actif=True, tracking=track(92))
    pv._noter(AG, f"{VA}#2", link_id="lnk_p2", shortcode="honeycutieyy", etat="prete", actif=True)
    pv._noter(AG, VA2, link_id="lnk_p3", shortcode="pearlbbyy", etat="prete", actif=True)
    pv._noter(AG, VA3, link_id="lnk_p4", shortcode="bbybunnyy", etat="prete", actif=False)
    pv._noter(TW, "160", link_id="lnk_t1", shortcode="starrdollyy", etat="prete", actif=True)
    # une page DEMANDÉE et acceptée (place 2 de VA4) : elle reste
    LIENS["lnk_d1"] = lien_gms("lnk_d1", "kittyyy", 95, "Instagram VA 95 @d page 2")
    d = pv._lire()
    d["demandes"] = {"abc": {"gid": AG, "uid": VA4, "etat": "acceptee", "place": 2}}
    pv._ecrire(d)
    pv._noter(AG, f"{VA4}#2", link_id="lnk_d1", shortcode="kittyyy", public_url="https://getmysocial.com/kittyyy",
              etat="prete", actif=True)
    check("une demande acceptée en place 2 compte (au-delà du plancher)", pv.places(AG, VA4) == [2])

    # une page tenue (look en cours) : attend le passage suivant
    tenu, libere = threading.Event(), threading.Event()

    def tenir():
        with pv._verrou_page(f"{AG}:{VA2}"):
            tenu.set()
            libere.wait(10)
    th = threading.Thread(target=tenir)
    th.start()
    tenu.wait(5)
    REGLE["refus_disable"] = {"lnk_p2"}
    b = pv.retirer_pages_hors_places(AG)
    libere.set()
    th.join()
    reg = pv._lire()
    anc = reg.get("anciennes") or {}
    check("rangées : la page 1 et la place 2 de VA, la page coupée de VA3 ; la page tenue de VA2 attend",
          sorted(b["rangees"]) == sorted([f"{AG}:{VA}", f"{AG}:{VA}#2", f"{AG}:{VA3}"])
          and f"{AG}:{VA2}" in reg["pages"], b)
    check("… la page DEMANDÉE de VA4 et la page Twitter restent dans « pages »",
          f"{AG}:{VA4}#2" in reg["pages"] and f"{TW}:160" in reg["pages"])
    check("… rangées AVANT d'être coupées (la reprise rallume une page coupée encore notée)",
          VU_A_LA_COUPURE.get("lnk_p1") == [] and VU_A_LA_COUPURE.get("lnk_p2") == [], VU_A_LA_COUPURE)
    ent = {x["shortcode"]: x for x in anc.values()}
    check("« anciennes » : link_id, adresse, place, raison ; une ancienne déjà coupée n'est pas recoupée",
          ent["velvetcandyy"]["link_id"] == "lnk_p1" and ent["velvetcandyy"]["place"] == 1
          and ent["honeycutieyy"]["place"] == 2 and "lien principal" in ent["velvetcandyy"]["raison"]
          and ("disable", "lnk_p4") not in APPELS and ent["bbybunnyy"]["a_couper"] is False, ent)
    check("… coupée : actif faux, plus à couper ; refusée (429) : encore à couper, essai compté",
          ent["velvetcandyy"]["actif"] is False and ent["velvetcandyy"]["a_couper"] is False
          and ent["honeycutieyy"]["a_couper"] is True and ent["honeycutieyy"]["essais_coupure"] == 1)
    check("… jamais supprimées : aucun appel autre que disable", {a[0] for a in APPELS} == {"disable"}, APPELS)
    REGLE["refus_disable"] = set()
    n = len(APPELS)
    b = pv.retirer_pages_hors_places(AG)
    ent = {x["shortcode"]: x for x in (pv._lire().get("anciennes") or {}).values()}
    check("passage suivant : la page libérée rangée et coupée, la coupure refusée refaite",
          b["rangees"] == [f"{AG}:{VA2}"] and ("disable", "lnk_p3") in APPELS[n:]
          and ("disable", "lnk_p2") in APPELS[n:] and ent["honeycutieyy"]["a_couper"] is False
          and ("disable", "lnk_p1") not in APPELS[n:], (b, APPELS[n:]))
    n = len(APPELS)
    check("un 3e passage ne fait rien", pv.retirer_pages_hors_places(AG) == {"rangees": [], "coupees": [], "rates": []}
          and APPELS[n:] == [])
    check("Twitter : rien rangé", pv.retirer_pages_hors_places(TW)["rangees"] == [] and f"{TW}:160" in pv._lire()["pages"])
    # registre qui refuse d'écrire : rien rangé, rien coupé
    pv._noter(AG, VA, link_id="lnk_p1b", shortcode="autreyy", etat="prete", actif=True)
    _vecr = pv._ecrire
    pv._ecrire = lambda d: False
    n = len(APPELS)
    b = pv.retirer_pages_hors_places(AG)
    pv._ecrire = _vecr
    check("registre qui refuse d'écrire : rien rangé, aucune coupure",
          b["rangees"] == [] and not [a for a in APPELS[n:] if a[0] == "disable"]
          and f"{AG}:{VA}" in pv._lire()["pages"], b)
    pv.retirer_pages_hors_places(AG)
    lids_anc = sorted(x["link_id"] for x in (pv._lire().get("anciennes") or {}).values())
    check("la même page rangée deux fois dans la même seconde : les deux gardées dans « anciennes »",
          "lnk_p1" in lids_anc and "lnk_p1b" in lids_anc, lids_anc)

    print("3. Copies orphelines")
    LIENS["lnk_orph"] = lien_gms("lnk_orph", "orphyy", 93, "Instagram VA 93 @b page 2")
    n = len(APPELS)
    b = pv.couper_copies_orphelines(AG)
    coup = [a[1] for a in APPELS[n:] if a[0] == "disable"]
    check("seule la copie au nom d'une page, inconnue du registre, est coupée (ni lien principal, ni gabarit, "
          "ni page notée ou rangée, ni Twitter)", coup == ["lnk_orph"], (coup, b))
    check("… une lecture de l'équipe, rafraîchie", [a for a in APPELS[n:] if a[0] == "liste"]
          == [("liste", pv._equipe(AG), True)])
    n = len(APPELS)
    check("… une seule fois par serveur", pv.couper_copies_orphelines(AG) == {"coupees": [], "rates": []}
          and APPELS[n:] == [])
    d = pv._lire()
    d["orphelines_vues"] = {}
    pv._ecrire(d)
    REGLE["liste_ok"] = False
    pv.couper_copies_orphelines(AG)
    REGLE["liste_ok"] = True
    check("équipe illisible : refait au passage suivant", not (pv._lire().get("orphelines_vues") or {}).get(AG))
    pv.couper_copies_orphelines(AG)

    print("4. La brune par défaut sur le lien principal")
    pv.LOOKS_PAR_PASSE = 2
    n = len(APPELS)
    b = pv.poser_looks_par_defaut(AG)
    check("LOOKS_PAR_PASSE (2) liens par passage, lien coupé (VA3) laissé",
          len(b["poses"]) == 2 and "babeyy" not in b["poses"], b)
    m1 = LIENS["lnk_m1"]
    check("… photo et fond de la brune, diapo vidée ; bio, boutons, tracking, pays, Telegram intacts",
          m1["profile_picture"] == BRUNE[3] and m1["background_image"] == BRUNE[4]
          and m1["profile_picture_slides"] == [] and m1["buttons"][0]["url"] == track(92)
          and len(m1["buttons"][0]["geofilters"]) == 233 and m1["buttons"][1]["url"] == "https://t.me/m/x"
          and all(set(a[2]) == {"display_name", "profile_picture", "profile_picture_slides", "background_image"}
                  for a in APPELS[n:] if a[0] == "update"), m1)
    check("… noté par lien : look « brune » sur le lien principal", pv.look_du_lien(AG, VA) == "brune")
    b = pv.poser_looks_par_defaut(AG)
    check("passage suivant : le reste (VA4), personne deux fois", b["poses"] == ["angelyy"], b)
    n = len(APPELS)
    check("puis plus rien", pv.poser_looks_par_defaut(AG)["poses"] == [] and APPELS[n:] == [])
    # le VA a choisi la blonde : jamais remis en brune
    pv.appliquer_look(AG, VA2, "blonde", n=1)
    n = len(APPELS)
    pv.poser_looks_par_defaut(AG)
    check("un look choisi par le VA n'est jamais remplacé par la brune",
          pv.look_du_lien(AG, VA2) == "blonde" and LIENS["lnk_m2"]["profile_picture"] == BLONDE[3] and APPELS[n:] == [])
    # lien refait (nouvel id) : il repart d'emyigbase → brune reposée
    LIENS["lnk_m1b"] = lien_gms("lnk_m1b", "newyy", 92, "Instagram VA 92 @fiable0010")
    FICHES[f"{AG}:{VA}"] = fiche(92, "fiable0010", "lnk_m1b", "newyy")
    check("lien refait : l'ancienne note ne compte plus", pv.look_du_lien(AG, VA) == "")
    b = pv.poser_looks_par_defaut(AG)
    check("… et la brune est reposée sur le nouveau", b["poses"] == ["newyy"]
          and LIENS["lnk_m1b"]["profile_picture"] == BRUNE[3], b)
    # un lien qui refuse : 3 essais puis plus rien
    LIENS["lnk_m5"] = lien_gms("lnk_m5", "refusyy", 96, "Instagram VA 96 @e")
    FICHES[f"{AG}:5005"] = fiche(96, "e", "lnk_m5", "refusyy")
    REGLE["refus_update"] = {"lnk_m5"}
    for _ in range(4):
        pv.poser_looks_par_defaut(AG)
    essais = [a for a in APPELS if a[0] == "update" and a[1] == "lnk_m5"]
    check("un lien qui refuse : ESSAIS_REPRISE (3) essais puis il attend qu'on regarde",
          len(essais) == pv.ESSAIS_REPRISE and not pv.look_du_lien(AG, "5005"), len(essais))
    REGLE["refus_update"] = set()
    check("Twitter : aucun look par défaut", pv.poser_looks_par_defaut(TW) == {"poses": [], "rates": []})

    print("5. appliquer_look : page 1 = le lien, page 2 = la page demandée")
    r = pv.appliquer_look(AG, VA4, "general", n=1)
    check("page 1 : le lien principal reçoit le look", r["ok"] and LIENS["lnk_m4"]["profile_picture"] ==
          pv.looks(AG)[2][3] and pv.look_du_lien(AG, VA4) == "general", r)
    r = pv.appliquer_look(AG, VA4, "blonde", n=2)
    check("page 2 : la page demandée, pas le lien", r["ok"] and LIENS["lnk_d1"]["profile_picture"] == BLONDE[3]
          and LIENS["lnk_m4"]["profile_picture"] == pv.looks(AG)[2][3]
          and pv.page_de(AG, f"{VA4}#2").get("look") == "blonde", r)
    check("page 1 : la fenêtre (modifier_page) refusée", not pv.modifiable(AG, 1))

    print("6. Le menu du ticket")

    def sections(uid, l):
        return tk._sections_pages_fixes(AG, uid, l, ticket={"salon": "T1"})

    def ids(s):
        return [b.get("custom_id") for x in s if x.get("type") == 1 for b in x.get("components") or []]
    s = sections(VA, FICHES[f"{AG}:{VA}"])
    txt = s[0]["content"]
    check("« Page 1 · ton lien 🔗 (newyy) », sans répéter l'adresse ; plus de page 2 ni 3",
          txt == "**📄 Tes pages**\nPage 1 · ton lien 🔗 (newyy)", txt)
    check("… ✏️ Page 1 (le choix du look) puis ➕ Demander une page",
          ids(s) == [f"page:o:{VA}", f"pgd:new:{VA}"], ids(s))
    s = sections(VA4, FICHES[f"{AG}:{VA4}"])
    check("avec une page acceptée : Page 1 = le lien, Page 2 = son adresse, ✏️ sur les deux",
          s[0]["content"] == "**📄 Tes pages**\nPage 1 · ton lien 🔗 (angelyy)\nPage 2 · https://getmysocial.com/kittyyy",
          s[0])
    check("… boutons ✏️ Page 1, ✏️ Page 2, puis ➕", ids(s)[:2] == [f"page:o:{VA4}", f"page:o2:{VA4}"], ids(s))
    s = sections(VA3, FICHES[f"{AG}:{VA3}"])
    check("lien coupé : « Page 1 · 🚫 désactivée », sans ✏️ ni ➕",
          s[0]["content"] == "**📄 Tes pages**\nPage 1 · 🚫 désactivée" and f"page:o:{VA3}" not in ids(s)
          and f"pgd:new:{VA3}" not in ids(s), s)

    print("7. Les clics")

    def clic(cid, qui=VA, typ=3, valeurs=None):
        data = {"custom_id": cid}
        if valeurs:
            data["values"] = valeurs
        return {"type": typ, "guild_id": AG, "channel_id": "T1", "token": "jeton", "application_id": "app",
                "member": {"user": {"id": qui}, "roles": [], "permissions": "0"},
                "data": data, "message": {"id": "m", "flags": 32768}}

    def boutons(rep):
        return [(b.get("custom_id"), b.get("style")) for row in (rep.get("data") or {}).get("components") or []
                for b in row.get("components") or []]
    r = tk.traiter(clic(f"page:o:{VA}"))
    check("✏️ Page 1 : les 3 looks, la brune en vert, sans « Modifier moi-même »",
          r.get("type") == 4 and boutons(r) == [(f"page:lbrune:{VA}", 3), (f"page:lblonde:{VA}", 2),
                                                (f"page:lgeneral:{VA}", 2)]
          and "Ta page 1 (ton lien)" in r["data"]["content"], r)
    SUITES.clear()
    r = tk.traiter(clic(f"page:lblonde:{VA}"))
    check("un look : en fond, « ✅ Look « Blonde » posé sur ta page 1 (ton lien). », sur le lien principal",
          r == {"type": 5, "data": {"flags": 64}} and SUITES == ["✅ Look « Blonde » posé sur ta page 1 (ton lien)."]
          and LIENS["lnk_m1b"]["profile_picture"] == BLONDE[3] and pv.look_du_lien(AG, VA) == "blonde", (r, SUITES))
    for cid in (f"page:m:{VA}", f"page:new:{VA}"):
        r = tk.traiter(clic(cid))
        check(f"{cid.split(':')[1]} sur la page 1 : refusé (« elle change par un look »)",
              r["type"] == 4 and "change par un look" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:lbrune:{VA}", qui=AUTRE))
    check("le look d'un autre VA : refusé", r["type"] == 4 and "Seul ce VA" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:lrousse:{VA}"))
    check("un look inconnu : refusé", r["type"] == 4 and "Look inconnu" in r["data"]["content"], r)
    r = tk.traiter(clic(f"page:sel:{VA}", valeurs=["1"]))
    check("la liste déroulante, choix « Page 1 » : le choix du look", r.get("type") == 4
          and boutons(r)[0][0] == f"page:lbrune:{VA}", r)
    r = tk.traiter(clic(f"page:o2:{VA4}", qui=VA4))
    check("✏️ Page 2 (demandée) : les looks ET « Modifier moi-même »",
          [c for c, _s in boutons(r)] == [f"page:lbrune2:{VA4}", f"page:lblonde2:{VA4}", f"page:lgeneral2:{VA4}",
                                          f"page:m2:{VA4}"], r)
    r = tk.traiter(clic(f"page:m2:{VA4}", qui=VA4))
    check("… « Modifier moi-même » : la fenêtre « Ma page 2 »",
          r.get("type") == 9 and r["data"]["title"] == "Ma page 2" and r["data"]["custom_id"] == f"page:f2:{VA4}", r)

    print("8. La reprise : rangement d'abord, menus redessinés")
    pv._noter(AG, VA2, link_id="lnk_p9", shortcode="encoreyy", etat="prete", actif=True)
    VUS = {}

    def reprise_vue(gid):
        VUS["pages"] = [c for c in pv._lire()["pages"] if c.startswith(AG + ":")]
        return {"ok": True}
    pv._reprendre_pages_avant_page1 = reprise_vue
    MENUS.clear()
    pv.reprendre_pages(AG)
    check("la page fixe est rangée AVANT la reprise (sinon elle la rallumerait)",
          f"{AG}:{VA2}" not in VUS["pages"] and f"{AG}:{VA4}#2" in VUS["pages"], VUS)
    check("… puis le menu de son VA est redessiné", MENUS == [(AG, VA2)], MENUS)
finally:
    for (m, n), v in SAV.items():
        setattr(m, n, v)

check("aucune connexion réseau tentée", not SORTIES, SORTIES)
print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
