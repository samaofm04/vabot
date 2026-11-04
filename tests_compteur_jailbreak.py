# -*- coding: utf-8 -*-
"""Le compteur « 🔓 VA Jailbreak : n » de MARCHE FR (04/11/2026), sans réseau :
compte le rôle Jailbreak FR de Youl4b sur toutes les pages, renomme seulement
quand le nombre change, ne touche à rien si une lecture rate, ne refait jamais
un salon supprimé. Lancer : python tests_compteur_jailbreak.py"""
import io, os, pathlib, sys
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT)); os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
from cogs import compteurjailbreak as cj   # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


BOTS = {cj.APP_REVEL: {"app_id": cj.APP_REVEL, "nom": "Wario"}, cj.APP_MEYZAH: {"app_id": cj.APP_MEYZAH, "nom": "Threads"}}
cj._bot = lambda app: BOTS.get(app)
ETAT = {"membres": [], "nom": "🔓 VA Jailbreak : 12", "panne": None, "salon_404": False, "role": "Jailbreak FR"}
APPELS = []


def http(bot, methode, chemin, **kw):
    APPELS.append((bot["nom"], methode, chemin, kw.get("json")))
    if ETAT["panne"] and ETAT["panne"] in chemin:
        return 503, {"message": "panne"}
    if chemin.endswith("/roles"):
        return 200, [{"id": "R_JB", "name": ETAT["role"]}, {"id": "R_US", "name": "Jailbreak US"}]
    if "/members?" in chemin:
        apres = chemin.split("after=")[1]
        reste = [m for m in ETAT["membres"] if int(m["user"]["id"]) > int(apres)]
        return 200, reste[:cj.PAGE]
    if chemin == f"/channels/{cj.SALON_ID}" and methode == "GET":
        return (404, {"code": 10003}) if ETAT["salon_404"] else (200, {"id": cj.SALON_ID, "name": ETAT["nom"]})
    if methode == "PATCH":
        ETAT["nom"] = kw["json"]["name"]
        return 200, {"name": ETAT["nom"]}
    return 404, {}


cj._http = http
# 2 500 membres : 14 Jailbreak FR répartis sur trois pages, des Jailbreak US à part
ETAT["membres"] = [{"user": {"id": str(1000 + i)},
                    "roles": ["R_JB"] if i % 180 == 0 else (["R_US"] if i % 7 == 0 else [])} for i in range(2500)]
attendu = sum(1 for m in ETAT["membres"] if "R_JB" in m["roles"])
check("compte le rôle Jailbreak FR sur toutes les pages (pas les US)", cj.compter() == attendu, (cj.compter(), attendu))
check("le nombre a changé : salon renommé par Meyzah", cj.mettre_a_jour() == "pose"
      and ETAT["nom"] == f"🔓 VA Jailbreak : {attendu}"
      and any(a[0] == "Threads" and a[1] == "PATCH" for a in APPELS), ETAT["nom"])
check("les membres de Youl4b sont lus par Revel", all(a[0] == "Wario" for a in APPELS if "/guilds/" in a[2]))
APPELS.clear()
check("même nombre : rien renommé (2 renommages / 10 min chez Discord)",
      cj.mettre_a_jour() == "deja" and not any(a[1] == "PATCH" for a in APPELS))
ETAT["panne"] = "/members?"
avant = ETAT["nom"]
check("membres illisibles : rien touché (jamais un faux 0)", cj.mettre_a_jour() == "rate" and ETAT["nom"] == avant)
ETAT["panne"] = None
ETAT["role"] = "Autre"
check("rôle introuvable : rien touché", cj.mettre_a_jour() == "rate" and ETAT["nom"] == avant)
ETAT["role"] = "Jailbreak FR"
ETAT["salon_404"] = True
check("salon supprimé à la main : jamais refait", cj.mettre_a_jour() == "supprime"
      and not any(a[1] == "POST" for a in APPELS))
src = (BOT / "main.py").read_text(encoding="utf-8")
check("chargé par le bot principal", '"compteurjailbreak"' in src.split("ADMIN_COGS")[0])
check("aucune commande slash (le bot principal est à 100/100)",
      "app_commands" not in (BOT / "cogs" / "compteurjailbreak.py").read_text(encoding="utf-8"))
print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
