# Paint waves over the whole lattice
# Scalar field selects the hue
from pylattice.examples.colors import hsv, vary
from pylattice.fields.types import ScalarField
from pylattice.examples.tempo import Event
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter
from pylattice.fields.types import Slot
from pylattice.runner.types import Effect


def bg_waves(
    graph: Graph,
    lattice: LatticeWriter,
    now: Event,
    bg_hue: ScalarField,
    bg_value: ScalarField,
):
    for v in graph.vertexes():
        ends = v.ends_cw()
        # A field keyed on the vertex answers the same at any of its ends.
        base_hue = bg_hue.get(now, ends[0])
        base_value = bg_value.get(now, ends[0])
        for end in ends:
            PERIOD = 200 + (end.__hash__() % 200)
            for i in range(4):
                hue = vary(now, base_hue, base_hue + .03, PERIOD, i/4)
                value = vary(now, 0.1, .7 * base_value, PERIOD*7.1, i/4)
                saturation = vary(now, .9, 1, PERIOD*3, i/4)
                lattice[end][i] = hsv(hue, saturation, value)


class BgWaves(Effect):
    """Waves over the whole lattice: one field picks the hue, another the brightness."""

    hue: Slot
    value: Slot

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        bg_waves(graph, lattice, now, self.hue, self.value)
