"""Engine: Spotify -> cover -> Ditoo, running in background threads.

Two threads, so neither HTTP nor Bluetooth ever blocks the GUI:
  * ditoo thread   — owns the DitooConnection; executes queued jobs, reconnects;
  * spotify thread — reads the current track: from the Windows media session
                     (local, once a second) or from the Spotify Web API (gently:
                     every 3 s while playing, 10 s otherwise - polling the API every
                     second around the clock got the app rate-limited for hours).

The Ditoo is left alone unless Spotify is playing: connecting sends nothing,
so the device's own buttons keep working while idle. The cover is sent when
playback starts or resumes, when the track changes, and when the Ditoo
(re)connects during playback. Resuming always re-sends, because the user may
have picked another picture on the device in the meantime.

When the music stops, the Ditoo is switched ONCE to the chosen idle channel
(clock by default) after a short grace period, so a quick pause does not make
the screen flicker. After that it is left alone again.

The GUI talks to the engine only through the public methods (thread-safe) and
receives events through listeners: listener(event_name, payload). Events:
  "ditoo"    (connected: bool, text: str)
  "spotify"  text: str
  "login"    logged_in: bool
  "track"    TrackInfo | None
  "display"  PIL.Image (16x16 preview of the current cover / test picture)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

import requests
from PIL import Image

from bluetooth import ditoo_commands as cmd
from bluetooth import divoom16
from bluetooth.connection import DitooConnection, DitooError, windows_sees_connected

from . import artwork
from .media_session import MediaSessionError, MediaSessionSource
from .models import TrackInfo
from .settings import CACHE_DIR, Settings
from .spotify import (SpotifyAuth, SpotifyAuthError, SpotifyClient, SpotifyError,
                      SpotifyRateLimited)

log = logging.getLogger(__name__)

Listener = Callable[[str, object], None]
DIAGNOSTIC_COLORS = (8, 32, 64, 100, 128, 129, 155, 178, 200, 230, 255, 256)
DIAGNOSTIC_STEP_S = 5.0
# Each RFCOMM attempt at a switched-off Ditoo pages it for ~2.6 s (radio busy, the
# worker blocked). So: right after start / losing it - every 3 s; later every 10 s.
# In between, Windows is asked for free whether the Ditoo is linked (its audio part
# reconnects on power-on), and then it is connected at once.
RECONNECT_FAST_S = 3.0
RECONNECT_SLOW_S = 10.0
RECONNECT_FAST_FOR_S = 60.0
JOB_WAIT_S = 1.0
MEDIA_POLL_S = 1.0       # local, free
API_POLL_PLAYING_S = 3.0
API_POLL_IDLE_S = 10.0
TRACK_SOURCES = {"media": "Приложение Spotify (медиасессия)", "api": "Spotify Web API"}


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._listeners: list[Listener] = []
        self._jobs: queue.Queue[Callable[[], None]] = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.http = requests.Session()

        # ditoo thread state
        self._conn: DitooConnection | None = None
        self._want_connected = bool(settings.ditoo_address)
        self._last_attempt = 0.0
        self._lost_at = time.monotonic()  # start counts as "just lost": fast retries first
        self._sent_cover: bytes | None = None  # cover last sent during this playback
        self._cover_shown = False  # our cover is on screen -> switch to idle mode later
        self._idle_since: float | None = None

        # spotify thread state
        self._auth: SpotifyAuth | None = None
        self._logged_in = SpotifyAuth.has_saved_login()
        self._track: TrackInfo | None = None
        self._cover: Image.Image | None = None  # full-size cover of the current track
        self._cover_track_id: str | None = None
        self._media = MediaSessionSource()
        self._wake = threading.Event()  # settings changed: poll again right away

    # ---- lifecycle -------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def start(self, *, music=True, bluetooth=True) -> None:
        targets = []
        if bluetooth:
            targets.append((self._ditoo_loop, "ditoo"))
        if music:
            targets.append((self._spotify_loop, "spotify"))
        for target, name in targets:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        if music:
            self._emit("login", self._logged_in)

    def mirror_playback(self, source: Engine) -> None:
        """Update a Bluetooth-only worker from the shared music worker."""
        from dataclasses import replace
        track = source._track
        cover = source.now_playing_cover()
        if track and track.album_art_url:
            track = replace(track, album_art_url=None)
        self._handle_track(track, cover[1] if cover and track and cover[0] == track.track_id else None)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=3)
        if self._conn:
            self._conn.disconnect()

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    @property
    def playing(self) -> bool:
        return (self.settings.show_artwork and self._track is not None
                and self._track.is_playing)

    def now_playing_cover(self) -> tuple[str, Image.Image] | None:
        """(track id, full-size cover) while Spotify is playing, else None."""
        track, cover = self._track, self._cover
        if not self.settings.show_artwork or track is None or not track.is_playing or cover is None:
            return None
        if self._cover_track_id != track.track_id:
            return None  # the new cover is still downloading
        return track.track_id, cover

    # ---- public API (any thread) ----------------------------------------

    def connect_ditoo(self, address: str) -> None:
        def job() -> None:
            if address != self.settings.ditoo_address:
                self.settings.ditoo_address, self.settings.ditoo_port = address, 0
                self.settings.save()
            self._want_connected = True
            self._connect()
        self._jobs.put(job)

    def wake_spotify(self) -> None:
        """Re-read the track now (source or account changed), even during a long back-off."""
        self._wake.set()

    def reconnect_ditoo(self) -> None:
        if self.settings.ditoo_address:
            self.connect_ditoo(self.settings.ditoo_address)

    def disconnect_ditoo(self) -> None:
        def job() -> None:
            self._want_connected = False
            self._drop_connection("Отключено")
        self._jobs.put(job)

    # Explicit user actions: always sent, regardless of playback.

    def apply_brightness(self) -> None:
        self._jobs.put(lambda: self._send(cmd.set_brightness(self.settings.brightness)))

    def show_image(self, image: Image.Image) -> None:
        def job() -> None:
            self._emit("display", image)
            self._sent_cover = None  # the cover is no longer on screen
            self._cover_shown = False
            self._upload(image)
        self._jobs.put(job)

    def show_test_pattern(self) -> None:
        self.show_image(artwork.test_pattern())

    def show_file(self, path: str) -> None:
        def job() -> None:
            with Image.open(path) as img:
                processed = self._process(img)
            self._emit("display", processed)
            self._sent_cover = None
            self._cover_shown = False
            self._upload(processed)
        self._jobs.put(job)

    def clear_display(self) -> None:
        self.show_image(Image.new("RGB", (artwork.DISPLAY_SIZE, artwork.DISPLAY_SIZE)))

    def set_display_mode(self, key: str) -> None:
        def job() -> None:
            self._cover_shown = False
            self._send(cmd.display_mode(key))
        self._jobs.put(job)

    def run_diagnostic(self) -> None:
        """Send rainbow test pictures with growing palettes, then the current
        cover, so the user can tell which uploads come out scrambled."""
        def job() -> None:
            self._cover_shown = False
            self._sent_cover = None
            steps = [(f"{n} цветов", artwork.diagnostic_pattern(n)) for n in DIAGNOSTIC_COLORS]
            if self._cover is not None:
                cover = self._process(self._cover)
                colors = len(set(cover.get_flattened_data()))
                steps.append((f"текущая обложка, {colors} цветов", cover))
            for i, (label, image) in enumerate(steps, 1):
                log.info("Диагностика: шаг %d из %d — %s", i, len(steps), label)
                self._emit("display", image)
                if not self._upload(image):
                    log.warning("Диагностика прервана: Ditoo не подключён")
                    return
                time.sleep(DIAGNOSTIC_STEP_S)
            log.info("Диагностика завершена")
        self._jobs.put(job)

    def keyboard_light(self, action: cmd.KeyboardLight) -> None:
        self._jobs.put(lambda: self._send(cmd.keyboard_light(action)))

    def refresh_artwork(self) -> None:
        """Re-render the cover after the artwork settings changed."""
        self._jobs.put(lambda: self._show_cover(force=False))

    def spotify_login(self) -> None:
        def run() -> None:
            try:
                self._emit("spotify", "Ожидание входа в браузере...")
                SpotifyAuth(self.settings.spotify_client_id, self.http).login()
                self._auth = None  # rebuild with fresh tokens
                self._set_logged_in(True)
            except SpotifyError as e:
                log.error("Spotify login failed: %s", e)
                self._emit("spotify", f"Ошибка входа: {e}")
        threading.Thread(target=run, name="spotify-login", daemon=True).start()

    def spotify_logout(self) -> None:
        SpotifyAuth.logout()
        self._auth = None
        self._set_logged_in(False)

    # ---- ditoo thread ----------------------------------------------------

    def _ditoo_loop(self) -> None:
        while not self._stop.is_set():
            self._check_idle()
            try:
                job = self._jobs.get(timeout=JOB_WAIT_S)
            except queue.Empty:
                job = None
            if job is not None:
                try:
                    job()
                except Exception:
                    log.exception("Ditoo job failed")
                continue

            if self._conn is not None and not self._conn.is_connected():
                self._drop_connection("Связь потеряна")
            if (self.settings.ditoo_enabled and self._conn is None and self._want_connected and self.settings.auto_reconnect
                    and self.settings.ditoo_address and self._reconnect_due()):
                self._connect(quiet=True)

    def _reconnect_due(self) -> bool:
        now = time.monotonic()
        since_attempt = now - self._last_attempt
        if since_attempt < RECONNECT_FAST_S:
            return False
        if now - self._lost_at < RECONNECT_FAST_FOR_S or since_attempt >= RECONNECT_SLOW_S:
            return True
        return windows_sees_connected(self.settings.ditoo_address) is True

    def _connect(self, quiet: bool = False) -> None:
        self._drop_connection(None)
        self._last_attempt = time.monotonic()
        address = self.settings.ditoo_address
        if not address:
            self._emit("ditoo", (False, "Устройство не выбрано"))
            return
        if not quiet:
            self._emit("ditoo", (False, f"Подключение к {address}..."))
        conn = DitooConnection(address, self.settings.ditoo_port or None)
        try:
            port = conn.connect()
        except DitooError as e:
            # Expected every few seconds while the Ditoo is switched off.
            (log.debug if quiet else log.warning)("Ditoo connect failed: %s", e)
            waiting = "Ожидание Ditoo (выключен или вне зоны)"
            self._emit("ditoo", (False, waiting if self.settings.auto_reconnect
                                 else "Не удалось подключиться"))
            return
        self._conn = conn
        if port != self.settings.ditoo_port:
            self.settings.ditoo_port = port
            self.settings.save()
        log.info("Ditoo connected (%s, channel %d)", address, port)
        self._emit("ditoo", (True, f"Подключено ({address}, канал {port})"))
        # Nothing is sent on connect, unless music is playing right now.
        self._show_cover(force=True)

    def _drop_connection(self, reason: str | None) -> None:
        if self._conn is not None:
            self._conn.disconnect()
            self._conn = None
            self._last_attempt = self._lost_at = time.monotonic()
            if reason:
                log.info("Ditoo: %s", reason)
        if reason:
            self._emit("ditoo", (False, reason))

    def _send(self, frames: bytes | list[bytes]) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.send(frames)
            return True
        except DitooError as e:
            log.warning("Ditoo send failed: %s", e)
            self._drop_connection("Связь потеряна")
            return False

    def _upload(self, image: Image.Image) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.upload_animation(divoom16.encode_image(image))
            return True
        except DitooError as e:
            log.warning("Image upload failed: %s", e)
            if not self._conn.is_connected():
                self._drop_connection("Связь потеряна")
            return False

    def _show_cover(self, force: bool) -> None:
        """Update the preview; send the cover to the Ditoo only while playing."""
        track, cover = self._track, self._cover
        if cover is None or track is None or self._cover_track_id != track.track_id:
            return
        image = self._process(cover)
        self._emit("display", image)
        if not self.playing:
            return
        data = image.tobytes()
        if (force or data != self._sent_cover) and self._upload(image):
            self._sent_cover = data
            self._cover_shown = True
            log.info("Cover sent to Ditoo (%d colours)", len(set(image.get_flattened_data())))

    def _process(self, img: Image.Image) -> Image.Image:
        s = self.settings
        return artwork.to_ditoo(img, s.contrast, s.saturation, s.art_brightness, s.max_colors)

    # ---- spotify thread --------------------------------------------------

    def _set_logged_in(self, value: bool) -> None:
        self._logged_in = value
        self._emit("login", value)
        self._emit("spotify", "Вход выполнен" if value else "Не выполнен вход")

    def _spotify_loop(self) -> None:
        last_status = ""
        while not self._stop.is_set():
            self._wake.clear()
            try:
                status, delay = self._spotify_tick()
            except Exception:
                log.exception("Music polling failed; retrying")
                status, delay = "Ошибка чтения трека, повтор через 5 с", 5.0
            if status and status != last_status:
                log.info("Music: %s", status)
                self._emit("spotify", status)
                last_status = status
            self._wake.wait(delay)

    def _spotify_tick(self) -> tuple[str, float]:
        s = self.settings
        if not s.show_artwork:
            self._handle_track(None)
            return "Интеграция на паузе", 1.0
        if s.track_source == "media":
            return self._media_tick()
        if not s.spotify_client_id:
            self._handle_track(None)
            return "Введите Client ID", 1.0
        if not self._logged_in:
            self._handle_track(None)
            return "Не выполнен вход", 1.0
        if self._auth is None or self._auth.client_id != s.spotify_client_id:
            self._auth = SpotifyAuth(s.spotify_client_id, self.http)
        try:
            track = SpotifyClient(self._auth).get_current_track()
        except SpotifyRateLimited as e:
            until = time.strftime("%H:%M", time.localtime(time.time() + e.retry_after))
            log.warning("Spotify API rate limit: retry after %.0f s (%s)", e.retry_after, until)
            return (f"Spotify ограничил запросы до {until}. Источник «Приложение Spotify» "
                    f"в Настройках работает без ограничений", e.retry_after)
        except SpotifyAuthError as e:
            log.warning("Spotify auth: %s", e)
            self._auth = None
            self._set_logged_in(False)
            return "Нужно войти заново", 1.0
        except SpotifyError as e:
            log.warning("%s", e)
            return "Spotify недоступен, повтор через 5 с", 5.0

        self._handle_track(track)
        if track is None:
            return "Ничего не играет", API_POLL_IDLE_S
        if track.is_playing:
            return "Играет", API_POLL_PLAYING_S
        return "Пауза", API_POLL_IDLE_S

    def _media_tick(self) -> tuple[str, float]:
        s = self.settings
        if not s.show_artwork:
            self._handle_track(None)
            return "Интеграция на паузе", 1.0
        try:
            track, cover = self._media.read(s.media_only_spotify, self._cover_track_id)
        except MediaSessionError as e:
            log.warning("%s", e)
            return str(e), 5.0
        self._handle_track(track, cover)
        if track is None:
            return ("Spotify не запущен" if s.media_only_spotify else "Ничего не играет"), MEDIA_POLL_S
        return ("Играет" if track.is_playing else "Пауза"), MEDIA_POLL_S

    def _handle_track(self, track: TrackInfo | None, cover: Image.Image | None = None) -> None:
        """`cover` comes with the track from the media session; the API gives a URL."""
        old = self._track
        was_playing = old is not None and old.is_playing
        changed = track is not None and (old is None or old.track_id != track.track_id)
        if changed:
            log.info("Track: %s — %s", track.artist_name, track.track_name)
            if cover is None and track.album_art_url:
                cover = self._download(track)
        # the media session may hand the cover over a moment after the title
        late = not changed and track is not None and self._cover_track_id != track.track_id
        fresh = cover is not None and (changed or late)
        if fresh:
            self._cover = cover
            self._cover_track_id = track.track_id
        self._track = track
        # Emitted after the state is updated, so listeners (the Times Gate centre
        # screen) read the new track together with its cover.
        if ((old is None) != (track is None) or changed or (late and fresh)
                or (old and track and old.is_playing != track.is_playing)):
            self._emit("track", track)

        now_playing = track is not None and track.is_playing
        ready = track is not None and self._cover_track_id == track.track_id
        if now_playing and ready and (changed or not was_playing or (late and fresh)):
            if not was_playing:
                log.info("Playback started")
            self._jobs.put(lambda: self._show_cover(force=True))
        elif was_playing and not now_playing:
            log.info("Playback stopped: leaving the Ditoo alone")

    def _check_idle(self) -> None:
        """Once the music has been stopped for idle_delay_s, show the idle channel."""
        if not self._cover_shown or self.playing:
            self._idle_since = None
            return
        now = time.monotonic()
        if self._idle_since is None:
            self._idle_since = now
            return
        if now - self._idle_since < self.settings.idle_delay_s:
            return
        self._idle_since = None
        self._cover_shown = False
        mode = self.settings.idle_mode
        if mode in cmd.DISPLAY_MODES and mode != "keep":
            log.info("Music stopped: switching the Ditoo to '%s'", cmd.DISPLAY_MODES[mode][0])
            self._jobs.put(lambda: self._send(cmd.display_mode(mode)) if not self.playing else None)

    def _download(self, track: TrackInfo) -> Image.Image | None:
        if not track.album_art_url:
            return None  # local file without cover: keep the last picture
        try:
            return artwork.fetch_cover(track.album_art_url, CACHE_DIR, self.http)
        except (requests.RequestException, OSError) as e:
            log.warning("Cover download failed: %s", e)
            return None

    # ---- events ----------------------------------------------------------

    def _emit(self, name: str, payload: object) -> None:
        for listener in self._listeners:
            try:
                listener(name, payload)
            except Exception:
                log.exception("Listener failed for %s", name)
