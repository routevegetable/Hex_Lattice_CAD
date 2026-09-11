"""Art-Net receive: drive a LatticeWriter straight from incoming DMX.

Universe == fiber index: universe 0 drives filament 0 of every end, universe 1
filament 1, and so on. Inside a universe the tiles follow graph.tiles() order,
36 channels each: edge major - the edge classes A..F, and within each edge a
triple for the top end then the bottom end.

    tile block: [A top][A bot][B top]...[F bot]

In a fiber universe an end's triple is plain RGB. Universe 4 is the zap plane:
the same mapping again, but the triple is hue / saturation / zap likelihood -
the last standing in for the beat_env inferno.py drives its zaps with. One zap
triple covers all four fibers of an end; each fiber latches independently, so
they spark at their own times.

No two ends share channels, and every channel block belongs to the tile it is
addressed under - unlike a vertex-major layout, whose vertices reach into
neighbouring tiles. 36 channels a tile means only the first 14 tiles fit in a
512-channel universe; tiles past that are not addressable over Art-Net.
"""
import time
from collections.abc import Generator

from stupidArtnet import StupidArtnetServer

from pylattice.graph import EdgeClass, EndRef, Graph, TileRef
from pylattice.lattice_writer import LatticeWriter

from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event, EventLatch, sweep

EDGE_ORDER = tuple(EdgeClass)
FIBERS = 4
ZAP_UNIVERSE = FIBERS                                    # the 5th universe
CHANNELS_PER_EDGE = 6                                    # two ends, a triple each
CHANNELS_PER_TILE = len(EDGE_ORDER) * CHANNELS_PER_EDGE  # 36
UNIVERSE_SIZE = 512
TILES_PER_UNIVERSE = UNIVERSE_SIZE // CHANNELS_PER_TILE  # 14

# Zap timing, as in inferno.py's main loop: roll the dice once a period, then
# fade over ZAP_DECAY ms.
ZAP_PERIOD = 40
ZAP_DECAY = 50
ZAP_FLOOR = 0.1


def _triple(data, o: int) -> list[float]:
    return [data[o] / 255, data[o + 1] / 255, data[o + 2] / 255]


def end_offsets(tiles: list[TileRef], data) -> Generator[tuple[EndRef, int], None, None]:
    """Walk the universe's channel map: each end with the offset of its triple."""
    for t, tile in enumerate(tiles):
        base = t * CHANNELS_PER_TILE
        for e, edge_class in enumerate(EDGE_ORDER):
            o = base + e * CHANNELS_PER_EDGE
            if o + CHANNELS_PER_EDGE > len(data):
                return              # short frame: nothing left to read
            yield (tile.top_end(edge_class), o)
            yield (tile.bottom_end(edge_class), o + 3)


def paint_universe(lattice: LatticeWriter, tiles: list[TileRef], fiber: int, data) -> None:
    """Paint one fiber universe's DMX frame onto `fiber` of every addressable end."""
    for end, o in end_offsets(tiles, data):
        lattice[end][fiber] = _triple(data, o)


def paint_zaps(lattice: LatticeWriter, zap_event: dict, tiles: list[TileRef],
               now: Event, data) -> None:
    """Overlay the zap universe: hue / saturation / likelihood per end.

    Each fiber of an end rolls the dice once a period against the incoming
    likelihood, then fades - so the zap universe stands in for the beat_env
    inferno.py's main loop drives its zaps with.
    """
    for end, o in end_offsets(tiles, data):
        hue, saturation, likelihood = _triple(data, o)
        for i in range(FIBERS):
            zap = zap_event[(end, i)].maybe(now, end.__hash__() + i, ZAP_PERIOD, likelihood)
            zap_env = sweep(now, zap, ZAP_DECAY, 1, 0, 0)

            if zap_env > ZAP_FLOOR:
                lattice[end][i] = hsv(hue, saturation, zap_env)


def tiles_for(graph: Graph) -> list[TileRef]:
    """The tiles a universe can address, in channel order."""
    return list(graph.tiles())[:TILES_PER_UNIVERSE]


def run(lattice: LatticeWriter, graph: Graph, fps: float = 60.0) -> None:
    """Receive Art-Net and paint it straight onto `lattice`.

    Listens on one universe per fiber plus the zap universe (see the channel map
    above) and redraws at `fps`. Blocks until interrupted.
    """
    tiles = tiles_for(graph)
    zap_event = {(end, i): EventLatch() for end in graph.ends() for i in range(FIBERS)}

    # The server receives on its own thread and keeps the last frame per
    # listener; we sample whatever is in each buffer when we come to draw
    # rather than redrawing from a callback.
    server = StupidArtnetServer()
    listeners = [server.register_listener(u) for u in range(FIBERS)]
    zap_listener = server.register_listener(ZAP_UNIVERSE)

    try:
        while True:
            lattice.clear()
            now = Event.for_now()
            for fiber, listener in enumerate(listeners):
                paint_universe(lattice, tiles, fiber, server.get_buffer(listener))
            # Zaps go on last, over the flat colour, as in inferno.py's main loop.
            paint_zaps(lattice, zap_event, tiles, now, server.get_buffer(zap_listener))
            lattice.show()
            time.sleep(1 / fps)
    finally:
        server.delete_all_listener()
        server.close()
