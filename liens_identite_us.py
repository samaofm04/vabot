# -*- coding: utf-8 -*-
"""Les liens GetMySocial PAR IDENTITE des VA du marche US (serveur Youl4b).

POURQUOI (proprietaire, 06/10/2026)
    Chaque VA US a un LIEN GLOBAL GetMySocial, celui que le proprietaire lui
    donne, qui vise SON lien de suivi OnlyFans de Jessye
    (onlyfans.com/jessyewdiference/c<N>, suivi par Infloww). Les meilleurs VA
    postent avec plusieurs identites -- « c'est les meilleurs VA qui ont
    plusieurs identites, mais pour mieux convertir faut ca ». Chaque VA cree
    donc LUI-MEME, sans validation, une PAGE par identite : la tete de
    l'identite et un bouton OF qui vise LE MEME c<N> que son global. Ses ventes
    restent a lui ; rien a creer chez Infloww ni chez MyPuls.

LES PAGES DE BASE
    Une par identite, dans l'espace « JESSY LE RETOUR », nommee « TEMPLATE
    <identite> » (« TEMPLATE ibenhaastrup »). Le proprietaire ne les fait PAS
    a la main : « avoir une base et juste changer les PP et la photo c'est
    tout ». Il poste le nom et 2 photos dans le salon admin « bases-identites »
    (cogs/bases_identite.py) et bases_identite_us.creer_base cree la page au
    style de lilskysmk2 (POST multipart /v3/links, fichiers profilePicture et
    backgroundImage). Ici, on ne fait que la DUPLIQUER : duplicate_link
    recopie photo et fond cote serveur. Une page faite a la main sous ce nom
    marche aussi. « TEMPLATE » est deja le mot des gabarits pour
    clics_personnes.est_gabarit : la page de base sort d'elle-meme du report
    des clics.

MISE EN SERVICE PAR ETAPES (dossier_ouvert)
    Le salon -generateur-de-lien n'apparait d'abord que dans les dossiers
    d'essai (DOSSIERS_ESSAI) ; data/liens_identite_us_config.json
    {"tous": true} l'ouvre a tous.

LE NOM D'UN LIEN D'IDENTITE (nom_lien)
    « (<personne du global>) <identite> », plus « SPAM » si le global l'est.
    podium_discord.personne doit y lire EXACTEMENT la personne du global :
    c'est par elle que le podium, la page Infloww et la paie rattachent un lien
    a quelqu'un. Un nom qui donnerait une autre personne creerait un VA
    fantome, a qui iraient ses clics.

LA PAIE
    Un lien d'identite n'est PAS une ligne payee de la page Infloww (« une
    ligne = un lien GMS ... chaque ligne c'est une paye ») : il est rattache a
    la ligne de son global (rattachements()) ; ses clics rendent cette ligne
    active, sans fixe de plus.

LE GLOBAL CHANGE
    Un admin corrige le global d'un VA, ou le global est rebranche dans
    GetMySocial : ses pages visent encore l'ancien c<N>, donc les ventes d'un
    autre. La coche ✅ tombe aussitot (_a_jour_pour), rattachements() suit le
    global du moment, et les pages deja donnees sont a rebrancher
    (a_rebrancher) -- le cog le fait tout de suite, et l'entretien rattrape
    le reste. Attendre le clic du VA, c'etait attendre pour rien : son
    message garde la meme adresse, rien ne l'invite a rechoisir. Le global
    d'un VA PARTI se reprend (definir_global(partis=...)) ; ses pages restent
    sur ce meme lien, donc chez son heritier.

RIEN N'EST SUPPRIME
    delete_links est definitif, sans corbeille. Une copie dont les boutons
    n'ont pas pu etre branches reste au registre « a_reparer » et se repare
    SUR PLACE au clic suivant : meme adresse. Tant qu'elle n'est pas
    branchee, son adresse n'est PAS donnee au VA -- ses boutons viseraient
    encore le c<N> de la page de base, donc les ventes de quelqu'un d'autre.
"""
from __future__ import annotations

import copy
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import clics_personnes as cp
import podium_discord as pd
import safe_json

GUILD_ID = "1535758943324999711"                  # Youl4b (US)
EQUIPE = "tm_6a0e4739bfa0c238f20a8bf5"            # JESSY LE RETOUR
NOM_EQUIPE = "JESSY LE RETOUR"
REGISTRE = Path(__file__).resolve().parent / "data" / "liens_identite_us.json"
#: L'etiquette des appels GetMySocial (gms.api_tag). Ni « fond » (un VA
#: attend derriere son clic) ni « paie » (la reserve de la paie n'est pas a
#: nous) : « normal ».
ETIQUETTE = "liens-identite"
DOMAINE = "https://getmysocial.com"
#: GetMySocial coupe un display_name trop long (gms.duplicate_link : [:60]).
#: Coupe apres coup, un nom perdrait son « SPAM » final -- donc sa personne.
NOM_MAX = 60
#: Appels duplicate_link au plus par creation. Les adresses deja vues dans
#: l'equipe sont sautees SANS appel : seules celles prises ailleurs sur la
#: plateforme coutent un essai (le quota du jour est commun aux quatre cles).
ESSAIS_SHORTCODE = 12

#: MISE EN SERVICE PAR ETAPES. Le salon -generateur-de-lien n'est cree que
#: dans ces dossiers tant que data/liens_identite_us_config.json ne dit pas
#: {"tous": true} : sans ca, le premier demarrage l'aurait pose d'un coup
#: dans les ~35 dossiers, avant que le proprietaire ait pu l'essayer
#: (06/10 : « je fais comment pour test ? »). Le fichier peut aussi donner
#: sa propre liste : {"dossiers": ["eud0616_94567", ...]}.
CONFIG = REGISTRE.with_name("liens_identite_us_config.json")
DOSSIERS_ESSAI = ("eud0616_94567",)


def dossier_ouvert(base) -> bool:
    """Le salon -generateur-de-lien a-t-il sa place dans le dossier `base`
    (« eud0616_94567 ») ? La SEULE regle : creation d'un dossier, rattrapage
    des dossiers existants et entretien du spoofer passent tous par elle --
    deux listes auraient ouvert le salon d'un cote et pas de l'autre."""
    b = str(base or "").strip().lower()
    if not b:
        return False
    try:
        cfg = safe_json.load(CONFIG, default={}) if CONFIG.exists() else {}
    except Exception as e:                                   # noqa: BLE001
        # config illisible : on reste sur l'etape d'essai, et on le dit
        print(f"[liens-identite] {CONFIG.name} illisible ({type(e).__name__}: {e}) : "
              f"salon ouvert aux seuls dossiers d'essai", flush=True)
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get("tous") is True:
        return True
    dossiers = cfg.get("dossiers")
    if not isinstance(dossiers, (list, tuple)):
        dossiers = DOSSIERS_ESSAI
    return b in {str(d).strip().lower() for d in dossiers}


_VERROU_REGISTRE = threading.RLock()
_VERROUS: Dict[str, threading.Lock] = {}
_VERROUS_GARDE = threading.Lock()
#: La derniere liste de l'equipe lue avec succes. gms.list_links_team refuse
#: meme son cache pendant une pause de quota : sans ce repli, le compteur des
#: liens actifs tomberait a zero pour sept heures.
_DERNIERE: Dict[str, Any] = {"t": 0.0, "liens": []}
_DOUBLONS_DITS: set = set()
#: Les relectures forcees de la liste (hors du cache de 15 min de gms) faites
#: pour un MANQUE (global ou page de base absents) : une par motif et par
#: quart d'heure. Sans ca, un global retire de l'equipe coutait un appel
#: GetMySocial a chaque clic du VA, indefiniment.
RELECTURE_S = 15 * 60
_RELECTURES: Dict[str, float] = {}


def _gms():
    import gms
    return gms


def _maintenant() -> int:
    return int(time.time())


def _uid(uid: Any) -> str:
    return str(uid if uid is not None else "").strip()


def _ident(identite: Any) -> str:
    """La cle d'une identite : minuscules, sans espaces. « TEMPLATE Iben
    Haastrup » et le dossier « ibenhaastrup » doivent se retrouver."""
    return re.sub(r"\s+", "", str(identite or "")).lower()


def _relecture_permise(motif: str) -> bool:
    t = time.time()
    with _VERROUS_GARDE:
        if 0 <= t - _RELECTURES.get(motif, -1e18) < RELECTURE_S:
            return False
        _RELECTURES[motif] = t
        return True


def _verrou(cle: str) -> threading.Lock:
    with _VERROUS_GARDE:
        v = _VERROUS.get(cle)
        if v is None:
            v = _VERROUS[cle] = threading.Lock()
        return v


# ─── le registre ─────────────────────────────────────────────────────────
def _lire_registre() -> Optional[Dict[str, Any]]:
    """Le registre, ou None s'il existe mais ne se lit pas (ni lui ni .prev) :
    le reecrire a partir de rien effacerait les globaux poses par les admins."""
    d = safe_json.load(REGISTRE, default=None)
    if d is None:
        try:
            if REGISTRE.exists() and REGISTRE.stat().st_size > 1:
                print(f"[liens_identite_us] registre {REGISTRE.name} illisible : "
                      "aucune ecriture tant qu'il ne l'est pas", flush=True)
                return None
        except OSError:
            return None
        d = {}
    if not isinstance(d, dict):
        print(f"[liens_identite_us] registre {REGISTRE.name} n'est pas un objet : ignore", flush=True)
        return None
    for k in ("globaux", "liens"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def registre() -> Dict[str, Any]:
    """Le registre en lecture (vide s'il est illisible -- et c'est dit au journal)."""
    return _lire_registre() or {"globaux": {}, "liens": {}}


def _ecrire(modif: Callable[[Dict[str, Any]], Tuple[bool, Any]]) -> Tuple[bool, Any, str]:
    """Lit, modifie, ecrit -- sous verrou, sur une lecture FRAICHE.

    `modif(d)` rend (a_ecrire, resultat). Rend (ecrit, resultat, erreur)."""
    with _VERROU_REGISTRE:
        d = _lire_registre()
        if d is None:
            return False, None, f"registre data/{REGISTRE.name} illisible : rien n'est écrit"
        a_ecrire, res = modif(d)
        if not a_ecrire:
            return False, res, ""
        REGISTRE.parent.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(REGISTRE, d, indent=1):
            return False, res, f"registre data/{REGISTRE.name} non écrit"
        return True, res, ""


# ─── la liste de l'equipe ────────────────────────────────────────────────
def liens_equipe(force: bool = False) -> Tuple[List[Dict[str, Any]], str]:
    """(liens de JESSY LE RETOUR, raison). Ne leve jamais.

    raison vide : liste fraiche (ou du cache de 15 min de gms). raison non
    vide : GetMySocial indisponible (pause, quota, budget, reseau) ; la liste
    est alors la derniere lue avec succes, peut-etre vide -- a l'appelant de
    le dire, pas de la prendre pour l'etat du jour."""
    try:
        gms = _gms()
        with gms.api_tag(ETIQUETTE):
            r = gms.list_links_team(EQUIPE, force_refresh=force)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not isinstance(r, dict):
        r = {"ok": False, "error": "réponse illisible"}
    if r.get("ok"):
        brut = r.get("links") or []
        liens = [l for l in brut if isinstance(l, dict) and l.get("id")]
        if len(brut) != len(liens):
            # compte et dit : un lien sans id ne se rattache a personne
            print(f"[liens_identite_us] {len(brut) - len(liens)} lien(s) sans identifiant "
                  f"dans {NOM_EQUIPE} : laissés de côté", flush=True)
        _DERNIERE.update(t=time.time(), liens=liens)
        return list(liens), ""
    raison = str(r.get("error") or "GetMySocial ne répond pas")
    return list(_DERNIERE["liens"]), f"GetMySocial indisponible : {raison}"


def _par_id(liens: Iterable[Dict[str, Any]], link_id: Any) -> Optional[Dict[str, Any]]:
    lid = str(link_id or "")
    if not lid:
        return None
    return next((l for l in liens if str(l.get("id") or "") == lid), None)


def _nom_de(l: Dict[str, Any]) -> str:
    """Le nom tel que le lit le podium (podium_discord.entites)."""
    return str(l.get("display_name") or l.get("title") or l.get("shortcode") or "")


def _meme_nom(a: Any, b: Any) -> bool:
    return cp.propre(a).lower() == cp.propre(b).lower()


def _actif(l: Optional[Dict[str, Any]]) -> bool:
    return bool(l) and str(l.get("status") or "").strip().lower() == "active"


def _nombre(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ─── les pages de base « TEMPLATE <identite> » ──────────────────────────
_MOT_BASE = re.compile(r"^\s*([A-Za-z]+)\s*[:\-–—_]*\s*(.*?)\s*$", re.S)


def identite_de_base(nom: Any) -> Optional[str]:
    """« TEMPLATE ibenhaastrup » -> « ibenhaastrup » (casse et espaces
    indifferents) ; None si ce n'est pas une page de base d'identite."""
    m = _MOT_BASE.match(str(nom or ""))
    if not m:
        return None
    mot, reste = m.group(1), m.group(2)
    # LA regle etroite du podium, de la page Infloww et de la paie
    # (clics_personnes.commence_par_gabarit) : « TEMPALTE », « TEAMPLTE »
    # passent (fautes deja vues dans les vrais noms) ; « Templeton » ou
    # « Temple » non -- un VA pourrait s'appeler ainsi.
    if not cp.commence_par_gabarit(mot):
        return None
    ident = _ident(reste.strip(" \t«»\"'()[]{}<>"))
    return ident or None


def est_base(nom: Any) -> bool:
    return identite_de_base(nom) is not None


def _bases_groupees(liens: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for l in liens:
        i = identite_de_base(l.get("display_name"))
        if i:
            out.setdefault(i, []).append(l)
    # la page (pas un lien direct), active, puis la plus ancienne : un choix
    # qui ne bascule pas d'un affichage a l'autre
    for ls in out.values():
        ls.sort(key=lambda l: (str(l.get("type") or "") == "directlink", not _actif(l),
                               _nombre(l.get("created")), str(l.get("id"))))
    return out


def bases(liens: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    """{identite: lien de sa page de base}. Deux pages pour une identite : la
    premiere est prise et le doublon est dit au journal (etat_bases le
    montre)."""
    if liens is None:
        liens, _ = liens_equipe()
    out = {}
    for i, ls in _bases_groupees(liens).items():
        out[i] = ls[0]
        signature = (i,) + tuple(str(l.get("id")) for l in ls)
        if len(ls) > 1 and signature not in _DOUBLONS_DITS:
            # dit une fois : bases() tourne a chaque affichage du menu
            _DOUBLONS_DITS.add(signature)
            print(f"[liens_identite_us] {len(ls)} pages de base pour « {i} » : "
                  f"{ls[0].get('shortcode')} retenue, "
                  f"{', '.join(str(l.get('shortcode')) for l in ls[1:])} ignorée(s)", flush=True)
    return out


def etat_bases(identites_us: Iterable[Any],
               liens: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Ce qui manque au proprietaire, pour le lui montrer plutot que de taire
    une identite absente du menu : {avec_base, sans_base, orphelines (pages
    « TEMPLATE x » dont x n'est pas une identite US -- faute de frappe ?),
    doublons {identite: [shortcodes]}, raison}."""
    raison = ""
    if liens is None:
        liens, raison = liens_equipe()
    groupes = _bases_groupees(liens)
    vues, avec, sans = set(), [], []
    for i in identites_us or []:
        k = _ident(i)
        if not k or k in vues:
            continue
        vues.add(k)
        (avec if k in groupes else sans).append(str(i))
    orphelines = [str(ls[0].get("display_name")) for k, ls in groupes.items() if k not in vues]
    doublons = {k: [str(l.get("shortcode")) for l in ls] for k, ls in groupes.items() if len(ls) > 1}
    return {"avec_base": avec, "sans_base": sans, "orphelines": sorted(orphelines),
            "doublons": doublons, "raison": raison}


# ─── le suivi OnlyFans ───────────────────────────────────────────────────
_OF = re.compile(r"^\s*(?:https?://)?(?:www\.)?onlyfans\.com/", re.I)
#: Les cles ou GetMySocial range une destination : l'adresse d'un bouton,
#: celle d'une regle pays, d'une redirection intelligente, d'une vignette de
#: carrousel. Un libelle qui contient « onlyfans.com » est du TEXTE : on n'y
#: touche pas.
_CLES_URL = ("url", "destination_url")
#: Les champs d'une page (hors boutons) qui peuvent porter une destination et
#: que update_link accepte. Une redirection de la page de base vers un autre
#: c<N> enverrait les fans de ce VA chez quelqu'un d'autre.
_CHAMPS_PAGE = ("smart_redirect", "geofilters", "ab_testing", "traffic_recovery",
                "social_media_links")


def _code_suivi(url: Any) -> Tuple[str, str]:
    """(« 117 », "") pour onlyfans.com/jessyewdiference/c117, sinon ("",
    pourquoi). LA regle de la page Infloww (infloww_liens.code_de_l_url) :
    deux regles finiraient par accepter d'un cote ce que l'autre refuse."""
    try:
        import infloww_liens
        return infloww_liens.code_de_l_url(url)
    except Exception as e:                                   # noqa: BLE001
        return "", f"vérification du suivi impossible ({type(e).__name__}: {e})"


def _urls_of(obj: Any) -> List[str]:
    """Toutes les adresses OnlyFans de destination dans obj (boutons, regles)."""
    out: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _CLES_URL and isinstance(v, str) and _OF.match(v):
                out.append(v)
            elif isinstance(v, (dict, list)):
                out += _urls_of(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _urls_of(v)
    return out


def _remplacer(obj: Any, tracking: str) -> Tuple[Any, int]:
    """Une COPIE de obj ou chaque destination OnlyFans qui ne vise pas deja le
    suivi `tracking` le vise ; rend (copie, nombre de changements). Tout le
    reste (images, effets, couleurs) est garde tel quel : update_link
    REMPLACE le tableau entier."""
    cible = _code_suivi(tracking)[0]
    n = [0]

    def walk(x):
        if isinstance(x, dict):
            y = {}
            for k, v in x.items():
                if k in _CLES_URL and isinstance(v, str) and _OF.match(v):
                    if not cible or _code_suivi(v)[0] != cible:
                        n[0] += 1
                        y[k] = tracking
                        continue
                    y[k] = v
                else:
                    y[k] = walk(v)
            return y
        if isinstance(x, list):
            return [walk(v) for v in x]
        return copy.deepcopy(x)

    return walk(obj), n[0]


def _verifier(lien: Dict[str, Any], tracking: str, nom: str) -> Tuple[bool, str]:
    """Le lien relu (ou rendu par update_link) vise-t-il bien le suivi du VA,
    et porte-t-il un nom qui donne SA personne ?"""
    cible = _code_suivi(tracking)[0]
    urls = _urls_of(lien.get("buttons") or [])
    if not urls:
        return False, "aucun bouton OnlyFans sur le lien après modification"
    autres: List[str] = []
    for champ in ("buttons",) + _CHAMPS_PAGE:
        autres += [u for u in _urls_of(lien.get(champ)) if _code_suivi(u)[0] != cible]
    if autres:
        return False, f"{len(autres)} destination(s) OnlyFans ne visent pas le suivi c{cible}"
    dn = lien.get("display_name")
    if dn is not None and pd.personne(str(dn)) != pd.personne(nom):
        return False, f"nom « {dn} » au lieu de « {nom} »"
    return True, ""


# ─── les noms ────────────────────────────────────────────────────────────
#: Les morceaux d'un nom d'identite que les regles des classements
#: interpreteraient : « spam » (podium_discord.personne : « SPAM » n'importe
#: ou), les fragments de « template » (clics_personnes.est_gabarit), « @ »
#: (le pseudo qui suit devient la personne), les parentheses (la personne).
#: « nanas__nyspam » est une vraie identite US : sous un global non SPAM, son
#: lien aurait ete compte comme le lien SPAM du VA.
_DESARMER = ("spam",) + tuple(cp.GABARITS)


def _identite_affichee(identite: Any) -> str:
    t = re.sub(r"[()\[\]{}@]", "", str(identite or "").strip())
    t = re.sub(r"\s+", "_", t)
    for morceau in _DESARMER:
        t = re.sub(re.escape(morceau), lambda m: m.group(0)[:2] + "-" + m.group(0)[2:],
                   t, flags=re.I)
    return t


def nom_lien(glob: Dict[str, Any], identite: Any) -> str:
    """Le nom GetMySocial du lien de cette identite pour ce global.

    « (<personne>) <identite> », plus « SPAM » si le global l'est : « ( Carter
    ) 1 » -> « (Carter) ibenhaastrup », « (Gerome) SPAM » -> « (Gerome)
    ibenhaastrup SPAM ».

    CONDITION : podium_discord.personne lit sur ce nom EXACTEMENT la personne
    (et le SPAM) du global -- podium, page Infloww, paie. Si possible aussi
    la meme personne pour clics_personnes (le report des clics), dont les
    regles different. Ecarts connus, impossibles a combler tant que les deux
    regles different :
      - « tsiry 1 », « eddy 2 »… (sans parentheses) : le podium garde le
        chiffre, le report le pele. Le lien sort en « tsiry 1 » au report, a
        cote de « tsiry ».
      - « LaBoule ( Phone ) » : le podium y lit « Phone », le report
        « LaBoule ». Le nom garde alors ce qui precede la parenthese
        (« LaBoule (Phone) ibenhaastrup ») : les deux regles retombent juste.
      - un global a « @pseudo » : le podium suit le pseudo ; le report, non.
    "" si aucun nom ne donne la personne du global au podium."""
    brut = str((glob or {}).get("nom") or "")
    if brut.strip():
        personne, spam = pd.personne(brut)
    else:
        personne, spam = str((glob or {}).get("personne") or ""), bool((glob or {}).get("spam"))
        brut = f"({personne}) SPAM" if spam else f"({personne})"
    if not personne.strip():
        return ""
    ident = _identite_affichee(identite)
    if not ident:
        return ""
    devants = [""]
    if "(" in brut and "@" not in brut:
        devant = brut[:brut.index("(")].strip()
        if devant:
            devants.append(devant)
    voulu = (personne, spam)
    pseudo_global = cp.pseudo(brut)
    pd_seul = ""
    for devant in devants:
        tete = (devant + " " if devant else "") + f"({personne}) "
        queue = " SPAM" if spam else ""
        place = NOM_MAX - len(tete) - len(queue)
        if place < 3:
            continue
        nom = tete + ident[:place] + queue
        if est_base(nom) or pd.personne(nom) != voulu:
            continue
        if cp.est_gabarit(nom) and not cp.est_gabarit(brut):
            continue
        if cp.pseudo(nom) == pseudo_global:
            return nom
        pd_seul = pd_seul or nom
    return pd_seul


def shortcode_pour(identite: Any, essai: int = 0) -> str:
    """L'adresse courte : l'identite et un mot doux (« ibenhaastrupcute »),
    comme les liens Twitter (liens_va.mots_doux) -- elle se lit sur le profil
    de l'identite. 3 a 24 caracteres [a-z0-9]. Au-dela des mots, un chiffre :
    « ibenhaastrupcute2 »."""
    try:
        from liens_va import MOTS_DOUX as mots
    except Exception:                                        # noqa: BLE001
        mots = ("cute", "lovee", "baby", "angel", "honey", "sweet", "bby", "doll")
    base = re.sub(r"[^a-z0-9]+", "", _ident(identite))[:12]
    if len(base) < 2:
        base = (base + "id")[:12]
    essai = max(0, int(essai or 0))
    tour = essai // len(mots)
    return f"{base}{mots[essai % len(mots)]}" + (str(tour + 1) if tour else "")


# ─── le lien global d'un VA ──────────────────────────────────────────────
_ADRESSE_GMS = re.compile(r"^(?:https?://)?(?:www\.)?getmysocial\.com/([A-Za-z0-9_-]+)", re.I)
_SHORTCODE = re.compile(r"^[A-Za-z0-9_-]{3,24}$")


def _chercher(liens: List[Dict[str, Any]], valeur: str) -> List[Dict[str, Any]]:
    v = str(valeur or "").strip()
    if not v:
        return []
    if v.startswith("lnk_"):
        return [l for l in liens if str(l.get("id")) == v]
    m = _ADRESSE_GMS.match(v)
    if m:
        sc = m.group(1).lower()
        return [l for l in liens if str(l.get("shortcode") or "").lower() == sc]
    if _SHORTCODE.match(v):
        par_sc = [l for l in liens if str(l.get("shortcode") or "").lower() == v.lower()]
        if par_sc:
            return par_sc
    return [l for l in liens if _meme_nom(l.get("display_name"), v)]


def _fiche_globale(l: Dict[str, Any], code: str, par: Any) -> Dict[str, Any]:
    nom = str(l.get("display_name") or "")
    personne, spam = pd.personne(nom)
    sc = str(l.get("shortcode") or "")
    return {"link_id": str(l.get("id")), "shortcode": sc, "url": str(l.get("url") or "").strip(),
            "public_url": f"{DOMAINE}/{sc}" if sc else "", "code": code,
            "nom": nom, "personne": personne, "spam": spam,
            "par": str(par or ""), "quand": _maintenant()}


def definir_global(uid: Any, valeur: Any, par: Any = None,
                   partis: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """Pose le lien global d'un VA (geste d'admin : le nom d'un lien ne dit
    pas le pseudo Discord, rien ne se devine). `valeur` : le shortcode,
    l'adresse getmysocial.com/<sc>, l'id lnk_… ou le nom exact du lien dans
    JESSY LE RETOUR. Rend {ok, erreur, global} (+ remplace, meme_personne,
    a_rebrancher, repris_de).

    `partis` : les VA qui ne sont plus membres du serveur (le cog le verifie
    aupres de Discord). Le global de l'un d'eux peut etre repris : « quand un
    VA part, le suivant herite du lien ». Sans ca, le lien d'un VA parti
    restait a lui pour toujours, et le suivant attendait devant un menu grise
    -- seule issue, editer le registre a la main sur le VPS."""
    u = _uid(uid)
    out: Dict[str, Any] = {"ok": False, "erreur": "", "global": None}
    if not u:
        out["erreur"] = "VA inconnu (aucun identifiant Discord)"
        return out
    v = str(valeur or "").strip()
    if not v:
        out["erreur"] = "Donne le shortcode, l'adresse getmysocial.com/… ou le nom exact du lien."
        return out
    partis_ = {_uid(x) for x in (partis or ()) if _uid(x) and _uid(x) != u}
    liens, raison = liens_equipe()
    if raison:
        out["erreur"] = raison
        return out
    trouves = _chercher(liens, v)
    if not trouves:
        # cree il y a moins d'un quart d'heure : pas encore dans le cache de gms
        liens, raison = liens_equipe(force=True)
        if raison:
            out["erreur"] = raison
            return out
        trouves = _chercher(liens, v)
    if not trouves:
        out["erreur"] = f"« {v} » introuvable dans {NOM_EQUIPE}"
        return out
    if len(trouves) > 1:
        out["erreur"] = (f"« {v} » désigne {len(trouves)} liens ("
                         + ", ".join(str(l.get("shortcode")) for l in trouves)
                         + ") : donne le shortcode")
        return out
    l = trouves[0]
    nom = str(l.get("display_name") or "")
    # la regle ETROITE (le nom commence par « TEMPLATE ») : en sous-chaine,
    # le global « (Teamplayer) 1 » d'un vrai VA etait refuse
    if est_base(nom) or cp.commence_par_gabarit(nom):
        out["erreur"] = f"« {nom} » est une page de base (TEMPLATE), pas le lien d'un VA"
        return out
    code, pourquoi = _code_suivi(l.get("url"))
    if not code:
        out["erreur"] = (f"« {nom} » : {pourquoi} — un lien global doit viser "
                         "onlyfans.com/jessyewdiference/c<N>")
        return out
    fiche = _fiche_globale(l, code, par)

    def modif(d):
        for k, e in d["liens"].items():
            if isinstance(e, dict) and str(e.get("link_id")) == fiche["link_id"]:
                return False, ("identite", k)
        repris = None
        for autre, g in list(d["globaux"].items()):
            if autre != u and isinstance(g, dict) and str(g.get("link_id")) == fiche["link_id"]:
                if autre not in partis_:
                    return False, ("pris", autre)
                # le VA parti perd son global ; ses pages d'identite restent
                # rattachees a ce meme lien (rattachements : un VA sans global
                # garde le global_link_id de ses entrees), donc au suivant
                d.setdefault("globaux_anciens", []).append(
                    {**g, "uid": autre, "libere": _maintenant(), "libere_pour": u,
                     "libere_par": str(par or "")})
                del d["globaux"][autre]
                repris = (autre, sum(1 for k in d["liens"] if k.startswith(autre + ":")))
        ancien = d["globaux"].get(u)
        change = isinstance(ancien, dict) and str(ancien.get("link_id")) != fiche["link_id"]
        marquees = []
        if change:
            d.setdefault("globaux_anciens", []).append({**ancien, "uid": u, "remplace": _maintenant(),
                                                        "remplace_par": str(par or "")})
            # Ses pages visent encore l'ancien suivi : la coche tombe tout de
            # suite (etat), et celles dont l'adresse a ete donnee sont a
            # rebrancher sans attendre un clic -- que rien ne pousserait le VA
            # a faire, puisque son message garde la meme adresse.
            for k, e in d["liens"].items():
                if k.startswith(u + ":") and isinstance(e, dict):
                    if _donne(e):
                        e["donne"] = True
                        marquees.append(str(e.get("identite") or k.split(":", 1)[1]))
                    e["etat"] = "a_reparer"
                    e["erreur"] = "lien global changé : à rebrancher"
        d["globaux"][u] = fiche
        meme = sorted(a for a, g in d["globaux"].items()
                      if a != u and isinstance(g, dict)
                      and str(g.get("personne")) == fiche["personne"])
        return True, ("ok", ancien if change else None, meme, marquees, repris)

    ecrit, res, err = _ecrire(modif)
    if res and res[0] == "identite":
        out["erreur"] = f"« {nom} » est un lien d'identité ({res[1]}), pas un lien global"
        return out
    if res and res[0] == "pris":
        out["erreur"] = f"« {nom} » est déjà le lien global d'un autre VA (Discord {res[1]})"
        out["autre_uid"] = res[1]
        return out
    if not ecrit:
        out["erreur"] = err or "registre non écrit"
        return out
    _, ancien, meme, _marquees, repris = res
    out["ok"] = True
    out["global"] = dict(fiche)
    if isinstance(ancien, dict):
        out["remplace"] = dict(ancien)
    # a l'appelant de les rebrancher (cog : aussitot ; sinon l'entretien, ou
    # le clic suivant du VA). Relu par LA regle (a_rebrancher) : reposer le
    # meme global rattrape aussi un rebranchement rate la fois d'avant.
    a_rebrancher_ = a_rebrancher(u)
    if a_rebrancher_:
        out["a_rebrancher"] = a_rebrancher_
    if repris:
        out["repris_de"], out["pages_du_parti"] = repris
    if meme:
        out["meme_personne"] = meme
    if not _actif(l):
        # accepte (un admin peut le rallumer), mais ses liens d'identite
        # visent un suivi dont le lien principal est coupe : a lui dire
        out["inactif"] = True
    print(f"[liens_identite_us] global de {u} : « {nom} » ({fiche['shortcode']}, c{code}) "
          f"par {par}" + (f", repris de {repris[0]} (parti)" if repris else "")
          + (f", {len(a_rebrancher_)} page(s) à rebrancher" if a_rebrancher_ else ""), flush=True)
    return out


def global_de(uid: Any) -> Optional[Dict[str, Any]]:
    g = registre()["globaux"].get(_uid(uid))
    return dict(g) if isinstance(g, dict) else None


def _donne(e: Dict[str, Any]) -> bool:
    """L'adresse de cette page a-t-elle ete donnee au VA (postee dans son
    salon) ? Une page jamais donnee attend le clic du VA, qui la postera ;
    une page donnee se rebranche seule, sans quoi son message garde une
    adresse dont le bouton vise un autre suivi."""
    return bool(e.get("donne")) or e.get("etat") == "ok"


def _a_jour_pour(e: Any, g: Any) -> bool:
    """Cette page est-elle branchee sur CE global : etat « ok », meme lien
    global, meme code de suivi, meme nom ? LA regle de la coche ✅, du
    « redonne sans verifier » et du rebranchement : un etat « ok » seul ne
    dit pas que le global n'a pas change depuis."""
    if not (isinstance(e, dict) and isinstance(g, dict)) or e.get("etat") != "ok":
        return False
    if str(e.get("global_link_id") or "") != str(g.get("link_id") or ""):
        return False
    code = str(g.get("code") or "") or _code_suivi(g.get("url"))[0]
    if code and _code_suivi(e.get("tracking"))[0] != code:
        return False
    ident = e.get("identite")
    if ident and e.get("nom") and nom_lien(g, ident) != e.get("nom"):
        return False
    return True


def a_rebrancher(uid: Any) -> List[str]:
    """Les identites de ce VA dont la page a ete DONNEE et ne vise plus son
    global du moment (global remplace, rebranche ou renomme dans
    GetMySocial). Chacune se repare par creer_pour_identite : meme adresse,
    deux appels environ."""
    u = _uid(uid)
    d = registre()
    g = d["globaux"].get(u)
    if not isinstance(g, dict):
        return []
    return [str(e.get("identite") or k.split(":", 1)[1])
            for k, e in sorted(d["liens"].items())
            if k.startswith(u + ":") and isinstance(e, dict) and _donne(e)
            and not _a_jour_pour(e, g)]


def global_present(uid: Any, liens: Optional[List[Dict[str, Any]]]) -> Optional[bool]:
    """Le global de ce VA est-il dans la liste de l'equipe ? None si on ne
    sait pas (pas de liste). Un global retire de JESSY LE RETOUR remet le
    panneau en attente : sinon chaque choix d'identite relisait GetMySocial
    pour rien."""
    g = global_de(uid)
    if not g:
        return False
    if liens is None:
        return None
    return _par_id(liens, g.get("link_id")) is not None


def actualiser(uid: Any, liens: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Le registre de ce VA suit la liste de l'equipe DEJA LUE (aucun appel) :
    global renomme, rebranche ou change d'adresse dans GetMySocial, adresse
    d'une page d'identite changee. Pour l'entretien du salon, qui repose alors
    les messages dont l'adresse a change et rebranche ce qui doit l'etre.

    Rend {global (la fiche a jour ou None), global_absent, adresses
    [identites dont l'adresse a change], a_rebrancher [identites]}."""
    u = _uid(uid)
    out: Dict[str, Any] = {"global": None, "global_absent": False, "adresses": [],
                           "a_rebrancher": []}
    d = registre()
    g = d["globaux"].get(u)
    if not isinstance(g, dict) or not g.get("link_id"):
        return out
    gl = _par_id(liens or [], g.get("link_id"))
    if gl is None:
        out["global_absent"] = True
    else:
        code = _code_suivi(gl.get("url"))[0]
        if code:
            g = _rafraichir_global(u, g, gl, code)
    out["global"] = dict(g)
    changes: Dict[str, Tuple[str, str]] = {}
    for k, e in d["liens"].items():
        if not (k.startswith(u + ":") and isinstance(e, dict)):
            continue
        present = _par_id(liens or [], e.get("link_id"))
        sc = str((present or {}).get("shortcode") or "")
        if sc and sc != str(e.get("shortcode") or ""):
            changes[k] = (sc, str(e.get("identite") or k.split(":", 1)[1]))
    if changes:
        def modif(dd):
            fait = []
            for k, (sc, ident) in changes.items():
                e = dd["liens"].get(k)
                if isinstance(e, dict):
                    e.update(shortcode=sc, public_url=f"{DOMAINE}/{sc}", vu_change=_maintenant())
                    if _donne(e):
                        fait.append(ident)
            return True, fait
        ecrit, fait, err = _ecrire(modif)
        if ecrit:
            out["adresses"] = list(fait or [])
            print(f"[liens_identite_us] {u} : adresse changée dans GetMySocial pour "
                  f"{', '.join(v[1] for v in changes.values())}", flush=True)
        else:
            print(f"[liens_identite_us] {u} : adresses changées non écrites ({err})", flush=True)
    out["a_rebrancher"] = a_rebrancher(u)
    return out


def _rafraichir_global(u: str, g: Dict[str, Any], gl: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Le global renomme ou rebranche dans GetMySocial : le registre suit. Le
    nom decide de la personne, l'adresse du suivi a brancher."""
    nom, url = str(gl.get("display_name") or ""), str(gl.get("url") or "").strip()
    sc = str(gl.get("shortcode") or g.get("shortcode") or "")
    if nom == g.get("nom") and url == g.get("url") and sc == g.get("shortcode"):
        return g
    personne, spam = pd.personne(nom)
    # l'adresse publique suit le shortcode : sans ca, le salon reposterait
    # l'ancienne adresse du global apres un changement fait dans GetMySocial
    neuf = {**g, "nom": nom, "url": url, "code": code, "personne": personne, "spam": spam,
            "shortcode": sc, "public_url": f"{DOMAINE}/{sc}" if sc else g.get("public_url", ""),
            "vu_change": _maintenant()}

    def modif(d):
        cur = d["globaux"].get(u)
        if not isinstance(cur, dict) or str(cur.get("link_id")) != str(g.get("link_id")):
            return False, None
        d["globaux"][u] = neuf
        return True, None

    _, _, err = _ecrire(modif)
    if err:
        print(f"[liens_identite_us] global de {u} relu mais non réécrit : {err}", flush=True)
    print(f"[liens_identite_us] global de {u} changé dans GetMySocial : « {g.get('nom')} » "
          f"-> « {nom} », {g.get('url')} -> {url}", flush=True)
    return neuf


# ─── brancher un lien d'identite ─────────────────────────────────────────
def _brancher(link_id: str, tracking: str, nom: str,
              base_boutons: Optional[List[Any]] = None,
              lire_base: Optional[Callable[[], Optional[List[Any]]]] = None,
              activer: bool = False) -> Tuple[bool, str, List[str]]:
    """Met la copie en etat : chaque destination OnlyFans sur le suivi du VA,
    le nom qui donne sa personne, active si demande. Idempotent : un lien deja
    juste ne coute qu'une lecture. Rend (ok, erreur, soucis)."""
    gms = _gms()
    soucis: List[str] = []
    r = gms.get_link(link_id, EQUIPE)
    if not r.get("ok"):
        return False, f"lien illisible ({r.get('error')})", soucis
    lien = r.get("link") or {}
    boutons = lien.get("buttons")
    if not (isinstance(boutons, list) and _urls_of(boutons)):
        # la copie relue sans ses boutons : ceux de la page de base, jamais
        # « rien » (une page sans bouton ne vend pas)
        bb = base_boutons if base_boutons is not None else (lire_base() if lire_base else None)
        if isinstance(bb, list) and _urls_of(bb):
            boutons = bb
            soucis.append("boutons de la copie illisibles : repris de la page de base")
        else:
            return False, "le lien n'a aucun bouton OnlyFans à brancher", soucis
    maj: Dict[str, Any] = {}
    neufs, n = _remplacer(boutons, tracking)
    if n or boutons is not lien.get("buttons"):
        maj["buttons"] = neufs
    for champ in _CHAMPS_PAGE:
        if lien.get(champ) and _urls_of(lien.get(champ)):
            val, k = _remplacer(lien[champ], tracking)
            if k:
                maj[champ] = val
    if str(lien.get("display_name") or "") != nom:
        maj["display_name"] = nom
    final = lien
    if maj:
        # une page exige son display_name a chaque modification (schema update_link)
        maj["display_name"] = nom
        r = gms.update_link(link_id, maj, team_id=EQUIPE)
        if not r.get("ok"):
            return False, f"boutons non branchés ({r.get('error')})", soucis
        final = r.get("link") or {}
        if not isinstance(final.get("buttons"), list):
            r = gms.get_link(link_id, EQUIPE)
            if not r.get("ok"):
                return False, f"vérification impossible ({r.get('error')})", soucis
            final = r.get("link") or {}
    ok, pourquoi = _verifier(final, tracking, nom)
    if not ok:
        return False, pourquoi, soucis
    if activer:
        statut = str(final.get("status") or lien.get("status") or "").strip().lower()
        if statut and statut != "active":
            # copie d'une page de base desactivee : la copie l'est aussi
            r = gms.enable_link(link_id)
            if not r.get("ok"):
                return False, f"lien désactivé, réactivation refusée ({r.get('error')})", soucis
            soucis.append("copie d'une page de base désactivée : lien réactivé")
    return True, "", soucis


def _poser(cle: str, entree: Dict[str, Any]) -> str:
    def modif(d):
        d["liens"][cle] = entree
        return True, None
    _, _, err = _ecrire(modif)
    return err


def _mettre_en_etat(cle: str, entree: Dict[str, Any], g: Dict[str, Any], tracking: str,
                    nom: str, out: Dict[str, Any], deja: bool,
                    base_boutons: Optional[List[Any]] = None,
                    lire_base: Optional[Callable[[], Optional[List[Any]]]] = None,
                    activer: bool = False) -> Dict[str, Any]:
    activer = activer or bool(entree.get("a_activer"))
    ok, err, soucis = _brancher(entree["link_id"], tracking, nom, base_boutons, lire_base,
                                activer=activer)
    etait = entree.get("etat")
    neuve = {**entree, "global_link_id": str(g.get("link_id")), "tracking": tracking,
             "nom": nom, "etat": "ok" if ok else "a_reparer", "tente": _maintenant()}
    neuve.pop("erreur", None)
    if ok:
        neuve.pop("a_activer", None)
        # l'adresse part chez le VA : desormais, un changement de son global
        # la rebranche sans attendre son clic (a_rebrancher)
        neuve["donne"] = True
        if deja:
            neuve["repare"] = _maintenant()
    else:
        neuve["erreur"] = err
        if activer:
            neuve["a_activer"] = True
    err_reg = _poser(cle, neuve)
    if err_reg:
        soucis.append(err_reg)
    out["soucis"] += soucis
    out.update(nom=nom, link_id=neuve["link_id"], deja=deja)
    if ok and err_reg:
        # Branchee, mais le registre ne le sait pas : sans lui, la page n'est
        # rattachee a aucun global, et la paie en ferait une ligne de plus
        # (un fixe) des son premier clic. L'adresse attend donc ; le clic
        # suivant reprend cette page a son nom (etape « homonymes »), sans
        # recopie.
        out.update(ok=False, url="", repare=False,
                   erreur=f"Lien « {nom} » prêt mais non enregistré ({err_reg}) : reclique plus tard.")
        print(f"[liens_identite_us] {nom} ({entree.get('link_id')}) branché mais registre non "
              f"écrit, adresse non donnée : {err_reg}", flush=True)
        return out
    if ok:
        out.update(ok=True, url=neuve.get("public_url") or "", repare=deja, erreur="")
        print(f"[liens_identite_us] {nom} -> {out['url']} "
              f"({'réparé' if deja else 'créé'}{', était ' + str(etait) if deja else ''})", flush=True)
    else:
        # l'adresse n'est PAS rendue : ses boutons visent peut-etre encore le
        # c<N> de la page de base
        out.update(ok=False, url="", repare=False,
                   erreur=f"Lien « {nom} » pas encore branché ({err}) : reclique plus tard.")
        print(f"[liens_identite_us] {nom} ({entree.get('link_id')}) a réparer : {err}", flush=True)
    return out


def creer_pour_identite(uid: Any, identite: Any, par: Any = None) -> Dict[str, Any]:
    """Le lien de ce VA pour cette identite : cree s'il manque, redonne s'il
    existe, repare sur place s'il etait rate. Un seul par (VA, identite).

    Rend {ok, url, deja, repare, erreur} (+ nom, link_id, soucis ; actif
    quand le lien etait deja en ordre). `deja` : le lien existait avant ce
    clic. `repare` : ce clic l'a remis en etat (branche, renomme apres un
    changement du global, ou repris au registre). ok faux => url vide : une
    copie non branchee n'est jamais donnee. Ne leve pas : une erreur imprevue
    devient `erreur`."""
    u, ident = _uid(uid), _ident(identite)
    out: Dict[str, Any] = {"ok": False, "url": "", "deja": False, "repare": False, "erreur": "",
                           "nom": "", "link_id": "", "soucis": []}
    if not u or not ident:
        out["erreur"] = "VA ou identité manquant"
        return out
    with _verrou(f"{u}:{ident}"):
        try:
            gms = _gms()
            with gms.api_tag(ETIQUETTE):
                return _creer(u, ident, str(identite).strip(), par, out)
        except Exception as e:                               # noqa: BLE001
            traceback.print_exc()
            out.update(ok=False, url="", erreur=f"interrompu : {type(e).__name__}: {e}")
            return out


def _creer(u: str, ident: str, affichee: str, par: Any, out: Dict[str, Any]) -> Dict[str, Any]:
    gms = _gms()
    cle = f"{u}:{ident}"
    d = _lire_registre()
    if d is None:
        out["erreur"] = f"registre data/{REGISTRE.name} illisible"
        return out
    g = d["globaux"].get(u)
    if not isinstance(g, dict) or not g.get("link_id"):
        out["erreur"] = "Pas encore de lien global : un admin doit le poser."
        return out
    entree = d["liens"].get(cle) if isinstance(d["liens"].get(cle), dict) else None
    if entree and entree.get("identite"):
        # le nom suit la graphie du PREMIER clic : « IbenHaastrup » puis
        # « ibenhaastrup » renommait le lien a chaque appel (deux appels payes)
        affichee = str(entree["identite"])

    def deja_sans_verif(raison: str) -> Optional[Dict[str, Any]]:
        # GetMySocial muet : un lien deja branche SUR SON GLOBAL DU MOMENT se
        # redonne tel quel (rien a appeler) ; tout le reste attend. Un « ok »
        # branche sur un ancien global enverrait ses fans chez un autre VA.
        if entree and _a_jour_pour(entree, g) and entree.get("public_url"):
            out.update(ok=True, url=entree["public_url"], deja=True, nom=str(entree.get("nom") or ""),
                       link_id=str(entree.get("link_id") or ""))
            out["soucis"].append(raison)
            return out
        return None

    liens, raison = liens_equipe()
    if raison:
        return deja_sans_verif(raison) or {**out, "erreur": raison}
    gl = _par_id(liens, g["link_id"])
    if gl is None and _relecture_permise(f"global:{g['link_id']}"):
        liens, raison = liens_equipe(force=True)
        if raison:
            return deja_sans_verif(raison) or {**out, "erreur": raison}
        gl = _par_id(liens, g["link_id"])
    if gl is None:
        out["erreur"] = (f"Ton lien global « {g.get('nom')} » n'est plus dans {NOM_EQUIPE} : "
                         "un admin doit en poser un autre.")
        return out
    code, pourquoi = _code_suivi(gl.get("url"))
    if not code:
        out["erreur"] = (f"Ton lien global « {gl.get('display_name')} » ne vise plus un suivi "
                         f"OnlyFans de Jessye ({pourquoi}).")
        return out
    g = _rafraichir_global(u, g, gl, code)
    tracking = str(gl.get("url") or "").strip()
    nom = nom_lien(g, affichee)
    if not nom:
        out["erreur"] = f"Aucun nom de lien ne garde la personne de « {g.get('nom')} »"
        return out

    # 1. deja au registre
    if entree and entree.get("link_id"):
        present = _par_id(liens, entree["link_id"])
        if present is None:
            liens2, r2 = liens_equipe(force=True)
            if r2:
                return deja_sans_verif(r2) or {**out, "erreur": r2}
            liens = liens2
            present = _par_id(liens, entree["link_id"])
        if present is not None:
            sc_neuf = str(present.get("shortcode") or "")
            change_sc = bool(sc_neuf) and sc_neuf != str(entree.get("shortcode") or "")
            if change_sc:
                # adresse changee dans GetMySocial : l'ancienne ne mene plus
                # nulle part, c'est la nouvelle qui se donne
                entree = {**entree, "shortcode": sc_neuf, "public_url": f"{DOMAINE}/{sc_neuf}",
                          "vu_change": _maintenant()}
            # le meme suivi a une barre finale pres n'est pas un changement
            # (_a_jour_pour compare les codes) : chaque reparation inutile
            # coute deux appels
            a_jour = _a_jour_pour(entree, g) and entree.get("nom") == nom
            if a_jour:
                if change_sc:
                    err = _poser(cle, entree)
                    if err:
                        out["erreur"] = (f"Nouvelle adresse de « {nom} » non enregistrée ({err}) : "
                                         "reclique plus tard.")
                        return out
                out.update(ok=True, url=str(entree.get("public_url") or ""), deja=True, nom=nom,
                           link_id=str(entree["link_id"]), actif=_actif(present),
                           adresse_changee=change_sc)
                return out
            return _mettre_en_etat(cle, entree, g, tracking, nom, out, deja=True,
                                   lire_base=lambda: _boutons_base(ident, liens))
        # supprime a la main dans GetMySocial : garde en trace, puis recree
        perdu = {**entree, "cle": cle, "perdu": _maintenant()}

        def oublier(dd):
            dd.setdefault("perdus", []).append(perdu)
            dd["liens"].pop(cle, None)
            return True, None
        _, _, err = _ecrire(oublier)
        if err:
            out["soucis"].append(err)
        out["soucis"].append(f"l'ancien lien {entree.get('public_url')} n'existe plus dans "
                             "GetMySocial : un nouveau est créé")
        print(f"[liens_identite_us] {cle} : {entree.get('link_id')} disparu de {NOM_EQUIPE}", flush=True)

    # 2. absent du registre mais present a son nom (registre perdu, reponse
    # de duplicate_link perdue) : repris, pas recopie
    d = _lire_registre() or d
    pris = {str(e.get("link_id")) for k, e in d["liens"].items() if k != cle and isinstance(e, dict)}
    pris |= {str(x.get("link_id")) for x in d["globaux"].values() if isinstance(x, dict)}
    homonymes = sorted((l for l in liens if _meme_nom(l.get("display_name"), nom)
                        and str(l.get("id")) not in pris),
                       key=lambda l: (_nombre(l.get("created")), str(l.get("id"))))
    if homonymes:
        l = homonymes[0]
        if len(homonymes) > 1:
            print(f"[liens_identite_us] {len(homonymes)} liens « {nom} » hors registre : "
                  f"{l.get('shortcode')} repris", flush=True)
        sc = str(l.get("shortcode") or "")
        entree = _entree(l, sc, g, tracking, affichee, nom, par)
        entree["repris"] = "trouvé à son nom dans GetMySocial, absent du registre"
        return _mettre_en_etat(cle, entree, g, tracking, nom, out, deja=True,
                               lire_base=lambda: _boutons_base(ident, liens))

    # 3. creation : copie de la page de base
    base = bases(liens).get(ident)
    if not base and _relecture_permise(f"base:{ident}"):
        # faite a l'instant par le proprietaire : pas encore dans le cache de
        # 15 min de gms. Une relecture, sur ce seul chemin d'erreur, et une
        # par quart d'heure au plus
        l2, r2 = liens_equipe(force=True)
        if not r2:
            liens = l2
            base = bases(liens).get(ident)
    if not base:
        out["erreur"] = f"Pas de page de base « TEMPLATE {affichee} » dans {NOM_EQUIPE}."
        return out
    rb = gms.get_link(str(base["id"]), EQUIPE)
    if not rb.get("ok"):
        out["erreur"] = f"Page de base « {base.get('display_name')} » illisible ({rb.get('error')})"
        return out
    blien = rb.get("link") or {}
    bboutons = blien.get("buttons")
    if not (isinstance(bboutons, list) and _urls_of(bboutons)):
        direct = str(blien.get("type") or base.get("type") or "") == "directlink"
        out["erreur"] = (f"La page de base « {base.get('display_name')} » n'a aucun bouton OnlyFans"
                         + (" (c'est un lien direct, pas une page)" if direct else "") + ".")
        return out
    connus = {str(l.get("shortcode") or "").lower() for l in liens}
    connus |= {str(e.get("shortcode") or "").lower() for e in d["liens"].values() if isinstance(e, dict)}
    connus |= {str(e.get("shortcode") or "").lower() for e in d.get("perdus") or [] if isinstance(e, dict)}
    connus |= {str(x).lower() for x in d.get("pris_ailleurs") or []}
    copie, sc, appels = None, "", 0
    for essai in range(400):
        sc = shortcode_pour(ident, essai)
        if sc in connus:
            continue
        if appels >= ESSAIS_SHORTCODE:
            break
        appels += 1
        r = gms.duplicate_link(str(base["id"]), sc, nom, "", EQUIPE)
        lien = r.get("link") if r.get("ok") else None
        if isinstance(lien, dict) and lien.get("id"):
            copie = lien
            break
        err = str(r.get("error") or ("réponse sans identifiant" if r.get("ok") else "refus"))
        if "shortcode" in err.lower():
            connus.add(sc)
            if "recent" not in err.lower():
                # gms rejoue tout seul un appel dont la reponse s'est perdue
                # (_call_tool_brut) : la copie faite au premier envoi lui vaut
                # ce 409. Prise pour une adresse occupee ailleurs, elle restait
                # dans l'equipe, hors registre, bouton sur le c<N> de la page
                # de base -- et une seconde copie partait. On regarde d'abord.
                l2, r2 = liens_equipe(force=True)
                mienne = [l for l in l2 if str(l.get("shortcode") or "").lower() == sc
                          and _meme_nom(l.get("display_name"), nom)
                          and str(l.get("id")) not in pris] if not r2 else []
                if mienne:
                    copie = mienne[0]
                    out["soucis"].append("réponse de GetMySocial perdue : copie retrouvée à son adresse")
                    print(f"[liens_identite_us] {nom} : 409 sur {sc}, c'était notre copie "
                          f"({copie.get('id')}), reprise", flush=True)
                    break
            _noter_pris_ailleurs(sc)
            continue
        # reponse perdue ou illisible : la copie existe peut-etre. On regarde
        # avant tout nouvel essai -- deux copies feraient deux liens a son nom
        l2, r2 = liens_equipe(force=True)
        trouve = [l for l in l2 if _meme_nom(l.get("display_name"), nom)
                  and str(l.get("id")) not in pris] if not r2 else []
        if trouve:
            copie = trouve[0]
            sc = str(copie.get("shortcode") or sc)
            out["soucis"].append("réponse de GetMySocial perdue : copie retrouvée à son nom")
            break
        out["erreur"] = f"GetMySocial : {err}"
        return out
    if not copie:
        out["erreur"] = f"aucune adresse libre pour « {affichee} » ({appels} essai(s))"
        return out
    entree = _entree(copie, sc, g, tracking, affichee, nom, par)
    # ecrit AVANT de brancher : une coupure entre les deux laisse une entree
    # « a_reparer » -- le clic suivant repare, il ne recopie pas
    err = _poser(cle, entree)
    if err:
        out["soucis"].append(err)
    return _mettre_en_etat(cle, entree, g, tracking, nom, out, deja=False,
                           base_boutons=bboutons, activer=True)


#: Les adresses refusees (prises par un autre compte de la plateforme,
#: invisibles dans notre equipe). Retenues : sans elles, chaque VA suivant
#: repayait le meme refus sur le quota du jour.
PRIS_AILLEURS_MAX = 1000


def _noter_pris_ailleurs(sc: str) -> None:
    def modif(d):
        l = [x for x in d.get("pris_ailleurs") or [] if x != sc] + [sc]
        d["pris_ailleurs"] = l[-PRIS_AILLEURS_MAX:]
        return True, None
    _, _, err = _ecrire(modif)
    if err:
        print(f"[liens_identite_us] adresse {sc} prise ailleurs, non retenue : {err}", flush=True)


def _entree(l: Dict[str, Any], sc: str, g: Dict[str, Any], tracking: str, identite: str,
            nom: str, par: Any) -> Dict[str, Any]:
    return {"link_id": str(l.get("id")), "shortcode": sc,
            "public_url": f"{DOMAINE}/{sc}" if sc else "",
            "global_link_id": str(g.get("link_id")), "tracking": tracking,
            "identite": identite, "nom": nom, "etat": "a_reparer",
            "par": str(par or ""), "quand": _maintenant()}


def _boutons_base(ident: str, liens: List[Dict[str, Any]]) -> Optional[List[Any]]:
    base = bases(liens).get(ident)
    if not base:
        return None
    r = _gms().get_link(str(base["id"]), EQUIPE)
    if not r.get("ok"):
        return None
    b = (r.get("link") or {}).get("buttons")
    return b if isinstance(b, list) else None


# ─── ce que le VA a ──────────────────────────────────────────────────────
def liens_du_va(uid: Any, liens: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Tous les liens de l'equipe de la meme personne que son global -- au
    sens du podium (podium_discord.personne), SPAM compris -- plus ses liens
    d'identite du registre (meme renommes a la main). Hors pages de base, et
    hors ce que le registre donne a un AUTRE VA (sa page d'identite, son
    global) : une page pas encore rebranchee porte encore le nom de l'ancien
    global, et etait comptee chez les deux."""
    u = _uid(uid)
    d = registre()
    if liens is None:
        liens, _ = liens_equipe()
    ids = {str(e.get("link_id")) for k, e in d["liens"].items()
           if k.startswith(u + ":") and isinstance(e, dict) and e.get("link_id")}
    a_autrui = {str(e.get("link_id")) for k, e in d["liens"].items()
                if not k.startswith(u + ":") and isinstance(e, dict) and e.get("link_id")}
    a_autrui |= {str(x.get("link_id")) for a, x in d["globaux"].items()
                 if a != u and isinstance(x, dict) and x.get("link_id")}
    a_autrui -= ids
    g = d["globaux"].get(u)
    personne = None
    if isinstance(g, dict):
        gl = _par_id(liens, g.get("link_id"))
        personne = pd.personne(_nom_de(gl) if gl else str(g.get("nom") or ""))[0]
    out = []
    for l in liens:
        dn, lid = _nom_de(l), str(l.get("id"))
        if est_base(dn):
            continue
        if lid in ids or (lid not in a_autrui and personne is not None
                          and pd.personne(dn)[0] == personne):
            out.append(l)
    return out


def liens_actifs(uid: Any, liens: Optional[List[Dict[str, Any]]] = None) -> int:
    """Combien de ses liens sont en service (statut « active »)."""
    return sum(1 for l in liens_du_va(uid, liens) if _actif(l))


def liens_de(uid: Any) -> List[Dict[str, Any]]:
    """Ses liens d'identite au registre, dans l'ordre de creation."""
    u = _uid(uid)
    out = [dict(e) for k, e in registre()["liens"].items()
           if k.startswith(u + ":") and isinstance(e, dict)]
    return sorted(out, key=lambda e: _nombre(e.get("quand")))


_CACHE_RATT: Dict[str, Any] = {"cle": None, "val": {}}


def rattachements() -> Dict[str, str]:
    """{link_id d'un lien d'identite: link_id du global}. Pour la page
    Infloww, le podium et le report des clics (par
    clics_personnes.rattachements_identite) : un lien d'identite n'est pas une
    ligne payee, ses clics vont a la ligne de son global. Les liens
    « a_reparer » en sont : ils existent et portent le nom du VA.

    Le global est celui du VA AUJOURD'HUI (globaux[uid]), pas celui ou la
    page a ete branchee : un admin qui corrige le global d'un VA lui rend ses
    pages tout de suite, au lieu de les laisser chez l'ancien global -- qu'un
    autre VA peut recevoir ensuite. Un VA sans global (parti, global repris
    par un autre) garde le global_link_id de ses pages : ce meme lien, donc
    son heritier.

    LEVE si le registre existe mais ne se lit pas : rendre {} ferait
    redevenir chaque page d'identite une ligne payee, sans un mot.
    clics_personnes rattrape et le dit (rattachements_identite_ou_panne).

    Gardee tant que le fichier ne change pas (inode, date, taille : chaque
    ecriture atomique cree un nouveau fichier) : elle est appelee a chaque
    regroupement, plusieurs fois par affichage."""
    try:
        st = REGISTRE.stat()
        cle = (str(REGISTRE), st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        cle = (str(REGISTRE), None, None, None)
    if cle == _CACHE_RATT["cle"]:
        return dict(_CACHE_RATT["val"])
    d = _lire_registre()
    if d is None:
        raise RuntimeError(f"registre data/{REGISTRE.name} illisible")
    val = {}
    for k, e in d["liens"].items():
        if not (isinstance(e, dict) and e.get("link_id")):
            continue
        g = d["globaux"].get(str(k).split(":", 1)[0])
        glob = str((g.get("link_id") if isinstance(g, dict) else "") or e.get("global_link_id") or "")
        if glob:
            val[str(e["link_id"])] = glob
    _CACHE_RATT.update(cle=cle, val=val)
    return dict(val)


def identites_proposables(identites_us: Iterable[Any],
                          liens: Optional[List[Dict[str, Any]]] = None,
                          uid: Any = None) -> List[Tuple[str, bool]]:
    """[(identite, a_deja_un_lien)] des identites US qui ONT une page de base,
    dans l'ordre recu. `a_deja_un_lien` : ce VA (uid) a deja son lien branche
    pour elle SUR SON GLOBAL DU MOMENT (_a_jour_pour) ; toujours faux sans
    uid. Un « ok » branche sur un ancien global n'a pas sa coche : le VA est
    invite a rechoisir, ce qui le rebranche. Celles sans page : etat_bases."""
    b = bases(liens)
    u = _uid(uid)
    a_lui = set()
    if u:
        d = registre()
        g = d["globaux"].get(u)
        a_lui = {k.split(":", 1)[1] for k, e in d["liens"].items()
                 if k.startswith(u + ":") and _a_jour_pour(e, g)}
    out, vues = [], set()
    for i in identites_us or []:
        k = _ident(i)
        if k and k not in vues and k in b:
            vues.add(k)
            out.append((str(i), k in a_lui))
    return out
