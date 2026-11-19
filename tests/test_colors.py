from PIL import Image, ImageDraw

from core import colors

RAINBOW = {1: (255, 0, 0), 2: (255, 128, 0), 3: (255, 255, 0), 4: (0, 255, 0),
           5: (0, 255, 255), 6: (0, 0, 255), 7: (160, 0, 255), 8: (255, 255, 255)}


def hue_deg(c):
    return colors.to_hsv(c)[0] * 360


def test_dark_cover_with_big_blue_area_gives_blue():
    img = Image.new("RGB", (300, 300), (8, 8, 10))
    ImageDraw.Draw(img).ellipse((60, 60, 240, 240), fill=(30, 60, 200))
    accent = colors.accent_color(img)
    assert 200 < hue_deg(accent) < 250
    assert colors.to_hsv(accent)[2] >= 0.8  # lifted, visible on LEDs


def test_black_cover_gives_black_even_with_noise_and_a_tiny_logo():
    import random
    rnd = random.Random(1)
    img = Image.new("RGB", (300, 300))
    img.putdata([(rnd.randint(0, 40), rnd.randint(0, 25), rnd.randint(0, 45)) for _ in range(300 * 300)])
    ImageDraw.Draw(img).ellipse((140, 140, 170, 170), fill=(220, 30, 30))   # ~1 % red logo
    assert colors.accent_color(img) == colors.BLACK


def test_small_coloured_subject_on_a_grey_cover_gives_its_colour():
    img = Image.new("RGB", (300, 300), (70, 70, 74))                    # grey street
    ImageDraw.Draw(img).ellipse((40, 130, 140, 230), fill=(210, 20, 30))  # red car, ~10 %
    accent = colors.accent_color(img)
    assert (hue_deg(accent) < 15 or hue_deg(accent) > 345) and colors.to_hsv(accent)[1] > 0.6
    black = Image.new("RGB", (300, 300), (5, 5, 8))
    ImageDraw.Draw(black).ellipse((100, 100, 200, 200), fill=(110, 40, 200))  # violet circle
    assert 250 < hue_deg(colors.accent_color(black)) < 280


def test_white_and_beige_covers_give_white():
    assert colors.accent_color(Image.new("RGB", (100, 100), (250, 250, 248))) == colors.WHITE
    assert colors.accent_color(Image.new("RGB", (100, 100), (235, 225, 205))) == colors.WHITE


def test_dull_red_keeps_its_saturation():
    accent = colors.accent_color(Image.new("RGB", (100, 100), (120, 60, 55)))
    h, s, v = colors.to_hsv(accent)
    original_h, original_s, _ = colors.to_hsv((120, 60, 55))
    assert abs(h - original_h) < 0.01 and abs(s - original_s) < 0.01
    assert v >= 0.79


def test_greyscale_cover_follows_the_bigger_part():
    img = Image.new("RGB", (100, 100), (40, 40, 40))
    ImageDraw.Draw(img).rectangle((0, 0, 70, 100), fill=(200, 200, 200))
    assert colors.accent_color(img) == colors.WHITE
    img = Image.new("RGB", (100, 100), (40, 40, 40))
    ImageDraw.Draw(img).rectangle((0, 0, 30, 100), fill=(200, 200, 200))
    assert colors.accent_color(img) == colors.BLACK


def test_larger_vivid_area_wins():
    img = Image.new("RGB", (100, 100), (0, 180, 0))
    ImageDraw.Draw(img).rectangle((0, 0, 20, 20), fill=(220, 0, 0))
    assert 90 < hue_deg(colors.accent_color(img)) < 150


def test_nearest_effect():
    assert colors.nearest_effect((230, 20, 30), RAINBOW) == 1
    assert colors.nearest_effect((20, 40, 230), RAINBOW) == 6
    assert colors.nearest_effect((250, 250, 250), RAINBOW) == 8
    assert colors.nearest_effect((255, 140, 20), RAINBOW) == 2
    assert colors.nearest_effect((1, 2, 3), {}) is None


def test_hex_round_trip():
    assert colors.parse_hex(colors.hex_color((167, 59, 219))) == (167, 59, 219)
