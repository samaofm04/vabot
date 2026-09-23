"""Le podium de la semaine : un classement des subs, posté chaque lundi.

La semaine court du LUNDI au DIMANCHE, et le message part le lundi suivant :
il récapitule la semaine qui vient de finir, jamais celle en cours.

CE QU'ON COMPTE. « Subs » veut dire ici les clics venus des États-Unis sur les
liens GetMySocial — la mesure que le tableau de bord appelle « Clics US ».

LA LISTE DES LIENS EST LUE EN DIRECT, jamais dans le cache du site. Le cache
`gmsdash_links.json` avait treize liens quand GetMySocial en portait
trente-trois : neuf personnes manquaient, dont celle qui avait fait le plus de
subs de la semaine. Un podium bâti là-dessus payait la mauvaise personne. Si
GetMySocial ne répond pas, on se rabat sur le cache — et le message le DIT.

UNE PERSONNE, PLUSIEURS LIENS. Certains en ont quatre. Leurs clics sont
additionnés en un seul appel : GetMySocial calcule alors le détail par pays
sur l'ensemble, ce qu'une somme de relevés séparés ne sait pas faire (chaque
lien ne rend que son top ~10 de pays, et la traîne se perdait).

LE LIEN « SPAM » COMPTE À PART, comme une personne de plus — c'est la règle
voulue : il porte son propre trafic, il a son propre numéro.

LES NUMÉROS NE BOUGENT JAMAIS. Le classement est anonyme : personne ne doit
lire le prénom d'un autre à côté d'un chiffre. Mais un numéro attribué par le
rang ne voudrait rien dire — on ne se reconnaîtrait pas d'une semaine sur
l'autre. La table personne → numéro est donc gardée dans un fichier, et elle
reprend les anciens numéros de GetMySocial (VA 1 = BO7, VA 2 = Safidy…) pour
que rien ne change pour ceux qui étaient déjà là.

UN RELEVÉ RATÉ N'EST PAS UN ZÉRO. Si GetMySocial ne répond pas pour quelqu'un,
il est mis de côté et le message le dit : un zéro inventé le ferait tomber du
podium, et c'est de l'argent.

LES RÔLES NE SONT PAS POSÉS PAR LE BOT. Rien ne relie un numéro de VA à un
compte Discord, et le bot n'a pas la permission de lire la liste des membres.
Les primes se réclament à la main, comme le bonus du jour.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "podium.json"
CONFIG_FICHIER = DATA_DIR / "podium_config.json"
NUMEROS_FICHIER = DATA_DIR / "podium_numeros.json"
LIENS_CACHE = DATA_DIR / "gmsdash_links.json"

SALON_PODIUM = "─│🏆┤-podium"
EQUIPE_VA = "tm_6a0e4739bfa0c238f20a8bf5"   # l'espace GetMySocial des liens VA

PRIMES = [10.0, 5.0, 3.0]
MEDAILLES = ["🥇", "🥈", "🥉"]
COMBIEN_AFFICHES = 15
HEURE_POST = 9          # lundi, heure française
MINUTES_LIVE = 60       # entre deux rafraîchissements du message vivant

# Les numéros que GetMySocial portait avant d'être renommé. Ils sont repris
# tels quels : quelqu'un qui était VA 12 reste VA 12.
NUMEROS_HISTORIQUES = {
    "BO7": 1, "Safidy": 2, "Laboule": 3, "VA 1 Noum": 4, "Bryan": 5,
    "Mykey": 6, "Miranto": 7, "VA 2 Noum": 8, "VA 3 Noum": 9,
    "Abdoul": 10, "Kylmich": 11, "Roucham": 12, "Gerome": 13,
}


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


# ─── la semaine ──────────────────────────────────────────────────────────
def semaine_en_cours(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi de la semaine où l'on est, et AUJOURD'HUI.

    La fin n'est pas le dimanche à venir : demander des clics sur des jours
    qui n'existent pas encore ne rend rien de plus, et afficher « au 28/09 »
    un mardi laisserait croire que la semaine est finie.
    """
    j = jour or dt.date.today()
    return j - dt.timedelta(days=j.weekday()), j


def semaine_passee(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi et le dimanche de la semaine QUI VIENT DE FINIR.

    Un lundi, rend la semaine d'avant. Un autre jour, la dernière semaine
    complète : un rattrapage à la main donne alors le même message.
    """
    j = jour or dt.date.today()
    lundi = j - dt.timedelta(days=j.weekday() + 7)
    return lundi, lundi + dt.timedelta(days=6)


# ─── qui est qui ─────────────────────────────────────────────────────────
def personne(nom_du_lien: str) -> Tuple[str, bool]:
    """« (Gerome) SPAM » → (« Gerome », True). « ( BO7 ) 1 » → (« BO7 », False)."""
    n = str(nom_du_lien or "").strip()
    dedans = re.search(r"\(([^)]*)\)", n)
    base = (dedans.group(1) if dedans else re.sub(r"\s*\d+\s*$", "", n)).strip()
    return (base or n), ("SPAM" in n.upper())


def cle_entite(nom: str, spam: bool) -> str:
    return f"{nom} SPAM" if spam else nom


def liens_bruts() -> Tuple[List[Dict[str, Any]], bool]:
    """(liens, frais). `frais` est faux quand on a dû se rabattre sur le cache."""
    equipe = _config().get("equipe") or EQUIPE_VA
    try:
        import gms
        # force_refresh : la liste est mise en cache deux minutes cote gms, et
        # un lien renomme ou cree la veille doit apparaitre dans le podium du
        # lundi — ce releve n'a lieu qu'une fois par semaine, il peut payer
        # le vrai appel.
        r = gms.list_links_team(equipe, force_refresh=True) or {}
        vivants = r.get("links") or r.get("data") or []
        if r.get("ok") is not False and vivants:
            return [l for l in vivants if isinstance(l, dict) and l.get("id")], True
    except Exception as e:
        print(f"[podium] liste des liens : {type(e).__name__}: {e}", flush=True)
    cache = _lire(LIENS_CACHE, {}).get(equipe) or []
    return [l for l in cache if isinstance(l, dict) and l.get("id")], False


def entites(liens: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{clé: {nom, spam, ids}} — une personne, ou son lien SPAM, comptés à part."""
    out: Dict[str, Dict[str, Any]] = {}
    for l in liens:
        nom, spam = personne(l.get("display_name") or l.get("title") or l.get("shortcode") or "")
        c = cle_entite(nom, spam)
        e = out.setdefault(c, {"nom": nom, "spam": spam, "ids": []})
        e["ids"].append(str(l["id"]))
    return out


def numeros(cles: List[str]) -> Dict[str, int]:
    """La table clé → numéro de VA, complétée et gardée sur disque.

    Un numéro déjà donné ne change plus. Les nouveaux sont attribués dans
    l'ordre alphabétique, pour qu'un même lot donne toujours le même résultat.
    """
    table = dict(_lire(NUMEROS_FICHIER, {}))
    if not table:
        table = {k: v for k, v in NUMEROS_HISTORIQUES.items()}
    pris = set(int(v) for v in table.values())
    neuf = False
    for c in sorted(cles):
        if c in table:
            continue
        n = 1
        while n in pris:
            n += 1
        table[c] = n
        pris.add(n)
        neuf = True
    if neuf:
        safe_json.write_text(NUMEROS_FICHIER,
                             json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True))
    return {k: int(v) for k, v in table.items()}


# ─── le classement ───────────────────────────────────────────────────────
def classement(debut: dt.date, fin: dt.date, pause: float = 0.3) -> Dict[str, Any]:
    """{lignes, illisibles, frais} — les clics US par entité, du plus fort au plus faible."""
    import gms
    d0, d1 = debut.isoformat(), fin.isoformat()
    liens, frais = liens_bruts()
    ents = entites(liens)
    table = numeros(list(ents.keys()))
    lignes: List[Dict[str, Any]] = []
    illisibles: List[str] = []
    for cle, e in ents.items():
        try:
            _, pays = gms.analytics_for_links(e["ids"], d0, d1)
        except Exception:
            pays = None
        va = f'VA {table.get(cle, 0)}'
        if pays is None:
            illisibles.append(va)
        else:
            lignes.append({"va": va, "numero": table.get(cle, 999),
                           "clics": int((pays or {}).get("US") or 0),
                           "liens": len(e["ids"]), "spam": e["spam"]})
        time.sleep(pause)
    # à égalité, le numéro départage : deux relevés de la même semaine doivent
    # rendre le même ordre, sinon le podium changerait tout seul d'un appel à l'autre
    lignes.sort(key=lambda x: (-x["clics"], x["numero"]))
    return {"lignes": lignes, "illisibles": sorted(illisibles), "frais": frais,
            "entites": len(ents), "liens": len(liens)}


# ─── le message ──────────────────────────────────────────────────────────
def embed_podium(cl: Dict[str, Any], debut: dt.date, fin: dt.date,
                 en_cours: bool = False) -> Dict[str, Any]:
    lignes = cl["lignes"]
    if en_cours:
        c = [f'🗓️ **Semaine en cours** — depuis le **{debut.strftime("%d/%m")}**, '
             f'arrêté au **{fin.strftime("%d/%m")}**',
             "Abonnements via Twitter 🐦 — clics **US**",
             "🔴 _Mis à jour tout seul, plusieurs fois par jour. Rien n'est joué._", ""]
    else:
        c = [f'🗓️ Semaine du **{debut.strftime("%d/%m")}** au **{fin.strftime("%d/%m/%Y")}**',
             "Abonnements via Twitter 🐦 — clics **US**", ""]
    for i, x in enumerate(lignes[:COMBIEN_AFFICHES]):
        if i < 3:
            c.append(f'{MEDAILLES[i]} **{x["va"]}** — **{x["clics"]}** subs '
                     f'· 💰 **{PRIMES[i]:.0f}$**')
        else:
            c.append(f'{i + 1}. {x["va"]} — **{x["clics"]}** subs')
    reste = len(lignes) - COMBIEN_AFFICHES
    if reste > 0:
        c.append(f'… _et {reste} autre{"s" if reste > 1 else ""}_ 👏')
    if not lignes:
        c.append("_Aucun relevé cette semaine._")

    c += ["", "🎁 **Les 3 meilleurs de la semaine touchent une prime :**"]
    for i, p in enumerate(PRIMES):
        c.append(f'{MEDAILLES[i]} {i + 1}{"er" if i == 0 else "e"} → **{p:.0f}$**')
    c += ["", "💸 **Pour recevoir ta prime :** envoie un message à **@SEVEN** dans "
              "**ton espace perso** avec **ton rang de la semaine** et **ton adresse "
              "USDC (réseau Solana)**.",
          "Un seul prix par personne · payé à la main après vérification",
          "", "🔢 _Ton numéro de VA ne change jamais : c'est le même chaque semaine._"]

    if cl["illisibles"]:
        c += ["", "⚠️ **Classement incomplet** : " + ", ".join(cl["illisibles"])
                  + " — relevé indisponible"
                  + (", il remontera au prochain passage." if en_cours
                     else ", à confirmer avant de payer.")]
    if not cl["frais"]:
        c += ["", "⚠️ _Liste des liens non rafraîchie (GetMySocial injoignable) : "
                  "des comptes peuvent manquer._"]

    pied = "YOULAB • Marché US · comptes VA, sans pseudo"
    if en_cours:
        pied += " · mis à jour " + dt.datetime.now().strftime("%d/%m à %Hh%M")
    return {"title": ("🔴 PODIUM SUBS — SEMAINE EN COURS" if en_cours
                      else "🏆 PODIUM SUBS DE LA SEMAINE"),
            "color": 0xE67E22 if en_cours else 0xF1C40F,
            "description": "\n".join(c)[:4096],
            "footer": {"text": pied}}


def _salon(gid: str) -> str:
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return ""
    voulu = _config().get("salon") or SALON_PODIUM
    for x in rep:
        if x.get("name") == voulu:
            return str(x["id"])
    return ""


def poster_podium(gid: str, jour: Optional[dt.date] = None,
                  mentionner: bool = True, forcer: bool = False) -> str:
    """Poste le podium de la semaine passée. Ne le poste pas deux fois."""
    gid = str(gid)
    debut, fin = semaine_passee(jour)
    d = _etat()
    postes = d.setdefault("postes", {})
    cle = f"{gid}:{debut.isoformat()}"
    if postes.get(cle) and not forcer:
        return str(postes[cle])
    salon = _salon(gid)
    if not salon:
        print(f"[podium] salon {SALON_PODIUM} introuvable sur {gid}", flush=True)
        return ""
    cl = classement(debut, fin)
    corps: Dict[str, Any] = {"embeds": [embed_podium(cl, debut, fin)]}
    if mentionner:
        corps["content"] = "@everyone 🏆 Podium subs de la semaine !"
        corps["allowed_mentions"] = {"parse": ["everyone"]}
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    postes[cle] = str(rep["id"])
    # le message vivant de la semaine ecoulee a fini son office : le prochain
    # rafraichissement en creera un neuf pour la semaine qui commence
    (d.setdefault("vivants", {})).pop(gid, None)
    _ecrire(d)
    print(f'[podium] {debut} → {fin} postée dans {gid} : {len(cl["lignes"])} entités, '
          f'{len(cl["illisibles"])} illisible(s), liste {"fraîche" if cl["frais"] else "du cache"}',
          flush=True)
    return str(rep["id"])


def rafraichir(gid: str, jour: Optional[dt.date] = None) -> str:
    """Met à jour (ou crée) le message VIVANT de la semaine en cours.

    Le message est RÉÉDITÉ, jamais reposté : un classement qui s'empile vingt
    fois par jour noierait le salon, et Discord ne notifie pas une édition —
    personne n'est dérangé pour trois clics de plus.

    Une semaine nouvelle veut un message neuf : celui de la semaine d'avant
    reste en place, il est devenu l'archive.
    """
    gid = str(gid)
    debut, fin = semaine_en_cours(jour)
    d = _etat()
    vivants = d.setdefault("vivants", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid)
    if not salon:
        print(f"[podium] salon {SALON_PODIUM} introuvable sur {gid}", flush=True)
        return ""
    cl = classement(debut, fin)
    if not cl["lignes"] and not cl["illisibles"]:
        # aucun relevé du tout : on ne remplace pas un classement correct par du vide
        print("[podium] aucun relevé, message vivant laissé tel quel", flush=True)
        return str(garde.get("message") or "")
    corps = {"embeds": [embed_podium(cl, debut, fin, en_cours=True)]}

    mid = str(garde.get("message") or "")
    if mid and garde.get("semaine") == debut.isoformat():
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json=corps)
        if code == 200:
            garde["vu"] = time.time()
            vivants[gid] = garde
            _ecrire(d)
            return mid
        # le message a pu être supprimé à la main : on en refait un plutôt
        # que de rester muet jusqu'à la semaine prochaine
        print(f"[podium] édition refusée (HTTP {code}), nouveau message", flush=True)

    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    vivants[gid] = {"semaine": debut.isoformat(), "message": str(rep["id"]), "vu": time.time()}
    _ecrire(d)
    print(f'[podium] message vivant {debut} → {fin} : {len(cl["lignes"])} entités', flush=True)
    return str(rep["id"])


def a_rafraichir(gid: str, maintenant: Optional[float] = None) -> bool:
    """Vrai quand le message vivant a passé l'âge, ou n'existe pas encore."""
    if _pause_gms():
        return False
    garde = (_etat().get("vivants") or {}).get(str(gid)) or {}
    if garde.get("semaine") != semaine_en_cours()[0].isoformat():
        return True
    minutes = int(_config().get("minutes") or MINUTES_LIVE)
    return (maintenant or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


def _pause_gms() -> bool:
    """GetMySocial nous a dit de nous calmer : on saute ce tour.

    Sans ça, le rafraîchissement tapait dans un quota déjà épuisé et volait
    les appels du tableau de bord, qui sert de vraies pages à de vraies gens.
    """
    try:
        import gms
        return int(gms.pause_restante() or 0) > 0
    except Exception:
        return False


def a_poster(maintenant: Optional[dt.datetime] = None) -> bool:
    """Vrai un lundi, passé l'heure de publication."""
    n = maintenant or dt.datetime.now()
    return n.weekday() == 0 and n.hour >= int(_config().get("heure") or HEURE_POST)
