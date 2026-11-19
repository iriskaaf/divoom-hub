"""Local card artwork, shared between setup and settings (including frozen builds)."""
from functools import lru_cache
from pathlib import Path
import sys

from PySide6.QtGui import QIcon


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
TILE_ARTWORK = {
    "ditoo": "imgs/ditoo.png",
    "timesgate": "imgs/times-gate.png",
    "media": "resources/illustrations/media-session.svg",
    "api": "resources/illustrations/spotify.svg",
}


@lru_cache(maxsize=len(TILE_ARTWORK))
def tile_icon(key: str) -> QIcon:
    # Share decoded images between cards; never fetch artwork at application startup.
    return QIcon(str(ROOT / TILE_ARTWORK[key]))
