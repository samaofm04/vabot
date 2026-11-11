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

        # La reserve est COUPEE en production depuis le 05/09
        # (noctus_reserve.ACTIF = False). Ces tests eprouvent le
        # mecanisme, pas l interrupteur : sans cette ligne, prendre()
        # rendrait (None, "") et toute la suite tomberait sans que
        # rien ne soit casse. Le jour ou la reserve est rallumee,
        # cette ligne devient inutile mais reste juste.
        nr.ACTIF = True
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

        # ---- le tour ne retient pas la boucle du bot ----------------------
        # Du 04 au 11/11/2026, chaque matin de 04:00 a 04:15 UTC : le choix de
        # la case (toute la reserve relue, ~5 500 petites lectures) tournait
        # SUR la boucle du bot. Pendant le releve Instagram il durait 10 a
        # 30 s : « heartbeat blocked », et les clics des VA en « Unknown
        # interaction ». On rejoue un tour avec un balayage et une recette
        # LENTS : la boucle doit continuer de battre, et le tour doit decider
        # exactement ce qu il decidait.
        import asyncio
        import threading
        import time
        import types

        nr.RACINE = Path(tmp) / "reserve3"
        LENT = 0.3
        journal = []                     # (quoi, fil, detail), dans l ordre
        sans_recette = ("emma", "caption")

        pool = object.__new__(np.NoctusPool)     # ni bot, ni tache lancee
        pool._occupe = False

        def balayage_lent(identites, ecartees=()):
            journal.append(("balayage", threading.get_ident(), set(ecartees)))
            time.sleep(LENT)
            return choisir(None, identites, ecartees)

        def recette_lente(identite, famille):
            journal.append(("recette", threading.get_ident(), (identite, famille)))
            time.sleep(LENT)
            if (identite, famille) == sans_recette:
                return None                      # vivier vide
            return ({"video": "x"}, "emp-" + identite + "-" + famille)

        async def moteur_en_panne(identite, famille, prep):
            journal.append(("fabrique", threading.get_ident(),
                            ((identite, famille), prep)))
            return False

        pool._case_la_plus_vide = balayage_lent
        pool._preparer = recette_lente
        pool._fabriquer_une = moteur_en_panne
        pool._sans_reserves = lambda identites: list(identites)

        attend = {"oui": False}

        def quelqu_un_attend():
            journal.append(("attend", threading.get_ident(), attend["oui"]))
            return attend["oui"]

        # Le tour lit trois modules du site : des doublures, pour que ce test
        # ne depende ni de web_upload ni du data/ du poste.
        doublures = {
            "web_upload": types.SimpleNamespace(
                _list_content_identities=lambda: list(idents)),
            "identite_pause": types.SimpleNamespace(
                sans_pauses=lambda identites: list(identites)),
        }
        avant = {nom: sys.modules.get(nom) for nom in doublures}
        vrais = (np._quelqu_un_attend, np.REPOS_S, _nw.setup_ok)
        sys.modules.update(doublures)
        np._quelqu_un_attend = quelqu_un_attend
        np.REPOS_S = 0
        _nw.setup_ok = lambda: True

        async def un_tour():
            """Joue remplir() ; rend le pire retard de la boucle et son fil."""
            pire, fini = [0.0], [False]

            async def battement():
                while not fini[0]:
                    t = time.monotonic()
                    await asyncio.sleep(0.01)
                    pire[0] = max(pire[0], time.monotonic() - t - 0.01)

            b = asyncio.ensure_future(battement())
            await asyncio.sleep(0.05)
            await np.NoctusPool.remplir.coro(pool)
            fini[0] = True
            await b
            return pire[0], threading.get_ident()

        try:
            pire, boucle = asyncio.run(un_tour())
            balayages = [j for j in journal if j[0] == "balayage"]
            recettes = [j for j in journal if j[0] == "recette"]
            fabriques = [j for j in journal if j[0] == "fabrique"]
            check("tour : le choix de la case ne tourne plus sur la boucle du bot",
                  balayages and all(j[1] != boucle for j in balayages),
                  "c est lui qui arretait le bot 10 a 30 s chaque matin")
            check("tour : la recette non plus",
                  recettes and all(j[1] != boucle for j in recettes))
            check("tour : la boucle bat pendant un balayage lent",
                  pire < LENT / 2,
                  "boucle arretee %.2f s pour un balayage de %.2f s" % (pire, LENT))
            # Ce que le tour DECIDE n a pas change : la case la plus vide,
            # ecartee si rien n en sort, jusqu a ce qu il n en reste aucune.
            check("tour : chaque balayage voit les cases deja ecartees",
                  [len(j[2]) for j in balayages] == [0, 1, 2, 3, 4]
                  and balayages[-1][2] == toutes, [j[2] for j in balayages])
            check("tour : une case par balayage, jamais deux fois la meme",
                  len(recettes) == 4 and {j[2] for j in recettes} == toutes,
                  [j[2] for j in recettes])
            check("tour : une case sans recette est ecartee sans lancer le moteur",
                  sans_recette not in [j[2][0] for j in fabriques]
                  and len(fabriques) == 3, [j[2][0] for j in fabriques])
            check("tour : le moteur recoit la recette deja preparee",
                  all(j[2][1] == ({"video": "x"}, "emp-%s-%s" % j[2][0])
                      for j in fabriques), fabriques[:1])
            # La politesse : rien ne s intercale entre « un VA attend-il ? »
            # et le lancement du moteur, sinon un VA pourrait cliquer dans
            # l intervalle et se retrouver a partager ffmpeg.
            ordre = [j[0] for j in journal]
            check("tour : le regard « un VA attend ? » precede IMMEDIATEMENT le moteur",
                  all(ordre[i - 1] == "attend"
                      for i, q in enumerate(ordre) if q == "fabrique"), ordre)
            check("tour : la tache se libere a la fin", pool._occupe is False)

            # Un VA attend : on rend la main au premier regard, sans moteur.
            del journal[:]
            attend["oui"] = True
            asyncio.run(un_tour())
            check("tour : un VA attend -> un seul balayage, aucun moteur",
                  [j[0] for j in journal] == ["balayage", "recette", "attend"],
                  [j[0] for j in journal])
            check("tour : ... et la tache se libere quand meme",
                  pool._occupe is False)
        finally:
            np._quelqu_un_attend, np.REPOS_S, _nw.setup_ok = vrais
            for nom, module in avant.items():
                if module is None:
                    sys.modules.pop(nom, None)
                else:
                    sys.modules[nom] = module

        # ---- la preparation : recette, empreinte, et « en manque-t-on ? » --
        nr.RACINE = Path(tmp) / "reserve4"
        source = atelier / "source.mp4"
        source.write_bytes(b"s")
        recette = {"video": source, "draft": {"cut_at": 1.5}, "imposees": (),
                   "brute_imposee": None, "desc": "", "caption": None}
        faux = types.SimpleNamespace(_recette=lambda i, f: None)
        check("preparation : vivier vide -> rien a fabriquer",
              np.NoctusPool._preparer(faux, "emma", "caption") is None)
        faux._recette = lambda i, f: recette
        attendue = nr.empreinte("emma", "caption", source, brutes=(),
                                caption=None, draft=recette["draft"])
        check("preparation : la recette et SON empreinte",
              np.NoctusPool._preparer(faux, "emma", "caption") == (recette, attendue))
        for i in range(nr.PROFONDEUR):
            f = atelier / ("pourvue_%d.mp4" % i)
            f.write_bytes(b"v")
            nr.deposer("emma", "caption", f, attendue, recette={"repli": False})
        check("preparation : recette deja pourvue -> rien a fabriquer",
              np.NoctusPool._preparer(faux, "emma", "caption") is None,
              "on refabriquerait sans fin la meme variante")

    print()
    if ECHECS:
        print("%d ECHEC(S) : %s" % (len(ECHECS), ", ".join(ECHECS)))
        return 1
    print("tout est vert — aucune video generee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
