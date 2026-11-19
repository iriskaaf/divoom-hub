"""Verify the cover replacement using the real Python engines with a synthetic track."""
import base64
import io
import sys
from dataclasses import replace
from datetime import datetime

from PIL import Image

sys.path.insert(0, sys.argv[1])
import worker
from worker import Hub, decode_settings
from core.models import TrackInfo
from core.player import Engine
from timesgate.client import TimesGateClient
from timesgate.engine import TimesGateEngine


class Capture(TimesGateClient):
    def __init__(self):
        super().__init__("127.0.0.1", "123456")
        self.payloads = []

    def command(self, payload):
        self.payloads.append(payload)
        return {}


def main():
    hub = Hub()
    hub.settings = decode_settings({"tg_center_cover": True, "show_artwork": True})
    hub.engine = Engine(hub.settings)
    hub.gate = TimesGateEngine(hub.settings, clock=lambda: datetime(2026, 1, 1, 12, 34),
                               cover_provider=hub.engine.now_playing_cover)
    hub.engine.add_listener(hub.event)
    events = []
    worker.send = lambda **message: events.append(message)
    wire = Capture()

    hub.gate._update_screens(wire)
    original = [m for m in wire.payloads if m["LcdArray"] == [0, 0, 1, 0, 0]][0]["PicData"]

    track = TrackInfo(True, "smoke-track", "Test track", "Test artist", "Test album", None, 0, 30000)
    album = Image.new("RGB", (320, 320), (225, 34, 65))
    hub.engine._handle_track(track, album)
    assert events[-1]["data"]["cover"].startswith("iVBOR")
    wire.payloads.clear()
    hub.gate._update_screens(wire)
    assert len(wire.payloads) == 1 and wire.payloads[0]["LcdArray"] == [0, 0, 1, 0, 0]
    pixels = Image.open(io.BytesIO(base64.b64decode(wire.payloads[0]["PicData"])))
    assert pixels.size == (128, 128) and pixels.getpixel((64, 64))[0] > 210

    wire.payloads.clear()
    hub.gate._update_screens(wire)
    assert wire.payloads == []
    hub.engine._handle_track(replace(track, is_playing=False))
    assert events[-1]["data"]["cover"] is None
    hub.gate._update_screens(wire)
    assert all(m["LcdArray"] == [0, 0, 1, 0, 0] for m in wire.payloads)
    assert wire.payloads[0]["PicData"] == original
    print("PASS: cover replaces the colon only on LCD 3, stays cached, and gives way to the colon on pause")


if __name__ == "__main__":
    main()
