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

US_METADATA_PRESETS = [
    {"location": "New York, NY, USA", "make": "Apple",   "model": "iPhone 14 Pro",       "software": "16.0"},
    {"location": "Los Angeles, CA, USA", "make": "Apple", "model": "iPhone 13",           "software": "15.4"},
    {"location": "Miami, FL, USA",       "make": "Samsung","model": "Galaxy S23",         "software": "13.0"},
    {"location": "Chicago, IL, USA",     "make": "Apple",  "model": "iPhone 14",          "software": "16.2"},
    {"location": "Austin, TX, USA",      "make": "Google", "model": "Pixel 7",            "software": "13.0"},
    {"location": "Seattle, WA, USA",     "make": "Apple",  "model": "iPhone 12 Pro Max",  "software": "15.7"},
    {"location": "San Francisco, CA, USA","make": "Samsung","model": "Galaxy S22",        "software": "12.0"},
    {"location": "Boston, MA, USA",      "make": "Apple",  "model": "iPhone 14 Plus",     "software": "16.1"},
    {"location": "Houston, TX, USA",     "make": "Apple",  "model": "iPhone 13 Pro",      "software": "15.6"},
    {"location": "Phoenix, AZ, USA",     "make": "Samsung","model": "Galaxy Note 20",     "software": "11.0"},
    {"location": "Denver, CO, USA",      "make": "Apple",  "model": "iPhone 15",          "software": "17.0"},
    {"location": "Atlanta, GA, USA",     "make": "Google", "model": "Pixel 8",            "software": "14.0"},
]

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

    # Random US metadata
    if config.get("random_us_metadata", {}).get("enabled"):
        meta = random.choice(US_METADATA_PRESETS)
        cmd.extend([
            "-metadata", f"location={meta['location']}",
            "-metadata", f"make={meta['make']}",
            "-metadata", f"model={meta['model']}",
            "-metadata", f"software={meta['software']}",
            "-metadata", f"comment=Shot on {meta['model']}",
            "-map_metadata", "-1",  # strip original
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
