"""ProxEasy : la clé API REST (collée sur le site) et les logins des proxys,
postés par Ryuk dans les salons « proxyeasy-N-pe-XXXX » du serveur Youl4b ( Spam ).

Demande du propriétaire (25/10/2026) : « un de mes bots envoie les logins, une
ligne par truc séparé ». Sur téléphone, l'appui long copie le message ENTIER :
chaque valeur est donc seule dans son message, sans titre ni libellé — hôte,
port, utilisateur, mot de passe, dans cet ordre, comme les logins postés à la
main avant. « pe-XXXX » est le numéro du service chez ProxEasy.

En cinquième message, le lien de rotation (« changer d'IP ») s'il est connu :
l'API ne le donne pas, il est relevé dans l'espace client et gardé dans l'état
(clé « rotation », par numéro de service). Jamais ouvert ici : l'ouvrir change
l'IP — d'où l'aperçu de lien coupé sur chaque message.

Port SOCKS5, pas HTTP : les logins que l'équipe s'échangeait (salons 3, 5, 6,
et l'exemple du propriétaire) portent le port SOCKS5 ; ProxEasy donne le même
hôte et les mêmes identifiants pour les deux, seul le port change.

Rien de secret ne sort d'ici : ni la clé ni un identifiant dans le journal, la
page ne montre que les quatre derniers caractères de la clé. Les salons sont
vérifiés fermés à @everyone avant chaque envoi.
"""
from __future__ import annotations

import html
import os
import re
import threading
import time
from pathlib import Path

import requests

import safe_json

DATA = Path(__file__).resolve().parent / "data"
CLE = DATA / "proxeasy_cle.json"            # {"cle", "le", "par", "test"}
ETAT = DATA / "proxeasy_salons.json"        # mode, messages postés, alertes, dernier relevé
API = "https://api.proxeasy.net/v1"
DISCORD = "https://discord.com/api/v10"
SERVEUR = "1535758943324999711"             # Youl4b ( Spam ) — Ryuk y est administrateur
# Youl4b SEUL, pas tous les serveurs US (guild_features.US_GUILD_IDS) : un
# proxy = un salon, et YouCham n'a recopié ni la catégorie proxy ni
# suivi-proxy (30/10/2026). Le suivi des proxys reste du côté du propriétaire.
SUIVI = "1556970178846130187"               # suivi-proxy (son tableau est tenu par proxy_discord, hors git)
MOTIF = re.compile(r"proxyeasy-(\d+)-pe-(\d+)$")
PROTOCOLE = "socks5"
PERIODE_S = 600
VOIR = 1 << 10
ADMINISTRATEUR = 1 << 3
# messages silencieux (9 salons × 4 messages notifiaient tout le monde d'un
# coup) et sans aperçu de lien
_DRAPEAUX = (1 << 12) | (1 << 2)

_VERROU = threading.Lock()
_DEMARRE = False


class Erreur(Exception):
    """Refus de ProxEasy ou de Discord : un texte lisible, jamais la clé."""

    def __init__(self, texte: str, statut: int = 0):
        super().__init__(texte)
        self.statut = statut


# ── La clé ──────────────────────────────────────────────────────────────────

def _fiche_cle() -> dict:
    d = safe_json.load(CLE, default={}) or {}
    return d if isinstance(d, dict) else {}


def cle() -> str:
    return str(_fiche_cle().get("cle") or "")


def etat_cle() -> dict:
    """Ce que la page peut montrer : jamais la clé, seulement sa fin."""
    d = _fiche_cle()
    k = str(d.get("cle") or "")
    return {"presente": bool(k), "fin": k[-4:] if len(k) >= 16 else "",
            "le": d.get("le"), "par": d.get("par") or "", "test": d.get("test") or {}}


def _ecrire_cle(d: dict) -> bool:
    # pas de copie .prev : une seconde copie de la clé pour rien ; perdue,
    # elle se recolle en deux secondes
    ok = safe_json.write(CLE, d, backup=False)
    try:
        os.chmod(CLE, 0o600)
    except OSError:
        pass
    return ok


def enregistrer_cle(valeur: str, par: str) -> tuple[bool, str]:
    """Teste la clé AVANT de la garder : une clé refusée remplacerait une clé
    peut-être encore bonne. Un ProxEasy injoignable n'empêche pas de la
    garder (le relevé suivant dira)."""
    v = (valeur or "").strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    if len(v) < 20 or len(v) > 512 or any(c.isspace() for c in v):
        return False, "Clé vide ou mal copiée : colle-la en entier, sans espace."
    if v.startswith("pe_mcp_"):
        return False, ("Ça, c'est la clé MCP (pour Claude). Ici, il faut celle de l'onglet "
                       "« Application ou script (API REST) » de ProxEasy.")
    ok, texte, statut = tester(v)
    if not ok and statut in (401, 403):
        return False, "ProxEasy refuse cette clé : " + texte
    d = {"cle": v, "le": time.time(), "par": par or "",
         "test": {"ok": ok, "texte": texte, "le": time.time()}}
    if not _ecrire_cle(d):
        return False, "Écriture impossible dans data/ : clé non enregistrée."
    fin = v[-4:]
    if ok:
        return True, f"Clé ProxEasy enregistrée (…{fin}). {texte}"
    return True, f"Clé enregistrée (…{fin}), mais le test a échoué : {texte}"


def noter_test(ok: bool, texte: str) -> None:
    d = _fiche_cle()
    if d.get("cle"):
        d["test"] = {"ok": ok, "texte": texte, "le": time.time()}
        _ecrire_cle(d)


# ── L'API ProxEasy ──────────────────────────────────────────────────────────

def _get(chemin: str, k: str = "", params: dict | None = None):
    k = k or cle()
    if not k:
        raise Erreur("aucune clé ProxEasy enregistrée")
    try:
        r = requests.get(API + chemin, params=params, timeout=20,
                         headers={"Authorization": "Bearer " + k, "Accept": "application/json",
                                  "User-Agent": "youl4b-vabot/1.0"})
    except requests.RequestException as e:
        raise Erreur(f"ProxEasy injoignable ({type(e).__name__})", -1)
    try:
        j = r.json()
    except ValueError:
        j = {}
    err = j.get("error") if isinstance(j, dict) else None
    if r.status_code >= 400 or err:
        err = err if isinstance(err, dict) else {}
        texte = " — ".join(x for x in (str(err.get("code") or f"HTTP {r.status_code}"),
                                        str(err.get("message") or "")) if x)
        raise Erreur(texte, r.status_code)
    # même enveloppe que le MCP de ProxEasy : {"data": ..., "request_id": ...}
    return j.get("data", j) if isinstance(j, dict) else j


def services(k: str = "") -> list:
    out, apres = [], None
    for _ in range(50):
        params = {"limit": 100}
        if apres:
            params["after"] = apres
        d = _get("/services", k, params)
        items = d.get("items") if isinstance(d, dict) else d
        if not isinstance(items, list):
            raise Erreur("réponse inattendue de ProxEasy (liste des services)")
        out += [i for i in items if isinstance(i, dict)]
        apres = d.get("next_cursor") if isinstance(d, dict) else None
        if not apres:
            break
    return out


def identifiants(service_id: int, k: str = "") -> list:
    """[hôte, port, utilisateur, mot de passe] du port SOCKS5 (HTTP à défaut)."""
    d = _get(f"/services/{int(service_id)}/credentials", k)
    eps = d.get("endpoints") if isinstance(d, dict) else None
    eps = [e for e in eps or [] if isinstance(e, dict)]
    if not eps:
        raise Erreur("ProxEasy ne donne aucun identifiant pour ce proxy")
    ep = next((e for e in eps if e.get("protocol") == PROTOCOLE), eps[0])
    return [str(ep.get(c) if ep.get(c) is not None else "").strip()
            for c in ("host", "port", "username", "password")]


def _lisible(s: dict) -> bool:
    return s.get("status") == "active" and "credentials" in (s.get("capabilities") or [])


def tester(k: str = "") -> tuple[bool, str, int]:
    """(ok, texte, statut HTTP du refus). Lit la liste des proxys puis les
    identifiants d'un seul, sans rien en montrer."""
    try:
        servs = services(k)
    except Erreur as e:
        return False, str(e), e.statut
    actifs = [s for s in servs if s.get("status") == "active"]
    lisibles = [s for s in actifs if _lisible(s)]
    if not lisibles:
        return False, f"clé acceptée, mais aucun proxy actif aux identifiants lisibles ({len(servs)} service(s))", 0
    try:
        identifiants(int(lisibles[0]["id"]), k)
    except Erreur as e:
        return False, f"clé acceptée, mais les identifiants sont refusés : {e}", e.statut
    return True, f"{len(actifs)} proxy(s) actif(s), identifiants lisibles.", 0


# ── Discord (Ryuk, le bot principal) ────────────────────────────────────────

def _discord(methode: str, chemin: str, corps=None):
    """Réponse JSON, ou None sur 404 (message ou salon disparu)."""
    jeton = (os.environ.get("DISCORD_TOKEN") or "").strip()
    if not jeton:
        raise Erreur("jeton du bot absent (DISCORD_TOKEN)")
    for essai in range(3):
        try:
            r = requests.request(methode, DISCORD + chemin, json=corps, timeout=20,
                                 headers={"Authorization": "Bot " + jeton})
        except requests.RequestException as e:
            raise Erreur(f"Discord injoignable ({type(e).__name__})", -1)
        if r.status_code == 429 and essai < 2:
            try:
                attente = float((r.json() or {}).get("retry_after") or 1)
            except ValueError:
                attente = 1.0
            time.sleep(min(attente, 30) + 0.25)
            continue
        if r.status_code == 404:
            return None
        if not r.ok:
            raise Erreur(f"Discord HTTP {r.status_code} sur {methode} {chemin.split('?')[0]}", r.status_code)
        return r.json() if r.content else {}
    raise Erreur("Discord limite le débit (429) : réessai au prochain tour", 429)


def _visibilite(salon: dict, roles: dict, nom_membre) -> tuple[bool, list]:
    """(ouvert à tout le serveur, [qui le voit]). Le droit « voir » d'@everyone
    vient du serveur puis du salon ; si le salon le refuse, ne voient que les
    rôles et membres qu'il autorise, plus les rôles administrateurs."""
    ow = {str(o.get("id")): o for o in salon.get("permission_overwrites") or []}
    tous = int((roles.get(SERVEUR) or {}).get("permissions") or 0) & VOIR
    e = ow.get(SERVEUR)
    if e:
        if int(e.get("deny") or 0) & VOIR:
            tous = 0
        if int(e.get("allow") or 0) & VOIR:
            tous = VOIR
    if tous:
        return True, ["tout le serveur"]
    voient = []
    for i, o in ow.items():
        if i == SERVEUR or not int(o.get("allow") or 0) & VOIR:
            continue
        if int(o.get("type") or 0) == 1:
            voient.append(nom_membre(i))
        else:
            voient.append("@" + str((roles.get(i) or {}).get("name") or i))
    admins = sorted("@" + str(r.get("name")) for i, r in roles.items()
                    if i != SERVEUR and int(r.get("permissions") or 0) & ADMINISTRATEUR)
    return False, voient + admins


def _nom_membre(uid: str, cache: dict) -> str:
    if uid not in cache:
        m = _discord("GET", f"/guilds/{SERVEUR}/members/{uid}") or {}
        u = m.get("user") or {}
        cache[uid] = str(m.get("nick") or u.get("global_name") or u.get("username") or f"membre {uid}")
    return cache[uid]


# ── L'état ──────────────────────────────────────────────────────────────────

def _charger() -> dict:
    d = safe_json.load(ETAT, default={}) or {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("mode", "arret")           # arret | essai | tous
    d.setdefault("salons", {})
    d.setdefault("alertes", {})
    return d


def _sauver(etat: dict) -> None:
    if not safe_json.write(ETAT, etat):
        print("[proxeasy] état non enregistré (écriture refusée)", flush=True)


def etat() -> dict:
    return _charger()


def choisir_mode(mode: str) -> tuple[bool, str]:
    if mode not in ("arret", "essai", "tous"):
        return False, "mode inconnu"
    with _VERROU:
        d = _charger()
        d["mode"] = mode
        _sauver(d)
    return True, {"arret": "Envois arrêtés : les messages déjà postés restent.",
                  "essai": "Essai lancé dans le premier salon proxy.",
                  "tous": "Les logins partent dans tous les salons proxy."}[mode]


def rotation(etat: dict, sid: int) -> str:
    """Le lien de rotation de ce proxy, s'il a été relevé (https, sans blanc)."""
    lien = str((etat.get("rotation") or {}).get(str(sid)) or "").strip()
    return lien if re.fullmatch(r"https://\S{8,500}", lien) else ""


def _alerter(etat: dict, cle_a: str, texte: str) -> None:
    """Dit le problème UNE fois dans suivi-proxy (pas à chaque tour)."""
    if cle_a in etat["alertes"]:
        return
    m = _discord("POST", f"/channels/{SUIVI}/messages",
                 {"content": texte, "allowed_mentions": {"parse": []}})
    etat["alertes"][cle_a] = {"le": time.time(), "texte": texte[:300],
                              "message": (m or {}).get("id")}
    print(f"[proxeasy] alerte « {cle_a} » dite dans suivi-proxy", flush=True)


def _lever(etat: dict, cle_a: str, texte: str = "") -> None:
    if cle_a not in etat["alertes"]:
        return
    if texte:
        _discord("POST", f"/channels/{SUIVI}/messages",
                 {"content": texte, "allowed_mentions": {"parse": []}})
    etat["alertes"].pop(cle_a, None)


# ── Les messages d'un salon ─────────────────────────────────────────────────

def _tenir(etat: dict, salon: str, sid: int, valeurs: list) -> str:
    """Quatre messages, un par valeur. Déjà là : édités si une valeur a
    changé, jamais reposés. Un message disparu (effacé à la main) : le jeu
    complet est reposé dans l'ordre, les restes de l'ancien effacés."""
    fiche = etat["salons"].get(salon) or {}
    ids = [str(i) for i in fiche.get("messages") or []]
    # un envoi interrompu au tour précédent : l'ancien jeu attend encore d'être effacé
    restes = [str(i) for i in fiche.get("anciens") or [] if str(i) not in ids]
    actuels = []
    if len(ids) == len(valeurs):
        for mid in ids:
            m = _discord("GET", f"/channels/{salon}/messages/{mid}")
            if m is None:
                actuels = None
                break
            actuels.append(m.get("content") or "")
    else:
        actuels = None
    maintenant = time.time()
    if actuels is not None:
        changes = 0
        for mid, avant, v in zip(ids, actuels, valeurs):
            if avant != v:
                # flags : l'aperçu reste coupé (Discord ouvrirait le lien de rotation)
                _discord("PATCH", f"/channels/{salon}/messages/{mid}",
                         {"content": v, "allowed_mentions": {"parse": []}, "flags": 1 << 2})
                changes += 1
        fiche.update(service=sid, verifie_le=maintenant)
        if changes:
            fiche["modifie_le"] = maintenant
        etat["salons"][salon] = fiche
        return f"{changes} message(s) édité(s)" if changes else "à jour"
    nouveaux = []
    for v in valeurs:
        m = _discord("POST", f"/channels/{salon}/messages",
                     {"content": v, "allowed_mentions": {"parse": []}, "flags": _DRAPEAUX})
        if not m or not m.get("id"):
            raise Erreur("Discord n'a pas rendu le message posté")
        nouveaux.append(str(m["id"]))
        # retenu message par message : un arrêt au troisième fait reposer le
        # jeu au tour suivant et effacer ces deux-là, pas les laisser en double
        etat["salons"][salon] = {"service": sid, "messages": nouveaux, "poste_le": maintenant,
                                 "verifie_le": maintenant, "anciens": ids + restes}
        _sauver(etat)
    for mid in ids + restes:
        try:
            _discord("DELETE", f"/channels/{salon}/messages/{mid}")
        except Erreur as e:
            print(f"[proxeasy] ancien message {mid} non effacé : {e}", flush=True)
    etat["salons"][salon].pop("anciens", None)
    return "posté"


# ── Le relevé ───────────────────────────────────────────────────────────────

def synchroniser() -> dict:
    """Un tour : liste les proxys chez ProxEasy et les salons « proxyeasy-N-pe-XXXX »,
    puis tient les logins des salons actifs (mode essai : le premier salon,
    mode tous : chacun). En mode arrêt, lecture seule : rien n'est écrit sur
    Discord. Rend le bilan, gardé pour la page."""
    if not _VERROU.acquire(blocking=False):
        return {"erreur": "un relevé est déjà en cours"}
    try:
        return _synchroniser()
    finally:
        _VERROU.release()


def _synchroniser() -> dict:
    d = _charger()
    mode = d["mode"]
    ecrire = mode in ("essai", "tous")
    bilan = {"le": time.time(), "mode": mode, "salons": [], "erreur": ""}
    d["bilan"] = bilan
    k = cle()
    if not k:
        bilan["erreur"] = "aucune clé ProxEasy enregistrée"
        _sauver(d)
        return bilan
    try:
        servs = {}
        for s in services(k):
            try:
                servs[int(s.get("id"))] = s
            except (TypeError, ValueError):
                continue
        if not (_fiche_cle().get("test") or {}).get("ok"):
            noter_test(True, f"{sum(_lisible(s) for s in servs.values())} proxy(s) actif(s) lisibles.")
        if ecrire:
            _lever(d, "cle", "✅ La clé ProxEasy répond de nouveau : les logins des salons proxy sont suivis.")
    except Erreur as e:
        bilan["erreur"] = f"ProxEasy : {e}"
        noter_test(False, str(e))
        if ecrire and e.statut in (401, 403):
            _alerter(d, "cle", f"⚠️ ProxEasy refuse la clé API ({e}) : les logins des salons proxy ne "
                               "sont plus mis à jour. Recolle-la sur youl4b.com › Settings › "
                               "Intégrations › Clé ProxEasy.")
        _sauver(d)
        return bilan
    try:
        _parcourir(d, bilan, servs, k)
    except Erreur as e:
        bilan["erreur"] = f"Discord : {e}"
        print(f"[proxeasy] relevé interrompu : {e}", flush=True)
    _sauver(d)
    return bilan


def _parcourir(d: dict, bilan: dict, servs: dict, k: str) -> None:
    mode = d["mode"]
    ecrire = mode in ("essai", "tous")
    roles = {str(r.get("id")): r for r in _discord("GET", f"/guilds/{SERVEUR}/roles") or []}
    salons = []
    for c in _discord("GET", f"/guilds/{SERVEUR}/channels") or []:
        m = MOTIF.search(str(c.get("name") or "")) if c.get("type") == 0 else None
        if m:
            salons.append((int(m.group(1)), int(m.group(2)), c))
    salons.sort(key=lambda t: (t[0], t[1]))
    if salons and (mode != "essai" or d.get("essai") not in {c["id"] for _, _, c in salons}):
        d["essai"] = salons[0][2]["id"]
    membres = d.setdefault("membres", {})
    for n, sid, c in salons:
        cid = str(c["id"])
        ligne = {"salon": cid, "nom": c.get("name"), "n": n, "service": sid,
                 "poste": bool((d["salons"].get(cid) or {}).get("messages"))}
        bilan["salons"].append(ligne)
        ouvert, ligne["voient"] = _visibilite(c, roles, lambda uid: _nom_membre(uid, membres))
        s = servs.get(sid)
        ligne["statut"] = str(s.get("status")) if s else "introuvable"
        ligne["echeance"] = (s or {}).get("next_due_date")
        if s is None:
            probleme = "introuvable chez ProxEasy"
        elif s.get("status") != "active":
            probleme = f"« {s.get('status')} » chez ProxEasy (expiré ou résilié)"
        elif not _lisible(s):
            probleme = "identifiants non lisibles par l'API ProxEasy"
        else:
            probleme = ""
        if ouvert:
            ligne["probleme"] = "visible de tout le serveur : rien n'y est posté"
            if ecrire:
                _alerter(d, f"ouvert:{cid}", f"⚠️ <#{cid}> est visible de tout le serveur : les logins "
                                             f"de pe-{sid} n'y sont pas postés.")
            continue
        if ecrire:
            _lever(d, f"ouvert:{cid}")
        if probleme:
            ligne["probleme"] = probleme
            if ecrire:
                _alerter(d, f"proxy:{cid}", f"⚠️ <#{cid}> : le proxy pe-{sid} est {probleme}. Les logins "
                                            "du salon ne sont plus mis à jour.")
            continue
        actif = mode == "tous" or (mode == "essai" and cid == d.get("essai"))
        ligne["actif"] = actif
        if not actif:
            continue
        try:
            valeurs = identifiants(sid, k)
            lien = rotation(d, sid)
            if lien:
                valeurs.append(lien)
            if not all(valeurs) or any(len(v) > 2000 for v in valeurs):
                raise Erreur("une valeur des identifiants est vide ou trop longue")
            ligne["action"] = _tenir(d, cid, sid, valeurs)
            ligne["poste"] = True
            _lever(d, f"proxy:{cid}", f"✅ <#{cid}> : pe-{sid} de nouveau lisible chez ProxEasy, logins à jour.")
        except Erreur as e:
            ligne["probleme"] = str(e)
            if 0 <= e.statut < 500 and e.statut != 429:
                _alerter(d, f"proxy:{cid}", f"⚠️ <#{cid}> : logins de pe-{sid} non tenus ({e}). "
                                            "Ils ne sont plus mis à jour.")
        _sauver(d)
    # un salon renommé ou supprimé ne garde pas son alerte ouverte pour toujours
    presents = {str(c["id"]) for _, _, c in salons}
    for cle_a in [a for a in d["alertes"] if ":" in a and a.split(":", 1)[1] not in presents]:
        d["alertes"].pop(cle_a, None)
    faits = [l for l in bilan["salons"] if l.get("action")]
    print(f"[proxeasy] relevé ({mode}) : {len(salons)} salon(s), {len(faits)} tenu(s) — "
          + ", ".join(f"pe-{l['service']} {l['action']}" for l in faits), flush=True)


def lancer() -> None:
    """Un relevé tout de suite, en fond (après un enregistrement ou un clic)."""
    def tour():
        try:
            synchroniser()
        except Exception as e:                               # noqa: BLE001
            print(f"[proxeasy] relevé : {type(e).__name__}", flush=True)
    threading.Thread(target=tour, daemon=True, name="proxeasy-maintenant").start()


def demarrer() -> bool:
    """Le relevé toutes les dix minutes, dans son fil (create_app, machine de
    production seulement). Une fois par processus."""
    global _DEMARRE
    if _DEMARRE:
        return False
    _DEMARRE = True

    def boucle():
        time.sleep(60)                       # laisse le bot se connecter
        while True:
            try:
                synchroniser()
            except Exception as e:                           # noqa: BLE001
                # le type seul : un message d'exception peut citer une réponse
                print(f"[proxeasy] relevé : {type(e).__name__}", flush=True)
            time.sleep(PERIODE_S)

    threading.Thread(target=boucle, daemon=True, name="proxeasy-salons").start()
    return True


# ── La page (Settings › Intégrations › Clé ProxEasy) ────────────────────────

def _boite(fond, bord, couleur, texte):
    return ("<div style='padding:12px 16px;background:%s;border:1px solid %s;"
            "border-radius:8px;margin-bottom:14px;font-size:13px;color:%s'>%s</div>"
            % (fond, bord, couleur, texte))


def _date(ts) -> str:
    # le VPS est en UTC ; le propriétaire lit l'heure de Paris
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        return datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def panneau_html() -> str:
    e = html.escape
    ck = etat_cle()
    test = ck["test"]
    if not ck["presente"]:
        h = _boite("rgba(148,163,184,.08)", "rgba(148,163,184,.25)", "#94a3b8",
                   "Aucune clé : les logins des salons proxy ne sont pas tenus.")
    elif test and not test.get("ok"):
        h = _boite("rgba(239,68,68,.08)", "rgba(239,68,68,.35)", "#f87171",
                   f"✕ Clé enregistrée (se termine par …{e(ck['fin'])}), mais ProxEasy a répondu : "
                   f"{e(str(test.get('texte') or ''))} — {e(_date(test.get('le')))}")
    else:
        h = _boite("rgba(16,185,129,.08)", "rgba(16,185,129,.3)", "#34d399",
                   f"✓ Clé enregistrée, se termine par …{e(ck['fin'])} — le {e(_date(ck['le']))}"
                   + (f" par {e(ck['par'])}" if ck["par"] else "")
                   + (f". Dernier test : {e(str(test.get('texte') or '').rstrip('.'))}" if test else "")
                   + ". Colle une nouvelle clé ci-dessous pour la remplacer.")
    champ = ("font-size:11px;color:#888;font-weight:600;text-transform:uppercase;letter-spacing:.05em")
    h += ("<form method='POST' action='/settings/proxeasy/cle' style='display:flex;flex-direction:column;gap:8px'>"
          f"<label style='{champ}'>Clé API REST ProxEasy</label>"
          "<input type='password' name='cle' autocomplete='off' spellcheck='false' required minlength='20' "
          "placeholder='onglet « Application ou script (API REST) »' style='font-family:monospace;font-size:12px'>"
          "<button type='submit' style='width:100%;margin-top:8px'>Enregistrer la clé</button>"
          "</form>")
    if ck["presente"]:
        h += ("<form method='POST' action='/settings/proxeasy/tester' style='margin-top:8px'>"
              "<button type='submit' style='width:100%'>Tester</button></form>")
    d = _charger()
    mode = d.get("mode")
    b = d.get("bilan") or {}
    h += "<h4 style='margin:22px 0 6px'>Logins dans les salons proxy (Youl4b Spam)</h4>"
    h += ("<small style='color:#888;display:block;margin-bottom:10px'>Ryuk poste dans chaque salon "
          "« proxyeasy-N-pe-XXXX » un message par valeur : hôte, port SOCKS5, utilisateur, mot de passe, "
          "puis le lien de rotation s'il est connu — l'appui long copie une seule valeur. Relu toutes les 10 min : "
          "un identifiant changé chez ProxEasy est édité en place ; un proxy introuvable ou expiré "
          "est dit dans suivi-proxy.</small>")
    libelle = {"arret": "arrêté (lecture seule, rien n'est posté)",
               "essai": "essai dans le premier salon seulement",
               "tous": "tous les salons"}.get(mode, mode)
    h += f"<div style='font-size:13px;margin-bottom:8px'>Envois : <b>{e(libelle)}</b>"
    if b.get("le"):
        h += f" · dernier relevé le {e(_date(b['le']))}"
    h += "</div>"
    if b.get("erreur"):
        h += _boite("rgba(239,68,68,.08)", "rgba(239,68,68,.35)", "#f87171", "✕ " + e(b["erreur"]))
    lignes = b.get("salons") or []
    if lignes:
        h += ("<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:12px'>"
              "<tr style='text-align:left;color:#888'><th style='padding:6px'>Salon</th>"
              "<th style='padding:6px'>ProxEasy</th><th style='padding:6px'>Qui voit</th>"
              "<th style='padding:6px'>Logins</th></tr>")
        for l in lignes:
            statut = str(l.get("statut") or "")
            if l.get("echeance") and statut == "active":
                statut += f" · échéance {l['echeance']}"
            if l.get("probleme"):
                logins = "⚠️ " + str(l["probleme"])
            elif l.get("action"):
                logins = "✓ " + str(l["action"])
            elif l.get("poste"):
                logins = "postés (pas tenus en ce moment)"
            else:
                logins = "pas encore postés"
            h += ("<tr style='border-top:1px solid rgba(148,163,184,.2)'>"
                  f"<td style='padding:6px'>{e(str(l.get('nom') or ''))}</td>"
                  f"<td style='padding:6px'>pe-{e(str(l.get('service')))} · {e(statut)}</td>"
                  f"<td style='padding:6px'>{e(', '.join(l.get('voient') or []))}</td>"
                  f"<td style='padding:6px'>{e(logins)}</td></tr>")
        h += "</table></div>"
    elif ck["presente"]:
        h += "<small style='color:#888'>Pas encore de relevé : clique « Relire maintenant ».</small>"
    if ck["presente"]:
        boutons = [("maintenant", "Relire maintenant")]
        if mode == "arret":
            boutons.append(("essai", "Poster dans le premier salon (essai)"))
        if mode == "essai":
            boutons.append(("tous", "Poster dans tous les salons"))
        if mode in ("essai", "tous"):
            boutons.append(("arret", "Arrêter les envois"))
        h += "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:12px'>"
        for valeur, texte in boutons:
            h += ("<form method='POST' action='/settings/proxeasy/salons' style='flex:1;min-width:180px'>"
                  f"<input type='hidden' name='mode' value='{valeur}'>"
                  f"<button type='submit' style='width:100%'>{e(texte)}</button></form>")
        h += "</div>"
    h += ("<details style='font-size:12px;color:#888;margin-top:14px'>"
          "<summary style='cursor:pointer;color:#3b82f6;font-weight:600'>Où trouver la clé ?</summary>"
          "<ol style='margin:8px 0 0 18px;line-height:1.7'>"
          "<li>Espace client ProxEasy › connexions API</li>"
          "<li>Onglet <b>Application ou script (API REST)</b> (pas « Assistant IA (MCP) »)</li>"
          "<li>Crée la clé avec la lecture des services et des identifiants, copie-la, colle-la ici</li>"
          "</ol>"
          "<p style='margin-top:8px;color:#666'>Elle n'est jamais réaffichée : seuls ses quatre derniers "
          "caractères le sont, pour la reconnaître.</p></details>")
    return h
