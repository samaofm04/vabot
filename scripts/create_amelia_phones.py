"""create_amelia_phones.py - Cree 25 cloud phones GeeLark pour AMELIA OSIRENCE.

Endpoint : POST /open/v1/phone/addNew
Config :
- Android 15
- Langue : French (France) -> fr-fr
- Reseau mobile (netType=1)
- Proxy SOCKS5 partage : lafxcfxnrz.cn.fxdx.in:14821
- Refresh URL : https://i.fxdx.in/actionlinks/do/changeip/hGz4neSzRGyfnLPoYLrWAw
- Group : AMELIA OSIRENCE (auto-cree si inexistant)
- Charge mode : 0 = on-demand (par minute)
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Charge .env du bot
HERE = Path(__file__).resolve().parent
BOT_DIR = HERE.parent
load_dotenv(BOT_DIR / ".env")

BEARER = os.getenv("GEELARK_BEARER", "").strip()
if not BEARER:
    print("[FATAL] GEELARK_BEARER manquant dans .env")
    sys.exit(1)

GEELARK_BASE = "https://openapi.geelark.com"
GROUP_NAME = "AMELIA OSIRENCE"

PROXY_INFO = "socks5://lzuckr:0pqtnx@lafxcfxnrz.cn.fxdx.in:14821"
REFRESH_URL = "https://i.fxdx.in/actionlinks/do/changeip/hGz4neSzRGyfnLPoYLrWAw"

USERNAMES = [
    "ameange9",
    "dupuis_mya",
    "clara.granger",
    "chloeverdieer",
    "camille226106",
    "bastien70852",
    "ambre33575",
    "alma95289",
    "alix55218",
    "alix35134",
    "milaafontaine",
    "eli_benoit",
    "eeileenfaure",
    "leo706362",
    "johann66586",
    "siennamarchand",
    "perrier.axelle",
    "riveenndupuis",
    "maya742717",
    "ethan912102",
    "ameliebourdn",
    "pons.zara",
    "tahliappons",
    "tao51614",
    "mira228193",
]


def headers():
    return {"Authorization": f"Bearer {BEARER}", "Content-Type": "application/json"}


def make_env_row(username: str) -> dict:
    return {
        "profileName": username,
        "proxyInformation": PROXY_INFO,
        "refreshUrl": REFRESH_URL,
        "proxyQueryChannel": 2,  # IP2Location default
        "mobileLanguage": "fr-fr",
        "profileGroup": GROUP_NAME,
        "profileNote": f"Auto-cree pour @{username}",
        "netType": 1,  # mobile network
    }


def call_create(envs: list[dict]) -> dict:
    payload = {
        "mobileType": "Android 15",
        "chargeMode": 0,  # on-demand
        "data": envs,
    }
    print(f"\n>>> POST /open/v1/phone/addNew avec {len(envs)} phone(s)")
    print(f"    Group: {GROUP_NAME}")
    print(f"    Names: {[e['profileName'] for e in envs]}")
    r = requests.post(
        f"{GEELARK_BASE}/open/v1/phone/addNew",
        headers=headers(),
        json=payload,
        timeout=60,
    )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"status": r.status_code, "body": body}


def main():
    print(f"[INFO] {len(USERNAMES)} phones a creer dans group '{GROUP_NAME}'")
    print(f"[INFO] Proxy SOCKS5 : {PROXY_INFO}")
    print(f"[INFO] Refresh URL  : {REFRESH_URL}")
    if "--dry-run" in sys.argv:
        print("\n[DRY-RUN] payload sample :")
        print(json.dumps(make_env_row(USERNAMES[0]), indent=2, ensure_ascii=False))
        return

    # ETAPE 1 : test sur 1 phone
    if "--all" not in sys.argv:
        print("\n[ETAPE 1/2] Test sur 1 phone (ameange9)...")
        res = call_create([make_env_row(USERNAMES[0])])
        print(f"    HTTP {res['status']}")
        print(f"    Body: {json.dumps(res['body'], indent=2, ensure_ascii=False)}")
        if res["status"] != 200 or res["body"].get("code") != 0:
            print("\n[FAIL] Test phone n'a pas reussi - STOP. Verifie la conf.")
            sys.exit(2)
        data = res["body"].get("data", {})
        success = data.get("successAmount", 0)
        if success != 1:
            print(f"\n[FAIL] Test phone : successAmount={success} (attendu 1)")
            print(f"    Details : {data.get('details')}")
            sys.exit(3)
        print(f"[OK] Test phone cree avec succes !")
        details = data.get("details", [])
        if details:
            print(f"    Phone ID : {details[0].get('id')}")
            print(f"    Phone Name : {details[0].get('profileName')}")
        print("\n[ETAPE 2/2] Creation des 24 phones restants...")
        remaining = USERNAMES[1:]
    else:
        print("\n[ETAPE BATCH] Creation des 25 phones d'un coup...")
        remaining = USERNAMES

    # ETAPE 2 : batch des restants
    envs = [make_env_row(u) for u in remaining]
    res = call_create(envs)
    print(f"    HTTP {res['status']}")
    body = res["body"]
    if res["status"] != 200 or body.get("code") != 0:
        print(f"\n[FAIL] Batch raté : code={body.get('code')} msg={body.get('msg')}")
        print(f"    Full body : {json.dumps(body, indent=2, ensure_ascii=False)}")
        # Si erreur 44001, fallback en one-by-one
        if str(body.get("code")) == "44001":
            print("\n[FALLBACK] Pas de batch sur ton plan, je passe en one-by-one...")
            ok = 0
            fail = 0
            for u in remaining:
                r2 = call_create([make_env_row(u)])
                b2 = r2["body"]
                d2 = b2.get("data", {})
                if r2["status"] == 200 and b2.get("code") == 0 and d2.get("successAmount") == 1:
                    ok += 1
                    print(f"    [OK] {u}")
                else:
                    fail += 1
                    print(f"    [FAIL] {u} : {b2.get('msg', b2)}")
            print(f"\n[RESUME one-by-one] {ok} OK / {fail} fail")
        sys.exit(4)

    data = body.get("data", {})
    total = data.get("totalAmount", 0)
    success = data.get("successAmount", 0)
    failed = data.get("failAmount", 0)
    print(f"\n[OK] Batch termine : {success}/{total} OK, {failed} fail")
    if failed > 0:
        for d in data.get("details", []):
            if d.get("code") != 0:
                print(f"    [FAIL] {d.get('profileName')} : {d.get('msg')}")
    print("\n[DONE] Phones crees. Verifie dans GeeLark UI.")


if __name__ == "__main__":
    main()
