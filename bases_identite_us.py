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

LE GROUPE « TEMPLATES » (proprietaire, 06/10/2026)
    « Il faut stocker quelque part uniquement les templates sur GMS. » Les
    pages de base vivaient au milieu des liens des VA de JESSY LE RETOUR :
    elles sont rangees dans un groupe GetMySocial « TEMPLATES » de la meme
    equipe, et RIEN D'AUTRE n'y reste. Ce qui y va : la regle des noms de
    base (identite_de_base), celle du module VA -- une page est « une base »
    au meme sens des deux cotes. L'id du groupe est garde dans
    data/bases_identite_us_groupe.json (list_groups puis create_group une
    seule fois) ; liens_identite_us le lit pour sortir du groupe une copie de
    VA qui l'aurait herite de sa base (duplicate_link). Une page neuve y entre
    a sa creation (group_id dans le POST, sinon assign_links_to_group) ;
    l'entretien du cog (ranger_templates) y range celles qui n'y sont pas et
    en sort les copies de VA connues et les pages rejetees -- rien d'autre,
    sans preuve -- en un appel par sens, aucun si tout est en place. Ses
    appels sont au rang « fond » (ETIQUETTE_FOND) ; un refus de droits (403)
    est retenu un jour.

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

import ast
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
#: L'etiquette de l'ENTRETIEN (compteur du panneau, rangement du groupe),
#: rang « fond » dans gms.PRIORITES : personne n'attend derriere. Sous
#: « bases-us », ce rangement cosmetique continuait de consommer la quota
#: commune (podium, paie) quand le dashboard et le warm s'effacaient deja.
ETIQUETTE_FOND = "bases-us-fond"
_FIL = threading.local()


def _etiquette() -> str:
    """L'etiquette des appels de CE fil : « fond » dans au_fond(), sinon
    celle d'une creation."""
    return getattr(_FIL, "etiquette", None) or ETIQUETTE


class au_fond:
    """Contexte : les appels GetMySocial de ce fil passent au rang « fond »
    (l'entretien du cog, lance dans un fil de l'executor)."""

    def __enter__(self):
        self.prev = getattr(_FIL, "etiquette", None)
        _FIL.etiquette = ETIQUETTE_FOND
        return self

    def __exit__(self, *exc):
        _FIL.etiquette = self.prev
        return False

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

#: Le groupe GetMySocial des pages de base, et ou son id est garde.
GROUPE = _RACINE / "data" / "bases_identite_us_groupe.json"
NOM_GROUPE = "TEMPLATES"
#: assign/remove_links_from_group refusent plus de 100 ids par appel.
LOT_GROUPE = 100
#: list_groups rend 100 groupes par page ; une equipe en tient 500 au plus.
PAGES_GROUPES = 5
#: Au-dela, ce ne sont plus des copies egarees : un « TEMPLATES » fait a la
#: main pour autre chose, ou une liste mal lue. Le groupe n'est pas vide a
#: l'aveugle : c'est dit, et rien ne bouge.
INTRUS_MAX = 25
#: Un refus de DROITS (403 team_permission_denied : la cle API sans
#: manage_groups dans l'equipe) est retenu un jour. Sans ca, chaque entretien
#: (donc chaque push, le cron redemarre le bot) et chaque creation repayaient
#: list_groups + create_group, ou un assign, pour le meme refus.
REFUS_DROITS_S = 86400
_RE_DROITS = re.compile(r"permission_denied|\b403\b", re.I)

#: Les creations par la fenetre du panneau EN COURS : {cle: {identite,
#: user_id, channel_id, guild_id, pid, quand}}. Un redemarrage (un par push)
#: pendant la creation ne laissait aucune trace dans le salon -- le flux par
#: message, lui, garde son ⏳. Le cog relit ce fichier au demarrage.
EN_COURS = _RACINE / "data" / "bases_identite_us_en_cours.json"

_VERROU = threading.RLock()          # une creation a la fois (registre compris)
_VERROU_CACHE = threading.Lock()
_VERROU_GROUPE = threading.RLock()
#: L'id du groupe quand le fichier ne s'ecrit pas : sans lui, chaque besoin
#: repayait list_groups.
_GROUPE_MEMOIRE: Dict[str, str] = {"equipe": "", "id": ""}
#: Les refus de droits quand le fichier ne s'ecrit pas : {outil: {quand, erreur}}.
_DROITS_MEMOIRE: Dict[str, Dict[str, Any]] = {}
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
        with gms.api_tag(_etiquette()):
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


def _nombre(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def base_retenue(liens: Iterable[Dict[str, Any]], identite) -> Optional[Dict[str, Any]]:
    """La page « TEMPLATE <identite> » que le module VA COPIE : SA regle
    (liens_identite_us.bases : la page, active, puis la plus ancienne), la
    meme ici sans lui. None s'il n'y en a pas."""
    pages = pages_de_base(liens, identite)
    if not pages:
        return None
    m = _liu()
    f = getattr(m, "bases", None) if m else None
    if callable(f):
        try:
            choix = list((f(pages) or {}).values())
            if choix:
                return choix[0]
        except Exception as e:                               # noqa: BLE001
            _dire_une_fois("bases", f"[bases_us] liens_identite_us.bases : {type(e).__name__}: {e}")
    return sorted(pages, key=lambda l: (str(l.get("type") or "") == "directlink", not _actif(l),
                                        _nombre(l.get("created")), str(l.get("id"))))[0]


def nom_affiche_de(liens: Iterable[Dict[str, Any]], identite) -> str:
    """Le nom affiche (name_user) de la page que les VA copient, "" sans page."""
    return str((base_retenue(liens, identite) or {}).get("name_user") or "").strip()[:80]


def etat_pages() -> Tuple[Set[str], Dict[str, str], str]:
    """(cles des identites qui ONT une base aux yeux du module VA, {cle: nom
    affiche de cette base}, raison). Le nom vient de la MEME lecture : une
    page faite a la main n'est pas au registre du bot, et la fenetre arrivait
    vide -- refaire ses photos lui donnait le nom du modele (« Emy ♡ »).
    raison non vide : la liste de l'equipe n'a pas pu etre lue, tout vient
    alors du registre du bot."""
    liens, err = liens_equipe()
    if err:
        reg = bases_registre()
        return ({cle(k) for k in reg},
                {cle(k): str(v.get("nom_affiche") or "")[:80] for k, v in reg.items() if v.get("nom_affiche")},
                err)
    faites: Set[str] = set()
    for l in liens:
        i = identite_de_base(l.get("display_name"))
        if i:
            faites.add(cle(i))
    noms = {}
    for k in faites:
        n = nom_affiche_de(liens, k)
        if n:
            noms[k] = n
    return faites, noms, ""


def etat_liste() -> Tuple[Set[str], str]:
    """(cles des identites qui ONT une base aux yeux du module VA, raison).
    raison non vide : la liste de l'equipe n'a pas pu etre lue, l'ensemble
    vient alors du registre du bot."""
    faites, _noms, raison = etat_pages()
    return faites, raison


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
        if not gms.budget_ok(_etiquette()):
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


# ─────────────────────────────────────────── le groupe « TEMPLATES » ──

def _sans_grp(gid) -> str:
    g = str(gid or "").strip().lower()
    return g[4:] if g.startswith("grp_") else g


def _avec_grp(gid) -> str:
    g = str(gid or "").strip()
    return g if not g or g.startswith("grp_") else "grp_" + g


def meme_groupe(a, b) -> bool:
    """Deux ids de groupe designent-ils le meme ? Avec ou sans « grp_ » : les
    outils MCP le mettent, l'API privee non (gms._assign_via_v3)."""
    x = _sans_grp(a)
    return bool(x) and x == _sans_grp(b)


def _etat_groupe() -> Dict[str, Any]:
    d = safe_json.load(GROUPE, default={}) or {}
    return d if isinstance(d, dict) else {}


def _ecrire_groupe(d: Dict[str, Any]) -> bool:
    try:
        GROUPE.parent.mkdir(parents=True, exist_ok=True)
        return bool(safe_json.write(GROUPE, d, indent=1))
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases_us] {GROUPE.name} non écrit : {type(e).__name__}: {e}", flush=True)
        return False


def groupe_connu() -> str:
    """L'id du groupe TEMPLATES de l'equipe des bases (« grp_… »), "" s'il
    n'est pas encore connu. AUCUN appel : liens_identite_us s'en sert a
    chaque copie de VA."""
    eq = equipe()
    d = _etat_groupe()
    if _avec_tm(d.get("equipe")) == eq and d.get("id"):
        return _avec_grp(d["id"])
    if _GROUPE_MEMOIRE["equipe"] == eq and _GROUPE_MEMOIRE["id"]:
        return _GROUPE_MEMOIRE["id"]
    return ""


def _retenir_groupe(gid: str, **plus) -> None:
    eq = equipe()
    _GROUPE_MEMOIRE.update(equipe=eq, id=gid)
    d = _etat_groupe()
    if _avec_tm(d.get("equipe")) != eq:
        d = {}
    d.update(equipe=eq, id=gid, nom=NOM_GROUPE, quand=int(time.time()), **plus)
    d.pop("oublie", None)
    if not _ecrire_groupe(d):
        print(f"[bases_us] id du groupe {NOM_GROUPE} gardé en mémoire seulement", flush=True)


def _oublier_groupe(raison: str) -> None:
    """Le groupe a ete supprime a la main (group_not_found) : son id ne sert
    plus. Garde en trace, jamais efface sans un mot."""
    d = _etat_groupe()
    ancien = d.pop("id", None) or _GROUPE_MEMOIRE.get("id")
    _GROUPE_MEMOIRE.update(equipe="", id="")
    d["oublie"] = {"id": ancien, "raison": str(raison or "")[:200], "quand": int(time.time())}
    _ecrire_groupe(d)
    print(f"[bases_us] groupe {NOM_GROUPE} {ancien} introuvable ({str(raison)[:120]}) : il sera "
          "recherché ou recréé", flush=True)


def refus_du_groupe(statut: int, code: str, message: str) -> bool:
    """Ce refus du POST peut-il venir du group_id, seul champ ajoute a la
    requete de l'essai du 06/10 ? La doc de create_link en nomme trois :
    400 invalid_group_id, 404 group_not_found, 403 team_permission_denied
    (manage_groups manquant -- ou create_links : on ne sait pas, la requete
    sans lui le dira). La creation est alors refaite UNE fois sans lui : le
    groupe ne doit jamais couter une page. Tout autre refus (adresse,
    forfait, invalid_url…) se repeterait a l'identique : un seul POST."""
    c, m = str(code or "").lower(), str(message or "").lower()
    if int(statut or 0) not in (400, 403, 404, 422):
        return False
    return "group" in c or "group" in m or (int(statut) == 403 and c == "team_permission_denied")


#: Un refus du group_id dans le POST est retenu un mois : assez pour ne pas
#: repayer un POST rate a chaque page, pas assez pour se priver pour toujours
#: d'un champ que l'API aura pu se mettre a accepter.
REFUS_POST_S = 30 * 86400


def post_avec_groupe() -> bool:
    """Le POST de creation porte-t-il group_id ? Oui, sauf si GetMySocial l'a
    refuse ce mois-ci (la creation avait alors reussi sans lui) : chaque
    page suivante aurait paye un POST rate de plus."""
    refus = _etat_groupe().get("post_refuse")
    if not isinstance(refus, dict):
        return not refus
    try:
        return time.time() - float(refus.get("quand") or 0) > REFUS_POST_S
    except (TypeError, ValueError):
        return False


def _noter_post_refuse(statut: int, code: str, message: str) -> None:
    d = _etat_groupe()
    d["post_refuse"] = {"statut": int(statut), "code": str(code or ""), "message": str(message or "")[:200],
                        "quand": int(time.time())}
    _ecrire_groupe(d)
    print(f"[bases_us] group_id refusé dans le POST (HTTP {statut} {code}) : les pages seront "
          f"rangées dans {NOM_GROUPE} après leur création", flush=True)


def degrouper_par_maj() -> bool:
    """Une copie de VA peut-elle sortir du groupe dans l'update_link de ses
    boutons (group_id "") ? Oui, sauf si GetMySocial l'a refuse ce mois-ci :
    la copie sort alors par remove_links_from_group (liens_identite_us)."""
    refus = _etat_groupe().get("maj_refuse")
    if not isinstance(refus, dict):
        return not refus
    try:
        return time.time() - float(refus.get("quand") or 0) > REFUS_POST_S
    except (TypeError, ValueError):
        return False


def noter_maj_refuse(erreur: str) -> None:
    """group_id "" refuse dans update_link (la meme ecriture sans lui a
    reussi) : retenu, pour ne pas repayer un appel rate a chaque copie."""
    d = _etat_groupe()
    d["maj_refuse"] = {"erreur": str(erreur or "")[:200], "quand": int(time.time())}
    _ecrire_groupe(d)
    print(f"[bases_us] group_id \"\" refusé par update_link ({str(erreur)[:120]}) : les copies de VA "
          f"sortiront de {NOM_GROUPE} par remove_links_from_group", flush=True)


def _refus_droits(outil: str) -> str:
    """"" si l'outil peut partir ; sinon la phrase du refus de droits retenu
    (aucun appel jusqu'a son echeance)."""
    d = _etat_groupe().get("droits_refuses")
    e = d.get(outil) if isinstance(d, dict) else None
    if not isinstance(e, dict):
        e = _DROITS_MEMOIRE.get(outil)
    if not isinstance(e, dict):
        return ""
    fin = _nombre(e.get("quand")) + REFUS_DROITS_S
    if time.time() > fin:
        return ""
    heure = time.strftime("%d/%m %H:%M", time.localtime(fin))
    _dire_une_fois(f"droits:{outil}:{e.get('quand')}",
                   f"[bases_us] {outil} refusé par GetMySocial ({str(e.get('erreur') or '')[:120]}) : "
                   f"plus essayé avant {heure}")
    return f"{outil} refusé par GetMySocial ({str(e.get('erreur') or '')[:120]}) — pas réessayé avant {heure}"


def _noter_droits(outil: str, ok: bool, erreur: str = "") -> None:
    """Retient un refus de droits de l'outil, ou l'efface quand il repasse."""
    if ok:
        _DROITS_MEMOIRE.pop(outil, None)
        d = _etat_groupe()
        refus = d.get("droits_refuses")
        if isinstance(refus, dict) and outil in refus:
            refus.pop(outil)
            _ecrire_groupe(d)
        return
    if not _RE_DROITS.search(str(erreur or "")):
        return                  # panne, quota : rien d'un refus durable
    e = {"erreur": str(erreur or "")[:200], "quand": int(time.time())}
    _DROITS_MEMOIRE[outil] = e
    d = _etat_groupe()
    refus = d.get("droits_refuses") if isinstance(d.get("droits_refuses"), dict) else {}
    refus[outil] = e
    d["droits_refuses"] = refus
    _ecrire_groupe(d)
    print(f"[bases_us] {outil} : droits refusés dans {NOM_EQUIPE} ({str(erreur)[:120]}) — "
          f"plus essayé pendant {REFUS_DROITS_S // 3600} h", flush=True)


def _appel(outil: str, args: Dict[str, Any], etiquette: Optional[str] = "") -> Dict[str, Any]:
    """Un outil MCP par gms (budget, pause, compteur), etiquete ; jamais
    d'exception. `etiquette` None : garder celle de l'appelant
    (liens_identite_us, dont le VA attend derriere son clic)."""
    import contextlib
    try:
        tag = (contextlib.nullcontext() if etiquette is None
               else gms.api_tag(etiquette or _etiquette()))
        with tag:
            r = gms._call_tool(outil, args)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return r if isinstance(r, dict) else {"ok": False, "error": "réponse vide"}


def _donnees(r: Dict[str, Any]) -> Any:
    """Le corps d'une reponse MCP : dict, ou texte JSON / repr Python."""
    d = r.get("data")
    if isinstance(d, str):
        for lire in (json.loads, ast.literal_eval):
            try:
                return lire(d)
            except Exception:                                # noqa: BLE001
                continue
    return d


def _lister_groupes(eq: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """(groupes de l'equipe, erreur). None : on ne SAIT PAS ce qui existe."""
    out: List[Dict[str, Any]] = []
    curseur = None
    refus = _refus_droits("list_groups")
    if refus:
        return None, refus
    for _ in range(PAGES_GROUPES):
        args: Dict[str, Any] = {"team_id": eq, "limit": 100}
        if curseur:
            args["cursor"] = curseur
        r = _appel("list_groups", args)
        if not r.get("ok"):
            err = str(r.get("error") or "list_groups refusé")[:200]
            _noter_droits("list_groups", False, err)
            return None, err
        _noter_droits("list_groups", True)
        d = _donnees(r)
        items = d.get("data") if isinstance(d, dict) else d
        out += [g for g in (items or []) if isinstance(g, dict)]
        curseur = d.get("next_cursor") if isinstance(d, dict) and d.get("has_more") else None
        if not curseur:
            return out, ""
    # create_group rend le groupe existant s'il porte deja ce nom : une liste
    # incomplete ne fabrique pas de doublon, elle est seulement dite
    print(f"[bases_us] list_groups : plus de {PAGES_GROUPES} pages, liste lue en partie", flush=True)
    return out, ""


def assurer_groupe(force: bool = False) -> Tuple[str, str]:
    """(id du groupe TEMPLATES, erreur). Le cache d'abord, sans appel ;
    sinon list_groups, puis create_group s'il manque (une fois pour toutes).
    Jamais d'exception."""
    if not force:
        g = groupe_connu()
        if g:
            return g, ""
    refus = _refus_quota() or _refus_droits("create_group")
    if refus:
        # create_group refuse (droits) : list_groups + create_group repayes a
        # chaque entretien et chaque creation pour le meme refus
        return "", refus
    eq = equipe()
    with _VERROU_GROUPE:
        if not force:
            g = groupe_connu()
            if g:
                return g, ""
        groupes, err = _lister_groupes(eq)
        if groupes is None:
            # on ne sait pas ce qui existe : rien n'est cree a l'aveugle
            return "", f"groupes de {NOM_EQUIPE} illisibles ({err})"
        nommes = [g for g in groupes if g.get("id")
                  and str(g.get("name") or "").strip().lower() == NOM_GROUPE.lower()]
        if len(nommes) > 1:
            print(f"[bases_us] {len(nommes)} groupes « {NOM_GROUPE} » dans {NOM_EQUIPE} : "
                  f"{nommes[0].get('id')} retenu", flush=True)
        contenu = ""
        if nommes:
            gid, cree = _avec_grp(nommes[0]["id"]), False
            if nommes[0].get("link_count"):
                # un « TEMPLATES » fait a la main avant nous : ce qu'il tient
                # n'est jamais sorti sans preuve (ranger_templates), c'est dit
                contenu = f" ({nommes[0].get('link_count')} lien(s) déjà dedans)"
        else:
            r = _appel("create_group", {"name": NOM_GROUPE, "team_id": eq})
            if not r.get("ok"):
                err = str(r.get("error") or "")[:150]
                _noter_droits("create_group", False, err)
                return "", f"groupe {NOM_GROUPE} non créé ({err})"
            _noter_droits("create_group", True)
            d = _donnees(r)
            g = d.get("group") if isinstance(d, dict) and isinstance(d.get("group"), dict) else d
            gid, cree = _avec_grp(g.get("id") if isinstance(g, dict) else ""), True
            if not gid:
                return "", f"groupe {NOM_GROUPE} : réponse de create_group sans id"
        _retenir_groupe(gid)
        print(f"[bases_us] groupe {NOM_GROUPE} {'créé' if cree else 'trouvé'} dans {NOM_EQUIPE} : {gid}"
              + contenu, flush=True)
        return gid, ""


def _par_lots(outil: str, gid: str, ids: List[str], etiquette: Optional[str] = "") -> Tuple[List[str], str]:
    """(ids traites, erreur) : l'outil de groupe sur `ids`, 100 par appel.
    Un refus de droits retenu : aucun appel."""
    faits: List[str] = []
    refus = _refus_droits(outil)
    if refus:
        return faits, refus
    for i in range(0, len(ids), LOT_GROUPE):
        lot = ids[i:i + LOT_GROUPE]
        r = _appel(outil, {"group_id": _avec_grp(gid), "link_ids": lot, "team_id": equipe()}, etiquette)
        if not r.get("ok"):
            err = str(r.get("error") or f"{outil} refusé")[:200]
            _noter_droits(outil, False, err)
            return faits, err
        _noter_droits(outil, True)
        d = _donnees(r)
        rates = d.get("failed") if isinstance(d, dict) else None
        if rates:
            # un id refuse n'echoue pas l'appel : il part dans « failed »
            mauvais = {str(x.get("id") if isinstance(x, dict) else x) for x in rates}
            faits += [x for x in lot if x not in mauvais]
            return faits, f"{len(mauvais)} lien(s) refusé(s) par {outil} : {str(rates)[:150]}"
        faits += lot
    return faits, ""


def ranger(link_ids: Iterable[Any], gid: str = "", vider: bool = True) -> Dict[str, Any]:
    """Range ces liens dans le groupe TEMPLATES (assign_links_to_group,
    idempotent). Un groupe supprime a la main est retrouve ou recree, une
    fois. `vider` : vider le cache de la liste apres (creer_base le vide
    lui-meme, une fois, a la fin). Rend {ok, ranges, erreur, groupe}."""
    ids = list(dict.fromkeys(str(x) for x in link_ids or () if x))
    out: Dict[str, Any] = {"ok": True, "ranges": [], "erreur": "", "groupe": gid}
    if not ids:
        return out
    if not gid:
        gid, err = assurer_groupe()
        if not gid:
            out.update(ok=False, erreur=err)
            return out
    for essai in range(2):
        faits, err = _par_lots("assign_links_to_group", gid, ids)
        out["ranges"] += faits
        if err and essai == 0 and "group_not_found" in err:
            _oublier_groupe(err)
            gid, err2 = assurer_groupe(force=True)
            if not gid:
                out.update(ok=False, erreur=err2)
                return out
            ids = [x for x in ids if x not in faits]
            continue
        if err:
            out.update(ok=False, erreur=err)
        break
    out["groupe"] = gid
    if out["ranges"] and vider:
        _vider_cache()          # la liste de l'equipe porte les group_id
    return out


def _ranger_page(lien: Dict[str, Any], lid: str, gid: str, gerr: str = "") -> Dict[str, Any]:
    """La page neuve dans le groupe TEMPLATES : rien a faire si la reponse
    du POST l'y dit deja (group_id accepte), sinon un assign. {ok, appel,
    erreur} ; un echec est dit au journal, l'entretien la rangera. `gerr` :
    le groupe vient d'etre introuvable (quota, liste illisible) -- pas de
    second essai dans la meme seconde. `groupe` : l'id ou la page a ete
    rangee (un groupe supprime a la main en change)."""
    if gid and meme_groupe((lien or {}).get("group_id"), gid):
        return {"ok": True, "appel": False, "erreur": "", "groupe": gid}
    if not gid and gerr:
        return {"ok": False, "appel": False, "erreur": gerr, "groupe": ""}
    r = ranger([lid], gid, vider=False)
    if not r["ok"]:
        print(f"[bases_us] {lid} hors du groupe {NOM_GROUPE} ({r['erreur']}) : "
              "l'entretien la rangera", flush=True)
    return {"ok": bool(r["ok"]), "appel": True, "erreur": r["erreur"], "groupe": r.get("groupe") or ""}


def sortir(link_ids: Iterable[Any], gid: str, etiquette: Optional[str] = "") -> Dict[str, Any]:
    """Sort ces liens du groupe (remove_links_from_group : ils restent
    dans l'equipe, sans groupe). Rend {ok, sortis, erreur}. `etiquette`
    None : celle de l'appelant (liens_identite_us)."""
    ids = list(dict.fromkeys(str(x) for x in link_ids or () if x))
    if not ids or not gid:
        return {"ok": True, "sortis": [], "erreur": ""}
    faits, err = _par_lots("remove_links_from_group", gid, ids, etiquette)
    if faits:
        _vider_cache()
    return {"ok": not err, "sortis": faits, "erreur": err}


_GROUPE_ABSENT_DIT = {"fait": False}


def _copies_va() -> Set[str]:
    """Les ids des copies de VA que liens_identite_us a faites (son
    registre) : les SEULS liens de VA que l'entretien sort du groupe -- ceux
    qui l'ont herite de leur base (duplicate_link). Registre illisible :
    aucun, rien n'est sorti sur un doute."""
    m = _liu()
    f = getattr(m, "registre", None) if m else None
    if not callable(f):
        return set()
    try:
        liens = (f() or {}).get("liens") or {}
    except Exception as e:                                   # noqa: BLE001
        _dire_une_fois("copies", f"[bases_us] registre des copies de VA illisible ({type(e).__name__}: {e}) : "
                                 "aucune copie sortie du groupe")
        return set()
    return {str(e.get("link_id")) for e in liens.values() if isinstance(e, dict) and e.get("link_id")}


def est_rejet(nom) -> bool:
    """« REJET TEMPLATE x 06-10 14h05 » : une page creee par le bot puis
    rejetee (_rejeter). Elle n'est plus une base."""
    n = str(nom or "").strip()
    return n.upper().startswith(PREFIXE_REJET) and bool(identite_de_base(n[len(PREFIXE_REJET):]))


def ranger_templates(liens: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """L'entretien du groupe : toute page de base de l'equipe dedans. N'en
    sort QUE ce qui est prouve hors de propos : une copie de VA connue (le
    registre de liens_identite_us) ou une page rejetee (« REJET … »). Tout
    le reste deja dedans -- une page « TEMPLATE » sans identite que le podium
    traite en gabarit, un lien range a la main dans un « TEMPLATES » adopte
    -- y reste, dit au journal : deux regles pour decider « est un
    gabarit » finissaient par sortir ce que le proprietaire y avait mis, a
    chaque redemarrage. Aucun appel si tout est en place ; sinon un assign
    et/ou un remove (par 100). Jamais d'exception.

    Rend {ok, groupe, ranges, sortis, intrus_gardes, erreur}."""
    out: Dict[str, Any] = {"ok": True, "groupe": "", "ranges": [], "sortis": [], "intrus_gardes": [],
                           "erreur": ""}
    try:
        if liens is None:
            liens, err = liens_equipe()
            if err:
                out.update(ok=False, erreur=err)
                return out
        liens = [l for l in liens or [] if isinstance(l, dict) and l.get("id")]
        bases_ = [l for l in liens if identite_de_base(l.get("display_name"))]
        gid = groupe_connu()
        if not gid:
            if not bases_:
                return out              # rien a ranger : pas d'appel pour un groupe vide
            gid, err = assurer_groupe()
            if not gid:
                out.update(ok=False, erreur=err)
                return out
        out["groupe"] = gid
        if liens and not any("group_id" in l for l in liens) and not _GROUPE_ABSENT_DIT["fait"]:
            _GROUPE_ABSENT_DIT["fait"] = True
            print("[bases_us] la liste de l'équipe ne dit pas les groupes (group_id absent) : "
                  "les pages de base sont re-rangées à chaque passage", flush=True)
        hors = [str(l["id"]) for l in bases_ if not meme_groupe(l.get("group_id"), gid)]
        dedans = [l for l in liens if meme_groupe(l.get("group_id"), gid)
                  and not identite_de_base(l.get("display_name"))]
        copies = _copies_va() if dedans else set()
        intrus = [l for l in dedans if str(l["id"]) in copies or est_rejet(l.get("display_name"))]
        gardes = [l for l in dedans if l not in intrus]

        def nom_de(l):
            return str(l.get("display_name") or l.get("shortcode") or l.get("id"))
        if gardes:
            out["intrus_gardes"] = [nom_de(l) for l in gardes]
            _dire_une_fois("gardes:" + ",".join(sorted(str(l["id"]) for l in gardes)),
                           f"[bases_us] groupe {NOM_GROUPE} : {len(gardes)} lien(s) qui ne sont pas des pages "
                           f"de base laissé(s) en place, ni copie de VA connue ni page rejetée : "
                           f"{', '.join(out['intrus_gardes'][:8])}{'…' if len(gardes) > 8 else ''}")
        refus = _refus_quota() if (hors or intrus) else ""
        if refus:
            # la liste venait du cache : les ecritures, elles, seraient refusees
            out.update(ok=False, erreur=refus)
            return out
        if hors:
            r = ranger(hors, gid)
            out["ranges"] = r["ranges"]
            if not r["ok"]:
                out.update(ok=False, erreur=r["erreur"])
            gid = r.get("groupe") or gid
        if intrus:
            noms = [nom_de(l) for l in intrus]
            if len(intrus) > INTRUS_MAX:
                out["intrus_gardes"] += noms
                print(f"[bases_us] groupe {NOM_GROUPE} : {len(intrus)} copies de VA ou pages rejetées "
                      f"({', '.join(noms[:8])}…) — trop pour des copies égarées, rien n'est "
                      "sorti : à vérifier dans GetMySocial", flush=True)
            else:
                r = sortir([l["id"] for l in intrus], gid)
                out["sortis"] = r["sortis"]
                if not r["ok"]:
                    out.update(ok=False, erreur=(out["erreur"] + " ; " if out["erreur"] else "") + r["erreur"])
        if out["ranges"] or out["sortis"] or out["erreur"]:
            print(f"[bases_us] groupe {NOM_GROUPE} : {len(out['ranges'])} page(s) rangée(s), "
                  f"{len(out['sortis'])} lien(s) sorti(s)"
                  + (f" ; {out['erreur']}" if out["erreur"] else ""), flush=True)
    except Exception as e:                                   # noqa: BLE001
        out.update(ok=False, erreur=f"{type(e).__name__}: {e}")
    return out


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
    with gms.api_tag(_etiquette()):
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
                    onlyfans: Optional[str] = None, groupe: str = "") -> Dict[str, str]:
    """Les champs texte du POST multipart : ceux du modele, encodes comme dans
    l'essai reussi (dict/list/bool en JSON, le reste en texte), plus l'adresse,
    le nom, le type et l'equipe (SANS « tm_ », comme le PATCH v3). `onlyfans` :
    l'adresse que visent les boutons OnlyFans (la forme de la requete ne
    change pas, seule la valeur). `groupe` : le seul champ AJOUTE a l'essai
    (group_id, « interprete dans le contexte de team_id » selon la doc de
    create_link) ; refuse une fois, il n'est plus envoye (post_avec_groupe)."""
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
    if groupe:
        champs["group_id"] = _avec_grp(groupe)
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
            prises: Iterable[str] = (), onlyfans: Optional[str] = None,
            groupe: str = "", trace: Optional[Dict[str, Any]] = None):
    """(lien, shortcode, erreur, adresses refusees en 409). Saute sans appel
    les adresses deja connues ; change d'adresse tant qu'elle est prise.

    `groupe` : group_id ajoute au POST. Un refus qui peut venir de lui
    (refus_du_groupe) fait refaire la MEME adresse sans lui, une fois ;
    `trace` recoit {groupe_envoye, groupe_refuse}."""
    trace = trace if trace is not None else {}
    trace.setdefault("groupe_envoye", False)
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
        champs = champs_creation(modele, sc, display_name, equipe, nom_affiche, onlyfans, groupe)
        trace["groupe_envoye"] = bool(groupe)
        fichiers = {"profilePicture": ("pp.jpg", pp, "image/jpeg"),
                    "backgroundImage": ("fond.jpg", fond, "image/jpeg")}
        postes += 1
        with gms.api_tag(_etiquette()):
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
        if groupe and refus_du_groupe(r.status_code, code, msg):
            # le group_id est le seul champ ajoute a la requete prouvee : on
            # la refait telle quelle, meme adresse, avant de conclure
            print(f"[bases_us] {sc} : HTTP {r.status_code} {code} avec group_id — refait sans lui",
                  flush=True)
            trace["groupe_refuse"] = (r.status_code, code, msg)
            groupe = ""
            rang -= 1
            postes -= 1
            continue
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
        with gms.api_tag(_etiquette()):
            res = gms.disable_link(link_id)
        return res if isinstance(res, dict) else {"ok": False, "error": "réponse vide"}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _renommer(link_id: str, nom: str, team) -> Dict[str, Any]:
    """Changer le nom d'une page (update_link exige display_name pour une
    page). gms.update_link quand il existe, sinon l'outil MCP directement.
    Le nom SEUL : c'est l'appel deja eprouve. Y joindre group_id "" (jamais
    essaye en vrai) faisait dependre le renommage d'un rejet de ce champ."""
    champs: Dict[str, Any] = {"display_name": nom}
    try:
        with gms.api_tag(_etiquette()):
            maj = getattr(gms, "update_link", None)
            if callable(maj):
                res = maj(link_id, champs, team_id=team or None)
            else:
                args = {"link_id": link_id, **champs}
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


def _rejeter(lien, lid, sc, pb, display_name, eq, k, nom, par, groupe_envoye: bool = False,
             gid: str = "") -> Tuple[str, bool]:
    """Une page creee mais non conforme : coupee ET renommee. Coupee seule,
    elle gardait « TEMPLATE x » et le module VA, qui prend une page inactive
    quand c'est la seule, la copiait pour chaque VA (sans fond, ou avec la
    mauvaise photo). Creee DANS le groupe TEMPLATES, elle en sort APRES le
    renommage, par son propre appel (rare : un appel de plus ne coute rien) :
    le groupe ne garde que des bases. Rend (phrase d'erreur, manuel) --
    manuel : coupure ou renommage rate, il reste a faire dans GetMySocial."""
    sortie = {"ok": True}
    if lid.startswith("lnk_"):
        coupe = _desactiver(lid)
        nouveau = f"{PREFIXE_REJET}{display_name} {time.strftime('%d-%m %Hh%M')}"
        renomme = _renommer(lid, nouveau, lien.get("team_id") or eq)
        # la reponse du POST la dit dans le groupe -- ou ne dit rien du groupe
        # alors qu'on l'y a demandee
        if gid and (meme_groupe(lien.get("group_id"), gid) or (groupe_envoye and "group_id" not in lien)):
            sortie = sortir([lid], gid)
            if not sortie["ok"]:
                print(f"[bases_us] {lid} rejetée reste dans {NOM_GROUPE} ({sortie['erreur']}) : "
                      "l'entretien la sortira", flush=True)
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
    manuel = lid.startswith("lnk_") and not (coupe.get("ok") and renomme.get("ok"))
    return phrase + f" ({lid or sc})", manuel


def creer_base(identite, pp_bytes: bytes, fond_bytes: bytes, nom_affiche: Optional[str] = None,
               par: str = "", identites: Optional[List[str]] = None) -> Dict[str, Any]:
    """Cree (ou remplace) la base « TEMPLATE <identite> ».

    Rend {ok, url, link_id, shortcode, remplace, coupees, erreur,
    avertissement, groupe, nom_affiche, manuel}. coupees = les anciennes
    pages « TEMPLATE <identite> » desactivees (remplace = la premiere). ok est
    FAUX si l'une d'elles n'a pas pu etre coupee : la nouvelle existe (url)
    mais le module VA, qui prend la plus ancienne active, ne s'en servirait
    pas. groupe = {ok, appel, erreur, groupe} du rangement dans TEMPLATES : il
    ne decide jamais de ok. nom_affiche : celui de la page creee. manuel :
    il reste quelque chose a faire a la main dans GetMySocial (une page a
    couper ou a renommer) -- a garder dans le salon, pas en ephemere.

    `nom_affiche` absent : celui de la base REMPLACEE (la page que les VA
    copient, meme faite a la main), sinon celui du modele. Refaire les seules
    photos donnait sinon « Emy ♡ » (le modele) a l'identite, sans un mot.
    Si `identites` est fourni, l'identite doit en faire partie."""
    out: Dict[str, Any] = {"ok": False, "url": "", "link_id": "", "shortcode": "",
                           "remplace": None, "coupees": [], "erreur": "", "avertissement": "",
                           "groupe": None, "nom_affiche": "", "manuel": False}
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
        if not nom_affiche:
            nom_affiche = nom_affiche_de(liens, nom) or None
            if nom_affiche:
                print(f"[bases_us] {display_name} : nom affiché repris de la base actuelle "
                      f"(« {nom_affiche} »)", flush=True)
        out["nom_affiche"] = nom_affiche or str(modele.get("name_user") or "")
        # le groupe TEMPLATES : connu une fois pour toutes (aucun appel), cree
        # au premier besoin. Sans lui, la page se cree quand meme -- hors du
        # groupe, que l'entretien rattrapera
        gid, gerr = assurer_groupe()
        if gerr:
            print(f"[bases_us] {display_name} : groupe {NOM_GROUPE} indisponible ({gerr}) : "
                  "page créée hors groupe", flush=True)
        trace: Dict[str, Any] = {}
        debut = time.time()
        lien, sc, err, refusees = _poster(modele, nom, display_name, eq, nom_affiche, pp, fond,
                                          prises, url_onlyfans(),
                                          groupe=gid if gid and post_avec_groupe() else "",
                                          trace=trace)
        douteux = None
        if trace.get("groupe_refuse"):
            st, code_g, msg_g = trace["groupe_refuse"]
            if "group_not_found" in f"{code_g} {msg_g}":
                # deux causes : le groupe supprime a la main, ou le POST qui ne
                # le resout pas (contexte de l'equipe). L'assign qui suit, avec
                # le MEME id, tranche : groupe introuvable -> ranger() l'oublie
                # et le retrouve ou le recree ; groupe trouve -> c'etait le
                # champ du POST. Oublier d'emblee repayait POST rate + POST +
                # list_groups + assign a chaque page, groupe intact.
                douteux = (st, code_g, msg_g)
            elif not err:
                # sans group_id la meme requete a reussi : c'etait lui
                _noter_post_refuse(st, code_g, msg_g)
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
            out["erreur"], out["manuel"] = _rejeter(lien, lid, sc, pb, display_name, eq, k, nom, par,
                                                    groupe_envoye=bool(trace.get("groupe_envoye")),
                                                    gid=gid)
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
        # Le rangement apres ce qui compte (la page, les anciennes coupees) :
        # un groupe rate ne coute jamais une base. Aucun appel si la reponse
        # du POST la dit deja dans le groupe.
        out["groupe"] = _ranger_page(lien, lid, gid, gerr)
        if douteux and out["groupe"]["ok"] and meme_groupe(out["groupe"].get("groupe"), gid):
            # rangee dans le MEME groupe : il existe, c'est le POST qui refuse
            _noter_post_refuse(*douteux)
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
            out["manuel"] = True
            out["erreur"] = (f"{url} créée, mais {noms} pas désactivée ({raison}) : la nouvelle base "
                             f"ne sera PAS utilisée pour les VA tant que {noms} est active — "
                             "la couper dans GetMySocial")
        print(f"[bases_us] {display_name} : {url} ({lid})"
              + (f", coupe {', '.join(out['coupees'])}" if out["coupees"] else "")
              + (f", PAS coupées : {', '.join(str(l.get('id')) for l, _ in ratees)}" if ratees else ""),
              flush=True)
        return out
