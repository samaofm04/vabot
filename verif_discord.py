"""verif_discord.py — Verification anti-fraude a l'entree du serveur Discord
« YouLab - Entretien (Réglement) », via le bot SEVEN.

LE PARCOURS
  1. Un nouveau ne voit qu'un salon, #🔐┃vérification, avec le bouton
     « Se vérifier ». Le reste du serveur (salons ET liste des membres) est
     reserve au role ✅ Vérifié.
  2. Le clic arrive ici par HTTP (Interactions Endpoint de l'application :
     pas de processus bot a faire tourner). On repond, en message visible
     par lui seul, un lien PERSONNEL signe, valable 15 minutes, a usage
     unique : /verif/<jeton>. UN SEUL lien vit a la fois : un nouveau clic
     efface le message precedent et rend l'ancien lien caduc (sinon les
     messages s'empilaient dans #verification, et chaque vieux lien
     pouvait encore reposter une alerte).
  3. Discord ne donne JAMAIS l'IP d'un membre a un bot : c'est la page web
     qui la voit. Elle releve aussi une empreinte de l'appareil.
  4. Decision (decider) :
       - IP hors Bénin / Madagascar                              -> SUSPECT :
         role 🚩 Suspect, alerte « fraude » dans #🚩┃suspicions ; le
         membre, lui, lit « en attente » : un responsable peut l'accepter
         a la main (demande du proprietaire, 23/09/2026) ;
         (un VPN n'est pas interdit : il est signale, le pays de l'IP decide)
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
LIENS = DATA_DIR / "verif_liens.json"   # le lien actif de chaque membre (et de quoi effacer son message)
_VERROU = threading.Lock()
_EN_COURS: set = set()        # jetons en cours de verification (la geolocalisation prend du temps)
_UIDS_EN_COURS: set = set()   # un membre = une verification a la fois, quel que soit le nombre de liens


def _en_fond(f):
    """Travail apres la reponse a Discord (3 s maximum pour repondre).
    Remplacee par un appel direct dans les tests."""
    threading.Thread(target=f, daemon=True).start()


_EN_FOND = _en_fond

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
def _proxycheck(ip: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"https://proxycheck.io/v2/{ip}", params={"vpn": 3, "asn": 1}, timeout=8)
        d = (r.json() or {}).get(ip) or {}
    except Exception:
        return {}
    if not d.get("isocode"):
        return {}
    return {"pays": d.get("isocode", "").upper(), "pays_nom": d.get("country", ""),
            "fai": d.get("provider") or d.get("organisation") or "", "org": d.get("organisation") or "",
            "asn": d.get("asn") or "", "ville": d.get("city") or "", "region": d.get("region") or "",
            "lat": d.get("latitude"), "lon": d.get("longitude"),
            "vpn": str(d.get("proxy", "no")).lower() == "yes" or str(d.get("vpn", "no")).lower() == "yes",
            "type": d.get("type", "")}


def _ipapi(ip: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=8, params={
            "fields": "status,countryCode,country,regionName,city,lat,lon,isp,org,as,mobile,proxy,hosting"})
        d = r.json() or {}
    except Exception:
        return {}
    if d.get("status") != "success":
        return {}
    return {"pays": (d.get("countryCode") or "").upper(), "pays_nom": d.get("country", ""),
            "fai": d.get("isp", ""), "org": d.get("org", ""), "asn": (d.get("as") or "").split(" ")[0],
            "ville": d.get("city", ""), "region": d.get("regionName", ""), "lat": d.get("lat"), "lon": d.get("lon"),
            "mobile": bool(d.get("mobile")), "vpn": bool(d.get("proxy") or d.get("hosting")),
            "type": "hébergeur" if d.get("hosting") else ""}


def infos_ip(ip: str) -> Dict[str, Any]:
    """{ok, pays, pays_nom, fai, org, asn, ville, region, lat, lon, mobile,
    vpn, type, pays_autre, source, erreur}.

    Les deux services sont interroges EN MEME TEMPS et fusionnes :
    proxycheck.io fait foi pour le pays et le VPN (c'est son metier, 100
    requetes par jour sans compte), ip-api.com complete (reseau mobile ou
    fixe, numero d'AS) et prend le relais s'il est muet. S'ils ne donnent
    pas le meme pays, on le dit au staff au lieu de choisir en silence.
    Les deux en panne : ok=False, et la decision passe au manager."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as ex:
        fa, fb = ex.submit(_proxycheck, ip), ex.submit(_ipapi, ip)
        a, b = fa.result(), fb.result()
    if not a and not b:
        return {"ok": False, "erreur": "pays de l'IP introuvable (services de géolocalisation muets)"}
    r = dict(b)
    r.update({k: v for k, v in a.items() if v not in (None, "")})
    r["vpn"] = bool(a.get("vpn") or b.get("vpn"))
    r["type"] = a.get("type") or b.get("type") or ""
    r["mobile"] = b.get("mobile")
    if a.get("pays") and b.get("pays") and a["pays"] != b["pays"]:
        r["pays_autre"] = f"{b.get('pays_nom') or b['pays']} selon ip-api.com"
    r["source"] = " + ".join(n for n, x in (("proxycheck.io", a), ("ip-api.com", b)) if x)
    r["ok"] = bool(r.get("pays"))
    return r


# ─── Fiches ───────────────────────────────────────────────────────────────
def _fiches() -> Dict[str, Any]:
    """Purgees a la LECTURE aussi : sinon une fiche de 91 jours comptait
    encore dans la detection des doubles comptes tant que personne n'ecrivait."""
    try:
        d = safe_json.load(FICHES, default={}) or {}
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    limite = time.time() - CONSERVATION_S
    return {k: v for k, v in d.items() if isinstance(v, dict) and float(v.get("ts") or 0) >= limite}


def _ecrire_fiches(d: Dict[str, Any]) -> bool:
    limite = time.time() - CONSERVATION_S
    d = {k: v for k, v in d.items() if float((v or {}).get("ts") or 0) >= limite}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ok = bool(safe_json.write_text(FICHES, json.dumps(d, ensure_ascii=False, indent=1)))
    if not ok:
        print("[verif] ECHEC d'ecriture de data/verif_membres.json", flush=True)
    return ok


def _liens() -> Dict[str, Any]:
    try:
        d = safe_json.load(LIENS, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ecrire_liens(d: Dict[str, Any]) -> bool:
    limite = time.time() - 3600
    d = {k: v for k, v in d.items() if isinstance(v, dict) and float(v.get("ts") or 0) >= limite}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write_text(LIENS, json.dumps(d, ensure_ascii=False)))


def _effacer_message(token: str, ts: float):
    """Efface le message ephemere d'un ancien clic. Discord le permet avec
    le jeton d'interaction, valable 15 minutes : au-dela, le lien est mort
    de toute facon et le message disparait au prochain rechargement."""
    if token and time.time() - float(ts or 0) < 14 * 60:
        _EN_FOND(lambda: api("DELETE", f"/webhooks/{APP_ID}/{token}/messages/@original"))


def _message_unique(uid: str, token: str, nonce: Optional[str] = None):
    """UN seul message « Se verifier » visible a la fois, quelle que soit la
    reponse (lien, « deja verifie », « en attente ») : on retient celui qui
    part et on efface le precedent. Sans nonce, le lien actif reste le meme."""
    with _VERROU:
        liens = _liens()
        ancien = liens.get(uid) or {}
        liens[uid] = {"nonce": ancien.get("nonce", "") if nonce is None else nonce,
                      "token": str(token or ""), "ts": time.time()}
        _ecrire_liens(liens)
    _effacer_message(ancien.get("token", ""), ancien.get("ts", 0))


def _clore_lien(uid: str, nonce: str, texte: str):
    """Le lien a servi : son message ephemere affiche le resultat, sans bouton."""
    with _VERROU:
        liens = _liens()
        actif = liens.get(uid) or {}
        if actif.get("nonce") != nonce:
            return
        liens.pop(uid, None)
        _ecrire_liens(liens)
    token, ts = actif.get("token"), float(actif.get("ts") or 0)
    if token and time.time() - ts < 14 * 60:
        _EN_FOND(lambda: api("PATCH", f"/webhooks/{APP_ID}/{token}/messages/@original",
                             json={"content": texte, "components": [], "allowed_mentions": {"parse": []}}))


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


INDICATIFS = {"229": "BJ", "261": "MG"}


def normaliser_tel(brut: Any) -> str:
    """'+229 01 23-45.67 89' -> '+2290123456789' ; '' si inexploitable.
    L'indicatif est exige : sans lui, impossible de savoir le pays."""
    t = re.sub(r"[\s.\-()/]", "", str(brut or ""))[:30]
    if t.startswith("00"):
        t = "+" + t[2:]
    return t if re.fullmatch(r"\+\d{8,15}", t) else ""


def pays_du_tel(tel: str) -> str:
    for code, pays in INDICATIFS.items():
        if tel.startswith("+" + code):
            return pays
    return ""


def resume_appareil(ua: str) -> str:
    """Ce que le navigateur dit de lui : 'Android 14 · Chrome 129', 'iPhone
    iOS 17.5 · Safari'. Chrome masque le modele exact depuis 2023."""
    ua = str(ua or "")
    os_ = ""
    m = re.search(r"Android ([\d.]+)(?:; ([^;)]+))?", ua)
    if m:
        modele = re.sub(r"\s*Build/.*$", "", (m.group(2) or ""))
        modele = re.sub(r"[^A-Za-z0-9 ._+-]", "", modele).strip()[:40]
        os_ = f"Android {m.group(1)}" + (f" ({modele})" if modele and modele != "K" else "")
    elif "iPhone" in ua or "iPad" in ua:
        m = re.search(r"OS (\d+[_\d]*)", ua)
        os_ = ("iPad" if "iPad" in ua else "iPhone") + (f" iOS {m.group(1).replace('_', '.')}" if m else "")
    elif "Windows" in ua:
        os_ = "Windows"
    elif "Mac OS X" in ua:
        os_ = "Mac"
    elif "Linux" in ua:
        os_ = "Linux"
    nav = ""
    for motif, nom in ((r"Discord/", "appli Discord"), (r"EdgA?/(\d+)", "Edge"), (r"OPR/(\d+)", "Opera"),
                       (r"SamsungBrowser/(\d+)", "Samsung Internet"), (r"Firefox/(\d+)", "Firefox"),
                       (r"CriOS/(\d+)|Chrome/(\d+)", "Chrome"), (r"Version/[\d.]+ .*Safari", "Safari")):
        m = re.search(motif, ua)
        if m:
            v = next((g for g in m.groups() if g), "") if m.groups() else ""
            nav = nom + (f" {v}" if v else "")
            break
    if "; wv)" in ua and "Discord" not in nav:
        nav += " (navigateur intégré)"
    return " · ".join(x for x in (os_, nav) if x) or "?"


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
    # Meme appareil = meme identifiant garde par le navigateur : certain.
    # Meme empreinte ET meme IP = probable, mais deux amis au meme Tecno sur
    # le meme partage de connexion donnent la meme chose : on le dit tel quel.
    meme_appareil = sorted({k for k, v in autres.items() if k != uid
                            and fiche.get("appareil") and v.get("appareil") == fiche.get("appareil")})
    meme_modele_et_ip = sorted((set(meme_empreinte) & set(meme_ip)) - set(meme_appareil))
    # La navigation privee change l'identifiant, pas l'empreinte : un compte
    # refuse ou banni qui revient ainsi doit passer par un humain.
    empreinte_douteuse = sorted(k for k in meme_empreinte
                                if (autres.get(k) or {}).get("etat") in ("banni", "refuse", "bloque"))
    meme_tel = sorted({k for k, v in autres.items() if k != uid and fiche.get("telephone")
                       and v.get("telephone") == fiche.get("telephone")})
    precedent = (autres.get(uid) or {}).get("etat") if uid else None
    if not fiche.get("ip_ok"):
        etat = "attente"
        raisons.append(fiche.get("ip_erreur") or "pays de l'IP inconnu")
    else:
        if fiche.get("pays") not in PAYS_AUTORISES:
            etat = "bloque"
            raisons.append(f"IP hors Bénin/Madagascar : {fiche.get('pays_nom') or fiche.get('pays') or '?'}")
        if fiche.get("vpn"):
            # Le VPN n'est pas interdit (demande du proprietaire, 23/09/2026) :
            # il est signale au staff, et c'est le pays de l'IP qui decide.
            raisons.append(f"VPN / proxy détecté ({fiche.get('type') or 'masquage'}) — autorisé, "
                           "l'IP affichée est celle du VPN")
    if fiche.get("hors_cloudflare"):
        # le site passe toujours par Cloudflare : une requete qui arrive sans
        # a vise le serveur en direct, la ou les en-tetes IP s'inventent
        etat = "bloque" if etat == "bloque" else "attente"
        raisons.append("connexion arrivée hors Cloudflare (IP peut-être falsifiée)")
    if etat != "bloque":
        if meme_appareil:
            etat = "attente"
            raisons.append("même appareil qu'un autre compte")
        if meme_modele_et_ip:
            etat = "attente"
            raisons.append("même modèle de téléphone ET même connexion qu'un autre compte (peut être une coïncidence)")
        if empreinte_douteuse:
            etat = "attente"
            etats = sorted({_ETAT_LISIBLE.get((autres.get(k) or {}).get("etat"), "?") for k in empreinte_douteuse})
            raisons.append(f"même modèle d'appareil qu'un compte {' / '.join(etats)}")
        if meme_tel:
            etat = "attente"
            raisons.append("même numéro de téléphone qu'un autre compte")
        tel = fiche.get("telephone") or ""
        if tel and not pays_du_tel(tel):
            etat = "attente"
            raisons.append(f"numéro hors Bénin/Madagascar ({tel[:4]}…)")
        if precedent in ("bloque", "attente", "refuse", "banni"):
            etat = "attente"
            raisons.append(f"nouvel essai après un précédent « {_ETAT_LISIBLE.get(precedent, precedent)} »")
        fz = fiche.get("fuseau") or ""
        if fiche.get("pays") in FUSEAUX_ATTENDUS and fz and fz not in FUSEAUX_ATTENDUS[fiche["pays"]]:
            etat = "attente"
            raisons.append(f"fuseau du téléphone incohérent : {fz} pour une IP {PAYS_AUTORISES.get(fiche['pays'])}")
    if etat == "bloque" and fiche.get("telephone") and not pays_du_tel(fiche["telephone"]):
        raisons.append(f"numéro hors Bénin/Madagascar ({fiche['telephone'][:4]}…)")
    return {"etat": etat, "raisons": raisons, "meme_appareil": meme_appareil, "meme_ip": meme_ip,
            "meme_tel": meme_tel, "meme_empreinte": [k for k in meme_empreinte if k not in meme_appareil]}


# ─── Alertes staff ────────────────────────────────────────────────────────
_COULEUR = {"ok": 0x57F287, "attente": 0xF59E0B, "bloque": 0xED4245}
_TITRE = {"ok": "✅ Entrée vérifiée", "attente": "⏳ En attente d'un manager", "bloque": "🚨 Alerte fraude — hors Bénin/Madagascar, à valider à la main"}


def _propre(x: Any, n: int = 80) -> str:
    """Texte venu du membre ou d'un service : sans accent grave ni
    mention, sinon il casserait la mise en forme de l'alerte."""
    return str(x or "").replace("`", "'").replace("@", "@\u200b")[:n]


def lien_maps(fiche: Dict[str, Any]) -> str:
    try:
        lat, lon = float(fiche.get("lat")), float(fiche.get("lon"))
    except (TypeError, ValueError):
        return ""
    return f"https://www.google.com/maps?q={lat:.4f},{lon:.4f}"


def _qui(x: str, toutes: Optional[Dict[str, Any]]) -> str:
    """Un compte lie, lisible meme s'il a quitte le serveur (une mention
    <@id> d'un absent s'affiche « @utilisateur inconnu ») : pseudo, id et
    ce qu'il est devenu — banni ou refuse, c'est tout ce qui compte."""
    f = (toutes or {}).get(x) or {}
    morceaux = [f"<@{x}>"]
    if f.get("pseudo"):
        morceaux.append(f"`{_propre(f['pseudo'], 30)}`")
    morceaux.append(f"`{x}`")
    if f.get("etat"):
        morceaux.append(f"**{_ETAT_LISIBLE.get(f['etat'], f['etat'])}**")
    return " ".join(morceaux)


def embed_alerte(fiche: Dict[str, Any], d: Dict[str, Any], toutes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    uid = fiche["user_id"]
    lignes_liens = []

    def liste(ids):
        return "\n".join("  " + _qui(x, toutes) for x in ids[:8])
    if d.get("meme_appareil"):
        lignes_liens.append("📱 **Même appareil** (même navigateur) que :\n" + liste(d["meme_appareil"]))
    if d.get("meme_tel"):
        lignes_liens.append("📞 **Même numéro** que :\n" + liste(d["meme_tel"]))
    if d.get("meme_empreinte"):
        lignes_liens.append("🧬 Même modèle de téléphone / navigateur *(peut être une coïncidence)* que :\n"
                            + liste(d["meme_empreinte"]))
    if d.get("meme_ip"):
        lignes_liens.append("🌐 Même IP *(souvent normal : réseau mobile / cybercafé)* que :\n" + liste(d["meme_ip"]))
    lieu = ", ".join(_propre(x, 40) for x in (fiche.get("ville"), fiche.get("region")) if x) or "?"
    maps = lien_maps(fiche)
    if maps:
        lieu += f"\n[📍 Voir sur Google Maps]({maps})\n*zone du réseau, pas l'adresse*"
    mobile = fiche.get("mobile")
    reseau = [_propre(fiche.get("fai"), 60) or "?"]
    if fiche.get("org") and fiche.get("org") != fiche.get("fai"):
        reseau.append(_propre(fiche.get("org"), 60))
    if fiche.get("asn"):
        reseau.append(f"`{_propre(fiche.get('asn'), 20)}`")
    reseau.append("📶 réseau mobile" if mobile else ("🏠 connexion fixe / box" if mobile is False else "type inconnu"))
    pays = _propre(fiche.get("pays_nom") or fiche.get("pays"), 40) or "?"
    if fiche.get("pays_autre"):
        pays += f"\n*(⚠️ {_propre(fiche['pays_autre'], 60)})*"
    tel = fiche.get("telephone") or ""
    champs = [
        {"name": "Membre", "value": f"<@{uid}> · `{_propre(fiche.get('pseudo'), 40) or '?'}`\nCompte créé il y a **{fiche.get('age_compte', '?')} j**", "inline": True},
        {"name": "📞 Numéro", "value": (f"`{tel}`" + ("" if pays_du_tel(tel) else " ⚠️ hors 🇧🇯/🇲🇬")) if tel else "non donné", "inline": True},
        {"name": "IP", "value": f"`{fiche.get('ip', '?')}`" + ("" if fiche.get("ip_garantie") else " *(non attestée)*"), "inline": True},
        {"name": "🌍 Pays", "value": pays, "inline": True},
        {"name": "📍 Localisation", "value": lieu, "inline": True},
        {"name": "🛰️ Opérateur / réseau", "value": "\n".join(reseau), "inline": True},
        {"name": "VPN / proxy", "value": ("oui — " + _propre(fiche.get("type"), 40)) if fiche.get("vpn") else "non", "inline": True},
        {"name": "📱 Appareil", "value": f"{_propre(fiche.get('appareil_resume'), 80) or '?'}\nécran `{_propre(fiche.get('ecran'), 20) or '?'}` · id `{(fiche.get('empreinte') or '?')[:10]}`", "inline": True},
        {"name": "⚙️ Réglages", "value": f"fuseau `{_propre(fiche.get('fuseau'), 40) or '?'}`\nlangue `{_propre(fiche.get('langue'), 40) or '?'}`", "inline": True},
    ]
    if d.get("raisons"):
        champs.append({"name": "Pourquoi", "value": "\n".join("• " + r for r in d["raisons"])[:1000], "inline": False})
    if lignes_liens:
        champs.append({"name": "Liens avec d'autres comptes", "value": "\n".join(lignes_liens)[:1020], "inline": False})
    return {"title": _TITRE[d["etat"]], "color": _COULEUR[d["etat"]], "fields": champs,
            "footer": {"text": "YouLab • Vérification" + (f" • {fiche['source_ip']}" if fiche.get("source_ip") else "")},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def boutons_manager(uid: str) -> List[Dict[str, Any]]:
    return [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Accepter", "emoji": {"name": "✅"}, "custom_id": f"verif:ok:{uid}"},
        {"type": 2, "style": 4, "label": "Refuser (expulser)", "emoji": {"name": "⛔"}, "custom_id": f"verif:kick:{uid}"},
        {"type": 2, "style": 2, "label": "Bannir", "emoji": {"name": "🔨"}, "custom_id": f"verif:ban:{uid}"},
    ]}]


def _salon_alerte(etat: str) -> str:
    return {"attente": SALON_ATTENTE, "bloque": SALON_SUSPICIONS}.get(etat) or SALON_ALERTES


def _poster_alerte(fiche, d, toutes: Optional[Dict[str, Any]] = None) -> str:
    salon = _salon_alerte(d["etat"])
    if not salon:
        return ""
    corps = {"embeds": [embed_alerte(fiche, d, toutes)], "allowed_mentions": {"parse": []}}
    if d["etat"] in ("attente", "bloque"):
        corps["components"] = boutons_manager(fiche["user_id"])
    code, rep = api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200:
        print(f"[verif] alerte NON postee pour {fiche.get('user_id')} ({d['etat']}) : HTTP {code} "
              f"{str((rep or {}).get('message') or '')[:120]}", flush=True)
        return ""
    return str(rep.get("id") or "")


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
    l'alerte. Le jeton ne sert qu'une fois, et seul le DERNIER lien donne
    au membre est valable."""
    _charger_config()
    j = lire_jeton(jeton, maintenant)
    if not j:
        return {"etat": "erreur", "message": "Lien expiré ou invalide. Retourne sur Discord et clique à nouveau « Se vérifier »."}
    now = maintenant if maintenant is not None else time.time()
    if donnees.get("site_web"):          # champ piege : un humain ne le voit pas
        return {"etat": "erreur", "message": "Vérification refusée."}
    # Temps passe sur la page, mesure par le navigateur lui-meme : comparer
    # son horloge a celle du serveur refusait sans fin un telephone a l'heure
    # fausse, sans arreter aucun script (qui envoie ce qu'il veut).
    try:
        duree = float(donnees["duree"]) if donnees.get("duree") is not None else None
    except (TypeError, ValueError):
        duree = None
    if duree is not None and duree < DELAI_MIN_PAGE_S:
        return {"etat": "erreur", "message": "Attends quelques secondes, puis clique à nouveau."}
    tel = normaliser_tel(donnees.get("telephone"))
    if not tel:
        # le lien n'est pas consomme : il corrige et renvoie
        return {"etat": "erreur", "message": "Numéro invalide : écris-le avec l'indicatif, par exemple +229 01 23 45 67 89 "
                                             "(Bénin) ou +261 34 12 345 67 (Madagascar)."}
    if not _token():
        # sans token : ni role, ni alerte — le membre resterait « en attente »
        # d'un responsable que personne n'a prevenu
        print("[verif] token du bot SEVEN absent : verification suspendue", flush=True)
        return {"etat": "erreur", "message": "Vérification momentanément indisponible. Réessaie dans quelques minutes."}
    donnees = dict(donnees, telephone=tel)
    uid, nonce = j["user_id"], j["nonce"]
    with _VERROU:
        actif = _liens().get(uid) or {}
        if actif.get("nonce") and actif["nonce"] != nonce:
            return {"etat": "erreur", "message": "Ce lien a été remplacé par une demande plus récente : "
                                                 "utilise le dernier lien reçu sur Discord."}
        deja = _fiches().get(uid) or {}
        if nonce in (deja.get("jetons_utilises") or []) or nonce in _EN_COURS:
            return {"etat": "erreur", "message": "Ce lien a déjà servi. Clique à nouveau « Se vérifier » sur Discord."}
        if uid in _UIDS_EN_COURS:
            return {"etat": "erreur", "message": "Une vérification est déjà en cours pour ton compte. Patiente quelques secondes."}
        essais = [t for t in (deja.get("essais") or []) if now - t < 86400]
        if len(essais) >= ESSAIS_MAX_24H:
            return {"etat": "erreur", "message": "Trop de tentatives aujourd'hui. Un manager va examiner ton cas."}
        _EN_COURS.add(nonce)
        _UIDS_EN_COURS.add(uid)
    try:
        # Hors du verrou : la geolocalisation peut prendre 10 s, les autres
        # membres n'ont pas a l'attendre. Le jeton est reserve dans _EN_COURS.
        code_m, membre = api("GET", f"/guilds/{GUILD_ID}/members/{uid}")
        if code_m == 404:
            return {"etat": "erreur", "message": "Tu n'es plus sur le serveur YouLab. Rejoins-le puis clique à nouveau « Se vérifier »."}
        membre = membre if code_m == 200 and isinstance(membre, dict) else {}
        roles = membre.get("roles") or []
        # Un vieux lien ouvert apres coup ne doit ni reposter une bienvenue,
        # ni coller une alerte fraude a quelqu'un qui est deja passe.
        if ROLE_VERIFIE and ROLE_VERIFIE in roles:
            return {"etat": "ok", "message": "✅ Tu es déjà vérifié : tout le serveur t'est ouvert."}
        if any(r and r in roles for r in (ROLE_ATTENTE, ROLE_SUSPECT)):
            return {"etat": "attente", "message": "⏳ Ta demande d'accès attend déjà la validation d'un responsable."}
        u = membre.get("user") or {}
        infos = infos_ip(ip)
        res = _conclure(uid, nonce, now, donnees, ip, ip_garantie, hors_cloudflare, infos,
                        str(u.get("global_name") or u.get("username") or "")[:40])
        if res["etat"] != "erreur":
            _clore_lien(uid, nonce, res["message"])
        return res
    finally:
        _EN_COURS.discard(nonce)
        _UIDS_EN_COURS.discard(uid)


def _nettoyer(x: Any, garder: str, n: int) -> str:
    """Champ envoye par la page : on ne garde que les caracteres attendus.
    Un fuseau « x` [Valider](https://…) » s'affichait tel quel, lien
    compris, dans l'alerte que lit le manager."""
    return re.sub(garder, "", str(x or ""))[:n]


def _conclure(uid, nonce, now, donnees, ip, ip_garantie, hors_cloudflare, infos, pseudo) -> Dict[str, Any]:
    with _VERROU:
        toutes = _fiches()
        deja = toutes.get(uid) or {}
        # relu SOUS le verrou : calcule avant la geolocalisation, deux
        # verifications simultanees n'en comptaient qu'une
        essais = [t for t in (deja.get("essais") or []) if now - t < 86400]
        fiche = {
            "user_id": uid, "pseudo": pseudo or deja.get("pseudo") or "",
            "ts": int(now), "ip": ip, "ip_hash": _hash_ip(ip), "ip_garantie": ip_garantie,
            "hors_cloudflare": bool(hors_cloudflare), "essais": essais + [int(now)],
            "ip_ok": infos.get("ok", False), "ip_erreur": infos.get("erreur", ""),
            "pays": infos.get("pays", ""), "pays_nom": infos.get("pays_nom", ""),
            "fai": infos.get("fai", ""), "vpn": bool(infos.get("vpn")), "type": infos.get("type", ""),
            "fuseau": _nettoyer(donnees.get("fuseau"), r"[^A-Za-z0-9/_+\-]", 60),
            "langue": _nettoyer(donnees.get("langues"), r"[^A-Za-z0-9,\-]", 60),
            "empreinte": empreinte(donnees), "appareil": _nettoyer(donnees.get("appareil"), r"[^A-Za-z0-9\-]", 64),
            "telephone": str(donnees.get("telephone") or ""),
            "appareil_resume": resume_appareil(donnees.get("ua")),
            "ecran": _nettoyer(donnees.get("ecran"), r"[^0-9x]", 20),
            "ville": infos.get("ville", ""), "region": infos.get("region", ""),
            "lat": infos.get("lat"), "lon": infos.get("lon"), "org": infos.get("org", ""),
            "asn": infos.get("asn", ""), "mobile": infos.get("mobile"), "pays_autre": infos.get("pays_autre", ""),
            "source_ip": infos.get("source", ""),
            "age_compte": age_compte_jours(uid),
            "jetons_utilises": ((deja.get("jetons_utilises") or []) + [nonce])[-10:],
        }
        d = decider(fiche, toutes)
        fiche["etat"] = d["etat"]
        fiche["raisons"] = d["raisons"]
        toutes[uid] = fiche
        if not _ecrire_fiches(toutes):
            # rien n'est fait tant que la fiche n'est pas gardee : sinon le
            # meme lien se rejouait (bienvenue et alertes en double)
            return {"etat": "erreur", "message": "Erreur technique. Réessaie dans quelques minutes."}
    if d["etat"] == "ok" and not ouvrir(uid):
        # Role refuse par Discord (role au-dessus de celui du bot, panne) :
        # le membre a reussi, mais il resterait enferme sans que personne
        # le sache. Il passe en attente, avec les boutons pour un manager.
        print(f"[verif] role Verifie NON pose pour {uid}", flush=True)
        d["etat"] = "attente"
        d["raisons"].append("vérification réussie mais le bot n'a pas pu poser le rôle ✅ Vérifié")
        with _VERROU:
            fs = _fiches()
            if uid in fs:
                fs[uid].update(etat="attente", raisons=d["raisons"])
                _ecrire_fiches(fs)
    alerte = _poster_alerte(fiche, d, toutes)
    if d["etat"] == "ok":
        return {"etat": "ok", "message": "✅ Vérification réussie ! Retourne sur Discord : tout le serveur est maintenant ouvert."}
    if not alerte:
        # Pas d'alerte = aucun responsable prevenu. On ne pose PAS le role
        # En attente / Suspect : il peut recliquer, et l'alerte repartira.
        return {"etat": "attente", "message": "⏳ Ta demande est enregistrée, mais l'équipe n'a pas pu être prévenue "
                                              "automatiquement. Reclique « Se vérifier » sur Discord dans quelques minutes."}
    _role("PUT", uid, ROLE_ATTENTE if d["etat"] == "attente" else ROLE_SUSPECT)
    # Pas de « refuse » a l'ecran, meme pour une IP etrangere : un Francais
    # peut etre un vrai VA, un responsable tranche avec les boutons.
    return {"etat": "attente", "message": "⏳ Ta demande d'accès doit être validée à la main par un responsable. "
                                          "Tu seras mentionné dans #bienvenue dès que c'est fait."}


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


def _action_manager(p: Dict[str, Any], action: str, cible: str, qui: str):
    """Le travail d'un bouton manager, APRES la reponse a Discord : quatre
    appels REST (et une attente sur limite de debit) depassaient parfois
    les 3 s, Discord affichait « echec » alors que le role etait pose, et
    un second clic reposait une bienvenue."""
    if action == "ok":
        reussi = ouvrir(cible)
        fait, etat = ("✅ accepté", "ok") if reussi else ("échec de l'acceptation (rôle non posé) — réessaie", "")
    elif action == "kick":
        code, _ = api("DELETE", f"/guilds/{GUILD_ID}/members/{cible}")
        reussi = code in (200, 204, 404)             # 404 : deja parti, le refus tient
        fait = ("⛔ refusé et expulsé" if code != 404 else "⛔ refusé (il avait déjà quitté)") if reussi \
            else f"échec de l'expulsion (HTTP {code}) — réessaie"
        etat = "refuse"
    else:
        code, _ = api("PUT", f"/guilds/{GUILD_ID}/bans/{cible}", json={"delete_message_seconds": 0})
        reussi = code in (200, 204)
        fait = "🔨 banni" if reussi else f"échec du bannissement (HTTP {code}) — réessaie"
        etat = "banni"
    if reussi:
        with _VERROU:
            toutes = _fiches()
            if cible in toutes:
                toutes[cible]["etat"] = etat
                toutes[cible]["decision_manager"] = f"{fait} par {qui}"
                _ecrire_fiches(toutes)
    else:
        print(f"[verif] action manager {action} sur {cible} par {qui} : {fait}", flush=True)
    message = p.get("message") or {}
    embeds = message.get("embeds") or []
    if embeds:
        embeds[0]["footer"] = {"text": f"YouLab • Vérification — {fait} par {qui}"}
    # En cas d'echec les boutons RESTENT : sans eux, le membre garde son role
    # En attente, « Se verifier » lui est refuse, et plus personne ne peut agir.
    api("PATCH", f"/webhooks/{APP_ID}/{p.get('token')}/messages/@original",
        json={"embeds": embeds, "components": [] if reussi else (message.get("components") or []),
              "allowed_mentions": {"parse": []}})


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
        if not configure():
            print("[verif] clic « Se verifier » refuse : bot SEVEN non configure (token ?)", flush=True)
            return _ephemere("⚠️ Vérification momentanément indisponible. Réessaie dans quelques minutes.")
        roles = membre.get("roles") or []
        if ROLE_VERIFIE and ROLE_VERIFIE in roles:
            _message_unique(uid, p.get("token"))
            return _ephemere("✅ Tu es déjà vérifié.")
        if any(r and r in roles for r in (ROLE_ATTENTE, ROLE_SUSPECT)):
            # un nouvel essai finirait de toute facon en attente, et reposterait
            # une alerte a chaque clic
            _message_unique(uid, p.get("token"))
            return _ephemere("⏳ Ta demande d'accès attend la validation d'un responsable. Tu seras mentionné dans #bienvenue dès que c'est fait.")
        jeton = creer_jeton(uid)
        # le nouveau lien remplace l'ancien, qui ne sert plus
        _message_unique(uid, p.get("token"), (lire_jeton(jeton) or {}).get("nonce", ""))
        return _ephemere(
            "🔐 **Vérification anti-fraude**\n"
            "Ouvre ce lien **sur ton téléphone ou ton ordinateur habituel**. "
            "Il est personnel, valable **15 minutes**, et remplace tout lien précédent.",
            [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Ouvrir la vérification",
                                         "url": f"{SITE}/verif/{jeton}"}]}])

    m = re.fullmatch(r"verif:(ok|kick|ban):(\d{5,25})", cid)
    if m:
        if not _est_manager(membre):
            return _ephemere("Réservé aux managers.")
        qui = _propre(user.get("username") or "?", 40)
        _EN_FOND(lambda: _action_manager(p, m.group(1), m.group(2), qui))
        return {"type": 6}                                  # « je m'en occupe » : le message sera mis a jour

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
.champ{display:block;margin-top:14px;font-size:13px;color:var(--gris)}
.champ input{display:block;width:100%;margin-top:6px;padding:12px;border-radius:10px;border:1px solid var(--bord);background:var(--fond);color:var(--texte);font-size:16px}
</style></head><body><div class="carte">
<h1>🔐 Vérification YouLab</h1>
<p>Pour protéger le serveur contre les faux comptes et la fraude, on vérifie ta connexion avant de t'ouvrir l'accès.</p>
<p class="petit">En continuant, tu acceptes que soient relevés <b>ton numéro de téléphone, ton adresse IP, ton pays, ta ville approximative, ton opérateur et une empreinte technique de ton appareil</b>, uniquement pour détecter la fraude et les doubles comptes. Elles sont visibles par l'équipe YouLab seulement. Le fichier de vérification est purgé au bout de 90 jours ; les alertes transmises à l'équipe sur Discord sont conservées.</p>
<div class="piege"><label>Site web<input id="site_web" tabindex="-1" autocomplete="off"></label></div>
<label class="champ">Ton numéro de téléphone (WhatsApp), avec l'indicatif
<input id="tel" type="tel" inputmode="tel" autocomplete="tel" placeholder="+229 01 23 45 67 89" maxlength="24"></label>
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
    var tel = (document.getElementById('tel').value || '').replace(/[\\s.\\-()\\/]/g, '');
    if (tel.indexOf('00') === 0) { tel = '+' + tel.slice(2); }
    if (!/^\\+\\d{8,15}$/.test(tel)) {
      res.className = 'res erreur'; res.style.display = 'block';
      res.textContent = "Écris ton numéro avec l'indicatif : +229… (Bénin) ou +261… (Madagascar).";
      return;
    }
    bouton.disabled = true; bouton.textContent = 'Vérification en cours…';
    var d = {
      t0: t0, duree: performance.now() / 1000, site_web: document.getElementById('site_web').value,
      canvas: canvas(), webgl: webgl(), ecran: screen.width + 'x' + screen.height + 'x' + (screen.colorDepth || ''),
      plateforme: navigator.platform || '', coeurs: navigator.hardwareConcurrency || '', memoire: navigator.deviceMemory || '',
      fuseau: (Intl.DateTimeFormat().resolvedOptions().timeZone || ''), langues: (navigator.languages || [navigator.language]).join(','),
      ua: navigator.userAgent, appareil: appareil(), telephone: tel
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
