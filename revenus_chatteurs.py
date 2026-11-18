"""Ce que la liste des chatteurs affiche EN PLUS des ventes de la periode.

La page « Revenus chatteurs » sait deja lire les ventes (mypuls.fetch_team_stats).
Ce module ajoute ce qui sert a juger un chatteur d'un coup d'oeil : la periode
d'avant (pour le petit % de hausse ou de baisse), les messages et les PPV
envoyes, et la presence.

TOUT EST LU APRES LA PAGE, par /mypuls/chatters/complement.json. La page de
paie ne doit jamais attendre ni tomber parce qu'un chiffre de confort manque :
si un appel echoue ici, la colonne affiche « — », l'erreur est NOMMEE dans la
reponse, et les ventes comme la paie restent exactes.

Aucune ecriture : ce module ne fait que lire MyPuls.
"""
import calendar
import threading
import time
from datetime import date, timedelta

from revenus_dates import transaction_hour

# Les frais des deux plateformes, pour passer du net au brut a l'affichage.
# MEMES VALEURS que OF_FEE / MYM_FEE du tableau de bord (web_upload.py) : la
# bascule Net / Brut doit donner le meme chiffre sur les deux ecrans.
# OnlyFans : MyPuls rend le brut, le net vaut brut x 0,80 (constate vente par
# vente le 18/11/2026). MYM : MyPuls ne rend QUE le net, le brut est calcule.
FRAIS_OF = 0.20
FRAIS_MYM = 0.26

# Les quatre shifts du menu « Shift » de la page. Une vente de la periode
# d'avant est rangee dans son shift ici, pour que le % suive le filtre.
CRENEAUX = ((2, 8), (8, 14), (14, 20), (20, 2))

# Le nom que la page donne aux ventes que MyPuls n'a rattachees a personne
# quand il ne leur en donne aucun (mypuls._team_stats_par_api). Les ventes des
# deux periodes doivent porter CE nom-la : sinon la ligne « non attribue »
# existe dans la liste mais aucune vente ne la retrouve, et elle disparait au
# premier filtre.
SANS_CHATTEUR = "(non attribué)"

_CACHE = {}
_VERROU = threading.Lock()
_TTL_OUVERTE = 600        # periode en cours : les chiffres bougent
_TTL_CLOSE = 3600         # periode terminee : ils ne bougent plus


def periode_precedente(debut: str, fin: str):
    """La periode a laquelle comparer, comme MyPuls le fait pour ses quinzaines.

    Une quinzaine se compare a la quinzaine d'avant (1-15 <-> 16-fin du mois
    precedent), un mois entier au mois d'avant. Toute autre plage se compare
    aux memes N jours juste avant. Sans ces deux cas, le 1-15 novembre (15
    jours) etait compare au 17-31 octobre : un jour de la quinzaine d'avant
    manquait, et tous les % sortaient un peu trop hauts.
    """
    d, f = date.fromisoformat(debut), date.fromisoformat(fin)
    dernier = calendar.monthrange(d.year, d.month)[1]
    meme_mois = (d.year, d.month) == (f.year, f.month)
    if meme_mois and d.day == 1 and f.day == 15:
        veille = d - timedelta(days=1)
        return veille.replace(day=16).isoformat(), veille.isoformat()
    if meme_mois and d.day == 16 and f.day == dernier:
        return d.replace(day=1).isoformat(), d.replace(day=15).isoformat()
    if meme_mois and d.day == 1 and f.day == dernier:
        veille = d - timedelta(days=1)
        return veille.replace(day=1).isoformat(), veille.isoformat()
    jours = (f - d).days + 1
    return (d - timedelta(days=jours)).isoformat(), (d - timedelta(days=1)).isoformat()


def creneau(heure: int) -> int:
    """Le rang du shift qui contient cette heure, ou -1 (heure illisible)."""
    if not isinstance(heure, int) or heure < 0:
        return -1
    for i, (a, b) in enumerate(CRENEAUX):
        if (a <= heure < b) if a < b else (heure >= a or heure < b):
            return i
    return -1


def est_usd(devise) -> bool:
    cs = str(devise or "").upper()
    return "USD" in cs or "$" in cs


def famille(libelle) -> str:
    """'p' (PPV vendu en message), 't' (pourboire), '' (autre).

    UNE SEULE regle pour les deux periodes et pour le navigateur : la page
    recoit cette lettre avec chaque vente (cle « k ») au lieu de reclasser le
    libelle de son cote. Deux classements du meme libelle finissent par
    diverger, et le % comparerait alors deux choses differentes.
    """
    import mypuls
    f = mypuls.categorie_transaction(libelle)
    return "p" if f == "Messages" else "t" if f == "Tips" else ""


def agreger_ventes(transactions) -> list:
    """Les ventes d'une periode, resserrees : une ligne par (chatteur, model,
    shift) -> [chatteur, model, shift, usd, total, ppv, tips, nb_ppv].

    Le detail vente par vente de la periode d'avant ne sert a rien a l'ecran ;
    l'envoyer doublerait le poids de la page. Cette forme garde exactement ce
    qu'il faut pour que le % suive les filtres (plateforme, model, shift).
    Les montants restent dans la devise de la vente : c'est le navigateur qui
    convertit, avec le meme taux et la meme bascule Net / Brut que le reste.
    """
    par = {}
    for t in transactions or []:
        cle = ((str(t.get("chatter") or "").strip() or SANS_CHATTEUR).lower(), str(t.get("creator") or ""),
               creneau(transaction_hour(t.get("date", ""))), 1 if est_usd(t.get("currency")) else 0)
        ligne = par.setdefault(cle, [0.0, 0.0, 0.0, 0])
        try:
            montant = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        ligne[0] += montant
        k = famille(t.get("type"))
        if k == "p":
            ligne[1] += montant
            ligne[3] += 1
        elif k == "t":
            ligne[2] += montant
    return [[c[0], c[1], c[2], c[3], round(v[0], 2), round(v[1], 2), round(v[2], 2), v[3]]
            for c, v in par.items()]


def comptes() -> dict:
    """{pseudo: identifiant} des comptes des creatrices, par l'API d'abord.

    La page tenait cette liste de mypuls.list_creators(), qui lit le site de
    MyPuls avec le cookie. Constate en ligne le 18/11/2026 : elle revenait
    VIDE sur le serveur, sans erreur. Deux effets, aucun message : plus une
    seule photo de model sur la page (pastilles en initiales), et les messages
    ne pouvaient pas etre lus compte par compte. L'API, elle, connait les 13
    comptes : on part d'elle, et le cookie ne fait que completer.
    """
    import mypuls
    liste = {}
    try:
        for c in mypuls.api_creators_cached() or []:
            if isinstance(c, dict) and c.get("pseudo") and c.get("id") is not None:
                liste[str(c["pseudo"])] = c["id"]
    except Exception:
        pass
    try:
        r = mypuls.list_creators()
        if r.get("ok"):
            for nom, cid in (r.get("creators") or {}).items():
                liste.setdefault(str(nom), cid)
    except Exception:
        pass
    return liste


#: Les messages d'un compte sur une periode, gardes a part du complement : ils
#: coutent un appel par compte, et la meme periode d'avant sert a plusieurs
#: ecrans. Periode terminee : 6 h. Periode en cours : 15 minutes.
_CACHE_MESSAGES = {}


def _messages_d_un_compte(debut, fin, compte):
    cle = (str(debut), str(fin), str(compte))
    with _VERROU:
        vu = _CACHE_MESSAGES.get(cle)
        if vu and time.time() - vu[0] < (21600 if str(fin) < date.today().isoformat() else 900):
            return vu[1], ""
    lignes, erreur = _lire_messages_d_un_compte(debut, fin, compte)
    if lignes is not None:
        with _VERROU:
            _CACHE_MESSAGES[cle] = (time.time(), lignes)
    return lignes, erreur


def _lire_messages_d_un_compte(debut, fin, compte):
    import mypuls
    r = mypuls.api_team_messages_stats(debut, fin, creator=str(compte))
    if not r.get("ok"):
        return None, r.get("error") or "messages indisponibles"
    lignes = {}
    for m in r.get("par_chatteur") or []:
        nom = str(m.get("user") or "").strip().lower()
        if not nom:
            continue
        try:
            lignes[nom] = [int(m.get("total_messages") or 0), int(m.get("ppv_messages") or 0)]
        except (TypeError, ValueError):
            continue
    return lignes, ""


def messages(debut: str, fin: str, comptes: dict) -> dict:
    """Messages et PPV envoyes par chatteur, compte par compte.

    Rend {lignes: [[chatteur, model, messages, ppv_envoyes]], par_compte, erreurs, notes}.
    `erreurs` : une panne passagere (la reponse ne sera pas gardee, on retentera).
    `notes` : un constat stable sur ce que MyPuls rend — il s'affiche, et la
    reponse est gardee quand meme. Sans cette difference, un MyPuls qui ignore
    le filtre par compte aurait relance une trentaine d'appels a chaque
    ouverture de la page, pour retomber sur le meme constat.

    POURQUOI COMPTE PAR COMPTE. La page filtre par plateforme (MYM / OF US /
    OF FR). Un total « tous comptes » sous un filtre donnerait un golden ratio
    faux pour tout chatteur qui travaille des deux cotes.

    ET POURQUOI ON LE VERIFIE. Rien ne garantit que MyPuls respecte le filtre
    par compte sur cet appel : s'il l'ignorait, chaque compte rendrait le total
    et la somme serait multipliee par le nombre de comptes, sans une erreur. On
    relit donc le total « tous comptes » et on compare. Si la somme des comptes
    ne le recoupe pas, on rend le total seul (model « * ») et `par_compte` vaut
    False : la page le DIT au lieu d'afficher un chiffre gonfle.
    """
    tout, err = _messages_d_un_compte(debut, fin, "all")
    if tout is None:
        return {"lignes": [], "par_compte": False, "erreurs": ["Messages : " + err], "notes": []}
    noms = [(nom, cid) for nom, cid in (comptes or {}).items() if cid is not None]
    erreurs, notes, lignes, somme = [], [], [], 0
    if noms:
        # UN APPEL A LA FOIS, pas une rafale. Lances a quatre de front, ces
        # appels (un par compte, pour deux periodes) arrivaient par paquets
        # d'une trentaine en quelques secondes, en plus de ceux de la page. Le
        # 18/11/2026, le repartiteur de MyPuls s'est mis a rendre des pages a
        # la place des donnees, des cles ont ete ecartees, et la page de paie
        # est tombee. Ce complement est un confort : il peut prendre dix
        # secondes, il ne doit pas couter la page.
        rendus = []
        for _nom, _cid in noms:
            rendus.append(_messages_d_un_compte(debut, fin, _cid))
            if rendus[-1][0] is None:
                break                     # MyPuls refuse : inutile d'insister sur les comptes suivants
        rendus += [(None, "non lu")] * (len(noms) - len(rendus))
        for (nom, _cid), (par_chatteur, e) in zip(noms, rendus):
            if par_chatteur is None:
                if e != "non lu":             # le premier refus suffit a le dire
                    erreurs.append("Messages de %s : %s" % (nom, e))
                continue
            for chatteur, (nb, ppv) in par_chatteur.items():
                if nb or ppv:
                    lignes.append([chatteur, nom, nb, ppv])
                    somme += nb
    total = sum(v[0] for v in tout.values())
    recoupe = bool(lignes) and not erreurs and abs(somme - total) <= max(5, 0.02 * total)
    if not recoupe:
        if not noms:
            erreurs.append("Messages : liste des comptes indisponible, total tous comptes affiche")
        elif not erreurs:
            notes.append("Messages et PPV envoyés : le détail par compte (%d messages) ne recoupe pas "
                         "le total (%d), le total tous comptes est affiché" % (somme, total))
        lignes = [[c, "*", v[0], v[1]] for c, v in tout.items() if v[0] or v[1]]
    return {"lignes": lignes, "par_compte": recoupe, "erreurs": erreurs, "notes": notes}


def presence(ventes_des_deux_periodes) -> dict:
    """{chatteur: [en_ligne, derniere_activite]} depuis la liste de l'equipe.

    L'API ne nomme ses membres que par un identifiant ; c'est la vente qui
    porte a la fois l'identifiant et le nom du chatteur. Un chatteur sans
    aucune vente sur les deux periodes n'a donc pas de presence ici — il n'est
    de toute facon pas dans la liste.
    """
    import mypuls
    r = mypuls.api_users()
    if not r.get("ok"):
        return {"lignes": {}, "erreurs": ["Présence : " + str(r.get("error") or "indisponible")]}
    par_id = {}
    for m in r.get("membres") or []:
        if isinstance(m, dict) and m.get("user_id") is not None:
            par_id[str(m.get("user_id"))] = [bool(m.get("is_active_now")),
                                              str(m.get("last_activity_at") or "")]
    lignes = {}
    for t in ventes_des_deux_periodes or []:
        nom = str(t.get("chatter") or "").strip().lower()
        uid = t.get("attributed_user_id")
        if nom and uid is not None and nom not in lignes and str(uid) in par_id:
            lignes[nom] = par_id[str(uid)]
    return {"lignes": lignes, "erreurs": []}


def complement(debut: str, fin: str, comptes: dict, ventes: list = None) -> dict:
    """Tout ce que la liste lit apres coup, en une reponse.

    `ventes` : les ventes de la periode affichee, deja lues par la page (elles
    ne servent ici qu'a relier un chatteur a son identifiant d'equipe).
    """
    try:
        avant = periode_precedente(debut, fin)
    except ValueError:
        return {"ok": False, "erreurs": ["Période illisible : %s → %s" % (debut, fin)]}
    # Au-dela de 90 jours (« Annee », « Tout »), pas de comparaison : la
    # periode d'avant serait aussi longue (pour « Tout », elle remonterait a
    # 1913), et MyPuls refuse les periodes de plus de 92 jours. On le DIT ;
    # les colonnes de comparaison affichent « — ».
    try:
        longue = (date.fromisoformat(fin) - date.fromisoformat(debut)).days >= 90
    except ValueError:
        longue = False
    if longue:
        return {"ok": True, "avant": None, "ventes_avant": None, "messages": None, "messages_avant": None,
                "presence": {}, "erreurs": [], "frais": {"of": FRAIS_OF, "mym": FRAIS_MYM},
                "creneaux": [list(c) for c in CRENEAUX],
                "notes": ["Période de plus de 90 jours : pas de comparaison avec la période d’avant, "
                          "ni messages et PPV envoyés (MyPuls ne les rend que par tranches de 92 jours)."]}
    cle = (debut, fin, tuple(sorted((str(k), str(v)) for k, v in (comptes or {}).items())))
    close = fin < date.today().isoformat()
    with _VERROU:
        vu = _CACHE.get(cle)
        if vu and time.time() - vu[0] < (_TTL_CLOSE if close else _TTL_OUVERTE):
            return vu[1]
    import mypuls
    erreurs = []
    rep = {"ok": True, "avant": list(avant), "frais": {"of": FRAIS_OF, "mym": FRAIS_MYM},
           "creneaux": [list(c) for c in CRENEAUX]}

    prec = mypuls.fetch_team_stats(avant[0], avant[1], use_cache=True)
    if prec.get("ok"):
        ventes_avant = prec.get("transactions") or []
        rep["ventes_avant"] = agreger_ventes(ventes_avant)
    else:
        ventes_avant = []
        rep["ventes_avant"] = None
        erreurs.append("Période d'avant : " + str(prec.get("error") or "indisponible"))

    notes = []
    for nom, d0, d1 in (("messages", debut, fin), ("messages_avant", avant[0], avant[1])):
        m = messages(d0, d1, comptes)
        rep[nom] = m["lignes"] if (m["lignes"] or not m["erreurs"]) else None
        rep[nom + "_par_compte"] = m["par_compte"]
        erreurs.extend(m["erreurs"])
        notes.extend(n for n in m["notes"] if n not in notes)
    rep["notes"] = notes

    p = presence(list(ventes or []) + list(ventes_avant))
    rep["presence"] = p["lignes"]
    erreurs.extend(p["erreurs"])

    rep["erreurs"] = erreurs
    # Une reponse amputee n'est pas gardee : la prochaine ouverture retente,
    # au lieu de servir « indisponible » pendant une heure pour un 429 passager.
    if not erreurs:
        with _VERROU:
            _CACHE[cle] = (time.time(), rep)
    return rep


def vider_cache():
    with _VERROU:
        _CACHE.clear()
        _CACHE_MESSAGES.clear()
