"""A value sweeping round the lattice, left to right, for ever."""

from pylattice.examples.colors import vary
from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef


class RotaryField(ScalarField):

    def __init__(self, graph: Graph, midi: MIDIFor, *, period: int, parts: int, shape: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period, "period") # How long to do one rotation (0.5 sec at 0, 16 sec at 127)
        self._parts = midi.cc(parts, "parts") # How many parts
        self._shape = midi.cc(shape, "shape") # What wave shape
    
    def get(self, now: Event, end: EndRef) -> float:
        v = end.vertex()
        offset = v.physical()[0] / (TileRef.WIDTH * self._width) # we are here between 0 -> 1
        #print(v.physical(), offset)
        # 0.5s a rotation at 0 up to 16s at 127, a constant ratio per step.
        # Doubling per CC step ran off the end of the knob by about step 5.
        period = 500 * (16000 / 500) ** (self._period().data / 127)
        return vary(now, 0, 1, period, offset)
