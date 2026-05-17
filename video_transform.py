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
    "enabled": True,
    "delete_source_after_use": False,
    "framerate":      {"enabled": True,  "min": 30,   "max": 60},
    "video_bitrate_kbps": {"enabled": True, "min": 5000, "max": 6000},
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
    "random_us_metadata":     {"enabled": True},
    "random_9_16_dimensions": {"enabled": True},
}

IPHONE_MODELS = [
    "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
    "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max",
    "iPhone 17", "iPhone 17 Plus", "iPhone 17 Pro", "iPhone 17 Pro Max",
]

FRENCH_CITIES = [
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Strasbourg",
    "Montpellier", "Bordeaux", "Lille", "Rennes", "Reims", "Le Havre", "Toulon",
    "Saint-Étienne", "Grenoble", "Dijon", "Angers", "Nîmes", "Villeurbanne",
    "Saint-Denis", "Le Mans", "Aix-en-Provence", "Clermont-Ferrand", "Brest",
    "Tours", "Limoges", "Amiens", "Perpignan", "Metz", "Besançon",
    "Boulogne-Billancourt", "Orléans", "Mulhouse", "Rouen", "Caen", "Nancy",
    "Argenteuil", "Montreuil", "Roubaix", "Dunkerque", "Tourcoing", "Nanterre",
    "Avignon", "Vitry-sur-Seine", "Créteil", "Versailles", "Courbevoie",
    "Asnières-sur-Seine", "Poitiers", "Colombes", "Aulnay-sous-Bois",
    "La Rochelle", "Calais", "Cannes", "Antibes", "Béziers", "Champigny-sur-Marne",
    "Bourges", "La Seyne-sur-Mer", "Mérignac", "Rueil-Malmaison", "Pessac",
    "Saint-Nazaire", "Saint-Quentin", "Tarbes", "Quimper", "Annecy", "Niort",
    "Beauvais", "Cholet", "Valence", "Vannes", "Chambéry", "Évreux", "Pau",
    "Bayonne", "Biarritz", "Lorient", "Saint-Malo", "Charleville-Mézières",
    "Albi", "Castres", "Carcassonne", "Sète", "Arles", "Fréjus", "Cagnes-sur-Mer",
    "Hyères", "Salon-de-Provence", "Saint-Brieuc", "Beauvais", "Châteauroux",
    "Lourdes", "Cherbourg", "Saint-Tropez", "Deauville", "La Baule", "Honfleur",
]

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
    """Generate a random preset on the fly. Variety = 12 models x 95 cities x ~10 iOS = 11000+."""
    model = random.choice(IPHONE_MODELS)
    city = random.choice(FRENCH_CITIES)
    software = random.choice(_IOS_BY_MODEL.get(model, ["18.0"]))
    return {
        "make": "Apple",
        "model": model,
        "software": software,
        "location": f"{city}, France",
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
        # ffmpeg missing: fallback to direct copy
        shutil.copy2(input_path, output_path)
        return True

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

    # Random 9:16 dimensions (applied last)
    if config.get("random_9_16_dimensions", {}).get("enabled"):
        w, h = random.choice(RANDOM_9_16_DIMS)
        video_filters.append(f"scale={w}:{h}:flags=lanczos")

    # Speed (video PTS)
    if abs(speed - 1.0) > 1e-6:
        video_filters.append(f"setpts={1.0 / speed:.5f}*PTS")
        # atempo accepts 0.5-100 in newer ffmpeg, but to be safe we cap
        audio_filters.append(f"atempo={speed:.5f}")

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

    # Codec settings (good quality)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
    ])

    # Random metadata (iPhone + ville française + GPS + dates)
    if config.get("random_us_metadata", {}).get("enabled"):
        meta = random_metadata_preset()
        from datetime import datetime, timedelta
        rand_date = datetime.now() - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23))
        creation_time = rand_date.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        # ISO 6709 format pour la localisation Apple: +48.8566+002.3522/
        lat_sign = "+" if meta["lat"] >= 0 else "-"
        lon_sign = "+" if meta["lon"] >= 0 else "-"
        iso6709 = f"{lat_sign}{abs(meta['lat']):08.4f}{lon_sign}{abs(meta['lon']):09.4f}+{meta['alt']:.3f}/"
        cmd.extend([
            "-map_metadata", "-1",
            "-metadata", f"title=IMG_{random.randint(1000, 9999)}",
            "-metadata", f"location={meta['location']}",
            "-metadata", f"location-eng={meta['location']}",
            "-metadata", f"com.apple.quicktime.location.ISO6709={iso6709}",
            "-metadata", f"com.apple.quicktime.make={meta['make']}",
            "-metadata", f"com.apple.quicktime.model={meta['model']}",
            "-metadata", f"com.apple.quicktime.software={meta['software']}",
            "-metadata", f"com.apple.quicktime.creationdate={creation_time}",
            "-metadata", f"make={meta['make']}",
            "-metadata", f"model={meta['model']}",
            "-metadata", f"software={meta['software']}",
            "-metadata", f"creation_time={creation_time}",
            "-metadata", f"date={rand_date.strftime('%Y-%m-%d')}",
            "-metadata", f"comment=Shot on {meta['model']}",
            "-metadata", f"encoder=Apple {meta['model']}",
        ])
    else:
        cmd.extend(["-map_metadata", "-1"])

    cmd.append(str(output_path))

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
