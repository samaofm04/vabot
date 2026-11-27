"""POLE TWITTER FR : copie de TRUST TWITTER pour le marché FR (25/11/2026).

Propriétaire : « je dois build un nouveau server pour twitter mais sur le
marche fr tu peux faire un copie colle ». Structure recopiée par REST avec
Nasse (rôles, catégories, salons, droits ; sans les tickets des managers).
Puis « Oui, branche » : vérification, tickets, menu et outils comme TRUST
TWITTER.

Une seule table : chaque id de TRUST TWITTER -> son double ici. Les modules
recopient la config de Twitter par traduire() au lieu d'écrire une seconde
liste d'ids à la main. Un id de Twitter SANS double devient "" (et il est
compté dans MANQUANTS) : le garder ferait écrire le bot sur TRUST TWITTER
depuis un clic de ce serveur.

Pas branché (à demander) : podium, classements, liens GetMySocial, pages VA,
stats, paie — ses VA ne se mélangent pas à ceux de Twitter
(chaque serveur TRUST ses VA).
"""
import re
from typing import Any, List

POLE_ID = "1575133611311763578"
SOURCE_ID = "1445108485090971710"     # TRUST TWITTER

#: id de TRUST TWITTER -> id de POLE TWITTER FR (relevé le 25/11/2026 par
#: catégorie + nom de salon, nom de rôle)
CORRESPONDANCE = {
    SOURCE_ID: POLE_ID,
    "1445108485090971710": "1575133611311763578",
    "1552192933690744883": "1575135159798202440",
    "1552192935100026881": "1575135152630145144",
    "1552192936597520466": "1575135171026489444",
    "1552192939051188316": "1575135173341876265",
    "1552192942385537034": "1575135209714745365",
    "1552192944944058408": "1575135203913896069",
    "1552192946218991616": "1575135348520910988",
    "1552192947766960158": "1575135351859712052",
    "1552192949851525131": "1575135354678280263",
    "1552192951600545843": "1575135357383614505",
    "1552195869946945646": "1575135134976581725",
    "1552353733357215754": "1575135327478358228",
    "1552381465415782474": "1575135199396761700",
    "1552381514325434430": "1575135227746066644",
    "1552382795899207762": "1575135212545904730",
    "1552382821228613887": "1575135214534008843",
    "1552382833958326342": "1575135332754661486",
    "1552382852694278167": "1575135264295092266",
    "1552382859082338405": "1575135265939390534",
    "1552382871606657104": "1575135268485468292",
    "1552382880100130987": "1575135271387791480",
    "1552382888262242405": "1575135274042790019",
    "1552382895002230796": "1575135279432605859",
    "1552382901826621500": "1575135276756631655",
    "1552382908248096778": "1575135303554039840",
    "1552382929169023028": "1575135288936632360",
    "1552385970182168607": "1575135242946215997",
    "1552385975806726154": "1575135251200737300",
    "1552385982232273047": "1575135301213491330",
    "1552385988553343036": "1575135224591945828",
    "1552392023703683123": "1575135244372279356",
    "1552392030104330240": "1575135248059207811",
    "1552392036475478016": "1575135253712863282",
    "1552392880402866218": "1575135259681366198",
    "1552392891995922453": "1575135256325918741",
    "1552392906340565114": "1575135320716869693",
    "1552392915622436874": "1575135294704058428",
    "1552401579523702797": "1575135233475350549",
    "1552405659239186472": "1575135282829852793",
    "1552405673046712330": "1575135285828788305",
    "1552410199753490525": "1575135176424554577",
    "1552410206187814992": "1575135179142463498",
    "1552410213649485824": "1575135181419839651",
    "1552410230548340848": "1575135183798141071",
    "1552410237406027868": "1575135187547852840",
    "1552410243722518659": "1575135190466961448",
    "1552472761287446608": "1575135168644259920",
    "1552474724615852132": "1575135163636125696",
    "1555969785265659985": "1575135262315511890",
    "1559487241502335066": "1575135155155107941",
    "1560033695560241232": "1575135336563220500",
    "1560099417422569505": "1575135335212646552",
    "1560099421717401710": "1575135325762756692",
    "1560148341210349639": "1575135201300844614",
    "1560153647395115058": "1575135206862753832",
    "1560163530760790057": "1575135217692311572",
    "1562463909011529790": "1575135311044804698",
    "1562464002121015367": "1575135314140336180",
    "1563007188589355060": "1575135220401700945",
    "1563598272705208390": "1575135166043787306",
    "1563734528290193419": "1575135345777844426",
    "1566203455662592000": "1575135236285792407",
    "1568052477410934864": "1575135316657045554",
    "1568052482217869447": "1575135317915209869",
    "1568052487158767806": "1575135323233460396",
    "1568293149430911137": "1575135240073248942",
    "1568371634740400250": "1575135329810391104",
    "1569700297289371668": "1575135339129999440",
    "1570556490459123874": "1575135291667382272",
    "1574690084077305957": "1575135342607208538",
}

#: les ids de Twitter qui n'ont pas de double, vus par traduire()
MANQUANTS: List[str] = []
_ID = re.compile(r"^\d{17,20}$")


def traduire(v: Any) -> Any:
    """Copie de v où chaque id de TRUST TWITTER est remplacé par son double."""
    if isinstance(v, dict):
        return {k: traduire(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        out = [traduire(x) for x in v]
        return type(v)(out) if isinstance(v, tuple) else out
    if isinstance(v, set):
        return {traduire(x) for x in v}
    if isinstance(v, str) and _ID.match(v):
        if v in CORRESPONDANCE:
            return CORRESPONDANCE[v]
        if v not in MANQUANTS:
            MANQUANTS.append(v)
        return ""
    return v


# ═══ Rangement par model, liens choisis à la main, classements (26/11/2026) ═══
# Propriétaire : « branche aussi le podium et les liens », « je mets toutes
# les models FR, pas de Lia », « c'est moi je choisis le lien qu'il va avoir
# et ils sont rangés comme sur IG par model », « si je lui mets le rôle
# Amelia son lien devient Amelia et voilà ».
#  - un rôle par model (créé ici) ; le rôle FAIT FOI, comme sur Va IG ;
#  - le salon perso du VA va dans la catégorie de sa model (premier de ses
#    rôles dans l'ordre de MODELS), ou dans « 🆕 SANS MODEL » ;
#  - un lien par VA ET par model, posé à la main sur /pole-twitter-fr ; le
#    salon du VA reçoit le lien de chacune de ses models, SEUL dans son
#    message (appui long sur téléphone = tout le message copié) ;
#  - 🏆・classement : la semaine, 📈・subs : la quinzaine, en abonnés des
#    trackings MyPuls derrière ses liens (tous ses liens, toutes models).
# Rien n'est créé chez MyPuls ni GetMySocial : MyPuls ne sait pas effacer un
# tracking, et les trackings MYM sont en panne (code par e-mail, 17/11).
import json
import threading
import time
import datetime as _dt
from pathlib import Path
from typing import Dict, Optional, Tuple

import safe_json

MODELS = ("amelia", "emma", "lola", "julia", "sarah", "alicia")
NOMS = {m: m.capitalize() for m in MODELS}
#: couleurs des rôles (celles des models sur You FR / Va IG, à peu près)
COULEURS = {"amelia": 0xF472B6, "emma": 0xA78BFA, "lola": 0xF87171,
            "julia": 0x60A5FA, "sarah": 0x34D399, "alicia": 0xFBBF24}
CATEGORIE = {m: f"🎀 {m.upper()}" for m in MODELS}
CATEGORIE_SANS = "🆕 SANS MODEL"
SALON_SEMAINE = "1575135253712863282"     # 📣 ANNONCES ET SUIVI › 🏆・classement
SALON_QUINZAINE = "1575135251200737300"   # 📣 ANNONCES ET SUIVI › 📈・subs
FICHIER = Path(__file__).resolve().parent / "data" / "pole_twitter_fr.json"
TOUR_S = 5 * 60
CLASSEMENT_S = 60 * 60
PARIS = None
try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:                                            # noqa: BLE001
    pass

_VERROU = threading.RLock()
_DEMARRE = [False]


def _log(t: str) -> None:
    print(f"[pole-twitter-fr] {t}", flush=True)


def _api(methode: str, chemin: str, **kw):
    import verif_discord as vd
    with vd.sur_serveur(POLE_ID):
        return vd.api(methode, chemin, **kw)


def etat() -> Dict[str, Any]:
    d = safe_json.load(FICHIER, default={}) or {}
    for k in ("liens", "membres", "messages", "numeros", "roles", "categories", "classements"):
        d.setdefault(k, {})
    return d


def _ecrire(d: Dict[str, Any]) -> bool:
    return bool(safe_json.write(FICHIER, d))


# ─── Rôles et catégories ─────────────────────────────────────────────────
def assurer_roles(roles: List[Dict[str, Any]], d: Dict[str, Any]) -> Dict[str, str]:
    """{model: id du rôle}, les manquants créés (affichés à part, sans droit)."""
    par_nom = {str(r.get("name") or "").strip().lower(): str(r["id"]) for r in roles}
    out = {}
    for m in MODELS:
        rid = par_nom.get(m)
        if not rid:
            code, r = _api("POST", f"/guilds/{POLE_ID}/roles",
                           json={"name": NOMS[m], "color": COULEURS[m], "hoist": True,
                                 "mentionable": False, "permissions": "0"})
            if code in (200, 201) and isinstance(r, dict):
                rid = str(r["id"])
                _log(f"rôle {NOMS[m]} créé")
            else:
                _log(f"rôle {NOMS[m]} non créé (HTTP {code}) {str(r)[:120]}")
                continue
        out[m] = rid
    d["roles"] = out
    return out


def _categorie(salons: List[Dict[str, Any]], nom: str, d: Dict[str, Any]) -> str:
    """L'id de la catégorie `nom`, créée cachée à @everyone si elle manque."""
    for c in salons:
        if c.get("type") == 4 and str(c.get("name") or "") == nom:
            return str(c["id"])
    code, r = _api("POST", f"/guilds/{POLE_ID}/channels",
                   json={"name": nom, "type": 4, "permission_overwrites": [
                       {"id": POLE_ID, "type": 0, "allow": "0", "deny": str(1024)}]})
    if code in (200, 201) and isinstance(r, dict):
        salons.append(r)
        _log(f"catégorie {nom} créée")
        return str(r["id"])
    _log(f"catégorie {nom} non créée (HTTP {code}) {str(r)[:120]}")
    return ""


def models_du_membre(m: Dict[str, Any], roles_ids: Dict[str, str]) -> List[str]:
    siens = set(str(x) for x in (m.get("roles") or []))
    return [mo for mo in MODELS if roles_ids.get(mo) in siens]


# ─── Liens ───────────────────────────────────────────────────────────────
_RE_TRACKING = re.compile(r"https?://(?:www\.)?(?:onlyfans\.com/[A-Za-z0-9._-]+/c\d+"
                          r"|mym\.(?:fans|me)/app/t/[A-Za-z0-9]+)")


def trackings_du_lien(url: str) -> List[str]:
    """Les adresses de tracking MyPuls derrière un lien : lui-même s'il en est
    un, sinon les boutons de sa page GetMySocial (lue par l'API, sans visite).
    [] si on ne sait pas : le lien reste posé, il ne compte pas de subs."""
    url = str(url or "").strip()
    if _RE_TRACKING.match(url):
        return [_RE_TRACKING.match(url).group(0)]
    m = re.match(r"https?://(?:www\.)?getmysocial\.com/([A-Za-z0-9._-]+)", url)
    if not m:
        return []
    try:
        import gms
        res = gms._call_tool("search_links", {"query": m.group(1)})
        items = res.get("data") if res.get("ok") else None
        if isinstance(items, dict):
            items = items.get("links") or items.get("data") or []
        lien = next((x for x in items or [] if isinstance(x, dict)
                     and str(x.get("shortcode") or "").lower() == m.group(1).lower()), None)
        if not lien:
            return []
        g = gms.get_link(str(lien.get("id") or lien.get("_id") or ""),
                         team_id=str(lien.get("team_id") or lien.get("teamId") or "") or None)
        texte = json.dumps(g.get("link") or {}, ensure_ascii=False)
        return sorted(set(x.group(0) for x in _RE_TRACKING.finditer(texte)))
    except Exception as e:                                   # noqa: BLE001
        _log(f"page {url} illisible : {type(e).__name__}: {e}")
        return []


def poser_lien(uid: str, model: str, url: str, par: str = "",
               trackings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Le lien de ce VA pour cette model (url vide : retiré). Rend la fiche.
    `trackings` : ceux qu'on vient de créer (creer_lien) — sans eux, relus
    sur la page."""
    uid, model, url = str(uid), str(model).lower(), str(url or "").strip()
    if model not in MODELS:
        raise ValueError("model inconnue")
    if url and not re.match(r"https?://\S+$", url):
        raise ValueError("lien invalide")
    tr = list(trackings) if trackings is not None else (trackings_du_lien(url) if url else [])
    with _VERROU:
        d = etat()
        fiche = d["liens"].setdefault(uid, {})
        if url:
            fiche[model] = {"url": url, "trackings": tr, "par": par, "quand": int(time.time())}
            # tout lien donné un jour compte dans ses subs (il a pu changer
            # de model en cours de quinzaine)
            hist = d.setdefault("historique", {}).setdefault(uid, [])
            for t in tr:
                if t not in hist:
                    hist.append(t)
        else:
            fiche.pop(model, None)
        _ecrire(d)
    return fiche.get(model) or {}


def _poser_messages(salon: str, uid: str, voulu: List[str], d: Dict[str, Any]) -> None:
    """Un message par lien, le lien SEUL. Réédité s'il change, retiré s'il
    n'a plus lieu d'être (nos messages seulement)."""
    deja: List[Dict[str, str]] = list((d["messages"].get(uid) or {}).get("liste") or [])
    if (d["messages"].get(uid) or {}).get("salon") not in (None, salon):
        deja = []          # nouveau salon : les anciens messages restent où ils sont
    nouveaux = []
    for i, texte in enumerate(voulu):
        if i < len(deja) and deja[i].get("id"):
            if deja[i].get("texte") != texte:
                code, _ = _api("PATCH", f"/channels/{salon}/messages/{deja[i]['id']}",
                               json={"content": texte, "allowed_mentions": {"parse": []}})
                if code == 404:
                    deja[i] = {}
            if deja[i].get("id"):
                nouveaux.append({"id": deja[i]["id"], "texte": texte})
                continue
        code, r = _api("POST", f"/channels/{salon}/messages",
                       json={"content": texte, "allowed_mentions": {"parse": []}})
        if code in (200, 201) and isinstance(r, dict):
            nouveaux.append({"id": str(r["id"]), "texte": texte})
        else:
            _log(f"lien non posé dans {salon} (HTTP {code})")
    for vieux in deja[len(voulu):]:
        if vieux.get("id"):
            _api("DELETE", f"/channels/{salon}/messages/{vieux['id']}")
    d["messages"][uid] = {"salon": salon, "liste": nouveaux}


# ─── Le tour ─────────────────────────────────────────────────────────────
def tour() -> Dict[str, Any]:
    """Rôles, rangement, liens. Ne lève pas."""
    import tickets_discord as td
    bilan: Dict[str, Any] = {"deplaces": [], "liens": 0, "rates": []}
    with _VERROU:
        d = etat()
        code, roles = _api("GET", f"/guilds/{POLE_ID}/roles")
        code2, membres = _api("GET", f"/guilds/{POLE_ID}/members?limit=1000")
        code3, salons = _api("GET", f"/guilds/{POLE_ID}/channels")
        if not (code == code2 == code3 == 200):
            bilan["rates"].append(f"Discord illisible (HTTP {code}/{code2}/{code3})")
            _log(bilan["rates"][-1])
            return bilan
        rids = assurer_roles(roles, d)
        par_id = {str(c["id"]): c for c in salons}
        vus = {}
        for m in membres:
            u = m.get("user") or {}
            if u.get("bot"):
                continue
            uid = str(u.get("id"))
            mods = models_du_membre(m, rids)
            vus[uid] = {"pseudo": u.get("username") or uid, "models": mods,
                        "nom": m.get("nick") or u.get("global_name") or u.get("username")}
            if uid not in d["numeros"]:
                d["numeros"][uid] = len(d["numeros"]) + 1
            salon = td.ticket_de(POLE_ID, uid)
            if not salon or salon not in par_id:
                continue
            vus[uid]["salon"] = salon
            cible = _categorie(salons, CATEGORIE[mods[0]] if mods else CATEGORIE_SANS, d)
            if cible and str(par_id[salon].get("parent_id") or "") != cible:
                # parent seul, sans lock_permissions : le salon garde SES droits
                c, r = _api("PATCH", f"/channels/{salon}", json={"parent_id": cible})
                if c == 200:
                    par_id[salon]["parent_id"] = cible
                    bilan["deplaces"].append(f"{vus[uid]['pseudo']} → {mods[0] if mods else 'sans model'}")
                else:
                    bilan["rates"].append(f"{vus[uid]['pseudo']} non déplacé (HTTP {c})")
            liens = d["liens"].get(uid) or {}
            voulu = [liens[mo]["url"] for mo in mods if (liens.get(mo) or {}).get("url")]
            _poser_messages(salon, uid, voulu, d)
            bilan["liens"] += len(voulu)
        d["membres"] = vus
        d["vu"] = int(time.time())
        _ecrire(d)
    # le menu v2 des tickets lit le lien d'ici : redessiné s'il a bougé
    try:
        import verif_discord as vd
        with vd.sur_serveur(POLE_ID):
            td.rafraichir_menus(POLE_ID)
    except Exception as e:                                   # noqa: BLE001
        _log(f"menus non redessinés : {type(e).__name__}: {e}")
    if bilan["deplaces"] or bilan["rates"]:
        _log(f"tour : {bilan}")
    return bilan


# ─── Classements ─────────────────────────────────────────────────────────
def _aujourdhui() -> _dt.date:
    return _dt.datetime.now(PARIS).date() if PARIS else _dt.date.today()


def periodes(jour: Optional[_dt.date] = None) -> Dict[str, Tuple[_dt.date, _dt.date]]:
    j = jour or _aujourdhui()
    lundi = j - _dt.timedelta(days=j.weekday())
    debut_q = j.replace(day=1 if j.day <= 15 else 16)
    if j.day <= 15:
        fin_q = j.replace(day=15)
    else:
        suivant = (j.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
        fin_q = suivant - _dt.timedelta(days=1)
    return {"semaine": (lundi, lundi + _dt.timedelta(days=6)), "quinzaine": (debut_q, fin_q)}


def classement(debut: _dt.date, fin: _dt.date, d: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """[{uid, va, subs, sans_tracking}] trié, sur [debut, fin] (aujourd'hui au plus)."""
    import mypuls
    d = d or etat()
    fin_lue = min(fin, _aujourdhui())
    lignes = mypuls.api_tracking_links(debut=debut.isoformat(), fin=fin_lue.isoformat())
    par_url = {}
    for t in lignes:
        u = str(t.get("url") or "").rstrip("/")
        if u:
            par_url[u] = t
    out = []
    for uid, info in (d.get("membres") or {}).items():
        hist = list((d.get("historique") or {}).get(uid) or [])
        for f in ((d.get("liens") or {}).get(uid) or {}).values():
            hist += [t for t in f.get("trackings") or [] if t not in hist]
        if not hist and not info.get("models"):
            continue
        subs, trouves = 0, 0
        for u in hist:
            t = par_url.get(u.rstrip("/"))
            if t is not None:
                trouves += 1
                subs += int(t.get("abonnes_periode") or 0)
        out.append({"uid": uid, "va": f"VA {d['numeros'].get(uid, '?')}", "subs": subs,
                    "sans_tracking": not trouves})
    out.sort(key=lambda x: (-x["subs"], x["va"]))
    return out


# Les primes de TRUST TWITTER (propriétaire, 26/11/2026 : « mets les mêmes
# primes que sur twitter »), recopiées de podium_discord au 26/11 : semaine
# 10 / 5 / 3 $ dès 100 subs, jour 5 / 3 / 2 $ dès 40 subs. Le gagnant est
# prévenu dans SON salon, son manager mentionné, son adresse USDC (bouton 💳)
# rappelée ; le paiement reste à la main, comme sur Twitter.
PRIMES = {"semaine": [10.0, 5.0, 3.0], "jour": [5.0, 3.0, 2.0]}
MINIMUM = {"semaine": 100, "jour": 40}
SALON_BONUS = "1575135256325918741"       # 📣 ANNONCES ET SUIVI › 💰・bonus-journalier
MEDAILLES = ("🥇", "🥈", "🥉")


def primes(cle: str, lignes: List[Dict[str, Any]]) -> List[Optional[float]]:
    """La prime de chaque ligne (None : pas de prime), aux premiers qui ont le
    minimum ; jamais à 0 sub."""
    bareme = PRIMES.get(cle) or []
    out, k = [], 0
    for l in lignes:
        if k < len(bareme) and l["subs"] > 0 and l["subs"] >= MINIMUM.get(cle, 0):
            out.append(bareme[k])
            k += 1
        else:
            out.append(None)
    return out


def _texte(titre: str, debut: _dt.date, fin: _dt.date, lignes: List[Dict[str, Any]],
           combien: int, cle: str, fini: bool = False) -> str:
    pr = primes(cle, lignes)
    quand = (f"Du {debut:%d/%m} au {fin:%d/%m}" if debut != fin else f"Le {debut:%d/%m}")
    etat_ = "**terminé**" if fini else f"mis à jour <t:{int(time.time())}:R>"
    t = [f"## {titre}", f"{quand} · en abonnés · {etat_}"]
    if cle in MINIMUM:
        t.append(f"💰 {' / '.join(f'{x:g} $' for x in PRIMES[cle])} · minimum {MINIMUM[cle]} subs")
    t.append("")
    if not lignes:
        t.append("_Personne encore._")
    for i, l in enumerate(lignes[:combien]):
        rang = MEDAILLES[i] if i < 3 else f"**{i + 1}.**"
        prime = f" · 💰 {pr[i]:g} $" if pr[i] else ""
        t.append(f"{rang} {l['va']} — **{l['subs']}** sub{'s' if l['subs'] > 1 else ''}{prime}")
    if cle in MINIMUM and not fini:
        t += ["", "💸 Pour recevoir ta prime : enregistre ton adresse USDC (Solana ou Ethereum) "
                  "avec le bouton **💳 Mon adresse USDC** du message épinglé de ton espace perso."]
    return "\n".join(t)[:1990]


def _annoncer(cle: str, debut: _dt.date, fin: _dt.date, lignes: List[Dict[str, Any]],
              d: Dict[str, Any]) -> List[str]:
    """Dit à chaque gagnant, dans son salon, ce qu'il touche. Une fois."""
    import tickets_discord as td
    import suivi_va as sv
    faits = d.setdefault("primes_dites", {})
    dits = []
    place = -1
    for l, montant in zip(lignes, primes(cle, lignes)):
        if not montant:
            continue
        place += 1
        k = f"{cle}:{debut.isoformat()}:{l['uid']}"
        if faits.get(k):
            continue
        fiche = (td._etat().get("tickets") or {}).get(f"{POLE_ID}:{l['uid']}") or {}
        salon = str(fiche.get("salon") or "")
        if not salon or fiche.get("parti"):
            # parti : sa prime est annulée, pas reportée (comme Twitter)
            faits[k] = {"sans_salon": True}
            _log(f"prime {cle} {debut} de {l['va']} : pas de salon, non annoncée")
            continue
        mid = str(fiche.get("manager") or "")
        adr = sv.adresse_de(POLE_ID, l["uid"])
        ligne_adr = (f"💳 Vers `{adr}`" if adr else
                     "⚠️ **Aucune adresse enregistrée** — clique 💳 **Mon adresse USDC** sur le message épinglé.")
        quoi = "de la semaine" if cle == "semaine" else "du jour"
        periode = (f"Semaine du **{debut:%d/%m}** au **{fin:%d/%m}**" if cle == "semaine"
                   else f"Journée du **{debut:%d/%m}**")
        code, _r = _api("POST", f"/channels/{salon}/messages", json={
            "content": (f"<@{l['uid']}> " + (f"<@{mid}>" if mid else "")).strip(),
            "allowed_mentions": {"users": [l["uid"]] + ([mid] if mid else [])},
            "embeds": [{"title": f"{MEDAILLES[place]} {place + 1}e {quoi} — {montant:.2f}$",
                        "color": 0xF1C40F,
                        "description": f"{periode} · **{l['subs']}** subs.\n{ligne_adr}"}]})
        if code in (200, 201):
            faits[k] = int(time.time())
            dits.append(f"{l['va']} {montant:g}$")
    return dits


#: une période finie n'est figée (et ses primes annoncées) qu'à partir de
#: cette heure du lendemain : MyPuls relit les trackings MYM toutes les 30 min,
#: les subs de 23 h 50 arrivent après minuit
HEURE_FIGE = 2
TITRES = {"semaine": ("🏆 Podium de la semaine", 3), "quinzaine": ("📈 Classement de la quinzaine", 40),
          "jour": ("💰 Bonus du jour", 10)}
SALONS = {"semaine": SALON_SEMAINE, "quinzaine": SALON_QUINZAINE, "jour": SALON_BONUS}


def _maintenant() -> _dt.datetime:
    return _dt.datetime.now(PARIS) if PARIS else _dt.datetime.now()


def _figer(cle: str, fiche: Dict[str, Any], d: Dict[str, Any], out: Dict[str, Any]) -> bool:
    """Réédite le message d'une période finie ; figé et primes annoncées une
    fois l'heure passée. Rend vrai quand c'est fait (à retirer de la file)."""
    titre, combien = TITRES[cle]
    salon = SALONS[cle]
    a_deb = _dt.date.fromisoformat(fiche["debut"])
    a_fin = _dt.date.fromisoformat(fiche.get("fin") or (periodes(a_deb)[cle][1] if cle in ("semaine", "quinzaine")
                                                        else fiche["debut"]))
    m = _maintenant()
    pret = m.date() > a_fin + _dt.timedelta(days=1) or (m.date() > a_fin and m.hour >= HEURE_FIGE)
    lignes = classement(a_deb, a_fin, d)
    _api("PATCH", f"/channels/{salon}/messages/{fiche['id']}",
         json={"content": _texte(titre, a_deb, a_fin, lignes, combien, cle, fini=pret),
               "allowed_mentions": {"parse": []}})
    if not pret:
        return False
    if cle in PRIMES:
        out[f"{cle}_{a_deb.isoformat()}_primes"] = _annoncer(cle, a_deb, a_fin, lignes, d)
    d["classements"].setdefault("figes", {})[f"{cle}:{a_deb.isoformat()}"] = {
        "id": fiche["id"], "lignes": lignes, "quand": int(time.time())}
    return True


def publier_classements() -> Dict[str, Any]:
    """Un message par période, réédité. Une période finie passe dans la file
    « a_figer » ; elle y est rééditée jusqu'à HEURE_FIGE le lendemain, puis
    figée (« terminé ») et ses primes annoncées. Un relevé raté ne fige rien."""
    out: Dict[str, Any] = {}
    with _VERROU:
        d = etat()
        auj = _aujourdhui()
        p = periodes(auj)
        p["jour"] = (auj, auj)
        file = d["classements"].setdefault("a_figer", [])
        for cle in ("semaine", "quinzaine", "jour"):
            salon = SALONS[cle]
            titre, combien = TITRES[cle]
            debut, fin = p[cle]
            fiche = d["classements"].get(cle) or {}
            if fiche.get("id") and fiche.get("debut") != debut.isoformat():
                file.append(dict(fiche, cle=cle))
                fiche = {}
                d["classements"].pop(cle, None)
            try:
                lignes = classement(debut, fin, d)
            except Exception as e:                           # noqa: BLE001
                out[cle] = f"relevé raté ({type(e).__name__})"
                continue
            texte = _texte(titre, debut, fin, lignes, combien, cle)
            if fiche.get("id"):
                code, _ = _api("PATCH", f"/channels/{salon}/messages/{fiche['id']}",
                               json={"content": texte, "allowed_mentions": {"parse": []}})
                if code != 404:
                    out[cle] = f"réédité ({code})"
                    continue
            code, r = _api("POST", f"/channels/{salon}/messages",
                           json={"content": texte, "allowed_mentions": {"parse": []}})
            if code in (200, 201) and isinstance(r, dict):
                d["classements"][cle] = {"id": str(r["id"]), "debut": debut.isoformat(),
                                         "fin": fin.isoformat()}
            out[cle] = f"posté ({code})"
        reste = []
        for f in file:
            try:
                if not _figer(f["cle"], f, d, out):
                    reste.append(f)
            except Exception as e:                           # noqa: BLE001
                out[f"{f['cle']}_{f.get('debut')}"] = f"non figé ({type(e).__name__}: {e})"
                reste.append(f)
        d["classements"]["a_figer"] = reste
        _ecrire(d)
    return out


# ─── Paie (26/11/2026) ───────────────────────────────────────────────────
# Propriétaire : « pour le marché FR mets 0.5 0 à 100, 100-300 0.6, 0.7 300 à
# 500, et 500+ 0.8 ». Même règle que la grille de TRUST INSTAGRAM / TWITTER
# (stats_va.GRILLE) : TOUS les subs d'une quinzaine au prix du palier que leur
# total sur la quinzaine atteint. Montrée au staff seul (/pole-twitter-fr).
GRILLE = ((500, 0.80), (300, 0.70), (100, 0.60), (0, 0.50))


def prix_du_sub(n: int) -> float:
    for seuil, prix in GRILLE:
        if n >= seuil:
            return prix
    return GRILLE[-1][1]


def paie(debut: _dt.date, fin: _dt.date, d: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """[{uid, va, subs, prix, montant}] de la quinzaine, du plus payé au moins."""
    out = []
    for l in classement(debut, fin, d):
        if l["subs"] <= 0:
            continue
        px = prix_du_sub(l["subs"])
        out.append(dict(l, prix=px, montant=round(l["subs"] * px, 2)))
    return out


# ─── Le menu du ticket et la page perso (26/11/2026) ─────────────────────
# Propriétaire, capture du menu d'un VA de Twitter : « comme ça de base non ? »
# — 🔗 Ton lien, 📊 Tes stats, 💳 Paiement. Le menu v2 de tickets_discord lit
# ici le lien de la model du rôle (« une ligne par model et il change en
# fonction du @ »), et « Voir ma page » ouvre /mes-stats avec la clé du VA
# (stats_va.jeton), servie par page_stats.
def lien_menu(uid: str) -> Dict[str, Any]:
    """Ce que tickets_discord._corps_menu attend de liens_va.lien_de."""
    d = etat()
    uid = str(uid)
    info = (d.get("membres") or {}).get(uid) or {}
    liens = (d.get("liens") or {}).get(uid) or {}
    url = next((liens[m]["url"] for m in info.get("models") or [] if (liens.get(m) or {}).get("url")), "")
    out: Dict[str, Any] = {"numero": d["numeros"].get(uid), "pseudo": info.get("pseudo") or ""}
    if url:
        out.update(public_url=url, actif=True)
    return out


def lien_stats(uid: str) -> str:
    import domaines
    import stats_va
    if not str(uid).isdigit():
        return ""
    return f"{domaines.site(POLE_ID)}/mes-stats?t={stats_va.jeton(POLE_ID, uid)}"


def page_stats(uid: str) -> Tuple[int, str]:
    """La page perso d'un VA : ses subs (jour, semaine, quinzaine), son prix du
    sub et ses gains de la quinzaine, ses primes. Rien d'un autre VA."""
    import html as _h
    d = etat()
    uid = str(uid)
    info = (d.get("membres") or {}).get(uid) or {}
    auj = _aujourdhui()
    p = periodes(auj)
    p["jour"] = (auj, auj)
    cases = []
    subs: Dict[str, int] = {}
    for cle, titre in (("jour", "Aujourd'hui"), ("semaine", "Cette semaine"), ("quinzaine", "Cette quinzaine")):
        deb, fin = p[cle]
        try:
            moi = next((l for l in classement(deb, fin, d) if l["uid"] == uid), None)
            subs[cle] = moi["subs"] if moi else 0
            val = str(subs[cle])
        except Exception:                                    # noqa: BLE001
            val = "—"
        cases.append(f"<div class=c><span>{titre}</span><b>{val}</b><small>subs</small></div>")
    q = subs.get("quinzaine")
    gains = ""
    if q is not None:
        px = prix_du_sub(q)
        gains = (f"<div class=c><span>Gains de la quinzaine</span><b>{q * px:.2f} $</b>"
                 f"<small>{q} × {px:.2f} $</small></div>")
    primes_vues = [k.split(":") for k, v in (d.get("primes_dites") or {}).items()
                   if k.endswith(":" + uid) and isinstance(v, int)]
    pr = [f"Prime {'de la semaine' if c == 'semaine' else 'du jour'} du {deb_}" for c, deb_, _u in primes_vues]
    liens = (d.get("liens") or {}).get(uid) or {}
    mes_liens = "".join(
        f"<li>{_h.escape(NOMS[m])} : <a href=\"{_h.escape(f['url'])}\">{_h.escape(f['url'])}</a></li>"
        for m, f in liens.items() if m in (info.get("models") or []) and f.get("url"))
    grille = " · ".join(f"{s_}+ : {p_:.2f} $" for s_, p_ in sorted(GRILLE))
    models = ", ".join(NOMS[m] for m in info.get("models") or []) or "sans model"
    page = ("<!doctype html><html lang=fr><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'><title>Mes stats</title>"
            "<style>body{font:15px/1.5 -apple-system,system-ui,sans-serif;background:#0f1115;color:#e5e7eb;"
            "padding:16px;max-width:640px;margin:auto}"
            ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}"
            ".c{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:12px;display:flex;flex-direction:column}"
            ".c span{color:#9ca3af;font-size:13px}.c b{font-size:26px}.c small{color:#6b7280}"
            "a{color:#60a5fa;word-break:break-all}</style></head><body>"
            f"<h1>📊 Mes stats</h1><p>VA {d['numeros'].get(uid, '?')} · @{_h.escape(str(info.get('pseudo') or ''))}"
            f" · {_h.escape(models)}</p>"
            f"<div class=g>{''.join(cases)}{gains}</div>"
            f"<p>Prix du sub sur la quinzaine : {_h.escape(grille)} (tous tes subs au palier atteint).</p>"
            + (f"<h2>Mes liens</h2><ul>{mes_liens}</ul>" if mes_liens else "<p>Pas encore de lien.</p>")
            + (f"<h2>Mes primes</h2><ul>{''.join(f'<li>{_h.escape(x)}</li>' for x in pr)}</ul>" if pr else "")
            + "<p><small>Les subs arrivent de MyPuls avec un peu de retard (30 min environ).</small></p>"
            "</body></html>")
    return 200, page


def _boucle() -> None:
    time.sleep(60)
    dernier = 0.0
    while True:
        try:
            tour()
        except Exception as e:                               # noqa: BLE001
            _log(f"tour en échec : {type(e).__name__}: {e}")
        try:
            auto = creer_au_role()
            if auto["crees"] or auto["echecs"]:
                _log(f"liens au rôle : {auto}")
        except Exception as e:                               # noqa: BLE001
            _log(f"liens au rôle en échec : {type(e).__name__}: {e}")
        if time.time() - dernier >= CLASSEMENT_S:
            try:
                _log(f"classements : {publier_classements()}")
            except Exception as e:                           # noqa: BLE001
                _log(f"classements en échec : {type(e).__name__}: {e}")
            dernier = time.time()
        time.sleep(TOUR_S)


def demarrer() -> None:
    """Au démarrage du site (web_upload), sur le VPS seulement."""
    if _DEMARRE[0]:
        return
    _DEMARRE[0] = True
    threading.Thread(target=_boucle, name="pole-twitter-fr", daemon=True).start()


def categorie_pour_membre(uid: str) -> str:
    """La catégorie où naît le salon d'un VA (ouvrir_ticket) : celle de sa
    model, sinon « 🆕 SANS MODEL ». « » si Discord ne répond pas."""
    try:
        with _VERROU:
            d = etat()
            code, roles = _api("GET", f"/guilds/{POLE_ID}/roles")
            code2, m = _api("GET", f"/guilds/{POLE_ID}/members/{uid}")
            code3, salons = _api("GET", f"/guilds/{POLE_ID}/channels")
            if not (code == code2 == code3 == 200):
                return ""
            rids = assurer_roles(roles, d)
            mods = models_du_membre(m, rids)
            cid = _categorie(salons, CATEGORIE[mods[0]] if mods else CATEGORIE_SANS, d)
            _ecrire(d)
            return cid
    except Exception as e:                                   # noqa: BLE001
        _log(f"catégorie de {uid} : {type(e).__name__}: {e}")
        return ""


# ─── « Créer son lien » (27/11/2026) ─────────────────────────────────────
# Propriétaire : « cree le lien ça crée un lien avec le emma si le mec a le
# tag emma », puis « il faut bien que ça soit un truc genre Twitter […] pour
# le marché français, un peu comme sur l'autre marché ». Comme TRUST TWITTER :
# une adresse sans prénom (« angelyy », liens_va.mots_sans_prenom) et un
# tracking MyPuls au nom du VA, « Twitter FR <Model> VA n @pseudo ». La page
# est une copie de la page modèle de la model du rôle (espace perso
# GetMySocial, où vivent les six pages modèles : un duplicata reste dans
# l'espace de sa source).
#
# Ce qui ne se défait pas : un tracking MyPuls ne s'efface jamais. La copie de
# la page vient donc D'ABORD (GetMySocial refuse : rien de créé chez
# MyPuls) ; un tracking déjà au même nom est repris, jamais doublé ; un essai
# raté garde sa page et ses trackings (« echecs ») pour le clic suivant.
GABARITS = {
    "amelia": "lnk_6a1eab91bc03b4376dd15ade",    # ameliatempalte (OF + MYM)
    "emma": "lnk_6a1eab77e11d56977a3cfe5f",      # emmatemplatee (MYM)
    "lola": "lnk_6a1eab9dbc03b4376dd15d68",      # lolatemplate (OF + MYM)
    "julia": "lnk_6a1eabd9bc03b4376dd16455",     # juliateamplte (OF + MYM)
    "sarah": "lnk_6a1eabace11d56977a3d000f",     # sarahtemaplte (MYM ; son OF n'est pas chez MyPuls)
    "alicia": "lnk_6a3da5f27c98eff5cb529b63",    # aliciatemplate (MYM)
}


def nom_du_lien(model: str, numero: Any, pseudo: str) -> str:
    return f"Twitter FR {NOMS[model]} VA {numero} @{pseudo}"[:60]


def models_en_direct(uid: str) -> Tuple[Optional[List[str]], str]:
    """(models du rôle du membre, pseudo), lus sur Discord à l'instant : un
    rôle donné il y a une minute compte déjà. (None, "") si Discord se tait."""
    with _VERROU:
        d = etat()
        code, roles = _api("GET", f"/guilds/{POLE_ID}/roles")
        code2, m = _api("GET", f"/guilds/{POLE_ID}/members/{uid}")
        if code != 200 or code2 != 200 or not isinstance(m, dict):
            return None, ""
        rids = assurer_roles(roles, d)
        u = m.get("user") or {}
        uid = str(uid)
        if uid not in d["numeros"]:
            d["numeros"][uid] = len(d["numeros"]) + 1
        _ecrire(d)
        return models_du_membre(m, rids), str(u.get("username") or uid)


def a_creer(uid: str) -> List[str]:
    """Les models du rôle de ce VA (dernier tour) qui n'ont pas encore de lien :
    ce que « Créer son lien » ferait. Pour dessiner le bouton."""
    d = etat()
    uid = str(uid)
    mods = ((d.get("membres") or {}).get(uid) or {}).get("models") or []
    liens = (d.get("liens") or {}).get(uid) or {}
    return [m for m in mods if not (liens.get(m) or {}).get("url")]


def _creer_un(uid: str, pseudo: str, model: str, par: str) -> Dict[str, Any]:
    import gms
    import liens_fr
    import liens_va
    import liens_jb_fr
    cfg = liens_fr.MODELS.get(model) or {}
    with liens_fr._VERROU:
        d = etat()
        deja = ((d["liens"].get(uid) or {}).get(model) or {})
        if deja.get("url"):
            return {"ok": True, "deja": True, "model": model, "url": deja["url"]}
        cle = f"{uid}:{model}"
        ancien = (d.get("echecs") or {}).get(cle) or {}
        n = ancien.get("numero") or d["numeros"].get(uid) or "?"
        nom = ancien.get("nom") or nom_du_lien(model, n, pseudo)
        urls: Dict[str, str] = dict(ancien.get("trackings") or {})
        link_id, sc = str(ancien.get("link_id") or ""), str(ancien.get("shortcode") or "")
        soucis: List[str] = []

        def echec(erreur: str) -> Dict[str, Any]:
            if link_id:
                # la copie garde les boutons de la page modèle : coupée tant
                # qu'elle n'a pas SES trackings, jamais donnée — ni supprimée
                try:
                    gms.disable_link(link_id)
                except Exception:                            # noqa: BLE001
                    pass
            if urls or link_id:
                d2 = etat()
                d2.setdefault("echecs", {})[cle] = {
                    "numero": n, "nom": nom, "trackings": dict(urls), "link_id": link_id,
                    "shortcode": sc, "erreur": erreur, "quand": int(time.time())}
                _ecrire(d2)
            _log(f"{nom} : ÉCHEC {erreur}")
            return {"ok": False, "model": model, "erreur": erreur, "trackings": dict(urls)}

        lu = gms._call_tool("get_link", {"link_id": GABARITS[model]})
        gabarit = liens_fr._objet(lu) if lu.get("ok") else {}
        boutons = gabarit.get("buttons") or []
        if not boutons:
            return echec(f"page modèle de {NOMS[model]} illisible ({str(lu.get('error'))[:120]})")
        plates = sorted({liens_fr.plateforme(b.get("url")) for b in boutons} - {""})
        plates = [p for p in plates if cfg.get(p)]
        if not plates:
            return echec(f"la page modèle de {NOMS[model]} n'a aucun bouton OF ni MYM suivi par MyPuls")

        # 1) la page, copiée de la page modèle
        if not link_id:
            for essai in range(liens_va.ESSAIS_ADRESSE):
                sc = liens_va.mots_sans_prenom(nom, essai)
                r = gms.duplicate_link(GABARITS[model], sc, nom)
                if r.get("ok"):
                    link_id = str((r.get("link") or {}).get("id") or "")
                    break
                err = str(r.get("error") or "")
                if "shortcode" not in err.lower():
                    sc = ""
                    return echec(f"GetMySocial refuse la copie : {err[:160]}")
            if not link_id:
                sc = ""
                return echec("GetMySocial : aucune adresse libre")

        # 2) les trackings MyPuls, au nom du VA — repris s'ils existent déjà
        tn = liens_fr.nom_tracking(nom)
        for p in plates:
            if urls.get(p):
                continue
            cid = int(cfg[p])
            ex = liens_va._tracking_existant(tn, cid)
            t = {"ok": True, "url": ex["url"]} if ex else liens_fr.creer_tracking(tn, cid)
            if t.get("ok") and t.get("url"):
                urls[p] = t["url"]
            else:
                soucis.append(f"{p.upper()} : {t.get('erreur')}")
        if not urls:
            return echec("aucun tracking MyPuls créé (" + " ; ".join(soucis)[:300] + ")")

        # 3) les boutons vers SES trackings (un bouton sans tracking est retiré)
        neufs = [{k: v for k, v in b.items() if k != "block_id" and v is not None}
                 for b in liens_fr.boutons_remplaces(boutons, urls)]
        r = liens_jb_fr._appel("update_link", {"link_id": link_id, "display_name": nom,
                                               "buttons": neufs})
        if not r.get("ok"):
            return echec(f"boutons non posés ({str(r.get('error'))[:160]})")
        if ancien.get("link_id"):
            gms.enable_link(link_id)              # coupée par l'essai raté
        public = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
        poser_lien(uid, model, public, par=par, trackings=sorted(urls.values()))
        with _VERROU:
            d3 = etat()
            f = d3["liens"].get(uid, {}).get(model)
            if f is not None:
                f.update(link_id=link_id, shortcode=sc, nom=nom, cree=True, soucis=soucis)
            (d3.get("echecs") or {}).pop(cle, None)
            _ecrire(d3)
        _log(f"{nom} -> {public} (trackings {sorted(urls)}, soucis {soucis})")
        return {"ok": True, "model": model, "url": public, "trackings": dict(urls), "soucis": soucis}


def creer_lien(uid: str, par: str = "") -> Dict[str, Any]:
    """« Créer son lien » : un lien par model du rôle de ce VA qui n'en a pas.
    Rend {ok, faits: [...], erreur}. Bloquant (réseau) : à lancer en fond."""
    uid = str(uid)
    mods, pseudo = models_en_direct(uid)
    if mods is None:
        return {"ok": False, "erreur": "Discord ne répond pas : rien n'a été créé, reclique dans une minute."}
    if not mods:
        return {"ok": False, "erreur": "ce VA n'a aucun rôle de model (Amelia, Emma, Lola, Julia, "
                                       "Sarah, Alicia) : donne-lui le rôle, puis reclique."}
    faits = []
    for m in mods:
        try:
            faits.append(_creer_un(uid, pseudo, m, par))
        except Exception as e:                               # noqa: BLE001
            faits.append({"ok": False, "model": m, "erreur": f"{type(e).__name__}: {e}"})
    try:
        tour()                     # le lien posé dans le ticket, le menu redessiné
    except Exception as e:                                   # noqa: BLE001
        _log(f"tour après création : {type(e).__name__}: {e}")
    return {"ok": any(f.get("ok") for f in faits), "faits": faits, "pseudo": pseudo}


def texte_creation(uid: str, r: Dict[str, Any]) -> str:
    """La réponse au manager, une ligne par model."""
    if not r.get("faits"):
        return "✕ " + str(r.get("erreur") or "échec")
    lignes = []
    for f in r["faits"]:
        nom = NOMS.get(f.get("model"), f.get("model"))
        if f.get("ok") and f.get("deja"):
            lignes.append(f"🔗 {nom} : déjà fait — {f['url']}")
        elif f.get("ok"):
            s = f.get("soucis") or []
            lignes.append(f"✅ {nom} : lien créé pour <@{uid}> — {f['url']}"
                          + (f"\n⚠️ {' ; '.join(s)[:300]} (bouton retiré de la page)" if s else ""))
        else:
            lignes.append(f"✕ {nom} : {str(f.get('erreur'))[:400]}")
    return "\n".join(lignes)


# ─── Le lien créé tout seul au rôle (27/11/2026) ─────────────────────────
# Propriétaire : « quand le mec il met un rôle Lola, lui créer son lien sur
# Lola […] si le mec il revient sur Amelia, ça lui met pas à recréer un lien,
# son lien il est déjà là ». Après chaque tour : un VA dont le rôle de model
# n'a pas encore de lien reçoit le sien (_creer_un, comme le bouton). Un lien
# déjà fait reste dans sa case quand le rôle change : il revient avec le rôle,
# rien n'est recréé. Un essai raté (MYM bloqué par le code MyPuls) n'est
# retenté qu'au bout de REPRISE_S : sa page est gardée, aucun tracking n'est
# doublé, mais un essai toutes les 5 min pour rien remplirait le journal.
REPRISE_S = 60 * 60
AUTO_PAR_TOUR = 5


def creer_au_role() -> Dict[str, Any]:
    d = etat()
    bilan: Dict[str, Any] = {"crees": [], "echecs": []}
    maintenant = time.time()
    a_faire = []
    for uid, info in (d.get("membres") or {}).items():
        for m in a_creer(uid):
            e = (d.get("echecs") or {}).get(f"{uid}:{m}") or {}
            if e and maintenant - float(e.get("quand") or 0) < REPRISE_S:
                continue
            a_faire.append((uid, str(info.get("pseudo") or uid), m))
    for uid, pseudo, m in a_faire[:AUTO_PAR_TOUR]:
        try:
            r = _creer_un(uid, pseudo, m, "bot (rôle de model)")
        except Exception as e:                               # noqa: BLE001
            r = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        if r.get("ok") and not r.get("deja"):
            bilan["crees"].append(f"{pseudo}/{m} {r.get('url')}")
        elif not r.get("ok"):
            bilan["echecs"].append(f"{pseudo}/{m} : {str(r.get('erreur'))[:160]}")
    if bilan["crees"]:
        tour()                     # le lien posé dans le ticket, le menu redessiné
    return bilan
