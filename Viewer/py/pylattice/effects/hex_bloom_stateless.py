"""A hexagon fades up, then its colour spreads out along the web."""

from functools import lru_cache

from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event, periodic, sweep
from pylattice.fields.types import Slot
from pylattice.graph import EndRef, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter

RISE = 4000  # ms for any edge to go dark -> full
HOLD = 1500  # ms the finished web stays lit
FADE = 2500  # ms to fade the whole web out
MAX_DEPTH = 2  # 0 = the hex, 1 = the two spokes, then one more per branching
SPAWN_EVERY = 4000  # ms between new hexes

DONE = (MAX_DEPTH + 1) * RISE  # everything has reached full by now
LIFETIME = DONE + HOLD + FADE  # ...and is gone by now


def edge_key(end: EndRef):
    return (end.edge_class, end.tile)  # same for both ends of an edge


HUE_SPREAD = 0.15  # each bloom lands within +/- half this of the hue slot


def hue_offset(n: int) -> float:
    """Bloom n's hue shift - random-looking, but the same n always gives the same."""
    ev = Event(n * SPAWN_EVERY, None)
    return (ev.rand(2) / 0xFFFFFFFF - 0.5) * HUE_SPREAD


@lru_cache(maxsize=32)
def grow(graph: Graph, n: int) -> tuple:
    """Bloom n's edges as (start end, hop depth) pairs. The same n always
    gives the same web, so this can be cached and never stored."""
    ev = Event(n * SPAWN_EVERY, None)

    ends = list(graph.ends())
    hex_ends = ends[ev.rand(0) % len(ends)].hex_ends()
    edges = {edge_key(e): (e, 0) for e in hex_ends}

    # Two adjacent corners = the two ends of one hex edge. Each has one edge
    # that is not part of the hex - its spoke - and the web leaves along those.
    a = hex_ends[ev.rand(1) % len(hex_ends)]
    frontier = []
    for corner in (a, a.other()):
        for start in corner.lr():
            key = edge_key(start)
            if key not in edges:
                edges[key] = (start, 1)
                frontier.append(start)

    depth = 1
    while frontier and depth < MAX_DEPTH:
        depth += 1
        nxt = []
        for end in frontier:
            for start in end.other().lr():  # the two onward edges
                key = edge_key(start)
                if key not in edges:
                    edges[key] = (start, depth)
                    nxt.append(start)
        frontier = nxt

    return tuple(edges.values())


class HexBloom(Effect):
    value: Slot  # brightness
    hue: Slot  # base hue

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        current = periodic(now, SPAWN_EVERY).data

        # Every bloom that could still be alive, oldest first.
        for n in range(current - LIFETIME // SPAWN_EVERY, current + 1):
            t0 = Event(n * SPAWN_EVERY, None)
            if now.when - t0.when >= LIFETIME:
                continue

            fade = sweep(now, t0.delay(DONE + HOLD), FADE, 1, 0, 1)

            for start, depth in grow(graph, n):
                begin = depth * (RISE // 2)  # each generation starts at 50% of the last

                # near end first, far end a quarter-rise behind: that's the direction
                for end, lag in (
                    (start, 0),
                    (start.other(), RISE // 4 if depth else 0),
                ):
                    a = sweep(now, t0.delay(begin + lag), RISE, 0, 1, 0) * fade
                    if a <= 0:
                        continue
                    a *= self.value.get(now, end)
                    hue = self.hue.get(now, end) + hue_offset(n)
                    for i in range(4):
                        color = hsv(hue + i * 0.01, 0.9, 1.0)
                        px = lattice[end][i]
                        px[:] = [c + (n_ - c) * a for c, n_ in zip(px, color)]
