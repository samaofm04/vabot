"""verif_discord.py — Verification anti-fraude a l'entree du serveur Discord
« YouLab - Entretien (Réglement) », via le bot SEVEN.

LE PARCOURS
  1. Un nouveau ne voit qu'un salon, #🔐┃vérification, avec le bouton
     « Se vérifier ». Le reste du serveur (salons ET liste des membres) est
     reserve au role ✅ Vérifié.
  2. Le clic arrive ici par HTTP (Interactions Endpoint de l'application :
     pas de processus bot a faire tourner). On repond, en message visible
     par lui seul, un lien PERSONNEL signe, valable 15 minutes, a usage
     unique : /verif/<jeton>.
  3. Discord ne donne JAMAIS l'IP d'un membre a un bot : c'est la page web
     qui la voit. Elle releve aussi une empreinte de l'appareil.
  4. Decision (decider) :
       - IP hors Bénin / Madagascar, ou VPN / proxy / hebergeur  -> BLOQUE,
         role 🚩 Suspect, alerte « fraude » dans #🚩┃suspicions ;
       - meme appareil qu'un autre compte                        -> EN ATTENTE,
         role ⏳ En attente, alerte avec boutons Accepter / Refuser
         pour un manager dans #⏳┃en-attente ;
       - fuseau horaire du telephone incoherent (Europe/Paris
         derriere une IP beninoise : VPN non detecte)            -> EN ATTENTE ;
       - deja bloque, en attente ou refuse une fois               -> EN ATTENTE
         (sinon il suffirait de recommencer jusqu'a passer) ;
       - sinon                                                   -> OK, role
         ✅ Vérifié pose, bienvenue dans #bienvenue (il est mentionne), et
         une ligne dans #✅┃entrées (avec l'IP) pour le staff.

POURQUOI L'IP SEULE NE FAIT PAS UN DOUBLE COMPTE
  Au Bénin et a Madagascar, beaucoup de gens sortent sur Internet par la
  meme IP (reseau mobile, cybercafe). Bloquer sur l'IP refuserait de vrais
  VA. Le double compte se juge sur l'APPAREIL : l'identifiant garde dans
  le navigateur, ou l'empreinte technique ET la meme IP ensemble.
  L'empreinte seule ne suffit pas : deux Tecno du meme modele, meme
  version de Chrome, donnent la meme ; elle est seulement signalee, comme
  l'IP partagee.

DONNEES
  data/verif_membres.json : une fiche par membre (IP, pays, FAI, VPN,
  fuseau, empreinte). Purgee au-dela de 90 jours. La page previent le
  membre avant de relever quoi que ce soit.

Aucun secret dans ce fichier : les identifiants Discord et la cle PUBLIQUE
de l'application ne sont pas des secrets. Le token du bot est lu dans
SEVEN_BOT_TOKEN ou data/seven_bot_token ; la cle de signature des liens est
creee au premier usage dans data/verif_secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

import safe_json

# ─── Configuration (identifiants Discord, pas des secrets) ────────────────
APP_ID = "1552153790701117480"
CLE_PUBLIQUE_APP = "77740f51e42a72067e175348c5e58e1ef4fad20a9f2b4074884cb38b46076d77"  # verify_key (publique)
GUILD_ID = "1552152470464110703"
ROLE_VERIFIE = "1552167021037490306"      # ✅ Vérifié
ROLE_MANAGER = "1552167022324879422"      # 🛡️ Manager
ROLE_ATTENTE = "1552170116685504515"      # ⏳ En attente
ROLE_SUSPECT = "1552170118140919889"      # 🚩 Suspect
SALON_ALERTES = "1552167029253869610"     # ✅┃entrées : chaque entree reussie, avec son IP
SALON_ATTENTE = "1552170120632205314"     # ⏳┃en-attente : a valider par un manager
SALON_SUSPICIONS = "1552170122288963648"  # 🚩┃suspicions : alertes fraude
SALON_BIENVENUE = "1552152471281860611"
SALONS_ETAPES = {"info": "1552159098600955924", "explication": "1552159099796328478",
                 "commencement": "1552159101763461193", "instagram": "1552159912849580136",
                 "threads": "1552159910454624296", "twitter": "1552159110244470825"}
SITE = "https://youl4b.com"

PAYS_AUTORISES = {"BJ": "Bénin", "MG": "Madagascar"}
# Fuseaux attendus pour ces deux pays. Un telephone beninois peut annoncer
# Africa/Lagos (meme heure, reglage Android courant).
FUSEAUX_ATTENDUS = {
    "BJ": {"Africa/Porto-Novo", "Africa/Lagos", "Africa/Cotonou"},
    "MG": {"Indian/Antananarivo", "Africa/Nairobi", "Africa/Addis_Ababa"},
}
DUREE_LIEN_S = 15 * 60
DELAI_MIN_PAGE_S = 3          # un humain met plus de 3 s a cliquer ; un script non
ESSAIS_MAX_24H = 3            # au-dela, chaque essai rate reposterait une alerte
CONSERVATION_S = 90 * 86400

API = "https://discord.com/api/v10"
DATA_DIR = Path(__file__).resolve().parent / "data"
FICHES = DATA_DIR / "verif_membres.json"
SECRET_FILE = DATA_DIR / "verif_secret"
_VERROU = threading.Lock()
_EN_COURS: set = set()        # jetons en cours de verification (la geolocalisation prend du temps)

# Plages IP de Cloudflare (publiees sur cloudflare.com/ips). Sert a savoir si
# l'en-tete CF-Connecting-IP vient VRAIMENT de Cloudflare : un visiteur qui
# attaque le serveur en direct peut ecrire cet en-tete lui-meme.
_CLOUDFLARE = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32")]


def _charger_config():
    """Les identifiants poses par la mise en place (data/verif_config.json)
    completent ceux du code : on peut relancer la mise en place sans
    redeployer."""
    global CLE_PUBLIQUE_APP, ROLE_VERIFIE, ROLE_MANAGER, SALON_ALERTES, SALON_ATTENTE, SALON_SUSPICIONS
    try:
        c = safe_json.load(DATA_DIR / "verif_config.json", default={}) or {}
    except Exception:
        c = {}
    CLE_PUBLIQUE_APP = c.get("cle_publique") or CLE_PUBLIQUE_APP
    ROLE_VERIFIE = c.get("role_verifie") or ROLE_VERIFIE
    ROLE_MANAGER = c.get("role_manager") or ROLE_MANAGER
    SALON_ALERTES = c.get("salon_alertes") or SALON_ALERTES
    SALON_ATTENTE = c.get("salon_attente") or SALON_ATTENTE
    SALON_SUSPICIONS = c.get("salon_suspicions") or SALON_SUSPICIONS


# ─── Discord REST (token du bot SEVEN) ────────────────────────────────────
def _token() -> str:
    t = (os.environ.get("SEVEN_BOT_TOKEN") or "").strip()
    if t:
        return t
    try:
        return (DATA_DIR / "seven_bot_token").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def configure() -> bool:
    _charger_config()
    return bool(_token() and CLE_PUBLIQUE_APP and ROLE_VERIFIE and SALON_ALERTES)


def api(methode: str, chemin: str, **kw) -> Tuple[int, Any]:
    tok = _token()
    if not tok:
        return 0, {"message": "token du bot SEVEN absent"}
    h = {"Authorization": f"Bot {tok}", "User-Agent": "DiscordBot (youl4b-verif, 1.0)"}
    for _ in range(4):
        try:
            r = requests.request(methode, API + chemin, headers=h, timeout=20, **kw)
        except Exception as e:
            return 0, {"message": str(e)[:200]}
        if r.status_code == 429:
            try:
                time.sleep(min(10.0, float(r.json().get("retry_after", 1)) + 0.2))
            except Exception:
                time.sleep(1)
            continue
        try:
            corps = r.json() if r.text else {}
        except Exception:
            corps = {"message": r.text[:200]}
        return r.status_code, corps
    return 429, {"message": "limite Discord"}


# ─── Signature des interactions (Ed25519) ─────────────────────────────────
def signature_valide(corps: bytes, signature_hex: str, horodatage: str,
                     cle_publique_hex: Optional[str] = None) -> bool:
    """Discord signe chaque interaction : sans cette verification, n'importe
    qui pourrait appeler l'URL et se faire donner le role Vérifié."""
    cle = cle_publique_hex or CLE_PUBLIQUE_APP
    if not (cle and signature_hex and horodatage):
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(cle)).verify(
            bytes.fromhex(signature_hex), horodatage.encode() + corps)
        return True
    except Exception:
        return False


# ─── Liens personnels signes ──────────────────────────────────────────────
def _secret() -> bytes:
    try:
        s = SECRET_FILE.read_bytes()
        if len(s) >= 32:
            return s
    except Exception:
        pass
    s = secrets.token_bytes(48)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SECRET_FILE.with_suffix(".tmp")
    tmp.write_bytes(s)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SECRET_FILE)
    return s


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def creer_jeton(user_id: str, maintenant: Optional[float] = None) -> str:
    t = int(maintenant if maintenant is not None else time.time())
    charge = f"{user_id}.{t + DUREE_LIEN_S}.{secrets.token_hex(8)}".encode()
    sig = hmac.new(_secret(), charge, hashlib.sha256).digest()[:20]
    return _b64(charge) + "." + _b64(sig)


def lire_jeton(jeton: str, maintenant: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """{user_id, expire, nonce} si le jeton est authentique et pas expire."""
    try:
        a, b = jeton.split(".", 1)
        charge, sig = _unb64(a), _unb64(b)
        attendu = hmac.new(_secret(), charge, hashlib.sha256).digest()[:20]
        if not hmac.compare_digest(sig, attendu):
            return None
        uid, exp, nonce = charge.decode().split(".")
        if not uid.isdigit():
            return None
        if int(exp) < int(maintenant if maintenant is not None else time.time()):
            return None
        return {"user_id": uid, "expire": int(exp), "nonce": nonce}
    except Exception:
        return None


# ─── IP du visiteur ───────────────────────────────────────────────────────
def _est_cloudflare(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return any(a in n for n in _CLOUDFLARE)
    except Exception:
        return False


def ip_du_visiteur(entetes, adresse_directe: str) -> Tuple[str, bool]:
    """(ip, garantie).

    Le site est derriere Cloudflare : l'IP reelle est CF-Connecting-IP. Mais
    le port 80 du serveur repond aussi en direct, et la un visiteur peut
    ecrire CF-Connecting-IP lui-meme. On ne la dit GARANTIE que si nginx
    atteste (X-Real-IP, qu'il ecrase toujours) que la connexion venait
    d'une adresse Cloudflare. Sans cette attestation — nginx ne la pose pas
    encore sur « location / » — l'IP est utilisee mais signalee « non
    garantie » dans l'alerte."""
    cf = (entetes.get("CF-Connecting-IP") or "").strip()
    pair = (entetes.get("X-Real-IP") or "").strip()
    if cf:
        try:
            ipaddress.ip_address(cf)
        except Exception:
            cf = ""
    if cf and pair and _est_cloudflare(pair):
        return cf, True
    if cf:
        return cf, False
    return (adresse_directe or "").strip() or "?", False


# ─── Pays, VPN, FAI ───────────────────────────────────────────────────────
def infos_ip(ip: str) -> Dict[str, Any]:
    """{ok, pays, pays_nom, fai, vpn, type, source, erreur}.

    proxycheck.io d'abord (detecte VPN / proxy / hebergeur, 100 requetes
    par jour sans compte : une entree dure une fois par personne), ip-api.com
    en secours. Les deux en panne : ok=False, et la decision passe au
    manager plutot que d'ouvrir ou de fermer a l'aveugle."""
    try:
        r = requests.get(f"https://proxycheck.io/v2/{ip}", params={"vpn": 3, "asn": 1}, timeout=10)
        d = (r.json() or {}).get(ip) or {}
        if d.get("isocode"):
            return {"ok": True, "pays": d.get("isocode", "").upper(), "pays_nom": d.get("country", ""),
                    "fai": d.get("organisation") or d.get("provider") or "",
                    "vpn": str(d.get("proxy", "no")).lower() == "yes" or str(d.get("vpn", "no")).lower() == "yes",
                    "type": d.get("type", ""), "source": "proxycheck.io"}
    except Exception:
        pass
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}",
                         params={"fields": "status,countryCode,country,isp,proxy,hosting,mobile"}, timeout=10)
        d = r.json() or {}
        if d.get("status") == "success":
            return {"ok": True, "pays": (d.get("countryCode") or "").upper(), "pays_nom": d.get("country", ""),
                    "fai": d.get("isp", ""), "vpn": bool(d.get("proxy") or d.get("hosting")),
                    "type": "hébergeur" if d.get("hosting") else ("mobile" if d.get("mobile") else ""),
                    "source": "ip-api.com"}
    except Exception:
        pass
    return {"ok": False, "erreur": "pays de l'IP introuvable (services de géolocalisation muets)"}


# ─── Fiches ───────────────────────────────────────────────────────────────
def _fiches() -> Dict[str, Any]:
    try:
        d = safe_json.load(FICHES, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ecrire_fiches(d: Dict[str, Any]):
    limite = time.time() - CONSERVATION_S
    d = {k: v for k, v in d.items() if float((v or {}).get("ts") or 0) >= limite}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_json.write_text(FICHES, json.dumps(d, ensure_ascii=False, indent=1))


def age_compte_jours(user_id: str) -> float:
    """Les identifiants Discord portent leur date de creation."""
    try:
        ms = (int(user_id) >> 22) + 1420070400000
        return round((time.time() * 1000 - ms) / 86400000, 1)
    except Exception:
        return -1.0


def empreinte(donnees: Dict[str, Any]) -> str:
    """Hachage stable des caracteristiques de l'appareil (pas de l'IP)."""
    parts = [str(donnees.get(k) or "") for k in
             ("canvas", "webgl", "ecran", "plateforme", "coeurs", "memoire", "fuseau", "langues", "ua")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def _hash_ip(ip: str) -> str:
    return hmac.new(_secret(), ip.encode(), hashlib.sha256).hexdigest()[:20]


# ─── Decision ─────────────────────────────────────────────────────────────
_ETAT_LISIBLE = {"bloque": "bloqué", "attente": "en attente", "refuse": "refusé", "banni": "banni", "ok": "vérifié"}


def decider(fiche: Dict[str, Any], autres: Dict[str, Any]) -> Dict[str, Any]:
    """{etat: ok|attente|bloque, raisons:[...], meme_appareil:[ids], meme_ip:[ids]}.

    Pure (aucun appel reseau) : c'est elle que les tests eprouvent."""
    raisons, etat = [], "ok"
    uid = fiche.get("user_id")
    # Tous les etats comptent : un compte refuse ou banni qui revient sous
    # un autre nom avec le meme telephone est exactement ce qu'on cherche.
    meme_ip = sorted({k for k, v in autres.items() if k != uid and fiche.get("ip_hash")
                      and v.get("ip_hash") == fiche.get("ip_hash")})
    meme_empreinte = sorted({k for k, v in autres.items() if k != uid and fiche.get("empreinte")
                             and v.get("empreinte") == fiche.get("empreinte")})
    meme_appareil = sorted({k for k, v in autres.items() if k != uid
                            and fiche.get("appareil") and v.get("appareil") == fiche.get("appareil")}
                           | (set(meme_empreinte) & set(meme_ip)))
    precedent = (autres.get(uid) or {}).get("etat") if uid else None
    if not fiche.get("ip_ok"):
        etat = "attente"
        raisons.append(fiche.get("ip_erreur") or "pays de l'IP inconnu")
    else:
        if fiche.get("pays") not in PAYS_AUTORISES:
            etat = "bloque"
            raisons.append(f"IP hors Bénin/Madagascar : {fiche.get('pays_nom') or fiche.get('pays') or '?'}")
        if fiche.get("vpn"):
            etat = "bloque"
            raisons.append(f"VPN / proxy / hébergeur détecté ({fiche.get('type') or 'masquage'})")
    if fiche.get("hors_cloudflare"):
        # le site passe toujours par Cloudflare : une requete qui arrive sans
        # a vise le serveur en direct, la ou les en-tetes IP s'inventent
        etat = "bloque" if etat == "bloque" else "attente"
        raisons.append("connexion arrivée hors Cloudflare (IP peut-être falsifiée)")
    if etat != "bloque":
        if meme_appareil:
            etat = "attente"
            raisons.append("même appareil qu'un autre compte")
        if precedent in ("bloque", "attente", "refuse", "banni"):
            etat = "attente"
            raisons.append(f"nouvel essai après un précédent « {_ETAT_LISIBLE.get(precedent, precedent)} »")
        fz = fiche.get("fuseau") or ""
        if fiche.get("pays") in FUSEAUX_ATTENDUS and fz and fz not in FUSEAUX_ATTENDUS[fiche["pays"]]:
            etat = "attente"
            raisons.append(f"fuseau du téléphone incohérent : {fz} pour une IP {PAYS_AUTORISES.get(fiche['pays'])}")
        if fiche.get("ip_garantie") is False and fiche.get("pays") in PAYS_AUTORISES and etat == "ok":
            # IP non attestee par Cloudflare : on ne la bloque pas, on la signale
            raisons.append("IP non garantie (connexion hors Cloudflare)")
    return {"etat": etat, "raisons": raisons, "meme_appareil": meme_appareil, "meme_ip": meme_ip,
            "meme_empreinte": [k for k in meme_empreinte if k not in meme_appareil]}


# ─── Alertes staff ────────────────────────────────────────────────────────
_COULEUR = {"ok": 0x57F287, "attente": 0xF59E0B, "bloque": 0xED4245}
_TITRE = {"ok": "✅ Entrée vérifiée", "attente": "⏳ En attente d'un manager", "bloque": "🚨 Alerte fraude — accès bloqué"}


def embed_alerte(fiche: Dict[str, Any], d: Dict[str, Any]) -> Dict[str, Any]:
    uid = fiche["user_id"]
    lignes_liens = []
    if d.get("meme_appareil"):
        lignes_liens.append("📱 Même appareil que : " + ", ".join(f"<@{x}>" for x in d["meme_appareil"][:10]))
    if d.get("meme_empreinte"):
        lignes_liens.append("🧬 Même modèle de téléphone / navigateur que : "
                            + ", ".join(f"<@{x}>" for x in d["meme_empreinte"][:10])
                            + " *(peut être une coïncidence)*")
    if d.get("meme_ip"):
        lignes_liens.append("🌐 Même IP que : " + ", ".join(f"<@{x}>" for x in d["meme_ip"][:10])
                            + " *(souvent normal : réseau mobile / cybercafé partagé)*")
    champs = [
        {"name": "Membre", "value": f"<@{uid}> · `{fiche.get('pseudo', '?')}`\nCompte créé il y a **{fiche.get('age_compte', '?')} j**", "inline": True},
        {"name": "IP", "value": f"`{fiche.get('ip', '?')}`" + ("" if fiche.get("ip_garantie") else " ⚠️ non garantie"), "inline": True},
        {"name": "Pays / FAI", "value": f"{fiche.get('pays_nom') or fiche.get('pays') or '?'} · {fiche.get('fai') or '?'}", "inline": True},
        {"name": "VPN / proxy", "value": ("oui — " + (fiche.get("type") or "")) if fiche.get("vpn") else "non", "inline": True},
        {"name": "Téléphone", "value": f"fuseau `{fiche.get('fuseau') or '?'}` · langue `{fiche.get('langue') or '?'}`", "inline": True},
        {"name": "Appareil", "value": f"`{(fiche.get('empreinte') or '?')[:12]}`", "inline": True},
    ]
    if d.get("raisons"):
        champs.append({"name": "Pourquoi", "value": "\n".join("• " + r for r in d["raisons"])[:1000], "inline": False})
    if lignes_liens:
        champs.append({"name": "Liens avec d'autres comptes", "value": "\n".join(lignes_liens)[:1000], "inline": False})
    return {"title": _TITRE[d["etat"]], "color": _COULEUR[d["etat"]], "fields": champs,
            "footer": {"text": "YouLab • Vérification"}, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def boutons_manager(uid: str) -> List[Dict[str, Any]]:
    return [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Accepter", "emoji": {"name": "✅"}, "custom_id": f"verif:ok:{uid}"},
        {"type": 2, "style": 4, "label": "Refuser (expulser)", "emoji": {"name": "⛔"}, "custom_id": f"verif:kick:{uid}"},
        {"type": 2, "style": 2, "label": "Bannir", "emoji": {"name": "🔨"}, "custom_id": f"verif:ban:{uid}"},
    ]}]


def _salon_alerte(etat: str) -> str:
    return {"attente": SALON_ATTENTE, "bloque": SALON_SUSPICIONS}.get(etat) or SALON_ALERTES


def _poster_alerte(fiche, d) -> str:
    salon = _salon_alerte(d["etat"])
    if not salon:
        return ""
    corps = {"embeds": [embed_alerte(fiche, d)], "allowed_mentions": {"parse": []}}
    if d["etat"] in ("attente", "bloque"):
        corps["components"] = boutons_manager(fiche["user_id"])
    code, rep = api("POST", f"/channels/{salon}/messages", json=corps)
    return str(rep.get("id") or "") if code == 200 else ""


def _role(methode: str, uid: str, role: str) -> bool:
    if not role:
        return False
    code, _ = api(methode, f"/guilds/{GUILD_ID}/members/{uid}/roles/{role}")
    return code in (200, 204)


def donner_role(uid: str) -> bool:
    return _role("PUT", uid, ROLE_VERIFIE)


def ouvrir(uid: str) -> bool:
    """Role Vérifié, retire En attente / Suspect, et bienvenue publique."""
    ok = donner_role(uid)
    if ok:
        _role("DELETE", uid, ROLE_ATTENTE)
        _role("DELETE", uid, ROLE_SUSPECT)
        poster_bienvenue(uid)
    return ok


def poster_bienvenue(uid: str) -> str:
    """Le nouveau est MENTIONNE : Discord le notifie et l'amene dans
    #bienvenue, avec les etapes et le choix de sa plateforme."""
    if not SALON_BIENVENUE:
        return ""
    s = SALONS_ETAPES
    e = {"title": "👋 Bienvenue dans l'agence YouLab !", "color": 0x5865F2,
         "description": (f"<@{uid}> vient d'arriver — vérifié ✅\n\n"
                         "**📋 Par où commencer :**\n"
                         f"1️⃣ Comment tu es payé 👉 <#{s['info']}>\n"
                         f"2️⃣ L'organisation 👉 <#{s['explication']}>\n"
                         f"3️⃣ L'entretien 👉 <#{s['commencement']}>\n\n"
                         "**📱 Choisis ta plateforme :**\n"
                         f"📸 Instagram 👉 <#{s['instagram']}>\n"
                         f"🧵 Threads 👉 <#{s['threads']}>\n"
                         f"🐦 Twitter (X) 👉 <#{s['twitter']}>"),
         "footer": {"text": "YouLab • Bienvenue dans l'équipe !"}}
    code, rep = api("POST", f"/channels/{SALON_BIENVENUE}/messages",
                    json={"content": f"<@{uid}>", "embeds": [e], "allowed_mentions": {"users": [uid]}})
    return str(rep.get("id") or "") if code == 200 else ""


# ─── La verification elle-meme (appelee par la page) ─────────────────────
def verifier(jeton: str, donnees: Dict[str, Any], ip: str, ip_garantie: bool,
             maintenant: Optional[float] = None, hors_cloudflare: bool = False) -> Dict[str, Any]:
    """Rend {etat, message} pour la page. Ecrit la fiche, pose le role ou
    l'alerte. Le jeton ne sert qu'une fois."""
    _charger_config()
    j = lire_jeton(jeton, maintenant)
    if not j:
        return {"etat": "erreur", "message": "Lien expiré ou invalide. Retourne sur Discord et clique à nouveau « Se vérifier »."}
    t0 = float(donnees.get("t0") or 0)
    now = maintenant if maintenant is not None else time.time()
    if donnees.get("site_web"):          # champ piege : un humain ne le voit pas
        return {"etat": "erreur", "message": "Vérification refusée."}
    if t0 and now - t0 < DELAI_MIN_PAGE_S:
        return {"etat": "erreur", "message": "Trop rapide. Recharge la page et réessaie."}
    uid, nonce = j["user_id"], j["nonce"]
    with _VERROU:
        deja = _fiches().get(uid) or {}
        if nonce in (deja.get("jetons_utilises") or []) or nonce in _EN_COURS:
            return {"etat": "erreur", "message": "Ce lien a déjà servi. Clique à nouveau « Se vérifier » sur Discord."}
        essais = [t for t in (deja.get("essais") or []) if now - t < 86400]
        if len(essais) >= ESSAIS_MAX_24H:
            return {"etat": "erreur", "message": "Trop de tentatives aujourd'hui. Un manager va examiner ton cas."}
        _EN_COURS.add(nonce)
    try:
        # Hors du verrou : la geolocalisation peut prendre 10 s, les autres
        # membres n'ont pas a l'attendre. Le jeton est reserve dans _EN_COURS.
        code_m, membre = api("GET", f"/guilds/{GUILD_ID}/members/{uid}")
        if code_m == 404:
            return {"etat": "erreur", "message": "Tu n'es plus sur le serveur YouLab. Rejoins-le puis clique à nouveau « Se vérifier »."}
        u = (membre.get("user") or {}) if code_m == 200 and isinstance(membre, dict) else {}
        infos = infos_ip(ip)
        return _conclure(uid, nonce, now, donnees, ip, ip_garantie, hors_cloudflare, infos, essais,
                         str(u.get("global_name") or u.get("username") or "")[:40])
    finally:
        _EN_COURS.discard(nonce)


def _conclure(uid, nonce, now, donnees, ip, ip_garantie, hors_cloudflare, infos, essais, pseudo) -> Dict[str, Any]:
    with _VERROU:
        toutes = _fiches()
        deja = toutes.get(uid) or {}
        fiche = {
            "user_id": uid, "pseudo": pseudo or deja.get("pseudo") or "",
            "ts": int(now), "ip": ip, "ip_hash": _hash_ip(ip), "ip_garantie": ip_garantie,
            "hors_cloudflare": bool(hors_cloudflare), "essais": essais + [int(now)],
            "ip_ok": infos.get("ok", False), "ip_erreur": infos.get("erreur", ""),
            "pays": infos.get("pays", ""), "pays_nom": infos.get("pays_nom", ""),
            "fai": infos.get("fai", ""), "vpn": bool(infos.get("vpn")), "type": infos.get("type", ""),
            "fuseau": str(donnees.get("fuseau") or "")[:60], "langue": str(donnees.get("langues") or "")[:60],
            "empreinte": empreinte(donnees), "appareil": str(donnees.get("appareil") or "")[:64],
            "age_compte": age_compte_jours(uid),
            "jetons_utilises": ((deja.get("jetons_utilises") or []) + [nonce])[-10:],
        }
        d = decider(fiche, toutes)
        fiche["etat"] = d["etat"]
        fiche["raisons"] = d["raisons"]
        toutes[uid] = fiche
        _ecrire_fiches(toutes)
    if d["etat"] == "ok" and not ouvrir(uid):
        # Role refuse par Discord (bot sans token, role au-dessus du sien) :
        # le membre a reussi, mais il resterait enferme sans que personne
        # le sache. Il passe en attente, avec les boutons pour un manager.
        d["etat"] = "attente"
        d["raisons"].append("vérification réussie mais le bot n'a pas pu poser le rôle ✅ Vérifié")
        with _VERROU:
            toutes = _fiches()
            if uid in toutes:
                toutes[uid].update(etat="attente", raisons=d["raisons"])
                _ecrire_fiches(toutes)
    if d["etat"] != "ok":
        _role("PUT", uid, ROLE_ATTENTE if d["etat"] == "attente" else ROLE_SUSPECT)
    _poster_alerte(fiche, d)
    if d["etat"] == "ok":
        return {"etat": "ok", "message": "✅ Vérification réussie ! Retourne sur Discord : tout le serveur est maintenant ouvert."}
    if d["etat"] == "attente":
        return {"etat": "attente", "message": "⏳ Ta vérification doit être validée par un manager. Tu seras prévenu sur Discord."}
    return {"etat": "bloque", "message": "⛔ Accès refusé. Ce serveur est réservé aux candidats du Bénin et de Madagascar, sans VPN."}


# ─── Interactions Discord (bouton « Se vérifier », boutons manager) ───────
def _permissions(membre: Dict[str, Any]) -> int:
    try:
        return int(membre.get("permissions") or 0)
    except Exception:
        return 0


def _est_manager(membre: Dict[str, Any]) -> bool:
    p = _permissions(membre)
    if p & 0x8 or p & 0x10000000:              # administrateur ou gestion des roles
        return True
    return bool(ROLE_MANAGER and ROLE_MANAGER in (membre.get("roles") or []))


def _ephemere(texte: str, composants: Optional[list] = None) -> Dict[str, Any]:
    data = {"content": texte, "flags": 64}
    if composants:
        data["components"] = composants
    return {"type": 4, "data": data}


def traiter_interaction(p: Dict[str, Any]) -> Dict[str, Any]:
    _charger_config()
    if p.get("type") == 1:                                  # PING de validation de Discord
        return {"type": 1}
    if p.get("type") != 3:
        return _ephemere("Action inconnue.")
    if str(p.get("guild_id") or "") != GUILD_ID:
        return _ephemere("Ce bouton ne fonctionne que sur le serveur YouLab.")
    membre = p.get("member") or {}
    user = membre.get("user") or {}
    cid = ((p.get("data") or {}).get("custom_id") or "")

    if cid == "verif:start":
        uid = str(user.get("id") or "")
        if not uid.isdigit():
            return _ephemere("Compte introuvable.")
        roles = membre.get("roles") or []
        if ROLE_VERIFIE and ROLE_VERIFIE in roles:
            return _ephemere("✅ Tu es déjà vérifié.")
        if ROLE_ATTENTE and ROLE_ATTENTE in roles:
            # un nouvel essai finirait de toute facon en attente, et reposterait
            # une alerte a chaque clic
            return _ephemere("⏳ Ta vérification attend la validation d'un manager. Tu seras prévenu ici dès que c'est fait.")
        lien = f"{SITE}/verif/{creer_jeton(uid)}"
        return _ephemere(
            "🔐 **Vérification anti-fraude**\n"
            "Ouvre ce lien **sur ton téléphone ou ton ordinateur habituel**, sans VPN. "
            "Il est personnel et valable **15 minutes**.",
            [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Ouvrir la vérification", "url": lien}]}])

    m = re.fullmatch(r"verif:(ok|kick|ban):(\d{5,25})", cid)
    if m:
        if not _est_manager(membre):
            return _ephemere("Réservé aux managers.")
        action, cible = m.group(1), m.group(2)
        qui = user.get("username") or "?"
        if action == "ok":
            code = 204 if ouvrir(cible) else 0
            fait = "✅ accepté" if code else "échec de l'acceptation (rôle non posé)"
            etat = "ok"
        elif action == "kick":
            code, _ = api("DELETE", f"/guilds/{GUILD_ID}/members/{cible}")
            fait = "⛔ refusé et expulsé" if code in (200, 204) else f"échec de l'expulsion (HTTP {code})"
            etat = "refuse"
        else:
            code, _ = api("PUT", f"/guilds/{GUILD_ID}/bans/{cible}", json={"delete_message_seconds": 0})
            fait = "🔨 banni" if code in (200, 204) else f"échec du bannissement (HTTP {code})"
            etat = "banni"
        with _VERROU:
            toutes = _fiches()
            if cible in toutes and code in (200, 204):
                toutes[cible]["etat"] = etat
                toutes[cible]["decision_manager"] = f"{fait} par {qui}"
                _ecrire_fiches(toutes)
        message = p.get("message") or {}
        embeds = message.get("embeds") or []
        if embeds:
            embeds[0]["footer"] = {"text": f"YouLab • Vérification — {fait} par {qui}"}
        return {"type": 7, "data": {"embeds": embeds, "components": [], "allowed_mentions": {"parse": []}}}

    return _ephemere("Action inconnue.")


# ─── La page web ──────────────────────────────────────────────────────────
PAGE_HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Vérification YouLab</title>
<style>
:root{--fond:#0b0b10;--carte:#15151d;--bord:#26263a;--texte:#e8e8f0;--gris:#9a9ab0;--bleu:#5865f2;--vert:#22c55e;--orange:#f59e0b;--rouge:#ef4444}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:16px;padding:26px;max-width:440px;width:100%}
h1{font-size:20px;margin:0 0 8px}p{color:var(--gris);margin:8px 0}
button{width:100%;margin-top:16px;padding:14px;border:0;border-radius:10px;background:var(--bleu);color:#fff;font-weight:700;font-size:15px;cursor:pointer}
button:disabled{opacity:.6}.res{margin-top:16px;padding:12px;border-radius:10px;display:none;font-weight:600}
.ok{background:rgba(34,197,94,.12);color:var(--vert)}.attente{background:rgba(245,158,11,.12);color:var(--orange)}
.bloque,.erreur{background:rgba(239,68,68,.12);color:var(--rouge)}.petit{font-size:12px}
.piege{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
</style></head><body><div class="carte">
<h1>🔐 Vérification YouLab</h1>
<p>Pour protéger le serveur contre les faux comptes et la fraude, on vérifie ta connexion avant de t'ouvrir l'accès.</p>
<p class="petit">En continuant, tu acceptes que soient relevés <b>ton adresse IP, ton pays et une empreinte technique de ton appareil</b>, uniquement pour détecter la fraude et les doubles comptes. Ces données sont visibles par l'équipe YouLab seulement et effacées au bout de 90 jours.</p>
<div class="piege"><label>Site web<input id="site_web" tabindex="-1" autocomplete="off"></label></div>
<button id="go">Lancer la vérification</button>
<div id="res" class="res"></div>
</div>
<script>
(function(){
  var t0 = Date.now() / 1000;
  function h(s){ var x = 0; for (var i = 0; i < s.length; i++){ x = ((x << 5) - x + s.charCodeAt(i)) | 0; } return (x >>> 0).toString(16); }
  function canvas(){ try { var c = document.createElement('canvas'); c.width = 240; c.height = 60; var g = c.getContext('2d');
    g.textBaseline = 'top'; g.font = '16px Arial'; g.fillStyle = '#f60'; g.fillRect(100, 1, 62, 20);
    g.fillStyle = '#069'; g.fillText('YouLab verif \\u2728 123', 2, 15); g.fillStyle = 'rgba(102,204,0,.7)'; g.fillText('YouLab verif \\u2728 123', 4, 17);
    return h(c.toDataURL()); } catch (e) { return ''; } }
  function webgl(){ try { var c = document.createElement('canvas'); var g = c.getContext('webgl'); if (!g) return '';
    var e = g.getExtension('WEBGL_debug_renderer_info'); return e ? (g.getParameter(e.UNMASKED_VENDOR_WEBGL) + '|' + g.getParameter(e.UNMASKED_RENDERER_WEBGL)) : ''; } catch (e) { return ''; } }
  function appareil(){ try { var k = 'yl_appareil'; var v = localStorage.getItem(k);
    if (!v) { v = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)); localStorage.setItem(k, v); } return v; } catch (e) { return ''; } }
  var bouton = document.getElementById('go'), res = document.getElementById('res');
  bouton.onclick = function(){
    bouton.disabled = true; bouton.textContent = 'Vérification en cours…';
    var d = {
      t0: t0, site_web: document.getElementById('site_web').value,
      canvas: canvas(), webgl: webgl(), ecran: screen.width + 'x' + screen.height + 'x' + (screen.colorDepth || ''),
      plateforme: navigator.platform || '', coeurs: navigator.hardwareConcurrency || '', memoire: navigator.deviceMemory || '',
      fuseau: (Intl.DateTimeFormat().resolvedOptions().timeZone || ''), langues: (navigator.languages || [navigator.language]).join(','),
      ua: navigator.userAgent, appareil: appareil()
    };
    fetch(location.pathname, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) })
      .then(function(r){ return r.json(); })
      .then(function(j){ res.className = 'res ' + (j.etat || 'erreur'); res.textContent = j.message || 'Erreur'; res.style.display = 'block';
        if (j.etat === 'erreur') { bouton.disabled = false; bouton.textContent = 'Réessayer'; } else { bouton.style.display = 'none'; } })
      .catch(function(){ res.className = 'res erreur'; res.textContent = 'Connexion impossible. Réessaie.'; res.style.display = 'block';
        bouton.disabled = false; bouton.textContent = 'Réessayer'; });
  };
})();
</script></body></html>"""
