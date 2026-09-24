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
SALON_SUBS = "─│📊┤-subs"
SALON_BONUS = "─│💸┤-bonus-journalier"
PRIMES_JOUR = [7.50, 5.00, 3.50]
ALLTIME_FICHIER = DATA_DIR / "podium_alltime.json"
ALLTIME_DEPUIS = "2024-01-01"     # avant les premiers liens : « depuis toujours »
# Les espaces GetMySocial qui portent des liens de VA. Il y en a DEUX : les
# anciens liens vivent dans « JESSY LE RETOUR », les nouveaux sont generes
# dans « EMY TWITTER ». N'en lire qu'un rendait l'autre invisible au
# classement — quelqu'un aurait travaille sans jamais apparaitre.
EQUIPES_VA = ["tm_6a0e4739bfa0c238f20a8bf5",   # JESSY LE RETOUR
              "tm_6ab46ebb11a0232c11211b1a"]   # EMY TWITTER
EQUIPE_VA = EQUIPES_VA[0]                      # garde l'ancien nom lisible

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


# Le VPS tourne en UTC, le Mac en heure de Paris : sans cela, « lundi 09h »
# tombait a 11h francaise, et la semaine basculait le lundi a 02h. Tout ce qui
# touche aux dates passe par ici.
def _maintenant() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None)
    except Exception:
        return dt.datetime.now()


def _aujourdhui() -> dt.date:
    return _maintenant().date()


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


# ─── la semaine ──────────────────────────────────────────────────────────
def saison_en_cours(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """La quinzaine : du 1er au 15, ou du 16 à la fin du mois.

    Même découpage que les rangs et les quêtes — un seul calendrier dans la
    tête des VA, sinon « la saison » ne veut plus rien dire.
    """
    j = jour or _aujourdhui()
    if j.day <= 15:
        return j.replace(day=1), j.replace(day=15)
    fin = (j.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return j.replace(day=16), fin


def semaine_en_cours(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi de la semaine où l'on est, et AUJOURD'HUI.

    La fin n'est pas le dimanche à venir : demander des clics sur des jours
    qui n'existent pas encore ne rend rien de plus, et afficher « au 28/09 »
    un mardi laisserait croire que la semaine est finie.
    """
    j = jour or _aujourdhui()
    return j - dt.timedelta(days=j.weekday()), j


def semaine_passee(jour: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Le lundi et le dimanche de la semaine QUI VIENT DE FINIR.

    Un lundi, rend la semaine d'avant. Un autre jour, la dernière semaine
    complète : un rattrapage à la main donne alors le même message.
    """
    j = jour or _aujourdhui()
    lundi = j - dt.timedelta(days=j.weekday() + 7)
    return lundi, lundi + dt.timedelta(days=6)


# ─── qui est qui ─────────────────────────────────────────────────────────
def personne(nom_du_lien: str) -> Tuple[str, bool]:
    """« (Gerome) SPAM » → (« Gerome », True). « ( BO7 ) 1 » → (« BO7 », False)."""
    n = str(nom_du_lien or "").strip()
    # « Twitter VA 1 @abdoul », « va_@abdoul » : quand le nom porte une
    # arobase, c'est le pseudo qui suit qui designe la personne. Sans cette
    # regle, le nom entier devenait la cle — un numero de VA par libelle, et
    # « Twitter VA 1 @abdoul » n'aurait rien eu a voir avec « abdoul ».
    arobase = re.search(r"@\s*([A-Za-z0-9._-]{2,32})", n)
    if arobase:
        return arobase.group(1).strip("._-"), ("SPAM" in n.upper())
    dedans = re.search(r"\(([^)]*)\)", n)
    if dedans:
        base = dedans.group(1).strip()
    else:
        # PAS de rognage du chiffre final. « BO7 » devenait « BO » : une entite
        # fantome, un numero de VA gaspille a vie, et les clics du vrai BO7
        # coupes en deux. Et rogner « VA 9 » aurait donne « VA », ce qui fond
        # en un seul compte tous les liens du cache de repli. Sans parentheses,
        # le nom est pris tel quel.
        base = re.sub(r"\s+SPAM\s*$", "", n, flags=re.IGNORECASE).strip()
    return (base or n), ("SPAM" in n.upper())


def cle_entite(nom: str, spam: bool) -> str:
    return f"{nom} SPAM" if spam else nom


def liens_bruts() -> Tuple[List[Dict[str, Any]], bool]:
    """(liens, frais) sur TOUS les espaces de VA.

    `frais` n'est vrai que si chaque espace a repondu. Un seul repli sur le
    cache suffit a le rendre faux : le message le dira, plutot que de laisser
    croire a une liste complete.
    """
    equipes = list(_config().get("equipes") or
                   ([_config()["equipe"]] if _config().get("equipe") else EQUIPES_VA))
    tout: List[Dict[str, Any]] = []
    vus = set()
    frais = True
    for equipe in equipes:
        liens = None
        try:
            import gms
            # force_refresh : la liste est mise en cache deux minutes cote gms,
            # et un lien cree la veille doit apparaitre des le lendemain.
            r = gms.list_links_team(equipe, force_refresh=True) or {}
            vivants = r.get("links") or r.get("data") or []
            if r.get("ok") is not False and vivants:
                liens = vivants
        except Exception as e:
            print(f"[podium] liste {equipe} : {type(e).__name__}: {e}", flush=True)
        if liens is None:
            frais = False
            liens = _lire(LIENS_CACHE, {}).get(equipe) or []
            print(f"[podium] espace {equipe} : repli sur le cache "
                  f"({len(liens)} lien(s))", flush=True)
        for l in liens:
            if isinstance(l, dict) and l.get("id") and l["id"] not in vus:
                vus.add(l["id"])
                tout.append(l)
    return tout, frais


def entites(liens: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{clé: {nom, spam, ids}} — une personne, ou son lien SPAM, comptés à part."""
    out: Dict[str, Dict[str, Any]] = {}
    for l in liens:
        nom, spam = personne(l.get("display_name") or l.get("title") or l.get("shortcode") or "")
        c = cle_entite(nom, spam)
        e = out.setdefault(c, {"nom": nom, "spam": spam, "ids": []})
        e["ids"].append(str(l["id"]))
    return out


def numeros(cles: List[str], attribuer: bool = True) -> Dict[str, int]:
    """La table clé → numéro de VA, complétée et gardée sur disque.

    Un numéro déjà donné ne change plus. Les nouveaux sont attribués dans
    l'ordre alphabétique, pour qu'un même lot donne toujours le même résultat.
    """
    table = dict(_lire(NUMEROS_FICHIER, {}))
    if not table:
        table = {k: v for k, v in NUMEROS_HISTORIQUES.items()}
    pris = set(int(v) for v in table.values())
    neuf = False
    if not attribuer:
        # Liste non rafraichie : les noms viennent du cache, qui porte l'ANCIENNE
        # convention (« VA 9 », « Gaspacio »). Leur donner un numero le graverait
        # pour toujours, sur une panne passagere. On rend ce qu'on sait deja.
        return {k: int(v) for k, v in table.items()}
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
    table = numeros(list(ents.keys()), attribuer=frais)
    sans_numero = [c for c in ents if c not in table]
    if sans_numero:
        print(f"[podium] {len(sans_numero)} compte(s) sans numero, ecartes : "
              + ", ".join(sorted(sans_numero)[:6]), flush=True)
    lignes: List[Dict[str, Any]] = []
    illisibles: List[str] = []
    for cle, e in ents.items():
        if cle not in table:
            continue
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
            "entites": len(ents), "liens": len(liens),
            "sans_numero": sorted(sans_numero)}


def alltime() -> Dict[str, int]:
    """Le total « depuis toujours » par entité, recalculé une fois par jour.

    Ce chiffre ne bouge presque pas d'une heure à l'autre : le redemander à
    chaque rafraîchissement doublait le nombre d'appels pour rien, et volait
    le quota du tableau de bord.
    """
    cache = _lire(ALLTIME_FICHIER, {})
    if cache.get("jour") == _aujourdhui().isoformat() and cache.get("totaux"):
        return {k: int(v) for k, v in cache["totaux"].items()}
    import gms
    liens, _ = liens_bruts()
    ents = entites(liens)
    table = numeros(list(ents.keys()))
    fin = _aujourdhui().isoformat()
    totaux = dict(cache.get("totaux") or {})
    for cle, e in ents.items():
        try:
            _, pays = gms.analytics_for_links(e["ids"], ALLTIME_DEPUIS, fin)
        except Exception:
            pays = None
        if pays is not None:
            # un relevé raté garde l'ancien total plutôt que de l'effacer
            totaux[f'VA {table.get(cle, 0)}'] = int((pays or {}).get("US") or 0)
        time.sleep(0.3)
    safe_json.write_text(ALLTIME_FICHIER,
                         json.dumps({"jour": fin, "totaux": totaux},
                                    ensure_ascii=False, indent=2, sort_keys=True))
    return {k: int(v) for k, v in totaux.items()}


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
    if cl.get("sans_numero"):
        c += [f'ℹ️ _{len(cl["sans_numero"])} compte(s) pas encore numéroté(s), '
              "écarté(s) le temps que la liste revienne._"]

    pied = "YOULAB • Marché US · comptes VA, sans pseudo"
    if en_cours:
        pied += " · mis à jour " + _maintenant().strftime("%d/%m à %Hh%M")
    return {"title": ("🔴 PODIUM SUBS — SEMAINE EN COURS" if en_cours
                      else "🏆 PODIUM SUBS DE LA SEMAINE"),
            "color": 0xE67E22 if en_cours else 0xF1C40F,
            "description": "\n".join(c)[:4096],
            "footer": {"text": pied}}


def pages_subs(cl: Dict[str, Any], debut: dt.date, fin: dt.date,
               totaux: Dict[str, int]) -> List[Dict[str, Any]]:
    """Le classement de la quinzaine, découpé en autant de messages qu'il faut.

    Discord coupe une description à 4096 caractères. Plutôt que de tronquer —
    ce qui ferait croire à quelqu'un du bas de tableau qu'il n'existe pas —, on
    répartit sur plusieurs messages, numérotés « page 2/3 ». Le total de la
    période va sur la dernière page : c'est là qu'on le cherche.
    """
    lignes = cl["lignes"]
    tete = (f'🗓️ Période **{debut.strftime("%d/%m")} → {fin.strftime("%d/%m/%Y")}** '
            f'· depuis le {debut.strftime("%d/%m")} à 00h00\n'
            f'Clics **US** · **{len(lignes)}** comptes classés\n')

    rangs = []
    for i, x in enumerate(lignes):
        at = totaux.get(x["va"])
        suffixe = f' · 🌐 {at} all-time' if at is not None else ""
        rangs.append(f'{MEDAILLES[i]} **{x["va"]}** — **{x["clics"]}** subs{suffixe}'
                     if i < 3 else
                     f'{i + 1}. {x["va"]} — {x["clics"]} subs{suffixe}')
    if not rangs:
        rangs = ["_Aucun relevé pour cette période._"]

    total = sum(int(x["clics"]) for x in lignes)
    queue = [f'\n👥 **Total période**\n**{total}** subs']
    if cl["illisibles"]:
        queue.append("\n⚠️ Sans relevé cette fois : " + ", ".join(cl["illisibles"])
                     + " — ils remonteront au prochain passage.")
    if not cl["frais"]:
        queue.append("\n⚠️ _Liste des liens non rafraîchie : des comptes peuvent manquer._")
    bas = "\n".join(queue)

    # on remplit page par page, en gardant de la place pour l'en-tête ; la
    # dernière doit aussi loger le total, d'où la marge plus large
    MARGE = 3600
    pages: List[List[str]] = [[]]
    taille = len(tete)
    for r in rangs:
        if taille + len(r) + 1 > MARGE and pages[-1]:
            pages.append([])
            taille = len(tete)
        pages[-1].append(r)
        taille += len(r) + 1
    # le total ne tient plus sur la dernière page : il prend la sienne
    if len("\n".join([tete] + pages[-1])) + len(bas) > 4000:
        pages.append([])

    out = []
    for n, page in enumerate(pages, start=1):
        corps = tete + "\n" + "\n".join(page)
        if n == len(pages):
            corps += "\n" + bas
        pied = ("YOULAB • Marché US · comptes VA, sans pseudo · mis à jour "
                + _maintenant().strftime("%d/%m à %Hh%M"))
        if len(pages) > 1:
            pied = f"page {n}/{len(pages)} · " + pied
        out.append({"title": ("📊 Classement subs — la quinzaine"
                              + (f" ({n}/{len(pages)})" if len(pages) > 1 else "")),
                    "color": 0x3B82F6,
                    "description": corps[:4096],
                    "footer": {"text": pied}})
    return out


def rafraichir_subs(gid: str, jour: Optional[dt.date] = None) -> str:
    """Met à jour (ou crée) le classement vivant de la quinzaine, sur N pages."""
    gid = str(gid)
    debut, fin_saison = saison_en_cours(jour)
    aujourd = jour or _aujourdhui()
    d = _etat()
    vivants = d.setdefault("subs", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid, _config().get("salon_subs") or SALON_SUBS)
    if not salon:
        print(f"[podium] salon {SALON_SUBS} introuvable sur {gid}", flush=True)
        return ""
    # on s'arrête à aujourd'hui : demander des jours qui n'existent pas encore
    # ne rend rien de plus, et laisserait croire que la quinzaine est finie
    cl = classement(debut, min(aujourd, fin_saison))
    if not cl["lignes"] and not cl["illisibles"]:
        print("[podium] aucun relevé, classement subs laissé tel quel", flush=True)
        return str((garde.get("messages") or [""])[0])
    try:
        totaux = alltime()
    except Exception as e:
        print(f"[podium] all-time indisponible : {type(e).__name__}: {e}", flush=True)
        totaux = {}
    pages = pages_subs(cl, debut, fin_saison, totaux)

    # `message` (au singulier) est l'ancien format : un seul identifiant
    ids = list(garde.get("messages") or ([garde["message"]] if garde.get("message") else []))
    if garde.get("saison") != debut.isoformat():
        ids = []                      # quinzaine nouvelle : messages neufs
    neufs: List[str] = []
    for i, page in enumerate(pages):
        corps = {"embeds": [page]}
        if i < len(ids):
            code, rep = _api("PATCH", f"/channels/{salon}/messages/{ids[i]}", json=corps)
            if code == 200:
                neufs.append(ids[i])
                continue
            # supprimé à la main : on en refait un plutôt que de rester muet
            print(f"[podium] page {i + 1} inéditable (HTTP {code}), reposte", flush=True)
        code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
        if code != 200 or not rep.get("id"):
            print(f"[podium] page {i + 1} refusée (HTTP {code}) {str(rep)[:140]}", flush=True)
            continue
        neufs.append(str(rep["id"]))

    # la liste a raccourci : les pages en trop diraient n'importe quoi
    for surplus in ids[len(pages):]:
        c, _r = _api("DELETE", f"/channels/{salon}/messages/{surplus}")
        print(f"[podium] page en trop {surplus} retirée (HTTP {c})", flush=True)

    if not neufs:
        return ""
    vivants[gid] = {"saison": debut.isoformat(), "messages": neufs, "vu": time.time()}
    _ecrire(d)
    print(f'[podium] classement subs {debut} → {fin_saison} : {len(cl["lignes"])} comptes, '
          f'{len(neufs)} page(s)', flush=True)
    return neufs[0]


def a_rafraichir_subs(gid: str, maintenant: Optional[float] = None) -> bool:
    if _pause_gms():
        return False
    garde = (_etat().get("subs") or {}).get(str(gid)) or {}
    if garde.get("saison") != saison_en_cours()[0].isoformat():
        return True
    minutes = int(_config().get("minutes_subs") or _config().get("minutes") or MINUTES_LIVE)
    return (maintenant or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


def embed_bonus(cl: Dict[str, Any], jour: dt.date) -> Dict[str, Any]:
    """Le bonus du jour : les trois premiers de la JOURNÉE, et ce qu'ils gagnent."""
    lignes = cl["lignes"]
    c = [f'📅 Journée du **{jour.strftime("%d/%m/%Y")}** · clics **US** '
         f'· **{len(lignes)}** comptes suivis', ""]
    for i in range(3):
        x = lignes[i] if i < len(lignes) else None
        if x is None:
            c.append(f'{MEDAILLES[i]} **—** · **{PRIMES_JOUR[i]:.2f}$**')
        else:
            c.append(f'{MEDAILLES[i]} **{x["va"]}** — **{x["clics"]}** subs '
                     f'→ **{PRIMES_JOUR[i]:.2f}$**')
    # tout le monde a zéro : le dire, sinon un podium de zéros ressemble à un bug
    if lignes and not any(x["clics"] for x in lignes[:3]):
        c += ["", "_Personne n'a encore de sub aujourd'hui — le classement bouge "
                  "dès le premier._"]
    c += ["", "————————————",
          "🎁 **Pour recevoir ton bonus :** envoie un message à **@SEVEN** dans "
          "**ton espace perso** avec **ton rang du jour (top 1, 2 ou 3)** et "
          "**ton adresse USDC (réseau Solana)**.",
          "Un seul prix par personne · payé à la main après vérification"]
    if cl["illisibles"]:
        c += ["", "⚠️ Sans relevé aujourd'hui : " + ", ".join(cl["illisibles"])
                  + " — à confirmer avant de payer."]
    if not cl["frais"]:
        c += ["", "⚠️ _Liste des liens non rafraîchie : des comptes peuvent manquer._"]
    return {"title": f'💸 Bonus subs du jour — {jour.strftime("%d/%m/%Y")}',
            "color": 0x22C55E,
            "description": "\n".join(c)[:4096],
            "footer": {"text": "YOULAB • Marché US · comptes VA, sans pseudo · mis à jour "
                               + _maintenant().strftime("%d/%m à %Hh%M")}}


def rafraichir_bonus(gid: str, jour: Optional[dt.date] = None) -> str:
    """Met à jour (ou crée) le bonus du jour. Un message NEUF par journée."""
    gid = str(gid)
    j = jour or _aujourdhui()
    d = _etat()
    vivants = d.setdefault("bonus", {})
    garde = vivants.get(gid) or {}
    salon = _salon(gid, _config().get("salon_bonus") or SALON_BONUS)
    if not salon:
        print(f"[podium] salon {SALON_BONUS} introuvable sur {gid}", flush=True)
        return ""
    cl = classement(j, j)
    if not cl["lignes"] and not cl["illisibles"]:
        print("[podium] aucun relevé, bonus du jour laissé tel quel", flush=True)
        return str(garde.get("message") or "")
    corps = {"embeds": [embed_bonus(cl, j)]}

    mid = str(garde.get("message") or "")
    if mid and garde.get("jour") == j.isoformat():
        code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json=corps)
        if code == 200:
            garde["vu"] = time.time()
            vivants[gid] = garde
            _ecrire(d)
            return mid
        print(f"[podium] édition bonus refusée (HTTP {code}), nouveau message", flush=True)
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi bonus refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    vivants[gid] = {"jour": j.isoformat(), "message": str(rep["id"]), "vu": time.time()}
    _ecrire(d)
    print(f'[podium] bonus du jour {j} : {len(cl["lignes"])} comptes', flush=True)
    return str(rep["id"])


def a_rafraichir_bonus(gid: str, maintenant: Optional[float] = None) -> bool:
    if _pause_gms():
        return False
    garde = (_etat().get("bonus") or {}).get(str(gid)) or {}
    if garde.get("jour") != _aujourdhui().isoformat():
        return True
    minutes = int(_config().get("minutes_bonus") or _config().get("minutes") or MINUTES_LIVE)
    return (maintenant or time.time()) - float(garde.get("vu") or 0) >= minutes * 60


def _salon(gid: str, voulu: str = "") -> str:
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return ""
    voulu = voulu or _config().get("salon") or SALON_PODIUM
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
    if not cl["lignes"]:
        # GetMySocial muet un lundi matin : sans cela on publiait un podium VIDE
        # avec @everyone, et la semaine etait marquee comme faite POUR TOUJOURS.
        # On ne note rien : le tour suivant, dans dix minutes, reessaiera.
        print(f'[podium] {debut} → {fin} : aucun releve payable '
              f'({cl["entites"]} entites, {len(cl["illisibles"])} illisible(s)) — '
              "rien poste, nouvel essai au prochain tour", flush=True)
        return ""
    corps: Dict[str, Any] = {"embeds": [embed_podium(cl, debut, fin)]}
    if mentionner:
        corps["content"] = "@everyone 🏆 Podium subs de la semaine !"
        corps["allowed_mentions"] = {"parse": ["everyone"]}
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[podium] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    postes[cle] = str(rep["id"])
    # Le message vivant de la semaine ecoulee a fini son office. Mais le lundi
    # a 09h il montre deja la semaine QUI COMMENCE (elle a bascule a 00h) :
    # le jeter sans regarder laissait un « SEMAINE EN COURS » orphelin fige
    # dans le salon, et en faisait creer un second juste apres.
    _v = d.setdefault("vivants", {})
    if (_v.get(gid) or {}).get("semaine") == debut.isoformat():
        _v.pop(gid, None)
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
    n = maintenant or _maintenant()
    return n.weekday() == 0 and n.hour >= int(_config().get("heure") or HEURE_POST)
