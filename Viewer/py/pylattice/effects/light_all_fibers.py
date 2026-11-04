from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class LightAllFibers(Effect):
    """MapFiber without the spread: every LED of an end lights at the value."""

    value: Slot
    hue: Slot
    sat: Slot

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for end in graph.ends():

            val = self.value.get(now, end)

            if val > 0.001:
                color = hsv(self.hue.get(now, end), self.sat.get(now, end), val)
                for i in range(4):
                    lattice[end][i] = list(color)
