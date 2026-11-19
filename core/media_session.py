"""Current track from the Windows media session (System Media Transport Controls).

The Spotify desktop app publishes title, artist, album, play state and a 300x300
cover to Windows - the same data the volume flyout shows. Reading it is local:
no internet, no Spotify account, no API rate limits, and it reacts at once.
Checked on the user's PC 2026-10-05: Spotify.exe session, PNG cover 300x300.

Other players (browsers, etc.) publish sessions too; by default only Spotify's
is used.

Cost per poll is kept tiny: one long-lived worker thread with its own event loop
and session manager, and the cover is read and decoded only while the engine
still needs it for the current track (not every second).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import io
import logging
import threading
import time

from PIL import Image

from .models import TrackInfo

log = logging.getLogger(__name__)

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
TIMEOUT_S = 5.0
THUMB_LAG_S = 2.0  # same cover for longer than this: the next track really has it (same album)


class MediaSessionError(Exception):
    pass


def available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("winrt.windows.media.control") is not None
    except ImportError:
        return False


def _is_spotify(app_id: str) -> bool:
    return "spotify" in (app_id or "").lower()


def _track_id(app: str, artist: str, album: str, title: str) -> str:
    key = "\n".join((app, artist, album, title))
    return "smtc:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


_manager = None  # lives on the worker loop


async def _session(only_spotify: bool):
    global _manager
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as Manager

    if _manager is None:
        _manager = await Manager.request_async()
    sessions = list(_manager.get_sessions())
    if only_spotify:
        sessions = [s for s in sessions if _is_spotify(s.source_app_user_model_id)]
    else:  # the session Windows considers current first, then any playing one
        current = _manager.get_current_session()
        sessions.sort(key=lambda s: (s.get_playback_info().playback_status != PLAYING,
                                     current is None or s.source_app_user_model_id
                                     != current.source_app_user_model_id))
    return sessions[0] if sessions else None


async def _read(only_spotify: bool, have_cover_for: str | None) -> tuple[TrackInfo, bytes | None] | None:
    """(track, cover bytes). The cover is read only if `have_cover_for` is another track."""
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    session = await _session(only_spotify)
    if session is None:
        return None
    props = await session.try_get_media_properties_async()
    if not props or not props.title:
        return None
    timeline = session.get_timeline_properties()
    track = TrackInfo(
        is_playing=session.get_playback_info().playback_status == PLAYING,
        track_id=_track_id(session.source_app_user_model_id, props.artist, props.album_title, props.title),
        track_name=props.title,
        artist_name=props.artist,
        album_name=props.album_title,
        album_art_url=None,
        progress_ms=int(timeline.position.total_seconds() * 1000) if timeline else 0,
        duration_ms=int(timeline.end_time.total_seconds() * 1000) if timeline else 0,
    )
    data = None
    if props.thumbnail and track.track_id != have_cover_for:
        stream = await props.thumbnail.open_read_async()
        buf = Buffer(stream.size)
        await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
        data = bytes(buf)
    return track, data


class _Worker:
    """One daemon thread running an event loop for all WinRT calls. In a COM
    single-threaded apartment (the Qt GUI thread) they never complete - checked
    2026-10-05 - so they never run on the caller's thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                loop = asyncio.new_event_loop()
                started = threading.Event()
                loop.call_soon(started.set)
                threading.Thread(target=loop.run_forever, name="media-session", daemon=True).start()
                started.wait(TIMEOUT_S)
                self._loop = loop
            return self._loop

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop())
        try:
            return future.result(TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            future.cancel()
            global _manager
            _manager = None  # ask Windows for a fresh manager next time
            raise MediaSessionError("Медиасессия Windows не отвечает") from None


_worker = _Worker()


def control_playback(action: str, only_spotify: bool) -> bool:
    async def control():
        session = await _session(only_spotify)
        if session is None:
            return False
        operations = {
            "previous": session.try_skip_previous_async,
            "toggle": session.try_toggle_play_pause_async,
            "next": session.try_skip_next_async,
        }
        return await operations[action]()

    return _worker.run(control())


class MediaSessionSource:
    """Polled once a second by the engine's music thread."""

    def __init__(self) -> None:
        self._last_thumb: bytes | None = None  # cover bytes handed out last (previous track)
        self._pending: str | None = None       # track waiting for its own cover
        self._changed_at = 0.0

    def read(self, only_spotify: bool = True,
             have_cover_for: str | None = None) -> tuple[TrackInfo | None, Image.Image | None]:
        """(track, cover). The cover comes only while the caller has none for this
        track, and not while Windows still holds the previous track's one: right
        after a change the thumbnail lags behind the title."""
        global _manager
        try:
            result = _worker.run(_read(only_spotify, have_cover_for))
        except MediaSessionError:
            raise
        except ImportError as e:
            raise MediaSessionError("Нет модулей winrt для медиасессии") from e
        except OSError as e:  # COM / WinRT errors: start over with a new manager
            _manager = None
            raise MediaSessionError(f"Медиасессия недоступна: {e}") from e
        if result is None:
            return None, None
        track, data = result
        if not data:
            return track, None
        if track.track_id != self._pending:
            self._pending, self._changed_at = track.track_id, time.monotonic()
        if data == self._last_thumb and time.monotonic() - self._changed_at < THUMB_LAG_S:
            return track, None  # most likely still the previous track's cover
        try:
            cover = Image.open(io.BytesIO(data)).convert("RGB")
        except OSError:
            return track, None
        self._last_thumb = data
        return track, cover
