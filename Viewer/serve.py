#!/usr/bin/env python3
"""Static server + LED-hardware emulator bridge for the Hinge Hexagon viewer.

Three things run together:

  1. HTTP  — serves index.html and assets (as before).
  2. UNIX socket (SOCK_DGRAM) — created and bound by this server. Another
     process (e.g. app.ts under Deno) sendmsg()s one datagram per module:

         [1 byte: length of location string][location ascii, e.g. "0-0"][payload]

     where <payload> is the frame.ts ModuleFrame.serialize() bytes.
  3. WebSocket (/ws) — each datagram received on the UNIX socket is forwarded
     verbatim (location + payload) to every connected browser, which parses the
     location and routes the payload to that module's buffer (see frame.ts
     ModuleFrame.deserialize).

Usage:
    python3 serve.py                     # http:8765, socket /tmp/hinge-leds.sock
    python3 serve.py 9000                # custom port
    python3 serve.py 9000 /tmp/x.sock    # custom port + socket path
"""
import base64
import hashlib
import http.server
import json
import os
import socket
import struct
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
SOCK_PATH = sys.argv[2] if len(sys.argv) > 2 else "/tmp/hinge-leds.sock"

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_ws_clients = set()          # raw sockets of connected browsers
_ws_lock = threading.Lock()

# Last lattice shape reported by the viewer's build() (see index.html/lite.html)
# — lets Python examples (py/examples/*.py) size themselves to whatever's
# actually built in the browser instead of guessing fixed constants.
_shape_lock = threading.Lock()
_lattice_shape = {"levels": None, "perRow": None}


def _ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()


def _ws_frame(payload: bytes) -> bytes:
    """Wrap bytes in a server->client binary WebSocket frame (opcode 0x2, unmasked)."""
    n = len(payload)
    head = bytearray([0x82])          # FIN + binary
    if n < 126:
        head.append(n)
    elif n < 65536:
        head.append(126)
        head += struct.pack(">H", n)
    else:
        head.append(127)
        head += struct.pack(">Q", n)
    return bytes(head) + payload


def _broadcast(msg: bytes) -> None:
    frame = _ws_frame(msg)
    with _ws_lock:
        dead = []
        for c in _ws_clients:
            try:
                c.sendall(frame)
            except OSError:
                dead.append(c)
        for c in dead:
            _ws_clients.discard(c)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            return self._serve_ws()
        if path == "/lattice-shape":
            return self._get_shape()
        super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] == "/lattice-shape":
            return self._post_shape()
        self.send_error(404)

    def _get_shape(self):
        with _shape_lock:
            body = json.dumps(_lattice_shape).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _post_shape(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) if length else b"{}")
            levels, per_row = int(data["levels"]), int(data["perRow"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self.send_error(400)
        with _shape_lock:
            _lattice_shape["levels"] = levels
            _lattice_shape["perRow"] = per_row
        self.send_response(204)
        self.end_headers()

    def _serve_ws(self):
        key = self.headers.get("Sec-WebSocket-Key", "")
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {_ws_accept(key)}\r\n\r\n"
        )
        self.connection.sendall(resp.encode())
        self.close_connection = True
        sock = self.connection
        with _ws_lock:
            _ws_clients.add(sock)
        # Hold the thread open until the browser disconnects. We only send
        # (server->client), so incoming bytes are drained and ignored.
        try:
            while sock.recv(4096):
                pass
        except OSError:
            pass
        finally:
            with _ws_lock:
                _ws_clients.discard(sock)


def _unix_listener():
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    # Bigger receive buffer so bursts of per-module datagrams aren't dropped.
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    srv.bind(SOCK_PATH)
    print(f"LED socket (SOCK_DGRAM): {SOCK_PATH}")
    while True:
        try:
            data, _ = srv.recvfrom(1 << 16)
        except OSError:
            break
        if data:
            _broadcast(data)


def main():
    threading.Thread(target=_unix_listener, daemon=True).start()

    httpd = http.server.ThreadingHTTPServer(("", PORT), Handler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    url = f"http://localhost:{PORT}/index.html"
    print(f"Hinge Hexagon viewer serving at {url}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
