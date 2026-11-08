"""tests_entretien_ouvert.py — Entretien sans vérification (entretien_ouvert).
Discord simulé, état temporaire : rien n'est écrit dans data/, rien ne part.

    python tests_entretien_ouvert.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import entretien_ouvert as eo  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="eo_"))
eo.FICHIER = TMP / "entretien_ouvert.json"
eo.time.sleep = lambda s: None
OK, KO = [], []
G, BOT, V, A, MANAGER = eo.GID, "1552153790701117480", "1552167021037490306", "1552170116685504515", "1552167022324879422"
FILS = 1 << 35


def check(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  ok  " if cond else "  KO  ") + nom + ("" if cond else f"  — {detail}"))


def ow(i, allow=0, deny=0, typ=0):
    return {"id": i, "type": typ, "allow": str(allow), "deny": str(deny)}


def salons():
    return [
        {"id": "1552159108898103347", "type": 0, "permission_overwrites": []},
        {"id": "1552167029253869610", "type": 0, "permission_overwrites": []},
        {"id": "1552170122288963648", "type": 0, "permission_overwrites": []},
        {"id": "1552152471281860611", "type": 0, "permission_overwrites": [
            ow(eo.ROLE_BOT, 1024), ow(MANAGER, 1024, 2048), ow(BOT, 1024, typ=1), ow(G, 0, 3072),
            ow("479005370438778891", 1024, 2048, 1)]},
        {"id": "1552167025097576478", "type": 0, "permission_overwrites": [
            ow(eo.ROLE_BOT, 1024), ow(V, 0, 3072), ow(G, 1024, 2048 | FILS)]},
        {"id": eo.EN_ATTENTE, "type": 0, "permission_overwrites": []},
        {"id": "1560163540831182941", "type": 0, "permission_overwrites": [
            ow(A, 1024, 2048), ow(V, 0, 3072), ow(G, 0, 3072)]},
        {"id": "1552152471281860612", "type": 2, "permission_overwrites": [
            ow(A, 1024 | (1 << 20) | (1 << 21)), ow(V, 0, 1024), ow(G, 0, 3072)]},
    ]


class Discord:
    def __init__(self):
        self.ecritures = []
        self.refus = set()
        self.refus_fils = True
        self.salons = salons()

    def api(self, methode, chemin, **kw):
        if methode == "GET" and chemin == f"/guilds/{G}/channels":
            return 200, self.salons
        if methode == "GET" and chemin == f"/guilds/{G}/roles":
            return 200, [{"id": G, "permissions": str(1 << 20 | 1 << 21)},
                         {"id": eo.ROLE_BOT, "permissions": str(sum(1 << b for b in (0, 4, 5, 10, 11, 13, 14, 15, 16, 17, 28)))}]
        if methode == "GET" and chemin == f"/guilds/{G}/members/{BOT}":
            return 200, {"roles": [eo.ROLE_BOT]}
        if methode == "GET" and chemin.startswith(f"/guilds/{G}/members?"):
            return 200, [{"user": {"id": "1"}, "roles": [V]}, {"user": {"id": "2"}, "roles": []},
                         {"user": {"id": "3", "bot": True}, "roles": []}, {"user": {"id": "4"}, "roles": [A]}]
        if methode == "GET" and "/messages/" in chemin:
            return 200, {"embeds": [{"type": "rich", "title": "🎁 Deuxième parrainage",
                                     "description": "x\n📷 Instagram : **en construction**.", "color": 1}]}
        self.ecritures.append((methode, chemin, kw.get("json")))
        if chemin in self.refus:
            return 500, {}
        if methode == "PUT" and "/permissions/" in chemin and self.refus_fils:
            j = kw["json"]
            if (int(j["allow"]) | int(j["deny"])) & FILS:
                return 403, {}
        return (204 if methode in ("PUT", "DELETE") else 200), {}


D = Discord()
sys.modules["verif_discord"] = types.SimpleNamespace(
    api=lambda m, c, **k: D.api(m, c, **k), bot_du_serveur=lambda gid=None: {"app_id": BOT},
    serveur=lambda gid=None: {"role_verifie": V, "role_attente": A}, sur_serveur=None)
import journal_primes  # noqa: E402,F401  (son _permissions_du_bot passe par verif_discord simulé)
journal_primes._api = lambda m, c, **k: D.api(m, c, **k)

try:
    print("entretien_ouvert")
    D.refus = {"/channels/1552167029253869610"}
    r = eo.menage()
    supp = [c for m, c, _ in D.ecritures if m == "DELETE" and c.count("/") == 2]
    check("supprimés : 🔗・mon-lien-invitation, ✅┃entrées, 🚩┃suspicions — et rien d'autre",
          sorted(supp) == sorted("/channels/" + s for s in eo.A_SUPPRIMER), supp)
    check("un refus est dit et noté, pas oublié", r["supprimer:1552167029253869610"] == "HTTP 500"
          and "supprimer:1552167029253869610" in eo._etat()["echecs"], r)
    puts = {c: j for m, c, j in D.ecritures if m == "PUT"}
    e = puts.get(f"/channels/1552152471281860611/permissions/{G}")
    check("✅・membres-vérifiés : @everyone sans la vue", e and int(e["deny"]) & 1024, e)
    dels = [c for m, c, _ in D.ecritures if m == "DELETE" and "/permissions/" in c]
    check("✅・membres-vérifiés : managers et membre nommé n'y voient plus, le bot garde sa vue",
          sorted(dels) == sorted([f"/channels/1552152471281860611/permissions/{MANAGER}",
                                  "/channels/1552152471281860611/permissions/479005370438778891"]), dels)
    e = puts.get(f"/channels/1552167025097576478/permissions/{G}")
    check("🔐・vérification : caché ; refusé avec les fils, repassé sans eux (403)",
          e and int(e["deny"]) & 1024 and not int(e["allow"]) & 1024 and not int(e["deny"]) & FILS
          and r["cacher:1552167025097576478"] == "ok", (e, r))
    ren = [j for m, c, j in D.ecritures if m == "PATCH" and c == f"/channels/{eo.EN_ATTENTE}"]
    check("⏳┃en-attente renommé 🎙️┃candidat-en-vocal", ren and ren[0]["name"] == "🎙️┃candidat-en-vocal", ren)
    a = puts.get(f"/channels/1560163540831182941/permissions/{V}")
    v = puts.get(f"/channels/1552152471281860612/permissions/{V}")
    check("annonces et vocal : ✅ Vérifié prend les droits de ⏳ En attente",
          a == {"type": 0, "allow": "1024", "deny": "2048"}
          and v == {"type": 0, "allow": str(1024 | 1 << 20 | 1 << 21), "deny": "0"}, (a, v))
    ig = [j for m, c, j in D.ecritures if m == "PATCH" and "/messages/" in c]
    check("Instagram : « en construction » devient le salon 📷・instagram",
          ig and ig[0]["embeds"][0]["description"] == "x\n📷 Instagram : <#1552159912849580136>", ig)

    n = len(D.ecritures)
    D.refus = set()
    eo.menage()
    refait = D.ecritures[n:]
    check("au démarrage suivant : seule l'étape refusée est refaite",
          refait == [("DELETE", "/channels/1552167029253869610", None)], refait)

    D.ecritures.clear()
    b = eo.verifier_tous()
    roles = [c for m, c, _ in D.ecritures if m == "PUT"]
    check("✅ Vérifié donné à ceux qui ne l'ont pas, bots exceptés",
          sorted(roles) == [f"/guilds/{G}/members/2/roles/{V}", f"/guilds/{G}/members/4/roles/{V}"]
          and b["donnes"] == 2, roles)

    # le vocal ouvert à la main : l'étape se tient pour faite, sans écrire
    for f in TMP.iterdir():
        f.unlink()
    D.ecritures.clear()
    for c in D.salons:
        if c["id"] == "1552152471281860612":
            c["permission_overwrites"] = [o for o in c["permission_overwrites"] if o["id"] != V] + [ow(V, 1024 | 1 << 20)]
    r = eo.menage()
    check("vocal déjà ouvert à la main : étape faite, aucun PUT dessus",
          r["ouvrir:1552152471281860612"] == "ok"
          and not any(c == f"/channels/1552152471281860612/permissions/{V}" for m, c, _ in D.ecritures), r)

    src = (ICI / "web_upload.py").read_text(encoding="utf-8")
    check("web_upload : démarré sur la machine de production seulement, surveillé",
          '_machine_proprietaire("entretien-ouvert")' in src and "_eo_boot.demarrer()" in src
          and '"entretien_ouvert": ("entretien-ouvert"' in src)
    import importlib.util
    spec = importlib.util.spec_from_file_location("verif_discord_vrai", ICI / "verif_discord.py")
    vrai = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vrai)
    c = vrai.serveur(vrai.GUILD_ID)
    check("verif_discord : plus de ✅┃entrées ni de 🚩┃suspicions pour Entretien, Peach garde son salon",
          c["salon_entrees"] == "" and c["salon_suspicions"] == "" and c["salon_attente"] == vrai.SALON_ATTENTE
          and vrai.serveur(vrai.TWITTER_ID)["salon_entrees"], c)
    check("écritures par safe_json seulement",
          "write_text" not in (ICI / "entretien_ouvert.py").read_text(encoding="utf-8"))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{len(OK)} ok, {len(KO)} échec(s)")
sys.exit(1 if KO else 0)
