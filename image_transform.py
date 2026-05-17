"""Image transformation module (Pillow-based).
Par defaut: change UNIQUEMENT les metadata EXIF (Make/Model/DateTime).
La taille et le rendu visuel restent intacts.
"""
import io
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "image_transform_config.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "metadata_only": True,  # si True: ignore toutes les transfos visuelles, change que les metadata
    "random_us_metadata": {"enabled": True},

    # Options visuelles (desactivees par defaut, activables si metadata_only=False)
    "rotation_degrees":   {"enabled": False, "min": 0.3,  "max": 1.0},
    "saturation":         {"enabled": False, "min": 0.95, "max": 1.05},
    "brightness":         {"enabled": False, "min": 0.97, "max": 1.03},
    "contrast":           {"enabled": False, "min": 0.98, "max": 1.05},
    "sharpness":          {"enabled": False, "min": 0.95, "max": 1.10},
    "random_dimensions":  {"enabled": False},
    "jpeg_quality":       {"enabled": False, "min": 85,   "max": 95},
    "noise":              {"enabled": False, "min": 0,    "max": 0},
}

US_METADATA_PRESETS = [
    {"make": "Apple",   "model": "iPhone 14 Pro",      "software": "16.0",  "location": "New York, NY, USA"},
    {"make": "Apple",   "model": "iPhone 13",          "software": "15.4",  "location": "Los Angeles, CA, USA"},
    {"make": "Samsung", "model": "Galaxy S23",         "software": "13.0",  "location": "Miami, FL, USA"},
    {"make": "Apple",   "model": "iPhone 14",          "software": "16.2",  "location": "Chicago, IL, USA"},
    {"make": "Google",  "model": "Pixel 7",            "software": "13.0",  "location": "Austin, TX, USA"},
    {"make": "Apple",   "model": "iPhone 12 Pro Max",  "software": "15.7",  "location": "Seattle, WA, USA"},
    {"make": "Samsung", "model": "Galaxy S22",         "software": "12.0",  "location": "San Francisco, CA, USA"},
    {"make": "Apple",   "model": "iPhone 14 Plus",     "software": "16.1",  "location": "Boston, MA, USA"},
    {"make": "Apple",   "model": "iPhone 13 Pro",      "software": "15.6",  "location": "Houston, TX, USA"},
    {"make": "Samsung", "model": "Galaxy Note 20",     "software": "11.0",  "location": "Phoenix, AZ, USA"},
    {"make": "Apple",   "model": "iPhone 15",          "software": "17.0",  "location": "Denver, CO, USA"},
    {"make": "Google",  "model": "Pixel 8",            "software": "14.0",  "location": "Atlanta, GA, USA"},
]


def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(cfg)
        # S'assurer que metadata_only existe
        if "metadata_only" not in cfg:
            merged["metadata_only"] = True
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


def _build_random_exif(preset):
    """Build an Image.Exif object with random US metadata."""
    from PIL import Image
    exif = Image.Exif()
    random_date = datetime.now() - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23))
    date_str = random_date.strftime("%Y:%m:%d %H:%M:%S")
    # Standard EXIF tags
    exif[271] = preset["make"]            # Make
    exif[272] = preset["model"]           # Model
    exif[305] = preset["software"]        # Software
    exif[306] = date_str                  # DateTime
    exif[36867] = date_str                # DateTimeOriginal
    exif[36868] = date_str                # DateTimeDigitized
    exif[270] = f"Shot on {preset['model']}"  # ImageDescription
    return exif


def transform_image(input_path, output_path, config=None, target="post"):
    """Apply transformations to an image.
    Si config['metadata_only'] = True (defaut) : change UNIQUEMENT les metadata.
    Sinon : applique aussi les transfos visuelles selon config.
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
        from PIL import Image, ImageEnhance
    except ImportError:
        shutil.copy2(input_path, output_path)
        return True

    metadata_only = config.get("metadata_only", True)

    try:
        img = Image.open(input_path)
        original_mode = img.mode
        if img.mode != "RGB":
            img = img.convert("RGB")

        if not metadata_only:
            # Rotation
            if config.get("rotation_degrees", {}).get("enabled"):
                deg = _rand(config["rotation_degrees"]["min"], config["rotation_degrees"]["max"])
                if random.random() < 0.5:
                    deg = -deg
                img = img.rotate(deg, fillcolor=(255, 255, 255), expand=False, resample=Image.BICUBIC)
            # Saturation / Brightness / Contrast / Sharpness
            if config.get("saturation", {}).get("enabled"):
                img = ImageEnhance.Color(img).enhance(_rand(config["saturation"]["min"], config["saturation"]["max"]))
            if config.get("brightness", {}).get("enabled"):
                img = ImageEnhance.Brightness(img).enhance(_rand(config["brightness"]["min"], config["brightness"]["max"]))
            if config.get("contrast", {}).get("enabled"):
                img = ImageEnhance.Contrast(img).enhance(_rand(config["contrast"]["min"], config["contrast"]["max"]))
            if config.get("sharpness", {}).get("enabled"):
                img = ImageEnhance.Sharpness(img).enhance(_rand(config["sharpness"]["min"], config["sharpness"]["max"]))
            # Resize (sauf metadata_only)
            if config.get("random_dimensions", {}).get("enabled"):
                if target == "storycta":
                    img = img.resize((1080, 1920), Image.LANCZOS)
                elif target == "profile":
                    size = random.choice([512, 720, 1080])
                    img = img.resize((size, size), Image.LANCZOS)

        # Quality
        quality = 92
        if not metadata_only and config.get("jpeg_quality", {}).get("enabled"):
            quality = int(_rand(config["jpeg_quality"]["min"], config["jpeg_quality"]["max"]))

        # EXIF metadata
        exif_bytes = None
        if config.get("random_us_metadata", {}).get("enabled"):
            try:
                preset = random.choice(US_METADATA_PRESETS)
                exif = _build_random_exif(preset)
                exif_bytes = exif.tobytes()
            except Exception:
                exif_bytes = None

        # Determine format
        ext = output_path.suffix.lower()
        save_kwargs = {}
        if ext in (".jpg", ".jpeg") or ext == "":
            save_kwargs["format"] = "JPEG"
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
        elif ext == ".png":
            save_kwargs["format"] = "PNG"
            save_kwargs["optimize"] = True
        elif ext == ".webp":
            save_kwargs["format"] = "WEBP"
            save_kwargs["quality"] = quality
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
        else:
            save_kwargs["format"] = "JPEG"
            save_kwargs["quality"] = quality

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
        # Fallback: copie directe
        try:
            shutil.copy2(input_path, output_path)
            return True
        except Exception:
            return False


def config_summary_text(config=None):
    if config is None:
        config = load_config()
    lines = []
    lines.append(f"**Transformation images activée :** {'✅' if config.get('enabled', True) else '❌'}")
    lines.append(f"**Mode metadata uniquement :** {'✅ OUI' if config.get('metadata_only', True) else '❌ NON (transfos visuelles actives)'}")
    lines.append("")
    lines.append("**Options :**")
    for key, value in config.items():
        if key in ("enabled", "metadata_only"):
            continue
        if isinstance(value, dict):
            en = value.get("enabled", True)
            mark = "✅" if en else "❌"
            if "min" in value:
                lines.append(f"{mark} `{key}` : {value['min']} → {value['max']}")
            else:
                lines.append(f"{mark} `{key}`")
    return "\n".join(lines)
