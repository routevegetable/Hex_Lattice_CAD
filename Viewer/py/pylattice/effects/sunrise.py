from pylattice.examples.sunrise import color_transitions, sunrise
from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class Sunrise(Effect):
    value: Slot

    def draw_sunrise(self):
        sunrise(color_transitions)

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        return
