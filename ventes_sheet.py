# -*- coding: utf-8 -*-
"""Ventes des chatteurs poussees dans un Google Sheet, tenu a jour tout seul.

L'export Excel donne une photo a un instant donne ; ici le classeur reste
vivant : on le laisse ouvert dans un onglet et il se met a jour.

Reutilise le compte de service deja en place pour la synchro Jailbreak
(sheets_sync) — rien de nouveau a configurer cote Google.
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
from pathlib import Path

import safe_json
import ventes_export

DATA_DIR = Path("data")
CONFIG = DATA_DIR / "ventes_sheet.json"

ONGLET_VENTES = "Ventes"
ONGLET_CHATTEURS = "Par chatteur"
ONGLET_QUINZAINE = "Par quinzaine"
ONGLET_FICHES = "Fiches chatteurs"
ONGLET_PAIE = "Paie quinzaine"
ONGLET_RAPPRO = "Site vs registre"

_ETAT = {"state": "idle", "ts": 0, "lignes": 0, "err": "",
         # periode reellement dans le classeur, et par qui elle y a ete mise :
         # sans ca, personne ne peut savoir ce qu'il lit.
         "periode": "", "source": "", "auto_pause": 0}
_LOCK = threading.Lock()

# Duree pendant laquelle une poussee faite A LA MAIN n'est pas ecrasee par la
# boucle automatique. Sans ce respit, une periode poussee pour examiner une
# vente contestee vivait moins de 5 minutes : le temps d'ouvrir le classeur,
# elle avait deja ete remplacee. Le respit expire tout seul — un classeur qui
# resterait fige sur une vieille periode serait un defaut pire.
RESPIT_MANUEL_S = 30 * 60


def load_config() -> dict:
    try:
        return safe_json.load(CONFIG, default={}) or {}
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_json.write(CONFIG, cfg, indent=2)


# Classeur par defaut, fourni par le proprietaire du site. La configuration
# posee depuis l'interface prime toujours : changer de classeur ne demande
# donc pas de toucher au code.
SHEET_DEFAUT = "1ulu1fGir3BDNRfiadaVtJpOOdcbwqHVnf0EEXEAvXAg"


def sheet_id() -> str:
    return str(load_config().get("sheet") or SHEET_DEFAUT or "").strip()


def set_sheet(url_or_id: str) -> str:
    """Accepte l'URL complete du classeur ou son seul identifiant."""
    import re
    t = (url_or_id or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})", t)
    ident = m.group(1) if m else t
    cfg = load_config()
    cfg["sheet"] = ident
    save_config(cfg)
    return ident


def disponible() -> bool:
    """Le compte de service Google est-il utilisable ?"""
    try:
        import sheets_sync
        return bool(sheets_sync.gspread_available())
    except Exception:
        return False


def etat() -> dict:
    with _LOCK:
        return dict(_ETAT)


def _set(**kw):
    with _LOCK:
        _ETAT.update(kw)


def _client():
    """Le meme compte de service que la synchro Jailbreak."""
    import sheets_sync
    return sheets_sync._client()


def _colonne_a1(n: int) -> str:
    """Numero de colonne -> lettre(s) : 1 -> A, 27 -> AA."""
    lettres = ""
    while n > 0:
        n, reste = divmod(n - 1, 26)
        lettres = chr(65 + reste) + lettres
    return lettres


def _onglet(classeur, titre: str, colonnes: int):
    """Recupere l'onglet, le cree s'il manque."""
    try:
        return classeur.worksheet(titre)
    except Exception:
        return classeur.add_worksheet(title=titre, rows=1000, cols=max(colonnes, 8))


def _ecrire(classeur, titre: str, grille, gras_sur: str = "",
            marqueur: str = "") -> None:
    """Ecrit une grille entiere dans son onglet, en l'agrandissant au besoin.

    Un onglet Google a une taille FIXE : ecrire au-dela de sa grille echoue.
    La feuille de paie etale une colonne par vente — sa largeur depend donc
    des donnees du mois et ne peut pas etre decidee a l'avance.

    `marqueur` est pose sur CHAQUE onglet, juste apres les donnees : il dit
    quelle periode l'onglet couvre. Il n'y etait que sur « Ventes », si bien
    qu'on pouvait payer une quinzaine en lisant un onglet qui en montrait une
    autre sans que rien ne le signale.
    """
    if not grille:
        return
    hauteur = len(grille) + 20                 # marge : evite un resize par ligne
    # +3 : une colonne de respiration, puis la colonne du marqueur.
    largeur = max(len(r) for r in grille) + 3
    ws = _onglet(classeur, titre, largeur)
    try:
        if ws.row_count < hauteur or ws.col_count < largeur:
            ws.resize(rows=max(hauteur, ws.row_count),
                      cols=max(largeur, ws.col_count))
    except Exception:
        pass
    ws.clear()
    # Toutes les lignes n'ont pas la meme longueur (une par vente) : on les
    # complete, sinon l'API refuse la grille.
    large = max(len(r) for r in grille)
    plates = [list(r) + [""] * (large - len(r)) for r in grille]
    ws.update("A1", plates, value_input_option="RAW")
    if marqueur:
        try:
            ws.update("%s1" % _colonne_a1(large + 2), [[marqueur]],
                      value_input_option="RAW")
        except Exception:
            pass
    try:
        ws.freeze(rows=1)
        if gras_sur:
            ws.format(gras_sur, {"textFormat": {"bold": True}})
    except Exception:
        pass


def contexte_reel(transactions) -> tuple:
    """(commissions par chatteur, taux EUR->USD du jour), lus a la source.

    Sans ca, une poussee qui ne les fournit pas ecrit une feuille de paie a
    0 % de commission — donc « A payer (USD) » a 0,00 pour tout le monde — et
    convertit les euros au taux de repli 1,14 au lieu du taux BCE du jour.
    Constate a l'execution : web_upload.py appelle pousser_async(tx, periode=…)
    sans aucun de ces deux arguments (c'est le bouton de la page Revenus),
    et l'onglet « Paie quinzaine » sortait avec Commission 0 % / A payer 0,00
    pour chaque chatteur. La boucle automatique, elle, les fournissait :
    les deux poussees ecrivaient donc des montants differents dans le meme
    onglet, selon qui avait pousse en dernier.
    """
    import mypuls
    try:
        taux = float(mypuls.get_eur_usd_rate()["rate"]) or 1.14
    except Exception:
        taux = 1.14
    comm = {}
    for nom in {(t.get("chatter") or "").strip() for t in (transactions or [])}:
        if not nom:
            continue
        # Un try PAR NOM : quand il englobait toute la boucle, un seul nom
        # illisible laissait la table a moitie remplie et les chatteurs
        # suivants repartaient a 0 % de commission.
        try:
            comm[nom] = float(mypuls.get_chatter_meta(nom)["commission_pct"])
        except Exception:
            pass
    return comm, taux


def preparer(transactions, commissions=None, eur_usd: float = 1.14,
             chatters=None, diagnostic=None) -> tuple:
    """Transactions -> les grilles a ecrire, un onglet chacune. Testable seul."""
    lignes = ventes_export.lignes_ventes(transactions)
    entetes = ventes_export.COLONNES
    cols_recap, recap = ventes_export.recap_par_chatteur(lignes)
    cols_q, recap_q = ventes_export.recap_par_quinzaine(lignes)
    fiches = [["Chatteur", "Quand", "Compte", "Fan", "Montant"]] +         ventes_export.fiches_chatteurs(lignes)
    cols_p, paie = ventes_export.paie_quinzaine(lignes, commissions=commissions,
                                                eur_usd=eur_usd)
    cols_r, rappro = ventes_export.rapprochement(lignes, chatters, diagnostic)
    # Les lignes ecrites portent la quinzaine en clair ; le tri, lui, s'est
    # deja fait sur la cle technique.
    return (([entetes] + ventes_export.lignes_affichables(lignes)),
            ([cols_recap] + recap), ([cols_q] + recap_q),
            fiches, ([cols_p] + paie), ([cols_r] + rappro))


def pousser(transactions, periode: str = "", commissions=None,
            eur_usd: float = None, chatters=None, diagnostic=None,
            auto: bool = False) -> dict:
    """Ecrit les ventes dans le classeur. Retourne {ok, lignes, err}.

    `auto` : reserve a la boucle de rafraichissement. Tout le reste — bouton
    de la page, adresse /ventes-sheet — est une poussee A LA MAIN, et une
    poussee a la main tient la boucle a distance le temps d'etre lue
    (cf. RESPIT_MANUEL_S).

    `commissions` et `eur_usd` omis ne valent plus « 0 % » et « 1,14 » : ils
    sont lus a la source (cf. contexte_reel). Un appelant qui les fournit
    reste prioritaire — c'est le cas de la boucle et de /ventes-sheet.
    """
    sid = sheet_id()
    if not sid:
        return {"ok": False, "err": "Aucun classeur configure"}
    if not disponible():
        return {"ok": False, "err": "Compte de service Google indisponible"}
    if commissions is None or eur_usd is None:
        _comm, _taux = contexte_reel(transactions)
        if commissions is None:
            commissions = _comm
        if eur_usd is None:
            eur_usd = _taux
    grille, recap, quinz, fiches, paie, rappro = preparer(
        transactions, commissions, eur_usd, chatters, diagnostic)
    _set(state="running", err="", ts=int(time.time()))
    try:
        gc = _client()
        classeur = gc.open_by_key(sid)

        # Le meme marqueur sur tous les onglets : quelle periode, mise a jour
        # quand, et par qui. C'est ce qui manquait pour qu'un onglet « Paie
        # quinzaine » ne puisse plus etre lu pour une autre quinzaine que la
        # sienne.
        quand = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        marqueur = "Periode : %s — mis a jour le %s (%s)" % (
            periode or "?", quand, "automatique" if auto else "a la main")

        _ecrire(classeur, ONGLET_VENTES, grille, "A1:I1", marqueur)
        _ecrire(classeur, ONGLET_CHATTEURS, recap, "", marqueur)
        _ecrire(classeur, ONGLET_QUINZAINE, quinz, "", marqueur)
        _ecrire(classeur, ONGLET_FICHES, fiches, "", marqueur)
        _ecrire(classeur, ONGLET_PAIE, paie, "A1:K1", marqueur)
        _ecrire(classeur, ONGLET_RAPPRO, rappro, "A1:F1", marqueur)

        cfg = load_config()
        cfg["last"] = int(time.time())
        cfg["last_lignes"] = len(grille) - 1
        cfg["derniere_periode"] = periode
        cfg["derniere_source"] = "auto" if auto else "manuel"
        if not auto:
            # Horodate la poussee manuelle : la boucle s'y refere pour ne pas
            # l'ecraser dans les minutes qui suivent.
            cfg["manuel_ts"] = int(time.time())
        save_config(cfg)
        _set(state="done", lignes=len(grille) - 1, ts=int(time.time()),
             periode=periode, source=("auto" if auto else "manuel"))
        return {"ok": True, "lignes": len(grille) - 1}
    except Exception as e:
        _set(state="error", err=str(e)[:200], ts=int(time.time()))
        return {"ok": False, "err": str(e)[:200]}


def pousser_async(transactions, periode: str = "", **kw) -> bool:
    """Lance l'ecriture en arriere-plan (la page ne doit pas attendre).

    Les arguments nommes (commissions, eur_usd, chatters, diagnostic) sont
    transmis tels quels a `pousser` : sans eux, la feuille de paie repart sur
    les valeurs par defaut et ne recoupe plus la page Paie du site.
    """
    if etat().get("state") == "running":
        return False
    threading.Thread(target=pousser, args=(transactions, periode), kwargs=kw,
                     daemon=True, name="ventes-sheet").start()
    return True


# ---------------------------------------------------------------------------
# Mise a jour automatique
# ---------------------------------------------------------------------------
_AUTO = {"on": False}


def debut_fenetre_auto(jour: _dt.date = None) -> _dt.date:
    """Premier jour couvert par la boucle : le debut de la quinzaine PRECEDENTE.

    La boucle ne couvrait que le mois en cours. Le 1er septembre a 00h05,
    l'onglet « Paie quinzaine » ne contenait donc plus que le 1er septembre —
    pendant que le proprietaire payait la quinzaine du 16 au 31 aout. Or on
    paie toujours la quinzaine ECHUE : elle doit rester dans le classeur.

    La fenetre porte donc exactement deux quinzaines, celle qu'on travaille et
    celle qu'on paie. Elle reste bornee (16 a 46 jours) : on ne rescrape pas
    l'annee entiere toutes les 5 minutes.
    """
    jour = jour or _dt.date.today()
    if jour.day <= 15:
        # quinzaine en cours = 1-15 ; la precedente est le 16-fin du mois d'avant
        veille_du_mois = jour.replace(day=1) - _dt.timedelta(days=1)
        return veille_du_mois.replace(day=16)
    return jour.replace(day=1)


def _bornes(periode: str) -> tuple:
    """« 2026-08-01 -> 2026-08-23 (auto) » -> les deux dates, ou (None, None)."""
    import re
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", periode or "")
    if len(dates) < 2:
        return None, None
    try:
        return _dt.date.fromisoformat(dates[0]), _dt.date.fromisoformat(dates[1])
    except ValueError:
        return None, None


def respit_manuel(debut_auto: _dt.date, fin_auto: _dt.date) -> int:
    """Secondes restantes avant que la boucle reprenne la main. 0 = elle peut ecrire.

    Une poussee manuelle du mois en cours est deja incluse dans la fenetre
    automatique : la reecrire ne fait perdre aucune ligne, on ne bloque rien.
    C'est la poussee d'une periode PLUS ANCIENNE — celle qu'on fait pour
    verifier une vente contestee — qui merite d'etre protegee.
    """
    cfg = load_config()
    ts = int(cfg.get("manuel_ts") or 0)
    if not ts:
        return 0
    reste = RESPIT_MANUEL_S - (int(time.time()) - ts)
    if reste <= 0:
        return 0
    debut, fin = _bornes(cfg.get("derniere_periode") or "")
    if debut and fin and debut_auto <= debut and fin <= fin_auto:
        return 0
    # Periode illisible : on protege plutot que d'ecraser au jugé.
    return reste


def start_auto(interval: int = 300) -> bool:
    """Rafraichit le classeur toutes les 5 minutes.

    Periode couverte : la quinzaine en cours ET la precedente (cf.
    debut_fenetre_auto) — celle qu'on paie ne disparait donc jamais du
    classeur. Le cache MyPuls dure aussi 5 minutes : on ne le sollicite pas
    plus que necessaire.

    Une poussee faite a la main sur une autre periode n'est pas ecrasee tout
    de suite : voir respit_manuel.
    """
    if _AUTO["on"]:
        return False
    _AUTO["on"] = True

    def _boucle():
        while True:
            try:
                time.sleep(interval)
                if not sheet_id() or not disponible():
                    continue
                today = _dt.date.today()
                debut = debut_fenetre_auto(today)
                reste = respit_manuel(debut, today)
                if reste > 0:
                    # On ne saute pas en silence : l'etat dit pourquoi et
                    # jusqu'a quand, la page peut l'afficher.
                    _set(auto_pause=reste)
                    continue
                _set(auto_pause=0)
                import mypuls
                res = mypuls.fetch_team_stats(debut.isoformat(), today.isoformat(),
                                              use_cache=True)
                if res.get("ok"):
                    tx = res.get("transactions") or []
                    # Une seule implementation du contexte : la boucle en
                    # tenait une copie, la poussee manuelle n'en avait aucune,
                    # et les deux ecrivaient donc des montants differents dans
                    # le meme onglet.
                    comm, taux = contexte_reel(tx)
                    pousser(tx, periode="%s -> %s" % (debut.isoformat(),
                                                      today.isoformat()),
                            commissions=comm, eur_usd=taux,
                            chatters=res.get("chatters"),
                            diagnostic=res.get("diagnostic"), auto=True)
            except Exception:
                pass          # une panne passagere ne doit pas tuer la boucle

    threading.Thread(target=_boucle, daemon=True, name="ventes-sheet-auto").start()
    return True
