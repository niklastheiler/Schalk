"""
Size of the user interface (text, fields, spacing and icons together): 100 % to 200 %.

Qt scales the whole interface by QT_SCALE_FACTOR, so every layout keeps its proportions; enlarging only the
font would cut off text in fields with a fixed width. The factor must be set before the QApplication exists,
so the choice is kept in a small file in the data folder (not in the encrypted database, which is opened later)
and takes effect at the next start.
"""
import json
import logging
import os
from src.utils import paths

logger = logging.getLogger(__name__)

SCALES = [100, 125, 150, 175, 200]
DEFAULT = 100


def _file() -> str:
    return os.path.join(paths.DATA_DIR, "darstellung.json")


def load() -> int:
    try:
        with open(_file(), encoding="utf-8") as f:
            scale = int(json.load(f).get("scale", DEFAULT))
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT
    return scale if scale in SCALES else DEFAULT


def save(scale: int):
    if scale not in SCALES:
        raise ValueError(f"Unbekannte Größe: {scale} %")
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    temp = _file() + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"scale": scale}, f)
    os.replace(temp, _file())


def apply_before_start():
    """Sets the scale factor for Qt; call before the QApplication is created. A factor set from outside wins."""
    scale = load()
    if scale != DEFAULT and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = str(scale / 100)
        logger.info("Darstellung: %s %%", scale)
