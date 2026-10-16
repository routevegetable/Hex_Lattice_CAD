"""Fire climbing the lattice from the bottom."""
from collections.abc import Iterator

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, periodic
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, VertexClass, VertexRef


class TilePattern(ScalarField):
    """
    Horizontally tile a pattern across the grid.
    The pattern has a trace running around it.
    CC to select the pattern.
    Note to 'shift' the pattern in some pattern-specific way.
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

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)
