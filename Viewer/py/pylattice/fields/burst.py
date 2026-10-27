"""Which edges count: a field that is 1 on the edge classes it names."""

from pylattice.examples.midi import FloatRange, MIDIFor
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, Graph


class BurstField(ScalarField):
    """
    A number of ends are 'lit up' randomly each note press, and decay.
    """

    MIN_DECAY_MS = 100
    MAX_DECAY_MS = 2000
    DECAY = FloatRange(MIN_DECAY_MS, MAX_DECAY_MS, "ms")

    def __init__(self, graph: Graph, midi: MIDIFor, note: int, decay: int):
        self._graph = graph
        self._note = midi.note(note, "trigger")
        self._decay = midi.cc(decay, "decay", meta=self.DECAY)
        self._latches = {end: EventLatch(0) for end in graph.ends()}


    def get(self, now: Event, end: EndRef) -> float:

        latch = self._latches[end]

        n = self._note()
        if n:
            # On note press, get a random number 
            press, _ = n
            r = press.rand(end.__hash__()) % 100
            #print(r)
            latch.latch(press, r < 10)
            #latch.latch(n, press)
            #print("latch")

        decay = self.DECAY.at(self._decay().data)
        

        v = sweep(now, latch.read(), decay, 1, 0, 0)


        #print(f"v: {v}")
        return v
