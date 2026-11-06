"""La page GetMySocial d'un VA de TRUST TWITTER, qu'il modifie lui-même.

Propriétaire, 06/11/2026 : « je veux avoir 2 liens pour les VA, un direct et
un landing page qu'ils peuvent modifier ». Ses réponses : le VA change sa
photo de profil et l'image de fond (il dépose des images : « le fond aussi
c'est une image », « les deux quoi »), son nom et sa bio, le texte du bouton.
Même tracking que son lien direct (« c'est le même tracking pour les VA, y a
rien qui change »), pays hors cibles vers la model, safe page — mais PAS de
70/30 (« ça doit pas être 70 30 ») : tout le bouton sur le tracking. Base :
liaseeo. Essai d'abord sur le propriétaire seul (PILOTE), dans son ticket.

Le lien direct ne change pas : la page est un SECOND lien GetMySocial, copie
du gabarit de page de l'équipe (GABARIT_PAGE), son bouton OnlyFans sur le
tracking du VA (liens_va._poser_tracking), ses pays sur le bouton
(liens_va.poser_pays), la safe page posée, sans A/B. Rangée dans
le groupe de son manager. Le registre vit à part (data/pages_va.json) : la
fiche de liens_va ne porte qu'un lien, et tout ce qui la relit (pays, bases,
podium, menus) continue de ne voir que le direct.

Ce que les essais du 06/11 (pages jetables, coupées ensuite) ont montré :
  - nom, bio, texte du bouton : update_link (lecture-écriture, le tableau
    des boutons renvoyé ENTIER, le tracking et les pays du bouton gardés) ;
  - la photo : update_link n'accepte qu'une adresse images.getmysocial.com.
    L'image passe par une page temporaire créée en multipart (profilePicture),
    dont on reprend l'adresse, puis la page temporaire est supprimée — l'image
    reste servie (HTTP 200 après suppression) ;
  - le fond : l'image de fond du gabarit ne s'efface pas (« » et null gardent
    l'ancienne). La couleur choisie devient donc une image unie, envoyée
    comme la photo (backgroundImage), avec custom_background_color ;
  - le texte de la page (nom, bio) prend custom_text_color, choisi clair ou
    foncé selon le fond ; le balisage {{color:…}} du gabarit est retiré au
    premier changement de couleur, sinon une bio blanche disparaît sur un
    fond clair.

Ce que le VA tape est nettoyé (nettoyer) : ni accolades (le balisage
{{color}} et les jetons {city} de GetMySocial), ni caractères de contrôle,
longueurs bornées. Il ne touche jamais au nom de tableau de bord ni à
l'adresse (display_name, shortcode).

TRUST INSTAGRAM (propriétaire, 06/11/2026) : chaque VA qui a un lien en
service a 3 pages FIXES, une par place, chacune copiée de SON gabarit
(GABARITS_PLACE : liabrune, liablonde, liatemplate, équipe EMY IG), créées
d'office par la reprise (creer_pages_manquantes, en fond), jamais modifiables
depuis Discord. Il peut en demander d'autres (« ➕ Demander une page »), sans
maximum : un manager accepte ou refuse (registre « demandes »), la page
acceptée copie GABARIT_PAGE et se modifie comme celle de Twitter. Toutes ont
le 70/30 « Lia seule » (AB_PAGES) ; Twitter reste sans A/B.
"""
from __future__ import annotations

import io
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

TWITTER_ID = "1445108485090971710"
AGENCY_IG_ID = "1488331963575177247"
#: Qui a ses pages, par serveur : des membres, ou « * » pour tous. Pilote le
#: 06/11 sur le propriétaire ; le même jour : « envoie le truc pour les liens
#: page aussi à tout le monde pour les VA Twitter » — chaque VA qui a un lien
#: la crée quand il veut (« 📄 Créer »). TRUST INSTAGRAM : « met leur genre 3
#: pages de dispo » — ouvert à tous ses VA : sans ça, liens_va.synchroniser
#: ne lance pas la reprise, donc ni création des pages fixes ni 70/30.
PILOTE: Dict[str, set] = {TWITTER_ID: {"*"}, AGENCY_IG_ID: {"*"}}
#: Combien de pages par VA là où il n'y a pas de places fixes (« pour Twitter
#: 1 page directe et une safe » : le lien direct + 1 page, que le VA crée).
PAGES_MAX: Dict[str, int] = {TWITTER_ID: 1}
#: Les places FIXES par serveur : créées d'office pour chaque VA dont le lien
#: sert, jamais modifiables depuis Discord (ni par le VA ni par personne). Au
#: delà, des pages à la demande, sans maximum, une fois acceptées par un
#: manager — modifiables, elles. Ce dictionnaire décide seul où il y a des
#: places fixes et des demandes : Twitter n'y est pas (sa page 1 reste à lui).
FIXES: Dict[str, int] = {AGENCY_IG_ID: 3}
#: Le gabarit de page de l'équipe du serveur (GetMySocial refuse de copier un
#: lien d'une autre équipe) : « Gabarit Twitter (page de base) ».
#: Propriétaire, 06/11 : « tu prends le lien qui s'appelle liaseeo ». liaseeo
#: vit dans l'espace perso : sa copie dans EMY TWITTER, « Template landing
#: Twitter (liaseeo) » (le canard, « Lia ♡ », « MY FREE 0F 🔗 »). D'abord
#: « juste le lien OF, pas de Telegram » ; le même jour vers 13 h : « que les
#: landing pages [aient] Telegram ; quand c'est direct, y a pas de Telegram »
#: — « MY TELEGRAM » ajouté en dernier bouton sur ce gabarit (à la main, dans
#: GetMySocial). Le code ne touche que les boutons OnlyFans (_RE_OF) : le
#: Telegram reste quand le VA modifie sa page ou que la reprise re-pointe.
#: TRUST INSTAGRAM : liatemplate (EMY IG), le gabarit des pages demandées
#: (place 4 et suivantes) ; les places fixes ont le leur (GABARITS_PLACE).
#: Une chaîne par serveur : tout ce qui copie ou teste un gabarit la lit telle
#: quelle (gabarit() choisit entre les deux).
GABARIT_PAGE: Dict[str, str] = {TWITTER_ID: "lnk_6aed1548c7881b6c805e773a",
                                AGENCY_IG_ID: "lnk_6aedd88dc7881b6c8066a2c0"}
#: Un gabarit par place fixe (propriétaire, 06/11), tous dans l'équipe EMY IG
#: du serveur. Leur 2e bouton (Telegram) n'est jamais touché : seuls les
#: boutons OnlyFans (liens_va._RE_OF) reçoivent le tracking ou un texte.
GABARITS_PLACE: Dict[str, Dict[int, str]] = {
    AGENCY_IG_ID: {1: "lnk_6aedd88bc7881b6c8066a247",      # liabrune
                   2: "lnk_6aedd88cc7881b6c8066a28c",      # liablonde
                   3: "lnk_6aedd88dc7881b6c8066a2c0"},     # liatemplate
}
#: Les serveurs dont les pages portent le 70/30 « Lia seule » (70 % sur le
#: tracking du VA, 30 % « Base Lia » directe), comme leurs liens directs — si
#: liens_va.lia_seule(gid) le veut encore. Twitter n'y est pas : « ça doit pas
#: être 70 30 » (06/11). Une page se coupe par disable_link, jamais en
#: éteignant son A/B : éteindre efface les variantes chez GetMySocial (21/10).
AB_PAGES = {AGENCY_IG_ID}

FICHIER = Path(__file__).resolve().parent / "data" / "pages_va.json"
MAX_NOM, MAX_BIO, MAX_BOUTON = 40, 160, 40
PHOTO_MAX = 8 * 1024 * 1024
COTE_PHOTO = 800
FOND_TAILLE = (1080, 1920)
#: Les fonds proposés (une liste : Discord n'a pas de nuancier ; 25 au plus).
COULEURS: Tuple[Tuple[str, str], ...] = (
    ("Noir", "#000000"), ("Gris anthracite", "#1F2937"), ("Blanc", "#FFFFFF"),
    ("Rose poudré", "#F9A8D4"), ("Rose vif", "#EC4899"), ("Rouge", "#DC2626"),
    ("Bordeaux", "#7F1D1D"), ("Violet", "#8B5CF6"), ("Lavande", "#C4B5FD"),
    ("Bleu nuit", "#1E3A8A"), ("Bleu", "#3B82F6"), ("Bleu ciel", "#7DD3FC"),
    ("Vert", "#22C55E"), ("Menthe", "#A7F3D0"), ("Jaune", "#FACC15"),
    ("Orange", "#F97316"), ("Pêche", "#FDBA74"), ("Beige", "#F5E6D3"),
    ("Marron", "#7C4A2D"),
)
_VERROU = threading.RLock()
#: Les pages en cours de création (gid:uid) : un double clic en faisait deux.
_CREATIONS: set = set()
#: Un verrou par page autour des lectures-écritures GetMySocial : une
#: modification du VA et la reprise (tracking re-pointé) ne s'écrasent pas.
_VERROUS: Dict[str, threading.RLock] = {}
#: La pixellisation max d'une photo déposée : un PNG de 12 000 × 12 000 pèse
#: 140 Ko et en prend plus d'un Go une fois décodé.
PIXELS_MAX = 40_000_000


def _verrou_page(cle: str) -> threading.RLock:
    with _VERROU:
        return _VERROUS.setdefault(str(cle), threading.RLock())


def _log(texte: str) -> None:
    print(f"[page] {texte}", flush=True)


def gabarit(gid: Any, n: int = 1) -> str:
    """Le lien que copie la page n de ce serveur : celui de sa place fixe
    (GABARITS_PLACE), sinon le gabarit du serveur (GABARIT_PAGE). « » : pas
    de page ici. Seul endroit qui le décide."""
    gid = str(gid or "")
    return str((GABARITS_PLACE.get(gid) or {}).get(int(n or 1)) or GABARIT_PAGE.get(gid) or "")


def ouverte(gid: Any, uid: Any) -> bool:
    membres = PILOTE.get(str(gid or ""), set())
    return bool(gabarit(gid, 1)) and ("*" in membres or str(uid).split("#")[0] in membres)


def a_des_pages(gid: Any) -> bool:
    """Ce serveur a des pages notées : leur reprise tourne même si on le
    referme (PILOTE ou GABARIT_PAGE retirés) — sinon une page vivante ne
    suivrait plus ni coupure ni changement de tracking."""
    g = f"{gid}:"
    return any(str(c).startswith(g) for c in (_lire().get("pages") or {}))


#: La bascule des pages part en fond, dans l'ordre (une file, un fil) : le
#: clic « 🚫 Désactiver » d'un manager attendait une réponse de GetMySocial
#: par page, au risque des 3 s de Discord. Un redémarrage au milieu : la
#: reprise (30 min) remet les pages sur leur direct.
_FILE: "queue.Queue" = None  # type: ignore[assignment]


def _travailleur() -> None:
    while True:
        f = _FILE.get()
        try:
            f()
        except Exception as e:                               # noqa: BLE001
            _log(f"tâche de fond : {type(e).__name__}: {e}")
        finally:
            _FILE.task_done()


def _en_fond(f) -> None:
    global _FILE
    import queue
    with _VERROU:
        if _FILE is None:
            _FILE = queue.Queue()
            threading.Thread(target=_travailleur, name="pages_va", daemon=True).start()
    _FILE.put(f)


EN_FOND = _en_fond


def place(uid: Any, n: int = 1) -> str:
    """La clé de registre de la n-ième page d'un VA : « uid » pour la 1re,
    « uid#n » ensuite (une clé par page : chacune se crée, se modifie, se
    coupe à part)."""
    return str(uid) if int(n or 1) <= 1 else f"{uid}#{int(n)}"


def numero_de_place(uid_place: Any) -> int:
    """L'inverse de place() : « uid » → 1, « uid#7 » → 7."""
    _u, _s, n = str(uid_place).partition("#")
    return int(n) if n.isdigit() else 1


def fixes(gid: Any) -> int:
    """Le nombre de places fixes de ce serveur (0 : pas de places fixes, pas
    de demandes — Twitter)."""
    return int(FIXES.get(str(gid or ""), 0))


def sur_demande(gid: Any) -> bool:
    """Ce serveur a des places fixes créées d'office et des pages à la
    demande (acceptées par un manager)."""
    return fixes(gid) > 0


def modifiable(gid: Any, n: int = 1) -> bool:
    """Une place fixe ne se modifie pas depuis Discord ; les autres oui."""
    return int(n or 1) > fixes(gid)


def places(gid: Any, uid: Any, d: Optional[Dict[str, Any]] = None) -> List[int]:
    """Les places auxquelles ce VA a droit : 1..PAGES_MAX sans places fixes
    (Twitter) ; sinon les fixes puis chaque page acceptée par un manager.
    `d` : le registre déjà lu (un tour sur tous les VA ne le relit pas)."""
    gid = str(gid or "")
    f = fixes(gid)
    if not f:
        return list(range(1, int(PAGES_MAX.get(gid, 1)) + 1))
    return list(range(1, f + 1)) + places_acceptees(gid, uid, d)


def pages_max(gid: Any, uid: Any = None) -> int:
    """La plus haute place de ce VA (de ce serveur sans `uid`) : PAGES_MAX
    sans places fixes ; sinon les fixes, plus les pages acceptées du VA."""
    if uid is None or not sur_demande(gid):
        return fixes(gid) or int(PAGES_MAX.get(str(gid or ""), 1))
    return max(places(gid, uid))


def _vrai_uid(uid: Any) -> str:
    return str(uid).split("#", 1)[0]


def fiche_complete(fiche: Any) -> bool:
    """Le numéro et le pseudo du VA dans sa fiche liens_va : sans eux, la
    page s'appellerait « Twitter VA None @None page » et le registre des
    trackings y verrait une 2e personne sur son tracking (« en doute », sans
    relevé). Lu par en_service ET creer_page : une seule règle."""
    f = fiche if isinstance(fiche, dict) else {}
    return str(f.get("numero") or "").isdigit() and bool(str(f.get("pseudo") or "").strip())


def depart_du_va(gid: Any, ticket: Any, disparu: Any) -> str:
    """Pourquoi ce VA compte pour parti (« » s'il ne l'est pas). LA règle du
    départ, lue par en_service (création, menu, ➕, ✅) et par la reprise
    (raison_depart), qui coupe ses pages :
      - un ticket vivant (dans « tickets ») fait foi : parti s'il porte
        « parti » ;
      - sans ticket vivant, sur un serveur à places fixes : parti si sa fiche
        rangée dans « tickets_disparus » porte « parti » (le VA 110, parti le
        28/10, fiche liens_va jamais coupée, a reçu ses pages au premier
        passage du 06/11), ou s'il n'a de ticket NULLE PART.
    Un ticket rangé dans « tickets_disparus » SANS « parti » (salon supprimé
    à la main, entretenir_accueils) ne dit pas que le VA est parti : la 1re
    version de la règle le jugeait parti, et la reprise coupait les pages
    vivantes d'un VA en service en conseillant au journal de couper son
    direct (4 VA de TRUST TWITTER sont dans ce cas en prod le 06/11, direct
    actif). `ticket`, `disparu` : les fiches de ce VA ({} ou None : aucune)."""
    t = ticket if isinstance(ticket, dict) else {}
    if t:
        return "ticket marqué parti" if t.get("parti") else ""
    if not sur_demande(gid):
        return ""                       # Twitter : seul le direct décide
    x = disparu if isinstance(disparu, dict) else {}
    if x:
        return "ticket rangé dans tickets_disparus (parti)" if x.get("parti") else ""
    return "aucun ticket sur ce serveur"


def en_service(gid: Any, uid: Any, fiche: Optional[Dict[str, Any]] = None,
               ticket: Optional[Dict[str, Any]] = None,
               disparu: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Ce VA peut-il avoir des pages créées sur un serveur à places fixes ?
    (vrai, « ») ou (faux, « sans_lien » | « coupe » | « parti » |
    « fiche_incomplete »). Sa fiche liens_va doit avoir link_id, tracking et
    public_url, le lien en service, son numéro et son pseudo (fiche_complete),
    et le VA ne pas être parti (depart_du_va). Seul endroit qui le décide : le
    menu, ➕, ✅, la création automatique et creer_page en avaient chacun leur
    version — un VA sans tracking pouvait demander, être accepté, puis rester
    « ⏳ en préparation » à vie (la reprise l'écartait) ; un VA sans pseudo
    était annoncé « ⏳ », accepté, puis refusé par creer_page à chaque passage
    (3 essais comptés par place, le lot bloqué pour les autres).
    `fiche`, `ticket` (sa fiche dans « tickets »), `disparu` (sa fiche dans
    « tickets_disparus ») : déjà lus ({} : lu, et absent ; None : relu ici —
    « tickets_disparus » seulement s'il n'a pas de ticket vivant)."""
    gid, vrai = str(gid or ""), _vrai_uid(uid)
    if fiche is None:
        import liens_va as lv
        fiche = lv.lien_de(gid, vrai)
    f = fiche if isinstance(fiche, dict) else {}
    if not (f.get("link_id") and f.get("tracking") and f.get("public_url")):
        return False, "sans_lien"
    if f.get("actif", True) is False:
        return False, "coupe"
    if ticket is None:
        import tickets_discord as tk
        ticket = tk._fiche(gid, vrai)
    if disparu is None and sur_demande(gid) and not (isinstance(ticket, dict) and ticket):
        import tickets_discord as tk
        disparu = (tk._etat().get("tickets_disparus") or {}).get(f"{gid}:{vrai}") or {}
    if depart_du_va(gid, ticket, disparu):
        return False, "parti"
    if not fiche_complete(f):
        return False, "fiche_incomplete"
    return True, ""


def raison_depart(gid: Any, uid: Any, etat_tickets: Dict[str, Any]) -> str:
    """Pourquoi ce VA compte pour parti sur un serveur à places fixes (« »
    s'il ne l'est pas, depart_du_va) — pour la reprise, qui coupe ses pages,
    et son journal. `etat_tickets` : tickets_discord._etat() déjà lu."""
    cle = f"{gid}:{_vrai_uid(uid)}"
    return depart_du_va(gid, (etat_tickets.get("tickets") or {}).get(cle),
                        (etat_tickets.get("tickets_disparus") or {}).get(cle))


# ─── Registre ─────────────────────────────────────────────────────────────
def _lire() -> Dict[str, Any]:
    d = safe_json.load(FICHIER, default={}) or {}
    if not isinstance(d, dict):
        _log(f"{FICHIER.name} n'est pas un objet JSON : repart à vide")
        d = {}
    if not isinstance(d.get("pages"), dict):
        d["pages"] = {}
    return d


def _ecrire(d: Dict[str, Any]) -> bool:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(safe_json.write(FICHIER, d, indent=1))
    if not ok:
        _log(f"écriture de {FICHIER.name} refusée")
    return ok


def page_de(gid: Any, uid: Any) -> Dict[str, Any]:
    p = _lire()["pages"].get(f"{gid}:{uid}")
    return dict(p) if isinstance(p, dict) else {}


#: Les champs remplacés tels quels (les autres dict sont fusionnés) : un
#: compteur remis à zéro par {} ne doit pas garder ses anciennes valeurs.
_REMPLACES = {"essais"}


def _noter(gid: Any, uid: Any, **champs) -> bool:
    """Rend vrai si le registre est écrit : creer_page en dépend (une copie
    GetMySocial que le registre ne connaît pas serait recopiée à chaque
    passage — disque plein, 4 passages : 12 copies vivantes pour 3 places)."""
    with _VERROU:
        d = _lire()
        p = d["pages"].setdefault(f"{gid}:{uid}", {})
        for k, v in champs.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict) and k not in _REMPLACES:
                p[k] = dict(p[k], **v)
            else:
                p[k] = v
        return _ecrire(d)


# ─── Demandes de pages (TRUST INSTAGRAM, 06/11/2026) ─────────────────────
# Une clé à part, « demandes », et pas une fiche « uid#n » sans link_id dans
# « pages » : le menu et la reprise y verraient une page à créer. Une demande
# par id (secrets.token_hex, dans le custom_id des boutons ✅ / ❌) : un vieux
# ✅ resté sur un message ne peut pas accepter une demande plus récente. La
# bascule attente → acceptee / refusee se fait sous _VERROU, écrite sur le
# disque avant de répondre : un seul clic gagne, même après un redémarrage
# (un verrou en mémoire, comme celui de verif_discord, s'y perd).
def _demandes(d: Dict[str, Any]) -> Dict[str, Any]:
    dem = d.get("demandes")
    if not isinstance(dem, dict):
        dem = d["demandes"] = {}
    return dem


def _de_ce_va(x: Any, gid: str, uid: str) -> bool:
    return isinstance(x, dict) and str(x.get("gid")) == gid and str(x.get("uid")) == uid


def demande_en_attente(gid: Any, uid: Any, d: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """La demande en attente de ce VA ({…, "id"}), ou {}. `d` : le registre
    déjà lu."""
    gid, uid = str(gid), _vrai_uid(uid)
    for did, x in ((d if d is not None else _lire()).get("demandes") or {}).items():
        if _de_ce_va(x, gid, uid) and x.get("etat") == "attente":
            return dict(x, id=str(did))
    return {}


def places_acceptees(gid: Any, uid: Any, d: Optional[Dict[str, Any]] = None) -> List[int]:
    """Les places attribuées aux demandes acceptées de ce VA, dans l'ordre."""
    gid, uid = str(gid), _vrai_uid(uid)
    f = fixes(gid)
    out = set()
    for x in ((d if d is not None else _lire()).get("demandes") or {}).values():
        if _de_ce_va(x, gid, uid) and x.get("etat") == "acceptee":
            try:
                n = int(x.get("place") or 0)
            except (TypeError, ValueError):
                n = 0
            if n > f:
                out.add(n)
            else:
                _log(f"demande acceptée de {gid}:{uid} sans place valable ({x.get('place')!r}) : ignorée")
    return sorted(out)


def demander_page(gid: Any, uid: Any, par: str = "") -> Dict[str, Any]:
    """Note une demande de page de ce VA. Une seule en attente à la fois.
    Rend {ok, id} ou {ok: False, deja, id, erreur}."""
    gid, uid = str(gid), _vrai_uid(uid)
    if not sur_demande(gid):
        return {"ok": False, "erreur": "pas de pages à la demande sur ce serveur"}
    orpheline = ""
    with _VERROU:
        d = _lire()
        dem = _demandes(d)
        deja = next((k for k, x in dem.items() if _de_ce_va(x, gid, uid) and x.get("etat") == "attente"), "")
        if deja and _sans_message_depuis_trop(dem[deja]):
            # notée, puis le bot a redémarré avant de poser le message ✅ / ❌
            # (le cron redémarre va-bot moins d'une minute après un push) :
            # personne ne pourrait y répondre, le VA resterait « ⏳ » à vie
            dem[deja].update(etat="annulee", raison="message jamais posé (redémarrage ?)",
                             decide_quand=int(time.time()))
            orpheline, deja = str(deja), ""
        if deja:
            return {"ok": False, "deja": True, "id": str(deja), "erreur": "demande déjà en attente"}
        did = secrets.token_hex(5)
        while did in dem:
            did = secrets.token_hex(5)
        dem[did] = {"gid": gid, "uid": uid, "etat": "attente", "par": str(par or ""), "quand": int(time.time())}
        if not _ecrire(d):
            return {"ok": False, "erreur": "registre non écrit : demande non notée, reclique"}
    if orpheline:
        _log(f"demande de page {orpheline} de {gid}:{uid} annulée : message jamais posé (redémarrage ?)")
    _log(f"demande de page {did} de {gid}:{uid} (par {par or '?'})")
    return {"ok": True, "id": did}


#: Une demande notée sans message ✅ / ❌ au-delà de ça est orpheline : le
#: fil qui le pose (tickets_discord, _demande_page) met au pire une
#: quarantaine de secondes (429 de Discord) ; au-delà, le bot a redémarré.
DEMANDE_SANS_MESSAGE_S = 10 * 60


def _sans_message_depuis_trop(x: Any) -> bool:
    return isinstance(x, dict) and x.get("etat") == "attente" and not x.get("message") \
        and time.time() - float(x.get("quand") or 0) > DEMANDE_SANS_MESSAGE_S


def demande(did: str) -> Dict[str, Any]:
    """La demande `did` ({…, "id"}), ou {}."""
    x = (_lire().get("demandes") or {}).get(str(did))
    return dict(x, id=str(did)) if isinstance(x, dict) else {}


def demande_de_place(gid: Any, uid: Any, n: int, d: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """La demande acceptée qui a attribué la place n de ce VA ({…, "id"}), ou {}."""
    gid, uid = str(gid), _vrai_uid(uid)
    for did, x in ((d if d is not None else _lire()).get("demandes") or {}).items():
        if _de_ce_va(x, gid, uid) and x.get("etat") == "acceptee" and str(x.get("place")) == str(int(n)):
            return dict(x, id=str(did))
    return {}


def noter_message_demande(did: str, salon: str, mid: str) -> None:
    """Le message ✅ / ❌ posé pour cette demande (pour le retrouver)."""
    with _VERROU:
        d = _lire()
        x = _demandes(d).get(str(did))
        if isinstance(x, dict):
            x.update(salon=str(salon), message=str(mid))
            _ecrire(d)


def noter_message_maj(did: str) -> None:
    """Le message de la demande porte l'adresse de la page : la reprise ne le
    réécrit plus."""
    with _VERROU:
        d = _lire()
        x = _demandes(d).get(str(did))
        if isinstance(x, dict):
            x["message_maj"] = int(time.time())
            _ecrire(d)


def noter_message_rate(did: str) -> int:
    """Un PATCH du message de la demande refusé par Discord : compté (le lot
    le refait, MESSAGE_ESSAIS_MAX fois). Rend le nombre d'essais."""
    with _VERROU:
        d = _lire()
        x = _demandes(d).get(str(did))
        if not isinstance(x, dict):
            return 0
        x["message_essais"] = int(x.get("message_essais") or 0) + 1
        _ecrire(d)
        return int(x["message_essais"])


def annuler_demande(did: str, raison: str) -> bool:
    """Une demande dont le message n'a pas pu être posé : annulée (sinon le VA
    resterait « ⏳ en attente » sans que personne ne puisse répondre)."""
    with _VERROU:
        d = _lire()
        x = _demandes(d).get(str(did))
        if not isinstance(x, dict) or x.get("etat") != "attente":
            return False
        x.update(etat="annulee", raison=str(raison)[:200], decide_quand=int(time.time()))
        ok = _ecrire(d)
    _log(f"demande de page {did} annulée : {raison}")
    return ok


def _prochaine_place(d: Dict[str, Any], gid: str, uid: str) -> int:
    """Après les fixes, la plus haute place déjà attribuée (demande acceptée)
    ou créée (registre des pages), plus un : jamais deux fois la même."""
    haut = fixes(gid)
    for x in _demandes(d).values():
        if _de_ce_va(x, gid, uid) and x.get("etat") == "acceptee":
            try:
                haut = max(haut, int(x.get("place") or 0))
            except (TypeError, ValueError):
                pass
    for cle in (d.get("pages") or {}):
        g, _s, u = str(cle).partition(":")
        if g == gid and _vrai_uid(u) == uid:
            haut = max(haut, numero_de_place(u))
    return haut + 1


def decider_demande(gid: Any, uid: Any, did: str, accepte: bool, par: str = "") -> Dict[str, Any]:
    """Accepte ou refuse la demande `did` de ce VA. Rend {ok, etat, place}
    (place : attribuée ici, à l'acceptation) ; déjà tranchée : {ok: False,
    deja, etat, par, place} ; disque refusé : {ok: False, erreur}, rien
    décidé."""
    gid, uid, did = str(gid), _vrai_uid(uid), str(did)
    with _VERROU:
        d = _lire()
        x = _demandes(d).get(did)
        if not _de_ce_va(x, gid, uid):
            return {"ok": False, "erreur": "demande inconnue"}
        if x.get("etat") != "attente":
            return {"ok": False, "deja": True, "etat": str(x.get("etat") or ""),
                    "par": str(x.get("decide_par") or ""), "place": int(x.get("place") or 0)}
        n = _prochaine_place(d, gid, uid) if accepte else 0
        x.update(etat="acceptee" if accepte else "refusee", decide_par=str(par or ""),
                 decide_quand=int(time.time()))
        if accepte:
            x["place"] = n
        if not _ecrire(d):
            return {"ok": False, "erreur": "registre non écrit : rien n'est décidé, reclique"}
    _log(f"demande de page {did} de {gid}:{uid} {'acceptée (page ' + str(n) + ')' if accepte else 'refusée'}"
         f" par {par or '?'}")
    return {"ok": True, "etat": "acceptee" if accepte else "refusee", "place": n}


# ─── Ce que tape le VA ────────────────────────────────────────────────────
_BALISE = re.compile(r"\{\{/?color(?::[^}]*)?\}\}", re.I)


def sans_balisage(texte: Any) -> str:
    """Le texte d'une page sans le balisage de couleur de GetMySocial."""
    return _BALISE.sub("", str(texte or ""))


def nettoyer(texte: Any, n: int, lignes: int = 1) -> str:
    """Ce que le VA tape, sans balisage GetMySocial (accolades : {{color}},
    jetons {city}…) ni caractères de contrôle, `lignes` lignes et `n`
    caractères au plus."""
    t = sans_balisage(texte).replace("{", "").replace("}", "")
    t = "".join(c for c in t if c == "\n" or (ord(c) >= 32 and ord(c) != 127))
    morceaux = [re.sub(r"[ \t]+", " ", l).strip() for l in t.replace("\r", "").split("\n")]
    morceaux = [l for l in morceaux if l]
    if lignes > 1:
        return "\n".join(morceaux[:lignes]).strip()[:n]
    return " ".join(morceaux).strip()[:n]


_BALISE_OUVRANTE = re.compile(r"^\{\{color:(#[0-9A-Fa-f]{3,8})\}\}")


def avec_couleur_du_modele(nouveau: str, ancien: Any) -> str:
    """Le texte du VA dans la couleur du texte qu'il remplace : la page de
    base écrit « Lia ♡ » en blanc ({{color:#ffffff}}) sur le canard ; sans
    ça, le texte modifié prenait la couleur de la page et disparaissait."""
    m = _BALISE_OUVRANTE.match(str(ancien or "").strip())
    if not m or not nouveau:
        return nouveau
    return "{{color:%s}}%s{{/color}}" % (m.group(1), nouveau)


def couleur_valide(c: Any) -> str:
    c = str(c or "").strip().upper()
    return c if re.fullmatch(r"#[0-9A-F]{6}", c) else ""


def couleur_texte(fond: str) -> str:
    """Le texte de la page, lisible sur ce fond : blanc sur foncé, presque
    noir sur clair (luminance relative)."""
    c = couleur_valide(fond) or "#000000"
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(x):
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    blanc = 1.05 / (lum + 0.05)
    fonce = (lum + 0.05) / (0.0056 + 0.05)          # #111111 : luminance ≈ 0,0056
    return "#FFFFFF" if blanc >= fonce else "#111111"


def image_unie(couleur: str) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", FOND_TAILLE, couleur_valide(couleur) or "#000000").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def preparer_fond(octets: bytes) -> Tuple[Optional[bytes], str]:
    """L'image de fond déposée : (JPEG FOND_TAILLE, 9:16, recadré au centre,
    sans EXIF, « ») ou (None, la raison)."""
    return preparer_photo(octets, FOND_TAILLE)


def preparer_photo(octets: bytes, taille: Optional[Tuple[int, int]] = None) -> Tuple[Optional[bytes], str]:
    """(JPEG carré COTE_PHOTO — ou `taille` —, « ») ou (None, la raison à dire
    au VA)."""
    taille = taille or (COTE_PHOTO, COTE_PHOTO)
    if not octets:
        return None, "image vide"
    if len(octets) > PHOTO_MAX:
        return None, f"image trop lourde (au plus {PHOTO_MAX // (1024 * 1024)} Mo)"
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(octets))
        if im.size[0] * im.size[1] > PIXELS_MAX:
            return None, "image trop grande (en pixels) : envoie une photo normale"
        if im.format == "JPEG":
            im.draft("RGB", (taille[0] * 2, taille[1] * 2))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            # la transparence devenait du noir : posée sur du blanc
            im = im.convert("RGBA")
            fond = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(fond, im)
        im = im.convert("RGB")
        im = ImageOps.fit(im, taille, method=Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)        # sans EXIF : ni GPS ni appareil
        return buf.getvalue(), ""
    except Exception as e:                                   # noqa: BLE001
        _log(f"photo illisible : {type(e).__name__}: {str(e)[:120]}")
        return None, "image illisible (envoie un JPG ou un PNG)"


# ─── GetMySocial ──────────────────────────────────────────────────────────
def _equipe(gid: str) -> str:
    import liens_va as lv
    e = str(lv.espace(gid).get("equipe") or "")
    return e if e.startswith("tm_") else f"tm_{e}" if e else ""


def _sans_tm(e: str) -> str:
    return e[3:] if e.startswith("tm_") else e


#: Une image ENVOYÉE (pas l'image par défaut de GetMySocial) : son adresse
#: porte l'horodatage de l'envoi, en millisecondes.
_RE_ENVOI = re.compile(r"^https://images\.getmysocial\.com/.*?(\d{13})[-/]", re.I)


def _envoyee_depuis(url: Any, depuis: float) -> bool:
    m = _RE_ENVOI.match(str(url or ""))
    return bool(m) and int(m.group(1)) >= int((depuis - 120) * 1000)


def envoyer_images(equipe: str, photo: Optional[bytes] = None,
                   fond: Optional[bytes] = None) -> Dict[str, Any]:
    """Les images, mises chez GetMySocial par une page temporaire (multipart),
    dont on reprend les adresses ; la page temporaire est supprimée ensuite
    (l'image reste servie, essai du 06/11). Rend {ok, photo, fond, erreur}."""
    import requests
    import gms
    if not (photo or fond):
        return {"ok": True, "photo": "", "fond": ""}
    cle = gms.get_api_key()
    if not cle:
        return {"ok": False, "erreur": "clé API GetMySocial absente"}
    fichiers = {}
    if photo:
        fichiers["profilePicture"] = ("pp.jpg", photo, "image/jpeg")
    if fond:
        fichiers["backgroundImage"] = ("fond.jpg", fond, "image/jpeg")
    depuis = time.time()
    champs = {"shortcode": "pgimg" + secrets.token_hex(5),
              "display_name": "image de page (temporaire)", "type": "landing",
              "team_id": _sans_tm(equipe)}
    try:
        r = requests.post(f"{gms.PUBLIC_REST_BASE}/links", headers={"Authorization": f"Bearer {cle}"},
                          data=champs, files=fichiers, timeout=60)
    except Exception as e:                                   # noqa: BLE001
        # la page a pu être créée avant la coupure : retrouvée et retirée
        _retirer_temporaire(equipe, champs["shortcode"], "")
        return {"ok": False, "erreur": f"GetMySocial injoignable ({type(e).__name__})"}
    try:
        tmp = r.json()
    except Exception:                                        # noqa: BLE001
        tmp = {}
    if isinstance(tmp, dict) and isinstance(tmp.get("data"), dict) and "id" not in tmp:
        tmp = tmp["data"]
    tid = str((tmp or {}).get("id") or "") if isinstance(tmp, dict) else ""
    out: Dict[str, Any] = {"ok": False, "photo": "", "fond": "", "erreur": ""}
    try:
        if r.status_code not in (200, 201) or not tid:
            if r.status_code >= 500 or (r.status_code in (200, 201) and not tid):
                _retirer_temporaire(equipe, champs["shortcode"], "")
            out["erreur"] = f"GetMySocial refuse l'image (HTTP {r.status_code})"
            return out
        if photo:
            u = str(tmp.get("profile_picture") or "")
            if not _envoyee_depuis(u, depuis):
                out["erreur"] = "photo refusée par GetMySocial (image par défaut à la place)"
                return out
            out["photo"] = u
        if fond:
            u = str(tmp.get("background_image") or "")
            if not _envoyee_depuis(u, depuis):
                out["erreur"] = "fond refusé par GetMySocial"
                return out
            out["fond"] = u
        out["ok"] = True
        return out
    finally:
        if tid:
            _retirer_temporaire(equipe, champs["shortcode"], tid)


def _retirer_temporaire(equipe: str, sc: str, tid: str) -> bool:
    """Supprime la page temporaire d'images (retrouvée par son adresse quand
    la réponse s'est perdue) ; refusée : coupée et notée, la reprise la
    supprimera. Rend vrai si elle n'existe plus."""
    import gms
    if not tid:
        try:
            r = gms.list_links_team(equipe, force_refresh=True)
            tid = next((str(l.get("id")) for l in (r.get("links") or [])
                        if str(l.get("shortcode") or "") == sc), "")
        except Exception as e:                               # noqa: BLE001
            _log(f"page temporaire {sc} : équipe illisible ({type(e).__name__})")
            tid = ""
        if not tid:
            return True                 # jamais créée (ou introuvable : rien de vivant connu)
    if gms.delete_link(tid).get("ok"):
        return True
    gms.disable_link(tid)
    with _VERROU:
        d = _lire()
        d.setdefault("orphelines", {})[tid] = {"equipe": equipe, "quand": int(time.time())}
        _ecrire(d)
    _log(f"page temporaire {tid} non supprimée : coupée, notée pour la reprise")
    return False


def _lire_page(lid: str, equipe: str) -> Dict[str, Any]:
    import gms
    r = gms.get_link(lid, equipe)
    return r.get("link") if r.get("ok") and isinstance(r.get("link"), dict) else {}


def _boutons_of(boutons: Any) -> List[Dict[str, Any]]:
    import liens_va as lv
    return [b for b in (boutons or []) if isinstance(b, dict) and lv._RE_OF.search(str(b.get("url") or ""))]


# ─── Création ─────────────────────────────────────────────────────────────
def creer_page(gid: str, uid: str, par: str = "", n: int = 1) -> Dict[str, Any]:
    """La page du VA : copie du gabarit de sa place, bouton sur SON tracking,
    pays, safe page, le 70/30 là où il est voulu (AB_PAGES), rangée chez son
    manager. Rend {ok, url, erreur, deja} — et « hors_service » (la raison
    d'en_service) quand le VA ne peut pas avoir de page : rien n'a été tenté.
    Un échec après la copie la laisse COUPÉE (jamais supprimée), dite."""
    import gms
    import liens_va as lv
    gid, vrai = str(gid), _vrai_uid(uid)
    n = int(n or 1)
    if n not in places(gid, vrai):
        if sur_demande(gid):
            return {"ok": False, "erreur": f"page {n} pas acceptée par un manager"}
        return {"ok": False, "erreur": f"{pages_max(gid)} page(s) au plus ici"}
    uid = place(vrai, n)
    cle = f"{gid}:{uid}"
    deja = page_de(gid, uid)
    if deja.get("link_id") and deja.get("etat", "prete") == "prete":
        return {"ok": True, "deja": True, "url": deja.get("public_url", ""), "erreur": "",
                "manques": list(deja.get("manques") or [])}
    gab = gabarit(gid, n)
    if not gab:
        return {"ok": False, "erreur": "pas de gabarit de page sur ce serveur"}
    # « hors_service » : la raison d'en_service — le lot de créations
    # automatiques n'y voit pas un essai raté (un VA coupé PENDANT le lot
    # perdait ainsi 2 essais sur 3 et 2 places du lot)
    f = lv.lien_de(gid, vrai)
    if not (f.get("link_id") and f.get("tracking") and f.get("public_url")):
        return {"ok": False, "hors_service": "sans_lien",
                "erreur": "il faut d'abord son lien direct (avec son tracking)"}
    if f.get("actif", True) is False:
        # la copie naîtrait coupée et le VA recevrait « ✅ » avec une adresse morte
        return {"ok": False, "hors_service": "coupe", "erreur": "son lien direct est désactivé"}
    if not fiche_complete(f):
        return {"ok": False, "hors_service": "fiche_incomplete",
                "erreur": "numéro ou pseudo du VA manquant dans sa fiche"}
    if sur_demande(gid):
        # la règle de la création automatique et de ✅ (en_service) : une page
        # vivante sur le tracking d'un VA parti, ou née coupée, ne sert à rien
        sert, raison = en_service(gid, vrai, fiche=f)
        if not sert:
            return {"ok": False, "hors_service": raison, "erreur": f"VA hors service ({raison}) : pas de page"}
    # Plus de « crée d'abord la page n-1 » : une page ratée (quota, panne)
    # bloquait toutes les suivantes, création automatique comprise.
    equipe = _equipe(gid)
    with _VERROU:
        if cle in _CREATIONS:
            return {"ok": False, "erreur": "création déjà en cours"}
        _CREATIONS.add(cle)
    try:
        # sous le verrou de la page, comme la bascule, la reprise et la
        # modification : un « Désactiver » ou un « 🔁 Réessayer » pendant la
        # copie attend la fin, puis voit la page telle qu'elle est notée
        with _verrou_page(cle):
            return _creer_sous_verrou(gid, uid, vrai, n, cle, page_de(gid, uid), f, equipe, gab, par)
    finally:
        with _VERROU:
            _CREATIONS.discard(cle)


def _creer_sous_verrou(gid: str, uid: str, vrai: str, n: int, cle: str, deja: Dict[str, Any],
                       f: Dict[str, Any], equipe: str, gab: str, par: str) -> Dict[str, Any]:
    import gms
    import liens_va as lv
    if deja.get("link_id") and deja.get("etat", "prete") == "prete":
        # finie par un autre clic pendant qu'on attendait le verrou
        return {"ok": True, "deja": True, "url": deja.get("public_url", ""), "erreur": "",
                "manques": list(deja.get("manques") or [])}
    plateforme = str(lv.espace(gid).get("plateforme") or "Twitter")
    nom = (f'{plateforme} VA {f.get("numero")} @{f.get("pseudo")} page' + (f" {n}" if n > 1 else ""))[:60]
    if deja.get("link_id"):
        # une création ratée (bouton non posé, panne) : reprise sur la MÊME
        # copie, coupée en attendant — jamais une seconde copie
        lid, sc = str(deja["link_id"]), str(deja.get("shortcode") or "")
        url = str(deja.get("public_url") or f"{gms.PUBLIC_LINK_DOMAIN}/{sc}")
        try:
            return _finir_page(gid, uid, f, lid, sc, str(deja.get("nom") or nom), url, equipe)
        except Exception as e:                           # noqa: BLE001
            _couper(gid, uid, lid, etat="ratee", erreur=f"{type(e).__name__}: {str(e)[:120]}")
            return {"ok": False, "erreur": f"{type(e).__name__} : page coupée"}
    lid, sc, erreur, essai = "", "", "", 0
    # Sur un serveur à places fixes, directement les paires de mots : les
    # 25 mots seuls sont pris chez GetMySocial (adresses communes à tous
    # les comptes ; la page pilote Twitter du 06/11 est sortie
    # « sugarlilyy », une paire). Chaque refus est une écriture sur la clé
    # principale, 25 de plus par page × 3 pages × chaque VA. Twitter garde
    # son ordre.
    decalage = len(lv.MOTS_THREADS) if sur_demande(gid) else 0
    # Les liens de l'équipe à ce nom AVANT la 1re copie : seuls ceux qui
    # naissent pendant cet appel peuvent être une copie à la réponse perdue.
    # Sans ce relevé, _couper_doublons coupait une page VIVANTE au même nom
    # que le registre ne connaissait plus (rangée dans « anciennes », registre
    # restauré) : la 1re adresse essayée ne dépend que du nom, l'ancienne page
    # la porte, le refus « adresse prise » menait à la coupure à coup sûr.
    # Twitter n'a pas _couper_doublons : pas de relevé (aucune lecture en plus).
    avant = _ids_au_nom(equipe, nom) if sur_demande(gid) else None
    for essai in range(lv.ESSAIS_ADRESSE):
        sc = lv.mots_sans_prenom(nom, essai + decalage)
        r = gms.duplicate_link(gab, sc, nom, "", equipe)
        if r.get("ok") and (r.get("link") or {}).get("id"):
            lid = str(r["link"]["id"])
            break
        erreur = str(r.get("error") or "refus GetMySocial")
        if "shortcode" not in erreur.lower():
            break
    if not lid:
        return {"ok": False, "erreur": f"GetMySocial : {erreur[:140]}"}
    url = f"{gms.PUBLIC_LINK_DOMAIN}/{sc}"
    if not _noter(gid, uid, link_id=lid, shortcode=sc, public_url=url, nom=nom, par=str(par),
                  quand=int(time.time()), actif=True, etat="en_cours"):
        # une copie que le registre ne connaît pas serait refaite au
        # passage suivant, et ainsi de suite : coupée tout de suite
        coupee = bool(gms.disable_link(lid).get("ok"))
        _log(f"page {sc} de {cle} : registre non écrit, copie {lid} "
             + ("coupée" if coupee else "NON coupée (à couper à la main)"))
        return {"ok": False, "disque": True, "erreur": "registre non écrit : copie coupée"}
    if essai and sur_demande(gid):
        # un « adresse prise » peut être la NÔTRE : gms renvoie une fois
        # un appel dont la réponse s'est perdue (_call_tool_brut), la 1re
        # copie existe alors sans que personne ne la connaisse
        _couper_doublons(gid, vrai, equipe, nom, lid, avant)
    try:
        return _finir_page(gid, uid, f, lid, sc, nom, url, equipe)
    except Exception as e:                               # noqa: BLE001
        _couper(gid, uid, lid, etat="ratee", erreur=f"{type(e).__name__}: {str(e)[:120]}")
        _log(f"page {sc} de {cle} : {type(e).__name__}: {e} — coupée")
        return {"ok": False, "erreur": f"{type(e).__name__} : page coupée"}


def _ids_au_nom(equipe: str, nom: str) -> Tuple[Optional[set], str]:
    """Les ids des liens de l'équipe dont le nom (display_name) est `nom`, lus
    à l'instant (force_refresh). (None, la raison) si l'équipe est illisible."""
    import gms
    try:
        r = gms.list_links_team(equipe, force_refresh=True)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not r.get("ok"):
        return None, str(r.get("error") or "équipe illisible")[:100]
    return {str(l.get("id")) for l in (r.get("links") or [])
            if isinstance(l, dict) and l.get("id") and str(l.get("display_name") or "") == nom}, ""


def _ids_notes() -> set:
    """Les link_id de toutes les pages du registre, « anciennes » comprises :
    aucune n'est une copie orpheline."""
    d = _lire()
    out = set()
    for groupe in (d.get("pages"), d.get("anciennes")):
        valeurs = groupe.values() if isinstance(groupe, dict) else groupe if isinstance(groupe, list) else []
        out |= {str(p["link_id"]) for p in valeurs if isinstance(p, dict) and p.get("link_id")}
    return out


def _couper_doublons(gid: str, vrai: str, equipe: str, nom: str, lid: str,
                     avant: Tuple[Optional[set], str]) -> int:
    """Les copies au nom de cette page NÉES PENDANT CET APPEL (absentes du
    relevé `avant`, pris avant la 1re copie) que le registre ne connaît pas
    (ni `lid`, ni aucune page notée, « anciennes » comprises) : coupées,
    jamais supprimées, et dites. Sans relevé d'avant : rien coupé, dit. Rend
    leur nombre."""
    import gms
    ids_avant, pourquoi = avant if isinstance(avant, tuple) else (None, "pas de relevé")
    if ids_avant is None:
        _log(f"doublons de « {nom} » non cherchés : relevé de l'équipe d'avant la copie impossible "
             f"({pourquoi}) — rien coupé")
        return 0
    try:
        r = gms.list_links_team(equipe, force_refresh=True)
    except Exception as e:                                   # noqa: BLE001
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not r.get("ok"):
        _log(f"doublons de « {nom} » non cherchés : équipe illisible ({str(r.get('error'))[:100]})")
        return 0
    connus = set(ids_avant) | _ids_notes() | set(liens_des_pages(gid, vrai)) | {str(lid)}
    coupees = 0
    for l in r.get("links") or []:
        i = str((l or {}).get("id") or "") if isinstance(l, dict) else ""
        if not i or i in connus or str(l.get("display_name") or "") != nom:
            continue
        if gms.disable_link(i).get("ok"):
            coupees += 1
            _log(f"copie {i} « {nom} » née pendant cet appel (réponse perdue de GetMySocial), "
                 "inconnue du registre : coupée")
        else:
            _log(f"copie {i} « {nom} » née pendant cet appel, inconnue du registre : NON coupée, "
                 "à couper à la main")
    return coupees


def _finir_page(gid: str, uid: str, f: Dict[str, Any], lid: str, sc: str, nom: str,
                url: str, equipe: str) -> Dict[str, Any]:
    import gms
    import liens_va as lv
    cle = f"{gid}:{uid}"
    pose = lv._poser_tracking(lid, f["tracking"], nom, equipe)
    if not pose.get("ok"):
        _couper(gid, uid, lid, etat="ratee", erreur=f"bouton : {pose.get('erreur')}")
        _log(f"page {sc} de {cle} : tracking non posé ({pose.get('erreur')}), coupée")
        return {"ok": False, "erreur": f"bouton non posé ({pose.get('erreur')}) : page coupée"}
    pays = lv.poser_pays(lid, equipe)
    sur = gms.update_link(lid, {"display_name": nom, "bot_protection": {"mode": "safe_page"}}, equipe)
    # Le 70/30 APRÈS le bouton : _poser_base_seule relit la destination de la
    # page (sa model) et refuse tant qu'elle ne mène pas au tracking du VA.
    # Twitter : « ça doit pas être 70 30 » — aucun A/B (ab_voulu faux).
    ab = _poser_ab(gid, uid, lid, f["tracking"], sc) if ab_voulu(gid) else None
    if ab is not None and ab.get("inattendu"):
        # la copie a hérité d'un A/B inconnu de son gabarit (un duplicata garde
        # l'A/B de sa source) : elle servirait une variante que personne ne
        # connaît. Coupée (disable_link : éteindre l'A/B effacerait ses
        # variantes), jamais donnée.
        _couper(gid, uid, lid, etat="ratee", erreur=f"70/30 : {str(ab.get('erreur'))[:160]}")
        _log(f"page {sc} de {cle} : A/B inattendu hérité du gabarit, coupée ({str(ab.get('erreur'))[:120]})")
        return {"ok": False, "erreur": "A/B inattendu sur la copie (hérité du gabarit) : page coupée"}
    groupe = lv.ranger(equipe, lid, str(f.get("groupe") or f.get("manager") or ""))
    lu = _lire_page(lid, equipe)
    ofs = _boutons_of(lu.get("buttons"))
    champs = {"nom": nettoyer(lu.get("name_user"), MAX_NOM),
              "bio": nettoyer(lu.get("bio"), MAX_BIO, lignes=4),
              "bouton": nettoyer((ofs[0].get("label") if ofs else ""), MAX_BOUTON)}
    # relue à la fin : un « Désactiver » (ou un départ) pendant la copie a
    # écrit la fiche et sa tâche de fond attend notre verrou — ou l'a déjà
    # trouvée sans page ; dans les deux cas la page ne doit pas rester vivante
    actif = f.get("actif", True) is not False \
        and lv.lien_de(gid, _vrai_uid(uid)).get("actif", True) is not False
    manques = ([] if pays.get("ok") else ["pays"]) + ([] if sur.get("ok") else ["safe page"]) \
        + ([] if ab is None or ab.get("ok") else ["70/30"])
    a_rallumer = False
    if not actif:
        # son lien direct est coupé : la page aussi (reprise si GetMySocial refuse)
        if not gms.disable_link(lid).get("ok"):
            _noter(gid, uid, a_couper=True)
    elif page_de(gid, uid).get("actif") is False:
        # reprise d'une page ratée, coupée par l'échec : rallumée
        a_rallumer = not gms.enable_link(lid).get("ok")
    _noter(gid, uid, actif=bool(actif) and not a_rallumer, a_rallumer=a_rallumer, etat="prete", erreur="",
           pays=bool(pays.get("ok")), pays_erreur=str(pays.get("erreur") or ""),
           safe=bool(sur.get("ok")), groupe=groupe, champs=champs, manques=manques, essais={}, a_verifier=False,
           tracking=f["tracking"], **({"ab": _note_ab(ab)} if ab is not None else {}))
    _log(f"page {sc} prête pour {cle}" + (f", à reprendre : {manques}" if manques else ""))
    return {"ok": True, "url": url, "erreur": "", "manques": manques}


def ab_voulu(gid: Any) -> bool:
    """Le 70/30 « Lia seule » sur les pages de ce serveur : AB_PAGES, et
    liens_va.lia_seule encore vrai (la clé « lia_seule » de la config peut
    l'éteindre pour tous les liens d'un coup)."""
    if str(gid or "") not in AB_PAGES:
        return False
    import liens_va as lv
    try:
        return bool(lv.lia_seule(str(gid)))
    except Exception as e:                                   # noqa: BLE001
        # config illisible : pas de 70/30 cette fois, et pas de note « ab » —
        # la reprise le rattrape dès qu'elle se relit (page prête sans ab.ok)
        _log(f"70/30 de {gid} : lia_seule illisible ({type(e).__name__}: {e})")
        return False


def _cookie_ok() -> bool:
    """Le cookie de l'écran A/B (le 70/30 passe par l'API privée) : posé, pas
    expiré, pas refusé. Sans lui, la page ATTEND : ni essai ni passage
    compté, comme le lien direct (liens_va.reprendre_base_seule)."""
    import gms
    import liens_va as lv
    try:
        ck = gms.get_session_cookie()
        exp = gms.cookie_expiration(ck) if ck else None
        return bool(ck) and not (exp and exp < time.time()) \
            and lv._etat().get("cookie_refuse") != lv._empreinte(ck)
    except Exception:                                        # noqa: BLE001
        return False


def _poser_ab(gid: str, uid: str, lid: str, tracking: str, sc: str) -> Dict[str, Any]:
    """Le 70/30 sur CETTE page (son id, son tracking) : l'appel privé avec
    `lien`. Le public liens_va.poser_base_seule écrirait dans la fiche du lien
    direct du VA. Ne lève pas."""
    import liens_va as lv
    if not _cookie_ok():
        return {"ok": False, "cookie": True, "erreur": "cookie GetMySocial absent, expiré ou refusé"}
    try:
        return lv._poser_base_seule(gid, uid, lien=_lien_ab(lid, tracking, sc))
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:120]}"}


def _lien_ab(lid: str, tracking: str, sc: Any) -> Dict[str, Any]:
    """Ce que reçoit liens_va._poser_base_seule pour une page. `safe_page` :
    la branche 30 % est une copie FIGÉE du lien temporaire au moment de
    l'enregistrement (ses pays sont posés dessus avant, pour cette raison) ;
    sans la safe page sur cette copie, les robots qui tombent dans les 30 %
    verraient l'adresse OnlyFans que la page, elle, cache. Non vérifié chez
    GetMySocial (pas d'essai possible sans réseau) : posée par prudence."""
    return {"link_id": lid, "tracking": tracking, "shortcode": sc, "safe_page": True}


def _note_ab(ab: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": bool(ab.get("ok")), "erreur": str(ab.get("erreur") or ""),
            "cookie": bool(ab.get("cookie")), "quand": int(time.time())}


def _couper(gid: str, uid: str, lid: str, etat: str, erreur: str) -> None:
    """Une page ratée : coupée (jamais supprimée), notée « ratee » — ni la
    bascule ni la reprise ne la rallument ; « Réessayer » la reprend."""
    import gms
    ok = bool(gms.disable_link(lid).get("ok"))
    _noter(gid, uid, actif=False, etat=etat, erreur=erreur, a_couper=not ok)


# ─── Modification ─────────────────────────────────────────────────────────
def modifier_page(gid: str, uid: str, nom: Optional[str] = None, bio: Optional[str] = None,
                  bouton: Optional[str] = None, couleur: Optional[str] = None,
                  photo: Optional[bytes] = None, fond: Optional[bytes] = None, n: int = 1) -> Dict[str, Any]:
    """Change ce qui est donné (None : on n'y touche pas). `photo`, `fond` :
    des JPEG déjà préparés (preparer_photo, preparer_fond). `couleur` : un
    fond uni (plus proposé dans la fenêtre depuis l'image de fond, 06/11).
    Relu ensuite. Rend {ok, faits, erreur}."""
    import gms
    if not modifiable(gid, n):
        # refusé ICI, avant toute lecture GetMySocial : cacher le bouton ne
        # suffit pas (un vieux menu, un custom_id forgé)
        return {"ok": False, "erreur": "page fixe : elle ne se modifie pas"}
    gid, uid = str(gid), place(_vrai_uid(uid), n)
    pg = page_de(gid, uid)
    lid = str(pg.get("link_id") or "")
    if not lid:
        return {"ok": False, "erreur": "pas de page"}
    equipe = _equipe(gid)
    couleur = couleur_valide(couleur) if couleur else ""
    with _verrou_page(f"{gid}:{uid}"):
        return _modifier(gid, uid, pg, lid, equipe, nom, bio, bouton, couleur, photo, fond)


def _modifier(gid, uid, pg, lid, equipe, nom, bio, bouton, couleur, photo, fond=None) -> Dict[str, Any]:
    import gms
    imgs = envoyer_images(equipe, photo=photo, fond=fond or (image_unie(couleur) if couleur else None))
    if not imgs.get("ok"):
        return {"ok": False, "erreur": imgs.get("erreur") or "images refusées"}
    lu = _lire_page(lid, equipe)
    if not lu:
        return {"ok": False, "erreur": "page illisible chez GetMySocial"}
    champs: Dict[str, Any] = {"display_name": str(lu.get("display_name") or pg.get("nom") or "")}
    faits: List[str] = []
    if nom is not None:
        champs["name_user"] = avec_couleur_du_modele(nettoyer(nom, MAX_NOM), lu.get("name_user"))
        faits.append("nom")
    if bio is not None:
        champs["bio"] = avec_couleur_du_modele(nettoyer(bio, MAX_BIO, lignes=4), lu.get("bio"))
        faits.append("bio")
    if fond:
        champs["background_image"] = imgs["fond"]
        faits.append("fond")
    if couleur:
        champs.update(custom_background_color=couleur, custom_text_color=couleur_texte(couleur),
                      background_image=imgs["fond"])
        # le balisage {{color}} du gabarit imposait sa couleur au texte
        champs.setdefault("bio", nettoyer(lu.get("bio"), MAX_BIO, lignes=4))
        champs.setdefault("name_user", nettoyer(lu.get("name_user"), MAX_NOM))
        faits.append("couleur")
    if bouton is not None:
        boutons = [dict(b) for b in (lu.get("buttons") or []) if isinstance(b, dict)]
        ofs = _boutons_of(boutons)
        if not ofs:
            return {"ok": False, "erreur": "aucun bouton OnlyFans sur la page"}
        for b in ofs:
            b["label"] = nettoyer(bouton, MAX_BOUTON)
        champs["buttons"] = boutons                # le tableau ENTIER : tracking et pays gardés
        faits.append("bouton")
    if photo:
        champs.update(profile_picture=imgs["photo"],
                      profile_picture_slides=[{"url": imgs["photo"], "media_type": "image"}])
        faits.append("photo")
    if not faits:
        return {"ok": True, "faits": [], "erreur": ""}
    r = gms.update_link(lid, champs, equipe)
    if not r.get("ok"):
        return {"ok": False, "erreur": "GetMySocial refuse : " + str(r.get("error") or "")[:140]}
    relu = _lire_page(lid, equipe)
    rates = []
    for cle_page in ("name_user", "bio", "custom_background_color", "profile_picture", "background_image"):
        if cle_page in champs and str(relu.get(cle_page) or "") != str(champs[cle_page] or ""):
            rates.append(cle_page)
    if "buttons" in champs:
        avant = [(b.get("url"), len(b.get("geofilters") or [])) for b in _boutons_of(lu.get("buttons"))]
        apres = [(b.get("url"), len(b.get("geofilters") or [])) for b in _boutons_of(relu.get("buttons"))]
        if [b.get("label") for b in _boutons_of(relu.get("buttons"))] != [nettoyer(bouton, MAX_BOUTON)] * len(apres) \
                or avant != apres:
            rates.append("buttons")
    if rates:
        _log(f"page {lid} de {gid}:{uid} relue autrement : {rates}")
        return {"ok": False, "faits": faits, "erreur": "relu autrement chez GetMySocial : " + ", ".join(rates)}
    _noter(gid, uid, champs={k: v for k, v in (
        ("nom", nettoyer(champs["name_user"], MAX_NOM) if "name_user" in champs else None),
        ("bio", nettoyer(champs["bio"], MAX_BIO, lignes=4) if "bio" in champs else None),
        ("bouton", nettoyer(bouton, MAX_BOUTON) if bouton is not None else None),
        ("couleur", couleur or None)) if v is not None}, modifiee=int(time.time()))
    _log(f"page {lid} de {gid}:{uid} modifiée : {faits}")
    return {"ok": True, "faits": faits, "erreur": ""}


# ─── Suivre le lien direct ────────────────────────────────────────────────
def liens_des_pages(gid: str, uid: str) -> List[str]:
    """Les identifiants GetMySocial de toutes les pages notées de ce VA (toutes
    places) — pour compter leurs visites avec celles du lien direct."""
    vrai = _vrai_uid(uid)
    out: List[str] = []
    for c, pg in (_lire().get("pages") or {}).items():
        g, _s, u = str(c).partition(":")
        if g == str(gid) and _vrai_uid(u) == vrai and isinstance(pg, dict) and pg.get("link_id"):
            out.append(str(pg["link_id"]))
    return out


def suivre_bascule(gid: str, uid: str, actif: bool) -> None:
    """Le lien direct coupé ou rallumé (liens_va.basculer) : ses pages suivent
    — un VA parti ne garde pas une page vivante sur son tracking."""
    vrai = _vrai_uid(uid)
    # toutes ses places notées, pas seulement jusqu'à pages_max : un plafond
    # baissé ne doit pas laisser une page 3 vivante sur le tracking d'un parti
    places = {place(vrai, 1)} | {str(c).partition(":")[2] for c in (_lire().get("pages") or {})
                                 if str(c).startswith(f"{gid}:{vrai}#")}
    for u in sorted(places):
        _suivre_bascule_une(gid, u, actif)


def _suivre_bascule_une(gid: str, uid: str, actif: bool) -> None:
    with _verrou_page(f"{gid}:{uid}"):
        _suivre_bascule_une_sous_verrou(gid, uid, actif)


def _suivre_bascule_une_sous_verrou(gid: str, uid: str, actif: bool) -> None:
    import gms
    pg = page_de(gid, uid)
    lid = str(pg.get("link_id") or "")
    if not lid or pg.get("etat", "prete") != "prete":
        return                      # une page ratée ne se rallume jamais par là
    if bool(pg.get("actif", True)) == bool(actif) and not pg.get("a_couper") \
            and not (not actif and pg.get("a_rallumer")):
        return                      # (a_rallumer : un enable incertain, la page est peut-être en ligne)
    r = gms.enable_link(lid) if actif else gms.disable_link(lid)
    if r.get("ok"):
        _noter(gid, uid, actif=bool(actif), a_couper=False, a_rallumer=False)
    else:
        # repris par reprendre_pages (synchro des liens, toutes les 30 min)
        _noter(gid, uid, a_couper=not actif, a_rallumer=bool(actif))
        _log(f"page {lid} de {gid}:{uid} non {'rallumée' if actif else 'coupée'} : {str(r.get('error'))[:100]}")


# ─── Reprise (synchro des liens, toutes les 30 min) ───────────────────────
#: Au-delà, une étape ratée attend une main (« a_verifier », dit au journal à
#: chaque passage).
ESSAIS_REPRISE = 3
#: Les pages remises d'aplomb par passage (la boucle du podium attend).
PAGES_PAR_PASSE = 10
#: Une création « en_cours » plus vieille que ça (redémarrage au milieu) est
#: coupée : son adresse n'a jamais été donnée.
EN_COURS_MAX_S = 15 * 60
#: Les 70/30 tentés par passage, à part de PAGES_PAR_PASSE : un 70/30 coûte une
#: dizaine d'appels GetMySocial (copie temporaire, pays, lecture et écriture
#: privées, relecture) — comme BASES_POSEES_PAR_PASSE pour les liens directs.
AB_PAR_PASSE = 3
#: Le plafond des 70/30 par passage, par serveur, compté à part de
#: PAGES_PAR_PASSE (comme REPOINTES_PAR_PASSE). TRUST INSTAGRAM : après un
#: changement de model, 3 par passage laissaient la branche 30 % « Base … »
#: sur l'ancienne model ~11 h pour 22 VA (66 pages), ~17 h pour 45 VA.
AB_PAR_PASSE_SERVEUR: Dict[str, int] = {AGENCY_IG_ID: 10}
#: Les pages d'un VA parti (serveur à places fixes) coupées par passage : le
#: VA 110, parti le 28/10, a reçu 3 pages vivantes le 06/11 ; la reprise les
#: coupe (une écriture chacune), un tickets.json mal relu ne doit pas tout
#: couper d'un coup.
COUPURES_DEPART_PAR_PASSE = 15
#: Les boutons re-pointés par passage, à part de PAGES_PAR_PASSE, là où un VA
#: a plusieurs pages (TRUST INSTAGRAM) : après un changement de model, 45 VA ×
#: 3 pages × (bouton, pays, 70/30) dans un plafond de 10 laissaient 70 % des
#: visiteurs sur l'ancienne model pendant ~20 h (39 passages). Un re-pointage
#: coûte ~4 appels ; pays et 70/30 suivent aux passages d'après. Twitter (une
#: page par VA) garde le plafond commun.
REPOINTES_PAR_PASSE: Dict[str, int] = {AGENCY_IG_ID: 30}
#: Ce qui dit une panne PASSAGÈRE de GetMySocial (quota, 429, réseau, 5xx,
#: session MCP) : ni essai compté ni « à vérifier » — sinon une heure de quota
#: épuisé figeait des places « à reprendre » pour toujours. Le texte vient de
#: gms (« Quota GetMySocial epuise … », « HTTP 429 … », « Erreur réseau : … »).
#: Aussi « Budget GetMySocial du jour reserve a la paie (…) — relance plus
#: tard » (gms._choisir_cle, lectures de fond quand le pool est en pause) et
#: « Réponse invalide : <!DOCTYPE html>… » (page Cloudflare) : comptés comme
#: de vrais refus, ils figeaient 3 places « à reprendre » en fin de journée.
_RE_PASSAGERE = re.compile(r"quota|(?:HTTP|Error) 429|too many requests|rate.?limit|r[ée]seau|injoignable|"
                           r"time[d ]?out|HTTP 5\d\d|initialiser la session|budget getmysocial|"
                           r"r[ée]serv[ée]e? [aà] la paie|relance plus tard|r[ée]ponse invalide", re.I)
#: Parmi elles, celles qui touchent TOUT le compte (quota, 429, budget du
#: jour) : la copie suivante échouerait pareil, le lot s'arrête. Une autre
#: (un 502 sur le bouton d'UNE page) arrêtait aussi le lot, toujours sur la
#: même place en tête de file : plus aucune création sur le serveur.
_RE_GLOBALE = re.compile(r"quota|(?:HTTP|Error) 429|too many requests|rate.?limit|budget getmysocial|"
                         r"r[ée]serv[ée]e? [aà] la paie|relance plus tard", re.I)


def erreur_passagere(texte: Any) -> bool:
    return bool(_RE_PASSAGERE.search(str(texte or "")))


def panne_globale(texte: Any) -> bool:
    """Une panne passagère de tout le compte GetMySocial (quota, 429, budget)."""
    return bool(_RE_GLOBALE.search(str(texte or "")))


def _tickets_pour_departs(gid: str) -> Optional[Dict[str, Any]]:
    """L'état des tickets, s'il permet de dire qui est parti sur ce serveur ;
    None sinon, dit au journal : tickets_discord._etat rend {} sur un fichier
    (et son .prev) illisible, et sans un seul ticket de ce serveur tous ses
    VA compteraient pour partis — leurs pages seraient toutes coupées."""
    try:
        import tickets_discord as tk
        e = tk._etat()
    except Exception as ex:                                  # noqa: BLE001
        _log(f"reprise des pages {gid} : tickets illisibles ({type(ex).__name__}: {ex}) — "
             "aucune page coupée pour un départ ni rallumée ce passage")
        return None
    t = e.get("tickets") if isinstance(e, dict) else None
    if not isinstance(t, dict) or not any(str(k).startswith(f"{gid}:") for k in t):
        _log(f"reprise des pages {gid} : tickets illisibles ou sans ticket de ce serveur — "
             "aucune page coupée pour un départ ni rallumée ce passage")
        return None
    return e


def reprendre_pages(gid: str) -> Dict[str, Any]:
    """Les pages de ce serveur, remises d'aplomb sur leur lien direct :
      - une page ratée, ou une création interrompue, encore vivante : coupée ;
      - une page prête : coupée si le direct l'est — ou, sur un serveur à
        places fixes, si son VA est parti (depart_du_va : ticket marqué
        parti, rangé dans tickets_disparus AVEC « parti », ou introuvable
        partout ; un salon supprimé seul ne coupe rien),
        COUPURES_DEPART_PAR_PASSE au plus, son lien direct laissé tel quel
        et signalé —, rallumée s'il sert ;
        la fiche du direct est relue sous le verrou de la page avant de
        couper ou de rallumer ;
        son bouton re-pointé si le tracking du direct a changé (changement de
        model, passer_sur) — le tracking n'est noté qu'une fois le bouton
        relu dessus —, puis les pays (et le 70/30 sur AB_PAGES) refaits ;
        rangée chez le manager actuel ; les étapes manquées refaites,
        ESSAIS_REPRISE fois chacune (un 70/30 sans cookie attend sans
        compter ; sur un serveur à places fixes, une panne passagère de
        GetMySocial non plus, et une étape « à vérifier » est retentée une
        fois par CREATION_REESSAI_S) ; sur AB_PAGES, une page prête sans 70/30
        noté le reçoit ;
      - une page tenue par une création, une bascule ou une modification :
        laissée au passage suivant (« occupees »), jamais attendue ;
      - les pages temporaires d'images non supprimées : supprimées ;
      - sur un serveur à places fixes, les pages manquantes créées en fond
        (lancer_creations).
    PAGES_PAR_PASSE pages, AB_PAR_PASSE 70/30 (AB_PAR_PASSE_SERVEUR à part)
    et (là où il est fixé) REPOINTES_PAR_PASSE boutons re-pointés au plus. Le
    registre n'est réécrit que pour ce qui change. Ne lève pas."""
    import gms
    import liens_va as lv
    bilan: Dict[str, Any] = {"coupees": [], "rallumees": [], "trackings": [], "reprises": [],
                             "rates": [], "a_verifier": []}
    ab_ici = ab_voulu(gid)
    cookie: Optional[bool] = None
    ab_tentes = 0
    bilan["ab_en_attente"] = 0           # pages dont le 70/30 attend le cookie ou le passage suivant
    plafond_repointes = REPOINTES_PAR_PASSE.get(str(gid))
    repointees = 0
    plafond_ab = AB_PAR_PASSE_SERVEUR.get(str(gid))
    ab_max = AB_PAR_PASSE if plafond_ab is None else plafond_ab
    ab_a_part = plafond_ab is not None and ab_ici        # le 70/30 hors de PAGES_PAR_PASSE
    # Twitter garde ses règles (une page par VA) : la panne passagère n'est
    # mise à part que là où il y a des places fixes
    passageres_ici = sur_demande(gid)
    bilan["passageres"] = []
    # la fiche du direct, lue une fois par VA et par passage : 3 pages et plus
    # par VA relisaient liens_va.json chacune — RELUE sous le verrou de la page
    # avant de couper ou de rallumer (plus bas)
    fiches_vues: Dict[str, Dict[str, Any]] = {}
    etat_tk = _tickets_pour_departs(gid) if passageres_ici else None
    # sans savoir qui est parti, rien n'est rallumé non plus : la page d'un
    # VA parti, coupée au passage d'avant, revenait en ligne pour un passage
    tickets_inconnus = passageres_ici and etat_tk is None
    coupes_depart = 0
    d = _lire()
    eq = _equipe(gid)
    for tid, o in list((d.get("orphelines") or {}).items()):
        if isinstance(o, dict) and o.get("equipe") and str(o["equipe"]) != eq:
            continue                # celle d'un autre serveur : sa reprise s'en charge
        if gms.delete_link(tid).get("ok"):
            with _VERROU:
                d2 = _lire()
                (d2.get("orphelines") or {}).pop(tid, None)
                _ecrire(d2)
    traitees = 0
    for cle, pg in list(d["pages"].items()):
        g, _s, uid = str(cle).partition(":")          # uid : « uid » ou « uid#n » (la place)
        if g != str(gid) or not isinstance(pg, dict) or not pg.get("link_id"):
            continue
        lid = str(pg["link_id"])
        # Jamais attendre la page : depuis c8b306f une création (✅ d'un
        # manager, le lot) tient son verrou pendant toute la copie — plusieurs
        # dizaines de secondes avec le 70/30 —, et la reprise tourne dans la
        # boucle du podium, qui restait bloquée derrière. Reprise au passage
        # suivant.
        with _VERROU:
            en_creation = cle in _CREATIONS
        verrou = _verrou_page(cle)
        if en_creation or not verrou.acquire(blocking=False):
            bilan.setdefault("occupees", []).append(uid)
            continue
        try:
            pg = page_de(g, uid)
            etat = pg.get("etat", "prete")
            if etat != "prete":
                vieille = etat == "en_cours" and cle not in _CREATIONS \
                    and time.time() - float(pg.get("quand") or 0) > EN_COURS_MAX_S
                if pg.get("a_couper") or (vieille and pg.get("actif") is not False):
                    traitees += 1
                    if gms.disable_link(lid).get("ok"):
                        _noter(g, uid, actif=False, a_couper=False, etat="ratee")
                        bilan["coupees"].append(uid)
                    else:
                        bilan["rates"].append(f"{uid} : coupure")
                continue
            vrai = _vrai_uid(uid)
            if vrai not in fiches_vues:
                fiches_vues[vrai] = lv.lien_de(g, vrai)
            f = fiches_vues[vrai]
            depart = raison_depart(g, vrai, etat_tk) if etat_tk is not None else ""
            sert = bool(f.get("link_id")) and f.get("actif", True) is not False and not depart
            if pg.get("a_couper") or pg.get("a_rallumer") or sert != (pg.get("actif") is not False):
                # une coupure ou un rallumage à décider : la fiche RELUE, sous
                # le verrou de la page. La bascule en fond (liens_va.basculer →
                # EN_FOND → suivre_bascule) écrit la fiche AVANT de prendre ce
                # verrou : la fiche du cache, lue sur une page précédente du
                # même VA, faisait rallumer la page d'un VA que le manager
                # venait de désactiver (et re-couper celle d'un VA rallumé).
                f = fiches_vues[vrai] = lv.lien_de(g, vrai)
                sert = bool(f.get("link_id")) and f.get("actif", True) is not False and not depart
            if not sert:
                if pg.get("actif") is not False or pg.get("a_couper") or pg.get("a_rallumer"):
                    # le direct sert encore : c'est le départ du VA qui coupe
                    par_depart = bool(depart) and bool(f.get("link_id")) and f.get("actif", True) is not False
                    if par_depart:
                        if coupes_depart >= COUPURES_DEPART_PAR_PASSE:
                            bilan["departs_restent"] = int(bilan.get("departs_restent") or 0) + 1
                            continue
                        coupes_depart += 1
                    coupee = bool(gms.disable_link(lid).get("ok"))
                    if coupee:
                        _noter(g, uid, actif=False, a_couper=False, a_rallumer=False)
                        bilan["coupees"].append(uid)
                    else:
                        # comme suivre_bascule(False) : la reprise suivante recoupe
                        _noter(g, uid, a_couper=True, **({"a_rallumer": False} if par_depart else {}))
                        bilan["rates"].append(f"{uid} : coupure")
                    if par_depart:
                        bilan.setdefault("departs", []).append(f"{uid} : {depart}")
                        _log(f"page {pg.get('shortcode') or lid} de {cle} "
                             + ("coupée" if coupee else "NON coupée (refus GetMySocial, recoupée au passage suivant)")
                             + f" : VA parti ({depart}) ; son lien direct "
                             f"{f.get('shortcode') or f.get('link_id')} est encore en service — "
                             "hors des pages, à couper à la main")
                continue
            equipe = _equipe(g)
            manques = list(pg.get("manques") or [])
            essais = dict(pg.get("essais") or {}) if isinstance(pg.get("essais"), dict) else {}
            if f.get("tracking") and str(pg.get("tracking") or "") != str(f["tracking"]):
                if plafond_repointes is None:
                    if traitees >= PAGES_PAR_PASSE:
                        continue
                    traitees += 1
                else:
                    if repointees >= plafond_repointes:
                        continue
                    repointees += 1
                lu = _lire_page(lid, equipe)
                ofs = _boutons_of(lu.get("buttons"))
                if not ofs:
                    bilan["rates"].append(f"{uid} : page illisible, tracking non suivi")
                    continue
                if any(str(b.get("url") or "") != f["tracking"] for b in ofs):
                    pose = lv._poser_tracking(lid, f["tracking"], str(pg.get("nom") or ""), equipe)
                    if not pose.get("ok"):
                        bilan["rates"].append(f"{uid} : tracking ({pose.get('erreur')})")
                        continue
                # une autre model : la branche « Base … » de l'A/B est à refaire
                manques = sorted(set(manques) | {"pays"} | ({"70/30"} if ab_ici else set()))
                essais = {}
                _noter(g, uid, tracking=f["tracking"], manques=manques, essais={}, a_verifier=False,
                       **({"ab": {"ok": False}} if ab_ici else {}))
                pg = page_de(g, uid)    # ce qui est noté fait foi pour l'écriture de fin
                bilan["trackings"].append(uid)
            if pg.get("actif") is False or pg.get("a_rallumer"):
                if tickets_inconnus:
                    bilan.setdefault("rallumages_reportes", []).append(uid)
                    continue
                if gms.enable_link(lid).get("ok"):
                    _noter(g, uid, actif=True, a_rallumer=False)
                    bilan["rallumees"].append(uid)
                else:
                    _noter(g, uid, a_rallumer=True)
                    bilan["rates"].append(f"{uid} : rallumage")
                    continue
            plein = traitees >= PAGES_PAR_PASSE
            if plein and not ab_a_part:
                continue                # le reste au passage suivant (la boucle du podium attend)
            voulu = str(f.get("groupe") or f.get("manager") or "")
            if not plein and voulu and voulu != str(pg.get("groupe") or ""):
                traitees += 1
                rg = lv.ranger(equipe, lid, voulu)
                if rg:
                    _noter(g, uid, groupe=rg)
            restes, a_verifier, attend, differees = [], [], False, []
            if not ab_ici:
                # Twitter : « ça doit pas être 70 30 » (06/11) — une ancienne
                # étape 70/30 tombe, sans rien poser
                manques = [m for m in manques if m != "70/30"]
            elif not (pg.get("ab") or {}).get("ok") and "70/30" not in manques:
                # une page prête avant le 70/30 (ou dont la note s'est
                # perdue) : sans ça, la reprise ne la verrait jamais
                manques.append("70/30")
            # Sur un serveur à places fixes, une étape « à vérifier » est
            # retentée une fois par CREATION_REESSAI_S, comme une création :
            # trois 429 de suite sur une lecture figeaient le 70/30 pour
            # toujours (page à 100 % sur le tracking, sans geste possible).
            reessai = passageres_ici and bool(pg.get("a_verifier")) \
                and time.time() - float(pg.get("a_verifier_quand") or 0) >= CREATION_REESSAI_S
            for etape in manques:
                if int(essais.get(etape) or 0) >= ESSAIS_REPRISE and not reessai:
                    restes.append(etape)
                    a_verifier.append(etape)
                    continue
                if etape == "70/30":
                    if cookie is None:
                        cookie = _cookie_ok()
                    if not cookie or ab_tentes >= ab_max:
                        restes.append(etape)    # attend le cookie, ou le passage suivant : rien compté
                        attend = True
                        continue
                a_part = etape == "70/30" and ab_a_part
                if traitees >= PAGES_PAR_PASSE and not a_part:
                    restes.append(etape)
                    if passageres_ici:
                        differees.append(etape)     # pas tentée : ni ratée ni comptée
                    continue
                if not a_part:
                    traitees += 1
                compte, err = True, ""
                try:
                    if etape == "70/30":
                        ab_tentes += 1
                        ab = lv._poser_base_seule(g, uid, lien=_lien_ab(lid, f["tracking"], pg.get("shortcode")))
                        ok, compte = bool(ab.get("ok")), not ab.get("cookie")
                        err = str(ab.get("erreur") or "")
                        if ab.get("cookie"):
                            cookie = False      # refusé : les suivantes attendent aussi
                        _noter(g, uid, ab=_note_ab(ab))
                    elif etape == "pays":
                        rp = lv.poser_pays(lid, equipe)
                        ok, err = bool(rp.get("ok")), str(rp.get("erreur") or "")
                    elif etape == "safe page":
                        ru = gms.update_link(lid, {"display_name": str(pg.get("nom") or ""),
                                                   "bot_protection": {"mode": "safe_page"}}, equipe)
                        ok, err = bool(ru.get("ok")), str(ru.get("error") or "")
                    else:
                        ok = True                    # étape inconnue (ancienne fiche)
                except Exception as e:               # noqa: BLE001
                    _log(f"reprise {etape} de {cle} : {type(e).__name__}: {str(e)[:100]}")
                    ok, err = False, f"{type(e).__name__}: {e}"
                if not ok:
                    restes.append(etape)
                    if compte and passageres_ici and erreur_passagere(err):
                        compte = False          # panne passagère : refaite au passage suivant
                        bilan["passageres"].append(f"{uid} : {etape} ({err[:80]})")
                    if compte:
                        essais[etape] = int(essais.get(etape) or 0) + 1
            fin = {"manques": restes, "essais": essais, "a_verifier": bool(a_verifier),
                   "pays": "pays" not in restes}
            if passageres_ici and fin["a_verifier"] and not pg.get("a_verifier"):
                fin["a_verifier_quand"] = int(time.time())  # le réessai du lendemain part d'ici
            if ("a_verifier_quand" in fin or list(pg.get("manques") or []) != fin["manques"]
                    or (pg.get("essais") if isinstance(pg.get("essais"), dict) else {}) != fin["essais"]
                    or bool(pg.get("a_verifier")) != fin["a_verifier"] or pg.get("pays") != fin["pays"]):
                # écrit seulement si quelque chose change : le registre
                # entier était réécrit (copie .prev, fsync) pour chaque
                # page prête à chaque passage, dans la boucle du podium
                _noter(g, uid, **fin)
            if a_verifier:
                bilan["a_verifier"].append(f"{uid} : {a_verifier}")
            if attend:
                bilan["ab_en_attente"] += 1
            if manques and not restes:
                bilan["reprises"].append(uid)
            elif restes and set(restes) - set(a_verifier) - ({"70/30"} if attend else set()) - set(differees):
                bilan["rates"].append(f"{uid} : {restes}")
        except Exception as e:                               # noqa: BLE001
            bilan["rates"].append(f"{uid} : {type(e).__name__}: {str(e)[:80]}")
        finally:
            verrou.release()
    # Twitter : ni 70/30 ni panne passagère mise à part — ces deux clés,
    # toujours vides, s'ajoutaient à chaque ligne de son journal
    if not ab_ici and not bilan.get("ab_en_attente"):
        bilan.pop("ab_en_attente", None)
    if not passageres_ici and not bilan.get("passageres"):
        bilan.pop("passageres", None)
    if any(bilan.values()):
        _log(f"reprise des pages {gid} : {bilan}")
    if sur_demande(gid):
        try:
            lancer_creations(gid)
        except Exception as e:                               # noqa: BLE001
            _log(f"création des pages de {gid} non lancée : {type(e).__name__}: {e}")
    return bilan


# ─── Création automatique (serveurs à places fixes) ──────────────────────
#: Les créations par passage : une copie coûte une vingtaine d'appels
#: GetMySocial dont une dizaine d'écritures (copie, bouton relu, pays, safe
#: page, 70/30 avec sa copie temporaire, rangement, relecture), toutes sur la
#: clé principale. Le rattrapage d'un serveur entier (≈ 3 pages par VA)
#: s'étale donc sur plusieurs passages de la synchro (30 min).
CREATIONS_PAR_PASSE = 3
#: Au-delà, la place attend (« a_verifier » dans « creations », dit au journal
#: à chaque passage) — CREATION_REESSAI_S, puis un nouvel essai. Pour la
#: relancer tout de suite : retirer sa clé « gid:uid#n » de « creations »
#: dans data/pages_va.json. Une panne passagère (erreur_passagere) ne compte
#: pas.
ESSAIS_CREATION = 3
#: Une place « à vérifier » est retentée une fois par jour : une vraie panne
#: de GetMySocial ne la figeait plus pour toujours, sans geste possible
#: depuis Discord (seule une retouche du registre sur le VPS la relançait).
CREATION_REESSAI_S = 24 * 3600
#: Les demandes en attente dont on relit le message ✅ / ❌ par passage (un GET
#: Discord chacune) : un message supprimé laissait le VA « ⏳ » à vie.
DEMANDES_RELUES_PAR_PASSE = 25
#: Un seul lot de créations à la fois, sans jamais attendre : la synchro
#: (liens_va.synchroniser) tourne dans la boucle du podium, qui ne doit pas
#: rester bloquée une minute derrière 3 copies GetMySocial — d'où le fil, et
#: un verrou non bloquant (comme les 50/50 de web_upload, _variantes) : si le
#: lot d'avant tourne encore, ce passage-ci n'en lance pas un second.
_LOT_CREATIONS = threading.Lock()
#: Quand chaque demande en attente a vu son message relu (en mémoire : la
#: rotation repart du début après un redémarrage, sans gravité).
_RELUES: Dict[str, float] = {}


def _fil(f) -> None:
    threading.Thread(target=f, daemon=True, name="pages-va-creations").start()


#: Remplaçable par les tests (exécution sur place).
_FIL = _fil


def _creations(d: Dict[str, Any]) -> Dict[str, Any]:
    c = d.get("creations")
    if not isinstance(c, dict):
        c = d["creations"] = {}
    return c


def creation_a_verifier(gid: Any, uid: Any, n: int, d: Optional[Dict[str, Any]] = None) -> bool:
    """Cette place a épuisé ses essais de création automatique, il y a moins
    de CREATION_REESSAI_S."""
    x = ((d if d is not None else _lire()).get("creations") or {}).get(f"{gid}:{place(_vrai_uid(uid), n)}")
    return bool(isinstance(x, dict) and x.get("a_verifier")
                and time.time() - float(x.get("quand") or 0) < CREATION_REESSAI_S)


def _noter_creation(cle: str, ok: bool, erreur: str = "") -> Dict[str, Any]:
    """Le compteur d'essais de cette place. Rend la note, avec « ecrit » :
    faux si le registre a refusé l'écriture (le lot s'arrête alors)."""
    with _VERROU:
        d = _lire()
        c = _creations(d)
        if ok:
            c.pop(cle, None)
            x: Dict[str, Any] = {}
        else:
            x = c.get(cle) if isinstance(c.get(cle), dict) else {}
            x = dict(x, essais=int(x.get("essais") or 0) + 1, erreur=str(erreur)[:200],
                     quand=int(time.time()))
            x["a_verifier"] = x["essais"] >= ESSAIS_CREATION
            c[cle] = x
        ecrit = _ecrire(d)
    return dict(x, ecrit=ecrit)


def _va_du_serveur(gid: str) -> Dict[str, Dict[str, Any]]:
    """Les fiches de liens_va de ce serveur, par VA."""
    import liens_va as lv
    out: Dict[str, Dict[str, Any]] = {}
    for c, f in ((lv._etat().get("liens") or {}).items()):
        g, _s, u = str(c).partition(":")
        if g == gid and u and isinstance(f, dict):
            out[u] = f
    return out


def etat_place(gid: Any, uid: Any, n: int, d: Optional[Dict[str, Any]] = None,
               hors_service: str = "") -> Tuple[str, str]:
    """Ce que montre le menu pour la place n de ce VA : (« prete », adresse),
    (« coupee », adresse), (« en_preparation », « »), (« a_reprendre », « »),
    ou, quand le VA est hors service (`hors_service` : la raison
    d'en_service) et que la place n'a pas de page prête, (« coupee », « »)
    pour un lien coupé ou un VA parti, (« sans_lien », « ») pour un lien ou
    une fiche incomplets — rien ne s'y préparera ni ne s'y reprendra (le lot
    l'écarte), « ⏳ » ou « ⚠️ à reprendre » mentiraient. Seul endroit qui le
    décide. `d` : le registre déjà lu."""
    d = d if d is not None else _lire()
    pg = (d.get("pages") or {}).get(f"{gid}:{place(_vrai_uid(uid), n)}")
    pg = pg if isinstance(pg, dict) else {}
    hors = ("coupee" if hors_service in ("coupe", "parti") else "sans_lien") if hors_service else ""
    if pg.get("link_id"):
        etat = pg.get("etat", "prete")
        if etat == "prete":
            return ("coupee" if pg.get("actif", True) is False else "prete"), str(pg.get("public_url") or "")
        if hors:
            return hors, ""
        if etat == "ratee":
            return "a_reprendre", ""
        return "en_preparation", ""                    # en_cours : la copie se fait
    if hors:
        return hors, ""
    return ("a_reprendre" if creation_a_verifier(gid, uid, n, d) else "en_preparation"), ""


def balayer_demandes(gid: str, tickets: Dict[str, Any]) -> Dict[str, Any]:
    """Les demandes en attente que plus aucun bouton ne peut trancher,
    annulées (le VA retrouve ➕) et dites : message jamais posé (redémarrage
    entre la note et le POST), message supprimé (relu, 404), ticket refait
    (autre salon), VA parti. `tickets` : l'état des tickets déjà lu. Ne lève
    pas."""
    import tickets_discord as tk
    gid = str(gid)
    bilan: Dict[str, Any] = {"annulees": [], "relues": 0}
    a_relire: List[Tuple[str, Dict[str, Any]]] = []
    for did, x in list((_lire().get("demandes") or {}).items()):
        if not (isinstance(x, dict) and str(x.get("gid")) == gid and x.get("etat") == "attente"):
            continue
        uid = str(x.get("uid") or "")
        t = tickets.get(f"{gid}:{uid}") if isinstance(tickets.get(f"{gid}:{uid}"), dict) else {}
        raison = ""
        if _sans_message_depuis_trop(x):
            raison = "message jamais posé (redémarrage ?)"
        elif not x.get("message"):
            continue                    # le fil le pose en ce moment
        elif t.get("parti"):
            raison = "VA parti"
        elif t.get("salon") and str(t["salon"]) != str(x.get("salon") or ""):
            raison = "ticket refait (autre salon)"
        else:
            a_relire.append((str(did), x))
            continue
        if annuler_demande(did, raison):
            bilan["annulees"].append(f"{uid} : {raison}")
            _menu_a_jour(gid, uid)
    a_relire.sort(key=lambda dx: _RELUES.get(dx[0], 0.0))
    for did, x in a_relire[:DEMANDES_RELUES_PAR_PASSE]:
        _RELUES[did] = time.time()
        bilan["relues"] += 1
        try:
            import verif_discord as vd
            with vd.sur_serveur(gid):
                code, _r = tk._api_reseau("GET", f"/channels/{x.get('salon')}/messages/{x.get('message')}")
        except Exception as e:                               # noqa: BLE001
            _log(f"demande {did} : message non relu ({type(e).__name__}: {e})")
            continue
        # 404 seulement (message ou salon inconnus) : une panne, un 403 ou un
        # 429 ne disent pas que le message a disparu
        if code == 404 and annuler_demande(did, "message disparu (supprimé ?)"):
            bilan["annulees"].append(f"{x.get('uid')} : message disparu")
            _menu_a_jour(gid, str(x.get("uid") or ""))
    for did in [k for k in _RELUES if k not in dict(a_relire)]:
        _RELUES.pop(did, None)
    if bilan["annulees"]:
        _log(f"demandes de pages {gid} sans réponse possible, annulées : {bilan['annulees']}")
    return bilan


def _registre_ecrit() -> bool:
    """Le registre s'écrit-il ? Relu et réécrit tel quel sous _VERROU (jamais
    un instantané plus vieux : il écraserait un ✅ tranché entre-temps)."""
    with _VERROU:
        return _ecrire(_lire())


def _pause_ecritures() -> int:
    """Secondes de pause des écritures GetMySocial (0 : libre)."""
    import gms
    try:
        return int(gms.pause_restante("ecriture") or 0)
    except Exception as e:                                   # noqa: BLE001
        _log(f"pause GetMySocial illisible : {type(e).__name__}: {e}")
        return 0


def _noter_passagere(cle: str, erreur: str) -> None:
    """Une panne passagère propre à cette place (pas de tout le compte) :
    l'heure notée, AUCUN essai compté — le lot suivant la passe après les
    places jamais en panne (rotation), au lieu de la retenter en tête."""
    with _VERROU:
        d = _lire()
        c = _creations(d)
        x = c.get(cle) if isinstance(c.get(cle), dict) else {}
        c[cle] = dict(x, passagere_quand=int(time.time()), passagere=str(erreur)[:200])
        _ecrire(d)


#: Les messages de demande (pages acceptées) dont le PATCH de l'adresse est
#: refait par passage : un seul 500 ou 429 de Discord au clic ✅ laissait le
#: message « — page 4 en création » pour toujours, sans adresse.
MESSAGES_REPRIS_PAR_PASSE = 5
#: Au-delà, le message n'est plus retenté (supprimé, salon fermé) : dit une fois.
MESSAGE_ESSAIS_MAX = 3


def creer_pages_manquantes(gid: str) -> Dict[str, Any]:
    """Les places de chaque VA en service (en_service) qui n'ont pas encore de
    page prête : les places fixes, et les pages acceptées dont la copie a
    raté ou n'a pas eu lieu (redémarrage). Les pages acceptées d'abord (un
    manager les a voulues), puis place par place (la page 1 de chacun avant
    la page 2 de personne). CREATIONS_PAR_PASSE au plus, chaque place
    ESSAIS_CREATION fois au plus (puis une fois par CREATION_REESSAI_S) ; une
    panne passagère de tout le compte GetMySocial (quota, 429, budget) arrête
    le lot sans rien compter ; celle d'une seule place ne compte pas non
    plus, et le lot passe à la suivante (rotation : elle repart derrière) ;
    un registre qui refuse l'écriture l'arrête aussi. Un VA coupé ou parti
    PENDANT le lot n'est pas un essai (« ignores »). Une page ratée ne bloque
    pas les autres. Balaie d'abord les demandes sans réponse possible ;
    refait ensuite le message d'une demande resté « en création ». Rend un
    bilan ; ne lève pas."""
    gid = str(gid)
    bilan: Dict[str, Any] = {"creees": [], "ratees": [], "a_verifier": [], "restent": 0,
                             "passageres": [], "ignores": {"sans_lien": 0, "coupe": 0, "parti": 0}}
    if not sur_demande(gid) or not PILOTE.get(gid):
        return bilan
    vas = _va_du_serveur(gid)
    try:
        import tickets_discord as tk
        etat_tk = tk._etat()
        tickets = etat_tk.get("tickets") if isinstance(etat_tk, dict) else None
        if not isinstance(tickets, dict) and vas:
            # tk._etat rend {} sur un fichier (et son .prev) illisible : sans
            # ce contrôle, personne n'était « parti »
            raise ValueError("état des tickets vide ou illisible")
        tickets = tickets if isinstance(tickets, dict) else {}
        disparus = etat_tk.get("tickets_disparus") if isinstance(etat_tk, dict) else None
        disparus = disparus if isinstance(disparus, dict) else {}
    except Exception as e:                                   # noqa: BLE001
        # sans savoir qui est parti, ne rien créer : une page vivante sur le
        # tracking d'un VA parti serait pire qu'un passage sauté
        _log(f"pages de {gid} : tickets illisibles ({type(e).__name__}: {e}), aucune création ce passage")
        bilan["erreur"] = "tickets illisibles"
        return bilan
    try:
        bilan["demandes"] = balayer_demandes(gid, tickets)
    except Exception as e:                                   # noqa: BLE001
        _log(f"demandes de pages {gid} non balayées : {type(e).__name__}: {e}")
    a_faire: List[Tuple[int, int, float, str]] = []
    servis: set = set()
    reg = _lire()                       # un instantané pour le tour : relu par creer_page ensuite
    for uid, f in sorted(vas.items()):
        # sans ticket vivant : « parti » si sa fiche rangée porte « parti », ou
        # s'il n'en a nulle part (depart_du_va, la règle de la reprise aussi)
        sert, raison = en_service(gid, uid, fiche=f, ticket=tickets.get(f"{gid}:{uid}") or {},
                                  disparu=disparus.get(f"{gid}:{uid}") or {})
        if not sert:
            bilan["ignores"][raison] = bilan["ignores"].get(raison, 0) + 1
            continue
        servis.add(uid)
        for n in places(gid, uid, reg):
            pg = reg["pages"].get(f"{gid}:{place(uid, n)}")
            pg = pg if isinstance(pg, dict) else {}
            if pg.get("link_id") and pg.get("etat", "prete") in ("prete", "en_cours"):
                continue            # prête, ou en cours (la reprise coupe une création interrompue)
            if creation_a_verifier(gid, uid, n, reg):
                bilan["a_verifier"].append(place(uid, n))
                continue
            x = (reg.get("creations") or {}).get(f"{gid}:{place(uid, n)}")
            pq = float(x.get("passagere_quand") or 0) if isinstance(x, dict) else 0.0
            # (priorité, place, dernière panne passagère, VA) : à place égale,
            # une place restée en panne passe derrière les autres
            a_faire.append((0 if modifiable(gid, n) else 1, n, pq, uid))
    pause = _pause_ecritures() if a_faire else 0
    if pause:
        # rien ne passerait : ni essai compté, ni copie tentée
        bilan["restent"] = len(a_faire)
        bilan["passageres"].append(f"quota des écritures GetMySocial, reprise dans {pause // 60} min")
        a_faire = []
    elif a_faire and not _registre_ecrit():
        # le registre refuse d'écrire (disque plein, droits) : une copie
        # créée serait inconnue de lui, donc refaite à chaque passage
        bilan["restent"] = len(a_faire)
        bilan["erreur"] = "registre non écrit"
        a_faire = []
    faites = 0
    ecartes: set = set()
    for i, (_prio, n, _pq, uid) in enumerate(sorted(a_faire)):
        cle = f"{gid}:{place(uid, n)}"
        if faites >= CREATIONS_PAR_PASSE:
            bilan["restent"] += 1
            continue
        if uid in ecartes:
            continue                # coupé ou parti pendant ce lot : déjà compté
        with _VERROU:
            en_cours = cle in _CREATIONS
        if en_cours:
            continue                # un clic la crée en ce moment
        if i and _pause_ecritures():
            bilan["restent"] += len(a_faire) - i
            bilan["passageres"].append("quota des écritures GetMySocial")
            break
        faites += 1
        try:
            r = creer_page(gid, uid, par="auto", n=n)
        except Exception as e:                               # noqa: BLE001
            r = {"ok": False, "erreur": f"{type(e).__name__}: {str(e)[:120]}"}
        if r.get("ok"):
            _noter_creation(cle, True)
            bilan["creees"].append(place(uid, n))
            _apres_creation(gid, uid, n, str(r.get("url") or ""))
            continue
        if r.get("erreur") == "création déjà en cours":
            faites -= 1             # rien tenté : ni essai ni place du plafond
            continue
        if r.get("hors_service"):
            # coupé (« 🚫 Désactiver »), parti ou fiche retouchée APRÈS la
            # lecture du début du lot : creer_page a refusé sans rien copier.
            # Ce n'est pas un essai raté (3 essais et « à reprendre » à la
            # réactivation), ni une place du lot.
            faites -= 1
            ecartes.add(uid)
            raison = str(r["hors_service"])
            bilan["ignores"][raison] = bilan["ignores"].get(raison, 0) + 1
            _log(f"création de {place(uid, n)} sur {gid} : VA devenu hors service pendant le lot ({raison}), "
                 "ses places attendent")
            continue
        if r.get("disque"):
            bilan["erreur"] = "registre non écrit"
            bilan["restent"] += len(a_faire) - i        # la copie est coupée : sa place reste à faire
            break
        if erreur_passagere(r.get("erreur")):
            bilan["passageres"].append(f"{place(uid, n)} : {str(r.get('erreur'))[:100]}")
            if panne_globale(r.get("erreur")):
                # tout le compte GetMySocial : les suivantes échoueraient pareil
                bilan["restent"] += len(a_faire) - i
                break
            # cette place seule (un 502 sur son bouton, une page Cloudflare) :
            # ni essai ni arrêt du lot, elle repart derrière au tour suivant
            _noter_passagere(cle, str(r.get("erreur") or ""))
            bilan["restent"] += 1
            continue
        x = _noter_creation(cle, False, str(r.get("erreur") or "?"))
        bilan["ratees"].append(f"{place(uid, n)} : {r.get('erreur')}")
        if x.get("a_verifier"):
            bilan["a_verifier"].append(place(uid, n))
        if not x.get("ecrit"):
            bilan["erreur"] = "registre non écrit"
            bilan["restent"] += len(a_faire) - i - 1
            break
    try:
        refaits = _reprendre_messages(gid, servis)
        if refaits:
            bilan["messages"] = refaits
    except Exception as e:                                   # noqa: BLE001
        _log(f"messages de demande de {gid} non repris : {type(e).__name__}: {e}")
    if (bilan["creees"] or bilan["ratees"] or bilan["a_verifier"] or bilan["passageres"]
            or bilan.get("erreur") or bilan.get("messages") or any(bilan["ignores"].values())):
        # les VA écartés sont dits à chaque passage (« ne jamais écarter en
        # silence »), même quand rien d'autre n'a eu lieu
        _log(f"création des pages {gid} : créées {bilan['creees']}, ratées {bilan['ratees'][:5]}, "
             f"à vérifier {bilan['a_verifier'][:10]}, restent {bilan['restent']}, "
             f"en attente {bilan['passageres'][:3]}, VA écartés {bilan['ignores']}"
             + (f", messages de demande refaits {bilan['messages']}" if bilan.get("messages") else "")
             + (f", ERREUR {bilan['erreur']}" if bilan.get("erreur") else ""))
    return bilan


def _reprendre_messages(gid: str, servis: set) -> List[str]:
    """Les demandes acceptées dont la page est prête mais dont le message ne
    porte pas encore l'adresse (PATCH raté au clic ✅) : refait,
    MESSAGES_REPRIS_PAR_PASSE au plus, MESSAGE_ESSAIS_MAX fois chacun. Le fil
    du clic a DEMANDE_SANS_MESSAGE_S pour le faire lui-même (sa réponse type 7
    doit passer avant). Seulement les VA en service. Rend ce qui a été tenté."""
    d = _lire()
    faits: List[str] = []
    candidates = sorted(((did, x) for did, x in _demandes(d).items() if isinstance(x, dict)),
                        key=lambda dx: float(dx[1].get("decide_quand") or 0))
    for did, x in candidates:
        if len(faits) >= MESSAGES_REPRIS_PAR_PASSE:
            break
        if not (str(x.get("gid")) == gid and x.get("etat") == "acceptee" and x.get("salon")
                and x.get("message") and not x.get("message_maj")):
            continue
        uid = str(x.get("uid") or "")
        if uid not in servis or int(x.get("message_essais") or 0) >= MESSAGE_ESSAIS_MAX:
            continue
        if time.time() - float(x.get("decide_quand") or 0) < DEMANDE_SANS_MESSAGE_S:
            continue
        try:
            n = int(x.get("place") or 0)
        except (TypeError, ValueError):
            continue
        pg = (d.get("pages") or {}).get(f"{gid}:{place(uid, n)}")
        if not (isinstance(pg, dict) and pg.get("link_id") and pg.get("etat", "prete") == "prete"):
            continue                    # pas encore créée : _apres_creation s'en chargera
        code = _maj_message_de_place(gid, uid, n, str(pg.get("public_url") or ""), dict(x, id=str(did)))
        faits.append(f"{place(uid, n)} : HTTP {code}")
        if code != 200:
            essais = noter_message_rate(str(did))
            if essais >= MESSAGE_ESSAIS_MAX:
                _log(f"demande {did} : message de {place(uid, n)} jamais mis à jour ({essais} essais, "
                     f"HTTP {code}) — plus retenté, l'adresse est dans le menu du ticket")
    return faits


def _maj_message_de_place(gid: str, uid: str, n: int, url: str, x: Dict[str, Any]) -> int:
    """Le message de la demande `x` ({salon, message, decide_par, id}) prend
    l'adresse de la page n ; noté (message_maj) s'il est passé. Rend le code
    HTTP (0 : exception, dite)."""
    try:
        import tickets_discord as tk
        import verif_discord as vd
        with vd.sur_serveur(gid):
            code = tk.maj_message_demande(uid, x, n, url)
    except Exception as e:                                   # noqa: BLE001
        _log(f"demande {x.get('id')} : message non mis à jour : {type(e).__name__}: {e}")
        return 0
    if code == 200:
        noter_message_maj(str(x["id"]))
    else:
        _log(f"demande {x.get('id')} : message non mis à jour (HTTP {code})")
    return int(code or 0)


def _apres_creation(gid: str, uid: str, n: int, url: str) -> None:
    """Une page créée par la reprise : le menu du ticket la montre, et le
    message de sa demande (page acceptée) prend son adresse — sinon, après
    un redémarrage pendant la copie, il disait « en création » à vie."""
    _menu_a_jour(gid, uid)
    if not modifiable(gid, n):
        return
    x = demande_de_place(gid, uid, n)
    if not (x.get("salon") and x.get("message")) or x.get("message_maj"):
        return
    _maj_message_de_place(gid, uid, n, url, x)


def _menu_a_jour(gid: str, uid: str) -> None:
    """Le menu du ticket montre l'adresse aussitôt (sinon au tour suivant)."""
    try:
        import tickets_discord as tk
        import verif_discord as vd
        with vd.sur_serveur(gid):
            tk._maj_menu_v2(gid, uid)
    except Exception as e:                                   # noqa: BLE001
        _log(f"menu de {gid}:{uid} non remis à jour : {type(e).__name__}: {e}")


def lancer_creations(gid: str) -> str:
    """creer_pages_manquantes en fond, un lot à la fois. Rend « lancee »,
    « occupee » (le lot d'avant tourne encore) ou « rien »."""
    gid = str(gid)
    if not sur_demande(gid) or not PILOTE.get(gid):
        return "rien"
    if not _LOT_CREATIONS.acquire(blocking=False):
        _log(f"création des pages {gid} : le lot d'avant tourne encore, rien de lancé")
        return "occupee"

    def travail() -> None:
        try:
            creer_pages_manquantes(gid)
        except Exception as e:                               # noqa: BLE001
            _log(f"création des pages {gid} : {type(e).__name__}: {e}")
        finally:
            _LOT_CREATIONS.release()
    try:
        _FIL(travail)
    except Exception:
        _LOT_CREATIONS.release()
        raise
    return "lancee"


# ─── Pays riches d'Europe sur les pages (06/11/2026) ──────────────────────
# liens_va.PAYS_EN_PLUS (Twitter et Instagram) : une page posée avec l'ancienne
# liste reprend l'étape « pays » (son bouton OnlyFans), une fois par liste ;
# la reprise ci-dessus la refait (ESSAIS_REPRISE, puis « a_verifier »).
_reprendre_pages_sans_liste = reprendre_pages


def _marquer_liste_pays(gid: str) -> List[str]:
    import liens_va as lv
    gid = str(gid)
    if lv._cibles_pays_sans_serveur() is None:
        return []       # (aussi hors PAYS_EN_PLUS : un serveur retiré revient à la liste de base)
    voulu, avant = lv.signature_pays(gid), lv.signature_pays_avant()
    marques: List[str] = []
    for cle, pg in list((_lire().get("pages") or {}).items()):
        g, _s, uid = str(cle).partition(":")
        if g != gid or not isinstance(pg, dict) or not pg.get("link_id") or pg.get("etat", "prete") != "prete":
            continue
        posee = pg.get("pays_cibles") or (lv._POSES_PAYS.get(str(pg["link_id"]))
                                          if "pays" not in (pg.get("manques") or []) else None)
        if posee == voulu and not pg.get("pays_cibles"):
            _noter(g, uid, pays_cibles=voulu)     # posée par ce processus : notée, rien à refaire
            continue
        if str(posee or avant) == voulu or pg.get("pays_liste_due") == voulu:
            continue
        # verrou NON bloquant, comme la reprise : une page tenue (création au
        # clic, bascule, modification) faisait attendre la boucle du podium ;
        # elle est revue au passage suivant
        v = _verrou_page(cle)
        if not v.acquire(blocking=False):
            continue
        try:
            pg = page_de(g, uid)
            essais = dict(pg.get("essais") or {}) if isinstance(pg.get("essais"), dict) else {}
            essais.pop("pays", None)
            # sans « a_verifier=False » : la reprise le recalcule des essais à la
            # fin du passage ; l'écrire ici sautait le réessai à 24 h d'un 70/30
            # « à vérifier » et remettait son horloge à zéro
            _noter(g, uid, manques=sorted(set(pg.get("manques") or []) | {"pays"}), essais=essais,
                   pays=False, pays_liste_due=voulu)
        finally:
            v.release()
        marques.append(uid)
    if marques:
        _log(f"pays {gid} : {len(marques)} page(s) à reposer avec la nouvelle liste")
    return marques


def _noter_liste_pays(gid: str) -> None:
    for cle, pg in list((_lire().get("pages") or {}).items()):
        g, _s, uid = str(cle).partition(":")
        if (g == str(gid) and isinstance(pg, dict) and pg.get("pays_liste_due")
                and "pays" not in (pg.get("manques") or [])):
            v = _verrou_page(cle)
            if not v.acquire(blocking=False):
                continue                    # tenue : notée au passage suivant (pays_liste_due reste)
            try:
                due = page_de(g, uid).get("pays_liste_due")
                if due:
                    _noter(g, uid, pays_cibles=due, pays_liste_due="")
            finally:
                v.release()


def reprendre_pages(gid: str) -> Dict[str, Any]:   # noqa: F811
    try:
        _marquer_liste_pays(gid)
    except Exception as e:                                   # noqa: BLE001
        _log(f"pays {gid} : liste des pages non comparée ({type(e).__name__}: {e})")
    b = _reprendre_pages_sans_liste(gid)
    try:
        _noter_liste_pays(gid)
    except Exception as e:                                   # noqa: BLE001
        _log(f"pays {gid} : liste posée des pages non notée ({type(e).__name__}: {e})")
    return b


reprendre_pages.__doc__ = _reprendre_pages_sans_liste.__doc__


# ─── Le look de la page : brune, blonde, général (TRUST TWITTER, 06/11/2026) ──
# Propriétaire : « quand ils cliquent sur modifier [...] ils peuvent choisir
# leur template [...] template brune, template blonde, [...] et après ils
# peuvent modifier par eux-mêmes comme ils le veulent, mais ils ont toujours
# une seule page en safe page sur Twitter » ; « Template » renommé « Général ».
# Les trois gabarits de TRUST INSTAGRAM (tpligbrune1, tpligblonde2,
# tpligtemplate3) ne diffèrent que par la photo et le fond : seules ces deux
# images changent (adresses recopiées ici, leurs liens ne sont jamais lus ni
# touchés) ; nom, bio, boutons, tracking, pays, safe page, Telegram restent.
_IMG = "https://images.getmysocial.com/68e4961d3abdf07547f50bd7"
_SLIDES = "https://images.getmysocial.com/profile-slides/68e4961d3abdf07547f50bd7"
#: (clé, emoji, libellé, photo, fond)
LOOKS: Dict[str, Tuple[Tuple[str, str, str, str, str], ...]] = {TWITTER_ID: (
    ("brune", "🟤", "Brune", f"{_IMG}/1793965144979-b1e1240d04e3.jpg", f"{_IMG}/1793965144944-e832f9bc389f.jpg"),
    ("blonde", "🟡", "Blonde", f"{_SLIDES}/1793971762887-6260dbacfdec.jpg", f"{_IMG}/1793971762889-7786fb4455fa.jpg"),
    ("general", "✨", "Général", f"{_SLIDES}/1793971989305-788e7bcfed60.jpg", f"{_IMG}/1793971990377-6691d940790e.jpg"),
)}


def looks(gid: Any) -> Tuple[Tuple[str, str, str, str, str], ...]:
    return LOOKS.get(str(gid or ""), ())


def _poser_look_lien(lid: str, equipe: str, photo: str, fond: str) -> Dict[str, Any]:
    """Photo + fond d'un look sur une page ; relue (images posées, bouton
    OnlyFans intact). Rend {ok, erreur}."""
    import gms
    lu = _lire_page(lid, equipe)
    if not lu:
        return {"ok": False, "erreur": "page illisible chez GetMySocial"}
    avant = [(b.get("url"), len(b.get("geofilters") or [])) for b in _boutons_of(lu.get("buttons"))]
    # la diapo de profil vidée : une ancienne diapo restait affichée à la place
    # de la nouvelle photo (essai du 06/11 sur sugarlilyy) ; les pages vivantes
    # n'en ont pas, et la photo déposée par le VA (fenêtre) ne la touche pas
    r = gms.update_link(lid, {"display_name": str(lu.get("display_name") or ""),
                              "profile_picture": photo, "profile_picture_slides": [],
                              "background_image": fond}, equipe)
    if not r.get("ok"):
        return {"ok": False, "erreur": str(r.get("error") or "GetMySocial a refusé")[:140]}
    l2 = _lire_page(lid, equipe)
    apres = [(b.get("url"), len(b.get("geofilters") or [])) for b in _boutons_of(l2.get("buttons"))]
    if (str(l2.get("profile_picture") or "") != photo or str(l2.get("background_image") or "") != fond
            or l2.get("profile_picture_slides")):
        return {"ok": False, "erreur": "relue sans le nouveau look"}
    if apres != avant:
        # jamais vu : dit, plutôt qu'un « ✅ » sur un bouton changé
        _log(f"look de {lid} : bouton OnlyFans changé ({avant} → {apres})")
        return {"ok": False, "erreur": "bouton OnlyFans changé à la relecture : prévenir un manager"}
    return {"ok": True, "erreur": ""}


def appliquer_look(gid: str, uid: str, cle: str, n: int = 1) -> Dict[str, Any]:
    """Le look `cle` sur la page n du VA, sous le verrou de la page."""
    gid = str(gid)
    choix = {x[0]: x for x in looks(gid)}
    if cle not in choix:
        return {"ok": False, "erreur": "look inconnu"}
    if not modifiable(gid, n):
        # la même garde que modifier_page : un appel direct ou une tâche de
        # fond ne doit jamais changer une place fixe (si LOOKS s'ouvre un jour
        # à TRUST INSTAGRAM)
        return {"ok": False, "erreur": "page fixe : elle ne se modifie pas"}
    u = place(_vrai_uid(uid), n)
    with _verrou_page(f"{gid}:{u}"):
        pg = page_de(gid, u)
        if not pg.get("link_id") or pg.get("etat", "prete") != "prete":
            return {"ok": False, "erreur": "pas de page"}
        _c, _e, libelle, photo, fond = choix[cle]
        r = _poser_look_lien(str(pg["link_id"]), _equipe(gid), photo, fond)
        if r.get("ok"):
            _noter(gid, u, look=cle)
            _log(f"page {pg.get('shortcode')} de {gid}:{u} : look {libelle}")
        return dict(r, libelle=libelle)
