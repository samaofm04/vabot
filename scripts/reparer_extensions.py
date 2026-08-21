# -*- coding: utf-8 -*-
"""Rend son extension a un media qui l'a perdue au moment de l'upload.

`_safe_upload_name` tronquait a 120 caracteres sans regarder ou tombait le
point : un nom Instagram long arrivait sans suffixe. Or les galeries du site
ET gdrive_sync filtrent par extension — un media nu n'etait donc ni affiche
ni sauvegarde nulle part. Le defaut est corrige ; ce script repare l'existant.

    python scripts/reparer_extensions.py              # constat seul, n'ecrit rien
    python scripts/reparer_extensions.py --appliquer  # renomme
    python scripts/reparer_extensions.py --annuler --appliquer   # revient en arriere

Regles de surete, dans l'esprit du reste du depot :
  - l'extension vient des OCTETS du fichier, jamais d'une supposition ;
  - on AJOUTE le suffixe, on ne remplace pas la fin du nom : « _co » fait
    partie du nom tronque, ce n'est pas une extension ;
  - aucune suppression, aucun ecrasement : uniquement des renommages ;
  - chaque renommage est journalise, donc annulable ;
  - rien n'est ecarte en silence : ce qui n'est pas repare est compte et motive.
"""
import argparse
import pathlib
import sys
import time

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import safe_json                                              # noqa: E402
# Les jeux d'extensions viennent de gdrive_sync : c'est LUI qui decide ce qui
# est sauvegarde. Une seconde liste ici finirait par diverger — le Drive a
# deja perdu 598 fichiers a ce jeu-la.
from gdrive_sync import IMAGE_EXTS, VIDEO_EXTS, SIDECAR_EXTS  # noqa: E402

IDENTITES = RACINE / "data" / "identities"
JOURNAL = RACINE / "data" / "reparation_extensions.json"
CONNUES = IMAGE_EXTS | VIDEO_EXTS | SIDECAR_EXTS | {".prev"}
# Un telechargement interrompu ressemble a un media ampute : ses octets de
# tete sont ceux d'un JPEG alors que la fin manque. On le signale, on ne le
# renomme jamais — le promouvoir en media livrerait une image tronquee.
INACHEVES = {".part", ".tmp", ".crdownload", ".download"}
# Les voisins d'un media : mal les suivre casserait la caption ou le montage.
VOISINS = (".txt", ".desc.txt", ".acheck.txt", ".montage.json", ".analyse.json")


def sniffer(entete):
    """L'extension deduite des octets, et le format lu — ou (None, motif)."""
    if entete[:3] == b"\xff\xd8\xff":
        return ".jpg", "JPEG"
    if entete[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "PNG"
    if entete[:4] == b"RIFF" and entete[8:12] == b"WEBP":
        return ".webp", "WEBP"
    if entete[4:8] == b"ftyp":
        marque = entete[8:12].decode("ascii", "replace").strip()
        return (".mov" if marque.startswith("qt") else ".mp4"), "ISOBMFF/" + marque
    if entete[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm", "Matroska/WebM"
    if entete[:6] in (b"GIF87a", b"GIF89a"):
        return None, "GIF"
    if not entete:
        return None, "fichier vide"
    return None, "entete inconnu " + entete[:12].hex()


def candidats():
    """Les fichiers dont le suffixe n'est reconnu de personne, avec leur verdict.

    On parcourt les sous-dossiers tels qu'ils existent, sans liste ecrite en
    dur : une liste de plus serait une deuxieme regle a maintenir, et c'est
    exactement ce qui avait rendu 598 fichiers du Drive invisibles.
    """
    trouves = []
    if not IDENTITES.is_dir():
        return trouves
    for ident in sorted(p for p in IDENTITES.iterdir() if p.is_dir()):
        for sous in sorted(p for p in ident.iterdir() if p.is_dir()):
            for f in sorted(p for p in sous.iterdir() if p.is_file()):
                if f.suffix.lower() in CONNUES:
                    continue
                fiche = {"chemin": f, "ext": None, "taille": 0,
                         "format": "", "motif": None, "cible": None}
                try:
                    with f.open("rb") as fh:
                        entete = fh.read(32)
                    fiche["taille"] = f.stat().st_size
                except Exception as e:                    # illisible : on le dit
                    fiche["format"] = "illisible"
                    fiche["motif"] = "illisible (%s)" % e
                    trouves.append(fiche)
                    continue
                ext, format_lu = sniffer(entete)
                fiche["format"] = format_lu
                if f.suffix.lower() in INACHEVES:
                    fiche["motif"] = ("reste de telechargement (%s, %d octets) : "
                                      "laisse tel quel"
                                      % (f.suffix.lower(), fiche["taille"]))
                elif ext is None:
                    fiche["motif"] = format_lu
                elif ext not in (IMAGE_EXTS | VIDEO_EXTS):
                    fiche["motif"] = "%s : format non gere par le site" % format_lu
                else:
                    cible = f.with_name(f.name + ext)
                    fiche["ext"] = ext
                    fiche["cible"] = cible
                    if cible.exists():
                        # Jamais d'ecrasement : un homonyme se regle a la main.
                        fiche["motif"] = "la cible existe deja : %s" % cible.name
                    elif f.stem != f.name:
                        # Nom a point interne : une fois le suffixe ajoute, les
                        # voisins ne se retrouveraient plus par with_suffix.
                        vs = [v for v in VOISINS
                              if f.with_name(f.stem + v).exists()]
                        if vs:
                            fiche["motif"] = ("voisins accroches a l'ancien "
                                              "radical (%s) : a la main"
                                              % ", ".join(vs))
                trouves.append(fiche)
    return trouves


def references(noms):
    """Les fichiers de data/ qui citent un de ces noms.

    Un media invisible ne peut pas avoir ete choisi dans un planning, mais on
    verifie plutot que de le supposer : renommer un fichier cite ailleurs
    romprait le lien en silence.
    """
    touches = []
    if not noms:
        return touches
    for j in sorted((RACINE / "data").glob("*.json")):
        try:
            txt = j.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for n in noms:
            if n in txt:
                touches.append((j.name, n))
    return touches


def appliquer(fiches, pour_de_vrai):
    faits = []
    for f in fiches:
        if f["motif"] or not f["cible"]:
            continue
        if pour_de_vrai:
            f["chemin"].rename(f["cible"])
        faits.append({"avant": str(f["chemin"].relative_to(RACINE)).replace("\\", "/"),
                      "apres": str(f["cible"].relative_to(RACINE)).replace("\\", "/"),
                      "taille": f["taille"], "format": f["format"],
                      "quand": int(time.time())})
    if faits and pour_de_vrai:
        d = safe_json.load(JOURNAL, default={}) or {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("renommages", []).extend(faits)
        safe_json.write(JOURNAL, d)
    return faits


def annuler(pour_de_vrai):
    d = safe_json.load(JOURNAL, default={}) or {}
    faits = (d.get("renommages") or []) if isinstance(d, dict) else []
    restants, rendus = [], 0
    for r in reversed(faits):
        avant, apres = RACINE / r["avant"], RACINE / r["apres"]
        if apres.exists() and not avant.exists():
            print("  <- %s" % apres.name[:90])
            if pour_de_vrai:
                apres.rename(avant)
            rendus += 1
        else:
            restants.append(r)
            print("  !! non annulable (deplace ou deja rendu) : %s" % r["apres"])
    if pour_de_vrai:
        d = d if isinstance(d, dict) else {}
        d["renommages"] = restants
        safe_json.write(JOURNAL, d)
    return rendus


def main():
    ap = argparse.ArgumentParser(description="Rend son extension a un media nu.")
    ap.add_argument("--appliquer", action="store_true", help="renomme pour de vrai")
    ap.add_argument("--annuler", action="store_true",
                    help="rejoue le journal a l'envers")
    a = ap.parse_args()

    if a.annuler:
        print("ANNULATION%s" % ("" if a.appliquer else " (constat seul)"))
        print("%d fichier(s) a rendre a leur ancien nom" % annuler(a.appliquer))
        return

    fiches = candidats()
    reparables = [f for f in fiches if not f["motif"] and f["cible"]]
    bloques = [f for f in fiches if f["motif"]]

    print("=== A REPARER : %d fichier(s) ===" % len(reparables))
    par_dossier = {}
    for f in reparables:
        par_dossier.setdefault(str(f["chemin"].relative_to(IDENTITES).parent),
                               []).append(f)
    for dossier, fs in sorted(par_dossier.items()):
        octets = sum(x["taille"] for x in fs)
        print("  %-30s %3d fichier(s)  %7.1f Mo  [%s]"
              % (dossier, len(fs), octets / 1048576.0,
                 ", ".join(sorted({x["format"] for x in fs}))))
        for x in fs[:3]:
            print("      %s  ->  + %s" % (x["chemin"].name[:74], x["ext"]))
        if len(fs) > 3:
            print("      ... et %d autre(s)" % (len(fs) - 3))

    if bloques:
        print("\n=== LAISSES DE COTE : %d ===" % len(bloques))
        for f in bloques:
            print("  %-58s %s"
                  % (str(f["chemin"].relative_to(IDENTITES))[-58:], f["motif"]))

    cites = references([f["chemin"].name for f in reparables])
    if cites:
        print("\n!! Ces noms sont cites dans data/ — a regler AVANT de renommer :")
        for j, n in cites:
            print("   %s : %s" % (j, n[:70]))
        print("   (abandon, rien n'a ete touche)")
        return

    faits = appliquer(fiches, a.appliquer)
    if a.appliquer:
        print("\n%d renommage(s) effectues, journalises dans data/%s"
              % (len(faits), JOURNAL.name))
        print("Retour arriere : python scripts/reparer_extensions.py "
              "--annuler --appliquer")
    else:
        print("\nConstat seul : rien n'a ete ecrit. "
              "Ajouter --appliquer pour renommer.")


if __name__ == "__main__":
    main()
