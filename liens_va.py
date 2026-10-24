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
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

import contextlib as _contextlib

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "liens_va_config.json"
ETAT_FICHIER = DATA_DIR / "liens_va.json"

EQUIPE_VA = "tm_6ab46ebb11a0232c11211b1a"     # EMY TWITTER
TWITTER_ID = "1445108485090971710"
THREADS_ID = "1498948161039896586"

# YouLab THREADS a SON espace : ranger ses liens dans EMY TWITTER les
# melangerait aux liens Twitter, dans le podium comme dans la paie.
# Proprietaire, 13/10/2026 : « pour Threads c'est pas avec un lien de
# tracking, faut juste dupliquer le lien de VA Threads » — emythreads, l'A/B
# seren/emy 50/50. Le duplicata garde l'A/B (verifie : 13 seren / 17 emy sur
# 30 visiteurs). Surchargeable par la cle « threads » de liens_va_config.json.
# « sans_prenom » : l'adresse du lien ne porte aucun prénom (mots_sans_prenom).
ESPACE_THREADS = {"equipe": "tm_6ab51e03b299b7e3ba6ff7bf",      # EMY THREADS
                  "gabarit": "lnk_6acdd0a53fb996c565a47e90",    # getmysocial.com/emythreads
                  "sans_prenom": True, "plateforme": "Threads",
                  # la copie temporaire d'une variante part d'ici, pas du
                  # gabarit : emythreads porte lui-même un A/B, emythreadsb
                  # (Emy, deeplink Threads) n'en a pas
                  "source_variante": "lnk_6acdd2c93fb996c565a48982",
                  # l'espace n'a QUE les groupes des managers (synchroniser,
                  # étape 3) : « de base y avait 2 groupes et c'est tout »
                  "groupes_managers_seuls": True}

# Twitter, 14/10/2026 : le meme 50/50 que emythreads, mais chaque moitie au
# tracking du VA. Proprietaire : « exactement le meme lien juste pour Twitter,
# le mec il a son tracking link », puis « avec 2 tracking links, un pour Emy et
# un pour Seren ». Le lien garde son tracking Emy (creator_id de la config) ;
# `poids` % des visiteurs partent sur SON tracking Seren (poser_variante).
# Surchargeable par la cle « variante » de liens_va_config.json ; {} ou false
# l'eteint pour les liens a venir.
VARIANTE_TWITTER = {"modele": "Seren", "creator_id": 3867, "poids": 50}

# Agency VA INSTAGRAM (22/10/2026), « comme Twitter » : espace EMY IG (« MIG »
# à l'oral), tracking MyPuls chez Emy au nom du VA, 100 % Emy, jamais de
# variante. D'abord un lien direct (« pour le moment mets juste le lien
# direct »), puis, le 23/10 : « mets la landing de base, comme dans Youl4b le
# retour de Jessye » — la page « Emy ♡ » de JESSY LE RETOUR (template arthur),
# copiée, son bouton OnlyFans vers le tracking du VA (_poser_tracking). Le
# gabarit vit DANS EMY IG (« emyigbase », recopie à l'identique d'une landing
# de JESSY LE RETOUR, bouton vers le profil d'Emy) : GetMySocial refuse de
# copier un lien d'une autre équipe (« link_not_in_team », constaté le 23/10).
# Sans gabarit, le lien direct revient. Surchargeable par la clé « agency_ig »
# de liens_va_config.json.
AGENCY_IG_ID = "1488331963575177247"
ESPACE_AGENCY_IG = {"equipe": "tm_6ada83b07218da6450e65862",      # EMY IG
                    # « emyigbase » : la page Emy ♡ de JESSY LE RETOUR, dans EMY IG
                    "gabarit": "lnk_6ada9ed9cf84f313d19d14ae", "landing": True,
                    "direct": True,
                    "sans_prenom": True, "plateforme": "Instagram",
                    # le lien est ouvert depuis Instagram : sortir de son
                    # navigateur intégré dès la page chargée, comme les liens
                    # de Threads (propriétaire, 23/10/2026 : « active le deeplink »)
                    "deeplink": "pageload",
                    # la moitié Seren (24/10/2026) : copie de « emyigserenbase »,
                    # lien direct d'EMY IG vers onlyfans.com/seren.vale, sa
                    # destination remplacée par le tracking Seren du VA
                    "source_variante": "lnk_6adc91b2c2f08bda9012135f"}

# Les serveurs Discord dont les VA ont un lien GetMySocial (voir espace()).
SERVEURS = {TWITTER_ID, THREADS_ID, AGENCY_IG_ID}

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


#: Les mots doux de Threads : ceux qui se lisent bien avec deux y (« angelyy »,
#: « cherryy »). Pas « lovee », « sweetie », « kisses », « princess » :
#: « loveeyy », « kissesyy » ne ressemblent plus à un compte. Une longueur
#: (25) première avec les pas de mots_sans_prenom (7 et 37).
MOTS_THREADS = ("angel", "cute", "baby", "honey", "sweet", "doll", "cherry", "peachy",
                "bunny", "kitty", "candy", "lovely", "sugar", "dreamy", "starr", "pearl",
                "babe", "lil", "berry", "bloom", "glow", "velvet", "coco", "bby", "cutie")


def _deux_y(mot: str) -> str:
    """« angel » → « angelyy », « honey » → « honeyy » : deux y à la fin."""
    return mot + ("y" if mot.endswith("y") else "yy")


#: Essais d'adresse avant d'abandonner. Les adresses GetMySocial sont communes
#: à tous les comptes : le 15/10/2026, pour le VA 71, les douze premiers mots
#: seuls (« velvetyy », « honeyy », « candyy »…) étaient TOUS pris, et la
#: création comme le renommage abandonnaient. Après les 25 mots seuls viennent
#: les paires (« angelpearlyy »), presque toujours libres.
ESSAIS_ADRESSE = 60


def mots_sans_prenom(graine: str, essai: int = 0) -> str:
    """« angelyy », « cuteyy », « bunnyy »… Une adresse SANS prénom (Threads).

    Propriétaire, 13/10/2026, pour Threads : « il ne doit pas y avoir de emy,
    ça doit être sans nom », « genre angel, vraiment sans prénom » — le
    premier lien créé était sorti « emyangel » —, puis « tu peux mettre genre
    deux y à la fin ». Un mot doux et deux y. Les adresses GetMySocial sont
    communes à tous les comptes : un mot seul est presque toujours pris
    (« cute », « baby » : 403), avec deux y bien moins (« angelyy »,
    « cuteyy », « bunnyy » libres le 13/10 ; « honeyy », « dollyy » pris).
    Chaque mot de MOTS_THREADS une fois, puis deux mots doux et deux y, jamais le
    même deux fois. Le point de départ dépend du lien (`graine`, son nom) :
    deux VA qui créent leur lien n'usent pas leurs essais sur les mêmes noms.
    """
    n = len(MOTS_THREADS)
    h = int(hashlib.md5(str(graine or "").encode("utf-8")).hexdigest(), 16)
    if essai < n:
        # 7 est premier avec la longueur de la liste : chaque mot passe une fois
        return _deux_y(MOTS_THREADS[(h + essai * 7) % n])
    # puis les paires (a, b), a != b ; un pas premier avec leur nombre les
    # parcourt sans retomber deux fois sur la même
    i = (h + (essai - n) * 37) % (n * (n - 1))
    a, b = divmod(i, n - 1)
    if b >= a:
        b += 1
    return _deux_y(MOTS_THREADS[a] + MOTS_THREADS[b])


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


def espace(gid: str = "") -> Dict[str, Any]:
    """Où vivent les liens des VA de ce serveur, et comment on les fabrique :
    {equipe, gabarit, base_shortcode, plateforme, tracking}.

    Un seul endroit qui le décide : créer, couper, supprimer et ranger lisent
    tous ici — deux tables auraient fini par envoyer un lien Threads chez
    Twitter. « tracking » : un tracking link MyPuls avant le lien (Twitter,
    quand l'interrupteur est ouvert) ; jamais sur Threads. « variante » : le
    50/50 vers une autre modèle, chacune à son tracking (Twitter) ; None sans
    tracking — une moitié sans tracking ne serait rattachée à personne.
    """
    c = config()
    # Threads : ses trackings par VA (Emy + Seren, comme Twitter) s'ouvrent
    # par la clé « threads » : {"tracking": true} de la config. La logique vit
    # dans un patch local du VPS (99-threads-mypuls-20261015, 15/10/2026) :
    # ces lignes restent telles quelles pour qu'il s'applique encore.
    if str(gid) == THREADS_ID:
        sur = c.get("threads") if isinstance(c.get("threads"), dict) else {}
        e = dict(ESPACE_THREADS, **{k: v for k, v in sur.items() if v})
        e["tracking"] = False
        e["variante"] = None
        return e
    v = c.get("variante", VARIANTE_TWITTER)
    v = dict(VARIANTE_TWITTER, **v) if isinstance(v, dict) and v else (
        dict(VARIANTE_TWITTER) if v is True else None)
    return {"equipe": str(c.get("equipe") or EQUIPE_VA),
            "gabarit": str(c.get("gabarit") or ""),
            "base_shortcode": str(c.get("base_shortcode") or c.get("modele") or "emy"),
            "plateforme": "Twitter", "tracking": mypuls_actif(),
            # Proprietaire, 14/10/2026, une fois le 50/50 Emy / Seren pose :
            # « pour les noms des liens GMS ca doit pas avoir de nom ». Comme
            # Threads : « angelyy », plus « emycute » — le lien mene aussi chez
            # Seren. Les liens deja postes gardent leur adresse (la changer
            # casserait ce que le VA a mis sur Twitter). Cle « sans_prenom » :
            # false pour revenir a « emy » + mot doux.
            "sans_prenom": bool(c.get("sans_prenom", True)),
            "variante": v if mypuls_actif() else None}


def manque(gid: str = "") -> str:
    """Ce qui empêche de créer un lien aujourd'hui, en une phrase. « » si tout va."""
    c = config()
    e = espace(gid)
    if e["tracking"] and not c.get("creator_id"):
        return ("aucune créatrice choisie : le tracking link serait créé chez "
                "n'importe qui. À poser dans data/liens_va_config.json "
                "(creator_id, modele).")
    if e.get("direct") and not e.get("gabarit"):
        # lien direct (Agency) : il n'a de sens que vers SON tracking
        return "" if e["tracking"] else ("suivi MyPuls fermé : un lien direct sans "
                                         "tracking ne serait rattaché à personne.")
    if not e.get("gabarit"):
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
        return {"ok": False, "refuse": True, "erreur": "aucune créatrice choisie"}
    nom = str(nom or "").strip()[:60]
    if not nom:
        return {"ok": False, "refuse": True, "erreur": "nom vide"}

    s = mypuls._make_session()
    if s is None:
        return {"ok": False, "refuse": True, "erreur": "session MyPuls indisponible (cookies)"}
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
            # LA RAISON, pas seulement le code : le tracking MYM d'Amelia
            # revenait « HTTP 400 » (03/10/2026) sans rien pour savoir quoi
            # changer, et la session MyPuls n'existe que sur le VPS.
            return {"ok": False, "refuse": True,
                    "erreur": f"MyPuls a refusé (HTTP {r.status_code}) : {_raison_refus(r)}"}
        try:
            rep = r.json()
        except Exception:
            return {"ok": False, "erreur": "MyPuls a répondu autre chose que du JSON "
                                           "(session expirée ?)"}
        if not rep.get("success"):
            return {"ok": False, "refuse": True, "erreur": str(rep.get("message") or "refus MyPuls")[:140]}

        # MyPuls ne rend pas toujours le lien créé : on relit la page et on
        # prend celui qui n'y était pas. Deviner le code (« le dernier + 1 »)
        # donnerait une adresse qui n'existe pas.
        page2 = s.get(f"{mypuls.BASE_URL}/tracking-stats/", timeout=mypuls.TIMEOUT)
        neufs = [l for l in _tracking_de(s, page2.text) if l["code"] not in avant]
        vise = [l for l in neufs if l["nom"] == nom] or neufs
        if not vise:
            # l'adresse dans la reponse de creation, si MyPuls la donne
            dedans = _adresse_dans(rep)
            if dedans:
                return {"ok": True, "url": dedans, "code": "", "erreur": ""}
            return {"ok": False, "reponse": rep,
                    "erreur": "créé, mais introuvable à la relecture — à vérifier à la main dans MyPuls"}
        return {"ok": True, "url": vise[0]["url"], "code": vise[0]["code"], "erreur": ""}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:120]}"}


def _tracking_existant(nom: str, creator_id: int) -> Optional[Dict[str, Any]]:
    """{url, code} du tracking déjà nommé `nom` chez cette créatrice (API
    MyPuls, toutes ses pages), None s'il n'y en a pas ou si l'API se tait."""
    try:
        import mypuls
        for page in range(1, 6):
            res = mypuls.api_get("tracking-links", {"per_page": 500, "page": page})
            if not res.get("ok"):
                return None
            d = res.get("data")
            items = d.get("data") if isinstance(d, dict) else d
            items = [it for it in (items or []) if isinstance(it, dict)]
            for it in items:
                if (str(it.get("creator_id")) == str(int(creator_id))
                        and str(it.get("name") or "").strip() == nom and it.get("url")):
                    return {"url": str(it["url"]), "code": str(it.get("code") or "")}
            if len(items) < 500:
                break
    except Exception as e:                                   # noqa: BLE001
        print(f"[lien] recherche du tracking « {nom} » : {type(e).__name__}: {e}", flush=True)
    return None


def _creer_ou_reprendre(nom: str, creator_id: Optional[int] = None) -> Dict[str, Any]:
    """Le tracking `nom` chez cette créatrice : celui qui existe déjà, sinon un
    neuf. MyPuls ne supprime rien : un essai raté après la création (VA 75 et
    76, 15/10/2026 : « créé, mais introuvable à la relecture ») laissait un
    tracking au nom du VA ; le clic suivant en créait un second, à vie."""
    cid = int(creator_id or config().get("creator_id") or 0)
    if cid:
        ex = _tracking_existant(nom, cid)
        if ex:
            print(f"[lien] tracking « {nom} » déjà chez MyPuls ({ex['url']}) : repris", flush=True)
            return {"ok": True, "url": ex["url"], "code": ex["code"], "repris": True, "erreur": ""}
    return creer_tracking(nom, creator_id) if creator_id else creer_tracking(nom)


def _raison_refus(r) -> str:
    """Le message d'une reponse MyPuls en erreur (JSON Laravel : message +
    errors par champ), sinon le debut du texte brut."""
    try:
        d = r.json()
        if isinstance(d, dict):
            morceaux = [str(d.get("message") or "")]
            for champ, msgs in (d.get("errors") or {}).items():
                morceaux.append(f"{champ}: {' '.join(map(str, msgs)) if isinstance(msgs, list) else msgs}")
            txt = " | ".join(m for m in morceaux if m)
            if txt:
                return txt[:300]
    except Exception:                                        # noqa: BLE001
        pass
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text or ""))[:300] or "réponse vide"


def _adresse_dans(o) -> str:
    """Une adresse OnlyFans / MYM n'importe ou dans une reponse JSON."""
    if isinstance(o, str):
        return o if re.match(r"https?://(www\.)?(onlyfans\.com|mym\.(fans|me))/", o) else ""
    vals = o.values() if isinstance(o, dict) else (o if isinstance(o, list) else [])
    for v in vals:
        a = _adresse_dans(v)
        if a:
            return a
    return ""


def _tracking_de(session, html: str):
    """Les tracking links lus dans la page : [{code, nom, url}]. Les adresses
    MYM aussi (le 03/10/2026, un tracking MYM cree etait « introuvable a la
    relecture » : seules les adresses OnlyFans etaient lues) -- leur code est
    l'adresse entiere, la comparaison avant/apres ne garde que la nouvelle."""
    out, vus = [], set()
    # LE NOM DE CHAQUE TRACKING, lu sur sa ligne du tableau
    # (<tr id="row-link-N"> … <div class="fw-bold">NOM</div> … l'adresse).
    # Il restait vide : depuis la garde du 15/10/2026 (patch local du VPS,
    # 99-z-tracking-creator-guard), qui ne retient plus que le tracking AU BON
    # NOM, chaque création « créé, mais introuvable à la relecture » — le
    # tracking existait chez MyPuls (VA 75 c83, VA 76 c84), le lien jamais.
    import html as _html
    for r in re.finditer(r'<tr id="row-link-\d+"(.*?)</tr>', html or "", re.S):
        ligne = r.group(1)
        n = re.search(r'<div class="fw-bold">\s*(.*?)\s*</div>', ligne, re.S)
        nom = _html.unescape(re.sub(r"<[^>]+>", "", n.group(1))).strip() if n else ""
        o = re.search(r'https://onlyfans\.com/([A-Za-z0-9._-]+)/(c\d+)', ligne)
        if o and o.group(2) not in vus:
            vus.add(o.group(2))
            out.append({"code": o.group(2), "nom": nom, "url": o.group(0)})
            continue
        y = re.search(r'https?://(?:www\.)?mym\.(?:fans|me)/[A-Za-z0-9._~/?=&%-]+', ligne)
        if y:
            url = y.group(0).rstrip("/.&?")
            if url not in vus:
                vus.add(url)
                out.append({"code": url, "nom": nom, "url": url})
    # ce que le tableau n'a pas donné (page d'une autre forme) : par l'adresse
    for m in re.finditer(r'https://onlyfans\.com/([A-Za-z0-9._-]+)/(c\d+)', html):
        code = m.group(2)
        if code in vus:
            continue
        vus.add(code)
        out.append({"code": code, "nom": "", "url": m.group(0)})
    for m in re.finditer(r'https?://(?:www\.)?mym\.(?:fans|me)/[A-Za-z0-9._~/?=&%-]+', html):
        url = m.group(0).rstrip("/.&?")
        if url in vus:
            continue
        vus.add(url)
        out.append({"code": url, "nom": "", "url": url})
    return out


def _sous_bascule(creer):
    """creer_tracking sous mypuls._OF_SWITCH_LOCK.

    MyPuls ne retient QU'UNE créatrice par session : une bascule d'un autre
    relevé (files OF, pushs MYM, subs MYM de subs_va) entre la nôtre et la
    création poserait le tracking chez elle — et il ne s'efface jamais.
    Posé en enveloppe, pas dans le corps : les patchs locaux du VPS
    (99-z-tracking-creator-guard) réécrivent ce corps, une ligne de plus
    dedans les ferait tomber en silence."""
    import functools

    @functools.wraps(creer)
    def enveloppe(*a, **kw):
        try:
            import mypuls
            verrou = getattr(mypuls, "_OF_SWITCH_LOCK", None) or _contextlib.nullcontext()
        except Exception:                                    # noqa: BLE001
            verrou = _contextlib.nullcontext()
        with verrou:
            return creer(*a, **kw)
    enveloppe.brut = creer
    return enveloppe


creer_tracking = _sous_bascule(creer_tracking)


# ─── GetMySocial : le lien court ─────────────────────────────────────────
def creer_gms(nom: str, url: str, gid: str = "") -> Dict[str, Any]:
    """Duplique le gabarit de l'espace du serveur vers un lien neuf.

    Le duplicata garde les boutons, les pixels, l'A/B et le design du gabarit,
    et reste dans le meme espace : seul le nom change, et la destination
    quand `url` est donnee (« » : celle du gabarit, voulu sur Threads).
    """
    import gms
    e = espace(gid)
    gabarit = str(e.get("gabarit") or "")
    equipe = str(e.get("equipe") or EQUIPE_VA)
    base = str(e.get("base_shortcode") or "emy")
    direct = bool(e.get("direct") and not gabarit)
    if direct and not url:
        return {"ok": False, "erreur": "lien direct sans destination"}
    if not gabarit and not direct:
        return {"ok": False, "erreur": "aucun gabarit GetMySocial"}
    for essai in range(ESSAIS_ADRESSE):
        # Threads et Twitter : aucune base, aucun prénom (voir mots_sans_prenom)
        sc = mots_sans_prenom(nom, essai) if e.get("sans_prenom") else mots_doux(base, essai)
        landing = bool(e.get("landing") and gabarit)
        r = (gms.create_directlink(sc, url, nom, team_id=equipe,
                                   deeplink_mode=str(e.get("deeplink") or "")) if direct
             # une landing ne prend pas d'URL : son bouton, plus bas
             else gms.duplicate_link(gabarit, sc, nom, "" if landing else url, equipe))
        if r.get("ok"):
            lien = r.get("link") or {}
            lid = str(lien.get("id") or "")
            if landing:
                pose = _poser_tracking(lid, url, nom, equipe)
                if not pose.get("ok"):
                    # la copie garde le tracking d'un autre VA (celui du
                    # gabarit) : coupée, jamais donnée — ni supprimée
                    gms.disable_link(lid)
                    return {"ok": False, "erreur": f"landing {sc} copiée mais bouton non posé "
                                                   f"({pose.get('erreur')}) : copie coupée"}
            return {"ok": True, "shortcode": sc,
                    "url": f"{gms.PUBLIC_LINK_DOMAIN}/{sc}",
                    "id": lid, "erreur": ""}
        # « shortcode deja pris » est le seul echec qu'on repasse : tout le
        # reste (droits, gabarit absent) se repeterait a l'identique
        if "shortcode" not in str(r.get("error") or "").lower():
            return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    return {"ok": False, "erreur": f"{ESSAIS_ADRESSE} noms essayés, tous pris"}


#: Un bouton de la landing qui mène chez OnlyFans : celui qui reçoit le
#: tracking du VA (la page de JESSY LE RETOUR n'en a qu'un).
_RE_OF = re.compile(r"https?://(?:www\.)?onlyfans\.com/", re.I)


def _poser_tracking(lid: str, tracking: str, nom: str, equipe: str) -> Dict[str, Any]:
    """Le bouton OnlyFans d'une landing copiée vers `tracking`, relu ensuite.
    Les boutons sont renvoyés tels quels (update_link remplace tout le
    tableau), seule leur adresse change. Rend {ok, erreur}."""
    import gms
    if not (lid and tracking):
        return {"ok": False, "erreur": "lien ou tracking manquant"}
    lu = gms._call_tool("get_link", {"link_id": lid, "team_id": equipe})
    copie = lu.get("data") if lu.get("ok") else None
    if isinstance(copie, dict) and isinstance(copie.get("data"), dict) and "buttons" not in copie:
        copie = copie["data"]
    boutons = (copie or {}).get("buttons") if isinstance(copie, dict) else None
    if not boutons:
        return {"ok": False, "erreur": "copie illisible ou sans bouton"}
    neufs = []
    for b in boutons:
        b2 = dict(b)
        if _RE_OF.match(str(b2.get("url") or "")):
            b2["url"] = tracking
        neufs.append(b2)
    if not any(b.get("url") == tracking for b in neufs):
        return {"ok": False, "erreur": "aucun bouton OnlyFans sur la landing"}
    r = gms._call_tool("update_link", {"link_id": lid, "team_id": equipe,
                                       "display_name": nom[:60], "buttons": neufs})
    if not r.get("ok"):
        return {"ok": False, "erreur": str(r.get("error") or "update_link refusé")[:120]}
    relu = gms._call_tool("get_link", {"link_id": lid, "team_id": equipe})
    d = relu.get("data") if relu.get("ok") else None
    if isinstance(d, dict) and isinstance(d.get("data"), dict) and "buttons" not in d:
        d = d["data"]
    restes = [b.get("url") for b in ((d or {}).get("buttons") or []) if isinstance(d, dict)
              and _RE_OF.match(str(b.get("url") or "")) and b.get("url") != tracking]
    if not isinstance(d, dict) or restes:
        return {"ok": False, "erreur": f"relu : bouton(s) encore ailleurs {restes[:2]}"}
    return {"ok": True}


def groupes(equipe: str, essais: int = 3) -> Optional[Dict[str, str]]:
    """{nom en minuscules: identifiant} des groupes d'un espace. None si on ne sait pas.

    Passe par l'outil MCP, PAS par `gms.group_id_by_name` : celui-ci interroge
    l'API privée avec un cookie de session que le serveur n'a pas — il rendait
    donc « aucun groupe », et chaque clic aurait fabriqué un « YAZID » de plus.

    None et {} veulent dire deux choses différentes : « je ne sais pas » et
    « il n'y en a aucun ». Confondre les deux, c'est créer à l'aveugle.
    """
    import time as _t
    import gms
    for essai in range(max(1, essais)):
        r = gms._call_tool("list_groups", {"team_id": equipe})
        if r.get("ok"):
            d = r.get("data") or {}
            items = d.get("data") if isinstance(d, dict) else d
            out: Dict[str, str] = {}
            for g in (items or []):
                if isinstance(g, dict) and g.get("name") and g.get("id"):
                    out[str(g["name"]).strip().lower()] = str(g["id"])
            return out
        # l'outil est limité en débit : on laisse passer l'orage une fois
        if "429" in str(r.get("error") or "") and essai + 1 < essais:
            _t.sleep(22)
            continue
        return None
    return None


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
        connus = groupes(equipe)
        if connus is None:
            # On ne SAIT PAS ce qui existe : creer a l'aveugle ferait un
            # deuxieme « YAZID » a chaque clic. On renonce au rangement, le
            # lien lui-meme est deja cree et ne risque rien.
            print(f"[lien] groupes illisibles : « {nom} » non rangé cette fois",
                  flush=True)
            return ""
        deja = connus.get(nom.lower())
        if deja:
            return deja
        r = gms._call_tool("create_group", {"name": nom, "team_id": equipe})
        if not r.get("ok"):
            print(f"[lien] groupe « {nom} » non créé : {str(r.get('error'))[:100]}",
                  flush=True)
            return ""
        d = r.get("data") or {}
        g = d.get("group") if isinstance(d, dict) and isinstance(d.get("group"), dict) else d
        gid = (g or {}).get("id") or (g or {}).get("_id") or (g or {}).get("groupId") or ""
        if gid:
            return str(gid)
        # créé mais identifiant illisible : on relit plutôt que d'abandonner
        return (groupes(equipe) or {}).get(nom.lower(), "")
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
    empeche = manque(gid)
    if empeche:
        return {"ok": False, "erreur": empeche}
    e = espace(gid)

    n = numero_de(pseudo)
    if not n:
        return {"ok": False, "erreur": "numéro de VA indisponible : rien n'a été créé"}

    # Le meme nom des deux cotes : « Twitter VA 1 @abdoul ». Le podium
    # retrouve la personne derriere l'arobase, donc rien a reconcilier.
    # Threads : « Threads VA 1 @abdoul », le meme numero (une seule table).
    nom = f'{e["plateforme"]} VA {n} @{pseudo}'[:60]
    t = {"ok": True, "url": "", "code": ""}
    if e["tracking"]:
        t = _creer_ou_reprendre(nom)
        if not t.get("ok"):
            return {"ok": False, "erreur": "MyPuls : " + t.get("erreur", "")}
    # sans URL, le duplicata garde la destination du gabarit. Sur Twitter :
    # le lien marche et ses clics sont comptes a part, mais l'abonne n'est pas
    # encore rattache a CE VA chez MyPuls — dit au manager, pas cache. Sur
    # Threads, c'est le but : la copie de emythreads, A/B compris.
    g = creer_gms(nom, t["url"], gid)
    if not g.get("ok"):
        if t.get("url"):
            # le tracking link est créé et ne peut pas être défait : on le DIT,
            # pour qu'il soit repris à la main plutôt que perdu
            return {"ok": False, "tracking": t["url"],
                    "erreur": f'GetMySocial : {g.get("erreur")} — le tracking link '
                              f'{t["code"]} existe déjà chez MyPuls, à réutiliser.'}
        return {"ok": False, "erreur": "GetMySocial : " + str(g.get("erreur") or "")}
    # rangé au nom du manager : un lien perdu dans « Ungrouped » n'apprend rien
    groupe = ranger(str(e["equipe"]), g.get("id", ""), manager)

    d = _etat()
    (d.setdefault("liens", {}))[f"{gid}:{uid}"] = {
        "pseudo": pseudo, "numero": n, "groupe": groupe, "manager": manager,
        # garde l'identifiant GetMySocial : le deplacement s'en sert, et le
        # retrouver par shortcode coute une liste entiere a chaque fois
        "link_id": g.get("id", ""),
        "public_url": g["url"], "shortcode": g["shortcode"],
        "tracking": t["url"], "code": t["code"], "par": str(par),
        "quand": int(_t.time())}
    _ecrire(d)
    # le 50/50 APRES le lien : un echec ici laisse un lien qui marche (tout
    # chez la premiere modele), note dans la fiche et repris par
    # reprendre_variantes ; dans l'autre ordre, un echec GetMySocial aurait
    # laisse deux trackings MyPuls orphelins au lieu d'un
    var = None
    if e.get("variante"):
        try:
            rv = poser_variante(gid, uid)
        except Exception as ex:                              # noqa: BLE001
            # le lien est cree et note : une exception ici ne doit pas faire
            # croire au manager que rien n'a marche
            rv = {"ok": False, "erreur": f"{type(ex).__name__}: {str(ex)[:120]}"}
        var = {"ok": bool(rv.get("ok")), "modele": e["variante"]["modele"],
               "poids": int(e["variante"]["poids"]), "tracking": rv.get("tracking", ""),
               "cookie": bool(rv.get("cookie")), "erreur": rv.get("erreur", "")}
    elif SEREN_EN_PAUSE and g.get("id"):
        # Threads : le lien neuf est une copie de emythreads, 50/50 Seren
        # compris. Éteint tout de suite ; raté (cookie), couper_seren le
        # reprend à la synchro suivante.
        try:
            _couper_lien(str(gid), str(e["equipe"]), g["id"], g.get("shortcode", ""),
                         nom, f"{gid}:{uid}")
        except Exception as ex:                              # noqa: BLE001
            print(f"[lien] Seren en pause : {g.get('shortcode')} : {type(ex).__name__}: {ex}",
                  flush=True)
    return {"ok": True, "numero": n, "public_url": g["url"], "groupe": groupe,
            "shortcode": g["shortcode"], "tracking": t["url"],
            # Threads n'a pas de tracking link a venir : rien de provisoire
            "provisoire": e["plateforme"] == "Twitter" and not e["tracking"],
            "plateforme": e["plateforme"], "variante": var, "erreur": ""}


# ─── le 50/50 de Twitter : la moitié des visiteurs chez une autre modèle ─────
def _sans_prefixe(lid: Any) -> str:
    s = str(lid or "").strip()
    return s[4:] if s.startswith("lnk_") else s


def poser_variante(gid: str, uid: str) -> Dict[str, Any]:
    """Branche le 50/50 sur le lien d'un VA : `poids` % de ses visiteurs
    partent sur SON tracking chez la modèle de la variante (Seren).
    Rend {ok, tracking, cookie, erreur}.

    GetMySocial ne prend pas d'URL pour une variante : elle COPIE un autre
    lien, à l'enregistrement. D'où un lien temporaire vers le tracking Seren,
    copié dans l'A/B puis supprimé. Vérifié le 14/10/2026 sur un lien d'essai
    d'EMY TWITTER : 24 / 16 sur 40 visiteurs, et toujours 24 / 16 une fois la
    source modifiée puis supprimée — la copie est figée.

    Reprenable : le tracking Seren est noté dans la fiche DÈS sa création.
    MyPuls ne sait pas le supprimer ; un second essai (cookie recollé) le
    réutilise au lieu d'en créer un autre.
    """
    import secrets
    import time as _t
    import gms
    e = espace(gid)
    v = e.get("variante")
    if not v:
        return {"ok": False, "erreur": "pas de 50/50 sur ce serveur"}
    l = lien_de(gid, uid)
    if not l.get("shortcode"):
        return {"ok": False, "erreur": "ce VA n'a pas de lien"}
    fv = dict(l.get("variante") or {})
    if fv.get("posee"):
        return {"ok": True, "deja": True, "tracking": fv.get("tracking", ""), "erreur": ""}
    equipe = str(e["equipe"])
    lid = str(l.get("link_id") or "") or _id_du_lien(equipe, l["shortcode"])
    if not lid:
        return {"ok": False, "erreur": "lien introuvable chez GetMySocial"}
    nom = f'Twitter VA {l.get("numero") or "?"} @{l.get("pseudo") or uid}'[:60]

    def noter(**kw) -> None:
        d = _etat()
        f = (d.setdefault("liens", {})).setdefault(f"{gid}:{uid}", {})
        f["variante"] = dict(f.get("variante") or {}, **kw)
        _ecrire(d)

    if not fv.get("tracking"):
        # le meme nom que le tracking Emy : le podium (registre, nom MyPuls)
        # y retrouve le meme VA
        t = _creer_ou_reprendre(nom, int(v["creator_id"]))
        if not t.get("ok"):
            err = f'MyPuls ({v["modele"]}) : {t.get("erreur", "")}'
            # un refus net n'a rien créé : on pourra réessayer. Le reste
            # (créé mais introuvable, réponse illisible, coupure) a PEUT-ÊTRE
            # créé un tracking qu'on ne connaît pas : un second essai en
            # ferait un deuxième, à vie. À vérifier à la main dans MyPuls.
            noter(modele=v["modele"], posee=False, erreur=err,
                  a_verifier=not t.get("refuse"))
            return {"ok": False, "erreur": err, "mypuls": True}
        fv = {"modele": v["modele"], "creator_id": int(v["creator_id"]),
              "tracking": t["url"], "code": t["code"]}
        noter(posee=False, erreur="", **fv)

    def rate(err: str, cookie: bool = False) -> Dict[str, Any]:
        # un cookie refusé ne dit rien du lien : il ne compte pas comme essai.
        # Le reste (lien disparu, refus GetMySocial) se répéterait à chaque
        # reprise, une copie temporaire à chaque fois : au bout de
        # ESSAIS_VARIANTE, la main
        essais = int((lien_de(gid, uid).get("variante") or {}).get("essais") or 0) \
            + (0 if cookie else 1)
        noter(posee=False, erreur=err, essais=essais, a_verifier=essais >= ESSAIS_VARIANTE)
        return {"ok": False, "cookie": cookie, "tracking": fv["tracking"], "erreur": err}

    sc = "abtmp" + secrets.token_hex(5)
    r = gms.duplicate_link(e.get("source_variante") or e["gabarit"], sc,
                           f'variante {v["modele"]} - {nom}'[:60], fv["tracking"], equipe)
    if not r.get("ok"):
        return rate(f'GetMySocial : copie temporaire refusée ({str(r.get("error"))[:100]})')
    tmp = r.get("link") if isinstance(r.get("link"), dict) else {}
    tmp_id = str(tmp.get("id") or "")
    try:
        if not tmp_id:
            return rate("GetMySocial : copie temporaire sans identifiant")
        # duplicate_link avale un échec de sa mise à jour d'adresse : la copie
        # garderait celle du gabarit, et la « variante » repartirait chez Emy
        if str(tmp.get("url") or "").strip().rstrip("/").lower() != \
                str(fv["tracking"]).strip().rstrip("/").lower():
            return rate(f'GetMySocial : la copie temporaire pointe sur '
                        f'{tmp.get("url") or "?"}, pas sur le tracking {v["modele"]}')
        ab = gms.poser_ab_testing(lid, tmp_id, equipe, int(v["poids"]), v["modele"])
    finally:
        if tmp_id:
            rd = gms.delete_link(tmp_id)
            if not rd.get("ok"):
                # resté dans EMY TWITTER : à effacer à la main, et c'est dit
                print(f"[lien] copie temporaire {sc} ({tmp_id}) non supprimée : "
                      f"{str(rd.get('error'))[:100]}", flush=True)
    if not ab.get("ok"):
        return rate("GetMySocial : " + str(ab.get("error") or "A/B refusé"),
                    cookie=bool(ab.get("cookie")))
    noter(posee=True, erreur="", quand=int(_t.time()))
    return {"ok": True, "tracking": fv["tracking"], "erreur": ""}


#: Au-delà, une variante qui échoue pour autre chose que le cookie attend la main.
ESSAIS_VARIANTE = 3
#: Entre deux VA : MyPuls crée un tracking en trois pages, on ne l'enchaîne pas.
PAUSE_VARIANTE_S = 2.0
_REPRISE = __import__("threading").Lock()


def _empreinte(cookie: str) -> str:
    return hashlib.sha1(str(cookie or "").encode("utf-8")).hexdigest()[:12]


def en_attente(gid: str = TWITTER_ID) -> list:
    """Les fiches dont le 50/50 reste à poser : celles créées avec et restées
    en plan, ET les liens d'avant le 50/50 (propriétaire, 14/10/2026, à « tu
    veux passer les anciens en 50/50 ? » : « yes avec un tracking link »).
    Pas un lien coupé (le VA ne bosse plus : deux trackings pour rien), ni
    une variante à vérifier à la main."""
    gid = str(gid)
    out = []
    for cle, l in sorted((_etat().get("liens") or {}).items()):
        if not cle.startswith(f"{gid}:") or not l.get("shortcode") or l.get("actif") is False:
            continue
        fv = l.get("variante")
        if isinstance(fv, dict) and (fv.get("posee") or fv.get("a_verifier")):
            continue
        out.append(cle)
    return out


def reprendre_variantes(gid: str = TWITTER_ID) -> Dict[str, Any]:
    """Pose les 50/50 qui manquent, anciens liens compris. Un VA sans son
    propre tracking Emy (lien d'avant MyPuls) le reçoit d'abord (rebrancher).

    Ne fait rien sans cookie utilisable : absent, échu, ou déjà refusé (son
    empreinte est notée — un nouveau cookie collé relance tout). S'arrête au
    premier refus de cookie, ou quand MyPuls n'a pas de session : le suivant
    échouerait pareil. Un seul passage à la fois (boucle du podium et cookie
    collé peuvent se croiser)."""
    import time as _t
    import gms
    gid = str(gid)
    bilan: Dict[str, Any] = {"poses": [], "rates": [], "a_verifier": []}
    if not espace(gid).get("variante"):
        return bilan
    ck = gms.get_session_cookie()
    exp = gms.cookie_expiration(ck) if ck else None
    if not ck or (exp and exp < _t.time()) or _etat().get("cookie_refuse") == _empreinte(ck):
        bilan["cookie"] = True
        return bilan
    if not _REPRISE.acquire(blocking=False):
        bilan["occupe"] = True
        return bilan
    try:
        for i, cle in enumerate(en_attente(gid)):
            if i:
                _t.sleep(PAUSE_VARIANTE_S)
            uid = cle.split(":", 1)[1]
            l = lien_de(gid, uid)
            qui = l.get("pseudo") or cle
            if not l.get("tracking"):
                rb = rebrancher(gid, uid)
                if not rb.get("ok"):
                    if rb.get("tracking"):
                        # le tracking Emy existe, la destination n'a pas suivi :
                        # le refaire en créerait un second, à vie
                        d = _etat()
                        f = (d.setdefault("liens", {})).setdefault(cle, {})
                        f["variante"] = dict(f.get("variante") or {}, posee=False, a_verifier=True,
                                             erreur=f'tracking Emy {rb["tracking"]} créé, '
                                                    f'lien non rebranché : {rb.get("erreur")}')
                        _ecrire(d)
                        bilan["a_verifier"].append(qui)
                    else:
                        bilan["rates"].append(f'{qui} : {rb.get("erreur")}')
                    if "session MyPuls" in str(rb.get("erreur")):
                        break
                    continue
            r = poser_variante(gid, uid)
            if r.get("ok"):
                bilan["poses"].append(qui)
                continue
            fv = lien_de(gid, uid).get("variante") or {}
            (bilan["a_verifier"] if fv.get("a_verifier") else bilan["rates"]).append(
                f'{qui} : {r.get("erreur")}')
            if r.get("cookie"):
                d = _etat()
                d["cookie_refuse"] = _empreinte(ck)
                _ecrire(d)
                bilan["cookie"] = True
                break
            if "session MyPuls" in str(r.get("erreur")):
                break
    finally:
        _REPRISE.release()
    return bilan


_VARIANTES_LUES: Dict[str, Any] = {}


def trackings_variantes() -> Dict[str, list]:
    """{identifiant du lien (sans « lnk_ ») : [tracking de sa variante]}.

    Le podium de Twitter reconnaît un VA à ses trackings, lus dans l'adresse
    du lien et de ses boutons. Celui de la variante n'y est nulle part (la
    liste des liens ne donne que l'identifiant de la variante) : sans ceci,
    la moitié Seren des clics de chaque VA n'irait à personne. Relu quand le
    fichier change seulement — le podium le demande pour chaque lien."""
    try:
        mt = ETAT_FICHIER.stat().st_mtime
    except OSError:
        return {}
    cle = f"{ETAT_FICHIER}:{mt}"
    if _VARIANTES_LUES.get("cle") != cle:
        out: Dict[str, list] = {}
        for l in (_etat().get("liens") or {}).values():
            fv = l.get("variante") if isinstance(l, dict) else None
            if isinstance(fv, dict) and fv.get("posee") and fv.get("tracking") and l.get("link_id"):
                out.setdefault(_sans_prefixe(l["link_id"]), []).append(str(fv["tracking"]))
        _VARIANTES_LUES.clear()
        _VARIANTES_LUES.update(cle=cle, out=out)
    return _VARIANTES_LUES["out"]


def rebrancher(gid: str, uid: str) -> Dict[str, Any]:
    """Donne son propre tracking link à un VA qui n'en avait pas.

    Sert aux liens créés avant que MyPuls soit ouvert : ils pointaient sur
    l'adresse générale de la modèle, donc leurs abonnés n'étaient rattachés à
    personne. L'ADRESSE PUBLIQUE NE CHANGE PAS — seule la destination bouge —
    donc ce que le VA a déjà posté sur Twitter continue de marcher.
    """
    import gms
    l = lien_de(gid, uid)
    if not l.get("shortcode"):
        return {"ok": False, "erreur": "ce VA n'a pas de lien"}
    if l.get("tracking"):
        return {"ok": False, "erreur": "ce VA a déjà son tracking link : "
                                       + str(l["tracking"])}
    if str(gid) == THREADS_ID:
        return {"ok": False, "erreur": "Threads n'a pas de tracking link : son lien "
                                       "est une copie de emythreads"}
    if not mypuls_actif():
        return {"ok": False, "erreur": "la création MyPuls est fermée"}
    equipe = str(espace(gid)["equipe"])
    lid = str(l.get("link_id") or "") or _id_du_lien(equipe, l["shortcode"])
    if not lid:
        return {"ok": False, "erreur": "lien introuvable chez GetMySocial"}

    nom = f'Twitter VA {l.get("numero") or "?"} @{l.get("pseudo") or uid}'[:60]
    t = creer_tracking(nom)
    if not t.get("ok"):
        return {"ok": False, "erreur": "MyPuls : " + t.get("erreur", "")}
    r = gms._call_tool("update_link", {"link_id": lid, "url": t["url"],
                                       "display_name": nom, "typeLink": "directlink"})
    if not r.get("ok"):
        # le tracking link existe et ne peut pas etre defait : on le nomme
        return {"ok": False, "tracking": t["url"],
                "erreur": f'GetMySocial : {str(r.get("error"))[:100]} — le tracking '
                          f'link {t["code"]} est cree, a rebrancher a la main.'}
    d = _etat()
    fiche = (d.setdefault("liens", {})).setdefault(f"{gid}:{uid}", {})
    fiche["tracking"], fiche["code"], fiche["link_id"] = t["url"], t["code"], lid
    _ecrire(d)
    return {"ok": True, "public_url": l.get("public_url", ""), "tracking": t["url"],
            "code": t["code"], "erreur": ""}


def changer_adresse(gid: str, uid: str) -> Dict[str, Any]:
    """Donne au lien d'un VA une adresse sans prénom (« angelyy »). Rend
    {ok, public_url, ancienne, erreur}.

    Propriétaire, 14/10/2026 : « change le lien pour ceux qui sont déjà et
    remets le bon ». Le MÊME lien GetMySocial est renommé : son A/B, ses
    trackings et ses clics restent. L'ancienne adresse cesse de marcher —
    c'est voulu, et elle est gardée dans la fiche (« anciennes_adresses »)
    pour qu'on sache d'où venait un clic perdu."""
    import gms
    e = espace(gid)
    l = lien_de(gid, uid)
    if not l.get("shortcode"):
        return {"ok": False, "erreur": "ce VA n'a pas de lien"}
    if not e.get("sans_prenom"):
        return {"ok": False, "erreur": "adresses sans prénom désactivées (sans_prenom)"}
    nom = f'{e["plateforme"]} VA {l.get("numero") or "?"} @{l.get("pseudo") or uid}'[:60]
    ancienne = str(l["shortcode"])
    if ancienne in {mots_sans_prenom(nom, i) for i in range(40)}:
        return {"ok": True, "deja": True, "public_url": l.get("public_url", ""),
                "ancienne": "", "erreur": ""}
    equipe = str(e["equipe"])
    lid = str(l.get("link_id") or "") or _id_du_lien(equipe, ancienne)
    if not lid:
        return {"ok": False, "erreur": "lien introuvable chez GetMySocial"}
    for essai in range(ESSAIS_ADRESSE):
        sc = mots_sans_prenom(nom, essai)
        r = gms._call_tool("update_link", {"link_id": lid, "shortcode": sc, "team_id": equipe})
        if r.get("ok"):
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            # relu : un « ok » qui aurait gardé l'ancienne adresse ne doit pas
            # faire afficher au VA un lien qui n'existe pas
            if d and str(d.get("shortcode") or "") != sc:
                return {"ok": False, "erreur": f"GetMySocial a gardé « {d.get('shortcode')} »"}
            etat = _etat()
            f = (etat.setdefault("liens", {})).setdefault(f"{gid}:{uid}", {})
            f["anciennes_adresses"] = list(f.get("anciennes_adresses") or []) + [ancienne]
            f["shortcode"] = sc
            f["public_url"] = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
            f["link_id"] = lid
            _ecrire(etat)
            return {"ok": True, "public_url": f["public_url"], "ancienne": ancienne, "erreur": ""}
        # adresse prise (elles sont communes à tout GetMySocial) : la suivante
        if "shortcode" not in str(r.get("error") or "").lower():
            return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    return {"ok": False, "erreur": f"{ESSAIS_ADRESSE} adresses essayées, toutes prises"}


def basculer(gid: str, uid: str, actif: bool) -> Dict[str, Any]:
    """Coupe ou remet en service le lien d'un VA. Rend {ok, url, actif, erreur}.

    Couper plutôt que supprimer : un VA qui ne bosse pas peut s'y remettre, et
    son adresse est déjà postée sur Twitter. Un lien coupé garde son historique
    de clics et se rallume d'un clic — un lien supprimé ne revient jamais.
    """
    import gms
    l = lien_de(gid, uid)
    if not l.get("shortcode"):
        return {"ok": False, "erreur": "ce VA n'a pas de lien"}
    equipe = str(espace(gid)["equipe"])
    lid = str(l.get("link_id") or "") or _id_du_lien(equipe, l["shortcode"])
    if not lid:
        return {"ok": False, "erreur": "lien introuvable chez GetMySocial"}
    try:
        r = gms.enable_link(lid) if actif else gms.disable_link(lid)
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:100]}"}
    if not r.get("ok"):
        return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    d = _etat()
    fiche = (d.setdefault("liens", {})).setdefault(f"{gid}:{uid}", {})
    fiche["actif"] = bool(actif)
    fiche["link_id"] = lid
    _ecrire(d)
    return {"ok": True, "url": l.get("public_url", ""), "actif": bool(actif), "erreur": ""}


def est_actif(gid: str, uid: str) -> bool:
    """Un lien est en service tant qu'on ne l'a pas coupé."""
    return bool((lien_de(gid, uid) or {}).get("actif", True))


def supprimer(gid: str, uid: str) -> Dict[str, Any]:
    """Efface le lien GetMySocial d'un VA. Rend {ok, url, erreur}.

    On efface d'abord chez GetMySocial, on oublie ensuite. Dans l'autre sens,
    un echec aurait laisse un lien vivant que plus personne ne rattache a
    quelqu'un — invisible, donc jamais nettoye.
    """
    import gms
    l = lien_de(gid, uid)
    if not l.get("shortcode"):
        return {"ok": False, "erreur": "ce VA n'a pas de lien"}
    equipe = str(espace(gid)["equipe"])
    lid = str(l.get("link_id") or "") or _id_du_lien(equipe, l["shortcode"])
    if not lid:
        return {"ok": False, "erreur": "lien introuvable chez GetMySocial — "
                                       "déjà supprimé ? La fiche est laissée en place."}
    try:
        r = gms.delete_link(lid)
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:100]}"}
    if not r.get("ok"):
        return {"ok": False, "erreur": str(r.get("error") or "refus GetMySocial")[:140]}
    d = _etat()
    (d.get("liens") or {}).pop(f"{gid}:{uid}", None)
    _ecrire(d)
    return {"ok": True, "url": l.get("public_url", ""), "erreur": ""}


# ─── synchronisation : la catégorie Discord fait foi ─────────────────────
def nom_dans_categorie(nom_categorie: str) -> str:
    """« 🔵┤ Manager YAZID ├🔵 » → « YAZID ». « » si ce n'est pas une catégorie de manager."""
    m = re.search(r"Manager\s+(.+?)\s*├", str(nom_categorie or ""))
    return m.group(1).strip() if m else ""


def synchroniser(gid: str) -> Dict[str, Any]:
    """Aligne GetMySocial sur Discord. Rend un compte rendu de ce qui a bougé.

    DEUX CHOSES, et la seconde est la raison d'être de la première :

    1. Chaque manager a son groupe, même sans un seul VA. Un groupe vide dit
       « ce manager existe et n'a personne » — ce qui se voit, alors qu'un
       groupe absent ne se voit pas.
    2. Un VA dont le salon a été déplacé dans la catégorie d'un AUTRE manager
       voit son lien suivre. La catégorie Discord fait foi : c'est là qu'on
       déplace les gens à la main, donc c'est elle qui a raison.
    """
    import tickets_discord as tk
    gid = str(gid)
    equipe = str(espace(gid)["equipe"])
    bilan = {"groupes_crees": [], "deplaces": [], "sans_categorie": [], "rates": []}
    if gid not in SERVEURS:
        return bilan      # les managers de ce serveur n'ont rien a faire ici

    connus = groupes(equipe)
    if connus is None:
        bilan["rates"].append("groupes GetMySocial illisibles : rien touché")
        return bilan

    # 1. un groupe par manager, même à zéro VA
    for m in (tk.managers(gid) or []):
        nom = tk._nom_court(m)
        if not nom or nom.lower() in connus:
            continue
        if groupe_manager(equipe, nom):
            bilan["groupes_crees"].append(nom)
            connus = groupes(equipe) or connus

    # 2. les salons déplacés à la main
    code, salons = tk._api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        bilan["rates"].append(f"salons Discord illisibles (HTTP {code})")
        return bilan
    # Le nom réduit comme le lit le suivi des managers (tickets_discord) :
    # « Manager Spectrum🥷 », retapée à la main, y est la catégorie de
    # SPECTRUM — lue brute ici, elle rangeait les liens dans un groupe
    # « Spectrum🥷 », à côté du « SPECTRUM » créé à l'étape 1.
    categorie = {str(c["id"]): tk._cle_categorie(c.get("name"))
                 for c in salons if c.get("type") == 4}
    parent = {str(c["id"]): str(c.get("parent_id") or "")
              for c in salons if c.get("type") == 0}

    etat = _etat()
    liens = etat.setdefault("liens", {})
    fiches = (tk._etat().get("tickets") or {})
    change = False
    for cle, l in liens.items():
        if not cle.startswith(f"{gid}:") or not l.get("shortcode"):
            continue
        salon = str((fiches.get(cle) or {}).get("salon") or "")
        voulu = categorie.get(parent.get(salon, ""), "")
        if not voulu:
            bilan["sans_categorie"].append(l.get("pseudo") or cle)
            continue
        if voulu.lower() == str(l.get("groupe") or "").lower():
            continue
        lid = l.get("link_id") or _id_du_lien(equipe, l["shortcode"])
        if not lid:
            bilan["rates"].append(f'{l.get("pseudo")} : lien introuvable chez GetMySocial')
            continue
        if ranger(equipe, lid, voulu):
            l["groupe"], l["manager"], l["link_id"] = voulu, voulu, lid
            bilan["deplaces"].append(f'{l.get("pseudo")} → {voulu}')
            change = True
        else:
            bilan["rates"].append(f'{l.get("pseudo")} : rangement refusé')
    if change:
        _ecrire(etat)
    # 3. Threads : l'espace n'a que les groupes de ses managers
    if espace(gid).get("groupes_managers_seuls"):
        _seulement_les_managers(gid, equipe, categorie, parent, liens, fiches, bilan)
    return bilan


def _seulement_les_managers(gid: str, equipe: str, categorie: Dict[str, str],
                            parent: Dict[str, str], liens: Dict[str, Any],
                            fiches: Dict[str, Any], bilan: Dict[str, Any]) -> None:
    """Range l'espace : un groupe par manager, et rien d'autre.

    Propriétaire, 13/10/2026, devant EMY THREADS (ABDOUL, MOMOBY, ROUCHAM,
    MANAGER) : « de base y avait 2 groupes et c'est tout, pourquoi y a
    Roucham, pourquoi y a un truc MANAGER », puis « je veux que ça soit
    automatique ». Un groupe qui ne répond plus à aucun manager (Roucham passé
    Helper, « MANAGER » né d'un surnom mal lu) est vidé de ce qu'aucune fiche
    ne tient, puis supprimé — supprimer un groupe ne supprime aucun lien, ils
    passent « sans groupe ». Dans le groupe d'un manager, un lien COUPÉ
    qu'aucune fiche ne tient (refait à neuf) en sort. Un lien actif inconnu
    reste où il est : posé à la main, peut-être. La liste des managers
    indéterminable : rien n'est touché."""
    import gms
    import tickets_discord as tk
    _fixe, _rid, liste = tk._managers_surs(gid)
    if not liste:
        bilan["rates"].append("managers indéterminables : groupes laissés tels quels")
        return
    voulus = {tk._nom_court(m).lower() for m in liste}
    # un manager parti dont la catégorie tient encore des VA garde son groupe
    # tant qu'ils n'en sont pas sortis
    for cle, l in liens.items():
        if cle.startswith(f"{gid}:") and l.get("shortcode"):
            salon = str((fiches.get(cle) or {}).get("salon") or "")
            v = categorie.get(parent.get(salon, ""), "")
            if v:
                voulus.add(v.lower())
    tenus = {str(l.get("link_id")) for cle, l in liens.items()
             if cle.startswith(f"{gid}:") and l.get("link_id")}
    connus = groupes(equipe)
    if connus is None:
        bilan["rates"].append("groupes GetMySocial illisibles : rangement remis")
        return
    for nom, grp in sorted(connus.items()):
        garde = nom in voulus
        r = gms._call_tool("list_links", {"team_id": equipe, "group_id": grp, "limit": 100})
        d = r.get("data") if r.get("ok") else None
        items = d.get("data") if isinstance(d, dict) else d
        if not isinstance(items, list):
            bilan["rates"].append(f"groupe {nom.upper()} illisible : laissé")
            continue
        sortir = [str(x.get("id")) for x in items if isinstance(x, dict) and x.get("id")
                  and str(x.get("id")) not in tenus
                  and (not garde or str(x.get("status") or "active") != "active")]
        if sortir:
            rr = gms._call_tool("remove_links_from_group",
                                {"group_id": grp, "link_ids": sortir, "team_id": equipe})
            if not rr.get("ok"):
                bilan["rates"].append(f"groupe {nom.upper()} : liens non sortis "
                                      f"({str(rr.get('error'))[:80]})")
                continue
            bilan.setdefault("sortis", []).extend(f"{s_} ({nom.upper()})" for s_ in sortir)
        if garde:
            continue
        restent = len(items) - len(sortir)
        if restent or (isinstance(d, dict) and d.get("has_more")):
            # un lien qu'une fiche tient encore dedans : l'étape 2 n'a pas pu
            # le ranger ; le groupe attend, et c'est dit
            bilan["rates"].append(f"groupe {nom.upper()} sans manager, gardé : "
                                  f"{restent} lien(s) de VA encore dedans")
            continue
        rd = gms._call_tool("delete_group", {"group_id": grp, "team_id": equipe})
        if rd.get("ok"):
            bilan.setdefault("groupes_supprimes", []).append(nom.upper())
        else:
            bilan["rates"].append(f"groupe {nom.upper()} non supprimé ({str(rd.get('error'))[:80]})")


def _id_du_lien(equipe: str, shortcode: str) -> str:
    """Retrouve l'identifiant GetMySocial d'un lien par son shortcode."""
    try:
        import gms
        r = gms.list_links_team(equipe, force_refresh=True) or {}
        for l in (r.get("links") or r.get("data") or []):
            if str(l.get("shortcode") or "") == shortcode:
                return str(l.get("id") or "")
    except Exception as e:
        print(f"[lien] recherche de {shortcode} : {type(e).__name__}: {e}", flush=True)
    return ""


# ─── Seren en pause : tout chez Emy ──────────────────────────────────────
# Propriétaire, 21/10/2026 : « tout envoyé que sur Emy, plus de Seren pour le
# moment, pour Threads et Twitter, et même pour les prochaines créations »,
# puis « ok, tout sur Emy ». Tant que SEREN_EN_PAUSE est vrai :
# - un lien neuf ne reçoit pas de variante (espace() la rend à None) ;
# - un lien neuf de Threads perd le 50/50 hérité de emythreads (creer_pour) ;
# - couper_seren éteint, à chaque passage, les A/B encore allumés de l'espace
#   du serveur, liens de VA comme liens de base (emythreads).
# Éteindre un A/B EFFACE sa variante chez GetMySocial (constaté le 21/10 :
# « Variant … not found » en la rallumant). Rien d'autre ne part : le
# tracking Seren du VA reste chez MyPuls et dans sa fiche. Pour remettre le
# 50/50 : SEREN_EN_PAUSE = False, puis remettre_seren(gid) — reprendre_variantes
# refait chaque variante vers LE MÊME tracking Seren (aucun nouveau tracking).
# COUPES_FICHIER garde chaque A/B éteint et sa config d'avant.
# Propriétaire, 24/10/2026 : « c'est fini, faut envoyer aussi sur Seren, à
# nouveau » : la pause est levée. tickets_discord._couper_seren appelle alors
# remettre_seren (sous _REPRISE), et la boucle du podium (reprendre_variantes)
# refait les variantes.
SEREN_EN_PAUSE = False
COUPES_FICHIER = DATA_DIR / "liens_seren_coupes.json"
_COUPE = __import__("threading").Lock()

_espace_avec_seren = espace


def espace(gid: str = "") -> Dict[str, Any]:    # noqa: F811 — voir plus haut
    """espace() (plus haut), sans variante tant que Seren est en pause, et
    Agency VA INSTAGRAM. Enveloppe : le corps d'origine est touché par un patch
    local du VPS (99-threads-mypuls) pour Threads."""
    if str(gid) == AGENCY_IG_ID:
        c = config()
        sur = c.get("agency_ig") if isinstance(c.get("agency_ig"), dict) else {}
        e = dict(ESPACE_AGENCY_IG, **{k: v for k, v in sur.items() if v not in (None, "")})
        # Propriétaire, 24/10/2026 : « Threads, Instagram, Twitter : faut
        # envoyer aussi sur Seren ». Le 50/50 comme Twitter, mais sa variante
        # copie un lien DIRECT d'EMY IG (source_variante) : une copie de la
        # landing garderait son bouton chez Emy, et la moitié Seren finirait
        # chez Emy. Sans source : Emy seule, comme avant.
        var = (dict(VARIANTE_TWITTER)
               if mypuls_actif() and not SEREN_EN_PAUSE and e.get("source_variante") else None)
        e.update(tracking=mypuls_actif(), variante=var,
                 base_shortcode=str(c.get("base_shortcode") or c.get("modele") or "emy"))
        return e
    e = _espace_avec_seren(gid)
    if SEREN_EN_PAUSE:
        e["variante"] = None
    return e


def _noter_coupe(lid: str, **kw) -> None:
    d = _lire(COUPES_FICHIER, {})
    d = d if isinstance(d, dict) else {}
    f = (d.setdefault("liens", {})).setdefault(_sans_prefixe(lid), {})
    f.update(kw)
    safe_json.write_text(COUPES_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _couper_lien(gid: str, equipe: str, lid: str, shortcode: str = "", nom: str = "",
                 cle: str = "") -> Dict[str, Any]:
    """Éteint l'A/B d'un lien, noté AVANT dans COUPES_FICHIER (config d'avant,
    tracking Seren de la fiche) puis marqué dans la fiche du VA (variante.coupee).
    La fiche garde « posee » : en_attente ne la reprend pas, et le podium
    reconnaît encore les clics Seren d'avant la coupure."""
    import time as _t
    import gms
    lid = _sans_prefixe(lid)
    av = gms.lire_ab_testing(lid, equipe)
    if not av.get("ok"):
        return av
    if not av["config"].get("enabled"):
        return {"ok": True, "deja": True}
    fiche = (_etat().get("liens") or {}).get(cle) or {} if cle else {}
    _noter_coupe(lid, serveur=str(gid), equipe=equipe, shortcode=shortcode, nom=nom,
                 fiche=cle if fiche else "",
                 tracking_seren=str((fiche.get("variante") or {}).get("tracking") or ""),
                 avant=av["config"], quand=int(_t.time()), fait=False)
    r = gms.allumer_ab_testing(lid, equipe, actif=False)
    if not r.get("ok"):
        _noter_coupe(lid, erreur=str(r.get("error") or "")[:200])
        return r
    _noter_coupe(lid, fait=True, erreur="")
    if fiche:
        d = _etat()
        f = (d.get("liens") or {}).get(cle)
        if isinstance(f, dict):
            f["variante"] = dict(f.get("variante") or {}, coupee=int(_t.time()))
            _ecrire(d)
    return {"ok": True}


def _noter_eteints(gid: str, equipe: str, eteints: set) -> None:
    """Une fiche « posee » dont l'A/B est DÉJÀ éteint (à la main dans
    GetMySocial, ou bloomyy, l'essai du 21/10/2026) est marquée « coupee » elle
    aussi : sans ça, remettre_seren l'oublierait."""
    import time as _t
    d = _etat()
    vus = []
    for cle, f in (d.get("liens") or {}).items():
        fv = f.get("variante") if isinstance(f, dict) else None
        if (cle.startswith(f"{gid}:") and isinstance(fv, dict) and fv.get("posee")
                and not fv.get("coupee") and _sans_prefixe(f.get("link_id")) in eteints):
            f["variante"] = dict(fv, coupee=int(_t.time()))
            vus.append((cle, f))
    if not vus:
        return
    _ecrire(d)
    for cle, f in vus:
        _noter_coupe(f.get("link_id"), serveur=str(gid), equipe=equipe,
                     shortcode=str(f.get("shortcode") or ""), nom="", fiche=cle,
                     tracking_seren=str(f["variante"].get("tracking") or ""),
                     deja_eteint=True, quand=int(_t.time()), fait=True)


def couper_seren(gid: str) -> Dict[str, Any]:
    """Éteint les A/B encore allumés de l'espace GetMySocial de ce serveur.
    {coupes, rates, cookie?}. Lus dans la liste des liens (« ab_testing »),
    donc rien n'est appelé quand tout est déjà éteint. S'arrête au premier
    refus de cookie : le suivant échouerait pareil."""
    import time as _t
    import gms
    gid = str(gid)
    bilan: Dict[str, Any] = {"coupes": [], "rates": []}
    if not SEREN_EN_PAUSE or gid not in SERVEURS:
        return bilan
    equipe = str(espace(gid)["equipe"])
    r = gms.list_links_team(equipe, force_refresh=True) or {}
    liens = [l for l in (r.get("links") or r.get("data") or [])
             if isinstance(l, dict) and l.get("id") and isinstance(l.get("ab_testing"), dict)]
    allumes = [l for l in liens if l["ab_testing"].get("enabled")]
    _noter_eteints(gid, equipe, {_sans_prefixe(l["id"]) for l in liens
                                 if not l["ab_testing"].get("enabled")})
    if not allumes:
        return bilan
    if not _COUPE.acquire(blocking=False):
        bilan["occupe"] = True
        return bilan
    try:
        fiches = {_sans_prefixe(f.get("link_id")): cle
                  for cle, f in (_etat().get("liens") or {}).items()
                  if isinstance(f, dict) and f.get("link_id") and cle.startswith(f"{gid}:")}
        for i, l in enumerate(allumes):
            if i:
                _t.sleep(0.5)
            lid = _sans_prefixe(l["id"])
            qui = str(l.get("shortcode") or lid)
            if "seren" in str(l.get("url") or "").lower():
                # emythreads, 21/10/2026 : sa destination était Seren et sa
                # variante Emy ; l'A/B éteint, il est parti à 100 % chez Seren
                # (remis sur emy.brw/c66 à la main). Sa destination passe chez
                # Emy d'abord : on ne devine pas laquelle.
                bilan["rates"].append(f"{qui} : destination Seren ({l.get('url')}), A/B laissé")
                continue
            rc = _couper_lien(gid, equipe, lid, qui, str(l.get("display_name") or ""),
                              fiches.get(lid, ""))
            if rc.get("ok"):
                bilan["coupes"].append(qui)
                continue
            bilan["rates"].append(f'{qui} : {rc.get("error")}')
            if rc.get("cookie"):
                bilan["cookie"] = True
                break
    finally:
        _COUPE.release()
    return bilan


def remettre_seren(gid: str) -> Dict[str, Any]:
    """Le chemin du retour au 50/50, SEREN_EN_PAUSE remis à False : les fiches
    coupées repassent « à poser », et reprendre_variantes refait leur variante
    vers leur tracking Seren déjà créé. Les liens sans fiche (emythreads, les
    premiers liens de Threads) se refont à la main : leur config d'avant est
    dans COUPES_FICHIER."""
    if SEREN_EN_PAUSE:
        return {"ok": False, "erreur": "SEREN_EN_PAUSE est encore vrai"}
    gid = str(gid)
    # sous le verrou de reprendre_variantes : réécrire l'état pendant qu'elle
    # note un tracking Seren tout juste créé l'effacerait, et le passage
    # suivant en créerait un second chez MyPuls, à vie
    if not _REPRISE.acquire(blocking=False):
        return {"ok": False, "occupe": True, "erreur": "reprise des variantes en cours"}
    try:
        return _remettre_seren(gid)
    finally:
        _REPRISE.release()


def _remettre_seren(gid: str) -> Dict[str, Any]:
    d = _etat()
    n = 0
    for cle, f in (d.get("liens") or {}).items():
        fv = f.get("variante") if isinstance(f, dict) else None
        if cle.startswith(f"{gid}:") and isinstance(fv, dict) and fv.get("coupee"):
            f["variante"] = dict({k: v for k, v in fv.items() if k != "coupee"},
                                 posee=False, essais=0, a_verifier=False)
            n += 1
    if n:
        _ecrire(d)
    return {"ok": True, "a_reposer": n}


# Le tracking Seren d'un VA d'Agency doit s'appeler « Instagram VA n @pseudo » :
# _creer_ou_reprendre REPREND un tracking existant du même nom chez la même
# créatrice, et « Twitter VA n » (le nom du corps d'origine) donnerait au VA
# d'Agency le tracking du VA n de Twitter. Le patch du VPS 99-threads-mypuls
# nomme par la plateforme ; s'il venait à tomber, rien n'est créé pour Agency.
_poser_variante_sans_garde = poser_variante


def poser_variante(gid: str, uid: str) -> Dict[str, Any]:   # noqa: F811
    if str(gid) == AGENCY_IG_ID:
        import inspect
        try:
            source = inspect.getsource(_poser_variante_sans_garde)
        except (OSError, TypeError):
            source = ""
        if 'e["plateforme"]} VA' not in source:
            return {"ok": False, "erreur": "trackings Seren d'Agency nommés « Twitter VA » "
                                          "(patch 99-threads-mypuls absent) : rien créé"}
    return _poser_variante_sans_garde(gid, uid)
