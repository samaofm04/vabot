# -*- coding: utf-8 -*-
"""Les sessions vocales des VA : le calendrier, et qui y etait.

CE QUE CE MODULE FAIT, ET CE QU'IL NE FAIT PAS

Il ne parle pas a Discord. Il tient le CALENDRIER des sessions (a quelle heure,
dans quel fuseau, pendant combien de temps) et le REGISTRE des presences (qui
etait la, combien de temps). Le cog Discord se contente de lui dire, chaque
minute, « voici les gens actuellement dans le salon » ; le site se contente de
lui demander des resumes. Tout le raisonnement est ici, et il se teste sans
bot, sans reseau et sans serveur.

POURQUOI ON COMPTE PAR SONDAGE, PAS PAR EVENEMENTS

Discord sait dire « untel vient d'entrer » et « untel vient de sortir ». S'y
fier seul a deux defauts qu'on paie toujours le meme jour : si le bot
redemarre au milieu d'une session, tous ceux qui etaient deja connectes
n'existent plus pour lui ; et si un evenement se perd, quelqu'un reste
« present » jusqu'a la fin des temps.

On releve donc la liste des presents CHAQUE MINUTE et on ajoute une minute a
chacun. Le compteur mesure alors du temps reellement passe, pas un clic sur
« rejoindre » -- ce qui est exactement la question posee : qui etait la.

LE FUSEAU N'EST PAS UN DETAIL

Les salons s'appellent « BJ 12 h 00 » : douze heures au BENIN, qui est a
UTC+1 toute l'annee, sans heure d'ete. Les VA de Madagascar, eux, sont a
UTC+3 : la meme session tombe chez eux a quatorze heures. Le patron, lui, est
a Paris, qui change d'heure deux fois par an. Trois horloges pour un seul
rendez-vous : l'heure de reference est donc ECRITE dans la configuration, et
tout le reste en decoule.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

import safe_json

FICHIER_CFG = Path("data") / "sessions_cfg.json"
FICHIER_PRESENCE = Path("data") / "sessions_presence.json"
FICHIER_DIRECT = Path("data") / "sessions_direct.json"

#: Le fuseau de reference des horaires affiches dans les noms de salons.
#: Le Benin ne change pas d'heure : une session a midi y est a midi toute
#: l'annee, ce qui n'est vrai ni a Paris ni pour un serveur en UTC.
FUSEAU_DEFAUT = "Africa/Porto-Novo"

#: Les fuseaux des pays ou vivent les VA, pour afficher a chacun SON heure.
#: Les memes sigles que le module de paiement (BJ Moov/MTN, MG Airtel/Orange).
FUSEAUX_PAYS = {
    "BJ": "Africa/Porto-Novo",      # Benin, UTC+1 toute l'annee
    "MG": "Indian/Antananarivo",    # Madagascar, UTC+3 toute l'annee
    "FR": "Europe/Paris",
}

#: Le calendrier de depart, repris des salons existants (« BJ 12 h 00 au
#: Benin », 17 h, 23 h, 2 h). Il se change dans la page Sessions, pas ici.
#: LES FENETRES SONT OUVERTES AU MAXIMUM, choix du proprietaire le
#: 11/09/2026 : chaque session court jusqu'au debut de la suivante, pour
#: qu'un VA qui passe a n'importe quelle heure soit compte quelque part.
#: Deux bornes posees a la main : celle de midi ouvre a DIX heures, celle
#: de deux heures ferme a CINQ. Il reste donc une seule zone morte, de 5 h a
#: 10 h -- et c'est voulu : sans elle, la session de deux heures du matin
#: avalerait toute la matinee.
SESSIONS_DEFAUT = [
    {"id": "s1", "nom": "Session 1", "heure": 10, "minute": 0,
     "fin_heure": 17, "fin_minute": 0},
    {"id": "s2", "nom": "Session 2", "heure": 17, "minute": 0,
     "fin_heure": 23, "fin_minute": 0},
    {"id": "s3", "nom": "Session 3", "heure": 23, "minute": 0,
     "fin_heure": 2, "fin_minute": 0},
    {"id": "s4", "nom": "Session 4", "heure": 2, "minute": 0,
     "fin_heure": 5, "fin_minute": 0},
]

#: Combien de temps une session dure, et a partir de quand on compte quelqu'un
#: comme arrive. Arriver cinq minutes avant, c'est etre a l'heure ; passer
#: trente secondes dans le salon n'est pas y avoir assiste.
DUREE_MIN_DEFAUT = 120
AVANT_MIN_DEFAUT = 15
PRESENCE_MIN_SECONDES_DEFAUT = 300

_CACHE: dict = {"sig": None, "data": None}


# ==============================================================================
# Configuration
# ==============================================================================

def config() -> dict:
    """La configuration, complete, avec ses valeurs par defaut.

    Relue quand le fichier bouge : le site ecrit, le bot lit, ce sont deux
    processus.
    """
    try:
        sig = FICHIER_CFG.stat().st_mtime_ns
    except OSError:
        sig = None
    if _CACHE["sig"] != sig or _CACHE["data"] is None:
        brut = safe_json.load(FICHIER_CFG, default={}) or {}
        if not isinstance(brut, dict):
            brut = {}
        _CACHE.update(sig=sig, data=_completer(brut))
    return dict(_CACHE["data"])


def _completer(brut: dict) -> dict:
    """Un reglage absent vaut son defaut, jamais une exception.

    Le premier lancement se fait donc SANS fichier : la page s'affiche avec le
    calendrier de depart, et le proprietaire corrige ce qui ne va pas. Un
    ecran qui exige d'etre configure avant de montrer quoi que ce soit ne se
    configure jamais.
    """
    sessions = brut.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        sessions = [dict(s) for s in SESSIONS_DEFAUT]
    propres = []
    for i, s in enumerate(sessions):
        if not isinstance(s, dict):
            continue
        try:
            h = int(s.get("heure"))
            m = int(s.get("minute") or 0)
        except (TypeError, ValueError):
            continue
        if not (0 <= h <= 23 and 0 <= m <= 59):
            continue
        # UNE SESSION SE DIT « DE 12 H A 15 H ». C'est ainsi que le
        # proprietaire la pense et l'annonce a ses VA ; « 12 h pendant 180
        # minutes » est une facon de parler d'horloger. On accepte donc une
        # heure de FIN, et on en deduit la duree -- qui reste ce que le reste
        # du code manipule, parce qu'une duree ne se trompe jamais de jour.
        duree = _duree_depuis_fin(h, m, s.get("fin_heure"), s.get("fin_minute"))
        if duree is None:
            duree = _entier(s.get("duree_min"), DUREE_MIN_DEFAUT, 5, 720)
        _fh, _fm = _fin_depuis_duree(h, m, duree)
        propres.append({
            "id": str(s.get("id") or "s%d" % (i + 1)),
            "nom": str(s.get("nom") or "Session %d" % (i + 1)),
            "heure": h,
            "minute": m,
            "duree_min": duree,
            # La fin est RECALCULEE et rendue avec le reste : l'ecran affiche
            # « de ... a ... » sans avoir a refaire le calcul de son cote, et
            # sans risque que les deux ne disent pas la meme chose.
            "fin_heure": _fh,
            "fin_minute": _fm,
            "avant_min": _entier(s.get("avant_min"), AVANT_MIN_DEFAUT, 0, 240),
        })
    propres.sort(key=lambda s: (s["heure"], s["minute"]))
    return {
        "fuseau": str(brut.get("fuseau") or FUSEAU_DEFAUT),
        "sessions": propres,
        # Les salons suivis. Vide = on suit tout salon vocal dont le nom ou la
        # categorie correspond a `motif_salon` / `categorie`.
        "salons": [int(x) for x in (brut.get("salons") or []) if str(x).strip().isdigit()],
        "categorie": str(brut.get("categorie") or "session"),
        # LE NOM SUFFIT, LA CATEGORIE AUSSI. Le salon est reconnu s'il porte
        # « session » dans SON nom OU dans celui de sa categorie. Exiger les
        # deux ferait dependre le suivi d'un rangement Discord qui bouge : le
        # jour ou le salon est deplace hors de la categorie, plus personne
        # n'est compte, et rien ne le dit.
        "motif_salon": str(brut.get("motif_salon") or "session"),
        # OU VONT LES DEUX MESSAGES. Deux salons, deux roles, et deux motifs
        # qui ne peuvent pas se confondre : le direct va dans un salon qui
        # porte « session » SANS « bilan », le bilan dans celui qui porte
        # « bilan ». Un seul motif pour les deux aurait poste le direct dans
        # le bilan des que le proprietaire a cree « session-bilan ».
        "salon_direct": str(brut.get("salon_direct") or "session"),
        "salon_bilan": str(brut.get("salon_bilan") or "bilan"),
        "direct_actif": bool(brut.get("direct_actif", True)),
        # Toutes les combien de minutes le message en direct est reecrit.
        # Discord limite les editions ; quatre minutes est le rythme demande,
        # et il reste tres loin des plafonds.
        "maj_minutes": _entier(brut.get("maj_minutes"), 4, 1, 60),
        "presence_min_secondes": _entier(brut.get("presence_min_secondes"),
                                         PRESENCE_MIN_SECONDES_DEFAUT, 0, 7200),
        # LE RESUME AUTOMATIQUE EST ETEINT TANT QU'ON NE L'ALLUME PAS.
        # Poster chaque matin dans un salon, c'est ecrire chez le
        # proprietaire, devant ses VA, une liste de qui n'etait pas la. Ca ne
        # se met pas en route tout seul parce qu'un reglage avait « True » par
        # defaut. Le bouton « Poster le resume sur Discord » permet de l'
        # essayer a la main autant qu'on veut avant de l'automatiser.
        # LE BILAN PART TOUT SEUL, depuis qu'il a SON salon. Ce qui le
        # retenait n'etait pas le principe mais la destination : poster la
        # liste des absents dans le salon ou tout le monde parle n'est pas la
        # meme chose que la poser dans un salon fait pour ca.
        "resume_actif": bool(brut.get("resume_actif", True)),
        # Heure du resume, dans le fuseau de reference.
        "resume_heure": _entier(brut.get("resume_heure"), 8, 0, 23),
    }


def _duree_depuis_fin(h, m, fin_h, fin_m) -> Optional[int]:
    """Minutes entre le debut et la fin. None si la fin n'est pas donnee.

    UNE SESSION QUI FINIT « AVANT » SON DEBUT PASSE MINUIT : 23 h -> 1 h fait
    deux heures, pas moins vingt-deux. C'est le cas normal ici, la moitie des
    sessions se tiennent la nuit.
    """
    if fin_h is None or str(fin_h).strip() == "":
        return None
    try:
        fh = int(fin_h)
        fm = int(fin_m or 0)
    except (TypeError, ValueError):
        return None
    if not (0 <= fh <= 23 and 0 <= fm <= 59):
        return None
    d = (fh * 60 + fm) - (int(h) * 60 + int(m))
    if d <= 0:
        d += 24 * 60
    return max(5, min(720, d))


def _fin_depuis_duree(h, m, duree) -> tuple:
    """L'heure de fin, pour l'afficher sans la recalculer ailleurs."""
    t = (int(h) * 60 + int(m) + int(duree)) % (24 * 60)
    return t // 60, t % 60


def _entier(v, defaut: int, mini: int, maxi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return defaut
    return max(mini, min(maxi, n))


def ecrire_config(nouvelle: dict) -> dict:
    """Enregistre la configuration, completee et bornee. Rend ce qui a ete ecrit."""
    propre = _completer(nouvelle if isinstance(nouvelle, dict) else {})
    FICHIER_CFG.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER_CFG, propre)
    _CACHE.update(sig=None, data=None)
    return propre


def _tz(nom: str = ""):
    """Le fuseau demande, ou celui de reference, ou UTC en dernier recours.

    Un fuseau manquant sur une machine mal installee ne doit pas faire tomber
    le suivi : mieux vaut des heures decalees qu'un ecran vide.
    """
    from zoneinfo import ZoneInfo
    for candidat in (nom, config().get("fuseau"), FUSEAU_DEFAUT):
        if not candidat:
            continue
        try:
            return ZoneInfo(str(candidat))
        except Exception:
            continue
    return _dt.timezone.utc


# ==============================================================================
# Le calendrier
# ==============================================================================

def jour_de(ts: float) -> str:
    """La date, dans le fuseau de reference. « 2026-09-11 »."""
    return _dt.datetime.fromtimestamp(float(ts), _tz()).date().isoformat()


def fenetre(session: dict, jour: str) -> tuple:
    """(debut, fin) en horodatages, pour cette session CE jour-la.

    Le debut inclut la marge d'avance : quelqu'un qui arrive dix minutes avant
    est present, il n'est pas en avance sur rien.
    """
    d = _dt.date.fromisoformat(jour)
    depart = _dt.datetime(d.year, d.month, d.day,
                          int(session["heure"]), int(session["minute"]),
                          tzinfo=_tz())
    debut = depart - _dt.timedelta(minutes=int(session.get("avant_min", AVANT_MIN_DEFAUT)))
    fin = depart + _dt.timedelta(minutes=int(session.get("duree_min", DUREE_MIN_DEFAUT)))
    return debut.timestamp(), fin.timestamp()


def session_a(ts: float) -> Optional[dict]:
    """La session qui contient cet instant, ou None.

    QUAND DEUX FENETRES SE CHEVAUCHENT, LA PLUS PROCHE GAGNE. Avec des
    sessions a 23 h et a 2 h et deux heures de duree, la nuit appartient aux
    deux : attribuer au hasard ferait apparaitre des gens a une session ou ils
    n'etaient pas. On rattache a celle dont l'heure de depart est la plus
    proche -- ce que ferait n'importe qui en regardant l'horloge.
    """
    cfg = config()
    ts = float(ts)
    jour_courant = jour_de(ts)
    veille = (_dt.date.fromisoformat(jour_courant) - _dt.timedelta(days=1)).isoformat()
    lendemain = (_dt.date.fromisoformat(jour_courant) + _dt.timedelta(days=1)).isoformat()
    meilleure, ecart_min = None, None
    for j in (veille, jour_courant, lendemain):
        for s in cfg["sessions"]:
            debut, fin = fenetre(s, j)
            if not (debut <= ts < fin):
                continue
            depart = debut + int(s.get("avant_min", AVANT_MIN_DEFAUT)) * 60
            ecart = abs(ts - depart)
            if ecart_min is None or ecart < ecart_min:
                ecart_min, meilleure = ecart, dict(s, jour=j, debut=debut, fin=fin)
    return meilleure


def en_cours(ts: Optional[float] = None) -> Optional[dict]:
    """La session en cours maintenant, ou None."""
    import time as _t
    return session_a(_t.time() if ts is None else ts)


def prochaine(ts: Optional[float] = None) -> Optional[dict]:
    """La prochaine session a venir, avec son horodatage de depart."""
    import time as _t
    ts = _t.time() if ts is None else float(ts)
    cfg = config()
    jour_courant = jour_de(ts)
    candidats = []
    for j in (jour_courant,
              (_dt.date.fromisoformat(jour_courant) + _dt.timedelta(days=1)).isoformat()):
        for s in cfg["sessions"]:
            debut, _fin = fenetre(s, j)
            depart = debut + int(s.get("avant_min", AVANT_MIN_DEFAUT)) * 60
            if depart > ts:
                candidats.append(dict(s, jour=j, depart=depart))
    if not candidats:
        return None
    return min(candidats, key=lambda s: s["depart"])


def sessions_du_jour(jour: str) -> list:
    """Les sessions de ce jour-la, avec leurs fenetres, dans l'ordre."""
    out = []
    for s in config()["sessions"]:
        debut, fin = fenetre(s, jour)
        out.append(dict(s, jour=jour, debut=debut, fin=fin))
    return out


def heures_locales(session: dict) -> dict:
    """L'heure de cette session dans chaque pays ou vivent des VA.

    « BJ 12 h 00 » ne veut rien dire pour un VA malgache : chez lui c'est
    quatorze heures. Afficher les deux evite la moitie des retards.
    """
    jour = session.get("jour") or jour_de(__import__("time").time())
    d = _dt.date.fromisoformat(jour)
    depart = _dt.datetime(d.year, d.month, d.day,
                          int(session["heure"]), int(session["minute"]),
                          tzinfo=_tz())
    out = {}
    for code, zone in FUSEAUX_PAYS.items():
        try:
            out[code] = depart.astimezone(_tz(zone)).strftime("%H:%M")
        except Exception:
            continue
    return out


# ==============================================================================
# Le registre des presences
# ==============================================================================

def _charger() -> dict:
    d = safe_json.load(FICHIER_PRESENCE, default={}) or {}
    return d if isinstance(d, dict) else {}


def direct_charger() -> dict:
    """Les messages « en direct » deja postes : {« jour:session »: fiche}.

    Persiste sur disque et pas en memoire : le bot redemarre, et un message
    qu'on ne retrouve plus est un message qu'on reposte. Le proprietaire
    verrait alors deux comptes rendus de la meme session, dont un fige a
    mi-parcours.
    """
    d = safe_json.load(FICHIER_DIRECT, default={}) or {}
    return d if isinstance(d, dict) else {}


def direct_poser(cle: str, fiche: dict) -> None:
    d = direct_charger()
    d[str(cle)] = dict(fiche)
    FICHIER_DIRECT.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER_DIRECT, d)


def direct_cle(session: dict) -> str:
    return "%s:%s" % (session.get("jour"), session.get("id"))


def direct_a_figer(ts) -> list:
    """Les sessions terminees dont le message bouge encore.

    « Quand c'est fini, ca ne modifie plus » : on repasse une DERNIERE fois
    pour que le message porte le compte definitif, puis on le marque fige et
    on n'y touche plus jamais. Sans ce dernier passage, le message resterait
    sur le releve d'il y a trois minutes -- c'est-a-dire faux, et pour
    toujours.
    """
    out = []
    for cle, fiche in direct_charger().items():
        if not isinstance(fiche, dict) or fiche.get("fige"):
            continue
        try:
            if float(fiche.get("fin") or 0) <= float(ts):
                out.append((cle, fiche))
        except (TypeError, ValueError):
            continue
    return out


def direct_purger(jours_gardes: int = 30) -> int:
    """Oublie les vieux messages figes : leur id ne sert plus a rien."""
    import time as _t
    limite = (_dt.datetime.fromtimestamp(_t.time(), _tz()).date()
              - _dt.timedelta(days=max(1, int(jours_gardes)))).isoformat()
    d = direct_charger()
    vieux = [k for k in d if str(k).split(":")[0] < limite]
    if not vieux:
        return 0
    for k in vieux:
        d.pop(k, None)
    safe_json.write(FICHIER_DIRECT, d)
    return len(vieux)


def pointer(membres, secondes: int = 60, ts: Optional[float] = None) -> Optional[dict]:
    """Ajoute `secondes` de presence a chacun. Rend la session touchee, ou None.

    `membres` est une liste de {id, nom} -- le cog Discord ne passe QUE ce
    qu'il a vu, jamais une liste de qui devrait etre la. Le registre note ce
    qui s'est passe ; c'est le resume qui confronte a la liste attendue.

    Hors session, on n'ecrit rien : quelqu'un qui traine dans le salon a
    quinze heures n'a assiste a rien.
    """
    import time as _t
    ts = _t.time() if ts is None else float(ts)
    s = session_a(ts)
    if s is None:
        return None
    jour, sid = s["jour"], s["id"]
    data = _charger()
    par_jour = data.setdefault(jour, {})
    par_session = par_jour.setdefault(sid, {})
    for m in (membres or []):
        try:
            mid = str(m["id"])
        except (TypeError, KeyError):
            continue
        fiche = par_session.setdefault(mid, {"secondes": 0, "premiere": ts, "derniere": ts})
        fiche["secondes"] = int(fiche.get("secondes") or 0) + int(secondes)
        fiche["derniere"] = ts
        fiche.setdefault("premiere", ts)
        nom = str(m.get("nom") or "").strip()
        if nom:
            # Le nom est note a chaque passage : un VA qui se renomme reste
            # reconnaissable dans l'historique par son identifiant, et lisible
            # par son dernier nom connu.
            fiche["nom"] = nom
    FICHIER_PRESENCE.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER_PRESENCE, data)
    return s


def premier_releve() -> Optional[float]:
    """Le tout premier instant ou quelqu'un a ete vu. None si le registre est vide.

    Sert a ne pas juger l'avant. Une session terminee avant cet instant n'a
    pas ete desertee : elle n'a pas ete REGARDEE -- le cog n'existait pas, ou
    le bot etait arrete. Sans cette borne, le premier bilan accuse tout le
    monde d'avoir manque les sessions de la veille, et c'est la premiere chose
    que le proprietaire aurait lue.
    """
    plus_tot = None
    for jours in _charger().values():
        if not isinstance(jours, dict):
            continue
        for fiches in jours.values():
            if not isinstance(fiches, dict):
                continue
            for f in fiches.values():
                try:
                    t = float((f or {}).get("premiere"))
                except (TypeError, ValueError):
                    continue
                if plus_tot is None or t < plus_tot:
                    plus_tot = t
    return plus_tot


def presences(jour: str, session_id: str = "") -> dict:
    """Ce qui est enregistre pour ce jour (et cette session si precisee)."""
    j = _charger().get(jour) or {}
    if session_id:
        return dict(j.get(session_id) or {})
    return {k: dict(v) for k, v in j.items() if isinstance(v, dict)}


def a_assiste(fiche: dict) -> bool:
    """Assez longtemps pour que ca compte comme une presence."""
    try:
        return int(fiche.get("secondes") or 0) >= config()["presence_min_secondes"]
    except Exception:
        return False


def sans_accent(t: str) -> str:
    """« Session », « sessions » et « SESSION » sont le meme mot."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t or ""))
                   if unicodedata.category(c) != "Mn").lower().replace("_", "-")


def salon_texte_ok(nom: str, motif: str, exclure: str = "") -> bool:
    """Ce salon TEXTE porte-t-il `motif` sans porter `exclure` ?

    L'exclusion n'est pas theorique : des que « session-bilan » existe, il
    porte AUSSI « session ». Sans elle, le message en direct de chaque
    session irait s'empiler dans le salon du bilan.

    Fonction PURE : un discord.TextChannel ne s'instancie pas, donc la
    decision doit pouvoir se tester sans lui.
    """
    n = sans_accent(nom)
    m = sans_accent(motif or "")
    x = sans_accent(exclure or "")
    if not m or m not in n:
        return False
    return not (x and x in n)


def salon_suivi(salon_id, nom: str = "", nom_categorie: str = "", cfg=None) -> bool:
    """Ce salon vocal fait-il partie des sessions ?

    Trois designations, de la plus precise a la plus souple : une liste
    d'identifiants, une categorie, un motif de nom. Le proprietaire hesitait
    entre « un salon par session » et « un seul salon pour toutes » : les deux
    marchent sans rien changer, parce que c'est l'HORLOGE qui decide de la
    session, jamais le salon.

    Fonction PURE : elle ne recoit que des chaines et un identifiant, donc
    elle se teste sans Discord -- un vrai VoiceChannel ne s'instancie pas.
    """
    cfg = cfg if isinstance(cfg, dict) else config()
    ids = set(cfg.get("salons") or [])
    if ids:
        try:
            return int(salon_id) in ids
        except (TypeError, ValueError):
            return False
    cat = sans_accent(cfg.get("categorie") or "")
    motif = sans_accent(cfg.get("motif_salon") or "")
    if cat and cat in sans_accent(nom_categorie):
        return True
    return bool(motif) and motif in sans_accent(nom)


FICHIER_USERS = Path("data") / "users.json"


def attendus() -> list:
    """Les VA qu'on attend aux sessions : [{id, nom, identite}].

    La source est users.json, le registre que le bot tient deja de ses VA.
    On ne garde que les identifiants NUMERIQUES : ce fichier contient aussi
    des entrees « manual_... » qui ne sont pas des comptes Discord et qui,
    mises dans la liste des attendus, ressortiraient absentes tous les jours
    de leur vie -- un reproche adresse a quelqu'un qui n'existe pas.

    Le nom rendu ici n'est qu'un repli : le cog Discord connait le vrai
    pseudo affiche et le recrit au passage.
    """
    d = safe_json.load(FICHIER_USERS, default={}) or {}
    if not isinstance(d, dict):
        return []
    out = []
    for uid, fiche in d.items():
        if not str(uid).isdigit():
            continue
        f = fiche if isinstance(fiche, dict) else {}
        out.append({
            "id": str(uid),
            "nom": str(f.get("username") or uid),
            "identite": str(f.get("identity") or f.get("identite") or ""),
        })
    out.sort(key=lambda x: x["nom"].lower())
    return out


def resume_jour(jour: str, attendus=None) -> dict:
    """Qui etait la, qui ne l'etait pas, session par session.

    `attendus` est la liste des VA qu'on attendait -- [{id, nom}] . Sans elle,
    on ne peut rendre que les presents : le registre ne sait pas qui aurait du
    venir, et INVENTER une liste d'absents a partir des presents des autres
    jours produirait des accusations fausses le jour ou quelqu'un est en
    conge.
    """
    cfg = config()
    attendus = list(attendus or [])
    index_attendus = {str(a["id"]): a for a in attendus if isinstance(a, dict) and a.get("id")}
    # DEPUIS QUAND ON REGARDE. Tout ce qui s'est termine avant est hors de
    # notre portee : on ne peut pas dire qui y etait, encore moins qui n'y
    # etait pas.
    depuis = premier_releve()
    lignes = []
    for s in sessions_du_jour(jour):
        surveillee = depuis is None or float(s["fin"]) >= float(depuis)
        brut = presences(jour, s["id"])
        presents, partiels = [], []
        for mid, fiche in brut.items():
            item = {"id": mid,
                    "nom": fiche.get("nom") or (index_attendus.get(mid) or {}).get("nom") or mid,
                    "secondes": int(fiche.get("secondes") or 0),
                    "premiere": fiche.get("premiere"),
                    "derniere": fiche.get("derniere"),
                    "attendu": mid in index_attendus}
            (presents if a_assiste(fiche) else partiels).append(item)
        presents.sort(key=lambda x: -x["secondes"])
        partiels.sort(key=lambda x: -x["secondes"])
        vus = {p["id"] for p in presents} | {p["id"] for p in partiels}
        # AUCUN ABSENT SUR UNE SESSION QU'ON NE REGARDAIT PAS. La liste serait
        # complete -- tout le monde -- et entierement fausse.
        absents = ([dict(a, id=str(a["id"])) for a in attendus
                    if str(a["id"]) not in vus] if surveillee else [])
        lignes.append({
            "id": s["id"], "nom": s["nom"],
            "heure": "%02d:%02d" % (s["heure"], s["minute"]),
            "heures_locales": heures_locales(s),
            "debut": s["debut"], "fin": s["fin"],
            "presents": presents, "partiels": partiels, "absents": absents,
            # Sans liste d'attendus, « absents » est vide et ne veut RIEN
            # dire : l'ecran doit pouvoir le distinguer d'un « personne ne
            # manquait ». Idem pour une session non surveillee.
            "attendus_connus": bool(attendus) and surveillee,
            "surveillee": surveillee,
        })
    return {"jour": jour, "fuseau": cfg["fuseau"], "sessions": lignes}


def resume_par_personne(jour: str, attendus=None) -> list:
    """Le meme jour, vu par VA : combien de sessions sur combien.

    C'est cette vue-la qu'on lit pour dire « untel n'est jamais la », et c'est
    elle qui doit servir de base a toute consequence -- pas une impression.
    """
    r = resume_jour(jour, attendus)
    # « 1 sur 4 » n'a de sens que si les quatre ont ete regardees. Compter une
    # session non surveillee au denominateur fabrique une assiduite fausse,
    # et c'est le chiffre sur lequel on juge quelqu'un.
    surveillees = [x for x in r["sessions"] if x.get("surveillee", True)]
    total = len(surveillees)
    gens = {}
    for s in surveillees:
        for p in s["presents"]:
            g = gens.setdefault(p["id"], {"id": p["id"], "nom": p["nom"],
                                          "presentes": 0, "secondes": 0,
                                          "sessions": []})
            g["presentes"] += 1
            g["secondes"] += p["secondes"]
            g["sessions"].append(s["id"])
            g["nom"] = p["nom"] or g["nom"]
        for p in s["partiels"]:
            gens.setdefault(p["id"], {"id": p["id"], "nom": p["nom"],
                                      "presentes": 0, "secondes": 0, "sessions": []})
    for a in (attendus or []):
        aid = str(a.get("id") or "")
        if aid and aid not in gens:
            gens[aid] = {"id": aid, "nom": a.get("nom") or aid,
                         "presentes": 0, "secondes": 0, "sessions": []}
    out = list(gens.values())
    for g in out:
        g["sur"] = total
        g["manquees"] = max(0, total - g["presentes"])
    out.sort(key=lambda g: (-g["presentes"], g["nom"].lower()))
    return out


def purger(jours_gardes: int = 120) -> int:
    """Efface les journees trop anciennes. Rend le nombre de journees retirees.

    Le registre grossit d'un peu chaque minute : sans purge, il finit par etre
    relu en entier a chaque tour de boucle.
    """
    import time as _t
    limite = (_dt.datetime.fromtimestamp(_t.time(), _tz()).date()
              - _dt.timedelta(days=max(1, int(jours_gardes)))).isoformat()
    data = _charger()
    vieux = [j for j in data if j < limite]
    if not vieux:
        return 0
    for j in vieux:
        data.pop(j, None)
    safe_json.write(FICHIER_PRESENCE, data)
    return len(vieux)
