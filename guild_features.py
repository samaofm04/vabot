"""Gating des fonctions par serveur Discord (multi-serveurs).

Principe :
- Un serveur NON listé dans data/guild_features.json a **toutes** les fonctions
  (le serveur principal n'est donc jamais impacté, aucune config requise).
- Un serveur **listé** n'a QUE les fonctions de sa liste (serveur « bridé »).
- You US et You FR sont bridés par le CODE (FONCTIONS_PAR_DEFAUT), sans
  dépendre du fichier ; une entrée du fichier passe devant.

Fonctions (clés) :
- contenu    : menu de contenu (Reel/Story/Post/Pseudo/Name/Bio/PP) + boutons
               Ajouter un compte / Mes comptes Insta
- onboarding : parcours d'arrivée (vidéos + étapes)
- clics      : bouton Mes clics + récap quotidien des clics
- liens      : Demander un lien + Générer le lien (GMS)
- tickets    : création auto d'un salon/ticket à l'arrivée d'un membre
- statut     : ronds 🟢/🟠/🔴 d'activité devant les salons va-
"""
import json
import pathlib
import safe_json

_FILE = pathlib.Path(__file__).resolve().parent / "data" / "guild_features.json"

ALL_FEATURES = ("contenu", "onboarding", "clics", "liens", "tickets", "statut", "rappels")


def _load() -> dict:
    try:
        d = safe_json.load_or_prev(_FILE)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> bool:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_FILE, json.dumps(d, indent=2, ensure_ascii=False))
        return True
    except Exception:
        return False


def _gid(guild_or_id):
    """Accepte un id, un objet guild, ou None -> renvoie un str ou None."""
    if guild_or_id is None:
        return None
    gid = getattr(guild_or_id, "id", guild_or_id)
    try:
        return str(int(gid))
    except Exception:
        return None


def get_features(guild_or_id) -> set:
    """Set des fonctions activées pour ce serveur.
    Serveur inconnu / non configuré -> TOUTES les fonctions (non bridé)."""
    gid = _gid(guild_or_id)
    if gid is None:
        return set(ALL_FEATURES)
    if gid in NUMERO_SEUL:
        return set(NUMERO_SEUL_GARDE)
    v = _load().get(gid)
    if v is None:
        # Pas d'entree dans le fichier : le bridage que le CODE porte pour ce
        # serveur (FONCTIONS_PAR_DEFAUT), s'il en a un.
        v = FONCTIONS_PAR_DEFAUT.get(gid)
    if v is None:
        return set(ALL_FEATURES)
    if not isinstance(v, (list, tuple)):
        return set(ALL_FEATURES)
    return {x for x in v if x in ALL_FEATURES}


def enabled(guild_or_id, feature: str) -> bool:
    """True si `feature` est active sur ce serveur (toujours True si non bridé)."""
    return feature in get_features(guild_or_id)


#: Serveurs SANS aucun rappel (Story du jour, Reel, Story CTA, suivi des
#: comptes). Va IG, proprietaire 03/10/2026 : « je veux plus de rappel, je
#: vais creer un truc dans annonce ; pour savoir si le mec est actif : s'il
#: demande des photos c'est good ». L'activite se lit aux clics sur le menu
#: (cogs/vaactivity, alimente par le bot principal), pas aux rappels.
SANS_RAPPELS = {"1505418484052394004"}   # Va IG


def reminders_enabled(guild_or_id) -> bool:
    """True si les rappels/suivi (Story du jour, Reel, Suivi des comptes…) sont
    actifs sur ce serveur. OFF automatiquement en mode Threads (c'est Threads,
    pas Insta) et sur les serveurs de SANS_RAPPELS, et désactivable via la
    fonction 'rappels'."""
    return (enabled(guild_or_id, "rappels") and not threads_mode(guild_or_id)
            and _gid(guild_or_id) not in SANS_RAPPELS)


#: Serveurs où le bot écrit dans le salon « rappels », au lieu des rappels
#: dans chaque ticket : UNE annonce publique par tâche et par jour (Story 10h,
#: Reel 16h, Story CTA 20h), au plus 3 relances anonymes tant qu'un VA n'a pas
#: cliqué, et le message « comptes » lundi, jeudi et dimanche. Va IG,
#: propriétaire 03/10/2026 : « c'est le mec qui clique mais tout le monde peut
#: le faire, chacun voit son truc en vert, ça change que pour lui ». Les autres
#: serveurs gardent leurs rappels par ticket (reminders_enabled) et ne
#: reçoivent rien de tout ça. Un serveur d'ici doit aussi être dans
#: SANS_RAPPELS, sinon il reçoit les deux.
ANNONCES_POST = {"1505418484052394004"}   # Va IG


def annonces_post_enabled(guild_or_id) -> bool:
    """True si ce serveur reçoit les annonces, relances et message comptes du
    salon « rappels » (cogs/cta_reminder.AnnoncesPost)."""
    return _gid(guild_or_id) in ANNONCES_POST


def is_restricted(guild_or_id) -> bool:
    """True si le serveur est explicitement configuré (bridé)."""
    gid = _gid(guild_or_id)
    return gid is not None and gid in _load()


# ---- Serveur(s) US (Youl4b, YouCham) ----
# Les commandes dédiées US (/menujailbreakus, /ticketsall) ne marchent QUE sur
# ces serveurs : partout ailleurs elles refusent — le serveur principal ne peut
# pas être impacté, même par erreur.
#
# YouCham (30/10/2026, propriétaire : « branche tout comme youl4b ») : mêmes
# rôles et salons communs, recopiés de Youl4b. Sans lui dans cette liste, un
# VA qui y arrivait recevait le ticket VA CLASSIQUE (setup_va_ticket :
# identité de rotation, fiche users.json, salons cachés) au lieu de son
# dossier perso. LA liste : arrivée, menu Jailbreak US, ✨ General, spoofer,
# téléchargement, générateur de lien et alerte des 500 salons la lisent —
# aucun module ne recopie l'id de YouCham.
YOUL4B_GUILD_ID = "1535758943324999711"
YOUCHAM_GUILD_ID = "1565640097146347533"
# You US et You FR (10/11/2026, propriétaire : « un serveur uniquement dédié
# pour le marché français … et un exprès pour le marché US, pour mes pôles à
# moi. Ça reprend le même style que YouLab Spam … le seul truc qui importe,
# c'est le bot avec le menu, le spoofer, download, numéro, email. Ça, il faut
# que je le retrouve au niveau des deux nouveaux serveurs »). Branchés comme
# YouCham. « Serveur US » dit ici le MODÈLE de serveur, celui de Youl4b (un
# salon perso par membre, menu ouvert à tous, outils communs), pas le marché :
# celui de You FR est « fr » (MARCHE_SERVEUR).
YOU_US_GUILD_ID = "1569560765961207909"
YOU_FR_GUILD_ID = "1569560463887442022"
#: id -> nom court, pour les textes (« serveurs US : Youl4b, YouCham »).
US_GUILDS = {YOUL4B_GUILD_ID: "Youl4b", YOUCHAM_GUILD_ID: "YouCham",
             YOU_US_GUILD_ID: "You US", YOU_FR_GUILD_ID: "You FR"}
US_GUILD_IDS = set(US_GUILDS)


def is_us_guild(guild_or_id) -> bool:
    """True si ce serveur est un serveur US (Youl4b, YouCham, You US, You FR)."""
    return _gid(guild_or_id) in US_GUILD_IDS


def is_youl4b(guild_or_id) -> bool:
    """True pour Youl4b SEUL, le serveur US d'origine.

    Ce qui n'existe qu'UNE fois pour tout le marché US y reste : le salon
    admin bases-identites (pages TEMPLATE GetMySocial communes à l'équipe),
    les alertes staff du debrief-day (numgen.ALERTES_SALON), les logins
    ProxEasy et suivi-proxy, inflow-resultat. Le propriétaire garde ces
    outils de son côté ; YouCham n'a recopié ni « proxy » ni « base ». Un
    second exemplaire sur YouCham doublerait l'alerte ou le panneau."""
    return _gid(guild_or_id) == YOUL4B_GUILD_ID


def noms_us() -> str:
    """« Youl4b, YouCham, You US, You FR » : les serveurs US, pour les textes
    montrés."""
    return ", ".join(US_GUILDS[g] for g in US_GUILDS if g in US_GUILD_IDS)


#: Serveurs US aux outils COMMUNS (outils_communs.py) : quatre salons pour
#: tous dans « 🧰 OUTILS » (menu, spoofer, download, numéro) et UN salon
#: <pseudo>-content par VA, au lieu du dossier de cinq salons de Youl4b.
#: Propriétaire, 30/10/2026 : « sur YouCham, un salon où tout le monde voit
#: un menu en commun, un spoofer en commun, un download en commun, un numéro
#: en commun, et un content qui est leur ticket à eux ». A 5 salons par VA,
#: Discord (500 salons par serveur) arrête un serveur vers 100 VA. LA liste :
#: arrivée, /ticketsall, rattrapage des dossiers (completer_dossiers_us),
#: entretien du spoofer, menu, spoofer, download et numéro la lisent --
#: jamais l'id recopié.
OUTILS_COMMUNS = {YOUCHAM_GUILD_ID, YOU_US_GUILD_ID, YOU_FR_GUILD_ID}

#: Les serveurs aux outils communs qui ont AUSSI le 📊・click-et-sub : la page
#: des liens de suivi de Lia, celle des VA de YouCham (leurs liens, leurs
#: subs). Créé partout, le salon aurait montré à You US et à You FR les
#: chiffres des VA de YouCham, redessinés toutes les heures.
CLICS_ET_SUBS = {YOUCHAM_GUILD_ID}

#: Le marché d'un serveur ENTIER, quand tout le monde y travaille le même :
#: You FR (« uniquement dédié pour le marché français ») et You US. Le menu y
#: sert à chacun les models de CE marché, sans rôle @Jailbreak FR / US à
#: poser : cogs/welcome.SANS_ROLE_JAILBREAK les reprend, à côté de Va IG, et
#: cogs/user.marche_du_membre le lit. Sans cette table, un membre de You FR,
#: sans rôle, recevait le menu US -- « us » est le défaut d'un serveur US.
#: Personne n'y a UNE model à lui : les 💥・banger-<model> y sont à tous
#: (cogs/welcome.auto_secure_general_channels, qui les cache ailleurs aux
#: VA d'une autre model, passe ces serveurs).
MARCHE_SERVEUR = {YOU_US_GUILD_ID: "us", YOU_FR_GUILD_ID: "fr"}

#: Les serveurs dont les salons bangers reçoivent, en COPIE, ceux de leur
#: marché (bangers_miroir.py) : « us » = le 💥・banger et le 💣・all-banger de
#: Youl4b, « fr » = les 🔥・banger-<model> de Va IG. Propriétaire, 10/11/2026 :
#: « sur FR … il va falloir quand même retrouver banger Emma, banger Amelia …
#: et sur l'autre, comme d'hab, banger et all-banger », puis « oui, les
#: bangers ». Ses équipes n'ont pas encore de comptes à elles dans le relevé :
#: rien d'autre n'alimenterait ces salons. Une table à part du marché : couper
#: la copie d'un serveur ne doit pas changer son menu.
BANGERS_MIROIR = dict(MARCHE_SERVEUR)

#: Les serveurs où le rôle d'une model s'écrit dans le pseudo du membre :
#: « yous1m (AMELIA) » (pseudo_model.py). Propriétaire, 10/11/2026, devant You
#: FR : « tu peux créer un rôle par model … y a le rôle Amelia, Lola etc. et …
#: ça change leur name dans le serveur, genre yous1m (AMELIA) ». Les models
#: sont celles du marché du serveur (les mêmes que ses salons banger). Le
#: rôle n'est qu'une étiquette : il n'ouvre ni ne ferme rien, le menu et les
#: bangers restent à tous (MARCHE_SERVEUR).
PSEUDO_MODEL = {YOU_FR_GUILD_ID}

#: Les serveurs qui achètent leurs numéros sur le compte GetAText des serveurs
#: TRUST sans en être un (numgen.serveurs_compte_trust), id -> nom court.
#: Propriétaire, 10/11/2026 : « je veux use des num avec API du serv trust
#: instagram », puis « change juste API du fournisseur … pour les SMS sur You
#: FR ». Seul le COMPTE change : la clé qui achète, le solde affiché sur le
#: panneau et son alerte « sans crédit ». Ni la vignette GetAText (« seulement
#: TRUST », 08/11/2026 : elle reste lue dans numgen.TRUST_SERVEURS), ni les
#: paliers de numéros par jour de TRUST INSTAGRAM, ni le pays des numéros.
#: You US reste sur le compte principal : il l'avait d'abord demandé pour ce
#: serveur, puis a dit « stop laisse tomber » et nommé You FR. Sans la clé
#: TRUST, ces serveurs achètent sur le compte principal, comme avant.
NUMEROS_COMPTE_TRUST = {YOU_FR_GUILD_ID: "You FR"}

#: Le bridage que le CODE porte, pour les serveurs absents de
#: data/guild_features.json : les fonctions de YouCham (tout sauf « statut »,
#: les ronds des salons va-, qui n'existent pas sur un serveur US). Celles de
#: YouCham vivent dans le fichier du VPS, posé à la main le 30/10/2026 ; data/
#: n'est pas dans git, You US et You FR auraient donc eu TOUTES les fonctions
#: jusqu'à ce que quelqu'un pense au fichier. Une entrée du fichier passe
#: devant celle-ci (get_features).
FONCTIONS_PAR_DEFAUT = {
    g: ("contenu", "onboarding", "clics", "liens", "tickets", "rappels")
    for g in (YOU_US_GUILD_ID, YOU_FR_GUILD_ID)}


#: Serveurs ou le bot admin (Rem) ne sert QUE le numero : le panneau du
#: salon « numéro » et, au clic, une carte ephemere de 15 min, comme le
#: 📱・numéro de YouCham (cogs/numeros.clic_partage), 3 numeros par jour et
#: par VA. Proprietaire, 31/10/2026 : « mettre ce bot aussi juste pour ca pour
#: un autre server juste le numero dans ce serv », puis « limite a 3 par jour
#: pour le server trust instagram ». Aucune autre fonction de Rem n'y tourne
#: (get_features, sauf NUMERO_SEUL_GARDE) : un serveur inconnu les a TOUTES, et le tri des salons va-
#: (vasort) s'y lancait toutes les 20 min. Le reste de TRUST INSTAGRAM est a
#: Revel, par REST, qui ne lit pas ce fichier. id -> nom court.
NUMERO_SEUL: dict = {"1488331963575177247": "TRUST INSTAGRAM"}

#: Ce que ces serveurs GARDENT : le 🎬 Contenu des tickets (contenu_tickets)
#: joue les commandes du menu US de Yoshi avec une interaction de CE serveur,
#: et leur garde (_gate_contenu) lit get_features. Avec un ensemble vide,
#: chaque clic du Contenu repondait « Cette fonction est désactivée sur ce
#: serveur » (31/10/2026, ticket de jackson_lord1, 9 refus). Aucun cog de
#: Rem ne lit « contenu », et Yoshi n'est pas sur TRUST INSTAGRAM.
NUMERO_SEUL_GARDE = frozenset({"contenu"})


def numero_seul(guild_or_id) -> bool:
    """True si le bot ne sert que le numero sur ce serveur."""
    return _gid(guild_or_id) in NUMERO_SEUL


def outils_communs(guild_or_id) -> bool:
    """True si ce serveur a les outils communs (YouCham, You US, You FR).
    Toujours un serveur US : hors US_GUILD_IDS, le menu Jailbreak US n'y
    serait pas servi."""
    g = _gid(guild_or_id)
    return g in OUTILS_COMMUNS and g in US_GUILD_IDS


def clics_et_subs(guild_or_id) -> bool:
    """True si ce serveur aux outils communs a le 📊・click-et-sub (YouCham)."""
    g = _gid(guild_or_id)
    return g in CLICS_ET_SUBS and outils_communs(g)


def marche_serveur(guild_or_id):
    """« fr » ou « us » pour un serveur au marché unique (MARCHE_SERVEUR),
    None partout ailleurs."""
    return MARCHE_SERVEUR.get(_gid(guild_or_id))


def pseudo_model(guild_or_id) -> bool:
    """True si, sur ce serveur, le rôle d'une model s'écrit dans le pseudo."""
    return _gid(guild_or_id) in PSEUDO_MODEL


def set_features(guild_or_id, features) -> set:
    """Définit la liste des fonctions d'un serveur (le bride). Retourne le set."""
    gid = _gid(guild_or_id)
    if gid is None:
        return set(ALL_FEATURES)
    d = _load()
    d[gid] = [f for f in features if f in ALL_FEATURES]
    _save(d)
    return get_features(gid)


def clear_guild(guild_or_id) -> bool:
    """Retire le bridage d'un serveur -> il repasse à TOUTES les fonctions."""
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load()
    if gid in d:
        d.pop(gid, None)
        _save(d)
        return True
    return False


# ---- Mode Threads (par serveur) : menu réduit + comptes Threads au lieu d'Instagram ----
# Stocké à part pour ne pas toucher le format des fonctions. Défaut = OFF partout
# (donc le serveur principal reste en mode Instagram normal).
_THREADS_FILE = pathlib.Path(__file__).resolve().parent / "data" / "guild_threads.json"


def _load_threads() -> dict:
    try:
        d = json.loads(_THREADS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def threads_mode(guild_or_id) -> bool:
    """True si le serveur est en mode Threads (menu réduit + comptes threads.net)."""
    gid = _gid(guild_or_id)
    return bool(gid is not None and _load_threads().get(gid))


def set_threads(guild_or_id, on: bool) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_threads()
    if on:
        d[gid] = True
    else:
        d.pop(gid, None)
    try:
        _THREADS_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_THREADS_FILE, json.dumps(d, indent=2, ensure_ascii=False))
    except Exception:
        return False
    return bool(on)


# ---- Catégorie d'accueil des nouveaux VAs (par serveur) ----
# Si définie, les nouveaux salons va- d'un serveur vont dans CETTE catégorie
# (ex: "Equipe 1") au lieu d'une catégorie par identité.
_VACAT_FILE = pathlib.Path(__file__).resolve().parent / "data" / "va_category.json"


def _load_vacat() -> dict:
    try:
        d = json.loads(_VACAT_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_va_category_id(guild_or_id):
    """ID de la catégorie où placer les nouveaux salons va- de ce serveur, ou None."""
    gid = _gid(guild_or_id)
    if gid is None:
        return None
    try:
        return int(_load_vacat().get(gid)) if _load_vacat().get(gid) else None
    except Exception:
        return None


def set_va_category(guild_or_id, category_id) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_vacat()
    if category_id:
        d[gid] = int(category_id)
    else:
        d.pop(gid, None)
    try:
        _VACAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_VACAT_FILE, json.dumps(d, indent=2, ensure_ascii=False))
    except Exception:
        return False
    return True


# ---- Identité par défaut d'un serveur (ex: "jessye" pour le marché US) ----
# Si définie, les nouveaux VAs de ce serveur reçoivent CETTE identité au lieu
# de la rotation normale (qui exclut les identités jailbreak-only). Permet
# d'avoir un marché US séparé du marché français.
_SVID_FILE = pathlib.Path(__file__).resolve().parent / "data" / "server_identity.json"


def _load_svid() -> dict:
    try:
        d = json.loads(_SVID_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_server_identity(guild_or_id):
    """Identité par défaut des VAs de ce serveur (str), ou None."""
    gid = _gid(guild_or_id)
    if gid is None:
        return None
    v = _load_svid().get(gid)
    return v if (isinstance(v, str) and v.strip()) else None


def serveurs_avec_identite(ident) -> list:
    """Ids (str) des serveurs dont `ident` est l'identité dédiée.

    Sert au site, avant de faire d'une entrée une RÉSERVE : _link_identity
    rend l'identité dédiée du serveur pour chacun de ses VA, quelle que soit
    celle stockée dans users.json. Compter les seuls VA laissait donc passer
    une entrée qui sert encore tout un serveur."""
    idl = str(ident or "").strip().lower()
    if not idl:
        return []
    return sorted(g for g, v in _load_svid().items()
                  if isinstance(v, str) and v.strip().lower() == idl)


def set_server_identity(guild_or_id, ident) -> bool:
    gid = _gid(guild_or_id)
    if gid is None:
        return False
    d = _load_svid()
    if ident and str(ident).strip():
        d[gid] = str(ident).strip().lower()
    else:
        d.pop(gid, None)
    try:
        _SVID_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_SVID_FILE, json.dumps(d, indent=2, ensure_ascii=False))
    except Exception:
        return False
    return True
