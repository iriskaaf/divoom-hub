"""Bluetooth Classic RFCOMM (SPP) link to the Ditoo Pro, using only the stdlib.

Why RFCOMM and not BLE: RFCOMM is the transport every working Ditoo image
upload uses (andreas-mausch, futpib, hass-divoom). futpib also has a BLE
transport, but image upload over BLE is marked "not yet verified on hardware".
CPython on Windows supports AF_BLUETOOTH/BTPROTO_RFCOMM natively, so no
third-party Bluetooth package is needed.

The device must be paired in Windows Settings first ("DitooPro-Audio").
RFCOMM channel: 2 for Ditoo models according to hass-divoom config_flow.py;
we probe 2 first and fall back to other channels, confirming each candidate
with a read-only GET_VOLUME query.
"""

from __future__ import annotations

import logging
import queue
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from . import ditoo_commands as cmd
from .protocol import FrameParser, Reply

log = logging.getLogger(__name__)

DIVOOM_NAME_HINTS = ("ditoo", "divoom", "pixoo", "timebox", "tivoo", "timoo", "tiivoo")


class DitooError(Exception):
    pass


@dataclass(frozen=True)
class BtDevice:
    name: str
    address: str  # "AA:BB:CC:DD:EE:FF"

    @property
    def is_divoom(self) -> bool:
        return any(h in self.name.lower() for h in DIVOOM_NAME_HINTS)


_bt_api = None  # (BluetoothGetDeviceInfo, struct type) once loaded; False if unavailable


def _load_bt_api():
    global _bt_api
    if _bt_api is None:
        try:
            import ctypes
            from ctypes import wintypes

            class SystemTime(ctypes.Structure):
                _fields_ = [(n, wintypes.WORD) for n in ("y", "mo", "dow", "d", "h", "mi", "s", "ms")]

            class DeviceInfo(ctypes.Structure):  # BLUETOOTH_DEVICE_INFO, 560 bytes on x64
                _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong),
                            ("ulClassofDevice", wintypes.ULONG), ("fConnected", wintypes.BOOL),
                            ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                            ("stLastSeen", SystemTime), ("stLastUsed", SystemTime),
                            ("szName", wintypes.WCHAR * 248)]

            fn = ctypes.WinDLL("BluetoothApis.dll").BluetoothGetDeviceInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(DeviceInfo)]
            fn.restype = wintypes.DWORD
            _bt_api = (fn, DeviceInfo)
        except (OSError, AttributeError):
            _bt_api = False
    return _bt_api


def windows_sees_connected(address: str) -> bool | None:
    """Whether Windows has a live Bluetooth link to the device (e.g. the Ditoo's
    audio part reconnected after power-on). Answers in ~0.1 ms without radio
    traffic, unlike an RFCOMM connect attempt, which pages the device for ~2.6 s.
    None when the API is unavailable."""
    api = _load_bt_api()
    if not api:
        return None
    import ctypes
    fn, info_type = api
    info = info_type()
    info.dwSize = ctypes.sizeof(info)
    try:
        info.Address = int(address.replace(":", ""), 16)
    except ValueError:
        return None
    if fn(None, ctypes.byref(info)) != 0:
        return None
    return bool(info.fConnected)


def paired_devices() -> list[BtDevice]:
    """Classic Bluetooth devices paired with Windows (read from the registry)."""
    if sys.platform != "win32":
        return []
    import winreg

    path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    devices: list[BtDevice] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        log.warning("Bluetooth registry key not found; is Bluetooth enabled?")
        return devices
    with root:
        i = 0
        while True:
            try:
                key_name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, key_name) as sub:
                    raw, _ = winreg.QueryValueEx(sub, "Name")
            except OSError:
                continue
            name = bytes(raw).split(b"\0", 1)[0].decode("utf-8", "replace")
            address = ":".join(key_name[j : j + 2] for j in range(0, 12, 2)).upper()
            devices.append(BtDevice(name, address))
    return devices


class DitooConnection:
    DEFAULT_PORTS = (2, 1, 3, 4, 5, 6, 7, 8)
    PROBE_TIMEOUT = 2.0
    UPLOAD_READY_TIMEOUT = 2.0   # wait for "ready" after the 0x8B start packet
    UPLOAD_RESEND_WINDOW = 0.3   # how long to listen for chunk resend requests
    UPLOAD_MAX_RESENDS = 10

    def __init__(self, address: str, port: int | None = None, packet_delay: float = 0.04):
        self.address = address.upper()
        self.port = port
        self.packet_delay = packet_delay
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._replies: queue.Queue[Reply] = queue.Queue()
        self._write_lock = threading.Lock()
        self._connected = threading.Event()

    # ---- discovery -------------------------------------------------------

    @staticmethod
    def scan(include_all: bool = False) -> list[BtDevice]:
        devices = paired_devices()
        return devices if include_all else [d for d in devices if d.is_divoom]

    # ---- lifecycle -------------------------------------------------------

    def connect(self, timeout: float = 8.0) -> int:
        """Open the RFCOMM link and return the channel that answered."""
        self.disconnect()
        candidates = (self.port,) if self.port else self.DEFAULT_PORTS
        fallback: int | None = None
        last_error: OSError | None = None

        for port in candidates:
            try:
                self._open(port, timeout)
            except OSError as e:
                last_error = e
                log.debug("RFCOMM channel %d: %s", port, e)
                continue
            reply = self.request(cmd.get_volume(), cmd.CMD_GET_VOLUME, self.PROBE_TIMEOUT)
            if reply is not None:
                log.info("Connected to %s on RFCOMM channel %d (volume reply %s)",
                         self.address, port, reply.data.hex() or "-")
                self.port = port
                return port
            log.debug("RFCOMM channel %d connected but did not answer the probe", port)
            fallback = fallback or port
            if self.port:  # explicitly configured channel: trust it
                log.warning("Channel %d did not answer the probe; keeping it anyway", port)
                return port
            self.disconnect()

        if fallback is not None:
            log.warning("No channel answered the probe; using channel %d unverified", fallback)
            self._open(fallback, timeout)
            self.port = fallback
            return fallback
        raise DitooError(f"Cannot connect to {self.address}: {last_error}")

    def disconnect(self) -> None:
        self._connected.clear()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
        self._reader = None

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # ---- I/O -------------------------------------------------------------

    def send(self, frames: bytes | Iterable[bytes]) -> None:
        if isinstance(frames, (bytes, bytearray)):
            frames = [bytes(frames)]
        with self._write_lock:
            for frame in frames:
                sock = self._sock
                if sock is None or not self._connected.is_set():
                    raise DitooError("Not connected")
                try:
                    sock.sendall(frame)
                except OSError as e:
                    log.warning("Send failed, link lost: %s", e)
                    self._connected.clear()
                    raise DitooError(f"Send failed: {e}") from e
                log.debug("-> %s", frame.hex())
                time.sleep(self.packet_delay)

    def request(self, frame: bytes, command: int, timeout: float = 2.0) -> Reply | None:
        """Send one frame and wait for the reply to `command` (None on timeout)."""
        self._drain_replies()
        self.send(frame)
        return self._wait_reply(command, timeout)

    def upload_animation(self, divoom16_data: bytes) -> None:
        """Upload an image/animation with command 0x8B, following the official
        handshake: wait for "ready" after the start packet, then send the
        chunks and serve the device's resend requests."""
        chunks = cmd.animation_chunks(divoom16_data)
        self._drain_replies()
        self.send(cmd.animation_start(divoom16_data))
        ready = self._wait_reply(cmd.CMD_SEND_ANIMATION, self.UPLOAD_READY_TIMEOUT,
                                 lambda r: r.data[:1] == bytes([cmd.ANIM_START]))
        if ready is None:
            log.warning("No 'ready' reply to the image upload; sending anyway")
        elif ready.data[1:2] == b"\x00":
            raise DitooError("Device refused the image upload")

        self.send(chunks)
        for _ in range(self.UPLOAD_MAX_RESENDS):
            again = self._wait_reply(cmd.CMD_SEND_ANIMATION, self.UPLOAD_RESEND_WINDOW,
                                     lambda r: r.data[:1] == bytes([cmd.ANIM_DATA])
                                     and len(r.data) >= 3)
            if again is None:
                return
            index = int.from_bytes(again.data[1:3], "little")
            log.info("Device asked for image chunk %d again", index)
            if index < len(chunks):
                self.send(chunks[index])
        log.warning("Too many resend requests for one image")

    def _drain_replies(self) -> None:
        while not self._replies.empty():
            self._replies.get_nowait()

    def _wait_reply(self, command: int, timeout: float,
                    match: Callable[[Reply], bool] = lambda r: True) -> Reply | None:
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                reply = self._replies.get(timeout=left)
            except queue.Empty:
                break
            if reply.command == command and match(reply):
                return reply
        return None

    # ---- internals -------------------------------------------------------

    def _open(self, port: int, timeout: float) -> None:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(timeout)
        try:
            sock.connect((self.address, port))
        except OSError:
            sock.close()
            raise
        sock.settimeout(0.5)
        self._sock = sock
        self._connected.set()
        self._reader = threading.Thread(target=self._read_loop, args=(sock,),
                                        name="ditoo-reader", daemon=True)
        self._reader.start()

    def _read_loop(self, sock: socket.socket) -> None:
        parser = FrameParser()
        while self._connected.is_set() and self._sock is sock:
            try:
                data = sock.recv(1024)
            except socket.timeout:
                continue
            except OSError as e:
                if self._sock is sock:
                    log.warning("Link lost: %s", e)
                break
            if not data:
                log.warning("Link closed by device")
                break
            for frame in parser.feed(data):
                reply = frame.as_reply()
                log.debug("<- cmd=0x%02X payload=%s", frame.command, frame.payload.hex())
                if reply is not None:
                    self._replies.put(reply)
        if self._sock is sock:
            self._connected.clear()
