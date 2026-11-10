"""« 📷 Mes comptes » des VA de TRUST INSTAGRAM (comptes_tickets).

Propriétaire, 08/11/2026 : comme sur Va IG, un bouton « Mes comptes » qui
donne au VA le lien pour ajouter ses comptes Instagram ; ses comptes arrivent
sous @lia sur la page Jailbreak, avec son @Discord. Ticket ET menu commun,
pas d'email, pas de maximum.

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. Le bouton : à côté de 🎬 dans le menu du ticket TRUST INSTAGRAM, dans le
     📋 menu commun quand le VA a un ticket, nulle part ailleurs ; le menu est
     redessiné une fois (BOUTONS_VERSION).
  2. Le clic du VA : sa fiche sous lia (nom = pseudo Discord = identifiant),
     son lien trust-ofm.com/mes-comptes/<jeton>, en privé ; recliquer rend le
     même lien sans doubler la fiche.
  3. Les refus : un autre VA dans un ticket qui n'est pas le sien ; un nom déjà
     porté par un autre pseudo Discord (jamais écrasé) ; hors TRUST INSTAGRAM.
  4. Un manager dans le ticket : le lien du VA, pas le sien.
  4b. Le lien suit l'id Discord : un VA renommé garde sa page, un autre qui
      reprend son ancien pseudo ne l'obtient pas (relecture du 08/11).
  4c. Pas de paie Jailbreak pour Lia ; un classeur Sheet non créable n'est
      pas retenté à chaque envoi.
  5. Le domaine laisse passer /mes-comptes/ ; la route connaît « cpt: ».
  6. Rien d'écrit dans le vrai data/.

    python tests_comptes_tickets.py
"""
from __future__ import annotations

import io
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
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


VRAIS = [BOT / "data" / n for n in ("jailbreak.json", "jb_va_liens.json", "comptes_tickets.json")]
AVANT = [f.stat().st_mtime if f.exists() else None for f in VRAIS]

import jailbreak as jb          # noqa: E402
import va_portal as vp          # noqa: E402
import tickets_discord as tk    # noqa: E402
import outils_tickets as ot     # noqa: E402
import liens_va as lv           # noqa: E402
import comptes_tickets as ct    # noqa: E402
import domaines                 # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="comptes_tickets_"))
jb.JAILBREAK_FILE = TMP / "jailbreak.json"
jb.PREV_FILE = TMP / "jailbreak.prev.json"
jb.BACKUP_DIR = TMP / "jailbreak_backups"
jb.TOMB_FILE = TMP / "jb_tombstones.json"
vp.LIENS_FILE = TMP / "jb_va_liens.json"
ct.LIAISONS_FILE = TMP / "comptes_tickets.json"

AG = tk.AGENCY_IG_ID
TW = tk.TWITTER_ID
VA, AUTRE, CHEF = "111111111111111111", "222222222222222222", "333333333333333333"
SALON_VA, SALON_AUTRE, COMMUN = "900000000000000001", "900000000000000002", "900000000000000099"
ot._tickets = lambda gid: {SALON_VA: VA, SALON_AUTRE: AUTRE} if str(gid) == AG else {}
tk._est_manager_brut = lambda gid, membre: str(((membre or {}).get("user") or {}).get("id")) == CHEF
FICHES = {f"{AG}:{VA}": {"pseudo": "abdoul_9684", "numero": 99}}
lv.lien_de = lambda gid, uid: dict(FICHES.get(f"{gid}:{uid}") or {})
lv.est_actif = lambda gid, uid: True
MEMBRES = {VA: "abdoul_9684", AUTRE: "autre_va"}
APPELS_API = []


def _api(methode, chemin, **kw):
    APPELS_API.append(chemin)
    uid = chemin.rsplit("/", 1)[-1]
    if uid in MEMBRES:
        return 200, {"user": {"id": uid, "username": MEMBRES[uid]}}
    return 404, {}


tk._api = _api


def clic(qui, nom, salon, uid_bouton=VA, gid=AG, cid=None):
    return {"type": 3, "guild_id": gid, "channel_id": salon,
            "member": {"user": {"id": qui, "username": nom}, "roles": []},
            "data": {"custom_id": cid or f"cpt:o:{uid_bouton}"}}


def bouton_lien(rep):
    rangs = ((rep or {}).get("data") or {}).get("components") or []
    return next((b.get("url") for r in rangs for b in (r.get("components") or []) if b.get("style") == 5), "")


print("1. Le bouton")
check("même préfixe et mêmes serveurs des deux côtés (bouton, clics)",
      tk.COMPTES_PREFIXE == ct.PREFIXE and tk.COMPTES_DANS_MENU == set(ct.MODELE))
check("TRUST INSTAGRAM reçoit les comptes sous Lia", ct.MODELE.get(AG) == "lia")
rangs = tk.boutons_va(VA, confirme=True, a_un_lien=True, gid=AG)
rangee = next((r["components"] for r in rangs
               if any(str(b.get("custom_id", "")).startswith("cnt:o:") for b in r["components"])), [])
check("ticket TRUST INSTAGRAM : 📷 Mes comptes à côté de 🎬",
      [b.get("custom_id") for b in rangee] == [f"cnt:o:{VA}", f"cpt:o:{VA}"]
      and rangee[1]["label"] == "Mes comptes" and rangee[1]["emoji"]["name"] == "📷", rangee)
check("au plus cinq rangées, cinq boutons chacune",
      len(rangs) <= 5 and all(len(r["components"]) <= 5 for r in rangs), [len(r["components"]) for r in rangs])
for g in (TW, tk.THREADS_ID):
    plats = [b for r in tk.boutons_va(VA, confirme=True, a_un_lien=True, gid=g) for b in r["components"]]
    check(f"pas de 📷 sur {g[-4:]}", not any(str(b.get("custom_id", "")).startswith("cpt:") for b in plats))
check("menu redessiné une fois (BOUTONS_VERSION 14)", tk.BOUTONS_VERSION >= 14)
tk._fiche = lambda gid, uid: {"confirme": True}
tk._corps_menu = lambda gid, uid, rangs, **kw: rangs
me = tk.menu_ephemere(AG, VA, avec_contenu=True)
ids = [b.get("custom_id") for r in me["data"]["components"] for b in r["components"]]
check("menu commun : 📷 avec 🎬 et 💳", f"cpt:o:{VA}" in ids and f"cnt:o:{VA}" in ids, ids)
me0 = tk.menu_ephemere(AG, VA, avec_contenu=False)
ids0 = [b.get("custom_id") for r in me0["data"]["components"] for b in r["components"]]
check("menu commun sans ticket : ni 🎬 ni 📷", not any(str(i).startswith(("cpt:", "cnt:")) for i in ids0), ids0)

print("2. Le clic du VA")
check("pas le nôtre : None", ct.traiter(clic(VA, "Abdoul_9684", SALON_VA, cid="cnt:o:1")) is None
      and ct.traiter({"type": 2}) is None)
r = ct.traiter(clic(VA, "Abdoul_9684", SALON_VA))
url = bouton_lien(r)
fiches = (jb.list_all().get("lia") or {}).get("vas") or []
check("réponse privée (éphémère) avec un bouton lien", r and r["type"] == 4 and r["data"]["flags"] == 64 and url, r)
check("lien sur trust-ofm.com/mes-comptes/<jeton>", url.startswith("https://trust-ofm.com/mes-comptes/"), url)
jeton = url.rsplit("/", 1)[-1]
rec = vp.resoudre(jeton) or {}
check("le jeton désigne la fiche lia / abdoul_9684", rec.get("identite") == "lia" and rec.get("va") == "abdoul_9684", rec)
check("fiche sous lia : nom et pseudo Discord = l'identifiant, en minuscules",
      fiches == [{"name": "abdoul_9684", "discord_username": "abdoul_9684"}], fiches)
check("le texte nomme le VA", "@abdoul_9684" in r["data"]["content"], r["data"]["content"])
r2 = ct.traiter(clic(VA, "abdoul_9684", COMMUN))
check("menu commun : le même lien, fiche pas doublée",
      bouton_lien(r2) == url and len((jb.list_all().get("lia") or {}).get("vas") or []) == 1, (bouton_lien(r2), url))
check("le portail accepte la fiche (elle est vivante)", vp.resoudre(jeton) is not None)

print("3. Les refus")
r3 = ct.traiter(clic(AUTRE, "autre_va", SALON_VA))
check("un autre VA dans un ticket qui n'est pas le sien : refusé",
      r3["data"]["content"] == ot.TEXTE_PAS_A_TOI and not bouton_lien(r3), r3)
jb.add_va("lia", "pris", discord_username="quelquun")
r4 = ct.traiter(clic(AUTRE, "Pris", SALON_AUTRE))
f_pris = next(v for v in jb.list_all()["lia"]["vas"] if v["name"] == "pris")
check("nom déjà porté par un autre pseudo Discord : refusé, rien écrasé",
      "déjà utilisé" in r4["data"]["content"] and not bouton_lien(r4)
      and f_pris["discord_username"] == "quelquun", (r4, f_pris))
jb.add_va("lia", "sans_pseudo")
FICHES[f"{AG}:{AUTRE}"] = {"pseudo": "sans_pseudo"}
r5 = ct.traiter(clic(AUTRE, "sans_pseudo", SALON_AUTRE))
f_sp = next(v for v in jb.list_all()["lia"]["vas"] if v["name"] == "sans_pseudo")
check("fiche du même nom sans pseudo : reliée à ce VA, lien donné",
      bouton_lien(r5) and f_sp["discord_username"] == "sans_pseudo", (r5, f_sp))
r6 = ct.traiter(clic(VA, "abdoul_9684", SALON_VA, gid=TW))
check("hors TRUST INSTAGRAM : refusé", r6 and not bouton_lien(r6), r6)

print("4. Un manager dans le ticket")
r7 = ct.traiter(clic(CHEF, "le_chef", SALON_VA))
check("manager : le lien DU VA (même jeton), pas une fiche à son nom",
      bouton_lien(r7) == url and not any(v["name"] == "le_chef" for v in jb.list_all()["lia"]["vas"])
      and "@abdoul_9684" in r7["data"]["content"], r7)
# un VA pas encore lié : le manager prend son identifiant ACTUEL chez Discord,
# jamais le pseudo figé de sa fiche de lien
NOUVEAU, SALON_NOUVEAU = "444444444444444444", "900000000000000004"
ot._tickets = lambda gid: ({SALON_VA: VA, SALON_AUTRE: AUTRE, SALON_NOUVEAU: NOUVEAU}
                           if str(gid) == AG else {})
FICHES[f"{AG}:{NOUVEAU}"] = {"pseudo": "pseudo_fige"}
MEMBRES[NOUVEAU] = "nouveau_va"
r8 = ct.traiter(clic(CHEF, "le_chef", SALON_NOUVEAU))
noms = {v["name"] for v in jb.list_all()["lia"]["vas"]}
check("manager, VA pas encore lié : sa fiche à son identifiant actuel (pas le pseudo figé)",
      bouton_lien(r8) and "nouveau_va" in noms and "pseudo_fige" not in noms, (r8, noms))
r9 = ct.traiter(clic(NOUVEAU, "nouveau_va", SALON_NOUVEAU))
check("… et le VA reçoit ensuite exactement le même lien", bouton_lien(r9) == bouton_lien(r8))
del MEMBRES[NOUVEAU]
SANS, SALON_SANS = "555555555555555555", "900000000000000005"
ot._tickets = lambda gid: ({SALON_VA: VA, SALON_AUTRE: AUTRE, SALON_NOUVEAU: NOUVEAU, SALON_SANS: SANS}
                           if str(gid) == AG else {})
r10 = ct.traiter(clic(CHEF, "le_chef", SALON_SANS))
check("manager, Discord muet sur un VA pas encore lié : rien créé, « réessaie »",
      not bouton_lien(r10) and r10["data"]["content"] == ct.TEXTE_PANNE, r10)

print("4b. Le lien suit l'id Discord, pas le pseudo")
r11 = ct.traiter(clic(VA, "abdoul_renomme", SALON_VA))
check("VA renommé chez Discord : il garde SA page (même lien, même fiche)",
      bouton_lien(r11) == url and "@abdoul_9684" in r11["data"]["content"]
      and "abdoul_renomme" not in {v["name"] for v in jb.list_all()["lia"]["vas"]}, r11)
VOLEUR, SALON_VOLEUR = "666666666666666666", "900000000000000006"
ot._tickets = lambda gid: ({SALON_VA: VA, SALON_AUTRE: AUTRE, SALON_NOUVEAU: NOUVEAU, SALON_SANS: SANS,
                            SALON_VOLEUR: VOLEUR} if str(gid) == AG else {})
r12 = ct.traiter(clic(VOLEUR, "abdoul_9684", SALON_VOLEUR))
check("un autre VA qui reprend l'ancien pseudo : refusé, il n'a pas la page",
      not bouton_lien(r12) and "déjà utilisé" in r12["data"]["content"], r12)
import json as _json  # noqa: E402
liaisons = _json.loads(ct.LIAISONS_FILE.read_text())
check("liaisons gardées par id Discord, jeton du portail",
      liaisons["lia"][VA] == url.rsplit("/", 1)[-1] and VOLEUR not in liaisons["lia"], liaisons)
# la page fermée sur le site (revoquer) : un nouveau lien, lié au même id
vp.revoquer("lia", "abdoul_9684")
r13 = ct.traiter(clic(VA, "abdoul_9684", SALON_VA))
check("lien fermé sur le site : un nouveau, sur la même fiche",
      bouton_lien(r13) and bouton_lien(r13) != url and "@abdoul_9684" in r13["data"]["content"]
      and len([v for v in jb.list_all()["lia"]["vas"] if v["name"] == "abdoul_9684"]) == 1, r13)
NEUF, SALON_NEUF = "777777777777777777", "900000000000000007"
ot._tickets = lambda gid: ({SALON_VA: VA, SALON_AUTRE: AUTRE, SALON_NEUF: NEUF} if str(gid) == AG else {})
_vrai_creer = vp.creer_lien
vp.creer_lien = lambda model, nom: "jeton_jamais_enregistre_xxxxxxxx"
r14 = ct.traiter(clic(NEUF, "tout_neuf", SALON_NEUF))
vp.creer_lien = _vrai_creer
check("jeton annoncé mais pas enregistré : pas de lien mort, « réessaie »",
      not bouton_lien(r14) and r14["data"]["content"] == ct.TEXTE_PANNE, r14)

print("4c. Paie et Sheet")
import jb_objectifs as ob  # noqa: E402
check("Lia : pas de paie Jailbreak ; Jessye si",
      not ob.paie_active("lia") and not ob.paie_active(" Lia ") and ob.paie_active("jessye"))
# 10/11/2026 : la page des VA des models FR (You FR, 📷 Ajouter mes comptes)
# tait aussi la paie (« masque-la ») ; le dashboard la garde.
import bangers as _bgP  # noqa: E402
check("models FR : la page du VA ne montre pas la paie (les six, casse ignorée)",
      len(_bgP.MODELS_FR) == 6 and not any(ob.paie_active(m) for m in _bgP.MODELS_FR)
      and not ob.paie_active(" Julia "))
import sheets_sync as ss  # noqa: E402


class _GcRefus:
    n_create = 0

    def open(self, titre):
        raise LookupError(titre)

    def create(self, titre, folder_id=None):
        _GcRefus.n_create += 1
        raise RuntimeError("APIError: [403]: The user's Drive storage quota has been exceeded.")


_vrai_save = ss.save_config
ss.save_config = lambda cfg: None
_e1 = _e2 = ""
try:
    ss._ensure_identity_sheet(_GcRefus(), "lia", {"sheets": {}})
except Exception as e:                                       # noqa: BLE001
    _e1 = str(e)
try:
    ss._ensure_identity_sheet(_GcRefus(), "lia", {"sheets": {}})
except Exception as e:                                       # noqa: BLE001
    _e2 = str(e)
ss.save_config = _vrai_save
ss._CREATION_RATEE.pop("lia", None)
check("Sheet : création refusée une fois, pas retentée au prochain envoi, et dit pourquoi",
      _GcRefus.n_create == 1 and "quota" in _e1 and "crée-le dans le dossier partagé" in _e2, (_e1, _e2))

print("5. Domaine et route")
check("trust-ofm.com sert /mes-comptes/<jeton> et ses sous-pages",
      domaines.chemin_trust("/mes-comptes/abc") and domaines.chemin_trust("/mes-comptes/abc/ajouter")
      and not domaines.chemin_trust("/mes-comptes"))
src = (BOT / "web_upload.py").read_text(encoding="utf-8")
check("la route des interactions passe « cpt: » à comptes_tickets",
      'startswith("cpt:")' in src and "import comptes_tickets as _cpt" in src)

print("6. Isolation")
check("rien écrit dans le vrai data/", [f.stat().st_mtime if f.exists() else None for f in VRAIS] == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for x in KO:
        print("  - " + x)
print("=" * 70)
sys.exit(1 if KO else 0)
