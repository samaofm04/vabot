"""tests_gdrive_sync.py — le banc du LISTAGE DRIVE EN ECHEC pendant run_sync.

Lancer :  python tests_gdrive_sync.py       (depuis le dossier bot/)

Ce que ce banc reproduit, et pourquoi il existe : quand le listage d'UN dossier
Drive echoue (429 « userRateLimitExceeded »), la synchro le memorisait pour
tout le run. Consequences observees, en chaine :

  1. les 5 fichiers du dossier — 500 en vrai — echouaient tous, alors que le
     dossier repondait de nouveau une seconde plus tard ;
  2. rien n'entrait dans st["uploaded"], donc sync_report().a_envoyer ne
     descendait pas ;
  3. la synchro s'annoncait quand meme « done » : la barre du dashboard
     affiche « ✓ termine » a 100 % des que l'etat vaut « done » ;
  4. la veille (start_watcher) relançait donc une synchro COMPLETE toutes les
     60 s, indefiniment — en martelant le Drive qui repondait 429.

Aucun acces reseau, aucune ecriture dans data/ : STATE_FILE, load_config,
save_config et IDENTITIES_DIR pointent tous sur un dossier temporaire, et
_session / _lister / _ensure_folder / _upload_file sont des faux.
"""
import sys
import pathlib
import shutil
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gdrive_sync as gd                                        # noqa: E402

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{detail}]" if detail and not cond else ""))


# --------------------------------------------------------------- faux Drive
class FauxDrive:
    """Le strict minimum pour faire tourner run_sync sans reseau.

    `echecs_reels` : combien de listages du dossier « Reels » doivent lever
    un 429 avant de repondre. -1 = toujours (le 429 dure).
    """

    def __init__(self, echecs_reels=0):
        self.echecs_reels = echecs_reels
        self.envoyes = []
        self.listages = []
        self.verrou = threading.Lock()

    # _lister(sess, parent_id, dossiers=False)
    def lister(self, sess, parent_id, dossiers=False):
        with self.verrou:
            self.listages.append((parent_id, dossiers))
            n = sum(1 for p, d in self.listages
                    if p == parent_id and not d)
        if not dossiers and str(parent_id).endswith("/Reels"):
            if self.echecs_reels < 0 or n <= self.echecs_reels:
                raise gd.ErreurDrive("HTTP 429 userRateLimitExceeded",
                                     status=429,
                                     raison="userRateLimitExceeded")
        return []                      # dossier Drive vide

    # _ensure_folder(sess, parent, name, st) — un id lisible et unique
    def dossier(self, sess, parent, name, st):
        cle = str(parent) + "/" + name
        st.setdefault("folders", {})[cle] = cle
        return cle

    # _upload_file(sess, parent, path)
    def envoi(self, sess, parent, path):
        with self.verrou:
            self.envoyes.append(str(parent) + "/" + path.name)
        return "id-" + path.name


def avec_faux_drive(faux, fichiers=5, fn=None):
    """Monte une identite « julia » avec `fichiers` reels, branche le faux
    Drive, appelle `fn(tmp)` et remet tout en place."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    orig = (gd.IDENTITIES_DIR, gd.STATE_FILE, gd._session, gd._session_thread,
            gd._ensure_folder, gd._upload_file, gd._lister, gd.load_config,
            gd.save_config)
    try:
        (tmp / "identities" / "julia" / "videos").mkdir(parents=True)
        for i in range(fichiers):
            (tmp / "identities" / "julia" / "videos"
             / f"r{i}.mp4").write_bytes(b"x" * 10)
        gd.IDENTITIES_DIR = tmp / "identities"
        gd.STATE_FILE = tmp / "state.json"
        gd._session = lambda: "S"
        gd._session_thread = lambda: "S"
        gd._lister = faux.lister
        gd._ensure_folder = faux.dossier
        gd._upload_file = faux.envoi
        gd.load_config = lambda: {"folder": "RACINEbidon1234",
                                  "include_videos": True}
        gd.save_config = lambda c: True
        gd._set_status(state="idle", errors=0, err="", ts=0)
        return fn(tmp)
    finally:
        (gd.IDENTITIES_DIR, gd.STATE_FILE, gd._session, gd._session_thread,
         gd._ensure_folder, gd._upload_file, gd._lister, gd.load_config,
         gd.save_config) = orig
        gd._set_status(state="idle", errors=0, err="", ts=0)
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================== 1 =====
# Un 429 PASSAGER sur un dossier ne doit plus condamner tout le dossier.
try:
    _faux = FauxDrive(echecs_reels=1)      # le 1er listage echoue, puis ca passe
    _res = avec_faux_drive(_faux, 5, lambda tmp: gd.run_sync())
    check("listage : un 429 passager n emporte pas les 5 fichiers du dossier",
          _res["uploaded"] == 5 and _res["errors"] == 0, str(_res))
    check("listage : le dossier est bien reliste (2e essai), pas relu 5 fois",
          sum(1 for p, d in _faux.listages
              if str(p).endswith("/Reels") and not d) == 2,
          str([p for p, d in _faux.listages if not d]))
    check("listage : chaque fichier est parti une seule fois",
          len(_faux.envoyes) == 5 == len(set(_faux.envoyes)),
          str(_faux.envoyes))
except Exception as _e:                                    # pragma: no cover
    check("listage : 429 passager testable", False, repr(_e)[:200])


# ===================================================================== 2 =====
# Un 429 QUI DURE : la synchro n'a rien envoye — elle ne s'annonce pas
# « terminee ». La barre du dashboard met « ✓ termine » a 100 % sur l'etat
# « done », et c'est ce meme etat que la veille regarde pour prendre du recul.
def _persistant(tmp):
    res = gd.run_sync()
    return res, gd.status()


try:
    _faux2 = FauxDrive(echecs_reels=-1)          # le 429 ne passe pas
    _res2, _st2 = avec_faux_drive(_faux2, 5, _persistant)
    check("429 durable : les fichiers comptent en erreur, aucun envoi a l aveugle",
          _res2["errors"] == 5 and _res2["uploaded"] == 0
          and not _faux2.envoyes, str(_res2))
    check("429 durable : la synchro ne s annonce PAS « done » (barre : termine a 100 %)",
          _st2.get("state") == "error", str(_st2.get("state")))
    check("429 durable : l erreur est remontee dans l etat",
          "429" in str(_st2.get("err") or ""), str(_st2.get("err"))[:120])
    # Le dossier en echec est memorise : les 4 fichiers suivants echouent
    # sans rappeler Google. Retenter par FICHIER entretiendrait le 429.
    check("429 durable : Google n est pas martele (2 listages au plus, pas 5)",
          sum(1 for p, d in _faux2.listages
              if str(p).endswith("/Reels") and not d) <= 2,
          str(len([p for p, d in _faux2.listages if not d])))
    # L horodatage sert au recul de la veille : sans lui, elle repart aussitot.
    check("429 durable : l etat est horodate",
          abs(int(_st2.get("ts") or 0) - int(time.time())) < 120,
          str(_st2.get("ts")))
except Exception as _e:                                    # pragma: no cover
    check("429 durable : testable", False, repr(_e)[:200])


# ===================================================================== 3 =====
# La boucle infinie : une synchro finie EN ERREUR n'a rien envoye, donc
# « a_envoyer » vaut toujours 5 au tour suivant. Sans recul, la veille
# relançait une synchro complete toutes les 60 s, pour toujours.
try:
    _maintenant = time.time()
    check("recul : une synchro en erreur ne repart pas dans la minute",
          gd._recul_synchro({"state": "error", "errors": 5,
                             "ts": _maintenant - 60}, _maintenant) > 200)
    check("recul : passe le delai, la relance est de nouveau permise",
          gd._recul_synchro({"state": "error", "errors": 5,
                             "ts": _maintenant - gd.RECUL_APRES_ERREUR - 1},
                            _maintenant) == 0)
    check("recul : une synchro reussie n est jamais freinee",
          gd._recul_synchro({"state": "done", "errors": 0,
                             "ts": _maintenant}, _maintenant) == 0
          and gd._recul_synchro({"state": "idle"}, _maintenant) == 0)
    check("recul : sans horodatage on ne bloque pas la synchro",
          gd._recul_synchro({"state": "error", "ts": 0}, _maintenant) == 0)

    # Le tour de veille lui-meme : c'est lui qui decide de relancer.
    _lances = []
    _o = (gd.sync_report, gd.status, gd.start_background)
    try:
        gd.sync_report = lambda mode=None: {"a_envoyer": 5, "hors_mode": 0}
        gd.start_background = lambda: _lances.append(1) or True

        gd.status = lambda: {"state": "error", "errors": 5,
                             "ts": time.time() - 60}
        _recul = gd._tour_envoi_auto({})
        check("veille : apres un echec, PAS de synchro complete 60 s plus tard",
              not _lances and _recul > 200, f"lances={len(_lances)} recul={_recul}")

        gd.status = lambda: {"state": "error", "errors": 5,
                             "ts": time.time() - gd.RECUL_APRES_ERREUR - 1}
        _recul = gd._tour_envoi_auto({})
        check("veille : le recul passe, la synchro repart",
              len(_lances) == 1 and _recul == 0,
              f"lances={len(_lances)} recul={_recul}")

        _lances.clear()
        gd.status = lambda: {"state": "running"}
        gd._tour_envoi_auto({})
        gd.sync_report = lambda mode=None: {"a_envoyer": 0}
        gd.status = lambda: {"state": "done", "ts": time.time()}
        gd._tour_envoi_auto({})
        check("veille : ni pendant une synchro, ni quand il n y a rien a envoyer",
              not _lances, str(len(_lances)))
    finally:
        (gd.sync_report, gd.status, gd.start_background) = _o

    # Et le recul doit vraiment allonger l attente de la boucle, sinon il ne
    # sert a rien : la boucle dort `attente` secondes entre deux tours.
    _src = pathlib.Path(__file__).with_name("gdrive_sync.py").read_text(
        encoding="utf-8")
    _deb = _src.find("def start_watcher")
    _boucle = _src[_deb:_src.find("def import_preview", _deb)]
    check("veille : la boucle applique le recul rendu par le tour d envoi",
          "_tour_envoi_auto" in _boucle
          and "attente = max(attente" in _boucle
          and "time.sleep(attente)" in _boucle)
except Exception as _e:                                    # pragma: no cover
    check("recul de la veille : testable", False, repr(_e)[:200])


print()
print("=" * 70)
print(f"{len(OKS)} OK · {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  FAIL " + f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
