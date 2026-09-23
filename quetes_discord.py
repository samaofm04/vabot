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
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
ETAT_FICHIER = DATA_DIR / "quetes.json"
CATALOGUE_FICHIER = DATA_DIR / "quetes_catalogue.json"

SALON_QUETES = "─│🎯┤-quête-du-jour"

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
    return bool(rid) and rid in roles


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
    """Le manager valide ou refuse. Un seul verdict par demande."""
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
    if v.get("message"):
        couleur = 0x22C55E if accepte else 0x6B7280
        texte = (f'✅ Validée par <@{par}> — **{v["montant"]:.2f}$** pour <@{uid}>.'
                 if accepte else f'✖️ Refusée par <@{par}>.')
        _api("PATCH", f'/channels/{v["salon"]}/messages/{v["message"]}',
             json={"embeds": [{"title": "🎯 Quête " + ("validée" if accepte else "refusée"),
                               "color": couleur,
                               "description": f'**{v["titre"]}**\n📅 {jour}\n\n{texte}',
                               "footer": {"text": f'YOULAB • saison {v.get("saison")}'}}],
                   "components": []})
    if accepte:
        g = gains(gid, uid, v.get("saison"))
        _api("POST", f'/channels/{v["salon"]}/messages',
             json={"content": f'<@{uid}> 🎉 Quête validée : **+{v["montant"]:.2f}$**. '
                              f'Total de la saison : **{g["montant"]:.2f}$**.',
                   "allowed_mentions": {"users": [uid]}})
        return _ephemere(f'✅ Validée. +{v["montant"]:.2f}$ pour <@{uid}>.')
    return _ephemere("✖️ Refusée.")


# ─── la commande /quetes ─────────────────────────────────────────────────
def enregistrer_commande(gid: str) -> bool:
    """Déclare /quetes sur le serveur. À lancer une fois ; Discord la garde."""
    from verif_discord import APP_ID
    code, rep = _api("POST", f"/applications/{APP_ID}/guilds/{gid}/commands",
                     json={"name": "quetes", "type": 1,
                           "description": "Voir l'argent gagné avec les quêtes cette saison"})
    ok = code in (200, 201)
    print(f'[quetes] /quetes {"enregistrée" if ok else "refusée"} sur {gid} : '
          f'HTTP {code} {"" if ok else str(rep)[:160]}', flush=True)
    return ok
