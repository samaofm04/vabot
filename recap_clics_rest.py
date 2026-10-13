"""Le récap des clics de Va Twitter et de Va Threads, posté par REST.

Propriétaire, 13/10/2026 : « ici tu peux envoyer les récap des subs et les
récap de clicks pour le Threads et aussi pour Twitter », les liens « tout le
lien comme d'hab ». Le récap des clics « comme d'hab », c'est le report que
Yoshi tient à jour chaque heure dans le salon click-us de Youl4b
(cogs/clickrecap.py) : l'espace GetMySocial JESSY LE RETOUR, marché US, tout
l'espace (data/report_click.json du VPS, relu le 13/10/2026). C'est aussi
l'espace que lit le Dashboard clics depuis que le marché français y est coupé
(c1e7c19). Le même message, à l'identique, dans « ─│📊┤-l-clicks » de Va
Twitter et de Va Threads.

LES CHIFFRES NE SONT PAS RECALCULÉS. Un report, c'est plus d'une centaine
d'appels GetMySocial (le détail par lien sur trois périodes, les totaux en
lot) : le refaire pour deux salons de plus aurait triplé la facture pour les
mêmes chiffres, sur un quota déjà juste. _build_group_report dépose ici
l'embed COMPLET qu'il vient de construire (retenir), avant que l'image des
classements ne l'allège ; ce module le repose tel quel. Seul un report PUBLIÉ
est gardé (celui du salon Discord, ou celui construit ici) : la page publique
des clics et l'essai du rig construisent le même report sous un autre nom, et
ne doivent rien changer sur Twitter ni Threads. Si aucun report de cet
espace n'est configuré, ou s'il ne produit plus rien depuis ATTENTE_SOURCE_S,
le module le construit lui-même — une fois par heure au plus, et une seule
fois pour tous les salons qui le reprennent.

POURQUOI REST. Yoshi (discord.py, qui tient le report) n'est pas sur Va
Twitter. Le message part avec le bot du serveur (verif_discord.api, gid
donné) : Luigi sur Twitter, Bowser sur Threads.

UN MESSAGE PAR SALON, ÉDITÉ SUR PLACE, comme le report d'origine (et épinglé
comme lui). Son identifiant est gardé sur disque : un redémarrage le reprend.
Fichier perdu : le message est retrouvé dans le salon (épinglés, puis les
cinquante derniers), à son auteur et à son titre, avant d'en poster un autre
— jamais deux récaps dans le même salon. Une panne passagère de Discord garde
le message et réessaie au passage suivant : reposter laisserait l'ancien
« Updated 14:00 » pour toujours à côté du neuf.

Sans bouton : « Rafraîchir » est un bouton de Yoshi, que le bot du serveur ne
saurait pas traiter.

Les salons se règlent ici (CIBLES_DEFAUT), et se changent sans redéployer
dans data/recap_clics_rest.json : {"cibles": {"<serveur>": {...} | null}}
(null retire un serveur). Aucune commande. Un salon changé reçoit le récap au
relevé suivant ; l'ancien message reste tel quel dans l'ancien salon.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "recap_clics_rest.json"

TWITTER_ID = "1445108485090971710"           # Va Twitter (verif_discord.TWITTER_ID)
THREADS_ID = "1498948161039896586"           # Va Threads (verif_discord.THREADS_ID)
ESPACE_JESSY = "tm_6a0e4739bfa0c238f20a8bf5"  # JESSY LE RETOUR (clics_personnes.ESPACE_RANKING)
SALON_CLICS = "─│📊┤-l-clicks"

#: Le report repris : le MÊME réglage que celui du salon click-us de Youl4b.
#: Même réglage = même signature (voir signature) = le même relevé, pris une
#: fois. Twitter et Threads ont « tout le lien comme d'hab » : les VA de
#: Twitter, au marché US, des deux côtés.
_REPORT_US = {"team_id": ESPACE_JESSY, "group_id": None, "identity": None,
              "group_name": "JESSY LE RETOUR", "marche": "us", "tout": True}
CIBLES_DEFAUT: Dict[str, Dict[str, Any]] = {
    TWITTER_ID: dict(_REPORT_US, salon=SALON_CLICS),
    THREADS_ID: dict(_REPORT_US, salon=SALON_CLICS),
}

#: Un relevé de plus de 75 minutes : la source a sauté son heure.
FRAIS_S = 75 * 60
#: La source configurée mais muette : on l'attend deux heures avant de
#: construire le report ici (elle peut être en pause GetMySocial : la doubler
#: tout de suite referait les mêmes appels pour le même échec).
ATTENTE_SOURCE_S = 2 * 3600
#: Un report construit ici : une fois par heure au plus.
ESSAI_S = 3600

_VERROU = threading.Lock()
_MOI: Dict[str, str] = {}                   # serveur -> identifiant du bot qui y poste


def _fichier_etat() -> Path:
    # relus à chaque appel, pas figés à l'import : les tests déplacent DATA_DIR
    return DATA_DIR / "recap_clics_rest_etat.json"


def _fichier_releves() -> Path:
    return DATA_DIR / "recap_clics_releves.json"


def _fichier_config() -> Path:
    return DATA_DIR / CONFIG_FICHIER.name


def _lire(chemin: Path) -> Dict[str, Any]:
    try:
        d = safe_json.load(chemin, default={}) or {}
    except Exception as e:                                   # noqa: BLE001
        print(f"[recap-clics] {chemin.name} illisible ({type(e).__name__}) : ignoré", flush=True)
        return {}
    return d if isinstance(d, dict) else {}


def _etat() -> Dict[str, Any]:
    return _lire(_fichier_etat())


def _ecrire_etat(d: Dict[str, Any]) -> None:
    safe_json.write(_fichier_etat(), d)


# ─── qui reçoit quoi ────────────────────────────────────────────────────
def cibles() -> Dict[str, Dict[str, Any]]:
    """{serveur: réglage} : CIBLES_DEFAUT, corrigé par data/recap_clics_rest.json.

    Une entrée mal écrite est écartée ET dite : un salon qui ne reçoit plus
    rien sans un mot, c'est ce que ce dépôt a déjà payé trop souvent."""
    out = {g: dict(c) for g, c in CIBLES_DEFAUT.items()}
    surcharge = _lire(_fichier_config()).get("cibles")
    if surcharge is None:
        return out
    if not isinstance(surcharge, dict):
        print("[recap-clics] recap_clics_rest.json : « cibles » n'est pas un objet, ignoré",
              flush=True)
        return out
    for g, c in surcharge.items():
        g = str(g)
        if c is None:
            out.pop(g, None)
        elif isinstance(c, dict) and (c.get("salon") or (out.get(g) or {}).get("salon")):
            out[g] = {**(out.get(g) or {}), **c}
        else:
            print(f"[recap-clics] recap_clics_rest.json : réglage de {g} illisible, ignoré : "
                  f"{str(c)[:120]}", flush=True)
    return out


def _marche(c: Dict[str, Any]) -> str:
    """La clé du marché, lue comme le report la lit (clickrecap._marche_de) :
    deux lectures, et un « US » d'un côté serait « tout » de l'autre."""
    try:
        from cogs.clickrecap import _marche_de
        return str(_marche_de(c)[0])
    except Exception:                                        # noqa: BLE001
        m = str((c or {}).get("marche") or "tout").lower()
        return m if m in ("fr", "us", "tout") else "tout"


def signature(c: Optional[Dict[str, Any]]) -> str:
    """Ce qui fait qu'un report est le même qu'un autre : l'espace, le groupe,
    l'identité, « tout l'espace », le marché, le contenu. Le nom affiché et le
    salon n'y sont pas : deux salons qui veulent la même chose partagent le
    même relevé."""
    c = c or {}
    return "|".join([str(c.get("team_id") or ""), str(c.get("group_id") or ""),
                     str(c.get("identity") or ""), "1" if c.get("tout") else "0",
                     _marche(c), str(c.get("contenu") or "tout").strip().lower()])


# ─── le relevé, déposé par le report ────────────────────────────────────
def _poste_ici() -> bool:
    """La machine qui poste sur Discord (VA_MACHINE_PROD, posée dans le seul
    .env du VPS) : elle seule garde des relevés. Les suites de tests
    construisent de vrais reports avec de faux chiffres ; gardés dans un data/
    lu par la boucle, ils seraient partis tels quels sur Twitter et Threads."""
    import os
    return os.environ.get("VA_MACHINE_PROD") == "1"


#: La « source » d'un report construit ici (_construire), à la place de la clé
#: « serveur:salon » d'un report Discord publié.
ICI = "recap_clics_rest"
_DITS: set = set()                          # les refus déjà dits (une fois chacun)


def retenir(c: Dict[str, Any], embed: Dict[str, Any], source: str = "") -> bool:
    """Garde l'embed d'un report que Twitter ou Threads reprend. Appelé par
    _build_group_report, report complet seulement (pas un « No data »).
    Rien pour les autres reports : ce fichier n'est pas un cache de plus.

    `source` : la clé du report PUBLIÉ qui l'a construit (clickrecap
    ._REPORT_PUBLIE), ou ICI. Vide -- la page publique des clics, l'essai du
    rig, /reportclick -- : rien n'est gardé. Ces constructions ont la même
    signature sous un autre nom ; gardées, elles renommaient le récap des deux
    serveurs à chaque vue (vu en relecture le 13/10/2026). Parmi les reports
    publiés, seul celui que _releve attend fait foi (_source_configuree) : deux
    reports du même espace sous deux noms feraient alterner le titre."""
    if not _poste_ici() or not source:
        return False
    sig = signature(c)
    if sig not in {signature(x) for x in cibles().values()}:
        return False
    if source != ICI:
        attendue = _source_configuree(sig)
        if source != attendue:
            if (source, attendue) not in _DITS:
                _DITS.add((source, attendue))
                print(f"[recap-clics] report {source} non repris pour Twitter/Threads : "
                      f"le même espace est déjà publié par {attendue or '?'}, "
                      "qui seul fait foi", flush=True)
            return False
    rel = _lire(_fichier_releves())
    rel[sig] = {"t": time.time(), "embed": json.loads(json.dumps(embed, ensure_ascii=False))}
    safe_json.write(_fichier_releves(), rel)
    return True


def _source_configuree(sig: str) -> str:
    """La clé (« serveur:salon ») d'un report Discord configuré qui produit ce
    relevé, ou ""."""
    try:
        from cogs.clickrecap import _load_report_cfg, _reports_configures
        for cle, c in _reports_configures(_load_report_cfg()):
            if signature(c) == sig:
                return str(cle)
    except Exception as e:                                   # noqa: BLE001
        print(f"[recap-clics] reports configurés illisibles ({type(e).__name__}: {e})",
              flush=True)
    return ""


def _construire(cib: Dict[str, Any]) -> bool:
    """Le report construit ici, par la MÊME fonction que Discord et le site
    (deux calculs finiraient par diverger). Elle le dépose elle-même (retenir).
    `permettre_vide=False` : GetMySocial muet ne fait jamais un « No data »
    qui remplacerait de bons chiffres."""
    from cogs.clickrecap import ClickRecap, _REPORT_PUBLIE

    class _Faux:
        """_build_group_report n'appelle aucun self.* (web_upload fait pareil)."""

    c = {k: cib.get(k) for k in ("team_id", "group_id", "identity", "group_name",
                                 "marche", "tout", "contenu") if k in cib}
    # asyncio.run copie le contexte : le report construit ici se sait repris
    # (retenir), et le marqueur ne survit pas à l'appel
    jeton = _REPORT_PUBLIE.set(ICI)
    try:
        emb = asyncio.run(ClickRecap._build_group_report(_Faux(), c, permettre_vide=False))
    finally:
        _REPORT_PUBLIE.reset(jeton)
    return emb is not None


def _releve(sig: str, cib: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Le dernier relevé de ce report, construit ici s'il le faut (voir l'en-tête)."""
    r = _lire(_fichier_releves()).get(sig)
    r = r if isinstance(r, dict) and isinstance(r.get("embed"), dict) else None
    t = time.time()
    etat = _etat()
    attente = etat.setdefault("_attente", {})
    if r and 0 <= t - float(r.get("t") or 0) < FRAIS_S:
        if attente.pop(sig, None) is not None:
            _ecrire_etat(etat)
        return r
    source = _source_configuree(sig)
    if source:
        if sig not in attente:
            attente[sig] = t
            _ecrire_etat(etat)
            print(f"[recap-clics] aucun relevé récent de {sig} : on attend le report {source} "
                  f"(construit ici s'il reste muet {ATTENTE_SOURCE_S // 3600} h)", flush=True)
        if 0 <= t - float(attente[sig]) < ATTENTE_SOURCE_S:
            return r
    essais = etat.setdefault("_essai", {})
    if 0 <= t - float(essais.get(sig) or 0) < ESSAI_S:
        return r
    essais[sig] = t
    _ecrire_etat(etat)
    print(f"[recap-clics] report {sig} construit ici ("
          + (f"le report {source} ne produit plus rien" if source
             else "aucun report de cet espace n'est configuré") + ")", flush=True)
    try:
        ok = _construire(cib)
    except Exception as e:                                   # noqa: BLE001
        print(f"[recap-clics] report {sig} : {type(e).__name__}: {e}", flush=True)
        ok = False
    if not ok:
        print(f"[recap-clics] report {sig} : GetMySocial n'a rien rendu, le dernier message "
              "reste tel quel", flush=True)
    r2 = _lire(_fichier_releves()).get(sig)
    return r2 if isinstance(r2, dict) and isinstance(r2.get("embed"), dict) else r


# ─── Discord ────────────────────────────────────────────────────────────
def _api(methode: str, chemin: str, gid: str, **kw) -> Tuple[int, Any]:
    """Le bot DE CE SERVEUR, toujours (gid donné à verif_discord.api), quel
    que soit le fil qui appelle."""
    from verif_discord import api
    return api(methode, chemin, gid=gid, **kw)


def _passager(code: Any, rep: Any = None) -> bool:
    # la même règle que le podium : un seul avis sur ce qui repassera
    from podium_discord import _passager as p
    return p(code, rep)


def _nom_nu(nom: Any) -> str:
    from podium_discord import _nom_nu as n
    return n(nom)


def _salon(gid: str, voulu: str) -> str:
    """Le salon voulu : exact, puis au nom nu (le propriétaire redécore ses
    salons), puis LE salon texte en « clicks ». Plusieurs : aucun, et dit."""
    code, rep = _api("GET", f"/guilds/{gid}/channels", gid)
    if code != 200 or not isinstance(rep, list):
        print(f"[recap-clics] {gid} : liste des salons illisible (HTTP {code})", flush=True)
        return ""
    # texte (0) ou annonces (5) : une catégorie au même nom n'est pas un salon
    textes = [x for x in rep if isinstance(x, dict) and x.get("type", 0) in (0, 5)]
    for x in textes:
        if x.get("name") == voulu:
            return str(x["id"])
    cible = _nom_nu(voulu)
    trouves = [x for x in textes if _nom_nu(x.get("name")) == cible]
    pourquoi = "même nom nu"
    if not trouves:
        trouves = [x for x in textes if re.search(r"(?:^|-)clicks$", _nom_nu(x.get("name")))]
        pourquoi = "seul salon en « clicks »"
    if len(trouves) == 1:
        print(f"[recap-clics] {gid} : salon « {voulu} » retrouvé sous le nom "
              f"« {trouves[0].get('name')} » ({pourquoi})", flush=True)
        return str(trouves[0]["id"])
    if trouves:
        print(f"[recap-clics] {gid} : {len(trouves)} salons possibles pour « {voulu} » ("
              + ", ".join(str(x.get("name")) for x in trouves)
              + ") — aucun choisi, il faut en renommer un", flush=True)
    else:
        print(f"[recap-clics] {gid} : salon « {voulu} » introuvable", flush=True)
    return ""


def _moi(gid: str) -> str:
    """L'identifiant du bot qui poste sur ce serveur (pour reconnaître SES messages)."""
    if gid not in _MOI:
        code, rep = _api("GET", "/users/@me", gid)
        if code != 200 or not isinstance(rep, dict) or not rep.get("id"):
            return ""
        _MOI[gid] = str(rep["id"])
    return _MOI[gid]


def _retrouver(gid: str, salon: str, titre: str) -> str:
    """Le récap déjà posté par ce bot dans ce salon (état perdu), ou "".

    Au titre exact d'abord ; à défaut, au même genre de titre (« 🇺🇸 Clicks — »,
    le nom du groupe changé) : le report d'origine renommé entre deux passages,
    l'état perdu au même moment, et un second récap partait à côté du premier."""
    moi = _moi(gid)
    if not moi or not titre:
        return ""
    genre = titre.split(" — ")[0] + " — " if " — " in titre else ""
    proche = ""
    for chemin in (f"/channels/{salon}/pins", f"/channels/{salon}/messages?limit=50"):
        code, rep = _api("GET", chemin, gid)
        if code != 200 or not isinstance(rep, list):
            continue
        for m in rep:
            if not isinstance(m, dict) or str((m.get("author") or {}).get("id") or "") != moi:
                continue
            embeds = m.get("embeds") or []
            t = str((embeds[0] or {}).get("title") or "") if embeds else ""
            if t == titre:
                print(f"[recap-clics] {gid} : récap retrouvé dans le salon ({m.get('id')}), "
                      "repris plutôt que reposté", flush=True)
                return str(m.get("id") or "")
            if genre and not proche and t.startswith(genre):
                proche = str(m.get("id") or "")
    if proche:
        print(f"[recap-clics] {gid} : récap retrouvé dans le salon ({proche}) sous un autre "
              f"nom de groupe, repris plutôt que reposté", flush=True)
    return proche


def _contenu() -> str:
    """La ligne au-dessus de l'embed, celle du report d'origine : la même
    heure pleine (le relevé suivant), décomptée par Discord."""
    try:
        from cogs.clickrecap import _next_heure_unix
        ts = int(_next_heure_unix())
    except Exception:                                        # noqa: BLE001
        ts = (int(time.time()) // 3600 + 1) * 3600
    return f"⏱️ **Prochaine mise à jour** <t:{ts}:R> (à <t:{ts}:t>)"


def _patch(gid: str, salon: str, mid: str, corps: Dict[str, Any]) -> Tuple[int, Any]:
    return _api("PATCH", f"/channels/{salon}/messages/{mid}", gid, json=corps)


# ─── la publication ─────────────────────────────────────────────────────
def publier(gid: str) -> str:
    """Pose ou met à jour le récap des clics de ce serveur. Rend l'identifiant
    du message ("" si rien n'a pu partir, ou si ce serveur n'en a pas).

    Un seul passage à la fois (la boucle du podium et la fin du report horaire
    l'appellent toutes deux) : deux passages sur un salon sans message en
    auraient posté deux."""
    gid = str(gid)
    cib = cibles().get(gid)
    if not cib:
        return ""
    if not _VERROU.acquire(blocking=False):
        print(f"[recap-clics] {gid} : un passage tourne déjà, repris au prochain tour", flush=True)
        return ""
    try:
        return _publier(gid, cib)
    finally:
        _VERROU.release()


def publier_tous() -> Dict[str, str]:
    """Chaque serveur qui a un récap des clics, chacun avec son bot."""
    import verif_discord as vd
    out = {}
    for gid in cibles():
        try:
            with vd.sur_serveur(gid):
                out[gid] = publier(gid)
        except Exception as e:                               # noqa: BLE001
            print(f"[recap-clics] {gid} : {type(e).__name__}: {e}", flush=True)
            out[gid] = ""
    return out


def _retirer_avis(gid: str, salon: str, mid: str) -> bool:
    """Retire l'avis « … a épinglé un message » laissé par l'épinglage du récap.

    Le propriétaire ne veut pas de ces avis (même règle que les menus et les
    tickets) : le 13/10/2026, le premier récap de Va Twitter en avait laissé
    un juste au-dessus de lui. Seulement les avis (type 6) qui pointent CE
    message ; rien d'autre n'est touché. Rend True si plus aucun ne reste."""
    code, rep = _api("GET", f"/channels/{salon}/messages", gid, params={"limit": "15"})
    if code != 200 or not isinstance(rep, list):
        return False
    ok = True
    for m in rep:
        ref = str(((m.get("message_reference") or {}).get("message_id")) or "")
        if m.get("type") == 6 and ref == str(mid):
            c, _r = _api("DELETE", f"/channels/{salon}/messages/{m.get('id')}", gid)
            if c in (200, 204):
                print(f"[recap-clics] {gid} : avis d'épinglage retiré ({m.get('id')})", flush=True)
            else:
                ok = False
                print(f"[recap-clics] {gid} : avis d'épinglage {m.get('id')} non retiré "
                      f"(HTTP {c})", flush=True)
    return ok


def _publier(gid: str, cib: Dict[str, Any]) -> str:
    sig = signature(cib)
    rel = _releve(sig, cib)
    if not rel:
        return ""
    etat = _etat()
    e = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
    salon, mid = str(e.get("salon") or ""), str(e.get("message") or "")
    if mid and float(e.get("t_releve") or 0) >= float(rel.get("t") or 0):
        return mid                     # rien de neuf depuis le dernier passage
    embed = rel["embed"]
    corps = {"content": _contenu(), "embeds": [embed], "allowed_mentions": {"parse": []}}
    voulu = str(cib.get("salon") or SALON_CLICS)
    # le nom réglé que l'on note avec le message : celui d'avant tant que le
    # nouveau salon n'est pas trouvé, pour le chercher encore au relevé suivant
    nom_note = voulu

    def noter(s: str, m: str, fait: bool, avis: Optional[bool] = None) -> str:
        et = _etat()
        avant = et.get(gid) if isinstance(et.get(gid), dict) else {}
        et[gid] = {"salon": s, "nom": nom_note, "message": m,
                   # pas « fait » (Discord en panne) : le même relevé repartira
                   "t_releve": float(rel.get("t") or 0) if fait else float(e.get("t_releve") or 0),
                   "vu": time.time(),
                   # l'avis « a épinglé » de CE message est retiré (une fois)
                   "avis_retire": (bool(avis) if avis is not None
                                   else bool(avant.get("avis_retire")) and avant.get("message") == m)}
        _ecrire_etat(et)
        return m

    # LE SALON RÉGLÉ A CHANGÉ (data/recap_clics_rest.json) depuis le dernier
    # envoi. Sans cette vérification, le message gardé était édité sur place
    # pour toujours : le nouveau salon ne recevait jamais rien (vu en relecture
    # le 13/10/2026). Une fois par relevé neuf, seulement quand le nom diffère.
    salon_voulu = ""
    if salon and mid and str(e.get("nom") or "") != voulu:
        salon_voulu = _salon(gid, voulu)
        if not salon_voulu:
            nom_note = str(e.get("nom") or "")
            print(f"[recap-clics] {gid} : salon réglé « {voulu} » introuvable, le récap reste "
                  f"dans l'ancien salon ({salon})", flush=True)
        elif salon_voulu != salon:
            print(f"[recap-clics] {gid} : le salon réglé est maintenant « {voulu} » "
                  f"({salon_voulu}) : le récap y part ; l'ancien message {mid} reste tel quel "
                  f"dans {salon}", flush=True)
            salon, mid = "", ""

    if salon and mid:
        code, rep = _patch(gid, salon, mid, corps)
        if code == 200:
            # un récap posté avant ce correctif garde son avis : retiré une fois
            if not e.get("avis_retire"):
                # un seul essai, réussi ou non (dit au journal) : pas un appel
                # de plus à chaque relevé si Discord refuse
                _retirer_avis(gid, salon, mid)
                return noter(salon, mid, True, True)
            return noter(salon, mid, True)
        if _passager(code, rep):
            print(f"[recap-clics] {gid} : Discord indisponible (HTTP {code}), message gardé, "
                  "nouvel essai au prochain passage", flush=True)
            return mid
        # supprimé à la main, salon refait, message d'un autre bot : on repart
        # du salon, en cherchant d'abord si le récap n'y est pas déjà
        print(f"[recap-clics] {gid} : message {mid} inéditable (HTTP {code}), recherche "
              "dans le salon", flush=True)
    salon2 = salon_voulu or _salon(gid, voulu)
    if not salon2:
        return ""
    mid2 = _retrouver(gid, salon2, str(embed.get("title") or ""))
    if mid2:
        code, rep = _patch(gid, salon2, mid2, corps)
        if code == 200:
            # retrouvé (état perdu ou salon changé) : son avis aussi, une fois
            _retirer_avis(gid, salon2, mid2)
            return noter(salon2, mid2, True, True)
        if _passager(code, rep):
            noter(salon2, mid2, False)
            return mid2
        print(f"[recap-clics] {gid} : récap retrouvé {mid2} inéditable (HTTP {code}), reposté",
              flush=True)
    code, rep = _api("POST", f"/channels/{salon2}/messages", gid, json=corps)
    if code != 200 or not isinstance(rep, dict) or not rep.get("id"):
        print(f"[recap-clics] {gid} : envoi refusé (HTTP {code}) {str(rep)[:160]}", flush=True)
        return ""
    neuf = str(rep["id"])
    noter(salon2, neuf, True)
    # épinglé comme le report d'origine ; un refus (droit « Gérer les
    # messages » absent) ne retire rien au récap, il est dit
    c_pin, r_pin = _api("PUT", f"/channels/{salon2}/pins/{neuf}", gid)
    if c_pin not in (200, 204):
        print(f"[recap-clics] {gid} : récap non épinglé (HTTP {c_pin}) {str(r_pin)[:120]}",
              flush=True)
    else:
        time.sleep(1)                  # l'avis met un instant à apparaître
        _retirer_avis(gid, salon2, neuf)
    noter(salon2, neuf, True, True)
    print(f"[recap-clics] {gid} : récap des clics posté ({neuf}) dans {salon2}", flush=True)
    return neuf
