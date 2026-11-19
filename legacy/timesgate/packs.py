"""Clock packs: a theme plus (for custom packs) its own digit pictures.

Each custom pack keeps private copies of its pictures in
%LOCALAPPDATA%\\DivoomHub\\timesgate\\packs\\<id>\\, so moving or deleting
the originals does not break it. A pack exports to / imports from a .zip:

    manifest.json   {"format": 1, "name", "style", "color", "bg",
                     "chars": {"0": "char_0.png", ..., ":": "char_colon.gif"}}
    char_*.*        the pictures
"""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path

from core.settings import APP_DIR

from .digits import CHARS, STYLES, style_roles, parse_hex

PACKS_DIR = APP_DIR / "timesgate" / "packs"
PACK_FORMAT = 1
MAX_FILE = 20 * 1024 * 1024
ALLOWED = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


class PackError(Exception):
    pass


def char_slug(ch: str) -> str:
    return "colon" if ch == ":" else ch


def pack_dir(theme: dict) -> Path:
    if not theme.get("id"):
        theme["id"] = uuid.uuid4().hex[:12]
    return PACKS_DIR / theme["id"]


def set_char(theme: dict, ch: str, source: str | None) -> None:
    """Copy a picture into the pack (None removes the character)."""
    folder = pack_dir(theme)
    chars = dict(theme.get("chars") or {})
    for old in folder.glob(f"char_{char_slug(ch)}.*"):
        old.unlink(missing_ok=True)
    if source:
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"char_{char_slug(ch)}{Path(source).suffix.lower()}"
        shutil.copyfile(source, dst)
        chars[ch] = str(dst)
    else:
        chars.pop(ch, None)
    theme["chars"] = chars


def new_pack(name: str, base: dict | None = None) -> dict:
    theme = {"name": name, "style": "custom", "color": "#FFFFFF", "bg": "#000000", "chars": {}}
    if base:
        theme.update({k: base[k] for k in ("color", "bg") if k in base})
        for ch, path in (base.get("chars") or {}).items():
            if Path(path).exists():
                set_char(theme, ch, path)
    return theme


def delete_pack_files(theme: dict) -> None:
    if theme.get("id"):
        shutil.rmtree(PACKS_DIR / theme["id"], ignore_errors=True)


def export_pack(theme: dict, zip_path: str) -> None:
    manifest = {"format": PACK_FORMAT, "name": theme.get("name", "Пак"),
                "style": theme.get("style", "custom"), "color": theme.get("color", "#FFFFFF"),
                "bg": theme.get("bg", "#000000"), "chars": {}}
    manifest["palette"] = {key: theme.get(key, default) for key, _, default in style_roles(theme.get("style", "custom"))}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for ch, path in (theme.get("chars") or {}).items():
            p = Path(path)
            if p.exists():
                arc = f"char_{char_slug(ch)}{p.suffix.lower()}"
                z.write(p, arc)
                manifest["chars"][ch] = arc
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))


def import_pack(zip_path: str) -> dict:
    try:
        with zipfile.ZipFile(zip_path) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != PACK_FORMAT:
                raise PackError("Неизвестный формат пака")
            style = manifest.get("style", "custom")
            theme = {"name": str(manifest.get("name") or "Пак")[:40],
                     "style": style if style in STYLES else "custom",
                     "color": str(manifest.get("color", "#FFFFFF"))[:7],
                     "bg": str(manifest.get("bg", "#000000"))[:7], "chars": {}}
            palette = manifest.get("palette", {})
            if isinstance(palette, dict):
                for key, _, default in style_roles(theme["style"]):
                    color = palette.get(key)
                    if isinstance(color, str):
                        try:
                            parse_hex(color)
                            theme[key] = color
                        except (ValueError, TypeError):
                            theme[key] = default
            folder = pack_dir(theme)
            folder.mkdir(parents=True, exist_ok=True)
            for ch, arc in (manifest.get("chars") or {}).items():
                info = z.getinfo(arc)  # KeyError if missing
                suffix = Path(arc).suffix.lower()
                if ch not in CHARS or suffix not in ALLOWED or info.file_size > MAX_FILE:
                    continue
                dst = folder / f"char_{char_slug(ch)}{suffix}"  # our own name: no path tricks
                dst.write_bytes(z.read(info))
                theme["chars"][ch] = str(dst)
            return theme
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise PackError(f"Не удалось прочитать пак: {e}") from e
