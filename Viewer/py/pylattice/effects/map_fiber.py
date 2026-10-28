from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class MapFiber(Effect):
    value: Slot
    hue: Slot
    sat: Slot

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for end in graph.ends():

            val = self.value.get(now, end)
            hue = self.hue.get(now, end)
            sat = self.sat.get(now, end)


            if val > 0.001:
                lattice[end][0] = list(hsv(hue, sat, val))
            if val > 0.3:
                lattice[end][1] = list(hsv(hue, sat, val/2))
            if val > 0.6:
                lattice[end][2] = list(hsv(hue, sat, val/3))
            if val > 0.8:
                lattice[end][3] = list(hsv(hue, sat, val/4))

        return
