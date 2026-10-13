"""La quête du jour : une mission par jour, une récompense, validée par un manager.

Chaque nuit une quête est postée dans le salon des quêtes, avec un bouton
« ✅ Valider ma quête ». Le membre clique, sa demande part dans SON salon
perso (celui ouvert par tickets_discord), et son manager tranche d'un clic.
Validée, la récompense s'ajoute à ses gains de la saison ; `/quetes` les lui
montre.

POURQUOI UN MANAGER TRANCHE, et pas le bot tout seul. Rien ne permet
aujourd'hui de vérifier une quête automatiquement :

- « X subs » : YouL4b compte les subs par LIEN (VA 1 à 10, GetMySocial), pas
  par compte Discord. Le bot ne peut pas savoir que tel membre en a fait 100.
- « X messages » : le bot SEVEN n'a pas de passerelle Discord (il ne répond
  qu'aux interactions HTTP) et la permission de lire les messages est
  désactivée. Il ne voit littéralement aucun message.

Le clic ouvre donc une demande, comme le bonus du jour l'annonce déjà :
« payé à la main après vérification ». Le jour où l'une des deux mesures
existera, `_verifiable` le dira et la validation pourra devenir automatique
sans toucher au reste.

LA SAISON est la quinzaine, comme le classement des subs : 2026-09-A du 1er
au 15, 2026-09-B du 16 à la fin du mois. Les gains repartent à zéro à chaque
saison — c'est écrit dans le message, il ne faut pas que ce soit une surprise.

EN PAUSE depuis le 13/10/2026 (QUETES_EN_PAUSE, plus bas) : plus de quête du
jour, plus de nouvelle demande, les boutons déjà postés retirés une fois. Les
demandes déjà parties chez un manager se tranchent toujours.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "quetes.json"
CATALOGUE_FICHIER = DATA_DIR / "quetes_catalogue.json"

SALON_QUETES = "─│🎯┤-quête-du-jour"

# Propriétaire, 13/10/2026, sur la capture d'un ticket VA (« 🎯 Quête validée »,
# « 🎯 Quête à valider » et ses boutons Valider/Refuser) : « pour tous les
# trucs, pour le moment retire les quêtes ». « Pour le moment » : un
# interrupteur, pas un retrait du code — False remet tout comme avant.
# Pendant la pause, sur TOUS les serveurs :
# - la quête du jour n'est plus postée ;
# - le bouton « Valider ma quête » des anciens messages répond la pause et
#   n'enregistre rien ;
# - les demandes DÉJÀ parties chez un manager se tranchent toujours : c'est de
#   l'argent gagné, on ne le perd ni ne le refuse d'office ;
# - /quetes montre toujours le total de la saison, avec la ligne de pause ;
# - une seule fois, les messages de quête déjà postés perdent leur bouton.
QUETES_EN_PAUSE = True
PAUSE_TEXTE = "⏸️ Les quêtes sont en pause pour le moment."
# La ligne posée sur les messages de quête dont le bouton est retiré.
PAUSE_LIGNE_MESSAGE = "⏸️ **Quêtes en pause** pour le moment."

# Lire-modifier-écrire de data/quetes.json. Le retrait des boutons tourne dans
# le fil du démon pendant qu'un manager tranche depuis la route Discord : sans
# verrou, l'un relisait l'état, l'autre écrivait le sien, et le premier
# réécrivait sa copie par-dessus — un verdict « validée » pouvait disparaître
# alors que le message avait déjà perdu ses boutons.
_VERROU_ETAT = threading.Lock()
# « [quetes] en pause » une fois par serveur et par jour : le démon repasse
# toutes les 10 minutes, la ligne noierait le journal.
_PAUSE_DITE: set = set()

# Le catalogue par défaut. data/quetes_catalogue.json le remplace entièrement
# s'il existe : les missions et les montants se règlent sans toucher au code.
# `auto` dit si le bot saurait vérifier tout seul — aucune ne le peut encore.
CATALOGUE: List[Dict[str, Any]] = [
    {"id": "subs_saison_100", "titre": "Avoir 100 subs depuis le début de la saison",
     "detail": "Atteins **100 subs cumulés** depuis le début de la saison en cours.",
     "montant": 2.00, "auto": False},
    {"id": "messages_50", "titre": "Envoyer 50 messages sur le Discord aujourd'hui",
     "detail": "Envoie **50 messages** aujourd'hui sur le serveur (tous salons confondus). "
               "Remis à 0 chaque jour.",
     "montant": 0.15, "auto": False},
    {"id": "subs_jour_5", "titre": "Faire 5 subs aujourd'hui",
     "detail": "Amène **5 subs** dans la journée sur ton compte.",
     "montant": 0.50, "auto": False},
    {"id": "tweets_3", "titre": "Poster 3 tweets aujourd'hui",
     "detail": "Publie **3 tweets** aujourd'hui sur ton compte.",
     "montant": 0.25, "auto": False},
    {"id": "podium_jour", "titre": "Être dans le top 3 du classement du jour",
     "detail": "Termine la journée **dans les 3 premiers** du classement des subs.",
     "montant": 0.75, "auto": False},
    {"id": "parrainage_1", "titre": "Parrainer une nouvelle recrue",
     "detail": "Fais entrer **une personne** sur le serveur : elle doit te citer "
               "comme parrain dans son espace perso.",
     "montant": 1.00, "auto": False},
]


# ─── état ────────────────────────────────────────────────────────────────
def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(ETAT_FICHIER, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ecrire(d: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[quetes] état non écrit : {type(e).__name__}: {e}", flush=True)


def catalogue() -> List[Dict[str, Any]]:
    try:
        d = safe_json.load(CATALOGUE_FICHIER, default=None)
        if isinstance(d, list) and d:
            return [q for q in d if isinstance(q, dict) and q.get("id")]
    except Exception:
        pass
    return CATALOGUE


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


# ─── saison et quête du jour ─────────────────────────────────────────────
def saison(jour: Optional[dt.date] = None) -> str:
    """« 2026-09-B » : la quinzaine, comme le classement des subs."""
    j = jour or dt.date.today()
    return f'{j.strftime("%Y-%m")}-{"A" if j.day <= 15 else "B"}'


def quete_du_jour(jour: Optional[dt.date] = None) -> Dict[str, Any]:
    """La quête d'un jour donné.

    Le choix dérive de la DATE, pas du hasard : reposter le même jour redonne
    la même quête, et on peut dire à l'avance celle de demain. Le catalogue
    est parcouru en boucle pour qu'aucune mission ne revienne deux jours de
    suite tant qu'il en reste d'autres.
    """
    q = catalogue()
    j = jour or dt.date.today()
    return dict(q[j.toordinal() % len(q)])


def _verifiable(q: Dict[str, Any]) -> bool:
    """Le bot saurait-il trancher seul ? Aucune mesure ne le permet encore
    (voir l'en-tête) ; la fonction existe pour que le jour où ça change, il
    n'y ait qu'un endroit à modifier."""
    return bool(q.get("auto"))


# ─── poster la quête ─────────────────────────────────────────────────────
def _salon_quetes(gid: str) -> str:
    code, rep = _api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(rep, list):
        return ""
    for c in rep:
        if c.get("name") == SALON_QUETES:
            return str(c["id"])
    return ""


def _embed_quete(q: Dict[str, Any], jour: dt.date) -> Dict[str, Any]:
    return {
        "title": "🎯 Quête du jour",
        "color": 0x3B82F6,
        "description": (
            f'**{q["titre"]}**\n\n'
            f'📖 {q["detail"]}\n\n'
            f'🎁 Récompense : **{q["montant"]:.2f}$**\n\n'
            "Réussis-la puis clique ✅ **Valider ma quête** ci-dessous.\n"
            "Ta demande part dans **ton espace perso** ; ton manager la valide.\n\n"
            "💰 **Tes gains**\nFais `/quetes` pour voir tout l'argent gagné **cette saison**.\n"
            "⚠️ Les gains repartent à **0 à chaque nouvelle saison**."),
        "footer": {"text": f'YOULAB • {jour.strftime("%d/%m/%Y")} • saison {saison(jour)}'},
    }


def _bouton_valider(jour: dt.date) -> List[Dict[str, Any]]:
    return [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Valider ma quête",
         "emoji": {"name": "✅"}, "custom_id": f"quete:go:{jour.isoformat()}"}]}]


def poster_quete(gid: str, jour: Optional[dt.date] = None, mentionner: bool = True) -> str:
    """Poste la quête du jour. Ne la poste pas deux fois le même jour."""
    gid = str(gid)
    if QUETES_EN_PAUSE:
        _en_pause(gid, jour or dt.date.today())
        return ""
    try:
        import verif_discord as _vd
        if (_vd.serveur(gid) or {}).get("quetes") is False:
            return ""        # serveur sans quete du jour (Va IG) : rien, sans erreur
    except Exception:                                        # noqa: BLE001
        pass
    j = jour or dt.date.today()
    d = _etat()
    postees = d.setdefault("postees", {})
    cle = f"{gid}:{j.isoformat()}"
    if postees.get(cle):
        return str(postees[cle])
    salon = _salon_quetes(gid)
    if not salon:
        print(f"[quetes] salon {SALON_QUETES} introuvable sur {gid}", flush=True)
        return ""
    q = quete_du_jour(j)
    corps: Dict[str, Any] = {"embeds": [_embed_quete(q, j)], "components": _bouton_valider(j)}
    if mentionner:
        corps["content"] = "@everyone 🎯 La quête du jour est là !"
        corps["allowed_mentions"] = {"parse": ["everyone"]}
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    if code != 200 or not rep.get("id"):
        print(f"[quetes] envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    postees[cle] = str(rep["id"])
    _ecrire(d)
    print(f'[quetes] {j} « {q["titre"]} » postée dans {gid}', flush=True)
    return str(rep["id"])


# ─── la pause ────────────────────────────────────────────────────────────
def _en_pause(gid: str, j: dt.date) -> None:
    """Ce que fait le passage du démon pendant la pause : ne rien poster, le
    dire au journal, et retirer les boutons encore en place sur CE serveur.
    Le démon appelle poster_quete serveur par serveur, chacun sous son bot
    (sur_serveur) : c'est ce passage-là qui fait le retrait."""
    try:
        import verif_discord as _vd
        sans_quetes = (_vd.serveur(gid) or {}).get("quetes") is False
    except Exception:                                        # noqa: BLE001
        sans_quetes = False
    # Va IG n'a jamais eu de quête du jour : y annoncer la pause chaque jour
    # serait du bruit. Son retrait tourne quand même (il ne trouve rien).
    cle = f"{gid}:{j.isoformat()}"
    if not sans_quetes and cle not in _PAUSE_DITE:
        _PAUSE_DITE.add(cle)
        print(f"[quetes] en pause (QUETES_EN_PAUSE) : aucune quête du jour postée "
              f"le {j.isoformat()} sur {gid}", flush=True)
        _signaler_hors_boucle()
    retirer_boutons(gid)


def _signaler_hors_boucle() -> None:
    """Le démon ne passe que sur les serveurs de SERVEURS_EXTRA : une quête
    postée ailleurs (à la main) garderait son bouton sans que personne le
    sache. On le dit, une fois par serveur ; retirer_boutons(<gid>) s'appelle
    à la main."""
    try:
        import verif_discord as _vd
        visites = {str(g) for g in _vd.SERVEURS_EXTRA}
    except Exception:                                        # noqa: BLE001
        return
    d = _etat()
    faits = d.get("pause_boutons") or {}
    restes: Dict[str, int] = {}
    for cle in (d.get("postees") or {}):
        g = str(cle).rpartition(":")[0]
        if g not in visites and cle not in faits:
            restes[g] = restes.get(g, 0) + 1
    for g, n in restes.items():
        if f"hors:{g}" not in _PAUSE_DITE:
            _PAUSE_DITE.add(f"hors:{g}")
            print(f"[quetes] pause : {n} quête(s) postée(s) sur {g}, serveur que le démon ne "
                  f"visite pas — boutons laissés (quetes_discord.retirer_boutons('{g}'))", flush=True)


def _noter_retraits(resultats: Dict[str, str]) -> None:
    """La trace du retrait, relue juste avant d'écrire et sous verrou : un
    manager peut avoir tranché pendant les appels à Discord (voir
    _VERROU_ETAT)."""
    if not resultats:
        return
    with _VERROU_ETAT:
        d = _etat()
        trace = d.setdefault("pause_boutons", {})
        maintenant = int(time.time())
        for cle, etat in resultats.items():
            trace[cle] = {"etat": etat, "le": maintenant}
        _ecrire(d)


def retirer_boutons(gid: str) -> Dict[str, int]:
    """Une seule fois par message : retire « ✅ Valider ma quête » des quêtes
    déjà postées sur ce serveur et y pose la ligne de pause.

    Pourquoi : un ancien message garde son bouton pour toujours, et un clic
    sur la quête d'un jour passé ouvrait encore une demande. Le clic répond
    déjà la pause (traiter), mais un bouton qui ne fait plus rien ne doit
    pas rester sous les yeux des VA.

    On MODIFIE, on n'efface jamais : le contenu passe à la ligne de pause,
    les boutons disparaissent, l'embed (la quête et son montant) ne bouge
    pas. Le message est modifié par le bot de son serveur (sur_serveur) :
    Discord ne laisse modifier un message qu'à son auteur.

    Trace dans data/quetes.json (« pause_boutons ») : un message retiré ne
    l'est pas deux fois. Un échec passager (salon introuvable, réseau,
    limite Discord) n'est PAS noté : le passage suivant du démon réessaie.
    Deux refus définitifs sont notés, et dits : le message n'existe plus
    (404), ou il a été posté par un autre bot (403, code 50005 — Siri, avant
    que Threads ait le sien) ; un clic y répond la pause de toute façon.
    """
    gid = str(gid)
    bilan = {"retires": 0, "absents": 0, "autre_bot": 0, "echecs": 0, "illisibles": 0}
    d = _etat()
    postees = d.get("postees") or {}
    faits = d.get("pause_boutons") or {}
    a_faire: List[tuple] = []
    resultats: Dict[str, str] = {}
    for cle, mid in postees.items():
        if cle in faits:
            continue
        g, _, jour = str(cle).rpartition(":")
        if g != gid:
            continue
        if not str(mid or "").strip():
            # une entrée sans identifiant de message : rien à modifier, mais
            # on le dit (une seule fois, elle est notée)
            print(f"[quetes] pause : entrée {cle} sans message, rien à retirer", flush=True)
            resultats[cle] = "illisible"
            bilan["illisibles"] += 1
            continue
        a_faire.append((jour, cle, str(mid)))
    if not a_faire:
        _noter_retraits(resultats)
        return bilan
    # le plus récent d'abord : c'est celui sur lequel les VA cliquent
    a_faire.sort(reverse=True)
    from verif_discord import sur_serveur
    with sur_serveur(gid):
        salon = _salon_quetes(gid)
        if not salon:
            bilan["echecs"] += len(a_faire)
            print(f"[quetes] pause : salon {SALON_QUETES} introuvable sur {gid} — "
                  f"{len(a_faire)} bouton(s) à retirer, nouvel essai au prochain passage", flush=True)
            _noter_retraits(resultats)
            return bilan
        for jour, cle, mid in a_faire:
            code, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}",
                             json={"content": PAUSE_LIGNE_MESSAGE, "components": [],
                                   "allowed_mentions": {"parse": []}})
            code_d = (rep or {}).get("code") if isinstance(rep, dict) else None
            if code == 200:
                resultats[cle] = "retire"
                bilan["retires"] += 1
            elif code == 404:
                resultats[cle] = "absent"
                bilan["absents"] += 1
                print(f"[quetes] pause : message de la quête du {jour} ({mid}) introuvable "
                      f"sur {gid} — rien à retirer", flush=True)
            elif code == 403 and code_d == 50005:
                resultats[cle] = "autre_bot"
                bilan["autre_bot"] += 1
                print(f"[quetes] pause : la quête du {jour} ({mid}) sur {gid} a été postée par "
                      f"un autre bot — bouton laissé, un clic y répond la pause", flush=True)
            else:
                bilan["echecs"] += 1
                print(f"[quetes] pause : bouton de la quête du {jour} ({mid}) non retiré sur {gid} "
                      f"(HTTP {code}) {str(rep)[:120]} — nouvel essai au prochain passage", flush=True)
    _noter_retraits(resultats)
    print(f'[quetes] pause sur {gid} : {bilan["retires"]} bouton(s) retiré(s), '
          f'{bilan["absents"]} message(s) disparu(s), {bilan["autre_bot"]} d\'un autre bot, '
          f'{bilan["echecs"]} à réessayer', flush=True)
    return bilan


# ─── gains ───────────────────────────────────────────────────────────────
def gains(gid: str, uid: str, sais: Optional[str] = None) -> Dict[str, Any]:
    """{montant, quetes} d'un membre pour une saison."""
    s = sais or saison()
    faits = [v for k, v in (_etat().get("demandes") or {}).items()
             if k.startswith(f"{gid}:{uid}:") and v.get("etat") == "ok" and v.get("saison") == s]
    return {"montant": round(sum(float(v.get("montant") or 0) for v in faits), 2),
            "quetes": len(faits), "saison": s}


def _ephemere(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte, "flags": 64}}


def _est_manager(p: Dict[str, Any], gid: str) -> bool:
    try:
        import tickets_discord
        rid = tickets_discord.role_manager(gid)
    except Exception:
        rid = ""
    roles = ((p.get("member") or {}).get("roles") or [])
    if rid and rid in roles:
        return True
    try:
        hid = tickets_discord.role_helper(gid)     # même niveau qu'un manager
    except Exception:
        hid = ""
    return bool(hid) and hid in roles


# ─── interactions ────────────────────────────────────────────────────────
def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Répond aux boutons et à /quetes. Rend None si ce n'est pas pour nous :
    l'appelant passe alors la main à verif_discord, qui garde ses propres
    boutons. Une seule route Discord, deux modules, aucun mélange."""
    try:
        t = p.get("type")
        gid = str(p.get("guild_id") or "")
        user = ((p.get("member") or {}).get("user") or p.get("user") or {})
        uid = str(user.get("id") or "")

        if t == 2:                                   # commande /quetes
            if ((p.get("data") or {}).get("name") or "") != "quetes":
                return None
            g = gains(gid, uid)
            if QUETES_EN_PAUSE:
                # le total gagné reste visible : il est dû ; seul le conseil
                # « clique Valider » disparaît, le bouton ne fait plus rien
                if not g["quetes"]:
                    return _ephemere(f'💰 Aucune quête validée pour la saison **{g["saison"]}**.\n'
                                     + PAUSE_TEXTE)
                return _ephemere(f'💰 Saison **{g["saison"]}** : **{g["montant"]:.2f}$** '
                                 f'sur **{g["quetes"]}** quête(s) validée(s).\n'
                                 "⚠️ Payé après validation de ta période d'essai.\n"
                                 + PAUSE_TEXTE)
            if not g["quetes"]:
                return _ephemere(f'💰 Aucune quête validée pour la saison **{g["saison"]}**.\n'
                                 "Clique ✅ **Valider ma quête** après l'avoir réussie.")
            return _ephemere(f'💰 Saison **{g["saison"]}** : **{g["montant"]:.2f}$** '
                             f'sur **{g["quetes"]}** quête(s) validée(s).\n'
                             "⚠️ Payé après validation de ta période d'essai.")

        if t != 3:
            return None
        cid = ((p.get("data") or {}).get("custom_id") or "")
        if not cid.startswith("quete:"):
            return None
        if QUETES_EN_PAUSE and cid.split(":")[1:2] == ["go"]:
            # un ancien message garde son bouton : le clic répond la pause et
            # n'écrit RIEN (ni demande, ni message dans l'espace perso)
            return _ephemere(PAUSE_TEXTE)
        if not gid or not uid:
            return _ephemere("Compte introuvable.")
        morceaux = cid.split(":")
        action = morceaux[1] if len(morceaux) > 1 else ""

        if action == "go":
            jour = morceaux[2] if len(morceaux) > 2 else dt.date.today().isoformat()
            return _demander(gid, uid, jour, p)
        if action in ("ok", "no"):
            if len(morceaux) < 4:
                return _ephemere("Bouton illisible.")
            if not _est_manager(p, gid):
                return _ephemere("Seul un 🛡️ Manager peut valider une quête.")
            return _trancher(gid, morceaux[2], morceaux[3], action == "ok", uid, p)
        return _ephemere("Action inconnue.")
    except Exception as e:
        print(f"[quetes] interaction : {type(e).__name__}: {e}", flush=True)
        return _ephemere("⚠️ Une erreur est survenue. Réessaie dans un instant.")


def _demander(gid: str, uid: str, jour: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Le membre réclame la quête : la demande part dans son espace perso."""
    d = _etat()
    demandes = d.setdefault("demandes", {})
    cle = f"{gid}:{uid}:{jour}"
    deja = demandes.get(cle)
    if deja and deja.get("etat") == "ok":
        return _ephemere("✅ Cette quête t'a déjà été validée.")
    if deja and deja.get("etat") == "attente":
        salon = deja.get("salon")
        return _ephemere("⏳ Ta demande est déjà partie"
                         + (f" dans <#{salon}>." if salon else ".")
                         + " Ton manager la regarde.")

    try:
        import tickets_discord
        ticket = tickets_discord.ticket_de(gid, uid)
    except Exception:
        ticket = ""
    if not ticket:
        return _ephemere("Tu n'as pas encore d'espace perso — un manager doit t'en "
                         "ouvrir un. Préviens-le, puis reclique ici.")

    q = quete_du_jour(dt.date.fromisoformat(jour))
    embed = {"title": "🎯 Quête à valider", "color": 0xF59E0B,
             "description": (f'<@{uid}> déclare avoir réussi :\n\n**{q["titre"]}**\n\n'
                             f'🎁 Récompense : **{q["montant"]:.2f}$**\n'
                             f'📅 {jour}\n\n'
                             "Un 🛡️ Manager tranche ci-dessous."),
             "footer": {"text": f"YOULAB • saison {saison(dt.date.fromisoformat(jour))}"}}
    boutons = [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Valider", "emoji": {"name": "✅"},
         "custom_id": f"quete:ok:{uid}:{jour}"},
        {"type": 2, "style": 4, "label": "Refuser", "emoji": {"name": "✖️"},
         "custom_id": f"quete:no:{uid}:{jour}"}]}]
    code, rep = _api("POST", f"/channels/{ticket}/messages",
                     json={"embeds": [embed], "components": boutons,
                           "allowed_mentions": {"users": [uid]}})
    if code != 200:
        print(f"[quetes] demande non postée dans {ticket} : HTTP {code}", flush=True)
        return _ephemere("⚠️ Impossible de prévenir ton manager. Réessaie dans un instant.")
    demandes[cle] = {"quete": q["id"], "titre": q["titre"], "montant": float(q["montant"]),
                     "etat": "attente", "saison": saison(dt.date.fromisoformat(jour)),
                     "salon": ticket, "message": str(rep.get("id") or ""),
                     "demande": int(time.time())}
    _ecrire(d)
    return _ephemere(f"✅ Demande envoyée à ton manager dans <#{ticket}>.\n"
                     f'Récompense si elle est validée : **{q["montant"]:.2f}$**.')


def _trancher(gid: str, uid: str, jour: str, accepte: bool,
              par: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Le manager valide ou refuse. Un seul verdict par demande.

    Pendant la pause aussi : une demande déjà partie est de l'argent gagné."""
    # sous verrou : le retrait des boutons de la pause écrit le même fichier
    # depuis le fil du démon (voir _VERROU_ETAT)
    with _VERROU_ETAT:
        d = _etat()
        demandes = d.setdefault("demandes", {})
        cle = f"{gid}:{uid}:{jour}"
        v = demandes.get(cle)
        if not v:
            return _ephemere("Demande introuvable (elle a peut-être été effacée).")
        if v.get("etat") != "attente":
            deja = "validée" if v["etat"] == "ok" else "refusée"
            return _ephemere(f"Cette quête a déjà été {deja}.")
        v["etat"] = "ok" if accepte else "non"
        v["par"] = par
        v["tranche"] = int(time.time())
        _ecrire(d)

    # Le message perd ses boutons : impossible de revenir dessus par mégarde.
    couleur = 0x22C55E if accepte else 0x6B7280
    texte = (f'✅ Validée par <@{par}> — **{v["montant"]:.2f}$** pour <@{uid}>.'
             if accepte else f'✖️ Refusée par <@{par}>.')
    verdict = {"title": "🎯 Quête " + ("validée" if accepte else "refusée"),
               "color": couleur,
               "description": f'**{v["titre"]}**\n📅 {jour}\n\n{texte}',
               "footer": {"text": f'YOULAB • saison {v.get("saison")}'}}
    # Quand le clic vient du message de la demande, c'est la REPONSE au clic
    # qui le remplace (type 7), avec le jeton du clic. Un PATCH classique part
    # avec le jeton du bot en service : si la demande a ete postee par un
    # autre bot (Siri, avant la bascule de Threads), Discord le refuse — et le
    # message gardait ses boutons Valider/Refuser apres le verdict.
    clique = str(((p or {}).get("message") or {}).get("id") or "")
    par_le_clic = bool(v.get("message")) and clique == str(v["message"])
    if v.get("message") and not par_le_clic:
        code_m, rep_m = _api("PATCH", f'/channels/{v["salon"]}/messages/{v["message"]}',
                             json={"embeds": [verdict], "components": []})
        if code_m != 200:
            print(f"[quetes] demande {cle} : message non mis a jour (HTTP {code_m}) "
                  f"{str(rep_m)[:100]}", flush=True)
    if accepte:
        g = gains(gid, uid, v.get("saison"))
        _api("POST", f'/channels/{v["salon"]}/messages',
             json={"content": f'<@{uid}> 🎉 Quête validée : **+{v["montant"]:.2f}$**. '
                              f'Total de la saison : **{g["montant"]:.2f}$**.',
                   "allowed_mentions": {"users": [uid]}})
        if par_le_clic:
            return {"type": 7, "data": {"embeds": [verdict], "components": [],
                                        "allowed_mentions": {"parse": []}}}
        return _ephemere(f'✅ Validée. +{v["montant"]:.2f}$ pour <@{uid}>.')
    if par_le_clic:
        return {"type": 7, "data": {"embeds": [verdict], "components": [],
                                    "allowed_mentions": {"parse": []}}}
    return _ephemere("✖️ Refusée.")


# ─── la commande /quetes ─────────────────────────────────────────────────
def enregistrer_commande(gid: str) -> bool:
    """Déclare /quetes sur le serveur. À lancer une fois ; Discord la garde.

    Sous l'application du bot de CE serveur : déclarée sous Siri sur
    Threads, la commande serait partie vers Siri, et non vers le bot Threads.
    À relancer quand le bot Threads prend le relais."""
    from verif_discord import bot_du_serveur
    app = bot_du_serveur(gid)["app_id"]
    code, rep = _api("POST", f"/applications/{app}/guilds/{gid}/commands",
                     json={"name": "quetes", "type": 1,
                           "description": "Voir l'argent gagné avec les quêtes cette saison"})
    ok = code in (200, 201)
    print(f'[quetes] /quetes {"enregistrée" if ok else "refusée"} sur {gid} : '
          f'HTTP {code} {"" if ok else str(rep)[:160]}', flush=True)
    return ok
