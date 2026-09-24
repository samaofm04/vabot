"""Ce que le bot sait maintenant faire tout seul, parce qu'un VA a son lien.

Jusqu'ici rien ne reliait un compte Discord à des chiffres : les primes se
réclamaient à la main, un VA qui dormait ne se voyait qu'à l'œil, et l'essai
ne finissait jamais. Depuis que chaque VA a SON lien, trois choses se font
seules :

- **celui qui dort** : lien à zéro clic depuis quelques jours, son manager est
  prévenu dans le salon du VA, le bouton pour couper son lien juste à côté ;
- **l'essai** : l'objectif atteint, 🧪 devient ⭐ sans que personne y pense.
  Le bouton du manager reste, pour les cas que le chiffre ne dit pas ;
- **la paie** : le gagnant de la semaine reçoit son montant et son adresse
  USDC dans son salon, son manager mentionné — plus de « envoie-moi ton rang ».

UN RELEVÉ RATÉ N'EST JAMAIS UN ZÉRO. GetMySocial muet, c'est « je ne sais
pas » : on ne réveille personne et on ne coupe rien là-dessus. Un zéro inventé
accuserait quelqu'un qui travaille.

UNE ALERTE NE SE RÉPÈTE PAS. Redire chaque jour « ton VA dort » transforme
l'avertissement en bruit de fond, et plus personne ne le lit.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "suivi_va.json"
CONFIG_FICHIER = DATA_DIR / "suivi_va_config.json"

JOURS_SOMMEIL = 5          # zéro clic sur cette durée = on prévient
REDIRE_APRES_J = 7         # et on ne le redit pas avant
OBJECTIF_CLICS = 50        # pour passer d'essai à confirmé
OBJECTIF_JOURS = 14        # sur cette fenêtre


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


def _reglage(nom: str, defaut: int) -> int:
    try:
        return int(config().get(nom) or defaut)
    except Exception:
        return defaut


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


# ─── les clics d'un VA ───────────────────────────────────────────────────
def clics_us(link_id: str, debut: dt.date, fin: dt.date) -> Optional[int]:
    """Les clics venus des États-Unis sur UN lien. None si on ne sait pas.

    None et 0 ne veulent pas dire la même chose : le premier interdit toute
    conclusion, le second en autorise une.
    """
    if not link_id:
        return None
    try:
        import gms
        _, pays = gms.analytics_for_links([link_id], debut.isoformat(), fin.isoformat())
    except Exception as e:
        print(f"[suivi] clics de {link_id} : {type(e).__name__}: {e}", flush=True)
        return None
    if pays is None:
        return None
    return int((pays or {}).get("US") or 0)


# ─── adresse de paiement ─────────────────────────────────────────────────
# Une adresse Solana est du base58 : ni 0, ni O, ni I, ni l, jamais.
RE_SOLANA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def adresse_valide(a: str) -> bool:
    return bool(RE_SOLANA.match(str(a or "").strip()))


def poser_adresse(gid: str, uid: str, adresse: str) -> Dict[str, Any]:
    """Garde l'adresse USDC d'un VA. Refuse ce qui n'est pas une adresse Solana."""
    a = str(adresse or "").strip()
    if not adresse_valide(a):
        return {"ok": False, "erreur": "Ce n'est pas une adresse Solana valide "
                                       "(32 à 44 caractères, sans 0, O, I ni l)."}
    d = _etat()
    (d.setdefault("adresses", {}))[f"{gid}:{uid}"] = {"adresse": a, "quand": int(time.time())}
    _ecrire(d)
    return {"ok": True, "adresse": a, "erreur": ""}


def adresse_de(gid: str, uid: str) -> str:
    return str(((_etat().get("adresses") or {}).get(f"{gid}:{uid}") or {}).get("adresse") or "")


# ─── le tour de garde ────────────────────────────────────────────────────
def _vas(gid: str) -> List[Dict[str, Any]]:
    """Les VA du serveur, avec leur lien, leur salon et leur fiche."""
    import liens_va as lv
    import tickets_discord as tk
    fiches = tk._etat().get("tickets") or {}
    out = []
    for cle, l in (lv._etat().get("liens") or {}).items():
        if not cle.startswith(f"{gid}:") or not l.get("link_id"):
            continue
        uid = cle.split(":", 1)[1]
        f = fiches.get(cle) or {}
        if not f.get("salon"):
            continue
        out.append({"uid": uid, "cle": cle, "lien": l, "fiche": f})
    return out


def verifier(gid: str, jour: Optional[dt.date] = None) -> Dict[str, Any]:
    """Un tour : qui dort, qui a fini son essai. Rend le compte rendu."""
    import liens_va as lv
    import tickets_discord as tk
    gid = str(gid)
    j = jour or dt.date.today()
    dorme = _reglage("jours_sommeil", JOURS_SOMMEIL)
    redire = _reglage("redire_apres_j", REDIRE_APRES_J)
    but = _reglage("objectif_clics", OBJECTIF_CLICS)
    fenetre = _reglage("objectif_jours", OBJECTIF_JOURS)

    d = _etat()
    vus = d.setdefault("alertes", {})
    bilan = {"dorment": [], "confirmes": [], "illisibles": [], "reveilles": []}

    for va in _vas(gid):
        uid, l, f = va["uid"], va["lien"], va["fiche"]
        lid = str(l.get("link_id") or "")
        salon = str(f.get("salon") or "")

        # --- l'essai : sur la fenêtre de l'objectif
        if f.get("essai") and not f.get("confirme"):
            n = clics_us(lid, j - dt.timedelta(days=fenetre - 1), j)
            if n is None:
                bilan["illisibles"].append(l.get("pseudo"))
            elif n >= but:
                r = tk.confirmer(gid, uid, par="objectif")
                if r.get("ok"):
                    bilan["confirmes"].append(f'{l.get("pseudo")} ({n} clics)')
                    _annoncer_confirme(gid, uid, salon, n, but)
                    continue

        # --- le sommeil : zéro clic sur la fenêtre courte
        if not lv.est_actif(gid, uid):
            continue                      # lien déjà coupé : rien à signaler
        n = clics_us(lid, j - dt.timedelta(days=dorme - 1), j)
        cle_a = f"{gid}:{uid}"
        if n is None:
            if l.get("pseudo") not in bilan["illisibles"]:
                bilan["illisibles"].append(l.get("pseudo"))
            continue
        if n > 0:
            if vus.pop(cle_a, None) is not None:
                bilan["reveilles"].append(l.get("pseudo"))
            continue
        dernier = float((vus.get(cle_a) or {}).get("quand") or 0)
        if time.time() - dernier < redire * 86400:
            continue
        if _prevenir_manager(gid, uid, salon, dorme):
            vus[cle_a] = {"quand": time.time()}
            bilan["dorment"].append(l.get("pseudo"))

    _ecrire(d)
    return bilan


def _annoncer_confirme(gid: str, uid: str, salon: str, n: int, but: int) -> None:
    import tickets_discord as tk
    tk._api("POST", f"/channels/{salon}/messages", json={
        "content": f"<@{uid}>",
        "allowed_mentions": {"users": [uid]},
        "embeds": [{"title": "⭐ Essai réussi — tu es confirmé",
                    "color": 0x22C55E,
                    "description": f"**{n} subs** sur la période, l'objectif était de "
                                   f"**{but}**.\nTon badge 🧪 Essai laisse la place à "
                                   "⭐ **Confirmé**. Bien joué."}]})
    # le badge de l'accueil n'a plus lieu d'être : on remet les bons boutons
    fiche = (tk._etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    mid = str(fiche.get("accueil") or "")
    if mid:
        tk._api("PATCH", f"/channels/{salon}/messages/{mid}",
                json={"components": tk.boutons_va(uid, confirme=True, a_un_lien=True,
                                                  gid=gid)})


def _prevenir_manager(gid: str, uid: str, salon: str, jours: int) -> bool:
    import tickets_discord as tk
    fiche = (tk._etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
    mid = str(fiche.get("manager") or "")
    qui = f"<@{mid}>" if mid else ""
    code, _r = tk._api("POST", f"/channels/{salon}/messages", json={
        "content": qui,
        "allowed_mentions": {"users": [mid] if mid else []},
        "embeds": [{"title": "😴 Ce VA ne rapporte plus rien",
                    "color": 0xF59E0B,
                    "description": f"Son lien n'a eu **aucun clic depuis {jours} jours**.\n"
                                   "Le bouton 🚫 **Désactiver le lien** est sur le message "
                                   "épinglé, si tu veux le couper. Il se rallume ensuite."}]})
    return code == 200


# ─── la paie du lundi ────────────────────────────────────────────────────
def annoncer_primes(gid: str, cl: Dict[str, Any], debut, fin) -> Dict[str, Any]:
    """Dit à chaque gagnant, dans SON salon, ce qu'il touche et où ça part.

    Le podium reste anonyme en public — « VA 27 » et rien d'autre. Le nom, le
    montant et l'adresse ne se disent que dans le salon privé du gagnant, son
    manager mentionné : c'est lui qui paie.
    """
    import liens_va as lv
    import podium_discord as pod
    import tickets_discord as tk
    gid = str(gid)
    d = _etat()
    faits = d.setdefault("primes", {})
    bilan = {"dits": [], "sans_adresse": [], "inconnus": []}

    # numéro de VA -> le VA Discord qui le porte
    par_numero = {}
    for cle, l in (lv._etat().get("liens") or {}).items():
        if cle.startswith(f"{gid}:") and l.get("numero"):
            par_numero[int(l["numero"])] = (cle.split(":", 1)[1], l)

    for rang, ligne in enumerate(cl.get("lignes") or []):
        if rang >= len(pod.PRIMES):
            break
        try:
            num = int(str(ligne.get("va", "")).split()[-1])
        except Exception:
            continue
        trouve = par_numero.get(num)
        if not trouve:
            bilan["inconnus"].append(ligne.get("va"))
            continue
        uid, l = trouve
        cle_p = f'{gid}:{uid}:{debut.isoformat()}'
        if faits.get(cle_p):
            continue                       # deja dit cette semaine
        fiche = (tk._etat().get("tickets") or {}).get(f"{gid}:{uid}") or {}
        salon = str(fiche.get("salon") or "")
        if not salon:
            continue
        mid = str(fiche.get("manager") or "")
        adr = adresse_de(gid, uid)
        montant = pod.PRIMES[rang]
        if adr:
            ligne_adr = f"💳 Vers `{adr}`"
        else:
            ligne_adr = ("⚠️ **Aucune adresse enregistrée** — clique "
                         "💳 **Mon adresse USDC** sur le message épinglé.")
            bilan["sans_adresse"].append(l.get("pseudo"))
        code, _r = tk._api("POST", f"/channels/{salon}/messages", json={
            "content": (f"<@{uid}> " + (f"<@{mid}>" if mid else "")).strip(),
            "allowed_mentions": {"users": [uid] + ([mid] if mid else [])},
            "embeds": [{"title": f'{pod.MEDAILLES[rang]} {rang + 1}e de la semaine '
                                 f'— {montant:.2f}$',
                        "color": 0xF1C40F,
                        "description": f'Semaine du **{debut.strftime("%d/%m")}** au '
                                       f'**{fin.strftime("%d/%m")}** · '
                                       f'**{ligne.get("clics")}** subs.\n{ligne_adr}'}]})
        if code == 200:
            faits[cle_p] = int(time.time())
            bilan["dits"].append(f'{l.get("pseudo")} : {montant:.2f}$')
    _ecrire(d)
    return bilan
