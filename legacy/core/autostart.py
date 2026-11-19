"""Start with Windows via HKCU\\...\\Run (per user, no admin rights needed)."""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

from core.profile import TEST_MODE

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "DivoomHub"
LEGACY_VALUE = "DitooSpotify"  # the app's name before 1.0


def command() -> str:
    """Command line that starts this program hidden in the tray."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    root = Path(__file__).resolve().parent.parent
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    return f'"{pythonw}" "{root / "app.py"}" --minimized'


def _read(value: str = VALUE) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, value)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    if TEST_MODE:
        return False
    return _read() is not None or _read(LEGACY_VALUE) is not None


def set_enabled(enabled: bool) -> None:
    if TEST_MODE:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
            log.info("Autostart enabled: %s", command())
        for name in (LEGACY_VALUE,) if enabled else (VALUE, LEGACY_VALUE):
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        if not enabled:
            log.info("Autostart disabled")


def refresh() -> None:
    """If autostart is on but points elsewhere (the folder was moved, or it is the
    entry of the old "Ditoo Spotify" build), fix it. Only the built .exe does this,
    so running from source never hijacks it."""
    if TEST_MODE or not getattr(sys, "frozen", False):
        return
    if _read(LEGACY_VALUE) is not None or _read() not in (None, command()):
        set_enabled(True)
