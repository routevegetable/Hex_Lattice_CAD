import math

from pylattice.examples.midi import FloatRange, MIDIFor
from pylattice.examples.tempo import Event
from pylattice.graph import EdgeClass, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class AmbientLight(Effect):
    """Tops up the bottom row so the lattice gives off a minimum of light.

    The target is how bright the bottom row sits when everything else is dark.
    What it adds is the colour mix of the bottom row, held while the row is dark.
    Reads what the effects before it drew, so it belongs last in the chain.
    """

    TARGET = FloatRange(0, 1)

    SETTLE = 200       # ms the measured light takes to follow the lattice

    def __init__(self, graph: Graph, midi: MIDIFor):
        super().__init__()
        self._target = midi.cc(89, "target", meta=self.TARGET)

        # The bottom row of tiles has no F edges.
        self._ends = [end for end in graph.ends()
                      if not (end.y == 0 and end.edge_class == EdgeClass.F)]
        self._bottom = [graph.TILE[x, 0].bottom_end(c) for x in range(graph.width)
                        for c in (EdgeClass.D, EdgeClass.E)]

        # The most this effect can add, as a fraction of the whole lattice.
        self._share = len(self._bottom) / len(self._ends)

        self._light = 0.0
        self._measured_at = 0
        self._mix = [1.0, 1.0, 1.0]

    def _measure(self, lattice: LatticeWriter) -> float:
        """The light on the lattice, from 0 for dark to 1 for all full white."""
        total = 0.0

        for end in self._ends:
            for r, g, b in lattice[end]:
                total += r + g + b

        return total / (len(self._ends) * 12)

    def _bottom_colour(self, lattice: LatticeWriter) -> list[float]:
        """The red, green and blue on the bottom row, summed."""
        colour = [0.0, 0.0, 0.0]

        for end in self._bottom:
            for r, g, b in lattice[end]:
                colour[0] += r
                colour[1] += g
                colour[2] += b

        return colour

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        # One-pole smoothing, so strobes and zaps do not flicker the bottom row.
        dt = now.when - self._measured_at
        self._measured_at = now.when
        follow = 1 - math.exp(-dt / self.SETTLE)
        self._light += (self._measure(lattice) - self._light) * follow

        colour = self._bottom_colour(lattice)

        if sum(colour) > 0:
            self._mix = [m + (c - m) * follow for m, c in zip(self._mix, colour)]

        level = self.TARGET.at(self._target().data) - self._light / self._share

        if level <= 0:
            return

        # Light equal to `level` of white, as far as the brightest channel allows.
        scale = min(level * 3 / sum(self._mix), 1 / max(self._mix))
        add_r, add_g, add_b = [m * scale for m in self._mix]

        for end in self._bottom:
            frame = lattice[end]
            r, g, b = frame[0]
            frame[0] = [r + add_r, g + add_g, b + add_b]
