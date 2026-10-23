"""agency_accueil.py — Agency VA INSTAGRAM : arrivées, départs, parrainage,
panneau « Se vérifier ».

Propriétaire, 23/10/2026 : « branche les arrivées et la vérification », puis
« il manque parrainage avec la création et tout, et le suivi avec le lien pour
le tracking pour les recruteurs ». Comme twitter_accueil (fichier du VPS, hors
git) :

- chaque membre a SON invitation Discord, permanente, créée sur
  🔐・vérification (lien_pour) ;
- le parrain d'un arrivé se lit à la différence d'usage des invitations entre
  deux relevés : une seule invitation a servi, autant de fois qu'il y a
  d'arrivés → son propriétaire est le parrain. Sinon l'origine reste « à
  confirmer » : rien n'est deviné ;
- le bouton du panneau de 🤝・parrainage (posé par Wario) donne en privé
  l'adresse de son espace sur youl4b.com (affiliation_site, VPS) : son lien,
  son parrain, ses filleuls et leurs subs (primes à 10 et 200 subs, payées à
  la main).

Un membre neuf est annoncé dans 🚪・arrivées-sur-le-serveur (avec son parrain),
un membre parti dans 👋・départs-et-sanctions. Au premier passage, les membres
déjà là sont notés SANS annonce : 160 « nouvelle arrivée » d'un coup
n'apprendraient rien à personne.

C'est le SEUL relevé des membres d'Agency, dans son propre fil, chaque minute
(demarrer) — il tournait avant dans le tour des tickets, toutes les dix
minutes : deux arrivées par deux liens dans la même fenêtre, et aucune des
deux n'était attribuée.

Le panneau « Se vérifier » de 🔐・vérification est posé par Wario (le clic va
à l'application qui a posté le message) : verif_discord.assurer_message_verif,
qui ne fait rien quand il est déjà là.

Une liste des membres ou des invitations illisible (403, panne) : rien n'est
annoncé ni oublié, c'est dit, le tour suivant réessaie.
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

GID = "1488331963575177247"                      # Agency VA INSTAGRAM
SALON_ARRIVEES = "1562974536662523954"           # 🚪・arrivées-sur-le-serveur
SALON_DEPARTS = "1562974549157351474"            # 👋・départs-et-sanctions
SALON_VERIF = "1562974555423776848"              # 🔐・vérification
SALON_VERIFIES = "1562974542953975978"           # ✅・membres-vérifiés
SALON_PARRAINAGE = "1531696385420820540"         # 🤝・parrainage
# la carte de bienvenue : les premiers pas, comme celle de Twitter
# (entretien_visuel.EQUIPES, fichier du VPS hors git)
SALON_FORMATION = "1531698896454287390"          # 🎓・formation
SALON_PAIEMENTS = "1531696033116065963"          # 💳・paiements
SALON_DISCUSSIONS = "1531703501296504962"        # 💬・discussions
DATA_DIR = Path(__file__).resolve().parent / "data"
FICHIER = DATA_DIR / "agency_accueil.json"
#: au plus autant d'annonces par tour : un afflux (ou une liste à moitié
#: lue) ne doit pas noyer le salon ; le reste part au tour suivant
MAX_ANNONCES = 20
#: le panneau est revérifié au plus une fois l'heure (un GET de 20 messages)
PANNEAU_S = 3600
#: un relevé par minute, comme Twitter : plus espacé, deux arrivées par deux
#: liens tombent dans la même fenêtre et aucune n'est attribuée
PERIODE_S = 60
#: l'historique (rattraper) : au plus autant de messages par tour, pour ne
#: pas retenir le relevé plusieurs minutes d'affilée
RATTRAPAGE_PAR_TOUR = 40
#: l'affiche de Twitter (Mario, « 0,50 $ à 10 subs, 10 $ à 200 subs ») :
#: aucune mention de serveur, servie par affiliation_site
AFFICHE = "https://youl4b.com/affiliation/affiche.png"

LOCK = threading.RLock()
_TOUR = threading.Lock()
_DEMARRE = False
_DIT: Dict[str, str] = {}


def _api(methode: str, chemin: str, **kw):
    import verif_discord as vd
    return vd.api(methode, chemin, gid=GID, **kw)


def _dire(cle: str, texte: str) -> None:
    """Une panne qui dure ne s'imprime qu'une fois (un tour par minute) ;
    texte vide = rétabli."""
    if _DIT.get(cle, "") != texte:
        _DIT[cle] = texte
        if texte:
            print(f"[agency] {texte}", flush=True)


def _etat() -> Dict[str, Any]:
    try:
        d = safe_json.load(FICHIER, default={}) or {}
    except Exception:                                        # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write(FICHIER, d)


def registre() -> Dict[str, Any]:
    """L'état entier : liens (invitations), filleuls, membres. Lu par la page
    d'administration du parrainage (affiliation_sources, VPS)."""
    with LOCK:
        return _etat()


def membres() -> Optional[Dict[str, Dict[str, Any]]]:
    """{uid : membre} sans les bots, toutes pages lues ; None si Discord ne
    rend pas la liste entière."""
    out: Dict[str, Dict[str, Any]] = {}
    apres = ""
    for _ in range(50):
        code, part = _api("GET", f"/guilds/{GID}/members?limit=1000" + (f"&after={apres}" if apres else ""))
        if code != 200 or not isinstance(part, list):
            _dire("membres", f"liste des membres illisible (HTTP {code})")
            return None
        out.update({str(m["user"]["id"]): m for m in part
                    if isinstance(m, dict) and not (m.get("user") or {}).get("bot")})
        if len(part) < 1000:
            _dire("membres", "")
            return out
        apres = str(max(int(m["user"]["id"]) for m in part))
    return None


def invitations() -> Optional[Dict[str, int]]:
    """{code : nombre d'usages} de toutes les invitations du serveur."""
    code, rows = _api("GET", f"/guilds/{GID}/invites")
    if code != 200 or not isinstance(rows, list):
        _dire("invitations", f"invitations illisibles (HTTP {code}) : parrains non relevés")
        return None
    _dire("invitations", "")
    return {str(r["code"]): int(r.get("uses") or 0)
            for r in rows if isinstance(r, dict) and r.get("code")}


def candidats(avant: Optional[Dict[str, int]], apres: Dict[str, int],
              liens: Dict[str, Dict[str, Any]], nouveaux: int) -> Optional[str]:
    """Le parrain des `nouveaux` arrivés de ce tour, ou None. Une seule
    invitation a servi, et autant de fois qu'il y a d'arrivés (la règle de
    threads_accueil.candidats, VPS). Deux liens dans le même tour, une
    invitation qui n'est à personne : None, l'origine reste à confirmer."""
    if avant is None or apres is None or not nouveaux:
        return None
    deltas = {c: n - avant.get(c, 0) for c, n in apres.items() if n > avant.get(c, 0)}
    if len(deltas) != 1:
        return None
    code, n = next(iter(deltas.items()))
    if n != nouveaux:
        return None
    return next((uid for uid, f in liens.items() if (f or {}).get("code") == code), None)


def lien_pour(uid: str) -> str:
    """L'invitation personnelle de `uid` (https://discord.gg/…), créée au
    premier appel : permanente, sans limite d'usage, unique à lui."""
    uid = str(uid)
    with LOCK:
        d = _etat()
        liens = d.setdefault("liens", {})
        if (liens.get(uid) or {}).get("code"):
            return "https://discord.gg/" + liens[uid]["code"]
        code, rep = _api("POST", f"/channels/{SALON_VERIF}/invites",
                         json={"max_age": 0, "max_uses": 0, "unique": True})
        if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("code"):
            raise RuntimeError(f"invitation Agency refusée (HTTP {code})")
        liens[uid] = {"code": str(rep["code"]), "date": time.time()}
        _ecrire(d)
        return "https://discord.gg/" + liens[uid]["code"]


def parrain_de(uid: str) -> str:
    """Le parrain enregistré de `uid` ("" si aucun) — la bienvenue des
    vérifiés le remercie (verif_discord.poster_bienvenue)."""
    with LOCK:
        f = (_etat().get("filleuls") or {}).get(str(uid)) or {}
    return str(f.get("parrain") or "")


def _poster(salon: str, embed: Dict[str, Any], cle: str, mention: str = "") -> str:
    """Sans mention, sauf `mention` (le membre accueilli, comme Twitter)."""
    nonce = hashlib.sha256(cle.encode()).hexdigest()[:24]
    corps = {"embeds": [embed], "allowed_mentions": {"parse": []}, "nonce": nonce, "enforce_nonce": True}
    if mention:
        corps["content"] = f"<@{mention}>"
        corps["allowed_mentions"]["users"] = [mention]
    code, rep = _api("POST", f"/channels/{salon}/messages", json=corps)
    return str(rep.get("id") or "") if code in (200, 201) and isinstance(rep, dict) else ""


def _nom(m: Dict[str, Any]) -> str:
    """Le pseudo Discord (username), qui retrouve quelqu'un ; "" inconnu."""
    u = m.get("user") or {}
    return str(u.get("username") or m.get("nick") or u.get("global_name") or "")


def _date(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(str(iso or "")) >= 10 else "?"


# ─── les cartes, comme Twitter (entretien_visuel.appliquer) ──────────────
# Propriétaire, 23/10/2026, devant l'historique posté : « il n'y a pas les
# cartes et tout comme dans Twitter » — le nom et la photo du membre en tête,
# et pour la bienvenue ses premiers pas.
def _avatar(uid: str, m: Dict[str, Any]) -> str:
    u = m.get("user") or {}
    if m.get("avatar"):
        a = str(m["avatar"])
        return (f"https://cdn.discordapp.com/guilds/{GID}/users/{uid}/avatars/{a}."
                f"{'gif' if a.startswith('a_') else 'png'}?size=256")
    if u.get("avatar"):
        a = str(u["avatar"])
        return f"https://cdn.discordapp.com/avatars/{uid}/{a}.{'gif' if a.startswith('a_') else 'png'}?size=256"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(uid) >> 22) % 6}.png"


def _carte(embed: Dict[str, Any], uid: str, m: Dict[str, Any], verifie: bool) -> Dict[str, Any]:
    # le nom affiché sur le serveur, comme la carte de Twitter (le pseudo de
    # _nom sert à retrouver quelqu'un, pas à l'accueillir)
    u = (m or {}).get("user") or {}
    nom = str((m or {}).get("nick") or u.get("global_name") or u.get("username") or "Nouveau membre")
    url = _avatar(uid, m or {})
    embed["author"] = {"name": nom + (" • Membre vérifié" if verifie else " • Nouvelle arrivée"),
                       "icon_url": url, "url": f"https://discord.com/users/{uid}"}
    embed["thumbnail"] = {"url": url}
    return embed


def embed_arrivee(uid: str, m: Dict[str, Any], verifie: bool, historique: bool,
                  parrain: Optional[str] = None) -> Dict[str, Any]:
    quand = (f"a rejoint le serveur le {_date(m.get('joined_at'))}." if historique
             else "vient de rejoindre le serveur.")
    etat = ("✅ Vérification validée." if verifie else
            f"⏳ **Pas encore vérifié.** La vérification se fait dans <#{SALON_VERIF}>.")
    return _carte({"title": "🚪 " + ("Arrivée" if historique else "Nouvelle arrivée")
                            + " sur Agency VA INSTAGRAM",
                   "description": f"<@{uid}> {quand}\n{etat}" + (f"\nInvité par <@{parrain}>." if parrain else ""),
                   "color": 0x5865F2,
                   "footer": {"text": "Agency VA INSTAGRAM • Arrivées sur le serveur"}},
                  uid, m, verifie)


def embed_bienvenue(uid: str, m: Dict[str, Any], parrain: str = "") -> Dict[str, Any]:
    return _carte({
        "title": "✨ Bienvenue dans l’équipe YouLab Agency !",
        "description": (f"<@{uid}>, ta vérification est validée.\n**Tu peux commencer avec ton équipe.**"
                        + (f"\n\n🙏 Merci <@{parrain}> de l’avoir invité !" if parrain else "")),
        "color": 0x34C759,
        "fields": [
            {"name": "🧭 TES PREMIERS PAS",
             "value": (f"**01** · Ta formation → <#{SALON_FORMATION}>\n"
                       f"**02** · Ta rémunération → <#{SALON_PAIEMENTS}>\n"
                       f"**03** · Échanger avec l’équipe → <#{SALON_DISCUSSIONS}>"), "inline": False},
            {"name": "🔒 TON ESPACE PERSONNEL",
             "value": ("Ton lien de parrainage et le suivi de tes filleuls sont accessibles depuis "
                       f"**Mon espace personnel** dans <#{SALON_PARRAINAGE}>."), "inline": False}],
        "footer": {"text": "YouLab Agency • Vérification validée ✓"}}, uid, m, True)


def _bienvenue_faite(d: Dict[str, Any], uid: str, joined_at: str) -> str:
    """Le message de bienvenue déjà posté pour ce passage de `uid` (« »
    sinon). Deux registres : le membre noté par le relevé, et les bienvenues
    postées avant que le relevé ne l'ait vu — la vérification d'un arrivé de
    la minute passe avant lui, et sans ce second registre sa note d'arrivée
    effaçait la bienvenue (puis le tour la reposait)."""
    f = (d.get("membres") or {}).get(uid) or {}
    if f.get("bienvenue") and (f.get("joined_at") or "") in ("", joined_at or ""):
        return str(f["bienvenue"])
    b = (d.get("bienvenues") or {}).get(uid) or {}
    return str(b.get("message") or "") if (b.get("joined_at") or "") == (joined_at or "") else ""


def bienvenue(uid: str, m: Optional[Dict[str, Any]] = None) -> str:
    """La carte de bienvenue d'un membre qui vient d'être vérifié, dans
    ✅・membres-vérifiés, le membre mentionné et son parrain remercié (comme
    Twitter). Une fois par passage sur le serveur ; rend l'identifiant du
    message (« » si déjà faite ou refusée). Appelée par la vérification
    (verif_discord.poster_bienvenue) et par le relevé, pour un ✅ Vérifié
    posé à la main."""
    uid = str(uid)
    if m is None:
        code, m = _api("GET", f"/guilds/{GID}/members/{uid}")
        m = m if code == 200 and isinstance(m, dict) else {}
    ja = str(m.get("joined_at") or "")
    with LOCK:
        if _bienvenue_faite(_etat(), uid, ja):
            return ""
    # le message hors du verrou (un clic sur « Mon espace » n'attend pas
    # Discord) ; deux appels en même temps : le nonce n'en garde qu'un
    mid = _poster(SALON_VERIFIES, embed_bienvenue(uid, m, parrain_de(uid)),
                  f"{GID}:{uid}:{ja}:verifie", mention=uid)
    if mid:
        with LOCK:
            d = _etat()
            d.setdefault("bienvenues", {})[uid] = {"message": mid, "joined_at": ja, "date": int(time.time())}
            f = (d.get("membres") or {}).get(uid)
            if f is not None and (f.get("joined_at") or "") == ja:
                f["bienvenue"] = mid
                f["carte"] = 1
            _ecrire(d)
    return mid


def rattraper(actuels: Dict[str, Dict[str, Any]], role_verifie: str) -> int:
    """L'historique, une fois : propriétaire, 23/10/2026, devant la première
    arrivée annoncée : « remets les mecs ici et tout » — comme sur Twitter, où
    chaque membre a sa ligne. Chaque membre déjà là reçoit la sienne dans
    🚪・arrivées (date d'arrivée, vérifié ou non), dans l'ordre d'arrivée, et
    chaque vérifié sa bienvenue dans ✅・membres-vérifiés. Sans mention : ces
    gens sont là depuis des semaines. Les arrivés du relevé (« neuf ») ont
    déjà leur annonce, et leur bienvenue vient de la vérification : pas eux.
    RATTRAPAGE_PAR_TOUR messages par tour ; rend le nombre posté. Fini quand
    il n'y a plus rien à poster (« rattrape »)."""
    with LOCK:
        d = _etat()
        if d.get("rattrape"):
            return 0
        connus = d.get("membres") or {}
        a_faire = []
        for uid, m in sorted(actuels.items(), key=lambda kv: str(kv[1].get("joined_at") or "")):
            f = connus.get(uid)
            if f is None or f.get("neuf") or f.get("a_annoncer"):
                continue
            verifie = bool(role_verifie and role_verifie in (m.get("roles") or []))
            if not f.get("arrivee"):
                a_faire.append((uid, m, "arrivee", verifie))
            if verifie and not _bienvenue_faite(d, uid, m.get("joined_at") or ""):
                a_faire.append((uid, m, "bienvenue", verifie))
    n = 0
    for uid, m, quoi, verifie in a_faire[:RATTRAPAGE_PAR_TOUR]:
        if quoi == "arrivee":
            salon, cle = SALON_ARRIVEES, f"{GID}:{uid}:{m.get('joined_at')}:arrivee"
            embed = embed_arrivee(uid, m, verifie, historique=True)
        else:
            salon, cle = SALON_VERIFIES, f"{GID}:{uid}:{m.get('joined_at')}:verifie"
            embed = embed_bienvenue(uid, m)
        mid = _poster(salon, embed, cle)
        if not mid:
            return n
        with LOCK:
            d = _etat()
            g = (d.get("membres") or {}).get(uid)
            if g is not None:
                g[quoi] = mid
                g["carte"] = 1
                _ecrire(d)
        n += 1
    if len(a_faire) <= RATTRAPAGE_PAR_TOUR:
        with LOCK:
            d = _etat()
            d["rattrape"] = int(time.time())
            _ecrire(d)
    return n


def habiller(actuels: Dict[str, Dict[str, Any]], role_verifie: str) -> int:
    """L'historique posté sans carte (le 23/10/2026, avant elles) est réécrit
    sur place, une fois : la carte d'arrivée, la carte de bienvenue. Une
    édition ne notifie personne. RATTRAPAGE_PAR_TOUR éditions par tour ;
    fini : « habille »."""
    with LOCK:
        d = _etat()
        if d.get("habille"):
            return 0
        a_faire = [(uid, dict(f)) for uid, f in
                   sorted((d.get("membres") or {}).items(), key=lambda kv: str(kv[1].get("joined_at") or ""))
                   if uid in actuels and not f.get("carte") and (f.get("arrivee") or f.get("bienvenue"))]
        filleuls = d.get("filleuls") or {}
    n = 0
    for uid, f in a_faire:
        if n >= RATTRAPAGE_PAR_TOUR:
            return n
        m = actuels[uid]
        verifie = bool(role_verifie and role_verifie in (m.get("roles") or []))
        p = (filleuls.get(uid) or {}).get("parrain")
        for cle, salon, embed in (("arrivee", SALON_ARRIVEES,
                                   embed_arrivee(uid, m, verifie, historique=not f.get("neuf"), parrain=p)),
                                  ("bienvenue", SALON_VERIFIES, embed_bienvenue(uid, m, p or ""))):
            if f.get(cle):
                code, _r = _api("PATCH", f"/channels/{salon}/messages/{f[cle]}",
                                json={"embeds": [embed], "allowed_mentions": {"parse": []}})
                if code not in (200, 404):
                    return n                     # Discord refuse : le tour suivant reprend
                n += 1
        with LOCK:
            d = _etat()
            g = (d.get("membres") or {}).get(uid)
            if g is not None:
                g["carte"] = 1
                _ecrire(d)
    with LOCK:
        d = _etat()
        d["habille"] = int(time.time())
        _ecrire(d)
    return n


def surveiller() -> Dict[str, Any]:
    """Un tour : le panneau, le relevé (arrivées, parrains, départs), puis les
    annonces. Rend le bilan."""
    if not _TOUR.acquire(blocking=False):
        return {"occupe": True}
    try:
        return _surveiller()
    finally:
        _TOUR.release()


def _surveiller() -> Dict[str, Any]:
    bilan: Dict[str, Any] = {"arrivees": 0, "departs": 0, "panneau": "", "parraines": 0}
    if time.time() - float(_etat().get("panneau_vu") or 0) >= PANNEAU_S:
        try:
            import verif_discord as vd
            bilan["panneau"] = vd.assurer_message_verif(GID)
        except Exception as e:                               # noqa: BLE001
            bilan["panneau"] = f"{type(e).__name__}: {e}"
        if bilan["panneau"] in ("deja", "pose"):
            with LOCK:
                d = _etat()
                d["panneau_vu"] = time.time()
                _ecrire(d)
    actuels = membres()
    inv = invitations() if actuels is not None else None
    if actuels is None or inv is None:
        return bilan
    import verif_discord as vd
    role_verifie = (vd.serveur(GID) or {}).get("role_verifie")
    with LOCK:
        d = _etat()
        if not d.get("initialise"):
            d["membres"] = {u: {"joined_at": m.get("joined_at") or "", "nom": _nom(m)}
                            for u, m in actuels.items()}
            d["invite_uses"] = inv
            d["initialise"] = int(time.time())
            _ecrire(d)
            bilan["initialise"] = len(actuels)
            return bilan
        connus = d.setdefault("membres", {})
        # revenu entre deux relevés : nouvelle date d'arrivée, nouvel arrivé
        neufs = [u for u, m in actuels.items()
                 if u not in connus or (connus[u].get("joined_at") or "") != (m.get("joined_at") or "")]
        if len(neufs) > max(MAX_ANNONCES, len(actuels) // 2):
            # La moitié du serveur « arrivée » d'un coup : c'est l'état qui a
            # été perdu ou abîmé, pas un afflux. Nouvelle référence, sans
            # annonce ni parrain — et c'est dit.
            for uid in neufs:
                m = actuels[uid]
                connus[uid] = {"joined_at": m.get("joined_at") or "", "nom": _nom(m)}
            d["invite_uses"] = inv
            d["dernier_releve"] = int(time.time())
            _ecrire(d)
            print(f"[agency] {len(neufs)} membres inconnus d'un coup sur {len(actuels)} : "
                  "notés comme référence, sans annonce ni parrain", flush=True)
            bilan["reference"] = len(neufs)
            return bilan
        # sans relevé d'invitations (état d'avant le parrainage), le premier
        # tour pose la référence : aucun parrain deviné
        parrain = candidats(d.get("invite_uses"), inv, d.get("liens") or {}, len(neufs))
        filleuls = d.setdefault("filleuls", {})
        for uid in neufs:
            m = actuels[uid]
            # un revenu garde son premier parrain
            if uid not in filleuls:
                p = parrain if parrain and parrain != uid else None
                filleuls[uid] = {"parrain": p, "joined_at": m.get("joined_at") or "",
                                 "source": "invitation_unique" if p else "a_confirmer",
                                 "date": int(time.time())}
                bilan["parraines"] += bool(p)
            connus[uid] = {"joined_at": m.get("joined_at") or "", "nom": _nom(m),
                           "a_annoncer": True, "neuf": True, "carte": 1}
            b = _bienvenue_faite(d, uid, m.get("joined_at") or "")
            if b:
                connus[uid]["bienvenue"] = b
        for uid in [u for u in connus if u not in actuels]:
            d.setdefault("partis", {})[uid] = dict(connus.pop(uid), a_annoncer=True,
                                                   quand=int(time.time()))
        for uid, m in actuels.items():
            connus[uid]["nom"] = _nom(m)
            if uid in filleuls:
                filleuls[uid]["verifie"] = bool(role_verifie and role_verifie in (m.get("roles") or []))
        d["invite_uses"] = inv
        d["dernier_releve"] = int(time.time())
        _ecrire(d)
        arrivees = [(u, dict(f), (filleuls.get(u) or {}).get("parrain"))
                    for u, f in connus.items() if f.get("a_annoncer")][:MAX_ANNONCES]
        departs = [(u, dict(f)) for u, f in (d.get("partis") or {}).items()
                   if f.get("a_annoncer")][:MAX_ANNONCES]
        rattrape = bool(d.get("rattrape"))
        habille = bool(d.get("habille"))
        # ✅ Vérifié posé à la main (sans passer par la vérification) : sa
        # carte de bienvenue quand même, comme Twitter (verified_sent). Après
        # l'historique, qui poste celles des anciens
        sans_bienvenue = ([u for u, m in actuels.items()
                           if role_verifie and role_verifie in (m.get("roles") or [])
                           and not _bienvenue_faite(d, u, m.get("joined_at") or "")][:MAX_ANNONCES]
                          if rattrape else [])
    # Les annonces hors du verrou : un clic sur « Mon espace » n'attend pas
    # vingt messages Discord. L'historique d'abord, dans l'ordre d'arrivée.
    if not rattrape:
        bilan["rattrapage"] = rattraper(actuels, role_verifie)
        if bilan["rattrapage"]:
            print(f"[agency] historique : {bilan['rattrapage']} message(s) posté(s)", flush=True)
    elif not habille:
        bilan["habillage"] = habiller(actuels, role_verifie)
        if bilan["habillage"]:
            print(f"[agency] cartes : {bilan['habillage']} message(s) réécrit(s)", flush=True)
    for uid, f, p in arrivees:
        m = actuels.get(uid) or {}
        deja = bool(role_verifie and role_verifie in (m.get("roles") or []))
        mid = _poster(SALON_ARRIVEES, embed_arrivee(uid, m, deja, historique=False, parrain=p),
                      f"{GID}:{uid}:{f.get('joined_at')}:arrivee")
        if not mid:
            break                                   # Discord refuse : le tour suivant reprend
        with LOCK:
            d = _etat()
            g = (d.get("membres") or {}).get(uid)
            if g is not None:
                g.pop("a_annoncer", None)
                g["arrivee"] = mid
                _ecrire(d)
        bilan["arrivees"] += 1
    for uid, f in departs:
        embed = {"title": "👋 Départ",
                 "description": f"<@{uid}> a quitté le serveur.",
                 "color": 0xE67E22,
                 "footer": {"text": "Agency VA INSTAGRAM • Départs"}}
        mid = _poster(SALON_DEPARTS, embed, f"{GID}:{uid}:{f.get('joined_at')}:depart")
        if not mid:
            break
        with LOCK:
            d = _etat()
            g = (d.get("partis") or {}).get(uid)
            if g is not None:
                g.pop("a_annoncer", None)
                g["depart"] = mid
                _ecrire(d)
        bilan["departs"] += 1
    bilan["bienvenues"] = sum(bool(bienvenue(u, actuels[u])) for u in sans_bienvenue)
    if bilan["arrivees"] or bilan["departs"]:
        print(f"[agency] {bilan['arrivees']} arrivée(s) ({bilan['parraines']} parrainée(s)), "
              f"{bilan['departs']} départ(s) annoncé(s)", flush=True)
    return bilan


# ── l'espace personnel (youl4b.com/affiliation/mon-espace) ─────────────────
def subs_fiche(fiche: Dict[str, Any], metrics: Optional[Dict[str, Any]]) -> Optional[int]:
    """Les vrais subs cumulés d'un lien d'Agency : le tracking Emy du VA (et
    celui d'une variante s'il y en avait une — mêmes adresses que
    subs_va.trackings_du_va). None = inconnu : pas de lien, ou MyPuls ne rend
    pas toutes ses adresses. Lu aussi par la page d'administration."""
    if metrics is None:
        return None
    urls = {str(u).strip().rstrip("/").lower()
            for u in ((fiche or {}).get("tracking"), ((fiche or {}).get("variante") or {}).get("tracking"))
            if u}
    if not urls:
        return None
    ns = [metrics.get(u) for u in urls]
    return None if any(n is None for n in ns) else sum(ns)


def _pct(n: int, seuil: int) -> str:
    p = min(100.0, n * 100 / seuil)
    return (f"{p:.1f}".rstrip("0").rstrip(".") if p % 1 else str(int(p))).replace(".", ",")


def panneau(uid: str) -> Dict[str, Any]:
    """Les rubriques de l'espace personnel (affiliation_site.personnel) : son
    lien, son parrain, ses filleuls et leurs subs, les primes."""
    import liens_va
    uid = str(uid)
    lien = lien_pour(uid)
    d = registre()
    noms = {u: f.get("nom") for u, f in (d.get("membres") or {}).items()}
    noms.update({u: f.get("nom") for u, f in (d.get("partis") or {}).items() if u not in noms})

    def qui(u: str) -> str:
        return "@" + str(noms.get(u) or u)

    filleuls = d.get("filleuls") or {}
    parrain = (filleuls.get(uid) or {}).get("parrain")
    enfants = sorted((u for u, f in filleuls.items() if (f or {}).get("parrain") == uid),
                     key=lambda u: (filleuls[u].get("date") or 0))
    fields: List[Dict[str, str]] = [
        {"name": "🔗 Ton lien personnel · Agency", "value": lien},
        {"name": "🤝 Ton parrain",
         "value": qui(parrain) if parrain else "Aucun parrain enregistré pour Agency."},
        {"name": "👥 Tes filleuls", "value": f"{len(enfants)} filleul(s) enregistré(s)."},
    ]
    metrics = None
    if enfants:
        try:
            import affiliation_privee
            metrics = affiliation_privee.compteurs()
        except Exception:                                    # noqa: BLE001
            metrics = None
    for e in enfants:
        f = filleuls[e]
        fiche = liens_va.lien_de(GID, e)
        n = subs_fiche(fiche, metrics)
        etat = ("👋 Parti du serveur" if e in (d.get("partis") or {}) and e not in (d.get("membres") or {})
                else "✅ Vérifié" if f.get("verifie") else "⏳ Pas encore vérifié")
        if not (fiche.get("tracking") or (fiche.get("variante") or {}).get("tracking")):
            suivi = "Pas encore de lien de suivi : ses subs compteront dès sa création."
        elif n is None:
            suivi = "Subs indisponibles pour le moment : aucun palier confirmé."
        else:
            suivi = (f"{n} vrais subs · Objectif 10 : {_pct(n, 10)} %"
                     f" · Objectif 200 : {_pct(n, 200)} %")
        fields.append({"name": "📊 Progression du filleul", "value": f"{qui(e)} — {etat}\n{suivi}"})
    fields.append({"name": "💰 Primes de parrainage",
                   "value": "0,50 $ à 10 subs, puis 10 $ supplémentaires à 200 subs, par filleul. "
                            "Cumul depuis son arrivée. Primes et paiements gérés manuellement."})
    return {"fields": fields}


# ── le panneau de 🤝・parrainage et son bouton ──────────────────────────────
def message_parrainage() -> Dict[str, Any]:
    """Le panneau, au texte de celui de Twitter (🔐・vérification de Twitter,
    « 🔒 Mon espace personnel · Affiliation Twitter »)."""
    return {
        "embeds": [{
            "title": "🔒 Mon espace personnel · Parrainage Agency",
            "description": ("Retrouve **ton lien de parrainage**, ton parrain et la progression de "
                            "tes filleuls sur le site.\n\n"
                            "Clique ci-dessous : **ton lien d’accès est visible uniquement par toi**. "
                            "Garde cette adresse privée.\n\n"
                            "💰 **0,50 $ à 10 subs**, puis **10 $ supplémentaires à 200 subs**, par "
                            "filleul. Primes cumulables, paiements gérés manuellement."),
            "color": 0x5865F2,
            "image": {"url": AFFICHE},
        }],
        "components": [{"type": 1, "components": [
            {"type": 2, "style": 1, "custom_id": "agency-aff:mes", "label": "🔒 Mon espace personnel"}]}],
        "allowed_mentions": {"parse": []},
    }


def poser_panneau_parrainage() -> str:
    """Pose le panneau dans 🤝・parrainage (Wario : le clic va à l'application
    qui a posté), épinglé. Déjà là : remis au texte du jour. Rend "pose",
    "mis a jour" ou la raison de l'échec. Appelé à la main : rien ne le
    pose seul."""
    with LOCK:
        f = dict(_etat().get("panneau_parrainage") or {})
    corps = message_parrainage()
    if f.get("message"):
        code, _rep = _api("PATCH", f"/channels/{SALON_PARRAINAGE}/messages/{f['message']}", json=corps)
        if code == 200:
            return "mis a jour"
        if code != 404:
            return f"illisible (HTTP {code})"
    code, rep = _api("POST", f"/channels/{SALON_PARRAINAGE}/messages", json=corps)
    if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
        return f"non pose (HTTP {code})"
    mid = str(rep["id"])
    with LOCK:
        d = _etat()
        d["panneau_parrainage"] = {"salon": SALON_PARRAINAGE, "message": mid, "date": int(time.time())}
        _ecrire(d)
    code_p, _ = _api("PUT", f"/channels/{SALON_PARRAINAGE}/pins/{mid}")
    if code_p not in (200, 204):
        print(f"[agency] panneau du parrainage posé, épingle refusée (HTTP {code_p})", flush=True)
    return "pose"


def traiter(charge: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Le bouton « 🔒 Mon espace personnel » : l'adresse privée de son espace,
    visible de lui seul. None quand ce n'est pas ce bouton."""
    cid = str((charge.get("data") or {}).get("custom_id") or "")
    if not cid.startswith("agency-aff:"):
        return None
    import verif_discord as vd
    uid = str(((charge.get("member") or {}).get("user") or {}).get("id") or "")
    valide = (str(charge.get("guild_id")) == GID and uid.isdigit()
              and str(charge.get("application_id")) == str(vd.bot_du_serveur(GID).get("app_id")))
    texte = "Ce bouton ne correspond pas à ce serveur."
    if valide:
        try:
            import affiliation_site
            texte = ("🔒 **Ton espace personnel · Agency**\n" + affiliation_site.lien_personnel(uid, "agency")
                     + "\nTon lien, ton parrain et tes filleuls d'Agency. Cette adresse est privée : "
                       "ne la partage pas.")
        except Exception as e:                               # noqa: BLE001
            print(f"[agency] espace personnel de {uid} : {type(e).__name__}: {e}", flush=True)
            texte = "❌ Ton espace est momentanément indisponible. Réessaie dans un instant."
    return {"type": 4, "data": {"content": texte, "flags": 64, "allowed_mentions": {"parse": []}}}


def demarrer() -> bool:
    """Le relevé, chaque minute, dans son fil (web_upload.create_app, sur la
    machine de production seulement). Une fois par processus."""
    global _DEMARRE
    with LOCK:
        if _DEMARRE:
            return False
        _DEMARRE = True

    def boucle():
        while True:
            try:
                import verif_discord as vd
                with vd.sur_serveur(GID):
                    surveiller()
            except Exception as e:                           # noqa: BLE001
                print(f"[agency] relevé : {type(e).__name__}: {e}", flush=True)
            time.sleep(PERIODE_S)

    threading.Thread(target=boucle, daemon=True, name="agency-accueil").start()
    return True
