"""Accent colour of a cover, and matching it to a keyboard-light effect.

Algorithm (spec section 10), Pillow only, no OpenCV/numpy:
  64x64 -> drop near-black / near-white -> drop low-saturation pixels ->
  median-cut clustering (K=6) -> score clusters by share, saturation and
  brightness -> lift brightness, preserving the winner's hue and saturation.
"""

from __future__ import annotations

import colorsys

from PIL import Image

RGB = tuple[int, int, int]

SAMPLE = 64
CLUSTERS = 6
# A pixel counts as colourful only with real chroma at a usable brightness. Dark
# pixels carry JPEG hue noise and must not decide the colour of a black cover.
MIN_CHROMA = 0.18           # (max - min) of the RGB channels, 0..1
MIN_VALUE = 0.30
# Spotify takes the accent of a small coloured subject too (a red car on a grey
# street is ~10 % of the cover, a violet circle on black similar), so the share
# is low; JPEG noise and a tiny logo (~1 %) still fall below it.
MIN_SATURATED_SHARE = 0.03  # fewer colourful pixels -> black/white/grey cover
WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)


def to_hsv(c: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)


def from_hsv(h: float, s: float, v: float) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return round(r * 255), round(g * 255), round(b * 255)


def hex_color(c: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*c)


def parse_hex(s: str) -> RGB:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def dominant_colors(image: Image.Image, k: int = CLUSTERS) -> list[tuple[RGB, float]]:
    """Colourful clusters of the image as (colour, share of all pixels), best first."""
    img = image.convert("RGB").resize((SAMPLE, SAMPLE), Image.Resampling.BILINEAR)
    pixels = list(img.get_flattened_data())
    useful = []
    for p in pixels:
        hi, lo = max(p) / 255, min(p) / 255
        if hi < MIN_VALUE or hi - lo < MIN_CHROMA:  # dark, grey or near white
            continue
        useful.append(p)
    if len(useful) < MIN_SATURATED_SHARE * len(pixels):
        return []

    strip = Image.new("RGB", (len(useful), 1))
    strip.putdata(useful)
    q = strip.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    clusters = []
    for count, idx in q.getcolors() or []:
        color = (pal[idx * 3], pal[idx * 3 + 1], pal[idx * 3 + 2])
        clusters.append((color, count / len(pixels)))

    def score(item: tuple[RGB, float]) -> float:
        color, share = item
        _, s, v = to_hsv(color)
        return share * (0.3 + s) * (0.3 + v)

    return sorted(clusters, key=score, reverse=True)


def accent_color(image: Image.Image) -> RGB:
    clusters = dominant_colors(image)
    if not clusters:
        return neutral_color(image)
    h, s, v = to_hsv(clusters[0][0])
    # Do not raise saturation: that made muted pinks, purples and oranges more
    # vivid than the actual cover. Brightness is independent of the colour mix.
    return from_hsv(h, s, max(v, 0.80))


def neutral_color(image: Image.Image) -> RGB:
    """Black/white/grey cover: black when most of it is dark, otherwise white."""
    grey = image.convert("L").resize((SAMPLE, SAMPLE), Image.Resampling.BILINEAR)
    pixels = list(grey.get_flattened_data())
    dark = sum(1 for v in pixels if v < 128)
    return BLACK if dark > len(pixels) / 2 else WHITE


def color_distance(a: RGB, b: RGB) -> float:
    """Distance that cares about hue for colourful colours and about saturation
    otherwise (so grey/white accents pick a white effect, not a random hue)."""
    h1, s1, _ = to_hsv(a)
    h2, s2, _ = to_hsv(b)
    hue = abs(h1 - h2)
    hue = min(hue, 1 - hue) * 2  # 0..1 around the colour wheel
    return (min(s1, s2) * hue) ** 2 + 0.5 * (s1 - s2) ** 2


def nearest_effect(color: RGB, effects: dict[int, RGB]) -> int | None:
    if not effects:
        return None
    return min(effects, key=lambda n: color_distance(color, effects[n]))
