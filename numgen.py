"""Numéros SMS et adresses mail temporaires (GetAText + SMSBower).

Repris du projet test de l'user (sms_api/main.py) :
  - SMS  : GetAText, protocole « stubs handler_api » (ACCESS_NUMBER:id:phone,
           STATUS_OK:code…) ; fallback SMSBower stubs si GetAText n'a pas de
           numéro (même protocole, autre clé).
  - Mail : SMSBower, API JSON /api/mail/getActivation + getCode.

Clés : .env (GETATEXT_API_KEY / SMSBOWER_API_KEY) ou data/numgen.json (posé par
`/smskey`). Jamais de clé dans le code.
"""
import os
import pathlib

import requests

import safe_json

_FILE = pathlib.Path(__file__).resolve().parent / "data" / "numgen.json"

GETATEXT_URL = "https://getatext.com/stubs/handler_api.php"
SMSBOWER_STUBS_URL = "https://smsbower.app/stubs/handler_api.php"
MAIL_BASE = "https://smsbower.page/api/mail"
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


def set_keys(getatext=None, smsbower=None, country=None, service=None) -> dict:
    c = _cfg()
    if getatext is not None:
        c["getatext_api_key"] = str(getatext).strip()
    if smsbower is not None:
        c["smsbower_api_key"] = str(smsbower).strip()
    if country is not None:
        c["country"] = str(country).strip()
    if service is not None:
        c["service"] = str(service).strip().lower()
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
        "country": str(c.get("country") or "0"),
        "service": str(c.get("service") or "ig"),
        "sms_ok": bool(getatext_key() or smsbower_key()),
        "mail_ok": bool(smsbower_key()),
    }


def default_country() -> str:
    return str(_cfg().get("country") or "0")


def balances() -> dict:
    """Soldes des 2 fournisseurs, prêts à afficher ('12.34 $' ou '—')."""
    out = {"sms": "—", "mail": "—"}
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
    return out


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
    else:
        key, url = getatext_key(), GETATEXT_URL
    if not key:
        return "NO_KEY"
    return _get(url, {"api_key": key, "action": action, **params})


def get_number(service="ig", country=None):
    """Commande un numéro (GetAText, fallback SMSBower).
    -> (True, {id, phone, provider}) ou (False, message)."""
    country = str(country if country is not None else default_country())
    errs = []
    if getatext_key():
        txt = _stubs("getatext", "getNumber",
                     service=GETATEXT_SERVICES.get(service, service), country=country)
        if txt.startswith("ACCESS_NUMBER"):
            p = txt.split(":")
            if len(p) >= 3:
                return True, {"id": p[1], "phone": "+" + p[2].lstrip("+"),
                              "provider": "getatext"}
        errs.append(f"GetAText : {_human(txt)}")
    if smsbower_key():
        txt2 = _stubs("smsbower", "getNumber", service=service, country=country)
        if txt2.startswith("ACCESS_NUMBER"):
            p2 = txt2.split(":")
            if len(p2) >= 3:
                return True, {"id": p2[1], "phone": "+" + p2[2].lstrip("+"),
                              "provider": "smsbower"}
        errs.append(f"SMSBower : {_human(txt2)}")
    return False, " | ".join(errs) or "aucune clé SMS configurée (`/smskey`)"


def get_code(activation_id, provider="getatext"):
    """-> ('code', '1234') | ('wait', '') | ('cancel', '') | ('error', msg)."""
    txt = _stubs(provider, "getStatus", id=str(activation_id))
    if txt.startswith("STATUS_OK"):
        code = txt.split(":", 1)[1] if ":" in txt else ""
        return "code", code.replace(" ", "").strip()
    if txt in ("STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND"):
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
}


def _human(txt):
    t = (txt or "").strip()
    return _MSG.get(t.split(":")[0], t or "réponse vide")
