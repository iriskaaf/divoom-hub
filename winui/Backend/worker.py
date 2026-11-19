"""Local JSON-lines adapter for the existing Divoom Hub engines. No Qt imports."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
import threading
from dataclasses import asdict, fields

if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
os.environ["DIVOOM_HUB_PROFILE"] = "winui_test" if os.environ.get("DIVOOM_WINUI_TEST") == "1" else "winui"

from bluetooth.connection import DitooConnection
from bluetooth.ditoo_commands import KeyboardLight, DISPLAY_MODES
from core.player import Engine
from core.settings import Settings
from timesgate.client import TimesGateClient, discover, whole_faces
from timesgate.digits import STYLES, style_roles
from timesgate.digits import theme_thumbnail
from timesgate.engine import TimesGateEngine

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
_write_lock = threading.Lock()


def send(**message):
    with _write_lock:
        print(json.dumps(message, ensure_ascii=False, separators=(",", ":")), flush=True)


def png(image, size=160):
    if image is None:
        return None
    image = image.copy()
    image.thumbnail((size, size))
    with io.BytesIO() as output:
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")


class Journal(logging.Handler):
    def emit(self, record):
        # Keep tracebacks and third-party debug output off the IPC channel.
        if record.name.startswith(("core.", "timesgate.", "bluetooth.")):
            send(event="log", data=record.getMessage())


def decode_settings(profile):
    settings = Settings()
    for field in fields(Settings):
        default = getattr(settings, field.name)
        value = profile.get(field.name)
        if type(value) is type(default) or (isinstance(default, float) and type(value) is int):
            setattr(settings, field.name, value)
    settings.ditoo_enabled &= settings.onboarding_completed
    settings.timesgate_enabled &= settings.onboarding_completed
    if profile.get("devices_paused"):
        settings.ditoo_enabled = settings.timesgate_enabled = False

    themes = []
    selected = profile.get("selected_face_id")
    for face in profile.get("tg_themes", []):
        style = face.get("style")
        if style not in STYLES:
            continue
        palette = face.get("palette", {})
        theme = {key: palette.get(key, default) for key, _, default in style_roles(style)}
        theme.update(name=face["name"], style=style, id=face["id"], chars=face.get("chars", {}))
        if face["id"] == selected:
            settings.tg_theme = len(themes)
        themes.append(theme)
    if themes:
        settings.tg_themes = themes
        settings.tg_theme %= len(themes)
    return settings


class Hub:
    def __init__(self, source=None, device=None, kind=None):
        self.settings = None
        self.engine = None
        self.gate = None
        self.config = {}
        self.ditoo_connected = False
        self.source, self.device, self.kind = source, device, kind

    def emit(self, name, value):
        extra = {"device": self.device} if self.device else {}
        send(event=name, data=value, **extra)

    def apply(self, profile):
        # Use original values for comparison: the engines can update port/IP themselves.
        new = decode_settings(profile)
        if self.settings is None:
            self.settings = new
            # C# owns the profile. Old Python settings are never saved by this process.
            new.save = lambda *args, **kwargs: None
            self.engine = Engine(new)
            self.gate = TimesGateEngine(new, cover_provider=(self.source or self.engine).now_playing_cover)
            self.engine.add_listener(self.event)
            self.gate.add_listener(self.event)
            self.config = profile
            self.engine.start(music=self.source is None, bluetooth=self.kind != "gate")
            if self.kind != "ditoo":
                self.gate.start()
            if self.source and self.kind == "ditoo":
                self.engine.mirror_playback(self.source)
            return

        s = self.settings
        changed = {field.name for field in fields(Settings)
                   if getattr(new, field.name) != getattr(s, field.name)}
        if profile.get("tg_ip") == self.config.get("tg_ip"):
            changed.discard("tg_ip")  # keep an address just rediscovered by Python
        if (profile.get("ditoo_address") == self.config.get("ditoo_address")
                and profile.get("ditoo_port") == self.config.get("ditoo_port")):
            changed.discard("ditoo_port")
        self.config = profile
        for name in changed:
            setattr(s, name, getattr(new, name))
        if changed & {"ditoo_address", "ditoo_enabled", "ditoo_port"}:
            if s.ditoo_enabled and s.ditoo_address and (s.auto_reconnect or "ditoo_address" in changed):
                if not self.ditoo_connected or "ditoo_address" in changed:
                    self.engine.connect_ditoo(s.ditoo_address)
            else:
                self.engine.disconnect_ditoo()
        elif changed & {"auto_reconnect"} and s.auto_reconnect and s.ditoo_enabled and not self.ditoo_connected:
            self.engine.reconnect_ditoo()
        if changed & {"track_source", "media_only_spotify", "spotify_client_id", "show_artwork"}:
            self.engine.wake_spotify()
        if "brightness" in changed:
            self.engine.apply_brightness()
        if changed & {"contrast", "saturation", "art_brightness"}:
            self.engine.refresh_artwork()
        if changed & {"tg_ip", "tg_token", "tg_hardware", "timesgate_enabled"}:
            self.gate.reconnect()
        if "tg_brightness" in changed:
            self.gate.apply_brightness()
        if any(key.startswith("tg_") for key in changed):
            self.gate.refresh()

    def event(self, name, value):
        if name == "track":
            if self.source:
                return
            self.gate.refresh()
            track = asdict(value) if value else None
            if track:
                cover = self.engine.now_playing_cover()
                track["cover"] = png(cover[1]) if cover else None
            self.emit(name, track)
        elif name == "display":
            from PIL import Image
            self.emit(name, png(value.resize((160, 160), Image.Resampling.NEAREST)))
        elif name == "ditoo":
            self.ditoo_connected = bool(value[0])
            self.emit(name, [*value, self.settings.ditoo_address, self.settings.ditoo_port])
        elif name in ("login", "spotify", "tg", "tg_screens", "tg_ip"):
            self.emit(name, value)

    def call(self, command, args):
        if command == "configure":
            self.apply(args)
        elif command == "preview":
            return [png(image, 128) for image in self.gate.preview()]
        elif command == "thumbnails":
            profile = decode_settings(args)
            compact = profile.tg_mode == "gifs_clock"
            return [png(theme_thumbnail(face, tile=44, gap=2, compact=compact), 230) for face in profile.tg_themes]
        elif command == "scan_ditoo":
            return [asdict(x) for x in DitooConnection.scan(bool(args.get("all")))]
        elif command == "scan_gate":
            return [asdict(x) for x in discover()]
        elif command == "builtins":
            return whole_faces()
        elif command == "probe_gate":
            # Read-only verification; a wizard should not write device frames before it is saved.
            hardware = int(args["hardware"])
            TimesGateClient(args["ip"], args["token"], hardware, timeout=5).get_config()
            return True
        elif command == "probe_ditoo":
            address = args["address"].upper()
            if self.ditoo_connected:
                if address == self.settings.ditoo_address.upper():
                    return self.settings.ditoo_port
                raise RuntimeError("Отключите текущее устройство Ditoo перед подключением другого.")
            conn = DitooConnection(address)
            try:
                return conn.connect(timeout=6)
            finally:
                conn.disconnect()
        elif command == "connect_ditoo":
            if self.settings.ditoo_enabled and not self.ditoo_connected:
                self.engine.connect_ditoo(self.settings.ditoo_address)
        elif command == "disconnect_ditoo":
            self.engine.disconnect_ditoo()
        elif command == "reconnect_gate":
            self.gate.reconnect()
        elif command == "spotify_login":
            if not self.settings.spotify_client_id:
                raise ValueError("Введите Client ID.")
            self.engine.spotify_login()
        elif command == "spotify_logout":
            self.engine.spotify_logout()
        elif command.startswith("media_") and self.settings.track_source == "media":
            from core.media_session import control_playback
            if not control_playback(command.removeprefix("media_"), self.settings.media_only_spotify):
                raise ValueError("Команда медиасессии не поддерживается.")
            self.engine.wake_spotify()
        elif command.startswith("ditoo_") and self.ditoo_connected and self.settings.ditoo_enabled:
            action = command.removeprefix("ditoo_")
            if action == "file":
                self.engine.show_file(args["path"])
            elif action == "idle":
                if self.settings.idle_mode in DISPLAY_MODES:
                    self.engine.set_display_mode(self.settings.idle_mode)
            elif action in ("TOGGLE", "PREV", "NEXT"):
                self.engine.keyboard_light(KeyboardLight[action])
            else:
                {"test": self.engine.show_test_pattern, "clear": self.engine.clear_display,
                 "diagnostic": self.engine.run_diagnostic}[action]()
        else:
            raise ValueError("Действие недоступно. Проверьте подключение.")
        return None

    def close(self):
        if self.gate and self.gate.stop():
            self.gate.release_to_device()
        if self.engine:
            self.engine.stop()


class Fleet(Hub):
    """One media poller, one hardware worker per configured device."""

    def __init__(self):
        super().__init__()
        self.devices = {}
        self.multi = False
        self.lock = threading.Lock()

    def apply_devices(self, args):
        self.multi = True
        root = args["music"]
        if self.settings is None:
            self.settings = decode_settings(root)
            self.engine = Engine(self.settings)
            self.engine.add_listener(self.event)
            self.engine.start(bluetooth=False)
        else:
            keys = ("track_source", "media_only_spotify", "spotify_client_id", "show_artwork")
            updated = decode_settings(root)
            changes = [key for key in keys if getattr(self.settings, key) != getattr(updated, key)]
            for key in changes:
                setattr(self.settings, key, getattr(updated, key))
            if changes:
                self.engine.wake_spotify()

        configured = args.get("devices", [])
        ids = {item["id"] for item in configured}
        with self.lock:
            for key in list(self.devices.keys() - ids):
                obsolete = self.devices.pop(key)
                threading.Thread(target=obsolete.close, daemon=True).start()
            for item in configured:
                key, kind = item["id"], item["kind"]
                child = self.devices.get(key)
                if child is None:
                    child = self.devices[key] = Hub(self.engine, key, kind)
                child.apply({**item["settings"], "onboarding_completed": True,
                             "devices_paused": args.get("devices_paused", False),
                             "show_artwork": root["show_artwork"], "timesgate_enabled": kind == "gate",
                             "ditoo_enabled": kind == "ditoo"})

    def event(self, name, value):
        if not self.multi:
            return super().event(name, value)
        if name == "track":
            with self.lock:
                for child in self.devices.values():
                    if child.kind == "gate":
                        child.gate.refresh()
                    else:
                        child.engine.mirror_playback(self.engine)
            track = asdict(value) if value else None
            cover = self.engine.now_playing_cover()
            if track is not None:
                track["cover"] = png(cover[1]) if cover else None
            self.emit(name, track)
        elif name in ("login", "spotify"):
            self.emit(name, value)

    def call(self, command, args):
        if command == "configure_all":
            return self.apply_devices(args)
        if not self.multi:
            return super().call(command, args)
        if command == "probe_ditoo":
            with self.lock:
                existing = next((x for x in self.devices.values() if x.kind == "ditoo" and
                                 x.settings.ditoo_address.upper() == args["address"].upper()), None)
            if existing:
                return existing.call(command, args)
            # Probe a new address without borrowing another Ditoo's connection.
            return Hub().call(command, args)
        if command in ("preview", "reconnect_gate", "connect_ditoo", "disconnect_ditoo") or command.startswith("ditoo_"):
            with self.lock:
                child = self.devices.get(args.get("device"))
            if child is None:
                raise ValueError("Unknown device")
            return child.call(command, args)
        return super().call(command, args)

    def close(self):
        if not self.multi:
            return super().close()
        with self.lock:
            children = list(self.devices.values())
            self.devices.clear()
        jobs = [threading.Thread(target=child.close, daemon=True) for child in children]
        for job in jobs:
            job.start()
        if self.engine:
            self.engine.stop()
        for job in jobs:
            job.join(timeout=7)


def main():
    root = logging.getLogger()
    root.addHandler(Journal())
    root.setLevel(logging.INFO)
    hub = Fleet()

    def reply(message):
        command = message.get("command", "")
        try:
            data = hub.call(command, message.get("args") or {})
            send(id=message["id"], data=data)
        except Exception:
            # Avoid leaking configuration or tokens in device/HTTP errors.
            errors = {
                "probe_ditoo": "Ditoo не подтвердил подключение. Проверьте сопряжение и закройте другие контроллеры.",
                "probe_gate": "Times Gate не ответил или отклонил LocalToken. Проверьте адрес, токен и ревизию.",
                "scan_gate": "Поиск Times Gate недоступен. Можно ввести IP вручную.",
            }
            send(id=message["id"], error=errors.get(command, "Операция не выполнена."))

    send(event="ready", data=1)
    try:
        for line in sys.stdin:
            message = json.loads(line)
            command = message.get("command")
            if command == "shutdown":
                break
            if command in ("scan_gate", "scan_ditoo", "probe_gate", "probe_ditoo", "preview", "builtins", "thumbnails"):
                threading.Thread(target=reply, args=(message,), daemon=True).start()
            else:
                reply(message)
    finally:
        hub.close()


if __name__ == "__main__":
    main()
