import asyncio
import datetime as _dt
import json
import os
import random
import re
import tempfile
import time
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks

from video_transform import transform_video, load_config as load_transform_config
from image_transform import transform_image, load_config as load_image_config

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"

# Fuseau France pour le post quotidien à minuit (heure locale FR)
try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = _dt.timezone(_dt.timedelta(hours=1))  # fallback UTC+1


def _build_menu_embed(identity):
    """Embed clair et intuitif : chaque bouton est expliqué en une ligne."""
    emb = discord.Embed(
        title="☀️ Ton contenu du jour",
        description="Clique sur un bouton pour recevoir ton contenu **prêt à poster** 👇",
        color=discord.Color.blurple(),
    )
    emb.add_field(name="🎬 Reel", value="Vidéos + captions (1 par compte)", inline=True)
    emb.add_field(name="📖 Story", value="Photo + texte pour ta story", inline=True)
    emb.add_field(name="🖼️ Post", value="Photo + légende pour le feed", inline=True)
    emb.add_field(name="📲 Story CTA", value="Photo CTA (à poster le soir)", inline=True)
    emb.add_field(name="👤 Pseudo", value="Des pseudos Insta dispo", inline=True)
    emb.add_field(name="📝 Name", value="Des noms d'affichage", inline=True)
    emb.add_field(name="💬 Bio", value="Des bios Insta de ton identité", inline=True)
    emb.add_field(name="🖼 PP", value="Des photos de profil prêtes", inline=True)
    emb.add_field(name="🔗 Demander un lien", value="Prévient les managers → ils t'envoient ton lien", inline=True)
    if identity:
        emb.set_footer(text=f"Identité : {identity}")
    return emb
USERS_FILE = DATA_DIR / "users.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
LINK_REQ_CONFIG = DATA_DIR / "link_request_config.json"  # {channel_id, role_id}

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    # Écriture atomique : on écrit dans un fichier temporaire puis os.replace.
    # Évite qu'un kill/crash en plein flush laisse un JSON tronqué (ce qui
    # réinitialiserait silencieusement l'état, ex. les blocs anti-doublon).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    except Exception:
        return False


def _is_staff_member(member):
    """True si le membre a des permissions de staff/manager (admin / gerer serveur / gerer salons)."""
    p = getattr(member, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_guild or p.manage_channels))


# ---- Demandes de lien : anti-spam (1 demande en attente) + anti-doublon (1 SEUL lien / VA) ----
# Bloc DUR : dès qu'un VA a un lien, on refuse d'en regénérer un (sauf future commande dédiée).
LINK_STATE_FILE = DATA_DIR / "link_request_state.json"  # {uid: {"p": ts_demande, "g": ts_genere, "url": ..., "name": ...}}
_REQ_PENDING_TTL = 24 * 3600   # une demande en attente expire après 24h

# Verrou en mémoire : empêche un double-clic / 2 managers de générer 2 liens
# pendant que la 1re génération (lente, réseau) est encore en cours.
_LINK_GEN_INFLIGHT = set()


def _gms_exact_link(handle: str, links) -> "dict | None":
    """Match STRICT pour le bloc dur : display_name normalisé == 'va' + handle.
    Volontairement PAS de substring (gms.find_link_for_handle bloquerait à tort
    un VA différent dont le pseudo est inclus dans un autre, ex: @mia vs @mialee)."""
    h = re.sub(r"[^a-z0-9]", "", (handle or "").lower())
    if len(h) < 3 or not links:
        return None
    target = "va" + h
    for l in links:
        if re.sub(r"[^a-z0-9]", "", (l.get("display_name") or "").lower()) == target:
            return l
    return None


def _lr_load():
    d = load_json(LINK_STATE_FILE, {})
    return d if isinstance(d, dict) else {}


def _lr_is_pending(uid) -> bool:
    e = _lr_load().get(str(uid)) or {}
    p = e.get("p")
    return bool(p and (time.time() - p) < _REQ_PENDING_TTL)


def _lr_mark_pending(uid):
    d = _lr_load()
    d.setdefault(str(uid), {})["p"] = time.time()
    save_json(LINK_STATE_FILE, d)


def _lr_existing(uid):
    """Renvoie l'entrée {g, url, name} si un lien a DÉJÀ été généré pour ce VA, sinon None.
    Sert de bloc dur : une fois qu'un VA a un lien, plus de génération auto."""
    e = _lr_load().get(str(uid)) or {}
    return e if e.get("g") else None


def _lr_mark_generated(uid, url: str = "", name: str = ""):
    d = _lr_load()
    e = d.setdefault(str(uid), {})
    e["g"] = time.time()
    if url:
        e["url"] = url
    if name:
        e["name"] = name
    e.pop("p", None)  # la demande est traitée
    save_json(LINK_STATE_FILE, d)


async def _lr_send_blocked(interaction, uid, url: str = "", source: str = ""):
    """Réponse standard quand un VA a déjà un lien : éphémère + on retire le bouton."""
    where = " (trouvé sur GetMySocial)" if source == "gms" else ""
    try:
        await interaction.followup.send(
            f"🔒 **Ce VA a déjà un lien**{where} — génération bloquée pour éviter les doublons."
            + (f"\n🔗 Lien existant : {url}" if url else "")
            + "\n\n_Pour en recréer un, il faudra une commande dédiée (pas encore dispo)._",
            ephemeral=True,
        )
    except Exception:
        pass
    msg = getattr(interaction, "message", None)
    if msg is not None:
        try:
            await msg.edit(
                content=f"🔒 {interaction.user.mention} — ce VA a déjà un lien"
                + (f" : {url}" if url else "")
                + " (génération bloquée, anti-doublon).",
                view=None,
            )
        except Exception:
            pass


def unescape_newlines(text):
    return text.replace("\\n", "\n") if text else text


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def random_username_for(identity):
    items = read_lines(IDENTITIES_DIR / identity / "usernames.txt")
    return unescape_newlines(random.choice(items)) if items else None


# === USERNAME GENERATOR + INSTAGRAM AVAILABILITY CHECK ===

# Sufixes / prefixes utilises par les VAs pour creer des pseudos qui ont du sens
_PREFIXES = [
    "sweet", "baby", "miss", "lil", "kiss", "cute", "iam", "the",
    "queen", "princess", "honey", "tiny", "bb", "babe",
]
_SUFFIXES = [
    "xx", "xo", "xoxo", "cuty", "cute", "babe", "honey",
    "love", "angel", "doll", "vibes", "muse", "girl",
    "bunny", "rose", "lover", "kiss", "fr", "official",
    "ofc",
]
_LETTERS_BLOCKS = ["xx", "yy", "zz", "qq", "mm", "ll", "bb"]
_RANDOM_DOUBLE_LETTERS = ["ee", "oo", "ii", "aa", "uu"]


def generate_username_candidates(base: str, count: int = 40) -> list:
    """Genere des pseudos style 'name_xxxx' / 'name_xx' avec 3-4 lettres
    random (consonnes souvent). Format Instagram credible.

    Exemples : julia_vdlnt, anna_vnbs, amelia_xqks, mel_brtn, lia_zqp
    """
    base = base.lower().strip()
    base = "".join(c for c in base if c.isalpha())
    if not base:
        return []
    # Consonnes (pour eviter "mama", "papa" - favoriser look random credible)
    consonants = "bcdfghjklmnpqrstvwxz"
    vowels = "aeiouy"
    all_letters = "abcdefghijklmnopqrstuvwxyz"
    seen = set()
    out = []
    def add(u):
        u = u.lower()
        if u and 4 <= len(u) <= 30 and u not in seen and u.replace("_", "").isalpha():
            seen.add(u)
            out.append(u)
    # Bases a considerer : nom complet + diminutifs
    bases = [base] + _get_diminutives(base)
    bases = list(dict.fromkeys(bases))
    # Genere format principal : name + (_)?+ 3-4 lettres random
    # On fait beaucoup d'iterations pour avoir count candidats dispo apres check
    for _ in range(count * 4):
        b = random.choice(bases)
        sep = random.choice(["_", "_", ""])  # 2/3 chance d'underscore
        n_letters = random.choice([3, 3, 4, 4])  # 3 ou 4 lettres
        # Mix consonnes + parfois 1 voyelle pour rendre plus naturel
        letters_pool = random.choice([
            consonants,           # 100% consonnes = look "code"
            consonants + vowels,  # mix = plus prononcable
            all_letters,          # tout
        ])
        rand_part = "".join(random.choice(letters_pool) for _ in range(n_letters))
        add(b + sep + rand_part)
    random.shuffle(out)
    return out[:count]


async def check_instagram_username_available(username: str) -> bool:
    """Check si un username Instagram est dispo via RapidAPI Instagram Scraper.
    Plus fiable que le HTTP direct (IG redirect login pour les non-authentifies).

    Retourne True si dispo (= profile pas trouve), False si pris.
    """
    if not username:
        return False
    import aiohttp
    try:
        from insta_scraper import load_auth
        auth = load_auth()
        api_key = (auth.get("rapidapi_key") or "").strip()
        host = (auth.get("rapidapi_host") or "instagram-scraper-stable-api.p.rapidapi.com").strip()
        if not api_key:
            return False  # Pas de cle = on peut pas check, on retourne False (safe)
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": host,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://{host}/ig_get_fb_profile_v3.php",
                headers=headers,
                data=f"username_or_url={username}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 404:
                    return True
                if r.status != 200:
                    return False
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    return False
                if not isinstance(body, dict):
                    # body non-dict suggere reponse vide / erreur
                    return True
                # Unwrap "data"/"user"
                user = body
                if "user" in body and isinstance(body["user"], dict):
                    user = body["user"]
                elif "data" in body and isinstance(body["data"], dict):
                    user = body["data"]
                if not isinstance(user, dict):
                    return True
                # Un profil valide a soit username, pk, ou id, ou follower_count
                has_id = bool(user.get("username") or user.get("pk") or user.get("id"))
                # Si erreur explicite, dispo
                err = (user.get("error") or user.get("message") or "")
                if err and ("not found" in str(err).lower() or "introuvable" in str(err).lower()):
                    return True
                if not has_id:
                    return True  # rien dans la reponse = pas trouve = dispo
                return False  # has_id = profil existe = pris
    except Exception:
        return False


async def find_available_usernames(base: str, max_check: int = 30, want: int = 5) -> list:
    """Genere des candidats et check leur dispo Instagram en parallele.
    Retourne les premiers `want` qui sont dispo."""
    candidates = generate_username_candidates(base, count=max_check)
    if not candidates:
        return []
    # Check en parallele (8 en simultane max pour eviter rate-limit)
    semaphore = asyncio.Semaphore(8)
    available = []
    async def check_one(u):
        async with semaphore:
            if len(available) >= want:
                return
            ok = await check_instagram_username_available(u)
            if ok:
                available.append(u)
    tasks = [asyncio.create_task(check_one(c)) for c in candidates]
    # Attend jusqu'a ce qu'on en ait assez OU qu'on ait tout teste
    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED, timeout=20)
    for t in pending:
        t.cancel()
    return available[:want]


def random_name_for(identity):
    items = read_lines(IDENTITIES_DIR / identity / "names.txt")
    return unescape_newlines(random.choice(items)) if items else None


# === DISPLAY NAME GENERATOR (Instagram-style) ===

# Noms de famille FR / international qui passent bien sur IG
_LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Durand", "Robert", "Petit", "Richard",
    "Moreau", "Laurent", "Lefebvre", "Roux", "Fournier", "Mercier", "Bonnet",
    "Lambert", "Rousseau", "Vincent", "Muller", "Lefevre", "Garnier", "Faure",
    "Andre", "Mercier", "Blanc", "Henry", "Roussel", "Garcia", "David", "Bertrand",
    "Charpentier", "Renard", "Marchand", "Carpentier", "Vidal", "Caron", "Hubert",
    "Aubert", "Rey", "Lemoine", "Riviere", "Fontaine", "Olivier", "Lopez",
    "Gauthier", "Lacroix", "Gerard", "Renaud", "Dumont", "Roger", "Schmitt",
    "Colin", "Mathieu", "Roy", "Picard", "Roche", "Boyer", "Aubry", "Dupuis",
    "Lemoine", "Brun", "Adam", "Joly", "Roussel", "Carre", "Camus", "Renard",
    # International qui marche bien sur IG
    "Rose", "Stone", "Wilde", "Storm", "Lane", "Reed", "Knox", "Wood",
    "Cole", "Quinn", "Ray", "Page", "Lee", "May", "Belle", "Fox",
]
_NAME_EMOJIS = [
    "🌹", "🤍", "💕", "✨", "🌸", "🦋", "🌟", "💫", "🌺", "🍒",
    "💋", "🔥", "❤️", "🌷", "💞", "👼", "🌙", "💎", "🦄", "🐝",
    "",  # Vide aussi pour avoir des noms sans emoji parfois
    "", "", "",
]
_SEPARATORS = [" ", " | ", " • ", " · ", " "]


def _capitalize_smart(s: str) -> str:
    """amelia -> Amélia (avec accent si pertinent)."""
    s = s.strip().lower()
    if not s:
        return ""
    # Petit accent automatique sur prenoms FR courants
    accents_map = {
        "amelia": "Amélia", "celia": "Célia", "emelia": "Émelia",
        "agathe": "Agathe", "agnes": "Agnès", "anais": "Anaïs",
        "andrea": "Andréa", "charlene": "Charlène", "chloe": "Chloé",
        "clemence": "Clémence", "elea": "Éléa", "eleonore": "Éléonore",
        "elise": "Élise", "eloise": "Éloïse", "elodie": "Élodie",
        "emilie": "Émilie", "ines": "Inès", "lea": "Léa",
        "noemie": "Noémie", "phebe": "Phébé", "renee": "Renée",
        "salome": "Salomé", "valerie": "Valérie", "zoe": "Zoé",
    }
    if s in accents_map:
        return accents_map[s]
    return s[0].upper() + s[1:]


def _get_diminutives(base: str) -> list:
    """Genere des diminutifs auto a partir d'un prenom.
    Ex: amelia -> ['ame', 'meli', 'lia', 'mel', 'amy']
        julia  -> ['jul', 'juju', 'lia', 'jule']
        sophia -> ['soph', 'sophie', 'sofy', 'phia']
    """
    base = base.lower().strip()
    if len(base) < 3:
        return []
    out = set()
    # 1. 3 premieres lettres
    out.add(base[:3])
    # 2. 4 premieres lettres
    if len(base) >= 4:
        out.add(base[:4])
    # 3. 3 dernieres lettres
    out.add(base[-3:])
    # 4. lettres milieu (chars 1-4)
    if len(base) >= 5:
        out.add(base[1:4])
    # 5. forme avec doublage premiere syllabe (juju, mimi, lolo, etc.)
    if len(base) >= 2:
        out.add(base[:2] + base[:2])
    # 6. diminutifs FR communs hardcoded pour certains prenoms
    known_dim = {
        "amelia": ["ame", "mel", "lia", "amy", "melie"],
        "julia": ["jul", "juju", "lia", "jules"],
        "sophia": ["soph", "sofy", "phia", "sophie"],
        "emma": ["em", "emmy", "emmi"],
        "lola": ["lo", "lolo"],
        "sarah": ["sara", "sass", "sasa"],
        "jessy": ["jess", "jessi"],
        "chloe": ["clo", "chlo", "chloe"],
        "lea": ["leya", "leaa"],
        "ines": ["ine", "nes"],
        "manon": ["mano", "manou"],
        "lucie": ["lulu", "luce", "lucy"],
        "camille": ["cam", "cami", "milie"],
        "marie": ["mary", "mariee"],
    }
    if base in known_dim:
        out.update(known_dim[base])
    # Filter : 2-7 chars, alpha only
    return [d for d in out if 2 <= len(d) <= 7 and d.isalpha()]


def generate_display_names(base: str, count: int = 5) -> list:
    """Genere `count` display names varies. Focus sur 'Prenom Nom' avec
    diminutifs + parfois emojis discrets."""
    first = _capitalize_smart(base)
    if not first:
        return []
    # Cree aussi des variants avec diminutifs (Amy Rose, Mel Stone, etc.)
    diminutives = _get_diminutives(base)
    first_variants = [first] + [_capitalize_smart(d) for d in diminutives]
    out = set()
    attempts = 0
    while len(out) < count and attempts < 60:
        attempts += 1
        # Choisit le prenom (de base ou diminutif)
        fv = random.choice(first_variants)
        last = random.choice(_LAST_NAMES)
        # Patterns (focus sur Prenom Nom)
        pattern = random.choices(
            ["first_last", "first_last", "first_last",  # 3x pour favoriser ce format
             "first_last_emoji", "first_only_emoji"],
            weights=[3, 3, 3, 1, 0.5],
        )[0]
        if pattern == "first_last":
            name = f"{fv} {last}"
        elif pattern == "first_last_emoji":
            emoji = random.choice([e for e in _NAME_EMOJIS if e])
            name = f"{fv} {last} {emoji}"
        else:  # first_only_emoji
            emoji = random.choice([e for e in _NAME_EMOJIS if e])
            name = f"{fv} {emoji}"
        out.add(name.strip())
    return list(out)[:count]


SHARED_BIOS_FILE = DATA_DIR / "bios.txt"


def _read_bios_at(path):
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    return [b.strip() for b in content.split("---") if b.strip()]


def random_bio_for(identity):
    """Try identity-specific bios first, fallback to shared bios."""
    if identity:
        bios = _read_bios_at(IDENTITIES_DIR / identity / "bios.txt")
        if bios:
            return unescape_newlines(random.choice(bios))
    bios = _read_bios_at(SHARED_BIOS_FILE)
    if bios:
        return unescape_newlines(random.choice(bios))
    return None


def _list_clean_videos(identity):
    """Liste les videos clean (hors .example) d'une identite."""
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return []
    return [
        p for p in videos_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]


def _video_meta(video):
    """Retourne (caption, description, example_path) pour une video donnee."""
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        try:
            caption = caption_path.read_text(encoding="utf-8").strip().replace("\\n", "\n")
        except Exception:
            pass
    if desc_path.exists():
        try:
            description = desc_path.read_text(encoding="utf-8").strip().replace("\\n", "\n")
        except Exception:
            pass
    example = None
    for ext in VIDEO_EXTS:
        candidate = video.parent / f"{video.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return caption, description, example


def random_n_reels_for(identity, n: int):
    """Pioche n reels uniques (sans remise). Retourne une liste de tuples
    (video, caption, description, example). Liste peut etre plus courte si pas assez.
    """
    videos = _list_clean_videos(identity)
    if not videos:
        return []
    n = min(n, len(videos))
    picked = random.sample(videos, n)
    return [(v, *_video_meta(v)) for v in picked]


def random_reel_for(identity):
    """Pick random clean video + caption + description + example_path|None.
    Returns (Path, caption|None, description|None, example_Path|None).
    Conserve pour la compatibilite (autopost.send_reel etc.).
    """
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None, None
    # Filtrer les videos clean (pas les .example.*)
    videos = [
        p for p in videos_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not videos:
        return None, None, None, None
    video = random.choice(videos)
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        caption = unescape_newlines(caption_path.read_text(encoding="utf-8").strip())
    if desc_path.exists():
        description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip())
    # Chercher la video exemple
    example = None
    for ext in VIDEO_EXTS:
        candidate = videos_dir / f"{video.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return video, caption, description, example


def random_profile_pic():
    if not PROFILE_PICS_DIR.exists():
        return None
    pics = [p for p in PROFILE_PICS_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(pics) if pics else None


def random_image_with_pair(directory):
    """Pick a random clean image + caption + description + example. Skips .example.* files."""
    if not directory.exists():
        return None, None, None, None
    images = [
        p for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not images:
        return None, None, None, None
    image = random.choice(images)
    cap_path = image.with_suffix(".txt")
    desc_path = image.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_path.read_text(encoding="utf-8").strip()) if cap_path.exists() else None
    description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip()) if desc_path.exists() else None
    example = None
    for ext in IMAGE_EXTS:
        candidate = directory / f"{image.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return image, caption, description, example


def random_post_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "posts")


def random_story_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "stories")


STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"


def random_story_cta_caption():
    if not STORY_CTA_CAPTIONS_FILE.exists():
        return None
    lines = [l.strip() for l in STORY_CTA_CAPTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return unescape_newlines(random.choice(lines)) if lines else None


def random_story_cta_image_for(identity):
    d = IDENTITIES_DIR / identity / "storyctas"
    if not d.exists():
        return None
    images = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(images) if images else None


def get_user_identity(user_id):
    users = load_json(USERS_FILE, {})
    data = users.get(str(user_id))
    if data is None:
        return None
    if isinstance(data, str):
        return data  # legacy format
    if isinstance(data, dict):
        return data.get("identity")
    return None


class GenLinkButton(discord.ui.DynamicItem[discord.ui.Button], template=r"genlink:(?P<uid>\d+)"):
    """Bouton « Générer le lien » sur une demande de lien. L'ID du VA est dans le
    custom_id -> persistant (marche même après un redémarrage du bot). Réservé staff.
    Au clic : génère le lien GMS et l'envoie dans le salon perso du VA."""

    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        super().__init__(
            discord.ui.Button(
                label="Générer le lien", emoji="🔗",
                style=discord.ButtonStyle.success,
                custom_id=f"genlink:{int(user_id)}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        uid = self.user_id
        # Bloc DUR anti-doublon (couche 1, locale) : ce VA a déjà eu un lien -> on refuse.
        _ex = _lr_existing(uid)
        if _ex:
            await _lr_send_blocked(interaction, uid, _ex.get("url", ""))
            return
        # Verrou anti double-clic : la génération est lente (réseau) ; on empêche
        # une 2e génération concurrente pour le même VA tant que celle-ci tourne.
        # (check + add sans await entre les deux -> atomique côté asyncio)
        if uid in _LINK_GEN_INFLIGHT:
            try:
                await interaction.followup.send(
                    "⏳ Une génération est déjà en cours pour ce VA — patiente quelques secondes.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return
        _LINK_GEN_INFLIGHT.add(uid)
        try:
            identity = get_user_identity(uid)
            if not identity:
                await interaction.followup.send("⚠️ Ce VA n'a pas d'identité assignée (`/adduser`).", ephemeral=True)
                return
            # Salon perso + handle du VA
            users = load_json(USERS_FILE, {})
            data = users.get(str(uid), {})
            ch_id = data.get("channel_id") if isinstance(data, dict) else None
            va_ch = interaction.client.get_channel(ch_id) if ch_id else None
            handle = ""
            if va_ch:
                m = re.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (va_ch.name or "").lower())
                handle = m.group(1) if m else ""
            if not handle:
                member = interaction.guild.get_member(uid) if interaction.guild else None
                handle = (getattr(member, "name", "") or "").lower()
            try:
                import gms
            except Exception as e:
                await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
                return
            # Bloc DUR anti-doublon (couche 2, GMS) : un lien va_@<handle> existe déjà
            # côté GetMySocial (ex: créé via le site). On utilise un match STRICT
            # (pas de substring) pour ne jamais bloquer un VA différent par erreur.
            if handle:
                try:
                    _all = await asyncio.to_thread(gms.list_all_links)
                except Exception:
                    _all = {"ok": False}
                # Fail-closed : si on ne peut pas vérifier, on n'invente pas un lien.
                if not _all.get("ok"):
                    await interaction.followup.send(
                        "⚠️ Impossible de vérifier sur GetMySocial pour l'instant (API indispo). "
                        "Génération annulée par sécurité (anti-doublon) — réessaie dans un instant.",
                        ephemeral=True,
                    )
                    return
                _hit = _gms_exact_link(handle, _all.get("links") or [])
                if _hit:
                    _sc = _hit.get("shortcode", "")
                    _u = f"{gms.PUBLIC_LINK_DOMAIN}/{_sc}" if _sc else ""
                    _lr_mark_generated(uid, _u, _hit.get("display_name", ""))
                    await _lr_send_blocked(interaction, uid, _u, source="gms")
                    return
            try:
                res = await asyncio.to_thread(gms.quick_generate_for_identity, identity, handle)
            except Exception as e:
                await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
                return
            if not res.get("ok"):
                await interaction.followup.send(f"❌ {res.get('error', 'Génération échouée')}", ephemeral=True)
                return
            url = res.get("public_url", "")
            _lr_mark_generated(uid, url, res.get("va_name", ""))  # bloc dur + clôt la demande
            if va_ch:
                try:
                    await va_ch.send(
                        f"🔗 **Voici ton lien GetMySocial :**\n{url}\n\n📲 Mets-le dans la bio de tes comptes Instagram."
                    )
                except Exception:
                    pass
            # Marque la demande comme traitée (retire le bouton)
            try:
                await interaction.message.edit(
                    content=f"✅ Lien généré par {interaction.user.mention} : {url}", view=None
                )
            except Exception:
                pass
            try:
                await interaction.followup.send(
                    f"✅ Lien généré pour <@{uid}> (`{identity}`) : {url}"
                    + (f"\n→ envoyé dans {va_ch.mention}" if va_ch else " (⚠️ salon VA introuvable — copie-le manuellement)"),
                    ephemeral=True,
                )
            except Exception:
                pass
        finally:
            _LINK_GEN_INFLIGHT.discard(uid)


class _SendProxy:
    """Imite interaction.response ET interaction.followup mais envoie dans un salon cible.
    Permet de réutiliser les commandes telles quelles en redirigeant leur sortie."""
    _OK = ("embed", "embeds", "file", "files", "view", "allowed_mentions", "tts")

    def __init__(self, channel):
        self._ch = channel

    def _clean(self, kw):
        return {k: v for k, v in kw.items() if k in self._OK}

    async def send(self, content=None, **kw):
        return await self._ch.send(content=content, **self._clean(kw))

    async def send_message(self, content=None, **kw):
        return await self._ch.send(content=content, **self._clean(kw))

    async def defer(self, *a, **k):
        return None

    def is_done(self):
        return True


class _ChannelProxy:
    """Faux 'interaction' qui route les sends d'une commande vers `channel`."""
    def __init__(self, real_interaction, channel):
        self._real = real_interaction
        self.channel = channel
        self.channel_id = channel.id
        self.user = real_interaction.user
        self.guild = getattr(real_interaction, "guild", None)
        self.client = getattr(real_interaction, "client", None)
        self.response = _SendProxy(channel)
        self.followup = _SendProxy(channel)

    def __getattr__(self, name):
        return getattr(self._real, name)


class UserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _va_channel(self, user_id):
        """Salon va- d'un VA depuis users.json (None si pas configuré)."""
        users = load_json(USERS_FILE, {})
        data = users.get(str(user_id))
        ch_id = data.get("channel_id") if isinstance(data, dict) else None
        return self.bot.get_channel(ch_id) if ch_id else None

    async def _central_run(self, interaction, cmd):
        """Bouton du menu CENTRAL : exécute la commande mais la sortie va dans le salon du VA."""
        identity = get_user_identity(interaction.user.id)
        target = self._va_channel(interaction.user.id)
        if not identity or target is None:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas de salon perso configuré. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ C'est parti — ton contenu arrive dans {target.mention} 👇", ephemeral=True
        )
        proxy = _ChannelProxy(interaction, target)
        try:
            await cmd.callback(self, proxy)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            except Exception:
                pass

    @app_commands.command(name="username", description="Génère des pseudos Instagram VRAIMENT dispo basés sur ton identité")
    async def username(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        # Defer car on va check ~20 URLs Instagram = quelques secondes
        await interaction.response.defer()
        try:
            available = await find_available_usernames(identity, max_check=30, want=5)
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Erreur lors du check Instagram : {e}\n"
                "Fallback sur la liste pré-définie :"
            )
            u = random_username_for(identity)
            if u:
                await interaction.followup.send(u)
            return
        if not available:
            # Tous pris -> fallback sur la liste manuelle
            u = random_username_for(identity)
            await interaction.followup.send(
                f"😬 Tous les pseudos auto-générés sont déjà pris pour `{identity}`. "
                + (f"Essaie celui-ci :\n`{u}`" if u else "Demande à un admin (`/addusernames`).")
            )
            return
        # Affichage des dispo
        lines = [
            f"✅ **{len(available)} pseudo(s) dispo sur Instagram** pour `{identity}` :",
            "",
        ]
        for u in available:
            lines.append(f"• `{u}`")
        lines.append("")
        lines.append("👉 Copie celui que tu veux et inscris-le sur Instagram.")
        lines.append("⚠️ Les pseudos sont checkés en temps réel — ils peuvent être pris à tout moment, prends rapidement.")
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="name", description="Donne 5 noms (display Instagram) variés avec nom de famille")
    async def name(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True
            )
            return
        # Genere 5 noms varies via le generateur
        names = generate_display_names(identity, count=5)
        if not names:
            # Fallback ancien systeme
            n = random_name_for(identity)
            if n:
                await interaction.response.send_message(n)
            else:
                await interaction.response.send_message(
                    f"Aucun nom pour ton identité `{identity}`.", ephemeral=True,
                )
            return
        lines = [f"✨ **5 noms pour `{identity}` :**", ""]
        for n in names:
            lines.append(f"• `{n}`")
        lines.append("")
        lines.append("👉 Copie celui qui te plait pour le display name Instagram.")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="insta", description="Enregistre tes 3 comptes Instagram (handles séparés par espace)")
    @app_commands.describe(
        handle1="@handle du 1er compte Insta",
        handle2="@handle du 2e compte Insta (optionnel)",
        handle3="@handle du 3e compte Insta (optionnel)",
    )
    async def insta(
        self,
        interaction: discord.Interaction,
        handle1: str,
        handle2: str = "",
        handle3: str = "",
    ):
        import re as _re_ig, json as _json_ig
        uid = str(interaction.user.id)

        def _norm(raw):
            if not raw:
                return ""
            h = raw.strip().lstrip("@").strip()
            h = _re_ig.sub(r"[^a-zA-Z0-9_.]", "", h).lower()
            return h if (h and len(h) <= 30) else ""

        handles = []
        seen = set()
        for raw in (handle1, handle2, handle3):
            n = _norm(raw)
            if n and n not in seen:
                seen.add(n)
                handles.append(n)
        if not handles:
            await interaction.response.send_message(
                "❌ Aucun handle valide. Format attendu : `@username` (lettres/chiffres/_./).",
                ephemeral=True,
            )
            return

        VA_INSTA_FILE_C = DATA_DIR / "va_insta_accounts.json"
        try:
            existing = _json_ig.loads(VA_INSTA_FILE_C.read_text(encoding="utf-8")) if VA_INSTA_FILE_C.exists() else {}
        except Exception:
            existing = {}
        existing[uid] = handles
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            VA_INSTA_FILE_C.write_text(_json_ig.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur de sauvegarde : {e}", ephemeral=True)
            return

        lines = [f"• @{h}" for h in handles]
        await interaction.response.send_message(
            "✅ Comptes Instagram enregistrés :\n" + "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(name="bio", description="Donne des bios Instagram de ton identité")
    @app_commands.describe(nombre="Combien de bios (1-10, défaut 3)")
    async def bio(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        bios, seen = [], set()
        for _ in range(nombre * 5):
            if len(bios) >= nombre:
                break
            b = random_bio_for(identity)
            if not b:
                break
            if b in seen:
                continue
            seen.add(b)
            bios.append(b)
        if not bios:
            await interaction.response.send_message(
                f"Aucune bio pour ton identité `{identity}`. Demande à un admin (`/addbios`).",
                ephemeral=True,
            )
            return
        if len(bios) == 1:
            await interaction.response.send_message(bios[0])
        else:
            msg = "💬 **Bios pour ton identité** (mets-en une différente par compte) :\n\n" + "\n\n".join(
                f"**Compte {i}.** {b}" for i, b in enumerate(bios, 1)
            )
            await interaction.response.send_message(msg[:2000])

    @app_commands.command(name="profilepic", description="Donne des photos de profil (transformées)")
    @app_commands.describe(nombre="Combien de photos (1-10, défaut 3)")
    async def profilepic(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        pics, seen = [], set()
        for _ in range(nombre * 5):
            if len(pics) >= nombre:
                break
            p = random_profile_pic()
            if not p:
                break
            if str(p) in seen:
                continue
            seen.add(str(p))
            pics.append(p)
        if not pics:
            await interaction.response.send_message(
                "Aucune photo de profil disponible. Demande à un admin (`/addprofilepic`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        cfg = load_image_config()
        n = len(pics)
        for i, pic in enumerate(pics, 1):
            tmp_dir = None
            send_path = pic
            try:
                if cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix="pp_")
                    tmp_path = Path(tmp_dir) / pic.name
                    if await asyncio.to_thread(transform_image, pic, tmp_path, cfg, "profile"):
                        send_path = tmp_path
                head = (
                    f"📸 **Photo de profil {i}/{n}** → une différente sur ton **compte n°{i}**"
                    if n > 1
                    else "📸 **Photo de profil**"
                )
                await interaction.followup.send(
                    f"{head}\n*Télécharge et upload sur Instagram.*",
                    file=discord.File(send_path),
                )
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    async def _send_image_content(self, interaction, kind_label, kind_target, random_fn, transform_cfg, count=3):
        """Generic handler pour /post et /story. Envoie `count` items DISTINCTS."""
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        # Recupere jusqu'a `count` images distinctes (best-effort)
        picks, seen = [], set()
        for _ in range(count * 5):
            if len(picks) >= count:
                break
            image, caption, description, example = random_fn(identity)
            if not image:
                break
            key = str(image)
            if key in seen:
                continue
            seen.add(key)
            picks.append((image, caption, description, example))
        if not picks:
            await interaction.response.send_message(
                f"Aucun {kind_label} pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        n = len(picks)
        for i, (image, caption, description, example) in enumerate(picks, 1):
            tmp_dir = None
            send_path = image
            try:
                if transform_cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix=f"{kind_target}_")
                    tmp_path = Path(tmp_dir) / image.name
                    if await asyncio.to_thread(transform_image, image, tmp_path, transform_cfg, kind_target):
                        send_path = tmp_path
                num = f" {i}/{n}" if n > 1 else ""
                if n > 1:
                    intro = (
                        f"🖼️ **{kind_label.upper()} {i}/{n}** → à poster sur ton **compte n°{i}** (`{identity}`)\n"
                        f"📥 Télécharge la photo CLEAN."
                    )
                else:
                    intro = f"🖼️ **{kind_label.upper()} — identité `{identity}`**\n📥 Télécharge la photo CLEAN."
                if example:
                    intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
                files = [discord.File(send_path, filename=image.name)]
                if example:
                    files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
                try:
                    await interaction.followup.send(content=intro, files=files)
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                    continue
                if caption:
                    await interaction.followup.send(
                        f"📝 **CAPTION {kind_label.upper()}{num}** (à écrire **PAR-DESSUS la photo**) :"
                    )
                    await interaction.followup.send(caption)
                if description:
                    await interaction.followup.send(
                        f"📄 **DESCRIPTION {kind_label.upper()}{num}** (à coller dans le **champ légende**) :"
                    )
                    await interaction.followup.send(description)
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    @app_commands.command(name="post", description="Génère 3 posts photo (photo + caption + description)")
    @app_commands.describe(nombre="Combien de posts (1-10, défaut 3)")
    async def post(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        cfg = load_image_config()
        await self._send_image_content(interaction, "post", "post", random_post_for, cfg, count=nombre)

    @app_commands.command(name="story", description="Génère 3 stories (photo + caption + description)")
    @app_commands.describe(nombre="Combien de stories (1-10, défaut 3)")
    async def story(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        cfg = load_image_config()
        await self._send_image_content(interaction, "story", "story", random_story_for, cfg, count=nombre)

    @app_commands.command(name="storycta", description="Génère des stories CTA: photo 1080x1920 + caption à écrire dessus")
    @app_commands.describe(nombre="Combien de stories CTA (1-10, défaut 3)")
    async def storycta(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True
            )
            return
        images, seen = [], set()
        for _ in range(nombre * 5):
            if len(images) >= nombre:
                break
            im = random_story_cta_image_for(identity)
            if not im:
                break
            if str(im) in seen:
                continue
            seen.add(str(im))
            images.append(im)
        if not images:
            await interaction.response.send_message(
                f"Aucune story CTA pour ton identité `{identity}`. Demande à un admin (`/addstorycta`).",
                ephemeral=True,
            )
            return
        if not random_story_cta_caption():
            await interaction.response.send_message(
                "Aucune caption disponible. Demande à un admin (`/addstoryctacaptions`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        cfg = load_image_config()
        n = len(images)
        for i, image in enumerate(images, 1):
            caption = random_story_cta_caption() or ""
            tmp_dir = None
            send_path = image
            try:
                if cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix="storycta_")
                    tmp_path = Path(tmp_dir) / image.name
                    if await asyncio.to_thread(transform_image, image, tmp_path, cfg, "storycta"):
                        send_path = tmp_path
                head = (
                    f"📲 **STORY CTA {i}/{n}** → pour ton **compte n°{i}** (`{identity}`)"
                    if n > 1
                    else f"📲 **STORY CTA — identité `{identity}`**"
                )
                intro = (
                    f"{head}\n"
                    f"📥 Télécharge la photo, écris la caption dessus en story.\n\n"
                    f"🕖 **À POSTER LE SOIR ENTRE 19H ET 23H** — c'est le créneau "
                    f"où tes clics convertissent le mieux 💰"
                )
                try:
                    await interaction.followup.send(content=intro, file=discord.File(send_path))
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                    continue
                if caption:
                    await interaction.followup.send(caption)
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    @app_commands.command(name="reel", description="Genere 3 reels (par defaut) : video clean + caption + description + exemple")
    @app_commands.describe(nombre="Combien de reels envoyer (1-10, defaut 3)")
    async def reel(
        self,
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 10] = 3,
    ):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        reels = random_n_reels_for(identity, nombre)
        if not reels:
            await interaction.response.send_message(
                f"Aucune vidéo pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        transform_cfg = load_transform_config()
        total = len(reels)

        # Message d'intro CLAIR : 1 reel different par compte + explication caption/description
        intro_global = (
            f"🎬 **{total} reels pour `{identity}` — {total} comptes**\n\n"
            f"🚨 **RÈGLE : 1 reel différent par compte.**\n"
            f"Poste **REEL 1** sur ton **compte 1**, **REEL 2** sur le **compte 2**, "
            f"**REEL 3** sur le **compte 3**.\n"
            f"⚠️ NE POSTE JAMAIS le même reel sur 2 comptes → duplicate content = shadowban.\n\n"
            f"📝 **Pour chaque reel je vais t'envoyer 2 textes :**\n"
            f"• **CAPTION** = le texte à écrire **PAR-DESSUS la vidéo** "
            f"(dans l'éditeur Insta, outil texte, en overlay sur le reel)\n"
            f"• **DESCRIPTION** = le texte à coller dans **le champ légende** du post "
            f"(en bas, là où Instagram demande 'Écrire une légende...')"
        )
        await interaction.followup.send(intro_global)

        if total < nombre:
            await interaction.followup.send(
                f"ℹ️ Seulement **{total}** reels disponibles pour `{identity}` "
                f"(tu en as demande {nombre})."
            )

        for idx, (video, caption, description, example) in enumerate(reels, start=1):
            intro = (
                f"🎬 **REEL {idx}/{total}** → à poster sur ton **compte n°{idx}** (`{identity}`)\n"
                f"📥 Télécharge la vidéo CLEAN."
            )
            if example:
                intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
            video_to_send = video  # toujours envoyer l'original
            files = [discord.File(video_to_send, filename=video.name)]
            if example:
                files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
            try:
                await interaction.followup.send(content=intro, files=files)
            except discord.HTTPException as e:
                if example and len(files) == 2:
                    try:
                        await interaction.followup.send(
                            content=intro + "\n\n⚠️ *(Vidéo exemple omise car trop lourde)*",
                            file=discord.File(video_to_send, filename=video.name),
                        )
                    except discord.HTTPException:
                        await interaction.followup.send(
                            f"⚠️ Reel {idx}: impossible d'envoyer (trop lourd): {e}"
                        )
                        continue
                else:
                    await interaction.followup.send(
                        f"⚠️ Reel {idx}: impossible d'envoyer (trop lourd): {e}"
                    )
                    continue
            if caption:
                await interaction.followup.send(
                    f"📝 **CAPTION REEL {idx}** (à mettre **PAR-DESSUS la vidéo** dans l'éditeur Insta) :"
                )
                await interaction.followup.send(caption)
            if description:
                await interaction.followup.send(
                    f"📄 **DESCRIPTION REEL {idx}** (à coller dans le **champ légende** du post) :"
                )
                await interaction.followup.send(description)

            # Suppression de la source si configuré
            if transform_cfg.get("delete_source_after_use", False):
                try:
                    video.unlink(missing_ok=True)
                    cap_p = video.with_suffix(".txt")
                    desc_p = video.with_suffix(".desc.txt")
                    cap_p.unlink(missing_ok=True)
                    desc_p.unlink(missing_ok=True)
                    if example:
                        example.unlink(missing_ok=True)
                except Exception:
                    pass

    async def cog_load(self):
        # Vue persistante : les boutons du menu marchent meme apres un redemarrage du bot
        try:
            self.bot.add_view(ContentMenuView(self))
            self.bot.add_view(CentralMenuView(self))
            self.bot.add_view(LinkPanelView())  # panneau "Générer un lien"
            self.bot.add_dynamic_items(GenLinkButton)  # bouton "Générer le lien" persistant
        except Exception:
            pass
        if not self.daily_menu.is_running():
            self.daily_menu.start()

    def cog_unload(self):
        try:
            self.daily_menu.cancel()
        except Exception:
            pass

    async def _post_menu(self, channel, identity, mention_user_id=None):
        """Poste le menu (embed + boutons) dans `channel`. @ping le VA si fourni."""
        content = f"<@{mention_user_id}> 👇 **Ton contenu du jour est prêt !**" if mention_user_id else None
        try:
            await channel.send(
                content=content,
                embed=_build_menu_embed(identity),
                view=ContentMenuView(self),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            return True
        except Exception:
            return False

    async def _push_menu_to_all_vas(self):
        """Poste le menu (avec @ping) dans le salon de chaque VA. Retourne le nb d'envois."""
        users = load_json(USERS_FILE, {})
        sent = 0
        for uid, data in users.items():
            ch_id = data.get("channel_id") if isinstance(data, dict) else None
            ident = (data.get("identity") if isinstance(data, dict)
                     else (data if isinstance(data, str) else None))
            if not ch_id or not ident:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch is None:
                continue
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                uid_int = None
            if await self._post_menu(ch, ident, mention_user_id=uid_int):
                sent += 1
        return sent

    @tasks.loop(time=_dt.time(hour=0, minute=0, tzinfo=_PARIS_TZ))
    async def daily_menu(self):
        """Chaque jour à MINUIT (heure FR) : poste le menu contenu (boutons)
        dans le salon de chaque VA, en le @pingant."""
        await self._push_menu_to_all_vas()

    @daily_menu.before_loop
    async def _before_daily_menu(self):
        await self.bot.wait_until_ready()

    # ===== Demande de lien : notification des managers =====

    async def _admin_ids(self):
        """IDs des managers à prévenir en DM : owner du bot + whitelist."""
        ids = set()
        try:
            app = await self.bot.application_info()
            if app and app.owner:
                ids.add(app.owner.id)
        except Exception:
            pass
        wl = load_json(WHITELIST_FILE, [])
        if isinstance(wl, list):
            for x in wl:
                try:
                    ids.add(int(x))
                except (TypeError, ValueError):
                    pass
        return ids

    async def _notify_managers_link_request(self, member, identity, guild):
        """Prévient les managers (salon + @rôle + DM) qu'un VA demande son lien."""
        cfg = load_json(LINK_REQ_CONFIG, {})
        ch_id = cfg.get("channel_id")
        role_id = cfg.get("role_id")
        name = getattr(member, "display_name", str(member))
        emb = discord.Embed(
            title="🔗 Demande de lien",
            description=f"{member.mention} (**{name}**) demande son lien.",
            color=discord.Color.orange(),
        )
        emb.add_field(name="Identité", value=f"`{identity}`", inline=True)
        emb.add_field(name="VA", value=member.mention, inline=True)
        emb.set_footer(text="Envoie-lui son lien GetMySocial.")

        # 1) Salon manager (+ ping rôle si configuré)
        ch = guild.get_channel(ch_id) if (guild and ch_id) else None
        if ch is None and guild:
            # Fallback : si pas configuré (/setliensalon), trouve un salon "demande-...-lien"
            ch = discord.utils.find(
                lambda c: "demande" in (c.name or "").lower() and "lien" in (c.name or "").lower(),
                guild.text_channels,
            )
        if ch is not None:
            ping = f"<@&{role_id}> " if role_id else ""
            view = discord.ui.View(timeout=None)
            try:
                view.add_item(GenLinkButton(member.id))
            except Exception:
                view = None
            try:
                await ch.send(
                    content=(ping + "nouvelle demande de lien").strip(),
                    embed=emb,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
            except Exception:
                pass

        # 2) DM aux managers (owner + whitelist)
        for aid in await self._admin_ids():
            try:
                u = self.bot.get_user(aid) or await self.bot.fetch_user(aid)
                if u:
                    await u.send(embed=emb)
            except Exception:
                pass

    async def request_link(self, interaction: discord.Interaction):
        """Le VA demande son lien → confirmation au VA + notif aux managers."""
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas d'identité assignée — demande à un admin.", ephemeral=True
            )
            return
        # Anti-spam : si une demande est déjà en attente, on ne reposte rien
        if _lr_is_pending(interaction.user.id):
            await interaction.response.send_message(
                "⏳ **Ta demande est déjà en attente** — un manager va t'envoyer ton lien. "
                "Pas besoin de re-cliquer 🙂",
                ephemeral=True,
            )
            return
        _lr_mark_pending(interaction.user.id)
        await interaction.response.send_message(
            "✅ **Demande envoyée aux managers !** Tu vas recevoir ton lien bientôt 🔗",
            ephemeral=True,
        )
        try:
            await self._notify_managers_link_request(
                interaction.user, identity, interaction.guild
            )
        except Exception:
            pass

    @app_commands.command(name="lien", description="Demande ton lien aux managers")
    async def lien(self, interaction: discord.Interaction):
        await self.request_link(interaction)

    @app_commands.command(
        name="menuall",
        description="[ADMIN] Pousse le menu contenu à TOUS les VAs maintenant (avec @ping)",
    )
    async def menuall(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message(
                "Réservé aux managers/admins.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        sent = await self._push_menu_to_all_vas()
        await interaction.followup.send(
            f"✅ Menu poussé à **{sent}** VA(s) (chacun @pingé dans son salon).",
            ephemeral=True,
        )

    @app_commands.command(
        name="panellien",
        description="[ADMIN] Poste ICI un panneau pour générer un lien GetMySocial en 1 clic",
    )
    async def panellien(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        emb = discord.Embed(
            title="🔗 Générateur de lien GetMySocial",
            description=(
                "Clique sur le bouton, entre l'**identité** (le modèle) et le **pseudo du VA**, "
                "et le lien est généré en 1 clic.\n"
                "Le lien est nommé `va_@pseudo`, et s'il existe un salon `va-pseudo`, il y est aussi envoyé."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, view=LinkPanelView())

    @app_commands.command(
        name="menucentral",
        description="[ADMIN] Poste ICI un menu central : chaque VA clique, le contenu arrive dans SON salon",
    )
    async def menucentral(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        emb = discord.Embed(
            title="🎛️ Menu contenu — clique, ça arrive dans TON salon",
            description=(
                "Clique un bouton ci-dessous : ton contenu est envoyé **dans ton salon perso `va-…`** "
                "(pas ici). Tu peux cliquer **autant de fois que tu veux**.\n\n"
                "🎬 **Reel** · 📖 **Story** · 🖼️ **Post** · 📲 **Story CTA**\n"
                "👤 **Pseudo** · 📝 **Name** · 💬 **Bio** · 🖼 **PP** · 🔗 **Demander un lien**\n\n"
                "⚠️ **Règles :** 1 reel différent par compte (jamais le même sur 2 comptes) · "
                "Story CTA **entre 19h et 23h** · suis ton onboarding (jour 0 → 6+)."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=emb, view=CentralMenuView(self))

    @app_commands.command(
        name="menupin",
        description="[ADMIN] Épingle un menu PERMANENT (h24) dans le salon de chaque VA",
    )
    async def menupin(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        users = load_json(USERS_FILE, {})
        pinned = 0
        for uid, data in users.items():
            ch_id = data.get("channel_id") if isinstance(data, dict) else None
            ident = (data.get("identity") if isinstance(data, dict)
                     else (data if isinstance(data, str) else None))
            if not ch_id or not ident:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch is None:
                continue
            try:
                # dépingle l'ancien menu permanent du bot (évite les doublons)
                try:
                    for pm in await ch.pins():
                        if (pm.author and pm.author.id == self.bot.user.id and pm.embeds
                                and "contenu du jour" in ((pm.embeds[0].title or "").lower())):
                            await pm.unpin(reason="remplacement menu permanent")
                except Exception:
                    pass
                msg = await ch.send(embed=_build_menu_embed(ident), view=ContentMenuView(self))
                await msg.pin(reason="Menu permanent VA (h24)")
                pinned += 1
                await asyncio.sleep(1.2)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[menupin] salon {ch_id} : {e}")
        await interaction.followup.send(
            f"📌 Menu permanent épinglé dans **{pinned}** salon(s) VA.\n"
            "→ Chaque VA a le menu en **message épinglé** en haut de son salon : il clique, le contenu arrive dans son salon (autant de fois qu'il veut).\n"
            "⚠️ Le bot a besoin de **Gérer les messages** pour épingler.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setliensalon",
        description="[ADMIN] Définit le salon où arrivent les demandes de lien",
    )
    @app_commands.describe(salon="Le salon manager qui reçoit les demandes de lien")
    async def setliensalon(self, interaction: discord.Interaction, salon: discord.TextChannel):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        cfg = load_json(LINK_REQ_CONFIG, {})
        cfg["channel_id"] = salon.id
        save_json(LINK_REQ_CONFIG, cfg)
        await interaction.response.send_message(
            f"✅ Les demandes de lien arriveront dans {salon.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="setlienrole",
        description="[ADMIN] Définit le rôle à ping pour les demandes de lien",
    )
    @app_commands.describe(role="Le rôle manager à @ping (laisse vide pour enlever le ping)")
    async def setlienrole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        cfg = load_json(LINK_REQ_CONFIG, {})
        cfg["role_id"] = role.id if role else None
        save_json(LINK_REQ_CONFIG, cfg)
        if role:
            await interaction.response.send_message(
                f"✅ Le rôle {role.mention} sera ping à chaque demande de lien.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message("✅ Ping de rôle désactivé.", ephemeral=True)

    @app_commands.command(
        name="menu",
        description="Menu contenu : reel / story / story CTA / pseudo / name en 1 clic",
    )
    async def menu(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas d'identité assignée — demande à un admin.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=_build_menu_embed(identity), view=ContentMenuView(self)
        )

    @app_commands.command(name="help", description="Affiche l'aide")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Aide — Commandes du bot",
            color=discord.Color.blurple(),
            description=(
                "**Commandes VA :**\n"
                "`/username` — un username Instagram de ton identité\n"
                "`/bio` — une bio Instagram de ton identité\n"
                "`/profilepic` — une photo de profil (pool partagé)\n"
                "`/reel` — un reel de ton identité + sa caption associée\n"
                "`/help` — cette aide\n\n"
                "**Onboarding :** suis les étapes dans ton salon (boutons →)."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ContentMenuView(discord.ui.View):
    """Menu de contenu cliquable. Chaque bouton sert le contenu correspondant
    pour l'identité du VA qui clique (réutilise les commandes existantes).
    Vue persistante (custom_id) : marche après un redémarrage du bot."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Reel", emoji="🎬", style=discord.ButtonStyle.primary, custom_id="cmenu:reel", row=0)
    async def b_reel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.reel.callback(self.cog, interaction)

    @discord.ui.button(label="Story", emoji="📖", style=discord.ButtonStyle.primary, custom_id="cmenu:story", row=0)
    async def b_story(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.story.callback(self.cog, interaction)

    @discord.ui.button(label="Post", emoji="🖼️", style=discord.ButtonStyle.primary, custom_id="cmenu:post", row=0)
    async def b_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.post.callback(self.cog, interaction)

    @discord.ui.button(label="Story CTA", emoji="📲", style=discord.ButtonStyle.primary, custom_id="cmenu:storycta", row=0)
    async def b_storycta(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.storycta.callback(self.cog, interaction)

    @discord.ui.button(label="Pseudo", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="cmenu:pseudo", row=1)
    async def b_pseudo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.username.callback(self.cog, interaction)

    @discord.ui.button(label="Name", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="cmenu:name", row=1)
    async def b_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.name.callback(self.cog, interaction)

    @discord.ui.button(label="Bio", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="cmenu:bio", row=1)
    async def b_bio(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.bio.callback(self.cog, interaction)

    @discord.ui.button(label="PP", emoji="🖼", style=discord.ButtonStyle.secondary, custom_id="cmenu:pp", row=1)
    async def b_pp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.profilepic.callback(self.cog, interaction)

    @discord.ui.button(label="Demander un lien", emoji="🔗", style=discord.ButtonStyle.success, custom_id="cmenu:lien", row=2)
    async def b_lien(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.request_link(interaction)


class CentralMenuView(discord.ui.View):
    """Menu CENTRAL (salon partagé type #commande-va) : chaque bouton envoie le
    contenu dans le SALON PERSO du VA qui clique (via _central_run). Persistant."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Reel", emoji="🎬", style=discord.ButtonStyle.primary, custom_id="cmenu2:reel", row=0)
    async def b_reel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.reel)

    @discord.ui.button(label="Story", emoji="📖", style=discord.ButtonStyle.primary, custom_id="cmenu2:story", row=0)
    async def b_story(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.story)

    @discord.ui.button(label="Post", emoji="🖼️", style=discord.ButtonStyle.primary, custom_id="cmenu2:post", row=0)
    async def b_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.post)

    @discord.ui.button(label="Story CTA", emoji="📲", style=discord.ButtonStyle.primary, custom_id="cmenu2:storycta", row=0)
    async def b_storycta(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.storycta)

    @discord.ui.button(label="Pseudo", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="cmenu2:pseudo", row=1)
    async def b_pseudo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.username)

    @discord.ui.button(label="Name", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="cmenu2:name", row=1)
    async def b_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.name)

    @discord.ui.button(label="Bio", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="cmenu2:bio", row=1)
    async def b_bio(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.bio)

    @discord.ui.button(label="PP", emoji="🖼", style=discord.ButtonStyle.secondary, custom_id="cmenu2:pp", row=1)
    async def b_pp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.profilepic)

    @discord.ui.button(label="Demander un lien", emoji="🔗", style=discord.ButtonStyle.success, custom_id="cmenu2:lien", row=2)
    async def b_lien(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.request_link(interaction)


class GenLinkModal(discord.ui.Modal, title="🔗 Générer un lien GetMySocial"):
    identite = discord.ui.TextInput(
        label="Identité (modèle)", placeholder="ex: sarah, amelia, julia…",
        required=True, max_length=40,
    )
    pseudo = discord.ui.TextInput(
        label="Pseudo du VA (pour nommer le lien)", placeholder="ex: ozen28 (optionnel)",
        required=False, max_length=40,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        ident = str(self.identite.value or "").strip().lower()
        handle = str(self.pseudo.value or "").strip().lstrip("@")
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        # Bloc DUR anti-doublon : si ce pseudo a déjà un lien va_@<handle>, on refuse.
        # Match STRICT (pas de substring) pour ne pas bloquer un pseudo voisin.
        if handle:
            try:
                _all = await asyncio.to_thread(gms.list_all_links)
            except Exception:
                _all = {"ok": False}
            if not _all.get("ok"):
                await interaction.followup.send(
                    "⚠️ Impossible de vérifier sur GetMySocial pour l'instant (API indispo). "
                    "Génération annulée par sécurité (anti-doublon) — réessaie dans un instant.",
                    ephemeral=True,
                )
                return
            _hit = _gms_exact_link(handle, _all.get("links") or [])
            if _hit:
                _sc = _hit.get("shortcode", "")
                _u = f"{gms.PUBLIC_LINK_DOMAIN}/{_sc}" if _sc else ""
                await interaction.followup.send(
                    f"🔒 **`@{handle}` a déjà un lien** — génération bloquée (anti-doublon)."
                    + (f"\n🔗 {_u}" if _u else "")
                    + "\n\n_Pour en recréer un, il faudra une commande dédiée (pas encore dispo)._",
                    ephemeral=True,
                )
                return
        try:
            res = await asyncio.to_thread(gms.quick_generate_for_identity, ident, handle)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        if not res.get("ok"):
            await interaction.followup.send(f"❌ {res.get('error', 'Génération échouée')}", ephemeral=True)
            return
        url = res.get("public_url", "")
        # Si un salon va-<pseudo> existe, on y dépose aussi le lien
        posted = ""
        if handle:
            import re as _re_h
            for g in interaction.client.guilds:
                vch = discord.utils.find(
                    lambda c: _re_h.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (c.name or "").lower())
                    and _re_h.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (c.name or "").lower()).group(1) == handle.lower(),
                    g.text_channels,
                )
                if vch:
                    try:
                        await vch.send(f"🔗 **Voici ton lien GetMySocial :**\n{url}\n\n📲 Mets-le dans la bio de tes comptes Instagram.")
                        posted = f"\n→ envoyé dans {vch.mention}"
                    except Exception:
                        pass
                    break
        await interaction.followup.send(
            f"✅ **Lien généré** — {res.get('va_name', '')} · identité `{ident}`\n"
            f"🔗 {url}\nShortcode `/{res.get('shortcode', '')}`{posted}",
            ephemeral=True,
        )


class LinkPanelView(discord.ui.View):
    """Panneau permanent : un bouton 'Générer un lien' qui ouvre le mini-formulaire."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Générer un lien", emoji="🔗", style=discord.ButtonStyle.success, custom_id="linkpanel:gen")
    async def gen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        await interaction.response.send_modal(GenLinkModal())


async def setup(bot):
    await bot.add_cog(UserCog(bot))
