"""« Numéro X » sur YouLab TWITTER : un numéro US loué chez HeroSMS, et son code.

Le même panneau sur YouLab THREADS depuis le 21/10/2026 (« Numéro Instagram »,
posé par Bowser), mais chez GetAText, le fournisseur des numéros Instagram de
cogs/numeros : tout ce qui change d'un serveur à l'autre est dans SERVEURS
(`poser threads`).

Propriétaire, 17/10/2026 : « mes numéros et tout j'en ai plus, me créer un
bot qui puisse me générer des numéros […] sur Hero SMS, pour me donner des
numéros de compte X ». Ses réponses : chaque VA, numéros des États-Unis, 3 par
jour, un salon dédié (📱・numéro-usa) — et « chaque personne a son truc, les
autres voient pas ce qui se passe ».

Le serveur est servi par Luigi SANS gateway : le panneau est posé par REST
(`python numeros_x_discord.py poser`), et chaque clic arrive sur
/discord/interactions (web_upload). Tout ce qui suit le clic est ÉPHÉMÈRE : le
numéro et le code ne se voient que de celui qui a cliqué.

Un formulaire déjà déroulé (propriétaire, 18/10/2026, comme le panneau
Outlook) : sous « Numéro X », la case du numéro (🇺🇸) puis celle du code (🔐),
VIDES dans le salon — aucun texte —, remplies dans le message privé :
  en attente  🇺🇸 +15550142294 · 🔐 ⏳ En attente du code…
              🔄 Redemander un code · 🔁 Autre · ❌ Annuler
  code reçu   🇺🇸 +15550142294 · 🔐 482913
              ✅ C'est bon · 🔄 Nouveau code · 🔁 Autre
Les boutons et leur ordre sont ceux du panneau Numéro de Va IG
(cogs/numeros.py, validé le 27/09/2026).
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
import functools
import hashlib
import os
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
        "fournisseur": "herosms",
        "service": "tw",                          # Twitter/X chez HeroSMS
        "pays": "187", "drapeau": "🇺🇸",           # États-Unis : 0,06 $ le 17/10/2026
        "quota": 3,                               # par jour et par VA ; le staff n'est pas bridé
        "titre": "Numéro X",
    },
    # Propriétaire, 21/10/2026, sur Threads : « je veux le truc des num »,
    # « comme pour twitter mais pour threads », puis « get atexte le meme que
    # insta ». Un compte Threads est un compte Instagram : le même panneau,
    # acheté comme les numéros Instagram (GetAText, repli SMSBower ; 0,25 $ un
    # numéro US ce jour-là), posé par Bowser.
    vd.THREADS_ID: {
        "nom": "YouLab THREADS",
        "salon": "1562393803887747122",          # 📚 RESSOURCES > 📱・numéro-usa
        "fournisseur": "getatext",
        "service": "ig",                          # « instagram/threads » chez GetAText
        "pays": "187", "drapeau": "🇺🇸",
        "quota": 3,
        "titre": "Numéro Instagram",
        # Propriétaire, 21/10/2026, captures à l'appui : « comme ça », la carte
        # numéro des salons -numero-mail d'Instagram (cogs/numeros.PanneauNumero).
        "style": "insta",
        "icone": "numeros/numero_instagram.png",  # sous static/ (copie de emojis/)
    },
    # Propriétaire, 23/10/2026, sur 📱・numéro-usa d'Agency VA INSTAGRAM :
    # « remplace le truc num » (le panneau d'un autre bot, « Numéro US »).
    # Exactement comme Threads : la carte Instagram dans chaque ticket, par Wario.
    vd.AGENCY_IG_ID: {
        "nom": "Agency VA INSTAGRAM",
        "salon": "1548399504527466656",          # 🧰 OUTILS INSTAGRAM > 📱・numéro-usa
        "fournisseur": "getatext",
        "service": "ig",
        "pays": "187", "drapeau": "🇺🇸",
        "quota": 3,
        "titre": "Numéro Instagram",
        "style": "insta",
        "icone": "numeros/numero_instagram.png",
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
    if not isinstance(d.get("cartes"), dict):
        d["cartes"] = {}
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
    if isinstance(m, dict) and (m.get("jeton") or m.get("carte")):
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


def _retenir_carte(cle: str, salon: str, mid: str) -> None:
    """La carte du ticket devient LE message de la personne : la suite s'y
    écrit par le bot, sans jeton d'interaction (ni ses 15 minutes)."""
    with _VERROU:
        d = _lire()
        d["messages"][cle] = {"carte": True, "salon": str(salon), "message": str(mid),
                              "le": time.time()}
        _ecrire(d)


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


def _prendre_bouton(conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Bleu sur la carte Instagram : la place du « Redemander un code ».
    return _bouton("prendre", "Prendre un numéro", "📱", 1 if _insta(conf) else 3)


#: Le panneau est un formulaire DÉJÀ DÉROULÉ, ses cases vides avant le clic
#: (propriétaire, 18/10/2026 : « pareil pour les numéros », comme le panneau
#: Outlook, et « juste des blancs avant la commande », aucun texte). Un code
#: fait d'espaces insécables s'affiche comme une case grise vide.
BLANC = "`" + "\u00a0" * 16 + "`"
BLANC_CODE = "`" + "\u00a0" * 8 + "`"


def _drapeau(conf: Optional[Dict[str, Any]] = None) -> str:
    return (conf or SERVEURS[vd.TWITTER_ID]).get("drapeau", "📱")


def _titre(conf: Optional[Dict[str, Any]] = None) -> str:
    return "## " + (conf or SERVEURS[vd.TWITTER_ID]).get("titre", "Numéro X")


def _numero(a: Dict[str, Any]) -> str:
    # Le numéro COLLÉ, sans espaces : demande expresse du propriétaire (Va IG).
    return "`%s`" % "".join(str(a.get("valeur") or "?").split())


# ─── La carte Instagram (Threads) ─────────────────────────────────────────
# Propriétaire, 21/10/2026, sur deux captures de la carte des salons
# -numero-mail : « comme ça de base, si y a pas de num ça met …. en attente »,
# et « ça doit tenir en 1 truc ». UNE carte, rose, le numéro en gros, le
# drapeau et l'état dessous, l'icône à droite, une rangée de boutons ; elle
# change d'état sur place. Dans le salon, la carte vide ; au clic, la carte du
# VA, privée, identique, qui se remplit (un nouveau clic remplace l'ancienne).
ROSE = 0xE1306C                 # le rose de cogs/numeros (_ROSE)
VIDE = "…."
STATIC = Path(__file__).resolve().parent / "static"


def _insta(conf: Optional[Dict[str, Any]]) -> bool:
    return (conf or {}).get("style") == "insta"


@functools.lru_cache(maxsize=None)
def _icone_url(rel: str) -> str:
    """L'adresse publique de l'icône : une réponse à un clic ne porte pas de
    fichier, la vignette vient donc du site (static/, comme les vignettes du
    podium). Versionnée : le site sert static/ en « immutable », un 404 lu
    avant la mise en ligne resterait sept jours chez Cloudflare. "" si le
    fichier manque : la carte part sans icône plutôt que pas du tout."""
    try:
        v = hashlib.md5((STATIC / rel).read_bytes()).hexdigest()[:8]
    except OSError as e:
        _log(f"icône static/{rel} illisible ({type(e).__name__}) : carte sans icône")
        return ""
    return f"{vd.SITE.rstrip('/')}/static/{rel}?v={v}"


def _carte(conf: Dict[str, Any], numero: str, etat: str,
           boutons: Optional[List[Dict[str, Any]]], souci: str = "") -> List[Dict[str, Any]]:
    lignes = ["## `%s`" % numero, _drapeau(conf) + " " + etat] + ([souci] if souci else [])
    textes = [{"type": 10, "content": t} for t in lignes]
    url = _icone_url(conf["icone"]) if conf.get("icone") else ""
    corps: List[Dict[str, Any]] = (
        [{"type": 9, "components": textes, "accessory": {"type": 11, "media": {"url": url}}}]
        if url else textes)
    if boutons:
        corps.append({"type": 1, "components": boutons})
    return [{"type": 17, "accent_color": ROSE, "components": corps}]


def _valeur(a: Dict[str, Any]) -> str:
    return "".join(str(a.get("valeur") or "?").split())


def vue_panneau(conf: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if _insta(conf):
        return _carte(conf, VIDE, "⏳ En attente", [_prendre_bouton(conf)])
    return _vue([_titre(conf), _drapeau(conf) + " " + BLANC, "🔐 " + BLANC_CODE],
                [_prendre_bouton()])


def vue_attente(texte: str, a: Optional[Dict[str, Any]] = None,
                conf: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Le formulaire pendant un appel à HeroSMS : le numéro en cours s'il y
    en a un, l'attente dans la case du code ; sinon l'attente dans la case du
    numéro."""
    if _insta(conf):
        return _carte(conf, _valeur(a) if a else VIDE, texte, None)
    if a:
        return _vue([_titre(conf), _drapeau(conf) + " " + _numero(a), "🔐 " + texte])
    return _vue([_titre(conf), _drapeau(conf) + " " + texte, "🔐 " + BLANC_CODE])


def vue_close(texte: str, conf: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if _insta(conf):
        return _carte(conf, VIDE, "⏳ En attente", [_prendre_bouton(conf)], souci=texte)
    return _vue([_titre(conf), _drapeau(conf) + " " + BLANC, "🔐 " + BLANC_CODE, texte],
                [_prendre_bouton()])


def vue_actif(a: Dict[str, Any], conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Le formulaire rempli : le numéro, puis le code (ou son attente)."""
    act_id = str(a.get("id") or "")
    code = a.get("code")
    if code:
        ligne = "**%s**" % code
        boutons = [_bouton("fini", "C'est bon", "✅", 3, act_id),
                   _bouton("retry", "Nouveau code", "🔄", 1, act_id),
                   _bouton("autre", "Autre", "🔁", 2, act_id)]
    else:
        ligne = "⏳ En attente du code…"
        boutons = [_bouton("retry", "Redemander un code", "🔄", 1, act_id),
                   _bouton("autre", "Autre", "🔁", 2, act_id),
                   _bouton("annuler", "Annuler", "❌", 4, act_id)]
    if _insta(conf):
        etat = ("🔑 **Code : `%s`**" % code) if code else "⏳ En attente du code…"
        return _carte(conf, _valeur(a), etat, boutons, souci=a.get("souci") or "")
    return _vue([_titre(conf), _drapeau(conf) + " " + _numero(a), "🔐 " + ligne,
                 a.get("souci") or ""], boutons)


def _texte(texte: str) -> Dict[str, Any]:
    return {"type": 4, "data": {"content": texte, "flags": EPHEMERE}}


def _repondre(p: Dict[str, Any], cle: str, comps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sur ce message éphémère lui-même : on le change sur place. Sur le
    panneau du salon : un NOUVEAU message, visible du seul cliqueur, qui
    efface le précédent — jamais deux messages pour un même numéro."""
    carte = p.get("_carte")
    if carte:
        # La carte du ticket : changée sur place, jamais un autre message.
        _retenir_carte(cle, carte["salon"], carte["message"])
        return {"type": 7, "data": {"components": comps}}
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p)
    source = int(((p.get("message") or {}).get("flags")) or 0)
    avant = _retenir(cle, jeton, app)
    if source & EPHEMERE:
        return {"type": 7, "data": {"components": comps}}
    if avant and avant.get("jeton") and avant.get("jeton") != jeton and \
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
    if m.get("carte"):
        code, corps = vd.api("PATCH", f"/channels/{m['salon']}/messages/{m['message']}",
                             json={"components": comps or vue_actif(a, conf),
                                   "allowed_mentions": {"parse": []}})
        if code != 200:
            _log(f"carte du salon {m['salon']} non mise à jour : HTTP {code} {str(corps)[:160]}")
        return code
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
        return _texte("Ce bouton ne sert pas sur ce serveur.")
    membre = p.get("member") or {}
    user = membre.get("user") or {}
    uid = str(user.get("id") or "")
    if not uid.isdigit():
        return _texte("Compte introuvable.")
    _reprendre_ecoutes()
    morceaux = cid[len(PREFIXE):].split(":")
    action, act_id = morceaux[0], (morceaux[1] if len(morceaux) > 1 else "")
    carte = _carte_du_clic(p)
    if carte:
        # Une carte de ticket : le numéro et le quota sont ceux du VA du
        # ticket, même quand son manager clique pour lui (staff : non bridé).
        p = dict(p, _carte=carte)
        if carte["uid"] != uid:
            uid, user = carte["uid"], {}
    cle = f"{gid}:{uid}"
    if action == "prendre":
        return _prendre(p, gid, uid, cle, membre, user, conf)
    if action == "menu":
        return _menu(p, gid, uid, conf)
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
        # Seuls les numéros qui ont reçu leur code comptent : les autres sont
        # rendus, donc remboursés (cogs.numeros.numeros_du_jour).
        return "📵 %d codes reçus aujourd'hui : c'est le maximum. Reviens demain." % conf["quota"]
    return ""


NOMS_FOURNISSEURS = {"herosms": "HeroSMS", "getatext": "GetAText", "smsbower": "SMSBower"}


def _fournisseur(conf: Dict[str, Any]) -> str:
    return str(conf.get("fournisseur") or "herosms")


def _prov(a: Optional[Dict[str, Any]]) -> str:
    """Le fournisseur d'UNE activation : avec GetAText, le repli SMSBower peut
    avoir servi ; les premières (17/10) ne portaient que HeroSMS."""
    return str((a or {}).get("provider") or "herosms")


def _cle_posee(conf: Dict[str, Any]) -> bool:
    if _fournisseur(conf) == "herosms":
        return bool(numgen.herosms_key())
    return bool(numgen.getatext_key() or numgen.smsbower_key())


def _cle_credit(conf: Dict[str, Any]) -> str:
    """La clé de l'alerte « sans crédit » : GetAText a la même que les
    panneaux Instagram (cogs/numeros) — c'est le même compte."""
    return "credit:herosms" if _fournisseur(conf) == "herosms" else "credit:sms"


def _acheter_chez(conf: Dict[str, Any]):
    if _fournisseur(conf) == "herosms":
        return numgen.get_number_herosms(conf["service"], conf["pays"])
    # Le même achat que les numéros Instagram (GetAText, repli SMSBower), mais
    # dans CE pays : le drapeau du panneau ne doit pas mentir.
    return numgen.get_number(conf["service"], conf["pays"])


def _souci_achat(res: Any, conf: Dict[str, Any]) -> str:
    """Le refus d'achat tel que le VA le lit. Un solde vide se dit en clair et
    prévient le staff une fois (numgen.alerter_staff) ; recharger reste au
    propriétaire."""
    if not numgen.sans_credit(res):
        return "❌ " + str(res)
    cle = _cle_credit(conf)
    if cle == "credit:herosms":
        alerte = ("⚠️ **HeroSMS sans crédit** (« %s ») : les VA de Twitter ne peuvent plus "
                  "prendre de Numéro X. À recharger sur hero-sms.com." % str(res)[:120])
    else:
        alerte = ("⚠️ **Numéros SMS sans crédit** (« %s ») : les VA ne peuvent plus prendre "
                  "de numéro (Instagram, Threads). À recharger." % str(res)[:160])
    etat = numgen.alerter_staff(cle, alerte)
    if etat not in ("envoye", "deja", "hors production"):
        _log(f"alerte « {cle} » non envoyée au staff : {etat}")
    return "❌ Service de numéros sans crédit : le staff est prévenu."


def _nom(user: Dict[str, Any]) -> str:
    return str(user.get("global_name") or user.get("username") or "")


def _prendre(p, gid, uid, cle, membre, user, conf):
    if not _cle_posee(conf):
        nom = NOMS_FOURNISSEURS.get(_fournisseur(conf), _fournisseur(conf))
        _log(f"clic « Prendre un numéro » : clé {nom} absente")
        return _repondre(p, cle, vue_close(
            "❌ Numéros indisponibles : la clé %s n'est pas posée. Préviens un admin." % nom, conf))
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
            return _repondre(p, cle, vue_close(refus, conf))
        _ACHATS.add(cle)
    salon = str(p.get("channel_id") or conf["salon"])
    # Le message d'abord, l'achat ensuite : l'achat écrit le numéro dans LE
    # message courant, qui doit déjà être celui-ci.
    rep = _repondre(p, cle, vue_attente("⏳ Recherche d'un numéro…", None, conf))
    try:
        _fond(lambda: _acheter(cle, gid, uid, _nom(user), conf, salon))
    except Exception as e:
        with _VERROU:
            _ACHATS.discard(cle)
        _log(f"achat non lancé pour {uid} ({type(e).__name__}: {e})")
        return _repondre(p, cle, vue_close("❌ Impossible pour le moment : réessaie dans un instant.",
                                           conf))
    return rep


def _acheter(cle, gid, uid, nom, conf, salon):
    try:
        ok, res = _acheter_chez(conf)
        if not ok:
            _log(f"achat refusé pour {uid} : {res}")
            _redessiner(cle, conf, vue_close(_souci_achat(res, conf), conf))
            return
        numgen.fin_alerte(_cle_credit(conf))
        a = {"id": str(res["id"]), "provider": res.get("provider") or _fournisseur(conf),
             "service": conf["service"],
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
            return _repondre(p, cle, vue_close("Ce numéro n'est plus actif.", conf))
        if a.get("clos"):
            return _repondre(p, cle, vue_close("Ce numéro n'est plus actif.", conf))
        a = _maj(cle, act_id, souci="") or a
        if action == "fini":
            if not a.get("code") and _vivant(a):
                # « C'est bon » sans code abandonnerait un numéro payé : ce
                # bouton n'existe pas dans cet état, un clic croisé peut l'envoyer.
                return _repondre(p, cle, vue_actif(a, conf))
            _maj(cle, act_id, clos="fini")
    if action == "fini":
        _histo(act_id, "fini")
        _fond(lambda: numgen.finish(act_id, _prov(a)))
        return _repondre(p, cle, vue_close("✅ C'est bon.", conf))
    if action == "retry":
        rep = _repondre(p, cle, vue_attente("⏳ Nouveau code demandé…", a, conf))
        _fond(lambda: _redemander(cle, act_id, conf))
        return rep
    rep = _repondre(p, cle, vue_attente("⏳ Annulation…" if action == "annuler" else "⏳ Autre numéro…",
                                        a, conf))
    _fond(lambda: _rendre(cle, gid, uid, membre, user, conf, act_id, action))
    return rep


def _redemander(cle, act_id, conf):
    ok, txt = numgen.retry(act_id, _prov(_actif(cle)))
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
        numgen.finish(act_id, _prov(a))
        ok, raison = True, ""
    else:
        ok, raison = numgen.cancel(act_id, _prov(a))
    if not ok and _vivant(a) and "inconnue" not in raison:
        # Refusé, vivant, sans code (« annulation trop tôt — attends ~2 min ») :
        # le numéro reste affiché, avec la raison.
        _log(f"{action} de {a.get('valeur')} refusé par "
             f"{NOMS_FOURNISSEURS.get(_prov(a), _prov(a))} : {raison}")
        _maj(cle, act_id, souci="❌ " + raison)
        _redessiner(cle, conf)
        return
    _maj(cle, act_id, clos="remplace" if action == "autre" else "annule")
    _histo(act_id, "remplace" if action == "autre" else "annule")
    _log(f"{a.get('valeur')} : {action} par {uid}")
    if action == "annuler":
        _redessiner(cle, conf, vue_close(
            "❌ Numéro annulé." if a.get("code")
            else "❌ Numéro annulé : il ne compte pas dans tes %d du jour." % conf["quota"], conf))
        return
    refus = _quota_refus(uid, gid, membre, conf)
    if refus:
        _redessiner(cle, conf, vue_close(refus, conf))
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
                numgen.cancel(act_id, _prov(a))       # rendu s'il peut encore l'être
                _maj(cle, act_id, clos="expire")
                _log(f"{a.get('valeur')} : aucun code en {DUREE_NUMERO_SEC // 60} min")
                _redessiner(cle, conf, vue_close(
                    "⌛ Aucun code en 20 min : numéro rendu, il ne compte pas dans tes %d du jour."
                    % conf["quota"], conf))
                return
            etat, val = numgen.get_code(act_id, _prov(a))
            if etat == "code" and val:
                if _maj(cle, act_id, code=val, code_le=int(time.time()), souci=""):
                    _histo(act_id, "code")
                    _log(f"{a.get('valeur')} : code reçu")
                    _redessiner(cle, conf)
                return
            if etat == "cancel":
                _maj(cle, act_id, clos="annule")
                _histo(act_id, "souci")
                _log(f"{a.get('valeur')} : fermé par {NOMS_FOURNISSEURS.get(_prov(a), _prov(a))}")
                _redessiner(cle, conf, vue_close("❌ Le fournisseur a fermé ce numéro. Prends-en un autre.",
                                                 conf))
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
    # Le récap ne tourne que sur le VPS : ailleurs (Mac, suites de tests), il
    # posterait des chiffres d'essai dans le vrai salon.
    if os.environ.get("VA_MACHINE_PROD") == "1":
        threading.Thread(target=_boucle_recap, daemon=True).start()
        threading.Thread(target=_boucle_cartes, daemon=True).start()


# ─── Récap du jour (« debrief-day ») ──────────────────────────────────────
# Le récap des numéros (cogs/numeros.py) est tenu par le bot admin, qui n'est
# pas sur YouLab TWITTER : du 17 au 20/10/2026, ses 26 numéros sont restés
# « en attente de salon », 53 WARNING au journal. Propriétaire, 21/10/2026 :
# le récap, oui, dans un « 📊・debrief-day » qu'il crée lui-même dans 🔒 STAFF.
# Même règle que le récap d'origine — UN message par jour, créé au premier
# tour (même à 0), édité quand un chiffre change, figé à minuit (heure du
# Bénin) puis corrigé tant qu'un numéro de la journée attend son code —, mais
# posté par REST avec Luigi, comme recap_clics_rest. Les mêmes chiffres
# (cogs.numeros.agreger) et la même image (numeros_image) : un seul récap.
# Le cog écarte ces serveurs du sien (cogs.numeros._serveurs_rest).

RECAP_FICHIER = Path(__file__).resolve().parent / "data" / "numeros_x_recap.json"
RECAP_PAS_SEC = 60
#: Un salon absent est recherché de nouveau au plus toutes les 10 minutes.
SALON_ABSENT_SEC = 600
#: Sans nouvel événement, le message est quand même revu (salon recréé, image
#: refaite) une fois par heure.
RECAP_REVOIR_SEC = 3600
#: Un envoi refusé (droits, panne Discord) est retenté au bout de 5 minutes.
RECAP_ECHEC_SEC = 300
#: Les photos de profil : quelques secondes en tout, au-delà des initiales.
PHOTOS_DELAI_SEC = 8.0

_RECAP: Dict[str, Any] = {"gen": None, "jour": None, "reveil": 0.0}
_SALONS: Dict[str, Any] = {}        # serveur -> (salon ou None, lu le)
_SALONS_REFUS: set = set()          # (serveur, code HTTP) déjà dits
_NOMS: Dict[str, Any] = {}          # « gid:uid » -> (nom, url de la photo, lu le)
_PHOTOS: Dict[str, bytes] = {}      # url -> octets


def _recap_lire() -> Dict[str, Any]:
    d = safe_json.load(RECAP_FICHIER, default={}) or {}
    if not isinstance(d, dict):
        _log(f"{RECAP_FICHIER.name} n'est pas un objet JSON : repart à vide")
        d = {}
    for k in ("jours", "dits"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _recap_ecrire(d: Dict[str, Any]) -> None:
    RECAP_FICHIER.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(RECAP_FICHIER, d, indent=1):
        _log(f"écriture de {RECAP_FICHIER.name} refusée : le récap pourrait être reposté")


def _dire_une_fois(d: Dict[str, Any], sujet: str, etat: str, texte: str) -> bool:
    """Un souci du récap se dit UNE fois, même après un redémarrage (retenu
    dans le registre) : le récap d'origine redisait le sien quatre fois à
    chaque démarrage. Il se redit quand son état change. Rend True si dit."""
    if d["dits"].get(sujet) == etat:
        return False
    d["dits"][sujet] = etat
    _log(texte)
    return True


def _salon_debrief(gid: str) -> Optional[str]:
    """Le salon « debrief-day » du serveur, quel que soit son décor (même règle
    que cogs.numeros._salons_debrief), lu par REST."""
    vu = _SALONS.get(gid)
    if vu and time.time() - vu[1] < (RECAP_REVOIR_SEC if vu[0] else SALON_ABSENT_SEC):
        return vu[0]
    from cogs.welcome import nom_sans_decor
    with vd.sur_serveur(gid):
        code, salons = vd.api("GET", f"/guilds/{gid}/channels")
    if code != 200 or not isinstance(salons, list):
        # Relu dans SALON_ABSENT_SEC, et dit une fois par refus : sans ça, un
        # bot privé de lecture l'aurait écrit à chaque tour.
        if (gid, code) not in _SALONS_REFUS:
            _SALONS_REFUS.add((gid, code))
            _log(f"récap : salons de {gid} illisibles (HTTP {code})")
        _SALONS[gid] = (vu[0] if vu else None, time.time())
        return _SALONS[gid][0]
    trouve = [str(c["id"]) for c in sorted(salons, key=lambda c: c.get("position") or 0)
              if c.get("type") == 0
              and nom_sans_decor(str(c.get("name") or "")).lstrip("-_") == _num().RECAP_SALON]
    _SALONS[gid] = (trouve[0] if trouve else None, time.time())
    return _SALONS[gid][0]


def _membre(gid: str, uid: str, note: str = ""):
    """(nom affiché, adresse de la photo ou "") du VA, lus par REST et gardés
    une heure. Parti du serveur : le nom noté à la prise."""
    cle = f"{gid}:{uid}"
    vu = _NOMS.get(cle)
    if vu and time.time() - vu[2] < 3600:
        return vu[0], vu[1]
    with vd.sur_serveur(gid):
        code, m = vd.api("GET", f"/guilds/{gid}/members/{uid}")
    if code != 200 or not isinstance(m, dict):
        _NOMS[cle] = (str(note or uid), "", time.time())
        return _NOMS[cle][0], ""
    u = m.get("user") or {}
    nom = str(m.get("nick") or u.get("global_name") or u.get("username") or note or uid)
    url = ""
    if m.get("avatar"):
        url = f"https://cdn.discordapp.com/guilds/{gid}/users/{uid}/avatars/{m['avatar']}.png?size=128"
    elif u.get("avatar"):
        url = f"https://cdn.discordapp.com/avatars/{uid}/{u['avatar']}.png?size=128"
    _NOMS[cle] = (nom, url, time.time())
    return nom, url


def _photos(urls: Dict[str, str]) -> Dict[str, bytes]:
    """{uid: PNG} ; une photo absente donne des initiales sur l'image."""
    import requests
    out: Dict[str, bytes] = {}
    fin = time.time() + PHOTOS_DELAI_SEC
    for uid, url in urls.items():
        if not url:
            continue
        if url not in _PHOTOS and time.time() < fin:
            try:
                r = requests.get(url, timeout=max(1.0, fin - time.time()))
                if r.status_code == 200 and r.content:
                    if len(_PHOTOS) > 200:
                        _PHOTOS.clear()
                    _PHOTOS[url] = r.content
            except Exception as e:
                _log(f"récap : photo de {uid} non lue ({type(e).__name__})")
        if url in _PHOTOS:
            out[uid] = _PHOTOS[url]
    return out


def _textes(composants) -> List[str]:
    out: List[str] = []
    for c in composants or []:
        if isinstance(c, dict):
            if isinstance(c.get("content"), str):
                out.append(c["content"])
            out += _textes(c.get("components"))
    return out


def _retrouver(salon: str, jour, moi: str) -> Optional[str]:
    """Le récap de `jour` déjà posté par ce bot dans le salon (registre perdu,
    réponse d'envoi perdue) : à éditer, pas à reposter."""
    N = _num()
    nom = N.NOM_IMAGE_RECAP % jour.isoformat()
    titre = "## " + N.titre_recap(jour, False)
    code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
    if code != 200 or not isinstance(ms, list):
        return None
    for m in ms:
        if str((m.get("author") or {}).get("id")) != str(moi):
            continue
        if any(a.get("filename") == nom for a in m.get("attachments") or []) or \
                any(t.startswith(titre) for t in _textes(m.get("components"))):
            return str(m["id"])
    return None


def _corps_recap(jour, agg: Dict[str, Any], noms: Dict[str, str], photos: Dict[str, bytes],
                 final: bool, now: float) -> Dict[str, Any]:
    """Les arguments de vd.api : l'image (Components V2, une galerie) comme
    le récap d'origine, sinon son texte. Sans « flags » : un PATCH n'a pas le
    droit d'y toucher, le POST l'ajoute."""
    import json
    import numeros_image
    N = _num()
    try:
        png = numeros_image.dessiner_recap(
            jour, agg, noms, photos, not final, None, now, seuil_loupe=N.RECAP_SEUIL_LOUPE,
            zero_direct=N.RECAP_ZERO_DIRECT, zero_final=N.RECAP_ZERO_FINAL, tz=N.BENIN,
            cle_nom=N._cle_nom_recap(noms))
    except Exception as e:
        png = None
        _log(f"récap du {jour.isoformat()} : image impossible ({type(e).__name__}: "
             f"{str(e)[:120]}) -- en texte")
    if png:
        nom = N.NOM_IMAGE_RECAP % jour.isoformat()
        titre_alt, desc_alt = N.alt_recap(jour, agg, final, now)
        corps = {"components": [
            {"type": 10, "content": "## " + N.titre_recap(jour, False)},
            {"type": 12, "items": [{"media": {"url": "attachment://" + nom},
                                    "description": ("%s\n%s" % (titre_alt, desc_alt))[:N.RECAP_ALT_MAX]}]}],
            "attachments": [{"id": 0, "filename": nom}], "allowed_mentions": {"parse": []}}
        return {"data": {"payload_json": json.dumps(corps)},
                "files": {"files[0]": (nom, png, "image/png")}}
    titre, morceaux = N.texte_recap(jour, agg, noms, limite=N.RECAP_TEXTE_V2_MAX,
                                    en_direct=None if final else now)
    return {"json": {"components": [{"type": 10, "content": ("## %s\n%s" % (titre, morceaux[0]))
                                     [:N.RECAP_V2_BLOC_MAX]}],
                     "attachments": [], "allowed_mentions": {"parse": []}}}


def _ecrire_recap(gid: str, salon: str, moi: str, jour, fiche: Dict[str, Any],
                  kw: Dict[str, Any]):
    """Édite le message du jour, le retrouve, ou le poste. Rend (id, "") ou
    (None, le refus) : retenté plus tard, dit une fois par l'appelant."""
    import json
    mid = str(fiche.get("message") or "") if str(fiche.get("salon") or "") == salon else ""
    if not mid:
        mid = _retrouver(salon, jour, moi) or ""
    if mid:
        code, rep = vd.api("PATCH", f"/channels/{salon}/messages/{mid}", **kw)
        if code == 200:
            return mid, ""
        if code != 404:
            return None, f"édition refusée : HTTP {code} {str(rep)[:120]}"
        # Supprimé à la main : on le repose.
    if "json" in kw:
        kw = {"json": dict(kw["json"], flags=V2)}
    else:
        corps = json.loads(kw["data"]["payload_json"])
        kw = {"data": {"payload_json": json.dumps(dict(corps, flags=V2))}, "files": kw["files"]}
    code, rep = vd.api("POST", f"/channels/{salon}/messages", **kw)
    if code == 200 and isinstance(rep, dict) and rep.get("id"):
        return str(rep["id"]), ""
    if code == 404:
        _SALONS.pop(gid, None)              # salon supprimé : relu au tour suivant
    return None, f"envoi refusé : HTTP {code} {str(rep)[:120]}"


def recap_tour(maintenant: Optional[float] = None, forcer: bool = False) -> Dict[str, Any]:
    """Un tour du récap des serveurs de SERVEURS. Rend le bilan du tour."""
    import json
    N = _num()
    now = float(time.time() if maintenant is None else maintenant)
    bilan: Dict[str, Any] = {"postes": [], "edites": [], "sans_salon": [], "echecs": []}
    if not forcer and not N.machine_prod():
        return bilan
    gen, auj = N._HISTO_GEN[0], N.jour_benin(now)
    reg = _recap_lire()
    salons: Dict[str, Optional[str]] = {}
    dit = False
    for gid, conf in SERVEURS.items():
        salons[gid] = _salon_debrief(gid)
        if not salons[gid]:
            dit |= _dire_une_fois(reg, f"salon:{gid}", "absent",
                                  f"récap : aucun salon « {N.RECAP_SALON} » sur {conf['nom']} -- "
                                  f"les numéros attendent, ils partiront dès qu'il existera "
                                  f"(dit une fois)")
            bilan["sans_salon"].append(gid)
        else:
            dit |= _dire_une_fois(reg, f"salon:{gid}", salons[gid],
                                  f"récap : salon {salons[gid]} trouvé sur {conf['nom']}")
    vu = _RECAP
    if not any(salons.values()) or (
            not forcer and vu["gen"] == gen and vu["jour"] == auj.isoformat()
            and now < vu["reveil"]):
        if dit:
            _recap_ecrire(reg)
        return bilan
    try:
        entrees = N._histo_lire()
    except Exception as e:
        _log(f"récap : historique illisible ({type(e).__name__}: {e})")
        return bilan
    jours = N.jours_a_recapituler(now) + [auj]
    for k in [k for k in reg["jours"] if k < jours[0].isoformat()]:
        reg["jours"].pop(k, None)
    a_refaire = False
    for gid, conf in SERVEURS.items():
        salon = salons[gid]
        if not salon:
            continue
        moi = vd.bot_du_serveur(gid)["app_id"]
        for jour in jours:
            cle = jour.isoformat()
            fiche = dict((reg["jours"].get(cle) or {}).get(gid) or {})
            if fiche.get("fige"):
                continue                    # salon changé depuis : l'ancien message reste
            final = jour < auj
            agg = N.agreger(entrees, jour, now).get(gid) or N._agg_zero()
            if final and not fiche.get("message") and N._agg_vide(agg):
                # Aucun jour vide posté après coup, comme le récap d'origine.
                reg["jours"].setdefault(cle, {})[gid] = {"fige": True, "salon": salon, "vide": True}
                continue
            infos = {u: _membre(gid, u, v.get("nom") or "") for u, v in agg["vas"].items()}
            noms = {u: i[0] for u, i in infos.items()}
            signature = json.dumps([final, agg, noms], sort_keys=True, default=str)
            if fiche.get("signature") == signature and fiche.get("message") \
                    and fiche.get("salon") == salon:
                if final and not agg.get("attente"):
                    fiche["fige"] = True
                    reg["jours"].setdefault(cle, {})[gid] = fiche
                continue
            with vd.sur_serveur(gid):
                kw = _corps_recap(jour, agg, noms, _photos({u: i[1] for u, i in infos.items()}),
                                  final, now)
                mid, refus = _ecrire_recap(gid, salon, moi, jour, fiche, kw)
            if not mid:
                # Droits ou panne : retenté dans RECAP_ECHEC_SEC, sans redire
                # la même raison à chaque essai.
                a_refaire = True
                bilan["echecs"].append((cle, gid))
                # « envoi refusé : HTTP 403 » : la raison, sans le détail qui varie.
                _dire_une_fois(reg, f"envoi:{gid}", " ".join(refus.split(" ")[:5]),
                               f"récap du {cle} sur {conf['nom']} : {refus} -- nouvel essai "
                               f"dans {RECAP_ECHEC_SEC // 60} min (dit une fois)")
                break
            reg["dits"].pop(f"envoi:{gid}", None)
            (bilan["edites"] if mid == str(fiche.get("message") or "") else bilan["postes"]).append((cle, gid))
            fiche.update(salon=salon, message=mid, signature=signature, final=final,
                         fige=bool(final and not agg.get("attente")))
            reg["jours"].setdefault(cle, {})[gid] = fiche
            _recap_ecrire(reg)              # au fil de l'eau : pas de doublon après un arrêt
    attentes = [N._ts(e.get("pris_le")) + N.DUREE_NUMERO_SEC for e in entrees
                if str(e.get("serveur")) in SERVEURS and N._issue(e, now) == "attente"]
    vu.update(gen=gen, jour=auj.isoformat(),
              reveil=min(attentes + [now + (RECAP_ECHEC_SEC if a_refaire else RECAP_REVOIR_SEC)]))
    _recap_ecrire(reg)
    for quoi in ("postes", "edites"):
        if bilan[quoi]:
            _log(f"récap : {quoi} {', '.join(f'{c} ({g})' for c, g in bilan[quoi])}")
    return bilan


def _boucle_recap() -> None:
    # time.sleep et pas _dormir : les tests remplacent _dormir par rien.
    time.sleep(60)                           # le bot charge cogs.numeros entre-temps
    while True:
        try:
            recap_tour()
        except Exception as e:
            _log(f"tour du récap en échec ({type(e).__name__}: {e})")
        time.sleep(RECAP_PAS_SEC)


# ─── Une carte dans le ticket de chaque VA (Threads) ──────────────────────
# Propriétaire, 21/10/2026, devant la carte privée : « ça recrée un message tu
# vois », puis « met le dans leur truc alors c'est bon ? » sur la capture d'un
# ticket : comme les salons -numero-mail de Youl4b, UNE carte par VA, dans son
# salon perso (tickets_discord), postée par le bot du serveur, qui change sur
# place — jamais de message éphémère ni de nouveau message. La carte vit dans
# data/numeros_x.json (« cartes » : {salon: {message, uid, gid}}) ; le salon
# 📱・numéro-usa ne garde qu'une ligne qui y renvoie (vue_renvoi).
CARTES_PAS_SEC = 600
#: Une carte connue est revérifiée (supprimée à la main ?) une fois par jour.
CARTE_REVOIR_SEC = 86400
TEXTE_RENVOI = "📱 Ton numéro est maintenant dans ton salon perso."
#: Le salon est devenu « 📋・menu » (propriétaire, 23/10/2026, mêmes ids).
TEXTE_MENU = "📋 Ton menu s'affiche dans ton salon perso."
_CARTES_DITS: set = set()


def _cartes_auto(gid: str) -> bool:
    return bool((_lire().get("cartes_auto") or {}).get(str(gid)))


def _carte_du_clic(p: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """{salon, message, uid} si le clic vient de la carte d'un ticket."""
    salon = str(p.get("channel_id") or "")
    mid = str((p.get("message") or {}).get("id") or "")
    c = _lire()["cartes"].get(salon)
    if isinstance(c, dict) and mid and str(c.get("message")) == mid and c.get("uid"):
        return {"salon": salon, "message": mid, "uid": str(c["uid"])}
    return None


def vue_renvoi(conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"type": 17, "accent_color": ROSE if _insta(conf) else BLEU,
             "components": [{"type": 10, "content": TEXTE_RENVOI}]}]


def vue_menu(conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Le salon 📱・numéro-usa une fois les cartes en place. Propriétaire,
    23/10/2026 : la carte remonte dans un ticket qui vit, l'épingler ne suffit
    pas — « remplacer numéro-usa par un menu qui crée le menu dans leur
    salon ». Un clic ramène la carte du VA tout en bas de SON salon perso."""
    return [{"type": 17, "accent_color": ROSE if _insta(conf) else BLEU, "components": [
        {"type": 10, "content": TEXTE_MENU},
        {"type": 1, "components": [_bouton("menu", "Afficher le menu", "📋", 1)]}]}]


def ramener_carte(gid: str, uid: str, salon: str) -> str:
    """La carte du VA revient en dernier dans son salon perso : reposée en
    bas dans son état du moment, l'ancienne retirée (le bot ne retire que SA
    carte). Rend « deja » (déjà en bas), « ramenee » ou « echec »."""
    conf, cle = SERVEURS[gid], f"{gid}:{uid}"
    with vd.sur_serveur(gid):
        ancien = str((_lire()["cartes"].get(salon) or {}).get("message") or "")
        code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=1")
        if ancien and code == 200 and isinstance(ms, list) and ms and str(ms[0].get("id")) == ancien:
            return "deja"
        code, rep = vd.api("POST", f"/channels/{salon}/messages",
                           json={"flags": V2, "components": _vue_carte(cle, conf),
                                 "allowed_mentions": {"parse": []}})
        if code != 200 or not isinstance(rep, dict) or not rep.get("id"):
            _log(f"menu : carte non reposée dans {salon} : HTTP {code} {str(rep)[:120]}")
            return "echec"
        mid = str(rep["id"])
        with _VERROU:
            d = _lire()
            d["cartes"][salon] = {"message": mid, "uid": uid, "gid": gid, "vu_le": time.time()}
            _ecrire(d)
        _retenir_carte(cle, salon, mid)
        # Un code arrivé pendant le déplacement est allé sur l'ancienne carte :
        # la nouvelle est redessinée une fois, à jour.
        _redessiner(cle, conf, _vue_carte(cle, conf))
        if ancien and ancien != mid:
            code, rep = vd.api("DELETE", f"/channels/{salon}/messages/{ancien}")
            if code not in (204, 404):
                _log(f"menu : ancienne carte {ancien} non retirée de {salon} : HTTP {code}")
    _log(f"menu : carte de {uid} ramenée en bas de {salon}")
    return "ramenee"


#: Le message privé de renvoi s'efface tout seul au bout de RENVOI_SEC
#: (propriétaire, 23/10/2026 : « il peut s'effacer auto le message à la fin »).
RENVOI_SEC = 15


def _effacer_apres(p: Dict[str, Any], dormir=None, delai: int = RENVOI_SEC) -> None:
    """Efface la réponse d'origine de ce clic (le jeton vit 15 min) après
    `delai` secondes. Le menu posé dans le salon perso, lui, reste."""
    jeton, app = str(p.get("token") or ""), vd.app_de_reponse(p)
    if not jeton:
        return

    def effacer():
        (dormir or _dormir)(delai)
        code, corps = vd.api("DELETE", f"/webhooks/{app}/{jeton}/messages/@original")
        if code not in (204, 404):
            _log(f"renvoi non effacé : HTTP {code} {str(corps)[:120]}")
    try:
        _fond(effacer)
    except Exception as e:
        _log(f"effacement du renvoi non lancé ({type(e).__name__}: {e})")


def _menu(p: Dict[str, Any], gid: str, uid: str, conf: Dict[str, Any]) -> Dict[str, Any]:
    tickets = _tickets_du_serveur(gid)
    ici = str(p.get("channel_id") or "")
    if ici in tickets:
        # Le bouton « 📱 Numéro » du menu épinglé du ticket (propriétaire,
        # 23/10/2026 : « je veux que ça soit une option dans le menu pin ») :
        # la carte du VA de CE ticket descend en bas — même si c'est son
        # manager qui clique —, sans aucun message de plus.
        vau = tickets[ici]
        try:
            _fond(lambda: ramener_carte(gid, vau, ici))
        except Exception as e:
            _log(f"menu : déplacement non lancé dans {ici} ({type(e).__name__}: {e})")
            return _texte("❌ Impossible pour le moment : réessaie dans un instant.")
        return {"type": 6}
    salon = next((s for s, u in tickets.items() if u == uid), "")
    source = int(((p.get("message") or {}).get("flags")) or 0)
    if not salon:
        # Sans salon perso — le staff (propriétaire, 23/10/2026 : « un menu pour
        # les boss, les managers, pour tout le monde », il lisait « pas de
        # salon » sur Agency), ou un VA pas encore servi. Rien n'est écrit
        # dans le ticket d'un VA.
        cle = f"{gid}:{uid}"
        if source & EPHEMERE:
            if source & V2:
                return _repondre(p, cle, _vue_carte(cle, conf))     # sa carte, sur place
            # Le « 📱 Numéro » du menu privé (tickets_discord.menu_prive, un
            # message classique) : la carte s'ouvre à part, en privé — un
            # message classique ne se change pas en carte V2.
            return _repondre(dict(p, message={"flags": 0}), cle, _vue_carte(cle, conf))
        try:
            import tickets_discord
            rep = tickets_discord.menu_prive(gid, uid)
            if isinstance(rep, dict) and rep.get("type"):
                return rep
        except Exception as e:
            _log(f"menu privé indisponible ({type(e).__name__}: {e}) : la carte à la place")
        return _repondre(p, cle, _vue_carte(cle, conf))
    # Depuis le panneau du salon commun : le MENU du ticket redescend
    # (tickets_discord.ramener_menu, avec son bouton « 📱 Numéro ») ; la carte,
    # elle, descend au clic sur ce bouton. Sans cette fonction (version
    # d'avant), c'est la carte qui descend.
    def descendre():
        try:
            import tickets_discord
            if hasattr(tickets_discord, "ramener_menu"):
                if tickets_discord.ramener_menu(gid, uid, salon) != "echec":
                    return
                _log(f"menu : menu du ticket {salon} non reposé, la carte à la place")
        except Exception as e:
            _log(f"menu : ramener_menu en échec ({type(e).__name__}: {e}), la carte à la place")
        ramener_carte(gid, uid, salon)
    try:
        _fond(descendre)
    except Exception as e:
        _log(f"menu : déplacement non lancé pour {uid} ({type(e).__name__}: {e})")
        return _texte("❌ Impossible pour le moment : réessaie dans un instant.")
    _effacer_apres(p)
    return _texte(f"📋 Ton menu est en bas de <#{salon}>.")


def _vue_carte(cle: str, conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """La carte telle qu'elle doit être : le numéro en cours, ou vide."""
    a = _actif(cle)
    return vue_actif(a, conf) if _vivant(a) or (a and a.get("code") and not a.get("clos")) \
        else vue_panneau(conf)


def _tickets_du_serveur(gid: str) -> Dict[str, str]:
    """{salon perso: VA} des tickets de ce serveur, lus dans data/tickets.json
    (tickets_discord) sans y écrire."""
    import tickets_discord
    t = (safe_json.load(tickets_discord.ETAT_FICHIER, default={}) or {}).get("tickets") or {}
    out: Dict[str, str] = {}
    for k, v in t.items():
        g, _sep, uid = str(k).partition(":")
        if g == str(gid) and uid.isdigit() and isinstance(v, dict) and v.get("salon"):
            out[str(v["salon"])] = uid
    return out


def _carte_dans(salon: str, moi: str) -> str:
    """La carte de ce bot déjà dans le salon (registre perdu), ou « »."""
    code, ms = vd.api("GET", f"/channels/{salon}/messages?limit=50")
    if code != 200 or not isinstance(ms, list):
        return ""
    for m in ms:
        if str((m.get("author") or {}).get("id")) == str(moi) and \
                any(c.startswith(PREFIXE) for c in _ids(m.get("components"))):
            return str(m["id"])
    return ""


def poser_cartes(gid: str, seulement: Optional[str] = None,
                 maintenant: Optional[float] = None) -> Dict[str, Any]:
    """Une carte dans chaque ticket du serveur qui n'en a pas (`seulement` :
    ce salon-là). Rend le bilan {posees, retrouvees, deja, echecs}."""
    conf = SERVEURS[gid]
    now = float(time.time() if maintenant is None else maintenant)
    bilan: Dict[str, Any] = {"posees": [], "retrouvees": [], "deja": 0, "echecs": [],
                             "partis": []}
    with vd.sur_serveur(gid):
        moi = vd.bot_du_serveur(gid)["app_id"]
        for salon, uid in sorted(_tickets_du_serveur(gid).items()):
            if seulement and salon != str(seulement):
                continue
            c = _lire()["cartes"].get(salon)
            if isinstance(c, dict) and c.get("uid") == uid:
                if now - float(c.get("vu_le") or 0) < CARTE_REVOIR_SEC:
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
            cle = f"{gid}:{uid}"
            code, _m = vd.api("GET", f"/guilds/{gid}/members/{uid}")
            if code == 404:
                # Parti du serveur (VA 83 de Threads, 21/10/2026) : son ticket
                # reste, une carte n'y servirait à personne.
                bilan["partis"].append(salon)
                continue
            mid = _carte_dans(salon, moi)
            if mid:
                bilan["retrouvees"].append(salon)
            else:
                code, rep = vd.api("POST", f"/channels/{salon}/messages",
                                   json={"flags": V2, "components": _vue_carte(cle, conf),
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
            # Un numéro déjà en cours (carte privée d'avant) : la suite, son
            # code compris, s'écrit désormais dans la carte du ticket.
            _retenir_carte(cle, salon, mid)
    for quoi in ("posees", "retrouvees"):
        if bilan[quoi]:
            _log(f"cartes {conf['nom']} : {quoi} dans {', '.join(bilan[quoi])}")
    for salon, pourquoi in bilan["echecs"]:
        _log(f"carte du salon {salon} non posée : {pourquoi}")
    for salon in bilan["partis"]:
        if ("parti", salon) not in _CARTES_DITS:
            _CARTES_DITS.add(("parti", salon))
            _log(f"pas de carte dans le salon {salon} : son VA a quitté le serveur")
    return bilan


def vider_cartes_echues(maintenant: Optional[float] = None) -> List[str]:
    """Une carte de ticket redevient vide quand son numéro a fait ses 20 min
    (propriétaire, 21/10/2026 : « après les 20 pour un num tu effaces ») :
    code reçu, il est terminé ; sans code, rendu (l'écoute l'a manqué : bot
    redémarré entre-temps). Rend les clés vidées."""
    now = float(time.time() if maintenant is None else maintenant)
    vides: List[str] = []
    d = _lire()
    for cle, m in list(d["messages"].items()):
        a = d["actifs"].get(cle)
        if not (isinstance(m, dict) and m.get("carte")) or not isinstance(a, dict) or a.get("clos"):
            continue
        age = now - float(a.get("pris_le") or 0)
        # Sans code, l'écoute rend le numéro à 20 min pile : une minute de
        # marge pour ne pas la doubler.
        if age < DUREE_NUMERO_SEC + (0 if a.get("code") else 60):
            continue
        gid, act_id = cle.split(":", 1)[0], str(a.get("id") or "")
        conf = SERVEURS.get(gid)
        if not conf or _maj(cle, act_id, clos="fini" if a.get("code") else "expire") is None:
            continue
        with vd.sur_serveur(gid):
            if a.get("code"):
                _histo(act_id, "fini")
                numgen.finish(act_id, _prov(a))
                _redessiner(cle, conf, vue_panneau(conf))
            else:
                numgen.cancel(act_id, _prov(a))
                _redessiner(cle, conf, vue_close(
                    "⌛ Aucun code en 20 min : numéro rendu, il ne compte pas dans tes %d du jour."
                    % conf["quota"], conf))
        vides.append(cle)
        _log(f"carte de {cle} vidée : numéro {a.get('valeur')} au bout de 20 min")
    return vides


def _boucle_cartes() -> None:
    """Chaque minute, les cartes dont le numéro a fait ses 20 min redeviennent
    vides ; toutes les 10 minutes, les nouveaux tickets reçoivent leur carte
    (sans toucher à tickets_discord : une boucle à part)."""
    time.sleep(90)
    tour = 0
    while True:
        try:
            vider_cartes_echues()
        except Exception as e:
            _log(f"cartes : nettoyage en échec ({type(e).__name__}: {e})")
        if tour % max(1, CARTES_PAS_SEC // 60) == 0:
            for gid in SERVEURS:
                if _cartes_auto(gid):
                    try:
                        poser_cartes(gid)
                    except Exception as e:
                        _log(f"cartes de {gid} : tour en échec ({type(e).__name__}: {e})")
            try:
                import outlook_x_discord        # ses cartes : même rythme, même boucle
                outlook_x_discord.tour_cartes()
            except Exception as e:
                _log(f"cartes Outlook : tour en échec ({type(e).__name__}: {e})")
        tour += 1
        time.sleep(60)


def generaliser_cartes(gid: str) -> str:
    """Toutes les cartes, la boucle des nouveaux tickets, et le panneau du
    salon commun réduit à une ligne qui renvoie au salon perso."""
    with _VERROU:
        d = _lire()
        d.setdefault("cartes_auto", {})[str(gid)] = True
        _ecrire(d)
    b = poser_cartes(gid)
    return (f"cartes : {len(b['posees'])} posée(s), {len(b['retrouvees'])} retrouvée(s), "
            f"{b['deja']} déjà là, {len(b['partis'])} VA parti(s), {len(b['echecs'])} échec(s) ; "
            + poser_panneau(gid))


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
        # Le panneau, ou la ligne de renvoi qui l'a remplacé (sans bouton) :
        # sans elle, le menu aurait été posé EN PLUS de la ligne.
        miens = [m for m in ms if str((m.get("author") or {}).get("id")) == str(moi)
                 and (any(c.startswith(PREFIXE) for c in _ids(m.get("components")))
                      or TEXTE_RENVOI in str(m.get("components")))]
        vue = vue_menu(conf) if _cartes_auto(gid) else vue_panneau(conf)
        corps = {"flags": V2, "components": vue, "allowed_mentions": {"parse": []}}
        if miens:
            code, rep = vd.api("PATCH", f"/channels/{salon}/messages/{miens[0]['id']}",
                               json={"components": corps["components"]})
            return f"panneau remis à neuf : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")
        code, rep = vd.api("POST", f"/channels/{salon}/messages", json=corps)
        return f"panneau posé : HTTP {code}" + ("" if code == 200 else f" {str(rep)[:160]}")


if __name__ == "__main__":
    import sys
    noms = {"twitter": vd.TWITTER_ID, "threads": vd.THREADS_ID, "agency": vd.AGENCY_IG_ID}
    if sys.argv[1:2] == ["poser"] and len(sys.argv) <= 3:
        vd._charger_config()
        quel = (sys.argv[2:] or ["twitter"])[0].lower()
        gid = noms.get(quel, quel)
        print(poser_panneau(gid) if gid in SERVEURS else f"serveur inconnu : {quel}")
    elif sys.argv[1:2] == ["cartes"] and len(sys.argv) == 4:
        # cartes threads <salon> : une seule carte (essai) ; cartes threads tous :
        # toutes, la boucle des nouveaux tickets, et le panneau commun en renvoi.
        vd._charger_config()
        gid = noms.get(sys.argv[2].lower(), sys.argv[2])
        if gid not in SERVEURS:
            print(f"serveur inconnu : {sys.argv[2]}")
        elif sys.argv[3] == "tous":
            print(generaliser_cartes(gid))
        else:
            print(poser_cartes(gid, seulement=sys.argv[3]))
    else:
        print("usage : python numeros_x_discord.py poser [twitter|threads|agency]\n"
              "        python numeros_x_discord.py cartes <twitter|threads|agency> <salon>|tous")
