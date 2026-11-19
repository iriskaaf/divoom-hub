"""Clock digits for the Times Gate screens (128x128 each), drawn with Pillow.

Every style takes a digit colour and a background colour, and can render any
box size, so the same code draws one digit per screen and the compact HH:MM
clock on a single screen.
"""

from __future__ import annotations

import os
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .client import MAX_FRAMES, SIZE

STYLES = {
    "segment": "Сегменты",
    "neon": "Неон",
    "pixel": "Пиксели",
    "flip": "Флип",
    "minimal": "Минимал",
    "nixie": "Никси",
    "synthwave": "Синтвейв",
    "terminal": "Терминал",
    "bauhaus": "Баухаус",
    "blueprint": "Чертёж",
    "binary": "Бинарные",
    "valorant": "Valorant",
    "marathon": "Marathon",
    "island": "Animal Crossing",
    "ghibli": "Гибли",
    "pocket": "Покемон",
    "typo": "Типографика",
    "material": "Material Expressive",
    "widget": "Виджет (один экран)",
    "custom": "Свои картинки",
}
CHARS = "0123456789:"
BLINK_MS = 500
SS = 3  # supersampling for smooth edges

DEFAULT_THEMES = [
    {"name": "Неон", "style": "neon", "color": "#FF2BD6", "bg": "#000000"},
    {"name": "Табло", "style": "segment", "color": "#FF3B30", "bg": "#000000"},
    {"name": "Матрица", "style": "pixel", "color": "#39FF14", "bg": "#000000"},
    {"name": "Флип", "style": "flip", "color": "#F5F5F7", "bg": "#000000"},
    {"name": "Минимал", "style": "minimal", "color": "#7FDBFF", "bg": "#000000"},
    {"name": "Свои цифры", "style": "custom", "color": "#FFFFFF", "bg": "#000000"},
]
# Added in themes version 2 (appended once to existing configs, see Settings.load).
DESIGNER_THEMES = [
    {"name": "Никси", "style": "nixie", "color": "#FF7A1A", "bg": "#0A0604"},
    {"name": "Синтвейв", "style": "synthwave", "color": "#FF2E97", "bg": "#14002E"},
    {"name": "Терминал", "style": "terminal", "color": "#33FF66", "bg": "#020902"},
    {"name": "Баухаус", "style": "bauhaus", "color": "#E63946", "bg": "#F1E9DA"},
    {"name": "Чертёж", "style": "blueprint", "color": "#EAF2FF", "bg": "#0F3D73"},
    {"name": "Бинарные", "style": "binary", "color": "#00E5FF", "bg": "#07070B"},
]
# Added in themes version 3: original artwork in the spirit of games/films
# (no logos, characters or other copyrighted assets).
FANDOM_THEMES = [
    {"name": "Valorant", "style": "valorant", "color": "#FF4655", "bg": "#0F1923"},
    {"name": "Marathon", "style": "marathon", "color": "#C8FF00", "bg": "#0A0A0A"},
    {"name": "Animal Crossing", "style": "island", "color": "#FFF6DC", "bg": "#8ED1B5"},
    {"name": "Гибли", "style": "ghibli", "color": "#FFFFFF", "bg": "#6FB7E9"},
    {"name": "Покемон", "style": "pocket", "color": "#FFCB05", "bg": "#E3350D"},
]
# Added in themes version 4.
CUSTOMIZABLE_THEMES = [
    {"name": "Типографика", "style": "typo", "color": "#FFFFFF", "bg": "#000000",
     "font": "", "effect": "plain", "size": 100},
    {"name": "Material Expressive", "style": "material", "bg": "#FEF7FF", "s1": "#D0BCFF",
     "s2": "#FFD8E4", "s3": "#B9F0D0", "s4": "#FFDDB4", "digit": "#1D1B20", "colon": "#6750A4"},
    {"name": "Виджет", "style": "widget", "bg": "#2F7DF6", "box": "#000000", "time": "#FFFFFF",
     "date_bg": "#FF9F0A", "date": "#1C1C1E", "temp_bg": "#0B2A6F", "temp": "#FFFFFF", "lang": "ru"},
]
DEFAULT_THEMES = (DEFAULT_THEMES[:-1] + DESIGNER_THEMES + FANDOM_THEMES + CUSTOMIZABLE_THEMES
                  + DEFAULT_THEMES[-1:])
THEME_ADDITIONS = {2: DESIGNER_THEMES, 3: FANDOM_THEMES, 4: CUSTOMIZABLE_THEMES}
THEMES_VERSION = 4

RGB = tuple[int, int, int]
Frames = tuple[list[Image.Image], int]  # (frames, ms per frame)

SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}
PIXEL_FONT = {  # 5x7
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
}


def parse_hex(s: str) -> RGB:
    s = (s or "#FFFFFF").lstrip("#")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return 255, 255, 255


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


@lru_cache(maxsize=8)
def font(name: str, size: int) -> ImageFont.ImageFont:
    for path in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), name):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
                  fnt: ImageFont.ImageFont, fill: RGB) -> None:
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    x = box[0] + (box[2] - box[0] - (r - l)) / 2 - l
    y = box[1] + (box[3] - box[1] - (b - t)) / 2 - t
    draw.text((x, y), text, font=fnt, fill=fill)


# ---- styles (each draws on a canvas `SS` times larger than the output) -------

def _segment_polys(w: float, h: float) -> dict[str, list[tuple[float, float]]]:
    t = w * 0.17           # stroke thickness
    gap = t * 0.18
    L, R = t / 2 + w * 0.06, w - t / 2 - w * 0.06
    T, M, B = t / 2 + h * 0.04, h / 2, h - t / 2 - h * 0.04

    def hseg(x1: float, x2: float, y: float):
        return [(x1, y), (x1 + t / 2, y - t / 2), (x2 - t / 2, y - t / 2),
                (x2, y), (x2 - t / 2, y + t / 2), (x1 + t / 2, y + t / 2)]

    def vseg(x: float, y1: float, y2: float):
        return [(x, y1), (x + t / 2, y1 + t / 2), (x + t / 2, y2 - t / 2),
                (x, y2), (x - t / 2, y2 - t / 2), (x - t / 2, y1 + t / 2)]

    return {
        "a": hseg(L + gap, R - gap, T), "g": hseg(L + gap, R - gap, M),
        "d": hseg(L + gap, R - gap, B),
        "f": vseg(L, T + gap, M - gap), "b": vseg(R, T + gap, M - gap),
        "e": vseg(L, M + gap, B - gap), "c": vseg(R, M + gap, B - gap),
    }


def _colon_dots(draw: ImageDraw.ImageDraw, w: float, h: float, fill: RGB, r: float) -> None:
    for cy in (h * 0.33, h * 0.67):
        draw.ellipse((w / 2 - r, cy - r, w / 2 + r, cy + r), fill=fill)


def _draw_segment(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    dim = mix(bg, color, 0.12)
    if ch == ":":
        _colon_dots(draw, w, h, color if lit else dim, w * 0.09)
        return
    # digit box keeps a 0.6 aspect ratio inside the canvas
    bw, bh = min(w * 0.82, h * 0.88 * 0.6), min(h * 0.88, w * 0.82 / 0.6)
    ox, oy = (w - bw) / 2, (h - bh) / 2
    on = SEGMENTS.get(ch, "")
    for name, poly in _segment_polys(bw, bh).items():
        draw.polygon([(x + ox, y + oy) for x, y in poly], fill=color if name in on else dim)


def _draw_neon(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    glow_layer = Image.new("RGB", img.size, (0, 0, 0))
    _draw_segment(glow_layer, ch, color if lit else (0, 0, 0), (0, 0, 0), True)
    if ch != ":":  # drop the dim "off" segments from the glow layer
        mask = glow_layer.convert("L").point(lambda v: 255 if v > 40 else 0)
        glow_layer = Image.composite(glow_layer, Image.new("RGB", img.size), mask)
    glow = glow_layer.filter(ImageFilter.GaussianBlur(img.size[0] * 0.05))
    halo = glow_layer.filter(ImageFilter.GaussianBlur(img.size[0] * 0.015))
    core = Image.blend(glow_layer, Image.new("RGB", img.size, (255, 255, 255)), 0.35)
    core = Image.composite(core, Image.new("RGB", img.size), glow_layer.convert("L"))
    base = Image.new("RGB", img.size, bg)
    for layer in (glow, glow, halo, core):
        base = ImageChops.add(base, layer)
    dim_layer = Image.new("RGB", img.size, bg)
    _draw_segment(dim_layer, ch, mix(bg, color, 0.06), bg, False)  # faint unlit segments
    img.paste(ImageChops.lighter(base, dim_layer))


def _draw_pixel(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    rows = PIXEL_FONT.get(ch, PIXEL_FONT["0"])
    pitch = min(w / 6, h / 8)
    ox, oy = (w - pitch * 5) / 2, (h - pitch * 7) / 2
    dim = mix(bg, color, 0.10)
    r = pitch * 0.42
    for y, row in enumerate(rows):
        for x, bit in enumerate(row):
            cx, cy = ox + (x + 0.5) * pitch, oy + (y + 0.5) * pitch
            on = bit == "1" and (lit or ch != ":")
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color if on else dim)


def _draw_flip(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    pad = w * 0.05
    card_top, card_bottom = mix(bg, (60, 60, 66), 0.9), mix(bg, (44, 44, 50), 0.9)
    radius = w * 0.11
    draw.rounded_rectangle((pad, pad, w - pad, h - pad), radius, fill=card_bottom)
    draw.rounded_rectangle((pad, pad, w - pad, h / 2), radius, fill=card_top)
    draw.rectangle((pad, h / 2 - radius, w - pad, h / 2), fill=card_top)
    if ch == ":":
        _colon_dots(draw, w, h, color if lit else mix(card_bottom, color, 0.15), w * 0.08)
    else:
        centered_text(draw, (0, 0, w, h), ch, font("segoeuib.ttf", int(h * 0.78)), color)
    split = max(1, int(h * 0.018))
    draw.rectangle((pad, h / 2 - split, w - pad, h / 2 + split), fill=bg)
    for x in (pad, w - pad):  # hinge notches
        draw.ellipse((x - split * 2, h / 2 - split * 2, x + split * 2, h / 2 + split * 2), fill=bg)


def _draw_minimal(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    if ch == ":":
        _colon_dots(draw, w, h, color if lit else mix(bg, color, 0.15), w * 0.05)
        return
    centered_text(draw, (0, 0, w, h), ch, font("segoeuil.ttf", int(h * 0.95)), color)


# ---- designer styles ------------------------------------------------------------

def _text_mask(size: tuple[int, int], ch: str, fnt: ImageFont.ImageFont,
               box: tuple[float, float, float, float] | None = None, stroke: int = 0) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    box = box or (0, 0, size[0], size[1])
    l, t, r, b = draw.textbbox((0, 0), ch, font=fnt, stroke_width=stroke)
    x = box[0] + (box[2] - box[0] - (r - l)) / 2 - l
    y = box[1] + (box[3] - box[1] - (b - t)) / 2 - t
    draw.text((x, y), ch, font=fnt, fill=255, stroke_width=stroke, stroke_fill=255)
    return mask


def _vertical_gradient(size: tuple[int, int], top: RGB, bottom: RGB) -> Image.Image:
    col = Image.new("RGB", (1, size[1]))
    col.putdata([mix(top, bottom, y / max(1, size[1] - 1)) for y in range(size[1])])
    return col.resize(size, Image.Resampling.NEAREST)


def _glow(img: Image.Image, mask: Image.Image, color: RGB, radius: float, strength: int = 2) -> Image.Image:
    layer = Image.composite(Image.new("RGB", img.size, color), Image.new("RGB", img.size), mask)
    blurred = layer.filter(ImageFilter.GaussianBlur(radius))
    for _ in range(strength):
        img = ImageChops.add(img, blurred)
    return img


@lru_cache(maxsize=8)
def _nixie_wires(size: tuple[int, int], box: tuple[float, float, float, float]) -> Image.Image:
    """Outlines of all ten cathodes stacked behind the lit one (same for every digit)."""
    fnt = font("segoeuil.ttf", int(size[1] * 0.72))
    wires = Image.new("L", size, 0)
    for d in "0123456789":
        m = _text_mask(size, d, fnt, box)
        wires = ImageChops.lighter(wires, ImageChops.subtract(m.filter(ImageFilter.MaxFilter(3)), m))
    return wires


def _draw_nixie(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Nixie tube: glass, honeycomb mesh, faint wire digits, glowing cathode."""
    w, h = img.size
    canvas = img.copy()
    draw = ImageDraw.Draw(canvas)
    pad = w * 0.07
    tube = (pad, pad * 0.6, w - pad, h - pad * 0.6)
    glass = mix(bg, (38, 28, 22), 0.7)
    draw.rounded_rectangle(tube, radius=w * 0.28, fill=glass,
                           outline=mix(bg, (130, 110, 95), 0.45), width=max(1, int(w * 0.012)))
    tube_mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(tube_mask).rounded_rectangle(tube, radius=w * 0.28, fill=255)
    mesh = Image.new("RGB", img.size, glass)
    md = ImageDraw.Draw(mesh)
    step = w * 0.07
    mesh_color = mix(glass, (95, 80, 70), 0.55)
    for i in range(-int(h / step), int(w / step) + int(h / step) + 2):
        x = i * step
        md.line((x, 0, x + h * 0.58, h), fill=mesh_color, width=max(1, int(w * 0.004)))
        md.line((x, 0, x - h * 0.58, h), fill=mesh_color, width=max(1, int(w * 0.004)))
    canvas = Image.composite(Image.blend(canvas, mesh, 0.45), canvas, tube_mask)
    draw = ImageDraw.Draw(canvas)
    fnt = font("segoeuil.ttf", int(h * 0.72))
    box = (tube[0], tube[1] + h * 0.04, tube[2], tube[3])
    if ch == ":":
        wire = mix(glass, color, 0.10)
        _colon_dots(draw, w, h, wire, w * 0.07)
        dots = Image.new("L", img.size, 0)
        if lit:
            _colon_dots(ImageDraw.Draw(dots), w, h, 255, w * 0.055)
    else:
        canvas.paste(mix(glass, color, 0.13), mask=_nixie_wires(img.size, box))
        dots = _text_mask(img.size, ch, fnt, box) if lit else Image.new("L", img.size, 0)
    canvas = _glow(canvas, dots, color, w * 0.07, 2)
    canvas = _glow(canvas, dots, color, w * 0.02, 1)
    canvas.paste(mix(color, (255, 240, 200), 0.55), mask=dots.filter(ImageFilter.MinFilter(3)))
    shine = Image.new("L", img.size, 0)  # glass reflection
    ImageDraw.Draw(shine).rounded_rectangle((pad + w * 0.06, pad + h * 0.05, pad + w * 0.14, h * 0.55),
                                            radius=w * 0.05, fill=40)
    canvas.paste((255, 255, 255), mask=shine.filter(ImageFilter.GaussianBlur(w * 0.02)))
    img.paste(canvas)


def _draw_synthwave(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """80s sunset: gradient sky, neon floor grid, sliced gradient digit."""
    w, h = img.size
    canvas = _vertical_gradient(img.size, bg, mix(bg, color, 0.35))
    draw = ImageDraw.Draw(canvas)
    small = w < 64 * SS  # compact clock tile: no scenery
    horizon = h if small else h * 0.80
    grid = mix(bg, color, 0.75)
    lw = max(1, int(w * 0.008))
    for i in range(1, 7 if not small else 1):  # floor lines get denser towards the horizon
        y = horizon + (h - horizon) * (i / 6) ** 1.8
        draw.line((0, y, w, y), fill=grid, width=lw)
    for i in range(-6, 7) if not small else ():
        draw.line((w / 2 + i * w * 0.05, horizon, w / 2 + i * w * 0.32, h), fill=grid, width=lw)
    if not small:
        draw.line((0, horizon, w, horizon), fill=mix(color, (255, 255, 255), 0.4), width=lw * 2)

    if ch == ":":
        mask = Image.new("L", img.size, 0)
        _colon_dots(ImageDraw.Draw(mask), w, h * 0.86, 255, w * 0.08)
    else:
        mask = _text_mask(img.size, ch, font("segoeuib.ttf", int(h * 0.80)), (0, 0, w, horizon))
        mask = mask.transform(img.size, Image.Transform.AFFINE, (1, 0.18, -h * 0.09, 0, 1, 0),
                              Image.Resampling.BICUBIC)  # italic
    if not lit:
        mask = mask.point(lambda v: v // 6)
    top = mix(color, (255, 228, 94), 0.85)
    fill = _vertical_gradient(img.size, top, color)
    bbox = mask.getbbox()
    if bbox and ch != ":":  # sunset slices across the lower half of the digit
        cut = ImageDraw.Draw(mask)
        y0, y1 = bbox[1] + (bbox[3] - bbox[1]) * 0.52, bbox[3]
        n = 5
        for i in range(n):
            y = y0 + (y1 - y0) * i / n
            cut.rectangle((0, y, w, y + (y1 - y0) / n * (0.12 + 0.12 * i)), fill=0)
    canvas = _glow(canvas, mask, color, w * 0.05, 1)
    canvas.paste(fill, mask=mask)
    img.paste(canvas)


def _draw_terminal(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Phosphor CRT: monospace glyph, glow, scanlines, vignette."""
    w, h = img.size
    canvas = Image.new("RGB", img.size, bg)
    mask = _text_mask(img.size, ch, font("consolab.ttf", int(h * 0.95)))
    if not lit:
        mask = mask.point(lambda v: v // 8)
    canvas = _glow(canvas, mask, color, w * 0.05, 1)
    canvas.paste(color, mask=mask)
    canvas.paste(mix(color, (255, 255, 255), 0.5), mask=mask.filter(ImageFilter.MinFilter(9)))
    period = 3 * SS  # scanlines survive the downscale (3 px period)
    scan = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(scan)
    for y in range(0, h, period):
        sd.rectangle((0, y, w, y + SS - 1), fill=110)
    canvas.paste(bg, mask=scan)
    vignette = Image.radial_gradient("L").resize(img.size).point(lambda v: max(0, v - 120) * 2)
    canvas.paste(bg, mask=vignette)
    img.paste(canvas)


BAUHAUS_FONT = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    ":": ["000", "010", "000", "010", "000"],
}


def _draw_bauhaus(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Geometric blocks; outer corners rounded into half-discs, three-colour palette."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    rows = BAUHAUS_FONT.get(ch, BAUHAUS_FONT["0"])
    cell = min(w / 3.5, h / 5.5)
    gap = cell * 0.07
    ox, oy = (w - cell * 3) / 2, (h - cell * 5) / 2
    palette = [color, (29, 53, 87), (244, 163, 0)]

    def on(r: int, c: int) -> bool:
        return 0 <= r < 5 and 0 <= c < 3 and rows[r][c] == "1"

    for r in range(5):
        for c in range(3):
            if not on(r, c):
                continue
            fill = palette[(r * 2 + c) % 3] if lit else mix(bg, palette[(r * 2 + c) % 3], 0.2)
            corners = (not on(r - 1, c) and not on(r, c - 1), not on(r - 1, c) and not on(r, c + 1),
                       not on(r + 1, c) and not on(r, c + 1), not on(r + 1, c) and not on(r, c - 1))
            x0, y0 = ox + c * cell + gap, oy + r * cell + gap
            draw.rounded_rectangle((x0, y0, x0 + cell - 2 * gap, y0 + cell - 2 * gap),
                                   radius=(cell - 2 * gap) / 2 - 1, fill=fill, corners=corners)


def _draw_blueprint(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Technical drawing: grid paper, outlined digit, dimension line."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    minor, major = mix(bg, (255, 255, 255), 0.10), mix(bg, (255, 255, 255), 0.22)
    for i in range(17):
        p = i * w / 16
        c = major if i % 4 == 0 else minor
        lw = max(1, int(w * (0.006 if i % 4 == 0 else 0.003)))
        draw.line((p, 0, p, h), fill=c, width=lw)
        draw.line((0, p * h / w, w, p * h / w), fill=c, width=lw)
    ink = color if lit else mix(bg, color, 0.25)
    stroke = max(1, int(w * 0.014))
    if ch == ":":
        for cy in (h * 0.36, h * 0.64):
            r = w * 0.07
            draw.ellipse((w / 2 - r, cy - r, w / 2 + r, cy + r), outline=ink, width=stroke)
            draw.line((w / 2 - r * 1.6, cy, w / 2 + r * 1.6, cy), fill=ink, width=max(1, stroke // 3))
        return
    fnt = font("segoeuib.ttf", int(h * 0.74))
    box = (w * 0.16, h * 0.06, w, h * 0.90) if w >= 64 * SS else (0, 0, w, h)
    mask = _text_mask(img.size, ch, fnt, box, stroke=stroke)
    inner = _text_mask(img.size, ch, fnt, box)
    img.paste(ink, mask=ImageChops.subtract(mask, inner))
    if w < 64 * SS:
        return  # compact clock tile: digit only
    bb = inner.getbbox()
    if bb:  # vertical dimension line with ticks and arrows
        x = w * 0.09
        thin = max(1, stroke // 2)
        draw.line((x, bb[1], x, bb[3]), fill=ink, width=thin)
        for y in (bb[1], bb[3]):
            draw.line((x - w * 0.03, y, x + w * 0.03, y), fill=ink, width=thin)
            d = w * 0.025 * (1 if y == bb[1] else -1)
            draw.polygon([(x, y), (x - w * 0.018, y + d), (x + w * 0.018, y + d)], fill=ink)
    small = font("segoeui.ttf", int(h * 0.08))
    draw.text((w * 0.60, h * 0.89), f"№ {ch}", font=small, fill=mix(bg, color, 0.7))


def _draw_binary(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """The digit's value as glowing bits 8-4 / 2-1 with a small numeral."""
    w, h = img.size
    canvas = img.copy()
    draw = ImageDraw.Draw(canvas)
    if ch == ":":
        mask = Image.new("L", img.size, 0)
        _colon_dots(ImageDraw.Draw(mask), w, h, 255 if lit else 40, w * 0.06)
        canvas = _glow(canvas, mask, color, w * 0.04, 1)
        canvas.paste(color, mask=mask)
        img.paste(canvas)
        return
    value = int(ch)
    size = min(w, h * 0.8) * 0.36
    gap = size * 0.18
    ox, oy = (w - 2 * size - gap) / 2, h * 0.08
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    dim = mix(bg, color, 0.22)
    for i, bit in enumerate((8, 4, 2, 1)):
        x = ox + (i % 2) * (size + gap)
        y = oy + (i // 2) * (size + gap)
        rect = (x, y, x + size, y + size)
        if value & bit and lit:
            md.rounded_rectangle(rect, radius=size * 0.25, fill=255)
        else:
            draw.rounded_rectangle(rect, radius=size * 0.25, outline=dim, width=max(1, int(w * 0.012)))
    canvas = _glow(canvas, mask, color, w * 0.05, 1)
    canvas.paste(color, mask=mask)
    label = font("consolab.ttf", int(h * 0.16))
    centered_text(ImageDraw.Draw(canvas), (0, h * 0.80, w, h * 0.98), f"{value:04b}", label,
                  mix(bg, color, 0.6))
    img.paste(canvas)


# ---- game / film inspired styles ----------------------------------------------

@lru_cache(maxsize=16)
def font_var(name: str, size: int, variation: str) -> ImageFont.ImageFont:
    f = font(name, size)
    try:
        f = ImageFont.truetype(f.path, size)  # own copy: variations are per object
        f.set_variation_by_name(variation)
    except (AttributeError, OSError, ValueError):
        pass
    return f


def _soft_round(mask: Image.Image, radius: float) -> Image.Image:
    """Round every corner of a glyph mask (blur + threshold)."""
    return mask.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: 255 if v > 110 else 0)


def _dilate(mask: Image.Image, px: int) -> Image.Image:
    px = max(3, px | 1)  # MaxFilter(1) crashes Pillow with a division by zero
    if px <= 15:
        return mask.filter(ImageFilter.MaxFilter(px))
    return mask.filter(ImageFilter.GaussianBlur(px / 2)).point(lambda v: 255 if v > 20 else 0)


def _offset(mask: Image.Image, dx: float, dy: float) -> Image.Image:
    return ImageChops.offset(mask, int(dx), int(dy))


def _draw_valorant(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Tactical-shooter HUD: navy, red slash, corner brackets, condensed off-white digit."""
    w, h = img.size
    small = w < 64 * SS
    off_white = (236, 232, 225)
    draw = ImageDraw.Draw(img)
    for i in range(-h, w, int(w * 0.06)):  # faint diagonal texture
        draw.line((i, h, i + h, 0), fill=mix(bg, off_white, 0.035), width=max(1, int(w * 0.01)))
    draw.polygon([(0, h * 0.72), (w, h * 0.50), (w, h * 0.60), (0, h * 0.82)], fill=color)
    if not small:
        L, t = w * 0.10, max(1, int(w * 0.012))
        for (x, y, sx, sy) in ((w * 0.05, h * 0.05, 1, 1), (w * 0.95, h * 0.05, -1, 1),
                               (w * 0.05, h * 0.95, 1, -1), (w * 0.95, h * 0.95, -1, -1)):
            draw.line((x, y, x + sx * L, y), fill=off_white, width=t)
            draw.line((x, y, x, y + sy * L), fill=off_white, width=t)
    ink = off_white if lit else mix(bg, off_white, 0.15)
    if ch == ":":
        for cy in (h * 0.36, h * 0.64):
            r = w * 0.075
            draw.polygon([(w / 2, cy - r), (w / 2 + r, cy), (w / 2, cy + r), (w / 2 - r, cy)],
                         fill=color if lit else mix(bg, color, 0.2))
        return
    fnt = font_var("bahnschrift.ttf", int(h * 0.92), "Bold Condensed")
    mask = _text_mask(img.size, ch, fnt, (0, 0, w, h * 0.96))
    shadow = _offset(mask, w * 0.025, h * 0.02)
    img.paste(mix(bg, (0, 0, 0), 0.5), mask=shadow)
    img.paste(ink, mask=mask)
    if not small:
        draw.rectangle((w * 0.08, h * 0.10, w * 0.13, h * 0.15), fill=color)
        draw.text((w * 0.66, h * 0.86), f"// 0{ch}", font=font("bahnschrift.ttf", int(h * 0.075)),
                  fill=mix(bg, off_white, 0.7))


def _draw_marathon(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Brutalist sci-fi graphics: acid colour, glitch slices, barcode, registration marks."""
    w, h = img.size
    small = w < 64 * SS
    draw = ImageDraw.Draw(img)
    paper = (232, 232, 222)
    if not small:
        step = w * 0.045  # halftone corner
        for gy in range(12):
            for gx in range(12):
                x, y = w - gx * step - step / 2, h - gy * step - step / 2
                r = step * 0.42 * max(0.0, 1 - (gx + gy) / 12)
                if r > 0.5:
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=mix(bg, color, 0.28))
        tick = max(1, int(w * 0.008))
        for (x, y) in ((w * 0.09, h * 0.09), (w * 0.91, h * 0.09)):  # registration marks
            r = w * 0.035
            draw.ellipse((x - r, y - r, x + r, y + r), outline=paper, width=tick)
            draw.line((x - r * 1.6, y, x + r * 1.6, y), fill=paper, width=tick)
            draw.line((x, y - r * 1.6, x, y + r * 1.6), fill=paper, width=tick)
        micro = font("consolab.ttf", int(h * 0.06))
        draw.text((w * 0.17, h * 0.055), f"UNIT-0{ch if ch != ':' else 'X'} // RUN", font=micro,
                  fill=mix(bg, paper, 0.75))
        bars = [3, 1, 2, 1, 1, 3, 2, 1, 3, 1, 1, 2, 2, 1, 3, 1, 2, 1, 1, 3]  # barcode
        x = w * 0.08
        unit = w * 0.011
        for i, b in enumerate(bars):
            if i % 2 == 0:
                draw.rectangle((x, h * 0.88, x + b * unit, h * 0.95), fill=paper)
            x += b * unit + unit * 0.6
    ink = color if lit else mix(bg, color, 0.15)
    if ch == ":":
        for cy in (h * 0.38, h * 0.62):
            s = w * 0.07
            draw.rectangle((w / 2 - s, cy - s, w / 2 + s, cy + s), fill=ink)
        return
    fnt = font_var("bahnschrift.ttf", int(h * 0.86), "Bold")
    mask = _text_mask(img.size, ch, fnt, (0, h * 0.04, w, h * 0.88))
    if not small:  # glitch: two displaced horizontal slices
        for y0, y1, dx in ((0.30, 0.37, 0.07), (0.58, 0.63, -0.05)):
            band = mask.crop((0, int(h * y0), w, int(h * y1)))
            mask.paste(0, (0, int(h * y0), w, int(h * y1)))
            mask.paste(band, (int(w * dx), int(h * y0)))
        img.paste(mix(bg, paper, 0.9), mask=_offset(mask, -w * 0.02, 0).point(lambda v: v // 3))
    img.paste(ink, mask=mask)


def _leaf(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill: RGB, vein: RGB) -> None:
    draw.ellipse((cx - size, cy - size * 0.55, cx + size, cy + size * 0.55), fill=fill)
    draw.polygon([(cx + size * 0.8, cy - size * 0.35), (cx + size * 1.35, cy - size * 0.75),
                  (cx + size * 1.0, cy - size * 0.1)], fill=fill)
    draw.line((cx - size * 0.85, cy + size * 0.1, cx + size * 1.1, cy - size * 0.45),
              fill=vein, width=max(1, int(size * 0.12)))


def _draw_island(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Cozy island life: mint polka dots, cream sticker digit with brown outline, a leaf."""
    w, h = img.size
    small = w < 64 * SS
    draw = ImageDraw.Draw(img)
    dot = mix(bg, (255, 255, 255), 0.25)
    step = w * 0.14
    for gy in range(9):
        for gx in range(9):
            x = gx * step + (step / 2 if gy % 2 else 0)
            y = gy * step
            r = step * 0.18
            draw.ellipse((x - r, y - r, x + r, y + r), fill=dot)
    brown = (122, 90, 58)
    shadow = mix(bg, (0, 60, 40), 0.35)
    if ch == ":":
        mask = Image.new("L", img.size, 0)
        _colon_dots(ImageDraw.Draw(mask), w, h, 255, w * 0.075)
    else:
        mask = _text_mask(img.size, ch, font("segoeuib.ttf", int(h * 0.80)), (0, h * 0.05, w, h))
        mask = _soft_round(mask, w * 0.025)
    outline = _dilate(mask, int(w * 0.05))
    img.paste(shadow, mask=_offset(outline, w * 0.02, h * 0.03))
    img.paste(brown if lit else mix(bg, brown, 0.3), mask=outline)
    img.paste(color if lit else mix(bg, color, 0.4), mask=mask)
    if not small and ch != ":":
        _leaf(draw, w * 0.80, h * 0.14, w * 0.075, (77, 179, 106), (46, 120, 66))


def _draw_ghibli(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Hand-painted summer sky: soft gradient, fluffy clouds, rolling hills, serif digit."""
    w, h = img.size
    small = w < 64 * SS
    sky = _vertical_gradient(img.size, bg, mix(bg, (255, 246, 230), 0.75))
    if not small:
        clouds = Image.new("L", img.size, 0)
        cd = ImageDraw.Draw(clouds)
        for cx, cy, r in ((0.18, 0.22, 0.11), (0.30, 0.17, 0.14), (0.44, 0.23, 0.10),
                          (0.72, 0.36, 0.09), (0.84, 0.31, 0.12), (0.95, 0.37, 0.08)):
            cd.ellipse((w * (cx - r), h * (cy - r), w * (cx + r), h * (cy + r)), fill=255)
        cd.rectangle((w * 0.10, h * 0.22, w * 0.52, h * 0.30), fill=255)
        clouds = clouds.filter(ImageFilter.GaussianBlur(w * 0.012))
        sky.paste((255, 255, 255), mask=clouds)
        shade = _offset(clouds, 0, h * 0.025).point(lambda v: v // 5)
        sky.paste(mix(bg, (255, 255, 255), 0.6), mask=ImageChops.subtract(shade, clouds))
        hills = ImageDraw.Draw(sky)
        hills.ellipse((-w * 0.3, h * 0.80, w * 0.8, h * 1.5), fill=(121, 179, 107))
        hills.ellipse((w * 0.35, h * 0.86, w * 1.4, h * 1.6), fill=(78, 138, 75))
    img.paste(sky)
    shadow_col = mix(bg, (20, 40, 80), 0.6)
    if ch == ":":
        mask = Image.new("L", img.size, 0)
        _colon_dots(ImageDraw.Draw(mask), w, h, 255 if lit else 70, w * 0.06)
    else:
        mask = _text_mask(img.size, ch, font("georgiab.ttf", int(h * 0.74)), (0, 0, w, h * 0.92))
        if not lit:
            mask = mask.point(lambda v: v // 4)
    img.paste(shadow_col, mask=_offset(mask, w * 0.02, h * 0.025).filter(
        ImageFilter.GaussianBlur(w * 0.012)).point(lambda v: v // 2))
    img.paste(color, mask=mask)


def _pokeball(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], top: RGB) -> None:
    x0, y0, x1, y1 = box
    w = x1 - x0
    band = max(1, int(w * 0.08))
    draw.ellipse(box, fill=(245, 245, 245), outline=(25, 25, 25), width=band)
    draw.pieslice(box, 180, 360, fill=top, outline=(25, 25, 25), width=band)
    cy = (y0 + y1) / 2
    draw.rectangle((x0, cy - band / 2, x1, cy + band / 2), fill=(25, 25, 25))
    r = w * 0.17
    cx = (x0 + x1) / 2
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(245, 245, 245), outline=(25, 25, 25), width=band)


def _draw_pocket(img: Image.Image, ch: str, color: RGB, bg: RGB, lit: bool) -> None:
    """Pocket-monster ball: red/white halves, black band, yellow digit with blue outline."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    if ch == ":":
        img.paste(bg, (0, 0, w, h))
        draw.rectangle((0, h / 2, w, h), fill=(245, 245, 245))
        for cy in (h * 0.30, h * 0.70):
            r = w * 0.14
            _pokeball(draw, (w / 2 - r, cy - r, w / 2 + r, cy + r), bg if lit else mix(bg, (245, 245, 245), 0.6))
        return
    draw.rectangle((0, h / 2, w, h), fill=(245, 245, 245))
    band = h * 0.07
    draw.rectangle((0, h / 2 - band / 2, w, h / 2 + band / 2), fill=(25, 25, 25))
    r = w * 0.17
    draw.ellipse((w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), fill=(245, 245, 245),
                 outline=(25, 25, 25), width=max(1, int(band * 0.7)))
    blue, deep = (42, 117, 187), (24, 52, 120)
    mask = _text_mask(img.size, ch, font("ariblk.ttf", int(h * 0.74)), (0, 0, w, h * 0.98))
    mask = _soft_round(mask, w * 0.012)
    outline = _dilate(mask, int(w * 0.07))
    img.paste(deep, mask=_offset(outline, w * 0.03, h * 0.035))
    img.paste(blue, mask=outline)
    img.paste(color if lit else mix((245, 245, 245), color, 0.3), mask=mask)


DRAWERS = {"segment": _draw_segment, "neon": _draw_neon, "pixel": _draw_pixel,
           "flip": _draw_flip, "minimal": _draw_minimal, "nixie": _draw_nixie,
           "synthwave": _draw_synthwave, "terminal": _draw_terminal, "bauhaus": _draw_bauhaus,
           "blueprint": _draw_blueprint, "binary": _draw_binary, "valorant": _draw_valorant,
           "marathon": _draw_marathon, "island": _draw_island, "ghibli": _draw_ghibli,
           "pocket": _draw_pocket}


def fit_cover(image: Image.Image) -> Image.Image:
    """Spotify cover filling one 128x128 screen."""
    return ImageOps.fit(image.convert("RGB"), (SIZE, SIZE), Image.Resampling.LANCZOS)


# ---- colour roles ---------------------------------------------------------------
# Every colour a style uses is a theme key the user can change in the editor.

DEFAULT_ROLES = [("color", "Цифры", "#FFFFFF"), ("bg", "Фон", "#000000")]
STYLE_ROLES = {
    "widget": [("bg", "Рамка", "#2F7DF6"), ("box", "Плашка времени", "#000000"),
               ("time", "Время", "#FFFFFF"), ("date_bg", "Плашка даты", "#FF9F0A"),
               ("date", "Дата", "#1C1C1E"), ("temp_bg", "Круг погоды", "#0B2A6F"),
               ("temp", "Погода", "#FFFFFF")],
    "material": [("bg", "Фон", "#FEF7FF"), ("s1", "Фигура 1", "#D0BCFF"),
                 ("s2", "Фигура 2", "#FFD8E4"), ("s3", "Фигура 3", "#B9F0D0"),
                 ("s4", "Фигура 4", "#FFDDB4"), ("digit", "Цифры", "#1D1B20"),
                 ("colon", "Двоеточие", "#6750A4")],
}
SINGLE_STYLES = {"widget"}  # one-screen faces: shown in the middle, pictures on the sides


def style_roles(style: str) -> list[tuple[str, str, str]]:
    return STYLE_ROLES.get(style, DEFAULT_ROLES)


CANVAS_ROLE = {"swiss": "dark", "glass": "bg", "crt": "case", "serif": "paper", "gameboy": "lightest"}


def canvas_bg(theme: dict) -> RGB:
    """Colour behind a style's digits (empty side screens, compact clock)."""
    style = theme.get("style", "")
    if style == "soft":
        return (0,0,0)
    if style in STYLE_ROLES or style in CANVAS_ROLE:
        return role(theme, CANVAS_ROLE.get(style, "bg"))
    return parse_hex(theme.get("bg", "#000000"))


def role(theme: dict, name: str) -> RGB:
    default = next((d for r, _, d in style_roles(theme.get("style", "")) if r == name), "#FFFFFF")
    return parse_hex(theme.get(name) or default)


# ---- Material 3 Expressive --------------------------------------------------------

def _polar_shape(n: int, amp: float, phase: float = 0.0, points: int = 360):
    import math
    pts = []
    for i in range(points):
        t = 2 * math.pi * i / points
        r = (1 + amp * math.cos(n * t + phase)) / (1 + amp)
        pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def _superellipse(p: float, rotate: float = 0.0, points: int = 240):
    import math
    pts = []
    for i in range(points):
        t = 2 * math.pi * i / points
        c, s = math.cos(t), math.sin(t)
        x = math.copysign(abs(c) ** (2 / p), c)
        y = math.copysign(abs(s) ** (2 / p), s)
        if rotate:
            x, y = x * math.cos(rotate) - y * math.sin(rotate), x * math.sin(rotate) + y * math.cos(rotate)
        pts.append((x, y))
    return pts


# One expressive shape per digit, so every number gets its own silhouette.
M3_SHAPES = {
    "0": ("cookie", lambda: _polar_shape(9, 0.09)),
    "1": ("pill", None),
    "2": ("clover", lambda: _polar_shape(4, 0.24, 0.785)),
    "3": ("sunny", lambda: _polar_shape(8, 0.07)),
    "4": ("gem", lambda: _superellipse(1.6, 0.785)),
    "5": ("flower", lambda: _polar_shape(6, 0.17)),
    "6": ("squircle", lambda: _superellipse(4.0)),
    "7": ("arch", None),
    "8": ("cookie12", lambda: _polar_shape(12, 0.05)),
    "9": ("pentagon", lambda: _polar_shape(5, 0.11, -1.5708)),
}


def m3_shape_mask(size: tuple[int, int], ch: str, scale: float = 0.92) -> Image.Image:
    w, h = size
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    kind, gen = M3_SHAPES.get(ch, M3_SHAPES["0"])
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 * scale
    if kind == "pill":
        d.rounded_rectangle((cx - r * 0.62, cy - r, cx + r * 0.62, cy + r), radius=r * 0.62 - 1, fill=255)
    elif kind == "arch":
        d.rounded_rectangle((cx - r * 0.86, cy - r * 0.2, cx + r * 0.86, cy + r), radius=r * 0.18, fill=255)
        d.pieslice((cx - r * 0.86, cy - r, cx + r * 0.86, cy + r * 0.72), 180, 360, fill=255)
    else:
        d.polygon([(cx + x * r, cy + y * r) for x, y in gen()], fill=255)
    return mask


def _draw_material(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    bg = role(theme, "bg")
    if ch == ":":
        dot = role(theme, "colon") if lit else mix(bg, role(theme, "colon"), 0.25)
        draw = ImageDraw.Draw(img)
        for i, cy in enumerate((h * 0.34, h * 0.66)):
            r = w * (0.10 if i == 0 else 0.085)  # slightly different sizes: playful
            draw.ellipse((w / 2 - r, cy - r, w / 2 + r, cy + r), fill=dot)
        return
    shape = role(theme, f"s{pos % 4 + 1}")
    img.paste(shape if lit else mix(bg, shape, 0.3), mask=m3_shape_mask(img.size, ch))
    mask = _text_mask(img.size, ch, font("segoeuib.ttf", int(h * 0.60)), (0, 0, w, h * 0.97))
    img.paste(role(theme, "digit"), mask=_soft_round(mask, w * 0.012))


# ---- Typography: font, effect and size chosen by the user ---------------------------

TYPO_EFFECTS = {"plain": "Обычный", "outline": "Контур", "shadow": "Тень", "glow": "Свечение",
                "underline": "Подчёркивание", "boxed": "В рамке"}


def _typo_font(theme: dict, px: int) -> ImageFont.ImageFont:
    path = theme.get("font") or ""
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return font("segoeuil.ttf", px)


def _draw_typo(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    color, bg = role(theme, "color"), role(theme, "bg")
    ink = color if lit else mix(bg, color, 0.15)
    scale = max(30, min(140, int(theme.get("size") or 100))) / 100
    effect = theme.get("effect", "plain")
    mask = _text_mask(img.size, ch, _typo_font(theme, int(h * 0.82 * scale)))
    draw = ImageDraw.Draw(img)
    if effect == "shadow":
        img.paste(mix(bg, (0, 0, 0), 0.6) if sum(bg) > 120 else mix(bg, color, 0.25),
                  mask=_offset(mask, w * 0.03, h * 0.03).filter(ImageFilter.GaussianBlur(w * 0.01)))
    elif effect == "glow" and lit:
        base = _glow(img.copy(), mask, color, w * 0.06, 2)
        img.paste(base)
    if effect == "outline":
        stroke = max(SS, int(w * 0.014))
        img.paste(ink, mask=ImageChops.subtract(_dilate(mask, stroke * 2 + 1), mask))
    else:
        img.paste(ink, mask=mask)
    box = mask.getbbox()
    if box and ch != ":":
        if effect == "underline":
            y = min(h * 0.95, box[3] + h * 0.05)
            draw.rounded_rectangle((box[0], y, box[2], y + h * 0.035), radius=h * 0.017, fill=ink)
        elif effect == "boxed":
            pad = w * 0.06
            draw.rounded_rectangle((pad, pad, w - pad, h - pad), radius=w * 0.12, outline=ink,
                                   width=max(SS, int(w * 0.012)))


THEME_DRAWERS = {"material": _draw_material, "typo": _draw_typo}


def render(style: str, ch: str, color: str, bg: str, size: tuple[int, int] = (SIZE, SIZE),
           lit: bool = True, theme: dict | None = None, pos: int = 0) -> Image.Image:
    """One character in a style. Styles with several colours / options read them from `theme`."""
    theme = theme or {"style": style, "color": color, "bg": bg}
    if style in SQUARE_STYLES and size[0] != size[1]:
        # designed as square tiles: draw one and centre it (compact HH:MM cells)
        side = min(size)
        tile = render(style, ch, color, bg, (side, side), lit, theme, pos)
        canvas = Image.new("RGB", size, canvas_bg(theme))
        canvas.paste(tile, ((size[0] - side) // 2, (size[1] - side) // 2))
        return canvas
    b = canvas_bg(theme) if style in THEME_DRAWERS else parse_hex(bg)
    big = Image.new("RGB", (size[0] * SS, size[1] * SS), b)
    if style in THEME_DRAWERS:
        THEME_DRAWERS[style](big, ch, theme, lit, pos)
    else:
        DRAWERS.get(style, _draw_segment)(big, ch, parse_hex(color), b, lit)
    return big.resize(size, Image.Resampling.LANCZOS)


# ---- Widget: one-screen face (time, weekday + date, temperature) ---------------------

WEEKDAYS = {"ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
            "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def widget_frame(theme: dict, time_text: str, weekday: int, day: int, temp: float | None,
                 size: int = SIZE) -> Image.Image:
    S = size * SS
    img = Image.new("RGB", (S, S), role(theme, "bg"))
    d = ImageDraw.Draw(img)
    u = S / 128  # layout in 128-px units
    d.rounded_rectangle((7 * u, 7 * u, 121 * u, 62 * u), radius=15 * u, fill=role(theme, "box"))
    centered_text(d, (7 * u, 7 * u, 121 * u, 62 * u), time_text,
                  font("segoeui.ttf", int(38 * u)), role(theme, "time"))
    d.rounded_rectangle((7 * u, 68 * u, 61 * u, 121 * u), radius=13 * u, fill=role(theme, "date_bg"))
    names = WEEKDAYS.get(theme.get("lang", "ru"), WEEKDAYS["ru"])
    label = font("segoeuib.ttf", int(16 * u))
    d.text((14 * u, 75 * u), names[weekday % 7], font=label, fill=role(theme, "date"))
    d.text((14 * u, 95 * u), str(day), font=label, fill=role(theme, "date"))
    d.ellipse((67 * u, 68 * u, 121 * u, 122 * u), fill=role(theme, "temp_bg"))
    temp_text = f"{round(temp)}°" if temp is not None else "--°"
    centered_text(d, (67 * u, 68 * u, 121 * u, 122 * u), temp_text,
                  font("segoeuib.ttf", int(17 * u)), role(theme, "temp"))
    return img.resize((size, size), Image.Resampling.LANCZOS)


# ---- user media ---------------------------------------------------------------

def load_media(path: str, size: tuple[int, int] = (SIZE, SIZE)) -> Frames:
    """Picture or GIF -> frames cropped to fill `size` (max MAX_FRAMES frames)."""
    with Image.open(path) as im:
        count = getattr(im, "n_frames", 1)
        step = max(1, -(-count // MAX_FRAMES))  # ceil: sample long GIFs evenly
        frames, total_ms = [], 0
        for i in range(0, count, step):
            im.seek(i)
            frame = im.convert("RGBA")
            flat = Image.new("RGB", frame.size, (0, 0, 0))
            flat.paste(frame, mask=frame.getchannel("A"))
            frames.append(ImageOps.fit(flat, size, Image.Resampling.LANCZOS))
            total_ms += int(im.info.get("duration", 100) or 100) * step
    return frames, max(50, total_ms // max(1, len(frames)))


# ---- what goes on one screen -----------------------------------------------------

def _render_theme(theme: dict, ch: str, size: tuple[int, int], lit: bool, pos: int) -> Image.Image:
    style = theme.get("style", "segment")
    if style == "custom" or style in SINGLE_STYLES:
        style = "segment"  # custom pack without this picture yet
    return render(style, ch, theme.get("color", "#FFFFFF"), theme.get("bg", "#000000"),
                  size, lit=lit, theme=theme, pos=pos)


def char_frames(theme: dict, ch: str, blink: bool, custom: dict[str, str], pos: int = 0) -> Frames:
    if theme.get("style") == "custom":
        path = custom.get(ch)
        if path and os.path.exists(path):
            return load_media(path)
    if ch == ":" and blink:
        return [_render_theme(theme, ch, (SIZE, SIZE), True, pos),
                _render_theme(theme, ch, (SIZE, SIZE), False, pos)], BLINK_MS
    return [_render_theme(theme, ch, (SIZE, SIZE), True, pos)], 1000


def compact_clock_frames(theme: dict, text: str, blink: bool, custom: dict[str, str]) -> Frames:
    """A dedicated two-row composition on one continuous square panel."""
    style = theme.get("style", "swiss")
    hours, minutes = text.split(":")
    scale = 3
    size = SIZE * scale
    background = canvas_bg(theme)
    foreground = role(theme, "light") if style == "swiss" else (255, 255, 255)
    font_name = "ArchivoBlack-Regular.ttf"
    if style == "swiss":
        background = role(theme, f"t{hours[0]}")
        foreground = role(theme, "dark" if _lum(background) > .33 else "light")
    elif style == "glass":
        foreground, font_name = role(theme, "digit"), "Unbounded-Variable.ttf"
    elif style == "crt":
        background, foreground, font_name = role(theme, "screen"), role(theme, "phosphor"), "VT323-Regular.ttf"
    elif style == "serif":
        background, foreground, font_name = role(theme, "paper"), role(theme, "ink"), "InstrumentSerif-Italic.ttf"
    elif style == "soft":
        background, foreground, font_name = (0,0,0), role(theme, "digit"), "Outfit-Variable.ttf"
    elif style == "gameboy":
        background, foreground, font_name = role(theme, "lightest"), role(theme, "darkest"), "PressStart2P-Regular.ttf"

    def frame(lit):
        image = Image.new("RGB", (size, size), background)
        if style == "crt":
            _draw_crt(image, "", theme, True, 0, (hours,minutes), lit)
            return image.resize((SIZE,SIZE), Image.Resampling.LANCZOS)
        if style == "glass":
            _draw_glass(image, "", theme, True, 0)
        elif style == "soft":
            image.paste(role(theme,"shape"),mask=soft_form_mask((size,size),"1"))
        draw = ImageDraw.Draw(image)
        if style == "serif":
            for y in (8, 120):
                draw.line((8*scale, y*scale, 120*scale, y*scale), fill=role(theme, "rule"), width=scale)
        if style == "gameboy":
            draw.rectangle((5*scale, 5*scale, 123*scale, 123*scale), outline=role(theme, "dark"), width=2*scale)
        if style == "custom":
            for i, ch in enumerate(hours + minutes):
                path = custom.get(ch)
                if path and os.path.exists(path):
                    image.paste(load_media(path, (54*scale, 54*scale))[0][0],
                                ((9+(i%2)*57)*scale, (8+(i//2)*59)*scale))
        else:
            fnt = bundled_font(font_name, (38 if style == "gameboy" else 46 if style == "glass" else 57)*scale, "Bold" if style == "soft" else None)
            boxes = ((20*scale,18*scale,108*scale,59*scale),(20*scale,69*scale,108*scale,110*scale)) if style == "glass" else ((8*scale,7*scale,120*scale,61*scale),(8*scale,67*scale,120*scale,121*scale))
            for value, box in zip((hours,minutes), boxes):
                while draw.textlength(value, font=fnt) > box[2]-box[0]:
                    fnt = bundled_font(font_name, max(scale, fnt.size-scale), "Bold" if style == "soft" else None)
                centered_text(draw, box, value, fnt, foreground)
        # Separator is the only animated part; neither row jumps on a blink.
        color = foreground if lit else background
        draw.line((56*scale, 64*scale, 72*scale, 64*scale), fill=color, width=scale)
        return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return ([frame(True), frame(False)], BLINK_MS) if blink else ([frame(True)], 1000)


def theme_chars(theme: dict, fallback: dict[str, str] | None = None) -> dict[str, str]:
    """Pictures of a custom pack (older configs kept them globally)."""
    return dict(theme.get("chars") or fallback or {})


def theme_thumbnail(theme: dict, text: str = "12:34", tile: int = 40, gap: int = 3, compact: bool = False) -> Image.Image:
    """A strip of five small screens for the theme gallery."""
    if compact:
        return compact_clock_frames(theme, text, False, theme_chars(theme))[0][0].resize((tile, tile), Image.Resampling.LANCZOS)
    strip = Image.new("RGB", (tile * 5 + gap * 4, tile), (16, 16, 18))
    if theme.get("style") in SINGLE_STYLES:
        side = Image.new("RGB", (tile, tile), (34, 34, 38))
        for i in (0, 1, 3, 4):
            strip.paste(side, (i * (tile + gap), 0))
        strip.paste(widget_frame(theme, "12:34", 0, 26, 18, size=tile), (2 * (tile + gap), 0))
        return strip
    chars = theme_chars(theme)
    digit_pos = 0
    for i, ch in enumerate(text):
        path = chars.get(ch) if theme.get("style") == "custom" else None
        if path and os.path.exists(path):
            img = load_media(path, (tile, tile))[0][0]
        else:
            img = _render_theme(theme, ch, (tile, tile), True, digit_pos)
        if ch != ":":
            digit_pos += 1
        strip.paste(img, (i * (tile + gap), 0))
    return strip


# Built-in clock-face renderers
# Measurements are in the design's 200-px tile units (u = canvas width / 200).
# Fonts (SIL OFL, bundled in resources/fonts): Archivo Black, Space Mono, Unbounded,
# VT323, Instrument Serif, Press Start 2P.

import colorsys as _colorsys
import random as _random
import sys as _sys
from pathlib import Path as _Path

FONTS_DIR = _Path(getattr(_sys, "_MEIPASS", _Path(__file__).resolve().parent.parent)) / "resources" / "fonts"


def bundled_font(name: str, size: int, variation: str | None = None) -> ImageFont.ImageFont:
    path = FONTS_DIR / name
    try:
        f = ImageFont.truetype(str(path), size)
        if variation:
            try:
                f.set_variation_by_name(variation)
            except (OSError, ValueError):
                pass
        return f
    except OSError:
        return font("segoeuib.ttf", size)  # fallback if a font file is missing


def _lum(c: RGB) -> float:
    """WCAG relative luminance."""
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _hsv(c: RGB) -> tuple[float, float, float]:
    return _colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)


def _from_hsv(h: float, s: float, v: float) -> RGB:
    r, g, b = _colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return round(r * 255), round(g * 255), round(b * 255)


def _hex(c: RGB) -> str:
    return "#%02X%02X%02X" % c


def _tile_text(img: Image.Image, text: str, fnt, center: tuple[float, float], fill) -> Image.Image:
    """Mask of `text` with its glyph box centred on `center` (like CSS text-box-trim)."""
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    l, t, r, b = d.textbbox((0, 0), text, font=fnt)
    d.text((center[0] - (l + r) / 2, center[1] - (t + b) / 2), text, font=fnt, fill=255)
    if fill is not None:
        img.paste(fill, mask=mask)
    return mask


def _blur_paste(img: Image.Image, mask: Image.Image, color: RGB, radius: float, alpha: float) -> None:
    soft = mask.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: int(v * alpha))
    img.paste(color, mask=soft)


# 07 · Swiss Brutal: flat colour per digit, oversized grotesque bleeding off the edge,
# number label and a dot in the corner.
SWISS_TILES = ["#FF3B1F", "#0047FF", "#FFD400", "#00A86B", "#FF6FB5",
               "#111111", "#F2EFE6", "#7B2FF7", "#FF8A00", "#00C2D1"]


def _draw_swiss(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    u = w / 200
    dark, light = role(theme, "dark"), role(theme, "light")
    d = ImageDraw.Draw(img)
    if ch == ":":
        if theme.get("_light"):
            # one colour for every tile: the colon is their negative
            # (e.g. red tiles with black digits -> black colon with red squares)
            tile = parse_hex(theme["_light"])
            back = dark if _lum(tile) > 0.33 else light
            accent = tile
            if max(tile) < 24:  # black cover: the whole face stays black, white squares
                back, accent = tile, light
        else:
            back, accent = dark, role(theme, "accent")
        img.paste(back, (0, 0, w, h))
        ink = accent
        if not lit:
            accent = mix(back, accent, 0.3)
        for y in (56, 114):
            d.rectangle((88 * u, y * u, 112 * u, (y + 24) * u), fill=accent)
    else:
        bg = role(theme, f"t{ch}")
        img.paste(bg, (0, 0, w, h))
        ink = dark if _lum(bg) > 0.33 else light  # same rule the design follows
        if not lit:
            ink = mix(bg, ink, 0.3)
        _tile_text(img, ch, bundled_font("ArchivoBlack-Regular.ttf", int(250 * u)), (134 * u, 130 * u), ink)
    d.text((14 * u, 12 * u), f"N°{ch}", font=bundled_font("SpaceMono-Bold.ttf", max(6, int(15 * u))), fill=ink)
    if ch != ":":
        d.ellipse((170 * u, 14 * u, 186 * u, 30 * u), fill=ink)


# 04 · Glassmorphism: frosted glass over coloured blobs; every digit has its own
# palette (the base palette rotated round the colour wheel) and blob layout.

def _glass_palette(theme: dict, ch: str) -> list[RGB]:
    # Layout varies by digit; user-selected hues must never rotate.
    return [role(theme, "b1"), role(theme, "b2"), role(theme, "b3")]


def _draw_glass(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    u = w / 200
    bg = Image.new("RGB", img.size)
    bg.paste(_vertical_gradient(img.size, role(theme, "bg"), role(theme, "bg2")))
    rnd = _random.Random(f"glass-{ch}")  # stable blob layout per digit
    blobs = Image.new("RGB", img.size, (0, 0, 0))
    mask = Image.new("L", img.size, 0)
    for color in _glass_palette(theme, ch):
        size = rnd.uniform(130, 175) * u
        x, y = rnd.uniform(-30, 120) * u, rnd.uniform(-30, 120) * u
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).ellipse((x, y, x + size, y + size), fill=255)
        blobs.paste(color, mask=m)
        mask = ImageChops.lighter(mask, m)
    blobs = blobs.filter(ImageFilter.GaussianBlur(26 * u))
    mask = mask.filter(ImageFilter.GaussianBlur(26 * u))
    bg.paste(blobs, mask=mask)
    card = Image.new("L", img.size, 0)
    ImageDraw.Draw(card).rounded_rectangle((20 * u, 20 * u, 180 * u, 180 * u), radius=36 * u, fill=255)
    _blur_paste(bg, _offset(card, 0, 10 * u), (0, 0, 0), 12 * u, 0.25)        # drop shadow
    frosted = bg.filter(ImageFilter.GaussianBlur(11 * u))                    # backdrop blur
    bg.paste(frosted, mask=card)
    sheen = Image.linear_gradient("L").rotate(45, expand=False).resize(img.size)
    sheen = ImageChops.multiply(sheen.point(lambda v: int(15 + v * 0.18)), card)   # 24% -> 6% white
    bg.paste((255, 255, 255), mask=sheen)
    edge = ImageChops.subtract(card, card.filter(ImageFilter.MinFilter(3)))
    bg.paste((255, 255, 255), mask=edge.point(lambda v: int(v * 0.45)))
    fnt = bundled_font("Unbounded-Variable.ttf", int(92 * u), "Medium")
    digit = role(theme, "digit") if lit else mix(role(theme, "bg"), role(theme, "digit"), 0.35)
    shadow = _tile_text(bg, ch, fnt, (100 * u, 104 * u), None)
    _blur_paste(bg, shadow, (0, 0, 0), 6 * u, 0.18)
    _tile_text(bg, ch, fnt, (100 * u, 100 * u), digit)
    img.paste(bg)


# 08 · CRT Terminal: green phosphor in a rounded screen: VT323, scanlines, vignette.

def _draw_crt(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int, compact_text=None, separator_lit=True) -> None:
    w, h = img.size
    u = w / 200
    case = role(theme, "case")
    img.paste(_vertical_gradient(img.size, case, mix(case, (0, 0, 0), 0.5)))
    screen_box = (10 * u, 10 * u, 190 * u, 190 * u)
    screen_mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(screen_mask).rounded_rectangle(screen_box, radius=30 * u, fill=255)
    glass = role(theme, "screen")
    radial = Image.radial_gradient("L").resize((int(180 * u), int(180 * u)))
    screen = Image.new("RGB", img.size, glass)
    edge = mix(glass, (0, 0, 0), 0.75)
    shade = Image.new("RGB", radial.size, edge)
    screen.paste(shade, (int(10 * u), int(10 * u)), mask=radial)
    phosphor = role(theme, "phosphor") if lit else mix(glass, role(theme, "phosphor"), 0.15)
    if compact_text is None:
        ImageDraw.Draw(screen).text((26*u,16*u), ">", font=bundled_font("VT323-Regular.ttf",int(30*u)),fill=mix(glass,phosphor,.5))
        m = _tile_text(screen,ch,bundled_font("VT323-Regular.ttf",int(210*u)),(100*u,100*u),None)
    else:
        m = Image.new("L",img.size,0)
        for value, center in zip(compact_text, ((100*u,59*u),(100*u,141*u))):
            glyph = _tile_text(screen,value,bundled_font("VT323-Regular.ttf",int(90*u)),center,None)
            m = ImageChops.lighter(m,glyph)
        if separator_lit:
            ImageDraw.Draw(m).line((88*u,100*u,112*u,100*u),fill=255,width=max(1,int(u)))
    _blur_paste(screen, m, phosphor, 14 * u, 0.45)
    _blur_paste(screen, m, phosphor, 4 * u, 0.85)
    screen.paste(phosphor, mask=m)
    lines = Image.new("L", img.size, 0)
    ld = ImageDraw.Draw(lines)
    y = 11 * u
    while y < 190 * u:  # 2-u scanlines every 4 u, 28 % black
        ld.rectangle((0, y, w, y + max(0.0, 2 * u - 1)), fill=int(255 * 0.28))  # never inverted on tiny tiles
        y += 4 * u
    screen.paste((0, 0, 0), mask=lines)
    vig = Image.radial_gradient("L").resize((int(180 * u), int(180 * u))).point(
        lambda v: 0 if v < 128 else int((v - 128) / 127 * 255 * 0.75))
    vmask = Image.new("L", img.size, 0)
    vmask.paste(vig, (int(10 * u), int(10 * u)))
    screen.paste((0, 0, 0), mask=vmask)
    refl = Image.new("L", img.size, 0)
    ImageDraw.Draw(refl).rounded_rectangle((28 * u, 24 * u, 118 * u, 64 * u), radius=20 * u, fill=16)
    screen.paste((255, 255, 255), mask=refl.filter(ImageFilter.GaussianBlur(3 * u)))
    inner = ImageChops.subtract(screen_mask, screen_mask.filter(ImageFilter.GaussianBlur(5 * u)))
    screen.paste((0, 0, 0), mask=inner.point(lambda v: min(255, v * 3)))
    img.paste(screen, mask=screen_mask)


# 09 · Editorial Serif: italic antiqua on cream paper, hairline rules, number and the
# digit spelled out as a word.
SERIF_WORDS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]


def _draw_serif(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    u = w / 200
    paper, ink, rule, accent, note = (role(theme, k) for k in ("paper", "ink", "rule", "accent", "note"))
    img.paste(paper, (0, 0, w, h))
    d = ImageDraw.Draw(img)
    hair = max(1, int(1.2 * u))
    d.line((12 * u, 14 * u, 188 * u, 14 * u), fill=ink, width=hair)
    small = font("segoeui.ttf", max(5, int(9 * u)))  # has Cyrillic for the spelled-out words
    d.text((12 * u, 20 * u), "— · —" if ch == ":" else f"N° 0{ch}", font=small, fill=note)
    label = "MMXXVI"
    tw = d.textlength(label, font=small)
    d.text((188 * u - tw, 20 * u), label, font=small, fill=note)
    d.line((12 * u, 184 * u, 188 * u, 184 * u), fill=rule, width=hair)
    dot = accent if lit else mix(paper, accent, 0.3)
    if ch == ":":
        for y in (79, 127):
            r = 6.5 * u
            d.ellipse((100 * u - r, y * u - r, 100 * u + r, y * u + r), fill=dot)
        return
    _tile_text(img, ch, bundled_font("InstrumentSerif-Italic.ttf", int(170 * u)), (100 * u, 100 * u),
               ink if lit else mix(paper, ink, 0.3))
    d.text((12 * u, 166 * u), SERIF_WORDS[int(ch)], font=small, fill=note)
    r = 3.5 * u
    d.ellipse((180 * u - r, 172 * u - r, 180 * u + r, 172 * u + r), fill=dot)


# 10 · Game Boy: four greens of the DMG screen, pixel font with a hard shadow and a
# "health" bar that fills with the digit's value.

def _draw_gameboy(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w, h = img.size
    u = w / 200
    lightest, light, dark, darkest = (role(theme, k) for k in ("lightest", "light", "dark", "darkest"))
    img.paste(lightest, (0, 0, w, h))
    d = ImageDraw.Draw(img)
    stroke = max(2, int(5 * u))
    d.rectangle((12 * u, 12 * u, 188 * u, 188 * u), outline=darkest, width=stroke)
    for x, y in ((12, 12), (183, 12), (12, 183), (183, 183)):  # notched pixel corners
        d.rectangle((x * u, y * u, (x + 5) * u, (y + 5) * u), fill=lightest)
    fnt = bundled_font("PressStart2P-Regular.ttf", int(84 * u))
    ink = darkest if lit else mix(lightest, darkest, 0.3)
    if ch != ":":  # the design's colon has no shadow
        _tile_text(img, ch, fnt, (107 * u, 92 * u), dark)    # hard shadow
    _tile_text(img, ch, fnt, (100 * u, 85 * u), ink)
    if ch == ":":
        return
    value = int(ch)
    seg, gap, x0, y0 = 14 * u, 2.5 * u, 26 * u, 158 * u
    for i in range(9):
        x = x0 + i * (seg + gap)
        d.rectangle((x, y0, x + seg, y0 + 7 * u), fill=darkest if i < value else light)


# ---- colour roles of the Figma styles and "colour from the light" -------------------

STYLE_ROLES.update({
    "swiss": [(f"t{i}", f"Фон «{i}»", c) for i, c in enumerate(SWISS_TILES)]
             + [("dark", "Тёмные цифры", "#111111"), ("light", "Светлые цифры", "#F2EFE6"),
                ("accent", "Двоеточие", "#FF3B1F")],
    "glass": [("bg", "Фон", "#0E0F22"), ("bg2", "Фон (низ)", "#1B1237"), ("digit", "Цифры", "#FFFFFF"),
              ("b1", "Пятно 1", "#E8343A"), ("b2", "Пятно 2", "#2BD46A"), ("b3", "Пятно 3", "#2F6FE0")],
    "crt": [("phosphor", "Люминофор", "#7CFFA6"), ("screen", "Экран", "#0C4020"), ("case", "Корпус", "#24241C")],
    "serif": [("paper", "Бумага", "#F3EEE3"), ("ink", "Цифры", "#1C1A17"), ("accent", "Акцент", "#C0532F"),
              ("note", "Подписи", "#776C64"), ("rule", "Линейки", "#C3BFB5")],
    "gameboy": [("lightest", "Экран", "#9BBC0F"), ("light", "Пустая полоска", "#8BAC0F"),
                ("dark", "Тень", "#306230"), ("darkest", "Цифры", "#0F380F")],
})
THEME_DRAWERS.update({"swiss": _draw_swiss, "glass": _draw_glass, "crt": _draw_crt,
                      "serif": _draw_serif, "gameboy": _draw_gameboy})
SQUARE_STYLES = {"swiss", "glass", "crt", "serif", "gameboy"}  # laid out on a square tile


def _tints(c: RGB, n: int) -> list[RGB]:
    hh, ss, vv = _hsv(c)
    return [_from_hsv(hh + (i - (n - 1) / 2) * 0.06, ss * (0.75 + 0.1 * i), min(1, vv * (0.9 + 0.05 * i)))
            for i in range(n)]


# Black or white light (a black/white cover): hue-based palettes would turn red, so
# these styles get greys instead. A black light makes a dark face with light digits.
GREY_LIGHT = {
    "glass": {True: ("#3A3A3E", "#2A2A2E", "#4A4A50"), False: ("#E6E6EA", "#C8C8CE", "#F4F4F6")},
    "gameboy": {True: ("#1A1A1A", "#333333", "#4D4D4D", "#F0F0F0"),
                False: ("#E8E8E8", "#C8C8C8", "#8A8A8A", "#202020")},
}


def apply_light(theme: dict, light_hex: str) -> dict:
    """Theme copy whose main colour follows the light (and so the cover while music plays)."""
    L = parse_hex(light_hex)
    style = theme.get("style", "")
    t = dict(theme, _light=light_hex)
    if max(L) - min(L) < 24 and style in GREY_LIGHT:
        names = ("b1", "b2", "b3") if style == "glass" else ("lightest", "light", "dark", "darkest")
        t.update(zip(names, GREY_LIGHT[style][_lum(L) < 0.2]))
        return t
    if style == "soft":
        ink = (20,20,20) if _lum(L) > .33 else (245,245,245)
        t.update(bg="#000000",shape=_hex(L),digit=_hex(ink))
    elif style == "swiss":
        t.update({f"t{i}": _hex(L) for i in range(10)})
    elif style == "glass":
        t.update(dict(zip(("b1", "b2", "b3"), (_hex(c) for c in _tints(L, 3)))))
    elif style == "crt":
        t.update(phosphor="#FFFFFF" if max(L) < 24 else _hex(L), screen=_hex(mix((0,0,0), L, 0.16)),
                 case=_hex(mix((0,0,0), L, 0.06)))
    elif style == "serif":
        ink = (20,20,20) if _lum(L) > 0.33 else (245,245,245)
        t.update(paper=_hex(L), ink=_hex(ink), accent=_hex(ink),
                 note=_hex(mix(L, ink, .75)), rule=_hex(mix(L, ink, .45)))
    elif style == "gameboy":
        hh = _hsv(L)[0]
        t.update(lightest=_hex(_from_hsv(hh, 0.9, 0.74)), light=_hex(_from_hsv(hh, 0.9, 0.66)),
                 dark=_hex(_from_hsv(hh, 0.5, 0.38)), darkest=_hex(_from_hsv(hh, 0.73, 0.22)))
    elif style == "material":
        t.update(dict(zip(("s1", "s2", "s3", "s4"), (_hex(mix(c, (255, 255, 255), 0.45)) for c in _tints(L, 4)))))
    elif style == "widget":
        t["bg"] = _hex(L)
    elif style in ("custom",):
        pass
    else:
        t["color"] = _hex(L)
    return t


FIGMA_THEMES = [
    {"name": "Glassmorphism", "style": "glass", "bg": "#0E0F22", "bg2": "#1B1237", "digit": "#FFFFFF",
     "b1": "#E8343A", "b2": "#2BD46A", "b3": "#2F6FE0"},
    {"name": "Swiss Brutal", "style": "swiss", "dark": "#111111", "light": "#F2EFE6", "accent": "#FF3B1F",
     **{f"t{i}": c for i, c in enumerate(SWISS_TILES)}},
    {"name": "CRT Terminal", "style": "crt", "phosphor": "#7CFFA6", "screen": "#0C4020", "case": "#24241C"},
    {"name": "Editorial Serif", "style": "serif", "paper": "#F3EEE3", "ink": "#1C1A17", "accent": "#C0532F",
     "note": "#776C64", "rule": "#C3BFB5"},
    {"name": "Game Boy", "style": "gameboy", "lightest": "#9BBC0F", "light": "#8BAC0F", "dark": "#306230",
     "darkest": "#0F380F"},
]
STYLES.update({"glass": "Glassmorphism", "swiss": "Swiss Brutal", "crt": "CRT Terminal",
               "serif": "Editorial Serif", "gameboy": "Game Boy"})
STYLES["custom"] = STYLES.pop("custom")  # keep "Свои картинки" last
DEFAULT_THEMES[-1:-1] = FIGMA_THEMES
THEME_ADDITIONS[5] = FIGMA_THEMES
THEMES_VERSION = 5


# ---- built-in set (themes version 6) ---------------------------------------------
# Only the five Figma faces are offered; the older stock styles stay drawable
# (for imported packs / old configs) but are hidden from the style list.
ALL_BUILTIN_THEMES = [dict(t) for t in DEFAULT_THEMES]
KEEP_STYLES = ("glass", "swiss", "crt", "serif", "gameboy")
DEFAULT_THEMES[:] = [dict(t) for t in FIGMA_THEMES]
_visible = {k: STYLES[k] for k in (*KEEP_STYLES, "custom")}
STYLES.clear()
STYLES.update(_visible)
THEMES_VERSION = 6

# Colour roles replaced by apply_light() for each style; the editor hides them
# while the face follows the light (they would have no effect).
LIGHT_ROLES = {
    "swiss": {f"t{i}" for i in range(10)} | {"accent"},
    "glass": {"b1", "b2", "b3"},
    "crt": {"phosphor", "screen", "case"},
    "serif": {"paper", "ink", "accent", "note", "rule"},
    "gameboy": {"lightest", "light", "dark", "darkest"},
}
FOLLOW_LIGHT_STYLES = set(LIGHT_ROLES)  # "custom" packs are pictures: nothing to recolour


def editable_roles(theme: dict) -> list[tuple[str, str, str]]:
    """Colour pickers worth showing for this theme right now."""
    style = theme.get("style", "")
    if style == "custom":
        return [("bg", "Фон пустых экранов", "#000000")]
    hidden = LIGHT_ROLES.get(style, set()) if theme.get("follow_light") else set()
    return [r for r in style_roles(style) if r[0] not in hidden]


# Soft Forms, times-gate reference supplied by the author. Native masks remain
# recolourable at every resolution; Outfit Bold is bundled under SIL OFL 1.1.
def soft_form_mask(size: tuple[int, int], ch: str) -> Image.Image:
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if ch in "0369":
        draw.ellipse((0, 0, w-1, h-1), fill=255)
        return mask
    radii = (.5, .125, .5, .125) if ch in "147:" else (.25, .25, .25, .25)
    a,b,c,d = [int(min(w,h)*r) for r in radii]
    right, bottom = w-1, h-1
    draw.polygon([(a,0),(right-b,0),(right,b),(right,bottom-c),
                  (right-c,bottom),(d,bottom),(0,bottom-d),(0,a)], fill=255)
    for radius, box, start in ((a,(0,0,2*a,2*a),180),
                                (b,(right-2*b,0,right,2*b),270),
                                (c,(right-2*c,bottom-2*c,right,bottom),0),
                                (d,(0,bottom-2*d,2*d,bottom),90)):
        if radius:
            draw.pieslice(box,start,start+90,fill=255)
    return mask


def _draw_soft_forms(img: Image.Image, ch: str, theme: dict, lit: bool, pos: int) -> None:
    w,h = img.size
    img.paste((0,0,0),(0,0,w,h))
    shape, ink = role(theme,"shape"), role(theme,"digit")
    img.paste(shape,mask=soft_form_mask(img.size,ch))
    if not lit:
        ink = mix(shape,ink,.18)
    if ch == ":":
        draw=ImageDraw.Draw(img)
        radius=w*.075
        for y in (.50,.76):
            draw.ellipse((w*.5-radius,h*y-radius,w*.5+radius,h*y+radius),fill=ink)
    else:
        _tile_text(img,ch,bundled_font("Outfit-Variable.ttf",int(w*.85),"Bold"),
                   (w*.5,h*.52),ink)


SOFT_FORMS_THEME = {"name":"Material Expressive","style":"soft","bg":"#000000",
                    "shape":"#C8D9B9","digit":"#203B2D"}
STYLE_ROLES["soft"] = [("shape","Фигуры","#C8D9B9"),
                       ("digit","Цифры и двоеточие","#203B2D")]
THEME_DRAWERS["soft"] = _draw_soft_forms
SQUARE_STYLES.add("soft")
CANVAS_ROLE["soft"] = "bg"
KEEP_STYLES = (*KEEP_STYLES,"soft")
_custom_label = STYLES.pop("custom")
STYLES["soft"] = "Material Expressive"
STYLES["custom"] = _custom_label
FIGMA_THEMES.append(dict(SOFT_FORMS_THEME))
DEFAULT_THEMES.append(dict(SOFT_FORMS_THEME))
THEMES_VERSION = 7
THEME_ADDITIONS[7] = [dict(SOFT_FORMS_THEME)]
LIGHT_ROLES["soft"] = {"bg","shape","digit"}
FOLLOW_LIGHT_STYLES.add("soft")
