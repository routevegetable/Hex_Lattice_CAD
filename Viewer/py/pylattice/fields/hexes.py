# a selection of hexes across the lattice

import itertools
from collections.abc import Iterator

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, HexRef


def _hex_ends(hex_ref: HexRef) -> set[EndRef]:
    ends: set[EndRef] = set()
    for end in hex_ref.ends():
        ends.add(end)
        ends.add(end.other())
    return ends


def outer_bounce(graph: Graph) -> Iterator[tuple[int, int]]:
    """Bottom, then the top full row - skipping the interstitial one between
    them - and back down, scooting over one column with each hop."""
    top = 2 * (graph.height - 1)
    for x in range(graph.width):
        yield (x, 0 if x % 2 == 0 else top)


def _next_nonadjacent(
    graph: Graph, from_hex: tuple[int, int], row: int
) -> tuple[int, int]:
    """The first hex on `row`, searching forward from from_hex's column,
    that doesn't touch from_hex."""
    width = graph.width
    for step in range(width):
        candidate = ((from_hex[0] + step) % width, row)
        if not graph.HEX.is_adjacent(from_hex, candidate):
            return candidate
    raise ValueError("lattice too narrow to place a non-adjacent hex")


def _bounce_rows(top: int) -> Iterator[int]:
    """0, 1, ..., top, top - 1, ..., 0, 1, ... forever."""
    y, direction = 0, 1
    while True:
        yield y
        if y + direction < 0 or y + direction > top:
            direction = -direction
        y += direction


def sparse_climb(graph: Graph) -> Iterator[tuple[int, int]]:
    """Lowest, then middle, then upper, then back down via middle to lower,
    and so on - each pick skipping past the previous one's neighbors, so the
    zigzag spirals around the rig as it bounces between top and bottom."""
    top = 2 * (graph.height - 1)
    rows = _bounce_rows(top)

    current = (0, next(rows))
    yield current

    for row in itertools.islice(rows, graph.width - 1):
        current = _next_nonadjacent(graph, current, row)
        yield current


class HexesField(ScalarField):
    """A mask: 1 on every end inside the hexes a pattern selects, 0 elsewhere."""

    PATTERNS = [outer_bounce, sparse_climb]

    def __init__(self, graph: Graph, midi: MIDIFor, *, pattern: int):
        self._graph = graph
        self._pattern_cc = midi.cc(pattern, "pattern")

        self._built_idx: int | None = None
        self._ends: set[EndRef] = set()

    def _rebuild(self):
        idx = min(self._pattern_cc().data, len(self.PATTERNS) - 1)
        if idx == self._built_idx:
            return

        ends: set[EndRef] = set()
        for x, y in self.PATTERNS[idx](self._graph):
            ends |= _hex_ends(self._graph.HEX[x, y])

        self._ends = ends
        self._built_idx = idx

    def get(self, now: Event, end: EndRef) -> float:
        self._rebuild()
        return 1.0 if end in self._ends else 0.0
