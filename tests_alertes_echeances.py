# -*- coding: utf-8 -*-
"""tests_alertes_echeances.py — banc d'essai des alertes staff (Telegram).

Lancer :  python tests_alertes_echeances.py

Autonome : data/ TEMPORAIRE, faux envoi Telegram qui ENREGISTRE ce qui
partirait, faux bots Discord. AUCUN reseau, aucune vraie donnee touchee.

Verifie, chaque fois avec un etat simule :
  - cookie GetMySocial : rien a J-17, une alerte a J-7, une a J-1, une echue,
    jamais deux fois le meme palier, recolle = paliers remis a zero, et la
    valeur du cookie nulle part ;
  - serveur Spam : rien a 449, une alerte a 450, pas de rearmement a 445,
    rearme a 440, le rythme calcule depuis le releve de l'audit ;
  - categories de Va IG : alerte a 48, rearme a 45, categorie supprimee ;
  - le coffre Outlook n'est PAS surveille ici (numgen le dit deja au staff) ;
  - rien la nuit (garde pour 9 h), un envoi refuse se retente ;
  - AUCUN doublon apres redemarrage (module recharge, meme fichier d'etat) ;
  - le cog : arme seulement avec VA_MACHINE_PROD=1, zero commande slash,
    serveur cherche chez le bot qui y est ; main.py le charge sur le bot admin.
"""
import ast
import asyncio
import base64
import importlib
import json
import os
import pathlib
import sys
import tempfile
import types
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="alertes_test_"))

import alertes_echeances as ae

ETAT = _TMP / "alertes_echeances.json"
ae.FICHIER = ETAT

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("  OK   " if cond else "  ECHEC ") + label + ("" if cond else f"  -> {detail}"))


def ts(s):
    """« 2026-10-31 18:30 » en UTC → epoch."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


EXP = int(ts("2026-11-07 18:25"))           # l'échéance réelle du cookie
COOKIE = "authToken=" + ".".join([
    base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("="),
    base64.urlsafe_b64encode(json.dumps({"exp": EXP}).encode()).decode().rstrip("="),
    "SECRETSIGNATUREQUIDOITRESTERCACHEE"])


class Telegram:
    def __init__(self, ok=True):
        self.ok, self.envois = ok, []

    def __call__(self, texte):
        self.envois.append(texte)
        return {"ok": self.ok, "error": "" if self.ok else "Bad Request: chat not found"}


def hors(exp=None):
    return {"gms_exp": exp, "avertissements": []}


def spam(n):
    return {ae.SERVEUR_SPAM: {"nom": "Spam", "salons": n, "categories": []}}


def vaig(cats):
    return {ae.VA_IG: {"nom": "Va IG", "salons": 300,
                       "categories": [{"id": i, "nom": nom, "salons": n} for i, nom, n in cats]}}


def reset():
    # la copie .prev aussi : safe_json.load la reprend quand le fichier manque
    # (c'est voulu en production : un état perdu ne fait rien repartir)
    for f in (ETAT, ETAT.with_suffix(".json.prev")):
        if f.exists():
            f.unlink()


def tour(serveurs=None, exp=None, quand="2026-10-21 12:00", tg=None):
    tg = tg or Telegram()
    b = ae.tour(serveurs or {}, maintenant=ts(quand), envoyer=tg, fichier=ETAT,
                hors_discord=hors(exp))
    return b, tg


# ---- cookie GetMySocial -------------------------------------------------------

def test_gms():
    print("Cookie GetMySocial")
    reset()
    b, tg = tour(exp=EXP, quand="2026-10-21 12:00")
    check("J-17 : rien", not tg.envois, tg.envois)
    b, tg = tour(exp=EXP, quand="2026-10-31 18:30")
    check("J-7 : une alerte", len(tg.envois) == 1 and b["envoyees"] == [f"gms:{EXP}:7"], b)
    t7 = tg.envois[0] if tg.envois else ""
    check("J-7 : « dans 7 jours », date et heure de Paris",
          "fin dans 7 jours" in t7 and "07/11 à 19:25" in t7, t7)
    check("J-7 : dit ce que coûte la panne et où recoller",
          "50/50 Seren" in t7 and "Twitter et Threads" in t7 and "?tab=sgms" in t7, t7)
    b, tg = tour(exp=EXP, quand="2026-11-02 12:00")
    check("entre J-7 et J-1 : rien de plus", not tg.envois, tg.envois)
    b, tg = tour(exp=EXP, quand="2026-11-06 18:30")
    check("J-1 : une alerte", len(tg.envois) == 1 and b["envoyees"] == [f"gms:{EXP}:1"], b)
    check("J-1 : en heures", "fin dans 24 h" in (tg.envois or [""])[0], tg.envois)
    b, tg = tour(exp=EXP, quand="2026-11-06 20:00")
    check("J-1 : une seule fois", not tg.envois, tg.envois)
    b, tg = tour(exp=EXP, quand="2026-11-08 10:00")
    check("échu : une alerte", len(tg.envois) == 1 and "échu" in tg.envois[0], tg.envois)
    b, tg = tour(exp=EXP, quand="2026-11-08 12:00")
    check("échu : une seule fois", not tg.envois, tg.envois)
    neuf = EXP + 30 * 86400
    b, tg = tour(exp=neuf, quand="2026-11-08 13:00")
    etat = ae.charger(ETAT)
    check("recollé : rien à envoyer, anciens paliers effacés",
          not tg.envois and not [k for k in etat["envoyees"] if k.startswith("gms:")], etat["envoyees"])
    b, tg = tour(exp=neuf, quand="2026-11-30 18:30")
    check("recollé : son propre J-7 repart", len(tg.envois) == 1 and f"gms:{neuf}:7" in b["envoyees"], b)

    reset()
    b, tg = tour(exp=EXP, quand="2026-11-07 09:00")
    check("déployé à J-0,4 : directement J-1, pas un J-7 en retard",
          b["envoyees"] == [f"gms:{EXP}:1"], b)

    # la vraie lecture du cookie : l'échéance sort, la valeur jamais
    import gms
    gms.CONFIG_FILE = _TMP / "gms_config.json"
    gms.CONFIG_FILE.write_text(json.dumps({"session_cookie": COOKIE}), encoding="utf-8")
    m = ae.mesurer_hors_discord()
    check("mesure : exp lue dans le jeton", m["gms_exp"] == EXP, m)
    reset()
    tg = Telegram()
    ae.tour({}, maintenant=ts("2026-10-31 18:30"), envoyer=tg, fichier=ETAT)
    sortie = " ".join(tg.envois) + ETAT.read_text(encoding="utf-8")
    check("le cookie n'est ni dans l'alerte ni dans l'état",
          tg.envois and "SECRETSIGNATURE" not in sortie and COOKIE.split(".")[1] not in sortie, sortie[:300])
    gms.CONFIG_FILE.write_text("{}", encoding="utf-8")
    m = ae.mesurer_hors_discord()
    check("sans cookie : pas d'alerte, mais c'est dit", m["gms_exp"] is None
          and "cookie GetMySocial absent" in m["avertissements"], m)


# ---- serveur Spam --------------------------------------------------------------

def test_serveur():
    print("Serveur Spam (500 salons)")
    reset()
    b, tg = tour(spam(381))
    check("381 : rien", not tg.envois, tg.envois)
    b, tg = tour(spam(449))
    check("449 : rien", not tg.envois, tg.envois)
    b, tg = tour(spam(450), quand="2026-11-24 12:00")
    t = (tg.envois or [""])[0]
    check("450 : une alerte", len(tg.envois) == 1 and b["envoyees"] == [f"salons:{ae.SERVEUR_SPAM}"], b)
    check("450 : nom, compte, reste", "« Spam » : 450 salons sur 500" in t and "Il en reste 50" in t, t)
    check("450 : rythme depuis le relevé de l'audit (381 le 20/10)",
          "Au rythme des 35 derniers jours (+14 salons par semaine), plein vers le 19/12" in t, t)
    b, tg = tour(spam(458), quand="2026-11-25 12:00")
    check("458 : pas une deuxième", not tg.envois, tg.envois)
    b, tg = tour({}, quand="2026-11-25 13:00")
    check("serveur pas vu : rien, et l'alerte reste notée",
          not tg.envois and f"salons:{ae.SERVEUR_SPAM}" in ae.charger(ETAT)["envoyees"], b)
    b, tg = tour(spam(445), quand="2026-11-26 12:00")
    b, tg = tour(spam(451), quand="2026-11-26 13:00")
    check("redescendu à 445 puis 451 : pas rearmée (oscillation)", not tg.envois, tg.envois)
    b, tg = tour(spam(440), quand="2026-11-27 12:00")
    check("440 : rearmée", f"salons:{ae.SERVEUR_SPAM}" in b["rearmees"], b)
    b, tg = tour(spam(452), quand="2026-11-28 12:00")
    check("remonté à 452 : nouvelle alerte", len(tg.envois) == 1, tg.envois)
    h = ae.charger(ETAT)["historique"][ae.SERVEUR_SPAM]
    check("historique : un relevé par jour", [p[0] for p in h] == sorted({p[0] for p in h}), h)


# ---- catégories de Va IG ---------------------------------------------------------

def test_categories():
    print("Catégories de Va IG (50 salons)")
    reset()
    b, tg = tour(vaig([("1", "👤 Amelia", 44), ("2", "👤 Lola", 12)]))
    check("Amelia 44 : rien", not tg.envois, tg.envois)
    b, tg = tour(vaig([("1", "👤 Amelia", 48), ("2", "👤 Lola", 12)]))
    t = (tg.envois or [""])[0]
    check("Amelia 48 : une alerte", len(tg.envois) == 1 and b["envoyees"] == [f"categorie:{ae.VA_IG}:1"], b)
    check("texte : serveur, catégorie, compte", "Va IG : catégorie « 👤 Amelia » à 48 salons sur 50" in t, t)
    b, tg = tour(vaig([("1", "👤 Amelia", 50), ("2", "👤 Lola", 48)]))
    check("Amelia 50 : pas une deuxième ; Lola 48 : la sienne",
          b["envoyees"] == [f"categorie:{ae.VA_IG}:2"] and "👤 Lola" in tg.envois[0], b)
    b, tg = tour(vaig([("1", "👤 Amelia", 45), ("2", "👤 Lola", 48)]))
    check("Amelia 45 : rearmée", b["rearmees"] == [f"categorie:{ae.VA_IG}:1"] and not tg.envois, b)
    b, tg = tour(vaig([("1", "👤 Amelia", 45)]))
    check("Lola supprimée : son alerte s'efface", b["rearmees"] == [f"categorie:{ae.VA_IG}:2"], b)
    b, tg = tour(spam(300))
    check("Va IG pas vu ce tour-ci : rien n'est rearmé", not b["rearmees"], b)
    d = ae.charger(ETAT)["dernier_tour"]
    check("dernier tour : la plus remplie se lit", d["serveurs"] == {ae.SERVEUR_SPAM: {
        "nom": "Spam", "salons": 300, "categories_max": []}}, d)
    b, tg = tour(vaig([("1", "👤 Amelia", 44), ("3", "Accueil", 7)]))
    d = ae.charger(ETAT)["dernier_tour"]["serveurs"][ae.VA_IG]
    check("dernier tour : Amelia 44 en tête", d["categories_max"][0] == ["👤 Amelia", 44], d)


# ---- nuit, échec d'envoi, redémarrage -------------------------------------------------

def test_nuit_echec_redemarrage():
    print("Nuit, envoi refusé, redémarrage")
    reset()
    b, tg = tour(spam(460), quand="2026-11-24 22:30")     # 23 h 30 à Paris
    check("la nuit : gardée, rien d'envoyé, rien de noté",
          not tg.envois and b["gardees"] and not ae.charger(ETAT)["envoyees"], b)
    b, tg = tour(spam(460), quand="2026-11-25 08:05")     # 9 h 05 à Paris
    check("le matin : partie", len(tg.envois) == 1, tg.envois)

    reset()
    refus = Telegram(ok=False)
    b, _ = tour({**spam(460), **vaig([("1", "👤 Amelia", 48)])}, tg=refus)
    check("envoi refusé : rien de noté, l'erreur est gardée",
          len(refus.envois) == 2 and not ae.charger(ETAT)["envoyees"] and len(b["erreurs"]) == 2, b)
    b, tg = tour({**spam(460), **vaig([("1", "👤 Amelia", 48)])})
    check("tour suivant : les deux repartent", len(tg.envois) == 2, tg.envois)

    # redémarrage : le module est rechargé (comme un nouveau processus), même data/
    reset()
    b, tg = tour({**spam(470), **vaig([("1", "👤 Amelia", 49)])}, exp=EXP, quand="2026-11-06 18:30")
    check("avant redémarrage : 3 alertes (cookie, Spam, Amelia)", len(tg.envois) == 3, tg.envois)
    importlib.reload(ae)
    ae.FICHIER = ETAT
    for quand in ("2026-11-06 18:45", "2026-11-06 19:00"):
        b, tg = tour({**spam(471), **vaig([("1", "👤 Amelia", 49)])}, exp=EXP, quand=quand)
        check(f"après redémarrage ({quand}) : aucun doublon", not tg.envois, tg.envois)

    # fichier d'état perdu (coupure en pleine écriture) : la copie .prev suffit
    ETAT.unlink()
    b, tg = tour({**spam(471), **vaig([("1", "👤 Amelia", 49)])}, exp=EXP, quand="2026-11-06 19:15")
    check("état effacé, .prev présent : aucun doublon", not tg.envois, tg.envois)

    # un plantage APRÈS le premier envoi : il est déjà noté
    reset()

    class Plante(Telegram):
        def __call__(self, texte):
            if self.envois:
                raise KeyboardInterrupt
            return super().__call__(texte)
    p = Plante()
    try:
        tour({**spam(470), **vaig([("1", "👤 Amelia", 49)])}, tg=p)
    except KeyboardInterrupt:
        pass
    check("plantage au 2e envoi : le 1er est déjà noté", len(ae.charger(ETAT)["envoyees"]) == 1,
          ae.charger(ETAT)["envoyees"])


# ---- envoi Telegram : le canal des alertes SFS ------------------------------------------

def test_canal():
    print("Canal Telegram")
    vu = []
    faux = types.ModuleType("web_upload")
    faux._sfs_alertes_cfg = lambda: {"telegram": {"chat_id": "-1001234567890"}}
    faux._telegram_envoyer = lambda chat, texte: vu.append((chat, texte)) or {"ok": True}
    sys.modules["web_upload"] = faux
    r = ae.envoyer_telegram("x")
    check("groupe des alertes SFS, par _telegram_envoyer", r["ok"] and vu == [("-1001234567890", "x")], vu)
    faux._sfs_alertes_cfg = lambda: {}
    r = ae.envoyer_telegram("x")
    check("groupe non réglé : refus dit, rien d'envoyé", not r["ok"] and "aucun groupe" in r["error"]
          and len(vu) == 1, r)
    src = pathlib.Path(ae.__file__).read_text(encoding="utf-8")
    check("jamais getUpdates", "getUpdates" not in src.replace("getUpdates appartient", ""))
    # numgen.alerter_staff (« outlook:vide ») le dit déjà dans le debrief-day du
    # Spam : d'ici, le même événement partirait deux fois, sur deux canaux
    check("coffre Outlook : pas surveillé ici (numgen s'en charge)",
          "import outlook_comptes" not in src and "outlook:vide\"" not in src.replace("« outlook:vide »", ""))
    del sys.modules["web_upload"]


# ---- le cog --------------------------------------------------------------------------------

class G:
    def __init__(self, gid, name, cats, autres=0):
        self.id, self.name, self.unavailable = gid, name, False
        self.categories = [types.SimpleNamespace(id=i, name=n, channels=[object()] * k)
                           for i, n, k in cats]
        self.channels = list(self.categories) + [object()] * (sum(k for _, _, k in cats) + autres)


class B:
    def __init__(self, guildes):
        self.g = {g.id: g for g in guildes}

    def get_guild(self, gid):
        return self.g.get(gid)

    async def wait_until_ready(self):
        return None


def test_cog():
    print("Cog")
    import cogs.alertes as ca
    check("zéro commande slash", not ca.Alertes.__cog_app_commands__, ca.Alertes.__cog_app_commands__)

    spam_g = G(int(ae.SERVEUR_SPAM), "Spam", [(1, "VA 1", 3)], autres=10)
    vaig_g = G(int(ae.VA_IG), "Va IG", [(7, "👤 Amelia", 44), (8, "👤 Lola", 2)])
    admin, principal = B([vaig_g]), B([spam_g, vaig_g])
    faux = types.ModuleType("web_upload")
    faux._BOT_REF, faux._BOT_ADMIN_REF = principal, admin
    appels = []

    def porte(quoi):
        appels.append(quoi)
        return os.environ.get("VA_MACHINE_PROD") == "1"
    faux._machine_proprietaire = porte
    sys.modules["web_upload"] = faux
    sauve = os.environ.pop("VA_MACHINE_PROD", None)

    async def scenario():
        c = ca.Alertes(admin)
        arme_mac = c.boucle.is_running()
        c.cog_unload()
        os.environ["VA_MACHINE_PROD"] = "1"
        c2 = ca.Alertes(admin)
        arme_prod = c2.boucle.is_running()
        c2.cog_unload()
        return c, arme_mac, arme_prod
    try:
        c, arme_mac, arme_prod = asyncio.run(scenario())
    finally:
        os.environ.pop("VA_MACHINE_PROD", None)
        if sauve is not None:
            os.environ["VA_MACHINE_PROD"] = sauve
    check("sans VA_MACHINE_PROD : boucle non armée", not arme_mac)
    check("avec VA_MACHINE_PROD=1 : boucle armée", arme_prod)
    check("la porte est _machine_proprietaire", appels and set(appels) == {"alertes-echeances"}, appels)

    serveurs, avert = c.mesurer()
    check("Spam lu chez le principal (le bot admin n'y est pas)",
          serveurs.get(ae.SERVEUR_SPAM, {}).get("salons") == 1 + 3 + 10, serveurs)
    check("catégories de Va IG comptées",
          serveurs[ae.VA_IG]["categories"] == [{"id": "7", "nom": "👤 Amelia", "salons": 44},
                                               {"id": "8", "nom": "👤 Lola", "salons": 2}], serveurs)
    check("tout vu : aucun avertissement", not avert, avert)
    faux._BOT_REF = None
    serveurs, avert = c.mesurer()
    check("principal absent : Spam pas vu, et c'est dit",
          ae.SERVEUR_SPAM not in serveurs and avert == [f"serveur {ae.SERVEUR_SPAM} vu par aucun bot"], avert)
    del sys.modules["web_upload"]

    arbre = ast.parse(pathlib.Path(ae.__file__).with_name("main.py").read_text(encoding="utf-8"))
    listes = {n.targets[0].id: [e.value for e in n.value.elts] for n in arbre.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id in ("MAIN_COGS", "ADMIN_COGS")}
    check("main.py : sur le bot admin, une seule fois",
          listes["ADMIN_COGS"].count("alertes") == 1 and "alertes" not in listes["MAIN_COGS"], listes)
    check("main.py : en fin de liste (le patch peach_accueil du VPS tient la ligne 58)",
          listes["ADMIN_COGS"][-1] == "alertes", listes["ADMIN_COGS"])


def main():
    test_gms()
    test_serveur()
    test_categories()
    test_nuit_echec_redemarrage()
    test_canal()
    test_cog()
    print("=" * 70)
    print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
    if FAILS:
        for f in FAILS:
            print("  - " + f)
    print("=" * 70)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
