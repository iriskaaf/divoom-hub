"""Divoom serial (SPP) framing used by the Ditoo Pro.

Ditoo Pro protocol framing:
  Purpose:  wraps every command sent over RFCOMM and every reply received.
  Packet format (request):
      0x01 | length LE16 | command | payload... | checksum LE16 | 0x02
      length   = len(payload) + 3        (command byte + 2 checksum bytes)
      checksum = sum(length_lo, length_hi, command, *payload) & 0xFFFF
  Packet format (reply):
      0x01 | length LE16 | 0x04 | original command | ack (0x55 = ACK) | data... | checksum LE16 | 0x02
  The Ditoo family does NOT use the 0x03-escaping of 0x01/0x02/0x03 bytes
  that older Timebox models need.
  Source:
      andreas-mausch/divoom-ditoo-pro-controller  src/protocol/packet.rs
      futpib/divoom-ditoo-pro-controller           src/protocol/packet.rs (Response)
      d03n3rfr1tz3/hass-divoom                     devices/ditoo.py (escapePayload=False)
  Status: framing checked against the captured "alarm off" packet from the
  andreas-mausch README (see tests/test_protocol.py).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

START = 0x01
END = 0x02
REPLY_COMMAND = 0x04
ACK = 0x55


def checksum(data: bytes) -> int:
    return sum(data) & 0xFFFF


def build_frame(command: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<HB", len(payload) + 3, command) + bytes(payload)
    return bytes([START]) + body + struct.pack("<H", checksum(body)) + bytes([END])


@dataclass(frozen=True)
class Reply:
    command: int  # the command this reply answers
    ack: bool
    data: bytes


@dataclass(frozen=True)
class Frame:
    command: int
    payload: bytes

    def as_reply(self) -> Reply | None:
        if self.command != REPLY_COMMAND or len(self.payload) < 2:
            return None
        return Reply(self.payload[0], self.payload[1] == ACK, self.payload[2:])


class FrameParser:
    """Incremental parser for the byte stream coming back from the device.

    Garbage and corrupted frames are skipped byte by byte, so a single bad
    byte never desynchronises the stream permanently.
    """

    MAX_LENGTH = 4096

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buf.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buf.find(START)
            if start < 0:
                self._buf.clear()
                return frames
            del self._buf[:start]
            if len(self._buf) < 3:
                return frames
            length = struct.unpack_from("<H", self._buf, 1)[0]
            if length < 3 or length > self.MAX_LENGTH:
                del self._buf[0]
                continue
            total = length + 4
            if len(self._buf) < total:
                return frames
            raw = bytes(self._buf[:total])
            body = raw[1:-3]
            expected = struct.unpack_from("<H", raw, total - 3)[0]
            if raw[-1] != END or checksum(body) != expected:
                del self._buf[0]
                continue
            del self._buf[:total]
            frames.append(Frame(body[2], body[3:]))
