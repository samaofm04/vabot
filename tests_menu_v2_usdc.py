"""Le menu en blocs et l'adresse USDC par réseau (04/11/2026, Twitter et Threads).

Propriétaire : « fais un truc plus carré » (le menu), « les virements sont en
USDC, choisis en Solana ou en ETH », l'adresse et le QR visibles « à tout
moment » ; maquette validée (« oui fais-la »), QR facultatif, « uniquement
Twitter et Threads ». Ce fichier prouve, sans réseau :
  1. le menu v2 : un conteneur, son lien et sa page en boutons-liens, la
     section Paiement porte le 💳 (retiré des rangées), rien d'autre ;
  2. ramener_menu : posé en v2 (drapeau, sans texte), rien d'écrit au second
     passage, une copie TEXTE d'avant reposée en v2 puis retirée ;
  3. le ménage reconnaît la copie v2, pas la carte Paiement ;
  4. le tour des liens et le miroir de l'accueil mettent le menu v2 à jour
     sur place, sans texte, et sans appel quand rien n'a bougé ;
  5. une réponse « sur place » (⭐ Confirmer) sur le menu v2 revient en blocs ;
  6. 💳 : choix du réseau, fenêtre (adresse + QR facultatif), adresse
     refusée sans rien écrire, adresse Ethereum + QR : carte épinglée avec
     l'image, menu à jour, réponse au VA ; changée sans QR : l'ancien QR n'est
     plus montré (mais pas effacé) ; Copier rend l'adresse seule ;
  7. les droits (un autre VA refusé) et TRUST INSTAGRAM inchangé ;
  8. les emojis Solana / Ethereum : repli unicode, créés une fois, puis servis.

Lancer depuis la racine du dépôt : python tests_menu_v2_usdc.py
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile

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
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


import liens_va as lv          # noqa: E402
import stats_va                # noqa: E402
import suivi_va                # noqa: E402
import tickets_discord as tk   # noqa: E402
import verif_discord as vd     # noqa: E402
import requests                # noqa: E402

G, U, S, ACC = tk.TWITTER_ID, "777", "5000", "9001"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="menu_v2_"))
tk.ETAT_FICHIER = TMP / "tickets.json"
tk.DATA_DIR = TMP
tk.USDC_QR_DOSSIER = TMP / "usdc_qr"
tk.USDC_EMOJIS_FICHIER = TMP / "usdc_emojis.json"
suivi_va.ETAT_FICHIER = TMP / "suivi_va.json"
tk._EN_FOND = lambda f: f()
tk._en_fond = lambda f: f()
tk._app_du_serveur = lambda g: ""            # pas d'application : repli unicode
LIEN = {"public_url": "https://getmysocial.com/candypeachyy", "numero": 95, "pseudo": "rodolpheks",
        "actif": True}
lv.lien_de = lambda gid, uid: dict(LIEN) if (str(gid), str(uid)) == (G, U) else {}
stats_va.lien = lambda gid, uid: "https://youl4b.com/mes-stats?t=cle" if str(gid) == G else ""
RANGS = [
    {"type": 1, "components": [
        {"type": 2, "style": 2, "label": "Mon adresse USDC", "custom_id": f"usdc:set:{U}"},
        {"type": 2, "style": 3, "label": "Mes stats", "custom_id": f"subs:total:{U}"},
        {"type": 2, "style": 2, "label": "Numéro", "custom_id": "numx:menu"}]},
    {"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Confirmer le VA", "custom_id": f"essai:ok:{U}"},
        {"type": 2, "style": 4, "label": "Désactiver le lien", "custom_id": f"lien:off:{U}"}]}]


class FauxDiscord:
    def __init__(self):
        self.appels = []
        self.messages = {ACC: {"id": ACC, "type": 0, "author": {"id": "bot", "bot": True},
                               "components": json.loads(json.dumps(RANGS))}}
        self.fil = [ACC]
        self.epingles = {ACC}
        self.n = 0

    def _corps(self, kw):
        if kw.get("json") is not None:
            return kw["json"]
        return json.loads((kw.get("data") or {}).get("payload_json") or "{}")

    def api(self, methode, chemin, **kw):
        corps = self._corps(kw)
        self.appels.append((methode, chemin, corps, sorted((kw.get("files") or {}).keys())))
        if methode == "GET" and "?limit=" in chemin:
            lim = int(chemin.rsplit("=", 1)[1])
            return 200, [self.messages[m] for m in reversed(self.fil)][:lim]
        if methode == "GET":
            mid = chemin.rsplit("/", 1)[1]
            return (200, self.messages[mid]) if mid in self.messages else (404, {})
        if methode == "POST" and chemin.endswith("/messages"):
            self.n += 1
            mid = f"c{self.n}"
            self.messages[mid] = {"id": mid, "type": 0, "author": {"id": "bot", "bot": True},
                                  "content": corps.get("content"), "flags": corps.get("flags", 0),
                                  "components": corps.get("components")}
            self.fil.append(mid)
            return 200, {"id": mid}
        if methode == "PUT" and "/pins/" in chemin:
            mid = chemin.rsplit("/", 1)[1]
            self.epingles.add(mid)
            return 204, {}
        if methode == "DELETE":
            mid = chemin.rsplit("/", 1)[1]
            self.fil = [m for m in self.fil if m != mid]
            self.epingles.discard(mid)
            return (204, {}) if self.messages.pop(mid, None) else (404, {})
        if methode == "PATCH" and "/webhooks/" in chemin:
            return 200, {}
        if methode == "PATCH":
            mid = chemin.rsplit("/", 1)[1]
            if mid not in self.messages:
                return 404, {"code": 10008}
            if (self.messages[mid].get("flags", 0) & tk.V2) and "content" in corps:
                return 400, {"message": "content sur un message v2"}
            for k in ("components", "content"):
                if k in corps:
                    self.messages[mid][k] = corps[k]
            return 200, {}
        return 200, {}

    def ecrits(self):
        return [a for a in self.appels if a[0] != "GET"]


def etat():
    return json.loads(tk.ETAT_FICHIER.read_text(encoding="utf-8"))


def blocs(corps):
    return corps[0]["components"]


def textes(corps):
    out = []
    for b in blocs(corps):
        if b.get("type") == 10:
            out.append(b["content"])
        if b.get("type") == 9:
            out += [x["content"] for x in b["components"]]
    return "\n".join(out)


def ids(corps):
    out = []
    for b in blocs(corps):
        if b.get("type") == 1:
            out += [x.get("custom_id") for x in b["components"]]
        if b.get("type") == 9 and b["accessory"].get("custom_id"):
            out.append(b["accessory"]["custom_id"])
    return out


def clic(cid, qui=U, roles=None, typ=3, gid=G, message=None, data=None):
    p = {"type": typ, "guild_id": gid, "channel_id": S, "token": "jeton", "application_id": "APP",
         "member": {"user": {"id": qui}, "roles": roles or [], "permissions": "0"},
         "data": dict({"custom_id": cid}, **(data or {}))}
    if message is not None:
        p["message"] = message
    return p


tk.ETAT_FICHIER.write_text(json.dumps({"tickets": {
    f"{G}:{U}": {"salon": S, "accueil": ACC, "manager": "1", "confirme": False}}}), encoding="utf-8")
d = FauxDiscord()
tk._api_reseau = d.api
vd.api = d.api

print("1. Le menu v2")
c = tk._corps_menu(G, U, RANGS)
check("un conteneur, et rien d'autre", len(c) == 1 and c[0]["type"] == 17)
check("« 📋 Ton menu », puis « Twitter VA 95 · @rodolpheks »",
      blocs(c)[0]["content"] == "## 📋 Ton menu\n-# Twitter VA 95 · @rodolpheks", blocs(c)[0])
sec_toutes = [b for b in blocs(c) if b.get("type") == 9]
# 06/11/2026 : « 📄 Ta page » (pages_va, ouverte à tous sur Twitter) se glisse
# sous « 🔗 Ton lien » — vérifiée à part, les autres sections lues sans elle
sec = [b for b in sec_toutes if not b["components"][0]["content"].startswith("**📄")]
check("📄 Ta page : juste sous « 🔗 Ton lien », « Créer » tant qu'il n'en a pas",
      len(sec_toutes) == len(sec) + 1
      and sec_toutes[1]["components"][0]["content"].startswith("**📄 Ta page**")
      and sec_toutes[1]["accessory"].get("custom_id") == f"page:new:{U}", sec_toutes[:2])
check("Ton lien : le lien en texte et un bouton-lien Ouvrir",
      "https://getmysocial.com/candypeachyy" in sec[0]["components"][0]["content"]
      and sec[0]["accessory"] == {"type": 2, "style": 5, "label": "Ouvrir", "url": LIEN["public_url"]}, sec[0])
check("Tes stats : un bouton-lien vers sa page (la clé n'est plus écrite en clair)",
      sec[1]["accessory"].get("url") == "https://youl4b.com/mes-stats?t=cle"
      and "mes-stats" not in sec[1]["components"][0]["content"], sec[1])
check("Paiement : « Pas encore d'adresse », bouton Ajouter = le 💳",
      "Pas encore d'adresse" in sec[2]["components"][0]["content"]
      and sec[2]["accessory"]["custom_id"] == f"usdc:set:{U}" and sec[2]["accessory"]["label"] == "Ajouter",
      sec[2])
check("le 💳 n'est plus dans les rangées (un custom_id par message)",
      ids(c).count(f"usdc:set:{U}") == 1 and f"subs:total:{U}" in ids(c) and f"lien:off:{U}" in ids(c), ids(c))
check("aucun texte « YouLab » (réécrit sur les serveurs TRUST)", "YouLab" not in json.dumps(c))

print("2. ramener_menu")
# 04/11/2026 : l'accueil en bas ne tient plus lieu de menu (ni page de stats,
# ni paiement) : un ticket sans menu en blocs en reçoit un, dessous
r0 = tk.ramener_menu(G, U, S)
post0 = [a for a in d.ecrits() if a[0] == "POST"]
check("accueil tout juste posé, pas encore de menu en blocs : le menu posé dessous, en v2",
      r0 == "ramene" and len(post0) == 1 and post0[0][2].get("flags") == tk.V2, (r0, d.ecrits()))
n0 = len(d.ecrits())
check("… redemandé : déjà en bas, rien de plus", tk.ramener_menu(G, U, S) == "deja" and len(d.ecrits()) == n0,
      d.ecrits()[n0:])
d.n += 1
d.messages["h1"] = {"id": "h1", "type": 0, "author": {"id": U}}
d.fil.append("h1")
r = tk.ramener_menu(G, U, S)
post = [a for a in d.ecrits() if a[0] == "POST"]
f = etat()["tickets"][f"{G}:{U}"]
check("un humain a écrit : le menu reposé EN V2 (drapeau, sans texte)",
      r == "ramene" and post and post[-1][2].get("flags") == tk.V2 and "content" not in post[-1][2]
      and post[-1][2]["components"][0]["type"] == 17, (r, post[-1:] if post else None))
check("… noté v2, avec ses rangées et son empreinte, et épinglé",
      f.get("menu_v2") == 1 and f.get("menu_rangs") and f.get("menu_empreinte") and f["menu"] in d.epingles, f)
n = len(d.ecrits())
check("redemandé tout de suite : déjà en bas, rien écrit",
      tk.ramener_menu(G, U, S) == "deja" and len(d.ecrits()) == n, d.ecrits()[n:])
# une copie TEXTE d'avant (menu de la veille), en bas
f_v2 = f["menu"]
d.messages["t1"] = {"id": "t1", "type": 0, "author": {"id": "bot", "bot": True},
                    "content": "📋 **Menu**\n🔗 <https://getmysocial.com/candypeachyy>", "components": RANGS}
d.fil.append("t1")
st = etat()
st["tickets"][f"{G}:{U}"].update(menu="t1", menu_v2=None)
tk.ETAT_FICHIER.write_text(json.dumps(st), encoding="utf-8")
n = len(d.ecrits())
r = tk.ramener_menu(G, U, S)
nouv = d.ecrits()[n:]
check("une copie texte d'avant : reposée en v2, puis retirée (jamais modifiée)",
      r == "ramene" and any(a[0] == "POST" and a[2].get("flags") == tk.V2 for a in nouv)
      and ("DELETE", f"/channels/{S}/messages/t1", {}, []) in [(a[0], a[1], a[2], a[3]) for a in nouv]
      and not any(a[0] == "PATCH" and a[1].endswith("/t1") for a in nouv), nouv)

print("3. Le ménage")
menu_id = etat()["tickets"][f"{G}:{U}"]["menu"]
bots = {"bot"}
check("la copie v2 est reconnue comme menu", tk.est_copie_du_menu(d.messages[menu_id], bots))
check("une copie texte aussi", tk.est_copie_du_menu(
    {"author": {"id": "bot"}, "type": 0, "components": RANGS, "content": "📋 **Menu**"}, bots))
carte = {"author": {"id": "bot"}, "type": 0, "flags": tk.V2,
         "components": tk._corps_carte_usdc(G, U) if suivi_va.adresse_de(G, U) else
         [{"type": 17, "components": [{"type": 10, "content": "## 💳 Paiement\n…"}]}]}
check("la carte 💳 Paiement n'en est pas une", not tk.est_copie_du_menu(carte, bots))

print("4. Le tour des liens et le miroir")
n = len(d.ecrits())
tk.rafraichir_menus(G)
check("rien n'a bougé : aucun appel", len(d.ecrits()) == n, d.ecrits()[n:])
LIEN["public_url"] = "https://getmysocial.com/neuve"
tk.rafraichir_menus(G)
p = [a for a in d.ecrits()[n:] if a[0] == "PATCH"]
check("nouvelle adresse : le menu v2 modifié sur place, sans texte",
      len(p) == 1 and "content" not in p[0][2] and "neuve" in json.dumps(p[0][2]), p)
n = len(d.ecrits())
neufs = json.loads(json.dumps(RANGS))
neufs[1]["components"][1] = {"type": 2, "style": 3, "label": "Réactiver le lien", "custom_id": f"lien:on:{U}"}
tk._api("PATCH", f"/channels/{S}/messages/{ACC}", json={"components": neufs})
m = d.messages[etat()["tickets"][f"{G}:{U}"]["menu"]]
check("l'accueil change de boutons : le menu v2 suit, en blocs",
      f"lien:on:{U}" in ids(m["components"]) and m["components"][0]["type"] == 17, ids(m["components"]))

print("5. Une réponse sur place sur le menu v2")
menu_id = etat()["tickets"][f"{G}:{U}"]["menu"]
_vrai = tk._traiter_sans_usdc
tk._traiter_sans_usdc = lambda p: {"type": 7, "data": {
    "embeds": [], "content": "📋 **Menu**\n⭐ Confirmé par <@1>.", "components": RANGS}}
rep = tk.traiter(clic(f"essai:ok:{U}", qui="1", message={"id": menu_id, "flags": tk.V2}))
tk._traiter_sans_usdc = _vrai
check("⭐ Confirmer sur le menu v2 : la réponse revient en blocs, sans texte ni encart",
      rep["type"] == 7 and set(rep["data"]) == {"components", "allowed_mentions"}
      and rep["data"]["components"][0]["type"] == 17 and "⭐ Confirmé par <@1>." in textes(rep["data"]["components"]),
      rep)

print("6. 💳 : réseau, adresse, QR, carte")
r = tk.traiter(clic(f"usdc:set:{U}"))
cids = [x["custom_id"] for b in r["data"]["components"][0]["components"] if b.get("type") == 1 for x in b["components"]]
check("💳 : un éphémère v2 « choisis ton réseau » : Solana, Ethereum",
      r["type"] == 4 and r["data"]["flags"] == 64 | tk.V2 and cids == [f"usdc:net:sol:{U}", f"usdc:net:eth:{U}"], r)
check("… icônes de repli tant que les emojis n'existent pas",
      [x["emoji"] for b in r["data"]["components"][0]["components"] if b.get("type") == 1
       for x in b["components"]] == [{"name": "🟣"}, {"name": "💎"}])
fen = tk.traiter(clic(f"usdc:net:eth:{U}"))
lab = fen["data"]["components"]
check("Ethereum : la fenêtre, adresse 0x (42 caractères) puis QR facultatif",
      fen["type"] == 9 and fen["data"]["custom_id"] == f"usdc:f2:eth:{U}"
      and lab[0]["type"] == 18 and lab[0]["component"]["min_length"] == 42 == lab[0]["component"]["max_length"]
      and lab[1]["component"]["type"] == 19 and lab[1]["component"]["required"] is False
      and lab[1]["component"]["min_values"] == 0 and len(fen["data"]["title"]) <= 45, fen)


def envoi(court, adresse, qr=None, qui=U):
    data = {"components": [{"type": 18, "component": {"type": 4, "custom_id": "adresse", "value": adresse}},
                           {"type": 18, "component": {"type": 19, "custom_id": "qr",
                                                      "values": ["555"] if qr else []}}]}
    if qr:
        data["resolved"] = {"attachments": {"555": qr}}
    return tk.traiter(clic(f"usdc:f2:{court}:{U}", qui=qui, typ=5, data=data))


n = len(d.ecrits())
r = envoi("eth", "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
check("une adresse Solana sous Ethereum : refusée, dite, rien écrit",
      r["type"] == 4 and "choisis Solana" in r["data"]["content"] and not suivi_va.adresse_de(G, U)
      and len(d.ecrits()) == n, r)
from PIL import Image  # noqa: E402
_b = io.BytesIO()
Image.new("RGB", (60, 60), (255, 255, 255)).save(_b, "JPEG")
_JPG = _b.getvalue()


class _R:
    status_code, content = 200, _JPG


_get = requests.get
requests.get = lambda url, **kw: _R()
ETH = "0x52908400098527886E0F7030069857D2E4169EE7"
n = len(d.ecrits())
r = envoi("eth", ETH, qr={"id": "555", "url": "https://cdn.discordapp.com/x.jpg?ex=1",
                          "content_type": "image/jpeg", "size": len(_JPG), "filename": "qr.jpg"})
requests.get = _get
e = suivi_va.paiement_de(G, U)
f = etat()["tickets"][f"{G}:{U}"]
nouv = d.ecrits()[n:]
post_carte = [a for a in nouv if a[0] == "POST" and a[1].endswith("/messages")]
check("Ethereum + QR : réponse différée, adresse et réseau gardés, QR enregistré (PNG)",
      r["type"] == 5 and e.get("adresse") == ETH and e.get("reseau") == "ethereum"
      and str(e.get("qr") or "").startswith("usdc_qr/") and (TMP / e["qr"]).read_bytes()[:4] == b"\x89PNG", e)
check("la carte : postée en v2 avec l'image jointe, épinglée, notée dans la fiche",
      post_carte and post_carte[0][2].get("flags") == tk.V2 and post_carte[0][3] == ["files[0]"]
      and post_carte[0][2]["attachments"][0]["filename"].startswith("qr_")
      and f.get("carte_usdc") in d.epingles, (post_carte, f.get("carte_usdc")))
ct = d.messages[f["carte_usdc"]]["components"]
check("… l'adresse entière seule dans son bloc, le QR, Modifier et Copier",
      f"```\n{ETH}\n```" in textes(ct) and any(b.get("type") == 12 for b in blocs(ct))
      and ids(ct) == [f"usdc:set:{U}", f"usdc:copie:{U}"] and "ERC-20" in textes(ct), textes(ct))
mm = d.messages[f["menu"]]["components"]
check("le menu montre le paiement : « USDC · Ethereum · `0x52…69EE7` · QR ✅ », bouton Modifier",
      "USDC · Ethereum · `0x52…9EE7` · QR ✅" in textes(mm)
      and any(b.get("type") == 9 and b["accessory"].get("label") == "Modifier" for b in blocs(mm)), textes(mm))
suite = [a for a in nouv if "/webhooks/" in a[1]]
check("le VA lit « ✅ Adresse enregistrée : USDC · Ethereum »",
      suite and "✅ Adresse enregistrée : USDC · Ethereum" in suite[-1][2]["content"], suite)
qr_avant = TMP / e["qr"]
SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
n = len(d.ecrits())
envoi("sol", SOL)
e2 = suivi_va.paiement_de(G, U)
pt = [a for a in d.ecrits()[n:] if a[0] == "PATCH" and a[1].endswith("/" + f["carte_usdc"])]
check("changée pour Solana sans QR : l'ancien QR n'est plus montré (carte sans image)",
      e2["reseau"] == "solana" and not e2.get("qr") and pt and pt[0][2].get("attachments") == [], (e2, pt))
check("… mais il n'est pas effacé, et l'adresse d'avant est gardée dans « avant »",
      qr_avant.exists() and e2["avant"][0]["adresse"] == ETH)
r = tk.traiter(clic(f"usdc:copie:{U}", qui="1", roles=[]))
check("Copier, par un autre que le VA (pas manager) : refusé", "Réservé" in r["data"]["content"])
r = tk.traiter(clic(f"usdc:copie:{U}"))
check("Copier : l'adresse SEULE, en éphémère", r["data"] == {"content": SOL, "flags": 64}, r)
n = len(d.ecrits())
r = envoi("sol", "x", qr=None)
check("une adresse vide ou fausse : refusée, l'adresse en place ne bouge pas",
      r["type"] == 4 and suivi_va.adresse_de(G, U) == SOL and len(d.ecrits()) == n)
_get = requests.get
requests.get = lambda url, **kw: _R()
r = envoi("sol", SOL, qr={"id": "555", "url": "https://cdn.discordapp.com/x.pdf", "content_type": "application/pdf",
                          "size": 10, "filename": "x.pdf"})
requests.get = _get
suite = [a for a in d.ecrits() if "/webhooks/" in a[1]][-1]
check("un QR qui n'est pas une image : l'adresse gardée, le QR refusé et dit",
      suivi_va.adresse_de(G, U) == SOL and "QR non enregistré" in suite[2]["content"], suite)

print("6b. La réponse sur place n'est pas tenue pour faite")
menu_id = etat()["tickets"][f"{G}:{U}"]["menu"]
_vrai = tk._traiter_sans_usdc
tk._traiter_sans_usdc = lambda p: {"type": 7, "data": {"content": "📋 **Menu**", "components": RANGS}}
tk.traiter(clic(f"essai:ok:{U}", qui="1", message={"id": menu_id, "flags": tk.V2}))
check("après une réponse sur place, l'empreinte est vide (Discord a pu la refuser)",
      etat()["tickets"][f"{G}:{U}"].get("menu_empreinte") == "")
n = len(d.ecrits())
tk.rafraichir_menus(G)
check("… le tour suivant réécrit le menu UNE fois, puis plus rien",
      len([a for a in d.ecrits()[n:] if a[0] == "PATCH"]) == 1
      and (tk.rafraichir_menus(G) or True) and len([a for a in d.ecrits()[n:] if a[0] == "PATCH"]) == 1,
      d.ecrits()[n:])
vieux = {"id": "vieux1", "flags": tk.V2, "components": [{"type": 17, "components": [
    {"type": 10, "content": "## 📋 Ton menu\n-# …"}]}]}
rep = tk.traiter(clic(f"essai:ok:{U}", qui="1", message=vieux))
tk._traiter_sans_usdc = _vrai
check("un ANCIEN menu v2 encore cliqué (pas celui de la fiche) : la réponse revient en blocs aussi",
      rep["type"] == 7 and "content" not in rep["data"] and rep["data"]["components"][0]["type"] == 17
      and etat()["tickets"][f"{G}:{U}"]["menu"] == menu_id, rep)

print("7. Les droits, et TRUST INSTAGRAM")
r = tk.traiter(clic(f"usdc:set:{U}", qui="888"))
check("un autre VA ne peut pas changer l'adresse", r["type"] == 4 and "Seul ce VA" in r["data"]["content"])
check("TRUST INSTAGRAM : 💳 garde l'ancienne fenêtre Solana (rien d'intercepté)",
      tk._usdc(clic(f"usdc:set:{U}", gid=tk.AGENCY_IG_ID)) is None)
r = suivi_va.poser_adresse(tk.AGENCY_IG_ID, U, "0x52908400098527886E0F7030069857D2E4169EE7")
check("TRUST INSTAGRAM : une adresse 0x dans la fenêtre Solana reçoit le message d'avant, mot pour mot",
      r["ok"] is False and r["erreur"] == "Ce n'est pas une adresse Solana valide (32 à 44 caractères, sans 0, O, I ni l).", r)
r = suivi_va.poser_adresse(tk.AGENCY_IG_ID, U, "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
check("… une adresse Solana y est gardée sans réseau noté (l'annonce de prime ne change pas)",
      r["ok"] and "reseau" not in json.loads(suivi_va.ETAT_FICHIER.read_text())["adresses"][f"{tk.AGENCY_IG_ID}:{U}"])
check("la règle d'avant reste celle d'adresse_valide sans « strict » (une adresse Tron y passe, comme avant)",
      suivi_va.adresse_valide("TJRabPrwbZy45sbavfcjinPJC18kjpRTv8")
      and not suivi_va.adresse_valide("TJRabPrwbZy45sbavfcjinPJC18kjpRTv8", strict=True))

print("8. Les emojis Solana / Ethereum")
tk._app_du_serveur = lambda g: "APP1"
tk._EMOJIS_ESSAIS.clear()
crees = []


def _api_emojis(methode, chemin, **kw):
    if chemin == "/applications/APP1/emojis" and methode == "GET":
        return 200, {"items": [{"name": "autre", "id": "1"}]}
    if chemin == "/applications/APP1/emojis" and methode == "POST":
        crees.append(kw["json"]["name"])
        return 201, {"id": f"9{len(crees)}"}
    return d.api(methode, chemin, **kw)


vd.api = _api_emojis
r = tk.traiter(dict(clic(f"usdc:set:{U}"), application_id="APP1"))
em1 = [x["emoji"] for b in r["data"]["components"][0]["components"] if b.get("type") == 1 for x in b["components"]]
# (ici le « fond » tourne tout de suite : le 2e bouton les trouve déjà)
check("premier clic : repli unicode, et les deux emojis créés en fond",
      em1[0] == {"name": "🟣"} and crees == ["usdc_solana", "usdc_ethereum"], (em1, crees))
r = tk.traiter(dict(clic(f"usdc:set:{U}"), application_id="APP1"))
em2 = [x["emoji"] for b in r["data"]["components"][0]["components"] if b.get("type") == 1 for x in b["components"]]
check("clic suivant : les emojis de l'application", em2 == [{"name": "usdc_solana", "id": "91"},
                                                            {"name": "usdc_ethereum", "id": "92"}], em2)
check("… et le menu les montre devant le réseau", "<:usdc_solana:91> Solana" in tk._paiement_court(G, U))
r = tk.traiter(dict(clic(f"usdc:set:{U}"), application_id="AUTRE_APP"))
em3 = [x["emoji"] for b in r["data"]["components"][0]["components"] if b.get("type") == 1 for x in b["components"]]
check("un clic reçu par une AUTRE application (vieux message de Siri) : le repli, jamais l'emoji d'une autre",
      em3 == [{"name": "🟣"}, {"name": "💎"}], em3)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
