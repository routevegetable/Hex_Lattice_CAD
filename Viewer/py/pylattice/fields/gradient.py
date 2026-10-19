"""Which edges count: a field that is 1 on the edge classes it names."""

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, TileRef


class VGradientField(ScalarField):

    def __init__(self, midi: MIDIFor, origin: int):
        self._origin_cc = midi.cc(origin, "origin")

    def get(self, now: Event, end: EndRef) -> float:
        graph = end.tile.graph
        
        phys_height = graph.height * TileRef.HEIGHT

        # The knob picks a height, so it reads as a fraction of the lattice.
        origin = self._origin_cc().data / 127 * phys_height

        _x, y = end.vertex().physical()

        if y >= origin:
            return (y - origin) / (phys_height - origin)
        else:
            return (origin - y) / origin
