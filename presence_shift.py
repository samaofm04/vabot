# -*- coding: utf-8 -*-
"""presence_shift.py — Etait-il a son shift ? Le raisonnement, sans Discord.

CE QUE CE MODULE FAIT, ET CE QU IL NE FAIT PAS

Il ne parle pas a Discord. Il tient le RELEVE (qui a ete vu en vocal,
combien de temps, a partir de quand) et rend le VERDICT (a l heure, en
retard, absent, ou — et c est le plus important — pas jugeable). Le cog se
contente de lui dire chaque minute « voici qui est en vocal ». Tout ce qui
est ici se teste sans bot, sans reseau et sans serveur Discord.

POURQUOI ON RELEVE CHAQUE MINUTE AU LIEU D ECOUTER LES ENTREES ET SORTIES

Meme raison que sessions_voc, et elle a deja ete payee : `on_voice_state_update`
ne survit pas a un redemarrage — ceux qui etaient deja connectes n existent
plus pour le bot — et un evenement perdu laisse quelqu un « present »
indefiniment. Le VPS redemarre le service des qu un commit arrive sur main,
c est-a-dire n importe quand. Relever la liste chaque minute mesure du temps
reellement passe et se repare tout seul au tour suivant.

LA REGLE QUI COMMANDE TOUTES LES AUTRES : PAS DE SIGNAL = PAS DE VERDICT

Un creneau que le bot n a pas pu observer ne produit NI « Retard » NI
« Present ». Il produit « non verifiable », qui se compte et s affiche. Sans
cette regle, une coupure du bot pendant la nuit accuserait tout le monde le
lendemain matin — et comme « Present » est aussi la valeur par defaut d une
case jamais touchee, l absence de signal se lirait comme une presence
CONSTATEE. Les deux erreurs sont symetriques et toutes deux inacceptables :
l une accuse un innocent, l autre blanchit un absent.

C est pour ca que le releve compte ses TOURS. Un minimum global (« le
registre a commence a telle heure ») ne detecte pas un trou au milieu : une
panne de cinquante-cinq minutes passerait pour une observation complete. On
compare donc les tours REUSSIS aux tours ATTENDUS sur la fenetre, fenetre
par fenetre.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import safe_json
import chatting

DATA_DIR = Path(__file__).resolve().parent / "data"
RACINE = DATA_DIR / "presence_vocal"
FICHIER_CFG = DATA_DIR / "presence_shift_cfg.json"
FICHIER_ETAT = DATA_DIR / "presence_shift_etat.json"

CFG_DEFAUT = {
    # Rien n est ecrit sur le planning tant que ce n est pas arme. Un
    # pointage qui demarrerait tout seul le jour du deploiement ecrirait sur
    # des donnees que personne n a eu le temps de regarder.
    "ecrire": False,
    "guilde": "YouLab AGENCY",

    # Arriver un peu avant, c est etre a l heure. Repris de sessions_voc,
    # ou ce reglage sert deja aux VA.
    "avance_toleree_min": 15,

    # Le delai de grace APRES le debut du shift. « Retard cash » veut dire
    # court, pas nul : a zero, quelqu un qui se connecte a 08h00m30s serait
    # pointe en retard. Mesure sur les 161 arrivees reelles des VA : 63 %
    # sont la a l heure ou en avance, 22 % ont plus d une heure de retard.
    "grace_min": 5,

    # Sous ce seuil, ce n est pas une prise de poste : c est un passage.
    "presence_min_s": 300,

    # En dessous de cette part de tours reussis sur la fenetre de decision,
    # on ne juge pas. C est le garde-fou anti-panne.
    "couverture_min": 0.70,

    # Le partage d ecran est RELEVE mais ne fait pas le verdict par defaut.
    # Marquer quelqu un en retard parce qu il n a pas partage son ecran
    # alors qu il est la et qu il travaille serait un faux positif dur a
    # defendre. Mettre a true en connaissance de cause.
    "exiger_partage": False,
}


def config() -> dict:
    d = safe_json.load(str(FICHIER_CFG), default=None)
    cfg = dict(CFG_DEFAUT)
    if isinstance(d, dict):
        cfg.update({k: v for k, v in d.items() if k in CFG_DEFAUT})
    return cfg


def _fichier(jour_shift: str) -> Path:
    return RACINE / ("%s.json" % str(jour_shift)[:10])


def lire_releve(jour_shift: str) -> Dict[str, Any]:
    d = safe_json.load(str(_fichier(jour_shift)), default=None)
    if not isinstance(d, dict) or not isinstance(d.get("creneaux"), dict):
        return {"jour": jour_shift, "creneaux": {}}
    return d


def enregistrer_tour(jour_shift: str, creneau: str, vus: Dict[str, Dict[str, Any]],
                     quand: Optional[float] = None, pas_s: int = 60) -> Dict[str, Any]:
    """Un tour d observation : qui est en vocal maintenant, et depuis quand.

    `vus` = {user_id: {"nom": str, "partage": bool}}. Un dictionnaire VIDE
    est une observation valide — « j ai regarde, il n y avait personne » —
    et il compte comme un tour. C est tout l interet : ne pas confondre
    « personne n etait la » avec « je n ai pas regarde ».

    Le cog appelle cette fonction UNIQUEMENT quand il a reellement pu lire
    l etat du serveur. S il n a pas pu, il n appelle pas, et le tour manque
    — ce qui fera baisser la couverture, donc suspendre le verdict.
    """
    quand = quand if quand is not None else datetime.now(timezone.utc).timestamp()
    d = lire_releve(jour_shift)
    d["jour"] = jour_shift
    bloc = d["creneaux"].setdefault(creneau, {"tours": 0, "tours_fenetre": 0, "gens": {}})
    bloc["tours"] = int(bloc.get("tours", 0)) + 1
    # ET, SEPAREMENT, les tours tombes DANS la fenetre de decision.
    # Comparer le total du shift aux tours attendus sur la seule prise de
    # poste saturerait toujours le ratio : 360 tours pour 20 attendus sur un
    # shift de six heures. Une panne pile a 08h00 passerait alors pour une
    # observation complete — exactement le trou au milieu qu un minimum
    # global ne voit pas.
    fen = fenetre_decision(creneau, jour_shift, config())
    if fen and fen[0].timestamp() <= quand <= fen[1].timestamp():
        bloc["tours_fenetre"] = int(bloc.get("tours_fenetre", 0)) + 1
    bloc["dernier_tour"] = quand
    bloc.setdefault("premier_tour", quand)
    for uid, info in (vus or {}).items():
        g = bloc["gens"].setdefault(str(uid), {
            "secondes": 0, "partage_s": 0, "premiere": quand, "derniere": quand, "nom": ""})
        g["secondes"] = int(g.get("secondes", 0)) + pas_s
        if info.get("partage"):
            g["partage_s"] = int(g.get("partage_s", 0)) + pas_s
        g["derniere"] = quand
        g["premiere"] = min(float(g.get("premiere", quand)), quand)
        if info.get("nom"):
            g["nom"] = info["nom"]
    safe_json.write(str(_fichier(jour_shift)), d)
    return d


def fenetre_decision(creneau: str, jour_shift: str, cfg: dict):
    """Le moment ou l on juge la prise de poste : [debut - avance, debut + grace].

    Juger sur tout le shift repondrait a une autre question (« a-t-il
    travaille ? ») que celle posee (« etait-il la a l heure ? »).
    """
    f = chatting.fenetre_shift(creneau, jour_shift)
    if not f:
        return None
    return (f["debut"] - timedelta(minutes=int(cfg["avance_toleree_min"])),
            f["debut"] + timedelta(minutes=int(cfg["grace_min"])),
            f)


def couverture(jour_shift: str, creneau: str, maintenant: datetime,
               cfg: dict) -> Dict[str, Any]:
    """Quelle part de la fenetre de decision a REELLEMENT ete observee.

    Rend {"tours", "attendus", "part", "suffisante"}. Un minimum global ne
    detecterait pas un trou au milieu : on compte des tours, pas une date de
    debut.
    """
    fen = fenetre_decision(creneau, jour_shift, cfg)
    if not fen:
        return {"tours": 0, "attendus": 0, "part": 0.0, "suffisante": False}
    debut, fin, _ = fen
    bloc = (lire_releve(jour_shift).get("creneaux") or {}).get(creneau) or {}
    ecoule = min(maintenant, fin).timestamp() - debut.timestamp()
    attendus = max(0, int(ecoule // 60))
    tours = int(bloc.get("tours_fenetre", 0))
    part = (tours / attendus) if attendus else 0.0
    return {"tours": tours, "attendus": attendus, "part": round(min(part, 1.0), 3),
            "suffisante": attendus > 0 and part >= float(cfg["couverture_min"])}


def verdict_ligne(row: Dict[str, Any], user_id: Optional[str], jour_shift: str,
                  maintenant: datetime, cfg: dict) -> Dict[str, Any]:
    """Le verdict d UNE ligne du planning, ou la raison de s abstenir.

    Rend {"valeur": "Present"|"Retard"|"Absent"|None, "motif": str}.

    valeur None n est pas un echec : c est le troisieme etat, celui qui
    empeche d accuser quelqu un qu on n a pas pu regarder. Le motif est
    toujours rempli — « ne jamais ecarter en silence ».
    """
    creneau = (row.get("creneau") or "").strip()
    fen = fenetre_decision(creneau, jour_shift, cfg)
    if not fen:
        return {"valeur": None, "motif": "creneau sans horaire connu : %r" % creneau}
    debut, fin_grace, f = fen

    if maintenant < fin_grace:
        return {"valeur": None, "motif": "shift pas encore juge"}

    jour_cle = chatting.DAYS[datetime.fromisoformat(jour_shift).weekday()] \
        if len(jour_shift) == 10 else ""
    if jour_cle and chatting.jour_de_repos(row) == jour_cle:
        return {"valeur": None, "motif": "jour de repos declare"}

    if not user_id:
        return {"valeur": None, "motif": "ligne non rattachee a un compte Discord"}

    cov = couverture(jour_shift, creneau, maintenant, cfg)
    if not cov["suffisante"]:
        return {"valeur": None,
                "motif": "creneau non observe (%d tours sur %d attendus)"
                         % (cov["tours"], cov["attendus"])}

    bloc = (lire_releve(jour_shift).get("creneaux") or {}).get(creneau) or {}
    g = (bloc.get("gens") or {}).get(str(user_id))
    if not g:
        return {"valeur": "Absent", "motif": "jamais vu en vocal de tout le shift"}

    assez = int(g.get("secondes", 0)) >= int(cfg["presence_min_s"])
    if not assez:
        return {"valeur": "Absent",
                "motif": "vu %d s seulement, sous le seuil de %d s"
                         % (int(g.get("secondes", 0)), int(cfg["presence_min_s"]))}

    arrivee = float(g.get("premiere", 0))
    if arrivee <= fin_grace.timestamp():
        if cfg.get("exiger_partage") and not int(g.get("partage_s", 0)):
            return {"valeur": "Retard", "motif": "present mais sans partage d ecran"}
        return {"valeur": "Present", "motif": "en vocal a l heure"}

    minutes = int((arrivee - f["debut"].timestamp()) // 60)
    return {"valeur": "Retard", "motif": "arrive %d min apres le debut" % minutes}


def appliquer(resoudre=None, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Passe tout le planning en revue et ecrit ce qui est jugeable.

    `resoudre(handle) -> user_id | None` est fourni par l appelant : c est
    le SEUL endroit qui parle a Discord, et il reste dehors. Le module
    garde ainsi sa propriete d etre testable sans bot — et le rattachement
    handle -> membre continue de se decider a un seul endroit dans le depot
    plutot que d etre reecrit ici.

    Rend un bilan CHIFFRE de tout, y compris de ce qui n a pas ete ecrit :
    la plupart des « ca ne marche pas » de ce projet venaient de quelque
    chose d ignore sans trace.
    """
    cfg = config()
    maintenant = maintenant or datetime.now(timezone.utc)
    bilan = {"ecrit": 0, "refuse": 0, "abstenu": 0, "lignes": 0,
             "non_rattachees": 0, "motifs": {}, "ecrire": bool(cfg["ecrire"])}

    def compter(motif):
        bilan["motifs"][motif] = bilan["motifs"].get(motif, 0) + 1

    # La veille aussi : un shift de nuit commence hier et se juge ce matin.
    ici = maintenant.astimezone(chatting._zone())
    jours = [(ici.date() - timedelta(days=1)).isoformat(), ici.date().isoformat()]

    for e in chatting.list_edts():
        for row in e.get("rows") or []:
            handle = (row.get("discord_username") or "").strip()
            uid = None
            if handle and resoudre:
                try:
                    uid = resoudre(handle)
                except Exception:
                    uid = None      # resolveur muet = ligne non jugeable, pas accusee
            for jour_shift in jours:
                f = chatting.fenetre_shift((row.get("creneau") or "").strip(), jour_shift)
                if not f or f["fin"] > maintenant:
                    continue          # shift pas termine : rien a juger encore
                bilan["lignes"] += 1
                v = verdict_ligne(row, uid, jour_shift, maintenant, cfg)
                if v["valeur"] is None:
                    bilan["abstenu"] += 1
                    if "non rattachee" in v["motif"]:
                        bilan["non_rattachees"] += 1
                    compter(v["motif"])
                    continue
                if not cfg["ecrire"]:
                    compter("simulation : " + v["motif"])
                    continue
                jcle = chatting.DAYS[datetime.fromisoformat(jour_shift).weekday()]
                sem = chatting.week_start_for(datetime.fromisoformat(jour_shift).date()).isoformat()
                r = chatting.poser_auto(e["id"], row["id"], sem, jcle,
                                        v["valeur"], v["motif"])
                if r["ok"]:
                    bilan["ecrit"] += 1
                else:
                    bilan["refuse"] += 1
                    compter("refus : " + r["raison"])
    try:
        safe_json.write(str(FICHIER_ETAT), dict(
            bilan, quand=maintenant.isoformat(timespec="seconds")))
    except Exception:
        pass
    return bilan
