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


def poser_lien(uid: str, model: str, url: str, par: str = "") -> Dict[str, Any]:
    """Le lien de ce VA pour cette model (url vide : retiré). Rend la fiche."""
    uid, model, url = str(uid), str(model).lower(), str(url or "").strip()
    if model not in MODELS:
        raise ValueError("model inconnue")
    if url and not re.match(r"https?://\S+$", url):
        raise ValueError("lien invalide")
    tr = trackings_du_lien(url) if url else []
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


def _texte(titre: str, debut: _dt.date, fin: _dt.date, lignes: List[Dict[str, Any]], podium: bool) -> str:
    medailles = ("🥇", "🥈", "🥉")
    t = [f"## {titre}", f"Du {debut:%d/%m} au {fin:%d/%m} · en abonnés · mis à jour <t:{int(time.time())}:R>", ""]
    if not lignes:
        t.append("_Personne encore : les liens se posent sur le dashboard._")
    for i, l in enumerate(lignes[:3 if podium else 40]):
        rang = medailles[i] if i < 3 else f"**{i + 1}.**"
        t.append(f"{rang} {l['va']} — **{l['subs']}** sub{'s' if l['subs'] > 1 else ''}")
    return "\n".join(t)[:1990]


def publier_classements() -> Dict[str, Any]:
    """Un message par période, réédité ; une nouvelle période = un nouveau
    message (l'ancien reste, figé)."""
    out = {}
    with _VERROU:
        d = etat()
        p = periodes()
        for cle, salon, titre, podium in (("semaine", SALON_SEMAINE, "🏆 Podium de la semaine", True),
                                          ("quinzaine", SALON_QUINZAINE, "📈 Classement de la quinzaine", False)):
            if not salon:
                continue
            debut, fin = p[cle]
            try:
                lignes = classement(debut, fin, d)
            except Exception as e:                           # noqa: BLE001
                out[cle] = f"relevé raté ({type(e).__name__})"
                continue
            texte = _texte(titre, debut, fin, lignes, podium)
            fiche = d["classements"].get(cle) or {}
            if fiche.get("debut") == debut.isoformat() and fiche.get("id"):
                code, _ = _api("PATCH", f"/channels/{salon}/messages/{fiche['id']}",
                               json={"content": texte, "allowed_mentions": {"parse": []}})
                if code != 404:
                    out[cle] = f"réédité ({code})"
                    continue
            code, r = _api("POST", f"/channels/{salon}/messages",
                           json={"content": texte, "allowed_mentions": {"parse": []}})
            if code in (200, 201) and isinstance(r, dict):
                d["classements"][cle] = {"id": str(r["id"]), "debut": debut.isoformat()}
            out[cle] = f"posté ({code})"
        _ecrire(d)
    return out


def _boucle() -> None:
    time.sleep(60)
    dernier = 0.0
    while True:
        try:
            tour()
        except Exception as e:                               # noqa: BLE001
            _log(f"tour en échec : {type(e).__name__}: {e}")
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
