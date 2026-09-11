

# Paint waves over the whole lattice
# Scalar field selects the hue
from py.pylattice.examples.colors import hsv, vary
from py.pylattice.examples.instrument import ScalarField
from py.pylattice.examples.tempo import Event
from py.pylattice.graph import Graph
from py.pylattice.lattice_writer import LatticeWriter


def bg_waves(graph: Graph, lattice: LatticeWriter, now: Event, bg_hue: ScalarField, bg_value: ScalarField):
    for v in graph.vertexes():
        base_hue = bg_hue.get(now, v)
        base_value = bg_value.get(now, v)
        for end in v.ends_cw():
            PERIOD = 200 + (end.__hash__() % 200)
            for i in range(4):
                hue = vary(now, base_hue, base_hue + .03, PERIOD, i/4)
                value = vary(now, 0.1, .7 * base_value, PERIOD*7.1, i/4)
                saturation = vary(now, .9, 1, PERIOD*3, i/4)
                lattice[end][i] = hsv(hue, saturation, value)