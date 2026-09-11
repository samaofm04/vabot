# -*- coding: utf-8 -*-
"""L'historique des abonnes, jour par jour.

POURQUOI CE FICHIER EXISTE

Le cache de scrape porte le nombre d'abonnes ACTUEL de chaque compte, et rien
d'autre. On pouvait donc dire « ce compte a 4 210 abonnes », jamais « il en a
gagne 300 cette semaine » -- alors que c'est la seule des deux phrases qui
dise si le travail des VA sert a quelque chose.

Rien nulle part ne gardait cette valeur d'un jour sur l'autre. Une courbe ne
s'invente pas apres coup : tant qu'on n'enregistre pas, il n'y a rien a
tracer, et il n'y aura toujours rien dans un mois. On commence donc a
enregistrer maintenant, meme si le premier graphique sera plat.

CE QU'ON ECRIT, ET CE QU'ON N'ECRIT PAS

Une valeur par compte et par jour (date de Paris, comme partout ailleurs dans
ce depot), ecrasee si le scrape repasse le meme jour -- six fois par jour, la
derniere vaut. On n'ecrit RIEN pour un compte dont le scrape a echoue : un
zero se confondrait avec une chute a zero, et c'est exactement le genre de
faux signal qui fait douter de tout l'ecran.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

import safe_json

FICHIER = Path("data") / "abonnes_jours.json"

#: Au-dela, on oublie : un an de recul suffit largement, et le fichier est
#: relu en entier a chaque ecriture.
JOURS_GARDES = 400


def _jour_paris(ts: Optional[float] = None) -> str:
    """La date a Paris. Le serveur tourne en UTC : sa date n'est pas la notre
    entre minuit et deux heures, et le proprietaire travaille la nuit."""
    import time as _t
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Paris")
    except Exception:
        tz = None
    d = _dt.datetime.fromtimestamp(_t.time() if ts is None else float(ts), tz)
    return d.date().isoformat()


def _charger() -> dict:
    d = safe_json.load(FICHIER, default={}) or {}
    return d if isinstance(d, dict) else {}


def enregistrer(cache: dict, jour: str = "") -> int:
    """Note les abonnes du jour, depuis le cache de scrape. Rend le nombre note.

    `cache` est {handle: entree} tel que le scrape le tient. On ne prend que
    les entrees qui portent VRAIMENT un nombre d'abonnes : une entree en
    erreur garde parfois les anciennes donnees (voir le « cliquet » de
    _compute_insta_3_stats), mais une entree neuve en echec n'a rien du tout,
    et ecrire zero pour elle inventerait une chute.
    """
    if not isinstance(cache, dict) or not cache:
        return 0
    jour = jour or _jour_paris()
    data = _charger()
    n = 0
    for handle, e in cache.items():
        if not isinstance(e, dict):
            continue
        brut = e.get("followers")
        try:
            v = int(brut)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            # Zero n'est pas une mesure : c'est ce que rend un scrape qui n'a
            # rien vu. Un vrai compte a zero abonne n'interesse personne, et
            # le confondre avec un echec ferait plonger la courbe.
            continue
        data.setdefault(str(handle), {})[jour] = v
        n += 1
    if n:
        _purger(data)
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write(FICHIER, data)
    return n


def _purger(data: dict) -> None:
    limite = (_dt.date.fromisoformat(_jour_paris())
              - _dt.timedelta(days=JOURS_GARDES)).isoformat()
    for handle, jours in list(data.items()):
        if not isinstance(jours, dict):
            data.pop(handle, None)
            continue
        for j in [x for x in jours if x < limite]:
            jours.pop(j, None)
        if not jours:
            data.pop(handle, None)


def serie(handle: str) -> dict:
    """{jour: abonnes} pour un compte."""
    d = _charger().get(str(handle))
    return dict(d) if isinstance(d, dict) else {}


def total_par_jour(handles=None) -> dict:
    """{jour: somme des abonnes} sur les comptes demandes (tous si None).

    UN TOTAL NE SE CALCULE QUE SUR LES COMPTES MESURES CE JOUR-LA. Additionner
    ce qu'on a, jour par jour, ferait chuter la courbe le jour ou un compte
    n'a pas repondu -- une baisse qui n'a jamais eu lieu. On reporte donc la
    derniere valeur connue de chaque compte tant qu'il en a une.
    """
    data = _charger()
    if handles is not None:
        vus = {str(h) for h in handles}
        data = {k: v for k, v in data.items() if k in vus}
    jours = sorted({j for v in data.values() if isinstance(v, dict) for j in v})
    out, dernier = {}, {}
    for j in jours:
        for h, v in data.items():
            if isinstance(v, dict) and j in v:
                dernier[h] = v[j]
        out[j] = sum(dernier.values())
    return out


def variation(handles=None, jours: int = 7) -> tuple:
    """(gagnes, depuis_le_jour) sur la periode. (None, "") si trop court.

    Rend None plutot que zero quand l'historique ne remonte pas assez loin :
    « 0 abonne gagne » et « on ne sait pas encore » ne sont pas la meme
    chose, et l'ecran doit pouvoir dire la seconde.
    """
    t = total_par_jour(handles)
    if len(t) < 2:
        return None, ""
    js = sorted(t)
    cible = (_dt.date.fromisoformat(js[-1]) - _dt.timedelta(days=int(jours))).isoformat()
    anciens = [j for j in js if j <= cible]
    depart = anciens[-1] if anciens else js[0]
    return t[js[-1]] - t[depart], depart
