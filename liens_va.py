"""Le lien d'un VA : un tracking link MyPuls, et le lien GetMySocial dessus.

Un VA a besoin d'une adresse à poster sur Twitter. Cette adresse doit être à
LUI SEUL, sinon rien ne marche : le podium ne saurait plus qui a amené quel
clic, et MyPuls ne saurait plus quel abonné vient de qui.

La chaîne, dans cet ordre, et l'ordre compte :

1. MyPuls crée le tracking link. C'est lui qui fabrique le code (« c112 ») et
   l'adresse « onlyfans.com/<modèle>/c112 ». L'API publique ne sait que LIRE —
   la création vit dans l'interface, on passe donc par la session à cookies,
   comme le fait déjà le rafraîchissement des pushs.
2. GetMySocial crée le lien court qui pointe dessus, nommé « va_@pseudo », dans
   l'espace des VA. C'est ce lien-là que compte le podium.

MYPULS NE SAIT PAS SUPPRIMER UN TRACKING LINK. Aucune route de suppression
n'existe dans son interface. Un lien créé par erreur reste là pour toujours :
d'où le garde-fou d'unicité — on refuse plutôt que de créer un doublon — et le
refus net quand la configuration manque, plutôt que de deviner une modèle.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "liens_va_config.json"
ETAT_FICHIER = DATA_DIR / "liens_va.json"

EQUIPE_VA = "tm_6ab46ebb11a0232c11211b1a"     # EMY TWITTER

# Un lien GetMySocial est lu par des gens sur Twitter : il doit ressembler au
# compte, pas a une reference interne. D'ou des mots doux plutot qu'un tirage
# au hasard. La base vient de la modele (« emy »), le reste de cette liste.
MOTS_DOUX = ("cute", "lovee", "baby", "angel", "honey", "sweet", "bby", "doll",
             "cherry", "peachy", "bunny", "kitty", "candy", "lovely", "sugar",
             "dreamy", "starr", "pearl", "cutie", "babe", "kisses", "sweetie",
             "princess", "lil", "berry", "bloom", "glow", "velvet", "coco")


def mots_doux(base: str, essai: int = 0) -> str:
    """« emycute », « emylovee »… Un shortcode qui a l'air d'un vrai compte.

    Au-dela de la liste, on recommence avec un chiffre : « emycute2 ». Mieux
    vaut un chiffre qu'un tirage illisible — le lien se lit a voix haute.
    """
    base = re.sub(r"[^a-z0-9]+", "", str(base or "emy").lower())[:12] or "emy"
    mot = MOTS_DOUX[essai % len(MOTS_DOUX)]
    tour = essai // len(MOTS_DOUX)
    return f"{base}{mot}" + (str(tour + 1) if tour else "")


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    """{creator_id, modele, equipe, gabarit} — ce qu'il faut savoir avant de créer."""
    return _lire(CONFIG_FICHIER, {})


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def mypuls_actif() -> bool:
    """La création du tracking link chez MyPuls est-elle autorisée ?

    Fermée par défaut, et par choix : MyPuls ne sait pas supprimer un tracking
    link. Tant que l'interrupteur est fermé, on ne crée que le lien
    GetMySocial, qui se défait, lui.
    """
    return bool(config().get("mypuls_actif"))


def manque() -> str:
    """Ce qui empêche de créer un lien aujourd'hui, en une phrase. « » si tout va."""
    c = config()
    if mypuls_actif() and not c.get("creator_id"):
        return ("aucune créatrice choisie : le tracking link serait créé chez "
                "n'importe qui. À poser dans data/liens_va_config.json "
                "(creator_id, modele).")
    if not c.get("gabarit"):
        return ("aucun lien gabarit GetMySocial pour l'espace des VA : la "
                "création copie un lien existant (boutons, pixels, design). "
                "À poser dans data/liens_va_config.json (gabarit).")
    return ""


# ─── MyPuls : le tracking link ───────────────────────────────────────────
def creer_tracking(nom: str, creator_id: Optional[int] = None) -> Dict[str, Any]:
    """Crée un tracking link chez MyPuls. Rend {ok, url, code, erreur}.

    Le lien est créé pour la créatrice SÉLECTIONNÉE : on bascule d'abord, sinon
    il atterrit chez la précédente — et on ne peut pas l'effacer ensuite.
    """
    import mypuls
    cid = int(creator_id or config().get("creator_id") or 0)
    if not cid:
        return {"ok": False, "erreur": "aucune créatrice choisie"}
    nom = str(nom or "").strip()[:60]
    if not nom:
        return {"ok": False, "erreur": "nom vide"}

    s = mypuls._make_session()
    if s is None:
        return {"ok": False, "erreur": "session MyPuls indisponible (cookies)"}
    try:
        s.get(f"{mypuls.BASE_URL}/switch-creator/{cid}?from=app_pushs",
              timeout=mypuls.TIMEOUT, allow_redirects=True)
        page = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
        jeton = ""
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        if m:
            jeton = m.group(1)
        avant = {l["code"] for l in _tracking_de(s, page.text)}
        r = s.post(f"{mypuls.BASE_URL}/tracking-stats/create",
                   data={"name": nom, "_token": jeton},
                   headers={"X-CSRF-TOKEN": jeton,
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json"},
                   timeout=mypuls.TIMEOUT)
        mypuls._save_rotated_cookies(s)
        if r.status_code != 200:
            return {"ok": False, "erreur": f"MyPuls a refusé (HTTP {r.status_code})"}
        try:
            rep = r.json()
        except Exception:
            return {"ok": False, "erreur": "MyPuls a répondu autre chose que du JSON "
                                           "(session expirée ?)"}
        if not rep.get("success"):
            return {"ok": False, "erreur": str(rep.get("message") or "refus MyPuls")[:140]}

        # MyPuls ne rend pas toujours le lien créé : on relit la page et on
        # prend celui qui n'y était pas. Deviner le code (« le dernier + 1 »)
        # donnerait une adresse qui n'existe pas.
        page2 = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
        neufs = [l for l in _tracking_de(s, page2.text) if l["code"] not in avant]
        vise = [l for l in neufs if l["nom"] == nom] or neufs
        if not vise:
            return {"ok": False, "erreur": "créé, mais introuvable à la relecture — "
                                           "à vérifier à la main dans MyPuls"}
        return {"ok": True, "url": vise[0]["url"], "code": vise[0]["code"], "erreur": ""}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:120]}"}


def _tracking_de(session, html: str):
    """Les tracking links lus dans la page : [{code, nom, url}]."""
    out, vus = [], set()
    for m in re.finditer(r'https://onlyfans\.com/([A-Za-z0-9._-]+)/(c\d+)', html):
        code = m.group(2)
        if code in vus:
            continue
        vus.add(code)
        out.append({"code": code, "nom": "", "url": m.group(0)})
    return out


# ─── GetMySocial : le lien court ─────────────────────────────────────────
def creer_gms(nom: str, url: str) -> Dict[str, Any]:
    """Duplique le gabarit vers un lien neuf pointant sur `url`.

    Le duplicata garde les boutons, les pixels et le design du gabarit, et
    reste dans le meme espace : seules la destination et le nom changent.
    """
    import gms
    c = config()
    gabarit = str(c.get("gabarit") or "")
    equipe = str(c.get("equipe") or EQUIPE_VA)
    base = str(c.get("base_shortcode") or c.get("modele") or "emy")
    if not gabarit:
        return {"ok": False, "erreur": "aucun gabarit GetMySocial"}
    for essai in range(12):
        sc = mots_doux(base, essai)
        r = gms.duplicate_link(gabarit, sc, nom, url, equipe)
        if r.get("ok"):
            lien = r.get("link") or {}
            return {"ok": True, "shortcode": sc,
                    "url": f"{gms.PUBLIC_LINK_DOMAIN}/{sc}",
                    "id": str(lien.get("id") or ""), "erreur": ""}
        # « shortcode deja pris » est le seul echec qu'on repasse : tout le
        # reste (droits, gabarit absent) se repeterait a l'identique
        if "shortcode" not in str(r.get("error") or "").lower():
            return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    return {"ok": False, "erreur": "douze noms essayés, tous pris"}


def groupe_manager(equipe: str, nom: str) -> str:
    """L'identifiant du groupe GetMySocial au nom du manager, créé s'il manque.

    Ranger les liens par manager, c'est retrouver d'un coup d'œil qui suit qui
    — et repérer celui qui n'a plus personne. Le groupe est cherché par son
    nom avant d'être créé : deux groupes « YAZID » seraient pires que zéro.
    """
    import gms
    nom = str(nom or "").strip()[:40]
    if not nom:
        return ""
    try:
        deja = gms.group_id_by_name(equipe, nom)
        if deja:
            return str(deja)
        r = gms._call_tool("create_group", {"name": nom, "team_id": equipe})
        if not r.get("ok"):
            print(f"[lien] groupe « {nom} » non créé : {str(r.get('error'))[:100]}",
                  flush=True)
            return ""
        d = r.get("data") or {}
        if isinstance(d, dict):
            g = d.get("group") if isinstance(d.get("group"), dict) else d
            gid = g.get("id") or g.get("_id") or g.get("groupId") or ""
            if gid:
                return str(gid)
        # créé mais identifiant illisible : on relit plutôt que d'abandonner
        return str(gms.group_id_by_name(equipe, nom) or "")
    except Exception as e:
        print(f"[lien] groupe « {nom} » : {type(e).__name__}: {e}", flush=True)
        return ""


def ranger(equipe: str, link_id: str, nom_groupe: str) -> str:
    """Range un lien dans le groupe du manager. Rend le nom rangé, ou « »."""
    import gms
    if not (link_id and nom_groupe):
        return ""
    gid = groupe_manager(equipe, nom_groupe)
    if not gid:
        return ""
    try:
        r = gms.assign_link_to_group(link_id, gid, team_id=equipe)
        if r.get("ok"):
            return nom_groupe
        print(f"[lien] rangement refusé : {str(r.get('error'))[:100]}", flush=True)
    except Exception as e:
        print(f"[lien] rangement : {type(e).__name__}: {e}", flush=True)
    return ""


def numero_de(pseudo: str) -> int:
    """Le numero de VA, pris dans la table du podium — une seule source.

    Reserve avant la creation, parce que le nom du tracking link le porte
    (« Twitter VA 1 @abdoul »). Un second essai pour le meme pseudo retombe
    sur le meme numero : la table est indexee par le pseudo.
    """
    try:
        import podium_discord as pod
        return int(pod.numeros([pseudo], attribuer=True).get(pseudo) or 0)
    except Exception as e:
        print(f"[lien] numero de VA indisponible : {type(e).__name__}: {e}", flush=True)
        return 0


# ─── la chaîne ───────────────────────────────────────────────────────────
def lien_de(gid: str, uid: str) -> Dict[str, Any]:
    return (_etat().get("liens") or {}).get(f"{gid}:{uid}") or {}


def creer_pour(gid: str, uid: str, pseudo: str, par: str = "",
               manager: str = "") -> Dict[str, Any]:
    """Toute la chaîne pour un VA. Rend {ok, public_url, tracking, erreur}.

    Refuse si ce VA en a déjà un : MyPuls ne sait pas supprimer, un doublon
    resterait à vie et fausserait les deux classements.
    """
    import time as _t
    deja = lien_de(gid, uid)
    if deja.get("public_url"):
        return {"ok": False, "deja": True, "erreur": "ce VA a déjà un lien",
                "public_url": deja["public_url"], "tracking": deja.get("tracking", "")}
    empeche = manque()
    if empeche:
        return {"ok": False, "erreur": empeche}

    n = numero_de(pseudo)
    if not n:
        return {"ok": False, "erreur": "numéro de VA indisponible : rien n'a été créé"}

    # Le meme nom des deux cotes : « Twitter VA 1 @abdoul ». Le podium
    # retrouve la personne derriere l'arobase, donc rien a reconcilier.
    t = {"ok": True, "url": "", "code": ""}
    if mypuls_actif():
        t = creer_tracking(f"Twitter VA {n} @{pseudo}"[:60])
        if not t.get("ok"):
            return {"ok": False, "erreur": "MyPuls : " + t.get("erreur", "")}
    # sans URL, le duplicata garde la destination du gabarit : le lien marche
    # et ses clics sont comptes a part, mais l'abonne n'est pas encore
    # rattache a CE VA chez MyPuls. C'est dit au manager, pas cache.
    g = creer_gms(f"Twitter VA {n} @{pseudo}"[:60], t["url"])
    if not g.get("ok"):
        if t.get("url"):
            # le tracking link est créé et ne peut pas être défait : on le DIT,
            # pour qu'il soit repris à la main plutôt que perdu
            return {"ok": False, "tracking": t["url"],
                    "erreur": f'GetMySocial : {g.get("erreur")} — le tracking link '
                              f'{t["code"]} existe déjà chez MyPuls, à réutiliser.'}
        return {"ok": False, "erreur": "GetMySocial : " + str(g.get("erreur") or "")}
    # rangé au nom du manager : un lien perdu dans « Ungrouped » n'apprend rien
    groupe = ranger(str(config().get("equipe") or EQUIPE_VA), g.get("id", ""), manager)

    d = _etat()
    (d.setdefault("liens", {}))[f"{gid}:{uid}"] = {
        "pseudo": pseudo, "numero": n, "groupe": groupe, "manager": manager,
        "public_url": g["url"], "shortcode": g["shortcode"],
        "tracking": t["url"], "code": t["code"], "par": str(par),
        "quand": int(_t.time())}
    _ecrire(d)
    return {"ok": True, "numero": n, "public_url": g["url"], "groupe": groupe,
            "shortcode": g["shortcode"], "tracking": t["url"],
            "provisoire": not mypuls_actif(), "erreur": ""}
