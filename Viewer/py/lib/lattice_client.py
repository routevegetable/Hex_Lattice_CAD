"""Python port of ts/lib/lattice-client.ts — the client that sends module frames
to the lattice (the LED hardware, and the viewer via serve.py).

Transport is UDP multicast: one send reaches every local consumer that has joined
the group (serve.py, other tools, real hardware). Each frame is one datagram:

    [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]
"""
import json
import os
import socket
import urllib.error
import urllib.request

try:                                    # as a package (py.lib.lattice_client)
    from .frame import ModuleFrame
except ImportError:                     # as loose modules on sys.path
    from frame import ModuleFrame

DEFAULT_SOCK = "/tmp/hinge-leds.sock"
DEFAULT_HTTP = "http://localhost:8765"


def fetch_lattice_shape(http_base: str | None = None, timeout: float = 1.0):
    """GET serve.py's /lattice-shape - {"levels": N, "perRow": N} reported by
    the viewer's own build() (see index.html/lite.html), or None if serve.py
    isn't reachable or the viewer hasn't built anything yet (both fields null).
    Lets an example size itself to whatever's actually on screen instead of a
    guessed constant.
    """
    base = http_base or os.environ.get("HINGE_HTTP") or DEFAULT_HTTP
    try:
        with urllib.request.urlopen(f"{base}/lattice-shape", timeout=timeout) as resp:
            shape = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if shape.get("levels") is None or shape.get("perRow") is None:
        return None
    return shape
DEFAULT_GROUP = "239.69.69.69"          # administratively-scoped (RFC 2365)
DEFAULT_PORT = 6969
DEFAULT_IFACE = "127.0.0.1"             # egress interface (loopback = stay local)


def _pascal(s: str) -> bytes:
    b = s.encode()
    return bytes([len(b)]) + b


class LatticeClient:
    """Sends module frames to the multicast group. `sendModule` is the API."""

    def __init__(self, group: str | None = None, port: int | None = None,
                 iface: str | None = None):
        # group/port/iface: explicit arg > HEXNET_MCAST_* env > default.
        self.group = group or os.environ.get("HEXNET_MCAST_GROUP") or DEFAULT_GROUP
        self.port = int(port or os.environ.get("HEXNET_MCAST_PORT") or DEFAULT_PORT)
        iface = iface or os.environ.get("HEXNET_MCAST_IF") or DEFAULT_IFACE

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)   # stay local subnet
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)  # local receivers get a copy
        # Pin the send to `iface` (loopback keeps frames on the box).
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        self._warned = False

    def sendModule(self, x: int, y: int, frame: ModuleFrame) -> None:
        """Send one module's frame, addressed by grid coords x (lateral), y (height)."""
        self._send_payload(x, y, frame.serialize())

    def sendChannels(self, x: int, y: int, channels) -> None:
        """Send raw channel data, bypassing ModuleFrame. `channels` is one list of
        RGB pixels per channel (each RGB 0-255); each channel is prefixed with its
        pixel count, matching ModuleFrame.serialize's layout."""
        payload = bytearray()
        for ch in channels:
            payload.append(len(ch) & 0xFF)             # pixel count
            for px in ch:
                payload.append(max(0, min(255, int(px[0]))))
                payload.append(max(0, min(255, int(px[1]))))
                payload.append(max(0, min(255, int(px[2]))))
        self._send_payload(x, y, bytes(payload))

    def _send_payload(self, x: int, y: int, payload: bytes) -> None:
        try:
            self.sock.sendto(_pascal(f"{x}-{y}") + payload, (self.group, self.port))
            self._warned = False
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"send failed: {e}")

    # Pythonic aliases.
    send_module = sendModule
    send_channels = sendChannels

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "LatticeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
