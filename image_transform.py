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
    "Hyères", "Salon-de-Provence", "Saint-Brieuc", "Châteauroux",
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
    """Generate a random preset on the fly. Variety = 12 models x 95 cities x ~10 iOS."""
    model = random.choice(IPHONE_MODELS)
    city = random.choice(FRENCH_CITIES)
    software = random.choice(_IOS_BY_MODEL.get(model, ["18.0"]))
    return {
        "make": "Apple",
        "model": model,
        "software": software,
        "location": f"{city}, France",
    }


# Backward compat
US_METADATA_PRESETS = [random_metadata_preset() for _ in range(20)]


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
                preset = random_metadata_preset()
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
