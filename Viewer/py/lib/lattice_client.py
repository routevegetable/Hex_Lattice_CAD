"""Python port of ts/lib/lattice-client.ts — the client that sends module frames
to the lattice (the LED hardware, and the viewer via serve.py).

Transport is UDP multicast: one send reaches every local consumer that has joined
the group (serve.py, other tools, real hardware). Each frame is one datagram:

    [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]
"""
import os
import socket

try:                                    # as a package (py.lib.lattice_client)
    from .frame import ModuleFrame
except ImportError:                     # as loose modules on sys.path
    from frame import ModuleFrame

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
        try:
            self.sock.sendto(_pascal(f"{x}-{y}") + frame.serialize(), (self.group, self.port))
            self._warned = False
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"send failed: {e}")

    # Pythonic alias.
    send_module = sendModule

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "LatticeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
