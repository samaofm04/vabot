"""« Numéro X » sur YouLab TWITTER : un numéro US loué chez HeroSMS, et son code.

Propriétaire, 17/10/2026 : « mes numéros et tout j'en ai plus, me créer un
bot qui puisse me générer des numéros […] sur Hero SMS, pour me donner des
numéros de compte X ». Ses réponses : chaque VA, numéros des États-Unis, 3 par
jour, un salon dédié (📱・numéro-usa) — et « chaque personne a son truc, les
autres voient pas ce qui se passe ».

Le serveur est servi par Luigi SANS gateway : le panneau est posé par REST
(`python numeros_x_discord.py poser`), et chaque clic arrive sur
/discord/interactions (web_upload). Tout ce qui suit le clic est ÉPHÉMÈRE : le
numéro et le code ne se voient que de celui qui a cliqué.

Même dessin que le panneau Numéro de Va IG (cogs/numeros.py, validé le
27/09/2026) :
  en attente  le numéro, collé (+15550142294), « ⏳ En attente du code… »
              🔄 Redemander un code · 🔁 Autre · ❌ Annuler
  code reçu   le même numéro, « 🔑 Code : 482913 »
              ✅ C'est bon · 🔄 Nouveau code · 🔁 Autre
Même historique (data/numgen_historique.json) et même compte du jour
(numeros_du_jour) que Va IG : le quota se lit au même endroit, pas dans une
seconde table qui finirait par dire autre chose.

L'état de chaque numéro vit dans data/numeros_x.json, pas dans le message :
un bouton cliqué après un redémarrage retrouve son numéro.

UN message par personne. Propriétaire, 17/10/2026, capture à l'appui : « quand
je prends un autre num je veux qu'il remplace l'autre, histoire d'avoir
toujours le même truc ». Chaque clic sur le panneau du salon ouvrait un
message éphémère de plus, avec le même numéro. Le nouveau message efface
désormais le précédent (son jeton d'interaction, gardé 15 min, le permet) ;
les boutons d'un message le changent sur place.
"""
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import numgen
import safe_json
import verif_discord as vd

PREFIXE = "numx:"
FICHIER = Path(__file__).resolve().parent / "data" / "numeros_x.json"

SERVEURS: Dict[str, Dict[str, Any]] = {
    vd.TWITTER_ID: {
        "nom": "YouLab TWITTER",
        "salon": "1552392915622436874",          # 📚 RESSOURCES > 📱・numéro-usa
        "service": "tw",                          # Twitter/X chez HeroSMS
        "pays": "187", "drapeau": "🇺🇸",           # États-Unis : 0,06 $ le 17/10/2026
        "quota": 3,                               # par jour et par VA ; le staff n'est pas bridé
    },
}

#: Durée de vie d'un numéro chez le fournisseur (comme cogs/numeros.py).
DUREE_NUMERO_SEC = 20 * 60
#: Un jeton d'interaction vit 15 min : au-delà, Discord refuse l'édition.
JETON_SEC = 14 * 60 + 30
POLL_SEC = 5
POLL_LENT_SEC = 15
POLL_RAPIDE_JUSQUA = 180
ERREURS_MAX = 5
V2 = 1 << 15
EPHEMERE = 64
BLEU = 0x1D9BF0

_VERROU = threading.RLock()
_ACHATS: set = set()            # « gid:uid » dont l'achat est en cours
_ECOUTES: Dict[str, str] = {}   # « gid:uid » -> id d'activation écoutée
_REPRIS = [False]


def _fond(f):
    """Travail après la réponse à Discord : il a 3 s pour l'avoir, un achat
    HeroSMS en prend parfois plus. Remplacé par un appel direct dans les tests."""
    vd._EN_FOND(f)


def _dormir(s):
    time.sleep(s)


def _log(texte: str) -> None:
    print(f"[numx] {texte}", flush=True)


# ─── État ─────────────────────────────────────────────────────────────────
def _lire() -> Dict[str, Any]:
    d = safe_json.load(FICHIER, default={}) or {}
    if not isinstance(d, dict):
        _log(f"{FICHIER.name} n'est pas un objet JSON : repart à vide")
        d = {}
    if not isinstance(d.get("actifs"), dict):
        d["actifs"] = {}
    if not isinstance(d.get("messages"), dict):
        d["messages"] = {}
    return d


def _ecrire(d: Dict[str, Any]) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(FICHIER, d, indent=1):
        _log(f"écriture de {FICHIER.name} refusée")


def _actif(cle: str) -> Optional[Dict[str, Any]]:
    a = _lire()["actifs"].get(cle)
    return a if isinstance(a, dict) else None


def _maj(cle: str, act_id: str, **champs) -> Optional[Dict[str, Any]]:
    """Complète l'activation `act_id` de `cle` ; None si ce n'est plus elle
    (« Autre » l'a remplacée entre-temps, rien ne doit écrire sur la suivante)."""
    with _VERROU:
        d = _lire()
        a = d["actifs"].get(cle)
        if not isinstance(a, dict) or str(a.get("id")) != str(act_id):
            return None
        a.update(champs)
        _ecrire(d)
        return a


def _message(cle: str) -> Optional[Dict[str, Any]]:
    """Le message éphémère que la personne a sous les yeux : {jeton, app, le}.
    Repli sur le jeton rangé dans l'activation (format du premier jour)."""
    d = _lire()
    m = d["messages"].get(cle)
    if isinstance(m, dict) and m.get("jeton"):
        return m
    a = d["actifs"].get(cle)
    if isinstance(a, dict) and a.get("jeton"):
        return {"jeton": a["jeton"], "app": a.get("app") or "", "le": a.get("jeton_le") or 0}
    return None


def _retenir(cle: str, jeton: str, app: str) -> Optional[Dict[str, Any]]:
    """Ce message devient LE message de la personne ; rend le précédent."""
    with _VERROU:
        avant = _message(cle)
        d = _lire()
        d["messages"][cle] = {"jeton": jeton, "app": app, "le": time.time()}
        _ecrire(d)
    return avant


def _effacer(m: Dict[str, Any]) -> None:
    code, corps = vd.api("DELETE", f"/webhooks/{m.get('app') or ''}/{m['jeton']}/messages/@original")
    # 404 : déjà fermé par la personne (« Rejeter le message ») ; rien à dire.
    if code not in (204, 404):
        _log(f"ancien message non effacé : HTTP {code} {str(corps)[:160]}")


def _vivant(a: Optional[Dict[str, Any]]) -> bool:
    return bool(a) and not a.get("clos") and \
        time.time() - float(a.get("pris_le") or 0) < DUREE_NUMERO_SEC


# ─── L'historique de Va IG (quota et récap) ───────────────────────────────
def _num():
    """cogs.numeros : déjà chargé par le bot dans ce processus."""
    from cogs import numeros
    return numeros


def numeros_du_jour(uid: str, gid: str) -> int:
    return _num().numeros_du_jour(uid, gid)


def _histo_prise(a: Dict[str, Any], gid: str, nom: str) -> None:
    try:
        salon = SimpleNamespace(id=a.get("salon"), guild=SimpleNamespace(id=gid))
        qui = SimpleNamespace(id=a.get("par"), display_name=nom)
        if not _num().histo_prise(dict(a, kind="sms"), channel=salon, user=qui):
            _log(f"prise de {a.get('valeur')} NON notée à l'historique (quota faussé)")
    except Exception as e:
        _log(f"historique : prise de {a.get('valeur')} NON notée ({type(e).__name__}: {e})")


def _histo(act_id: str, quoi: str) -> None:
    try:
        _num().histo_evenement("sms", act_id, quoi)
    except Exception as e:
        _log(f"historique : {quoi} de {act_id} NON noté ({type(e).__name__}: {e})")


# ─── Dessin (Components V2) ───────────────────────────────────────────────
def _bouton(action: str, label: str, emoji: str, style: int, act_id: str = "") -> Dict[str, Any]:
    return {"type": 2, "style": style, "label": label, "emoji": {"name": emoji},
            "custom_id": PREFIXE + action + (":" + act_id if act_id else "")}


def _vue(lignes: List[str], boutons: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    corps: List[Dict[str, Any]] = [{"type": 10, "content": t} for t in lignes if t]
    if boutons:
        corps.append({"type": 1, "components": boutons})
    return [{"type": 17, "accent_color": BLEU, "components": corps}]


def _prendre_bouton() -> Dict[str, Any]:
    return _bouton("prendre", "Prendre un numéro", "📱", 3)


def vue_panneau() -> List[Dict[str, Any]]:
    return _vue(["## Numéro X"], [_prendre_bouton()])


def vue_attente(texte: str) -> List[Dict[str, Any]]:
    return _vue(["## Numéro X", texte])


def vue_close(texte: str) -> List[Dict[str, Any]]:
    return _vue(["## Numéro X", texte], [_prendre_bouton()])


def vue_actif(a: Dict[str, Any], conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    act_id = str(a.get("id") or "")
    # Le numéro COLLÉ, sans espaces : demande expresse du propriétaire (Va IG).
    valeur = "".join(str(a.get("valeur") or "?").split())
    code = a.get("code")
    if code:
        ligne = "🔑 **Code : `%s`**" % code
        boutons = [_bouton("fini", "C'est bon", "✅", 3, act_id),
                   _bouton("retry", "Nouveau code", "🔄", 1, act_id),
                   _bouton("autre", "Autre", "🔁", 2, act_id)]
    else:
        ligne = "⏳ En attente du code…"
        boutons = [_bouton("retry", "Redemander un code", "🔄", 1, act_id),
                   _bouton("autre", "Autre", "🔁", 2, act_id),
                   _bouton("annuler", "Annuler", "❌", 4, act_id)]
    return _vue(["## `%s`" % valeur, conf.get("drapeau", "📱") + " " + ligne,
                 a.get("souci") or ""], boutons)


def _texte(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte, "flags": EPHEMERE}}


def _repondre(p: Dict[str, Any], cle: str, comps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sur ce message éphémère lui-même : on le change sur place. Sur le
    panneau du salon : un NOUVEAU message, visible du seul cliqueur, qui
    efface le précédent — jamais deux messages pour un même numéro."""
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p)
    source = int(((p.get("message") or {}).get("flags")) or 0)
    avant = _retenir(cle, jeton, app)
    if source & EPHEMERE:
        return {"type": 7, "data": {"components": comps}}
    if avant and avant.get("jeton") != jeton and \
            time.time() - float(avant.get("le") or 0) < JETON_SEC:
        try:
            _fond(lambda: _effacer(avant))
        except Exception as e:
            _log(f"effacement de l'ancien message non lancé ({type(e).__name__}: {e})")
    return {"type": 4, "data": {"flags": V2 | EPHEMERE, "components": comps}}


def _editer(app: str, jeton: str, comps: List[Dict[str, Any]]) -> int:
    code, corps = vd.api("PATCH", f"/webhooks/{app}/{jeton}/messages/@original",
                         json={"components": comps, "allowed_mentions": {"parse": []}})
    if code != 200:
        _log(f"message éphémère non mis à jour : HTTP {code} {str(corps)[:160]}")
    return code


def _redessiner(cle: str, conf: Dict[str, Any], comps: Optional[List[Dict[str, Any]]] = None) -> int:
    a, m = _actif(cle), _message(cle)
    if not m or (comps is None and not a):
        return 0
    if time.time() - float(m.get("le") or 0) > JETON_SEC:
        # Le message ne s'édite plus (jeton de 15 min) : le prochain clic du
        # VA le redessine avec ce qui est arrivé entre-temps.
        _log(f"{(a or {}).get('valeur', cle)} : jeton expiré, affichage au prochain clic")
        return 0
    return _editer(m.get("app") or "", m["jeton"], comps or vue_actif(a, conf))


# ─── Clics ────────────────────────────────────────────────────────────────
def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La réponse à un clic « numx: », ou None si ce n'est pas le nôtre :
    l'appelant (web_upload, /discord/interactions) passe au module suivant."""
    p = p or {}
    if p.get("type") != 3:
        return None
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if not cid.startswith(PREFIXE):
        return None
    gid = str(p.get("guild_id") or "")
    conf = SERVEURS.get(gid)
    if not conf:
        return _texte("Ce bouton ne sert que sur YouLab TWITTER.")
    membre = p.get("member") or {}
    user = membre.get("user") or {}
    uid = str(user.get("id") or "")
    if not uid.isdigit():
        return _texte("Compte introuvable.")
    _reprendre_ecoutes()
    morceaux = cid[len(PREFIXE):].split(":")
    action, act_id = morceaux[0], (morceaux[1] if len(morceaux) > 1 else "")
    cle = f"{gid}:{uid}"
    if action == "prendre":
        return _prendre(p, gid, uid, cle, membre, user, conf)
    if action in ("retry", "autre", "annuler", "fini"):
        return _agir(p, gid, uid, cle, membre, user, conf, action, act_id)
    return _texte("Action inconnue.")


def _staff(membre: Dict[str, Any], gid: str) -> bool:
    try:
        return vd._est_manager(membre, vd.serveur(gid))
    except Exception as e:
        _log(f"rôle staff illisible ({type(e).__name__}: {e}) : quota appliqué")
        return False


def _quota_refus(uid: str, gid: str, membre: Dict[str, Any], conf: Dict[str, Any]) -> str:
    """« » si l'achat est permis, sinon le refus à montrer. Historique
    illisible : rien n'est acheté — sans lui, rien ne bornerait la dépense."""
    if _staff(membre, gid):
        return ""
    try:
        n = numeros_du_jour(uid, gid)
    except Exception as e:
        _log(f"quota illisible pour {uid} ({type(e).__name__}: {e}) : rien n'est acheté")
        return "❌ L'historique des numéros ne se lit plus : rien n'a été acheté. Préviens un admin."
    if n >= conf["quota"]:
        _log(f"quota atteint pour {uid} ({n}/{conf['quota']})")
        return "📵 %d numéros aujourd'hui : c'est le maximum. Reviens demain." % conf["quota"]
    return ""


def _nom(user: Dict[str, Any]) -> str:
    return str(user.get("global_name") or user.get("username") or "")


def _prendre(p, gid, uid, cle, membre, user, conf):
    if not numgen.herosms_key():
        _log("clic « Prendre un numéro » : clé HeroSMS absente")
        return _repondre(p, cle, vue_close(
            "❌ Numéros indisponibles : la clé HeroSMS n'est pas posée. Préviens un admin."))
    with _VERROU:
        if cle in _ACHATS:
            # Le message « Recherche d'un numéro… » va recevoir le numéro : en
            # ouvrir un autre l'effacerait, et le numéro payé ne s'afficherait
            # nulle part. Le clic est seulement accusé.
            return {"type": 6}
        a = _actif(cle)
        if _vivant(a):
            # Un numéro déjà payé : on le remontre, on n'en rachète pas.
            rep = _repondre(p, cle, vue_actif(a, conf))
            _assurer_ecoute(cle, a, conf)
            return rep
        refus = _quota_refus(uid, gid, membre, conf)
        if refus:
            return _repondre(p, cle, vue_close(refus))
        _ACHATS.add(cle)
    salon = str(p.get("channel_id") or conf["salon"])
    # Le message d'abord, l'achat ensuite : l'achat écrit le numéro dans LE
    # message courant, qui doit déjà être celui-ci.
    rep = _repondre(p, cle, vue_attente("⏳ Recherche d'un numéro…"))
    try:
        _fond(lambda: _acheter(cle, gid, uid, _nom(user), conf, salon))
    except Exception as e:
        with _VERROU:
            _ACHATS.discard(cle)
        _log(f"achat non lancé pour {uid} ({type(e).__name__}: {e})")
        return _repondre(p, cle, vue_close("❌ Impossible pour le moment : réessaie dans un instant."))
    return rep


def _acheter(cle, gid, uid, nom, conf, salon):
    try:
        ok, res = numgen.get_number_herosms(conf["service"], conf["pays"])
        if not ok:
            _log(f"achat refusé pour {uid} : {res}")
            _redessiner(cle, conf, vue_close("❌ " + str(res)))
            return
        a = {"id": str(res["id"]), "provider": "herosms", "service": conf["service"],
             "valeur": res["phone"], "par": uid, "pris_le": int(time.time()), "salon": salon}
        with _VERROU:
            d = _lire()
            d["actifs"][cle] = a
            _ecrire(d)
        _log(f"{a['valeur']} pris par {uid} ({nom})")
        _histo_prise(a, gid, nom)
        _redessiner(cle, conf)
        _assurer_ecoute(cle, a, conf)
    finally:
        with _VERROU:
            _ACHATS.discard(cle)


def _agir(p, gid, uid, cle, membre, user, conf, action, act_id):
    with _VERROU:
        if cle in _ACHATS:
            return {"type": 6}                    # un numéro arrive dans le message courant
        a = _actif(cle)
        if not a or str(a.get("id")) != act_id:
            # Un bouton d'un ancien message : on montre ce qui est vrai maintenant.
            if _vivant(a):
                return _repondre(p, cle, vue_actif(a, conf))
            return _repondre(p, cle, vue_close("Ce numéro n'est plus actif."))
        if a.get("clos"):
            return _repondre(p, cle, vue_close("Ce numéro n'est plus actif."))
        a = _maj(cle, act_id, souci="") or a
        if action == "fini":
            if not a.get("code") and _vivant(a):
                # « C'est bon » sans code abandonnerait un numéro payé : ce
                # bouton n'existe pas dans cet état, un clic croisé peut l'envoyer.
                return _repondre(p, cle, vue_actif(a, conf))
            _maj(cle, act_id, clos="fini")
    if action == "fini":
        _histo(act_id, "fini")
        _fond(lambda: numgen.finish(act_id, "herosms"))
        return _repondre(p, cle, vue_close("✅ C'est bon."))
    if action == "retry":
        rep = _repondre(p, cle, vue_attente("⏳ Nouveau code demandé…"))
        _fond(lambda: _redemander(cle, act_id, conf))
        return rep
    rep = _repondre(p, cle, vue_attente("⏳ Annulation…" if action == "annuler" else "⏳ Autre numéro…"))
    _fond(lambda: _rendre(cle, gid, uid, membre, user, conf, act_id, action))
    return rep


def _redemander(cle, act_id, conf):
    ok, txt = numgen.retry(act_id, "herosms")
    if ok:
        a = _maj(cle, act_id, code=None, souci="")
        _log(f"nouveau code demandé sur {act_id}")
    else:
        a = _maj(cle, act_id, souci="❌ " + txt)
        _log(f"nouveau code refusé sur {act_id} : {txt}")
    if a:
        _redessiner(cle, conf)
        _assurer_ecoute(cle, a, conf)


def _rendre(cle, gid, uid, membre, user, conf, act_id, action):
    a = _actif(cle)
    if not a or str(a.get("id")) != act_id:
        return
    if a.get("code"):
        # Code reçu : le numéro a servi, on le clôt (rien à rembourser).
        numgen.finish(act_id, "herosms")
        ok, raison = True, ""
    else:
        ok, raison = numgen.cancel(act_id, "herosms")
    if not ok and _vivant(a) and "inconnue" not in raison:
        # Refusé, vivant, sans code (« annulation trop tôt — attends ~2 min ») :
        # le numéro reste affiché, avec la raison.
        _log(f"{action} de {a.get('valeur')} refusé par HeroSMS : {raison}")
        _maj(cle, act_id, souci="❌ " + raison)
        _redessiner(cle, conf)
        return
    _maj(cle, act_id, clos="remplace" if action == "autre" else "annule")
    _histo(act_id, "remplace" if action == "autre" else "annule")
    _log(f"{a.get('valeur')} : {action} par {uid}")
    if action == "annuler":
        _redessiner(cle, conf, vue_close("❌ Numéro annulé."))
        return
    refus = _quota_refus(uid, gid, membre, conf)
    if refus:
        _redessiner(cle, conf, vue_close(refus))
        return
    with _VERROU:
        if cle in _ACHATS:
            return
        _ACHATS.add(cle)
    _acheter(cle, gid, uid, _nom(user), conf, a.get("salon") or conf["salon"])


# ─── Écoute du code ───────────────────────────────────────────────────────
def _assurer_ecoute(cle: str, a: Dict[str, Any], conf: Dict[str, Any]) -> None:
    act_id = str(a.get("id") or "")
    with _VERROU:
        if not act_id or a.get("code") or not _vivant(a) or _ECOUTES.get(cle) == act_id:
            return
        _ECOUTES[cle] = act_id
    try:
        _fond(lambda: _ecouter(cle, act_id, conf))
    except Exception as e:
        with _VERROU:
            _ECOUTES.pop(cle, None)
        _log(f"écoute de {act_id} non lancée ({type(e).__name__}: {e})")


def _ecouter(cle: str, act_id: str, conf: Dict[str, Any]) -> None:
    erreurs = 0
    try:
        while True:
            a = _actif(cle)
            if not a or str(a.get("id")) != act_id or a.get("clos") or a.get("code"):
                return
            age = time.time() - float(a.get("pris_le") or 0)
            if age >= DUREE_NUMERO_SEC:
                numgen.cancel(act_id, "herosms")      # rendu s'il peut encore l'être
                _maj(cle, act_id, clos="expire")
                _log(f"{a.get('valeur')} : aucun code en {DUREE_NUMERO_SEC // 60} min")
                _redessiner(cle, conf, vue_close("⌛ Aucun code en 20 min : numéro rendu."))
                return
            etat, val = numgen.get_code(act_id, "herosms")
            if etat == "code" and val:
                if _maj(cle, act_id, code=val, code_le=int(time.time()), souci=""):
                    _histo(act_id, "code")
                    _log(f"{a.get('valeur')} : code reçu")
                    _redessiner(cle, conf)
                return
            if etat == "cancel":
                _maj(cle, act_id, clos="annule")
                _histo(act_id, "souci")
                _log(f"{a.get('valeur')} : fermé par HeroSMS")
                _redessiner(cle, conf, vue_close("❌ HeroSMS a fermé ce numéro. Prends-en un autre."))
                return
            if etat == "error":
                erreurs += 1
                _log(f"{a.get('valeur')} : lecture du code en échec ({erreurs}/{ERREURS_MAX}) : {val}")
                if erreurs >= ERREURS_MAX:
                    _maj(cle, act_id, souci="❌ Écoute du code interrompue (%s). "
                                            "Clique « Redemander un code »." % val)
                    _redessiner(cle, conf)
                    return
            else:
                erreurs = 0
            _dormir(POLL_SEC if age < POLL_RAPIDE_JUSQUA else POLL_LENT_SEC)
    finally:
        with _VERROU:
            if _ECOUTES.get(cle) == act_id:
                _ECOUTES.pop(cle, None)


def _reprendre_ecoutes() -> None:
    """Après un redémarrage, les numéros en attente n'étaient plus écoutés :
    le code arrivait chez HeroSMS et ne s'affichait jamais. Relancé au
    premier clic qui suit le démarrage (sans gateway, pas d'autre réveil)."""
    with _VERROU:
        if _REPRIS[0]:
            return
        _REPRIS[0] = True
    try:
        actifs = _lire()["actifs"]
    except Exception as e:
        _log(f"reprise des écoutes impossible ({type(e).__name__}: {e})")
        return
    n = 0
    for cle, a in list(actifs.items()):
        conf = SERVEURS.get(cle.split(":", 1)[0])
        if conf and isinstance(a, dict) and _vivant(a) and not a.get("code"):
            _assurer_ecoute(cle, a, conf)
            n += 1
    if n:
        _log(f"reprise : {n} numéro(s) en attente réécouté(s)")


def demarrer() -> None:
    """Au démarrage du site. Sans ça, un redémarrage (plusieurs par jour)
    laissait les numéros en attente sans écoute jusqu'au premier clic sur le
    panneau : le 17/10/2026, quatre numéros attendaient leur code pendant le
    redémarrage de 21:01."""
    def _go():
        _dormir(20)                          # laisser le site se lever
        for gid in SERVEURS:
            with vd.sur_serveur(gid):
                _reprendre_ecoutes()
    threading.Thread(target=_go, daemon=True).start()


# ─── Pose du panneau ──────────────────────────────────────────────────────
def _ids(composants) -> List[str]:
    out: List[str] = []
    for c in composants or []:
        if isinstance(c, dict):
            if c.get("custom_id"):
                out.append(str(c["custom_id"]))
            out += _ids(c.get("components"))
            if isinstance(c.get("accessory"), dict):
                out += _ids([c["accessory"]])
    return out


def poser_panneau(gid: str = vd.TWITTER_ID) -> str:
    """Pose le panneau dans le salon du serveur, ou remet à neuf celui qui y
    est déjà (jamais deux). Rend ce qui a été fait."""
    conf = SERVEURS[gid]
    salon = conf["salon"]
    with vd.sur_serveur(gid):
        moi = vd.bot_du_serveur(gid)["app_id"]
        code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
        if code != 200 or not isinstance(ms, list):
            return f"salon illisible : HTTP {code} {str(ms)[:160]}"
        miens = [m for m in ms if str((m.get("author") or {}).get("id")) == str(moi)
                 and PREFIXE + "prendre" in _ids(m.get("components"))]
        corps = {"flags": V2, "components": vue_panneau(), "allowed_mentions": {"parse": []}}
        if miens:
            code, rep = vd.api("PATCH", f"/channels/{salon}/messages/{miens[0]['id']}",
                               json={"components": corps["components"]})
            return f"panneau remis à neuf : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")
        code, rep = vd.api("POST", f"/channels/{salon}/messages", json=corps)
        return f"panneau posé : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["poser"]:
        vd._charger_config()
        print(poser_panneau())
    else:
        print("usage : python numeros_x_discord.py poser")
