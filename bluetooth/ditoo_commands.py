"""Ditoo Pro command builders. Every function returns ready-to-send frames.

Nothing here is invented: each command cites the implementation it was taken
from, and its hardware status is tracked in docs/research.md.
"""

from __future__ import annotations

import datetime as _dt
import struct
from enum import IntEnum


from .protocol import build_frame

CMD_GET_VOLUME = 0x09
CMD_SET_DATETIME = 0x18
CMD_KEYBOARD_LIGHT = 0x23  # SPP_LIGHT_ARROW_SWITCH in the Divoom Android app
CMD_SET_BRIGHTNESS = 0x74
CMD_SEND_ANIMATION = 0x8B  # "App new send gif cmd"

ANIMATION_CHUNK = 256


def get_volume() -> bytes:
    # Ditoo Pro command: 0x09 GET_VOLUME
    # Purpose: read-only query; the device answers with a 0x04 reply frame.
    #          Used as a harmless "is this the right RFCOMM channel?" probe.
    # Packet format: empty payload. Reply data: [volume 0..15].
    # Source: futpib/divoom-ditoo-pro-controller src/lib.rs send_get_volume
    #         (README: auto transport uses "a read-only volume probe").
    return build_frame(CMD_GET_VOLUME)


def set_brightness(percent: int) -> bytes:
    # Ditoo Pro command: 0x74 SET_BRIGHTNESS
    # Purpose: display brightness.
    # Packet format: [brightness 0..100]
    # Source: futpib/divoom-ditoo-pro-controller src/lib.rs send_set_brightness;
    #         sent to real hardware (over BLE) in firmware/restore-brightness-requests.json.
    return build_frame(CMD_SET_BRIGHTNESS, bytes([max(0, min(100, int(percent)))]))


def set_datetime(when: _dt.datetime | None = None) -> bytes:
    # Ditoo Pro command: 0x18 SET_DATETIME
    # Purpose: sync the device clock (the stock clock face uses it).
    # Packet format: [year % 100, year // 100, month, day, hour, minute, second]
    # Source: andreas-mausch/divoom-ditoo-pro-controller src/protocol/datetime.rs
    #         (originally d03n3rfr1tz3/esp32-divoom divoom.cpp).
    t = when or _dt.datetime.now()
    return build_frame(
        CMD_SET_DATETIME,
        bytes([t.year % 100, t.year // 100, t.month, t.day, t.hour, t.minute, t.second]),
    )


class KeyboardLight(IntEnum):
    # Ditoo Pro command: 0x23 keyboard light
    # Purpose: switch the stock keyboard light effect. Stock firmware offers
    #          ONLY these three actions; there is no RGB / per-key colour
    #          command on stock firmware (futpib docs/protocol-capabilities.md #7).
    # Packet format: [action]
    # Source: futpib src/main.rs (Next=0, Prev=1, Toggle=2) vs
    #         hass-divoom devices/ditoo.py (prev=0x00, next=0x01, toggle=0x02).
    #         The two sources disagree on next/prev; toggle=2 matches in both.
    NEXT = 0
    PREV = 1
    TOGGLE = 2


def keyboard_light(action: KeyboardLight) -> bytes:
    return build_frame(CMD_KEYBOARD_LIGHT, bytes([int(action)]))


CMD_SET_BOX_MODE = 0x45  # SPP_SET_BOX_MODE: switch the display channel
CMD_EXTENDED = 0xBD      # SPP_SECOND_* commands, selector in the first payload byte
EXT_USE_USER_DEFINE_INDEX = 0x17  # SPP_SECOND_USE_USER_DEFINE_INDEX: favourites tab

# Ditoo Pro command: 0x45 SET_BOX_MODE (+ 0xBD/0x17 for the favourites tab)
# Purpose: the channels the "M" key cycles through.
# Packet format: [channel, channel parameters...]
#   00 clock:   [00, 01, style, 01 (on), weather, temperature, calendar]
#   01 light:   [01, R, G, B, brightness, effect, power, 00, 00, 00]
#   02 hot (cloud), 04 visualizer [04, n], 05 custom/favourites, 06 lyrics/track name
# Source: RomRider/node-divoom-timebox-evo PROTOCOL.md (channel codes, clock,
#         light); d03n3rfr1tz3/hass-divoom devices/divoom.py show_clock /
#         show_light / show_visualization / show_design, devices/ditoo.py
#         show_lyrics; BD/17 name from the APK catalogue in futpib
#         data/protocol-commands.json.
# Status: the Ditoo sends no reply to 0x45 over RFCOMM (checked 2026-10-05),
#         so each mode is verified only by looking at the device.
DISPLAY_MODES: dict[str, tuple[str, list[tuple[int, bytes]]]] = {
    "keep": ("Не менять (оставить обложку)", []),
    "clock": ("Часы", [(CMD_SET_BOX_MODE, bytes([0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00]))]),
    "color": ("Цвет", [(CMD_SET_BOX_MODE, bytes([0x01, 0xFF, 0xFF, 0xFF, 100, 0x00, 0x01, 0, 0, 0]))]),
    "hot": ("Hot", [(CMD_SET_BOX_MODE, bytes([0x02]))]),
    "visualizer": ("Визуализатор музыки", [(CMD_SET_BOX_MODE, bytes([0x04, 0x00]))]),
    **{
        f"favorite{n}": (f"Избранное {n}", [
            (CMD_SET_BOX_MODE, bytes([0x05])),
            (CMD_EXTENDED, bytes([EXT_USE_USER_DEFINE_INDEX, n - 1])),
        ]) for n in (1, 2, 3)
    },
    "track_name": ("Название трека", [(CMD_SET_BOX_MODE, bytes([0x06, 0x00, 0x00, 0x00]))]),
    # Guess: the light channel with power off. Unverified.
    "black": ("Чёрный экран", [(CMD_SET_BOX_MODE, bytes([0x01, 0, 0, 0, 0, 0x00, 0x00, 0, 0, 0]))]),
}


def display_mode(key: str) -> list[bytes]:
    _, commands = DISPLAY_MODES[key]
    return [build_frame(command, payload) for command, payload in commands]


# Ditoo Pro command: 0x8B "App new send gif cmd"
# Purpose: upload a divoom16 image/animation and show it immediately.
# Packet format:
#   start: [0x00, total size LE32]
#          -> the APP MUST wait for the device reply [0x00, 0x01] ("start
#             sending data"; [0x00, 0x00] = cannot start, cancel) before data;
#   data:  [0x01, total size LE32, chunk index LE16, up to 256 bytes]
#          -> the device may ask for a chunk again with reply [0x01, index LE16];
#   terminate: [0x02] (optional, not sent by the working implementations).
# Source: official Divoom doc https://docin.divoom-gz.com/web/#/5/293
#         (ShowDoc page 293); chunking as in andreas-mausch src/lib.rs.
# Status: device reply [00 01] to the start packet observed on hardware 2026-10-05.
#         Sending data without waiting for it scrambled covers now and then.
ANIM_START, ANIM_DATA = 0, 1


def animation_start(divoom16_data: bytes) -> bytes:
    return build_frame(CMD_SEND_ANIMATION, struct.pack("<BI", ANIM_START, len(divoom16_data)))


def animation_chunks(divoom16_data: bytes) -> list[bytes]:
    size = len(divoom16_data)
    frames = []
    for index in range(0, size, ANIMATION_CHUNK):
        chunk = divoom16_data[index : index + ANIMATION_CHUNK]
        header = struct.pack("<BIH", ANIM_DATA, size, index // ANIMATION_CHUNK)
        frames.append(build_frame(CMD_SEND_ANIMATION, header + chunk))
    return frames


def send_animation(divoom16_data: bytes) -> list[bytes]:
    """All frames of an upload, for inspection. Real uploads must use
    DitooConnection.upload_animation, which waits for the device in between."""
    return [animation_start(divoom16_data)] + animation_chunks(divoom16_data)
