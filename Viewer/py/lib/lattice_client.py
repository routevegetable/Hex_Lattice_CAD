"""Python port of ts/lib/lattice-client.ts — the client that sends module frames
to the lattice (the LED hardware, emulated by serve.py's UNIX socket).

Each frame is one datagram:

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


def _pascal(s: str) -> bytes:
    b = s.encode()
    return bytes([len(b)]) + b


class LatticeClient:
    """Sends module frames to the lattice. `sendModule` is the API."""

    def __init__(self, server_sock: str | None = None):
        # Resolve the socket path here: explicit arg > HINGE_SOCK env > default.
        self.server_sock = server_sock or os.environ.get("HINGE_SOCK") or DEFAULT_SOCK
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._warned = False

    def sendModule(self, location: str, frame: ModuleFrame) -> None:
        """Send one module's frame, addressed to `location` (e.g. "0-0")."""
        try:
            self.sock.sendto(_pascal(location) + frame.serialize(), self.server_sock)
            self._warned = False
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"send failed (is serve.py running?): {e}")

    # Pythonic alias.
    send_module = sendModule

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "LatticeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
