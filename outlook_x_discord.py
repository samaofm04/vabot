"""Adresses Outlook sur YouLab TWITTER : les mails du propriétaire, pour les VA.

Propriétaire, 18/10/2026 : « je veux mettre un truc qui leur donne aussi des
mail stp, des mail que j'ai deja. note juste ils ont pas le droit de voir le
code a2F ». Ses réponses : le salon 📧・adresse-outlook, les mails collés sur
youl4b.com/outlook (le coffre de Va IG, outlook_comptes), un bouton « Code
2FA » qui donne le code à 6 chiffres du moment — jamais la clé secrète —, et
3 adresses par jour au plus pour un VA (le staff n'est pas bridé).

Comme le panneau « Numéro X » (numeros_x_discord) : Luigi sans gateway, le
panneau posé par REST (`python outlook_x_discord.py poser`), chaque clic sur
/discord/interactions, et tout ce qui suit est éphémère.

Le panneau est un formulaire DÉJÀ DÉROULÉ (propriétaire, 18/10/2026, sur
maquette puis : « en bas mail, en bas mot de passe et après code 2FA », « je
veux pas qu'il y ait des infos, juste des blancs avant la commande du mail ») :
sous le titre, les cases mail, mot de passe et code 2FA, vides. Au clic, le
VA reçoit le même formulaire rempli, pour lui seul : chacune de ses adresses
(la plus récente d'abord) avec son mail, son mot de passe et le code du
moment, un 🔄 pour le renouveler. Un nouveau clic sur le panneau efface le
formulaire d'avant : un seul à l'écran, comme les numéros.

La clé 2FA (« seed ») ne sort jamais du serveur : elle ne sert qu'à calculer
le code du moment (outlook_comptes.texte_2fa / totp).

« juste pour le mail et mot de passe tu peux leur envoyer dans leur salon
aussi, juste otp qui reste dans adresse outlook » : une adresse NEUVE part
aussi dans le salon perso du VA (tickets_discord.ticket_de), l'adresse puis
le mot de passe, chacun SEUL dans son message — sur téléphone, l'appui long
copie le message entier (mémoire « copie sur téléphone »). Le salon garde ce
que l'éphémère perd. Le code du moment, jamais là-bas.
"""
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numgen
import outlook_comptes as oc
import safe_json
import verif_discord as vd
import numeros_x_discord as nx

PREFIXE = "mailx:"
FICHIER = Path(__file__).resolve().parent / "data" / "outlook_x.json"

SERVEURS: Dict[str, Dict[str, Any]] = {
    vd.TWITTER_ID: {
        "nom": "YouLab TWITTER",
        "salon": "1552392906340565114",          # 📚 RESSOURCES > 📧・adresse-outlook
        "quota": 3,                               # par jour et par VA ; le staff n'est pas bridé
        # Propriétaire, 23/10/2026 : « retire outlook » du salon, « garde outlook
        # pour twitter dans leur menu » — la carte du ticket et le bouton
        # « 📧 Outlook » du menu épinglé suffisent. Plus de panneau ici.
        "panneau": False,
    },
}
#: Adresses montrées (les plus récentes) : un message V2 porte 40 composants
#: au plus, imbriqués compris ; chaque adresse en prend six (mail, mot de
#: passe, section, son texte, son 🔄, séparateur), plus le cadre, le titre et
#: la rangée « Prendre » : 3 + 6 x 6 = 39.
LISTE_MAX = 6
#: L'ancien message s'efface APRÈS la réponse au clic.
ATTENTE_SUIVI_SEC = 1.0

_VERROU = threading.RLock()


def _log(texte: str) -> None:
    # Jamais l'adresse, le mot de passe ni le code : le journal du VPS se lit.
    print(f"[mailx] {texte}", flush=True)


def _fond(f):
    nx._fond(f)


def _dormir(s):
    time.sleep(s)


# ─── Les messages de chacun ───────────────────────────────────────────────
def _lire() -> Dict[str, Any]:
    d = safe_json.load(FICHIER, default={}) or {}
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("messages"), dict):
        d["messages"] = {}
    if not isinstance(d.get("cartes"), dict):
        d["cartes"] = {}
    return d


def _ecrire(d: Dict[str, Any]) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(FICHIER, d, indent=1):
        _log(f"écriture de {FICHIER.name} refusée")


def _retenir(cle: str, jeton: str, app: str) -> Optional[Dict[str, Any]]:
    """Ce clic ouvre LE jeu de messages de la personne ; rend le précédent."""
    with _VERROU:
        d = _lire()
        avant = d["messages"].get(cle)
        d["messages"][cle] = {"jeton": jeton, "app": app, "le": time.time(), "suivis": []}
        _ecrire(d)
    return avant if isinstance(avant, dict) else None


def _effacer_jeu(m: Dict[str, Any]) -> None:
    if not m or not m.get("jeton") or time.time() - float(m.get("le") or 0) > nx.JETON_SEC:
        return                                    # jeton mort : Discord refuserait
    base = f"/webhooks/{m.get('app') or ''}/{m['jeton']}/messages/"
    for mid in ["@original"] + [str(x) for x in (m.get("suivis") or [])]:
        code, corps = vd.api("DELETE", base + mid)
        if code not in (204, 404):                # 404 : déjà fermé par la personne
            _log(f"ancien message non effacé : HTTP {code} {str(corps)[:120]}")


# ─── Dessin ───────────────────────────────────────────────────────────────
#: Les cases vides du panneau : « je veux pas qu'il y ait des infos, juste des
#: blancs avant la commande du mail » (propriétaire, 18/10/2026). Un code fait
#: d'espaces insécables s'affiche comme une case grise vide.
BLANC = "`" + "\u00a0" * 24 + "`"
BLANC_CODE = "`" + "\u00a0" * 8 + "`"


def _nom(cid: str, label: str) -> Dict[str, Any]:
    """Le bouton gris qui nomme un texte : désactivé, il n'est pas copié."""
    return {"type": 2, "style": 2, "label": label, "custom_id": cid, "disabled": True}


def _bouton(action: str, label: str, emoji: str, style: int, arg: str = "") -> Dict[str, Any]:
    return {"type": 2, "style": style, "label": label, "emoji": {"name": emoji},
            "custom_id": PREFIXE + action + (":" + arg if arg else "")}


def _rangee(*boutons) -> Dict[str, Any]:
    return {"type": 1, "components": list(boutons)}


def _sans_md(t: str) -> str:
    """Une adresse avec « _ » passait en italique et perdait ses tirets bas."""
    return "".join("\\" + ch if ch in "_*~`|\\" else ch for ch in str(t))


def _litteral(t: str) -> str:
    """Tel quel à l'écran : un mot de passe avec « * » ou « _ » passait en
    gras ou en italique. En code, sauf s'il contient lui-même un accent grave."""
    t = str(t)
    return "`%s`" % t if "`" not in t else _sans_md(t)


def _prendre_bouton() -> Dict[str, Any]:
    return _bouton("prendre", "Prendre une adresse", "📧", 3)


def vue_panneau() -> List[Dict[str, Any]]:
    """Le panneau du salon : le formulaire déjà déroulé, ses cases vides."""
    return [{"type": 17, "accent_color": nx.BLEU, "components": [
        {"type": 10, "content": "## Adresses Outlook"},
        {"type": 10, "content": "📧 " + BLANC},
        {"type": 10, "content": "🔑 " + BLANC},
        {"type": 10, "content": "🔐 " + BLANC_CODE},
        _rangee(_prendre_bouton(), _bouton("2fa", "Code 2FA", "🔐", 2))]}]


def vue_mes_adresses(uid: str, gid: str, maintenant=None) -> List[Dict[str, Any]]:
    """Le même formulaire, rempli pour le VA : sous le titre, chaque adresse
    (la plus récente d'abord) avec son mail, son mot de passe, puis le code du
    moment et un 🔄. Jamais la clé 2FA. Sans adresse : les cases vides."""
    l = oc.comptes_du_va(uid, gid)[:LISTE_MAX]
    if not l:
        return vue_panneau()
    blocs: List[Dict[str, Any]] = [{"type": 10, "content": "## Adresses Outlook"}]
    for i, c in enumerate(l):
        _t, code, reste = oc.texte_2fa(c, maintenant)
        if i:
            blocs.append({"type": 14, "divider": True, "spacing": 1})
        blocs += [{"type": 10, "content": "📧 " + _litteral(c.get("email") or "?")},
                  {"type": 10, "content": "🔑 " + _litteral(c.get("password") or "?")},
                  {"type": 9,
                   "components": [{"type": 10, "content": "🔐 **%s** · %d s" % (code, reste)}],
                   "accessory": {"type": 2, "style": 2, "emoji": {"name": "🔄"},
                                 "custom_id": PREFIXE + "maj:" + str(c.get("id"))}}]
    blocs.append(_rangee(_prendre_bouton()))
    return [{"type": 17, "accent_color": nx.BLEU, "components": blocs}]


# ─── La carte du ticket ───────────────────────────────────────────────────
# Propriétaire, 23/10/2026 : « pour twitter mets ça aussi dans leur ticket comme
# sur threads » — comme la carte numéro (numeros_x_discord) : UNE carte par VA
# dans son salon perso, changée sur place, et un bouton « 📧 Outlook » dans le
# menu épinglé du ticket (tickets_discord). Les codes 2FA ne s'affichent qu'au
# clic, et repartent au bout de CODE_VISIBLE_SEC : un code laissé dans un
# message qui dure aurait été faux trente secondes plus tard.
CODE_VISIBLE_SEC = 60
TEXTE_RENVOI = "📧 Ton adresse est maintenant dans ton salon perso."


def vue_carte(uid: str, gid: str, codes: bool = False, souci: str = "",
              maintenant=None) -> List[Dict[str, Any]]:
    l = oc.comptes_du_va(uid, gid)[:LISTE_MAX]
    blocs: List[Dict[str, Any]] = [{"type": 10, "content": "## Adresses Outlook"}]
    if not l:
        blocs += [{"type": 10, "content": "📧 " + BLANC}, {"type": 10, "content": "🔑 " + BLANC},
                  {"type": 10, "content": "🔐 " + BLANC_CODE}]
    for i, c in enumerate(l):
        if i:
            blocs.append({"type": 14, "divider": True, "spacing": 1})
        if codes:
            _t, code, reste = oc.texte_2fa(c, maintenant)
            ligne = "🔐 **%s** · %d s" % (code, reste)
        else:
            ligne = "🔐 " + BLANC_CODE
        blocs += [{"type": 10, "content": "📧 " + _litteral(c.get("email") or "?")},
                  {"type": 10, "content": "🔑 " + _litteral(c.get("password") or "?")},
                  {"type": 9, "components": [{"type": 10, "content": ligne}],
                   "accessory": {"type": 2, "style": 2, "emoji": {"name": "🔄"},
                                 "custom_id": PREFIXE + "maj:" + str(c.get("id"))}}]
    if souci:
        blocs.append({"type": 10, "content": souci})
    boutons = [_prendre_bouton()] + ([_bouton("2fa", "Code 2FA", "🔐", 2)] if l else [])
    blocs.append(_rangee(*boutons))
    return [{"type": 17, "accent_color": nx.BLEU, "components": blocs}]


def vue_menu() -> List[Dict[str, Any]]:
    """📧・adresse-outlook une fois les cartes en place : la ligne de renvoi et
    le bouton qui ramène la carte du VA en bas de SON salon perso."""
    return [{"type": 17, "accent_color": nx.BLEU, "components": [
        {"type": 10, "content": TEXTE_RENVOI},
        _rangee(_bouton("menu", "Afficher le menu", "📋", 1))]}]


def _cartes_auto(gid: str) -> bool:
    return bool((_lire().get("cartes_auto") or {}).get(str(gid)))


def _carte_du_clic(p: Dict[str, Any]) -> Optional[Dict[str, str]]:
    salon = str(p.get("channel_id") or "")
    mid = str((p.get("message") or {}).get("id") or "")
    c = _lire()["cartes"].get(salon)
    if isinstance(c, dict) and mid and str(c.get("message")) == mid and c.get("uid"):
        return {"salon": salon, "message": mid, "uid": str(c["uid"])}
    return None


def _cacher_codes_plus_tard(gid: str, uid: str, salon: str, le: float) -> None:
    """Les codes affichés repartent au bout de CODE_VISIBLE_SEC, sauf si un
    clic plus récent les a réaffichés entre-temps."""
    def cacher():
        _dormir(CODE_VISIBLE_SEC)
        c = _lire()["cartes"].get(salon) or {}
        if float(c.get("codes_le") or 0) != le or not c.get("message"):
            return
        with vd.sur_serveur(gid):
            code, corps = vd.api("PATCH", f"/channels/{salon}/messages/{c['message']}",
                                 json={"components": vue_carte(uid, gid),
                                       "allowed_mentions": {"parse": []}})
        if code != 200:
            _log(f"codes non cachés dans {salon} : HTTP {code} {str(corps)[:120]}")
    try:
        _fond(cacher)
    except Exception as e:
        _log(f"codes : effacement différé non lancé ({type(e).__name__}: {e})")


def _sur_la_carte(p: Dict[str, Any], gid: str, uid: str, codes: bool = False,
                  souci: str = "") -> Dict[str, Any]:
    """La carte du ticket, changée sur place (type 7). Codes affichés : ils
    repartent d'eux-mêmes un peu plus tard."""
    carte = p["_carte"]
    if codes:
        le = time.time()
        with _VERROU:
            d = _lire()
            if isinstance(d["cartes"].get(carte["salon"]), dict):
                d["cartes"][carte["salon"]]["codes_le"] = le
                _ecrire(d)
        _cacher_codes_plus_tard(gid, uid, carte["salon"], le)
    return {"type": 7, "data": {"components": vue_carte(uid, gid, codes=codes, souci=souci)}}


def _refus(p: Dict[str, Any], gid: str, uid: str, texte: str) -> Dict[str, Any]:
    """Un refus : dans la carte du ticket s'il vient d'elle, sinon en privé."""
    if p.get("_carte"):
        return _sur_la_carte(p, gid, uid, souci=texte)
    return nx._texte(texte)


def _tickets(gid: str) -> Dict[str, str]:
    return nx._tickets_du_serveur(gid)


def _carte_dans(salon: str, moi: str) -> str:
    """La carte de ce bot déjà dans le salon (registre perdu), ou « ». Les
    dépôts adresse / mot de passe (boutons « mailx:n: ») n'en sont pas."""
    code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
    if code != 200 or not isinstance(ms, list):
        return ""
    for m in ms:
        if str((m.get("author") or {}).get("id")) == str(moi) and \
                PREFIXE + "prendre" in nx._ids(m.get("components")):
            return str(m["id"])
    return ""


def poser_cartes(gid: str, seulement: Optional[str] = None,
                 maintenant: Optional[float] = None) -> Dict[str, Any]:
    """Une carte Outlook dans chaque ticket du serveur qui n'en a pas."""
    now = float(time.time() if maintenant is None else maintenant)
    bilan: Dict[str, Any] = {"posees": [], "retrouvees": [], "deja": 0, "echecs": [], "partis": []}
    with vd.sur_serveur(gid):
        moi = vd.bot_du_serveur(gid)["app_id"]
        for salon, uid in sorted(_tickets(gid).items()):
            if seulement and salon != str(seulement):
                continue
            c = _lire()["cartes"].get(salon)
            if isinstance(c, dict) and c.get("uid") == uid:
                if now - float(c.get("vu_le") or 0) < nx.CARTE_REVOIR_SEC:
                    bilan["deja"] += 1
                    continue
                code, _m = vd.api("GET", f"/channels/{salon}/messages/{c.get('message')}")
                if code == 200:
                    with _VERROU:
                        d = _lire()
                        d["cartes"][salon] = dict(c, vu_le=now)
                        _ecrire(d)
                    bilan["deja"] += 1
                    continue
                if code != 404:
                    bilan["echecs"].append((salon, f"relecture HTTP {code}"))
                    continue
            code, _m = vd.api("GET", f"/guilds/{gid}/members/{uid}")
            if code == 404:
                bilan["partis"].append(salon)
                continue
            mid = _carte_dans(salon, moi)
            if mid:
                bilan["retrouvees"].append(salon)
            else:
                code, rep = vd.api("POST", f"/channels/{salon}/messages",
                                   json={"flags": nx.V2, "components": vue_carte(uid, gid),
                                         "allowed_mentions": {"parse": []}})
                if code != 200 or not isinstance(rep, dict) or not rep.get("id"):
                    bilan["echecs"].append((salon, f"HTTP {code} {str(rep)[:120]}"))
                    continue
                mid = str(rep["id"])
                bilan["posees"].append(salon)
            with _VERROU:
                d = _lire()
                d["cartes"][salon] = {"message": mid, "uid": uid, "gid": gid, "vu_le": now}
                _ecrire(d)
    for quoi in ("posees", "retrouvees"):
        if bilan[quoi]:
            _log(f"cartes Outlook : {quoi} dans {', '.join(bilan[quoi])}")
    for salon, pourquoi in bilan["echecs"]:
        _log(f"carte Outlook du salon {salon} non posée : {pourquoi}")
    return bilan


def ramener_carte(gid: str, uid: str, salon: str) -> str:
    """La carte Outlook du VA revient en dernier dans son salon perso (le bot
    ne retire que SA carte). « deja », « ramenee » ou « echec »."""
    with vd.sur_serveur(gid):
        ancien = str((_lire()["cartes"].get(salon) or {}).get("message") or "")
        code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=1")
        if ancien and code == 200 and isinstance(ms, list) and ms and str(ms[0].get("id")) == ancien:
            return "deja"
        code, rep = vd.api("POST", f"/channels/{salon}/messages",
                           json={"flags": nx.V2, "components": vue_carte(uid, gid),
                                 "allowed_mentions": {"parse": []}})
        if code != 200 or not isinstance(rep, dict) or not rep.get("id"):
            _log(f"menu : carte Outlook non reposée dans {salon} : HTTP {code} {str(rep)[:120]}")
            return "echec"
        mid = str(rep["id"])
        with _VERROU:
            d = _lire()
            d["cartes"][salon] = {"message": mid, "uid": uid, "gid": gid, "vu_le": time.time()}
            _ecrire(d)
        if ancien and ancien != mid:
            code, _r = vd.api("DELETE", f"/channels/{salon}/messages/{ancien}")
            if code not in (204, 404):
                _log(f"menu : ancienne carte Outlook {ancien} non retirée de {salon} : HTTP {code}")
    _log(f"menu : carte Outlook de {uid} ramenée en bas de {salon}")
    return "ramenee"


def _menu(p: Dict[str, Any], gid: str, uid: str) -> Dict[str, Any]:
    """« 📋 Afficher le menu » (📧・adresse-outlook) ou « 📧 Outlook » (menu
    épinglé du ticket) : la carte descend en bas du salon perso."""
    tickets = _tickets(gid)
    ici = str(p.get("channel_id") or "")
    if ici in tickets:
        vau = tickets[ici]
        try:
            _fond(lambda: ramener_carte(gid, vau, ici))
        except Exception as e:
            _log(f"menu : déplacement non lancé dans {ici} ({type(e).__name__}: {e})")
            return nx._texte("❌ Impossible pour le moment : réessaie dans un instant.")
        return {"type": 6}
    salon = next((s for s, u in tickets.items() if u == uid), "")
    if not salon:
        # Sans salon perso (le staff, un VA pas encore servi) : ses adresses
        # s'ouvrent en privé, comme la carte numéro. Depuis le menu privé
        # (tickets_discord.menu_prive, message classique) : à part, pas sur place.
        source = int(((p.get("message") or {}).get("flags")) or 0)
        if source & nx.EPHEMERE and not source & nx.V2:
            p = dict(p, message={"flags": 0})
        return _repondre(p, gid, uid, vue_mes_adresses(uid, gid))
    try:
        _fond(lambda: ramener_carte(gid, uid, salon))
    except Exception as e:
        _log(f"menu : déplacement non lancé pour {uid} ({type(e).__name__}: {e})")
        return nx._texte("❌ Impossible pour le moment : réessaie dans un instant.")
    nx._effacer_apres(p, dormir=_dormir)           # le renvoi s'efface seul
    return nx._texte(f"📋 Ton menu est en bas de <#{salon}>.")


def generaliser_cartes(gid: str) -> str:
    with _VERROU:
        d = _lire()
        d.setdefault("cartes_auto", {})[str(gid)] = True
        _ecrire(d)
    b = poser_cartes(gid)
    return (f"cartes Outlook : {len(b['posees'])} posée(s), {len(b['retrouvees'])} retrouvée(s), "
            f"{b['deja']} déjà là, {len(b['partis'])} VA parti(s), {len(b['echecs'])} échec(s) ; "
            + poser_panneau(gid))


def tour_cartes() -> None:
    """Appelé par la boucle des cartes numéro (numeros_x_discord) toutes les
    10 minutes : les nouveaux tickets reçoivent aussi leur carte Outlook."""
    for gid in SERVEURS:
        if _cartes_auto(gid):
            try:
                poser_cartes(gid)
            except Exception as e:
                _log(f"cartes Outlook de {gid} : tour en échec ({type(e).__name__}: {e})")


# ─── Clics ────────────────────────────────────────────────────────────────
def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La réponse à un clic « mailx: », ou None si ce n'est pas le nôtre."""
    p = p or {}
    if p.get("type") != 3:
        return None
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if not cid.startswith(PREFIXE):
        return None
    gid = str(p.get("guild_id") or "")
    conf = SERVEURS.get(gid)
    if not conf:
        return nx._texte("Ce bouton ne sert que sur YouLab TWITTER.")
    membre = p.get("member") or {}
    user = membre.get("user") or {}
    uid = str(user.get("id") or "")
    if not uid.isdigit():
        return nx._texte("Compte introuvable.")
    action = cid[len(PREFIXE):].split(":")[0]
    if action == "menu":
        return _menu(p, gid, uid)
    carte = _carte_du_clic(p)
    if carte:
        # La carte d'un ticket : les adresses et le quota sont ceux du VA du
        # ticket, même quand son manager clique pour lui (staff : non bridé).
        p = dict(p, _carte=carte)
        if carte["uid"] != uid:
            uid, user = carte["uid"], {}
    if action == "prendre":
        return _prendre(p, gid, uid, membre, user, conf)
    if action in ("2fa", "maj") and carte:
        return _sur_la_carte(p, gid, uid, codes=True)
    if action == "2fa":
        return _repondre(p, gid, uid, vue_mes_adresses(uid, gid))
    if action == "maj":
        # Les codes changent tous ensemble (toutes les 30 s) : n'importe quel 🔄
        # redessine le formulaire entier, sur place.
        return {"type": 7, "data": {"components": vue_mes_adresses(uid, gid)}}
    return nx._texte("Action inconnue.")


def _repondre(p, gid, uid, comps):
    """Sur le message privé lui-même : changé sur place. Sur le panneau du
    salon : un NOUVEAU message privé, qui efface le précédent — un seul
    formulaire à l'écran, comme les numéros."""
    cle = f"{gid}:{uid}"
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p, gid)
    avant = _retenir(cle, jeton, app)
    if int(((p.get("message") or {}).get("flags")) or 0) & nx.EPHEMERE:
        return {"type": 7, "data": {"components": comps}}
    if avant and avant.get("jeton") != jeton:
        def effacer():
            _dormir(ATTENTE_SUIVI_SEC)
            _effacer_jeu(avant)
        try:
            _fond(effacer)
        except Exception as e:
            _log(f"effacement de l'ancien message non lancé pour {uid} ({type(e).__name__}: {e})")
    return {"type": 4, "data": {"flags": nx.V2 | nx.EPHEMERE, "components": comps,
                                "allowed_mentions": {"parse": []}}}


#: Ce que le VA lit quand le coffre est vide (le même texte sur Va IG).
TEXTE_COFFRE_VIDE = oc.TEXTE_COFFRE_VIDE + " Reviens plus tard."


def coffre_vide(qui: str, refus: bool = True) -> None:
    """Dit au journal POURQUOI le coffre ne donne rien, et prévient le staff
    UNE fois (numgen.alerter_staff, le debrief-day du Spam) — partagé avec
    Va IG (cogs/outlook.py) : c'est le même coffre. Le remplir reste au
    propriétaire (youl4b.com/outlook). Jamais d'adresse ni de secret ici.
    `refus` faux : la dernière adresse vient de partir, personne n'est encore
    refusé — le staff le sait AVANT le premier VA éconduit."""
    try:
        n = len(oc.comptes())
    except Exception as e:
        n = -1
        _log(f"coffre illisible ({type(e).__name__}: {e})")
    pourquoi = ("aucune adresse enregistrée" if n == 0 else
                "coffre illisible" if n < 0 else f"{n} adresse(s), toutes déjà données")
    _log(f"coffre vide ({pourquoi}) : " + (f"demande de {qui} refusée" if refus
                                            else f"dernière adresse donnée à {qui}"))
    etat = numgen.alerter_staff(
        "outlook:vide", "⚠️ **Coffre Outlook vide** (%s) : les VA de Twitter et de Va IG ne "
                        "reçoivent plus d'adresse. À remplir sur youl4b.com/outlook." % pourquoi)
    if etat not in ("envoye", "deja", "hors production"):
        _log(f"alerte « coffre vide » non envoyée au staff : {etat}")


def suivre_coffre(qui: str) -> None:
    """Après une adresse donnée (Twitter ou Va IG) : la dernière partie, le
    staff est prévenu tout de suite ; sinon une alerte en cours est levée (le
    coffre a été rempli), la prochaine panne sera redite."""
    if oc.nb_libres():
        numgen.fin_alerte("outlook:vide")
    else:
        coffre_vide(qui, refus=False)


def _prendre(p, gid, uid, membre, user, conf):
    if not oc.nb_libres():
        try:
            _fond(lambda: coffre_vide(uid))
        except Exception as e:
            _log(f"coffre vide : alerte non lancée ({type(e).__name__}: {e})")
        return _refus(p, gid, uid, TEXTE_COFFRE_VIDE)
    if not nx._staff(membre, gid):
        try:
            n = oc.nb_du_jour(uid, gid)
        except Exception as e:
            _log(f"quota illisible pour {uid} ({type(e).__name__}: {e}) : rien n'est donné")
            return _refus(p, gid, uid, "❌ Le coffre ne se lit plus : rien n'a été donné. "
                                       "Préviens un admin.")
        if n >= conf["quota"]:
            _log(f"quota atteint pour {uid} ({n}/{conf['quota']})")
            return _refus(p, gid, uid, "📵 %d adresses aujourd'hui : c'est le maximum. "
                                       "Reviens demain." % conf["quota"])
    try:
        c, etat = oc.attribuer_une_de_plus(uid, str(user.get("global_name") or user.get("username") or ""), gid)
    except Exception as e:
        _log(f"attribution impossible pour {uid} ({type(e).__name__}: {e})")
        return _refus(p, gid, uid, "❌ Le coffre ne s'écrit plus : rien n'a été donné. "
                                   "Préviens un admin.")
    if not c:
        # La dernière adresse libre partie entre-temps (deux clics à la fois).
        try:
            _fond(lambda: coffre_vide(uid))
        except Exception as e:
            _log(f"coffre vide : alerte non lancée ({type(e).__name__}: {e})")
        return _refus(p, gid, uid, TEXTE_COFFRE_VIDE)
    _log(f"adresse n°{c.get('id')} donnée à {uid} ({c.get('va')})")
    rep = (_sur_la_carte(p, gid, uid, codes=True) if p.get("_carte")
           else _repondre(p, gid, uid, vue_mes_adresses(uid, gid)))
    try:
        _fond(lambda: suivre_coffre(uid))
    except Exception as e:
        _log(f"suivi du coffre non lancé ({type(e).__name__}: {e})")
    try:
        _fond(lambda: deposer_au_salon(gid, uid, c))
    except Exception as e:
        _log(f"dépôt au salon perso non lancé pour {uid} ({type(e).__name__}: {e})")
    return rep


def deposer_au_salon(gid: str, uid: str, c: Dict[str, Any]) -> bool:
    """L'adresse et le mot de passe dans le salon perso du VA, chacun SEUL
    pour la copie sur téléphone — jamais le code ni la clé 2FA. Sans salon
    perso, le journal le dit : le VA a quand même son formulaire privé."""
    try:
        import tickets_discord
        salon = tickets_discord.ticket_de(gid, uid)
    except Exception as e:
        _log(f"salon perso de {uid} illisible ({type(e).__name__}: {e}) : adresse n°{c.get('id')} non déposée")
        return False
    if not salon:
        _log(f"{uid} n'a pas de salon perso : adresse n°{c.get('id')} non déposée")
        return False
    ok = True
    for texte, nom, n in ((str(c.get("email") or ""), "📧 Adresse Outlook", "s1"),
                          (str(c.get("password") or ""), "🔑 Mot de passe", "s2")):
        m = {"content": texte, "components": [_rangee(_nom(PREFIXE + "n:" + n, nom))],
             "allowed_mentions": {"parse": []}, "flags": 4}   # 4 : aucun aperçu de lien
        code, corps = vd.api("POST", f"/channels/{salon}/messages", json=m)
        if code != 200:
            ok = False
            _log(f"dépôt au salon {salon} refusé : HTTP {code} {str(corps)[:120]}")
    if ok:
        _log(f"adresse n°{c.get('id')} déposée dans le salon perso de {uid}")
    return ok


# ─── Pose du panneau ──────────────────────────────────────────────────────
def poser_panneau(gid: str = vd.TWITTER_ID) -> str:
    conf = SERVEURS[gid]
    if conf.get("panneau") is False:
        return "pas de panneau dans ce salon (retiré à la demande du propriétaire)"
    salon = conf["salon"]
    with vd.sur_serveur(gid):
        moi = vd.bot_du_serveur(gid)["app_id"]
        code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
        if code != 200 or not isinstance(ms, list):
            return f"salon illisible : HTTP {code} {str(ms)[:160]}"
        # Le panneau, ou le menu qui l'a remplacé : sinon un second message.
        miens = [m for m in ms if str((m.get("author") or {}).get("id")) == str(moi)
                 and ({PREFIXE + "prendre", PREFIXE + "menu"} & set(nx._ids(m.get("components"))))]
        comps = vue_menu() if _cartes_auto(gid) else vue_panneau()
        if miens:
            code, rep = vd.api("PATCH", f"/channels/{salon}/messages/{miens[0]['id']}",
                               json={"components": comps})
            return f"panneau remis à neuf : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")
        code, rep = vd.api("POST", f"/channels/{salon}/messages",
                           json={"flags": nx.V2, "components": comps, "allowed_mentions": {"parse": []}})
        return f"panneau posé : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["poser"]:
        vd._charger_config()
        print(poser_panneau())
    elif sys.argv[1:2] == ["cartes"] and len(sys.argv) == 3:
        # cartes <salon> : une seule carte (essai) ; cartes tous : toutes, les
        # nouveaux tickets ensuite, et le panneau du salon commun en menu.
        vd._charger_config()
        print(generaliser_cartes(vd.TWITTER_ID) if sys.argv[2] == "tous"
              else poser_cartes(vd.TWITTER_ID, seulement=sys.argv[2]))
    else:
        print("usage : python outlook_x_discord.py poser | cartes <salon>|tous")
