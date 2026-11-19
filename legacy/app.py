"""Divoom Hub — entry point.

    python app.py                        open the window (settings + all functions)

Diagnostics from the command line:

    python app.py --scan                 list paired Divoom devices
    python app.py --probe                connect and check two-way communication
    python app.py --test-display         send a test pattern
    python app.py --test-led             try the keyboard-light commands
    python app.py --brightness 40        set display brightness
    python app.py --image cover.jpg      send any picture
    python app.py --spotify-test         log in to Spotify and show the current track
    python app.py --spotify-logout       forget the saved Spotify login

Every hardware test asks you what the device actually did and logs the
answer as VERIFIED / FAILED, because a successful socket write proves nothing.
The first successful connection saves the device address, so --mac is only
needed once.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Started with another Python (e.g. VS Code "Run" with the system interpreter)?
# Re-run inside the project's virtual environment, where the dependencies are.
_VENV_PY = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
if (not getattr(sys, "frozen", False) and _VENV_PY.exists()
        and Path(sys.prefix).resolve() != _VENV_PY.parent.parent.resolve()):
    sys.exit(subprocess.call([str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))

import argparse  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

from PIL import Image  # noqa: E402

from bluetooth import ditoo_commands as cmd  # noqa: E402
from bluetooth import divoom16  # noqa: E402
from bluetooth.connection import BtDevice, DitooConnection, DitooError  # noqa: E402
from core import artwork  # noqa: E402
from core.settings import APP_DIR, Settings  # noqa: E402

log = logging.getLogger("divoomhub")


LOG_MAX_BYTES = 1_000_000  # app.log + 2 old parts: at most ~3 MB on disk
LOG_BACKUPS = 2


def setup_logging(verbose: bool) -> None:
    """INFO to a size-limited file (DEBUG only with --verbose). The old unlimited
    DEBUG log grew to 190 MB: a line every second from asyncio and the PNG decoder."""
    from logging.handlers import RotatingFileHandler

    log_dir = APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "app.log"
    try:
        if path.stat().st_size > LOG_MAX_BYTES * 4:  # left over from an old version
            path.unlink()
            for old in log_dir.glob("app.log.*"):
                old.unlink()
    except OSError:
        pass
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                       encoding="utf-8", delay=True)
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr:  # None under pythonw.exe
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        console.setLevel(logging.DEBUG if verbose else logging.INFO)
        handlers.append(console)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers)
    for noisy in ("urllib3", "keyring", "PIL", "asyncio", "win32ctypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def ask(question: str) -> bool:
    try:
        return input(f"  ? {question} [y/n] ").strip().lower().startswith(("y", "д"))
    except EOFError:
        return False


def record(test: str, ok: bool) -> None:
    log.info("%s: %s", test, "VERIFIED on hardware" if ok else "FAILED / not observed")


# ---- Ditoo ---------------------------------------------------------------

def pick_device(address: str | None, settings: Settings) -> BtDevice:
    if address:
        return BtDevice("manual", address)
    if settings.ditoo_address:
        return BtDevice("saved", settings.ditoo_address)
    devices = DitooConnection.scan()
    if len(devices) == 1:
        return devices[0]
    if not devices:
        sys.exit("No paired Divoom device. Pair 'DitooPro-Audio' in Windows Bluetooth "
                 "settings, or pass --mac AA:BB:CC:DD:EE:FF")
    names = "\n".join(f"  {d.address}  {d.name}" for d in devices)
    sys.exit(f"Several Divoom devices are paired, choose one with --mac:\n{names}")


def cmd_scan(include_all: bool) -> None:
    devices = DitooConnection.scan(include_all)
    if not devices:
        print("No paired Divoom devices found (use --all to list every paired device).")
    for d in devices:
        print(f"{d.address}  {d.name}")


def run_hardware(args: argparse.Namespace, settings: Settings) -> None:
    device = pick_device(args.mac, settings)
    port = args.port or (settings.ditoo_port if device.address == settings.ditoo_address else 0)
    conn = DitooConnection(device.address, port or None)
    log.info("Connecting to %s (%s)...", device.name, device.address)
    port = conn.connect()
    if (settings.ditoo_address, settings.ditoo_port) != (device.address, port):
        settings.ditoo_address, settings.ditoo_port = device.address, port
        settings.save()
        log.info("Saved device %s, RFCOMM channel %d", device.address, port)
    try:
        if args.probe:
            reply = conn.request(cmd.get_volume(), cmd.CMD_GET_VOLUME)
            record("Two-way RFCOMM (GET_VOLUME reply)", reply is not None)
            if reply:
                print(f"Device volume: {reply.data[0] if reply.data else '?'}")

        if args.brightness is not None:
            conn.send(cmd.set_brightness(args.brightness))
            record(f"SET_BRIGHTNESS {args.brightness}", ask("Did the brightness change?"))

        if args.test_display:
            conn.send(cmd.set_datetime())
            conn.upload_animation(divoom16.encode_image(artwork.test_pattern()))
            record("Display test pattern", ask(
                "Do you see red (top-left), green (top-right), blue (bottom-left), "
                "white (bottom-right) and one yellow pixel in the top-left corner?"))

        if args.image:
            img = artwork.to_ditoo(Image.open(args.image))
            conn.upload_animation(divoom16.encode_image(img))
            record(f"Display image {args.image}", ask("Is the picture on the display?"))

        if args.test_led:
            for action in (cmd.KeyboardLight.TOGGLE, cmd.KeyboardLight.TOGGLE,
                           cmd.KeyboardLight.NEXT, cmd.KeyboardLight.PREV):
                conn.send(cmd.keyboard_light(action))
                time.sleep(0.3)
                record(f"Keyboard light {action.name} (0x23 {int(action):02X})",
                       ask(f"Sent {action.name}. Did the keyboard lighting change?"))
    finally:
        conn.disconnect()


# ---- Spotify -------------------------------------------------------------

def run_spotify_test(client_id: str | None, settings: Settings) -> None:
    from core.spotify import (REDIRECT_URI, SpotifyAuth, SpotifyAuthError, SpotifyClient,
                              SpotifyError, SpotifyRateLimited)

    if client_id:
        settings.spotify_client_id = client_id.strip()
        settings.save()
    if not settings.spotify_client_id:
        print(f"Spotify app Redirect URI must be exactly: {REDIRECT_URI}")
        settings.spotify_client_id = input("Paste your Spotify Client ID: ").strip()
        if not settings.spotify_client_id:
            sys.exit("No Client ID entered.")
        settings.save()

    auth = SpotifyAuth(settings.spotify_client_id)
    if not auth.has_saved_login():
        print("A browser window will open. Log in to Spotify and press 'Agree'.")
        auth.login()
    client = SpotifyClient(auth)

    print("Watching playback, press Ctrl+C to stop.")
    last: tuple | None = None
    try:
        while True:
            try:
                track = client.get_current_track()
            except SpotifyRateLimited as e:
                log.warning("%s", e)
                time.sleep(e.retry_after)
                continue
            except SpotifyAuthError as e:
                log.error("%s", e)
                sys.exit("Run --spotify-test again to log in, or check the Client ID.")
            except SpotifyError as e:
                log.error("%s", e)
                time.sleep(5)
                continue
            state = (track.track_id, track.is_playing) if track else None
            if state != last:
                last = state
                if track is None:
                    log.info("Spotify: nothing playing")
                else:
                    log.info("Spotify: %s %s — %s [%s]  cover: %s",
                             "▶" if track.is_playing else "⏸", track.artist_name,
                             track.track_name, track.album_name, track.album_art_url)
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def run_self_test() -> int:
    """Packaging check for the built .exe: every dependency loads and works.
    Touches neither the Ditoo nor the Spotify account (read-only checks)."""
    import socket

    import keyring
    import requests
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from core.spotify import SpotifyAuth
    from gui.tray import app_icon

    from core.profile import PROFILE_NAME
    results: dict[str, object] = {"profile": PROFILE_NAME}
    checks = {
        "keyring": lambda: type(keyring.get_keyring()).__name__,
        "spotify_login_saved": SpotifyAuth.has_saved_login,
        "media_session": lambda: (lambda t: t[0].track_name if t[0] else "no session")(
            __import__("core.media_session", fromlist=["x"]).MediaSessionSource().read()),
        "https": lambda: requests.get("https://accounts.spotify.com", timeout=10).status_code,
        "rfcomm": lambda: socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                        socket.BTPROTO_RFCOMM).close() or "ok",
        "paired_divoom": lambda: len(DitooConnection.scan()),
        "image": lambda: len(cmd.send_animation(divoom16.encode_image(artwork.test_pattern()))),
    }
    app = QApplication.instance() or QApplication([])
    checks["tray"] = QSystemTrayIcon.isSystemTrayAvailable
    checks["fluent_ui"] = lambda: __import__("gui.main_window").__name__ and "ok"
    checks["timesgate_render"] = lambda: __import__("timesgate.digits", fromlist=["x"]).render(
        "neon", "8", "#FF2BD6", "#000000").size
    checks["icon"] = lambda: not app_icon().isNull()
    def check_card_artwork():
        from gui.assets import TILE_ARTWORK, tile_icon
        for key in TILE_ARTWORK:
            pix = tile_icon(key).pixmap(64, 64)
            if pix.isNull():
                return False
            image = pix.toImage()
            if not any(image.pixelColor(x, y).alpha()
                       for y in range(image.height()) for x in range(image.width())):
                return False
        return True
    checks["card_artwork"] = check_card_artwork

    def render_window() -> str:
        """Builds and paints the whole window off-screen: catches Qt parts missing
        from the build (SVG icons, styles, image plugins), not just imports."""
        from PySide6.QtGui import QIcon

        from core.player import Engine
        from gui.main_window import MainWindow
        from timesgate.engine import TimesGateEngine

        s = Settings()
        s.save = lambda path=None: None  # never touch the real config
        w = MainWindow(s, Engine(s), TimesGateEngine(s))
        try:
            w.resize(1000, 700)
            for destination in (w.ditoo, w.timesgate, w.settings_page, w.faq):
                destination.page = destination._factory(destination)
                destination.layout_.addWidget(destination.page)
            from gui.onboarding import SetupPage
            wizard = SetupPage(w)
            wizard.reject()
            pix = w.grab()
            from qfluentwidgets import FluentIcon
            svg = FluentIcon.HOME.icon().pixmap(32, 32).toImage()
            drawn = any(svg.pixelColor(x, y).alpha() for x in range(32) for y in range(32))
            if pix.isNull() or not drawn or QIcon(":/nothing").isNull() is not True:
                return "FAILED"
            return f"{pix.width()}x{pix.height()}, svg icons ok"
        finally:
            w.tray.hide()
            w.deleteLater()
    checks["window"] = render_window
    ok = True
    for name, check in checks.items():
        try:
            results[name] = check()
        except Exception as e:  # report every failure, keep going
            results[name] = f"FAILED: {e!r}"
            ok = False
    ok = (ok and results.get("keyring") == "WinVaultKeyring" and results.get("icon") is True
          and results.get("card_artwork") is True
          and "svg icons ok" in str(results.get("window")))
    log.info("SELF-TEST %s %s", "OK" if ok else "FAILED", results)
    del app
    return 0 if ok else 1


# ---- main ----------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Ditoo Pro controller — diagnostics")
    p.add_argument("--scan", action="store_true", help="list paired Divoom devices")
    p.add_argument("--all", action="store_true", help="with --scan: list every paired device")
    p.add_argument("--mac", help="device address, AA:BB:CC:DD:EE:FF (saved after connecting)")
    p.add_argument("--port", type=int, help="RFCOMM channel (default: probe 2, 1, 3...)")
    p.add_argument("--probe", action="store_true", help="check two-way communication")
    p.add_argument("--test-display", action="store_true", help="send a test pattern")
    p.add_argument("--test-led", action="store_true", help="try keyboard-light commands")
    p.add_argument("--brightness", type=int, metavar="0-100")
    p.add_argument("--image", metavar="PATH", help="send a picture")
    p.add_argument("--spotify-test", action="store_true", help="log in and show the current track")
    p.add_argument("--client-id", help="with --spotify-test: set the Spotify Client ID")
    p.add_argument("--spotify-logout", action="store_true", help="forget the Spotify login")
    p.add_argument("-v", "--verbose", action="store_true", help="log every packet")
    p.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    p.add_argument("--reset-test-profile", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()

    if args.reset_test_profile:
        from core.profile import TEST_MODE
        if not TEST_MODE:
            p.error("Reset is allowed only in DivoomHub_TEST")
        from PySide6.QtCore import QLockFile
        APP_DIR.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(APP_DIR / "instance.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            sys.exit(1)
        from core.spotify import SpotifyAuth
        SpotifyAuth.logout()
        Settings().save()
        return
    setup_logging(args.verbose)
    settings = Settings.load()
    if args.self_test:
        sys.exit(run_self_test())
    if args.scan:
        cmd_scan(args.all)
        return
    if args.spotify_logout:
        from core.spotify import SpotifyAuth
        SpotifyAuth.logout()
        print("Spotify login removed.")
        return
    if args.spotify_test:
        run_spotify_test(args.client_id, settings)
        return
    if not (args.probe or args.test_display or args.test_led or args.image
            or args.brightness is not None):
        from gui.main_window import run_gui
        sys.exit(run_gui(settings, minimized=args.minimized))
    try:
        run_hardware(args, settings)
    except DitooError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
