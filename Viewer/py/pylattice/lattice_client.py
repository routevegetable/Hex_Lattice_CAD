"""Python port of ts/lib/lattice-client.ts — the client that sends module frames
to the lattice (the LED hardware, and the viewer via serve.py).

Transport is UDP multicast: one send reaches every local consumer that has joined
the group (serve.py, other tools, real hardware). Each frame is one datagram:

    [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]

Frames stay on this machine by default (multicast TTL 0). To reach real hardware
on the LAN, raise it — `LatticeClient(ttl=1)` or HEXNET_MCAST_TTL=1 — and point
HEXNET_MCAST_IF at the real interface rather than loopback.
"""
import math
import os
import socket

from .format import STANDARD_MODULE, ChannelData, FrameFormat

from .frame import RGB, ModuleFrame

DEFAULT_GROUP = "239.69.69.69"          # administratively-scoped (RFC 2365)
DEFAULT_PORT = 6969
DEFAULT_IFACE = "127.0.0.1"             # egress interface (loopback = stay local)
DEFAULT_TTL = 0                         # 0 = never leaves this host (1 would reach the LAN)


def _pascal(s: str) -> bytes:
    b = s.encode()
    return bytes([len(b)]) + b


def _byte(c: float) -> int:
    # Match JS Math.round (round half up) so bytes are identical across ports.
    return max(0, min(255, math.floor(c * 255 + 0.5)))

class LatticeClient:
    """Sends module frames to the multicast group. `sendModule` is the API."""

    def __init__(self, group: str | None = None, port: int | None = None,
                 iface: str | None = None, ttl: int | None = None):
        # group/port/iface/ttl: explicit arg > HEXNET_MCAST_* env > default.
        self.group = group or os.environ.get("HEXNET_MCAST_GROUP") or DEFAULT_GROUP
        self.port = int(port or os.environ.get("HEXNET_MCAST_PORT") or DEFAULT_PORT)
        iface = iface or os.environ.get("HEXNET_MCAST_IF") or DEFAULT_IFACE
        # `or` won't do here: ttl=0 is the meaningful default, not "unset".
        if ttl is None:
            ttl = int(os.environ.get("HEXNET_MCAST_TTL", DEFAULT_TTL))
        self.ttl = ttl

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # TTL 0 is dropped by the first router *and* by the sending NIC — the
        # datagram never reaches the wire. Loopback delivery is independent of
        # TTL, so same-host receivers (serve.py, other tools) still get it.
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)  # local receivers get a copy
        # Pin the send to `iface` (loopback keeps frames on the box).
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        self._warned = False

    def send(self, x: int, y: int, channels: list[ChannelData]) -> None:
        """
        Send a number of channels
        """
        payload = bytearray()
        for ch in channels:
            payload.append(len(ch.data) & 0xFF)             # pixel count
            for px in ch.data:
                payload.append(_byte(px[0]))
                payload.append(_byte(px[1]))
                payload.append(_byte(px[2]))
        self._send_payload(x, y, bytes(payload))

    def _send_payload(self, x: int, y: int, payload: bytes) -> None:
        try:
            self.sock.sendto(_pascal(f"{x}-{y}") + payload, (self.group, self.port))
            self._warned = False
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"send failed: {e}")

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "LatticeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
