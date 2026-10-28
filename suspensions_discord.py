"""Cartes « ⏸️ Suspension temporaire » : la raison, et un bouton pour la lever.

Propriétaire, 28/10/2026, devant 👋・départs-et-sanctions de Twitter : la carte
disait seulement « Discord indique une exclusion temporaire », sans dire
pourquoi, et un manager qui voulait remettre le VA devait aller le chercher
dans la liste des membres. Il veut « la raison » et, « du même bouton »,
pouvoir « directement remettre le gars ».

La carte elle-même est postée par membres_evenements (Codex, hors git, sur
le VPS). Ce module ne poste rien de lui-même :
- brancher()   au démarrage (create_app) : enveloppe l'appel REST par lequel
               membres_evenements poste, pour compléter ses cartes ⏸️ ;
- raison()     le pourquoi, lu dans le journal d'audit : c'est le seul endroit
               où Discord le donne (règle AutoMod, ou le staff qui a suspendu) ;
- composants() le bouton ▶️ Lever la suspension ;
- traiter()    le clic, depuis /discord/interactions (web_upload).
"""
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

PREFIXE = "susp:lever:"
MODERER = 1 << 40                 # « Exclure temporairement des membres »
AUDIT_AUTOMOD = 145               # AUTO_MODERATION_USER_COMMUNICATION_DISABLED
AUDIT_MEMBRE = 24                 # MEMBER_UPDATE (un staff, à la main)
# La carte part au tour suivant de membres_evenements (45 s) ; une heure de
# marge couvre un bot redémarré entre la suspension et le constat.
AVANT_S = 3600
APRES_S = 120
REGLES_S = 600                    # les règles AutoMod changent rarement
MAX_DESCRIPTION = 4096
# ce qu'écrit membres_evenements sur sa carte (titres, LABELS['suspendu'])
TITRE = "⏸️ Suspension temporaire"
LIBELLE = "Suspension temporaire"
_RE_MEMBRE = re.compile(r"<@!?(\d{5,25})>")
_RE_FIN = re.compile(r"<t:(\d+):F>")

_REGLES: Dict[str, Tuple[float, Dict[str, str]]] = {}
_EN_COURS: set = set()
_VERROU = threading.Lock()


def _date_id(snowflake: Any) -> float:
    return ((int(snowflake) >> 22) + 1420070400000) / 1000


def _ephemere(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte, "flags": 64}}


def _messages_regles(gid: str) -> Dict[str, str]:
    """nom de règle -> le message que Discord montre au membre bloqué."""
    import verif_discord as v
    vu = _REGLES.get(gid)
    if vu and time.time() - vu[0] < REGLES_S:
        return vu[1]
    s, regles = v.api("GET", f"/guilds/{gid}/auto-moderation/rules", gid=gid)
    noms: Dict[str, str] = {}
    if s == 200 and isinstance(regles, list):
        for r in regles:
            for a in r.get("actions") or []:
                texte = ((a.get("metadata") or {}).get("custom_message") or "").strip()
                if a.get("type") == 1 and texte:
                    noms[str(r.get("name") or "")] = texte
    _REGLES[gid] = (time.time(), noms)
    return noms


def _entrees(gid: str, type_action: int) -> Tuple[int, List[Dict[str, Any]]]:
    import verif_discord as v
    s, data = v.api("GET", f"/guilds/{gid}/audit-logs", gid=gid,
                    params={"action_type": type_action, "limit": 50})
    if s != 200 or not isinstance(data, dict):
        return s, []
    return s, data.get("audit_log_entries") or []


def raison(gid: str, uid: str, quand: Optional[float] = None) -> str:
    """Pourquoi ce membre est suspendu, en deux ou trois lignes. Jamais vide :
    sans trace dans le journal, la carte le dit plutôt que de se taire."""
    gid, uid = str(gid), str(uid)
    quand = time.time() if quand is None else quand
    s_auto, auto = _entrees(gid, AUDIT_AUTOMOD)
    s_main, main = _entrees(gid, AUDIT_MEMBRE)
    candidats = []
    for e in auto:
        if str(e.get("target_id")) == uid:
            candidats.append((_date_id(e["id"]), "automod", e))
    for e in main:
        if str(e.get("target_id")) != uid:
            continue
        # une levée (nouvelle valeur vide) n'est pas une suspension
        if any(c.get("key") == "communication_disabled_until" and c.get("new_value")
               for c in e.get("changes") or []):
            candidats.append((_date_id(e["id"]), "staff", e))
    candidats = [c for c in candidats if quand - AVANT_S <= c[0] <= quand + APRES_S]
    if not candidats:
        if s_auto != 200 or s_main != 200:
            return f"❔ Raison illisible : journal d'audit refusé (HTTP {s_auto if s_auto != 200 else s_main})."
        return "❔ Raison introuvable dans le journal d'audit de Discord."
    _, origine, e = max(candidats, key=lambda c: c[0])
    if origine == "automod":
        o = e.get("options") or {}
        nom = o.get("auto_moderation_rule_name") or "?"
        lignes = [f"🛡️ **Raison** : AutoMod, règle « {nom} »"]
        message = _messages_regles(gid).get(nom)
        if message:
            lignes.append(f"> {message}")
        if o.get("channel_id"):
            lignes.append(f"💬 Salon : <#{o['channel_id']}>")
        return "\n".join(lignes)
    lignes = [f"👮 **Suspendu par** <@{e.get('user_id')}>"]
    lignes.append(f"**Raison** : {e['reason']}" if e.get("reason") else "Aucune raison donnée.")
    return "\n".join(lignes)


def composants(uid: str) -> List[Dict[str, Any]]:
    return [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "Lever la suspension",
         "custom_id": f"{PREFIXE}{uid}", "emoji": {"name": "▶️"}}]}]


def _fin(valeur: Any) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


def completer(corps: Dict[str, Any], gid: str) -> bool:
    """Ajoute la raison et le bouton à une carte ⏸️, juste avant son envoi.
    False (rien touché) pour tout autre message.

    La carte est reconnue à son titre et à son pied (« … • Suspension
    temporaire ») ; le membre et la fin sont relus dans son texte, que
    membres_evenements écrit « <@uid> · … Fin prévue : <t:…:F> »."""
    embeds = corps.get("embeds") if isinstance(corps, dict) else None
    if not embeds or not isinstance(embeds[0], dict) or corps.get("components"):
        return False
    e = embeds[0]
    if not (str(e.get("title") or "") == TITRE
            or str((e.get("footer") or {}).get("text") or "").endswith("• " + LIBELLE)):
        return False
    desc = str(e.get("description") or "")
    m = _RE_MEMBRE.search(desc)
    if not m:
        print("[suspension] carte ⏸️ sans membre lisible : envoyée sans raison ni bouton", flush=True)
        return False
    uid = m.group(1)
    e["description"] = (desc + "\n\n" + raison(gid, uid))[:MAX_DESCRIPTION]
    fin = _RE_FIN.search(desc)
    # une suspension déjà finie quand la carte part (bot redémarré) : rien à lever
    if not fin or int(fin.group(1)) > time.time():
        corps["components"] = composants(uid)
    return True


def brancher() -> bool:
    """Branche completer() sur l'envoi de membres_evenements.

    membres_evenements vit hors git sur le VPS : le retoucher là-bas ferait
    une copie que git ne voit pas, et qu'une retouche de Codex effacerait sans
    un mot. On enveloppe donc, d'ici, sa fonction REST (api, qu'il relit à
    chaque envoi) — comme _demarrages_proteges enveloppe déjà son observer."""
    import importlib.util
    try:
        if importlib.util.find_spec("membres_evenements") is None:
            return False                      # copie locale : pas de cartes à compléter
        import membres_evenements as me
    except Exception as e:
        print(f"[suspension] membres_evenements illisible ({type(e).__name__}) : "
              "cartes ⏸️ sans raison ni bouton", flush=True)
        return False
    origine = getattr(me, "api", None)
    if not callable(origine):
        print("[suspension] membres_evenements sans fonction api : cartes ⏸️ sans raison ni bouton",
              flush=True)
        return False
    if getattr(origine, "_suspensions", False):
        return True

    def api(g, methode, chemin, **kw):
        if methode == "POST" and str(chemin).endswith("/messages"):
            try:
                completer(kw.get("json"), str(g))
            except Exception as e:
                print(f"[suspension] carte ⏸️ envoyée sans raison ni bouton : {type(e).__name__}: {e}",
                      flush=True)
        return origine(g, methode, chemin, **kw)

    api._suspensions = True
    me.api = api
    print("[suspension] cartes ⏸️ de membres_evenements : raison et bouton branchés", flush=True)
    return True


def _lever(p: Dict[str, Any], gid: str, cible: str, qui: str) -> None:
    """Le travail du bouton, APRÈS la réponse à Discord (3 s au plus) : une
    limite de débit peut faire attendre l'appel REST plusieurs secondes."""
    import verif_discord as v
    message = p.get("message") or {}
    garder = message.get("components") or []
    s, membre = v.api("GET", f"/guilds/{gid}/members/{cible}", gid=gid)
    if s == 404:
        fait, reussi = "il a quitté le serveur, rien à lever", True
    elif s != 200:
        fait, reussi = f"échec (HTTP {s}), réessaie", False
    elif _fin((membre or {}).get("communication_disabled_until")) <= time.time():
        fait, reussi = "la suspension était déjà terminée", True
    else:
        s, _ = v.api("PATCH", f"/guilds/{gid}/members/{cible}", gid=gid,
                     json={"communication_disabled_until": None})
        reussi = s in (200, 204)
        fait = "▶️ suspension levée" if reussi else f"échec de la levée (HTTP {s}), réessaie"
    print(f"[suspension] {gid} : {cible} — {fait} (par {qui})", flush=True)
    embeds = message.get("embeds") or []
    if embeds:
        ligne = f"\n\n**{fait[0].upper() + fait[1:]}** par {qui} · <t:{int(time.time())}:R>"
        embeds[0]["description"] = ((embeds[0].get("description") or "") + ligne)[:MAX_DESCRIPTION]
    # en cas d'échec le bouton RESTE : sans lui, plus personne ne pourrait réessayer d'ici
    s_maj, _ = v.api("PATCH", f"/webhooks/{v.app_de_reponse(p, gid)}/{p.get('token')}/messages/@original",
                     gid=gid, json={"embeds": embeds, "components": [] if reussi else garder,
                                    "allowed_mentions": {"parse": []}})
    if s_maj != 200:
        print(f"[suspension] carte non mise à jour après « {fait} » sur {cible} : HTTP {s_maj}", flush=True)


def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Le clic sur ▶️ Lever la suspension. None si ce n'est pas ce bouton :
    l'appelant passe au module suivant."""
    p = p or {}
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if p.get("type") != 3 or not cid.startswith(PREFIXE):
        return None
    import verif_discord as v
    m = re.fullmatch(re.escape(PREFIXE) + r"(\d{5,25})", cid)
    gid = str(p.get("guild_id") or "")
    cfg = v.serveur(gid) if gid else None
    if not m or not cfg:
        return _ephemere("Action inconnue.")
    membre = p.get("member") or {}
    # Manager / Helper / admin, ou qui a le droit d'exclure temporairement :
    # c'est ce droit que Discord demande pour lever une suspension à la main.
    if not (v._est_manager(membre, cfg) or v._permissions(membre) & MODERER):
        return _ephemere("🔒 Réservé aux managers.")
    cible = m.group(1)
    qui = str((membre.get("user") or {}).get("username") or "?")[:40]
    verrou = f"{gid}:{cible}"
    with _VERROU:
        if verrou in _EN_COURS:
            return _ephemere("⏳ Déjà en cours pour ce membre.")
        _EN_COURS.add(verrou)

    def tache():
        try:
            _lever(p, gid, cible, qui)
        finally:
            _EN_COURS.discard(verrou)
    v._EN_FOND(tache)
    return {"type": 6}                    # « je m'en occupe » : la carte sera mise à jour
