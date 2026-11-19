"""Divoom Times Gate local HTTP API (Wi-Fi, JSON over HTTP POST).

Facts used, with sources:
  * POST JSON to http://IP/post; hardware revision 402 uses http://IP:9000/divoom_api
    (official Divoom docs, ShowDoc item 5 "TimeGate" pages 102/107/133/353;
    402 is unverified by anyone we know of).
  * Every request carries an integer LocalToken (Divoom app -> device settings).
    A wrong token makes the device answer {"error_code": "DeviceToken is err"}.
  * Draw/SendHttpGif: PicData must be a base64 JPEG (raw RGB is accepted but
    leaves the screen on "loading"), PicWidth 128, LcdArray one flag per screen,
    PicID strictly increasing (reset once with Draw/ResetHttpGifId), at most
    ~40 frames per animation, all frames share one PicID.
  * Channel/SetRGBInfo: OnOff 1 = on (the official doc says the opposite).
  * LAN discovery: POST https://app.divoom-gz.com/Device/ReturnSameLANDevice.
  Verified-on-device notes: averhaegen/hacs-divoom-times-gate-dev docs/API.md,
  LIMITATIONS.md, RGB_LIGHTS.md (hardware 400 unit).
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

import requests
from PIL import Image

log = logging.getLogger(__name__)

SCREENS = 5
SIZE = 128
MAX_FRAMES = 40
DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"
WHOLE_FACES_URL = "https://app.divoom-gz.com/Channel/Get5LcdClockListForCommon"
# Fallback when the cloud list is unavailable (Get5LcdClockListForCommon, 2026-10).
BUILTIN_FACES = {581: "Clock face", 697: "City Time", 570: "DIY Time number", 1040: "Neon",
                 703: "Brilliant Xamas", 583: "Import Figure"}


class TimesGateError(Exception):
    pass


class TimesGateAuthError(TimesGateError):
    """The device rejected the LocalToken."""


@dataclass(frozen=True)
class FoundDevice:
    name: str
    device_id: int
    ip: str
    mac: str


def discover(session: requests.Session | None = None) -> list[FoundDevice]:
    """Divoom devices behind the same public IP (cloud lookup, no account needed)."""
    http = session or requests.Session()
    try:
        r = http.post(DISCOVERY_URL, json={}, timeout=8)
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        raise TimesGateError(f"Discovery failed: {e}") from e
    return [FoundDevice(d.get("DeviceName", ""), int(d.get("DeviceId") or 0),
                        d.get("DevicePrivateIP", ""), d.get("DeviceMac", ""))
            for d in body.get("DeviceList") or []]


def whole_faces(session: requests.Session | None = None) -> dict[int, str]:
    """Built-in faces spanning all five screens (cloud catalogue, 30 per page).
    Selecting one is local and keeps running without the PC."""
    http = session or requests.Session()
    faces: dict[int, str] = {}
    try:
        for page in range(1, 6):
            r = http.post(WHOLE_FACES_URL, json={"Page": page}, timeout=8)
            items = r.json().get("ClockList") or []
            for item in items:
                faces[int(item["ClockId"])] = str(item.get("ClockName", "")).strip() or str(item["ClockId"])
            if len(items) < 30:
                break
    except (requests.RequestException, ValueError, KeyError) as e:
        log.debug("Whole-face list unavailable: %s", e)
    return faces or dict(BUILTIN_FACES)


def to_jpeg(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    # 4:4:4 chroma keeps pixel-art edges and saturated colours clean.
    image.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0)
    return buf.getvalue()


# Light effects: (id, name, takes the chosen colour). Edge / all-lights mapping
# and backlight mapping differ (RGB_LIGHTS.md tables 1a/1b, verified on HW 400).
EFFECTS_EDGE = [
    (0, "Искры (пастель)", False), (1, "Маятник", False), (2, "Радуга", False),
    (3, "Жук (радуга)", False), (4, "Дыхание", True), (5, "Белый свет", False),
    (6, "Волны", False), (7, "Дождь", False), (8, "Сердце", True),
    (9, "Бесконечность", True), (10, "Ракета", False), (11, "Цветовое колесо", True),
]
EFFECTS_BACK = [
    (0, "Жук (радуга)", False), (1, "Атом", False), (2, "Маятник", False),
    (3, "Искры", False), (4, "Пульс", True), (5, "Ровный цвет", True),
    (6, "Бесконечность", True), (7, "Чат", True), (8, "Антенна", True),
    (9, "Волны", True), (10, "Дождь", True), (11, "Круги", True),
]
LIGHT_ZONES = {0: "Вся подсветка", 1: "Боковая", 2: "Задняя"}


def safe_light_color(color: str) -> str:
    """Validate the documented #RRGGBB value without changing its channels.

    The old 255 -> 254 workaround was an unverified hypothesis. In particular
    it prevented sending the documented pure-white value at all.
    """
    s = color.strip().removeprefix("#")
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError("Light colour must be #RRGGBB")
    return "#" + s.upper()


def effects_for_zone(zone: int) -> list[tuple[int, str, bool]]:
    return EFFECTS_BACK if zone == 2 else EFFECTS_EDGE


class TimesGateClient:
    def __init__(self, ip: str, token: int | str, hardware: int = 400,
                 session: requests.Session | None = None, timeout: float = 6.0):
        self.ip = ip.strip()
        self.token = int(token)
        self.hardware = hardware
        self.http = session or requests.Session()
        self.timeout = timeout
        self._pic_id = 0

    @property
    def url(self) -> str:
        if self.hardware == 402:
            return f"http://{self.ip}:9000/divoom_api"
        return f"http://{self.ip}/post"

    def command(self, payload: dict) -> dict:
        body = {**payload, "LocalToken": self.token}
        try:
            r = self.http.post(self.url, json=body, timeout=self.timeout)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise TimesGateError(f"{payload.get('Command')}: {e}") from e
        code = data.get("error_code", 0)
        if code == 0:
            return data
        if "token" in str(code).lower():
            raise TimesGateAuthError("LocalToken rejected")
        raise TimesGateError(f"{payload.get('Command')}: error_code {code!r}")

    # ---- device ----------------------------------------------------------

    def get_config(self) -> dict:
        return self.command({"Command": "Channel/GetAllConf"})

    def get_weather(self) -> dict:
        # Times Gate command: Device/GetWeatherInfo
        # Purpose: the weather the device holds for the city set in the Divoom app
        #          (CurTemp, MinTemp, MaxTemp, Weather, ...).
        # Source: official doc page 112; HACS docs/LIMITATIONS.md ("works, cloud weather").
        return self.command({"Command": "Device/GetWeatherInfo"})

    def reset_pic_id(self) -> None:
        self.command({"Command": "Draw/ResetHttpGifId"})
        self._pic_id = 0

    def set_brightness(self, value: int) -> None:
        self.command({"Command": "Channel/SetBrightness",
                      "Brightness": max(0, min(100, int(value)))})

    def set_whole_face(self, clock_id: int) -> None:
        # Times Gate command: Channel/Set5LcdWholeClockId
        # Purpose: switch all five screens to a built-in face that runs on the
        #          device itself (no PC needed afterwards).
        # Source: official doc page 116; verified on HW 400 in
        #         averhaegen/hacs-divoom-times-gate-dev docs/API.md section 2.4.
        self.command({"Command": "Channel/Set5LcdWholeClockId", "ClockId": int(clock_id)})

    def set_screen_on(self, on: bool) -> None:
        self.command({"Command": "Channel/OnOffScreen", "OnOff": 1 if on else 0})

    def set_light(self, *, on: bool, brightness: int, color: str, zone: int,
                  effect: int, color_cycle: bool, key_light: bool) -> None:
        # LightList index meaning depends on SelectLightIndex (RGB_LIGHTS.md 2b-2d):
        # zone 0 -> [0], zone 1 (edge) -> [1], zone 2 (back) -> [2].
        light_list = [{"SelectEffect": 0} for _ in range(3)]
        color = safe_light_color(color)
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        if on and max(rgb) == min(rgb):
            # Confirmed on the user's Times Gate 2026-11-04: white RGB in
            # effect 11 -> red; rear effect 5 -> rainbow; combined effect 5
            # -> white on both zones. Restore the requested zone/effect for
            # the next chromatic colour (do not change saved preferences).
            if rgb[0] == 0:
                on = False
            else:
                zone, effect, color_cycle = 0, 5, False
                brightness = round(brightness * rgb[0] / 255)
                color = "#FFFFFF"
        light_list[zone if zone in (1, 2) else 0] = {"SelectEffect": int(effect)}
        self.command({
            "Command": "Channel/SetRGBInfo",
            "OnOff": 1 if on else 0,
            "Brightness": max(0, min(100, int(brightness))),
            "Color": color,
            "ColorCycle": 1 if color_cycle else 0,
            "SelectLightIndex": zone,
            "LightList": light_list,
            "KeyOnOff": 1 if key_light else 0,
        })

    # ---- pictures --------------------------------------------------------

    def send_frames(self, screen: int, frames: list[Image.Image], speed_ms: int = 500) -> None:
        """Show a picture (1 frame) or a looping animation on one screen (0-4)."""
        if not 0 <= screen < SCREENS:
            raise ValueError(f"screen must be 0-{SCREENS - 1}")
        frames = frames[:MAX_FRAMES] or [Image.new("RGB", (SIZE, SIZE))]
        lcd = [0] * SCREENS
        lcd[screen] = 1
        self._pic_id += 1
        for offset, frame in enumerate(frames):
            if frame.size != (SIZE, SIZE):
                frame = frame.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
            self.command({
                "Command": "Draw/SendHttpGif",
                "LcdArray": lcd,
                "PicNum": len(frames),
                "PicWidth": SIZE,
                "PicOffset": offset,
                "PicID": self._pic_id,
                "PicSpeed": max(50, int(speed_ms)),
                "PicData": base64.b64encode(to_jpeg(frame)).decode("ascii"),
            })
