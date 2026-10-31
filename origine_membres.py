"""origine_membres.py — par quel lien un membre est arrivé, pourquoi il est parti.

Propriétaire, 31/10/2026, devant les salons d'accueil de TRUST Threads :
- 👋・départs-et-sanctions disait « Son départ du serveur a été constaté » :
  « je sais pas s'il a quitté par lui-même, je sais pas si quelqu'un l'a
  viré, je sais pas c'est qui l'a viré » (l'exclusion de Rebo0t non plus ne
  disait pas qui) ;
- 🚪・arrivées-sur-le-serveur : « est-ce que c'est avec le lien officiel, ou
  est-ce que c'est avec un lien en commun ? … faudrait le lien
  d'affiliation, genre le lien qui dit lui est venu de la part de lui ».

Les cartes sont postées par des fichiers Codex hors git du VPS —
membres_evenements (départs des quatre serveurs, arrivées de Va IG),
threads_accueil et twitter_accueil (arrivées) — et par agency_accueil (git).
Comme suspensions_discord, ce module ne poste rien de lui-même : brancher()
enveloppe la fonction REST de chaque module hors git et complète la carte
juste avant son envoi ; agency_accueil appelle directement lignes_arrivee()
et motif_depart().

Départ : le journal d'audit (MEMBER_KICK, MEMBER_BAN_ADD) visant le membre
depuis sa dernière arrivée. Rien trouvé dans un journal lisible : parti de
lui-même. Journal refusé : la carte le dit, elle ne conclut rien.
membres_evenements attend déjà deux minutes, en relisant le journal à chaque
tour, avant de poser « départ » ; la carte le relit une dernière fois à
l'envoi.

Arrivée : le code d'invitation tel que Discord l'a noté pour ce membre — la
recherche de membres de la page « Membres » des paramètres du serveur
(source_invite_code, inviter_id), ouverte aux bots (vérifié le 31/10/2026 sur
les quatre serveurs). Le parrain reste celui du registre de parrainage du
serveur (le code perso de chaque parrain) : aucun deuxième registre. Discord
muet : comptage des invitations depuis le dernier relevé, et un résultat
ambigu est écrit tel quel (« plusieurs possibles », « inconnu »).
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

AUDIT_EXCLU = 20                  # MEMBER_KICK
AUDIT_BANNI = 22                  # MEMBER_BAN_ADD
ADMIN = 1 << 3
# Sans date d'arrivée connue, une exclusion plus vieille que ça n'est pas
# celle de ce départ (bot redémarré entre l'exclusion et le constat : 1 h de
# marge, comme suspensions_discord).
AVANT_S = 3600
APRES_S = 300
# Un membre arrivé à l'instant peut manquer à la recherche quelques secondes
RECHERCHE_ESSAIS = (0, 2, 4)
CACHE_S = 600
MAX_DESCRIPTION = 4096

# Ce qu'écrit membres_evenements (carte : titles, phrases, LABELS)
TITRES_DEPART = ("👋 Un membre a quitté le serveur", "🚫 Un membre a été exclu", "⛔ Un membre a été banni")
PHRASES_DEPART = ("Son départ du serveur a été constaté.",
                  "Discord confirme son exclusion du serveur.",
                  "Discord confirme son bannissement du serveur.")
LIBELLES_DEPART = ("Départ du serveur", "Membre exclu", "Membre banni", "Départ volontaire")
TITRE_ARRIVEE = "🚪 Nouvelle arrivée"
MARQUE_ARRIVEE = "🔗 **Lien**"
MARQUES_DEPART = ("🚶 **Parti de lui-même**", "👮 **Exclu par**", "👮 **Banni par**", "❔ **Parti, sans")
_RE_MEMBRE = re.compile(r"<@!?(\d{5,25})>")
_RE_INVITE_PAR = re.compile(r"\n?Invité par <@!?(\d+)>\.")

# join_source_type de la recherche de membres
SOURCES = {1: "ajouté par un bot", 2: "intégration", 3: "découverte de serveurs", 4: "hub étudiant",
           5: "invitation", 6: "lien personnalisé du serveur", 7: "demande d'adhésion acceptée"}

Api = Optional[Callable[..., Tuple[int, Any]]]
_CACHE: Dict[Tuple[str, str], Tuple[float, Any]] = {}
_VERROU = threading.Lock()


def _api(gid: str, api: Api, methode: str, chemin: str, **kw) -> Tuple[int, Any]:
    """`api` = la fonction REST du module appelant (agency_accueil._api, que
    ses tests remplacent) ; sans elle, verif_discord.api et le bot du serveur."""
    if api is not None:
        return api(methode, chemin, **kw)
    import verif_discord as v
    return v.api(methode, chemin, gid=str(gid), **kw)


def _date_id(snowflake: Any) -> float:
    return ((int(snowflake) >> 22) + 1420070400000) / 1000


def _date_iso(valeur: Any) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _cache(gid: str, cle: str, lire: Callable[[], Any]) -> Any:
    with _VERROU:
        vu = _CACHE.get((gid, cle))
        if vu and time.time() - vu[0] < CACHE_S:
            return vu[1]
    valeur = lire()
    if valeur is not None:
        with _VERROU:
            _CACHE[(gid, cle)] = (time.time(), valeur)
    return valeur


# ─── départs ──────────────────────────────────────────────────────────────
Journal = Tuple[int, List[Dict[str, Any]], Dict[str, Dict[str, Any]]]


def journal(gid: str, api: Api = None) -> Journal:
    """(HTTP, entrées d'exclusion et de bannissement, {id: utilisateur}).
    Deux lectures filtrées par type : sur Twitter, les rôles posés par les
    bots remplissent vite les 100 dernières entrées tous types confondus."""
    entrees: List[Dict[str, Any]] = []
    gens: Dict[str, Dict[str, Any]] = {}
    for type_action in (AUDIT_EXCLU, AUDIT_BANNI):
        s, data = _api(gid, api, "GET", f"/guilds/{gid}/audit-logs",
                       params={"action_type": type_action, "limit": 100})
        if s != 200 or not isinstance(data, dict):
            return s, [], {}
        entrees.extend(e for e in data.get("audit_log_entries") or [] if isinstance(e, dict))
        gens.update({str(u.get("id")): u for u in data.get("users") or [] if isinstance(u, dict)})
    return 200, entrees, gens


def motif_depart(gid: str, uid: str, arrivee: Any = None, vu: Optional[float] = None,
                 lu: Optional[Journal] = None, api: Api = None) -> Dict[str, Any]:
    """Pourquoi `uid` a quitté `gid` : {kind: depart|exclu|banni, lu, http,
    auteur, auteur_nom, auteur_bot, raison}. `arrivee` = sa dernière date
    d'arrivée (ISO ou horodatage) : une exclusion postérieure est forcément
    celle de ce départ. Inconnue : une heure avant `vu`, le constat."""
    uid = str(uid)
    vu = time.time() if vu is None else float(vu)
    debut = _date_iso(arrivee) if isinstance(arrivee, str) else float(arrivee or 0)
    if not debut:
        debut = vu - AVANT_S
    s, entrees, gens = lu if lu is not None else journal(gid, api)
    if s != 200:
        return {"kind": "depart", "lu": False, "http": s}
    trouvees = [e for e in entrees
                if str(e.get("target_id")) == uid and e.get("action_type") in (AUDIT_EXCLU, AUDIT_BANNI)
                and debut - 5 <= _date_id(e["id"]) <= vu + APRES_S]
    if not trouvees:
        return {"kind": "depart", "lu": True, "http": 200}
    # exclu puis banni (ou l'inverse) : le dernier geste compte
    e = max(trouvees, key=lambda x: _date_id(x["id"]))
    auteur = str(e.get("user_id") or "")
    u = gens.get(auteur) or {}
    return {"kind": "exclu" if e.get("action_type") == AUDIT_EXCLU else "banni", "lu": True, "http": 200,
            "auteur": auteur, "auteur_nom": str(u.get("username") or ""), "auteur_bot": bool(u.get("bot")),
            "raison": str(e.get("reason") or "").strip(), "quand": _date_id(e["id"])}


def texte_depart(m: Dict[str, Any]) -> Dict[str, str]:
    """{titre, libelle, texte} d'une carte de départ pour le motif `m`."""
    kind = m.get("kind")
    if kind in ("exclu", "banni"):
        qui = f"<@{m['auteur']}>" if m.get("auteur") else "quelqu'un"
        if m.get("auteur_nom"):
            qui += f" · `@{m['auteur_nom']}`" + (" (bot)" if m.get("auteur_bot") else "")
        texte = (f"👮 **{'Exclu' if kind == 'exclu' else 'Banni'} par** {qui}\n"
                 + (f"**Raison** : {m['raison'][:900]}" if m.get("raison") else "Aucune raison donnée."))
        if kind == "exclu":
            return {"titre": "🚫 Un membre a été exclu", "libelle": "Membre exclu", "texte": texte}
        return {"titre": "⛔ Un membre a été banni", "libelle": "Membre banni", "texte": texte}
    if m.get("lu"):
        return {"titre": "👋 Un membre est parti de lui-même", "libelle": "Départ volontaire",
                "texte": "🚶 **Parti de lui-même** : ni exclusion ni bannissement dans le journal d'audit."}
    return {"titre": "👋 Un membre a quitté le serveur", "libelle": "Départ du serveur",
            "texte": (f"❔ **Parti, sans savoir comment** : journal d'audit refusé (HTTP {m.get('http')}), "
                      "impossible de dire s'il est parti seul ou s'il a été exclu.")}


def habiller_depart(e: Dict[str, Any], motif: Dict[str, Any]) -> Dict[str, Any]:
    """Titre, texte, pied et nom de la carte `e` selon `motif` (sur place)."""
    t = texte_depart(motif)
    desc = str(e.get("description") or "")
    for phrase in PHRASES_DEPART:
        if phrase in desc:
            desc = desc.replace(phrase, t["texte"])
            break
    else:
        desc = desc.rstrip() + "\n\n" + t["texte"]
    e["title"] = t["titre"]
    e["description"] = desc[:MAX_DESCRIPTION]
    for cle, champ in (("footer", "text"), ("author", "name")):
        bloc = e.get(cle)
        if isinstance(bloc, dict) and isinstance(bloc.get(champ), str):
            avant, sep, apres = bloc[champ].rpartition(" • ")
            if sep and apres in LIBELLES_DEPART:
                bloc[champ] = f"{avant} • {t['libelle']}"
    return e


def _arrivee_connue(gid: str, uid: str) -> Any:
    """La date d'arrivée du partant, relue dans l'état de membres_evenements
    (la carte ne porte que la date du constat)."""
    try:
        import membres_evenements as me
        etat = (me.lire() or {}).get(str(gid)) or {}
    except Exception:                                        # noqa: BLE001
        return None
    for e in sorted((etat.get("events") or {}).values(), key=lambda x: -float(x.get("date") or 0)):
        m = e.get("member") or {}
        if str((m.get("user") or {}).get("id")) == str(uid) and e.get("kind") in ("depart", "exclu", "banni"):
            return m.get("joined_at")
    return None


def completer_depart(corps: Any, gid: str) -> bool:
    """Le motif du départ sur une carte 👋 / 🚫 / ⛔ de membres_evenements,
    juste avant son envoi. False (rien touché) pour tout autre message."""
    embeds = corps.get("embeds") if isinstance(corps, dict) else None
    if not embeds or not isinstance(embeds[0], dict):
        return False
    e = embeds[0]
    if str(e.get("title") or "") not in TITRES_DEPART:
        return False
    desc = str(e.get("description") or "")
    if any(x in desc for x in MARQUES_DEPART):
        return False
    m = _RE_MEMBRE.search(desc)
    if not m:
        print("[origine] carte de départ sans membre lisible : envoyée sans motif", flush=True)
        return False
    uid = m.group(1)
    motif = motif_depart(gid, uid, _arrivee_connue(gid, uid), _date_iso(e.get("timestamp")) or None)
    habiller_depart(e, motif)
    return True


# ─── arrivées ─────────────────────────────────────────────────────────────
def source_discord(gid: str, uid: str, api: Api = None) -> Optional[Dict[str, Any]]:
    """{code, type, inviteur} tel que Discord l'a noté à l'arrivée de `uid` ;
    None s'il ne le dit pas (pas encore indexé, refus, source non précisée)."""
    corps = {"limit": 1, "and_query": {"user_id": {"or_query": [str(uid)]}}}
    s = 0
    for attente in RECHERCHE_ESSAIS:
        if attente:
            time.sleep(attente)
        s, rep = _api(gid, api, "POST", f"/guilds/{gid}/members-search", json=corps)
        if s == 200 and isinstance(rep, dict):
            for r in rep.get("members") or []:
                if str(((r.get("member") or {}).get("user") or {}).get("id")) != str(uid):
                    continue
                src = {"code": str(r.get("source_invite_code") or ""), "type": r.get("join_source_type"),
                       "inviteur": str(r.get("inviter_id") or "")}
                # type 0 sans code : Discord ne sait pas — le comptage prend le relais
                if src["code"] or src["type"] not in (0, None):
                    return src
                s = "source non précisée"
                break
            else:
                continue                           # pas encore indexé : on réessaie
            break
        if s in (401, 403, 404):
            break                                  # refus : réessayer n'y changera rien
    print(f"[origine] {gid} : source d'arrivée de {uid} non donnée par Discord ({s}) : comptage des invitations",
          flush=True)
    return None


def invitations(gid: str, api: Api = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """{code: invitation} en cours sur le serveur (inviteur, salon, usages)."""
    s, rows = _api(gid, api, "GET", f"/guilds/{gid}/invites")
    if s != 200 or not isinstance(rows, list):
        return None
    return {str(r["code"]): r for r in rows if isinstance(r, dict) and r.get("code")}


def _serveur(gid: str, api: Api) -> Dict[str, Any]:
    """{owner, staff (rôles Manager, Helper, Administrateur), vanity}."""
    def lire():
        s, g = _api(gid, api, "GET", f"/guilds/{gid}")
        if s != 200 or not isinstance(g, dict):
            return None
        import tickets_discord
        import verif_discord as v
        staff = {str(r.get("id")) for r in g.get("roles") or []
                 if isinstance(r, dict) and (int(r.get("permissions") or 0) & ADMIN or tickets_discord._est_helper(r))}
        staff.add(str((v.serveur(gid) or {}).get("role_manager") or ""))
        staff -= {"", str(gid)}
        return {"owner": str(g.get("owner_id") or ""), "staff": staff, "vanity": str(g.get("vanity_url_code") or "")}
    return _cache(gid, "serveur", lire) or {"owner": "", "staff": set(), "vanity": ""}


def _qui(gid: str, uid: str, api: Api) -> Dict[str, Any]:
    """{nom, bot, staff} de l'auteur d'une invitation."""
    def lire():
        s, m = _api(gid, api, "GET", f"/guilds/{gid}/members/{uid}")
        if s == 200 and isinstance(m, dict):
            srv = _serveur(gid, api)
            u = m.get("user") or {}
            return {"nom": str(u.get("username") or ""), "bot": bool(u.get("bot")),
                    "staff": uid == srv["owner"] or bool(srv["staff"] & set(m.get("roles") or []))}
        s, u = _api(gid, api, "GET", f"/users/{uid}")
        u = u if s == 200 and isinstance(u, dict) else {}
        return {"nom": str(u.get("username") or ""), "bot": bool(u.get("bot")), "staff": False}
    return _cache(gid, "qui:" + str(uid), lire) or {"nom": "", "bot": False, "staff": False}


def _decrire_code(gid: str, code: str, inviteur: str, parrains: Dict[str, str],
                  invits: Optional[Dict[str, Dict[str, Any]]], api: Api) -> str:
    """Une ligne : ce lien-là, et de la part de qui."""
    if code in parrains:
        return f"🤝 **De la part de** <@{parrains[code]}> : son lien de parrainage `{code}`"
    if code == _serveur(gid, api)["vanity"]:
        return f"🏷️ Lien officiel du serveur `{code}` · aucun parrain"
    inv = (invits or {}).get(code) or {}
    salon = str((inv.get("channel") or {}).get("id") or "")
    ou = f" dans <#{salon}>" if salon else ""
    inviteur = inviteur or str((inv.get("inviter") or {}).get("id") or "")
    if not inviteur:
        return f"`{code}`, auteur inconnu · hors parrainage, aucun parrain"
    q = _qui(gid, inviteur, api)
    nom = f" · `@{q['nom']}`" if q.get("nom") else ""
    if q.get("bot"):
        return f"🤖 Lien `{code}` créé par le bot{ou} · inconnu du parrainage, aucun parrain"
    if q.get("staff"):
        return f"🛡️ Lien du staff `{code}`, créé par <@{inviteur}>{nom}{ou} · aucun parrain"
    return f"👥 Lien de <@{inviteur}>{nom} `{code}`{ou} · hors parrainage, aucun parrain enregistré"


def lignes_arrivee(gid: str, uid: str, liens: Dict[str, Any], parrain: Optional[str] = None,
                   parrain_vu: bool = False, usages_avant: Optional[Dict[str, int]] = None,
                   api: Api = None) -> str:
    """Les lignes « 🔗 Lien » d'une carte d'arrivée (commencent par un saut de
    ligne). `liens` = le registre de parrainage du serveur ({uid: {code}}) ;
    `parrain` = celui que ce registre a noté pour `uid`, `parrain_vu` = le
    registre a déjà traité son arrivée ; `usages_avant` = le dernier comptage
    des invitations (secours quand Discord ne donne pas la source)."""
    gid, uid = str(gid), str(uid)
    parrains = {str(f.get("code")): str(u) for u, f in (liens or {}).items()
                if isinstance(f, dict) and f.get("code")}
    src = source_discord(gid, uid, api)
    invits = invitations(gid, api)
    lignes: List[str] = []
    code = ""
    if src and src.get("code"):
        code = src["code"]
        demande = " (demande d'adhésion acceptée)" if src.get("type") == 7 else ""
        lignes.append(f"{MARQUE_ARRIVEE} : " + _decrire_code(gid, code, src.get("inviteur", ""),
                                                           parrains, invits, api) + demande)
    elif src:
        lignes.append(f"{MARQUE_ARRIVEE} : aucun, arrivé sans invitation "
                      f"({SOURCES.get(src.get('type'), 'source ' + str(src.get('type')))})")
    else:
        # les invitations dont le compteur a monté depuis le dernier relevé :
        # une seule, probable ; plusieurs, toutes, telles quelles
        montees = []
        if usages_avant is not None and invits is not None:
            montees = sorted(c for c, i in invits.items()
                             if int(i.get("uses") or 0) > int(usages_avant.get(c, 0) or 0))
        if len(montees) == 1:
            lignes.append(f"{MARQUE_ARRIVEE} probable (comptage des invitations) : "
                          + _decrire_code(gid, montees[0], "", parrains, invits, api))
        elif montees:
            lignes.append(f"{MARQUE_ARRIVEE} : plusieurs possibles, "
                          + ", ".join(f"`{c}`" + (f" (parrainage de <@{parrains[c]}>)" if c in parrains else "")
                                      for c in montees[:5]))
        else:
            lignes.append(f"{MARQUE_ARRIVEE} inconnu : Discord ne l'a pas donné et le comptage des "
                          "invitations ne tranche pas.")
    p_code = parrains.get(code)
    if parrain and p_code and str(parrain) != p_code:
        lignes.append(f"⚠️ Le parrainage a noté <@{parrain}> : origine à vérifier.")
    elif parrain and not p_code:
        lignes.append(f"🤝 Parrain noté par le parrainage : <@{parrain}>.")
    elif p_code and parrain_vu and not parrain:
        lignes.append("⚠️ Pas compté dans son parrainage (comptage ambigu) : à confirmer.")
    return "\n" + "\n".join(lignes)


# Registre de parrainage de chaque serveur, le même que lit
# affiliation_sources.source (VPS). Module absent (copie locale) : None.
def _registre(gid: str) -> Optional[Dict[str, Any]]:
    import importlib
    import importlib.util
    import verif_discord as v
    nom = {v.THREADS_ID: "threads_accueil", v.TWITTER_ID: "twitter_accueil",
           v.VA_IG_ID: "instagram_accueil"}.get(str(gid))
    try:
        if nom and importlib.util.find_spec(nom) is not None:
            return importlib.import_module(nom).lire() or {}
        if str(gid) == v.AGENCY_IG_ID:
            import agency_accueil
            return agency_accueil.registre()
    except Exception as e:                                   # noqa: BLE001
        print(f"[origine] registre de parrainage de {gid} illisible : {type(e).__name__}", flush=True)
    return None


def completer_arrivee(corps: Any, gid: str) -> bool:
    """Les lignes « 🔗 Lien » sur une carte 🚪 Nouvelle arrivée, juste avant
    son envoi ; la ligne « Invité par » qu'elles reprennent disparaît."""
    embeds = corps.get("embeds") if isinstance(corps, dict) else None
    if not embeds or not isinstance(embeds[0], dict):
        return False
    e = embeds[0]
    if not str(e.get("title") or "").startswith(TITRE_ARRIVEE):
        return False
    desc = str(e.get("description") or "")
    if MARQUE_ARRIVEE in desc:
        return False
    m = _RE_MEMBRE.search(desc)
    if not m:
        print("[origine] carte d'arrivée sans membre lisible : envoyée sans lien", flush=True)
        return False
    uid = m.group(1)
    reg = _registre(gid)
    filleuls = (reg or {}).get("filleuls") or {}
    # « Invité par » = ce que le registre a décidé à ce tour même : twitter_accueil
    # poste la carte avant d'écrire son fichier
    invite_par = _RE_INVITE_PAR.search(desc)
    parrain = invite_par.group(1) if invite_par else (filleuls.get(uid) or {}).get("parrain")
    lignes = lignes_arrivee(gid, uid, (reg or {}).get("liens") or {}, parrain,
                            bool(invite_par) or uid in filleuls,
                            (reg or {}).get("invite_uses") if reg is not None else None)
    if reg is None:
        lignes += "\n❔ Registre de parrainage illisible : parrain non vérifié."
    e["description"] = (_RE_INVITE_PAR.sub("", desc).rstrip() + lignes)[:MAX_DESCRIPTION]
    return True


def completer(corps: Any, gid: str) -> bool:
    return completer_depart(corps, gid) or completer_arrivee(corps, gid)


# ─── branchement sur les modules hors git ─────────────────────────────────
def _envelopper(nom: str, avec_gid: bool) -> bool:
    import importlib
    import importlib.util
    try:
        if importlib.util.find_spec(nom) is None:
            return False                      # copie locale : pas de cartes à compléter
        mod = importlib.import_module(nom)
    except Exception as e:                                   # noqa: BLE001
        print(f"[origine] {nom} illisible ({type(e).__name__}) : cartes sans lien ni motif", flush=True)
        return False
    origine = getattr(mod, "api", None)
    if not callable(origine):
        print(f"[origine] {nom} sans fonction api : cartes sans lien ni motif", flush=True)
        return False
    if getattr(origine, "_origines", False):
        return True
    gid_fixe = str(getattr(mod, "GID", "") or "")

    def api(*a, **kw):
        # membres_evenements.api(g, methode, chemin) ; les accueils api(methode, chemin)
        g, methode, chemin = (str(a[0]), a[1], a[2]) if avec_gid else (gid_fixe, a[0], a[1])
        if methode == "POST" and str(chemin).endswith("/messages") and g:
            try:
                completer(kw.get("json"), g)
            except Exception as e:                           # noqa: BLE001
                print(f"[origine] carte envoyée sans lien ni motif : {type(e).__name__}: {e}", flush=True)
        return origine(*a, **kw)

    api._origines = True
    mod.api = api
    return True


def brancher() -> Dict[str, bool]:
    """Enveloppe la fonction REST des modules hors git qui postent les cartes
    (ils la relisent à chaque envoi), comme suspensions_discord.brancher :
    les retoucher sur le VPS ferait une copie que git ne voit pas, et qu'une
    retouche de Codex effacerait sans un mot."""
    fait = {"membres_evenements": _envelopper("membres_evenements", True),
            "threads_accueil": _envelopper("threads_accueil", False),
            "twitter_accueil": _envelopper("twitter_accueil", False)}
    branches = [n for n, ok in fait.items() if ok]
    if branches:
        print(f"[origine] liens d'arrivée et motifs de départ branchés : {', '.join(branches)}", flush=True)
    return fait
