"""Image transformation module (Pillow-based).
Applies randomized transformations to images (profile pics, posts, stories).
"""
import io
import json
import random
import shutil
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "image_transform_config.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "rotation_degrees":   {"enabled": True, "min": 0.3,  "max": 1.0},
    "saturation":         {"enabled": True, "min": 0.95, "max": 1.05},
    "brightness":         {"enabled": True, "min": 0.97, "max": 1.03},
    "contrast":           {"enabled": True, "min": 0.98, "max": 1.05},
    "sharpness":          {"enabled": True, "min": 0.95, "max": 1.10},
    "random_dimensions":  {"enabled": True},
    "jpeg_quality":       {"enabled": True, "min": 85,   "max": 95},
    "random_us_metadata": {"enabled": True},
    "noise":              {"enabled": False, "min": 0,   "max": 0},
}

# Instagram standard dimensions (portrait + square)
RANDOM_PORTRAIT_DIMS = [
    (1080, 1080),  # square (1:1)
    (1080, 1350),  # 4:5 post
    (1080, 1920),  # 9:16 story / reel cover
]

RANDOM_STORY_DIMS = [
    (1080, 1920),  # Instagram story format obligatoire
]

RANDOM_POST_DIMS = [
    (1080, 1350),  # Instagram feed post 4:5
]


def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
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


def _rand(min_v, max_v):
    if min_v == max_v:
        return min_v
    return random.uniform(float(min_v), float(max_v))


def is_pillow_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def transform_image(input_path, output_path, config=None, target="post"):
    """Apply transformations to an image. target = 'post', 'story', or 'profile'.
    Returns True on success.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not is_pillow_available():
        shutil.copy2(input_path, output_path)
        return True

    if config is None:
        config = load_config()

    if not config.get("enabled", True):
        shutil.copy2(input_path, output_path)
        return True

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        shutil.copy2(input_path, output_path)
        return True

    try:
        img = Image.open(input_path)
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Rotation
        if config.get("rotation_degrees", {}).get("enabled"):
            deg = _rand(config["rotation_degrees"]["min"], config["rotation_degrees"]["max"])
            if random.random() < 0.5:
                deg = -deg
            img = img.rotate(deg, fillcolor=(255, 255, 255), expand=False, resample=Image.BICUBIC)

        # Saturation
        if config.get("saturation", {}).get("enabled"):
            f = _rand(config["saturation"]["min"], config["saturation"]["max"])
            img = ImageEnhance.Color(img).enhance(f)

        # Brightness
        if config.get("brightness", {}).get("enabled"):
            f = _rand(config["brightness"]["min"], config["brightness"]["max"])
            img = ImageEnhance.Brightness(img).enhance(f)

        # Contrast
        if config.get("contrast", {}).get("enabled"):
            f = _rand(config["contrast"]["min"], config["contrast"]["max"])
            img = ImageEnhance.Contrast(img).enhance(f)

        # Sharpness
        if config.get("sharpness", {}).get("enabled"):
            f = _rand(config["sharpness"]["min"], config["sharpness"]["max"])
            img = ImageEnhance.Sharpness(img).enhance(f)

        # Resize (only for targets that NEED a specific size)
        if config.get("random_dimensions", {}).get("enabled"):
            if target == "storycta":
                # Force 1080x1920 for story CTAs
                img = img.resize((1080, 1920), Image.LANCZOS)
            elif target == "profile":
                # Square for profile pic
                size = random.choice([512, 720, 1080])
                img = img.resize((size, size), Image.LANCZOS)
            # post & story: pas de resize, on garde la taille originale

        # JPEG quality
        quality = 90
        if config.get("jpeg_quality", {}).get("enabled"):
            quality = int(_rand(config["jpeg_quality"]["min"], config["jpeg_quality"]["max"]))

        # Save
        # Determine format from output extension
        ext = output_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            save_kwargs = {"format": "JPEG", "quality": quality, "optimize": True}
        elif ext == ".png":
            save_kwargs = {"format": "PNG", "optimize": True}
        elif ext == ".webp":
            save_kwargs = {"format": "WEBP", "quality": quality}
        else:
            save_kwargs = {"format": "JPEG", "quality": quality, "optimize": True}

        img.save(output_path, **save_kwargs)
        return True
    except Exception as e:
        try:
            err_log = DATA_DIR / "image_transform_errors.log"
            err_log.parent.mkdir(parents=True, exist_ok=True)
            with err_log.open("a", encoding="utf-8") as f:
                f.write(f"{input_path} -> {output_path}: {type(e).__name__}: {e}\n")
        except Exception:
            pass
        return False


def config_summary_text(config=None):
    if config is None:
        config = load_config()
    lines = [f"**Transformation images activée :** {'✅' if config.get('enabled', True) else '❌'}", "", "**Paramètres :**"]
    for key, value in config.items():
        if key == "enabled":
            continue
        if isinstance(value, dict):
            en = value.get("enabled", True)
            mark = "✅" if en else "❌"
            if "min" in value:
                lines.append(f"{mark} `{key}` : {value['min']} → {value['max']}")
            else:
                lines.append(f"{mark} `{key}`")
    return "\n".join(lines)
