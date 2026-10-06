# -*- coding: utf-8 -*-
"""Les pages de BASE des identites US dans GetMySocial : « TEMPLATE <identite> ».

POURQUOI (proprietaire, 06/10/2026)
    « Avoir une base et juste changer les PP et la photo c'est tout. » Il
    poste dans le salon admin « bases-identites » du serveur US le nom d'une
    identite et deux photos (1re = photo de profil, 2e = fond) ; le bot
    (cogs/bases_identite.py) cree ici, dans l'equipe GetMySocial « JESSY LE
    RETOUR », une page qui reprend TOUT le style d'une page modele
    (lilskysmk2, equipe NOUM FR) avec seulement ces deux photos changees.

    Ces pages sont ensuite copiees pour chaque VA (liens_identite_us.py), le
    suivi du VA pose sur le bouton OnlyFans. Elles doivent donc vivre dans
    l'equipe des VA : GetMySocial ne copie un lien que DANS son equipe
    (404 link_not_in_team, constate le 03/10, voir liens_fr.py).

COMMENT
    duplicate_link ne sait ni changer d'equipe ni changer les images. On
    RECREE donc la page : GET /v3/links/<modele> rend tous ses reglages, et un
    POST multipart /v3/links les renvoie avec les deux fichiers. Essaye en
    direct le 06/10/2026 : 201, rendu compare a l'oeil, identique au modele
    hormis les deux photos. Les champs fichiers s'appellent profilePicture et
    backgroundImage : profile_picture et background_image sont REFUSES
    (400 « Unexpected file field »). NON PROUVE : cet essai a cree la page
    dans NOUM FR ; aucune creation n'a encore ete vue dans JESSY LE RETOUR.

    Seule VALEUR changee par rapport au modele : l'adresse OnlyFans des
    boutons. Celle du modele (onlyfans.com/emy.brw) est une creatrice du cote
    FR ; la page de base est publique, son adresse est postee pour etre
    copiee : collee dans une bio, elle aurait envoye les ventes a Emy. Elle
    vise donc la creatrice des identites US (Jessye, sans c<N>) ;
    liens_identite_us y pose ensuite le suivi de chaque VA.

QUELLE BASE LES VA RECOIVENT
    liens_identite_us ne lit PAS le registre d'ici : il prend dans la liste
    de l'equipe les pages nommees « TEMPLATE <identite> » (meme faites a la
    main), la page active, puis LA PLUS ANCIENNE. Remplacer une base, c'est
    donc couper TOUTES les autres pages actives a ce nom -- pas seulement
    celle du registre : sinon le bot repondait ✅ et chaque VA recevait encore
    la copie de l'ancienne. Une page creee mais rejetee est RENOMMEE
    (« REJET TEMPLATE ... ») en plus d'etre coupee : le module VA prend aussi
    une page inactive quand c'est la seule.

CE QUI N'EST JAMAIS FAIT
    Supprimer une page (delete_links est definitif, GetMySocial n'a pas de
    corbeille). Une base remplacee est DESACTIVEE -- reversible dans
    GetMySocial -- et seulement APRES que la nouvelle a ete creee et
    verifiee ; son id reste dans « anciens ».

LE REGISTRE (data/bases_identite_us.json) : l'historique du bot
    {identite: {link_id, shortcode, url, display_name, nom_affiche, equipe,
                modele, par, quand, anciens: [link_id...], adresses: [...]}}
    « adresses » : toutes les adresses deja obtenues ou refusees (409) pour
    cette identite -- on repart apres la plus haute, sans payer un POST par
    adresse deja prise. Une entree SANS link_id n'a pas de base active (elle
    ne garde que des essais rates, « rates »).
"""
from __future__ import annotations

import copy
import difflib
import io
import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

import gms
import safe_json

_RACINE = Path(__file__).resolve().parent
CONFIG = _RACINE / "data" / "bases_identite_us_config.json"
REGISTRE = _RACINE / "data" / "bases_identite_us.json"

#: JESSY LE RETOUR. PAS reglable dans CONFIG : liens_identite_us, qui copie
#: ces pages, ne regarde que cette equipe-la. Une equipe reglee ici a part,
#: c'etait ✅ cote bot et « Pas de page de base » cote VA. Meme valeur que
#: infloww_liens.EQUIPE_GMS (verifie par tests_bases_identite.py).
EQUIPE = "tm_6a0e4739bfa0c238f20a8bf5"
NOM_EQUIPE = "JESSY LE RETOUR"
#: La creatrice que vendent toutes les identites US : infloww_liens.CREATRICE.
CREATRICE = "jessyewdiference"

#: Tout se regle dans CONFIG (facultatif) ; ce qui manque prend ces valeurs.
DEFAUTS = {
    # lilskysmk2, equipe NOUM FR : la page dont on reprend le style
    "base_link_id": "lnk_6abb26204ae4ffa662156701",
    # le salon admin du serveur US (cogs/bases_identite.py)
    "salon": "bases-identites",
}

PREFIXE_NOM = "TEMPLATE "
PREFIXE_REJET = "REJET "

#: Les champs du modele qu'on ne renvoie PAS. Les uns sont poses par le
#: serveur (id, dates, statut, proprietaire), les autres sont propres a la
#: page modele (adresse, equipe, groupe, nom) ou remplaces par les fichiers
#: envoyes. Liste exacte de l'essai reussi du 06/10/2026 : en changer un,
#: c'est revenir a une requete jamais essayee.
EXCLUS = frozenset({
    "id", "object", "created", "updated", "user_id", "status", "url",
    "profile_picture", "profile_picture_slides", "background_image",
    "team_id", "group_id", "selected_domain", "shortcode", "display_name",
    "notes",
})

#: Etiquette des appels (gms.api_tag) : rang « normal » dans gms.PRIORITES.
#: Surtout pas une etiquette « fond », qui s'efface la premiere quand le
#: budget du jour baisse -- ici c'est le proprietaire qui attend.
ETIQUETTE = "bases-us"

TTL_MODELE = 600            # le modele bouge rarement ; dix minutes de cache
#: POST au plus par creation, pour des adresses prises AILLEURS (une autre
#: equipe de la plateforme). Celles deja connues (registre, liste de
#: l'equipe) sont sautees sans appel.
ESSAIS_SHORTCODE = 6
TAILLE_MAX = 10 * 1024 * 1024   # limite de GetMySocial, par fichier
PP_MAX, PP_MIN = 1024, 400      # photo de profil carree, conseil de l'API
FOND = (1080, 1920)             # fond 9:16, conseil de l'API
COTE_MINI = 64                  # en dessous, ce n'est pas une photo
#: Ecart toleré entre l'heure du serveur et l'horodatage d'une photo envoyee.
MARGE_PHOTO = 600

_VERROU = threading.RLock()          # une creation a la fois (registre compris)
_VERROU_CACHE = threading.Lock()
_CACHE_MODELE: Dict[str, Any] = {"id": None, "t": 0.0, "modele": None}
_DITS: Set[str] = set()


def _dire_une_fois(cle_msg: str, texte: str) -> None:
    if cle_msg not in _DITS:
        _DITS.add(cle_msg)
        print(texte, flush=True)


# ───────────────────────────────────────────────────── config, registre ──

def _avec_tm(equipe) -> str:
    e = str(equipe or "").strip()
    return e if not e or e.startswith("tm_") else "tm_" + e


def _sans_tm(equipe) -> str:
    e = str(equipe or "").strip()
    return e[3:] if e.startswith("tm_") else e


def _liu():
    """liens_identite_us, le module qui copie les bases, ou None s'il n'est
    pas la (il vit encore dans une autre branche)."""
    try:
        import liens_identite_us
        return liens_identite_us
    except ImportError:
        return None
    except Exception as e:                                   # noqa: BLE001
        _dire_une_fois("liu", f"[bases_us] liens_identite_us illisible ({type(e).__name__}: {e}) : "
                              "règles locales")
        return None


def equipe() -> str:
    """L'equipe des bases : CELLE que liens_identite_us lit, s'il est la."""
    m = _liu()
    e = _avec_tm(getattr(m, "EQUIPE", "") if m else "")
    return e or EQUIPE


def url_onlyfans() -> str:
    return f"https://onlyfans.com/{CREATRICE}"


def config() -> Dict[str, str]:
    d = safe_json.load(CONFIG, default={}) or {}
    out = dict(DEFAUTS)
    if isinstance(d, dict):
        for k in DEFAUTS:
            v = str(d.get(k) or "").strip()
            if v:
                out[k] = v
        voulue = _avec_tm(d.get("equipe"))
        if voulue and voulue != equipe():
            # dit, jamais suivi : le module VA ne verrait pas ces bases
            _dire_une_fois("equipe:" + voulue,
                           f"[bases_us] « equipe » {voulue} de {CONFIG.name} ignorée : les bases "
                           f"vont dans {equipe()}, la seule que liens_identite_us lit")
    lid = out["base_link_id"]
    out["base_link_id"] = lid if lid.startswith("lnk_") else "lnk_" + lid
    out["equipe"] = equipe()
    return out


def cle(identite) -> str:
    """La cle d'une identite : minuscules, sans « @ » ni blancs. Un iPhone
    met une majuscule au premier mot : « Ibenhaastrup » doit trouver
    « ibenhaastrup ». Sans blancs, comme liens_identite_us._ident :
    « TEMPLATE Iben Haastrup » y designe « ibenhaastrup »."""
    return re.sub(r"\s+", "", str(identite or "").strip().lstrip("@")).lower()


def _registre_brut() -> Dict[str, Any]:
    d = safe_json.load(REGISTRE, default={}) or {}
    return d if isinstance(d, dict) else {}


def bases_registre() -> Dict[str, Dict[str, Any]]:
    """{identite: entree} des bases ACTIVES selon le registre du bot. La
    verite des VA est la liste de l'equipe : voir etat_liste()."""
    return {k: dict(v) for k, v in _registre_brut().items()
            if isinstance(v, dict) and v.get("link_id")}


def base_de(identite) -> Optional[Dict[str, Any]]:
    e = _registre_brut().get(cle(identite))
    return dict(e) if isinstance(e, dict) and e.get("link_id") else None


def _ecrire_registre(d: Dict[str, Any]) -> bool:
    REGISTRE.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write(REGISTRE, d, indent=1))


def _maj_registre(k: str, nom: str, modif) -> bool:
    """Relit, modifie l'entree k (creee si besoin), ecrit."""
    reg = _registre_brut()
    e = reg.get(k) if isinstance(reg.get(k), dict) else {"identite": nom}
    modif(e)
    reg[k] = e
    return _ecrire_registre(reg)


def _adresses(entree: Optional[Dict[str, Any]]) -> Set[str]:
    """Les adresses deja tenues ou refusees pour cette identite."""
    e = entree if isinstance(entree, dict) else {}
    out = {str(x).lower() for x in e.get("adresses") or [] if x}
    if e.get("shortcode"):
        out.add(str(e["shortcode"]).lower())
    for r in e.get("rates") or []:
        if isinstance(r, dict) and r.get("shortcode"):
            out.add(str(r["shortcode"]).lower())
    return out


# ───────────────────────────────────────── la liste de l'equipe (les VA) ──

_MOT_BASE = re.compile(r"^\s*([A-Za-z]+)\s*[:\-–—_]*\s*(.*?)\s*$", re.S)


def identite_de_base(nom) -> Optional[str]:
    """« TEMPLATE ibenhaastrup » -> « ibenhaastrup ». LA regle de
    liens_identite_us quand il est la (deux regles finiraient par voir des
    bases differentes) ; sinon la meme, sans ses tolerances aux fautes."""
    m = _liu()
    f = getattr(m, "identite_de_base", None) if m else None
    if callable(f):
        try:
            return f(nom)
        except Exception as e:                               # noqa: BLE001
            _dire_une_fois("idb", f"[bases_us] identite_de_base : {type(e).__name__}: {e}")
    mm = _MOT_BASE.match(str(nom or ""))
    if not mm or mm.group(1).lower() != "template":
        return None
    ident = re.sub(r"\s+", "", mm.group(2).strip(" \t«»\"'()[]{}<>")).lower()
    return ident or None


def _actif(l: Optional[Dict[str, Any]]) -> bool:
    return bool(l) and str(l.get("status") or "").strip().lower() == "active"


def liens_equipe(force: bool = False) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """(liens de l'equipe, erreur). La liste que liens_identite_us lit (cache
    de 15 min de gms). Jamais d'exception."""
    try:
        with gms.api_tag(ETIQUETTE):
            r = gms.list_links_team(equipe(), force_refresh=force)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not isinstance(r, dict) or not r.get("ok"):
        return None, str((r or {}).get("error") if isinstance(r, dict) else "") or "GetMySocial ne répond pas"
    brut = r.get("links") or []
    liens = [l for l in brut if isinstance(l, dict) and l.get("id")]
    if len(liens) != len(brut):
        print(f"[bases_us] {len(brut) - len(liens)} lien(s) sans identifiant dans {NOM_EQUIPE} : "
              "laissés de côté", flush=True)
    return liens, ""


def pages_de_base(liens: Iterable[Dict[str, Any]], identite) -> List[Dict[str, Any]]:
    """Les liens de l'equipe nommes « TEMPLATE <identite> », tous statuts."""
    k = cle(identite)
    return [l for l in liens or [] if cle(identite_de_base(l.get("display_name")) or "") == k and k]


def etat_liste() -> Tuple[Set[str], str]:
    """(cles des identites qui ONT une base aux yeux du module VA, raison).
    raison non vide : la liste de l'equipe n'a pas pu etre lue, l'ensemble
    vient alors du registre du bot."""
    liens, err = liens_equipe()
    if err:
        return {cle(k) for k in bases_registre()}, err
    out = set()
    for l in liens:
        i = identite_de_base(l.get("display_name"))
        if i:
            out.add(cle(i))
    return out, ""


# ─────────────────────────────────────────────────────────── identites ──

def trouver(identite, identites) -> Optional[str]:
    """Le nom EXACT (celui du dossier) qui correspond, ou None."""
    c = cle(identite)
    return next((n for n in (identites or []) if cle(n) == c), None)


def proches(identite, identites, n: int = 5) -> List[str]:
    """Les noms qui ressemblent : faute de frappe, nom tronque ou rallonge."""
    c = cle(identite)
    par_cle = {cle(x): x for x in (identites or [])}
    vus: List[str] = []
    for k in difflib.get_close_matches(c, list(par_cle), n=n, cutoff=0.6):
        vus.append(par_cle[k])
    if len(c) >= 3:
        for k, nom in sorted(par_cle.items()):
            if (c in k or k in c) and nom not in vus:
                vus.append(nom)
    return vus[:n]


def shortcode_base(identite, essai: int = 0) -> str:
    """« tpl » + l'identite reduite a [a-z0-9_-], 24 signes au plus ; un
    chiffre au bout a partir du 2e essai (tplbob, tplbob2, tplbob3...)."""
    s = unicodedata.normalize("NFKD", str(identite or "")).encode("ascii", "ignore").decode()
    propre = re.sub(r"[^a-z0-9_-]", "", s.lower())
    suffixe = "" if essai <= 0 else str(essai + 1)
    return ("tpl" + propre)[:24 - len(suffixe)] + suffixe


#: Borne du parcours des adresses connues (aucun appel : juste du calcul).
_RANG_MAX = 1000


def premier_essai(identite, prises: Iterable[str]) -> int:
    """Le rang de l'adresse a essayer en premier : juste apres la plus haute
    deja tenue (registre, liste de l'equipe). Une page desactivee garde son
    adresse ; repartir de tpl<nom> a chaque remplacement payait un POST par
    remplacement passe, et le 7e bloquait l'identite pour de bon."""
    p = {str(x).lower() for x in prises or ()}
    haut = -1
    for k in range(_RANG_MAX):
        if shortcode_base(identite, k) in p:
            haut = k
    return haut + 1


# ───────────────────────────────────────────────── budget GetMySocial ──
#
# Ces deux appels REST ne passent pas par gms._call_tool, qui tient la pause
# et le compteur du jour. Sans les reprendre ici, un refus « today: 0 » ne
# fermait rien et nos appels n'etaient pas comptes -- exactement le trou que
# list_links_team avait, et qui entretenait le refus (voir gms.py).

def _refus_quota() -> str:
    try:
        reste = int(gms.pause_restante() or 0)
    except Exception:                                        # noqa: BLE001
        reste = 0
    if reste > 0:
        return ("quota GetMySocial épuisé — reprise vers "
                + time.strftime("%H:%M", time.localtime(time.time() + reste)))
    try:
        if not gms.budget_ok(ETIQUETTE):
            return "budget GetMySocial du jour réservé à la paie (podium, primes) — relance plus tard"
    except Exception:                                        # noqa: BLE001
        pass
    return ""


def _noter(status) -> None:
    """Compte l'appel dans le budget du jour de gms (a faire DANS api_tag :
    l'etiquette est lue au moment de noter)."""
    try:
        gms._api_note(status)
    except Exception:                                        # noqa: BLE001
        pass                     # compter est un confort, jamais une panne


def _refus_429(r) -> str:
    texte = getattr(r, "text", "") or ""
    try:
        gms._gms_note_429()
    except Exception:                                        # noqa: BLE001
        pass
    try:
        gms._noter_refus(texte)      # « retry after N / today: 0 » arme la pause
    except Exception:                                        # noqa: BLE001
        pass
    refus = _refus_quota()
    return refus or "GetMySocial freine (429) — réessaie dans une minute"


def _code_erreur(r) -> Tuple[str, str]:
    """(code, message) d'une reponse d'erreur, quelle que soit sa forme."""
    texte = getattr(r, "text", "") or ""
    code, message = "", ""
    try:
        j = r.json()
    except Exception:                                        # noqa: BLE001
        j = None
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            code = str(e.get("code") or e.get("type") or "")
            message = str(e.get("message") or "")
        elif isinstance(e, str):
            code = e
        code = code or str(j.get("code") or "")
        message = message or str(j.get("message") or "")
    if not code:
        m = re.search(r"shortcode_taken|shortcode_recently_deleted|plan_limit_reached"
                      r"|LIMIT_FILE_SIZE|invalid_[a-z_]+|[a-z]+_permission_denied", texte)
        code = m.group(0) if m else ""
    return code, (message or texte)[:300]


# ───────────────────────────────────────────────────────── le modele ──

def lire_modele(force: bool = False) -> Tuple[Optional[Dict[str, Any]], str]:
    """(modele, erreur) : la page modele telle que GET /v3/links la rend.
    Jamais d'exception : l'erreur est une phrase a montrer."""
    lid = config()["base_link_id"]
    with _VERROU_CACHE:
        c = _CACHE_MODELE
        if (not force and c["id"] == lid and c["modele"]
                and time.time() - c["t"] < TTL_MODELE):
            return copy.deepcopy(c["modele"]), ""
    refus = _refus_quota()
    if refus:
        return None, refus
    cle_api = gms.get_api_key()
    if not cle_api:
        return None, "clé API GetMySocial absente"
    with gms.api_tag(ETIQUETTE):
        try:
            r = requests.get(f"{gms.PUBLIC_REST_BASE}/links/{lid}",
                             headers={"Authorization": f"Bearer {cle_api}"}, timeout=20)
        except Exception as e:                               # noqa: BLE001
            _noter(0)
            return None, f"page modèle illisible (réseau : {type(e).__name__})"
        _noter(r.status_code)
    if r.status_code == 429:
        return None, _refus_429(r)
    if r.status_code == 404:
        return None, f"page modèle {lid} introuvable dans GetMySocial"
    if r.status_code != 200:
        code, msg = _code_erreur(r)
        return None, f"page modèle illisible (HTTP {r.status_code} {code} : {msg[:150]})"
    try:
        m = r.json()
    except Exception:                                        # noqa: BLE001
        m = None
    if not isinstance(m, dict) or not m.get("id"):
        return None, "page modèle : réponse illisible"
    if m.get("type") != "landing":
        return None, f"la page modèle {lid} n'est pas une page (type {m.get('type')!r})"
    with _VERROU_CACHE:
        _CACHE_MODELE.update(id=lid, t=time.time(), modele=copy.deepcopy(m))
    return copy.deepcopy(m), ""


# ─────────────────────────────────────────────────────────── les images ──

_MARQUES_HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_HEIF = {"pret": None}


def _est_heic(donnees: bytes) -> bool:
    return len(donnees) > 12 and donnees[4:8] == b"ftyp" and donnees[8:12] in _MARQUES_HEIF


def _heif_dispo() -> bool:
    """pillow_heif branche sur PIL, si installe (il l'est sur le VPS pour le
    spoofer). Les photos d'iPhone arrivent en HEIC ; GetMySocial les refuse."""
    if _HEIF["pret"] is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _HEIF["pret"] = True
        except Exception:                                    # noqa: BLE001
            _HEIF["pret"] = False
    return bool(_HEIF["pret"])


def _ouvrir(donnees: bytes, quoi: str):
    """(image PIL redressee, erreur)."""
    from PIL import Image, ImageOps
    if not donnees:
        return None, f"{quoi} : fichier vide"
    if _est_heic(donnees) and not _heif_dispo():
        return None, f"{quoi} : photo HEIC (iPhone) illisible ici — envoie-la en JPG ou PNG"
    try:
        im = Image.open(io.BytesIO(donnees))
        im.load()
    except Image.DecompressionBombError:
        return None, f"{quoi} : image trop grande"
    except Exception:                                        # noqa: BLE001
        return None, f"{quoi} : ce n'est pas une image lisible (JPG, PNG, WEBP, HEIC)"
    try:
        # un telephone enregistre la photo couchee et note « a tourner » dans
        # l'EXIF ; GetMySocial efface l'EXIF : sans ce redressement, la photo
        # arrivait de travers sur la page
        im = ImageOps.exif_transpose(im)
    except Exception:                                        # noqa: BLE001
        pass
    if min(im.size) < COTE_MINI:
        return None, f"{quoi} : image trop petite ({im.size[0]}×{im.size[1]})"
    return im, ""


def _sur_8_bits(im):
    """Une image 16 ou 32 bits (PNG gris 16 bits, TIFF) ramenee sur 8 bits.
    convert("RGB") ecrete a 255 : un PNG gris 16 bits devenait une photo
    toute blanche, acceptee sans un mot (Pillow 12.3)."""
    if im.mode.startswith("I;16"):
        im = im.convert("I")
    if im.mode not in ("I", "F"):
        return im
    lo, hi = im.getextrema()
    if im.mode == "F" and 0 <= lo and hi <= 1.0:
        plafond = 1.0                   # flottants 0..1
    elif hi <= 255:
        plafond = 255.0
    elif hi <= 65535:
        plafond = 65535.0               # le cas courant : 16 bits
    else:
        plafond = float(hi)
    return im.point(lambda v: v * (255.0 / plafond)).convert("L")


def _en_rgb(im):
    from PIL import Image
    im = _sur_8_bits(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        fond = Image.new("RGB", im.size, (255, 255, 255))
        fond.paste(im, mask=im.split()[-1])
        return fond
    return im.convert("RGB")


def _recadrer(im, largeur: int, hauteur: int):
    """Le plus grand rectangle de proportions largeur:hauteur, au centre."""
    w, h = im.size
    cible = largeur / hauteur
    if w / h > cible:
        nw = max(1, round(h * cible))
        x = (w - nw) // 2
        return im.crop((x, 0, x + nw, h))
    nh = max(1, round(w / cible))
    y = (h - nh) // 2
    return im.crop((0, y, w, y + nh))


def _jpeg(im) -> bytes:
    for q in (90, 85, 80, 70, 60):
        b = io.BytesIO()
        im.save(b, "JPEG", quality=q, optimize=True)
        if b.tell() <= TAILLE_MAX:
            return b.getvalue()
    return b.getvalue()


def preparer_images(pp_bytes: bytes, fond_bytes: bytes) -> Tuple[Optional[bytes], Optional[bytes], str]:
    """(pp_jpeg, fond_jpeg, erreur). La photo de profil est recadree au centre
    en carre (400 a 1024 px), le fond au centre en 9:16 puis 1080×1920 : les
    dimensions que GetMySocial conseille. Tout part en JPEG, sans EXIF."""
    from PIL import Image
    try:
        pp, err = _ouvrir(pp_bytes, "photo de profil")
        if err:
            return None, None, err
        fond, err = _ouvrir(fond_bytes, "fond")
        if err:
            return None, None, err
        pp = _recadrer(_en_rgb(pp), 1, 1)
        cote = min(max(pp.size[0], PP_MIN), PP_MAX)
        if pp.size != (cote, cote):
            pp = pp.resize((cote, cote), Image.LANCZOS)
        fond = _recadrer(_en_rgb(fond), 9, 16).resize(FOND, Image.LANCZOS)
        a, b = _jpeg(pp), _jpeg(fond)
    except Exception as e:                                   # noqa: BLE001
        return None, None, f"photos illisibles ({type(e).__name__}: {e})"
    if len(a) > TAILLE_MAX or len(b) > TAILLE_MAX:
        return None, None, "photo trop lourde pour GetMySocial (10 Mo)"
    return a, b, ""


# ───────────────────────────────────────────────────────── la creation ──

_OF = re.compile(r"^\s*(?:https?://)?(?:www\.)?onlyfans\.com/", re.I)
#: Les cles ou GetMySocial range une destination (bouton, regle pays,
#: redirection) : les memes que liens_identite_us._CLES_URL. Un libelle qui
#: contient « onlyfans.com » est du texte : on n'y touche pas.
_CLES_URL = ("url", "destination_url")
_CHAMPS_PAGE = ("smart_redirect", "geofilters", "ab_testing", "traffic_recovery",
                "social_media_links")


def _vers_of(obj: Any, cible: str) -> Any:
    """Copie de obj ou chaque destination OnlyFans vise `cible`."""
    if isinstance(obj, dict):
        return {k: (cible if k in _CLES_URL and isinstance(v, str) and _OF.match(v) else _vers_of(v, cible))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_vers_of(v, cible) for v in obj]
    return obj


def champs_creation(modele: Dict[str, Any], shortcode: str, display_name: str,
                    equipe: str, nom_affiche: Optional[str] = None,
                    onlyfans: Optional[str] = None) -> Dict[str, str]:
    """Les champs texte du POST multipart : ceux du modele, encodes comme dans
    l'essai reussi (dict/list/bool en JSON, le reste en texte), plus l'adresse,
    le nom, le type et l'equipe (SANS « tm_ », comme le PATCH v3). `onlyfans` :
    l'adresse que visent les boutons OnlyFans (la forme de la requete ne
    change pas, seule la valeur)."""
    m = copy.deepcopy(modele or {})
    if isinstance(m.get("buttons"), list):
        # block_id est l'identifiant du bouton DANS la page modele ; les cles a
        # None sont celles que l'essai n'envoyait pas
        m["buttons"] = [{k: v for k, v in b.items() if k != "block_id" and v is not None}
                        if isinstance(b, dict) else b for b in m["buttons"]]
    if onlyfans:
        for champ in ("buttons",) + _CHAMPS_PAGE:
            if m.get(champ) is not None:
                m[champ] = _vers_of(m[champ], onlyfans)
    if nom_affiche:
        m["name_user"] = nom_affiche
    champs = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else str(v))
              for k, v in m.items() if k not in EXCLUS and v is not None}
    champs.update(shortcode=shortcode, display_name=display_name, type="landing",
                  team_id=_sans_tm(equipe))
    return champs


#: Les codes 409 qui disent « adresse prise ». Un autre 409 (conflit de nom,
#: d'equipe...) n'a rien a voir avec l'adresse : en changer brulait 6 POST
#: pour finir sur « adresses deja prises », faux.
_CODES_ADRESSE = ("", "shortcode_taken", "shortcode_recently_deleted")


def _retrouver(sc: str, display_name: str, quoi: str):
    """Apres une panne (reseau, 5xx, 524 de Cloudflare) : l'origine a pu finir
    la creation. Relit l'equipe ; la page a cette adresse et ce nom est
    reprise (et verifiee comme une autre). (lien, erreur)."""
    liens, err = liens_equipe(force=True)
    if not err:
        trouve = next((l for l in liens if str(l.get("shortcode") or "").lower() == sc.lower()), None)
        if trouve and str(trouve.get("display_name") or "") == display_name:
            print(f"[bases_us] {quoi} mais {sc} existe ({trouve.get('id')}) : reprise", flush=True)
            return trouve, ""
        if not trouve:
            return None, (f"GetMySocial en panne ({quoi}) ; {sc} absente de {NOM_EQUIPE} juste après "
                          "— renvoie dans quelques minutes (une page apparue entre-temps sera coupée)")
    return None, (f"GetMySocial en panne ({quoi}) — la page {sc} a peut-être été créée : "
                  "vérifie dans GetMySocial avant de renvoyer")


def _poster(modele, identite, display_name, equipe, nom_affiche, pp, fond,
            prises: Iterable[str] = (), onlyfans: Optional[str] = None):
    """(lien, shortcode, erreur, adresses refusees en 409). Saute sans appel
    les adresses deja connues ; change d'adresse tant qu'elle est prise."""
    prises = {str(x).lower() for x in prises or ()}
    rang = premier_essai(identite, prises)
    sc = shortcode_base(identite, rang)
    refusees: List[str] = []
    postes = 0
    while postes < ESSAIS_SHORTCODE and rang < _RANG_MAX:
        sc = shortcode_base(identite, rang)
        rang += 1
        if sc in prises:
            continue
        refus = _refus_quota()
        if refus:
            return None, sc, refus, refusees
        cle_api = gms.get_api_key()
        if not cle_api:
            return None, sc, "clé API GetMySocial absente", refusees
        champs = champs_creation(modele, sc, display_name, equipe, nom_affiche, onlyfans)
        fichiers = {"profilePicture": ("pp.jpg", pp, "image/jpeg"),
                    "backgroundImage": ("fond.jpg", fond, "image/jpeg")}
        postes += 1
        with gms.api_tag(ETIQUETTE):
            try:
                r = requests.post(f"{gms.PUBLIC_REST_BASE}/links",
                                  headers={"Authorization": f"Bearer {cle_api}"},
                                  data=champs, files=fichiers, timeout=60)
            except Exception as e:                           # noqa: BLE001
                _noter(0)
                r = None
                panne = f"réseau : {type(e).__name__}"
            else:
                _noter(r.status_code)
        if r is None or r.status_code >= 500:
            # la requete a pu aboutir avant la coupure (524 : Cloudflare a
            # lache, l'origine a fini) : relancer sans regarder donnait deux
            # pages « TEMPLATE x » actives
            lien, err = _retrouver(sc, display_name, panne if r is None else f"HTTP {r.status_code}")
            return lien, sc, err, refusees
        if r.status_code in (200, 201):
            try:
                lien = r.json()
            except Exception:                                # noqa: BLE001
                lien = None
            if not isinstance(lien, dict):
                return None, sc, (f"page {sc} créée mais réponse illisible — "
                                  "vérifie dans GetMySocial avant de renvoyer"), refusees
            return lien, sc, "", refusees
        code, msg = _code_erreur(r)
        if r.status_code == 409 and code in _CODES_ADRESSE:
            print(f"[bases_us] {sc} : {code or 'adresse prise'} — adresse suivante", flush=True)
            refusees.append(sc)
            prises.add(sc)
            continue
        if r.status_code == 409:
            return None, sc, f"GetMySocial refuse (409 {code}) : {msg[:200]}", refusees
        if r.status_code == 429:
            return None, sc, _refus_429(r), refusees
        if r.status_code == 403 and code == "plan_limit_reached":
            # « ne pas reessayer sans agir » (doc de l'API) : il faut liberer
            # de la place ou changer de forfait, pas boucler
            return None, sc, "limite du forfait GetMySocial atteinte : plus de page possible", refusees
        if r.status_code in (401, 403, 404):
            # jamais vu en vrai dans cette equipe : l'essai du 06/10 a cree
            # dans NOUM FR
            return None, sc, (f"GetMySocial refuse de créer dans {NOM_EQUIPE} ({equipe}) : la clé API "
                              f"n'y a peut-être pas droit (HTTP {r.status_code} {code} : {msg[:150]})"), refusees
        if r.status_code == 400 and code == "LIMIT_FILE_SIZE":
            return None, sc, "photo trop lourde pour GetMySocial (10 Mo)", refusees
        return None, sc, f"GetMySocial refuse (HTTP {r.status_code} {code}) : {msg[:200]}", refusees
    return None, sc, (f"{len(refusees)} adresse(s) déjà prise(s) ailleurs ({', '.join(refusees)}) : "
                      "réessaie plus tard"), refusees


#: Une photo ENVOYEE : images.getmysocial.com/<user>/<ms>-<hash>.<ext>
#: (essai du 06/10 : .../68e4961d3abdf07547f50bd7/1791248795949-611e8be94c36.jpg).
_URL_ENVOI = re.compile(r"^https://images\.getmysocial\.com/(?:[a-z_-]+/)?[0-9a-f]{16,40}/"
                        r"(\d{12,14})-[0-9a-z]+\.(?:jpe?g|png|webp|gif)(?:\?.*)?$", re.I)


def _photo_neuve(url, depuis: float) -> bool:
    m = _URL_ENVOI.match(str(url or ""))
    return bool(m) and int(m.group(1)) / 1000.0 >= depuis - MARGE_PHOTO


def verifier(lien: Dict[str, Any], modele: Dict[str, Any], display_name: str,
             equipe: str, shortcode: str, depuis: Optional[float] = None) -> str:
    """Ce qui cloche dans la page creee ("" si elle est conforme). Le 201 seul
    ne prouve pas que les photos ont pris : sans fichier, GetMySocial pose une
    photo par defaut et rend quand meme 201. Une photo par defaut n'est ni
    vide ni celle du modele : on exige une photo ENVOYEE a l'instant (son
    horodatage, compare a la creation de la page -- l'horloge du serveur --
    ou a l'heure du POST)."""
    cree = lien.get("created")
    try:
        cree = float(cree)
        cree = cree / 1000.0 if cree > 1e12 else cree
    except (TypeError, ValueError):
        cree = 0.0
    ref = cree if cree > 0 else (depuis or 0.0)
    pb = []
    for champ, quoi in (("profile_picture", "photo de profil"), ("background_image", "fond")):
        v = lien.get(champ)
        if not v:
            pb.append(f"{quoi} absent")
        elif v == (modele or {}).get(champ):
            pb.append(f"{quoi} identique au modèle")
        elif ref and not _photo_neuve(v, ref):
            pb.append(f"{quoi} pas celle envoyée (photo par défaut ? {str(v)[:120]})")
    if lien.get("display_name") != display_name:
        pb.append(f"nom « {lien.get('display_name')} » au lieu de « {display_name} »")
    if _avec_tm(lien.get("team_id")) != _avec_tm(equipe):
        pb.append(f"équipe {lien.get('team_id')} au lieu de {_avec_tm(equipe)}")
    if lien.get("shortcode") and str(lien["shortcode"]).lower() != shortcode.lower():
        pb.append(f"adresse {lien.get('shortcode')} au lieu de {shortcode}")
    return ", ".join(pb)


def _desactiver(link_id: str) -> Dict[str, Any]:
    """Couper une page, jamais la supprimer : disable_link est reversible."""
    try:
        with gms.api_tag(ETIQUETTE):
            res = gms.disable_link(link_id)
        return res if isinstance(res, dict) else {"ok": False, "error": "réponse vide"}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _renommer(link_id: str, nom: str, team) -> Dict[str, Any]:
    """Changer le nom d'une page (update_link exige display_name pour une
    page). gms.update_link quand il existe, sinon l'outil MCP directement."""
    try:
        with gms.api_tag(ETIQUETTE):
            maj = getattr(gms, "update_link", None)
            if callable(maj):
                res = maj(link_id, {"display_name": nom}, team_id=team or None)
            else:
                args = {"link_id": link_id, "display_name": nom}
                if team:
                    args["team_id"] = _avec_tm(team)
                res = gms._call_tool("update_link", args)
        return res if isinstance(res, dict) else {"ok": False, "error": "réponse vide"}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _vider_cache() -> None:
    try:
        gms.invalidate_grouping_cache()      # la liste de l'equipe a change
    except Exception:                                        # noqa: BLE001
        pass


def _rejeter(lien, lid, sc, pb, display_name, eq, k, nom, par) -> str:
    """Une page creee mais non conforme : coupee ET renommee. Coupee seule,
    elle gardait « TEMPLATE x » et le module VA, qui prend une page inactive
    quand c'est la seule, la copiait pour chaque VA (sans fond, ou avec la
    mauvaise photo). Rend la phrase d'erreur."""
    if lid.startswith("lnk_"):
        coupe = _desactiver(lid)
        nouveau = f"{PREFIXE_REJET}{display_name} {time.strftime('%d-%m %Hh%M')}"
        renomme = _renommer(lid, nouveau, lien.get("team_id") or eq)
        _vider_cache()
    else:
        coupe = renomme = {"ok": False, "error": "id inconnu"}
        nouveau = ""

    def trace(e):
        e.setdefault("rates", []).append({
            "link_id": lid, "shortcode": sc, "raison": pb, "desactivee": bool(coupe.get("ok")),
            "renommee": nouveau if renomme.get("ok") else "", "par": str(par or ""),
            "quand": int(time.time())})
    if not _maj_registre(k, nom, trace):
        print(f"[bases_us] trace de {lid} non écrite dans le registre", flush=True)
    print(f"[bases_us] {display_name} : page {lid} non conforme ({pb})", flush=True)
    phrase = f"page créée mais {pb} : " + (
        "désactivée" if coupe.get("ok")
        else f"PAS désactivée ({str(coupe.get('error') or '')[:120]})")
    if not renomme.get("ok"):
        phrase += (f", et elle s'appelle encore « {display_name} » ({str(renomme.get('error') or '')[:120]}) : "
                   "le module VA peut la copier — à renommer ou couper dans GetMySocial")
    return phrase + f" ({lid or sc})"


def creer_base(identite, pp_bytes: bytes, fond_bytes: bytes, nom_affiche: Optional[str] = None,
               par: str = "", identites: Optional[List[str]] = None) -> Dict[str, Any]:
    """Cree (ou remplace) la base « TEMPLATE <identite> ».

    Rend {ok, url, link_id, shortcode, remplace, coupees, erreur,
    avertissement}. coupees = les anciennes pages « TEMPLATE <identite> »
    desactivees (remplace = la premiere). ok est FAUX si l'une d'elles n'a pas
    pu etre coupee : la nouvelle existe (url) mais le module VA, qui prend la
    plus ancienne active, ne s'en servirait pas.
    Si `identites` est fourni, l'identite doit en faire partie."""
    out: Dict[str, Any] = {"ok": False, "url": "", "link_id": "", "shortcode": "",
                           "remplace": None, "coupees": [], "erreur": "", "avertissement": ""}
    nom = str(identite or "").strip().lstrip("@").strip()
    if not nom:
        out["erreur"] = "nom d'identité vide"
        return out
    if identites is not None:
        exact = trouver(nom, identites)
        if not exact:
            p = proches(nom, identites)
            out["erreur"] = (f"« {nom} » n'est pas une identité US"
                             + (f". Proches : {', '.join(p)}" if p else ""))
            return out
        nom = exact
    if shortcode_base(nom) == "tpl":
        out["erreur"] = f"« {nom} » : aucune lettre ni chiffre pour faire l'adresse"
        return out
    nom_affiche = (str(nom_affiche or "").strip() or None)
    if nom_affiche:
        nom_affiche = nom_affiche[:80]
    cfg = config()
    eq = cfg["equipe"]
    display_name = PREFIXE_NOM + nom
    k = cle(nom)

    with _VERROU:
        # les photos d'abord : gratuit et sans reseau. Apres le GET du modele,
        # chaque envoi rate (HEIC, fichier abime) coutait un appel pour rien
        pp, fond, err = preparer_images(pp_bytes, fond_bytes)
        if err:
            out["erreur"] = err
            return out
        modele, err = lire_modele()
        if err:
            out["erreur"] = err
            return out
        # ce que le module VA voit : sans cette liste, impossible de savoir
        # quelles pages couper -- creer quand meme laissait l'ancienne servir
        liens, err = liens_equipe()
        if err:
            out["erreur"] = f"liste de {NOM_EQUIPE} illisible ({err}) : rien n'est créé"
            return out
        precedente = _registre_brut().get(k)
        precedente = precedente if isinstance(precedente, dict) else {}
        prises = _adresses(precedente) | {str(l.get("shortcode") or "").lower() for l in liens}
        debut = time.time()
        lien, sc, err, refusees = _poster(modele, nom, display_name, eq, nom_affiche, pp, fond,
                                          prises, url_onlyfans())
        out["shortcode"] = sc
        if refusees:
            # retenues : le prochain envoi ne les repaiera pas
            def noter_refusees(e):
                e["adresses"] = sorted(set(e.get("adresses") or []) | set(refusees))
            _maj_registre(k, nom, noter_refusees)
        if err:
            out["erreur"] = err
            return out
        lid = str(lien.get("id") or "")
        pb = "réponse sans id de page" if not lid.startswith("lnk_") else \
            verifier(lien, modele, display_name, eq, sc, debut)
        if pb:
            out["erreur"] = _rejeter(lien, lid, sc, pb, display_name, eq, k, nom, par)
            return out

        if refusees:
            # une adresse prise hors de la liste connue : peut-etre une page
            # faite depuis la lecture (cache de 15 min) -- a couper aussi
            frais, err2 = liens_equipe(force=True)
            if not err2:
                liens = frais
        a_couper = [l for l in pages_de_base(liens, nom)
                    if _actif(l) and str(l.get("type") or "") != "directlink"
                    and str(l.get("id")) != lid]
        sc_final = str(lien.get("shortcode") or sc)
        url = f"{gms.PUBLIC_LINK_DOMAIN}/{sc_final}"
        anciens = [str(x) for x in precedente.get("anciens") or []]
        for x in [precedente.get("link_id")] + [l.get("id") for l in a_couper]:
            if x and str(x) != lid and str(x) not in anciens:
                anciens.append(str(x))
        entree = {"identite": nom, "link_id": lid, "shortcode": sc_final,
                  "url": url, "display_name": display_name,
                  "nom_affiche": nom_affiche or (modele.get("name_user") or ""),
                  "equipe": eq, "modele": cfg["base_link_id"], "onlyfans": url_onlyfans(),
                  "par": str(par or ""), "quand": int(time.time()), "anciens": anciens}
        reg = _registre_brut()
        avant = reg.get(k) if isinstance(reg.get(k), dict) else {}
        entree["adresses"] = sorted(_adresses(avant) | {sc_final.lower()} | set(refusees))
        for garde in ("rates", "non_desactives"):
            if avant.get(garde):
                entree[garde] = avant[garde]
        reg[k] = entree
        if not _ecrire_registre(reg):
            # le registre n'est que l'historique du bot : le module VA lit la
            # liste de l'equipe. On coupe donc quand meme les anciennes.
            out["avertissement"] = "registre data/bases_identite_us.json non écrit"
        out.update(ok=True, url=url, link_id=lid, shortcode=sc_final)

        coupees, ratees = [], []
        for l in a_couper:
            res = _desactiver(str(l.get("id")))
            (coupees if res.get("ok") else ratees).append((l, res))
        # APRES les desactivations : vide avant, la liste relue entre-temps
        # par un VA montrait l'ancienne encore active, et restait 15 min en
        # cache -- les copies reprenaient les anciennes photos
        _vider_cache()
        out["coupees"] = [str(l.get("id")) for l, _ in coupees]
        out["remplace"] = out["coupees"][0] if out["coupees"] else None
        if ratees:
            noms = ", ".join(str(l.get("shortcode") or l.get("id")) for l, _ in ratees)
            raison = str(ratees[0][1].get("error") or "")[:150]

            def noter_ratees(e):
                if e.get("link_id") == lid:
                    nd = list(e.get("non_desactives") or [])
                    nd += [str(l.get("id")) for l, _ in ratees if str(l.get("id")) not in nd]
                    e["non_desactives"] = nd
            _maj_registre(k, nom, noter_ratees)
            out["ok"] = False
            out["erreur"] = (f"{url} créée, mais {noms} pas désactivée ({raison}) : la nouvelle base "
                             f"ne sera PAS utilisée pour les VA tant que {noms} est active — "
                             "la couper dans GetMySocial")
        print(f"[bases_us] {display_name} : {url} ({lid})"
              + (f", coupe {', '.join(out['coupees'])}" if out["coupees"] else "")
              + (f", PAS coupées : {', '.join(str(l.get('id')) for l, _ in ratees)}" if ratees else ""),
              flush=True)
        return out
