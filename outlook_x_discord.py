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

L'adresse, le mot de passe et le code partent chacun SEUL dans son message :
sur téléphone, l'appui long copie le message entier (mémoire « copie sur
téléphone », cogs/user._envoyer_a_copier). Un bouton gris désactivé nomme
chacun sans être copié. Un nouveau clic efface les trois messages d'avant :
un seul jeu à l'écran, comme les numéros.

La clé 2FA (« seed ») ne sort jamais du serveur : elle ne sert qu'à calculer
le code du moment (outlook_comptes.texte_2fa / totp).

Propriétaire, 18/10/2026 : « juste pour le mail et mot de passe tu peux leur
envoyer dans leur salon aussi, juste otp qui reste dans adresse outlook ».
Une adresse NEUVE part donc aussi dans le salon perso du VA
(tickets_discord.ticket_de), l'adresse puis le mot de passe, chacun seul : les
éphémères disparaissent, le salon garde. Le code du moment, jamais là-bas.

« 🔐 Code 2FA » montre TOUT d'un coup (choix du propriétaire sur maquette,
18/10/2026, « déjà déroulé ») : chaque adresse du VA avec son code du moment
et un 🔄, dans un seul message — sans clic de plus pour choisir l'adresse.
"""
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    },
}
#: Autres adresses du VA proposées sous le code (une rangée de boutons).
AUTRES_MAX = 4
#: Adresses montrées par « Code 2FA » (les plus récentes) : un message V2
#: porte 40 composants au plus, et chaque adresse en prend trois.
LISTE_MAX = 10
#: Les suivis partent APRÈS la réponse au clic : Discord refuse un suivi
#: d'une interaction à laquelle il n'a pas encore reçu de réponse.
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


def _noter_suivi(cle: str, jeton: str, mid: str) -> None:
    with _VERROU:
        d = _lire()
        m = d["messages"].get(cle)
        if isinstance(m, dict) and m.get("jeton") == jeton:
            m.setdefault("suivis", []).append(mid)
            _ecrire(d)


def _effacer_jeu(m: Dict[str, Any]) -> None:
    if not m or not m.get("jeton") or time.time() - float(m.get("le") or 0) > nx.JETON_SEC:
        return                                    # jeton mort : Discord refuserait
    base = f"/webhooks/{m.get('app') or ''}/{m['jeton']}/messages/"
    for mid in ["@original"] + [str(x) for x in (m.get("suivis") or [])]:
        code, corps = vd.api("DELETE", base + mid)
        if code not in (204, 404):                # 404 : déjà fermé par la personne
            _log(f"ancien message non effacé : HTTP {code} {str(corps)[:120]}")


# ─── Dessin ───────────────────────────────────────────────────────────────
def _nom(cid: str, label: str) -> Dict[str, Any]:
    """Le bouton gris qui nomme un texte : désactivé, il n'est pas copié."""
    return {"type": 2, "style": 2, "label": label, "custom_id": cid, "disabled": True}


def _msg(texte: str, rangees: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"content": texte, "components": rangees, "allowed_mentions": {"parse": []},
            "flags": nx.EPHEMERE | 4}             # 4 : aucun aperçu de lien


def _bouton(action: str, label: str, emoji: str, style: int, arg: str = "") -> Dict[str, Any]:
    return {"type": 2, "style": style, "label": label, "emoji": {"name": emoji},
            "custom_id": PREFIXE + action + (":" + arg if arg else "")}


def _rangee(*boutons) -> Dict[str, Any]:
    return {"type": 1, "components": list(boutons)}


def msg_code(c: Dict[str, Any], uid: str, gid: str, maintenant=None) -> Dict[str, Any]:
    _texte, code, reste = oc.texte_2fa(c, maintenant)
    rangees = [_rangee(_nom(PREFIXE + "n:3", "🔐 Code 2FA · encore %d s" % reste),
                       _bouton("code", "Nouveau code", "🔄", 1, str(c.get("id"))))]
    autres = [a for a in oc.comptes_du_va(uid, gid) if str(a.get("id")) != str(c.get("id"))]
    if autres:
        rangees.append(_rangee(*[
            {"type": 2, "style": 2, "label": str(a.get("email") or "?")[:80],
             "custom_id": PREFIXE + "voir:" + str(a.get("id"))} for a in autres[:AUTRES_MAX]]))
    return _msg(code, rangees)


def jeu(c: Dict[str, Any], uid: str, gid: str) -> List[Dict[str, Any]]:
    """Les trois messages d'une adresse : adresse, mot de passe, code. Jamais la clé."""
    return [_msg(str(c.get("email") or ""), [_rangee(_nom(PREFIXE + "n:1", "📧 Adresse"))]),
            _msg(str(c.get("password") or ""), [_rangee(_nom(PREFIXE + "n:2", "🔑 Mot de passe"))]),
            msg_code(c, uid, gid)]


def _sans_md(t: str) -> str:
    """Une adresse avec « _ » passait en italique et perdait ses tirets bas."""
    return "".join("\\" + ch if ch in "_*~`|" else ch for ch in str(t))


def vue_mes_adresses(uid: str, gid: str, maintenant=None) -> List[Dict[str, Any]]:
    """Toutes les adresses du VA, chacune avec son code du moment et un 🔄."""
    blocs = []
    for c in oc.comptes_du_va(uid, gid)[:LISTE_MAX]:
        _t, code, reste = oc.texte_2fa(c, maintenant)
        blocs.append({"type": 9,
                      "components": [{"type": 10, "content": "%s\n🔐 **%s** · %d s"
                                      % (_sans_md(c.get("email") or "?"), code, reste)}],
                      "accessory": {"type": 2, "style": 2, "emoji": {"name": "🔄"},
                                    "custom_id": PREFIXE + "maj:" + str(c.get("id"))}})
    return [{"type": 17, "accent_color": nx.BLEU, "components": blocs}]


def vue_panneau() -> List[Dict[str, Any]]:
    return nx._vue(["## Adresses Outlook"], [_bouton("prendre", "Prendre une adresse", "📧", 3),
                                             _bouton("2fa", "Code 2FA", "🔐", 2)])


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
    morceaux = cid[len(PREFIXE):].split(":")
    action, arg = morceaux[0], (morceaux[1] if len(morceaux) > 1 else "")
    if action == "prendre":
        return _prendre(p, gid, uid, membre, user, conf)
    if action == "2fa":
        if not oc.comptes_du_va(uid, gid):
            return nx._texte("Tu n'as pas encore d'adresse : clique « 📧 Prendre une adresse ».")
        return _liste(p, gid, uid)
    if action == "maj":
        # Les codes changent tous ensemble (toutes les 30 s) : n'importe quel 🔄
        # redessine la liste entière, sur place.
        return {"type": 7, "data": {"components": vue_mes_adresses(uid, gid)}}
    if action in ("code", "voir"):
        c = oc.compte_par_id(arg)
        if not c or c.get("statut") != "attribue" or str(c.get("uid")) != uid \
                or str(c.get("serveur") or "") != gid:
            # Le bouton d'une adresse qui n'est pas (ou plus) la sienne.
            return nx._texte("Cette adresse n'est pas à toi.")
        if action == "code":
            m = msg_code(c, uid, gid)
            return {"type": 7, "data": {"content": m["content"], "components": m["components"]}}
        return _envoyer(p, gid, uid, c)
    return nx._texte("Action inconnue.")


def _prendre(p, gid, uid, membre, user, conf):
    if not oc.nb_libres():
        _log(f"plus aucune adresse libre (demande de {uid})")
        return nx._texte("❌ Plus d'adresse disponible pour le moment. Préviens un admin.")
    if not nx._staff(membre, gid):
        try:
            n = oc.nb_du_jour(uid, gid)
        except Exception as e:
            _log(f"quota illisible pour {uid} ({type(e).__name__}: {e}) : rien n'est donné")
            return nx._texte("❌ Le coffre ne se lit plus : rien n'a été donné. Préviens un admin.")
        if n >= conf["quota"]:
            _log(f"quota atteint pour {uid} ({n}/{conf['quota']})")
            return nx._texte("📵 %d adresses aujourd'hui : c'est le maximum. Reviens demain."
                             % conf["quota"])
    try:
        c, etat = oc.attribuer_une_de_plus(uid, str(user.get("global_name") or user.get("username") or ""), gid)
    except Exception as e:
        _log(f"attribution impossible pour {uid} ({type(e).__name__}: {e})")
        return nx._texte("❌ Le coffre ne s'écrit plus : rien n'a été donné. Préviens un admin.")
    if not c:
        return nx._texte("❌ Plus d'adresse disponible pour le moment. Préviens un admin.")
    _log(f"adresse n°{c.get('id')} donnée à {uid} ({c.get('va')})")
    rep = _envoyer(p, gid, uid, c)
    try:
        _fond(lambda: deposer_au_salon(gid, uid, c))
    except Exception as e:
        _log(f"dépôt au salon perso non lancé pour {uid} ({type(e).__name__}: {e})")
    return rep


def deposer_au_salon(gid: str, uid: str, c: Dict[str, Any]) -> bool:
    """L'adresse et le mot de passe dans le salon perso du VA — jamais le code
    ni la clé 2FA. Sans salon perso, le journal le dit : le VA a quand même
    tout reçu en éphémère."""
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
    for texte, nom in ((str(c.get("email") or ""), "📧 Adresse Outlook"),
                       (str(c.get("password") or ""), "🔑 Mot de passe")):
        m = _msg(texte, [_rangee(_nom(PREFIXE + "n:" + ("s1" if "Adresse" in nom else "s2"), nom))])
        m["flags"] = 4                            # dans le salon : pas éphémère, sans aperçu
        code, corps = vd.api("POST", f"/channels/{salon}/messages", json=m)
        if code != 200:
            ok = False
            _log(f"dépôt au salon {salon} refusé : HTTP {code} {str(corps)[:120]}")
    if ok:
        _log(f"adresse n°{c.get('id')} déposée dans le salon perso de {uid}")
    return ok


def _envoyer(p, gid, uid, c):
    """Le jeu de l'adresse : le 1er message en réponse au clic, les deux autres
    en suivis ; le jeu précédent de la personne est effacé."""
    cle = f"{gid}:{uid}"
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p, gid)
    messages = jeu(c, uid, gid)
    avant = _retenir(cle, jeton, app)

    def suite():
        _dormir(ATTENTE_SUIVI_SEC)
        if avant and avant.get("jeton") != jeton:
            _effacer_jeu(avant)
        for m in messages[1:]:
            code, corps = vd.api("POST", f"/webhooks/{app}/{jeton}?wait=true", json=m)
            if code == 404:                       # la réponse n'était pas encore enregistrée
                _dormir(2)
                code, corps = vd.api("POST", f"/webhooks/{app}/{jeton}?wait=true", json=m)
            if code == 200 and isinstance(corps, dict) and corps.get("id"):
                _noter_suivi(cle, jeton, str(corps["id"]))
            else:
                _log(f"suivi non envoyé à {uid} : HTTP {code} {str(corps)[:120]}")
    try:
        _fond(suite)
    except Exception as e:
        _log(f"suivis non lancés pour {uid} ({type(e).__name__}: {e})")
    return {"type": 4, "data": messages[0]}


def _liste(p, gid, uid):
    """La liste « déjà déroulée » : un seul message, qui remplace le jeu d'avant."""
    cle = f"{gid}:{uid}"
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p, gid)
    avant = _retenir(cle, jeton, app)
    if avant and avant.get("jeton") != jeton:
        def effacer():
            _dormir(ATTENTE_SUIVI_SEC)
            _effacer_jeu(avant)
        try:
            _fond(effacer)
        except Exception as e:
            _log(f"effacement de l'ancien jeu non lancé pour {uid} ({type(e).__name__}: {e})")
    return {"type": 4, "data": {"flags": nx.V2 | nx.EPHEMERE, "components": vue_mes_adresses(uid, gid),
                                "allowed_mentions": {"parse": []}}}


# ─── Pose du panneau ──────────────────────────────────────────────────────
def poser_panneau(gid: str = vd.TWITTER_ID) -> str:
    conf = SERVEURS[gid]
    salon = conf["salon"]
    with vd.sur_serveur(gid):
        moi = vd.bot_du_serveur(gid)["app_id"]
        code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
        if code != 200 or not isinstance(ms, list):
            return f"salon illisible : HTTP {code} {str(ms)[:160]}"
        miens = [m for m in ms if str((m.get("author") or {}).get("id")) == str(moi)
                 and PREFIXE + "prendre" in nx._ids(m.get("components"))]
        comps = vue_panneau()
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
    else:
        print("usage : python outlook_x_discord.py poser")
