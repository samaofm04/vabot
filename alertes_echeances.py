# -*- coding: utf-8 -*-
"""alertes_echeances.py — prevenir le staff AVANT qu'une limite casse quelque chose.

POURQUOI (audit des serveurs du 20/10/2026) : quatre choses allaient lacher
sans un mot, chacune decouverte trop tard la fois d'avant :

- le cookie GetMySocial (authToken) dure 30 jours. Echu, le 50/50 Seren ne se
  pose plus sur les nouveaux liens Twitter et Threads : tout part sur Emy, et
  rien ne le dit ailleurs que sur une page de reglages que personne n'ouvre ;
- le serveur Spam grossit d'environ 7 espaces VA par semaine (381 salons sur
  500 le 20/10). Discord refuse le 501e salon, et la creation d'un espace VA
  echoue alors au moment ou un VA arrive ;
- une categorie Discord ne prend que 50 salons. Sur Va IG, « 👤 Amelia » en
  avait 44 le 20/10 : le 51e ticket ne s'ouvrirait plus ;
- le coffre Outlook vide : le VA qui demande une adresse n'en recoit pas
  (un message lui est fait ailleurs ; ici, seulement le staff).

Les alertes partent dans le groupe Telegram des alertes SFS, par le bot de la
veille (@va_auto_dl_bot), avec la MEME fonction que les alertes SFS
(web_upload._telegram_envoyer) : elle suit deja le groupe quand Telegram le
passe en supergroupe. sendMessage seulement — getUpdates appartient a
tg_router, un second lecteur lui volerait ses messages.

UNE ALERTE PAR EVENEMENT. Ce qui est parti est note dans
data/alertes_echeances.json (safe_json) AVANT de passer au message suivant :
un redemarrage — le VPS en fait a chaque commit — ne renvoie rien. Une alerte
de seuil ne se rearme que nettement sous le seuil (450 → rearmee a 440) : un
serveur qui oscille autour de 450 au gre des arrivees et des departs aurait
sinon sonne a chaque passage.

Logique PURE ici (mesures → alertes), testable sans Discord ni reseau. La
lecture de Discord est dans cogs/alertes.py, qui ne tourne que sur la machine
de production (VA_MACHINE_PROD=1) : depuis le Mac, avec son propre data/, elle
aurait renvoye chaque alerte une seconde fois.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path("data")
FICHIER = DATA_DIR / "alertes_echeances.json"

#: Comme les alertes SFS : rien la nuit, garde pour 9 h (heure de Paris).
HEURES = (9, 22)

#: Cookie GetMySocial : J-7, J-1, puis « echu » s'il n'a pas ete recolle.
GMS_PALIERS = (7, 1, 0)

#: Le serveur Spam : Discord plafonne un serveur a 500 salons, categories
#: comprises (les fils ne comptent pas).
SERVEUR_SPAM = "1535758943324999711"
SERVEURS_SALONS = {SERVEUR_SPAM: "Spam"}          # id → nom si Discord ne le donne pas
PLAFOND_SERVEUR = 500
SEUIL_SERVEUR = 450
REARME_SERVEUR = 440

#: Va IG : 50 salons au plus par categorie (les tickets y sont ranges par model).
VA_IG = "1505418484052394004"
SERVEURS_CATEGORIES = {VA_IG: "Va IG"}
PLAFOND_CATEGORIE = 50
SEUIL_CATEGORIE = 48
REARME_CATEGORIE = 45

#: Le releve de l'audit, pour donner un rythme des la premiere alerte : sans
#: lui, il faudrait une semaine d'historique avant de pouvoir dire « plein vers
#: le … ». Constante, donc identique sur toutes les machines.
AMORCE_SALONS = {SERVEUR_SPAM: ("2026-10-20", 381)}
HISTORIQUE_JOURS = 60

LIEN_COOKIE = "https://youl4b.com/?tab=sgms"
LIEN_OUTLOOK = "https://youl4b.com/outlook"


# ---- Etat ------------------------------------------------------------------

def charger(fichier=None) -> Dict[str, Any]:
    d = safe_json.load(Path(fichier or FICHIER), None)
    d = d if isinstance(d, dict) else {}
    if not isinstance(d.get("envoyees"), dict):
        d["envoyees"] = {}
    if not isinstance(d.get("historique"), dict):
        d["historique"] = {}
    return d


def _ecrire(fichier, etat: Dict[str, Any]) -> None:
    Path(fichier).parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(Path(fichier), etat)


# ---- Heures et dates ---------------------------------------------------------

def _paris(ts: float) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Paris"))
    except Exception:
        return datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=1)


def dans_les_heures(maintenant: float) -> bool:
    return HEURES[0] <= _paris(maintenant).hour < HEURES[1]


def _jour(ts: float) -> str:
    return _paris(ts).date().isoformat()


# ---- Mesures qui ne passent pas par Discord ----------------------------------

def mesurer_hors_discord() -> Dict[str, Any]:
    """Echeance du cookie GetMySocial et etat du coffre Outlook.

    Lecture seule. Le cookie ne sort jamais : seule son echeance (le champ exp
    du jeton) est lue, par la fonction qu'emploie deja la page de reglages."""
    m: Dict[str, Any] = {"gms_exp": None, "outlook": None, "avertissements": []}
    try:
        import gms
        ck = gms.get_session_cookie()
        m["gms_exp"] = gms.cookie_expiration(ck) if ck else None
        if not ck:
            m["avertissements"].append("cookie GetMySocial absent")
        elif m["gms_exp"] is None:
            m["avertissements"].append("cookie GetMySocial illisible (pas d'échéance)")
    except Exception as e:
        m["avertissements"].append(f"cookie GetMySocial : {type(e).__name__}: {e}"[:200])
    try:
        import outlook_comptes
        m["outlook"] = {"libres": int(outlook_comptes.nb_libres()),
                        "total": len(outlook_comptes.comptes())}
    except Exception as e:
        # « je n'ai pas pu lire » n'est PAS « le coffre est vide » : pas d'alerte
        m["avertissements"].append(f"coffre Outlook : {type(e).__name__}: {e}"[:200])
    return m


# ---- Textes ------------------------------------------------------------------

def palier_gms(exp: Optional[int], maintenant: float) -> Optional[int]:
    """Le palier le plus urgent atteint (7, 1 ou 0 = echu), None s'il est loin.

    Un seul palier a la fois : deploye a J-3, on n'envoie pas « J-7 » en
    retard puis « J-1 » quatre jours plus tard en croyant bien faire — on
    envoie J-7 avec le vrai nombre de jours, puis J-1."""
    if not exp:
        return None
    reste = exp - maintenant
    for p in sorted(GMS_PALIERS):
        if reste <= p * 86400:
            return p
    return None


def texte_gms(exp: int, palier: int, maintenant: float) -> str:
    quand = _paris(exp).strftime("%d/%m à %H:%M")
    reste = exp - maintenant
    faire = ("À faire : se reconnecter à GetMySocial, copier la valeur d'authToken "
             "et la coller dans Réglages › Intégrations › Cookies GetMySocial.\n"
             + LIEN_COOKIE)
    if palier == 0:
        return ("❌ Cookie GetMySocial échu\n"
                f"Il a expiré le {quand} (heure de Paris).\n"
                "Les nouveaux liens Twitter et Threads partent tous sur Emy, sans le 50/50 Seren. "
                "Ils se rattrapent dès qu'un cookie valide est collé.\n"
                + faire)
    if palier == 1:
        h = max(1, int(round(reste / 3600)))
        dans = f"dans {h} h"
    else:
        j = max(2, int(round(reste / 86400)))
        dans = f"dans {j} jours"
    return (f"🔑 Cookie GetMySocial : fin {dans}\n"
            f"Il expire le {quand} (heure de Paris).\n"
            "Sans lui, les nouveaux liens Twitter et Threads n'ont plus le 50/50 Seren : "
            "tout part sur Emy.\n"
            + faire)


def _rythme(points: List[Tuple[str, int]], n: int, aujourd_hui: str) -> str:
    """« Au rythme des N derniers jours (+X salons par semaine), plein vers le … »
    « » sans au moins une semaine d'ecart entre le premier releve et aujourd'hui."""
    if not points:
        return ""
    j0, n0 = points[0]
    try:
        jours = (date.fromisoformat(aujourd_hui) - date.fromisoformat(j0)).days
    except Exception:
        return ""
    if jours < 7 or n <= n0:
        return ""
    par_jour = (n - n0) / jours
    plein = date.fromisoformat(aujourd_hui) + timedelta(days=int((PLAFOND_SERVEUR - n) / par_jour))
    return (f"Au rythme des {jours} derniers jours (+{round(par_jour * 7)} salons par semaine), "
            f"plein vers le {plein.strftime('%d/%m')}.\n")


def texte_serveur(nom: str, n: int, rythme: str = "") -> str:
    return (f"📦 Serveur « {nom} » : {n} salons sur {PLAFOND_SERVEUR}\n"
            f"Discord refuse le {PLAFOND_SERVEUR + 1}e salon : au-delà, plus aucun espace VA "
            f"ne pourra s'ouvrir. Il en reste {max(0, PLAFOND_SERVEUR - n)}.\n"
            + rythme
            + "À faire : supprimer les salons des VA partis, ou prévoir un second serveur.")


def texte_categorie(serveur: str, categorie: str, n: int) -> str:
    return (f"🗂️ {serveur} : catégorie « {categorie} » à {n} salons sur {PLAFOND_CATEGORIE}\n"
            f"Discord refuse un {PLAFOND_CATEGORIE + 1}e salon dans une catégorie : "
            "les prochains tickets de cette catégorie ne s'ouvriront plus.\n"
            "À faire : y faire de la place (tickets des VA partis).")


def texte_outlook(total: int) -> str:
    if total:
        tete = f"📭 Coffre Outlook vide : 0 adresse libre ({total} déjà données)"
    else:
        tete = "📭 Coffre Outlook vide : aucune adresse enregistrée"
    return (tete + "\n"
            "Les VA qui demandent une adresse Outlook (Va IG et Twitter) n'en reçoivent plus.\n"
            "À faire : ajouter des adresses.\n" + LIEN_OUTLOOK)


# ---- Decision ----------------------------------------------------------------

def _noter_historique(etat: Dict[str, Any], serveurs: Dict[str, Any], maintenant: float) -> None:
    """Un releve par jour et par serveur surveille, pour donner le rythme."""
    jour = _jour(maintenant)
    for gid in SERVEURS_SALONS:
        s = serveurs.get(gid)
        if not s:
            continue
        pts = [p for p in (etat["historique"].get(gid) or [])
               if isinstance(p, list) and len(p) == 2]
        if pts and pts[-1][0] == jour:
            pts[-1] = [jour, int(s["salons"])]
        else:
            pts.append([jour, int(s["salons"])])
        etat["historique"][gid] = pts[-HISTORIQUE_JOURS:]


def _points(etat: Dict[str, Any], gid: str) -> List[Tuple[str, int]]:
    pts = [tuple(p) for p in (etat["historique"].get(gid) or [])]
    am = AMORCE_SALONS.get(gid)
    if am and (not pts or am[0] < pts[0][0]):
        pts.insert(0, am)
    return pts


def evaluer(mesures: Dict[str, Any], etat: Dict[str, Any],
            maintenant: float) -> Tuple[List[Tuple[str, str]], List[str]]:
    """(alertes neuves [(cle, texte)], cles a rearmer). Ne touche a rien.

    La cle dit l'evenement : deux passages qui voient la meme situation
    rendent la meme cle, et une cle deja dans etat["envoyees"] ne repart pas."""
    deja = etat.get("envoyees") or {}
    neuves: List[Tuple[str, str]] = []
    rearmer: List[str] = []

    exp = mesures.get("gms_exp")
    if exp:
        # un cookie recolle a une autre echeance : ses paliers repartent de zero
        rearmer += [k for k in deja if k.startswith("gms:") and k.split(":")[1] != str(exp)]
        p = palier_gms(exp, maintenant)
        if p is not None and f"gms:{exp}:{p}" not in deja:
            neuves.append((f"gms:{exp}:{p}", texte_gms(exp, p, maintenant)))

    serveurs = mesures.get("serveurs") or {}
    for gid, nom_defaut in SERVEURS_SALONS.items():
        s = serveurs.get(gid)
        if not s:
            continue                      # pas vu ce tour-ci : on ne rearme rien
        cle, n = f"salons:{gid}", int(s["salons"])
        if n >= SEUIL_SERVEUR and cle not in deja:
            neuves.append((cle, texte_serveur(s.get("nom") or nom_defaut, n,
                                              _rythme(_points(etat, gid), n, _jour(maintenant)))))
        elif n <= REARME_SERVEUR and cle in deja:
            rearmer.append(cle)

    for gid, nom_defaut in SERVEURS_CATEGORIES.items():
        s = serveurs.get(gid)
        if not s:
            continue
        vues = set()
        for c in s.get("categories") or []:
            cle, n = f"categorie:{gid}:{c['id']}", int(c["salons"])
            vues.add(cle)
            if n >= SEUIL_CATEGORIE and cle not in deja:
                neuves.append((cle, texte_categorie(nom_defaut, c.get("nom") or "?", n)))
            elif n <= REARME_CATEGORIE and cle in deja:
                rearmer.append(cle)
        # categorie supprimee depuis l'alerte : plus rien a surveiller
        rearmer += [k for k in deja if k.startswith(f"categorie:{gid}:") and k not in vues]

    ol = mesures.get("outlook")
    if isinstance(ol, dict):
        if int(ol.get("libres") or 0) == 0:
            if "outlook:vide" not in deja:
                neuves.append(("outlook:vide", texte_outlook(int(ol.get("total") or 0))))
        elif "outlook:vide" in deja:
            rearmer.append("outlook:vide")
    return neuves, sorted(set(rearmer))


# ---- Envoi -------------------------------------------------------------------

def envoyer_telegram(texte: str) -> Dict[str, Any]:
    """Dans le groupe des alertes SFS, par la fonction des alertes SFS."""
    import web_upload as w
    chat = str((w._sfs_alertes_cfg().get("telegram") or {}).get("chat_id") or "").strip()
    if not chat:
        return {"ok": False, "error": "aucun groupe Telegram réglé (Réglages des alertes SFS)"}
    return w._telegram_envoyer(chat, texte)


_DERNIERE_ERREUR = {"texte": ""}


def tour(serveurs: Dict[str, Any], avertissements: List[str] = (),
         maintenant: Optional[float] = None,
         envoyer: Optional[Callable[[str], Dict[str, Any]]] = None,
         fichier=None, hors_discord: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Un passage : mesurer, decider, envoyer ce qui est neuf, noter.

    `serveurs` vient du cog : {id: {"nom", "salons", "categories": [{"id",
    "nom", "salons"}]}}, un serveur absent = pas vu ce tour-ci."""
    maintenant = time.time() if maintenant is None else maintenant
    fichier = Path(fichier or FICHIER)
    envoyer = envoyer or envoyer_telegram
    etat = charger(fichier)
    mesures = dict(mesurer_hors_discord() if hors_discord is None else hors_discord)
    mesures["serveurs"] = serveurs or {}
    avert = list(mesures.pop("avertissements", []) or []) + list(avertissements or [])

    _noter_historique(etat, mesures["serveurs"], maintenant)
    neuves, rearmer = evaluer(mesures, etat, maintenant)
    for k in rearmer:
        etat["envoyees"].pop(k, None)

    bilan: Dict[str, Any] = {"envoyees": [], "gardees": [], "erreurs": [], "rearmees": rearmer}
    if neuves and not dans_les_heures(maintenant):
        bilan["gardees"] = [k for k, _ in neuves]
    else:
        for k, texte in neuves:
            try:
                r = envoyer(texte) or {}
            except Exception as e:
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if r.get("ok"):
                etat["envoyees"][k] = {"quand": datetime.fromtimestamp(maintenant, timezone.utc)
                                       .isoformat(timespec="seconds"), "texte": texte}
                # noté tout de suite : si le message suivant plante le processus,
                # celui-ci ne doit pas repartir au redemarrage
                _ecrire(fichier, etat)
                bilan["envoyees"].append(k)
                print(f"[alertes] envoyée sur Telegram : {k}", flush=True)
            else:
                bilan["erreurs"].append(f"{k} : {(r.get('error') or 'envoi refusé')}"[:300])

    if bilan["erreurs"]:
        txt = " | ".join(bilan["erreurs"])
        if txt != _DERNIERE_ERREUR["texte"]:       # une ligne par erreur nouvelle, pas par tour
            _DERNIERE_ERREUR["texte"] = txt
            print(f"[alertes] envoi impossible, réessai au prochain tour : {txt}", flush=True)
    etat["dernier_tour"] = {
        "quand": datetime.fromtimestamp(maintenant, timezone.utc).isoformat(timespec="seconds"),
        "gms_exp": mesures.get("gms_exp"),
        "outlook": mesures.get("outlook"),
        "serveurs": {g: {"nom": s.get("nom"), "salons": s.get("salons"),
                         # les plus remplies : « Amelia 44/50 » se lit sans ouvrir Discord
                         "categories_max": sorted(
                             ([c.get("nom"), c.get("salons")] for c in (s.get("categories") or [])),
                             key=lambda x: -int(x[1] or 0))[:3]}
                     for g, s in mesures["serveurs"].items()},
        "avertissements": avert,
        **{k: v for k, v in bilan.items() if v},
    }
    _ecrire(fichier, etat)
    return bilan
