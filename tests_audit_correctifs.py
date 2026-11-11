"""Correctifs issus de l'audit général du 11/11/2026 — un bloc par bug.

  B-163  safe_json : un fichier que le processus n'a pas le DROIT de lire n'est
         ni pris pour abîmé (repli sur .prev), ni écrasé ;
  B-076  numgen.alerter_staff : une panne qui dure est redite une fois par
         jour, avec le nombre de refus ;
  B-069  infloww_liens.groupes_equipe : après une lecture ratée de
         GetMySocial, pas de nouvel appel avant dix minutes ;
  B-099  cogs/outils.numeroter : les mêmes salons « sans fiche » ne sont plus
         réécrits au journal toutes les dix minutes ;
  B-128  aucun module ne lève plus de SyntaxWarning à la compilation.

Rien de réel n'est touché : dossiers temporaires, GetMySocial et Discord
doublés, toute connexion réseau fait échouer la suite. Chaque bloc est
indépendant : s'il plante, il le dit en une ligne et les suivants tournent
quand même (lancée sur le code d'avant les correctifs, la suite échoue dans
chacun des quatre premiers blocs).
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import pathlib
import socket
import sys
import tempfile
import time
import types
import warnings

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []
SORTIES = []
_VRAIS_SOCKET = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)


def _reseau_interdit(*a, **k):
    SORTIES.append(str(a[1:2])[:80])
    raise OSError("réseau interdit dans tests_audit_correctifs")


socket.socket.connect = socket.socket.connect_ex = _reseau_interdit
socket.getaddrinfo = _reseau_interdit


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


@contextlib.contextmanager
def journal():
    """Ce que le code écrit au journal (print) pendant le bloc."""
    tampon, vrai = io.StringIO(), sys.stdout
    sys.stdout = tampon
    try:
        yield tampon
    finally:
        sys.stdout = vrai


def bloc(titre, fonction):
    """Un bloc qui plante le dit (une ligne FAIL) au lieu d'arrêter la suite."""
    print(titre)
    try:
        fonction()
    except Exception as e:                                   # noqa: BLE001
        check(f"{titre.split('.')[0]} : le bloc va jusqu'au bout", False, f"{type(e).__name__}: {e}")


TMP = pathlib.Path(tempfile.mkdtemp(prefix="audit_correctifs_"))


# ══ B-163 : safe_json et les fichiers sans droit de lecture ═════════════════
def bloc_b163():
    import safe_json
    p = TMP / "cle.json"
    safe_json.write(p, {"cle": "ancienne"})
    safe_json.write(p, {"cle": "bonne"})                 # .prev = l'ancienne version
    prev = p.with_suffix(".json.prev")
    check("mise en place : le fichier et sa copie .prev existent",
          json.loads(p.read_text())["cle"] == "bonne" and json.loads(prev.read_text())["cle"] == "ancienne")
    os.chmod(p, 0)
    try:
        if os.access(p, os.R_OK):
            # root lit tout : le cas ne peut pas se produire, donc pas se tester
            check("(lancé en root : un fichier sans droit reste lisible, cas sans objet)", True)
        else:
            getattr(safe_json, "_INTERDITS_DITS", {}).clear()
            with journal() as j:
                lu = [safe_json.load(p, {"defaut": 1}) for _ in range(3)]
            check("lecture : la valeur par défaut, pas la vieille copie .prev",
                  lu == [{"defaut": 1}] * 3, lu)
            check("… dite au journal, une seule fois (pas à chaque lecture), avec le mot ALERTE et « chown »",
                  j.getvalue().count("ALERTE") == 1 and "chown" in j.getvalue()
                  and "tentative .prev" not in j.getvalue(), j.getvalue()[:300])
            with journal() as j:
                ecrit = safe_json.write(p, {"cle": "neuve"})
            check("écriture par-dessus : REFUSÉE (False), dite au journal",
                  ecrit is False and "REFUSÉE" in j.getvalue(), (ecrit, j.getvalue()[:200]))
            check("… aucun fichier .tmp laissé", not p.with_suffix(".json.tmp").exists())
            os.chmod(p, 0o644)
            check("droits rendus : le contenu d'origine est intact (ni .prev remis, ni contenu neuf)",
                  json.loads(p.read_text()) == {"cle": "bonne"}, p.read_text()[:80])
            check("… et la lecture puis l'écriture remarchent",
                  safe_json.load(p, {}) == {"cle": "bonne"} and safe_json.write(p, {"cle": "suivante"}) is True
                  and safe_json.load(p, {}) == {"cle": "suivante"})
    finally:
        os.chmod(p, 0o644)
    # le filet d'origine reste : un fichier ABÎMÉ (pas interdit) repart de .prev
    q = TMP / "abime.json"
    safe_json.write(q, {"n": 1})
    safe_json.write(q, {"n": 2})
    with open(q, "w", encoding="utf-8") as f:
        f.write("{tronqué")
    with journal() as j:
        lu = safe_json.load(q, {})
    check("un fichier abîmé (JSON tronqué) est toujours restauré depuis .prev", lu == {"n": 1},
          (lu, j.getvalue()[:160]))
    with journal() as j:
        absent = safe_json.load(TMP / "absent.json", {"d": 1})
    check("un fichier absent rend toujours la valeur par défaut, sans alerte",
          absent == {"d": 1} and "ALERTE" not in j.getvalue(), j.getvalue()[:120])


# ══ B-076 : alerte au staff redite une fois par jour ════════════════════════
def bloc_b076():
    import numgen
    sav = (numgen.ALERTES_FICHIER, numgen._poster_alerte, numgen._en_production)
    envois, regle = [], {"ok": True}
    fichier = TMP / "numgen_alertes.json"
    numgen.ALERTES_FICHIER = fichier
    numgen._poster_alerte = lambda texte: (envois.append(texte) or (True, "")) if regle["ok"] else (False, "HTTP 500")
    numgen._en_production = lambda: True
    texte = "⚠️ **HeroSMS sans crédit** : à recharger."

    def lire():
        return json.loads(fichier.read_text(encoding="utf-8"))

    def poser(d):
        with open(fichier, "w", encoding="utf-8") as f:
            json.dump(d, f)

    def fiche(cle="credit:herosms"):
        return lire().get(cle) or {}

    def vieillir(secondes, cle="credit:herosms"):
        d = lire()
        for k in ("le", "rappel"):
            if k in d[cle]:
                d[cle][k] -= secondes
        poser(d)

    try:
        with journal():
            r1 = numgen.alerter_staff("credit:herosms", texte)
            r2 = numgen.alerter_staff("credit:herosms", texte)
            r3 = numgen.alerter_staff("credit:herosms", texte)
        check("premier refus : le message part ; les deux suivants, le même jour, ne redisent rien",
              (r1, r2, r3) == ("envoye", "deja", "deja") and envois == [texte], (r1, r2, r3, envois))
        check("… mais les refus sont comptés", fiche().get("refus") == 2, fiche())
        vieillir(25 * 3600)
        with journal():
            r4 = numgen.alerter_staff("credit:herosms", texte)
        check("plus de 24 h après : la panne est REDITE, avec « Rappel », le nombre de refus et le texte d'origine",
              r4 == "envoye" and len(envois) == 2 and "Rappel" in envois[-1] and "3 refus" in envois[-1]
              and texte in envois[-1] and "depuis le" in envois[-1], (r4, envois[-1]))
        check("… le compteur repart de zéro et l'heure du rappel est notée",
              fiche().get("refus") == 0 and fiche().get("rappels") == 1 and fiche().get("rappel"), fiche())
        with journal():
            r5 = numgen.alerter_staff("credit:herosms", texte)
        check("juste après le rappel : rien de plus avant le lendemain", r5 == "deja" and len(envois) == 2,
              (r5, len(envois)))
        vieillir(25 * 3600)
        regle["ok"] = False
        with journal() as j:
            r6 = numgen.alerter_staff("credit:herosms", texte)
        check("rappel refusé par Discord : « deja » (le staff a déjà été prévenu), dit au journal, compteur gardé",
              r6 == "deja" and len(envois) == 2 and "NON envoyé" in j.getvalue() and fiche().get("refus") == 2,
              (r6, fiche(), j.getvalue()[:160]))
        regle["ok"] = True
        with journal():
            r7 = numgen.alerter_staff("credit:herosms", texte)
        check("… et il repart au refus suivant", r7 == "envoye" and len(envois) == 3 and "3 refus" in envois[-1],
              (r7, envois[-1]))
        # une fiche d'avant le correctif : pas de compteur, donc pas de nombre inventé
        poser({"outlook:vide": {"le": int(time.time()) - 8 * 86400, "texte": "x"}})
        with journal():
            r8 = numgen.alerter_staff("outlook:vide", "⚠️ **Coffre Outlook vide**")
        check("fiche ancienne (sans compteur) : rappel « depuis … (8 jours) », sans nombre de refus inventé",
              r8 == "envoye" and "8 jours" in envois[-1] and "refus depuis" not in envois[-1]
              and "encore refusés" in envois[-1], (r8, envois[-1]))
        with journal():
            fin = numgen.fin_alerte("outlook:vide")
            r9 = numgen.alerter_staff("outlook:vide", "⚠️ **Coffre Outlook vide**")
        check("service revenu puis nouvelle panne : un premier message, pas un rappel",
              fin and r9 == "envoye" and "Rappel" not in envois[-1], (fin, r9, envois[-1]))
        # hors production : rien ne part, rien n'est écrit
        numgen._en_production = lambda: False
        vieillir(30 * 3600, "outlook:vide")              # un rappel serait dû : il ne doit pas partir
        avant, n = fichier.read_bytes(), len(envois)
        with journal():
            ra, rb = numgen.alerter_staff("outlook:vide", "x"), numgen.alerter_staff("credit:neuf", "y")
        check("hors production : « deja » / « hors production », aucun envoi, fichier inchangé",
              (ra, rb) == ("deja", "hors production") and len(envois) == n and fichier.read_bytes() == avant,
              (ra, rb))
    finally:
        numgen.ALERTES_FICHIER, numgen._poster_alerte, numgen._en_production = sav


# ══ B-069 : groupes GetMySocial, pas d'appel en boucle après un échec ════════
def bloc_b069():
    import gms
    import infloww_liens as il
    sav = (gms.list_team_groups, il.EQUIPE_GMS, dict(il._GROUPES))
    appels, reponse = [], {"r": {"error": "JSON invalide"}}
    attente = getattr(il, "GROUPES_ECHEC_S", 600)

    def faux_groupes(equipe):
        appels.append(equipe)
        if isinstance(reponse["r"], Exception):
            raise reponse["r"]
        return reponse["r"]

    try:
        gms.list_team_groups = faux_groupes
        il.EQUIPE_GMS = "tm_test"
        il._GROUPES.clear()
        il._GROUPES.update(t=0.0, par_id={}, echec=0.0)
        with journal() as j:
            lus = [il.groupes_equipe() for _ in range(40)]       # 40 lignes d'un tableau
        check("lecture ratée : UN appel pour 40 lignes du tableau (avant : 40), dit une fois",
              len(appels) == 1 and lus == [{}] * 40 and j.getvalue().count("illisibles") == 1
              and "nouvel essai dans 10 min" in j.getvalue(), (len(appels), j.getvalue()[:200]))
        il._GROUPES["echec"] = time.time() - attente - 1
        with journal():
            il.groupes_equipe()
            il.groupes_equipe()
        check("dix minutes plus tard : un nouvel essai, un seul", len(appels) == 2, len(appels))
        il._GROUPES["echec"] = 0.0
        reponse["r"] = RuntimeError("connexion coupée")
        with journal() as j:
            il.groupes_equipe()
            il.groupes_equipe()
        check("une exception compte comme un échec : un appel, pas deux ; rien ne remonte",
              len(appels) == 3 and "RuntimeError" in j.getvalue(), (len(appels), j.getvalue()[:160]))
        il._GROUPES["echec"] = 0.0
        reponse["r"] = {"groups": [{"id": "grp_a", "name": "Manager A"}, {"id": "ungrouped", "name": "x"}]}
        with journal():
            g1, g2 = il.groupes_equipe(), il.groupes_equipe()
        check("lecture réussie : gardée une heure (un appel), l'échec est oublié",
              len(appels) == 4 and g1 == g2 == {"a": (0, "Manager A")} and il._GROUPES["echec"] == 0.0,
              (len(appels), g1))
        il._GROUPES["t"] = time.time() - il.GROUPES_FRAIS_S - 1
        reponse["r"] = {"error": "HTTP 429"}
        with journal():
            g3, g4 = il.groupes_equipe(), il.groupes_equipe()
        check("une heure après, GetMySocial en panne : la dernière lecture connue est rendue, un seul appel",
              len(appels) == 5 and g3 == g4 == {"a": (0, "Manager A")}, (len(appels), g3))
    finally:
        gms.list_team_groups, il.EQUIPE_GMS = sav[0], sav[1]
        il._GROUPES.clear()
        il._GROUPES.update(sav[2])


# ══ B-099 : numéros des VA, le même « sans fiche » n'est plus redit ═════════
class Salon:
    def __init__(self, i, nom, pos):
        self.id, self.name, self.position, self.renommes = i, nom, pos, []

    async def edit(self, name=None, reason=None):
        self.renommes.append(name)
        self.name = name


def bloc_b099():
    import cogs.outils as co
    import cogs.welcome as cw
    import liens_fr
    sav = (cw.load_users, cw.models_du_serveur, liens_fr.numero_va, asyncio.sleep)

    async def sans_attente(_s):
        return None

    try:
        cw.load_users = lambda: {"11": {"channel_id": 1}, "12": {"channel_id": 3}}
        cw.models_du_serveur = lambda g: ["amelia"]
        liens_fr.numero_va = lambda uid, model: {"11": 3, "12": 7}[str(uid)]
        asyncio.sleep = sans_attente
        bob, hycham = Salon(1, "🟢-3-va-bob", 0), Salon(2, "🔴-va-hycham", 1)
        cat = types.SimpleNamespace(name="amelia", text_channels=[bob, hycham])
        guilde = types.SimpleNamespace(id=777, categories=[cat])
        cog = types.SimpleNamespace()                  # numeroter ne lit que son propre registre

        def passe():
            with journal() as j:
                b = asyncio.run(co.Outils.numeroter(cog, guilde))
            return b, j.getvalue().count("[outils] numeros des VA")

        (b1, n1), (b2, n2), (b3, n3) = passe(), passe(), passe()
        check("un salon sans fiche : compté à chaque passage, dit au journal UNE fois sur trois passages",
              b1["sans_va"] == b3["sans_va"] == ["🔴-va-hycham"] and (n1, n2, n3) == (1, 0, 0), (b1, n1, n2, n3))
        cat.text_channels.append(Salon(4, "🔴-va-zoe", 2))
        _b, n4 = passe()
        _b, n5 = passe()
        check("la liste change (un 2e salon sans fiche) : redite une fois", (n4, n5) == (1, 0), (n4, n5))
        cog._sans_fiche_dits[777] = (cog._sans_fiche_dits[777][0], time.time() - 90000)
        _b, n6 = passe()
        _b, n6b = passe()
        check("un jour plus tard, toujours pareil : redite une fois (le défaut ne disparaît pas du journal)",
              (n6, n6b) == (1, 0), (n6, n6b))
        cat.text_channels.append(Salon(3, "🟢-va-carl", 3))      # fiche 12, numéro 7 : à renommer
        b7, n7 = passe()
        check("un renommage se dit toujours",
              b7["renommes"] == 1 and n7 == 1 and cat.text_channels[-1].name == "🟢-7-va-carl",
              (b7, cat.text_channels[-1].name))
        cat.text_channels[:] = [bob, cat.text_channels[-1]]
        b8, n8 = passe()
        check("plus aucun salon sans fiche : rien au journal, registre remis à zéro",
              b8["sans_va"] == [] and n8 == 0 and 777 not in cog._sans_fiche_dits, (b8, n8))
        cat.text_channels.append(hycham)
        _b, n9 = passe()
        check("… et s'il revient, il est redit tout de suite", n9 == 1, n9)
    finally:
        cw.load_users, cw.models_du_serveur, liens_fr.numero_va, asyncio.sleep = sav


# ══ B-128 : plus aucun avertissement de syntaxe ═════════════════════════════
def bloc_b128():
    fautifs = []
    for f in sorted(list(BOT.glob("*.py")) + list((BOT / "cogs").glob("*.py"))):
        if f.name.startswith("tests_"):
            continue
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                compile(f.read_text(encoding="utf-8"), str(f), "exec")
            except SyntaxError as e:
                fautifs.append(f"{f.name} : SyntaxError {e}")
        fautifs += [f"{f.name}:{x.lineno} {x.message}" for x in w if issubclass(x.category, SyntaxWarning)]
    check("antislashs inconnus de Python (« \\/ », « \\s »…) : aucun dans une chaîne non brute", not fautifs,
          fautifs[:6])


bloc("B-163. safe_json : fichier sans droit de lecture", bloc_b163)
bloc("B-076. numgen : alerte au staff redite", bloc_b076)
bloc("B-069. infloww_liens : groupes GetMySocial après un échec", bloc_b069)
bloc("B-099. cogs/outils : salons sans fiche au journal", bloc_b099)
bloc("B-128. Aucun module ne lève d'avertissement de syntaxe", bloc_b128)

socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = _VRAIS_SOCKET
check("aucune connexion réseau tentée pendant la suite", not SORTIES, SORTIES[:3])
print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
