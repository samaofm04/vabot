#!/usr/bin/env python3
"""test_hikerapi.py — Verifie que HikerAPI rend ce dont le parc a besoin.

LECTURE SEULE. N'ecrit aucun fichier, ne touche ni au site ni aux donnees.

    /opt/va-bot/venv/bin/python test_hikerapi.py VOTRE_CLE

POURQUOI CE FICHIER EXISTE
--------------------------
Le parc paie aujourd'hui DEUX fournisseurs : RapidAPI pour les statistiques
(3 appels par compte) et Apify pour resoudre les URL video des reels. Un
seul appel a /v1/user/clips rend les deux, plus la legende. Avant de
resilier quoi que ce soit, il faut la preuve que les champs arrivent
vraiment sur de VRAIS comptes du parc — un gros compte de demonstration ne
prouve rien pour des comptes petits et recents.

Trois questions, et un "oui" partiel ne vaut rien :

  1. les VUES arrivent-elles ?        (play_count)  -> sinon tout tombe
  2. la DATE arrive-t-elle ?          (taken_at)    -> pour « 3 reels/jour »
  3. l'URL VIDEO et la LEGENDE ?                    -> remplace Apify

CE QUI A ETE APPRIS EN TESTANT (21/09/2026), et qui est code ici
----------------------------------------------------------------
- urllib est refuse par Cloudflare (erreur 1010 : empreinte du client).
  `requests` et `curl` passent. Ne PAS revenir a urllib.
- /v2/user/clips rend HTTP 400. Le bon endpoint est /v1/user/clips, et il
  veut un `user_id`, pas un `username` : il faut donc d'abord resoudre le
  compte via /v1/user/by/username (2 appels pour le premier controle, mais
  le pk est stable et peut etre mis en cache -> 1 appel ensuite).
- `taken_at` est une chaine ISO 8601 ("2026-06-23T07:51:58Z"), pas un
  horodatage Unix. Un int() direct leve ValueError. `taken_at_ts` existe
  aussi et porte, lui, des secondes.
"""
import datetime
import json
import sys

import requests

BASE = "https://api.hikerapi.com"

# De vrais comptes du parc, pris dans le cache de production.
COMPTES = [
    "jessy.beauty_love",
    "kyara.chz",
    "jessy_baddies",
    "ameliaa_ameliy",
    "eemmaa_maah",
]

_appels = {"n": 0, "ok": 0}


def appel(chemin, **params):
    """Un GET. Rend (code, donnees) sans jamais lever.

    Les echecs ne sont pas factures — le tarif est « par requete reussie » —
    donc sonder plusieurs variantes ne coute rien.
    """
    _appels["n"] += 1
    try:
        r = requests.get(BASE + chemin,
                         headers={"x-access-key": CLE, "Accept": "application/json"},
                         params=params, timeout=60)
    except Exception as e:                       # reseau : on continue
        return 0, str(e)
    if r.status_code != 200:
        return r.status_code, r.text[:200]
    _appels["ok"] += 1
    try:
        return 200, r.json()
    except ValueError:
        return 200, None


def quand(ts):
    """taken_at arrive en ISO 8601 ; taken_at_ts en secondes. On accepte les deux."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts)
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def premier(m, *noms):
    for n in noms:
        if m.get(n) is not None:
            return m.get(n)
    return None


def extraire(item):
    """Sort les 4 champs decisifs, quelle que soit l'enveloppe du JSON."""
    m = item.get("media") if isinstance(item.get("media"), dict) else item
    video = premier(m, "video_url") or ""
    if not video:
        vv = m.get("video_versions")
        if isinstance(vv, list) and vv and isinstance(vv[0], dict):
            video = vv[0].get("url", "")
    legende = m.get("caption_text") or ""
    if not legende and isinstance(m.get("caption"), dict):
        legende = m["caption"].get("text") or ""
    return {
        "vues": premier(m, "play_count", "view_count", "video_view_count"),
        "date": quand(premier(m, "taken_at_ts", "taken_at", "taken_at_timestamp")),
        "legende": legende,
        "video": video,
    }


def main():
    print("=" * 68)
    print("  Test HikerAPI — lecture seule, sur de vrais comptes du parc")
    print("=" * 68)

    bilan = {"vues": 0, "date": 0, "video": 0, "legende": 0, "reels": 0, "comptes": 0}

    for u in COMPTES:
        print("\n@%s" % u)
        code, data = appel("/v1/user/by/username", username=u)
        if code != 200 or not isinstance(data, dict):
            print("   profil : HTTP %s  %s" % (code, str(data)[:140]))
            continue
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        uid = premier(user, "pk", "id", "pk_id")
        print("   profil : %s abonne(s), %s publication(s)"
              % (user.get("follower_count"), user.get("media_count")))

        code, data = appel("/v1/user/clips", user_id=uid)
        if code != 200:
            print("   reels  : HTTP %s  %s" % (code, str(data)[:140]))
            continue
        items = data if isinstance(data, list) else (
            (data or {}).get("items") or ((data or {}).get("response") or {}).get("items") or [])
        if not items:
            print("   reels  : reponse vide")
            continue

        bilan["comptes"] += 1
        par_jour = {}
        for it in items:
            f = extraire(it)
            bilan["reels"] += 1
            if f["vues"] is not None:
                bilan["vues"] += 1
            if f["date"]:
                bilan["date"] += 1
                j = f["date"].strftime("%d/%m")
                par_jour[j] = par_jour.get(j, 0) + 1
            if f["video"]:
                bilan["video"] += 1
            if f["legende"]:
                bilan["legende"] += 1
        print("   reels  : %d rendus" % len(items))
        for it in items[:3]:
            f = extraire(it)
            print("      %-12s vues=%-8s video=%-3s  %s" % (
                f["date"].strftime("%d/%m %H:%M") if f["date"] else "?",
                f["vues"] if f["vues"] is not None else "ABSENT",
                "oui" if f["video"] else "NON",
                (f["legende"][:34] + "...") if len(f["legende"]) > 34
                else (f["legende"].replace("\n", " ") or "(aucune)")))
        if par_jour:
            recents = sorted(par_jour.items(), reverse=True)[:4]
            print("      publications/jour : %s"
                  % ", ".join("%s=%d" % (j, n) for j, n in recents))

    n = bilan["reels"] or 1
    print("\n" + "=" * 68)
    print("  VERDICT")
    print("=" * 68)
    print("  comptes releves : %d / %d   (%d reels au total)"
          % (bilan["comptes"], len(COMPTES), bilan["reels"]))
    for cle, libelle, vital in (("vues", "VUES (play_count)", True),
                                ("date", "DATE de publication", True),
                                ("video", "URL video (remplace Apify)", False),
                                ("legende", "LEGENDE du reel", False)):
        etat = "OK" if bilan[cle] else ("BLOQUANT" if vital else "absent")
        print("  %-30s %3d/%-3d  %s" % (libelle, bilan[cle], n, etat))
    print("\n  requetes : %d envoyees, %d reussies (donc facturees)"
          % (_appels["n"], _appels["ok"]))
    if bilan["vues"] and bilan["date"]:
        print("\n  => HikerAPI couvre le besoin. Le remplacement est possible.")
    else:
        print("\n  => Il manque l'essentiel : NE PAS resilier RapidAPI.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    CLE = sys.argv[1].strip()
    main()
