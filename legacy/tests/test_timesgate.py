import base64
import datetime as dt
import io

import pytest
from PIL import Image

from core.settings import Settings
from timesgate import digits
from timesgate.client import TimesGateAuthError, TimesGateClient
from timesgate.engine import TimesGateEngine


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, reply=None):
        self.posts = []
        self.reply = reply or {"error_code": 0}

    def post(self, url, json, timeout):
        self.posts.append((url, json))
        return FakeResponse(self.reply)


def test_every_request_carries_token_and_uses_post_endpoint():
    s = FakeSession()
    TimesGateClient("192.168.1.50", "229930", session=s).set_brightness(150)
    url, body = s.posts[0]
    assert url == "http://192.168.1.50/post"
    assert body == {"Command": "Channel/SetBrightness", "Brightness": 100, "LocalToken": 229930}


def test_hardware_402_endpoint():
    assert TimesGateClient("1.2.3.4", 1, hardware=402).url == "http://1.2.3.4:9000/divoom_api"


def test_wrong_token_raises_auth_error():
    s = FakeSession({"error_code": "DeviceToken is err"})
    with pytest.raises(TimesGateAuthError):
        TimesGateClient("1.2.3.4", 1, session=s).get_config()


def test_send_frames_is_jpeg_with_one_hot_lcd_and_shared_increasing_pic_id():
    s = FakeSession()
    c = TimesGateClient("1.2.3.4", 1, session=s)
    frames = [Image.new("RGB", (128, 128), (255, 0, 0)), Image.new("RGB", (128, 128), (0, 0, 255))]
    c.send_frames(2, frames, 500)
    c.send_frames(4, frames[:1])
    bodies = [b for _, b in s.posts]
    assert [b["LcdArray"] for b in bodies] == [[0, 0, 1, 0, 0]] * 2 + [[0, 0, 0, 0, 1]]
    assert [b["PicID"] for b in bodies] == [1, 1, 2]
    assert [(b["PicNum"], b["PicOffset"]) for b in bodies] == [(2, 0), (2, 1), (1, 0)]
    jpeg = base64.b64decode(bodies[0]["PicData"])
    assert Image.open(io.BytesIO(jpeg)).format == "JPEG"


def test_light_list_index_follows_zone():
    s = FakeSession()
    c = TimesGateClient("1.2.3.4", 1, session=s)
    c.set_light(on=True, brightness=50, color="#00FF00", zone=2, effect=5,
                color_cycle=False, key_light=True)
    body = s.posts[0][1]
    assert body["OnOff"] == 1 and body["SelectLightIndex"] == 2
    assert [x["SelectEffect"] for x in body["LightList"]] == [0, 0, 5]


# ---- engine -----------------------------------------------------------------

class FakeClient:
    instances = []

    def __init__(self, ip, token, hardware):
        self.sent = []
        self.calls = []
        FakeClient.instances.append(self)

    def get_config(self):
        self.calls.append("config")
        return {}

    def reset_pic_id(self):
        self.calls.append("reset")

    def set_brightness(self, v):
        self.calls.append(("brightness", v))

    def set_light(self, **kw):
        self.calls.append(("light", kw["effect"]))
        self.light_colors = getattr(self, "light_colors", []) + [kw["color"]]
        self.light_states = getattr(self, "light_states", []) + [kw]

    def send_frames(self, screen, frames, speed):
        self.sent.append(screen)

    def set_whole_face(self, clock_id):
        self.calls.append(("face", clock_id))

    def get_weather(self):
        self.calls.append("weather")
        return {"error_code": 0, "CurTemp": 18.4}


@pytest.fixture
def make_engine(monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, path=None: None)
    FakeClient.instances.clear()

    def make(now, **kw):
        s = Settings(tg_ip="10.0.0.5", tg_token="1", **kw)
        clock = {"now": now}
        e = TimesGateEngine(s, client_factory=FakeClient, clock=lambda: clock["now"])
        return e, clock
    return make


def test_first_tick_sends_all_then_only_changed_digits(make_engine):
    e, clock = make_engine(dt.datetime(2026, 10, 5, 12, 59))
    e._tick()
    client = FakeClient.instances[0]
    assert client.calls[:2] == ["config", "reset"]
    assert sorted(client.sent) == [0, 1, 2, 3, 4]
    client.sent.clear()
    clock["now"] = dt.datetime(2026, 10, 5, 13, 0)   # 12:59 -> 13:00: H2, M1, M2 change
    e._tick()
    assert sorted(client.sent) == [1, 3, 4]
    client.sent.clear()
    clock["now"] = dt.datetime(2026, 10, 5, 13, 1)
    e._tick()
    assert client.sent == [4]


def test_theme_switch_resends_everything_and_wraps(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    e._tick()
    client = FakeClient.instances[0]
    client.sent.clear()
    e.settings.tg_theme = 0
    assert e.switch_theme(-1) == digits.DEFAULT_THEMES[-1]["name"]
    e._tick()
    assert sorted(client.sent) == [0, 1, 2, 3, 4]
    assert e.switch_theme(name="swiss brutal") == "Swiss Brutal"


def test_off_mode_skips_screens_but_keeps_light_management(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0), tg_mode="off")
    e._tick()
    client = FakeClient.instances[0]
    assert client.sent == []
    assert ("light", 4) in client.calls
    e.settings.tg_manage_light = True
    e.apply_lights()
    e._tick()
    assert ("light", 4) in client.calls


def test_gifs_clock_puts_compact_clock_in_the_middle(make_engine, tmp_path):
    pic = tmp_path / "a.png"
    Image.new("RGB", (300, 300), (0, 255, 0)).save(pic)
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0), tg_mode="gifs_clock",
                       tg_side_media=[str(pic), "", "", str(pic)])
    preview = e.preview()
    assert preview[0].getpixel((64, 64)) == (0, 255, 0)
    assert preview[4].getpixel((64, 64)) == (0, 255, 0)
    assert preview[1].getpixel((64, 64)) == digits.canvas_bg(e.current_theme())  # empty slot
    assert preview[2].size == (128, 128)


def test_digit_styles_render_128():
    for style in digits.STYLES:
        theme = {"style": style, "color": "#FF0000", "bg": "#000000"}
        frames, speed = digits.char_frames(theme, ":", True, {})
        assert len(frames) == 2 and speed == digits.BLINK_MS
        assert all(f.size == (128, 128) for f in frames)


def test_center_cover_replaces_colon_while_playing(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    cover = {"value": None}
    e.cover_provider = lambda: cover["value"]
    e._tick()
    client = FakeClient.instances[0]
    client.sent.clear()
    cover["value"] = ("track1", Image.new("RGB", (300, 300), (10, 200, 30)))
    e._tick()
    assert client.sent == [2]                       # only the centre screen changes
    assert e.preview()[2].getpixel((64, 64)) == (10, 200, 30)
    client.sent.clear()
    cover["value"] = None                           # music stopped -> colon again
    e._tick()
    assert client.sent == [2]
    e.settings.tg_center_cover = False
    cover["value"] = ("track1", Image.new("RGB", (300, 300)))
    client.sent.clear()
    e._tick()
    assert client.sent == []


def test_render_cache_shares_frames_between_preview_and_upload(make_engine, monkeypatch):
    calls = []
    real = digits.char_frames
    monkeypatch.setattr(digits, "char_frames", lambda *a: calls.append(a[1]) or real(*a))
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    e.preview()
    e._tick()
    e.preview()
    assert sorted(calls) == ["0", "1", ":"]          # identical digits share one render


def test_device_mode_hands_screens_to_builtin_face_once(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    e._tick()
    client = FakeClient.instances[0]
    client.sent.clear()
    e.set_mode("device")
    e._tick()
    e._tick()
    assert client.calls.count(("face", 581)) == 1 and client.sent == []
    e.settings.tg_device_face = 697
    e._tick()
    assert ("face", 697) in client.calls
    e.switch_theme(+1)                       # picking a face returns to our clock
    assert e.settings.tg_mode == "clock"
    e._tick()
    assert sorted(client.sent) == [0, 1, 2, 3, 4]


def test_release_to_device_on_exit(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    e._tick()
    client = FakeClient.instances[0]
    e.release_to_device()
    assert ("face", 581) in client.calls
    client.calls.clear()
    e.settings.tg_device_face_on_exit = False
    e.release_to_device()
    assert client.calls == []


def test_pack_export_import_round_trip(tmp_path, monkeypatch):
    from timesgate import packs
    monkeypatch.setattr(packs, "PACKS_DIR", tmp_path / "packs")
    src = tmp_path / "seven.png"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(src)
    pack = packs.new_pack("Мой пак")
    packs.set_char(pack, "7", str(src))
    packs.set_char(pack, ":", str(src))
    assert pathlib_exists(pack["chars"]["7"]) and "packs" in pack["chars"]["7"]
    zip_path = tmp_path / "pack.zip"
    packs.export_pack(pack, str(zip_path))
    imported = packs.import_pack(str(zip_path))
    assert imported["name"] == "Мой пак" and set(imported["chars"]) == {"7", ":"}
    assert imported["id"] != pack["id"]
    frames, _ = digits.char_frames(imported, "7", False, imported["chars"])
    assert frames[0].getpixel((64, 64))[0] > 150
    packs.set_char(imported, "7", None)
    assert "7" not in imported["chars"]


def test_import_ignores_path_tricks(tmp_path, monkeypatch):
    import json
    import zipfile
    from timesgate import packs
    monkeypatch.setattr(packs, "PACKS_DIR", tmp_path / "packs")
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("../../evil.png", b"x")
        z.writestr("manifest.json", json.dumps({"format": 1, "name": "x", "chars": {"1": "../../evil.png"}}))
    theme = packs.import_pack(str(zp))
    stored = theme["chars"]["1"]
    assert str(tmp_path / "packs") in stored and not (tmp_path.parent / "evil.png").exists()


def pathlib_exists(p):
    import os
    return os.path.exists(p)


def theme_named(name):
    return dict(next(t for t in digits.ALL_BUILTIN_THEMES if t["name"] == name))


def test_material_digits_sit_on_position_colours():
    theme = theme_named("Material Expressive")
    a = digits.char_frames(theme, "8", False, {}, 0)[0][0]
    b = digits.char_frames(theme, "8", False, {}, 1)[0][0]
    corner = (30, 64)                                      # inside the shape, outside the digit
    assert a.getpixel(corner) != b.getpixel(corner)
    theme["s1"] = "#FF0000"
    red = digits.char_frames(theme, "8", False, {}, 0)[0][0].getpixel(corner)
    assert red[0] > 200 and red[1] < 60


def test_typo_effects_and_font_change_the_picture():
    theme = theme_named("Типографика")
    plain = digits.char_frames(theme, "5", False, {})[0][0]
    outline = digits.char_frames({**theme, "effect": "outline"}, "5", False, {})[0][0]
    other_font = digits.char_frames({**theme, "font": r"C:\Windows\Fonts\ariblk.ttf"}, "5", False, {})[0][0]
    assert plain.tobytes() != outline.tobytes() != other_font.tobytes()
    missing = digits.char_frames({**theme, "font": r"C:\nope.ttf"}, "5", False, {})[0][0]
    assert missing.tobytes() == plain.tobytes()          # unknown font -> default


def test_widget_face_uses_device_weather_and_side_slots(make_engine):
    e, clock = make_engine(dt.datetime(2026, 10, 5, 22, 6))
    e.settings.tg_themes = [theme_named("Виджет")]
    e.settings.tg_theme = 0
    e._tick()
    client = FakeClient.instances[0]
    assert "weather" in client.calls and e._weather == 18.4
    assert sorted(client.sent) == [0, 1, 2, 3, 4]
    client.sent.clear()
    clock["now"] = dt.datetime(2026, 10, 5, 22, 7)
    e._tick()
    assert client.sent == [2]                            # only the widget changes each minute
    frame = digits.widget_frame(theme_named("Виджет"), "22:06", 0, 26, 18.4)
    assert frame.size == (128, 128) and frame.getpixel((2, 2)) == digits.parse_hex("#2F7DF6")


def test_light_follows_cover_and_returns_to_own_colour(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    e.settings.tg_manage_light = True
    e.settings.tg_light_follow_cover = True
    e.settings.tg_light_color = "#112233"
    cover = {"value": None}
    e.cover_provider = lambda: cover["value"]
    e._tick()
    client = FakeClient.instances[0]
    assert client.light_colors[-1] == "#112233"
    cover["value"] = ("t1", Image.new("RGB", (100, 100), (20, 40, 220)))
    e._tick()
    r, g, b = digits.parse_hex(client.light_colors[-1])
    assert b > 200 and r < 100                           # blue cover -> blue light
    n = len(client.light_colors)
    e._tick()
    assert len(client.light_colors) == n                 # unchanged: not re-sent
    cover["value"] = None
    e._tick()
    assert client.light_colors[-1] == "#112233"


def test_pink_cover_uses_compatible_effect_without_changing_the_face(make_engine):
    engine, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    settings = engine.settings
    settings.tg_light_follow_cover = True
    settings.tg_light_zone = 0
    settings.tg_light_effect = 5
    engine.cover_provider = lambda: ("pink", Image.new("RGB", (64, 64), (255, 16, 105)))
    captured = []
    client = FakeClient("1.2.3.4", 1, 400)
    client.set_light = lambda **values: captured.append(values)
    engine._apply_device_settings(client)
    assert engine.cover_color() == "#FF1069"
    assert captured[-1]["color"] == "#FF107F"
    assert captured[-1]["effect"] == 9
    assert settings.tg_light_effect == 5
    engine.cover_provider = lambda: None
    engine._apply_device_settings(client)
    assert captured[-1]["effect"] == 5


@pytest.mark.parametrize("theme", digits.FIGMA_THEMES, ids=lambda t: t["style"])
def test_figma_styles_render_every_char_and_compact(theme):
    for i, ch in enumerate("0123456789:"):
        frames, _ = digits.char_frames(theme, ch, True, {}, i)
        assert all(f.size == (128, 128) for f in frames)
    frames, _ = digits.compact_clock_frames(theme, "21:47", True, {})
    assert frames[0].size == (128, 128)
    assert digits.theme_thumbnail(theme).size[1] == 40


def test_bundled_fonts_are_found():
    for name in ("ArchivoBlack-Regular.ttf", "SpaceMono-Bold.ttf", "Unbounded-Variable.ttf",
                 "VT323-Regular.ttf", "InstrumentSerif-Italic.ttf", "PressStart2P-Regular.ttf"):
        assert (digits.FONTS_DIR / name).exists(), name


def test_swiss_digit_ink_contrasts_with_tile():
    theme = theme_named("Swiss Brutal")
    yellow = digits.char_frames(theme, "2", False, {})[0][0]     # yellow tile -> dark digit
    blue = digits.char_frames(theme, "1", False, {})[0][0]       # blue tile -> light digit
    dark = digits.parse_hex("#111111")
    assert any(sum(abs(a - b) for a, b in zip(px, dark)) < 30 for px in yellow.get_flattened_data())
    light = digits.parse_hex("#F2EFE6")
    assert any(sum(abs(a - b) for a, b in zip(px, light)) < 30 for px in blue.get_flattened_data())


def test_swiss_follow_light_paints_every_tile_and_follows_cover(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 21, 47))
    e.settings.tg_face_follow_cover = True
    e.settings.tg_themes = [dict(theme_named("Swiss Brutal"), follow_light=True)]
    e.settings.tg_theme = 0
    e.settings.tg_light_color = "#00FF00"
    corner = (4, 120)
    e.cover_provider = lambda: ("green", Image.new("RGB", (64, 64), (0,255,0)))
    green = e.preview()
    assert all(img.getpixel(corner)[1] > 200 and img.getpixel(corner)[0] < 60 for i, img in enumerate(green) if i != 2)
    e.settings.tg_light_follow_cover = True
    e.cover_provider = lambda: ("t", Image.new("RGB", (64, 64), (220, 20, 20)))
    red = e.preview()
    assert red[0].getpixel(corner)[0] > 180 and red[0].getpixel(corner)[1] < 90
    e.cover_provider = lambda: ("t2", Image.new("RGB", (64, 64), (10, 10, 10)))   # black cover
    black = e.preview()
    assert max(black[0].getpixel(corner)) < 25                                    # -> black tiles
    assert any(min(px) > 200 for px in black[0].get_flattened_data())             # with light digits
    e.cover_provider = lambda: ("t3", Image.new("RGB", (64, 64), (245, 245, 245)))  # white cover
    white = e.preview()
    assert min(white[0].getpixel(corner)) > 230                                   # -> white tiles
    e.cover_provider = lambda: None                                               # stopped
    assert e.preview()[0].getpixel(corner)[1] > 200


def test_apply_light_keeps_original_theme_untouched():
    theme = theme_named("Game Boy")
    lit = digits.apply_light(theme, "#3366FF")
    assert theme["lightest"] == "#9BBC0F" and lit["lightest"] != "#9BBC0F"


def test_light_colour_preserves_all_rgb_channels():
    from timesgate.client import safe_light_color
    assert safe_light_color("#FFFFFF") == "#FFFFFF"
    assert safe_light_color("#EEFF00") == "#EEFF00"
    assert safe_light_color("#FC4E48") == "#FC4E48"
    s = FakeSession()
    TimesGateClient("1.2.3.4", 1, session=s).set_light(on=True, brightness=50, color="#FFFFFF", zone=0,
                                                      effect=11, color_cycle=False, key_light=True)
    assert s.posts[0][1]["Color"] == "#FFFFFF"



def test_v6_keeps_only_figma_faces_and_user_packs(tmp_path):
    import json
    from core.settings import Settings as S
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "tg_themes_version": 5, "tg_theme": 3,
        "tg_themes": [{"name": "Неон", "style": "neon"}, {"name": "Виджет", "style": "widget"},
                      {"name": "Мой пак", "style": "custom", "chars": {"1": "C:/x/1.png"}},
                      {"name": "Swiss Brutal", "style": "swiss", "follow_light": True},
                      {"name": "Пустой пак", "style": "custom"}],
        "tg_custom_chars": {}}), "utf-8")
    s = S.load(path)
    names = [x["name"] for x in s.tg_themes]
    assert names == ["Мой пак", "Swiss Brutal", "Material Expressive", "Glassmorphism", "CRT Terminal", "Editorial Serif", "Game Boy"]
    assert s.tg_themes[s.tg_theme]["name"] == "Swiss Brutal" and s.tg_themes[1]["follow_light"]


def test_only_figma_styles_are_offered():
    assert list(digits.STYLES) == ["glass", "swiss", "crt", "serif", "gameboy", "soft", "custom"]
    assert [x["name"] for x in digits.DEFAULT_THEMES] == ["Glassmorphism", "Swiss Brutal", "CRT Terminal",
                                                          "Editorial Serif", "Game Boy", "Material Expressive"]


def test_swiss_colon_is_the_negative_of_the_digits_when_following_light():
    theme = digits.apply_light(theme_named("Swiss Brutal"), "#FF3B1F")      # red tiles, cream digits
    colon = digits.char_frames(theme, ":", False, {})[0][0]
    assert colon.getpixel((10, 120)) == digits.parse_hex("#F2EFE6")         # background = digit colour
    r, g, b = colon.getpixel((64, 50))                                      # a square = tile colour
    assert r > 220 and g < 90
    yellow = digits.apply_light(theme_named("Swiss Brutal"), "#FFD400")     # yellow tiles, black digits
    colon = digits.char_frames(yellow, ":", False, {})[0][0]
    assert colon.getpixel((10, 120)) == digits.parse_hex("#111111")
    plain = digits.char_frames(theme_named("Swiss Brutal"), ":", False, {})[0][0]
    assert plain.getpixel((10, 120)) == digits.parse_hex("#111111")         # default design unchanged


def test_black_and_white_cover_uses_the_chosen_led_fallback(make_engine):
    e, _ = make_engine(dt.datetime(2026, 10, 5, 10, 0))
    s = e.settings
    s.tg_manage_light, s.tg_light_follow_cover, s.tg_light_color = True, True, "#EEFF00"
    e.cover_provider = lambda: ("bw", Image.new("RGB", (64, 64), (15, 15, 15)))
    assert e.light_color() == "#000000"                    # mostly black: the face goes black
    assert e.led_color() == ("#FFFFFF", True)              # default: own colour on the LEDs
    s.tg_light_bw_mode = "off"
    assert e.led_color() == ("#FFFFFF", True)
    s.tg_light_bw_mode = "white"
    assert e.led_color() == ("#FFFFFF", True)
    e.cover_provider = lambda: ("blue", Image.new("RGB", (64, 64), (20, 40, 220)))
    assert e.led_color()[0] != "#EEFF00" and e.led_color()[1] is True


def test_cover_colour_disables_cycle_until_playback_stops(make_engine):
    e, _ = make_engine(dt.datetime(2026, 11, 4, 12, 0))
    s = e.settings
    s.tg_manage_light = s.tg_light_follow_cover = s.tg_light_cycle = True
    cover = [None]
    e.cover_provider = lambda: cover[0]
    e._tick()
    client = FakeClient.instances[-1]
    assert client.light_states[-1]['color_cycle'] is True
    cover[0] = ('song', Image.new('RGB', (64, 64), (180, 100, 120)))
    e._tick()
    assert client.light_states[-1]['color_cycle'] is False
    assert s.tg_light_cycle is True  # remember the user's idle setting
    cover[0] = None
    e._tick()
    assert client.light_states[-1]['color_cycle'] is True


def test_monochrome_off_applies_even_when_own_colour_is_white(make_engine):
    e, _ = make_engine(dt.datetime(2026, 11, 4, 12, 0))
    s = e.settings
    s.tg_light_follow_cover = True
    s.tg_light_color = '#FFFFFF'
    s.tg_light_bw_mode = 'off'
    e.cover_provider = lambda: ('white', Image.new('RGB', (64, 64), 'white'))
    assert e.led_color() == ("#FFFFFF", True)
    e.cover_provider = lambda: None
    assert e.led_color() == ('#FFFFFF', True)


@pytest.mark.parametrize('value', ['#FFF', '#1234567', '#GG0000', '12 456'])
def test_invalid_light_colours_are_rejected(value):
    from timesgate.client import safe_light_color
    with pytest.raises(ValueError):
        safe_light_color(value)


def test_white_uses_verified_combined_white_effect_then_restores_selected_effect():
    s = FakeSession()
    c = TimesGateClient('1.2.3.4', 1, session=s)
    options = dict(on=True, brightness=70, zone=2, effect=11, color_cycle=True, key_light=True)
    c.set_light(color='#FFFFFF', **options)
    white = s.posts[-1][1]
    assert white['SelectLightIndex'] == 0
    assert [x['SelectEffect'] for x in white['LightList']] == [5, 0, 0]
    assert white['ColorCycle'] == 0 and white['Brightness'] == 70
    c.set_light(color='#8060D0', **options)
    colored = s.posts[-1][1]
    assert colored['SelectLightIndex'] == 2 and colored['LightList'][2]['SelectEffect'] == 11
    assert colored['Color'] == '#8060D0' and colored['ColorCycle'] == 1


def test_black_is_off_and_grey_scales_white_brightness():
    s = FakeSession()
    c = TimesGateClient('1.2.3.4', 1, session=s)
    options = dict(on=True, brightness=80, zone=0, effect=11, color_cycle=False, key_light=False)
    c.set_light(color='#000000', **options)
    assert s.posts[-1][1]['OnOff'] == 0
    c.set_light(color='#808080', **options)
    assert s.posts[-1][1]['Brightness'] == 40
    assert s.posts[-1][1]['LightList'][0]['SelectEffect'] == 5


def test_glass_manual_palette_does_not_rotate_by_digit():
    theme = dict(theme_named("Glassmorphism"), b1="#FF0000", b2="#00FF00", b3="#0000FF")
    for char in "0123456789:":
        assert digits._glass_palette(theme, char) == [(255,0,0),(0,255,0),(0,0,255)]


@pytest.mark.parametrize("theme", digits.FIGMA_THEMES, ids=lambda t:t["style"])
def test_manual_color_roles_change_the_render(theme):
    for key, _, _ in digits.style_roles(theme["style"]):
        altered = dict(theme, **{key:"#FF00FF"})
        # Swiss per-digit backgrounds are tested with that actual digit.
        text = (key[1]+"2:34") if key.startswith("t") and key[1:].isdigit() else "12:34"
        before = digits.theme_thumbnail(theme, text=text).tobytes()
        assert digits.theme_thumbnail(altered, text=text).tobytes() != before, (theme["style"], key)


def test_compact_swiss_has_shared_background_and_one_gallery_tile():
    theme = theme_named("Swiss Brutal")
    image = digits.compact_clock_frames(theme,"12:34",False,{})[0][0]
    assert image.getpixel((1,1)) == image.getpixel((126,126)) == digits.role(theme,"t1")
    assert digits.theme_thumbnail(theme,compact=True).size == (40,40)
    assert digits.theme_thumbnail(theme).size == (212,40)


def test_cover_palette_recolors_serif_background_and_crt_screen():
    serif = digits.apply_light(theme_named("Editorial Serif"), "#0088FF")
    assert serif["paper"] == "#0088FF"
    assert serif["ink"] != serif["paper"]
    crt = digits.apply_light(theme_named("CRT Terminal"), "#FF0022")
    assert crt["phosphor"] == "#FF0022"
    assert digits.parse_hex(crt["screen"])[1] == 0
    assert digits.parse_hex(crt["case"])[1] == 0


def test_black_cover_keeps_crt_digits_visible():
    theme = digits.apply_light(theme_named("CRT Terminal"), "#000000")
    assert theme["screen"] == "#000000"
    assert theme["phosphor"] == "#FFFFFF"


def test_soft_forms_shapes_palette_and_cover_color():
    theme = digits.SOFT_FORMS_THEME
    assert digits.soft_form_mask((128,128),"0").getpixel((0,0)) == 0
    leaf = digits.soft_form_mask((128,128),"1")
    assert leaf.getpixel((25,5)) == 0
    assert leaf.getpixel((100,5)) == 255
    for color in ("#FF0033", "#000000", "#FFFFFF"):
        followed = digits.apply_light(theme,color)
        assert followed["shape"] == color
        assert followed["digit"] != color
    changed = dict(theme, digit="#FF0000")
    image = digits.char_frames(changed,"8",False,{})[0][0]
    assert any(r>240 and g<20 and b<20 for r,g,b in image.get_flattened_data())


def test_soft_forms_is_added_once_without_reselecting_current_theme(tmp_path):
    import json
    from core.settings import Settings
    path = tmp_path/"settings.json"
    path.write_text(json.dumps({"tg_themes_version":6,"tg_theme":0,
        "tg_themes":[{"name":"My Swiss","style":"swiss","t1":"#123456"}]}))
    settings = Settings.load(path)
    assert settings.tg_themes[settings.tg_theme]["name"] == "My Swiss"
    assert settings.tg_themes[0]["t1"] == "#123456"
    assert sum(t["style"]=="soft" for t in settings.tg_themes) == 1
    settings.save(path)
    again = Settings.load(path)
    assert sum(t["style"]=="soft" for t in again.tg_themes) == 1


def test_outfit_bold_is_bundled():
    from PIL import ImageFont
    font = ImageFont.truetype(str(digits.FONTS_DIR/"Outfit-Variable.ttf"),32)
    assert b"Bold" in font.get_variation_names()


def test_soft_forms_pack_preserves_user_palette(tmp_path, monkeypatch):
    from timesgate import packs
    monkeypatch.setattr(packs,"PACKS_DIR",tmp_path/"packs")
    theme = dict(digits.SOFT_FORMS_THEME,shape="#BB2255",digit="#FFFFFF",bg="#112233")
    path = tmp_path/"soft.zip"
    packs.export_pack(theme,str(path))
    imported = packs.import_pack(str(path))
    assert imported["style"] == "soft"
    assert all(imported[key] == theme[key] for key in ("bg","shape","digit"))



def test_material_expressive_forces_black_background_even_for_old_palettes():
    theme = dict(digits.SOFT_FORMS_THEME,bg="#FFFFFF")
    assert theme["name"] == "Material Expressive"
    assert digits.canvas_bg(theme) == (0,0,0)
    assert "bg" not in [key for key,_,_ in digits.style_roles("soft")]
    assert digits.char_frames(theme,"0",False,{})[0][0].getpixel((0,0)) == (0,0,0)
    assert digits.compact_clock_frames(theme,"19:34",False,{})[0][0].getpixel((0,0)) == (0,0,0)
    assert digits.apply_light(theme,"#FF0022")["bg"] == "#000000"



def test_soft_forms_rename_preserves_selection_and_palette(tmp_path):
    import json
    from core.settings import Settings
    path = tmp_path/"config.json"
    path.write_text(json.dumps({"tg_themes_version":7,"tg_theme":0,
        "tg_themes":[{"name":"Soft Forms","style":"soft","bg":"#FFFFFF",
                      "shape":"#AA2255","digit":"#FFFFFF"}]}))
    settings = Settings.load(path)
    assert len(settings.tg_themes) == 1
    assert settings.tg_theme == 0
    assert settings.tg_themes[0]["name"] == "Material Expressive"
    assert settings.tg_themes[0]["shape"] == "#AA2255"
    assert settings.tg_themes[0]["bg"] == "#000000"



def test_heartbeat_marks_idle_device_offline_and_recovers(make_engine, monkeypatch):
    import timesgate.engine as module
    now = [100.0]
    monkeypatch.setattr(module.time,"monotonic",lambda:now[0])
    e,_ = make_engine(dt.datetime(2026,11,11,12,0))
    events = []
    e.add_listener(lambda name,payload:events.append((name,payload)))
    assert e._tick() <= module.HEARTBEAT_S
    client = FakeClient.instances[-1]
    assert e.status[0]
    client.sent.clear()
    original = client.get_config
    def offline():
        raise module.TimesGateError("offline")
    client.get_config = offline
    now[0] += module.HEARTBEAT_S
    e._tick()
    assert not e.status[0]
    assert client.sent == []
    client.get_config = original
    now[0] += 10
    e._tick()
    assert e.status[0]
    assert len(client.sent) == 5
