"""Les liens de suivi de Jessye, PAR PERSONNE, comme sur GetMySocial.

Ce que le propriétaire a demandé : « c'est que les tracking sur le retour de
Jessye sur GMS qui sont comptés, chaque personne c'est un truc ». Donc :

- LES PERSONNES viennent de GetMySocial, espace « JESSY LE RETOUR » et lui
  seul (l'autre espace, EMY TWITTER, pointe vers Emy). Liste lue EN DIRECT ;
  si GetMySocial ne répond pas, repli sur le cache du site
  (data/gmsdash_links.json), et la page le DIT. Le nom d'une personne se tire
  du nom du lien par podium_discord.entites (personne + cle_entite) : les
  MÊMES fonctions que le podium — deux règles de nommage auraient donné deux
  classements. Le lien SPAM compte comme une personne à part (règle voulue).
- LES CHIFFRES viennent d'Infloww (infloww.py, API officielle, lecture
  seule). Chaque lien GMS pointe vers onlyfans.com/jessyewdiference/c<N>, et
  le lien de suivi Infloww de code N porte ses clics, subs et gains. Plusieurs
  liens GMS d'une personne visent souvent le MÊME code (le 26/09, BO7 : 4
  liens GMS → c85) : une personne additionne ses liens Infloww DISTINCTS,
  jamais deux fois le même.
- Par personne : Clics US (GetMySocial, depuis toujours — la mesure du
  podium et de la page « Clics US » du tableau de bord), Clics OF (Infloww),
  Subs, CVR = subs ÷ clics OF, $ / sub = gains NETS ÷ subs. Le total des
  gains n'est affiché NULLE PART : le salon est public, les VA le lisent.
- Rien n'est écarté sans trace : un lien GMS sans lien Infloww en face est
  dit (« lien Infloww introuvable », jamais un zéro inventé), et les liens
  Infloww de Jessye qu'aucun lien GMS ne vise sont listés à part, non
  comptés.

- UNE PÉRIODE (?du=AAAA-MM-JJ&au=AAAA-MM-JJ, formulaire en tête de page) :
  mêmes personnes, mêmes règles, mais les chiffres de ces jours-là. Clics OF,
  subs et gains viennent alors de MyPuls (un appel pour tous les liens, bornes
  incluses, heure de Paris), les clics US de GetMySocial sur les mêmes jours
  (calculés en arrière-plan, gardés sur disque ; périodes distinctes et
  appels plafonnés par jour ; MyPuls attendu 5 s au plus). Sans
  période, la vue Infloww « depuis toujours » est inchangée ; Discord aussi.

Deux sorties : la page /infloww/liens, sans JavaScript (clé ?k= pour les VA
sans compte), et des messages Discord de Bixby dans « inflow-resultat ».
L'ENVOI DISCORD EST COUPÉ tant que data/infloww_liens_config.json ne porte pas
"discord_actif": true — le propriétaire veut d'abord choisir le format.

infloww.py n'est importé que par ce module et web_upload.py.
"""
from __future__ import annotations

import base64
import datetime as dt
import html as _html
import json
import re
import unicodedata
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import safe_json
import infloww
import podium_discord as pd

CREATRICE = "jessyewdiference"
NOM_AFFICHE = "Jessye"
# L'espace GetMySocial « JESSY LE RETOUR », le seul compté : l'autre espace
# des VA (EMY TWITTER) pointe vers Emy, pas vers Jessye.
EQUIPE_GMS = "tm_6a0e4739bfa0c238f20a8bf5"
NOM_EQUIPE = "JESSY LE RETOUR"
GUILD = "1535758943324999711"        # serveur Youl4b
SALON = "1553218920842928219"        # salon « inflow-resultat », public : les VA le voient
BOT_APP = "1552785601051365516"      # application Discord de Bixby
REFRESH_S = 2 * 3600                 # Infloww ne met ses liens à jour que toutes les 2 h

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "infloww_liens_discord.json"
CONFIG_FICHIER = DATA_DIR / "infloww_liens_config.json"
US_FICHIER = DATA_DIR / "infloww_liens_us.json"
CLE_FICHIER = DATA_DIR / "infloww_liens_cle"
# le cache de liste du site, celui dont le podium se sert aussi en repli
GMS_CACHE = pd.LIENS_CACHE
JETON_FICHIERS: Tuple[Path, ...] = (DATA_DIR / "bixby_bot_token",
                                    Path.home() / ".config" / "bixby_bot_token")
SITE = "https://youl4b.com"
API_DISCORD = "https://discord.com/api/v10"

COULEUR = 0xF97341                   # l'orange d'Infloww
# Discord refuse une description d'embed de plus de 4 096 caractères et un
# message de plus de 6 000 en tout (titre + description + pied). On remplit
# une page à 3 900 au plus, un seul embed par message : titre et pied tiennent
# largement dans les 2 100 restants.
DESCRIPTION_MAX = 3900
NOM_DISCORD_MAX = 80                 # un nom plus long est coupé (entier sur la page)

# Clics US « depuis toujours » : un appel GetMySocial par personne, une
# vingtaine en tout. Le chiffre bouge peu : relevé une fois par jour, gardé
# sur disque. Un relevé raté est retenté, mais pas à chaque affichage.
US_REESSAI_S = 600
US_ATTENTE_S = 20                    # premier affichage sans aucun relevé : on attend ça, pas plus
US_PAUSE_S = 0.3                     # entre deux appels, comme le podium
# Faux dans les tests : le relevé se fait alors sur place, sans fil qui
# survivrait aux bouchons et partirait sur le vrai GetMySocial.
US_EN_FOND = True

# ─── une PÉRIODE choisie sur la page (?du=AAAA-MM-JJ&au=AAAA-MM-JJ) ───────
# Le propriétaire (26/09) : « je sélectionne les cinq derniers jours jusqu'à
# aujourd'hui, je fais OK, et ça retravaille les calculs ». Infloww ne donne
# que des compteurs cumulés depuis la création du lien : les chiffres d'une
# période viennent de MyPuls (« les clics avec MyPuls »), qui rend TOUS les
# liens de suivi en un seul appel, période comprise. Sans période : la vue
# Infloww d'avant, inchangée.
PLANCHER = dt.date.fromisoformat(pd.ALLTIME_DEPUIS)   # avant les premiers liens
MYPULS_TTL_S = 600                   # une période relue au plus toutes les 10 min
_MYPULS_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_MYPULS_CACHE_MAX = 40
# MyPuls lent ou muet (relecture du 26/09) : chaque affichage d'une période
# attendait les 30 s de mypuls.api_get, sans garder trace de l'échec, et sur
# un 429 relançait jusqu'à six appels — ce qui prolongeait la limitation pour
# tout le tableau de bord. La lecture part donc dans un fil, UN par période ;
# la page ne l'attend que MYPULS_ATTENTE_S (compté depuis le départ du fil :
# un rechargement pendant la lecture sort tout de suite) ; un échec est gardé
# MYPULS_ECHEC_S, sans rappeler MyPuls entre-temps.
MYPULS_ATTENTE_S = 5.0
MYPULS_ECHEC_S = 90
_MYPULS_ECHECS: Dict[Tuple[str, str], Dict[str, Any]] = {}
_MYPULS_FILS: Dict[Tuple[str, str], Dict[str, Any]] = {}
# à part de _VERROU, que l'envoi Discord garde pendant tout un relevé
_VERROU_MP = threading.Lock()
# Clics US d'une période : un appel GetMySocial par personne, comme depuis
# toujours, mais sur un quota serré et partagé avec le tableau de bord (épuisé
# le 26/09 au petit matin). D'où un cache disque par (personne, période) et un
# plafond de périodes DISTINCTES calculées par jour : au-delà, « — », dit.
US_PERIODES_FICHIER = DATA_DIR / "infloww_liens_us_periodes.json"
US_PERIODES_MAX_JOUR = 6
# Le plafond de périodes DISTINCTES ne bornait pas les appels (relecture du
# 26/09) : une période qui finit aujourd'hui repartait pour tout le monde
# toutes les 2 h sans compter dans le plafond — trois raccourcis ouverts
# toutes les 2 h, 36 calculs complets par jour, 1 008 appels avec 28
# personnes. D'où un BUDGET d'appels par jour, décompté à CHAQUE appel
# (recalculs, reprises et vérifications de zéro compris) : 6 par personne,
# soit six calculs complets. Au-delà, plus rien avant le lendemain, dit.
US_PERIODES_APPELS_PAR_PERSONNE = 6
US_OUVERTE_FRAIS_S = 2 * 3600        # période qui finit aujourd'hui : recalculée toutes les 2 h
US_PERIODE_ESSAIS_MAX = 3            # relevés ratés d'une personne sur une période, par jour
US_PERIODES_GARDE_S = 45 * 86400     # au-delà, une période plus consultée sort du cache

TRIS = ("nom", "us", "clics", "subs", "cvr", "par_sub")
SENS = ("asc", "desc")

_VERROU = threading.RLock()
_VERROU_US = threading.Lock()
_FIL_US: Dict[str, Any] = {"fil": None}
# le calcul d'une période a son propre verrou : il ne bloque pas le relevé
# « depuis toujours » du démon, et n'est pas bloqué par lui
_VERROU_US_P = threading.Lock()
_FIL_US_P: Dict[str, Any] = {"fil": None}


def _texte_erreur(e: Exception) -> str:
    code = getattr(e, "code", 0)
    rid = getattr(e, "request_id", "")
    return (str(e) + (f" (HTTP {code})" if code else "")
            + (f" [x-request-id {rid}]" if rid else ""))


def _lire_json(chemin: Path) -> Dict[str, Any]:
    try:
        d = safe_json.load(chemin, default={}) or {}
    except Exception:
        d = {}
    return d if isinstance(d, dict) else {}


def _aujourdhui() -> str:
    # l'heure de Paris, comme le podium : le VPS tourne en UTC
    return pd._aujourdhui().isoformat()


# ─── GetMySocial : qui est qui ───────────────────────────────────────────
# La page garde SA copie de la dernière liste GMS réussie, adresses OnlyFans
# comprises. Le 26/09, le quota GetMySocial épuisé renvoyait la page sur le
# cache du site, qui n'avait pas les adresses : 28 personnes « introuvables ».
# Et relire GMS à chaque affichage usait ce quota partagé avec le tableau de
# bord : la liste est reprise telle quelle pendant GMS_FRAIS_S.
GMS_COPIE = DATA_DIR / "infloww_liens_gms.json"
GMS_FRAIS_S = 600
_CHAMPS_GMS = ("id", "shortcode", "display_name", "title", "url")


def _copie_gms() -> Dict[str, Any]:
    d = _lire_json(GMS_COPIE)
    L = d.get("liens") if isinstance(d, dict) else None
    return {"t": float(d.get("t") or 0), "liens": L} if isinstance(L, list) and L else {}


def liens_gms(maintenant: Optional[float] = None) -> Dict[str, Any]:
    """{liens, repli} de l'espace JESSY LE RETOUR. `repli` non vide = la
    liste vient d'une copie (et dit pourquoi). Ne lève jamais."""
    maintenant = time.time() if maintenant is None else maintenant
    copie = _copie_gms()
    if copie and maintenant - copie["t"] < GMS_FRAIS_S:
        return {"liens": list(copie["liens"]), "repli": ""}
    raison = ""
    try:
        import gms
        # force_refresh : un lien créé dans la journée doit apparaître au
        # prochain relevé, pas à l'expiration du cache de gms
        r = gms.list_links_team(EQUIPE_GMS, force_refresh=True) or {}
        vivants = r.get("links") or r.get("data") or []
        if r.get("ok") is not False and vivants:
            try:
                safe_json.write_text(GMS_COPIE, json.dumps(
                    {"t": maintenant, "liens": [{k: l.get(k) for k in _CHAMPS_GMS if l.get(k) is not None}
                                               for l in vivants if isinstance(l, dict)]},
                    ensure_ascii=False))
            except Exception as e:
                print(f"[infloww-liens] copie GMS non écrite : {e}", flush=True)
            return {"liens": list(vivants), "repli": ""}
        raison = str(r.get("error") or "liste vide")
    except Exception as e:
        raison = f"{type(e).__name__} : {e}"
    if copie:
        return {"liens": list(copie["liens"]),
                "repli": f"{raison or '?'} — dernière liste lue le {_heure(copie['t'])}"[:300]}
    cache = _lire_json(GMS_CACHE).get(EQUIPE_GMS) or []
    return {"liens": list(cache) if isinstance(cache, list) else [],
            "repli": (raison or "?")[:300]}


def nom_gms(l: Mapping[str, Any]) -> str:
    # l'ordre de podium_discord.entites : le même lien porte le même nom partout
    return str(l.get("display_name") or l.get("title") or l.get("shortcode") or "")


_URL_OF = re.compile(r"^https?://(?:www\.)?onlyfans\.com/([^/?#\s]+)/c(\d+)/?(?:[?#]\S*)?$", re.I)


def code_de_l_url(url: Any) -> Tuple[str, str]:
    """(code, raison) : « 110 » pour https://onlyfans.com/jessyewdiference/c110,
    sinon ("", pourquoi ce n'est pas un lien de suivi de Jessye)."""
    u = str(url or "").strip()
    if not u:
        return "", "le lien GetMySocial n'a pas d'adresse OnlyFans"
    m = _URL_OF.match(u)
    if not m:
        return "", "l'adresse du lien GetMySocial n'est pas un lien de suivi OnlyFans"
    if m.group(1).lower() != CREATRICE:
        return "", f"le lien GetMySocial pointe vers @{m.group(1)}, pas vers @{CREATRICE}"
    return str(int(m.group(2))), ""


def _code_infloww(x: Mapping[str, Any]) -> str:
    """Le code d'un lien Infloww (champ « code » de infloww._lien_norm),
    ramené à la forme de l'adresse OnlyFans : « 110 »."""
    c = str(x.get("code") or "").strip()
    m = re.fullmatch(r"[cC]?(\d+)", c)
    return str(int(m.group(1))) if m else c


def entites(liens: List[Any]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """({clé: {nom, spam, ids}}, liens sans identifiant). Le regroupement est
    celui du podium, tel quel ; un lien sans identifiant est compté, pas avalé."""
    propres = [l for l in liens if isinstance(l, Mapping) and l.get("id")]
    return pd.entites([dict(l) for l in propres]), len(liens) - len(propres)


# ─── Clics US : GetMySocial, une fois par jour ───────────────────────────
def _us_cache() -> Dict[str, Any]:
    return _lire_json(US_FICHIER)


def us_depuis_cache(ents: Mapping[str, Mapping[str, Any]], cache: Optional[Mapping[str, Any]] = None,
                    jour: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{clé: {us, jour, etat, raison}}. etat : « ok » (relevé du jour, sur les
    liens d'aujourd'hui), « ancien » (valeur d'un autre jour ou d'une autre
    liste de liens), « rate » (le dernier essai a échoué : l'ancienne valeur
    reste), « absent » (jamais relevé). Jamais un zéro inventé."""
    cache = _us_cache() if cache is None else cache
    jour = jour or _aujourdhui()
    pers = cache.get("personnes") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for cle, e in ents.items():
        c = pers.get(cle) or {}
        v = c.get("us")
        ids = sorted(str(i) for i in e.get("ids") or [])
        if c.get("rate"):
            etat = "rate"
        elif v is None:
            etat = "absent"
        elif c.get("jour") == jour and sorted(c.get("ids") or []) == ids:
            etat = "ok"
        else:
            etat = "ancien"
        out[cle] = {"us": None if v is None else int(v), "jour": str(c.get("jour") or ""),
                    "etat": etat, "raison": str(c.get("rate") or "")}
    return out


def _a_mesurer(ents: Mapping[str, Mapping[str, Any]], cache: Mapping[str, Any], jour: str,
               maintenant: float) -> List[str]:
    etats = us_depuis_cache(ents, cache, jour)
    pers = cache.get("personnes") or {}
    return [c for c in ents if etats[c]["etat"] != "ok"
            # un essai raté il y a cinq minutes n'est pas refait à chaque affichage
            and not (etats[c]["etat"] == "rate"
                     and maintenant - float((pers.get(c) or {}).get("essai") or 0) < US_REESSAI_S)]


def _dormir_us(s: float) -> None:
    time.sleep(s)


def _pause_gms() -> int:
    """Secondes avant que GetMySocial accepte de nouveau (quota du jour
    épuisé), 0 si la voie est libre. Le 26/09, le quota du jour était déjà à
    zéro au petit matin : sans ce test, les vingt-huit relevés partaient l'un
    après l'autre pour rien."""
    try:
        import gms
        return max(0, int(gms.pause_restante() or 0))
    except Exception:
        return 0


def _reprise_gms() -> str:
    try:
        import gms
        r = str((gms.etat_quota() or {}).get("reprise") or "")
    except Exception:
        r = ""
    return f", reprise vers {r}" if r else ""


def releve_us(ents: Mapping[str, Mapping[str, Any]], forcer: bool = False) -> Dict[str, Any]:
    """Recalcule les clics US des personnes qui n'ont pas leur relevé du jour.

    UN appel par personne, tous ses liens GMS ensemble, comme le podium :
    GetMySocial calcule alors le détail par pays sur l'ensemble, alors qu'une
    somme de relevés séparés perd la traîne des pays. Un relevé raté garde
    l'ancienne valeur, marquée. Le cache est écrit après chaque personne :
    une page qui n'attend que vingt secondes a déjà ce qui est fait.
    """
    if not _VERROU_US.acquire(blocking=False):
        return {"appels": 0, "rates": 0, "occupe": True}
    try:
        jour = _aujourdhui()
        cache = _us_cache()
        cibles = list(ents) if forcer else _a_mesurer(ents, cache, jour, time.time())
        if not cibles:
            _noter_passage(cache, ents, jour)
            return {"appels": 0, "rates": 0}
        import gms
        pause = _pause_gms()
        if pause > 0:
            # GetMySocial a demandé de souffler : taper dans un quota épuisé
            # volerait les appels du tableau de bord. Les valeurs d'hier restent.
            return {"appels": 0, "rates": 0, "pause": pause}
        pers = dict(cache.get("personnes") or {})
        rates = appels = 0
        for i, cle in enumerate(cibles):
            if i and _pause_gms():
                # le quota du jour vient de tomber : les suivants seraient
                # refusés sans même partir. Ils restent « à relever », pas
                # « ratés » : le démon les reprendra à la levée de la pause.
                break
            ids = sorted(str(x) for x in ents[cle].get("ids") or [])
            raison = ""
            appels += 1
            try:
                tot, pays = gms.analytics_for_links(ids, pd.ALLTIME_DEPUIS, jour)
            except Exception as e:
                tot, pays, raison = None, None, f"{type(e).__name__} : {e}"[:160]
            if pays is not None and not tot and not pays:
                # 0 clic ET aucun pays, depuis toujours : c'est ce que gms rend
                # quand il n'a pas su lire la réponse. Constaté le 26/09 :
                # GetMySocial ajoutait « NOTICE: stale: true » après son JSON,
                # gms gardait le texte brut et en tirait (0, {}) — ANDRY, 207
                # clics US, serait sorti à zéro. Un zéro ne s'écrit pas sur un
                # relevé qu'on ne sait pas distinguer d'une panne.
                pays, raison = None, "GetMySocial a rendu un relevé vide ou illisible (0 clic, aucun pays)"
            c = dict(pers.get(cle) or {})
            c["essai"] = time.time()
            if pays is None:
                rates += 1
                if not raison and _pause_gms():
                    raison = "quota GetMySocial épuisé" + _reprise_gms()
                c["rate"] = f"{jour} : " + (raison or "GetMySocial n'a pas rendu de relevé")
            else:
                c.update(us=int((pays or {}).get("US") or 0), jour=jour, ids=ids, rate="")
            pers[cle] = c
            cache = dict(cache, personnes=pers, maj=time.time())
            safe_json.write(US_FICHIER, cache)
            if i + 1 < len(cibles):
                _dormir_us(US_PAUSE_S)
        _noter_passage(cache, ents, jour)
        return {"appels": appels, "rates": rates, "reportes": len(cibles) - appels}
    finally:
        _VERROU_US.release()


def _noter_passage(cache: Dict[str, Any], ents: Mapping[str, Mapping[str, Any]], jour: str) -> None:
    """Le passage du jour, pour us_a_rafraichir : complet si chaque personne
    d'aujourd'hui a son relevé du jour. Sans ça, une personne disparue de
    GetMySocial (lien renommé) restait « à relever » et le démon relisait la
    liste toutes les dix minutes pour rien."""
    complet = all(v["etat"] == "ok" for v in us_depuis_cache(ents, cache, jour).values())
    p = {"jour": jour, "complet": complet}
    if {k: (cache.get("passage") or {}).get(k) for k in p} == p:
        return                        # rien de neuf : pas d'écriture à chaque affichage
    safe_json.write(US_FICHIER, dict(cache, passage=dict(p, quand=time.time())))


def _lancer_us(ents: Mapping[str, Mapping[str, Any]]) -> Optional[threading.Thread]:
    """Le relevé en arrière-plan : la page ne l'attend pas. Un seul à la fois."""
    if not US_EN_FOND:
        releve_us(ents)
        return None
    with _VERROU:
        f = _FIL_US.get("fil")
        if f is not None and f.is_alive():
            return f
        f = threading.Thread(target=releve_us, args=(dict(ents),), daemon=True,
                             name="infloww-liens-us")
        _FIL_US["fil"] = f
        f.start()
        return f


def _us_pour_la_page(ents: Mapping[str, Mapping[str, Any]]) -> None:
    """Rien à relever : rien. Des valeurs d'avant : on les affiche et le
    relevé part derrière. Aucun relevé du tout (premier affichage) : on
    attend US_ATTENTE_S au plus, puis on affiche ce qui est arrivé."""
    cache = _us_cache()
    if not _a_mesurer(ents, cache, _aujourdhui(), time.time()):
        return
    f = _lancer_us(ents)
    if f is not None and not (cache.get("personnes") or {}):
        f.join(US_ATTENTE_S)


def us_a_rafraichir(maintenant: Optional[float] = None) -> bool:
    """Pour le démon, sans appeler GetMySocial : pas de passage aujourd'hui,
    ou un relevé raté à retenter."""
    p = _us_cache().get("passage") or {}
    if p.get("jour") != _aujourdhui():
        return True
    return (not p.get("complet")
            and (maintenant or time.time()) - float(p.get("quand") or 0) >= US_REESSAI_S)


def rafraichir_us() -> str:
    """Le relevé du jour, pour le démon. Rend un statut lisible ; ne lève pas."""
    try:
        pause = _pause_gms()
        if pause > 0:
            return f"clics US : GetMySocial en pause ({pause} s{_reprise_gms()}), relevé remis"
        g = liens_gms()
        ents, _sans_id = entites(g["liens"])
        if not ents:
            return "clics US : aucun lien GetMySocial lisible, rien à relever"
        r = releve_us(ents)
        if r.get("occupe"):
            return "clics US : un relevé est déjà en cours"
        if r.get("pause"):
            return f"clics US : GetMySocial en pause ({r['pause']} s{_reprise_gms()}), relevé remis"
        return (f"clics US : {r.get('appels', 0)} appel(s), {r.get('rates', 0)} raté(s)"
                + (f", {r['reportes']} remis (quota GetMySocial)" if r.get("reportes") else "")
                + (" — liste GMS du cache" if g["repli"] else ""))
    except Exception as e:
        return f"clics US : échec inattendu : {type(e).__name__} : {e}"


# ─── Infloww ─────────────────────────────────────────────────────────────
def _infloww() -> Dict[str, Any]:
    """Les liens de suivi de Jessye, lus dans Infloww. Ne lève jamais : une
    panne est rendue dans « erreur »."""
    suivi: Dict[str, Any] = {"appels": 0, "caches": 0, "plus_ancien": None}
    # le suivi d'infloww dit de quand date la plus vieille lecture servie par
    # son cache : « lu à » est l'âge réel des chiffres, pas l'heure d'affichage
    jeton_ctx = infloww._SUIVI.set(suivi)
    try:
        c, _toutes = infloww._creatrice_ou_erreur(CREATRICE)
        cid = str(c.get("id") or "")
        if not cid:
            return {"erreur": f"« {CREATRICE} » est rendue par Infloww sans identifiant"}
        r = infloww.liens(cid, "TRACKING")
    except infloww.ErreurInfloww as e:
        return {"erreur": _texte_erreur(e)}
    except Exception as e:  # une réponse de forme imprévue : dite, pas avalée
        return {"erreur": f"{type(e).__name__} : {e}"}
    finally:
        infloww._SUIVI.reset(jeton_ctx)
    return {"erreur": "", "liens": r.get("liens") or [], "tronque": r.get("tronque") or [],
            "doublons": r.get("doublons") or 0, "depuis": str(r.get("depuis") or ""),
            "lu_a": suivi.get("plus_ancien") or time.time()}


# ─── une période : les paramètres de l'adresse ───────────────────────────
_DATE_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DATE_FR = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _date_arg(v: Any) -> Optional[dt.date]:
    """AAAA-MM-JJ (ce qu'envoie un champ date), ou JJ/MM/AAAA (ce qu'on tape
    dans le champ texte d'un navigateur qui n'a pas de calendrier). Autre
    chose, ou une date qui n'existe pas (31/02) : None."""
    s = str(v or "").strip()[:20]
    m = _DATE_ISO.fullmatch(s)
    if m:
        a, mo, j = (int(x) for x in m.groups())
    else:
        m = _DATE_FR.fullmatch(s)
        if not m:
            return None
        j, mo, a = (int(x) for x in m.groups())
    try:
        return dt.date(a, mo, j)
    except ValueError:
        return None


def periode_des_args(args: Mapping[str, Any], aujourdhui: str = "") -> Optional[Tuple[str, str]]:
    """(du, au) en AAAA-MM-JJ, ou None = depuis toujours (la vue Infloww).

    Une date illisible est ignorée ; début seul = jusqu'à aujourd'hui, fin
    seule = depuis le premier jour ; bornes ramenées entre le 01/01/2024 et
    aujourd'hui (heure de Paris) ; début après fin = inversées."""
    try:
        auj = dt.date.fromisoformat(aujourdhui or _aujourdhui())
    except ValueError:
        auj = dt.date.today()
    du, au = _date_arg(args.get("du")), _date_arg(args.get("au"))
    if du is None and au is None:
        return None
    du = du or PLANCHER
    au = au or auj
    du, au = (min(max(d, PLANCHER), auj) for d in (du, au))
    if du > au:
        du, au = au, du
    return du.isoformat(), au.isoformat()


# ─── une période : MyPuls ────────────────────────────────────────────────
# Relevé réel du 26/09 (tracking-links, from/to) : la réponse rend la période
# comptée, « 2026-09-21T00:00:00+02:00 » → « 2026-09-26T23:59:59+02:00 » pour
# from=2026-09-21&to=2026-09-26 : journées ENTIÈRES, heure de Paris, les deux
# bornes INCLUSES ; le 25 plus le 26 donnent exactement 25→26 (clics, subs et
# gains). Le revenu est NET (sans période, c110 : 652,16 = le net d'Infloww).
def _entier(v: Any) -> Optional[int]:
    try:
        return None if v is None or v == "" or isinstance(v, bool) else int(v)
    except (TypeError, ValueError):
        return None


def _lire_mypuls(d: Any) -> Dict[str, Any]:
    """Les liens de suivi de Jessye dans une réponse tracking-links, à la forme
    d'infloww._lien_norm (net en centimes) : construire() s'en sert tel quel.
    Rattachés par l'ADRESSE (pseudo + code), jamais par le nom : « c47 »
    existe chez cinq créatrices."""
    items = d if isinstance(d, list) else None
    if items is None and isinstance(d, Mapping):
        inner = d.get("data")
        items = inner.get("data") if isinstance(inner, Mapping) else inner
    if not isinstance(items, list):
        return {"erreur": f"MyPuls a rendu une réponse de forme imprévue ({type(d).__name__})"}
    liens: List[Dict[str, Any]] = []
    vus: Dict[str, int] = {}
    illisibles = doublons = champs = 0
    for it in items:
        if not isinstance(it, Mapping):
            illisibles += 1
            continue
        url = str(it.get("url") or "").strip()
        m = _URL_OF.match(url)
        if not m:
            # un lien de Jessye à l'adresse illisible : compté, pas avalé
            if CREATRICE in url.lower():
                illisibles += 1
            continue
        if m.group(1).lower() != CREATRICE:
            continue
        code = str(int(m.group(2)))
        if code in vus:
            doublons += 1            # la même adresse deux fois : comptée UNE fois
            continue
        vus[code] = 1
        rev = it.get("revenue")
        total = rev.get("total") if isinstance(rev, Mapping) else rev
        try:
            net = None if total is None or isinstance(total, bool) else int(round(float(total) * 100))
        except (TypeError, ValueError):
            net = None
        subs = _entier(it.get("subscribers_period"))
        if net is None or subs is None:
            champs += 1
        liens.append({"id": f"mypuls:{code}", "nom": str(it.get("name") or "").strip(), "code": code,
                      "clics": _entier(it.get("visits_period")), "abonnes": subs, "net": net,
                      "termine": it.get("active") is False})
    compte = _entier(d.get("count")) if isinstance(d, Mapping) else None
    per = d.get("period") if isinstance(d, Mapping) else None
    return {"erreur": "", "liens": liens, "illisibles": illisibles, "doublons": doublons,
            "champs_manquants": champs,
            "tronque": ([f"MyPuls annonce {compte} liens de suivi, {len(items)} rendus"]
                        if compte is not None and compte > len(items) else []),
            "periode_mypuls": ({"from": str(per.get("from") or ""), "to": str(per.get("to") or "")}
                               if isinstance(per, Mapping) else {}),
            "devise": str(d.get("currency") or "") if isinstance(d, Mapping) else ""}


def _lire_mypuls_api(du: str, au: str) -> Tuple[Dict[str, Any], str]:
    """UN appel tracking-links : (liens lus, "") ou ({}, pourquoi)."""
    try:
        import mypuls
        # l'API brute et non api_tracking_links : celle-ci ne garde pas le
        # revenu, et rend [] aussi bien en panne que sans lien — une panne
        # serait passée pour « aucun sub »
        r = mypuls.api_get("tracking-links", {"per_page": 500, "from": du, "to": au})
    except Exception as e:
        r = {"ok": False, "error": f"{type(e).__name__} : {e}"}
    if not isinstance(r, Mapping) or not r.get("ok"):
        return {}, str((r or {}).get("error") if isinstance(r, Mapping) else r or "") or "pas de réponse"
    v = _lire_mypuls(r.get("data"))
    return v, str(v.get("erreur") or "")


def _releve_mypuls(du: str, au: str) -> None:
    """Le fil d'une période : lit MyPuls, range la lecture (cache) ou l'échec
    (gardé MYPULS_ECHEC_S), puis se retire. Ne lève jamais."""
    cle = (du, au)
    try:
        v, raison = _lire_mypuls_api(du, au)
    except Exception as e:  # par ceinture : un fil qui meurt sans rien ranger ne dirait rien
        v, raison = {}, f"{type(e).__name__} : {e}"
    t = time.time()
    with _VERROU_MP:
        if raison:
            _MYPULS_ECHECS[cle] = {"t": t, "raison": raison[:300]}
            if len(_MYPULS_ECHECS) > _MYPULS_CACHE_MAX:
                for k in sorted(_MYPULS_ECHECS, key=lambda k: _MYPULS_ECHECS[k]["t"])[:10]:
                    _MYPULS_ECHECS.pop(k, None)
        else:
            v["lu_a"] = t
            _MYPULS_CACHE[cle] = {"t": t, "v": v}
            _MYPULS_ECHECS.pop(cle, None)
            if len(_MYPULS_CACHE) > _MYPULS_CACHE_MAX:
                for k in sorted(_MYPULS_CACHE, key=lambda k: _MYPULS_CACHE[k]["t"])[:10]:
                    _MYPULS_CACHE.pop(k, None)
        if (_MYPULS_FILS.get(cle) or {}).get("fil") is threading.current_thread():
            _MYPULS_FILS.pop(cle, None)


def _sans_mypuls(hit: Optional[Mapping[str, Any]], raison: str, en_cours: bool = False) -> Dict[str, Any]:
    """MyPuls n'a pas donné de lecture neuve : la dernière réussie de CETTE
    période si elle existe (« perime » dit pourquoi et de quand), sinon
    « erreur »."""
    if hit:
        return dict(hit["v"], perime=f"{raison[:240]} — chiffres de la lecture du {_heure(hit['t'])}")
    if en_cours:
        return {"erreur": raison[:400], "en_cours": True}
    return {"erreur": f"MyPuls n'a pas répondu : {raison}"[:400]}


def _mypuls_periode(du: str, au: str, attente: Optional[float] = None) -> Dict[str, Any]:
    """Les liens de Jessye sur la période, lus dans MyPuls en UN appel (tous
    les liens de l'agence), gardés MYPULS_TTL_S. Ne lève jamais, et n'attend
    pas MyPuls plus de `attente` secondes (MYPULS_ATTENTE_S) : au-delà, la
    lecture continue dans son fil et la page le dit (« en_cours »)."""
    attente = MYPULS_ATTENTE_S if attente is None else float(attente)
    cle = (du, au)
    with _VERROU_MP:
        maintenant = time.time()
        hit = _MYPULS_CACHE.get(cle)
        if hit and 0 <= maintenant - hit["t"] < MYPULS_TTL_S:
            return dict(hit["v"])
        ech = _MYPULS_ECHECS.get(cle)
        if ech and 0 <= maintenant - ech["t"] < MYPULS_ECHEC_S:
            # échec récent : pas de nouvel appel, ni d'attente
            reste = int(MYPULS_ECHEC_S - (maintenant - ech["t"])) + 1
            return _sans_mypuls(hit, f"{ech['raison']} (essai du {_heure(ech['t'])}, "
                                     f"pas de nouvel essai avant {reste} s)")
        en_vol = _MYPULS_FILS.get(cle)
        if not en_vol or not en_vol["fil"].is_alive():
            # UN appel à la fois par période : un rechargement pendant la
            # lecture attend celle-ci, il n'en lance pas une seconde
            f = threading.Thread(target=_releve_mypuls, args=(du, au), daemon=True,
                                 name="infloww-liens-mypuls")
            en_vol = {"fil": f, "debut": maintenant}
            _MYPULS_FILS[cle] = en_vol
            f.start()
    f = en_vol["fil"]
    f.join(max(0.0, en_vol["debut"] + attente - time.time()))
    with _VERROU_MP:
        neuf = _MYPULS_CACHE.get(cle)
        ech = _MYPULS_ECHECS.get(cle)
        fini = not f.is_alive()
    if neuf is not None and neuf is not hit:
        return dict(neuf["v"])
    if fini:
        return _sans_mypuls(hit, (ech or {}).get("raison") or "lecture terminée sans résultat")
    return _sans_mypuls(hit, f"MyPuls ne répond pas encore (plus de {attente:g} s) : la lecture continue "
                             "en arrière-plan, rechargez la page dans une minute", en_cours=True)


# ─── une période : les clics US (GetMySocial) ────────────────────────────
def _cle_periode(du: str, au: str) -> str:
    return f"{du}|{au}"


def _us_periodes_cache() -> Dict[str, Any]:
    return _lire_json(US_PERIODES_FICHIER)


def _jour_de(ts: Any) -> str:
    """Le jour (heure de Paris) d'un horodatage."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Paris")).date().isoformat()
    except Exception:
        return ""


def us_periode_depuis_cache(ents: Mapping[str, Mapping[str, Any]], du: str, au: str,
                            cache: Optional[Mapping[str, Any]] = None, jour: Optional[str] = None,
                            maintenant: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """{clé: {us, etat, raison, note}} pour la période. etat : « ok » (relevé
    pris après la fin de la période, ou il y a moins de 2 h si elle finit
    aujourd'hui), « ancien » (relevé pris avant la fin de la période, ou sur
    d'autres liens), « rate », « absent ». Jamais un zéro inventé."""
    cache = _us_periodes_cache() if cache is None else cache
    jour = jour or _aujourdhui()
    maintenant = time.time() if maintenant is None else maintenant
    per = ((cache.get("periodes") or {}).get(_cle_periode(du, au)) or {})
    out: Dict[str, Dict[str, Any]] = {}
    for cle, e in ents.items():
        c = per.get(cle) or {}
        v = c.get("us")
        ids = sorted(str(i) for i in e.get("ids") or [])
        note = ""
        if c.get("rate"):
            etat = "rate"
            note = "US : dernier relevé raté" + (f", valeur du {_heure(c.get('quand'))}" if v is not None else "")
        elif v is None:
            etat = "absent"
        elif sorted(c.get("ids") or []) != ids:
            etat, note = "ancien", f"US : relevé du {_heure(c.get('quand'))}, avant un changement de liens"
        elif str(c.get("jour") or "") > au:
            etat = "ok"              # pris après la fin de la période : définitif
        elif jour == au and 0 <= maintenant - float(c.get("quand") or 0) < US_OUVERTE_FRAIS_S:
            etat = "ok"
        else:
            etat, note = "ancien", f"US : relevé du {_heure(c.get('quand'))}"
        out[cle] = {"us": None if v is None else int(v), "etat": etat, "jour": str(c.get("jour") or ""),
                    "raison": str(c.get("rate") or ""), "note": note}
    return out


def _a_mesurer_periode(ents: Mapping[str, Mapping[str, Any]], du: str, au: str,
                       cache: Mapping[str, Any], jour: str, maintenant: float) -> List[str]:
    etats = us_periode_depuis_cache(ents, du, au, cache, jour, maintenant)
    per = ((cache.get("periodes") or {}).get(_cle_periode(du, au)) or {})
    out = []
    for c in ents:
        if etats[c]["etat"] == "ok":
            continue
        p = per.get(c) or {}
        if etats[c]["etat"] == "rate":
            # un raté n'est retenté qu'après 10 min, et trois fois par jour au
            # plus : chaque essai coûte un appel du quota partagé
            if maintenant - float(p.get("essai") or 0) < US_REESSAI_S:
                continue
            if p.get("essais_jour") == jour and int(p.get("essais") or 0) >= US_PERIODE_ESSAIS_MAX:
                continue
        out.append(c)
    return out


def _periodes_du_jour(cache: Mapping[str, Any], jour: str) -> List[str]:
    return [str(x) for x in ((cache.get("jours") or {}).get(jour) or [])]


def _periode_admise(cache: Mapping[str, Any], jour: str, du: str, au: str) -> bool:
    """Une période déjà calculée aujourd'hui l'est encore ; une nouvelle
    seulement sous le plafond du jour."""
    deja = _periodes_du_jour(cache, jour)
    return _cle_periode(du, au) in deja or len(deja) < US_PERIODES_MAX_JOUR


def _budget_jour(nb_personnes: int) -> int:
    """Les appels GetMySocial permis par jour pour TOUTES les périodes."""
    return US_PERIODES_APPELS_PAR_PERSONNE * max(1, int(nb_personnes or 0))


def _appels_du_jour(cache: Mapping[str, Any], jour: str) -> int:
    try:
        return max(0, int((cache.get("appels") or {}).get(jour) or 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _verifier_zero(ids: List[str], du: str, au: str) -> Tuple[Optional[int], Optional[Dict[str, int]], str]:
    """Un relevé (0 clic, aucun pays) relu dans la réponse BRUTE de GetMySocial.

    gms rend (0, {}) aussi bien pour une période sans clic que pour une
    réponse qu'il n'a pas su lire (constaté le 26/09 : « NOTICE: stale: true »
    après le JSON). Les visites MyPuls ne tranchent PAS : une visite OF peut
    venir d'ailleurs que de GetMySocial (lien OF donné en direct, robot
    d'aperçu) — une personne à 1 clic OF et 0 clic GMS restait « ratée » et
    coûtait trois appels par jour, sans fin. La réponse brute tranche : un
    objet qui porte total_clicks est lu, 0 compris ; du texte non lu est un
    raté. (total, pays, "") ou (None, None, pourquoi)."""
    try:
        import gms
        res = gms.get_analytics_overview(du, au, link_ids=list(ids))
    except Exception as e:
        return None, None, f"vérification du 0 : {type(e).__name__} : {e}"[:160]
    if not isinstance(res, Mapping) or not res.get("ok"):
        err = str(res.get("error") or "") if isinstance(res, Mapping) else ""
        return None, None, ("vérification du 0 : " + (err or "pas de réponse"))[:160]
    d = res.get("data")
    if not isinstance(d, Mapping) or "total_clicks" not in d:
        return None, None, "GetMySocial a rendu un relevé illisible (0 clic, aucun pays, réponse non lue)"
    try:
        # la lecture de gms, telle quelle : les mêmes pays que le relevé normal
        tot, pays = gms._lire_analytics(dict(res, data=dict(d)))
    except Exception:
        tot, pays = None, None
    if pays is None:
        return None, None, "GetMySocial a rendu un relevé illisible (total_clicks non numérique)"
    return tot, pays, ""


def _elaguer(periodes: Mapping[str, Any], maintenant: float) -> Dict[str, Any]:
    """Les périodes plus touchées depuis US_PERIODES_GARDE_S sortent : le
    fichier ne grossit pas d'une entrée par période jamais revue."""
    out = {}
    for k, per in periodes.items():
        if not isinstance(per, Mapping):
            continue
        dernier = max([float((c or {}).get("quand") or 0) for c in per.values() if isinstance(c, Mapping)]
                      + [float((c or {}).get("essai") or 0) for c in per.values() if isinstance(c, Mapping)]
                      + [0.0])
        if maintenant - dernier < US_PERIODES_GARDE_S:
            out[k] = per
    return out


def releve_us_periode(ents: Mapping[str, Mapping[str, Any]], du: str, au: str) -> Dict[str, Any]:
    """Les clics US de la période, UN appel GetMySocial par personne (tous ses
    liens ensemble), pour les personnes qui n'ont pas de relevé valable.

    Un relevé (0 clic, aucun pays) est ambigu — c'est aussi ce que gms rend
    quand il n'a pas su lire la réponse : il est vérifié dans la réponse
    brute (_verifier_zero), un appel de plus. Chaque appel, vérification
    comprise, est décompté du budget du jour (_budget_jour).
    """
    if not _VERROU_US_P.acquire(blocking=False):
        return {"appels": 0, "rates": 0, "occupe": True}
    try:
        jour = _aujourdhui()
        maintenant = time.time()
        cache = _us_periodes_cache()
        cibles = _a_mesurer_periode(ents, du, au, cache, jour, maintenant)
        if not cibles:
            return {"appels": 0, "rates": 0}
        if not _periode_admise(cache, jour, du, au):
            return {"appels": 0, "rates": 0, "plafond": True}
        budget = _budget_jour(len(ents))
        faits = _appels_du_jour(cache, jour)
        if faits >= budget:
            return {"appels": 0, "rates": 0, "budget": budget}
        pause = _pause_gms()
        if pause > 0:
            return {"appels": 0, "rates": 0, "pause": pause}
        import gms
        cp = _cle_periode(du, au)
        deja = _periodes_du_jour(cache, jour)
        # la période compte dans le plafond dès qu'on appelle GetMySocial pour
        # elle, que les appels réussissent ou non : c'est l'appel qui coûte
        periodes = _elaguer(dict(cache.get("periodes") or {}), maintenant)
        per = dict(periodes.get(cp) or {})
        cache = {"jours": {jour: deja + ([cp] if cp not in deja else [])},
                 "appels": {jour: faits}, "periodes": periodes, "maj": maintenant}
        rates = appels = mesures = 0
        for i, cle in enumerate(cibles):
            if i and _pause_gms():
                break                 # quota tombé en route : les suivants restent à relever
            if faits >= budget:
                break                 # budget du jour atteint : idem, jusqu'à demain
            ids = sorted(str(x) for x in ents[cle].get("ids") or [])
            raison = ""
            appels += 1
            faits += 1
            try:
                tot, pays = gms.analytics_for_links(ids, du, au)
            except Exception as e:
                tot, pays, raison = None, None, f"{type(e).__name__} : {e}"[:160]
            if pays is not None and not tot and not pays:
                if faits >= budget:
                    pays, raison = None, "relevé à 0 clic non vérifié : budget GetMySocial du jour atteint"
                else:
                    appels += 1
                    faits += 1
                    tot, pays, raison = _verifier_zero(ids, du, au)
            mesures += 1
            c = dict(per.get(cle) or {})
            c["essai"] = time.time()
            if pays is None:
                rates += 1
                if not raison and _pause_gms():
                    raison = "quota GetMySocial épuisé" + _reprise_gms()
                n = int(c.get("essais") or 0) if c.get("essais_jour") == jour else 0
                c.update(rate=f"{jour} : " + (raison or "GetMySocial n'a pas rendu de relevé"),
                         essais=n + 1, essais_jour=jour)
            else:
                c.update(us=int((pays or {}).get("US") or 0), ids=ids, quand=time.time(), jour=jour,
                         rate="", essais=0)
            per[cle] = c
            cache["periodes"] = dict(cache["periodes"], **{cp: per})
            cache["appels"] = {jour: faits}
            safe_json.write(US_PERIODES_FICHIER, cache)
            if i + 1 < len(cibles):
                _dormir_us(US_PAUSE_S)
        return {"appels": appels, "rates": rates, "reportes": len(cibles) - mesures,
                "budget": budget if faits >= budget and mesures < len(cibles) else 0}
    finally:
        _VERROU_US_P.release()


def _lancer_us_periode(ents: Mapping[str, Mapping[str, Any]], du: str, au: str
                       ) -> Optional[threading.Thread]:
    """En arrière-plan, un seul calcul à la fois : une autre période demandée
    pendant ce temps sera calculée au prochain affichage."""
    if not US_EN_FOND:
        releve_us_periode(ents, du, au)
        return None
    with _VERROU:
        f = _FIL_US_P.get("fil")
        if f is not None and f.is_alive():
            return f
        f = threading.Thread(target=releve_us_periode, args=(dict(ents), du, au),
                             daemon=True, name="infloww-liens-us-periode")
        _FIL_US_P["fil"] = f
        f.start()
        return f


def _us_periode_pour_la_page(ents: Mapping[str, Mapping[str, Any]], du: str, au: str) -> Dict[str, Any]:
    """Lance ce qui manque, sans l'attendre : les chiffres MyPuls de la période
    s'affichent tout de suite, les clics US suivent. Rend ce que la page doit
    dire (plafond, budget, pause, calcul en cours)."""
    jour = _aujourdhui()
    cache = _us_periodes_cache()
    if not _a_mesurer_periode(ents, du, au, cache, jour, time.time()):
        return {}
    if not _periode_admise(cache, jour, du, au):
        return {"plafond": True, "calculees": _periodes_du_jour(cache, jour)}
    budget = _budget_jour(len(ents))
    if _appels_du_jour(cache, jour) >= budget:
        return {"budget": budget}
    if _pause_gms():
        return {"pause": "quota du jour épuisé" + _reprise_gms()}
    _lancer_us_periode(ents, du, au)
    return {"en_cours": True}


# ─── le tableau ──────────────────────────────────────────────────────────
def _somme(liens: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Clics, subs, CVR et $ / sub de liens Infloww. Le net n'est PAS rendu :
    il ne sert qu'au $ / sub, et ce qui n'est pas dans la ligne ne peut pas
    finir affiché par mégarde."""
    if not liens:
        return {"clics": None, "subs": None, "cvr": None, "par_sub": None, "sans_clics": 0}
    connus = [x for x in liens if x.get("clics") is not None]
    clics = sum(int(x["clics"]) for x in connus) if connus else None
    subs = sum(int(x.get("abonnes") or 0) for x in liens)
    net = sum(int(x.get("net") or 0) for x in liens)
    # le CVR sur les seuls liens dont Infloww donne les clics : les subs d'un
    # lien sans clics connus, divisés par les clics des autres, le gonflaient
    subs_connus = sum(int(x.get("abonnes") or 0) for x in connus)
    return {"clics": clics, "subs": subs, "sans_clics": len(liens) - len(connus),
            # 0 clic : pas de pourcentage (et non 0 %, qui voudrait dire
            # « aucun des clics n'a converti »)
            "cvr": (subs_connus * 100.0 / clics) if clics else None,
            # 0 sub : un sub ne « revient » à rien, ce n'est pas 0 $
            "par_sub": (net / 100.0 / subs) if subs else None}


def _resume_infloww(x: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": str(x.get("id") or ""), "nom": str(x.get("nom") or ""), "code": _code_infloww(x),
            "desactive": bool(x.get("termine"))}


def _cle_nom(nom: Any) -> Tuple[Tuple[int, Any], ...]:
    """Ordre alphabétique « naturel », sans accents ni casse : les numéros
    comptent comme des nombres. Sans ça, VA 10 Noum passerait avant VA 2 Noum
    (le propriétaire veut VA 1 à VA 6 dans l'ordre, pas rangés par subs)."""
    t = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().casefold()
    return tuple((0, int(p)) if p.isdigit() else (1, p.strip())
                 for p in re.split(r"(\d+)", t) if p.strip())


def _ordre_defaut(x: Mapping[str, Any]):
    # alphabétique : c'est l'ordre voulu par le propriétaire (26/09), pour la
    # page comme pour Discord ; le lien SPAM suit ainsi la personne
    return (_cle_nom(x.get("nom")), -int(x.get("subs") or 0))


def construire(liens_infloww: List[Any], liens_gms_: List[Any],
               us: Optional[Mapping[str, Mapping[str, Any]]] = None, lu_a: Optional[float] = None,
               tronque: Optional[List[str]] = None, doublons: int = 0, depuis: str = "",
               repli_gms: str = "", erreur: str = "", us_pause: str = "",
               source: str = "Infloww", illisibles: int = 0,
               periode: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Le tableau par personne, à partir des liens normalisés d'infloww
    (_lien_norm), des liens GetMySocial de l'espace et des clics US relevés.

    `source` = « MyPuls » pour une période : mêmes règles (liens DISTINCTS
    par personne, un code partagé compté une fois au total), les liens étant
    ceux que _lire_mypuls a mis à la même forme. `periode` : ce que la page
    doit en dire (bornes, lecture MyPuls, clics US)."""
    us = us or {}
    inf = [x for x in liens_infloww if isinstance(x, Mapping)]
    par_code: Dict[str, List[Mapping[str, Any]]] = {}
    for x in inf:
        c = _code_infloww(x)
        if c:
            par_code.setdefault(c, []).append(x)
    gms_propres = [l for l in liens_gms_ if isinstance(l, Mapping) and l.get("id")]
    par_id = {str(l["id"]): l for l in gms_propres}
    ents, gms_sans_id = entites(liens_gms_)

    lignes: List[Dict[str, Any]] = []
    rattaches: Dict[str, Mapping[str, Any]] = {}    # id Infloww -> lien, une fois
    qui: Dict[str, List[str]] = {}                  # id Infloww -> personnes
    for cle, e in ents.items():
        siens: Dict[str, Mapping[str, Any]] = {}    # DISTINCTS : 4 liens GMS -> c85 une fois
        introuvables: List[Dict[str, str]] = []
        for gid in e["ids"]:
            l = par_id.get(str(gid)) or {}
            code, raison = code_de_l_url(l.get("url"))
            if code and not par_code.get(code):
                raison = f"code c{code} absent des liens de suivi {_de(source)}"
            if raison:
                introuvables.append({"nom": nom_gms(l), "code": code, "raison": raison})
                continue
            for x in par_code[code]:
                siens[str(x.get("id") or "")] = x
        for iid, x in siens.items():
            rattaches[iid] = x
            qui.setdefault(iid, []).append(cle)
        u = us.get(cle) or {}
        ligne = {"cle": cle, "nom": cle, "spam": bool(e.get("spam")), "nb_gms": len(e["ids"]),
                 "infloww": sorted((_resume_infloww(x) for x in siens.values()),
                                   key=lambda r: (len(r["code"]), r["code"])),
                 "introuvables": introuvables,
                 "us": u.get("us"), "us_etat": u.get("etat") or "absent",
                 "us_jour": u.get("jour") or "", "us_raison": u.get("raison") or "",
                 "us_note": u.get("note") or ""}
        ligne.update(_somme(list(siens.values())))
        lignes.append(ligne)

    comptes = list(rattaches.values())
    T = _somme(comptes)
    T.pop("sans_clics", None)
    us_connus = [x["us"] for x in lignes if x.get("us") is not None]
    T.update(personnes=len(lignes), liens_infloww=len(comptes),
             us=sum(us_connus) if us_connus else None,
             us_manquants=len(lignes) - len(us_connus))
    hors = [x for x in inf if str(x.get("id") or "") not in rattaches]
    hors_lignes = []
    for x in hors:
        r = _resume_infloww(x)
        r.update(_somme([x]))
        hors_lignes.append(r)
    partages = [{"code": _code_infloww(rattaches[i]), "nom": str(rattaches[i].get("nom") or ""),
                 "personnes": sorted(p)} for i, p in qui.items() if len(p) > 1]
    maj = max([int(x.get("maj") or 0) for x in inf] or [0])
    return {
        "creatrice": CREATRICE, "equipe": EQUIPE_GMS, "equipe_nom": NOM_EQUIPE,
        "source": source, "periode": dict(periode or {}),
        "erreur": str(erreur or ""), "repli_gms": str(repli_gms or ""),
        # GetMySocial a coupé pour la journée : les clics US attendent la reprise
        "us_pause": str(us_pause or ""),
        "lu_a": float(lu_a or time.time()),
        "lignes": sorted(lignes, key=_ordre_defaut), "totaux": T,
        "hors_gms": sorted(hors_lignes, key=_ordre_defaut),
        "partages": sorted(partages, key=lambda p: p["code"]),
        "nb_gms": len(liens_gms_), "gms_sans_id": gms_sans_id,
        "introuvables": sum(len(x["introuvables"]) for x in lignes),
        "nb_infloww": len(inf),
        # une ligne que l'API rend sous une autre forme qu'un objet : comptée,
        # jamais avalée sans trace
        "illisibles": len(liens_infloww) - len(inf) + int(illisibles or 0),
        "sans_clics": sum(1 for x in comptes if x.get("clics") is None),
        "tronque": list(tronque or []), "doublons": int(doublons or 0), "depuis": depuis,
        # quand Infloww a rafraîchi ses compteurs pour la dernière fois
        "maj_infloww": (maj / 1000.0) if maj else None,
    }


def _de(source: str) -> str:
    return "d'Infloww" if source == "Infloww" else f"de {source}"


def _vide(erreur: str, periode: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    if periode:
        return construire([], [], erreur=erreur, source="MyPuls",
                          periode={"du": periode[0], "au": periode[1]})
    return construire([], [], erreur=erreur)


def tableau(us: str = "page") -> Dict[str, Any]:
    """Le tableau par personne. `us` : « page » (valeurs gardées, relevé en
    arrière-plan), « calcul » (relevé sur place, pour le démon), « cache »
    (aucun appel GetMySocial d'analyse). Ne lève jamais."""
    g = liens_gms()
    i = _infloww()
    ents, _ = entites(g["liens"])
    erreur = i.get("erreur") or ""
    if not g["liens"]:
        erreur = erreur or (f"GetMySocial n'a pas répondu ({g['repli']}) et le site n'a "
                            f"aucune liste de secours pour « {NOM_EQUIPE} »")
    try:
        if us == "calcul":
            releve_us(ents)
        elif us == "page":
            _us_pour_la_page(ents)
    except Exception as e:  # les clics US ne font pas tomber la page
        print(f"[infloww-liens] clics US : {type(e).__name__}: {e}", flush=True)
    return construire(i.get("liens") or [], g["liens"], us=us_depuis_cache(ents),
                      lu_a=i.get("lu_a"), tronque=i.get("tronque"), doublons=i.get("doublons") or 0,
                      depuis=str(i.get("depuis") or ""), repli_gms=g["repli"], erreur=erreur,
                      us_pause=("quota du jour épuisé" + _reprise_gms()) if _pause_gms() else "")


def tableau_periode(du: str, au: str, us: str = "page") -> Dict[str, Any]:
    """Le tableau par personne sur une période (bornes incluses, AAAA-MM-JJ,
    déjà validées par periode_des_args) : clics OF, subs et gains de MyPuls,
    clics US de GetMySocial sur les mêmes jours. `us` : « page » (calcul en
    arrière-plan), « calcul » (sur place), « cache » (aucun appel). Ne lève
    jamais."""
    g = liens_gms()
    m = _mypuls_periode(du, au)
    ents, _ = entites(g["liens"])
    erreur = m.get("erreur") or ""
    if not g["liens"]:
        erreur = erreur or (f"GetMySocial n'a pas répondu ({g['repli']}) et le site n'a "
                            f"aucune liste de secours pour « {NOM_EQUIPE} »")
    per: Dict[str, Any] = {"du": du, "au": au, "perime": m.get("perime") or "",
                           "periode_mypuls": m.get("periode_mypuls") or {},
                           "devise": m.get("devise") or "", "doublons": int(m.get("doublons") or 0),
                           "champs_manquants": int(m.get("champs_manquants") or 0),
                           # MyPuls n'a pas répondu dans le temps que la page lui laisse
                           "mypuls_en_cours": bool(m.get("en_cours"))}
    commun = dict(lu_a=m.get("lu_a"), tronque=m.get("tronque"), repli_gms=g["repli"], erreur=erreur,
                  source="MyPuls", illisibles=int(m.get("illisibles") or 0))
    liens = m.get("liens") or []
    if not erreur:
        try:
            if us == "calcul":
                r = releve_us_periode(ents, du, au)
                if r.get("plafond"):
                    per["us_info"] = {"plafond": True,
                                      "calculees": _periodes_du_jour(_us_periodes_cache(), _aujourdhui())}
                else:
                    per["us_info"] = {"budget": r["budget"]} if r.get("budget") else {}
            elif us == "page":
                per["us_info"] = _us_periode_pour_la_page(ents, du, au)
        except Exception as e:  # les clics US ne font pas tomber la page
            print(f"[infloww-liens] clics US de la période : {type(e).__name__}: {e}", flush=True)
    info = per.get("us_info") or {}
    if _pause_gms() and not info.get("plafond") and not info.get("budget"):
        per["us_info"] = dict(per.get("us_info") or {}, pause="quota du jour épuisé" + _reprise_gms())
    return construire(liens, g["liens"], us=us_periode_depuis_cache(ents, du, au), periode=per, **commun)


# ─── formats ─────────────────────────────────────────────────────────────
def _nb(n: Any, sep: str = "\u202f") -> str:
    if n is None:
        return "—"
    return f"{int(n):,}".replace(",", sep)


def _dec(v: Any, k: int = 2, sep: str = "\u202f") -> str:
    if v is None:
        return "—"
    return f"{float(v):,.{k}f}".replace(",", sep).replace(".", ",")


def _pct(v: Any, sep: str = "\u202f") -> str:
    return "—" if v is None else _dec(v, 2, sep) + "\u00a0%"


def _dollars(v: Any, sep: str = "\u202f") -> str:
    return "—" if v is None else _dec(v, 2, sep) + "\u00a0$"


def _heure(ts: Optional[float]) -> str:
    """26/09 à 14h05, heure de Paris : le VPS tourne en UTC."""
    if not ts:
        return "?"
    try:
        from zoneinfo import ZoneInfo
        d = dt.datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Paris"))
    except Exception:
        d = dt.datetime.fromtimestamp(float(ts))
    return d.strftime("%d/%m à %Hh%M")


def _jour_court(iso: str) -> str:
    try:
        return dt.date.fromisoformat(str(iso)).strftime("%d/%m")
    except Exception:
        return "?"


def _jour_long(iso: str) -> str:
    try:
        return dt.date.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except Exception:
        return "?"


# ─── Discord : le contenu ────────────────────────────────────────────────
# Un caractère de mise en forme précédé d'une barre oblique inverse est pris
# littéralement par Discord. Sans ça, un nom « **VA** » ou « a_b_c » cassait
# le gras de toute la ligne, « [x](y) » devenait un lien et « <@1> » une
# mention. Seuls ces caractères-là : le nom n'est jamais en début de ligne
# (# titre, - liste, > citation n'y jouent pas), et une barre devant autre
# chose risquerait de s'afficher telle quelle sur un client mobile.
_MD = re.compile(r"([\\*_~`|\[\]<>])")


def _md(nom: Any, maxi: int = NOM_DISCORD_MAX) -> str:
    s = " ".join(str(nom or "").split()) or "(sans nom)"
    if len(s) > maxi:
        s = s[:maxi - 1] + "…"
    s = _MD.sub(r"\\\1", s)
    # une mention dans un embed ne notifie pas, et allowed_mentions bloque le
    # reste ; mais « @everyone » s'afficherait quand même comme une mention.
    # L'espace de largeur nulle la rend inerte à l'œil aussi.
    return s.replace("@", "@\u200b")


# Les seuils du propriétaire (26/09) : une CVR de 10 % est « good », un sub
# qui rapporte 2 $ aussi. Au-dessus, vert, de plus en plus foncé à mesure que
# ça monte ; en dessous, orange de plus en plus soutenu, puis rouge sous la
# moitié du seuil. Un seul barème pour la page et pour Discord.
SEUIL_CVR = 10.0
SEUIL_PAR_SUB = 2.0
_PALIERS = ((1.5, "v3"), (1.25, "v2"), (1.0, "v1"), (0.75, "o1"), (0.5, "o2"))


def niveau(v: Any, seuil: float) -> str:
    """v3/v2/v1 (vert, du plus foncé au plus clair), o1/o2 (orange), r
    (rouge) ; "" si la valeur manque — pas de couleur sur un « — »."""
    f = _f_ou_none(v)
    if f is None:
        return ""
    for mult, nom in _PALIERS:
        if f >= seuil * mult:
            return nom
    return "r"


def _f_ou_none(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _pastille(texte: str, niv: str) -> str:
    return f'<span class="nv {niv}">{texte}</span>' if niv else texte


def _rond(niv: str) -> str:
    return {"v": "🟢", "o": "🟠", "r": "🔴"}.get(niv[:1], "")


def _ligne_discord(rang: int, x: Mapping[str, Any]) -> str:
    """Deux lignes courtes par personne, lisibles sur un téléphone : un
    tableau en bloc de code, lui, débordait et se lisait en faisant défiler.
    Pas de @ : le propriétaire n'a pas encore choisi qui mentionner."""
    s = "\u00a0"
    tete = f"**{rang}. {_md(x.get('nom'))}**\n🇺🇸{s}{_nb(x.get('us'), s)} US · "
    if not x.get("infloww"):
        return tete + "lien Infloww introuvable"
    return (tete + f"{_nb(x.get('clics'), s)} clics OF → **{_nb(x.get('subs'), s)} subs** · "
            f"{_rond(niveau(x.get('cvr'), SEUIL_CVR))}{_pct(x.get('cvr'), s)} · "
            f"{_rond(niveau(x.get('par_sub'), SEUIL_PAR_SUB))}**{_dollars(x.get('par_sub'), s)}**{s}/{s}sub")


def _taille_embed(e: Mapping[str, Any]) -> int:
    """Ce que Discord compte dans ses 6 000 caractères par message."""
    n = len(e.get("title") or "") + len(e.get("description") or "")
    n += len((e.get("footer") or {}).get("text") or "")
    n += len((e.get("author") or {}).get("name") or "")
    for f in e.get("fields") or []:
        n += len(f.get("name") or "") + len(f.get("value") or "")
    return n


def messages_discord(t: Mapping[str, Any], url: str = "") -> List[Dict[str, Any]]:
    """Les charges utiles des messages, dans l'ordre : un embed par message.

    Une ligne par personne, classées par subs décroissants puis clics. Le
    lien de la page est en tête du premier. Aucun montant de gains, nulle part.
    """
    s = "\u00a0"
    lignes = sorted(t.get("lignes") or [], key=_ordre_defaut)
    T = t.get("totaux") or {}
    tete: List[str] = []
    if url:
        tete.append(f"🔗 **[Voir le tableau complet]({url})** — trié comme on veut")
    if t.get("erreur"):
        tete.append(f"⚠️ Lecture impossible : {_md(t['erreur'], 1500)}")
    else:
        tete.append(f"**{_nb(len(lignes), s)} personnes** · GetMySocial « {NOM_EQUIPE} »\n"
                    f"🇺🇸{s}{_nb(T.get('us'), s)} US · {_nb(T.get('clics'), s)} clics OF → "
                    f"**{_nb(T.get('subs'), s)} subs** · {_pct(T.get('cvr'), s)} · "
                    f"**{_dollars(T.get('par_sub'), s)}**{s}/{s}sub en moyenne")
    if t.get("repli_gms"):
        tete.append("⚠️ GetMySocial n'a pas répondu : liste des liens reprise du cache du site")
    if t.get("tronque"):
        tete.append("⚠️ Liste Infloww INCOMPLÈTE : pagination arrêtée sur "
                    + _md(", ".join(str(x) for x in t["tronque"]), 500))
    if t.get("illisibles"):
        tete.append(f"⚠️ {t['illisibles']} ligne(s) d'Infloww illisible(s), non comptée(s)")
    if t.get("introuvables"):
        tete.append(f"⚠️ {t['introuvables']} lien(s) GetMySocial sans lien Infloww en face")
    tete_txt = "\n".join(tete) + "\n\n"

    corps = [_ligne_discord(i, x) for i, x in enumerate(lignes, start=1)]
    if not corps and not t.get("erreur"):
        corps = ["_Aucune personne dans l'espace GetMySocial._"]

    # remplissage page par page ; la première porte l'en-tête
    pages: List[List[str]] = [[]]
    taille = len(tete_txt)
    for c in corps:
        c = c[:DESCRIPTION_MAX - 50]
        if pages[-1] and taille + len(c) + 1 > DESCRIPTION_MAX:
            pages.append([])
            taille = 0
        pages[-1].append(c)
        taille += len(c) + 1

    nb_hors = len(t.get("hors_gms") or [])
    hors = (f"{_nb(nb_hors, s)} lien{'s' if nb_hors > 1 else ''} Infloww hors GetMySocial, non compté"
            f"{'s' if nb_hors > 1 else ''}" if nb_hors else "aucun lien Infloww hors GetMySocial")
    pied = (f"Source : Infloww (toutes les 2 h) + GetMySocial « {NOM_EQUIPE} » · lu le "
            f"{_heure(t.get('lu_a'))} (heure de Paris) · {hors} · $ / sub = gains nets ÷ subs")
    out: List[Dict[str, Any]] = []
    n = len(pages)
    for i, p in enumerate(pages, start=1):
        desc = (tete_txt if i == 1 else "") + "\n".join(p)
        e: Dict[str, Any] = {
            "title": f"📊 Liens de suivi · {NOM_AFFICHE}" + (f" ({i}/{n})" if n > 1 else ""),
            "color": COULEUR, "description": desc[:4096],
            "footer": {"text": (f"page {i}/{n} · " if n > 1 else "") + pied}}
        if url:
            e["url"] = url
        out.append({"embeds": [e],
                    # personne n'est notifié, quoi qu'un nom de lien contienne
                    "allowed_mentions": {"parse": []}})
    return out


# ─── Discord : l'envoi ───────────────────────────────────────────────────
def discord_actif() -> bool:
    """L'interrupteur du salon. Absent, illisible ou autre chose que `true` :
    coupé. Le propriétaire : « le format du salon, on fait après »."""
    return _lire_json(CONFIG_FICHIER).get("discord_actif") is True


def jeton() -> str:
    for p in JETON_FICHIERS:
        try:
            v = Path(p).read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


def _app_du_jeton(tok: str) -> str:
    """L'identifiant d'application inscrit dans un jeton de bot (sa première
    partie, en base64). Sert à refuser le jeton d'un AUTRE bot déposé par
    erreur : sinon Siri ou Jarvis posterait à la place de Bixby."""
    try:
        a = tok.split(".", 1)[0]
        v = base64.urlsafe_b64decode(a + "=" * (-len(a) % 4)).decode("ascii")
        return v if v.isdigit() else ""
    except Exception:
        return ""


def _dormir(s: float) -> None:
    time.sleep(s)


def _requete(methode: str, chemin: str, corps: Optional[Dict[str, Any]], tok: str
             ) -> Tuple[int, Any, Mapping[str, str]]:
    """UN appel HTTP à Discord (bouchonné dans les tests). Ne lève pas."""
    import requests
    try:
        r = requests.request(methode, API_DISCORD + chemin, json=corps, timeout=20, headers={
            "Authorization": f"Bot {tok}", "User-Agent": "DiscordBot (youl4b-infloww, 1.0)"})
    except Exception as e:
        return 0, {"message": f"{type(e).__name__} : {e}"[:200]}, {}
    try:
        rep = r.json() if r.text else {}
    except Exception:
        rep = {"message": r.text[:200]}
    return r.status_code, rep, dict(r.headers)


def _api(methode: str, chemin: str, corps: Optional[Dict[str, Any]] = None, tok: str = ""
         ) -> Tuple[int, Any]:
    """Un appel qui respecte le 429 de Discord : on attend `retry_after`, puis
    on recommence. Réessayer tout de suite prolongeait la pénalité."""
    for _ in range(5):
        code, rep, entetes = _requete(methode, chemin, corps, tok)
        if code != 429:
            return code, rep
        try:
            attente = float((rep or {}).get("retry_after") or entetes.get("Retry-After") or 1)
        except Exception:
            attente = 1.0
        _dormir(min(60.0, max(0.5, attente)) + 0.2)
    return 429, {"message": "limite Discord (429) malgré les reprises"}


def _msg(rep: Any) -> str:
    return str((rep or {}).get("message") if isinstance(rep, dict) else rep or "")[:120]


# ─── Discord : l'état et le rafraîchissement ─────────────────────────────
def _etat() -> Dict[str, Any]:
    return _lire_json(ETAT_FICHIER)


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write(ETAT_FICHIER, d)


def _ids(etat: Mapping[str, Any]) -> List[str]:
    # les messages d'un autre salon (constante changée) ne se modifient pas ici
    if str(etat.get("salon") or SALON) != SALON:
        return []
    return [str(x) for x in etat.get("messages") or [] if str(x).isdigit()]


def a_rafraichir(maintenant: Optional[float] = None) -> bool:
    """Envoi coupé : jamais. Sinon : jamais posté, ou dernier passage réussi
    plus vieux que REFRESH_S. Un passage raté ne compte pas : le démon
    réessaie au tour suivant."""
    if not discord_actif():
        return False
    etat = _etat()
    if not _ids(etat):
        return True
    return (maintenant or time.time()) - float(etat.get("vu") or 0) >= REFRESH_S


def _noter(etat: Dict[str, Any], statut: str, erreur: str = "") -> str:
    etat.update(statut=statut, erreur=erreur, essai=time.time(), salon=SALON)
    _ecrire(etat)
    return statut


def rafraichir() -> str:
    """Poste, ou modifie sur place, les messages du salon. Rend un statut
    lisible. Ne lève jamais."""
    with _VERROU:
        try:
            return _rafraichir()
        except Exception as e:
            statut = f"échec inattendu : {type(e).__name__} : {e}"
            try:
                return _noter(_etat(), statut, statut)
            except Exception:
                return statut


def _rafraichir() -> str:
    etat = _etat()
    if not discord_actif():
        return _noter(etat, "envoi Discord coupé (« discord_actif » absent ou faux dans "
                            "data/infloww_liens_config.json) : rien n'est posté", "envoi coupé")
    ids = _ids(etat)
    tok = jeton()
    if not tok:
        return _noter(etat, "jeton de Bixby absent (data/bixby_bot_token ou "
                            "~/.config/bixby_bot_token) : rien n'est posté", "jeton absent")
    app = _app_du_jeton(tok)
    if app and app != BOT_APP:
        return _noter(etat, f"le jeton déposé est celui de l'application {app}, pas de Bixby "
                            f"({BOT_APP}) : rien n'est posté", "jeton d'un autre bot")
    t = tableau(us="calcul")
    if t.get("erreur"):
        # on ne remplace pas un tableau juste par un message d'erreur : les
        # derniers chiffres restent affichés, avec leur heure de lecture
        return _noter(etat, f"lecture impossible ({t['erreur']}) : les {len(ids)} message(s) "
                            "déjà posté(s) sont gardés tels quels", str(t["erreur"])[:300])
    charges = messages_discord(t, url_page())

    a_retirer = [str(x) for x in etat.get("a_retirer") or [] if str(x).isdigit()]
    neufs: List[str] = []
    ennuis: List[str] = []
    rupture = False
    for i, charge in enumerate(charges):
        if i < len(ids) and not rupture:
            code, rep = _api("PATCH", f"/channels/{SALON}/messages/{ids[i]}", charge, tok)
            if code == 200:
                neufs.append(ids[i])
                continue
            if code != 404:
                # panne passagère, droit manquant : le message existe peut-être
                # encore, en reposter un ferait un doublon. On le garde.
                neufs.append(ids[i])
                ennuis.append(f"page {i + 1} non modifiée (HTTP {code} {_msg(rep)})")
                continue
            # supprimé à la main : on reposte À PARTIR d'ici, et on retire nos
            # messages suivants, sinon la page 1 se retrouvait sous la page 2
            rupture = True
            a_retirer += ids[i + 1:]
        code, rep = _api("POST", f"/channels/{SALON}/messages", charge, tok)
        if code in (200, 201) and isinstance(rep, dict) and rep.get("id"):
            neufs.append(str(rep["id"]))
        else:
            ennuis.append(f"page {i + 1} non postée (HTTP {code} {_msg(rep)})")
    if not rupture:
        # moins de pages qu'avant : nos messages en trop diraient des chiffres faux
        a_retirer += ids[len(charges):]

    reste: List[str] = []
    for mid in dict.fromkeys(a_retirer):
        if mid in neufs:
            continue
        code, rep = _api("DELETE", f"/channels/{SALON}/messages/{mid}", None, tok)
        if code not in (200, 204, 404):
            reste.append(mid)       # réessayé au prochain passage, pas oublié
            ennuis.append(f"message {mid} non retiré (HTTP {code} {_msg(rep)})")

    nb_p, nb_h = len(t.get("lignes") or []), len(t.get("hors_gms") or [])
    etat.update(messages=neufs, a_retirer=reste, pages=len(charges), personnes=nb_p,
                hors_gms=nb_h, lu_a=t.get("lu_a"))
    if ennuis:
        return _noter(etat, f"{len(neufs)} message(s) à jour, avec des ennuis : "
                            + " ; ".join(ennuis), " ; ".join(ennuis)[:500])
    etat["vu"] = time.time()
    return _noter(etat, f"{len(neufs)} message(s) à jour ({nb_p} personnes, "
                        f"{nb_h} liens Infloww hors GetMySocial non comptés)")


# ─── la page ─────────────────────────────────────────────────────────────
def cle_page() -> str:
    """La clé qui ouvre la page sans compte. Créée au premier appel."""
    with _VERROU:
        try:
            v = CLE_FICHIER.read_text(encoding="utf-8").strip()
            if len(v) >= 20:
                return v
        except Exception:
            pass
        v = secrets.token_urlsafe(24)
        if not safe_json.write_text(CLE_FICHIER, v):
            raise OSError(f"clé de la page non écrite ({CLE_FICHIER})")
        try:
            CLE_FICHIER.chmod(0o600)
        except Exception:
            pass
        return v


def url_page() -> str:
    return f"{SITE}/infloww/liens?k={cle_page()}"


def _e(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _tri_valide(tri: Any, sens: Any) -> Tuple[str, str]:
    tri = str(tri or "")
    if tri not in TRIS:
        return "nom", "asc"
    sens = str(sens or "")
    if sens not in SENS:
        sens = "asc" if tri == "nom" else "desc"
    return tri, sens


def trier(lignes: List[Mapping[str, Any]], tri: str = "nom", sens: str = "asc"
          ) -> List[Mapping[str, Any]]:
    """Trie ; une valeur absente (lien Infloww introuvable, 0 clic, 0 sub,
    clics US pas encore relevés) va toujours en bas, dans un sens comme dans
    l'autre."""
    tri, sens = _tri_valide(tri, sens)
    base = sorted(lignes, key=_ordre_defaut)
    avec = [x for x in base if x.get(tri) is not None]
    sans = [x for x in base if x.get(tri) is None]
    if tri == "nom":
        cle = lambda x: _cle_nom(x.get("nom"))  # noqa: E731
    else:
        cle = lambda x: float(x.get(tri) or 0)  # noqa: E731
    return sorted(avec, key=cle, reverse=(sens == "desc")) + sans


def _adresse(*paires: Tuple[str, Any]) -> str:
    """« ?a=1&amp;b=2 », prête pour un href. Paramètres vides omis, valeurs
    encodées (la clé vient de l'adresse : elle ne doit rien pouvoir casser),
    ordre fixe tri, sens, du, au, k. Rien du tout : « ? », la page nue."""
    from urllib.parse import quote
    q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in paires if v)
    return _e("?" + q)


def _lien_page(tri: str, sens: str, cle: str, du: str = "", au: str = "") -> str:
    """Un lien vers la page, tri gardé (omis quand c'est celui par défaut)."""
    defaut = (tri, sens) == ("nom", "asc")
    return _adresse(("tri", "" if defaut else tri), ("sens", "" if defaut else sens),
                    ("du", du), ("au", au), ("k", cle))


def _lien_tri(col: str, tri: str, sens: str, cle: str, du: str = "", au: str = "") -> str:
    if col == tri:
        nouveau = "asc" if sens == "desc" else "desc"
    else:
        nouveau = "asc" if col == "nom" else "desc"
    # la période et la clé suivent : trier ne ramène pas à « depuis toujours »,
    # et un VA sans compte ne perd pas l'accès
    return _adresse(("tri", col), ("sens", nouveau), ("du", du), ("au", au), ("k", cle))


def _detail_personne(x: Mapping[str, Any], source: str = "Infloww") -> str:
    """Sous le nom, en petit : les liens de suivi comptés, et ce qui manque."""
    d: List[str] = []
    for r in x.get("infloww") or []:
        s = f'{_e(r.get("nom")) or "(sans nom)"} · c{_e(r.get("code"))}'
        if r.get("desactive"):
            s += ' · <span class="off">désactivé</span>'
        d.append(f"<span>{s}</span>")
    for r in x.get("introuvables") or []:
        nom = f"« {_e(r.get('nom'))} » : " if r.get("nom") else ""
        d.append(f'<span class="manque">{nom}lien {_e(source)} introuvable — {_e(r.get("raison"))}</span>')
    if int(x.get("nb_gms") or 0) > 1:
        d.append(f"<span>{_nb(x['nb_gms'])} liens GetMySocial</span>")
    # Clics US : la date seulement quand elle n'est pas celle du jour. « Pas
    # encore relevé » n'est dit qu'une fois, en tête : répété sur vingt-huit
    # lignes, il doublait la hauteur du tableau sur un téléphone.
    etat = x.get("us_etat")
    if x.get("us_note"):
        # une période : la note est déjà écrite (heure du relevé, raté)
        cl = ' class="manque"' if etat == "rate" else ""
        d.append(f'<span{cl}>{_e(x["us_note"])}</span>')
    elif etat == "ancien":
        d.append(f'<span>US : relevé du {_e(_jour_court(x.get("us_jour")))}</span>')
    elif etat == "rate":
        d.append('<span class="manque">US : dernier relevé raté'
                 + (f', valeur du {_e(_jour_court(x.get("us_jour")))}' if x.get("us") is not None
                    else "") + "</span>")
    return f'<div class="det">{"<br>".join(d)}</div>' if d else ""


def _table_personnes(lignes: List[Mapping[str, Any]], T: Mapping[str, Any], tri: str, sens: str,
                     cle: str, du: str = "", au: str = "", source: str = "Infloww") -> str:
    cols = (("nom", "Personne", "nom"), ("us", "Clics US", "n"), ("clics", "Clics OF", "n"),
            ("subs", "Subs", "n"), ("cvr", "CVR", "n"), ("par_sub", "$\u00a0/\u00a0sub", "n"))
    th = []
    for col, titre, cl in cols:
        fl = (" ▾" if sens == "desc" else " ▴") if col == tri else ""
        on = " on" if col == tri else ""
        th.append(f'<th class="{cl}{on}"><a href="{_lien_tri(col, tri, sens, cle, du, au)}">{titre}{fl}</a></th>')
    corps = []
    for x in lignes:
        nom = _e(x.get("nom")) or '<span class="faible">(sans nom)</span>'
        us_cl = "" if x.get("us_etat") == "ok" else " vieux"
        corps.append(f'<tr><td class="nom"><b>{nom}</b>{_detail_personne(x, source)}</td>'
                     f'<td class="n{us_cl}">{_nb(x.get("us"))}</td>'
                     f'<td class="n">{_nb(x.get("clics"))}</td>'
                     f'<td class="n fort">{_nb(x.get("subs"))}</td>'
                     f'<td class="n">{_pastille(_pct(x.get("cvr")), niveau(x.get("cvr"), SEUIL_CVR))}</td>'
                     f'<td class="n">{_pastille(_dollars(x.get("par_sub")), niveau(x.get("par_sub"), SEUIL_PAR_SUB))}'
                     f'</td></tr>')
    if not corps:
        corps.append('<tr><td class="faible" colspan="6">Aucune personne.</td></tr>')
    lib = f"Total · {_nb(len(lignes))} personne{'s' if len(lignes) > 1 else ''}"
    pied = (f'<tr class="total"><td class="nom">{_e(lib)}</td><td class="n">{_nb(T.get("us"))}</td>'
            f'<td class="n">{_nb(T.get("clics"))}</td><td class="n">{_nb(T.get("subs"))}</td>'
            f'<td class="n">{_pastille(_pct(T.get("cvr")), niveau(T.get("cvr"), SEUIL_CVR))}</td>'
            f'<td class="n">{_pastille(_dollars(T.get("par_sub")), niveau(T.get("par_sub"), SEUIL_PAR_SUB))}'
            f'</td></tr>')
    return (f'<div class="boite"><table><thead><tr>{"".join(th)}</tr></thead>'
            f'<tbody>{"".join(corps)}</tbody><tfoot>{pied}</tfoot></table></div>')


def _table_hors(lignes: List[Mapping[str, Any]], source: str = "Infloww") -> str:
    """Les liens Infloww qu'aucun lien GMS ne vise. Pas de total : ils ne
    comptent pas, un total les ferait lire comme s'ils comptaient."""
    corps = []
    for x in lignes:
        nom = _e(x.get("nom")) or '<span class="faible">(sans nom)</span>'
        det = f'c{_e(x.get("code"))}' if x.get("code") else "sans code"
        if x.get("desactive"):
            det += ' · <span class="off">désactivé</span>'
        corps.append(f'<tr><td class="nom">{nom}<div class="det">{det}</div></td>'
                     f'<td class="n">{_nb(x.get("clics"))}</td><td class="n">{_nb(x.get("subs"))}</td>'
                     f'<td class="n">{_pastille(_pct(x.get("cvr")), niveau(x.get("cvr"), SEUIL_CVR))}</td>'
                     f'<td class="n">{_pastille(_dollars(x.get("par_sub")), niveau(x.get("par_sub"), SEUIL_PAR_SUB))}'
                     f'</td></tr>')
    return (f'<div class="boite"><table><thead><tr><th class="nom">Lien {_e(source)}</th><th class="n">Clics OF</th>'
            '<th class="n">Subs</th><th class="n">CVR</th><th class="n">$\u00a0/\u00a0sub</th></tr></thead>'
            f'<tbody>{"".join(corps)}</tbody></table></div>')


def _avertissements(t: Mapping[str, Any], lignes: List[Mapping[str, Any]], cle: str = "",
                    tri: str = "nom", sens: str = "asc") -> List[str]:
    h: List[str] = []
    source = str(t.get("source") or "Infloww")
    per = t.get("periode") or {}
    if per.get("perime"):
        h.append(f'<div class="avert"><b>MyPuls n\'a pas répondu</b> ({_e(per["perime"])}).</div>')
    if t.get("repli_gms"):
        h.append(f'<div class="avert"><b>GetMySocial n\'a pas répondu</b> ({_e(t["repli_gms"])}) : '
                 f'liste des liens reprise du cache du site ({_nb(t.get("nb_gms"))} liens), '
                 "peut-être ancienne ou incomplète.</div>")
    if t.get("tronque"):
        h.append(f'<div class="avert">Liste {_e(source)} INCOMPLÈTE : la pagination s\'est arrêtée sur '
                 + _e(", ".join(str(x) for x in t["tronque"])) + ".</div>")
    if t.get("illisibles"):
        h.append(f'<div class="avert">{_nb(t["illisibles"])} ligne(s) rendue(s) par {_e(source)} sous '
                 "une forme illisible : non comptée(s).</div>")
    if per.get("doublons"):
        h.append(f'<div class="avert">{_nb(per["doublons"])} lien(s) rendu(s) deux fois par MyPuls '
                 "(même adresse) : comptés une seule fois.</div>")
    if per.get("champs_manquants"):
        h.append(f'<div class="avert">{_nb(per["champs_manquants"])} lien(s) MyPuls sans nombre de subs '
                 "ou sans gains lisibles : comptés à zéro sur ce point.</div>")
    if per.get("devise") and per["devise"] != "USD":
        h.append(f'<div class="avert">MyPuls compte les gains en {_e(per["devise"])}, pas en dollars : '
                 "le $ / sub est dans cette monnaie.</div>")
    pm = per.get("periode_mypuls") or {}
    if pm.get("from") and pm.get("to") and (pm["from"][:10], pm["to"][:10]) != (per.get("du"), per.get("au")):
        h.append(f'<div class="avert">MyPuls a compté du {_e(pm["from"])} au {_e(pm["to"])}, '
                 "pas exactement la période demandée.</div>")
    if t.get("gms_sans_id"):
        h.append(f'<div class="avert">{_nb(t["gms_sans_id"])} lien(s) GetMySocial sans identifiant : '
                 "non comptés.</div>")
    if t.get("introuvables"):
        h.append(f'<div class="avert">{_nb(t["introuvables"])} lien(s) GetMySocial sans lien de suivi '
                 f"{_e(source)} en face : la personne est affichée avec « — », pas avec un zéro "
                 "(détail sous son nom).</div>")
    for p in t.get("partages") or []:
        h.append(f'<div class="avert">Le lien {_e(source)} « {_e(p["nom"])} » (c{_e(p["code"])}) est visé par '
                 f'plusieurs personnes ({_e(", ".join(p["personnes"]))}) : compté chez chacune, '
                 "UNE seule fois dans le total.</div>")
    if per:
        a = _avert_us_periode(per, lignes, cle, tri, sens)
        if a:
            h.append(a)
        return h
    etats = [x.get("us_etat") for x in lignes]
    rates, anciens, absents = etats.count("rate"), etats.count("ancien"), etats.count("absent")
    if rates or anciens or absents:
        m = []
        if anciens:
            m.append(f"{_nb(anciens)} d'un jour précédent (en gris, date sous le nom)")
        if rates:
            m.append(f"{_nb(rates)} en échec au dernier essai (l'ancienne valeur reste, "
                     "retenté dans 10 min)")
        if absents:
            m.append(f"{_nb(absents)} pas encore relevé(s) (—)")
        if t.get("us_pause"):
            suite = (f". GetMySocial n'accepte plus d'appel ({_e(t['us_pause'])}) : "
                     "le relevé reprendra tout seul.")
        else:
            suite = ". Le relevé du jour se fait en arrière-plan : rechargez dans une minute."
        h.append('<div class="avert">Clics US : ' + " ; ".join(m) + suite + "</div>")
    return h


def _libelle_periode(du: str, au: str, auj: str = "") -> str:
    """« 21/09 → 26/09 », l'année seulement quand ce n'est pas celle en cours."""
    an = (auj or _aujourdhui())[:4]
    f = (lambda d: _jour_court(d) if d[:4] == an else _jour_long(d))  # noqa: E731
    return f(du) if du == au else f"{f(du)} → {f(au)}"


def _avert_us_periode(per: Mapping[str, Any], lignes: List[Mapping[str, Any]], cle: str,
                      tri: str, sens: str) -> str:
    """Ce que la page dit des clics US d'une période, en UNE boîte : répété
    sur chaque ligne, ça doublait la hauteur du tableau sur un téléphone."""
    info = per.get("us_info") or {}
    etats = [x.get("us_etat") for x in lignes]
    rates, anciens, absents = etats.count("rate"), etats.count("ancien"), etats.count("absent")
    if not (rates or anciens or absents):
        return ""
    if info.get("plafond"):
        deja = [p.split("|", 1) for p in info.get("calculees") or [] if "|" in p]
        liens = ", ".join(f'<a href="{_lien_page(tri, sens, cle, d, a)}">{_e(_libelle_periode(d, a))}</a>'
                          for d, a in deja)
        return ('<div class="avert">Clics US : déjà ' + _nb(US_PERIODES_MAX_JOUR)
                + " périodes différentes calculées aujourd'hui, le plafond du jour (le quota GetMySocial "
                "est partagé avec le tableau de bord) : pas de calcul pour celle-ci avant demain, "
                "« — » sauf relevé déjà gardé. Les autres chiffres, eux, sont bien ceux de la période."
                + (f" Périodes déjà calculées aujourd'hui : {liens}." if liens else "") + "</div>")
    if info.get("budget"):
        return ('<div class="avert">Clics US : les ' + _nb(info["budget"]) + " appels GetMySocial du jour "
                f"réservés aux périodes sont faits ({_nb(US_PERIODES_APPELS_PAR_PERSONNE)} par personne ; le "
                "quota est partagé avec le tableau de bord) : pas de nouveau calcul avant demain. Les relevés "
                "déjà gardés restent (en gris s'ils ont été pris avant la fin de la période), « — » sinon. "
                "Les autres chiffres, eux, sont bien ceux de la période.</div>")
    m = []
    if anciens:
        m.append(f"{_nb(anciens)} relevé(s) pris avant la fin de la période (en gris, heure sous le nom)")
    if rates:
        m.append(f"{_nb(rates)} en échec au dernier essai (retenté dans 10 min, trois fois par jour au plus)")
    if absents:
        m.append(f"{_nb(absents)} pas encore relevé(s) (—)")
    if info.get("pause"):
        suite = (f". GetMySocial n'accepte plus d'appel ({_e(info['pause'])}) : "
                 "le calcul reprendra à un prochain affichage.")
    else:
        suite = ". Le calcul se fait en arrière-plan : rechargez dans une minute."
    return '<div class="avert">Clics US de la période : ' + " ; ".join(m) + suite + "</div>"


def _titre_periode(du: str, au: str, auj: str) -> str:
    """« Du 21/09 au 26/09 · MyPuls », « Le 26/09 · MyPuls » ou « Depuis
    toujours · Infloww » : d'où viennent les chiffres, avant tout le reste."""
    if not du:
        return "Depuis toujours · Infloww"
    f = _jour_long if (du[:4] != auj[:4] or au[:4] != auj[:4]) else _jour_court
    return (f"Le {f(du)}" if du == au else f"Du {f(du)} au {f(au)}") + " · MyPuls"


def _bornes_mypuls(pm: Mapping[str, Any]) -> str:
    """« du 21/09/2026 00:00:00 au 26/09/2026 23:59:59, heure de Paris
    (UTC+02:00) » à partir des bornes que MyPuls rend avec ses chiffres ;
    "" si elles manquent ou ne se lisent pas."""
    try:
        d0, d1 = (dt.datetime.fromisoformat(str(pm.get(k) or "")) for k in ("from", "to"))
    except ValueError:
        return ""
    z = d0.strftime("%z")
    return (f"du {d0:%d/%m/%Y %H:%M:%S} au {d1:%d/%m/%Y %H:%M:%S}, heure de Paris"
            + (f" (UTC{z[:3]}:{z[3:]})" if z else ""))


def _formulaire(du: str, au: str, tri: str, sens: str, cle: str, auj: str) -> str:
    """Le choix de la période, SANS JavaScript : un formulaire GET qui porte
    aussi la clé (sans elle, un VA sans compte perdait l'accès en validant)
    et le tri, plus des raccourcis en simples liens."""
    caches = "".join(f'<input type="hidden" name="{n}" value="{_e(v)}">'
                     for n, v in (("k", cle), ("tri", tri), ("sens", sens)) if v)
    try:
        j = dt.date.fromisoformat(auj)
    except ValueError:
        j = dt.date.today()
    raccourcis = (("Depuis toujours", "", ""), ("Aujourd'hui", auj, auj),
                  ("7 derniers jours", (j - dt.timedelta(days=6)).isoformat(), auj),
                  ("30 derniers jours", (j - dt.timedelta(days=29)).isoformat(), auj))
    liens = []
    for lib, d, a in raccourcis:
        on = ' class="on" aria-current="page"' if (d, a) == (du, au) else ""
        liens.append(f'<a href="{_lien_page(tri, sens, cle, d, a)}"{on}>{_e(lib)}</a>')
    bornes = f'min="{_e(PLANCHER.isoformat())}" max="{_e(auj)}"'
    return (f'<form class="periode" method="get">{caches}'
            '<span class="lib">Période</span>'
            f'<input type="date" name="du" value="{_e(du)}" {bornes} aria-label="Date de début">'
            '<span class="fl" aria-hidden="true">→</span>'
            f'<input type="date" name="au" value="{_e(au)}" {bornes} aria-label="Date de fin">'
            '<button type="submit">OK</button></form>'
            f'<nav class="raccourcis" aria-label="Périodes">{"".join(liens)}</nav>')


def _note(t: Mapping[str, Any], du: str, au: str, auj: str) -> List[str]:
    source = str(t.get("source") or "Infloww")
    if not du:
        note = [f"<b>Personnes</b> : liens GetMySocial de l'espace « {_e(NOM_EQUIPE)} », un lien SPAM "
                "compte à part ; une personne additionne ses liens Infloww distincts",
                "<b>Clics US</b> : clics venus des États-Unis sur ses liens GetMySocial, depuis toujours "
                "(la mesure « Clics US » du tableau de bord et du podium), relevés une fois par jour",
                "<b>Clics OF</b> : clics OnlyFans du lien de suivi, lus dans Infloww (pas dans MyPuls)",
                "<b>CVR</b> = subs ÷ clics OF ; <b>$ / sub</b> = gains nets ÷ subs",
                "compteurs Infloww cumulés depuis la création de chaque lien, mis à jour toutes les 2 h",
                f"lu le {_e(_heure(t.get('lu_a')))} (heure de Paris)"]
        if t.get("maj_infloww"):
            note.append(f"compteurs rafraîchis par Infloww le {_e(_heure(t['maj_infloww']))}")
    else:
        # la sémantique de from/to, telle que MyPuls la rend avec ses chiffres
        # (relevé du 26/09 : journées entières, heure de Paris, bornes incluses)
        bornes = _bornes_mypuls((t.get("periode") or {}).get("periode_mypuls") or {})
        note = [("<b>Période</b> : " + (_e(bornes) + ", les deux jours inclus (bornes rendues par MyPuls)"
                                        if bornes else
                                        f"du {_e(_jour_long(du))} à 00:00:00 au {_e(_jour_long(au))} à "
                                        "23:59:59, heure de Paris, les deux jours inclus")),
                f"<b>Personnes</b> : liens GetMySocial de l'espace « {_e(NOM_EQUIPE)} », un lien SPAM "
                "compte à part ; une personne additionne ses liens de suivi distincts",
                "<b>Clics US</b> : clics venus des États-Unis sur ses liens GetMySocial pendant ces mêmes "
                "jours, calculés en arrière-plan puis gardés (toutes les 2 h si la période finit "
                f"aujourd'hui) ; {_nb(US_PERIODES_MAX_JOUR)} périodes différentes et "
                f"{_nb(US_PERIODES_APPELS_PAR_PERSONNE)} appels GetMySocial par personne par jour au plus"
                + (f" ({_nb(_budget_jour(len(t['lignes'])))} en tout)" if t.get("lignes") else "")
                + ", le quota GetMySocial est partagé ; un 0 n'est affiché qu'une fois relu dans la réponse "
                "brute de GetMySocial",
                "<b>Clics OF</b> et <b>Subs</b> : visites et abonnés du lien de suivi sur la période, "
                "lus dans MyPuls (pas dans Infloww, qui ne donne que des cumuls)",
                "<b>CVR</b> = subs ÷ clics OF ; <b>$ / sub</b> = gains nets que MyPuls attribue au lien "
                "sur la période ÷ subs de la période"]
        if au == auj:
            note.append("aujourd'hui compte jusqu'à l'heure de lecture")
        note.append(f"MyPuls lu le {_e(_heure(t.get('lu_a')))} (heure de Paris), relu toutes les "
                    f"{_nb(MYPULS_TTL_S // 60)} min au plus")
    if t.get("sans_clics"):
        note.append(f"{_nb(t['sans_clics'])} lien(s) sans nombre de clics chez {_e(source)}")
    return note


def page_html(t: Mapping[str, Any], tri: str = "nom", sens: str = "asc", cle: str = "") -> str:
    """La page entière. Aucun JavaScript : le tri et la période passent par
    l'adresse, et une apostrophe dans un nom de lien ne peut rien casser.
    Tout est échappé."""
    tri, sens = _tri_valide(tri, sens)
    lignes = trier(t.get("lignes") or [], tri, sens)
    hors = sorted(t.get("hors_gms") or [], key=_ordre_defaut)
    T = t.get("totaux") or {}
    source = str(t.get("source") or "Infloww")
    per = t.get("periode") or {}
    du, au = str(per.get("du") or ""), str(per.get("au") or "")
    if not (du and au):
        du = au = ""
    auj = _aujourdhui()
    h: List[str] = [_formulaire(du, au, tri, sens, cle, auj)]
    if t.get("erreur"):
        # MyPuls lent : ce n'est pas (encore) une panne, la lecture continue
        titre = "Lecture en cours." if per.get("mypuls_en_cours") else "Lecture impossible."
        h.append(f'<div class="err"><b>{titre}</b><br>{_e(t["erreur"])}</div>')
    else:
        h += _avertissements(t, lignes, cle, tri, sens)
        h.append(_table_personnes(lignes, T, tri, sens, cle, du, au, source))
        h.append('<p class="legende">Couleurs : <span class="nv v1">vert</span> dès '
                 f'{_dec(SEUIL_CVR, 0)}\u00a0% de CVR et dès {_dollars(SEUIL_PAR_SUB)}\u00a0par sub '
                 '(plus foncé = mieux), <span class="nv o1">orange</span> en dessous, '
                 '<span class="nv r">rouge</span> sous la moitié.</p>')
        if hors:
            h.append(f'<details><summary>Hors GetMySocial, non comptés ({_nb(len(hors))}) — '
                     f'liens de suivi de Jessye qu\'aucun lien de « {_e(NOM_EQUIPE)} » ne vise'
                     f'</summary>{_table_hors(hors, source)}</details>')
    note = _note(t, du, au, auj)
    sous = (f"<b>{_e(_titre_periode(du, au, auj))}</b> · @{_e(t.get('creatrice') or CREATRICE)} · "
            f"GetMySocial « {_e(NOM_EQUIPE)} »")
    if not t.get("erreur"):
        sous += f" · {_nb(len(lignes))} personnes"
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">
<title>Liens de suivi · {_e(NOM_AFFICHE)}</title>
<style>
:root{{--fond:#0e0e10;--carte:#18181b;--bord:#2a2a2f;--texte:#f4f4f5;--faible:#a1a1aa;--acc:#f97341;--rouge:#ef4444;--ambre:#f59e0b}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--fond);color:var(--texte)}}
body{{font:14px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;padding:20px 16px 32px;max-width:960px;margin:0 auto}}
.marque{{color:var(--acc);font-weight:700;font-size:12px;letter-spacing:.06em;text-transform:uppercase}}
h1{{font-size:20px;margin:4px 0 2px}}
.sous{{color:var(--faible);font-size:13px;margin:0 0 16px;overflow-wrap:anywhere}}
.boite{{background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:9px 10px;border-bottom:1px solid var(--bord);text-align:left;vertical-align:top}}
th{{font-size:12px;font-weight:600;white-space:nowrap;background:var(--carte)}}
th a{{color:var(--faible);text-decoration:none}} th.on a{{color:var(--acc)}}
td.nom{{overflow-wrap:anywhere;min-width:110px}}
.det{{color:var(--faible);font-size:11px;line-height:1.35;margin-top:3px}}
.det .off{{color:var(--ambre)}} .det .manque{{color:var(--ambre)}}
.n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.fort{{font-weight:700}} .acc{{color:var(--acc);font-weight:600}} .faible{{color:var(--faible)}}
td.vieux{{color:var(--faible)}}
.nv{{display:inline-block;border-radius:6px;padding:1px 7px;font-weight:700}}
.nv.v1{{background:#4ade80;color:#052e16}} .nv.v2{{background:#16a34a;color:#fff}}
.nv.v3{{background:#166534;color:#fff}} .nv.o1{{background:#fbbf24;color:#1c1203}}
.nv.o2{{background:#f97316;color:#1c0a02}} .nv.r{{background:#dc2626;color:#fff}}
.legende{{color:var(--faible);font-size:12px;margin:8px 0 0}}
.sous b{{color:var(--texte);font-weight:600}}
.periode{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 8px}}
.periode .lib{{color:var(--faible);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}}
.periode input{{flex:1 1 128px;min-width:0;max-width:180px;background:var(--carte);color:var(--texte);border:1px solid var(--bord);border-radius:8px;padding:7px 8px;font:inherit;font-size:14px;color-scheme:dark}}
.periode .fl{{color:var(--faible)}}
.periode button{{background:var(--acc);color:#1c0a02;border:0;border-radius:8px;padding:8px 16px;font:inherit;font-weight:700;cursor:pointer}}
.raccourcis{{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}}
.raccourcis a{{color:var(--faible);text-decoration:none;border:1px solid var(--bord);border-radius:999px;padding:4px 10px;font-size:12px;white-space:nowrap}}
.raccourcis a.on{{color:var(--acc);border-color:var(--acc)}}
.avert a{{color:var(--acc)}}
tbody tr:hover td{{background:rgba(249,115,65,.06)}}
tfoot td{{border-bottom:0;border-top:2px solid var(--bord);font-weight:700}}
details{{margin:18px 0 0}}
summary{{cursor:pointer;color:var(--faible);font-size:13px;padding:6px 0}}
details .boite{{margin-top:8px;opacity:.85}}
.note{{color:var(--faible);font-size:12px;margin:16px 0 0}}
.err{{background:rgba(239,68,68,.12);border:1px solid var(--rouge);border-radius:12px;padding:14px 16px;overflow-wrap:anywhere}}
.avert{{background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.6);border-radius:12px;padding:10px 14px;margin:0 0 12px;font-size:13px;overflow-wrap:anywhere}}
/* 360 px de large : les six colonnes tiennent. Les en-têtes passent sur deux
   lignes (« Clics / OF » ; th.n et non th, que .n remettait en nowrap) et le
   nom se replie ; sans ça le $ / sub, la colonne qu'on vient lire, sortait de
   l'écran. Ce qui ne tiendrait pas défile dans la boîte, jamais la page. */
@media (max-width:480px){{.periode .lib{{flex-basis:100%}} table{{font-size:12px}} th,td{{padding:8px 3px}} th.n{{white-space:normal}} th:first-child,td:first-child{{padding-left:10px}} th:last-child,td:last-child{{padding-right:10px}} td.nom{{min-width:74px}} .det{{font-size:10.5px}} .nv{{padding:1px 3px}} h1{{font-size:18px}}}}
@media (max-width:340px){{table{{font-size:11.5px}} th,td{{padding:7px 2px}} th:first-child,td:first-child{{padding-left:8px}} th:last-child,td:last-child{{padding-right:8px}} td.nom{{min-width:64px}}}}
</style></head><body>
<div class="marque">Infloww · YouL4b</div>
<h1>Liens de suivi · {_e(NOM_AFFICHE)}</h1>
<p class="sous">{sous}</p>
{"".join(h)}
<p class="note">{" · ".join(note)}.</p>
</body></html>'''


def page(args: Mapping[str, Any], cle: str = "") -> str:
    """La page à partir des paramètres de l'adresse. Ne lève jamais : une
    panne s'affiche SUR la page."""
    tri, sens = _tri_valide(args.get("tri"), args.get("sens"))
    try:
        per = periode_des_args(args)
    except Exception:            # par ceinture : une période illisible = depuis toujours
        per = None
    try:
        # sans période : la vue Infloww d'avant, inchangée
        t = tableau_periode(*per) if per else tableau()
    except Exception as e:  # tableau() ne lève pas ; par ceinture
        t = _vide(f"{type(e).__name__} : {e}", per)
    try:
        return page_html(t, tri, sens, cle)
    except Exception as e:
        # la clé suit jusque dans la page de panne : le formulaire la porte
        return page_html(_vide(f"la page n'a pas pu être construite : {type(e).__name__} : {e}", per),
                         cle=cle)
