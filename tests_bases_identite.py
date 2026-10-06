# -*- coding: utf-8 -*-
"""tests_bases_identite.py — les bases « TEMPLATE <identite> » du serveur US.

Demande du propriétaire (06/10/2026) : « avoir une base et juste changer les
PP et la photo c'est tout ». Il poste dans le salon admin « bases-identites »
le nom d'une identité US et deux photos ; le bot crée dans GetMySocial (équipe
JESSY LE RETOUR) la page « TEMPLATE <identite> », copie du style de
lilskysmk2, et répond son adresse seule.

Ce qui est vérifié :
  - la requête est EXACTEMENT celle de l'essai réussi du 06/10 (champs du
    modèle moins les exclus, JSON pour dict/list/bool, boutons sans block_id
    ni None, team_id sans « tm_ », fichiers profilePicture / backgroundImage) ;
  - les photos : carré centré 400–1024 px, fond 1080×1920, JPEG RVB sans EXIF,
    orientation EXIF appliquée, HEIC lu ou refusé clairement, non-image refusée ;
  - adresses déjà prises (409) : essai suivant, borné ; forfait (403), quota
    (429 / pause / budget), réseau : dit, jamais en boucle ;
  - la réponse est vérifiée (photos neuves, nom, équipe) : non conforme ->
    désactivée, jamais supprimée ;
  - remplacement : TOUTES les pages « TEMPLATE x » actives de l'équipe (celle
    du registre, une faite à la main, une orpheline) sont désactivées APRÈS
    la nouvelle, gardées dans « anciens », jamais supprimées ; une
    désactivation ratée n'est pas un ✅ ; le cache vidé APRÈS ;
  - adresses : on repart après la plus haute connue (1 POST par
    remplacement, même au 8e) ; seuls les 409 « adresse prise » changent
    d'adresse ; un 5xx relit l'équipe avant de conclure ;
  - page rejetée : désactivée ET renommée (le module VA ne la copie plus) ;
    photo par défaut repérée (horodatage de l'envoi) ;
  - le bouton OnlyFans vise Jessye, plus Emy ;
  - le cog : seul un administrateur, seul ce salon, seul le serveur US ;
    une photo / trois photos / pas d'image / identité inconnue -> ❌ et la
    raison ; succès -> ⏳ puis ✅ et l'adresse seule ; « liste » ✅/➖ (la liste
    de l'équipe, ordre alphabétique, noms échappés) coupée à 2000 signes ;
    message vide relu, puis dit (rôle du bot mentionné : dit) ; salon privé
    créé une fois, reconnu décoré, accentué ou suffixé ; droits du bot
    reposés ; serveur indisponible : rien créé ; ⏳ laissés par un
    redémarrage repris.

Hors réseau : GetMySocial (requests et gms) et Discord sont des doublures ;
les fichiers du module pointent vers un dossier temporaire (data/ n'est pas
touché). Lancement : python tests_bases_identite.py
"""
from __future__ import annotations

import ast
import asyncio
import copy
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile
import contextlib
import threading
import time
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_bases_us_"))

# La page modèle telle que GET /v3/links/lnk_6abb26204ae4ffa662156701 l'a
# rendue le 06/10/2026 (copie exacte).
MODELE = json.loads(r'''{"id": "lnk_6abb26204ae4ffa662156701", "object": "link", "type": "landing", "shortcode": "lilskysmk2", "url": null, "buttons": [{"block_id": "54e3ad93-36d5-4a35-8eb3-9081d1f6589b", "label": "“exclusive” stuff lol ", "url": "https://onlyfans.com/emy.brw", "description": "(yes, for free 😭)", "image_url": null, "cover_image_url": null, "profile_image_url": null, "icon_url": null, "button_effect": "2", "button_animation": "bounce", "container_style": "custom-color", "container_color": "#d99be3", "text_color": "#000000", "desc_color": "#FFFFFF", "disable_logo": false, "open_in_new_tab": false, "is_age_restricted": false, "grid_size": "2x1", "grid_columns": null, "height": null, "text_style": null, "text_align": null, "divider_line": null, "divider_color": null, "divider_gap": null, "duration": null, "start_date": null, "end_date": null, "countdown_style": null, "digits_color": null, "monetization": {"type": "none"}, "geofilters": [], "smart_redirect": {"enabled": false, "destination_url": "", "trigger_after_visits": 3, "within_days": 7}, "carousel_slides": []}], "display_name": "lil sky ♡ (copie)", "bio": "{{color:#ffffff}}posting my secretttts :3{{/color}}", "notes": null, "status": "active", "deeplink_enabled": true, "user_id": "usr_68e4961d3abdf07547f50bd7", "created": 1790649888, "updated": 1791247275, "profile_picture": "https://images.getmysocial.com/profile-slides/68e4961d3abdf07547f50bd7/1790649888560-9a5fa5079a39.jpg", "profile_picture_slides": [{"url": "https://images.getmysocial.com/profile-slides/68e4961d3abdf07547f50bd7/1790649888560-9a5fa5079a39.jpg", "media_type": "image", "_id": "6ac443abb8d63d2636176f8e"}], "background_image": "https://images.getmysocial.com/68e4961d3abdf07547f50bd7/1790649888666-113b5c987ad8.jpg", "background_blur": false, "background_color": 0, "custom_background_color": "#8B5CF6", "custom_text_color": "#6366F1", "texts_color": 1, "font_family": 3, "buttons_styles": 0, "template": 0, "name_user": "Emy  ♡", "online": true, "location": {"display": 0, "position": 0, "style": 0, "text_color": ""}, "fallback_location": "Paris, France", "response_time": null, "social_media_links": [], "verified_badge": false, "verified_badge_color": "#1DA1F2", "show_profile_picture": true, "disable_link_logos": false, "whitelabel": false, "google_analytics": null, "facebook_pixel": null, "facebook_pixel_events": [], "tiktok_pixel": null, "tiktok_pixel_events": [], "snapchat_pixel": null, "snapchat_pixel_events": [], "x_pixel": null, "x_event_id": null, "hotjar_site_id": null, "tracking_parameters": [], "seo": {}, "safe_page_enabled": false, "strict_bot_protection": false, "landing_page_bot_protection": false, "age_verification_enabled": false, "redirect_cta_subtitle": null, "redirect_cta_button": null, "open_in_new_tab": false, "strict_deeplink": false, "strict_deeplink_design": 0, "smart_redirect": {"enabled": false, "destination_url": "", "trigger_after_visits": 2, "within_days": 7}, "traffic_recovery": {"enabled": false, "destination_url": ""}, "ab_testing": {"enabled": false, "control_weight": 50, "total_visitors": 0, "variants": []}, "geofilters": [], "audio_enabled": false, "audio_url": null, "audio_autoplay": true, "audio_loop": true, "audio_style": "pill", "audio_cta": null, "selected_domain": null, "team_id": null, "group_id": null}''')

EQUIPE_SANS_TM = "6a0e4739bfa0c238f20a8bf5"
BASE = "https://api.getmysocial.com/v3"
US = 1535758943324999711
YOSHI = 1505416430840189041
IDENTITES = ["ibenhaastrup", "mini_caryn", "ema_bb0", "nanas__nyspam"]

# ─────────────────────────────────────── doublure de gms (AVANT l'import) ──
JOURNAL = []       # l'ordre des appels : ("get"|"post"|"disable", ...)

fg = types.ModuleType("gms")
fg.PUBLIC_REST_BASE = BASE
fg.PUBLIC_LINK_DOMAIN = "https://getmysocial.com"
fg.etat = {}
fg.notes, fg.refus, fg.desactives, fg.supprimes, fg.tags_budget = [], [], [], [], []


fg.listes, fg.maj, fg.liste_suite = [], [], []
fg.cache = {"liens": None}


def _gms_remise():
    fg.etat.clear()
    fg.etat.update(pause=0, budget=True, cle="cle-test", disable_ok=True, tag=None, maj_ok=True)
    for lst in (fg.notes, fg.refus, fg.desactives, fg.supprimes, fg.tags_budget, fg.listes,
                fg.maj, fg.liste_suite):
        lst.clear()
    fg.cache["liens"] = None


class _api_tag:
    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        self.prev = fg.etat.get("tag")
        fg.etat["tag"] = self.tag
        return self

    def __exit__(self, *a):
        fg.etat["tag"] = self.prev
        return False


def _api_note(status):
    fg.notes.append((int(status or 0), fg.etat.get("tag")))


def _budget_ok(tag=None):
    fg.tags_budget.append(tag)
    return fg.etat["budget"]


def _noter_refus(message):
    fg.refus.append(message)
    if "today: 0" in str(message):
        fg.etat["pause"] = 7836


def _disable_link(link_id):
    fg.desactives.append((link_id, fg.etat.get("tag")))
    JOURNAL.append(("disable", link_id))
    if fg.etat["disable_ok"]:
        if link_id in FR.liens:
            FR.liens[link_id]["status"] = "inactive"
        return {"ok": True, "data": {"id": link_id, "status": "inactive"}}
    return {"ok": False, "error": "HTTP 500 : panne"}


def _list_links_team(team_id, force_refresh=False):
    """Comme gms : un cache que seul invalidate_grouping_cache (ou force) vide."""
    fg.listes.append((team_id, bool(force_refresh), fg.etat.get("tag")))
    JOURNAL.append(("liste", bool(force_refresh)))
    if fg.liste_suite and not fg.liste_suite.pop(0):
        return {"ok": False, "error": "HTTP 503"}
    tid = team_id if team_id.startswith("tm_") else "tm_" + team_id
    if force_refresh or fg.cache["liens"] is None:
        fg.cache["liens"] = [copy.deepcopy(l) for l in FR.liens.values() if l.get("team_id") == tid]
    return {"ok": True, "links": copy.deepcopy(fg.cache["liens"])}


def _invalider():
    JOURNAL.append(("invalidate",))
    fg.cache["liens"] = None


def _call_tool(nom, args=None, **k):
    if nom == "update_link":
        fg.maj.append(dict(args or {}))
        JOURNAL.append(("update", (args or {}).get("link_id")))
        if not fg.etat["maj_ok"]:
            return {"ok": False, "error": "HTTP 500 : panne"}
        l = FR.liens.get((args or {}).get("link_id"))
        if l is not None and "display_name" in args:
            l["display_name"] = args["display_name"]
        return {"ok": True, "data": {"id": (args or {}).get("link_id")}}
    return _interdit(nom, args)


def _interdit(*a, **k):
    fg.supprimes.append((a, k))
    return {"ok": False, "error": "interdit"}


fg.api_tag = _api_tag
fg._api_note = _api_note
fg.budget_ok = _budget_ok
fg.pause_restante = lambda: fg.etat["pause"]
fg.get_api_key = lambda: fg.etat["cle"]
fg._gms_note_429 = lambda: fg.refus.append("429")
fg._noter_refus = _noter_refus
fg.disable_link = _disable_link
fg.delete_link = _interdit
fg.delete_links = _interdit
fg._call_tool = _call_tool
fg.list_links_team = _list_links_team
fg.invalidate_grouping_cache = _invalider
_gms_remise()
sys.modules["gms"] = fg

import discord                         # noqa: E402
import safe_json                       # noqa: E402
import bases_identite_us as b          # noqa: E402
from cogs import bases_identite as cb  # noqa: E402

b.CONFIG = TMP / "bases_identite_us_config.json"
b.REGISTRE = TMP / "bases_identite_us.json"


# ──────────────────────────────────────────────── doublure de requests ──

class Rep:
    def __init__(self, status, j=None, text=None):
        self.status_code = status
        self._j = j
        self.text = text if text is not None else (json.dumps(j, ensure_ascii=False) if j is not None else "")

    def json(self):
        if self._j is None:
            raise ValueError("pas de JSON")
        return copy.deepcopy(self._j)


class FauxRequests:
    def __init__(self):
        self.remise()

    def remise(self):
        self.gets, self.posts, self.rep_get, self.rep_post = [], [], [], []
        self.pris = set()          # adresses prises AILLEURS (autre equipe de la plateforme)
        self.liens = {}            # les pages qui existent : {id: lien}
        self.n = 0
        self.surcharge = {}        # ce que la prochaine page creee rendra de travers

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": dict(headers or {}), "tag": fg.etat.get("tag")})
        JOURNAL.append(("get", url))
        r = self.rep_get.pop(0) if self.rep_get else Rep(200, MODELE)
        if isinstance(r, Exception):
            raise r
        return r

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        self.posts.append({"url": url, "headers": dict(headers or {}), "data": dict(data or {}),
                           "files": dict(files or {}), "tag": fg.etat.get("tag")})
        JOURNAL.append(("post", (data or {}).get("shortcode")))
        r = self.rep_post.pop(0) if self.rep_post else self.creer
        if isinstance(r, Exception):
            raise r
        return r(data) if callable(r) else r

    def creer(self, data, **surcharge):
        sc = data["shortcode"]
        if sc in self.pris or any(l["shortcode"] == sc for l in self.liens.values()):
            return Rep(409, {"error": {"code": "shortcode_taken", "message": "Shortcode already taken"}})
        self.n += 1
        ms = int(time.time() * 1000)
        # la forme des photos envoyees, vue dans essai_create.json
        lien = {"id": f"lnk_{self.n:024x}", "object": "link", "type": "landing", "shortcode": sc,
                "display_name": data["display_name"], "status": "active", "created": ms // 1000,
                "profile_picture": f"https://images.getmysocial.com/68e4961d3abdf07547f50bd7/{ms}-{self.n:012x}.jpg",
                "background_image": f"https://images.getmysocial.com/68e4961d3abdf07547f50bd7/{ms + 129}-{self.n + 4096:012x}.jpg",
                "team_id": "tm_" + data["team_id"], "name_user": data.get("name_user"),
                "buttons": json.loads(data.get("buttons") or "[]")}
        lien.update(self.surcharge)
        lien.update(surcharge)
        self.liens[lien["id"]] = copy.deepcopy(lien)
        return Rep(201, lien)

    def a_la_main(self, lid, nom, sc, status="active", created=1790000000, team="tm_" + EQUIPE_SANS_TM,
                  type_="landing"):
        """Une page faite dans l'editeur GetMySocial (ou restee orpheline)."""
        self.liens[lid] = {"id": lid, "type": type_, "shortcode": sc, "display_name": nom,
                           "status": status, "created": created, "team_id": team}

    def actives(self, identite):
        return sorted(l["id"] for l in self.liens.values()
                      if l["status"] == "active" and l["display_name"] == "TEMPLATE " + identite)


FR = FauxRequests()
b.requests = FR


def remise():
    _gms_remise()
    FR.remise()
    JOURNAL.clear()
    for p in TMP.glob("bases_identite_us*"):
        p.unlink()
    b._CACHE_MODELE.update(id=None, t=0.0, modele=None)
    b._HEIF["pret"] = None


# ─────────────────────────────────────────────────────────────── images ──

def image(taille=(800, 600), couleur=(200, 30, 90), fmt="JPEG", mode="RGB"):
    from PIL import Image
    im = Image.new(mode, taille, couleur)
    o = io.BytesIO()
    im.save(o, fmt)
    return o.getvalue()


def deux_moities(taille, gauche, droite, orientation=None):
    """Moitié gauche d'une couleur, droite d'une autre ; EXIF Orientation optionnel."""
    from PIL import Image
    w, h = taille
    im = Image.new("RGB", taille, gauche)
    im.paste(Image.new("RGB", (w - w // 2, h), droite), (w // 2, 0))
    o = io.BytesIO()
    if orientation:
        ex = Image.Exif()
        ex[0x0112] = orientation
        im.save(o, "JPEG", quality=95, exif=ex.tobytes())
    else:
        im.save(o, "JPEG", quality=95)
    return o.getvalue()


def ouvrir(d):
    from PIL import Image
    im = Image.open(io.BytesIO(d))
    im.load()
    return im


def proche(px, couleur, tol=40):
    return all(abs(int(a) - int(c)) <= tol for a, c in zip(px, couleur))


ROUGE, BLEU = (220, 20, 20), (20, 20, 220)
PP, FOND = image((900, 900), (200, 30, 90)), image((1080, 1920), (30, 90, 200))


# L'ESSAI REUSSI DU 06/10, recopie ICI et non importe du module : un champ
# change dans le module doit faire echouer ce banc.
EXCLU_ESSAI = {"id", "object", "created", "updated", "user_id", "status", "url", "profile_picture",
               "profile_picture_slides", "background_image", "team_id", "group_id",
               "selected_domain", "shortcode", "display_name", "notes"}


OF_JESSYE = "https://onlyfans.com/jessyewdiference"


def champs_essai(modele, shortcode, display_name, name_user=None):
    m = copy.deepcopy(modele)
    m["buttons"] = [{k: v for k, v in bt.items() if k != "block_id" and v is not None}
                    for bt in m["buttons"]]
    # seule VALEUR changee depuis l'essai : le bouton OF du modele (Emy, cote
    # FR) vise la creatrice des identites US
    for bt in m["buttons"]:
        if "onlyfans.com" in bt.get("url", ""):
            bt["url"] = OF_JESSYE
    if name_user:
        m["name_user"] = name_user
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else str(v))
              for k, v in m.items() if k not in EXCLU_ESSAI and v is not None}
    fields.update(shortcode=shortcode, display_name=display_name, type="landing",
                  team_id=EQUIPE_SANS_TM)
    return fields


# ═════════════════════════════════════════════════════════════════════════
print("1) La doublure de gms suit le vrai gms.py")
src_gms = (BOT / "gms.py").read_text(encoding="utf-8")
arbre = ast.parse(src_gms)
noms_gms = {n.name for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
noms_gms |= {t.id for n in arbre.body if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name)}
utilises = {"api_tag", "_api_note", "budget_ok", "pause_restante", "get_api_key", "_gms_note_429",
            "_noter_refus", "disable_link", "invalidate_grouping_cache", "PUBLIC_REST_BASE",
            "PUBLIC_LINK_DOMAIN", "list_links_team", "_call_tool"}
check("tout ce que le module appelle existe dans gms.py", utilises <= noms_gms,
      sorted(utilises - noms_gms))
prio = next((ast.literal_eval(n.value) for n in arbre.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "PRIORITES" for t in n.targets)), None)
check("étiquette des appels : pas « fond » (s'effacerait la première)",
      isinstance(prio, dict) and prio.get(b.ETIQUETTE, "normal") != "fond", f"{b.ETIQUETTE} -> {prio}")
check("PUBLIC_REST_BASE du vrai gms = la base doublée",
      f'PUBLIC_REST_BASE = "{BASE}"' in src_gms)
src_mod = (BOT / "bases_identite_us.py").read_text(encoding="utf-8")
check("module : aucune suppression GetMySocial (delete_link/delete_links)",
      "delete_link" not in src_mod.replace("delete_links est definitif", ""))
check("module : registre écrit par safe_json, jamais write_text(json.dumps",
      "safe_json.write(REGISTRE" in src_mod and "write_text(json.dumps" not in src_mod)
src_inf = ast.parse((BOT / "infloww_liens.py").read_text(encoding="utf-8"))
consts = {t.id: n.value.value for n in src_inf.body if isinstance(n, ast.Assign)
          and isinstance(n.value, ast.Constant) for t in n.targets if isinstance(t, ast.Name)}
check("une seule vérité : équipe et créatrice = celles d'infloww_liens (et de liens_identite_us)",
      consts.get("EQUIPE_GMS") == b.EQUIPE == "tm_" + EQUIPE_SANS_TM and consts.get("CREATRICE") == b.CREATRICE,
      (consts.get("EQUIPE_GMS"), consts.get("CREATRICE")))

# ═════════════════════════════════════════════════════════════════════════
print("2) La requête de création = l'essai réussi")
remise()
r = b.creer_base("ibenhaastrup", PP, FOND, par="seven (1)", identites=IDENTITES)
check("création : ok, adresse tplibenhaastrup", r["ok"] and r["url"] == "https://getmysocial.com/tplibenhaastrup", r)
check("modèle lu par GET /v3/links/<modèle> avec la clé Bearer",
      len(FR.gets) == 1 and FR.gets[0]["url"] == f"{BASE}/links/lnk_6abb26204ae4ffa662156701"
      and FR.gets[0]["headers"].get("Authorization") == "Bearer cle-test", FR.gets)
p = FR.posts[0] if FR.posts else {"data": {}, "files": {}, "headers": {}, "url": ""}
check("POST sur /v3/links avec la clé Bearer", p["url"] == f"{BASE}/links"
      and p["headers"].get("Authorization") == "Bearer cle-test", p["url"])
attendu = champs_essai(MODELE, "tplibenhaastrup", "TEMPLATE ibenhaastrup")
check("champs texte EXACTEMENT ceux de l'essai réussi", p["data"] == attendu,
      {k: (p["data"].get(k), attendu.get(k)) for k in set(p["data"]) ^ set(attendu)
       or [k for k in attendu if p["data"].get(k) != attendu[k]]})
check("team_id sans « tm_ »", p["data"].get("team_id") == EQUIPE_SANS_TM, p["data"].get("team_id"))
bt = json.loads(p["data"].get("buttons", "[]"))
check("boutons : sans block_id ni valeur nulle ; le bouton OF vise Jessye, plus Emy (FR)",
      bt and all("block_id" not in x and None not in x.values() for x in bt)
      and bt[0]["url"] == OF_JESSYE and "emy.brw" not in json.dumps(p["data"]), bt)
check("le reste du bouton est celui du modèle (libellé, couleurs, effet)",
      bt and {k: v for k, v in bt[0].items() if k != "url"}
      == {k: v for k, v in MODELE["buttons"][0].items() if k not in ("url", "block_id") and v is not None})
check("booléens en JSON, nombres en texte, emoji intacts",
      p["data"].get("deeplink_enabled") == "true" and p["data"].get("font_family") == "3"
      and "😭" in p["data"].get("buttons", ""), {k: p["data"].get(k) for k in ("deeplink_enabled", "font_family")})
check("aucun champ exclu ni nul envoyé (notes, status, profile_picture…)",
      not ({"notes", "status", "profile_picture", "background_image", "user_id", "group_id",
            "selected_domain", "url", "id"} & set(p["data"])))
check("fichiers : profilePicture et backgroundImage (jamais le snake_case refusé)",
      set(p["files"]) == {"profilePicture", "backgroundImage"}, sorted(p["files"]))
check("fichiers : JPEG, type image/jpeg",
      all(v[2] == "image/jpeg" and v[1][:2] == b"\xff\xd8" for v in p["files"].values()))
check("appels étiquetés « bases-us » et comptés dans le budget de gms",
      all(x["tag"] == "bases-us" for x in FR.gets + FR.posts)
      and fg.notes == [(200, "bases-us"), (201, "bases-us")] and "bases-us" in fg.tags_budget,
      f"{fg.notes} {fg.tags_budget}")
e = b.base_de("ibenhaastrup")
check("registre : link_id, shortcode, url, nom affiché du modèle, par, quand, anciens",
      e and e["link_id"] == r["link_id"] and e["shortcode"] == "tplibenhaastrup"
      and e["url"] == r["url"] and e["nom_affiche"] == "Emy  ♡" and e["par"] == "seven (1)"
      and isinstance(e["quand"], int) and e["anciens"] == [] and e["display_name"] == "TEMPLATE ibenhaastrup"
      and e["equipe"] == "tm_" + EQUIPE_SANS_TM, e)
check("registre : JSON valide sur disque, pas de .tmp qui traîne",
      json.loads(b.REGISTRE.read_text(encoding="utf-8")).get("ibenhaastrup", {}).get("link_id") == r["link_id"]
      and not list(TMP.glob("*.tmp")))
check("bases_registre : l'identité y est", list(b.bases_registre()) == ["ibenhaastrup"])
check("rien n'a été supprimé ni désactivé", not fg.supprimes and not fg.desactives)
check("liste de l'équipe lue (JESSY LE RETOUR), étiquetée « bases-us »",
      fg.listes and all(t == "tm_" + EQUIPE_SANS_TM and tag == "bases-us" for t, _, tag in fg.listes), fg.listes)

remise()
r = b.creer_base("@Ibenhaastrup", PP, FOND, nom_affiche="  Iben ♡ ", identites=IDENTITES)
p = FR.posts[0]
check("majuscule d'iPhone et @ : retrouve « ibenhaastrup »",
      r["ok"] and p["data"]["display_name"] == "TEMPLATE ibenhaastrup", p["data"].get("display_name"))
check("2e ligne : name_user remplacé, le reste identique à l'essai",
      p["data"] == champs_essai(MODELE, "tplibenhaastrup", "TEMPLATE ibenhaastrup", "Iben ♡"),
      p["data"].get("name_user"))
check("registre : nom affiché retenu", b.base_de("ibenhaastrup")["nom_affiche"] == "Iben ♡")
r2 = b.creer_base("mini_caryn", PP, FOND, identites=IDENTITES)
check("modèle en cache : pas de 2e GET dans les 10 min", r2["ok"] and len(FR.gets) == 1, len(FR.gets))

# ═════════════════════════════════════════════════════════════════════════
print("3) Les photos")
a, f, err = b.preparer_images(image((3000, 2000)), image((2000, 2000)))
check("PP 3000×2000 -> 1024×1024, fond 2000×2000 -> 1080×1920, JPEG RVB",
      not err and ouvrir(a).size == (1024, 1024) and ouvrir(f).size == (1080, 1920)
      and ouvrir(a).format == "JPEG" and ouvrir(a).mode == "RGB", err)
a, f, err = b.preparer_images(image((600, 900)), image((1080, 1920)))
check("PP 600×900 -> carré 600, fond déjà 1080×1920 gardé",
      not err and ouvrir(a).size == (600, 600) and ouvrir(f).size == (1080, 1920), err)
a, f, err = b.preparer_images(image((300, 300)), image((300, 500)))
check("PP 300 -> 400 (minimum conseillé), petit fond agrandi en 1080×1920",
      not err and ouvrir(a).size == (400, 400) and ouvrir(f).size == (1080, 1920), err)
a, f, err = b.preparer_images(image((500, 500), (0, 0, 0, 0), "PNG", "RGBA"), image((800, 800), fmt="WEBP"))
check("PNG transparent et WEBP acceptés, convertis en JPEG",
      not err and ouvrir(a).format == "JPEG" and ouvrir(f).format == "JPEG", err)
a, f, err = b.preparer_images(deux_moities((800, 400), ROUGE, BLEU, 6), deux_moities((1000, 500), ROUGE, BLEU, 6))
pa, pf = ouvrir(a) if a else None, ouvrir(f) if f else None
check("EXIF orientation 6 appliquée (PP : rouge en haut, bleu en bas)",
      not err and proche(pa.getpixel((pa.width // 2, 5)), ROUGE) and proche(pa.getpixel((pa.width // 2, pa.height - 5)), BLEU),
      err or (pa.getpixel((pa.width // 2, 5)), pa.getpixel((pa.width // 2, pa.height - 5))))
check("EXIF orientation 6 appliquée (fond : rouge en haut, bleu en bas, 1080×1920)",
      pf is not None and pf.size == (1080, 1920) and proche(pf.getpixel((540, 5)), ROUGE)
      and proche(pf.getpixel((540, 1914)), BLEU))
check("aucun EXIF d'orientation renvoyé (sinon tourné deux fois)",
      pa is not None and 0x0112 not in pa.getexif() and 0x0112 not in pf.getexif())
a, f, err = b.preparer_images(b"bonjour", FOND)
check("PP qui n'est pas une image : refusée, et dit laquelle", a is None and "photo de profil" in err, err)
a, f, err = b.preparer_images(PP, b"%PDF-1.4 pas une image")
check("fond qui n'est pas une image : refusé, et dit lequel", f is None and err.startswith("fond"), err)
a, f, err = b.preparer_images(b"", FOND)
check("fichier vide : refusé", a is None and "vide" in err, err)
a, f, err = b.preparer_images(image((20, 20)), FOND)
check("image minuscule : refusée", a is None and "trop petite" in err, err)
HEIC_FAUX = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
b._HEIF["pret"] = False
a, f, err = b.preparer_images(HEIC_FAUX, FOND)
check("HEIC sans pillow_heif : erreur claire (JPG/PNG)", a is None and "HEIC" in err and "JPG" in err, err)
b._HEIF["pret"] = None
try:
    import pillow_heif
    from PIL import Image as _I
    o = io.BytesIO()
    pillow_heif.from_pillow(_I.new("RGB", (700, 500), (10, 200, 30))).save(o, format="HEIF", quality=90)
    a, f, err = b.preparer_images(o.getvalue(), FOND)
    check("HEIC avec pillow_heif : lu et converti en JPEG", not err and ouvrir(a).format == "JPEG"
          and ouvrir(a).size == (500, 500), err)
except ImportError:
    check("HEIC avec pillow_heif : pillow_heif installé dans venv/", False, "pillow_heif absent")
from PIL import Image as _I
o = io.BytesIO()
_I.new("I;16", (800, 800), 40000).save(o, "PNG")
a, f, err = b.preparer_images(o.getvalue(), FOND)
pa = ouvrir(a) if a else None
check("PNG gris 16 bits (40000) : ramené sur 8 bits (≈155), pas une photo toute blanche",
      not err and pa is not None and proche(pa.getpixel((10, 10)), (155, 155, 155), 3),
      err or (pa.getpixel((10, 10)) if pa else None))
o = io.BytesIO()
_I.new("F", (800, 800), 0.5).save(o, "TIFF")
a, f, err = b.preparer_images(o.getvalue(), FOND)
pa = ouvrir(a) if a else None
check("image flottante 0..1 (0,5) : gris moyen, pas noire",
      not err and pa is not None and proche(pa.getpixel((10, 10)), (127, 127, 127), 3),
      err or (pa.getpixel((10, 10)) if pa else None))
remise()
r = b.creer_base("ibenhaastrup", b"pas une image", FOND, identites=IDENTITES)
check("photo invalide : refusée AVANT tout appel (ni GET du modèle, ni liste, ni POST)",
      not r["ok"] and not FR.posts and not FR.gets and not fg.listes and "photo de profil" in r["erreur"],
      (r, len(FR.gets), fg.listes))

# ═════════════════════════════════════════════════════════════════════════
print("4) Adresses")
check("tpl + identité", b.shortcode_base("ibenhaastrup") == "tplibenhaastrup")
check("2e essai : chiffre au bout", b.shortcode_base("ibenhaastrup", 1) == "tplibenhaastrup2")
check("tirets bas gardés", b.shortcode_base("nanas__nyspam") == "tplnanas__nyspam")
check("accents et points retirés", b.shortcode_base("Émilie.Rose") == "tplemilierose", b.shortcode_base("Émilie.Rose"))
longs = [b.shortcode_base("x" * 40, k) for k in range(b.ESSAIS_SHORTCODE)]
check("24 signes au plus, même avec suffixe, tous différents",
      all(len(s) <= 24 for s in longs) and len(set(longs)) == len(longs), longs)
check("toujours valide pour GetMySocial ([a-z0-9_-]{3,24})",
      all(re.fullmatch(r"[a-z0-9_-]{3,24}", b.shortcode_base(n, k)) for n in IDENTITES + ["Émilie.Rose", "a" * 50]
          for k in range(6)))

# ═════════════════════════════════════════════════════════════════════════
print("5) Erreurs de GetMySocial")
remise()
FR.rep_post = [Rep(409, {"error": {"code": "shortcode_taken", "message": "taken"}}),
               Rep(409, {"error": {"code": "shortcode_recently_deleted", "retryAfterSeconds": 3600}})]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("409 pris puis récemment supprimé : 3e adresse essayée et retenue",
      r["ok"] and [x["data"]["shortcode"] for x in FR.posts] == ["tplibenhaastrup", "tplibenhaastrup2", "tplibenhaastrup3"]
      and r["url"].endswith("/tplibenhaastrup3") and b.base_de("ibenhaastrup")["shortcode"] == "tplibenhaastrup3", r)
remise()
FR.rep_post = [Rep(409, text="Error 409 (shortcode_taken)")] + [Rep(409, {"error": {"code": "shortcode_taken"}})] * 20
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check(f"toujours pris : {b.ESSAIS_SHORTCODE} essais puis erreur, pas de boucle",
      not r["ok"] and len(FR.posts) == b.ESSAIS_SHORTCODE and "déjà prise" in r["erreur"]
      and b.base_de("ibenhaastrup") is None, (len(FR.posts), r["erreur"]))
check("adresses refusées retenues au registre : le prochain envoi ne les repaie pas",
      set(((safe_json.load(b.REGISTRE, default={}) or {}).get("ibenhaastrup") or {}).get("adresses") or [])
      == {x["data"]["shortcode"] for x in FR.posts})
FR.rep_post = []
n0 = len(FR.posts)
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("envoi suivant : 1 seul POST, sur l'adresse d'après",
      r["ok"] and len(FR.posts) == n0 + 1 and r["shortcode"] == b.shortcode_base("ibenhaastrup", b.ESSAIS_SHORTCODE),
      (len(FR.posts) - n0, r.get("shortcode")))
remise()
FR.rep_post = [Rep(409, {"error": {"code": "display_name_conflict", "message": "name already used"}})]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("409 qui n'est pas une adresse prise : un seul POST, le code de GetMySocial dit",
      not r["ok"] and len(FR.posts) == 1 and "display_name_conflict" in r["erreur"]
      and "adresse" not in r["erreur"], r)
for st in (403, 404):
    remise()
    FR.rep_post = [Rep(st, {"error": {"code": "team_access_denied", "message": "no access"}})]
    r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
    check(f"{st} : dit que la clé n'a peut-être pas le droit de créer dans JESSY LE RETOUR",
          not r["ok"] and len(FR.posts) == 1 and "JESSY LE RETOUR" in r["erreur"]
          and "tm_" + EQUIPE_SANS_TM in r["erreur"], r)
remise()
FR.rep_post = [Rep(403, {"error": {"code": "plan_limit_reached", "message": "Plan limit"}})]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("403 plan_limit_reached : dit, un seul essai", not r["ok"] and len(FR.posts) == 1 and "forfait" in r["erreur"], r)
remise()
FR.rep_post = [Rep(429, text="Error 429 (rate_limit_exceeded): RATE_LIMITED: retry after 7836s. "
                             "Do not retry before then. Requests remaining this minute: 117, today: 0.")]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("429 « today: 0 » : refus transmis à gms (pause armée), quota dit",
      not r["ok"] and len(FR.posts) == 1 and any("today: 0" in str(x) for x in fg.refus)
      and "quota" in r["erreur"], r)
n_get, n_post = len(FR.gets), len(FR.posts)
r = b.creer_base("mini_caryn", PP, FOND, identites=IDENTITES)
check("pendant la pause : aucun appel ne part", not r["ok"] and len(FR.gets) == n_get
      and len(FR.posts) == n_post and "reprise vers" in r["erreur"], r)
remise()
fg.etat["pause"] = 600
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("pause déjà en cours : ni GET ni POST", not r["ok"] and not FR.gets and not FR.posts and "épuisé" in r["erreur"], r)
remise()
fg.etat["budget"] = False
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("budget du jour réservé à la paie : ni GET ni POST", not r["ok"] and not FR.gets and not FR.posts
      and "budget" in r["erreur"], r)
remise()
fg.etat["cle"] = ""
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("clé API absente : dit, rien n'est envoyé", not r["ok"] and not FR.posts and "clé" in r["erreur"], r)
remise()
FR.rep_post = [Rep(400, {"error": {"code": "invalid_url", "message": "bad media url"}})]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("400 invalid_* : code dit, pas de nouvel essai", not r["ok"] and len(FR.posts) == 1 and "invalid_url" in r["erreur"], r)
remise()
FR.rep_post = [TimeoutError("lecture expirée")]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("réseau coupé, page absente de l'équipe relue : pas de 2e envoi, « renvoie »",
      not r["ok"] and len(FR.posts) == 1 and "absente" in r["erreur"] and "renvoie" in r["erreur"]
      and fg.notes[-1] == (0, "bases-us") and fg.listes[-1][1] is True, r)
remise()
FR.rep_post = [TimeoutError("lecture expirée")]
fg.liste_suite[:] = [True, False]          # la relecture apres la panne echoue
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("réseau coupé, équipe illisible : « vérifie dans GetMySocial avant de renvoyer »",
      not r["ok"] and len(FR.posts) == 1 and "vérifie dans GetMySocial" in r["erreur"], r)
for st in (502, 524):
    remise()
    FR.rep_post = [lambda d: (FR.creer(d), Rep(st, text="<html>timeout</html>"))[1]]
    r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
    check(f"HTTP {st} mais la page a été créée : retrouvée dans l'équipe, vérifiée, retenue",
          r["ok"] and len(FR.posts) == 1 and r["url"].endswith("/tplibenhaastrup")
          and b.base_de("ibenhaastrup")["link_id"] == r["link_id"], r)
remise()
FR.rep_post = [Rep(503, text="Service Unavailable")]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("HTTP 503 sans page : pas « refuse », relue puis « renvoie »",
      not r["ok"] and "refuse" not in r["erreur"] and "HTTP 503" in r["erreur"] and "renvoie" in r["erreur"], r)
remise()
fg.liste_suite[:] = [False]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("équipe illisible avant la création : rien n'est créé (on ne saurait pas quoi couper)",
      not r["ok"] and not FR.posts and "JESSY LE RETOUR" in r["erreur"], r)
remise()
FR.rep_get = [Rep(404, {"error": {"code": "link_not_found"}})]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("modèle introuvable (404) : dit, rien n'est créé", not r["ok"] and not FR.posts and "introuvable" in r["erreur"], r)
remise()
FR.rep_get = [Rep(200, {**MODELE, "type": "directlink"})]
m, err = b.lire_modele()
check("modèle qui n'est pas une page : refusé", m is None and "n'est pas une page" in err, err)
remise()
FR.rep_get = [ConnectionError("dns")]
m, err = b.lire_modele()
check("lire_modele : jamais d'exception, une phrase", m is None and "réseau" in err, err)

# ═════════════════════════════════════════════════════════════════════════
print("6) Réponse vérifiée")
remise()
FR.rep_post = [lambda d: FR.creer(d, profile_picture=MODELE["profile_picture"])]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
reg = json.loads(b.REGISTRE.read_text(encoding="utf-8")) if b.REGISTRE.exists() else {}
check("photo de profil du modèle rendue : page désactivée, pas retenue, trace gardée",
      not r["ok"] and "identique au modèle" in r["erreur"] and "désactivée" in r["erreur"]
      and [x[0] for x in fg.desactives] == ["lnk_" + "0" * 23 + "1"] and b.base_de("ibenhaastrup") is None
      and reg.get("ibenhaastrup", {}).get("rates", [{}])[0].get("desactivee") is True
      and not fg.supprimes, (r, fg.desactives, reg))
check("bases_registre ignore une entrée sans base active", b.bases_registre() == {})
nouveau = fg.maj[0].get("display_name", "") if fg.maj else ""
check("page rejetée RENOMMÉE « REJET TEMPLATE ibenhaastrup … » (le module VA prend aussi une page inactive)",
      len(fg.maj) == 1 and nouveau.startswith("REJET TEMPLATE ibenhaastrup ")
      and fg.maj[0]["link_id"] == "lnk_" + "0" * 23 + "1" and b.identite_de_base(nouveau) is None
      and reg["ibenhaastrup"]["rates"][0]["renommee"] == nouveau, (fg.maj, reg))
check("après rejet : plus aucune page « TEMPLATE ibenhaastrup » vue, « liste » dit ➖",
      not b.pages_de_base(b.liens_equipe()[0], "ibenhaastrup") and "ibenhaastrup" not in b.etat_liste()[0])
remise()
fg.etat["maj_ok"] = False
FR.rep_post = [lambda d: FR.creer(d, background_image=None)]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("renommage raté : l'erreur dit que la page s'appelle encore TEMPLATE et que le module VA peut la copier",
      not r["ok"] and "s'appelle encore « TEMPLATE ibenhaastrup »" in r["erreur"] and "module VA" in r["erreur"], r)
remise()
fg.update_link = lambda lid, champs, team_id=None: (fg.maj.append({"link_id": lid, **champs, "via": "update_link",
                                                                     "team_id": team_id}) or {"ok": True})
FR.rep_post = [lambda d: FR.creer(d, background_image=None)]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("gms.update_link présent (branche liens-identite-us) : c'est lui qui renomme",
      fg.maj and fg.maj[0].get("via") == "update_link" and fg.maj[0]["display_name"].startswith("REJET ")
      and fg.maj[0]["team_id"] == "tm_" + EQUIPE_SANS_TM, fg.maj)
del fg.update_link
for quoi, url in (("photo par défaut", "https://images.getmysocial.com/defaults/avatar.png"),
                  ("photo ancienne", "https://images.getmysocial.com/68e4961d3abdf07547f50bd7/1700000000000-abcdef123456.jpg")):
    remise()
    FR.rep_post = [lambda d, u=url: FR.creer(d, profile_picture=u)]
    r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
    check(f"{quoi} rendue (201) : repérée, page rejetée", not r["ok"] and "pas celle envoyée" in r["erreur"]
          and b.base_de("ibenhaastrup") is None and len(fg.desactives) == 1, r)
check("photo du modèle (profile-slides) : fraîche au regard de SA création, pas aujourd'hui",
      b._photo_neuve(MODELE["profile_picture"], MODELE["created"])
      and not b._photo_neuve(MODELE["profile_picture"], time.time()))
check("photo de l'essai réel du 06/10 : reconnue comme envoyée",
      b._photo_neuve("https://images.getmysocial.com/68e4961d3abdf07547f50bd7/1791248795949-611e8be94c36.jpg",
                     1791248796))
remise()
FR.rep_post = [lambda d: FR.creer(d, team_id="tm_6abb029639f60ccb3a54be05")]
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("mauvaise équipe : dit et désactivée", not r["ok"] and "équipe tm_6abb029639f60ccb3a54be05" in r["erreur"]
      and len(fg.desactives) == 1, r)
remise()
FR.rep_post = [lambda d: FR.creer(d, background_image=None)]
fg.etat["disable_ok"] = False
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("fond absent et désactivation ratée : dit « PAS désactivée » avec l'id",
      not r["ok"] and "fond absent" in r["erreur"] and "PAS désactivée" in r["erreur"] and "lnk_" in r["erreur"], r)

# ═════════════════════════════════════════════════════════════════════════
print("7) Remplacement d'une base")
remise()
r1 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
JOURNAL.clear()
n0 = len(FR.posts)
r2 = b.creer_base("ibenhaastrup", image((900, 900), (1, 2, 3)), FOND, identites=IDENTITES)
e = b.base_de("ibenhaastrup")
check("2e envoi : nouvelle base à l'adresse suivante, en 1 seul POST (l'ancienne sautée sans appel)",
      r1["ok"] and r2["ok"] and r2["link_id"] != r1["link_id"] and r2["remplace"] == r1["link_id"]
      and r2["url"].endswith("/tplibenhaastrup2") and len(FR.posts) == n0 + 1, (r1, r2, len(FR.posts) - n0))
etapes = [x[0] for x in JOURNAL if x[0] in ("post", "disable", "invalidate")]
check("ancienne désactivée APRÈS la création, cache de l'équipe vidé APRÈS la désactivation",
      etapes == ["post", "disable", "invalidate"] and ("disable", r1["link_id"]) in JOURNAL, JOURNAL)
check("registre : la nouvelle active, l'ancienne dans « anciens »",
      e["link_id"] == r2["link_id"] and e["anciens"] == [r1["link_id"]], e)
check("une seule base active pour l'identité chez GetMySocial", FR.actives("ibenhaastrup") == [r2["link_id"]],
      FR.actives("ibenhaastrup"))
check("jamais de suppression", not fg.supprimes)
r3 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("3e envoi : anciens = [1re, 2e], seule la 2e désactivée cette fois",
      r3["ok"] and b.base_de("ibenhaastrup")["anciens"] == [r1["link_id"], r2["link_id"]]
      and [x[0] for x in fg.desactives] == [r1["link_id"], r2["link_id"]], fg.desactives)
avant = b.base_de("ibenhaastrup")
FR.rep_post = [Rep(400, {"error": {"code": "invalid_shortcode"}})]
r4 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("création ratée : l'ancienne base reste active, rien de désactivé",
      not r4["ok"] and b.base_de("ibenhaastrup") == avant and len(fg.desactives) == 2
      and FR.actives("ibenhaastrup") == [avant["link_id"]], r4)
FR.surcharge = {"display_name": "autre"}
r5 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
FR.surcharge = {}
check("nouvelle non conforme : l'ancienne reste la base, seule la nouvelle coupée",
      not r5["ok"] and b.base_de("ibenhaastrup")["link_id"] == avant["link_id"]
      and fg.desactives[-1][0] != avant["link_id"] and FR.actives("ibenhaastrup") == [avant["link_id"]],
      (r5, fg.desactives))
fg.etat["disable_ok"] = False
r6 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
e = b.base_de("ibenhaastrup")
check("ancienne pas désactivée : PAS un succès — la nouvelle ne servira pas tant que l'ancienne est active",
      not r6["ok"] and "ne sera PAS utilisée" in r6["erreur"] and avant["shortcode"] in r6["erreur"]
      and r6["url"] and r6["url"] in r6["erreur"], r6)
check("… la nouvelle est quand même inscrite, l'ancienne gardée « à couper »",
      e["link_id"] == r6["link_id"] and avant["link_id"] in e["anciens"]
      and e["non_desactives"] == [avant["link_id"]], e)
fg.etat["disable_ok"] = True
r7 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("envoi suivant : les DEUX anciennes encore actives coupées",
      r7["ok"] and sorted(r7.get("coupees") or []) == sorted([avant["link_id"], r6["link_id"]])
      and FR.actives("ibenhaastrup") == [r7["link_id"]], (r7, FR.actives("ibenhaastrup")))
check("désactivations étiquetées « bases-us »", all(t == "bases-us" for _, t in fg.desactives), fg.desactives)

remise()
couts = []
for i in range(8):
    n0 = len(FR.posts)
    r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
    couts.append((len(FR.posts) - n0, r["ok"]))
check("8 remplacements de suite : 1 POST chacun, tous réussis (plus de blocage au 7e)",
      couts == [(1, True)] * 8 and FR.actives("ibenhaastrup") == [r["link_id"]]
      and r["url"].endswith("/tplibenhaastrup8"), (couts, r.get("url")))

remise()
FR.a_la_main("lnk_main", "TEMPLATE ibenhaastrup", "ibenmain", created=1780000000)
FR.a_la_main("lnk_lien", "TEMPLATE ibenhaastrup", "ibendirect", type_="directlink")
FR.a_la_main("lnk_autre", "TEMPLATE mini_caryn", "carynbase")
check("« liste » : une base faite à la main compte (✅), comme pour le module VA",
      b.etat_liste() == ({"ibenhaastrup", "mini_caryn"}, ""), b.etat_liste())
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("base faite à la main (absente du registre) : coupée aussi, gardée dans « anciens »",
      r["ok"] and r.get("coupees") == ["lnk_main"] and "lnk_main" in b.base_de("ibenhaastrup")["anciens"]
      and FR.actives("ibenhaastrup") == sorted([r["link_id"], "lnk_lien"]), (r, FR.actives("ibenhaastrup")))
check("… un lien direct au même nom et une autre identité ne sont pas touchés",
      FR.liens["lnk_lien"]["status"] == "active" and FR.liens["lnk_autre"]["status"] == "active")

remise()
FR.a_la_main("lnk_orph", "TEMPLATE ibenhaastrup", "tplibenhaastrup", created=int(time.time()) - 60)
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("orpheline (redémarrage entre le POST et le registre) : son adresse sautée sans POST, elle coupée",
      r["ok"] and [x["data"]["shortcode"] for x in FR.posts] == ["tplibenhaastrup2"]
      and r.get("coupees") == ["lnk_orph"] and FR.actives("ibenhaastrup") == [r["link_id"]], (r, FR.posts and FR.posts[0]["data"]["shortcode"]))

remise()
b.liens_equipe()                                # la liste est en cache…
FR.a_la_main("lnk_orph2", "TEMPLATE ibenhaastrup", "tplibenhaastrup", created=int(time.time()) - 30)
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)   # …sans l'orpheline
check("orpheline faite après la lecture (cache) : le 409 fait relire l'équipe, elle est coupée",
      r["ok"] and [x["data"]["shortcode"] for x in FR.posts] == ["tplibenhaastrup", "tplibenhaastrup2"]
      and r.get("coupees") == ["lnk_orph2"] and any(f for _, f, _ in fg.listes), (r, fg.listes))

remise()
FR.pris.add("tplibenhaastrup")                  # prise par une autre équipe
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
n0 = len(FR.posts)
r2 = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("adresse prise ailleurs : retenue, le remplacement suivant ne la repaie pas",
      r["ok"] and r2["ok"] and len(FR.posts) - n0 == 1 and r2["url"].endswith("/tplibenhaastrup3"), (r, r2))

# ═════════════════════════════════════════════════════════════════════════
print("8) Identité et configuration")
remise()
r = b.creer_base("  ", PP, FOND, identites=IDENTITES)
check("identité vide : refusée sans appel", not r["ok"] and "vide" in r["erreur"] and not FR.gets, r)
r = b.creer_base("ibenhastrup", PP, FOND, identites=IDENTITES)
check("faute de frappe : refusée, noms proches proposés",
      not r["ok"] and "n'est pas une identité US" in r["erreur"] and "ibenhaastrup" in r["erreur"]
      and not FR.gets, r)
check("proches : nom tronqué retrouvé", "nanas__nyspam" in b.proches("nanas", IDENTITES), b.proches("nanas", IDENTITES))
r = b.creer_base("...", PP, FOND)
check("sans liste : un nom sans lettre ni chiffre est refusé", not r["ok"] and "aucune lettre" in r["erreur"], r)
safe_json.write(b.CONFIG, {"base_link_id": "6abb000000000000000000aa", "equipe": "6a0e0000000000000000ffff"})
journal = io.StringIO()
with contextlib.redirect_stdout(journal):
    c = b.config()
check("config : préfixe lnk_ remis, salon par défaut ; « equipe » IGNORÉE (le module VA ne la lirait pas)",
      c == {"base_link_id": "lnk_6abb000000000000000000aa", "equipe": "tm_" + EQUIPE_SANS_TM,
            "salon": "bases-identites"}, c)
check("… et c'est dit au journal, pas tu", "ignorée" in journal.getvalue(), journal.getvalue())
r = b.creer_base("ibenhaastrup", PP, FOND, identites=IDENTITES)
check("config : autre modèle lu, mais toujours créé et vérifié dans JESSY LE RETOUR",
      r["ok"] and FR.gets[-1]["url"].endswith("/links/lnk_6abb000000000000000000aa")
      and FR.posts[-1]["data"]["team_id"] == EQUIPE_SANS_TM
      and b.base_de("ibenhaastrup")["equipe"] == "tm_" + EQUIPE_SANS_TM
      and all(t == "tm_" + EQUIPE_SANS_TM for t, _, _ in fg.listes), r)
faux_liu = types.ModuleType("liens_identite_us")
faux_liu.EQUIPE = "tm_" + EQUIPE_SANS_TM
faux_liu.identite_de_base = lambda nom: "vu-par-liu" if "TEMPALTE" in str(nom) else None
sys.modules["liens_identite_us"] = faux_liu
check("liens_identite_us présent : SA règle des noms de base est celle employée",
      b.identite_de_base("TEMPALTE x") == "vu-par-liu" and b.identite_de_base("TEMPLATE x") is None)
del sys.modules["liens_identite_us"]
check("sans lui : « TEMPLATE Iben Haastrup » -> ibenhaastrup ; « REJET TEMPLATE x » et « Templeton » ne sont pas des bases",
      b.identite_de_base("TEMPLATE Iben Haastrup") == "ibenhaastrup"
      and b.identite_de_base("REJET TEMPLATE ibenhaastrup 06-10 14h05") is None
      and b.identite_de_base("Templeton bob") is None)

# ═════════════════════════════════════════════════════════════════════════
print("9) Le cog")


class Perms:
    def __init__(self, admin):
        self.administrator = admin


class Auteur:
    def __init__(self, admin=True, bot=False):
        self.id, self.name, self.bot = 402069419393679370, "seven_ofm", bot
        self.guild_permissions = Perms(admin)


class Piece:
    def __init__(self, nom, data, ct="image/jpeg"):
        self.filename, self._d, self.content_type, self.size = nom, data, ct, len(data)

    async def read(self):
        return self._d


class Canal:
    def __init__(self, nom, cid=77):
        self.name, self.id, self.envoyes, self.a_relire, self.category = nom, cid, [], None, None
        self.droits = {}          # {id de la cible: droits} ; sinon le bot a tout, @everyone rien
        self.poses, self.historique, self.refus_droits = [], [], None

    async def send(self, content=None, **kw):
        self.envoyes.append({"content": content, **kw})
        return types.SimpleNamespace(id=len(self.envoyes))

    async def fetch_message(self, mid):
        if self.a_relire is None:
            raise RuntimeError("message introuvable")
        return self.a_relire

    def permissions_for(self, cible):
        d = self.droits.get(cible.id)
        if d is None:
            d = dict(cb.DROITS_BOT) if cible.nom == "me" else {"view_channel": False}
        return types.SimpleNamespace(**{k: d.get(k, False) for k in
                                        set(cb.DROITS_BOT) | {"view_channel"}})

    async def set_permissions(self, cible, reason=None, **kw):
        if self.refus_droits:
            raise self.refus_droits
        self.poses.append((cible, kw, reason))
        self.droits[cible.id] = {**(self.droits.get(cible.id) or {}), **kw}

    async def _hist(self, limit):
        for m in self.historique[:limit]:
            yield m

    def history(self, limit=100):
        return self._hist(limit)


class Cible:
    """Membre ou role : cle d'un dictionnaire de droits (hachable)."""
    def __init__(self, cid, nom):
        self.id, self.nom, self.name = cid, nom, nom


class Guilde:
    def __init__(self, gid=US, salons=()):
        self.id, self.name, self.unavailable = gid, "Youl4b", False
        self.me, self.default_role = Cible(YOSHI, "me"), Cible(gid, "everyone")
        self.self_role = Cible(424242, "Yoshi.exe")
        self.text_channels = list(salons)
        self.crees = []

    async def create_text_channel(self, nom, overwrites=None, reason=None, **kw):
        ch = Canal(nom, 900 + len(self.crees))
        self.crees.append({"nom": nom, "overwrites": overwrites, "reason": reason})
        self.text_channels.append(ch)
        return ch


class Message:
    def __init__(self, contenu, pieces=(), admin=True, canal=None, guilde=None, bot=False,
                 mtype=discord.MessageType.default):
        self.content, self.attachments = contenu, list(pieces)
        self.author = Auteur(admin, bot)
        self.channel = canal or Canal("bases-identites")
        self.guild = guilde or Guilde(salons=[self.channel])
        self.type, self.id, self.reactions, self.role_mentions = mtype, 5555, [], []

    async def add_reaction(self, e):
        self.reactions.append(("+", e))

    async def remove_reaction(self, e, membre):
        self.reactions.append(("-", e))


BOT_FAUX = types.SimpleNamespace(user=types.SimpleNamespace(id=YOSHI, mention=f"<@{YOSHI}>"), guilds=[])
cog = cb.BasesIdentite(BOT_FAUX)
check("cog : aucune commande slash ni préfixe (bot principal à 100/100)",
      cog.get_app_commands() == [] and cog.get_commands() == [])
src_cog = (BOT / "cogs" / "bases_identite.py").read_text(encoding="utf-8")
check("cog : n'emploie pas app_commands", "app_commands" not in src_cog)
main_ast = ast.parse((BOT / "main.py").read_text(encoding="utf-8"))
listes = {t.id: ast.literal_eval(n.value) for n in main_ast.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name) and t.id in ("MAIN_COGS", "ADMIN_COGS")}
check("enregistré dans MAIN_COGS (le bot admin n'est pas sur le serveur US)",
      "bases_identite" in listes.get("MAIN_COGS", []) and "bases_identite" not in listes.get("ADMIN_COGS", []))
check("setup(bot) présent et asynchrone", asyncio.iscoroutinefunction(getattr(cb, "setup", None)))

APPELS = []


def faux_creer(identite, pp, fond, nom_affiche=None, par="", identites=None):
    APPELS.append({"identite": identite, "pp": pp, "fond": fond, "nom_affiche": nom_affiche,
                   "par": par, "identites": identites, "thread": threading.get_ident()})
    return dict(REPONSE)


REPONSE = {}
vrai_creer, vrais_ids = cb.bases.creer_base, cb.identites_us
cb.bases.creer_base = faux_creer
cb.identites_us = lambda: list(IDENTITES)


def jouer(msg):
    APPELS.clear()
    asyncio.run(cog.on_message(msg))
    return msg


def envoyes(msg):
    return [x["content"] for x in msg.channel.envoyes]


DEUX = [Piece("pp.jpg", PP), Piece("fond.png", FOND, "image/png")]
REPONSE.update(ok=True, url="https://getmysocial.com/tplibenhaastrup", link_id="lnk_x", avertissement="")
m = jouer(Message("ibenhaastrup", DEUX, admin=False))
check("non-admin : ignoré (ni réaction, ni message, ni création)", not m.reactions and not m.channel.envoyes and not APPELS)
m = jouer(Message("ibenhaastrup", DEUX, canal=Canal("général")))
check("autre salon : ignoré", not m.reactions and not m.channel.envoyes and not APPELS)
m = jouer(Message("ibenhaastrup", DEUX, guilde=Guilde(gid=1111111111111111111)))
check("autre serveur (pas US) : ignoré", not m.reactions and not APPELS)
m = jouer(Message("ibenhaastrup", DEUX, bot=True))
check("message d'un bot : ignoré", not m.reactions and not APPELS)
m = jouer(Message("ibenhaastrup", DEUX, mtype=discord.MessageType.pins_add))
check("message système : ignoré", not m.reactions and not APPELS)

m = jouer(Message(f"<@{YOSHI}> Ibenhaastrup\nIben ♡", DEUX))
check("succès : ⏳ puis ✅ (⏳ retiré)", m.reactions == [("+", "⏳"), ("-", "⏳"), ("+", "✅")], m.reactions)
check("succès : l'adresse SEULE, dans un message ordinaire sans aperçu",
      envoyes(m) == ["https://getmysocial.com/tplibenhaastrup"]
      and m.channel.envoyes[0].get("suppress_embeds") is True and "reference" not in m.channel.envoyes[0],
      m.channel.envoyes)
a0 = APPELS[0] if APPELS else {}
check("mention retirée, 2e ligne = nom affiché, ordre des photos gardé (1re PP, 2e fond)",
      a0.get("identite") == "Ibenhaastrup" and a0.get("nom_affiche") == "Iben ♡"
      and a0.get("pp") == PP and a0.get("fond") == FOND and a0.get("identites") == IDENTITES
      and "402069419393679370" in a0.get("par", ""), {k: v for k, v in a0.items() if k not in ("pp", "fond")})
check("travail GetMySocial hors de la boucle (executor)", a0.get("thread") not in (None, threading.get_ident()))
m = jouer(Message("ibenhaastrup", DEUX, canal=Canal("🧱・bases-identites")))
check("salon décoré à la main : reconnu", len(APPELS) == 1, m.reactions)

m = jouer(Message("ibenhaastrup", DEUX[:1]))
check("1 seule photo : ❌ et la raison, rien créé",
      m.reactions == [("+", "❌")] and not APPELS and "Une seule photo" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("ibenhaastrup", DEUX + [Piece("x.jpg", PP)]))
check("3 photos : ❌ et la raison", not APPELS and "3 pièces jointes" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("ibenhaastrup", []))
check("aucune photo : ❌ « Il manque les 2 photos »", not APPELS and "Il manque les 2 photos" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("ibenhaastrup", [DEUX[0], Piece("contrat.pdf", b"%PDF", "application/pdf")]))
check("pièce jointe pas image : ❌ et son nom", not APPELS and "contrat.pdf" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("ibenhastrup", DEUX))
check("identité inconnue : ❌ et noms proches, sans ⏳ ni création",
      m.reactions == [("+", "❌")] and not APPELS and "Proches : ibenhaastrup" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("nanas_nyspam", DEUX))
check("noms proches échappés : « nanas__nyspam » ne se lit pas « nanasnyspam »",
      "nanas\\_\\_nyspam" in (envoyes(m) or [""])[0], envoyes(m))
m = jouer(Message("ibenhaastrup\nIben\nen trop", DEUX))
check("plus de 2 lignes : ❌", not APPELS and "2 lignes" in (envoyes(m) or [""])[0], envoyes(m))
REPONSE.clear()
REPONSE.update(ok=False, erreur="limite du forfait GetMySocial atteinte : plus de page possible")
m = jouer(Message("ibenhaastrup", DEUX))
check("échec : ⏳ puis ❌, raison en une ligne",
      m.reactions == [("+", "⏳"), ("-", "⏳"), ("+", "❌")]
      and envoyes(m) == ["❌ limite du forfait GetMySocial atteinte : plus de page possible"], (m.reactions, envoyes(m)))
REPONSE.clear()
REPONSE.update(ok=True, url="https://getmysocial.com/tplibenhaastrup2", avertissement="ancienne base tplibenhaastrup pas désactivée (HTTP 500)")
m = jouer(Message("ibenhaastrup", DEUX))
check("avertissement : l'adresse seule, puis une ligne ⚠️",
      envoyes(m) == ["https://getmysocial.com/tplibenhaastrup2",
                     "⚠️ ancienne base tplibenhaastrup pas désactivée (HTTP 500)"], envoyes(m))
cog.en_cours.add("ibenhaastrup")
m = jouer(Message("ibenhaastrup", DEUX))
check("même identité déjà en cours : ❌, pas de 2e création", not APPELS and "déjà en cours" in (envoyes(m) or [""])[0])
cog.en_cours.clear()

# message vide : l'intention Message Content manque
REPONSE.clear()
REPONSE.update(ok=True, url="https://getmysocial.com/tplibenhaastrup", avertissement="")
m = Message("", [])
m.channel.a_relire = types.SimpleNamespace(content="ibenhaastrup", attachments=DEUX)
jouer(m)
check("message livré vide : relu par l'API, puis traité", len(APPELS) == 1
      and envoyes(m) == ["https://getmysocial.com/tplibenhaastrup"], envoyes(m))
m = jouer(Message("", []))
check("toujours vide après relecture : ❌ et « mentionne-moi », jamais un silence",
      m.reactions == [("+", "❌")] and not APPELS and f"<@{YOSHI}>" in (envoyes(m) or [""])[0]
      and m.channel.envoyes[0].get("allowed_mentions") is not None, envoyes(m))
m = Message("", [])
m.role_mentions = [m.guild.self_role]
jouer(m)
check("rôle du bot mentionné (message vide) : ❌ « mentionne le membre, pas le rôle »",
      m.reactions == [("+", "❌")] and "rôle @Yoshi.exe" in (envoyes(m) or [""])[0]
      and f"<@{YOSHI}>" in (envoyes(m) or [""])[0], envoyes(m))


def creer_casse(*a, **k):
    raise RuntimeError("panne imprévue")


cb.bases.creer_base = creer_casse
m = jouer(Message("ibenhaastrup", DEUX))
check("exception après ⏳ : ⏳ retiré, ❌ posé (jamais les deux côte à côte)",
      m.reactions == [("+", "⏳"), ("-", "⏳"), ("+", "❌")] and "panne imprévue" in (envoyes(m) or [""])[0],
      (m.reactions, envoyes(m)))
cb.bases.creer_base = faux_creer
REPONSE.clear()
REPONSE.update(ok=False, url="https://getmysocial.com/tplnanas__nyspam2",
               erreur="https://getmysocial.com/tplnanas__nyspam2 créée, mais tplnanas__nyspam pas désactivée "
                      "(HTTP 500) : la nouvelle base ne sera PAS utilisée pour les VA tant que tplnanas__nyspam "
                      "est active — la couper dans GetMySocial")
m = jouer(Message("nanas__nyspam", DEUX))
check("ancienne pas coupée : ❌ (pas ✅), raison lisible, adresse intacte",
      m.reactions[-1] == ("+", "❌") and "ne sera PAS utilisée" in (envoyes(m) or [""])[0]
      and "https://getmysocial.com/tplnanas__nyspam2" in (envoyes(m) or [""])[0]
      and "tplnanas\\_\\_nyspam pas" in (envoyes(m) or [""])[0], envoyes(m))
REPONSE.clear()
REPONSE.update(ok=True, url="https://getmysocial.com/tplibenhaastrup", avertissement="")

# « liste » : la liste de l'equipe, celle que lit le module VA
remise()
FR.a_la_main("lnk_main", "TEMPLATE ibenhaastrup", "ibenmain")                 # faite à la main
FR.a_la_main("lnk_rej", "REJET TEMPLATE ema_bb0 06-10 14h05", "tplema_bb0", status="inactive")
safe_json.write(b.REGISTRE, {"ema_bb0": {"rates": [{"link_id": "lnk_rej"}]}})
m = jouer(Message(f"<@{YOSHI}> Liste", []))
check("« liste » : ✅ pour une base faite à la main (absente du registre), ➖ pour un rejet ; noms échappés",
      envoyes(m) == ["✅ ibenhaastrup\n➖ mini\\_caryn\n➖ ema\\_bb0\n➖ nanas\\_\\_nyspam"] and not m.reactions,
      envoyes(m))
fg.liste_suite[:] = [False]
safe_json.write(b.REGISTRE, {"mini_caryn": {"link_id": "lnk_c", "shortcode": "tplmini_caryn"}})
fg.cache["liens"] = None
m = jouer(Message("liste", []))
check("« liste », équipe illisible : dit en tête, puis d'après le registre",
      envoyes(m) and envoyes(m)[0].startswith("⚠️ GetMySocial illisible")
      and "✅ mini\\_caryn" in envoyes(m)[0] and "➖ ibenhaastrup" in envoyes(m)[0], envoyes(m))
remise()
beaucoup = [f"identite_tres_longue_numero_{i:04d}" for i in range(150)]
cb.identites_us = lambda: list(beaucoup)
m = jouer(Message("liste", []))
lignes = "\n".join(envoyes(m)).split("\n")
check("liste de plus de 2000 signes : coupée entre deux lignes, rien de perdu",
      len(envoyes(m)) >= 3 and all(len(t) <= 2000 for t in envoyes(m))
      and lignes == ["➖ " + discord.utils.escape_markdown(n) for n in beaucoup],
      [len(t) for t in envoyes(m)])
cb.identites_us = lambda: list(IDENTITES)
check("ordre de la liste : alphabétique, celui de la maquette",
      cb.textes_liste(sorted(IDENTITES, key=str.lower), {"ibenhaastrup"})[0].split("\n")
      == ["➖ ema\\_bb0", "✅ ibenhaastrup", "➖ mini\\_caryn", "➖ nanas\\_\\_nyspam"])

# de bout en bout, avec le vrai creer_base et la doublure de GetMySocial
cb.bases.creer_base = vrai_creer
remise()
m = jouer(Message(f"<@{YOSHI}> ibenhaastrup", DEUX))
check("de bout en bout : page créée, adresse seule postée, registre écrit",
      envoyes(m) == ["https://getmysocial.com/tplibenhaastrup"] and m.reactions[-1] == ("+", "✅")
      and b.base_de("ibenhaastrup") is not None and FR.posts[0]["data"]["display_name"] == "TEMPLATE ibenhaastrup",
      (envoyes(m), m.reactions))
m = jouer(Message("liste", []))
check("de bout en bout : la liste marque ✅ la base créée", envoyes(m) and envoyes(m)[0].startswith("✅ ibenhaastrup"), envoyes(m))

# le salon
g = Guilde(salons=[Canal("général")])
ch = asyncio.run(cog.assurer_salon(g))
ow = g.crees[0]["overwrites"] if g.crees else {}
check("salon absent : créé « bases-identites »", len(g.crees) == 1 and g.crees[0]["nom"] == "bases-identites")
check("salon privé : @everyone sans vue, le bot voit, écrit, réagit",
      ow.get(g.default_role) is not None and ow[g.default_role].view_channel is False
      and ow.get(g.me) is not None and ow[g.me].view_channel is True and ow[g.me].send_messages is True
      and ow[g.me].add_reactions is True and ow[g.me].read_message_history is True, ow)
asyncio.run(cog.assurer_salon(g))
check("2e passage : pas de doublon", len(g.crees) == 1)
g2 = Guilde(salons=[Canal("🧱・bases-identites")])
asyncio.run(cog.assurer_salon(g2))
check("salon décoré à la main : reconnu, pas recréé", not g2.crees)
for nom in ("bases-identités", "bases-identites-🧱", "🧱・bases-identités-🧱", "Bases-Identites"):
    g3 = Guilde(salons=[Canal(nom)])
    asyncio.run(cog.assurer_salon(g3))
    check(f"salon renommé « {nom} » : reconnu (messages lus), pas de doublon",
          cb.est_salon_bases(Canal(nom)) and not g3.crees)
check("… mais « bases-identites-2 » ou « bases » ne sont pas ce salon",
      not cb.est_salon_bases(Canal("bases-identites-2")) and not cb.est_salon_bases(Canal("bases")))
sourd = Canal("🧱・bases-identites")
sourd.droits[YOSHI] = {"view_channel": False}          # catégorie réservée, « synchroniser »
g4 = Guilde(salons=[sourd])
journal = io.StringIO()
with contextlib.redirect_stdout(journal):
    asyncio.run(cog.assurer_salon(g4))
check("salon existant que le bot ne voit pas : ses droits reposés (voir, écrire, réagir, historique)",
      not g4.crees and len(sourd.poses) == 1 and sourd.poses[0][0] is g4.me
      and all(sourd.poses[0][1].get(d) is True for d in cb.DROITS_VITAUX), (sourd.poses, journal.getvalue()))
asyncio.run(cog.assurer_salon(g4))
check("… une fois : au passage suivant, rien n'est reposé", len(sourd.poses) == 1)
sourd2 = Canal("bases-identites")
sourd2.droits[YOSHI] = {"view_channel": True, "send_messages": True}
sourd2.refus_droits = discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
journal = io.StringIO()
with contextlib.redirect_stdout(journal):
    asyncio.run(cog.assurer_salon(Guilde(salons=[sourd2])))
check("droits impossibles à reposer : dit au journal (lesquels manquent), pas d'exception",
      "add_reactions" in journal.getvalue() and "à la main" in journal.getvalue(), journal.getvalue())
public = Canal("bases-identites")
public.droits[US] = {"view_channel": True}
journal = io.StringIO()
with contextlib.redirect_stdout(journal):
    asyncio.run(cog.assurer_salon(Guilde(salons=[public])))
check("salon visible de @everyone : ATTENTION au journal (aucun message dans le salon)",
      "ATTENTION" in journal.getvalue() and not public.envoyes, journal.getvalue())
gi = Guilde(salons=[])
gi.unavailable = True
gm = Guilde(salons=[])
gm.me = None
BOT_FAUX.guilds = [gi, gm]
with contextlib.redirect_stdout(io.StringIO()):
    asyncio.run(cog._entretien.coro(cog))
check("serveur US indisponible au démarrage (ou bot inconnu) : aucun salon créé",
      not gi.crees and not gm.crees)
gus, gfr = Guilde(salons=[]), Guilde(gid=1505418484052394004, salons=[])
BOT_FAUX.guilds = [gus, gfr]
asyncio.run(cog._entretien.coro(cog))
check("entretien : salon créé sur le serveur US seulement", len(gus.crees) == 1 and not gfr.crees)
check("aucun message posté à la création du salon (ni notice ni épingle)",
      not any(c.envoyes for c in gus.text_channels) and "pin(" not in src_cog)


class Ancien:
    """Un message du salon relu par l'historique."""
    def __init__(self, mid, contenu, emojis, me=True):
        self.id, self.content = mid, contenu
        self.reactions = [types.SimpleNamespace(emoji=e, me=me) for e in emojis]
        self.faits = []

    async def add_reaction(self, e):
        self.faits.append(("+", e))

    async def remove_reaction(self, e, membre):
        self.faits.append(("-", e))


salon = Canal("bases-identites")
coupe_net = Ancien(1, f"<@{YOSHI}> ibenhaastrup", ["⏳"])
fini = Ancien(2, f"<@{YOSHI}> mini_caryn", ["⏳", "✅"])
rate = Ancien(3, f"<@{YOSHI}> ema_bb0", ["❌"])
autrui = Ancien(4, "", ["⏳"], me=False)
salon.historique = [coupe_net, fini, rate, autrui]
gr = Guilde(salons=[salon])
cog.repris.clear()
BOT_FAUX.guilds = [gr]
asyncio.run(cog._entretien.coro(cog))
check("redémarrage : le ⏳ du bot resté seul devient ❌, avec une ligne en réponse à ce message",
      coupe_net.faits == [("-", "⏳"), ("+", "❌")] and len(salon.envoyes) == 1
      and salon.envoyes[0].get("reference") is coupe_net
      and "ibenhaastrup" in salon.envoyes[0]["content"] and "redémarrage" in salon.envoyes[0]["content"],
      (coupe_net.faits, salon.envoyes))
check("… un ⏳ suivi de ✅, un ❌, un ⏳ d'un autre : pas touchés",
      not fini.faits and not rate.faits and not autrui.faits)
asyncio.run(cog._entretien.coro(cog))
check("… une seule fois (le tour suivant de l'entretien ne recommence pas)", len(salon.envoyes) == 1)
# la creation tourne dans un fil de l'executor : le verrou y est tenu
tenu, lacher = threading.Event(), threading.Event()


def _creation_en_cours():
    with b._VERROU:
        tenu.set()
        lacher.wait(5)


fil = threading.Thread(target=_creation_en_cours)
fil.start()
tenu.wait(5)
try:
    cog.repris.clear()
    coupe_net.faits.clear()
    asyncio.run(cog._entretien.coro(cog))
finally:
    lacher.set()
    fil.join()
check("… une création en cours dans ce processus : rien n'est déclaré interrompu", not coupe_net.faits)
BOT_FAUX.guilds = []

# la liste des identités : celle du menu US
cb.identites_us = vrais_ids
faux_user = types.ModuleType("cogs.user")
faux_user._jb_models_marche = lambda marche="us": ["zoe", "Alba", "mia"] if marche == "us" else ["julia"]
faux_user.EXCLURE_MENU = {"jessye"}
ancien_user = sys.modules.get("cogs.user")
sys.modules["cogs.user"] = faux_user
check("identités : celles du menu US (_jb_models_marche('us')), triées", cb.identites_us() == ["Alba", "mia", "zoe"],
      cb.identites_us())
faux_user._jb_models_marche = lambda marche="us": (_ for _ in ()).throw(RuntimeError("cassé"))
import cogs.welcome as _w           # noqa: E402
import marche as _marche            # noqa: E402
vrai_li, vrai_de = _w.list_identities, _marche.de
_w.list_identities = lambda *a, **k: ["julia", "jessye", "ibenhaastrup", "mini_caryn"]
_marche.de = lambda n: "fr" if n == "julia" else "us"
check("menu illisible : repli sur le marché des dossiers, sans la source jessye",
      cb.identites_us() == ["ibenhaastrup", "mini_caryn"], cb.identites_us())
_w.list_identities, _marche.de = vrai_li, vrai_de
if ancien_user is not None:
    sys.modules["cogs.user"] = ancien_user
else:
    sys.modules.pop("cogs.user", None)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{len(OKS)} OK, {len(FAILS)} échec(s)")
sys.exit(1 if FAILS else 0)
