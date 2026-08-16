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

_ETAT = {"state": "idle", "ts": 0, "lignes": 0, "err": ""}
_LOCK = threading.Lock()


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


def _onglet(classeur, titre: str, colonnes: int):
    """Recupere l'onglet, le cree s'il manque."""
    try:
        return classeur.worksheet(titre)
    except Exception:
        return classeur.add_worksheet(title=titre, rows=1000, cols=max(colonnes, 8))


def preparer(transactions) -> tuple:
    """Transactions -> (lignes du registre, lignes du recap). Testable seul."""
    lignes = ventes_export.lignes_ventes(transactions)
    entetes = ventes_export.COLONNES
    cols_recap, recap = ventes_export.recap_par_chatteur(lignes)
    cols_q, recap_q = ventes_export.recap_par_quinzaine(lignes)
    return ([entetes] + lignes), ([cols_recap] + recap), ([cols_q] + recap_q)


def pousser(transactions, periode: str = "") -> dict:
    """Ecrit les ventes dans le classeur. Retourne {ok, lignes, err}."""
    sid = sheet_id()
    if not sid:
        return {"ok": False, "err": "Aucun classeur configure"}
    if not disponible():
        return {"ok": False, "err": "Compte de service Google indisponible"}
    grille, recap, quinz = preparer(transactions)
    _set(state="running", err="", ts=int(time.time()))
    try:
        gc = _client()
        classeur = gc.open_by_key(sid)

        ws = _onglet(classeur, ONGLET_VENTES, len(ventes_export.COLONNES))
        ws.clear()
        ws.update("A1", grille, value_input_option="RAW")
        try:                       # en-tete figee et en gras : confort de lecture
            ws.freeze(rows=1)
            ws.format("A1:H1", {"textFormat": {"bold": True}})
        except Exception:
            pass

        ws2 = _onglet(classeur, ONGLET_CHATTEURS, len(recap[0]) if recap else 4)
        ws2.clear()
        ws2.update("A1", recap, value_input_option="RAW")
        try:
            ws2.freeze(rows=1)
        except Exception:
            pass

        ws3 = _onglet(classeur, ONGLET_QUINZAINE, len(quinz[0]) if quinz else 4)
        ws3.clear()
        ws3.update("A1", quinz, value_input_option="RAW")
        try:
            ws3.freeze(rows=1)
        except Exception:
            pass

        # une ligne d'horodatage : on sait de quand datent les chiffres
        try:
            quand = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.update("K1", [["Mis a jour", quand, periode]], value_input_option="RAW")
        except Exception:
            pass

        cfg = load_config()
        cfg["last"] = int(time.time())
        cfg["last_lignes"] = len(grille) - 1
        save_config(cfg)
        _set(state="done", lignes=len(grille) - 1, ts=int(time.time()))
        return {"ok": True, "lignes": len(grille) - 1}
    except Exception as e:
        _set(state="error", err=str(e)[:200], ts=int(time.time()))
        return {"ok": False, "err": str(e)[:200]}


def pousser_async(transactions, periode: str = "") -> bool:
    """Lance l'ecriture en arriere-plan (la page ne doit pas attendre)."""
    if etat().get("state") == "running":
        return False
    threading.Thread(target=pousser, args=(transactions, periode),
                     daemon=True, name="ventes-sheet").start()
    return True


# ---------------------------------------------------------------------------
# Mise a jour automatique
# ---------------------------------------------------------------------------
_AUTO = {"on": False}


def start_auto(interval: int = 300) -> bool:
    """Rafraichit le classeur toutes les 5 minutes.

    Periode couverte : le mois en cours — donc les DEUX quinzaines y sont
    toujours. Le cache MyPuls dure aussi 5 minutes : on ne le sollicite donc
    pas plus que necessaire.
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
                import mypuls
                today = _dt.date.today()
                debut = today.replace(day=1).isoformat()
                res = mypuls.fetch_team_stats(debut, today.isoformat(), use_cache=True)
                if res.get("ok"):
                    pousser(res.get("transactions") or [],
                            periode="%s -> %s (auto)" % (debut, today.isoformat()))
            except Exception:
                pass          # une panne passagere ne doit pas tuer la boucle

    threading.Thread(target=_boucle, daemon=True, name="ventes-sheet-auto").start()
    return True
