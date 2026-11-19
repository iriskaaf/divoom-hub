"""Installed fonts (name -> file), read from the Windows registry like the Fonts settings page."""

from __future__ import annotations

import os
import re
import winreg
from functools import lru_cache

KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
SUFFIXES = (".ttf", ".otf", ".ttc")


@lru_cache(maxsize=1)
def system_fonts() -> dict[str, str]:
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    found: dict[str, str] = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):  # machine + per-user fonts
        try:
            key = winreg.OpenKey(hive, KEY)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not isinstance(value, str) or not value.lower().endswith(SUFFIXES):
                    continue
                path = value if os.path.isabs(value) else os.path.join(fonts_dir, value)
                if os.path.exists(path):
                    label = re.sub(r"\s*\((TrueType|OpenType)\)$", "", name).strip()
                    found.setdefault(label, path)
    return dict(sorted(found.items(), key=lambda kv: kv[0].lower()))
