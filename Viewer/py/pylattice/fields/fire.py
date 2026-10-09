"""Fire climbing the lattice from the bottom."""
from collections.abc import Iterator

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, periodic
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, VertexClass, VertexRef


class FireField(ScalarField):
    """
    Fire rising from the bottom of the lattice, always going.

    Every vertex along the bottom is an ember, throwing a particle upward
    every so often. How often is how hard the pad is being leaned on: nothing
    at rest, every ember on every tick at full pressure. It is not gated by
    the note - the pad is a dimmer, not a trigger.

    Which way a particle goes is the lattice's business. At a CDE or an ABF
    there is an edge going straight up, so it takes it. At a DEF or an ABC
    there is not - only a pair of diagonals - so it picks one at random and
    leans that way. Either way the step climbs exactly one row of vertices,
    four rows to a tile, which is how a particle knows when it has reached the
    top: it has nowhere left to go and goes out, rather than coming back round
    at the bottom.

    Nothing about a particle is stored. Embers throw on a fixed grid of ticks,
    and which ticks they threw on - and which way each one leaned - comes out
    of the tick's own `rand`. Turning the pressure up fills in more of the
    same grid rather than moving what is already in the air.

    CC:
        * note - aftertouch on this pad sets how often the embers throw
    """

    # The vertices with an edge going straight up out of them.
    UP = (VertexClass.CDE, VertexClass.ABF)

    SPAWN = 100         # ms between an ember's chances to throw one
    SPEED = 90          # ms a particle takes to climb one edge
    TAIL = 3.0          # edges of trail behind the head

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int):
        self._pressure = midi.polytouch(note, "rate")

        # The bottom row: the DEF of each tile along the bottom, which is the
        # lowest vertex there is.
        self._embers: list[VertexRef] = [graph.TILE[x, 0].vertex(VertexClass.DEF)
                                         for x in range(graph.width)]

        # Four vertex rows to a tile, and every step up crosses one of them.
        self._rows = graph.height * 4

        # How far back to look for particles still in the air.
        self._slots = self._rows * self.SPEED // self.SPAWN + 2

        self._state: dict[EndRef, float] = {}
        self._generated: int | None = None

    def _climb(self, ev: Event, ember: int) -> Iterator[EndRef]:
        """The ends a particle visits on its way up, in order."""
        vertex = self._embers[ember]

        for step in range(self._rows - 1):
            ends = vertex.ends_cw()         # index 0 is always the vertical

            if vertex.vertex_class in self.UP:
                end = ends[0]
            else:
                # The vertical here points down, so it is one diagonal or the
                # other. Decided by the throw, so a particle never wavers.
                end = ends[1 + ev.rand(ember * 1000 + step) % 2]

            yield end
            vertex = end.other().vertex()

    def _level(self, at: float, head: float) -> float:
        """How bright a point on the path is - a trail behind the head, going
        thinner the higher it has got."""
        behind = head - at

        if behind < 0 or behind >= self.TAIL:
            return 0.0                      # ahead of it, or long past

        return (1 - behind / self.TAIL) * max(0.0, 1 - at / self._rows)

    def _regen(self, now: Event):
        """Work out every particle in the air. Once a frame."""
        if now.when == self._generated:
            return

        self._generated = now.when
        self._state = {}

        chance = self._pressure() / 127

        if chance <= 0:
            return                          # nobody leaning on it

        for ember in range(len(self._embers)):
            # Embers are offset against each other, or the whole bottom row
            # would throw in step.
            offset = ember * self.SPAWN // len(self._embers)
            latest = periodic(now, self.SPAWN, offset)

            for back in range(self._slots):
                ev = Event(when=latest.when - back * self.SPAWN, data=None)

                if ev.rand(ember) % 100 >= chance * 100:
                    continue                # this ember let that tick pass

                head = (now.when - ev.when) / self.SPEED

                for i, end in enumerate(self._climb(ev, ember)):
                    if i > head:
                        break               # the rest is above the head

                    # An edge is entered before it is left, so its far end sits
                    # half a step further up the path.
                    for at, lit in ((i, end), (i + 0.5, end.other())):
                        level = self._level(at, head)

                        if level > 0:
                            self._state[lit] = max(level, self._state.get(lit, 0.0))

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)
