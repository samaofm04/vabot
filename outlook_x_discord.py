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
    if action == "prendre":
        return _prendre(p, gid, uid, membre, user, conf)
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
        return nx._texte(TEXTE_COFFRE_VIDE)
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
        # La dernière adresse libre partie entre-temps (deux clics à la fois).
        try:
            _fond(lambda: coffre_vide(uid))
        except Exception as e:
            _log(f"coffre vide : alerte non lancée ({type(e).__name__}: {e})")
        return nx._texte(TEXTE_COFFRE_VIDE)
    _log(f"adresse n°{c.get('id')} donnée à {uid} ({c.get('va')})")
    rep = _repondre(p, gid, uid, vue_mes_adresses(uid, gid))
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
