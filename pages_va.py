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
#: pages de dispo » — repris par une autre session (pages fixes + demandes) :
#: ni PILOTE ni GABARIT_PAGE ici tant qu'elle n'a pas fini.
PILOTE: Dict[str, set] = {TWITTER_ID: {"*"}}
#: Combien de pages par VA (« pour Twitter 1 page directe et une safe » : le
#: lien direct + 1 page ; Instagram : 3 pages).
PAGES_MAX: Dict[str, int] = {TWITTER_ID: 1, AGENCY_IG_ID: 3}
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
GABARIT_PAGE: Dict[str, str] = {TWITTER_ID: "lnk_6aed1548c7881b6c805e773a"}

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


def ouverte(gid: Any, uid: Any) -> bool:
    membres = PILOTE.get(str(gid or ""), set())
    return bool(GABARIT_PAGE.get(str(gid or ""))) and ("*" in membres or str(uid).split("#")[0] in membres)


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


def pages_max(gid: Any) -> int:
    return int(PAGES_MAX.get(str(gid or ""), 1))


def _vrai_uid(uid: Any) -> str:
    return str(uid).split("#", 1)[0]


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


def _noter(gid: Any, uid: Any, **champs) -> None:
    with _VERROU:
        d = _lire()
        p = d["pages"].setdefault(f"{gid}:{uid}", {})
        for k, v in champs.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict) and k not in _REMPLACES:
                p[k] = dict(p[k], **v)
            else:
                p[k] = v
        _ecrire(d)


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
    """La page du VA : copie du gabarit, bouton sur SON tracking, pays, safe
    page (pas d'A/B), rangée chez son manager. Rend {ok, url, erreur, deja}.
    Un échec après la copie la laisse COUPÉE (jamais supprimée), dite."""
    import gms
    import liens_va as lv
    gid, vrai = str(gid), _vrai_uid(uid)
    n = int(n or 1)
    if n > pages_max(gid):
        return {"ok": False, "erreur": f"{pages_max(gid)} page(s) au plus ici"}
    uid = place(vrai, n)
    cle = f"{gid}:{uid}"
    deja = page_de(gid, uid)
    if deja.get("link_id") and deja.get("etat", "prete") == "prete":
        return {"ok": True, "deja": True, "url": deja.get("public_url", ""), "erreur": "",
                "manques": list(deja.get("manques") or [])}
    gab = GABARIT_PAGE.get(gid, "")
    if not gab:
        return {"ok": False, "erreur": "pas de gabarit de page sur ce serveur"}
    f = lv.lien_de(gid, vrai)
    if not (f.get("link_id") and f.get("tracking") and f.get("public_url")):
        return {"ok": False, "erreur": "il faut d'abord son lien direct (avec son tracking)"}
    if f.get("actif", True) is False:
        # la copie naîtrait coupée et le VA recevrait « ✅ » avec une adresse morte
        return {"ok": False, "erreur": "son lien direct est désactivé"}
    if not (str(f.get("numero") or "").isdigit() and str(f.get("pseudo") or "").strip()):
        # « Twitter VA None @None page » : le registre des trackings y verrait
        # une 2e personne sur son tracking (« en doute », sans relevé)
        return {"ok": False, "erreur": "numéro ou pseudo du VA manquant dans sa fiche"}
    if n > 1 and page_de(gid, place(vrai, n - 1)).get("etat") != "prete":
        return {"ok": False, "erreur": f"crée d'abord la page {n - 1}"}
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
    lid, sc, erreur = "", "", ""
    for essai in range(lv.ESSAIS_ADRESSE):
        sc = lv.mots_sans_prenom(nom, essai)
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
    _noter(gid, uid, link_id=lid, shortcode=sc, public_url=url, nom=nom, par=str(par),
           quand=int(time.time()), actif=True, etat="en_cours")
    try:
        return _finir_page(gid, uid, f, lid, sc, nom, url, equipe)
    except Exception as e:                               # noqa: BLE001
        _couper(gid, uid, lid, etat="ratee", erreur=f"{type(e).__name__}: {str(e)[:120]}")
        _log(f"page {sc} de {cle} : {type(e).__name__}: {e} — coupée")
        return {"ok": False, "erreur": f"{type(e).__name__} : page coupée"}


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
    # Propriétaire, 06/11 : « ça doit pas être 70 30 » — la page n'a pas
    # d'A/B : tout le bouton sur le tracking du VA.
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
    manques = ([] if pays.get("ok") else ["pays"]) + ([] if sur.get("ok") else ["safe page"])
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
           tracking=f["tracking"])
    _log(f"page {sc} prête pour {cle}" + (f", à reprendre : {manques}" if manques else ""))
    return {"ok": True, "url": url, "erreur": "", "manques": manques}


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


def reprendre_pages(gid: str) -> Dict[str, Any]:
    """Les pages de ce serveur, remises d'aplomb sur leur lien direct :
      - une page ratée, ou une création interrompue, encore vivante : coupée ;
      - une page prête : coupée si le direct l'est, rallumée s'il sert ;
        son bouton re-pointé si le tracking du direct a changé (changement de
        model, passer_sur) — le tracking n'est noté qu'une fois le bouton
        relu dessus —, puis les pays refaits ; rangée chez le manager
        actuel ; les étapes manquées refaites, ESSAIS_REPRISE fois chacune ;
      - les pages temporaires d'images non supprimées : supprimées.
    PAGES_PAR_PASSE pages au plus. Ne lève pas."""
    import gms
    import liens_va as lv
    bilan: Dict[str, Any] = {"coupees": [], "rallumees": [], "trackings": [], "reprises": [],
                             "rates": [], "a_verifier": []}
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
        try:
            with _verrou_page(cle):
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
                f = lv.lien_de(g, _vrai_uid(uid))
                sert = bool(f.get("link_id")) and f.get("actif", True) is not False
                if not sert:
                    if pg.get("actif") is not False or pg.get("a_couper") or pg.get("a_rallumer"):
                        if gms.disable_link(lid).get("ok"):
                            _noter(g, uid, actif=False, a_couper=False, a_rallumer=False)
                            bilan["coupees"].append(uid)
                        else:
                            _noter(g, uid, a_couper=True)
                            bilan["rates"].append(f"{uid} : coupure")
                    continue
                equipe = _equipe(g)
                manques = list(pg.get("manques") or [])
                essais = dict(pg.get("essais") or {}) if isinstance(pg.get("essais"), dict) else {}
                if f.get("tracking") and str(pg.get("tracking") or "") != str(f["tracking"]):
                    if traitees >= PAGES_PAR_PASSE:
                        continue
                    traitees += 1
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
                    manques = sorted(set(manques) | {"pays"})
                    essais = {}
                    _noter(g, uid, tracking=f["tracking"], manques=manques, essais={}, a_verifier=False)
                    bilan["trackings"].append(uid)
                if pg.get("actif") is False or pg.get("a_rallumer"):
                    if gms.enable_link(lid).get("ok"):
                        _noter(g, uid, actif=True, a_rallumer=False)
                        bilan["rallumees"].append(uid)
                    else:
                        _noter(g, uid, a_rallumer=True)
                        bilan["rates"].append(f"{uid} : rallumage")
                        continue
                if traitees >= PAGES_PAR_PASSE:
                    continue                # le reste au passage suivant (la boucle du podium attend)
                voulu = str(f.get("groupe") or f.get("manager") or "")
                if voulu and voulu != str(pg.get("groupe") or ""):
                    traitees += 1
                    rg = lv.ranger(equipe, lid, voulu)
                    if rg:
                        _noter(g, uid, groupe=rg)
                restes, a_verifier = [], []
                # « ça doit pas être 70 30 » (06/11) : une ancienne étape 70/30 tombe
                manques = [m for m in manques if m != "70/30"]
                for etape in manques:
                    if int(essais.get(etape) or 0) >= ESSAIS_REPRISE:
                        restes.append(etape)
                        a_verifier.append(etape)
                        continue
                    if traitees >= PAGES_PAR_PASSE:
                        restes.append(etape)
                        continue
                    traitees += 1
                    compte = True
                    try:
                        if etape == "pays":
                            ok = bool(lv.poser_pays(lid, equipe).get("ok"))
                        elif etape == "safe page":
                            ok = bool(gms.update_link(lid, {"display_name": str(pg.get("nom") or ""),
                                                            "bot_protection": {"mode": "safe_page"}},
                                                      equipe).get("ok"))
                        else:
                            ok = True                    # étape inconnue (ancienne fiche)
                    except Exception as e:               # noqa: BLE001
                        _log(f"reprise {etape} de {cle} : {type(e).__name__}: {str(e)[:100]}")
                        ok = False
                    if not ok:
                        restes.append(etape)
                        if compte:
                            essais[etape] = int(essais.get(etape) or 0) + 1
                _noter(g, uid, manques=restes, essais=essais, a_verifier=bool(a_verifier),
                       pays="pays" not in restes)
                if a_verifier:
                    bilan["a_verifier"].append(f"{uid} : {a_verifier}")
                if manques and not restes:
                    bilan["reprises"].append(uid)
                elif restes and set(restes) != set(a_verifier):
                    bilan["rates"].append(f"{uid} : {restes}")
        except Exception as e:                               # noqa: BLE001
            bilan["rates"].append(f"{uid} : {type(e).__name__}: {str(e)[:80]}")
    if any(bilan.values()):
        _log(f"reprise des pages {gid} : {bilan}")
    return bilan
