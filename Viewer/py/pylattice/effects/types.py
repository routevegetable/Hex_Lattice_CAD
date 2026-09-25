from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter
from pylattice.instrument.types import Effect


class PersistentEffect(Effect):
    
    fader: Slot
    
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        visible = self.fader.get(now, graph.ends()[0])