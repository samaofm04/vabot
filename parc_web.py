"""parc_web.py — le coeur du poste de pilotage du parc (onglet « Remote 2 »).

POURQUOI CE MODULE EXISTE
-------------------------
L'onglet Remote actuel montre ce que le poste pousse, brut. Il ne sait pas
dire : ce qui VA se passer, ce qui a ete REFUSE, depuis QUAND un chiffre n'a
pas bouge, ni QUI tient le telephone. La nuit du 21/08 l'a demontre : quatre
agents empiles sur un seul iPhone, WebDriverAgent qui tombait toutes les
20 s, un registre annoncant 33 conteneurs pour 1 conteneur reel, et des
ecrans « confirm that you're human » archives comme des reussites. Rien de
tout cela n'etait visible a l'ecran.

Ce module tient les cinq pieces qui manquaient, et RIEN d'autre :
  1. les REGLAGES (data/parc_regles.json) — tout est pre-configure ;
  2. le PLANIFICATEUR — fonctions PURES : il dit quoi faire et quand, sans
     rien executer (aucune ecriture dans rig_jobs.json, aucun thread) ;
  3. les GARDE-FOUS — une fonction par controle, chacune rendant un
     diagnostic (nom, gravite, message, bloquant) ;
  4. le JOURNAL — append-only, borne en taille, filtrable ;
  5. les AGREGATS et les GRAPHIQUES (SVG rendus COTE SERVEUR : Chart.js est
     bloque cote client dans ce projet).

Plus l'OBSERVATEUR, sans lequel rien du reste n'existe : le poste ne
transmet ni date de creation, ni date de derniere action, ni duree, ni
identite de machine. L'observateur derive tout cela de ce que le poste
pousse DEJA, en comparant chaque declaration a la precedente. Sans lui, les
trois tris demandes (plus recent / dernier cree / plus vieux) sont
impossibles et aucune duree n'existe.

CE QUI FAIT QUE « CA TOURNE TOUT SEUL »
----------------------------------------
Une HORLOGE (thread daemon, section 15 ter) joue un tour toutes les
`tick_s` secondes et, elle seule, demande l'execution. Sans elle,
`regles["pilote"]` etait un interrupteur que RIEN ne lisait : on cliquait
« DEMARRER LE PARC », on fermait son navigateur, et au matin il n'y avait
ni publication, ni travail dans la file, ni trace de la nuit.

L'inscription reelle passe par `inscrire_travaux()` (section 15), qui porte
les trois precautions verifiees dans le code :
  * rig_jobs.json ne garde que 80 travaux (web_upload.py, `[:80]`) : on
    respecte le meme plafond, et un travail qu'on refuse d'inscrire faute
    de place est journalise, jamais avale. Le planificateur n'emet de toute
    facon que `lot_par_tick` travaux par tour, et seulement pour une machine
    LIBRE : la file ne peut pas se remplir d'un coup.
  * Remote 2 et /api/rig/pull ecrivent le meme fichier sans verrou partage :
    on relit apres avoir ecrit, on re-inscrit une fois ce qui a disparu, et
    on journalise `course_file` (gf_course_fichier le compte deja).
  * chaque travail est pre-enregistre dans l'historique AVEC sa machine,
    sans quoi l'observateur le redecouvrirait au pull suivant et lui
    collerait une attribution inventee.

Deux verrous avant toute ecriture, et ils sont dans tick() : `pilote` (faux
en usine) et le pre-vol. Un clic humain sur « Jouer un tour » reste une
SIMULATION — seule l'horloge execute.

Aucune ligne de /api/rig/*, ni de l'onglet Remote, n'est modifiee.

CONTRAT DU MODULE (patron facture_web / noctus_web)
---------------------------------------------------
Deux fonctions publiques : `render_page()` et `register(app, is_auth)`.
Le module n'importe JAMAIS web_upload — sinon import circulaire au
demarrage. Ses dependances arrivent par register().
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import safe_json

# ---------------------------------------------------------------- chemins
# RELATIF au cwd (= bot/) : c'est ce qui permet aux tests de rediriger
# parc_web.REGLES_FILE vers un dossier temporaire sans toucher les vraies
# donnees. BOT_DIR est ABSOLU parce qu'un asset doit etre trouve quel que
# soit le cwd du process.
DATA_DIR = Path("data")
BOT_DIR = Path(__file__).parent.resolve()

# Fichiers que CE module possede (prefixe parc_) — il est le seul a ecrire.
REGLES_FILE = DATA_DIR / "parc_regles.json"
ETAT_FILE = DATA_DIR / "parc_etat.json"
HIST_FILE = DATA_DIR / "parc_hist.json"
ECARTS_FILE = DATA_DIR / "parc_ecarts.json"
MEDIAS_VUS_FILE = DATA_DIR / "parc_medias_vus.json"
TOURS_FILE = DATA_DIR / "parc_tours.json"
JOURNAL_FILE = DATA_DIR / "parc_journal.jsonl"
JOURNAL_ROT = DATA_DIR / "parc_journal.1.jsonl"
# Le releve REEL du telephone. Le poste l'ecrit a la main dans
# inventaire_telephone.json et ne le pousse pas : tant qu'il n'arrive pas
# ici, le controle registre<->realite est ○ non declare, jamais vert.
INVENTAIRE_FILE = DATA_DIR / "parc_inventaire.json"

# Fichiers ecrits par web_upload (ce que le poste pousse). LECTURE SEULE.
RIG_PARC = DATA_DIR / "rig_parc.json"
RIG_JOBS = DATA_DIR / "rig_jobs.json"
RIG_ACTIONS = DATA_DIR / "rig_actions.json"
RIG_SCENARIOS = DATA_DIR / "rig_scenarios.json"
RIG_PILOTAGE = DATA_DIR / "rig_pilotage.json"

_LOCK_REGLES = threading.Lock()
_LOCK_ETAT = threading.Lock()
_LOCK_HIST = threading.RLock()
_LOCK_ECARTS = threading.Lock()
_LOCK_JOURNAL = threading.RLock()
_LOCK_TICK = threading.RLock()
_LOCK_FILE = threading.RLock()

# ---------------------------------------------------------------- banc d'essai
# L'observateur est un after_request GLOBAL : il se declenchait aussi sur les
# requetes de tests_site.py, qui poste un travail de synthese sur
# /api/rig/jobs. Mesure faite : parc_hist.json 557 -> 762 octets, une ligne
# {"evt":"hors_plan","detail":"inscrit dans la file"} de plus dans le VRAI
# journal a CHAQUE passage de tests — un « travail parti sans que le plan le
# demande » qui n'a jamais eu lieu sur un telephone. Au bout de quelques
# semaines, « 12 travaux hors plan » dans Ecarts, ce sont douze lancements de
# tests, et on cherche une panne qui n'existe pas.
# Deux interrupteurs, parce que les deux servent :
#   * la variable d'environnement, posee par tests_site.py AVANT d'importer
#     web_upload — c'est elle qui protege le banc d'essai ;
#   * l'attribut de module, pour un test qui voudrait observer volontairement.
_ENV_BANC = "VABOT_BANC_ESSAI"
OBSERVATEUR_ACTIF = True


def observateur_actif() -> bool:
    """Faux quand on tourne sous banc d'essai. Lu A CHAQUE REQUETE (et pas au
    chargement du module) : tests_site.py importe web_upload tres tot, et un
    drapeau fige a l'import aurait ete pris avant que la variable soit
    posee."""
    import os
    if str(os.environ.get(_ENV_BANC) or "").strip() in ("1", "true", "oui"):
        return False
    return bool(OBSERVATEUR_ACTIF)

# Nom de repli quand l'agent ne dit pas qui il est. Le jour ou il joint un
# champ « machine » au corps du /pull, l'ecran passe a N machines sans une
# ligne de plus ici.
MACHINE_DEFAUT = "poste-1"

# Ce qu'on affiche quand PERSONNE n'a declare la machine. Un nom de machine
# invente est pire qu'un trou : le tableau agrege rendait « poste-1 · test ·
# 67 comptes » a 250 comptes et 5 machines, soit une attribution fabriquee
# dans le seul tableau cense porter cette dimension.
MACHINE_NON_DECLAREE = "machine non declaree"

# Les 8 etapes du cycle, dans l'ordre de cycle.py. Sert au graphique de
# couverture : 8 colonnes que le parc fasse 33 ou 2 500 conteneurs.
ETAPES = ["conteneur", "medias", "instagram", "numero", "identite", "fin",
          "profil", "reels"]

# ---------------------------------------------------------------- provenance
# Un chiffre nu est interdit. Chacun porte sa marque : ce que le poste a
# reellement mesure, ce que le site a derive, ce que personne ne declare.
# Un ○ n'est JAMAIS un vert par defaut : un controle qu'on ne peut pas faire
# n'est pas un controle reussi.
MESURE = "mesure"
DERIVE = "derive"
NON_DECLARE = "non_declare"
_MARQUES = {MESURE: "●", DERIVE: "◐", NON_DECLARE: "○"}


def marque(provenance: str) -> str:
    """Le pictogramme de provenance a coller a cote d'un chiffre."""
    return _MARQUES.get(provenance, "○")


# ---------------------------------------------------------------- temps
def maintenant() -> float:
    """Une seule porte vers l'horloge : les tests la remplacent d'un coup."""
    return time.time()


def _age(ts) -> float:
    """Age en secondes d'un horodatage. -1 si l'horodatage n'existe pas —
    « je ne sais pas » ne doit jamais ressembler a « c'est frais »."""
    try:
        t = float(ts or 0)
    except (TypeError, ValueError):
        return -1.0
    if t <= 0:
        return -1.0
    return max(0.0, maintenant() - t)


def duree_humaine(secondes) -> str:
    """« 3 j 14 h », « 41 min », « 26 s ». Un ecran de pilotage se lit d'un
    coup d'oeil : 298 800 secondes ne se lisent pas."""
    try:
        s = int(float(secondes))
    except (TypeError, ValueError):
        return "?"
    if s < 0:
        return "?"
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 86400:
        h, m = divmod(s // 60, 60)
        return "%d h %02d" % (h, m) if m else "%d h" % h
    j = s // 86400
    h = (s % 86400) // 3600
    return "%d j %d h" % (j, h) if h else "%d j" % j


def _hhmm(txt, defaut_min: int = 0) -> int:
    """« 10:30 » -> 630 minutes depuis minuit. Tolerant : une saisie
    incomprehensible rend le defaut au lieu de faire tomber la page."""
    m = re.match(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})\s*$", str(txt or ""))
    if not m:
        return defaut_min
    h = min(23, int(m.group(1)))
    mi = min(59, int(m.group(2) or 0))
    return h * 60 + mi


def _mmhh(minutes: int) -> str:
    """L'inverse : 630 -> « 10:30 ». Une fenetre se relit telle qu'ecrite."""
    minutes = max(0, min(24 * 60, int(minutes)))
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def _minute_du_jour(ts: float) -> int:
    d = datetime.fromtimestamp(ts)
    return d.hour * 60 + d.minute


def _debut_du_jour(ts: float) -> float:
    d = datetime.fromtimestamp(ts)
    return datetime(d.year, d.month, d.day).timestamp()


def _esc(x) -> str:
    """Echappement pour le SVG genere ici. Un nom de conteneur vient du
    poste : il n'a aucune raison de contenir un chevron, mais on ne parie
    pas la page dessus."""
    return (str("" if x is None else x).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


# ---------------------------------------------------------------- codes
# LISTE COURTE ET FERMEE. Le champ job.erreur actuel est la derniere ligne
# de stdout tronquee a 300 caracteres : ingroupable, donc incomptable. Sans
# table fermee, « ce qui cloche » ne peut pas etre agrege par cause.
# `inconnu` garde les 300 caracteres bruts ET est compte a part : le jour ou
# il est premiere cause, c'est la table qui est a completer, et ca se voit.
CODES = {
    "wda_injoignable": "WebDriverAgent ne repond pas — relancer WDA sur le poste",
    "wda_predicate_refuse": "WDA refuse « -ios predicate string » — corriger le scenario",
    "wda_session_recreee": "session WDA recreee — signature d'un conflit multi-agents",
    "tunnel_muet": "le tunnel media est mort — le relancer, sinon zero publication",
    "captcha": "ecran « confirm that you're human » — verification humaine",
    "pseudo_discordant": "le pseudo a l'ecran n'est pas celui attendu — publication refusee",
    "compte_deconnecte": "le compte est deconnecte — reconnexion a la main",
    "conteneur_introuvable": "le conteneur n'existe plus sur le telephone — recenser",
    "pellicule_non_videe": "la pellicule n'a pas ete videe — vider avant de reprendre",
    "stock_vide": "aucun media dans la categorie — recharger le Vault",
    "hors_fenetre": "passage du hors de la fenetre horaire — reporte",
    "doublon": "un travail vise deja ce conteneur — refuse",
    "expire_900s": "aucune nouvelle depuis 15 min — le travail a ete degrippe",
    "agent_disparu": "l'agent est mort en cours de travail",
    "refus_garde_fou": "un garde-fou a refuse le travail",
    "course_file": "ecriture perdue sur rig_jobs.json — travail re-inscrit",
    "sans_categorie": "conteneur sans categorie — l'etape des medias echouerait",
    "abandonne": "conteneur marque abandonne",
    "quarantaine": "conteneur en quarantaine apres echecs repetes",
    "repetition_media": "video rejouee avant son repos",
    "reussite_douteuse": "fini trop vite pour etre vrai",
    "inconnu": "cause non classee — completer la table des codes",
}

_MOTIFS = [
    (r"predicate", "wda_predicate_refuse"),
    (r"session (invalide|recre)", "wda_session_recreee"),
    (r"(8100|webdriveragent|wda)", "wda_injoignable"),
    (r"(tunnel|localtunnel)", "tunnel_muet"),
    (r"(confirm that you|captcha|verification humaine|humain)", "captcha"),
    (r"(pseudo|mauvais compte|bon compte)", "pseudo_discordant"),
    (r"(deconnect|log ?in|se connecter)", "compte_deconnecte"),
    (r"(conteneur .*introuv|introuvable)", "conteneur_introuvable"),
    (r"pellicule", "pellicule_non_videe"),
    (r"(aucun media|stock vide|aucune video)", "stock_vide"),
]


def classer_erreur(brut: str) -> str:
    """Range une fin de stdout dans la table fermee des codes.

    POURQUOI : sans code court, deux occurrences du meme incident ne se
    ressemblent pas (l'une finit par « ... timeout 30s », l'autre par
    « ... connection refused ») et « 12x wda_injoignable » est impossible a
    ecrire. Ce qui n'est pas reconnu devient `inconnu` — jamais ecarte.
    """
    t = (brut or "").lower()
    if not t.strip():
        return "inconnu"
    for motif, code in _MOTIFS:
        if re.search(motif, t):
            return code
    return "inconnu"


def conduite(code: str) -> str:
    """Ce qu'il faut FAIRE face a ce code. Un code sans conduite a tenir est
    un chiffre nu de plus."""
    return CODES.get(code) or CODES["inconnu"]


# ==================================================================
# 1. LES REGLAGES
# ==================================================================
# Regle absolue : AUCUN champ vide nulle part. Chaque reglage a une valeur
# d'usine defendable, et un « pourquoi » qui dit d'ou elle sort — de la
# bouche du proprietaire, d'un fichier de production, ou d'une contrainte
# physique. Un reglage absent du fichier prend son defaut : jamais un
# plantage, jamais un zero silencieux.
REGLAGES = [
    # -- pilote ------------------------------------------------------
    {"cle": "pilote", "groupe": "pilote", "libelle": "Le parc tourne tout seul",
     "type": "bool", "defaut": False,
     "pourquoi": "On ne demarre jamais un parc en installant une page. C'est le "
                 "seul reglage dont le defaut est volontairement inutile."},
    {"cle": "profil", "groupe": "pilote", "libelle": "Profil de depart",
     "type": "choix", "defaut": "croisiere",
     "choix": ["prudent", "croisiere", "plein", "surveillance", "personnalise"],
     "pourquoi": "Remplit les autres reglages d'un coup. Croisiere = le regime "
                 "demande par le proprietaire."},
    # -- parc --------------------------------------------------------
    {"cle": "objectif_total", "groupe": "parc", "libelle": "Objectif total de comptes",
     "type": "int", "defaut": 50, "min": 1, "max": 5000,
     "pourquoi": "Deja declare par le poste (rig_parc.objectif = 50) et confirme "
                 "par playlists.json:objectif_total. On n'invente pas une valeur "
                 "que le poste connait."},
    {"cle": "repartition", "groupe": "parc", "libelle": "Repartition par categorie",
     "type": "repartition", "defaut": {"beta": 35, "test": 15},
     "pourquoi": "Lu dans playlists.json:objectif — la verite de production. Le "
                 "proprietaire avait evoque 20/30 : l'ecart est AFFICHE, jamais "
                 "arbitre en douce."},
    {"cle": "categorie_defaut", "groupe": "parc",
     "libelle": "Categorie d'un conteneur qui n'en a pas",
     "type": "texte", "defaut": "test", "max": 40,
     "pourquoi": "9 conteneurs sur 33 n'ont aucune categorie. test est le bac a "
                 "sable : une erreur de classement y coute le moins."},
    {"cle": "sans_categorie", "groupe": "parc",
     "libelle": "Que faire d'un conteneur sans categorie",
     "type": "choix", "defaut": "refuser", "choix": ["refuser", "classer"],
     "pourquoi": "Un cycle sans categorie va jusqu'a l'etape des medias puis "
                 "echoue ; /api/rig/jobs le refuse deja par un 400. Autant le "
                 "compter dans Ecarts que creer un compte pour rien."},
    # -- creation ----------------------------------------------------
    {"cle": "creation_active", "groupe": "creation", "libelle": "Creer les comptes manquants",
     "type": "bool", "defaut": True,
     "pourquoi": "33 declares pour 50 vises : le manque est l'etat normal du "
                 "parc, pas une exception."},
    {"cle": "creation_par_jour", "groupe": "creation",
     "libelle": "Creations par jour et par categorie",
     "type": "int", "defaut": 5, "min": 0, "max": 100,
     "pourquoi": "a_venir.json plafonne a 50 identites reservees ; 5 par jour "
                 "comble le manque en 4 jours sans figer la reserve."},
    {"cle": "creation_stop_echecs", "pas_branche": "Les creations sont PLANIFIEES et affichees, mais le pilote n'ouvre pas encore de cycle de creation de son propre chef : il n'y a donc pas d'echec de creation a compter.", "groupe": "creation",
     "libelle": "Arreter la creation apres N echecs d'affilee",
     "type": "int", "defaut": 3, "min": 1, "max": 20,
     "pourquoi": "essais_inscription montre des conteneurs relances "
                 "indefiniment. Trois laisse la place a un alea reseau et coupe "
                 "avant la boucle."},
    # -- publication -------------------------------------------------
    {"cle": "reels_par_passage", "groupe": "publication", "libelle": "Reels par passage",
     "type": "int", "defaut": 6, "min": 1, "max": 30,
     "pourquoi": "Mot du proprietaire. Le poste en tirera 3 (playlists.json > "
                 "publication > Reels = 3) et Remote 2 ne peut pas le changer a "
                 "distance : les tuiles calculent les DEUX chiffres."},
    {"cle": "intervalle_min_h", "groupe": "publication",
     "libelle": "Intervalle minimum entre deux passages d'un meme compte",
     "type": "int", "defaut": 10, "min": 1, "max": 168, "unite": "h",
     "pourquoi": "Mot du proprietaire (« toutes les dix douze heures »)."},
    {"cle": "intervalle_max_h", "groupe": "publication",
     "libelle": "Intervalle maximum entre deux passages d'un meme compte",
     "type": "int", "defaut": 12, "min": 1, "max": 336, "unite": "h",
     "pourquoi": "Mot du proprietaire. Au-dela, le compte est declare en retard "
                 "et remonte en tete de l'ordre de passage."},
    {"cle": "jitter_min", "groupe": "publication", "libelle": "Decalage aleatoire par compte",
     "type": "int", "defaut": 35, "min": 0, "max": 240, "unite": "min",
     "pourquoi": "50 comptes qui publient a la meme minute est une signature "
                 "exploitable. 35 min etale sans sortir d'une fenetre de 3 h."},
    {"cle": "ordre", "groupe": "publication", "libelle": "Ordre de passage",
     "type": "choix", "defaut": "retard",
     "choix": ["retard", "moins_passages", "aleatoire", "registre"],
     "pourquoi": "A 250 comptes le vrai risque est qu'un compte soit muet trois "
                 "jours, pas qu'un autre publie tard."},
    {"cle": "lot_par_tick", "groupe": "publication",
     "libelle": "Travaux inscrits par tour d'horloge",
     "type": "int", "defaut": 3, "min": 1, "max": 10,
     "pourquoi": "rig_jobs.json ne garde que 80 travaux (web_upload.py:44838, "
                 "[:80]) et /api/rig/pull ignore toute heure d'echeance : "
                 "inscrire une journee d'un coup tronquerait la file et "
                 "effacerait l'historique. 3 suffit a saturer 3 machines."},
    {"cle": "tick_s", "groupe": "publication", "libelle": "Periode de l'ordonnanceur",
     "type": "int", "defaut": 60, "min": 15, "max": 900, "unite": "s",
     "pourquoi": "Le pull du poste est a 8 s ; 60 s suffit et laisse le disque "
                 "tranquille."},
    # -- fenetres ----------------------------------------------------
    {"cle": "fuseau", "pas_branche": "Toutes les heures sont calculees dans le fuseau du serveur. Changer ce champ ne deplace aucune fenetre pour l'instant.", "groupe": "fenetres", "libelle": "Fuseau horaire",
     "type": "lecture", "defaut": "Europe/Paris",
     "pourquoi": "Tous les horodatages du poste sont ecrits en heure locale "
                 "(« 21/08 00:53 »). Un second fuseau creerait un decalage "
                 "invisible."},
    {"cle": "fenetres", "groupe": "fenetres", "libelle": "Fenetres horaires de publication",
     "type": "fenetres", "defaut": [["10:00", "13:00"]],
     "pourquoi": "Mot du proprietaire, laisse tel quel EXPRES : c'est ce qui "
                 "permet a la tuile Fenetre de montrer que 3 h n'absorbent "
                 "qu'une fraction des passages, avec trois corrections a un clic."},
    {"cle": "jours", "groupe": "fenetres", "libelle": "Jours actifs",
     "type": "jours", "defaut": [True, True, True, True, True, True, True],
     "pourquoi": "Un parc qui s'arrete le week-end se voit. C'est le premier "
                 "reglage a reduire si Instagram se raidit."},
    {"cle": "maintenance", "groupe": "fenetres", "libelle": "Pause de maintenance quotidienne",
     "type": "plage", "defaut": ["04:00", "04:20"],
     "pourquoi": "Le recensement du parc reel et le redemarrage de WDA doivent "
                 "tomber quand rien ne publie."},
    {"cle": "hors_fenetre", "groupe": "fenetres", "libelle": "Hors fenetre, que faire des retards",
     "type": "choix", "defaut": "reporter", "choix": ["reporter", "abandonner"],
     "pourquoi": "Abandonner creuse un trou invisible. Reporter le rend "
                 "comptable : chaque report est une ligne dans Ecarts."},
    # -- machines ----------------------------------------------------
    {"cle": "machines_strategie", "groupe": "machines",
     "libelle": "Repartition du travail entre machines",
     "type": "choix", "defaut": "moins_chargee",
     "choix": ["moins_chargee", "par_categorie", "manuel"],
     "pourquoi": "Seule strategie qui reste juste quand une machine tombe : par "
                 "categorie, la panne d'un poste arrete une categorie entiere."},
    {"cle": "machines_parallele", "groupe": "machines", "libelle": "Travaux simultanes par machine",
     "note_lecture": "Valeur imposee : un iPhone = un WebDriverAgent. Affiche pour expliquer la contrainte, pas pour etre change.",
     "type": "int", "defaut": 1, "min": 1, "max": 1, "verrou": True,
     "pourquoi": "Un iPhone = un WebDriverAgent. La nuit du 21/08, quatre agents "
                 "empiles se disputaient WDA. Contrainte physique, pas un choix : "
                 "le champ s'explique au clic mais ne se change pas."},
    {"cle": "machines_heures_utiles", "groupe": "machines",
     "libelle": "Heures utiles par machine et par jour",
     "type": "int", "defaut": 20, "min": 1, "max": 24, "unite": "h",
     "pourquoi": "24 h moins 4 h de marge : recharge, maintenance, "
                 "redemarrages. Sert de denominateur a la charge en pourcentage."},
    {"cle": "duree_passage_min", "groupe": "machines",
     "libelle": "Duree estimee d'un passage",
     "type": "int", "defaut": 11, "min": 1, "max": 180, "unite": "min",
     "pourquoi": "Estimation ○ decomposee : 40 s bascule + 60 s import + 6x90 s "
                 "+ 30 s de marge. Des que 20 passages sont journalises, la "
                 "mediane MESUREE la remplace et le libelle le dit."},
    {"cle": "muette_min", "groupe": "machines", "libelle": "Machine declaree muette apres",
     "type": "int", "defaut": 5, "min": 1, "max": 180, "unite": "min",
     "pourquoi": "Le battement est a 8 s : 5 min = 37 pulls manques. Ce n'est "
                 "plus un hoquet reseau."},
    {"cle": "reattribuer_min", "groupe": "machines",
     "libelle": "Reattribuer les travaux d'une machine muette apres",
     "type": "int", "defaut": 20, "min": 1, "max": 720, "unite": "min",
     "pourquoi": "Superieur au timeout de 900 s du poste : on ne reattribue "
                 "donc jamais un travail encore vivant, ce qui produirait deux "
                 "executions du meme geste."},
    # -- garde-fous --------------------------------------------------
    {"cle": "seuil_wda_chutes", "groupe": "gardefous",
     "libelle": "Chutes de WebDriverAgent tolerees par heure",
     "type": "int", "defaut": 3, "min": 1, "max": 100,
     "pourquoi": "La nuit du 21/08, WDA tombait toutes les 20 s pendant une "
                 "purge. Trois chutes en une heure ne sont plus un alea."},
    {"cle": "seuil_ecart_registre", "groupe": "gardefous",
     "libelle": "Ecart tolere entre le registre et le telephone",
     "type": "int", "defaut": 50, "min": 1, "max": 100, "unite": "%",
     "pourquoi": "L'ecart reel est de 97 % (33 declares, 1 releve). A 50 % on "
                 "attrape la situation actuelle sans bloquer un parc qui bouge ; "
                 "ambre des 10 %."},
    {"cle": "age_inventaire_h", "groupe": "gardefous",
     "libelle": "Age maximal du dernier recensement reel",
     "type": "int", "defaut": 24, "min": 1, "max": 720, "unite": "h",
     "pourquoi": "Ambre a 24 h, rouge au double. Personne n'a jamais confronte "
                 "le registre a la realite : c'est ce qui a produit « 87 "
                 "conteneurs pour 33 reels »."},
    {"cle": "echecs_quarantaine", "groupe": "gardefous",
     "libelle": "Quarantaine d'un compte apres N echecs consecutifs",
     "type": "int", "defaut": 3, "min": 1, "max": 50,
     "pourquoi": "Empeche les quarante relances d'un conteneur mort, tout en "
                 "laissant passer un alea reseau isole."},
    {"cle": "sortie_quarantaine", "groupe": "gardefous", "libelle": "Sortie de quarantaine",
     "type": "choix", "defaut": "manuel", "choix": ["manuel", "auto24h"],
     "pourquoi": "Un compte bloque par Instagram ne se debloque pas tout seul : "
                 "reessayer automatiquement ne fait que confirmer le blocage."},
    {"cle": "job_fige_min", "groupe": "gardefous", "libelle": "Travail « pris » sans nouvelle depuis",
     "type": "int", "defaut": 15, "min": 1, "max": 240, "unite": "min",
     "pourquoi": "Exactement le timeout de lancer() cote poste (900 s). Au-dela, "
                 "l'agent est mort : le travail est degrippe en echec "
                 "agent_disparu."},
    {"cle": "succes_court_min", "groupe": "gardefous", "libelle": "Cycle anormalement court",
     "type": "int", "defaut": 4, "min": 1, "max": 120, "unite": "min",
     "pourquoi": "Un passage reel mesure a dure 8 min 54. Plus court, c'est un "
                 "ecran « confirm that you're human » valide comme reussite."},
    {"cle": "pause_si_echecs", "groupe": "gardefous", "libelle": "Arret d'urgence : nombre d'echecs",
     "type": "int", "defaut": 5, "min": 1, "max": 100,
     "pourquoi": "Une panne WDA en produit cinq en dix minutes ; un alea isole, "
                 "non."},
    {"cle": "pause_si_minutes", "groupe": "gardefous", "libelle": "Arret d'urgence : fenetre",
     "type": "int", "defaut": 30, "min": 1, "max": 1440, "unite": "min",
     "pourquoi": "La nuit du 21/08, une cause unique a produit 100 % d'echecs "
                 "pendant des heures sans que rien ne s'arrete."},
    {"cle": "age_donnees_min", "groupe": "gardefous",
     "libelle": "Age maximal des donnees pour demarrer",
     "type": "int", "defaut": 10, "min": 1, "max": 240, "unite": "min",
     "pourquoi": "Au-dela, le pre-vol passe en ambre : on demarre sur des "
                 "chiffres perimes, mais en le sachant."},
    # -- medias ------------------------------------------------------
    {"cle": "medias_source", "pas_branche": 'Le stock de medias vit dans le Vault PRO du POSTE ; le site ne le lit pas (rig_parc.json ne declare que des categories tronquees). Ce choix ne peut pas encore etre applique ici.', "groupe": "medias", "libelle": "Source des medias",
     "type": "choix", "defaut": "vault_poste", "choix": ["vault_poste", "biblio_site"],
     "pourquoi": "C'est la seule reserve que la chaine de publication consomme "
                 "reellement aujourd'hui (playlist.py -> Vault PRO -> tunnel)."},
    {"cle": "repos_video_j", "pas_branche": "Demande de savoir quelle video est partie sur quel compte : le poste ne le transmet pas. Le compteur de repetition (tuile Stock) est la seule mesure possible aujourd'hui.", "groupe": "medias",
     "libelle": "Ne pas republier une video sur le meme compte avant",
     "type": "int", "defaut": 1, "min": 0, "max": 60, "unite": "j",
     "pourquoi": "Plus court n'a pas de sens ; plus long est inapplicable avec "
                 "15 reels pour 300 publications."},
    {"cle": "si_stock_court", "pas_branche": "Meme raison que le repos : sans l'historique des medias par compte, le site ne peut ni constater le manque, ni annuler le passage.", "groupe": "medias",
     "libelle": "Si le stock ne permet pas de respecter le repos",
     "type": "choix", "defaut": "publier", "choix": ["publier", "annuler"],
     "pourquoi": "Le proprietaire a dit que republier les memes videos ne le "
                 "derange pas. Le compteur rend la repetition visible sans "
                 "l'empecher — c'est exactement ce qu'il a demande."},
    {"cle": "tirage", "pas_branche": "L'ordre de tirage est decide par le poste (playlist.py) : le site ne choisit pas les medias.", "groupe": "medias", "libelle": "Ordre de tirage des medias",
     "type": "choix", "defaut": "moins_recent", "choix": ["moins_recent", "aleatoire"],
     "pourquoi": "Avec 15 reels pour 300 publications, le tirage au hasard "
                 "reposte la meme video deux fois de suite sur le meme compte."},
    {"cle": "alerte_stock_j", "pas_branche": "Demande un stock de reels chiffre ; le poste n'en declare aucun (reels_declares reste ○ non declare).", "groupe": "medias",
     "libelle": "Alerter sous N jours de stock sans repetition",
     "type": "int", "defaut": 2, "min": 0, "max": 60, "unite": "j",
     "pourquoi": "Laisse le temps de recharger le Vault avant que la repetition "
                 "ne devienne mecanique."},
    # -- journal -----------------------------------------------------
    {"cle": "retention_j", "groupe": "journal", "libelle": "Conserver le journal",
     "type": "int", "defaut": 90, "min": 1, "max": 3650, "unite": "j",
     "pourquoi": "Une panne survenue a 3 h du matin doit rester lisible des "
                 "semaines plus tard. Aujourd'hui l'historique fait 80 travaux, "
                 "soit environ 3 h."},
    {"cle": "retention_lignes", "groupe": "journal", "libelle": "Plafond de lignes du journal",
     "type": "int", "defaut": 200000, "min": 1000, "max": 5000000,
     "pourquoi": "Rotation en parc_journal.1.jsonl. Le nombre de lignes purgees "
                 "est lui-meme journalise : une purge silencieuse serait un "
                 "ecart de plus."},
    {"cle": "niveau", "groupe": "journal", "libelle": "Niveau du journal",
     "type": "choix", "defaut": "tout", "choix": ["tout", "evenements", "echecs"],
     "pourquoi": "Sans les DECISIONS de l'ordonnanceur, on ne saura jamais "
                 "POURQUOI un tour n'est pas parti. C'est le trou actuel."},
    {"cle": "canal_alerte", "groupe": "journal", "libelle": "Ou prevenir",
     "type": "choix", "defaut": "ici", "choix": ["ici", "ici_discord"],
     "pourquoi": "Un defaut sans champ a remplir. Choisir Discord revele le "
                 "champ webhook — pas de fausse promesse tant que rien n'est "
                 "cable."},
    {"cle": "canal_webhook", "groupe": "journal", "libelle": "Webhook Discord",
     "type": "texte", "defaut": "", "max": 300,
     "pourquoi": "Reste vide tant que « ici + Discord » n'est pas choisi. Un "
                 "champ vide affiche est un champ a remplir : celui-ci ne "
                 "s'affiche que quand il sert."},
    # -- affichage ---------------------------------------------------
    {"cle": "rafraichissement_actif_s", "groupe": "affichage",
     "libelle": "Rafraichissement quand le pilote tourne",
     "type": "int", "defaut": 5, "min": 2, "max": 120, "unite": "s",
     "pourquoi": "Le pull du poste est a 8 s : sonder plus vite n'apporte rien."},
    {"cle": "rafraichissement_repos_s", "groupe": "affichage",
     "libelle": "Rafraichissement au repos",
     "type": "int", "defaut": 20, "min": 5, "max": 600, "unite": "s",
     "pourquoi": "Au repos rien ne bouge ; le sondage masque est a 0, "
                 "obligatoire — un sondage qui continue en arriere-plan a deja "
                 "coute cher a ce projet."},
    {"cle": "vue_parc", "groupe": "affichage", "libelle": "Vue du parc par defaut",
     "type": "choix", "defaut": "agregee", "choix": ["agregee", "detaillee"],
     "pourquoi": "20 lignes a 5 machines et 4 categories, quel que soit le "
                 "nombre de comptes. 250 lignes a l'ouverture ne se lisent pas."},
    {"cle": "lignes_parc", "groupe": "affichage", "libelle": "Lignes par page du parc",
     "type": "int", "defaut": 50, "min": 10, "max": 500,
     "pourquoi": "Au-dela le navigateur rame et personne ne lit. Le pied annonce "
                 "toujours le total et le nombre de lignes masquees."},
    {"cle": "lignes_journal", "groupe": "affichage", "libelle": "Lignes par page du journal",
     "type": "int", "defaut": 100, "min": 10, "max": 1000,
     "pourquoi": "Meme raison. Aucun slice() muet nulle part."},
]

_PAR_CLE = {r["cle"]: r for r in REGLAGES}

# Les profils ne changent QUE les cles qu'ils nomment : le reste garde sa
# valeur d'usine. Modifier un champ ensuite bascule sur « personnalise » —
# on ne laisse jamais croire qu'on tourne sur Croisiere alors que non.
PROFILS = {
    "prudent": {
        "titre": "Prudent",
        "quand": "apres une panne, pour verifier que ca repart",
        "valeurs": {"lot_par_tick": 1, "reels_par_passage": 3,
                    "intervalle_min_h": 12, "intervalle_max_h": 24,
                    "creation_par_jour": 1, "pause_si_echecs": 3,
                    "seuil_wda_chutes": 2, "si_stock_court": "annuler"},
    },
    "croisiere": {
        "titre": "Croisiere",
        "quand": "le regime demande par le proprietaire — defaut",
        "valeurs": {},          # = les valeurs d'usine, par construction
    },
    "plein": {
        "titre": "Plein regime",
        "quand": "depasse le debit mesure d'une machine — a reserver a 3 machines",
        "valeurs": {"lot_par_tick": 6, "reels_par_passage": 6,
                    "intervalle_min_h": 8, "intervalle_max_h": 10,
                    "creation_par_jour": 10, "jitter_min": 20,
                    "fenetres": [["08:00", "23:59"]]},
    },
    "surveillance": {
        "titre": "Surveillance seule",
        "quand": "le parc ne publie pas mais continue d'etre surveille",
        "valeurs": {"pilote": False, "creation_active": False,
                    "lot_par_tick": 1},
    },
}


def defauts() -> dict:
    """Les valeurs d'usine, dans un dict {cle: valeur}.

    POURQUOI une fonction et pas une constante : les valeurs de type liste
    ou dict (fenetres, jours, repartition) doivent etre COPIEES a chaque
    appel. Une constante partagee se serait fait modifier en place par le
    premier appelant, et « revenir aux valeurs d'usine » aurait rendu la
    derniere saisie de l'utilisateur.
    """
    out = {}
    for r in REGLAGES:
        d = r["defaut"]
        out[r["cle"]] = json.loads(json.dumps(d)) if isinstance(d, (list, dict)) else d
    return out


def _valider_un(regle: dict, valeur, contexte: dict):
    """Valide UN reglage. Rend (valeur_retenue, motif_de_correction|None).

    La correction est RENVOYEE au client en clair au lieu d'etre appliquee
    en douce : « j'ai ecrit 40, le site en a garde 30 » doit se voir, sinon
    on croit piloter avec une valeur qu'on n'a pas.
    """
    t = regle.get("type")
    if t == "lecture":
        return regle["defaut"], ("valeur imposee : %s" % regle["defaut"]
                                 if valeur not in (None, regle["defaut"]) else None)
    if t == "bool":
        return bool(valeur), None
    if t == "int":
        try:
            v = int(float(valeur))
        except (TypeError, ValueError):
            return regle["defaut"], "valeur illisible — valeur d'usine reprise"
        if regle.get("verrou"):
            return regle["defaut"], ("cadenas : %s" % regle["pourquoi"].split(".")[0]
                                     if v != regle["defaut"] else None)
        lo, hi = regle.get("min", 0), regle.get("max", 10 ** 9)
        if v < lo:
            return lo, "en dessous du minimum (%s)" % lo
        if v > hi:
            return hi, "au dessus du maximum (%s)" % hi
        return v, None
    if t == "choix":
        v = str(valeur or "").strip()
        if v not in (regle.get("choix") or []):
            return regle["defaut"], "choix inconnu « %s » — valeur d'usine reprise" % v[:30]
        return v, None
    if t == "texte":
        v = str(valeur or "").strip()
        hi = int(regle.get("max") or 200)
        if len(v) > hi:
            return v[:hi], "texte coupe a %d caracteres" % hi
        return v, None
    if t == "jours":
        if not isinstance(valeur, (list, tuple)) or len(valeur) != 7:
            return list(regle["defaut"]), "il faut exactement 7 jours — valeur d'usine reprise"
        v = [bool(x) for x in valeur]
        if not any(v):
            return list(regle["defaut"]), "aucun jour actif : le parc ne tournerait jamais"
        return v, None
    if t == "plage":
        try:
            a, b = valeur[0], valeur[1]
        except Exception:
            return list(regle["defaut"]), "plage illisible — valeur d'usine reprise"
        da, db = _hhmm(a, -1), _hhmm(b, -1)
        if da < 0 or db < 0:
            return list(regle["defaut"]), "heure illisible — valeur d'usine reprise"
        return [_mmhh(da), _mmhh(db)], None
    if t == "fenetres":
        if not isinstance(valeur, (list, tuple)) or not valeur:
            return json.loads(json.dumps(regle["defaut"])), \
                "aucune fenetre : rien ne partirait jamais — valeur d'usine reprise"
        propres, ecartees = [], 0
        for f in valeur[:12]:
            try:
                da, db = _hhmm(f[0], -1), _hhmm(f[1], -1)
            except Exception:
                ecartees += 1
                continue
            if da < 0 or db < 0 or db <= da:
                ecartees += 1
                continue
            propres.append([_mmhh(da), _mmhh(db)])
        if not propres:
            return json.loads(json.dumps(regle["defaut"])), \
                "aucune fenetre valide (%d ecartee(s)) — valeur d'usine reprise" % ecartees
        propres.sort(key=lambda f: _hhmm(f[0]))
        # Compter et remonter : une fenetre ecartee sans trace, c'est une
        # heure de publication qui disparait sans que personne ne le sache.
        return propres, ("%d fenetre(s) ecartee(s) : fin avant debut, ou heure "
                         "illisible" % ecartees) if ecartees else None
    if t == "repartition":
        if not isinstance(valeur, dict) or not valeur:
            return json.loads(json.dumps(regle["defaut"])), \
                "repartition vide — valeur d'usine reprise"
        propres = {}
        for k, v in list(valeur.items())[:20]:
            nom = str(k).strip()[:40]
            if not nom:
                continue
            try:
                propres[nom] = max(0, int(float(v)))
            except (TypeError, ValueError):
                propres[nom] = 0
        if not propres:
            return json.loads(json.dumps(regle["defaut"])), \
                "aucune categorie lisible — valeur d'usine reprise"
        total = sum(propres.values())
        cible = int(contexte.get("objectif_total") or total or 0)
        if cible and total != cible:
            # On NE recale PAS en douce : on dit l'ecart et on laisse la
            # somme telle quelle. Corriger silencieusement une repartition
            # ferait mentir la tuile de charge.
            return propres, ("la somme fait %d pour un objectif de %d — l'ecart "
                             "est affiche, rien n'a ete recale" % (total, cible))
        return propres, None
    return valeur, "type de reglage inconnu (%s) — valeur gardee telle quelle" % t


def valider_regles(brut: dict) -> tuple:
    """Valide un jeu de reglages COMPLET, champ par champ, cote serveur.

    Rend (regles_propres, corrections, inconnues) :
      * corrections = [{champ, demande, retenu, motif}] — a AFFICHER, pas a
        avaler : le client doit voir ce que le serveur a change ;
      * inconnues = les cles du fichier qui ne correspondent a aucun reglage
        (une version anterieure, un copier-coller). Elles sont comptees et
        remontees, jamais jetees en silence.
    """
    brut = brut if isinstance(brut, dict) else {}
    out = defauts()
    corrections = []
    # L'objectif d'abord : la repartition a besoin de lui comme contexte.
    ctx = {}
    if "objectif_total" in brut:
        v, motif = _valider_un(_PAR_CLE["objectif_total"], brut.get("objectif_total"), {})
        out["objectif_total"] = v
        if motif:
            corrections.append({"champ": "objectif_total",
                                "demande": brut.get("objectif_total"),
                                "retenu": v, "motif": motif})
    ctx["objectif_total"] = out["objectif_total"]
    for regle in REGLAGES:
        cle = regle["cle"]
        if cle == "objectif_total" or cle not in brut:
            continue            # absent du fichier = valeur d'usine, sans bruit
        v, motif = _valider_un(regle, brut.get(cle), ctx)
        out[cle] = v
        if motif:
            corrections.append({"champ": cle, "demande": brut.get(cle),
                                "retenu": v, "motif": motif})
    inconnues = [k for k in brut.keys() if k not in _PAR_CLE and not k.startswith("_")]
    # Coherence croisee : un intervalle max inferieur au min rend l'ordre de
    # passage absurde (tout le monde serait « en retard » en permanence).
    if out["intervalle_max_h"] < out["intervalle_min_h"]:
        corrections.append({"champ": "intervalle_max_h",
                            "demande": out["intervalle_max_h"],
                            "retenu": out["intervalle_min_h"],
                            "motif": "le maximum ne peut pas etre sous le minimum"})
        out["intervalle_max_h"] = out["intervalle_min_h"]
    if out["reattribuer_min"] <= out["job_fige_min"]:
        corrections.append({"champ": "reattribuer_min",
                            "demande": out["reattribuer_min"],
                            "retenu": out["job_fige_min"] + 5,
                            "motif": "reattribuer avant le timeout du poste "
                                     "ferait jouer le meme geste deux fois"})
        out["reattribuer_min"] = out["job_fige_min"] + 5
    return out, corrections, inconnues


def charger_regles() -> dict:
    """Les reglages effectifs. JAMAIS d'exception, JAMAIS de champ manquant.

    Un fichier absent, tronque ou ecrit par une version anterieure rend les
    valeurs d'usine : la page doit s'afficher meme quand les donnees sont
    illisibles, sinon une faute de frappe dans un JSON eteint le poste de
    pilotage au moment ou on en a le plus besoin.
    """
    brut = safe_json.load(REGLES_FILE, default=None)
    if not isinstance(brut, dict):
        return defauts()
    propres, _corr, _inc = valider_regles(brut)
    return propres


def regles_meta() -> list:
    """La description des reglages pour l'interface : libelle, type, bornes,
    valeur d'usine et POURQUOI. Le client n'a ainsi aucune valeur en dur —
    ajouter un reglage ici le fait apparaitre dans le tiroir tout seul."""
    out = []
    for r in REGLAGES:
        d = dict(r)
        d["defaut"] = defauts()[r["cle"]]
        out.append(d)
    return out


def enregistrer_regles(brut: dict, par: str = "?") -> dict:
    """Ecrit les reglages et journalise CHAQUE champ modifie, avec son nom de
    session. Sans cette trace, « pourquoi le parc tourne-t-il a 6 par lot ce
    matin ? » n'a pas de reponse."""
    avant = charger_regles()
    propres, corrections, inconnues = valider_regles(brut)
    # Un champ change a la main sort du profil : on ne laisse pas croire
    # qu'on tourne sur Croisiere alors qu'on n'y est plus.
    diffs = [k for k in propres if propres.get(k) != avant.get(k) and k != "profil"]
    if diffs and propres.get("profil") == avant.get("profil"):
        attendu = dict(defauts())
        attendu.update(PROFILS.get(propres.get("profil"), {}).get("valeurs") or {})
        if any(propres.get(k) != attendu.get(k) for k in diffs):
            propres["profil"] = "personnalise"
    with _LOCK_REGLES:
        REGLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write(REGLES_FILE, propres, indent=1)
    for k in diffs:
        journal("reglage_change", objet="plan", code=k, par=par,
                detail="%s -> %s" % (_court(avant.get(k)), _court(propres.get(k))))
    if inconnues:
        journal("reglage_change", objet="plan", code="cles_inconnues", par=par,
                detail="ignorees : " + ", ".join(sorted(inconnues))[:200])
    return {"ok": True, "regles": propres, "corriges": corrections,
            "inconnues": inconnues, "modifies": diffs}


def appliquer_profil(nom: str, par: str = "?") -> dict:
    """Pose un profil : il pre-remplit d'un coup tous les reglages qu'il
    nomme, le reste revenant aux valeurs d'usine. C'est la reponse a « tu me
    pre-configures tout ce qui est possible de pre-configurer »."""
    nom = str(nom or "").strip().lower()
    if nom not in PROFILS:
        return {"ok": False, "error": "profil inconnu : %s" % nom[:40]}
    voulu = defauts()
    voulu.update(PROFILS[nom]["valeurs"])
    voulu["profil"] = nom
    # Le pilote ne se rallume jamais tout seul en changeant de profil : c'est
    # une commande, pas un reglage.
    voulu["pilote"] = bool(charger_regles().get("pilote")) and nom != "surveillance"
    res = enregistrer_regles(voulu, par=par)
    journal("reglage_change", objet="plan", code="profil", par=par,
            detail="profil %s applique" % nom)
    return res


def _court(v) -> str:
    """Une valeur de reglage rendue lisible dans une ligne de journal."""
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
    return s if len(s) <= 80 else s[:77] + "..."


# ==================================================================
# 2. LES SOURCES — ce que le poste pousse. LECTURE SEULE.
# ==================================================================
# Ce module ne reecrit JAMAIS un fichier rig_* : ils appartiennent aux
# routes /api/rig/* de web_upload, qu'un operateur utilise en ce moment.


def lire_parc() -> dict:
    """Le parc declare par l'agent, avec l'AGE de la declaration.

    L'age compte autant que le chiffre : a 5 machines, « 33 conteneurs »
    releve il y a 40 minutes n'est pas la meme information que « 33 »
    releve il y a 8 secondes.
    """
    d = safe_json.load(RIG_PARC, default={}) or {}
    if not isinstance(d, dict):
        d = {}
    return {
        "conteneurs": d.get("conteneurs") or [],
        "categories": d.get("categories") or [],
        "objectif": int(d.get("objectif") or 0),
        "wda": bool(d.get("wda")),
        "ts": int(d.get("ts") or 0),
        "age_s": _age(d.get("ts")),
        # Le poste plafonne sa declaration a 200 conteneurs (agent_rig.py) et
        # la route en refuse autant : atteindre le plafond doit se voir.
        "plafond_atteint": len(d.get("conteneurs") or []) >= 200,
    }


def lire_jobs() -> dict:
    """La file de travaux et le battement du poste."""
    d = safe_json.load(RIG_JOBS, default={}) or {}
    if not isinstance(d, dict):
        d = {}
    jobs = d.get("jobs") or []
    return {
        "jobs": jobs if isinstance(jobs, list) else [],
        "battement": int(d.get("battement") or 0),
        "battement_age_s": _age(d.get("battement")),
        "etat_poste": d.get("etat_poste") or {},
        # 80 gardes cote ecriture, 40 rendus par le GET : le jour ou la file
        # est pleine, l'historique de la journee est deja perdu.
        "plafond_atteint": len(jobs if isinstance(jobs, list) else []) >= 80,
    }


def lire_actions() -> dict:
    """La palette d'actions du moteur, declaree au demarrage de l'agent."""
    d = safe_json.load(RIG_ACTIONS, default={}) or {}
    a = d.get("actions") or []
    return {"actions": a, "n": len(a), "ts": int(d.get("ts") or 0),
            "age_s": _age(d.get("ts"))}


def lire_scenarios() -> dict:
    """Le catalogue de scenarios, declare au demarrage de l'agent."""
    d = safe_json.load(RIG_SCENARIOS, default={}) or {}
    s = d.get("scenarios") or []
    return {"scenarios": s, "n": len(s), "ts": int(d.get("ts") or 0),
            "age_s": _age(d.get("ts"))}


def pilotage_ts() -> float:
    """Quand quelqu'un a regarde l'ecran pour la derniere fois. C'est la
    cause DIRECTE de la chute de WDA du 21/08 : capturer interroge le
    telephone pendant qu'une purge tourne."""
    d = safe_json.load(RIG_PILOTAGE, default={}) or {}
    try:
        return float(d.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def lire_inventaire() -> dict:
    """Le dernier recensement REEL du telephone.

    Il n'existe aujourd'hui que sur le poste (inventaire_telephone.json,
    ecrit a la main : aucune occurrence de `releve_le` dans le code) et
    n'est pas pousse. Tant qu'il n'arrive pas ici, le controle
    registre<->realite reste ○ non declare — surtout pas vert.
    """
    d = safe_json.load(INVENTAIRE_FILE, default={}) or {}
    if not isinstance(d, dict):
        d = {}
    noms = [str(x) for x in (d.get("conteneurs") or []) if x]
    return {"present": bool(d), "conteneurs": noms,
            "nombre": int(d.get("nombre") or len(noms)),
            "ts": int(d.get("ts") or 0), "age_s": _age(d.get("ts")),
            "releve_le": str(d.get("releve_le") or ""),
            "note": str(d.get("note") or "")[:300]}


_RE_CAT_NOM = re.compile(r"'nom'\s*:\s*'([^']{1,40})'")
_RE_CAT_MED = re.compile(r"'medias'\s*:\s*(\d{1,6})")


def stock_categories(parc: dict) -> dict:
    """Le stock de medias par categorie — ET l'aveu qu'il arrive en bouillie.

    POURQUOI ce code bizarre : `declarer_parc()` fait
    `[str(x) for x in categories]` alors que chaque x est un DICT, puis la
    route tronque a 40 caracteres. Le fichier contient donc aujourd'hui
    ["{'nom': 'beta', 'medias': 37, 'dossiers'", ...]. On recupere ce qui
    est recuperable (nom, nombre de medias) et on DIT que c'est tronque,
    avec le contenu brut : jamais un chiffre invente, jamais un silence.
    Le correctif est cote poste, agent_rig.py:364.
    """
    brut = parc.get("categories") or []
    cats, illisibles = [], 0
    for x in brut:
        s = str(x)
        if s.startswith("{"):
            nom = _RE_CAT_NOM.search(s)
            med = _RE_CAT_MED.search(s)
            if nom:
                cats.append({"nom": nom.group(1),
                             "medias": int(med.group(1)) if med else None,
                             "tronque": True, "brut": s})
            else:
                illisibles += 1
        elif s.strip():
            # Format sain (le jour ou le poste sera corrige) : un simple nom,
            # sans compte de medias — donc ○ non declare, pas zero.
            cats.append({"nom": s.strip()[:40], "medias": None,
                         "tronque": False, "brut": s})
        else:
            illisibles += 1
    tronque = any(c.get("tronque") for c in cats)
    # Un dict tronque a 40 caracteres N'EST PAS une mesure lisible, meme
    # quand la regex y peche un « 'medias': 37 ». Sans le `not tronque`,
    # `lisible` passait a True sur les vraies donnees : le pre-vol rendait
    # VERT « beta 37, test 36 » et la tuile annoncait « chaque video rejouee
    # 8x par jour / 73 medias declares », alors que le stock reel mesure a
    # la main le 21/08 est de 15 reels (facteur 5 d'ecart, reel : 40x). La
    # branche « stock illisible » — la seule qui porte cette mesure a la
    # main et le correctif agent_rig.py:364 — etait donc inatteignable.
    # C'est le mecanisme exact de « 87 conteneurs pour 33 reels » : un
    # chiffre derive d'un champ casse, presente comme une mesure.
    lisible = (bool(cats) and not tronque
               and all(c.get("medias") is not None for c in cats))
    return {
        "categories": cats,
        "illisibles": illisibles,
        "lisible": lisible,
        "tronque": tronque,
        "provenance": DERIVE if cats else NON_DECLARE,
        "note": ("Le poste serialise des dict tronques a 40 caracteres "
                 "(agent_rig.py:364) : le nombre de medias est extrait du "
                 "texte, la liste des sous-dossiers est perdue."
                 if tronque else
                 "Le poste ne declare aucun stock par categorie."),
        # Le vrai stock de reels est dans le Vault PRO du poste, que le site
        # ne peut pas lire : 15 reels mesures a la main le 21/08.
        "reels_declares": None,
    }


# ==================================================================
# 3. L'ETAT DU PILOTE — ce que Remote 2 decide, et lui seul.
# ==================================================================
def _etat_vide() -> dict:
    return {"pilote_depuis": 0, "pause_jusqu_a": 0, "arret_urgence": {},
            "quarantaine": {}, "machines": {}, "dernier_tick": 0,
            "prevol_dernier": {}}


def charger_etat() -> dict:
    """L'etat du pilote : depuis quand il tourne, ce qui est en quarantaine,
    quelles machines sont suspendues. Fail-soft comme partout."""
    d = safe_json.load(ETAT_FILE, default=None)
    if not isinstance(d, dict):
        return _etat_vide()
    base = _etat_vide()
    for k, v in d.items():
        base[k] = v
    return base


def enregistrer_etat(d: dict) -> None:
    with _LOCK_ETAT:
        ETAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write(ETAT_FILE, d, indent=1)


def en_pause(etat: dict = None) -> bool:
    """« Je pars, ne fais rien ce soir » — vrai tant que l'echeance n'est
    pas passee.

    /parc/pause ecrivait `pause_jusqu_a` que PERSONNE ne relisait : tant
    qu'aucune horloge n'existait, le bouton de pause ne pouvait rien mettre
    en pause. C'est l'horloge qui lui donne son sens.
    """
    etat = etat if isinstance(etat, dict) else charger_etat()
    try:
        return float(etat.get("pause_jusqu_a") or 0) > maintenant()
    except (TypeError, ValueError):
        return False


# ==================================================================
# 4. LE JOURNAL — append-only, borne, filtrable
# ==================================================================
# Une ligne JSON par evenement, en mode 'a' sous verrou : jamais reecrit.
# POURQUOI un fichier a part et pas une cle de plus dans un JSON : un JSON
# relu-reecrit a chaque evenement perd une ligne des que deux threads
# ecrivent en meme temps, et il grossit sans fin.
OBJETS = ("job", "parc", "poste", "incident", "plan", "verrou", "media")
EVENEMENTS = (
    "inscrit", "pris", "avance", "fini", "echec", "annule", "degrippe",
    "publie", "parc_apparu", "parc_disparu", "parc_statut", "parc_passage",
    "wda_chute", "wda_retour", "poste_muet", "poste_retour", "verrou_pris",
    "verrou_perdu", "incident_ouvert", "incident_acquitte", "pilote_on",
    "pilote_off", "arret_urgence", "prevol", "prevol_force",
    "reglage_change", "rotation", "plan_decision", "plan_refus",
    "hors_plan", "agents_empiles", "inventaire",
)

_JOURNAL_N = None           # nombre de lignes connu, None = pas encore compte


def _compter_lignes(p: Path) -> int:
    """Compte les lignes sans charger le fichier en memoire : a 200 000
    lignes, un read_text() coute plus cher que tout le reste de la page."""
    n = 0
    try:
        with open(p, "rb") as f:
            while True:
                bloc = f.read(1 << 20)
                if not bloc:
                    break
                n += bloc.count(b"\n")
    except FileNotFoundError:
        return 0
    except Exception:
        return 0
    return n


def _rotation_si_besoin(plafond: int) -> None:
    """Bascule parc_journal.jsonl -> parc_journal.1.jsonl quand le plafond
    est atteint. Le nombre de lignes REELLEMENT perdues (l'ancien fichier de
    rotation) est journalise : une purge silencieuse serait un ecart de plus.
    """
    global _JOURNAL_N
    if _JOURNAL_N is None or _JOURNAL_N < max(1000, int(plafond)):
        return
    perdues = _compter_lignes(JOURNAL_ROT)
    try:
        if JOURNAL_ROT.exists():
            JOURNAL_ROT.unlink()
        JOURNAL_FILE.replace(JOURNAL_ROT)
    except Exception as e:
        print("[parc] rotation du journal impossible : %s" % e, flush=True)
        return
    _JOURNAL_N = 0
    journal("rotation", objet="plan", code="rotation",
            detail="plafond %d atteint — %d ligne(s) definitivement purgees "
                   "(ancienne rotation)" % (plafond, perdues))


def purge_anciennete(jours: int) -> int:
    """Retire du journal les lignes plus vieilles que `jours`. Rend le compte.

    `retention_j` (« Conserver le journal : 90 j ») etait declare, explique,
    et lu par PERSONNE : seul `retention_lignes` agissait. Un parc peu actif
    n'atteint jamais les 200 000 lignes, donc le journal ne se purgeait
    jamais par anciennete, quoi qu'on saisisse.

    La purge est elle-meme journalisee : une purge silencieuse serait
    exactement l'ecartement muet que ce module refuse partout ailleurs.
    """
    global _JOURNAL_N
    jours = max(1, int(jours or 90))
    limite = maintenant() - jours * 86400
    if not JOURNAL_FILE.exists():
        return 0
    with _LOCK_JOURNAL:
        gardees, retirees = [], 0
        try:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                for ligne in f:
                    if not ligne.strip():
                        continue
                    try:
                        if float(json.loads(ligne).get("ts") or 0) < limite:
                            retirees += 1
                            continue
                    except Exception:
                        # Une ligne illisible est GARDEE : on ne supprime pas
                        # ce qu'on n'a pas su lire.
                        pass
                    gardees.append(ligne if ligne.endswith("\n") else ligne + "\n")
        except Exception as e:
            print("[parc] purge du journal impossible : %s" % e, flush=True)
            return 0
        if not retirees:
            return 0
        if not safe_json.write_text(JOURNAL_FILE, "".join(gardees), backup=False):
            return 0
        _JOURNAL_N = len(gardees)
    journal("rotation", objet="plan", code="retention",
            detail="%d ligne(s) de plus de %d jours purgees" % (retirees, jours))
    return retirees


# ---------------------------------------------------------------- alertes
# « Une panne a 3 h du matin est invisible jusqu'au lendemain soir. » Le
# reglage canal_alerte proposait « ici + Discord » et revelait un champ
# webhook, alors que le module ne contenait AUCUN client HTTP : on collait
# son webhook, on choisissait Discord, et on ne recevait jamais rien.
#
# Un seul hote autorise : c'est un champ « Webhook Discord », et une URL
# arbitraire postee par le serveur serait un SSRF offert.
_HOTES_WEBHOOK = ("discord.com", "discordapp.com", "ptb.discord.com",
                  "canary.discord.com")
# Une alerte par cle et par heure : l'horloge tourne toutes les 60 s, et un
# parc en panne enverrait 60 messages par heure sans ce frein.
_ALERTES_VUES: dict = {}
_LOCK_ALERTE = threading.Lock()


def _webhook_valide(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        u = urlparse(str(url or "").strip())
        return (u.scheme == "https" and u.hostname in _HOTES_WEBHOOK
                and "/api/webhooks/" in (u.path or ""))
    except Exception:
        return False


def alerter(cle: str, titre: str, texte: str, regles: dict = None) -> dict:
    """Previent le proprietaire hors de l'ecran. Rend ce qui a ete fait.

    Toujours journalise (canal « ici »). En plus, si canal_alerte vaut
    « ici_discord » ET que le webhook est un vrai webhook Discord, un
    message part. L'echec d'envoi est journalise lui aussi : une alerte
    perdue en silence serait pire que pas d'alerte.
    """
    regles = regles if isinstance(regles, dict) else charger_regles()
    journal("incident_ouvert", objet="incident", code=str(cle)[:40],
            par="horloge", detail=("%s — %s" % (titre, texte))[:300])
    if str(regles.get("canal_alerte") or "ici") != "ici_discord":
        return {"envoye": False, "raison": "canal « ici » seulement"}
    url = str(regles.get("canal_webhook") or "").strip()
    if not url:
        return {"envoye": False, "raison": "aucun webhook saisi"}
    if not _webhook_valide(url):
        journal("incident_ouvert", objet="incident", code="webhook_invalide",
                par="horloge",
                detail="le webhook saisi n'est pas une URL de webhook Discord "
                       "en https : rien n'a ete envoye")
        return {"envoye": False, "raison": "webhook invalide"}
    with _LOCK_ALERTE:
        dernier = _ALERTES_VUES.get(cle) or 0
        if maintenant() - dernier < 3600:
            return {"envoye": False, "raison": "deja alerte il y a moins d'une heure"}
        _ALERTES_VUES[cle] = maintenant()
    try:
        import urllib.request
        corps = json.dumps({"content": ("**%s**\n%s" % (titre, texte))[:1900]})
        req = urllib.request.Request(
            url, data=corps.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "Remote2-parc/1.0"})
        # Timeout court : cet appel est fait depuis l'horloge, il ne doit
        # jamais retarder le tour suivant.
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(200)
        return {"envoye": True}
    except Exception as e:
        journal("incident_ouvert", objet="incident", code="alerte_perdue",
                par="horloge",
                detail="envoi Discord en echec : %s: %s"
                       % (type(e).__name__, str(e)[:120]))
        return {"envoye": False, "raison": str(e)[:120]}


_PLAFOND_CACHE = [0.0, 200000]


def _plafond_journal() -> int:
    """Le plafond de lignes, relu au plus une fois par minute.

    POURQUOI un cache : sans lui, chaque ligne de journal relisait
    parc_regles.json — et l'observateur en ecrit une rafale a chaque
    declaration de parc. Un reglage change met donc au plus 60 s a
    s'appliquer, ce qui est sans consequence pour une rotation.
    """
    if maintenant() - _PLAFOND_CACHE[0] > 60:
        try:
            _PLAFOND_CACHE[1] = int(charger_regles().get("retention_lignes") or 200000)
        except Exception:
            pass
        _PLAFOND_CACHE[0] = maintenant()
    return int(_PLAFOND_CACHE[1])


def journal(evt: str, objet: str = "plan", machine: str = "", conteneur: str = "",
            job_id: str = "", type_: str = "", duree_s=None, code: str = "",
            detail: str = "", par: str = "", src: str = "site") -> bool:
    """Ecrit UNE ligne de journal. Rend True si elle est partie.

    POURQUOI tout journaliser, y compris les DECISIONS et les REFUS : sans
    eux, on ne saura jamais POURQUOI un tour n'est pas parti. C'est le trou
    d'aujourd'hui — l'ecran ne sait dire que ce qui est arrive, jamais ce
    qui a ete refuse. Une panne a 3 h du matin doit rester lisible le
    lendemain soir.
    """
    global _JOURNAL_N
    ligne = {
        "ts": int(maintenant()),
        "evt": str(evt or "")[:30],
        "objet": str(objet or "")[:12],
        "machine": str(machine or "")[:40],
        "conteneur": str(conteneur or "")[:60],
        "job_id": str(job_id or "")[:30],
        "type": str(type_ or "")[:20],
        "duree_s": (int(duree_s) if isinstance(duree_s, (int, float)) else None),
        "code": str(code or "")[:40],
        "detail": str(detail or "")[:300],
        "par": str(par or "")[:40],
        "src": str(src or "")[:12],
    }
    try:
        with _LOCK_JOURNAL:
            JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            if _JOURNAL_N is None:
                _JOURNAL_N = _compter_lignes(JOURNAL_FILE)
            with open(JOURNAL_FILE, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            _JOURNAL_N += 1
            _rotation_si_besoin(_plafond_journal())
        return True
    except Exception as e:
        # Un journal qui echoue ne doit pas emporter l'action qu'il decrit.
        print("[parc] journal indisponible : %s" % e, flush=True)
        return False


def _lignes_fin(p: Path, maxi: int) -> list:
    """Les `maxi` dernieres lignes d'un fichier, lues par la fin.

    POURQUOI par la fin : le journal est chronologique et l'ecran regarde
    toujours le present. Lire 200 000 lignes pour en afficher 100 ferait
    ramer la page a chaque rafraichissement de 5 secondes.
    """
    out = []
    try:
        taille = p.stat().st_size
    except Exception:
        return out
    reste = b""
    pos = taille
    morceaux = []
    try:
        with open(p, "rb") as f:
            while pos > 0 and sum(m.count(b"\n") for m in morceaux) <= maxi:
                lire = min(1 << 18, pos)
                pos -= lire
                f.seek(pos)
                morceaux.insert(0, f.read(lire))
        reste = b"".join(morceaux)
    except Exception:
        return out
    for l in reste.split(b"\n")[-(maxi + 1):]:
        if not l.strip():
            continue
        try:
            out.append(json.loads(l.decode("utf-8", "replace")))
        except Exception:
            continue        # une ligne coupee par une rotation : on l'ignore
    return out


def journal_lire(evt: str = "", objet: str = "", machine: str = "",
                 conteneur: str = "", code: str = "", texte: str = "",
                 depuis_s: int = 0, page: int = 1, par_page: int = 100,
                 balayage: int = 20000) -> dict:
    """Lit le journal filtre et PAGINE, en disant toujours ce qu'il ne montre
    pas : combien de lignes correspondent, combien sont masquees, et si le
    balayage lui-meme a ete plafonne. Aucun slice() muet."""
    par_page = max(10, min(1000, int(par_page or 100)))
    page = max(1, int(page or 1))
    lignes = _lignes_fin(JOURNAL_FILE, int(balayage))
    balaye = len(lignes)
    lim = maintenant() - float(depuis_s) if depuis_s else 0
    t = (texte or "").lower().strip()

    def garde(l):
        if evt and l.get("evt") != evt:
            return False
        if objet and l.get("objet") != objet:
            return False
        if machine and l.get("machine") != machine:
            return False
        if conteneur and l.get("conteneur") != conteneur:
            return False
        if code and l.get("code") != code:
            return False
        if lim and float(l.get("ts") or 0) < lim:
            return False
        if t and t not in json.dumps(l, ensure_ascii=False).lower():
            return False
        return True

    gardees = [l for l in lignes if garde(l)]
    gardees.reverse()               # le plus recent d'abord
    total = len(gardees)
    debut = (page - 1) * par_page
    tranche = gardees[debut:debut + par_page]
    return {
        "lignes": tranche, "total": total, "page": page,
        "pages": max(1, (total + par_page - 1) // par_page),
        "par_page": par_page,
        "masquees": max(0, total - len(tranche) - debut),
        "balaye": balaye,
        # Le balayage lui-meme est borne : le dire, sinon « 0 resultat »
        # pourrait vouloir dire « rien » ou « trop loin dans le passe ».
        "balayage_plafonne": balaye >= int(balayage),
        "rotation_disponible": JOURNAL_ROT.exists(),
    }


def journal_lignes_total() -> int:
    """Taille du journal, pour l'afficher au lieu de la subir."""
    global _JOURNAL_N
    if _JOURNAL_N is None:
        _JOURNAL_N = _compter_lignes(JOURNAL_FILE)
    return _JOURNAL_N


# ==================================================================
# 5. LES ECARTS — le journal du NEGATIF
# ==================================================================
# « Ne jamais ecarter en silence : compter et remonter. » Le journal
# chronologique ne sait pas repondre a « qu'est-ce que le pilote n'a pas
# fait, combien de fois, et que dois-je changer pour que ca cesse ». Ce
# fichier-la, oui.


def ecart(motif: str, conteneur: str = "", machine: str = "",
          detail: str = "", journaliser: bool = True) -> None:
    """Compte un refus. Un ecart non compte est un « ca ne marche pas » de
    plus dans six mois."""
    jour = datetime.fromtimestamp(maintenant()).strftime("%Y-%m-%d")
    with _LOCK_ECARTS:
        d = safe_json.load(ECARTS_FILE, default={}) or {}
        if not isinstance(d, dict):
            d = {}
        e = d.get(motif) or {"total": 0, "jours": {}, "dernier_ts": 0,
                             "dernier_exemplaire": "", "conduite": conduite(motif)}
        e["total"] = int(e.get("total") or 0) + 1
        jours = e.get("jours") or {}
        jours[jour] = int(jours.get(jour) or 0) + 1
        # 14 jours suffisent a l'ecran ; au-dela c'est le journal qui sert.
        e["jours"] = dict(sorted(jours.items())[-14:])
        e["dernier_ts"] = int(maintenant())
        e["dernier_exemplaire"] = (conteneur or machine or detail or "")[:120]
        e["conduite"] = conduite(motif)
        d[motif] = e
        safe_json.write(ECARTS_FILE, d, indent=1)
    if journaliser:
        journal("plan_refus", objet="plan", conteneur=conteneur, machine=machine,
                code=motif, detail=detail)


def ecarts_resume() -> list:
    """Les refus groupes par motif, avec 24 h, total, dernier exemplaire et
    la conduite a tenir. C'est le tableau « Ecarts » de l'ecran."""
    d = safe_json.load(ECARTS_FILE, default={}) or {}
    if not isinstance(d, dict):
        return []
    hier = datetime.fromtimestamp(maintenant() - 86400).strftime("%Y-%m-%d")
    auj = datetime.fromtimestamp(maintenant()).strftime("%Y-%m-%d")
    out = []
    for motif, e in d.items():
        jours = e.get("jours") or {}
        out.append({
            "motif": motif,
            "libelle": conduite(motif),
            "h24": int(jours.get(auj) or 0) + int(jours.get(hier) or 0),
            "total": int(e.get("total") or 0),
            "dernier_ts": int(e.get("dernier_ts") or 0),
            "dernier_age": duree_humaine(_age(e.get("dernier_ts"))),
            "dernier_exemplaire": e.get("dernier_exemplaire") or "",
            "conduite": e.get("conduite") or conduite(motif),
        })
    out.sort(key=lambda x: (-x["h24"], -x["total"]))
    return out


# ==================================================================
# 6. L'OBSERVATEUR — l'historien du parc
# ==================================================================
# LA PIECE SANS LAQUELLE RIEN DU RESTE N'EXISTE.
# Le poste ne transmet ni date de creation, ni date de derniere action, ni
# duree, ni identite de machine. Sans historien :
#   * les trois tris demandes (plus recent / dernier cree / plus vieux) sont
#     IMPOSSIBLES — le site n'a que nom, categorie, pseudo, passages, statut ;
#   * aucune duree n'existe, donc « ce cycle traine » ne peut pas se dire ;
#   * le compteur de chutes de WDA n'existe pas, donc la panne du 21/08
#     (WDA qui tombait toutes les 20 s) reste invisible.
# L'observateur ne coute AUCUNE ligne cote poste : il compare simplement
# chaque declaration a la precedente, et journalise la difference.


def _hist_vide() -> dict:
    return {"depuis": int(maintenant()), "conteneurs": {}, "machines": {},
            "wda": {"etat": None, "chutes": [], "change_le": 0},
            "jobs": {}, "heures": {}, "durees": []}


def charger_hist() -> dict:
    d = safe_json.load(HIST_FILE, default=None)
    if not isinstance(d, dict):
        return _hist_vide()
    base = _hist_vide()
    for k, v in d.items():
        base[k] = v
    base.setdefault("depuis", int(maintenant()))
    return base


def _sauver_hist(h: dict) -> None:
    # Bornes : un historique qui grossit sans fin finit par couter plus cher
    # a lire que l'ecran qu'il alimente.
    try:
        h["durees"] = list(h.get("durees") or [])[-200:]
        w = h.get("wda") or {}
        w["chutes"] = list(w.get("chutes") or [])[-500:]
        h["wda"] = w
        jobs = h.get("jobs") or {}
        if len(jobs) > 400:
            gardes = sorted(jobs.items(), key=lambda kv: -(kv[1].get("vu") or 0))[:400]
            h["jobs"] = dict(gardes)
        heures = h.get("heures") or {}
        if len(heures) > 400:
            h["heures"] = dict(sorted(heures.items())[-400:])
    except Exception:
        pass
    with _LOCK_HIST:
        HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write(HIST_FILE, h, indent=None)


def hist_age_h() -> float:
    """Depuis combien d'heures l'observateur observe. Sert a dire « tri actif
    dans 19 h » au lieu de proposer un tri qui mentirait."""
    h = charger_hist()
    return max(0.0, (maintenant() - float(h.get("depuis") or maintenant())) / 3600.0)


def _bucket_heure(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d-%H")


def _compter_heure(h: dict, quoi: str, quand: float = None) -> None:
    """Compteur horaire (fini / echec / refuse / publie) : c'est la matiere du
    graphique de debit des 24 dernieres heures."""
    b = _bucket_heure(quand if quand else maintenant())
    heures = h.setdefault("heures", {})
    case = heures.setdefault(b, {})
    case[quoi] = int(case.get(quoi) or 0) + 1


def observer_parc() -> dict:
    """Compare la declaration de parc qui vient d'arriver a la precedente.

    Ce qu'on en tire, et qu'aucun fichier ne contient aujourd'hui :
    premiere_vue et derniere_vue par conteneur (donc les trois tris par
    date), les apparitions et disparitions, les changements de statut et de
    passages (donc la « derniere activite »), et les transitions du booleen
    `wda` true->false — c'est-a-dire le COMPTEUR DE CHUTES par heure, la
    seule facon de voir un WDA qui tombe toutes les 20 secondes.
    """
    parc = lire_parc()
    with _LOCK_HIST:
        h = charger_hist()
        ch = h.setdefault("conteneurs", {})
        now = int(maintenant())
        # PREMIER passage de l'observateur : tout ce qu'il voit existait
        # avant lui, donc aucune de ces « premiere_vue » n'est une date de
        # creation. Aux passages SUIVANTS, un conteneur qui apparait est
        # reellement neuf et sa date, elle, est vraie. Sans cette
        # distinction, `avant_observateur` etait pose sur TOUS les
        # conteneurs, y compris ceux crees plus tard : les tris « dernier
        # cree » et « plus vieux » n'auraient jamais eu la moindre date
        # exploitable.
        premier_passage = not bool(h.get("premier_passage_fait"))
        vus = set()
        for c in parc["conteneurs"]:
            nom = str(c.get("nom") or "")
            if not nom:
                continue
            vus.add(nom)
            e = ch.get(nom)
            if e is None:
                e = ch[nom] = {
                    "premiere_vue": now, "derniere_vue": now,
                    "passages": int(c.get("passages") or 0), "passages_le": 0,
                    "statut": str(c.get("statut") or ""), "statut_le": now,
                    "sig": "", "etapes_le": 0, "echecs": [],
                    # Un conteneur present AVANT l'installation n'a pas de
                    # vraie date de creation : on le marque, et l'ecran
                    # affiche « ≈ » plutot qu'une date inventee.
                    "avant_observateur": premier_passage,
                }
                journal("parc_apparu", objet="parc", conteneur=nom,
                        detail="categorie %s" % (c.get("categorie") or "aucune"))
            e["derniere_vue"] = now
            p = int(c.get("passages") or 0)
            if p != int(e.get("passages") or 0):
                journal("parc_passage", objet="parc", conteneur=nom,
                        detail="%s -> %s passage(s)" % (e.get("passages"), p))
                e["passages"], e["passages_le"] = p, now
            st = str(c.get("statut") or "")
            if st != e.get("statut"):
                journal("parc_statut", objet="parc", conteneur=nom,
                        code=("captcha" if st == "bloque" else ""),
                        detail="statut %s -> %s" % (e.get("statut") or "vide",
                                                    st or "vide"))
                e["statut"], e["statut_le"] = st, now
                if st == "echec":
                    e["echecs"] = (e.get("echecs") or [])[-19:] + [now]
            sig = json.dumps(c.get("etapes") or {}, sort_keys=True)
            if sig != e.get("sig"):
                e["sig"], e["etapes_le"] = sig, now
        # Disparitions : un conteneur qui sort du registre sans que personne
        # ne le dise, c'est exactement « 87 conteneurs pour 33 reels ».
        for nom in list(ch.keys()):
            if nom in vus:
                continue
            e = ch[nom]
            if not e.get("disparu_le"):
                e["disparu_le"] = now
                journal("parc_disparu", objet="parc", conteneur=nom,
                        detail="n'est plus declare par le poste")
        # WDA : c'est la TRANSITION qui informe, pas le booleen.
        w = h.setdefault("wda", {"etat": None, "chutes": [], "change_le": 0})
        etat = bool(parc.get("wda"))
        if w.get("etat") is None:
            w["etat"], w["change_le"] = etat, now
        elif etat != bool(w.get("etat")):
            if not etat:
                w["chutes"] = list(w.get("chutes") or []) + [now]
                journal("wda_chute", objet="poste", code="wda_injoignable",
                        detail="WebDriverAgent ne repond plus")
            else:
                journal("wda_retour", objet="poste",
                        detail="WebDriverAgent repond de nouveau")
            w["etat"], w["change_le"] = etat, now
        # Le premier passage est fait : a partir de maintenant, un conteneur
        # qui apparait est reellement neuf.
        h["premier_passage_fait"] = True
        _sauver_hist(h)
    return {"ok": True, "conteneurs": len(parc["conteneurs"]),
            "premier_passage": premier_passage}


def observer_pull(corps: dict = None) -> dict:
    """Enregistre le battement d'une machine et cherche les agents empiles.

    SIGNATURE DU 21/08 : deux prises de travail a moins de 8 secondes, ou
    deux PID differents vus dans la meme minute. Le verrou socket 8771 rend
    la situation impossible depuis, mais le SITE ne le sait pas : tant que
    l'agent ne joint pas {verrou:{pid,depuis}} a son pull, cette signature
    derivee est le seul filet.
    """
    corps = corps if isinstance(corps, dict) else {}
    nom = str(corps.get("machine") or "").strip()[:40] or MACHINE_DEFAUT
    verrou = corps.get("verrou") if isinstance(corps.get("verrou"), dict) else {}
    now = maintenant()
    with _LOCK_HIST:
        h = charger_hist()
        ms = h.setdefault("machines", {})
        m = ms.get(nom)
        # Frein : le battement est a 8 s au repos et 1 s en pilotage. Sans
        # lui, parc_hist.json etait reecrit deux fois par seconde pour une
        # information qui n'a pas bouge — et ce sont les ecritures du poste
        # qui ralentissaient. Une prise rapide (agents empiles) passe quand
        # meme : c'est justement ce qu'on cherche.
        recent = m and (now - float(m.get("dernier_vu") or 0)) < 10
        rapide = bool(m and m.get("pulls") and (now - m["pulls"][-1]) < 8)
        if recent and not rapide and not verrou.get("pid"):
            m["dernier_vu"] = int(now)
            return {"ok": True, "machine": nom, "ecrit": False}
        if m is None:
            m = ms[nom] = {"premier_vu": int(now), "dernier_vu": int(now),
                           "pulls": [], "pids": {}, "rapides": 0,
                           "battements": 0, "muette_depuis": 0,
                           "identifiee": bool(corps.get("machine"))}
            journal("poste_retour", objet="poste", machine=nom,
                    detail="premiere apparition de cette machine")
        precedent = float(m.get("dernier_vu") or 0)
        if precedent and (now - precedent) > 300:
            journal("poste_retour", objet="poste", machine=nom,
                    detail="de nouveau la apres %s de silence"
                           % duree_humaine(now - precedent))
        m["dernier_vu"] = int(now)
        m["battements"] = int(m.get("battements") or 0) + 1
        m["muette_depuis"] = 0
        pulls = [t for t in (m.get("pulls") or []) if now - t < 3600][-49:]
        # Deux prises a moins de 8 s : le battement nominal du poste EST de
        # 8 s, donc plus rapide veut dire « deux agents parlent ».
        if pulls and (now - pulls[-1]) < 8:
            m["rapides"] = int(m.get("rapides") or 0) + 1
            if m["rapides"] in (1, 5, 20, 50):
                journal("agents_empiles", objet="verrou", machine=nom,
                        code="refus_garde_fou",
                        detail="battement %.1f s (nominal 8 s) — %d fois"
                               % (now - pulls[-1], m["rapides"]))
        pulls.append(now)
        m["pulls"] = pulls
        pid = str(verrou.get("pid") or "")
        if pid:
            pids = m.setdefault("pids", {})
            if pid not in pids:
                if pids and (now - max(pids.values())) < 60:
                    journal("agents_empiles", objet="verrou", machine=nom,
                            detail="deux PID vus en moins d'une minute : %s"
                                   % ", ".join(list(pids)[:3] + [pid]))
                journal("verrou_pris", objet="verrou", machine=nom,
                        detail="pid %s" % pid)
            pids[pid] = now
            m["pids"] = {k: v for k, v in pids.items() if now - v < 7200}
        et = corps.get("etat")
        if isinstance(et, dict):
            m["etat_poste"] = {"connecte": bool(et.get("connecte")),
                               "appareil": str(et.get("appareil") or "")[:40]}
        _sauver_hist(h)
    return {"ok": True, "machine": nom, "ecrit": True}


def observer_jobs(src: str = "", machine: str = "") -> dict:
    """Derive tout ce qui manque a la file : durees, codes, machine, doutes.

    C'est ici que trois trous se ferment d'un coup :
      * la DUREE (maj - pris_a) — aucun job n'en a aujourd'hui ;
      * le CODE d'erreur court, tire d'une fin de stdout tronquee a 300
        caracteres, sans quoi rien n'est groupable par cause ;
      * la REUSSITE DOUTEUSE : un cycle « fini » en moins de 4 minutes alors
        qu'un passage reel dure 8 min 54, c'est un ecran « confirm that
        you're human » archive comme un succes. Il est compte a part, jamais
        efface : l'historique de succes est partiellement faux et ca doit se
        voir au lieu d'un 100 % confortable.
    """
    f = lire_jobs()
    regles = charger_regles()
    court_s = int(regles.get("succes_court_min") or 4) * 60
    modif = False
    with _LOCK_HIST:
        h = charger_hist()
        js = h.setdefault("jobs", {})
        now = int(maintenant())
        for job in f["jobs"]:
            jid = str(job.get("id") or "")
            if not jid:
                continue
            etat = str(job.get("etat") or "")
            e = js.get(jid)
            if e is not None and e.get("etat") == etat:
                continue        # rien n'a bouge : ne pas reecrire l'historique
            modif = True
            if e is None:
                # machine="" et NON MACHINE_DEFAUT : tant que personne n'a
                # tire ce travail, on ne sait pas quel telephone le prendra.
                # Ecrire « poste-1 » ici, c'etait inventer une attribution —
                # et c'est ce qui faisait afficher le meme travail sur les
                # cinq lignes du tableau des machines.
                e = js[jid] = {"vu": now, "etat": "", "conteneur": job.get("conteneur") or "",
                               "type": job.get("type") or "", "par": job.get("par") or "",
                               "cree": int(job.get("cree") or now), "duree_s": None,
                               "code": "", "douteux": False,
                               "machine": ""}
                # Un travail inscrit sans passer par le plan (quelqu'un a
                # clique dans Remote 1) : trace comme tel, jamais confondu
                # avec une decision de l'ordonnanceur.
                journal("hors_plan" if (job.get("par") or "") != "remote2" else "inscrit",
                        objet="job", job_id=jid, conteneur=job.get("conteneur") or "",
                        type_=job.get("type") or "", par=job.get("par") or "",
                        src=src or "observateur",
                        detail="inscrit dans la file")
            if etat and etat != e.get("etat"):
                duree = None
                if job.get("pris_a") and job.get("maj"):
                    try:
                        duree = max(0, int(job["maj"]) - int(job["pris_a"]))
                    except (TypeError, ValueError):
                        duree = None
                if etat == "pris":
                    # C'est le pull qui revele l'attribution : la machine qui
                    # parle en ce moment est celle qui vient de prendre le
                    # travail. Seule mesure d'attribution qui existe.
                    if machine:
                        e["machine"] = machine
                    journal("pris", objet="job", job_id=jid,
                            conteneur=job.get("conteneur") or "",
                            machine=e.get("machine") or "", type_=job.get("type") or "")
                elif etat == "en_cours":
                    journal("avance", objet="job", job_id=jid,
                            conteneur=job.get("conteneur") or "",
                            machine=e.get("machine") or "",
                            detail=str(job.get("avancement") or "")[:200])
                elif etat == "fini":
                    douteux = bool(duree is not None and duree < court_s
                                   and (job.get("type") in ("cycle", "scenario")))
                    e["douteux"] = douteux
                    if duree is not None:
                        h.setdefault("durees", []).append(int(duree))
                    _compter_heure(h, "fini")
                    if douteux:
                        _compter_heure(h, "douteux")
                        ecart("reussite_douteuse", conteneur=job.get("conteneur") or "",
                              detail="fini en %s, seuil %s"
                                     % (duree_humaine(duree), duree_humaine(court_s)),
                              journaliser=False)
                    journal("fini", objet="job", job_id=jid,
                            conteneur=job.get("conteneur") or "",
                            machine=e.get("machine") or "", duree_s=duree,
                            code=("reussite_douteuse" if douteux else ""),
                            detail=("reussite DOUTEUSE : trop rapide pour etre vraie"
                                    if douteux else str(job.get("avancement") or "")[:200]))
                elif etat == "echec":
                    code = classer_erreur(str(job.get("erreur") or ""))
                    e["code"] = code
                    _compter_heure(h, "echec")
                    journal("echec", objet="job", job_id=jid,
                            conteneur=job.get("conteneur") or "",
                            machine=e.get("machine") or "", duree_s=duree,
                            code=code, detail=str(job.get("erreur") or "")[:300])
                    if code == "captcha":
                        # L'ecran « confirm that you're human » n'est pas une
                        # reussite : le conteneur part en quarantaine.
                        mettre_en_quarantaine(job.get("conteneur") or "",
                                              "captcha", par="observateur")
                e["etat"] = etat
                e["duree_s"] = duree
                e["vu"] = now
        if modif:
            _sauver_hist(h)
    return {"ok": True, "jobs": len(f["jobs"]), "ecrit": modif}


def mediane_duree() -> tuple:
    """(mediane en secondes, nombre de mesures). Tant qu'il y a moins de 20
    passages journalises, l'ecran garde l'estimation ○ decomposee et le dit ;
    au-dela il affiche « mediane MESUREE sur N passages »."""
    h = charger_hist()
    d = sorted(int(x) for x in (h.get("durees") or []) if x)
    if not d:
        return (None, 0)
    n = len(d)
    med = d[n // 2] if n % 2 else (d[n // 2 - 1] + d[n // 2]) // 2
    return (med, n)


def duree_passage_s(regles: dict = None) -> tuple:
    """La duree d'un passage : mesuree si on en a assez, estimee sinon.

    Rend (secondes, provenance, phrase). On n'invente jamais une estimation
    sans dire d'ou elle sort — c'est la regle « aucun chiffre sans sa
    provenance » appliquee au denominateur de tous les calculs de charge.
    """
    regles = regles or charger_regles()
    med, n = mediane_duree()
    if med and n >= 20:
        return (med, MESURE, "mediane mesuree sur %d passages" % n)
    est = int(regles.get("duree_passage_min") or 11) * 60
    return (est, NON_DECLARE,
            "estimation : 40 s bascule + 60 s import + %d x 90 s + 30 s de marge"
            % int(regles.get("reels_par_passage") or 6))


def mettre_en_quarantaine(conteneur: str, motif: str, par: str = "?") -> bool:
    """Ecarte un conteneur du plan jusqu'a decision humaine.

    POURQUOI a la main par defaut : un compte bloque par Instagram ne se
    debloque pas tout seul, et reessayer automatiquement ne fait que
    confirmer le blocage.
    """
    conteneur = str(conteneur or "").strip()
    if not conteneur:
        return False
    e = charger_etat()
    q = e.setdefault("quarantaine", {})
    if conteneur in q:
        return False
    q[conteneur] = {"depuis": int(maintenant()), "motif": motif, "par": par}
    enregistrer_etat(e)
    journal("incident_ouvert", objet="parc", conteneur=conteneur, code=motif,
            par=par, detail="mis en quarantaine")
    ecart("quarantaine", conteneur=conteneur, detail=motif, journaliser=False)
    return True


def rehabiliter(conteneur: str, par: str = "?") -> bool:
    """Sort un conteneur de quarantaine. Journalise QUI l'a fait : c'est une
    decision humaine, elle doit avoir un nom."""
    e = charger_etat()
    q = e.setdefault("quarantaine", {})
    if conteneur not in q:
        return False
    q.pop(conteneur, None)
    enregistrer_etat(e)
    journal("incident_acquitte", objet="parc", conteneur=conteneur, par=par,
            detail="sorti de quarantaine")
    return True


def observer_inventaire(donnees: dict, par: str = "?") -> dict:
    """Enregistre un recensement REEL du telephone (colle a la main ou pousse
    par le poste). C'est la seule chose qui peut rendre vert le controle
    « le registre correspond au telephone » — sans elle il reste ○."""
    noms = [str(x)[:60] for x in (donnees.get("conteneurs") or []) if x][:1000]
    d = {"conteneurs": noms, "nombre": int(donnees.get("nombre") or len(noms)),
         "releve_le": str(donnees.get("releve_le") or "")[:40],
         "note": str(donnees.get("note") or "")[:300],
         "ts": int(maintenant()), "par": par}
    safe_json.write(INVENTAIRE_FILE, d, indent=1)
    journal("inventaire", objet="parc", par=par,
            detail="%d conteneur(s) reellement presents" % len(noms))
    return {"ok": True, "n": len(noms)}


# ==================================================================
# 7. LE CONTEXTE — une seule lecture de chaque source par affichage
# ==================================================================
def machine_du_job(job: dict, hist: dict) -> str:
    """Le telephone qui tient CE travail, ou "" si personne ne l'a declare.

    L'attribution est derivee (◐) : elle vient du nom de machine joint au
    /api/rig/pull qui a fait passer le travail a « pris ». Une chaine vide
    est une reponse honnete — la remplacer par MACHINE_DEFAUT etait la
    fabrication qui montrait le meme travail sur tous les telephones.
    """
    e = (hist.get("jobs") or {}).get(str(job.get("id") or "")) or {}
    return str(e.get("machine") or "")


def machines_liste(hist: dict, jobs: dict, etat: dict, regles: dict) -> list:
    """Une ligne par telephone. La machine est une dimension de PREMIER
    PLAN, pas une colonne ajoutee apres coup.

    Tant que l'agent ne joint pas son nom au corps du /pull, il n'y a qu'une
    ligne « poste-1 (non identifie) » — et la phrase qui va avec : un second
    telephone ecraserait ses donnees (rig_parc.json est un document global
    unique). Le jour ou le champ arrive, l'ecran passe a N machines sans une
    ligne de code de plus.
    """
    now = maintenant()
    muette_s = int(regles.get("muette_min") or 5) * 60
    ms = dict(hist.get("machines") or {})
    if not ms:
        # Aucun pull observe : on se rabat sur le battement global, qui est
        # la seule preuve de vie disponible.
        ms = {MACHINE_DEFAUT: {"premier_vu": 0, "dernier_vu": jobs.get("battement") or 0,
                               "pulls": [], "pids": {}, "rapides": 0,
                               "battements": 0, "identifiee": False}}
    suspendues = (etat.get("machines") or {})
    en_cours = [j for j in jobs["jobs"] if j.get("etat") in ("pris", "en_cours")]
    # Les travaux dont AUCUN pull n'a revele la machine. A une seule machine
    # connue, l'attribution ne fait aucun doute ; au-dela, on ne devine pas.
    orphelins = [j for j in en_cours if not machine_du_job(j, hist)]
    out = []
    for nom, m in ms.items():
        age = now - float(m.get("dernier_vu") or 0) if m.get("dernier_vu") else -1
        sus = bool((suspendues.get(nom) or {}).get("suspendue"))
        # UN travail appartient a UNE machine. `miens = en_cours` donnait la
        # liste ENTIERE a chaque machine identifiee : a 5 machines, les 5
        # lignes affichaient « jobs=29 » et le meme « fait=cpt0209 », soit
        # 145 travaux montres pour 29 reels — une attribution fabriquee dans
        # le seul tableau cense porter la dimension machine.
        miens = [j for j in en_cours if machine_du_job(j, hist) == nom]
        if len(ms) == 1:
            miens = list(en_cours)
        if sus:
            etat_m = "suspendue"
        elif age < 0 or age > muette_s:
            etat_m = "muette"
        elif miens:
            etat_m = "travail"
        else:
            etat_m = "attente"
        pids = list((m.get("pids") or {}).keys())
        out.append({
            "nom": nom,
            "identifiee": bool(m.get("identifiee")),
            "etat": etat_m,
            "dernier_vu": int(m.get("dernier_vu") or 0),
            "silence_s": int(age) if age >= 0 else None,
            "silence": duree_humaine(age) if age >= 0 else "jamais vue",
            # Colonne parapluie : QUI TIENT LE TELEPHONE. Sans elle, on ne
            # sait pas combien d'agents tournent — la panne du 21/08.
            "verrou": ({"pid": pids[-1], "provenance": MESURE} if pids else
                       {"pid": None, "provenance": NON_DECLARE}),
            "verrou_texte": ("verrou 8771 — pid %s" % pids[-1] if pids else
                             "AUCUN VERROU DECLARE"),
            "battements": int(m.get("battements") or 0),
            "pulls_rapides": int(m.get("rapides") or 0),
            "fait_quoi": (("%s — %s" % (miens[0].get("conteneur") or "?",
                                        (miens[0].get("avancement") or
                                         miens[0].get("type") or "")[:40]))
                          if miens else ""),
            "jobs_en_cours": len(miens),
            "suspendue": sus,
            "etat_poste": m.get("etat_poste") or {},
        })
    # Les MUETTES EN HAUT : a l'echelle, ce qu'on cherche c'est le poste qui
    # ne parle plus, pas celui qui travaille bien.
    ordre = {"muette": 0, "suspendue": 1, "travail": 2, "attente": 3}
    out.sort(key=lambda m: (ordre.get(m["etat"], 4), -(m["silence_s"] or 0)))
    return out


def contexte() -> dict:
    """Lit CHAQUE source une seule fois et rend l'etat brut du monde.

    POURQUOI : les garde-fous, les agregats, les graphiques et le
    planificateur regardent les memes fichiers. Sans contexte partage, un
    seul affichage de la page relisait rig_parc.json une douzaine de fois —
    et pouvait afficher deux chiffres incoherents pris a deux instants.
    """
    regles = charger_regles()
    parc = lire_parc()
    jobs = lire_jobs()
    hist = charger_hist()
    etat = charger_etat()
    ctx = {
        "now": maintenant(),
        "regles": regles,
        "parc": parc,
        "conteneurs": parc["conteneurs"],
        "jobs": jobs,
        "hist": hist,
        "etat": etat,
        "actions": lire_actions(),
        "scenarios": lire_scenarios(),
        "pilotage_ts": pilotage_ts(),
        "inventaire": lire_inventaire(),
        "stock": stock_categories(parc),
    }
    ctx["machines"] = machines_liste(hist, jobs, etat, regles)
    ctx["age_max_s"] = max([x for x in (parc["age_s"], jobs["battement_age_s"]) if x and x > 0]
                           or [-1])
    return ctx


# ==================================================================
# 8. LES GARDE-FOUS — « tout ce qui pourrait entraver ce qui tourne »
# ==================================================================
# Chacun est une fonction separee qui rend UN diagnostic. Tous sont fondes
# sur ce qui est reellement arrive la nuit du 21/08, ou sur un trou constate
# dans les donnees. Un controle qu'on ne peut pas faire rend ○ GRIS — jamais
# vert : « je ne sais pas » et « tout va bien » ne se ressemblent pas.
VERT, AMBRE, ROUGE, GRIS = "vert", "ambre", "rouge", "gris"


def _diag(cle, nom, gravite, valeur, message, bloque=False,
          provenance=DERIVE, source="", age_s=None, action=None,
          correctif="") -> dict:
    """Forme unique d'un diagnostic : verdict, valeur observee, ce que ca
    bloque, et le bouton qui repare. Un controle sans conduite a tenir est
    une lampe rouge sans notice."""
    return {"cle": cle, "nom": nom, "gravite": gravite, "valeur": valeur,
            "message": message, "bloque": bool(bloque) and gravite == ROUGE,
            "bloquant_si_rouge": bool(bloque), "provenance": provenance,
            "marque": marque(provenance), "source": source,
            "age_s": (int(age_s) if isinstance(age_s, (int, float)) and age_s >= 0
                      else None),
            "age": duree_humaine(age_s) if isinstance(age_s, (int, float)) and age_s >= 0
                   else "",
            "action": action or {}, "correctif": correctif}


def gf_poste_repond(ctx) -> dict:
    """Agent mort ou machine eteinte : rien ne partira, mais l'ecran
    continuerait d'afficher un plan credible."""
    age = ctx["jobs"]["battement_age_s"]
    if age < 0:
        return _diag("poste", "Le poste repond", GRIS, "jamais vu",
                     "Aucun battement n'a jamais ete recu : l'agent n'a jamais "
                     "parle a ce site.", bloque=True, provenance=NON_DECLARE,
                     source="rig_jobs.json > battement",
                     action={"quoi": "journal", "libelle": "Journal"})
    if age > 90:
        return _diag("poste", "Le poste repond", ROUGE, "muet %s" % duree_humaine(age),
                     "Rien ne partira tant que l'agent ne rappelle pas.",
                     bloque=True, provenance=MESURE,
                     source="rig_jobs.json > battement", age_s=age,
                     action={"quoi": "journal", "libelle": "Journal"})
    return _diag("poste", "Le poste repond", VERT, "il y a %s" % duree_humaine(age),
                 "L'agent bat normalement (8 s au repos).", bloque=True,
                 provenance=MESURE, source="rig_jobs.json > battement", age_s=age)


def gf_agent_unique(ctx) -> dict:
    """LA panne fondatrice : quatre agents empiles par des relances
    successives se disputaient WebDriverAgent et pouvaient rejouer le meme
    travail quatre fois. Le verrou socket 8771 existe depuis, cote poste —
    mais il n'est pas declare au site, donc on derive la signature."""
    suspects = [m for m in ctx["machines"] if m["pulls_rapides"] > 0]
    declare = [m for m in ctx["machines"] if m["verrou"]["pid"]]
    if suspects:
        return _diag("agent_unique", "Un seul agent par machine", ROUGE,
                     "%d machine(s) suspecte(s)" % len(suspects),
                     "Battement plus rapide que le nominal de 8 s : plusieurs "
                     "agents prennent du travail sur le meme telephone. Ils "
                     "peuvent rejouer le meme geste plusieurs fois.",
                     bloque=True, provenance=DERIVE,
                     source="cadence des /api/rig/pull",
                     action={"quoi": "machines", "libelle": "Voir les machines"})
    if not declare:
        return _diag("agent_unique", "Un seul agent par machine", GRIS,
                     "non declare",
                     "Le poste ne dit pas qui tient le telephone. Le verrou "
                     "8771 existe cote poste depuis le 21/08 : il suffirait de "
                     "joindre {verrou:{pid,depuis}} au corps du /pull pour que "
                     "ce controle devienne ● mesure.",
                     bloque=True, provenance=NON_DECLARE,
                     source="corps de /api/rig/pull",
                     correctif="agent_rig.un_tour() : joindre le pid du verrou 8771")
    return _diag("agent_unique", "Un seul agent par machine", VERT,
                 "%d verrou(s) declare(s)" % len(declare),
                 "Un seul agent par telephone, verrou a l'appui.", bloque=True,
                 provenance=MESURE, source="corps de /api/rig/pull")


def gf_hors_file(ctx) -> dict:
    """Un cycle.py lance a la main pendant que le pilote veut travailler :
    c'est le conflit le plus courant, et il est totalement invisible du site.
    Tout se lit deja LOCALEMENT (mini.PILOTES + psutil, utilises par
    action_stop_tout) — il ne reste qu'a le transmettre."""
    vus = [m for m in ctx["machines"] if (m.get("etat_poste") or {}).get("pilotes")]
    if not vus:
        return _diag("hors_file", "Rien ne tourne hors de la file", GRIS,
                     "non declare",
                     "Le site affichera « rien en cours » pendant qu'un "
                     "cycle.py tourne — et laissera en lancer un second.",
                     bloque=True, provenance=NON_DECLARE,
                     source="corps de /api/rig/pull",
                     correctif="joindre pilotes_actifs (mini.PILOTES vus par psutil)")
    return _diag("hors_file", "Rien ne tourne hors de la file", AMBRE,
                 "%d script(s) hors file" % len(vus),
                 "Un travail tourne en dehors de la file : le pilote doit "
                 "attendre, sinon deux scripts se disputent le telephone.",
                 bloque=True, provenance=MESURE, source="corps de /api/rig/pull")


def gf_wda_repond(ctx) -> dict:
    """Sans WebDriverAgent, aucun geste n'est possible : tous les travaux
    echoueraient l'un apres l'autre."""
    p = ctx["parc"]
    if p["ts"] == 0:
        return _diag("wda", "WebDriverAgent repond", GRIS, "non declare",
                     "Le parc n'a jamais ete declare : on ne sait pas si le "
                     "telephone repond.", bloque=True, provenance=NON_DECLARE,
                     source="rig_parc.json > wda")
    if not p["wda"]:
        return _diag("wda", "WebDriverAgent repond", ROUGE, "non",
                     "Aucun geste n'est possible sur le telephone.",
                     bloque=True, provenance=MESURE, source="rig_parc.json > wda",
                     age_s=p["age_s"],
                     action={"quoi": "reessayer", "libelle": "Reessayer"})
    return _diag("wda", "WebDriverAgent repond", VERT, "oui",
                 "Le telephone accepte les gestes.", bloque=True,
                 provenance=MESURE, source="rig_parc.json > wda", age_s=p["age_s"])


def gf_wda_stable(ctx) -> dict:
    """WDA qui tombe et se recree en boucle. Le 21/08 il tombait toutes les
    20 s parce que la console interrogeait le telephone pendant une purge.
    Un booleen sans historique ne montre RIEN de ce probleme — d'ou le
    compteur de chutes derive par l'observateur."""
    chutes = [t for t in ((ctx["hist"].get("wda") or {}).get("chutes") or [])
              if ctx["now"] - t < 3600]
    seuil = int(ctx["regles"].get("seuil_wda_chutes") or 3)
    if len(chutes) >= seuil:
        return _diag("wda_stable", "WebDriverAgent est stable", ROUGE,
                     "%d chutes en 1 h" % len(chutes),
                     "Au-dela de %d chutes par heure ce n'est plus un alea : le "
                     "pilotage ecran doit rester gele jusqu'a 15 min sans "
                     "chute." % seuil, bloque=False, provenance=DERIVE,
                     source="transitions wda observees")
    if chutes:
        return _diag("wda_stable", "WebDriverAgent est stable", AMBRE,
                     "%d chute(s) en 1 h" % len(chutes),
                     "Surveiller : au-dela de %d par heure, le parc se met en "
                     "pause." % seuil, bloque=False, provenance=DERIVE,
                     source="transitions wda observees")
    return _diag("wda_stable", "WebDriverAgent est stable", VERT, "0 chute en 1 h",
                 "Aucune chute observee depuis une heure.", bloque=False,
                 provenance=DERIVE, source="transitions wda observees")


def gf_tunnel(ctx) -> dict:
    """Tunnel localtunnel mort = zero publication de toute la nuit, sans la
    moindre alerte. La mesure existe deja cote poste
    (etapes/_commun.py:62, tunnel_repond) : elle n'est pas transmise."""
    val = None
    for m in ctx["machines"]:
        v = (m.get("etat_poste") or {}).get("tunnel")
        if v is not None:
            val = bool(v)
    if val is None:
        return _diag("tunnel", "Le tunnel media repond", GRIS, "non declare",
                     "Un tunnel mort ne produit aucune erreur visible : les "
                     "publications echouent en silence.", bloque=True,
                     provenance=NON_DECLARE, source="corps de /api/rig/pull",
                     correctif="joindre tunnel_repond (etapes/_commun.py:62)")
    if not val:
        return _diag("tunnel", "Le tunnel media repond", ROUGE, "non",
                     "Aucune publication ne peut aboutir.", bloque=True,
                     provenance=MESURE, source="corps de /api/rig/pull")
    return _diag("tunnel", "Le tunnel media repond", VERT, "oui",
                 "Les medias sont servis au telephone.", bloque=True,
                 provenance=MESURE, source="corps de /api/rig/pull")


def gf_pilotage_pendant_job(ctx) -> dict:
    """Regarder l'ecran pendant qu'un travail tourne EST la cause directe de
    la chute de WDA du 21/08 : la capture interroge le telephone pendant la
    purge. Le signal existait, la consequence n'avait jamais ete tiree."""
    actif = (ctx["now"] - ctx["pilotage_ts"]) < 25 if ctx["pilotage_ts"] else False
    travail = [j for j in ctx["jobs"]["jobs"] if j.get("etat") in ("pris", "en_cours")]
    if actif and travail:
        return _diag("pilotage", "Personne ne regarde l'ecran", ROUGE,
                     "pilotage actif pendant %d travail(s)" % len(travail),
                     "La capture d'ecran interroge WebDriverAgent pendant le "
                     "travail : c'est exactement ce qui l'a fait tomber toutes "
                     "les 20 secondes le 21/08. Fermer l'ecran de Remote.",
                     bloque=False, provenance=MESURE,
                     source="rig_pilotage.json + rig_jobs.json")
    if actif:
        return _diag("pilotage", "Personne ne regarde l'ecran", AMBRE,
                     "quelqu'un regarde",
                     "Le pilotage ecran est actif. Aucun travail ne tourne, "
                     "donc rien n'est menace — mais un lancement maintenant "
                     "ferait chuter WDA.", bloque=False, provenance=MESURE,
                     source="rig_pilotage.json")
    return _diag("pilotage", "Personne ne regarde l'ecran", VERT, "non",
                 "Aucune capture en cours.", bloque=False, provenance=MESURE,
                 source="rig_pilotage.json")


def gf_registre_reel(ctx) -> dict:
    """« 87 conteneurs pour 33 reels » venait d'un script qui cherchait une
    application disparue, et personne ne confrontait jamais le registre a la
    realite. Ce controle est cette confrontation."""
    declares = len(ctx["conteneurs"])
    inv = ctx["inventaire"]
    if not inv["present"]:
        return _diag("registre", "Le registre correspond au telephone", GRIS,
                     "%d declares / aucun releve" % declares,
                     "Aucun recensement reel n'a jamais ete pousse : le "
                     "registre n'est confronte a rien. C'est ce qui a produit "
                     "« 87 conteneurs pour 33 reels ».",
                     bloque=True, provenance=NON_DECLARE,
                     source="parc_inventaire.json (absent)",
                     action={"quoi": "recenser", "libelle": "Recenser"},
                     correctif="pousser inventaire_telephone.json (poste) vers "
                               "POST /parc/inventaire")
    reel = inv["nombre"]
    ecart_pct = 0 if not declares else int(round(100.0 * abs(declares - reel) / declares))
    seuil = int(ctx["regles"].get("seuil_ecart_registre") or 50)
    age_h = inv["age_s"] / 3600.0 if inv["age_s"] > 0 else 9999
    vieux = age_h > float(ctx["regles"].get("age_inventaire_h") or 24)
    if ecart_pct >= seuil:
        return _diag("registre", "Le registre correspond au telephone", ROUGE,
                     "%d declares / %d releves (%d %%)" % (declares, reel, ecart_pct),
                     "On lancerait %d cycles dans le vide." % max(0, declares - reel),
                     bloque=True, provenance=MESURE, source="parc_inventaire.json",
                     age_s=inv["age_s"],
                     action={"quoi": "recenser", "libelle": "Recenser"})
    if ecart_pct >= 10 or vieux:
        return _diag("registre", "Le registre correspond au telephone", AMBRE,
                     "%d / %d (%d %%)%s" % (declares, reel, ecart_pct,
                                            ", releve il y a %s" % duree_humaine(inv["age_s"])
                                            if inv["age_s"] > 0 else ""),
                     "Ecart tolerable, ou releve trop vieux pour etre cru.",
                     bloque=True, provenance=MESURE, source="parc_inventaire.json",
                     age_s=inv["age_s"],
                     action={"quoi": "recenser", "libelle": "Recenser"})
    return _diag("registre", "Le registre correspond au telephone", VERT,
                 "%d / %d" % (declares, reel),
                 "Le registre colle a la realite du telephone.", bloque=True,
                 provenance=MESURE, source="parc_inventaire.json", age_s=inv["age_s"])


def gf_stock_categorie(ctx) -> dict:
    """Une categorie a zero reel : tous les travaux de publication de cette
    categorie echoueront a l'etape des medias."""
    st = ctx["stock"]
    if not st["categories"]:
        return _diag("stock", "Il reste des medias dans chaque categorie", GRIS,
                     "non declare", st["note"], bloque=True,
                     provenance=NON_DECLARE, source="rig_parc.json > categories")
    if not st["lisible"]:
        brut = " | ".join((c.get("brut") or "")[:44] for c in st["categories"][:3])
        return _diag("stock", "Il reste des medias dans chaque categorie", GRIS,
                     "stock illisible", st["note"] + " Contenu brut : " + brut,
                     bloque=True, provenance=NON_DECLARE,
                     source="rig_parc.json > categories",
                     correctif="agent_rig.py:364 — envoyer les dict, pas str(x)")
    vides = [c["nom"] for c in st["categories"] if not (c.get("medias") or 0)]
    if vides:
        return _diag("stock", "Il reste des medias dans chaque categorie", ROUGE,
                     "vide : " + ", ".join(vides),
                     "Tous les passages de ces categories echoueraient a "
                     "l'etape des medias.", bloque=True, provenance=DERIVE,
                     source="rig_parc.json > categories")
    return _diag("stock", "Il reste des medias dans chaque categorie", VERT,
                 ", ".join("%s %s" % (c["nom"], c["medias"]) for c in st["categories"]),
                 "Chaque categorie visee a de quoi publier.", bloque=True,
                 provenance=DERIVE, source="rig_parc.json > categories")


def gf_pseudo_connu(ctx) -> dict:
    """AMBRE, JAMAIS ROUGE — l'arbitrage compte autant que le controle.

    Publier sur un compte precis n'existe pas : e8_reels.py ne rouvre pas le
    conteneur, il lit son nom seulement pour choisir le dossier de videos.
    Une publication peut donc partir sur le mauvais compte, sans erreur. Mais
    ce controle n'ecarte QUE les passages de PUBLICATION : les cycles de
    CREATION doivent partir, puisque c'est le cycle qui cree le pseudo. En
    rouge, le parc serait bloque pour toujours avec 1 pseudo sur 33.
    """
    tot = len(ctx["conteneurs"])
    avec = len([c for c in ctx["conteneurs"] if (c.get("pseudo") or "").strip()])
    if tot and avec == tot:
        return _diag("pseudo", "Les comptes vises ont un pseudo", VERT,
                     "%d / %d" % (avec, tot), "Chaque publication sait ou elle va.",
                     bloque=False, provenance=MESURE, source="rig_parc.conteneurs[].pseudo")
    return _diag("pseudo", "Les comptes vises ont un pseudo", AMBRE,
                 "%d / %d" % (avec, tot),
                 "Les PUBLICATIONS de ces comptes seront ecartees (elles "
                 "pourraient partir sur le mauvais compte) ; les CREATIONS "
                 "partent, puisque c'est le cycle qui cree le pseudo.",
                 bloque=False, provenance=MESURE,
                 source="rig_parc.conteneurs[].pseudo",
                 action={"quoi": "parc_sans_pseudo", "libelle": "Voir les %d" % (tot - avec)})


def gf_scenario_compatible(ctx) -> dict:
    """WebDriverAgent refuse desormais le locator « -ios predicate string » :
    un scenario qui en contient echouera systematiquement."""
    fautifs = []
    for s in ctx["scenarios"]["scenarios"]:
        try:
            txt = json.dumps(s.get("detail") or [], ensure_ascii=False)
        except Exception:
            continue
        if "predicate" in txt.lower():
            fautifs.append(s.get("nom") or "?")
    if fautifs:
        return _diag("scenario", "Aucun scenario refuse par le moteur", ROUGE,
                     ", ".join(fautifs[:4]),
                     "Ces scenarios contiennent « -ios predicate string », que "
                     "WebDriverAgent refuse : ils echoueront a chaque fois.",
                     bloque=True, provenance=MESURE, source="rig_scenarios.json",
                     action={"quoi": "editeur", "libelle": "Ouvrir l'editeur (Remote)"})
    if not ctx["scenarios"]["n"]:
        return _diag("scenario", "Aucun scenario refuse par le moteur", GRIS,
                     "aucun scenario declare",
                     "Le catalogue n'est declare qu'au demarrage de l'agent : "
                     "un scenario ajoute a la main n'apparait qu'au "
                     "relancement.", bloque=False, provenance=NON_DECLARE,
                     source="rig_scenarios.json")
    return _diag("scenario", "Aucun scenario refuse par le moteur", VERT,
                 "%d scenario(s)" % ctx["scenarios"]["n"],
                 "Aucun locator refuse par le moteur.", bloque=True,
                 provenance=MESURE, source="rig_scenarios.json",
                 age_s=ctx["scenarios"]["age_s"])


def gf_palette_actions(ctx) -> dict:
    """La console 8770 etait eteinte au dernier demarrage de l'agent :
    l'editeur propose une palette vide et on croit que le moteur ne sait plus
    rien faire. Le .prev en contenait 37 : la degradation est silencieuse."""
    n = ctx["actions"]["n"]
    if n < 10:
        return _diag("palette", "La palette d'actions est complete", AMBRE,
                     "%d action(s)" % n,
                     "Le .prev en contenait 37 : la console 8770 etait eteinte "
                     "au dernier demarrage de l'agent. L'editeur de scenarios "
                     "proposera une palette vide.", bloque=False,
                     provenance=MESURE, source="rig_actions.json",
                     age_s=ctx["actions"]["age_s"])
    return _diag("palette", "La palette d'actions est complete", VERT,
                 "%d actions" % n, "Le moteur declare toutes ses actions.",
                 bloque=False, provenance=MESURE, source="rig_actions.json",
                 age_s=ctx["actions"]["age_s"])


def gf_donnees_fraiches(ctx) -> dict:
    """A 5 machines, l'age d'un chiffre compte autant que le chiffre. Decider
    sur des donnees de 26 minutes en les croyant fraiches est une faute que
    l'ecran actuel rend invisible."""
    seuil = int(ctx["regles"].get("age_donnees_min") or 10) * 60
    age = max(ctx["parc"]["age_s"], ctx["jobs"]["battement_age_s"],
              ctx["actions"]["age_s"])
    if age < 0:
        return _diag("fraicheur", "Les donnees ne sont pas perimees", GRIS,
                     "aucune donnee", "Rien n'est encore arrive du poste.",
                     bloque=False, provenance=NON_DECLARE, source="rig_*.json")
    if age > seuil:
        return _diag("fraicheur", "Les donnees ne sont pas perimees", AMBRE,
                     duree_humaine(age),
                     "Ces chiffres peuvent etre faux. On peut demarrer, mais en "
                     "le sachant.", bloque=False, provenance=MESURE,
                     source="rig_parc.ts / battement / rig_actions.ts", age_s=age,
                     action={"quoi": "recharger", "libelle": "Recharger"})
    return _diag("fraicheur", "Les donnees ne sont pas perimees", VERT,
                 duree_humaine(age), "Les chiffres affiches sont recents.",
                 bloque=False, provenance=MESURE, source="rig_*.json", age_s=age)


def gf_un_job_par_machine(ctx) -> dict:
    """Un iPhone n'a qu'un WebDriverAgent : deux travaux simultanes sur le
    meme telephone se marchent dessus."""
    actifs = [j for j in ctx["jobs"]["jobs"] if j.get("etat") in ("pris", "en_cours")]
    n_machines = max(1, len(ctx["machines"]))
    # APPARIER, et pas seulement compter : deux travaux sur poste-3 pendant
    # que poste-1 dort, c'est « 2 travaux pour 2 machines » — le controle
    # passait au vert sur exactement la panne qu'il est cense voir.
    par_machine = {}
    sans = 0
    for j in actifs:
        m = machine_du_job(j, ctx["hist"])
        if m:
            par_machine[m] = par_machine.get(m, 0) + 1
        else:
            sans += 1
    empiles = ["%s : %d travaux" % (m, n) for m, n in sorted(par_machine.items()) if n > 1]
    if empiles:
        return _diag("un_job_machine", "Un seul travail a la fois par machine",
                     ROUGE, ", ".join(empiles),
                     "Deux travaux tournent sur le meme telephone : ils se "
                     "disputent WebDriverAgent.", bloque=True, provenance=MESURE,
                     source="rig_jobs.json apparie au pull")
    if len(actifs) > n_machines:
        return _diag("un_job_machine", "Un seul travail a la fois par machine",
                     ROUGE, "%d travaux pour %d machine(s)" % (len(actifs), n_machines),
                     "Plus de travaux actifs que de telephones : au moins deux "
                     "se disputent WebDriverAgent.", bloque=True, provenance=DERIVE,
                     source="rig_jobs.json")
    if sans:
        # ○ et non vert : on ne peut pas apparier, donc on ne peut pas
        # conclure. « Je ne sais pas » et « tout va bien » ne se ressemblent
        # pas — et c'est le garde-fou de la panne fondatrice.
        return _diag("un_job_machine", "Un seul travail a la fois par machine",
                     GRIS, "%d travail(x) sans machine declaree" % sans,
                     "Aucun pull n'a revendique ces travaux : impossible de "
                     "verifier qu'ils sont sur des telephones differents. "
                     "L'agent doit joindre {machine} au corps de /api/rig/pull.",
                     bloque=True, provenance=NON_DECLARE,
                     source="rig_jobs.json apparie au pull",
                     correctif="agent_rig.py — joindre le nom de machine au pull")
    return _diag("un_job_machine", "Un seul travail a la fois par machine", VERT,
                 "%d travail(s) / %d machine(s)" % (len(actifs), n_machines),
                 "Aucun empilement : chaque travail actif est sur un telephone "
                 "distinct.", bloque=True, provenance=MESURE,
                 source="rig_jobs.json apparie au pull")


def gf_un_job_par_conteneur(ctx) -> dict:
    """Rien n'empeche aujourd'hui deux travaux de viser ig-445bt en meme
    temps. Le refus doit etre NOMME, pas silencieux."""
    vus, doublons = {}, []
    for j in ctx["jobs"]["jobs"]:
        if j.get("etat") in ("fini", "echec", "annule"):
            continue
        c = (j.get("conteneur") or "").strip()
        if not c:
            continue
        if c in vus:
            doublons.append("%s (%s + %s)" % (c, vus[c], j.get("id")))
        else:
            vus[c] = j.get("id")
    if doublons:
        return _diag("un_job_conteneur", "Un seul travail a la fois par conteneur",
                     ROUGE, "%d doublon(s)" % len(doublons), "; ".join(doublons[:3]),
                     bloque=True, provenance=DERIVE, source="rig_jobs.json")
    return _diag("un_job_conteneur", "Un seul travail a la fois par conteneur",
                 VERT, "aucun doublon", "Chaque conteneur n'a qu'un travail en file.",
                 bloque=True, provenance=DERIVE, source="rig_jobs.json")


def gf_travail_absurde(ctx) -> dict:
    """Le « qui n'a aucun sens » du proprietaire, en CINQ motifs distincts,
    chacun compte separement dans Ecarts : conteneur abandonne, sans pseudo
    pour une publication, categorie a zero reel, absent de l'inventaire reel,
    ou en quarantaine."""
    motifs = {}
    inv = set(ctx["inventaire"]["conteneurs"] or [])
    quar = set((ctx["etat"].get("quarantaine") or {}).keys())
    sans_cat = ctx["regles"].get("sans_categorie") == "refuser"
    for c in ctx["conteneurs"]:
        nom = c.get("nom") or ""
        if c.get("abandonne"):
            motifs["abandonne"] = motifs.get("abandonne", 0) + 1
        elif nom in quar:
            motifs["quarantaine"] = motifs.get("quarantaine", 0) + 1
        elif sans_cat and not (c.get("categorie") or "").strip():
            motifs["sans_categorie"] = motifs.get("sans_categorie", 0) + 1
        elif inv and nom not in inv:
            motifs["conteneur_introuvable"] = motifs.get("conteneur_introuvable", 0) + 1
    n = sum(motifs.values())
    total = len(ctx["conteneurs"]) or 1
    txt = ", ".join("%s x%d" % (k, v) for k, v in sorted(motifs.items(), key=lambda kv: -kv[1]))
    if n and n >= total:
        return _diag("absurde", "Refuser le travail qui n'a aucun sens", ROUGE,
                     "%d / %d ecartes" % (n, total),
                     "Aucun conteneur n'est lancable : " + txt, bloque=True,
                     provenance=DERIVE, source="rig_parc.json + inventaire + quarantaine")
    if n:
        return _diag("absurde", "Refuser le travail qui n'a aucun sens", AMBRE,
                     "%d / %d ecartes" % (n, total),
                     "Ces conteneurs seront refuses et comptes dans Ecarts : " + txt,
                     bloque=True, provenance=DERIVE,
                     source="rig_parc.json + inventaire + quarantaine",
                     action={"quoi": "ecarts", "libelle": "Voir les ecarts"})
    return _diag("absurde", "Refuser le travail qui n'a aucun sens", VERT,
                 "0 ecarte", "Tous les conteneurs declares sont lancables.",
                 bloque=True, provenance=DERIVE, source="rig_parc.json")


def gf_captcha(ctx) -> dict:
    """L'ecran « confirm that you're human » est archive comme une REUSSITE
    (« fil atteint ») : l'historique de succes est partiellement faux."""
    bloques = [c.get("nom") for c in ctx["conteneurs"] if c.get("statut") == "bloque"]
    if bloques:
        return _diag("captcha", "Aucun compte en verification humaine", AMBRE,
                     "%d compte(s)" % len(bloques),
                     "Instagram demande une verification humaine sur : %s. Ces "
                     "comptes partent en quarantaine — les relancer ne fait que "
                     "confirmer le blocage." % ", ".join(bloques[:4]),
                     bloque=False, provenance=MESURE,
                     source="rig_parc.conteneurs[].statut = bloque")
    return _diag("captcha", "Aucun compte en verification humaine", VERT, "0",
                 "Aucun ecran de verification signale.", bloque=False,
                 provenance=MESURE, source="rig_parc.conteneurs[].statut")


def gf_succes_court(ctx) -> dict:
    """Un travail « fini » en moins de 4 min alors qu'un passage reel dure
    8 min 54 : un ecran inattendu a ete valide comme un succes."""
    seuil = int(ctx["regles"].get("succes_court_min") or 4) * 60
    douteux = [j for j in (ctx["hist"].get("jobs") or {}).values()
               if j.get("douteux") and (ctx["now"] - (j.get("vu") or 0)) < 86400]
    if douteux:
        return _diag("douteux", "Les reussites sont credibles", AMBRE,
                     "%d reussite(s) douteuse(s) en 24 h" % len(douteux),
                     "Finies en moins de %s : comptees a part, la courbe de "
                     "reussite trace deux lignes (brute et verifiee) pour que "
                     "l'ecart se voie." % duree_humaine(seuil),
                     bloque=False, provenance=DERIVE, source="durees derivees")
    return _diag("douteux", "Les reussites sont credibles", VERT, "0 en 24 h",
                 "Aucune reussite anormalement rapide.", bloque=False,
                 provenance=DERIVE, source="durees derivees")


def gf_job_fige(ctx) -> dict:
    """Un travail reste « pris » pour toujours parce que l'agent est mort
    entre-temps. Le timeout de lancer() cote poste est de 900 s."""
    seuil = int(ctx["regles"].get("job_fige_min") or 15) * 60
    figes = []
    for j in ctx["jobs"]["jobs"]:
        if j.get("etat") not in ("pris", "en_cours"):
            continue
        ref = j.get("maj") or j.get("pris_a") or 0
        if ref and (ctx["now"] - float(ref)) > seuil:
            figes.append(j)
    if figes:
        return _diag("fige", "Aucun travail fige", ROUGE, "%d travail(s)" % len(figes),
                     "Pris depuis plus de %s sans nouvelle : l'agent est mort. "
                     "Degripper les passe en echec agent_disparu (si l'agent "
                     "rapporte plus tard, le journal gardera les deux entrees — "
                     "c'est voulu)." % duree_humaine(seuil),
                     bloque=False, provenance=DERIVE, source="rig_jobs.json",
                     action={"quoi": "degripper", "libelle": "Degripper"})
    return _diag("fige", "Aucun travail fige", VERT, "0",
                 "Aucun travail bloque a l'etat « pris ».", bloque=False,
                 provenance=DERIVE, source="rig_jobs.json")


def gf_arret_urgence(ctx) -> dict:
    """Une cause unique qui produit 100 % d'echecs pendant des heures sans
    que rien ne s'arrete — la nuit du 21/08 entiere."""
    n = int(ctx["regles"].get("pause_si_echecs") or 5)
    fen = int(ctx["regles"].get("pause_si_minutes") or 30) * 60
    recents = [j for j in (ctx["hist"].get("jobs") or {}).values()
               if j.get("etat") == "echec" and (ctx["now"] - (j.get("vu") or 0)) < fen]
    if len(recents) >= n:
        codes = {}
        for j in recents:
            codes[j.get("code") or "inconnu"] = codes.get(j.get("code") or "inconnu", 0) + 1
        dominant = sorted(codes.items(), key=lambda kv: -kv[1])[0]
        return _diag("urgence", "Pas d'echecs en rafale", ROUGE,
                     "%d echecs en %s" % (len(recents), duree_humaine(fen)),
                     "Cause dominante : %s (%dx). Le parc doit passer en pause ; "
                     "les travaux en attente sont geles, pas annules."
                     % (dominant[0], dominant[1]),
                     bloque=True, provenance=DERIVE, source="journal derive",
                     action={"quoi": "pause", "libelle": "Mettre le parc en pause"})
    return _diag("urgence", "Pas d'echecs en rafale", VERT,
                 "%d echec(s) en %s" % (len(recents), duree_humaine(fen)),
                 "Sous le seuil d'arret d'urgence (%d)." % n, bloque=True,
                 provenance=DERIVE, source="journal derive")


def gf_repetition_media(ctx) -> dict:
    """15 reels en stock pour un objectif de 300 publications par jour :
    chaque video repart 20 a 40 fois. Le proprietaire l'accepte — le passage
    PART, mais chaque violation est comptee."""
    st = ctx["stock"]
    reels = sum(c.get("medias") or 0 for c in st["categories"]) if st["lisible"] else None
    besoin = (int(ctx["regles"].get("objectif_total") or 0)
              * int(ctx["regles"].get("reels_par_passage") or 0)
              * _passages_par_jour(ctx["regles"]))
    if reels is None:
        return _diag("repetition", "Le stock supporte la cadence", GRIS,
                     "stock illisible",
                     "Le poste ne declare pas un stock exploitable (dict "
                     "tronques). Mesure a la main le 21/08 : 15 reels pour "
                     "%d publications par jour." % besoin, bloque=False,
                     provenance=NON_DECLARE, source="rig_parc.json > categories")
    if reels and besoin and besoin / max(1, reels) > 1:
        return _diag("repetition", "Le stock supporte la cadence", AMBRE,
                     "chaque video rejouee %dx / jour" % round(besoin / max(1, reels)),
                     "La regle de repos sera violee a chaque passage : ces "
                     "passages partiront (vous l'avez valide) et seront comptes "
                     "dans Ecarts.", bloque=False, provenance=DERIVE,
                     source="stock declare / objectif")
    return _diag("repetition", "Le stock supporte la cadence", VERT,
                 "%s medias" % reels, "Le stock couvre la cadence demandee.",
                 bloque=False, provenance=DERIVE, source="stock declare / objectif")


def gf_fenetre_tenable(ctx) -> dict:
    """La fenetre 10 h - 13 h n'absorbe qu'une fraction des passages. On ne
    dit jamais « non » au proprietaire : on lui montre l'arithmetique."""
    t = tuile_fenetre(ctx["regles"], ctx)
    grav = {"ok": VERT, "tendu": AMBRE, "impossible": ROUGE}.get(t["verdict"], GRIS)
    return _diag("fenetre", "La fenetre horaire absorbe le plan", grav, t["valeur"],
                 t["phrase"], bloque=False, provenance=t["provenance"],
                 source="reglages + duree de passage",
                 action={"quoi": "reglages", "libelle": "Ouvrir les reglages"})


def gf_course_fichier(ctx) -> dict:
    """Remote 2 et /api/rig/pull ecriraient rig_jobs.json sans verrou
    partage : une mise a jour perdue ferait disparaitre un travail sans
    laisser de trace. Aucun des angles d'analyse ne l'avait vue."""
    perdus = [l for l in _lignes_fin(JOURNAL_FILE, 2000)
              if l.get("code") == "course_file" and ctx["now"] - (l.get("ts") or 0) < 86400]
    if perdus:
        return _diag("course", "Aucune ecriture perdue sur la file", AMBRE,
                     "%d course(s) en 24 h" % len(perdus),
                     "Une inscription a disparu apres ecriture et a ete refaite. "
                     "Si cela se repete, c'est que deux ecrivains se marchent "
                     "dessus.", bloque=False, provenance=DERIVE, source="journal")
    return _diag("course", "Aucune ecriture perdue sur la file", VERT, "0",
                 "Aucune inscription perdue detectee : chaque travail inscrit "
                 "par l'ordonnanceur a bien ete relu dans la file apres "
                 "ecriture.",
                 bloque=False, provenance=DERIVE, source="journal")


def gf_plafonds(ctx) -> dict:
    """Tout ecartement silencieux : 200 conteneurs declares au maximum, 80
    travaux gardes, 40 rendus, 120 etapes de scenario. A 5 machines x 50
    comptes, la troncature commence EN SILENCE."""
    atteints = []
    if ctx["parc"]["plafond_atteint"]:
        atteints.append("le poste plafonne sa declaration a 200 conteneurs")
    if ctx["jobs"]["plafond_atteint"]:
        atteints.append("la file ne garde que 80 travaux (l'historique du jour "
                        "est deja perdu)")
    incomplets = [s.get("nom") for s in ctx["scenarios"]["scenarios"]
                  if not s.get("complet")]
    if incomplets:
        atteints.append("scenario(s) tronque(s) a 120 etapes : "
                        + ", ".join(str(x) for x in incomplets[:3]))
    if atteints:
        return _diag("plafonds", "Aucun plafond atteint", AMBRE,
                     "%d plafond(s)" % len(atteints), " · ".join(atteints),
                     bloque=False, provenance=MESURE, source="rig_*.json")
    return _diag("plafonds", "Aucun plafond atteint", VERT, "aucun",
                 "Aucune troncature en cours.", bloque=False, provenance=MESURE,
                 source="rig_*.json")


# L'ordre compte : c'est celui du pre-vol a l'ecran, du plus bloquant au
# plus informatif.
GARDEFOUS = [
    gf_agent_unique, gf_poste_repond, gf_hors_file, gf_wda_repond,
    gf_wda_stable, gf_tunnel, gf_pilotage_pendant_job, gf_registre_reel,
    gf_stock_categorie, gf_pseudo_connu, gf_scenario_compatible,
    gf_palette_actions, gf_donnees_fraiches, gf_un_job_par_machine,
    gf_un_job_par_conteneur, gf_travail_absurde, gf_captcha, gf_succes_court,
    gf_job_fige, gf_arret_urgence, gf_repetition_media, gf_fenetre_tenable,
    gf_course_fichier, gf_plafonds,
]


def prevol(ctx: dict = None) -> dict:
    """Passe TOUS les garde-fous et rend le pre-vol complet.

    Un controle qui plante ne disparait pas : il devient un diagnostic GRIS
    « controle en erreur », compte comme les autres. Ecarter un controle en
    silence serait la pire des issues — on croirait avoir 24 verifications
    quand on n'en aurait que 23.
    """
    ctx = ctx or contexte()
    controles, erreurs = [], []
    for fn in GARDEFOUS:
        try:
            d = fn(ctx)
            if not isinstance(d, dict):
                raise TypeError("diagnostic non conforme")
        except Exception as e:
            d = _diag(getattr(fn, "__name__", "?"), getattr(fn, "__name__", "?"),
                      GRIS, "controle en erreur",
                      "%s: %s" % (type(e).__name__, str(e)[:120]),
                      provenance=NON_DECLARE, source="parc_web.%s" % fn.__name__)
            erreurs.append(fn.__name__)
        controles.append(d)
    rouges = [d for d in controles if d["gravite"] == ROUGE]
    ambres = [d for d in controles if d["gravite"] == AMBRE]
    gris = [d for d in controles if d["gravite"] == GRIS]
    bloquants = [d for d in rouges if d["bloque"]]
    correctifs = sorted({d["correctif"] for d in controles if d.get("correctif")})
    return {
        "controles": controles,
        "total": len(controles),
        "verts": len([d for d in controles if d["gravite"] == VERT]),
        "ambres": len(ambres), "rouges": len(rouges), "gris": len(gris),
        "bloquants": [d["nom"] for d in bloquants],
        "peut_demarrer": not bloquants,
        "erreurs_de_controle": erreurs,
        # « 9 indicateurs sont ○ non declares — 6 correctifs cote poste les
        # rendraient ● » : la ligne de pied du pre-vol, en une donnee.
        "non_declares": len([d for d in controles
                             if d["provenance"] == NON_DECLARE]),
        "correctifs_poste": correctifs,
        "calcule_le": int(maintenant()),
    }


# ==================================================================
# 9. LE PLANIFICATEUR — fonctions PURES : quoi faire, et quand
# ==================================================================
# Il ne touche RIEN. Il lit les reglages et l'etat du parc, et rend une
# decision lisible : ce qui serait inscrit maintenant, ce qui attend son
# heure, et ce qui est refuse AVEC SON MOTIF. On peut donc le verifier a
# l'oeil (GET /parc/plan) avant de lui donner la main sur la file.


def _passages_par_jour(regles: dict) -> int:
    """Combien de fois par jour un meme compte passe.

    « Toutes les dix douze heures » = 2 passages par jour. C'est ce chiffre
    qui transforme « 6 reels par passage » en « 600 publications par jour »,
    et c'est pour cela qu'il est calcule ici une seule fois."""
    mini = max(1, int(regles.get("intervalle_min_h") or 10))
    return max(1, int(24 // mini))


def fenetres_minutes(regles: dict) -> list:
    """Les fenetres en minutes depuis minuit, triees et fusionnees."""
    out = []
    for f in (regles.get("fenetres") or []):
        try:
            a, b = _hhmm(f[0], -1), _hhmm(f[1], -1)
        except Exception:
            continue
        if a < 0 or b <= a:
            continue
        out.append((a, b))
    out.sort()
    fusion = []
    for a, b in out:
        if fusion and a <= fusion[-1][1]:
            fusion[-1] = (fusion[-1][0], max(fusion[-1][1], b))
        else:
            fusion.append((a, b))
    return fusion


def minutes_utiles(regles: dict) -> int:
    """Le total de minutes ouvrables par jour, maintenance deduite.

    POURQUOI deduire la maintenance : c'est elle qui rend la tuile Fenetre
    honnete. Une fenetre de 3 h dont 20 min de maintenance n'en fait pas 3."""
    tot = sum(b - a for a, b in fenetres_minutes(regles))
    try:
        ma, mb = _hhmm(regles["maintenance"][0]), _hhmm(regles["maintenance"][1])
    except Exception:
        return tot
    perdu = 0
    for a, b in fenetres_minutes(regles):
        perdu += max(0, min(b, mb) - max(a, ma))
    return max(0, tot - perdu)


def jour_actif(regles: dict, quand: float) -> bool:
    """Lundi = 0. Un parc qui s'arrete le week-end se voit : c'est un
    reglage, pas un hasard."""
    jours = regles.get("jours") or [True] * 7
    try:
        return bool(jours[datetime.fromtimestamp(quand).weekday()])
    except Exception:
        return True


def en_maintenance(regles: dict, quand: float) -> bool:
    """La pause quotidienne : le recensement reel et le redemarrage de WDA
    doivent tomber quand rien ne publie."""
    try:
        a, b = _hhmm(regles["maintenance"][0]), _hhmm(regles["maintenance"][1])
    except Exception:
        return False
    m = _minute_du_jour(quand)
    return a <= m < b if b > a else (m >= a or m < b)


def dans_fenetre(regles: dict, quand: float) -> bool:
    """Le parc a-t-il le droit de travailler a cet instant precis ?"""
    if not jour_actif(regles, quand) or en_maintenance(regles, quand):
        return False
    m = _minute_du_jour(quand)
    return any(a <= m < b for a, b in fenetres_minutes(regles))


def prochaine_ouverture(regles: dict, depuis: float) -> float:
    """Le prochain instant ou le parc pourra travailler.

    Cherche sur 14 jours puis abandonne : au-dela, c'est que tous les jours
    sont decoches ou qu'aucune fenetre n'est valide — et le refus doit alors
    etre visible, pas une boucle infinie.
    """
    fens = fenetres_minutes(regles)
    if not fens:
        return 0.0
    t = depuis
    for _ in range(14 * len(fens) + 14):
        jour0 = _debut_du_jour(t)
        if jour_actif(regles, t):
            m = _minute_du_jour(t)
            for a, b in fens:
                if m < b:
                    cible = jour0 + max(a, m) * 60
                    if not en_maintenance(regles, cible):
                        return cible
        t = _debut_du_jour(t) + 86400 + 60      # le lendemain, minuit passe
    return 0.0


def _index_stable(cle: str, n: int) -> int:
    """Un index dans [0, n[ toujours le meme pour la meme cle.

    Sert a « une machine par categorie » : le tirage doit tenir d'un tour a
    l'autre, sinon la categorie beta changerait de telephone toutes les
    minutes et l'attribution ne voudrait plus rien dire.
    """
    if n <= 1:
        return 0
    h = hashlib.sha1(str(cle).encode("utf-8")).hexdigest()[:8]
    return int(h, 16) % int(n)


def decalage(nom: str, jitter_min: int) -> int:
    """Le decalage propre a un compte, en secondes. STABLE : le meme
    conteneur a toujours le meme decalage.

    POURQUOI stable et pas aleatoire : un jitter tire a chaque tick ferait
    danser toutes les heures d'echeance d'un tour a l'autre, et le ruban de
    24 h afficherait un futur different toutes les minutes. 50 comptes qui
    publient a la meme minute restent une signature exploitable — le
    decalage doit exister, mais il doit tenir.
    """
    if jitter_min <= 0:
        return 0
    h = hashlib.sha1(str(nom).encode("utf-8")).hexdigest()[:8]
    return int(h, 16) % (int(jitter_min) * 60)


def derniere_activite(hist: dict, nom: str) -> int:
    """Quand ce compte a-t-il bouge pour la derniere fois ? 0 = jamais vu
    bouger depuis l'installation de l'observateur (et on le dit)."""
    e = (hist.get("conteneurs") or {}).get(nom) or {}
    return int(max(e.get("passages_le") or 0, e.get("statut_le") or 0,
                   e.get("etapes_le") or 0))


def echeance(nom: str, hist: dict, regles: dict) -> tuple:
    """(instant du prochain passage, en_retard, raison lisible).

    Trois cas seulement, et chacun s'explique en une phrase a l'ecran :
    jamais vu passer -> tout de suite (avec son decalage) ; passe
    recemment -> derniere activite + intervalle minimum ; pas passe depuis
    plus que l'intervalle maximum -> en retard, remonte en tete.
    """
    mini = int(regles.get("intervalle_min_h") or 10) * 3600
    maxi = int(regles.get("intervalle_max_h") or 12) * 3600
    dec = decalage(nom, int(regles.get("jitter_min") or 0))
    der = derniere_activite(hist, nom)
    now = maintenant()
    if not der:
        return (now + dec, False, "jamais vu passer depuis l'installation")
    du = der + mini + dec
    if now - der > maxi:
        return (now, True, "en retard de %s sur l'intervalle maximum"
                % duree_humaine(now - der - maxi))
    return (du, False, "dernier passage il y a %s" % duree_humaine(now - der))


def refus_conteneur(c: dict, ctx: dict) -> tuple:
    """Faut-il refuser ce conteneur, et pourquoi ? (motif|None, detail).

    CINQ motifs distincts, chacun compte separement dans Ecarts avec sa
    conduite a tenir — parce que « 12 refus » ne dit rien et « 12 refus
    faute de categorie » dit quoi corriger.
    """
    nom = (c.get("nom") or "").strip()
    regles = ctx["regles"]
    if not nom:
        return ("inconnu", "conteneur sans nom dans la declaration du poste")
    if c.get("abandonne"):
        return ("abandonne", "marque abandonne dans le registre du poste")
    if nom in (ctx["etat"].get("quarantaine") or {}):
        q = (ctx["etat"]["quarantaine"] or {}).get(nom) or {}
        age_q = _age(q.get("depuis"))
        # `sortie_quarantaine` etait declare, explique... et lu par personne :
        # « auto24h » ne liberait jamais rien. Le defaut reste « manuel »
        # (un compte bloque par Instagram ne se debloque pas tout seul), mais
        # choisir auto24h a maintenant un effet.
        if regles.get("sortie_quarantaine") == "auto24h" and age_q >= 24 * 3600:
            pass                    # la quarantaine a expire : on ne refuse plus
        else:
            return ("quarantaine", "en quarantaine depuis %s (%s)"
                    % (duree_humaine(age_q), q.get("motif") or "?"))
    if not (c.get("categorie") or "").strip() and regles.get("sans_categorie") == "refuser":
        return ("sans_categorie", "aucune categorie : l'etape des medias "
                                  "echouerait, et /api/rig/jobs le refuse deja")
    inv = ctx["inventaire"]
    if inv["present"] and inv["conteneurs"] and nom not in inv["conteneurs"]:
        return ("conteneur_introuvable",
                "absent du dernier recensement reel (%s)" % (inv["releve_le"] or "?"))
    echecs = ((ctx["hist"].get("conteneurs") or {}).get(nom) or {}).get("echecs") or []
    seuil = int(regles.get("echecs_quarantaine") or 3)
    if len(echecs) >= seuil and all(ctx["now"] - t < 7 * 86400 for t in echecs[-seuil:]):
        return ("quarantaine", "%d echecs consecutifs (seuil %d)" % (len(echecs), seuil))
    return (None, "")


def type_de_travail(c: dict) -> str:
    """« creation » tant que le compte n'a pas de pseudo, « publication »
    ensuite.

    POURQUOI : publier sur un compte precis n'existe pas (e8_reels.py ne
    rouvre pas le conteneur, il lit son nom pour choisir le dossier de
    videos). Sans pseudo, une publication peut donc partir sur le mauvais
    compte, sans erreur — alors qu'un cycle de creation, lui, doit partir :
    c'est lui qui cree le pseudo.
    """
    return "publication" if (c.get("pseudo") or "").strip() else "creation"


def planifier(ctx: dict = None, horizon_h: int = 24) -> dict:
    """LE planificateur. Rend une decision complete et VERIFIABLE.

    Sortie :
      a_inscrire : ce qui partirait MAINTENANT (au plus `lot_par_tick`) ;
      a_venir    : ce qui attend son heure, avec l'instant prevu ;
      refus      : ce qui est ecarte, motif par motif ;
      resume     : les comptes — dus, programmes, refuses, machines libres,
                   et le nombre de lignes masquees. Aucun slice() muet.

    RIEN N'EST ECRIT : ni la file, ni les ecarts. Cette fonction est pure
    au sens ou deux appels de suite rendent la meme chose.
    """
    ctx = ctx or contexte()
    regles, hist = ctx["regles"], ctx["hist"]
    now = ctx["now"]
    lot = int(regles.get("lot_par_tick") or 3)
    dus, a_venir, refus = [], [], []
    par_motif = {}

    # Machines libres : une seule tache a la fois par telephone (contrainte
    # physique, cadenassee dans les reglages).
    #
    # `occupees.add(MACHINE_DEFAUT)` attribuait TOUT travail en cours a
    # poste-1 : a deux telephones, un travail tournant sur poste-3 laissait
    # poste-3 dans `libres`, qui recevait un second travail — deux scripts
    # sur le meme WebDriverAgent, c'est-a-dire la panne fondatrice du 21/08
    # recreee par l'ordonnanceur lui-meme.
    occupees, inconnues = set(), 0
    for j in ctx["jobs"]["jobs"]:
        if j.get("etat") in ("pris", "en_cours"):
            m = machine_du_job(j, ctx["hist"])
            if m:
                occupees.add(m)
            else:
                inconnues += 1
    libres = [m for m in ctx["machines"]
              if m["etat"] == "attente" and not m["suspendue"]
              and m["nom"] not in occupees]
    # Un travail en cours dont on ignore la machine peut etre sur N'IMPORTE
    # laquelle : on retire autant de machines libres qu'il y a de travaux non
    # attribues. Prudent par choix — se tromper ici, c'est empiler deux
    # agents sur un telephone.
    bride_par_inconnues = 0
    if inconnues:
        bride_par_inconnues = min(inconnues, len(libres))
        libres = libres[bride_par_inconnues:]
    en_file = {(j.get("conteneur") or "") for j in ctx["jobs"]["jobs"]
               if j.get("etat") not in ("fini", "echec", "annule")}

    for c in ctx["conteneurs"]:
        nom = (c.get("nom") or "").strip()
        motif, detail = refus_conteneur(c, ctx)
        if motif:
            refus.append({"conteneur": nom, "motif": motif, "detail": detail,
                          "conduite": conduite(motif)})
            par_motif[motif] = par_motif.get(motif, 0) + 1
            continue
        genre = type_de_travail(c)
        if genre == "publication" and not (c.get("pseudo") or "").strip():
            refus.append({"conteneur": nom, "motif": "pseudo_discordant",
                          "detail": "publication sans pseudo connu",
                          "conduite": conduite("pseudo_discordant")})
            par_motif["pseudo_discordant"] = par_motif.get("pseudo_discordant", 0) + 1
            continue
        if nom in en_file:
            refus.append({"conteneur": nom, "motif": "doublon",
                          "detail": "un travail vise deja ce conteneur",
                          "conduite": conduite("doublon")})
            par_motif["doublon"] = par_motif.get("doublon", 0) + 1
            continue
        du, retard, raison = echeance(nom, hist, regles)
        hors = not dans_fenetre(regles, du)
        if hors:
            if regles.get("hors_fenetre") == "abandonner":
                refus.append({"conteneur": nom, "motif": "hors_fenetre",
                              "detail": "du a %s, hors fenetre — abandonne"
                                        % datetime.fromtimestamp(du).strftime("%H:%M"),
                              "conduite": conduite("hors_fenetre")})
                par_motif["hors_fenetre"] = par_motif.get("hors_fenetre", 0) + 1
                continue
            suivant = prochaine_ouverture(regles, du)
            if not suivant:
                refus.append({"conteneur": nom, "motif": "hors_fenetre",
                              "detail": "aucune fenetre ouverte dans les 14 jours",
                              "conduite": "elargir la fenetre ou reactiver un jour"})
                par_motif["hors_fenetre"] = par_motif.get("hors_fenetre", 0) + 1
                continue
            raison += " — reporte a l'ouverture de %s" % \
                datetime.fromtimestamp(suivant).strftime("%d/%m %H:%M")
            du = suivant
            par_motif["hors_fenetre_reporte"] = par_motif.get("hors_fenetre_reporte", 0) + 1
        entree = {"conteneur": nom, "categorie": (c.get("categorie") or "").strip()
                  or regles.get("categorie_defaut"), "type": genre,
                  "du_a": int(du), "retard": bool(retard), "raison": raison,
                  "heure": datetime.fromtimestamp(du).strftime("%d/%m %H:%M"),
                  "passages": int(c.get("passages") or 0)}
        (dus if du <= now + int(regles.get("tick_s") or 60) else a_venir).append(entree)

    # Ordre de passage : le plus en retard d'abord par defaut — a 250
    # comptes, le vrai risque est qu'un compte soit muet trois jours.
    mode = regles.get("ordre") or "retard"
    if mode == "moins_passages":
        cle = lambda e: (e["passages"], e["du_a"])
    elif mode == "aleatoire":
        cle = lambda e: decalage(e["conteneur"], 1440)
    elif mode == "registre":
        cle = lambda e: e["conteneur"]
    else:
        cle = lambda e: (0 if e["retard"] else 1, e["du_a"])
    dus.sort(key=cle)
    a_venir.sort(key=lambda e: e["du_a"])

    # Attribution : une seule tache par machine — c'est physique, pas
    # negociable. La STRATEGIE, elle, est un reglage : `machines_strategie`
    # etait declare, explique, et lu par personne (`libres.pop(0)` prenait
    # toujours la premiere machine de la liste, c'est-a-dire la plus
    # silencieuse — jamais la moins chargee).
    strategie = str(regles.get("machines_strategie") or "moins_chargee")
    jour0 = _debut_du_jour(now)
    charge = {}
    for e_hist in (hist.get("jobs") or {}).values():
        if float(e_hist.get("vu") or 0) < jour0:
            continue
        m = str(e_hist.get("machine") or "")
        if m:
            charge[m] = charge.get(m, 0) + 1
    if strategie == "moins_chargee":
        # Le nom en second : a charge egale, un ordre STABLE evite que deux
        # affichages successifs proposent deux attributions differentes.
        libres.sort(key=lambda m: (charge.get(m["nom"], 0), m["nom"]))
    elif strategie == "par_categorie":
        # Une machine par categorie, choisie de facon deterministe : la
        # panne d'un poste arrete alors UNE categorie, pas tout le parc —
        # c'est le compromis que le reglage annonce.
        libres.sort(key=lambda m: m["nom"])
    # « manuel » : on ne reordonne rien, l'ordre de machines_liste fait foi.

    # AVANT que la boucle ne les consomme : « machines_libres » tout court
    # etait compte APRES les pop() et valait donc « ce qu'il reste », pas
    # « ce qui etait disponible ». Deux nombres, deux noms.
    libres_avant = len(libres)

    a_inscrire = []
    for e in dus[:lot]:
        if not libres:
            break
        if strategie == "par_categorie" and len(libres) > 1:
            m = libres.pop(_index_stable(e.get("categorie") or "", len(libres)))
        else:
            m = libres.pop(0)
        e = dict(e, machine=m["nom"])
        a_inscrire.append(e)

    # ---------------------------------------------------------------
    # L'ECART A LA CIBLE — dans les DEUX sens, et sans depasser le total.
    #
    # L'ancien calcul ne voyait que les deficits et ignorait les conteneurs
    # SANS categorie. Sur la phrase exacte du proprietaire (50 conteneurs,
    # 20 beta, 30 test) contre la realite (beta 18, test 8, 9 sans
    # categorie), il demandait 18 + 8 = 26 creations, ce qui aurait porte le
    # parc de 33 a 59 pour un objectif de 50 : depassement de +9, exactement
    # les 9 conteneurs sans categorie qu'il ne comptait ni ne reaffectait.
    # Ces 9-la n'ont pas besoin d'etre CREES, seulement CLASSES.
    # ---------------------------------------------------------------
    par_cat = {}
    for c in ctx["conteneurs"]:
        k = (c.get("categorie") or "").strip()
        par_cat[k] = par_cat.get(k, 0) + 1
    sans_cat = par_cat.pop("", 0)
    repartition = {str(k): int(v) for k, v in (regles.get("repartition") or {}).items()}
    objectif_total = int(regles.get("objectif_total") or 0)
    total_actuel = len(ctx["conteneurs"])

    ecarts_cat, deficit_total, surplus_total = [], 0, 0
    for cat in sorted(set(list(repartition) + list(par_cat))):
        vise = int(repartition.get(cat, 0))
        a = int(par_cat.get(cat, 0))
        ecarts_cat.append({"categorie": cat, "vise": vise, "actuel": a,
                           "ecart": a - vise})
        if a < vise:
            deficit_total += vise - a
        elif a > vise:
            surplus_total += a - vise

    # Les conteneurs sans categorie comblent les deficits SANS creation :
    # les classer coute un clic, les recreer coute un compte Instagram.
    a_reaffecter = min(sans_cat, deficit_total)
    reste_a_creer = max(0, deficit_total - a_reaffecter)
    # Plafond dur : ne jamais depasser l'objectif TOTAL, meme si la somme des
    # cibles par categorie est incoherente avec lui.
    place = max(0, objectif_total - total_actuel)
    depassement = max(0, reste_a_creer - place)
    reste_a_creer = min(reste_a_creer, place)

    creations = []
    if regles.get("creation_active") and reste_a_creer:
        # Repartir les creations autorisees au prorata des deficits.
        manquants = [(c["categorie"], -c["ecart"]) for c in ecarts_cat if c["ecart"] < 0]
        restant, total_manque = reste_a_creer, sum(n for _, n in manquants) or 1
        for i, (cat, manque) in enumerate(sorted(manquants, key=lambda x: -x[1])):
            part = (restant if i == len(manquants) - 1
                    else min(restant, int(round(reste_a_creer * manque / total_manque))))
            if part <= 0:
                continue
            restant -= part
            creations.append({
                "categorie": cat, "manque": manque, "a_creer": part,
                "par_jour": min(part, int(regles.get("creation_par_jour") or 5)),
                "raison": "%d compte(s) manquant(s) pour atteindre %d"
                          % (manque, int(repartition.get(cat, 0)))})

    repartition_bilan = {
        "objectif_total": objectif_total,
        "total_actuel": total_actuel,
        "sans_categorie": sans_cat,
        "categories": ecarts_cat,
        "deficit": deficit_total,
        "surplus": surplus_total,
        "a_reaffecter": a_reaffecter,
        "a_creer": reste_a_creer,
        # Jamais silencieux : si la cible par categorie demande plus de
        # comptes que l'objectif total, on le DIT au lieu de le depasser.
        "depassement_evite": depassement,
        "coherente": sum(repartition.values()) == objectif_total,
        "note_coherence": ("" if sum(repartition.values()) == objectif_total else
                           "La somme de la repartition (%d) ne fait pas "
                           "l'objectif total (%d)."
                           % (sum(repartition.values()), objectif_total)),
    }

    plafond_affiche = 200
    return {
        "maintenant": int(now),
        "fenetre_ouverte": dans_fenetre(regles, now),
        "prochaine_ouverture": int(prochaine_ouverture(regles, now) or 0),
        "en_maintenance": en_maintenance(regles, now),
        "a_inscrire": a_inscrire,
        "a_venir": a_venir[:plafond_affiche],
        "creations": creations,
        "repartition": repartition_bilan,
        "refus": refus[:plafond_affiche],
        "resume": {
            "dus": len(dus), "programmes": len(a_venir), "refuses": len(refus),
            "inscrits_maintenant": len(a_inscrire),
            "par_motif": par_motif,
            "machines_libres": libres_avant,
            "machines_libres_apres": len(libres),
            "machines_occupees": sorted(occupees),
            # Jamais silencieux : ces machines sont retenues par prudence,
            # pas parce qu'on les sait occupees.
            "machines_retenues_par_doute": bride_par_inconnues,
            "travaux_sans_machine": inconnues,
            "lot_par_tick": lot,
            # Compter et remonter : ce qui n'est pas affiche est ANNONCE.
            "a_venir_masques": max(0, len(a_venir) - plafond_affiche),
            "refus_masques": max(0, len(refus) - plafond_affiche),
            "bride_par_machines": len(dus) > len(a_inscrire) and not libres,
        },
        # planifier() reste PUR : c'est tick() qui inscrit, via
        # inscrire_travaux(). Ce drapeau dit que CE calcul-ci n'a rien ecrit.
        "execute": False,
    }


def preparer_travail(entree: dict, regles: dict = None) -> dict:
    """Construit le travail EXACTEMENT comme /api/rig/jobs l'ecrirait.

    Il n'est pas inscrit : cette fonction existe pour que le jour du
    branchement soit une seule ligne d'ecriture, et pour qu'on puisse
    verifier la forme du travail (type accepte, categorie obligatoire pour
    un cycle) sans jamais toucher a la file d'un operateur.
    """
    regles = regles or charger_regles()
    # Le contrat de /api/rig/jobs n'accepte que cycle / etape / scenario /
    # geste / enregistrer. Une CREATION est un cycle complet ; une
    # PUBLICATION est l'etape « reels » seule — passer un cycle entier
    # rejouerait la creation du compte.
    publication = entree.get("type") == "publication"
    genre = "etape" if publication else "cycle"
    return {
        "type": genre,
        "etape": "reels" if publication else "",
        "conteneur": str(entree.get("conteneur") or "")[:60],
        "categorie": str(entree.get("categorie") or regles.get("categorie_defaut"))[:40],
        "scenario": "", "geste": {}, "identity": "",
        "sans_lien": False, "etapes": [],
        "par": "remote2",
        "du_a": int(entree.get("du_a") or maintenant()),
        "machine": str(entree.get("machine") or MACHINE_DEFAUT)[:40],
        "raison": str(entree.get("raison") or "")[:200],
    }


# ==================================================================
# 10. LES TUILES DE CONSEQUENCE — « sinon je comprends juste rien »
# ==================================================================
# Chaque tuile prend les regles du proprietaire et affiche leur CONSEQUENCE
# CHIFFREE, avec un verdict et des corrections a un clic. On ne dit jamais
# « non » : on montre l'arithmetique de ce qui a ete demande.


def tuile_charge(regles: dict, ctx: dict = None) -> dict:
    """« 600 publications par jour » — ce que la regle produit vraiment."""
    comptes = int(regles.get("objectif_total") or 0)
    reels = int(regles.get("reels_par_passage") or 0)
    ppj = _passages_par_jour(regles)
    total = comptes * reels * ppj
    # Le poste tire 3 reels (playlists.json > publication > Reels = 3) et
    # Remote 2 ne peut pas le changer a distance : les DEUX chiffres.
    total_poste = comptes * 3 * ppj
    verdict = "ok" if total <= 300 else "tendu"
    return {
        "cle": "charge", "titre": "Charge produite",
        "valeur": "%d publications / jour" % total,
        "detail": "%d comptes x %d reels x %d passage(s)" % (comptes, reels, ppj),
        "verdict": verdict, "provenance": DERIVE,
        "phrase": ("Le poste n'en tirera que %d : sa playlist « publication » "
                   "est reglee sur 3 reels, et Remote 2 ne peut pas la changer "
                   "a distance." % total_poste) if reels != 3 else
                  "Le poste tire exactement ce nombre.",
        "corrections": [
            {"libelle": "Passer a 1 passage par jour", "champ": "intervalle_min_h",
             "valeur": 24},
            {"libelle": "Reduire a 3 reels par passage", "champ": "reels_par_passage",
             "valeur": 3},
        ],
    }


def tuile_temps(regles: dict, ctx: dict = None) -> dict:
    """« 18 h 20 de telephone par jour » — la charge d'une machine."""
    dur, prov, phrase_dur = duree_passage_s(regles)
    machines = max(1, len(ctx["machines"]) if ctx else 1)
    comptes = int(regles.get("objectif_total") or 0)
    passages = comptes * _passages_par_jour(regles)
    minutes = passages * (dur / 60.0)
    dispo = machines * int(regles.get("machines_heures_utiles") or 20) * 60
    pct = int(round(100.0 * minutes / dispo)) if dispo else 999
    verdict = "ok" if pct <= 70 else ("tendu" if pct <= 100 else "impossible")
    return {
        "cle": "temps", "titre": "Temps telephone",
        "valeur": "%s de telephone / jour" % duree_humaine(minutes * 60),
        "detail": "%d passages x %s sur %d h utiles, %d machine(s) = %d %%"
                  % (passages, duree_humaine(dur),
                     int(regles.get("machines_heures_utiles") or 20), machines, pct),
        "verdict": verdict, "provenance": prov,
        "phrase": ("Une seule panne de WebDriverAgent et le plan decroche. "
                   "Deux machines ramenent a %d %%." % (pct // 2)
                   if machines == 1 and pct > 70 else
                   "Duree d'un passage : %s." % phrase_dur),
        "corrections": [
            {"libelle": "Reduire a 1 passage par jour", "champ": "intervalle_min_h",
             "valeur": 24},
        ],
    }


def tuile_fenetre(regles: dict, ctx: dict = None) -> dict:
    """« 16 passages sur 100 tiennent dans la fenetre » — la tuile qui montre
    au proprietaire que sa propre regle est arithmetiquement impossible, sans
    jamais lui dire non."""
    dur, prov, _ = duree_passage_s(regles)
    machines = max(1, len(ctx["machines"]) if ctx else 1)
    comptes = int(regles.get("objectif_total") or 0)
    passages = comptes * _passages_par_jour(regles)
    fen_min = minutes_utiles(regles)
    capacite = int((fen_min * machines) / max(1, dur / 60.0))
    verdict = ("ok" if capacite >= passages else
               ("tendu" if capacite >= passages * 0.75 else "impossible"))
    besoin = int(-(-passages * (dur / 60.0) // max(1, fen_min))) if fen_min else 0
    retard_h = max(0, (passages - capacite)) * (dur / 3600.0)
    fens = " + ".join("%s-%s" % (f[0], f[1]) for f in (regles.get("fenetres") or []))
    return {
        "cle": "fenetre", "titre": "Fenetre",
        "valeur": "%d passages sur %d tiennent dans la fenetre" % (min(capacite, passages),
                                                                   passages),
        "detail": "%s = %s utiles ÷ %s par passage x %d machine(s)"
                  % (fens or "aucune fenetre", duree_humaine(fen_min * 60),
                     duree_humaine(dur), machines),
        "verdict": verdict, "provenance": prov,
        "phrase": ("Le retard s'accumulerait de %s par jour. Pour tenir, il "
                   "faudrait %d telephones." % (duree_humaine(retard_h * 3600), besoin)
                   if verdict == "impossible" else
                   "La fenetre absorbe le plan." if verdict == "ok" else
                   "La fenetre absorbe tout juste le plan : une panne et le "
                   "retard commence."),
        "corrections": [
            {"libelle": "Ajouter 21:00 - 00:30", "champ": "fenetres",
             "valeur": (regles.get("fenetres") or []) + [["21:00", "23:59"]]},
            {"libelle": "Ouvrir 24 h/24", "champ": "fenetres",
             "valeur": [["00:00", "23:59"]]},
            {"libelle": "Reduire a 1 passage par jour", "champ": "intervalle_min_h",
             "valeur": 24},
        ],
    }


def tuile_stock(regles: dict, ctx: dict = None) -> dict:
    """« chaque video rejouee 40 fois par jour » — le ratio que le
    proprietaire a accepte, mais qui doit rester sous les yeux."""
    ctx = ctx or contexte()
    st = ctx["stock"]
    reels = sum(c.get("medias") or 0 for c in st["categories"]) if st["lisible"] else None
    pubs = (int(regles.get("objectif_total") or 0)
            * int(regles.get("reels_par_passage") or 0) * _passages_par_jour(regles))
    if reels is None:
        return {"cle": "stock", "titre": "Stock", "valeur": "stock illisible",
                "detail": st["note"], "verdict": "tendu",
                "provenance": NON_DECLARE,
                "phrase": "Mesure a la main le 21/08 : 15 reels pour %d "
                          "publications par jour, soit chaque video rejouee "
                          "environ %d fois." % (pubs, round(pubs / 15.0) if pubs else 0),
                "corrections": [{"libelle": "Voir les ecarts", "champ": "",
                                 "valeur": ""}]}
    ratio = round(pubs / max(1, reels))
    return {
        "cle": "stock", "titre": "Stock",
        "valeur": "chaque video rejouee %dx par jour" % ratio,
        "detail": "%d medias declares (%s)" % (
            reels, ", ".join("%s %s" % (c["nom"], c["medias"]) for c in st["categories"])),
        "verdict": "ok" if ratio <= 1 else "tendu", "provenance": DERIVE,
        "phrase": ("Vous avez valide la repetition. La regle de repos sera "
                   "violee a chaque passage : ces passages partiront et seront "
                   "comptes dans Ecarts." if ratio > 1 else
                   "Le stock couvre la cadence sans repetition."),
        # Le bouton « Durcir : annuler le passage » ecrivait si_stock_court,
        # que RIEN ne lit : un clic qui ne change rien est pire qu'aucun
        # bouton. Les deux corrections proposees ici agissent reellement —
        # elles reduisent la demande, seul levier dont le site dispose tant
        # que le stock de medias vit dans le Vault PRO du poste.
        "corrections": [
            {"libelle": "Reduire a 1 passage par jour", "champ": "intervalle_min_h",
             "valeur": 24},
            {"libelle": "Moins de reels par passage", "champ": "reels_par_passage",
             "valeur": max(1, int(regles.get("reels_par_passage") or 6) // 2)},
        ],
    }


def simuler(regles: dict = None, ctx: dict = None) -> dict:
    """Les quatre tuiles, recalculees a chaque frappe dans le tiroir de
    reglages. AUCUNE ECRITURE : c'est ce qui permet de tester une valeur
    avant de l'enregistrer."""
    ctx = ctx or contexte()
    regles = regles or ctx["regles"]
    tuiles = []
    for fn in (tuile_charge, tuile_temps, tuile_fenetre, tuile_stock):
        try:
            tuiles.append(fn(regles, ctx))
        except Exception as e:
            # Une tuile qui plante ne disparait pas : elle le dit.
            tuiles.append({"cle": fn.__name__, "titre": fn.__name__,
                           "valeur": "calcul impossible", "detail": str(e)[:150],
                           "verdict": "tendu", "provenance": NON_DECLARE,
                           "phrase": "Ce calcul a echoue — le reste de l'ecran "
                                     "reste valable.", "corrections": []})
    return {"tuiles": tuiles, "calcule_le": int(maintenant())}


# ==================================================================
# 11. LES TABLEAUX — agreges d'abord, detail a la demande
# ==================================================================
# Regle d'echelle : la vue par defaut ne grossit PAS avec le parc. Une ligne
# par (machine x categorie) fait 20 lignes a 5 machines et 4 categories, que
# le parc compte 33 ou 2 500 comptes.

# Les tris demandes par le proprietaire (« plus recent, dernier cree, plus
# vieux ») n'existent QUE grace a l'observateur : le poste ne transmet
# aucune date. Tant qu'il n'a pas 24 h de recul, ils sont DESACTIVES
# VISIBLEMENT, avec « actif dans 19 h » — jamais silencieusement absents.
TRIS = [
    {"cle": "retard", "libelle": "Le plus en retard (defaut)", "date": False},
    {"cle": "recent", "libelle": "Plus recent (derniere activite)", "date": True},
    {"cle": "cree", "libelle": "Dernier cree (premiere vue)", "date": True},
    {"cle": "vieux", "libelle": "Plus vieux", "date": True},
    {"cle": "passages_desc", "libelle": "Le plus de passages", "date": False},
    {"cle": "passages_asc", "libelle": "Le moins de passages", "date": False},
    {"cle": "echecs", "libelle": "Le plus d'echecs", "date": False},
    {"cle": "alpha", "libelle": "Alphabetique", "date": False},
]


def tris_disponibles(hist: dict = None) -> list:
    """Les tris, avec pour chacun s'il est actif et, sinon, POURQUOI.

    Ne regarder que l'age de l'observateur ne suffisait pas. Les trois tris
    que le proprietaire a nommes (plus recent / dernier cree / plus vieux)
    sont justement ceux qui dependent d'une date, et tous les conteneurs
    PREEXISTANTS ont recu la meme `premiere_vue` au premier passage. Passe
    24 h, « dernier cree » et « plus vieux » se declaraient donc actifs et
    triaient 33 conteneurs sur un horodatage IDENTIQUE : egalite parfaite,
    ordre arbitraire rendu par le tri stable — un tri qui se dit
    fonctionnel et ne trie rien.

    On compte donc ce qui est REELLEMENT distinguable :
      * `cree` / `vieux` : le nombre de conteneurs ayant une vraie date de
        creation (apparus APRES le premier passage de l'observateur) ;
      * `recent` : le nombre de conteneurs qu'on a vus bouger au moins une
        fois — sans activite observee, il n'y a rien a ordonner.
    """
    hist = hist if isinstance(hist, dict) else charger_hist()
    age = hist_age_h()
    conts = (hist.get("conteneurs") or {})
    n_total = len(conts)
    # Une date de creation reelle : le conteneur est apparu sous l'oeil de
    # l'observateur, pas au premier inventaire.
    n_dates = sum(1 for e in conts.values()
                  if not e.get("avant_observateur") and (e.get("premiere_vue") or 0))
    n_bouges = sum(1 for e in conts.values()
                   if (e.get("passages_le") or 0) or (e.get("statut_le") or 0)
                   or (e.get("etapes_le") or 0))
    besoins = {
        "recent": (n_bouges >= 2,
                   "%d conteneur(s) sur %d ont une activite observee : il n'y a "
                   "pas encore de quoi les ordonner. L'observateur a %s de "
                   "recul." % (n_bouges, n_total, duree_humaine(age * 3600))),
        "cree": (n_dates >= 2,
                 "%d conteneur(s) sur %d ont une vraie date de creation. Les "
                 "autres etaient deja la au premier inventaire et portent tous "
                 "le meme horodatage : les trier donnerait un ordre arbitraire."
                 % (n_dates, n_total)),
    }
    besoins["vieux"] = besoins["cree"]
    out = []
    for t in TRIS:
        d = dict(t)
        if not t["date"]:
            d["actif"], d["note"] = True, ""
        else:
            ok, pourquoi = besoins.get(t["cle"], (age >= 24, ""))
            d["actif"] = bool(ok)
            d["note"] = "" if ok else pourquoi
        # Meme actif, un tri partiellement a egalite doit le dire.
        if d["actif"] and t["cle"] in ("cree", "vieux") and n_dates < n_total:
            d["reserve"] = ("%d conteneur(s) sur %d sont a egalite (deja la au "
                            "premier inventaire) et restent groupes en fin de "
                            "tri." % (n_total - n_dates, n_total))
        else:
            d.setdefault("reserve", "")
        out.append(d)
    return out


def _ligne_conteneur(c: dict, ctx: dict) -> dict:
    """Une ligne de parc detaillee, avec tout ce qui est DERIVE clairement
    marque. La fiabilite (mesure / reconstitue) est promue en colonne : 13
    lignes sur 33 sont reconstituees, et l'ignorer c'est croire un historique
    reconstruit."""
    nom = c.get("nom") or ""
    h = (ctx["hist"].get("conteneurs") or {}).get(nom) or {}
    der = derniere_activite(ctx["hist"], nom)
    du, retard, raison = echeance(nom, ctx["hist"], ctx["regles"])
    quar = (ctx["etat"].get("quarantaine") or {}).get(nom)
    motif, detail = refus_conteneur(c, ctx)
    etapes = c.get("etapes") or {}
    return {
        "nom": nom,
        "categorie": (c.get("categorie") or ""),
        # RIEN ne relie un conteneur a un telephone : rig_parc.json est un
        # document GLOBAL, sans nom de machine. Ecrire MACHINE_DEFAUT ici
        # affichait une attribution inventee dans la colonne meme qui porte
        # la dimension machine. ○ non declare, comme partout ailleurs.
        "machine": "",
        "machine_texte": MACHINE_NON_DECLAREE,
        "machine_provenance": NON_DECLARE,
        "machine_marque": marque(NON_DECLARE),
        "pseudo": c.get("pseudo") or "",
        "passages": int(c.get("passages") or 0),
        # 4 statuts et non 2 : « bloque » (verification humaine) est transmis
        # par le poste et jete par l'interface actuelle.
        "statut": c.get("statut") or "",
        "etape": c.get("etape") or "",
        "etapes": [{"nom": e, "etat": etapes.get(e) or ""} for e in ETAPES],
        "franchies": len([e for e in ETAPES if (etapes.get(e) or "") == "ok"]),
        "fiabilite": "reconstitue" if c.get("reconstitue") else "mesure",
        "abandonne": bool(c.get("abandonne")),
        "quarantaine": bool(quar),
        "premiere_vue": int(h.get("premiere_vue") or 0),
        "premiere_vue_approx": bool(h.get("avant_observateur")),
        "derniere_activite": int(der),
        "derniere_activite_texte": (duree_humaine(_age(der)) if der else
                                    "jamais vue bouger"),
        "echecs": len(h.get("echecs") or []),
        "prochain": int(du), "retard": bool(retard), "raison": raison,
        "refus": motif or "", "refus_detail": detail,
        "provenance_dates": DERIVE,
    }


def parc_agrege(ctx: dict = None) -> dict:
    """Une ligne par MACHINE x CATEGORIE. C'est la vue par defaut, et la
    seule qui reste lisible a 250 comptes."""
    ctx = ctx or contexte()
    lignes = {}
    for c in ctx["conteneurs"]:
        cat = (c.get("categorie") or "").strip() or "(sans categorie)"
        # La machine n'est PAS une donnee du conteneur (rig_parc.json est
        # global). On ne fabrique donc pas de cle « poste-1 » : la colonne
        # porte ○ et le dit, au lieu de laisser lire une attribution reelle.
        cle = ("", cat)
        L = lignes.setdefault(cle, {
            "machine": "", "machine_texte": MACHINE_NON_DECLAREE,
            "machine_provenance": NON_DECLARE,
            "machine_marque": marque(NON_DECLARE),
            "categorie": cat, "comptes": 0,
            "prets": 0, "echec": 0, "bloque": 0, "sans_pseudo": 0,
            "quarantaine": 0, "passages": 0, "derniere_activite": 0,
            "refuses": 0, "reconstitues": 0,
        })
        L["comptes"] += 1
        st = c.get("statut") or ""
        if st == "ok":
            L["prets"] += 1
        elif st == "echec":
            L["echec"] += 1
        elif st == "bloque":
            L["bloque"] += 1
        if not (c.get("pseudo") or "").strip():
            L["sans_pseudo"] += 1
        if c.get("reconstitue"):
            L["reconstitues"] += 1
        if (c.get("nom") or "") in (ctx["etat"].get("quarantaine") or {}):
            L["quarantaine"] += 1
        L["passages"] += int(c.get("passages") or 0)
        L["derniere_activite"] = max(L["derniere_activite"],
                                     derniere_activite(ctx["hist"], c.get("nom") or ""))
        if refus_conteneur(c, ctx)[0]:
            L["refuses"] += 1
    out = []
    stock = {c["nom"]: c.get("medias") for c in ctx["stock"]["categories"]}
    for (mach, cat), L in lignes.items():
        L["passages_moyens"] = round(L["passages"] / max(1, L["comptes"]), 1)
        L["derniere_activite_texte"] = (duree_humaine(_age(L["derniere_activite"]))
                                        if L["derniere_activite"] else "jamais")
        L["stock_medias"] = stock.get(cat)
        L["avertissement"] = ("ces conteneurs sont refuses au lancement, motif "
                              "visible dans Ecarts" if cat == "(sans categorie)" else "")
        out.append(L)
    out.sort(key=lambda L: (-L["comptes"], L["categorie"]))
    return {"lignes": out, "total_comptes": len(ctx["conteneurs"]),
            "provenance": DERIVE,
            # La dimension machine de ce tableau est ○ : le poste ne dit pas
            # sur quel telephone vit un conteneur. Le tableau reste « une
            # ligne par categorie » tant que ce champ n'arrive pas.
            "machine_declaree": False,
            "note_machine": ("Aucun conteneur ne declare sa machine : les "
                             "lignes sont groupees par categorie seulement. "
                             "Le poste doit joindre le nom de machine a "
                             "rig_parc.json pour que cette colonne existe.")}


def parc_detaille(ctx: dict = None, tri: str = "retard", sens: str = "asc",
                  page: int = 1, par_page: int = None, machine: str = "",
                  categorie: str = "", statut: str = "", q: str = "",
                  filtre: str = "") -> dict:
    """Le detail, TRIE ET PAGINE COTE SERVEUR.

    Le pied de tableau dit TOUJOURS ce qu'il ne montre pas (« 50 affiches
    sur 214 · 164 masques »), et si le poste a plafonne sa declaration a 200
    conteneurs, il le dit aussi. Aucun slice() muet.
    """
    ctx = ctx or contexte()
    par_page = int(par_page or ctx["regles"].get("lignes_parc") or 50)
    par_page = max(10, min(500, par_page))
    page = max(1, int(page or 1))
    lignes = [_ligne_conteneur(c, ctx) for c in ctx["conteneurs"]]
    total_brut = len(lignes)

    # Aucun conteneur ne declare de machine (rig_parc.json est global) : un
    # filtre par machine ne peut donc RIEN selectionner. Le laisser filtrer
    # rendait un tableau vide sans dire pourquoi — on l'annonce et on ignore
    # le critere, plutot que d'ecarter 250 lignes en silence.
    machine_filtrable = any(L["machine"] for L in lignes)
    note_machine = ""
    if machine and not machine_filtrable:
        note_machine = ("filtre machine « %s » sans effet : aucun conteneur ne "
                        "declare de machine (rig_parc.json est un document "
                        "global)" % str(machine)[:40])
        machine = ""

    def garde(L):
        if machine and L["machine"] != machine:
            return False
        if categorie and (L["categorie"] or "(sans categorie)") != categorie:
            return False
        if statut and (L["statut"] or "") != statut:
            return False
        if filtre == "sans_pseudo" and L["pseudo"]:
            return False
        if filtre == "reconstitue" and L["fiabilite"] != "reconstitue":
            return False
        if filtre == "quarantaine" and not L["quarantaine"]:
            return False
        if filtre == "refuses" and not L["refus"]:
            return False
        if q and q.lower() not in (L["nom"] + " " + L["pseudo"]).lower():
            return False
        return True

    # Les puces de filtre comptent sur le parc ENTIER : une puce qui compte
    # le sous-ensemble deja filtre affiche « 0 » et laisse croire qu'il n'y a
    # rien a voir, alors qu'un autre filtre est simplement actif.
    compteurs = {
        "sans_pseudo": len([L for L in lignes if not L["pseudo"]]),
        "reconstitue": len([L for L in lignes if L["fiabilite"] == "reconstitue"]),
        "quarantaine": len([L for L in lignes if L["quarantaine"]]),
        "refuses": len([L for L in lignes if L["refus"]]),
    }
    lignes = [L for L in lignes if garde(L)]
    dispo = {t["cle"]: t for t in tris_disponibles(ctx["hist"])}
    demande = tri
    note = ""
    if tri not in dispo or not dispo[tri]["actif"]:
        note = (dispo.get(tri, {}).get("note")
                or "tri inconnu « %s »" % str(tri)[:20]) + " — tri par defaut applique"
        tri = "retard"
    cles = {
        "retard": lambda L: (0 if L["retard"] else 1, L["prochain"]),
        "recent": lambda L: -L["derniere_activite"],
        # Les conteneurs sans vraie date de creation portent TOUS le meme
        # horodatage : les melanger aux autres donnait un ordre arbitraire au
        # milieu du tableau. Ils sont groupes en fin de tri, ce que la
        # reserve du tri annonce.
        "cree": lambda L: (1 if L["premiere_vue_approx"] else 0, -L["premiere_vue"]),
        "vieux": lambda L: (1 if L["premiere_vue_approx"] else 0, L["premiere_vue"]),
        "passages_desc": lambda L: -L["passages"],
        "passages_asc": lambda L: L["passages"],
        "echecs": lambda L: -L["echecs"],
        "alpha": lambda L: L["nom"].lower(),
    }
    lignes.sort(key=cles.get(tri, cles["retard"]), reverse=(sens == "desc"))
    total = len(lignes)
    debut = (page - 1) * par_page
    tranche = lignes[debut:debut + par_page]
    return {
        "lignes": tranche, "total": total, "total_brut": total_brut,
        "page": page, "pages": max(1, (total + par_page - 1) // par_page),
        "par_page": par_page,
        "affiches": len(tranche),
        "masques": max(0, total - debut - len(tranche)),
        "tri": tri, "tri_demande": demande, "sens": sens,
        "note": " · ".join(x for x in (note, note_machine) if x),
        "tris": tris_disponibles(ctx["hist"]),
        "plafond_poste": ctx["parc"]["plafond_atteint"],
        "pied": ("%d affiches sur %d · %d masques" % (len(tranche), total,
                                                      max(0, total - debut - len(tranche)))
                 + (" · le poste plafonne sa declaration a 200 conteneurs"
                    if ctx["parc"]["plafond_atteint"] else "")),
        # Filtres avec leur COMPTE : une puce sans compte oblige a cliquer
        # pour savoir si elle sert.
        "filtres": compteurs,
    }


def causes(ctx: dict = None, maxi: int = 5) -> dict:
    """« Ce qui cloche », agrege PAR CAUSE et non par occurrence.

    Cinq lignes au plus, puis OBLIGATOIREMENT la ligne de comptage des
    restes (« + 3 causes a 1 occurrence (18 lignes) »). Une liste tronquee
    sans son compte est un ecartement silencieux de plus.
    """
    ctx = ctx or contexte()
    lignes = _lignes_fin(JOURNAL_FILE, 5000)
    fenetre = ctx["now"] - 86400
    par_code = {}
    for l in lignes:
        if l.get("evt") not in ("echec", "wda_chute", "agents_empiles", "plan_refus"):
            continue
        if float(l.get("ts") or 0) < fenetre:
            continue
        code = l.get("code") or "inconnu"
        e = par_code.setdefault(code, {"code": code, "n": 0, "dernier": 0,
                                       "machines": set(), "conteneurs": set(),
                                       "exemple": ""})
        e["n"] += 1
        e["dernier"] = max(e["dernier"], int(l.get("ts") or 0))
        if l.get("machine"):
            e["machines"].add(l["machine"])
        if l.get("conteneur"):
            e["conteneurs"].add(l["conteneur"])
        if not e["exemple"]:
            e["exemple"] = (l.get("detail") or "")[:160]
    tout = sorted(par_code.values(), key=lambda e: -e["n"])
    for e in tout:
        e["machines"] = len(e["machines"])
        e["conteneurs"] = len(e["conteneurs"])
        e["dernier_age"] = duree_humaine(_age(e["dernier"]))
        e["conduite"] = conduite(e["code"])
    tete, reste = tout[:maxi], tout[maxi:]
    return {
        "lignes": tete,
        "reste_causes": len(reste),
        "reste_occurrences": sum(e["n"] for e in reste),
        "pied": ("+ %d cause(s) supplementaire(s) (%d ligne(s))"
                 % (len(reste), sum(e["n"] for e in reste)) if reste else ""),
        "fenetre": "24 h",
        # Le jour ou « inconnu » est premiere cause, c'est la TABLE qui est a
        # completer — et ca doit se voir, pas se deviner.
        "inconnu_en_tete": bool(tete and tete[0]["code"] == "inconnu"),
    }


def machines_tableau(ctx: dict = None) -> dict:
    """Les machines, enrichies de ce qu'elles ont fait aujourd'hui et de la
    charge que le plan leur destine. Au-dela de 6 machines, seules les plus
    bruyantes sont detaillees — le reste est agrege en une ligne."""
    ctx = ctx or contexte()
    jour0 = _debut_du_jour(ctx["now"])
    lignes = _lignes_fin(JOURNAL_FILE, 5000)
    par_machine = {}
    for l in lignes:
        ts = float(l.get("ts") or 0)
        if ts < jour0:
            continue
        m = l.get("machine") or MACHINE_DEFAUT
        e = par_machine.setdefault(m, {"fini": 0, "echec": 0, "echecs_1h": 0})
        if l.get("evt") == "fini":
            e["fini"] += 1
        elif l.get("evt") == "echec":
            e["echec"] += 1
            if ctx["now"] - ts < 3600:
                e["echecs_1h"] += 1
    dur, _prov, _ph = duree_passage_s(ctx["regles"])
    dispo_min = int(ctx["regles"].get("machines_heures_utiles") or 20) * 60
    comptes = max(1, len(ctx["conteneurs"]))
    n_mach = max(1, len(ctx["machines"]))
    charge_min = (comptes * _passages_par_jour(ctx["regles"]) * (dur / 60.0)) / n_mach
    out = []
    for m in ctx["machines"]:
        s = par_machine.get(m["nom"], {"fini": 0, "echec": 0, "echecs_1h": 0})
        d = dict(m)
        d["aujourdhui"] = s
        # IDENTIQUE SUR TOUTES LES LIGNES, par construction : charge_min est
        # la charge GLOBALE divisee par le nombre de machines. Ce n'est donc
        # pas « ce que fait ce telephone » mais « la part moyenne d'un
        # telephone ». Le dire, plutot que de laisser lire cinq mesures
        # distinctes la ou il n'y en a qu'une.
        d["charge_pct"] = int(round(100.0 * charge_min / dispo_min)) if dispo_min else 0
        d["charge_provenance"] = DERIVE
        d["charge_marque"] = marque(DERIVE)
        d["charge_note"] = ("part moyenne d'une machine (charge totale / %d) — "
                            "identique sur chaque ligne : le poste ne declare "
                            "pas la charge par telephone" % n_mach)
        d["phrase"] = ("Muette depuis %s. Dernier signe de vie %s. Ses travaux "
                       "seront reattribues dans %s."
                       % (m["silence"],
                          datetime.fromtimestamp(m["dernier_vu"]).strftime("%H:%M")
                          if m["dernier_vu"] else "jamais",
                          duree_humaine(max(0, int(ctx["regles"].get("reattribuer_min") or 20) * 60
                                            - (m["silence_s"] or 0))))
                       if m["etat"] == "muette" else "")
        out.append(d)
    # Un travail « pris »/« en_cours » qu'aucun pull n'a revendique n'est
    # compte sur aucune ligne : il doit etre annonce, pas efface.
    orphelins = 0
    if len(ctx["machines"]) > 1:
        orphelins = sum(1 for j in ctx["jobs"]["jobs"]
                        if j.get("etat") in ("pris", "en_cours")
                        and not machine_du_job(j, ctx["hist"]))
    bruyantes, silencieuses = out[:6], out[6:]
    return {
        "lignes": bruyantes,
        "agregees": len(silencieuses),
        "agregees_anomalies": len([m for m in silencieuses
                                   if m["aujourdhui"]["echecs_1h"]]),
        "pied": ("+ %d machine(s) non detaillee(s), %d avec anomalie"
                 % (len(silencieuses),
                    len([m for m in silencieuses if m["aujourdhui"]["echecs_1h"]]))
                 if silencieuses else ""),
        "identite_declaree": any(m["identifiee"] for m in out),
        "note_identite": ("" if any(m["identifiee"] for m in out) else
                          "Cette machine ne dit pas son nom. Un second telephone "
                          "ecraserait ses donnees : rig_parc.json est un document "
                          "global unique."),
        # Compter et remonter : un travail en cours qu'on ne sait rattacher a
        # aucun telephone doit se voir, pas disparaitre du tableau.
        "non_attribues": orphelins,
        "note_non_attribues": (
            "%d travail(x) en cours sans machine declaree : aucun pull ne les "
            "a revendiques. Ils ne sont comptes sur aucune ligne."
            % orphelins) if orphelins else "",
    }


# ==================================================================
# 12. LES GRAPHIQUES — SVG rendus COTE SERVEUR
# ==================================================================
# Chart.js peut etre bloque cote client dans ce projet (carte vide, sans
# erreur) : tous les graphiques sont donc du SVG genere ici, comme
# _home_sales_svg (web_upload.py:22089). Les rectangles portent
# class='hsc-dot' data-tip='...' pour heriter du tooltip global existant.
_VERT_G, _AMBRE_G, _ROUGE_G, _BLEU_G, _GRIS_G = ("#22c55e", "#f59e0b", "#ef4444",
                                                 "#3b82f6", "#9ca3af")


def svg_ruban(ctx: dict = None, plan: dict = None) -> str:
    """LE graphique principal : une voie par machine sur un seul axe de 24 h.

    POURQUOI celui-la et pas un camembert : c'est le seul qui montre un
    CHEVAUCHEMENT. Deux blocs superposes sur la meme voie, ce sont les
    quatre agents empiles de la nuit du 21/08. Un camembert ne l'aurait
    jamais montre — ni le temps, ni la simultaneite.

    Le PASSE est en blocs pleins (largeur = duree derivee), le FUTUR en
    blocs haches (prevu par le plan) sur la MEME regle.
    """
    ctx = ctx or contexte()
    plan = plan or planifier(ctx)
    machines = ctx["machines"] or [{"nom": MACHINE_DEFAUT, "etat": "muette",
                                    "dernier_vu": 0, "silence_s": None}]
    n = len(machines)
    W, VOIE, HAUT = 1200.0, 22.0, 40.0
    H = HAUT + 28 * n + 16
    ML, MR = 92.0, 12.0
    IW = W - ML - MR
    t0 = ctx["now"] - 18 * 3600
    t1 = ctx["now"] + 6 * 3600

    def X(t):
        return ML + IW * max(0.0, min(1.0, (float(t) - t0) / (t1 - t0)))

    out = [
        "<svg viewBox='0 0 %d %d' style='width:100%%;height:auto' "
        "xmlns='http://www.w3.org/2000/svg'>" % (int(W), int(H)),
        "<defs><pattern id='r2hach' width='6' height='6' patternUnits='userSpaceOnUse' "
        "patternTransform='rotate(45)'><rect width='3' height='6' fill='#3b82f6' "
        "opacity='.35'/></pattern>"
        "<pattern id='r2muet' width='6' height='6' patternUnits='userSpaceOnUse' "
        "patternTransform='rotate(45)'><rect width='3' height='6' fill='#9ca3af' "
        "opacity='.30'/></pattern></defs>",
    ]
    # Axe des heures : un trait par heure, une etiquette toutes les 3 h.
    h = datetime.fromtimestamp(t0).replace(minute=0, second=0, microsecond=0)
    t = h.timestamp()
    while t < t1:
        x = X(t)
        heure = datetime.fromtimestamp(t).hour
        out.append("<line x1='%.1f' y1='%.0f' x2='%.1f' y2='%.0f' "
                   "stroke='rgba(136,136,136,.16)' stroke-width='1'/>"
                   % (x, HAUT - 8, x, H - 12))
        if heure % 3 == 0:
            out.append("<text x='%.1f' y='%.0f' text-anchor='middle' font-size='10' "
                       "fill='#888'>%02dh</text>" % (x, HAUT - 14, heure))
        t += 3600
    # « Maintenant » : la ligne de partage entre le mesure et le prevu.
    xn = X(ctx["now"])
    out.append("<line x1='%.1f' y1='%.0f' x2='%.1f' y2='%.0f' stroke='%s' "
               "stroke-width='1.5' stroke-dasharray='3 3'/>"
               % (xn, HAUT - 10, xn, H - 12, _BLEU_G))
    out.append("<text x='%.1f' y='%.0f' text-anchor='middle' font-size='9' fill='%s'>"
               "maintenant</text>" % (xn, HAUT - 22, _BLEU_G))

    for i, m in enumerate(machines):
        y = HAUT + 28 * i
        out.append("<text x='6' y='%.0f' font-size='11' fill='#888'>%s</text>"
                   % (y + 15, _esc(m["nom"][:14])))
        out.append("<rect x='%.1f' y='%.0f' width='%.1f' height='%.0f' rx='4' "
                   "fill='rgba(136,136,136,.08)'/>" % (ML, y, IW, VOIE))
        # Zone muette : « zero travail » et « pas de donnee » se ressemblent
        # a l'oeil et ne veulent pas dire la meme chose.
        if m.get("etat") == "muette" and m.get("dernier_vu"):
            x1, x2 = X(m["dernier_vu"]), X(ctx["now"])
            if x2 > x1:
                out.append("<rect class='hsc-dot' x='%.1f' y='%.0f' width='%.1f' "
                           "height='%.0f' fill='url(#r2muet)' data-tip='%s'/>"
                           % (x1, y, x2 - x1, VOIE,
                              _esc("machine muette depuis " + (m.get("silence") or "?"))))
        # Passe : les travaux reels.
        for j in ctx["jobs"]["jobs"]:
            deb = j.get("pris_a") or j.get("cree")
            if not deb or float(deb) > t1:
                continue
            fin = j.get("maj") or (ctx["now"] if j.get("etat") in ("pris", "en_cours")
                                   else deb)
            if float(fin) < t0:
                continue
            coul = {"fini": _VERT_G, "echec": _ROUGE_G, "en_cours": _BLEU_G,
                    "pris": _BLEU_G}.get(j.get("etat"), _GRIS_G)
            x1, x2 = X(deb), X(fin)
            larg = max(2.0, x2 - x1)
            tip = "%s %s\n%s\n%s" % (j.get("type") or "?", j.get("conteneur") or "",
                                     j.get("etat") or "?",
                                     duree_humaine(float(fin) - float(deb)))
            out.append("<rect class='hsc-dot' x='%.1f' y='%.0f' width='%.1f' "
                       "height='%.0f' rx='3' fill='%s' opacity='.85' "
                       "data-tip='%s' style='cursor:pointer'/>"
                       % (x1, y + 2, larg, VOIE - 4, coul, _esc(tip)))
        # Futur : ce que le plan prevoit, hache.
        for e in (plan.get("a_venir") or [])[:120]:
            if e.get("machine") and e["machine"] != m["nom"]:
                continue
            if float(e["du_a"]) > t1 or float(e["du_a"]) < t0:
                continue
            x1 = X(e["du_a"])
            larg = max(3.0, IW * (duree_passage_s(ctx["regles"])[0] / (t1 - t0)))
            out.append("<rect class='hsc-dot' x='%.1f' y='%.0f' width='%.1f' "
                       "height='%.0f' rx='3' fill='url(#r2hach)' data-tip='%s'/>"
                       % (x1, y + 2, larg, VOIE - 4,
                          _esc("prevu %s — %s\n%s" % (e["heure"], e["conteneur"],
                                                      e["raison"]))))
    # Chutes de WDA : un trait ambre en travers de toutes les voies.
    for tsc in ((ctx["hist"].get("wda") or {}).get("chutes") or [])[-80:]:
        if t0 <= tsc <= t1:
            x = X(tsc)
            out.append("<line class='hsc-dot' x1='%.1f' y1='%.0f' x2='%.1f' y2='%.0f' "
                       "stroke='%s' stroke-width='1.5' data-tip='%s'/>"
                       % (x, HAUT, x, H - 14, _AMBRE_G,
                          _esc("chute de WebDriverAgent a "
                               + datetime.fromtimestamp(tsc).strftime("%H:%M"))))
    out.append("</svg>")
    return "".join(out)


def svg_debit(ctx: dict = None) -> dict:
    """Le debit des 24 dernieres heures : 24 barres empilees (reussi / echec)
    et une phrase GENEREE sous le graphe — un axe muet n'apprend rien.

    Rend {svg, phrase} : la phrase (« Creux de 02 h a 07 h : 0 publication,
    14 echecs wda_injoignable ») est souvent la seule chose qu'on lira.
    """
    ctx = ctx or contexte()
    heures = ctx["hist"].get("heures") or {}
    barres = []
    for k in range(23, -1, -1):
        t = ctx["now"] - k * 3600
        b = heures.get(_bucket_heure(t)) or {}
        barres.append({"h": datetime.fromtimestamp(t).hour,
                       "fini": int(b.get("fini") or 0),
                       "echec": int(b.get("echec") or 0),
                       "douteux": int(b.get("douteux") or 0), "ts": t})
    W, H = 1200.0, 190.0
    ML, MR, MT, MB = 40.0, 12.0, 14.0, 26.0
    IW, IH = W - ML - MR, H - MT - MB
    vmax = max([b["fini"] + b["echec"] for b in barres] + [1])
    larg = IW / 24.0
    out = ["<svg viewBox='0 0 %d %d' style='width:100%%;height:auto' "
           "xmlns='http://www.w3.org/2000/svg'>" % (int(W), int(H))]
    for k in range(4):
        gy = MT + IH * k / 3.0
        out.append("<line x1='%.0f' y1='%.1f' x2='%.0f' y2='%.1f' "
                   "stroke='rgba(136,136,136,.14)'/>" % (ML, gy, W - MR, gy))
        out.append("<text x='%.0f' y='%.1f' text-anchor='end' font-size='10' "
                   "fill='#888'>%d</text>" % (ML - 6, gy + 3.5, vmax * (3 - k) / 3))
    for i, b in enumerate(barres):
        x = ML + i * larg
        hf = IH * b["fini"] / vmax
        he = IH * b["echec"] / vmax
        if b["fini"]:
            out.append("<rect class='hsc-dot' x='%.1f' y='%.1f' width='%.1f' "
                       "height='%.1f' fill='%s' data-tip='%s'/>"
                       % (x + 1, MT + IH - hf, larg - 2, hf, _VERT_G,
                          _esc("%02dh — %d reussite(s)%s" % (b["h"], b["fini"],
                               (", dont %d douteuse(s)" % b["douteux"]) if b["douteux"] else ""))))
        if b["echec"]:
            out.append("<rect class='hsc-dot' x='%.1f' y='%.1f' width='%.1f' "
                       "height='%.1f' fill='%s' data-tip='%s'/>"
                       % (x + 1, MT + IH - hf - he, larg - 2, he, _ROUGE_G,
                          _esc("%02dh — %d echec(s)" % (b["h"], b["echec"]))))
        if b["h"] % 3 == 0:
            out.append("<text x='%.1f' y='%.0f' text-anchor='middle' font-size='10' "
                       "fill='#888'>%02dh</text>" % (x + larg / 2, H - 8, b["h"]))
    out.append("</svg>")
    # La phrase : le PLUS LONG creux, et ce qui s'y est passe. Un axe muet
    # n'apprend rien ; et quand il n'y a rien du tout, on le dit franchement
    # plutot que d'annoncer un creux qui fait le tour du cadran.
    total_f = sum(b["fini"] for b in barres)
    total_e = sum(b["echec"] for b in barres)
    if total_f == 0 and total_e == 0:
        phrase = ("Aucun travail journalise sur 24 h — le journal ne commence "
                  "qu'a l'installation du poste de pilotage.")
    elif total_f == 0:
        phrase = ("Aucune publication sur 24 h, mais %d echec(s) : le parc "
                  "tourne a vide." % total_e)
    else:
        meilleur, debut = None, None
        for b in barres:
            if b["fini"] == 0:
                debut = debut or b
                if meilleur is None or (b["ts"] - debut["ts"]) > (meilleur[1]["ts"] - meilleur[0]["ts"]):
                    meilleur = (debut, b)
            else:
                debut = None
        if meilleur and (meilleur[1]["ts"] - meilleur[0]["ts"]) >= 3600:
            ech = sum(x["echec"] for x in barres
                      if meilleur[0]["ts"] <= x["ts"] <= meilleur[1]["ts"])
            phrase = ("Creux de %02d h a %02d h : 0 publication, %d echec(s)."
                      % (meilleur[0]["h"], meilleur[1]["h"], ech))
        else:
            phrase = ("%d reussite(s) et %d echec(s) sur 24 h." % (total_f, total_e))
    return {"svg": "".join(out), "phrase": phrase}


def svg_couverture(ctx: dict = None) -> str:
    """La couverture du parc : 8 colonnes, une par etape du cycle.

    C'est le SEUL graphique qui ne grossit pas avec le parc — 8 colonnes que
    le parc fasse 33 ou 2 500 comptes — et c'est pour cela qu'il remplace
    toute liste d'etapes par conteneur dans la vue par defaut.
    """
    ctx = ctx or contexte()
    tot = max(1, len(ctx["conteneurs"]))
    vals = []
    for e in ETAPES:
        n = len([c for c in ctx["conteneurs"]
                 if ((c.get("etapes") or {}).get(e) or "") == "ok"])
        vals.append((e, n, int(round(100.0 * n / tot))))
    W, H = 1200.0, 180.0
    ML, MR, MT, MB = 34.0, 12.0, 16.0, 34.0
    IW, IH = W - ML - MR, H - MT - MB
    larg = IW / len(ETAPES)
    out = ["<svg viewBox='0 0 %d %d' style='width:100%%;height:auto' "
           "xmlns='http://www.w3.org/2000/svg'>" % (int(W), int(H))]
    out.append("<line x1='%.0f' y1='%.1f' x2='%.0f' y2='%.1f' "
               "stroke='rgba(136,136,136,.2)'/>" % (ML, MT + IH, W - MR, MT + IH))
    for i, (nom, n, pct) in enumerate(vals):
        x = ML + i * larg
        h = IH * pct / 100.0
        coul = _VERT_G if pct >= 80 else (_AMBRE_G if pct >= 20 else _ROUGE_G)
        out.append("<rect class='hsc-dot' x='%.1f' y='%.1f' width='%.1f' height='%.1f' "
                   "rx='4' fill='%s' opacity='.85' data-tip='%s'/>"
                   % (x + 8, MT + IH - h, larg - 16, max(1.0, h), coul,
                      _esc("%s : %d conteneur(s) sur %d ont franchi cette etape"
                           % (nom, n, tot))))
        out.append("<text x='%.1f' y='%.0f' text-anchor='middle' font-size='10' "
                   "fill='#888'>%s</text>" % (x + larg / 2, H - 18, _esc(nom)))
        out.append("<text x='%.1f' y='%.0f' text-anchor='middle' font-size='11' "
                   "fill='#888'>%d %%</text>" % (x + larg / 2, MT + IH - h - 5, pct))
    out.append("</svg>")
    return "".join(out)


def graphiques(ctx: dict = None, plan: dict = None) -> dict:
    """Les graphiques prets a poser dans la page. Chacun est deja une chaine
    SVG : le client ne calcule rien, il colle.

    La courbe « reussite brute contre reussite verifiee » n'apparait qu'au
    14e jour de journal : avant, elle n'aurait que des jours vides — elle
    mentirait et elle demoraliserait.
    """
    ctx = ctx or contexte()
    debit = svg_debit(ctx)
    jours_journal = hist_age_h() / 24.0
    return {
        "ruban": svg_ruban(ctx, plan),
        "debit": debit["svg"], "debit_phrase": debit["phrase"],
        "couverture": svg_couverture(ctx),
        "reussite_14j": None,
        "reussite_14j_note": ("Disponible dans %d jour(s) : une courbe de 14 "
                              "jours dont 13 sont vides ment."
                              % max(0, int(14 - jours_journal))),
    }


# ==================================================================
# 13. LE VERDICT, LE BOUTON, LES VOYANTS — l'etage 0
# ==================================================================
# Une phrase, un bouton, cinq voyants. Rien d'autre au-dessus de la ligne de
# flottaison : « facile a utiliser » veut dire qu'on comprend l'ecran avant
# de faire defiler.


def verdict(ctx: dict, pv: dict, plan: dict) -> dict:
    """LA phrase du haut, par ordre de gravite descendante. Elle est
    cliquable et renvoie vers la zone qui l'explique — un verdict sans
    explication atteignable est un slogan."""
    conflits = [d for d in pv["controles"]
                if d["cle"] == "agent_unique" and d["gravite"] == ROUGE]
    if conflits:
        return {"niveau": ROUGE, "ancre": "machines",
                "phrase": "CONFLIT — plusieurs agents suspectes sur le meme telephone"}
    muettes = [m for m in ctx["machines"] if m["etat"] == "muette"]
    if muettes and len(muettes) == len(ctx["machines"]):
        m = muettes[0]
        return {"niveau": ROUGE, "ancre": "machines",
                "phrase": "PARC A L'ARRET — %s muet depuis %s" % (m["nom"], m["silence"])}
    if not pv["peut_demarrer"]:
        return {"niveau": ROUGE, "ancre": "prevol",
                "phrase": "NO-GO — %d blocage(s) : %s"
                          % (len(pv["bloquants"]), ", ".join(pv["bloquants"][:3]))}
    chutes = [d for d in pv["controles"] if d["cle"] == "wda_stable"
              and d["gravite"] in (ROUGE, AMBRE)]
    if muettes or chutes:
        return {"niveau": AMBRE, "ancre": "machines",
                "phrase": "DEGRADE — %d machine(s) sur %d%s"
                          % (len(ctx["machines"]) - len(muettes), len(ctx["machines"]),
                             ", " + chutes[0]["valeur"] if chutes else "")}
    actifs = [j for j in ctx["jobs"]["jobs"] if j.get("etat") in ("pris", "en_cours")]
    if ctx["regles"].get("pilote") and actifs:
        return {"niveau": VERT, "ancre": "ruban",
                "phrase": "EN MARCHE — %d travail(s) en cours" % len(actifs)}
    if ctx["regles"].get("pilote"):
        h = plan.get("prochaine_ouverture") or 0
        return {"niveau": VERT, "ancre": "ruban",
                "phrase": "EN MARCHE — rien en cours, prochain passage %s"
                          % (datetime.fromtimestamp(h).strftime("%H h %M") if h else
                             "des qu'un compte est du")}
    return {"niveau": "jaune", "ancre": "bouton",
            "phrase": "EN VEILLE — le pilote est arrete, rien ne partira"}


def bouton(ctx: dict, pv: dict) -> dict:
    """La machine a etats du bouton unique : LE LIBELLE EST L'ETAT.

    Un bouton ne se grise JAMAIS sans texte : il dit toujours pourquoi il
    refuse. Et la bascule (plutot qu'un declencheur de vague) parce que le
    proprietaire a dit « il faut que ca tourne tout seul » : personne ne
    clique un bouton a 3 h du matin.
    """
    poste = [d for d in pv["controles"] if d["cle"] == "poste"][0] \
        if any(d["cle"] == "poste" for d in pv["controles"]) else None
    if poste and poste["gravite"] in (ROUGE, GRIS):
        return {"etat": "inerte", "libelle": "POSTE MUET (%s)" % poste["valeur"],
                "style": "gris", "peut_cliquer": False,
                "raison": "Rien ne partira tant que l'agent ne rappelle pas."}
    if ctx["regles"].get("pilote"):
        return {"etat": "pause", "libelle": "METTRE LE PARC EN PAUSE",
                "style": "contour_rouge", "peut_cliquer": True,
                "confirmation": "CONFIRMER LA PAUSE", "confirmation_s": 4,
                "raison": "Les travaux en attente seront geles, pas annules."}
    if not pv["peut_demarrer"]:
        return {"etat": "nogo", "libelle": "NO-GO — %d BLOCAGE(S)" % len(pv["bloquants"]),
                "style": "contour_rouge", "peut_cliquer": False,
                "raison": "; ".join(pv["bloquants"][:3]),
                "ouvre": "prevol_rouges"}
    if pv["ambres"]:
        return {"etat": "reserves",
                "libelle": "DEMARRER AVEC %d RESERVE(S)" % pv["ambres"],
                "style": "plein_ambre", "peut_cliquer": True,
                "confirmation": "CONFIRMER — %d RESERVE(S)" % pv["ambres"],
                "confirmation_s": 4,
                "raison": "Les reserves franchies sont ecrites au journal "
                          "(code prevol_force)."}
    return {"etat": "demarrer", "libelle": "DEMARRER LE PARC", "style": "plein_vert",
            "peut_cliquer": True,
            "raison": "%d controles, %d OK." % (pv["total"], pv["verts"])}


def voyants(ctx: dict) -> list:
    """Cinq voyants avec leur AGE et leur provenance : Agent, WDA, Tunnel,
    Console, Medias. Au clic, chacun ouvre le tiroir de provenance — valeur
    brute, fichier d'origine, horodatage, et ce que ca veut dire."""
    j, p, a = ctx["jobs"], ctx["parc"], ctx["actions"]
    st = ctx["stock"]
    def v(cle, nom, grav, valeur, source, age, sens, prov):
        return {"cle": cle, "nom": nom, "gravite": grav, "valeur": valeur,
                "source": source, "age_s": (int(age) if age and age > 0 else None),
                "age": duree_humaine(age) if age and age > 0 else "jamais",
                "sens": sens, "provenance": prov, "marque": marque(prov)}
    return [
        v("agent", "Agent",
          VERT if 0 <= j["battement_age_s"] < 90 else ROUGE,
          "bat" if 0 <= j["battement_age_s"] < 90 else "muet",
          "rig_jobs.json > battement", j["battement_age_s"],
          "L'agent vient chercher du travail toutes les 8 s.", MESURE),
        v("wda", "WDA", VERT if p["wda"] else ROUGE, "oui" if p["wda"] else "non",
          "rig_parc.json > wda", p["age_s"],
          "Sans lui, aucun geste n'est possible sur le telephone.", MESURE),
        v("tunnel", "Tunnel", GRIS, "non declare", "corps de /api/rig/pull", -1,
          "Le poste mesure deja tunnel_repond (etapes/_commun.py:62) mais ne "
          "le transmet pas : un tunnel mort = zero publication, sans alerte.",
          NON_DECLARE),
        v("console", "Console", VERT if a["n"] >= 10 else AMBRE,
          "%d action(s)" % a["n"], "rig_actions.json", a["age_s"],
          "1 action sur 37 : la console 8770 etait eteinte au dernier "
          "demarrage de l'agent, l'editeur proposera une palette vide."
          if a["n"] < 10 else "Le moteur declare toutes ses actions.", MESURE),
        v("medias", "Medias", GRIS if not st["lisible"] else VERT,
          "illisible" if not st["lisible"] else
          "%d medias" % sum(c.get("medias") or 0 for c in st["categories"]),
          "rig_parc.json > categories", p["age_s"], st["note"],
          NON_DECLARE if not st["lisible"] else DERIVE),
    ]


# ==================================================================
# 14. L'ETAT COMPLET — un seul fetch pilote toute la page
# ==================================================================
def etat_complet() -> dict:
    """Tout l'ecran, DEJA CALCULE cote serveur.

    POURQUOI : c'est la condition pour que l'ecran reste juste a 5 machines.
    La verite est calculee une fois, ici ; le JS ne fait aucun calcul metier,
    il pose du HTML. Chaque bloc est protege : un bloc qui echoue est
    remonte dans `erreurs` et le reste de l'ecran s'affiche quand meme.
    """
    erreurs = []

    def bloc(nom, fn, defaut=None):
        try:
            return fn()
        except Exception as e:
            erreurs.append("%s: %s: %s" % (nom, type(e).__name__, str(e)[:120]))
            return defaut

    ctx = contexte()
    pv = bloc("prevol", lambda: prevol(ctx), {"controles": [], "total": 0, "verts": 0,
                                              "ambres": 0, "rouges": 0, "gris": 0,
                                              "bloquants": [], "peut_demarrer": False,
                                              "non_declares": 0, "correctifs_poste": []})
    plan = bloc("plan", lambda: planifier(ctx), {"a_inscrire": [], "a_venir": [],
                                                 "refus": [], "resume": {},
                                                 "creations": []})
    return {
        "ok": True,
        "maintenant": int(ctx["now"]),
        "verdict": bloc("verdict", lambda: verdict(ctx, pv, plan), {}),
        "bouton": bloc("bouton", lambda: bouton(ctx, pv), {}),
        "voyants": bloc("voyants", lambda: voyants(ctx), []),
        "tuiles": bloc("tuiles", lambda: simuler(ctx["regles"], ctx), {"tuiles": []}),
        "prevol": pv,
        "machines": bloc("machines", lambda: machines_tableau(ctx), {"lignes": []}),
        "parc": bloc("parc", lambda: parc_agrege(ctx), {"lignes": []}),
        "causes": bloc("causes", lambda: causes(ctx), {"lignes": []}),
        "ecarts": bloc("ecarts", ecarts_resume, []),
        "graphiques": bloc("graphiques", lambda: graphiques(ctx, plan), {}),
        "plan": {"resume": plan.get("resume") or {},
                 "a_inscrire": plan.get("a_inscrire") or [],
                 "creations": plan.get("creations") or [],
                 # L'ecart cible <-> realite, dans les deux sens. Sans lui,
                 # « repartition » etait un reglage que le proprietaire
                 # saisissait et qui n'apparaissait NULLE PART a l'ecran.
                 "repartition": plan.get("repartition") or {},
                 "fenetre_ouverte": plan.get("fenetre_ouverte"),
                 "prochaine_ouverture": plan.get("prochaine_ouverture"),
                 "execute": False},
        "regles": ctx["regles"],
        "regles_meta": bloc("regles_meta", regles_meta, []),
        "profils": {k: {"titre": v["titre"], "quand": v["quand"]}
                    for k, v in PROFILS.items()},
        "etat_pilote": ctx["etat"],
        "journal": {"lignes_total": bloc("journal_total", journal_lignes_total, 0),
                    "observateur_depuis_h": round(hist_age_h(), 1)},
        "fraicheur": {
            "age_s": int(ctx["age_max_s"]) if ctx["age_max_s"] > 0 else None,
            "age": duree_humaine(ctx["age_max_s"]) if ctx["age_max_s"] > 0 else "inconnu",
            "perime": ctx["age_max_s"] > int(ctx["regles"].get("age_donnees_min") or 10) * 60,
        },
        # Ce qui n'a pas pu etre calcule est DIT. Un ecran incomplet qui se
        # tait est pire qu'un ecran incomplet qui s'explique.
        "erreurs": erreurs,
    }


# ==================================================================
# 15. L'INSCRIPTION REELLE DANS LA FILE DU POSTE
# ==================================================================
# Plafond de web_upload.py:44923 — `([job] + d["jobs"])[:80]`. Il faut le
# respecter A L'IDENTIQUE ici, sinon les deux ecrivains n'ont pas la meme
# idee de la taille de la file.
_PLAFOND_FILE = 80

# Les champs que preparer_travail() ajoute pour le PLAN et que la file du
# poste ne connait pas : l'agent ne les lit pas, et les laisser ferait
# diverger le format de /api/rig/jobs.
_CHAMPS_PLAN = ("du_a", "machine", "raison")


def _job_depuis_plan(e: dict, regles: dict, rang: int = 0) -> dict:
    """Un travail au format EXACT de /api/rig/jobs (web_upload.py).

    La correspondance creation -> cycle / publication -> etape « reels » est
    decidee par preparer_travail() et par elle SEULE. Ce module avait deja
    cette fonction, ecrite « pour que le jour du branchement soit une seule
    ligne d'ecriture » : la redupliquer ici, c'etait se donner deux tables
    de correspondance pour la meme decision — le piege connu du projet, ou
    un cas accepte d'un cote est ignore de l'autre.

    `par = "remote2"` est LOAD-BEARING : c'est a ce champ que
    observer_jobs() reconnait une inscription de l'ordonnanceur et la
    journalise « inscrit » au lieu de « hors_plan ». Un travail pose par
    l'horloge ne doit jamais ressembler a un clic humain dans Remote 1.
    """
    job = dict(preparer_travail(e, regles))
    for k in _CHAMPS_PLAN:
        job.pop(k, None)
    # `rang` : trois travaux d'un meme tour naissent dans la meme
    # milliseconde et se seraient partage un seul identifiant — deux
    # d'entre eux auraient disparu de l'historique, qui est indexe par id.
    job["id"] = "j%d" % (int(maintenant() * 1000) + rang)
    job["cree"] = int(maintenant())
    job["etat"], job["avancement"], job["erreur"] = "en_attente", "", ""
    return job


def inscrire_travaux(entrees: list, par: str = "horloge") -> dict:
    """Ecrit REELLEMENT les travaux du plan dans rig_jobs.json.

    C'est la seule fonction du module qui touche un fichier du poste. Les
    trois precautions annoncees dans l'en-tete du module sont ici, et pas
    ailleurs :

    * PLAFOND — la file est tronquee a 80 par l'autre ecrivain. On refuse
      d'inscrire ce qui ferait tomber un travail encore vivant de la file,
      et on le DIT (journal + compteur) au lieu de le laisser disparaitre.
    * COURSE — Remote 2 et /api/rig/pull ecrivent le meme fichier sans
      verrou partage. On relit apres avoir ecrit ; si nos identifiants ont
      disparu, l'ecriture a ete perdue : on re-inscrit UNE fois et on
      journalise `course_file` (le garde-fou gf_course_fichier le compte
      deja, il etait arme d'avance).
    * PRE-ENREGISTREMENT — chaque travail est inscrit dans l'historique avec
      LA MACHINE qui lui a ete attribuee. Sans cela l'observateur le
      redecouvrirait au prochain pull, le journaliserait une seconde fois,
      et lui collerait MACHINE_DEFAUT — c'est-a-dire la fausse attribution
      que le tableau des machines montrait.

    Rend {inscrits, refuses, course}. Rien n'est jamais ecarte en silence.
    """
    entrees = [e for e in (entrees or []) if (e.get("conteneur") or "").strip()]
    if not entrees:
        return {"inscrits": [], "refuses": [], "course": False}

    inscrits, refuses, course = [], [], False
    regles = charger_regles()
    with _LOCK_FILE:
        d = safe_json.load(RIG_JOBS, default={}) or {}
        if not isinstance(d, dict):
            d = {}
        file_ = d.get("jobs")
        file_ = file_ if isinstance(file_, list) else []
        # Ne jamais poser deux fois le meme conteneur : l'autre ecrivain a pu
        # en inscrire un entre le calcul du plan et maintenant.
        deja = {(j.get("conteneur") or "") for j in file_
                if j.get("etat") not in ("fini", "echec", "annule")}
        vivants = sum(1 for j in file_
                      if j.get("etat") not in ("fini", "echec", "annule"))
        neufs = []
        for e in entrees:
            nom = (e.get("conteneur") or "").strip()
            if nom in deja:
                refuses.append({"conteneur": nom, "motif": "doublon",
                                "detail": "un travail vise deja ce conteneur "
                                          "dans la file du poste"})
                continue
            # Un cycle sans categorie est refuse par la route ET s'arrete a
            # la sixieme etape cote agent, APRES avoir cree un compte : le
            # refuser ici coute un compte de moins pour rien.
            j_essai = _job_depuis_plan(e, regles, rang=len(neufs))
            if j_essai["type"] == "cycle" and not (j_essai.get("categorie") or "").strip():
                refuses.append({"conteneur": nom, "motif": "sans_categorie",
                                "detail": "cycle sans categorie : l'etape des "
                                          "medias echouerait apres la creation"})
                continue
            if vivants + len(neufs) >= _PLAFOND_FILE:
                refuses.append({"conteneur": nom, "motif": "file_pleine",
                                "detail": "la file du poste est a son plafond "
                                          "de %d travaux" % _PLAFOND_FILE})
                continue
            j = j_essai
            j["_machine"] = e.get("machine") or MACHINE_DEFAUT
            neufs.append(j)

        if neufs:
            # La machine attribuee n'a rien a faire dans le fichier du poste
            # (l'agent ne connait pas ce champ) : elle vit dans l'historique.
            machines = {j["id"]: j.pop("_machine") for j in neufs}
            d["jobs"] = (list(reversed(neufs)) + file_)[:_PLAFOND_FILE]
            safe_json.write(RIG_JOBS, d, indent=None)

            # -- relecture : l'autre ecrivain a-t-il ecrase notre ecriture ?
            relu = safe_json.load(RIG_JOBS, default={}) or {}
            presents = {str(j.get("id") or "")
                        for j in (relu.get("jobs") or [])
                        if isinstance(j, dict)}
            perdus = [j for j in neufs if j["id"] not in presents]
            course = course or bool(perdus)
            if perdus:
                d2 = relu if isinstance(relu, dict) else {}
                base = d2.get("jobs")
                base = base if isinstance(base, list) else []
                d2["jobs"] = (list(reversed(perdus)) + base)[:_PLAFOND_FILE]
                safe_json.write(RIG_JOBS, d2, indent=None)
                journal("plan_decision", objet="verrou", par=par,
                        code="course_file",
                        detail="%d travail(x) disparu(s) apres ecriture — "
                               "re-inscrit(s) une fois" % len(perdus))

            # -- pre-enregistrement dans l'historique, AVEC la machine.
            with _LOCK_HIST:
                h = charger_hist()
                js = h.setdefault("jobs", {})
                now = int(maintenant())
                for j in neufs:
                    js[j["id"]] = {
                        "vu": now, "etat": "en_attente",
                        "conteneur": j.get("conteneur") or "",
                        "type": j.get("type") or "", "par": "remote2",
                        "cree": int(j.get("cree") or now), "duree_s": None,
                        "code": "", "douteux": False,
                        "machine": machines.get(j["id"]) or MACHINE_DEFAUT,
                    }
                _sauver_hist(h)

            for j in neufs:
                journal("inscrit", objet="job", job_id=j["id"],
                        conteneur=j.get("conteneur") or "",
                        machine=machines.get(j["id"]) or "",
                        type_=j.get("type") or "", par=par, src="horloge",
                        detail="inscrit par l'ordonnanceur")
                inscrits.append(j["id"])

    # Compter et remonter : un refus d'inscription est un ecart, pas un vide.
    for r in refuses:
        ecart(r["motif"], conteneur=r["conteneur"], detail=r["detail"],
              journaliser=True)
    return {"inscrits": inscrits, "refuses": refuses, "course": course}


# ==================================================================
# 15 bis. LE TOUR D'HORLOGE
# ==================================================================
def tick(par: str = "horloge", executer: bool = False) -> dict:
    """Un tour d'ordonnanceur : il calcule, JOURNALISE, et inscrit.

    `executer=True` inscrit reellement dans rig_jobs.json, via
    inscrire_travaux() qui porte les trois precautions (plafond de 80,
    mitigation de course, pre-enregistrement de la machine). C'est
    l'horloge — et elle seule — qui le demande : un clic humain sur
    « Jouer un tour » reste une SIMULATION, pour qu'on puisse verifier a
    l'oeil ce que le pilote ferait sans qu'il parte.

    Rien ne part tant que `regles["pilote"]` est faux (defaut d'usine) NI
    tant que le pre-vol a un bloquant : les deux verrous sont plus bas.

    Idempotent a la minute : deux appels dans la meme minute ne produisent
    qu'une seule trace (cle AAAAMMJJ-HHMM), sinon un rafraichissement de
    page toutes les 5 s remplirait le journal.
    """
    with _LOCK_TICK:
        cle = datetime.fromtimestamp(maintenant()).strftime("%Y%m%d-%H%M")
        tours = safe_json.load(TOURS_FILE, default={}) or {}
        if not isinstance(tours, dict):
            tours = {}
        deja = tours.get("dernier_tick") == cle
        ctx = contexte()
        pv = prevol(ctx)
        plan = planifier(ctx)
        if deja:
            return {"ok": True, "deja_fait": cle, "plan": plan["resume"],
                    "execute": False}
        tours["dernier_tick"] = cle
        tours["dernier_ts"] = int(maintenant())
        tours["dernier_resume"] = plan["resume"]
        safe_json.write(TOURS_FILE, tours, indent=1)

    if not ctx["regles"].get("pilote"):
        journal("plan_decision", objet="plan", par=par,
                detail="pilote arrete — %d travail(s) auraient ete dus"
                       % plan["resume"]["dus"])
        return {"ok": True, "pilote": False, "plan": plan["resume"], "execute": False}
    if en_pause(ctx["etat"]):
        journal("plan_decision", objet="plan", par=par, code="refus_garde_fou",
                detail="pause demandee jusqu'a %s — %d travail(s) en attente"
                       % (datetime.fromtimestamp(
                           ctx["etat"].get("pause_jusqu_a") or 0).strftime("%d/%m %H:%M"),
                          plan["resume"]["dus"]))
        return {"ok": True, "pause": True, "plan": plan["resume"], "execute": False}
    if not pv["peut_demarrer"]:
        journal("plan_decision", objet="plan", par=par, code="refus_garde_fou",
                detail="pre-vol bloquant : " + ", ".join(pv["bloquants"][:4]))
        # LE scenario nomme par le proprietaire : « une panne a 3 h du matin
        # est invisible jusqu'au lendemain soir ». Le pilote est demarre, il
        # veut travailler, et un garde-fou l'en empeche : c'est exactement ce
        # qu'il faut savoir tout de suite.
        if executer:
            alerter("prevol_bloquant", "Le parc est arrete par un garde-fou",
                    "Le pilote est demarre mais rien ne peut partir : %s. "
                    "%d travail(x) etaient dus."
                    % (", ".join(pv["bloquants"][:4]), plan["resume"]["dus"]),
                    regles=ctx["regles"])
        return {"ok": True, "bloque": pv["bloquants"], "plan": plan["resume"],
                "execute": False}
    for r in plan["refus"]:
        ecart(r["motif"], conteneur=r["conteneur"], detail=r["detail"],
              journaliser=False)
    if not executer:
        # Le clic humain « Jouer un tour » : on montre ce qui PARTIRAIT.
        for e in plan["a_inscrire"]:
            journal("plan_decision", objet="plan", conteneur=e["conteneur"],
                    machine=e.get("machine") or "", type_=e["type"], par=par,
                    detail="serait inscrit maintenant (%s)" % e["raison"])
        return {"ok": True, "plan": plan["resume"], "execute": False}

    pose = inscrire_travaux(plan["a_inscrire"], par=par)
    return {"ok": True, "plan": plan["resume"], "execute": True,
            "inscrits": pose["inscrits"], "refuses": pose["refuses"]}


# ==================================================================
# 15 ter. L'HORLOGE — ce qui fait que « ca tourne tout seul »
# ==================================================================
# Sans elle, `regles["pilote"]` etait un interrupteur que RIEN ne lisait :
# le proprietaire cliquait « DEMARRER LE PARC », voyait le bandeau « pilote
# demarre », fermait son navigateur — et au matin, zero publication, zero
# travail dans la file, une seule ligne de journal. Le seul declencheur
# etait un clic humain sur « Jouer un tour », qui n'inscrivait rien.
_HORLOGE = None
_HORLOGE_ARRET = threading.Event()

# Periode de repli quand les reglages sont illisibles. On ne veut NI une
# boucle serree qui martyrise le disque, NI un silence : 60 s = le defaut
# de `tick_s`.
_HORLOGE_PERIODE_REPLI = 60


_DERNIER_ENTRETIEN = [0.0]


def _entretien_quotidien(regles: dict) -> None:
    """Ce qui doit tourner une fois par jour, pas a chaque tour.

    Aujourd'hui : la purge du journal par anciennete (`retention_j`), qui
    n'avait aucun declencheur — le reglage existait, la fonction non.
    """
    if maintenant() - _DERNIER_ENTRETIEN[0] < 86400:
        return
    _DERNIER_ENTRETIEN[0] = maintenant()
    try:
        purge_anciennete(int(regles.get("retention_j") or 90))
    except Exception as e:
        print("[parc] entretien : %s" % str(e)[:120], flush=True)


def _boucle_horloge() -> None:
    """Le tour d'ordonnanceur, toutes les `tick_s` secondes, pour toujours.

    Trois choix qui ont chacun une raison :

    * elle tourne MEME pilote arrete. tick() sort tout seul sur le premier
      verrou et journalise « pilote arrete — N travail(s) auraient ete dus ».
      C'est ce qui permet de lire au matin ce que le parc AURAIT fait, et
      de demarrer en connaissance de cause. Une horloge qu'on arrete quand
      le pilote s'arrete ne laisse aucune trace de la nuit.
    * elle n'explose JAMAIS. Une exception dans un thread de fond meurt en
      silence et le parc s'arrete sans que rien ne le dise : tout est sous
      try/except, et l'echec est journalise puis retente au tour suivant.
    * elle est en `daemon` et s'appuie sur un Event : un rechargement du
      serveur de dev ne laisse pas deux horloges derriere lui.
    """
    # Un demarrage de site ne doit pas partir dans la seconde : le poste n'a
    # pas encore battu, le pre-vol serait rouge pour rien.
    _HORLOGE_ARRET.wait(15)
    while not _HORLOGE_ARRET.is_set():
        periode = _HORLOGE_PERIODE_REPLI
        try:
            regles = charger_regles()
            periode = max(15, min(900, int(regles.get("tick_s") or 60)))
            tick(par="horloge", executer=True)
            _entretien_quotidien(regles)
        except Exception as e:
            # Compter et remonter : une horloge muette est exactement le
            # defaut qu'elle est censee corriger.
            try:
                journal("plan_decision", objet="plan", par="horloge",
                        code="erreur_interne",
                        detail="tour d'horloge en echec : %s: %s"
                               % (type(e).__name__, str(e)[:160]))
            except Exception:
                pass
            print("[parc] horloge : %s" % str(e)[:160], flush=True)
        _HORLOGE_ARRET.wait(periode)


def demarrer_horloge() -> bool:
    """Lance l'horloge une seule fois. Rend True si c'est elle qui l'a lancee.

    Le garde `is_alive` compte : en developpement, Flask recharge le module
    a chaque sauvegarde, et sans lui on empilait une horloge de plus a
    chaque fois — soit exactement la panne du 21/08 (plusieurs agents sur un
    seul telephone), rejouee cote site.
    """
    global _HORLOGE
    if _HORLOGE is not None and _HORLOGE.is_alive():
        return False
    _HORLOGE_ARRET.clear()
    _HORLOGE = threading.Thread(target=_boucle_horloge, name="parc-horloge",
                                daemon=True)
    _HORLOGE.start()
    return True


def arreter_horloge() -> None:
    """Utile aux tests : sans elle, une horloge survit a la fin du test et
    ecrit dans les donnees pendant le test suivant."""
    _HORLOGE_ARRET.set()


# ==================================================================
# 16. LA PAGE (coquille) ET LES ROUTES
# ==================================================================
# Le style suit le patron de #form-remote (web_upload.py:9161-9175) : UNE
# teinte d'accent, redefinie par theme, et rien d'autre en dur.
#
# UNE difference assumee avec Remote 1 : ici les SURFACES passent aussi par
# des variables, redefinies en bloc pour le theme clair. Remote 1 corrige
# ses surfaces regle par regle (une trentaine de `body.light .rmt-…`) et un
# seul oubli y laisse une carte noire sur fond blanc — le defaut du site
# etant `light` (web_upload.py:40556), l'oubli se voit chez presque tout le
# monde. Avec des variables, oublier devient impossible.
#
# Aucun !important nulle part : la specificite suffit et se CALCULE.
#   `#parc-root`            = (0,1,0)  -> le sombre, theme `dark` sans classe
#   `body.light #parc-root` = (0,2,1)  -> le clair, gagne sur le precedent
#   `body.apple #parc-root` = (0,2,1)  -> meme poids que light, mais les deux
#                                         blocs ne declarent JAMAIS la meme
#                                         variable (accent ici, surfaces la),
#                                         donc l'ordre du fichier n'arbitre
#                                         rien et Apple = surfaces claires +
#                                         accent Apple, sans ambiguite.
_STYLE = """<style>
/* --- 1. L'ACCENT, par theme. body.light ne le redefinit pas : le clair
   herite du bleu nu et seul Apple change d'accent en clair, exactement
   comme Remote 1. 5 themes, 5 selecteurs. */
#parc-root{--r2:#3b82f6;--r2-doux:rgba(59,130,246,.14);
  --r2-trait:rgba(59,130,246,.40)}
body.apple #parc-root{--r2:#007aff;--r2-doux:rgba(0,122,255,.12);
  --r2-trait:rgba(0,122,255,.42)}
body.violet #parc-root{--r2:#a855f7;--r2-doux:rgba(168,85,247,.14);
  --r2-trait:rgba(168,85,247,.40)}
body.gold #parc-root{--r2:#d9b74a;--r2-doux:rgba(217,183,74,.14);
  --r2-trait:rgba(217,183,74,.40)}
body.obsidian #parc-root{--r2:#8b9cf7;--r2-doux:rgba(139,156,247,.14);
  --r2-trait:rgba(139,156,247,.40)}

/* --- 2. LES SURFACES ET LES TROIS COULEURS DE VERDICT. Le vert, l'ambre
   et le rouge sont HORS theme : un rouge doit rester rouge dans les cinq
   themes. Ils sont seulement fonces en clair, sinon un #22c55e sur blanc
   est illisible. */
#parc-root{--r2-fond:#141418;--r2-fond2:#1a1a1f;--r2-champ:#0f0f12;
  --r2-bord:#26262c;--r2-bord2:#303036;--r2-txt:#e6e6ea;--r2-gris:#8b8b95;
  --r2-faible:#6b6b70;
  --r2-vert:#22c55e;--r2-ambre:#f59e0b;--r2-rouge:#ef4444;--r2-bleu:#3b82f6;
  --r2-jaune:#eab308;
  --r2-vert-d:rgba(34,197,94,.15);--r2-ambre-d:rgba(245,158,11,.15);
  --r2-rouge-d:rgba(239,68,68,.14);--r2-gris-d:rgba(139,139,149,.13);
  --r2-ombre:0 10px 30px rgba(0,0,0,.45);--r2-scrim:rgba(0,0,0,.42);
  --r2-sur-plein:#10151a}
body.light #parc-root{--r2-fond:#fff;--r2-fond2:#f2f2f7;--r2-champ:#fff;
  --r2-bord:rgba(60,60,67,.12);--r2-bord2:rgba(60,60,67,.18);--r2-txt:#1c1c1e;
  --r2-gris:#5f5f6a;--r2-faible:#8b8b95;
  --r2-vert:#15803d;--r2-ambre:#b45309;--r2-rouge:#dc2626;--r2-bleu:#1d4ed8;
  --r2-jaune:#a16207;
  --r2-vert-d:rgba(21,128,61,.10);--r2-ambre-d:rgba(180,83,9,.10);
  --r2-rouge-d:rgba(220,38,38,.09);--r2-gris-d:rgba(60,60,67,.07);
  --r2-ombre:0 10px 30px rgba(60,60,67,.18);--r2-scrim:rgba(60,60,67,.30);
  /* Sur un aplat de couleur, le texte change de sens avec le theme : blanc
     sur le vert fonce du clair, presque noir sur le vert vif du sombre.
     Une seule variable, et les trois boutons pleins suivent. */
  --r2-sur-plein:#ffffff}

/* --- 3. SOCLE */
#parc-root{max-width:1500px;margin:0 auto;width:100%;color:var(--r2-txt);
  position:relative}
#parc-root .r2-carte{border:1px solid var(--r2-bord);border-radius:13px;
  background:var(--r2-fond);padding:15px 16px;margin-bottom:12px}
#parc-root .r2-carte-in{margin:10px 0;background:var(--r2-fond2)}
#parc-root .r2-tete{display:flex;justify-content:space-between;
  align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:10px}
#parc-root .r2-h{font-size:15px;font-weight:700;letter-spacing:-.01em}
#parc-root .r2-h2{font-size:13px;font-weight:700;margin:14px 0 6px}
#parc-root .r2-sous{font-size:12px;color:var(--r2-gris);line-height:1.45}
#parc-root .r2-faible{font-size:11px;color:var(--r2-faible)}
#parc-root .r2-note{font-size:11.5px;color:var(--r2-gris);line-height:1.5;
  border-left:2px solid var(--r2-trait);padding-left:10px;margin-top:10px}
#parc-root .r2-pied{font-size:11.5px;color:var(--r2-gris);margin-top:9px;
  padding-top:8px;border-top:1px solid var(--r2-bord)}
#parc-root .r2-vide{font-size:12.5px;color:var(--r2-gris);padding:16px 4px;
  line-height:1.5}
#parc-root .r2-etiq{font-size:10px;font-weight:700;padding:1px 7px;
  border-radius:99px;background:var(--r2-gris-d);color:var(--r2-gris);
  white-space:nowrap}
/* Les deux etats d'un garde-fou, VISUELLEMENT distincts : rouge quand il
   bloque REELLEMENT le demarrage, gris efface quand il ne fait que le
   pourrait. Selecteurs a DEUX classes (0,1,2,0) contre (0,1,1,0) pour
   .r2-etiq : la specificite l'emporte, sans dependre de l'ordre du
   fichier ni d'un !important. Les teintes sont deja redefinies par theme
   plus haut (--r2-rouge / --r2-rouge-d), donc rien a ajouter par theme. */
#parc-root .r2-etiq.r2-etiq-bloque{background:var(--r2-rouge-d);
  color:var(--r2-rouge)}
#parc-root .r2-etiq.r2-etiq-inerte{background:transparent;
  color:var(--r2-gris);border:1px solid var(--r2-bord);font-weight:600;
  opacity:.85}
/* Tout tableau large defile DANS sa boite : la page, elle, ne defile
   jamais horizontalement. Un faux tableau en grille n'est pas un <table>
   et echappe au .main table{overflow-x:auto} global (web_upload.py:1830). */
#parc-root .r2-scroll{overflow-x:auto;overflow-y:hidden}
#parc-root .r2-liste{font-size:12.5px;line-height:1.7;color:var(--r2-gris);
  padding-left:18px}

/* --- 4. VERDICTS. Une seule famille de classes sert le texte, la pastille
   et le fond : `.r2-pt.r2-g-x` (0,2,0) bat `.r2-pt` (0,1,0). */
#parc-root .r2-g-vert{color:var(--r2-vert)}
#parc-root .r2-g-ambre{color:var(--r2-ambre)}
#parc-root .r2-g-rouge{color:var(--r2-rouge)}
#parc-root .r2-g-bleu{color:var(--r2-bleu)}
#parc-root .r2-g-jaune{color:var(--r2-jaune)}
#parc-root .r2-g-gris{color:var(--r2-gris)}
#parc-root .r2-pt{width:9px;height:9px;border-radius:50%;flex-shrink:0;
  display:inline-block;background:var(--r2-gris);
  box-shadow:0 0 0 3px var(--r2-gris-d)}
#parc-root .r2-pt.r2-g-vert{background:var(--r2-vert);
  box-shadow:0 0 0 3px var(--r2-vert-d)}
#parc-root .r2-pt.r2-g-ambre{background:var(--r2-ambre);
  box-shadow:0 0 0 3px var(--r2-ambre-d)}
#parc-root .r2-pt.r2-g-rouge{background:var(--r2-rouge);
  box-shadow:0 0 0 3px var(--r2-rouge-d)}
#parc-root .r2-pt.r2-g-bleu{background:var(--r2-bleu);
  box-shadow:0 0 0 3px var(--r2-doux)}
/* Les marques de provenance : ● mesure, ◐ derive, ○ non declare. Le ○ est
   volontairement pale — il ne doit JAMAIS ressembler a un vert. */
#parc-root .r2-mq{font-size:10px;cursor:help;vertical-align:1px}
#parc-root .r2-mq-mesure{color:var(--r2-vert)}
#parc-root .r2-mq-derive{color:var(--r2-bleu)}
#parc-root .r2-mq-non_declare{color:var(--r2-faible)}

/* --- 5. BANDEAUX D'ALERTE (garde-fous visibles en haut) */
#parc-root .r2-bandeau{border:1px solid var(--r2-bord);border-left-width:3px;
  border-radius:11px;padding:11px 14px;margin-bottom:10px;
  background:var(--r2-fond)}
#parc-root .r2-bandeau.r2-g-rouge{border-left-color:var(--r2-rouge);
  background:var(--r2-rouge-d)}
#parc-root .r2-bandeau.r2-g-ambre{border-left-color:var(--r2-ambre);
  background:var(--r2-ambre-d)}
#parc-root .r2-bandeau-t{font-size:13px;font-weight:700;color:var(--r2-txt)}
#parc-root .r2-bandeau-x{font-size:12px;color:var(--r2-gris);margin-top:3px;
  line-height:1.5}
#parc-root .r2-bandeau-b{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}

/* --- 6. ZONE A : le verdict, le bouton, les voyants */
#parc-root .r2-barre{position:sticky;top:0;z-index:12;
  border:1px solid var(--r2-bord);border-radius:13px;padding:14px 16px;
  background:var(--r2-fond);margin-bottom:12px}
#parc-root .r2-barre-h{display:flex;justify-content:space-between;gap:12px;
  align-items:center;flex-wrap:wrap}
#parc-root .r2-verdict{font-size:19px;font-weight:800;letter-spacing:-.02em;
  background:none;border:0;padding:0;font-family:inherit;cursor:pointer;
  text-align:left}
#parc-root .r2-verdict:hover{text-decoration:underline}
#parc-root .r2-frais{font-size:11.5px;font-weight:700;padding:3px 10px;
  border-radius:99px;background:var(--r2-gris-d);cursor:help}
#parc-root .r2-cmd{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  margin-top:12px}
#parc-root .r2-cmd-x{flex:1;min-width:220px}
#parc-root .r2-cmd-b{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#parc-root .r2-pausebloc{display:inline-flex;gap:4px;align-items:center}
#parc-root .r2-sousligne{font-size:12.5px;font-weight:600;color:var(--r2-txt)}
#parc-root .r2-voyants{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
#parc-root .r2-voy{display:inline-flex;align-items:center;gap:7px;
  padding:6px 11px;border:1px solid var(--r2-bord);border-radius:99px;
  background:var(--r2-fond2);cursor:pointer;font:inherit;font-size:12px;
  color:var(--r2-txt)}
#parc-root .r2-voy:hover{border-color:var(--r2-trait)}
#parc-root .r2-voy-n{font-weight:700}
#parc-root .r2-voy-v{color:var(--r2-gris)}
#parc-root .r2-voy-a{color:var(--r2-faible);font-size:11px}

/* --- 7. BOUTONS. Le libelle EST l'etat : un bouton ne se grise jamais
   sans texte, et le desactive garde son libelle plein. */
#parc-root .r2-b1{min-height:44px;padding:0 22px;border-radius:11px;
  font:inherit;font-size:14px;font-weight:800;letter-spacing:.01em;
  cursor:pointer;border:1px solid transparent;white-space:nowrap}
#parc-root .r2-b1-petit{min-height:36px;font-size:13px;padding:0 16px}
#parc-root .r2-b1-plein_vert{background:var(--r2-vert);border-color:var(--r2-vert);
  color:var(--r2-sur-plein)}
#parc-root .r2-b1-plein_ambre{background:var(--r2-ambre);
  border-color:var(--r2-ambre);color:var(--r2-sur-plein)}
#parc-root .r2-b1-plein_accent{background:var(--r2);border-color:var(--r2);
  color:var(--r2-sur-plein)}
#parc-root .r2-b1-contour_rouge{background:var(--r2-rouge-d);
  border-color:var(--r2-rouge);color:var(--r2-rouge)}
#parc-root .r2-b1-gris{background:var(--r2-gris-d);border-color:var(--r2-bord2);
  color:var(--r2-gris)}
#parc-root .r2-b1-conf{outline:2px dashed var(--r2-ambre);outline-offset:2px}
#parc-root .r2-b1[disabled]{cursor:not-allowed;opacity:.75}
#parc-root .r2-b2{min-height:38px;padding:0 13px;border-radius:9px;
  border:1px solid var(--r2-bord2);background:var(--r2-fond2);
  color:var(--r2-txt);font:inherit;font-size:12.5px;font-weight:600;
  cursor:pointer;display:inline-flex;align-items:center;gap:6px}
#parc-root .r2-b2:hover{border-color:var(--r2-trait);color:var(--r2)}
#parc-root .r2-b2[disabled]{opacity:.5;cursor:not-allowed}
#parc-root .r2-b3{padding:4px 10px;border-radius:8px;
  border:1px solid var(--r2-bord2);background:transparent;
  color:var(--r2-gris);font:inherit;font-size:11.5px;font-weight:600;
  cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}
#parc-root .r2-b3:hover{border-color:var(--r2-trait);color:var(--r2)}
#parc-root .r2-b3[disabled]{opacity:.4;cursor:not-allowed}
#parc-root .r2-lien{background:none;border:0;padding:0;font:inherit;
  font-size:13px;font-weight:700;color:var(--r2);cursor:pointer;
  text-align:left}
#parc-root .r2-lien:hover{text-decoration:underline}
#parc-root .r2-plier{background:none;border:0;padding:0;font:inherit;
  font-size:13.5px;font-weight:700;color:var(--r2-txt);cursor:pointer;
  text-align:left}
#parc-root .r2-plie{margin-top:12px}

/* --- 8. ZONE B : les tuiles de consequence et les graphiques */
#parc-root .r2-tuiles{display:grid;gap:12px;margin-bottom:12px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
#parc-root .r2-tuile{position:relative;border:1px solid var(--r2-bord);
  border-top-width:3px;border-radius:13px;padding:14px 15px;
  background:var(--r2-fond)}
#parc-root .r2-t-ok{border-top-color:var(--r2-vert)}
#parc-root .r2-t-tendu{border-top-color:var(--r2-ambre)}
#parc-root .r2-t-impossible{border-top-color:var(--r2-rouge)}
#parc-root .r2-tuile-t{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.4px;color:var(--r2-gris)}
#parc-root .r2-tuile-v{font-size:19px;font-weight:800;letter-spacing:-.02em;
  margin:5px 0 3px;line-height:1.2}
#parc-root .r2-tuile-d{font-size:11.5px;color:var(--r2-faible)}
#parc-root .r2-tuile-p{font-size:12px;color:var(--r2-gris);margin-top:8px;
  line-height:1.5}
#parc-root .r2-tuile-c{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
#parc-root .r2-tuile-verdict{position:absolute;top:12px;right:14px;
  font-size:10px;font-weight:800;letter-spacing:.5px;color:var(--r2-faible)}
#parc-root .r2-t-tendu .r2-tuile-verdict{color:var(--r2-ambre)}
#parc-root .r2-t-impossible .r2-tuile-verdict{color:var(--r2-rouge)}
#parc-root .r2-t-ok .r2-tuile-verdict{color:var(--r2-vert)}
#parc-root .r2-apercu{border:1px dashed var(--r2-ambre);border-radius:11px;
  padding:9px 13px;margin-bottom:10px;font-size:12px;color:var(--r2-ambre);
  background:var(--r2-ambre-d)}
#parc-root .r2-legendes{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;
  font-size:11px;color:var(--r2-gris)}
#parc-root .r2-leg{display:inline-flex;align-items:center;gap:5px}
#parc-root .r2-hach{width:12px;height:9px;display:inline-block;border-radius:2px;
  background:repeating-linear-gradient(45deg,var(--r2-bleu) 0 2px,
    transparent 2px 5px);opacity:.7}
#parc-root .r2-hach-g{background:repeating-linear-gradient(45deg,
  var(--r2-gris) 0 2px,transparent 2px 5px)}
#parc-root .r2-trait-a{width:2px;height:11px;display:inline-block;
  background:var(--r2-ambre)}
#parc-root svg{max-width:100%}

/* --- 9. ZONE C : le pre-vol */
#parc-root .r2-pv{margin-top:6px}
#parc-root .r2-pvl{display:grid;gap:10px;align-items:baseline;
  grid-template-columns:12px minmax(150px,1.1fr) minmax(90px,.7fr) 2.2fr 110px;
  padding:9px 2px;border-bottom:1px solid var(--r2-bord);font-size:12.5px}
#parc-root .r2-pvl:last-child{border-bottom:0}
#parc-root .r2-pvl-n{font-weight:700}
#parc-root .r2-pvl-v{color:var(--r2-txt);font-weight:600}
#parc-root .r2-pvl-m{color:var(--r2-gris);font-size:12px;line-height:1.45}
#parc-root .r2-pvl-a{text-align:right}
#parc-root .r2-pv-ok{opacity:.72}

/* --- 10. LES FAUX TABLEAUX (machines, parc agrege).
   La grille est declaree UNE SEULE FOIS dans une classe partagee par
   l'en-tete et les lignes : c'est le piege connu du projet (.va-ig3-thead
   duplique ses colonnes et se desaligne au premier changement). */
#parc-root .r2-mgrid{display:grid;gap:10px;align-items:center;
  grid-template-columns:12px minmax(120px,1.1fr) 92px 190px minmax(130px,1.4fr)
    120px 74px 140px 40px}
#parc-root .r2-agrid{display:grid;gap:10px;align-items:center;
  grid-template-columns:32px 90px minmax(110px,1fr) 74px 62px 62px 96px 104px
    120px 96px}
#parc-root .r2-mtbl,#parc-root .r2-atbl{min-width:1020px}
/* L'ecart cible <-> realite : trois colonnes, donc AUCUN min-width — sinon
   un tableau de trois colonnes forcerait un defilement horizontal. */
#parc-root .r2-rgrid{display:grid;gap:10px;align-items:center;
  grid-template-columns:minmax(110px,1.2fr) 130px minmax(120px,1fr)}
#parc-root .r2-rtbl{min-width:0}
#parc-root .r2-sous-carte{margin-top:12px}
#parc-root .r2-mhead,#parc-root .r2-ahead{font-size:10px;font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;color:var(--r2-faible);
  padding:8px 10px;border-bottom:1px solid var(--r2-bord)}
#parc-root .r2-mrow,#parc-root .r2-arow{padding:11px 10px;font-size:12.5px;
  border-bottom:1px solid var(--r2-bord)}
#parc-root .r2-mrow:hover,#parc-root .r2-arow:hover{background:var(--r2-fond2)}
#parc-root .r2-mrow-muette{background:var(--r2-ambre-d)}
#parc-root .r2-mrow-p,#parc-root .r2-arow-p{grid-column:1/-1;font-size:11.5px;
  color:var(--r2-ambre);padding-top:2px}
#parc-root .r2-jauge{display:inline-block;width:62px;height:6px;
  border-radius:99px;background:var(--r2-gris-d);overflow:hidden;
  vertical-align:middle}
#parc-root .r2-jauge i{display:block;height:100%}
#parc-root .r2-jauge i.r2-g-vert{background:var(--r2-vert)}
#parc-root .r2-jauge i.r2-g-ambre{background:var(--r2-ambre)}
#parc-root .r2-jauge i.r2-g-rouge{background:var(--r2-rouge)}

/* --- 11. LE VRAI TABLEAU (parc detaille, journal). Un <table> herite du
   .main table{display:block;overflow-x:auto} global en mobile, ce qu'une
   grille CSS ne fait pas — d'ou le choix ici. */
#parc-root .r2-tbl{width:100%;border-collapse:collapse;font-size:12px;
  min-width:900px}
#parc-root .r2-tbl th{background:var(--r2-fond2);color:var(--r2-faible);
  padding:8px 10px;text-align:left;border-bottom:1px solid var(--r2-bord);
  font-size:10px;text-transform:uppercase;letter-spacing:.05em;font-weight:700;
  white-space:nowrap}
/* En-tetes cliquables : le tri se prend au titre de colonne, pas seulement
   dans un menu deroulant. Un tri pas encore disponible (l'observateur n'a
   pas 24 h de recul) reste VISIBLE, en pointille, avec son delai en
   infobulle — jamais absent en silence. */
#parc-root .r2-th{cursor:pointer;user-select:none}
#parc-root .r2-th:hover,#parc-root .r2-th.on{color:var(--r2)}
#parc-root .r2-th-off{cursor:help;opacity:.55;text-decoration:underline dotted}
#parc-root .r2-tbl td{padding:8px 10px;border-bottom:1px solid var(--r2-bord);
  color:var(--r2-txt);vertical-align:top}
#parc-root .r2-tbl tr:hover td{background:var(--r2-fond2)}
#parc-root .r2-jd{max-width:340px;white-space:normal;word-break:break-word;
  color:var(--r2-gris)}
#parc-root .r2-tr{display:inline-flex;gap:2px;width:78px;vertical-align:middle}
#parc-root .r2-tr i{flex:1;height:5px;border-radius:99px;
  background:var(--r2-gris-d);display:block}
#parc-root .r2-tr i.ok{background:var(--r2-vert)}
#parc-root .r2-tr i.now{background:var(--r2)}
#parc-root .r2-tr i.ko{background:var(--r2-rouge)}

/* --- 12. ONGLETS INTERNES, FILTRES, CHAMPS */
#parc-root .r2-onglets{display:flex;gap:2px;flex-wrap:wrap;
  border-bottom:1px solid var(--r2-bord);margin-bottom:12px}
#parc-root .r2-onglets-p{border-bottom:0;margin-bottom:0}
#parc-root .r2-onglet{padding:9px 14px;font:inherit;font-size:13px;
  font-weight:600;color:var(--r2-gris);background:transparent;border:0;
  border-bottom:2px solid transparent;cursor:pointer;margin-bottom:-1px}
#parc-root .r2-onglet:hover{color:var(--r2-txt)}
#parc-root .r2-onglet.on{color:var(--r2);border-bottom-color:var(--r2)}
#parc-root .r2-filtres{display:flex;gap:7px;flex-wrap:wrap;align-items:center;
  margin-bottom:10px}
#parc-root .r2-lab{font-size:11px;color:var(--r2-faible);
  text-transform:uppercase;letter-spacing:.4px}
#parc-root .r2-puce{padding:5px 11px;border-radius:99px;
  border:1px solid var(--r2-bord2);background:var(--r2-fond2);
  color:var(--r2-gris);font:inherit;font-size:11.5px;cursor:pointer}
#parc-root .r2-puce.on{border-color:var(--r2-trait);background:var(--r2-doux);
  color:var(--r2)}
#parc-root .r2-champ{padding:7px 10px;border-radius:9px;
  border:1px solid var(--r2-bord2);background:var(--r2-champ);
  color:var(--r2-txt);font:inherit;font-size:12.5px;max-width:100%}
/* Les <option> ne suivent pas le style du <select> sur tous les systemes :
   sans ces deux lignes, la liste s'ouvrait noir sur noir (Remote 1, 9202). */
#parc-root .r2-champ option{background:var(--r2-fond);color:var(--r2-txt)}
#parc-root .r2-champ[disabled]{opacity:.65;cursor:not-allowed}
#parc-root .r2-champ-n{width:96px}
#parc-root .r2-champ-h{width:110px}
#parc-root .r2-champ-s{padding:6px 8px}
#parc-root .r2-txt{width:100%;font-family:ui-monospace,SFMono-Regular,
  Menlo,monospace;font-size:12px;line-height:1.5}

/* --- 13. CE QUI CLOCHE / ECARTS */
#parc-root .r2-ctbl{display:flex;flex-direction:column}
#parc-root .r2-crow{display:grid;gap:12px;align-items:baseline;
  grid-template-columns:58px minmax(140px,1.4fr) 130px 170px 1.6fr 110px;
  padding:10px 2px;border-bottom:1px solid var(--r2-bord);font-size:12.5px}
#parc-root .r2-crow:last-child{border-bottom:0}
#parc-root .r2-crow-n{font-size:17px;font-weight:800;letter-spacing:-.02em}

/* --- 14. PIED */
#parc-root .r2-renvois{display:grid;gap:12px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
#parc-root .r2-renvoi{border:1px solid var(--r2-bord);border-radius:11px;
  padding:12px 13px;background:var(--r2-fond2)}
#parc-root .r2-pied-actions{display:flex;gap:10px;align-items:center;
  flex-wrap:wrap;margin-top:14px}
#parc-root .r2-partage{margin-top:12px;font-size:12px;font-weight:700;
  color:var(--r2-faible)}

/* --- 15. LES TIROIRS (etage 2) */
#parc-root .r2-voile{position:fixed;inset:0;background:var(--r2-scrim);
  opacity:0;pointer-events:none;transition:opacity .18s ease;z-index:60}
#parc-root .r2-voile.ouvert{opacity:1;pointer-events:auto}
#parc-root .r2-tiroir{position:fixed;top:0;right:0;bottom:0;width:460px;
  max-width:96vw;background:var(--r2-fond);border-left:1px solid var(--r2-bord);
  box-shadow:var(--r2-ombre);transform:translateX(102%);
  transition:transform .2s ease;z-index:61;overflow-y:auto;
  padding:16px 18px 40px}
#parc-root .r2-tiroir.ouvert{transform:translateX(0)}
#parc-root .r2-tiroir-t{display:flex;justify-content:space-between;
  align-items:center;gap:10px;margin-bottom:12px;position:sticky;top:-16px;
  background:var(--r2-fond);padding:6px 0}
#parc-root .r2-tiroir-p{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;
  padding-top:12px;border-top:1px solid var(--r2-bord)}
#parc-root .r2-profils{display:grid;gap:8px;margin:10px 0;
  grid-template-columns:1fr 1fr}
#parc-root .r2-prof{text-align:left;padding:9px 11px;border-radius:10px;
  border:1px solid var(--r2-bord2);background:var(--r2-fond2);font:inherit;
  cursor:pointer;color:var(--r2-txt)}
#parc-root .r2-prof.on{border-color:var(--r2-trait);background:var(--r2-doux)}
#parc-root .r2-prof b{display:block;font-size:12.5px}
#parc-root .r2-prof span{display:block;font-size:11px;color:var(--r2-gris);
  margin-top:2px;line-height:1.35}
#parc-root .r2-rgroupe{margin-top:18px;padding-top:12px;
  border-top:1px solid var(--r2-bord)}
#parc-root .r2-rl{padding:10px 0;border-bottom:1px solid var(--r2-bord)}
#parc-root .r2-rl-t{font-size:12.5px;font-weight:700}
#parc-root .r2-rl-c{display:flex;gap:7px;align-items:center;flex-wrap:wrap;
  margin:6px 0 4px}
#parc-root .r2-rl-u{font-size:10.5px;color:var(--r2-faible)}
#parc-root .r2-rl-p{font-size:11px;color:var(--r2-gris);line-height:1.45;
  margin-top:3px}
/* Un reglage que personne ne lit : visiblement en retrait, et sa raison en
   ambre juste dessous. Selecteur a deux classes (0,1,2,0) pour passer devant
   .r2-rl (0,1,1,0) sans !important — la specificite se calcule. */
#parc-root .r2-rl.r2-rl-inerte{opacity:.72}
#parc-root .r2-rl-inerte-p{font-size:11px;color:var(--r2-ambre);
  line-height:1.45;margin-top:4px}
#parc-root .r2-unite{font-size:11.5px;color:var(--r2-faible)}
#parc-root .r2-cadenas{font-size:11px;color:var(--r2-ambre);cursor:help}
#parc-root .r2-jours{display:flex;gap:4px;flex-wrap:wrap}
#parc-root .r2-jour{width:38px;padding:5px 0;border-radius:8px;
  border:1px solid var(--r2-bord2);background:var(--r2-fond2);
  color:var(--r2-gris);font:inherit;font-size:11px;cursor:pointer}
#parc-root .r2-jour.on{border-color:var(--r2-trait);background:var(--r2-doux);
  color:var(--r2)}
#parc-root .r2-fenetres,#parc-root .r2-repart{display:flex;
  flex-direction:column;gap:6px}
#parc-root .r2-fen,#parc-root .r2-rep{display:flex;gap:6px;align-items:center;
  flex-wrap:wrap;font-size:12px}
#parc-root .r2-rep-n{min-width:80px;font-weight:600}
#parc-root .r2-corr{border:1px solid var(--r2-ambre);border-radius:10px;
  padding:10px 12px;margin-bottom:10px;font-size:11.5px;color:var(--r2-gris);
  background:var(--r2-ambre-d)}
#parc-root .r2-corr ul{margin:6px 0 0;padding-left:16px;line-height:1.6}
#parc-root .r2-bascule{display:inline-flex;align-items:center;cursor:pointer}
#parc-root .r2-bascule input{position:absolute;opacity:0;width:0;height:0}
#parc-root .r2-bascule span{width:42px;height:23px;border-radius:99px;
  background:var(--r2-gris-d);border:1px solid var(--r2-bord2);
  position:relative;transition:.15s}
#parc-root .r2-bascule span::after{content:'';position:absolute;top:2px;
  left:2px;width:17px;height:17px;border-radius:50%;background:var(--r2-gris);
  transition:.15s}
#parc-root .r2-bascule input:checked + span{background:var(--r2-doux);
  border-color:var(--r2-trait)}
#parc-root .r2-bascule input:checked + span::after{left:21px;
  background:var(--r2)}

/* --- 16. CHARGEMENT ET SECOURS. Le message de secours n'a besoin
   d'AUCUN script : si /parc/app.js ne se charge pas (404, RBAC, cache),
   la page dirait sinon « Chargement… » pour toujours. */
#parc-root .r2-secours{display:flex;align-items:flex-start;gap:12px;
  padding:26px 2px;font-size:13px;color:var(--r2-gris)}
#parc-root .r2-rouet{width:20px;height:20px;border-radius:50%;flex-shrink:0;
  border:3px solid var(--r2-gris-d);border-top-color:var(--r2);
  animation:r2Spin .8s linear infinite}
#parc-root .r2-tard{opacity:0;animation:r2Voir 0s linear 6s forwards;
  font-size:12px;color:var(--r2-ambre);margin-top:6px;line-height:1.5}
@keyframes r2Spin{to{transform:rotate(360deg)}}
@keyframes r2Voir{to{opacity:1}}

/* --- 17. TELEPHONE. On ne demarre pas un parc de 250 comptes depuis un
   telephone dans le metro : le bouton de commande est masque, tout le
   reste (verdict, machines, journal) reste lisible. */
#parc-root .r2-mob{display:none;font-size:12px;color:var(--r2-gris);
  border:1px dashed var(--r2-bord2);border-radius:11px;padding:10px 13px;
  margin-bottom:10px;line-height:1.5}
@media(max-width:768px){
  #parc-root .r2-mob{display:block}
  #parc-root .r2-cmd .r2-b1{display:none}
  #parc-root .r2-barre{position:static}
  #parc-root .r2-verdict{font-size:16px}
  #parc-root .r2-pvl{grid-template-columns:12px 1fr;row-gap:2px}
  #parc-root .r2-pvl-a{text-align:left;grid-column:2}
  #parc-root .r2-crow{grid-template-columns:52px 1fr;row-gap:2px}
  #parc-root .r2-profils{grid-template-columns:1fr}
  #parc-root .r2-tiroir{width:100%;max-width:100%}
}
</style>"""

# La coquille. Elle ne contient AUCUN script en ligne : tout le rendu est
# fait par /parc/app.js. C'est la seule reponse structurelle au piege n°1 du
# projet (le JS qui vit dans des chaines Python, ou une apostrophe tue le
# script de la page entiere) : ici « node --check parc_app.js » verifie le
# fichier tel qu'il est servi.
_COQUILLE = """<div id="parc-root">
<div class="r2-mob">Vous etes sur telephone : la commande de demarrage est
masquee expres. Le verdict, les machines, les ecarts et le journal restent
lisibles — on demarre un parc devant un ecran, pas dans le metro.</div>
<div class="r2-secours">
<div class="r2-rouet"></div>
<div>Chargement du poste de pilotage…
<div class="r2-tard">Toujours rien apres six secondes : /parc/app.js n a pas
ete servi. A verifier dans l ordre — le fichier bot/parc_app.js existe,
parc_web.register() a bien tourne au demarrage, et le prefixe /parc/ est
declare dans le RBAC de web_upload.py (sans quoi la lecture rend 403).</div>
</div>
</div>
<div id="r2-bandeaux"></div>
<div id="r2-a"></div>
<div id="r2-b"></div>
<div id="r2-c"></div>
<div id="r2-d"></div>
<div id="r2-e"></div>
<div id="r2-f"></div>
<div id="r2-g"></div>
<div class="r2-voile" id="r2-voile"></div>
<div class="r2-tiroir" id="r2-tiroir" aria-hidden="true"></div>
</div>
<script src="/parc/app.js" defer></script>"""


def render_page() -> str:
    """La coquille + le style. TOUT le rendu vivant est fait par
    /parc/app.js (fichier separe), ce qui sort le JavaScript des chaines
    Python — donc plus d'apostrophe capable de tuer le script de la page
    entiere, et `node --check` marche directement sur le fichier."""
    return _STYLE + _COQUILLE


def register(app, is_auth):
    """Enregistre les routes. Appele depuis create_app() sous try/except : un
    module casse ne doit pas emporter le dashboard, dont depend l'equipe."""
    from flask import request, jsonify, send_file, Response, session

    def _qui() -> str:
        try:
            return (session.get("username") or "?")[:40]
        except Exception:
            return "?"

    def _json_toujours(fn):
        """Toute exception d'une route /parc/ ressort en JSON.

        Sans ca, une exception rendait la page d'erreur HTML de Flask :
        500 text/html. Cote navigateur, r.json() rejetait et le clic ne
        faisait RIEN — ni toast, ni trace, ni couleur qui change. Les routes
        de lecture (/parc/state, /parc/plan) avaient deja leur try/except ;
        les sept routes d'ECRITURE, celles qui demarrent et arretent le
        parc, n'en avaient aucun.

        functools.wraps est LOAD-BEARING : Flask nomme l'endpoint d'apres
        __name__, et sept vues appelees « _emballe » se seraient ecrasees
        les unes les autres au demarrage.
        """
        @functools.wraps(fn)
        def _emballe(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:
                detail = "%s: %s" % (type(e).__name__, str(e)[:160])
                try:
                    journal("plan_decision", objet="plan", par=_qui(),
                            code="erreur_interne",
                            detail="%s a leve : %s" % (fn.__name__, detail))
                except Exception:
                    pass
                print("[parc] %s : %s" % (fn.__name__, detail), flush=True)
                return jsonify({"ok": False, "error": detail}), 500
        return _emballe

    # ---------- l'observateur ----------
    @app.after_request
    def _parc_observateur(reponse):
        """Ecoute les 4 routes du poste et DERIVE ce que le poste ne dit pas.

        Il ne modifie AUCUNE reponse et ne peut pas faire echouer la requete
        observee : tout est sous try/except. C'est ce qui rend les trois tris
        par date, les durees et le compteur de chutes de WDA possibles sans
        une ligne de changement cote poste.
        """
        try:
            if request.method != "POST":
                return reponse
            # Sous banc d'essai on n'observe RIEN : sinon la suite de tests
            # ecrit dans les vraies donnees (voir observateur_actif()).
            if not observateur_actif():
                return reponse
            chemin = request.path or ""
            if not chemin.startswith("/api/rig/"):
                return reponse
            if reponse.status_code >= 400:
                return reponse          # un refus de jeton n'est pas une mesure
            if chemin == "/api/rig/parc":
                observer_parc()
            elif chemin == "/api/rig/pull":
                corps = request.get_json(silent=True) or {}
                corps = corps if isinstance(corps, dict) else {}
                observer_pull(corps)
                # QUI vient de tirer du travail : c'est la seule occasion de
                # savoir quelle machine prend quel travail. Sans ce nom, tout
                # etait attribue a poste-1 en dur.
                observer_jobs("pull",
                              machine=str(corps.get("machine") or "").strip()[:40])
            elif chemin in ("/api/rig/report", "/api/rig/jobs"):
                observer_jobs(chemin.rsplit("/", 1)[-1])
        except Exception as e:
            print("[parc] observateur : %s" % str(e)[:160], flush=True)
        return reponse

    # ---------- l'asset ----------
    @app.route("/parc/app.js")
    def parc_app_js():
        # L'extension .js est LOAD-BEARING : le garde de lecture de
        # web_upload exempte les assets par extension. Renommer cette route
        # sans .js la ferait tomber en 403 pour tout role restreint.
        if not is_auth():
            return "", 401
        p = BOT_DIR / "parc_app.js"
        if not p.exists():
            return ("// parc_app.js manquant — la page restera sur son "
                    "message de chargement", 404)
        return send_file(str(p), mimetype="text/javascript", conditional=True)

    # ---------- lecture ----------
    @app.route("/parc/state")
    def parc_state():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            return jsonify(etat_complet())
        except Exception as e:
            return jsonify({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    @app.route("/parc/regles")
    def parc_regles_get():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify({"ok": True, "regles": charger_regles(),
                        "meta": regles_meta(),
                        "profils": {k: {"titre": v["titre"], "quand": v["quand"],
                                        "valeurs": v["valeurs"]}
                                    for k, v in PROFILS.items()}})

    @app.route("/parc/plan")
    def parc_plan():
        """Le plan, LISIBLE ET VERIFIABLE — rien n'est execute."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            return jsonify({"ok": True, **planifier()})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/parc/prevol")
    def parc_prevol():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify({"ok": True, **prevol()})

    @app.route("/parc/liste")
    def parc_liste():
        """Le parc : agrege par defaut, detaille a la demande. Tri et
        pagination COTE SERVEUR — a 250 comptes, trier en JS voudrait dire
        transporter 250 lignes a chaque rafraichissement."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        vue = (request.args.get("vue") or "agregee").strip()
        if vue == "agregee":
            return jsonify({"ok": True, "vue": "agregee", **parc_agrege()})
        return jsonify({"ok": True, "vue": "detaillee", **parc_detaille(
            tri=(request.args.get("tri") or "retard").strip(),
            sens=(request.args.get("sens") or "asc").strip(),
            page=int(request.args.get("page") or 1),
            machine=(request.args.get("machine") or "").strip(),
            categorie=(request.args.get("cat") or "").strip(),
            statut=(request.args.get("statut") or "").strip(),
            q=(request.args.get("q") or "").strip()[:60],
            filtre=(request.args.get("filtre") or "").strip())})

    @app.route("/parc/journal")
    def parc_journal_route():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        args = dict(evt=(request.args.get("evt") or "").strip(),
                    objet=(request.args.get("objet") or "").strip(),
                    machine=(request.args.get("machine") or "").strip(),
                    conteneur=(request.args.get("conteneur") or "").strip(),
                    code=(request.args.get("code") or "").strip(),
                    texte=(request.args.get("q") or "").strip()[:80],
                    depuis_s=int(request.args.get("depuis") or 0),
                    page=int(request.args.get("page") or 1),
                    par_page=int(request.args.get("par_page") or 100))
        if (request.args.get("format") or "") == "jsonl":
            # Export par un vrai lien : a.click() declenche en script est
            # bloque dans ce projet.
            d = journal_lire(**dict(args, par_page=1000, page=1))
            corps = "\n".join(json.dumps(l, ensure_ascii=False) for l in d["lignes"])
            return Response(corps, mimetype="application/x-ndjson", headers={
                "Content-Disposition": "attachment; filename=parc_journal.jsonl"})
        return jsonify({"ok": True, **journal_lire(**args)})

    @app.route("/parc/ecarts")
    def parc_ecarts_route():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify({"ok": True, "lignes": ecarts_resume()})

    # ---------- ecriture ----------
    @app.route("/parc/regles", methods=["POST"])
    @_json_toujours
    def parc_regles_post():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            brut = json.loads(request.form.get("regles")
                              or request.get_data(as_text=True) or "{}")
        except Exception as e:
            return jsonify({"ok": False, "error": "JSON invalide: %s" % e})
        if not isinstance(brut, dict):
            return jsonify({"ok": False, "error": "un objet de reglages est attendu"})
        return jsonify(enregistrer_regles(brut, par=_qui()))

    @app.route("/parc/regles/profil", methods=["POST"])
    @_json_toujours
    def parc_profil_post():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify(appliquer_profil(request.form.get("profil") or "", par=_qui()))

    @app.route("/parc/simuler", methods=["POST"])
    @_json_toujours
    def parc_simuler():
        """Recalcule les tuiles de consequence SANS RIEN ECRIRE : c'est ce
        qui permet d'essayer une valeur avant de l'enregistrer."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            brut = json.loads(request.form.get("regles") or "{}")
        except Exception as e:
            return jsonify({"ok": False, "error": "JSON invalide: %s" % e})
        propres, corriges, inconnues = valider_regles(brut if isinstance(brut, dict) else {})
        return jsonify({"ok": True, "corriges": corriges, "inconnues": inconnues,
                        **simuler(propres)})

    @app.route("/parc/pilote", methods=["POST"])
    @_json_toujours
    def parc_pilote():
        """La bascule. Le pre-vol est rejoue a chaque demarrage ; franchir
        une reserve demande `force=1` et laisse une trace."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        on = (request.form.get("on") or "").strip() in ("1", "true", "oui")
        force = (request.form.get("force") or "").strip() in ("1", "true", "oui")
        regles = charger_regles()
        e = charger_etat()
        if on:
            pv = prevol()
            if not pv["peut_demarrer"]:
                journal("prevol", objet="plan", par=_qui(), code="refus_garde_fou",
                        detail="demarrage refuse : " + ", ".join(pv["bloquants"][:4]))
                return jsonify({"ok": False, "error": "pre-vol bloquant",
                                "bloquants": pv["bloquants"]})
            if pv["ambres"] and not force:
                return jsonify({"ok": False, "confirmation": True,
                                "reserves": pv["ambres"],
                                "error": "%d reserve(s) — confirmer" % pv["ambres"]})
            if pv["ambres"]:
                journal("prevol_force", objet="plan", par=_qui(),
                        detail="%d reserve(s) franchie(s)" % pv["ambres"])
            e["pilote_depuis"] = int(maintenant())
        else:
            e["pilote_depuis"] = 0
        regles["pilote"] = on
        with _LOCK_REGLES:
            safe_json.write(REGLES_FILE, regles, indent=1)
        enregistrer_etat(e)
        journal("pilote_on" if on else "pilote_off", objet="plan", par=_qui(),
                detail="le pilote %s — l'horloge joue un tour toutes les %d s "
                       "et inscrit dans la file du poste"
                       % ("demarre" if on else "s'arrete",
                          int(regles.get("tick_s") or 60)))
        return jsonify({"ok": True, "pilote": on})

    @app.route("/parc/pause", methods=["POST"])
    @_json_toujours
    def parc_pause():
        """« Je pars, ne fais rien ce soir » — le geste qui manque partout."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        # heures = 0 LEVE la pause. Sans ce cas, la route ne savait
        # qu'arreter : une pause posee par erreur tenait douze heures et rien
        # dans le site ne pouvait la lever. Un bouton qui arrete sans bouton
        # qui repart n'est pas un bouton, c'est un piege.
        brut = request.form.get("heures")
        if brut is None:
            brut = (request.get_json(silent=True) or {}).get("heures")
        try:
            demande = int(brut) if brut is not None else 12
        except (TypeError, ValueError):
            demande = 12

        e = charger_etat()
        if demande <= 0:
            e["pause_jusqu_a"] = 0
            enregistrer_etat(e)
            journal("pilote_on", objet="plan", par=_qui(),
                    detail="pause levee")
            return jsonify({"ok": True, "jusqu_a": 0, "en_pause": False})

        heures = max(1, min(168, demande))
        e["pause_jusqu_a"] = int(maintenant() + heures * 3600)
        enregistrer_etat(e)
        journal("pilote_off", objet="plan", par=_qui(),
                detail="pause de %d h demandee" % heures)
        return jsonify({"ok": True, "jusqu_a": e["pause_jusqu_a"],
                        "en_pause": True})

    @app.route("/parc/tick", methods=["POST"])
    @_json_toujours
    def parc_tick():
        """Joue un tour d'ordonnanceur EN SIMULATION et le journalise."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify(tick(par=_qui()))

    @app.route("/parc/conteneur/quarantaine", methods=["POST"])
    @_json_toujours
    def parc_quarantaine():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        nom = (request.form.get("conteneur") or "").strip()
        motif = (request.form.get("motif") or "manuel").strip()[:40]
        fait = mettre_en_quarantaine(nom, motif, par=_qui())
        return jsonify({"ok": True, "modifie": int(fait),
                        "note": "" if fait else "deja en quarantaine, ou nom vide"})

    @app.route("/parc/conteneur/rehabiliter", methods=["POST"])
    @_json_toujours
    def parc_rehabiliter():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        nom = (request.form.get("conteneur") or "").strip()
        fait = rehabiliter(nom, par=_qui())
        return jsonify({"ok": True, "modifie": int(fait),
                        "note": "" if fait else "ce conteneur n'etait pas en quarantaine"})

    @app.route("/parc/machine/suspendre", methods=["POST"])
    @_json_toujours
    def parc_machine_suspendre():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        nom = (request.form.get("machine") or "").strip()[:40]
        on = (request.form.get("on") or "1").strip() in ("1", "true", "oui")
        e = charger_etat()
        m = e.setdefault("machines", {}).setdefault(nom, {})
        m["suspendue"] = on
        m["depuis"] = int(maintenant())
        enregistrer_etat(e)
        journal("incident_ouvert" if on else "incident_acquitte", objet="poste",
                machine=nom, par=_qui(),
                detail="machine %s" % ("suspendue" if on else "reprise"))
        return jsonify({"ok": True, "machine": nom, "suspendue": on})

    @app.route("/parc/inventaire", methods=["POST"])
    @_json_toujours
    def parc_inventaire_post():
        """Le recensement REEL du telephone, colle a la main ou pousse par le
        poste. C'est la seule chose qui peut rendre vert le controle
        « le registre correspond au telephone »."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            d = json.loads(request.form.get("inventaire")
                           or request.get_data(as_text=True) or "{}")
        except Exception as e:
            return jsonify({"ok": False, "error": "JSON invalide: %s" % e})
        if not isinstance(d, dict):
            return jsonify({"ok": False, "error": "un objet est attendu"})
        return jsonify(observer_inventaire(d, par=_qui()))

    # ---------- l'horloge ----------
    # C'est ICI que « ca tourne tout seul » commence. Elle ne demarre pas
    # sous banc d'essai : un thread qui inscrit des travaux pendant
    # tests_site.py ecrirait dans les vraies donnees ET dans la file du
    # poste. Elle ne demarre pas non plus dans le processus rechargeur de
    # Flask (WERKZEUG_RUN_MAIN absent quand le reloader est actif), sinon
    # deux horloges tournent en developpement.
    import os as _os
    if not observateur_actif():
        print("[parc] horloge NON demarree (banc d'essai)", flush=True)
    elif _os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        print("[parc] horloge NON demarree (processus rechargeur)", flush=True)
    elif demarrer_horloge():
        print("[parc] horloge demarree — un tour toutes les %d s ; "
              "le pilote est %s"
              % (int(charger_regles().get("tick_s") or 60),
                 "EN MARCHE" if charger_regles().get("pilote") else "a l'arret"),
              flush=True)

    print("[parc] poste de pilotage enregistre (%d reglages, %d garde-fous)"
          % (len(REGLAGES), len(GARDEFOUS)), flush=True)
