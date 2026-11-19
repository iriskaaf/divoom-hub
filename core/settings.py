"""Application settings, stored as JSON in %LOCALAPPDATA%\\DivoomHub\\config.json.

Secrets (Spotify tokens) are NOT stored here; see core/spotify.py (Windows
Credential Manager via keyring).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from core.profile import PROFILE_NAME, TEST_MODE, WINUI_MODE

from timesgate.digits import DEFAULT_THEMES, FIGMA_THEMES, KEEP_STYLES, THEME_ADDITIONS, THEMES_VERSION

log = logging.getLogger(__name__)

_BASE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home()))
LEGACY_APP_DIR = _BASE_DIR / "DitooSpotify"  # the app was called "Ditoo Spotify" before 1.0


def _app_dir() -> Path:
    """The old folder is moved to the new name once. If an old copy of the app is
    still running and keeps files open, the old folder simply stays in use."""
    new = _BASE_DIR / PROFILE_NAME
    if TEST_MODE or WINUI_MODE:
        return new
    if new.exists() or not LEGACY_APP_DIR.exists():
        return new
    try:
        LEGACY_APP_DIR.rename(new)
        return new
    except OSError:
        return LEGACY_APP_DIR


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"
_SAVE_LOCK = threading.Lock()


def _relocate(value):
    """Picture paths saved under the old data folder point into the new one."""
    old = str(LEGACY_APP_DIR)
    if APP_DIR == LEGACY_APP_DIR:
        return value
    if isinstance(value, str) and value.lower().startswith(old.lower() + os.sep):
        return str(APP_DIR) + value[len(old):]
    if isinstance(value, list):
        return [_relocate(v) for v in value]
    if isinstance(value, dict):
        return {k: _relocate(v) for k, v in value.items()}
    return value


@dataclass
class Settings:
    onboarding_completed: bool = False
    ditoo_enabled: bool = True
    timesgate_enabled: bool = True
    developer_mode: bool = False
    # Ditoo
    ditoo_address: str = ""
    ditoo_port: int = 0  # 0 = probe automatically
    brightness: int = 60
    auto_reconnect: bool = True
    # Spotify
    spotify_client_id: str = ""
    track_source: str = "media"      # media (Windows media session) | api (Spotify Web API)
    media_only_spotify: bool = True  # media session: ignore browsers and other players
    show_artwork: bool = True
    # What the Ditoo shows after the music stops (key of DISPLAY_MODES)
    idle_mode: str = "clock"
    idle_delay_s: int = 5
    # Artwork processing
    contrast: float = 1.1
    saturation: float = 1.15
    art_brightness: float = 1.0
    max_colors: int = 256

    ui_theme: str = "auto"  # auto | dark | light
    # Times Gate (Wi-Fi)
    tg_ip: str = ""
    tg_token: str = ""
    tg_hardware: int = 400
    tg_mac: str = ""
    tg_mode: str = "clock"          # clock | gifs_clock | device | off
    tg_device_face: int = 581       # built-in whole-device face ("Clock face")
    tg_device_face_on_exit: bool = True
    tg_24h: bool = True
    tg_blink_colon: bool = True
    tg_face_follow_cover: bool = False
    tg_center_cover: bool = True    # Spotify cover instead of ":" while music plays
    tg_themes: list[dict] = field(default_factory=lambda: [dict(t) for t in DEFAULT_THEMES])
    tg_theme: int = 1
    tg_themes_version: int = THEMES_VERSION
    tg_custom_chars: dict[str, str] = field(default_factory=dict)  # "0".."9", ":" -> file
    tg_side_media: list[str] = field(default_factory=lambda: ["", "", "", ""])
    tg_manage_brightness: bool = True
    tg_brightness: int = 80
    tg_manage_light: bool = True
    tg_light_on: bool = True
    tg_light_brightness: int = 80
    tg_light_color: str = "#FF2BD6"
    tg_light_follow_cover: bool = False  # cover accent while Spotify plays, own colour otherwise
    tg_light_bw_mode: str = "white"        # black/white cover: own colour | off | white
    tg_light_zone: int = 0
    tg_light_effect: int = 4
    tg_light_cycle: bool = False
    tg_key_light: bool = True

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as e:
            log.warning("Ignoring unreadable config %s: %s", path, e)
            return cls()
        settings = cls()
        if not isinstance(data, dict):
            log.warning("Ignoring config with a non-object root")
            return settings
        for f in fields(cls):
            default = getattr(settings, f.name)
            value = data.get(f.name, default)
            if type(value) is type(default) or (type(default) is float and type(value) is int):
                setattr(settings, f.name, _relocate(value))
        settings.tg_side_media = ([p if isinstance(p, str) else "" for p in
                                   settings.tg_side_media[:4]] + [""] * 4)[:4]
        settings.tg_themes = [t for t in settings.tg_themes
                              if isinstance(t, dict) and isinstance(t.get("name"), str)
                              and isinstance(t.get("style"), str)
                              and isinstance(t.get("chars", {}), dict)]
        for theme in settings.tg_themes:
            if "chars" in theme:
                theme["chars"] = {k: p for k, p in theme["chars"].items() if isinstance(p, str)}
        if not settings.tg_themes:
            settings.tg_themes = [dict(t) for t in DEFAULT_THEMES]
            settings.tg_theme = 0
        if "tg_themes" in data:
            version = data.get("tg_themes_version", 1)
            settings._migrate_themes(version if type(version) is int and version >= 1 else 1)
        if "onboarding_completed" not in data:
            settings.onboarding_completed = bool(settings.ditoo_address or (settings.tg_ip and settings.tg_token))
        settings.tg_manage_light = settings.tg_manage_brightness = True
        settings.tg_light_bw_mode = "white"
        settings.tg_theme %= len(settings.tg_themes)
        if "tg_face_follow_cover" not in data:
            settings.tg_face_follow_cover = bool(settings.tg_themes[settings.tg_theme].get("follow_light"))
        return settings

    def _migrate_themes(self, version: int) -> None:
        # Move legacy digit art before pruning old empty/custom templates.
        if self.tg_custom_chars:
            for t in self.tg_themes:
                if t.get("style") == "custom" and not t.get("chars"):
                    t["chars"] = {k: p for k, p in self.tg_custom_chars.items() if isinstance(p, str)}
                    break
            self.tg_custom_chars = {}
        for theme in self.tg_themes:
            if theme.get("style") == "soft":
                if theme.get("name") == "Soft Forms":
                    theme["name"] = "Material Expressive"
                theme["bg"] = "#000000"
        # New built-in themes are added once; the user's own list and order stay.
        for v in range(version + 1, THEMES_VERSION + 1):
            names = {t.get("name") for t in self.tg_themes}
            self.tg_themes += [dict(t) for t in THEME_ADDITIONS.get(v, []) if t["name"] not in names]
        if version < 6:
            # v6: only the five Figma faces stay built in; the user's picture packs stay too.
            current = self.tg_themes[self.tg_theme % len(self.tg_themes)]["name"] if self.tg_themes else ""
            kept = [t for t in self.tg_themes
                    if t.get("style") in KEEP_STYLES or (t.get("style") == "custom" and t.get("chars"))]
            names = {t.get("name") for t in kept}
            kept += [dict(t) for t in FIGMA_THEMES if t["name"] not in names]
            self.tg_themes = kept
            self.tg_theme = next((i for i, t in enumerate(kept) if t["name"] == current), 0)
        self.tg_themes_version = THEMES_VERSION

    def save(self, path: Path = CONFIG_PATH) -> None:
        # The device threads and the UI can save at the same time.
        with _SAVE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)


def settings_for_gui_launch(current: Settings) -> Settings:
    """Called only after acquiring the instance lock, never for diagnostics."""
    if not TEST_MODE:
        return current
    fresh = Settings()
    fresh.save()
    return fresh
