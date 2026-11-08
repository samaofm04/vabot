"""entretien_ouvert.py — le serveur Entretien (TRUST Agency) sans vérification.

Propriétaire, 08/11/2026 : « il ne faudrait pas mettre de sécurité dans ce
serveur-là […] tout le monde est vérifié instantanément », puis, salon par
salon, ce qui reste et ce qui part. Ses choix, un par un :

- supprimés : 🔗・mon-lien-invitation (« exactement la même chose » que
  🤝・parrainage), ✅┃entrées, 🚩┃suspicions ;
- cachés, pas supprimés : ✅・membres-vérifiés et 🔐・vérification. Les 71
  liens perso des recruteurs sont des invitations créées sur
  ✅・membres-vérifiés (entretien_parrainage.lien_pour) et 4 autres sur
  🔐・vérification : supprimer le salon les aurait tous fait mourir ;
- ⏳┃en-attente devient 🎙️┃candidat-en-vocal : Peach y prévient les managers
  d'un candidat dans le vocal (cogs/peach_accueil, salon_attente) ;
- le rôle ✅ Vérifié reste — le recrutement à 0,20 $ ne compte qu'un invité
  qui l'a (entretien_parrainage, VPS) — mais chaque membre le reçoit à son
  arrivée, les 37 qui ne l'avaient pas compris ;
- 📢・annonces-entretiens et le vocal 🎙️ Entretiens étaient cachés aux
  vérifiés (le parcours d'avant : vérifié APRÈS l'entretien). Tout le monde
  étant vérifié, ils n'auraient plus été vus de personne : ✅ Vérifié y prend
  les droits de ⏳ En attente ;
- dans 🤝・parrainage, « Instagram : en construction » devient le salon
  📷・instagram (« il est là, maintenant »).

Les changements de salons se font une fois : chaque étape réussie est notée
(data/entretien_ouvert.json), une étape refusée est dite et retentée au
démarrage suivant. Le rôle, lui, est donné chaque minute aux arrivants.
Discord refuse (403) à un bot de régler un droit qu'il n'a pas : ces bits-là
sont gardés tels quels (journal_primes._permissions_du_bot).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

GID = "1552152470464110703"                      # TRUST Agency (Entretien)
DATA_DIR = Path(__file__).resolve().parent / "data"
FICHIER = DATA_DIR / "entretien_ouvert.json"
PERIODE_S = 60
#: au plus autant de rôles donnés par tour (un PUT chacun)
ROLES_PAR_TOUR = 40
VOIR, ECRIRE = 1024, 2048
#: le rôle géré du bot (« TRUST Agency ») : il garde sa vue sur les salons
#: cachés, sans elle le bot ne pourrait plus créer les liens perso sur
#: ✅・membres-vérifiés
ROLE_BOT = "1552159041084727339"

A_SUPPRIMER = {
    "1552159108898103347": "🔗・mon-lien-invitation",
    "1552167029253869610": "✅┃entrées",
    "1552170122288963648": "🚩┃suspicions",
}
A_CACHER = {
    "1552152471281860611": "✅・membres-vérifiés",
    "1552167025097576478": "🔐・vérification",
}
#: ⏳┃en-attente : le salon de Peach (verif_discord.serveur, salon_attente)
EN_ATTENTE = "1552170120632205314"
NOM_EN_ATTENTE = "🎙️┃candidat-en-vocal"
A_OUVRIR = {
    "1560163540831182941": "📢・annonces-entretiens",
    "1552152471281860612": "🎙️ Entretiens",
}
PARRAINAGE = "1552159107207790602"               # 🤝・parrainage
DEUXIEME_PARRAINAGE = "1552159204159266884"      # « 🎁 Deuxième parrainage »
INSTAGRAM = "1552159912849580136"                # 📷・instagram
ANCIEN_INSTAGRAM = "📷 Instagram : **en construction**."
NOUVEL_INSTAGRAM = f"📷 Instagram : <#{INSTAGRAM}>"

LOCK = threading.Lock()
_DEMARRE = False
_DIT: Dict[str, str] = {}


def _dire(cle: str, texte: str) -> None:
    if _DIT.get(cle, "") != texte:
        _DIT[cle] = texte
        if texte:
            print(f"[entretien-ouvert] {texte}", flush=True)


def _api(methode: str, chemin: str, **kw):
    import verif_discord as vd
    return vd.api(methode, chemin, gid=GID, **kw)


def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(FICHIER, default={}) or {}
    except Exception:                                        # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def _noter(etape: str, resultat: str) -> None:
    with LOCK:
        d = _etat()
        if resultat == "ok":
            d.setdefault("faites", {})[etape] = int(time.time())
            d.setdefault("echecs", {}).pop(etape, None)
        else:
            d.setdefault("echecs", {})[etape] = resultat
        safe_json.write(FICHIER, d)


def _ow(c: Dict[str, Any], oid: str) -> Optional[Dict[str, Any]]:
    return next((o for o in c.get("permission_overwrites") or [] if str(o.get("id")) == oid), None)


def _poser(salon: str, oid: str, typ: int, allow: int, deny: int, ancien: Optional[Dict[str, Any]],
           masque: int) -> int:
    """PUT d'un droit, en gardant tels quels les bits que le bot n'a pas."""
    a0, d0 = (int(ancien.get("allow") or 0), int(ancien.get("deny") or 0)) if ancien else (0, 0)
    gardes = (a0 | d0) & ~masque
    code, _ = _api("PUT", f"/channels/{salon}/permissions/{oid}",
                   json={"type": typ, "allow": str((allow & masque) | (a0 & ~masque)),
                         "deny": str((deny & masque) | (d0 & ~masque))})
    if code == 403 and gardes:
        # Discord refuse même de RENVOYER un droit que le bot n'a pas : ces
        # bits-là (les fils de discussion de 🔐・vérification) partent alors.
        # Aucun rôle ne les donne sur Entretien : rien ne change pour personne.
        code, _ = _api("PUT", f"/channels/{salon}/permissions/{oid}",
                       json={"type": typ, "allow": str(allow & masque), "deny": str(deny & masque)})
        if code in (200, 204):
            _dire(f"gardes:{salon}", f"droits que le bot n'a pas retirés de {salon} : {gardes}")
    return code


def menage() -> Dict[str, str]:
    """Les changements de salons, chacun une fois. Rend {étape: résultat}."""
    import verif_discord as vd
    import journal_primes
    d = _etat()
    faites = d.get("faites") or {}
    out: Dict[str, str] = {}
    code, salons = _api("GET", f"/guilds/{GID}/channels")
    if code != 200 or not isinstance(salons, list):
        _dire("salons", f"salons illisibles (HTTP {code}) : ménage remis au tour suivant")
        return {"salons": f"HTTP {code}"}
    _dire("salons", "")
    par_id = {str(c.get("id")): c for c in salons if isinstance(c, dict)}
    cfg = vd.serveur(GID) or {}
    role_v, role_a = str(cfg.get("role_verifie") or ""), str(cfg.get("role_attente") or "")
    bot = str(vd.bot_du_serveur(GID).get("app_id") or "")
    siens = journal_primes._permissions_du_bot(bot) if bot else None
    masque = siens if siens is not None and not siens & 8 else ~0

    def faire(etape: str, fn) -> None:
        if etape in faites:
            return
        try:
            r = fn()
        except Exception as e:                               # noqa: BLE001
            r = f"{type(e).__name__}: {e}"
        out[etape] = r
        _noter(etape, r)
        if r != "ok":
            print(f"[entretien-ouvert] {etape} : {r} — retenté au prochain démarrage", flush=True)

    for sid, nom in A_SUPPRIMER.items():
        def supprimer(sid=sid):
            if sid not in par_id:
                return "ok"                                  # déjà parti
            code, _ = _api("DELETE", f"/channels/{sid}")
            return "ok" if code in (200, 204, 404) else f"HTTP {code}"
        faire(f"supprimer:{sid}", supprimer)

    for sid, nom in A_CACHER.items():
        def cacher(sid=sid):
            c = par_id.get(sid)
            if not c:
                return "salon introuvable"
            # personne d'autre que les BOSS (administrateurs) et le bot : la
            # vue de @everyone retirée, les droits du staff et d'un membre
            # nommé enlevés
            e = _ow(c, GID) or {}
            code = _poser(sid, GID, 0, int(e.get("allow") or 0) & ~VOIR, int(e.get("deny") or 0) | VOIR,
                          e or None, masque)
            if code not in (200, 204):
                return f"@everyone : HTTP {code}"
            for o in c.get("permission_overwrites") or []:
                oid = str(o.get("id"))
                if oid in (GID, bot, ROLE_BOT):
                    continue
                if int(o.get("allow") or 0) & VOIR:
                    code, _ = _api("DELETE", f"/channels/{sid}/permissions/{oid}")
                    if code not in (200, 204, 404):
                        return f"droit {oid} : HTTP {code}"
            return "ok"
        faire(f"cacher:{sid}", cacher)

    def renommer():
        if EN_ATTENTE not in par_id:
            return "salon introuvable"
        code, _ = _api("PATCH", f"/channels/{EN_ATTENTE}", json={
            "name": NOM_EN_ATTENTE,
            "topic": "Peach prévient ici quand un candidat attend son entretien dans 🎙️ Entretiens."})
        return "ok" if code == 200 else f"HTTP {code}"
    faire("renommer:en-attente", renommer)

    for sid, nom in A_OUVRIR.items():
        def ouvrir(sid=sid):
            c = par_id.get(sid)
            if not c or not role_v or not role_a:
                return "salon ou rôle introuvable"
            attente = _ow(c, role_a)
            if not attente:
                return "⏳ En attente n'y a pas de droit à recopier"
            deja = _ow(c, role_v) or {}
            if int(deja.get("allow") or 0) & VOIR and not int(deja.get("deny") or 0) & VOIR:
                return "ok"                  # déjà ouvert (à la main, pour le vocal)
            code = _poser(sid, role_v, 0, int(attente.get("allow") or 0), int(attente.get("deny") or 0),
                          _ow(c, role_v), masque)
            if code == 403:
                # 08/11 : le vocal 🎙️ Entretiens est dans 🎙️ ESPACE VOCAL, que
                # le bot ne voit pas — Discord lui interdit d'en régler les
                # droits. À faire à la main ; l'étape se tient alors pour faite.
                return "HTTP 403 (le bot ne voit pas ce salon : ✅ Vérifié à ouvrir à la main)"
            return "ok" if code in (200, 204) else f"HTTP {code}"
        faire(f"ouvrir:{sid}", ouvrir)

    def instagram():
        code, m = _api("GET", f"/channels/{PARRAINAGE}/messages/{DEUXIEME_PARRAINAGE}")
        if code != 200 or not isinstance(m, dict) or not m.get("embeds"):
            return f"message illisible (HTTP {code})"
        e = m["embeds"][0]
        texte = str(e.get("description") or "")
        if NOUVEL_INSTAGRAM in texte:
            return "ok"
        if ANCIEN_INSTAGRAM not in texte:
            return "ligne « Instagram : en construction » introuvable"
        import trust_agency_anciens as taa
        embeds = [taa.embed_a_renvoyer(x) for x in m["embeds"]]
        embeds[0]["description"] = texte.replace(ANCIEN_INSTAGRAM, NOUVEL_INSTAGRAM)
        code, _ = _api("PATCH", f"/channels/{PARRAINAGE}/messages/{DEUXIEME_PARRAINAGE}", json={"embeds": embeds})
        return "ok" if code == 200 else f"HTTP {code}"
    faire("instagram", instagram)

    if out:
        ok = [k for k, v in out.items() if v == "ok"]
        print(f"[entretien-ouvert] ménage : {len(ok)} étape(s) faite(s) {ok}"
              + (f", {len(out) - len(ok)} refusée(s)" if len(ok) != len(out) else ""), flush=True)
    return out


def verifier_tous() -> Dict[str, Any]:
    """✅ Vérifié pour chaque membre qui ne l'a pas (bots exceptés)."""
    import verif_discord as vd
    role = str((vd.serveur(GID) or {}).get("role_verifie") or "")
    bilan: Dict[str, Any] = {"donnes": 0, "refus": 0}
    if not role:
        _dire("role", "rôle ✅ Vérifié inconnu : rien donné")
        return bilan
    membres: List[Dict[str, Any]] = []
    apres = ""
    for _ in range(20):
        code, page = _api("GET", f"/guilds/{GID}/members?limit=1000" + (f"&after={apres}" if apres else ""))
        if code != 200 or not isinstance(page, list):
            _dire("membres", f"membres illisibles (HTTP {code})")
            return bilan
        membres += page
        if len(page) < 1000:
            break
        apres = str(max(int(m["user"]["id"]) for m in page))
    _dire("membres", "")
    sans = [m for m in membres if not (m.get("user") or {}).get("bot") and role not in (m.get("roles") or [])]
    for m in sans[:ROLES_PAR_TOUR]:
        uid = str(m["user"]["id"])
        code, _ = _api("PUT", f"/guilds/{GID}/members/{uid}/roles/{role}")
        if code in (200, 204):
            bilan["donnes"] += 1
        else:
            bilan["refus"] += 1
            _dire(f"role:{uid}", f"✅ Vérifié refusé à {uid} (HTTP {code})")
        time.sleep(0.5)
    if bilan["donnes"]:
        print(f"[entretien-ouvert] ✅ Vérifié donné à {bilan['donnes']} membre(s)"
              + (f", {len(sans) - ROLES_PAR_TOUR} au tour suivant" if len(sans) > ROLES_PAR_TOUR else ""),
              flush=True)
    return bilan


def tour() -> Dict[str, Any]:
    """Le ménage (tant qu'une étape reste à faire), puis les rôles."""
    d = _etat()
    faites = d.get("faites") or {}
    etapes = ([f"supprimer:{s}" for s in A_SUPPRIMER] + [f"cacher:{s}" for s in A_CACHER]
              + ["renommer:en-attente"] + [f"ouvrir:{s}" for s in A_OUVRIR] + ["instagram"])
    bilan: Dict[str, Any] = {}
    if any(e not in faites for e in etapes) and not d.get("menage_tente"):
        bilan["menage"] = menage()
        with LOCK:
            d = _etat()
            d["menage_tente"] = int(time.time())       # une fois par démarrage (voir demarrer)
            safe_json.write(FICHIER, d)
    bilan["roles"] = verifier_tous()
    return bilan


def demarrer() -> bool:
    """Le fil, chaque minute (web_upload.create_app, machine de production
    seulement). Le ménage est retenté une fois à chaque démarrage."""
    global _DEMARRE
    if _DEMARRE:
        return False
    _DEMARRE = True
    with LOCK:
        d = _etat()
        d.pop("menage_tente", None)
        safe_json.write(FICHIER, d)

    def boucle():
        time.sleep(60)
        while True:
            try:
                import verif_discord as vd
                with vd.sur_serveur(GID):
                    tour()
            except Exception as e:                           # noqa: BLE001
                print(f"[entretien-ouvert] {type(e).__name__}: {e}", flush=True)
            time.sleep(PERIODE_S)

    threading.Thread(target=boucle, daemon=True, name="entretien-ouvert").start()
    return True
