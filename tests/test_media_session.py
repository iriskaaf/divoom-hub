"""Windows media session source: the cover lags behind the title after a change."""

import io

from PIL import Image

from core import media_session
from core.models import TrackInfo


def png(color):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def feed(monkeypatch, items):
    queue = list(items)

    async def fake(only_spotify, have_cover_for):
        tid, data = queue.pop(0)
        return TrackInfo(True, tid, "t", "a", "al", None, 0, 1), data
    monkeypatch.setattr(media_session, "_read", fake)


def test_old_cover_is_not_taken_for_the_new_track(monkeypatch):
    src = media_session.MediaSessionSource()
    red, blue = png((255, 0, 0)), png((0, 0, 255))
    feed(monkeypatch, [("a", red), ("b", red), ("b", blue)])
    assert src.read()[1].getpixel((0, 0)) == (255, 0, 0)
    assert src.read()[1] is None                          # "b" still shows a's cover
    assert src.read()[1].getpixel((0, 0)) == (0, 0, 255)  # now it is b's own


def test_same_album_cover_is_accepted_after_a_moment(monkeypatch):
    src = media_session.MediaSessionSource()
    red = png((255, 0, 0))
    feed(monkeypatch, [("a", red), ("b", red), ("b", red)])
    src.read()
    assert src.read()[1] is None
    monkeypatch.setattr(media_session, "THUMB_LAG_S", 0.0)
    assert src.read()[1] is not None


def test_nothing_playing(monkeypatch):
    async def none(only_spotify, have_cover_for):
        return None
    monkeypatch.setattr(media_session, "_read", none)
    assert media_session.MediaSessionSource().read() == (None, None)


def test_cover_is_not_read_while_the_caller_has_it(monkeypatch):
    asked = []

    async def fake(only_spotify, have_cover_for):
        asked.append(have_cover_for)
        data = None if have_cover_for == "a" else png((255, 0, 0))
        return TrackInfo(True, "a", "t", "a", "al", None, 0, 1), data
    monkeypatch.setattr(media_session, "_read", fake)
    src = media_session.MediaSessionSource()
    assert src.read(True, None)[1] is not None
    assert src.read(True, "a")[1] is None and asked == [None, "a"]


def test_a_stuck_call_times_out(monkeypatch):
    import asyncio

    async def stuck(only_spotify, have_cover_for):
        await asyncio.sleep(60)
    monkeypatch.setattr(media_session, "_read", stuck)
    monkeypatch.setattr(media_session, "TIMEOUT_S", 0.2)
    import pytest
    with pytest.raises(media_session.MediaSessionError):
        media_session.MediaSessionSource().read()
