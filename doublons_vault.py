# -*- coding: utf-8 -*-
"""Les copies EXACTES d'un media dans un meme dossier du vault : rangees
automatiquement, jamais effacees.

POURQUOI CE FICHIER EXISTE

Le proprietaire, le 26/09/2026, devant les « _2_2 » de themikkiangel : « ne
supprime pas, mets[-le] de facon automatique ». Mesure le meme jour : 885
copies octet pour octet dans tout le vault (1,2 Go) -- emma/stories 151,
julia/profile_pics 143, lillaroseconlon/brutes 123, brune/posts 101...

D'OU ELLES VIENNENT (et pourquoi un rangement a la main ne tenait pas)

Le 15/08, l'import Drive renommait en « x_2 » un nom deja pris ; la synchro
montante renvoyait x_2 au Drive, l'import suivant le ramenait en « x_2_2 » :
une couche par minute. /gdrive/doublons a range 4364 copies a 01:52... et le
16/08, 343 sont revenues du Drive, l'import reprenant tout fichier absent du
site. Ce module ne suffit donc pas seul : gdrive_sync._candidats_import
ecarte desormais un media dont le CONTENU (taille + md5) est deja dans le
dossier, et un voisin dont le media n'est plus la. Sans ces deux garde-fous,
155 medias et 227 voisins revenaient dans la minute (simule le 26/09).

CE QUI EST UN DOUBLON

  - meme dossier data/identities/<identite>/<section> : la meme photo dans
    posts ET stories est voulue (476 groupes), pas un doublon ;
  - memes octets : taille puis md5 COMPLET. Jamais la forme du nom -- «
    IMG_8013 », « pp_67 » finissent deja par des chiffres, et brune/posts a
    ses copies sous des noms sans rapport ;
  - un media, pas un voisin : deux captions identiques sont normales (pool
    commun, captions vides).

QUEL EXEMPLAIRE RESTE

La racine de la chaine de suffixes (gdrive_sync._parents_possibles, la regle
meme de l'import Drive), puis celui qui porte le plus (voisins, marques),
puis l'ordre naturel des noms (pp_1 avant pp_11). Jamais la date : les
re-imports du 16/08 ont rendu x_2 plus recent que x_2_2, et chaque
deploiement remet les ctime a zero (chown -R).

RIEN NE SE PERD

Avant de ranger une copie, ce qu'elle porte et que l'exemplaire garde n'a pas
passe sur lui : caption, description, montage, vues, etoile, Flash/Trash,
etat eteint (avec le verdict de texte qui l'a motive -- sinon « remettre
sans_texte » le rallumait). Deux versions differentes d'un meme travail
(deux captions, deux montages, un banger sur deux exemplaires) : le groupe
n'est PAS touche, et il est liste avec sa raison.

La copie part avec TOUS ses voisins dans
data/_corbeille_doublons/<AAAAMMJJ-HHMMSS>/<identite>/<section>/, avec un
manifeste.json : un passage se restaure (restaurer()), et une copie
restauree est retenue comme voulue -- le passage suivant ne la reprend pas.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import safe_json

_ICI = Path(__file__).resolve().parent
DATA = _ICI / "data"
CORBEILLE = DATA / "_corbeille_doublons"
#: Ce qu'on SUPPRIME sur le site ou depuis le bot (supprimer()) : meme
#: machinerie, corbeille a part. Le site n'efface jamais un media.
CORBEILLE_SUPPRESSIONS = DATA / "_corbeille_suppressions"
#: {"<identite>|<section>": {md5: {"nom", "le"}}} : le contenu supprime sur
#: le site. L'import Drive le consulte : sans lui, un media supprime revenait
#: du Drive dans la minute (la veille reprend tout ce qui manque au site).
SUPPRIMES = DATA / "supprimes_du_site.json"
JOURNAL = DATA / "doublons_vault.json"
EXCEPTIONS = DATA / "doublons_exceptions.json"
DOSSIER_MD5 = DATA / "empreintes_md5"

#: Un fichier modifie depuis moins longtemps est peut-etre encore en cours
#: d'ecriture (depot, import) : on repassera.
RECENT_SEC = 600
PASSES_GARDEES = 60

#: Les voisins d'un media, par leur nom EXACT « <tige><suffixe> » -- la liste
#: de /cloud/delete, plus .perfect.json. `humain` : un travail (deux versions
#: differentes = conflit) ; `auto` : regenerable, celui du garde prime.
#: .off.json et .textecheck.json vont ensemble (voir _plan_groupe) ;
#: .thumb.jpg se refait, il part avec sa copie.
VOISINS = (
    (".txt", "humain"),
    (".desc.txt", "humain"),
    (".acheck.txt", "humain"),
    (".montage.json", "humain"),
    (".perfect.json", "humain"),
    (".analyse.json", "auto"),
    (".social.json", "auto"),
    (".montage.png", "auto"),
    (".off.json", "etat"),
    (".textecheck.json", "etat"),
    (".thumb.jpg", "jetable"),
)
#: Les copies de secours que safe_json laisse a cote d'un JSON.
PREV = ".prev"

_VERROU = threading.Lock()


# ------------------------------------------------------------------ medias

def _sections():
    import gdrive_sync as _gd
    return [(s, video) for s, _nom, video in _gd.SECTIONS]


def _exts_media(video: bool) -> set:
    import gdrive_sync as _gd
    return set(_gd.VIDEO_EXTS if video else _gd.IMAGE_EXTS)


def est_media(nom: str, video: bool) -> bool:
    """Un media de cette section, et pas un voisin qui en a l'extension
    (« x.example.mp4 », « x.thumb.jpg », « x.montage.png »)."""
    bas = nom.lower()
    if Path(bas).suffix not in _exts_media(video):
        return False
    return not (".example." in bas or bas.endswith(".thumb.jpg")
                or bas.endswith(".montage.png"))


def est_un_media(nom: str) -> bool:
    """Un media, video ou image, quelle que soit la section."""
    return est_media(nom, True) or est_media(nom, False)


def voisins_de(tige: str, noms: Iterable[str]) -> List[str]:
    """Les voisins presents de la tige `tige`, copies de secours comprises."""
    noms = set(noms)
    out = []
    for suf, _k in VOISINS:
        for n in (tige + suf, tige + suf + PREV):
            if n in noms:
                out.append(n)
    ex = tige + ".example."
    out += sorted(n for n in noms if n.startswith(ex))
    return out


def _cle_naturelle(nom: str):
    # isdecimal, pas isdigit : « ² » passe isdigit et int("²") leve -- tout
    # le passage tombait, chaque heure
    return [int(t) if t.isdecimal() else t.lower() for t in re.split(r"(\d+)", nom)]


# --------------------------------------------------------------------- md5

def _fichier_md5(dossier: Path) -> Path:
    return DOSSIER_MD5 / f"{dossier.parent.name}__{dossier.name}.json"


class _Md5:
    """Le md5 des fichiers d'UN dossier, garde en cache par (taille, date) :
    un passage ne relit que ce qui a change."""

    def __init__(self, dossier: Path):
        self.dossier = dossier
        d = safe_json.load(_fichier_md5(dossier), default={})
        self.cache = d if isinstance(d, dict) else {}
        self.change = False

    def de(self, nom: str) -> Optional[str]:
        p = self.dossier / nom
        try:
            st = p.stat()
        except OSError:
            return None
        sig = [st.st_size, st.st_mtime_ns]
        c = self.cache.get(nom)
        if isinstance(c, list) and len(c) == 3 and c[:2] == sig:
            return c[2]
        h = hashlib.md5()
        try:
            with p.open("rb") as f:
                for bloc in iter(lambda: f.read(1 << 20), b""):
                    h.update(bloc)
        except OSError:
            return None
        self.cache[nom] = sig + [h.hexdigest()]
        self.change = True
        return h.hexdigest()

    def fermer(self, presents: Optional[set] = None) -> None:
        if presents is not None:
            for n in [n for n in self.cache if n not in presents]:
                self.cache.pop(n, None)
                self.change = True
        if self.change:
            try:
                DOSSIER_MD5.mkdir(parents=True, exist_ok=True)
                safe_json.write(_fichier_md5(self.dossier), self.cache)
            except Exception:
                pass      # un cache perdu se recalcule
            self.change = False


class IndexContenu:
    """Pour l'import Drive : « ce contenu est-il deja dans ce dossier ? ».

    La veille rescanne le Drive chaque minute ; apres un rangement, une
    centaine de fichiers Drive passent ce test a chaque tour. Les tailles
    d'un dossier sont donc lues UNE fois par scan, et seuls les fichiers de
    meme taille sont lus (md5 garde en cache par taille et date)."""

    def __init__(self):
        self._tailles: Dict[Path, Dict[int, list]] = {}
        self._md5: Dict[Path, _Md5] = {}

    def present(self, dossier: Path, taille: int, md5: str,
                video: Optional[bool] = None) -> Optional[str]:
        if not taille or not md5:
            return None
        t = self._tailles.get(dossier)
        if t is None:
            t = {}
            try:
                for p in dossier.iterdir():
                    try:
                        if p.is_file():
                            t.setdefault(p.stat().st_size, []).append(p.name)
                    except OSError:
                        pass
            except OSError:
                pass
            self._tailles[dossier] = t
        noms = sorted(n for n in t.get(taille, ())
                      if video is None or est_media(n, video))
        if not noms:
            return None
        m = self._md5.get(dossier)
        if m is None:
            m = self._md5[dossier] = _Md5(dossier)
        for n in noms:
            if m.de(n) == md5:
                return n
        return None

    def fermer(self) -> None:
        for m in self._md5.values():
            m.fermer()


def contenu_present(dossier: Path, taille: int, md5: str,
                    video: Optional[bool] = None) -> Optional[str]:
    """Le nom d'un media de `dossier` qui a exactement ce contenu, ou None."""
    idx = IndexContenu()
    try:
        return idx.present(dossier, taille, md5, video)
    finally:
        idx.fermer()


# ------------------------------------------------------------- registres

class Registres:
    """Ce que le site range par « identite|section|nom » (etoile, favori,
    desactive, Flash/Trash). web_upload en fournit la vraie version ; celle-ci
    ne porte rien (tests, simulation)."""

    def marques(self, fid: str) -> set:
        return set()

    def transferer(self, de: str, vers: str) -> List[str]:
        return []

    def oublier(self, fid: str) -> List[str]:
        return []

    def apres_rangement(self, ident: str, section: str, nom: str) -> None:
        pass


# ------------------------------------------------------------------ plans

def _meme_contenu(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _choisir(groupe: List[str], poids: Callable[[str], int]) -> str:
    # casse ignoree : « x_2.mp4 » est une copie de « x.MP4 » (l'extension
    # passe en minuscules chez certains importeurs)
    noms = {n.lower() for n in groupe}
    racines = [n for n in groupe
               if not any(p.lower() in noms for p in _parents(n))]
    cands = racines or list(groupe)
    return sorted(cands, key=lambda n: (-poids(n), _cle_naturelle(n)))[0]


def _parents(nom: str) -> list:
    import gdrive_sync as _gd
    return _gd._parents_possibles(nom)


def _plan_groupe(dossier: Path, ident: str, section: str, groupe: List[str],
                 noms: set, medias: set, reg: Registres) -> dict:
    """Ce qu'il faudrait faire pour ce groupe -- ou pourquoi on n'y touche pas."""
    fid = lambda n: f"{ident}|{section}|{n}"
    tiges = {n: Path(n).stem for n in groupe}
    # Une tige portee par un autre media (x.mp4 et x.MOV) : ses voisins sont
    # a DEUX medias, en emporter un les arracherait a l'autre.
    for n in groupe:
        autres = [m for m in medias if m != n and Path(m).stem == tiges[n]]
        if autres:
            return {"conflit": f"« {n} » partage ses voisins avec « {autres[0]} »"}
    marques = {n: reg.marques(fid(n)) for n in groupe}

    # Grise (⊘) ou eteinte A LA MAIN sur un exemplaire, en service sur un
    # autre : « ce contenu est mauvais » ou « c'est la copie en trop » ? On ne
    # tranche pas -- reporter l'etat eteignait le seul exemplaire servi aux
    # VA, sans un mot. Seul le verdict du reperage de texte tient au contenu
    # lui-meme (memes octets, meme texte incruste) : lui passe sur le garde.
    import brutes_off as _off
    desactives = [n for n in groupe if "disabled" in marques[n]]
    if desactives and len(desactives) < len(groupe):
        return {"conflit": "désactivé (⊘) sur " + ", ".join(desactives)
                           + ", en service sur l'autre"}
    eteints = [n for n in groupe if tiges[n] + _off.SUFFIXE in noms]
    if eteints and len(eteints) < len(groupe):
        def _cause(n):
            d = safe_json.load(dossier / (tiges[n] + _off.SUFFIXE), default={})
            return d.get("cause") if isinstance(d, dict) else None
        a_la_main = [n for n in eteints if _cause(n) != _off.CAUSE_TEXTE]
        if a_la_main:
            return {"conflit": "éteint à la main sur " + ", ".join(a_la_main)
                               + ", en service sur l'autre"}

    def _poids(n):
        # ce qui est un TRAVAIL (caption, montage, vues, etoile) ; pas l'etat
        # eteint ni le verdict de texte, qui ne doivent pas attirer le choix
        return (len([v for v in voisins_de(tiges[n], noms)
                     if not v.endswith((".textecheck.json", ".thumb.jpg", ".off.json", PREV))])
                + len(marques[n] - {"disabled"}))
    garde = _choisir(groupe, _poids)
    copies = [n for n in groupe if n != garde]
    tg = tiges[garde]
    renommes: List[list] = []        # [voisin d'une copie, nouveau nom]
    ecartes_du_garde: List[str] = []  # voisins du garde remplaces

    # marques : une seule version possible par exemplaire
    avec_banger = [n for n in groupe if "banger" in marques[n]]
    if len(avec_banger) > 1:
        return {"conflit": "étoile banger sur " + " et ".join(avec_banger), "garde": garde}
    toutes = set().union(*marques.values())
    if "flash" in toutes and "trash" in toutes:
        return {"conflit": "Flash sur l'un, Trash sur l'autre", "garde": garde}

    # voisins de travail et regenerables
    for suf, genre in VOISINS:
        if genre not in ("humain", "auto"):
            continue
        porteurs = [c for c in copies if tiges[c] + suf in noms]
        if not porteurs:
            continue
        if tg + suf in noms:
            if genre == "humain":
                for c in porteurs:
                    if not _meme_contenu(dossier / (tg + suf), dossier / (tiges[c] + suf)):
                        return {"conflit": f"deux {suf} différents ({garde} / {c})", "garde": garde}
            continue
        if genre == "humain" and len({(dossier / (tiges[c] + suf)).read_bytes()
                                      for c in porteurs}) > 1:
            return {"conflit": f"deux {suf} différents parmi les copies", "garde": garde}
        renommes.append([tiges[porteurs[0]] + suf, tg + suf])
    # les exemples, extension par extension
    for c in copies:
        pre = tiges[c] + ".example."
        for v in sorted(n for n in noms if n.startswith(pre)):
            cible = tg + ".example." + v[len(pre):]
            if cible in noms:
                if not _meme_contenu(dossier / cible, dossier / v):
                    return {"conflit": f"deux exemples différents ({garde} / {c})", "garde": garde}
            elif cible not in {r[1] for r in renommes}:
                renommes.append([v, cible])

    # etat eteint : il passe sur le garde AVEC le verdict de texte qui l'a
    # motive -- sinon « remettre sans_texte » le rallumait au prochain clic
    if tg + ".off.json" not in noms:
        eteintes = [c for c in copies if tiges[c] + ".off.json" in noms]
        if eteintes:
            c = eteintes[0]
            renommes.append([tiges[c] + ".off.json", tg + ".off.json"])
            if tiges[c] + ".textecheck.json" in noms:
                if tg + ".textecheck.json" in noms:
                    ecartes_du_garde.append(tg + ".textecheck.json")
                renommes.append([tiges[c] + ".textecheck.json", tg + ".textecheck.json"])

    renommes_src = {r[0] for r in renommes}
    deplaces = {c: [c] + [v for v in voisins_de(tiges[c], noms) if v not in renommes_src]
                for c in copies}
    return {"garde": garde, "copies": copies, "renommes": renommes,
            "ecartes_du_garde": ecartes_du_garde, "deplaces": deplaces,
            "marques": {c: sorted(marques[c]) for c in copies if marques[c]}}


def _sig(p: Path):
    try:
        st = p.stat()
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


# ------------------------------------------------------------------ passe

def _exceptions() -> dict:
    d = safe_json.load(EXCEPTIONS, default={})
    return d if isinstance(d, dict) else {}


def trouver(racine: Path, exclure: Iterable[str] = (), maintenant: Optional[float] = None) -> dict:
    """Les groupes de copies, SANS rien toucher."""
    maintenant = time.time() if maintenant is None else maintenant
    exclure = {str(x).lower() for x in (exclure or ())}
    exc = _exceptions()
    groupes, erreurs = [], []
    ecartes = {"recents": 0, "en_cours_d_ecriture": 0, "liens": 0,
               "voulus": 0, "identites_occupees": 0, "illisibles": 0}
    try:
        idents = sorted(p for p in racine.iterdir() if p.is_dir())
    except OSError:
        idents = []
    for ident_dir in idents:
        ident = ident_dir.name
        if ident.lower() in exclure:
            ecartes["identites_occupees"] += 1
            continue
        for section, video in _sections():
            dossier = ident_dir / section
            if not dossier.is_dir():
                continue
            try:
                groupes += _trouver_dossier(dossier, ident, section, video, exc, ecartes, maintenant)
            except Exception as e:
                # un dossier illisible ne fait plus tomber tout le vault : il
                # est compte, et dit
                ecartes["illisibles"] += 1
                erreurs.append(f"{ident}/{section} illisible : {type(e).__name__}: {e}"[:200])
    return {"groupes": groupes, "ecartes": ecartes, "erreurs": erreurs}


def _trouver_dossier(dossier: Path, ident: str, section: str, video: bool, exc: dict,
                     ecartes: dict, maintenant: float) -> list:
    fichiers = [p for p in dossier.iterdir() if p.is_file()]
    noms = {p.name for p in fichiers}
    medias = {p.name for p in fichiers if est_media(p.name, video)}
    par_taille: Dict[int, list] = {}
    for n in medias:
        try:
            t = (dossier / n).stat().st_size
        except OSError:
            continue
        if t > 0:
            par_taille.setdefault(t, []).append(n)
    out = []
    md5 = _Md5(dossier)
    try:
        for t, lot in par_taille.items():
            if len(lot) < 2:
                continue
            par_md5: Dict[str, list] = {}
            for n in lot:
                h = md5.de(n)
                if h:
                    par_md5.setdefault(h, []).append(n)
            for h, g in par_md5.items():
                if len(g) < 2:
                    continue
                g = sorted(g, key=_cle_naturelle)
                if any(exc.get(f"{ident}|{section}|{n}") == h for n in g):
                    ecartes["voulus"] += 1
                    continue
                if any(n + ".part" in noms for n in g):
                    ecartes["en_cours_d_ecriture"] += 1
                    continue
                try:
                    sts = [(dossier / n).stat() for n in g]
                except OSError:
                    continue          # parti entre-temps : au prochain passage
                if any(maintenant - x.st_mtime < RECENT_SEC for x in sts):
                    ecartes["recents"] += 1
                    continue
                if any(x.st_nlink > 1 for x in sts):
                    ecartes["liens"] += 1
                    continue
                out.append({"ident": ident, "section": section, "md5": h,
                            "taille": t, "membres": g, "dossier": dossier,
                            "noms": noms, "medias": medias, "video": video,
                            "sigs": {n: _sig(dossier / n) for n in g}})
    finally:
        md5.fermer(medias)
    return out


MANIFESTE = "manifeste.jsonl"


def _ecrire_manifeste(base: Path, ligne: dict) -> None:
    """Une ligne par etape, ajoutee et forcee sur le disque AVANT de bouger :
    un redemarrage (chaque deploiement) en plein passage laisse une trace
    restaurable. Leve si l'ecriture echoue -- le passage s'arrete alors."""
    base.mkdir(parents=True, exist_ok=True)
    with (base / MANIFESTE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _lire_manifeste(base: Path) -> list:
    out = []
    try:
        texte = (base / MANIFESTE).read_text(encoding="utf-8")
    except OSError:
        return out
    for l in texte.splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue          # derniere ligne coupee par un arret brutal
        if isinstance(d, dict):
            out.append(d)
    return out


def passe(racine: Path, reg: Optional[Registres] = None, actif: bool = False,
          exclure: Iterable[str] = (), verrou: Optional[Callable] = None,
          renommer_social: Optional[Callable] = None,
          occupee: Optional[Callable[[str], bool]] = None) -> dict:
    """Un passage sur tout le vault. `actif=False` : simulation (rien ne bouge).

    `verrou()` : un gestionnaire de contexte qui rend True quand on a la main
    (la synchro Drive est a l'arret) ; sans la main, rien n'est deplace et le
    bilan dit « differe ». `renommer_social(ident, section, ancien, nouveau)` :
    les vues TikTok/Instagram qui designaient la copie designent le garde.
    `occupee(ident)` : relu juste avant chaque groupe (un import qui demarre
    pendant le passage)."""
    reg = reg or Registres()
    debut = time.time()
    with _VERROU:
        trouve = trouver(racine, exclure)
        bilan = {"ts": int(debut), "actif": bool(actif), "groupes": 0,
                 "copies": 0, "octets": 0, "conflits": [],
                 "erreurs": list(trouve["erreurs"]), "avertissements": [],
                 "ecartes": trouve["ecartes"], "dossier": None, "differe": False,
                 "par_dossier": {}}
        plans = []
        for g in trouve["groupes"]:
            try:
                p = _plan_groupe(g["dossier"], g["ident"], g["section"], g["membres"],
                                 g["noms"], g["medias"], reg)
            except Exception as e:
                p = {"conflit": f"illisible : {type(e).__name__}: {e}"[:200]}
            if "conflit" in p:
                _conflit(bilan, g, p.get("garde"), p["conflit"])
                continue
            plans.append((g, p))
        if not actif:
            for g, p in plans:
                _compter(bilan, g, p)
            return _journaliser(bilan, debut)
        if not plans:
            return _journaliser(bilan, debut)
        ctx = verrou() if verrou else _libre()
        with ctx as a_la_main:
            if not a_la_main:
                bilan["differe"] = True
                return _journaliser(bilan, debut)
            nom_passe = time.strftime("%Y%m%d-%H%M%S", time.localtime(debut))
            base = CORBEILLE / nom_passe
            k = 2
            while base.exists():
                base = CORBEILLE / f"{nom_passe}-{k}"
                k += 1
            for g, p in plans:
                if occupee and occupee(g["ident"]):
                    _conflit(bilan, g, p["garde"], "import TikTok/Instagram en cours : au prochain passage")
                    continue
                cle = {"ident": g["ident"], "section": g["section"], "md5": g["md5"],
                       "garde": p["garde"]}
                try:
                    _ecrire_manifeste(base, dict(cle, type="prevu", copies=p["deplaces"],
                                                 renommes=p["renommes"],
                                                 ecartes_du_garde=p["ecartes_du_garde"],
                                                 marques=p["marques"]))
                except Exception as e:
                    bilan["erreurs"].append(f"manifeste non écrit ({type(e).__name__}: {e}) : "
                                            "passage arrêté, plus rien n'est rangé"[:240])
                    break
                fait = _appliquer(g, p, base, reg, renommer_social)
                try:
                    _ecrire_manifeste(base, dict(cle, type="abandon" if fait.get("raison") else "fait",
                                                 **{k2: v for k2, v in fait.items() if k2 not in cle}))
                except Exception as e:
                    bilan["erreurs"].append(f"manifeste non écrit ({type(e).__name__}: {e}) : "
                                            "passage arrêté"[:240])
                    break
                bilan["avertissements"] += [f"{g['ident']}/{g['section']} : {a}"
                                            for a in fait.get("avertissements") or ()]
                if fait.get("raison"):
                    _conflit(bilan, g, p["garde"], fait["raison"])
                    continue
                if fait.get("erreur"):
                    bilan["erreurs"].append(f"{g['ident']}/{g['section']} {g['membres'][0]} : "
                                            + fait["erreur"])
                if any(fait.get("copies", {}).values()) or fait.get("renommes"):
                    bilan["dossier"] = base.name
                if fait.get("erreur"):
                    continue
                _compter(bilan, g, p)
                for c, mq in fait["marques"].items():
                    bilan.setdefault("marques", []).append({
                        "doublon": f"{g['ident']}|{g['section']}|{c}",
                        "original": f"{g['ident']}|{g['section']}|{p['garde']}",
                        "marques": mq})
    return _journaliser(bilan, debut)


class _libre:
    def __enter__(self):
        return True

    def __exit__(self, *a):
        return False


def _conflit(bilan: dict, g: dict, garde, raison: str) -> None:
    bilan["conflits"].append({"ou": f"{g['ident']}/{g['section']}",
                              "membres": g["membres"], "garde": garde, "raison": raison})


def _compter(bilan: dict, g: dict, p: dict) -> None:
    n = len(p["copies"])
    bilan["groupes"] += 1
    bilan["copies"] += n
    bilan["octets"] += n * g["taille"]
    ou = f"{g['ident']}/{g['section']}"
    bilan["par_dossier"][ou] = bilan["par_dossier"].get(ou, 0) + n


def _appliquer(g: dict, p: dict, base: Path, reg: Registres,
               renommer_social: Optional[Callable]) -> dict:
    """Reporte, renomme, range. Rien n'est ecrase, rien n'est efface."""
    dossier, ident, section = g["dossier"], g["ident"], g["section"]
    fid = lambda n: f"{ident}|{section}|{n}"
    # 1) rien n'a bouge depuis le reperage ? Les md5 se lisent HORS pause
    # (des minutes au premier passage) : un depot, une caption corrigee, une
    # marque posee entre-temps etaient sinon perdus. Le plan est refait sur
    # le dossier tel qu'il est ; s'il differe, on repasse.
    for n in g["membres"]:
        if _sig(dossier / n) != g["sigs"].get(n):
            return {"raison": f"« {n} » a changé depuis le repérage"}
    try:
        noms = {q.name for q in dossier.iterdir() if q.is_file()}
        frais = _plan_groupe(dossier, ident, section, g["membres"], noms,
                             {n for n in noms if est_media(n, g["video"])}, reg)
    except Exception as e:
        return {"raison": f"relecture impossible : {type(e).__name__}: {e}"[:200]}
    if "conflit" in frais:
        return {"raison": frais["conflit"]}
    if frais != p:
        return {"raison": "voisins ou marques changés depuis le repérage : au prochain passage"}
    # 2) les marques d'abord : si le report echoue, rien n'a encore bouge
    marques = {}
    for c, mq in p["marques"].items():
        err = reg.transferer(fid(c), fid(p["garde"]))
        if err:
            return {"raison": "marques non reportées : " + "; ".join(err)[:200]}
        marques[c] = mq
    cible = base / ident / section
    fait = {"copies": {}, "renommes": [], "ecartes_du_garde": [], "marques": marques}
    try:
        cible.mkdir(parents=True, exist_ok=True)
        _deplacer(dossier, cible, p, fait, reg, renommer_social, fid, ident, section)
    except Exception as e:
        # rendu avec ce qui a DEJA bouge : l'appelant l'ecrit au manifeste
        fait["erreur"] = f"{type(e).__name__}: {e}"[:200]
    return fait


def _deplacer(dossier: Path, cible: Path, p: dict, fait: dict, reg: Registres,
              renommer_social: Optional[Callable], fid: Callable,
              ident: str, section: str) -> None:
    # 3) le voisin du garde qu'un voisin de copie remplace part en corbeille
    for n in p["ecartes_du_garde"]:
        if (dossier / n).exists() and not (cible / n).exists():
            shutil.move(str(dossier / n), str(cible / n))
            fait["ecartes_du_garde"].append(n)
    # 4) ce que les copies portent passe sur le garde (la signature permet a
    # restaurer() de le rendre s'il n'a pas ete modifie depuis)
    for src, dst in p["renommes"]:
        if (dossier / dst).exists():
            continue                     # jamais ecraser
        os.rename(dossier / src, dossier / dst)
        fait["renommes"].append([src, dst, _sig(dossier / dst)])
    # 5) les copies et leurs voisins restants, a la corbeille -- inscrites
    # fichier par fichier : un echec au milieu reste restaurable
    for c, liste in p["deplaces"].items():
        partis = fait["copies"].setdefault(c, [])
        try:
            for n in liste:
                if not (dossier / n).exists() or (cible / n).exists():
                    continue
                try:
                    shutil.move(str(dossier / n), str(cible / n))
                except FileNotFoundError:
                    if (dossier / n).exists():
                        raise
                    continue      # efface entre-temps (rallumer, /a-relire)
                partis.append(n)
        finally:
            if c in partis:       # le media est parti : ses suites aussi
                for e in reg.oublier(fid(c)):
                    fait.setdefault("avertissements", []).append(e)
                if renommer_social:
                    try:
                        renommer_social(ident, section, c, p["garde"])
                    except Exception as e:
                        fait.setdefault("avertissements", []).append(f"vues : {e}"[:160])
                try:
                    reg.apres_rangement(ident, section, c)
                except Exception:
                    pass


def _journaliser(bilan: dict, debut: float) -> dict:
    """Au journal : ce qui a range, ce qui est en conflit ou en erreur, ce qui
    a ete differe. Un passage horaire sans rien a faire ne met a jour que
    « dernier » -- sinon, en vingt heures, il poussait hors de la page le
    passage qui avait range."""
    bilan["duree"] = round(time.time() - debut, 1)
    j = safe_json.load(JOURNAL, default={}) or {}
    j = j if isinstance(j, dict) else {}
    passes = [x for x in (j.get("passes") or []) if isinstance(x, dict)]
    utile = (bilan["copies"] or bilan["conflits"] or bilan["erreurs"]
             or bilan.get("avertissements") or bilan.get("differe"))
    if utile:
        court = dict(bilan)
        court["conflits_n"] = len(bilan["conflits"])
        court["conflits"] = bilan["conflits"][:40]
        court["erreurs"] = bilan["erreurs"][:20]
        court["avertissements"] = (bilan.get("avertissements") or [])[:40]
        passes.append(court)
        j["passes"] = passes[-PASSES_GARDEES:]
    if bilan["actif"]:
        j["dernier"] = {"ts": bilan["ts"], "copies": bilan["copies"],
                        "differe": bilan["differe"], "duree": bilan["duree"]}
    if utile or bilan["actif"]:
        try:
            safe_json.write(JOURNAL, j, indent=1)
        except Exception:
            pass
    return bilan


def journal() -> list:
    j = safe_json.load(JOURNAL, default={}) or {}
    return [x for x in (j.get("passes") or []) if isinstance(x, dict)] if isinstance(j, dict) else []


def dernier() -> dict:
    j = safe_json.load(JOURNAL, default={}) or {}
    d = j.get("dernier") if isinstance(j, dict) else None
    return d if isinstance(d, dict) else {}


def passages(corbeille: Optional[Path] = None) -> list:
    """Les passages qui ont range quelque chose, lus dans la corbeille elle-
    meme (pas dans le journal) : tant que la corbeille les garde, ils se
    restaurent."""
    corbeille = CORBEILLE if corbeille is None else corbeille
    out = []
    try:
        dossiers = sorted((d for d in corbeille.iterdir()
                           if d.is_dir() and (d / MANIFESTE).exists()), reverse=True)
    except OSError:
        return out
    for d in dossiers:
        lignes = _lire_manifeste(d)
        faits = {_cle_groupe(l): l for l in lignes if l.get("type") in ("fait", "abandon")}
        prevus = [l for l in lignes if l.get("type") == "prevu"]
        interrompus = [l for l in prevus if _cle_groupe(l) not in faits]
        n = sum(1 for l in faits.values() if l.get("type") == "fait"
                for c, fs in (l.get("copies") or {}).items() if c in fs)
        if not n and not interrompus:
            continue
        restaures = [l for l in lignes if l.get("type") == "restaure"]
        noms = [c for l in faits.values() if l.get("type") == "fait"
                for c, fs in (l.get("copies") or {}).items() if c in fs]
        out.append({"nom": d.name, "copies": n, "interrompus": len(interrompus),
                    "restaure": bool(restaures), "noms": noms[:12],
                    "ts": _ts_passage(d.name, lignes)})
    return out


def _ts_passage(nom: str, lignes: list) -> int:
    """L'heure d'un passage : celle de son dossier (« 20260926-041209 », heure
    du serveur). Les lignes du rangement des doublons ne la portent pas --
    la page affichait « 01/01 01:00 »."""
    try:
        return int(time.mktime(time.strptime(nom[:15], "%Y%m%d-%H%M%S")))
    except ValueError:
        return min((l.get("ts") or 0 for l in lignes if l.get("ts")), default=0)


def _cle_groupe(l: dict) -> tuple:
    return (l.get("ident"), l.get("section"), l.get("garde"), l.get("md5"),
            tuple(sorted((l.get("copies") or {}).keys())))


# -------------------------------------------------------------- restaurer

def restaurer(racine: Path, nom_passe: str, corbeille: Optional[Path] = None) -> dict:
    """Remet en place ce qu'un passage a range (jamais par-dessus un fichier).

    Dans l'ordre : ce qui etait passe sur le garde revient a sa copie (sinon
    l'etat eteint changeait d'exemplaire), le voisin du garde qu'il avait
    remplace revient, puis la copie et ses voisins. Une copie restauree est
    retenue comme VOULUE (doublons_exceptions.json), ecrit AVANT de remettre :
    sans ca, le passage suivant la rangeait de nouveau. Les marques
    (etoile, Flash...) restent sur l'exemplaire garde."""
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}(-[0-9]+)?", nom_passe or ""):
        return {"ok": False, "error": "passage inconnu"}
    base = (CORBEILLE if corbeille is None else corbeille) / nom_passe
    lignes = _lire_manifeste(base)
    groupes: Dict[tuple, dict] = {}
    for l in lignes:
        if l.get("type") in ("prevu", "fait"):
            groupes.setdefault(_cle_groupe(l), {})[l["type"]] = l
    if not groupes:
        return {"ok": False, "error": "manifeste introuvable"}
    remis, bloques = 0, []
    with _VERROU:
        exc = _exceptions()
        n_exc = len(exc)
        for (ident, section, _g, md5, _c), gr in groupes.items():
            ref0 = gr.get("fait") or gr.get("prevu") or {}
            if ref0.get("supprime"):
                continue          # une suppression restauree n'est pas un doublon voulu
            for c in (ref0.get("copies") or {}):
                exc[f"{ident}|{section}|{c}"] = md5
        if len(exc) != n_exc and not safe_json.write(EXCEPTIONS, exc, indent=1):
            return {"ok": False, "error": "doublons_exceptions.json non écrit : rien n'est "
                                          "remis (les copies seraient rangées de nouveau)"}
        rendus = []           # (identite|section, md5) des suppressions remises
        for (ident, section, garde, _md5, _c), gr in groupes.items():
            src = base / ident / section
            dst = racine / ident / section
            ref0 = gr.get("fait") or gr.get("prevu") or {}
            if ref0.get("dossier"):
                # une suppression garde son dossier d'origine (identite, ou
                # reserve de photos de profil) -- jamais hors de data/
                d0 = Path(ref0["dossier"]).resolve()
                permis = {DATA.resolve(), Path(racine).resolve().parent}
                if not permis & set(d0.parents):
                    bloques.append(f"{ref0['dossier']} : hors de data/, ignoré")
                    continue
                dst = d0
            if not dst.is_dir():
                bloques.append(f"{ident}/{section} : dossier absent")
                continue
            fait = gr.get("fait")
            if fait is not None:
                for ren in reversed(fait.get("renommes") or []):
                    de, vers = ren[0], ren[1]
                    if not (dst / vers).exists():
                        continue
                    if (dst / de).exists() or len(ren) < 3 or _sig(dst / vers) != ren[2]:
                        bloques.append(f"{ident}/{section}/{vers} : modifié depuis, laissé sur {garde}")
                        continue
                    os.rename(dst / vers, dst / de)
                    remis += 1
            elif (gr.get("prevu") or {}).get("renommes"):
                bloques.append(f"{ident}/{section}/{garde} : rangement interrompu, ce qui était "
                               "passé sur lui y reste")
            ref = fait if fait is not None else gr.get("prevu") or {}
            for n in ref.get("ecartes_du_garde") or []:
                if (src / n).exists():
                    if (dst / n).exists():
                        bloques.append(f"{ident}/{section}/{n} : le nom est repris")
                        continue
                    shutil.move(str(src / n), str(dst / n))
                    remis += 1
            for copie, fichiers in (ref.get("copies") or {}).items():
                for n in fichiers:
                    if not (src / n).exists():
                        continue
                    if (dst / n).exists():
                        bloques.append(f"{ident}/{section}/{n} : le nom est repris")
                        continue
                    shutil.move(str(src / n), str(dst / n))
                    remis += 1
                if ref.get("supprime") and ref.get("md5") and (dst / copie).exists():
                    rendus.append((f"{ident}|{section}", ref["md5"]))
        if rendus:
            _oublier_supprimes(rendus)
        try:
            _ecrire_manifeste(base, {"type": "restaure", "ts": int(time.time()), "remis": remis})
        except Exception:
            pass
    return {"ok": True, "remis": remis, "bloques": bloques}


# ------------------------------------------------------------- supprimer

_CACHE_SUPPRIMES: dict = {"sig": None, "d": {}}


def _supprimes() -> dict:
    try:
        sig = SUPPRIMES.stat().st_mtime_ns
    except OSError:
        return {}
    if _CACHE_SUPPRIMES["sig"] != sig:
        d = safe_json.load(SUPPRIMES, default={})
        _CACHE_SUPPRIMES.update(sig=sig, d=d if isinstance(d, dict) else {})
    return _CACHE_SUPPRIMES["d"]


def supprime_du_site(ident: str, section: str, md5: str) -> bool:
    """Ce contenu a-t-il ete supprime sur le site, dans ce dossier ?"""
    if not md5:
        return False
    return md5 in (_supprimes().get(f"{ident}|{section}") or {})


def _oublier_supprimes(paires: list) -> None:
    d = dict(_supprimes())
    for cle, h in paires:
        (d.get(cle) or {}).pop(h, None)
    safe_json.write(SUPPRIMES, d, indent=1)


def supprimer(chemins: Iterable[Path], reg: Optional[Registres] = None) -> dict:
    """Met ces fichiers a la corbeille (CORBEILLE_SUPPRESSIONS), chaque media
    avec TOUS ses voisins -- la liste de VOISINS, la meme que le rangement
    des doublons. Rien n'est efface ; un passage se restaure (restaurer).

    Le contenu (md5) d'un media supprime dans un dossier d'identite est
    retenu (SUPPRIMES) : l'import Drive ne le ramene plus. Sans ca, un media
    supprime sur le site revenait du Drive dans la minute.

    Rend {"ranges": [{"nom", "fichiers", "avertissements"}], "echecs":
    [(nom, raison)], "passage": dossier de la corbeille ou None}."""
    reg = reg or Registres()
    chemins = [Path(c) for c in chemins]
    ranges, echecs = [], []
    if not chemins:
        return {"ranges": ranges, "echecs": echecs, "passage": None}
    with _VERROU:
        debut = time.time()
        nom_passe = time.strftime("%Y%m%d-%H%M%S", time.localtime(debut))
        base = CORBEILLE_SUPPRESSIONS / nom_passe
        k = 2
        while base.exists():
            base = CORBEILLE_SUPPRESSIONS / f"{nom_passe}-{k}"
            k += 1
        morts: Dict[str, dict] = {}
        for p in chemins:
            try:
                if not p.is_file():
                    echecs.append((p.name, "introuvable"))
                    continue
                dossier = p.parent
                ident, section = dossier.parent.name, dossier.name
                noms = {q.name for q in dossier.iterdir() if q.is_file()}
                media = est_un_media(p.name)
                # une tige portee par un autre media (x.mp4 et x.jpg) : ses
                # voisins sont a lui aussi, on ne les emporte pas
                partagee = any(q != p.name and Path(q).stem == p.stem and est_un_media(q)
                               for q in noms)
                liste = [p.name] + ([] if (partagee or not media)
                                    else voisins_de(p.stem, noms))
                h = None
                if media:
                    m = _Md5(dossier)
                    h = m.de(p.name)
                    m.fermer()
                ligne = {"ident": ident, "section": section, "dossier": str(dossier),
                         "garde": None, "md5": h, "supprime": True, "ts": int(debut)}
                _ecrire_manifeste(base, dict(ligne, type="prevu", copies={p.name: liste}))
                cible = base / ident / section
                cible.mkdir(parents=True, exist_ok=True)
                partis: List[str] = []
                try:
                    for n in liste:
                        if not (dossier / n).exists() or (cible / n).exists():
                            continue
                        shutil.move(str(dossier / n), str(cible / n))
                        partis.append(n)
                finally:
                    _ecrire_manifeste(base, dict(ligne, type="fait", copies={p.name: partis}))
                if p.name not in partis:
                    echecs.append((p.name, "non déplacé"))
                    continue
                if h and dossier.parent.parent.name == "identities":
                    morts.setdefault(f"{ident}|{section}", {})[h] = {"nom": p.name,
                                                                    "le": int(debut)}
                avert = list(reg.oublier(f"{ident}|{section}|{p.name}"))
                try:
                    reg.apres_rangement(ident, section, p.name)
                except Exception:
                    pass
                ranges.append({"nom": p.name, "fichiers": partis, "avertissements": avert})
            except Exception as e:
                echecs.append((p.name, f"{type(e).__name__}: {e}"[:160]))
        if morts:
            d = {k2: dict(v) for k2, v in _supprimes().items()}
            for cle, hs in morts.items():
                d.setdefault(cle, {}).update(hs)
            if not safe_json.write(SUPPRIMES, d, indent=1):
                echecs.append(("*", "supprimes_du_site.json non écrit : le Drive pourrait "
                                    "ramener ces médias"))
    return {"ranges": ranges, "echecs": echecs,
            "passage": base.name if ranges else None}
