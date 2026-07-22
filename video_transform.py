"""Video transformation module (ffmpeg-based).
Applies randomized transformations to videos to change metadata/perceptual fingerprint.
Used by /reel to give each VA a unique-looking copy of the same base video.
"""
import io
import json
import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "transform_config.json"

DEFAULT_CONFIG = {
    "enabled": False,  # desactive par defaut : envoie la video telle quelle
    "metadata_only": True,
    "delete_source_after_use": False,
    "framerate":      {"enabled": True,  "min": 30,   "max": 60},
    "video_bitrate_kbps": {"enabled": True, "min": 5000, "max": 6000},
    "audio_bitrate_kbps": {"enabled": True, "min": 128,  "max": 320},
    "saturation":     {"enabled": True,  "min": 0.95, "max": 0.95},
    "contrast":       {"enabled": True,  "min": 1.1,  "max": 1.1},
    "brightness":     {"enabled": True,  "min": 0.05, "max": 0.05},
    "gamma":          {"enabled": True,  "min": 1.1,  "max": 1.1},
    "vignette_angle": {"enabled": True,  "min": 0.25, "max": 0.5},
    "speed":          {"enabled": True,  "min": 1.03, "max": 1.04},
    "zoom":           {"enabled": True,  "min": 1.03, "max": 1.06},
    "noise_strength": {"enabled": True,  "min": 5,    "max": 5},
    "rotation_degrees": {"enabled": True, "min": 0.9, "max": 1.2},
    "cut_start_seconds": {"enabled": True, "min": 0.1, "max": 0.15},
    "cut_end_seconds":   {"enabled": True, "min": 0.1, "max": 0.15},
    # ── Options TikFusion supplémentaires (désactivées par défaut) ──
    "volume":           {"enabled": False, "min": 1.3,   "max": 1.6},   # gain audio
    "waveform_shift":   {"enabled": False, "min": 6,     "max": 6},     # décalage audio (ms)
    "pixel_shift":      {"enabled": False, "min": 3.5,   "max": 5.2},   # décalage image (px)
    "lens_correction":  {"enabled": False, "min": 0.008, "max": 0.01},  # distorsion objectif
    "hflip":            {"enabled": False},                              # miroir horizontal
    "dimensions":       {"enabled": False, "width": 1080, "height": 1920},  # taille fixe
    "random_us_metadata":     {"enabled": True},
    "random_9_16_dimensions": {"enabled": True},
}

IPHONE_MODELS = [
    "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
    "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max",
    "iPhone 17", "iPhone 17 Plus", "iPhone 17 Pro", "iPhone 17 Pro Max",
]

# Villes françaises AVEC coordonnées GPS réelles (lat, lon, altitude_m).
# Le GPS injecté doit matcher la ville affichée -> crédible si Meta recoupe
# le nom de ville et les coordonnées (un « Paris » à Marseille = drapeau rouge).
FRENCH_CITIES = {
    "Paris":             (48.8566, 2.3522, 35),
    "Marseille":         (43.2965, 5.3698, 12),
    "Lyon":              (45.7640, 4.8357, 170),
    "Toulouse":          (43.6047, 1.4442, 146),
    "Nice":              (43.7102, 7.2620, 10),
    "Nantes":            (47.2184, -1.5536, 8),
    "Strasbourg":        (48.5734, 7.7521, 142),
    "Montpellier":       (43.6108, 3.8767, 27),
    "Bordeaux":          (44.8378, -0.5792, 6),
    "Lille":             (50.6292, 3.0573, 23),
    "Rennes":            (48.1173, -1.6778, 52),
    "Reims":             (49.2583, 4.0317, 83),
    "Le Havre":          (49.4944, 0.1079, 5),
    "Toulon":            (43.1242, 5.9280, 10),
    "Saint-Étienne":     (45.4397, 4.3872, 516),
    "Grenoble":          (45.1885, 5.7245, 212),
    "Dijon":             (47.3220, 5.0415, 245),
    "Angers":            (47.4784, -0.5632, 20),
    "Nîmes":             (43.8367, 4.3601, 39),
    "Le Mans":           (48.0061, 0.1996, 51),
    "Aix-en-Provence":   (43.5297, 5.4474, 173),
    "Clermont-Ferrand":  (45.7772, 3.0870, 321),
    "Brest":             (48.3904, -4.4861, 34),
    "Tours":             (47.3941, 0.6848, 48),
    "Limoges":           (45.8336, 1.2611, 209),
    "Amiens":            (49.8941, 2.2957, 32),
    "Perpignan":         (42.6887, 2.8948, 42),
    "Metz":              (49.1193, 6.1757, 173),
    "Besançon":          (47.2378, 6.0241, 250),
    "Orléans":           (47.9029, 1.9093, 116),
    "Rouen":             (49.4432, 1.0999, 12),
    "Caen":              (49.1829, -0.3707, 8),
    "Nancy":             (48.6921, 6.1844, 200),
    "Avignon":           (43.9493, 4.8055, 23),
    "Poitiers":          (46.5802, 0.3404, 116),
    "La Rochelle":       (46.1591, -1.1520, 5),
    "Cannes":            (43.5528, 7.0174, 11),
    "Antibes":           (43.5808, 7.1251, 21),
    "Béziers":           (43.3442, 3.2158, 17),
    "Bourges":           (47.0810, 2.3988, 130),
    "Mérignac":          (44.8386, -0.6436, 30),
    "Pau":               (43.2951, -0.3708, 200),
    "Bayonne":           (43.4929, -1.4748, 15),
    "Biarritz":          (43.4832, -1.5586, 19),
    "Lorient":           (47.7485, -3.3702, 12),
    "Saint-Malo":        (48.6493, -2.0257, 7),
    "Annecy":            (45.8992, 6.1294, 447),
    "Chambéry":          (45.5646, 5.9178, 270),
    "Valence":           (44.9334, 4.8924, 126),
    "Vannes":            (47.6582, -2.7608, 20),
    "Quimper":           (47.9960, -4.0973, 20),
    "Arles":             (43.6768, 4.6277, 10),
    "Fréjus":            (43.4332, 6.7370, 22),
    "Hyères":            (43.1204, 6.1287, 40),
    "Saint-Tropez":      (43.2727, 6.6386, 10),
    "Deauville":         (49.3600, 0.0756, 3),
    "La Baule":          (47.2860, -2.3908, 6),
    "Honfleur":          (49.4189, 0.2337, 8),
    "Lourdes":           (43.0942, -0.0459, 420),
    "Colmar":            (48.0794, 7.3585, 194),
    "Mulhouse":          (47.7508, 7.3359, 240),
    "Versailles":        (48.8014, 2.1301, 132),
    "Saint-Nazaire":     (47.2733, -2.2135, 5),
    "Tarbes":            (43.2328, 0.0783, 304),
    "Niort":             (46.3239, -0.4587, 20),
    "Cherbourg":         (49.6386, -1.6164, 10),
}

_IOS_BY_MODEL = {
    "iPhone 15":         ["17.0", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "18.0", "18.1", "18.2"],
    "iPhone 15 Plus":    ["17.0", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "18.0", "18.1", "18.2", "18.3"],
    "iPhone 15 Pro":     ["17.0", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "18.0", "18.1", "18.2", "18.3", "18.4"],
    "iPhone 15 Pro Max": ["17.0", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "18.0", "18.1", "18.2", "18.3", "18.4", "18.5"],
    "iPhone 16":         ["18.0", "18.1", "18.2", "18.3", "18.4", "18.5", "19.0", "19.1"],
    "iPhone 16 Plus":    ["18.0", "18.1", "18.2", "18.3", "18.4", "18.5", "18.6", "19.0", "19.1"],
    "iPhone 16 Pro":     ["18.0", "18.1", "18.2", "18.3", "18.4", "18.5", "18.6", "19.0", "19.1", "19.2"],
    "iPhone 16 Pro Max": ["18.0", "18.1", "18.2", "18.3", "18.4", "18.5", "18.6", "19.0", "19.1", "19.2", "19.3"],
    "iPhone 17":         ["19.0", "19.1", "19.2", "19.3"],
    "iPhone 17 Plus":    ["19.0", "19.1", "19.2", "19.3", "19.4"],
    "iPhone 17 Pro":     ["19.0", "19.1", "19.2", "19.3", "19.4"],
    "iPhone 17 Pro Max": ["19.0", "19.1", "19.2", "19.3", "19.4", "19.5"],
}


def random_metadata_preset():
    """Génère un preset aléatoire à la volée : iPhone + iOS cohérent + ville
    française + GPS RÉEL de cette ville (avec un léger jitter ~±300 m pour que
    deux vidéos « de Paris » ne pointent pas au mètre près au même endroit).
    Variété = 12 modèles × ~66 villes × ~10 iOS = 7000+ combinaisons."""
    model = random.choice(IPHONE_MODELS)
    city = random.choice(list(FRENCH_CITIES.keys()))
    lat0, lon0, alt0 = FRENCH_CITIES[city]
    lat = lat0 + random.uniform(-0.003, 0.003)   # ~±330 m
    lon = lon0 + random.uniform(-0.004, 0.004)
    # max(0) : jamais d'altitude négative (irréaliste + casserait le format ISO6709)
    alt = round(max(0.0, alt0 + random.uniform(-5, 15)), 3)
    software = random.choice(_IOS_BY_MODEL.get(model, ["18.0"]))
    return {
        "make": "Apple",
        "model": model,
        "software": software,
        "location": f"{city}, France",
        "location_str": f"{city}, France",  # alias (rétro-compat _transform_metadata_only)
        "lat": lat,
        "lon": lon,
        "alt": alt,
    }


# Backward compat: keep a small sample for any code that imports the constant
US_METADATA_PRESETS = [random_metadata_preset() for _ in range(20)]

# Common phone resolutions in 9:16 portrait
RANDOM_9_16_DIMS = [
    (720, 1280),   # 720p
    (1080, 1920),  # 1080p
    (828, 1792),   # iPhone XR/11
    (1170, 2532),  # iPhone 13/14
    (1080, 2340),  # Samsung S22
    (1080, 2400),  # Samsung S23
]


def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        # Merge defaults pour les nouvelles clés non encore dans le fichier
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(cfg)
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def reset_config():
    save_config(DEFAULT_CONFIG)


def is_ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _rand(min_v, max_v):
    if min_v == max_v:
        return min_v
    return random.uniform(float(min_v), float(max_v))


def _ffprobe_duration(path):
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _has_audio(path) -> bool:
    """True si le fichier a au moins une piste audio (évite d'ajouter des
    -metadata:s:a:0 sur une vidéo muette, ce qui ferait planter ffmpeg)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _apple_container_args(has_audio: bool):
    """handler_name = 'Core Media Video'/'Core Media Audio', comme un vrai iPhone.
    (Le mouchard `encoder=Lavf…` que TikFusion laisse traîner est effacé à part,
    via -bitexact en option de sortie — validé sur une vraie vidéo iPhone.)"""
    args = ["-metadata:s:v:0", "handler_name=Core Media Video"]
    if has_audio:
        args += ["-metadata:s:a:0", "handler_name=Core Media Audio"]
    return args


def _transform_metadata_only(input_path, output_path, config, timeout):
    """Mode rapide: remux + changement de metadata, pas de re-encodage."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(input_path)]
    cmd.extend(["-c", "copy", "-map_metadata", "-1"])
    if config.get("random_us_metadata", {}).get("enabled"):
        from datetime import datetime, timedelta
        meta = random_metadata_preset()
        rand_date = datetime.now() - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23))
        creation_time = rand_date.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        # creationdate Apple = heure LOCALE avec offset (+0200), pas UTC "Z"
        creationdate = rand_date.strftime("%Y-%m-%dT%H:%M:%S+0200")
        lat_sign = "+" if meta["lat"] >= 0 else "-"
        lon_sign = "+" if meta["lon"] >= 0 else "-"
        alt_sign = "+" if meta["alt"] >= 0 else "-"
        # Format Apple exact : lat 2 chiffres, lon 3 chiffres, alt 3 chiffres,
        # chaque valeur avec SON signe (ex: +44.8363-000.5792+009.990/).
        iso6709 = f"{lat_sign}{abs(meta['lat']):07.4f}{lon_sign}{abs(meta['lon']):08.4f}{alt_sign}{abs(meta['alt']):07.3f}/"
        cmd.extend([
            "-metadata", f"com.apple.quicktime.location.ISO6709={iso6709}",
            "-metadata", f"com.apple.quicktime.make={meta['make']}",
            "-metadata", f"com.apple.quicktime.model={meta['model']}",
            "-metadata", f"com.apple.quicktime.software={meta['software']}",
            "-metadata", f"com.apple.quicktime.creationdate={creationdate}",
            "-metadata", f"make={meta['make']}",
            "-metadata", f"model={meta['model']}",
            "-metadata", f"creation_time={creation_time}",
        ])
    cmd.extend(_apple_container_args(_has_audio(input_path)))
    # use_metadata_tags : écrit les atomes com.apple.quicktime.* (sinon MP4 les
    # jette). -bitexact : efface le tag encoder=Lavf (le mouchard ffmpeg).
    cmd.extend(["-movflags", "use_metadata_tags+faststart", "-bitexact", str(output_path)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False


def transform_video(input_path, output_path, config=None, timeout=180):
    """Apply transformations to a video using ffmpeg. Returns True on success, False on failure."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    if config is None:
        config = load_config()

    if not config.get("enabled", True):
        shutil.copy2(input_path, output_path)
        return True

    if not is_ffmpeg_available():
        shutil.copy2(input_path, output_path)
        return True

    # Mode rapide: remux + metadata seulement (defaut)
    if config.get("metadata_only", True):
        ok = _transform_metadata_only(input_path, output_path, config, timeout=30)
        if ok:
            return True
        # Si echec, fallback copie directe
        try:
            shutil.copy2(input_path, output_path)
            return True
        except Exception:
            return False

    # Mode complet (re-encodage avec tous les filtres)
    video_filters = []
    audio_filters = []

    # Speed (video PTS + audio tempo)
    speed = 1.0
    if config.get("speed", {}).get("enabled"):
        c = config["speed"]
        speed = _rand(c["min"], c["max"])

    # eq filter (brightness, contrast, saturation, gamma)
    eq_parts = []
    if config.get("brightness", {}).get("enabled"):
        eq_parts.append(f"brightness={_rand(config['brightness']['min'], config['brightness']['max']):.3f}")
    if config.get("contrast", {}).get("enabled"):
        eq_parts.append(f"contrast={_rand(config['contrast']['min'], config['contrast']['max']):.3f}")
    if config.get("saturation", {}).get("enabled"):
        eq_parts.append(f"saturation={_rand(config['saturation']['min'], config['saturation']['max']):.3f}")
    if config.get("gamma", {}).get("enabled"):
        eq_parts.append(f"gamma={_rand(config['gamma']['min'], config['gamma']['max']):.3f}")
    if eq_parts:
        video_filters.append("eq=" + ":".join(eq_parts))

    # Vignette
    if config.get("vignette_angle", {}).get("enabled"):
        angle = _rand(config["vignette_angle"]["min"], config["vignette_angle"]["max"])
        video_filters.append(f"vignette=angle={angle:.3f}")

    # Noise
    if config.get("noise_strength", {}).get("enabled"):
        strength = int(_rand(config["noise_strength"]["min"], config["noise_strength"]["max"]))
        if strength > 0:
            video_filters.append(f"noise=alls={strength}:allf=t")

    # Pixel shift : décale l'image de quelques px (crop décentré + pad) -> le
    # cadrage bouge légèrement = empreinte différente. Dimensions préservées.
    if config.get("pixel_shift", {}).get("enabled"):
        s = max(1, int(round(_rand(config["pixel_shift"]["min"], config["pixel_shift"]["max"]))))
        dx = random.randint(-s, s)
        dy = random.randint(-s, s)
        video_filters.append(
            f"crop=iw-{2*s}:ih-{2*s}:{s+dx}:{s+dy},pad=iw+{2*s}:ih+{2*s}:{s}:{s}:black")

    # Lens correction : légère distorsion d'objectif (comme un vrai téléphone)
    if config.get("lens_correction", {}).get("enabled"):
        k = _rand(config["lens_correction"]["min"], config["lens_correction"]["max"])
        video_filters.append(f"lenscorrection=cx=0.5:cy=0.5:k1={k:.4f}:k2={k:.4f}")

    # Flip horizontal (miroir)
    if config.get("hflip", {}).get("enabled"):
        video_filters.append("hflip")

    # Rotation (small degrees, in radians for ffmpeg rotate filter)
    if config.get("rotation_degrees", {}).get("enabled"):
        deg = _rand(config["rotation_degrees"]["min"], config["rotation_degrees"]["max"])
        # Random sign so it can tilt either direction
        if random.random() < 0.5:
            deg = -deg
        rad = math.radians(deg)
        video_filters.append(f"rotate={rad:.5f}:ow=iw:oh=ih:c=black")

    # Zoom: scale up then crop back to original size
    if config.get("zoom", {}).get("enabled"):
        z = _rand(config["zoom"]["min"], config["zoom"]["max"])
        video_filters.append(f"scale=trunc(iw*{z:.3f}/2)*2:trunc(ih*{z:.3f}/2)*2,crop=trunc(iw/{z:.3f}/2)*2:trunc(ih/{z:.3f}/2)*2")

    # Random 9:16 dimensions
    if config.get("random_9_16_dimensions", {}).get("enabled"):
        w, h = random.choice(RANDOM_9_16_DIMS)
        video_filters.append(f"scale={w}:{h}:flags=lanczos")

    # Dimensions FIXES (taille imposée) — appliqué en DERNIER, écrase le 9:16
    if config.get("dimensions", {}).get("enabled"):
        dc = config["dimensions"]
        dw = int(dc.get("width", 1080))
        dh = int(dc.get("height", 1920))
        # force paire (libx264) + lanczos
        dw -= dw % 2
        dh -= dh % 2
        video_filters.append(f"scale={dw}:{dh}:flags=lanczos")

    # Speed (video PTS)
    if abs(speed - 1.0) > 1e-6:
        video_filters.append(f"setpts={1.0 / speed:.5f}*PTS")
        # atempo accepts 0.5-100 in newer ffmpeg, but to be safe we cap
        audio_filters.append(f"atempo={speed:.5f}")

    # Volume (gain audio)
    if config.get("volume", {}).get("enabled"):
        vol = _rand(config["volume"]["min"], config["volume"]["max"])
        audio_filters.append(f"volume={vol:.3f}")

    # Waveform shift : petit décalage temporel de l'audio (ms) = signature audio
    # différente (l'onde n'est plus alignée au bit près avec l'original).
    if config.get("waveform_shift", {}).get("enabled"):
        ms = max(1, int(_rand(config["waveform_shift"]["min"], config["waveform_shift"]["max"])))
        audio_filters.append(f"adelay={ms}|{ms}")

    # Build ffmpeg command
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # Cut start
    cut_start = 0.0
    if config.get("cut_start_seconds", {}).get("enabled"):
        cut_start = _rand(config["cut_start_seconds"]["min"], config["cut_start_seconds"]["max"])
    if cut_start > 0:
        cmd.extend(["-ss", f"{cut_start:.3f}"])

    cmd.extend(["-i", str(input_path)])

    # Cut end (need duration)
    cut_end = 0.0
    if config.get("cut_end_seconds", {}).get("enabled"):
        cut_end = _rand(config["cut_end_seconds"]["min"], config["cut_end_seconds"]["max"])
    if cut_end > 0:
        total = _ffprobe_duration(input_path)
        if total is not None:
            new_duration = total - cut_start - cut_end
            if new_duration > 0:
                cmd.extend(["-t", f"{new_duration:.3f}"])

    # Apply filters
    if video_filters:
        cmd.extend(["-vf", ",".join(video_filters)])
    if audio_filters:
        cmd.extend(["-af", ",".join(audio_filters)])

    # Framerate
    if config.get("framerate", {}).get("enabled"):
        fr = int(_rand(config["framerate"]["min"], config["framerate"]["max"]))
        cmd.extend(["-r", str(fr)])

    # Video bitrate
    if config.get("video_bitrate_kbps", {}).get("enabled"):
        br = int(_rand(config["video_bitrate_kbps"]["min"], config["video_bitrate_kbps"]["max"]))
        cmd.extend(["-b:v", f"{br}k"])

    # Audio bitrate (randomisé si activé, sinon 192k par défaut) -> piste audio
    # au bitrate variable = signature audio différente à chaque export.
    abr = 192
    if config.get("audio_bitrate_kbps", {}).get("enabled"):
        abr = int(_rand(config["audio_bitrate_kbps"]["min"], config["audio_bitrate_kbps"]["max"]))

    # Codec settings (rapid + bonne qualite)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-threads", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", f"{abr}k",
        # use_metadata_tags : écrit les atomes com.apple.quicktime.* dans le MP4
        "-movflags", "use_metadata_tags+faststart",
    ])

    # Métadonnées iPhone (make/model/software/GPS/dates) — jeu RÉALISTE, aligné
    # sur une vraie vidéo iPhone (pas de faux title/comment/encoder).
    if config.get("random_us_metadata", {}).get("enabled"):
        meta = random_metadata_preset()
        from datetime import datetime, timedelta
        rand_date = datetime.now() - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23))
        creation_time = rand_date.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        creationdate = rand_date.strftime("%Y-%m-%dT%H:%M:%S+0200")
        lat_sign = "+" if meta["lat"] >= 0 else "-"
        lon_sign = "+" if meta["lon"] >= 0 else "-"
        alt_sign = "+" if meta["alt"] >= 0 else "-"
        # Format Apple exact : lat 2 chiffres, lon 3 chiffres, alt 3 chiffres,
        # chaque valeur avec SON signe (ex: +44.8363-000.5792+009.990/).
        iso6709 = f"{lat_sign}{abs(meta['lat']):07.4f}{lon_sign}{abs(meta['lon']):08.4f}{alt_sign}{abs(meta['alt']):07.3f}/"
        cmd.extend([
            "-map_metadata", "-1",
            "-metadata", f"com.apple.quicktime.location.ISO6709={iso6709}",
            "-metadata", f"com.apple.quicktime.make={meta['make']}",
            "-metadata", f"com.apple.quicktime.model={meta['model']}",
            "-metadata", f"com.apple.quicktime.software={meta['software']}",
            "-metadata", f"com.apple.quicktime.creationdate={creationdate}",
            "-metadata", f"make={meta['make']}",
            "-metadata", f"model={meta['model']}",
            "-metadata", f"creation_time={creation_time}",
        ])
    else:
        cmd.extend(["-map_metadata", "-1"])
    cmd.extend(_apple_container_args(_has_audio(input_path)))
    # -bitexact : efface le tag encoder=Lavf (+ le SEI x264) = zéro signature
    # ffmpeg/x264 dans le fichier (là où TikFusion laisse le sien).
    cmd.extend(["-bitexact", str(output_path)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            # Log error to a debug file
            try:
                debug_log = DATA_DIR / "transform_errors.log"
                debug_log.parent.mkdir(parents=True, exist_ok=True)
                with debug_log.open("a", encoding="utf-8") as f:
                    f.write(f"--- {input_path} -> {output_path} ---\n")
                    f.write("CMD: " + " ".join(cmd) + "\n")
                    f.write("STDERR: " + (result.stderr or "")[:2000] + "\n\n")
            except Exception:
                pass
            return False
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def config_summary_text(config=None):
    """Return a markdown summary of the current config."""
    if config is None:
        config = load_config()
    lines = []
    enabled_global = config.get("enabled", True)
    delete_after = config.get("delete_source_after_use", False)
    lines.append(f"**Transformation activée :** {'✅' if enabled_global else '❌'}")
    lines.append(f"**Supprimer la vidéo source après envoi :** {'✅' if delete_after else '❌'}")
    lines.append("")
    lines.append("**Paramètres :**")
    for key, value in config.items():
        if key in ("enabled", "delete_source_after_use"):
            continue
        if isinstance(value, dict):
            en = value.get("enabled", True)
            mark = "✅" if en else "❌"
            if "min" in value:
                lines.append(f"{mark} `{key}` : {value['min']} → {value['max']}")
            else:
                lines.append(f"{mark} `{key}`")
    return "\n".join(lines)
