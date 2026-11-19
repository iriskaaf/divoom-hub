"""Cover art -> 16x16 image the Ditoo can display."""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageOps

DISPLAY_SIZE = 16  # Ditoo Pro panel, confirmed by every reference implementation


def fetch_cover(url: str, cache_dir: Path, session: requests.Session) -> Image.Image:
    """Download a cover once; later calls read it from the cache.

    Cached by URL hash, so every track of an album shares one file.
    """
    path = cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if not path.exists():
        r = session.get(url, timeout=10)
        r.raise_for_status()
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(path)
    with Image.open(path) as img:
        img.load()
        return img.copy()


def limit_colors(img: Image.Image, max_colors: int) -> Image.Image:
    if max_colors >= 256 or len(set(img.get_flattened_data())) <= max_colors:
        return img
    return img.quantize(max_colors, method=Image.Quantize.MEDIANCUT,
                        dither=Image.Dither.NONE).convert("RGB")


def diagnostic_pattern(colors: int) -> Image.Image:
    """Smooth rainbow bands, top to bottom, with exactly `colors` distinct colours.
    A scrambled upload turns the bands into noise."""
    import colorsys
    palette: list[tuple[int, int, int]] = []
    used: set[tuple[int, int, int]] = set()
    for k in range(colors):
        r, g, b = colorsys.hsv_to_rgb(0.85 * k / max(1, colors - 1), 0.85, 0.9)
        c = (round(r * 255), round(g * 255), round(b * 255))
        while c in used:  # rounding collision: nudge until unique
            c = (c[0], c[1], (c[2] + 1) % 256)
        used.add(c)
        palette.append(c)
    total = DISPLAY_SIZE * DISPLAY_SIZE
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE))
    img.putdata([palette[i * colors // total] for i in range(total)])
    return img


def to_ditoo(image: Image.Image, contrast: float = 1.1, saturation: float = 1.15,
             brightness: float = 1.0, max_colors: int = 256) -> Image.Image:
    img = ImageOps.exif_transpose(image).convert("RGB")
    # Center-crop to a square instead of stretching, then downscale in one
    # high-quality step. Enhancing after the resize keeps it cheap and makes the
    # sliders act on exactly the pixels the user sees.
    img = ImageOps.fit(img, (DISPLAY_SIZE, DISPLAY_SIZE), Image.Resampling.LANCZOS)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    return limit_colors(img, max_colors)


def test_pattern() -> Image.Image:
    """Asymmetric pattern so orientation and colour order are obvious on the device:
    red/green top half, blue/white bottom half, yellow pixel in the top-left corner."""
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE))
    half = DISPLAY_SIZE // 2
    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            if y < half:
                color = (255, 0, 0) if x < half else (0, 255, 0)
            else:
                color = (0, 0, 255) if x < half else (255, 255, 255)
            img.putpixel((x, y), color)
    img.putpixel((0, 0), (255, 255, 0))
    return img
