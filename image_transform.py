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


CITY_COORDS = {
    "Paris": (48.8566, 2.3522, 35),
    "Marseille": (43.2965, 5.3698, 12),
    "Lyon": (45.7640, 4.8357, 173),
    "Toulouse": (43.6047, 1.4442, 146),
    "Nice": (43.7102, 7.2620, 9),
    "Nantes": (47.2184, -1.5536, 20),
    "Strasbourg": (48.5734, 7.7521, 142),
    "Montpellier": (43.6108, 3.8767, 27),
    "Bordeaux": (44.8378, -0.5792, 8),
    "Lille": (50.6292, 3.0573, 22),
    "Rennes": (48.1173, -1.6778, 30),
    "Reims": (49.2583, 4.0317, 82),
    "Le Havre": (49.4944, 0.1079, 5),
    "Toulon": (43.1242, 5.9280, 11),
    "Saint-Étienne": (45.4397, 4.3872, 510),
    "Grenoble": (45.1885, 5.7245, 215),
    "Dijon": (47.3220, 5.0415, 245),
    "Angers": (47.4784, -0.5632, 30),
    "Nîmes": (43.8367, 4.3601, 39),
    "Villeurbanne": (45.7702, 4.8895, 168),
    "Le Mans": (48.0061, 0.1996, 46),
    "Aix-en-Provence": (43.5297, 5.4474, 173),
    "Clermont-Ferrand": (45.7772, 3.0870, 396),
    "Brest": (48.3905, -4.4860, 35),
    "Tours": (47.3941, 0.6848, 53),
    "Limoges": (45.8336, 1.2611, 209),
    "Amiens": (49.8941, 2.2958, 30),
    "Perpignan": (42.6886, 2.8949, 32),
    "Metz": (49.1193, 6.1757, 173),
    "Besançon": (47.2378, 6.0241, 250),
    "Annecy": (45.8992, 6.1294, 448),
    "Cannes": (43.5528, 7.0174, 5),
    "Antibes": (43.5808, 7.1239, 8),
    "Biarritz": (43.4832, -1.5586, 19),
    "Bayonne": (43.4929, -1.4748, 12),
    "Saint-Tropez": (43.2727, 6.6406, 5),
    "Deauville": (49.3589, 0.0764, 5),
    "Avignon": (43.9493, 4.8055, 23),
    "La Rochelle": (46.1591, -1.1520, 4),
    "Chambéry": (45.5646, 5.9178, 270),
    "Pau": (43.2951, -0.3708, 207),
    "Quimper": (47.9960, -4.0978, 50),
    "Saint-Malo": (48.6493, -2.0258, 5),
    "Honfleur": (49.4197, 0.2330, 5),
    "Lorient": (47.7482, -3.3702, 12),
}


def _city_coords(city):
    if city in CITY_COORDS:
        return CITY_COORDS[city]
    # Random French coords for cities not in the dict
    return (
        round(random.uniform(43.0, 50.5), 4),
        round(random.uniform(-4.0, 7.5), 4),
        round(random.uniform(5, 400)),
    )


def random_metadata_preset():
    """Generate a random preset with realistic camera+GPS data."""
    model = random.choice(IPHONE_MODELS)
    city = random.choice(FRENCH_CITIES)
    software = random.choice(_IOS_BY_MODEL.get(model, ["18.0"]))
    lat, lon, alt = _city_coords(city)
    # Add slight random offset to GPS (within ~500m)
    lat += random.uniform(-0.005, 0.005)
    lon += random.uniform(-0.005, 0.005)
    alt += random.randint(-5, 10)
    # Camera specs
    is_pro = "Pro" in model
    iso = random.choice([32, 50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000])
    exposure_num, exposure_denom = random.choice([
        (1, 30), (1, 50), (1, 60), (1, 100), (1, 120),
        (1, 200), (1, 250), (1, 500), (1, 1000)
    ])
    f_number = (178, 100) if is_pro else (160, 100)  # f/1.78 or f/1.6
    focal_length = (57, 10) if is_pro else (51, 10)   # 5.7mm or 5.1mm
    return {
        "make": "Apple",
        "model": model,
        "software": software,
        "location_str": f"{city}, France",
        "city": city,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "iso": iso,
        "exposure_time": (exposure_num, exposure_denom),
        "f_number": f_number,
        "focal_length": focal_length,
        "lens_model": f"{model} back camera 6.86mm f/{f_number[0]/f_number[1]:.2f}" if is_pro else f"{model} back camera 5.7mm f/{f_number[0]/f_number[1]:.2f}",
    }


def _to_gps_rational(decimal_value):
    """Convert decimal degrees to (deg, min, sec) rational tuple."""
    abs_value = abs(decimal_value)
    degrees = int(abs_value)
    remainder = (abs_value - degrees) * 60
    minutes = int(remainder)
    seconds = (remainder - minutes) * 60
    # Use 100x precision for seconds
    return ((degrees, 1), (minutes, 1), (int(seconds * 100), 100))


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


def _build_random_exif_bytes(preset):
    """Build EXIF bytes with comprehensive metadata using piexif."""
    try:
        import piexif
    except ImportError:
        return None
    random_date = datetime.now() - timedelta(
        days=random.randint(1, 60),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    date_str = random_date.strftime("%Y:%m:%d %H:%M:%S")
    offset_str = "+01:00"  # CET
    lat = preset["lat"]
    lon = preset["lon"]
    alt = preset["alt"]
    lat_ref = "N" if lat >= 0 else "S"
    lon_ref = "E" if lon >= 0 else "W"
    alt_ref = 0 if alt >= 0 else 1
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: preset["make"].encode("utf-8"),
            piexif.ImageIFD.Model: preset["model"].encode("utf-8"),
            piexif.ImageIFD.Software: preset["software"].encode("utf-8"),
            piexif.ImageIFD.DateTime: date_str.encode("utf-8"),
            piexif.ImageIFD.ImageDescription: f"Shot on {preset['model']}".encode("utf-8"),
            piexif.ImageIFD.Orientation: 1,
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
            piexif.ImageIFD.ResolutionUnit: 2,
            piexif.ImageIFD.YCbCrPositioning: 1,
            piexif.ImageIFD.HostComputer: f"{preset['model']}".encode("utf-8"),
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: date_str.encode("utf-8"),
            piexif.ExifIFD.DateTimeDigitized: date_str.encode("utf-8"),
            piexif.ExifIFD.OffsetTime: offset_str.encode("utf-8"),
            piexif.ExifIFD.OffsetTimeOriginal: offset_str.encode("utf-8"),
            piexif.ExifIFD.OffsetTimeDigitized: offset_str.encode("utf-8"),
            piexif.ExifIFD.ExposureTime: preset["exposure_time"],
            piexif.ExifIFD.FNumber: preset["f_number"],
            piexif.ExifIFD.ExposureProgram: 2,  # Normal program
            piexif.ExifIFD.ISOSpeedRatings: preset["iso"],
            piexif.ExifIFD.SensitivityType: 2,
            piexif.ExifIFD.ExifVersion: b"0232",
            piexif.ExifIFD.ComponentsConfiguration: b"\x01\x02\x03\x00",
            piexif.ExifIFD.ShutterSpeedValue: preset["exposure_time"],
            piexif.ExifIFD.ApertureValue: preset["f_number"],
            piexif.ExifIFD.BrightnessValue: (random.randint(0, 50), 10),
            piexif.ExifIFD.ExposureBiasValue: (0, 1),
            piexif.ExifIFD.MeteringMode: 5,  # Pattern
            piexif.ExifIFD.Flash: 16,  # Flash did not fire (compulsory)
            piexif.ExifIFD.FocalLength: preset["focal_length"],
            piexif.ExifIFD.SubjectArea: (random.randint(1000, 3000), random.randint(1500, 4000), 2000, 2000),
            piexif.ExifIFD.SubSecTimeOriginal: str(random.randint(100, 999)).encode("utf-8"),
            piexif.ExifIFD.SubSecTimeDigitized: str(random.randint(100, 999)).encode("utf-8"),
            piexif.ExifIFD.ColorSpace: 1,  # sRGB
            piexif.ExifIFD.SensingMethod: 2,  # One-chip color area sensor
            piexif.ExifIFD.SceneType: b"\x01",
            piexif.ExifIFD.ExposureMode: 0,  # Auto
            piexif.ExifIFD.WhiteBalance: 0,  # Auto
            piexif.ExifIFD.FocalLengthIn35mmFilm: 24 if "Pro" in preset["model"] else 26,
            piexif.ExifIFD.SceneCaptureType: 0,  # Standard
            piexif.ExifIFD.LensSpecification: (preset["focal_length"], preset["focal_length"], preset["f_number"], preset["f_number"]),
            piexif.ExifIFD.LensMake: b"Apple",
            piexif.ExifIFD.LensModel: preset["lens_model"].encode("utf-8"),
        },
        "GPS": {
            piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
            piexif.GPSIFD.GPSLatitudeRef: lat_ref.encode("utf-8"),
            piexif.GPSIFD.GPSLatitude: _to_gps_rational(lat),
            piexif.GPSIFD.GPSLongitudeRef: lon_ref.encode("utf-8"),
            piexif.GPSIFD.GPSLongitude: _to_gps_rational(lon),
            piexif.GPSIFD.GPSAltitudeRef: alt_ref,
            piexif.GPSIFD.GPSAltitude: (max(0, int(alt * 100)), 100),
            piexif.GPSIFD.GPSTimeStamp: (
                (random_date.hour, 1),
                (random_date.minute, 1),
                (random_date.second, 1),
            ),
            piexif.GPSIFD.GPSDateStamp: random_date.strftime("%Y:%m:%d").encode("utf-8"),
            piexif.GPSIFD.GPSImgDirectionRef: b"T",  # True north
            piexif.GPSIFD.GPSImgDirection: (random.randint(0, 35900), 100),  # 0-359° with 2 decimals
            piexif.GPSIFD.GPSSpeedRef: b"K",  # km/h
            piexif.GPSIFD.GPSSpeed: (0, 1),
        },
        "1st": {},
        "thumbnail": None,
    }
    try:
        return piexif.dump(exif_dict)
    except Exception:
        return None


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

        # EXIF metadata (comprehensive with piexif)
        exif_bytes = None
        if config.get("random_us_metadata", {}).get("enabled"):
            try:
                preset = random_metadata_preset()
                exif_bytes = _build_random_exif_bytes(preset)
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
