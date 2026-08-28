# -*- coding: utf-8 -*-
"""Verifie la logique du remplisseur de nuit. Ne genere RIEN.

    python tests_noctuspool.py

Aucune video fabriquee, aucun appel a Discord : on eprouve les deux decisions
qui comptent — « suis-je dans le creneau ? » et « quelle case remplir ? ».
Elles n ont besoin ni du moteur ni du reseau, et c est justement pour ca
qu elles doivent etre testees ici plutot que decouvertes a trois heures du
matin en production.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ECHECS = []


def check(intitule, condition, detail=""):
    if condition:
        print("OK   %s" % intitule)
    else:
        print("ECHEC %s%s" % (intitule, ("  -> " + str(detail)) if detail else ""))
        ECHECS.append(intitule)


def a(heure):
    """Un instant a l heure dite, le reste sans importance."""
    return datetime(2026, 8, 22, heure, 30)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NOCTUS_RESERVE_DIR"] = str(Path(tmp) / "reserve")
        os.environ["NOCTUS_RESERVE_PROFONDEUR"] = "5"
        sys.path.insert(0, str(Path(__file__).resolve().parent))

        import noctus_reserve as nr
        from cogs import noctuspool as np

        # ---- par defaut, il tourne TOUJOURS -------------------------------
        check("par defaut : aucun creneau, il tourne a toute heure",
              np.TOUJOURS and all(np._dans_le_creneau(a(h)) for h in range(24)),
              "un remplissage seulement nocturne laisse la reserve se vider "
              "en fin de journee")

        # ---- le creneau, quand on en pose un ------------------------------
        np.TOUJOURS = False
        np.DEBUT_H, np.FIN_H = 0, 5
        check("creneau 0h-5h : 1h dedans", np._dans_le_creneau(a(1)))
        check("creneau 0h-5h : 4h dedans", np._dans_le_creneau(a(4)))
        check("creneau 0h-5h : 5h DEHORS", not np._dans_le_creneau(a(5)),
              "la borne haute est exclue, sinon on deborde d une heure")
        check("creneau 0h-5h : midi dehors", not np._dans_le_creneau(a(12)))
        check("creneau 0h-5h : 23h dehors", not np._dans_le_creneau(a(23)))

        # Le cas qui casse une comparaison naive : le creneau enjambe minuit.
        np.DEBUT_H, np.FIN_H = 22, 5
        check("creneau 22h-5h : 23h dedans", np._dans_le_creneau(a(23)),
              "un creneau qui enjambe minuit doit rester vrai avant minuit")
        check("creneau 22h-5h : 2h dedans", np._dans_le_creneau(a(2)))
        check("creneau 22h-5h : 12h dehors", not np._dans_le_creneau(a(12)))
        check("creneau 22h-5h : 21h dehors", not np._dans_le_creneau(a(21)))

        # Bornes egales : creneau vide, jamais « toujours ouvert ».
        np.DEBUT_H = np.FIN_H = 3
        check("bornes egales : ne tourne jamais",
              not any(np._dans_le_creneau(a(h)) for h in range(24)),
              "un creneau nul ne doit pas devenir permanent")
        np.DEBUT_H, np.FIN_H = 0, 5
        np.TOUJOURS = True

        # ---- la politesse : on ne fabrique pas pendant qu un VA attend ----
        import noctus_web as _nw
        vrai = _nw.generations_en_cours
        try:
            _nw.generations_en_cours = lambda: {"vam-en-cours"}
            check("un VA attend : on cede le tour", np._quelqu_un_attend(),
                  "les deux se disputeraient ffmpeg")
            _nw.generations_en_cours = lambda: set()
            check("personne n attend : on peut fabriquer",
                  not np._quelqu_un_attend())

            def _casse():
                raise RuntimeError("moteur illisible")
            _nw.generations_en_cours = _casse
            check("moteur illisible : on cede, par prudence",
                  np._quelqu_un_attend(),
                  "ceder coute un retard, passer outre ralentit quelqu un")
        finally:
            _nw.generations_en_cours = vrai

        # ---- les familles declarees ---------------------------------------
        check("les huit familles qui generent sont declarees",
              set(np.FAMILLES) == {"caption", "montage", "reelmonte",
                                   "template", "template_brut",
                                   "flash", "flash_banger", "flash_brut"},
              sorted(np.FAMILLES))

        # ---- le choix de la case -----------------------------------------
        # On restreint la liste : ce qu on eprouve ici est la SELECTION, pas
        # le catalogue. Sans ca, ajouter une famille casserait ce test sans
        # qu aucun comportement n ait change.
        np.FAMILLES = ("caption", "montage")
        choisir = np.NoctusPool._case_la_plus_vide
        idents = ["emma", "julia"]

        c = choisir(None, idents)
        check("tout vide : une case est choisie", c is not None)

        atelier = Path(tmp) / "atelier"
        atelier.mkdir()

        def poser(ident, famille, combien):
            for i in range(combien):
                f = atelier / ("%s_%s_%d.mp4" % (ident, famille, i))
                f.write_bytes(b"v")
                nr.deposer(ident, famille, f, "emp")

        # emma/caption bien fournie, le reste a zero : on ne doit PAS la servir.
        poser("emma", "caption", 5)
        c = choisir(None, idents)
        check("la case pleine n est pas choisie", c != ("emma", "caption"), c)

        # On remplit tout sauf julia/montage : c est elle qu il faut servir.
        poser("emma", "montage", 5)
        poser("julia", "caption", 5)
        poser("julia", "montage", 4)
        check("la case la plus degarnie est choisie",
              choisir(None, idents) == ("julia", "montage"),
              choisir(None, idents))

        poser("julia", "montage", 1)
        check("tout plein : plus rien a faire",
              choisir(None, idents) is None,
              "on continuerait a fabriquer pour rien")

        # ---- les cases ecartees -------------------------------------------
        # Une case dont le vivier est vide echoue a chaque tour. Sans mise a
        # l ecart, elle se represente comme « la plus degarnie » indefiniment
        # et la nuit entiere s y use.
        nr.RACINE = Path(tmp) / "reserve2"
        c1 = choisir(None, idents)
        check("nouvelle reserve vide : une case est choisie", c1 is not None)
        c2 = choisir(None, idents, ecartees={c1})
        check("case ecartee : une AUTRE est choisie", c2 is not None and c2 != c1)
        toutes = {(i, f) for i in idents for f in np.FAMILLES}
        check("toutes ecartees : plus rien",
              choisir(None, idents, ecartees=toutes) is None,
              "la boucle tournerait a vide jusqu au matin")

    print()
    if ECHECS:
        print("%d ECHEC(S) : %s" % (len(ECHECS), ", ".join(ECHECS)))
        return 1
    print("tout est vert — aucune video generee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
