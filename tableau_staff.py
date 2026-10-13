"""Le tableau staff : l'état de chaque VA, pour les managers, serveur par serveur.

Propriétaire, 13/10/2026, devant les pastilles des salons de Threads :
« montre-moi le tableau pour le staff », puis « fais ça aussi pour les autres
groupes, IG, Twitter ». Un message (ou plusieurs pages) dans un salon que seul
le staff voit, réédité toutes les heures : chaque VA, son lien, les visites de
ce lien sur les JOURS derniers jours, et sa pastille.

  🟢 son lien a eu des visites     🟠 un lien, mais aucune visite
  🔵 pas encore de lien            🔴 pas de lien, plus rien depuis JOURS jours

CHAQUE SERVEUR A SES DONNÉES (choix du propriétaire, même jour) :
  - Threads : les tickets (tickets_discord) et leur lien Threads (liens_va) ;
    la pastille est celle du salon (tickets_discord.rond_du_va), le manager
    la catégorie du ticket.
  - Twitter : « par numéro de VA ». Les pages JESSY LE RETOUR, où travaille la
    plupart des VA, ne sont reliées à AUCUN compte Discord (podium_discord,
    en-tête) : une ligne par numéro du registre des trackings (le même que le
    podium), ses pages et leurs visites, sans ticket.
  - Va IG : « par model, tous ses liens » : une section par model, chaque VA
    avec SON lien de cette model (liens_fr) ; un VA de deux models paraît
    dans les deux. Les comptes sans limite du propriétaire n'y sont pas.

LES VISITES : get_link_metrics de GetMySocial, un appel par espace et par
centaine de liens (« pageviews » : les visites d'une page, ou les passages
d'un lien direct). Un espace qui ne répond pas : le tableau n'est pas refait
(une page de zéros mentirait), et c'est dit au journal.

Le salon est créé s'il manque, fermé à @everyone, ouvert aux rôles du staff
et au bot. Les noms des VA y paraissent : personne d'autre ne le voit.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"

TWITTER_ID = "1445108485090971710"
THREADS_ID = "1498948161039896586"
VA_IG_ID = "1505418484052394004"

#: Les serveurs qui ont un tableau, et le nom de son salon (le style de chacun)
SALONS = {TWITTER_ID: "─│📊┤-suivi-va", THREADS_ID: "─│📊┤-suivi-va",
          VA_IG_ID: "📊・suivi-va"}
#: Les espaces GetMySocial de Twitter : JESSY LE RETOUR (pages) et EMY TWITTER
#: (liens « Créer son lien ») — podium_discord.EQUIPES_VA
EQUIPES_TWITTER = ("tm_6a0e4739bfa0c238f20a8bf5", "tm_6ab46ebb11a0232c11211b1a")
JOURS = 2
MINUTES = 60
#: Une page de message : Discord coupe une description à 4096 caractères, et
#: refuse plus de 6000 sur l'ensemble d'un message ; une page par message.
TAILLE_PAGE = 3800

VERT, ORANGE, BLEU, ROUGE, SANS_NUMERO = "🟢", "🟠", "🔵", "🔴", "❔"
ORDRE = (VERT, ORANGE, BLEU, ROUGE, SANS_NUMERO)
TITRES = {VERT: "Leur lien fait des visites", ORANGE: "Lien sans visite, ou coupé",
          BLEU: "Pas encore de lien", ROUGE: f"Sans lien, plus rien depuis {JOURS} jours",
          SANS_NUMERO: "Sans numéro de VA (tracking neuf, partagé ou absent)"}
#: Des sections qui ne paraissent que si elles ont quelqu'un
_SI_PLEINES = (ROUGE, SANS_NUMERO)

VOIR, ECRIRE, LIENS, HISTORIQUE = 1 << 10, 1 << 11, 1 << 14, 1 << 16

_VERROU = threading.Lock()


def _fichier_etat() -> Path:
    # relu à chaque appel : les tests déplacent DATA_DIR
    return DATA_DIR / "tableau_staff.json"


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


def _maintenant_paris() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:                                        # noqa: BLE001
        return dt.datetime.now()


# ─── les visites ────────────────────────────────────────────────────────
def visites(equipes) -> Optional[Dict[str, int]]:
    """{link_id: visites sur les JOURS derniers jours} pour tous les liens de
    ces espaces. None si l'un d'eux ne répond pas : pas de faux zéro."""
    import gms
    auj = _maintenant_paris().date()
    out: Dict[str, int] = {}
    for equipe in equipes:
        args: Dict[str, Any] = {"team_id": equipe, "limit": 100, "timezone": "Europe/Paris",
                                "start_date": (auj - dt.timedelta(days=JOURS)).isoformat(),
                                "end_date": auj.isoformat()}
        for _page in range(30):
            r = gms._call_tool("get_link_metrics", args)
            d = r.get("data") if r.get("ok") else None
            lignes = d.get("data") if isinstance(d, dict) else None
            if not isinstance(lignes, list):
                print(f"[tableau] visites de {equipe} illisibles ({str(r.get('error'))[:80]})",
                      flush=True)
                return None
            for x in lignes:
                if isinstance(x, dict) and x.get("key"):
                    out[str(x["key"])] = out.get(str(x["key"]), 0) + int(x.get("pageviews") or 0)
            if not d.get("has_more") or not d.get("next_cursor"):
                break
            args["cursor"] = d["next_cursor"]
    return out


def _date_salon(cid: str) -> float:
    """L'heure de création d'un salon, lue dans son identifiant (Discord)."""
    try:
        return ((int(cid) >> 22) + 1420070400000) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _pluriel(n: int, mot: str) -> str:
    return f"**{n}** {mot}{'s' if n > 1 else ''}"


# ─── Threads ────────────────────────────────────────────────────────────
def _lignes_threads(salons: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    import liens_va as lv
    import tickets_discord as tk
    gid = THREADS_ID
    vis = visites([str(lv.espace(gid)["equipe"])])
    if vis is None:
        return None
    par_id = {str(c.get("id")): c for c in salons if isinstance(c, dict)}
    cats = {i: c.get("name") for i, c in par_id.items() if c.get("type") == 4}
    out = []
    for cle, f in sorted((tk._etat().get("tickets") or {}).items()):
        if not str(cle).startswith(f"{gid}:") or not isinstance(f, dict) or not f.get("salon"):
            continue
        uid = str(cle).split(":", 1)[1]
        c = par_id.get(str(f["salon"]))
        if not c:
            continue                       # salon disparu : plus un VA du serveur
        nom = str(c.get("name") or "")
        i = nom.find(f"-va-{tk.AROBASE}")
        pseudo = nom[i + len(f"-va-{tk.AROBASE}"):] if i >= 0 else nom
        m = re.search(r"-(\d+)$", nom[:i]) if i >= 0 else None
        l = lv.lien_de(gid, uid) or {}
        lid = str(l.get("link_id") or "")
        n = int(m.group(1)) if m else int(l.get("numero") or 0)
        rond = tk.rond_du_va(gid, uid, vis, dict(f, ouvert=f.get("ouvert") or _date_salon(f["salon"])))
        coupe = bool(lid) and l.get("actif") is False
        # un lien coupé : 🟠 comme son salon (rond_du_va) ; ses visites d'avant
        # la coupure ne comptent pas, sinon « sans visite » et « 12 visites »
        v = int(vis.get(lid) or 0) if lid and not coupe else 0
        manager = tk._cle_categorie(cats.get(str(c.get("parent_id") or ""), "")) or "—"
        morceaux = [f"`VA {n}`" if n else "`VA ?`", pseudo]
        if coupe:
            morceaux += [f'`{l.get("shortcode") or "?"}`', "lien coupé"]
        elif lid:
            morceaux += [f'`{l.get("shortcode") or "?"}`', _pluriel(v, "visite")]
        morceaux += [manager, f'<#{f["salon"]}>']
        out.append({"rond": rond or BLEU, "n": n or 10 ** 6, "visites": v,
                    "texte": " · ".join(morceaux)})
    return out


# ─── Twitter ────────────────────────────────────────────────────────────
def _lignes_twitter(salons: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """Une ligne par numéro de VA du registre des trackings (le podium)."""
    import clics_personnes as cp
    import podium_discord as pd
    vis = visites(EQUIPES_TWITTER)
    if vis is None:
        return None
    liens, frais = pd.liens_bruts(TWITTER_ID, "tableau")
    if not frais:
        print("[tableau] Twitter : liste des liens non fraîche, tableau laissé tel quel",
              flush=True)
        return None
    actifs = {str(l.get("id")) for l in liens if pd._actif(l)}
    sc = {str(l.get("id")): str(l.get("shortcode") or "") for l in liens}
    # les pages EN SERVICE, et le doute sur la fenêtre du tableau : sans d0,
    # un tracking quitté en août gardait son « doute » dans le registre et
    # « ⚠️ numéro en doute » restait à vie, quand le podium avait cessé de le
    # dire ; une page coupée « mise de côté » mettait aussi ses VA en doute
    vivants = [l for l in liens if pd._actif(l)]
    auj = _maintenant_paris().date()
    ents = pd.entites(vivants, cp.rattachements_identite())
    table = pd.numeros(list(ents.keys()), attribuer=False)
    groupes, num, doute, _cause = pd._par_tracking(
        vivants, ents, table, (auj - dt.timedelta(days=JOURS)).isoformat(), auj.isoformat())
    out = []
    sans_num = 0
    for cle, g in groupes.items():
        ids = [i for i in g["ids"] if i in actifs]
        if not ids:
            continue                       # plus aucun lien en service
        # les pages EN SERVICE seulement : une page coupée hier gardait ses
        # visites de la veille et peignait en vert un VA qui ne fait rien
        v = sum(int(vis.get(i) or 0) for i in ids)
        pages = ", ".join(f"`{sc.get(i) or '?'}`" for i in ids[:3]) + (
            f" +{len(ids) - 3}" if len(ids) > 3 else "")
        n = num.get(cle)
        if not n:
            # pas de numéro : tracking neuf que MyPuls ne connaît pas encore
            # (deux jours au plus), tracking de deux VA, ou page sans
            # tracking. Le podium le dit à son journal ; ici, une section :
            # ce sont les nouveaux et les cas à régler que le staff doit voir.
            sans_num += 1
            out.append({"rond": SANS_NUMERO, "n": 10 ** 6, "visites": v,
                        "texte": f"{cle} · {pages} · {_pluriel(v, 'visite')}"})
            continue
        out.append({"rond": VERT if v else ORANGE, "n": n, "visites": v,
                    "texte": f"`VA {n}`{' SPAM' if g.get('spam') else ''} · {pages} · "
                             f"{_pluriel(v, 'visite')}"
                             + (" · ⚠️ numéro en doute" if n in doute else "")})
    if sans_num:
        print(f"[tableau] Twitter : {sans_num} groupe(s) de pages sans numéro de VA",
              flush=True)
    return out


# ─── Va IG ──────────────────────────────────────────────────────────────
def _activite_ig(uid: str) -> float:
    """La dernière activité d'un VA de Va IG (cogs/vaactivity : messages des
    salons de VA, clics sur les boutons des bots), 0 si inconnue."""
    d = safe_json.load(DATA_DIR / "va_activity.json", default={}) or {}
    brut = str(((d.get(str(uid)) or {}) if isinstance(d, dict) else {}).get("_last") or "")
    if not brut:
        return 0.0
    try:
        t = dt.datetime.fromisoformat(brut)
        if t.tzinfo is None:
            from zoneinfo import ZoneInfo
            t = t.replace(tzinfo=ZoneInfo("Europe/Paris"))
        return t.timestamp()
    except Exception:                                        # noqa: BLE001
        return 0.0


def _lignes_ig(salons: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """« Par model, tous ses liens » : (model, VA) -> son lien de cette model."""
    import liens_fr
    vis = visites([liens_fr.EQUIPE])
    if vis is None:
        return None
    par_id = {str(c.get("id")): c for c in salons if isinstance(c, dict)}
    cats = {i: str(c.get("name") or "").strip().lower() for i, c in par_id.items()
            if c.get("type") == 4}
    models = set(liens_fr.MODELS)
    sans_limite = {str(x) for x in getattr(liens_fr, "SANS_LIMITE", set())}
    users = safe_json.load(DATA_DIR / "users.json", default={}) or {}
    numeros = safe_json.load(DATA_DIR / "numeros_va_fr.json", default={}) or {}
    liens = (liens_fr._etat().get("liens") or {})
    vus = set()
    out = []
    # les VA du serveur : un salon de Va IG ; leur model, la catégorie du salon
    for uid, u in (users.items() if isinstance(users, dict) else []):
        if not isinstance(u, dict) or str(uid) in sans_limite:
            continue
        c = par_id.get(str(u.get("channel_id") or ""))
        if not c:
            continue
        model = cats.get(str(c.get("parent_id") or ""), "")
        les_models = {model} if model in models else set()
        # les models de ses liens EN SERVICE : un lien coupé (rôle retiré,
        # liens_fr.aligner) n'en fait plus un VA de cette model
        les_models |= {k.split(":", 1)[1] for k, e in liens.items()
                       if k.startswith(f"{uid}:")
                       and not (isinstance(e, dict) and e.get("actif") is False)}
        for m in sorted(les_models & models):
            vus.add((str(uid), m))
            out.append(_ligne_ig(str(uid), m, liens.get(f"{uid}:{m}") or {}, c, vis, numeros))
    # un lien dont le VA n'a plus de salon ici : dit, pas perdu
    for k, l in liens.items():
        uid, _, m = k.partition(":")
        if (uid, m) in vus or uid in sans_limite or m not in models or l.get("actif") is False:
            continue
        out.append(_ligne_ig(uid, m, l, None, vis, numeros))
    return out


def _ligne_ig(uid: str, model: str, l: Dict[str, Any], salon: Optional[Dict[str, Any]],
              vis: Dict[str, int], numeros: Dict[str, Any]) -> Dict[str, Any]:
    import liens_fr
    nom_m = liens_fr.MODELS[model]["nom"]
    n = int(l.get("numero") or (numeros.get(model) or {}).get(str(uid)) or 0)
    coupe = bool(l.get("link_id")) and l.get("actif") is False
    lid = str(l.get("link_id") or "") if not coupe else ""
    v = int(vis.get(lid) or 0) if lid else 0
    if coupe:
        rond = ORANGE                      # un lien, coupé : pas « sans lien »
    elif lid:
        rond = VERT if v else ORANGE
    else:
        delai = JOURS * 86400
        ouvert = _date_salon(str((salon or {}).get("id") or ""))
        rond = (ROUGE if time.time() - ouvert >= delai
                and time.time() - _activite_ig(uid) >= delai else BLEU)
    pseudo = str(l.get("pseudo") or "")
    if not pseudo and salon:
        pseudo = re.sub(r"^.*?va-", "", str(salon.get("name") or ""))
    morceaux = [f"{rond} `{nom_m} VA {n}`" if n else f"{rond} `{nom_m} VA ?`", pseudo or "?"]
    if coupe:
        morceaux += [f'`{l.get("shortcode") or "?"}`', "lien coupé"]
    elif lid:
        morceaux += [f'`{l.get("shortcode") or "?"}`', _pluriel(v, "visite")]
    morceaux.append(f"<#{salon['id']}>" if salon else "_sans salon_")
    return {"rond": rond, "n": n or 10 ** 6, "visites": v, "section": nom_m,
            "texte": " · ".join(morceaux)}


# ─── le message ─────────────────────────────────────────────────────────
NOMS = {THREADS_ID: "Threads", TWITTER_ID: "Twitter", VA_IG_ID: "Va IG"}


def pages(gid: str, lignes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Les embeds du tableau, une page par message. Threads et Twitter : une
    section par pastille ; Va IG : une section par model."""
    gid = str(gid)
    lignes = sorted(lignes, key=lambda x: (ORDRE.index(x["rond"]) if x["rond"] in ORDRE else 9,
                                           x["n"], x["texte"]))
    blocs: List[str] = []
    if gid == VA_IG_ID:
        for model in sorted({x.get("section", "") for x in lignes}):
            les = [x for x in lignes if x.get("section", "") == model]
            blocs.append(f"**{model} — {len(les)}**\n" + "\n".join(x["texte"] for x in les))
    else:
        for rond in ORDRE:
            les = [x for x in lignes if x["rond"] == rond]
            if not les and rond in _SI_PLEINES:
                continue
            blocs.append(f"{rond} **{TITRES[rond]} — {len(les)}**"
                         + ("\n" + "\n".join(x["texte"] for x in les) if les else ""))
    total = sum(x["visites"] for x in lignes)
    compte = {r: sum(1 for x in lignes if x["rond"] == r) for r in ORDRE}
    # la fenêtre réelle : J-JOURS à aujourd'hui compris (comme les pastilles
    # des salons, tickets_discord._clics_recents), soit JOURS + 1 dates ;
    # « en 2 jours » couvrait en fait trois jours du calendrier
    maintenant = _maintenant_paris()
    debut = (maintenant.date() - dt.timedelta(days=JOURS)).strftime("%d/%m")
    bas = (f"👥 {len(lignes)} ligne{'s' if len(lignes) > 1 else ''} · {total} visite"
           f"{'s' if total > 1 else ''} depuis le {debut} · "
           + " ".join(f"{r} {compte[r]}" for r in ORDRE if compte[r]))
    tete = (f"_visites des liens depuis le {debut}, aujourd'hui compris · mis à jour à "
            f"{maintenant.strftime('%Hh%M')}_")
    morceaux: List[List[str]] = [[]]
    taille = 0
    for b in blocs:
        for ligne in b.split("\n"):
            if taille + len(ligne) + 1 > TAILLE_PAGE and morceaux[-1]:
                morceaux.append([])
                taille = 0
            morceaux[-1].append(ligne)
            taille += len(ligne) + 1
        morceaux[-1].append("")
        taille += 1
    out = []
    for k, m in enumerate(morceaux, start=1):
        corps = (tete + "\n\n" if k == 1 else "") + "\n".join(m).rstrip()
        if k == len(morceaux):
            corps += "\n\n" + bas
        titre = f"📊 Suivi des VA — {NOMS.get(gid, gid)}"
        if len(morceaux) > 1:
            titre += f" ({k}/{len(morceaux)})"
        out.append({"title": titre, "description": corps[:4096], "color": 0x3B82F6})
    return out


# ─── le salon et la publication ─────────────────────────────────────────
def _roles_staff(gid: str) -> List[str]:
    try:
        import verif_discord as vd
        cfg = vd.serveur(gid) or {}
    except Exception:                                        # noqa: BLE001
        cfg = {}
    roles = [str(cfg.get("role_manager") or "")]
    if gid in (TWITTER_ID, THREADS_ID):
        try:
            import tickets_discord as tk
            roles.append(tk.role_helper(gid))
        except Exception:                                    # noqa: BLE001
            pass
    return [r for r in roles if r]


def _salon(gid: str, salons: List[Dict[str, Any]], connu: str = "") -> str:
    """Le salon du tableau, créé fermé s'il manque. « » si impossible.

    Celui qu'on connaît d'abord (son identifiant, data/tableau_staff.json) :
    le propriétaire redécore ses salons à la main (« ─│📊┤-subs » est devenu
    « ─│👤┤-subs »), et un salon cherché au seul nom aurait été recréé à
    côté, l'ancien gardant pour toujours un tableau figé."""
    voulu = SALONS[gid]
    for c in salons:
        if isinstance(c, dict) and connu and str(c.get("id")) == str(connu) \
                and c.get("type", 0) == 0:
            return str(c["id"])
    for c in salons:
        if isinstance(c, dict) and c.get("name") == voulu and c.get("type", 0) == 0:
            return str(c["id"])
    code, moi = _api("GET", "/users/@me")
    if code != 200 or not isinstance(moi, dict) or not moi.get("id"):
        return ""
    lus = VOIR | HISTORIQUE
    droits = [{"id": gid, "type": 0, "allow": "0", "deny": str(VOIR)},
              {"id": str(moi["id"]), "type": 1, "allow": str(lus | ECRIRE | LIENS), "deny": "0"}]
    droits += [{"id": r, "type": 0, "allow": str(lus), "deny": "0"} for r in _roles_staff(gid)]
    code, rep = _api("POST", f"/guilds/{gid}/channels",
                     json={"name": voulu, "type": 0, "permission_overwrites": droits,
                           "topic": "Le suivi des VA, pour le staff : mis à jour chaque heure."})
    if code not in (200, 201) or not isinstance(rep, dict) or not rep.get("id"):
        print(f"[tableau] {gid} : salon {voulu} non créé (HTTP {code}) {str(rep)[:100]}",
              flush=True)
        return ""
    print(f"[tableau] {gid} : salon {voulu} créé ({rep['id']}), réservé au staff", flush=True)
    return str(rep["id"])


def _cle_message(mid: str) -> int:
    return int(mid) if str(mid).isdigit() else 0


def _reprendre(salon: str, ids: List[str]) -> Optional[List[str]]:
    """Les pages du tableau postées par le bot mais absentes de l'état : un
    envoi sur un délai dépassé (code 0) ou un 5xx a souvent abouti chez
    Discord. Sans cette reprise, la page était reposée au passage suivant et
    la première restait dans le salon, figée. None si le salon est illisible."""
    c1, moi = _api("GET", "/users/@me")
    c2, msgs = _api("GET", f"/channels/{salon}/messages?limit=50")
    if c1 != 200 or c2 != 200 or not isinstance(moi, dict) or not isinstance(msgs, list):
        return None
    plus = [str(m["id"]) for m in msgs
            if isinstance(m, dict) and m.get("id") and str(m["id"]) not in ids
            and str((m.get("author") or {}).get("id")) == str(moi.get("id"))
            and any(str((x or {}).get("title") or "").startswith("📊 Suivi des VA")
                    for x in m.get("embeds") or [])]
    return ids + plus


def a_publier(gid: str, maintenant: Optional[float] = None) -> bool:
    gid = str(gid)
    if gid not in SALONS:
        return False
    e = (safe_json.load(_fichier_etat(), default={}) or {}).get(gid) or {}
    return (maintenant or time.time()) - float(e.get("vu") or 0) >= MINUTES * 60


def publier(gid: str) -> Dict[str, Any]:
    """Refait le tableau de ce serveur (avec SON bot : sur_serveur(gid))."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"messages": [], "lignes": 0, "erreur": ""}
    if gid not in SALONS:
        return bilan
    if not _VERROU.acquire(blocking=False):
        bilan["erreur"] = "un passage tourne déjà"
        return bilan
    try:
        code, salons = _api("GET", f"/guilds/{gid}/channels")
        if code != 200 or not isinstance(salons, list):
            bilan["erreur"] = f"salons illisibles (HTTP {code})"
            return bilan
        faire = {THREADS_ID: _lignes_threads, TWITTER_ID: _lignes_twitter,
                 VA_IG_ID: _lignes_ig}[gid]
        lignes = faire(salons)
        etat = safe_json.load(_fichier_etat(), default={}) or {}
        e = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
        if lignes is None:
            # GetMySocial muet : le tableau garde ses chiffres, on réessaie
            # dans dix minutes plutôt qu'à l'heure suivante
            bilan["erreur"] = "visites illisibles"
            e["vu"] = time.time() - (MINUTES - 10) * 60
            etat[gid] = e
            safe_json.write(_fichier_etat(), etat)
            return bilan
        bilan["lignes"] = len(lignes)
        salon = _salon(gid, salons, str(e.get("salon") or ""))
        if not salon:
            bilan["erreur"] = "pas de salon"
            return bilan
        if str(e.get("salon") or "") != salon:
            e = {"salon": salon, "messages": []}
        ids = [str(x) for x in e.get("messages") or []]
        if e.get("orphelins"):
            repris = _reprendre(salon, ids)
            if repris is not None:
                ids = repris
                e.pop("orphelins", None)
        lesp = pages(gid, lignes)
        neufs: List[str] = []
        reposte = False

        def _arret(raison: str, garder: List[str]) -> Dict[str, Any]:
            # Discord en panne ou trop lent : la page garde SON message (une
            # édition « ratée » sur un délai dépassé a souvent abouti), rien
            # n'est reposté à côté, nouvel essai dans dix minutes. Avant, toute
            # réponse autre que 200 reposait la page sous la dernière et
            # oubliait l'ancienne, figée pour toujours.
            e.update(salon=salon, messages=neufs + garder,
                     vu=time.time() - (MINUTES - 10) * 60)
            etat[gid] = e
            safe_json.write(_fichier_etat(), etat)
            print(f"[tableau] {gid} : {raison}, nouvel essai dans 10 min", flush=True)
            bilan["erreur"] = raison
            bilan["messages"] = neufs + garder
            return bilan

        for k, page in enumerate(lesp):
            if k < len(ids):
                c, rep = _api("PATCH", f"/channels/{salon}/messages/{ids[k]}", json={"embeds": [page]})
                if c == 200:
                    neufs.append(ids[k])
                    continue
                if c != 404:
                    return _arret(f"page {k + 1} non rééditée (HTTP {c})", ids[k:])
                reposte = True             # supprimée à la main : une neuve
            c, rep = _api("POST", f"/channels/{salon}/messages", json={"embeds": [page]})
            if c == 200 and isinstance(rep, dict) and rep.get("id"):
                neufs.append(str(rep["id"]))
            else:
                # posté quand même ? repris au passage suivant (_reprendre)
                e["orphelins"] = True
                return _arret(f"page {k + 1} refusée (HTTP {c})", ids[k + 1:])
        # une page en trop (le tableau a raccourci) : vidée, jamais supprimée
        tous = neufs + ids[len(lesp):]
        vide = {"description": "_(page vide)_", "color": 0x64748B}
        if reposte or tous != sorted(tous, key=_cle_message):
            # une page reposée (ou reprise) arrive en bas du salon : sans ce
            # tri, « (1/7) » restait pour de bon sous « (7/7) ». Les messages,
            # dans l'ordre où Discord les montre, reçoivent les pages dans
            # l'ordre. Le désordre laissé par un arrêt se répare ici aussi.
            tous.sort(key=_cle_message)
            for k, mid in enumerate(tous):
                c, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}",
                              json={"embeds": [lesp[k] if k < len(lesp) else vide]})
                if c != 200:
                    # une page sautée, une autre en double : pas un succès
                    neufs.clear()
                    return _arret(f"page {k + 1} non remise en ordre (HTTP {c})", tous)
        else:
            for mid in ids[len(lesp):]:
                c, rep = _api("PATCH", f"/channels/{salon}/messages/{mid}", json={"embeds": [vide]})
                if c == 404:
                    tous.remove(mid)       # supprimée à la main : oubliée
                elif c != 200:
                    neufs.clear()
                    return _arret(f"page en trop non vidée (HTTP {c})", tous)
        e.update(salon=salon, messages=tous, vu=time.time())
        etat[gid] = e
        safe_json.write(_fichier_etat(), etat)
        bilan["messages"] = tous
        return bilan
    finally:
        _VERROU.release()
