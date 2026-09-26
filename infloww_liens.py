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

- LE PAIEMENT (page seulement, le propriétaire : « une case où je peux
  choisir leur paiement », « la dernière case qui me dit si le VA me fait
  perdre ou gagner de l'argent ») : un réglage par personne
  (data/infloww_liens_paie.json : Aucun, Fixe ou Fixe + primes, montant,
  USD ou EUR, quinzaine ou mois, payé depuis), modifiable par un formulaire
  POST sans JavaScript (route /infloww/liens/paie). Pour le propriétaire
  SEUL : sa clé à lui (cle_paie, jamais postée) ou une session admin ; la
  clé du salon (celle des VA) ne montre ni paiement ni gain. Gain /
  perte = revenu net de la plage − fixe au prorata − primes par quinzaine
  (paliers de subs non cumulables, subs de MyPuls quinzaine par quinzaine).
  Euros convertis au taux BCE. Rien de tout ça sur Discord.
  Le fixe est payé PAR LIGNE : « chaque ligne c'est une paye (c'est un
  iPhone) » — une ligne = un lien GetMySocial de la personne qui a fait au
  moins un clic sur la tranche (clics GMS lien par lien, en arrière-plan,
  gardés dans data/infloww_liens_lignes.json, avec la personne à qui était
  le lien ; tranche close FIGÉE ; lignes « forcées » par le propriétaire
  pour un passé faussé ; rien avant la création du lien GMS). Les VA SPAM sont payés AU SUB
  (type « au_sub » : 0,40 $ jusqu'à 200 subs par quinzaine, 0,50 $ au-delà,
  au marginal), sans fixe.

Deux sorties : la page /infloww/liens, sans JavaScript (clé ?k= pour les VA
sans compte), et des messages Discord de Bixby dans « inflow-resultat ».
L'ENVOI DISCORD EST COUPÉ tant que data/infloww_liens_config.json ne porte pas
"discord_actif": true — le propriétaire veut d'abord choisir le format.

infloww.py n'est importé que par ce module et web_upload.py.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html as _html
import json
import math
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
# la clé du propriétaire, À PART de celle du salon (cle_paie)
CLE_PAIE_FICHIER = DATA_DIR / "infloww_liens_cle_paie"
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

# « gain » : la colonne Gain / perte (le paiement, page seulement) ; une
# personne sans réglage n'a pas de gain et va en bas, dans les deux sens
TRIS = ("nom", "us", "clics", "subs", "cvr", "par_sub", "gain")
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
# created_at / createdAt : gardés s'ils viennent un jour (la liste v3 du 26/09
# n'en a pas) — la date de création d'un lien GMS borne ses lignes (cree_gms)
_CHAMPS_GMS = ("id", "shortcode", "display_name", "title", "url", "created_at", "createdAt")


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


# « lnk_6a0e5346fba948185cdbdfaf » : un ObjectId, dont les 8 premiers chiffres
# hexadécimaux sont les secondes de sa création (0x6a0e5346 = 21/05/2026, le
# jour de l'espace tm_6a0e4739…)
_LNK_OBJECTID = re.compile(r"lnk_([0-9a-f]{8})[0-9a-f]{16}")
_TS_MIN = 1577836800                  # 01/01/2020 : avant, ce n'est pas une date de lien


def cree_gms(l: Any, maintenant: Optional[float] = None) -> str:
    """Le jour (AAAA-MM-JJ, heure de Paris) où un lien GMS a été créé : son
    champ de création s'il en a un, sinon l'horodatage de son identifiant.
    "" si on ne sait pas (identifiant d'une autre forme) : rien n'est alors
    borné par cette date. `l` : le lien, ou son seul identifiant."""
    maintenant = time.time() if maintenant is None else maintenant
    ts: Optional[float] = None
    lid = str(l.get("id") or "") if isinstance(l, Mapping) else str(l or "")
    if isinstance(l, Mapping):
        for champ in ("created_at", "createdAt"):
            v = l.get(champ)
            if isinstance(v, bool) or v in (None, ""):
                continue
            try:
                if isinstance(v, (int, float)):
                    ts = float(v) / (1000.0 if float(v) > 1e11 else 1.0)
                else:
                    d = dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
                    ts = (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()
            except (ValueError, OverflowError, OSError):
                ts = None
            if ts is not None:
                break
    if ts is None:
        m = _LNK_OBJECTID.fullmatch(lid)
        ts = float(int(m.group(1), 16)) if m else None
    if ts is None or not _TS_MIN <= ts <= maintenant + 86400:
        return ""
    return _jour_de(ts)


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
            # le jour (Paris) de la lecture : une tranche lue APRÈS son dernier
            # jour ne bouge plus, le paiement la garde alors sur disque
            v["lu_jour"] = _aujourdhui()
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
    # Pour le paiement (avec_paie, la page seulement) : le revenu et la date de
    # création de chaque lien rattaché, À PART des lignes — une ligne qui ne
    # porte pas de montant ne peut pas en afficher un par mégarde (Discord lit
    # les lignes, jamais ceci).
    paie_liens = {iid: {"net": _entier(x.get("net")), "cree": str(x.get("cree") or "")[:10],
                        "devise": str(x.get("devise") or "")}
                  for iid, x in rattaches.items()}
    return {
        "_paie_liens": paie_liens, "_gms": list(liens_gms_),
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


# ─── le paiement des VA, et ce qu'ils rapportent ─────────────────────────
# Le propriétaire (26/09), pour lui seul (la page s'ouvre avec la clé) :
# « une case où je peux choisir leur paiement », puis « la dernière case qui
# me dit si le VA me fait perdre ou gagner de l'argent ». Sa grille :
# - un FIXE : 75 $ par période de paie, payée le 16 et le 1er — quinzaines du
#   1er au 15 et du 16 à la fin du mois ; certains VA ont un autre fixe, par
#   exemple 200 € par mois, converti en dollars ;
# - des PRIMES par quinzaine selon les VRAIS abonnés OnlyFans du VA (la
#   colonne Subs), NON cumulables : seul le palier atteint compte ;
# - Top Performer, Bonus Agence (tiré au sort), Bonus Elite et malus sont
#   décidés à la main : pas calculables, pas comptés, et la page le dit.
# Rien de tout ça ne part sur Discord : le démon passe par tableau(), jamais
# par avec_paie(), et messages_discord ne lit que ses propres colonnes.
PAIE_FICHIER = DATA_DIR / "infloww_liens_paie.json"
# « au_sub » (le propriétaire, 26/09) : « les VA SPAM c'est des paiements au
# sub : 0,4, et au-delà de 200 subs sur la quinzaine ça passe à 0,5 ». Pas de
# fixe. Au MARGINAL : 250 subs = 200 × 0,40 + 50 × 0,50 = 105 $ (et non
# 250 × 0,50). Rien n'est choisi à la place du propriétaire : une ligne SPAM
# non réglée n'est pas mise « au sub » d'office, le formulaire n'en porte que
# les valeurs par défaut.
TYPES_PAIE = ("aucun", "fixe", "fixe_primes", "au_sub")
LIB_TYPES = {"aucun": "Aucun", "fixe": "Fixe", "fixe_primes": "Fixe + primes", "au_sub": "Au sub"}
TYPES_PAYES = ("fixe", "fixe_primes", "au_sub")     # ceux qui coûtent : un gain se calcule
TYPES_FIXE = ("fixe", "fixe_primes")                # ceux qui ont un fixe, payé par ligne active
DEVISES = ("USD", "EUR")
FREQUENCES = ("quinzaine", "mois")
# ce que le formulaire propose pour une personne pas encore réglée : la grille
PAIE_DEFAUT: Dict[str, Any] = {"type": "fixe_primes", "montant": 75.0, "devise": "USD",
                               "frequence": "quinzaine", "depuis": "",
                               "taux1": 0.40, "seuil": 200, "taux2": 0.50, "lignes": None}
MONTANT_MAX = 20000.0            # par quinzaine ou par mois : au-delà, une faute de frappe
TAUX_SUB_MAX = 100.0             # $ par sub : au-delà, une faute de frappe
SEUIL_SUB_MAX = 100000           # subs par quinzaine
LIGNES_MAX = 50                  # « lignes payées » saisies à la main
# « lignes forcées » : le nombre de lignes d'une quinzaine (ou d'un mois)
# imposé par le propriétaire, même quand GetMySocial l'a compté — pour un
# passé faussé avant que le propriétaire de chaque lien soit noté (BO7 sur le
# 01/09 → 15/09 : « ( BO7 ) 3 » et « 4 » renommés le 26/09, relevés ensuite
# au nom de LaBoule). Par tranche ENTIÈRE, au plus FORCES_MAX.
FORCES_MAX = 240
PAIE_PERSONNES_MAX = 500
# (plancher de subs de la quinzaine, prime en $), du plus haut au plus bas
PALIERS_PRIMES: Tuple[Tuple[int, float], ...] = (
    (1500, 540.0), (1000, 320.0), (750, 250.0), (500, 170.0), (300, 90.0),
    (250, 70.0), (200, 45.0), (150, 25.0), (100, 10.0))

# Les subs d'une quinzaine viennent de MyPuls, sur ses seuls jours : une
# lecture tracking-links par tranche, la mécanique des périodes (cache mémoire
# MYPULS_TTL_S, échec gardé MYPULS_ECHEC_S, une lecture en vol par tranche).
# Une tranche lue APRÈS son dernier jour ne bouge plus : gardée sur disque,
# pour toujours, sans son revenu. La vue « depuis toujours » d'un VA payé
# depuis un an en demande vingt-cinq, et le débit MyPuls est limité (un 429
# prolonge la limitation pour tout le tableau de bord) : QUINZ_APPELS_MAX
# lectures NOUVELLES au plus par affichage, l'une après l'autre dans UN fil,
# arrêtées au premier échec.
QUINZ_FICHIER = DATA_DIR / "infloww_liens_quinzaines.json"
QUINZ_APPELS_MAX = 3
QUINZ_PAUSE_S = 1.0
QUINZ_ATTENTE_S = 4.0             # la page attend le fil ça, pas plus
# Relecture du 26/09 : une tranche close lue avec un TROU (lien sans nombre
# de subs, ou pas encore connu de MyPuls) était gardée telle quelle, pour
# toujours : le gain restait « — » même quand MyPuls avait les chiffres. Le
# disque ne garde donc que les subs CONNUS, lien par lien ; une tranche dont
# il manque un lien d'une personne réglée est relue, mais au plus une fois par
# QUINZ_TROU_REESSAI_S : le 26/09, LaBoule (c125, c126) était absent de
# MyPuls, et relire ses vingt-cinq quinzaines toutes les 10 min userait le
# débit MyPuls pour rien.
QUINZ_TROU_REESSAI_S = 3600
# Le disque grossissait d'un morceau par période consultée (vingt périodes,
# vingt-deux tranches gardées, aucune jamais retirée). Seules les quinzaines
# ENTIÈRES et les morceaux de début de paie (« payé depuis », création du
# lien) sont gardés pour toujours ; un autre morceau inutilisé depuis
# QUINZ_GARDE_S sort. « vu » (dernière utilisation) n'est réécrit qu'au jour
# près : pas une écriture disque à chaque affichage.
QUINZ_GARDE_S = 45 * 86400
QUINZ_VU_PAS_S = 86400
# Faux dans les tests : lecture sur place, sans fil qui survivrait aux bouchons
QUINZ_EN_FOND = True
_VERROU_Q = threading.Lock()
_VERROU_PAIE = threading.Lock()
_FIL_Q: Dict[str, Any] = {"fil": None, "pause": 0.0, "raison": ""}

# Euros → dollars : le taux de référence de la BCE, gratuit et sans clé, lu
# une fois par jour et gardé. BCE muette : le dernier taux connu, et la page
# dit de quand. Aucun taux connu : le coût d'un VA payé en euros est « — »,
# jamais un taux inventé.
BCE_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
BCE_FICHIER = DATA_DIR / "infloww_liens_bce.json"
BCE_REESSAI_S = 1800              # un échec n'est pas retenté à chaque affichage
_VERROU_BCE = threading.Lock()

# Les LIGNES ACTIVES (le propriétaire, 26/09) : « quand un VA a 2 liens et
# qu'ils font des clics, il prend 2 payes de base : chaque ligne c'est une
# paye (c'est un iPhone) ». BO7 a quatre liens GMS qui visent tous c85 :
# quatre iPhones, quatre fixes. Une ligne est ACTIVE sur une tranche du fixe
# (quinzaine ou mois, partie incluse dans la plage) si son lien GMS y a fait
# au moins un clic, tous pays. UN appel analytics_for_link par lien et par
# tranche, sur le quota GetMySocial serré et partagé (épuisé le 26/09 au petit
# matin) : cache disque par (tranche, lien), tranche close définitive, tranche
# en cours relue au plus une fois par jour, budget d'appels par jour, calcul
# en fil de fond — la page n'attend pas. Tant qu'un compte manque : les
# « lignes payées » saisies à la main s'il y en a, sinon « — ».
#
# À QUI était un lien sur une tranche (relecture du 26/09) : les lignes d'une
# quinzaine close se recalculaient avec la liste GMS du jour. « ( BO7 ) 3 » et
# « ( BO7 ) 4 », renommés « Laboule ( X ) » et « LaBoule ( Phone ) » le 26/09,
# retiraient deux payes à BO7 sur le 01/09 → 15/09 et en donnaient une à X,
# sur une quinzaine antérieure à son lien. Donc : chaque relevé note la
# personne à qui était le lien (« qui ») ; une tranche close entièrement
# relevée est FIGÉE ({personne: liens, actif ou non}) et relue telle quelle ;
# un lien qui a changé de personne ou disparu depuis est dit sous la ligne.
# Et un lien créé après la fin d'une tranche n'en est pas une ligne (aucun
# appel) : avant le premier lien GMS d'une personne, « pas encore de lien
# GetMySocial » — les liens Noum datent du 21/05, leurs liens Infloww du
# 02/04 ; la vue « depuis toujours » payait avril à 0 ligne.
LIGNES_FICHIER = DATA_DIR / "infloww_liens_lignes.json"
LIGNES_APPELS_JOUR = 120          # vérifications des zéros comprises
LIGNES_GARDE_S = 45 * 86400       # un morceau de période plus servi depuis : élagué
# Faux dans les tests : le relevé se fait sur place, sans fil
LIGNES_EN_FOND = True
_VERROU_LG = threading.Lock()     # un relevé à la fois
_VERROU_LG_F = threading.Lock()   # les écritures du fichier (relevé et « vu » de la page)
_VERROU_LG_LANCE = threading.Lock()
_FIL_LG: Dict[str, Any] = {"fil": None}


def palier(subs: Any) -> Tuple[float, str]:
    """(prime en $, palier atteint) pour les subs d'une quinzaine. Paliers
    NON cumulables : 320 subs rapportent 90 $, pas 10 + 25 + 45 + 70 + 90."""
    n = _entier(subs) or 0
    haut: Optional[int] = None
    for plancher, prime in PALIERS_PRIMES:
        if n >= plancher:
            return prime, (f"{_nb(plancher)} subs et plus" if haut is None
                           else f"{_nb(plancher)}–{_nb(haut - 1)} subs")
        haut = plancher
    return 0.0, f"moins de {_nb(PALIERS_PRIMES[-1][0])} subs"


def _fin_du_mois(d: dt.date) -> dt.date:
    suivant = d.replace(day=28) + dt.timedelta(days=4)
    return suivant - dt.timedelta(days=suivant.day)


def quinzaine_de(d: dt.date) -> Tuple[dt.date, dt.date]:
    """La période de paie d'un jour : du 1er au 15, ou du 16 à la fin du mois
    (la paie tombe le 16 et le 1er)."""
    if d.day <= 15:
        return d.replace(day=1), d.replace(day=15)
    return d.replace(day=16), _fin_du_mois(d)


def mois_de(d: dt.date) -> Tuple[dt.date, dt.date]:
    return d.replace(day=1), _fin_du_mois(d)


def decouper(a: dt.date, b: dt.date, frequence: str = "quinzaine") -> List[Dict[str, Any]]:
    """Les quinzaines (ou mois civils) qui touchent [a, b], bornes incluses,
    chacune avec sa partie incluse : {du, au, p_du, p_au, jours,
    jours_periode, complete}. [] si a > b."""
    de = mois_de if frequence == "mois" else quinzaine_de
    out: List[Dict[str, Any]] = []
    d = a
    while d <= b:
        p0, p1 = de(d)
        f = min(p1, b)
        out.append({"du": d, "au": f, "p_du": p0, "p_au": p1, "jours": (f - d).days + 1,
                    "jours_periode": (p1 - p0).days + 1, "complete": d == p0 and f == p1})
        d = f + dt.timedelta(days=1)
    return out


def cout_fixe(cfg: Mapping[str, Any], a: dt.date, b: dt.date) -> Tuple[float, List[Dict[str, Any]]]:
    """Le fixe sur [a, b], dans la devise du réglage, au prorata des jours de
    chaque quinzaine (ou mois) : 75 $ sur toute la quinzaine du 1er au 15 =
    75 $ ; sur 5 de ses jours = 25 $."""
    tr = decouper(a, b, str(cfg.get("frequence") or "quinzaine"))
    m = float(cfg.get("montant") or 0)
    return sum(m * t["jours"] / t["jours_periode"] for t in tr), tr


def _milliemes(v: Any) -> int:
    return int(round(float(v or 0) * 1000))


def cout_au_sub(cfg: Mapping[str, Any], subs: Any) -> Tuple[float, int, int]:
    """(coût dans la devise du réglage, subs au premier prix, subs au second)
    pour les subs d'UNE quinzaine (ou de sa partie incluse : le seuil reste
    celui de la quinzaine entière). Au MARGINAL : avec 0,40 jusqu'à 200 puis
    0,50, 250 subs = 200 × 0,40 + 50 × 0,50 = 105 ; 201 subs = 80,50. Compté
    en millièmes : 200 × 0,4 ne donne pas 80,000000001."""
    n = max(0, _entier(subs) or 0)
    seuil = max(0, _entier(cfg.get("seuil")) or 0)
    bas, haut = min(n, seuil), max(0, n - seuil)
    return (bas * _milliemes(cfg.get("taux1")) + haut * _milliemes(cfg.get("taux2"))) / 1000.0, bas, haut


# ─── le paiement : les réglages ──────────────────────────────────────────
def _decimal(v: Any, maxi: float, decimales: int) -> Optional[float]:
    """Un nombre >= 0 et <= maxi, `decimales` décimales au plus ; « 75,5 »
    comme « 75.50 ». Autre chose : None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = (str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "")
             .replace(",", "."))
        if not re.fullmatch(r"\d{1,6}(?:\.\d{0,%d})?" % decimales, s):
            return None
        f = float(s)
    if not math.isfinite(f) or f < 0 or f > maxi:
        return None
    return round(f, decimales)


def _montant(v: Any) -> Optional[float]:
    """Un montant >= 0 et <= MONTANT_MAX, deux décimales au plus."""
    return _decimal(v, MONTANT_MAX, 2)


def _entier_borne(v: Any, mini: int, maxi: int) -> Optional[int]:
    """Un entier de mini à maxi (« 200 », 200, 200.0) ; « 2,5 », « 1e3 » ou
    autre chose : None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, float):
        if not math.isfinite(v) or not v.is_integer():
            return None
        n = int(v)
    else:
        s = str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "")
        if not re.fullmatch(r"\d{1,7}", s):
            return None
        n = int(s)
    return n if mini <= n <= maxi else None


def valider_paie(r: Any, aujourdhui: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """Un réglage, du formulaire ou du fichier : (réglage propre, "") ou
    (None, ce qui ne va pas). Seuls les champs du type choisi comptent : le
    formulaire envoie tout (fixe comme au sub), le réglage ne garde que les
    siens — un prix au sub vide n'empêche pas d'enregistrer un fixe."""
    if not isinstance(r, Mapping):
        return None, "réglage illisible"
    typ = str(r.get("type") or "").strip()
    if typ not in TYPES_PAIE:
        return None, "type inconnu (Aucun, Fixe, Fixe + primes ou Au sub)"
    sub: Dict[str, Any] = {}
    m: Optional[float] = None
    if typ == "au_sub":
        for champ, quoi in (("taux1", "prix par sub jusqu'au seuil"), ("taux2", "prix par sub au-delà du seuil")):
            sub[champ] = _decimal(r.get(champ), TAUX_SUB_MAX, 3)
            if sub[champ] is None:
                return None, (f"{quoi} invalide : un nombre de 0 à {_nb(TAUX_SUB_MAX)}, "
                              "trois décimales au plus")
        sub["seuil"] = _entier_borne(r.get("seuil"), 0, SEUIL_SUB_MAX)
        if sub["seuil"] is None:
            return None, f"seuil invalide : un nombre entier de subs, de 0 à {_nb(SEUIL_SUB_MAX)}"
    else:
        m = _montant(r.get("montant"))
        if m is None:
            return None, (f"montant invalide : un nombre de 0 à {_nb(MONTANT_MAX)}, "
                          "deux décimales au plus")
    devise = str(r.get("devise") or "").strip().upper()
    if devise not in DEVISES:
        return None, "devise inconnue (USD ou EUR)"
    freq = str(r.get("frequence") or "").strip().lower()
    if typ != "au_sub" and freq not in FREQUENCES:
        return None, "fréquence inconnue (quinzaine ou mois)"
    lignes: Optional[int] = None
    if typ in TYPES_FIXE and str(r.get("lignes") if r.get("lignes") is not None else "").strip():
        lignes = _entier_borne(r.get("lignes"), 1, LIGNES_MAX)
        if lignes is None:
            return None, f"lignes payées invalides : un nombre entier de 1 à {_nb(LIGNES_MAX)}, ou rien"
    forces: Dict[str, int] = {}
    if typ in TYPES_FIXE and r.get("forces") is not None:
        # jamais du formulaire (enregistrer_paie les fusionne), seulement du fichier
        fr = r.get("forces")
        if not isinstance(fr, Mapping) or len(fr) > FORCES_MAX:
            return None, f"lignes forcées illisibles (un objet de {_nb(FORCES_MAX)} tranches au plus)"
        for k, n in fr.items():
            if cle_tranche_entiere(k) != str(k):
                return None, f"lignes forcées : « {str(k)[:30]} » n'est pas une quinzaine ou un mois entier"
            nn = _entier_borne(n, 0, LIGNES_MAX)
            if nn is None:
                return None, f"lignes forcées invalides : un nombre entier de 0 à {_nb(LIGNES_MAX)}"
            forces[str(k)] = nn
    brut = str(r.get("depuis") or "").strip()
    depuis = ""
    if brut:
        d = _date_arg(brut)
        if d is None:
            return None, f"date « payé depuis » invalide : « {brut[:20]} »"
        try:
            auj = dt.date.fromisoformat(aujourdhui or _aujourdhui())
        except ValueError:
            auj = dt.date.today()
        fin = auj + dt.timedelta(days=366)
        if not PLANCHER <= d <= fin:
            return None, (f"date « payé depuis » hors bornes (du {_jour_long(PLANCHER.isoformat())} "
                          f"au {_jour_long(fin.isoformat())})")
        depuis = d.isoformat()
    if typ == "au_sub":
        return dict(type=typ, taux1=sub["taux1"], seuil=sub["seuil"], taux2=sub["taux2"],
                    devise=devise, depuis=depuis), ""
    out = {"type": typ, "montant": m, "devise": devise, "frequence": freq, "depuis": depuis}
    if lignes is not None:
        out["lignes"] = lignes
    if forces:
        out["forces"] = dict(sorted(forces.items()))
    return out, ""


def lire_paie() -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """({clé de personne: réglage}, [réglages illisibles, dits sur la page])."""
    d = _lire_json(PAIE_FICHIER)
    mauvais: List[str] = []
    if not d:
        try:
            if PAIE_FICHIER.exists() and PAIE_FICHIER.stat().st_size > 2:
                mauvais.append("le fichier des réglages est illisible")
        except Exception:
            pass
        return {}, mauvais
    pers = d.get("personnes", {})
    if not isinstance(pers, Mapping):
        return {}, ["le fichier des réglages n'a pas la forme attendue"]
    out: Dict[str, Dict[str, Any]] = {}
    for cle, r in pers.items():
        v, err = valider_paie(r)
        if v is None:
            mauvais.append(f"« {cle} » : {err}")
        else:
            out[str(cle)] = v
    return out, mauvais


def _requete_page(tri: str, sens: str, cle: str, du: str = "", au: str = "") -> str:
    """« ?tri=…&du=…&k=… » brut (pas pour un href : _lien_page l'échappe)."""
    from urllib.parse import quote
    defaut = (tri, sens) == ("nom", "asc")
    paires = (("tri", "" if defaut else tri), ("sens", "" if defaut else sens),
              ("du", du), ("au", au), ("k", cle))
    return "?" + "&".join(f"{k}={quote(str(v), safe='')}" for k, v in paires if v)


def ancre(cle_personne: Any) -> str:
    """L'ancre de la ligne d'une personne : le retour du formulaire y ramène."""
    return "p-" + hashlib.sha1(str(cle_personne).encode("utf-8")).hexdigest()[:10]


def adresse_retour(form: Mapping[str, Any]) -> str:
    """La vue d'où vient le formulaire : tri, période et clé gardés, tous
    revalidés (rien de l'envoi n'est recopié tel quel dans l'adresse)."""
    tri, sens = _tri_valide(form.get("tri"), form.get("sens"))
    du, au = _date_arg(form.get("du")), _date_arg(form.get("au"))
    du_s, au_s = (du.isoformat(), au.isoformat()) if du and au else ("", "")
    q = _requete_page(tri, sens, str(form.get("k") or "")[:200], du_s, au_s)
    personne = str(form.get("personne") or "").strip()
    return "/infloww/liens" + ("" if q == "?" else q) + (f"#{ancre(personne)}" if personne else "")


def enregistrer_paie(form: Mapping[str, Any]) -> Tuple[bool, str, str]:
    """Le réglage envoyé par le formulaire de la page : (ok, pourquoi pas,
    adresse de retour). L'autorisation (clé de paiement ou admin) est vérifiée par la
    route, avant. Ne lève pas."""
    retour = adresse_retour(form)
    cle = str(form.get("personne") or "").strip()
    if not cle or len(cle) > 120:
        return False, "personne manquante", retour
    v, err = valider_paie(form)
    if v is None:
        return False, err, retour
    v.pop("forces", None)                 # jamais du formulaire : fusionnées plus bas
    # « Lignes forcées » de la période affichée : le champ n'est dans le
    # formulaire que sur une vue par période. Vide : plus rien de forcé sur
    # ses quinzaines (ou mois) ; un nombre : forcé sur chacune, en entier.
    # « forcer_avant » : la valeur que le formulaire montrait. Inchangée : rien
    # n'est touché (enregistrer un montant ne retire pas une tranche forcée).
    forcer: Optional[Tuple[set, Optional[int]]] = None
    if ("forcer_lignes" in form and v["type"] in TYPES_FIXE
            and str(form.get("forcer_lignes") or "").strip() != str(form.get("forcer_avant") or "").strip()):
        a_f, b_f = _date_arg(form.get("du")), _date_arg(form.get("au"))
        if not (a_f and b_f and a_f <= b_f):
            return False, "lignes forcées : choisissez d'abord la période en haut de la page", retour
        brut_f = str(form.get("forcer_lignes") or "").strip()
        n_f: Optional[int] = None
        if brut_f:
            n_f = _entier_borne(brut_f, 0, LIGNES_MAX)
            if n_f is None:
                return False, (f"lignes forcées invalides : un nombre entier de 0 à {_nb(LIGNES_MAX)}, "
                               "ou rien pour ne plus forcer"), retour
        forcer = ({_k_entiere(t) for t in decouper(a_f, b_f, v["frequence"])}, n_f)
    try:
        deja = cle in (lire_paie()[0])
        if not deja:
            # une personne de l'espace, pas un nom tapé à la main : le fichier
            # ne se remplit pas de clés qui ne correspondent à aucune ligne
            g = liens_gms()
            connues = set(entites(g["liens"])[0])
            if cle not in connues:
                return False, (f"« {cle} » n'est pas une personne de l'espace GetMySocial "
                               f"« {NOM_EQUIPE} »" + (" (liste de secours)" if g.get("repli") else "")), retour
        with _VERROU_PAIE:
            # Un fichier illisible (et sans .prev lisible) valait {} : le
            # réglage suivant écrasait tous les autres, et l'avertissement de
            # la page disparaissait avec eux (relecture du 26/09). On refuse :
            # le fichier reste tel quel, à réparer. (safe_json.load reprend
            # d'abord la copie .prev si elle se lit.)
            brut = safe_json.load(PAIE_FICHIER, default=None)
            if brut is None and PAIE_FICHIER.exists() and PAIE_FICHIER.stat().st_size > 2:
                return False, ("fichier des réglages illisible (data/infloww_liens_paie.json) : rien n'est "
                               "écrit, pour ne pas effacer les autres réglages — à réparer d'abord"), retour
            d = {} if brut is None else brut
            if not isinstance(d, Mapping) or not isinstance(d.get("personnes", {}), Mapping):
                return False, ("fichier des réglages sans la forme attendue (un objet « personnes ») : "
                               "rien n'est écrit, pour ne pas effacer les autres réglages — à réparer "
                               "d'abord"), retour
            pers = dict(d.get("personnes") or {})
            if cle not in pers and len(pers) >= PAIE_PERSONNES_MAX:
                return False, f"déjà {PAIE_PERSONNES_MAX} réglages", retour
            if v["type"] in TYPES_FIXE:
                # les tranches forcées d'autres périodes restent ; celles de
                # la période affichée prennent la nouvelle valeur (ou sortent)
                ancien, _e_anc = valider_paie(pers.get(cle)) if isinstance(pers.get(cle), Mapping) else (None, "")
                forces = dict((ancien or {}).get("forces") or {})
                if forcer is not None:
                    for k in forcer[0]:
                        forces.pop(k, None)
                        if forcer[1] is not None:
                            forces[k] = forcer[1]
                if len(forces) > FORCES_MAX:
                    return False, f"déjà {_nb(FORCES_MAX)} tranches aux lignes forcées", retour
                if forces:
                    v["forces"] = dict(sorted(forces.items()))
            pers[cle] = dict(v, maj=time.time())
            if not safe_json.write(PAIE_FICHIER, dict(d, personnes=pers, maj=time.time())):
                return False, "réglage non écrit (disque)", retour
    except Exception as e:
        return False, f"réglage non écrit : {type(e).__name__} : {e}"[:300], retour
    return True, "", retour


# ─── le paiement : le taux EUR → USD de la BCE ───────────────────────────
_BCE_DATE = re.compile(r"""\btime\s*=\s*['"](\d{4}-\d{2}-\d{2})['"]""")
_BCE_USD = re.compile(r"""\bcurrency\s*=\s*['"]USD['"]\s+rate\s*=\s*['"](\d+(?:\.\d+)?)['"]""")


def _bce_http() -> str:
    """Le fichier du jour de la BCE (bouchonné dans les tests). Lève en cas
    de panne."""
    import requests
    r = requests.get(BCE_URL, timeout=(3, 5), headers={"User-Agent": "youl4b-infloww-liens/1.0"})
    r.raise_for_status()
    return r.text


def lire_bce(xml: Any) -> Tuple[Optional[float], str]:
    """(dollars pour 1 euro, jour de publication) tirés du XML de la BCE ;
    (None, "") si le fichier ne se lit pas ou si le taux est absurde."""
    s = str(xml or "")
    m, d = _BCE_USD.search(s), _BCE_DATE.search(s)
    if not m or not d:
        return None, ""
    try:
        taux = float(m.group(1))
        dt.date.fromisoformat(d.group(1))
    except ValueError:
        return None, ""
    return (taux, d.group(1)) if 0.5 <= taux <= 3.0 else (None, "")


def taux_eur_usd(maintenant: Optional[float] = None) -> Dict[str, Any]:
    """{taux, date, panne} : le taux du jour (lu une fois par jour), sinon le
    dernier connu avec la panne qui empêche de le relire, sinon taux None.
    Ne lève pas."""
    maintenant = time.time() if maintenant is None else maintenant
    jour = _aujourdhui()
    with _VERROU_BCE:
        c = _lire_json(BCE_FICHIER)
        taux = _f_ou_none(c.get("taux"))
        if taux is not None and not 0.5 <= taux <= 3.0:
            taux = None
        if taux is not None and c.get("jour_lu") == jour:
            return {"taux": taux, "date": str(c.get("date") or ""), "panne": ""}
        if 0 <= maintenant - float(c.get("echec_t") or 0) < BCE_REESSAI_S:
            panne = f"{c.get('echec') or '?'} (essai du {_heure(c.get('echec_t'))})"
        else:
            try:
                neuf, date = lire_bce(_bce_http())
                panne = "" if neuf is not None else "réponse de la BCE illisible"
            except Exception as e:
                neuf, date, panne = None, "", f"{type(e).__name__} : {e}"[:200]
            if neuf is not None:
                safe_json.write(BCE_FICHIER, {"taux": neuf, "date": date, "jour_lu": jour, "lu": maintenant})
                return {"taux": neuf, "date": date, "panne": ""}
            safe_json.write(BCE_FICHIER, dict(c, echec=panne, echec_t=maintenant))
            panne = f"{panne} (essai du {_heure(maintenant)})"
        return {"taux": taux, "date": str(c.get("date") or "") if taux is not None else "", "panne": panne}


# ─── le paiement : les subs de chaque quinzaine (MyPuls) ─────────────────
def _q_disque() -> Dict[str, Any]:
    t = _lire_json(QUINZ_FICHIER).get("tranches")
    return dict(t) if isinstance(t, Mapping) else {}


def _t_entree(e: Any, *champs: str) -> float:
    """Le plus récent des horodatages `champs` d'une tranche gardée (0 sinon)."""
    if not isinstance(e, Mapping):
        return 0.0
    return max([_f_ou_none(e.get(c)) or 0.0 for c in champs] + [0.0])


def _connus(e: Any) -> Dict[str, int]:
    """Les subs CONNUS d'une tranche gardée. Un lien sans nombre (None, que la
    version d'avant écrivait) n'en fait pas partie : c'est un trou, à relire."""
    s = e.get("subs") if isinstance(e, Mapping) else None
    if not isinstance(s, Mapping):
        return {}
    out: Dict[str, int] = {}
    for c, n in s.items():
        v = _entier(n)
        if v is not None:
            out[str(c)] = v
    return out


def _liens_tranche(connus: Mapping[str, int]) -> List[Dict[str, Any]]:
    return [{"id": f"mypuls:{c}", "code": str(c), "abonnes": int(n), "nom": ""} for c, n in connus.items()]


def _bornes_ok(v: Mapping[str, Any], du: str, au: str) -> bool:
    """MyPuls a-t-il compté exactement les jours demandés ? (bornes qu'il rend
    avec ses chiffres). Absentes : on ne sait pas, donc non."""
    pm = v.get("periode_mypuls")
    return (isinstance(pm, Mapping) and str(pm.get("from") or "")[:10] == du
            and str(pm.get("to") or "")[:10] == au)


def _quinzaine_entiere(k: str) -> bool:
    try:
        du, au = (dt.date.fromisoformat(x) for x in str(k).split("|", 1))
    except ValueError:
        return False
    return quinzaine_de(du) == (du, au)


def _elaguer_tranches(tr: Mapping[str, Any], maintenant: float) -> Dict[str, Any]:
    """Garde pour toujours les quinzaines entières et les morceaux de début de
    paie ; un autre morceau (une période choisie au hasard, 21/09 → 25/09)
    sort après QUINZ_GARDE_S sans servir, comme les clics US (_elaguer)."""
    return {k: e for k, e in tr.items()
            if isinstance(e, Mapping) and (_quinzaine_entiere(k) or e.get("debut")
                                           or maintenant - _t_entree(e, "vu", "relu", "lu") < QUINZ_GARDE_S)}


def _garder_tranche(du: str, au: str, v: Mapping[str, Any],
                    maintenant: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Une tranche lue APRÈS son dernier jour : ses subs CONNUS, lien par
    lien, sur disque (sans revenu : le paiement n'en a pas besoin). Un lien
    sans nombre de subs, ou absent de la lecture, n'y est pas écrit : il reste
    un trou, relu plus tard (_etat_tranche) — le 26/09, un None gardé gelait
    le gain à « — » pour toujours. Une valeur déjà gardée ne change plus.
    Rien n'est gardé d'une lecture incomplète (pagination coupée) ni d'une
    lecture sur d'autres jours que ceux demandés. Rend l'entrée gardée, ou
    None."""
    if v.get("erreur") or v.get("tronque") or not str(v.get("lu_jour") or "") > au:
        return None
    if not _bornes_ok(v, du, au):
        return None
    connus: Dict[str, int] = {}
    for x in v.get("liens") or []:
        n = _entier(x.get("abonnes")) if isinstance(x, Mapping) and x.get("code") else None
        if n is not None:
            connus[str(x["code"])] = n
    lu = float(v.get("lu_a") or time.time())
    maintenant = time.time() if maintenant is None else maintenant
    with _VERROU_Q:
        c = _lire_json(QUINZ_FICHIER)
        tr = dict(c.get("tranches") or {}) if isinstance(c.get("tranches"), Mapping) else {}
        k = _cle_periode(du, au)
        e = tr.get(k) if isinstance(tr.get(k), Mapping) else {}
        if e and lu <= _t_entree(e, "relu", "lu"):
            return dict(e)                 # cette lecture-là est déjà rangée
        neuf: Dict[str, Any] = {"lu": _t_entree(e, "lu") or lu, "relu": lu,
                                "subs": dict(connus, **_connus(e)), "vu": max(_t_entree(e, "vu"), lu)}
        if e.get("debut"):
            neuf["debut"] = True
        tr[k] = neuf
        safe_json.write(QUINZ_FICHIER, {"tranches": _elaguer_tranches(tr, maintenant), "maj": maintenant})
        return dict(neuf)


def _toucher_tranches(cles: Any, debuts: Any, maintenant: Optional[float] = None) -> None:
    """Note que ces tranches gardées servent encore (« vu », au jour près) et
    marque les morceaux de début de paie (gardés pour toujours) ; élague au
    passage. UNE écriture au plus, et aucune si rien ne change."""
    maintenant = time.time() if maintenant is None else maintenant
    cles = {_cle_periode(*k) for k in cles}
    debuts = {_cle_periode(*k) for k in debuts}
    with _VERROU_Q:
        c = _lire_json(QUINZ_FICHIER)
        tr = dict(c.get("tranches") or {}) if isinstance(c.get("tranches"), Mapping) else {}
        change = False
        for k in cles | debuts:
            e = tr.get(k)
            if not isinstance(e, Mapping):
                continue
            e2 = dict(e)
            if k in cles and maintenant - _t_entree(e, "vu", "relu", "lu") >= QUINZ_VU_PAS_S:
                e2["vu"] = maintenant
            if k in debuts:
                e2["debut"] = True
            if e2 != e:
                tr[k] = e2
                change = True
        if change:
            safe_json.write(QUINZ_FICHIER, {"tranches": _elaguer_tranches(tr, maintenant), "maj": maintenant})


def _etat_tranche(du: str, au: str, disque: Mapping[str, Any], maintenant: float,
                  codes: Any = ()) -> Dict[str, Any]:
    """{liens} quand la tranche est lue (disque, ou mémoire même périmée),
    plus « a_lire » s'il faut la (re)lire, « en_cours » si une lecture est en
    vol, « erreur » si MyPuls vient d'échouer.

    `codes` : les liens dont les personnes réglées ont besoin. Le disque ne
    fait foi que s'il les a TOUS ; sinon la tranche est relue — au plus une
    fois par QUINZ_TROU_REESSAI_S (« trou_relu ») : un lien que MyPuls ne
    connaît pas ne coûte pas une lecture toutes les 10 min."""
    d = disque.get(_cle_periode(du, au))
    d = d if isinstance(d, Mapping) else None
    connus = _connus(d)
    if d is not None and set(codes) <= set(connus):
        return {"liens": _liens_tranche(connus), "disque": True}
    cle = (du, au)
    with _VERROU_MP:
        hit = _MYPULS_CACHE.get(cle)
        ech = _MYPULS_ECHECS.get(cle)
        vol = _MYPULS_FILS.get(cle)
    out: Dict[str, Any] = {}
    relu = _t_entree(d, "relu", "lu")
    if hit:
        out["liens"] = list(hit["v"].get("liens") or [])
        g = _garder_tranche(du, au, hit["v"])
        if g and set(codes) <= set(_connus(g)):
            return {"liens": _liens_tranche(_connus(g)), "disque": True}
        relu = max(relu, _t_entree(g, "relu", "lu"))
        if 0 <= maintenant - hit["t"] < MYPULS_TTL_S:
            return out
    elif connus:
        out["liens"] = _liens_tranche(connus)
    if relu and 0 <= maintenant - relu < QUINZ_TROU_REESSAI_S:
        # relue il y a moins d'une heure, toujours à trou : le trou tient à
        # MyPuls, pas à la lecture ; ce qui est connu sert, le reste est dit
        out.setdefault("liens", _liens_tranche(connus))
        out["trou_relu"] = relu
        return out
    if vol and vol["fil"].is_alive():
        out["en_cours"] = True
    elif ech and 0 <= maintenant - ech["t"] < MYPULS_ECHEC_S:
        out["erreur"] = str(ech.get("raison") or "?")
    else:
        out["a_lire"] = True
    return out


def _dormir_q(s: float) -> None:
    time.sleep(s)


def _lire_tranches(cles: List[Tuple[str, str]]) -> None:
    """Le fil des quinzaines : UNE lecture MyPuls à la fois, une pause entre
    deux, arrêt au premier échec (et plus aucune lecture de tranche pendant
    MYPULS_ECHEC_S). Ne lève pas."""
    appels = 0
    for du, au in cles:
        cle = (du, au)
        if appels:
            _dormir_q(QUINZ_PAUSE_S)
        with _VERROU_MP:
            hit = _MYPULS_CACHE.get(cle)
            vol = _MYPULS_FILS.get(cle)
            if (hit and 0 <= time.time() - hit["t"] < MYPULS_TTL_S) or (vol and vol["fil"].is_alive()):
                continue           # lue entre-temps, ou déjà en vol (la vue elle-même)
            _MYPULS_FILS[cle] = {"fil": threading.current_thread(), "debut": time.time()}
        appels += 1
        _releve_mypuls(du, au)
        with _VERROU_MP:
            neuf = _MYPULS_CACHE.get(cle)
            ech = _MYPULS_ECHECS.get(cle)
        if neuf is not None and neuf is not hit:
            _garder_tranche(du, au, neuf["v"])
            continue
        _FIL_Q["pause"] = time.time() + MYPULS_ECHEC_S
        _FIL_Q["raison"] = str((ech or {}).get("raison") or "lecture sans résultat")[:300]
        break


def _lancer_tranches(cles: List[Tuple[str, str]]) -> Optional[threading.Thread]:
    """Au plus QUINZ_APPELS_MAX lectures, dans UN fil à la fois : un
    rechargement pendant la lecture n'en lance pas d'autres."""
    cles = list(cles)[:QUINZ_APPELS_MAX]
    if not cles or time.time() < float(_FIL_Q.get("pause") or 0):
        return None
    if not QUINZ_EN_FOND:
        _lire_tranches(cles)
        return None
    with _VERROU_Q:
        f = _FIL_Q.get("fil")
        if f is not None and f.is_alive():
            return f
        f = threading.Thread(target=_lire_tranches, args=(cles,), daemon=True,
                             name="infloww-liens-quinzaines")
        _FIL_Q["fil"] = f
        f.start()
        return f


def _codes_personne(x: Mapping[str, Any]) -> set:
    """Les codes de suivi d'une personne : ceux rattachés dans le tableau, et
    ceux de ses liens GMS que la source ne connaît pas (introuvables avec un
    code). Un lien GMS sans adresse de suivi n'en a pas."""
    return ({str(r.get("code")) for r in x.get("infloww") or [] if r.get("code")}
            | {str(r.get("code")) for r in x.get("introuvables") or [] if r.get("code")})


def _subs_par_personne(liens: List[Any], gms: List[Any]
                       ) -> Tuple[Dict[str, Optional[int]], Dict[str, List[str]]]:
    """Les subs de chaque personne dans une lecture MyPuls, par la règle du
    tableau (construire : liens DISTINCTS, rattachés par l'adresse), et ses
    codes à trou. None : aucun lien rattaché, un lien dont MyPuls ne donne
    pas les subs, ou un de ses liens absent de la lecture — une prime ne se
    calcule pas sur un compte à trou (une tranche gardée n'a que les subs
    connus : sans ce dernier cas, un lien manquant y serait compté zéro)."""
    t = construire(liens, gms)
    sans = {str(x.get("id")) for x in liens if isinstance(x, Mapping) and x.get("abonnes") is None}
    out: Dict[str, Optional[int]] = {}
    trous: Dict[str, List[str]] = {}
    for x in t["lignes"]:
        ids = {str(r.get("id")) for r in x.get("infloww") or []}
        tr = ({str(r.get("code")) for r in x.get("infloww") or [] if str(r.get("id")) in sans}
              | {str(r.get("code")) for r in x.get("introuvables") or [] if r.get("code")})
        trous[x["cle"]] = sorted(tr, key=lambda c: (len(c), c))
        out[x["cle"]] = None if (not ids or tr) else _entier(x.get("subs"))
    return out, trous


# ─── le paiement : les lignes actives (clics GetMySocial, lien par lien) ─
def _lignes_cache() -> Dict[str, Any]:
    return _lire_json(LIGNES_FICHIER)


def _tranches_lg(cache: Any) -> Dict[str, Any]:
    t = cache.get("tranches") if isinstance(cache, Mapping) else None
    return dict(t) if isinstance(t, Mapping) else {}


def _entree_lg(tranches: Mapping[str, Any], k: str, lid: str) -> Dict[str, Any]:
    bloc = tranches.get(k)
    liens = bloc.get("liens") if isinstance(bloc, Mapping) else None
    e = liens.get(lid) if isinstance(liens, Mapping) else None
    return dict(e) if isinstance(e, Mapping) else {}


def _index_lg(tranches: Mapping[str, Any]) -> Dict[str, List[Tuple[str, str, Mapping[str, Any]]]]:
    """{lien: [(du, au, relevé)]} : chaque recherche ne parcourt que les
    relevés de SON lien. Sans index, la vue « depuis toujours » (vingt-cinq
    tranches, trente liens) relisait tout le fichier pour chaque couple."""
    idx: Dict[str, List[Tuple[str, str, Mapping[str, Any]]]] = {}
    for k, bloc in tranches.items():
        d0, _, d1 = str(k).partition("|")
        liens = bloc.get("liens") if isinstance(bloc, Mapping) else None
        if not d1 or not isinstance(liens, Mapping):
            continue
        for lid, e in liens.items():
            if isinstance(e, Mapping):
                idx.setdefault(str(lid), []).append((d0, d1, e))
    return idx


def etat_lien(tranches: Mapping[str, Any], lid: Any, du: str, au: str, jour: str,
              index: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Ce qu'on sait des clics du lien GMS `lid` sur [du, au] (AAAA-MM-JJ) :
    {etat} = « actif » (au moins un clic, tous pays), « inactif » (zéro
    CONFIRMÉ), « rate » (dernier relevé raté : raison, essai, essais),
    « perime » (zéro relevé pendant la tranche, qui a pu bouger depuis) ou
    « absent ».

    Un relevé sert aussi une autre tranche quand il la tranche sans
    ambiguïté : un clic sur [d0, d1] inclus dans [du, au] rend la ligne
    active (relevé hier sur 16 → 26, vue d'aujourd'hui 16 → 27 : pas d'appel) ;
    un zéro sur une plage qui contient [du, au], relevé après `au` ou
    aujourd'hui, la rend inactive. Jamais un zéro inventé : un lien sans
    relevé valable n'est ni l'un ni l'autre."""
    lid = str(lid)
    zero = False
    e: Mapping[str, Any] = {}
    for d0, d1, r in (_index_lg(tranches) if index is None else index).get(lid) or ():
        if (d0, d1) == (du, au):
            e = r
        n = _entier(r.get("clics"))
        if n is None:
            continue
        if n > 0 and du <= d0 and d1 <= au:
            return {"etat": "actif"}
        if n == 0 and d0 <= du and au <= d1:
            j = str(r.get("jour") or "")
            if j > au or j == jour:
                zero = True
    if zero:
        return {"etat": "inactif"}
    if e.get("rate"):
        return {"etat": "rate", "raison": str(e["rate"]), "essai": _f_ou_none(e.get("essai")) or 0.0,
                "essais": _entier(e.get("essais")) or 0, "essais_jour": str(e.get("essais_jour") or "")}
    return {"etat": "perime" if _entier(e.get("clics")) is not None else "absent"}


def _a_relever(st: Mapping[str, Any], jour: str, maintenant: float) -> bool:
    """Absent ou périmé : oui. Raté : après 10 min, trois fois par jour au
    plus — chaque essai coûte un appel du quota partagé."""
    if st.get("etat") in ("absent", "perime"):
        return True
    if st.get("etat") != "rate":
        return False
    if 0 <= maintenant - float(st.get("essai") or 0) < US_REESSAI_S:
        return False
    return not (st.get("essais_jour") == jour and int(st.get("essais") or 0) >= US_PERIODE_ESSAIS_MAX)


def _tranche_entiere(k: str) -> bool:
    """« 2026-09-01|2026-09-15 » ou « 2026-09-01|2026-09-30 » : une
    quinzaine ou un mois ENTIER, qui resservira tel quel."""
    try:
        du, au = (dt.date.fromisoformat(x) for x in str(k).split("|", 1))
    except ValueError:
        return False
    return quinzaine_de(du) == (du, au) or mois_de(du) == (du, au)


def cle_tranche_entiere(k: Any) -> str:
    """La clé « AAAA-MM-JJ|AAAA-MM-JJ » d'une quinzaine ou d'un mois entier,
    sous sa forme exacte ; "" pour autre chose."""
    try:
        du, au = (dt.date.fromisoformat(x) for x in str(k).split("|", 1))
    except ValueError:
        return ""
    if quinzaine_de(du) != (du, au) and mois_de(du) != (du, au):
        return ""
    return _cle_periode(du.isoformat(), au.isoformat())


def _k_entiere(t: Mapping[str, Any]) -> str:
    """La tranche ENTIÈRE (quinzaine ou mois) d'un morceau de decouper."""
    return _cle_periode(t["p_du"].isoformat(), t["p_au"].isoformat())


def _elaguer_lignes(tr: Mapping[str, Any], maintenant: float) -> Dict[str, Any]:
    """Quinzaines et mois entiers gardés pour toujours ; un morceau de
    période (« 7 derniers jours », une autre tranche chaque jour) sort après
    LIGNES_GARDE_S sans servir : sans ça, une entrée par lien et par jour."""
    out: Dict[str, Any] = {}
    for k, bloc in tr.items():
        if not isinstance(bloc, Mapping):
            continue
        liens = bloc.get("liens") if isinstance(bloc.get("liens"), Mapping) else {}
        dernier = max([_f_ou_none(bloc.get("vu")) or 0.0]
                      + [max(_f_ou_none(e.get("quand")) or 0.0, _f_ou_none(e.get("essai")) or 0.0)
                         for e in liens.values() if isinstance(e, Mapping)])
        if _tranche_entiere(k) or maintenant - dernier < LIGNES_GARDE_S:
            out[k] = bloc
    return out


def _ecrire_lien(k: str, lid: str, e: Mapping[str, Any], jour: str, faits: int) -> Dict[str, Any]:
    """Range le relevé d'UN lien sur une tranche, fichier relu sous verrou
    (la page a pu noter un « vu » entre-temps). Rend les tranches à jour."""
    with _VERROU_LG_F:
        c = _lignes_cache()
        tr = _tranches_lg(c)
        bloc = dict(tr[k]) if isinstance(tr.get(k), Mapping) else {}
        liens = dict(bloc.get("liens") or {}) if isinstance(bloc.get("liens"), Mapping) else {}
        liens[str(lid)] = dict(e)
        maintenant = time.time()
        bloc["liens"] = liens
        bloc.setdefault("vu", maintenant)
        tr[k] = bloc
        tr = _elaguer_lignes(tr, maintenant)
        faits = max(int(faits), _appels_du_jour(c, jour))
        safe_json.write(LIGNES_FICHIER, {"tranches": tr, "appels": {jour: faits}, "maj": maintenant})
        return tr


def _toucher_lignes(cles: Any, maintenant: Optional[float] = None) -> None:
    """Note que ces tranches servent encore (« vu », au jour près) : un
    morceau de période resservi à chaque affichage n'est pas élagué. UNE
    écriture au plus, aucune si rien ne change."""
    maintenant = time.time() if maintenant is None else maintenant
    with _VERROU_LG_F:
        c = _lignes_cache()
        tr = _tranches_lg(c)
        change = False
        for k in {_cle_periode(*k) for k in cles}:
            bloc = tr.get(k)
            if isinstance(bloc, Mapping) and maintenant - (_f_ou_none(bloc.get("vu")) or 0.0) >= QUINZ_VU_PAS_S:
                tr[k] = dict(bloc, vu=maintenant)
                change = True
        if change:
            safe_json.write(LIGNES_FICHIER, dict(c, tranches=_elaguer_lignes(tr, maintenant), maj=maintenant))


def _clics_releve(tot: Any, pays: Any) -> Optional[int]:
    """Les clics TOUS PAYS d'un relevé gms (total, pays) ; None s'il n'y en a
    pas (appel raté)."""
    if not isinstance(pays, Mapping):
        return None
    s = 0
    for v in pays.values():
        s += _entier(v) or 0
    return max(_entier(tot) or 0, s)


def releve_lignes(taches: List[Tuple[str, str, str]],
                  proprios: Optional[Mapping[Tuple[str, str, str], Tuple[str, str]]] = None) -> Dict[str, Any]:
    """Les clics de chaque (lien GMS, du, au) de `taches` sans relevé
    valable : UN appel gms.analytics_for_link chacun, dans l'ordre reçu
    (personne par personne : quand le budget tombe, mieux vaut des personnes
    complètes que toutes à moitié).

    `proprios` : (personne, nom du lien) de chaque tâche, notés dans le relevé
    (« qui », « nom ») au PREMIER relevé de ce lien sur cette tranche, et
    gardés ensuite : un renommage ne déplace plus la ligne d'une tranche déjà
    relevée vers une autre personne.

    (0 clic, aucun pays) est ambigu — c'est aussi ce que gms rend quand il
    n'a pas su lire la réponse (26/09 : « NOTICE: stale: true » après le
    JSON) : relu dans la réponse brute (_verifier_zero), un appel de plus. Un
    relevé raté n'est jamais écrit comme un zéro. Chaque appel, vérification
    comprise, est décompté de LIGNES_APPELS_JOUR ; GetMySocial en pause : on
    s'arrête, le reste attend."""
    if not _VERROU_LG.acquire(blocking=False):
        return {"appels": 0, "rates": 0, "occupe": True}
    try:
        jour = _aujourdhui()
        cache = _lignes_cache()
        tr = _tranches_lg(cache)
        idx = _index_lg(tr)
        maintenant = time.time()
        cibles = list(dict.fromkeys((str(l), str(d), str(a)) for l, d, a in taches
                                    if _a_relever(etat_lien(tr, l, d, a, jour, idx), jour, maintenant)))
        if not cibles:
            return {"appels": 0, "rates": 0}
        budget = LIGNES_APPELS_JOUR
        faits = _appels_du_jour(cache, jour)
        if faits >= budget:
            return {"appels": 0, "rates": 0, "budget": budget}
        if _pause_gms() > 0:
            return {"appels": 0, "rates": 0, "pause": True}
        import gms
        rates = appels = mesures = 0
        for i, (lid, du, au) in enumerate(cibles):
            if i and _pause_gms():
                break                 # quota tombé en route : les suivants restent à relever
            if faits >= budget:
                break                 # budget du jour atteint : idem, jusqu'à demain
            if not _a_relever(etat_lien(tr, lid, du, au, jour, idx), jour, time.time()):
                mesures += 1          # tranché entre-temps par un relevé de cette passe
                continue
            raison = ""
            appels += 1
            faits += 1
            try:
                tot, pays = gms.analytics_for_link(lid, du, au)
            except Exception as e:
                tot, pays, raison = None, None, f"{type(e).__name__} : {e}"[:160]
            clics = _clics_releve(tot, pays)
            if clics == 0:
                if faits >= budget:
                    clics, raison = None, "relevé à 0 clic non vérifié : budget GetMySocial du jour atteint"
                else:
                    appels += 1
                    faits += 1
                    t2, p2, raison = _verifier_zero([lid], du, au)
                    clics = _clics_releve(t2, p2)
            mesures += 1
            k = _cle_periode(du, au)
            e = _entree_lg(tr, k, lid)
            e["essai"] = time.time()
            qui = (proprios or {}).get((lid, du, au))
            if qui and not e.get("qui"):
                e["qui"], e["nom"] = str(qui[0]), str(qui[1])
            if clics is None:
                rates += 1
                if not raison and _pause_gms():
                    raison = "quota GetMySocial épuisé" + _reprise_gms()
                n = int(e.get("essais") or 0) if e.get("essais_jour") == jour else 0
                e.update(rate=f"{jour} : " + (raison or "GetMySocial n'a pas rendu de relevé"),
                         essais=n + 1, essais_jour=jour)
            else:
                e.update(clics=int(clics), quand=time.time(), jour=jour, rate="", essais=0)
            tr = _ecrire_lien(k, lid, e, jour, faits)
            idx = _index_lg(tr)
            if i + 1 < len(cibles):
                _dormir_us(US_PAUSE_S)
        return {"appels": appels, "rates": rates, "reportes": len(cibles) - mesures,
                "budget": budget if faits >= budget and mesures < len(cibles) else 0}
    finally:
        _VERROU_LG.release()


def _lancer_lignes(taches: List[Tuple[str, str, str]],
                   proprios: Optional[Mapping[Tuple[str, str, str], Tuple[str, str]]] = None
                   ) -> Optional[threading.Thread]:
    """En arrière-plan, un relevé à la fois (verrou à part de _VERROU, que
    l'envoi Discord garde pendant tout un passage : la page n'attend pas)."""
    if not LIGNES_EN_FOND:
        releve_lignes(taches, proprios)
        return None
    with _VERROU_LG_LANCE:
        f = _FIL_LG.get("fil")
        if f is not None and f.is_alive():
            return f
        f = threading.Thread(target=releve_lignes, args=(list(taches), dict(proprios or {})), daemon=True,
                             name="infloww-liens-lignes")
        _FIL_LG["fil"] = f
        f.start()
        return f


def _info_lignes(reste: int, jour: str) -> Dict[str, Any]:
    """Pourquoi des lignes attendent encore : budget du jour, pause
    GetMySocial ou calcul en cours ({} si rien n'attend un appel)."""
    if not reste:
        return {}
    if _appels_du_jour(_lignes_cache(), jour) >= LIGNES_APPELS_JOUR:
        return {"budget": LIGNES_APPELS_JOUR}
    if _pause_gms():
        return {"pause": "quota du jour épuisé" + _reprise_gms()}
    return {"en_cours": True}


def _lignes_pour_la_page(taches: List[Tuple[str, str, str]],
                         proprios: Optional[Mapping[Tuple[str, str, str], Tuple[str, str]]] = None
                         ) -> Dict[str, Any]:
    """Lance le relevé de ce qui manque, SANS l'attendre ; rien si le budget
    du jour est fait ou si GetMySocial est en pause. Rend ce que la page doit
    en dire."""
    if not taches:
        return {}
    info = _info_lignes(len(taches), _aujourdhui())
    if info.get("en_cours"):
        _lancer_lignes(taches, proprios)
    return info


def _figer_lignes(gels: Mapping[str, Mapping[str, Any]], maintenant: Optional[float] = None) -> None:
    """Fige, UNE fois pour toutes, les lignes de tranches closes entièrement
    relevées : {tranche: {personne: {quand, liens: {lien: {nom, actif}}}}}.
    Une personne déjà figée sur une tranche ne l'est jamais une seconde fois.
    UNE écriture, aucune si rien n'est nouveau."""
    maintenant = time.time() if maintenant is None else maintenant
    with _VERROU_LG_F:
        c = _lignes_cache()
        tr = _tranches_lg(c)
        change = False
        for k, pers in gels.items():
            bloc = dict(tr[k]) if isinstance(tr.get(k), Mapping) else {"liens": {}, "vu": maintenant}
            fige = dict(bloc.get("fige") or {}) if isinstance(bloc.get("fige"), Mapping) else {}
            for cle, v in pers.items():
                if cle not in fige:
                    fige[cle] = dict(v)
                    change = True
            bloc["fige"] = fige
            tr[k] = bloc
        if change:
            safe_json.write(LIGNES_FICHIER, dict(c, tranches=_elaguer_lignes(tr, maintenant), maj=maintenant))


def _lignes_tranche(tr: Mapping[str, Any], idx: Mapping[str, Any], cle: str,
                    liens_now: List[Mapping[str, Any]], du: str, au: str, jour: str,
                    proprio: Mapping[str, str], noms: Mapping[str, str],
                    crees: Mapping[str, str]) -> Dict[str, Any]:
    """Les lignes de la personne `cle` sur la tranche [du, au] :
    {fige, sts: [(lien, état)], partis, exclus, pas_encore}.

    1. Tranche FIGÉE pour elle : l'ensemble gardé, tel quel (état compris).
    2. Sinon : ses liens du jour, SAUF ceux qu'un relevé de cette tranche a
       notés à une autre personne (ou figés chez une autre) ; PLUS ceux notés
       à elle, partis depuis (renommés, supprimés). Un lien jamais relevé sur
       la tranche : la liste du jour décide (rien d'autre n'est su).
    Un lien créé après la fin de la tranche n'y est pas une ligne
    (« pas_encore ») : aucun appel GetMySocial pour lui.
    `partis` : liens comptés, qui ne sont plus à elle aujourd'hui ;
    `exclus` : liens à elle aujourd'hui, pas comptés (à une autre sur la tranche)."""
    k = _cle_periode(du, au)
    bloc = tr.get(k) if isinstance(tr.get(k), Mapping) else {}
    fige = bloc.get("fige") if isinstance(bloc.get("fige"), Mapping) else {}
    rel = bloc.get("liens") if isinstance(bloc.get("liens"), Mapping) else {}
    miens = {str(l["id"]): str(l.get("nom") or l["id"]) for l in liens_now}
    a_autrui: Dict[str, str] = {}
    for c, v in fige.items():
        if str(c) != cle and isinstance(v, Mapping) and isinstance(v.get("liens"), Mapping):
            for lid in v["liens"]:
                a_autrui[str(lid)] = str(c)
    out: Dict[str, Any] = {"fige": False, "sts": [], "partis": [], "exclus": [], "pas_encore": []}

    def cree(lid: str) -> str:
        return crees.get(lid) or cree_gms(lid)

    mien_f = fige.get(cle)
    if isinstance(mien_f, Mapping) and isinstance(mien_f.get("liens"), Mapping):
        out["fige"] = True
        for lid, v in mien_f["liens"].items():
            v = v if isinstance(v, Mapping) else {}
            out["sts"].append(({"id": str(lid), "nom": str(v.get("nom") or lid)},
                               {"etat": "actif" if v.get("actif") else "inactif"}))
        figes = {l["id"] for l, _s in out["sts"]}
        for lid, nom in miens.items():
            if lid in figes:
                continue
            if cree(lid) and cree(lid) > au:
                out["pas_encore"].append({"nom": nom, "cree": cree(lid)})
            else:
                out["exclus"].append({"nom": nom, "chez": a_autrui.get(lid, "")})
    else:
        siens: Dict[str, str] = {}
        for lid, nom in miens.items():
            e = rel.get(lid) if isinstance(rel.get(lid), Mapping) else {}
            q = str(e.get("qui") or "")
            autre = a_autrui.get(lid) or (q if q and q != cle else "")
            if autre:
                out["exclus"].append({"nom": nom, "chez": autre})
            else:
                siens[lid] = nom
        for lid, e in rel.items():
            lid = str(lid)
            if (lid not in siens and lid not in miens and lid not in a_autrui and isinstance(e, Mapping)
                    and str(e.get("qui") or "") == cle):
                siens[lid] = str(e.get("nom") or noms.get(lid) or lid)
        for lid, nom in siens.items():
            if cree(lid) and cree(lid) > au:
                out["pas_encore"].append({"nom": nom, "cree": cree(lid)})
            else:
                out["sts"].append(({"id": lid, "nom": nom}, etat_lien(tr, lid, du, au, jour, idx)))
    out["sts"].sort(key=lambda s: (_cle_nom(s[0]["nom"]), s[0]["id"]))
    for l, _s in out["sts"]:
        if l["id"] not in miens:
            out["partis"].append({"nom": l["nom"], "chez": proprio.get(l["id"], ""),
                                  "nom_jour": noms.get(l["id"], "")})
    for cle_l in ("partis", "exclus", "pas_encore"):
        out[cle_l].sort(key=lambda d: _cle_nom(d["nom"]))
    return out


# ─── le paiement : le calcul ─────────────────────────────────────────────
def _plage_paie(x: Mapping[str, Any], cfg: Mapping[str, Any], per: Mapping[str, Any],
                liens_p: Mapping[str, Any], auj: dt.date) -> Tuple[Optional[dt.date], Optional[dt.date], str]:
    """[a, b] sur laquelle la personne est payée : la période affichée (à
    partir de « payé depuis » s'il tombe dedans), ou, depuis toujours, de
    « payé depuis » (sinon de la création de son plus ancien lien Infloww) à
    aujourd'hui. (None, None, pourquoi) si le début est inconnu."""
    depuis = _date_arg(cfg.get("depuis")) if cfg.get("depuis") else None
    if per.get("du") and per.get("au"):
        a, b = dt.date.fromisoformat(per["du"]), dt.date.fromisoformat(per["au"])
        return (max(a, depuis) if depuis else a), b, ""
    if depuis:
        return depuis, auj, ""
    crees = sorted(c for c in (str((liens_p.get(str(r.get("id"))) or {}).get("cree") or "")
                               for r in x.get("infloww") or []) if _date_arg(c))
    if not crees:
        return None, None, "début inconnu (aucune date de création Infloww) : renseignez « payé depuis »"
    return dt.date.fromisoformat(crees[0]), auj, ""


def _revenu(x: Mapping[str, Any], liens_p: Mapping[str, Any], devise_periode: str) -> Tuple[Optional[float], str]:
    """Le revenu NET de la personne, en dollars : la somme de ses liens
    DISTINCTS. (None, pourquoi) plutôt qu'un zéro inventé."""
    ids = [str(r.get("id")) for r in x.get("infloww") or []]
    if not ids:
        return None, "aucun lien de suivi rattaché : revenu inconnu"
    if devise_periode and devise_periode != "USD":
        return None, f"revenu MyPuls en {devise_periode}, pas en dollars"
    nets = [(liens_p.get(i) or {}).get("net") for i in ids]
    if any(n is None for n in nets):
        return None, "revenu illisible pour un de ses liens"
    autres = {str((liens_p.get(i) or {}).get("devise") or "") for i in ids} - {"", "USD"}
    if autres:
        return None, f"revenu en {', '.join(sorted(autres))}, pas en dollars"
    return sum(int(n) for n in nets) / 100.0, ""


def _k_tranche(t: Mapping[str, Any]) -> Tuple[str, str]:
    return t["du"].isoformat(), t["au"].isoformat()


def avec_paie(t: Mapping[str, Any], attente: Optional[float] = None) -> Dict[str, Any]:
    """Le tableau, plus le paiement de chaque personne et ce qu'elle rapporte
    (colonnes Paiement et Gain / perte). Pour la PAGE seulement. `t` n'est
    pas modifié. Peut lancer des lectures MyPuls (subs par quinzaine) et
    attendre QUINZ_ATTENTE_S au plus, et lancer le relevé GetMySocial des
    lignes actives (sans l'attendre)."""
    attente = QUINZ_ATTENTE_S if attente is None else float(attente)
    out = dict(t)
    lignes = [dict(x) for x in t.get("lignes") or []]
    out["lignes"] = lignes
    cfgs, mauvais = lire_paie()
    presents = {str(x.get("cle")) for x in lignes}
    P: Dict[str, Any] = {"mauvais": mauvais, "taux": None, "en_attente": 0, "a_relire": 0, "erreurs": {},
                         "orphelins": sorted((c for c, v in cfgs.items()
                                              if c not in presents and v["type"] != "aucun"), key=_cle_nom),
                         "configures": 0, "totaux": {}, "pause": "", "lignes": {}}
    out["paie"] = P
    for x in lignes:
        cfg = cfgs.get(str(x.get("cle")))
        x["paie"] = {"cfg": cfg, "resume": resume_paie(cfg)}
        x["gain"] = None
    if t.get("erreur"):
        P["orphelins"] = []            # pas de tableau : personne n'est « absent »
        return out
    per = t.get("periode") or {}
    if not (per.get("du") and per.get("au")):
        per = {}
    P["vue"] = "periode" if per else "toujours"
    liens_p = t.get("_paie_liens") or {}
    gms = t.get("_gms") or []
    try:
        auj = dt.date.fromisoformat(_aujourdhui())
    except ValueError:
        auj = dt.date.today()
    actifs = [x for x in lignes if (x["paie"]["cfg"] or {}).get("type") in TYPES_PAYES]
    P["configures"] = len(actifs)
    if not actifs:
        return out
    if any(x["paie"]["cfg"]["devise"] == "EUR" for x in actifs):
        P["taux"] = taux_eur_usd()

    # 1. plages, et quinzaines dont il faut les subs (primes, paie au sub)
    maintenant = time.time()
    disque = _q_disque()
    # par tranche, les codes de suivi dont les personnes réglées ont besoin :
    # le disque ne fait foi que s'il les a tous
    codes_q: Dict[Tuple[str, str], set] = {}
    debuts: set = set()
    for x in actifs:
        p, cfg = x["paie"], x["paie"]["cfg"]
        a, b, raison = _plage_paie(x, cfg, per, liens_p, auj)
        p.update(debut=a.isoformat() if a else "", fin=b.isoformat() if b else "", raison=raison)
        if a is None or cfg["type"] not in ("fixe_primes", "au_sub"):
            continue
        p["quinzaines"] = decouper(a, b, "quinzaine")
        codes_x = _codes_personne(x)
        for q in p["quinzaines"]:
            codes_q.setdefault(_k_tranche(q), set()).update(codes_x)
        # le morceau qui commence au premier jour payé (« payé depuis », sinon
        # la création du lien en vue « depuis toujours ») et finit avec sa
        # quinzaine : resservi à chaque affichage, gardé pour toujours
        q0 = p["quinzaines"][0] if p["quinzaines"] else None
        if (q0 and not q0["complete"] and q0["au"] == q0["p_au"]
                and (not per or a.isoformat() == cfg.get("depuis"))):
            debuts.add(_k_tranche(q0))
    besoins = {k: _etat_tranche(k[0], k[1], disque, maintenant, c) for k, c in codes_q.items()}
    # d'abord les tranches sans aucune lecture, puis les relectures (tranches
    # ouvertes dont la lecture a plus de 10 min, tranches closes à trou)
    a_lire = sorted((k for k, e in besoins.items() if e.get("a_lire")),
                    key=lambda k: ("liens" in besoins[k], k))
    if a_lire:
        f = _lancer_tranches(a_lire)
        if f is not None and attente > 0:
            f.join(attente)
        maintenant = time.time()
        disque = _q_disque()
        besoins = {k: _etat_tranche(k[0], k[1], disque, maintenant, c) for k, c in codes_q.items()}
    if time.time() < float(_FIL_Q.get("pause") or 0):
        P["pause"] = str(_FIL_Q.get("raison") or "")
    _toucher_tranches(besoins, debuts, maintenant)
    subs_q: Dict[Tuple[str, str], Dict[str, Optional[int]]] = {}
    trous_q: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    for k, e in besoins.items():
        if "liens" in e:
            subs_q[k], trous_q[k] = _subs_par_personne(e["liens"], gms)
        elif e.get("erreur"):
            P["erreurs"][k] = e["erreur"]
    attente_k: set = set()

    # 1 bis. les lignes actives des types à fixe : chaque lien GMS de la
    # personne, sur chaque tranche de son fixe (quinzaine ou mois, partie
    # incluse dans la plage). Relevé lancé en arrière-plan pour ce qui manque.
    ents_g, _sans = entites(gms)
    par_id_g = {str(l.get("id")): l for l in gms if isinstance(l, Mapping) and l.get("id")}
    proprio_g = {str(i): str(c) for c, e in ents_g.items() for i in e.get("ids") or []}
    noms_g = {i: nom_gms(l) or i for i, l in par_id_g.items()}
    crees_g = {i: cree_gms(l) for i, l in par_id_g.items()}
    jour = _aujourdhui()
    fixes: List[Dict[str, Any]] = []             # personne par personne
    for x in sorted(actifs, key=lambda x: _cle_nom(x.get("cle"))):
        p, cfg = x["paie"], x["paie"]["cfg"]
        if cfg["type"] not in TYPES_FIXE or not p.get("debut"):
            continue
        ids = sorted({str(i) for i in (ents_g.get(str(x.get("cle"))) or {}).get("ids") or []})
        p["liens_gms"] = sorted(({"id": i, "nom": noms_g.get(i) or i} for i in ids),
                                key=lambda l: (_cle_nom(l["nom"]), l["id"]))
        p["tranches_f"] = decouper(dt.date.fromisoformat(p["debut"]), dt.date.fromisoformat(p["fin"]),
                                   cfg["frequence"])
        premiers = [crees_g.get(l["id"]) or "" for l in p["liens_gms"]]
        p["premier_lien"] = min(premiers) if premiers and all(premiers) else ""
        fixes.append(x)
    tr_lg = _tranches_lg(_lignes_cache()) if fixes else {}
    idx_lg = _index_lg(tr_lg)

    def etats_lignes() -> Tuple[Dict[Tuple[str, str, str], Dict[str, Any]],
                                Dict[Tuple[str, str, str], Tuple[str, str, Dict[str, Any]]]]:
        """({(personne, du, au): lignes de la tranche}, {(lien, du, au):
        (personne, nom, état)} des liens dont le compte sert) — une tranche
        figée ou aux lignes forcées ne demande aucun relevé."""
        res: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        besoin: Dict[Tuple[str, str, str], Tuple[str, str, Dict[str, Any]]] = {}
        for x in fixes:
            p, cfg = x["paie"], x["paie"]["cfg"]
            forces = cfg.get("forces") or {}
            for q in p["tranches_f"]:
                du_q, au_q = _k_tranche(q)
                r = _lignes_tranche(tr_lg, idx_lg, str(x["cle"]), p["liens_gms"], du_q, au_q, jour,
                                    proprio_g, noms_g, crees_g)
                r["force"] = forces.get(_k_entiere(q))
                res[(str(x["cle"]), du_q, au_q)] = r
                if r["force"] is None and not r["fige"]:
                    for l, st in r["sts"]:
                        besoin[(l["id"], du_q, au_q)] = (str(x["cle"]), l["nom"], st)
        return res, besoin

    res_lg, besoin_lg = etats_lignes()
    taches = [pr for pr, v in besoin_lg.items() if _a_relever(v[2], jour, time.time())]
    if taches:
        _lignes_pour_la_page(taches, {pr: besoin_lg[pr][:2] for pr in taches})
        tr_lg = _tranches_lg(_lignes_cache())   # relevé sur place (tests) ou déjà fait
        idx_lg = _index_lg(tr_lg)
        res_lg, besoin_lg = etats_lignes()
    # une tranche CLOSE dont tous les liens sont tranchés (un clic, ou un 0
    # relu après sa fin) est figée : la liste GMS de demain n'y change rien
    gels: Dict[str, Dict[str, Any]] = {}
    for (c, du_q, au_q), r in res_lg.items():
        if (not r["fige"] and au_q < jour and r["sts"]
                and all(s["etat"] in ("actif", "inactif") for _l, s in r["sts"])):
            gels.setdefault(_cle_periode(du_q, au_q), {})[c] = {
                "quand": time.time(),
                "liens": {l["id"]: {"nom": l["nom"], "actif": s["etat"] == "actif"} for l, s in r["sts"]}}
    if gels:
        _figer_lignes(gels)
    if res_lg:
        _toucher_lignes({k[1:] for k in res_lg})

    # 2. par personne : revenu - coût ; chaque manque est dit
    taux = (P.get("taux") or {}).get("taux")
    devise_periode = str(per.get("devise") or "") if per else ""
    lg_inconnus = 0
    lg_rates: List[str] = []

    def subs_des_quinzaines(x: Mapping[str, Any], p: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], int, str]:
        """(détail, quinzaines en attente, ce qui manque) des subs de la
        personne, quinzaine par quinzaine."""
        attente_q = 0
        manque_q = ""
        detail_q: List[Dict[str, Any]] = []
        for q in p.get("quinzaines") or []:
            k = _k_tranche(q)
            e = besoins.get(k) or {}
            s = (subs_q.get(k) or {}).get(str(x["cle"]))
            detail_q.append({"du": k[0], "au": k[1], "complete": q["complete"], "subs": s})
            if k in subs_q and s is not None:
                continue
            if e.get("a_lire") or e.get("en_cours"):
                attente_q += 1             # (re)lecture demandée ou en vol
                attente_k.add(k)
            elif k in subs_q:
                tr = (trous_q.get(k) or {}).get(str(x["cle"])) or []
                manque_q = manque_q or (
                    f"subs du {_libelle_periode(*k)} inconnus chez MyPuls"
                    + (f" pour {', '.join('c' + c for c in tr)}" if tr else "")
                    + " (lien absent ou sans nombre de subs"
                    + (f" ; relu le {_heure(e['trou_relu'])}, relu au plus une fois par heure"
                       if e.get("trou_relu") else "") + ")")
            elif k in P["erreurs"]:
                manque_q = manque_q or (f"MyPuls n'a pas répondu pour le {_libelle_periode(*k)} "
                                        f"({P['erreurs'][k][:160]})")
            else:
                attente_q += 1
                attente_k.add(k)
        return detail_q, attente_q, manque_q

    def en_attente(quoi: str, detail_q: List[Any], attente_q: int) -> str:
        lues = len(detail_q) - attente_q
        return (f"{quoi} : calcul en cours ({_nb(lues)} quinzaine{'s' if lues > 1 else ''} "
                f"lue{'s' if lues > 1 else ''} sur {_nb(len(detail_q))})")

    for x in actifs:
        p, cfg = x["paie"], x["paie"]["cfg"]
        typ = cfg["type"]
        rev, r_raison = _revenu(x, liens_p, devise_periode)
        p["revenu"] = rev
        if not p.get("debut"):
            continue                       # début inconnu : la raison est déjà dite
        raisons: List[str] = []
        cout: Optional[float] = 0.0
        if typ in TYPES_FIXE:
            # le fixe, PAR LIGNE ACTIVE de chaque tranche. Lignes forcées par
            # le propriétaire : elles, telles quelles. Compte à trou : les
            # « lignes payées » saisies, BORNÉES par ce qui est su (jamais
            # moins que les lignes déjà confirmées actives, jamais plus que la
            # personne n'a de liens) ; sinon « — ». Avant son premier lien
            # GMS : les lignes saisies, sinon « — » (rien n'est inventé).
            m = float(cfg["montant"])
            saisie = _entier(cfg.get("lignes"))
            detail_f: List[Dict[str, Any]] = []
            for q in p.get("tranches_f") or []:
                du_q, au_q = _k_tranche(q)
                r = res_lg.get((str(x["cle"]), du_q, au_q)) or {"sts": [], "fige": False, "partis": [],
                                                                 "exclus": [], "pas_encore": [], "force": None}
                sts = r["sts"]
                actives = [l["nom"] for l, s in sts if s["etat"] == "actif"]
                sans_clic = [l["nom"] for l, s in sts if s["etat"] == "inactif"]
                inconnus = [l["nom"] for l, s in sts if s["etat"] not in ("actif", "inactif")]
                force = r.get("force")
                if force is None:              # une tranche forcée n'attend aucun relevé
                    lg_rates += [s["raison"] for _l, s in sts if s["etat"] == "rate"]
                    lg_inconnus += len(inconnus)
                if force is not None:
                    n, source = int(force), "force"
                elif not sts and r["pas_encore"]:
                    n, source = saisie, "sans_lien"
                elif not inconnus:
                    n, source = len(actives), "gms"
                elif saisie:
                    n = len(actives) + min(len(inconnus), max(0, saisie - len(actives)))
                    source = "manuel"
                else:
                    n, source = None, ""
                base = m * q["jours"] / q["jours_periode"]
                detail_f.append({"du": du_q, "au": au_q, "complete": q["complete"], "jours": q["jours"],
                                 "jours_periode": q["jours_periode"], "base": base, "total": len(sts),
                                 "actives": None if inconnus else len(actives), "confirmees": len(actives),
                                 "lignes": n, "source": source, "saisie": saisie, "fige": r["fige"],
                                 "sans_clic": sans_clic, "inconnus": inconnus,
                                 "pas_encore": [d["nom"] for d in r["pas_encore"]],
                                 "partis": r["partis"], "exclus": r["exclus"],
                                 "premier_lien": p.get("premier_lien") or "",
                                 "montant": None if n is None else base * n})
            p["detail_f"] = detail_f
            manque_f = [f for f in detail_f if f["lignes"] is None]
            fixe_d = None if manque_f else sum(f["montant"] for f in detail_f)
            p["fixe_devise"] = fixe_d
            p["fixe"] = (None if fixe_d is None else
                         fixe_d if cfg["devise"] == "USD" else (fixe_d * taux if taux else None))
            en_cours_f = [f for f in manque_f if f["source"] == ""]
            sans_lien_f = [f for f in manque_f if f["source"] == "sans_lien"]
            if en_cours_f:
                p["en_cours"] = True
                noms = sorted({nm for f in en_cours_f for nm in f["inconnus"]}, key=_cle_nom)
                raisons.append(f"lignes actives : calcul en cours (clics GetMySocial pas encore relevés pour "
                               f"{', '.join(noms)}" + (f", sur {_nb(len(en_cours_f))} {cfg['frequence']}s"
                                                         if len(detail_f) > 1 else "") + ")")
            if sans_lien_f:
                raisons.append(f"lignes : pas encore de lien GetMySocial du {_jour_long(sans_lien_f[0]['du'])} au "
                               f"{_jour_long(sans_lien_f[-1]['au'])}"
                               + (f" (premier lien créé le {_jour_long(p['premier_lien'])})"
                                  if p.get("premier_lien") else "")
                               + " : renseignez « lignes payées » (ou « payé depuis »)")
            if not manque_f and p["fixe"] is None:
                raisons.append("taux EUR → USD inconnu : fixe en euros non converti")
            cout = p["fixe"]
        if rev is None:
            raisons.append(r_raison)
        if typ == "fixe_primes":
            detail_q, attente_q, manque_q = subs_des_quinzaines(x, p)
            for q in detail_q:
                if q["subs"] is not None:
                    q["prime"], q["palier"] = palier(q["subs"])
            if manque_q:
                raisons.append(manque_q)
            if attente_q:
                p["en_cours"] = True
                raisons.append(en_attente("primes", detail_q, attente_q))
            primes = None if (manque_q or attente_q) else sum(q["prime"] for q in detail_q)
            p["primes"], p["detail_q"] = primes, detail_q
            cout = None if (cout is None or primes is None) else cout + primes
        elif typ == "au_sub":
            # au sub, par quinzaine : le seuil s'applique aux subs de CHAQUE
            # quinzaine (une quinzaine coupée par la plage garde le seuil entier)
            detail_q, attente_q, manque_q = subs_des_quinzaines(x, p)
            for q in detail_q:
                if q["subs"] is not None:
                    q["cout"], q["bas"], q["haut"] = cout_au_sub(cfg, q["subs"])
            if manque_q:
                raisons.append(manque_q)
            if attente_q:
                p["en_cours"] = True
                raisons.append(en_attente("paie au sub", detail_q, attente_q))
            sub_d = None if (manque_q or attente_q) else sum(q["cout"] for q in detail_q)
            p["detail_q"], p["sub_devise"] = detail_q, sub_d
            p["cout_sub"] = (None if sub_d is None else
                             sub_d if cfg["devise"] == "USD" else (sub_d * taux if taux else None))
            if sub_d is not None and p["cout_sub"] is None:
                raisons.append("taux EUR → USD inconnu : paie au sub en euros non convertie")
            cout = p["cout_sub"]
        p["cout"] = cout
        p["raison"] = " ; ".join(raisons)
        if not raisons and cout is not None and rev is not None:
            p["gain"] = round(rev - cout, 2)
            x["gain"] = p["gain"]
    # les tranches qu'une personne attend : jamais lues, ou à relire (une
    # lecture d'avant avait un trou pour elle)
    P["en_attente"] = len(attente_k)
    P["a_relire"] = sum(1 for k in attente_k if "liens" in (besoins.get(k) or {}))
    if besoin_lg:
        reste = sum(1 for v in besoin_lg.values() if _a_relever(v[2], jour, time.time()))
        P["lignes"] = {"paires": len(besoin_lg), "inconnus": lg_inconnus, "a_relever": reste,
                       "rates": sorted(set(lg_rates))[:3], "info": _info_lignes(reste, jour)}

    # 3. totaux, sur les personnes configurées dont le gain se calcule. Le
    # revenu d'un lien visé par deux personnes n'y compte qu'UNE fois, comme
    # au total des subs.
    calcules = [x for x in actifs if x["gain"] is not None]
    T: Dict[str, Any] = {"configures": len(actifs), "calcules": len(calcules),
                         "revenu": None, "cout": None, "gain": None}
    if calcules:
        ids = {str(r.get("id")) for x in calcules for r in x.get("infloww") or []}
        T["revenu"] = sum(int((liens_p.get(i) or {}).get("net") or 0) for i in ids) / 100.0
        T["cout"] = sum(x["paie"]["cout"] for x in calcules)
        T["gain"] = round(T["revenu"] - T["cout"], 2)
    P["totaux"] = T
    return out


def page_refus_paie(pourquoi: str, retour: str) -> str:
    """Un réglage refusé : ce qui ne va pas, et le retour à la même vue.
    Aucun JavaScript ; tout est échappé (le message peut citer l'envoi)."""
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
            '<meta name="color-scheme" content="dark"><title>Réglage refusé</title>'
            '<style>body{margin:0 auto;max-width:560px;padding:24px 16px;background:#0e0e10;color:#f4f4f5;'
            'font:15px/1.5 -apple-system,system-ui,"Segoe UI",sans-serif}'
            '.err{background:rgba(239,68,68,.12);border:1px solid #ef4444;border-radius:12px;padding:14px 16px;'
            'overflow-wrap:anywhere}a{color:#f97341}</style></head><body>'
            f'<div class="err"><b>Réglage non enregistré.</b><br>{_e(pourquoi)}</div>'
            f'<p><a href="{_e(retour)}">Revenir au tableau</a> : rien n\'a changé.</p></body></html>')


def resume_paie(cfg: Optional[Mapping[str, Any]]) -> str:
    """« 75 $ / quinzaine + primes », « 200 EUR / mois », « 0,40 $ / sub
    jusqu'à 200, 0,50 $ au-delà », « — »."""
    if not cfg or cfg.get("type") not in TYPES_PAYES:
        return "—"
    dev = "$" if cfg.get("devise") == "USD" else "EUR"
    if cfg["type"] == "au_sub":
        return (f"{_taux_court(cfg['taux1'])} {dev} / sub jusqu'à {_nb(cfg['seuil'])}, "
                f"{_taux_court(cfg['taux2'])} {dev} au-delà")
    s = f"{_montant_court(cfg['montant'])} {dev} / {cfg['frequence']}"
    return s + (" + primes" if cfg["type"] == "fixe_primes" else "")


def _montant_court(m: Any) -> str:
    f = float(m or 0)
    return _nb(f) if f.is_integer() else _dec(f)


def _taux_court(v: Any) -> str:
    """Un prix par sub : « 0,40 », « 0,375 », « 1,00 » (deux décimales au
    moins, trois au plus : 0,375 ne s'affiche pas 0,38)."""
    s = f"{float(v or 0):.3f}"
    return (s[:-1] if s.endswith("0") else s).replace(".", ",")


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
def _cle(fichier: Path, quoi: str) -> str:
    with _VERROU:
        try:
            v = fichier.read_text(encoding="utf-8").strip()
            if len(v) >= 20:
                return v
        except Exception:
            pass
        v = secrets.token_urlsafe(24)
        if not safe_json.write_text(fichier, v):
            raise OSError(f"{quoi} non écrite ({fichier})")
        try:
            fichier.chmod(0o600)
        except Exception:
            pass
        return v


def cle_page() -> str:
    """La clé du salon : elle ouvre la page des VA, sans compte, SANS
    paiement ni gain. Créée au premier appel."""
    return _cle(CLE_FICHIER, "clé de la page")


def cle_paie() -> str:
    """La clé du PROPRIÉTAIRE : la page, plus les colonnes Paiement et Gain /
    perte, et le droit de modifier un paiement. Jamais dans url_page() ni sur
    Discord. Relecture du 26/09 : la clé du salon ouvrait aussi le paiement,
    et une fois l'envoi Discord allumé, chaque VA aurait pu lire le salaire et
    le gain des autres, et les modifier. Créée au premier appel."""
    return _cle(CLE_PAIE_FICHIER, "clé de paiement")


def acces_cle(k: Any) -> str:
    """« paie » (clé du propriétaire), « page » (clé du salon) ou "" (clé
    fausse, ou illisible). Comparaisons en temps constant ; ne lève pas.
    Deux fichiers identiques par erreur : la clé est celle du salon."""
    import hmac
    s = str(k or "").encode("utf-8")
    if not s:
        return ""
    out = ""
    for nom, f in (("paie", cle_paie), ("page", cle_page)):
        try:
            bonne = f().encode("utf-8")
        except Exception as e:
            print(f"[infloww-liens] {nom} : clé illisible : {e}", flush=True)
            continue
        if hmac.compare_digest(s, bonne):
            out = nom
    return out


def url_page() -> str:
    """Le lien du salon, celui des VA : la clé du salon, jamais celle du
    paiement."""
    return f"{SITE}/infloww/liens?k={cle_page()}"


def url_paie() -> str:
    """Le lien personnel du propriétaire (page + paiement). Affiché à l'admin
    connecté seulement, jamais posté."""
    return f"{SITE}/infloww/liens?k={cle_paie()}"


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
    """Un lien vers la page, tri gardé (omis quand c'est celui par défaut).
    La même adresse que le retour du formulaire de paiement (_requete_page),
    échappée pour un href."""
    return _e(_requete_page(tri, sens, cle, du, au))


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
                     cle: str, du: str = "", au: str = "", source: str = "Infloww",
                     paie: Optional[Mapping[str, Any]] = None) -> str:
    # Paiement (le réglage, modifiable) puis Gain / perte, EN DERNIER : « la
    # dernière case qui me dit si le VA me fait perdre ou gagner de l'argent ».
    # Seulement sur la vue du propriétaire (paie non None : clé de paiement ou
    # admin) ; la vue des VA (clé du salon) n'a ni l'une ni l'autre.
    avec = paie is not None
    cols = (("nom", "Personne", "nom"), ("us", "Clics US", "n"), ("clics", "Clics OF", "n"),
            ("subs", "Subs", "n"), ("cvr", "CVR", "n"), ("par_sub", "$\u00a0/\u00a0sub", "n"))
    if avec:
        cols += (("paie", "Paiement", "paie"), ("gain", "Gain\u00a0/\u00a0perte", "n"))
    P = paie or {}
    taux = (P.get("taux") or {}).get("taux")
    th = []
    for col, titre, cl in cols:
        if col == "paie":
            th.append(f'<th class="{cl}">{titre}</th>')     # pas de tri sur un réglage
            continue
        fl = (" ▾" if sens == "desc" else " ▴") if col == tri else ""
        on = " on" if col == tri else ""
        th.append(f'<th class="{cl}{on}"><a href="{_lien_tri(col, tri, sens, cle, du, au)}">{titre}{fl}</a></th>')
    corps = []
    for x in lignes:
        nom = _e(x.get("nom")) or '<span class="faible">(sans nom)</span>'
        us_cl = "" if x.get("us_etat") == "ok" else " vieux"
        corps.append(f'<tr id="{ancre(x.get("cle"))}"><td class="nom"><b>{nom}</b>{_detail_personne(x, source)}</td>'
                     f'<td class="n{us_cl}">{_nb(x.get("us"))}</td>'
                     f'<td class="n">{_nb(x.get("clics"))}</td>'
                     f'<td class="n fort">{_nb(x.get("subs"))}</td>'
                     f'<td class="n">{_pastille(_pct(x.get("cvr")), niveau(x.get("cvr"), SEUIL_CVR))}</td>'
                     f'<td class="n">{_pastille(_dollars(x.get("par_sub")), niveau(x.get("par_sub"), SEUIL_PAR_SUB))}'
                     f'</td>{_cellule_paie(x, cle, tri, sens, du, au) + _cellule_gain(x, taux) if avec else ""}</tr>')
    if not corps:
        corps.append(f'<tr><td class="faible" colspan="{len(cols)}">Aucune personne.</td></tr>')
    lib = f"Total · {_nb(len(lignes))} personne{'s' if len(lignes) > 1 else ''}"
    pied = (f'<tr class="total"><td class="nom">{_e(lib)}</td><td class="n">{_nb(T.get("us"))}</td>'
            f'<td class="n">{_nb(T.get("clics"))}</td><td class="n">{_nb(T.get("subs"))}</td>'
            f'<td class="n">{_pastille(_pct(T.get("cvr")), niveau(T.get("cvr"), SEUIL_CVR))}</td>'
            f'<td class="n">{_pastille(_dollars(T.get("par_sub")), niveau(T.get("par_sub"), SEUIL_PAR_SUB))}'
            f'</td>{_cellules_total_paie(P) if avec else ""}</tr>')
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


# ─── la page : le paiement ───────────────────────────────────────────────
def _argent(v: Optional[float], signe: bool = False) -> str:
    """« 1 234,50 $ », « −12,00 $ » ; signe=True : « +12,00 $ » aussi."""
    if v is None:
        return "—"
    s = _dec(abs(v)) + "\u00a0$"
    if signe:
        return ("+" if v >= 0 else "−") + s
    return ("−" if v < 0 else "") + s


def _explique_fixe(p: Mapping[str, Any], taux: Optional[float]) -> str:
    """« 75 $ / quinzaine × 6/15 j × 3 lignes », ou sur plusieurs tranches
    « 75 $ / quinzaine du … au …, au prorata des jours, par ligne active de
    chaque quinzaine » (le détail tranche par tranche est dessous)."""
    cfg = p["cfg"]
    df = p.get("detail_f") or []
    base = f"{_montant_court(cfg['montant'])} {'$' if cfg['devise'] == 'USD' else 'EUR'} / {cfg['frequence']}"
    if not df:
        return f"payé à partir du {_jour_long(cfg.get('depuis'))} : rien sur la plage"
    if len(df) == 1:
        f = df[0]
        s = base + ("" if f["complete"] else f" × {f['jours']}/{f['jours_periode']} j")
        if f.get("lignes") is not None:
            s += f" × {_txt_lignes(f['lignes'])}" + {
                "manuel": " (saisie à la main, bornée par GetMySocial)",
                "sans_lien": " (saisie à la main)", "force": " (forcées à la main)"}.get(f.get("source") or "", "")
    else:
        s = (f"{base} du {_jour_long(p.get('debut'))} au {_jour_long(p.get('fin'))}, au prorata des jours, "
             f"par ligne active de chaque {cfg['frequence']}")
    if cfg["devise"] == "EUR" and p.get("fixe_devise") is not None:
        s += f" = {_dec(p.get('fixe_devise'))} EUR × {_dec(taux, 4)}" if taux else ""
    return s


def _txt_lignes(n: Any, adj: str = "") -> str:
    """« 1 ligne », « 3 lignes actives », « 0 ligne active »."""
    s = "s" if int(n or 0) > 1 else ""
    return f"{_nb(n)} ligne{s}" + (f" {adj}{s}" if adj else "")


def _pl(n: Any, *mots: str) -> str:
    """« 1 inconnue », « 3 actives confirmées » : chaque mot au pluriel au-delà de 1."""
    s = "s" if int(n or 0) > 1 else ""
    return " ".join([_nb(n)] + [m + s for m in mots])


def _ligne_f(f: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    """Le compte des lignes d'UNE tranche du fixe : « 3 lignes actives sur 4
    (× 75 $) — sans clic : ( BO7 ) 4 », les lignes forcées ou saisies à la
    main (avec ce que GetMySocial a confirmé), l'absence de lien GMS, ou le
    calcul en cours (et quels liens il attend) ; puis les liens comptés mais
    partis depuis, et ceux pas comptés (à une autre personne sur la tranche)."""
    dev = "$" if cfg.get("devise") == "USD" else "EUR"
    par = f"× {_montant_court(round(float(f.get('base') or 0), 2))}\u00a0{dev}"
    inconnus = list(f.get("inconnus") or [])
    src = f.get("source")
    premier = f" (premier lien créé le {_jour_long(f['premier_lien'])})" if f.get("premier_lien") else ""
    if src == "gms":
        s = (f"{_txt_lignes(f['lignes'], 'active')} sur {_nb(f.get('total'))} ({par})"
             + (", figé à la clôture" if f.get("fige") else ""))
    elif src == "force":
        if f.get("actives") is not None and f.get("total"):
            gms_txt = f"{_txt_lignes(f['actives'], 'active')} sur {_nb(f['total'])}"
        elif not f.get("total") and f.get("pas_encore"):
            gms_txt = "pas encore de lien"
        elif not f.get("total"):
            gms_txt = "aucun lien à cette personne sur cette période"
        else:
            gms_txt = (f"{_pl(f.get('confirmees'), 'active', 'confirmée')}, "
                       f"{_pl(len(inconnus), 'lien')} pas relevé{'s' if len(inconnus) > 1 else ''}")
        s = f"{_txt_lignes(f['lignes'], 'forcée')} à la main ({par}) ; GetMySocial : {gms_txt}"
    elif src == "manuel":
        a, u, sa = int(f.get("confirmees") or 0), len(inconnus), int(f.get("saisie") or 0)
        s = (f"{_pl(a, 'active', 'confirmée')} + {_pl(u, 'inconnue')} ({', '.join(inconnus)} : clics "
             f"GetMySocial pas encore relevés), {_pl(sa, 'saisie')} à la main → "
             f"{_txt_lignes(f['lignes'], 'payée')} ({par})")
    elif src == "sans_lien":
        if f.get("lignes") is not None:
            s = (f"{_txt_lignes(f['lignes'], 'payée')} saisie{'s' if int(f['lignes']) > 1 else ''} à la main "
                 f"({par}) : pas encore de lien GetMySocial{premier}")
        else:
            s = f"pas encore de lien GetMySocial{premier} : « lignes payées » à renseigner"
    else:
        s = (f"lignes actives : calcul en cours ({', '.join(inconnus)} pas encore "
             f"relevé{'s' if len(inconnus) > 1 else ''})")
    if f.get("sans_clic"):
        s += " — sans clic : " + ", ".join(f["sans_clic"])
    if f.get("pas_encore") and src != "sans_lien":
        s += " — pas encore créé : " + ", ".join(f["pas_encore"])
    if f.get("partis"):
        s += " — compté, changé depuis : " + ", ".join(
            f"{d['nom']} (" + (f"aujourd'hui « {d['nom_jour']} », à {d['chez']}" if d.get("chez")
                               else "supprimé de GetMySocial") + ")" for d in f["partis"])
    if f.get("exclus"):
        s += " — pas compté : " + ", ".join(
            f"{d['nom']} (" + (f"à {d['chez']} sur cette période" if d.get("chez")
                               else "pas à cette personne au relevé de cette période") + ")" for d in f["exclus"])
    return s


def _textes_lignes(p: Mapping[str, Any], connues: bool = False) -> List[str]:
    """Les lignes actives de chaque tranche du fixe, en texte (préfixées de
    la période quand il y en a plusieurs) ; `connues` : seulement les
    tranches dont le nombre de lignes est connu (relevé ou saisi)."""
    cfg = p.get("cfg") or {}
    df = p.get("detail_f") or []
    garde = [f for f in df if f.get("lignes") is not None or not connues]
    if len(df) == 1:
        return [_ligne_f(f, cfg) for f in garde]
    return [f"{_libelle_periode(f['du'], f['au'])} : {_ligne_f(f, cfg)}" for f in garde]


def _calc_sub(q: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    """« 200 × 0,40 $ + 50 × 0,50 $ »."""
    dev = "$" if cfg.get("devise") == "USD" else "EUR"
    s = f"{_nb(q.get('bas'))} × {_taux_court(cfg['taux1'])} {dev}"
    if q.get("haut"):
        s += f" + {_nb(q['haut'])} × {_taux_court(cfg['taux2'])} {dev}"
    return s


def _ligne_q_sub(q: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    """« 01/09 → 15/09 : 250 subs → 200 × 0,40 $ + 50 × 0,50 $ = 105,00 $ »."""
    dev = "$" if cfg.get("devise") == "USD" else "EUR"
    s = f"{_libelle_periode(q['du'], q['au'])} : {_nb(q.get('subs'))} subs"
    if q.get("cout") is not None:
        s += f" → {_calc_sub(q, cfg)} = {_dec(q['cout'])} {dev}"
    return s + ("" if q.get("complete") else " (quinzaine incomplète)")


def _explique_sub(p: Mapping[str, Any], taux: Optional[float]) -> str:
    cfg = p["cfg"]
    dq = p.get("detail_q") or []
    if not dq:
        s = "aucune quinzaine sur la plage"
    elif len(dq) == 1:
        q = dq[0]
        s = (f"{_nb(q.get('subs'))} subs" + (f" : {_calc_sub(q, cfg)}" if q.get("cout") is not None else "")
             + ("" if q.get("complete") else ", quinzaine incomplète"))
    else:
        inc = sum(1 for q in dq if not q.get("complete"))
        s = (f"{_nb(len(dq))} quinzaines" + (f", dont {_nb(inc)} incomplète{'s' if inc > 1 else ''}" if inc else "")
             + f", seuil de {_nb(cfg['seuil'])} subs par quinzaine")
    if cfg["devise"] == "EUR" and taux and p.get("sub_devise") is not None:
        s += f" = {_dec(p['sub_devise'])} EUR × {_dec(taux, 4)}"
    return s


def _ligne_q(q: Mapping[str, Any]) -> str:
    """« 16/09 → 26/09 : 123 subs, palier 100–149 subs → +10 $ (quinzaine incomplète) »."""
    s = f"{_libelle_periode(q['du'], q['au'])} : {_nb(q.get('subs'))} subs"
    if q.get("palier") is not None:
        s += (f", palier {q['palier']} → +{_montant_court(q['prime'])}\u00a0$" if q.get("prime")
              else ", sous le premier palier → 0\u00a0$")
    return s + ("" if q.get("complete") else " (quinzaine incomplète)")


def _explique_primes(p: Mapping[str, Any]) -> str:
    dq = p.get("detail_q") or []
    if not dq:
        return "aucune quinzaine sur la plage"
    if len(dq) == 1:
        q = dq[0]
        s = f"{_nb(q.get('subs'))} subs, " + (f"palier {q['palier']}" if q.get("prime")
                                              else f"sous le premier palier ({_nb(PALIERS_PRIMES[-1][0])})")
        return s + ("" if q.get("complete") else ", quinzaine incomplète")
    inc = sum(1 for q in dq if not q.get("complete"))
    return (f"{_nb(len(dq))} quinzaines" + (f", dont {_nb(inc)} incomplète{'s' if inc > 1 else ''}" if inc else "")
            + ", non cumulables")


def lignes_calcul(p: Mapping[str, Any], taux: Optional[float] = None) -> List[str]:
    """Le détail du gain, en texte : « revenu X », « − fixe Y (…) », les
    lignes actives, « − primes Z (…) » ; ou, au sub, « − paie au sub Y (…) »."""
    cfg = p.get("cfg") or {}
    L = [f"revenu {_argent(p.get('revenu'))}"]
    if cfg.get("type") == "au_sub":
        L.append(f"− paie au sub {_argent(p.get('cout_sub'))} ({_explique_sub(p, taux)})")
        return L
    L.append(f"− fixe {_argent(p.get('fixe'))} ({_explique_fixe(p, taux)})")
    if len(p.get("detail_f") or []) == 1:
        L += _textes_lignes(p)
    if cfg.get("type") == "fixe_primes":
        L.append(f"− primes {_argent(p.get('primes'))} ({_explique_primes(p)})")
    return L


def _form_paie(x: Mapping[str, Any], cle: str, tri: str, sens: str, du: str, au: str) -> str:
    """Le réglage d'une personne, SANS JavaScript : un formulaire POST dans un
    <details>. Clé, période et tri voyagent en champs cachés : le retour se
    fait sur la même vue. Seule la vue du propriétaire le porte : la clé est
    alors la sienne (cle_paie), jamais celle du salon. Tous les champs sont
    là (sans script, rien ne s'affiche selon le type) : seuls ceux du type
    choisi sont lus. Une ligne SPAM non réglée n'est PAS mise « au sub »
    d'office ; les prix au sub portent seulement leurs valeurs par défaut."""
    cfg = (x.get("paie") or {}).get("cfg")
    v = dict(PAIE_DEFAUT, **(cfg or {}))
    caches = "".join(f'<input type="hidden" name="{n}" value="{_e(val)}">'
                     for n, val in (("personne", x.get("cle")), ("k", cle), ("du", du), ("au", au),
                                    ("tri", tri), ("sens", sens)) if val)

    def choix(options, courant):
        return "".join(f'<option value="{_e(c)}"{" selected" if c == courant else ""}>{_e(lib)}</option>'
                       for c, lib in options)

    def taux_champ(val: Any) -> str:
        return _taux_court(val).replace(",", ".")
    montant = ("%.2f" % float(v["montant"] or 0)).rstrip("0").rstrip(".")
    try:
        fin = dt.date.fromisoformat(_aujourdhui()) + dt.timedelta(days=366)
    except ValueError:
        fin = dt.date.today() + dt.timedelta(days=366)
    lignes = "" if v.get("lignes") in (None, "") else str(int(v["lignes"]))
    # les lignes FORCÉES : seulement sur une vue par période (les quinzaines,
    # ou mois, qu'elle touche, en entier). « forcer_avant » : la valeur
    # montrée — enregistrer le montant sans toucher à ce champ ne retire
    # rien, même si les tranches de la période n'ont pas toutes la même.
    a_f, b_f = _date_arg(du), _date_arg(au)
    if a_f and b_f and a_f <= b_f:
        tr_f = decouper(a_f, b_f, v["frequence"])
        vals = {(v.get("forces") or {}).get(_k_entiere(t)) for t in tr_f}
        pre = str(next(iter(vals))) if len(vals) == 1 and None not in vals else ""
        quoi = "des quinzaines" if v["frequence"] == "quinzaine" else "des mois"
        forcer = (f'<label>Forcer les lignes {quoi} du {_jour_court(tr_f[0]["p_du"].isoformat())} au '
                  f'{_jour_court(tr_f[-1]["p_au"].isoformat())}, même si GetMySocial a compté (vide : ne plus '
                  f'forcer)<input type="number" name="forcer_lignes" value="{_e(pre)}" min="0" max="{LIGNES_MAX}" '
                  f'step="1" inputmode="numeric"></label><input type="hidden" name="forcer_avant" value="{_e(pre)}">')
    else:
        forcer = ('<div class="det">Forcer les lignes d\'une quinzaine : choisissez-la d\'abord en haut de la '
                  'page.</div>')
    return ('<details class="mod"><summary>modifier</summary>'
            f'<form class="fpaie" method="post" action="/infloww/liens/paie">{caches}'
            f'<label>Type<select name="type">{choix(((t, LIB_TYPES[t]) for t in TYPES_PAIE), v["type"])}'
            '</select></label>'
            f'<label>Devise<select name="devise">{choix((("USD", "$ (USD)"), ("EUR", "€ (EUR), converti en $")), v["devise"])}'
            '</select></label>'
            '<fieldset><legend>Fixe, Fixe + primes</legend>'
            f'<label>Montant par ligne<input type="number" name="montant" value="{_e(montant)}" min="0" '
            f'max="{int(MONTANT_MAX)}" step="0.01" inputmode="decimal"></label>'
            f'<label>Fréquence<select name="frequence">'
            f'{choix((("quinzaine", "par quinzaine"), ("mois", "par mois")), v["frequence"])}'
            '</select></label>'
            '<label>Lignes payées tant que GetMySocial n\'a pas répondu, ou avant le premier lien GMS '
            '(facultatif)<input type="number" '
            f'name="lignes" value="{_e(lignes)}" min="1" max="{LIGNES_MAX}" step="1" inputmode="numeric"></label>'
            f'{forcer}</fieldset>'
            '<fieldset><legend>Au sub (par quinzaine)</legend>'
            f'<label>Prix par sub jusqu\'au seuil<input type="number" name="taux1" value="{_e(taux_champ(v["taux1"]))}" '
            f'min="0" max="{int(TAUX_SUB_MAX)}" step="0.001" inputmode="decimal"></label>'
            f'<label>Seuil (subs par quinzaine)<input type="number" name="seuil" value="{_e(v["seuil"])}" '
            f'min="0" max="{SEUIL_SUB_MAX}" step="1" inputmode="numeric"></label>'
            f'<label>Prix par sub au-delà<input type="number" name="taux2" value="{_e(taux_champ(v["taux2"]))}" '
            f'min="0" max="{int(TAUX_SUB_MAX)}" step="0.001" inputmode="decimal"></label>'
            '</fieldset>'
            f'<label>Payé depuis (facultatif)<input type="date" name="depuis" value="{_e(v["depuis"])}" '
            f'min="{_e(PLANCHER.isoformat())}" max="{_e(fin.isoformat())}"></label>'
            '<button type="submit">Enregistrer</button></form></details>')


def _force_applicable(k: str, frequence: str) -> bool:
    """Une tranche forcée compte-t-elle avec cette fréquence ? (une quinzaine
    forcée ne dit rien d'une paie au mois : elle est montrée, pas comptée)"""
    try:
        du, au = (dt.date.fromisoformat(x) for x in str(k).split("|", 1))
    except ValueError:
        return False
    return (mois_de if frequence == "mois" else quinzaine_de)(du) == (du, au)


def _cellule_paie(x: Mapping[str, Any], cle: str, tri: str, sens: str, du: str, au: str) -> str:
    p = x.get("paie") or {}
    cfg = p.get("cfg")
    det: List[str] = []
    if cfg and cfg.get("type") in TYPES_PAYES and cfg.get("depuis"):
        det.append(f"payé depuis le {_jour_long(cfg['depuis'])}")
    if cfg and cfg.get("type") == "au_sub":
        det.append("par quinzaine, sans fixe")
    if cfg and cfg.get("type") in TYPES_FIXE and cfg.get("lignes"):
        det.append(f"lignes payées tant que GetMySocial manque : {_nb(cfg['lignes'])}")
    if cfg and cfg.get("type") in TYPES_FIXE and cfg.get("forces"):
        fz = sorted(cfg["forces"].items())
        det.append("lignes forcées à la main : " + " ; ".join(
            f"{_libelle_periode(*k.split('|', 1))} : {_nb(n)}"
            + ("" if _force_applicable(k, cfg["frequence"]) else f" (ignorée : paie au {cfg['frequence']})")
            for k, n in fz[:4]) + (f" ; et {_nb(len(fz) - 4)} autre(s)" if len(fz) > 4 else ""))
    cl = "pr ps" if cfg and cfg.get("type") == "au_sub" else "pr"
    return (f'<td class="paie"><span class="{cl}">{_e(p.get("resume") or resume_paie(cfg))}</span>'
            + (f'<div class="det">{"<br>".join(_e(d) for d in det)}</div>' if det else "")
            + f'{_form_paie(x, cle, tri, sens, du, au)}</td>')


def _details_tranches(p: Mapping[str, Any]) -> str:
    """Le détail tranche par tranche (subs et primes ou paie au sub, lignes
    actives), replié, quand la plage en compte plusieurs."""
    cfg = p.get("cfg") or {}
    df, dq = p.get("detail_f") or [], p.get("detail_q") or []
    if len(df) <= 1 and len(dq) <= 1:
        return ""
    par: Dict[Tuple[str, str], List[str]] = {}
    for q in dq:
        par.setdefault((q["du"], q["au"]), []).append(
            _ligne_q_sub(q, cfg) if cfg.get("type") == "au_sub" else _ligne_q(q))
    for f in df:
        k = (f["du"], f["au"])
        if k in par:
            par[k].append(_ligne_f(f, cfg))
        else:
            par[k] = [f"{_libelle_periode(*k)} : {_ligne_f(f, cfg)}"]
    quoi = "par quinzaine" if (cfg.get("type") == "au_sub" or cfg.get("frequence") != "mois") else "par période"
    return (f'<details class="qz"><summary>{quoi}</summary><div class="det">'
            + "<br>".join(_e(" ; ".join(v)) for _k, v in sorted(par.items())) + "</div></details>")


def _cellule_gain(x: Mapping[str, Any], taux: Optional[float]) -> str:
    """Le DERNIER chiffre de la ligne : vert si le VA rapporte au moins ce
    qu'il coûte, rouge sinon ; « — » s'il n'est pas réglé ou si un élément
    manque (dit dessous, avec les lignes actives déjà connues). Le détail du
    calcul sous le montant, et au survol."""
    p = x.get("paie") or {}
    cfg = p.get("cfg")
    if not cfg or cfg.get("type") not in TYPES_PAYES:
        return '<td class="n gain">—</td>'
    g = p.get("gain")
    q = _details_tranches(p)
    if g is None:
        connu = _textes_lignes(p, connues=True)
        extra = f'<div class="det">{"<br>".join(_e(l) for l in connu)}</div>' if connu and not q else ""
        return (f'<td class="n gain">—<div class="det manque">{_e(p.get("raison") or "incalculable")}</div>'
                f'{extra}{q}</td>')
    L = lignes_calcul(p, taux)
    return (f'<td class="n gain" title="{_e(" ".join(L))}"><span class="nv {"gp" if g >= 0 else "gn"}">'
            f'{_argent(g, signe=True)}</span><div class="det calc">{"<br>".join(_e(l) for l in L)}</div>{q}</td>')


def _cellules_total_paie(P: Mapping[str, Any]) -> str:
    T = P.get("totaux") or {}
    n = int(P.get("configures") or 0)
    if not n:
        return '<td class="paie">—</td><td class="n gain">—</td>'
    paie = f'<td class="paie">{_nb(n)} réglé{"s" if n > 1 else ""}</td>'
    if T.get("gain") is None:
        return paie + '<td class="n gain">—<div class="det manque">aucun gain calculable</div></td>'
    det = [f"revenu {_argent(T.get('revenu'))}", f"− coûts {_argent(T.get('cout'))}"]
    if int(T.get("calcules") or 0) < n:
        det.append(f"partiel : {_nb(T.get('calcules'))} personne{'s' if T.get('calcules', 0) > 1 else ''} "
                   f"sur {_nb(n)}")
    g = T["gain"]
    return (paie + f'<td class="n gain" title="{_e(" ".join(det))}"><span class="nv {"gp" if g >= 0 else "gn"}">'
            f'{_argent(g, signe=True)}</span><div class="det calc">{"<br>".join(_e(l) for l in det)}</div></td>')


def _avert_paie(t: Mapping[str, Any], lignes: List[Mapping[str, Any]]) -> List[str]:
    """Ce que la page dit du paiement, en tête : rien n'est écarté sans trace."""
    P = t.get("paie") or {}
    h: List[str] = []
    if P.get("erreur"):
        h.append(f'<div class="avert"><b>Paiement : calcul impossible</b> ({_e(P["erreur"])}) : '
                 "Gain / perte « — ».</div>")
    for m in P.get("mauvais") or []:
        h.append(f'<div class="avert">Réglage de paiement illisible, ignoré : {_e(m)}.</div>')
    if P.get("orphelins"):
        h.append('<div class="avert">Réglage(s) de paiement de personne(s) absente(s) de GetMySocial '
                 f'« {_e(NOM_EQUIPE)} » (lien renommé ?) : {_e(", ".join(P["orphelins"]))} — non compté(s).</div>')
    tx = P.get("taux") or {}
    if P.get("taux") is not None:
        if tx.get("taux") is None:
            h.append('<div class="avert"><b>Aucun taux EUR → USD connu</b> (BCE : '
                     f'{_e(tx.get("panne") or "?")}) : le coût des VA payés en euros est « — ».</div>')
        elif tx.get("panne"):
            h.append(f'<div class="avert">Taux EUR → USD : la BCE n\'a pas répondu ({_e(tx["panne"])}) : '
                     f'dernier taux connu, publié le {_e(_jour_long(tx.get("date")))}.</div>')
    if P.get("en_attente"):
        n, r = int(P["en_attente"]), int(P.get("a_relire") or 0)
        h.append(f'<div class="avert">Subs par quinzaine (primes, paie au sub) : {_nb(n)} '
                 f'quinzaine{"s" if n > 1 else ""} pas encore lue{"s" if n > 1 else ""} dans MyPuls'
                 + (f' (dont {_nb(r)} à relire : un lien y manquait ou était sans nombre de subs)' if r else "")
                 + '. Lecture en arrière-plan, '
                 f'{_nb(QUINZ_APPELS_MAX)} au plus par affichage (le débit MyPuls est limité) : rechargez '
                 "dans une minute. Gain / perte « — » en attendant.</div>")
    if P.get("pause"):
        h.append(f'<div class="avert">Subs par quinzaine : MyPuls a refusé une lecture ({_e(P["pause"])}) : pas de '
                 f'nouvelle lecture de quinzaine pendant {_nb(MYPULS_ECHEC_S)} s.</div>')
    elif P.get("erreurs"):
        k, r = sorted(P["erreurs"].items())[0]
        h.append(f'<div class="avert">Subs par quinzaine : MyPuls n\'a pas répondu pour {_nb(len(P["erreurs"]))} '
                 f'quinzaine(s), dont le {_e(_libelle_periode(*k))} ({_e(r)}) : Gain / perte « — » pour les '
                 "personnes concernées.</div>")
    L = P.get("lignes") or {}
    if L.get("inconnus"):
        info = L.get("info") or {}
        n = int(L["inconnus"])
        if info.get("budget"):
            pourquoi = (f"les {_nb(info['budget'])} appels GetMySocial du jour réservés à ce relevé sont faits "
                        "(le quota est partagé avec le tableau de bord) : la suite demain")
        elif info.get("pause"):
            pourquoi = (f"GetMySocial n'accepte plus d'appel ({_e(info['pause'])}) : le relevé reprendra à un "
                        "prochain affichage")
        elif info.get("en_cours"):
            pourquoi = "relevé en arrière-plan : rechargez dans une minute"
        else:
            pourquoi = ("dernier relevé raté" + (f" ({_e(L['rates'][0])})" if L.get("rates") else "")
                        + " : retenté dans 10 min, trois fois par jour au plus")
        s = "s" if n > 1 else ""
        h.append(f'<div class="avert">Lignes actives : {_nb(n)} relevé{s} de clics GetMySocial (un par lien '
                 f'GMS et par tranche du fixe) pas encore connu{s} — {pourquoi}. '
                 "Gain / perte « — » en attendant pour les personnes concernées, sauf « lignes payées » "
                 "saisies à la main, bornées par les lignes connues (jamais un nombre de lignes inventé).</div>")
    return h


def _note_paie(t: Mapping[str, Any], du: str) -> List[str]:
    P = t.get("paie") or {}
    primes = ", ".join(f"{_nb(b)}{'–' + _nb(PALIERS_PRIMES[i - 1][0] - 1) if i else ' et plus'} +{_montant_court(v)} $"
                       for i, (b, v) in reversed(list(enumerate(PALIERS_PRIMES))))
    note = ["<b>Paiement</b> : réglé par personne (« modifier ») ; <b>Gain / perte</b> = revenu net de la "
            "personne sur la plage − coût (fixe × lignes actives + primes, ou paie au sub), en dollars (vert "
            "si ≥ 0, rouge sinon) ; « — » sans réglage ou quand un élément manque",
            ("<b>Plage</b> : la période affichée, à partir de « payé depuis » s'il tombe dedans ; revenu = "
             "gains nets MyPuls de la période" if du else
             "<b>Plage</b> : de « payé depuis » (sinon de la création du plus ancien lien Infloww de la "
             "personne) à aujourd'hui ; revenu = gains nets Infloww cumulés"),
            "<b>Fixe</b> au prorata des jours : quinzaines du 1er au 15 et du 16 à la fin du mois (paie le 16 "
            "et le 1er), ou mois civil",
            "<b>Lignes</b> : une paie de base par ligne ACTIVE — un lien GetMySocial de la personne (un "
            "iPhone) qui a fait au moins 1 clic, tous pays, sur la quinzaine ou le mois (partie incluse dans "
            "la plage) : fixe × lignes actives ; clics relevés lien par lien en arrière-plan et gardés "
            "(tranche close définitive, tranche en cours relue une fois par jour, "
            f"{_nb(LIGNES_APPELS_JOUR)} appels GetMySocial par jour au plus) ; un 0 n'est compté qu'une fois "
            "relu dans la réponse brute. Chaque relevé note à qui était le lien, et une tranche close "
            "entièrement relevée est FIGÉE : un lien renommé ou supprimé ensuite ne change plus ses lignes "
            "(il est dit sous la ligne). Un lien créé après la fin d'une tranche n'y compte pas (aucun appel) ; "
            "avant le premier lien GetMySocial de la personne : « pas encore de lien ». Tant qu'un compte "
            "manque, les « lignes payées » saisies à la main, jamais moins que les lignes déjà confirmées "
            "actives ni plus que la personne n'a de liens (sans lien GetMySocial : telles quelles), sinon "
            "« — ». « Forcer les lignes » (vue par période) impose le nombre d'une quinzaine ou d'un mois, "
            "même compté par GetMySocial : pour un passé faussé, dit « forcées à la main »",
            f"<b>Primes</b> par quinzaine, une fois par personne (pas par ligne), sur les subs de la personne "
            f"lus dans MyPuls, non cumulables (seul le palier atteint compte) : {_e(primes)} ; une quinzaine "
            "coupée par la plage est comptée sur ses seuls jours (« quinzaine incomplète »)",
            "<b>Au sub</b> (sans fixe) : un prix par sub jusqu'au seuil, un autre au-delà, par quinzaine sur "
            "les subs de la personne lus dans MyPuls, au marginal (0,40 $ jusqu'à 200 puis 0,50 $ : 250 subs = "
            "200 × 0,40 + 50 × 0,50 = 105 $) ; une quinzaine coupée par la plage compte les subs de ses seuls "
            "jours, avec le seuil entier (« quinzaine incomplète »)",
            "Top Performer, Bonus Agence, Bonus Elite et malus : décidés à la main, non comptés"]
    tx = P.get("taux") or {}
    if tx.get("taux") is not None:
        note.append(f"euros convertis au taux BCE du {_e(_jour_long(tx.get('date')))} : 1 EUR = "
                    f"{_e(_dec(tx['taux'], 4))} $ (le même pour toute la plage)")
    elif P.get("taux") is not None:
        note.append("aucun taux EUR → USD connu : coût des VA payés en euros « — »")
    else:
        note.append("un montant en euros est converti au taux BCE du jour")
    return note


def page_html(t: Mapping[str, Any], tri: str = "nom", sens: str = "asc", cle: str = "",
              lien_perso: str = "") -> str:
    """La page entière. Aucun JavaScript : le tri et la période passent par
    l'adresse, et une apostrophe dans un nom de lien ne peut rien casser.
    Tout est échappé. Paiement et Gain / perte seulement si `t` les porte
    (avec_paie, que page() n'appelle que pour le propriétaire) ; `lien_perso`
    : son lien personnel, montré à l'admin connecté."""
    paie = "paie" in t
    tri, sens = _tri_valide(tri, sens)
    if tri == "gain" and not paie:
        tri, sens = "nom", "asc"         # pas de colonne Gain sur la vue des VA
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
        if paie:
            h += _avert_paie(t, lignes)
        h.append(_table_personnes(lignes, T, tri, sens, cle, du, au, source,
                                  (t.get("paie") or {}) if paie else None))
        h.append('<p class="legende">Couleurs : <span class="nv v1">vert</span> dès '
                 f'{_dec(SEUIL_CVR, 0)}\u00a0% de CVR et dès {_dollars(SEUIL_PAR_SUB)}\u00a0par sub '
                 '(plus foncé = mieux), <span class="nv o1">orange</span> en dessous, '
                 '<span class="nv r">rouge</span> sous la moitié.'
                 + (' Gain / perte : <span class="nv gp">vert</span> si le VA rapporte au moins ce '
                    'qu\'il coûte, <span class="nv gn">rouge</span> sinon.' if paie else "") + '</p>')
        if hors:
            h.append(f'<details><summary>Hors GetMySocial, non comptés ({_nb(len(hors))}) — '
                     f'liens de suivi de Jessye qu\'aucun lien de « {_e(NOM_EQUIPE)} » ne vise'
                     f'</summary>{_table_hors(hors, source)}</details>')
    note = _note(t, du, au, auj)
    if paie and not t.get("erreur"):
        note += _note_paie(t, du)
    sous = (f"<b>{_e(_titre_periode(du, au, auj))}</b> · @{_e(t.get('creatrice') or CREATRICE)} · "
            f"GetMySocial « {_e(NOM_EQUIPE)} »")
    if not t.get("erreur"):
        sous += f" · {_nb(len(lignes))} personnes"
    perso = ""
    if paie and lien_perso:
        # le propriétaire connecté : son lien avec le paiement, à garder pour
        # lui (celui du salon, lui, ne montre ni paiement ni gain)
        perso = (f'<p class="perso">Votre lien personnel, paiement et gain compris — ne le partagez pas '
                 f'(le lien du salon ne les montre pas) : <a href="{_e(lien_perso)}">{_e(lien_perso)}</a></p>')
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
.nv.gp{{background:#16a34a;color:#fff}} .nv.gn{{background:#dc2626;color:#fff}}
td.paie{{min-width:118px}} td.paie .pr{{white-space:nowrap}} td.paie .pr.ps{{white-space:normal}}
td details{{margin:4px 0 0}} td summary{{font-size:11px;padding:2px 0}}
td details.mod summary{{color:var(--acc)}}
.fpaie{{display:grid;gap:6px;margin-top:6px;min-width:176px;max-width:220px}}
.fpaie label{{display:grid;gap:2px;font-size:11px;color:var(--faible)}}
.fpaie fieldset{{display:grid;gap:6px;margin:0;padding:6px 7px 7px;border:1px solid var(--bord);border-radius:8px;min-width:0}}
.fpaie legend{{font-size:11px;color:var(--faible);padding:0 3px}}
.fpaie input,.fpaie select{{background:var(--fond);color:var(--texte);border:1px solid var(--bord);border-radius:6px;padding:5px 6px;font:inherit;font-size:13px;min-width:0;color-scheme:dark}}
.fpaie button{{background:var(--acc);color:#1c0a02;border:0;border-radius:6px;padding:7px 10px;font:inherit;font-weight:700;cursor:pointer}}
/* le détail du gain se replie : sur une ligne, il élargissait la colonne
   au point de pousser le tableau hors de sa boîte même sur un ordinateur */
td.gain .det{{white-space:normal;min-width:150px;max-width:220px;margin-left:auto}}
td.gain details .det{{text-align:left}}
tr:target td{{background:rgba(249,115,65,.12)}}
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
.perso{{color:var(--faible);font-size:12px;margin:-8px 0 14px;overflow-wrap:anywhere}} .perso a{{color:var(--acc)}}
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
{perso}{"".join(h)}
<p class="note">{" · ".join(note)}.</p>
</body></html>'''


def page(args: Mapping[str, Any], cle: str = "", paie: bool = False, lien_perso: bool = False) -> str:
    """La page à partir des paramètres de l'adresse. Ne lève jamais : une
    panne s'affiche SUR la page. `paie` : la vue du propriétaire (clé de
    paiement ou admin, décidé par la route) ; sans lui, la page des VA, sans
    paiement ni gain. `lien_perso` : montrer son lien personnel (admin
    connecté, sans clé)."""
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
    perso = ""
    if paie:
        try:
            # le paiement et le gain : la page du propriétaire seulement
            # (Discord passe par tableau(), les VA par la clé du salon)
            t = avec_paie(t)
        except Exception as e:  # le tableau reste ; la panne est dite en tête
            t = dict(t, paie={"erreur": f"{type(e).__name__} : {e}"[:300]})
        if lien_perso:
            try:
                perso = url_paie()
            except Exception as e:
                print(f"[infloww-liens] clé de paiement illisible : {e}", flush=True)
    try:
        return page_html(t, tri, sens, cle, lien_perso=perso)
    except Exception as e:
        # la clé suit jusque dans la page de panne : le formulaire la porte
        return page_html(_vide(f"la page n'a pas pu être construite : {type(e).__name__} : {e}", per),
                         cle=cle)
