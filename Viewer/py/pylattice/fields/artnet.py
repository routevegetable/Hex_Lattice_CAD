"""Art-Net pixels as scalar fields.

Incoming DMX is read as an RGB image. Each tile is a 2x2 square of pixels, one
per vertex, laid out the way the vertices sit:

    ABC  ABF
    CDE  DEF

so the image is twice the graph's width and twice its height, in row-major
order - tile (x, y) owns columns 2x, 2x+1 and rows 2y, 2y+1.

One universe is one whole picture, and carries its own four fields, so several
universes can drive different things at once:

    r, g, b, v = ArtnetPixels(graph, universe=0)

Three colours and their average, so a universe destructures straight into the
fields that read it.

At 3 channels a pixel a universe holds 170 pixels, which is a graph of up to
42 tiles wide by 2 tall. Pixels past that read 0.

The buffers are re-read once a frame - the first field asked for a value at a
given `now` refreshes them, and the rest of that frame reads the same picture.
"""
from collections.abc import Iterator
from typing import NamedTuple

from stupidArtnet import StupidArtnetServer

from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, VertexClass

# Where each vertex sits in its tile's square.
CORNERS: dict[VertexClass, tuple[int, int]] = {
    VertexClass.ABC: (0, 0),
    VertexClass.ABF: (1, 0),
    VertexClass.CDE: (0, 1),
    VertexClass.DEF: (1, 1),
}

CHANNELS_PER_PIXEL = 3
UNIVERSE_SIZE = 512
PIXELS_PER_UNIVERSE = UNIVERSE_SIZE // CHANNELS_PER_PIXEL      # 170


class ArtnetChannels(NamedTuple):
    """What a universe reads as: three colours, and their average."""
    r: ScalarField
    g: ScalarField
    b: ScalarField
    v: ScalarField


class ArtnetPixels:
    """An Art-Net receiver that hands out one scalar field per colour."""

    def __init__(self, graph: Graph, universe: int = 0, server: StupidArtnetServer | None = None):
        self.width = graph.width * 2
        self.height = graph.height * 2
        self.universe = universe

        # One server can carry every universe; each receiver just adds a listener.
        self._server = server or StupidArtnetServer()
        self._listener = self._server.register_listener(universe)
        self._buffer: list[int] = []
        self._sampled: int | None = None

        self.r = ArtnetChannel(self, 0, "r")
        self.g = ArtnetChannel(self, 1, "g")
        self.b = ArtnetChannel(self, 2, "b")
        self.v = (self.r + self.g + self.b) / 3          # brightness, near enough

    def channels(self) -> ArtnetChannels:
        return ArtnetChannels(self.r, self.g, self.b, self.v)

    def __iter__(self) -> Iterator[ScalarField]:
        """So `r, g, b, v = ArtnetPixels(...)` works, typed."""
        return iter(self.channels())

    def pixel(self, end: EndRef) -> int:
        """Which pixel an end's vertex reads from."""
        vertex = end.vertex()
        dx, dy = CORNERS[vertex.vertex_class]
        return (vertex.tile.y * 2 + dy) * self.width + (vertex.tile.x * 2 + dx)

    def sample(self, now: Event):
        """Take a fresh copy of the universe, once per frame."""
        if now.when == self._sampled:
            return
        self._sampled = now.when
        self._buffer = self._server.get_buffer(self._listener)

    def channel(self, now: Event, end: EndRef, offset: int) -> float:
        """One colour of one pixel, 0-1. Anything not being sent reads 0."""
        self.sample(now)

        at = self.pixel(end) * CHANNELS_PER_PIXEL + offset
        return self._buffer[at] / 255 if at < len(self._buffer) else 0.0


class ArtnetChannel(ScalarField):
    """One colour of the incoming picture."""

    def __init__(self, pixels: ArtnetPixels, offset: int, name: str):
        self._pixels = pixels
        self._offset = offset
        self._name = name

    def get(self, now: Event, end: EndRef) -> float:
        return self._pixels.channel(now, end, self._offset)

    def __repr__(self) -> str:
        return f"ArtnetChannel({self._pixels.universe}.{self._name})"


def artnet_universes(graph: Graph, count: int = 4, first: int = 0) -> list[ArtnetPixels]:
    """Several universes off a single server.

    One socket listens on 6454 for all of them - a server per universe would
    fight over the port, and only the first would ever bind.
    """
    server = StupidArtnetServer()
    return [ArtnetPixels(graph, universe=first + n, server=server) for n in range(count)]
