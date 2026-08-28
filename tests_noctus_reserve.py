# -*- coding: utf-8 -*-
"""Verifie la reserve de videos pre-generees. Ne genere RIEN, ne parle a rien.

    python tests_noctus_reserve.py

Aucun appel a ffmpeg, a Node, a Discord ni au site : tout se joue sur de faux
fichiers dans un dossier temporaire. C'est voulu — ce module decide qui recoit
quelle video, et on doit pouvoir le mettre en doute sans bruler une heure de
processeur.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

ECHECS = []


def check(intitule, condition, detail=""):
    if condition:
        print("OK   %s" % intitule)
    else:
        print("ECHEC %s%s" % (intitule, ("  -> " + str(detail)) if detail else ""))
        ECHECS.append(intitule)


def faux_mp4(dossier: Path, nom: str, octets: bytes = b"video") -> Path:
    p = dossier / nom
    p.write_bytes(octets)
    return p


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NOCTUS_RESERVE_DIR"] = str(Path(tmp) / "reserve")
        os.environ["NOCTUS_RESERVE_PROFONDEUR"] = "5"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import noctus_reserve as nr

        atelier = Path(tmp) / "atelier"
        atelier.mkdir()

        # ---- l'empreinte : ce qui rend deux variantes interchangeables ----
        src = faux_mp4(atelier, "tpl.mp4")
        e1 = nr.empreinte("emma", "template", src)
        e2 = nr.empreinte("emma", "template", src)
        check("empreinte : stable pour les memes ingredients", e1 == e2)
        check("empreinte : change avec l identite",
              nr.empreinte("julia", "template", src) != e1)
        check("empreinte : change avec la famille",
              nr.empreinte("emma", "flash", src) != e1)

        # Le CONTENU compte, pas seulement le nom : un admin qui corrige une
        # caption doit invalider ce qui a ete fabrique avant.
        cap_a = {"id": "c1", "text": "avant"}
        cap_b = {"id": "c1", "text": "apres"}
        check("empreinte : le TEXTE de la caption compte, pas que son id",
              nr.empreinte("emma", "caption", src, caption=cap_a)
              != nr.empreinte("emma", "caption", src, caption=cap_b))

        # Un fichier source remplace depuis doit invalider aussi.
        import time as _t
        _t.sleep(0.01)
        src.write_bytes(b"video modifiee")
        check("empreinte : une source modifiee invalide l ancienne",
              nr.empreinte("emma", "template", src) != e1)
        emp = nr.empreinte("emma", "template", src)

        # ---- deposer et compter ----
        check("stock vide au depart", nr.compter("emma", "template") == 0)
        p = nr.deposer("emma", "template", faux_mp4(atelier, "v1.mp4"), emp,
                       desc="une description")
        check("depose : la variante est rangee", p is not None and p.is_file())
        check("depose : le fichier a QUITTE l atelier",
              not (atelier / "v1.mp4").exists(),
              "il serait detruit par la purge des modeles")
        check("compte : une variante en stock", nr.compter("emma", "template") == 1)
        check("compte : filtre par empreinte",
              nr.compter("emma", "template", emp) == 1
              and nr.compter("emma", "template", "autre") == 0)

        # ---- manque : ce qu'il reste a fabriquer ----
        check("manque : 4 pour atteindre 5",
              nr.manque("emma", "template", emp) == 4)
        check("manque : profondeur imposee respectee",
              nr.manque("emma", "template", emp, profondeur=2) == 1)
        check("manque : jamais negatif",
              nr.manque("emma", "template", emp, profondeur=0) == 0)

        # ---- prendre : la variante SORT du stock ----
        chemin, desc = nr.prendre("emma", "template", emp, demandeur="va1")
        check("prendre : rend un fichier", chemin is not None and chemin.is_file())
        check("prendre : rend la description", desc == "une description")
        check("prendre : le stock est vide apres",
              nr.compter("emma", "template") == 0,
              "la variante serait servie deux fois")
        check("prendre : stock vide -> rien, sans erreur",
              nr.prendre("emma", "template", emp) == (None, ""))

        # ---- solder : une variante sortie ne revient jamais ----
        nr.solder(chemin, "envoye")
        check("solder : le fichier servi est efface", not chemin.exists())
        check("solder : et le stock reste vide",
              nr.compter("emma", "template") == 0)

        # ---- L'UNICITE SOUS CONCURRENCE : le test qui compte ----
        #
        # Dix variantes, vingt preneurs simultanes. Chaque fichier ne doit
        # partir qu'une fois, et personne ne doit recevoir le meme.
        for i in range(10):
            nr.deposer("emma", "montage",
                       faux_mp4(atelier, "m%d.mp4" % i), emp)
        recus, erreurs = [], []
        verrou = threading.Lock()

        def preneur():
            try:
                c, _d = nr.prendre("emma", "montage", emp)
                if c is not None:
                    with verrou:
                        recus.append(str(c))
            except Exception as exc:            # noqa: BLE001
                with verrou:
                    erreurs.append(repr(exc))

        fils = [threading.Thread(target=preneur) for _ in range(20)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()

        check("concurrence : aucune exception", not erreurs, erreurs[:2])
        check("concurrence : 10 variantes pour 20 preneurs -> 10 servies",
              len(recus) == 10, "%d servie(s)" % len(recus))
        check("concurrence : AUCUN DOUBLON",
              len(set(recus)) == len(recus),
              "deux comptes posteraient la meme video")
        check("concurrence : le stock est vide", nr.compter("emma", "montage") == 0)

        # ---- purger_perimes : ce qui ne correspond plus est jete ----
        nr.deposer("emma", "flash", faux_mp4(atelier, "f1.mp4"), "vieille")
        nr.deposer("emma", "flash", faux_mp4(atelier, "f2.mp4"), "vieille")
        nr.deposer("emma", "flash", faux_mp4(atelier, "f3.mp4"), emp)
        check("stock avant purge : 3", nr.compter("emma", "flash") == 3)
        check("purge : 2 perimees jetees",
              nr.purger_perimes("emma", "flash", emp) == 2)
        check("purge : la variante a jour survit",
              nr.compter("emma", "flash", emp) == 1)

        # ---- une fiche sans video ne doit jamais etre servie ----
        libre = nr._dossier("emma", "flash", "libre")
        orpheline = next(libre.glob("*.mp4"))
        orpheline.unlink()
        check("fiche orpheline : non comptee",
              nr.compter("emma", "flash") == 0,
              "on annoncerait une video qui n existe plus")
        check("fiche orpheline : non servie",
              nr.prendre("emma", "flash", emp) == (None, ""))

        # ---- etat : la vue d ensemble ----
        nr.deposer("emma", "caption", faux_mp4(atelier, "c1.mp4"), emp)
        nr.deposer("julia", "caption", faux_mp4(atelier, "c2.mp4"), emp)
        e = nr.etat()
        check("etat : rend le compte par identite et famille",
              e.get("emma/caption") == 1 and e.get("julia/caption") == 1, e)

        # ---- le journal existe et se relit ----
        j = nr._journal()
        check("journal : ecrit", j.is_file())
        if j.is_file():
            import json as _js
            lignes = [_js.loads(x) for x in
                      j.read_text(encoding="utf-8").splitlines() if x.strip()]
            check("journal : chaque ligne est un objet lisible",
                  all(isinstance(x, dict) and x.get("acte") for x in lignes))
            check("journal : les sorties sont tracees",
                  sum(1 for x in lignes if x.get("acte") == "sorti") == 11,
                  "1 + 10 sous concurrence")

    print()
    if ECHECS:
        print("%d ECHEC(S) : %s" % (len(ECHECS), ", ".join(ECHECS)))
        return 1
    print("tout est vert — aucune video generee, aucun appel reseau.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
