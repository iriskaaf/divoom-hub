"""0x8B upload handshake (official Divoom doc, ShowDoc page 293)."""

import struct

from bluetooth import ditoo_commands as cmd
from bluetooth.connection import DitooConnection, DitooError
from bluetooth.protocol import FrameParser, Reply

import pytest


class FakeDevice:
    """Records what the connection sends and answers like a Ditoo."""

    def __init__(self, conn, ready=1, resend=()):
        self.conn, self.ready, self.resend = conn, ready, list(resend)
        self.sent = []

    def send(self, frames):
        frames = [frames] if isinstance(frames, bytes) else list(frames)
        for frame in frames:
            parsed = FrameParser().feed(frame)[0]
            self.sent.append(parsed)
            control = parsed.payload[0]
            if control == cmd.ANIM_START and self.ready is not None:
                self.reply(bytes([0, self.ready]))
            elif control == cmd.ANIM_DATA and self.resend:
                index = struct.unpack_from("<H", parsed.payload, 5)[0]
                if index == self.resend[0][0]:
                    self.reply(bytes([1]) + struct.pack("<H", self.resend.pop(0)[1]))

    def reply(self, data):
        self.conn._replies.put(Reply(cmd.CMD_SEND_ANIMATION, True, data))

    def chunk_indices(self):
        return [struct.unpack_from("<H", f.payload, 5)[0] for f in self.sent
                if f.payload[0] == cmd.ANIM_DATA]


@pytest.fixture
def conn(monkeypatch):
    c = DitooConnection("AA:BB:CC:DD:EE:FF", 2)
    c.UPLOAD_READY_TIMEOUT = 0.2
    c.UPLOAD_RESEND_WINDOW = 0.05
    return c


DATA = bytes(range(256)) * 3 + b"tail"  # 4 chunks


def test_waits_for_ready_then_sends_all_chunks(conn, monkeypatch):
    dev = FakeDevice(conn)
    monkeypatch.setattr(conn, "send", dev.send)
    conn.upload_animation(DATA)
    assert dev.sent[0].payload[0] == cmd.ANIM_START
    assert dev.chunk_indices() == [0, 1, 2, 3]


def test_serves_resend_request(conn, monkeypatch):
    dev = FakeDevice(conn, resend=[(3, 1)])  # after chunk 3 the device asks for chunk 1
    monkeypatch.setattr(conn, "send", dev.send)
    conn.upload_animation(DATA)
    assert dev.chunk_indices() == [0, 1, 2, 3, 1]


def test_refused_upload_raises(conn, monkeypatch):
    dev = FakeDevice(conn, ready=0)
    monkeypatch.setattr(conn, "send", dev.send)
    with pytest.raises(DitooError):
        conn.upload_animation(DATA)
    assert dev.chunk_indices() == []


def test_no_ready_reply_still_sends(conn, monkeypatch):
    dev = FakeDevice(conn, ready=None)
    monkeypatch.setattr(conn, "send", dev.send)
    conn.upload_animation(DATA)
    assert dev.chunk_indices() == [0, 1, 2, 3]
