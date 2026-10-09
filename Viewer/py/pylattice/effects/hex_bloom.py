"""A hexagon fades up, then its colour spreads out along the web."""

import random

from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event, sweep
from pylattice.fields.types import Slot
from pylattice.graph import EndRef, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter

RISE = 4000  # ms for any edge to go dark -> full
HOLD = 1500  # ms the finished web stays lit
FADE = 2500  # ms to fade the whole web out
MAX_DEPTH = 3
MAX_BLOOMS = 6


def edge_key(end: EndRef):
    return (end.edge_class, end.tile)  # same for both ends of an edge


class Bloom:
    def __init__(self, t0: int, hue: float, edges: dict):
        self.t0 = t0
        self.hue = hue
        self.edges = edges  # key -> (start end, hop depth)
        self.begin_fade = t0 + (MAX_DEPTH + 1) * RISE + HOLD
        self.bloom_done = self.begin_fade + FADE


class HexBloom(Effect):
    value: Slot  # master brightness
    hue: Slot  # base hue
    rate: Slot  # 0 = a new hex every 8s, 1 = every 1s

    def __init__(self, **fields):
        super().__init__(**fields)  # makes the Slot cells
        self._blooms: list[Bloom] = []
        self._ends: list[EndRef] = []
        self._last_spawn = -(10**9)
        self._count = 0

    def _grow(self, seed: EndRef) -> dict:
        """Hop depth of every edge: 0 for the hex, then out from one hex edge."""
        hex_ends = seed.hex_ends()  # the hexagon: 6 edges, in order
        edges = {edge_key(e): (e, 0) for e in hex_ends}

        # Two adjacent corners = the two ends of one hex edge. Each has one
        # edge that is not part of the hex - its spoke - and the web leaves
        # along those.
        a = random.choice(hex_ends)
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
        return edges

    def _spawn(self, now: Event, hue: float):
        seed = random.choice(self._ends)
        self._blooms.append(Bloom(now.when, hue + self._count * 0.04, self._grow(seed)))
        self._count += 1
        self._last_spawn = now.when

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        if not self._ends:
            self._ends = list(graph.ends())  # graph.ends() is a generator

        probe = self._ends[0]  # slots want an end; these are global
        master = self.value.get(now, probe)
        hue = self.hue.get(now, probe)
        interval = 8000 - 7000 * self.rate.get(now, probe)

        if now.when - self._last_spawn >= interval and len(self._blooms) < MAX_BLOOMS:
            self._spawn(now, hue)
        self._blooms = [b for b in self._blooms if now.when < b.bloom_done]

        for b in self._blooms:
            t0 = Event(b.t0, None)
            fade = sweep(now, t0.delay(b.begin_fade - b.t0), FADE, 1, 0, 1)

            for start, depth in b.edges.values():
                begin = depth * (RISE // 2)  # each generation starts at 50% of the last

                # near end first, far end a quarter-rise behind: that's the direction
                for end, lag in (
                    (start, 0),
                    (start.other(), RISE // 4 if depth else 0),
                ):
                    a = sweep(now, t0.delay(begin + lag), RISE, 0, 1, 0) * fade * master
                    if a <= 0:
                        continue
                    for i in range(4):
                        color = hsv(b.hue + i * 0.01, 0.9, 1.0)
                        px = lattice[end][i]
                        px[:] = [c + (n - c) * a for c, n in zip(px, color)]
