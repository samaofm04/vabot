"""tests_sheets_sync.py — banc d'essai de la COURSE lecture/écriture de sheets_sync.

Lancer :  python tests_sheets_sync.py       (depuis le dossier bot/)

Ce banc reproduit le défaut B2 : le poller lit les classeurs Google HORS VERROU
(15 à 40 s observées), puis applique une photo déjà périmée. Une édition faite
sur le site pendant cette fenêtre était ré-écrasée par l'ancienne valeur, et un
compte créé pendant la fenêtre était purement supprimé.

100 % EN MÉMOIRE : aucun accès à data/, aucun accès réseau. Le module
`jailbreak` est remplacé par un faux dans sys.modules AVANT tout import, donc
le vrai jailbreak.json n'est jamais ni lu ni écrit.
"""
import sys, pathlib, json, types, tempfile
from contextlib import contextmanager

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))


# ---------------------------------------------------------------- faux jailbreak
class FauxJB(types.ModuleType):
    """Juste ce que sheets_sync attend d'un module `jailbreak`."""

    def __init__(self, state):
        super().__init__("jailbreak")
        self.state = state
        self.saves = 0

    @contextmanager
    def transaction(self):
        yield

    def _load(self):
        return json.loads(json.dumps(self.state))

    def _save(self, d):
        self.saves += 1
        self.state = json.loads(json.dumps(d))

    tombs = {"vas": {}, "accounts": {}}

    def tombstones(self):
        return json.loads(json.dumps(self.tombs))

    def tomb_clear(self, *a, **k):
        pass


def etat_depart():
    return {"lola": {"vas": [{"name": "Andry", "discord_username": ""},
                             {"name": "Bo7", "discord_username": ""}],
                     "accounts": [
                         {"id": 1, "username": "u1", "va": "Andry", "password": "MDP1",
                          "email": "a@x.io", "two_fa": "2FA1", "notes": "n1"},
                         {"id": 2, "username": "u2", "va": "Andry", "password": "MDP2",
                          "email": "b@x.io", "two_fa": "2FA2", "notes": "n2"}]}}


COLS = ["username", "password", "email", "two_fa", "va", "notes"]


def ligne(a, **over):
    d = {"username": a["username"], "password": a.get("password", ""),
         "email": a.get("email", ""), "two_fa": a.get("two_fa", ""),
         "va": a.get("va", ""), "notes": a.get("notes", ""), "__cols__": COLS}
    d.update(over)
    return d


def onglet_identite(state, identity="lola", **par_user):
    """Photo du Sheet telle qu'elle serait AVANT l'édition concurrente."""
    rows = []
    for a in state[identity]["accounts"]:
        rows.append(ligne(a, **(par_user.get(a["username"]) or {})))
    return {identity: rows}


def comptes(jb, identity="lola"):
    return {a["username"]: a for a in jb.state[identity]["accounts"]}


# On injecte le faux module AVANT d'importer sheets_sync : `import jailbreak`
# à l'intérieur de pull_and_merge résout alors sur sys.modules.
_JB = FauxJB(etat_depart())
sys.modules["jailbreak"] = _JB
import sheets_sync as ss                              # noqa: E402

ss.is_paused = lambda: False
ss.is_configured = lambda: True
ss.gspread_available = lambda: True


def pull(sheet_photo, pendant_la_lecture=None, force_delete=False):
    """Rejoue un cycle du poller.

    `sheet_photo` : ce que la lecture réseau finira par rendre (état du Sheet).
    `pendant_la_lecture` : callback exécuté PENDANT la lecture, c.-à-d. après la
    photo de référence et avant l'application — c'est exactement la fenêtre de
    course décrite par l'audit.
    """
    def _lecture():
        if pendant_la_lecture:
            pendant_la_lecture()
        return sheet_photo
    ss.pull_all = _lecture
    return ss.pull_and_merge(force_delete)


print("=" * 70)
print("1) Comportement NORMAL (aucune écriture concurrente) — non-régression")
print("=" * 70)

_JB.state = etat_depart()
sheet = onglet_identite(_JB.state, u1={"password": "NOUVEAU_DU_SHEET"})
ch, summ = pull(sheet)
check("édition faite dans le Sheet appliquée", comptes(_JB)["u1"]["password"] == "NOUVEAU_DU_SHEET",
      comptes(_JB)["u1"]["password"])

_JB.state = etat_depart()
sheet = {"lola": [ligne(_JB.state["lola"]["accounts"][0])]}      # u2 effacé du Sheet
ch, summ = pull(sheet)
check("suppression faite dans le Sheet appliquée", sorted(comptes(_JB)) == ["u1"], sorted(comptes(_JB)))

_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)
sheet["lola"].append({"username": "u3", "password": "P3", "email": "", "two_fa": "",
                      "va": "Bo7", "notes": "", "__cols__": COLS})
ch, summ = pull(sheet)
check("ajout fait dans le Sheet appliqué", "u3" in comptes(_JB), sorted(comptes(_JB)))

# déplacement de ligne entre onglets VA (comportement FIX6 existant)
_JB.state = etat_depart()
sheet = {"lola": [ligne(a) for a in _JB.state["lola"]["accounts"]],
         "lola andry": [{"username": "u2", "__cols__": ["username"]}],
         "lola bo7": [{"username": "u1", "__cols__": ["username"]}]}
ch, summ = pull(sheet)
check("déplacement d'onglet VA : compte gardé", "u1" in comptes(_JB), sorted(comptes(_JB)))
check("déplacement d'onglet VA : VA réassigné", comptes(_JB).get("u1", {}).get("va") == "bo7",
      comptes(_JB).get("u1", {}).get("va"))
check("déplacement d'onglet VA : mot de passe intact",
      comptes(_JB).get("u1", {}).get("password") == "MDP1")


# doublons dans le Sheet -> un seul compte
_JB.state = etat_depart()
sheet = {"lola": [ligne(_JB.state["lola"]["accounts"][0]),
                  ligne(_JB.state["lola"]["accounts"][1]),
                  {"username": "dup", "password": "P", "email": "", "two_fa": "",
                   "va": "Bo7", "notes": "", "__cols__": COLS},
                  {"username": "DUP", "password": "P", "email": "", "two_fa": "",
                   "va": "Bo7", "notes": "", "__cols__": COLS}]}
ch, summ = pull(sheet)
check("doublons du Sheet -> 1 seul compte",
      sum(1 for u in comptes(_JB) if u.lower() == "dup") == 1, sorted(comptes(_JB)))

# anti-résurrection : compte supprimé sur le site AVANT le cycle (tombstone).
# La protection « photo » passe devant le test des tombstones : ce cas vérifie
# qu'elle ne l'a pas court-circuitée.
import time as _t                                     # noqa: E402
_JB.state = etat_depart()
_JB.tombs = {"vas": {}, "accounts": {"lola|fantome": _t.time()}}
sheet = onglet_identite(_JB.state)
sheet["lola"].append({"username": "fantome", "password": "P", "email": "", "two_fa": "",
                      "va": "Bo7", "notes": "", "__cols__": COLS})
ch, summ = pull(sheet)
check("anti-résurrection (tombstone) tient", "fantome" not in comptes(_JB), sorted(comptes(_JB)))
check("tombstone comptée et remontée", "bloqué" in summ, summ)
_JB.tombs = {"vas": {}, "accounts": {}}


print()
print("=" * 70)
print("2) COURSE : édition sur le site PENDANT la lecture des classeurs (B2)")
print("=" * 70)


def _edit_site(champ, valeur, user="u1"):
    def _f():
        d = _JB._load()
        for a in d["lola"]["accounts"]:
            if a["username"] == user:
                a[champ] = valeur
        _JB._save(d)
    return _f


_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)          # photo du Sheet = ANCIEN mot de passe
ch, summ = pull(sheet, pendant_la_lecture=_edit_site("password", "CORRIGE_SUR_LE_SITE"))
check("mot de passe corrigé pendant la lecture : PAS revenu en arrière",
      comptes(_JB)["u1"]["password"] == "CORRIGE_SUR_LE_SITE", comptes(_JB)["u1"]["password"])

_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)
ch, summ = pull(sheet, pendant_la_lecture=_edit_site("two_fa", "2FA_CORRIGE"))
check("secret 2FA corrigé pendant la lecture : PAS revenu en arrière",
      comptes(_JB)["u1"]["two_fa"] == "2FA_CORRIGE", comptes(_JB)["u1"]["two_fa"])

_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)
ch, summ = pull(sheet, pendant_la_lecture=_edit_site("email", "corrige@x.io"))
check("email corrigé pendant la lecture : PAS revenu en arrière",
      comptes(_JB)["u1"]["email"] == "corrige@x.io", comptes(_JB)["u1"]["email"])

# le conflit doit être REMONTÉ, pas écarté en silence
check("conflit compté et remonté dans le résumé", "ignorée" in summ, summ)


def _cree_compte():
    d = _JB._load()
    d["lola"]["accounts"].append({"id": 99, "username": "tout_neuf", "va": "Bo7",
                                  "password": "P", "email": "", "two_fa": "", "notes": ""})
    _JB._save(d)


_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)           # le Sheet ne connaît pas 'tout_neuf'
ch, summ = pull(sheet, pendant_la_lecture=_cree_compte)
check("compte CRÉÉ pendant la lecture : pas supprimé", "tout_neuf" in comptes(_JB),
      sorted(comptes(_JB)))
check("compte protégé compté et remonté", "protégé" in summ, summ)

# le compte créé pendant la fenêtre ne doit pas non plus voir ses champs écrasés
_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)
sheet["lola"].append({"username": "tout_neuf", "password": "VIEUX", "email": "", "two_fa": "",
                      "va": "Andry", "notes": "", "__cols__": COLS})
ch, summ = pull(sheet, pendant_la_lecture=_cree_compte)
check("compte créé pendant la lecture : ses champs ne sont pas écrasés",
      comptes(_JB).get("tout_neuf", {}).get("password") == "P",
      comptes(_JB).get("tout_neuf", {}).get("password"))

# VA réassigné sur le site pendant la lecture : le déplacement lu (périmé) perd
_JB.state = etat_depart()
sheet = {"lola": [ligne(a) for a in _JB.state["lola"]["accounts"]],
         "lola andry": [{"username": "u2", "__cols__": ["username"]}],
         "lola bo7": [{"username": "u1", "__cols__": ["username"]}]}
ch, summ = pull(sheet, pendant_la_lecture=_edit_site("va", "Andry2"))
check("VA changé sur le site pendant la lecture : le site gagne",
      comptes(_JB).get("u1", {}).get("va") == "Andry2", comptes(_JB).get("u1", {}).get("va"))
check("VA changé sur le site pendant la lecture : compte pas supprimé", "u1" in comptes(_JB))

# compte RENOMMÉ sur le site pendant la lecture : la ligne périmée du Sheet
# porte l'ancien pseudo. La ré-importer fabriquerait un doublon (update_account
# ne pose pas de tombstone, contrairement à remove_account).
_JB.state = etat_depart()
sheet = onglet_identite(_JB.state)


def _renomme():
    d = _JB._load()
    d["lola"]["accounts"][0]["username"] = "u1_renomme"
    _JB._save(d)


ch, summ = pull(sheet, pendant_la_lecture=_renomme)
check("compte renommé pendant la lecture : pas de doublon à l'ancien pseudo",
      sorted(comptes(_JB)) == ["u1_renomme", "u2"], sorted(comptes(_JB)))
check("ligne périmée non ré-ajoutée : comptée et remontée", "non ré-ajoutée" in summ, summ)

# une suppression VOULUE dans le Sheet reste appliquée même s'il y a eu une
# édition concurrente sur un AUTRE compte
_JB.state = etat_depart()
sheet = {"lola": [ligne(_JB.state["lola"]["accounts"][0])]}      # u2 effacé du Sheet
ch, summ = pull(sheet, pendant_la_lecture=_edit_site("password", "X"))
check("suppression du Sheet toujours appliquée malgré une édition concurrente",
      sorted(comptes(_JB)) == ["u1"], sorted(comptes(_JB)))

# photo indisponible -> on n'applique RIEN, et on le dit
_JB.state = etat_depart()
_orig_load = _JB._load


def _load_ko():
    raise RuntimeError("fichier illisible")


_JB._load = _load_ko
ch, summ = ss.pull_and_merge()
_JB._load = _orig_load
check("état local illisible : pull annulé, rien appliqué", ch is False and "annulé" in summ, summ)


print()
print("=" * 70)
print("3) restore_from_single_sheet : lecture réseau puis application sous verrou")
print("=" * 70)


class FauxWS:
    def __init__(self, titre, values, avant_lecture=None):
        self.title = titre
        self._values = values
        self._avant = avant_lecture

    def get_all_values(self):
        if self._avant:            # simule le temps réseau : le site travaille
            self._avant()
            self._avant = None
        return self._values


class FauxBook:
    def __init__(self, ws):
        self._ws = ws

    def worksheets(self):
        return self._ws


_JB.state = etat_depart()


def _cree_pendant_restore():
    d = _JB._load()
    d["lola"]["accounts"].append({"id": 77, "username": "pendant_restore", "va": "Bo7",
                                  "password": "P77", "email": "", "two_fa": "", "notes": ""})
    _JB._save(d)


_tmp = pathlib.Path(tempfile.mkdtemp()) / "sa.json"
_tmp.write_text('{"client_email": "x@y.z"}', encoding="utf-8")
_orig_sa, _orig_cfg, _orig_client = ss.SA_FILE, ss.load_config, ss._client
ss.SA_FILE = _tmp
ss.load_config = lambda: {"sheets": {"lola": "SID"}}
ss._client = lambda: types.SimpleNamespace(open_by_key=lambda k: FauxBook([
    FauxWS("lola", [["username", "password", "email", "two_fa", "va", "notes"],
                    ["u1", "MDP1", "a@x.io", "2FA1", "Andry", "n1"],
                    ["u9", "MDP9", "c@x.io", "2FA9", "Bo7", "n9"]],
           avant_lecture=_cree_pendant_restore)]))
ok, msg = ss.restore_from_single_sheet()
_noms = sorted(comptes(_JB))
check("restore : compte manquant réimporté", ok and "u9" in _noms, msg)
check("restore : compte créé pendant la lecture PAS effacé", "pendant_restore" in _noms, _noms)
check("restore : comptes existants conservés", {"u1", "u2"} <= set(_noms), _noms)
ss.SA_FILE, ss.load_config, ss._client = _orig_sa, _orig_cfg, _orig_client

print()
print("=" * 70)
print("4) DOUBLONS de pseudo : la photo et le merge doivent viser la MÊME ligne")
print("=" * 70)


def etat_doublon():
    """Deux comptes locaux du MÊME pseudo — cas documenté (c'est la raison
    d'être de `_dedup_accounts`). La photo indexait « dernier gagnant » et le
    merge « premier gagnant » : la comparaison portait sur deux lignes
    différentes, donc disait « modifié sur le site » à chaque cycle et la
    ligne éditée dans le Sheet n'était plus JAMAIS appliquée."""
    st = etat_depart()
    st["lola"]["accounts"].append(
        {"id": 3, "username": "u1", "va": "Andry", "password": "MDP1_BIS",
         "email": "a2@x.io", "two_fa": "2FA1B", "notes": "n1b"})
    return st


_JB.state = etat_doublon()
sheet = {"lola": [ligne(_JB.state["lola"]["accounts"][0], password="EDITE_DANS_LE_SHEET"),
                  ligne(_JB.state["lola"]["accounts"][1])]}
res = pull(sheet)
_mdp = [a["password"] for a in _JB.state["lola"]["accounts"]]
check("doublon de pseudo : l'édition du Sheet est appliquée",
      _mdp[0] == "EDITE_DANS_LE_SHEET", _mdp)
check("doublon de pseudo : l'autre ligne n'est pas touchée",
      _mdp[1:] == ["MDP2", "MDP1_BIS"], _mdp)
check("doublon de pseudo : aucun conflit fantôme",
      res.compteurs.get("conflits", 0) == 0, res[1])
check("doublon de pseudo : le pull n'est plus bloqué en permanence", res[0] is True, res[1])

# ... et la protection anti-écrasement doit TENIR malgré le doublon
_JB.state = etat_doublon()
sheet = onglet_identite(_JB.state)
res = pull(sheet, pendant_la_lecture=_edit_site("password", "CORRIGE_SUR_LE_SITE"))
_mdp = [a["password"] for a in _JB.state["lola"]["accounts"]]
check("doublon + édition concurrente : le site gagne encore",
      _mdp[0] == "CORRIGE_SUR_LE_SITE", _mdp)
check("doublon + édition concurrente : conflit toujours remonté",
      res.compteurs.get("conflits", 0) >= 1, res[1])


print()
print("=" * 70)
print("5) Contrat de retour : un pull sans écriture n'est pas un pull sans histoire")
print("=" * 70)


def etat_gros(n=25):
    return {"lola": {"vas": [{"name": "Andry", "discord_username": ""}],
                     "accounts": [{"id": i, "username": f"a{i}", "va": "Andry",
                                   "password": f"P{i}", "email": "", "two_fa": "",
                                   "notes": ""} for i in range(n)]}}


# a) cycle vraiment calme
_JB.state = etat_depart()
res = pull(onglet_identite(_JB.state))
_ch, _summ = res                       # le couple historique doit survivre
check("résultat toujours un couple (changed, summary)",
      len(res) == 2 and _ch is False and isinstance(_summ, str), repr(res))
check("cycle calme : motif 'rien'", res.outcome == ss.PULL_RIEN, res.outcome)
check("cycle calme : écran 'rien de nouveau'",
      "Rien de nouveau" in ss.pull_message(res), ss.pull_message(res))

# b) valeur du Sheet ignorée (conflit)
_JB.state = etat_depart()
res = pull(onglet_identite(_JB.state),
           pendant_la_lecture=_edit_site("password", "CORRIGE_SUR_LE_SITE"))
_m = ss.pull_message(res)
check("conflit : rien d'écrit mais motif 'signale'",
      res[0] is False and res.outcome == ss.PULL_SIGNALE, f"{res[0]} {res.outcome}")
check("conflit : compteur porté par le résultat", res.compteurs.get("conflits") == 1,
      res.compteurs)
check("conflit : l'écran ne dit PAS 'rien de nouveau'", "Rien de nouveau" not in _m, _m)
check("conflit : l'écran dit ce qui a été ignoré", "ignorée" in _m, _m)

# c) compte protégé de la suppression
_JB.state = etat_depart()
res = pull(onglet_identite(_JB.state), pendant_la_lecture=_cree_compte)
_m = ss.pull_message(res)
check("compte protégé : motif 'signale'", res.outcome == ss.PULL_SIGNALE, res.outcome)
check("compte protégé : compteur porté", res.compteurs.get("proteges") == 1, res.compteurs)
check("compte protégé : remonté à l'écran", "protégé" in _m and "Rien de nouveau" not in _m, _m)

# d) ligne périmée non ré-ajoutée (compte renommé pendant la lecture)
_JB.state = etat_depart()
res = pull(onglet_identite(_JB.state), pendant_la_lecture=_renomme)
_m = ss.pull_message(res)
check("ligne périmée : compteur porté", res.compteurs.get("disparus") == 1, res.compteurs)
check("ligne périmée : remontée à l'écran", "non ré-ajoutée" in _m, _m)

# e) suppressions retenues par le garde anti-effacement, sans aucune écriture
_JB.state = etat_gros()
res = pull({"lola": [ligne(_JB.state["lola"]["accounts"][0])]})
_m = ss.pull_message(res)
check("anti-effacement : aucune suppression appliquée",
      len(_JB.state["lola"]["accounts"]) == 25, len(_JB.state["lola"]["accounts"]))
check("anti-effacement : motif 'signale'", res.outcome == ss.PULL_SIGNALE, res.outcome)
check("anti-effacement : compteur porté", res.compteurs.get("retenues") == 24, res.compteurs)
check("anti-effacement : remonté à l'écran", "RETENUES" in _m, _m)

# f) PULL ANNULÉ (état local illisible) — le pire cas : il s'annonçait « rien de nouveau »
_JB.state = etat_depart()
_orig_load = _JB._load
_JB._load = _load_ko
res = ss.pull_and_merge()
_JB._load = _orig_load
_m = ss.pull_message(res)
check("pull annulé : motif dédié", res.outcome == ss.PULL_ANNULE, res.outcome)
check("pull annulé : l'écran le DIT", "ANNULÉ" in _m, _m)
check("pull annulé : jamais confondu avec un pull sans nouveauté",
      "Rien de nouveau" not in _m, _m)

# g) Sheet illisible
_JB.state = etat_depart()
ss.pull_all = lambda: None
res = ss.pull_and_merge()
check("Sheet illisible : motif dédié", res.outcome == ss.PULL_INDISPO, res.outcome)
check("Sheet illisible : l'écran le DIT", "ILLISIBLE" in ss.pull_message(res),
      ss.pull_message(res))

# h) sync en pause
ss.is_paused = lambda: True
res = ss.pull_and_merge()
ss.is_paused = lambda: False
check("pause : motif dédié", res.outcome == ss.PULL_PAUSE, res.outcome)
check("pause : l'écran le DIT", "PAUSE" in ss.pull_message(res), ss.pull_message(res))

# i) un vrai changement reste un vrai changement
_JB.state = etat_depart()
res = pull(onglet_identite(_JB.state, u1={"password": "NOUVEAU"}))
check("changement réel : motif 'applique'", res.outcome == ss.PULL_APPLIQUE, res.outcome)
check("changement réel : écran d'import", "Importé" in ss.pull_message(res),
      ss.pull_message(res))


print()
print("=" * 70)
print("6) Journal du poller : ce qui est retenu doit laisser une trace")
print("=" * 70)

import io, contextlib                                 # noqa: E402

try:
    from cogs.sheetssync import SheetsSync as _Cog    # noqa: E402

    class _FauxCog:
        """Juste ce que `_journal` lit de `self` — ni bot, ni boucle discord."""
        _RELOG_S = _Cog._RELOG_S

        def __init__(self):
            self._dernier_log = ("", 0.0)

    def _journal(res, cog=None, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _Cog._journal(cog or _FauxCog(), res, **kw)
        return buf.getvalue()

    _JB.state = etat_depart()
    _calme = pull(onglet_identite(_JB.state))
    check("journal : cycle calme = aucune ligne", _journal(_calme) == "", _journal(_calme))

    _JB.state = etat_depart()
    _conflit = pull(onglet_identite(_JB.state),
                    pendant_la_lecture=_edit_site("password", "CORRIGE_SUR_LE_SITE"))
    _l = _journal(_conflit)
    check("journal : conflit écrit au journal", "ignorée" in _l, _l.strip() or "(rien)")

    _JB.state = etat_depart()
    _prot = pull(onglet_identite(_JB.state), pendant_la_lecture=_cree_compte)
    check("journal : compte protégé écrit au journal", "protégé" in _journal(_prot),
          _journal(_prot).strip() or "(rien)")

    _JB._load = _load_ko
    _annule = ss.pull_and_merge()
    _JB._load = _orig_load
    _l = _journal(_annule)
    check("journal : pull annulé écrit au journal", "annulé" in _l and "annule" in _l,
          _l.strip() or "(rien)")

    # Anti-noyade : le poller tourne toutes les 2 min. Un état qui DURE ne doit
    # pas écrire 720 lignes/jour (un journal noyé cache autant que le silence),
    # mais un pull demandé À LA MAIN garde toujours sa ligne.
    _c = _FauxCog()
    _un = _journal(_annule, cog=_c)
    _deux = _journal(_annule, cog=_c)
    check("journal : état qui dure = pas de répétition immédiate",
          _un != "" and _deux == "", repr(_deux))
    check("journal : pull manuel toujours écrit",
          _journal(_annule, cog=_c, toujours=True) != "")
except Exception as _e:                                # pragma: no cover
    check("journal du poller : testable", False, repr(_e)[:120])


print()
print("=" * 70)
print(f"{len(OKS)} OK · {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  FAIL " + f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
