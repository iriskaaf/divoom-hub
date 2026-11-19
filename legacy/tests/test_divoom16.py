import struct

import pytest
from PIL import Image

from bluetooth import divoom16
from core import artwork


def test_test_pattern_round_trip():
    img = artwork.test_pattern()
    data = divoom16.encode_image(img)
    magic, length, delay, reuse, count = struct.unpack_from("<BHHBB", data)
    assert (magic, delay, reuse, count) == (0xAA, 0, 0, 5)
    # 5 colours -> 3 bits per pixel -> 96 bytes of pixel data
    assert length == len(data) == 7 + 5 * 3 + 96
    [(decoded, _)] = divoom16.decode(data)
    assert list(decoded.get_flattened_data()) == list(img.get_flattened_data())


def test_palette_is_first_appearance_order_and_bits_are_lsb_first():
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    img.putpixel((1, 0), (255, 0, 0))
    data = divoom16.encode_image(img)
    assert data[7:13] == bytes([0, 0, 0, 255, 0, 0])
    # 1 bpp: pixel 1 is colour 1 -> bit 1 of the first pixel byte
    assert data[13] == 0b0000_0010


def test_single_colour_image_never_uses_zero_bits():
    data = divoom16.encode_image(Image.new("RGB", (16, 16), (10, 20, 30)))
    assert data[6] == 2
    [(decoded, _)] = divoom16.decode(data)
    assert set(decoded.get_flattened_data()) == {(10, 20, 30)}


def test_256_colours():
    img = Image.new("RGB", (16, 16))
    img.putdata([(i, 255 - i, i // 2) for i in range(256)])
    data = divoom16.encode_image(img)
    assert data[6] == 0  # count byte wraps: 0 means 256
    assert len(data) == 7 + 256 * 3 + 256


def test_rejects_wrong_size():
    with pytest.raises(ValueError):
        divoom16.encode_image(Image.new("RGB", (32, 32)))


def test_to_ditoo_crops_instead_of_stretching():
    wide = Image.new("RGB", (300, 100), (0, 0, 255))
    wide.paste((255, 0, 0), (100, 0, 200, 100))  # red centre square
    out = artwork.to_ditoo(wide, contrast=1, saturation=1, brightness=1)
    assert out.size == (16, 16)
    r, g, b = out.getpixel((8, 8))
    assert r > 200 and b < 50


def test_limit_colors():
    img = artwork.diagnostic_pattern(256)
    assert len(set(artwork.limit_colors(img, 64).get_flattened_data())) <= 64
    assert artwork.limit_colors(img, 256) is img


@pytest.mark.parametrize("n", [8, 100, 129, 178, 255, 256])
def test_diagnostic_pattern_has_exact_palette_and_round_trips(n):
    img = artwork.diagnostic_pattern(n)
    assert len(set(img.get_flattened_data())) == n
    [(decoded, _)] = divoom16.decode(divoom16.encode_image(img)) if n < 256 else [(img, 0)]
    assert list(decoded.get_flattened_data()) == list(img.get_flattened_data())
