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

    # How long a lit end takes to come up before it starts falling again. At
    # 0 it is on the moment the note lands, which is how it always was.
    ATTACK = FloatRange(0, 500, "ms")

    def __init__(self, graph: Graph, midi: MIDIFor, note: int, decay: int, attack: int):
        self._graph = graph
        self._note = midi.note(note, "trigger")
        self._decay = midi.cc(decay, "decay", meta=self.DECAY)
        self._attack = midi.cc(attack, "attack", meta=self.ATTACK)
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
        attack = self.ATTACK.at(self._attack().data)

        lit = latch.read()

        if lit is None:
            return 0.0              # this end has never been picked

        # Up, then down from wherever the climb finished. Taking the lower of
        # the two is what joins them: the fall waits at 1 until the rise is
        # over, and the rise sits at 1 once it is.
        rise = 1.0 if attack <= 0 else sweep(now, lit, attack, 0, 1, 0)
        fall = sweep(now, lit.delay(int(attack)), decay, 1, 0, 1)

        return min(rise, fall)
