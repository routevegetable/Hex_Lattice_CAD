"""Which edges count: a field that is 1 on the edge classes it names."""

from pylattice.examples.midi import FloatRange, MIDIFor, at
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, TileRef


class VGradientField(ScalarField):

    ORIGIN = FloatRange(0, 1)   # how far up the lattice the V sits

    def __init__(self, midi: MIDIFor, origin: int):
        self._origin_cc = midi.cc(origin, "origin", meta=self.ORIGIN)

    def get(self, now: Event, end: EndRef) -> float:
        graph = end.tile.graph
        
        phys_height = graph.height * TileRef.HEIGHT

        # The knob picks a height, so it reads as a fraction of the lattice.
        origin = at(self.ORIGIN, self._origin_cc().data) * phys_height

        _x, y = end.vertex().physical()

        if y >= origin:
            return (y - origin) / (phys_height - origin)
        else:
            return (origin - y) / origin
