"""Divoom 16x16 animation file format ("divoom16") — what command 0x8B uploads.

Ditoo Pro image format:
  Purpose:  pixel data container for the 16x16 display.
  Format (one frame, repeated for animations):
      0xAA | frame length LE16 | delay ms LE16 | reuse palette (0/1) | color count |
      palette: color count x (R, G, B) |
      pixels: 256 palette indices, row-major, each `bpp` bits wide,
              packed LSB-first into bytes; bpp = ceil(log2(palette size))
      frame length = 7 + 3 * color count + len(pixels)
      color count 0 is read as 256 by the device; we cap palettes at 256.
  Source:
      andreas-mausch/divoom-ditoo-pro-controller  src/divoom_file_format/frame.rs, frame_header.rs
      futpib/divoom-ditoo-pro-controller           Animation::from_image (static image: delay 0)
  Status: format reproduced from the reference implementation; round trip
  covered by tests/test_divoom16.py. Display on hardware: NOT VERIFIED yet.
"""

from __future__ import annotations

import struct

from PIL import Image

SIZE = 16
MAGIC = 0xAA
MAX_COLORS = 256

RGB = tuple[int, int, int]


def bits_per_pixel(color_count: int) -> int:
    # A one-colour palette would need 0 bits per pixel. The reference encoder
    # emits that, but whether the firmware accepts it is unknown, so we never
    # produce it (see encode_frame).
    return max(1, (color_count - 1).bit_length())


def encode_frame(image: Image.Image, delay_ms: int = 0) -> bytes:
    img = image.convert("RGB")
    if img.size != (SIZE, SIZE):
        raise ValueError(f"expected a {SIZE}x{SIZE} image, got {img.size}")

    pixels: list[RGB] = list(img.get_flattened_data())
    palette: list[RGB] = list(dict.fromkeys(pixels))  # first-appearance order
    if len(palette) > MAX_COLORS:
        raise ValueError(f"{len(palette)} colours; quantize to <= {MAX_COLORS} first")
    if len(palette) == 1:
        palette.append((0, 0, 0) if palette[0] != (0, 0, 0) else (255, 255, 255))

    index = {color: i for i, color in enumerate(palette)}
    bpp = bits_per_pixel(len(palette))
    packed = 0
    for i, color in enumerate(pixels):
        packed |= index[color] << (i * bpp)
    pixel_bytes = packed.to_bytes((SIZE * SIZE * bpp + 7) // 8, "little")

    palette_bytes = b"".join(bytes(c) for c in palette)
    length = 7 + len(palette_bytes) + len(pixel_bytes)
    header = struct.pack("<BHHBB", MAGIC, length, delay_ms, 0, len(palette) % 256)
    return header + palette_bytes + pixel_bytes


def encode_image(image: Image.Image) -> bytes:
    """A static picture is a one-frame animation with delay 0."""
    return encode_frame(image, delay_ms=0)


def decode(data: bytes) -> list[tuple[Image.Image, int]]:
    """Decode a divoom16 stream into (image, delay_ms) frames. Used by tests/debug."""
    frames: list[tuple[Image.Image, int]] = []
    palette: list[RGB] = []
    pos = 0
    while pos < len(data):
        magic, length, delay, reuse, count = struct.unpack_from("<BHHBB", data, pos)
        if magic != MAGIC:
            raise ValueError(f"bad frame magic 0x{magic:02X} at offset {pos}")
        p = pos + 7
        local = [tuple(data[p + 3 * i : p + 3 * i + 3]) for i in range(count)]
        palette = (palette + local) if reuse else local
        if not reuse and count == 0:
            raise ValueError("256-colour frames (count byte 0) are not decoded here")
        bpp = bits_per_pixel(len(palette))
        p += 3 * count
        nbytes = (SIZE * SIZE * bpp + 7) // 8
        packed = int.from_bytes(data[p : p + nbytes], "little")
        mask = (1 << bpp) - 1
        img = Image.new("RGB", (SIZE, SIZE))
        img.putdata([palette[(packed >> (i * bpp)) & mask] for i in range(SIZE * SIZE)])
        frames.append((img, delay))
        pos += length
    return frames
