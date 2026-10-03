"""Le plan d'onboarding du site, publié et tenu à jour dans un salon Discord.

Le plan vit sur le tableau de bord : c'est là qu'on écrit une étape, qu'on
dépose une vidéo, qu'on réordonne. Les VA, eux, lisent Discord. Sans pont
entre les deux, chaque correction obligeait à tout reposter à la main — et au
bout de deux fois, les deux versions ne disaient plus la même chose.

CE MODULE NE REPOSTE PAS, IL CORRIGE. Un message déjà publié est MODIFIÉ sur
place : les liens que les VA se sont envoyés continuent de marcher, et le
salon ne se remplit pas d'une nouvelle copie à chaque virgule changée.

IL NE TOUCHE QUE CE QU'IL A ÉCRIT. Les messages écrits à la main dans le salon
restent là où ils sont : le pont ne connaît que les messages dont il garde
l'identifiant, et il refuse d'en adopter un qu'il n'a pas posté.

RIEN NE PART SANS CHANGEMENT RÉEL. Chaque étape porte une empreinte (son
texte plus ses médias) : tant qu'elle ne bouge pas, aucun appel n'est fait.
Sans cette empreinte, une sauvegarde du site aurait réécrit les neuf messages
à chaque frappe.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json
import theme_mario

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "onboarding_discord.json"
ETAT_FICHIER = DATA_DIR / "onboarding_discord_etat.json"

MAX_TEXTE = 2000
# Discord plafonne la taille d'un fichier selon le niveau de boost du serveur.
# Sans boost c'est 10 Mo — et une capture d'écran de téléphone en fait trois
# cents. On la fait donc rétrécir au lieu de la refuser.
LIMITES_BOOST = {0: 10, 1: 10, 2: 50, 3: 100}      # en Mo
MARGE = 0.92                         # on vise un peu sous la limite : Discord compte l'enveloppe
CACHE_DIR = DATA_DIR / "onboarding_compresse"
SECRET_FICHIER = DATA_DIR / "onboarding_secret"
SITE = "https://youl4b.com"
_LIMITE: Dict[str, Any] = {}
MAX_JOINTES = 10
ATTENTE_S = 6.0                      # on laisse la rafale de frappes se calmer
MAX_ENCADRE = 4096                   # une description d'encadre tient plus large

# Une couleur par etape, posee sur la barre de gauche de l'encadre. C'est le
# seul moyen Discord de marquer « on change de jour » sans ajouter une ligne de
# separation que personne ne lit. La palette tourne si le plan s'allonge.
COULEURS = [0xF1C40F,   # accueil  — dore
            0x3B82F6,   # jour 0   — bleu
            0xF59E0B,   # attente  — orange
            0x22C55E,   # jour 1   — vert
            0x06B6D4,   # jour 2   — turquoise
            0x8B5CF6,   # jour 3   — violet
            0xEC4899,   # jour 4   — rose
            0xEF4444,   # jour 5   — rouge
            0x10B981]   # jour 6+  — emeraude


def couleur_de(etape: Dict[str, Any], rang: int) -> int:
    """La couleur de l'etape : la sienne si elle en a une, sinon celle du rang."""
    brute = etape.get("couleur") or etape.get("color")
    if brute not in (None, ""):
        try:
            return int(str(brute).lstrip("#"), 16) if isinstance(brute, str) else int(brute)
        except (TypeError, ValueError):
            pass
    # L'ordre compte : la couleur ecrite sur l'etape depuis le site l'emporte
    # (ci-dessus), puis la palette choisie dans la config, puis le theme du
    # serveur. Ce module ne connait QUE son salon -- pas de cle serveur dans
    # data/onboarding_discord.json -- donc c'est le salon qui designe Va IG.
    palette = (config().get("couleurs")
               or (theme_mario.COULEURS_WARMUP
                   if theme_mario.warmup_ici(config().get("salon")) else None)
               or COULEURS)
    return int(palette[rang % len(palette)])


def _lire(chemin: Path, defaut):
    try:
        return safe_json.load(chemin, default=defaut) or defaut
    except Exception:
        return defaut


def config() -> Dict[str, Any]:
    return _lire(CONFIG_FICHIER, {})


def actif() -> bool:
    c = config()
    return bool(c.get("actif")) and bool(c.get("salon"))


def _etat() -> Dict[str, Any]:
    return _lire(ETAT_FICHIER, {})


def _ecrire(d: Dict[str, Any]) -> None:
    safe_json.write_text(ETAT_FICHIER, json.dumps(d, ensure_ascii=False, indent=2))


def _api(methode: str, chemin: str, **kw):
    from verif_discord import api
    return api(methode, chemin, **kw)


def _api_patient(methode: str, chemin: str, essais: int = 4, **kw):
    """Comme _api, mais il attend quand Discord dit « trop vite ».

    Un 429 n'est PAS « ce message n'existe plus ». Confondre les deux a coûté
    des doublons en production : la correction d'un message etait refusee pour
    cadence, le pont en concluait qu'il avait disparu, et en reposait un neuf.
    """
    for essai in range(max(1, essais)):
        code, rep = _api(methode, chemin, **kw)
        if code != 429:
            return code, rep
        attente = float((rep or {}).get("retry_after") or 1) + 0.3
        print(f"[onboarding] cadence Discord : {attente:.1f}s avant de reessayer",
              flush=True)
        time.sleep(min(attente, 30))
    return 429, {"message": "cadence Discord : abandon apres plusieurs essais"}


def limite_octets() -> int:
    """La taille maximale d'un fichier sur CE serveur, demandée à Discord.

    Codée en dur, elle aurait menti le jour où le serveur est boosté — et on
    aurait continué à écraser des vidéos sans raison. Gardée une heure.
    """
    if _LIMITE.get("quand", 0) > time.time() - 3600 and _LIMITE.get("octets"):
        return int(_LIMITE["octets"])
    mo = 10
    try:
        salon = str(config().get("salon") or "")
        c, ch = _api("GET", f"/channels/{salon}")
        gid = str((ch or {}).get("guild_id") or "")
        if gid:
            c2, g = _api("GET", f"/guilds/{gid}")
            mo = LIMITES_BOOST.get(int((g or {}).get("premium_tier") or 0), 10)
    except Exception as e:
        print(f"[onboarding] limite de taille : {type(e).__name__}: {e} — 10 Mo retenu",
              flush=True)
    _LIMITE.update({"octets": mo * 1024 * 1024, "quand": time.time()})
    return mo * 1024 * 1024


def _secret() -> bytes:
    """La clé qui signe les liens de téléchargement, créée au premier besoin."""
    try:
        if SECRET_FICHIER.exists():
            v = SECRET_FICHIER.read_bytes().strip()
            if v:
                return v
    except OSError:
        pass
    import os as _os
    v = _os.urandom(32).hex().encode()
    SECRET_FICHIER.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FICHIER.write_bytes(v)
    try:
        SECRET_FICHIER.chmod(0o600)
    except OSError:
        pass
    return v


def jeton_media(step_id: str, media_id: str) -> str:
    """Un jeton qui ouvre CE fichier et aucun autre.

    Signé, donc impossible à deviner et impossible à bricoler pour atteindre
    un autre fichier du serveur. Rien n'est stocké : le lien reste valable tant
    que la clé ne change pas, et changer la clé les révoque tous d'un coup.
    """
    import base64
    import hmac
    corps = f"{step_id}:{media_id}".encode()
    sign = hmac.new(_secret(), corps, hashlib.sha256).digest()[:12]
    return (base64.urlsafe_b64encode(corps).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(sign).decode().rstrip("="))


def lire_jeton(jeton: str) -> Optional[Tuple[str, str]]:
    """(step_id, media_id) si la signature tient, None sinon."""
    import base64
    import hmac
    try:
        brut, _, sig = str(jeton or "").partition(".")
        if not brut or not sig:
            return None
        def _d(x):
            return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
        corps = _d(brut)
        attendu = hmac.new(_secret(), corps, hashlib.sha256).digest()[:12]
        # comparaison a temps constant : comparer avec == laisse fuiter
        # l'information octet par octet
        if not hmac.compare_digest(_d(sig), attendu):
            return None
        sid, _, mid = corps.decode().partition(":")
        return (sid, mid) if sid and mid else None
    except Exception:
        return None


def telechargements_de(etape: Dict[str, Any]) -> List[Tuple[str, str]]:
    """[(nom, adresse)] pour chaque fichier de l'étape, en qualité d'origine.

    La copie envoyée dans Discord est compressée pour tenir dans la limite ;
    celle-ci est l'originale. Un VA qui veut la regarder en grand la télécharge.
    """
    base = str(config().get("site") or SITE).rstrip("/")
    out = []
    for m in (etape.get("media") or []):
        if m.get("kind") == "link" or not m.get("path"):
            continue
        sid, mid = str(etape.get("id") or ""), str(m.get("id") or "")
        if not (sid and mid):
            continue
        out.append((str(m.get("name") or "fichier"),
                    f"{base}/ob/{jeton_media(sid, mid)}"))
    return out


def _duree(chemin: Path) -> float:
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(chemin)],
                           capture_output=True, text=True, timeout=120)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def comprimer(chemin: Path, cible: int) -> Tuple[Optional[Path], str]:
    """Rétrécit une vidéo sous `cible` octets. Rend (fichier, explication).

    Le débit se calcule depuis la DURÉE : viser une qualité fixe donnerait un
    fichier de taille inconnue, et on se serait fait refuser une deuxième fois.
    Le résultat est gardé : republier dix fois ne doit pas recompresser dix fois.
    """
    import subprocess
    duree = _duree(chemin)
    if duree <= 0:
        return None, "durée illisible (ffprobe)"
    try:
        st = chemin.stat()
        cle = hashlib.sha1(f"{chemin}|{st.st_mtime_ns}|{st.st_size}|{cible}"
                           .encode()).hexdigest()[:16]
    except OSError as e:
        return None, f"fichier illisible ({type(e).__name__})"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sortie = CACHE_DIR / f"{cle}.mp4"
    if sortie.exists() and 0 < sortie.stat().st_size <= cible:
        return sortie, "déjà compressée"

    audio = 64_000
    for hauteur in (720, 480, 360):
        video = int((cible * 8 * MARGE) / duree) - audio
        if video < 120_000:
            video = 120_000
        cmd = ["ffmpeg", "-y", "-i", str(chemin),
               "-vf", f"scale=-2:'min({hauteur},ih)'",
               "-c:v", "libx264", "-preset", "veryfast",
               "-b:v", str(video), "-maxrate", str(int(video * 1.2)),
               "-bufsize", str(int(video * 2)),
               "-c:a", "aac", "-b:a", str(audio), "-movflags", "+faststart",
               str(sortie)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=1800)
        except Exception as e:
            return None, f"ffmpeg : {type(e).__name__}"
        if r.returncode != 0 or not sortie.exists():
            return None, "ffmpeg a échoué"
        if sortie.stat().st_size <= cible:
            return sortie, (f"compressée {chemin.stat().st_size // (1024*1024)} Mo → "
                            f"{sortie.stat().st_size // (1024*1024)} Mo en {hauteur}p")
        # trop gros encore : on redescend d'un cran plutôt que d'abandonner
    return None, (f"impossible de passer sous {cible // (1024*1024)} Mo "
                  f"({int(duree)} s de vidéo)")


# ─── ce qu'une étape donne comme message ─────────────────────────────────
# Discord n'allume un lecteur que pour une poignee de sites, et SEULEMENT
# quand l'adresse est dans le texte du message : dans un encadre, elle reste un
# lien bleu. Google Drive n'en fait pas partie — un lien Drive fait quitter
# Discord, c'est tout.
LECTEURS = ("youtube.com/watch", "youtu.be/", "youtube.com/shorts",
            "vimeo.com/", "streamable.com/", "clips.twitch.tv/", "twitch.tv/videos/")


# Google Drive ne se joue PAS dans Discord — aucun moyen de l'y forcer. Mais
# une adresse Drive brute ne dit pas ce qu'elle fait : on la coupe en deux
# gestes nommes, regarder et telecharger, pour que le VA sache ou il va.
import re as _re
_DRIVE = (_re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]{10,})"),
          _re.compile(r"drive\.google\.com/open\?id=([A-Za-z0-9_-]{10,})"),
          _re.compile(r"drive\.google\.com/uc\?[^ ]*id=([A-Za-z0-9_-]{10,})"),
          _re.compile(r"docs\.google\.com/[^ ]*/d/([A-Za-z0-9_-]{10,})"))


def drive_id(url: str) -> str:
    """L'identifiant du fichier Drive, ou « » si ce n'est pas un lien Drive."""
    u = str(url or "")
    for motif in _DRIVE:
        m = motif.search(u)
        if m:
            return m.group(1)
    return ""


# Un lien vers un message de CE salon ne sert a rien : Discord le transforme
# en pastille « # salon › » qui renvoie la ou on est deja. C'etait la trace de
# l'import d'origine ; elle n'a plus lieu d'etre une fois la video rattachee.
def est_renvoi_discord(url: str) -> bool:
    return "discord.com/channels/" in str(url or "")


def est_lecteur(url: str) -> bool:
    u = str(url or "").lower()
    return any(m in u for m in LECTEURS)


def lecteurs_de(etape: Dict[str, Any]) -> List[str]:
    """Les adresses qui se jouent sur place, a mettre DANS le texte."""
    out = []
    for m in (etape.get("media") or []):
        u = m.get("url") or m.get("name") or ""
        if m.get("kind") == "link" and est_lecteur(u) and u not in out:
            out.append(str(u))
    return out


def titre_de(etape: Dict[str, Any]) -> str:
    return ((etape.get("icon") or "") + " " + (etape.get("title") or "")).strip()[:256]


def corps_de(etape: Dict[str, Any]) -> str:
    """Le corps de l'encadré : le texte de l'étape, puis ses liens."""
    corps = (etape.get("description") or "").strip()
    # les adresses qui se jouent sont remontees dans le texte : les repeter ici
    # aurait donne le meme lien deux fois, une fois jouable et une fois mort
    jouables = set(lecteurs_de(etape))
    liens = [m.get("name") or m.get("url") for m in (etape.get("media") or [])
             if m.get("kind") == "link" and (m.get("name") or m.get("url"))
             and not est_renvoi_discord(m.get("url") or m.get("name") or "")
             and (m.get("url") or m.get("name")) not in jouables
             # un Drive est rendu plus bas en deux gestes : le repeter ici
             # aurait donne la meme adresse trois fois
             and not drive_id(m.get("url") or m.get("name") or "")]
    if liens:
        corps = (corps + "\n\n" if corps else "") + "\n".join("📎 " + str(l) for l in liens)
    # un lien Drive devient deux gestes nommes
    drives = []
    for m in (etape.get("media") or []):
        if m.get("kind") != "link":
            continue
        u = m.get("url") or m.get("name") or ""
        ident = drive_id(u)
        if ident:
            drives.append((str(m.get("name") or "la vidéo"), ident))
    if drives:
        bloc = []
        for nom, ident in drives:
            nom_court = nom if not nom.startswith("http") else "la vidéo"
            bloc.append(
                f"▶️ [Regarder {nom_court}](https://drive.google.com/file/d/{ident}/view)"
                f"  ·  ⬇️ [Télécharger]"
                f"(https://drive.google.com/uc?export=download&id={ident})")
        corps = (corps + "\n\n" if corps else "") + "\n".join(bloc)

    tel = telechargements_de(etape)
    if tel:
        corps = (corps + "\n\n" if corps else "") + "\n".join(
            f"⬇️ [{nom} — qualité d'origine]({url})" for nom, url in tel)
    return corps[:MAX_ENCADRE]


def encadre_de(etape: Dict[str, Any], rang: int) -> Dict[str, Any]:
    """L'étape en encadré : sa barre de couleur marque le changement de jour."""
    return {"title": titre_de(etape),
            "description": corps_de(etape),
            "color": couleur_de(etape, rang)}


def texte_de(etape: Dict[str, Any]) -> str:
    """Le rendu en texte brut — sert encore aux empreintes et aux essais."""
    titre = titre_de(etape)
    corps = corps_de(etape)
    return (f"**{titre}**" + (f"\n\n{corps}" if corps else ""))[:MAX_TEXTE]


def fichiers_de(etape: Dict[str, Any]) -> Tuple[List[Tuple[str, bytes]], List[str]]:
    """(fichiers lisibles, ce qui a été écarté et pourquoi).

    Un média trop lourd ou disparu du disque n'est pas tu : le compte rendu le
    nomme, sinon on chercherait longtemps pourquoi une vidéo manque.
    """
    pris: List[Tuple[str, bytes]] = []
    ecartes: List[str] = []
    plafond = limite_octets()
    for m in (etape.get("media") or []):
        if m.get("kind") == "link":
            continue
        chemin = Path(str(m.get("path") or ""))
        nom = str(m.get("name") or chemin.name or "media")
        if not chemin.exists():
            ecartes.append(f"{nom} (fichier absent)")
            continue
        taille = chemin.stat().st_size
        if taille > plafond:
            if str(m.get("kind")) != "video":
                ecartes.append(f"{nom} ({taille // (1024 * 1024)} Mo, "
                               f"au-dessus des {plafond // (1024 * 1024)} Mo de Discord)")
                continue
            petite, mot = comprimer(chemin, plafond)
            if petite is None:
                ecartes.append(f"{nom} ({taille // (1024 * 1024)} Mo) : {mot}")
                continue
            print(f"[onboarding] {nom} : {mot}", flush=True)
            chemin = petite
        if len(pris) >= MAX_JOINTES:
            ecartes.append(f"{nom} (plus de {MAX_JOINTES} pièces jointes)")
            continue
        try:
            pris.append((nom, chemin.read_bytes()))
        except Exception as e:
            ecartes.append(f"{nom} ({type(e).__name__})")
    return pris, ecartes


def empreinte(etape: Dict[str, Any], rang: int = 0) -> str:
    """Change dès que le message rendu changerait — et pas avant.

    La couleur en fait partie : réordonner deux étapes change leur couleur, et
    sans ça le salon aurait gardé l'ancienne.
    """
    med = [(str(m.get("id")), str(m.get("kind")), str(m.get("name")),
            str(m.get("size") or ""), str(m.get("url") or ""))
           for m in (etape.get("media") or [])]
    brut = json.dumps([titre_de(etape), corps_de(etape), couleur_de(etape, rang),
                       lecteurs_de(etape), sorted(med)],
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()


# ─── publier ─────────────────────────────────────────────────────────────
def publier(force: bool = False) -> Dict[str, Any]:
    """Aligne le salon sur le plan. Rend le compte rendu de ce qui a bougé."""
    bilan = {"crees": [], "corriges": [], "effaces": [], "inchanges": 0,
             "ecartes": [], "rates": []}
    if not actif():
        bilan["rates"].append("pont désactivé (data/onboarding_discord.json)")
        return bilan
    salon = str(config().get("salon"))
    try:
        import onboarding as ob
        etapes = ob.list_steps()
    except Exception as e:
        bilan["rates"].append(f"plan illisible : {type(e).__name__}: {e}")
        return bilan

    d = _etat()
    connus = d.setdefault("messages", {})
    vivants = set()

    for rang, etape in enumerate(etapes):
        sid = str(etape.get("id") or "")
        if not sid:
            continue
        vivants.add(sid)
        emp = empreinte(etape, rang)
        fiche = connus.get(sid) or {}
        if fiche.get("id") and fiche.get("empreinte") == emp and not force:
            bilan["inchanges"] += 1
            continue
        fichiers, ecartes = fichiers_de(etape)
        bilan["ecartes"] += [f'{etape.get("title")} : {x}' for x in ecartes]
        # content vide ET embeds : en corrigeant un ancien message en texte
        # brut, sans le vider on aurait eu le texte DEUX fois, une en clair et
        # une dans l'encadre.
        corps = {"content": "\n".join(lecteurs_de(etape))[:MAX_TEXTE],
                 "embeds": [encadre_de(etape, rang)],
                 "allowed_mentions": {"parse": []}}

        if fiche.get("id"):
            # On REMPLACE les pièces jointes : sans la liste, Discord garde les
            # anciennes, et une vidéo remplacée se serait retrouvée en double.
            corps["attachments"] = [{"id": i, "filename": n}
                                    for i, (n, _o) in enumerate(fichiers)]
            if fichiers:
                code, rep = _api_fichiers("PATCH",
                                          f'/channels/{salon}/messages/{fiche["id"]}',
                                          corps, fichiers)
            else:
                code, rep = _api_patient("PATCH",
                                         f'/channels/{salon}/messages/{fiche["id"]}',
                                         json=corps)
            if code == 200:
                connus[sid] = {"id": fiche["id"], "empreinte": emp}
                bilan["corriges"].append(etape.get("title"))
                continue
            # UN SEUL CAS justifie de reposter : le message n'existe plus.
            # Tout le reste (cadence, panne, droits) se repare tout seul au
            # prochain tour, alors qu'un message de trop reste pour toujours.
            if code not in (404, 403, 10008):
                bilan["rates"].append(f'{etape.get("title")} : correction refusée '
                                      f'(HTTP {code}) — rien reposté, nouvel essai '
                                      "au prochain tour")
                continue
            print(f'[onboarding] {etape.get("title")!r} introuvable (HTTP {code}) : '
                  "nouveau message", flush=True)

        if fichiers:
            corps["attachments"] = [{"id": i, "filename": n}
                                    for i, (n, _o) in enumerate(fichiers)]
            code, rep = _api_fichiers("POST", f"/channels/{salon}/messages",
                                      corps, fichiers)
        else:
            corps.pop("attachments", None)
            code, rep = _api_patient("POST", f"/channels/{salon}/messages", json=corps)
        if code == 200 and rep.get("id"):
            connus[sid] = {"id": str(rep["id"]), "empreinte": emp}
            bilan["crees"].append(etape.get("title"))
        else:
            bilan["rates"].append(f'{etape.get("title")} : HTTP {code} '
                                  f'{str(rep.get("message") or "")[:80]}')
        time.sleep(1.0)

    # une étape supprimée du plan n'a plus à traîner dans le salon
    for sid in [s for s in list(connus) if s not in vivants]:
        mid = str((connus.get(sid) or {}).get("id") or "")
        if mid:
            c, _r = _api("DELETE", f"/channels/{salon}/messages/{mid}")
            bilan["effaces"].append(sid if c in (200, 204) else f"{sid} (HTTP {c})")
        connus.pop(sid, None)
    _ecrire(d)
    return bilan


def _api_fichiers(methode: str, chemin: str, payload: Dict[str, Any], fichiers):
    """Comme _api, mais en multipart — Discord veut ça pour les pièces jointes."""
    import json as _j
    import os as _os
    import urllib.error
    import urllib.request
    from verif_discord import _token
    limite = "----youl4b" + _os.urandom(12).hex()
    morceaux = []

    def champ(entete: bytes, contenu: bytes):
        morceaux.append(b"--" + limite.encode() + b"\r\n" + entete + b"\r\n\r\n"
                        + contenu + b"\r\n")

    champ(b'Content-Disposition: form-data; name="payload_json"\r\n'
          b"Content-Type: application/json",
          _j.dumps(payload, ensure_ascii=False).encode())
    for i, (nom, octets) in enumerate(fichiers):
        sur = nom.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
        champ(f'Content-Disposition: form-data; name="files[{i}]"; filename="{sur}"'
              .encode() + b"\r\nContent-Type: application/octet-stream", octets)
    morceaux.append(b"--" + limite.encode() + b"--\r\n")
    corps = b"".join(morceaux)
    req = urllib.request.Request(
        "https://discord.com/api/v10" + chemin, data=corps, method=methode,
        headers={"Authorization": "Bot " + _token(),
                 "Content-Type": f"multipart/form-data; boundary={limite}",
                 "User-Agent": "DiscordBot (youl4b, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            brut = r.read()
            return r.status, (_j.loads(brut) if brut else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, _j.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


# ─── adoption des messages déjà postés ───────────────────────────────────
def adopter(ids: List[str]) -> Dict[str, Any]:
    """Relie des messages DÉJÀ postés aux étapes, dans l'ordre du plan.

    Sert une seule fois, pour reprendre la main sur ce qui a été publié avant
    le pont. On refuse un message que le bot n'a pas écrit : on ne modifiera
    jamais le message de quelqu'un d'autre.
    """
    import onboarding as ob
    salon = str(config().get("salon") or "")
    etapes = ob.list_steps()
    if len(ids) != len(etapes):
        return {"ok": False, "erreur": f"{len(ids)} messages pour {len(etapes)} étapes"}
    code, moi = _api("GET", "/users/@me")
    mon_id = str((moi or {}).get("id") or "")
    d = _etat()
    connus = d.setdefault("messages", {})
    pris = []
    for rang, (etape, mid) in enumerate(zip(etapes, ids)):
        c, msg = _api("GET", f"/channels/{salon}/messages/{mid}")
        if c != 200:
            return {"ok": False, "erreur": f"message {mid} illisible (HTTP {c})"}
        if str(((msg.get("author") or {}).get("id")) or "") != mon_id:
            return {"ok": False, "erreur": f"le message {mid} n'est pas du bot : refus"}
        connus[str(etape["id"])] = {"id": str(mid), "empreinte": empreinte(etape, rang)}
        pris.append(etape.get("title"))
    _ecrire(d)
    return {"ok": True, "adoptes": pris}


# ─── déclenchement depuis le site ────────────────────────────────────────
_MINUTERIE: Optional[threading.Timer] = None
_VERROU = threading.Lock()


def planifier(delai: float = ATTENTE_S) -> None:
    """Demande une publication bientôt, et une seule.

    Le site enregistre à chaque frappe : publier à chaque appel aurait tapé
    sur Discord vingt fois pour une phrase. On attend que ça se calme.
    """
    global _MINUTERIE
    if not actif():
        return
    with _VERROU:
        if _MINUTERIE is not None:
            _MINUTERIE.cancel()
        _MINUTERIE = threading.Timer(delai, _tour)
        _MINUTERIE.daemon = True
        _MINUTERIE.start()


def _tour() -> None:
    try:
        b = publier()
        if any(b[k] for k in ("crees", "corriges", "effaces", "ecartes", "rates")):
            print(f"[onboarding] publication : {b}", flush=True)
    except Exception as e:
        print(f"[onboarding] publication : {type(e).__name__}: {e}", flush=True)
