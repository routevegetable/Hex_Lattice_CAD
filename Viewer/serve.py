#!/usr/bin/env python3
"""Static server + LED-frame bridge for the Hinge Hexagon viewer.

Two things run together:

  1. HTTP + WebSocket (/ws) — serves index.html/assets and pushes LED frames to
     every connected browser. The WebSocket is push-only: serve.py never reads
     from it (no TCP ingress).
  2. UDP multicast (the sole data ingress) — serve.py joins the group; any local
     producer that sends one datagram per module is forwarded verbatim to every
     browser, which routes it to that module (see frame.ts ModuleFrame).

     Datagram format:
         [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]

Usage:
    python3 serve.py            # http:8765, multicast 239.69.69.69:6969
    python3 serve.py 9000       # custom http port

Env: HEXNET_MCAST_GROUP, HEXNET_MCAST_PORT override the multicast group/port.
"""
import base64
import hashlib
import http.server
import os
import socket
import struct
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# UDP multicast source (browsers can't join groups, so serve.py joins and bridges
# to the viewer over WebSocket).
MCAST_GROUP = os.environ.get("HEXNET_MCAST_GROUP", "239.69.69.69")
MCAST_PORT = int(os.environ.get("HEXNET_MCAST_PORT", "6969"))

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_ws_clients = {}             # browser socket -> threading.Event (set when dropped)
_ws_lock = threading.Lock()


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
                dead.append(c)          # send failure => client is gone
        for c in dead:
            ev = _ws_clients.pop(c, None)
            if ev is not None:
                ev.set()                # wake its parked handler thread


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/ws" and \
                self.headers.get("Upgrade", "").lower() == "websocket":
            return self._serve_ws()
        super().do_GET()

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
        gone = threading.Event()
        with _ws_lock:
            _ws_clients[sock] = gone
        # Push-only: we never recv() from the browser. Hold the connection open
        # here until a broadcast send fails (see _broadcast), which sets `gone`.
        gone.wait()
        with _ws_lock:
            _ws_clients.pop(sock, None)


def _mcast_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    sock.bind(("", MCAST_PORT))
    # Join the group on both the loopback and the default interface, so it works
    # whether the producer pins its send to lo0 or lets it egress the default NIC.
    group = socket.inet_aton(MCAST_GROUP)
    for iface in ("127.0.0.1", "0.0.0.0"):
        try:
            mreq = struct.pack("=4s4s", group, socket.inet_aton(iface))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass
    print(f"multicast group: {MCAST_GROUP}:{MCAST_PORT}")
    while True:
        try:
            data, _ = sock.recvfrom(1 << 16)
        except OSError:
            import traceback
            traceback.print_exc()
            break
        if data:
            _broadcast(data)


def main():
    threading.Thread(target=_mcast_listener, daemon=True).start()

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


if __name__ == "__main__":
    main()
