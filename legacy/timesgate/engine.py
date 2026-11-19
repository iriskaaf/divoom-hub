"""Times Gate controller: keeps the five screens showing the chosen clock.

One background thread. Every wake-up it works out what each screen should show
(a key per screen) and uploads only screens whose key changed, so a normal
minute costs one upload (the last digit). The device reboots with the PC every
night, so a lost connection is retried, and the screens are re-sent after it
comes back. If the IP changed, the device is found again by MAC address.

Rendered frames are cached by screen key, so the GUI preview and the upload
share one render and an unchanged digit is never drawn twice.

Modes:
  clock       H H : M M across the five screens (optionally the Spotify cover
              instead of the colon while music plays)
  gifs_clock  user pictures/GIFs on screens 1, 2, 4, 5 and HH:MM in the middle
  device      a built-in face that runs on the Times Gate itself (no PC needed)
  off         the program does not touch the screens
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from PIL import Image

from core.settings import Settings

from . import digits
from .client import (SCREENS, TimesGateAuthError, TimesGateClient, TimesGateError, discover)

log = logging.getLogger(__name__)

MODES = {"clock": "Часы на 5 экранах", "gifs_clock": "Картинки по бокам, часы в центре",
         "device": "Встроенный циферблат устройства (без ПК)", "off": "Не управлять экранами"}
RETRY_S = 10.0
HEARTBEAT_S = 5.0
WEATHER_EVERY_S = 15 * 60
REDISCOVER_AFTER = 3  # failed connects before looking the device up again

Listener = Callable[[str, object], None]


def _is_grey(color: str) -> bool:
    c = digits.parse_hex(color)
    return max(c) - min(c) < 24
Render = Callable[[], digits.Frames]
CoverProvider = Callable[[], "tuple[str, Image.Image] | None"]
CACHE_SIZE = 48


class TimesGateEngine:
    def __init__(self, settings: Settings, client_factory=TimesGateClient,
                 clock: Callable[[], dt.datetime] = dt.datetime.now,
                 cover_provider: CoverProvider | None = None):
        self.settings = settings
        self.cover_provider = cover_provider or (lambda: None)
        self._cache: OrderedDict[tuple, digits.Frames] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._client_factory = client_factory
        self._now = clock
        self._listeners: list[Listener] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._client: TimesGateClient | None = None
        self._client_key: tuple | None = None
        self._connected = False
        self._last_probe_at = 0.0
        self._failures = 0
        self._sent: list[tuple | None] = [None] * SCREENS
        self._lights_dirty = True
        self._brightness_dirty = True
        self._device_face_sent: int | None = None
        self._light_sent: tuple | None = None
        self._accent: tuple[str, str] | None = None  # (track id, "#RRGGBB")
        self._weather: float | None = None
        self._weather_at = 0.0

    # ---- lifecycle -------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="timesgate", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)
        return not self._thread or not self._thread.is_alive()

    # ---- public API (any thread) ----------------------------------------

    def refresh(self) -> None:
        """Settings changed: re-render everything that differs."""
        self._wake.set()

    def reconnect(self) -> None:
        with self._lock:
            self._client = None
            self._connected = False
            self._sent = [None] * SCREENS
        self._status(False, "Подключение…")
        self._wake.set()

    def apply_lights(self) -> None:
        self._lights_dirty = True
        self._wake.set()

    def apply_brightness(self) -> None:
        self._brightness_dirty = True
        self._wake.set()

    def current_theme(self) -> dict:
        themes = self.settings.tg_themes or digits.DEFAULT_THEMES
        return themes[self.settings.tg_theme % len(themes)]

    def switch_theme(self, step: int = 0, name: str | None = None) -> str:
        """Next/previous theme (step = +1/-1) or one by name. Returns its name."""
        themes = self.settings.tg_themes or digits.DEFAULT_THEMES
        if name is not None:
            matches = [i for i, t in enumerate(themes) if t["name"].lower() == name.lower()]
            if not matches:
                log.warning("Times Gate: no theme named %r", name)
                return self.current_theme()["name"]
            self.settings.tg_theme = matches[0]
        else:
            self.settings.tg_theme = (self.settings.tg_theme + step) % len(themes)
        if self.settings.tg_mode in ("device", "off"):
            self.settings.tg_mode = "clock"  # choosing a face means "draw it"
            self._emit("tg_mode", "clock")
        self.settings.save()
        theme = self.current_theme()
        log.info("Times Gate: theme '%s'", theme["name"])
        self._emit("tg_theme", theme["name"])
        self._wake.set()
        return theme["name"]

    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self.settings.tg_mode = mode
            self.settings.save()
            self._emit("tg_mode", mode)
            self._wake.set()

    def preview(self) -> list[Image.Image | None]:
        """First frame of what each screen should show now (for the GUI)."""
        return [self._frames(item)[0][0] if item else None for item in self._desired(self._now())]

    def _frames(self, item: tuple[tuple, Render]) -> digits.Frames:
        key, render = item
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        frames = render()  # outside the lock: a duplicate render is harmless
        with self._cache_lock:
            self._cache[key] = frames
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return frames

    # ---- thread ----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            delay = self._tick()
            self._wake.wait(delay)

    def _tick(self) -> float:
        s = self.settings
        if not s.timesgate_enabled:
            self._connected = False
            self._status(False, "Устройство не выбрано")
            return 60.0
        if not s.tg_ip or not s.tg_token:
            self._status(False, "Укажите IP и LocalToken")
            return 60.0  # config changes wake this loop immediately
        if not s.tg_token.isascii() or not s.tg_token.isdigit():
            self._status(False, "LocalToken должен состоять из цифр")
            return 30.0
        try:
            client = self._ensure_client()
            if self._connected and time.monotonic()-self._last_probe_at >= HEARTBEAT_S:
                client.get_config()
                self._last_probe_at = time.monotonic()
            if not self._connected:
                client.get_config()
                self._last_probe_at = time.monotonic()
                client.reset_pic_id()
                self._connected, self._failures = True, 0
                self._sent = [None] * SCREENS
                self._lights_dirty = self._brightness_dirty = True
                self._device_face_sent = None
                self._light_sent = None
                self._weather_at = 0.0
                log.info("Times Gate connected (%s)", s.tg_ip)
                self._status(True, f"Подключено ({s.tg_ip})")
            self._apply_device_settings(client)
            self._apply_device_face(client)
            self._update_weather(client)
            self._update_screens(client)
        except TimesGateAuthError:
            self._connected = False
            self._status(False, "Неверный LocalToken")
            return 30.0
        except (TimesGateError, OSError) as e:
            if self._connected:
                log.warning("Times Gate lost: %s", e)
            self._connected = False
            self._failures += 1
            self._status(False, "Нет связи, повтор через 10 с")
            if self._failures >= REDISCOVER_AFTER and s.tg_mac:
                self._rediscover()
            return RETRY_S
        except Exception:
            self._connected = False
            self._status(False, "Ошибка связи, повтор через 10 с")
            log.exception("Times Gate update failed")
            return RETRY_S
        now = self._now()
        return min(HEARTBEAT_S, max(0.5, 60.5 - now.second - now.microsecond / 1e6))  # just after the next minute

    def _ensure_client(self) -> TimesGateClient:
        s = self.settings
        key = (s.tg_ip, s.tg_token, s.tg_hardware)
        with self._lock:
            if self._client is None or self._client_key != key:
                self._client = self._client_factory(s.tg_ip, int(s.tg_token), s.tg_hardware)
                self._client_key = key
                self._connected = False
            return self._client

    def _apply_device_settings(self, client: TimesGateClient) -> None:
        s = self.settings
        if self._brightness_dirty:
            self._brightness_dirty = False
            client.set_brightness(s.tg_brightness)
        color, on = self.led_color()
        # A colour cycle overrides the cover after each animation loop. Keep
        # cover-follow mode fixed while a track actually supplies a cover.
        follow = s.tg_light_follow_cover and self.cover_provider() is not None
        cycle = s.tg_light_cycle and not follow
        zone, effect = s.tg_light_zone, s.tg_light_effect
        if follow and not _is_grey(color):
            from .client import effects_for_zone
            if not any(number == effect and custom for number, _, custom in effects_for_zone(zone)):
                # A preset with its own palette can ignore Color altogether.
                effect = 6 if zone == 2 else 9
            r, g, b = digits.parse_hex(color)
            if r > b > g and b - g >= 18:
                # Compensate for red dominance in the pink range only.
                b = min(r, round(g + (b - g) * 1.25))
                color = f"#{r:02X}{g:02X}{b:02X}"
        state = (on, s.tg_light_brightness, color, zone, effect, cycle, s.tg_key_light)
        if self._lights_dirty or state != self._light_sent:
            client.set_light(on=on, brightness=s.tg_light_brightness, color=color,
                             zone=zone, effect=effect,
                             color_cycle=cycle, key_light=s.tg_key_light)
            if color != (self._light_sent or (None,) * 3)[2]:
                log.info("Times Gate light colour %s", color)
            self._lights_dirty, self._light_sent = False, state

    def led_color(self) -> tuple[str, bool]:
        """What the LEDs get, respecting the user's monochrome-cover policy."""
        s = self.settings
        color = self.light_color()
        if s.tg_light_follow_cover and self.cover_provider() is not None and _is_grey(color):
            return "#FFFFFF", s.tg_light_on
        return color, s.tg_light_on

    def light_color(self) -> str:
        """The cover's accent colour while Spotify plays (if enabled), else the user's colour."""
        s = self.settings
        return self.cover_color() if s.tg_light_follow_cover else s.tg_light_color

    def cover_color(self) -> str:
        cover = self.cover_provider()
        if cover is None:
            return self.settings.tg_light_color
        track_id, image = cover
        if self._accent is None or self._accent[0] != track_id:
            from core import colors
            self._accent = (track_id, colors.hex_color(colors.accent_color(image)))
        return self._accent[1]

    def _update_weather(self, client: TimesGateClient) -> None:
        """Temperature for the widget face, from the weather the device itself holds."""
        if self.current_theme().get("style") not in digits.SINGLE_STYLES:
            return
        if time.monotonic() - self._weather_at < WEATHER_EVERY_S:
            return
        self._weather_at = time.monotonic()
        try:
            temp = client.get_weather().get("CurTemp")
            self._weather = float(temp) if temp is not None else None
        except (TimesGateError, OSError, ValueError, TypeError) as e:
            log.debug("Times Gate weather unavailable: %s", e)

    def _apply_device_face(self, client: TimesGateClient) -> None:
        s = self.settings
        if s.tg_mode != "device":
            self._device_face_sent = None
            return
        if self._device_face_sent != s.tg_device_face:
            client.set_whole_face(s.tg_device_face)
            self._device_face_sent = s.tg_device_face
            log.info("Times Gate: built-in face %s, the device runs on its own", s.tg_device_face)

    def release_to_device(self) -> None:
        """On exit: leave a working clock instead of a frozen picture."""
        s = self.settings
        if not (s.timesgate_enabled and self._connected and s.tg_device_face_on_exit and s.tg_mode in ("clock", "gifs_clock")):
            return
        try:
            client = self._ensure_client()
            client.timeout = 3.0
            client.set_whole_face(s.tg_device_face)
            log.info("Times Gate: handed over to built-in face %s", s.tg_device_face)
        except (TimesGateError, OSError) as e:
            log.warning("Times Gate: could not switch to the built-in face: %s", e)

    def _update_screens(self, client: TimesGateClient) -> None:
        desired = self._desired(self._now())
        changed = False
        for screen, item in enumerate(desired):
            if self._stop.is_set():
                return
            if item is None:
                self._sent[screen] = None  # not ours: re-send when the mode comes back
                continue
            key = item[0]
            if key == self._sent[screen]:
                continue
            frames, speed = self._frames(item)
            client.send_frames(screen, frames, speed)
            self._sent[screen] = key
            changed = True
            log.debug("Times Gate screen %d updated (%s)", screen + 1, key[0])
        if changed:
            self._emit("tg_screens", None)

    def _desired(self, now: dt.datetime) -> list[tuple[tuple, Render] | None]:
        s = self.settings
        if s.tg_mode in ("off", "device"):
            return [None] * SCREENS
        theme = dict(self.current_theme())
        if s.tg_face_follow_cover and self.cover_provider() is not None:
            # the face takes the light's colour: the cover's while music plays
            theme = digits.apply_light(theme, self.cover_color())
        hh = now.strftime("%H" if s.tg_24h else "%I")
        text = f"{hh}:{now:%M}"
        custom = digits.theme_chars(theme, s.tg_custom_chars)
        # every colour / font / effect of the theme takes part in the cache key
        theme_key = (tuple(sorted((k, str(v)) for k, v in theme.items()
                                  if k not in ("name", "id", "chars"))), s.tg_blink_colon)
        per_position = theme.get("style") == "material"  # each digit sits on its own shape colour

        def media_key(path: str) -> tuple:
            try:
                return (path, os.path.getmtime(path))
            except OSError:
                return (path, None)

        def char_item(ch: str, pos: int):
            key = ("char", ch, theme_key, pos if per_position else None,
                   media_key(custom.get(ch, "")) if theme["style"] == "custom" else None)
            return key, lambda: digits.char_frames(theme, ch, s.tg_blink_colon, custom, pos)

        single = theme.get("style") in digits.SINGLE_STYLES
        if s.tg_mode == "clock" and not single:
            items = [char_item(ch, (0, 1, 0, 2, 3)[i]) for i, ch in enumerate(text)]
            cover = self.cover_provider() if s.tg_center_cover else None
            if cover is not None:
                track_id, image = cover
                items[2] = (("cover", track_id),
                            lambda img=image: ([digits.fit_cover(img)], 1000))
            return items

        # gifs_clock (or a one-screen face): pictures on 0, 1, 3, 4, a clock in the middle
        out: list[tuple[tuple, Render] | None] = []
        side = list(s.tg_side_media) + [""] * 4
        for screen in range(SCREENS):
            if screen == 2 and single:
                temp = None if self._weather is None else round(self._weather)
                key = ("widget", text, now.weekday(), now.day, temp, theme_key)
                out.append((key, lambda: ([digits.widget_frame(theme, text, now.weekday(), now.day, temp)],
                                          1000)))
                continue
            if screen == 2:
                customs = tuple(media_key(custom.get(c, "")) for c in "0123456789:") \
                    if theme["style"] == "custom" else None
                key = ("compact", text, theme_key, customs)
                out.append((key, lambda: digits.compact_clock_frames(theme, text, s.tg_blink_colon, custom)))
                continue
            path = side[screen if screen < 2 else screen - 1]
            if path and os.path.exists(path):
                out.append((("media", media_key(path)), lambda p=path: digits.load_media(p)))
            else:
                bg = digits.canvas_bg(theme)
                out.append((("blank", bg), lambda bg=bg: ([Image.new("RGB", (128, 128), bg)], 1000)))
        return out

    def _rediscover(self) -> None:
        s = self.settings
        try:
            found = discover()
        except TimesGateError as e:
            log.debug("Times Gate rediscovery failed: %s", e)
            return
        for dev in found:
            if dev.mac and dev.mac.lower() == s.tg_mac.lower() and dev.ip and dev.ip != s.tg_ip:
                log.info("Times Gate moved: %s -> %s", s.tg_ip, dev.ip)
                s.tg_ip = dev.ip
                s.save()
                self._emit("tg_ip", dev.ip)
                self._failures = 0
                return

    def _status(self, connected: bool, text: str) -> None:
        if (connected, text) != getattr(self, "_last_status", None):
            self._last_status = (connected, text)
            self._emit("tg", (connected, text))

    @property
    def status(self) -> tuple[bool, str]:
        return getattr(self, "_last_status", (False, "—"))

    def _emit(self, name: str, payload: object) -> None:
        for listener in self._listeners:
            try:
                listener(name, payload)
            except Exception:
                log.exception("Listener failed for %s", name)
