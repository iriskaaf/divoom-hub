"""Exercise the packaged worker with a local Times Gate stub and no physical devices."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

packaged = sys.argv[1]
events = queue.Queue()
requests = queue.Queue()
pending = []


class FakeGate(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.put(data)
        response = json.dumps({"error_code": 0 if data["LocalToken"] in (123456, 654321) else "token"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_):
        pass


def receive(predicate):
    for index, value in enumerate(pending):
        if predicate(value):
            return pending.pop(index)
    while True:
        value = events.get(timeout=22)
        if value is None:
            raise RuntimeError("Backend closed unexpectedly")
        if predicate(value):
            return value
        pending.append(value)


def main():
    gate = ThreadingHTTPServer(("127.0.0.1", 0), FakeGate)
    threading.Thread(target=gate.serve_forever, daemon=True).start()
    peer = subprocess.Popen([packaged], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)

    def read():
        for line in peer.stdout:
            events.put(json.loads(line))
        events.put(None)

    threading.Thread(target=read, daemon=True).start()
    serial = 0

    def call(command, **args):
        nonlocal serial
        serial += 1
        print(json.dumps({"id": serial, "command": command, "args": args}), file=peer.stdin, flush=True)
        return receive(lambda m: m.get("id") == serial)

    try:
        assert receive(lambda m: m.get("event") == "ready")["data"] == 1
        music = {"track_source": "media", "show_artwork": True}
        assert call("configure_all", music=music, devices=[], devices_paused=True)["data"] is None
        media = receive(lambda m: m.get("event") == "spotify")["data"]
        assert media in ("Spotify не запущен", "Играет", "Пауза"), "Windows media session unavailable"
        # Engine host/port syntax is accepted by the HTTP adapter only for this loopback test.
        ip = f"127.0.0.1:{gate.server_port}"
        ok = call("probe_gate", ip=ip, token="123456", hardware=400)
        assert ok["data"] is True
        bad = call("probe_gate", ip=ip, token="234567", hardware=400)
        assert "error" in bad and "234567" not in bad["error"]
        music["show_artwork"] = False
        devices = [
            {"id": "gate-a", "kind": "gate", "settings": {"tg_ip": ip, "tg_token": "123456",
             "tg_mode": "clock", "tg_brightness": 23}},
            {"id": "gate-b", "kind": "gate", "settings": {"tg_ip": f"localhost:{gate.server_port}", "tg_token": "654321",
             "tg_mode": "clock", "tg_brightness": 87}},
        ]
        assert call("configure_all", music=music, devices=devices)["data"] is None
        for device in devices:
            key = device["id"]
            receive(lambda m: m.get("event") == "tg" and m.get("device") == key and m["data"][0])
            preview = call("preview", device=key)["data"]
            assert len(preview) == 5 and all(frame.startswith("iVBOR") for frame in preview)
        assert len(call("thumbnails", tg_mode="clock")["data"]) == 6
        centres = {}
        while True:
            message = requests.get(timeout=10)
            if message["Command"] == "Draw/SendHttpGif" and message["LcdArray"] == [0, 0, 1, 0, 0]:
                centres[message["LocalToken"]] = message
                if len(centres) == 2:
                    break
        assert set(centres) == {123456, 654321}
        assert all(frame["PicWidth"] == 128 and frame["PicData"] for frame in centres.values())
        assert call("configure_all", music=music, devices=devices[1:])["data"] is None
        assert "error" in call("preview", device="gate-a")
        assert len(call("preview", device="gate-b")["data"]) == 5
        print('{"command":"shutdown"}', file=peer.stdin, flush=True)
        assert peer.wait(timeout=14) == 0
        assert any(item["Command"] == "Channel/Set5LcdWholeClockId" for item in list(requests.queue))
        print("PASS: Windows media session, token handling, two independent Times Gate workers, previews, thumbnails, removal and shutdown")
    finally:
        if peer.poll() is None:
            peer.kill()
            peer.wait()
        gate.shutdown()
        gate.server_close()


if __name__ == "__main__":
    main()
