"""Les rushs bruts servis aux VA — et ceux qu'on a mis de côté.

Pourquoi ce module
------------------
Le filtre « une vraie vidéo brute » était recopié à au moins trois endroits :
le site (`_brutes_d_identite`) et deux commandes du bot. Chaque copie devait
connaître les mêmes règles — bonne extension, pas de `.example` — et le jour
où une quatrième règle apparaît, c'est trois endroits à modifier, dont un
qu'on oublie.

Cette quatrième règle est arrivée : une brute qui porte **déjà une caption
incrustée** ne doit plus jamais partir chez un VA. En oublier un seul appel
suffirait à ce qu'elle continue d'être envoyée — et personne ne le verrait,
puisque ça marcherait « presque ».

Désactiver, pas supprimer
-------------------------
Le site n'efface jamais un média (cf. CLAUDE.md). Une brute désactivée reste
sur le disque : seul un fichier voisin s'ajoute à côté d'elle. C'est
réversible, et le voisin garde la CAUSE et la DATE — sans quoi on retombe six
mois plus tard sur une vidéo éteinte sans savoir par qui ni pourquoi.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Le voisin qui éteint une vidéo. Même convention que les autres métadonnées
#: du projet (.txt, .desc.txt, .montage.json, .analyse.json).
SUFFIXE = ".off.json"

#: Écrit dans le voisin quand c'est l'examen de texte qui a éteint la vidéo.
#: Le bouton inverse ne remet en service QUE ça : une brute éteinte à la main
#: pour une autre raison n'a aucune raison de revenir avec lui.
CAUSE_TEXTE = "caption déjà incrustée"

#: Les extensions considérées comme des vidéos, si l'appelant n'en impose pas.
EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"})


def lire(video: Path) -> dict:
    """Le voisin de désactivation, ou {} si la brute est en service."""
    try:
        return json.loads(
            video.with_suffix(SUFFIXE).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def est_desactivee(video: Path) -> bool:
    try:
        return video.with_suffix(SUFFIXE).exists()
    except Exception:
        return False


def desactiver(video: Path, cause: str = "") -> bool:
    """Met la vidéo de côté. Le fichier vidéo n'est pas touché."""
    import datetime as _dt
    try:
        import safe_json
        return bool(safe_json.write(
            video.with_suffix(SUFFIXE),
            {"cause": (cause or "").strip()[:200],
             "le": _dt.datetime.now().strftime("%d/%m/%Y %H:%M")},
            indent=None))
    except Exception:
        return False


def reactiver(video: Path) -> bool:
    try:
        video.with_suffix(SUFFIXE).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def lister(dossier, extensions=None, inclure_desactivees: bool = False) -> list:
    """Les brutes d'un dossier, triées par nom.

    C'est LA porte d'entrée : tout ce qui finit chez un VA passe par ici.
    `inclure_desactivees` n'est vrai que pour les vues du propriétaire, qui
    doivent au contraire MONTRER ce qui est éteint.
    """
    d = Path(dossier)
    if not d.exists():
        return []
    exts = extensions or EXTENSIONS
    out = []
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if ".example" in p.name:
            continue
        if not inclure_desactivees and est_desactivee(p):
            continue
        out.append(p)
    return out


def sans_desactivees(videos) -> list:
    """Filtre une liste déjà constituée — pour les appelants qui ne peuvent
    pas passer par `lister` (favoris lus depuis un registre, par exemple)."""
    return [p for p in videos if not est_desactivee(Path(p))]
