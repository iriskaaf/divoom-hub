"""The Ditoo must stay untouched unless Spotify is playing."""

import pytest
from PIL import Image

from bluetooth import ditoo_commands as cmd
from bluetooth.protocol import FrameParser
from core import player
from core.models import TrackInfo
from core.settings import Settings


class FakeConn:
    def __init__(self):
        self.frames = []

    def send(self, frames):
        self.frames.extend([frames] if isinstance(frames, bytes) else frames)

    def is_connected(self):
        return True

    def upload_animation(self, data):
        self.frames.extend(cmd.send_animation(data))

    def commands(self):
        return [f.command for f in FrameParser().feed(b"".join(self.frames))]

    def images_sent(self):
        # an image upload starts with a 0x8B frame whose control byte is 0
        return sum(1 for f in FrameParser().feed(b"".join(self.frames))
                   if f.command == cmd.CMD_SEND_ANIMATION and f.payload[0] == 0)


def track(track_id="a", playing=True):
    return TrackInfo(playing, track_id, "Song", "Artist", "Album", f"http://x/{track_id}", 0, 1)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(player.SpotifyAuth, "has_saved_login", staticmethod(lambda: False))
    monkeypatch.setattr(Settings, "save", lambda self, path=None: None)
    e = player.Engine(Settings(ditoo_address="AA:BB:CC:DD:EE:FF"))
    covers = {"a": (200, 0, 0), "b": (0, 0, 200)}
    monkeypatch.setattr(e, "_download", lambda t: Image.new("RGB", (64, 64), covers[t.track_id]))
    e._conn = FakeConn()
    return e


def step(engine, t):
    engine._handle_track(t)
    while not engine._jobs.empty():
        engine._jobs.get_nowait()()


def test_idle_sends_nothing(engine):
    step(engine, None)
    step(engine, track("a", playing=False))
    step(engine, None)
    assert engine._conn.frames == []


def test_cover_sent_once_per_track(engine):
    step(engine, track("a"))
    step(engine, track("a"))
    step(engine, track("a"))
    assert engine._conn.images_sent() == 1
    step(engine, track("b"))
    assert engine._conn.images_sent() == 2


def test_pause_leaves_device_alone_and_resume_resends(engine):
    step(engine, track("a"))
    step(engine, track("a", playing=False))
    step(engine, track("a", playing=False))
    assert engine._conn.images_sent() == 1
    step(engine, track("a"))  # user may have changed the picture meanwhile
    assert engine._conn.images_sent() == 2


def test_track_change_while_paused_is_not_sent(engine):
    step(engine, track("a", playing=False))
    step(engine, track("b", playing=False))
    assert engine._conn.frames == []
    step(engine, track("b"))
    assert engine._conn.images_sent() == 1


def test_connecting_while_idle_sends_nothing(engine, monkeypatch):
    monkeypatch.setattr(player.DitooConnection, "connect", lambda self, timeout=8.0: 2)
    sent = []
    monkeypatch.setattr(player.DitooConnection, "send", lambda self, f: sent.append(f))
    monkeypatch.setattr(player.DitooConnection, "upload_animation", lambda self, d: sent.append(d))
    engine._conn = None
    engine._connect()
    assert sent == []


def test_connecting_while_playing_sends_cover(engine, monkeypatch):
    step(engine, track("a"))
    monkeypatch.setattr(player.DitooConnection, "connect", lambda self, timeout=8.0: 2)
    monkeypatch.setattr(player.DitooConnection, "disconnect", lambda self: None)
    sent = []
    monkeypatch.setattr(player.DitooConnection, "upload_animation", lambda self, d: sent.append(d))
    engine._conn = None
    engine._connect()
    assert len(sent) == 1  # one image upload


def test_integration_paused_sends_nothing(engine):
    engine.settings.show_artwork = False
    step(engine, track("a"))
    assert engine._conn.frames == []


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(player.time, "monotonic", c)
    return c


def tick(engine, clock, seconds=1.0):
    clock.t += seconds
    engine._check_idle()
    while not engine._jobs.empty():
        engine._jobs.get_nowait()()


def box_modes(engine):
    return [f.payload for f in FrameParser().feed(b"".join(engine._conn.frames))
            if f.command == cmd.CMD_SET_BOX_MODE]


def test_switches_to_clock_once_after_music_stops(engine, clock):
    engine.settings.idle_delay_s = 5
    step(engine, track("a"))
    step(engine, track("a", playing=False))
    for _ in range(4):
        tick(engine, clock)
    assert box_modes(engine) == []          # grace period
    for _ in range(10):
        tick(engine, clock)
    assert box_modes(engine) == [bytes([0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00])]


def test_short_pause_does_not_switch(engine, clock):
    step(engine, track("a"))
    step(engine, track("a", playing=False))
    tick(engine, clock, 2)
    step(engine, track("a"))
    tick(engine, clock, 2)
    step(engine, track("a", playing=False))
    tick(engine, clock, 2)
    assert box_modes(engine) == []


def test_keep_mode_and_idle_start_do_nothing(engine, clock):
    step(engine, None)                      # app started while idle
    for _ in range(10):
        tick(engine, clock)
    assert engine._conn.frames == []
    engine.settings.idle_mode = "keep"
    step(engine, track("a"))
    step(engine, None)
    for _ in range(10):
        tick(engine, clock)
    assert box_modes(engine) == []


def test_favorite_tab_uses_extended_command(engine):
    frames = FrameParser().feed(b"".join(cmd.display_mode("favorite2")))
    assert [(f.command, f.payload) for f in frames] == [(0x45, b"\x05"), (0xBD, b"\x17\x01")]


def media_track(track_id="m", playing=True):
    return TrackInfo(playing, track_id, "Song", "Artist", "Album", None, 0, 1)


def test_media_session_cover_arriving_late_is_sent_once_it_comes(engine):
    events = []
    engine.add_listener(lambda name, payload: events.append(name))
    engine._handle_track(media_track(), None)             # title first, cover not yet
    assert engine._jobs.empty() and engine.now_playing_cover() is None
    engine._handle_track(media_track(), Image.new("RGB", (64, 64), (0, 200, 0)))
    while not engine._jobs.empty():
        engine._jobs.get_nowait()()
    assert engine._conn.images_sent() == 1
    assert engine.now_playing_cover()[0] == "m" and events.count("track") == 2
    engine._handle_track(media_track(), Image.new("RGB", (64, 64), (0, 200, 0)))  # same again
    assert engine._jobs.empty()


def test_media_source_is_used_without_spotify_account(engine, monkeypatch):
    engine.settings.track_source = "media"
    monkeypatch.setattr(engine._media, "read", lambda only_spotify, have: (media_track(), None))
    assert engine._spotify_tick()[0] == "Играет"
    engine.settings.track_source = "api"
    engine.settings.spotify_client_id = ""
    assert engine._spotify_tick()[0] == "Введите Client ID"


def test_api_rate_limit_waits_and_says_why(engine, monkeypatch):
    engine.settings.track_source, engine.settings.spotify_client_id = "api", "cid"
    engine._logged_in = True

    def limited(self):
        raise player.SpotifyRateLimited(3600)
    monkeypatch.setattr(player.SpotifyClient, "get_current_track", limited)
    status, delay = engine._spotify_tick()
    assert delay == 3600 and "ограничил" in status


def test_ditoo_reconnect_backs_off_but_follows_windows(engine, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(player.time, "monotonic", lambda: clock[0])
    seen = [False]
    monkeypatch.setattr(player, "windows_sees_connected", lambda address: seen[0])
    engine._lost_at, engine._last_attempt = 1000.0, 1000.0
    clock[0] = 1002.0
    assert not engine._reconnect_due()                 # never more often than every 3 s
    clock[0] = 1003.5
    assert engine._reconnect_due()                     # first minute: fast retries
    engine._last_attempt = clock[0] = 1100.0
    clock[0] = 1104.0
    assert not engine._reconnect_due()                 # later: radio left alone...
    seen[0] = True
    assert engine._reconnect_due()                     # ...unless Windows already sees the Ditoo
    seen[0] = False
    clock[0] = 1110.5
    assert engine._reconnect_due()                     # and still tried every 10 s
