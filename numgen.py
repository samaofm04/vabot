"""Numéros SMS et adresses mail temporaires (GetAText + SMSBower, HeroSMS).

Repris du projet test de l'user (sms_api/main.py) :
  - SMS  : GetAText, protocole « stubs handler_api » (ACCESS_NUMBER:id:phone,
           STATUS_OK:code…) ; fallback SMSBower stubs si GetAText n'a pas de
           numéro (même protocole, autre clé).
  - Mail : SMSBower, API JSON /api/mail/getActivation + getCode.
  - HeroSMS : numéros X du serveur YouLab TWITTER (numeros_x_discord), même
           protocole « stubs » (HeroSMS se dit compatible SMS-Activate). À part
           de get_number : un clic sur Instagram ne doit pas acheter chez lui,
           ni un clic X chez GetAText.

Clés : .env (GETATEXT_API_KEY / SMSBOWER_API_KEY / HEROSMS_API_KEY) ou
data/numgen.json (posé par `/smskey`). Jamais de clé dans le code.
"""
import os
import pathlib
import threading
import time

import requests

import safe_json

_FILE = pathlib.Path(__file__).resolve().parent / "data" / "numgen.json"

GETATEXT_URL = "https://getatext.com/stubs/handler_api.php"
SMSBOWER_STUBS_URL = "https://smsbower.app/stubs/handler_api.php"
HEROSMS_URL = "https://hero-sms.com/stubs/handler_api.php"
MAIL_BASE = "https://smsbower.page/api/mail"
# SMSPool ne parle pas « stubs » : son API est du JSON, la cle dans
# l'URL. Seul le solde est branche ici -- voir l'en-tete du module.
SMSPOOL_BALANCE_URL = "https://api.smspool.net/request/balance"
MAIL_DOMAIN = "gmail.com"

# Codes service -> nom attendu par chaque fournisseur (GetAText veut le nom long)
GETATEXT_SERVICES = {
    "ig": "instagram/threads", "fb": "facebook", "go": "google",
    "wa": "whatsapp", "tg": "telegram", "tt": "tiktok", "sc": "snapchat",
    "am": "amazon", "ms": "microsoft", "nf": "netflix",
}
SERVICE_LABELS = {
    "ig": "Instagram / Threads", "tt": "TikTok", "go": "Google",
    "fb": "Facebook", "tg": "Telegram", "wa": "WhatsApp", "sc": "Snapchat",
}

# Pays proposés, du plus fourni au moins fourni. Une seule table : le site et
# le bot y lisaient chacun la leur, et elles divergeaient.
PAYS = (
    ("187", "🇺🇸 États-Unis"),
    ("78", "🇫🇷 France"),
    ("43", "🇩🇪 Allemagne"),
    ("16", "🇬🇧 Royaume-Uni"),
    ("12", "🇺🇸 États-Unis (2ᵉ pool)"),
    ("0", "🇷🇺 Russie (défaut d'origine — rarement dispo)"),
)

# Le défaut d'origine était « 0 » = Russie, dont le stock est tombé à zéro :
# le panneau répondait « aucun numéro dispo » alors que les clés et le solde
# étaient bons, et rien dans le message ne pointait vers le pays.
PAYS_DEFAUT = "187"


def _cfg() -> dict:
    try:
        d = safe_json.load_or_prev(_FILE)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _key(name: str) -> str:
    """Clé : data/numgen.json d'abord (posée via /smskey), sinon .env."""
    v = (_cfg().get(name) or "").strip()
    return v or (os.getenv(name.upper()) or "").strip()


def getatext_key() -> str:
    return _key("getatext_api_key")


def smsbower_key() -> str:
    return _key("smsbower_api_key")


def smspool_key() -> str:
    return _key("smspool_api_key")


def herosms_key() -> str:
    return _key("herosms_api_key")


def set_keys(getatext=None, smsbower=None, country=None, service=None,
             smspool=None, herosms=None) -> dict:
    c = _cfg()
    if getatext is not None:
        c["getatext_api_key"] = str(getatext).strip()
    if smsbower is not None:
        c["smsbower_api_key"] = str(smsbower).strip()
    if country is not None:
        c["country"] = str(country).strip()
    if service is not None:
        c["service"] = str(service).strip().lower()
    if smspool is not None:
        c["smspool_api_key"] = str(smspool).strip()
    if herosms is not None:
        c["herosms_api_key"] = str(herosms).strip()
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write(_FILE, c, indent=2)
    except Exception:
        pass
    return status()


def status() -> dict:
    c = _cfg()

    def _m(v):
        return (v[:4] + "…" + v[-4:]) if len(v) > 10 else ("posée" if v else "")
    return {
        "getatext": _m(getatext_key()),
        "smsbower": _m(smsbower_key()),
        "smspool": _m(smspool_key()),
        "herosms": _m(herosms_key()),
        "country": str(c.get("country") or PAYS_DEFAUT),
        "service": str(c.get("service") or "ig"),
        "sms_ok": bool(getatext_key() or smsbower_key()),
        "mail_ok": bool(smsbower_key()),
        # Volontairement HORS de sms_ok : celui-la allume le bouton
        # « Obtenir un numero », et SMSPool ne sait pas acheter d'ici.
        "smspool_ok": bool(smspool_key()),
        # Hors de sms_ok aussi : HeroSMS ne sert que les numéros X.
        "herosms_ok": bool(herosms_key()),
    }


def default_country() -> str:
    return str(_cfg().get("country") or PAYS_DEFAUT)


def stock(service="ig") -> dict:
    """{code pays: numéros disponibles} chez GetAText.

    getNumbersStatus est une LECTURE : elle n'achète rien et ne consomme
    aucun crédit. Un pays dont la réponse est illisible est absent du
    résultat — on ne prétend pas qu'il a zéro numéro.
    """
    import json as _js
    cle = GETATEXT_SERVICES.get(service, service)
    out = {}
    for code, _lib in PAYS:
        t = _stubs("getatext", "getNumbersStatus", country=code)
        if not t.startswith("{"):
            continue
        try:
            v = _js.loads(t).get(f"{cle}_0")
        except Exception:
            continue
        out[code] = int(v) if str(v).isdigit() else 0
    return out


def balances() -> dict:
    """Soldes des fournisseurs, prêts à afficher ('12.34 $' ou '—')."""
    out = {"sms": "—", "mail": "—", "smspool": "—", "herosms": "—"}
    if getatext_key():
        t = _get(GETATEXT_URL, {"api_key": getatext_key(), "action": "getBalance"})
        if t.startswith("ACCESS_BALANCE:"):
            out["sms"] = t.split(":", 1)[1].strip() + " $"
        else:
            out["sms"] = _human(t)
    if smsbower_key():
        t = _get(SMSBOWER_STUBS_URL, {"api_key": smsbower_key(), "action": "getBalance"})
        if t.startswith("ACCESS_BALANCE:"):
            out["mail"] = t.split(":", 1)[1].strip() + " $"
        else:
            out["mail"] = _human(t)
    if smspool_key():
        out["smspool"] = _solde_smspool(
            _get(SMSPOOL_BALANCE_URL, {"key": smspool_key()}))
    if herosms_key():
        t = _stubs("herosms", "getBalance")
        out["herosms"] = (t.split(":", 1)[1].strip() + " $"
                          if t.startswith("ACCESS_BALANCE:") else _human(t))
    return out


def _solde_smspool(txt: str) -> str:
    """Le solde SMSPool, ou la raison du refus.

    DEUX PIEGES, tous les deux releves en production par le Parc :
    un refus arrive avec un code HTTP 200 -- on lit donc le CORPS, et
    pas le statut ; et « errors » est un TABLEAU d'objets, qui affiche
    « [object Object] » si on le passe tel quel.
    """
    import json as _js
    try:
        j = _js.loads(txt)
    except Exception:
        return _human(txt)
    if not isinstance(j, dict):
        return "réponse illisible"
    try:
        return "%.2f $" % float(j.get("balance"))
    except (TypeError, ValueError):
        pass
    e = j.get("errors")
    if isinstance(e, list) and e and isinstance(e[0], dict):
        e = e[0].get("message") or e[0].get("description")
    return str(j.get("message") or e or j.get("error") or "clé refusée")[:60]


def _get(url, params, timeout=20):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        return r.text.strip()
    except Exception as e:
        return f"ERR:{e}"


# ---------------------------------------------------------------- SMS (stubs)

def _stubs(provider, action, **params):
    if provider == "smsbower":
        key, url = smsbower_key(), SMSBOWER_STUBS_URL
    elif provider == "herosms":
        key, url = herosms_key(), HEROSMS_URL
    else:
        key, url = getatext_key(), GETATEXT_URL
    if not key:
        return "NO_KEY"
    txt = _get(url, {"api_key": key, "action": action, **params})
    if provider == "herosms":
        return _texte_herosms(txt)
    return txt


def _texte_herosms(txt):
    """HeroSMS répond « ACCESS_NUMBER:… » quand tout va bien, mais ses refus
    arrivent en JSON : {"title":"BAD_KEY","details":"Unauthorized"}, relevé le
    17/10/2026. Lu tel quel, ce JSON n'était reconnu par rien (ni _human, ni
    get_code) : on le ramène au mot du protocole, le détail derrière."""
    t = (txt or "").strip()
    if not t.startswith("{"):
        return t
    import json as _js
    try:
        j = _js.loads(t)
    except Exception:
        return t
    if isinstance(j, dict) and j.get("title"):
        d = str(j.get("details") or "").strip()
        return str(j["title"]).strip() + (":" + d if d else "")
    return t


def _commander(service, country):
    """Un achat, dans un pays. -> (ok, message|infos, réponses brutes)."""
    errs, brut = [], []
    if getatext_key():
        txt = _stubs("getatext", "getNumber",
                     service=GETATEXT_SERVICES.get(service, service), country=country)
        brut.append(txt)
        if txt.startswith("ACCESS_NUMBER"):
            p = txt.split(":")
            if len(p) >= 3:
                return True, {"id": p[1], "phone": "+" + p[2].lstrip("+"),
                              "provider": "getatext", "country": country}, brut
        errs.append(f"GetAText : {_human(txt)}")
    if smsbower_key():
        txt2 = _stubs("smsbower", "getNumber", service=service, country=country)
        brut.append(txt2)
        if txt2.startswith("ACCESS_NUMBER"):
            p2 = txt2.split(":")
            if len(p2) >= 3:
                return True, {"id": p2[1], "phone": "+" + p2[2].lstrip("+"),
                              "provider": "smsbower", "country": country}, brut
        errs.append(f"SMSBower : {_human(txt2)}")
    return False, " | ".join(errs) or "aucune clé SMS configurée (`/smskey`)", brut


def get_number(service="ig", country=None):
    """Commande un numéro (GetAText, fallback SMSBower).
    -> (True, {id, phone, provider, country}) ou (False, message)."""
    demande = str(country if country is not None else default_country())
    ok, res, brut = _commander(service, demande)
    if ok or country is not None:
        return ok, res

    # Le pays réglé est à sec. Répondre « aucun numéro dispo » n'aide
    # personne : il faut connaître les codes pays pour s'en sortir, et le
    # message ne dit même pas que le pays est en cause. On demande donc au
    # fournisseur où il lui en reste — c'est une lecture gratuite — et on y
    # va. Uniquement sur un manque de stock : une clé refusée ou un solde
    # vide se reproduiraient à l'identique dans tous les pays.
    if not any("NO_NUMBERS" in (t or "") for t in brut):
        return False, res

    # On ESSAIE les pays dans l'ordre de PAYS, du plus fourni au moins fourni,
    # au lieu de demander d'abord l'inventaire complet. stock() coûte SIX
    # appels HTTP a 20 s de delai chacun, tous faits avant meme de retenter :
    # depuis que le pays reglé est a sec, chaque demande de numero passait par
    # la, et l'attente se comptait en minutes. Un getNumber qui echoue est
    # gratuit et ne coute qu'un aller-retour — le premier pays fourni repond
    # donc tout de suite.
    essayes = {str(demande)}
    for code, _lib in PAYS:
        if code in essayes:
            continue
        essayes.add(code)
        ok2, res2, brut2 = _commander(service, code)
        if ok2:
            return True, res2
        # Une cle refusee ou un solde vide se reproduiraient a l'identique
        # partout : inutile de faire le tour du monde pour s'en convaincre.
        if not any("NO_NUMBERS" in (t or "") for t in brut2):
            return False, res2
    return False, f"{res} — aucun pays n'a de numéro pour ce service"


def get_number_herosms(service="tw", country="187"):
    """Un numéro HeroSMS, dans CE pays seulement : le propriétaire a choisi
    les États-Unis pour X (17/10/2026), et un repli silencieux vers un autre
    pays donnerait un numéro qu'il n'a pas voulu.
    -> (True, {id, phone, provider, country}) ou (False, message)."""
    txt = _stubs("herosms", "getNumber", service=service, country=str(country))
    if txt.startswith("ACCESS_NUMBER"):
        p = txt.split(":")
        if len(p) >= 3 and p[1] and p[2]:
            return True, {"id": p[1], "phone": "+" + p[2].lstrip("+"),
                          "provider": "herosms", "country": str(country)}
    return False, _human(txt)


def get_code(activation_id, provider="getatext"):
    """-> ('code', '1234') | ('wait', '') | ('cancel', '') | ('error', msg)."""
    txt = _stubs(provider, "getStatus", id=str(activation_id))
    if txt.startswith("STATUS_OK"):
        code = txt.split(":", 1)[1] if ":" in txt else ""
        return "code", code.replace(" ", "").strip()
    # Avec ou sans « :<code> » : apres un « Nouveau code » (statut 3), le
    # fournisseur repond STATUS_WAIT_RETRY:<ancien code> en attendant le
    # suivant. L'egalite stricte classait cette attente en erreur : au bout
    # de 5 tours, l'ecoute s'arretait sur « ❌ STATUS_WAIT_RETRY:… ».
    if txt.startswith(("STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND")):
        return "wait", ""
    if txt == "STATUS_CANCEL":
        return "cancel", ""
    return "error", _human(txt)


def retry(activation_id, provider="getatext"):
    """Redemande un NOUVEAU code sur le MÊME numéro (status 3)."""
    txt = _stubs(provider, "setStatus", id=str(activation_id), status="3")
    return (txt in ("ACCESS_RETRY_GET", "STATUS_WAIT_CODE")), _human(txt)


def finish(activation_id, provider="getatext"):
    return _stubs(provider, "setStatus", id=str(activation_id), status="6")


def cancel(activation_id, provider="getatext"):
    txt = _stubs(provider, "setStatus", id=str(activation_id), status="8")
    return (txt == "ACCESS_CANCEL"), _human(txt)


# ------------------------------------------------------------- MAIL (SMSBower)

def _mail(endpoint, **params):
    key = smsbower_key()
    if not key:
        return {"status": 0, "error": "aucune clé SMSBower (`/smskey`)"}
    import json as _js
    txt = _get(f"{MAIL_BASE}/{endpoint}", {"api_key": key, **params})
    try:
        return _js.loads(txt)
    except Exception:
        return {"status": 0, "error": txt[:180]}


def get_mail(service="ig", domain=MAIL_DOMAIN):
    """Commande une adresse mail. -> (True, {id, mail, stale}) ou (False, msg).
    `stale` = code déjà présent dans la boîte AVANT l'inscription : il doit être
    ignoré au polling (SMSBower recycle des adresses)."""
    d = _mail("getActivation", service=service, domain=domain)
    if not d or d.get("status") == 0 or not d.get("mailId"):
        return False, str(d.get("error") or "pas de mail dispo")
    stale = ""
    chk = _mail("getCode", mailId=str(d["mailId"]))
    if isinstance(chk, dict):
        stale = str(chk.get("code") or "").strip()
    return True, {"id": str(d["mailId"]), "mail": str(d.get("mail") or ""),
                  "stale": stale}


def get_mail_code(mail_id, stale=""):
    """-> ('code', '1234') | ('wait', '') | ('error', msg)."""
    d = _mail("getCode", mailId=str(mail_id))
    if isinstance(d, dict) and d.get("status") != 0:
        code = str(d.get("code") or "").replace(" ", "").strip()
        if code and code != (stale or ""):
            return "code", code
        return "wait", ""
    msg = str((d or {}).get("error") or "").lower()
    if any(k in msg for k in ("not been received", "not received", "no code",
                              "wait", "try again", "no mails yet")):
        return "wait", ""
    return "error", str((d or {}).get("error") or "erreur inconnue")


def mail_finish(mail_id):
    return _mail("setStatus", mailId=str(mail_id), status="6")


def mail_cancel(mail_id):
    return _mail("setStatus", mailId=str(mail_id), status="8")


_MSG = {
    "NO_KEY": "aucune clé API configurée (`/smskey`)",
    "BAD_KEY": "clé API refusée",
    "NO_BALANCE": "solde insuffisant",
    "NO_NUMBERS": "aucun numéro dispo (réessaie ou change de pays)",
    "NO_ACTIVATION": "activation inconnue (déjà terminée ?)",
    "WRONG_SERVICE": "service inconnu chez ce fournisseur",
    "BANNED": "compte bloqué par le fournisseur",
    "EARLY_CANCEL_DENIED": "annulation trop tôt — attends ~2 min",
    # Les mots de HeroSMS (relevés le 17/10/2026)
    "BAD_API_KEY": "clé API refusée",
    "NOT_FOUND": "activation inconnue (déjà terminée ?)",
    "SERVICE_NOT_AVAILABLE": "service indisponible chez ce fournisseur",
}


def _human(txt):
    t = (txt or "").strip()
    return _MSG.get(t.split(":")[0], t or "réponse vide")


# ------------------------------------------------------- ALERTE AU STAFF
# Un service à sec ne se lisait que dans le panneau du VA : du 16 au 20/10/2026,
# huit VA du serveur Spam ont reçu « Insufficient balance » de SMSBower, et
# aucun mail n'est parti depuis le 13/10 sans que personne ne le sache. Le
# staff est désormais prévenu UNE fois par panne, dans le 📊・debrief-day du
# serveur Spam -- là où part déjà le récap des numéros (choix du propriétaire,
# 21/10/2026). Recharger ou remplir reste à lui.

ALERTES_FICHIER = pathlib.Path(__file__).resolve().parent / "data" / "numgen_alertes.json"
#: Serveur Spam > 📊・debrief-day, posté par le bot admin (le même que le récap).
ALERTES_SALON = "1553627411680338153"
_VERROU_ALERTES = threading.Lock()

#: Les mots d'un solde vide : SMSBower (mail, en JSON) écrit « Insufficient
#: balance », le protocole stubs NO_BALANCE, que _human traduit.
_MOTS_CREDIT = ("insufficient balance", "no_balance", "solde insuffisant",
                "not enough balance", "low balance")


def sans_credit(msg) -> bool:
    """Le refus vient-il d'un solde vide ? Avec deux fournisseurs essayés
    (« GetAText : … | SMSBower : … »), TOUS doivent l'être : l'un à sec et
    l'autre en rupture de stock, recharger ne suffirait pas."""
    parts = [p for p in str(msg or "").lower().split("|") if p.strip()]
    return bool(parts) and all(any(k in p for k in _MOTS_CREDIT) for p in parts)


def _alertes() -> dict:
    d = safe_json.load(ALERTES_FICHIER, default={}) or {}
    return d if isinstance(d, dict) else {}


def _poster_alerte(texte: str):
    """Un message texte dans ALERTES_SALON, par REST : appelable depuis les
    fils du site (Twitter) comme depuis le bot. -> (ok, raison)."""
    tok = (os.getenv("DISCORD_ADMIN_TOKEN") or "").strip()
    if not tok:
        return False, "DISCORD_ADMIN_TOKEN absent"
    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{ALERTES_SALON}/messages",
            headers={"Authorization": "Bot " + tok, "User-Agent": "DiscordBot (youl4b, 1.0)"},
            json={"content": texte[:1900], "allowed_mentions": {"parse": []}}, timeout=20)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"HTTP {r.status_code} {r.text[:160]}"


def _en_production() -> bool:
    """La machine qui poste sur Discord : VA_MACHINE_PROD n'est posé que dans
    le .env du VPS. Remplacé dans les tests."""
    return os.environ.get("VA_MACHINE_PROD") == "1"


def alerter_staff(cle: str, texte: str) -> str:
    """Prévient le staff UNE fois par panne (`cle` : « credit:mail »,
    « outlook:vide »…), retenu dans data/numgen_alertes.json : un redémarrage
    ne le redit pas. Rend « envoye », « deja », ou la raison de l'échec -- rien
    n'est alors retenu, le refus suivant réessaie.

    Hors de la machine de production (VA_MACHINE_PROD absent), rien ne part :
    les suites de tests passent par ici avec le vrai data/."""
    with _VERROU_ALERTES:
        if cle in _alertes():
            return "deja"
        if not _en_production():
            return "hors production"
        ok, pourquoi = _poster_alerte(texte)
        if not ok:
            print(f"[numgen] alerte staff « {cle} » NON envoyée : {pourquoi}", flush=True)
            return pourquoi or "refus"
        d = _alertes()
        d[cle] = {"le": int(time.time()), "texte": texte[:300]}
        if not safe_json.write(ALERTES_FICHIER, d):
            print(f"[numgen] alerte staff « {cle} » envoyée mais non retenue : "
                  f"elle repartira au prochain refus", flush=True)
        else:
            print(f"[numgen] alerte staff « {cle} » envoyée", flush=True)
        return "envoye"


def fin_alerte(cle: str) -> bool:
    """Le service est revenu (un mail livré, une adresse donnée) : la
    prochaine panne sera redite. Rend True si une alerte était en cours."""
    with _VERROU_ALERTES:
        d = _alertes()
        if cle not in d:
            return False
        d.pop(cle, None)
        safe_json.write(ALERTES_FICHIER, d)
    print(f"[numgen] « {cle} » : service revenu, la prochaine panne sera redite", flush=True)
    return True
